from core.trash import move_to_trash
from core.util import filenotfounderror
from datetime import datetime
from errno import ENOENT
from fman import PLATFORM, Task
from fman.fs import FileSystem, cached
from fman.impl.util.qt.thread import run_in_main_thread
from fman.url import as_url, splitscheme, as_human_readable, join, basename, \
	dirname
from io import UnsupportedOperation
from os import remove, rmdir
from os.path import islink, samestat, isabs, splitdrive
from pathlib import Path
from PyQt5.QtCore import QFileSystemWatcher
from shutil import copystat, SameFileError
from stat import S_ISDIR, S_ISREG, S_IWRITE
from tempfile import mkstemp, mkdtemp

import errno
import os

if PLATFORM == 'Windows':
	from core.fs.local.windows.drives import DrivesFileSystem, DriveName
	from core.fs.local.windows.network import NetworkFileSystem

_COPY_BUFFER_SIZE = 1024 * 1024

class LocalFileSystem(FileSystem):

	scheme = 'file://'

	def __init__(self):
		super().__init__()
		self._watcher = None
	def get_default_columns(self, path):
		return 'core.Name', 'core.Size', 'core.Modified'
	def scan(self, path, check_canceled):
		os_path = self._url_to_os_path(path)
		if not self._isabs(os_path):
			raise filenotfounderror(path)
		if PLATFORM == 'Windows':
			from core.fs.local.windows.listing import scan
			listing = scan(self.scheme + path, os_path, check_canceled)
			if listing is not None:
				return listing
		return self._scan_entries(path, os_path, check_canceled)
	def _scan_entries(self, path, os_path, check_canceled):
		from fman.listing import Listing
		names, directories, sizes, modified, attributes = ([] for field in range(5))
		with os.scandir(os_path) as entries:
			for entry in entries:
				check_canceled()
				try:
					own = entry.stat(follow_symlinks=False)
					metadata = own
					if entry.is_symlink() or getattr(own, 'st_reparse_tag', 0) == 0xa0000003:
						try:
							metadata = os.stat(entry.path)
						except OSError:
							pass
				except FileNotFoundError:
					continue
				names.append(entry.name)
				directories.append(S_ISDIR(metadata.st_mode))
				sizes.append(metadata.st_size)
				modified.append(metadata.st_mtime_ns)
				attributes.append(getattr(own, 'st_file_attributes', 2 if entry.name.startswith('.') else 0))
		check_canceled()
		return Listing.create(self.scheme + path, names, is_dir=directories,
			sizes=sizes, mtimes_ns=modified, attributes=attributes)
	def exists(self, path):
		os_path = self._url_to_os_path(path)
		return self._isabs(os_path) and Path(os_path).exists()
	def iterdir(self, path):
		os_path = self._url_to_os_path(path)
		if not self._isabs(os_path):
			raise filenotfounderror(path)
		return os.listdir(os_path)
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
		src_os_path = self._url_to_os_path(src_path)
		src_is_link = islink(src_os_path) or os.path.isjunction(src_os_path)
		if use_rename:
			src_stat = os.lstat(src_os_path) if src_is_link else self.stat(src_path)
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
		if src_is_link:
			raise UnsupportedOperation('Cannot move links by copying; source retained.')
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
		if os.path.isjunction(os_path):
			delete_fn = rmdir
		elif islink(os_path):
			delete_fn = remove
		elif self.is_dir(path):
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
			if islink(os_path) or os.path.isjunction(os_path):
				raise
			try:
				mode = self.stat(path).st_mode
			except OSError:
				raise orig_exc
			if not (mode & S_IWRITE):
				try:
					Path(os_path).chmod(mode | S_IWRITE)
				except OSError:
					raise orig_exc
				# Try again, now the file is writeable:
				delete_fn(os_path)
			else:
				raise
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
	def watch(self, path):
		if PLATFORM != 'Windows':
			self._watch(path)
	def unwatch(self, path):
		if PLATFORM != 'Windows':
			self._unwatch(path)
	@run_in_main_thread
	def _watch(self, path):
		self._get_watcher().addPath(self._url_to_os_path(path))
	@run_in_main_thread
	def _unwatch(self, path):
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

class CopyFile(Task):
	def __init__(self, fs, src_url, dst_url, size_bytes):
		super().__init__('Copying ' + basename(src_url), size=size_bytes)
		self._fs = fs
		self._src_url = src_url
		self._dst_url = dst_url
	def __call__(self):
		dst_urlpath = splitscheme(self._dst_url)[1]
		src = as_human_readable(self._src_url)
		dst = as_human_readable(self._dst_url)
		try:
			destination = os.lstat(dst)
		except FileNotFoundError:
			destination = None
		if islink(src):
			if destination is not None:
				raise UnsupportedOperation('Symlink overwrite refused; destination retained')
			os.symlink(os.readlink(src), dst)
			copystat(src, dst, follow_symlinks=False)
		else:
			with open(src, 'rb') as fsrc:
				source = os.fstat(fsrc.fileno())
				if destination is not None:
					if not S_ISREG(destination.st_mode):
						raise UnsupportedOperation('Cannot safely overwrite a linked or non-regular destination')
					identified = source.st_ino and source.st_dev and destination.st_ino and destination.st_dev
					same_file = samestat(source, destination) if identified else \
						self._fs.resolve(splitscheme(self._src_url)[1]) == self._fs.resolve(dst_urlpath)
					if same_file:
						raise SameFileError(src, dst, 'Source and destination are the same file')
					if destination.st_nlink > 1:
						raise UnsupportedOperation('Cannot safely overwrite a hardlinked destination')
					if not destination.st_mode & S_IWRITE:
						raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), dst)
				if not S_ISREG(source.st_mode):
					raise UnsupportedOperation('Only regular files can be copied')
				descriptor, temporary = mkstemp(dir=self._staging_directory(dst), prefix='.fc-')
				try:
					with os.fdopen(descriptor, 'wb') as fdst:
						if destination is not None and PLATFORM == 'Windows':
							import win32security
							security = win32security.GetFileSecurity(dst, win32security.DACL_SECURITY_INFORMATION)
							win32security.SetNamedSecurityInfo(temporary, win32security.SE_FILE_OBJECT,
								win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
								None, None, security.GetSecurityDescriptorDacl(), None)
						self._copy_bytes(fsrc, fdst)
					copystat(src, temporary, follow_symlinks=False)
					copied_mode = source.st_mode
					restore_mode = destination is not None and PLATFORM == 'Windows' and not copied_mode & S_IWRITE
					if restore_mode:
						os.chmod(temporary, copied_mode | S_IWRITE)
					self.check_canceled()
					self._publish(temporary, dst, destination)
					if restore_mode:
						try:
							os.chmod(dst, copied_mode)
						except OSError as error:
							error.strerror = 'Copy published, but restoring file mode failed: ' + (error.strerror or str(error))
							self._fs.notify_file_changed(dst_urlpath)
							raise
				finally:
					try:
						os.unlink(temporary)
					except PermissionError:
						try:
							os.chmod(temporary, S_IWRITE)
							os.unlink(temporary)
						except OSError:
							pass
					except OSError:
						pass
		if destination is None:
			self._fs.notify_file_added(dst_urlpath)
		else:
			self._fs.notify_file_changed(dst_urlpath)
	@staticmethod
	def _staging_directory(destination):
		directory = os.path.dirname(destination)
		if PLATFORM == 'Windows':
			directory = os.path.abspath(directory)
			if not directory.startswith('\\\\?\\'):
				directory = '\\\\?\\UNC\\' + directory[2:] if directory.startswith('\\\\') else '\\\\?\\' + directory
		return directory
	def _copy_bytes(self, fsrc, fdst):
		num_written = 0
		while True:
			self.check_canceled()
			buffer = fsrc.read(_COPY_BUFFER_SIZE)
			if not buffer:
				break
			num_written += fdst.write(buffer)
			self.set_progress(num_written)
	def _publish(self, temporary, destination_path, destination):
		if destination is None:
			if PLATFORM == 'Windows':
				os.rename(temporary, destination_path)
			else:
				os.link(temporary, destination_path)
			return
		current = os.lstat(destination_path)
		fields = ('st_ino', 'st_dev', 'st_size', 'st_mtime_ns')
		if any(getattr(current, name) != getattr(destination, name) for name in fields) or \
			not S_ISREG(current.st_mode) or current.st_nlink > 1 or not current.st_mode & S_IWRITE:
			raise OSError('Destination changed while copying; replacement refused')
		if PLATFORM != 'Windows':
			raise UnsupportedOperation('Metadata-preserving overwrite is not supported on this platform')
		import ctypes
		from ctypes import wintypes
		replace = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
		replace.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
			wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID)
		replace.restype = wintypes.BOOL
		backup_directory = mkdtemp(dir=self._staging_directory(destination_path), prefix='.fb-')
		backup = os.path.join(backup_directory, 'o')
		try:
			if not replace(destination_path, temporary, backup, 0, None, None):
				error = ctypes.WinError(ctypes.get_last_error())
				if os.path.lexists(backup):
					try:
						os.rename(backup, destination_path)
					except OSError:
						error.strerror += ' Previous destination retained at: ' + backup
					raise error
				raise error
			try:
				os.unlink(backup)
			except OSError:
				pass
		finally:
			try:
				os.rmdir(backup_directory)
			except OSError:
				pass

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