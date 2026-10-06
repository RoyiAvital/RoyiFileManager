from contextlib import closing, nullcontext
from threading import BoundedSemaphore, Event, Lock

from fman.impl.model.listing import Canceled, LatestJobs
from fman.impl.ui import UiOwner
from fman.impl.ui.facade import ElidedLabel
from fman.impl.ui.session import ToolWindow
from fman.impl.ui.table import Table, defer
from fman.impl.ui.table_data import TableSchema, _validate_columns, text as checked_text
from fman.impl.util.qt.thread import is_in_main_thread, run_in_main_thread
from PyQt5.QtCore import QEvent, QEventLoop, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QApplication, QLineEdit, QMenu, QShortcut, QVBoxLayout, QWidget


_slots = BoundedSemaphore(2)
_board_owner = UiOwner()


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


def _prepare(schema, handler, text, check):
	try:
		check()
		rows = handler(text)
		check()
		iterator = iter(rows)
		with closing(iterator) if callable(getattr(iterator, 'close', None)) else nullcontext():
			snapshot = schema.snapshot(iterator, check_canceled=check)
		return snapshot, None
	except Canceled:
		raise
	except BaseException as error:
		check()
		return None, (isinstance(error, ValueError), (str(error) or type(error).__name__)[:2048])


class _Session:
	def __init__(self, text):
		self.done = Event()
		self.result = text, False
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
			self.table.counts.hide()
			self.table.layout().addWidget(self.status)
			layout.addWidget(self.table, 1)
			self.focus_widget = self.input
			self.setFocusProxy(self.input)
			QWidget.setTabOrder(self.input, self.table.view)
			self.input.textChanged.connect(self.request_preview)
			self.table.view.accept_requested.connect(self.request_accept)
			self.table.view.menu_requested.connect(self.open_menu)
			self.table.state_changed.connect(self.projection_changed)
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
			if self.revision:
				return
		else:
			self.revision += 1
			self.accept_revision = None
		self.pending = True
		self.preview_error = None
		self.close_menu()
		self.table.close_filter_menu()
		self.update_status()
		revision, text, schema, handler = self.revision, self.input.text(), self.schema, self.get_rows
		try:
			_input_text(text)
		except ValueError as error:
			self.jobs.cancel()
			self.receive(revision, (None, (True, str(error))), None)
			return
		try:
			self.jobs.submit(lambda check: _prepare(schema, handler, text, check),
				lambda result, error: self.post(self.receive, revision, result, error))
		except Exception as error:
			self.start_failed(error)

	def start_failed(self, error):
		from fman import show_alert
		self.close()
		if self.main.isVisible():
			show_alert('Could not start QuickBoard preview: ' + str(error)[:2048])

	def receive(self, revision, prepared, start_error):
		if not self.alive.is_set() or revision != self.revision:
			return
		if start_error is not None:
			self.start_failed(start_error)
			return
		rows, error = prepared
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
		self.table.replace_rows(rows)
		self.projection_changed()

	def update_status(self):
		message = 'Updating...' if self.pending else \
			('Preview error: ' + self.preview_error if self.preview_error is not None else '')
		self.status.set_content(' | '.join(part for part in (self.table.counts.text(), message) if part))

	def request_accept(self):
		if not self.alive.is_set() or self.busy or self.preview_error is not None:
			return
		self.accept_revision = self.revision
		self.projection_changed()

	def projection_changed(self):
		self.close_menu()
		if not self.alive.is_set():
			return
		self.update_status()
		if self.table.error:
			self.accept_revision = None
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
		self.accept_revision = None
		self.jobs.close()
		self.get_rows = None
		self.close_menu()
		if self.table is not None:
			self.table.dispose()
		text = self.input.text() if self.input is not None else self.session.result[0]
		self.session.result = text, self.accepted_text
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
		window = QuickBoardWindow(_get_ui(), session, TableSchema(columns), get_rows, text, title, summary, release)
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
	columns = _validate_columns(columns)
	session = _Session(text)
	_open(session, columns, get_rows, text, title, summary)
	if is_in_main_thread():
		if not session.done.is_set():
			session.loop = QEventLoop()
			session.loop.exec_()
	else:
		session.done.wait()
	return session.result