from calculate_file_hash.hashing import AVAILABLE_ALGORITHMS, compute_hash, default_algorithm, settings_snapshot
from calculate_file_hash.ui import HashController
from fman import DirectoryPaneCommand, QuicksearchItem, Task, load_json, save_json, show_quicksearch, show_status_message, submit_task
from fman.ui import settings_resource
from threading import Lock
from weakref import WeakKeyDictionary

import os
import stat


_SETTINGS_NAME = 'CalculateFileHash.json'
_settings_lock = settings_resource(_SETTINGS_NAME).lock
_busy_lock = Lock()
_busy_panes = WeakKeyDictionary()
_warned_default = False


def _load_settings():
	with _settings_lock:
		return settings_snapshot(load_json(_SETTINGS_NAME, default={}))


def _default(settings):
	global _warned_default
	algorithm = default_algorithm(settings['default_algorithm'], AVAILABLE_ALGORITHMS)
	with _settings_lock:
		warn = algorithm != settings['default_algorithm'] and not _warned_default
		if warn:
			_warned_default = True
	if warn:
		show_status_message('Configured hash algorithm unavailable; using %s.' % algorithm, timeout_secs=3)
	return algorithm


def _remember(algorithm, owner):
	with _settings_lock:
		loaded = load_json(_SETTINGS_NAME, default={})
		settings = settings_snapshot(loaded)
		if not owner.active or not settings['remember_last_algorithm'] or settings['default_algorithm'] == algorithm:
			return
		updated = dict(loaded)
		updated['default_algorithm'] = algorithm
		save_json(_SETTINGS_NAME, updated)


def _algorithm_items(query, configured):
	items = []
	for identifier, label in AVAILABLE_ALGORITHMS:
		letters = iter((label + ' ' + identifier).casefold())
		if all(character in letters for character in query.casefold()):
			items.append(QuicksearchItem(identifier, label, hint=identifier, description='default' if identifier == configured else ''))
	return items


class _HashFileTask(Task):
	def __init__(self, request, size, chunk_size):
		super().__init__('Calculate %s: %s' % (request.algorithm, request.path), size)
		self.request = request
		self.chunk_size = chunk_size
		self.result = None
		self.completed = False

	def __call__(self):
		self.result = compute_hash(self.request.path, self.request.algorithm,
			lambda done: self.set_progress(min(done, self.get_size())), self.check_canceled, self.chunk_size)
		self.check_canceled()
		self.completed = True

	def check_canceled(self):
		super().check_canceled()
		self.request.check_canceled()


class CalculateFileHash(DirectoryPaneCommand):
	aliases = ('Calculate file hash', 'File hash', 'Checksum')

	def is_visible(self):
		path = self.pane.get_path()
		url = self.pane.get_file_under_cursor()
		return isinstance(path, str) and path.startswith('file://') and isinstance(url, str) and url.startswith('file://')

	def __call__(self, algorithm=None, url=None):
		if HashController.owner is None or not HashController.owner.active:
			return
		url = self.pane.get_file_under_cursor() if url is None else url
		if not self._valid_target(url):
			return
		try:
			settings = _load_settings()
			selected = _default(settings) if algorithm is None else algorithm
			if not isinstance(selected, str) or selected not in dict(AVAILABLE_ALGORITHMS):
				raise ValueError('Unsupported hash algorithm: %s' % selected)
		except (OSError, ValueError) as error:
			show_status_message(str(error), timeout_secs=3)
			return
		self._hash_and_show(url, selected, settings, algorithm is not None)

	def _valid_target(self, url):
		if not url:
			show_status_message('Place the cursor on a file to hash it.', timeout_secs=3)
			return False
		if not isinstance(url, str) or not url.startswith('file://'):
			show_status_message('Hashing is available only for local files.', timeout_secs=3)
			return False
		return True

	def _hash_and_show(self, url, algorithm, settings, remember=False):
		with _busy_lock:
			busy = self.pane in _busy_panes
			if not busy:
				_busy_panes[self.pane] = True
		if busy:
			show_status_message('A file hash is already being calculated for this pane.', timeout_secs=3)
			return
		try:
			if not HashController.owner.active:
				return
			window = HashController.show(self.pane)
			session = window.session
			request = session.begin(url, algorithm, settings['auto_copy'])
			if request is None:
				return
			result, error, status_only = None, None, False
			try:
				request.check_canceled()
				info = os.stat(request.path)
				request.check_canceled()
				if not stat.S_ISREG(info.st_mode):
					error, status_only = 'Place the cursor on a file to hash it.', True
				else:
					if remember:
						try:
							_remember(algorithm, request.owner)
						except OSError as save_error:
							show_status_message('Could not save hash preference: %s' % save_error, timeout_secs=3)
					task = _HashFileTask(request, info.st_size, settings['chunk_size_mib'] * 1024 * 1024)
					submit_task(task)
					if task.completed:
						if task.result.changed:
							error = 'The file changed while it was being hashed. Please retry.'
						else:
							result = task.result
			except Task.Canceled:
				pass
			except OSError as read_error:
				error = 'Could not read %s (%s).' % (request.path, read_error.strerror or str(read_error))
			except ValueError as hash_error:
				error = str(hash_error)
			finally:
				session.complete(request, result, error, status_only)
		finally:
			with _busy_lock:
				_busy_panes.pop(self.pane, None)


class CalculateFileHashBy(CalculateFileHash):
	aliases = ('Calculate file hash by', 'File hash by algorithm')

	def __call__(self):
		if HashController.owner is None or not HashController.owner.active:
			return
		url = self.pane.get_file_under_cursor()
		if not self._valid_target(url):
			return
		try:
			settings = _load_settings()
		except OSError as error:
			show_status_message(str(error), timeout_secs=3)
			return
		try:
			configured = _default(settings)
		except ValueError:
			configured = None
		names = tuple(identifier for identifier, label in AVAILABLE_ALGORITHMS)
		choice = show_quicksearch(lambda query: _algorithm_items(query, configured), item=names.index(configured) if configured in names else 0)
		if choice is None or not choice[1] or not HashController.owner.active:
			return
		algorithm = choice[1]
		if algorithm not in names:
			show_status_message('Unsupported hash algorithm: %s' % algorithm, timeout_secs=3)
			return
		self._hash_and_show(url, algorithm, settings, True)