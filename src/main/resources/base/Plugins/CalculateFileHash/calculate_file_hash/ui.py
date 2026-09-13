from calculate_file_hash.hashing import AVAILABLE_ALGORITHMS
from fman import Task, show_alert, show_status_message
from fman.ui import OutputTextBox, UiController
from fman.url import as_human_readable
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QLabel, QVBoxLayout
from threading import Event, Lock


class HashRequest:
	def __init__(self, url, algorithm, auto_copy, owner, alive):
		self.url = url
		self.path = as_human_readable(url)
		self.algorithm = algorithm
		self.auto_copy = auto_copy
		self.owner = owner
		self.alive = alive
		self.canceled = Event()

	def check_canceled(self):
		if self.canceled.is_set() or not self.alive.is_set() or not self.owner.active:
			raise Task.Canceled()


class _PathLabel(QLabel):
	def __init__(self, parent):
		super().__init__(parent)
		self._path = ''
		self.setMinimumWidth(0)
		self.setTextFormat(Qt.PlainText)

	def set_path(self, path):
		self._path = path
		self.setToolTip(path)
		self._update_text()

	def _update_text(self):
		self.setText(self.fontMetrics().elidedText(self._path, Qt.ElideMiddle, self.contentsRect().width()))

	def resizeEvent(self, event):
		super().resizeEvent(event)
		self._update_text()

	def changeEvent(self, event):
		super().changeEvent(event)
		if event.type() in (QEvent.FontChange, QEvent.StyleChange) and hasattr(self, '_path'):
			self._update_text()


class HashController(UiController):
	@classmethod
	def build(cls, window, pane):
		window.setWindowTitle('Calculate File Hash')
		window.setMinimumSize(480, 160)
		window.resize(560, 180)
		layout = QVBoxLayout(window)
		layout.setContentsMargins(8, 6, 8, 6)
		layout.setSpacing(4)
		window.path_label = _PathLabel(window)
		window.output = OutputTextBox(parent=window)
		window.focus_widget = window.output
		layout.addWidget(window.path_label)
		layout.addWidget(window.output, 1)
		window.session = HashSession(window)
		window.output.copied.connect(window.session.copied)
		window.disposed.connect(window.session.dispose)
		window.shown.connect(window.session.center)
		window.output.setEnabled(False)


class HashSession:
	def __init__(self, window):
		self.window = window
		self.owner = window.owner
		self.alive = window.alive
		self.post = window.post
		self.lock = Lock()
		self.request = None
		self.last = None

	def center(self, query=''):
		window = self.window
		parent = window.parentWidget()
		window.layout().activate()
		available = parent.screen().availableGeometry()
		window.resize(window.size().expandedTo(window.minimumSizeHint()).boundedTo(available.size()))
		geometry = window.frameGeometry()
		geometry.moveCenter(parent.frameGeometry().center())
		position = geometry.topLeft()
		position.setX(max(available.left(), min(position.x(), available.right() - geometry.width() + 1)))
		position.setY(max(available.top(), min(position.y(), available.bottom() - geometry.height() + 1)))
		window.move(position)

	def begin(self, url, algorithm, auto_copy):
		with self.lock:
			if self.request is not None or not self.alive.is_set() or not self.owner.active:
				return None
			request = HashRequest(url, algorithm, auto_copy, self.owner, self.alive)
			self.request = request
		self.post(self._started, request)
		return request

	def dispose(self):
		with self.lock:
			if self.request is not None:
				self.request.canceled.set()

	def complete(self, request, result=None, error=None, status_only=False):
		self.post(self._finished, request, result, error, status_only)

	def _current(self, request):
		return self.alive.is_set() and self.owner.active and self.request is request and not request.canceled.is_set()

	def _busy(self, busy):
		self.window.set_busy(busy)
		self.window.output.setEnabled(not busy and self.last is not None)

	def _started(self, request):
		if not self._current(request):
			return
		self._busy(True)
		if self.last is None:
			self.window.path_label.set_path(request.path)
			self.window.setWindowTitle(request.path)
		self.center()

	def _finished(self, request, result, error, status_only):
		if not self._current(request):
			return
		with self.lock:
			self.request = None
		if result is not None:
			self.last = request.url, request.algorithm, result.digest
			self.window.path_label.set_path(request.path)
			self.window.setWindowTitle(request.path)
			self.window.output.set_text(result.digest)
			self.window.output.set_title('Hash Algorithm: %s' % dict(AVAILABLE_ALGORITHMS)[request.algorithm])
			self.window.output.setToolTip('%s\n%s' % (request.path, dict(AVAILABLE_ALGORITHMS)[request.algorithm]))
		self._busy(False)
		if not self.alive.is_set() or not self.owner.active:
			return
		if result is not None:
			self.window.output.setFocus()
			if request.auto_copy:
				self.window.output.copy_text()
			return
		if self.last is not None and not error:
			show_status_message('No new result. Previous hash retained.', timeout_secs=3)
		if error:
			if status_only:
				show_status_message(error, timeout_secs=3)
			elif self.last is not None:
				self.window.alert(error)
			else:
				show_alert(error)
		if self.last is None:
			self.window.close()

	def copied(self):
		if self.last is not None and self.alive.is_set() and self.owner.active:
			message = '%s copied to clipboard.' % dict(AVAILABLE_ALGORITHMS)[self.last[1]]
			show_status_message(message, timeout_secs=3)
