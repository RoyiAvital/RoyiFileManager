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

class SearchFileContentIT(QtIT):
	def test_root_follows_invoking_pane_and_fields_align(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import UiOwner
			from fman.url import as_url
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from search_file_content import DEFAULTS, SearchSession
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
			plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFileContent'
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
						host.form.setStyleSheet('QLabel { font-size: 16px; }')
						for width in (640, 960, 1440):
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
						with patch('search_file_content.Runner') as runner:
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
		from search_file_content import DEFAULTS, SearchSession
		from PyQt5.QtWidgets import QWidget
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock
		plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFileContent'
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
		from search_file_content import DEFAULTS, SearchSession
		from PyQt5.QtWidgets import QWidget
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock
		plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFileContent'
		owner = UiOwner(resource_root=str(plugin_root))
		with TemporaryDirectory() as root:
			Path(root, 'report.txt').write_text('first\nneedle here\n', encoding='utf-8')
			def prepare():
				main = MainWindow(Mock(), [], Mock(), Mock(), Mock(), 'null://')
				pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
				from fman.url import as_url
				pane.get_path = lambda: as_url(root)
				pane.on_path_changed = Mock(return_value=lambda: None)
				main.resize(900, 600)
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
	def test_choice_exclusivity_callbacks_and_atomic_updates(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import Choice, TextField, UiOwner, show_panel
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from PyQt5.QtWidgets import QWidget
			from pathlib import Path
			from unittest.mock import Mock
			owner = UiOwner(resource_root=str(Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFileContent'))
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
			root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFileContent'
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
			self.main.setGeometry(70, 60, 640, 400)
			QApplication.processEvents()
		self.run_in_app(place_main)
		window = self.controller.show(self.pane)
		def check_center():
			QApplication.processEvents()
			self.assertEqual(self.main.frameGeometry().center(), window.frameGeometry().center())
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
		self.run_in_app(lambda: self.main.setGeometry(70, 60, 640, 400))
		CalculateFileHash(self.pane)()
		window = self.controller.show(self.pane)
		def check(algorithm, digest):
			QApplication.processEvents()
			self.assertEqual(self.main.frameGeometry().center(), window.frameGeometry().center())
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
			window.resize(800, 600)
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
			self.parent.resize(800, 600)
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