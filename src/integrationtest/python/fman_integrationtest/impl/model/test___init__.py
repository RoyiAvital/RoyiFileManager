from contextlib import contextmanager
from fbs_runtime.platform import is_linux
from fman.impl.model import SortedFileSystemModel
from fman.impl.plugins.builtin import NullFileSystem, NullColumn
from fman.impl.plugins.mother_fs import MotherFileSystem
from fman.impl.util import filenotfounderror
from fman.impl.util.qt import connect_once, DisplayRole, DecorationRole
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import splitscheme
from fman_unittest.impl.model import StubFileSystem
from PyQt5.QtCore import Qt
from threading import Event
from time import time, sleep

import sys

class SortedFileSystemModelAT: # Instantiated in fman_integrationtest.test_qt

	_NUM_FILES = 100
	_NUM_VISIBLE_ROWS = 10

	def test_location_after_init(self):
		self.assertEqual('null://', self._model.get_location())
		self.assertEqual((self._null_column,), self._model.get_columns())
	def test_local_hidden_attributes_shared_panes_toggle_refresh_and_events(self):
		if sys.platform != 'win32':
			self.skipTest('Windows entry attributes')
		from core import LocalFileSystem, Modified
		from core.commands import _hidden_file_filter
		from fman.url import as_url
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import patch
		from PyQt5.QtCore import QThread, QItemSelectionModel
		from PyQt5.QtWidgets import QTableView, QApplication
		from win32file import SetFileAttributes
		self._timeout = 5
		with TemporaryDirectory() as temporary:
			root = Path(temporary).resolve()
			(root / 'visible').touch()
			(root / 'hidden').touch()
			(root / 'other').mkdir()
			SetFileAttributes(str(root / 'hidden'), 2)
			provider = LocalFileSystem()
			self._fs.add_child('file://', provider)
			self._register_column(Modified(self._fs))
			second = self.run_in_app(SortedFileSystemModel, None, self._fs, 'null://')
			models = [self._model, second]
			views = []
			wrong_threads = []
			def create_views():
				for model in models:
					view = QTableView()
					view.setModel(model)
					views.append(view)
					model.add_filter(_hidden_file_filter)
					model.files_changed.connect(lambda:
						wrong_threads.append(QThread.currentThread() != QApplication.instance().thread()))
			def names(model):
				return self.run_in_app(lambda: [model.data(model.index(row, 0))
					for row in range(model.rowCount())])
			with patch('core.commands.query', side_effect=self._fs.query), \
				patch.object(self._fs._icon_provider, 'get_icon', return_value=None):
				try:
					self.run_in_app(create_views)
					for model in models:
						loaded = Event()
						self.run_in_app(lambda: model.all_rows_loaded.connect(loaded.set))
						model.set_location(as_url(root))
						self.assertTrue(loaded.wait(5))
						self.run_in_app(lambda: model.all_rows_loaded.disconnect(loaded.set))
						self.assertEqual(['other', 'visible'], names(model))
					visible_url = as_url(root / 'visible')
					def select():
						selection = views[0].selectionModel()
						selection.setCurrentIndex(self._model.find(visible_url),
							QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
					self.run_in_app(select)
					self.run_in_app(self._model.remove_filter, _hidden_file_filter)
					self._wait_until(lambda: names(self._model) == ['other', 'hidden', 'visible'], 'toggle on')
					self.assertEqual(['other', 'visible'], names(second))
					self.assertEqual(visible_url, self.run_in_app(lambda:
						self._model.url(views[0].currentIndex())))
					self.assertEqual([visible_url], self.run_in_app(lambda:
						[self._model.url(index) for index in views[0].selectionModel().selectedRows()]))
					self.run_in_app(self._model.add_filter, _hidden_file_filter)
					self._wait_until(lambda: names(self._model) == ['other', 'visible'], 'toggle off')
					SetFileAttributes(str(root / 'visible'), 2)
					for model in models:
						self.run_in_app(model.sourceModel).notify_file_changed(visible_url)
					self._wait_until(lambda: all(names(model) == ['other'] for model in models), 'changed event')
					SetFileAttributes(str(root / 'hidden'), 128)
					provider.notify_file_changed(splitscheme(as_url(root))[1])
					self._wait_until(lambda: all(names(model) == ['other', 'hidden'] for model in models), 'refresh')
					provider.move(as_url(root / 'hidden'), as_url(root / 'renamed'))
					self._wait_until(lambda: all(names(model) == ['other', 'renamed'] for model in models), 'rename')
					provider.delete(splitscheme(as_url(root / 'renamed'))[1])
					self._wait_until(lambda: all(names(model) == ['other'] for model in models), 'delete')
					self.assertTrue(wrong_threads)
					self.assertFalse(any(wrong_threads))
				finally:
					for model in models:
						source = self.run_in_app(model.sourceModel)
						source.shutdown()
						source._worker._thread.join(5)
						self.assertFalse(source._worker._thread.is_alive())
					self.run_in_app(lambda: [view.deleteLater() for view in views])
	def test_navigation_away_from_blocked_local_scan_rejects_stale_rows(self):
		if sys.platform != 'win32':
			self.skipTest('Windows entry attributes')
		from core import LocalFileSystem, Modified
		from fman.url import as_url
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from types import SimpleNamespace
		from unittest.mock import patch
		started, resume = Event(), Event()
		with TemporaryDirectory() as temporary:
			root = Path(temporary).resolve()
			(root / 'entry').touch()
			provider = LocalFileSystem()
			self._fs.add_child('file://', provider)
			self._register_column(Modified(self._fs))
			class Entries:
				def __enter__(self):
					return self
				def __exit__(self, *args):
					pass
				def __iter__(self):
					started.set()
					if not resume.wait(5):
						raise TimeoutError('blocked scan not released')
					yield SimpleNamespace(name='entry', stat=lambda **kwargs:
						SimpleNamespace(st_file_attributes=32))
			with patch('core.fs.local.os.scandir', return_value=Entries()):
				self._model.set_location(as_url(root))
				old = self.run_in_app(self._model.sourceModel)
				try:
					self.assertTrue(started.wait(5))
					self._set_location('stub://dir')
					provider.cache.clear(splitscheme(as_url(root))[1])
				finally:
					resume.set()
					old._worker._thread.join(5)
				self.assertFalse(old._worker._thread.is_alive())
				self.assertTrue(old._shutdown)
				self.assertEqual('stub://dir', self._model.get_location())
				self.assertEqual(['subdir'], self._get_first_column())
				self.assertIsNone(provider._pane_hidden_state(splitscheme(as_url(root / 'entry'))[1]))
	def _tracked_location(self, url, callback=None):
		from fman.impl.navigation import NavigationRequest, tracking
		finished = Event()
		outcomes = []
		def deliver(*outcome):
			outcomes.append(outcome)
			finished.set()
		request = NavigationRequest(deliver)
		with tracking(request):
			self._model.set_location(url, callback=callback)
		self.assertTrue(finished.wait(2), 'Tracked navigation did not finish')
		self.assertTrue(request.settled.wait(2), 'Navigation did not settle')
		self._drain_initialization()
		self.assertEqual(1, len(outcomes))
		return outcomes[0]
	def test_tracked_empty_and_same_path_navigation(self):
		self.assertEqual('success', self._tracked_location('stub://dir')[0])
		self.assertEqual('success', self._tracked_location('stub://dir')[0])
	def test_superseded_before_init_releases_waiter(self):
		from unittest.mock import patch
		from fman.impl.model.model import Model
		from fman.impl.navigation import NavigationRequest, tracking
		from fman.impl.ui import submit_work
		for attempt in range(3):
			request = NavigationRequest(lambda *args: None)
			with patch.object(Model, 'start'):
				with tracking(request):
					self._model.set_location('stub://dir')
			old_model = self.run_in_app(self._model.sourceModel)
			finished = Event()
			self.assertTrue(submit_work(lambda: request.wait(1), lambda *args: finished.set()))
			self._set_location('stub://')
			self.assertTrue(request.settled.wait(1))
			self.assertTrue(finished.wait(1))
			self.assertTrue(old_model._shutdown)
			self.assertFalse(request.begin_initialization())
	def test_column_failure_preserves_displayed_model(self):
		from unittest.mock import patch
		self._set_location('stub://')
		old_model = self.run_in_app(self._model.sourceModel)
		with patch.object(self._fs, 'get_columns', side_effect=PermissionError('columns denied')):
			with self.assertRaises(PermissionError):
				self._model.set_location('stub://dir')
		self.assertIs(old_model, self.run_in_app(self._model.sourceModel))
		self.assertFalse(old_model._shutdown)
		self._set_location('stub://dir')
		self.assertTrue(old_model._shutdown)
	def test_tracked_iterator_failure_is_not_success(self):
		from unittest.mock import patch
		def denied(url):
			yield '0'
			raise PermissionError('listing denied')
		with patch.object(self._fs, 'iterdir', side_effect=denied):
			outcome, message = self._tracked_location('stub://')
		self.assertEqual('failure', outcome)
		self.assertIn('listing denied', message)
	def test_tracked_initial_error_and_cursor_failure(self):
		from unittest.mock import patch
		with patch('fman.impl.model.worker.sys.excepthook') as exception_hook:
			with patch.object(self._fs, 'iterdir', side_effect=PermissionError('denied')) as iterdir:
				outcome, message = self._tracked_location('stub://')
			self.assertEqual('failure', outcome)
			self.assertIn('denied', message)
			iterdir.assert_called_once_with('stub://')
			exception_hook.assert_not_called()
		def missing_cursor():
			raise ValueError('File disappeared')
		self.assertEqual('failure', self._tracked_location('stub://', missing_cursor)[0])
	def test_set_location(self):
		inited = Event()
		self._model.set_location('stub://', callback=inited.set)
		self.assertEqual('stub://', self._model.get_location())
		self._wait_for(inited)
		self._expect_column_headers(['Name', 'Size'])
		self.assertEqual(
			(self._name_column, self._size_column), self._model.get_columns()
		)
		self.assertEqual(
			['dir'] + [str(i) for i in range(self._NUM_FILES)],
			self._get_first_column(),
			'Should load at least the first column'
		)
		self._load_visible_rows()
		rows = self._get_data()[:self._NUM_VISIBLE_ROWS]
		icons = self._get_data(DecorationRole)[:self._NUM_VISIBLE_ROWS]
		self.assertEqual(('dir', ''), rows[0])
		self.assertEqual((self._folder_icon, None), icons[0])
		self.assertEqual(
			[
				(str(i), '%d B' % self._files[str(i)]['size'])
				for i in range(self._NUM_VISIBLE_ROWS - 1)
			],
			rows[1:]
		)
		self.assertEqual(
			[(self._file_icon, None)] * (self._NUM_VISIBLE_ROWS - 1), icons[1:]
		)
	def _load_visible_rows(self):
		loaded = Event()
		load_rows = run_in_main_thread(self._model.load_rows)
		load_rows(range(self._NUM_VISIBLE_ROWS), callback=loaded.set)
		self._wait_for(loaded)
	def test_remove_current_dir(self):
		self._set_location('stub://dir')
		with self._wait_for_signal(self._model.location_loaded):
			self._fs.delete('stub://dir')
		self.assertEqual('stub://', self._model.get_location())
	def test_remove_root(self):
		self._set_location('stub://dir')
		with self._wait_for_signal(self._model.location_loaded):
			self._fs.remove_child('stub://')
		self.assertEqual('null://', self._model.get_location())
	def test_reloads(self):
		self.test_set_location()
		self._set_location('stub://dir')
		self._files['0']['size'] = 87
		self._set_location('stub://')
		self._load_visible_rows()
		self._wait_until(
			lambda: self._get_data()[:2] == [('dir', ''), ('0', '87 B')],
			'Model failed to reload'
		)
	def test_sort(self):
		self.test_set_location()
		with self._wait_for_signal(self._model.sort_order_changed):
			run_in_main_thread(self._model.sort)(1)
		expected_files_sort_order = ['dir'] + sorted(
			(str(i) for i in range(self._NUM_FILES)),
			key=lambda fname: self._files[fname]['size']
		)
		self.assertEqual(expected_files_sort_order, self._get_first_column())
		self._load_visible_rows()
		self.assertEqual(
			[
				(fname, '%s B' % self._files[fname]['size'])
				for fname in expected_files_sort_order[1:self._NUM_VISIBLE_ROWS]
			],
			self._get_data()[1:self._NUM_VISIBLE_ROWS]
		)
	def test_file_added(self):
		self.test_set_location()
		self._files['new'] = {
			'is_dir': False,
			'size': 2,
			'icon': self._file_icon
		}
		self._files['']['files'].append('new')
		self._fs.file_added.trigger('stub://new')
		self.assertTrue(
			'new' in [r[0] for r in self._get_data()],
			'Should have processed new file synchronously to support use case:'
			' 1. Create file.txt'
			' 2. place cursor at file.txt. '
			'Without synchronous processing, step 2. would fail.'
		)
	def test_file_removed(self):
		self.test_set_location()
		self._stubfs.delete('0')
		self._fs.file_removed.trigger('stub://0')
		self._wait_until(
			lambda: '0' not in [r[0] for r in self._get_data()],
			'Did not pick up external removal of file'
		)
	def test_location_removed(self):
		self._set_location('stub://dir')
		self._stubfs.delete('dir')
		self._model.reload()
		self._wait_until(
			lambda: self._model.get_location() == 'stub://',
			'Did not pick up external removal of location'
		)
	def test_root_directory_changed(self):
		self.test_set_location()
		# "Delete" all files:
		self._files.clear()
		self._files.update({
			'': {'is_dir': True, 'files': ['dir'], 'icon': self._folder_icon},
			'dir': {'is_dir': True, 'files': [], 'icon': self._folder_icon}
		})
		self._stubfs.notify_file_changed('')
		self._wait_until(
			lambda: self._get_data() == [('dir', '')],
			'Did not pick up external update of root directory'
		)
	def test_file_renamed(self):
		self.test_set_location()
		self._stubfs.move('stub://0', 'stub://a')
		def rename_noticed():
			first_column = self._get_first_column()
			return 'a' in first_column and '0' not in first_column
		self._wait_until(rename_noticed, 'Did not pick up renaming of file')
	def test_file_moved_in(self):
		self.test_set_location()
		self._stubfs.move('stub://dir/subdir', 'stub://subdir')
		self._wait_until(
			lambda: 'subdir' in self._get_first_column(),
			'Did not pick up move of directory'
		)
	def test_file_moved_out(self):
		self.test_set_location()
		self._stubfs.move('stub://0', 'stub://dir/0')
		self._wait_until(
			lambda: not '0' in self._get_first_column(),
			'Did not pick up move of file into subdirectory'
		)
	def test_rename_file_different_case(self):
		self.test_set_location()
		self._stubfs.move('stub://dir', 'stub://Dir')
		def rename_noticed():
			first_column = self._get_first_column()
			return 'Dir' in first_column and 'dir' not in first_column
		self._wait_until(rename_noticed, 'Did not pick up renaming of file')
	def _set_location(self, location):
		loaded = Event()
		self._model.set_location(location, callback=loaded.set)
		self._wait_for(loaded)
		self._drain_initialization()
	def _drain_initialization(self):
		drained = Event()
		model = self.run_in_app(self._model.sourceModel)
		model._worker.submit(1, drained.set)
		self.assertTrue(drained.wait(2), 'Model initialization did not drain')
	def _get_data(self, role=DisplayRole):
		result = []
		for row in range(self._model.rowCount()):
			result.append(tuple(
				self._model.data(self._index(row, col), role)
				for col in range(self._model.columnCount())
			))
		return result
	def _get_first_column(self):
		return [row[0] for row in self._get_data()]
	def _index(self, row, column=0):
		return self._model.index(row, column)
	def _expect_column_headers(self, expected):
		actual = [
			self._model.headerData(column, Qt.Horizontal)
			for column in range(self._model.columnCount())
		]
		self.assertEqual(expected, actual)
	def setUp(self):
		super().setUp()
		# N.B.: Normally we should have QIcon instances here. But they don't
		# seem to work well with ==. So use strings instead:
		folder_icon = '<folder icon>'
		file_icon = '<file icon>'
		self._files = {
			'': {'is_dir': True, 'files': ['dir'], 'icon': folder_icon},
			'dir': {'is_dir': True, 'files': ['subdir'], 'icon': folder_icon},
			'dir/subdir': {'is_dir': True, 'icon': folder_icon}
		}
		for i in range(self._NUM_FILES):
			fname = str(i)
			# Make size ordering different from ordering by name:
			size = i + (0 if i % 2 else self._NUM_FILES)
			self._files[fname] = {
				'is_dir': False, 'size': size, 'icon': file_icon
			}
			self._files['']['files'].append(fname)
		self._folder_icon = folder_icon
		self._file_icon = file_icon
		files = self._files if is_linux() else CaseInsensitiveDict(self._files)
		self._fs = MotherFileSystem(StubIconProvider(files))
		self._fs.add_child('null://', NullFileSystem())
		self._null_column = NullColumn()
		self._register_column(self._null_column)
		self._stubfs = StubFileSystem(
			files, default_columns=('core.Name', 'core.Size')
		)
		self._fs.add_child('stub://', self._stubfs)
		# Import late to avoid ImportError. The reason it occurs is that fbs's
		# `test` command adds fman_integrationtest to sys.path before Core.
		# That's fair; It's actually unclean for this test to depend on Core.
		# But it is also very useful as a kind of end-to-end test. So we do it.
		from core import Name, Size
		self._name_column = Name(self._fs)
		self._register_column(self._name_column)
		self._size_column = Size(self._fs)
		self._register_column(self._size_column)
		self._model = self.run_in_app(
			SortedFileSystemModel, None, self._fs, 'null://'
		)
		self._drain_initialization()
		self._timeout = None if _is_debugger_attached() else .2
	def tearDown(self):
		model = self._model.sourceModel()
		model.shutdown()
		model._worker._thread.join(2)
		self.assertFalse(model._worker._thread.is_alive())
		super().tearDown()
	def _register_column(self, instance):
		self._fs.register_column(instance.get_qualified_name(), instance)
	@contextmanager
	def _wait_for_signal(self, signal):
		occurred = Event()
		run_in_main_thread(connect_once)(signal, lambda *_: occurred.set())
		yield
		self._wait_for(occurred)
	def _wait_for(self, event):
		if not event.wait(self._timeout):
			self.fail('Event was not set after timeout')
	def _wait_until(self, condition, message):
		end_time = time() + (self._timeout or sys.float_info.max)
		while time() < end_time:
			if condition():
				break
			if self._get_data()[:2] == [('dir', ''), ('0', '87 B')]:
				break
			sleep(.1)
		else:
			self.fail(message)

def _is_debugger_attached():
	return bool(sys.gettrace())

class StubIconProvider:
	def __init__(self, files):
		self._files = files
	def get_icon(self, url):
		path = splitscheme(url)[1]
		try:
			return self._files[path].get('icon', None)
		except KeyError:
			raise filenotfounderror(url)

class CaseInsensitiveDict:
	def __init__(self, items):
		self._items = items
	def __getitem__(self, key):
		for k, v in self._items.items():
			if k.lower() == key.lower():
				return v
		raise KeyError(key)
	def	__setitem__(self, key, value):
		for k, v in self._items.items():
			if k.lower() == key.lower():
				self._items[k] = value
				return
		self._items[key] = value
	def __contains__(self, item):
		try:
			self[item]
		except KeyError:
			return False
		return True
	def pop(self, key):
		for k, v in self._items.items():
			if k.lower() == key.lower():
				return self._items.pop(key)
		raise KeyError(key)
	def items(self):
		return self._items.items()
	def clear(self):
		self._items.clear()
	def update(self, other):
		for k, v in other.items():
			self[k] = v