from dataclasses import dataclass
from threading import BoundedSemaphore, RLock, Thread


@dataclass(frozen=True)
class ListItem:
	id: str
	title: str
	hint: str = ''
	title_matches: tuple = ()
	hint_matches: tuple = ()


def match_positions(matcher, text, query):
	folded = []
	offsets = []
	for index, char in enumerate(text):
		part = char.casefold()
		folded.append(part)
		offsets.extend([index] * len(part))
	result = matcher(''.join(folded), query.casefold())
	if result is not None:
		return tuple(dict.fromkeys(offsets[index] for index in result))


def utf16_span(text, index):
	start = len(text[:index].encode('utf-16-le')) // 2
	length = len(text[index:index + 1].encode('utf-16-le')) // 2
	return start, length


class Resource:
	def __init__(self):
		self.lock = RLock()
		self.revision = 0
		self._subscribers = set()
		self._subscriber_lock = RLock()

	def subscribe(self, callback, snapshot):
		with self.lock:
			with self._subscriber_lock:
				self._subscribers.add(callback)
			return self.revision, snapshot()

	def unsubscribe(self, callback):
		with self._subscriber_lock:
			self._subscribers.discard(callback)

	def committed(self, snapshot):
		with self.lock:
			self.revision += 1
			with self._subscriber_lock:
				return self.revision, snapshot, tuple(self._subscribers)

	@staticmethod
	def publish(notification):
		revision, snapshot, subscribers = notification
		for subscriber in subscribers:
			subscriber(revision, snapshot)


_resources = {}
_resources_lock = RLock()


def resource(name):
	with _resources_lock:
		return _resources.setdefault(name, Resource())


class UiOwner:
	def __init__(self):
		self.active = True
		self._sessions = set()
		self._lock = RLock()

	def attach(self, dispose):
		with self._lock:
			if not self.active:
				return False
			self._sessions.add(dispose)
			return True

	def detach(self, dispose):
		with self._lock:
			self._sessions.discard(dispose)

	def invalidate(self):
		with self._lock:
			self.active = False
			sessions = tuple(self._sessions)
			self._sessions.clear()
		for dispose in sessions:
			dispose()


class UiController:
	owner = None
	window_type = None

	def __init_subclass__(cls, **kwargs):
		super().__init_subclass__(**kwargs)
		from weakref import WeakKeyDictionary
		cls.owner = None
		cls._sessions = WeakKeyDictionary()

	@classmethod
	def require_owner(cls):
		if cls.owner is None or not cls.owner.active:
			raise RuntimeError('UI controller has no active plug-in owner. Load the plug-in before showing UI.')
		return cls.owner

	@classmethod
	def show(cls, pane, query=''):
		from fman.impl.util.qt.thread import run_in_main_thread
		return run_in_main_thread(cls._show)(pane, query)

	@classmethod
	def _show(cls, pane, query):
		from fman.impl.ui.session import PaneToolWindow
		owner = cls.require_owner()
		window = cls._sessions.get(pane)
		if window is None or not window.alive.is_set():
			window = (cls.window_type or PaneToolWindow)(pane, owner)
			try:
				cls.build(window, pane)
			except Exception:
				window.close()
				raise
			cls._sessions[pane] = window
			def remove():
				if cls._sessions.get(pane) is window:
					cls._sessions.pop(pane, None)
			window.disposed.connect(remove)
			window.show()
		window.on_shown(query)
		window.raise_()
		window.activateWindow()
		if window.focus_widget is not None:
			window.focus_widget.setFocus()
		return window

	@classmethod
	def build(cls, window, pane):
		raise NotImplementedError('Implement build(window, pane) using fman.ui components.')


def require_ui_thread():
	from PyQt5.QtCore import QThread
	from PyQt5.QtWidgets import QApplication
	app = QApplication.instance()
	if app is None or QThread.currentThread() != app.thread():
		raise RuntimeError('Construct UI components in UiController.build() on the Qt thread.')


_work_slots = BoundedSemaphore(2)


def submit_work(work, deliver):
	if not _work_slots.acquire(blocking=False):
		return False
	def run():
		try:
			try:
				result = work()
			except Exception as error:
				deliver(None, str(error))
			else:
				deliver(result, None)
		finally:
			_work_slots.release()
	Thread(target=run, daemon=True).start()
	return True