from collections import namedtuple, deque
from codecs import getincrementaldecoder
from contextlib import contextmanager
from core.os_ import is_arch, is_mac
from core.fileoperations import ArchiveUpdateError
from core.util import filenotfounderror
from datetime import datetime
from errno import EEXIST, EIO
from fman import PLATFORM, load_json, Task
from fman.fs import FileSystem
from fman.url import as_url, splitscheme, as_human_readable, basename
from hashlib import sha256
from io import UnsupportedOperation, FileIO, BufferedReader, TextIOWrapper
from os.path import join, dirname
from pathlib import PurePosixPath, Path
from queue import Queue, Empty, Full
from subprocess import Popen, PIPE, DEVNULL, CalledProcessError
from tempfile import TemporaryDirectory
from threading import Event, Thread

import fman.fs
import os
import os.path
import re
import signal
import sys

# Prevent 'Rename' below from accidentally overwriting core.Rename:
__all__ = ['ZipFileSystem', 'SevenZipFileSystem', 'TarFileSystem']

if is_arch():
	_7ZIP_BINARY = '/usr/bin/7za'
elif is_mac() and getattr(sys, 'frozen', False):
	_7ZIP_BINARY = join(dirname(sys.executable), '7za')
else:
	_7ZIP_BINARY = join(
		dirname(dirname(dirname(__file__))), 'bin', PLATFORM.lower(), '7za'
	)
	if PLATFORM == 'Windows':
		_7ZIP_BINARY += '.exe'

class _7ZipFileSystem(FileSystem):
	def __init__(self, fs=fman.fs, suffixes=None):
		if suffixes is None:
			suffixes = self._load_suffixes_from_json()
		super().__init__()
		self._fs = fs
		self._suffixes = suffixes
	def _load_suffixes_from_json(self):
		settings = load_json('Core Settings.json', default={})
		archive_handlers = settings.get('archive_handlers', {})
		return set(
			suffix for suffix, scheme in archive_handlers.items()
			if scheme == self.scheme
		)
	def get_default_columns(self, path):
		return 'core.Name', 'core.Size', 'core.Modified'
	def resolve(self, path):
		for suffix in self._suffixes:
			if suffix in path.lower():
				if not self.exists(path):
					raise FileNotFoundError(self.scheme + path)
				return super().resolve(path)
		return self._fs.resolve(as_url(path))
	def iterdir(self, path):
		path_in_zip = self._split(path)[1]
		already_yielded = set()
		for file_info in self._iter_infos(path):
			candidate = file_info.path
			while candidate:
				candidate_path = PurePosixPath(candidate)
				parent = str(candidate_path.parent)
				if parent == '.':
					parent = ''
				if parent == path_in_zip:
					name = candidate_path.name
					if name not in already_yielded:
						yield name
						already_yielded.add(name)
				candidate = parent
	def scan(self, path, check_canceled):
		from contextlib import closing
		from fman.listing import Listing
		path_in_zip = self._split(path)[1].rstrip('/')
		prefix = path_in_zip + '/' if path_in_zip else ''
		entries = {}
		with closing(self._iter_infos(path, cache=False)) as infos:
			for info in infos:
				check_canceled()
				if not info.path.startswith(prefix):
					continue
				relative = info.path[len(prefix):].rstrip('/')
				if not relative:
					continue
				name, separator, remainder = relative.partition('/')
				if separator:
					entries.setdefault(name, (True, None, None))
				else:
					try:
						modified = None if info.mtime is None else round(info.mtime.timestamp() * 1_000_000_000)
					except (OSError, OverflowError, ValueError):
						modified = None
					entries[name] = info.is_dir, info.size_bytes, modified
		check_canceled()
		return Listing.create(self.scheme + path, entries,
			is_dir=(value[0] for value in entries.values()),
			sizes=(value[1] for value in entries.values()),
			mtimes_ns=(value[2] for value in entries.values()))
	def is_dir(self, existing_path):
		zip_path, path_in_zip = self._split(existing_path)
		if not path_in_zip:
			if Path(zip_path).exists():
				return True
			raise filenotfounderror(existing_path)
		result = self._query_info_attr(existing_path, 'is_dir', True)
		if result is not None:
			return result
		raise filenotfounderror(existing_path)
	def exists(self, path):
		try:
			zip_path, path_in_zip = self._split(path)
		except FileNotFoundError:
			return False
		if not path_in_zip:
			return Path(zip_path).exists()
		try:
			next(iter(self._iter_infos(path)))
		except (StopIteration, FileNotFoundError):
			return False
		return True
	def copy(self, src_url, dst_url):
		for task in self.prepare_copy(src_url, dst_url):
			task()
	def prepare_copy(self, src_url, dst_url):
		src_scheme, src_path = splitscheme(src_url)
		dst_scheme, dst_path = splitscheme(dst_url)
		if src_scheme == self.scheme and dst_scheme == 'file://':
			zip_path, path_in_zip = self._split(src_path)
			dst_ospath = as_human_readable(dst_url)
			return [Extract(self._fs, zip_path, path_in_zip, dst_ospath)]
		elif src_scheme == 'file://' and dst_scheme == self.scheme:
			zip_path, path_in_zip = self._split(dst_path)
			src_ospath = as_human_readable(src_url)
			return [
				AddToArchive(self, self._fs, src_ospath, zip_path, path_in_zip)
			]
		elif src_scheme == dst_scheme:
			# Guaranteed by fman's file system implementation:
			assert src_scheme == self.scheme
			src_zip_path, path_in_src_zip = self._split(src_path)
			dst_zip_path, path_in_dst_zip = self._split(dst_path)
			return [CopyBetweenArchives(
				self, self._fs, src_zip_path, path_in_src_zip, dst_zip_path,
				path_in_dst_zip
			)]
		else:
			raise UnsupportedOperation()
	def move(self, src_url, dst_url):
		for task in self.prepare_move(src_url, dst_url):
			task()
	def prepare_move(self, src_url, dst_url):
		src_scheme, src_path = splitscheme(src_url)
		dst_scheme, dst_path = splitscheme(dst_url)
		if src_scheme == dst_scheme:
			# Guaranteed by fman's file system implementation:
			assert src_scheme == self.scheme
			src_zip, src_pth_in_zip = self._split(src_path)
			dst_zip, dst_pth_in_zip = self._split(dst_path)
			if src_zip == dst_zip:
				return [Rename(self, src_zip, src_pth_in_zip, dst_pth_in_zip)]
			else:
				return [MoveBetweenArchives(self, src_url, dst_url)]
		elif src_scheme == self.scheme and dst_scheme == 'file://':
			return [MoveOutOfArchive(self, src_url, dst_url)]
		else:
			result = list(self.prepare_copy(src_url, dst_url))
			title = 'Cleaning up ' + basename(src_url)
			result.append(Task(title, fn=self._fs.delete, args=(src_url,)))
			return result
	def mkdir(self, path):
		if self.exists(path):
			raise FileExistsError(path)
		zip_path, path_in_zip = self._split(path)
		if not path_in_zip:
			self._create_empty_archive(zip_path)
		elif not self.exists(str(PurePosixPath(path).parent)):
			raise filenotfounderror(path)
		else:
			with TemporaryDirectory() as tmp_dir:
				self.copy(as_url(tmp_dir), as_url(path, self.scheme))
	def _create_empty_archive(self, zip_path):
		# Run 7-Zip in an empty temporary directory. Create this directory next
		# to the Zip file to ensure Path.rename(...) works because it's on the
		# same file system.
		with _create_temp_dir_next_to(zip_path) as tmp_dir:
			name = PurePosixPath(zip_path).name
			_run_7zip(['a', name], cwd=tmp_dir)
			Path(tmp_dir, name).rename(zip_path)
		self.notify_file_added(zip_path)
	def delete(self, path):
		if not self.exists(path):
			raise filenotfounderror(path)
		zip_path, path_in_zip = self._split(path)
		with self._preserve_empty_parent(zip_path, path_in_zip):
			_run_7zip(['d', zip_path, path_in_zip])
		self.notify_file_removed(path)
	def prepare_delete(self, path):
		return [Task(
			'Deleting ' + path.rsplit('/', 1)[-1],
			fn=self.delete, args=(path,), size=1
		)]
	def size_bytes(self, path):
		return self._query_info_attr(path, 'size_bytes', None)
	def modified_datetime(self, path):
		return self._query_info_attr(path, 'mtime', None)
	def _query_info_attr(self, path, attr, folder_default):
		def compute_value():
			path_in_zip = self._split(path)[1]
			if not path_in_zip:
				return folder_default
			for info in self._iter_infos(path):
				if info.path == path_in_zip:
					return getattr(info, attr)
				return folder_default
		return self.cache.query(path, attr, compute_value)
	def _preserve_empty_parent(self, zip_path, path_in_zip, restore=None):
		# 7-Zip deletes empty directories that remain after an operation. For
		# instance, when deleting the last file from a directory, or when moving
		# it out of the directory. We don't want this to happen. The present
		# method allows us to preserve the parent directory, even if empty:
		parent = str(PurePosixPath(path_in_zip).parent)
		parent_fullpath = zip_path + '/' + parent
		class CM:
			def __enter__(cm):
				if parent != '.':
					cm._parent_wasdir_before = self.is_dir(parent_fullpath)
				else:
					cm._parent_wasdir_before = False
			def __exit__(cm, exc_type, exc_val, exc_tb):
				if not exc_val:
					if cm._parent_wasdir_before:
						if not self.exists(parent_fullpath):
							if restore is None:
								self.makedirs(parent_fullpath)
							else:
								restore(parent)
		return CM()
	def _split(self, path):
		for suffix in self._suffixes:
			try:
				split_point = path.lower().index(suffix) + len(suffix)
			except ValueError as suffix_not_found:
				continue
			else:
				return path[:split_point], path[split_point:].lstrip('/')
		raise filenotfounderror(self.scheme + path) from None
	def _iter_infos(self, path, cache=True):
		zip_path, path_in_zip = self._split(path)
		self._raise_filenotfounderror_if_not_exists(zip_path)
		args = ['l', '-ba', '-slt', zip_path]
		if path_in_zip:
			args.append(path_in_zip)
		with _7zip(args, kill=True) as process:
			stdout_lines = process.stdout_lines
			file_info = self._read_file_info(stdout_lines)
			if path_in_zip and not file_info:
				raise filenotfounderror(self.scheme + path)
			while file_info:
				if cache:
					self._put_in_cache(zip_path, file_info)
				yield file_info
				file_info = self._read_file_info(stdout_lines)
	def _raise_filenotfounderror_if_not_exists(self, zip_path):
		os.stat(zip_path)
	def _read_file_info(self, stdout):
		path = size = mtime = None
		is_dir = False
		for line in stdout:
			line = line.rstrip('\r\n')
			if not line:
				break
			if line.startswith('Path = '):
				path = line[len('Path = '):].replace(os.sep, '/')
			elif line.startswith('Folder = '):
				folder = line[len('Folder = '):]
				is_dir = is_dir or folder == '+'
			elif line.startswith('Size = '):
				size_str = line[len('Size = '):]
				if size_str:
					size = int(size_str)
			elif line.startswith('Modified = '):
				mtime_str = line[len('Modified = '):]
				if mtime_str:
					mtime = datetime.fromisoformat(mtime_str)
			elif line.startswith('Attributes = '):
				attributes = line[len('Attributes = '):]
				is_dir = is_dir or attributes.startswith('D')
		if path:
			return _FileInfo(path, is_dir, size, mtime)
	def _put_in_cache(self, zip_path, file_info):
		for field in file_info._fields:
			if field != 'path':
				self.cache.put(
					zip_path + '/' + file_info.path, field,
					getattr(file_info, field)
				)

class _7zipTaskWithProgress(Task):
	def run_7zip_with_progress(
		self, args, pty=True, allow_warning=True, cancellable=True,
		progress_limit=100, check_before=True, **kwargs
	):
		if check_before:
			self.check_canceled()
		def check():
			if cancellable:
				self.check_canceled()
			elif self._dialog.was_canceled():
				self.set_text('Canceling after archive update finishes...')
		with _7zip(args, pty=pty, allow_warning=allow_warning, **kwargs) as process:
			lines = process.stdout_lines if pty else process.progress_records(check)
			try:
				for line in lines:
					try:
						check()
					except Task.Canceled:
						process.kill()
						raise
					match = re.match(r'\s*(\d{1,3})%(?:\s|$)', line)
					if match:
						percent = min(progress_limit, int(match.group(1)))
						if percent > self.get_progress():
							self.set_progress(percent)
			finally:
				lines.close()

class AddToArchive(_7zipTaskWithProgress):
	def __init__(self, zip_fs, fman_fs, src_ospath, zip_path, path_in_zip, for_move=False):
		if not path_in_zip:
			raise ValueError(
				'Must specify the destination path inside the archive'
			)
		super().__init__('Packing ' + os.path.basename(src_ospath), size=200 if for_move else 100)
		self._for_move = for_move
		self._zip_fs = zip_fs
		self._fman_fs = fman_fs
		self._src_ospath = src_ospath
		self._zip_path = zip_path
		self._path_in_zip = path_in_zip
	def __call__(self):
		expected_digest = _tree_digest(Path(self._src_ospath), self.check_canceled) \
			if self._for_move else None
		temporary = _transfer_temp_directory(self) if self._for_move else TemporaryDirectory()
		with temporary as tmp_dir:
			dest = Path(tmp_dir, *self._path_in_zip.split('/'))
			dest.parent.mkdir(parents=True, exist_ok=True)
			src = Path(self._src_ospath)
			try:
				dest.symlink_to(src, src.is_dir())
			except OSError:
				# This for instance happens on non-NTFS drives on Windows.
				# We need to incur the cost of physically copying the file:
				self._fman_fs.copy(as_url(src), as_url(dest))
			args = ['a', self._zip_path, self._path_in_zip]
			if self._for_move:
				args[-1] = '-i!' + self._path_in_zip
			if PLATFORM != 'Windows':
				args.insert(1, '-l')
			if self._for_move:
				try:
					self.run_7zip_with_progress(
						args + ['-bsp1', '-bse1', '-spd'], cwd=tmp_dir,
						pty=False, allow_warning=False, cancellable=False,
						progress_limit=99
					)
				except _7zipError as error:
					raise OSError(EIO, str(error)) from error
				self.check_canceled()
				self.set_progress(100)
				self.set_text('Verifying ' + os.path.basename(self._zip_path))
				with _transfer_temp_directory(self) as verification_dir:
					verification = Extract(
						self._fman_fs, self._zip_path, self._path_in_zip,
						str(Path(verification_dir, 'output')), expected_digest=expected_digest
					)
					self.run(verification)
			else:
				self.run_7zip_with_progress(args, cwd=tmp_dir)
			dest_path = self._zip_path + '/' + self._path_in_zip
			self._zip_fs.notify_file_added(dest_path)

class Extract(_7zipTaskWithProgress):
	def __init__(self, fman_fs, zip_path, path_in_zip, dst_ospath,
		verify_output=False, expected_digest=None):
		super().__init__('Extracting ' + _basename(zip_path, path_in_zip), size=100)
		self._fman_fs = fman_fs
		self._zip_path = zip_path
		self._path_in_zip = path_in_zip
		self._dst_ospath = dst_ospath
		self._verify_output = verify_output
		self._expected_digest = expected_digest
		self._new_directory = False
	def require_new_directory(self, archive_path, destination=None):
		if self._path_in_zip or not os.path.samefile(archive_path, self._zip_path):
			raise OSError(EIO, 'Cannot safely identify the selected archive root')
		if destination is not None and os.path.normcase(os.path.normpath(destination)) != \
			os.path.normcase(os.path.normpath(self._dst_ospath)):
			raise OSError(EIO, 'Archive handler selected a different destination')
		self._new_directory = True
	def __call__(self):
		self.check_canceled()
		if self._new_directory:
			return self._unpack_new_directory()
		if Path(self._dst_ospath).exists() and os.path.samefile(self._zip_path, self._dst_ospath):
			raise OSError(EIO, 'Cannot extract over the source archive')
		# Create temp dir next to dst_path to ensure Path.replace(...) works
		# because it's on the same file system.
		tmp_dir = _create_temp_dir_next_to(self._dst_ospath)
		try:
			args = ['x', '-bsp1', '-bse1', '-y', '-spd', self._zip_path,
				'-o' + tmp_dir.name]
			if self._path_in_zip:
				args.append('-i!' + self._path_in_zip)
			try:
				self.run_7zip_with_progress(
					args, pty=False, allow_warning=False, progress_limit=99
				)
			except _7zipError as error:
				raise OSError(EIO, str(error)) from error
			output = Path(tmp_dir.name, self._path_in_zip)
			if not output.resolve().is_relative_to(Path(tmp_dir.name).resolve()):
				raise OSError(EIO, 'Archive output escapes its temporary directory')
			if not output.exists():
				raise filenotfounderror(str(output))
			digest = None
			if self._verify_output or self._expected_digest is not None:
				digest = _tree_digest(output, self.check_canceled)
				if self._expected_digest is not None and digest != self._expected_digest:
					raise OSError(EIO, 'Destination archive contents failed verification')
			self.check_canceled()
			# Use fman.fs.move(...) so fman's file:// caches are notified of the
			# new file:
			self._fman_fs.move(
				join(as_url(tmp_dir.name), self._path_in_zip),
				as_url(self._dst_ospath)
			)
			if self._verify_output:
				self.set_text('Verifying ' + os.path.basename(self._dst_ospath))
				if _tree_digest(Path(self._dst_ospath), self.check_canceled) != digest:
					raise OSError(EIO, 'Extracted output failed verification; source retained')
			self.set_progress(self.get_size())
		finally:
			_cleanup_extraction(self, tmp_dir)
	def _unpack_new_directory(self):
		if PLATFORM != 'Windows':
			raise UnsupportedOperation('Safe Unpack publication requires Windows')
		if os.path.lexists(self._dst_ospath):
			raise FileExistsError(EEXIST, 'Destination already exists', None, None, self._dst_ospath)
		temporary = _create_temp_dir_next_to(self._dst_ospath)
		try:
			before = os.stat(self._zip_path)
			self.set_text('Checking archive entries')
			with _7zip(['l', '-slt', '-ba', '-bse1', self._zip_path], allow_warning=False) as process:
				records = process.progress_records(self.check_canceled, truncate=False)
				try:
					_unpack_manifest(records, self.check_canceled)
				finally:
					records.close()
			output = Path(temporary.name, 'contents')
			output.mkdir()
			self.set_text('Extracting ' + os.path.basename(self._zip_path))
			self.run_7zip_with_progress(
				['x', '-bsp1', '-bse1', '-y', '-spd', self._zip_path, '-o' + str(output)],
				pty=False, allow_warning=False, progress_limit=99
			)
			after = os.stat(self._zip_path)
			if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
				raise OSError(EIO, 'Archive changed while being read')
			if output.is_symlink() or output.is_junction() or not output.is_dir():
				raise OSError(EIO, 'Archive output is not an ordinary directory')
			self.check_canceled()
			os.rename(output, self._dst_ospath)
			fman.fs.notify_file_added(as_url(self._dst_ospath))
			self.set_progress(self.get_size())
		except _7zipError as error:
			raise OSError(EIO, str(error)) from error
		finally:
			_cleanup_extraction(self, temporary)

def _unpack_manifest(records, check):
	manifest = {}
	explicit = set()
	fields = {}
	def finish():
		if not fields:
			return
		path = fields['Path'].replace('\\', '/')
		parts = path.split('/')
		for part in parts:
			if not part or part in ('.', '..') or part.endswith(('.', ' ')) or \
				any(ord(character) < 32 or character in '<>:"|?*' for character in part) or \
				re.fullmatch(r'(?i:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])', part.split('.')[0]):
				raise OSError(EIO, 'Archive entry name may be changed by extraction: ' + path)
		attributes = fields.get('Attributes', '')
		mode = fields.get('Mode', '')
		is_directory = fields.get('Folder') == '+' or attributes.startswith('D') or mode.startswith('d')
		key = path.casefold()
		if key in explicit:
			raise OSError(EIO, 'Colliding archive entries: ' + path)
		explicit.add(key)
		for count in range(1, len(parts) + 1):
			name = '/'.join(parts[:count])
			entry = (name, count < len(parts) or is_directory)
			previous = manifest.setdefault(name.casefold(), entry)
			if previous != entry:
				raise OSError(EIO, 'Colliding archive entries: ' + path)
	for record in records:
		check()
		if ' = ' not in record:
			raise OSError(EIO, 'Ambiguous archive listing')
		name, value = record.split(' = ', 1)
		if name == 'Path':
			finish()
			fields = {}
		elif not fields or name in fields:
			raise OSError(EIO, 'Ambiguous archive listing')
		if name in ('Path', 'Folder', 'Attributes', 'Mode'):
			fields[name] = value
	finish()
	return manifest

def _cleanup_extraction(task, temporary):
	primary_error = sys.exc_info()[1]
	for attempt in range(3):
		try:
			temporary.cleanup()
			return
		except FileNotFoundError:
			return
		except OSError as error:
			if attempt < 2:
				Event().wait(.05)
				continue
			message = 'Could not remove temporary output: ' + temporary.name
			if primary_error is None:
				raise OSError(error.errno, message) from error
			primary_error.add_note(message)
			try:
				task.show_alert(message)
			except Exception:
				pass

@contextmanager
def _transfer_temp_directory(task):
	temporary = TemporaryDirectory()
	try:
		yield temporary.name
	finally:
		_cleanup_extraction(task, temporary)

def _tree_digest(path, check):
	check()
	if path.is_symlink() or path.is_junction():
		raise OSError(EIO, 'Cannot verify archive transfer containing links: ' + str(path))
	digest = sha256()
	if path.is_dir():
		digest.update(b'directory\0')
		for child in sorted(path.iterdir(), key=lambda entry: entry.name):
			digest.update(child.name.encode('utf-8', 'surrogatepass') + b'\0')
			digest.update(_tree_digest(child, check))
	else:
		digest.update(b'file\0')
		with path.open('rb') as stream:
			while True:
				check()
				chunk = stream.read(1024 * 1024)
				if not chunk:
					break
				digest.update(chunk)
	return digest.digest()

def _archive_state(path, check):
	before = Path(path).stat()
	digest = _tree_digest(Path(path), check)
	after = Path(path).stat()
	identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
	if identity(before) != identity(after):
		raise OSError(EIO, 'Archive changed during transfer; source retained')
	return identity(after), digest

class UpdateArchive(_7zipTaskWithProgress):
	def __init__(self, archive_fs, source_url, expected_state):
		super().__init__('Updating ' + basename(source_url), size=100)
		self._fs = archive_fs
		self._source_url = source_url
		self._expected_state = expected_state
	def __call__(self):
		zip_path, path_in_zip = self._fs._split(splitscheme(self._source_url)[1])
		if not path_in_zip:
			raise UnsupportedOperation('Moving the archive root is not supported; copy its contents')
		if _archive_state(zip_path, self.check_canceled) != self._expected_state:
			raise OSError(EIO, 'Source archive changed during transfer; source retained')
		self.check_canceled()
		try:
			with self._fs._preserve_empty_parent(zip_path, path_in_zip,
				restore=lambda parent: self._restore_parent(zip_path, parent)):
				self.run_7zip_with_progress(
					['d', '-bsp1', '-bse1', '-spd', zip_path, '-i!' + path_in_zip],
					pty=False, allow_warning=False, cancellable=False, progress_limit=99
				)
			self._fs.notify_file_removed(splitscheme(self._source_url)[1])
		except (OSError, CalledProcessError) as error:
			raise ArchiveUpdateError(EIO,
				'Source removal failed; copied output was retained. Inspect ' + zip_path) from error
		self.set_progress(100)
		self.check_canceled()
	def _restore_parent(self, zip_path, parent):
		with _transfer_temp_directory(self) as directory:
			Path(directory, parent).mkdir(parents=True)
			self.run_7zip_with_progress(
				['a', '-bsp1', '-bse1', '-spd', zip_path, '-i!' + parent],
				cwd=directory, pty=False, allow_warning=False, cancellable=False,
				progress_limit=99, check_before=False
			)
		self._fs.notify_file_added(zip_path + '/' + parent)

class MoveOutOfArchive(Task):
	def __init__(self, archive_fs, source_url, destination_url):
		super().__init__('Moving ' + basename(source_url), size=200)
		self._fs = archive_fs
		self._source_url = source_url
		self._destination_url = destination_url
	def __call__(self):
		zip_path, path_in_zip = self._fs._split(splitscheme(self._source_url)[1])
		if not path_in_zip:
			raise UnsupportedOperation('Moving the archive root is not supported; copy its contents')
		state = _archive_state(zip_path, self.check_canceled)
		self.run(Extract(self._fs._fs, zip_path, path_in_zip,
			as_human_readable(self._destination_url), verify_output=True))
		self.check_canceled()
		self.run(UpdateArchive(self._fs, self._source_url, state))

class CopyBetweenArchives(Task):
	def __init__(
		self, zip_fs, fman_fs, src_zip_path, path_in_src_zip, dst_zip_path,
		path_in_dst_zip
	):
		title = 'Copying ' + _basename(src_zip_path, path_in_src_zip)
		super().__init__(title, size=200)
		self._zip_fs = zip_fs
		self._fman_fs = fman_fs
		self._src_zip_path = src_zip_path
		self._path_in_src_zip = path_in_src_zip
		self._dst_zip_path = dst_zip_path
		self._path_in_dst_zip = path_in_dst_zip
	def __call__(self):
		with _transfer_temp_directory(self) as tmp_dir:
			src_basename = self._path_in_src_zip.rsplit('/', 1)[-1]
			# Give temp dir the same name as the source file; This leads to the
			# correct name being displayed in the progress dialog:
			tmp_dst_ospath = os.path.join(tmp_dir, src_basename)
			self.run(Extract(
				self._fman_fs, self._src_zip_path, self._path_in_src_zip,
				tmp_dst_ospath
			))
			self.run(AddToArchive(
				self._zip_fs, self._fman_fs, tmp_dst_ospath, self._dst_zip_path,
				self._path_in_dst_zip
			))

class Rename(_7zipTaskWithProgress):
	def __init__(self, zip_fs, zip_path, src_in_zip, dst_in_zip):
		super().__init__('Renaming ' + src_in_zip.rsplit('/', 1)[-1], size=100)
		self._fs = zip_fs
		self._zip_path = zip_path
		self._src_in_zip = src_in_zip
		self._dst_in_zip = dst_in_zip
	def __call__(self, *args, **kwargs):
		with self._fs._preserve_empty_parent(self._zip_path, self._src_in_zip):
			self.run_7zip_with_progress(
				['rn', self._zip_path, self._src_in_zip, self._dst_in_zip]
			)
		self._fs.notify_file_removed(self._zip_path + '/' + self._src_in_zip)
		self._fs.notify_file_added(self._zip_path + '/' + self._dst_in_zip)

class MoveBetweenArchives(Task):
	def __init__(self, fs, src_url, dst_url):
		super().__init__('Moving ' + basename(src_url), size=400)
		self._fs = fs
		self._src_url = src_url
		self._dst_url = dst_url
	def __call__(self):
		self.set_text('Preparing...')
		source_archive, source_path = self._fs._split(splitscheme(self._src_url)[1])
		destination_archive, destination_path = self._fs._split(splitscheme(self._dst_url)[1])
		if Path(destination_archive).exists() and os.path.samefile(source_archive, destination_archive):
			raise OSError(EIO, 'Source and destination refer to the same archive')
		if not source_path:
			raise UnsupportedOperation('Moving the archive root is not supported; copy its contents')
		state = _archive_state(source_archive, self.check_canceled)
		with _transfer_temp_directory(self) as tmp_dir:
			# Give temp dir the same name as the source file; This leads to the
			# correct name being displayed in the progress dialog:
			tmp_url = as_url(os.path.join(tmp_dir, basename(self._src_url)))
			self.run(Extract(self._fs._fs, source_archive, source_path,
				as_human_readable(tmp_url)))
			self.run(AddToArchive(self._fs, self._fs._fs, as_human_readable(tmp_url),
				destination_archive, destination_path, for_move=True))
			self.check_canceled()
			self.run(UpdateArchive(self._fs, self._src_url, state))

def _basename(zip_path, path_in_zip):
	sep = ('/' if path_in_zip else '')
	return (zip_path + sep + path_in_zip).rsplit('/', 1)[-1]

def _run_7zip(args, cwd=None, pty=False):
	with _7zip(args, cwd=cwd, pty=pty):
		pass

def _create_temp_dir_next_to(path):
	return TemporaryDirectory(
		dir=str(Path(path).parent), prefix='', suffix='.tmp'
	)

class _7zip:

	_7ZIP_WARNING = 1

	def __init__(self, args, cwd=None, pty=False, kill=False, allow_warning=True):
		self._args = args
		self._cwd = cwd
		self._pty = pty
		self._kill = kill
		self._killed = False
		self._allow_warning = allow_warning
		self._process = None
		self._stdout_lines = deque(maxlen=100)
	def __enter__(self):
		if PLATFORM == 'Windows':
			cls = Run7ZipViaWinpty if self._pty else Popen7ZipWindows
		else:
			cls = Run7ZipViaPty if self._pty else Popen7ZipUnix
		self._process = cls(self._args, self._cwd)
		return self
	@property
	def stdout_lines(self):
		for line in self._process.stdout:
			self._stdout_lines.append(line)
			yield line
	def kill(self):
		self._killed = True
		self._process.kill()
	def wait(self):
		return self._process.wait()
	def progress_records(self, check, truncate=True):
		chunks = Queue(maxsize=16)
		stopped = Event()
		done = Event()
		errors = []
		def read():
			try:
				for chunk in self._process.output_chunks():
					while not stopped.is_set():
						try:
							chunks.put(chunk, timeout=.1)
							break
						except Full:
							pass
					if stopped.is_set():
						break
			except Exception as error:
				errors.append(error)
			finally:
				done.set()
		reader = Thread(target=read, name='7zip-output')
		reader.start()
		buffer = ''
		try:
			while not done.is_set() or not chunks.empty():
				check()
				try:
					chunk = chunks.get(timeout=.1)
				except Empty:
					continue
				for character in chunk:
					if character in '\r\n\b':
						if buffer:
							self._stdout_lines.append(buffer[:4096])
							yield buffer
							buffer = ''
					elif not truncate or len(buffer) < 4096:
						buffer += character
			if buffer:
				self._stdout_lines.append(buffer[:4096])
				yield buffer
			while self._process.poll() is None:
				check()
				stopped.wait(.1)
			check()
			if errors:
				raise errors[0]
		finally:
			stopped.set()
			if self._process.poll() is None:
				self.kill()
			self.wait()
			reader.join()
	def __exit__(self, exc_type, exc_val, exc_tb):
		try:
			if self._kill:
				self._process.kill()
				self._process.wait()
			else:
				exit_code = self._process.wait()
				if exit_code and not self._killed and exc_type is None and \
					not (self._allow_warning and exit_code == self._7ZIP_WARNING):
					raise _7zipError(
						exit_code, self._args, ''.join(self._stdout_lines)
					)
		finally:
			self._process.stdout.close()

class _7zipError(CalledProcessError):
	def __str__(self):
		result = '7-Zip with args %r returned non-zero exit status %d' % \
				 (self.cmd, self.returncode)
		if self.output:
			result += '. Output: %r' % re.sub('(\r?\n)+', ' ', self.output)
		return result

class Popen7Zip:
	def __init__(self, args, cwd, env, encoding=None, **kwargs):
		# We need to supply stdin and stderr != None because otherwise on
		# Windows, when fman is run as a GUI app, we get:
		# 	OSError: [WinError 6] The handle is invalid
		# This is likely caused by https://bugs.python.org/issue3905.
		self._process = Popen(
			[_7ZIP_BINARY] + args, stdout=PIPE, stderr=DEVNULL, stdin=DEVNULL,
			cwd=cwd, env=env, **kwargs
		)
		self.stdout = SourceClosingTextIOWrapper(self._process.stdout, encoding)
	def kill(self):
		self._process.kill()
	def wait(self):
		return self._process.wait()
	def poll(self):
		return self._process.poll()
	def output_chunks(self):
		decoder = getincrementaldecoder(self.stdout.encoding)(errors='replace')
		while True:
			chunk = self.stdout.buffer.read1(4096)
			if not chunk:
				break
			yield decoder.decode(chunk)
		tail = decoder.decode(b'', final=True)
		if tail:
			yield tail

class Popen7ZipWindows(Popen7Zip):
	def __init__(self, args, cwd):
		args = _get_7zip_args_windows(args)
		super().__init__(
			args, cwd, env=None, encoding='utf-8',
			startupinfo=self._get_startupinfo()
		)
	def _get_startupinfo(self):
		from subprocess import STARTF_USESHOWWINDOW, SW_HIDE, STARTUPINFO
		result = STARTUPINFO()
		result.dwFlags = STARTF_USESHOWWINDOW
		result.wShowWindow = SW_HIDE
		return result

def _get_7zip_args_windows(args):
	return ['-sccUTF-8'] + args

class Popen7ZipUnix(Popen7Zip):
	def __init__(self, args, cwd):
		env, encoding = _get_7zip_env_encoding_unix()
		super().__init__(args, cwd, env, encoding=encoding)

def _get_7zip_env_encoding_unix():
	# According to the README in its source code distribution, p7zip can
	# only handle unicode file names properly if the environment is UTF-8:
	env = {'LANG': 'en_US.UTF-8'}
	# Force encoding because TextIOWrapper uses ASCII if
	# locale.getpreferredencoding(False) happens to be None:
	encoding = 'utf-8'
	return env, encoding

class Run7ZipViaPty:
	"""
	When run from a terminal, 7-Zip displays progress information for some
	operations. This works as follows: It prints a line, say
		 41% + Picture.jpg
	Then, it outputs ASCII control characters that *delete* the line again. In
	the above example on Linux, this would be 18 * '\b', the Backspace
	character. Next, it "overwrites" the existing characters with 18 * ' '.
	Finally, it outputs the new line:
		 59% + Picture.jpg

	Unlike Popen, this class lets us read the progress information as it is
	written by 7-Zip. This is achieved by 1) faking a pseudo-terminal (hence the
	name "Pty") and 2) by faithfully interpreting '\b' in the subprocess's
	output.
	"""

	class Stdout:
		def __init__(self, fd, encoding):
			self._fd = fd
			self._encoding = encoding
			self._source = BufferedReader(FileIO(self._fd))
		def __iter__(self):
			buffer = b''
			prev_len_delta = 0
			curr_line = lambda: buffer.decode(self._encoding)
			while True:
				try:
					b = self._source.read(1)
				except OSError:
					yield curr_line()
					break
				if b == b'':
					yield curr_line()
					break
				elif b == b'\b':
					if prev_len_delta == 1:
						l = curr_line()
						if l.strip():
							yield l
					buffer = buffer[:-1]
					prev_len_delta = -1
				else:
					buffer += b
					if b == b'\n':
						yield curr_line()
						buffer = b''
						prev_len_delta = 0
					else:
						prev_len_delta = 1
		def close(self):
			self._source.close()

	def __init__(self, args, cwd):
		env, encoding = _get_7zip_env_encoding_unix()
		self._pid, fd = self._spawn([_7ZIP_BINARY] + args, cwd, env)
		self.stdout = self.Stdout(fd, encoding=encoding)
	def kill(self):
		os.kill(self._pid, signal.SIGTERM)
	def wait(self):
		return os.waitpid(self._pid, 0)[1]
	def _spawn(self, argv, cwd=None, env=None):
		# Copied and adapted from pty.spawn(...).
		import pty # <- import late because pty is not available on Windows.
		pid, master_fd = pty.fork()
		if pid == pty.CHILD:
			# In some magical way, this code is executed in the forked child
			# process.
			if cwd is not None:
				os.chdir(cwd)
			if env is not None:
				os.environ = env
			os.execlp(argv[0], *argv)
		return pid, master_fd

class Run7ZipViaWinpty:

	class Stdout:
		def __init__(self, process):
			self._process = process
			self._escape_ansi = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
		def __iter__(self):
			while True:
				try:
					line = self._process.read()
				except EOFError:
					break
				line = self._escape_ansi.sub('', line)
				if line:
					yield line
		def close(self):
			try:
				self._process.close()
			finally:
				# pywinpty marks the process closed in wait(), causing close()
				# to leave these sockets open.
				self._process.fileobj.close()
				self._process._server.close()

	def __init__(self, args, cwd):
		args = _get_7zip_args_windows(args)
		self._process = self._spawn([_7ZIP_BINARY] + args, cwd)
		self.stdout = self.Stdout(self._process)
	def kill(self):
		self._process.sendcontrol('c')
	def wait(self):
		return self._process.wait()
	def _spawn(self, argv, cwd=None, env=None):
		from winpty import PtyProcess
		return PtyProcess.spawn(argv, cwd, env)

class ZipFileSystem(_7ZipFileSystem):
	scheme = 'zip://'

class SevenZipFileSystem(_7ZipFileSystem):
	scheme = '7z://'

class TarFileSystem(_7ZipFileSystem):
	scheme = 'tar://'

_FileInfo = namedtuple('_FileInfo', ('path', 'is_dir', 'size_bytes', 'mtime'))

class SourceClosingTextIOWrapper(TextIOWrapper):
	def close(self):
		super().close()
		self.buffer.close()