from core.trash import move_to_trash
from core.util import filenotfounderror
from contextlib import contextmanager
from datetime import datetime
from errno import ENOENT
from fman import PLATFORM, Task
from fman.fs import FileSystem, cached
from fman.impl.fs_cache import Cache
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import as_url, splitscheme, as_human_readable, join, basename, \
	dirname
from io import UnsupportedOperation
from os import remove, rmdir
from os.path import islink, samestat, isabs, splitdrive
from pathlib import Path
from PyQt5.QtCore import QFileSystemWatcher
from shutil import copystat
from stat import S_ISDIR, S_IWRITE, FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_REPARSE_POINT
from threading import Lock

import errno
import os

if PLATFORM == 'Windows':
	from core.fs.local.windows.drives import DrivesFileSystem, DriveName
	from core.fs.local.windows.network import NetworkFileSystem

_COPY_BUFFER_SIZE = 1024 * 1024

class _EntryAttributesCache(Cache):
	def __init__(self):
		super().__init__()
		self._scans = {}
		self._scan_lock = Lock()
		self._lookup_directory = None
	@contextmanager
	def collect_entry_attributes(self, path):
		path = path.rstrip('/')
		token = object()
		with self._scan_lock:
			directory = self._root.update_child(path)
			self._scans[path] = token
		prefix_length = len(path) + 1
		def publish(entry_path, attributes):
			with self._scan_lock:
				if self._scans.get(path) is token:
					directory.update_child(entry_path[prefix_length:]).put(
						'_entry_attributes', attributes)
		try:
			yield publish
		finally:
			with self._scan_lock:
				if self._scans.get(path) is token:
					del self._scans[path]
	def get_entry_attributes(self, path):
		directory_path, name = path.rsplit('/', 1)
		with self._scan_lock:
			cached = self._lookup_directory
			if cached is None or cached[0] != directory_path:
				cached = directory_path, self._root.get_child(directory_path)
				self._lookup_directory = cached
			return cached[1].get_child(name).get('_entry_attributes')
	def clear(self, path):
		with self._scan_lock:
			self._lookup_directory = None
			cleared = path.rstrip('/')
			for directory in tuple(self._scans):
				if not cleared or directory == cleared \
					or directory.startswith(cleared + '/') \
					or cleared.startswith(directory + '/'):
					del self._scans[directory]
			super().clear(path)

class LocalFileSystem(FileSystem):

	scheme = 'file://'

	def __init__(self):
		super().__init__()
		if PLATFORM == 'Windows':
			self.cache = _EntryAttributesCache()
		self._watcher = None
	def get_default_columns(self, path):
		return 'core.Name', 'core.Size', 'core.Modified'
	def exists(self, path):
		os_path = self._url_to_os_path(path)
		return self._isabs(os_path) and Path(os_path).exists()
	def iterdir(self, path):
		os_path = self._url_to_os_path(path)
		if not self._isabs(os_path):
			raise filenotfounderror(path)
		if not _supports_entry_attributes(path.rstrip('/')):
			return os.listdir(os_path)
		names = []
		with self.cache.collect_entry_attributes(path) as publish:
			with os.scandir(os_path) as entries:
				for entry in entries:
					names.append(entry.name)
					try:
						attributes = getattr(entry.stat(follow_symlinks=False),
							'st_file_attributes', None)
					except OSError:
						attributes = None
					if type(attributes) is not int \
						or attributes & FILE_ATTRIBUTE_REPARSE_POINT:
						attributes = None
					publish(path.rstrip('/') + '/' + entry.name, attributes)
		return names
	def _pane_hidden_state(self, path):
		if not _supports_entry_attributes(path) or len(path) <= 3:
			return None
		try:
			attributes = self.cache.get_entry_attributes(path)
		except KeyError:
			return None
		if attributes is None:
			return None
		return bool(attributes & FILE_ATTRIBUTE_HIDDEN)
	def is_dir(self, existing_path):
		# Like Python's isdir(...) except raises FileNotFoundError if the file
		# does not exist and OSError if there is another error.
		return S_ISDIR(self.stat(existing_path).st_mode)
	@cached
	def stat(self, path):
		os_path = self._url_to_os_path(path)
		if not self._isabs(os_path):
			raise filenotfounderror(path)
		try:
			return os.stat(os_path)
		except FileNotFoundError:
			return os.stat(os_path, follow_symlinks=False)
	def size_bytes(self, path):
		return self.stat(path).st_size
	def modified_datetime(self, path):
		return datetime.fromtimestamp(self.stat(path).st_mtime)
	def touch(self, path):
		os_path = Path(self._url_to_os_path(path))
		if not os_path.is_absolute():
			raise ValueError('Path must be absolute')
		try:
			os_path.touch(exist_ok=False)
		except FileExistsError:
			os_path.touch(exist_ok=True)
		else:
			self.notify_file_added(path)
	def mkdir(self, path):
		os_path = Path(self._url_to_os_path(path))
		if not os_path.is_absolute():
			raise ValueError('Path must be absolute')
		try:
			os_path.mkdir()
		except FileNotFoundError:
			raise
		except IsADirectoryError: # macOS
			raise FileExistsError(path)
		except OSError as e:
			if e.errno == ENOENT:
				raise filenotfounderror(path) from e
			elif os_path.exists():
				# On at least Windows, Path('Z:\\').mkdir() raises
				# PermissionError instead of FileExistsError. We want the latter
				# however because #makedirs(...) relies on it. So handle this
				# case generally here:
				raise FileExistsError(path) from e
			else:
				raise
		self.notify_file_added(path)
	def move(self, src_url, dst_url):
		self._check_transfer_precnds(src_url, dst_url)
		for task in self._prepare_move(src_url, dst_url):
			task()
	def prepare_move(self, src_url, dst_url):
		self._check_transfer_precnds(src_url, dst_url)
		return self._prepare_move(src_url, dst_url, measure_size=True)
	def _prepare_move(
		self, src_url, dst_url, measure_size=False, use_rename=True,
		expected_st_dev=None
	):
		if expected_st_dev is None:
			expected_st_dev = {}
		src_path, dst_path = self._check_transfer_precnds(src_url, dst_url)
		if use_rename:
			src_stat = self.stat(src_path)
			dst_par_path = splitscheme(dirname(dst_url))[1]
			try:
				dst_par_dev = expected_st_dev[dst_par_path]
			except KeyError:
				dst_par_dev = self.stat(dst_par_path).st_dev
			if src_stat.st_dev == dst_par_dev:
				yield Task(
					'Moving ' + basename(src_url), size=1,
					fn=self._rename, args=(src_url, dst_url)
				)
				return
		src_is_dir = self.is_dir(src_path)
		if src_is_dir:
			yield Task(
				'Creating ' + basename(dst_url), fn=self.mkdir, args=(dst_path,)
			)
			dst_par_path = splitscheme(dirname(dst_url))[1]
			# Expect `dst_path` to inherit .st_dev from its parent:
			try:
				expected_st_dev[dst_path] = expected_st_dev[dst_par_path]
			except KeyError:
				expected_st_dev[dst_path] = self.stat(dst_par_path).st_dev
			for name in self.iterdir(src_path):
				try:
					yield from self._prepare_move(
						join(src_url, name), join(dst_url, name), measure_size,
						use_rename, expected_st_dev
					)
				except FileNotFoundError:
					pass
			yield DeleteIfEmpty(self, src_url)
		else:
			size = self.size_bytes(src_path) if measure_size else 0
			# It's tempting to "yield copy" then "yield delete" here. But this
			# can lead to data loss: fman / the user may choose to ignore errors
			# in a particular subtask. (Eg. moving file1.txt failed but the user
			# wants to go on to move file2.txt.) If we ignored a failure in
			# "yield copy" but then execute the "yield delete", we would delete
			# a file that has not been copied!
			# To avoid this, we "copy and delete" as a single, atomic task:
			yield MoveByCopying(self, src_url, dst_url, size)
	def _rename(self, src_url, dst_url):
		src_path = splitscheme(src_url)[1]
		os_src_path = self._url_to_os_path(src_path)
		dst_path = splitscheme(dst_url)[1]
		os_dst_path = self._url_to_os_path(dst_path)
		if PLATFORM == 'Windows' and Path(os_src_path).is_dir():
			os.rename(os_src_path, os_dst_path)
		else:
			Path(os_src_path).replace(os_dst_path)
		self.notify_file_removed(src_path)
		self.notify_file_added(dst_path)
	def move_to_trash(self, path):
		for task in self.prepare_trash(path):
			task()
	def prepare_trash(self, path):
		os_path = self._url_to_os_path(path)
		if not self._isabs(os_path):
			raise filenotfounderror(path)
		yield Task(
			'Deleting ' + path.rsplit('/', 1)[-1], size=1,
			fn=self._do_trash, args=(path, os_path)
		)
	def _do_trash(self, path, os_path):
		move_to_trash(os_path)
		self.notify_file_removed(path)
	def delete(self, path):
		for task in self.prepare_delete(path):
			task()
	def prepare_delete(self, path):
		os_path = self._url_to_os_path(path)
		if not self._isabs(os_path):
			raise filenotfounderror(path)
		# is_dir(...) follows symlinks. But if `path` is a symlink, we need to
		# use remove(...) instead of rmdir(...) to avoid NotADirectoryError.
		# So check if `path` is a symlink:
		if self.is_dir(path) and not islink(os_path):
			for name in self.iterdir(path):
				try:
					yield from self.prepare_delete(path + '/' + name)
				except FileNotFoundError:
					pass
			delete_fn = rmdir
		else:
			delete_fn = remove
		yield Task(
			'Deleting ' + path.rsplit('/', 1)[-1], size=1,
			fn=self._do_delete, args=(path, delete_fn)
		)
	def _do_delete(self, path, delete_fn):
		os_path = self._url_to_os_path(path)
		try:
			delete_fn(os_path)
		except OSError as orig_exc:
			try:
				mode = self.stat(path).st_mode
			except OSError:
				mode = 0
			if not (mode & S_IWRITE):
				try:
					Path(os_path).chmod(mode | S_IWRITE)
				except OSError:
					raise orig_exc
				# Try again, now the file is writeable:
				delete_fn(os_path)
		self.notify_file_removed(path)
	def resolve(self, path):
		path = self._url_to_os_path(path)
		if not self._isabs(path):
			raise filenotfounderror(path)
		if PLATFORM == 'Windows':
			is_unc_server = path.startswith(r'\\') and not '\\' in path[2:]
			if is_unc_server:
				# Python can handle \\server\folder but not \\server. Defer to
				# the network:// file system.
				return 'network://' + path[2:]
		p = Path(path)
		try:
			path = p.resolve(strict=True)
		except FileNotFoundError:
			if not p.exists():
				raise
		except OSError as e:
			# We for instance get errno.EINVAL ("[WinError 1]") when trying to
			# resolve folders on Cryptomator drives on Windows. Ignore it:
			if e.errno != errno.EINVAL:
				raise
		return as_url(path)
	def samefile(self, path1, path2):
		s1 = self.stat(path1)
		s2 = self.stat(path2)
		if s1.st_ino and s1.st_dev:
			return samestat(s1, s2)
		# samestat(...) above simply compares .st_ino and .st_dev.
		# However, there are cases where both of these values are 0.
		# This for instance happens on Windows Google Drive File Stream folders.
		# Fall back to comparing the (resolved) path to give meaningful results:
		return self.resolve(path1) == self.resolve(path2)
	def copy(self, src_url, dst_url):
		self._check_transfer_precnds(src_url, dst_url)
		for task in self._prepare_copy(src_url, dst_url):
			task()
	def prepare_copy(self, src_url, dst_url):
		self._check_transfer_precnds(src_url, dst_url)
		return self._prepare_copy(src_url, dst_url, measure_size=True)
	def _prepare_copy(self, src_url, dst_url, measure_size=False):
		src_path, dst_path = self._check_transfer_precnds(src_url, dst_url)
		src_is_dir = self.is_dir(src_path)
		if src_is_dir:
			yield Task(
				'Creating ' + basename(dst_url), fn=self.mkdir, args=(dst_path,)
			)
			for name in self.iterdir(src_path):
				try:
					yield from self._prepare_copy(
						join(src_url, name), join(dst_url, name), measure_size
					)
				except FileNotFoundError:
					pass
		else:
			size = self.size_bytes(src_path) if measure_size else 0
			yield CopyFile(self, src_url, dst_url, size)
	@run_in_main_thread
	def watch(self, path):
		self._get_watcher().addPath(self._url_to_os_path(path))
	@run_in_main_thread
	def unwatch(self, path):
		self._get_watcher().removePath(self._url_to_os_path(path))
	def _get_watcher(self):
		# Instantiate QFileSystemWatcher as late as possible. It requires a
		# QApplication which isn't available in some tests.
		if self._watcher is None:
			if PLATFORM == 'Windows':
				# On Windows, QFileSystemWatcher keeps excessive locks on files
				# and directories. This sometimes makes it impossible for fman
				# or other apps to access them properly. One example of this are
				# USB drives that can't be ejected as long as fman is running.
				# So don't watch files on Windows for now, perhaps until we have
				# a better implementation.
				self._watcher = StubFileSystemWatcher()
			else:
				self._watcher = QFileSystemWatcher()
				self._watcher.directoryChanged.connect(self._on_file_changed)
				self._watcher.fileChanged.connect(self._on_file_changed)
		return self._watcher
	def _on_file_changed(self, file_path):
		path_forward_slashes = splitscheme(as_url(file_path))[1]
		self.notify_file_changed(path_forward_slashes)
	def _check_transfer_precnds(self, src_url, dst_url):
		src_scheme, src_path = splitscheme(src_url)
		dst_scheme, dst_path = splitscheme(dst_url)
		if src_scheme != self.scheme or dst_scheme != self.scheme:
			raise UnsupportedOperation(
				"%s only supports transferring to and from %s." %
				(self.__class__.__name__, self.scheme)
			)
		if not self._isabs(self._url_to_os_path(dst_path)):
			raise ValueError('Destination path must be absolute')
		return src_path, dst_path
	def _url_to_os_path(self, path):
		# Convert a "URL path" a/b to a path understood by the OS, eg. a\b on
		# Windows. An important effect of this function is that it turns
		# C: -> C:\. This is required for Python functions such as Path#resolve.
		return as_human_readable(self.scheme + path)
	def _isabs(self, os_path):
		# Python's isabs(...) says \\host\share is *not* absolute. But for our
		# purposes, it is. So add some extra logic to handle this case:
		return isabs(os_path) or splitdrive(os_path)[0]

def _supports_entry_attributes(path):
	return PLATFORM == 'Windows' and len(path) >= 2 \
		and path[0] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' \
		and path[1] == ':' and '\\' not in path \
		and (len(path) == 2 or path[2] == '/' and all(
			part not in ('', '.', '..') for part in path[3:].split('/')))

class CopyFile(Task):
	def __init__(self, fs, src_url, dst_url, size_bytes):
		super().__init__('Copying ' + basename(src_url), size=size_bytes)
		self._fs = fs
		self._src_url = src_url
		self._dst_url = dst_url
	def __call__(self):
		dst_urlpath = splitscheme(self._dst_url)[1]
		dst_existed = self._fs.exists(dst_urlpath)
		src = as_human_readable(self._src_url)
		dst = as_human_readable(self._dst_url)
		if islink(src):
			os.symlink(os.readlink(src), dst)
		else:
			with open(src, 'rb') as fsrc:
				with open(dst, 'wb') as fdst:
					num_written = 0
					while True:
						self.check_canceled()
						buf = fsrc.read(_COPY_BUFFER_SIZE)
						if not buf:
							break
						num_written += fdst.write(buf)
						self.set_progress(num_written)
		copystat(src, dst, follow_symlinks=False)
		if not dst_existed:
			self._fs.notify_file_added(dst_urlpath)

class MoveByCopying(Task):
	def __init__(self, fs, src_url, dst_url, size_bytes):
		super().__init__('Moving ' + basename(src_url), size=size_bytes)
		self._fs = fs
		self._src_url = src_url
		self._dst_url = dst_url
	def __call__(self, *args, **kwargs):
		self._fs.copy(self._src_url, self._dst_url)
		self._fs.delete(splitscheme(self._src_url)[1])

class DeleteIfEmpty(Task):
	def __init__(self, fs, dir_url):
		super().__init__('Deleting ' + basename(dir_url), size=1)
		self._fs = fs
		self._dir_url = dir_url
	def __call__(self, *args, **kwargs):
		try:
			rmdir(as_human_readable(self._dir_url))
		except FileNotFoundError:
			pass
		except OSError as e:
			if e.errno != errno.ENOTEMPTY:
				raise
		else:
			self._fs.notify_file_removed(splitscheme(self._dir_url)[1])

class StubFileSystemWatcher:
	def addPath(self, path):
		pass
	def removePath(self, path):
		pass