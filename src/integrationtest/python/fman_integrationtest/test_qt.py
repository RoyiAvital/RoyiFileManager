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

import sys

class QtIT(TestCase):
	def run(self, result=None):
		from PyQt5.QtCore import QEventLoop, QMetaObject, QThread, QTimer
		from threading import Thread
		if _QtApp._app is None or QThread.currentThread() != _QtApp._app.thread():
			return super().run(result)
		loop = QEventLoop()
		results = []
		def execute():
			try:
				results.append(super(QtIT, self).run(result))
			finally:
				QMetaObject.invokeMethod(loop, 'quit', Qt.QueuedConnection)
		worker = Thread(target=execute)
		QTimer.singleShot(0, worker.start)
		loop.exec_()
		worker.join()
		return results[0]
	def run_in_app(self, f, *args, **kwargs):
		return _QtApp.run(f, *args, **kwargs)
	def drain_model(self, facade):
		from time import monotonic
		model = self.run_in_app(facade.sourceModel)
		deadline = monotonic() + 5
		while monotonic() < deadline:
			if self.run_in_app(lambda: not model._scanning and not model._dirty and
				model._committed_revision == model._revision and model._displayed is not None):
				return
		self.fail('Snapshot model did not settle')
	def wait_table(self, timeout=5):
		"""Return the newest open QuickTable window; show_quick_table blocks its caller until it closes."""
		from fman.impl.ui.facade import QuickTableWindow
		from time import monotonic, sleep
		deadline = monotonic() + timeout
		while monotonic() < deadline:
			windows = self.run_in_app(lambda: [widget for widget in QApplication.topLevelWidgets()
				if isinstance(widget, QuickTableWindow) and widget.alive.is_set() and widget.isVisible()])
			if windows:
				return windows[-1]
			sleep(.02)
		self.fail('No Table window opened')

class QtHarnessIT(QtIT):
	def test_completion_after_event_loop_exits(self):
		import subprocess
		from textwrap import dedent
		script = '''
from fman_integrationtest.test_qt import QtIT, _QtApp
from PyQt5.QtCore import QEventLoop, QThread
from threading import Event
from unittest import TestResult
from unittest.mock import patch
import faulthandler

faulthandler.dump_traceback_later(10)
loop_returned = Event()
class EarlyExitLoop(QEventLoop):
	def exec_(self):
		result = super().exec_()
		loop_returned.set()
		return result
class CompletedCase(QtIT):
	def runTest(self):
		self.assertIsNot(QThread.currentThread(), _QtApp._app.thread())
		self.run_in_app(lambda: self.assertEqual(
			_QtApp._app.thread(), QThread.currentThread()))
		self.run_in_app(loop.quit)
		self.assertTrue(loop_returned.wait(5))
_QtApp.start()
loop = EarlyExitLoop()
result = TestResult()
with patch('PyQt5.QtCore.QEventLoop', return_value=loop):
	CompletedCase().run(result)
assert result.wasSuccessful(), result.errors + result.failures
assert result.testsRun == 1
_QtApp.shutdown()
'''
		result = subprocess.run(
			[sys.executable, '-X', 'faulthandler', '-c', dedent(script)],
			capture_output=True, text=True, timeout=15)
		self.assertEqual(0, result.returncode, result.stdout + result.stderr)

class SortedFileSystemModelIT(SortedFileSystemModelAT, QtIT):
	pass

class UniformRowHeightsIT(QtIT):
	def test_column_width_batches_measure_once_and_preserve_manual_resize(self):
		from fman.impl.view.resize_cols_to_contents import \
			ResizeColumnsToContents, _get_ideal_column_widths, _resize_column
		from PyQt5.QtCore import QEvent, QPoint
		from PyQt5.QtGui import QMouseEvent, QStandardItemModel
		from PyQt5.QtTest import QTest
		class CountingView(ResizeColumnsToContents):
			def __init__(self):
				self.measurements = 0
				self.batches = []
				super().__init__(None)
			def _get_min_col_widths(self):
				self.measurements += 1
				return super()._get_min_col_widths()
			def _resize_cols_to_contents(self, curr_widths=None):
				before = self.measurements
				super()._resize_cols_to_contents(curr_widths)
				self.batches.append(self.measurements - before)
		def check():
			view = CountingView()
			model = QStandardItemModel(100, 3, view)
			model.setHorizontalHeaderLabels(['Name', 'Size', 'Modified'])
			view.setModel(model)
			notifications = []
			view.horizontalHeader().sectionResized.connect(
				lambda *args: notifications.append(args))
			try:
				view.show()
				QApplication.processEvents()
				for rows, width in ((100, 640), (0, 960), (100, 1280)):
					with self.subTest(rows=rows, width=width):
						model.setRowCount(rows)
						view.batches.clear()
						view.resize(width, 480)
						QApplication.processEvents()
						self.assertTrue(view.batches)
						self.assertEqual([1] * len(view.batches), view.batches)
						self.assertEqual(view._get_num_visible_rows(),
							view.horizontalHeader().resizeContentsPrecision())
						expected = _get_ideal_column_widths(view._get_column_widths(),
							view._get_min_col_widths(), view._get_width_excl_scrollbar())
						view.batches.clear()
						view.resizeColumnsToContents()
						self.assertEqual([1], view.batches)
						self.assertEqual(expected, view._get_column_widths())
				widths = view._get_column_widths()
				requested = widths[1] + 20
				expected = _resize_column(1, requested, widths,
					view._get_min_col_widths(), view._get_width_excl_scrollbar())
				view.measurements = 0
				view.horizontalHeader().resizeSection(1, requested)
				self.assertEqual(1, view.measurements)
				self.assertEqual(expected, view._get_column_widths())
				self.assertTrue(view._handle_col_resize)
				self.assertTrue(notifications)
				widths = view._get_column_widths()
				expected = _resize_column(1, widths[1] + 20, widths,
					view._get_min_col_widths(), view._get_width_excl_scrollbar())
				header = view.horizontalHeader()
				position = QPoint(header.sectionViewportPosition(1) + header.sectionSize(1) - 1,
					header.height() // 2)
				QTest.mousePress(header.viewport(), Qt.LeftButton, pos=position)
				position += QPoint(20, 0)
				QApplication.sendEvent(header.viewport(), QMouseEvent(QEvent.MouseMove,
					position, Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
				QTest.mouseRelease(header.viewport(), Qt.LeftButton, pos=position)
				self.assertEqual(expected, view._get_column_widths())
				self.assertTrue(view._handle_col_resize)
			finally:
				view.close()
				view.deleteLater()
		self.run_in_app(check)

	def test_cramped_column_batches_preserve_clamped_geometry(self):
		from fman.impl.view.resize_cols_to_contents import \
			ResizeColumnsToContents, _get_ideal_column_widths
		from PyQt5.QtGui import QStandardItemModel
		from unittest.mock import patch
		class PreviousView(ResizeColumnsToContents):
			def _apply_column_widths(self, widths):
				for column, width in enumerate(widths):
					self.setColumnWidth(column, width)
		def check():
			views = [PreviousView(None), ResizeColumnsToContents(None)]
			try:
				for view in views:
					model = QStandardItemModel(100, 3, view)
					model.setHorizontalHeaderLabels(['Name', 'Size', 'Modified'])
					for column, text in enumerate(('Long file name for cramped columns.txt',
						'123456789 bytes', '2026-09-25 14:30')):
						model.setData(model.index(0, column), text)
					view.setModel(model)
					view.show()
				QApplication.processEvents()
				for minimum in (-1, 64, 160):
					for width in (180, 240, 480, 960):
						with self.subTest(minimum=minimum, width=width):
							for view in views:
								view.horizontalHeader().setMinimumSectionSize(minimum)
								view.resize(width, 240)
								QApplication.processEvents()
								view._handle_col_resize = False
								try:
									view._apply_column_widths([300, 100, 160])
								finally:
									view._handle_col_resize = True
								section_minimum = view.horizontalHeader().minimumSectionSize()
								expected = [max(section_minimum, size) for size in _get_ideal_column_widths(
									view._get_column_widths(), view._get_min_col_widths(),
									view._get_width_excl_scrollbar())]
								with patch.object(view, '_get_min_col_widths', wraps=view._get_min_col_widths) as measure:
									view.resizeColumnsToContents()
									if view is views[1]:
										measure.assert_called_once()
										self.assertEqual(expected, view._get_column_widths())
								self.assertTrue(view._handle_col_resize)
								self.assertTrue(all(size >= view.horizontalHeader().minimumSectionSize()
									for size in view._get_column_widths()))
								self.assertFalse(view.grab().isNull())
							if QApplication.platformName() == 'windows':
								self.assertEqual(views[0]._get_column_widths(), views[1]._get_column_widths())
			finally:
				for view in views:
					view.close()
					view.deleteLater()
		self.run_in_app(check)

	def test_metadata_updates_do_not_measure_every_row(self):
		from fman.impl.view import FileListView
		from fman.impl.view.uniform_row_heights import DummyModel, UniformRowHeights
		from PyQt5.QtCore import QSize
		class CountingView(UniformRowHeights):
			def __init__(self):
				super().__init__()
				self.row_size_requests = 0
			def sizeHintForRow(self, row):
				self.row_size_requests += 1
				return super().sizeHintForRow(row)
		def check():
			model = DummyModel(200000, 3, QSize(16, 16))
			view = CountingView()
			model.setParent(view)
			view.setModel(model)
			FileListView._init_vertical_header(view)
			try:
				view.resize(640, 480)
				view.show()
				QApplication.processEvents()
				for first, last, column in ((0, 20, 2), (199900, 199920, 2), (0, 0, 0)):
					with self.subTest(first=first, last=last, column=column):
						view.row_size_requests = 0
						model.dataChanged.emit(model.index(first, 0), model.index(last, column), [])
						QApplication.processEvents()
						self.assertLess(view.row_size_requests, 100, 'Metadata update resized the entire directory')
						self.assertEqual(view.get_row_height(), view.rowHeight(0))
						self.assertEqual(view.rowHeight(0), view.rowHeight(model.rowCount() - 1))
				view.scrollTo(model.index(model.rowCount() - 1, 0))
				QApplication.processEvents()
				self.assertIn(model.rowCount() - 1, view.get_visible_row_range())
				self.assertEqual(view.rowAt(0), view.get_visible_row_range().start)
			finally:
				view.close()
				view.deleteLater()
		self.run_in_app(check)

	def test_font_style_and_editor_updates_preserve_row_geometry(self):
		from fman.impl.view import FileListView
		from fman.impl.view.uniform_row_heights import UniformRowHeights
		from PyQt5.QtGui import QFont, QStandardItemModel
		from PyQt5.QtTest import QTest
		from PyQt5.QtWidgets import QLineEdit
		def check():
			view = UniformRowHeights()
			model = QStandardItemModel(200, 3, view)
			view.setModel(model)
			view.setShowGrid(False)
			view.setWordWrap(False)
			FileListView._init_vertical_header(view)
			try:
				view.resize(640, 480)
				view.show()
				QApplication.processEvents()
				original_height = view.rowHeight(0)
				font = QFont(view.font())
				font.setPixelSize(original_height + 12)
				view.setFont(font)
				QApplication.processEvents()
				self.assertGreater(view.rowHeight(0), original_height)
				for style in ('QTableView::item { padding: 6px; }', ''):
					view.setStyleSheet(style)
					QApplication.processEvents()
					expected = max(view._get_cell_heights())
					self.assertEqual(expected, view.rowHeight(0))
					self.assertEqual(expected * model.rowCount(), view.verticalHeader().length())
					view.scrollTo(model.index(model.rowCount() - 1, 0))
					self.assertIn(model.rowCount() - 1, view.get_visible_row_range())
				index = model.index(model.rowCount() - 1, 0)
				model.setData(index, 'before')
				view.edit(index)
				editor = view.findChild(QLineEdit)
				self.assertIsNotNone(editor)
				model.setData(index, 'after')
				self.assertEqual('after', editor.text())
				QTest.keyClick(editor, Qt.Key_Escape)
				model.setRowCount(0)
				view.setFont(QFont())
				model.setRowCount(200)
				QApplication.processEvents()
				self.assertEqual(max(view._get_cell_heights()), view.rowHeight(0))
			finally:
				view.close()
				view.deleteLater()
		self.run_in_app(check)

class WindowsCleanupIT(QtIT):
	def test_clipboard_copy_cut_formats_and_text_preservation(self):
		def check():
			from fman import clipboard
			from PyQt5.QtCore import QMimeData
			from unittest.mock import Mock, patch
			storage = Mock()
			storage.mimeData.return_value = QMimeData()
			storage.text.side_effect = lambda: storage.mimeData.return_value.text()
			storage.setText.side_effect = lambda text: storage.mimeData.return_value.setText(text)
			storage.setMimeData.side_effect = lambda data: setattr(storage.mimeData, 'return_value', data)
			with patch.object(clipboard, '_clipboard', return_value=storage):
				urls = ['file://C:/sample.txt', 'zip://C:/archive.zip/entry.txt']
				clipboard.set_text('preserved name')
				clipboard.copy_files(urls)
				self.assertEqual(urls, clipboard.get_files())
				self.assertFalse(clipboard.files_were_cut())
				clipboard.cut_files(urls)
				self.assertEqual(urls, clipboard.get_files())
				self.assertTrue(clipboard.files_were_cut())
				mime = storage.mimeData()
				for mime_type in (clipboard._CFSTR_PREFERREDDROPEFFECT, clipboard._CF_PREFERREDDROPEFFECT):
					self.assertEqual(clipboard._DROPEFFECT_MOVE, bytes(mime.data(mime_type)))
				clipboard.copy_files(urls)
				self.assertFalse(clipboard.files_were_cut())
				self.assertEqual('preserved name', clipboard.get_text())
		self.run_in_app(check)

	def test_windows_drag_actions_and_move_acknowledgment(self):
		def check():
			from fman.impl.view.drag_and_drop import DragAndDrop
			from PyQt5.QtWidgets import QTableView
			from unittest.mock import Mock, patch
			view = DragAndDrop()
			try:
				for modifiers, action in ((Qt.NoModifier, Qt.MoveAction), (Qt.ControlModifier, Qt.CopyAction), (Qt.AltModifier, Qt.MoveAction)):
					event = Mock()
					event.keyboardModifiers.return_value = modifiers
					with patch.object(QTableView, 'dropEvent') as dispatch:
						view.dropEvent(event)
						dispatch.assert_called_once_with(event)
					event.setDropAction.assert_called_once_with(action)
					self.assertEqual(action == Qt.MoveAction, event.ignore.called)
			finally:
				view.deleteLater()
		self.run_in_app(check)

	def test_native_prompts_and_shortcut_choices(self):
		def check():
			from fman import OK
			from fman.impl.nonexistent_shortcut_handler import NonexistentShortcutDialog, NonexistentShortcutHandler
			from fman.impl.tour_state import TourState
			from fman.impl.widgets import MainWindow, Prompt
			from PyQt5.QtCore import QTimer
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QDialog, QLineEdit
			from unittest.mock import Mock
			window = MainWindow(QApplication.instance(), Mock(), Mock(), Mock(), 'null://')
			state = TourState()
			class Settings(dict):
				def flush(self):
					self.flushed = True
			settings = Settings()
			handler = NonexistentShortcutHandler(window, settings, state)
			def answer(dialog):
				def choose():
					if isinstance(dialog, NonexistentShortcutDialog):
						self.assertEqual(['first', 'second'], [value for value, _ in dialog._options])
						self.assertEqual([], dialog.findChildren(QLineEdit))
						dialog._radio_buttons[1].setFocus()
						QTest.keyClick(dialog._radio_buttons[1], Qt.Key_Space)
						dialog._dont_ask_again.setChecked(True)
						dialog.accept()
					elif isinstance(dialog, Prompt):
						dialog.setTextValue('renamed')
						dialog.accept()
					else:
						dialog.done(OK)
				QTimer.singleShot(0, choose)
			window.before_dialog.connect(answer)
			try:
				self.assertEqual(('renamed', True), window.show_prompt('Rename', 'sample'))
				self.assertEqual(OK, window.show_alert('Windows message'))
				state.finished('completed')
				self.assertEqual('second', handler._show_suggestions('probe', 'Choose', [('first', 'First'), ('second', 'Second')]))
				self.assertEqual({'suppress': True}, settings['probe'])
				self.assertTrue(settings.flushed)
				self.assertEqual((None, 0), state.take())
				window.before_dialog.disconnect(answer)
				window.before_dialog.connect(lambda dialog: QTimer.singleShot(0, dialog.reject))
				self.assertEqual(('', False), window.show_prompt('Cancel', 'sample'))
				self.assertIsNone(handler._show_suggestions('canceled', 'Choose', [('first', 'First')]))
				self.assertNotIn('canceled', settings)
			finally:
				window.close()
				window.deleteLater()
		self.run_in_app(check)


class MainWindowIT(QtIT):
	def test_forced_minimum_size(self):
		from fman.impl.widgets import MainWindow
		from PyQt5.QtCore import QSize
		from unittest.mock import Mock
		def check():
			window = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
			try:
				self.assertEqual(QSize(960, 600), window.minimumSize())
				for width, height in ((960, 600), (1280, 800), (1440, 900)):
					window.resize(width, height)
					self.assertEqual(QSize(width, height), window.size())
			finally:
				window.close()
				window.deleteLater()
		self.run_in_app(check)

	def test_geometry_reset_survives_saved_session_restart(self):
		from fman.impl.session import SessionManager, _encode
		from fman.impl.util.settings import Settings
		from fman.impl.widgets import MainWindow
		from pathlib import Path
		from PyQt5.QtCore import QSize
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		def check():
			for maximized in (False, True):
				with self.subTest(maximized=maximized), TemporaryDirectory() as directory:
					path = Path(directory, 'Session.json')
					settings = Settings(path)
					pane = Mock()
					pane.get_location.return_value = 'file://C:/Work'
					pane.get_default_column_widths.return_value = [600, 200, 200]
					pane.get_column_widths_by_name.return_value = {'core.Name': 600}
					window = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
					restarted = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
					window._panes = [pane]
					restarted._panes = [pane]
					try:
						window.resize(1100, 700)
						window.move(220, 150)
						window.showMaximized() if maximized else window.show()
						QApplication.processEvents()
						settings['window_geometry'] = _encode(bytes(window.saveGeometry()))
						settings['window_state'] = _encode(bytes(window.saveState(1)))
						manager = SessionManager(settings, None, Mock(), 'test', True)
						window.closed.connect(lambda: manager.on_close(window))
						public_window = Mock()
						public_window.reset_geometry.side_effect = window.reset_geometry

						manager.reset_window_geometry(public_window)
						QApplication.processEvents()
						self.assertFalse(window.isMaximized())
						self.assertEqual(QSize(1280, 800), window.size())
						window.close()
						reloaded = Settings(path)
						self.assertIsNone(reloaded.get('window_geometry', None))
						self.assertIsNone(reloaded.get('window_state', None))
						self.assertEqual('file://C:/Work', reloaded.get('panes', [])[0]['location'])

						fresh_manager = SessionManager(reloaded, None, Mock(), 'test', True)
						public_window._widget = restarted
						with patch('fman.impl.session.Thread'), \
								patch.object(restarted, 'restoreGeometry', wraps=restarted.restoreGeometry) as restore:
							fresh_manager.show_main_window(public_window)
							restore.assert_not_called()
						QApplication.processEvents()
						self.assertEqual(QSize(1280, 800), restarted.size())
						self.assertFalse(restarted.isMaximized() or restarted.isMinimized())
						restarted.move(123, 91)
						expected = _encode(bytes(restarted.saveGeometry()))
						restarted.closed.connect(lambda: fresh_manager.on_close(restarted))
						restarted.close()
						self.assertEqual(expected, Settings(path).get('window_geometry', None))
					finally:
						window.close()
						restarted.close()
						window.deleteLater()
						restarted.deleteLater()
		self.run_in_app(check)

class QuickViewIT(QtIT):
	def setUp(self):
		FilterBarIT.setUp(self)

	def close_window(self):
		FilterBarIT.close_window(self)

	def navigate(self, *args):
		return FilterBarIT.navigate(self, *args)

	def drain(self, *args):
		return FilterBarIT.drain(self, *args)

	def test_overlay_preserves_panes_and_focus(self):
		from fman.impl.quick_view import QuickViewOverlay
		from PyQt5.QtTest import QTest
		def check():
			source, target = self.panes
			original = (target.layout(), target._model, target._file_view.parent(), target.focusProxy(), self.window.minimumSize(), self.window._splitter.count())
			overlay = QuickViewOverlay(self.window, source, target)
			try:
				self.assertIs(overlay.parentWidget(), self.window.centralWidget())
				self.assertFalse(target.isAncestorOf(overlay))
				for key, modifiers in ((Qt.Key_Tab, Qt.NoModifier), (Qt.Key_Backtab, Qt.ShiftModifier), (Qt.Key_Escape, Qt.NoModifier)):
					overlay.focus_canvas()
					self.assertTrue(overlay.canvas.hasFocus())
					QTest.keyClick(overlay.canvas, key, modifiers)
					self.assertTrue(source.hasFocus())
					self.assertTrue(overlay.isVisible())
				overlay.focus_canvas()
				QTest.keyClick(overlay.canvas, Qt.Key_Down, Qt.ShiftModifier)
				self.assertTrue(overlay.canvas.hasFocus())
				self.controller.handle_shortcut.reset_mock()
				QTest.keyClick(overlay.canvas, Qt.Key_F8)
				self.controller.handle_shortcut.assert_called_once()
				self.assertTrue(source.hasFocus())
				self.assertEqual(original, (target.layout(), target._model, target._file_view.parent(), target.focusProxy(), self.window.minimumSize(), self.window._splitter.count()))
				target.setFocus()
				QTest.mouseClick(overlay.canvas.viewport(), Qt.LeftButton)
				self.assertTrue(overlay.canvas.hasFocus())
				self.assertIs(source, self.window._active_pane)
			finally:
				overlay.dispose()
		self.run_in_app(check)

	def test_overlay_follows_panel_and_splitter(self):
		from fman.impl.quick_view import QuickViewOverlay
		from PyQt5.QtCore import QPoint, QRect
		from PyQt5.QtWidgets import QFrame
		def check():
			source, target = self.panes
			overlay = QuickViewOverlay(self.window, source, target)
			panel = QFrame(self.window.centralWidget())
			panel.setFixedHeight(90)
			try:
				self.window._central_layout.addWidget(panel)
				panel.show()
				QApplication.processEvents()
				self.assertEqual(QRect(target.mapTo(overlay.parentWidget(), QPoint()), target.size()), overlay.geometry())
				panel.hide()
				QApplication.processEvents()
				before = target.pos()
				self.window._splitter.move(self.window._splitter.pos() + QPoint(0, 7))
				self.assertEqual(before, target.pos())
				self.assertEqual(QRect(target.mapTo(overlay.parentWidget(), QPoint()), target.size()), overlay.geometry())
				self.window._splitter.moveSplitter(390, 1)
				self.assertEqual(QRect(target.mapTo(overlay.parentWidget(), QPoint()), target.size()), overlay.geometry())
			finally:
				overlay.dispose()
				self.window._central_layout.removeWidget(panel)
				panel.deleteLater()
		self.run_in_app(check)


class QuickViewPdfIT(QtIT):
	setUp = QuickViewIT.setUp
	close_window = QuickViewIT.close_window
	navigate = QuickViewIT.navigate
	drain = QuickViewIT.drain

	def until(self, predicate):
		from PyQt5.QtCore import QEventLoop, QTimer
		loop = QEventLoop()
		poll = QTimer(loop)
		poll.timeout.connect(lambda: loop.quit() if predicate() else None)
		deadline = QTimer(loop)
		deadline.setSingleShot(True)
		deadline.timeout.connect(loop.quit)
		poll.start(5)
		deadline.start(5000)
		try:
			if not predicate():
				loop.exec_()
		finally:
			poll.stop()
			deadline.stop()
		self.assertTrue(predicate(), 'PDF preview did not settle')

	def start_session(self, session_type=None):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_images import load_preview
		from unittest.mock import patch
		def load(request, canceled):
			return load_preview(request, canceled, self.filesystem.resolve)
		with patch('fman.load_json', return_value={}):
			return (session_type or QuickViewSession)(self.window, *self.panes, load=load)

	def fake_controller(self, mode):
		from fman.impl.quick_view_pdf import PdfController
		script = '''
from _quick_view_pdf_worker import encode_frame, read_command
from threading import Event
import sys
output = sys.stdout.buffer
output.write(encode_frame({'type': 'ready'}))
output.flush()
request = read_command(sys.stdin.buffer)
if sys.argv[1] == 'error':
	response = dict(request, type='error', stage='open', message='Fixture rejected PDF')
else:
	response = dict(request, type='document', sizes=[[200, 400], [200, 400]], fingerprint=[1, 2, 3, 4])
output.write(encode_frame(response))
output.flush()
Event().wait()
'''
		controller = PdfController(self.window, command=[sys.executable, '-B', '-c', script, mode])
		self.window._quick_view_pdf_controller = controller
		return controller

	def test_pdf_session_render_switch_focus_and_reopen(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.url import as_url
		from fman_unittest.test_quick_view_pdf import pdf_bytes
		from PyQt5.QtCore import QPoint, QRect, QThread
		from PyQt5.QtTest import QTest
		pdf = self.root / 'preview.pdf'
		pdf.write_bytes(pdf_bytes())
		text = self.root / 'preview.txt'
		text.write_text('PDF switching fixture', encoding='utf-8')
		image = QuickViewImagesIT.make_image(self, 'preview.png', 8, 8)
		self.panes[0].reload()
		self.drain(self.panes[0])
		self.panes[0].place_cursor_at(as_url(pdf))
		def check():
			kinds, threads = [], []
			class RecordingSession(QuickViewSession):
				def show_result(self, result):
					kinds.append(result.kind)
					threads.append(QThread.currentThread())
					super().show_result(result)
				def _pdf_page(self, *args):
					threads.append(QThread.currentThread())
					super()._pdf_page(*args)
			session = self.start_session(RecordingSession)
			controller = None
			try:
				self.until(lambda: session.overlay.pdf_view is not None and bool(session.overlay.pdf_view.canvas.cache))
				controller = session._pdf_controller
				view = session.overlay.pdf_view
				canvas = view.canvas
				self.assertEqual([(200, 200), (300, 150)], [tuple(size) for size in canvas.sizes])
				pixels = next(pixels for key, pixels in canvas.cache.items() if key[0] == 0)
				self.assertEqual('#ff0000', pixels.pixelColor(pixels.width() // 2, pixels.height() // 2).name())
				self.assertIs(session.overlay.content.currentWidget(), view)
				self.assertFalse(session.overlay.buttons['copy_image'].isVisible())
				session.overlay.focus_canvas()
				QTest.keyClick(canvas, Qt.Key_W)
				self.assertEqual('fit_width', canvas.mode)
				for key, modifiers in ((Qt.Key_Tab, Qt.NoModifier), (Qt.Key_Backtab, Qt.ShiftModifier), (Qt.Key_Escape, Qt.NoModifier)):
					session.overlay.focus_canvas()
					QTest.keyClick(canvas, key, modifiers)
					self.assertTrue(session.source.hasFocus())
				self.controller.handle_shortcut.reset_mock()
				session.overlay.focus_canvas()
				QTest.keyClick(canvas, Qt.Key_F9)
				self.controller.handle_shortcut.assert_called_once()
				self.window._splitter.moveSplitter(390, 1)
				QApplication.processEvents()
				target = self.panes[1]
				self.assertEqual(QRect(target.mapTo(session.overlay.parentWidget(), QPoint()), target.size()), session.overlay.geometry())
				session.source.place_cursor_at(as_url(text))
				self.until(lambda: kinds == ['pdf', 'text'])
				self.assertIs(session.overlay.content.currentWidget(), session.overlay.text_view)
				self.assertEqual('PDF switching fixture', session.overlay.text_view.browser.toPlainText())
				self.assertFalse(canvas.cache)
				self.until(lambda: controller.process is None)
				session.source.place_cursor_at(as_url(image))
				self.until(lambda: kinds == ['pdf', 'text', 'image'])
				self.assertIs(session.overlay.content.currentWidget(), session.overlay.canvas)
				self.assertTrue(session.overlay.buttons['copy_image'].isVisible())
				session.source.place_cursor_at(as_url(pdf))
				self.until(lambda: bool(canvas.cache))
				self.assertEqual(['pdf', 'text', 'image', 'pdf'], kinds)
				self.assertEqual('fit_page', canvas.mode)
				self.assertEqual(0, canvas.current_page)
				self.assertIs(session._pdf_controller, controller)
				session.close()
				self.assertFalse(session._connections)
				session = self.start_session(RecordingSession)
				self.until(lambda: session.overlay.pdf_view is not None and bool(session.overlay.pdf_view.canvas.cache))
				self.assertIs(session._pdf_controller, controller)
				self.assertTrue(all(thread == QApplication.instance().thread() for thread in threads))
			finally:
				session.shutdown()
				if controller is not None:
					self.until(lambda: controller.process is None)
		self.run_in_app(check)

	def test_helper_errors_and_render_timeouts_stay_inline(self):
		from fman.url import as_url
		from unittest.mock import patch
		self.panes[0].place_cursor_at(as_url(self.root / 'Annual Report.pdf'))
		for mode, message in (('error', 'Fixture rejected PDF'), ('render', 'timed out')):
			with self.subTest(mode=mode):
				def check():
					controller = self.fake_controller(mode)
					errors = []
					controller.failed.connect(lambda *args: errors.append(args))
					with patch('fman.impl.quick_view_pdf.RENDER_TIMEOUT', 100):
						session = self.start_session()
						try:
							self.until(lambda: session.overlay.pdf_view is not None and
								message in session.overlay.pdf_view.canvas.message and controller.process is None)
							view = session.overlay.pdf_view
							self.assertIs(session.overlay.content.currentWidget(), view)
							self.assertFalse(view.canvas.sizes)
							self.assertFalse(view.canvas.cache)
							self.assertFalse(session.overlay.buttons['copy_image'].isVisible())
							self.assertEqual(1, len(errors))
							self.assertFalse(controller.deadline.isActive())
							self.assertFalse(controller.drain.isActive())
						finally:
							session.shutdown()
							controller.shutdown()
							self.until(lambda: controller.process is None)
							self.window._quick_view_pdf_controller = None
				self.run_in_app(check)

	def test_active_close_reopen_and_shutdown_disconnect_results(self):
		from fman.url import as_url
		self.panes[0].place_cursor_at(as_url(self.root / 'Annual Report.pdf'))
		def check():
			controller = self.fake_controller('render')
			session = self.start_session()
			def rendering():
				return controller._active is not None and controller._active['type'] == 'render'
			try:
				self.until(rendering)
				generation = session.generation
				session.close()
				self.assertFalse(session._connections)
				self.assertIsNone(self.window._quick_view_session)
				for signal in (controller.document_ready, controller.page_ready, controller.page_failed, controller.failed):
					self.assertEqual(0, controller.receivers(signal))
				controller.document_ready.emit(generation, [(1, 1)], (1, 2, 3, 4))
				controller.page_ready.emit(generation, 0, {}, None)
				controller.failed.emit(generation, 'Late closed-session failure')
				session = self.start_session()
				self.until(lambda: session._pdf_controller is controller and rendering())
				canvas = session.overlay.pdf_view.canvas
				sizes = list(canvas.sizes)
				controller.document_ready.emit(session.generation - 1, [(1, 1)], (1, 2, 3, 4))
				controller.page_ready.emit(session.generation - 1, canvas.revision, {}, None)
				controller.page_failed.emit(session.generation - 1, 0, 'Stale page error')
				controller.failed.emit(session.generation - 1, 'Stale document failure')
				self.assertEqual(sizes, list(canvas.sizes))
				self.assertFalse(canvas.errors)
				self.assertFalse(canvas.cache)
				session.shutdown()
				self.assertTrue(session.bridge.closed)
				self.assertFalse(session._connections)
				self.until(lambda: controller.process is None)
				self.assertIsNone(controller.job)
				self.assertFalse(controller.deadline.isActive())
				self.assertFalse(controller.drain.isActive())
			finally:
				session.shutdown()
				controller.shutdown()
				self.until(lambda: controller.process is None)
		self.run_in_app(check)


class QuickViewTextIT(QtIT):
	setUp = QuickViewIT.setUp
	close_window = QuickViewIT.close_window
	navigate = QuickViewIT.navigate
	drain = QuickViewIT.drain

	def test_find_modified_editing_keys_forward_to_source(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_text import TextContent, convert_text
		from PyQt5.QtGui import QTextCursor
		from PyQt5.QtTest import QTest
		from unittest.mock import patch
		def check():
			with patch('fman.load_json', return_value={}):
				session = QuickViewSession(self.window, *self.panes)
				session.timer.stop()
			try:
				content = TextContent('hello one hello two', 'sample.txt', 'utf-8', (), 19)
				session.show_result(convert_text(content))
				view = session.overlay.text_view
				forwarded = []
				def forward(source, event):
					forwarded.append((source, event.key(), int(event.modifiers())))
				cases = [(key, modifiers) for key in (Qt.Key_Return, Qt.Key_Enter)
					for modifiers in (Qt.AltModifier, Qt.AltModifier | Qt.ShiftModifier,
						Qt.ControlModifier, Qt.ControlModifier | Qt.ShiftModifier,
						Qt.MetaModifier, Qt.MetaModifier | Qt.ShiftModifier)]
				cases += [(key, modifiers) for key in (Qt.Key_Backspace, Qt.Key_Delete)
					for modifiers in (Qt.AltModifier, Qt.MetaModifier)]
				cases.append((Qt.Key_Enter, Qt.AltModifier | Qt.KeypadModifier))
				with patch.object(self.controller, 'handle_shortcut', side_effect=forward):
					for key, modifiers in cases:
						with self.subTest(key=key, modifiers=int(modifiers)):
							forwarded.clear()
							view.browser.moveCursor(QTextCursor.Start)
							view.find_bar.show()
							view.find_input.setText('hello')
							view.find_input.setFocus()
							QTest.keyClick(view.find_input, key, modifiers)
							self.assertEqual([(session.source, key, int(modifiers))], forwarded)
							self.assertTrue(session.source.hasFocus())
							self.assertEqual('hello', view.find_input.text())
							self.assertFalse(view.browser.textCursor().hasSelection())
			finally:
				session.close()
		self.run_in_app(check)

	def test_find_supported_editing_keys_stay_local(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_text import TextContent, convert_text
		from PyQt5.QtGui import QTextCursor
		from PyQt5.QtTest import QTest
		from unittest.mock import patch
		def check():
			with patch('fman.load_json', return_value={}):
				session = QuickViewSession(self.window, *self.panes)
				session.timer.stop()
			try:
				content = TextContent('hello one hello two', 'sample.txt', 'utf-8', (), 19)
				session.show_result(convert_text(content))
				view = session.overlay.text_view
				self.controller.handle_shortcut.reset_mock()
				for key in (Qt.Key_Return, Qt.Key_Enter):
					for modifiers in (Qt.NoModifier, Qt.ShiftModifier, Qt.KeypadModifier,
						Qt.ShiftModifier | Qt.KeypadModifier):
						with self.subTest(key=key, modifiers=int(modifiers)):
							view.browser.moveCursor(QTextCursor.Start)
							view.find_bar.show()
							view.find_input.setText('hello')
							view.find_input.setFocus()
							for expected in (0, 10):
								QTest.keyClick(view.find_input, key, modifiers)
								self.assertEqual('hello', view.browser.textCursor().selectedText())
								self.assertEqual(expected, view.browser.textCursor().selectionStart())
								self.assertTrue(view.find_input.hasFocus())
							QTest.keyClick(view.find_input, Qt.Key_F3, Qt.ShiftModifier)
							self.assertEqual(0, view.browser.textCursor().selectionStart())
				for key, modifiers, position, expected in (
					(Qt.Key_Backspace, Qt.NoModifier, 11, 'hello worl'),
					(Qt.Key_Backspace, Qt.ShiftModifier, 11, 'hello worl'),
					(Qt.Key_Backspace, Qt.ControlModifier, 11, 'hello '),
					(Qt.Key_Delete, Qt.NoModifier, 0, 'ello world'),
					(Qt.Key_Delete, Qt.ControlModifier, 0, 'world'),
				):
					with self.subTest(key=key, modifiers=int(modifiers)):
						view.find_input.setText('hello world')
						view.find_input.setCursorPosition(position)
						QTest.keyClick(view.find_input, key, modifiers)
						self.assertEqual(expected, view.find_input.text())
						self.assertTrue(view.find_input.hasFocus())
				self.controller.handle_shortcut.assert_not_called()
			finally:
				session.close()
		self.run_in_app(check)

	def test_rendering_modes_local_keys_and_source_forwarding(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_text import TextContent, convert_text
		from PyQt5.QtTest import QTest
		from unittest.mock import patch
		def check():
			with patch('fman.load_json', return_value={}):
				session = QuickViewSession(self.window, *self.panes)
				session.timer.stop()
			try:
				self.assertIsNone(session.overlay.text_view)
				content = TextContent('def example():\n    return "hello"\n# hello', 'sample.py', 'utf-8', (), 55)
				session.show_result(convert_text(content, colors=session._text_colors()))
				view = session.overlay.text_view
				browser = view.browser
				self.assertIn('def example()', browser.toPlainText())
				self.assertFalse(browser.document().find('def').charFormat().foreground().style() == Qt.NoBrush)
				self.assertFalse(session.overlay.buttons['copy_image'].isVisible())
				session.overlay.focus_canvas()
				self.assertTrue(browser.hasFocus())
				self.controller.handle_shortcut.reset_mock()
				QTest.keyClick(browser, Qt.Key_A, Qt.ControlModifier)
				self.assertIn('def example()', browser.textCursor().selectedText())
				QTest.keyClick(browser, Qt.Key_C, Qt.ControlModifier)
				self.assertIn('def example()', QApplication.clipboard().text())
				QTest.keyClick(browser, Qt.Key_F, Qt.ControlModifier)
				self.assertTrue(view.find_input.hasFocus())
				QTest.keyClicks(view.find_input, 'hello')
				QTest.keyClick(view.find_input, Qt.Key_Return)
				self.assertEqual('hello', browser.textCursor().selectedText())
				QTest.keyClick(view.find_input, Qt.Key_F3)
				QTest.keyClick(view.find_input, Qt.Key_F3, Qt.ShiftModifier)
				self.controller.handle_shortcut.assert_not_called()
				QTest.keyClick(view.find_input, Qt.Key_Escape)
				self.assertTrue(browser.hasFocus())
				self.assertFalse(view.find_bar.isVisible())
				QTest.keyClick(browser, Qt.Key_F8)
				self.controller.handle_shortcut.assert_called_once()
				self.assertTrue(session.source.hasFocus())
				self.controller.handle_shortcut.reset_mock()
				view.find_bar.show()
				view.find_input.setFocus()
				QTest.keyClick(view.find_input, Qt.Key_Q, Qt.ControlModifier)
				self.controller.handle_shortcut.assert_called_once()
				self.assertTrue(session.source.hasFocus())
				view.close_find()
				for key, modifiers in ((Qt.Key_Tab, Qt.NoModifier), (Qt.Key_Backtab, Qt.ShiftModifier), (Qt.Key_Escape, Qt.NoModifier)):
					session.overlay.focus_canvas()
					QTest.keyClick(browser, key, modifiers)
					self.assertTrue(session.source.hasFocus())
				self.assertFalse(browser.grab().isNull())
			finally:
				session.close()
		self.run_in_app(check)

	def test_resources_are_denied_and_plain_text_stays_literal(self):
		from fman.impl.quick_view_text import TextPreview, TextContent, convert_text
		from PyQt5.QtCore import QByteArray, QUrl
		from PyQt5.QtGui import QTextDocument
		from unittest.mock import patch
		def check():
			view = TextPreview(self.panes[0], self.window)
			try:
				content = TextContent('# <tag> *literal*\n    indented', 'sample.txt', 'utf-8', (), 32)
				with patch.object(view.browser, 'setHtml', side_effect=AssertionError('Plain text must not parse HTML')):
					view.show_result(convert_text(content))
				self.assertEqual(content.text, view.browser.toPlainText())
				for url in ('https://example.invalid/image.png', 'file:///must-not-read', 'relative.png', 'data:image/png,abc', '//server/share/image.png'):
					self.assertEqual(QByteArray(), view.browser.loadResource(QTextDocument.ImageResource, QUrl(url)))
					self.assertEqual(QByteArray(), view.browser.document().loadResource(QTextDocument.ImageResource, QUrl(url)))
				view.browser.setHtml('<img src="file:///must-not-read"><img src="https://example.invalid/image.png">')
				image = QuickViewImagesIT.make_image(self, 'blocked.png', 3, 3)
				url = QUrl.fromLocalFile(str(image))
				self.assertEqual(QByteArray(), view.browser.document().resource(QTextDocument.ImageResource, url))
				self.assertFalse(view.browser.openLinks())
				self.assertFalse(view.browser.openExternalLinks())
			finally:
				view.deleteLater()
		self.run_in_app(check)


	def test_limited_markdown_disables_rendered_until_eligible_content(self):
		from dataclasses import replace
		from fman.impl.quick_view_text import TextPreview, TextContent, FORMAT_LIMIT, convert_text
		from unittest.mock import Mock
		def check():
			view = TextPreview(self.panes[0], self.window)
			requested = Mock()
			view.mode_requested.connect(requested)
			try:
				content = TextContent('# Heading', 'sample.md', 'utf-8', (), 9)
				for limited, warning in ((replace(content, truncated=True), 'truncated'),
					(replace(content, byte_count=FORMAT_LIMIT + 1), '512 KiB')):
					for mode in ('rendered', 'source'):
						view.show_result(convert_text(limited, mode))
						self.assertFalse(view.mode_buttons['rendered'].isEnabled())
						self.assertTrue(view.mode_buttons['source'].isEnabled())
						self.assertTrue(view.mode_buttons['source'].isChecked())
						self.assertIn(warning, view.metadata.text())
						view.mode_buttons['rendered'].click()
						requested.assert_not_called()
				view.show_result(convert_text(replace(content, byte_count=FORMAT_LIMIT), 'source'))
				self.assertTrue(view.mode_buttons['rendered'].isEnabled())
				view.mode_buttons['rendered'].click()
				requested.assert_called_once_with('rendered')
			finally:
				view.deleteLater()
		self.run_in_app(check)

	def test_plain_source_and_code_use_four_space_tabs(self):
		from fman.impl.quick_view_text import TextPreview, TextContent, convert_text
		from PyQt5.QtGui import QFontMetricsF, QTextCursor
		def check():
			view = TextPreview(self.panes[0], self.window)
			view.resize(450, 300)
			view.show()
			try:
				for path, mode in (('sample.txt', 'rendered'), ('sample.md', 'source'),
					('sample.py', 'source'), ('sample.py', 'rendered')):
					with self.subTest(path=path, mode=mode):
						content = TextContent('\tvalue = 42', path, 'utf-8', (), 11)
						result = convert_text(content, mode)
						view.show_result(result)
						browser = view.browser
						expected = QFontMetricsF(browser.document().defaultFont()).horizontalAdvance('    ')
						self.assertAlmostEqual(expected, browser.tabStopDistance())
						cursor = QTextCursor(browser.document())
						start = browser.cursorRect(cursor).left()
						cursor.setPosition(4 if result.html else 1)
						self.assertAlmostEqual(expected, browser.cursorRect(cursor).left() - start, delta=1)
			finally:
				view.deleteLater()
		self.run_in_app(check)

	def test_worker_delivery_modes_reuse_source_and_clear_for_images(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_images import load_preview
		from fman.url import as_url
		from PyQt5.QtCore import QThread
		from unittest.mock import patch
		markdown = self.root / 'preview.md'
		markdown.write_text('# Heading\n\nA **bold** word.', encoding='utf-8')
		image = QuickViewImagesIT.make_image(self, 'preview.png', 8, 8)
		for source in self.panes:
			source.reload()
			self.drain(source)
			source.place_cursor_at(as_url(markdown))
		for panes in (self.panes, list(reversed(self.panes))):
			with self.subTest(source=panes[0]):
				ready = Event()
				loads = []
				class RecordingSession(QuickViewSession):
					def show_result(self, result):
						super().show_result(result)
						ready.set()
				def load(request, canceled):
					self.assertIsNot(QThread.currentThread(), QApplication.instance().thread())
					self.assertTrue(all(isinstance(color, str) for color in request.colors))
					loads.append(request)
					return load_preview(request, canceled, self.filesystem.resolve)
				with patch('fman.load_json', return_value={}):
					session = self.run_in_app(RecordingSession, self.window, *panes, load=load)
				try:
					self.assertTrue(ready.wait(5), 'Text result did not reach Qt')
					view = session.overlay.text_view
					self.assertEqual('Heading\nA bold word.', self.run_in_app(view.browser.toPlainText))
					content = session._text_content
					for mode in ('source', 'rendered'):
						ready.clear()
						with patch('fman.impl.quick_view_text.load_text', side_effect=AssertionError('Mode switch reread file')):
							self.run_in_app(session.text_mode, mode)
							self.assertTrue(ready.wait(5))
						self.assertIs(content, session._text_content)
						self.assertIs(view, session.overlay.text_view)
						self.assertEqual(mode == 'source', self.run_in_app(view.browser.toPlainText).startswith('#'))
					self.assertEqual(3, len(loads))
					self.assertIsNone(loads[0].content)
					self.assertIs(content, loads[1].content)
					ready.clear()
					panes[0].place_cursor_at(as_url(image))
					self.assertEqual('', self.run_in_app(view.browser.toPlainText))
					self.assertTrue(ready.wait(5))
					self.assertIsNone(session._text_content)
					self.assertIsNotNone(session.overlay.canvas.image)
					self.assertTrue(self.run_in_app(session.overlay.buttons['copy_image'].isVisible))
				finally:
					session.shutdown()

	def test_stale_conversion_after_cursor_change_cannot_restore_text(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_images import load_preview
		from fman.url import as_url
		from unittest.mock import patch
		path = self.root / 'preview.md'
		path.write_text('# Original', encoding='utf-8')
		image = QuickViewImagesIT.make_image(self, 'next.png', 8, 8)
		self.panes[0].reload()
		self.drain(self.panes[0])
		self.panes[0].place_cursor_at(as_url(path))
		ready, started, release = Event(), Event(), Event()
		self.addCleanup(release.set)
		results = []
		class RecordingSession(QuickViewSession):
			def show_result(self, result):
				results.append(result.kind)
				super().show_result(result)
				ready.set()
		def load(request, canceled):
			if request.content is not None:
				started.set()
				release.wait(5)
			return load_preview(request, canceled, self.filesystem.resolve)
		with patch('fman.load_json', return_value={}):
			session = self.run_in_app(RecordingSession, self.window, *self.panes, load=load)
		self.addCleanup(session.shutdown)
		self.assertTrue(ready.wait(5))
		ready.clear()
		self.run_in_app(session.text_mode, 'source')
		self.assertTrue(started.wait(5))
		worker = session.bridge.loader._thread
		self.panes[0].place_cursor_at(as_url(image))
		self.assertIs(worker, session.bridge.loader._thread)
		self.assertEqual('', self.run_in_app(session.overlay.text_view.browser.toPlainText))
		release.set()
		self.assertTrue(ready.wait(5))
		self.assertEqual(['text', 'image'], results)
		self.assertIsNone(session._text_content)


class QuickViewImagesIT(QtIT):
	setUp = QuickViewIT.setUp
	close_window = QuickViewIT.close_window
	navigate = QuickViewIT.navigate
	drain = QuickViewIT.drain

	def test_copy_image_uses_loaded_frame_and_preserves_focus(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_images import ImageResult
		from PyQt5.QtCore import QMimeData, QThread
		from PyQt5.QtGui import QColor, QImage
		from PyQt5.QtTest import QTest
		from unittest.mock import Mock, patch
		def check():
			clipboard = Mock()
			payload = QMimeData()
			def copy_image(image):
				self.assertEqual(QApplication.instance().thread(), QThread.currentThread())
				payload.setImageData(image)
			clipboard.setImage.side_effect = copy_image
			with patch('fman.load_json', return_value={}), patch('fman.impl.quick_view.QApplication.clipboard', return_value=clipboard) as access:
				session = QuickViewSession(self.window, *self.panes)
				session.timer.stop()
				try:
					canvas = session.overlay.canvas
					button = session.overlay.buttons['copy_image']
					self.assertFalse(button.isEnabled())
					button.click()
					session.image_action('copy_image')
					access.assert_not_called()
					image = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
					image.fill(QColor('#80402010'))
					session.show_result(ImageResult(image, format='png'))
					canvas.zoom(-4)
					self.assertNotEqual(1, canvas.scale)
					self.assertTrue(button.isEnabled())
					for focus in (session.source, canvas):
						focus.setFocus()
						QTest.mouseClick(button, Qt.LeftButton)
						self.assertTrue(focus.hasFocus())
						self.assertIs(image, clipboard.setImage.call_args.args[0])
					self.assertEqual(2, clipboard.setImage.call_count)
					self.assertEqual(image, payload.imageData())
					self.assertEqual(128, payload.imageData().pixelColor(0, 0).alpha())
					self.controller.handle_shortcut.reset_mock()
					QTest.keyClick(canvas, Qt.Key_C, Qt.ControlModifier)
					self.controller.handle_shortcut.assert_called_once()
					self.assertEqual(2, clipboard.setImage.call_count)
					for message in ('Loading', 'Cannot decode image', 'No file selected'):
						session._clear(message)
						self.assertFalse(button.isEnabled())
						button.click()
						session.image_action('copy_image')
					self.assertEqual(2, clipboard.setImage.call_count)
					replacement = QImage(4, 3, QImage.Format_RGB32)
					replacement.fill(Qt.blue)
					session.show_result(ImageResult(replacement, format='png'))
					self.assertEqual(image, payload.imageData())
				finally:
					session.close()
				self.assertEqual(image, payload.imageData())
		self.run_in_app(check)

	def make_image(self, name='image.png', width=600, height=400, color='red', image_format='PNG'):
		from PyQt5.QtGui import QColor, QImage
		path = self.root / name
		image = QImage(width, height, QImage.Format_ARGB32)
		image.fill(QColor(color))
		self.assertTrue(image.save(str(path), image_format))
		return path

	def test_decoders_limits_wrong_suffix_and_unsupported(self):
		from fman.impl.quick_view_images import ImageRequest, load_image, MAX_FILE_BYTES
		from fman.url import as_url
		from unittest.mock import patch
		from types import SimpleNamespace
		for image_format in ('JPEG', 'PNG', 'BMP'):
			path = self.make_image(image_format + '.wrong', 9, 7, image_format=image_format)
			result = load_image(ImageRequest(1, as_url(path)), lambda: False, lambda url: url)
			self.assertIsNotNone(result.image, result.message)
			self.assertEqual((9, 7), (result.image.width(), result.image.height()))
			self.assertEqual(1, result.image.devicePixelRatio())
			self.assertGreater(result.image.pixelColor(0, 0).red(), 240)
		path = self.make_image('retina@2x.png', 8, 6, '#80402010')
		result = load_image(ImageRequest(1, as_url(path)), lambda: False, lambda url: url)
		self.assertEqual(128, result.image.pixelColor(0, 0).alpha())
		self.assertEqual(1, result.image.devicePixelRatio())
		for name, data in (('bad.png', b'not an image'), ('vector.png', b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>')):
			path = self.root / name
			path.write_bytes(data)
			self.assertIsNone(load_image(ImageRequest(1, as_url(path)), lambda: False, lambda url: url).image)
		request = ImageRequest(1, as_url(self.root / 'retina@2x.png'))
		info = (self.root / 'retina@2x.png').stat()
		changed = SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size, st_mtime_ns=info.st_mtime_ns + 1)
		with patch('fman.impl.quick_view_images.os.stat', side_effect=[info, changed]):
			self.assertIn('changed', load_image(request, lambda: False, lambda url: url).message)
		oversized = SimpleNamespace(st_mode=info.st_mode, st_size=MAX_FILE_BYTES + 1)
		with patch('fman.impl.quick_view_images.os.stat', return_value=oversized), patch('fman.impl.quick_view_images.QImageReader') as reader:
			self.assertIsNone(load_image(request, lambda: False, lambda url: url).image)
			reader.assert_not_called()

	def test_exif_orientation(self):
		from fman.impl.quick_view_images import ImageRequest, load_image
		from fman.url import as_url
		from struct import pack
		path = self.make_image('oriented.jpg', 12, 8, image_format='JPEG')
		data = path.read_bytes()
		exif = b'Exif\0\0II' + pack('<HIH', 42, 8, 1) + pack('<HHIHHI', 274, 3, 1, 6, 0, 0)
		path.write_bytes(data[:2] + b'\xff\xe1' + pack('>H', len(exif) + 2) + exif + data[2:])
		result = load_image(ImageRequest(1, as_url(path)), lambda: False, lambda url: url)
		self.assertIsNotNone(result.image, result.message)
		self.assertEqual((8, 12), (result.image.width(), result.image.height()))

	def test_session_cursor_delivery_modes_and_cleanup(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_images import load_image
		from fman.impl.ui import UiOwner
		from fman.url import as_url
		from PyQt5.QtCore import QThread
		from unittest.mock import patch
		path = self.make_image()
		self.panes[0].reload()
		self.drain(self.panes[0])
		self.panes[0].place_cursor_at(as_url(path))
		ready, worker = Event(), []
		owner = UiOwner()
		def load(request, canceled):
			worker.append(QThread.currentThread() != QApplication.instance().thread())
			return load_image(request, canceled, self.filesystem.resolve)
		with patch('fman.load_json', return_value={'other': 7}), patch('fman.save_json') as save:
			def create():
				session = QuickViewSession(self.window, *self.panes, owner=owner, load=load)
				session.overlay.canvas.changed.connect(lambda: ready.set() if session.overlay.canvas.image is not None else None)
				return session
			session = self.run_in_app(create)
			self.addCleanup(session.shutdown)
			self.assertTrue(ready.wait(5), 'Image did not reach Qt')
			self.assertEqual([True], worker)
			def check():
				canvas = session.overlay.canvas
				self.assertIsNotNone(canvas.image)
				self.assertEqual('fit', canvas.mode)
				session.image_action('actual_size')
				self.assertEqual(1, canvas.scale)
				self.window.resize(1100, 680)
				self.assertEqual(1, canvas.scale)
				session.image_action('zoom_in')
				self.assertEqual(1.25, canvas.scale)
				session.switch_focus()
				self.assertTrue(canvas.hasFocus())
				session.switch_focus()
				self.assertTrue(self.panes[0].hasFocus())
				self.assertEqual(2, len(self.window.get_panes()))
			self.run_in_app(check)
			save.assert_called_once_with('QuickView.json', {'other': 7, 'image_mode': 'actual_size'})
			owner.invalidate()
			self.assertTrue(session.closed)
			self.assertIsNone(self.window._quick_view_session)
			self.assertFalse(session._connections)

	def test_empty_and_disappeared_locations_finish_loading(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_images import ImageResult
		from fman.url import as_url
		from PyQt5.QtGui import QImage
		from unittest.mock import Mock, patch
		source = self.panes[0]
		for disappears in (False, True):
			with self.subTest(disappears=disappears):
				parent = self.root / ('empty-%s' % disappears)
				parent.mkdir()
				destination = parent
				if disappears:
					destination = parent / 'disappearing'
					destination.mkdir()
				parent_url, destination_url = as_url(parent), as_url(destination)
				loaded = Event()
				load = Mock(return_value=ImageResult(message='Unexpected load'))
				from core.fs.local import LocalFileSystem
				scan = LocalFileSystem.scan
				def scan_directory(provider, path, check):
					if disappears and 'file://' + path == destination_url:
						destination.rmdir()
						raise FileNotFoundError(destination_url)
					return scan(provider, path, check)
				def on_loaded(url):
					if url == parent_url:
						loaded.set()
				def create():
					session = QuickViewSession(self.window, *self.panes, load=load)
					session.timer.stop()
					session.overlay.canvas.set_image(QImage(2, 2, QImage.Format_RGB32))
					session.overlay.set_title('previous.png')
					source._model.location_loaded.connect(on_loaded)
					return session
				with patch('fman.load_json', return_value={}), patch.object(LocalFileSystem, 'scan', scan_directory):
					session = self.run_in_app(create)
					try:
						from fman import _set_path_onerror
						source.set_location(destination_url, onerror=_set_path_onerror)
						self.assertTrue(loaded.wait(5), 'Empty parent did not finish loading')
						self.drain(source)
						def check():
							self.assertEqual(parent_url, source.get_location())
							self.assertFalse(session._loading_location)
							self.assertIsNone(session.overlay.canvas.image)
							self.assertEqual('No file selected', session.overlay.canvas.message)
							self.assertFalse(session.timer.isActive())
						self.run_in_app(check)
						load.assert_not_called()
					finally:
						self.run_in_app(source._model.location_loaded.disconnect, on_loaded)
						session.shutdown()

	def test_quickview_unreadable_refresh_finishes_parent_recovery(self):
		from core.fs.local import LocalFileSystem
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_images import ImageResult
		from fman.url import as_url
		from unittest.mock import Mock, patch
		source = self.panes[0]
		scan = LocalFileSystem.scan
		for index, error in enumerate((PermissionError('denied'), NotADirectoryError('not a directory'), OSError(5, 'not ready', None, 21))):
			with self.subTest(error=type(error)):
				destination = self.root / ('refresh-failure-%s' % index)
				destination.mkdir()
				loaded = Event()
				source.set_location(as_url(destination), callback=loaded.set)
				self.assertTrue(loaded.wait(5))
				self.drain(source)
				recovered = Event()
				def on_loaded(url):
					if url == as_url(self.root):
						recovered.set()
				def scan_directory(provider, path, check):
					if 'file://' + path == as_url(destination):
						raise error
					return scan(provider, path, check)
				with patch('fman.load_json', return_value={}):
					session = self.run_in_app(QuickViewSession, self.window, *self.panes,
						load=Mock(return_value=ImageResult(message='preview')))
				try:
					self.run_in_app(source._model.location_loaded.connect, on_loaded)
					with patch.object(LocalFileSystem, 'scan', scan_directory):
						source.reload()
						self.assertTrue(recovered.wait(5), 'Unreadable refresh did not recover')
						self.drain(source)
					self.assertFalse(self.run_in_app(lambda: session._loading_location))
					self.assertEqual(as_url(self.root), source.get_location())
				finally:
					self.run_in_app(source._model.location_loaded.disconnect, on_loaded)
					session.shutdown()

	def test_large_edge_paint_and_zoom_anchor(self):
		from fman.impl.quick_view import QuickViewOverlay
		from PyQt5.QtCore import QPointF
		from PyQt5.QtGui import QColor, QImage
		def check():
			overlay = QuickViewOverlay(self.window, *self.panes)
			try:
				canvas = overlay.canvas
				image = QImage(40, 20, QImage.Format_RGB32)
				image.fill(QColor('red'))
				canvas.set_image(image, 'actual_size')
				pixels = canvas.viewport().grab().toImage()
				def red(color):
					return color.red() > 240 and color.green() < 20 and color.blue() < 20
				self.assertEqual(40, sum(red(pixels.pixelColor(column, pixels.height() // 2)) for column in range(pixels.width())))
				self.assertEqual(20, sum(red(pixels.pixelColor(pixels.width() // 2, row)) for row in range(pixels.height())))
				image = QImage(65536, 8, QImage.Format_RGB32)
				image.fill(QColor('red'))
				canvas.set_image(image, 'actual_size')
				for position in (0, canvas.horizontalScrollBar().maximum()):
					canvas.horizontalScrollBar().setValue(position)
					pixels = canvas.viewport().grab().toImage()
					self.assertTrue(red(pixels.pixelColor(pixels.width() // 2, pixels.height() // 2)))
				image = QImage(2000, 1600, QImage.Format_RGB32)
				image.fill(QColor('blue'))
				canvas.set_image(image, 'actual_size')
				pointer = QPointF(120, 100)
				before = canvas._image_point(pointer)
				canvas.zoom(1, pointer)
				after = canvas._image_point(pointer)
				self.assertLess(abs(before.x() - after.x()), 2)
				self.assertLess(abs(before.y() - after.y()), 2)
			finally:
				overlay.dispose()
		self.run_in_app(check)

	def test_disable_reenable_reuses_blocked_loader_and_rejects_old_image(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_images import ImageResult
		from fman.url import as_url
		from PyQt5.QtGui import QColor, QImage
		from unittest.mock import patch
		path = self.make_image()
		self.panes[0].reload()
		self.drain(self.panes[0])
		self.panes[0].place_cursor_at(as_url(path))
		started, release, ready = Event(), Event(), Event()
		loads = []
		def load(request, canceled):
			loads.append(request.generation)
			first = len(loads) == 1
			if first:
				started.set()
				release.wait(5)
			image = QImage(2, 2, QImage.Format_RGB32)
			image.fill(QColor('red' if first else 'blue'))
			return ImageResult(image, format='png')
		self.addCleanup(release.set)
		with patch('fman.load_json', return_value={}):
			first = self.run_in_app(lambda: QuickViewSession(self.window, *self.panes, load=load))
			self.addCleanup(first.shutdown)
			self.assertTrue(started.wait(5))
			def replace():
				bridge = first.bridge
				first.close()
				session = QuickViewSession(self.window, *self.panes, load=load)
				self.assertIs(bridge, session.bridge)
				session.overlay.canvas.changed.connect(lambda: ready.set() if session.overlay.canvas.image is not None else None)
				return session
			second = self.run_in_app(replace)
			self.addCleanup(second.shutdown)
			release.set()
			self.assertTrue(ready.wait(5))
			self.assertEqual(2, len(loads))
			self.assertEqual(QColor('blue'), self.run_in_app(lambda: second.overlay.canvas.image.pixelColor(0, 0)))

	def test_cursor_debounce_ignores_marks_and_clears_old_pixels(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.impl.quick_view_images import load_image
		from fman.url import as_url
		from PyQt5.QtGui import QColor
		from unittest.mock import patch
		red = as_url(self.make_image('red.png', 8, 8, 'red'))
		blue = as_url(self.make_image('blue.png', 8, 8, 'blue'))
		self.panes[0].reload()
		self.drain(self.panes[0])
		self.panes[0].place_cursor_at(red)
		ready = Event()
		loads = []
		def load(request, canceled):
			loads.append(request.url)
			return load_image(request, canceled, self.filesystem.resolve)
		with patch('fman.load_json', return_value={}), patch('fman.save_json') as save:
			def create():
				session = QuickViewSession(self.window, *self.panes, load=load)
				session.overlay.canvas.changed.connect(lambda: ready.set() if session.overlay.canvas.image is not None else None)
				return session
			session = self.run_in_app(create)
			self.addCleanup(session.shutdown)
			self.assertTrue(ready.wait(5))
			ready.clear()
			generation = session.generation
			self.panes[0].select([blue])
			self.assertEqual(generation, session.generation)
			def browse():
				for index in range(200):
					self.panes[0].place_cursor_at(red if index % 2 else blue)
				self.panes[0].place_cursor_at(blue)
				self.assertIsNone(session.overlay.canvas.image)
				self.assertTrue(session.timer.isActive())
			self.run_in_app(browse)
			self.assertTrue(ready.wait(5))
			self.assertEqual([red, blue], loads)
			self.assertEqual(QColor('blue'), self.run_in_app(lambda: session.overlay.canvas.image.pixelColor(0, 0)))
			save.assert_not_called()

	def test_optional_formats_and_first_gif_frame(self):
		from fman.impl.quick_view_images import ImageRequest, load_image
		from fman.url import as_url
		from PyQt5.QtGui import QImageWriter, QImageReader
		from struct import pack
		writers = {bytes(name).lower() for name in QImageWriter.supportedImageFormats()}
		readers = {bytes(name).lower() for name in QImageReader.supportedImageFormats()}
		for image_format in ('webp', 'tiff', 'ico'):
			if image_format.encode() not in writers & readers:
				continue
			with self.subTest(format=image_format):
				path = self.make_image(image_format + '.bin', 16, 16, image_format=image_format.upper())
				result = load_image(ImageRequest(1, as_url(path)), lambda: False, lambda url: url)
				self.assertIsNotNone(result.image, result.message)
		if b'gif' not in readers:
			self.skipTest('Conditional GIF reader unavailable')
		header = b'GIF89a' + pack('<HHBBB', 1, 1, 128, 0, 0) + b'\xff\0\0\0\0\xff'
		frame = b',' + pack('<HHHHB', 0, 0, 1, 1, 0) + b'\x02\x02'
		path = self.root / 'animated.gif'
		path.write_bytes(header + frame + b'\x44\x01\0' + frame + b'\x4c\x01\0' + b';')
		result = load_image(ImageRequest(1, as_url(path)), lambda: False, lambda url: url)
		self.assertIsNotNone(result.image, result.message)
		self.assertEqual(255, result.image.pixelColor(0, 0).red())
		self.assertEqual(0, result.image.pixelColor(0, 0).blue())

	def test_mouse_controls_and_save_failure_remain_usable(self):
		from fman.impl.quick_view import QuickViewSession
		from PyQt5.QtCore import QEvent, QPoint, QPointF
		from PyQt5.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
		from unittest.mock import patch
		with patch('fman.load_json', return_value={}), patch('fman.save_json', side_effect=PermissionError('denied')):
			def check():
				session = QuickViewSession(self.window, *self.panes)
				try:
					session.timer.stop()
					canvas = session.overlay.canvas
					image = QImage(2000, 1600, QImage.Format_RGB32)
					image.fill(QColor('blue'))
					canvas.set_image(image, 'actual_size')
					session.image_action('fit')
					self.assertEqual('fit', canvas.mode)
					self.assertIn('could not be saved', self.window._status_bar_text.text())
					canvas.set_mode('actual_size')
					horizontal = canvas.horizontalScrollBar().value()
					vertical = canvas.verticalScrollBar().value()
					canvas.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(100, 100), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
					canvas.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(120, 130), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
					self.assertEqual(horizontal - 20, canvas.horizontalScrollBar().value())
					self.assertEqual(vertical - 30, canvas.verticalScrollBar().value())
					canvas.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(120, 130), Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
					canvas.wheelEvent(QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(), QPoint(0, 120), Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False))
					self.assertEqual(1.25, canvas.scale)
					self.assertFalse(session.overlay.buttons['fit'].isChecked())
					self.assertFalse(session.overlay.buttons['actual_size'].isChecked())
					self.assertTrue(canvas.hasFocus())
				finally:
					session.shutdown()
			self.run_in_app(check)

	def test_window_close_disposes_retiring_disabled_bridge(self):
		from fman.impl.quick_view import LoaderBridge
		from fman.impl.quick_view_images import ImageRequest, ImageResult
		started, release = Event(), Event()
		def load(request, canceled):
			started.set()
			release.wait(5)
			return ImageResult(message='late')
		bridge = self.run_in_app(lambda: LoaderBridge(self.window, load))
		self.addCleanup(release.set)
		bridge.loader.submit(ImageRequest(bridge.loader.invalidate(), 'blocked'))
		self.assertTrue(started.wait(5))
		self.run_in_app(self.window.closed.emit)
		self.assertTrue(bridge.closed)
		self.assertTrue(bridge.loader._closed)


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
		for column in (Name(), Size(), Modified(), NullColumn()):
			self.filesystem.register_column(column.get_qualified_name(), column)
		def create():
			self.window = MainWindow(QApplication.instance(), Mock(), Mock(), self.filesystem, 'null://')
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
		self.run_in_app(close)
		self.run_in_app(self.window.deleteLater)
		self.errors.assert_not_called()

	def navigate(self, pane, path):
		from fman.url import as_url
		loaded = Event()
		pane.set_location(as_url(path), callback=loaded.set)
		self.assertTrue(loaded.wait(5), 'Pane did not load')
		self.drain(pane)

	def drain(self, pane):
		self.drain_model(pane._model)

	def set_query(self, text, pane=None):
		pane = pane or self.panes[0]
		self.run_in_app(pane._filter_bar._input.setText, text)
		self.drain(pane)

	def status(self):
		for pane in self.panes:
			self.drain(pane)
		return self.run_in_app(self.window._status_bar_text.text)

	def key(self, key, text='', pane=None):
		from PyQt5.QtCore import QEvent
		from PyQt5.QtGui import QKeyEvent
		pane = pane or self.panes[0]
		result = self.run_in_app(pane._on_key_pressed, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, text))
		self.drain(pane)
		return result

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
		from core.fs.local import LocalFileSystem
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
		original = LocalFileSystem.scan
		def delayed(provider, path, check):
			entered.set()
			if not release.wait(5):
				raise AssertionError('Initial population was not released')
			return original(provider, path, check)
		self.set_query('tmp')
		threads = []
		def replace():
			emitter = Thread(target=old_model.files_changed.emit)
			emitter.start()
			emitter.join(2)
			self.assertFalse(emitter.is_alive())
			pane.set_location(as_url(nested), callback=loaded.set)
			pane._filter_bar._input.setText('rep')
			self.window.show_status_message('Loading command')
			pane._model.files_changed.connect(lambda: threads.append(QThread.currentThread()))
		with patch.object(LocalFileSystem, 'scan', delayed):
			try:
				self.run_in_app(replace)
				self.assertTrue(entered.wait(5))
				self.set_query('re')
				self.assertEqual('Filter "re": 2 of 5 items', self.status())
			finally:
				release.set()
			self.assertTrue(loaded.wait(5))
			self.drain(pane)
		self.set_query('re')
		self.assertEqual('Filter "re": 1 of 2 items', self.status())
		self.assertTrue(threads)
		self.assertTrue(all(thread == QApplication.instance().thread() for thread in threads))
		self.assertEqual(as_url(nested / 'report.new'), pane.get_file_under_cursor())
		new_file = nested / 'nonmatching.txt'
		new_file.write_bytes(b'')
		model = self.run_in_app(pane._model.sourceModel)
		model.notify_file_added(as_url(new_file))
		self.drain(pane)
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

	def test_compare_directories_counts_real_filtered_selections(self):
		from core.commands import CompareDirectories
		from fman import DirectoryPane
		from fman.url import as_url
		from unittest.mock import Mock, patch
		left_path, right_path = self.root / 'left', self.root / 'right'
		for path, names in ((left_path, ('common.txt', 'left.txt', 'hidden.log')),
			(right_path, ('common.txt', 'right.txt'))):
			path.mkdir()
			for name in names:
				(path / name).write_bytes(b'')
		for pane, path in zip(self.panes, (left_path, right_path)):
			self.navigate(pane, path)
		public_window = Mock()
		panes = [DirectoryPane(public_window, pane, Mock()) for pane in self.panes]
		public_window.get_panes.return_value = panes
		self.set_query('.txt$', self.panes[0])
		self.set_query('right.txt', self.panes[1])
		panes[0].select([as_url(left_path / 'common.txt')])
		with patch('core.commands.iterdir', side_effect=self.filesystem.iterdir), \
			patch('core.commands.show_alert') as alert:
			CompareDirectories(panes[1])()
			self.assertEqual([as_url(left_path / 'left.txt')], panes[0].get_selected_files())
			self.assertEqual([as_url(right_path / 'right.txt')], panes[1].get_selected_files())
			alert.assert_called_once_with(
				'Selected 1 visible file in the left pane not present on the right.<br/>'
				'Selected 1 visible file in the right pane not present on the left.<br/>'
				'The remaining differences are hidden, filtered, or otherwise not selectable.'
			)
			self.set_query('common.txt', self.panes[0])
			self.set_query('common.txt', self.panes[1])
			CompareDirectories(panes[0])()
			self.assertEqual([], panes[0].get_selected_files())
			self.assertEqual([], panes[1].get_selected_files())
			self.assertIn('none of the differences can currently be selected', alert.call_args.args[0])
			self.navigate(self.panes[1], left_path)
			self.set_query('left.txt', self.panes[1])
			CompareDirectories(panes[0])()
			self.assertIn('same file <em>names</em>', alert.call_args.args[0])
			self.assertEqual([], panes[0].get_selected_files())
			self.assertEqual([], panes[1].get_selected_files())

	def test_delete_continuation_suppresses_progress_popup(self):
		from core.commands import _Delete
		from fman import Task, submit_task, YES, NO
		from PyQt5.QtCore import QThread, QTimer
		from unittest.mock import patch
		attempted, dialogs, observed = [], [], []
		def fail():
			attempted.append('first')
			raise PermissionError(13, 'denied')
		children = {
			'file://C:/first': Task('Deleting first', size=1, fn=fail),
			'file://C:/second': Task('Deleting second', size=1, fn=lambda: attempted.append('second')),
		}
		task = _Delete(list(children), lambda url: [children[url]])
		self.run_in_app(lambda: setattr(self.window, '_progress_bar_palette', QApplication.instance().palette()))
		original = self.window.create_progress_dialog
		def create_dialog(*args):
			dialog = original(*args)
			dialogs.append(dialog)
			return dialog
		def answer(message_box):
			dialog = dialogs[-1]
			observed.append((
				dialog.minimumDuration() == dialog._MAX_C_INT,
				message_box.defaultButton() == message_box.button(YES),
				QThread.currentThread() == QApplication.instance().thread(),
			))
			QTimer.singleShot(0, message_box.button(NO).click)
		self.run_in_app(self.window.before_dialog.connect, answer)
		try:
			with patch('fman._get_ui', return_value=self.window), \
				patch.object(self.window, 'create_progress_dialog', side_effect=create_dialog), \
				patch('core.commands.show_alert', side_effect=AssertionError('Bypassed task alert')):
				submit_task(task)
			self.assertEqual(['first'], attempted)
			self.assertEqual([(True, True, True)], observed)
			self.assertEqual(dialogs[0]._MINIMUM_DURATION_MS, self.run_in_app(dialogs[0].minimumDuration))
		finally:
			self.run_in_app(self.window.before_dialog.disconnect, answer)
			for dialog in dialogs:
				self.run_in_app(dialog.cancel)
				self.run_in_app(dialog.deleteLater)

	def test_special_filenames_and_status_mode_changes(self):
		from fman.impl.status_bar import DEFAULT_SETTINGS, DISABLED, ACTIVE_PANE
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
		for mode in (ACTIVE_PANE, DISABLED):
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

class SnapshotFilterBarIT(FilterBarIT):
	def test_copy_preparation_progress_is_visible_and_cancel_leaves_no_changes(self):
		from core.commands import Copy
		from core.fileoperations import FileTreeOperation
		from fman import DirectoryPane
		from fman.url import as_url
		from PyQt5.QtCore import QTimer
		from time import perf_counter
		from unittest.mock import patch
		release, observed, dialogs = Event(), [], []
		destination = self.root / 'not-created'
		source = self.root / 'report.txt'
		pane = DirectoryPane(None, self.panes[0], None)
		self.run_in_app(lambda: setattr(self.window, '_progress_bar_palette', QApplication.instance().palette()))
		original_create = self.window.create_progress_dialog
		original_contains = FileTreeOperation._contains_destination
		def create(*args):
			dialog = original_create(*args)
			dialogs.append(dialog)
			def watch():
				timer = QTimer(dialog)
				def tick():
					if dialog.isVisible():
						timer.stop()
						observed.append((perf_counter() - started) * 1000)
						dialog.request_cancel()
						release.set()
				timer.timeout.connect(tick)
				timer.start(10)
			self.run_in_app(watch)
			return dialog
		def hold(operation, *args):
			self.assertTrue(release.wait(5), 'Preparation never displayed cancellable progress')
			return original_contains(operation, *args)
		started = perf_counter()
		try:
			with patch('fman._get_ui', return_value=self.window), \
					patch('fman.fs._get_mother_fs', return_value=self.filesystem), \
					patch.object(self.window, 'show_alert', side_effect=AssertionError('Unexpected copy alert')), \
					patch.object(self.window, 'create_progress_dialog', side_effect=create), \
					patch.object(Copy, '_confirm_tree_operation', return_value=(as_url(destination), None)), \
					patch.object(FileTreeOperation, '_contains_destination', hold):
				Copy(pane)(files=[as_url(source)], dest_dir=as_url(destination))
			self.assertEqual(1, len(observed))
			self.assertLess(observed[0], 1250)
			self.assertLess((perf_counter() - started) * 1000 - observed[0], 250)
			self.assertTrue(source.exists())
			self.assertFalse(destination.exists())
		finally:
			release.set()
			for dialog in dialogs:
				self.run_in_app(dialog.cancel)
				self.run_in_app(dialog.deleteLater)

	def test_plain_public_reload_keeps_worker_signal_path(self):
		from fman import DirectoryPane
		from threading import get_ident
		from unittest.mock import patch
		pane = self.panes[0]
		caller_thread = get_ident()
		threads = []
		with patch.object(pane._model, 'reload', side_effect=lambda: threads.append(get_ident())), \
				patch.object(pane, '_reload_with_callback') as with_callback:
			DirectoryPane(None, pane, None).reload()
			with_callback.assert_not_called()
		self.assertEqual([caller_thread], threads)

	def test_reload_completion_waits_for_fresh_scan_once(self):
		from fman import DirectoryPane
		from threading import get_ident
		from unittest.mock import patch
		pane = self.panes[0]
		source = self.run_in_app(pane._model.sourceModel)
		public = DirectoryPane(None, pane, None)
		started, released = (Event(), Event()), (Event(), Event())
		finished, scans, completions = Event(), [], []
		original = source._scanner
		def scan(check):
			index = len(scans)
			scans.append(index)
			if index < len(started):
				started[index].set()
				if not released[index].wait(5):
					raise TimeoutError('Reload scan not released')
			return original(check)
		def completed():
			completions.append((get_ident(), source._scan_revision,
				source._committed_revision == source._revision))
			finished.set()
		receivers = self.run_in_app(lambda: source.receivers(source.all_rows_loaded))
		with patch.object(source, '_scanner', scan):
			try:
				public.reload()
				self.assertTrue(started[0].wait(5))
				revision = self.run_in_app(lambda: source._scan_revision)
				public.reload(on_done=completed)
				self.assertFalse(finished.is_set())
				released[0].set()
				self.assertTrue(started[1].wait(5))
				self.assertFalse(finished.is_set(), 'In-flight scan satisfied a newer reload')
				released[1].set()
				self.assertTrue(finished.wait(5))
				self.drain(pane)
				self.assertEqual([(self.run_in_app(get_ident), revision + 1, True)], completions)
				self.assertEqual(receivers, self.run_in_app(lambda: source.receivers(source.all_rows_loaded)))
				public.reload()
				self.drain(pane)
				self.assertEqual(1, len(completions))
			finally:
				for release in released:
					release.set()

	def test_failed_reload_does_not_complete_on_filter_or_sort(self):
		from fman import DirectoryPane
		from unittest.mock import Mock, patch
		pane = self.panes[0]
		source = self.run_in_app(pane._model.sourceModel)
		public = DirectoryPane(None, pane, None)
		for invalid_scan in (Mock(side_effect=RuntimeError('Scan failed')), Mock(return_value=None)):
			failed, finished = Event(), Event()
			callback = Mock(side_effect=finished.set)
			revision = self.run_in_app(lambda: source._scan_revision)
			receivers = self.run_in_app(lambda: source.receivers(source.all_rows_loaded))
			with patch.object(source, '_scanner', invalid_scan), \
					patch('sys.excepthook', side_effect=lambda *args: failed.set()):
				public.reload(on_done=callback)
				self.assertTrue(failed.wait(5))
				self.set_query('report', pane)
				pane.set_sort_column('core.Name', False)
				self.drain(pane)
				callback.assert_not_called()
				self.assertEqual(revision, self.run_in_app(lambda: source._successful_scan_revision))
				self.assertEqual(revision + 1, self.run_in_app(lambda: source._scan_revision))
			public.reload()
			self.assertTrue(finished.wait(5), 'Successful retry did not complete reload')
			self.drain(pane)
			callback.assert_called_once_with()
			self.assertEqual(receivers, self.run_in_app(lambda: source.receivers(source.all_rows_loaded)))
			self.set_query('', pane)
			callback.assert_called_once_with()

	def test_reload_completion_disconnects_on_navigation(self):
		from fman import DirectoryPane
		from unittest.mock import Mock, patch
		pane = self.panes[0]
		callback = Mock()
		receivers = self.run_in_app(lambda: pane._model.receivers(pane._model.location_changed))
		with patch.object(pane._model, 'reload'):
			DirectoryPane(None, pane, None).reload(on_done=callback)
		self.assertEqual(receivers + 1, self.run_in_app(lambda: pane._model.receivers(pane._model.location_changed)))
		self.navigate(pane, self.root.parent)
		callback.assert_not_called()
		self.assertEqual(receivers, self.run_in_app(lambda: pane._model.receivers(pane._model.location_changed)))

	def test_reload_completion_disconnects_on_window_close(self):
		from fman import DirectoryPane
		from unittest.mock import Mock, patch
		pane = self.panes[0]
		source = self.run_in_app(pane._model.sourceModel)
		public, callback = DirectoryPane(None, pane, None), Mock()
		receivers = self.run_in_app(lambda: source.receivers(source.all_rows_loaded))
		with patch.object(pane._model, 'reload'):
			public.reload(on_done=callback)
		self.assertEqual(receivers + 1, self.run_in_app(lambda: source.receivers(source.all_rows_loaded)))
		self.run_in_app(self.window.close)
		self.assertEqual(receivers, self.run_in_app(lambda: source.receivers(source.all_rows_loaded)))
		self.run_in_app(source.all_rows_loaded.emit)
		public.reload(on_done=callback)
		self.assertEqual(receivers, self.run_in_app(lambda: source.receivers(source.all_rows_loaded)))
		callback.assert_not_called()

	def test_status_snapshots_are_complete_for_visible_entries(self):
		from fman.listing import Listing
		from unittest.mock import patch
		pane = self.panes[0]
		for query in ('', 'rep', 'no_matching_filename'):
			self.set_query(query)
			def check():
				snapshot = pane.get_status_snapshot()
				self.assertTrue(snapshot[2])
				self.assertEqual(pane._model.rowCount(), len(snapshot.entries))
				self.assertTrue(all(entry.is_loaded for entry in snapshot.entries))
			self.run_in_app(check)
		def check_large():
			source = pane._model.sourceModel()
			count = 20000
			listing = Listing.create(source.get_location(),
				tuple('entry%d.txt' % index for index in range(count)))
			with patch.multiple(source, _displayed=listing, _visible=tuple(range(count))):
				snapshot = pane.get_status_snapshot()
				self.assertTrue(snapshot[2])
				self.assertEqual(count, len(snapshot.entries))
				self.assertTrue(all(entry.is_loaded for entry in snapshot.entries))
		self.run_in_app(check_large)

	def test_unchanged_sentinel_restores_all_marks_cursor_and_scroll(self):
		from dataclasses import replace
		from fman.impl.model.listing import Projection
		from fman.listing import Listing, reconcile
		from unittest.mock import patch
		pane = self.panes[0]
		source = self.run_in_app(pane._model.sourceModel)
		count = 512
		previous = Listing.create(self.run_in_app(source.get_location), tuple('entry%04d' % index for index in range(count)),
			identities=b''.join((index + 1).to_bytes(16, 'little') for index in range(count)))
		current = replace(previous, names=tuple(name.encode().decode() for name in previous.names),
			identities=memoryview(previous.identities).tobytes(), sizes=(7,) * count)
		remap = reconcile(previous, current)
		self.assertIsNone(remap)
		visible = tuple(range(count))
		rows = {index: index for index in visible}
		def check():
			with patch.object(source, '_icons', None):
				source._listing = previous
				source._commit(Projection(previous, visible, rows, {}, 0, True, columns=source._columns))
				pane._file_view.setCurrentIndex(pane._model.index(count // 2, 0))
				pane._file_view.scrollTo(pane._file_view.currentIndex())
				pane._file_view.selectAll()
				scroll = pane._file_view.verticalScrollBar().value()
				source._listing = current
				source._commit(Projection(current, visible, rows, remap, 0, True, columns=source._columns))
				selected = pane._file_view.selectionModel().selection()
				self.assertEqual(count, sum(selection.bottom() - selection.top() + 1 for selection in selected))
				self.assertEqual(count // 2, pane._file_view.currentIndex().row())
				self.assertEqual(scroll, pane._file_view.verticalScrollBar().value())
		self.run_in_app(check)

	def test_metadata_delivery_repaints_without_reset_unless_sort_depends_on_it(self):
		from fman.url import as_url
		from unittest.mock import Mock, patch
		pane = self.panes[0]
		url = as_url(self.root / 'report.txt')
		pane.place_cursor_at(url)
		pane.select([url])
		for column in ('core.Name', 'core.Modified', 'core.Size'):
			pane.set_sort_column(column, True)
			self.drain(pane)
			model = self.run_in_app(pane._model.sourceModel)
			reset, changed = Mock(), Mock()
			self.run_in_app(model.modelReset.connect, reset)
			self.run_in_app(model.dataChanged.connect, changed)
			try:
				with patch.object(model._view_jobs, 'submit', wraps=model._view_jobs.submit) as submit:
					pane.refresh_files([url])
					self.drain(pane)
					if column == 'core.Size':
						submit.assert_called_once()
						reset.assert_called_once()
					else:
						submit.assert_not_called()
						reset.assert_not_called()
						self.assertTrue(any(args[2] == [Qt.DisplayRole] for args, kwargs in changed.call_args_list))
				self.assertEqual(url, pane.get_file_under_cursor())
				self.assertEqual([url], pane.get_selected_files())
			finally:
				self.run_in_app(model.modelReset.disconnect, reset)
				self.run_in_app(model.dataChanged.disconnect, changed)

	def test_missing_cursor_request_expires_after_refresh(self):
		from fman.url import as_url
		pane = self.panes[0]
		target = self.root / 'later.txt'
		pane.place_cursor_at(as_url(target))
		self.drain(pane)
		previous = pane.get_file_under_cursor()
		self.assertIsNone(self.run_in_app(lambda: pane._file_view._pending_cursor))
		target.write_bytes(b'later')
		pane.reload()
		self.drain(pane)
		self.assertEqual(previous, pane.get_file_under_cursor())

	def test_refresh_cancels_editor_and_invalidates_drag_index(self):
		from fman.url import as_url
		from PyQt5.QtWidgets import QLineEdit
		from unittest.mock import Mock
		pane = self.panes[0]
		url = as_url(self.root / 'report.txt')
		renamed = Mock()
		def begin():
			pane._model.file_renamed.connect(renamed)
			pane._file_view._dragged_index = pane._model.find(url)
			pane.edit_name(url)
			editor = pane._file_view.findChild(QLineEdit, 'editor')
			self.assertIsNotNone(editor)
			editor.setText('not-committed.txt')
		self.run_in_app(begin)
		(self.root / 'added-while-editing.txt').write_bytes(b'x')
		pane.reload()
		self.drain(pane)
		renamed.assert_not_called()
		self.assertIsNone(self.run_in_app(lambda: pane._file_view._dragged_index))
		self.assertNotEqual(pane._file_view.EditingState, self.run_in_app(pane._file_view.state))
		self.assertTrue((self.root / 'report.txt').exists())

	def test_unchanged_refresh_notifies_without_reset(self):
		from fman.url import as_url
		from PyQt5.QtWidgets import QLineEdit
		from unittest.mock import Mock, patch
		pane = self.panes[0]
		url = as_url(self.root / 'report.txt')
		pane.place_cursor_at(url)
		pane.select([url])
		self.drain(pane)
		source = self.run_in_app(pane._model.sourceModel)
		reset, committed, files_changed, all_rows_loaded, ended = (Mock() for _ in range(5))
		def begin():
			source.modelReset.connect(reset)
			source.committed.connect(committed)
			source.files_changed.connect(files_changed)
			source.all_rows_loaded.connect(all_rows_loaded)
			source.transaction_ended.add_callback(ended)
			pane.edit_name(url)
			self.assertIsNotNone(pane._file_view.findChild(QLineEdit, 'editor'))
		self.run_in_app(begin)
		try:
			with patch.object(source._view_jobs, 'submit', wraps=source._view_jobs.submit) as submit:
				pane.reload()
				self.drain(pane)
				submit.assert_not_called()
			reset.assert_not_called()
			for signal in (committed, files_changed, all_rows_loaded, ended):
				signal.assert_called_once()
			self.assertIs(source._last_projection, committed.call_args[0][0])
			self.assertEqual(url, pane.get_file_under_cursor())
			self.assertEqual([url], pane.get_selected_files())
			self.assertEqual(pane._file_view.EditingState, self.run_in_app(pane._file_view.state))
			# Changed metadata still goes through the normal commit.
			(self.root / 'report.txt').write_bytes(b'longer content')
			pane.reload()
			self.drain(pane)
			reset.assert_called_once()
			self.assertEqual(2, committed.call_count)
			self.assertEqual(url, pane.get_file_under_cursor())
		finally:
			self.run_in_app(source.transaction_ended.remove_callback, ended)

	def test_unchanged_refresh_resolves_missing_cursor_request(self):
		from fman.url import as_url
		from unittest.mock import patch
		pane = self.panes[0]
		source = self.run_in_app(pane._model.sourceModel)
		def request():
			with patch.object(source, 'reload'):
				pane._file_view.place_cursor_at(as_url(self.root / 'absent.txt'))
			self.assertIsNotNone(pane._file_view._pending_cursor)
		self.run_in_app(request)
		pane.reload()
		self.drain(pane)
		self.assertIsNone(self.run_in_app(lambda: pane._file_view._pending_cursor))

	def test_unchanged_refresh_retries_failed_projection(self):
		import sys
		from core import Name
		from time import monotonic
		from unittest.mock import Mock, patch
		pane = self.panes[0]
		self.drain(pane)
		source = self.run_in_app(pane._model.sourceModel)
		committed, hooks = Mock(), []
		self.run_in_app(source.committed.connect, committed)
		with patch.object(sys, 'excepthook', lambda *args: hooks.append(args)):
			with patch.object(Name, 'keys', side_effect=RuntimeError('injected key failure')):
				def rebuild_keys():
					source._order_cache = None  # otherwise the cached order skips Name.keys
					source.update()
				self.run_in_app(rebuild_keys)
				deadline = monotonic() + 5
				while monotonic() < deadline and not hooks:
					pass
			self.assertEqual(1, len(hooks))
			self.assertTrue(self.run_in_app(lambda: source._revision != source._committed_revision))
			committed.assert_not_called()
			pane.reload()
			self.drain(pane)
		committed.assert_called_once()
		self.assertTrue(self.run_in_app(lambda: source._revision == source._committed_revision))
		self.assertEqual(1, len(hooks))

	def test_native_mutations_refresh_both_panes_and_operation_cache(self):
		from fman.url import as_url
		first, second = self.panes
		created = as_url(self.root / 'created.txt')
		copied = as_url(self.root / 'copied.txt')
		moved = as_url(self.root / 'moved.txt')
		folder = as_url(self.root / 'created-folder')
		self.filesystem.touch(created)
		self.filesystem.mkdir(folder)
		for pane in self.panes:
			self.drain(pane)
			self.assertTrue(self.run_in_app(pane._model.find, created).isValid())
			self.assertTrue(self.run_in_app(pane._model.find, folder).isValid())
		metadata = self.filesystem.query(created, 'stat')
		self.assertNotEqual(0, metadata.st_ino)
		self.assertNotEqual(0, metadata.st_dev)
		first.select([created])
		self.filesystem.copy(created, copied)
		self.filesystem.move(created, moved)
		for pane in self.panes:
			self.drain(pane)
			self.assertTrue(self.run_in_app(pane._model.find, copied).isValid())
			self.assertTrue(self.run_in_app(pane._model.find, moved).isValid())
		self.assertEqual([moved], first.get_selected_files())
		self.assertEqual([], second.get_selected_files())
		for url in (copied, moved, folder):
			self.filesystem.delete(url)
		for pane in self.panes:
			self.drain(pane)
			self.assertEqual(5, self.run_in_app(pane._model.rowCount))
			self.assertEqual([], pane.get_selected_files())

	def test_window_close_retires_blocked_navigation_and_observation(self):
		from core.fs.local import LocalFileSystem
		from fman.impl.model.listing import ScanObservation
		from fman.impl.navigation import NavigationRequest, tracking
		from fman.url import as_url
		from unittest.mock import patch
		folder = self.root / 'pending-close'
		folder.mkdir()
		entered, release, cleaned = Event(), Event(), Event()
		outcomes = []
		request = NavigationRequest(lambda *args: outcomes.append(args))
		original, original_close = LocalFileSystem.scan, ScanObservation.close
		def delayed(provider, path, check):
			entered.set()
			if not release.wait(5):
				raise TimeoutError('Scan not released')
			return original(provider, path, check)
		def close(observation):
			original_close(observation)
			if observation._location == as_url(folder):
				cleaned.set()
		with patch.object(LocalFileSystem, 'scan', delayed), patch.object(ScanObservation, 'close', close):
			try:
				with tracking(request):
					self.panes[0]._model.set_location(as_url(folder))
				self.assertTrue(entered.wait(5))
				self.run_in_app(self.window.close)
				self.assertTrue(request.settled.wait(5))
				self.assertEqual([('superseded', '')], outcomes)
			finally:
				release.set()
			self.assertTrue(cleaned.wait(5))
		self.assertTrue(all(pane._model._closed for pane in self.panes))

	def test_icon_suffix_parsed_once_and_shell_arguments_preserved(self):
		from fman.impl.model.listing_icons import ListingIcons
		from fman.listing import Listing
		from pathlib import PureWindowsPath
		from unittest.mock import patch
		names = ('README', '.config', '..config', '.config.json', 'entry.',
			'entry.TXT', 'program.EXE', 'shortcut.lnk', 'folder.ext')
		listing = Listing.create('file://C:/icons', names, is_dir=(False,) * 8 + (True,))
		icons = self.run_in_app(ListingIcons)
		try:
			def check_icons():
				with patch('fman.impl.model.listing_icons.Thread'), \
					patch('fman.impl.model.listing_icons.PureWindowsPath', wraps=PureWindowsPath) as parse:
					for index, name in enumerate(names):
						self.assertFalse(icons.icon(listing, index).isNull())
						self.assertEqual(index + 1, parse.call_count)
						suffix = PureWindowsPath(name).suffix.lower()
						individual = listing.is_dir[index] or suffix in ('.exe', '.lnk', '.ico', '.url') or not suffix
						path = 'C:\\icons\\' + name
						key = (path, listing.identity(index), None) if individual else suffix
						self.assertEqual((path if individual else 'file' + suffix, 0, not individual), icons._pending[key])
			self.run_in_app(check_icons)
		finally:
			self.run_in_app(icons.close)
			self.run_in_app(icons.deleteLater)

	def test_model_decoration_reuses_key_for_misses_hits_and_notifications(self):
		from collections import OrderedDict
		from fman.impl.model.listing_icons import ListingIcons
		from fman.listing import Listing
		from unittest.mock import Mock, patch
		def check():
			source = self.panes[0]._model.sourceModel()
			icons = ListingIcons()
			listing = Listing.create('file://C:/icons', ('file.TXT', 'app.exe', 'folder'),
				is_dir=(False, False, True))
			changed = Mock()
			source.dataChanged.connect(changed)
			try:
				with patch.multiple(source, _icons=icons, _displayed=listing,
					_visible=(0, 1, 2), _icon_cells=OrderedDict()), \
					patch('fman.impl.model.listing_icons.Thread') as thread, \
					patch.object(icons, 'key', wraps=icons.key) as key_method:
					for row in range(3):
						index = source.index(row, 0)
						self.assertFalse(index.data(Qt.DecorationRole).isNull())
						key = source._icon_cells[row]
						self.assertIn(key, icons._pending)
						icons._cache[key] = None
						self.assertFalse(index.data(Qt.DecorationRole).isNull())
						self.assertEqual((row + 1) * 2, key_method.call_count)
						changed.reset_mock()
						source._icons_changed(key)
						changed.assert_called_once_with(index, index, [Qt.DecorationRole])
					thread.assert_called_once()
			finally:
				source.dataChanged.disconnect(changed)
				icons.close()
				icons.deleteLater()
		self.run_in_app(check)

	def test_precomputed_icon_keys_preserve_provider_and_attribute_fallbacks(self):
		from fman.impl.model.listing_icons import ListingIcons
		from fman.listing import Listing
		from unittest.mock import patch
		def check():
			icons = ListingIcons()
			try:
				with patch('fman.impl.model.listing_icons.Thread') as thread:
					for location, attributes in (('zip://archive', 0), ('file://C:/icons', 0x400),
						('file://C:/icons', 0x1000), ('file://C:/icons', 0x400000)):
						listing = Listing.create(location, ('file.txt', 'folder'),
							is_dir=(False, True), attributes=(attributes, attributes))
						for index, fallback in enumerate((icons._file, icons._folder)):
							key = icons.key(listing, index)
							self.assertIs(fallback, icons.icon(listing, index, key=key))
							self.assertIs(fallback, icons.icon(listing, index))
					thread.assert_not_called()
					self.assertFalse(icons._pending)
			finally:
				icons.close()
				icons.deleteLater()
		self.run_in_app(check)

	def test_icon_queue_bounds_pending_and_undelivered_results(self):
		from dataclasses import replace
		from fman.impl.model.listing_icons import ListingIcons
		from threading import get_ident
		started, release, delivered = Event(), Event(), Event()
		threads = []
		def loader(*args):
			threads.append(get_ident())
			started.set()
			if not release.wait(5):
				raise TimeoutError('Icon not released')
			return None
		icons = self.run_in_app(ListingIcons, None, loader)
		listing = self.panes[0].get_listing()
		count = 300
		listing = replace(listing, names=tuple('file.ext%d' % index for index in range(count)),
			is_dir=(False,) * count, sizes=(0,) * count, mtimes_ns=(0,) * count,
			attributes=(0,) * count, created_ns=(0,) * count, identities=b'\0' * (count * 16))
		try:
			def request():
				for index in range(count):
					self.assertFalse(icons.icon(listing, index).isNull())
				with icons._lock:
					self.assertLessEqual(len(icons._pending) + len(icons._inflight), 128)
			self.run_in_app(request)
			self.assertTrue(started.wait(5))
			self.assertNotEqual(self.run_in_app(get_ident), threads[0])
			self.run_in_app(icons.changed.connect, lambda *_: delivered.set())
			release.set()
			self.assertTrue(delivered.wait(5))
		finally:
			release.set()
			self.run_in_app(icons.close)
			self.run_in_app(icons.deleteLater)

	def test_fuzzy_find_mode_restores_filter_marks_cursor_and_metadata_columns(self):
		from search_file_fuzzy.indexer import ListingSearch
		from fman.url import as_url
		from unittest.mock import Mock
		pane = self.panes[0]
		self.set_query('rep')
		original = as_url(self.root / 'report.txt')
		pane.place_cursor_at(original)
		pane.select([original])
		accepted = Mock()
		self.assertTrue(pane.find_in_listing(ListingSearch(max_results=1), 'script', False, accepted))
		self.drain(pane)
		self.assertEqual(1, self.run_in_app(pane._model.rowCount))
		self.assertEqual(as_url(self.root / 'script.py'), pane.get_file_under_cursor())
		self.assertIn('Find "script": 1', self.status())
		self.assertEqual(tuple(range(6)), self.run_in_app(lambda: pane._model.index(0, 0).data(Qt.UserRole + 1)))
		self.assertFalse(self.run_in_app(pane._file_view.grab).isNull())
		self.assertTrue(self.run_in_app(pane._file_view.isColumnHidden, 1))
		self.set_query('Annual')
		self.assertEqual(as_url(self.root / 'Annual Report.pdf'), pane.get_file_under_cursor())
		pane.find_in_listing(ListingSearch(max_results=1), 'report', False, accepted)
		self.drain(pane)
		self.key(Qt.Key_Escape)
		self.assertEqual('rep', self.run_in_app(pane._filter_bar._input.text))
		self.assertEqual(original, pane.get_file_under_cursor())
		self.assertEqual([original], pane.get_selected_files())
		self.assertFalse(self.run_in_app(pane._file_view.isColumnHidden, 1))
		accepted.assert_not_called()
		pane.find_in_listing(ListingSearch(mode='regular'), 'Annual', True, accepted)
		self.drain(pane)
		self.key(Qt.Key_Return)
		accepted.assert_called_once_with(as_url(self.root / 'Annual Report.pdf'))
		self.assertEqual('rep', self.run_in_app(pane._filter_bar._input.text))

	def test_initial_handoff_rescans_only_when_mutated(self):
		from core.fs.local import LocalFileSystem
		from fman.url import as_url
		from unittest.mock import patch
		pane = self.panes[0]
		original = LocalFileSystem.scan
		for mutate in (False, True):
			folder = self.root / ('dirty' if mutate else 'clean')
			folder.mkdir()
			(folder / 'first.txt').touch()
			entered, release, loaded = Event(), Event(), Event()
			calls = []
			def delayed(provider, path, check):
				listing = original(provider, path, check)
				if path == as_url(folder)[7:]:
					calls.append(path)
					if len(calls) == 1:
						entered.set()
						if not release.wait(5):
							raise TimeoutError('Handoff not released')
				return listing
			with patch.object(LocalFileSystem, 'scan', delayed):
				try:
					pane.set_location(as_url(folder), callback=loaded.set)
					self.assertTrue(entered.wait(5))
					if mutate:
						self.filesystem.touch(as_url(folder / 'second.txt'))
				finally:
					release.set()
				self.assertTrue(loaded.wait(5))
				self.drain(pane)
			self.assertEqual(2 if mutate else 1, len(calls))
			self.assertEqual(2 if mutate else 1, self.run_in_app(pane._model.rowCount))

	def test_tracked_superseded_scan_cannot_replace_returned_location(self):
		from core.fs.local import LocalFileSystem
		from fman.impl.navigation import NavigationRequest, tracking
		from fman.url import as_url
		from unittest.mock import patch
		pane = self.panes[0]
		folder = self.root / 'pending'
		folder.mkdir()
		entered, release, retired, loaded = Event(), Event(), Event(), Event()
		outcomes = []
		request = NavigationRequest(lambda *args: outcomes.append(args))
		original = LocalFileSystem.scan
		def delayed(provider, path, check):
			if path == as_url(folder)[7:]:
				entered.set()
				try:
					if not release.wait(5):
						raise TimeoutError('Scan not released')
					return original(provider, path, check)
				finally:
					retired.set()
			return original(provider, path, check)
		with patch.object(LocalFileSystem, 'scan', delayed):
			try:
				with tracking(request):
					pane._model.set_location(as_url(folder))
				self.assertTrue(entered.wait(5))
				pane.set_location(as_url(self.root), callback=loaded.set)
				self.assertTrue(loaded.wait(5))
				self.assertTrue(request.settled.wait(5))
				self.assertEqual([('superseded', '')], outcomes)
			finally:
				release.set()
			self.assertTrue(retired.wait(5))
		self.drain(pane)
		self.assertEqual(as_url(self.root), pane.get_location())
		self.assertEqual([('superseded', '')], outcomes)

	def test_custom_filter_requires_snapshot_contract_without_replacing_model(self):
		pane = self.panes[0]
		old = self.run_in_app(pane._model.sourceModel)
		predicate = lambda url: url.endswith('.txt')
		with self.assertRaises(TypeError):
			self.run_in_app(pane._model.add_filter, predicate)
		predicate.snapshot_filter = lambda: lambda listing, index: listing.names[index].endswith('.txt')
		self.run_in_app(pane._model.add_filter, predicate)
		self.drain_model(pane._model)
		self.assertIs(old, self.run_in_app(pane._model.sourceModel))
		self.assertFalse(old._shutdown)
		self.assertEqual(1, self.run_in_app(pane._model.rowCount))

	def test_quick_view_retains_image_across_unchanged_snapshot_commits(self):
		from fman.impl.quick_view import QuickViewSession
		from fman.url import as_url
		from PyQt5.QtGui import QImage
		from unittest.mock import patch
		import os
		pane = self.panes[0]
		path = self.root / 'report.txt'
		pane.place_cursor_at(as_url(path))
		with patch('fman.load_json', return_value={}):
			session = self.run_in_app(QuickViewSession, self.window, pane, self.panes[1])
		def install_image():
			session.timer.stop()
			image = QImage(4, 4, QImage.Format_RGB32)
			image.fill(Qt.red)
			session.overlay.canvas.set_image(image)
			return session.generation
		generation = self.run_in_app(install_image)
		try:
			self.set_query('rep')
			pane.set_sort_column('core.Size', False)
			self.drain(pane)
			pane.reload()
			self.drain(pane)
			self.assertEqual(generation, self.run_in_app(lambda: session.generation))
			self.assertIsNotNone(self.run_in_app(lambda: session.overlay.canvas.image))
			modified = path.stat().st_mtime_ns + 2_000_000_000
			os.utime(path, ns=(modified, modified))
			pane.reload()
			self.drain(pane)
			self.assertGreater(self.run_in_app(lambda: session.generation), generation)
		finally:
			self.run_in_app(session.shutdown)

	def test_refresh_does_not_cancel_pending_navigation(self):
		from core.fs.local import LocalFileSystem
		from fman.url import as_url
		from unittest.mock import patch
		pane = self.panes[0]
		nested = self.root / 'nested'
		nested.mkdir()
		(nested / 'new.txt').touch()
		entered, release, loaded = Event(), Event(), Event()
		original = LocalFileSystem.scan
		def delayed(provider, path, check):
			if path == as_url(nested)[7:]:
				entered.set()
				if not release.wait(5):
					raise TimeoutError('Navigation scan not released')
			return original(provider, path, check)
		with patch.object(LocalFileSystem, 'scan', delayed):
			try:
				pane.set_location(as_url(nested), callback=loaded.set)
				self.assertTrue(entered.wait(5))
				(self.root / 'arrived.txt').touch()
				pane.reload()
				self.drain(pane)
				self.assertEqual(as_url(self.root), pane.get_location())
				self.assertEqual(7, self.run_in_app(pane._model.rowCount))
			finally:
				release.set()
			self.assertTrue(loaded.wait(5), 'Refresh canceled the requested navigation')
		self.drain(pane)
		self.assertEqual(as_url(nested), pane.get_location())
		self.assertEqual(1, self.run_in_app(pane._model.rowCount))

	def test_selection_rename_replacement_hidden_and_scope(self):
		from fman.url import as_url
		pane = self.panes[0]
		original = self.root / 'report.txt'
		renamed = self.root / 'renamed.txt'
		pane.place_cursor_at(as_url(original))
		pane.select([as_url(original)])
		original.rename(renamed)
		pane.reload()
		self.drain(pane)
		self.assertEqual([as_url(renamed)], pane.get_selected_files())
		self.assertEqual(as_url(renamed), pane.get_file_under_cursor())
		self.set_query('script')
		self.assertEqual([], pane.get_selected_files())
		self.set_query('')
		self.assertEqual([], pane.get_selected_files())
		pane.select([as_url(renamed)])
		renamed.rename(self.root / 'kept-object.txt')
		renamed.write_bytes(b'replacement')
		pane.reload()
		self.drain(pane)
		self.assertEqual([as_url(self.root / 'kept-object.txt')], pane.get_selected_files())
		self.assertNotIn(as_url(renamed), pane.get_selected_files())
		other = self.root / 'other'
		other.mkdir()
		(other / 'kept-object.txt').touch()
		self.navigate(pane, other)
		self.assertEqual([], pane.get_selected_files())

	def test_failed_scan_preserves_displayed_pane(self):
		from core.fs.local import LocalFileSystem
		from fman.url import as_url
		from unittest.mock import patch
		pane = self.panes[0]
		other = self.root / 'other'
		other.mkdir()
		failed = Event()
		def onerror(error, url):
			failed.set()
			return None
		with patch.object(LocalFileSystem, 'scan', side_effect=PermissionError('denied')):
			pane.set_location(as_url(other), onerror=onerror)
			self.assertTrue(failed.wait(5))
		self.assertEqual(as_url(self.root), pane.get_location())
		self.assertEqual(5, self.run_in_app(pane._model.rowCount))

	def close_window(self):
		def close():
			for pane in self.panes:
				pane._model.sourceModel().shutdown()
				pane._model._snapshot_scans.close()
				pane._model._snapshot_refreshes.close()
				pane._model._snapshot_views.close()
			self.window.close()
		self.run_in_app(close)
		self.run_in_app(self.window.deleteLater)
		self.errors.assert_not_called()

	def drain(self, pane):
		from time import monotonic
		deadline = monotonic() + 5
		while monotonic() < deadline:
			def settled():
				model = pane._model.sourceModel()
				return hasattr(model, '_committed_revision') and not model._scanning and not model._dirty \
					and model._committed_revision == model._revision
			if self.run_in_app(settled):
				return
		self.fail('Snapshot did not settle')

	def set_query(self, text, pane=None):
		pane = pane or self.panes[0]
		super().set_query(text, pane)
		self.drain(pane)

	def key(self, key, text='', pane=None):
		pane = pane or self.panes[0]
		result = super().key(key, text, pane)
		self.drain(pane)
		return result

	def status(self):
		for pane in self.panes:
			self.drain(pane)
		return super().status()

	def test_loading_navigation_and_retired_source(self):
		from core.fs.local import LocalFileSystem
		from fman.url import as_url
		from unittest.mock import patch
		pane = self.panes[0]
		old = self.run_in_app(pane._model.sourceModel)
		nested = self.root / 'nested'
		nested.mkdir()
		(nested / 'report.new').touch()
		entered, release, loaded = Event(), Event(), Event()
		original = LocalFileSystem.scan
		def delayed(provider, path, check):
			if path == as_url(nested)[7:]:
				entered.set()
				if not release.wait(5):
					raise TimeoutError('scan not released')
			return original(provider, path, check)
		with patch.object(LocalFileSystem, 'scan', delayed):
			try:
				pane.set_location(as_url(nested), callback=loaded.set)
				self.assertTrue(entered.wait(5))
				self.assertEqual(as_url(self.root), pane.get_location())
				self.set_query('rep')
				self.assertEqual('Filter "rep": 2 of 5 items', self.status())
			finally:
				release.set()
			self.assertTrue(loaded.wait(5))
		self.drain(pane)
		self.assertTrue(old._shutdown)
		self.assertEqual(as_url(nested / 'report.new'), pane.get_file_under_cursor())
		self.window.show_status_message('Unchanged')
		self.run_in_app(old.files_changed.emit)
		self.assertEqual('Unchanged', self.status())

	def test_bulk_selection_avoids_per_row_header_flags(self):
		from dataclasses import replace
		pane = self.panes[0]
		model = self.run_in_app(pane._model.sourceModel)
		listing = model._listing
		count = 2000
		large = replace(listing, names=tuple('file%06d.txt' % index for index in range(count)),
			is_dir=(False,) * count, sizes=(1,) * count, mtimes_ns=(listing.mtimes_ns[0],) * count,
			attributes=(32,) * count, created_ns=(1,) * count,
			identities=b''.join((index + 1).to_bytes(16, 'little') for index in range(count)))
		def install():
			model._listing = large
			model.update()
		self.run_in_app(install)
		self.drain(pane)
		self.set_query('!file001')
		self.assertEqual(1000, self.run_in_app(pane._model.rowCount))
		self.set_query('!file0019')
		self.assertEqual(1900, self.run_in_app(pane._model.rowCount))
		from unittest.mock import patch
		with patch.object(model, 'flags', wraps=model.flags) as flags:
			self.run_in_app(pane.select_all)
			self.run_in_app(pane._file_view.viewport().repaint)
			self.assertLess(flags.call_count, 1000)
		self.assertEqual(1900, self.run_in_app(lambda: sum(
			selection.bottom() - selection.top() + 1
			for selection in pane._file_view.selectionModel().selection())))
		def select_public_batch():
			view = pane._file_view
			view.clearSelection()
			changes = []
			def changed(*_):
				changes.append(True)
			view.selectionModel().selectionChanged.connect(changed)
			try:
				urls = [pane._model.url(pane._model.index(row, 0)) for row in range(pane._model.rowCount())]
				pane.select(urls)
				self.assertEqual(urls, pane.get_selected_files())
				self.assertEqual([True], changes)
			finally:
				view.selectionModel().selectionChanged.disconnect(changed)
		self.run_in_app(select_public_batch)

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
		window = self.run_in_app(MainWindow, Mock(), Mock(), Mock(), Mock(), 'null://')
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
		gui(stop)
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
		self.drain_model(widget._model)
		callbacks = []
		with patch.object(widget._model, 'set_extra_columns', side_effect=lambda *args: callbacks.append(args[-1])):
			widget.set_extra_columns(self.owner, {})
		self.run_in_app(model.shutdown)
		def dispose_and_deliver():
			sip.delete(widget)
			self.assertTrue(sip.isdeleted(widget._model))
			callbacks[0]()
		self.run_in_app(dispose_and_deliver)

	def test_toggle_notification_replacement_and_expiry_preserve_status_modes(self):
		from fman.impl.status_bar import DISABLED, ACTIVE_PANE
		from fman.impl.widgets import MainWindow
		from PyQt5.QtWidgets import QLabel
		from unittest.mock import Mock, patch
		window = self.run_in_app(MainWindow, Mock(), Mock(), Mock(), Mock(), 'null://')
		try:
			with patch('core.directory_size.save_json'), \
				patch('core.directory_size.scan_parents'), \
				patch('core.directory_size.show_status_message', side_effect=window.show_status_message):
				for mode in (DISABLED, ACTIVE_PANE):
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
		for column in (Name(), Size(), Modified(), NullColumn()):
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
			for widget in self.widgets:
				widget._model.shutdown()
			self.parent.close()
			self.parent.deleteLater()
		self.run_in_app(close)

	def drain_models(self):
		for widget in self.widgets:
			self.drain_model(widget._model)

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
				self.assertNotEqual(worker_threads[0], qt_thread)
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
		for column in (Name(), Size(), Modified(), NullColumn()):
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
			self.window = MainWindow(QApplication.instance(), Mock(), Mock(), self.filesystem, 'null://')
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
		self.assertEqual(3, self.provider.snapshot.call_count)
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
			for column in (Name(), Size(), Modified(), NullColumn()):
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
					model = widget._model
					model.shutdown()
					for dialog in dialogs:
						dialog.cancel()
					parent.close()
					parent.deleteLater()
					return model
				self.run_in_app(close)

class EverythingIT(QtIT):
	def test_native_picker_syntax_metadata_accept_and_cancel(self):
		from everything_search.instance import Settings, State
		from everything_search.ipc import Hit, Results, QueryTimeout
		from fman.impl.quicksearch import Quicksearch
		from fman.impl.theme import Theme
		from fman.url import as_url
		from pathlib import Path
		from PyQt5.QtCore import QThread, QTimer
		from PyQt5.QtTest import QTest
		from unittest.mock import Mock, patch
		import everything_search as commands
		app = QApplication.instance()
		pane = Mock()
		service = Mock(closed=False)
		service.manager.snapshot.return_value = State(1, 'ready', (42, 1, 'exe'))
		hit = Hit('C:\\Data\\sample.txt', False, 6, 0, tuple(range(8, 14)))

		def query(instance, identity, text, *args):
			self.assertEqual(app.thread(), QThread.currentThread())
			if text == 'busy':
				raise QueryTimeout()
			return Results(12345 if text == 'many' else 1, (hit,))

		service.client.query.side_effect = query
		def show(provider):
			self.assertEqual(app.thread(), QThread.currentThread())
			theme = Theme(Mock(), [])
			theme.load(str(Path(__file__).parents[3] / 'main/resources/base/Plugins/Core/Theme.css'))
			dialog = Quicksearch(None, app, theme.get_quicksearch_item_css(), provider)
			errors = []
			def inspect():
				try:
					dialog._query.setText('many')
					self.assertEqual('Showing 1 of 12,345', dialog._curr_items[-1].title)
					self.assertEqual(as_url(hit.path), dialog._curr_items[0].value)
					dialog._query.setText('busy')
					self.assertEqual('', dialog._curr_items[0].value)
					dialog._query.setText(accepted_query)
					item = dialog._curr_items[0]
					self.assertEqual(list(hit.highlight), item.highlight)
					self.assertTrue(item.description.strip())
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
		with patch.object(commands, '_read_settings', return_value=({}, Settings(folders=('C:\\Data',)))), \
				patch.object(commands, '_get_service', return_value=service), \
				patch.object(commands, 'show_quicksearch', side_effect=lambda provider: self.run_in_app(show, provider)):
			for accepted_query in ('*.txt dm:today', 'many'):
				for cancel in (False, True):
					pane.reset_mock()
					commands.SearchFileByEverything(pane)()
					if cancel:
						pane.run_command.assert_not_called()
					else:
						pane.run_command.assert_called_once_with('open_directory', {'url': as_url(hit.path)})
					self.assertEqual(accepted_query, service.client.query.call_args.args[2])

	def test_folder_persistence_delivery_and_unload_thread_affinity(self):
		from everything_search.instance import Manager
		from fman.impl.ui import UiOwner
		from pathlib import Path
		from PyQt5.QtCore import QThread
		from tempfile import TemporaryDirectory
		from threading import get_ident
		from unittest.mock import Mock, patch
		import json
		import everything_search as commands
		app = QApplication.instance()
		ready = Event()
		applied = []
		runtime = Mock()
		def apply(settings, canceled):
			self.assertNotEqual(app.thread(), QThread.currentThread())
			applied.append((settings.folders, get_ident()))
			return (42, 1, 'exe') if settings.folders else None
		runtime.apply.side_effect = apply
		def notification(text, **kwargs):
			self.assertEqual(app.thread(), QThread.currentThread())
			if text in ('Everything database is ready.', 'Everything database is stopped.'):
				ready.set()
		with TemporaryDirectory() as temporary:
			settings_path = Path(temporary) / 'Everything.json'
			settings_path.write_text(json.dumps({'folders': ['Z:\\Offline']}), encoding='utf-8')
			favorites = {'favorites': [
				{'name': 'Child', 'url': 'file://D:/Favorite/Child'},
				{'name': 'Parent', 'url': 'file://D:/Favorite/'},
				{'name': 'Duplicate', 'url': 'file://d:/FAVORITE'},
			]}
			def load(name, **kwargs):
				self.assertEqual(app.thread(), QThread.currentThread())
				if name == 'Favorites.json':
					return favorites
				return json.loads(settings_path.read_text(encoding='utf-8'))
			def save(name, value):
				self.assertEqual(app.thread(), QThread.currentThread())
				settings_path.write_text(json.dumps(value), encoding='utf-8')
			owner = UiOwner()
			service = commands.EverythingService(Mock(), owner)
			self.run_in_app(service.start)
			owner.attach(service.dispose)
			with patch.object(commands, 'Manager', side_effect=lambda directory, executable, notify, **kwargs:
					Manager(directory, executable, notify, Mock(return_value=runtime), **kwargs)), \
					patch.object(commands, 'load_json', side_effect=load), \
					patch.object(commands, 'save_json', side_effect=save), \
					patch.object(commands, '_default_folder', return_value=''), \
					patch.object(commands, '_validate_new_folder', side_effect=lambda path, allow_unavailable=False:
						commands.normalize_folder(path) if allow_unavailable else 'C:\\Added'), \
					patch.object(commands, 'show_prompt', return_value=('C:\\Added', True)), \
					patch.object(commands, 'show_status_message', side_effect=notification), \
					patch.object(commands, 'show_alert', return_value=commands.YES) as alert:
				try:
					commands.AddFolderToEverythingDatabase(Mock())()
					self.assertTrue(ready.wait(3))
					self.assertEqual(app.thread(), self.run_in_app(service.notifications.thread))
					ready.clear()
					commands.AddFavoritesToEverythingDatabase(Mock())()
					self.assertTrue(ready.wait(3))
					commands.AddFavoritesToEverythingDatabase(Mock())()
					self.assertEqual(2, len(applied))
					self.assertEqual(3, len(favorites['favorites']))
					for root in ('Z:\\Offline', 'C:\\Added', 'D:\\Favorite'):
						ready.clear()
						pane = Mock()
						pane.get_path.return_value = commands.FOLDERS_ROOT
						commands.RemoveEverythingFolders(pane)(urls=[commands.FOLDERS_ROOT + commands._folder_key(root)])
						self.assertTrue(ready.wait(3))
					self.assertEqual([], json.loads(settings_path.read_text(encoding='utf-8'))['folders'])
					self.assertEqual([('Z:\\Offline', 'C:\\Added'),
						('Z:\\Offline', 'C:\\Added', 'D:\\Favorite'),
						('C:\\Added', 'D:\\Favorite'), ('D:\\Favorite',), ()],
						[roots for roots, thread in applied])
					self.assertEqual(1, len({thread for roots, thread in applied}))
					self.assertEqual(3, alert.call_count)
				finally:
					self.run_in_app(owner.invalidate)
					service._cleanup_thread.join(3)
				self.assertTrue(service.closed)
				self.assertFalse(service.manager._thread.is_alive())
				runtime.close.assert_called_once_with(True)

	def test_empty_search_has_no_native_or_cleanup_worker(self):
		from everything_search.instance import Settings
		from fman.impl.ui import UiOwner
		from unittest.mock import Mock, patch
		import everything_search as commands
		with patch.object(commands, '_service'), patch.object(commands, 'Thread') as cleanup, \
				patch('everything_search.ipc.Thread') as ipc, patch('everything_search.instance.Thread') as manager:
			service = commands.EverythingService(Mock(), UiOwner())
			self.run_in_app(service.start)
			try:
				service.ensure(Settings())
			finally:
				self.run_in_app(service.dispose)
			for worker in (cleanup, ipc, manager):
				worker.assert_not_called()

	def test_ipc_preparation_and_shutdown_waits_stay_off_qt(self):
		from everything_search.instance import Manager, Settings
		from fman.impl.ui import UiOwner
		from PyQt5.QtCore import QThread
		from unittest.mock import Mock, patch
		import everything_search as commands
		ready, stopping, release = Event(), Event(), Event()
		runtime = Mock()
		runtime.apply.return_value = (42, 1, 'exe')
		client = Mock()
		def prepare():
			self.assertNotEqual(QApplication.instance().thread(), QThread.currentThread())
		def stop(exit_process):
			self.assertNotEqual(QApplication.instance().thread(), QThread.currentThread())
			stopping.set()
			release.wait(3)
		client.start.side_effect = prepare
		runtime.close.side_effect = stop
		owner = UiOwner()
		service = commands.EverythingService(Mock(), owner)
		with patch.object(commands, '_service'), patch.object(commands, 'IpcClient', return_value=client), \
				patch.object(commands, 'Manager', side_effect=lambda directory, executable, notify, **kwargs:
					Manager(directory, executable, lambda state: ready.set(), Mock(return_value=runtime), **kwargs)):
			self.run_in_app(service.start)
			owner.attach(service.dispose)
			try:
				service.ensure(Settings(folders=('C:\\Data',)))
				self.assertTrue(ready.wait(2))
				self.run_in_app(owner.invalidate)
				self.assertTrue(stopping.wait(2))
				self.assertTrue(service._cleanup_thread.is_alive())
				self.assertFalse(service._cleanup_thread.daemon)
				self.assertFalse(release.is_set())
				self.assertEqual('Qt responsive', self.run_in_app(lambda: 'Qt responsive'))
				client.start.assert_called_once()
				self.assertTrue(service.closed)
			finally:
				release.set()
				self.run_in_app(service.dispose)
				if service._cleanup_thread is not None:
					service._cleanup_thread.join(4)
			self.assertFalse(service.manager._thread.is_alive())
			self.assertFalse(service._cleanup_thread.is_alive())
			runtime.close.assert_called_once_with(True)

	def test_root_mutations_reject_disposal_during_validation_or_confirmation(self):
		from fman.impl.ui import UiOwner
		from unittest.mock import Mock, patch
		import everything_search as commands
		for operation in ('drop', 'prompt', 'favorites', 'remove', 'replace_parent'):
			with self.subTest(operation=operation), patch.object(commands, '_service'):
				owner = UiOwner()
				service = commands.EverythingService(Mock(), owner)
				self.run_in_app(service.start)
				owner.attach(service.dispose)
				pane = Mock()
				pane.get_path.return_value = commands.FOLDERS_ROOT
				provider = commands.EverythingFolders()
				def invalidate(*args, **kwargs):
					self.run_in_app(owner.invalidate)
					return 'C:\\Data'
				def confirm(*args):
					invalidate()
					return commands.YES
				data = {'folders': ['C:\\Data\\Child']}
				with patch.object(commands, 'load_json', return_value=data), \
						patch.object(commands, 'save_json') as save, \
						patch.object(commands, '_get_service') as activate, \
						patch.object(provider, 'notify_file_changed') as notify, \
						patch.object(commands, '_default_folder', return_value=''), \
						patch.object(commands, 'show_prompt', return_value=('C:\\Data', True)), \
						patch.object(commands, '_favorite_snapshot', return_value=(('file://C:/Data',), 0)), \
						patch.object(commands, '_validate_new_folder', side_effect=invalidate if operation in
							('drop', 'prompt', 'favorites') else lambda *args: 'C:\\Data'), \
						patch.object(commands, 'show_alert', side_effect=confirm) as alert, \
						patch.object(commands, 'show_status_message') as status, \
						patch.object(commands, 'submit_task', side_effect=lambda task: task()):
					if operation == 'drop':
						commands.AddEverythingFolders(pane)(files=['file://C:/Data'], dest_dir=commands.FOLDERS_ROOT)
					elif operation == 'favorites':
						commands.AddFavoritesToEverythingDatabase(pane)()
					elif operation == 'remove':
						commands.RemoveEverythingFolders(pane)(urls=[commands.FOLDERS_ROOT + commands._folder_key(data['folders'][0])])
					else:
						commands.AddFolderToEverythingDatabase(pane)()
					self.assertFalse(owner.active)
					self.assertTrue(service.closed)
					for effect in (save, activate, notify, status):
						effect.assert_not_called()
					self.assertEqual(int(operation in ('remove', 'replace_parent')), alert.call_count)

	def test_plugin_loader_commands_binding_and_unused_lifecycle(self):
		from fman import PLATFORM, Window
		from fman.impl.plugins.command_registry import ApplicationCommandRegistry, PaneCommandRegistry
		from fman.impl.plugins.config import Config
		from fman.impl.plugins.context_menu import ContextMenuProvider
		from fman.impl.plugins.key_bindings import KeyBindings
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from fman.impl.plugins.plugin import ExternalPlugin
		from fman_integrationtest.impl.plugins import StubCommandCallback, StubFontDatabase, StubTheme
		from fman_unittest.impl.plugins import StubErrorHandler
		from pathlib import Path
		from unittest.mock import Mock
		def check():
			errors = StubErrorHandler()
			callback = StubCommandCallback()
			pane_registry = PaneCommandRegistry(errors, callback)
			window = Window(None, pane_registry)
			application_registry = ApplicationCommandRegistry(window, errors, callback)
			bindings = KeyBindings()
			path = Path(__file__).parents[3] / 'main/resources/base/Plugins/Everything'
			plugin = ExternalPlugin(str(path), Config(PLATFORM), StubTheme(), StubFontDatabase(),
				ContextMenuProvider(pane_registry, application_registry, bindings), errors,
				application_registry, pane_registry, bindings, MotherFileSystem(None), window)
			self.assertTrue(plugin.load(), errors.error_messages)
			import everything_search
			service = everything_search._service
			try:
				visible = {'search_file_by_everything', 'add_folder_to_everything_database',
					'add_favorites_to_everything_database', 'manage_everything_folders'}
				hidden = {'remove_everything_folders', 'open_everything_folder',
					'copy_everything_folder_paths', 'add_everything_folders', 'everything_folder_operation_unsupported'}
				self.assertEqual(visible | hidden, pane_registry.get_commands())
				self.assertEqual(visible, {name for name in pane_registry.get_commands()
					if pane_registry.is_command_visible(name, Mock())})
				self.assertEqual(('Search file by Everything',),
					pane_registry.get_command_aliases('search_file_by_everything'))
				self.assertEqual(('Add folder to Everything database',),
					pane_registry.get_command_aliases('add_folder_to_everything_database'))
				self.assertEqual(('Add favorite folders to Everything database',),
					pane_registry.get_command_aliases('add_favorites_to_everything_database'))
				self.assertEqual(('Manage Everything database folders',),
					pane_registry.get_command_aliases('manage_everything_folders'))
				self.assertIn({'keys': ['Ctrl+E'], 'command': 'search_file_by_everything'},
					bindings.get_sanitized_bindings())
				self.assertIsNone(service.manager)
				self.assertIsNone(service.client)
				self.assertIsNone(service.notifications)
			finally:
				plugin.unload()
			self.assertTrue(service.closed)
			self.assertFalse(service.owner.active)
			self.assertFalse(errors.error_messages, errors.error_messages)
		self.run_in_app(check)


class EverythingFoldersIT(QtIT):
	def setUp(self):
		from core import Name, Size, Modified
		from core.commands import Open, OpenDirectory, OpenListener, MoveToTrash, DeletePermanently, \
			Copy, Move, Rename, CopyPathsToClipboard, DragAndDropListener
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
		from search_file_fuzzy import SearchFilesInCurrentFolder
		from pathlib import Path
		from PyQt5.QtGui import QIcon
		from PyQt5.QtCore import QThread
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		import json
		import sys
		previous = {name: module for name, module in sys.modules.items()
			if name == 'everything_search' or name.startswith('everything_search.')}
		self.addCleanup(sys.modules.update, previous)
		temporary = TemporaryDirectory()
		self.addCleanup(temporary.cleanup)
		self.root = Path(temporary.name).resolve()
		for name in ('Alpha', 'Beta', 'Gamma'):
			(self.root / name).mkdir()
		(self.root / 'sample.txt').write_text('untouched', encoding='utf-8')
		self.saved = {'folders': [str(self.root / 'Alpha'), str(self.root / 'Beta'), 'Z:\\Offline']}
		self.errors = Mock()
		self.finished = Event()
		callbacks = Mock()
		callbacks.after_command.side_effect = lambda *args: self.finished.set()
		self.filesystem = MotherFileSystem(Mock(get_icon=Mock(return_value=QIcon())))
		for backend in (LocalFileSystem(), NullFileSystem()):
			self.filesystem.add_child(backend.scheme, FileSystemWrapper(backend, self.filesystem, self.errors))
		for column in (Name(), Size(), Modified(), NullColumn()):
			self.filesystem.register_column(column.get_qualified_name(), column)
		applications, commands = self.run_in_app(lambda: (
			ApplicationCommandRegistry(Mock(), self.errors, callbacks), PaneCommandRegistry(self.errors, callbacks)))
		bindings = KeyBindings()
		for name, command in (('open', Open), ('open_directory', OpenDirectory), ('move_to_trash', MoveToTrash),
				('delete_permanently', DeletePermanently), ('copy', Copy), ('move', Move), ('rename', Rename),
				('copy_paths_to_clipboard', CopyPathsToClipboard), ('search_files_in_current_folder', SearchFilesInCurrentFolder)):
			commands.register_command(name, command)
			bindings.register_command(name)
		plugins = Path(__file__).parents[3] / 'main/resources/base/Plugins'
		with (plugins / 'Core/Key Bindings.json').open(encoding='utf-8') as stream:
			self.assertEqual([], bindings.load([entry for entry in json.load(stream)
				if entry['command'] in commands.get_commands()]))
		config, context = Config('Windows'), Mock()
		plugin = ExternalPlugin(str(plugins / 'Everything'), config, Mock(), Mock(), context,
			self.errors, applications, commands, bindings, self.filesystem, Mock())
		self.support = PluginSupport(lambda path: plugin, applications, bindings, context, config)
		self.plugin_path = str(plugins / 'Everything')
		self.assertTrue(self.support.load_plugin(self.plugin_path))
		self.module = sys.modules['everything_search']
		def load(*args, **kwargs):
			self.assertEqual(QApplication.instance().thread(), QThread.currentThread())
			return dict(self.saved, folders=list(self.saved['folders']))
		def save(name, value):
			self.assertEqual(QApplication.instance().thread(), QThread.currentThread())
			self.saved = value
		for target, options in (
			('everything_search.load_json', {'side_effect': load}),
			('everything_search.save_json', {'side_effect': save}),
			('everything_search._get_service', {}),
			('everything_search.show_alert', {'return_value': self.module.NO}),
			('everything_search.show_status_message', {}),
			('everything_search.submit_task', {'side_effect': lambda task: task()}),
			('fman.fs._get_mother_fs', {'return_value': self.filesystem}),
		):
			patcher = patch(target, **options)
			patcher.start()
			self.addCleanup(patcher.stop)
		self.controller = Controller(self.support, Mock(), Mock(), Mock())
		def create():
			self.window = MainWindow(QApplication.instance(), Mock(), Mock(), self.filesystem, 'null://')
			self.window.set_controller(self.controller)
			self.panes = [self.window.add_pane() for index in range(2)]
			public_window = Mock()
			self.public_panes = [DirectoryPane(public_window, widget, commands) for widget in self.panes]
			public_window.get_panes.return_value = self.public_panes
			for widget, pane in zip(self.panes, self.public_panes):
				pane._add_listener(DragAndDropListener(pane))
				pane._add_listener(OpenListener(pane))
				self.controller.register_pane(widget, pane)
			self.window.resize(960, 600)
			self.window.show()
		self.run_in_app(create)
		self.addCleanup(self.close_window)
		self.addCleanup(self.unload_plugin)
		for pane in self.panes:
			FilterBarIT.navigate(self, pane, self.root)

	drain = FilterBarIT.drain
	close_window = FilterBarIT.close_window
	set_query = FilterBarIT.set_query

	def unload_plugin(self):
		self.support.unload_plugin(self.plugin_path)
		for pane in self.panes:
			self.drain(pane)
		self.errors.report.assert_not_called()

	def manage(self, index=0):
		self.public_panes[index].run_command('manage_everything_folders')
		self.drain(self.panes[index])
		self.assertEqual(self.module.FOLDERS_ROOT, self.public_panes[index].get_path())
		self.errors.report.assert_not_called()

	def row_url(self, path):
		return self.module.FOLDERS_ROOT + self.module._folder_key(str(path))

	def press(self, index, key):
		from PyQt5.QtCore import QEvent
		from PyQt5.QtGui import QKeyEvent
		self.finished.clear()
		self.assertTrue(self.run_in_app(self.controller.handle_shortcut, self.panes[index],
			QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)))
		self.assertTrue(self.finished.wait(5), 'Manager action did not finish')
		for pane in self.panes:
			self.drain(pane)
		self.errors.report.assert_not_called()

	def test_filter_fuzzy_sort_bulk_remove_and_cross_pane_selection(self):
		from unittest.mock import patch
		self.manage(0)
		self.manage(1)
		self.module._get_service.assert_not_called()
		self.assertEqual(['core.Name', 'everything_search.IndexedFolderPath'], list(self.public_panes[0].get_columns()))
		self.set_query('off')
		self.assertEqual(1, self.run_in_app(self.panes[0]._model.rowCount))
		self.set_query('')
		self.public_panes[0].set_sort_column('everything_search.IndexedFolderPath')
		self.drain(self.panes[0])
		with patch('search_file_fuzzy.load_json', return_value={}), \
				patch('search_file_fuzzy.show_status_message'), patch('search_file_fuzzy.clear_status_message'), \
				patch('search_file_fuzzy.show_quicksearch', return_value=None) as picker:
			self.public_panes[0].run_command('search_files_in_current_folder', {'query': 'Alpha'})
			self.assertEqual([self.row_url(self.root / 'Alpha')],
				[item.value for item in picker.call_args.args[0]('Alpha')])
		beta = self.row_url(self.root / 'Beta')
		self.public_panes[0].toggle_selection(beta)
		for path in (self.root / 'Alpha', 'Z:\\Offline'):
			self.public_panes[1].toggle_selection(self.row_url(path))
		self.press(1, Qt.Key_F8)
		self.module.save_json.assert_not_called()
		self.assertEqual(self.module.NO, self.module.show_alert.call_args.args[2])
		self.module.show_alert.return_value = self.module.YES
		self.press(1, Qt.Key_F8)
		self.assertEqual([str(self.root / 'Beta')], self.saved['folders'])
		self.module.save_json.assert_called_once()
		self.module._get_service.assert_called_once()
		for pane in self.panes:
			self.assertEqual(1, self.run_in_app(pane._model.rowCount))
		self.assertEqual([beta], self.public_panes[0].get_selected_files())
		self.assertTrue((self.root / 'Alpha').is_dir())
		with patch.object(self.module.clipboard, 'clear'), patch.object(self.module.clipboard, 'set_text') as copy:
			self.press(0, Qt.Key_F11)
			copy.assert_called_once_with(str(self.root / 'Beta'))

	def test_f5_drop_navigation_and_refusal_do_not_mutate_target_files(self):
		from core.commands import DragAndDropListener
		from fman.url import as_url
		self.manage(0)
		self.public_panes[1].place_cursor_at(as_url(self.root / 'Gamma'))
		self.press(1, Qt.Key_F6)
		self.module.save_json.assert_not_called()
		self.press(1, Qt.Key_F5)
		self.module.save_json.assert_called_once()
		self.assertIn(str(self.root / 'Gamma'), self.saved['folders'])
		self.assertEqual(4, self.run_in_app(self.panes[0]._model.rowCount))
		DragAndDropListener(self.public_panes[0]).on_files_dropped(
			[as_url(self.root / 'Gamma'), as_url(self.root / 'sample.txt')],
			self.row_url(self.root / 'Beta'), False)
		self.drain(self.panes[0])
		self.module.save_json.assert_called_once()
		for command in ('copy', 'move', 'rename'):
			self.public_panes[0].run_command(command)
		self.module.save_json.assert_called_once()
		self.public_panes[0].place_cursor_at(self.row_url(self.root / 'Alpha'))
		self.press(0, Qt.Key_Return)
		self.assertEqual(as_url(self.root / 'Alpha'), self.public_panes[0].get_path())
		self.assertEqual('untouched', (self.root / 'sample.txt').read_text(encoding='utf-8'))
		self.assertEqual({'Alpha', 'Beta', 'Gamma', 'sample.txt'}, {path.name for path in self.root.iterdir()})


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
				return getattr(self, 'location', 'test://root')
			def get_listing(self):
				return getattr(self, 'listing', None)
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

	def test_two_panes_capture_hidden_visibility_before_snapshot_or_recursive_search(self):
		import ctypes
		from fman import DirectoryPane, Window
		from fman.listing import Listing
		from fman.url import as_url
		from search_file_fuzzy import SearchFilesInCurrentFolder, SearchFilesRecursively
		from PyQt5 import sip
		from PyQt5.QtCore import QThread
		from pathlib import Path
		from stat import FILE_ATTRIBUTE_HIDDEN
		from tempfile import TemporaryDirectory
		from unittest.mock import patch
		other_widget = self.run_in_app(type(self.widget))
		self.addCleanup(self.run_in_app, sip.delete, other_widget)
		window = Window(None, self.registry)
		self.pane.window = window
		other_pane = DirectoryPane(window, other_widget, self.registry)
		window.get_panes().extend((self.pane, other_pane))
		loads = []
		def settings(name, default=None):
			self.assertNotEqual(QApplication.instance().thread(), QThread.currentThread())
			loads.append(name)
			return ([{'show_hidden_files': True}, {'show_hidden_files': False}]
				if name == 'Panes.json' else {'include_hidden': not hidden})
		def show(get_items, query=''):
			def inspect():
				self.assertEqual(QApplication.instance().thread(), QThread.currentThread())
				with patch('search_file_fuzzy.load_json', side_effect=AssertionError('Query settings I/O')), \
						patch('search_file_fuzzy.indexer.os.scandir', side_effect=AssertionError('Query scan')):
					self.assertCountEqual(expected, [item.title for item in get_items('')])
					self.assertEqual(['.gitignore'], [item.title for item in get_items('gitignore')])
			self.run_in_app(inspect)
		set_attributes = ctypes.windll.kernel32.SetFileAttributesW
		set_attributes.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
		set_attributes.restype = ctypes.c_bool
		with TemporaryDirectory() as temporary:
			root = Path(temporary)
			names = ('visible.txt', 'hidden.txt', '.gitignore')
			for name in names:
				(root / name).touch()
			hidden_path = root / 'hidden.txt'
			attributes = hidden_path.stat().st_file_attributes
			try:
				self.assertTrue(set_attributes(str(hidden_path), attributes | FILE_ATTRIBUTE_HIDDEN))
				for widget in (self.widget, other_widget):
					self.run_in_app(setattr, widget, 'location', as_url(root))
					self.run_in_app(setattr, widget, 'listing', Listing.create(as_url(root),
						names, attributes=(0, FILE_ATTRIBUTE_HIDDEN, 0)))
				with patch('search_file_fuzzy.load_json', side_effect=settings), \
						patch('search_file_fuzzy.show_quicksearch', side_effect=show):
					for pane, hidden in zip(window.get_panes(), (True, False)):
						expected = list(names) if hidden else ['visible.txt', '.gitignore']
						for command in (SearchFilesInCurrentFolder, SearchFilesRecursively):
							for metadata in (False, True):
								with self.subTest(hidden=hidden, command=command.__name__, metadata=metadata):
									loads.clear()
									command(pane)(metadata=metadata)
									self.assertEqual(['SearchFileFuzzy.json', 'Panes.json'], loads)
									self.assertEqual(0, self.run_in_app(pane._widget.receivers,
										pane._widget.location_changed))
			finally:
				set_attributes(str(hidden_path), attributes)

	def test_reserved_rows_reorder_filter_accept_and_cancel(self):
		from fman.impl.quicksearch import Quicksearch
		from fman.impl.theme import Theme
		from fman.listing import Listing
		from search_file_fuzzy import SearchFilesInCurrentFolder, describe_metadata
		from search_file_fuzzy.indexer import IndexResult
		from search_file_fuzzy.matcher import SearchEntry
		from PyQt5.QtCore import QThread, QTimer
		from PyQt5.QtTest import QTest
		from PyQt5.QtWidgets import QStyleOptionViewItem
		from pathlib import Path
		from itertools import product
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
					for text in ('', 'rpt', 'report', '^second .txt$', '^first', 'missing', ''):
						dialog._query.setText(text)
						if text == 'rpt':
							self.assertEqual(2, len(dialog._curr_items))
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
			for snapshot, values in product((False, True), ((0, None), (None, 0), (None, None))):
				entries = [SearchEntry('test://root/' + name, name, name, size,
					1_800_000_000_000_000_000 if size is not None else None)
					for name, size in zip(('first-report.txt', 'second-report.txt'), values)]
				listing = Listing.create('test://root', tuple(entry.name for entry in entries),
					sizes=values, mtimes_ns=tuple(entry.modified_ns for entry in entries)) if snapshot else None
				self.run_in_app(setattr, self.widget, 'listing', listing)
				build.reset_mock()
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
				if snapshot:
					build.assert_not_called()

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

class RobocopyIT(QtIT):
	close_window = FilterBarIT.close_window
	navigate = FilterBarIT.navigate
	drain = FilterBarIT.drain

	def setUp(self):
		from fman import DirectoryPane, Window
		from fman.impl.plugins.discover import find_plugin_dirs
		from fman.impl.theme import Theme
		from fman_integrationtest.impl.plugins.test_plugin import ExternalPluginTest
		from fman_unittest.robocopy_fixture import PLUGIN_ROOT
		from pathlib import Path
		from shutil import copytree
		from unittest.mock import Mock, patch
		FilterBarIT.setUp(self)
		self.destination = self.root / 'destination'
		self.destination.mkdir()
		self.navigate(self.panes[1], self.destination)
		fixture = self.fixture = ExternalPluginTest()
		self.run_in_app(fixture.setUp)
		self.addCleanup(fixture.tearDown)
		installed = self.root / 'resources' / 'Plugins' / 'Robocopy'
		copytree(PLUGIN_ROOT, installed, ignore=__import__('shutil').ignore_patterns('__pycache__'))
		discovered = find_plugin_dirs(str(installed.parent),
			str(self.root / 'UserSettings/Plugins/Third-party'), str(self.root / 'UserSettings/Plugins/User'))
		self.assertIn(str(installed), discovered)
		fixture._plugin._path = next(path for path in discovered if Path(path).name == 'Robocopy')
		self.assertTrue(fixture._plugin.load(), fixture._error_handler.error_messages)
		self.loaded = True
		self.addCleanup(self.unload)
		import robocopy_plugin
		self.plugin = robocopy_plugin
		public_window = Window(self.window, fixture._panecmd_registry)
		self.public_panes = [DirectoryPane(public_window, pane, fixture._panecmd_registry) for pane in self.panes]
		public_window._panes = self.public_panes
		for pane in self.public_panes:
			fixture._plugin.on_pane_added(pane)
		self.accepted_path = None
		self.cancel_wizard = False
		self.wizard_count = 0
		self.dialog_errors = []
		self.progress = []
		self.alerts = []
		self.seeds = []
		def prepare():
			theme = Theme(Mock(), [])
			theme.load(str(Path(__file__).parents[3] / 'main/resources/base/Plugins/Core/Theme.css'))
			self.window._theme = theme
			self.window._progress_bar_palette = QApplication.instance().palette()
			self.window.before_dialog.connect(self.answer)
		self.run_in_app(prepare)
		original = self.window.create_progress_dialog
		def create(*args):
			dialog = original(*args)
			self.progress.append(dialog)
			return dialog
		for target, kwargs in (
			('fman._get_ui', {'return_value': self.window}),
			('fman._get_plugin_support', {'return_value': fixture._config}),
			('fman.DATA_DIRECTORY', {'new': str(self.root / 'settings')}),
			('fman.show_alert', {'side_effect': self.alerts.append})):
			patcher = patch(target, **kwargs)
			patcher.start()
			self.addCleanup(patcher.stop)
		patcher = patch.object(self.window, 'create_progress_dialog', side_effect=create)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(lambda: self.assertEqual([], self.dialog_errors))

	def unload(self):
		if self.loaded:
			self.run_in_app(self.fixture._plugin.unload)
			self.loaded = False

	def answer(self, dialog):
		from fman.impl.quicksearch import Quicksearch
		from PyQt5.QtCore import QThread, QTimer
		def respond():
			try:
				self.assertIsInstance(dialog, Quicksearch)
				self.assertEqual(QApplication.instance().thread(), QThread.currentThread())
				self.wizard_count += 1
				self.seeds.append(dialog._query.text())
				if self.cancel_wizard:
					dialog.reject()
				else:
					if self.accepted_path is not None:
						dialog._query.setText(str(self.accepted_path))
					self.assertEqual(dialog._query.text(), dialog._curr_items[0].value)
					dialog._on_return_pressed()
			except BaseException as error:
				self.dialog_errors.append(error)
				dialog.reject()
		QTimer.singleShot(0, respond)

	def choose(self, *names):
		from fman.url import as_url
		pane = self.public_panes[0]
		pane.clear_selection()
		pane.select(tuple(as_url(self.root / name) for name in names))

	def test_progress_text_fits_and_status_stays_on_one_line(self):
		from importlib import import_module
		from pathlib import Path
		from fman.impl.theme import Theme
		from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
		from PyQt5.QtWidgets import QLabel, QProgressBar, QPushButton
		from unittest.mock import Mock, patch
		engine = import_module('robocopy_plugin.engine')
		task = self.plugin._Transfer('Copy with robocopy', '', (), '', engine.Settings(), False, Event())
		dialog = self.window.create_progress_dialog(task.get_title(), 0)
		task._dialog = dialog
		self.progress_snapshots = {}
		def style():
			resources = Path(__file__).parents[3] / 'main/resources'
			theme = Theme(Mock(set_style_sheet=self.window.setStyleSheet),
				[str(resources / 'base/styles.qss'), str(resources / 'windows/os_styles.qss')])
			theme.load(str(resources / 'base/Plugins/Core/Theme.css'))
			theme.enable_updates()
			dialog.setMinimumDuration(0)
		self.run_in_app(style)
		try:
			for name in ('Quarterly reports', '\u754c' * 100):
				entry = engine.Source('C:\\source\\' + name, name, True, (1, 2, 3))
				job = engine.Job(entry.path, 'D:\\target', (entry,))
				task.current_job = job
				task.plan = Mock(jobs=(job, job))
				task.started_at = 0
				with patch.object(self.plugin, 'monotonic', return_value=70):
					task.activity('\tNew File\t82150C:\\bad\ufffdpath')
				def inspect():
					dialog._update()
					dialog.show()
					QApplication.processEvents()
					label = dialog.findChild(QLabel)
					bar = dialog.findChild(QProgressBar)
					button = dialog.findChild(QPushButton)
					self.assertLessEqual(dialog.width(), 640)
					self.assertEqual(0, bar.maximum())
					self.assertEqual(2, len(label.text().splitlines()))
					for line in label.text().splitlines():
						self.assertLessEqual(label.fontMetrics().horizontalAdvance(line), label.contentsRect().width())
					self.assertLessEqual(label.fontMetrics().lineSpacing() * 2, label.contentsRect().height())
					self.assertLess(label.geometry().bottom(), bar.geometry().top())
					self.assertLess(bar.geometry().bottom(), button.geometry().top())
					image = QByteArray()
					buffer = QBuffer(image)
					buffer.open(QIODevice.WriteOnly)
					self.assertTrue(dialog.grab().save(buffer, 'PNG'))
					return dialog.width(), bytes(image)
				width, image = self.run_in_app(inspect)
				self.progress_snapshots['unicode' if name.startswith('\u754c') else 'folder'] = image
				with patch.object(self.plugin, 'monotonic', return_value=71):
					task.activity('x' * 5000)
				self.assertEqual(width, self.run_in_app(inspect)[0])
			self.run_in_app(dialog.request_cancel)
			with self.assertRaises(task.Canceled):
				task.activity('Late output')
			self.assertEqual('Canceling...', dialog._text)
		finally:
			self.run_in_app(dialog.cancel)
			self.run_in_app(dialog.deleteLater)
		def baseline():
			self.window.resize(960, 600)
			self.window.layout().activate()
			QApplication.processEvents()
			return self.window.width(), self.window.statusBar().height()
		width, height = self.run_in_app(baseline)
		task.codes.extend((1, 1))
		task.log = Mock(path=Path('C:/logs/' + 'long-folder/' * 50 + 'transfer.txt'))
		self.plugin._present(task, self.plugin.ui.UiOwner(), Event())
		def inspect_status():
			QApplication.processEvents()
			label = self.window._status_bar_text
			self.assertNotIn('\n', label.text())
			self.assertNotIn('Log:', label.text())
			self.assertLessEqual(label.fontMetrics().horizontalAdvance(label.text()), label.contentsRect().width())
			self.assertEqual(width, self.window.width())
			self.assertEqual(height, self.window.statusBar().height())
		self.run_in_app(inspect_status)

	def test_discovery_real_wizard_copy_and_final_pane_snapshot(self):
		self.assertEqual({'copy_with_robocopy', 'move_with_robocopy'}, self.fixture._panecmd_registry.get_commands())
		self.choose('report.txt', 'script.py')
		self.public_panes[0].run_command('copy_with_robocopy')
		self.assertEqual([str(self.destination)], self.seeds)
		self.assertEqual([], self.alerts)
		self.assertEqual({'report.txt', 'script.py'}, {path.name for path in self.destination.iterdir()})
		self.drain(self.panes[1])
		self.assertEqual(2, self.run_in_app(self.panes[1]._model.rowCount))
		self.assertEqual(0, self.run_in_app(self.progress[0].maximum))
		self.assertFalse(self.run_in_app(self.progress[0].isVisible))
		self.assertFalse((self.root / 'settings').exists())

	def test_navigation_during_transfer_does_not_retarget_or_restore_panes(self):
		from fman.url import as_url
		from unittest.mock import patch
		other = self.root / 'other'
		other.mkdir()
		self.choose('report.txt')
		submit = self.plugin.fman.submit_task
		def navigate_then_submit(task):
			self.navigate(self.panes[0], other)
			self.navigate(self.panes[1], other)
			submit(task)
		with patch.object(self.plugin.fman, 'submit_task', side_effect=navigate_then_submit):
			self.public_panes[0].run_command('copy_with_robocopy')
		self.assertEqual([], self.alerts)
		self.assertTrue((self.destination / 'report.txt').exists())
		self.assertEqual([], list(other.iterdir()))
		self.assertEqual([as_url(other), as_url(other)], [pane.get_path() for pane in self.public_panes])

	def test_move_of_displayed_directory_refreshes_without_stale_location(self):
		from fman.url import as_url
		folder = self.root / 'Folder'
		folder.mkdir()
		(folder / 'file.txt').write_bytes(b'file')
		self.panes[0].reload()
		self.drain(self.panes[0])
		self.navigate(self.panes[1], folder)
		self.choose('Folder')
		self.accepted_path = self.destination
		restored = Event()
		self.addCleanup(self.public_panes[1].on_path_changed(restored.set))
		self.public_panes[0].run_command('move_with_robocopy')
		self.assertEqual([], self.alerts)
		self.assertTrue((self.destination / 'Folder' / 'file.txt').exists())
		self.assertFalse(folder.exists())
		self.assertTrue(restored.wait(5), 'Deleted-folder navigation did not finish')
		self.drain(self.panes[1])
		self.assertEqual(as_url(self.root), self.public_panes[1].get_path())
		self.assertNotIn('Folder', self.public_panes[1].get_listing().names)

	def test_wizard_cancel_and_typed_destination_cursor_fallback(self):
		from fman.url import as_url
		from unittest.mock import patch
		self.public_panes[0].clear_selection()
		self.public_panes[0].place_cursor_at(as_url(self.root / 'report.txt'))
		self.cancel_wizard = True
		with patch.object(self.plugin.fman, 'submit_task') as submit:
			self.public_panes[0].run_command('move_with_robocopy')
			submit.assert_not_called()
		self.cancel_wizard = False
		self.accepted_path = self.root / 'typed destination'
		self.public_panes[0].run_command('move_with_robocopy')
		self.assertFalse((self.root / 'report.txt').exists())
		self.assertTrue((self.accepted_path / 'report.txt').exists())
		self.assertEqual([], self.alerts)
		self.assertEqual(as_url(self.destination), self.public_panes[1].get_path())
		self.drain(self.panes[0])
		self.assertNotIn('report.txt', self.public_panes[0].get_listing().names)

	def test_log_viewer_after_real_progress_closure_and_lease_release(self):
		from pathlib import Path
		from unittest.mock import patch
		self.choose('report.txt')
		def view(path):
			self.assertTrue(self.run_in_app(lambda: all(not dialog.isVisible() for dialog in self.progress)))
			release = self.plugin.ui.settings_resource('Robocopy operation').try_claim()
			self.assertIsNotNone(release)
			release()
			self.assertIn('Robocopy finished', Path(path).read_text(encoding='utf-16'))
			raise OSError('Viewer fixture failure')
		with patch.object(self.plugin.fman, 'load_json', return_value={'log_enabled': True, 'open_log_on_finish': True}), \
				patch.object(self.plugin.os, 'startfile', side_effect=view) as viewer:
			self.public_panes[0].run_command('copy_with_robocopy')
			viewer.assert_called_once()
		self.assertEqual(1, len(self.alerts))
		self.assertIn('finished: 1/1', self.alerts[0])
		self.assertIn('Viewer fixture failure', self.alerts[0])

	def test_quiet_owned_child_cancel_and_unload_keep_lease_until_reaped(self):
		from importlib import import_module
		from unittest.mock import patch
		engine = import_module('robocopy_plugin.engine')
		windows = import_module('robocopy_plugin.windows')
		self.choose('report.txt')
		real_run, real_process = windows.run, windows.OwnedProcess
		children = []
		for unload in (False, True):
			with self.subTest(unload=unload):
				def launch(arguments, cwd=None):
					child = real_process([sys.executable, '-B', '-c', 'from threading import Event; Event().wait()'])
					children.append(child)
					self.assertEqual(0, self.run_in_app(self.progress[-1].maximum))
					self.plugin.MoveWithRobocopy(self.public_panes[0])()
					self.assertIn('already active', self.run_in_app(self.window._status_bar_text.text))
					self.assertIsNone(self.plugin.ui.settings_resource('Robocopy operation').try_claim())
					if unload:
						self.unload()
					else:
						self.run_in_app(self.progress[-1].request_cancel)
						self.assertEqual('Canceling...', self.progress[-1]._text)
					return child
				with patch.object(engine, 'probe'), patch.object(windows, 'OwnedProcess', side_effect=launch), \
						patch.object(self.plugin.fman, 'load_json', return_value={'log_enabled': True, 'open_log_on_finish': True}), \
						patch.object(self.plugin.os, 'startfile') as viewer:
					self.plugin.CopyWithRobocopy(self.public_panes[0])()
					if unload:
						viewer.assert_not_called()
					else:
						viewer.assert_called_once()
				self.assertFalse(children[-1].reader.is_alive())
				self.assertIsNone(children[-1].process)
				release = self.plugin.ui.settings_resource('Robocopy operation').try_claim()
				self.assertIsNotNone(release)
				release()
				if not unload:
					self.assertEqual('Canceling...', self.progress[-1]._text)
		self.assertEqual(1, len(self.alerts))
		self.assertIn('canceled', self.alerts[0])
		self.assertEqual(2, self.wizard_count)
		self.assertEqual([], list(self.destination.iterdir()))
		logs = list((self.root / 'settings' / 'Local' / 'Robocopy' / 'Logs').glob('*.txt'))
		self.assertEqual(2, len(logs))
		for log in logs:
			self.assertIn('[Robocopy transfer finished]', log.read_text(encoding='utf-16'))

	def test_pane_destruction_cancels_child_without_late_alert_or_viewer(self):
		from importlib import import_module
		from PyQt5 import sip
		from unittest.mock import patch
		engine = import_module('robocopy_plugin.engine')
		windows = import_module('robocopy_plugin.windows')
		self.choose('report.txt')
		real_process = windows.OwnedProcess
		children = []
		def launch(arguments, cwd=None):
			child = real_process([sys.executable, '-B', '-c', 'from threading import Event; Event().wait()'])
			children.append(child)
			widget = self.panes.pop(0)
			self.run_in_app(sip.delete, widget)
			return child
		with patch.object(engine, 'probe'), patch.object(windows, 'OwnedProcess', side_effect=launch), \
				patch.object(self.plugin.os, 'startfile') as viewer:
			self.plugin.CopyWithRobocopy(self.public_panes[0])()
			viewer.assert_not_called()
		self.assertEqual([], self.alerts)
		self.assertFalse(children[0].reader.is_alive())
		self.assertIsNone(children[0].process)
		release = self.plugin.ui.settings_resource('Robocopy operation').try_claim()
		self.assertIsNotNone(release)
		release()


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
			self.window = MainWindow(QApplication.instance(), theme, None, Mock(), 'null://')
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

class ComparatorIT(QtIT):
	def setUp(self):
		from core import Name, Size, Modified
		from core.commands import CompareFiles, CompareFolders, SetFileComparator, SetFolderComparator
		from core.fs.local import LocalFileSystem
		from fman import DirectoryPane, Window
		from fman.impl.plugins.builtin import NullFileSystem, NullColumn
		from fman.impl.plugins.command_registry import PaneCommandRegistry
		from fman.impl.plugins.config import Config
		from fman.impl.plugins.mother_fs import MotherFileSystem
		from fman.impl.plugins.plugin import FileSystemWrapper, _get_command_name
		from fman.impl.theme import Theme
		from fman.impl.widgets import MainWindow
		from fman.url import as_url
		from pathlib import Path
		from PyQt5.QtGui import QIcon, QPalette
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		self.directory = TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.root = Path(self.directory.name).resolve(strict=True)
		self.left_root, self.right_root = self.root / 'left', self.root / 'right'
		for root in (self.left_root, self.right_root):
			root.mkdir()
			(root / 'a.txt').write_text('first')
			(root / 'b.txt').write_text('second')
			(root / 'child').mkdir()
		self.config = Config('Windows')
		self.config.add_dir(str(self.root / 'settings'))
		self.config.save_json('Core Settings.json', {
			'file_comparator': {'executable': sys.executable, 'arguments': []},
			'folder_comparator': {'executable': sys.executable, 'arguments': []}})
		self.errors = Mock()
		self.filesystem = MotherFileSystem(Mock(get_icon=Mock(return_value=QIcon())))
		for backend in (LocalFileSystem(), NullFileSystem()):
			self.filesystem.add_child(backend.scheme, FileSystemWrapper(backend, self.filesystem, self.errors))
		for column in (Name(), Size(), Modified(), NullColumn()):
			self.filesystem.register_column(column.get_qualified_name(), column)
		def prepare():
			theme = Theme(Mock(), [])
			theme.load(str(Path(__file__).parents[3] / 'main/resources/base/Plugins/Core/Theme.css'))
			self.main = MainWindow(QApplication.instance(), theme, QPalette(), self.filesystem, 'null://')
			self.main.set_controller(Mock(handle_shortcut=Mock(return_value=False), handle_nonexistent_shortcut=Mock(return_value=False)))
			registry = PaneCommandRegistry(self.errors, Mock())
			for command in (CompareFiles, CompareFolders, SetFileComparator, SetFolderComparator):
				registry.register_command(_get_command_name(command), command)
			self.window = Window(self.main, registry)
			self.left = DirectoryPane(self.window, self.main.add_pane(), registry)
			self.right = DirectoryPane(self.window, self.main.add_pane(), registry)
			self.window._panes = [self.left, self.right]
			self.main.resize(960, 600)
			self.main.show()
		self.run_in_app(prepare)
		self.addCleanup(self.close_window)
		for target, kwargs in (
			('fman._get_ui', {'return_value': self.main}),
			('fman._get_plugin_support', {'return_value': self.config}),
			('fman.fs._get_mother_fs', {'return_value': self.filesystem}),
			('core.comparator.show_alert', {}), ('core.comparator.Popen', {})):
			patcher = patch(target, **kwargs)
			mock = patcher.start()
			self.addCleanup(patcher.stop)
			if target.endswith('Popen'):
				self.launch = mock
			elif target.endswith('show_alert'):
				self.alert = mock
		for pane, root in ((self.left, self.left_root), (self.right, self.right_root)):
			loaded = Event()
			pane.set_path(as_url(root), callback=loaded.set)
			self.assertTrue(loaded.wait(5))
			pane.place_cursor_at(as_url(root / 'a.txt'))

	def close_window(self):
		from core.comparator import _pending
		def close():
			models = [pane._widget._model for pane in (self.left, self.right)]
			for model in models:
				model.shutdown()
			self.main.close()
			return models
		self.run_in_app(close)
		self.run_in_app(self.main.deleteLater)
		self.assertEqual({}, _pending)
		self.errors.report.assert_not_called()

	def test_real_marks_cursors_folder_roots_and_registration(self):
		from core.commands import CompareFiles, CompareFolders
		from fman.url import as_url
		for identifier, label in (('compare_files', 'Compare files'), ('compare_folders', 'Compare folders'),
			('set_file_comparator', 'Set file comparator'), ('set_folder_comparator', 'Set folder comparator')):
			self.assertEqual((label,), self.left.get_command_aliases(identifier))
		for pane in (self.left, self.right):
			pane.focus()
			CompareFiles(pane)()
			self.launch.assert_called_with(args=[sys.executable, str(self.left_root / 'a.txt'), str(self.right_root / 'a.txt')], shell=False)
		self.left.select([as_url(self.left_root / 'b.txt')])
		CompareFiles(self.right)()
		self.assertEqual([str(self.left_root / 'b.txt'), str(self.right_root / 'a.txt')], self.launch.call_args.kwargs['args'][-2:])
		self.left.select([as_url(self.left_root / 'a.txt')])
		self.right.select([as_url(self.right_root / 'child')])
		CompareFiles(self.left)()
		self.assertEqual([str(self.left_root / 'a.txt'), str(self.left_root / 'b.txt')], self.launch.call_args.kwargs['args'][-2:])
		CompareFolders(self.right)()
		self.assertEqual([str(self.left_root), str(self.right_root)], self.launch.call_args.kwargs['args'][-2:])
		self.alert.assert_not_called()

	def test_context_menu_cursor_survives_qt_snapshot(self):
		from core.commands import CompareFiles
		from fman.url import as_url
		for pane, root in ((self.left, self.left_root), (self.right, self.right_root)):
			for marked in (False, True):
				with self.subTest(pane=str(root), marked=marked):
					pane.clear_selection()
					if marked:
						pane.select([as_url(root / 'a.txt')])
					with pane._override_file_under_cursor(as_url(root / 'b.txt')):
						self.assertEqual(as_url(root / 'a.txt'), self.run_in_app(pane.get_file_under_cursor))
						CompareFiles(pane)()
					left_name = 'b.txt' if pane is self.left and not marked else 'a.txt'
					right_name = 'b.txt' if pane is self.right and not marked else 'a.txt'
					self.launch.assert_called_with(args=[sys.executable,
						str(self.left_root / left_name), str(self.right_root / right_name)], shell=False)
					self.assertEqual(as_url(root / 'a.txt'), pane.get_file_under_cursor())
					pane.clear_selection()
		self.alert.assert_not_called()

	def test_snapshot_on_qt_and_metadata_off_qt(self):
		from core.comparator import compare, validate_operands
		from PyQt5.QtCore import QThread
		from unittest.mock import patch
		selected = self.left.get_selected_files
		def inspect_snapshot():
			self.assertEqual(QApplication.instance().thread(), QThread.currentThread())
			return selected()
		def inspect_metadata(*args):
			self.assertNotEqual(QApplication.instance().thread(), QThread.currentThread())
			return validate_operands(*args)
		with patch.object(self.left, 'get_selected_files', side_effect=inspect_snapshot), \
			patch('core.comparator.validate_operands', side_effect=inspect_metadata):
			compare(self.left, 'file')
		self.launch.assert_called_once()

	def _blocked_validation(self, cancel):
		from core.comparator import compare, validate_operands
		from fman import submit_task
		from fman.url import as_url
		from threading import Thread
		from unittest.mock import patch
		entered, release, finished = Event(), Event(), Event()
		tasks, failures = [], []
		def submit(task):
			tasks.append(task)
			submit_task(task)
		def blocked(*args):
			entered.set()
			if not release.wait(5):
				raise RuntimeError('Validation release timed out')
			validate_operands(*args)
		def run():
			try:
				compare(self.left, 'file')
			except BaseException as error:
				failures.append(error)
			finally:
				finished.set()
		with patch('core.comparator.validate_operands', side_effect=blocked), patch('core.comparator.submit_task', side_effect=submit):
			thread = Thread(target=run)
			thread.start()
			try:
				self.assertTrue(entered.wait(5))
				self.assertTrue(self.run_in_app(lambda: self.main.isVisible()))
				compare(self.right, 'file')
				self.assertIn('still validating', self.alert.call_args.args[0])
				self.assertEqual(1, len(tasks))
				if cancel:
					self.run_in_app(tasks[0]._dialog.request_cancel)
				else:
					loaded = Event()
					self.left.set_path(as_url(self.right_root), callback=loaded.set)
					self.assertTrue(loaded.wait(5))
			finally:
				release.set()
				self.assertTrue(finished.wait(5))
				thread.join(5)
		self.assertEqual([], failures)
		if cancel:
			self.launch.assert_not_called()
		else:
			self.assertEqual([str(self.left_root / 'a.txt'), str(self.right_root / 'a.txt')], self.launch.call_args.kwargs['args'][-2:])

	def test_pending_validation_is_bounded_and_snapshot_survives_navigation(self):
		self._blocked_validation(False)

	def test_cancel_blocked_validation_releases_slot(self):
		from core.comparator import compare
		self._blocked_validation(True)
		compare(self.left, 'folder')
		self.launch.assert_called_once()

	def test_wizard_dialogs_cancel_presets_manual_clear_and_persistence(self):
		from core.commands import SetFileComparator, SetFolderComparator
		from core.comparator import PRESETS
		from fman.impl.plugins.config import Config
		from fman.impl.quicksearch import Quicksearch
		from fman.impl.widgets import Prompt
		from PyQt5.QtCore import QTimer
		from unittest.mock import patch
		selection, canceled = 'Manual configuration', False
		errors = []
		def on_dialog(dialog):
			def answer():
				try:
					if canceled:
						dialog.reject()
					elif isinstance(dialog, Quicksearch):
						self.assertEqual([preset[0] for preset in PRESETS], [item.value for item in dialog._curr_items[:4]])
						dialog._query.setText(selection)
						dialog._on_return_pressed()
					elif isinstance(dialog, Prompt):
						dialog.setTextValue('--literal "two words"')
						dialog.accept()
					else:
						self.fail('Unexpected comparator dialog')
				except BaseException as error:
					errors.append(error)
					dialog.reject()
			QTimer.singleShot(0, answer)
		self.run_in_app(self.main.before_dialog.connect, on_dialog)
		with patch('fman.impl.widgets.QFileDialog.getOpenFileName', return_value=(sys.executable, 'Applications (*.exe)')):
			for command, role in ((SetFileComparator, 'file'), (SetFolderComparator, 'folder')):
				for selection in [preset[0] for preset in PRESETS] + ['Manual configuration']:
					command(self.left)()
					reloaded = Config('Windows')
					reloaded.add_dir(str(self.root / 'settings'))
					expected = ['--literal', 'two words'] if selection == 'Manual configuration' else list(next(preset for preset in PRESETS if preset[0] == selection)[2 if role == 'file' else 3])
					self.assertEqual(expected, reloaded.load_json('Core Settings.json')[role + '_comparator']['arguments'])
				canceled = True
				command(self.left)()
				canceled = False
				selection = 'Clear %s comparator' % role
				command(self.left)()
				self.assertIsNone(self.config.load_json('Core Settings.json')[role + '_comparator'])
		self.assertEqual([], errors)
		self.alert.assert_not_called()
		self.launch.assert_not_called()

class FindFilesIT(QtIT):
	def test_escape_closes_both_search_panels_and_focuses_pane(self):
		from fman.ui import UiOwner
		from fman.impl.ui.facade import _hosts
		from search_files import DEFAULTS, SearchSession
		from PyQt5.QtTest import QTest
		def close_panel(panel):
			host = _hosts[panel._key()]
			host.focus_panel()
			QApplication.processEvents()
			self.assertTrue(self.main._panel_dock.isAncestorOf(QApplication.focusWidget()))
			QTest.keyClick(QApplication.focusWidget(), Qt.Key_Escape)
			for turn in range(3):
				QApplication.processEvents()
			self.assertFalse(panel.is_open)
			self.assertIsNone(self.main._panel_dock)
			self.assertIs(self.pane._widget._file_view, QApplication.focusWidget())
		self.run_in_app(close_panel, self.session.panel)
		owner = UiOwner(resource_root=str(self.plugin_root.parent / 'SearchFiles'))
		try:
			session = self.run_in_app(SearchSession, owner, self.pane, str(self.root), dict(DEFAULTS))
			self.run_in_app(close_panel, session.panel)
		finally:
			owner.invalidate()

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
		for column in (Name(), Size(), Modified(), NullColumn()):
			self.filesystem.register_column(column.get_qualified_name(), column)
		self.plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/FindFiles'
		self.owner = UiOwner(resource_root=str(self.plugin_root))
		def prepare():
			self.main = MainWindow(QApplication.instance(), Mock(), Mock(), self.filesystem, 'null://')
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
			model = self.pane._widget._model
			model.shutdown()
			self.main.close()
			return model
		self.run_in_app(close)
		self.run_in_app(self.main.deleteLater)
		self.errors.report.assert_not_called()

	def search(self, **values):
		"""Start a search; return its open QuickTable window, or None when it finished without one."""
		from fman.impl.ui.facade import QuickTableWindow
		from find_files.engine import resolve_engine
		from pathlib import Path
		from time import monotonic, sleep
		if not Path(resolve_engine()).is_file():
			self.skipTest('Installed fd.exe is unavailable')
		self.finished = finished = Event()
		completed = self.session.completed
		def observed(*args):
			try:
				completed(*args)
			finally:
				self.session.completed = completed
				finished.set()
		self.session.completed = observed
		self.session.panel.update(values=values)
		self.run_in_app(self.session.action, 'search', self.session.panel.snapshot())
		deadline = monotonic() + 10
		while monotonic() < deadline:
			windows = self.run_in_app(lambda: [widget for widget in QApplication.topLevelWidgets()
				if isinstance(widget, QuickTableWindow) and widget.alive.is_set() and widget.isVisible()])
			if windows:
				return windows[-1]
			if finished.is_set():
				return None
			sleep(.02)
		self.fail('Search neither finished nor showed results')

	def test_date_entry_is_independent_of_current_month(self):
		from PyQt5.QtCore import QDate
		from PyQt5.QtTest import QTest
		from unittest.mock import patch
		def check():
			editor = self.host.controls['start_date'][1].editor
			for seed in (QDate(2026, 1, 1), QDate(2026, 9, 20), QDate(2026, 10, 1), QDate(2026, 12, 31)):
				class SeedDate(QDate):
					@staticmethod
					def currentDate():
						return seed
				with patch('fman.impl.ui.panel.QDate', SeedDate):
					for date in ('2024-02-29', '2026-09-20', '1752-09-14', '9999-12-31'):
						with self.subTest(seed=seed.toString('yyyy-MM-dd'), date=date):
							editor.set_value(None)
							editor.setFocus()
							editor.selectAll()
							QTest.keyClicks(editor, date)
							QTest.keyClick(editor, Qt.Key_Tab)
							self.assertEqual(date, self.session.panel.snapshot()['start_date'])
		self.run_in_app(check)

	def test_search_click_commits_date_without_focus_change(self):
		from PyQt5.QtTest import QTest
		from unittest.mock import Mock
		def check():
			search = self.host.controls['search'][1]
			for name in ('start_date', 'end_date'):
				for previous in (None, '2026-09-20'):
					for date in ('2024-02-29', '2000-01-01'):
						with self.subTest(field=name, previous=previous, date=date):
							self.session.panel.update(values={'start_date': None, 'end_date': None, name: previous})
							self.session.enable_form()
							self.assertTrue(search.isEnabled())
							editor = self.host.controls[name][1].editor
							editor.setFocus()
							editor.setSelectedSection(editor.YearSection)
							QTest.keyClicks(editor, date)
							self.assertEqual(date, editor.text())
							self.assertNotEqual(date, editor.date().toString('yyyy-MM-dd'))
							self.assertEqual(date, self.session.panel.snapshot()[name])
							action = Mock()
							self.host.on_action = action
							QTest.mouseClick(search, Qt.LeftButton)
							self.assertIs(editor, QApplication.focusWidget())
							action.assert_called_once()
							self.assertEqual('search', action.call_args.args[0])
							self.assertEqual(date, action.call_args.args[1][name])
							self.assertEqual(date, self.session.panel.snapshot()[name])
		self.run_in_app(check)

	def test_pending_date_bounds_update_search_eligibility(self):
		from PyQt5.QtCore import QDate
		from PyQt5.QtTest import QTest
		from unittest.mock import Mock, patch
		def check():
			class SeedDate(QDate):
				@staticmethod
				def currentDate():
					return QDate(2026, 10, 1)
			search = self.host.controls['search'][1]
			cases = (
				('start_date', 'end_date', '2024-12-31', '2024-02-29', '2025-01-01'),
				('end_date', 'start_date', '2028-01-01', '2028-06-30', '2027-12-31'),
			)
			with patch('fman.impl.ui.panel.QDate', SeedDate):
				for name, opposite, bound, valid, invalid in cases:
					for previous in (None, valid, invalid):
						with self.subTest(field=name, previous=previous):
							self.session.panel.update(values={name: previous, opposite: bound})
							self.session.enable_form()
							editor = self.host.controls[name][1].editor
							for date, enabled in ((valid, True), (invalid, False), (valid, True)):
								editor.setFocus()
								editor.setSelectedSection(editor.YearSection)
								QTest.keyClicks(editor, date)
								self.assertEqual(date, editor.text())
								self.assertEqual(enabled, search.isEnabled())
								action = Mock()
								self.host.on_action = action
								QTest.mouseClick(search, Qt.LeftButton)
								self.assertIs(editor, QApplication.focusWidget())
								if enabled:
									action.assert_called_once()
									self.assertEqual('search', action.call_args.args[0])
									self.assertEqual(date, action.call_args.args[1][name])
									self.assertEqual(bound, action.call_args.args[1][opposite])
								else:
									action.assert_not_called()
		self.run_in_app(check)

	def test_date_commit_can_close_panel_before_search_action(self):
		from PyQt5.QtTest import QTest
		from unittest.mock import Mock
		def check():
			editor = self.host.controls['start_date'][1].editor
			editor.setFocus()
			QTest.keyClicks(editor, '2024-02-29')
			action = Mock()
			self.host.on_action = action
			self.host.on_change = lambda values: self.session.panel.close()
			QTest.mouseClick(self.host.controls['search'][1], Qt.LeftButton)
			action.assert_not_called()
			self.assertFalse(self.session.panel.is_open)
			self.host.action('search')
			action.assert_not_called()
		self.run_in_app(check)

	def test_date_commit_can_invalidate_owner_before_search_action(self):
		from PyQt5.QtTest import QTest
		from unittest.mock import Mock
		def check():
			editor = self.host.controls['start_date'][1].editor
			editor.setFocus()
			QTest.keyClicks(editor, '2024-02-29')
			action = Mock()
			self.host.on_action = action
			self.host.on_change = lambda values: self.owner.invalidate()
			QTest.mouseClick(self.host.controls['search'][1], Qt.LeftButton)
			action.assert_not_called()
			self.assertFalse(self.owner.active)
			self.host.action('search')
			action.assert_not_called()
		self.run_in_app(check)

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
					editor.setFocus()
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
		window = self.search(type='all', max_results=None)
		def check():
			self.assertEqual(Qt.WindowModal, window.windowModality())
			self.assertEqual('Find files', window.windowTitle())
			self.assertIn('Showing 3 / 3 entries', window.summary.content)
			self.assertEqual('3 / 3 rows', window.table.counts.text())
			self.assertEqual(('Path', 'Size', 'Modified'), window.schema.headers)
			window.table.query.setText('report')
			QApplication.processEvents()
			self.assertEqual('1 / 3 rows', window.table.counts.text())
			window.open_menu(*window.table.current_cell, window.rect().center())
			next(action for action in window.menu.actions() if action.text() == 'Copy Path').trigger()
			self.assertEqual(str(self.root / 'report.txt'), QApplication.clipboard().text())
		self.run_in_app(check)
		closed = Event()
		self.run_in_app(window.disposed.connect, closed.set)
		with patch('fman.fs._get_mother_fs', return_value=self.filesystem):
			self.run_in_app(QTest.keyClick, window.table.view, Qt.Key_Return, Qt.ControlModifier)
			self.assertTrue(closed.wait(5))
			self.assertTrue(self.finished.wait(5))
			self.assertEqual(as_url(self.root / 'report.txt'), self.pane.get_file_under_cursor())
			window = self.search(type='d', max_results=None)
			self.assertEqual('1 / 1 rows', self.run_in_app(window.table.counts.text))
			closed.clear()
			self.run_in_app(window.disposed.connect, closed.set)
			self.run_in_app(QTest.keyClick, window.table.view, Qt.Key_Return, Qt.ControlModifier)
			self.assertTrue(closed.wait(5))
			self.assertTrue(self.finished.wait(5))
			self.assertEqual(as_url(self.root / 'folder'), self.pane.get_path())
			def check_focus():
				QApplication.processEvents()
				focused = QApplication.focusWidget()
				self.assertTrue(focused is self.pane._widget or self.pane._widget.isAncestorOf(focused))
			self.run_in_app(check_focus)

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
				self.assertEqual([], [widget for widget in QApplication.topLevelWidgets()
					if type(widget).__name__ == 'QuickTableWindow' and widget.alive.is_set()])
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
			for column in (Name(), Size(), Modified(), NullColumn()):
				filesystem.register_column(column.get_qualified_name(), column)
			plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFiles'
			owner = UiOwner(resource_root=str(plugin_root))
			def prepare():
				main = MainWindow(QApplication.instance(), Mock(), Mock(), filesystem, 'null://')
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
						('ctrl_enter', 'literal', 'report'), ('double', 'regex', '^report\\.txt$'), ('menu', 'glob', 'report*')):
						with self.subTest(action=action):
							pane.place_cursor_at(as_url(other))
							finished.clear()
							session.panel.update(values={'name': pattern, 'name_mode': mode, 'content': ''})
							self.run_in_app(session.action, 'search', session.panel.snapshot())
							window = self.wait_table()
							closed = Event()
							def activate():
								QApplication.processEvents()
								self.assertTrue(window.isVisible())
								self.assertEqual(Qt.WindowModal, window.windowModality())
								self.assertEqual('Search files', window.windowTitle())
								self.assertEqual(('report.txt', ''), window.table.current_cell[0].cells)
								self.assertIn('Complete: 1 files', window.summary.content)
								window.disposed.connect(closed.set)
								view = window.table.view
								if action == 'escape':
									QTest.keyClick(view, Qt.Key_Escape)
								elif action == 'enter':
									QTest.keyClick(view, Qt.Key_Return)
								elif action == 'ctrl_enter':
									QTest.keyClick(view, Qt.Key_Return, Qt.ControlModifier)
								elif action == 'double':
									position = view.visualRect(view.currentIndex()).center()
									QTest.mouseDClick(view.viewport(), Qt.LeftButton, pos=position)
								else:
									window.open_menu(*window.table.current_cell, view.mapToGlobal(view.rect().center()))
									next(item for item in window.menu.actions() if item.text() == 'Go To').trigger()
							self.run_in_app(activate)
							self.assertTrue(closed.wait(5), 'Results did not close after ' + action)
							self.assertTrue(finished.wait(5))
							def verify():
								QApplication.processEvents()
								host = _hosts[session.panel._key()]
								self.assertTrue(host.controls['name'][1].isEnabled())
								focused = QApplication.focusWidget()
								# Enter returns the visible rows (ignored by Search Files) and closes without navigating.
								if action in ('escape', 'enter'):
									self.assertIs(host.controls['name'][1], focused)
									self.assertEqual(as_url(other), pane.get_file_under_cursor())
								else:
									self.assertTrue(focused is pane._widget or pane._widget.isAncestorOf(focused))
									self.assertEqual(as_url(target), pane.get_file_under_cursor())
							self.run_in_app(verify)
			finally:
				owner.invalidate()
				def close():
					model = pane._widget._model
					model.shutdown()
					main.close()
					return model
				self.run_in_app(close)
				self.run_in_app(main.deleteLater)
				errors.report.assert_not_called()

	def test_root_follows_invoking_pane_and_fields_align(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import UiOwner
			from fman.url import as_url
			from fman.impl.ui.facade import QuickTableWindow, _hosts
			from fman.impl.widgets import MainWindow
			from search_files import DEFAULTS, SearchSession
			from PyQt5.QtCore import QPoint, QTimer, pyqtSignal
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
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
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
							buttons = [host.controls[name][1] for name in ('recursive', 'extended', 'search', 'stop')]
							control_left = modes[0].mapTo(host.form, QPoint()).x()
							self.assertEqual(control_left, modes[1].mapTo(host.form, QPoint()).x())
							self.assertEqual(control_left, buttons[0].mapTo(host.form, QPoint()).x())
							for row in [mode.group.buttons() for mode in modes] + [buttons]:
								self.assertTrue(all(button.width() == button.height() == 28 for button in row))
								self.assertEqual([control_left + 31 * column for column in range(len(row))],
									[button.mapTo(host.form, QPoint()).x() for button in row])
							centers = [button.mapTo(host.form, button.rect().center()).y() for button in buttons]
							self.assertLessEqual(max(centers) - min(centers), 1)
							self.assertLessEqual(buttons[-1].mapTo(host.form, buttons[-1].rect().topRight()).x(), host.form.width())
						large_label_width = host.form.fields[0][2].width()
						host.form.setStyleSheet('QLabel { font-size: 12px; }')
						QApplication.processEvents()
						self.assertLess(host.form.fields[0][2].width(), large_label_width)
						for record, wrapper, label in host.form.fields:
							self.assertEqual(host.form.fields[0][2].width(), label.width())
							self.assertGreaterEqual(label.width(), label.fontMetrics().horizontalAdvance(label.text()))
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
								progress=SimpleNamespace(files=1, elapsed=0), metadata=(), metadata_missing=0)
							seen = []
							def inspect():
								window = next(widget for widget in QApplication.topLevelWidgets()
									if isinstance(widget, QuickTableWindow) and widget.alive.is_set())
								seen.append((window.schema.base, window.pane, stop.isEnabled()))
								window.close()
							QTimer.singleShot(0, inspect)
							session.completed(session.generation, result)
							self.assertEqual([('C:\\next', panes[index], True)], seen)
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

	def test_real_search_panel_table_and_close(self):
		from fman import DirectoryPane, Window
		from fman.ui import UiOwner
		from fman.impl.ui.facade import QuickTableWindow, _hosts
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
				main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
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
			open_tables = lambda: self.run_in_app(lambda: [widget for widget in QApplication.topLevelWidgets()
				if isinstance(widget, QuickTableWindow) and widget.alive.is_set()])
			try:
				def start():
					host = _hosts[session.panel._key()]
					self.assertFalse(host.isVisible())
					self.assertFalse(host.activity_timer.isActive())
					for control, name in host.icon_controls:
						self.assertFalse(control.icon().isNull(), name)
					session.panel.update(values={'name': 'report', 'name_mode': 'literal', 'content': '*needle*', 'content_mode': 'glob'})
					session.action('search', session.panel.snapshot())
					self.assertTrue(host.activity_timer.isActive())
					self.assertFalse(host.controls['search'][1].isEnabled())
				self.run_in_app(start)
				window = self.wait_table()
				def check_content():
					self.assertEqual(Qt.WindowModal, window.windowModality())
					self.assertEqual(('report.txt', 'needle here'), window.table.current_cell[0].cells)
					self.assertIsNone(session.runner)
					self.assertFalse(finished.is_set())
					window.close()
				self.run_in_app(check_content)
				self.assertTrue(finished.wait(10))
				self.assertTrue(self.run_in_app(lambda: _hosts[session.panel._key()].controls['search'][1].isEnabled()))
				finished.clear()
				session.panel.update(values={'content': '(', 'content_mode': 'regex'})
				self.run_in_app(session.action, 'search', session.panel.snapshot())
				self.assertTrue(finished.wait(10))
				self.assertEqual([], open_tables())
				session.panel.update(values={'name': '*.txt', 'name_mode': 'glob', 'content': ''})
				finished.clear()
				self.run_in_app(session.action, 'search', session.panel.snapshot())
				window = self.wait_table()
				def check_names():
					self.assertEqual(('report.txt', ''), window.table.current_cell[0].cells)
					self.assertIn('Complete: 1 files', window.summary.content)
					window.close()
				self.run_in_app(check_names)
				self.assertTrue(finished.wait(10))
				session.panel.update(values={'content': 'needle', 'content_mode': 'literal'})
				finished.clear()
				def cancel():
					session.action('search', session.panel.snapshot())
					session.panel.close()
				self.run_in_app(cancel)
				self.assertTrue(finished.wait(10))
				self.assertEqual([], open_tables())
				self.assertTrue(session.panel.cancelled.is_set())
			finally:
				owner.invalidate()
				self.run_in_app(main.close)
				self.run_in_app(main.deleteLater)

	def test_extended_mode_typed_results_and_text_query(self):
		from fman import DirectoryPane, Window
		from fman.ui import UiOwner
		from fman.impl.ui.facade import _hosts
		from fman.impl.widgets import MainWindow
		from search_files import DEFAULTS, SearchSession
		from PyQt5.QtWidgets import QWidget
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock, patch
		plugin_root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFiles'
		owner = UiOwner(resource_root=str(plugin_root))
		with TemporaryDirectory() as root:
			Path(root, 'report.txt').write_text('final draft needle\nother needle\n', encoding='utf-8')
			Path(root, 'notes.txt').write_text('needle', encoding='utf-8')
			def prepare():
				main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
				pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
				from fman.url import as_url
				pane.get_path = lambda: as_url(root)
				pane.on_path_changed = Mock(return_value=lambda: None)
				main.show()
				session = SearchSession(owner, pane, root, dict(DEFAULTS))
				host = _hosts[session.panel._key()]
				toggle = host.controls['extended'][1]
				self.assertTrue(toggle.toolTip().startswith('Extended metadata mode'))
				self.assertFalse(toggle.icon().isNull())
				self.assertFalse(toggle.isChecked())
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
				with patch('search_files.Thread'):
					session.panel.update(values={'content': 'needle', 'name': '*.txt', 'extended': True})
					self.run_in_app(session.changed, session.panel.snapshot())
				self.assertIs(True, session.settings['extended'])
				self.run_in_app(session.action, 'search', session.panel.snapshot())
				window = self.wait_table(10)
				def check():
					table = window.table
					self.assertEqual(('File Path', 'Size', 'Date Modified', 'Snippet'), window.schema.headers)
					self.assertEqual((0, 3), window.schema.searchable)
					self.assertIs(False, table.truncated)
					self.assertEqual(3, table.model.rowCount())
					info = Path(root, 'report.txt').stat()
					row = next(row for row in table.model.rows if row.cells[0] == 'report.txt')
					self.assertEqual(('report.txt', info.st_size, info.st_mtime_ns, row.cells[3]), row.values)
					self.assertEqual('{:,} B'.format(info.st_size), row.cells[1])
					self.assertRegex(row.cells[2], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$')
					table.query.setText('report "FINAL draft"')
					QApplication.processEvents()
					self.assertEqual(1, table.model.rowCount())
					table.query.setText('"open')
					QApplication.processEvents()
					self.assertTrue(table.counts.text().startswith('Filter error: '))
					table.query.clear()
					table.set_sort(1, True)
					self.assertEqual('report.txt', table.model.rows[0].cells[0])
					window.close()
				self.run_in_app(check)
				self.assertTrue(finished.wait(10))
			finally:
				owner.invalidate()
				self.run_in_app(main.close)
				self.run_in_app(main.deleteLater)


class ChecksumFilesIT(QtIT):
	def show_results(self, results, pane, inspect):
		"""Run the blocking results table on Qt, inspecting and closing it from a timer."""
		from checksum_files import commands
		from fman.impl.ui.facade import QuickTableWindow
		from PyQt5.QtCore import QTimer
		seen = []
		def visit():
			window = next(widget for widget in QApplication.topLevelWidgets()
				if isinstance(widget, QuickTableWindow) and widget.alive.is_set())
			try:
				inspect(window)
				seen.append(window)
			finally:
				window.close()
		QTimer.singleShot(0, visit)
		commands.show_results(results, pane, 'C:\\checks\\checks.sha256')
		self.assertEqual(1, len(seen))

	def test_standalone_modeless_results(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.impl.widgets import MainWindow
			from PyQt5.QtCore import QPoint
			from PyQt5.QtWidgets import QLineEdit
			from checksum_files import engine
			from unittest.mock import Mock
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
			widget = QLineEdit(main)
			main._central_layout.addWidget(widget)
			pane = DirectoryPane(Window(main, Mock()), widget, Mock())
			main.show()
			main.activateWindow()
			QApplication.processEvents()
			try:
				results = engine.Results()
				results.add(engine.ResultRow(1, 'matched.txt', 'Matched', target='C:\\checks\\matched.txt'))
				results.add(engine.ResultRow(2, 'bad\x00name', 'Invalid record', details='bad\x00record'))
				results.complete = True
				results = results.freeze()
				def inspect(window):
					self.assertEqual(Qt.NonModal, window.windowModality())
					self.assertIsNone(QApplication.activeModalWidget())
					self.assertIsNone(main._panel_dock)
					self.assertEqual(results.summary, window.summary.content)
					self.assertEqual('2 / 2 rows', window.table.counts.text())
					self.assertEqual(('Relative Path', 'Status', 'Expected', 'Actual', 'Details'), window.schema.headers)
					rows = window.table.model.rows
					self.assertEqual('matched.txt', rows[0].cells[0])
					self.assertTrue(all('\x00' not in cell for row in rows for cell in row.cells))
					self.assertEqual('C:\\checks\\matched.txt', window.schema.target(rows[0], 0))
					window.table.view.setCurrentIndex(window.table.model.index(0, 0))
					window.open_menu(rows[0], 0, QPoint(10, 10))
					self.assertEqual(['Copy Path', 'Go To', 'Filter This Column...', 'Clear All Filters'],
						[action.text() for action in window.menu.actions() if not action.isSeparator()])
					window.close_menu()
					window.open_menu(None, -1, QPoint(10, 10))
					self.assertIsNone(window.menu)
				self.show_results(results, pane, inspect)
			finally:
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_empty_truncated_and_maximum_snapshots(self):
		from checksum_files import engine
		prepared = []
		for count in (0, 9999, 10000):
			results = engine.Results()
			for index in range(count):
				results.add(engine.ResultRow(index + 1, 'file-%s.txt' % index, 'Matched'))
			results.complete = True
			prepared.append(results.freeze())
		def check():
			from fman import DirectoryPane, Window
			from fman.impl.widgets import MainWindow
			from PyQt5.QtWidgets import QLineEdit
			from time import perf_counter
			from unittest.mock import Mock
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
			widget = QLineEdit(main)
			main._central_layout.addWidget(widget)
			pane = DirectoryPane(Window(main, Mock()), widget, Mock())
			main.show()
			try:
				for results in prepared:
					expected = 0 if results.all_rows is None else len(results.all_rows)
					def inspect(window):
						QApplication.processEvents()
						self.assertEqual(results.summary, window.summary.content)
						self.assertEqual(expected, window.table.model.rowCount())
						truncated = ' \u00b7 truncated' if expected < results.total else ''
						self.assertEqual('%d / %d rows%s' % (expected, expected, truncated), window.table.counts.text())
						if results.total == 10000:
							self.assertIn('Showing problems only', results.summary)
						if expected:
							started = perf_counter()
							window.table.query.setText('no-such-checksum-file')
							deadline = perf_counter() + 3
							while window.table.model.rowCount() and perf_counter() < deadline:
								QApplication.processEvents()
							print('Checksum Table %s-row filter: %.3f s' % (format(expected, ','), perf_counter() - started))
							self.assertIsNone(window.table.current_cell)
						image = window.grab().toImage()
						self.assertFalse(image.isNull())
						self.assertGreater(image.width(), 400)
						self.assertGreater(len({image.pixelColor(horizontal, vertical).rgba() for horizontal in range(0, image.width(), 30) for vertical in range(0, image.height(), 30)}), 1)
					self.show_results(results, pane, inspect)
			finally:
				main.close()
				main.deleteLater()
		self.run_in_app(check)


class QuickBoardFixture(QtIT):
	def setUp(self):
		from PyQt5.QtWidgets import QWidget
		from unittest.mock import patch
		self.main = self.run_in_app(QWidget)
		self.run_in_app(self.main.show)
		self.workers, self.releases = [], []
		self.ui_patch = patch('fman._get_ui', return_value=self.main)
		self.ui_patch.start()

	def tearDown(self):
		for release in self.releases:
			release.set()
		self.run_in_app(self.main.close)
		for worker, finished, results, errors in self.workers:
			self.assertTrue(finished.wait(5), 'QuickBoard caller stranded')
			worker.join(5)
			self.assertFalse(worker.is_alive())
			self.assertFalse(errors, errors)
		from fman.impl.ui.quick_board import _slots
		self.wait_for(lambda: _slots._value == 2)
		self.ui_patch.stop()
		self.run_in_app(self.main.deleteLater)

	def wait_for(self, predicate):
		from time import monotonic
		deadline = monotonic() + 5
		while monotonic() < deadline:
			value = self.run_in_app(predicate)
			if value:
				return value
			Event().wait(.01)
		self.fail('QuickBoard condition did not complete')

	def start_board(self, handler=None, **arguments):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board
		handler = handler or (lambda text: (QuickTableRow(('result: ' + text,)),))
		def mapped(text, mapping):
			return handler(text), None
		def invoke(**values):
			return show_quick_board(**values)[:2]
		defaults = dict(columns=(QuickTableColumn('Preview', sortable=False, filterable=False),), get_rows=mapped, text='draft')
		defaults.update(arguments)
		finished, results = self.start_call(invoke, **defaults)
		return mapped, finished, results

	def start_call(self, callback, *args, **kwargs):
		from threading import Thread
		finished, results, errors = Event(), [], []
		def invoke():
			try:
				results.append(callback(*args, **kwargs))
			except BaseException as error:
				errors.append(error)
			finally:
				finished.set()
		worker = Thread(target=invoke, daemon=True)
		self.workers.append((worker, finished, results, errors))
		worker.start()
		return finished, results

	def window_for(self, handler=None):
		from fman.impl.ui.quick_board import QuickBoardWindow
		return self.wait_for(lambda: next((widget for widget in QApplication.topLevelWidgets()
			if isinstance(widget, QuickBoardWindow) and (handler is None or widget.get_rows is handler)
			and widget.alive.is_set()), None))

	def settled(self, window):
		self.wait_for(lambda: not window.pending and window.table.settled)


class BatchFileRenamerIT(QuickBoardFixture):
	def test_hidden_occupied_name_is_invalid_and_cancel_leaves_files_unchanged(self):
		from tempfile import TemporaryDirectory
		from pathlib import Path
		from fman_unittest.batch_file_renamer_fixture import engine_module
		from fman.ui import show_quick_board
		from fman.url import as_url
		from fman.impl.ui.table_filters import compile_filter
		with TemporaryDirectory() as directory, engine_module() as engine:
			root = Path(directory).resolve()
			for name in ('A.txt', 'B.txt'):
				(root / name).write_text(name)
			captured = engine.capture(tuple(as_url(root / name) for name in ('A.txt', 'B.txt')))
			finished, result = self.start_call(show_quick_board, columns=engine.COLUMNS,
				get_rows=lambda text, mapping: engine.preview(captured, text, mapping, with_status=True), text='{name}{ext}')
			window = self.window_for()
			self.settled(window)
			self.run_in_app(window.table.set_column_filter, 2, compile_filter(engine.COLUMNS[2], 2, 'substring', 'A.txt'))
			self.settled(window)
			self.run_in_app(window.input.setText, 'B.txt')
			self.settled(window)
			self.assertEqual((0, None), window.mapping)
			self.assertIn('Target exists', self.run_in_app(lambda: window.table.model.rows[0].cells[5]))
			self.run_in_app(window.close)
			self.assertTrue(finished.wait(5))
			self.assertEqual([('B.txt', False, None)], result)
			self.assertEqual('A.txt', (root / 'A.txt').read_text())
			self.assertEqual('B.txt', (root / 'B.txt').read_text())


class QuickBoardMappingIT(QuickBoardFixture):
	def test_optional_caller_status_and_trailing_debounce(self):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board
		calls = []
		def rows(text, mapping):
			calls.append((text, mapping))
			return (QuickTableRow(('fixed',)),), None if text == 'quiet' else 'Rename blocked: 1 naming conflict.'
		finished, result = self.start_call(show_quick_board, columns=(QuickTableColumn('Name'),), get_rows=rows)
		window = self.window_for()
		self.settled(window)
		self.assertEqual('Rename blocked: 1 naming conflict.', self.run_in_app(window.caller_status.text))
		self.assertTrue(self.run_in_app(window.caller_status.isVisible))
		before = len(calls)
		def edit():
			for value in ('q', 'qu', 'qui', 'quie', 'quiet'):
				window.input.setText(value)
			self.assertTrue(window.debounce.isActive())
			self.assertEqual(before, len(calls))
			self.assertFalse(window.caller_status.isVisible())
		self.run_in_app(edit)
		self.settled(window)
		self.assertEqual(before + 1, len(calls))
		self.assertEqual('quiet', calls[-1][0])
		self.assertFalse(self.run_in_app(window.caller_status.isVisible))
		self.run_in_app(window.input.setText, 'accept')
		self.run_in_app(window.request_accept)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('accept', True, (0,))], result)

	def test_view_change_during_bootstrap_does_not_strand_dialog(self):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board
		entered, release = Event(), Event()
		self.releases.append(release)
		calls = []
		def rows(text, mapping):
			calls.append(mapping)
			if len(calls) == 1:
				entered.set()
				release.wait(5)
			return (QuickTableRow(('beta',)), QuickTableRow(('alpha',))), None
		finished, result = self.start_call(show_quick_board, columns=(QuickTableColumn('Name'),), get_rows=rows)
		window = self.window_for()
		self.assertTrue(entered.wait(5))
		self.run_in_app(window.table.set_sort, 0)
		release.set()
		self.settled(window)
		self.assertEqual((1, 0), window.mapping)
		self.run_in_app(window.request_accept)
		self.assertTrue(finished.wait(5))

	def test_view_change_clears_pending_acceptance_and_rejects_old_map(self):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board
		from fman.impl.ui.table_filters import compile_filter
		entered, release = Event(), Event()
		self.releases.append(release)
		def rows(text, mapping):
			if mapping == (0, 1):
				entered.set()
				release.wait(5)
			return tuple(QuickTableRow((name, '' if mapping is None or mapping[index] is None else str(mapping[index])))
				for index, name in enumerate(('alpha', 'beta'))), None
		columns = (QuickTableColumn('Source'), QuickTableColumn('Index', sortable=False, filterable=False))
		finished, result = self.start_call(show_quick_board, columns=columns, get_rows=rows)
		window = self.window_for()
		self.assertTrue(entered.wait(5))
		self.run_in_app(window.request_accept)
		self.run_in_app(window.table.set_column_filter, 0, compile_filter(columns[0], 0, 'substring', 'beta'))
		release.set()
		self.settled(window)
		self.assertFalse(finished.is_set())
		self.assertEqual((None, 0), window.mapping)
		self.run_in_app(window.request_accept)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('', True, (None, 0))], result)

	def test_bootstrap_once_and_accepted_map_matches_filtered_preview(self):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board
		from fman.impl.ui.table_filters import compile_filter
		calls = []
		def rows(text, mapping):
			calls.append((text, mapping))
			return tuple(QuickTableRow((name, '' if mapping is None or mapping[index] is None else text + str(mapping[index])))
				for index, name in enumerate(('beta', 'alpha', 'gamma'))), None
		columns = (QuickTableColumn('Name'), QuickTableColumn('Preview', sortable=False, filterable=False))
		finished, result = self.start_call(show_quick_board, columns=columns, get_rows=rows, text='old')
		window = self.window_for()
		self.settled(window)
		self.assertEqual([('old', None), ('old', (0, 1, 2))], calls)
		self.run_in_app(window.input.setText, 'new')
		self.settled(window)
		self.assertEqual(('new', (0, 1, 2)), calls[-1])
		self.run_in_app(window.table.set_sort, 0)
		self.settled(window)
		self.assertEqual((1, 0, 2), window.mapping)
		self.run_in_app(window.table.set_column_filter, 0, compile_filter(columns[0], 0, 'substring', 'alpha'))
		self.settled(window)
		self.assertEqual((None, 0, None), window.mapping)
		self.assertEqual('new0', self.run_in_app(lambda: window.table.model.rows[0].cells[1]))
		self.run_in_app(window.request_accept)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('new', True, (None, 0, None))], result)
		self.assertEqual(1, sum(mapping is None for text, mapping in calls))

	def test_sort_during_preview_error_marks_retained_rows_stale(self):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board
		calls = []
		def rows(text, mapping):
			calls.append((text, mapping))
			if text == 'invalid':
				raise ValueError('Invalid expression')
			return tuple(QuickTableRow((name, '' if mapping is None else str(mapping[index])))
				for index, name in enumerate(('beta', 'alpha'))), None
		columns = (QuickTableColumn('Name'), QuickTableColumn('Index', sortable=False, filterable=False))
		finished, result = self.start_call(show_quick_board, columns=columns, get_rows=rows)
		window = self.window_for()
		self.settled(window)
		self.run_in_app(window.input.setText, 'invalid')
		self.wait_for(lambda: window.preview_error)
		count = len(calls)
		self.run_in_app(window.table.set_sort, 0)
		self.wait_for(lambda: window.table.settled)
		self.assertEqual([('alpha', '1'), ('beta', '0')],
			self.run_in_app(lambda: [row.cells for row in window.table.model.rows]))
		self.assertIn('Stale preview', self.run_in_app(lambda: window.status.content))
		self.assertEqual(count, len(calls))
		self.run_in_app(window.request_accept)
		self.assertFalse(finished.is_set())
		self.run_in_app(window.input.setText, 'valid')
		self.settled(window)
		self.assertNotIn('Stale preview', self.run_in_app(lambda: window.status.content))
		self.assertEqual([('alpha', '0'), ('beta', '1')],
			self.run_in_app(lambda: [row.cells for row in window.table.model.rows]))
		self.run_in_app(window.request_accept)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('valid', True, (1, 0))], result)

	def test_changed_source_is_error_not_a_loop(self):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board
		calls = []
		def rows(text, mapping):
			calls.append(mapping)
			return (QuickTableRow(('initial' if mapping is None else 'changed',)),), None
		finished, result = self.start_call(show_quick_board, columns=(QuickTableColumn('Source'),), get_rows=rows)
		window = self.window_for()
		self.wait_for(lambda: window.preview_error)
		self.assertIn('must stay fixed', window.preview_error)
		self.assertIn("column 'Source'", window.preview_error)
		self.assertIn('sortable=False, filterable=False', window.preview_error)
		self.assertEqual([None, (0,)], calls)
		self.run_in_app(window.request_accept)
		self.assertFalse(finished.is_set())
		self.run_in_app(window.close)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('', False, None)], result)


class QuickBoardIT(QuickBoardFixture):
	def test_cancel_during_formatter_stops_next_formatter(self):
		from fman.ui import QuickTableColumn, QuickTableRow
		from unittest.mock import Mock
		from fman.impl.ui.quick_board import _slots
		for cancel_by_edit in (False, True):
			with self.subTest(cancel_by_edit=cancel_by_edit):
				entered, release = Event(), Event()
				self.releases.append(release)
				def first(value):
					if value == 1:
						entered.set()
						self.assertTrue(release.wait(5))
					return str(value)
				second = Mock(side_effect=str)
				columns = (QuickTableColumn('First', 'numeric', format=first, sortable=False, filterable=False),
					QuickTableColumn('Second', 'numeric', format=second, sortable=False, filterable=False))
				preview, finished, result = self.start_board(
					lambda text: (QuickTableRow((1, 2) if text == 'A' else (3, 4)),), columns=columns, text='A')
				window = self.window_for(preview)
				self.assertTrue(entered.wait(5))
				if cancel_by_edit:
					self.run_in_app(window.input.setText, 'B')
				else:
					self.run_in_app(window.close)
					self.assertTrue(finished.wait(5))
					self.assertEqual([('A', False)], result)
				self.assertEqual(1, _slots._value)
				release.set()
				if cancel_by_edit:
					self.settled(window)
					self.assertEqual([4, 4], [call.args[0] for call in second.call_args_list])
					self.run_in_app(window.close)
					self.assertTrue(finished.wait(5))
				else:
					self.wait_for(lambda: _slots._value == 2)
					second.assert_not_called()
				self.wait_for(lambda: _slots._value == 2)

	def test_multiline_paste_returns_draft_only_on_cancel(self):
		from PyQt5.QtTest import QTest
		preview, finished, result = self.start_board()
		window = self.window_for(preview)
		self.settled(window)
		draft = 'first\nsecond\r\nthird'
		def paste():
			clipboard = QApplication.clipboard()
			previous = clipboard.text()
			try:
				clipboard.setText(draft)
				window.input.selectAll()
				window.input.paste()
			finally:
				clipboard.setText(previous)
			self.assertEqual(draft, window.input.text())
			self.assertIsNotNone(window.preview_error)
			self.assertIn('Preview error:', window.status.content)
			QTest.keyClick(window.input, Qt.Key_Return)
		self.run_in_app(paste)
		self.assertFalse(finished.is_set())
		self.run_in_app(QTest.keyClick, window.input, Qt.Key_Escape)
		self.assertTrue(finished.wait(5))
		self.assertEqual([(draft, False)], result)

	def test_new_preview_closes_filter_editor_and_retains_committed_filter(self):
		from fman.ui import QuickTableColumn, QuickTableRow
		from fman.impl.ui.table import FilterEditor
		from fman.impl.ui.table_filters import compile_filter
		entered, release = Event(), Event()
		self.releases.append(release)
		def handler(text):
			if text == 'next':
				entered.set()
				release.wait(5)
			return (QuickTableRow(('alpha',)),)
		preview, finished, result = self.start_board(handler, columns=(QuickTableColumn('Preview'),))
		window = self.window_for(preview)
		self.settled(window)
		committed = compile_filter(window.schema.columns[0], 0, 'substring', 'alpha')
		self.run_in_app(window.table.set_column_filter, 0, committed)
		self.run_in_app(window.input.setText, 'next')
		self.assertTrue(entered.wait(5))
		def edit_filter():
			self.assertIn('Updating...', window.status.content)
			menu = window.table.open_filter_menu(0)
			menu.findChild(FilterEditor).first.setText('unapplied')
		self.run_in_app(edit_filter)
		release.set()
		self.settled(window)
		self.assertIsNone(self.run_in_app(lambda: window.table.filter_menu))
		self.assertIs(committed, self.run_in_app(lambda: window.table.filters[0]))
		self.assertNotIn('Updating...', self.run_in_app(lambda: window.status.content))
		self.run_in_app(window.close)

	def test_frameless_title_drags_without_changing_text(self):
		from PyQt5.QtCore import QEvent, QPoint, QPointF
		from PyQt5.QtGui import QMouseEvent
		from PyQt5.QtTest import QTest
		preview, finished, result = self.start_board(title='Compose names')
		window = self.window_for(preview)
		self.settled(window)
		def drag():
			start = window.pos()
			local, delta = QPoint(10, 8), QPoint(24, 16)
			QTest.mousePress(window.header, Qt.LeftButton, pos=local)
			global_position = window.header.mapToGlobal(local) + delta
			QApplication.sendEvent(window.header, QMouseEvent(QEvent.MouseMove, QPointF(local),
				QPointF(global_position), Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
			QTest.mouseRelease(window.header, Qt.LeftButton, pos=local)
			self.assertEqual(start + delta, window.pos())
			self.assertEqual('draft', window.input.text())
			self.assertIsNone(window.drag)
			window.close()
		self.run_in_app(drag)

	def test_construction_failure_releases_admission(self):
		from fman.ui import QuickTableColumn, show_quick_board
		from fman.impl.ui.quick_board import _slots
		from unittest.mock import Mock, patch
		handler = Mock(return_value=((), None))
		with patch('fman.impl.ui.quick_board.TableSchema', side_effect=ValueError('Invalid schema')), \
				self.assertRaisesRegex(ValueError, 'Invalid schema'):
			self.run_in_app(show_quick_board,
				columns=(QuickTableColumn('Preview'),), get_rows=handler, text='draft')
		handler.assert_not_called()
		self.assertEqual(2, _slots._value)

	def test_shown_before_initial_callback_and_early_enter_is_retained(self):
		from PyQt5.QtTest import QTest
		from unittest.mock import patch
		callbacks, visible = [], []
		def handler(text):
			visible.append(self.run_in_app(window.isVisible))
			return ()
		with patch('fman.impl.ui.quick_board.defer', side_effect=lambda window, callback: callbacks.append(callback)):
			owner, finished, result = self.start_board(handler)
			window = self.window_for(owner)
			self.assertFalse(visible)
			self.run_in_app(QTest.keyClick, window.table.view, Qt.Key_Return)
			self.assertFalse(finished.is_set())
			self.run_in_app(callbacks.pop())
			self.assertTrue(finished.wait(5))
		self.assertEqual([True, True], visible)
		self.assertEqual([('draft', True)], result)

	def test_queued_start_failure_and_owned_error_teardown(self):
		from unittest.mock import patch
		from PyQt5.QtTest import QTest
		entered, release = Event(), Event()
		self.releases.append(release)
		def handler(text):
			entered.set()
			release.wait(5)
			return ()
		owner, finished, result = self.start_board(handler)
		window = self.window_for(owner)
		self.assertTrue(entered.wait(5))
		self.run_in_app(window.input.setText, 'queued')
		with patch('fman.impl.model.listing.Thread', side_effect=RuntimeError('Queued start failed')), patch('fman.show_alert') as alert:
			release.set()
			self.assertTrue(finished.wait(5))
			self.wait_for(lambda: alert.call_count == 1)
		self.assertEqual([('queued', False)], result)
		from fman.ui import QuickTableColumn, QuickTableRow
		def bad_format(value):
			raise RuntimeError('Formatter failed')
		owner, finished, result = self.start_board(lambda text: (QuickTableRow((7,)),),
			columns=(QuickTableColumn('Value', 'numeric', format=bad_format),))
		window = self.window_for(owner)
		self.wait_for(lambda: window.prompt is not None)
		prompt = self.run_in_app(lambda: window.prompt)
		self.run_in_app(QTest.keyClick, prompt, Qt.Key_Escape)
		self.assertFalse(finished.is_set())
		self.assertEqual('Formatter failed', window.preview_error)
		self.run_in_app(window.close)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('draft', False)], result)

	def test_public_worker_and_qt_callers_preserve_text_and_theme(self):
		from fman.ui import QuickTableColumn, show_quick_board
		from fman.impl.ui.quick_board import QuickBoardWindow
		from PyQt5.QtCore import QTimer
		from PyQt5.QtTest import QTest
		from PyQt5.QtWidgets import QAbstractButton
		from threading import get_ident
		threads = []
		def handler(text):
			threads.append(get_ident())
			return ()
		owner, finished, result = self.start_board(handler, text='  draft  ', summary='<literal & summary>')
		window = self.window_for(owner)
		self.settled(window)
		def inspect():
			self.assertFalse([button for button in window.findChildren(QAbstractButton) if button.isVisible()])
			self.assertEqual(Qt.WindowModal, window.windowModality())
			self.assertTrue(window.windowFlags() & Qt.FramelessWindowHint)
			self.assertEqual(window.windowTitle(), window.header.content)
			self.assertEqual(Qt.PlainText, window.header.textFormat())
			self.assertTrue(window.header.font().bold())
			self.assertTrue(window.table.counts.isHidden())
			self.assertEqual('0 / 0 rows', window.status.content)
			self.assertEqual(window.table.layout().spacing(), window.table.view.y() - window.input.geometry().bottom() - 1)
			self.assertEqual((820, 520), (window.width(), window.height()))
			self.assertFalse(window.styleSheet())
			self.assertEqual('<literal & summary>', window.summary.content)
			self.assertEqual(Qt.PlainText, window.summary.textFormat())
			self.assertEqual('', window.table.query.text())
			self.assertTrue(window.table.query.isHidden())
			self.assertTrue(window.table.view.alternatingRowColors())
			self.assertNotEqual(get_ident(), threads[0])
			QTest.keyClick(window.input, Qt.Key_Return)
		self.run_in_app(inspect)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('  draft  ', True)], result)
		def nested():
			def cancel():
				board = next(widget for widget in QApplication.topLevelWidgets()
					if isinstance(widget, QuickBoardWindow) and widget.alive.is_set())
				QTest.keyClick(board.input, Qt.Key_Escape)
			QTimer.singleShot(0, cancel)
			return show_quick_board(columns=(QuickTableColumn('Value'),), get_rows=lambda text, mapping: ((), None), text='\U0001f600 draft')
		self.assertEqual(('\U0001f600 draft', False, None), self.run_in_app(nested))

	def test_queued_enter_accepts_only_its_revision(self):
		from fman.ui import QuickTableRow
		from PyQt5.QtTest import QTest
		for edited in (False, True):
			with self.subTest(edited=edited):
				entered, release = Event(), Event()
				self.releases.append(release)
				def handler(text):
					if text == 'A':
						entered.set()
						release.wait(5)
					return (QuickTableRow((text,)),)
				owner, finished, result = self.start_board(handler, text='A')
				window = self.window_for(owner)
				self.assertTrue(entered.wait(5))
				self.run_in_app(QTest.keyClick, window.input, Qt.Key_Return)
				self.assertFalse(finished.is_set())
				if edited:
					self.run_in_app(window.input.setText, 'B')
					release.set()
					self.settled(window)
					self.assertFalse(finished.is_set())
					self.assertEqual('B', self.run_in_app(lambda: window.table.model.rows[0].cells[0]))
					self.run_in_app(QTest.keyClick, window.input, Qt.Key_Return)
				else:
					release.set()
				self.assertTrue(finished.wait(5))
				self.assertEqual([('B' if edited else 'A', True)], result)

	def test_queued_enter_waits_for_new_projection(self):
		from fman.ui import QuickTableRow
		from fman.impl.ui.table_filters import compile_filter
		from itertools import count
		from unittest.mock import patch
		from PyQt5.QtTest import QTest
		entered, release = Event(), Event()
		self.releases.append(release)
		def handler(text):
			if text == 'slow':
				entered.set()
				release.wait(5)
			return tuple(QuickTableRow(('match%d' % index,)) for index in range(4))
		owner, finished, result = self.start_board(handler)
		window = self.window_for(owner)
		self.settled(window)
		self.run_in_app(window.table.set_column_filter, 0, compile_filter(window.schema.columns[0], 0, 'substring', 'match'))
		self.run_in_app(window.input.setText, 'slow')
		self.assertTrue(entered.wait(5))
		callbacks = []
		with patch('fman.impl.ui.table.perf_counter', side_effect=count().__next__), \
				patch('fman.impl.ui.table.defer', side_effect=lambda owner, callback: callbacks.append(callback)):
			self.run_in_app(QTest.keyClick, window.input, Qt.Key_Return)
			release.set()
			self.wait_for(lambda: not window.pending and window.table.pending)
			self.assertFalse(finished.is_set())
			def finish_projection():
				while callbacks:
					callbacks.pop(0)()
			self.run_in_app(finish_projection)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('slow', True)], result)

	def test_errors_are_separate_from_filtering_and_recover(self):
		from fman.ui import QuickTableRow
		from PyQt5.QtTest import QTest
		from unittest.mock import patch
		def handler(text):
			if text == 'invalid':
				def rows():
					yield QuickTableRow(('partial',))
					raise ValueError('Invalid expression')
				return rows()
			if text == 'broken':
				raise RuntimeError('Unexpected failure')
			return (QuickTableRow(('result',)),)
		owner, finished, result = self.start_board(handler)
		window = self.window_for(owner)
		self.settled(window)
		with patch.object(window, 'alert') as alert:
			for text in ('invalid', 'broken'):
				self.run_in_app(window.input.setText, text)
				self.wait_for(lambda: window.preview_error is not None)
				self.run_in_app(window.table.set_sort, 0, True)
				self.run_in_app(window.table.clear_all_filters)
				self.run_in_app(QTest.keyClick, window.input, Qt.Key_Return)
				self.assertFalse(finished.is_set())
				self.assertEqual('', self.run_in_app(lambda: window.table.error))
				self.assertIsNone(window.accept_revision)
			alert.assert_called_once_with('Unexpected failure')
		self.run_in_app(window.input.setText, 'good')
		self.settled(window)
		self.assertIsNone(window.preview_error)
		self.run_in_app(QTest.keyClick, window.input, Qt.Key_Escape)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('good', False)], result)

	def test_formatters_are_worker_only_and_late_results_are_discarded(self):
		from fman.ui import QuickTableColumn, QuickTableRow
		from threading import get_ident
		from unittest.mock import Mock
		calls = []
		formatter = Mock(side_effect=lambda value: (calls.append(get_ident()), 'custom:%d' % value)[1])
		columns = (QuickTableColumn('Value', 'numeric', format=formatter), QuickTableColumn('Date', 'date'))
		owner, finished, result = self.start_board(lambda text: (QuickTableRow((7, 0)),), columns=columns)
		window = self.window_for(owner)
		self.settled(window)
		self.assertNotEqual(self.run_in_app(get_ident), calls[0])
		self.assertEqual(('custom:7',), self.run_in_app(lambda: (window.table.model.rows[0].cells[0],)))
		self.assertEqual((7, 0), self.run_in_app(lambda: window.table.model.rows[0].values))
		self.run_in_app(window.table.set_sort, 0, True)
		self.assertGreaterEqual(formatter.call_count, 2)
		entered, release = Event(), Event()
		self.releases.append(release)
		def blocked(value):
			entered.set()
			release.wait(5)
			return 'late'
		formatter.side_effect = blocked
		self.run_in_app(window.input.setText, 'later')
		self.assertTrue(entered.wait(5))
		self.run_in_app(window.close)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('later', False)], result)
		from fman.impl.ui.quick_board import _slots
		self.assertEqual(1, _slots._value)
		release.set()
		self.wait_for(lambda: _slots._value == 2)

	def test_global_admission_includes_closed_blocked_boards(self):
		from fman.ui import QuickTableColumn, show_quick_board
		from fman.impl.ui import _work_slots
		from unittest.mock import Mock, patch
		release = Event()
		self.releases.append(release)
		entered = [Event(), Event()]
		windows = []
		for gate in entered:
			def handler(text, gate=gate):
				gate.set()
				release.wait(5)
				return ()
			owner, finished, result = self.start_board(handler)
			windows.append(self.window_for(owner))
			self.assertTrue(gate.wait(5))
		callback = Mock(return_value=((), None))
		with patch('fman.show_alert') as alert:
			for close in (False, True):
				if close:
					for window in windows:
						self.run_in_app(window.close)
					for worker, finished, result, errors in self.workers:
						self.assertTrue(finished.wait(5))
				self.assertEqual(('third', False, None), show_quick_board(columns=(QuickTableColumn('Value'),),
					get_rows=callback, text='third'))
			callback.assert_not_called()
			self.assertEqual(2, alert.call_count)
		release.set()
		from fman.impl.ui.quick_board import _slots
		self.wait_for(lambda: _slots._value == 2)
		self.assertTrue(_work_slots.acquire(blocking=False))
		self.assertTrue(_work_slots.acquire(blocking=False))
		try:
			owner, finished, result = self.start_board()
			window = self.window_for(owner)
			self.settled(window)
			self.run_in_app(window.close)
			self.assertTrue(finished.wait(5))
		finally:
			_work_slots.release()
			_work_slots.release()

	def test_thread_start_failure_releases_caller_and_admission(self):
		from unittest.mock import patch
		for constructor in (True, False):
			with self.subTest(constructor=constructor), patch('fman.show_alert') as alert, \
					patch('fman.impl.model.listing.Thread') as thread:
				if constructor:
					thread.side_effect = RuntimeError('Cannot start')
				else:
					thread.return_value.start.side_effect = RuntimeError('Cannot start')
				owner, finished, result = self.start_board()
				self.assertTrue(finished.wait(5))
				self.assertEqual([('draft', False)], result)
				self.wait_for(lambda: alert.call_count == 1)
		from fman.impl.ui.quick_board import _slots
		self.assertEqual(2, _slots._value)

	def test_filters_focus_and_copy_do_not_change_composition(self):
		from fman.ui import QuickTableColumn, QuickTableRow
		from fman.impl.ui.table import FilterEditor
		from PyQt5.QtCore import QPoint
		from PyQt5.QtTest import QTest
		columns = (QuickTableColumn('Path', 'file_path'), QuickTableColumn('Value', 'numeric'))
		owner, finished, result = self.start_board(lambda text: (QuickTableRow(('relative-file.txt', 7)),),
			columns=columns, text='rename-{index}')
		window = self.window_for(owner)
		self.settled(window)
		def check():
			window.raise_()
			window.activateWindow()
			window.input.setFocus()
			QApplication.processEvents()
			QTest.keyClick(window.input, Qt.Key_Down)
			self.assertIs(window.table.view, QApplication.focusWidget())
			QTest.keyClick(window.table.view, Qt.Key_F, Qt.ControlModifier)
			self.assertIs(window.input, QApplication.focusWidget())
			self.assertEqual('rename-{index}', window.input.selectedText())
			QTest.keyClick(window.input, Qt.Key_Tab)
			self.assertIs(window.table.view, QApplication.focusWidget())
			QTest.keyClick(window.table.view, Qt.Key_Backtab, Qt.ShiftModifier)
			self.assertIs(window.input, QApplication.focusWidget())
			QTest.keyClick(window.input, Qt.Key_Down, Qt.AltModifier)
			QApplication.processEvents()
			menu = window.table.filter_menu
			self.assertIsNotNone(menu)
			editor = menu.findChild(FilterEditor)
			editor.first.setText('not-present')
			QTest.keyClick(editor.first, Qt.Key_Return)
			QApplication.processEvents()
			self.assertEqual(0, window.table.model.rowCount())
			window.table.clear_all_filters()
			self.assertEqual('rename-{index}', window.input.text())
			self.assertEqual(1, window.table.model.rowCount())
			window.table.view.setCurrentIndex(window.table.model.index(0, 0))
			window.open_menu(window.table.model.rows[0], 0, window.mapToGlobal(QPoint(20, 50)))
			self.assertEqual(['Copy Path', '', 'Filter This Column...', 'Clear All Filters'],
				[action.text() for action in window.menu.actions()])
			clipboard = QApplication.clipboard()
			previous = clipboard.text()
			try:
				window.menu.setActiveAction(window.menu.actions()[0])
				QTest.keyClick(window.menu, Qt.Key_Return)
				self.assertEqual('relative-file.txt', clipboard.text())
			finally:
				clipboard.setText(previous)
			window.table.open_filter_menu(0)
			QTest.keyClick(window.table.filter_menu, Qt.Key_Escape)
			self.assertTrue(window.alive.is_set())
			QTest.keyClick(window.input, Qt.Key_Escape)
		self.run_in_app(check)
		self.assertTrue(finished.wait(5))
		self.assertEqual([('rename-{index}', False)], result)

	def test_parent_close_and_worker_completion_order(self):
		first, first_done, first_result = self.start_board(text='first')
		first_window = self.window_for(first)
		second, second_done, second_result = self.start_board(text='second')
		second_window = self.window_for(second)
		self.settled(first_window)
		self.settled(second_window)
		self.run_in_app(first_window.close)
		self.assertTrue(first_done.wait(5))
		self.assertFalse(second_done.is_set())
		self.run_in_app(self.main.close)
		self.assertTrue(second_done.wait(5))
		self.assertEqual([('first', False)], first_result)
		self.assertEqual([('second', False)], second_result)


class TableIT(QtIT):
	def test_view_mapping_preserves_duplicate_source_positions(self):
		def check():
			from fman.impl.ui.table import Table
			from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
			schema = TableSchema((QuickTableColumn('Name'),))
			duplicate = QuickTableRow(('beta',))
			table = Table(schema, schema.snapshot((duplicate, QuickTableRow(('alpha',)), duplicate)))
			try:
				table.set_sort(0)
				self.assertEqual((1, 0, 2), table.view_mapping())
				table.query.setText('beta')
				self.assertEqual((0, None, 1), table.view_mapping())
				self.assertEqual((0, 2), table.visible_positions())
				table.query.setText('missing')
				self.assertEqual((None, None, None), table.view_mapping())
			finally:
				table.dispose()
				table.deleteLater()
		self.run_in_app(check)

	def test_initial_column_and_empty_refill_use_first_filterable_column(self):
		def check():
			from fman.impl.ui.table import Table
			from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
			for filterable, expected in (((False, True), 1), ((False, False), 0), ((True, True), 0)):
				schema = TableSchema(tuple(QuickTableColumn(str(index), filterable=value)
					for index, value in enumerate(filterable)))
				table = Table(schema, schema.snapshot((QuickTableRow(('alpha', 'beta')),)))
				try:
					self.assertEqual(expected, table.view.currentIndex().column())
					table.query.setText('missing')
					self.assertFalse(table.view.currentIndex().isValid())
					table.query.clear()
					self.assertEqual(expected, table.view.currentIndex().column())
				finally:
					table.dispose()
					table.deleteLater()
		self.run_in_app(check)

	def test_replace_rows_preserves_presentation_and_rebuilds_identity_caches(self):
		def check():
			from fman.impl.ui.table import Table
			from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
			from fman.impl.ui.table_filters import compile_filter
			schema = TableSchema((QuickTableColumn('Name', 'file_name'), QuickTableColumn('Size', 'numeric')))
			original = schema.snapshot((QuickTableRow(('item10', 1)), QuickTableRow(('item2', 2))))
			replacement = schema.snapshot((QuickTableRow(('item3', 3)), QuickTableRow(('item20', 4)), QuickTableRow(('other', 9))))
			table = Table(schema, original)
			try:
				table.query.setText('item')
				predicate = compile_filter(schema.columns[1], 1, '<=', '5')
				table.set_column_filter(1, predicate)
				for descending in (False, True):
					table.set_sort(0, descending)
					table.view.setCurrentIndex(table.model.index(0, 1))
					self.assertTrue(table.sort_keys)
					table.replace_rows(replacement)
					self.assertTrue(table.settled)
					self.assertEqual(['item20', 'item3'] if descending else ['item3', 'item20'],
						[row.cells[0] for row in table.model.rows])
					self.assertEqual(1, table.view.currentIndex().column())
					self.assertIs(predicate, table.filters[1])
					self.assertEqual('item', table.query.text())
					self.assertEqual((0, 1), table.visible_positions())
					self.assertTrue(all(key[0] in {id(row) for row in replacement} for key in table.model.matches))
			finally:
				table.dispose()
				table.deleteLater()
		self.run_in_app(check)

	def test_replace_rows_rejects_pending_previous_projection(self):
		def check():
			from itertools import count
			from unittest.mock import patch
			from fman.impl.ui.table import Table
			from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
			schema = TableSchema((QuickTableColumn('Name'),))
			rows = schema.snapshot(tuple(QuickTableRow(('alpha%d' % index,)) for index in range(4)))
			table = Table(schema, rows)
			callbacks = []
			try:
				with patch('fman.impl.ui.table.perf_counter', side_effect=count().__next__), \
						patch('fman.impl.ui.table.defer', side_effect=lambda owner, callback: callbacks.append(callback)):
					table.query.setText('a')
					self.assertTrue(table.pending)
					obsolete = callbacks.pop(0)
					replacement = schema.snapshot((QuickTableRow(('beta',)), QuickTableRow(('gamma',))))
					table.replace_rows(replacement)
					obsolete()
					while callbacks:
						callbacks.pop(0)()
				self.assertTrue(table.settled)
				self.assertEqual({'beta', 'gamma'}, {row.cells[0] for row in table.model.rows})
			finally:
				table.dispose()
				table.deleteLater()
		self.run_in_app(check)

	def test_panel_escape_returns_focus_to_last_active_pane(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import TextField, UiOwner, show_panel
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QLineEdit
			from unittest.mock import Mock
			for active_index in (0, 1):
				with self.subTest(active=active_index):
					main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
					panes = [QLineEdit(main), QLineEdit(main)]
					for widget in panes:
						main._central_layout.addWidget(widget)
					pane = DirectoryPane(Window(main, Mock()), panes[0], Mock())
					owner = UiOwner()
					main.show()
					main.activateWindow()
					QApplication.processEvents()
					main._active_pane = panes[active_index]
					panes[active_index].setFocus()
					try:
						panel = show_panel(owner=owner, pane=pane, rows=((TextField('query', 'Query'),),))
						control = _hosts[panel._key()].controls['query'][1]
						QApplication.processEvents()
						self.assertIs(control, QApplication.focusWidget())
						QTest.keyClick(control, Qt.Key_Escape)
						for turn in range(3):
							QApplication.processEvents()
						self.assertFalse(panel.is_open)
						self.assertIsNone(main._panel_dock)
						self.assertIs(panes[active_index], QApplication.focusWidget())
						QTest.keyClicks(panes[active_index], 'ready')
						self.assertEqual('ready', panes[active_index].text())
					finally:
						main._active_pane = None
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
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
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

	def test_show_quick_table_blocks_caller_until_closed(self):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_table
		from PyQt5.QtCore import QTimer
		from PyQt5.QtWidgets import QWidget
		from threading import Thread
		from unittest.mock import patch
		main = self.run_in_app(QWidget)
		self.run_in_app(main.show)
		columns, rows = (QuickTableColumn('Name'),), (QuickTableRow(('one',)),)
		try:
			with patch('fman._get_ui', return_value=main):
				for modal in (True, False):
					with self.subTest(modal=modal, caller='worker'):
						returned = Event()
						worker = Thread(target=lambda: (show_quick_table(columns=columns, rows=rows, modal=modal), returned.set()))
						worker.start()
						window = self.wait_table()
						self.assertEqual(Qt.WindowModal if modal else Qt.NonModal, self.run_in_app(window.windowModality))
						self.assertFalse(returned.wait(.2))
						self.run_in_app(window.close)
						self.assertTrue(returned.wait(5))
						worker.join(5)
				with self.subTest(caller='qt'):
					def nested():
						seen = []
						def close():
							from fman.impl.ui.facade import QuickTableWindow
							window = next(widget for widget in QApplication.topLevelWidgets()
								if isinstance(widget, QuickTableWindow) and widget.alive.is_set())
							seen.append(window.table.model.rowCount())
							QTest.keyClick(window.table.view, Qt.Key_Escape)
						QTimer.singleShot(0, close)
						self.assertIsNone(show_quick_table(columns=columns, rows=rows))
						return seen
					from PyQt5.QtTest import QTest
					self.assertEqual([1], self.run_in_app(nested))
				for invalid in (dict(text_filter='exact'), dict(text_filter=1), dict(truncated=1), dict(columns=()),
						dict(columns=('Name',)), dict(modal=1), dict(rows=lambda: rows), dict(rows=(('one',),)),
						dict(owner=None), dict(accept='Rename')):
					with self.subTest(invalid=invalid), self.assertRaises((TypeError, ValueError)):
						show_quick_table(**dict(dict(columns=columns, rows=rows), **invalid))
		finally:
			self.run_in_app(main.close)
			self.run_in_app(main.deleteLater)

	def test_enter_returns_visible_input_positions(self):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_table
		from fman.impl.ui.facade import QuickTableWindow
		from PyQt5.QtCore import QTimer
		from PyQt5.QtTest import QTest
		from PyQt5.QtWidgets import QAbstractButton, QWidget
		from unittest.mock import patch
		main = self.run_in_app(QWidget)
		self.run_in_app(main.show)
		columns = (QuickTableColumn('Name', 'file_name'), QuickTableColumn('Size', 'numeric', unit='bytes'))
		shared = QuickTableRow(('beta.txt', 5))
		rows = (QuickTableRow(('gamma.jpg', 30)), shared, QuickTableRow(('alpha.jpg', 10)), shared, QuickTableRow(('delta.png', None)))
		def run(interact, **options):
			def nested():
				def act():
					window = next(widget for widget in QApplication.topLevelWidgets()
						if isinstance(widget, QuickTableWindow) and widget.alive.is_set())
					interact(window)
				QTimer.singleShot(0, act)
				return show_quick_table(columns=columns, rows=rows, base_path='C:\\root', **options)
			return self.run_in_app(nested)
		def settle(window):
			for turn in range(20):
				QApplication.processEvents()
				if window.table.settled:
					return
		def text_and_sort(window):
			self.assertFalse([button for button in window.findChildren(QAbstractButton) if button.isVisible()])
			window.table.set_sort(0, True)
			window.table.query.setText('jpg')
			settle(window)
			QTest.keyClick(window.table.query, Qt.Key_Return)
		def column_filter(window):
			from fman.impl.ui.table_filters import compile_filter
			window.table.set_column_filter(1, compile_filter(columns[1], 1, '<=', '5', '', 'B', None))
			settle(window)
			window.table.view.setFocus()
			QTest.keyClick(window.table.view, Qt.Key_Enter, Qt.KeypadModifier)
		def ignored_then_escape(window):
			# Ctrl+Enter without a pane, Enter while projecting and Enter with no visible row keep the window open.
			QTest.keyClick(window.table.view, Qt.Key_Return, Qt.ControlModifier)
			window.table.pending = True
			QTest.keyClick(window.table.view, Qt.Key_Return)
			window.table.pending = False
			window.table.query.setText('no such row')
			settle(window)
			QTest.keyClick(window.table.query, Qt.Key_Return)
			self.assertTrue(window.alive.is_set())
			QTest.keyClick(window.table.view, Qt.Key_Escape)
		try:
			with patch('fman._get_ui', return_value=main):
				# Input order, not the descending display sort; both copies of a shared row.
				self.assertEqual((0, 2), run(text_and_sort))
				self.assertEqual((1, 3), run(column_filter, modal=False))
				self.assertIsNone(run(ignored_then_escape))
				self.assertIsNone(run(lambda window: window.close()))
		finally:
			self.run_in_app(main.close)
			self.run_in_app(main.deleteLater)

	def test_modeless_worker_callers_return_in_close_order(self):
		from fman.ui import QuickTableColumn, QuickTableRow, show_quick_table
		from fman.impl.ui.facade import QuickTableWindow
		from PyQt5.QtWidgets import QWidget
		from threading import Thread
		from time import monotonic, sleep
		from unittest.mock import patch
		main = self.run_in_app(QWidget)
		self.run_in_app(main.show)
		returned = {name: Event() for name in 'AB'}
		def call(name):
			show_quick_table(columns=(QuickTableColumn('Name'),), rows=(QuickTableRow((name,)),), title=name, modal=False)
			returned[name].set()
		def window(title):
			deadline = monotonic() + 5
			while monotonic() < deadline:
				found = self.run_in_app(lambda: [widget for widget in QApplication.topLevelWidgets()
					if isinstance(widget, QuickTableWindow) and widget.alive.is_set() and widget.windowTitle() == title])
				if found:
					return found[0]
				sleep(.02)
			self.fail('Window %s did not open' % title)
		try:
			with patch('fman._get_ui', return_value=main):
				workers = [Thread(target=call, args=(name,)) for name in 'AB']
				workers[0].start()
				first = window('A')
				workers[1].start()
				second = window('B')
				self.run_in_app(first.close)
				self.assertTrue(returned['A'].wait(5), 'A stayed blocked while B was open')
				self.assertFalse(returned['B'].is_set())
				self.run_in_app(second.close)
				self.assertTrue(returned['B'].wait(5))
				for worker in workers:
					worker.join(5)
		finally:
			self.run_in_app(main.close)
			self.run_in_app(main.deleteLater)

	def test_filter_editor_rejects_extreme_exponents_through_text_changes(self):
		def check():
			import sys
			from fman.ui import QuickTableColumn, QuickTableRow
			from fman.impl.ui.facade import open_quick_table
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import patch
			main = QWidget()
			main.show()
			hooks = []
			try:
				with patch('fman._get_ui', return_value=main), patch.object(sys, 'excepthook', lambda *args: hooks.append(args)):
					window = open_quick_table(columns=(QuickTableColumn('Size', 'numeric', unit='bytes'),),
						rows=(QuickTableRow((5,)),), modal=False)
					QApplication.processEvents()
					menu = window.table.open_filter_menu(0)
					editor = menu.actions()[0].defaultWidget()
					apply = next(action for action in menu.actions() if action.text() == 'Apply Filter')
					editor.operator.setCurrentIndex(editor.operator.findData('>='))
					editor.first.setText('1')
					self.assertIsNotNone(editor.compiled)
					self.assertTrue(apply.isEnabled())
					for unit, value in (('B', '1e1000000'), ('B', '-1e1000000'), ('GiB', '1e999999')):
						with self.subTest(unit=unit, value=value):
							editor.unit.setCurrentIndex(editor.unit.findData(unit))
							editor.first.setText(value)
							self.assertIsNone(editor.compiled)
							self.assertFalse(apply.isEnabled())
							self.assertFalse(editor.error.isHidden())
							self.assertIn('out of range', editor.error.text())
							editor.first.setText('1')
							self.assertIsNotNone(editor.compiled)
					self.assertEqual([], hooks)
					menu.close()
					window.close()
			finally:
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_go_to_waits_for_pending_projection(self):
		def check():
			from itertools import count
			from fman.ui import QuickTableColumn, QuickTableRow
			from fman.impl.ui.facade import open_quick_table
			from PyQt5.QtCore import QPoint
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import Mock, patch
			main = QWidget()
			main.show()
			pane = Mock()
			pane.window._widget = main
			calls = []
			window = None
			try:
				with patch('fman.impl.ui.facade.navigate', side_effect=lambda target, url, *args, **kwargs: calls.append(url)):
					window = open_quick_table(columns=(QuickTableColumn('Path', 'file_path'),),
						rows=(QuickTableRow(('old.txt',)), QuickTableRow(('other.txt',))),
						pane=pane, base_path='C:\\root', modal=False)
					QApplication.processEvents()
					table, view = window.table, window.table.view
					view.setCurrentIndex(table.model.index(0, 0))
					view.setFocus()
					# Each clock read advances a second, so every projection slice ends after one row.
					clock = count()
					with patch('fman.impl.ui.table.perf_counter', side_effect=lambda: next(clock)):
						table.query.setText('zzz')
						self.assertTrue(table.pending)
						row, column = table.current_cell
						self.assertEqual('old.txt', row.cells[0])
						QTest.keyClick(view, Qt.Key_Return, Qt.ControlModifier)
						QTest.mouseDClick(view.viewport(), Qt.LeftButton, pos=view.visualRect(view.currentIndex()).center())
						window.open_menu(row, column, QPoint(10, 10))
						go = next(action for action in window.menu.actions() if action.text() == 'Go To')
						self.assertFalse(go.isEnabled())
						window.close_menu()
						window.go_to(row, column, 'C:\\root\\old.txt')
						self.assertEqual([], calls)
						for turn in range(50):
							QApplication.processEvents()
							if table.settled:
								break
					self.assertTrue(table.settled)
					self.assertEqual(0, table.model.rowCount())
					table.query.setText('')
					QApplication.processEvents()
					view.setCurrentIndex(table.model.index(0, 0))
					QTest.keyClick(view, Qt.Key_Return, Qt.ControlModifier)
					self.assertEqual(1, len(calls))
			finally:
				if window is not None:
					window.close()
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_row_targets_drive_copy_path_and_go_to(self):
		def check():
			from fman.ui import QuickTableColumn, QuickTableRow
			from fman.url import as_url
			from fman.impl.ui.facade import open_quick_table
			from pathlib import Path
			from PyQt5.QtCore import QPoint
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QWidget
			from tempfile import TemporaryDirectory
			from unittest.mock import Mock, patch
			main = QWidget()
			main.show()
			pane = Mock()
			pane.window._widget = main
			calls = []
			with TemporaryDirectory() as temporary:
				target = Path(temporary) / 'report\u200b.txt'
				target.write_bytes(b'payload')
				rows = (QuickTableRow(('report\\u200b.txt', 'Matched'), targets=(str(target), None)),
					QuickTableRow(('bad record', 'Invalid record'), targets=(None, None)))
				window = None
				try:
					with patch('fman.impl.ui.facade.navigate', side_effect=lambda target, url, *args, **kwargs: calls.append(url)):
						window = open_quick_table(columns=(QuickTableColumn('Relative Path', 'file_path'), QuickTableColumn('Status')),
							rows=rows, pane=pane, base_path=temporary, modal=False)
						QApplication.processEvents()
						table, view = window.table, window.table.view
						for index, expected in ((0, True), (1, False)):
							row = table.model.rows[index]
							view.setCurrentIndex(table.model.index(index, 0))
							window.open_menu(row, 0, QPoint(10, 10))
							actions = {action.text(): action for action in window.menu.actions()}
							self.assertEqual(expected, 'Go To' in actions)
							actions['Copy Path'].trigger()
							window.close_menu()
							self.assertEqual(str(target) if expected else 'bad record', QApplication.clipboard().text())
							QTest.keyClick(view, Qt.Key_Return, Qt.ControlModifier)
						self.assertEqual([as_url(str(target))], calls)
				finally:
					if window is not None:
						window.close()
					main.close()
					main.deleteLater()
		self.run_in_app(check)

	def test_typed_columns_header_icons_filter_menu_and_sort(self):
		def check():
			import gc
			from fman.ui import QuickTableColumn, QuickTableRow
			from fman.impl.ui.facade import open_quick_table
			from PyQt5.QtCore import QPoint
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import patch
			columns = (QuickTableColumn('Path', 'file_path'), QuickTableColumn('Size', 'numeric', unit='bytes'),
				QuickTableColumn('Modified', 'date'), QuickTableColumn('Note', filterable=False))
			rows = (QuickTableRow(('file10.txt', 2048, 0, 'a')),
				QuickTableRow(('file2.txt', None, None, 'b')),
				QuickTableRow(('file1.txt', 10, 86400 * 10 ** 9, 'c')))
			main = QWidget()
			main.show()
			main.activateWindow()
			QApplication.processEvents()
			try:
				with patch('fman._get_ui', return_value=main):
					window = open_quick_table(columns=columns, rows=rows, base_path='C:\\root', modal=False)
				QApplication.processEvents()
				table = window.table
				header = table.view.horizontalHeader()
				model = table.model
				order = lambda: ''.join(model.rows[index].cells[3] for index in range(model.rowCount()))
				self.assertIsNone(header.icon_rects(3)[1])
				self.assertEqual(frozenset({1}), model.right_aligned)
				filter_rect = header.icon_rects(1)[1]
				QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=filter_rect.center())
				QApplication.processEvents()
				self.assertIsNone(table.sort_column)
				menu = table.filter_menu
				self.assertIsNotNone(menu)
				self.assertEqual('table-filter-menu', menu.objectName())
				editor = menu.actions()[0].defaultWidget()
				labels = [action.text() for action in menu.actions()]
				for label in ('Apply Filter', 'Clear Filter', 'Clear All Filters', 'Sort Ascending', 'Sort Descending', 'Original Order'):
					self.assertIn(label, labels)
				apply = next(action for action in menu.actions() if action.text() == 'Apply Filter')
				self.assertFalse(apply.icon().isNull())
				self.assertFalse(apply.isEnabled())
				editor.operator.setCurrentIndex(editor.operator.findData('>='))
				editor.first.setText('1')
				editor.unit.setCurrentIndex(editor.unit.findData('KiB'))
				self.assertTrue(apply.isEnabled())
				apply.trigger()
				menu.close()
				# Closed menus await deferred deletion; collecting their closure cycles must not crash.
				gc.collect()
				QApplication.processEvents()
				self.assertEqual('a', order())
				self.assertIn('1 column filter', table.counts.text())
				self.assertEqual('Filtered: Size ≥ 1 KiB', table.header_tooltip(1, True))
				table.set_column_filter(1, None)
				self.assertEqual('abc', order())
				label_point = QPoint(header.sectionViewportPosition(1) + 10, header.height() // 2)
				QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=label_point)
				self.assertEqual((1, False), (table.sort_column, table.sort_descending))
				self.assertEqual('cab', order())
				self.assertIsNotNone(header.icon_rects(1)[0])
				QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=label_point)
				self.assertEqual('acb', order())
				table.set_sort(2, True)
				self.assertEqual('cab', order())
				table.set_sort(0)
				self.assertEqual('cba', order())
				table.set_sort(None)
				self.assertEqual('abc', order())
				table.view.setCurrentIndex(model.index(0, 2))
				table.view.setFocus()
				QApplication.processEvents()
				QTest.keyClick(table.view, Qt.Key_Down, Qt.AltModifier)
				QApplication.processEvents()
				self.assertIsNotNone(table.filter_menu)
				editor = table.filter_menu.actions()[0].defaultWidget()
				self.assertEqual('Filter Modified', editor.findChild(QWidget, 'table-filter-title').text())
				# The popup is sized once; Between must fit without squeezing the operator or fields.
				width = editor.sizeHint().width()
				editor.operator.setCurrentIndex(editor.operator.findData('between'))
				QApplication.processEvents()
				self.assertEqual(width, editor.sizeHint().width())
				self.assertGreaterEqual(editor.operator.width(), editor.operator.sizeHint().width())
				self.assertGreaterEqual(editor.second.width(), editor.second.minimumWidth())
				self.assertLessEqual(editor.second.geometry().right(), editor.width())
				editor.operator.setCurrentIndex(editor.operator.findData('missing'))
				editor.submitted.emit()
				QApplication.processEvents()
				self.assertEqual('b', order())
				table.view.setCurrentIndex(model.index(0, 1))
				window.open_menu(model.rows[0], 1, QPoint(10, 10))
				labels = [action.text() for action in window.menu.actions() if not action.isSeparator()]
				self.assertEqual(['Copy Value', 'Filter This Column...', 'Clear All Filters'], labels)
				window.menu.actions()[-1].trigger()
				self.assertEqual('abc', order())
				window.close_menu()
				table.view.setCurrentIndex(model.index(0, 0))
				window.open_menu(model.rows[0], 0, QPoint(10, 10))
				labels = [action.text() for action in window.menu.actions() if not action.isSeparator()]
				self.assertEqual(['Copy Path', 'Go To', 'Filter This Column...', 'Clear All Filters'], labels)
				window.close_menu()
				gc.collect()
				QApplication.processEvents()
				window.close()
			finally:
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_text_filter_hook_and_truncation_note(self):
		def check():
			from fman.ui import QuickTableColumn, QuickTableRow
			from fman.impl.ui.facade import open_quick_table
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import patch
			columns = (QuickTableColumn('Path', 'file_path'), QuickTableColumn('Size', 'numeric'), QuickTableColumn('Note'))
			rows = (QuickTableRow(('alpha.txt', 1, 'Final draft')), QuickTableRow(('beta.txt', 2, 'other')))
			compiled, received = [], []
			def compile_text_filter(query):
				compiled.append(query)
				if query == 'bad':
					raise ValueError('Bad query.')
				def predicate(cells):
					received.append(cells)
					return 1 if query == 'int' else query in cells[1].casefold()
				return predicate
			main = QWidget()
			try:
				with patch('fman._get_ui', return_value=main):
					window = open_quick_table(columns=columns, rows=rows, base_path='C:\\root', modal=False,
						text_filter=compile_text_filter, truncated=True)
				table = window.table
				self.assertEqual('2 / 2 rows \u00b7 truncated', table.counts.text())
				table.query.setText('draft')
				QApplication.processEvents()
				self.assertEqual(1, table.model.rowCount())
				self.assertEqual(['draft'], compiled)
				self.assertEqual(('alpha.txt', 'Final draft'), received[0])
				table.project()
				self.assertEqual(['draft'], compiled)
				for query, message in (('bad', 'Filter error: Bad query.'), ('int', 'Filter error: The text filter must return True or False.')):
					table.query.setText(query)
					QApplication.processEvents()
					self.assertEqual(message, table.counts.text())
					self.assertEqual(0, table.model.rowCount())
				window.close()
				for text_filter, visible in ((None, False), ('substring', True)):
					with patch('fman._get_ui', return_value=main):
						window = open_quick_table(columns=columns, rows=rows, modal=False, text_filter=text_filter)
					table = window.table
					self.assertEqual(visible, not table.query.isHidden())
					self.assertEqual('2 / 2 rows', table.counts.text())
					if visible:
						table.query.setText('ina')
						self.assertEqual(1, table.model.rowCount())
						table.query.setText('fnl')
						self.assertEqual(0, table.model.rowCount())
					window.close()
			finally:
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_real_navigation_modal_closes_and_modeless_stays(self):
		from fman.ui import QuickTableColumn, QuickTableRow
		from fman.impl.navigation import current_request
		from fman.impl.ui.facade import open_quick_table
		from fman.url import as_url
		from PyQt5.QtWidgets import QLineEdit, QWidget
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from unittest.mock import Mock
		for modal in (False, True):
			with self.subTest(modal=modal), TemporaryDirectory() as root:
				path = Path(root, 'file.txt')
				path.write_text('content', encoding='utf-8')
				finished, calls = Event(), []
				def dispatch(command, args):
					calls.append((command, args))
					request = current_request()
					self.assertIsNotNone(request)
					request.started = True
					request.finish('success')
				def prepare():
					main = QWidget()
					main._panel_dock = None
					pane = Mock()
					pane.window._widget = main
					pane._widget = QLineEdit(main)
					pane.on_closed.return_value = lambda: None
					pane.run_command.side_effect = dispatch
					main.show()
					main.activateWindow()
					QApplication.processEvents()
					window = open_quick_table(columns=(QuickTableColumn('File', 'file_path'), QuickTableColumn('Folder', 'folder_path'), QuickTableColumn('Text')),
						rows=(QuickTableRow(('file.txt', root, 'Plain')),), pane=pane, base_path=root, modal=modal)
					window.disposed.connect(finished.set)
					window.busy_changed.connect(lambda busy: None if busy else finished.set())
					column = 0 if modal else 1
					window.table.view.setCurrentIndex(window.table.model.index(0, column))
					window.activate_cell(*window.table.current_cell)
					self.assertTrue(window.busy)
					return main, pane, window
				main, pane, window = self.run_in_app(prepare)
				try:
					self.assertTrue(finished.wait(3))
					self.run_in_app(QApplication.processEvents)
					self.assertEqual([('open_directory', {'url': as_url(str(path) if modal else root)})], calls)
					self.assertEqual(not modal, self.run_in_app(window.alive.is_set))
					if not modal:
						self.assertFalse(self.run_in_app(lambda: window.busy))
						self.assertTrue(self.run_in_app(window.isVisible))
						self.assertIs(pane._widget, self.run_in_app(QApplication.focusWidget))
						self.run_in_app(window.close)
				finally:
					self.run_in_app(main.close)
					self.run_in_app(main.deleteLater)

	def test_directory_pane_styles_unchanged(self):
		def check():
			from pathlib import Path
			from fman.impl.ui.table import Table
			from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
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
				table = Table(TableSchema((QuickTableColumn('One'), QuickTableColumn('Two'))), (QuickTableRow(('Path', 'Text')),))
				table.setStyleSheet(styles.read_text(encoding='utf-8'))
				self.assertEqual(before, pane.grab().toImage())
				table.dispose()
				table.deleteLater()
				pane.close()
				pane.deleteLater()
		self.run_in_app(check)

	def test_facade_panel_values_status_and_disposal(self):
		from fman import DirectoryPane, Window
		from fman.ui import Action, TextField, UiOwner, show_panel
		from fman.impl.widgets import MainWindow
		from PyQt5.QtWidgets import QWidget
		from unittest.mock import Mock
		def prepare():
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
			pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
			main.show()
			main.activateWindow()
			QApplication.processEvents()
			return main, pane
		main, pane = self.run_in_app(prepare)
		owner = UiOwner()
		changes = []
		try:
			panel = show_panel(owner=owner, pane=pane,
				rows=((TextField('pattern', 'Name'), Action('apply', 'Apply')),),
				on_change=lambda values: changes.append(values))
			panel.update(values={'pattern': 'replacement'})
			self.assertEqual('replacement', panel.snapshot()['pattern'])
			self.assertEqual([], changes)
			panel.set_activity_status('Searching')
			self.assertIsNotNone(self.run_in_app(lambda: main.findChild(QWidget, 'plugin-activity-status')))
			panel.close()
			self.assertTrue(panel.cancelled.is_set())
			self.assertFalse(panel.is_open)
		finally:
			owner.invalidate()
			self.run_in_app(main.close)
			self.run_in_app(main.deleteLater)

	def test_panel_status_error_cleanup(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import Action, TextField, Toggle, UiOwner, show_panel
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from PyQt5.QtWidgets import QWidget
			from pathlib import Path
			from unittest.mock import Mock
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
			pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
			root = Path(__file__).parents[3] / 'main/resources/base/Plugins/SearchFiles'
			owner = UiOwner(resource_root=str(root))
			main.show()
			main.activateWindow()
			QApplication.processEvents()
			try:
				panel = show_panel(owner=owner, pane=pane, rows=((TextField('name', 'Name'), Action('apply', 'Apply')),))
				host = _hosts[panel._key()]
				def broken():
					raise ValueError('status failed')
				panel.set_activity_status(get_text=broken)
				self.assertFalse(host.activity_timer.isActive())
				self.assertEqual('status failed', host.status.content)
				panel.close()
				with self.assertRaises(ValueError):
					show_panel(owner=owner, pane=pane, rows=((Toggle('bad', '../outside.svg', 'Bad'),),))
				self.assertFalse(any(item.owner is owner for item in _hosts.values()))
			finally:
				owner.invalidate()
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_modal_close_returns_focus_to_panel(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import QuickTableColumn, QuickTableRow, TextField, UiOwner, show_panel
			from fman.impl.ui.facade import _hosts, open_quick_table
			from fman.impl.widgets import MainWindow
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import Mock
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
			pane = DirectoryPane(Window(main, Mock()), QWidget(main), Mock())
			owner = UiOwner()
			main.show()
			main.activateWindow()
			QApplication.processEvents()
			try:
				panel = show_panel(owner=owner, pane=pane, rows=((TextField('name', 'Name'),),))
				field = _hosts[panel._key()].controls['name'][1]
				window = open_quick_table(columns=(QuickTableColumn('Name'),), rows=(QuickTableRow(('one',)),), pane=pane)
				QApplication.processEvents()
				self.assertIs(window, QApplication.activeModalWidget())
				QTest.keyClick(window.table.view, Qt.Key_Escape)
				for turn in range(3):
					QApplication.processEvents()
				self.assertFalse(window.alive.is_set())
				self.assertIs(field, QApplication.focusWidget())
				self.assertTrue(panel.is_open)
			finally:
				owner.invalidate()
				main.close()
				main.deleteLater()
		self.run_in_app(check)

	def test_fuzzy_sort_and_current_cell(self):
		def check():
			from fman.impl.ui.table import Table
			from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
			rows = (QuickTableRow(('zebra', 'blue')), QuickTableRow(('alpha', 'green')))
			table = Table(TableSchema((QuickTableColumn('Name'), QuickTableColumn('Color'))), rows)
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
			finally:
				table.dispose()
				table.deleteLater()
			for filename in ('CudaText.cmd', 'Cud\u00e1Text.cmd'):
				table = Table(TableSchema((QuickTableColumn('Name'), QuickTableColumn('Text'))), (QuickTableRow((filename, 'text')),))
				try:
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
			from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QAbstractButton
			row = QuickTableRow(('C:\\file', 'text'))
			table = Table(TableSchema((QuickTableColumn('Path'), QuickTableColumn('Text'))), (row,))
			table.resize(500, 240)
			table.show()
			QApplication.processEvents()
			calls, accepts = [], []
			table.view.cell_activated.connect(lambda activated, column: calls.append((activated, column)))
			table.view.accept_requested.connect(lambda: accepts.append(True))
			try:
				self.assertFalse(any(button.isVisible() for button in table.findChildren(QAbstractButton)))
				index = table.model.index(0, 1)
				position = table.view.visualRect(index).center()
				QTest.mouseClick(table.view.viewport(), Qt.LeftButton, pos=position)
				self.assertEqual([], calls)
				self.assertEqual(1, table.current_cell[1])
				QTest.mouseDClick(table.view.viewport(), Qt.LeftButton, pos=position)
				self.assertEqual([(row, 1)], calls)
				# Enter asks for the result; Ctrl+Enter is Go To; other modifiers do nothing.
				for widget in (table.query, table.view):
					QTest.keyClick(widget, Qt.Key_Return)
					QTest.keyClick(widget, Qt.Key_Enter, Qt.KeypadModifier)
					QTest.keyClick(widget, Qt.Key_Return, Qt.ControlModifier)
					QTest.keyClick(widget, Qt.Key_Return, Qt.ShiftModifier)
					QTest.keyClick(widget, Qt.Key_Return, Qt.AltModifier)
				self.assertEqual(4, len(accepts))
				self.assertEqual([(row, 1)] * 3, calls)
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
			self.main = MainWindow(Mock(), theme, Mock(), Mock(), 'null://')
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
		from fman.impl.ui.panel import Panel
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
		from fman.ui import UiController, UiOwner
		from fman.impl.ui.panel import Panel
		from fman.impl.ui.quicklist import QuickList
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
		from fman.impl.ui.panel import Panel, TextButton, IconButton, DropDown, JsonSettings
		from fman.impl.ui.quicklist import QuickList
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
		from fman.ui import UiController, UiOwner
		from fman.impl.ui.panel import Panel, TextButton
		from fman.impl.ui.quicklist import QuickList
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
			main = MainWindow(Mock(), theme, Mock(), Mock(), 'null://')
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
			from fman.impl.ui.panel import Panel, TextButton
			from PyQt5.QtCore import QPoint
			from PyQt5.QtTest import QTest
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import Mock
			window = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
			window._splitter.addWidget(QWidget())
			window._splitter.addWidget(QWidget())
			window.resize(960, 600)
			window.show()
			QApplication.processEvents()
			window.layout().activate()
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
			from fman.ui import ListItem
			from fman.impl.ui.quicklist import QuickList
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
			from fman.ui import ListItem
			from fman.impl.ui.quicklist import QuickList
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

	def test_embedded_view_mouse_selection_and_optional_filter(self):
		def check():
			from fman.ui import ListItem
			from fman.impl.ui.quicklist import QuickList
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
			from fman.impl.ui.panel import Panel, DropDown, TextButton
			from fman.impl.ui.quicklist import QuickList
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

class QuickListServiceIT(QtIT):
	def setUp(self):
		from unittest.mock import Mock, patch
		from fman.impl.widgets import MainWindow
		def create():
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
			main._theme.get_quicksearch_item_css.return_value = None
			main.resize(960, 600)
			main.show()
			return main
		self.main = self.run_in_app(create)
		window_patch = patch('fman.impl.ui.quick_list_window._main_window', return_value=self.main)
		window_patch.start()
		self.addCleanup(window_patch.stop)

	def tearDown(self):
		def dispose():
			self.main.close()
			self.main.deleteLater()
		self.run_in_app(dispose)

	def items(self):
		from fman.ui import ListItem
		return (ListItem('a', 'Zulu', 'C:\\A', metadata={'Added': 1}),
			ListItem('b', 'alpha', 'C:\\B', metadata={'Added': 2}),
			ListItem('c', 'Mike', 'C:\\C', metadata={'Added': ()}))

	def open(self, **arguments):
		"""Run show_quick_list on its own worker; return (handle, window, results, thread)."""
		from fman.ui import show_quick_list
		from threading import Thread
		opened, results = Event(), []
		handles = []
		def on_open(handle):
			handles.append(handle)
			opened.set()
		arguments.setdefault('items', self.items())
		thread = Thread(target=lambda: results.append(show_quick_list(on_open=on_open, **arguments)), daemon=True)
		thread.start()
		self.assertTrue(opened.wait(5))
		handle = handles[0]
		window = handle._QuickListHandle__session.window
		self.run_in_app(lambda: None)
		return handle, window, results, thread

	def finish(self, thread, results):
		thread.join(5)
		self.assertFalse(thread.is_alive())
		return results[0]

	def test_enter_returns_chosen_and_escape_returns_none(self):
		from PyQt5.QtTest import QTest
		handle, window, results, thread = self.open(title='Pick')
		self.assertEqual('Pick', self.run_in_app(window.windowTitle))
		self.assertTrue(self.run_in_app(window.isVisible))
		self.assertTrue(self.run_in_app(lambda: window.windowFlags() & Qt.FramelessWindowHint))
		self.assertEqual('Pick', self.run_in_app(window.header.text))
		def drag():
			from PyQt5.QtCore import QEvent, QPointF
			from PyQt5.QtGui import QMouseEvent
			start = window.pos()
			point = window.header.rect().center()
			def send(kind, local, buttons):
				global_point = QPointF(window.header.mapToGlobal(local))
				QApplication.sendEvent(window.header, QMouseEvent(kind, QPointF(local), global_point,
					Qt.LeftButton, buttons, Qt.NoModifier))
			send(QEvent.MouseButtonPress, point, Qt.LeftButton)
			send(QEvent.MouseMove, point + QPoint(30, 20), Qt.LeftButton)
			send(QEvent.MouseButtonRelease, point + QPoint(30, 20), Qt.NoButton)
			return window.pos() - start
		from PyQt5.QtCore import QPoint
		self.assertEqual(QPoint(30, 20), self.run_in_app(drag))
		self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_Return)
		self.assertEqual(('a',), self.finish(thread, results))
		self.assertFalse(handle.is_open)
		handle, window, results, thread = self.open(selected=('c', 'b'))
		self.assertEqual(('b', 'c'), handle.snapshot().chosen)
		self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_Return)
		self.assertEqual(('b', 'c'), self.finish(thread, results))
		handle, window, results, thread = self.open()
		self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_Escape)
		self.assertIsNone(self.finish(thread, results))

	def test_close_inside_on_open_never_presents(self):
		from fman.ui import show_quick_list
		windows = []
		def on_open(handle):
			windows.append(handle._QuickListHandle__session.window)
			handle.close(('b',))
		self.assertEqual(('b',), show_quick_list(items=self.items(), on_open=on_open))
		self.run_in_app(lambda: None)
		from PyQt5 import sip
		self.assertTrue(self.run_in_app(lambda: windows[0] is None or sip.isdeleted(windows[0]) or not windows[0].isVisible()))
		def failing(handle):
			raise KeyError('driver')
		with self.assertRaises(KeyError):
			show_quick_list(items=self.items(), on_open=failing)

	def test_qt_thread_caller_runs_nested_loop(self):
		from fman.ui import show_quick_list
		from PyQt5.QtCore import QTimer
		def call():
			def on_open(handle):
				QTimer.singleShot(20, lambda: handle.close(('c',)))
			return show_quick_list(items=self.items(), modal=False, on_open=on_open)
		self.assertEqual(('c',), self.run_in_app(call))

	def test_snapshot_set_items_and_close_validation(self):
		from fman.ui import ListItem
		handle, window, results, thread = self.open(selected=('a', 'b'), query='')
		state = handle.snapshot()
		self.assertEqual(('a', 'b'), state.selected)
		self.assertEqual('a', state.current)
		handle.set_items(self.items()[1:])
		state = handle.snapshot()
		self.assertEqual(('b',), state.selected)
		with self.assertRaises(ValueError):
			handle.set_items((ListItem('x', 'X'), ListItem('x', 'Y')))
		with self.assertRaises(ValueError):
			handle.close(('a',))
		self.assertTrue(handle.is_open)
		handle.close(('b', 'c'))
		self.assertEqual(('b', 'c'), self.finish(thread, results))
		handle.set_items(())
		handle.focus()
		handle.close()

	def test_metadata_line_sort_keys_and_saved_sort(self):
		from unittest.mock import patch
		from PyQt5.QtTest import QTest
		saved = Event()
		stored = {'sort': 'Added', 'ascending': False, 'other': 1}
		def save(name, values):
			stored.update(values)
			saved.set()
		with patch('fman.load_json', side_effect=lambda *args, **kwargs: dict(stored)), \
				patch('fman.save_json', side_effect=save):
			handle, window, results, thread = self.open(title_label='Name', hint_label='Path',
				sort=('Name', True), settings='QuickList Test.json')
			def titles():
				return [item.title for item in window.list.model.items]
			self.assertEqual(['alpha', 'Zulu', 'Mike'], self.run_in_app(titles))
			self.assertEqual(('Added', False), handle.snapshot().sort)
			self.assertIn('Added 2', self.run_in_app(lambda: window.list.model.index(0, 0).data()))
			keys = lambda: window.list.sort_keys_label.text()
			self.assertEqual('Sort (Ctrl+F1\u2026F3): Name | Path | Added \u25bc', self.run_in_app(keys))
			self.assertEqual('0 selected (0 hidden)', self.run_in_app(window.list.counts.text))
			self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_F1, Qt.ControlModifier)
			self.assertEqual('Sort (Ctrl+F1\u2026F3): Name \u25b2 | Path | Added', self.run_in_app(keys))
			self.assertEqual(['alpha', 'Mike', 'Zulu'], self.run_in_app(titles))
			self.assertTrue(saved.wait(5))
			self.assertEqual({'sort': 'Name', 'ascending': True, 'other': 1}, stored)
			self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_F1, Qt.ControlModifier)
			self.assertEqual(['Zulu', 'Mike', 'alpha'], self.run_in_app(titles))
			saved.clear()
			self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_F1, Qt.ControlModifier)
			self.assertEqual(['Zulu', 'alpha', 'Mike'], self.run_in_app(titles))
			self.assertIsNone(handle.snapshot().sort)
			self.assertEqual('Sort (Ctrl+F1\u2026F3): Name | Path | Added', self.run_in_app(keys))
			self.assertTrue(saved.wait(5))
			from time import monotonic, sleep
			deadline = monotonic() + 5
			while stored.get('sort') is not None and monotonic() < deadline:
				sleep(.01)
			self.assertIsNone(stored['sort'])
			self.run_in_app(window.list.query.setText, 'a')
			self.assertEqual(['Zulu', 'alpha'], self.run_in_app(titles))
			handle.close()
			self.finish(thread, results)
			handle, window, results, thread = self.open(title_label='Name', sort=('Name', True),
				settings='QuickList Test.json')
			self.assertIsNone(handle.snapshot().sort, 'A saved original order must win over the argument')
			handle.close()
			self.finish(thread, results)

	def test_selection_keys(self):
		from PyQt5.QtTest import QTest
		handle, window, results, thread = self.open(selected=('a',))
		self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_I, Qt.ControlModifier)
		self.assertEqual(('b', 'c'), handle.snapshot().selected)
		self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_A, Qt.ControlModifier | Qt.ShiftModifier)
		self.assertEqual((), handle.snapshot().selected)
		def space():
			window.list.view.setFocus()
			QTest.keyClick(window.list.view, Qt.Key_Space)
		self.run_in_app(space)
		self.assertEqual(('a',), handle.snapshot().selected)
		handle.close()
		self.finish(thread, results)

	def test_global_tab_between_modeless_list_and_panel(self):
		from fman import DirectoryPane, Window
		from fman.ui import Action, UiOwner, show_panel
		from PyQt5.QtTest import QTest
		from PyQt5.QtWidgets import QWidget
		from unittest.mock import Mock
		owner = UiOwner()
		pane = self.run_in_app(lambda: DirectoryPane(Window(self.main, Mock()), QWidget(self.main), Mock()))
		def opened(handle):
			show_panel(owner=owner, pane=pane, rows=((Action('run', 'Run'), Action('stop', 'Stop')),),
				on_closed=handle.close)
		from fman.ui import show_quick_list
		from threading import Thread
		results, handles = [], []
		def on_open(handle):
			handles.append(handle)
			opened(handle)
		thread = Thread(target=lambda: results.append(show_quick_list(items=self.items(), modal=False,
			on_open=on_open)), daemon=True)
		thread.start()
		try:
			from time import monotonic, sleep
			deadline = monotonic() + 5
			while not handles and monotonic() < deadline:
				sleep(.01)
			window = handles[0]._QuickListHandle__session.window
			def check():
				dock = self.main._panel_dock
				window.activateWindow()
				window.list.view.setFocus()
				QApplication.processEvents()
				QTest.keyClick(window.list.view, Qt.Key_Tab)
				QApplication.processEvents()
				first = QApplication.focusWidget()
				self.assertTrue(dock.isAncestorOf(first))
				self.main.activateWindow()
				dock.close_button.setFocus()
				QApplication.processEvents()
				QTest.keyClick(dock.close_button, Qt.Key_Tab)
				QApplication.processEvents()
				self.assertIs(window.list.query, QApplication.focusWidget())
				QTest.mouseClick(dock.close_button, Qt.LeftButton)
			self.run_in_app(check)
			self.assertIsNone(self.finish(thread, results))
		finally:
			owner.invalidate()

	def test_slow_on_open_keeps_window_hidden(self):
		from fman.ui import show_quick_list
		from threading import Thread
		from PyQt5.QtTest import QTest
		entered, release, results, handles = Event(), Event(), [], []
		def on_open(handle):
			handles.append(handle)
			entered.set()
			release.wait(5)
		thread = Thread(target=lambda: results.append(show_quick_list(items=self.items(), on_open=on_open)), daemon=True)
		thread.start()
		self.assertTrue(entered.wait(5))
		window = handles[0]._QuickListHandle__session.window
		self.assertFalse(self.run_in_app(window.isVisible))
		self.assertTrue(handles[0].is_open)
		release.set()
		from time import monotonic, sleep
		deadline = monotonic() + 5
		while not self.run_in_app(window.isVisible) and monotonic() < deadline:
			sleep(.01)
		self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_Escape)
		self.assertIsNone(self.finish(thread, results))

	def test_invalid_set_items_and_requested_sort_after_refill(self):
		from fman.ui import ListItem
		handle, window, results, thread = self.open(items=(), sort=('Added', False))
		self.assertIsNone(handle.snapshot().sort)
		with self.assertRaises((TypeError, ValueError)):
			handle.set_items((ListItem('x', 'X', metadata=(('Added', float('nan'), 'x'),)),))
		self.assertEqual((), self.run_in_app(lambda: window.list.items))
		handle.set_items(self.items())
		self.assertEqual(('Added', False), handle.snapshot().sort)
		self.assertEqual(['alpha', 'Zulu', 'Mike'],
			self.run_in_app(lambda: [item.title for item in window.list.model.items]))
		handle.close()
		self.finish(thread, results)

	def test_failed_sort_save_does_not_block_qt(self):
		from unittest.mock import Mock, patch
		from time import perf_counter
		from PyQt5.QtTest import QTest
		release, reported = Event(), Event()
		def save(name, values):
			release.wait(5)
			raise PermissionError('read-only')
		status = Mock(side_effect=lambda *args, **kwargs: reported.set())
		with patch('fman.load_json', return_value={}), patch('fman.save_json', side_effect=save), \
				patch('fman.show_status_message', status):
			handle, window, results, thread = self.open(title_label='Name', settings='QuickList ReadOnly.json')
			started = perf_counter()
			self.run_in_app(QTest.keyClick, window.list.query, Qt.Key_F1, Qt.ControlModifier)
			self.assertLess(perf_counter() - started, 1)
			self.assertEqual(('Name', True), handle.snapshot().sort)
			release.set()
			self.assertTrue(reported.wait(5))
			self.assertIn('read-only', status.call_args.args[0])
			handle.close()
			self.finish(thread, results)

	def test_global_tab_two_lists_and_panel_alone(self):
		from fman import DirectoryPane, Window
		from fman.impl.ui.quick_list_window import recent_list
		from fman.ui import Action, UiOwner, show_panel
		from PyQt5.QtCore import QEvent
		from PyQt5.QtTest import QTest
		from PyQt5.QtWidgets import QWidget
		from unittest.mock import Mock
		owner = UiOwner()
		pane = self.run_in_app(lambda: DirectoryPane(Window(self.main, Mock()), QWidget(self.main), Mock()))
		try:
			show_panel(owner=owner, pane=pane, rows=((Action('run', 'Run'),),))
			def panel_alone():
				dock = self.main._panel_dock
				self.main.activateWindow()
				dock.close_button.setFocus()
				QApplication.processEvents()
				QTest.keyClick(dock.close_button, Qt.Key_Tab)
				QApplication.processEvents()
				self.assertTrue(dock.isAncestorOf(QApplication.focusWidget()))
			self.run_in_app(panel_alone)
			first = self.open(modal=False)
			second = self.open(modal=False)
			self.assertIs(second[1], self.run_in_app(recent_list, self.main))
			self.run_in_app(lambda: QApplication.sendEvent(first[1], QEvent(QEvent.WindowActivate)))
			self.assertIs(first[1], self.run_in_app(recent_list, self.main))
			first[0].close()
			self.finish(first[3], first[2])
			self.assertIs(second[1], self.run_in_app(recent_list, self.main))
			second[0].close()
			self.finish(second[3], second[2])
			self.assertIsNone(self.run_in_app(recent_list, self.main))
		finally:
			owner.invalidate()

	def test_owner_invalidation_and_main_window_close(self):
		from fman.ui import UiOwner
		owner = UiOwner()
		handle, window, results, thread = self.open(modal=False)
		self.assertTrue(owner.attach(handle.close))
		owner.invalidate()
		self.assertIsNone(self.finish(thread, results))
		handle, window, results, thread = self.open(modal=False)
		self.run_in_app(self.main.close)
		self.assertIsNone(self.finish(thread, results))

class QuickListLimitIT(QtIT):
	"""Opt-in: set QUICKLIST_BENCHMARK=1. Limits are ~4x the first native measurement (68/24/23 ms)."""

	def test_filter_and_sort_at_item_limit(self):
		import os
		if os.environ.get('QUICKLIST_BENCHMARK') != '1':
			self.skipTest('Set QUICKLIST_BENCHMARK=1 to run the 10,000-item QuickList gate.')
		def measure():
			from statistics import median
			from time import perf_counter
			from fman.impl.ui import ListItem
			from fman.impl.ui.quick_list_data import MAX_ITEMS, prepare_items
			from fman.impl.ui.quicklist import QuickList
			labels = ['Field%d' % index for index in range(8)]
			items = tuple(ListItem('id%05d' % row, 'Title %05d ' % row + 't' * 200, 'C:\\Folder\\' + 'h' * 300 + str(row),
				metadata={label: (row * 7919 % 10007 + column, 'v%05d ' % row + 'x' * 121)
					for column, label in enumerate(labels)}) for row in range(MAX_ITEMS))
			prepared = prepare_items(items, 'Name', 'Path')
			widget = QuickList(fuzzy=True)
			try:
				widget.resize(680, 430)
				widget.show()
				QApplication.processEvents()
				started = perf_counter()
				widget.set_sortable_items(prepared.items, prepared.labels, prepared.keys)
				QApplication.processEvents()
				applied = perf_counter() - started
				filters, sorts = [], []
				for query in ('t', 'ti', 'tit', '123', '9', '', 'h12', 'x'):
					started = perf_counter()
					widget.query.setText(query)
					QApplication.processEvents()
					filters.append(perf_counter() - started)
				widget.query.clear()
				for position in (0, 1, 2, 3, 9, 0, 5, 2):
					started = perf_counter()
					widget.sort_by(position)
					QApplication.processEvents()
					sorts.append(perf_counter() - started)
				return applied * 1000, median(filters) * 1000, median(sorts) * 1000
			finally:
				widget.deleteLater()
		applied, filtered, sorted_ = self.run_in_app(measure)
		print('QuickList 10,000 items: apply %.1f ms, filter median %.1f ms, sort median %.1f ms' % (applied, filtered, sorted_))
		self.assertLess(applied, 300)
		self.assertLess(filtered, 100)
		self.assertLess(sorted_, 100)

class PanelIT(QtIT):
	def test_textfield_tooltip_is_on_label_and_input(self):
		def check():
			from fman import DirectoryPane, Window
			from fman.ui import TextField, UiOwner, show_panel
			from fman.impl.ui.facade import _hosts
			from fman.impl.widgets import MainWindow
			from PyQt5.QtWidgets import QWidget
			from unittest.mock import Mock
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
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
			from fman.impl.ui.panel import Panel, TextButton, DropDown
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
		from fman.ui import UiOwner
		from fman.impl.ui.panel import Panel, DropDown, TextButton, JsonSettings
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
		from fman.impl.ui.panel import Panel, DropDown, TextButton, JsonSettings
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
		from fman.impl.ui.panel import Panel, IconButton, TextButton, DropDown, JsonSettings
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
	def setUp(self):
		from copy import deepcopy
		from unittest.mock import Mock, patch
		from favorites.ui import FavoritesController
		from fman.impl.widgets import MainWindow
		from fman.ui import UiOwner
		from PyQt5.QtWidgets import QWidget
		self.data = {'favorites': [{'name': 'Zulu', 'url': 'file:///C:/A'},
			{'name': 'Alpha', 'url': 'file:///C:/Z'}, {'name': 'Other', 'url': 'example://Other'}]}
		def save(name, values):
			self.data = deepcopy(values)
		def create():
			from fman import DirectoryPane
			main = MainWindow(Mock(), Mock(), Mock(), Mock(), 'null://')
			main._theme.get_quicksearch_item_css.return_value = None
			main.resize(960, 600)
			main.show()
			pane = Mock()
			pane._widget = QWidget(main)
			pane.window._widget = main
			pane.on_closed = DirectoryPane.on_closed.__get__(pane)
			return main, pane
		self.main, self.pane = self.run_in_app(create)
		self.owner = UiOwner()
		self.alert, self.status = Mock(), Mock()
		for patcher in (patch('fman.impl.ui.quick_list_window._main_window', return_value=self.main),
				patch('fman.impl.ui.quick_list_window._load_sort', return_value=None),
				patch('favorites.load_json', side_effect=lambda *args, **kwargs: deepcopy(self.data)),
				patch('favorites.save_json', side_effect=save),
				patch('favorites.ui.show_alert', self.alert),
				patch('favorites.ui.show_status_message', self.status),
				patch.object(FavoritesController, 'owner', self.owner)):
			patcher.start()
			self.addCleanup(patcher.stop)

	def tearDown(self):
		self.owner.invalidate()
		def dispose():
			self.main.close()
			self.main.deleteLater()
		self.run_in_app(dispose)

	def wait_until(self, predicate, message):
		from time import monotonic, sleep
		deadline = monotonic() + 5
		while monotonic() < deadline:
			if self.run_in_app(predicate):
				return
			sleep(.01)
		self.fail(message)

	def open(self, query=''):
		from favorites.ui import _sessions, show_manager
		from fman.impl.ui.facade import _hosts
		from threading import Thread
		previous = _sessions.get(self.pane.window)
		thread = Thread(target=show_manager, args=(self.pane, query), daemon=True)
		thread.start()
		self.wait_until(lambda: _sessions.get(self.pane.window) not in (None, previous) and
			_sessions[self.pane.window].panel is not None, 'Manager did not open')
		session = _sessions[self.pane.window]
		self.wait_until(lambda: session.revision >= 0, 'Manager did not load')
		self.session, self.thread = session, thread
		self.window = session.handle._QuickListHandle__session.window
		self.host = _hosts[session.panel._key()]
		return session

	def titles(self):
		return self.run_in_app(lambda: [item.title for item in self.window.list.model.items])

	def click(self, action):
		from PyQt5.QtTest import QTest
		self.run_in_app(QTest.mouseClick, self.host.controls[action][1], Qt.LeftButton)

	def closed(self):
		self.thread.join(5)
		self.assertFalse(self.thread.is_alive())
		self.assertFalse(self.session.is_open)
		self.assertIsNone(self.run_in_app(lambda: self.main._panel_dock))

	def test_manager_uses_public_services_only(self):
		from favorites.ui import FavoritesSession
		from fman.impl.ui.quick_list_window import QuickListWindow
		from PyQt5.QtCore import QObject
		self.open()
		self.assertNotIsInstance(self.session, QObject)
		self.assertIs(QuickListWindow, type(self.window))
		self.assertIs(FavoritesSession, type(self.session))
		self.assertEqual(['Zulu', 'Alpha', 'Other'], self.titles())
		self.assertEqual(('Name', 'Path', 'Added', 'Last opened', 'Opened'),
			self.run_in_app(lambda: self.window.list.sort_labels))
		self.assertEqual('Favorites UI.json', self.window.settings)
		self.assertFalse(self.window.modal)
		self.assertIs(self.host.panel, self.run_in_app(lambda: self.main._panel_dock.panel))

	def test_delete_removes_chosen_without_confirmation(self):
		from favorites.ui import item_id
		self.open()
		def select():
			self.window.list.selected_ids = {item_id('file:///C:/Z'), item_id('example://Other')}
			self.window.list.refresh()
		self.run_in_app(select)
		self.click('delete')
		self.wait_until(lambda: [item.title for item in self.window.list.model.items] == ['Zulu'], 'Delete not shown')
		self.assertEqual(['Zulu'], [entry['name'] for entry in self.data['favorites']])
		self.assertTrue(self.session.is_open)
		self.alert.assert_not_called()

	def test_delete_key_does_nothing(self):
		from PyQt5.QtTest import QTest
		self.open()
		def press():
			self.window.list.view.setFocus()
			QTest.keyClick(self.window.list.view, Qt.Key_Delete)
		self.run_in_app(press)
		self.assertEqual(3, len(self.data['favorites']))

	def test_rename_targets_current(self):
		from unittest.mock import patch
		self.open()
		with patch('favorites.ui.show_prompt', return_value=(' Renamed ', True)) as prompt:
			self.click('rename')
			self.wait_until(lambda: 'Renamed' in [item.title for item in self.window.list.model.items], 'Rename not shown')
		self.assertEqual('Zulu', prompt.call_args.args[1])
		self.assertEqual('Renamed', self.data['favorites'][0]['name'])

	def navigate_succeeds(self):
		self.pane.set_path.side_effect = lambda url, callback=None, onerror=None: callback()

	def test_go_to_success_closes_manager_and_panel(self):
		from unittest.mock import patch
		self.open()
		self.navigate_succeeds()
		with patch('favorites.ui.exists', return_value=True), patch('favorites.ui.is_dir', return_value=True):
			self.click('go_to')
			self.closed()
		self.assertEqual('file:///C:/A', self.pane.set_path.call_args.args[0])
		self.wait_until(lambda: self.data['favorites'][0].get('count') == 1, 'Use not recorded')
		self.assertIn('opened', self.data['favorites'][0])
		self.open()
		self.assertIn('Opened 1', self.run_in_app(lambda: self.window.list.model.index(0, 0).data()))

	def test_enter_goes_to_single_chosen(self):
		from unittest.mock import patch
		from PyQt5.QtTest import QTest
		self.open('Alp')
		self.navigate_succeeds()
		with patch('favorites.ui.exists', return_value=True), patch('favorites.ui.is_dir', return_value=True):
			self.run_in_app(QTest.keyClick, self.window.list.query, Qt.Key_Return)
			self.closed()
		self.assertEqual('file:///C:/Z', self.pane.set_path.call_args.args[0])

	def test_go_to_closes_only_after_navigation_succeeds(self):
		from unittest.mock import patch
		calls = []
		self.pane.set_path.side_effect = lambda url, callback=None, onerror=None: calls.append((callback, onerror))
		self.open()
		with patch('favorites.ui.exists', return_value=True), patch('favorites.ui.is_dir', return_value=True):
			self.click('go_to')
			self.wait_until(lambda: len(calls) == 1, 'Navigation not started')
			self.assertEqual('file:///C:/A', calls[0][1](PermissionError('denied'), 'file:///C:/A'))
			self.wait_until(lambda: self.alert.called, 'No navigation failure alert')
			self.assertIn('denied', self.alert.call_args.args[0])
			self.assertTrue(self.session.is_open)
			idle = lambda: not self.session.action_lock.locked()
			self.wait_until(idle, 'Action lock not released')
			self.click('go_to')
			self.wait_until(lambda: len(calls) == 2, 'Second navigation not started')
			self.wait_until(idle, 'Action lock not released')
			self.click('go_to')
			self.wait_until(lambda: len(calls) == 3, 'Third navigation not started')
			self.run_in_app(calls[1][0])
			self.assertTrue(self.session.is_open, 'A superseded navigation closed the manager')
			self.run_in_app(calls[2][0])
			self.closed()
			calls[2][1](PermissionError('late'), 'file:///C:/A')
		self.assertEqual(1, self.alert.call_count)

	def test_go_to_synchronous_failure_alerts(self):
		from unittest.mock import patch
		def fail(url, callback=None, onerror=None):
			error = PermissionError('denied')
			if onerror(error, url) == url:
				raise error
		self.pane.set_path.side_effect = fail
		self.open()
		with patch('favorites.ui.exists', return_value=True), patch('favorites.ui.is_dir', return_value=True):
			self.click('go_to')
			self.wait_until(lambda: self.alert.called, 'No navigation failure alert')
		self.assertEqual(1, self.alert.call_count)
		self.assertTrue(self.session.is_open)

	def test_action_failure_alerts_and_releases_lock(self):
		from unittest.mock import patch
		self.open()
		with patch('favorites.save_json', side_effect=OSError('disk full')):
			self.click('delete')
			self.wait_until(lambda: self.alert.called, 'No failure alert')
		self.assertIn('disk full', self.alert.call_args.args[0])
		self.assertEqual(3, len(self.data['favorites']))
		self.assertEqual(['Zulu', 'Alpha', 'Other'], self.titles())
		self.wait_until(lambda: not self.session.action_lock.locked(), 'Action lock not released')
		self.click('delete')
		self.wait_until(lambda: len(self.data['favorites']) == 2, 'Retry did not delete')

	def test_rename_prompt_after_close_changes_nothing(self):
		from unittest.mock import patch
		asked, answer = Event(), Event()
		def prompt(*args):
			asked.set()
			answer.wait(5)
			return 'Renamed', True
		self.open()
		with patch('favorites.ui.show_prompt', side_effect=prompt):
			self.click('rename')
			self.assertTrue(asked.wait(5))
			self.session.handle.close()
			self.closed()
			answer.set()
			self.wait_until(lambda: not self.session.action_lock.locked(), 'Rename did not finish')
		self.assertEqual('Zulu', self.data['favorites'][0]['name'])

	def test_long_names_and_urls_open_and_act(self):
		from favorites.ui import item_id
		long_url = 'file:///C:/' + '/'.join(['folder%03d' % index for index in range(60)])
		self.data = {'favorites': [{'name': 'N' * 600, 'url': long_url}, {'name': 'Short', 'url': 'file:///C:/A'}]}
		self.open()
		titles = self.titles()
		self.assertEqual(512, len(titles[0]))
		self.assertEqual(40, len(item_id(long_url)))
		self.run_in_app(lambda: (self.window.list.selected_ids.add(item_id(long_url)), self.window.list.refresh()))
		self.click('delete')
		self.wait_until(lambda: self.titles() == ['Short'], 'Long favorite not deleted')

	def test_rename_across_title_limit_and_reopen(self):
		from unittest.mock import patch
		self.open()
		with patch('favorites.ui.show_prompt', return_value=('R' * 600, True)):
			self.click('rename')
			self.wait_until(lambda: self.titles()[0].startswith('RRR'), 'Long rename not shown')
		self.assertEqual('R' * 600, self.data['favorites'][0]['name'])
		self.assertEqual(512, len(self.titles()[0]))
		self.session.handle.close()
		self.closed()
		self.open()
		self.assertEqual(512, len(self.titles()[0]))
		with patch('favorites.ui.show_prompt', return_value=('Short again', True)):
			self.wait_until(lambda: not self.session.action_lock.locked(), 'Action lock busy')
			self.click('rename')
			self.wait_until(lambda: self.titles()[0] == 'Short again', 'Rename back not shown')

	def test_rename_write_failure_alerts_and_keeps_name(self):
		from unittest.mock import patch
		self.open()
		with patch('favorites.ui.show_prompt', return_value=('Renamed', True)), \
				patch('favorites.save_json', side_effect=PermissionError('read-only')):
			self.click('rename')
			self.wait_until(lambda: self.alert.called, 'No rename failure alert')
		self.assertIn('read-only', self.alert.call_args.args[0])
		self.assertEqual('Zulu', self.data['favorites'][0]['name'])
		self.assertEqual('Zulu', self.titles()[0])
		self.assertTrue(self.session.is_open)

	def test_open_from_other_pane_keeps_one_list_and_panel(self):
		from unittest.mock import Mock
		from fman import DirectoryPane
		from fman.impl.ui.quick_list_window import QuickListWindow
		first = self.open()
		first_thread = self.thread
		other = Mock()
		def create():
			from PyQt5.QtWidgets import QWidget
			other._widget = QWidget(self.main)
			other.window = self.pane.window
			other.on_closed = DirectoryPane.on_closed.__get__(other)
		self.run_in_app(create)
		pane, self.pane = self.pane, other
		try:
			self.open()
		finally:
			self.pane = pane
		first_thread.join(5)
		self.assertFalse(first.is_open)
		def surfaces():
			QApplication.processEvents()
			lists = [widget for widget in QApplication.topLevelWidgets()
				if isinstance(widget, QuickListWindow) and widget.isVisible()]
			return len(lists), self.main._panel_dock.panel is self.host.panel
		self.assertEqual((1, True), self.run_in_app(surfaces))
		self.assertTrue(self.session.is_open)

	def test_go_to_failures_alert_and_keep_manager(self):
		from unittest.mock import patch
		self.open()
		with patch('favorites.ui.exists', return_value=False):
			self.click('go_to')
			self.wait_until(lambda: self.alert.called, 'No missing-location alert')
		self.assertIn('Favorite location not found', self.alert.call_args.args[0])
		with patch('favorites.ui.exists', return_value=True), patch('favorites.ui.is_dir', return_value=False):
			self.click('go_to')
			self.wait_until(lambda: self.alert.call_count == 2, 'No folder-only alert')
		self.assertIn('Favorites must point to folders', self.alert.call_args.args[0])
		def select():
			from favorites.ui import item_id
			self.window.list.selected_ids = {item_id('file:///C:/A'), item_id('file:///C:/Z')}
			self.window.list.refresh()
		self.run_in_app(select)
		self.click('go_to')
		self.wait_until(lambda: self.status.called, 'No single-choice message')
		self.assertTrue(self.session.is_open)
		self.pane.set_path.assert_not_called()

	def test_dock_close_and_escape_end_both(self):
		from PyQt5.QtTest import QTest
		self.open()
		self.run_in_app(QTest.mouseClick, self.main._panel_dock.close_button, Qt.LeftButton)
		self.closed()
		self.open()
		self.run_in_app(QTest.keyClick, self.window.list.query, Qt.Key_Escape)
		self.closed()

	def test_show_again_focuses_or_replaces_with_query(self):
		from favorites.ui import show_manager
		first = self.open()
		show_manager(self.pane)
		self.assertTrue(first.is_open)
		first_thread = self.thread
		self.open('Zul')
		first_thread.join(5)
		self.assertFalse(first.is_open)
		self.assertEqual('Zul', self.run_in_app(self.window.list.query.text))
		self.assertEqual(['Zulu'], self.titles())

	def test_external_commit_refreshes_and_keeps_query(self):
		import favorites
		from favorites.ui import mutate
		self.open()
		self.run_in_app(self.window.list.query.setText, 'l')
		mutate((favorites._snapshot()[0][1],), 'Lima', self.owner)
		self.wait_until(lambda: 'Lima' in [item.title for item in self.window.list.model.items], 'Commit not shown')
		self.assertEqual('l', self.run_in_app(self.window.list.query.text))

	def test_unload_closes_manager(self):
		self.open()
		self.owner.invalidate()
		self.closed()


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