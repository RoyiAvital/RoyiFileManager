from dataclasses import dataclass
from hashlib import sha256
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
from threading import Condition, Event, Thread
from time import monotonic

from everything_search.ipc import Native, SORTS


def normalize_folder(path):
	if not isinstance(path, str) or any(character in path for character in '\0\r\n"'):
		raise ValueError('Choose an absolute local folder.')
	path = ntpath.normpath(path)
	if not re.match(r'^[a-zA-Z]:\\', path):
		raise ValueError('Choose an absolute local folder, not a network or relative path.')
	return path


def contains(parent, child):
	try:
		return ntpath.commonpath((parent.casefold(), child.casefold())) == parent.casefold()
	except ValueError:
		return False


def normalize_folders(paths):
	roots = []
	for path in paths:
		path = normalize_folder(path)
		if any(contains(root, path) for root in roots):
			continue
		roots = [root for root in roots if not contains(path, root)]
		roots.append(path)
	return tuple(roots)


def add_folder(roots, path):
	roots = normalize_folders(roots)
	path = normalize_folder(path)
	if any(contains(root, path) for root in roots):
		return tuple(roots), ()
	replaced = tuple(root for root in roots if contains(path, root))
	return tuple(root for root in roots if root not in replaced) + (path,), replaced


@dataclass(frozen=True)
class Settings:
	folders: tuple = ()
	executable: str = ''
	instance: str = 'RoyiFileManager'
	max_results: int = 100
	sort: str = 'name'
	show_metadata: bool = True
	exit_with_application: bool = True
	query_timeout_ms: int = 50

	@classmethod
	def load(cls, data):
		if not isinstance(data, dict):
			raise ValueError('Everything.json must contain an object.')
		values = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
		folders = values.get('folders', [])
		if not isinstance(folders, (list, tuple)):
			raise ValueError('Everything folders must be a list.')
		values['folders'] = normalize_folders(folders)
		settings = cls(**values)
		if not isinstance(settings.instance, str) or not re.fullmatch(
				r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', settings.instance):
			raise ValueError('Everything instance must be a nonempty simple name.')
		if not isinstance(settings.executable, str) or '\0' in settings.executable:
			raise ValueError('Everything executable must be a path.')
		if type(settings.max_results) is not int or not 1 <= settings.max_results <= 1000:
			raise ValueError('Everything max_results must be between 1 and 1000.')
		if not isinstance(settings.sort, str) or settings.sort not in SORTS:
			raise ValueError('Unknown Everything sort.')
		if type(settings.query_timeout_ms) is not int or not 1 <= settings.query_timeout_ms <= 500:
			raise ValueError('Everything query_timeout_ms must be between 1 and 500.')
		if type(settings.show_metadata) is not bool or type(settings.exit_with_application) is not bool:
			raise ValueError('Everything metadata and exit settings must be booleans.')
		return settings


def make_ini(settings, state_directory):
	values = {
		'app_data': 0, 'run_as_admin': 0, 'show_tray_icon': 0,
		'run_in_background': 1, 'check_for_updates_on_startup': 0,
		'search_history_enabled': 0, 'run_history_enabled': 0,
		'auto_include_fixed_volumes': 0, 'auto_include_removable_volumes': 0,
		'auto_include_fixed_refs_volumes': 0, 'auto_include_removable_refs_volumes': 0,
		'ntfs_volume_guids': '', 'ntfs_volume_paths': '', 'ntfs_volume_includes': '',
		'refs_volume_guids': '', 'refs_volume_paths': '', 'refs_volume_includes': '',
		'folders': ','.join(json.dumps(path, ensure_ascii=False) for path in settings.folders),
		'folder_monitor_changes': ','.join('1' for _ in settings.folders),
		'folder_update_thread_mode_background': 1,
		'db_location': str(state_directory), 'index_size': 1,
		'index_date_modified': 1, 'index_date_created': 0, 'index_attributes': 1,
		'fast_path_sort': 1, 'fast_size_sort': 1, 'fast_date_modified_sort': 1,
		'http_server_enabled': 0, 'etp_server_enabled': 0,
		'allow_http_server': 0, 'allow_etp_server': 0,
	}
	return '[Everything]\n' + ''.join(f'{key}={value}\n' for key, value in values.items())


class Superseded(Exception):
	pass


class ProcessRuntime:
	def __init__(self, state_directory, bundled_executable):
		self.directory = Path(state_directory)
		self.bundled_executable = str(bundled_executable)
		self.native = Native()
		self.identity = None
		self.name = None
		self.process = None
		self.settings = None
		self._config_hash = None
		self._file_lock = None

	def _lock_directory(self):
		import msvcrt
		self.directory.mkdir(parents=True, exist_ok=True)
		lock = (self.directory / 'instance.lock').open('a+b')
		try:
			if lock.tell() == 0:
				lock.write(b'\0')
				lock.flush()
			lock.seek(0)
			msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
		except OSError as error:
			lock.close()
			raise RuntimeError('Everything is managed by another application instance.') from error
		self._file_lock = lock

	def _adopt(self):
		try:
			owner = json.loads((self.directory / 'owner.json').read_text(encoding='utf-8'))
		except FileNotFoundError:
			return
		if not isinstance(owner, dict) or not isinstance(owner.get('identity'), list) or \
				len(owner['identity']) != 3 or not isinstance(owner.get('instance'), str):
			raise RuntimeError('Invalid Everything process ownership file; refusing to control an instance.')
		window = self.native.find_instance(owner['instance'])
		if window:
			if self.native.identity(window) != tuple(owner['identity']):
				raise RuntimeError('Everything instance ownership has changed; refusing to stop it.')
			self.identity, self.name = tuple(owner['identity']), owner['instance']
			self._config_hash = owner.get('config_hash')

	def apply(self, settings, canceled):
		if self._file_lock is None:
			self._lock_directory()
			self._adopt()
		if canceled.is_set():
			raise Superseded()
		executable = Path(settings.executable or self.bundled_executable)
		configuration = make_ini(settings, self.directory)
		config_hash = sha256(configuration.encode('utf-8')).hexdigest()
		if settings.folders and self.identity is not None and self.name == settings.instance and \
				self._config_hash == config_hash and str(executable.resolve()).casefold() == self.identity[2]:
			window = self.native.find_instance(self.name)
			if window and self.native.identity(window) == self.identity and self._ready(window):
				self.settings = settings
				return self.identity
		self.stop()
		self.settings = settings
		if canceled.is_set():
			raise Superseded()
		if not settings.folders:
			return None
		if self.native.find_instance(settings.instance):
			raise RuntimeError('Everything instance name is already in use; choose another name.')
		if not executable.is_absolute() or not executable.is_file():
			raise RuntimeError('Everything.exe not found. Run python build.py run or set executable in Everything.json.')
		ini = self.directory / 'Everything.ini'
		ini.write_text(configuration, encoding='utf-8')
		self.name = settings.instance
		self.process = subprocess.Popen([str(executable), '-instance', self.name,
			'-startup', '-config', str(ini)], cwd=self.directory,
			creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
		try:
			self.identity = self.native.identity_for_pid(self.process.pid)
			self._config_hash = config_hash
			temporary = self.directory / 'owner.json.tmp'
			temporary.write_text(json.dumps({'instance': self.name, 'identity': self.identity,
				'config_hash': config_hash}), encoding='utf-8')
			temporary.replace(self.directory / 'owner.json')
			deadline = monotonic() + 30
			while not canceled.is_set():
				if self.process.poll() is not None:
					raise RuntimeError('Everything exited before its database became available.')
				window = self.native.find_instance(self.name)
				if window:
					if self.native.identity(window) != self.identity:
						raise RuntimeError('Everything instance name was claimed by another process.')
					if self._ready(window):
						return self.identity
				if monotonic() >= deadline:
					raise RuntimeError('Everything database did not become ready within 30 seconds.')
				canceled.wait(0.05)
			raise Superseded()
		except Exception:
			self.stop()
			raise

	def _ready(self, window):
		if not self.native.probe(window, 401):
			return False
		version = tuple(self.native.probe(window, command) for command in range(4))
		if version[:2] != (1, 4) or version < (1, 4, 1, 877):
			raise RuntimeError('Use a compatible Everything 1.4 portable executable; 1.5 is not certified.')
		if self.native.probe(window, 403) or self.native.probe(window, 404):
			raise RuntimeError('Everything must run without admin privileges or AppData storage.')
		return True

	def stop(self):
		if self.identity is None:
			if self.process is not None and self.process.poll() is None:
				self.process.terminate()
				self.process.wait(timeout=5)
			return
		window = self.native.find_instance(self.name)
		if window:
			if self.native.identity(window) != self.identity:
				raise RuntimeError('Everything ownership changed; refusing to stop another process.')
			self.native.probe(window, 4)
			deadline = monotonic() + 15
			waiter = Event()
			while self.native.find_instance(self.name):
				if monotonic() >= deadline:
					raise RuntimeError('Everything did not stop within 15 seconds.')
				waiter.wait(0.05)
		elif self.process is not None and self.process.poll() is None:
			self.process.terminate()
			self.process.wait(timeout=5)
		if self.process is not None:
			self.process.wait(timeout=5)
		self.identity, self.name, self.process = None, None, None
		self._config_hash = None
		(self.directory / 'owner.json').unlink(missing_ok=True)

	def close(self, exit_process=True):
		try:
			if exit_process:
				self.stop()
		finally:
			if self._file_lock is not None:
				self._file_lock.close()
				self._file_lock = None


@dataclass(frozen=True)
class State:
	generation: int = 0
	status: str = 'stopped'
	identity: tuple | None = None
	error: str = ''


class Manager:
	def __init__(self, state_directory, executable, notify=lambda state: None,
			runtime_factory=ProcessRuntime, prepare=lambda: None):
		self._directory, self._executable = state_directory, executable
		self._notify, self._runtime_factory = notify, runtime_factory
		self._prepare = prepare
		self._condition = Condition()
		self._state = State()
		self._settings = None
		self._thread = None
		self._closed = False
		self._canceled = Event()

	def request(self, settings, force=False):
		with self._condition:
			if self._closed:
				raise RuntimeError('Everything manager is closed.')
			if settings == self._settings and not force and self._state.status != 'error':
				return self._state
			self._settings = settings
			self._canceled.set()
			self._canceled = Event()
			self._state = State(self._state.generation + 1,
				'starting' if settings.folders else 'stopped')
			if self._thread is None and (settings.folders or force):
				self._thread = Thread(target=self._run, name='everything-instance', daemon=True)
				self._thread.start()
			self._condition.notify_all()
			return self._state

	def snapshot(self):
		with self._condition:
			return self._state

	def invalidate(self, state, error):
		with self._condition:
			if not self._closed and self._state == state:
				self._state = State(state.generation, 'error', error=str(error))

	def _run(self):
		runtime = None
		processed = -1
		try:
			while True:
				with self._condition:
					self._condition.wait_for(lambda: self._closed or self._state.generation != processed)
					if self._closed:
						break
					generation, settings, canceled = self._state.generation, self._settings, self._canceled
				try:
					if settings.folders:
						self._prepare()
					if runtime is None:
						runtime = self._runtime_factory(self._directory, self._executable)
					identity = runtime.apply(settings, canceled)
					state = State(generation, 'ready' if settings.folders else 'stopped', identity)
				except Superseded:
					continue
				except Exception as error:
					state = State(generation, 'error', error=str(error))
				with self._condition:
					processed = generation
					if self._closed or generation != self._state.generation:
						continue
					self._state = state
				self._notify(state)
		finally:
			if runtime is not None:
				try:
					runtime.close(self._settings.exit_with_application)
				except Exception as error:
					self._notify(State(self._state.generation, 'error', error=str(error)))

	def close(self, wait=True):
		with self._condition:
			self._closed = True
			self._canceled.set()
			self._condition.notify_all()
		if wait and self._thread:
			self._thread.join(21)