import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
from queue import Queue
import statistics
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4
import winreg

from everything_search.instance import Manager, Settings
from everything_search.ipc import IpcClient, Native


ROOT = Path(__file__).resolve().parents[4]


def registry_snapshot():
	def read(path):
		try:
			with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
				children, values, _ = winreg.QueryInfoKey(key)
				return (tuple(winreg.EnumValue(key, index) for index in range(values)),
					tuple((name, read(path + '\\' + name)) for name in
						(winreg.EnumKey(key, index) for index in range(children))))
		except FileNotFoundError:
			return None
	return read(r'Software\voidtools')


def file_snapshot(directory):
	if not directory.exists():
		return ()
	return tuple(sorted((str(path.relative_to(directory)), path.stat().st_size,
		path.stat().st_mtime_ns) for path in directory.rglob('*') if path.is_file()))


def run(executable, repeat=30):
	local = ROOT / 'UserSettings' / 'Local'
	local.mkdir(parents=True, exist_ok=True)
	native = Native()
	unnamed = native.find('EVERYTHING_TASKBAR_NOTIFICATION', None)
	unnamed_identity = native.identity(unnamed) if unnamed else None
	registry_before = registry_snapshot()
	binary_before = file_snapshot(executable.parent)
	appdata = Path(os.environ['APPDATA']) / 'Everything'
	appdata_before = file_snapshot(appdata)
	instance = 'RFM_Smoke_' + uuid4().hex
	with TemporaryDirectory(prefix='EverythingSmoke-', dir=local) as temporary:
		base = Path(temporary)
		first = base / 'Folder, with space \u00e9'
		second = base / 'Second'
		first.mkdir()
		second.mkdir()
		(first / 'sample \u00e9.txt').write_text('sample', encoding='utf-8')
		(first / 'zero.txt').touch()
		(first / 'folder.txt').mkdir()
		(second / 'other.txt').write_text('other', encoding='utf-8')
		settings = Settings(folders=(str(first), str(base / 'Offline')),
			executable=str(executable), instance=instance, query_timeout_ms=500)
		notifications = Queue()
		client = IpcClient()
		manager = Manager(base / 'State', executable, notifications.put, prepare=client.start)

		def activate(desired, force=False):
			requested = manager.request(desired, force)
			state = notifications.get(timeout=35)
			assert state.generation == requested.generation, state
			assert state.status == ('ready' if desired.folders else 'stopped'), state
			return state

		def query(text):
			state = manager.snapshot()
			return client.query(instance, state.identity, text, timeout_ms=500)

		try:
			activate(settings)
			result = query('ext:txt')
			assert result.total == 2, result
			assert any(hit.path.endswith('zero.txt') and hit.size == 0 for hit in result.hits)
			folder = query('folder: folder.txt').hits[0]
			assert folder.is_folder
			sample = query('sample').hits[0]
			assert sample.path.endswith('sample \u00e9.txt') and sample.size == 6
			assert sample.modified_ns and sample.highlight
			assert ''.join(sample.path[index] for index in sample.highlight) == 'sample'
			timings = []
			for _ in range(repeat):
				started = perf_counter()
				assert query('ext:txt').total == 2
				timings.append((perf_counter() - started) * 1000)
			median = statistics.median(timings)
			assert median < 5, median
			activate(replace(settings, folders=(str(second),)))
			assert query('sample').total == 0
			assert query('other').hits[0].path == str(second / 'other.txt')
			activate(replace(settings, folders=()))
			assert not native.find_instance(instance)
			(first / 'created while stopped.txt').touch()
			activate(settings)
			assert query('"created while stopped"').total == 1
			activate(replace(settings, exit_with_application=False), force=True)
			identity = manager.snapshot().identity
			manager.close()
			assert native.identity(native.find_instance(instance)) == identity
			manager = Manager(base / 'State', executable, notifications.put, prepare=client.start)
			activate(settings)
			assert manager.snapshot().identity == identity, 'Unchanged owned instance was restarted'
			assert query('sample').total == 1
			record = {'version': '1.4.1.1032', 'repeat': repeat,
				'median_ms': median, 'milliseconds': timings,
				'checks': ['metadata', 'highlights', 'Unicode and comma roots',
					'offline root retained', 'root replacement', 'empty-root shutdown',
					'changes while stopped', 'owned orphan recovery', 'unchanged owned instance reused']}
		finally:
			client.close()
			manager.close()
		assert not manager._thread.is_alive()
		assert not client._thread.is_alive()
		assert not native.find_instance(instance)
	assert native.find('EVERYTHING_TASKBAR_NOTIFICATION', None) == unnamed
	if unnamed:
		assert native.identity(unnamed) == unnamed_identity
	assert registry_snapshot() == registry_before, 'voidtools Registry settings changed'
	assert file_snapshot(appdata) == appdata_before, 'Everything AppData files changed'
	assert file_snapshot(executable.parent) == binary_before, 'Executable directory changed'
	(local / 'EverythingSmokeResults.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
	print('PASS: production IPC, folder management, owned recovery and clean shutdown')
	print('PASS: unnamed instance, executable directory, AppData and voidtools Registry unchanged')
	print(f'Warm IPC: {repeat} queries, median {median:.3f} ms')


def main():
	parser = argparse.ArgumentParser(description='Isolated Everything portable runtime smoke test')
	parser.add_argument('--exe', type=Path,
		default=ROOT / 'src/main/resources/base/Plugins/Everything/bin/Everything.exe')
	parser.add_argument('--repeat', type=int, default=30)
	arguments = parser.parse_args()
	if not arguments.exe.is_file():
		parser.error('Portable Everything is missing; provision it with build._ensure_everything().')
	if arguments.repeat < 1:
		parser.error('--repeat must be positive')
	run(arguments.exe.resolve(), arguments.repeat)


if __name__ == '__main__':
	main()