"""Qt tests share one main-thread QApplication for the process lifetime.

Each unittest runs on a worker while the main thread services a local event
loop. The optional qt_runner provides that event loop for the whole suite.
"""

from fman.impl.util.qt.thread import run_in_thread
from fman_integrationtest.impl.model.test___init__ import \
	SortedFileSystemModelAT
from fman_integrationtest.impl.util.qt.test_thread import RunInThreadAT
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from threading import Event
from unittest import TestCase

class QtIT(TestCase):
	def run(self, result=None):
		from PyQt5.QtCore import QEventLoop, QThread, QTimer
		from threading import Thread
		if _QtApp._app is None or QThread.currentThread() != _QtApp._app.thread():
			return super().run(result)
		loop = QEventLoop()
		results = []
		def execute():
			try:
				results.append(super(QtIT, self).run(result))
			finally:
				_QtApp.run(loop.quit)
		worker = Thread(target=execute)
		QTimer.singleShot(0, worker.start)
		loop.exec_()
		worker.join()
		return results[0]
	def run_in_app(self, f, *args, **kwargs):
		return _QtApp.run(f, *args, **kwargs)

class SortedFileSystemModelIT(SortedFileSystemModelAT, QtIT):
	pass

class MainWindowIT(QtIT):
	def test_forced_minimum_size(self):
		from fman.impl.widgets import MainWindow
		from PyQt5.QtCore import QSize
		from unittest.mock import Mock
		def check():
			window = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
			try:
				self.assertEqual(QSize(960, 600), window.minimumSize())
				for width, height in ((960, 600), (1280, 800), (1440, 900)):
					window.resize(width, height)
					self.assertEqual(QSize(width, height), window.size())
			finally:
				window.close()
				window.deleteLater()
		self.run_in_app(check)

class FilterBarIT(QtIT):
	def setUp(self):
		from core import Name, Size, Modified
		from core.fs.local import LocalFileSystem
		from fman.impl.plugins.builtin import NullFileSystem, NullColumn
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from fman.impl.plugins.plugin import FileSystemWrapper
		from fman.impl.widgets import MainWindow
		from pathlib import Path
		from PyQt5.QtGui import QIcon
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock
		self.temporary = TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name).resolve()
		for name in ('report.txt', 'Annual Report.pdf', 'script.py', 'script.pyc', 'tmp.log'):
			(self.root / name).write_bytes(b'')
		self.errors = Mock()
		self.filesystem = MotherFileSystem(Mock(get_icon=Mock(return_value=QIcon())))
		for backend in (LocalFileSystem(), NullFileSystem()):
			self.filesystem.add_child(backend.scheme, FileSystemWrapper(backend, self.filesystem, self.errors))
		for column in (Name(self.filesystem), Size(self.filesystem), Modified(self.filesystem), NullColumn()):
			self.filesystem.register_column(column.get_qualified_name(), column)
		def create():
			self.window = MainWindow(QApplication.instance(), [], Mock(), Mock(), self.filesystem, 'null://')
			self.controller = Mock(handle_shortcut=Mock(return_value=False),
				handle_nonexistent_shortcut=Mock(return_value=False))
			self.window.set_controller(self.controller)
			self.panes = [self.window.add_pane() for index in range(2)]
			self.window.resize(960, 600)
			self.window.show()
			self.window.activateWindow()
			self.panes[0].focus()
		self.run_in_app(create)
		self.addCleanup(self.close_window)
		for pane in self.panes:
			self.navigate(pane, self.root)
		self.run_in_app(self.window.clear_status_message)

	def close_window(self):
		def close():
			models = [pane._model.sourceModel() for pane in self.panes]
			for model in models:
				model.shutdown()
			self.window.close()
			return models
		for model in self.run_in_app(close):
			model._worker._thread.join(5)
			self.assertFalse(model._worker._thread.is_alive())
		self.run_in_app(self.window.deleteLater)
		self.errors.assert_not_called()

	def navigate(self, pane, path):
		from fman.url import as_url
		loaded = Event()
		pane.set_location(as_url(path), callback=loaded.set)
		self.assertTrue(loaded.wait(5), 'Pane did not load')
		self.drain(pane)

	def drain(self, pane):
		model = self.run_in_app(pane._model.sourceModel)
		drained = Event()
		model._worker.submit(100, drained.set)
		self.assertTrue(drained.wait(5), 'Model worker did not drain')
		self.run_in_app(lambda: None)

	def set_query(self, text, pane=None):
		pane = pane or self.panes[0]
		self.run_in_app(pane._filter_bar._input.setText, text)

	def status(self):
		return self.run_in_app(self.window._status_bar_text.text)

	def key(self, key, text='', pane=None):
		from PyQt5.QtCore import QEvent
		from PyQt5.QtGui import QKeyEvent
		pane = pane or self.panes[0]
		return self.run_in_app(pane._on_key_pressed, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text))

	def test_syntax_counts_and_clear_transitions(self):
		for query, count in [('rep', 2), ('^rep*$', 1), ('.py$', 1), ('!tmp', 4), ('[rt]*.???$', 4), ('missing', 0)]:
			with self.subTest(query=query):
				self.set_query(query)
				self.assertEqual('Filter "%s": %d of 5 items' % (query, count), self.status())
				self.assertFalse(self.run_in_app(self.window._timer.isActive))
		self.key(Qt.Key_Escape)
		self.assertEqual('Ready.', self.status())
		self.key(Qt.Key_R, 'r')
		self.key(Qt.Key_Backspace)
		self.assertEqual('Ready.', self.status())
		self.assertFalse(self.run_in_app(self.panes[0]._filter_bar.isVisible))
		self.window.show_status_message('Another command')
		self.key(Qt.Key_Escape)
		self.assertEqual('Another command', self.status())

	def test_committed_content_and_reload_counts(self):
		from fman.url import as_url
		pane = self.panes[0]
		model = self.run_in_app(pane._model.sourceModel)
		self.set_query('.py$')
		new_file = self.root / 'unmatched.txt'
		new_file.write_bytes(b'')
		model.notify_file_added(as_url(new_file))
		self.assertEqual('Filter ".py$": 1 of 6 items', self.status())
		new_file.unlink()
		model.notify_file_removed(as_url(new_file))
		self.assertEqual('Filter ".py$": 1 of 5 items', self.status())
		(self.root / 'other.py').write_bytes(b'')
		pane.reload()
		self.drain(pane)
		self.assertEqual('Filter ".py$": 2 of 6 items', self.status())

	def test_two_panes_and_unfiltered_noop(self):
		from unittest.mock import patch
		self.set_query('rep')
		self.set_query('tmp', self.panes[1])
		self.assertEqual('Filter "rep": 2 of 5 items', self.status())
		self.panes[1].focus()
		self.assertEqual('Filter "tmp": 1 of 5 items', self.status())
		self.window.show_status_message('Another command')
		self.run_in_app(lambda: self.panes[0]._model.sourceModel().files_changed.emit())
		self.assertEqual('Another command', self.status())
		self.set_query('', self.panes[0])
		self.panes[0].focus()
		self.assertEqual('Ready.', self.status())
		self.set_query('', self.panes[1])
		with patch.object(self.window, 'show_status_message') as status:
			self.run_in_app(lambda: self.panes[0]._model.sourceModel().files_changed.emit())
			self.key(Qt.Key_Escape)
			self.panes[1].focus()
			status.assert_not_called()

	def test_pane_filter_accessors(self):
		from unittest.mock import patch
		pane = self.panes[0]
		self.assertFalse(pane.is_filtering())
		self.window.show_status_message('Another command')
		pane.publish_filter_count()
		self.assertEqual('Another command', self.status())
		self.set_query('rep')
		self.assertTrue(pane.is_filtering())
		self.run_in_app(pane._filter_bar.hide)
		self.assertTrue(pane.is_filtering(), 'Filter state must not depend on widget visibility')
		self.window.show_status_message('Another command')
		model = self.run_in_app(pane._model.sourceModel)
		with patch.object(model, 'update', side_effect=AssertionError('Publishing counts must not refilter rows')):
			pane.publish_filter_count()
		self.assertEqual('Filter "rep": 2 of 5 items', self.status())
		self.set_query('missing')
		self.assertTrue(pane.is_filtering(), 'A zero-match query is still an active filter')
		self.key(Qt.Key_Escape)
		self.assertFalse(pane.is_filtering())
		self.window.show_status_message('Copied')
		pane.publish_filter_count()
		self.assertEqual('Copied', self.status())

	def test_loading_navigation_and_retired_source(self):
		from fman.impl.model.model import Model
		from fman.url import as_url
		from PyQt5.QtCore import QThread
		from threading import Thread
		from unittest.mock import patch
		pane = self.panes[0]
		old_model = self.run_in_app(pane._model.sourceModel)
		nested = self.root / 'nested'
		nested.mkdir()
		for name in ('report.new', 'other.txt'):
			(nested / name).write_bytes(b'')
		entered, release, loaded = Event(), Event(), Event()
		original = Model._on_rows_inited
		def delayed(model, rows, preloaded, callback):
			entered.set()
			if not release.wait(5):
				raise AssertionError('Initial population was not released')
			return original(model, rows, preloaded, callback)
		self.set_query('tmp')
		threads = []
		def replace():
			emitter = Thread(target=old_model.files_changed.emit)
			emitter.start()
			emitter.join(2)
			self.assertFalse(emitter.is_alive())
			pane.set_location(as_url(nested), callback=loaded.set)
			self.assertEqual('Ready.', self.window._status_bar_text.text())
			pane._filter_bar._input.setText('rep')
			self.window.show_status_message('Loading command')
			pane._model.files_changed.connect(lambda: threads.append(QThread.currentThread()))
		with patch.object(Model, '_on_rows_inited', delayed):
			try:
				self.run_in_app(replace)
				self.assertTrue(entered.wait(5))
				self.assertEqual('Loading command', self.status(), 'Retired queued signal published a count')
				self.set_query('re')
				self.assertEqual('Filter "re": 0 of 0 items', self.status())
			finally:
				release.set()
			self.assertTrue(loaded.wait(5))
			self.drain(pane)
		self.assertEqual('Filter "re": 1 of 2 items', self.status())
		self.assertTrue(threads)
		self.assertTrue(all(thread == QApplication.instance().thread() for thread in threads))
		self.assertEqual(as_url(nested / 'report.new'), pane.get_file_under_cursor())
		new_file = nested / 'nonmatching.txt'
		new_file.write_bytes(b'')
		model = self.run_in_app(pane._model.sourceModel)
		model.notify_file_added(as_url(new_file))
		self.assertEqual('Filter "re": 1 of 3 items', self.status())
		self.window.show_status_message('Another command')
		self.run_in_app(old_model.files_changed.emit)
		self.assertEqual('Another command', self.status())
		self.key(Qt.Key_Escape)
		self.window.show_status_message('Copied')
		self.navigate(pane, self.root)
		self.assertEqual('Copied', self.status())

	def test_keyboard_prefix_space_and_plain_status(self):
		from fman.impl.controller import Controller
		from fman.impl.plugins.key_bindings import KeyBindings
		from fman.url import as_url
		from pathlib import Path
		from unittest.mock import Mock
		import json
		pane = self.panes[0]
		pane.place_cursor_at(as_url(self.root / 'Annual Report.pdf'))
		self.key(Qt.Key_R, 'r')
		self.assertEqual(as_url(self.root / 'report.txt'), pane.get_file_under_cursor())
		self.assertEqual('Filter "r": 4 of 5 items', self.status())
		self.window.show_status_message('Copied', 5)
		self.key(Qt.Key_E, 'e')
		self.assertEqual('Filter "re": 2 of 5 items', self.status())
		self.assertFalse(self.run_in_app(self.window._timer.isActive))
		bindings = KeyBindings()
		bindings.register_command('toggle_selection')
		path = Path(__file__).parents[3] / 'main/resources/base/Plugins/Core/Key Bindings.json'
		with path.open(encoding='utf-8') as stream:
			space_binding = [binding for binding in json.load(stream) if binding['keys'] == ['Space']]
		self.assertEqual([], bindings.load(space_binding))
		public_pane = Mock(get_commands=Mock(return_value=['toggle_selection']))
		public_pane.run_command.side_effect = lambda name, args: pane.toggle_selection(pane.get_file_under_cursor())
		support = Mock(get_sanitized_key_bindings=bindings.get_sanitized_bindings)
		controller = Controller(support, Mock(), Mock(), Mock())
		self.run_in_app(controller.register_pane, pane, public_pane)
		self.controller.handle_shortcut.side_effect = controller.handle_shortcut
		for query in ('re', ''):
			self.set_query(query)
			pane.clear_selection()
			selected = pane.get_file_under_cursor()
			self.assertTrue(self.key(Qt.Key_Space, ' '))
			self.assertEqual([selected], pane.get_selected_files())
			self.assertEqual(query, self.run_in_app(pane._filter_bar._input.text))
		self.set_query('<b>')
		self.assertEqual('Filter "<b>": 0 of 5 items', self.status())
		self.assertEqual(Qt.PlainText, self.run_in_app(self.window._status_bar_text.textFormat))
		self.window.show_status_message('<b>Copied</b>')
		self.assertEqual(Qt.AutoText, self.run_in_app(self.window._status_bar_text.textFormat))
		self.set_query('a' * 300)
		self.assertEqual(255, len(self.run_in_app(pane._filter_bar._input.text)))

	def test_file_creation_shortcuts_keep_editor_launch_separate(self):
		from core.commands import CreateAndEditFile, NewEmptyFile, OpenWithEditor
		from fman.impl.controller import Controller
		from fman.impl.plugins.command_registry import PaneCommandRegistry
		from fman.impl.plugins.key_bindings import KeyBindings
		from fman.url import as_url
		from pathlib import Path
		from PyQt5.QtCore import QTimer
		from PyQt5.QtTest import QTest
		from unittest.mock import Mock, patch
		import json
		pane = self.panes[0]
		completed = Event()
		errors = Mock()
		errors.report.side_effect = lambda *args: completed.set()
		callback = Mock()
		callback.after_command.side_effect = lambda *args: completed.set()
		registry = self.run_in_app(PaneCommandRegistry, errors, callback)
		bindings = KeyBindings()
		for name, command in (
			('new_empty_file', NewEmptyFile), ('create_and_edit_file', CreateAndEditFile),
			('open_with_editor', OpenWithEditor), ('open', Mock())
		):
			registry.register_command(name, command)
			bindings.register_command(name)
		path = Path(__file__).parents[3] / 'main/resources/base/Plugins/Core/Key Bindings.json'
		with path.open(encoding='utf-8') as stream:
			self.assertEqual([], bindings.load([
				binding for binding in json.load(stream)
				if binding['command'] in registry.get_commands()
			]))
		public_pane = Mock(get_commands=registry.get_commands,
			get_path=pane.get_location, get_file_under_cursor=pane.get_file_under_cursor,
			place_cursor_at=pane.place_cursor_at)
		public_pane.run_command.side_effect = lambda name, args: registry.execute_command(name, args, public_pane)
		support = Mock(get_sanitized_key_bindings=bindings.get_sanitized_bindings)
		controller = Controller(support, Mock(), Mock(), Mock())
		self.run_in_app(controller.register_pane, pane, public_pane)
		self.controller.handle_shortcut.side_effect = controller.handle_shortcut
		def answer(dialog):
			def accept():
				dialog.setTextValue(filename)
				QTest.keyClick(dialog, Qt.Key_Return)
			QTimer.singleShot(0, accept)
		self.run_in_app(self.window.before_dialog.connect, answer)
		with patch('fman._get_ui', return_value=self.window), \
			patch('core.commands.exists', side_effect=self.filesystem.exists), \
			patch('core.commands.is_dir', side_effect=self.filesystem.is_dir), \
			patch('core.commands.touch', side_effect=self.filesystem.touch), \
			patch('core.text_editor.open_file') as open_file:
			for filename, key, modifiers, command, existing in (
				('new.txt', Qt.Key_N, Qt.ControlModifier, 'new_empty_file', False),
				('existing.txt', Qt.Key_N, Qt.ControlModifier, 'new_empty_file', True),
				('edit.txt', Qt.Key_F4, Qt.ShiftModifier, 'create_and_edit_file', False),
			):
				with self.subTest(shortcut=command, existing=existing):
					target = self.root / filename
					if existing:
						target.write_bytes(b'Keep this content')
					completed.clear()
					public_pane.run_command.reset_mock()
					open_file.reset_mock()
					self.run_in_app(QTest.keyClick, pane._file_view, key, modifiers)
					self.assertTrue(completed.wait(5), 'Creation command did not finish')
					self.drain(pane)
					errors.report.assert_not_called()
					public_pane.run_command.assert_called_once_with(command, {})
					self.assertEqual(b'Keep this content' if existing else b'', target.read_bytes())
					if not existing:
						self.assertEqual(as_url(target), pane.get_file_under_cursor())
					if command == 'new_empty_file':
						open_file.assert_not_called()
					else:
						open_file.assert_called_once_with(as_url(target), 'editor')

	def test_full_update_performance(self):
		from fman.impl.filter_pattern import compile_filter
		from fman.impl.model.model import File
		from fman.impl.model.table import Cell
		from PyQt5.QtCore import QEvent
		from PyQt5.QtGui import QIcon, QKeyEvent
		from statistics import median
		from time import perf_counter
		def measure():
			pane = self.panes[0]
			model = pane._model.sourceModel()
			for size in (1000, 10000):
				names = ['Annual Report %05d %s.txt' % (index, 'a' * 200) for index in range(size)]
				rows = [File('file:///' + name, QIcon(), False,
					[Cell(name, name, name), Cell('', 0, 0), Cell('', 0, 0)], True) for name in names]
				pane._filter_bar.close()
				model._on_rows_inited_main(rows, rows, lambda: None)
				for query in ('rep', 'rep*txt', '?*?*?*?*?*?*?*?Z', 'a*a*a*a*a*a*a*a*Z', '*' * 100):
					matcher = compile_filter(query)
					matcher_times, handler_times = [], []
					for repeat in range(3):
						started = perf_counter()
						matched = sum(matcher.matches(name) for name in names)
						matcher_times.append(perf_counter() - started)
						pane._filter_bar._input.setText(query[:-1])
						started = perf_counter()
						pane._on_key_pressed(QKeyEvent(QEvent.KeyPress, Qt.Key_unknown, Qt.NoModifier, query[-1]))
						handler_times.append(perf_counter() - started)
						self.assertEqual(matched, pane._model.rowCount())
						self.assertEqual('Filter "%s": %d of %d items' % (query, matched, size), self.window._status_bar_text.text())
					print('Filter %d rows %r: matcher %.1fms, full key %.1fms' %
						(size, query[:20], median(matcher_times) * 1000, median(handler_times) * 1000))
					self.assertLess(max(handler_times), 5, 'Full filter update exceeded the generous regression ceiling')
		self.run_in_app(measure)

	def test_special_filenames_and_status_mode_changes(self):
		from fman.impl.status_bar import DEFAULT_SETTINGS, DISABLED, ACTIVE_PANE, PER_PANE
		from fman.url import as_url
		pane = self.panes[0]
		for name in ('$RECYCLE.BIN', '[draft] notes.txt', '!important', '^caret'):
			(self.root / name).write_bytes(b'')
		pane.reload()
		self.drain(pane)
		for query, name in [(r'\$RECYCLE.BIN', '$RECYCLE.BIN'), (r'\[draft]', '[draft] notes.txt'),
			(r'\!important', '!important'), (r'\^caret', '^caret'), ('[$]*.???$', '$RECYCLE.BIN')]:
			self.set_query(query)
			self.assertEqual('Filter "%s": 1 of 9 items' % query, self.status())
			self.assertEqual(as_url(self.root / name), pane.get_file_under_cursor())
		for mode in (ACTIVE_PANE, PER_PANE, DISABLED):
			self.window.set_extended_status_bar(dict(DEFAULT_SETTINGS, mode=mode))
			self.panes[1].focus()
			self.assertEqual('Ready.', self.status())
			pane.focus()
			self.assertEqual('Filter "[$]*.???$": 1 of 9 items', self.status())
		self.assertIsNone(self.window._status_service)
		original_width = self.run_in_app(self.window.width)
		self.set_query('a' * 255)
		self.run_in_app(QApplication.processEvents)
		self.assertEqual(original_width, self.run_in_app(self.window.width), 'Long count text resized the window')

class DirectorySizeIT(QtIT):
	def test_no_standalone_directory_size_plugin(self):
		from pathlib import Path
		bundled_plugins = Path(__file__).parents[3] / 'main/resources/base/Plugins'
		self.assertFalse((bundled_plugins / 'DirectorySize').exists(),
			'Directory sizes belong only to Core; the standalone plug-in adds a duplicate column.')

	def test_explicit_status_while_running_and_stale_results(self):
		from core import directory_size as module
		from fman.impl.widgets import MainWindow
		from threading import Thread
		from unittest.mock import Mock, patch
		window = self.run_in_app(MainWindow, Mock(), [], Mock(), Mock(), Mock(), 'null://')
		self.panes[0].place_cursor_at(self.url)
		command = module.ShowDirectorySize(self.panes[0])
		real_walk = module.walk_directory
		try:
			for action in ('complete', 'replace', 'dispose'):
				with self.subTest(action=action):
					entered, release, finished = Event(), Event(), Event()
					failures = []
					def walk(path, max_files, check):
						if entered.is_set():
							yield from real_walk(path, max_files, check)
							return
						entered.set()
						if not release.wait(5):
							raise AssertionError('Blocked explicit scan was not released')
						yield module.DirSize(7, 1, 1, complete=True)
					def calculate():
						try:
							command()
						except BaseException as error:
							failures.append(error)
						finally:
							finished.set()
					worker = Thread(target=calculate, daemon=True)
					with patch.object(module, 'walk_directory', side_effect=walk), \
						patch.object(module, 'show_status_message', side_effect=window.show_status_message) as status, \
						patch('fman._get_ui') as ui:
						ui.return_value.create_progress_dialog.side_effect = AssertionError('No progress dialog is allowed')
						try:
							worker.start()
							self.assertTrue(entered.wait(5))
							self.assertFalse(finished.is_set())
							def verify_running():
								self.assertEqual('Calculating %s size...' % self.child, window._status_bar_text.text())
								self.assertFalse(window._timer.isActive())
							self.run_in_app(verify_running)
							old_task = self.service._explicit_task
							if action == 'replace':
								command()
								self.assertTrue(old_task.cancel_event.is_set())
							elif action == 'dispose':
								self.owner.invalidate()
								self.assertTrue(old_task.cancel_event.is_set())
								window.show_status_message('Another command')
							before = status.call_count
							release.set()
							self.assertTrue(finished.wait(5))
							self.assertEqual([], failures)
							self.assertEqual(before + (action == 'complete'), status.call_count)
							expected = 'Another command' if action == 'dispose' else 'folder: 7 B (1 files)'
							self.assertEqual(expected, self.run_in_app(window._status_bar_text.text))
							self.assertIsNone(self.service._explicit_task)
							self.assertIsNone(self.service._executor)
							ui.return_value.create_progress_dialog.assert_not_called()
						finally:
							release.set()
							worker.join(5)
							self.assertFalse(worker.is_alive())
		finally:
			self.run_in_app(window.close)
			self.run_in_app(window.deleteLater)

	def test_full_core_startup_and_persisted_size_toggle(self):
		import json
		import os
		import subprocess
		import sys
		from textwrap import dedent
		(self.root / 'plain.txt').write_bytes(b'abc')
		settings_dir = self.root / 'UserSettings/Plugins/User/Settings'
		settings_dir.mkdir(parents=True)
		(settings_dir / 'DirectorySize (Windows).json').write_text(
			json.dumps({'enabled': False, 'max_entries': 200000}), encoding='utf-8')
		script = r'''
import sys, traceback
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from fman.impl.application_context import get_application_context
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import as_url
from PyQt5.QtCore import QTimer

requested_root, phase = Path(sys.argv[1]), sys.argv[2]
root = requested_root.resolve()
context = get_application_context()
app = context.app
context.session_manager.is_first_run = False
sys.argv = [sys.argv[0], str(requested_root), str(requested_root)]
gui = lambda operation: run_in_main_thread(operation)()

def wait_for(predicate):
	ready = Event()
	def start():
		timer = QTimer(context.main_window)
		timer.setInterval(10)
		deadline = monotonic() + 10
		def check():
			if predicate():
				ready.set()
			if ready.is_set() or monotonic() > deadline:
				timer.stop()
				timer.deleteLater()
		timer.timeout.connect(check)
		timer.start()
		check()
	gui(start)
	assert ready.wait(12), gui(lambda: 'Source application did not reach expected state: '
		'phase=%s, requested_path=%r, expected_path=%r, panes=%r' % (
			phase, as_url(requested_root), as_url(root),
			[(pane.get_path(), tuple(pane.get_columns()), size_cell(pane, root / 'plain.txt'))
				for pane in context.window.get_panes()]))

def size_cell(pane, path):
	model = pane._widget._model
	try:
		return model.index(model.find(as_url(path)).row(), 1).data()
	except ValueError:
		return None

def exercise():
	code = 1
	try:
		wait_for(lambda: len(context.window.get_panes()) == 2 and all(
			pane.get_path() == as_url(root) and size_cell(pane, root / 'plain.txt') == '3 B'
			for pane in context.window.get_panes()))
		from core import directory_size
		service = directory_size._service
		assert service is not None
		assert service.enabled == (phase == 'restore')
		assert service.settings['max_files'] == 10000000
		assert gui(lambda: 'Directory sizes:' not in context.main_window._status_bar_text.text())
		if phase == 'restore':
			wait_for(lambda: all(size_cell(pane, root / 'folder') == '7 B' for pane in context.window.get_panes()))
		gui(lambda: context.plugin_support.run_application_command('toggle_directory_size_column'))
		enabled = phase == 'enable'
		wait_for(lambda: service.enabled == enabled and all(
			size_cell(pane, root / 'folder') == ('7 B' if enabled else '')
			for pane in context.window.get_panes()))
		def verify():
			for pane in context.window.get_panes():
				assert tuple(pane.get_columns()) == ('core.Name', 'core.Size', 'core.Modified')
				assert size_cell(pane, root / 'plain.txt') == '3 B'
			assert context.main_window._status_bar_text.text() == 'Directory sizes: ' + ('On' if enabled else 'Off')
			if not enabled:
				assert service._executor is None and not service._callbacks
		gui(verify)
		print('PASS: full Core startup %s, stable Size column, file sizes and persisted toggle' % phase, flush=True)
		code = 0
	except Exception:
		traceback.print_exc()
	finally:
		def stop():
			from core import directory_size
			if directory_size._service is not None:
				directory_size._service.owner.invalidate()
			models = [pane._widget._model.sourceModel() for pane in context.window.get_panes()]
			for model in models:
				model.shutdown()
			return models
		for model in gui(stop):
			model._worker._thread.join(2)
		gui(lambda: app.exit(code))

QTimer.singleShot(0, lambda: Thread(target=exercise, daemon=True).start())
sys.exit(context.run())
'''
		for phase in ('enable', 'restore'):
			with self.subTest(phase=phase):
				root_argument = self.root / '..' / self.root.name
				result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', dedent(script), str(root_argument), phase],
					env=dict(os.environ, ROYIFILEMANAGER_USER_SETTINGS=str(self.root / 'UserSettings')),
					capture_output=True, text=True, timeout=40)
				self.assertEqual(0, result.returncode, result.stdout + result.stderr)
				self.assertNotIn('Traceback', result.stderr)
				print(result.stdout.strip())

	def test_column_restore_ignores_deleted_widget(self):
		from fman.impl.widgets import DirectoryPaneWidget
		from PyQt5 import sip
		from unittest.mock import Mock, patch
		widget = self.run_in_app(DirectoryPaneWidget, self.filesystem, 'null://', self.parent, Mock())
		model = self.run_in_app(widget._model.sourceModel)
		ready = Event()
		model._worker.submit(100, ready.set)
		self.assertTrue(ready.wait(5))
		callbacks = []
		with patch.object(widget._model, 'set_extra_columns', side_effect=lambda *args: callbacks.append(args[-1])):
			widget.set_extra_columns(self.owner, {})
		self.run_in_app(model.shutdown)
		model._worker._thread.join(5)
		self.assertFalse(model._worker._thread.is_alive())
		def dispose_and_deliver():
			sip.delete(widget)
			self.assertTrue(sip.isdeleted(widget._model))
			callbacks[0]()
		self.run_in_app(dispose_and_deliver)

	def test_toggle_notification_replacement_and_expiry_preserve_status_modes(self):
		from fman.impl.status_bar import DISABLED, ACTIVE_PANE, PER_PANE
		from fman.impl.widgets import MainWindow
		from PyQt5.QtWidgets import QLabel
		from unittest.mock import Mock, patch
		window = self.run_in_app(MainWindow, Mock(), [], Mock(), Mock(), Mock(), 'null://')
		try:
			with patch('core.directory_size.save_json'), \
				patch('core.directory_size.scan_parents'), \
				patch('core.directory_size.show_status_message', side_effect=window.show_status_message):
				for mode in (DISABLED, ACTIVE_PANE, PER_PANE):
					window.set_extended_status_bar({'mode': mode, 'size_divisor': 1024, 'max_entries': 200000})
					labels = self.run_in_app(window.findChildren, QLabel)
					self.service.toggle()
					self.service.toggle()
					def check():
						self.assertEqual('Directory sizes: Off', window._status_bar_text.text())
						self.assertEqual(5000, window._timer.interval())
						self.assertTrue(window._timer.isActive())
						self.assertEqual(mode, window._extended_status_mode)
						self.assertEqual(labels, window.findChildren(QLabel))
						window._timer.timeout.emit()
						self.assertEqual('Ready.', window._status_bar_text.text())
						self.assertFalse(window._timer.isActive())
						window.show_status_message('Directory sizes: On', timeout_secs=5)
						window.show_status_message('Another command')
						self.assertEqual('Another command', window._status_bar_text.text())
						self.assertFalse(window._timer.isActive())
					self.run_in_app(check)
		finally:
			self.run_in_app(window.close)
			self.run_in_app(window.deleteLater)

	def test_core_registered_keys_service_restart_and_explicit_task(self):
		import core
		from core import directory_size as module
		from fman import ApplicationCommand
		from fman.impl.controller import Controller
		from fman.impl.plugins import PluginSupport
		from fman.impl.plugins.command_registry import ApplicationCommandRegistry, PaneCommandRegistry
		from fman.impl.plugins.config import Config
		from fman.impl.plugins.key_bindings import KeyBindings
		from fman.impl.plugins.plugin import ExternalPlugin
		from fman.impl.session import SessionManager
		from fman.url import as_url
		from pathlib import Path
		from PyQt5.QtCore import QEvent
		from PyQt5.QtGui import QKeyEvent
		from unittest.mock import Mock, patch
		import json
		self.owner.invalidate()
		bundled_plugins = Path(__file__).parents[3] / 'main/resources/base/Plugins'
		plugin_path = self.root / 'Core'
		plugin_path.mkdir()
		core_path = bundled_plugins / 'Core'
		config = Config('Windows')
		bindings = KeyBindings()
		finished = Event()
		callbacks = Mock()
		callbacks.after_command.side_effect = lambda *args: finished.set()
		def create_registries():
			return ApplicationCommandRegistry(Mock(), self.errors, callbacks), PaneCommandRegistry(self.errors, callbacks)
		applications, commands = self.run_in_app(create_registries)
		palette = Mock()
		class Palette(ApplicationCommand):
			def __call__(self):
				palette()
		applications.register_command('command_palette', Palette)
		bindings.register_command('command_palette')
		with (core_path / 'Key Bindings (Windows).json').open(encoding='utf-8') as stream:
			core_bindings = json.load(stream)
		palette_binding = [binding for binding in core_bindings if binding['keys'] == ['Ctrl+Shift+P']]
		feature_bindings = [binding for binding in core_bindings if binding['command'] in
			('toggle_directory_size_column', 'sort_by_directory_size', 'show_directory_size')]
		self.assertEqual(3, len(feature_bindings))
		self.assertEqual([], bindings.load(palette_binding))
		context = Mock()
		context.load.return_value = []
		plugin = ExternalPlugin(str(plugin_path), config, Mock(), Mock(), context,
			self.errors, applications, commands, bindings, self.filesystem, Mock())
		feature_classes = tuple(getattr(core, name) for name in ('DirectorySizeService',
			'ToggleDirectorySizeColumn', 'SortByDirectorySize', 'ShowDirectorySize', 'RecalculateDirectorySizes'))
		def load_feature_bindings():
			self.assertEqual([], bindings.load(feature_bindings))
			plugin._add_unload_action(bindings.unload, feature_bindings)
		support = PluginSupport(lambda path: plugin, applications, bindings, context, config)
		controller = Controller(support, Mock(), Mock(), Mock())
		for pane, widget in zip(self.panes, self.widgets):
			pane._command_registry = commands
			self.run_in_app(controller.register_pane, widget, pane)
		def shortcut(key, modifiers=Qt.ControlModifier | Qt.ShiftModifier):
			finished.clear()
			self.assertTrue(self.run_in_app(controller.handle_shortcut, self.widgets[0], QKeyEvent(QEvent.KeyPress, key, modifiers)))
			self.assertTrue(finished.wait(5), 'Registered command did not finish')
		with patch.object(plugin, '_load_packages', return_value=[core]), \
			patch.object(plugin, '_iterate_classes', return_value=feature_classes), \
			patch.object(plugin, '_load_key_bindings', side_effect=load_feature_bindings), \
			patch.object(module, 'load_json', side_effect=config.load_json), \
			patch.object(module, 'save_json', side_effect=config.save_json), \
			patch('fman.fs._get_mother_fs', return_value=self.filesystem), \
			patch.object(module, 'show_status_message') as status, patch.object(module, 'show_alert') as alert, \
			patch('fman._get_ui') as ui:
			try:
				self.assertTrue(support.load_plugin(str(plugin_path)))
				config.add_dir(str(self.root / 'UserSettings'))
				self.service = plugin._services[0]
				self.owner = self.service.owner
				self.assertFalse(self.service.enabled)
				self.assertIsNone(self.service._executor)
				self.assertEqual({}, self.service._callbacks)
				self.assertIn('toggle_directory_size_column', applications.get_commands())
				self.assertEqual(('Toggle directory sizes',), applications.get_command_aliases('toggle_directory_size_column'))
				self.assertTrue(applications.is_command_visible('toggle_directory_size_column'))
				shortcut(Qt.Key_P)
				palette.assert_called_once()
				status.assert_not_called()
				shortcut(Qt.Key_D)
				self.service._future.result(5)
				self.drain_models()
				status.assert_called_once_with('Directory sizes: On', timeout_secs=5)
				self.assertTrue(config.load_json('DirectorySize.json')['enabled'])
				for pane in self.panes:
					self.assertEqual(self.columns, tuple(pane.get_columns()))
				shortcut(Qt.Key_F4, Qt.ControlModifier)
				self.drain_models()
				self.assertEqual((module.COLUMN, True), self.panes[0].get_sort_column())
				self.widgets[0].set_column_widths([191, 93])
				manager = SessionManager({}, self.filesystem, self.errors, 'test', True)
				saved = manager._read_pane_settings(self.widgets[0])
				support.unload_plugin(str(plugin_path))
				self.assertEqual(self.columns, tuple(self.panes[0].get_columns()))
				self.assertIsNone(module._service)
				self.assertEqual([], [binding for binding in bindings.get_sanitized_bindings() if binding['command'] == 'toggle_directory_size_column'])
				self.assertTrue(support.load_plugin(str(plugin_path)))
				self.service = plugin._services[0]
				self.owner = self.service.owner
				self.assertTrue(config.load_json('DirectorySize.json')['enabled'],
					'Reloading the plug-in lost the persisted setting')
				self.assertTrue(self.service.enabled,
					'Restored service settings: %r' % self.service.settings)
				self.service._future.result(5)
				self.drain_models()
				manager._init_pane(self.panes[0], None, saved)
				self.drain_models()
				self.assertEqual([191, 93], self.widgets[0].get_column_widths())
				self.assertEqual(1, status.call_count, 'Startup/reload must not notify')
				finished.clear()
				self.run_in_app(support.run_application_command, 'toggle_directory_size_column')
				self.assertTrue(finished.wait(5))
				self.assertEqual('Directory sizes: Off', status.call_args.args[0])
				self.assertFalse(self.service.enabled)
				self.drain_models()
				self.panes[0].place_cursor_at(self.url)
				ui.return_value.create_progress_dialog.side_effect = AssertionError('No progress dialog is allowed')
				before = status.call_count
				shortcut(Qt.Key_Return)
				self.assertEqual(('Calculating %s size...' % self.child,), status.call_args_list[before].args)
				self.assertEqual('folder: 7 B (1 files)', status.call_args.args[0])
				self.assertIsNone(self.service._executor)
				ui.return_value.create_progress_dialog.assert_not_called()
				before = status.call_count
				with patch.object(module._DirectorySizeTask, 'check_canceled', side_effect=module.Task.Canceled):
					shortcut(Qt.Key_Return)
				self.assertEqual(before + 2, status.call_count)
				self.assertEqual('Directory size calculation canceled.', status.call_args.args[0])
				override = [{'keys': ['Ctrl+Shift+D'], 'command': 'command_palette'}]
				self.assertEqual([], bindings.load(override))
				shortcut(Qt.Key_D)
				self.assertEqual(2, palette.call_count)
				self.assertFalse(self.service.enabled)
				alert.assert_not_called()
				self.errors.report.assert_not_called()
			finally:
				plugin.unload()

	def setUp(self):
		from core import Name, Size, Modified
		from core.fs.local import LocalFileSystem
		from core.directory_size import DirectorySizeService
		from fman import DirectoryPane
		from fman.impl.plugins.builtin import NullFileSystem, NullColumn
		from fman.impl.plugins.command_registry import PaneCommandRegistry
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from fman.impl.plugins.plugin import FileSystemWrapper
		from fman.impl.ui import UiOwner
		from fman.impl.widgets import DirectoryPaneWidget
		from fman.url import as_url
		from pathlib import Path
		from PyQt5.QtGui import QIcon
		from PyQt5.QtWidgets import QWidget
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		self.temporary = TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name)
		self.child = self.root / 'folder'
		self.child.mkdir()
		(self.child / 'file.txt').write_bytes(b'payload')
		self.url = as_url(self.child)
		self.errors = Mock()
		self.filesystem = MotherFileSystem(Mock(get_icon=Mock(return_value=QIcon())))
		for backend in (LocalFileSystem(), NullFileSystem()):
			self.filesystem.add_child(backend.scheme, FileSystemWrapper(backend, self.filesystem, self.errors))
		for column in (Name(self.filesystem), Size(self.filesystem), Modified(self.filesystem), NullColumn()):
			self.filesystem.register_column(column.get_qualified_name(), column)
		self.owner = UiOwner()
		self.service = DirectorySizeService(Mock(), self.owner)
		self.owner.attach(self.service.dispose)
		self.service.start()
		def create():
			self.parent = QWidget()
			registry = PaneCommandRegistry(self.errors, Mock())
			self.widgets = [DirectoryPaneWidget(self.filesystem, 'null://', self.parent, Mock()) for index in range(2)]
			self.panes = [DirectoryPane(Mock(), widget, registry) for widget in self.widgets]
			self.parent.show()
		self.run_in_app(create)
		self.addCleanup(self.close_panes)
		for pane in self.panes:
			loaded = Event()
			pane.set_path(as_url(self.root), callback=loaded.set)
			self.assertTrue(loaded.wait(5))
			with patch('core.directory_size.load_json', return_value={}):
				self.service.on_pane_added(pane)
		self.drain_models()
		self.columns = ('core.Name', 'core.Size', 'core.Modified')
		self.assertEqual(self.columns, tuple(self.panes[0].get_columns()))

	def test_startup_reads_settings_after_plugin_layers_are_loaded(self):
		from core.directory_size import DirectorySizeService
		from fman.impl.plugins.config import Config
		from fman.impl.ui import UiOwner
		from unittest.mock import Mock, patch
		self.owner.invalidate()
		config = Config('Windows')
		config.add_dir(str(self.root / 'Core'))
		self.owner = UiOwner()
		self.service = DirectorySizeService(Mock(), self.owner)
		self.owner.attach(self.service.dispose)
		with patch('core.directory_size.load_json', side_effect=config.load_json) as load:
			self.service.start()
			load.assert_not_called()
			config.add_dir(str(self.root / 'AnotherPlugin'))
			config.add_dir(str(self.root / 'Settings'))
			config.save_json('DirectorySize.json', {'enabled': True, 'max_files': 2})
			with patch('core.directory_size.scan_parents') as scan:
				for pane in self.panes:
					self.service.on_pane_added(pane)
				self.service._future.result(5)
			self.assertTrue(self.service.enabled)
			self.assertEqual(2, self.service.settings['max_files'])
			self.assertEqual(2, scan.call_args.args[1])
			load.assert_called_once_with('DirectorySize.json', default={})

	def close_panes(self):
		self.owner.invalidate()
		def close():
			models = [widget._model.sourceModel() for widget in self.widgets]
			for model in models:
				model.shutdown()
			self.parent.close()
			self.parent.deleteLater()
			return models
		for model in self.run_in_app(close):
			model._worker._thread.join(2)

	def drain_models(self):
		for widget in self.widgets:
			done = Event()
			self.run_in_app(lambda: widget._model.sourceModel()._worker.submit(100, done.set))
			self.assertTrue(done.wait(5), 'Model work did not finish')

	def test_toggle_preserves_pane_state_and_named_widths(self):
		from core.directory_size import COLUMN, SortByDirectorySize
		from fman.impl.session import SessionManager
		from unittest.mock import Mock, patch
		pane = self.panes[0]
		widget = self.widgets[0]
		paths_changed = Mock()
		unsubscribe = pane.on_path_changed(paths_changed)
		self.addCleanup(unsubscribe)
		pane.place_cursor_at(self.url)
		pane.select([self.url])
		pane.set_sort_column('core.Size', False)
		self.run_in_app(widget._filter_bar._input.setText, 'folder')
		widget.set_column_widths([171, 83])
		self.drain_models()
		model = self.run_in_app(widget._model.sourceModel)
		with patch('core.directory_size.scan_parents') as scan, \
			patch.object(widget, 'set_extra_columns', side_effect=AssertionError('Column layout must not change')):
			self.service.set_enabled(True)
			self.service._future.result(5)
			self.drain_models()
			for candidate in self.panes:
				self.assertEqual(self.columns, tuple(candidate.get_columns()))
			self.assertIs(model, self.run_in_app(widget._model.sourceModel))
			self.assertEqual(self.url, pane.get_file_under_cursor())
			self.assertEqual([self.url], pane.get_selected_files())
			self.assertEqual(('core.Size', False), pane.get_sort_column())
			self.assertEqual('folder', self.run_in_app(widget._filter_bar._input.text))
			self.assertEqual([171, 83], widget.get_column_widths()[:2])
			paths_changed.assert_not_called()
			SortByDirectorySize(pane)()
			self.drain_models()
			self.assertEqual((COLUMN, True), pane.get_sort_column())
			SortByDirectorySize(pane)()
			self.drain_models()
			self.assertEqual((COLUMN, False), pane.get_sort_column())
			saved = SessionManager({}, None, None, 'test', True)._read_pane_settings(widget)
			self.assertEqual([171, 83], saved['col_widths'])
			self.assertEqual(83, saved['column_widths_by_name'][COLUMN])
			self.assertNotIn('core.Modified', saved['column_widths_by_name'])
			self.service.set_enabled(False)
			self.drain_models()
			self.assertEqual((COLUMN, False), pane.get_sort_column())
			self.assertEqual(self.columns, tuple(pane.get_columns()))
			self.assertIs(model, self.run_in_app(widget._model.sourceModel))
			self.assertEqual([171, 83], widget.get_column_widths())
			self.assertEqual([self.url], pane.get_selected_files())
			self.assertFalse(self.service._callbacks)
			self.assertIsNone(self.service._executor)
			self.service.restart()
			self.assertEqual(1, scan.call_count)
			paths_changed.assert_not_called()
		self.errors.report.assert_not_called()

	def test_incremental_delivery_and_navigation_while_scan_is_blocked(self):
		from core.directory_size import COLUMN, DirSize
		from fman.url import as_url
		from PyQt5.QtCore import QThread
		from threading import get_ident
		from time import monotonic
		from unittest.mock import patch
		started, restarted, release, delivered = Event(), Event(), Event(), Event()
		worker_threads, delivery_threads = [], []
		original = self.service._delivery._receive
		def receive(generation, results):
			delivery_threads.append(QThread.currentThread())
			original(generation, results)
			delivered.set()
		self.service._delivery._receive = receive
		def scan(paths, limit, check, publish):
			worker_threads.append(get_ident())
			publish({str(self.child): DirSize(3, 1, 1)})
			(started if len(worker_threads) == 1 else restarted).set()
			release.wait(10)
			publish({str(self.child): DirSize(7, 1, 1, True)})
		start = monotonic()
		futures, executors = [], []
		with patch('core.directory_size.scan_parents', side_effect=scan):
			try:
				self.service.set_enabled(True)
				future = self.service._future
				futures.append(future)
				executors.append(self.service._executor)
				self.assertTrue(started.wait(5))
				self.assertTrue(delivered.wait(5))
				self.drain_models()
				def read_cell():
					model = self.widgets[0]._model
					return model.index(model.find(self.url).row(), self.columns.index(COLUMN)).data()
				self.assertEqual('3 B...', self.run_in_app(read_cell))
				self.assertEqual([QApplication.instance().thread()], delivery_threads)
				qt_thread = self.run_in_app(get_ident)
				model_threads = self.run_in_app(lambda: [widget._model.sourceModel()._worker._thread.ident for widget in self.widgets])
				self.assertNotIn(worker_threads[0], [qt_thread] + model_threads)
				loaded = Event()
				self.panes[0].set_path(as_url(self.child), callback=loaded.set)
				self.assertTrue(loaded.wait(5), 'Navigation blocked behind directory walk')
				self.service.set_enabled(False)
				self.assertEqual(self.columns, tuple(self.panes[0].get_columns()))
				self.assertFalse(future.done())
				generation = self.service._generation
				self.run_in_app(self.service._receive, generation - 1, {str(self.child): DirSize(999, complete=True)})
				self.assertIsNone(self.service.result(self.url))
				self.service.set_enabled(True)
				futures.append(self.service._future)
				executors.append(self.service._executor)
				self.assertTrue(restarted.wait(5), 'Re-enable waited for the canceled scan')
				self.run_in_app(self.service._receive, generation - 1, {str(self.child): DirSize(999, complete=True)})
				self.assertNotEqual(999, self.service.result(self.url).size_bytes)
				self.owner.invalidate()
				self.assertFalse(self.service._callbacks)
				self.assertIsNone(self.service._executor)
				self.assertTrue(all(not candidate.done() for candidate in futures))
				self.assertEqual(self.columns, tuple(self.panes[1].get_columns()))
			finally:
				release.set()
				for candidate in futures:
					candidate.result(5)
				for executor in executors:
					for thread in executor._threads:
						thread.join(5)
						self.assertFalse(thread.is_alive(), 'Canceled automatic worker did not exit')
		self.drain_models()
		self.assertIsNone(self.service.result(self.url))
		print('DirectorySize blocked-scan smoke: first result, navigation, re-enable/dispose %.3fs; stale final rejected; workers stopped' % (monotonic() - start))

	def test_real_scan_and_empty_pane_width_restore(self):
		from fman.url import as_url
		from unittest.mock import patch
		self.service.set_enabled(True)
		self.service._future.result(5)
		self.run_in_app(lambda: None)
		self.drain_models()
		self.assertEqual(7, self.service.result(self.url).size_bytes)
		empty = self.root / 'empty'
		empty.mkdir()
		loaded = Event()
		self.panes[0].set_path(as_url(empty), callback=loaded.set)
		self.assertTrue(loaded.wait(5))
		self.drain_models()
		with patch('core.directory_size.scan_parents'):
			from PyQt5.QtCore import QThread
			threads = []
			original = self.widgets[0]._apply_column_widths
			def apply_widths():
				threads.append(QThread.currentThread())
				original()
			with patch.object(self.widgets[0], '_apply_column_widths', side_effect=apply_widths):
				self.service.set_enabled(False)
				self.drain_models()
				self.widgets[0].restore_column_widths({'core.Name': 181, 'core.Size': 91})
			self.assertTrue(threads)
			self.assertTrue(all(thread == QApplication.instance().thread() for thread in threads))
			self.assertEqual([181, 91], self.widgets[0].get_column_widths())

	def test_navigation_preserves_core_size_sort(self):
		from core.directory_size import COLUMN
		from fman.url import as_url
		self.service.set_enabled(True)
		loaded = Event()
		self.widgets[0].set_location(as_url(self.child), COLUMN, False, loaded.set)
		self.assertTrue(loaded.wait(5))
		self.drain_models()
		self.assertEqual((COLUMN, False), self.panes[0].get_sort_column())

	def test_nested_pane_pending_rows_do_not_inherit_parent_totals(self):
		from core.directory_size import DirSize
		from fman.url import as_url
		from unittest.mock import patch
		nested = self.child / 'nested'
		nested.mkdir()
		nested_url = as_url(nested)
		loaded = Event()
		self.panes[1].set_path(as_url(self.child), callback=loaded.set)
		self.assertTrue(loaded.wait(5))
		def read_cell():
			model = self.widgets[1]._model
			return model.index(model.find(nested_url).row(), 1).data()
		with patch('core.directory_size.scan_parents'):
			self.service.set_enabled(True)
			self.service._future.result(5)
			self.drain_models()
			for parent in (DirSize(12), DirSize(12, complete=True), DirSize(12, errors=True)):
				self.run_in_app(self.service._receive, self.service._generation, {str(self.child): parent})
				self.widgets[1].refresh_files([nested_url])
				self.drain_models()
				self.assertEqual('...', self.run_in_app(read_cell))
			self.run_in_app(self.service._receive, self.service._generation,
				{str(self.child): DirSize(None, complete=True, errors=True)})
			self.drain_models()
			self.assertEqual('?', self.run_in_app(read_cell))
			self.run_in_app(self.service._receive, self.service._generation,
				{str(nested): DirSize(3, complete=True)})
			self.drain_models()
			self.assertEqual('3 B', self.run_in_app(read_cell))

class ProcessPaneIT(QtIT):
	def setUp(self):
		from core import Name, Size, Modified
		from core.commands import MoveToTrash, Copy, Move, DragAndDropListener
		from core.fs.local import LocalFileSystem
		from fman import DirectoryPane
		from fman.impl.controller import Controller
		from fman.impl.plugins import PluginSupport
		from fman.impl.plugins.builtin import NullFileSystem, NullColumn
		from fman.impl.plugins.command_registry import ApplicationCommandRegistry, PaneCommandRegistry
		from fman.impl.plugins.config import Config
		from fman.impl.plugins.key_bindings import KeyBindings
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from fman.impl.plugins.plugin import ExternalPlugin, FileSystemWrapper
		from fman.impl.widgets import MainWindow
		from pathlib import Path
		from PyQt5.QtGui import QIcon
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		import json
		import sys
		previous_modules = {name: module for name, module in sys.modules.items()
			if name == 'process_pane' or name.startswith('process_pane.')}
		self.addCleanup(sys.modules.update, previous_modules)
		self.temporary = TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name)
		(self.root / 'sample.txt').write_text('test', encoding='utf-8')
		self.errors = Mock()
		self.finished = Event()
		callbacks = Mock()
		callbacks.after_command.side_effect = lambda *args: self.finished.set()
		self.filesystem = MotherFileSystem(Mock(get_icon=Mock(return_value=QIcon())))
		for backend in (LocalFileSystem(), NullFileSystem()):
			self.filesystem.add_child(backend.scheme, FileSystemWrapper(backend, self.filesystem, self.errors))
		for column in (Name(self.filesystem), Size(self.filesystem), Modified(self.filesystem), NullColumn()):
			self.filesystem.register_column(column.get_qualified_name(), column)
		applications, commands = self.run_in_app(lambda: (
			ApplicationCommandRegistry(Mock(), self.errors, callbacks), PaneCommandRegistry(self.errors, callbacks)))
		bindings = KeyBindings()
		for name, command in (('move_to_trash', MoveToTrash), ('copy', Copy), ('move', Move)):
			commands.register_command(name, command)
			bindings.register_command(name)
		plugins = Path(__file__).parents[3] / 'main/resources/base/Plugins'
		with (plugins / 'Core/Key Bindings.json').open(encoding='utf-8') as stream:
			binding = [entry for entry in json.load(stream) if entry['keys'] == ['F8']]
		self.assertEqual(1, len(binding))
		self.assertEqual([], bindings.load(binding))
		config = Config('Windows')
		context = Mock()
		plugin = ExternalPlugin(str(plugins / 'ProcessPane'), config, Mock(), Mock(), context,
			self.errors, applications, commands, bindings, self.filesystem, Mock())
		self.support = PluginSupport(lambda path: plugin, applications, bindings, context, config)
		self.plugin_path = str(plugins / 'ProcessPane')
		self.assertTrue(self.support.load_plugin(self.plugin_path))
		self.module = sys.modules['process_pane']
		from process_pane.processes import ProcessRecord
		self.provider = Mock()
		self.records = [ProcessRecord(12, 'report.exe', 100), ProcessRecord(2, 'other.exe', 200)]
		self.provider.snapshot.side_effect = lambda: list(self.records)
		for target, options in (
			('process_pane.get_provider', {'return_value': self.provider}),
			('process_pane.show_alert', {'return_value': self.module.NO}),
			('process_pane.show_status_message', {}),
			('process_pane.submit_task', {'side_effect': lambda task: task()}),
			('fman.fs._get_mother_fs', {'return_value': self.filesystem}),
		):
			patcher = patch(target, **options)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.controller = Controller(self.support, Mock(), Mock(), Mock())
		def create():
			self.window = MainWindow(QApplication.instance(), [], Mock(), Mock(), self.filesystem, 'null://')
			self.window.set_controller(self.controller)
			self.panes = [self.window.add_pane() for index in range(2)]
			public_window = Mock()
			self.public_panes = [DirectoryPane(public_window, widget, commands) for widget in self.panes]
			public_window.get_panes.return_value = self.public_panes
			for widget, pane in zip(self.panes, self.public_panes):
				pane._add_listener(DragAndDropListener(pane))
				self.controller.register_pane(widget, pane)
			self.window.resize(960, 600)
			self.window.show()
		self.run_in_app(create)
		self.addCleanup(self.close_window)
		self.addCleanup(self.unload_process_plugin)
		for pane in self.panes:
			FilterBarIT.navigate(self, pane, self.root)
		self.provider.snapshot.assert_not_called()

	drain = FilterBarIT.drain
	close_window = FilterBarIT.close_window
	set_query = FilterBarIT.set_query

	def unload_process_plugin(self):
		self.support.unload_plugin(self.plugin_path)
		for pane in self.panes:
			self.drain(pane)
		self.errors.report.assert_not_called()

	def navigate_processes(self, index=0):
		loaded = Event()
		self.public_panes[index].set_path('process://', callback=loaded.set)
		self.assertTrue(loaded.wait(5), 'Process pane did not load')
		self.drain(self.panes[index])
		self.errors.report.assert_not_called()

	def press_f8(self, index=0):
		from PyQt5.QtCore import QEvent
		from PyQt5.QtGui import QKeyEvent
		self.finished.clear()
		self.assertTrue(self.run_in_app(self.controller.handle_shortcut, self.panes[index],
			QKeyEvent(QEvent.KeyPress, Qt.Key_F8, Qt.NoModifier)))
		self.assertTrue(self.finished.wait(5), 'F8 command did not finish')
		self.drain(self.panes[index])
		self.errors.report.assert_not_called()

	def test_real_registry_filter_sort_reload_and_f8(self):
		self.navigate_processes()
		pane = self.public_panes[0]
		self.assertEqual(['core.Name', 'process_pane.Pid'], list(pane.get_columns()))
		pane.set_sort_column('process_pane.Pid')
		self.drain(self.panes[0])
		self.assertIn('~2~', pane.get_file_under_cursor())
		self.set_query('rep')
		self.assertEqual(1, self.run_in_app(self.panes[0]._model.rowCount))
		self.assertIn('report.exe', pane.get_file_under_cursor())
		self.press_f8()
		self.provider.end.assert_not_called()
		self.assertEqual(self.module.NO, self.module.show_alert.call_args.args[2])
		self.module.show_alert.return_value = self.module.YES
		self.press_f8()
		self.assertEqual(self.records[0], self.provider.end.call_args.args[0])
		self.module.show_status_message.assert_called_once()
		self.provider.snapshot.assert_called()
		self.assertEqual(2, self.provider.snapshot.call_count)
		self.set_query('')
		self.records = []
		pane.reload()
		self.drain(self.panes[0])
		self.assertEqual(0, self.run_in_app(self.panes[0]._model.rowCount))

	def test_file_delete_keeps_core_confirmation_and_transfers_are_blocked(self):
		from core.commands import DragAndDropListener
		from fman.url import as_url
		from unittest.mock import patch
		self.navigate_processes()
		with patch('core.commands.show_alert', return_value=self.module.NO) as file_alert:
			self.press_f8(1)
			file_alert.assert_called_once()
			self.assertEqual(self.module.YES, file_alert.call_args.args[2])
		self.module.show_alert.assert_not_called()
		for command in ('copy', 'move'):
			self.public_panes[1].run_command(command)
			self.assertIn('Processes are not files', self.module.show_alert.call_args.args[0])
		folder = self.root / 'folder'
		folder.mkdir()
		for source in (self.root / 'sample.txt', folder):
			for destination in ('process://', 'process://' + self.records[0].path(1)):
				DragAndDropListener(self.public_panes[0]).on_files_dropped([as_url(source)], destination, True)
				self.assertIn('Processes are not files', self.module.show_alert.call_args.args[0])
		self.assertEqual(1, self.provider.snapshot.call_count)
		self.provider.end.assert_not_called()
		self.assertTrue((self.root / 'sample.txt').exists())
		self.errors.report.assert_not_called()

	def test_stale_session_restores_root_and_two_panes_reject_old_row(self):
		from fman.impl.session import SessionManager
		from process_pane.processes import ProcessRecord
		manager = SessionManager({}, self.filesystem, self.errors, 'test', True)
		manager._init_pane(self.public_panes[0], None, {'location': 'process://gone~123~99'})
		self.drain(self.panes[0])
		self.assertEqual('process://', self.public_panes[0].get_path())
		self.assertEqual(1, self.provider.snapshot.call_count)
		old = self.public_panes[0].get_file_under_cursor()
		self.records = [ProcessRecord(2, 'other.exe', 999)]
		self.navigate_processes(1)
		self.public_panes[1].reload()
		self.drain(self.panes[1])
		self.assertIn('~3e7', self.public_panes[1].get_file_under_cursor())
		self.module.show_alert.return_value = self.module.YES
		self.public_panes[0].run_command('move_to_trash', {'urls': [old]})
		self.assertIn('Refresh', self.module.show_alert.call_args.args[0])
		self.provider.end.assert_not_called()
		self.module.show_status_message.assert_not_called()
		self.drain(self.panes[0])
		self.assertEqual(2, self.provider.snapshot.call_count)
		self.errors.report.assert_not_called()


class RunInThreadIT(RunInThreadAT, QtIT):
	pass

class ArchiveTransferIT(QtIT):
	def test_quiet_transfer_cancel_keeps_dialog_modeless(self):
		from core.fs.zip import _7zipTaskWithProgress
		from core.tests.fs.test_zip import FakePipeProcess
		from fman import Task
		from fman.impl.widgets import ProgressDialog
		from PyQt5.QtCore import QThread, QTimer
		from PyQt5.QtGui import QPalette
		from PyQt5.QtWidgets import QWidget
		from unittest.mock import patch
		process = FakePipeProcess(quiet=True)
		started = Event()
		original = process.output_chunks
		def output():
			started.set()
			yield from original()
		process.output_chunks = output
		observed = []
		def create():
			parent = QWidget()
			parent.show()
			dialog = ProgressDialog(parent, 'Archive transfer', 100, QPalette())
			dialog.forceShow()
			timer = QTimer(dialog)
			def cancel():
				if started.is_set():
					observed.append((dialog.isModal(), parent.isEnabled(),
						QApplication.activeModalWidget(), QThread.currentThread()))
					dialog.request_cancel()
					timer.stop()
			timer.timeout.connect(cancel)
			timer.start(10)
			return parent, dialog, timer
		parent, dialog, timer = self.run_in_app(create)
		task = _7zipTaskWithProgress('Extracting', size=100)
		task._dialog = dialog
		try:
			with patch('core.fs.zip.Popen7ZipWindows', return_value=process):
				with self.assertRaises(Task.Canceled):
					task.run_7zip_with_progress(['x'], pty=False)
			self.assertTrue(process.killed)
			self.assertTrue(process.waited)
			self.assertEqual([(False, True, None, QApplication.instance().thread())], observed)
		finally:
			def close():
				timer.stop()
				dialog.cancel()
				parent.close()
				parent.deleteLater()
			self.run_in_app(close)

class UnpackArchiveIT(QtIT):
	def test_registered_command_updates_pane_and_refuses_existing_output(self):
		from core import Name, Size, Modified
		from core.commands import UnpackArchive
		from core.fs.local import LocalFileSystem
		from core.fs.zip import ZipFileSystem
		from fman import DirectoryPane
		from fman.impl.plugins.builtin import NullFileSystem, NullColumn
		from fman.impl.plugins.command_registry import PaneCommandRegistry
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from fman.impl.plugins.plugin import FileSystemWrapper, Plugin
		from fman.impl.widgets import DirectoryPaneWidget, ProgressDialog
		from fman.url import as_url
		from pathlib import Path
		from PyQt5.QtCore import QThread
		from PyQt5.QtGui import QIcon, QPalette
		from PyQt5.QtWidgets import QWidget
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		from zipfile import ZipFile
		with TemporaryDirectory() as temporary:
			root = Path(temporary)
			archive = root / 'Reports.zip'
			with ZipFile(archive, 'w') as writer:
				writer.writestr('nested/file.txt', b'payload')
				writer.writestr('empty/', b'')
			original = archive.read_bytes()
			errors = Mock()
			finished = Event()
			callbacks = Mock()
			callbacks.after_command.side_effect = lambda *args: finished.set()
			filesystem = MotherFileSystem(Mock(get_icon=Mock(return_value=QIcon())))
			for backend in (LocalFileSystem(), NullFileSystem(), ZipFileSystem(filesystem, {'.zip'})):
				filesystem.add_child(backend.scheme, FileSystemWrapper(backend, filesystem, errors))
			for column in (Name(filesystem), Size(filesystem), Modified(filesystem), NullColumn()):
				filesystem.register_column(column.get_qualified_name(), column)
			def create():
				parent = QWidget()
				registry = PaneCommandRegistry(errors, callbacks)
				plugin = Plugin(errors, Mock(), registry, Mock(), filesystem, Mock())
				plugin._register_directory_pane_command(UnpackArchive)
				widget = DirectoryPaneWidget(filesystem, 'null://', parent, Mock())
				pane = DirectoryPane(Mock(), widget, registry)
				parent.show()
				return parent, widget, pane, registry
			parent, widget, pane, registry = self.run_in_app(create)
			dialogs = []
			threads = []
			def create_dialog(title, size):
				self.assertEqual(QApplication.instance().thread(), QThread.currentThread())
				dialog = ProgressDialog(parent, title, size, QPalette())
				dialogs.append(dialog)
				return dialog
			def prepare(*args):
				threads.append(QThread.currentThread())
				return filesystem.prepare_copy(*args)
			ui = Mock()
			ui.create_progress_dialog.side_effect = lambda *args: self.run_in_app(create_dialog, *args)
			loaded = Event()
			try:
				widget.set_location(as_url(root), callback=loaded.set)
				self.assertTrue(loaded.wait(5), 'Pane did not load')
				pane.place_cursor_at(as_url(archive))
				self.assertEqual(as_url(archive), pane.get_file_under_cursor())
				self.assertIn('unpack_archive', registry.get_commands())
				self.assertEqual(('Unpack archive',), registry.get_command_aliases('unpack_archive'))
				with patch('core.commands.load_json', return_value={'archive_handlers': {'.zip': 'zip://'}}), \
					patch('core.commands.samefile', side_effect=filesystem.samefile), \
					patch('core.commands.is_dir', side_effect=filesystem.is_dir), \
					patch('core.commands.prepare_copy', side_effect=prepare), \
					patch('fman.fs.notify_file_added', side_effect=filesystem.notify_file_added), \
					patch('fman._get_ui', return_value=ui), \
					patch('core.commands.show_alert') as alert, \
					patch('core.commands.show_status_message') as status:
					self.run_in_app(pane.run_command, 'unpack_archive')
					self.assertTrue(finished.wait(10), 'Command did not finish')
					self.assertEqual(b'payload', (root / 'Reports/nested/file.txt').read_bytes())
					self.assertTrue((root / 'Reports/empty').is_dir())
					self.assertEqual(original, archive.read_bytes())
					self.assertEqual(1, len(dialogs))
					self.assertTrue(all(thread != QApplication.instance().thread() for thread in threads))
					def check_model():
						model = widget._model
						self.assertGreaterEqual(model.rowCount(), 2)
						self.assertEqual(as_url(root), model.get_location())
					self.run_in_app(check_model)
					status.assert_called_once_with('Unpacked Reports', timeout_secs=5)
					alert.assert_not_called()
					pane.place_cursor_at(as_url(root / 'Reports'))
					self.assertEqual(as_url(root / 'Reports'), pane.get_file_under_cursor())
					pane.place_cursor_at(as_url(archive))
					finished.clear()
					self.run_in_app(pane.run_command, 'unpack_archive')
					self.assertTrue(finished.wait(5), 'Conflict command did not finish')
					alert.assert_called_once_with('Destination already exists: Reports')
					self.assertEqual(1, len(dialogs))
					self.assertEqual(1, status.call_count)
					errors.report.assert_not_called()
			finally:
				def close():
					model = widget._model.sourceModel()
					model.shutdown()
					for dialog in dialogs:
						dialog.cancel()
					parent.close()
					parent.deleteLater()
					return model
				model = self.run_in_app(close)
				model._worker._thread.join(2)

class SearchFileSyntaxIT(QtIT):
	def test_native_picker_queries_highlights_accept_and_cancel(self):
		from fman.impl.quicksearch import Quicksearch, QuicksearchItemRenderer
		from fman.impl.theme import Theme
		from fman.url import as_url
		from search_file_fuzzy import SearchFilesRecursively
		from PyQt5.QtCore import QThread, QTimer
		from PyQt5.QtTest import QTest
		from PyQt5.QtWidgets import QStyleOptionViewItem
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		app = QApplication.instance()
		with TemporaryDirectory() as temporary:
			root = Path(temporary)
			for name in ('src/report.py', 'src/report.rb', 'docs/report.py', '\U0001f600report.txt'):
				path = root / name
				path.parent.mkdir(parents=True, exist_ok=True)
				path.touch()
			pane = Mock()
			pane.get_path.return_value = as_url(root)
			def show_on_qt(provider, query=''):
				self.assertEqual(app.thread(), QThread.currentThread())
				resources = Path(__file__).parents[3] / 'main/resources/base'
				theme = Theme(Mock(), [])
				theme.load(str(resources / 'Plugins/Core/Theme.css'))
				css = theme.get_quicksearch_item_css()
				dialog = Quicksearch(None, app, css, provider, query=query)
				errors = []
				def inspect():
					try:
						for text, expected in (
							('^src .py$ | .rb$', {'src\\report.py', 'src\\report.rb'}),
							('!^src .py$', {'docs\\report.py'}),
							("'\U0001f600", {'\U0001f600report.txt'}),
						):
							dialog._query.setText(text)
							self.assertEqual(expected, {item.title for item in dialog._curr_items})
						self.assertEqual([0, 1], dialog._curr_items[0].highlight)
						option = QStyleOptionViewItem()
						option.initFrom(dialog._items)
						renderer = QuicksearchItemRenderer(dialog._curr_items[0], option, css)
						self.assertEqual([(0, 2)], renderer._get_highlight_ranges())
						self.assertFalse(dialog.grab().isNull())
						dialog._query.setText('^src .py$')
						QTest.keyClick(dialog._query, Qt.Key_Escape if cancel else Qt.Key_Return)
						self.assertFalse(dialog.isVisible())
					except BaseException as error:
						errors.append(error)
						dialog.reject()
				QTimer.singleShot(0, inspect)
				try:
					result = dialog.exec()
					if errors:
						raise errors[0]
					return result
				finally:
					dialog.deleteLater()
			with patch('search_file_fuzzy.load_json', return_value={}), \
				patch('search_file_fuzzy.show_status_message'), \
				patch('search_file_fuzzy.clear_status_message'), \
				patch('search_file_fuzzy.show_quicksearch', side_effect=lambda *args, **kwargs:
					self.run_in_app(show_on_qt, *args, **kwargs)):
				for cancel in (False, True):
					pane.run_command.reset_mock()
					SearchFilesRecursively(pane)()
					if cancel:
						pane.run_command.assert_not_called()
					else:
						pane.run_command.assert_called_once_with('open_directory',
							{'url': as_url(root / 'src/report.py')})


class SearchFileMetadataIT(QtIT):
	def setUp(self):
		from fman import DirectoryPane
		from fman.impl.widgets import ProgressDialog
		from PyQt5.QtCore import pyqtSignal
		from PyQt5.QtWidgets import QWidget
		from unittest.mock import Mock, patch
		class PaneWidget(QWidget):
			location_changed = pyqtSignal(str)
			def get_location(self):
				return 'test://root'
		self.widget = self.run_in_app(PaneWidget)
		self.registry = Mock()
		self.pane = DirectoryPane(Mock(), self.widget, self.registry)
		self.progress = []
		def create_progress(title, size):
			dialog = self.run_in_app(ProgressDialog, None, title, size, QApplication.instance().palette())
			self.progress.append(dialog)
			return dialog
		for target, options in (
			('fman._get_ui', {'return_value': Mock(create_progress_dialog=create_progress)}),
			('search_file_fuzzy.load_json', {'return_value': {}}),
			('search_file_fuzzy.show_status_message', {}),
			('search_file_fuzzy.clear_status_message', {}),
		):
			patcher = patch(target, **options)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.addCleanup(self.dispose)

	def dispose(self):
		from PyQt5 import sip
		def cleanup():
			for widget in [*self.progress, self.widget]:
				if not sip.isdeleted(widget):
					sip.delete(widget)
		self.run_in_app(cleanup)

	def assert_unsubscribed(self):
		self.assertEqual(0, self.run_in_app(self.widget.receivers, self.widget.location_changed))

	def test_reserved_rows_reorder_filter_accept_and_cancel(self):
		from fman.impl.quicksearch import Quicksearch
		from fman.impl.theme import Theme
		from search_file_fuzzy import SearchFilesInCurrentFolder, describe_metadata
		from search_file_fuzzy.indexer import IndexResult
		from search_file_fuzzy.matcher import SearchEntry
		from PyQt5.QtCore import QThread, QTimer
		from PyQt5.QtTest import QTest
		from PyQt5.QtWidgets import QStyleOptionViewItem
		from pathlib import Path
		from types import SimpleNamespace
		from unittest.mock import patch
		app = QApplication.instance()
		def show_on_qt(provider, query=''):
			self.assertEqual(app.thread(), QThread.currentThread())
			resources = Path(__file__).parents[3] / 'main/resources'
			previous_style = app.styleSheet()
			theme = Theme(SimpleNamespace(set_style_sheet=app.setStyleSheet), [
				str(resources / 'base/styles.qss'), str(resources / 'windows/os_styles.qss')])
			theme.load(str(resources / 'base/Plugins/Core/Theme.css'))
			theme.enable_updates()
			dialog = Quicksearch(None, app, theme.get_quicksearch_item_css(), provider, query=query)
			errors = []
			def inspect():
				try:
					for text in ('', 'report', '^second', '^first', 'missing', ''):
						dialog._query.setText(text)
						dialog._items.doItemsLayout()
						heights = []
						for row, item in enumerate(dialog._curr_items):
							entry = next(entry for entry in entries if entry.url == item.value)
							self.assertEqual(describe_metadata(entry) or ' ', item.description)
							index = dialog._items.model().index(row, 0)
							option = QStyleOptionViewItem()
							option.initFrom(dialog._items)
							needed = dialog._items.itemDelegate().sizeHint(option, index).height()
							actual = dialog._items.visualRect(index).height()
							self.assertGreaterEqual(actual, needed)
							heights.append(actual)
							if text:
								self.assertTrue(item.highlight)
						self.assertLessEqual(len(set(heights)), 1)
					self.assertFalse(dialog.grab().isNull())
					QTest.keyClick(dialog._query, Qt.Key_Escape if cancel else Qt.Key_Return)
					self.assertFalse(dialog.isVisible())
				except BaseException as error:
					errors.append(error)
					dialog.reject()
			QTimer.singleShot(0, inspect)
			try:
				result = dialog.exec()
				if errors:
					raise errors[0]
				return result
			finally:
				dialog.deleteLater()
				app.setStyleSheet(previous_style)
		with patch('search_file_fuzzy.build_index') as build, \
			patch('search_file_fuzzy.show_quicksearch', side_effect=lambda *args, **kwargs:
				self.run_in_app(show_on_qt, *args, **kwargs)):
			for values in ((0, None), (None, 0), (None, None)):
				entries = [SearchEntry('test://root/' + name, name, name, size,
					1_800_000_000_000_000_000 if size is not None else None)
					for name, size in zip(('first-report.txt', 'second-report.txt'), values)]
				build.return_value = IndexResult(entries, False)
				for cancel in (False, True):
					self.registry.reset_mock()
					SearchFilesInCurrentFolder(self.pane)(metadata=True)
					if cancel:
						self.registry.execute_command.assert_not_called()
					else:
						self.registry.execute_command.assert_called_once_with('open_directory',
							{'url': entries[0].url}, self.pane)
					self.assert_unsubscribed()

	def test_blocked_provider_cancel_navigation_and_disposal_reject_results(self):
		from concurrent.futures import ThreadPoolExecutor
		from search_file_fuzzy import SearchFilesInCurrentFolder
		from PyQt5 import sip
		from unittest.mock import patch
		for action in ('cancel', 'loaded', 'navigate', 'close'):
			with self.subTest(action=action):
				entered, release = Event(), Event()
				def metadata(*args):
					entered.set()
					if not release.wait(5):
						raise AssertionError('Provider was not released')
					return 0
				with patch('search_file_fuzzy.indexer.iterdir', return_value=['report.txt']), \
					patch('search_file_fuzzy.indexer.is_dir', return_value=False), \
					patch('search_file_fuzzy.indexer.query', side_effect=metadata) as query, \
					patch('search_file_fuzzy.show_quicksearch') as show, \
					patch('search_file_fuzzy.show_status_message') as status, \
					patch('search_file_fuzzy.clear_status_message', side_effect=status.reset_mock), \
					ThreadPoolExecutor(max_workers=1) as executor:
					pending = executor.submit(SearchFilesInCurrentFolder(self.pane), metadata=True)
					try:
						self.assertTrue(entered.wait(5))
						if action == 'cancel':
							self.run_in_app(self.progress[-1].request_cancel)
						elif action == 'loaded':
							self.run_in_app(self.widget.location_changed.emit, 'test://root')
						elif action == 'navigate':
							self.run_in_app(self.widget.location_changed.emit, 'test://away')
							self.run_in_app(self.widget.location_changed.emit, 'test://root')
						else:
							self.run_in_app(sip.delete, self.widget)
					finally:
						release.set()
					pending.result(timeout=5)
					query.assert_called_once_with('test://root/report.txt', 'size_bytes')
					show.assert_not_called()
					self.registry.execute_command.assert_not_called()
					if action == 'cancel':
						status.assert_called_once_with('Find files canceled.', timeout_secs=3)
					else:
						status.assert_not_called()
					if action != 'close':
						self.assert_unsubscribed()


class CommandPaletteRecentIT(QtIT):
	def test_history_thread_affinity_and_other_provider_isolation(self):
		from core.commands import CommandPalette, _COMMAND_PALETTE_HISTORY
		from fman import QuicksearchItem
		from fman.ui import Resource
		from fman.impl.quicksearch import Quicksearch
		from fman.impl.theme import Theme
		from PyQt5.QtCore import QThread, QTimer
		from pathlib import Path
		from unittest.mock import Mock, patch
		app = QApplication.instance()
		pane = Mock()
		pane.get_commands.return_value = ['copy', 'files']
		pane.is_command_visible.return_value = True
		pane.get_command_aliases.side_effect = {'copy': ['Copy'], 'files': ['Find files']}.__getitem__
		document = {'recent': [{'kind': 'pane', 'name': 'files'}]}
		loads = []
		def load(name, **kwargs):
			if name == _COMMAND_PALETTE_HISTORY:
				self.assertNotEqual(app.thread(), QThread.currentThread())
				loads.append(name)
				return document
			return []
		palette = CommandPalette(pane)
		def show_on_qt(provider, **kwargs):
			self.assertEqual(app.thread(), QThread.currentThread())
			root = Path(__file__).parents[3] / 'main/resources/base'
			theme = Theme(Mock(), [])
			theme.load(str(root / 'Plugins/Core/Theme.css'))
			css = theme.get_quicksearch_item_css()
			dialog = Quicksearch(None, app, css, provider, **kwargs)
			errors = []
			def inspect():
				try:
					self.assertEqual('Find files', dialog._curr_items[0].title)
					self.assertEqual('Recent', dialog._curr_items[0].hint)
					dialog._query.setText('copy')
					self.assertEqual(['Copy'], [item.title for item in dialog._curr_items])
					self.assertEqual('', dialog._curr_items[0].hint)
					dialog._query.setText('file')
					self.assertEqual('Recent', dialog._curr_items[0].hint)
					plain_item = QuicksearchItem('value', 'Unrelated picker', hint='Original hint')
					plain = Quicksearch(None, app, css, lambda query: [plain_item])
					try:
						plain._update_items('')
						self.assertEqual([plain_item], plain._curr_items)
						self.assertEqual('Original hint', plain._curr_items[0].hint)
					finally:
						plain.deleteLater()
				except BaseException as error:
					errors.append(error)
				finally:
					dialog.reject()
			QTimer.singleShot(0, inspect)
			try:
				result = dialog.exec()
				if errors:
					raise errors[0]
				return result
			finally:
				dialog.deleteLater()
		with patch('core.commands.load_json', side_effect=load), \
			patch('core.commands.get_application_commands', return_value=[]), \
			patch('fman.ui.settings_resource', return_value=Resource()), \
			patch('core.commands.show_quicksearch', side_effect=lambda *args, **kwargs:
				self.run_in_app(show_on_qt, *args, **kwargs)):
			palette()
		self.assertEqual(2, len(loads))
		pane.run_command.assert_not_called()

class TextEditorIT(QtIT):
	def setUp(self):
		from fman.impl.plugins.config import Config
		from fman.impl.theme import Theme
		from fman.impl.widgets import MainWindow
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		import sys
		self.directory = TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.config = Config('Windows')
		self.config.add_dir(self.directory.name)
		self.config.save_json('Core Settings.json', {
			'editor': {'executable': sys.executable, 'arguments': []},
			'viewer': {'executable': sys.executable, 'arguments': []}})
		self.dialogs = []
		self.errors = []
		self.selection = 'Manual configuration'
		self.argument_line = ''
		self.cancel = None
		def prepare():
			root = Path(__file__).parents[3] / 'main/resources/base'
			theme = Theme(Mock(), [])
			theme.load(str(root / 'Plugins/Core/Theme.css'))
			self.window = MainWindow(QApplication.instance(), [], theme, None, Mock(), 'null://')
			self.window.before_dialog.connect(self._on_dialog)
		self.run_in_app(prepare)
		self.addCleanup(lambda: self.run_in_app(self.window.deleteLater))
		for target, kwargs in (
			('fman._get_ui', {'return_value': self.window}),
			('fman._get_plugin_support', {'return_value': self.config}),
			('core.text_editor.resolve', {'side_effect': lambda url: url}),
			('fman.impl.widgets.QFileDialog.getOpenFileName', {'side_effect': self._pick_file})):
			patcher = patch(target, **kwargs)
			patcher.start()
			self.addCleanup(patcher.stop)

	def _on_dialog(self, dialog):
		from fman.impl.quicksearch import Quicksearch
		from fman.impl.widgets import Prompt
		from PyQt5.QtCore import QThread, QTimer
		def answer():
			try:
				self.assertEqual(QApplication.instance().thread(), QThread.currentThread())
				if isinstance(dialog, Quicksearch):
					self.dialogs.append('preset')
					self.assertEqual(['Notepad++', 'CudaText', 'Notepad 4', 'EmEditor', 'Manual configuration'],
						[item.value for item in dialog._curr_items[:-1]])
					self.assertIn(dialog._curr_items[-1].value, ('Clear editor', 'Clear viewer'))
					if self.cancel == 'preset':
						dialog.reject()
					else:
						dialog._query.setText(self.selection)
						dialog._on_return_pressed()
				elif isinstance(dialog, Prompt):
					self.dialogs.append('arguments')
					if self.cancel == 'arguments':
						dialog.reject()
					else:
						dialog.setTextValue(self.argument_line)
						dialog.accept()
				else:
					self.fail('Unexpected wizard dialog: %s' % type(dialog).__name__)
			except BaseException as error:
				self.errors.append(error)
				dialog.reject()
		QTimer.singleShot(0, answer)

	def _pick_file(self, parent, caption, path, filter_text):
		from PyQt5.QtCore import QThread, QTimer
		from PyQt5.QtWidgets import QFileDialog
		self.assertEqual(QApplication.instance().thread(), QThread.currentThread())
		self.assertIn(caption, ('Set text editor', 'Set text viewer'))
		self.assertEqual('Applications (*.exe)', filter_text)
		self.dialogs.append('executable')
		dialog = QFileDialog(parent, caption, path, filter_text)
		dialog.setOption(QFileDialog.DontUseNativeDialog, True)
		dialog.setFileMode(QFileDialog.ExistingFile)
		QTimer.singleShot(0, dialog.reject if self.cancel == 'executable' else dialog.accept)
		try:
			return (dialog.selectedFiles()[0], filter_text) if dialog.exec() else ('', '')
		finally:
			dialog.deleteLater()

	def test_preset_manual_persistence_and_real_child_launch(self):
		from core.commands import OpenWithEditor, SetTextEditor, SetTextViewer
		from fman.url import as_url
		from pathlib import Path
		from subprocess import PIPE, Popen, list2cmdline
		from unittest.mock import Mock, patch
		import json
		self.selection = 'CudaText'
		SetTextViewer(Mock())()
		self.assertEqual(['preset', 'executable'], self.dialogs)
		self.assertEqual(['-r', '-n', '-ns', '-nh'], self.config.load_json('Core Settings.json')['viewer']['arguments'])
		self.selection = 'Manual configuration'
		arguments = ['-c', 'import json,sys;print(json.dumps(sys.argv[1:]))', 'C:\\My Files\\session.ini', '', 'a"b']
		self.argument_line = list2cmdline(arguments)
		SetTextEditor(Mock())()
		self.assertEqual(['preset', 'executable', 'preset', 'executable', 'arguments'], self.dialogs)
		self.assertEqual([], self.errors)
		settings = self.config.load_json('Core Settings.json')
		self.assertEqual(arguments, settings['editor']['arguments'])
		self.assertEqual(['-r', '-n', '-ns', '-nh'], settings['viewer']['arguments'])
		target = Path(self.directory.name, 'file {data} \u754c.txt')
		target.touch()
		children = []
		def launch(**kwargs):
			child = Popen(**kwargs, stdout=PIPE, stderr=PIPE, text=True)
			children.append(child)
			return child
		try:
			with patch('core.text_editor.Popen', side_effect=launch):
				OpenWithEditor(Mock())(as_url(str(target)))
			self.assertEqual(1, len(children))
			stdout, stderr = children[0].communicate(timeout=5)
			self.assertEqual('', stderr)
			self.assertEqual([*arguments[2:], str(target)], json.loads(stdout))
		finally:
			for child in children:
				if child.poll() is None:
					child.kill()
				child.communicate()

	def test_presets_for_both_roles(self):
		from core.commands import SetTextEditor, SetTextViewer
		from fman.impl.plugins.config import Config
		from unittest.mock import Mock
		for preset, role, command, arguments in (
			('Notepad 4', 'editor', SetTextEditor, ['-ns']),
			('Notepad 4', 'viewer', SetTextViewer, ['-ro', '-ns']),
			('Notepad++', 'editor', SetTextEditor, ['-multiInst', '-nosession', '-notabbar']),
			('Notepad++', 'viewer', SetTextViewer, ['-multiInst', '-nosession', '-notabbar', '-ro']),
			('CudaText', 'editor', SetTextEditor, ['-n', '-ns', '-nh']),
			('CudaText', 'viewer', SetTextViewer, ['-r', '-n', '-ns', '-nh']),
			('EmEditor', 'editor', SetTextEditor, ['-nr', '-sp']),
			('EmEditor', 'viewer', SetTextViewer, ['-nr', '-sp', '-r']),
		):
			with self.subTest(preset=preset, role=role):
				self.selection = preset
				self.dialogs.clear()
				command(Mock())()
				self.assertEqual([], self.errors)
				self.assertEqual(['preset', 'executable'], self.dialogs)
				reloaded = Config('Windows')
				reloaded.add_dir(self.directory.name)
				self.assertEqual(arguments, reloaded.load_json('Core Settings.json')[role]['arguments'])

	def test_clear_from_setup_list_persists_without_additional_dialogs(self):
		from copy import deepcopy
		from core.commands import SetTextEditor, SetTextViewer
		from fman.impl.plugins.config import Config
		from unittest.mock import Mock, patch
		expected = deepcopy(self.config.load_json('Core Settings.json'))
		with patch('core.text_editor.Popen') as launch:
			for role, command in (('editor', SetTextEditor), ('viewer', SetTextViewer)):
				self.selection = 'Clear %s' % role
				command(Mock())()
				expected[role] = None
				reloaded = Config('Windows')
				reloaded.add_dir(self.directory.name)
				self.assertEqual(expected, reloaded.load_json('Core Settings.json'))
				self.assertEqual('Text %s cleared.' % role,
					self.run_in_app(self.window._status_bar_text.text))
			launch.assert_not_called()
		self.assertEqual(['preset', 'preset'], self.dialogs)
		self.assertEqual([], self.errors)

	def test_cancel_each_modal_stage_preserves_settings(self):
		from copy import deepcopy
		from core.commands import SetTextEditor
		from unittest.mock import Mock, patch
		original = deepcopy(self.config.load_json('Core Settings.json'))
		with patch('core.text_editor.Popen') as launch:
			for stage in ('preset', 'executable', 'arguments'):
				self.cancel = stage
				SetTextEditor(Mock())()
				self.assertEqual(original, self.config.load_json('Core Settings.json'))
			launch.assert_not_called()
		self.assertEqual([], self.errors)

class FindFilesIT(QtIT):
	def setUp(self):
		from core import Name, Size, Modified, OpenDirectory
		from core.fs.local import LocalFileSystem
		from fman import DirectoryPane, Window
		from fman.ui import UiOwner
		from fman.url import as_url
		from fman.impl.plugins.builtin import NullFileSystem, NullColumn
		from fman.impl.plugins.command_registry import PaneCommandRegistry
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from fman.impl.plugins.plugin import FileSystemWrapper
		from fman.impl.ui.facade import _hosts
		from fman.impl.widgets import MainWindow
		from find_files import DEFAULTS, FindSession
		from pathlib import Path
		from PyQt5.QtGui import QIcon
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock
		self.temporary = TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name).resolve()
		(self.root / 'report.txt').write_bytes(b'hello')
		(self.root / 'other.txt').write_bytes(b'')
		(self.root / 'folder').mkdir()
		self.errors = Mock()
		self.filesystem = MotherFileSystem(Mock(get_icon=Mock(return_value=QIcon())))
		for backend in (LocalFileSystem(), NullFileSystem()):
			self.filesystem.add_child(backend.scheme, FileSystemWrapper(backend, self.filesystem, self.errors))
		for column in (Name(self.filesystem), Size(self.filesystem), Modified(self.filesystem), NullColumn()):
			self.filesystem.register_column(column.get_qualified_name(), column)
		self.plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/FindFiles'
		self.owner = UiOwner(resource_root=str(self.plugin_root))
		def prepare():
			self.main = MainWindow(QApplication.instance(), [], Mock(), Mock(), self.filesystem, 'null://')
			self.main.set_controller(Mock(handle_shortcut=Mock(return_value=False), handle_nonexistent_shortcut=Mock(return_value=False)))
			self.main.setStyleSheet((self.plugin_root.parents[1] / 'styles.qss').read_text())
			registry = PaneCommandRegistry(self.errors, Mock())
			registry.register_command('open_directory', OpenDirectory)
			window = Window(self.main, Mock())
			self.pane = DirectoryPane(window, self.main.add_pane(), registry)
			window._panes = [self.pane]
			self.main.resize(960, 700)
			self.main.show()
			self.main.activateWindow()
		self.run_in_app(prepare)
		self.addCleanup(self.close_window)
		loaded = Event()
		self.pane.set_path(as_url(self.root), callback=loaded.set)
		self.assertTrue(loaded.wait(5))
		self.session = self.run_in_app(FindSession, self.owner, self.pane, str(self.root), dict(DEFAULTS))
		self.host = self.run_in_app(lambda: _hosts[self.session.panel._key()])

	def close_window(self):
		self.owner.invalidate()
		def close():
			model = self.pane._widget._model.sourceModel()
			model.shutdown()
			self.main.close()
			return model
		model = self.run_in_app(close)
		model._worker._thread.join(5)
		self.assertFalse(model._worker._thread.is_alive())
		self.run_in_app(self.main.deleteLater)
		self.errors.report.assert_not_called()

	def search(self, **values):
		from find_files.engine import resolve_engine
		from pathlib import Path
		if not Path(resolve_engine()).is_file():
			self.skipTest('Installed fd.exe is unavailable')
		finished = Event()
		completed = self.session.completed
		def observed(*args):
			try:
				completed(*args)
			finally:
				finished.set()
		self.session.completed = observed
		self.session.panel.update(values=values)
		self.run_in_app(self.session.action, 'search', self.session.panel.snapshot())
		self.assertTrue(finished.wait(10))
		self.session.completed = completed
		self.run_in_app(QApplication.processEvents)

	def test_controls_optional_bounds_validation_and_wrapping(self):
		from PyQt5.QtCore import QDate, QPoint
		from PyQt5.QtTest import QTest
		from unittest.mock import Mock, patch
		def check():
			controls = {name: control for name, (record, control) in self.host.controls.items()}
			self.assertEqual(11, controls['type'].count())
			self.assertEqual('smart', controls['case_mode'].value())
			self.assertIsNone(self.session.panel.snapshot()['max_results'])
			self.assertEqual('', controls['max_results'].editor.text())
			self.assertEqual('Name Pattern', self.host.controls['pattern'][0].label)
			self.assertEqual('Modification Date', controls['modified_label'].content)
			self.assertEqual('File Size', controls['size_label'].content)
			self.assertIn('Entry type', controls['type'].toolTip())
			self.assertIn('Entry type', controls['type'].parentWidget().toolTip())
			self.assertIn('Honor .gitignore', controls['honor_gitignore'].toolTip())
			self.assertIn('.fdignore', controls['honor_gitignore'].toolTip())
			self.assertTrue(controls['stop'].isEnabled())
			values, status = self.session.panel.snapshot(), self.host.status
			with patch('find_files.Runner') as runner:
				controls['stop'].click()
				runner.assert_not_called()
			self.assertIsNone(self.session.runner)
			self.assertEqual(values, self.session.panel.snapshot())
			self.assertIs(status, self.host.status)
			self.assertFalse(controls['min_size_unit'].isEnabled())
			self.assertNotIn('max_depth', controls)
			self.assertNotIn('size_filters', self.session.panel.snapshot())
			with self.assertRaises(ValueError):
				self.host.update_controls(values={'size_filters': 'invalid'})
			changed = Mock(wraps=self.session.changed)
			self.host.on_change = changed
			with patch('find_files.engine.subprocess.Popen') as process:
				self.session.panel.update(values={'min_size': 5000000000, 'start_date': '2024-02-29', 'max_results': None})
				changed.assert_not_called()
				self.assertEqual(5000000000, controls['min_size'].editor.value())
				controls['min_size'].editor.stepBy(1)
				self.assertEqual(1, changed.call_count)
				self.assertEqual(5000000001, self.session.panel.snapshot()['min_size'])
				self.assertTrue(controls['min_size_unit'].isEnabled())
				controls['min_size'].editor.selectAll()
				QTest.keyClick(controls['min_size'].editor, Qt.Key_Backspace)
				self.assertIsNone(self.session.panel.snapshot()['min_size'])
				self.assertFalse(controls['min_size_unit'].isEnabled())
				self.assertEqual('', controls['min_size'].editor.text())
				QTest.keyClicks(controls['min_size'].editor, '0')
				self.assertEqual(0, self.session.panel.snapshot()['min_size'])
				controls['min_size'].editor.selectAll()
				QTest.keyClicks(controls['min_size'].editor, '5000000001')
				self.assertEqual(5000000001, self.session.panel.snapshot()['min_size'])
				controls['start_date'].editor.setDate(QDate(2028, 2, 29))
				self.assertEqual('2028-02-29', self.session.panel.snapshot()['start_date'])
				controls['start_date'].editor.selectAll()
				QTest.keyClick(controls['start_date'].editor, Qt.Key_Backspace)
				self.assertIsNone(self.session.panel.snapshot()['start_date'])
				self.assertEqual('', controls['start_date'].editor.text().strip())
				for date in ('2024-02-29', '2026-09-20', '1752-09-14', '9999-12-31'):
					editor = controls['start_date'].editor
					editor.selectAll()
					QTest.keyClicks(editor, date)
					QTest.keyClick(editor, Qt.Key_Tab)
					self.assertEqual(date, self.session.panel.snapshot()['start_date'])
					editor.selectAll()
					QTest.keyClick(editor, Qt.Key_Delete)
					QTest.keyClick(editor, Qt.Key_Tab)
					self.assertIsNone(self.session.panel.snapshot()['start_date'])
				controls['start_date'].editor.setDate(QDate(2028, 2, 29))
				self.assertEqual('2028-02-29', self.session.panel.snapshot()['start_date'])
				self.session.panel.update(values={'max_size': 1})
				self.session.enable_form()
				self.assertFalse(controls['search'].isEnabled())
				self.assertIn('Minimum', self.host.status.content)
				self.session.action('search', self.session.panel.snapshot())
				process.assert_not_called()
				self.session.panel.update(values={'min_size': None, 'max_size': None, 'start_date': None})
				self.session.enable_form()
				self.assertTrue(controls['search'].isEnabled())
			for width in (960, 1280, 1440):
				self.main.resize(width, 800)
				QApplication.processEvents()
				self.assertEqual(width, self.main.width())
				for body, actions in self.host.form.rows:
					layout = body.layout()
					geometries = [layout.itemAt(index).geometry() for index in range(layout.count())]
					for index, geometry in enumerate(geometries):
						self.assertTrue(body.rect().contains(geometry), (width, body.rect(), geometry))
						self.assertFalse(any(geometry.intersects(other) for other in geometries[index + 1:]))
				for name in ('min_size', 'max_size'):
					bound, unit = controls[name], controls[name + '_unit']
					self.assertEqual(bound.mapTo(self.host.form, QPoint()).y(), unit.parentWidget().mapTo(self.host.form, QPoint()).y())
				self.assertTrue(self.host.form.rows[1][0].isAncestorOf(controls['max_results']))
				self.assertEqual(3, controls['stop'].mapTo(self.host.form, QPoint()).x() -
					controls['search'].mapTo(self.host.form, QPoint(controls['search'].width(), 0)).x())
				self.assertEqual(self.host.form.width(), controls['stop'].mapTo(self.host.form, QPoint(controls['stop'].width(), 0)).x())
				self.assertLess(controls['root'].mapTo(self.host.form, QPoint()).x(), controls['recursive'].mapTo(self.host.form, QPoint()).x())
				for name, maximum in (('pattern', 480), ('extensions', 180), ('exclude', 240)):
					self.assertLessEqual(controls[name].width(), maximum)
				for name in ('pattern', 'extensions', 'exclude', 'type', 'case_mode', 'recursive', 'search'):
					self.assertEqual(28, controls[name].height(), name)
				for name in ('min_size', 'max_size', 'start_date', 'end_date', 'max_results'):
					self.assertEqual(28, controls[name].editor.height(), name)
				for name in ('modified_label', 'size_label', 'root'):
					label = controls[name]
					self.assertTrue(label.isVisible(), name)
					self.assertTrue(label.parentWidget().rect().contains(label.geometry()), name)
				for body, actions in self.host.form.rows:
					bottoms = {}
					for index in range(body.layout().count()):
						geometry = body.layout().itemAt(index).geometry()
						bottoms.setdefault(geometry.top(), geometry.bottom())
						self.assertEqual(bottoms[geometry.top()], geometry.bottom())
			editor = controls['start_date'].editor
			editor.setFocus()
			QTest.mouseClick(editor, Qt.LeftButton, pos=QPoint(editor.width() - 10, editor.height() // 2))
			QApplication.processEvents()
			calendar = editor.calendarWidget()
			self.assertTrue(calendar.isVisible())
			self.assertEqual(QDate.currentDate().year(), calendar.yearShown())
			self.assertEqual(QDate.currentDate().month(), calendar.monthShown())
			QTest.keyClick(calendar, Qt.Key_Escape)
			self.assertTrue(self.session.panel.is_open)
			stops = [control for control in self.host.form.tab_controls if control.isEnabled()]
			stops.append(self.main._panel_dock.close_button)
			for sequence, key, modifiers in ((stops, Qt.Key_Tab, Qt.NoModifier),
					(list(reversed(stops)), Qt.Key_Tab, Qt.ShiftModifier)):
				sequence[0].setFocus()
				for current, expected in zip(sequence, sequence[1:]):
					QTest.keyClick(current, key, modifiers)
					self.assertIs(expected, QApplication.focusWidget(), expected.accessibleName())
		self.run_in_app(check)

	def test_real_results_counts_filter_copy_and_navigation(self):
		from fman.url import as_url
		from PyQt5.QtTest import QTest
		from unittest.mock import patch
		self.search(type='all', max_results=None)
		def check():
			window = self.host.table_window
			self.assertTrue(window.isVisible())
			self.assertEqual('Find files', window.windowTitle())
			self.assertEqual('Showing 3 / 3 files', window.table.counts.text())
			self.assertFalse(self.host.controls['pattern'][1].isEnabled())
			self.session.table.filter_text = 'report'
			QApplication.processEvents()
			self.assertEqual('Showing 1 / 3 files', window.table.counts.text())
			window.open_menu(*window.table.current_cell, window.rect().center())
			next(action for action in window.menu.actions() if action.text() == 'Copy Path').trigger()
			self.assertEqual(str(self.root / 'report.txt'), QApplication.clipboard().text())
			return window
		window = self.run_in_app(check)
		closed = Event()
		self.run_in_app(window.disposed.connect, closed.set)
		with patch('fman.fs._get_mother_fs', return_value=self.filesystem):
			self.run_in_app(QTest.keyClick, window.table.view, Qt.Key_Return)
			self.assertTrue(closed.wait(5))
			self.assertEqual(as_url(self.root / 'report.txt'), self.pane.get_file_under_cursor())
			self.search(type='d', max_results=None)
			window = self.run_in_app(lambda: self.host.table_window)
			closed.clear()
			self.run_in_app(window.disposed.connect, closed.set)
			self.run_in_app(QTest.keyClick, window.table.view, Qt.Key_Return)
			self.assertTrue(closed.wait(5))
			self.assertEqual(as_url(self.root / 'folder'), self.pane.get_path())
			def check_focus():
				QApplication.processEvents()
				focused = QApplication.focusWidget()
				self.assertTrue(focused is self.pane._widget or self.pane._widget.isAncestorOf(focused))
			self.run_in_app(check_focus)

	def test_inactive_results_keep_form_locked(self):
		from PyQt5.QtWidgets import QWidget
		def other_window():
			other = QWidget()
			other.show()
			other.activateWindow()
			QApplication.processEvents()
			return other
		other = self.run_in_app(other_window)
		try:
			self.search(max_results=None)
			def check():
				window = self.host.table_window
				self.assertTrue(window.pending)
				self.assertFalse(window.isVisible())
				self.assertFalse(self.host.controls['search'][1].isEnabled())
				self.assertFalse(self.host.controls['pattern'][1].isEnabled())
				self.main.activateWindow()
				for turn in range(3):
					QApplication.processEvents()
				self.assertTrue(window.isVisible())
				self.assertFalse(window.pending)
				self.session.table.close()
				self.assertTrue(self.host.controls['search'][1].isEnabled())
			self.run_in_app(check)
		finally:
			self.run_in_app(other.close)
			self.run_in_app(other.deleteLater)

	def test_cancel_root_change_and_unload_reject_stale_results(self):
		from find_files.engine import Result
		from unittest.mock import patch
		from fman.url import as_url
		def check():
			with patch('find_files.Runner') as runner:
				self.session.action('search', self.session.panel.snapshot())
				generation = self.session.generation
				self.assertTrue(self.host.controls['stop'][1].isEnabled())
				self.assertFalse(self.host.controls['pattern'][1].isEnabled())
				self.host.controls['stop'][1].click()
				runner.return_value.stop.assert_called_once()
				with patch.object(self.pane, 'get_path', return_value=as_url(self.root / 'folder')):
					self.session.refresh_root()
				self.assertEqual(2, runner.return_value.stop.call_count)
				self.assertTrue(self.host.controls['stop'][1].isEnabled())
				self.session.completed(generation, Result((), 0, True, False, 'Complete', ''))
				self.assertIsNone(self.host.table_window)
				self.session.action('search', self.session.panel.snapshot())
				self.owner.invalidate()
				self.assertFalse(self.session.panel.is_open)
				self.assertGreaterEqual(runner.return_value.stop.call_count, 3)
		self.run_in_app(check)


class SearchFilesIT(QtIT):
	def test_name_only_navigation_and_escape_focus(self):
		from core import Name, Size, Modified, OpenDirectory
		from core.fs.local import LocalFileSystem
		from fman import DirectoryPane, Window
		from fman.ui import UiOwner
		from fman.url import as_url
		from fman.impl.plugins.builtin import NullFileSystem, NullColumn
		from fman.impl.plugins.command_registry import PaneCommandRegistry
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from fman.impl.plugins.plugin import FileSystemWrapper
		from fman.impl.ui.facade import _hosts
		from fman.impl.widgets import MainWindow
		from search_files import DEFAULTS, SearchSession
		from pathlib import Path
		from PyQt5.QtGui import QIcon
		from PyQt5.QtTest import QTest
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		with TemporaryDirectory() as directory:
			root = Path(directory).resolve()
			target, other = root / 'report.txt', root / 'aaa.txt'
			target.write_bytes(b'\x00binary')
			other.write_bytes(b'')
			errors = Mock()
			filesystem = MotherFileSystem(Mock(get_icon=Mock(return_value=QIcon())))
			for backend in (LocalFileSystem(), NullFileSystem()):
				filesystem.add_child(backend.scheme, FileSystemWrapper(backend, filesystem, errors))
			for column in (Name(filesystem), Size(filesystem), Modified(filesystem), NullColumn()):
				filesystem.register_column(column.get_qualified_name(), column)
			plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFiles'
			owner = UiOwner(resource_root=str(plugin_root))
			def prepare():
				main = MainWindow(QApplication.instance(), [], Mock(), Mock(), filesystem, 'null://')
				main.set_controller(Mock())
				widget = main.add_pane()
				registry = PaneCommandRegistry(errors, Mock())
				registry.register_command('open_directory', OpenDirectory)
				window = Window(main, Mock())
				pane = DirectoryPane(window, widget, registry)
				window._panes = [pane]
				main.resize(960, 600)
				main.show()
				main.activateWindow()
				return main, pane
			main, pane = self.run_in_app(prepare)
			try:
				loaded = Event()
				pane.set_path(as_url(root), callback=loaded.set)
				self.assertTrue(loaded.wait(5))
				session = self.run_in_app(SearchSession, owner, pane, str(root), dict(DEFAULTS))
				finished = Event()
				complete = session.completed
				def observed(*args):
					try:
						complete(*args)
					finally:
						finished.set()
				session.completed = observed
				with patch('search_files.Runner') as runner:
					self.run_in_app(session.action, 'search', session.panel.snapshot())
					runner.assert_not_called()
				self.assertEqual('Enter a file name or content pattern.',
					self.run_in_app(lambda: _hosts[session.panel._key()].status.content))
				with patch('fman.fs._get_mother_fs', return_value=filesystem):
					for action, mode, pattern in (('escape', 'glob', '*.txt;!aaa*'), ('enter', 'literal', 'report'),
						('double', 'regex', '^report\\.txt$'), ('menu', 'glob', 'report*')):
						with self.subTest(action=action):
							pane.place_cursor_at(as_url(other))
							finished.clear()
							session.panel.update(values={'name': pattern, 'name_mode': mode, 'content': ''})
							self.run_in_app(session.action, 'search', session.panel.snapshot())
							self.assertTrue(finished.wait(5))
							closed = Event()
							def activate():
								host = _hosts[session.panel._key()]
								window = host.table_window
								self.assertIsNotNone(window)
								QApplication.processEvents()
								self.assertTrue(window.isVisible())
								self.assertEqual('Search files', window.windowTitle())
								self.assertEqual(('report.txt', ''), window.table.current_cell[0].cells)
								self.assertIn('Complete: 1 files', window.summary.content)
								window.disposed.connect(closed.set)
								view = window.table.view
								if action == 'escape':
									QTest.keyClick(view, Qt.Key_Escape)
								elif action == 'enter':
									QTest.keyClick(view, Qt.Key_Return)
								elif action == 'double':
									position = view.visualRect(view.currentIndex()).center()
									QTest.mouseDClick(view.viewport(), Qt.LeftButton, pos=position)
								else:
									window.open_menu(*window.table.current_cell, view.mapToGlobal(view.rect().center()))
									next(item for item in window.menu.actions() if item.text() == 'Go To').trigger()
							self.run_in_app(activate)
							self.assertTrue(closed.wait(5), 'Results did not close after ' + action)
							def verify():
								QApplication.processEvents()
								host = _hosts[session.panel._key()]
								self.assertTrue(host.controls['name'][1].isEnabled())
								focused = QApplication.focusWidget()
								if action == 'escape':
									self.assertIs(host.controls['name'][1], focused)
								else:
									self.assertTrue(focused is pane._widget or pane._widget.isAncestorOf(focused))
									self.assertEqual(as_url(target), pane.get_file_under_cursor())
							self.run_in_app(verify)
			finally:
				owner.invalidate()
				def close():
					model = pane._widget._model.sourceModel()
					model.shutdown()
					main.close()
					return model
				model = self.run_in_app(close)
				model._worker._thread.join(5)
				self.assertFalse(model._worker._thread.is_alive())
				self.run_in_app(main.deleteLater)
				errors.report.assert_not_called()

	def test_root_follows_invoking_pane_and_fields_align(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import UiOwner
			from fman.url import as_url
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from search_files import DEFAULTS, SearchSession
			from PyQt5.QtCore import QPoint, pyqtSignal
			from PyQt5.QtGui import QPalette
			from PyQt5.QtWidgets import QWidget
			from pathlib import Path
			from types import SimpleNamespace
			from unittest.mock import Mock, patch
			class PaneWidget(QWidget):
				location_changed = pyqtSignal(object)
				def get_location(self):
					return self.location
			plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFiles'
			main = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
			main.setStyleSheet((plugin_root.parents[1] / 'styles.qss').read_text())
			window = Window(main, Mock())
			widgets = [PaneWidget(main), PaneWidget(main)]
			panes = [DirectoryPane(window, widget, Mock()) for widget in widgets]
			window._panes = panes
			main.show()
			main.activateWindow()
			try:
				for index, hint in enumerate(('Left pane', 'Right pane')):
					for widget in widgets:
						widget.location = as_url('C:\\initial')
					owner = UiOwner(resource_root=str(plugin_root))
					session = SearchSession(owner, panes[index], 'C:\\initial', dict(DEFAULTS))
					try:
						host = _hosts[session.panel._key()]
						stop = host.controls['stop'][1]
						stop.ensurePolished()
						self.assertTrue(stop.isEnabled())
						stop.click()
						self.assertIsNone(session.runner)
						self.assertEqual('C:\\initial', session.panel.snapshot()['root'])
						indicator, icon_name = host.icon_labels[0]
						self.assertEqual(hint, indicator.toolTip())
						self.assertIn(hint.split()[0].lower(), icon_name)
						self.assertGreaterEqual(indicator.pixmap().width(), 20)
						image = indicator.pixmap().toImage()
						self.assertEqual(image.width(), image.height())
						left_alpha = image.pixelColor(image.width() // 4, image.height() // 2).alpha()
						right_alpha = image.pixelColor(3 * image.width() // 4, image.height() // 2).alpha()
						self.assertEqual((255, 0) if index == 0 else (0, 255), (left_alpha, right_alpha))
						self.assertEqual(255, image.pixelColor(image.width() // 10, image.height() // 10).alpha())
						self.assertEqual('glob', session.panel.snapshot()['name_mode'])
						self.assertEqual('literal', session.panel.snapshot()['content_mode'])
						for name in ('name_mode', 'content_mode'):
							buttons = host.controls[name][1].group.buttons()
							self.assertEqual(3, len(buttons))
							self.assertEqual(1, sum(button.isChecked() for button in buttons))
							self.assertEqual(['Literal text, case-insensitive', 'Glob: * any text, ? one character, [ab] a set',
								'Regular expression (ripgrep syntax), case-insensitive'], [button.toolTip() for button in buttons])
						self.assertEqual('Text within the name, globs matching the whole name (*.cmd;!*.bak), or a regular expression', host.controls['name'][1].toolTip())
						self.assertEqual('Text within the line, a glob matched anywhere in the line (Comm*der), or a regular expression; leave empty to list files by name', host.controls['content'][1].toolTip())
						for record, wrapper, label in host.form.fields:
							self.assertEqual(host.controls[record.id][1].toolTip(), label.toolTip())
						host.form.setStyleSheet('QLabel { font-size: 16px; }')
						for width in (960, 1280, 1440):
							main.resize(width, 600)
							QApplication.processEvents()
							self.assertEqual(width, main.width())
							fields = [host.controls[name][1] for name in ('name', 'content')]
							self.assertEqual(fields[0].mapTo(host.form, QPoint()).x(), fields[1].mapTo(host.form, QPoint()).x())
							self.assertEqual(fields[0].width(), fields[1].width())
							self.assertTrue(all(80 <= field.width() <= 480 for field in fields))
							for record, wrapper, label in host.form.fields:
								self.assertGreaterEqual(label.width(), label.fontMetrics().horizontalAdvance(label.text()))
							modes = [host.controls[name][1] for name in ('name_mode', 'content_mode')]
							buttons = [host.controls[name][1] for name in ('recursive', 'search', 'stop')]
							control_left = modes[0].mapTo(host.form, QPoint()).x()
							self.assertEqual(control_left, modes[1].mapTo(host.form, QPoint()).x())
							self.assertEqual(control_left, buttons[0].mapTo(host.form, QPoint()).x())
							for row in [mode.group.buttons() for mode in modes] + [buttons]:
								self.assertTrue(all(button.width() == button.height() == 28 for button in row))
								self.assertEqual([control_left + 31 * column for column in range(3)],
									[button.mapTo(host.form, QPoint()).x() for button in row])
							centers = [button.mapTo(host.form, button.rect().center()).y() for button in buttons]
							self.assertLessEqual(max(centers) - min(centers), 1)
							self.assertLessEqual(buttons[-1].mapTo(host.form, buttons[-1].rect().topRight()).x(), host.form.width())
						widgets[1 - index].location = as_url('C:\\other')
						widgets[1 - index].location_changed.emit(widgets[1 - index])
						self.assertEqual('C:\\initial', session.root)
						widgets[index].location = as_url('C:\\next')
						widgets[index].location_changed.emit(widgets[index])
						self.assertEqual('C:\\next', session.root)
						session.panel.update(values={'content': 'cuda'})
						with patch('search_files.Runner') as runner:
							session.action('search', session.panel.snapshot())
							self.assertTrue(stop.isEnabled())
							self.assertEqual('#ff5252', stop.palette().color(QPalette.Active, QPalette.ButtonText).name())
							self.assertEqual(255, stop.palette().color(QPalette.Active, QPalette.ButtonText).alpha())
							self.assertEqual('C:\\next', runner.call_args.args[0].root)
							widgets[index].location = as_url('C:\\later')
							widgets[index].location_changed.emit(widgets[index])
							self.assertEqual('C:\\next', session.root)
							hit = SimpleNamespace(relative_path='file.cmd', snippet='cuda', path='C:\\next\\file.cmd', line=1, column=1, spans=())
							result = SimpleNamespace(rows=(hit,), status='Complete', reason='', validated=True,
								progress=SimpleNamespace(files=1, elapsed=0))
							session.completed(session.generation, result)
							self.assertTrue(stop.isEnabled())
							self.assertEqual('C:\\next', host.table_window.schema.base)
							self.assertIs(panes[index], host.table_window.pane)
							session.table.close()
						self.assertEqual('C:\\later', session.root)
						widgets[index].location = 'zip://archive'
						widgets[index].location_changed.emit(widgets[index])
						self.assertIsNone(session.root)
						self.assertFalse(host.controls['search'][1].isEnabled())
						widgets[index].location = as_url('C:\\back')
						widgets[index].location_changed.emit(widgets[index])
						self.assertTrue(host.controls['search'][1].isEnabled())
					finally:
						owner.invalidate()
					self.assertEqual(0, widgets[index].receivers(widgets[index].location_changed))
			finally:
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_inactive_window_keeps_form_locked_until_results_close(self):
		from fman import DirectoryPane, Window
		from fman.ui import UiOwner
		from fman.impl.ui.facade import _hosts
		from fman.impl.widgets import MainWindow
		from search_files import DEFAULTS, SearchSession
		from PyQt5.QtWidgets import QWidget
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock
		plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFiles'
		for present in (False, True):
			with self.subTest(present=present), TemporaryDirectory() as root:
				Path(root, 'report.txt').write_text('needle', encoding='utf-8')
				owner = UiOwner(resource_root=str(plugin_root))
				def prepare():
					main = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
					pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
					from fman.url import as_url
					pane.get_path = lambda: as_url(root)
					pane.on_path_changed = Mock(return_value=lambda: None)
					main.show()
					session = SearchSession(owner, pane, root, dict(DEFAULTS))
					other = QWidget()
					other.show()
					other.activateWindow()
					QApplication.processEvents()
					self.assertIs(other, QApplication.activeWindow())
					return main, other, session
				main, other, session = self.run_in_app(prepare)
				finished = Event()
				completed = session.completed
				def observed(*args):
					try:
						completed(*args)
					finally:
						finished.set()
				session.completed = observed
				try:
					session.panel.update(values={'content': 'needle'})
					self.run_in_app(session.action, 'search', session.panel.snapshot())
					self.assertTrue(finished.wait(10))
					def check():
						host = _hosts[session.panel._key()]
						window = host.table_window
						self.assertTrue(window.pending)
						self.assertFalse(window.isVisible())
						self.assertIsNone(session.runner)
						for name in ('name', 'content', 'name_mode', 'content_mode', 'recursive', 'search'):
							self.assertFalse(host.controls[name][1].isEnabled(), name)
						self.assertTrue(host.controls['stop'][1].isEnabled())
						generation = session.generation
						session.action('search', session.panel.snapshot())
						self.assertEqual(generation, session.generation)
						if present:
							main.activateWindow()
							for turn in range(3):
								QApplication.processEvents()
							self.assertTrue(window.isVisible())
							self.assertFalse(window.pending)
							self.assertFalse(host.controls['search'][1].isEnabled())
						window.close()
						self.assertTrue(session.panel.is_open)
						self.assertTrue(host.controls['search'][1].isEnabled())
						self.assertIsNone(session.table)
					self.run_in_app(check)
				finally:
					owner.invalidate()
					self.run_in_app(other.close)
					self.run_in_app(other.deleteLater)
					self.run_in_app(main.close)
					self.run_in_app(main.deleteLater)

	def test_real_search_panel_table_and_close(self):
		from fman import DirectoryPane, Window
		from fman.ui import UiOwner
		from fman.impl.ui.facade import _hosts
		from fman.impl.widgets import MainWindow
		from search_files import DEFAULTS, SearchSession
		from PyQt5.QtWidgets import QWidget
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock
		plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFiles'
		owner = UiOwner(resource_root=str(plugin_root))
		with TemporaryDirectory() as root:
			Path(root, 'report.txt').write_text('first\nneedle here\n', encoding='utf-8')
			def prepare():
				main = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
				pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
				from fman.url import as_url
				pane.get_path = lambda: as_url(root)
				pane.on_path_changed = Mock(return_value=lambda: None)
				main.resize(960, 600)
				main.show()
				main.activateWindow()
				QApplication.processEvents()
				session = SearchSession(owner, pane, root, dict(DEFAULTS))
				return main, session
			main, session = self.run_in_app(prepare)
			finished = Event()
			completed = session.completed
			def observed(*args):
				try:
					completed(*args)
				finally:
					finished.set()
			session.completed = observed
			try:
				def start():
					host = _hosts[session.panel._key()]
					self.assertFalse(host.isVisible())
					self.assertFalse(host.activity_timer.isActive())
					for control, name in host.icon_controls:
						self.assertFalse(control.icon().isNull(), name)
					self.assertIsNone(host.table_window)
					session.panel.update(values={'name': 'report', 'name_mode': 'literal', 'content': '*needle*', 'content_mode': 'glob'})
					session.action('search', session.panel.snapshot())
					self.assertTrue(host.activity_timer.isActive())
					self.assertFalse(host.controls['search'][1].isEnabled())
				self.run_in_app(start)
				self.assertTrue(finished.wait(10))
				self.assertIsNotNone(session.table)
				self.assertTrue(session.table.is_open)
				self.assertEqual(('report.txt', 'needle here'), session.table.current_cell[0].cells)
				self.assertEqual(2, session.table.current_cell[0].value.line)
				self.assertIsNone(session.runner)
				previous = session.table
				finished.clear()
				session.panel.update(values={'content': '(', 'content_mode': 'regex'})
				self.run_in_app(session.action, 'search', session.panel.snapshot())
				self.assertIs(previous, session.table)
				self.assertTrue(previous.is_open)
				self.assertFalse(finished.is_set())
				session.table.close()
				self.assertTrue(session.panel.is_open)
				self.run_in_app(session.action, 'search', session.panel.snapshot())
				self.assertTrue(finished.wait(10))
				self.assertIsNone(session.table)
				session.panel.update(values={'name': '*.txt', 'name_mode': 'glob', 'content': ''})
				finished.clear()
				self.run_in_app(session.action, 'search', session.panel.snapshot())
				self.assertTrue(finished.wait(10))
				self.assertTrue(session.table.is_open)
				self.assertEqual(('report.txt', ''), session.table.current_cell[0].cells)
				self.assertEqual(0, session.table.current_cell[0].value.line)
				def check_names():
					host = _hosts[session.panel._key()]
					self.assertIn('Complete: 1 files', host.table_window.summary.content)
					self.assertEqual(str(Path(root, 'report.txt')), host.table_window.details.content)
				self.run_in_app(check_names)
				session.table.close()
				session.panel.update(values={'content': 'needle', 'content_mode': 'literal'})
				finished.clear()
				def cancel():
					session.action('search', session.panel.snapshot())
					session.panel.close()
				self.run_in_app(cancel)
				self.assertTrue(finished.wait(10))
				self.assertIsNone(session.table)
				self.assertTrue(session.panel.cancelled.is_set())
			finally:
				owner.invalidate()
				self.run_in_app(main.close)
				self.run_in_app(main.deleteLater)


class TableIT(QtIT):
	def test_close_callback_order_and_live_focus_targets(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import Action, TableRow, TextField, UiOwner, show_panel, show_table
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from PyQt5 import sip
			from PyQt5.QtWidgets import QLineEdit
			from unittest.mock import Mock, patch
			for modal in (False, True):
				for action in ('ordinary', 'navigate', 'close_panel', 'replace_panel', 'replace_table', 'invalidate', 'delete_pane', 'close_main'):
					with self.subTest(modal=modal, action=action):
						main = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
						pane_widget = QLineEdit(main)
						main._central_layout.addWidget(pane_widget)
						pane = DirectoryPane(Window(main, Mock()), pane_widget, Mock())
						owner = UiOwner()
						main.show()
						main.activateWindow()
						QApplication.processEvents()
						try:
							panel = show_panel(owner=owner, pane=pane, rows=((TextField('name', 'Name'), Action('stop', 'Stop')),))
							host = _hosts[panel._key()]
							panel.update(enabled={'name': False})
							completed = []
							def callback():
								completed.append(True)
								panel.update(enabled={'name': True})
								if action == 'close_panel':
									panel.close()
								elif action == 'replace_panel':
									show_panel(owner=owner, pane=pane, rows=((TextField('new', 'Replacement'),),))
								elif action == 'replace_table':
									show_table(owner=owner, panel=panel, get_rows=lambda: (TableRow('new', ('Replacement',)),),
										num_columns=1, columns_header=('New',), modal=modal)
								elif action == 'invalidate':
									owner.invalidate()
								elif action == 'delete_pane':
									sip.delete(pane_widget)
								elif action == 'close_main':
									main.close()
							handle = show_table(owner=owner, panel=panel, get_rows=lambda: (TableRow('one', ('File',)),),
								num_columns=1, columns_header=('Name',), modal=modal, on_closed=callback)
							window = host.table_window
							window.navigated = action != 'ordinary'
							original_focus = host.focus_panel
							def focus_panel():
								self.assertEqual([True], completed)
								self.assertTrue(host.controls['name'][1].isEnabled())
								original_focus()
							with patch.object(host, 'focus_panel', side_effect=focus_panel) as focus:
								handle.close()
								self.assertEqual([True], completed)
								self.assertEqual(int(action == 'ordinary'), focus.call_count)
								for turn in range(3):
									QApplication.processEvents()
								if action in ('ordinary', 'navigate'):
									self.assertIs(pane_widget if action == 'navigate' else host.controls['name'][1], QApplication.focusWidget())
								elif action == 'replace_table':
									self.assertTrue(host.table_window.isVisible())
									self.assertTrue(host.table_window.isAncestorOf(QApplication.focusWidget()))
								elif action == 'replace_panel':
									self.assertTrue(main._panel_dock.isAncestorOf(QApplication.focusWidget()))
						finally:
							owner.invalidate()
							main.close()
							main.deleteLater()
		self.run_in_app(check)

	def test_choice_exclusivity_callbacks_and_atomic_updates(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import Choice, TextField, UiOwner, show_panel
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from PyQt5.QtWidgets import QWidget
			from pathlib import Path
			from unittest.mock import Mock
			owner = UiOwner(resource_root=str(Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFiles'))
			main = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
			pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
			calls = []
			options = (('literal', 'icons/search.svg', 'Literal'), ('glob', 'icons/square.svg', 'Glob'), ('regex', 'icons/regex.svg', 'RegEx'))
			try:
				panel = show_panel(owner=owner, pane=pane,
					rows=((TextField('query', 'Query'), Choice('mode', 'Mode', options, 'glob')),), on_change=calls.append)
				control = _hosts[panel._key()].controls['mode'][1]
				self.assertEqual('glob', panel.snapshot()['mode'])
				control.group.button(1).click()
				self.assertEqual([], calls)
				control.group.button(2).click()
				self.assertEqual(1, len(calls))
				self.assertEqual('regex', calls[-1]['mode'])
				self.assertEqual(1, sum(button.isChecked() for button in control.group.buttons()))
				panel.update(values={'mode': 'literal'})
				self.assertEqual('literal', panel.snapshot()['mode'])
				self.assertEqual(1, len(calls))
				with self.assertRaises(ValueError):
					panel.update(values={'query': 'must not change', 'mode': 'unknown'})
				self.assertEqual('', panel.snapshot()['query'])
				panel.update(enabled={'mode': False})
				self.assertTrue(all(not button.isEnabled() for button in control.group.buttons()))
			finally:
				owner.invalidate()
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_custom_menu_stale_action_and_atomic_refresh(self):
		def check():
			from fman.ui import TableAction, TableRow, UiOwner, show_table
			from fman.impl.ui.facade import _hosts
			from PyQt5.QtCore import QPoint, QThread
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import patch
			main, owner, calls = QWidget(), UiOwner(), []
			rows = [TableRow('one', ('One', 'Two', 'Three'))]
			main.show()
			main.activateWindow()
			QApplication.processEvents()
			try:
				with patch('fman._get_ui', return_value=main):
					handle = show_table(owner=owner, get_rows=lambda: rows, num_columns=3,
						columns_header=('A', 'B', 'C'), modal=False,
						get_menu=lambda row, column: (TableAction('inspect', 'Inspect',
							lambda row, column: calls.append((row.id, column, QThread.currentThread()))),))
				window = next(host for host in _hosts.values() if host.owner is owner)
				window.open_menu(*handle.current_cell, QPoint(10, 10))
				action = window.menu.actions()[0]
				action.trigger()
				self.assertEqual([('one', 0, QApplication.instance().thread())], calls)
				window.table.view.setCurrentIndex(window.table.model.index(0, 1))
				window.table.view.setCurrentIndex(window.table.model.index(0, 0))
				action.trigger()
				self.assertEqual(1, len(calls))
				rows[:] = [TableRow('one', ('Replacement', 'Two', 'Three'))]
				handle.refresh()
				action.trigger()
				self.assertEqual(1, len(calls))
				rows.append(rows[0])
				with self.assertRaises(ValueError):
					handle.refresh()
				self.assertEqual('Replacement', handle.current_cell[0].cells[0])
			finally:
				owner.invalidate()
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_real_navigation_adapter_modal_and_modeless(self):
		from fman.ui import TableRow, UiOwner, show_table
		from fman.impl.navigation import current_request
		from fman.impl.ui.facade import _hosts
		from fman.url import as_url
		from PyQt5.QtWidgets import QWidget
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock
		for modal in (False, True):
			with self.subTest(modal=modal), TemporaryDirectory() as root:
				path = Path(root, 'file.txt')
				path.write_text('content', encoding='utf-8')
				owner, finished, calls = UiOwner(), Event(), []
				def dispatch(command, args):
					calls.append((command, args))
					request = current_request()
					self.assertIsNotNone(request)
					request.started = True
					request.finish('success')
				def prepare():
					main = QWidget()
					pane = Mock()
					pane.window._widget = main
					pane.on_closed.return_value = lambda: None
					pane.run_command.side_effect = dispatch
					main.show()
					main.activateWindow()
					QApplication.processEvents()
					handle = show_table(owner=owner, pane=pane, get_rows=lambda: (
						TableRow('one', ('file.txt', root, 'Plain')),), num_columns=3,
						columns_header=('File', 'Folder', 'Text'), file_path_column=0,
						folder_path_column=1, base_path=root, modal=modal)
					window = next(host for host in _hosts.values() if host.owner is owner)
					window.disposed.connect(finished.set)
					window.busy_changed.connect(lambda busy: None if busy else finished.set())
					column = 0 if modal else 1
					window.table.view.setCurrentIndex(window.table.model.index(0, column))
					window.activate_cell(*window.table.current_cell)
					self.assertTrue(window.busy)
					return main, handle, window
				main, handle, window = self.run_in_app(prepare)
				try:
					self.assertTrue(finished.wait(3))
					self.run_in_app(lambda: None)
					self.assertEqual([('open_directory', {'url': as_url(str(path) if modal else root)})], calls)
					self.assertEqual(not modal, handle.is_open)
					if handle.is_open:
						self.assertFalse(self.run_in_app(lambda: window.busy))
				finally:
					owner.invalidate()
					self.run_in_app(main.close)
					self.run_in_app(main.deleteLater)

	def test_large_snapshot_projection_timing(self):
		from time import perf_counter
		from fman.impl.ui.table import Table
		from fman.impl.ui.table_data import TableRow, TableSchema
		ready = Event()
		rows = tuple(TableRow(str(index), ('folder/file-%05d.txt' % index,
			'A long matching text snippet ' * 16)) for index in range(10000))
		def prepare():
			started = perf_counter()
			schema = TableSchema(2, ('File Path', 'Snippet'))
			widget = Table(schema, schema.snapshot(lambda: rows))
			construction = perf_counter() - started
			widget.state_changed.connect(lambda: ready.set() if widget.model.matches else None)
			started = perf_counter()
			widget.query.setText('fl9')
			return widget, construction, started
		widget, construction, started = self.run_in_app(prepare)
		try:
			self.assertTrue(ready.wait(10))
			elapsed = perf_counter() - started
			print('Table 10000 rows: snapshot/construction %.3f s; fuzzy %.3f s' % (construction, elapsed))
			self.assertGreater(self.run_in_app(widget.model.rowCount), 0)
		finally:
			self.run_in_app(widget.dispose)
			self.run_in_app(widget.deleteLater)

	def test_directory_pane_styles_unchanged(self):
		def check():
			from pathlib import Path
			from fman.impl.ui.table import Table
			from fman.impl.ui.table_data import TableRow, TableSchema
			from PyQt5.QtGui import QColor, QPalette, QStandardItem, QStandardItemModel
			from PyQt5.QtWidgets import QTableView
			styles = Path(__file__).parents[3] / 'main/resources/base/styles.qss'
			for base in ('#ffffff', '#272822'):
				pane = QTableView()
				palette = pane.palette()
				palette.setColor(QPalette.Base, QColor(base))
				pane.setPalette(palette)
				pane.setStyleSheet(styles.read_text(encoding='utf-8'))
				model = QStandardItemModel(pane)
				model.appendRow([QStandardItem('File'), QStandardItem('Size')])
				pane.setModel(model)
				pane.setCurrentIndex(model.index(0, 0))
				pane.show()
				QApplication.processEvents()
				before = pane.grab().toImage()
				table = Table(TableSchema(2, ('One', 'Two')), (TableRow('row', ('Path', 'Text')),))
				table.setStyleSheet(styles.read_text(encoding='utf-8'))
				self.assertEqual(before, pane.grab().toImage())
				table.dispose()
				table.deleteLater()
				pane.close()
				pane.deleteLater()
		self.run_in_app(check)

	def test_deferred_table_menu_and_owner_unload(self):
		def check():
			from fman.ui import TableRow, UiOwner, show_table
			from fman.impl.ui.facade import _hosts
			from PyQt5.QtCore import QPoint
			from PyQt5.QtWidgets import QDialog, QWidget
			from unittest.mock import Mock, patch
			main = QWidget()
			main.show()
			main.activateWindow()
			QApplication.processEvents()
			blocker = QDialog(main)
			blocker.setWindowModality(Qt.WindowModal)
			blocker.open()
			owner, details, closed = UiOwner(), Mock(return_value='Details'), Mock()
			try:
				with patch('fman._get_ui', return_value=main):
					handle = show_table(owner=owner, get_rows=lambda: (TableRow('one', ('C:\\folder\\file.txt', 'Plain')),),
						num_columns=2, columns_header=('Path', 'Text'), file_path_column=0,
						get_details=details, on_closed=closed)
				window = next(host for host in _hosts.values() if host.owner is owner)
				self.assertTrue(window.pending)
				self.assertFalse(window.isVisible())
				blocker.close()
				main.activateWindow()
				for turn in range(3):
					QApplication.processEvents()
				self.assertTrue(window.isVisible())
				self.assertFalse(window.pending)
				row, column = handle.current_cell
				window.open_menu(row, column, QPoint(10, 10))
				self.assertEqual(['Copy Path', 'Go To'], [action.text() for action in window.menu.actions()])
				self.assertFalse(window.menu.actions()[1].isEnabled())
				window.menu.actions()[0].trigger()
				self.assertEqual('C:\\folder\\file.txt', QApplication.clipboard().text())
				window.close_menu()
				before = details.call_count
				owner.invalidate()
				QApplication.processEvents()
				self.assertFalse(handle.is_open)
				self.assertEqual(before, details.call_count)
				closed.assert_not_called()
			finally:
				owner.invalidate()
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_facade_panel_modeless_refresh_and_disposal(self):
		from fman import DirectoryPane, Window
		from fman.ui import Action, TableRow, TextField, UiOwner, show_panel, show_table
		from fman.impl.widgets import MainWindow
		from PyQt5.QtWidgets import QWidget
		from unittest.mock import Mock
		def prepare():
			main = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
			pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
			main.show()
			main.activateWindow()
			QApplication.processEvents()
			return main, pane
		main, pane = self.run_in_app(prepare)
		owner = UiOwner()
		changes = []
		rows = [TableRow('source', ('old.txt', 'new.txt'))]
		try:
			panel = show_panel(owner=owner, pane=pane,
				rows=((TextField('pattern', 'Name'), Action('apply', 'Apply')),),
				on_change=lambda values: changes.append(values))
			panel.update(values={'pattern': 'replacement'})
			self.assertEqual('replacement', panel.snapshot()['pattern'])
			self.assertEqual([], changes)
			table = show_table(owner=owner, panel=panel, get_rows=lambda: tuple(rows),
				num_columns=2, columns_header=('Current', 'Proposed'), modal=False)
			self.assertTrue(table.is_open)
			self.assertFalse(isinstance(table, QWidget))
			rows[:] = [TableRow('source', ('old.txt', 'other.txt'))]
			table.refresh()
			self.assertEqual('other.txt', table.current_cell[0].cells[1])
			table.close()
			self.assertTrue(panel.is_open)
			self.assertFalse(table.is_open)
			with self.assertRaises(RuntimeError):
				table.refresh()
			panel.set_activity_status('Searching')
			self.assertIsNotNone(self.run_in_app(lambda: main.findChild(QWidget, 'plugin-activity-status')))
			panel.close()
			self.assertTrue(panel.cancelled.is_set())
			self.assertFalse(panel.is_open)
		finally:
			owner.invalidate()
			self.run_in_app(main.close)
			self.run_in_app(main.deleteLater)

	def test_modeless_panel_focus_and_status_error_cleanup(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import Action, TableRow, TextField, Toggle, UiOwner, show_panel, show_table
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QWidget
			from pathlib import Path
			from unittest.mock import Mock
			main = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
			pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
			root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFiles'
			owner = UiOwner(resource_root=str(root))
			main.show()
			main.activateWindow()
			QApplication.processEvents()
			try:
				panel = show_panel(owner=owner, pane=pane, rows=((TextField('name', 'Name'), Action('apply', 'Apply')),))
				table = show_table(owner=owner, panel=panel, modal=False, get_rows=lambda: (TableRow('one', ('Original', 'Proposed')),),
					num_columns=2, columns_header=('Original', 'Proposed'))
				host = _hosts[panel._key()]
				window = host.table_window
				window.activateWindow()
				window.table.view.setFocus()
				QApplication.processEvents()
				QTest.keyClick(window.table.view, Qt.Key_Tab)
				QApplication.processEvents()
				self.assertTrue(main._panel_dock.isAncestorOf(QApplication.focusWidget()))
				host.focus_from_panel()
				QApplication.processEvents()
				self.assertIs(window.table.query, QApplication.focusWidget())
				def broken():
					raise ValueError('status failed')
				panel.set_activity_status(get_text=broken)
				self.assertFalse(host.activity_timer.isActive())
				self.assertEqual('status failed', host.status.content)
				panel.close()
				self.assertFalse(table.is_open)
				with self.assertRaises(ValueError):
					show_panel(owner=owner, pane=pane, rows=((Toggle('bad', '../outside.svg', 'Bad'),),))
				self.assertFalse(any(item.owner is owner for item in _hosts.values()))
			finally:
				owner.invalidate()
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_fuzzy_sort_refresh_and_current_cell(self):
		def check():
			from fman.impl.ui.table import Table
			from fman.impl.ui.table_data import TableRow, TableSchema
			rows = (TableRow('first', ('zebra', 'blue')), TableRow('second', ('alpha', 'green')))
			table = Table(TableSchema(2, ('Name', 'Color')), rows)
			try:
				self.assertEqual((rows[0], 0), table.current_cell)
				table.view.setCurrentIndex(table.model.index(1, 1))
				table.sort_by(0)
				self.assertEqual((rows[1], 1), table.current_cell)
				table.query.setText('gn')
				QApplication.processEvents()
				self.assertEqual([rows[1]], list(table.model.rows))
				table.query.setText('no matching value')
				QApplication.processEvents()
				self.assertIsNone(table.current_cell)
				table.query.clear()
				table.replace((TableRow('second', ('alpha', 'proposed')),))
				self.assertEqual('second', table.current_cell[0].id)
				self.assertEqual('proposed', table.model.rows[0].cells[1])
				for filename in ('CudaText.cmd', 'Cud\u00e1Text.cmd'):
					table.replace((TableRow('script', (filename, 'text')),))
					table.query.setText('cmd')
					QApplication.processEvents()
					self.assertEqual((9, 10, 11), tuple(table.model.index(0, 0).data(Qt.UserRole + 1)))
			finally:
				table.dispose()
				table.deleteLater()
		self.run_in_app(check)

	def test_buttonless_cell_specific_activation(self):
		def check():
			from fman.impl.ui.table import Table
			from fman.impl.ui.table_data import TableRow, TableSchema
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QAbstractButton
			table = Table(TableSchema(2, ('Path', 'Text')), (TableRow('row', ('C:\\file', 'text')),))
			table.resize(500, 240)
			table.show()
			QApplication.processEvents()
			calls = []
			table.view.cell_activated.connect(lambda row, column: calls.append((row.id, column)))
			try:
				self.assertFalse(any(button.isVisible() for button in table.findChildren(QAbstractButton)))
				index = table.model.index(0, 1)
				position = table.view.visualRect(index).center()
				QTest.mouseClick(table.view.viewport(), Qt.LeftButton, pos=position)
				self.assertEqual([], calls)
				self.assertEqual(1, table.current_cell[1])
				QTest.mouseDClick(table.view.viewport(), Qt.LeftButton, pos=position)
				self.assertEqual([('row', 1)], calls)
				QTest.keyClick(table.query, Qt.Key_Return, Qt.ControlModifier)
				self.assertEqual(1, len(calls))
			finally:
				table.dispose()
				table.close()
				table.deleteLater()
		self.run_in_app(check)

class OutputTextBoxIT(QtIT):
	def test_title_parameter_layout_and_digest_only_copy(self):
		def check():
			from fman.ui import OutputTextBox
			from PyQt5.QtWidgets import QLabel, QToolButton, QWidget
			parent = QWidget()
			output = OutputTextBox('digest', parent, title='File Hash: sample.txt, SHA-256')
			try:
				parent.resize(640, 300)
				parent.show()
				output.resize(480, 140)
				output.show()
				QApplication.processEvents()
				label = output.findChild(QLabel, 'output-title')
				button = output.findChild(QToolButton)
				self.assertIs(parent, output.parentWidget())
				self.assertEqual(label.fontMetrics().elidedText(output.title(), Qt.ElideMiddle, label.contentsRect().width()), label.text())
				self.assertEqual(Qt.PlainText, label.textFormat())
				self.assertLess(button.geometry().right(), label.geometry().left())
				title = 'File Hash: ' + 'long filename ' * 30 + '\u03bb.txt, SHA-512'
				output.set_title(title)
				for width in (240, 480):
					output.resize(width, 140)
					QApplication.processEvents()
					self.assertEqual(width, output.width())
					self.assertLessEqual(label.fontMetrics().horizontalAdvance(label.text()), label.contentsRect().width())
				self.assertEqual(title, output.title())
				self.assertEqual(title, label.toolTip())
				output.copy_text()
				self.assertEqual('digest', QApplication.clipboard().text())
				with self.assertRaises(TypeError):
					output.set_title(None)
				with self.assertRaises(TypeError):
					OutputTextBox(title=None)
				output.set_title('')
				self.assertEqual('', label.text())
			finally:
				parent.close()
				parent.deleteLater()
		self.run_in_app(check)

	def test_high_dpi_icon_is_not_cropped(self):
		def check():
			from fman.ui import OutputTextBox
			from PyQt5.QtWidgets import QToolButton
			from unittest.mock import patch
			with patch.object(OutputTextBox, 'devicePixelRatioF', return_value=2):
				output = OutputTextBox('digest')
			try:
				image = output.findChild(QToolButton).icon().pixmap(32, 32).toImage()
				self.assertEqual((32, 32), (image.width(), image.height()))
				self.assertGreater(image.pixelColor(29, 16).alpha(), 0)
			finally:
				output.deleteLater()
		self.run_in_app(check)

	def test_copy_readonly_keyboard_and_exact_text(self):
		def check():
			from fman.ui import OutputTextBox
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QPlainTextEdit, QToolButton
			text = '<b>literal</b>\r\nUnicode: \u03bb\tvalue\n'
			output = OutputTextBox(text)
			try:
				output.resize(320, 140)
				output.show()
				editor = output.findChild(QPlainTextEdit)
				button = output.findChild(QToolButton)
				calls = []
				output.copied.connect(lambda: calls.append(True))
				self.assertEqual(text, output.text())
				self.assertTrue(editor.isReadOnly())
				self.assertFalse(button.isCheckable())
				self.assertFalse(button.icon().isNull())
				cursor = editor.textCursor()
				cursor.setPosition(3)
				cursor.setPosition(10, cursor.KeepAnchor)
				editor.setTextCursor(cursor)
				QTest.keyClick(editor, Qt.Key_C, Qt.ControlModifier)
				self.assertEqual('literal', QApplication.clipboard().text())
				for key, modifier in ((Qt.Key_Return, Qt.NoModifier), (Qt.Key_Enter, Qt.KeypadModifier)):
					QTest.keyClick(editor, key, modifier)
					self.assertEqual(text.replace('\r\n', '\n'), QApplication.clipboard().text().replace('\r\n', '\n'))
				QTest.mouseClick(button, Qt.LeftButton)
				self.assertEqual(3, len(calls))
				before = editor.toPlainText()
				QTest.keyClicks(editor, 'changed')
				QTest.keyClick(editor, Qt.Key_V, Qt.ControlModifier)
				QTest.keyClick(editor, Qt.Key_X, Qt.ControlModifier)
				self.assertEqual(before, editor.toPlainText())
				output.set_text('replacement')
				self.assertEqual('', editor.textCursor().selectedText())
				output.copy_text()
				self.assertEqual('replacement', QApplication.clipboard().text())
				output.set_text('')
				self.assertFalse(button.isEnabled())
				output.copy_text()
				self.assertEqual('replacement', QApplication.clipboard().text())
				self.assertEqual(4, len(calls))
				with self.assertRaises(TypeError):
					output.set_text(None)
			finally:
				output.close()
				output.deleteLater()
		self.run_in_app(check)

	def test_public_export_and_thread_guards(self):
		import fman.ui
		self.assertIn('OutputTextBox', fman.ui.__all__)
		with self.assertRaises(RuntimeError):
			fman.ui.OutputTextBox()
		output = self.run_in_app(fman.ui.OutputTextBox)
		try:
			for operation in (output.text, output.title, output.copy_text, lambda: output.set_text('no'), lambda: output.set_title('no')):
				with self.assertRaises(RuntimeError):
					operation()
		finally:
			self.run_in_app(output.deleteLater)

	def test_copy_passes_original_string_to_clipboard(self):
		def check():
			from fman.ui import OutputTextBox
			from unittest.mock import patch
			text = 'first\r\nsecond\rthird\t\n'
			output = OutputTextBox(text)
			try:
				with patch('fman.impl.ui.output.QApplication.clipboard') as clipboard:
					output.copy_text()
					clipboard.return_value.setText.assert_called_once_with(text)
			finally:
				output.deleteLater()
		self.run_in_app(check)

class HashResultIT(QtIT):
	def assert_centered_within_screen(self, window):
		available = self.main.screen().availableGeometry()
		frame = window.frameGeometry()
		expected = self.main.frameGeometry().center()
		expected.setX(max(available.left() + (frame.width() - 1) // 2,
			min(expected.x(), available.right() - frame.width() // 2)))
		expected.setY(max(available.top() + (frame.height() - 1) // 2,
			min(expected.y(), available.bottom() - frame.height() // 2)))
		self.assertEqual(expected, frame.center())

	def setUp(self):
		from calculate_file_hash.ui import HashController
		from fman import DirectoryPane, Window
		from fman.impl.widgets import MainWindow
		from fman.ui import UiOwner
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		self.directory = TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.path = Path(self.directory.name) / 'hash.txt'
		self.path.write_bytes(b'abc')
		self.url = 'file://' + self.path.as_posix()
		self.controller = HashController
		self.owner = UiOwner()
		for target, options in (
			('calculate_file_hash.HashController.owner', {'new': self.owner}),
			('calculate_file_hash.load_json', {'return_value': {}}),
			('calculate_file_hash.submit_task', {'side_effect': lambda task: task()}),
			('calculate_file_hash.show_status_message', {}),
			('calculate_file_hash.ui.show_status_message', {}),
			('calculate_file_hash.ui.show_alert', {}),
		):
			patcher = patch(target, **options)
			patcher.start()
			self.addCleanup(patcher.stop)
		def prepare():
			from PyQt5.QtWidgets import QWidget
			theme = Mock()
			theme.get_quicksearch_item_css.return_value = None
			self.main = MainWindow(Mock(), [], theme, Mock(), Mock(), 'null://')
			self.pane = DirectoryPane(Window(self.main, Mock()), QWidget(self.main), Mock())
			self.pane.get_file_under_cursor = Mock(return_value=self.url)
			self.pane.get_path = Mock(return_value='file://C:/')
			self.pane.run_command = Mock()
			self.main.show()
		self.run_in_app(prepare)

	def tearDown(self):
		self.owner.invalidate()
		self.run_in_app(self.main.close)
		self.run_in_app(self.main.deleteLater)

	def test_result_centers_on_main_window_when_shown(self):
		def place_main():
			self.main.setGeometry(70, 60, 960, 600)
			QApplication.processEvents()
		self.run_in_app(place_main)
		window = self.controller.show(self.pane)
		def check_center():
			QApplication.processEvents()
			self.assert_centered_within_screen(window)
		self.run_in_app(check_center)
		def move_windows():
			self.main.move(120, 100)
			window.move(0, 0)
		self.run_in_app(move_windows)
		self.assertIs(window, self.controller.show(self.pane))
		self.run_in_app(check_center)

	def test_quick_output_and_picker_share_panel_free_result(self):
		from calculate_file_hash import CalculateFileHash, CalculateFileHashBy
		from fman.url import as_human_readable
		from unittest.mock import patch
		import hashlib
		self.run_in_app(lambda: self.main.setGeometry(70, 60, 960, 600))
		CalculateFileHash(self.pane)()
		window = self.controller.show(self.pane)
		def check(algorithm, digest):
			QApplication.processEvents()
			self.assert_centered_within_screen(window)
			self.assertIsNone(window.bottom_panel)
			self.assertIsNone(self.main._panel_dock)
			self.assertEqual(2, window.layout().count())
			self.assertTrue(window.path_label.isVisible())
			self.assertEqual(as_human_readable(self.url), window.path_label.toolTip())
			self.assertEqual(as_human_readable(self.url), window.windowTitle())
			self.assertEqual(digest, window.output.text())
			self.assertEqual('Hash Algorithm: ' + algorithm, window.output.title())
			self.pane.run_command.assert_not_called()
		self.run_in_app(lambda: check('SHA-256', hashlib.sha256(b'abc').hexdigest()))
		def choose(*args, **kwargs):
			self.run_in_app(lambda: check('SHA-256', hashlib.sha256(b'abc').hexdigest()))
			self.pane.get_file_under_cursor.return_value = 'file://C:/another.txt'
			return '', 'sha512'
		with patch('calculate_file_hash.show_quicksearch', side_effect=choose) as picker:
			CalculateFileHashBy(self.pane)()
			picker.assert_called_once()
		self.assertIs(window, self.controller.show(self.pane))
		self.run_in_app(lambda: check('SHA-512', hashlib.sha512(b'abc').hexdigest()))
		self.pane.get_file_under_cursor.return_value = self.url
		with patch('calculate_file_hash.show_quicksearch', return_value=None):
			CalculateFileHashBy(self.pane)()
		self.run_in_app(lambda: check('SHA-512', hashlib.sha512(b'abc').hexdigest()))
		CalculateFileHash(self.pane)()
		self.run_in_app(lambda: check('SHA-256', hashlib.sha256(b'abc').hexdigest()))

	def test_published_result_focuses_output_for_enter_copy(self):
		from calculate_file_hash.hashing import HashResult
		from PyQt5.QtTest import QTest
		window = self.controller.show(self.pane)
		self.run_in_app(lambda: QApplication.setActiveWindow(window))
		for algorithm, digest in (('sha256', 'first digest'), ('sha512', 'new digest')):
			request = window.session.begin(self.url, algorithm, False)
			self.assertFalse(self.run_in_app(window.output.isEnabled))
			window.session.complete(request, HashResult(digest, 3, False))
			def check():
				QApplication.processEvents()
				focused = QApplication.focusWidget()
				self.assertIsNotNone(focused)
				self.assertTrue(focused is window.output or window.output.isAncestorOf(focused))
				QApplication.clipboard().setText('not copied')
				QTest.keyClick(focused, Qt.Key_Return)
				self.assertEqual(digest, QApplication.clipboard().text())
			self.run_in_app(check)

	def test_canceled_recompute_retains_result(self):
		from calculate_file_hash import CalculateFileHash, CalculateFileHashBy, Task
		from unittest.mock import patch
		for command in (CalculateFileHash, CalculateFileHashBy):
			with self.subTest(command=command.__name__):
				with patch('calculate_file_hash.show_quicksearch', return_value=('', 'sha256')):
					command(self.pane)()
				window = self.controller.show(self.pane)
				before = self.run_in_app(window.output.text)
				before_title = self.run_in_app(window.output.title)
				before_path = self.run_in_app(window.windowTitle)
				with patch('calculate_file_hash.compute_hash', side_effect=Task.Canceled()), \
						patch('calculate_file_hash.show_quicksearch', return_value=('', 'sha512')):
					args = {'algorithm': 'sha512'} if command is CalculateFileHash else {}
					command(self.pane)(**args)
				self.run_in_app(lambda: None)
				self.assertEqual(before, self.run_in_app(window.output.text))
				self.assertEqual(before_title, self.run_in_app(window.output.title))
				self.assertEqual(before_path, self.run_in_app(window.windowTitle))
				self.assertEqual('sha256', self.run_in_app(lambda: window.session.last[1]))
				self.assertIsNone(self.run_in_app(lambda: window.bottom_panel))
				self.assertFalse(self.run_in_app(lambda: window.busy))

	def test_hash_commands_preserve_unrelated_dock(self):
		from calculate_file_hash import CalculateFileHash, CalculateFileHashBy
		from fman.ui import Panel
		from unittest.mock import Mock, patch
		def prepare():
			panel = Panel()
			closed = Mock(side_effect=lambda: self.main.remove_bottom_panel(panel))
			self.main.set_bottom_panel(panel, closed)
			return panel, closed
		panel, closed = self.run_in_app(prepare)
		for command in (CalculateFileHash, CalculateFileHashBy):
			with self.subTest(command=command.__name__), \
					patch('calculate_file_hash.show_quicksearch', return_value=('', 'sha256')):
				command(self.pane)()
				window = self.controller.show(self.pane)
				self.assertIsNone(self.run_in_app(lambda: window.bottom_panel))
				self.assertIs(panel, self.run_in_app(lambda: self.main._panel_dock.panel))
				self.run_in_app(window.close)
				self.assertIs(panel, self.run_in_app(lambda: self.main._panel_dock.panel))
				closed.assert_not_called()

	def test_long_path_elides_without_growing_window(self):
		window = self.controller.show(self.pane)
		def check():
			path = 'C:/' + 'long folder/' * 30 + 'file.txt'
			window.path_label.set_path(path)
			for width in (480, 760):
				window.resize(width, 180)
				QApplication.processEvents()
				label = window.path_label
				self.assertLessEqual(label.fontMetrics().horizontalAdvance(label.text()), label.contentsRect().width())
				self.assertEqual(path, label.toolTip())
				self.assertEqual(width, window.width())
		self.run_in_app(check)

	def test_auto_copy_and_closed_session_reject_late_results(self):
		from calculate_file_hash import CalculateFileHash, Task
		from calculate_file_hash.hashing import HashResult
		from unittest.mock import patch
		with patch('calculate_file_hash.load_json', return_value={'auto_copy': True}):
			CalculateFileHash(self.pane)()
		window = self.controller.show(self.pane)
		self.assertEqual(self.run_in_app(window.output.text), self.run_in_app(lambda: QApplication.clipboard().text()))
		session = window.session
		request = session.begin(self.url, 'sha512', True)
		self.run_in_app(lambda: QApplication.clipboard().setText('keep'))
		self.run_in_app(window.close)
		with self.assertRaises(Task.Canceled):
			request.check_canceled()
		session.complete(request, HashResult('stale', 3, False))
		self.run_in_app(lambda: None)
		self.assertEqual('keep', self.run_in_app(lambda: QApplication.clipboard().text()))

	def test_unload_during_completion_prevents_auto_copy(self):
		from calculate_file_hash.hashing import HashResult
		window = self.controller.show(self.pane)
		request = window.session.begin(self.url, 'sha256', True)
		def prepare():
			QApplication.clipboard().setText('keep')
			window.busy_changed.connect(lambda busy: None if busy else self.owner.invalidate())
		self.run_in_app(prepare)
		window.session.complete(request, HashResult('late', 3, False))
		self.run_in_app(lambda: None)
		self.assertEqual('keep', self.run_in_app(lambda: QApplication.clipboard().text()))

class PublicUiIT(QtIT):
	def setUp(self):
		from fman.ui import UiController, UiOwner, QuickList, Panel
		from PyQt5.QtCore import QThread
		from PyQt5.QtWidgets import QWidget, QVBoxLayout
		from unittest.mock import Mock
		self.build_threads = []
		threads = self.build_threads
		class Demo(UiController):
			@classmethod
			def build(cls, window, pane):
				threads.append(QThread.currentThread())
				layout = QVBoxLayout(window)
				view = QuickList(window, fuzzy=True, css=window.item_css)
				layout.addWidget(view)
				layout.addWidget(Panel(window))
				window.focus_widget = view
		Demo.owner = UiOwner()
		self.controller = Demo
		def prepare():
			from fman import DirectoryPane
			self.parent = QWidget()
			self.parent._theme = Mock()
			self.parent._theme.get_quicksearch_item_css.return_value = None
			self.pane = Mock()
			self.pane._widget = self.parent
			self.pane.window._widget = self.parent
			self.pane.on_closed = DirectoryPane.on_closed.__get__(self.pane)
		self.run_in_app(prepare)

	def tearDown(self):
		self.controller.owner.invalidate()
		self.run_in_app(self.parent.deleteLater)

	def test_worker_command_construction_reuse_and_unload(self):
		window = self.controller.show(self.pane, 'seed')
		self.assertEqual([QApplication.instance().thread()], self.build_threads)
		self.assertEqual('seed', self.run_in_app(window.focus_widget.query.text))
		self.assertIs(window, self.controller.show(self.pane))
		self.assertEqual('seed', self.run_in_app(window.focus_widget.query.text))
		self.controller.show(self.pane, 'replacement')
		self.assertEqual('replacement', self.run_in_app(window.focus_widget.query.text))
		self.assertEqual(1, len(self.build_threads))
		closed = Event()
		self.run_in_app(lambda: window.disposed.connect(closed.set))
		self.controller.owner.invalidate()
		self.assertTrue(closed.wait(2))
		with self.assertRaisesRegex(RuntimeError, 'active plug-in owner'):
			self.controller.show(self.pane)

	def test_pane_close_callback_registration_and_unsubscribe(self):
		from fman import DirectoryPane
		from PyQt5 import sip
		from PyQt5.QtCore import QThread
		from PyQt5.QtWidgets import QWidget
		from unittest.mock import Mock
		widget = self.run_in_app(QWidget)
		pane = DirectoryPane(None, widget, Mock())
		calls = []
		removed = Mock()
		unsubscribe = pane.on_closed(lambda: calls.append(QThread.currentThread()))
		cancel = pane.on_closed(removed)
		cancel()
		cancel()
		self.run_in_app(sip.delete, widget)
		self.assertEqual([QApplication.instance().thread()], calls)
		removed.assert_not_called()
		unsubscribe()
		with self.assertRaises(TypeError):
			pane.on_closed(None)

	def test_widget_constructors_reject_command_thread(self):
		from fman.ui import QuickList, Panel, TextButton, IconButton, DropDown, JsonSettings
		constructors = (QuickList, Panel, lambda: TextButton('Run'),
			lambda: IconButton(None, 'Mode'), lambda: DropDown((('One', 1),), 'Choice'),
			lambda: JsonSettings('Test.json', None))
		for construct in constructors:
			with self.assertRaisesRegex(RuntimeError, 'UiController.build'):
				construct()

	def test_pane_path_callback_thread_and_unsubscribe(self):
		from fman import DirectoryPane
		from PyQt5 import sip
		from PyQt5.QtCore import QThread, pyqtSignal
		from PyQt5.QtWidgets import QWidget
		from unittest.mock import Mock
		class PaneWidget(QWidget):
			location_changed = pyqtSignal(object)
		widget = self.run_in_app(PaneWidget)
		pane = DirectoryPane(None, widget, Mock())
		calls = []
		unsubscribe = pane.on_path_changed(lambda: calls.append(QThread.currentThread()))
		self.run_in_app(widget.location_changed.emit, widget)
		self.assertEqual([QApplication.instance().thread()], calls)
		unsubscribe()
		unsubscribe()
		self.run_in_app(widget.location_changed.emit, widget)
		self.assertEqual(1, len(calls))
		self.run_in_app(sip.delete, widget)
		unsubscribe()
		with self.assertRaises(TypeError):
			pane.on_path_changed(None)

	def test_navigation_timeout_covers_blocked_precheck(self):
		from fman.ui import navigate
		window = self.controller.show(self.pane)
		started, release, exited, finished = Event(), Event(), Event(), Event()
		outcomes = []
		def check(url):
			started.set()
			try:
				release.wait(2)
			finally:
				exited.set()
		def completed(*result):
			outcomes.append(result)
			finished.set()
		try:
			handle = self.run_in_app(navigate, self.pane, 'file:///C:/Target', completed,
				window=window, check=check, timeout=0.05)
			self.assertTrue(started.wait(2))
			self.assertTrue(finished.wait(2))
			self.assertTrue(handle.done)
			self.assertEqual('failure', outcomes[0][0])
			self.assertIn('timed out', outcomes[0][1])
			handle.cancel()
			self.assertEqual(1, len(outcomes))
		finally:
			release.set()
			self.assertTrue(exited.wait(2))
		self.pane.run_command.assert_not_called()

	def test_navigation_saturation_and_busy_state(self):
		from fman.ui import navigate
		from unittest.mock import patch
		window = self.controller.show(self.pane)
		finished = Event()
		outcomes = []
		def completed(*result):
			outcomes.append(result)
			finished.set()
		with patch('fman.impl.ui.session.submit_work', return_value=False):
			handle = self.run_in_app(navigate, self.pane, 'file:///C:/Target', completed, window=window)
			self.assertTrue(finished.wait(2))
			self.assertTrue(handle.done)
			self.assertEqual('failure', outcomes[-1][0])
			self.assertFalse(window.busy)
		finished.clear()
		self.run_in_app(window.set_busy, True)
		self.run_in_app(navigate, self.pane, 'file:///C:/Target', completed, window=window)
		self.assertTrue(finished.wait(2))
		self.assertTrue(window.busy)

class DockedPanelIT(QtIT):
	def test_public_controller_dock_unload_and_late_result(self):
		from fman import DirectoryPane, Window
		from fman.ui import UiController, UiOwner, Panel, QuickList, TextButton
		from fman.impl.widgets import MainWindow
		from PyQt5.QtWidgets import QWidget, QVBoxLayout
		from unittest.mock import Mock
		class Demo(UiController):
			@classmethod
			def build(cls, window, pane):
				view = QuickList(window, fuzzy=True)
				window.focus_widget = view
				QVBoxLayout(window).addWidget(view)
				panel = Panel()
				panel.add(TextButton('Run'))
				window.set_panel(panel)
		Demo.owner = UiOwner()
		def prepare():
			theme = Mock()
			theme.get_quicksearch_item_css.return_value = None
			main = MainWindow(Mock(), [], theme, Mock(), Mock(), 'null://')
			pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
			main.show()
			return main, pane
		main, pane = self.run_in_app(prepare)
		started, release, exited, disposed = Event(), Event(), Event(), Event()
		completed = Mock()
		try:
			window = Demo.show(pane)
			self.assertIs(window, Demo.show(pane))
			self.assertIs(window.bottom_panel, self.run_in_app(lambda: main._panel_dock.panel))
			def detach_and_restore():
				window.set_panel(None)
				self.assertIsNone(main._panel_dock)
				self.assertIsNone(window.bottom_panel)
				self.assertTrue(window.alive.is_set())
				self.assertTrue(window.isVisible())
				window.set_panel(None)
				panel = Panel()
				panel.add(TextButton('Run'))
				window.set_panel(panel)
				self.assertIs(panel, main._panel_dock.panel)
			self.run_in_app(detach_and_restore)
			self.run_in_app(lambda: window.disposed.connect(disposed.set))
			def operation():
				started.set()
				try:
					release.wait(2)
				finally:
					exited.set()
			self.assertTrue(self.run_in_app(window.work, operation, completed))
			self.assertTrue(started.wait(2))
			Demo.owner.invalidate()
			self.assertTrue(disposed.wait(2))
			self.assertIsNone(self.run_in_app(lambda: main._panel_dock))
			release.set()
			self.assertTrue(exited.wait(2))
			self.run_in_app(lambda: None)
			completed.assert_not_called()
		finally:
			release.set()
			Demo.owner.invalidate()
			self.run_in_app(main.close)
			self.run_in_app(main.deleteLater)

	def test_main_window_panel_geometry_close_and_replacement(self):
		def check():
			from fman.impl.widgets import MainWindow
			from fman.ui import Panel, TextButton
			from PyQt5.QtCore import QPoint
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import Mock
			window = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
			window._splitter.addWidget(QWidget())
			window._splitter.addWidget(QWidget())
			window.resize(960, 600)
			window.show()
			QApplication.processEvents()
			original_height = window._splitter.height()
			panel = Panel()
			panel.add(TextButton('Run'))
			closed = Mock(side_effect=lambda: window.remove_bottom_panel(panel))
			try:
				window.set_bottom_panel(panel, closed)
				QApplication.processEvents()
				dock = window._panel_dock
				self.assertEqual(window.centralWidget().width(), dock.width())
				self.assertEqual(dock.mapTo(window, QPoint(0, dock.height())).y(),
					window.statusBar().mapTo(window, QPoint(0, 0)).y())
				self.assertLess(window._splitter.height(), original_height)
				self.assertFalse(dock.close_button.icon().isNull())
				QTest.mouseClick(dock.close_button, Qt.LeftButton)
				QApplication.processEvents()
				closed.assert_called_once()
				self.assertIsNone(window._panel_dock)
				self.assertEqual(original_height, window._splitter.height())
				first, second = Panel(), Panel()
				replaced = Mock(side_effect=lambda: window.remove_bottom_panel(first))
				window.set_bottom_panel(first, replaced)
				window.set_bottom_panel(second, lambda: window.remove_bottom_panel(second))
				replaced.assert_called_once()
				window.remove_bottom_panel(first)
				self.assertIs(second, window._panel_dock.panel)
				window.remove_bottom_panel(second)
			finally:
				window.close()
				window.deleteLater()
		self.run_in_app(check)


class QuickListIT(QtIT):
	def test_filter_arrows_transfer_focus_before_space_selection(self):
		def check():
			from fman.ui import QuickList, ListItem
			from PyQt5.QtTest import QTest
			widget = QuickList(fuzzy=True)
			try:
				widget.set_items(tuple(ListItem(str(row), 'Item %d' % row) for row in range(4)))
				widget.show()
				widget.activateWindow()
				QApplication.processEvents()
				for key in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
					widget.query.setText('Item')
					widget.query.setFocus()
					self.assertIs(widget.query, QApplication.focusWidget())
					QTest.keyClick(widget.query, key)
					self.assertIs(widget.view, QApplication.focusWidget())
					current = widget.current_id
					before = set(widget.selected_ids)
					QTest.keyClick(QApplication.focusWidget(), Qt.Key_Space)
					self.assertEqual(before ^ {current}, widget.selected_ids)
					self.assertEqual('Item', widget.query.text())
				widget.query.setFocus()
				widget.query.setCursorPosition(len(widget.query.text()))
				before = set(widget.selected_ids)
				QTest.keyClick(widget.query, Qt.Key_Space)
				self.assertEqual('Item ', widget.query.text())
				self.assertEqual(before, widget.selected_ids)
				widget.set_items(())
				QTest.keyClick(widget.query, Qt.Key_Down)
				QTest.keyClick(QApplication.focusWidget(), Qt.Key_Space)
				self.assertEqual(set(), widget.selected_ids)
			finally:
				widget.deleteLater()
		self.run_in_app(check)

	def test_right_click_toggles_rows_with_optional_filter(self):
		def check():
			from fman.ui import QuickList, ListItem
			from PyQt5.QtCore import QPoint
			from PyQt5.QtTest import QTest
			from unittest.mock import Mock
			for options in ({}, {'fuzzy': False}, {'fuzzy': True}):
				widget = QuickList(**options)
				activated = Mock()
				widget.activated.connect(activated)
				try:
					widget.resize(480, 350)
					widget.set_items((ListItem('a', 'Alpha'), ListItem('b', 'Beta')))
					widget.show()
					widget.activateWindow()
					widget.setFocus()
					QApplication.processEvents()
					filtered = options.get('fuzzy', False)
					self.assertEqual(not filtered, widget.query.isHidden())
					self.assertIs(widget.query if filtered else widget.view, QApplication.focusWidget())
					for row, expected in ((0, {'a'}), (1, {'a', 'b'}), (0, {'b'})):
						point = widget.view.visualRect(widget.model.index(row, 0)).center()
						QTest.mouseClick(widget.view.viewport(), Qt.RightButton, pos=point)
						self.assertEqual(expected, widget.selected_ids)
					QTest.mouseClick(widget.view.viewport(), Qt.RightButton,
						pos=QPoint(5, widget.view.viewport().height() - 5))
					self.assertEqual({'b'}, widget.selected_ids)
					widget.query.setText('Alpha')
					self.assertEqual(1 if filtered else 2, widget.model.rowCount())
					self.assertEqual({'b'}, widget.selected_ids)
					activated.assert_not_called()
				finally:
					widget.deleteLater()
		self.run_in_app(check)

	def test_public_embedded_view_mouse_selection_and_optional_filter(self):
		def check():
			from fman.ui import QuickList, ListItem
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QWidget
			parent = QWidget()
			widget = QuickList(parent, fuzzy=True)
			try:
				widget.resize(480, 300)
				widget.set_items((ListItem('a', 'Alpha'), ListItem('b', 'Beta'), ListItem('c', 'Gamma')))
				parent.show()
				widget.show()
				QApplication.processEvents()
				self.assertFalse(widget.isWindow())
				point = widget.view.visualRect(widget.model.index(1, 0)).center()
				QTest.mouseClick(widget.view.viewport(), Qt.LeftButton, pos=point)
				self.assertEqual('b', widget.current_item.id)
				self.assertEqual((), widget.selected_items)
				QTest.mouseClick(widget.view.viewport(), Qt.LeftButton, Qt.ControlModifier, point)
				self.assertEqual(('b',), tuple(item.id for item in widget.selected_items))
				point = widget.view.visualRect(widget.model.index(2, 0)).center()
				QTest.mouseClick(widget.view.viewport(), Qt.LeftButton, Qt.ControlModifier, point)
				self.assertEqual({'b', 'c'}, widget.selected_ids)
				widget.view.selectionModel().clearSelection()
				QTest.keyClick(widget.view, Qt.Key_Home)
				QTest.keyClick(widget.view, Qt.Key_End, Qt.ShiftModifier)
				self.assertEqual({'a', 'b', 'c'}, widget.selected_ids)
				QTest.keyClick(widget.view, Qt.Key_Home, Qt.ShiftModifier)
				self.assertEqual(set(), widget.selected_ids)
				QTest.keyClick(widget.view, Qt.Key_Down)
				QTest.keyClick(widget.view, Qt.Key_A, Qt.ControlModifier)
				QTest.keyClick(widget.view, Qt.Key_Space)
				self.assertEqual({'a', 'c'}, widget.selected_ids)
				widget.query.setText('alp')
				self.assertEqual(1, widget.model.rowCount())
				self.assertEqual(1, widget.hidden_selected_count)
				plain = QuickList(parent)
				self.assertTrue(plain.query.isHidden())
			finally:
				parent.deleteLater()
		self.run_in_app(check)

	def test_file_pane_selection_keys_and_text_editing(self):
		def check():
			from fman.impl.ui import ListItem
			from fman.impl.ui.quicklist import QuickList
			from core.quicksearch_matchers import contains_chars
			from PyQt5.QtTest import QTest
			widget = QuickList(matcher=contains_chars)
			try:
				widget.set_items(tuple(ListItem(str(row), 'Item %d' % row) for row in range(4)))
				widget.show()
				QTest.keyClick(widget.view, Qt.Key_Space)
				self.assertEqual({'0'}, widget.selected_ids)
				self.assertEqual('0', widget.current_id)
				QTest.keyClick(widget.view, Qt.Key_Down)
				QTest.keyClick(widget.view, Qt.Key_Insert)
				self.assertEqual({'0', '1'}, widget.selected_ids)
				self.assertEqual('2', widget.current_id)
				QTest.keyClick(widget.view, Qt.Key_Down, Qt.ShiftModifier)
				self.assertEqual({'0', '1', '2'}, widget.selected_ids)
				self.assertEqual('3', widget.current_id)
				QTest.keyClick(widget.view, Qt.Key_A, Qt.ControlModifier)
				self.assertEqual(4, len(widget.selected_ids))
				widget.query.setText('Item')
				QTest.keyClick(widget.query, Qt.Key_Space)
				self.assertEqual('Item ', widget.query.text())
				self.assertEqual(4, len(widget.selected_ids))
				widget.query.setText('3')
				self.assertEqual(3, widget.hidden_selected_count)
				QTest.keyClick(widget.view, Qt.Key_Space)
				self.assertEqual({'0', '1', '2'}, widget.selected_ids)
			finally:
				widget.deleteLater()
		self.run_in_app(check)

	def test_rows_fit_after_window_narrows(self):
		def check():
			from fman.impl.ui import ListItem
			from fman.impl.ui.quicklist import QuickList
			widget = QuickList()
			try:
				widget.resize(680, 300)
				widget.set_items((ListItem('id', 'Name', 'Long path ' * 40),))
				widget.show()
				QApplication.processEvents()
				widget.resize(480, 300)
				QApplication.processEvents()
				widget.view.doItemsLayout()
				rect = widget.view.visualRect(widget.model.index(0, 0))
				self.assertLessEqual(rect.right(), widget.view.viewport().rect().right())
				self.assertFalse(widget.view.horizontalScrollBar().isVisible())
			finally:
				widget.deleteLater()
		self.run_in_app(check)

	def test_delegate_without_widget_and_custom_panel_label(self):
		def check():
			from fman.impl.ui import ListItem
			from fman.ui import QuickList, Panel, DropDown, TextButton
			from PyQt5.QtWidgets import QStyleOptionViewItem
			from PyQt5.QtGui import QPixmap, QPainter
			from PyQt5.QtCore import QRect
			widget = QuickList()
			panel = Panel()
			choice = panel.add(DropDown((('One', 'one'),), 'Mode'))
			button = panel.add(TextButton('Apply'))
			try:
				widget.set_items((ListItem('id', 'Name', 'Path'),))
				option = QStyleOptionViewItem()
				option.rect = QRect(0, 0, 320, 64)
				pixmap = QPixmap(320, 64)
				painter = QPainter(pixmap)
				try:
					delegate = widget.view.itemDelegate()
					delegate.paint(painter, option, widget.model.index(0, 0))
					self.assertEqual(320, delegate.sizeHint(option, widget.model.index(0, 0)).width())
				finally:
					painter.end()
				self.assertEqual('Mode', choice.accessibleName())
				self.assertEqual('', button.styleSheet())
			finally:
				widget.deleteLater()
				panel.deleteLater()
		self.run_in_app(check)
	def test_selection_survives_filter_and_clear(self):
		def check():
			from core.quicksearch_matchers import contains_chars
			from fman.impl.ui import ListItem
			from fman.impl.ui.quicklist import QuickList
			from PyQt5.QtCore import QItemSelectionModel
			widget = QuickList(matcher=contains_chars)
			try:
				widget.set_items((ListItem('a', 'Alpha'), ListItem('b', 'Beta')))
				self.assertEqual('a', widget.current_id)
				self.assertEqual(set(), widget.selected_ids)
				widget.view.selectionModel().select(widget.model.index(1, 0), QItemSelectionModel.Select)
				widget.query.setText('alpha')
				self.assertEqual({'b'}, widget.selected_ids)
				self.assertEqual(1, widget.hidden_selected_count)
				widget.query.clear()
				self.assertEqual({'b'}, widget.selected_ids)
				self.assertEqual(1, len(widget.view.selectedIndexes()))
			finally:
				widget.deleteLater()
		self.run_in_app(check)

	def test_field_highlights_and_disabled_filter(self):
		def check():
			from core.quicksearch_matchers import contains_chars
			from fman.impl.ui import ListItem
			from fman.impl.ui.quicklist import QuickList
			widget = QuickList(matcher=contains_chars)
			try:
				widget.set_items((ListItem('a', 'Other', 'Ma\u00dfe'),))
				widget.query.setText('ss')
				self.assertEqual((2,), widget.model.items[0].hint_matches)
				widget.matcher = None
				widget.query.setText('absent')
				self.assertEqual(1, widget.model.rowCount())
			finally:
				widget.deleteLater()
		self.run_in_app(check)

	def test_filter_order_can_preserve_consumer_sort(self):
		def check():
			from core.quicksearch_matchers import contains_chars
			from fman.impl.ui import ListItem
			from fman.impl.ui.quicklist import QuickList
			widget = QuickList(matcher=contains_chars, preserve_sort=True)
			try:
				widget.set_items((ListItem('a', 'za'), ListItem('b', 'a')))
				widget.query.setText('a')
				self.assertEqual(['a', 'b'], [item.id for item in widget.model.items])
				widget.preserve_sort = False
				widget.refresh()
				self.assertEqual(['b', 'a'], [item.id for item in widget.model.items])
			finally:
				widget.deleteLater()
		self.run_in_app(check)

class PanelIT(QtIT):
	def test_textfield_tooltip_is_on_label_and_input(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import TextField, UiOwner, show_panel
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import Mock
			main = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
			pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
			owner = UiOwner()
			main.show()
			try:
				panel = show_panel(owner=owner, pane=pane, rows=((TextField('content', 'Content Pattern', tooltip='Content matching rule'),),
					(TextField('fallback', 'Fallback label'),)))
				host = _hosts[panel._key()]
				for record, wrapper, label in host.form.fields:
					self.assertEqual(record.tooltip or record.label, label.toolTip())
					self.assertEqual(label.toolTip(), host.controls[record.id][1].toolTip())
			finally:
				owner.invalidate()
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_action_widths_adapt_and_stop_at_cap(self):
		def check():
			from fman.ui import Panel, TextButton, DropDown
			from PyQt5.QtWidgets import QStyle, QStyleOptionButton
			panel = Panel()
			panel.add(DropDown((('Recent', 'recent'),), 'Sort'))
			panel.add_stretch()
			buttons = [panel.add(TextButton(label)) for label in ('Delete', 'Rename', 'Go To')]
			try:
				panel.show()
				widths = []
				for width in (480, 680, 1400):
					panel.resize(width, panel.sizeHint().height())
					QApplication.processEvents()
					widths.append([button.width() for button in buttons])
					if width >= 680:
						self.assertLessEqual(max(widths[-1]) - min(widths[-1]), 1)
					for button in buttons:
						self.assertLessEqual(button.width(), 160)
						option = QStyleOptionButton()
						button.initStyleOption(option)
						content = button.style().subElementRect(QStyle.SE_PushButtonContents, option, button)
						self.assertGreaterEqual(content.width(), button.fontMetrics().horizontalAdvance(button.text()))
				self.assertLess(widths[0][0], widths[1][0])
				self.assertEqual([160] * 3, widths[-1])
				custom = panel.add(TextButton('Run', max_width=120))
				QApplication.processEvents()
				self.assertEqual(120, custom.width())
				with self.assertRaises(ValueError):
					TextButton('Run', max_width=0)
			finally:
				panel.deleteLater()
		self.run_in_app(check)

	def test_two_bindings_save_failure_and_disposal(self):
		from copy import deepcopy
		from unittest.mock import patch
		from fman.ui import Panel, DropDown, TextButton, JsonSettings, UiOwner
		from fman.impl.ui import resource
		from fman.impl.util.qt.thread import is_in_main_thread
		data = {'mode': 'first', 'enabled': False, 'other': 42}
		ready = [Event(), Event()]
		failed, refreshed = Event(), Event()
		owner = UiOwner()
		def create(index):
			panel = Panel()
			choice = panel.add(DropDown((('First', 'first'), ('Second', 'second')), 'Mode'))
			toggle = panel.add(TextButton('Enabled', checkable=True))
			settings = JsonSettings('PanelSharedTest.json', panel, owner)
			settings.bind('mode', choice, 'first')
			settings.bind('enabled', toggle, False)
			settings.busy_changed.connect(lambda busy: ready[index].set() if not busy else None)
			settings.failed.connect(lambda message: failed.set())
			settings.load()
			return panel, choice, toggle, settings
		def save(filename, values):
			self.assertFalse(is_in_main_thread())
			data.update(deepcopy(values))
		with patch('fman.impl.ui.panel.load_json', side_effect=lambda *args, **kwargs: deepcopy(data)), \
				patch('fman.impl.ui.panel.save_json', side_effect=save) as save_mock:
			first = self.run_in_app(create, 0)
			second = self.run_in_app(create, 1)
			try:
				self.assertTrue(all(event.wait(2) for event in ready))
				self.run_in_app(lambda: second[3].changed.connect(lambda values: refreshed.set()))
				ready[0].clear()
				self.run_in_app(first[1].set_value, 'second')
				self.assertTrue(ready[0].wait(2))
				self.assertTrue(refreshed.wait(2))
				self.assertEqual('second', self.run_in_app(second[1].value))
				self.assertEqual(42, data['other'])
				save_mock.side_effect = PermissionError('Cannot save settings')
				self.run_in_app(first[2].click)
				self.assertTrue(failed.wait(2))
				self.assertFalse(self.run_in_app(first[2].isChecked))
				self.assertFalse(data['enabled'])
				save_mock.reset_mock()
				with resource('PanelSharedTest.json').lock:
					self.run_in_app(first[1].set_value, 'first')
					owner.invalidate()
				self.run_in_app(first[3].dispose)
			finally:
				for panel, choice, toggle, settings in (first, second):
					self.run_in_app(settings.dispose)
					self.run_in_app(panel.deleteLater)
			save_mock.assert_not_called()

	def test_invalid_stored_values_default_without_writing(self):
		from unittest.mock import patch
		from fman.ui import Panel, DropDown, TextButton, JsonSettings
		ready = Event()
		def create():
			panel = Panel()
			choice = panel.add(DropDown((('A', 'a'), ('B', 'b')), 'Mode'))
			settings = JsonSettings('PanelInvalidTest.json', panel)
			settings.bind('mode', choice, 'a')
			with self.assertRaises(ValueError):
				settings.bind('action', TextButton('Run', panel), False)
			settings.busy_changed.connect(lambda busy: ready.set() if not busy else None)
			settings.load()
			return panel, choice, settings
		with patch('fman.impl.ui.panel.load_json', return_value={'mode': ['invalid']}), \
				patch('fman.impl.ui.panel.save_json') as save:
			panel, choice, settings = self.run_in_app(create)
			try:
				self.assertTrue(ready.wait(2))
				self.assertEqual('a', self.run_in_app(choice.value))
				save.assert_not_called()
			finally:
				self.run_in_app(settings.dispose)
				self.run_in_app(panel.deleteLater)

	def test_public_controls_and_json_roundtrip(self):
		from copy import deepcopy
		from unittest.mock import patch
		from fman.ui import Panel, IconButton, TextButton, DropDown, JsonSettings
		from fman.impl.util.qt.thread import is_in_main_thread
		from PyQt5.QtWidgets import QStyle
		data = {'case_sensitive': True, 'scope': 'all', 'unrelated': {'keep': 1}}
		loaded, saved = Event(), Event()
		def load(*args, **kwargs):
			self.assertFalse(is_in_main_thread())
			return deepcopy(data)
		def save(filename, values):
			self.assertFalse(is_in_main_thread())
			data.update(deepcopy(values))
			saved.set()
		def create():
			panel = Panel()
			icon = panel.style().standardIcon(QStyle.SP_FileDialogDetailedView)
			button = panel.add(IconButton(icon, 'Match case'))
			choice = panel.add(DropDown((('Current', 'current'), ('All', 'all')), 'Scope'))
			action = panel.add(TextButton('Find'))
			settings = JsonSettings('PanelTest.json', panel)
			settings.bind('case_sensitive', button, False)
			settings.bind('scope', choice, 'current')
			settings.busy_changed.connect(lambda busy: loaded.set() if not busy else None)
			settings.load()
			return panel, button, choice, action, settings
		with patch('fman.impl.ui.panel.load_json', side_effect=load), \
				patch('fman.impl.ui.panel.save_json', side_effect=save):
			panel, button, choice, action, settings = self.run_in_app(create)
			try:
				self.assertTrue(loaded.wait(2))
				self.assertTrue(self.run_in_app(button.isChecked))
				self.assertEqual('all', self.run_in_app(choice.value))
				self.run_in_app(action.click)
				self.assertFalse(saved.is_set())
				loaded.clear()
				self.run_in_app(button.click)
				self.assertTrue(saved.wait(2))
				self.assertTrue(loaded.wait(2))
				self.assertFalse(data['case_sensitive'])
				self.assertEqual({'keep': 1}, data['unrelated'])
			finally:
				self.run_in_app(settings.dispose)
				self.run_in_app(panel.deleteLater)


class FavoritesManagerIT(QtIT):
	def test_split_focus_recovers_after_geometry_and_activation_changes(self):
		from fman_integrationtest.favorites_smoke import exercise_split_focus
		self.run_in_app(exercise_split_focus, self.window, self.parent)

	def test_controller_builds_plain_session_in_shared_host(self):
		from favorites.ui import FavoritesController, FavoritesSession
		from fman.ui import PaneToolWindow
		from PyQt5.QtCore import QObject
		self.assertIs(type(self.window), PaneToolWindow)
		self.assertIsNone(FavoritesController.window_type)
		self.assertIs(type(self.window.session), FavoritesSession)
		self.assertNotIsInstance(self.window.session, QObject)

	def test_view_panel_and_frameless_host_are_separate(self):
		def check():
			from PyQt5.QtWidgets import QPushButton, QToolButton
			self.assertTrue(self.window.windowFlags() & Qt.FramelessWindowHint)
			self.assertFalse(self.window.list.isWindow())
			self.assertIs(self.window.list.parentWidget(), self.window)
			self.assertIs(self.window.panel.parentWidget(), self.parent._panel_dock)
			self.assertIs(self.window.panel.window(), self.parent)
			self.assertFalse(self.window.list.findChildren(QPushButton))
			self.assertFalse(self.window.list.findChildren(QToolButton))
			self.assertFalse(self.window.panel.findChildren(QToolButton))
		self.run_in_app(check)

	def test_shared_confirmation_defaults_to_no_and_escape_keeps_manager(self):
		def check():
			from unittest.mock import Mock
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QDialogButtonBox
			accepted = Mock()
			self.window.confirm('Confirm operation', (('Item', 'Path'),), 0, 'Details', accepted)
			prompt = self.window.prompt
			buttons = prompt.findChild(QDialogButtonBox)
			self.assertTrue(buttons.button(QDialogButtonBox.No).isDefault())
			self.assertEqual(Qt.WindowModal, prompt.windowModality())
			QTest.keyClick(prompt, Qt.Key_Escape)
			self.assertIsNone(self.window.prompt)
			self.assertTrue(self.window.alive.is_set())
			self.assertFalse(self.window.busy)
			accepted.assert_not_called()
		self.run_in_app(check)

	def test_pane_destruction_closes_hosted_manager(self):
		def check():
			from PyQt5 import sip
			sip.delete(self.pane._widget)
			self.assertFalse(self.window.alive.is_set())
		self.run_in_app(check)

	def setUp(self):
		from unittest.mock import Mock, patch
		from favorites.store import Favorite
		from favorites.ui import FavoritesController
		from fman.ui import PaneToolWindow
		from fman.impl.ui import UiOwner
		from fman.impl.widgets import MainWindow
		from PyQt5.QtWidgets import QWidget
		settings_patch = patch('favorites.ui.JsonSettings')
		settings_patch.start()
		self.addCleanup(settings_patch.stop)
		def create():
			from fman import DirectoryPane
			self.parent = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
			self.parent._theme.get_quicksearch_item_css.return_value = None
			self.parent.resize(960, 600)
			self.parent.show()
			self.pane = Mock()
			self.pane._widget = QWidget(self.parent)
			self.pane.window._widget = self.parent
			self.pane.on_closed = DirectoryPane.on_closed.__get__(self.pane)
			self.owner = UiOwner()
			with patch.object(PaneToolWindow, 'work', return_value=True):
				self.window = PaneToolWindow(self.pane, self.owner)
				FavoritesController.build(self.window, self.pane)
			self.window.session._apply_snapshot((0, (
				Favorite('Zulu', 'file:///C:/A'),
				Favorite('Alpha', 'file:///C:/Z'),
				Favorite('Other', 'example://Other')
			)))
			self.window.show()
		self.run_in_app(create)

	def tearDown(self):
		def dispose():
			from PyQt5 import sip
			if not sip.isdeleted(self.window):
				self.window.close()
			self.parent.close()
			self.parent.deleteLater()
		self.run_in_app(dispose)

	def test_dock_close_ends_session_and_cancels_navigation(self):
		def check():
			from fman.impl.navigation import NavigationRequest
			from PyQt5.QtTest import QTest
			request = NavigationRequest(lambda *args: None)
			self.window.session.navigation = request
			QTest.mouseClick(self.parent._panel_dock.close_button, Qt.LeftButton)
			self.assertFalse(self.window.alive.is_set())
			self.assertTrue(request.done)
			self.assertIsNone(self.parent._panel_dock)
			self.window.settings.dispose.assert_called_once()
		self.run_in_app(check)

	def test_escape_in_panel_closes_session(self):
		def check():
			from PyQt5.QtTest import QTest
			self.parent.activateWindow()
			self.window.panel.choice.setFocus()
			QApplication.processEvents()
			QTest.keyClick(self.window.panel.choice, Qt.Key_Escape)
			self.assertFalse(self.window.alive.is_set())
			self.assertIsNone(self.parent._panel_dock)
		self.run_in_app(check)

	def test_tab_moves_between_list_and_docked_controls(self):
		def check():
			from PyQt5.QtTest import QTest
			self.window.activateWindow()
			self.window.list.view.setFocus()
			QApplication.processEvents()
			QTest.keyClick(self.window.list.view, Qt.Key_Tab)
			QApplication.processEvents()
			self.assertIs(self.window.panel.choice, QApplication.focusWidget())
			QTest.keyClick(self.window.panel.choice, Qt.Key_Tab, Qt.ShiftModifier)
			QApplication.processEvents()
			self.assertIs(self.window.list.view, QApplication.focusWidget())
			self.parent.activateWindow()
			self.parent._panel_dock.close_button.setFocus()
			QApplication.processEvents()
			QTest.keyClick(self.parent._panel_dock.close_button, Qt.Key_Tab)
			QApplication.processEvents()
			self.assertIs(self.window.list.query, QApplication.focusWidget())
		self.run_in_app(check)

	def test_panel_close_rejects_prompt_without_mutating(self):
		def check():
			from unittest.mock import Mock
			self.window.session._mutate = Mock()
			self.window.session.action('rename')
			self.parent._panel_dock.close_button.click()
			self.assertFalse(self.window.alive.is_set())
			self.assertIsNone(self.parent._panel_dock)
			self.window.session._mutate.assert_not_called()
		self.run_in_app(check)

	def test_new_docked_session_disposes_previous_session(self):
		def check():
			from favorites.ui import FavoritesController
			from fman.ui import PaneToolWindow
			from unittest.mock import patch
			with patch.object(FavoritesController, 'owner', self.owner), \
					patch.object(PaneToolWindow, 'work', return_value=True):
				new = FavoritesController.show(self.pane)
				self.assertFalse(self.window.alive.is_set())
				self.assertIs(new.panel, self.parent._panel_dock.panel)
				self.parent.close()
				self.assertFalse(new.alive.is_set())
				self.assertIsNone(self.parent._panel_dock)
		self.run_in_app(check)

	def test_sort_is_a_projection_and_keeps_selection(self):
		def check():
			from PyQt5.QtCore import QItemSelectionModel
			window = self.window
			self.assertEqual('Recent', window.panel.choice.currentText())
			window.list.view.selectionModel().select(window.list.model.index(0, 0), QItemSelectionModel.Select)
			window.panel.choice.setCurrentText('Name')
			self.assertEqual(['Alpha', 'Other', 'Zulu'], [item.title for item in window.list.model.items])
			window.list.query.setText('a')
			self.assertEqual(['Alpha', 'Other', 'Zulu'], [item.title for item in window.list.model.items])
			self.assertEqual({'file:///c:/a'}, window.list.selected_ids)
			self.assertEqual('Zulu', window.session.records[0].name)
		self.run_in_app(check)

	def test_delete_button_captures_hidden_selection_without_confirmation(self):
		def check():
			from unittest.mock import Mock
			from PyQt5.QtTest import QTest
			window = self.window
			window.session._mutate = Mock()
			window.list.selected_ids = {'file:///c:/z'}
			window.list.query.setText('Zulu')
			QTest.mouseClick(window.panel.buttons['delete'], Qt.LeftButton)
			self.assertIsNone(window.prompt)
			window.session._mutate.assert_called_once_with((window.session.records[1],), None)
			window.list.selected_ids.clear()
			captured, name = window.session._mutate.call_args.args
			self.assertEqual('Alpha', captured[0].name)
			self.assertIsNone(name)
			self.assertTrue(window.alive.is_set())
		self.run_in_app(check)

	def test_delete_button_current_fallback_and_empty_list(self):
		def check():
			from unittest.mock import Mock
			from PyQt5.QtTest import QTest
			window = self.window
			window.session._mutate = Mock()
			QTest.mouseClick(window.panel.buttons['delete'], Qt.LeftButton)
			window.session._mutate.assert_called_once_with((window.session.records[0],), None)
			self.assertIsNone(window.prompt)
			window.session._mutate.reset_mock()
			window.set_busy(True)
			window.session.action('delete')
			window.session._mutate.assert_not_called()
			window.set_busy(False)
			window.session._apply_snapshot((1, ()))
			self.assertFalse(window.panel.buttons['delete'].isEnabled())
			window.session.action('delete')
			window.session._mutate.assert_not_called()
		self.run_in_app(check)

	def test_rename_targets_current_and_escape_keeps_manager(self):
		def check():
			from unittest.mock import Mock
			from PyQt5.QtTest import QTest
			window = self.window
			window.session._mutate = Mock()
			window.list.selected_ids = {'file:///c:/z'}
			window.session.action('rename')
			window.prompt.setTextValue('Renamed')
			window.prompt.accept()
			self.assertEqual('Zulu', window.session._mutate.call_args.args[0][0].name)
			self.assertEqual('Renamed', window.session._mutate.call_args.args[1])
			window.session._mutate.reset_mock()
			window.session.action('rename')
			QTest.keyClick(window.prompt, Qt.Key_Escape)
			window.session._mutate.assert_not_called()
			self.assertTrue(window.alive.is_set())
			self.assertFalse(window.busy)
		self.run_in_app(check)

	def test_query_delete_does_not_invoke_delete_action(self):
		def check():
			from unittest.mock import Mock
			from PyQt5.QtTest import QTest
			window = self.window
			window.session.action = Mock()
			window.list.query.setText('abc')
			window.list.query.selectAll()
			QTest.keyClick(window.list.query, Qt.Key_Delete)
			self.assertEqual('', window.list.query.text())
			window.session.action.assert_not_called()
			QTest.keyClick(window.list.view, Qt.Key_Delete)
			window.session.action.assert_called_once_with('delete')
		self.run_in_app(check)

	def test_stale_snapshot_is_rejected_and_removed_selection_pruned(self):
		def check():
			window = self.window
			window.list.selected_ids = {'file:///c:/z'}
			window.session._apply_snapshot((2, window.session.records[:1]))
			window.session._apply_snapshot((1, ()))
			self.assertEqual(2, window.session.revision)
			self.assertEqual(1, len(window.session.records))
			self.assertEqual(set(), window.list.selected_ids)
			self.assertFalse(window.grab().isNull())
		self.run_in_app(check)

	def test_missing_navigation_keeps_manager_and_prompt_busy(self):
		from unittest.mock import patch
		finished = Event()
		original = self.window.session._navigated
		def navigated(*args):
			original(*args)
			finished.set()
		self.run_in_app(setattr, self.window.session, '_navigated', navigated)
		with patch('favorites.ui.exists', return_value=False):
			self.run_in_app(self.window.session.action, 'goto')
			self.assertTrue(finished.wait(2), 'No navigation failure delivered')
		self.run_in_app(lambda: None)
		def check():
			self.assertTrue(self.window.alive.is_set())
			self.assertIsNotNone(self.window.prompt)
			self.assertTrue(self.window.busy)
			self.pane.run_command.assert_not_called()
		self.run_in_app(check)

	def test_successful_navigation_closes_manager(self):
		from unittest.mock import patch
		from fman.impl.navigation import current_request
		finished = Event()
		def navigate(*args):
			request = current_request()
			request.started = True
			request.finish('success')
			request.settled.set()
		self.pane.run_command.side_effect = navigate
		self.run_in_app(lambda: self.window.finished.connect(finished.set))
		with patch('favorites.ui.exists', return_value=True), \
				patch('favorites.ui.is_dir', return_value=True):
			self.run_in_app(self.window.session.action, 'goto')
			self.assertTrue(finished.wait(2), 'Manager did not close')

	def test_file_favorite_is_rejected_without_changing_pane(self):
		from unittest.mock import patch
		from fman.impl.util.qt.thread import is_in_main_thread
		finished = Event()
		original = self.window.session._navigated
		def navigated(*args):
			original(*args)
			finished.set()
		def file_target(url):
			self.assertFalse(is_in_main_thread())
			return False
		self.run_in_app(setattr, self.window.session, '_navigated', navigated)
		with patch('favorites.ui.exists', return_value=True), \
				patch('favorites.ui.is_dir', side_effect=file_target):
			self.run_in_app(self.window.session.action, 'goto')
			self.assertTrue(finished.wait(2), 'No folder-only failure delivered')
		def check():
			self.assertTrue(self.window.alive.is_set())
			self.assertIn('Favorites must point to folders', self.window.prompt.text())
			self.pane.run_command.assert_not_called()
		self.run_in_app(check)

	def test_two_managers_receive_commits_without_resetting_query(self):
		from unittest.mock import Mock, patch
		from favorites.ui import FavoritesController
		from fman.ui import PaneToolWindow
		from PyQt5.QtWidgets import QWidget
		import favorites
		def create():
			from fman import DirectoryPane
			from fman.impl.widgets import MainWindow
			parent = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
			parent._theme.get_quicksearch_item_css.return_value = None
			pane = Mock()
			pane._widget = QWidget(parent)
			pane.window._widget = parent
			pane.on_closed = DirectoryPane.on_closed.__get__(pane)
			with patch.object(PaneToolWindow, 'work', return_value=True):
				window = PaneToolWindow(pane, self.owner)
				FavoritesController.build(window, pane)
				return parent, window
		other_parent, other = self.run_in_app(create)
		try:
			with patch('favorites.load_json', return_value={'favorites': []}):
				self.window.session._subscribe()
				other.session._subscribe()
			self.run_in_app(self.window.list.query.setText, 'Alpha')
			with favorites._LOCK:
				notification = favorites._resource.committed(self.window.session.records)
			favorites._resource.publish(notification)
			def check():
				self.assertEqual(self.window.session.records, other.session.records)
				self.assertEqual('Alpha', self.window.list.query.text())
				self.assertEqual(3, len(other.session.records))
			self.run_in_app(check)
		finally:
			self.run_in_app(other.close)
			self.run_in_app(other_parent.close)
			self.run_in_app(other_parent.deleteLater)

	def test_controller_reuses_session_and_explicit_query(self):
		from favorites.ui import FavoritesController
		from fman.ui import PaneToolWindow
		from unittest.mock import patch
		def check():
			with patch.object(FavoritesController, 'owner', self.owner), \
					patch.object(PaneToolWindow, 'work', return_value=True):
				FavoritesController.show(self.pane, 'Alpha')
				window = FavoritesController._sessions[self.pane]
				try:
					FavoritesController.show(self.pane)
					self.assertIs(window, FavoritesController._sessions[self.pane])
					self.assertEqual('Alpha', window.list.query.text())
					FavoritesController.show(self.pane, 'Zulu')
					self.assertEqual('Zulu', window.list.query.text())
				finally:
					window.close()
		self.run_in_app(check)

	def test_unload_rejects_prompt_and_disposes_session(self):
		finished = Event()
		def prepare():
			self.window.finished.connect(finished.set)
			self.window.session.action('rename')
		self.run_in_app(prepare)
		self.owner.invalidate()
		self.assertTrue(finished.wait(2), 'Unload did not close manager')
		self.assertFalse(self.window.alive.is_set())

	def test_escape_invalidates_session_before_deferred_destruction(self):
		def check():
			from fman.impl.navigation import NavigationRequest
			from PyQt5.QtTest import QTest
			request = NavigationRequest(lambda *args: None)
			request.started = True
			self.window.session.navigation = request
			QTest.keyClick(self.window.list.query, Qt.Key_Escape)
			self.assertFalse(self.window.alive.is_set())
			self.assertTrue(request.settled.is_set())
		self.run_in_app(check)

	def test_old_worker_completion_cannot_clear_new_busy_state(self):
		def check():
			from unittest.mock import Mock
			completed = Mock()
			self.window._operation_generation = 2
			self.window.set_busy(True)
			self.window._work_finished(1, completed, None, None)
			self.assertTrue(self.window.busy)
			completed.assert_not_called()
		self.run_in_app(check)

	def test_close_during_check_never_starts_navigation(self):
		from unittest.mock import patch
		from fman.impl.navigation import NavigationRequest
		started, release, dispatched = Event(), Event(), Event()
		def exists(url):
			started.set()
			release.wait(2)
			return True
		original = NavigationRequest.dispatch
		def dispatch(request, *args):
			try:
				return original(request, *args)
			finally:
				dispatched.set()
		with patch('favorites.ui.exists', side_effect=exists), \
				patch('favorites.ui.is_dir', return_value=True), \
				patch.object(NavigationRequest, 'dispatch', dispatch):
			try:
				self.run_in_app(self.window.session.action, 'goto')
				self.assertTrue(started.wait(2))
				self.run_in_app(self.window.close)
			finally:
				release.set()
			self.assertTrue(dispatched.wait(2))
		self.pane.run_command.assert_not_called()


def setUpModule():
	_QtApp.start()

def tearDownModule():
	_QtApp.shutdown()

class _QtApp:
	@classmethod
	def start(cls):
		if QApplication.instance() is not None:
			cls._app = QApplication.instance()
			return
		cls._app = QApplication([])
		cls._app.setQuitOnLastWindowClosed(False)
	@classmethod
	def run(cls, f, *args, **kwargs):
		return run_in_thread(cls._app.thread)(f)(*args, **kwargs)
	@classmethod
	def shutdown(cls):
		def dispose():
			from PyQt5.QtCore import QCoreApplication, QEvent
			for widget in cls._app.topLevelWidgets():
				widget.close()
				widget.deleteLater()
			QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
		cls.run(dispose)
	_app = None