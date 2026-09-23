"""Generate public, repeatable RoyiFileManager documentation screenshots.

The source capture follows the Qt smoke-test approach and grabs widgets directly.
The packaged capture launches the frozen executable and grabs its native window.
Both use isolated settings and only show ``C:\\`` and ``C:\\Windows``.
Generated PNG files remain ignored by Git. The Pages workflow generates them
before building its deployment artifact.

Run from the repository root:

    python src/misc/generate_docs_screenshots.py
    python src/misc/generate_docs_screenshots.py --mode source
    python src/misc/generate_docs_screenshots.py --mode packaged
"""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / 'target' / 'RoyiFileManager' / 'RoyiFileManager.exe'
DEFAULT_OUTPUT_DIR = ROOT / 'docs' / 'assets'
WORK_DIR = ROOT / 'target' / 'docs-screenshots'
SOURCE_CAPTURES = (
	'overview', 'go-to', 'context-menu', 'filter-pane', 'quick-view', 'fuzzy-find',
	'search-files', 'find-files'
)
SOURCE_PATHS = (
	ROOT / 'src' / 'main' / 'python',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Core',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' /
	'SearchFileFuzzy',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Favorites',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' /
	'CalculateFileHash',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'SearchFiles',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'FindFiles',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'ProcessPane',
)


def _positive_int(value):
	result = int(value)
	if result < 1:
		raise argparse.ArgumentTypeError('must be at least 1')
	return result


def _positive_float(value):
	result = float(value)
	if result <= 0:
		raise argparse.ArgumentTypeError('must be greater than 0')
	return result


def _parse_args(argv=None):
	parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
	parser.add_argument(
		'--mode', choices=('source', 'packaged', 'all'), default='all',
		help='capture source, packaged build, or both (default: all)'
	)
	parser.add_argument(
		'--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR,
		help='output directory (default: docs/assets)'
	)
	parser.add_argument(
		'--exe', type=Path, default=DEFAULT_EXE,
		help='packaged executable used by packaged/all mode'
	)
	parser.add_argument('--width', type=_positive_int, default=1280)
	parser.add_argument('--height', type=_positive_int, default=800)
	parser.add_argument('--timeout', type=_positive_float, default=30.0)
	parser.add_argument(
		'--settle-seconds', type=_positive_float, default=2.0,
		help='packaged window settle time (default: 2)'
	)
	parser.add_argument(
		'--_source-child', action='store_true', help=argparse.SUPPRESS
	)
	parser.add_argument(
		'--_capture', choices=SOURCE_CAPTURES, default='overview',
		help=argparse.SUPPRESS
	)
	return parser.parse_args(argv)


def _public_paths():
	root = Path('C:\\')
	windows = Path(os.environ.get('WINDIR', 'C:\\Windows')).resolve()
	if windows.anchor.casefold() != root.anchor.casefold() or \
			windows.name.casefold() != 'windows':
		raise RuntimeError('WINDIR is not the expected public Windows directory')
	return root, windows


def _public_image():
	_, windows = _public_paths()
	web = windows / 'Web'
	images = sorted(
		path for path in web.rglob('*')
		if path.is_file() and path.suffix.casefold() in
			('.bmp', '.jpeg', '.jpg', '.png')
	)
	if not images:
		raise FileNotFoundError(f'No public Windows image found under {web}')
	return images[0]


def _application_version():
	settings = ROOT / 'src' / 'build' / 'settings' / 'base.json'
	return json.loads(settings.read_text(encoding='utf-8'))['version']


def _prepare_settings(name):
	directory = WORK_DIR / name / 'UserSettings'
	if directory.parent.exists():
		shutil.rmtree(directory.parent)
	local = directory / 'Local'
	local.mkdir(parents=True)
	(local / 'Session.json').write_text(
		json.dumps({
			'fman_version': _application_version(),
			'is_licensed': True,
		}, indent=2) + '\n',
		encoding='utf-8'
	)
	return directory


def _source_environment(settings):
	environment = os.environ.copy()
	environment['ROYIFILEMANAGER_USER_SETTINGS'] = str(settings)
	paths = [str(path) for path in SOURCE_PATHS]
	if environment.get('PYTHONPATH'):
		paths.append(environment['PYTHONPATH'])
	environment['PYTHONPATH'] = os.pathsep.join(paths)
	return environment


def _save_pixmap(pixmap, output):
	output.parent.mkdir(parents=True, exist_ok=True)
	if pixmap.isNull() or not pixmap.save(str(output)):
		raise RuntimeError(f'Could not save screenshot: {output}')


def _grab_window_with_dialog(window, dialog):
	from PyQt5.QtCore import QPoint
	from PyQt5.QtGui import QPainter

	pixmap = window.grab()
	dialog_position = window.mapFromGlobal(dialog.mapToGlobal(QPoint()))
	painter = QPainter(pixmap)
	try:
		painter.drawPixmap(dialog_position, dialog.grab())
	finally:
		painter.end()
	return pixmap


def _source_capture_paths(capture):
	root, windows = _public_paths()
	if capture == 'quick-view':
		return _public_image().parent, windows
	if capture == 'fuzzy-find':
		return windows / 'Web', windows
	return root, windows


def _source_outputs(output_dir, capture):
	names = {
		'overview': (
			'royifilemanager-dual-pane.png',
			'royifilemanager-command-center.png',
		),
		'go-to': ('royifilemanager-find-location.png',),
		'context-menu': ('royifilemanager-file-context-menu.png',),
		'filter-pane': ('royifilemanager-filter-pane.png',),
		'quick-view': ('royifilemanager-quickview.png',),
		'fuzzy-find': ('royifilemanager-fuzzy-find-recursive.png',),
		'search-files': (
			'royifilemanager-search-files.png',
			'royifilemanager-search-files-panel.png',
		),
		'find-files': (
			'royifilemanager-find-files-fd.png',
			'royifilemanager-find-files-fd-panel.png',
		),
	}
	return tuple(output_dir / name for name in names[capture])


def _capture_source_child(args):
	left_path, right_path = _source_capture_paths(args._capture)
	sys.argv = [sys.argv[0], str(left_path), str(right_path)]

	from fman.impl.application_context import get_application_context
	from fman.url import as_url
	from PyQt5.QtCore import QTimer
	from PyQt5.QtWidgets import QApplication

	context = get_application_context()
	expected_paths = (as_url(str(left_path)), as_url(str(right_path)))
	outputs = _source_outputs(args.output_dir, args._capture)
	deadline = time.monotonic() + args.timeout
	state = {
		'settled': 0, 'started': False, 'captured': False,
		'initial_rows': None,
	}
	errors = []

	def fail():
		errors.append(traceback.format_exc())
		context.app.exit(1)

	def finish(pixmap, output, cleanup=None):
		_save_pixmap(pixmap, output)
		if cleanup is not None:
			cleanup()
		state['captured'] = True
		QTimer.singleShot(100, context.app.quit)

	def capture_dialog(dialog):
		def capture_overview_dialog():
			try:
				output = outputs[1] if args._capture == 'overview' else outputs[0]
				finish(
					_grab_window_with_dialog(context.main_window, dialog), output
				)
				dialog.reject()
			except BaseException:
				fail()
		def capture_fuzzy_dialog():
			try:
				if not dialog._curr_items:
					raise RuntimeError('Recursive fuzzy search returned no image results')
				finish(dialog.grab(), outputs[0])
				dialog.reject()
			except BaseException:
				fail()
		QTimer.singleShot(
			150,
			capture_overview_dialog if args._capture in ('overview', 'go-to')
			else capture_fuzzy_dialog
		)

	if args._capture in ('overview', 'go-to', 'fuzzy-find'):
		context.main_window.before_dialog.connect(capture_dialog)

	def check_ready():
		try:
			if time.monotonic() >= deadline:
				raise TimeoutError(
					f'{args._capture} capture did not settle before timeout'
				)
			panes = context.window.get_panes()
			ready = (
				len(panes) == 2
				and tuple(pane.get_path() for pane in panes) == expected_paths
				and all(pane._widget._model.rowCount() > 0 for pane in panes)
			)
			if not ready:
				state['settled'] = 0
				return
			context.main_window.resize(args.width, args.height)
			QApplication.processEvents()
			if context.main_window.width() != args.width or \
					context.main_window.height() != args.height:
				return
			state['settled'] += 1
			if state['settled'] < 3:
				return
			pane = panes[1] if args._capture in \
				('context-menu', 'filter-pane', 'search-files', 'find-files') else panes[0]
			if args._capture == 'overview':
				if state['started']:
					return
				pane.focus()
				QApplication.processEvents()
				_save_pixmap(context.main_window.grab(), outputs[0])
				state['started'] = True
				pane.run_command('command_palette')
			elif args._capture == 'go-to':
				if state['started']:
					return
				state['started'] = True
				pane.focus()
				pane.run_command('go_to')
			elif args._capture == 'context-menu':
				from PyQt5.QtGui import QContextMenuEvent
				from PyQt5.QtWidgets import QMenu
				file_url = as_url(str(_public_paths()[1] / 'win.ini'))
				if state['started']:
					return
				pane.place_cursor_at(file_url)
				if pane.get_file_under_cursor() != file_url:
					return
				pane.focus()
				view = pane._widget._file_view
				index = view.currentIndex()
				view.scrollTo(index, view.PositionAtCenter)
				QApplication.processEvents()
				position = view.visualRect(index).center()
				if not view.viewport().rect().contains(position):
					return
				def capture_menu():
					try:
						menu = QApplication.activePopupWidget()
						if not isinstance(menu, QMenu) or not menu.isVisible():
							raise RuntimeError('File context menu did not open')
						finish(
							_grab_window_with_dialog(context.main_window, menu),
							outputs[0], menu.close
						)
					except BaseException:
						fail()
				state['started'] = True
				QTimer.singleShot(150, capture_menu)
				QApplication.sendEvent(
					view.viewport(), QContextMenuEvent(
						QContextMenuEvent.Mouse, position,
						view.viewport().mapToGlobal(position)
					)
				)
			elif args._capture == 'filter-pane':
				filter_bar = pane._widget._filter_bar
				if not state['started']:
					state['started'] = True
					state['settled'] = 0
					state['initial_rows'] = pane._widget._model.rowCount()
					pane.focus()
					filter_bar._input.setText('*.exe')
					filter_bar.show()
					filter_bar.reposition()
					QApplication.processEvents()
					return
				row_count = pane._widget._model.rowCount()
				if state['settled'] >= 3 and filter_bar.isVisible() and \
						filter_bar.is_active() and 0 < row_count < state['initial_rows']:
					finish(
						context.main_window.grab(), outputs[0], filter_bar.close
					)
			elif args._capture == 'quick-view':
				image_url = as_url(str(_public_image()))
				if not state['started']:
					pane.place_cursor_at(image_url)
					pane.focus()
					if pane.get_file_under_cursor() != image_url:
						return
					state['started'] = True
					pane.run_command('toggle_quick_view')
					return
				session = getattr(context.main_window, '_quick_view_session', None)
				if session is not None and session.overlay.canvas.image is not None:
					finish(
						context.main_window.grab(), outputs[0],
						lambda: pane.run_command('toggle_quick_view')
					)
			elif args._capture == 'fuzzy-find':
				if state['started']:
					return
				state['started'] = True
				pane.focus()
				pane.run_command('search_files_recursively', {'query': 'img'})
			elif args._capture in ('search-files', 'find-files'):
				from fman.impl.ui.facade import _hosts
				if not state['started']:
					pane.focus()
					pane.run_command(
						'search_files' if args._capture == 'search-files'
						else 'find_files'
					)
					state['started'] = True
					state['settled'] = 0
					return
				if args._capture == 'search-files':
					from search_files import SearchUI
					owner = SearchUI.owner
					values = {'name': '*.ini', 'content': 'fonts', 'recursive': True}
				else:
					from find_files import FindUI
					owner = FindUI.owner
					values = {
						'pattern': 'notepad*', 'extensions': 'exe',
						'max_results': 25, 'recursive': True,
					}
				host = next(
					(host for host in _hosts.values() if host.owner is owner), None
				)
				if host is None:
					return
				host.on_action.__self__.panel.update(values=values)
				QApplication.processEvents()
				if state['settled'] >= 3:
					_save_pixmap(context.main_window.grab(), outputs[0])
					finish(
						host.panel.grab(), outputs[1],
						host.on_action.__self__.panel.close
					)
		except BaseException:
			fail()

	timer = QTimer(context.main_window)
	timer.setInterval(100)
	timer.timeout.connect(check_ready)
	timer.start()
	exit_code = context.run()
	if errors:
		raise RuntimeError(errors[0])
	if not state['captured']:
		raise RuntimeError(f'{args._capture} screenshot was not captured')
	return exit_code


def _run_source(args):
	outputs = []
	for capture in SOURCE_CAPTURES:
		settings = _prepare_settings('source-' + capture)
		command = [
			sys.executable, str(Path(__file__).resolve()), '--_source-child',
			'--_capture', capture,
			'--output-dir', str(args.output_dir.resolve()),
			'--width', str(args.width), '--height', str(args.height),
			'--timeout', str(args.timeout),
		]
		subprocess.run(
			command, cwd=ROOT, env=_source_environment(settings), check=True
		)
		outputs.extend(_source_outputs(args.output_dir, capture))
	return tuple(outputs)


def _find_window(process_id, timeout):
	import win32gui
	import win32process

	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		matches = []
		def collect(handle, _):
			_, candidate_process_id = win32process.GetWindowThreadProcessId(handle)
			if candidate_process_id == process_id and \
					win32gui.IsWindowVisible(handle) and \
					win32gui.GetWindowText(handle) == 'RoyiFileManager':
				matches.append(handle)
			return True
		win32gui.EnumWindows(collect, None)
		if matches:
			return matches[0]
		time.sleep(0.05)
	raise TimeoutError('Packaged RoyiFileManager window did not appear')


def _resize_client(handle, width, height):
	import win32con
	import win32gui

	rect = wintypes.RECT(0, 0, width, height)
	style = win32gui.GetWindowLong(handle, win32con.GWL_STYLE)
	extended_style = win32gui.GetWindowLong(handle, win32con.GWL_EXSTYLE)
	if not ctypes.windll.user32.AdjustWindowRectEx(
			ctypes.byref(rect), style, False, extended_style):
		raise ctypes.WinError()
	outer_width = rect.right - rect.left
	outer_height = rect.bottom - rect.top
	win32gui.MoveWindow(handle, 80, 80, outer_width, outer_height, True)
	win32gui.ShowWindow(handle, win32con.SW_RESTORE)
	win32gui.SetForegroundWindow(handle)


def _grab_native_window(handle, output):
	from PyQt5.QtWidgets import QApplication

	application = QApplication.instance() or QApplication(['screenshot-generator'])
	screen = application.primaryScreen()
	if screen is None:
		raise RuntimeError('No screen is available for packaged capture')
	_save_pixmap(screen.grabWindow(handle), output)


def _run_packaged(args):
	executable = args.exe.resolve()
	if not executable.is_file():
		raise FileNotFoundError(
			f'Packaged executable not found: {executable}. Run build.py freeze or '
			'use --mode source.'
		)
	settings = _prepare_settings('packaged')
	left_path, right_path = _public_paths()
	environment = os.environ.copy()
	environment['ROYIFILEMANAGER_USER_SETTINGS'] = str(settings)
	output = args.output_dir / 'royifilemanager-dual-pane-packaged.png'
	process = subprocess.Popen(
		[str(executable), str(left_path), str(right_path)],
		cwd=executable.parent, env=environment
	)
	try:
		handle = _find_window(process.pid, args.timeout)
		_resize_client(handle, args.width, args.height)
		time.sleep(args.settle_seconds)
		_grab_native_window(handle, output)
	finally:
		if process.poll() is None:
			try:
				import win32con
				import win32gui
				win32gui.PostMessage(handle, win32con.WM_CLOSE, 0, 0)
				process.wait(timeout=10)
			except (NameError, OSError, subprocess.TimeoutExpired):
				process.terminate()
				process.wait(timeout=10)
	return output,


def _validate_image(path, expected_width=None, expected_height=None):
	from PyQt5.QtGui import QImage

	image = QImage(str(path))
	if image.isNull():
		raise RuntimeError(f'Invalid screenshot: {path}')
	if expected_width is not None and image.width() != expected_width:
		raise RuntimeError(
			f'{path.name} width is {image.width()}, expected {expected_width}'
		)
	if expected_height is not None and image.height() != expected_height:
		raise RuntimeError(
			f'{path.name} height is {image.height()}, expected {expected_height}'
		)
	colors = {
		image.pixelColor(x, y).rgba()
		for x in range(0, image.width(), max(1, image.width() // 8))
		for y in range(0, image.height(), max(1, image.height() // 8))
	}
	if len(colors) < 2:
		raise RuntimeError(f'Screenshot appears blank: {path}')
	return image.width(), image.height()


def main(argv=None):
	args = _parse_args(argv)
	args.output_dir = args.output_dir.resolve()
	if args._source_child:
		return _capture_source_child(args)
	outputs = []
	if args.mode in ('source', 'all'):
		outputs.extend(_run_source(args))
	if args.mode in ('packaged', 'all'):
		outputs.extend(_run_packaged(args))
	for output in outputs:
		dimensions = _validate_image(output)
		print(f'Generated {output.relative_to(ROOT)} ({dimensions[0]}x{dimensions[1]})')
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
