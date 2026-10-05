from collections.abc import Mapping
from dataclasses import dataclass
from threading import BoundedSemaphore, RLock, Thread

import math


MAX_METADATA_FIELDS = 8
MAX_LABEL_LENGTH = 32
MAX_METADATA_TEXT = 128


@dataclass(frozen=True)
class ListItem:
	id: str
	title: str
	hint: str = ''
	title_matches: tuple = ()
	hint_matches: tuple = ()
	# Label -> value; stored as ((label, sort_key or None, text), ...).
	metadata: tuple = ()

	def __post_init__(self):
		if isinstance(self.metadata, Mapping):
			object.__setattr__(self, 'metadata', _normalize_metadata(self.metadata))
		elif not isinstance(self.metadata, tuple) or not all(
				isinstance(entry, tuple) and len(entry) == 3 for entry in self.metadata):
			raise TypeError('ListItem metadata must be a mapping of label to value.')


def _metadata_text(value, name):
	if not isinstance(value, str):
		raise TypeError('%s must be a string.' % name)
	if '\x00' in value or len(value) > MAX_METADATA_TEXT:
		raise ValueError('%s contains NUL or exceeds %d characters.' % (name, MAX_METADATA_TEXT))
	return value


def _metadata_key(value, name):
	if isinstance(value, str):
		return _metadata_text(value, name)
	if type(value) is int or type(value) is float and math.isfinite(value):
		return value
	raise TypeError('%s must be a string, an int or a finite float.' % name)


def _metadata_label(label):
	if not isinstance(label, str) or not label or '\x00' in label or len(label) > MAX_LABEL_LENGTH:
		raise ValueError('Metadata labels must be nonempty strings of at most %d characters.' % MAX_LABEL_LENGTH)
	return 'Metadata value of %r' % label


def validate_metadata(metadata):
	"""Full check of the canonical ((label, sort_key or None, text), ...) form."""
	if len(metadata) > MAX_METADATA_FIELDS:
		raise ValueError('ListItem metadata has more than %d labels.' % MAX_METADATA_FIELDS)
	for label, key, display in metadata:
		name = _metadata_label(label)
		if key is not None:
			_metadata_key(key, name)
		_metadata_text(display, name)


def _normalize_metadata(metadata):
	if len(metadata) > MAX_METADATA_FIELDS:
		raise ValueError('ListItem metadata has more than %d labels.' % MAX_METADATA_FIELDS)
	result = []
	for label, value in metadata.items():
		name = _metadata_label(label)
		if isinstance(value, (tuple, list)) and not value:
			result.append((label, None, ''))
		elif isinstance(value, (tuple, list)):
			if len(value) != 2:
				raise ValueError('%s must be (), a value or a (sort_key, text) pair.' % name)
			result.append((label, _metadata_key(value[0], name), _metadata_text(value[1], name)))
		else:
			key = _metadata_key(value, name)
			result.append((label, key, key if isinstance(key, str) else _metadata_text(str(key), name)))
	return tuple(result)


def match_positions(matcher, text, query):
	if text.isascii():
		result = matcher(text.lower(), query.casefold())
		return tuple(dict.fromkeys(result)) if result is not None else None
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
		self._work_slot = BoundedSemaphore(1)

	def try_claim(self):
		if not self._work_slot.acquire(blocking=False):
			return None
		released = False
		guard = RLock()
		def release():
			nonlocal released
			with guard:
				if not released:
					released = True
					self._work_slot.release()
		return release

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
		if name not in _resources:
			_resources[name] = Resource()
		return _resources[name]


class UiOwner:
	def __init__(self, *, resource_root=None):
		from os.path import abspath
		self._resource_root = abspath(resource_root) if resource_root is not None else None
		self.active = True
		self._sessions = set()
		self._lock = RLock()

	@property
	def resource_root(self):
		return self._resource_root

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
	try:
		Thread(target=run, daemon=True).start()
	except BaseException:
		_work_slots.release()
		raise
	return True