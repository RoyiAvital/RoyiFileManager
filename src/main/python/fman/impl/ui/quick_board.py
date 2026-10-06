from contextlib import closing, nullcontext
from threading import BoundedSemaphore, Event, Lock

from fman.impl.model.listing import Canceled, LatestJobs
from fman.impl.ui import UiOwner
from fman.impl.ui.facade import ElidedLabel
from fman.impl.ui.session import ToolWindow
from fman.impl.ui.table import Table, defer
from fman.impl.ui.table_data import TableSchema, _validate_columns, text as checked_text
from fman.impl.util.qt.thread import is_in_main_thread, run_in_main_thread
from PyQt5.QtCore import QEvent, QEventLoop, Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QMenu, QShortcut, QVBoxLayout, QWidget


_slots = BoundedSemaphore(2)
_board_owner = UiOwner()
MAX_ROWS = 25000
MAX_COLUMNS = 16
DEBOUNCE_MS = 100


def _reserve():
	if not _slots.acquire(blocking=False):
		return None
	lock, released = Lock(), False
	def release():
		nonlocal released
		with lock:
			if not released:
				released = True
				_slots.release()
	return release


def _input_text(value):
	checked_text(value, 'Text', 4096)
	if '\r' in value or '\n' in value or len(value.encode('utf-16-le', 'surrogatepass')) > 8192:
		raise ValueError('Text must be a single line of at most 4,096 UTF-16 units.')
	return value


def _prepare(schema, handler, text, check, mapping=None, source=None):
	try:
		check()
		result = handler(text, mapping)
		if not isinstance(result, tuple) or len(result) != 2:
			raise TypeError('QuickBoard get_rows must return a (rows, status) tuple.')
		rows, caller_status = result
		if caller_status is not None:
			checked_text(caller_status, 'Caller status', 512)
		check()
		iterator = iter(rows)
		with closing(iterator) if callable(getattr(iterator, 'close', None)) else nullcontext():
			snapshot = schema.snapshot(iterator, check_canceled=check)
		if source is not None:
			if len(snapshot) != len(source):
				raise ValueError('QuickBoard source row count must stay fixed.')
			columns = tuple(index for index, column in enumerate(schema.columns) if column.sortable or column.filterable)
			for previous, current in zip(source, snapshot):
				check()
				for column in columns:
					if (previous.cells[column] != current.cells[column] or
							(previous.values or previous.cells)[column] != (current.values or current.cells)[column]):
						raise ValueError('QuickBoard source column %r must stay fixed; use '
							'sortable=False, filterable=False for generated values.' % schema.columns[column].label)
		return snapshot, None, caller_status
	except Canceled:
		raise
	except BaseException as error:
		check()
		return None, (isinstance(error, ValueError), (str(error) or type(error).__name__)[:2048]), None


class _Session:
	def __init__(self, text):
		self.done = Event()
		self.result = text, False, None
		self.loop = None


class QuickBoardWindow(ToolWindow):
	def __init__(self, main, session, schema, get_rows, text, title, summary, release):
		super().__init__(main, _board_owner)
		self.main, self.session, self.schema = main, session, schema
		self.get_rows = get_rows
		self.jobs = LatestJobs(cooperative=True, on_closed=release)
		self.revision = 0
		self.preview_revision = None
		self.accept_revision = None
		self.preview_error = None
		self.pending = True
		self.accepted_text = False
		self.source = None
		self.mapping = self.generated_mapping = None
		self.requested = None
		self.publishing = False
		self.started = False
		self.caller_status_text = None
		self.debounce = QTimer(self)
		self.debounce.setSingleShot(True)
		self.debounce.setInterval(DEBOUNCE_MS)
		self.debounce.timeout.connect(self.submit_preview)
		self.table = self.input = self.menu = None
		self.disposed.connect(self.cleanup)
		try:
			self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
			self.setWindowModality(Qt.WindowModal)
			self.setWindowTitle(title or 'QuickBoard')
			self.resize(820, 520)
			self.setMinimumSize(460, 280)
			layout = QVBoxLayout(self)
			layout.setContentsMargins(14, 12, 14, 12)
			self.drag = None
			self.header = ElidedLabel(self.windowTitle(), self)
			self.header.setObjectName('quick-board-title')
			font = self.header.font()
			font.setBold(True)
			self.header.setFont(font)
			self.header.setCursor(Qt.SizeAllCursor)
			self.header.installEventFilter(self)
			layout.addWidget(self.header)
			self.summary = ElidedLabel(summary, self)
			self.summary.setVisible(bool(summary))
			layout.addWidget(self.summary)
			self.table = Table(schema, (), self, text_filter=None)
			for index, column in enumerate(schema.columns):
				if column.policy == 'number':
					self.table.view.setColumnWidth(index, max(90, self.fontMetrics().horizontalAdvance(column.label) + 64))
			if not schema.columns[0].typed:
				self.table.view.setColumnWidth(0, 300)
			for shortcut in self.table.findChildren(QShortcut):
				if shortcut.key().toString() == 'Ctrl+F':
					shortcut.setEnabled(False)
			self.input = QLineEdit(text, self.table)
			self.input.setMaxLength(4096)
			self.input.setAccessibleName(title or 'Compose text')
			self.input.installEventFilter(self)
			self.table.layout().insertWidget(0, self.input)
			self.status = ElidedLabel('', self.table)
			self.caller_status = ElidedLabel('', self.table)
			self.caller_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
			self.caller_status.hide()
			self.table.counts.hide()
			footer = QHBoxLayout()
			footer.setContentsMargins(0, 0, 0, 0)
			footer.addWidget(self.status, 1)
			footer.addWidget(self.caller_status, 1)
			self.table.layout().addLayout(footer)
			layout.addWidget(self.table, 1)
			self.focus_widget = self.input
			self.setFocusProxy(self.input)
			QWidget.setTabOrder(self.input, self.table.view)
			self.input.textChanged.connect(self.request_preview)
			self.table.view.accept_requested.connect(self.request_accept)
			self.table.view.menu_requested.connect(self.open_menu)
			self.table.state_changed.connect(self.projection_changed)
			self.table.presentation_changed.connect(self.view_changed)
			shortcut = QShortcut(QKeySequence('Ctrl+F'), self)
			shortcut.setContext(Qt.WidgetWithChildrenShortcut)
			shortcut.activated.connect(self.focus_input)
			self.update_status()
			main.installEventFilter(self)
		except BaseException:
			self.close()
			raise

	def focus_input(self):
		self.input.setFocus()
		self.input.selectAll()

	def request_preview(self, *_, initial=False):
		if not self.alive.is_set():
			return
		if initial:
			if self.started:
				return
		else:
			self.revision += 1
			self.accept_revision = None
		self.started = True
		self.pending = True
		self.preview_error = None
		self.clear_caller_status()
		self.close_menu()
		self.table.close_filter_menu()
		self.update_status()
		self.requested = None
		self.jobs.cancel()
		try:
			_input_text(self.input.text())
		except ValueError as error:
			self.debounce.stop()
			self.receive(self.revision, (None, (True, str(error)), None), None, None)
			return
		if initial:
			self.submit_preview()
		else:
			self.debounce.start()

	def clear_caller_status(self):
		self.caller_status_text = None
		self.caller_status.set_content('')
		self.caller_status.hide()

	def view_changed(self):
		self.accept_revision = None
		self.debounce.stop()
		self.clear_caller_status()
		if self.preview_error is not None:
			return
		self.revision += 1
		self.requested = None
		self.pending = True
		self.preview_error = None
		self.jobs.cancel()

	def submit_preview(self):
		if not self.alive.is_set() or self.debounce.isActive() or (self.source is not None and not self.table.settled):
			return
		mapping = self.table.view_mapping() if self.source is not None else None
		key = self.revision, mapping
		if self.requested == key:
			return
		self.requested = key
		revision, text, schema, handler, source = self.revision, self.input.text(), self.schema, self.get_rows, self.source
		try:
			_input_text(text)
		except ValueError as error:
			self.jobs.cancel()
			self.receive(revision, (None, (True, str(error)), None), None, mapping)
			return
		try:
			self.jobs.submit(lambda check: _prepare(schema, handler, text, check, mapping, source),
				lambda result, error: self.post(self.receive, revision, result, error, mapping))
		except Exception as error:
			self.start_failed(error)

	def start_failed(self, error):
		from fman import show_alert
		self.close()
		if self.main.isVisible():
			show_alert('Could not start QuickBoard preview: ' + str(error)[:2048])

	def receive(self, revision, prepared, start_error, mapping):
		if not self.alive.is_set() or revision != self.revision:
			return
		if start_error is not None:
			self.start_failed(start_error)
			return
		rows, error, caller_status = prepared
		self.pending = False
		if error is not None:
			self.accept_revision = None
			self.preview_error = error[1]
			self.update_status()
			if not error[0]:
				self.alert(self.preview_error)
			return
		self.preview_error = None
		self.preview_revision = revision
		self.generated_mapping = mapping
		self.caller_status_text = caller_status
		if self.source is None:
			self.source = rows
		self.publishing = True
		try:
			self.table.replace_rows(rows)
		finally:
			self.publishing = False
		self.projection_changed()

	def update_status(self):
		message = 'Updating...' if self.pending else \
			('Preview error: ' + self.preview_error if self.preview_error is not None else '')
		stale = 'Stale preview' if self.preview_error is not None and self.source is not None else ''
		self.status.set_content(' | '.join(part for part in (self.table.counts.text(), stale, message) if part))

	def request_accept(self):
		if not self.alive.is_set() or self.busy or self.preview_error is not None:
			return
		self.accept_revision = self.revision
		if self.debounce.isActive():
			self.debounce.stop()
			self.submit_preview()
		self.projection_changed()

	def projection_changed(self):
		self.close_menu()
		if not self.alive.is_set():
			return
		self.update_status()
		if self.table.error:
			self.accept_revision = None
			self.pending = False
			return
		if self.publishing or not self.table.settled or self.preview_error is not None:
			return
		if self.source is None:
			if self.started:
				self.submit_preview()
			return
		mapping = self.table.view_mapping()
		if self.generated_mapping != mapping or self.preview_revision != self.revision:
			self.pending = True
			self.update_status()
			self.submit_preview()
			return
		self.mapping = mapping
		if not self.pending:
			self.caller_status.set_content(self.caller_status_text or '')
			self.caller_status.setVisible(bool(self.caller_status_text))
		if (self.accept_revision == self.revision == self.preview_revision and
				not self.pending and self.preview_error is None and self.table.settled and not self.busy):
			self.accepted_text = True
			self.close()

	def eventFilter(self, watched, event):
		if watched is self.main and event.type() == QEvent.Close:
			self.close()
		elif watched is self.header:
			if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
				self.drag = event.globalPos() - self.frameGeometry().topLeft()
			elif event.type() == QEvent.MouseMove and self.drag is not None:
				self.move(event.globalPos() - self.drag)
			elif event.type() == QEvent.MouseButtonRelease:
				self.drag = None
		elif watched is self.input and event.type() == QEvent.KeyPress:
			modifiers = event.modifiers() & ~Qt.KeypadModifier
			if event.key() in (Qt.Key_Return, Qt.Key_Enter) and modifiers == Qt.NoModifier:
				self.request_accept()
				return True
			if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown) and modifiers == Qt.NoModifier:
				self.table.view.setFocus()
				return True
		return super().eventFilter(watched, event)

	def open_menu(self, row, column, position):
		self.close_menu()
		if row is None or not self.alive.is_set():
			return
		menu = QMenu(self)
		self.menu = menu
		revision = self.revision
		def guarded(callback):
			def invoke():
				cell = self.table.current_cell
				if self.alive.is_set() and revision == self.revision and cell is not None and cell[0] is row and cell[1] == column:
					callback()
			return invoke
		menu.addAction(self.schema.columns[column].copy_label,
			guarded(lambda: QApplication.clipboard().setText(row.cells[column])))
		if self.table.filterable(column):
			menu.addSeparator()
			menu.addAction('Filter This Column...', guarded(lambda: self.table.open_filter_menu(column)))
			clear = menu.addAction('Clear All Filters', guarded(self.table.clear_all_filters))
			clear.setEnabled(bool(self.table.filters))
		def hidden():
			if self.menu is menu:
				self.menu = None
		menu.aboutToHide.connect(hidden)
		menu.aboutToHide.connect(menu.deleteLater)
		menu.popup(position)

	def close_menu(self):
		if self.menu is not None:
			menu, self.menu = self.menu, None
			menu.close()

	def invalidate(self):
		super().invalidate()
		jobs = getattr(self, 'jobs', None)
		if jobs is not None:
			jobs.close()

	def cleanup(self):
		self.main.removeEventFilter(self)
		self.debounce.stop()
		self.accept_revision = None
		self.jobs.close()
		self.get_rows = None
		self.source = None
		self.close_menu()
		if self.table is not None:
			self.table.dispose()
		text = self.input.text() if self.input is not None else self.session.result[0]
		self.session.result = text, self.accepted_text, self.mapping if self.accepted_text else None
		self.session.done.set()
		if self.session.loop is not None:
			self.session.loop.quit()


@run_in_main_thread
def _open(session, columns, get_rows, text, title, summary):
	from fman import _get_ui, show_alert
	release = _reserve()
	if release is None:
		session.done.set()
		show_alert('Two QuickBoards are open or still finishing. Close one or try again shortly.')
		return
	try:
		window = QuickBoardWindow(_get_ui(), session,
			TableSchema(columns, max_rows=MAX_ROWS, max_columns=MAX_COLUMNS), get_rows, text, title, summary, release)
		window.show()
		window.raise_()
		window.activateWindow()
		window.input.setFocus()
		defer(window, lambda: window.request_preview(initial=True))
		return window
	except BaseException:
		release()
		raise


def show_quick_board(*, columns, get_rows, text='', title='', summary=''):
	if not callable(get_rows):
		raise TypeError('get_rows must be callable.')
	_input_text(text)
	checked_text(title, 'Title', 512)
	checked_text(summary, 'Summary', 2048)
	columns = _validate_columns(columns, MAX_COLUMNS)
	session = _Session(text)
	_open(session, columns, get_rows, text, title, summary)
	if is_in_main_thread():
		if not session.done.is_set():
			session.loop = QEventLoop()
			session.loop.exec_()
	else:
		session.done.wait()
	return session.result