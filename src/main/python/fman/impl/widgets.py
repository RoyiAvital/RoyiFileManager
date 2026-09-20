from fbs_runtime.platform import is_windows, is_mac
from fman import OK
from fman.impl.filter_pattern import compile_filter, MAX_FILTER_LENGTH
from fman.impl.model import SortedFileSystemModel
from fman.impl.quicksearch import Quicksearch
from fman.impl.status_bar import ACTIVE_PANE, DISABLED, PER_PANE, \
	PaneStatusSnapshot, PaneStatusWidget, StatusCalculationService, \
	set_size_divisor
from fman.impl.util.qt import disable_window_animations_mac, Key_Escape, \
	NoFocus, Key_Backspace, DisplayRole
from fman.impl.util.qt.thread import run_in_main_thread
from fman.impl.view.location_bar import LocationBar
from fman.impl.view import FileListView, Layout, set_selection
from fman.url import as_human_readable, basename, dirname
from PyQt5.QtCore import pyqtSignal, QTimer, Qt, QEvent, QSize
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QWidget, QMainWindow, QSplitter, QStatusBar, \
	QMessageBox, QInputDialog, QLineEdit, QFileDialog, QLabel, QDialog, \
	QHBoxLayout, QPushButton, QVBoxLayout, QSplitterHandle, QApplication, \
	QFrame, QAction, QSizePolicy, QProgressDialog, QProgressBar
from PyQt5 import sip

class Application(QApplication):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._main_window = None
		self.applicationStateChanged.connect(self._on_state_changed)
	def set_main_window(self, main_window):
		self._main_window = main_window
		# Ensure all other windows are closed as well when the main window
		# is closed. (This in particular closes windows opened by plugins.)
		main_window.closed.connect(self.quit)
	@run_in_main_thread
	def exit(self, returnCode=0):
		if self._main_window is not None:
			self._main_window.close()
		super().exit(returnCode)
	@run_in_main_thread
	def set_style_sheet(self, stylesheet):
		self.setStyleSheet(stylesheet)
	def _on_state_changed(self, new_state):
		if new_state == Qt.ApplicationActive:
			for pane in self._main_window.get_panes():
				pane.reload()

class DirectoryPaneWidget(QWidget):

	location_changed = pyqtSignal(QWidget)
	location_bar_clicked = pyqtSignal(QWidget)
	status_changed = pyqtSignal()
	filter_changed = pyqtSignal(str, int, int)
	filter_cleared = pyqtSignal()

	def __init__(self, fs, null_location, parent, controller):
		super().__init__(parent)
		self._location_bar = LocationBar(self)
		self._model = SortedFileSystemModel(self, fs, null_location)
		self._model.file_renamed.connect(self._on_file_renamed)
		self._model.files_dropped.connect(self._on_files_dropped)
		self._file_view = FileListView(
			self, lambda *args: controller.on_context_menu(self, *args)
		)
		self._file_view.setModel(self._model)
		self._file_view.doubleClicked.connect(self._on_doubleclicked)
		self._file_view.key_press_event_filter = self._on_key_pressed
		self.setLayout(Layout(self._location_bar, self._file_view))
		self._location_bar.setFocusProxy(self._file_view)
		self.setFocusProxy(self._file_view)
		self._controller = controller
		self._model.location_changed.connect(self._on_location_changed)
		self._model.location_loaded.connect(self._on_location_loaded)
		self._location_bar.clicked.connect(
			lambda: self.location_bar_clicked.emit(self)
		)
		self._filter_bar = FilterBar(self, self._model, self._file_view)
		self._filter_bar.filter_changed.connect(self.filter_changed)
		self._filter_bar.filter_cleared.connect(self.filter_cleared)
		self._hidden_files_shown = False
		self._status_widget = None
		self._status_tracking = False
		self._column_widths_by_name = {}
	def resizeEvent(self, e):
		super().resizeEvent(e)
		self._filter_bar.reposition()
	@run_in_main_thread
	def move_cursor_up(self, toggle_selection=False):
		self._file_view.move_cursor_up(toggle_selection)
	@run_in_main_thread
	def move_cursor_down(self, toggle_selection=False):
		self._file_view.move_cursor_down(toggle_selection)
	@run_in_main_thread
	def move_cursor_home(self, toggle_selection=False):
		self._file_view.move_cursor_home(toggle_selection)
	@run_in_main_thread
	def move_cursor_end(self, toggle_selection=False):
		self._file_view.move_cursor_end(toggle_selection)
	@run_in_main_thread
	def move_cursor_page_up(self, toggle_selection=False):
		self._file_view.move_cursor_page_up(toggle_selection)
	@run_in_main_thread
	def move_cursor_page_down(self, toggle_selection=False):
		self._file_view.move_cursor_page_down(toggle_selection)
	@run_in_main_thread
	def focus(self):
		self.setFocus()
	@run_in_main_thread
	def select_all(self):
		self._file_view.selectAll()
	@run_in_main_thread
	def clear_selection(self):
		self._file_view.clearSelection()
	@run_in_main_thread
	def toggle_selection(self, file_url):
		self._file_view.toggle_selection(file_url)
	@run_in_main_thread
	def select(self, file_urls, ignore_errors=False):
		self._file_view.select(file_urls, ignore_errors)
	@run_in_main_thread
	def deselect(self, file_urls, ignore_errors=False):
		self._file_view.deselect(file_urls, ignore_errors)
	@run_in_main_thread
	def get_selected_files(self):
		return self._file_view.get_selected_files()
	@run_in_main_thread
	def get_file_under_cursor(self):
		return self._file_view.get_file_under_cursor()
	@run_in_main_thread
	def get_location(self):
		return self._model.get_location()
	def set_location(
		self, url, sort_column='', ascending=True, callback=None, onerror=None
	):
		self._model.set_location(url, sort_column, ascending, callback, onerror)
	def reload(self):
		self._model.reload()
	@run_in_main_thread
	def place_cursor_at(self, file_url):
		self._file_view.place_cursor_at(file_url)
	@run_in_main_thread
	def edit_name(self, file_url, selection_start=0, selection_end=None):
		self._file_view.edit_name(file_url, selection_start, selection_end)
	@run_in_main_thread
	def add_filter(self, filter_):
		self._model.add_filter(filter_)
	@run_in_main_thread
	def remove_filter(self, filter_):
		self._model.remove_filter(filter_)
	@run_in_main_thread
	def is_filtering(self):
		return self._filter_bar.is_active()
	@run_in_main_thread
	def publish_filter_count(self):
		self._filter_bar.publish_count()
	def set_hidden_files_shown(self, value):
		self._hidden_files_shown = value
		self.status_changed.emit()
	@property
	def hidden_files_shown(self):
		return self._hidden_files_shown
	def get_status_snapshot(self):
		selected_urls = set(self.get_selected_files())
		entries = self._model.get_status_entries(selected_urls)
		return PaneStatusSnapshot(
			self._model.get_location(), entries,
			all(entry.is_loaded for entry in entries),
			self._hidden_files_shown
		)
	def set_status_widget(self, widget):
		if self._status_widget is not None:
			self.layout().removeWidget(self._status_widget)
		self._status_widget = widget
		if widget is not None:
			self.layout().addWidget(widget)
	def enable_status_tracking(self):
		if self._status_tracking:
			return
		self._status_tracking = True
		self._file_view.selectionModel().selectionChanged.connect(
			self._on_status_changed
		)
		self._model.transaction_ended.connect(self._on_status_changed)
		self._model.all_rows_loaded.connect(self._on_status_changed)
	def disable_status_tracking(self):
		if not self._status_tracking:
			return
		self._status_tracking = False
		self._file_view.selectionModel().selectionChanged.disconnect(
			self._on_status_changed
		)
		self._model.transaction_ended.disconnect(self._on_status_changed)
		self._model.all_rows_loaded.disconnect(self._on_status_changed)
	def _on_status_changed(self, *_):
		self.status_changed.emit()
	@property
	def window(self):
		return self.parentWidget().parentWidget()
	def get_columns(self):
		return [
			column.get_qualified_name() for column in self._model.get_columns()
		]
	@run_in_main_thread
	def set_sort_column(self, column, ascending=True):
		column_index = self.get_columns().index(column)
		order = Qt.AscendingOrder if ascending else Qt.DescendingOrder
		self._file_view.sortByColumn(column_index, order)
	@run_in_main_thread
	def get_sort_column(self):
		header = self._file_view.horizontalHeader()
		column_index = header.sortIndicatorSection()
		column = self.get_columns()[column_index]
		ascending = header.sortIndicatorOrder() == Qt.AscendingOrder
		return column, ascending
	@run_in_main_thread
	def get_column_widths(self):
		return [self._file_view.columnWidth(index) for index in range(self._model.columnCount() - 1)]
	@run_in_main_thread
	def set_column_widths(self, column_widths):
		num_columns = self._model.columnCount()
		if len(column_widths) not in (num_columns - 1, num_columns):
			raise ValueError(
				'Wrong number of columns: len(%r) != %d'
				% (column_widths, num_columns)
			)
		for i, width in enumerate(column_widths):
			self._file_view.setColumnWidth(i, width)
		self.get_column_widths_by_name()
	@run_in_main_thread
	def get_column_widths_by_name(self):
		self._column_widths_by_name.update(zip(self.get_columns(), self.get_column_widths()))
		return dict(self._column_widths_by_name)
	@run_in_main_thread
	def get_default_column_widths(self):
		widths = self.get_column_widths_by_name()
		return [widths.get(column.get_qualified_name(), self._file_view.columnWidth(index))
			for index, column in enumerate(self._model._default_columns[:-1])]
	@run_in_main_thread
	def restore_column_widths(self, by_name, legacy=None):
		if isinstance(by_name, dict):
			widths = by_name
		else:
			names = [column.get_qualified_name() for column in self._model._default_columns]
			widths = dict(zip(names, legacy or ()))
		self._column_widths_by_name.update({name: width for name, width in widths.items()
			if isinstance(name, str) and type(width) is int and width > 0})
		self._apply_column_widths()
	def _apply_column_widths(self):
		for index, name in enumerate(self.get_columns()[:-1]):
			if name in self._column_widths_by_name:
				self._file_view.setColumnWidth(index, self._column_widths_by_name[name])
	@run_in_main_thread
	def set_extra_columns(self, owner, columns_by_scheme):
		self.get_column_widths_by_name()
		cursor = self.get_file_under_cursor()
		selected = self.get_selected_files()
		sort_column, ascending = self.get_sort_column()
		new_model = None
		@run_in_main_thread
		def restore():
			if sip.isdeleted(self) or sip.isdeleted(self._model) or self._model.sourceModel() is not new_model:
				return
			self._file_view.resizeColumnsToContents()
			self._apply_column_widths()
			self.select(selected, ignore_errors=True)
			if cursor:
				try:
					self.place_cursor_at(cursor)
				except ValueError:
					pass
		self._model.set_extra_columns(owner, columns_by_scheme, sort_column, ascending, restore)
		new_model = self._model.sourceModel()
	@run_in_main_thread
	def refresh_files(self, urls):
		location = self.get_location()
		self._model.refresh_files(tuple(url for url in urls if dirname(url) == location))
	def _on_doubleclicked(self, index):
		self._controller.on_doubleclicked(self, self._model.url(index))
	def _on_key_pressed(self, event):
		if self._filter_bar.isVisible() and event.key() == Key_Backspace:
			self._filter_bar.handle_keypress(event)
			return True
		if self._controller.handle_shortcut(self, event):
			return True
		if self._filter_bar.handle_keypress(event):
			return True
		if self._controller.handle_nonexistent_shortcut(self, event):
			return True
		event.ignore()
		return False
	def _on_file_renamed(self, *args):
		self._controller.on_file_renamed(self, *args)
	def _on_files_dropped(self, *args):
		self._controller.on_files_dropped(self, *args)
	def _on_location_changed(self, url):
		self._filter_bar.close()
		self._location_bar.setText(as_human_readable(url))
		self.status_changed.emit()
	def _on_location_loaded(self, url):
		if not self.get_file_under_cursor():
			self.move_cursor_home()
		self._file_view.resizeColumnsToContents()
		self._apply_column_widths()
		self.location_changed.emit(self)

class FilterBar(QFrame):
	filter_changed = pyqtSignal(str, int, int)
	filter_cleared = pyqtSignal()

	def __init__(self, parent, model, file_view):
		super().__init__(parent)
		self._model = model
		self._file_view = file_view
		self.setVisible(False)
		self._input = QLineEdit()
		self._input.setMaxLength(MAX_FILTER_LENGTH)
		self._input.textChanged.connect(self._on_text_changed)
		self.setFrameShape(QFrame.Box)
		self.setFrameShadow(QFrame.Raised)
		layout = QVBoxLayout()
		layout.addWidget(self._input)
		layout.setContentsMargins(0, 0, 0, 0)
		self.setLayout(layout)
		self.setFocusPolicy(NoFocus)
		self._input.setFocusPolicy(NoFocus)
		self._matcher = compile_filter('')
		self._active = False
		self._model.add_filter(self._accepts)
		self._model.files_changed.connect(self.publish_count)
		file_view.verticalScrollBar().rangeChanged.connect(
			self._on_scroll_range_changed
		)
	def is_active(self):
		return self._active
	def handle_keypress(self, event):
		if event.key() == Key_Escape:
			self.close()
			return True
		query_before = self._input.text()
		self._input.keyPressEvent(event)
		query = self._input.text()
		result = query != query_before
		# Prevent Arrow-Left/-Right from changing the cursor position:
		self._input.setCursorPosition(len(query))
		self.setVisible(bool(query))
		if result:
			self._select_row_with_prefix(query)
		return result
	def _select_row_with_prefix(self, query):
		query_lower = query.lower()
		m = self._model
		def has_required_prefix(index):
			return m.data(index, DisplayRole).lower().startswith(query_lower)
		curr = self._file_view.currentIndex()
		if curr.isValid() and has_required_prefix(curr):
			# We're already at a row with the required prefix. Nothing to do.
			return
		for i in range(m.rowCount()):
			idx = m.index(i, 0)
			if has_required_prefix(idx):
				self._file_view.setCurrentIndex(idx)
				break
	def close(self):
		self.hide()
		self._input.setText('')
	def reposition(self, scroll_bar_visible=None):
		padding = QSize(5, 5)
		pos = self.parent().size() - self.size() - padding
		scroll_bar = self._file_view.verticalScrollBar()
		if scroll_bar_visible is None:
			scroll_bar_visible = scroll_bar.isVisible()
		if scroll_bar_visible:
			pos -= QSize(scroll_bar.width(), 0)
		self.move(pos.width(), pos.height())
	def _on_scroll_range_changed(self, min_, max_):
		self.reposition(scroll_bar_visible=min_ or max_)
	def _on_text_changed(self, text):
		was_active = self._active
		self._matcher = compile_filter(text)
		self._active = bool(text)
		self.setVisible(self._active)
		self._model.sourceModel().update()
		if self._active:
			self.publish_count()
		elif was_active:
			self.filter_cleared.emit()
	def publish_count(self):
		if self._active:
			self.filter_changed.emit(self._input.text(), self._model.rowCount(),
				len(self._model.sourceModel().get_rows()))
	def _accepts(self, url):
		return not self._active or self._matcher.matches(basename(url))

class MainWindow(QMainWindow):

	shown = pyqtSignal()
	closed = pyqtSignal()
	before_dialog = pyqtSignal(QDialog)

	def __init__(
		self, app, help_menu_actions, theme, progress_bar_palette, fs,
		null_location
	):
		super().__init__()
		self.setMinimumSize(960, 600)
		self._controller = None
		self._app = app
		self._theme = theme
		self._progress_bar_palette = progress_bar_palette
		self._fs = fs
		self._null_location = null_location
		self._panes = []
		self._active_pane = None
		self._extended_status_mode = DISABLED
		self._status_service = None
		self._single_pane_status = None
		self._pane_status_widgets = {}
		self._status_focus_tracking = False
		self._splitter = Splitter(self)
		central = QWidget(self)
		self._central_layout = QVBoxLayout(central)
		self._central_layout.setContentsMargins(0, 0, 0, 0)
		self._central_layout.setSpacing(0)
		self._central_layout.addWidget(self._splitter, 1)
		self._panel_dock = None
		self.setCentralWidget(central)
		self._status_bar = QStatusBar(self)
		self._status_bar_text = QLabel(self._status_bar)
		self._status_bar_text.setOpenExternalLinks(True)
		self._status_bar.addWidget(self._status_bar_text, 1)
		self._status_bar.setSizeGripEnabled(False)
		self.setStatusBar(self._status_bar)
		self._timer = QTimer(self)
		self._timer.timeout.connect(self.clear_status_message)
		self._timer.setSingleShot(True)
		self._shown_timer = QTimer(self)
		self._shown_timer.setSingleShot(True)
		self._shown_timer.timeout.connect(self.shown)
		self._dialog = None
		self._init_help_menu(help_menu_actions)
		self._app.focusChanged.connect(self._on_focus_changed)
		self._status_focus_tracking = True
	def set_controller(self, controller):
		self._controller = controller
	def set_bottom_panel(self, panel, close_session, focus_session=None):
		from fman.impl.ui.panel import PanelDock
		if self._panel_dock is not None:
			if self._panel_dock.panel is panel:
				return
			previous = self._panel_dock
			previous.close_session()
			self.remove_bottom_panel(previous.panel)
		self._panel_dock = PanelDock(panel, close_session, self.centralWidget(), focus_session)
		self._central_layout.addWidget(self._panel_dock)
		self._panel_dock.show()
		panel.show()
	def remove_bottom_panel(self, panel):
		if self._panel_dock is None or self._panel_dock.panel is not panel:
			return
		dock = self._panel_dock
		self._panel_dock = None
		dock.hide()
		self._central_layout.removeWidget(dock)
		dock.deleteLater()
	def _init_help_menu(self, help_menu_actions):
		if not help_menu_actions:
			return
		help_menu_text = 'Help'
		if is_mac():
				# On OS X, any menu named "Help" has the "Spotlight search for
				# Help" bar displayed in it. We don't need or want this. Add an
				# invisible character to fool OS X into not treating it as
				# "Help" (' ' doesn't work):
				help_menu_text += '\u2063'
		help_menu = self.menuBar().addMenu(help_menu_text)
		actions = []
		for action_name, shortcut, handler in help_menu_actions:
			action = QAction(action_name, help_menu)
			action.triggered.connect(handler)
			help_menu.addAction(action)
			actions.append(action)
		# On at least Mac, pressing a shortcut from a menu briefly highlights
		# the menu. We don't want this - especially for the Command Palette.
		# We therefore only enable the shortcuts when the menu is open:
		def enable_shortcuts():
			for i, (_, shortcut, _) in enumerate(help_menu_actions):
				if shortcut:
					actions[i].setShortcut(QKeySequence(shortcut))
		help_menu.aboutToShow.connect(enable_shortcuts)
		def disable_shortcuts():
			for action in actions:
				action.setShortcut(QKeySequence())
		help_menu.aboutToHide.connect(disable_shortcuts)
	@run_in_main_thread
	def show_alert(
		self, text, buttons=OK, default_button=OK, allow_escape=True
	):
		alert = MessageBox(self, allow_escape)
		# API users might pass arbitrary objects as text when trying to
		# debug, eg. exception instances. Convert to str(...) to allow for
		# this:
		alert.setText(str(text))
		alert.setStandardButtons(buttons)
		alert.setDefaultButton(default_button)
		return self.exec_dialog(alert)
	@run_in_main_thread
	def show_file_open_dialog(self, caption, dir_path, filter_text):
		# Let API users pass arbitrary objects by converting with str(...):
		return QFileDialog.getOpenFileName(
			self, str(caption), str(dir_path), str(filter_text)
		)[0]
	@run_in_main_thread
	def show_prompt(
		self, text, default='', selection_start=0, selection_end=None
	):
		# Let API users pass arbitrary objects by converting str(text):
		text_str = str(text)
		dialog = Prompt(
			self, 'RoyiFileManager', text_str, default,
			selection_start, selection_end
		)
		dialog.setTextValue(default)
		result = self.exec_dialog(dialog)
		if result:
			return dialog.textValue(), True
		return '', False
	@run_in_main_thread
	def show_quicksearch(
		self, get_items, get_tab_completion=None, query='', item=0
	):
		css = self._theme.get_quicksearch_item_css()
		dialog = Quicksearch(
			self, self._app, css, get_items, get_tab_completion, query, item
		)
		result = self.exec_dialog(dialog)
		return result
	@run_in_main_thread
	def create_progress_dialog(self, title, task_size):
		return ProgressDialog(
			self, title, task_size, self._progress_bar_palette
		)
	@run_in_main_thread
	def exec_dialog(self, dialog):
		self._dialog = dialog
		self.before_dialog.emit(dialog)
		dialog.moveToThread(self._app.thread())
		dialog.setParent(self)
		if is_mac():
			disable_window_animations_mac(dialog)
		result = dialog.exec()
		self._dialog = None
		return result
	@run_in_main_thread
	def show_status_message(self, text, timeout_secs=None):
		self._status_bar_text.setTextFormat(Qt.AutoText)
		self._status_bar_text.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
		self._status_bar_text.setWordWrap(False)
		self._status_bar_text.setText(text)
		if timeout_secs:
			self._timer.start(int(timeout_secs * 1000))
		else:
			self._timer.stop()
	@run_in_main_thread
	def clear_status_message(self):
		self.show_status_message('Ready.')
	@run_in_main_thread
	def add_pane(self):
		result = DirectoryPaneWidget(
			self._fs, self._null_location, self._splitter, self._controller
		)
		self._panes.append(result)
		self._splitter.addWidget(result)
		result.filter_changed.connect(self._on_filter_changed)
		result.filter_cleared.connect(self._on_filter_cleared)
		if self._active_pane is None:
			self._set_active_pane(result)
		if self._extended_status_mode == PER_PANE:
			self._add_pane_status(result)
		elif self._extended_status_mode == ACTIVE_PANE:
			self._single_pane_status.bind(self._active_pane)
		return result
	@run_in_main_thread
	def set_extended_status_bar(self, settings):
		self._clear_extended_status_bar()
		self._status_settings = settings
		set_size_divisor(settings['size_divisor'])
		self._extended_status_mode = settings['mode']
		if self._extended_status_mode == DISABLED:
			return
		self._on_focus_changed(None, self._app.focusWidget())
		self._status_service = StatusCalculationService(self._fs, self)
		if self._extended_status_mode == ACTIVE_PANE:
			widget = PaneStatusWidget(
				self._status_service, settings['max_entries'],
				settings['size_divisor'], False, self._status_bar
			)
			self._single_pane_status = widget
			self._status_bar.addPermanentWidget(widget)
			widget.bind(self._active_pane)
		else:
			for pane in self._panes:
				self._add_pane_status(pane)
	def _add_pane_status(self, pane):
		widget = PaneStatusWidget(
			self._status_service,  self._status_settings['max_entries'],
			self._status_settings['size_divisor'], True, pane
		)
		widget.bind(pane)
		widget.set_active(pane is self._active_pane)
		pane.set_status_widget(widget)
		self._pane_status_widgets[pane] = widget
	def _clear_extended_status_bar(self):
		if self._single_pane_status is not None:
			self._single_pane_status.deactivate()
			self._status_bar.removeWidget(self._single_pane_status)
			self._single_pane_status.deleteLater()
			self._single_pane_status = None
		for pane, widget in self._pane_status_widgets.items():
			widget.deactivate()
			pane.set_status_widget(None)
			widget.deleteLater()
		self._pane_status_widgets.clear()
		if self._status_service is not None:
			self._status_service.shutdown()
			self._status_service = None
	def _on_focus_changed(self, _old, new):
		if new is None:
			return
		for pane in self._panes:
			if pane is new or pane.isAncestorOf(new):
				self._set_active_pane(pane)
				return
	def _set_active_pane(self, pane):
		if pane is self._active_pane:
			return
		previous = self._active_pane
		self._active_pane = pane
		if self._single_pane_status is not None:
			self._single_pane_status.bind(pane)
		for candidate, widget in self._pane_status_widgets.items():
			widget.set_active(candidate is pane)
		if pane.is_filtering():
			pane.publish_filter_count()
		elif previous is not None and previous.is_filtering():
			self.clear_status_message()
	def _on_filter_changed(self, text, matched, total):
		if self.sender() is self._active_pane:
			self.show_status_message('Filter "%s": %d of %d items' % (text, matched, total))
			self._status_bar_text.setTextFormat(Qt.PlainText)
			self._status_bar_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
			self._status_bar_text.setWordWrap(True)
	def _on_filter_cleared(self):
		if self.sender() is self._active_pane:
			self.clear_status_message()
	def get_panes(self):
		return self._panes
	@run_in_main_thread
	def minimize(self):
		self.setWindowState(Qt.WindowMinimized)
	@run_in_main_thread
	def reset_geometry(self, width, height):
		self.showNormal()
		self.resize(width, height)
	def showEvent(self, *args):
		super().showEvent(*args)
		# singleShot after 50 ms (not 0) ensures that the window is already
		# fully visible. Any alerts we show in response to .shown are then
		# placed correctly over the center of the window.
		self._shown_timer.start(50)
	def closeEvent(self, _):
		self._shown_timer.stop()
		if self._status_focus_tracking:
			self._app.focusChanged.disconnect(self._on_focus_changed)
			self._status_focus_tracking = False
		if self._panel_dock is not None:
			dock = self._panel_dock
			dock.close_session()
			self.remove_bottom_panel(dock.panel)
		self._clear_extended_status_bar()
		self.closed.emit()
	@run_in_main_thread
	def show_overlay(self, overlay):
		overlay.resize(overlay.sizeHint())
		self._position_overlay(overlay)
		overlay.show()
	def _position_overlay(self, overlay):
		if self._dialog is None:
			pos_x = (self.width() - overlay.width()) / 2
			pos_y = (self.height() - overlay.height()) / 2
		else:
			dialog_pos = self._dialog.pos()
			pos_x = dialog_pos.x() - self.pos().x() + self._dialog.width() + 30
			pos_y = dialog_pos.y() - self.pos().y() + self._dialog.height() + 30
			right_margin = self.width() - pos_x - overlay.width()
			if right_margin / self.width() < 0.1:
				pos_x = 0.9 * self.width() - overlay.width()
		# The calculations above produce floats, but move(...) only accepts ints.
		overlay.move(int(pos_x), int(pos_y))
	def saveState(self, version=0):
		self_state = super().saveState(version)
		splitter_state = self._splitter.saveState()
		return self_state + splitter_state + bytes([len(self_state)])
	def restoreState(self, state, version=0):
		self_state_len = state[-1]
		if not super().restoreState(state[0:self_state_len], version):
			return False
		self._splitter.restoreState(state[self_state_len:-1])
		return True
	def focusNextPrevChild(self, next):
		if self._panel_dock is not None and self._panel_dock.isAncestorOf(self.focusWidget()):
			return self._panel_dock.focusNextPrevChild(next)
		# Returning False here lets us receive Tab in keyPressEvent(...).
		# This in turn lets us define our own key binding for the Tab key.
		return False

class MessageBox(QMessageBox):

	shown = pyqtSignal()

	def __init__(self, parent, allow_escape=True):
		super().__init__(parent)
		self._allow_escape = allow_escape
	def setStandardButtons(self, buttons):
		super().setStandardButtons(buttons)
		if is_mac():
			# The shortcut keys don't work out of the box on Mac, even though
			# they are displayed by our theme. (The standard macOS theme does
			# not display them.) The code below ensures that they work.
			# We do have to perform these steps _here_ because self.button(...)
			# returns None when called from the constructor.
			for button, shortcut in (
				(self.Yes, Qt.Key_Y), (self.No, Qt.Key_N),
				(self.YesToAll, Qt.Key_A), (self.NoToAll, Qt.Key_O)
			):
				if buttons & button:
					self.button(button).setShortcut(
						QKeySequence(Qt.CTRL + shortcut)
					)
	def keyPressEvent(self, event):
		if self._allow_escape or event.key() != Key_Escape:
			super().keyPressEvent(event)
	def showEvent(self, event):
		super().showEvent(event)
		self.shown.emit()

class Prompt(QInputDialog):
	"""
	Most of the code in this otherwise simple class solves the following
	problem: Say we want the user to enter a file path, and we want to
	pre-select the default file's base name without the extension. The file path
	is likely too long to be contained in the text field. We want to see:

		/path/to/my/file.txt
			 |      ----   |

	where --- is the selection and |   | are the visible borders of the text
	field. Instead, by default we see:

		/path/to/my/file.txt
		  |         ----|

	In other words, "file" is highlighted but the ".txt" suffix is cut off.

	QInputDialog and thus this class use QLineEdit for text input. That class
	internally uses a `hscroll` parameter to indicate the horizontal scroll
	position which distinguishes the two figures above. The problem is,
	`hscroll` is not settable from the outside. In fact, it is only set by
	QLineEdit::paintEvent(...). We thus perform the initial paintEvent(...)
	twice: First with the cursor at the end and then with the cursor / selection
	at the correct position. This sets `hscroll` to the required value.
	"""

	shown = pyqtSignal()

	def __init__(
		self, parent, title, text, default='', selection_start=0,
		selection_end=None
	):
		super().__init__(parent)
		self.setWindowTitle(title)
		self.setLabelText(text)
		self._selection_start = selection_start
		self._selection_end = selection_end
		if default:
			self.setTextValue(default)
		self.setTextEchoMode(QLineEdit.Normal)
		self._request_immediate_repaint = False
		self._is_second_paint = False
	def setVisible(self, visible):
		"""
		Unfortunately, our double call to paintEvent(...) leads to flickering
		effects on slower systems. The super() implementation of this function
		selects the text edit's entire text. This makes the flickering effect
		especially noticeable. To alleviate this, we only place the cursor at
		the end of the text field (via .end(...)). This still has the desired
		effect of getting Qt to not cut off the rightmost characters of the text
		field, yet has less visual effect.
		"""
		if visible:
			self.labelText() # Call private ensureLayout() of the superclass
			self._get_line_edit().end(False)
			self._request_immediate_repaint = True
		QDialog.setVisible(self, visible)
	def paintEvent(self, e):
		if self._request_immediate_repaint:
			self._request_immediate_repaint = False
			# Request the second paint:
			self.update()
			self._is_second_paint = True
		elif self._is_second_paint:
			self._is_second_paint = False
			self._set_cursor_and_selection()
	def showEvent(self, event):
		super().showEvent(event)
		self.shown.emit()
	def _set_cursor_and_selection(self):
		line_edit = self._get_line_edit()
		set_selection(line_edit, self._selection_start, self._selection_end)
	def _get_line_edit(self):
		for child in self.children():
			if isinstance(child, QLineEdit):
				return child
		raise AssertionError('Should not reach here')

class Splitter(QSplitter):
	def createHandle(self):
		result = QSplitterHandle(self.orientation(), self)
		result.installEventFilter(self)
		return result
	def eventFilter(self, splitter_handle, event):
		if event.type() == QEvent.MouseButtonDblClick:
			self._distribute_handles_evenly(splitter_handle.width())
			return True
		return False
	def _distribute_handles_evenly(self, handle_width):
		width_increment = self.width() // self.count()
		for i in range(1, self.count()):
			self.moveSplitter(i * width_increment - handle_width // 2, i)

class Overlay(QFrame):
	def __init__(self, parent, html, buttons=None):
		super().__init__(parent)

		self.setFrameShape(QFrame.Box)
		self.setFrameShadow(QFrame.Raised)
		self.setFocusPolicy(Qt.NoFocus)

		layout = QVBoxLayout()
		layout.setContentsMargins(20, 20, 20, 20)

		self.label = QLabel(self)
		self.label.setWordWrap(True)
		self.label.setText(html)

		# The following two lines prevent the label from being "cut off" at the
		# bottom under some circumstances:
		layout.setSizeConstraint(layout.SetMinAndMaxSize)
		self.label.setSizePolicy(
			QSizePolicy.MinimumExpanding, QSizePolicy.Minimum
		)

		layout.addWidget(self.label)

		if buttons:
			button_container = QWidget(self)
			button_layout = QHBoxLayout()
			for button_label, action in buttons:
				button = QPushButton(button_label, button_container)
				button.clicked.connect(lambda *_, action=action: action())
				# Prevent button from stealing focus from the directory pane:
				button.setFocusPolicy(Qt.NoFocus)
				button_layout.addWidget(button)
			button_container.setLayout(button_layout)
			layout.addWidget(button_container)

		self.setLayout(layout)
	def close(self):
		self.setParent(None)

class ProgressDialog(QProgressDialog):

	"""
	Instead of using @run_in_main_thread on #set_text(...) and
	#set_progress(...), this class uses #_update_timer to only update the GUI
	every 100ms. This avoids the unnecessary overhead of syncing with the main
	thread for every status update, and thus improves performance.
	"""

	_MAX_C_INT = 2147483647
	_MINIMUM_DURATION_MS = 1000
	_UPDATE_INTERVAL_MS = 100

	@run_in_main_thread
	def __init__(self, parent, title, size, progress_bar_palette):
		# Would like the dialog to be non-resizable on all platforms, but only
		# Windows supports it as a flag. On other platforms, we use
		# setFixedSize(...). See #resizeEvent(...) below.
		args = (Qt.MSWindowsFixedSizeDialogHint,) if is_windows() else ()
		super().__init__(parent, *args)
		self._title = title
		self._size = self.maximum()
		self._text = ''
		self._progress = 0
		self._was_canceled = False
		self.findChild(QProgressBar).setPalette(progress_bar_palette)
		self.setMinimumDuration(self._MINIMUM_DURATION_MS)
		self.setAutoReset(False)
		self.setWindowTitle(title)
		self.set_task_size(size)
		self.canceled.disconnect(super().cancel)
		self.canceled.connect(self.request_cancel)
		self._update_timer = QTimer(self)
		self._update_timer.timeout.connect(self._update)
		# Ensure the progress dialog appears in 1 sec starting *now*:
		self.setValue(0)
	def set_text(self, text):
		self._text = text
	@run_in_main_thread
	def set_task_size(self, size):
		self._size = size
		self.setMaximum(min(size, self._MAX_C_INT))
	def set_progress(self, progress):
		self._progress = progress
	def get_progress(self):
		return self._progress
	def reject(self):
		# Called when the user presses the "Close window" button.
		self.request_cancel()
	@run_in_main_thread
	def cancel(self):
		super().cancel()
	@run_in_main_thread
	def request_cancel(self):
		self.set_text('Canceling...')
		cancel_button = self.findChild(QPushButton)
		cancel_button.setEnabled(False)
		self._was_canceled = True
	@run_in_main_thread
	def show_alert(self, *args, **kwargs):
		# Prevent the progress dialog from popping up while the alert is shown:
		self.setMinimumDuration(self._MAX_C_INT)
		try:
			return self.parent().show_alert(*args, **kwargs)
		finally:
			self.setMinimumDuration(self._MINIMUM_DURATION_MS)
	def was_canceled(self):
		return self._was_canceled
	def showEvent(self, e):
		self._update()
		self._update_timer.start(self._UPDATE_INTERVAL_MS)
		super().showEvent(e)
	def closeEvent(self, e):
		self._update_timer.stop()
		super().closeEvent(e)
	def resizeEvent(self, e):
		super().resizeEvent(e)
		# Prevent the dialog from being resizable:
		if not is_windows():
			self.setFixedSize(self.size())
	def _update(self):
		if self.wasCanceled():
			return
		self.setLabelText(self._text)
		self._set_value(self._progress)
	def _set_value(self, progress):
		if self._size > self._MAX_C_INT:
			# QProgressDialog#setValue(...) can only handle ints. If `progress`
			# is too large, we need to scale it down. If we didn't do this and
			# pass a larger number, it would overflow to a negative value.
			progress = self._MAX_C_INT * progress // self._size
		self.setValue(progress)