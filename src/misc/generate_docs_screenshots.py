"""Generate public, repeatable application documentation screenshots.

The source capture follows the Qt smoke-test approach and grabs widgets directly.
The packaged capture launches the frozen executable and grabs its native window.
Both use isolated settings and only show ``C:\\`` and ``C:\\Windows`` locations.
The Robocopy picker shows an example destination and is canceled before transfer.
The text preview uses a generated Python sample with a neutral location label.
Checksum captures verify generated sample files and show only relative paths.
The batch renamer previews generated sample names and is canceled without renaming.
Selection captures use disposable sample files and change marks only.
Duplicate captures cancel the normal Copy prompt; free-space captures query a public local folder.
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
import faulthandler
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src/main/python'))
from build import _run_restricted
from fbs_runtime.build_settings import get_build_settings

BUILD_SETTINGS = get_build_settings()
APP_NAME = BUILD_SETTINGS['app_name']
DEFAULT_EXE = ROOT / 'target' / APP_NAME / (APP_NAME + '.exe')
DEFAULT_OUTPUT_DIR = ROOT / 'docs' / 'assets'
WORK_DIR = ROOT / 'target' / 'docs-screenshots'
SOURCE_LOG_DIR = ROOT / 'UserSettings' / 'Local' / 'DocsScreenshots'
SOURCE_CAPTURES = (
	'overview', 'go-to', 'context-menu', 'filter-pane', 'quick-view', 'quick-view-text', 'quick-view-csv',
	'fuzzy-find', 'everything-search', 'everything-folders',
	'search-files', 'find-files', 'favorites', 'directory-size', 'file-hash',
	'checksum-files', 'process-pane', 'pack-archive', 'quick-table', 'quick-board', 'batch-renamer', 'robocopy',
	'selection', 'duplicate-file', 'free-space'
)
QUICK_BOARD_SAMPLE = dict(text='Archive_', title='Compose a file-name prefix',
	summary='3 captured names; preview only')
QUICK_BOARD_NAMES = ('report.txt', 'notes.md', 'photo.jpg')
BATCH_RENAMER_NAMES = ('draft_01.txt', 'draft_02.txt', 'invoice_01.txt', 'invoice_02.txt',
	'notes.txt', 'report_01.txt', 'report_02.txt', 'report_10.txt')
BATCH_RENAMER_TEMPLATE = 'Archive_{(index + 1):03d}_{c}{d}{ext}'
SELECTION_NAMES = ('archive.tar.gz', 'backup.gz', 'draft notes.txt', 'draft report.txt',
	'invoice.csv', 'photo.jpg', 'README.md', 'report.txt', 'report.txt.bak')
PYTHON_SAMPLE = '''from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileSummary:
	name: str
	size: int


def describe_files(folder: Path) -> list[FileSummary]:
	return [
		FileSummary(path.name, path.stat().st_size)
		for path in sorted(folder.iterdir())
		if path.is_file()
	]


for item in describe_files(Path(".")):
	print(f"{item.name:24} {item.size:>8,} bytes")
'''.expandtabs(4)
CSV_SAMPLE = '''Order,Date,Customer,City,Product,Quantity,Amount
1001,2026-03-02,Avery Stone,Z\u00fcrich,Desk lamp,2,84.00
1002,2026-03-02,Noa Levi,Tel Aviv,"Monitor, 27""",1,329.90
1003,2026-03-03,Jo\u00e3o Silva,S\u00e3o Paulo,Keyboard,3,147.00
1004,2026-03-04,Mira Patel,Krak\u00f3w,USB-C hub,5,99.75
1005,2026-03-04,Liam Chen,Oslo,Office chair,1,249.00
1006,2026-03-05,Sara M\u00fcller,Z\u00fcrich,Notebook,12,36.00
1007,2026-03-06,Omar Haddad,Amman,Webcam,2,118.00
1008,2026-03-06,Ines Moreau,Lyon,Desk lamp,1,42.00
1009,2026-03-07,Kenji Sato,Osaka,"Monitor, 24""",2,398.00
1010,2026-03-08,Avery Stone,Z\u00fcrich,Mouse,4,79.60
1011,2026-03-09,Noa Levi,Tel Aviv,Headset,1,89.90
1012,2026-03-10,Elena Rossi,Milan,Standing desk,1,529.00
1013,2026-03-11,Mira Patel,Krak\u00f3w,Cable set,6,47.40
1014,2026-03-12,Liam Chen,Oslo,Docking station,1,219.00
'''
RIGHT_PANE_CAPTURES = (
	'context-menu', 'filter-pane', 'search-files', 'find-files', 'file-hash',
	'process-pane', 'pack-archive', 'quick-table'
)
DIALOG_CAPTURES = ('overview', 'go-to', 'fuzzy-find', 'everything-search', 'pack-archive', 'robocopy', 'duplicate-file')
EVERYTHING_QUERIES = (
	'ext:jpg;png size:>100kb !img0',
	'path:Fonts\\ <consola|segoe> ext:ttf !*b.ttf',
)
SOURCE_PATHS = (
	ROOT / 'src' / 'main' / 'python',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Core',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' /
	'SearchFileFuzzy',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Everything',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Favorites',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' /
	'CalculateFileHash',
	ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'ChecksumFiles',
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
	return BUILD_SETTINGS['version']


def _prepare_settings(name, *, initialize=True):
	directory = WORK_DIR / name / 'UserSettings'
	if directory.parent.exists():
		shutil.rmtree(directory.parent)
	if initialize:
		_initialize_session_settings(directory)
	return directory


def _initialize_session_settings(settings):
	(settings / 'Local').mkdir(parents=True, exist_ok=True)
	(settings / 'Local' / 'Session.json').write_text(
		json.dumps({
			'app_version': _application_version(),
			'is_licensed': True,
		}, indent=2) + '\n',
		encoding='utf-8'
	)


def _file_url(path):
	return 'file://' + path.as_posix().rstrip('/')


def _seed_settings(settings, capture):
	root, windows = _public_paths()
	if capture == 'favorites':
		favorites = (
			('Windows', windows, '2026-09-28T09:15:00', '2026-10-04T18:40:00', 14),
			('System32', windows / 'System32', '2026-09-21T14:02:00', '2026-10-03T11:25:00', 6),
			('Fonts', windows / 'Fonts', '2026-09-14T10:30:00', '2026-09-30T16:05:00', 3),
			('Wallpapers', windows / 'Web' / 'Wallpaper', '2026-09-07T20:45:00', None, 0),
			('Drive C', root, '2026-08-31T08:00:00', '2026-10-05T08:10:00', 27),
		)
		documents = {'Favorites.json': {'favorites': [
			dict({'name': name, 'url': _file_url(path), 'added': added, 'count': count},
				**({'opened': opened} if opened else {}))
			for name, path, added, opened, count in favorites
		]}}
	elif capture == 'directory-size':
		documents = {'DirectorySize.yaml': {'enabled': True}}
	elif capture == 'free-space':
		documents = {'Status Bar.yaml': {'mode': 'single'}}
	elif capture in ('everything-search', 'everything-folders'):
		documents = {'Everything.json': {
			'folders': [str(windows / 'Web'), str(windows / 'Fonts')],
			'instance': f'RoyiFileManagerDocs_{os.getpid()}',
		}}
	else:
		return
	directory = settings / 'Plugins' / 'User' / 'Settings'
	directory.mkdir(parents=True, exist_ok=True)
	for name, document in documents.items():
		(directory / name).write_text(
			json.dumps(document, indent=2) + '\n', encoding='utf-8'
		)


def _source_environment(settings):
	environment = os.environ.copy()
	environment['PYTHONFAULTHANDLER'] = '1'
	environment['PYTHONUNBUFFERED'] = '1'
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


def _grab_window_with_sample_location(window, location_bar, label='Python sample', dialog=None):
	original = location_bar.text()
	location_bar.setText(label)
	try:
		return window.grab() if dialog is None else _grab_window_with_dialog(window, dialog)
	finally:
		location_bar.setText(original)


def _source_capture_paths(capture):
	root, windows = _public_paths()
	if capture == 'duplicate-file':
		folder = WORK_DIR / 'source-duplicate-file' / 'sample'
		folder.mkdir(parents=True, exist_ok=True)
		for name in ('report.txt', 'report Copy 1.txt'):
			(folder / name).write_text('Documentation sample: ' + name + '\n', encoding='utf-8')
		return folder, windows
	if capture == 'selection':
		from datetime import datetime
		folder = WORK_DIR / 'source-selection' / 'sample'
		folder.mkdir(parents=True, exist_ok=True)
		modified = datetime(2026, 3, 15, 10, 30).timestamp()
		for name in SELECTION_NAMES:
			path = folder / name
			path.write_text('Documentation sample: ' + name + '\n', encoding='utf-8')
			os.utime(path, (modified, modified))
		(folder / 'Projects').mkdir(exist_ok=True)
		os.utime(folder / 'Projects', (modified, modified))
		return folder, windows
	if capture == 'batch-renamer':
		from datetime import datetime
		folder = WORK_DIR / 'source-batch-renamer' / 'sample'
		folder.mkdir(parents=True, exist_ok=True)
		modified = datetime(2026, 3, 15, 10, 30).timestamp()
		for name in BATCH_RENAMER_NAMES:
			path = folder / name
			path.write_text('Documentation sample: ' + name + '\n', encoding='utf-8')
			os.utime(path, (modified, modified))
		return folder, windows
	if capture == 'checksum-files':
		from checksum_files import engine
		folder = WORK_DIR / 'source-checksum-files' / 'sample'
		for name, content in {
			'README.txt': b'Checksum documentation sample.\n',
			'Data/readings.csv': b'time,value\n0,12\n1,15\n',
			'Documents/notes.txt': b'Release notes for the sample files.\n',
		}.items():
			path = folder / name
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_bytes(content)
		engine.generate(str(folder), (), str(folder / 'Samples.sha256'),
			engine.BY_ID['sha256'], engine.Settings())
		return folder, windows
	if capture == 'quick-view':
		return _public_image().parent, windows
	if capture == 'quick-view-text':
		folder = WORK_DIR / 'source-quick-view-text' / 'sample'
		folder.mkdir(parents=True, exist_ok=True)
		(folder / 'file_summary.py').write_text(PYTHON_SAMPLE, encoding='utf-8')
		return folder, windows
	if capture == 'quick-view-csv':
		folder = WORK_DIR / 'source-quick-view-csv' / 'sample'
		folder.mkdir(parents=True, exist_ok=True)
		(folder / 'orders.csv').write_text(CSV_SAMPLE, encoding='utf-8', newline='')
		return folder, windows
	if capture in ('fuzzy-find', 'robocopy'):
		return windows / 'Web', windows
	if capture in ('everything-search', 'everything-folders', 'free-space'):
		return windows / 'Web', windows / 'Fonts'
	if capture == 'directory-size':
		web = windows / 'Web'
		wallpaper = web / 'Wallpaper'
		return web, wallpaper if wallpaper.is_dir() else web
	return root, windows


def _source_outputs(output_dir, capture):
	names = {
		'overview': (
			'royifilemanager-dual-pane.png',
			'royifilemanager-command-center.png',
			'royifilemanager-ui-quicksearch.png',
		),
		'go-to': ('royifilemanager-find-location.png',),
		'context-menu': ('royifilemanager-file-context-menu.png',),
		'filter-pane': ('royifilemanager-filter-pane.png',),
		'quick-view': ('royifilemanager-quickview.png',),
		'quick-view-text': ('royifilemanager-quickview-python.png',),
		'quick-view-csv': ('royifilemanager-quickview-table.png',),
		'fuzzy-find': ('royifilemanager-fuzzy-find-recursive.png',),
		'everything-search': (
			'royifilemanager-everything-images.png',
			'royifilemanager-everything-fonts.png',
		),
		'everything-folders': ('royifilemanager-everything-folders.png',),
		'search-files': (
			'royifilemanager-search-files.png',
			'royifilemanager-search-files-panel.png',
			'royifilemanager-search-files-results.png',
		),
		'find-files': (
			'royifilemanager-find-files-fd.png',
			'royifilemanager-find-files-fd-panel.png',
			'royifilemanager-find-files-fd-results.png',
		),
		'favorites': (
			'royifilemanager-favorites.png',
			'royifilemanager-ui-quicklist.png',
		),
		'directory-size': ('royifilemanager-directory-size.png',),
		'file-hash': (
			'royifilemanager-file-hash.png',
			'royifilemanager-ui-output-text-box.png',
		),
		'checksum-files': ('royifilemanager-checksum-results.png',),
		'process-pane': ('royifilemanager-process-pane.png',),
		'pack-archive': ('royifilemanager-pack-archive.png',),
		'quick-table': (
			'royifilemanager-ui-quicktable.png',
			'royifilemanager-ui-quicktable-filter.png',
		),
		'quick-board': ('royifilemanager-ui-quickboard.png',),
		'batch-renamer': ('royifilemanager-batch-renamer.png',),
		'robocopy': ('royifilemanager-robocopy-destination.png',),
		'selection': ('royifilemanager-select-preview.png', 'royifilemanager-deselect-preview.png',
			'royifilemanager-select-extension.png'),
		'duplicate-file': ('royifilemanager-duplicate-file.png',),
		'free-space': ('royifilemanager-free-space.png',),
	}
	return tuple(output_dir / name for name in names[capture])


def _validate_everything_items(items, query_index):
	from fman.url import as_human_readable
	_, windows = _public_paths()
	results = [item for item in items if item.value]
	if not results:
		raise RuntimeError('Everything example returned no files')
	for item in results:
		path = Path(as_human_readable(item.value))
		name = path.name.casefold()
		if query_index == 0:
			matches = path.is_relative_to(windows / 'Web') and \
				path.suffix.casefold() in ('.jpg', '.png') and \
				path.stat().st_size > 100 * 1024 and 'img0' not in name
		else:
			matches = path.is_relative_to(windows / 'Fonts') and \
				path.suffix.casefold() == '.ttf' and \
				any(term in name for term in ('consola', 'segoe')) and \
				not name.endswith('b.ttf')
		if not matches or not item.description.strip():
			raise RuntimeError(f'Unexpected Everything example result: {item.title}')
	if query_index == 1 and not any(item.highlight for item in results):
		raise RuntimeError('Everything font results have no match highlights')


def _capture_source_child(args):
	# Create the whole settings tree with the non-admin token required by Everything.
	# Parent-created files or directories could require admin rights for later saves.
	settings = Path(os.environ['ROYIFILEMANAGER_USER_SETTINGS'])
	_initialize_session_settings(settings)
	_seed_settings(settings, args._capture)
	if args._capture == 'batch-renamer':
		shutil.copytree(ROOT / 'plugins/BatchFileRenamer', settings / 'Plugins/Third-party/BatchFileRenamer',
			ignore=shutil.ignore_patterns('__pycache__'))
	left_path, right_path = _source_capture_paths(args._capture)
	sys.argv = [sys.argv[0], str(left_path), str(right_path)]

	from fman.impl.application_context import get_application_context
	from fman.url import as_url
	from PyQt5.QtCore import QTimer, Qt
	from PyQt5.QtWidgets import QApplication, QMessageBox

	context = get_application_context()
	outputs = _source_outputs(args.output_dir, args._capture)
	deadline = time.monotonic() + args.timeout
	state = {
		'settled': 0, 'started': False, 'captured': False, 'closing': False,
		'initial_rows': None,
		'expected': (as_url(str(left_path)), as_url(str(right_path))),
	}
	errors = []

	def stop_capture():
		timer.stop()
		if state['closing']:
			return
		state['closing'] = True
		dialog = QApplication.activeModalWidget()
		if dialog is not None:
			dialog.reject()
		QTimer.singleShot(0, context.main_window.close)

	def fail():
		errors.append(traceback.format_exc())
		print(errors[-1], file=sys.stderr, flush=True)
		stop_capture()

	def finish(pixmap, output, cleanup=None):
		_save_pixmap(pixmap, output)
		if cleanup is not None:
			cleanup()
		state['captured'] = True
		stop_capture()

	def capture_dialog(dialog):
		if isinstance(dialog, QMessageBox):
			errors.append(dialog.text())
			print(errors[-1], file=sys.stderr, flush=True)
			QTimer.singleShot(0, dialog.reject)
			QTimer.singleShot(0, stop_capture)
			return
		if args._capture not in DIALOG_CAPTURES or state['captured'] or errors:
			return
		if args._capture == 'everything-search':
			state['dialog'] = dialog
			return
		def capture_overview_dialog():
			try:
				if args._capture == 'duplicate-file':
					from PyQt5.QtWidgets import QLineEdit
					if dialog.textValue() != str(left_path / 'report Copy 2.txt'):
						raise RuntimeError('Duplicate did not skip the occupied Copy 1 name')
					dialog.setTextValue('report Copy 2.txt')
					dialog.findChild(QLineEdit).setSelection(0, len('report Copy 2'))
					QApplication.processEvents()
					finish(_grab_window_with_sample_location(context.main_window,
						context.window.get_panes()[0]._widget._location_bar, 'Duplication sample', dialog), outputs[0])
					return
				if args._capture == 'robocopy':
					destination = str(_public_paths()[0] / 'Backups' / 'Wallpapers')
					dialog._query.setText(destination)
					if not dialog._curr_items or dialog._curr_items[0].value != destination:
						raise RuntimeError('Robocopy destination picker did not show the typed path')
					QApplication.processEvents()
				output = outputs[1] if args._capture == 'overview' else outputs[0]
				if args._capture == 'overview':
					_save_pixmap(dialog.grab(), outputs[2])
				finish(
					_grab_window_with_dialog(context.main_window, dialog), output
				)
			except BaseException:
				fail()
		def capture_fuzzy_dialog():
			try:
				if not dialog._curr_items:
					raise RuntimeError('Recursive fuzzy search returned no image results')
				finish(dialog.grab(), outputs[0])
			except BaseException:
				fail()
		QTimer.singleShot(
			150,
			capture_fuzzy_dialog if args._capture == 'fuzzy-find'
			else capture_overview_dialog
		)

	context.main_window.before_dialog.connect(capture_dialog)

	def check_ready():
		if state['captured'] or errors:
			return
		try:
			if time.monotonic() >= deadline:
				raise TimeoutError(
					f'{args._capture} capture did not settle before timeout'
				)
			panes = context.window.get_panes()
			ready = (
				len(panes) == 2
				and tuple(pane.get_path() for pane in panes) == state['expected']
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
			pane = panes[1] if args._capture in RIGHT_PANE_CAPTURES else panes[0]
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
			elif args._capture == 'robocopy':
				if state['started']:
					return
				folder = as_url(str(_public_paths()[1] / 'Web' / 'Wallpaper'))
				pane.clear_selection()
				pane.select((folder,))
				pane.place_cursor_at(folder)
				if pane.get_selected_files() != [folder]:
					raise RuntimeError('Robocopy source folder was not selected')
				pane.focus()
				state['started'] = True
				pane.run_command('copy_with_robocopy')
			elif args._capture == 'duplicate-file':
				if state['started']:
					return
				pane.clear_selection()
				pane.place_cursor_at(as_url(str(left_path / 'report.txt')))
				pane.focus()
				state['started'] = True
				pane.run_command('duplicate_file')
			elif args._capture == 'free-space':
				if not state['started']:
					pane.focus()
					state.update(started=True, settled=0)
					return
				status = context.main_window._single_pane_status
				if status is not None and status._free_space.text().startswith('Free: ') and state['settled'] >= 3:
					finish(context.main_window.grab(), outputs[0])
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
			elif args._capture == 'selection':
				from PyQt5.QtTest import QTest
				bar = pane._widget._filter_bar
				url = lambda name: as_url(str(left_path / name))
				baseline = {url('README.md')}
				selected = baseline | {url(name) for name in SELECTION_NAMES if name.endswith('.txt')}
				if not state['started']:
					pane.clear_selection()
					pane.select(baseline)
					pane.place_cursor_at(url('report.txt'))
					pane.focus()
					state.update(started=True, settled=0, phase='select')
					pane.run_command('select_by_pattern')
					return
				if pane._widget._model.rowCount() != len(SELECTION_NAMES) + 1:
					raise RuntimeError('Selection capture hid or changed sample rows')
				phase = state['phase']
				if phase in ('select', 'deselect'):
					session = bar._selection_session
					if session is None:
						return
					if phase == 'deselect' and not state.get('query_set'):
						bar._input.setText('^draft')
						state.update(query_set=True, settled=0)
						return
					if session['result'] is None or state['settled'] < 3:
						return
					preview = {url(session['listing'].names[session['visible'][row]])
						for row in session['result'][1]}
					expected = selected if phase == 'select' else {url('README.md'), url('report.txt')}
					if (preview != expected or set(pane.get_selected_files()) != (baseline if phase == 'select' else selected)
							or session['selecting'] != (phase == 'select')
							or bar._input.text() != ('*.txt$' if phase == 'select' else '^draft')):
						raise RuntimeError('Selection preview or committed marks differ from the documented example')
					_save_pixmap(_grab_window_with_sample_location(context.main_window,
						pane._widget._location_bar, 'Selection sample'), outputs[0 if phase == 'select' else 1])
					QTest.keyClick(pane._widget._file_view, Qt.Key_Return if phase == 'select' else Qt.Key_Escape)
					if bar._selection_session is not None or set(pane.get_selected_files()) != selected:
						raise RuntimeError('Enter or Escape did not preserve the documented selection')
					state.update(phase='deselect' if phase == 'select' else 'invert', settled=0)
					pane.run_command('deselect_by_pattern' if phase == 'select' else 'invert_selection')
					return
				if phase == 'invert':
					expected = {url(name) for name in (*SELECTION_NAMES, 'Projects')} - selected
					if set(pane.get_selected_files()) != expected:
						return
					pane.clear_selection()
					pane.select(baseline)
					pane.place_cursor_at(url('archive.tar.gz'))
					state.update(phase='extension', settled=0)
					pane.run_command('select_same_extension')
					return
				if set(pane.get_selected_files()) == baseline | {url('archive.tar.gz'), url('backup.gz')} and state['settled'] >= 3:
					finish(_grab_window_with_sample_location(context.main_window,
						pane._widget._location_bar, 'Selection sample'), outputs[2])
			elif args._capture in ('quick-view', 'quick-view-text'):
				text_capture = args._capture == 'quick-view-text'
				file_url = as_url(str(
					left_path / 'file_summary.py' if text_capture else _public_image()
				))
				if not state['started']:
					pane.place_cursor_at(file_url)
					pane.focus()
					if pane.get_file_under_cursor() != file_url:
						return
					state['started'] = True
					pane.run_command('toggle_quick_view')
					return
				session = getattr(context.main_window, '_quick_view_session', None)
				if session is None:
					return
				if text_capture:
					view = session.overlay.text_view
					if view is None or not view.isVisible():
						return
					browser = view.browser
					if browser.toPlainText().strip() != PYTHON_SAMPLE.strip():
						raise RuntimeError('QuickView did not display the Python sample')
					highlight = browser.document().find('def').charFormat().foreground()
					if highlight.style() == Qt.NoBrush or \
							highlight.color() == browser.palette().text().color():
						raise RuntimeError('QuickView Python sample is not syntax highlighted')
					finish(
						_grab_window_with_sample_location(
							context.main_window, pane._widget._location_bar
						), outputs[0],
						lambda: pane.run_command('toggle_quick_view')
					)
				elif session.overlay.canvas.image is not None:
					finish(
						context.main_window.grab(), outputs[0],
						lambda: pane.run_command('toggle_quick_view')
					)
			elif args._capture == 'quick-view-csv':
				file_url = as_url(str(left_path / 'orders.csv'))
				if not state['started']:
					pane.place_cursor_at(file_url)
					pane.focus()
					if pane.get_file_under_cursor() != file_url:
						return
					state['started'] = True
					pane.run_command('toggle_quick_view')
					return
				session = getattr(context.main_window, '_quick_view_session', None)
				view = session.overlay.csv_view if session is not None else None
				if view is None or not view.ready or view.pending or not view.isVisible():
					state['settled'] = 0
					return
				if view.sort_column is None:
					view.set_sort(3, False)
					return
				if view.model.count != 14 or any(view.model.row(row) is None for row in range(view.model.count)):
					return
				if view.model.row(0).cells[3] != 'Amman':
					raise RuntimeError('QuickView Table View did not sort the sample by City')
				view.view.setCurrentIndex(view.model.index(3, 4))
				state['settled'] += 1
				if state['settled'] >= 3:
					finish(
						_grab_window_with_sample_location(
							context.main_window, pane._widget._location_bar, 'CSV sample'
						), outputs[0],
						lambda: pane.run_command('toggle_quick_view')
					)
			elif args._capture == 'fuzzy-find':
				if state['started']:
					return
				state['started'] = True
				pane.focus()
				pane.run_command('search_files_recursively', {'query': 'img'})
			elif args._capture == 'everything-search':
				import everything_search
				if state['captured']:
					return
				if not state['started']:
					state['started'] = True
					pane.focus()
					pane.run_command('search_file_by_everything')
					return
				dialog = state.get('dialog')
				if dialog is None or not dialog.isVisible():
					return
				service = everything_search._service
				status = service.manager.snapshot()
				if status.status == 'error':
					raise RuntimeError(status.error)
				if status.status != 'ready':
					return
				query_index = state.get('query_index', 0)
				query = EVERYTHING_QUERIES[query_index]
				if dialog._query.text() != query:
					dialog._query.setText(query)
					state['settled'] = 0
					return
				if not any(item.value for item in dialog._curr_items):
					dialog._update_items(query)
					state['settled'] = 0
					return
				_validate_everything_items(dialog._curr_items, query_index)
				if dialog._query.fontMetrics().horizontalAdvance(query) > dialog._query.width() - 12:
					raise RuntimeError('Everything example query does not fit the capture')
				pixmap = _grab_window_with_dialog(context.main_window, dialog)
				if query_index == len(EVERYTHING_QUERIES) - 1:
					finish(pixmap, outputs[query_index], dialog.reject)
				else:
					_save_pixmap(pixmap, outputs[query_index])
					state['query_index'] = query_index + 1
			elif args._capture == 'everything-folders':
				import everything_search
				if not state['started']:
					state['started'] = True
					state['settled'] = 0
					state['expected'] = (everything_search.FOLDERS_ROOT, state['expected'][1])
					pane.focus()
					pane.run_command('manage_everything_folders')
					return
				listing = pane.get_listing()
				if set(listing.display_names) != {'Web', 'Fonts'} or len(listing.names) != 2:
					raise RuntimeError('Everything manager must contain only the two configured folder rows')
				if everything_search._service.manager is not None:
					raise RuntimeError('Opening the folder manager started Everything')
				finish(context.main_window.grab(), outputs[0])
			elif args._capture == 'favorites':
				from favorites.ui import _sessions
				from fman.impl.ui.quick_list_window import recent_list
				if not state['started']:
					state['started'] = True
					state['settled'] = 0
					pane.focus()
					pane.run_command('show_favorites')
					return
				session = _sessions.get(pane.window)
				window = recent_list(context.main_window)
				if session is None or session.revision < 0 or window is None or \
						context.main_window._panel_dock is None:
					state['settled'] = 0
					return
				if window.list.model.rowCount() == 0:
					raise RuntimeError('Favorites Manager shows no favorites')
				if state['settled'] >= 3:
					_save_pixmap(
						_grab_window_with_dialog(context.main_window, window), outputs[0]
					)
					quick_list = window.list
					quick_list.selected_ids = {item.id for item in quick_list.items[1:3]}
					quick_list.refresh()
					QApplication.processEvents()
					finish(window.grab(), outputs[1], window.close)
			elif args._capture == 'directory-size':
				from core import directory_size
				service = directory_size._service
				if service is None or not service.enabled:
					raise RuntimeError('Directory sizes were not enabled from settings')
				future = service._future
				if future is None or not future.done():
					return
				texts = []
				for candidate in panes:
					model = candidate._widget._model
					column = candidate.get_columns().index(directory_size.COLUMN)
					texts.extend(
						model.index(row, column).data() or ''
						for row in range(model.rowCount())
					)
				if all(texts) and not any(text.endswith('...') for text in texts):
					pane.focus()
					QApplication.processEvents()
					finish(context.main_window.grab(), outputs[0])
			elif args._capture == 'file-hash':
				from calculate_file_hash.ui import HashController
				file_url = as_url(str(_public_paths()[1] / 'win.ini'))
				if not state['started']:
					pane.place_cursor_at(file_url)
					if pane.get_file_under_cursor() != file_url:
						return
					pane.focus()
					state['started'] = True
					state['settled'] = 0
					pane.run_command('calculate_file_hash')
					return
				window = HashController._sessions.get(pane)
				if window is None or window.busy or window.session.last is None:
					state['settled'] = 0
					return
				if state['settled'] >= 3:
					_save_pixmap(window.grab(), outputs[1])
					finish(
						_grab_window_with_dialog(context.main_window, window),
						outputs[0], window.close
					)
			elif args._capture == 'checksum-files':
				from fman.impl.ui.facade import QuickTableWindow
				if not state['started']:
					manifest_url = as_url(str(left_path / 'Samples.sha256'))
					pane.place_cursor_at(manifest_url)
					if pane.get_file_under_cursor() != manifest_url:
						return
					pane.focus()
					state['started'] = True
					state['settled'] = 0
					pane.run_command('verify_checksum')
					return
				window = next((candidate for candidate in context.main_window.findChildren(QuickTableWindow)
					if candidate.isVisible() and candidate.windowTitle().startswith('Verify checksum file')), None)
				if window is None:
					state['settled'] = 0
					return
				if window.table.model.rowCount() != 3 or '3 matched, 0 problems' not in window.summary.content:
					raise RuntimeError('Checksum sample verification or result view is incorrect')
				if state['settled'] >= 3:
					finish(_grab_window_with_dialog(context.main_window, window), outputs[0], window.close)
			elif args._capture == 'quick-table':
				from PyQt5.QtCore import QPoint
				from PyQt5.QtGui import QPainter
				from fman.impl.ui.facade import open_quick_table
				from fman.impl.ui.table import FilterEditor
				from fman.ui import QuickTableColumn, QuickTableRow
				if not state['started']:
					entries = sorted((entry for entry in os.scandir(right_path) if entry.is_file()),
						key=lambda entry: entry.name.casefold())
					rows = [QuickTableRow((entry.name, entry.stat().st_size, entry.stat().st_mtime_ns,
						Path(entry.name).suffix.lstrip('.').upper())) for entry in entries]
					window = open_quick_table(columns=(
						QuickTableColumn('Name', 'file_name'),
						QuickTableColumn('Size', 'numeric', unit='bytes'),
						QuickTableColumn('Date Modified', 'date', date_display='date'),
						QuickTableColumn('Type'),
					), rows=rows, pane=pane, summary='Files in C:\\Windows: filter, then press Enter')
					table = window.table
					table.query.setText('.exe')
					table.set_sort(1, True)
					menu = table.open_filter_menu(1)
					editor = menu.findChild(FilterEditor)
					editor.operator.setCurrentIndex(editor.operator.findData('>='))
					editor.first.setText('100')
					editor.unit.setCurrentIndex(editor.unit.findData('KiB'))
					editor.submitted.emit()
					state.update(started=True, settled=0, window=window, total=len(rows))
					return
				window = state['window']
				table = window.table
				visible = table.model.rowCount()
				if not table.settled or 1 not in table.filters or state['settled'] < 3:
					return
				if not 0 < visible < state['total']:
					raise RuntimeError('QuickTable sample filters show no narrowed rows')
				if 'menu' not in state:
					table.view.setFocus()
					table.view.setCurrentIndex(table.model.index(0, 0))
					QApplication.processEvents()
					_save_pixmap(window.grab(), outputs[0])
					state['menu'] = table.open_filter_menu(1)
					state['settled'] = 0
					return
				menu = state['menu']
				if not menu.isVisible():
					raise RuntimeError('QuickTable filter menu did not open')
				pixmap = window.grab()
				painter = QPainter(pixmap)
				try:
					painter.drawPixmap(window.mapFromGlobal(menu.mapToGlobal(QPoint())), menu.grab())
				finally:
					painter.end()
				finish(pixmap, outputs[1], lambda: (menu.close(), window.close()))
			elif args._capture == 'quick-board':
				from fman.impl.ui.quick_board import _Session, _open
				from fman.ui import QuickTableColumn, QuickTableRow
				if not state['started']:
					def get_rows(prefix, mapping):
						return tuple(QuickTableRow((name, prefix + name)) for name in QUICK_BOARD_NAMES), None
					session = _Session(QUICK_BOARD_SAMPLE['text'])
					window = _open(session, (QuickTableColumn('Original'), QuickTableColumn('Preview', sortable=False, filterable=False)),
						get_rows, **QUICK_BOARD_SAMPLE)
					window.table.view.setColumnWidth(0, 340)
					state.update(started=True, settled=0, window=window)
					return
				window = state['window']
				if window.preview_error:
					raise RuntimeError(window.preview_error)
				if window.pending or not window.table.settled or state['settled'] < 3:
					return
				if (window.input.text() != QUICK_BOARD_SAMPLE['text'] or
						window.windowTitle() != QUICK_BOARD_SAMPLE['title'] or
						window.summary.content != QUICK_BOARD_SAMPLE['summary'] or
						tuple(row.cells for row in window.table.model.rows) != tuple(
							(name, QUICK_BOARD_SAMPLE['text'] + name) for name in QUICK_BOARD_NAMES)):
					raise RuntimeError('QuickBoard example arguments or preview differ from the documentation')
				finish(window.grab(), outputs[0], window.close)
			elif args._capture == 'batch-renamer':
				from fman.impl.ui.quick_board import QuickBoardWindow
				if not state['started']:
					pane.clear_selection()
					pane.select(tuple(as_url(str(left_path / name)) for name in BATCH_RENAMER_NAMES))
					if len(pane.get_selected_files()) != len(BATCH_RENAMER_NAMES):
						raise RuntimeError('Batch renamer sample selection is incomplete')
					pane.focus()
					state.update(started=True, settled=0)
					pane.run_command('batch_file_renamer')
					return
				window = next((candidate for candidate in context.main_window.findChildren(QuickBoardWindow)
					if candidate.isVisible() and candidate.windowTitle() == 'Batch File Renamer'), None)
				if window is None:
					state['settled'] = 0
					return
				if 'template_set' not in state:
					window.input.setText(BATCH_RENAMER_TEMPLATE)
					state.update(template_set=True, settled=0)
					return
				if window.preview_error:
					raise RuntimeError(window.preview_error)
				if window.pending or not window.table.settled or state['settled'] < 3:
					return
				rows = window.table.model.rows
				if (tuple(row.cells[2] for row in rows) != BATCH_RENAMER_NAMES or
						window.caller_status_text != '%d files ready to rename.' % len(BATCH_RENAMER_NAMES) or
						not all(row.cells[4].startswith('Archive_%03d_' % (index + 1))
							and row.cells[4].endswith('.txt') for index, row in enumerate(rows))):
					raise RuntimeError('Batch renamer example preview is incomplete or invalid')
				finish(window.grab(), outputs[0], window.close)
			elif args._capture == 'process-pane':
				filter_bar = pane._widget._filter_bar
				if not state['started']:
					state['started'] = True
					state['settled'] = 0
					state['expected'] = (state['expected'][0], 'process://')
					pane.focus()
					pane.run_command('show_processes')
					return
				if state['initial_rows'] is None:
					state['initial_rows'] = pane._widget._model.rowCount()
					state['settled'] = 0
					filter_bar._input.setText('svchost')
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
			elif args._capture == 'pack-archive':
				file_url = as_url(str(_public_paths()[1] / 'win.ini'))
				if state['started']:
					return
				pane.place_cursor_at(file_url)
				if pane.get_file_under_cursor() != file_url:
					return
				pane.focus()
				state['started'] = True
				pane.run_command('pack')
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
				# Results searches use folders without access-denied children, which would mark results as errors.
				windows = _public_paths()[1]
				if args._capture == 'search-files':
					from search_files import SearchUI
					owner = SearchUI.owner
					title = 'Search files'
					values = {'name': '*.ini', 'content': 'fonts', 'recursive': True}
					results_folder = windows / 'System32' / 'drivers' / 'etc'
					results_values = {
						'name': '', 'content': 'Copyright', 'recursive': False,
						'extended': True,
					}
				else:
					from find_files import FindUI
					owner = FindUI.owner
					title = 'Find files'
					values = {
						'pattern': 'notepad*', 'extensions': 'exe',
						'max_results': 25, 'recursive': True,
					}
					results_folder = windows
					results_values = {
						'pattern': '*', 'extensions': 'exe',
						'max_results': None, 'recursive': False,
					}
				host = next(
					(host for host in _hosts.values() if host.owner is owner), None
				)
				if host is None:
					return
				session = host.on_action.__self__
				panel = session.panel
				if 'searching' not in state:
					panel.update(values=values)
					QApplication.processEvents()
					if state['settled'] >= 3:
						_save_pixmap(context.main_window.grab(), outputs[0])
						_save_pixmap(host.panel.grab(), outputs[1])
						state['expected'] = (state['expected'][0], as_url(str(results_folder)))
						pane.set_path(state['expected'][1])
						state.update(searching=False, settled=0)
					return
				if not state['searching']:
					if session.root != str(results_folder):
						return
					panel.update(values=results_values)
					host.action('search')
					state.update(searching=True, settled=0)
					return
				from fman.impl.ui.facade import QuickTableWindow
				window = next((candidate for candidate in
					context.main_window.findChildren(QuickTableWindow)
					if candidate.isVisible() and candidate.windowTitle() == title), None)
				if window is None or not window.table.settled:
					state['settled'] = 0
					return
				summary = window.summary.content.casefold()
				if window.table.model.rowCount() == 0 or 'error' in summary or 'incomplete' in summary:
					raise RuntimeError(f'{title} results are empty or incomplete: {window.summary.content}')
				if 'sorted' not in state:
					window.table.set_sort(1, True)
					state.update(sorted=True, settled=0)
					return
				if state['settled'] >= 3:
					finish(window.grab(), outputs[2], lambda: (window.close(), panel.close()))
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
	if 'everything-search' in SOURCE_CAPTURES:
		subprocess.run([sys.executable, '-c', 'import build; build._ensure_everything()'],
			cwd=ROOT, check=True)
	elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
	outputs = []
	for capture in SOURCE_CAPTURES:
		# Only clean stale state here; the child must create its writable settings tree.
		settings = _prepare_settings('source-' + capture, initialize=False)
		command = [
			sys.executable, str(Path(__file__).resolve()), '--_source-child',
			'--_capture', capture,
			'--output-dir', str(args.output_dir.resolve()),
			'--width', str(args.width), '--height', str(args.height),
			'--timeout', str(args.timeout),
		]
		print(f'Capturing source: {capture}', flush=True)
		environment = _source_environment(settings)
		if elevated:
			SOURCE_LOG_DIR.mkdir(parents=True, exist_ok=True)
			_run_restricted(command, environment, SOURCE_LOG_DIR / (capture + '.log'),
				args.timeout + 30)
		else:
			subprocess.run(command, cwd=ROOT, env=environment, check=True)
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
					win32gui.GetWindowText(handle) == APP_NAME:
				matches.append(handle)
			return True
		win32gui.EnumWindows(collect, None)
		if matches:
			return matches[0]
		time.sleep(0.05)
	raise TimeoutError('Packaged %s window did not appear' % APP_NAME)


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
		faulthandler.dump_traceback_later(args.timeout)
		try:
			print(f'Starting source child: {args._capture}', flush=True)
			return _capture_source_child(args)
		finally:
			faulthandler.cancel_dump_traceback_later()
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
