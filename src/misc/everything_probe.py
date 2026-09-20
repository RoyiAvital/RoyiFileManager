"""Probe voidtools Everything as a search backend for RoyiFileManager.

Runs a portable Everything 1.4 as a *named* background instance with standard
privileges and folder indexing only (no NTFS/ReFS volume indexing, no admin),
queries it over the built-in loopback HTTP JSON API, and reports index build
time, memory, per-query latency and instance isolation. Nothing is written
beside the Everything executable; settings and the database live in the work
directory, which mirrors how the application would use `UserSettings`.

Standard library only. Requires an Everything 1.4 executable (1.5 moved the
HTTP server into a separate plugin). Everything prints nothing to the console
and opens an options window on any unknown switch, so only 1.4 switches are
used here. The user's own (unnamed) Everything instance may be running; the
`--collision` check verifies both instances coexist and that ours leaves the
user's process and `Everything.ini` untouched.

Examples, from the repository root:

    python src/misc/everything_probe.py --exe D:\\Tools\\Everything\\Everything.exe
    python src/misc/everything_probe.py --exe ... --folders C:\\Users\\me D:\\Data
    python src/misc/everything_probe.py --exe ... --all-drives --build-timeout 1800
    python src/misc/everything_probe.py --exe ... --collision

Results recorded on 2026-09-20 are summarized in Plan/FindFiles003.md.
"""
import argparse
import ctypes
import http.client
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time
import urllib.parse

DEFAULT_QUERIES = [
	'rea', '*.dll', 'ext:dll size:>1mb', 'dm:lastmonth', r'regex:^rep.*\.py$',
	'notepad | calc', '"annual report"', 'wholeword:cache', '',
]


def parse_args():
	parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
	parser.add_argument('--exe', required=True, help='Everything 1.4 executable')
	parser.add_argument('--instance', default='RoyiFileManager')
	parser.add_argument('--port', type=int, default=51873)
	parser.add_argument('--work-dir', default='target/everything-probe')
	parser.add_argument('--folders', nargs='*', help='folder indexes; default: repository root and %%WINDIR%%')
	parser.add_argument('--all-drives', action='store_true', help='folder-index every fixed drive root')
	parser.add_argument('--collision', action='store_true', help='also verify coexistence with a running unnamed instance')
	parser.add_argument('--repeat', type=int, default=30)
	parser.add_argument('--count', type=int, default=100, help='results per query')
	parser.add_argument('--startup-timeout', type=float, default=60)
	parser.add_argument('--build-timeout', type=float, default=600)
	parser.add_argument('--keep', action='store_true', help='keep the work directory (ini and database)')
	return parser.parse_args()


def fixed_drives():
	kernel = ctypes.windll.kernel32
	mask = kernel.GetLogicalDrives()
	return ['%s:\\' % chr(65 + i) for i in range(26) if mask >> i & 1 and kernel.GetDriveTypeW('%s:\\' % chr(65 + i)) == 3]


def everything_windows():
	user32 = ctypes.windll.user32
	found = set()
	@ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
	def callback(hwnd, _):
		name = ctypes.create_unicode_buffer(256)
		user32.GetClassNameW(hwnd, name, 256)
		if name.value.startswith('EVERYTHING_TASKBAR_NOTIFICATION'):
			pid = ctypes.c_ulong()
			user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
			found.add((name.value, pid.value))
		return True
	user32.EnumWindows(callback, 0)
	return sorted(found)


def everything_pids():
	output = subprocess.run(
		['powershell', '-NoProfile', '-Command', '(Get-Process -Name Everything* -ErrorAction SilentlyContinue).Id'],
		capture_output=True, text=True).stdout.split()
	return sorted(int(pid) for pid in output)


def working_set_mib(pid):
	output = subprocess.run(
		['powershell', '-NoProfile', '-Command', '(Get-Process -Id %d).WorkingSet64' % pid],
		capture_output=True, text=True).stdout.strip()
	return int(output) / 2 ** 20 if output.isdigit() else float('nan')


def write_ini(path, folders, port, work_dir):
	lines = [
		'[Everything]', 'app_data=0', 'run_as_admin=0', 'show_tray_icon=0', 'run_in_background=1',
		'check_for_updates_on_startup=0', 'search_history_enabled=0', 'run_history_enabled=0',
		'auto_include_fixed_volumes=0', 'auto_include_removable_volumes=0',
		'auto_include_fixed_refs_volumes=0', 'auto_include_removable_refs_volumes=0',
		'folders=' + ','.join(folders), 'folder_monitor_changes=' + ','.join('1' for _ in folders),
		'folder_update_thread_mode_background=1', 'db_update_thread_priority=-1',
		'db_location=' + str(work_dir), 'index_size=1', 'index_date_modified=1', 'index_date_created=0',
		'allow_http_server=1', 'http_server_enabled=1', 'http_server_bindings=127.0.0.1',
		'http_server_port=%d' % port, 'http_server_allow_file_download=0', 'http_server_logging_enabled=0',
	]
	path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


class Client:
	def __init__(self, port):
		self.port = port

	def query(self, text, count=100, timeout=5.0):
		params = urllib.parse.urlencode({
			's': text, 'j': 1, 'c': count, 'path_column': 1, 'size_column': 1,
			'date_modified_column': 1, 'sort': 'name'})
		connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
		try:
			connection.request('GET', '/?' + params)
			response = connection.getresponse()
			body = response.read()
		finally:
			connection.close()
		if response.status != 200:
			raise OSError('HTTP %d' % response.status)
		return json.loads(body)

	def total(self):
		return self.query('', count=1)['totalResults']


def wait_for_http(client, timeout):
	deadline = time.perf_counter() + timeout
	while True:
		try:
			return client.total()
		except (OSError, ConnectionError, json.JSONDecodeError):
			if time.perf_counter() > deadline:
				raise SystemExit('Everything HTTP server did not start within %.0f s.' % timeout)
			time.sleep(0.1)


def wait_for_index(client, started, timeout, settle=15.0):
	last, since, milestones = -1, None, []
	while time.perf_counter() - started < timeout:
		total = client.total()
		now = time.perf_counter() - started
		if total != last:
			milestones.append((round(now, 1), total))
			last, since = total, now
		elif total > 0 and now - since >= settle:
			return since, milestones
		time.sleep(1.0)
	return None, milestones


def main():
	args = parse_args()
	exe = pathlib.Path(args.exe)
	if not exe.is_file():
		raise SystemExit('Everything executable not found: %s' % exe)
	work_dir = pathlib.Path(args.work_dir).resolve()
	work_dir.mkdir(parents=True, exist_ok=True)
	for stale in work_dir.iterdir():
		stale.unlink()
	ini = work_dir / ('Everything-%s.ini' % args.instance)
	if args.all_drives:
		folders = fixed_drives()
	elif args.folders:
		folders = [str(pathlib.Path(folder).resolve()) for folder in args.folders]
	else:
		folders = [str(pathlib.Path('.').resolve()), os.environ['WINDIR']]
	write_ini(ini, folders, args.port, work_dir)
	exe_ini = exe.with_name('Everything.ini')
	exe_ini_before = exe_ini.stat().st_mtime_ns if exe_ini.exists() else None
	pids_before, windows_before = everything_pids(), everything_windows()
	print('folders:', folders)
	print('before launch: pids %s, windows %s' % (pids_before, windows_before))

	client = Client(args.port)
	started = time.perf_counter()
	process = subprocess.Popen(
		[str(exe), '-instance', args.instance, '-startup', '-config', str(ini)],
		creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
	try:
		wait_for_http(client, args.startup_timeout)
		print('HTTP up after %.2f s' % (time.perf_counter() - started))
		build, milestones = wait_for_index(client, started, args.build_timeout)
		total = client.total()
		state = 'complete after ~%.0f s' % build if build else 'still building at timeout'
		print('index: %s entries, %s; working set %.0f MiB' % (format(total, ','), state, working_set_mib(process.pid)))
		if len(milestones) > 2:
			print('growth: %s ... %s' % (milestones[:2], milestones[-2:]))
		print('windows after launch:', everything_windows())
		if args.collision:
			assert process.poll() is None, 'launcher exited: command line was forwarded to another instance'
			assert all(pid in everything_pids() for pid in pids_before), 'a pre-existing Everything process disappeared'

		print('%-42s %11s | %8s %8s %8s' % ('query', 'total', 'median', 'min', 'max'))
		for text in DEFAULT_QUERIES:
			times, totals = [], set()
			for _ in range(args.repeat):
				begin = time.perf_counter()
				result = client.query(text, args.count)
				times.append((time.perf_counter() - begin) * 1000)
				totals.add(result['totalResults'])
			print('%-42s %11s | %6.2f ms %6.2f ms %6.2f ms' % (
				text or '<empty>', format(max(totals), ','), statistics.median(times), min(times), max(times)))
		sample = client.query('py', count=1)['results']
		print('sample record:', json.dumps(sample[0], ensure_ascii=False) if sample else None)
	finally:
		subprocess.run([str(exe), '-instance', args.instance, '-exit'], timeout=15)
		for _ in range(150):
			if process.poll() is not None:
				break
			time.sleep(0.2)
		time.sleep(0.5)
		database = work_dir / ('Everything-%s.db' % args.instance)
		print('exited: %s | database: %s | stray ini beside exe: %s' % (
			process.poll(),
			'%.1f MiB' % (database.stat().st_size / 2 ** 20) if database.exists() else 'not saved',
			exe_ini.exists() and (exe_ini.stat().st_mtime_ns != exe_ini_before)))
		if args.collision:
			after_pids, after_windows = everything_pids(), everything_windows()
			print('collision check: user instance survived = %s, windows = %s' % (
				after_pids == pids_before and after_windows == windows_before, after_windows))
		if not args.keep:
			for leftover in work_dir.iterdir():
				leftover.unlink()
			work_dir.rmdir()


if __name__ == '__main__':
	if sys.platform != 'win32':
		raise SystemExit('Everything is a Windows program.')
	main()
