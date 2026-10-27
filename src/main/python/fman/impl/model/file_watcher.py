from contextlib import contextmanager
from fman.url import dirname
from threading import Lock, local
from weakref import WeakSet

SETTINGS = 'AppSettings.yaml'
LIVE_REFRESH = 'live_refresh_during_file_operations'

_state = local()

def live_refresh_enabled():
	"""Return the Core setting; missing or invalid values keep live refresh on."""
	try:
		settings = _load_settings()
	except (OSError, ValueError):
		return True
	value = settings.get(LIVE_REFRESH, True) if isinstance(settings, dict) else True
	return value if isinstance(value, bool) else True

def _load_settings():
	# Never creates the application context: tasks also run in tests and tools without one.
	from fman.impl.application_context import get_existing_application_context
	context = get_existing_application_context()
	return {} if context is None else context.config.load_json(SETTINGS, {})

@contextmanager
def deferred_refresh(defer=True):
	"""Defer pane reloads raised on this thread until the outermost scope exits."""
	if not defer or getattr(_state, 'models', None) is not None:
		yield
		return
	_state.models = WeakSet()
	try:
		yield
	finally:
		models, _state.models = list(_state.models), None
		for model in models:
			try:
				model.reload()
			except RuntimeError:
				pass # Qt object already deleted

def _defer(model):
	models = getattr(_state, 'models', None)
	if models is None:
		return False
	models.add(model)
	return True

class FileWatcher:
	def __init__(self, fs, model):
		self._fs = fs
		self._model = model
		self._lock = Lock()
	def start(self):
		with self._lock:
			self._fs.file_added.add_callback(self._on_file_added)
			self._fs.file_removed.add_callback(self._on_file_removed)
			try:
				self._fs.add_file_changed_callback(
					self._model.get_location(), self._on_file_changed
				)
			except BaseException:
				self._fs.file_removed.remove_callback(self._on_file_removed)
				self._fs.file_added.remove_callback(self._on_file_added)
				raise
	def shutdown(self):
		with self._lock:
			try:
				self._fs.remove_file_changed_callback(
					self._model.get_location(), self._on_file_changed
				)
			except (ValueError, FileNotFoundError):
				pass
			for event, callback in ((self._fs.file_removed, self._on_file_removed),
				(self._fs.file_added, self._on_file_added)):
				try:
					event.remove_callback(callback)
				except ValueError:
					pass
	def _on_file_added(self, url):
		if self._is_in_root(url) and not _defer(self._model):
			self._model.notify_file_added(url)
	def _on_file_removed(self, url):
		if self._is_in_root(url) and not _defer(self._model):
			self._model.notify_file_removed(url)
	def _on_file_changed(self, url):
		if url == self._model.get_location():
			# The common case
			if _defer(self._model):
				self._fs.clear_cache(url) # Live mode clears it when the scan starts
			else:
				self._model.reload()
		elif self._is_in_root(url):
			if _defer(self._model):
				self._fs.clear_cache(url)
			else:
				self._model.notify_file_changed(url)
	def _is_in_root(self, url):
		return dirname(url) == self._model.get_location()