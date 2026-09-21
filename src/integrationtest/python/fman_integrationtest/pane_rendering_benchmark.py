"""Read-only pane comparison against an isolated historical source revision."""

import argparse
from contextlib import nullcontext
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import perf_counter


def distribution(values):
	if not values:
		return {'count': 0}
	ordered = sorted(values)
	return {'count': len(values), 'median': statistics.median(values),
		'p95': ordered[min(len(values) - 1, int(len(values) * .95))],
		'max': max(values)}


def install_baseline(destination, revision):
	root = Path(__file__).resolve().parents[4]
	commit = subprocess.check_output(['git', 'rev-parse', '--verify', revision + '^{commit}'],
		cwd=root, text=True).strip()
	archive = subprocess.check_output(['git', 'archive', commit,
		'src/main', 'src/build/settings'], cwd=root)
	destination.mkdir()
	with tarfile.open(fileobj=io.BytesIO(archive)) as source:
		source.extractall(destination, filter='data')
	for index, path in enumerate(sys.path):
		absolute = Path(path).resolve()
		if absolute.is_relative_to(root / 'src' / 'main'):
			sys.path[index] = str(destination / absolute.relative_to(root))
	return commit


def child(directory, label, mode, show_hidden, rows_output=None, interactions=False, output=None, baseline_ref='56e840a'):
	temporary_settings = TemporaryDirectory(prefix='pane-rendering-')
	os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(Path(temporary_settings.name) / 'UserSettings')
	baseline_commit = None
	if mode != 'snapshot':
		baseline_commit = install_baseline(Path(temporary_settings.name) / 'baseline', baseline_ref)
	from core import LocalFileSystem
	from fman import DATA_DIRECTORY
	import core.commands as commands
	from fman.impl.application_context import get_application_context
	from fman.impl.fs_cache import Cache
	Model = None
	ListingModel = None
	if mode == 'snapshot':
		from fman.impl.model.listing import ListingModel
	else:
		from fman.impl.model.model import Model
	from fman.impl.model import SortedFileSystemModel
	from fman.impl.util.qt.thread import run_in_main_thread
	from fman.impl.view import FileListView
	from fman.url import as_url, splitscheme
	from PyQt5.QtCore import QCoreApplication, QEvent, Qt, QTimer
	from PyQt5.QtGui import QKeyEvent
	import win32api
	import win32process

	directory = directory.resolve(strict=True)
	target = as_url(directory)
	state = {'label': label, 'mode': mode, 'show_hidden': show_hidden, 'baseline_commit': baseline_commit,
		'hidden_queries': 0, 'path_stats': 0, 'commits_ms': [],
		'loading_keys_ms': [], 'settled_keys_ms': [],
		'loading_paints_ms': [], 'settled_paints_ms': [], 'errors': []}
	painted, completed = Event(), Event()
	pending = {}
	operation = {}
	started = [None]
	view_holder = []
	cursor = {'row': 0, 'count': 0}
	original_filter = commands._hidden_file_filter
	if mode == 'before':
		original_init = LocalFileSystem.__init__
		def baseline_init(provider):
			original_init(provider)
			provider.cache = Cache()
		def baseline_iterdir(provider, path):
			os_path = provider._url_to_os_path(path)
			if not provider._isabs(os_path):
				raise FileNotFoundError(path)
			return os.listdir(os_path)
		def baseline_filter(url):
			scheme, path = splitscheme(url)
			return scheme != 'file://' or not commands.is_hidden(path)
		LocalFileSystem.__init__ = baseline_init
		LocalFileSystem.iterdir = baseline_iterdir
		commands._hidden_file_filter = baseline_filter
	elif mode == 'reviewed':
		from contextlib import contextmanager
		from threading import Lock
		from core.fs import local
		class ReviewedEntryAttributesCache(Cache):
			def __init__(self):
				super().__init__()
				self._scans = {}
				self._scan_lock = Lock()
			@contextmanager
			def collect_entry_attributes(self, path):
				path = path.rstrip('/')
				token = object()
				with self._scan_lock:
					self._scans[path] = token
				def publish(entry_path, attributes):
					with self._scan_lock:
						if self._scans.get(path) is token:
							self.put(entry_path, '_entry_attributes', attributes)
				try:
					yield publish
				finally:
					with self._scan_lock:
						if self._scans.get(path) is token:
							del self._scans[path]
			def clear(self, path):
				with self._scan_lock:
					cleared = path.rstrip('/')
					for directory in tuple(self._scans):
						if not cleared or directory == cleared \
							or directory.startswith(cleared + '/') \
							or cleared.startswith(directory + '/'):
							del self._scans[directory]
					super().clear(path)
		def reviewed_hidden_state(provider, path):
			if not local._supports_entry_attributes(path) or len(path) <= 3:
				return None
			try:
				attributes = provider.cache.get(path, '_entry_attributes')
			except KeyError:
				return None
			if attributes is None:
				return None
			return bool(attributes & local.FILE_ATTRIBUTE_HIDDEN)
		local._EntryAttributesCache = ReviewedEntryAttributesCache
		LocalFileSystem._pane_hidden_state = reviewed_hidden_state
	else:
		commands._hidden_file_filter = original_filter
	original_iterdir = LocalFileSystem.iterdir
	def counted_iterdir(provider, path):
		begin = perf_counter()
		names = original_iterdir(provider, path)
		if 'file://' + path == target:
			state['enumeration_ms'] = (perf_counter() - begin) * 1000
			state['entries'] = len(names)
			state['entry_attribute_reads'] = len(names) if mode != 'before' else 0
		return names
	LocalFileSystem.iterdir = counted_iterdir
	original_hidden = commands.is_hidden
	def hidden(path):
		state['hidden_queries'] += 1
		return original_hidden(path)
	commands.is_hidden = hidden
	original_stat = os.stat
	def counted_stat(path, *args, **kwargs):
		if str(path).replace('\\', '/').startswith(str(directory).replace('\\', '/').rstrip('/') + '/'):
			state['path_stats'] += 1
		return original_stat(path, *args, **kwargs)
	os.stat = counted_stat
	original_navigation = SortedFileSystemModel._set_location
	def navigation(model, url, *args, **kwargs):
		if url == target:
			started[0] = perf_counter()
		return original_navigation(model, url, *args, **kwargs)
	SortedFileSystemModel._set_location = navigation
	original_scan = getattr(LocalFileSystem, 'scan', None)
	def scan(provider, path, check):
		begin = perf_counter()
		result = original_scan(provider, path, check)
		if 'file://' + path == target and result is not None:
			state['enumeration_ms'] = (perf_counter() - begin) * 1000
			state['entries'] = len(result.names)
		return result
	if mode == 'snapshot':
		LocalFileSystem.scan = scan
	original_snapshot_commit = ListingModel._commit if ListingModel is not None else None
	def snapshot_commit(model, result):
		begin = perf_counter()
		first = model._displayed is None
		if first and model.get_location() == target:
			state['prepare_ms'] = (begin - started[0]) * 1000
		original_snapshot_commit(model, result)
		if model.get_location() == target:
			elapsed = (perf_counter() - begin) * 1000
			if operation:
				operation['committed'] = True
				operation['commits'].append(elapsed)
				return
			if first:
				state['initial_commit_ms'] = elapsed
				state['complete_ms'] = (perf_counter() - started[0]) * 1000
				completed.set()
			else:
				state['commits_ms'].append(elapsed)
	if ListingModel is not None:
		ListingModel._commit = snapshot_commit
	if Model is not None:
		original_initialize = Model._initialize
		def initialize(model, callback):
			if model.get_location() == target and started[0] is None:
				started[0] = perf_counter()
			return original_initialize(model, callback)
		Model._initialize = initialize
		original_initial_commit = Model._on_rows_inited_main.__wrapped__
		def initial_commit(model, *args):
			begin = perf_counter()
			if model.get_location() == target:
				state['prepare_ms'] = (begin - started[0]) * 1000
			result = original_initial_commit(model, *args)
			if model.get_location() == target:
				state['initial_commit_ms'] = (perf_counter() - begin) * 1000
			return result
		Model._on_rows_inited_main = run_in_main_thread(initial_commit)
		original_record = Model._record_files_main.__wrapped__
		def record(model, *args):
			begin = perf_counter()
			result = original_record(model, *args)
			if model.get_location() == target:
				state['commits_ms'].append((perf_counter() - begin) * 1000)
			return result
		Model._record_files_main = run_in_main_thread(record)
		original_model_init = Model.__init__
		def model_init(model, *args, **kwargs):
			original_model_init(model, *args, **kwargs)
			if model.get_location() == target:
				def done():
					state['complete_ms'] = (perf_counter() - started[0]) * 1000
					completed.set()
				model.all_rows_loaded.connect(done)
		Model.__init__ = model_init
	original_paint = FileListView.paintEvent
	def changed(index, previous):
		cursor['row'] = index.row()
		if pending and pending.get('handled') and index.row() == pending['expected'] and 'cursor' not in pending:
			pending['cursor'] = perf_counter()
	original_key = FileListView.keyPressEvent
	def key_pressed(view, event):
		if pending and event.key() in (Qt.Key_Down, Qt.Key_Up):
			pending['received'] = perf_counter()
			pending['handled'] = True
			step = 1 if event.key() == Qt.Key_Down else -1
			pending['expected'] = max(0, min(view.model().rowCount() - 1, view.currentIndex().row() + step))
			if pending['expected'] == view.currentIndex().row():
				pending['cursor'] = perf_counter()
				view.viewport().update()
		return original_key(view, event)
	FileListView.keyPressEvent = key_pressed
	def observe_movement(original, step):
		def move(view, *args, **kwargs):
			if pending and pending.get('handled'):
				pending['move_started'] = perf_counter()
				pending['expected'] = max(0, min(view.model().rowCount() - 1, view.currentIndex().row() + step))
			result = original(view, *args, **kwargs)
			if pending and pending.get('handled') and view.currentIndex().row() == pending['expected']:
				pending.setdefault('cursor', perf_counter())
				view.viewport().update()
			return result
		return move
	FileListView.move_cursor_down = observe_movement(FileListView.move_cursor_down, 1)
	FileListView.move_cursor_up = observe_movement(FileListView.move_cursor_up, -1)
	def paint(view, event):
		result = original_paint(view, event)
		if view.model().get_location() != target:
			return result
		if operation.get('committed') and not operation['done'].is_set():
			operation['paint_ms'] = (perf_counter() - operation['start']) * 1000
			operation['done'].set()
		if not painted.is_set() and view.model().rowCount():
			state['first_paint_ms'] = (perf_counter() - started[0]) * 1000
			cursor.update(row=view.currentIndex().row(), count=view.model().rowCount())
			view.selectionModel().currentChanged.connect(changed)
			view_holder.append(view)
			painted.set()
		if pending and 'cursor' in pending and not pending['done'].is_set():
			phase = pending['phase']
			state[phase + '_keys_ms'].append((pending['cursor'] - pending['start']) * 1000)
			elapsed = (perf_counter() - pending['start']) * 1000
			state[phase + '_paints_ms'].append(elapsed)
			if operation and elapsed > operation.get('worst_arrow', {}).get('paint_ms', 0):
				operation['worst_arrow'] = {'paint_ms': elapsed,
					'key_received_ms': (pending.get('received', pending['start']) - pending['start']) * 1000,
					'move_started_ms': (pending.get('move_started', pending['start']) - pending['start']) * 1000,
					'cursor_changed_ms': (pending['cursor'] - pending['start']) * 1000}
			pending['done'].set()
		return result
	FileListView.paintEvent = paint

	with temporary_settings as temporary:
		root = Path(temporary)
		settings = root / 'UserSettings'
		if Path(DATA_DIRECTORY).resolve() != settings.resolve():
			raise RuntimeError('settings isolation failed')
		user = settings / 'Plugins' / 'User' / 'Settings'
		user.mkdir(parents=True)
		(user / 'Panes.json').write_text(json.dumps([
			{'show_hidden_files': show_hidden}, {'show_hidden_files': show_hidden}]), encoding='utf-8')
		empty = root / 'empty'
		empty.mkdir()
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(settings)
		context = get_application_context()
		_ = context.app
		original_excepthook = sys.excepthook
		def record_exception(error_type, error, traceback):
			state['errors'].append(error_type.__name__)
			original_excepthook(error_type, error, traceback)
		sys.excepthook = record_exception
		context.session_manager.is_first_run = False
		sys.argv = [sys.argv[0], str(directory), str(empty)]
		gui = lambda function: run_in_main_thread(function)()
		def exercise():
			code = 1
			try:
				if not painted.wait(90):
					raise TimeoutError('first paint')
				view = view_holder[0]
				def check_configuration():
					for pane in context.window.get_panes():
						active_filter = commands._hidden_file_filter in pane._widget._model._filters
						if active_filter == show_hidden:
							raise RuntimeError('requested hidden-filter mode is not active')
						if pane._widget._status_tracking:
							raise RuntimeError('status tracking must be disabled')
					if context.main_window._status_service is not None:
						raise RuntimeError('status service must be disabled')
					if 'fman.impl.quick_view' in sys.modules:
						raise RuntimeError('QuickView renderer must not be loaded')
				gui(check_configuration)
				state['settings_isolated'] = True
				settled_start = None
				deadline = perf_counter() + 90
				while perf_counter() < deadline:
					phase = 'settled' if completed.is_set() else 'loading'
					if phase == 'settled' and settled_start is None:
						settled_start = perf_counter()
					if settled_start is not None and perf_counter() - settled_start >= 2:
						break
					row, count = cursor['row'], cursor['count']
					if count < 2:
						raise RuntimeError('not enough rows for input probe')
					step = 1 if row < min(10, count - 1) else -1
					pending.clear()
					pending.update(start=perf_counter(), expected=row + step, phase=phase, done=Event())
					key = Qt.Key_Down if step == 1 else Qt.Key_Up
					QCoreApplication.postEvent(view, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
					if not pending['done'].wait(5):
						raise TimeoutError('arrow selection/paint')
					pending.clear()
					Event().wait(.05)
				if not completed.is_set():
					raise TimeoutError('metadata completion')
				if state['errors']:
					raise RuntimeError('application exceptions: ' + repr(state['errors']))
				if show_hidden and state['hidden_queries']:
					raise RuntimeError('filter-off run performed hidden queries')
				def fingerprint():
					model = view.model().sourceModel()
					digest = hashlib.sha256()
					if rows_output:
						rows_output.parent.mkdir(parents=True, exist_ok=True)
					capture = rows_output.open('w', encoding='ascii') if rows_output else nullcontext()
					with capture as output:
						for row in range(model.rowCount()):
							value = [model.url(model.index(row, 0)).rsplit('/', 1)[-1],
								[model.data(model.index(row, column), Qt.DisplayRole)
								for column in range(model.columnCount())]]
							serialized = json.dumps(value, ensure_ascii=True)
							digest.update(serialized.encode('ascii'))
							if output is not None:
								output.write(serialized + '\n')
					state['rows'] = model.rowCount()
					state['fingerprint'] = digest.hexdigest()
				gui(fingerprint)
				state['working_set_mib'] = win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['WorkingSetSize'] / 1048576
				state['metadata_tail_ms'] = max(0, state['complete_ms'] - state['first_paint_ms'])
				state['commits_total_ms'] = sum(state['commits_ms'])
				state['commits_ms'] = distribution(state['commits_ms'])
				if interactions:
					from search_file_fuzzy.indexer import ListingSearch
					pane = context.window.get_panes()[0]._widget
					state['interactions'] = {}
					def measure(name, action):
						state[name + '_keys_ms'], state[name + '_paints_ms'] = [], []
						operation.clear()
						operation.update(start=perf_counter(), done=Event(), commits=[])
						gui(action)
						for sample in range(2000):
							row, count = cursor['row'], cursor['count']
							if count >= 2:
								step = 1 if row < min(10, count - 1) else -1
								pending.clear()
								pending.update(start=perf_counter(), expected=row + step, phase=name, done=Event())
								QCoreApplication.postEvent(view, QKeyEvent(QEvent.KeyPress,
									Qt.Key_Down if step == 1 else Qt.Key_Up, Qt.NoModifier))
								if not pending['done'].wait(5):
									raise TimeoutError('%s arrow paint: pending=%r, current=%r, committed=%r' % (
										name, pending, gui(lambda: view.currentIndex().row()), operation.get('committed')))
								pending.clear()
							if operation['done'].is_set() and sample >= 20:
								break
						if not operation['done'].wait(10):
							raise TimeoutError(name + ' completed paint')
						state['interactions'][name] = {
							'completed_paint_ms': operation['paint_ms'],
							'worst_arrow': operation.get('worst_arrow'),
							'qt_commits_ms': distribution(operation['commits']),
							'arrow_to_cursor_ms': distribution(state.pop(name + '_keys_ms')),
							'arrow_to_paint_ms': distribution(state.pop(name + '_paints_ms'))}
					measure('filter', lambda: pane._filter_bar._input.setText('!zzzzzzzzzzzz'))
					measure('clear_filter', lambda: pane._filter_bar._input.setText(''))
					query = '1' if state['entries'] > 100000 else ''
					measure('fuzzy', lambda: pane.find_in_listing(ListingSearch(max_entries=1000000), query))
					measure('exit_fuzzy', lambda: pane._filter_bar.finish_search())
					measure('sort', lambda: pane.set_sort_column('core.Modified', False))
					measure('refresh', pane.reload)
					profile = None
					if os.environ.get('PANE_PROFILE_MARKED') == '1':
						import cProfile
						profile = cProfile.Profile()
						gui(profile.enable)
					gui(pane.select_all)
					measure('marked_sort', lambda: pane.set_sort_column('core.Name', True))
					if profile is not None:
						gui(profile.disable)
						profile.print_stats(sort='cumulative')
					state['interactions']['selected_count'] = gui(lambda: sum(
						selection.bottom() - selection.top() + 1 for selection in view.selectionModel().selection()))
					gui(pane.clear_selection)
					operation.clear()
					state['peak_working_set_mib'] = win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())['PeakWorkingSetSize'] / 1048576
					if state['errors']:
						raise RuntimeError('interaction exceptions: ' + repr(state['errors']))
				for phase in ('loading', 'settled'):
					for metric in ('keys_ms', 'paints_ms'):
						state[phase + '_' + metric] = distribution(state[phase + '_' + metric])
				code = 0
				if output:
					output.parent.mkdir(parents=True, exist_ok=True)
					output.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
				print('PANE_RESULT ' + json.dumps(state), flush=True)
			except BaseException as error:
				import traceback
				traceback.print_exc()
			finally:
				def stop():
					models = [pane._widget._model.sourceModel() for pane in context.window.get_panes()]
					for model in models:
						model.shutdown()
					return models
				for model in gui(stop):
					if hasattr(model, '_worker'):
						model._worker._thread.join(5)
						if model._worker._thread.is_alive():
							code = 1
				gui(lambda: context.app.exit(code))
		QTimer.singleShot(0, lambda: Thread(target=exercise, daemon=True).start())
		return context.run()


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('directories', nargs='+', type=Path)
	parser.add_argument('--repeat', type=int, default=3)
	parser.add_argument('--output', type=Path)
	parser.add_argument('--show-hidden', action='store_true')
	parser.add_argument('--baseline', choices=('before', 'reviewed', 'current'), default='before',
		help='Compare against no hidden cache or the reviewed full-path cache')
	parser.add_argument('--child', choices=('before', 'reviewed', 'after', 'current', 'snapshot'))
	parser.add_argument('--baseline-ref', default='56e840a', help='Historical application commit, extracted only in benchmark children')
	parser.add_argument('--label')
	parser.add_argument('--rows-output', type=Path, help='Diagnostic child-only row capture after timing')
	parser.add_argument('--interactions', action='store_true', help='Snapshot child: measure filter/find/sort/refresh and marked-state input')
	args = parser.parse_args()
	if args.interactions and args.child != 'snapshot':
		parser.error('--interactions requires --child snapshot')
	if args.child:
		return child(args.directories[0], args.label, args.child, args.show_hidden, args.rows_output, args.interactions, args.output, args.baseline_ref)
	if args.rows_output:
		parser.error('--rows-output requires --child')
	if args.repeat < 1:
		parser.error('--repeat must be positive')
	results = []
	for directory in args.directories:
		label = directory.name or 'DriveRoot'
		new_mode = 'snapshot' if args.baseline == 'current' else 'after'
		for iteration in range(args.repeat):
			for mode in ((args.baseline, new_mode) if iteration % 2 == 0 else (new_mode, args.baseline)):
				command = [sys.executable, '-m', 'fman_integrationtest.pane_rendering_benchmark',
					str(directory), '--child', mode, '--label', label, '--baseline-ref', args.baseline_ref]
				if args.show_hidden:
					command.append('--show-hidden')
				run = subprocess.run(command, capture_output=True, text=True, timeout=180)
				if run.returncode:
					print(run.stdout + run.stderr, file=sys.stderr)
					return run.returncode
				result = json.loads(next(line.removeprefix('PANE_RESULT ')
					for line in run.stdout.splitlines() if line.startswith('PANE_RESULT ')))
				result['iteration'] = iteration + 1
				results.append(result)
				print(json.dumps(result), flush=True)
				if args.output:
					args.output.parent.mkdir(parents=True, exist_ok=True)
					args.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
	return 0


if __name__ == '__main__':
	sys.exit(main())