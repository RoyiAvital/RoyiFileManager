import atexit
import ctypes
from datetime import datetime
from hashlib import blake2b
import ntpath
import os
from pathlib import Path
from threading import Thread
from weakref import WeakSet

from fman import DATA_DIRECTORY, DirectoryPaneCommand, DirectoryPaneListener, NO, YES, QuicksearchItem, \
	Task, clipboard, load_json, save_json, show_alert, show_prompt, show_quicksearch, show_status_message, submit_task
from fman.impl.plugins.plugin import PluginService
from fman.fs import Column, FileSystem
from fman.listing import Listing
from fman.impl.status_bar import format_size
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import as_human_readable, as_url
from PyQt5.QtCore import QCoreApplication, QObject, QThread, Qt, pyqtSignal, pyqtSlot

from everything_search.instance import Manager, Settings, normalize_folder, normalize_folders
from everything_search.ipc import IpcClient, IpcError, NotRunning, QueryTimeout


_service = None
_SETTINGS_NAME = 'Everything.json'
FOLDERS_ROOT = 'everything-folders://'


def _folder_key(path):
	return blake2b(path.casefold().encode('utf-8'), digest_size=16).hexdigest()


class EverythingFolders(FileSystem):
	scheme = FOLDERS_ROOT
	instances = WeakSet()

	def __init__(self):
		super().__init__()
		self.instances.add(self)

	def get_default_columns(self, path):
		return 'core.Name', 'everything_search.IndexedFolderPath'

	def scan(self, path, check_canceled):
		if path:
			raise NotADirectoryError('Open an indexed folder to browse its contents.')
		_, settings = _read_settings()
		keys = []
		for folder in settings.folders:
			check_canceled()
			keys.append(_folder_key(folder))
		return Listing.create(FOLDERS_ROOT, keys,
			labels=tuple(ntpath.basename(folder) or folder for folder in settings.folders),
			identities=b''.join(bytes.fromhex(key) for key in keys),
			extra=(('path', settings.folders),))

	def folder_path(self, key):
		_, settings = _read_settings()
		for folder in settings.folders:
			if _folder_key(folder) == key:
				return folder
		raise FileNotFoundError('This folder is no longer in the Everything database.')

	def name(self, path):
		if not path:
			return 'Everything folders'
		folder = self.folder_path(path)
		return ntpath.basename(folder) or folder

	def is_dir(self, path):
		if path:
			self.folder_path(path)
		return not path


class IndexedFolderPath(Column):
	display_name = 'Path'
	keys_depend_on_external_data = False

	def text(self, listing, index):
		return listing.column('path')[index]

	def keys(self, listing, ascending):
		return tuple(path.casefold() for path in listing.column('path'))


def _on_qt(function, *args):
	application = QCoreApplication.instance()
	if application is not None and QThread.currentThread() != application.thread():
		return run_in_main_thread(function)(*args)
	return function(*args)


class Notifications(QObject):
	changed = pyqtSignal(object)

	def __init__(self, service):
		super().__init__()
		self.service = service
		self.changed.connect(self.receive, Qt.QueuedConnection)

	@pyqtSlot(object)
	def receive(self, state):
		service = self.service
		if service.closed or not service.owner.active or service.manager.snapshot() != state:
			return
		if state.status == 'error':
			show_status_message('Everything: ' + state.error)
		elif state.status == 'ready':
			show_status_message('Everything database is ready.', timeout_secs=4)
		else:
			show_status_message('Everything database is stopped.', timeout_secs=4)


class EverythingService(PluginService):
	def start(self):
		global _service
		self.manager = None
		self.client = None
		self.notifications = None
		self.closed = False
		self._quit_connected = False
		self._cleanup_thread = None
		_service = self

	def ensure(self, settings, force=False):
		return _on_qt(self._ensure, settings, force)

	def _ensure(self, settings, force):
		if self.closed or not self.owner.active:
			raise RuntimeError('Everything plug-in is no longer active.')
		if self.manager is None:
			self.notifications = Notifications(self)
			self.client = IpcClient()
			self.manager = Manager(Path(DATA_DIRECTORY) / 'Local' / 'Everything',
				Path(__file__).resolve().parent.parent / 'bin' / 'Everything.exe',
				self.notifications.changed.emit, prepare=self.client.start)
			application = QCoreApplication.instance()
			if application is not None:
				application.aboutToQuit.connect(self.dispose)
				self._quit_connected = True
			atexit.register(self.dispose)
		self.manager.request(settings, force)
		return self

	def dispose(self):
		return _on_qt(self._dispose)

	def _dispose(self):
		global _service
		if self.closed:
			return
		self.closed = True
		if self.client is not None:
			self.client.close(wait=False)
		if self.manager is not None:
			self.manager.close(wait=False)
		if self._quit_connected:
			application = QCoreApplication.instance()
			if application is not None:
				try:
					application.aboutToQuit.disconnect(self.dispose)
				except (RuntimeError, TypeError):
					pass
		atexit.unregister(self.dispose)
		if _service is self:
			_service = None
		if any(worker is not None and worker._thread is not None for worker in (self.client, self.manager)):
			self._cleanup_thread = Thread(target=self._finish_close, name='everything-shutdown', daemon=False)
			self._cleanup_thread.start()
		elif self.notifications is not None:
			self.notifications.deleteLater()

	def _finish_close(self):
		try:
			if self.client is not None:
				self.client.close()
		finally:
			try:
				if self.manager is not None:
					self.manager.close()
			finally:
				if self.notifications is not None and \
						(self.manager._thread is None or not self.manager._thread.is_alive()):
					self.notifications.deleteLater()


def _read_settings():
	return _on_qt(_load_settings)


def _load_settings():
	data = load_json(_SETTINGS_NAME, default={})
	return data, Settings.load(data)


def _get_service(settings, force=False):
	if _service is None:
		raise RuntimeError('Everything plug-in service is not loaded.')
	return _service.ensure(settings, force)


def _service_active(service):
	return service is not None and service is _service and not service.closed and service.owner.active


def _hint(title):
	return [QuicksearchItem('', title=title)]


def search_items(service, settings, query):
	if service.closed:
		return _hint('Everything plug-in is closed.')
	if not settings.folders:
		return _hint('No folders in the Everything database.')
	state = service.manager.snapshot()
	if state.status == 'error':
		return _hint(state.error)
	if state.status != 'ready':
		return _hint('Starting Everything; try the query again shortly.')
	if not query.strip():
		return _hint('Search file by Everything')
	try:
		results = service.client.query(settings.instance, state.identity, query,
			settings.max_results, settings.sort, settings.query_timeout_ms)
	except QueryTimeout:
		return _hint('Everything is busy; try the query again.')
	except NotRunning as error:
		message = str(error) + ' Reopen search to retry.'
		service.manager.invalidate(state, message)
		return _hint(message)
	except (IpcError, ValueError, OSError) as error:
		return _hint(str(error))
	if service.closed or service.manager.snapshot() != state:
		return _hint('Everything configuration changed; reopen search.')
	items = []
	for hit in results.hits:
		metadata = []
		if settings.show_metadata:
			if hit.modified_ns is not None:
				try:
					metadata.append(datetime.fromtimestamp(hit.modified_ns / 1e9).strftime('%Y-%m-%d %H:%M'))
				except (ValueError, OverflowError, OSError):
					pass
			if hit.size is not None and not hit.is_folder:
				metadata.append(format_size(hit.size))
		items.append(QuicksearchItem(as_url(hit.path), title=hit.path,
			highlight=list(hit.highlight), description=', '.join(metadata) or ' '))
	if results.total > len(results.hits):
		items.extend(_hint(f'Showing {len(results.hits):,} of {results.total:,}'))
	return items or _hint('No matching files.')


class SearchFileByEverything(DirectoryPaneCommand):
	aliases = ('Search file by Everything',)

	def __call__(self):
		try:
			_, settings = _read_settings()
			service = _get_service(settings)
			result = show_quicksearch(lambda query: search_items(service, settings, query))
			if result and result[1] and not service.closed:
				self.pane.run_command('open_directory', {'url': result[1]})
		except (ValueError, RuntimeError, OSError) as error:
			show_alert(str(error))


def _default_folder(pane):
	for url in (pane.get_file_under_cursor(), pane.get_path()):
		if url and url.startswith('file://'):
			path = as_human_readable(url)
			try:
				path = normalize_folder(path)
			except ValueError:
				continue
			if os.path.isdir(path):
				return path
	return ''


def _validate_new_folder(path, allow_unavailable=False):
	path = normalize_folder(path)
	get_drive_type = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
	get_drive_type.argtypes, get_drive_type.restype = [ctypes.c_wchar_p], ctypes.c_uint
	if get_drive_type(path[:3]) == 4:
		raise ValueError('Network drives cannot be added to this Everything database.')
	if not os.path.isdir(path):
		if not allow_unavailable or os.path.exists(path):
			raise ValueError('The folder does not exist or is unavailable.')
		return path
	return normalize_folder(os.path.realpath(path))


class AddFolderToEverythingDatabase(DirectoryPaneCommand):
	aliases = ('Add folder to Everything database',)

	def __call__(self):
		service = _service
		try:
			if not _service_active(service):
				return
			path, accepted = show_prompt('Add folder to Everything database:', _default_folder(self.pane))
			if not accepted:
				return
			path = _validate_new_folder(path)
			if _add_roots((path,), service) is False:
				show_status_message('This folder is already covered by the Everything database.', timeout_secs=4)
		except (ValueError, RuntimeError, OSError) as error:
			show_alert(str(error))


def _add_roots(paths, service):
	confirmed = ()
	while _service_active(service):
		data, settings = _read_settings()
		roots = normalize_folders((*settings.folders, *paths))
		replaced = tuple(root for root in settings.folders if root not in roots)
		if replaced and replaced != confirmed:
			if not show_alert('Replace these indexed roots with their parent?\n\n' +
				'\n'.join(replaced), YES | NO, NO) & YES:
				return None
			confirmed = replaced
			continue
		if _save_roots(data, roots, service) is None:
			return None
		return roots != settings.folders


def _favorite_snapshot():
	from favorites.store import FavoritesStore
	from fman.ui import settings_resource
	with settings_resource('Favorites.json').lock:
		store = FavoritesStore.load(load_json('Favorites.json', default={}))
		return tuple(favorite.url for favorite in store.favorites), store.invalid_count


def _favorite_paths(service):
	urls, skipped = _on_qt(_favorite_snapshot)
	paths = []
	for url in urls:
		if not _service_active(service):
			break
		if not url.startswith('file://'):
			skipped += 1
			continue
		try:
			paths.append(_validate_new_folder(as_human_readable(url), allow_unavailable=True))
		except (ValueError, OSError):
			skipped += 1
	return normalize_folders(paths), skipped


class AddFavoritesToEverythingDatabase(DirectoryPaneCommand):
	aliases = ('Add favorite folders to Everything database',)

	def __call__(self):
		service = _service
		try:
			if not _service_active(service):
				return
			paths, skipped = _favorite_paths(service)
			if not _service_active(service):
				return
			if paths:
				changed = _add_roots(paths, service)
				if changed is None:
					return
				message = 'Everything: favorite folders added.' if changed else \
					'Favorite folders are already covered by the Everything database.'
			else:
				message = 'No local favorite folders to add.'
			if skipped:
				message += f' Skipped {skipped} invalid, duplicate or non-local favorites.'
			_on_qt(lambda: show_status_message(message, timeout_secs=6))
		except ImportError:
			show_alert('The Favorites plug-in is unavailable.')
		except (ValueError, RuntimeError, OSError) as error:
			show_alert(str(error))


def _save_roots(data, roots, service):
	return _on_qt(_commit_roots, data, roots, service)


def _commit_roots(data, roots, service):
	if not _service_active(service):
		return None
	if load_json(_SETTINGS_NAME, default={}) != data:
		raise RuntimeError('Everything settings changed while the chooser was open; try again.')
	updated = dict(data, folders=list(roots))
	settings = Settings.load(updated)
	updated['folders'] = list(settings.folders)
	if updated == data:
		return False
	save_json(_SETTINGS_NAME, updated)
	for filesystem in tuple(EverythingFolders.instances):
		filesystem.cache.clear('')
		filesystem.notify_file_changed('')
	if settings.folders != Settings.load(data).folders:
		_get_service(settings, force=True)
		show_status_message('Everything: updating indexed folders...')
	return True


class ManageEverythingFolders(DirectoryPaneCommand):
	aliases = ('Manage Everything database folders',)

	def __call__(self):
		if self.pane.get_path() == FOLDERS_ROOT:
			self.pane.reload()
		else:
			self.pane.set_path(FOLDERS_ROOT)


def _is_folder_url(url):
	return isinstance(url, str) and url.startswith(FOLDERS_ROOT)


def _paths_for_rows(urls, folders):
	if not isinstance(urls, (list, tuple)) or any(not _is_folder_url(url) for url in urls):
		raise ValueError('Choose entries from the Everything folder list.')
	indexed = {FOLDERS_ROOT + _folder_key(folder): folder for folder in folders}
	try:
		return tuple(dict.fromkeys(indexed[url] for url in urls))
	except KeyError:
		raise ValueError('The Everything folder list changed; select the folders again.') from None


class RemoveEverythingFolders(DirectoryPaneCommand):
	def is_visible(self):
		return False

	def __call__(self, urls=None):
		service = _service
		try:
			if not _service_active(service) or self.pane.get_path() != FOLDERS_ROOT:
				return
			data, settings = _read_settings()
			paths = _paths_for_rows(self.get_chosen_files() if urls is None else urls, settings.folders)
			if not paths:
				return
			message = f'Remove {len(paths)} indexed folder(s)? Folders on disk are not deleted.\n\n' + '\n'.join(paths)
			if show_alert(message, YES | NO, NO) & YES:
				_save_roots(data, tuple(folder for folder in settings.folders if folder not in paths), service)
		except (ValueError, RuntimeError, OSError) as error:
			show_alert(str(error))


class OpenEverythingFolder(DirectoryPaneCommand):
	def is_visible(self):
		return False

	def __call__(self, url):
		try:
			_, settings = _read_settings()
			path, = _paths_for_rows((url,), settings.folders)
			if not os.path.isdir(path):
				raise ValueError('Indexed folder is unavailable: ' + path)
			self.pane.run_command('open_directory', {'url': as_url(path)})
		except (ValueError, RuntimeError, OSError) as error:
			show_alert(str(error))


class CopyEverythingFolderPaths(DirectoryPaneCommand):
	def is_visible(self):
		return False

	def __call__(self):
		try:
			_, settings = _read_settings()
			paths = _paths_for_rows(self.get_chosen_files(), settings.folders)
			if paths:
				clipboard.clear()
				clipboard.set_text('\n'.join(paths))
		except (ValueError, RuntimeError, OSError) as error:
			show_alert(str(error))


class _CollectEverythingFolders(Task):
	def __init__(self, urls, service):
		super().__init__('Adding Everything folders', size=len(urls))
		self.service = service
		self.urls = tuple(urls)
		self.paths = None
		self.skipped = 0

	def __call__(self):
		paths = []
		for index, url in enumerate(self.urls):
			self.check_canceled()
			if not _service_active(self.service):
				return
			try:
				if not isinstance(url, str) or not url.startswith('file://'):
					raise ValueError('Only local folders can be indexed.')
				paths.append(_validate_new_folder(as_human_readable(url)))
			except (ValueError, OSError):
				self.skipped += 1
			if not _service_active(self.service):
				return
			self.set_progress(index + 1)
		self.check_canceled()
		self.paths = normalize_folders(paths)


class AddEverythingFolders(DirectoryPaneCommand):
	def is_visible(self):
		return False

	def __call__(self, files=None, dest_dir=None):
		service = _service
		try:
			if not _service_active(service) or not _is_folder_url(dest_dir):
				return
			urls = self.get_chosen_files() if files is None else files
			if not isinstance(urls, (list, tuple)):
				raise ValueError('Choose local folders to add.')
			if not urls:
				return
			task = _CollectEverythingFolders(urls, service)
			submit_task(task)
			if task.paths is None or not _service_active(service):
				return
			if task.paths and _add_roots(task.paths, service) is None:
				return
			if task.skipped:
				_on_qt(lambda: show_status_message(
					f'Everything: skipped {task.skipped} unavailable or non-folder entries.', timeout_secs=6))
		except (ValueError, RuntimeError, OSError) as error:
			show_alert(str(error))


class EverythingFolderOperationUnsupported(DirectoryPaneCommand):
	def is_visible(self):
		return False

	def __call__(self):
		show_alert('These are index entries, not files. Use F8 to remove roots or F5 into this pane to add folders.')


class EverythingFoldersListener(DirectoryPaneListener):
	def on_command(self, command_name, args):
		in_manager = self.pane.get_path() == FOLDERS_ROOT
		if command_name in ('open', 'open_file', 'open_directory'):
			url = args.get('url')
			if url is None and in_manager and command_name != 'open_directory':
				url = self.pane.get_file_under_cursor()
			if _is_folder_url(url) and url != FOLDERS_ROOT:
				return 'open_everything_folder', {'url': url}
		if in_manager and command_name in ('move_to_trash', 'delete_permanently'):
			return 'remove_everything_folders', args
		if in_manager and command_name == 'copy_paths_to_clipboard':
			return 'copy_everything_folder_paths', {}
		if command_name in ('copy', 'move', 'symlink'):
			files = args.get('files')
			dest = args.get('dest_dir')
			if dest is None:
				panes = self.pane.window.get_panes()
				dest = panes[(panes.index(self.pane) + 1) % len(panes)].get_path()
			from_manager = (in_manager and files is None) or any(_is_folder_url(url) for url in (files or ()))
			if _is_folder_url(dest) and command_name == 'copy' and not from_manager:
				return 'add_everything_folders', {'files': files, 'dest_dir': dest}
			if in_manager or from_manager or _is_folder_url(dest):
				return 'everything_folder_operation_unsupported', {}
		if in_manager and command_name in ('rename', 'pack', 'unpack_archive', 'create_directory',
				'new_empty_file', 'create_and_edit_file', 'cut', 'copy_to_clipboard', 'paste_cut'):
			return 'everything_folder_operation_unsupported', {}