import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter
import traceback


def exercise(context, root, output, layout_only=False):
	from fman.impl.ui.facade import _hosts
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.url import as_url
	from PyQt5.QtCore import QPoint, Qt, QTimer
	from PyQt5.QtWidgets import QApplication, QLabel
	from search_files import SearchFiles, SearchUI
	gui = lambda function: run_in_main_thread(function)()
	def wait_for(predicate, message):
		ready = Event()
		def connect():
			timer = QTimer(context.main_window)
			timer.setInterval(10)
			def check():
				if predicate():
					timer.stop()
					timer.deleteLater()
					ready.set()
			timer.timeout.connect(check)
			timer.start()
			check()
		gui(connect)
		assert ready.wait(15), message
	code = 1
	try:
		wait_for(lambda: len(context.window.get_panes()) == 2 and all(
			pane.get_path() == as_url(str(root)) for pane in context.window.get_panes()), 'Startup panes did not restore')
		pane = context.window.get_panes()[0]
		assert pane.get_command_aliases('search_files')[0] == 'Search files'
		assert 'search_file_content' in pane.get_commands(), 'Legacy search binding is unavailable'
		bindings = context.key_bindings.get_sanitized_bindings()
		assert next(binding for binding in bindings if binding['keys'] == ['Alt+F7'])['command'] == 'search_files'
		pane.run_command('search_files')
		wait_for(lambda: any(host.owner is SearchUI.owner for host in _hosts.values()), 'Search files panel did not open')
		host = gui(lambda: next(host for host in _hosts.values() if host.owner is SearchUI.owner))
		session = host.on_action.__self__
		assert not gui(host.isVisible), 'Panel coordinator was shown'
		assert session.panel.snapshot()['root'] == str(root)
		other = context.window.get_panes()[1]
		other.set_path(as_url(str(root / 'nested')))
		wait_for(lambda: other.get_path() == as_url(str(root / 'nested')), 'Other pane did not navigate')
		assert session.root == str(root), 'Other pane changed the search root'
		pane.set_path(as_url(str(root / 'nested')))
		wait_for(lambda: session.root == str(root / 'nested'), 'Search root did not follow its pane')
		pane.set_path(as_url(str(root)))
		wait_for(lambda: session.root == str(root), 'Search root did not return with its pane')
		def stop_is_red():
			button = host.controls['stop'][1]
			image = button.grab().toImage()
			return any(image.pixelColor(horizontal, vertical).red() > 180
				and image.pixelColor(horizontal, vertical).green() < 120
				and image.pixelColor(horizontal, vertical).blue() < 120
				for horizontal in range(image.width()) for vertical in range(image.height()))
		def geometry():
			main = context.main_window
			main.activateWindow()
			indicator = host.form.findChild(QLabel, 'panel-label-icon')
			expected_pane = 'Left pane' if pane is context.window.get_panes()[0] else 'Right pane'
			assert indicator.toolTip() == expected_pane, 'Wrong pane icon tooltip'
			assert not indicator.pixmap().isNull() and indicator.pixmap().width() >= 20, 'Missing or undersized pane icon'
			for width in (960, 1280, 1440):
				main.resize(width, 720)
				QApplication.processEvents()
				assert main.width() == width, 'Panel prevented the requested window width'
				fields = [host.controls[name][1] for name in ('name', 'content')]
				assert fields[0].mapTo(host.form, QPoint()).x() == fields[1].mapTo(host.form, QPoint()).x(), 'Pattern fields are not aligned'
				assert fields[0].width() == fields[1].width() <= 480, 'Pattern fields exceed their width cap'
				for name in ('name_mode', 'content_mode'):
					control = host.controls[name][1]
					buttons = control.group.buttons()
					assert len(buttons) == 3 and sum(button.isChecked() for button in buttons) == 1, 'Invalid mode selection'
					images = [button.icon().pixmap(16, 16).toImage() for button in buttons]
					assert all(any(image.pixelColor(horizontal, vertical).alpha() for horizontal in range(16) for vertical in range(16)) for image in images), 'Blank mode icon'
					assert images[0] != images[1] and images[1] != images[2] and images[0] != images[2], 'Mode icons are not distinct'
					assert control.mapTo(host.form, QPoint(control.width(), 0)).x() <= host.form.width(), 'Clipped mode buttons'
				controls = [host.controls[name][1] for name in ('name_mode', 'content_mode', 'recursive')]
				assert len({control.mapTo(host.form, QPoint()).x() for control in controls}) == 1, 'Search controls are not aligned with modes'
				buttons = [host.controls[name][1] for name in ('recursive', 'search', 'stop')]
				centers = [button.mapTo(host.form, button.rect().center()).y() for button in buttons]
				assert max(centers) - min(centers) <= 1, 'Search actions are not on one row'
				assert buttons[-1].mapTo(host.form, buttons[-1].rect().topRight()).x() < host.form.width(), 'Clipped search actions'
				button_rows = [host.controls[name][1].group.buttons() for name in ('name_mode', 'content_mode')] + [buttons]
				for row in button_rows:
					assert all(button.width() == button.height() == 28 and button.toolTip() for button in row), 'Unequal or unlabeled icon buttons'
					positions = [button.mapTo(host.form, QPoint()).x() for button in row]
					assert positions == [buttons[0].mapTo(host.form, QPoint()).x() + 31 * index for index in range(3)], 'Button columns or 3px spacing do not match'
				assert all(not host.controls[name][1].text() for name in ('search', 'stop')), 'Action labels are still visible'
				assert buttons[-1].isEnabled() and stop_is_red(), 'Stop must remain enabled and red'
				before = session.panel.snapshot()
				buttons[-1].click()
				assert session.runner is None and before == session.panel.snapshot(), 'Idle Stop was not a no-op'
				assert main._splitter.height() > 150, 'Dock consumed pane area'
				assert main._panel_dock.height() <= 180, 'Search dock is too tall'
				main._panel_dock.grab().save(str(output.with_name(output.stem + '-panel-%d.png' % width)))
				print('Panel geometry:', width, main._panel_dock.height(), flush=True)
			main.resize(960, 720)
		gui(geometry)
		if layout_only:
			session.panel.close()
			pane = other
			SearchFiles(pane)()
			host = gui(lambda: next(host for host in _hosts.values() if host.owner is SearchUI.owner))
			session = host.on_action.__self__
			output = output.with_name(output.stem + '-right.png')
			gui(geometry)
			print('PASS: layout only, both pane icons, 3x3 buttons, 3px gaps and idle Stop', flush=True)
			code = 0
			return
		gui(lambda: host.controls['name_mode'][1].group.button(2).click())
		gui(lambda: host.controls['content_mode'][1].group.button(1).click())
		settings = root / 'UserSettings/Plugins/User/Settings/SearchFiles (Windows).json'
		wait_for(lambda: not session.saving, 'Search preferences did not settle')
		saved = json.loads(settings.read_text(encoding='utf-8'))
		assert saved['name_mode'] == 'regex' and saved['content_mode'] == 'glob'
		assert not {'name_regex', 'content_regex', 'name', 'content'} & saved.keys()
		gui(lambda: session.panel.update(values={'name': 'report\\.txt$', 'content': '*needle*'}))
		started = perf_counter()
		def search():
			session.action('search', session.panel.snapshot())
			assert all(not button.isEnabled() for name in ('name_mode', 'content_mode') for button in host.controls[name][1].group.buttons()), 'Mode changed during search'
			stop = host.controls['stop'][1]
			assert stop.isEnabled() and stop_is_red(), 'Stop icon did not remain enabled and red'
			context.main_window._panel_dock.grab().save(str(output.with_name(output.stem + '-panel-running.png')))
		gui(search)
		wait_for(lambda: session.runner is None and session.table is not None, 'Search did not finish')
		assert gui(lambda: host.controls['stop'][1].isEnabled()), 'Completed search disabled Stop'
		window = gui(lambda: host.table_window)
		wait_for(window.isVisible, 'Results did not become visible')
		assert gui(window.windowTitle) == 'Search files', 'Incorrect results title'
		assert session.table.current_cell[0].value.line == 2
		assert not gui(host.activity_timer.isActive), 'Progress timer leaked'
		gui(lambda: setattr(session.table, 'filter_text', 'txt'))
		wait_for(lambda: tuple(window.table.model.index(0, 0).data(Qt.UserRole + 1) or ()) == (14, 15, 16), 'Extension highlight is not contiguous')
		gui(lambda: window.grab().save(str(output)))
		print('Search-to-visible seconds:', round(perf_counter() - started, 3), flush=True)
		target = root / 'nested' / 'report.txt'
		table = session.table
		gui(lambda: window.activate_cell(*table.current_cell))
		wait_for(lambda: not table.is_open, 'Tracked navigation did not close modal')
		wait_for(lambda: pane.get_path() == as_url(str(target.parent)) and
			pane.get_file_under_cursor() == as_url(str(target)), 'Target file was not highlighted')
		assert session.panel.is_open
		assert session.table is None
		assert gui(lambda: host.controls['search'][1].isEnabled()), 'Search remained locked after results closed'
		assert session.root == str(target.parent), 'Root did not follow successful result navigation'
		session.panel.close()
		assert gui(lambda: context.main_window._panel_dock is None)
		SearchFiles(pane)()
		reopened = gui(lambda: next(host for host in _hosts.values() if host.owner is SearchUI.owner)).on_action.__self__
		assert reopened.panel.snapshot()['name_mode'] == 'regex'
		assert reopened.panel.snapshot()['content_mode'] == 'glob'
		reopened.panel.close()
		print('PASS: native startup, mode icons/persistence, glob search, layout, modal and file navigation', flush=True)
		code = 0
	except BaseException:
		traceback.print_exc()
	finally:
		SearchUI.owner.invalidate()
		gui(lambda: context.app.exit(code))


def benchmark():
	from unittest.mock import patch
	from search_files.engine import Child, Options, Runner, resolve_engine
	from win32api import GetCurrentProcess
	from win32process import GetProcessMemoryInfo
	with TemporaryDirectory(prefix='file-search-benchmark-') as temporary:
		root = Path(temporary)
		fixture_bytes = 0
		for directory in range(100):
			folder = root / ('folder-%03d' % directory)
			folder.mkdir()
			for index in range(1000):
				content = b'needle\n' if index == 0 else b'ordinary text\n'
				(folder / ('file-%04d.txt' % index)).write_bytes(content)
				fixture_bytes += len(content)
		binary = resolve_engine()
		reports = []
		for regex in (False, True):
			runner = Runner(Options(str(root), 'needle', '^file-0000\\.txt$' if regex else '*.txt', name_regex=regex))
			starts, first_hit = [], []
			child_peak = []
			original_init, original_finish, original_accept = Child.__init__, Child.finish, runner.collector.accept
			started = perf_counter()
			def record_start(child, supervisor, arguments, data):
				starts.append(tuple(arguments))
				return original_init(child, supervisor, arguments, data)
			def record_hit(message):
				if message['type'] == 'match' and not first_hit:
					first_hit.append(perf_counter() - started)
				return original_accept(message)
			def record_finish(child, *args, **kwargs):
				try:
					child_peak.append(GetProcessMemoryInfo(child.process._handle)['PeakWorkingSetSize'])
				finally:
					result = original_finish(child, *args, **kwargs)
				return result
			runner.collector.accept = record_hit
			with patch.object(Child, '__init__', record_start), patch.object(Child, 'finish', record_finish):
				result = runner.run()
			elapsed = perf_counter() - started
			assert result.status == 'Complete' and len(result.rows) == 100, result
			reports.append({'mode': 'filename-regex' if regex else 'glob', 'files': 100000,
				'fixture_bytes': fixture_bytes, 'hits': len(result.rows), 'seconds': elapsed,
				'first_hit_seconds': first_hit[0], 'process_starts': len(starts),
				'host_peak_working_set_bytes': GetProcessMemoryInfo(GetCurrentProcess())['PeakWorkingSetSize'],
				'largest_child_peak_working_set_bytes': max(child_peak, default=0),
				'cache': 'warm after fixture creation; OS cache not flushed'})
		runner = Runner(Options(str(root), 'needle', '*.txt'))
		runner.engine = binary
		started = perf_counter()
		subprocess.run(runner.content_args() + ['--iglob', '*.txt', '--', str(root)],
			stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
		reports.append({'mode': 'direct-rg', 'seconds': perf_counter() - started})
		output = Path('target/search-files-benchmark.json')
		output.parent.mkdir(parents=True, exist_ok=True)
		output.write_text(json.dumps(reports, indent=2), encoding='utf-8')
		print(json.dumps(reports, indent=2), flush=True)
	return 0


def main():
	if '--benchmark' in sys.argv:
		return benchmark()
	layout_only = '--layout-only' in sys.argv
	with TemporaryDirectory(prefix='file-search-smoke-') as temporary:
		root = Path(temporary)
		(root / 'nested').mkdir()
		(root / 'nested/report.txt').write_text('first line\nneedle content\n', encoding='utf-8')
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(root / 'UserSettings')
		from fman.impl.application_context import get_application_context
		from PyQt5.QtCore import QTimer
		context = get_application_context()
		_ = context.app
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(root), str(root)]
		output = Path(os.environ.get('SEARCH_FILES_SMOKE_IMAGE', 'target/search-files-source.png')).resolve()
		output.parent.mkdir(parents=True, exist_ok=True)
		QTimer.singleShot(0, lambda: Thread(target=exercise, args=(context, root, output, layout_only), daemon=True).start())
		return context.run()


if __name__ == '__main__':
	sys.exit(main())