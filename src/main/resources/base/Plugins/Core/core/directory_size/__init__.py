from concurrent.futures import ThreadPoolExecutor
from fman import ApplicationCommand, DirectoryPaneCommand, Task, load_json, save_json, \
	show_alert, show_status_message
from fman.impl.plugins.plugin import PluginService
from fman.impl.status_bar import format_size
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import as_url, as_human_readable, dirname
from PyQt5.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QApplication
from PyQt5 import sip
from threading import Event, Lock

from core.directory_size.calculator import DirSize, scan_parents, walk_directory

import os


SETTINGS = 'DirectorySize.json'
COLUMN = 'core.Size'
DEFAULTS = {'enabled': False, 'max_files': 10000000}
_service = None


def settings_snapshot(value):
	result = dict(value) if isinstance(value, dict) else {}
	for name, default in DEFAULTS.items():
		current = result.get(name)
		valid = type(current) is bool if type(default) is bool else type(current) is int and current >= 0
		if not valid:
			result[name] = default
	return result


def _key(url):
	return os.path.normcase(os.path.normpath(as_human_readable(url)))


def format_result(result):
	if result is None:
		return '...'
	if result.skipped_link:
		return ''
	if result.size_bytes is None:
		return '?'
	return format_size(result.size_bytes) + ('...' if not result.complete else '') + \
		('+' if result.capped else '') + ('?' if result.errors else '')


def get_value(url):
	service = _service
	if service is None or not service._active or not service.enabled or not url.startswith('file://'):
		return None
	result = service.result(url)
	size = result.size_bytes if result is not None and result.size_bytes is not None else -1
	return format_result(result), size


class _Delivery(QObject):
	changed = pyqtSignal(int, object)

	def __init__(self, receive):
		super().__init__()
		self._receive = receive
		self.changed.connect(self.deliver, Qt.QueuedConnection)

	@pyqtSlot(int, object)
	def deliver(self, generation, results):
		self._receive(generation, results)


def _scan(paths, max_files, canceled, generation, emit):
	def check():
		if canceled.is_set():
			raise InterruptedError()
	def publish(results):
		check()
		try:
			emit(generation, results)
		except RuntimeError:
			canceled.set()
	try:
		scan_parents(paths, max_files, check, publish)
	except InterruptedError:
		pass


class DirectorySizeService(PluginService):
	def __init__(self, window, owner):
		super().__init__(window, owner)
		self.settings = dict(DEFAULTS)
		self._initialized = False
		self.enabled = False
		self._active = False
		self._panes = []
		self._callbacks = {}
		self._executor = None
		self._future = None
		self._canceled = Event()
		self._generation = 0
		self._results = {}
		self._result_lock = Lock()
		self._toggle_lock = Lock()
		self._delivery = None
		self._explicit_task = None

	def start(self):
		self._start_ui()

	@run_in_main_thread
	def _start_ui(self):
		global _service
		self._active = True
		_service = self
		self._delivery = _Delivery(self._receive)
		QApplication.instance().aboutToQuit.connect(self.owner.invalidate)

	@run_in_main_thread
	def on_pane_added(self, pane):
		if not self._active or pane in self._panes:
			return
		self._panes.append(pane)
		if not self._initialized:
			self._initialized = True
			self.settings = settings_snapshot(load_json(SETTINGS, default={}))
			self.set_enabled(self.settings['enabled'])
			return
		if self.enabled:
			self._attach(pane)
			self.restart()

	def _attach(self, pane):
		self._callbacks[pane] = (
			pane.on_path_changed(self.restart),
			pane.on_closed(lambda: self._pane_closed(pane))
		)

	def _pane_closed(self, pane):
		for unsubscribe in self._callbacks.pop(pane, ()):
			unsubscribe()
		if pane in self._panes:
			self._panes.remove(pane)
		self.restart()

	@run_in_main_thread
	def set_enabled(self, enabled):
		if not self._active or enabled == self.enabled:
			return
		self.enabled = enabled
		if enabled:
			self._panes = [pane for pane in self._panes if not sip.isdeleted(pane._widget)]
			self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='directory-size')
			for pane in self._panes:
				self._attach(pane)
			self.restart()
		else:
			self._cancel()
			for pane, callbacks in tuple(self._callbacks.items()):
				for unsubscribe in callbacks:
					unsubscribe()
			self._callbacks.clear()
			self._executor.shutdown(wait=False, cancel_futures=True)
			self._executor = None
			for pane in self._panes:
				if not sip.isdeleted(pane._widget) and pane.get_path().startswith('file://'):
					pane.reload()

	def _cancel(self):
		self._generation += 1
		self._canceled.set()
		if self._future is not None:
			self._future.cancel()
		self._future = None
		with self._result_lock:
			self._results.clear()

	@run_in_main_thread
	def restart(self):
		if not self._active or not self.enabled:
			return
		self._cancel()
		paths = {}
		for pane in self._panes:
			url = pane.get_path()
			if url.startswith('file://'):
				paths[_key(url)] = as_human_readable(url)
				pane.reload()
		self._canceled = Event()
		if paths:
			self._future = self._executor.submit(_scan, tuple(paths.values()),
				self.settings['max_files'], self._canceled, self._generation, self._delivery.changed.emit)

	def _receive(self, generation, results):
		if not self._active or not self.owner.active or not self.enabled or generation != self._generation:
			return
		urls = tuple(as_url(path) for path in results)
		with self._result_lock:
			self._results.update({_key(as_url(path)): result for path, result in results.items()})
		for pane in self._panes:
			location = pane.get_path()
			if location.startswith('file://'):
				parent = self._results.get(_key(location))
				if parent is not None and parent.size_bytes is None and parent.errors:
					pane.reload()
				else:
					pane._widget.refresh_files(urls)

	def result(self, url):
		with self._result_lock:
			result = self._results.get(_key(url))
			if result is not None:
				return result
			parent = self._results.get(_key(dirname(url)))
			if parent is not None and parent.size_bytes is None and parent.errors:
				return parent

	@run_in_main_thread
	def begin_explicit_calculation(self, paths):
		if not self._active or not self.owner.active:
			return
		task = _DirectorySizeTask(paths, self.settings['max_files'])
		if not self.owner.attach(task.cancel_event.set):
			return
		if self._explicit_task is not None:
			self._explicit_task.cancel_event.set()
		self._explicit_task = task
		text = 'Calculating %s size...' % paths[0] if len(paths) == 1 else \
			'Calculating sizes of %d directories...' % len(paths)
		show_status_message(text)
		return task

	@run_in_main_thread
	def finish_explicit_calculation(self, task):
		self.owner.detach(task.cancel_event.set)
		if self._explicit_task is not task:
			return
		self._explicit_task = None
		if not self._active or not self.owner.active:
			return
		if task.results is not None:
			show_status_message(summary_text(task.paths, task.results), timeout_secs=5)
		elif task.cancel_event.is_set():
			show_status_message('Directory size calculation canceled.', timeout_secs=5)

	def toggle(self):
		with self._toggle_lock:
			if not self._active:
				return
			settings = dict(self.settings, enabled=not self.enabled)
			try:
				save_json(SETTINGS, settings)
			except (OSError, ValueError) as error:
				show_alert(str(error))
				return
			if not self._active:
				return
			self.settings = settings
			self.set_enabled(settings['enabled'])
			show_status_message('Directory sizes: ' + ('On' if self.enabled else 'Off'), timeout_secs=5)

	@run_in_main_thread
	def dispose(self):
		global _service
		if not self._active:
			return
		self.set_enabled(False)
		self._active = False
		self._panes.clear()
		if _service is self:
			_service = None
		QApplication.instance().aboutToQuit.disconnect(self.owner.invalidate)
		self._delivery.deleteLater()


class ToggleDirectorySizeColumn(ApplicationCommand):
	aliases = ('Toggle directory sizes',)
	def is_visible(self):
		return True
	def __call__(self):
		if _service is not None:
			_service.toggle()


class RecalculateDirectorySizes(ApplicationCommand):
	def is_visible(self):
		return _service is not None and _service.enabled
	def __call__(self):
		if _service is not None:
			_service.restart()


class SortByDirectorySize(DirectoryPaneCommand):
	def is_visible(self):
		return _service is not None and _service.enabled and self.pane.get_path().startswith('file://') and COLUMN in self.pane.get_columns()
	@run_in_main_thread
	def __call__(self):
		if self.is_visible():
			column, ascending = self.pane.get_sort_column()
			self.pane.set_sort_column(COLUMN, not ascending if column == COLUMN else True)


class ShowDirectorySize(DirectoryPaneCommand):
	def is_visible(self):
		return self.pane.get_path().startswith('file://')
	def __call__(self):
		service = _service
		if service is None or not service.owner.active:
			return
		paths = []
		for url in self.get_chosen_files():
			if url.startswith('file://'):
				path = as_human_readable(url)
				if os.path.isdir(path) or os.path.islink(path) or os.path.isjunction(path):
					paths.append(path)
		if not paths:
			show_status_message('Choose a local directory.', timeout_secs=5)
			return
		task = service.begin_explicit_calculation(tuple(paths))
		if task is None:
			return
		try:
			task()
		except Task.Canceled:
			task.cancel_event.set()
		finally:
			service.finish_explicit_calculation(task)


class _DirectorySizeTask(Task):
	def __init__(self, paths, max_files):
		super().__init__('Directory size')
		self.paths = paths
		self.max_files = max_files
		self.cancel_event = Event()
		self.results = None
	def check_canceled(self):
		super().check_canceled()
		if self.cancel_event.is_set():
			raise self.Canceled()
	def __call__(self):
		results = []
		for path in self.paths:
			for result in walk_directory(path, self.max_files, self.check_canceled):
				if result.complete:
					results.append(result)
		self.check_canceled()
		self.results = results


def summary_text(paths, results):
	name = os.path.basename(paths[0]) if len(paths) == 1 else '%d directories' % len(paths)
	known = [result for result in results if result.size_bytes is not None]
	skipped = sum(result.skipped_link for result in results)
	errors = any(result.errors for result in results)
	capped = any(result.capped for result in results)
	if not known:
		return name + (': linked directories skipped' if skipped and not errors else ': size unavailable')
	text = name + ': ' + ('at least ' if errors or capped or skipped else '') + \
		format_size(sum(result.size_bytes for result in known)) + \
		' (%d files)' % sum(result.files for result in known)
	flags = [label for present, label in ((capped, 'file limit'), (errors, 'errors'), (skipped, 'links skipped')) if present]
	return text + (' (partial; ' + ', '.join(flags) + ')' if flags else '')