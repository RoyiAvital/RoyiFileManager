from fman.impl.ui import require_ui_thread, submit_work
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QLabel, QScrollArea, QVBoxLayout
from threading import Event


class MessageDialog(QDialog):
	def __init__(self, title, text, confirmation, parent):
		super().__init__(parent)
		self.setWindowTitle(title)
		self._text = text
		layout = QVBoxLayout(self)
		label = QLabel(text, self)
		label.setTextFormat(Qt.PlainText)
		label.setWordWrap(True)
		scroll = QScrollArea(self)
		scroll.setWidgetResizable(True)
		scroll.setWidget(label)
		layout.addWidget(scroll)
		choices = QDialogButtonBox.Yes | QDialogButtonBox.No if confirmation else QDialogButtonBox.Ok
		buttons = QDialogButtonBox(choices, self)
		buttons.clicked.connect(lambda button: self.done(int(buttons.standardButton(button))))
		default = buttons.button(QDialogButtonBox.No if confirmation else QDialogButtonBox.Ok)
		default.setDefault(True)
		default.setFocus()
		layout.addWidget(buttons)
		self.resize(520, 300 if confirmation else 180)

	def text(self):
		return self._text


class ToolWindow(QDialog):
	delivered = pyqtSignal(object)
	close_requested = pyqtSignal()
	disposed = pyqtSignal()
	shown = pyqtSignal(str)
	busy_changed = pyqtSignal(bool)

	def __init__(self, parent, owner):
		require_ui_thread()
		if owner is None or not owner.active:
			raise RuntimeError('A tool window requires an active plug-in owner.')
		super().__init__(parent, Qt.Tool)
		self.setObjectName('plugin-tool-window')
		self.focus_widget = None
		self.owner = owner
		self.alive = Event()
		self.alive.set()
		self.busy = False
		self._disposed = False
		self._operation_generation = 0
		self.prompt = None
		self.setAttribute(Qt.WA_DeleteOnClose)
		self.delivered.connect(self._deliver, Qt.QueuedConnection)
		self.close_requested.connect(self.close, Qt.QueuedConnection)
		self.destroyed.connect(lambda: self.alive.clear())
		self.destroyed.connect(lambda: owner.detach(self.invalidate))
		if not owner.attach(self.invalidate):
			self.alive.clear()

	def invalidate(self):
		self.alive.clear()
		try:
			self.close_requested.emit()
		except RuntimeError:
			pass

	def post(self, callback, *args):
		if self.alive.is_set():
			try:
				self.delivered.emit((callback, args))
			except RuntimeError:
				pass

	def _deliver(self, message):
		if self.alive.is_set() and self.owner.active:
			callback, args = message
			callback(*args)

	def work(self, operation, completed):
		if self.busy or not self.alive.is_set() or not self.owner.active:
			return False
		self.set_busy(True)
		self._operation_generation += 1
		generation = self._operation_generation
		def deliver(result, error):
			self.post(self._work_finished, generation, completed, result, error)
		if not submit_work(operation, deliver):
			self.set_busy(False)
			self.alert('Other operations are still finishing. Please try again.')
			return False
		return True

	def _work_finished(self, generation, completed, result, error):
		if generation != self._operation_generation:
			return
		if self.prompt is None:
			self.set_busy(False)
		if error:
			self.alert(error)
		else:
			completed(result)

	def set_busy(self, busy):
		self.busy = busy
		self.busy_changed.emit(busy)

	def on_shown(self, query):
		from fman.impl.ui.quicklist import QuickList
		if query and isinstance(self.focus_widget, QuickList):
			self.focus_widget.query.setText(query)
		self.shown.emit(query)

	def alert(self, text):
		dialog = MessageDialog(self.windowTitle(), str(text), False, self)
		self._open_prompt(dialog, lambda result: None)

	def confirm(self, title, records, hidden, footer, accepted):
		lines = ['%s\n%s' % (name[:160], path[:500]) for name, path in records[:10]]
		if len(records) > 10:
			lines.append('... and %d more' % (len(records) - 10))
		text = '%d total, %d selected items hidden\n\n%s\n\n%s' % (
			len(records), hidden, '\n\n'.join(lines), footer
		)
		dialog = MessageDialog(title, text, True, self)
		self._open_prompt(dialog, lambda result: accepted() if result == QDialogButtonBox.Yes else None)

	def _open_prompt(self, dialog, finished):
		self.prompt = dialog
		self.set_busy(True)
		dialog.setWindowModality(Qt.WindowModal)
		def complete(result):
			if self.alive.is_set() and self.owner.active:
				self.prompt = None
				self.set_busy(False)
				finished(result)
			dialog.deleteLater()
		dialog.finished.connect(complete)
		dialog.open()

	def closeEvent(self, event):
		self._dispose()
		super().closeEvent(event)

	def done(self, result):
		self._dispose()
		super().done(result)

	def _dispose(self):
		if self._disposed:
			return
		self._disposed = True
		self.alive.clear()
		self.owner.detach(self.invalidate)
		self.disposed.emit()
		if self.prompt:
			self.prompt.reject()


class PaneToolWindow(ToolWindow):
	def __init__(self, pane, owner):
		require_ui_thread()
		parent = pane.window._widget
		super().__init__(parent, owner)
		self.pane = pane
		self.item_css = parent._theme.get_quicksearch_item_css()
		self.disposed.connect(pane.on_closed(self.close))
		self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
		self.setMinimumSize(480, 260)
		self.resize(680, 430)


class NavigationHandle:
	def __init__(self, request):
		self._request = request

	@property
	def done(self):
		return self._request.done

	def cancel(self):
		self._request.cancel()


def navigate(pane, url, on_done, *, window, check=None, timeout=30):
	require_ui_thread()
	from fman.impl.navigation import NavigationRequest
	from fman.impl.util.qt.thread import is_in_main_thread
	from PyQt5.QtCore import QTimer
	if timeout <= 0:
		raise ValueError('Navigation timeout must be positive.')
	timer = QTimer(window)
	timer.setSingleShot(True)
	manages_busy = not window.busy
	def completed(outcome, message):
		timer.stop()
		timer.deleteLater()
		window.disposed.disconnect(handle.cancel)
		if manages_busy:
			window.set_busy(False)
		on_done(outcome, message)
	def deliver(*result):
		if is_in_main_thread():
			window._deliver((completed, result))
		else:
			window.post(completed, *result)
	request = NavigationRequest(deliver,
		lambda: window.alive.is_set() and window.owner.active)
	handle = NavigationHandle(request)
	window.disposed.connect(handle.cancel)
	timer.timeout.connect(lambda: request.fail('Directory navigation timed out; its filesystem check may still be finishing.'))
	def operation():
		if request.active:
			if check is not None:
				check(url)
			request.dispatch(pane, url)
			request.wait(timeout)
	def delivered(result, error):
		if error:
			request.fail(error)
	if not request.active:
		handle.cancel()
	elif window.busy:
		request.fail('Another operation is active in this window.')
	else:
		window.set_busy(True)
		if submit_work(operation, delivered):
			timer.start(round(timeout * 1000))
		else:
			request.fail('Other operations are still finishing. Please try again.')
	return handle