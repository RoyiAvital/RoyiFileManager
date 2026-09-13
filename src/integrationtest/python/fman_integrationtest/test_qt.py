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