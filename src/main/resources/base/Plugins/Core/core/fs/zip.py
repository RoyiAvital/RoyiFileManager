"""Archives through 7-Zip: read-only, one listing per archive version, one run per operation.

Every archive type shares one policy. A listing (`7za l -slt`) is kept in memory per
archive version and answers browsing and the checks before an operation. Each
operation starts 7-Zip once, whatever the number of items: output is staged on the
destination's volume and published by rename. Archive files are never changed.
Compressed tars (`x.tar.gz`) are read through a pipe of two 7-Zip processes.
"""
from collections import namedtuple, deque, Counter, OrderedDict
from codecs import getincrementaldecoder
from core.util import filenotfounderror
from datetime import datetime
from errno import EEXIST, EIO, ENOENT, ENOTDIR
from fman import PLATFORM, load_settings, Task, show_status_message, clear_status_message
from fman.fs import FileSystem
from fman.url import as_url, splitscheme, as_human_readable
from io import UnsupportedOperation, TextIOWrapper
from os.path import join, dirname
from pathlib import Path
from queue import Queue, Empty, Full
from stat import S_ISREG
from subprocess import Popen, PIPE, DEVNULL, CalledProcessError
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread

import fman.fs
import os
import os.path
import re
import sys
import time

__all__ = ['ZipFileSystem', 'SevenZipFileSystem', 'TarFileSystem', 'CompressedTarFileSystem']

READ_ONLY_MESSAGE = 'Archives are read-only. Unpack the archive, change the files and pack them again.'

_7ZIP_BINARY = join(
	dirname(dirname(dirname(__file__))), 'bin', PLATFORM.lower(), '7za'
)
_7ZIP_BINARY += '.exe'

class _7ZipFileSystem(FileSystem):
	read_only_message = READ_ONLY_MESSAGE
	def __init__(self, fs=fman.fs, suffixes=None):
		if suffixes is None:
			suffixes = self._load_suffixes_from_json()
		super().__init__()
		self._fs = fs
		self._suffixes = suffixes
	@property
	def _reader(self):
		return _DIRECT
	def _load_suffixes_from_json(self):
		settings = load_settings('AppSettings.yaml', default={})
		archive_handlers = settings.get('archive_handlers', {})
		return set(
			suffix for suffix, scheme in archive_handlers.items()
			if scheme == self.scheme
		)
	def get_default_columns(self, path):
		return 'core.Name', 'core.Size', 'core.Modified'
	def resolve(self, path):
		# A path is inside an archive only below a component named like an archive
		# that is not a real folder; otherwise it is a file system location (going
		# up from C:/old.zip/a.zip reaches the folder C:/old.zip).
		parts, candidates = self._archive_components(path)
		if any(not os.path.isdir('/'.join(parts[:index + 1])) for index in candidates):
			if not self.exists(path):
				raise FileNotFoundError(self.scheme + path)
			return super().resolve(path)
		return self._fs.resolve(as_url(path))
	def iterdir(self, path):
		zip_path, path_in_zip = self._split(path)
		return iter(self._folder(zip_path, path_in_zip, path))
	def scan(self, path, check_canceled):
		from fman.listing import Listing
		zip_path, path_in_zip = self._split(path)
		members = self.members(zip_path, check_canceled)
		folder = _normal(path_in_zip)
		names = self._folder(zip_path, folder, path, members)
		entries = [members.get(_join(folder, name)) for name in names]
		check_canceled()
		return Listing.create(self.scheme + path, names,
			is_dir=(entry.is_dir for entry in entries),
			sizes=(entry.size_bytes for entry in entries),
			mtimes_ns=(_nanoseconds(entry.mtime) for entry in entries))
	def is_dir(self, existing_path):
		zip_path, path_in_zip = self._split(existing_path)
		member = _normal(path_in_zip)
		if not member:
			if Path(zip_path).exists():
				return True
			raise filenotfounderror(existing_path)
		return self._entry(zip_path, member, existing_path).is_dir
	def exists(self, path):
		try:
			zip_path, path_in_zip = self._split(path)
		except FileNotFoundError:
			return False
		member = _normal(path_in_zip)
		if not member:
			return Path(zip_path).exists()
		try:
			return self.members(zip_path).get(member) is not None
		except FileNotFoundError:
			return False
	def members(self, zip_path, check=None, progress=None):
		"""The member list of the archive at the OS path `zip_path`."""
		return _MEMBER_LISTS.get(zip_path, self._reader, check, progress)
	def _entry(self, zip_path, member, url_path):
		entry = self.members(zip_path).get(member)
		if entry is None:
			raise filenotfounderror(self.scheme + url_path)
		return entry
	def _folder(self, zip_path, path_in_zip, url_path, members=None):
		if members is None:
			members = self.members(zip_path)
		names = members.folder(_normal(path_in_zip))
		if names is None:
			raise filenotfounderror(self.scheme + url_path)
		return names
	def copy(self, src_url, dst_url):
		for task in self.prepare_copy(src_url, dst_url):
			task()
	def prepare_copy(self, src_url, dst_url):
		src_scheme, src_path = splitscheme(src_url)
		dst_scheme, dst_path = splitscheme(dst_url)
		if src_scheme == self.scheme and dst_scheme == 'file://':
			zip_path, path_in_zip = self._split(src_path)
			return [Extract(self._fs, zip_path, _normal(path_in_zip), as_human_readable(dst_url), self._reader)]
		raise UnsupportedOperation(
			READ_ONLY_MESSAGE if dst_scheme == self.scheme else
			'Items in an archive can only be copied to a local folder.'
		)
	def size_bytes(self, path):
		return self._attribute(path, 'size_bytes')
	def modified_datetime(self, path):
		return self._attribute(path, 'mtime')
	def _attribute(self, path, name):
		zip_path, path_in_zip = self._split(path)
		member = _normal(path_in_zip)
		if not member:
			return None
		return getattr(self._entry(zip_path, member, path), name)
	def _split(self, path):
		"""Split into (archive path, path inside it) at a whole path component.

		Components named like archives can also be folders (C:/old.zip/a.zip) or
		members (a.zip/inner.zip/x). With one such component, it is the archive and
		no disk check is made. With several, the first that is not an existing
		folder is the archive; a missing archive still splits so callers report it.
		"""
		parts, candidates = self._archive_components(path)
		if not candidates:
			raise filenotfounderror(self.scheme + path) from None
		index = candidates[0]
		if len(candidates) > 1:
			index = next((candidate for candidate in candidates[:-1]
				if not os.path.isdir('/'.join(parts[:candidate + 1]))), candidates[-1])
		return '/'.join(parts[:index + 1]), '/'.join(parts[index + 1:]).lstrip('/')
	def _archive_components(self, path):
		"""Path components and the indices of those named like an archive."""
		parts = path.split('/')
		return parts, [index for index, part in enumerate(parts)
			if any(part.lower().endswith(suffix) for suffix in self._suffixes)]

def _normal(path_in_zip):
	return '/'.join(part for part in path_in_zip.split('/') if part and part != '.')

def _join(folder, name):
	return folder + '/' + name if folder else name

def _nanoseconds(mtime):
	try:
		return None if mtime is None else round(mtime.timestamp() * 1_000_000_000)
	except (OSError, OverflowError, ValueError):
		return None

_Entry = namedtuple('_Entry', ('stored', 'is_dir', 'size_bytes', 'mtime', 'is_link'))
# A folder that only appears in its members' paths has no stored entry.
_IMPLICIT_FOLDER = _Entry(None, True, None, None, False)
_LINK_MODE = re.compile(r'(?:^|\s)l[-rwxsStT]{9}')
# 'C:/x' or 'C:' is outside the root; 'a:b.txt' is a name 7-Zip changes on extraction.
_DRIVE_PATH = re.compile(r'[A-Za-z]:(?:/|$)')

class _Members:
	"""The entries of one archive version, by path without a leading './' ('' is the root)."""
	def __init__(self):
		self._entries = {'': _IMPLICIT_FOLDER}
		self._children = {'': {}}
		self.links = set()
		# (name as stored without a leading './', is folder) of every listed entry.
		self.names = []
		# The leading './' of stored names: '' and './' when an archive mixes both.
		self._prefixes = set()
		# Listed records, also the '.' entry: a tar of an empty folder has only that.
		self.records = 0
	def __len__(self):
		return len(self._entries) - 1
	def add(self, fields):
		self.records += 1
		stored = fields['Path'].replace('\\', '/')
		text, prefix = stored, ''
		while text.startswith('./'):
			text, prefix = text[2:], prefix + './'
		if text in ('', '.'):
			return
		parts = text.split('/')
		if text.startswith('/') or '..' in parts or _DRIVE_PATH.match(text):
			raise OSError(EIO, "The archive has an entry outside its root: " + stored)
		attributes = fields.get('Attributes', '')
		mode = fields.get('Mode', '')
		is_dir = fields.get('Folder') == '+' or attributes.lstrip().startswith('D') or mode.startswith('d')
		is_link = not is_dir and bool(fields.get('Symbolic Link') or mode.startswith('l') or
			_LINK_MODE.search(attributes))
		self.names.append((text, is_dir))
		path = _normal(text)
		if not path:
			return
		self._prefixes.add(prefix)
		size = fields.get('Size', '')
		modified = fields.get('Modified', '')
		try:
			mtime = datetime.fromisoformat(modified) if modified else None
		except ValueError:
			mtime = None
		entry = _Entry(stored, is_dir, int(size) if size.isdigit() else None, mtime, is_link)
		previous = self._entries.get(path)
		if previous is not None and previous.is_dir and not is_dir:
			# Keep a folder that has members; the name rules refuse the collision.
			return
		self._entries[path] = entry
		if is_dir:
			self._children.setdefault(path, {})
		# A later entry of the same path replaces a link, as extraction does.
		if is_link:
			self.links.add(path)
		else:
			self.links.discard(path)
		while True:
			parent, _, name = path.rpartition('/')
			children = self._children.get(parent)
			if children is not None:
				children[name] = None
				return
			self._children[parent] = {name: None}
			if not self._entries.get(parent, _IMPLICIT_FOLDER).is_dir or parent not in self._entries:
				self._entries[parent] = _IMPLICIT_FOLDER
				self.links.discard(parent)
			path = parent
	def get(self, path):
		return self._entries.get(path)
	def folder(self, path):
		"""Names in the folder at `path`, or None if it is not a folder."""
		children = self._children.get(path)
		return None if children is None else list(children)
	def stored(self, path):
		entry = self._entries[path]
		if entry.stored is not None:
			return entry.stored
		# include_names refuses a folder when the archive mixes prefixes, so there is one.
		return next(iter(self._prefixes), '') + path
	def check_names(self, check):
		"""Refuse names that Windows would change on extraction, or that collide."""
		manifest, explicit = {}, set()
		for index, (path, is_dir) in enumerate(self.names):
			if not index & 1023:
				check()
			_add_to_manifest(manifest, explicit, path, is_dir)
		return manifest
	def include_names(self, chosen):
		"""Stored names for 7-Zip to extract `chosen`, or None for everything."""
		chosen = set(chosen)
		if '' in chosen or chosen.issuperset(self._children['']):
			return None
		if len(self._prefixes) > 1:
			# 7-Zip matches './docs' and 'docs' as different names: a folder would come out incomplete.
			if any(self._entries[path].is_dir for path in chosen):
				raise OSError(EIO, 'This archive stores names both with and without "./". '
					'Choose files only, all items, or unpack the archive.')
			return [self.stored(path) for path in sorted(chosen)]
		by_folder = {}
		for path in chosen:
			folder, _, name = path.rpartition('/')
			by_folder.setdefault(folder, set()).add(name)
		names = set(chosen)
		for folder, selected in by_folder.items():
			# A folder whose entries were all chosen stands for them.
			if folder and len(selected) == len(self._children.get(folder, ())):
				names.difference_update(_join(folder, name) for name in selected)
				names.add(folder)
		return [self.stored(path) for path in sorted(names)]
	def links_within(self, chosen):
		"""Symbolic links among `chosen` and inside its folders."""
		chosen = set(chosen)
		if '' in chosen:
			return set(self.links)
		result = set()
		for link in self.links:
			path = link
			while path:
				if path in chosen:
					result.add(link)
					break
				path = path.rpartition('/')[0]
		return result

def _read_members(records, check):
	members = _Members()
	fields = None
	for index, record in enumerate(records):
		if not index & 1023:
			check()
		key, separator, value = record.partition(' = ')
		if not separator:
			continue
		if key == 'Path':
			if fields is not None:
				members.add(fields)
			fields = {'Path': value}
		elif fields is not None:
			fields.setdefault(key, value)
	if fields is not None:
		members.add(fields)
	return members

def _never():
	pass

class _MemberLists:
	"""Member lists by archive version, kept while they hold at most LIMIT members together."""
	LIMIT = 1_000_000
	def __init__(self):
		self._lists = OrderedDict()
		self._building = {}
		self._lock = Lock()
	def get(self, zip_path, reader, check=None, progress=None):
		check = check or _never
		key = self._key(zip_path, reader)
		while True:
			with self._lock:
				members = self._lists.get(key)
				if members is not None:
					self._lists.move_to_end(key)
					return members
				build = self._building.get(key)
				owner = build is None
				if owner:
					build = self._building[key] = Lock()
					build.acquire()
			if owner:
				break
			# Another thread lists this archive; take over if it is cancelled.
			while not build.acquire(timeout=.1):
				check()
			build.release()
		try:
			members = reader.read(zip_path, check, progress)
			if self._key(zip_path, reader) != key:
				raise OSError(EIO, 'Archive changed while being read: ' + os.path.basename(zip_path))
			with self._lock:
				for other in [other for other in self._lists if other[:2] == key[:2]]:
					del self._lists[other]
				self._lists[key] = members
				total = sum(len(value) for value in self._lists.values())
				while total > self.LIMIT and len(self._lists) > 1:
					total -= len(self._lists.popitem(last=False)[1])
			return members
		finally:
			with self._lock:
				self._building.pop(key, None)
			build.release()
	def clear(self):
		with self._lock:
			self._lists.clear()
	@staticmethod
	def _key(zip_path, reader):
		info = os.stat(zip_path)
		return (reader.kind, os.path.normcase(os.path.abspath(zip_path)), info.st_dev, info.st_ino,
			info.st_size, info.st_mtime_ns)

_MEMBER_LISTS = _MemberLists()

class _DirectReader:
	"""7-Zip reads the archive file itself."""
	kind = 'direct'
	piped = False
	def read(self, zip_path, check, progress=None):
		# The listing's header holds the reason when the archive is damaged, e.g. its end is missing.
		header = []
		try:
			with _7zip(['l', '-slt', '-bse1', zip_path]) as process:
				return _members_of(process, check, header)
		except _7zipError as error:
			raise OSError(EIO, _cannot_read(zip_path, error, header)) from error

class _PipedReader:
	"""7-Zip decompresses the archive into a second 7-Zip that reads it as a tar."""
	kind = 'piped'
	piped = True
	TYPES = {'gzip', 'bzip2', 'xz', 'zstd'}
	def read(self, zip_path, check, progress=None):
		name = os.path.basename(zip_path)
		types = set()
		try:
			with _7zip(['l', '-slt', '-bse1', zip_path]) as process:
				records = process.progress_records(check, truncate=False)
				try:
					for record in records:
						if record.startswith('Type = '):
							types.add(record[len('Type = '):])
						elif record.startswith('-' * 10):
							# The archive's properties end here; its entry list is not needed.
							break
				finally:
					records.close()
		except _7zipError:
			types = set()
		if not types & self.TYPES:
			raise OSError(EIO, 'Not a compressed tar archive: ' + name)
		status = _StatusProgress('Reading ' + name) if progress is None else None
		try:
			with _7zip(['l', '-ba', '-slt', '-bse1', '-si', '-ttar'], allow_warning=False,
					pipe_from=zip_path, on_progress=progress or status) as process:
				members = _members_of(process, check)
		except _7zipError as error:
			raise OSError(EIO, 'Not a compressed tar archive: ' + name) from error
		finally:
			if status is not None:
				status.close()
		if not members.records and not _starts_with_zero_block(zip_path):
			# Through a pipe 7-Zip lists any other data as an empty tar.
			raise OSError(EIO, 'Not a compressed tar archive: ' + name)
		return members

_DIRECT = _DirectReader()
_PIPED = _PipedReader()

def _members_of(process, check, header=None):
	"""The listed members; a listing with a header puts its first lines in `header`."""
	records = process.progress_records(check, truncate=False)
	try:
		if header is not None:
			for record in records:
				if record.startswith('-' * 10):
					break
				if len(header) < 100:
					header.append(record)
		return _read_members(records, check)
	finally:
		# A refused entry or Cancel stops reading early: end 7-Zip and its reader thread.
		records.close()

def _starts_with_zero_block(zip_path):
	process = Popen([_7ZIP_BINARY, '-sccUTF-8', 'x', '-so', '-bso0', '-bse0', '-bsp0', zip_path],
		stdout=PIPE, stderr=DEVNULL, stdin=DEVNULL, startupinfo=_hidden_window())
	try:
		block = process.stdout.read(512)
	finally:
		process.kill()
		process.wait()
		process.stdout.close()
	return len(block) == 512 and not any(block)

def _cannot_read(zip_path, error, header=()):
	reason = _reason_in([*header, *(error.output or '').splitlines()], zip_path)
	return 'Cannot read %s%s' % (os.path.basename(zip_path), ': ' + reason if reason else '.')

def _reason_in(lines, path=''):
	"""7-Zip's first reason: the line after a heading such as 'ERRORS:', or the text of an
	'ERROR: ' line without the archive's path ('ERROR: Data Error : a.txt')."""
	lines = [line.strip() for line in lines if ' = ' not in line and line.strip()]
	path = os.path.normcase(os.path.normpath(path)) if path else None
	for index, line in enumerate(lines):
		if line.startswith('Enter password'):
			# 7-Zip asked for a password; with no input it stops ('Break signaled').
			return 'The archive needs a password'
		if line.endswith(':') and ('ERROR' in line or 'WARNING' in line):
			if index + 1 < len(lines):
				return lines[index + 1]
		elif 'ERROR: ' in line:
			parts = [part for part in line.partition('ERROR: ')[2].split(' : ')
				if os.path.normcase(os.path.normpath(part)) != path]
			if parts:
				return ' : '.join(parts)
	return ''

class _StatusProgress:
	"""Shows a read's percentage in the status bar, at most 4 times per second."""
	def __init__(self, text):
		self._text = text
		self._shown = None
		self._time = None
	def __call__(self, percent):
		now = time.monotonic()
		if percent == self._shown or (self._time is not None and now - self._time < .25):
			return
		self._shown, self._time = percent, now
		try:
			show_status_message('%s: %d%%' % (self._text, percent))
		except Exception:
			pass
	def close(self):
		if self._shown is not None:
			try:
				clear_status_message()
			except Exception:
				pass

class _7zipTaskWithProgress(Task):
	def run_7zip_with_progress(self, args, allow_warning=True, progress_limit=100, check_before=True,
		pipe_from=None, **kwargs):
		"""Run 7-Zip and follow its percentage; with `pipe_from`, the decompressor's."""
		if check_before:
			self.check_canceled()
		pending = []
		def check():
			self.check_canceled()
			if pending:
				self._advance(pending[-1], progress_limit)
				pending.clear()
		with _7zip(args, allow_warning=allow_warning, pipe_from=pipe_from,
				on_progress=pending.append if pipe_from else None, **kwargs) as process:
			lines = process.progress_records(check)
			try:
				for line in lines:
					try:
						check()
					except Task.Canceled:
						process.kill()
						raise
					match = re.match(r'\s*(\d{1,3})%(?:\s|$)', line)
					if match:
						self._advance(int(match.group(1)), progress_limit)
			finally:
				lines.close()
	def _advance(self, percent, limit):
		percent = min(limit, percent)
		if percent > self.get_progress():
			self.set_progress(percent)

class _DestinationExists(FileExistsError):
	def __init__(self, name):
		super().__init__('Destination already exists: ' + name)
		self.errno = EEXIST

class Extract(_7zipTaskWithProgress):
	"""Extract from one archive with one 7-Zip run, then move the output into place.

	Copies extract chosen members, each to its own destination; further copies from
	the same archive join an Extract through absorb(). Unpack extracts everything,
	into a new folder or an existing one, and only creates.
	"""
	def __init__(self, fman_fs, zip_path, path_in_zip, dst_ospath, reader=None):
		super().__init__('Extracting ' + _basename(zip_path, path_in_zip), size=100)
		self._fman_fs = fman_fs
		self._zip_path = zip_path
		self._path_in_zip = path_in_zip
		self._dst_ospath = dst_ospath
		self._reader = reader or _DIRECT
		# (member, destination, replace): a copy replaces only what the user agreed to.
		self._pairs = [(_normal(path_in_zip), dst_ospath, os.path.lexists(dst_ospath))]
		self._mode = None
	@property
	def batch_key(self):
		"""Copies with the same key can share this run; see absorb()."""
		return None if self._mode else (os.path.normcase(self._zip_path), self._reader.kind)
	def absorb(self, other):
		if not isinstance(other, Extract) or self.batch_key is None or other.batch_key != self.batch_key:
			return False
		self._pairs.extend(other._pairs)
		self._title = 'Extracting {:,} items from {}'.format(len(self._pairs), os.path.basename(self._zip_path))
		return True
	def require_new_directory(self, archive_path, destination=None):
		self._require_root(archive_path, destination)
		self._mode = 'new'
	def require_existing_directory(self, archive_path, destination):
		self._require_root(archive_path, destination)
		self._mode = 'into'
	def _require_root(self, archive_path, destination):
		if self._path_in_zip or not os.path.samefile(archive_path, self._zip_path):
			raise OSError(EIO, 'Cannot safely identify the selected archive root')
		if destination is not None and os.path.normcase(os.path.normpath(destination)) != \
			os.path.normcase(os.path.normpath(self._dst_ospath)):
			raise OSError(EIO, 'Archive handler selected a different destination')
	def __call__(self):
		self.check_canceled()
		if self._mode:
			return self._unpack()
		return self._extract_chosen()
	def _members(self):
		name = os.path.basename(self._zip_path)
		def progress(percent):
			self.set_text('Reading %s: %d%%' % (name, percent))
		return _MEMBER_LISTS.get(self._zip_path, self._reader, self.check_canceled, progress)
	def _extract_chosen(self):
		members = self._members()
		for member, destination, replace in self._pairs:
			if members.get(member) is None:
				raise filenotfounderror(self._zip_path + '/' + member)
			if os.path.exists(destination) and os.path.samefile(self._zip_path, destination):
				raise OSError(EIO, 'Cannot extract over the source archive')
		chosen = [member for member, destination, replace in self._pairs]
		links = set(members.links_within(chosen))
		names = members.include_names(chosen)
		# Chosen names that differ only by case come out as one file on Windows: copy neither.
		by_case = Counter(member.casefold() for member in chosen)
		clashes = {member for member in chosen if by_case[member.casefold()] > 1}
		temporary = _create_temp_dir_next_to(self._pairs[0][1])
		try:
			output = Path(temporary.name, 'out')
			output.mkdir()
			args = ['x', '-bse1', '-y', '-spd', '-snl-', '-o' + str(output)]
			if names is not None:
				# -ssc: 7-Zip would also match 'makefile' for 'Makefile' and extract both into one name.
				args += ['-ssc', '-scsUTF-8', '-i@' + _write_list(Path(temporary.name, 'names.txt'), names)]
			self._extract(args, 90)
			self.check_canceled()
			folders = {}
			failures = []
			attempted = 0
			try:
				for index, (member, destination, replace) in enumerate(self._pairs):
					# Cancel stops between items; the items already moved stay, each complete.
					self.check_canceled()
					if member in links:
						continue
					attempted += 1
					if member in clashes:
						failures.append('%s: another chosen item differs only by case' % os.path.basename(destination))
						continue
					# Joined as text: a name part such as 'c:x.txt' must not leave the stage.
					source = str(output) + os.sep + member.replace('/', os.sep) if member else str(output)
					# Only a file replaces, and only an ordinary file the copy asked about;
					# a folder never replaces (os.replace would put it over a file).
					replaces = replace and not members.get(member).is_dir and _ordinary_file(destination)
					try:
						(os.replace if replaces else os.rename)(source, destination)
					except OSError as error:
						# Skip it and go on: the other items are extracted already.
						reason = 'not extracted' if not os.path.lexists(source) else error.strerror or str(error)
						failures.append('%s: %s' % (os.path.basename(destination), reason))
						continue
					folders.setdefault(os.path.dirname(destination), None)
					self._advance(90 + 10 * (index + 1) // len(self._pairs), 99)
			finally:
				# Also when publishing stops early, panes must show what was moved.
				for folder in folders:
					self._fman_fs.notify_file_changed(as_url(folder))
			self.set_progress(self.get_size())
			self._report_links(len(links))
			if failures:
				raise OSError(EIO, '{:,} of {:,} items {} not copied: {}{}'.format(len(failures), attempted,
					'was' if len(failures) == 1 else 'were', '; '.join(failures[:3]), '; ...' if len(failures) > 3 else ''))
		finally:
			_cleanup_extraction(self, temporary)
	def _unpack(self):
		destination = self._dst_ospath
		into = self._mode == 'into'
		if not into and os.path.lexists(destination):
			raise FileExistsError(EEXIST, 'Destination already exists', None, None, destination)
		# Before reading the archive: an existing file on the way to a new folder refuses.
		stage = destination if into else _existing_ancestor(os.path.dirname(destination))
		self.set_text('Checking archive entries')
		members = self._members()
		members.check_names(self.check_canceled)
		if into:
			for name in members.folder(''):
				if os.path.lexists(os.path.join(destination, name)):
					raise _DestinationExists(name)
		temporary = TemporaryDirectory(dir=stage, prefix='', suffix='.tmp')
		try:
			output = Path(temporary.name, 'contents')
			output.mkdir()
			self.set_text('Extracting ' + os.path.basename(self._zip_path))
			self._extract(['x', '-bse1', '-y', '-spd', '-snl-', '-o' + str(output)], 99)
			if output.is_symlink() or output.is_junction() or not output.is_dir():
				raise OSError(EIO, 'Archive output is not an ordinary directory')
			self.check_canceled()
			if into:
				moved = False
				try:
					for name in os.listdir(output):
						self.check_canceled()
						try:
							os.rename(os.path.join(output, name), os.path.join(destination, name))
						except OSError as error:
							raise OSError(error.errno, '%s: %s' % (name, error.strerror or error)) from error
						moved = True
				finally:
					if moved:
						fman.fs.notify_file_changed(as_url(destination))
			else:
				# The folders between the existing one and the destination, top first.
				created = []
				folder = os.path.dirname(destination)
				while folder != stage and os.path.dirname(folder) != folder:
					created.insert(0, folder)
					folder = os.path.dirname(folder)
				try:
					os.makedirs(os.path.dirname(destination), exist_ok=True)
					os.rename(output, destination)
				except OSError:
					for folder in reversed(created):
						try:
							os.rmdir(folder)
						except OSError:
							break
					raise
				# A pane shows the existing folder, so announce the top folder that is new.
				fman.fs.notify_file_added(as_url(created[0] if created else destination))
			self.set_progress(self.get_size())
			self._report_links(len(members.links))
		finally:
			_cleanup_extraction(self, temporary)
	def _extract(self, args, progress_limit):
		before = os.stat(self._zip_path)
		try:
			if self._reader.piped:
				self.run_7zip_with_progress(args + ['-si', '-ttar'], allow_warning=False,
					progress_limit=progress_limit, pipe_from=self._zip_path)
			else:
				self.run_7zip_with_progress(args + ['-bsp1', self._zip_path], allow_warning=False,
					progress_limit=progress_limit)
		except _7zipError as error:
			raise OSError(EIO, _cannot_read(self._zip_path, error)) from error
		after = os.stat(self._zip_path)
		if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
			raise OSError(EIO, 'Archive changed while being read')
	def _report_links(self, count):
		if count:
			try:
				self.show_alert('{:,} symbolic {} skipped: links are not extracted from archives.'
					.format(count, 'link was' if count == 1 else 'links were'))
			except NotImplementedError:
				pass

_REPARSE_NAME_SURROGATE = 0x20000000

def _ordinary_file(path):
	"""A regular file with one name, which a copy may replace. As for Rename, links and
	junctions (name surrogates) and hard links are refused; cloud placeholders are not."""
	try:
		info = os.lstat(path)
	except FileNotFoundError:
		return False
	return S_ISREG(info.st_mode) and info.st_nlink == 1 and \
		not getattr(info, 'st_reparse_tag', 0) & _REPARSE_NAME_SURROGATE

def _existing_ancestor(path):
	"""The nearest existing folder at or above `path`; an existing file on the way refuses."""
	while not os.path.isdir(path):
		if os.path.lexists(path):
			raise NotADirectoryError(ENOTDIR, 'Not a folder: ' + path)
		parent = os.path.dirname(path)
		if parent == path:
			raise filenotfounderror(path)
		path = parent
	return path

def _write_list(path, names):
	"""A UTF-8 list file for 7-Zip; quotes keep leading and trailing spaces."""
	for name in names:
		if any(character in name for character in '"\r\n'):
			raise OSError(EIO, 'Cannot extract an entry whose name contains quotes or line breaks: ' + name)
	with open(path, 'w', encoding='utf-8', newline='\n') as stream:
		stream.writelines('"%s"\n' % name for name in names)
	return str(path)

class PackArchive(_7zipTaskWithProgress):
	"""Create a new archive from local files and folders in one 7-Zip run."""
	TYPES = {'zip://': 'zip', '7z://': '7z', 'tar://': 'tar'}
	def __init__(self, sources, destination, archive_type):
		super().__init__('Packing ' + os.path.basename(destination), size=100)
		self._sources = sources
		self._destination = destination
		self._type = archive_type
	def __call__(self):
		if os.path.lexists(self._destination):
			raise _DestinationExists(os.path.basename(self._destination))
		folder = os.path.dirname(self._destination)
		if not os.path.isdir(folder):
			raise FileNotFoundError(ENOENT, 'Destination folder does not exist: ' + folder)
		temporary = _create_temp_dir_next_to(self._destination)
		try:
			# 7-Zip adds an extension to a name without one, so keep the destination's.
			archive = os.path.join(temporary.name, 'archive' + os.path.splitext(self._destination)[1])
			items = _write_list(Path(temporary.name, 'items.txt'), self._sources)
			try:
				# The stage can lie inside a chosen folder; its unique name keeps it out of the archive.
				self.run_7zip_with_progress(['a', '-t' + self._type, '-bsp1', '-bse1', '-spd', '-scsUTF-8',
					'-xr!' + os.path.basename(temporary.name), archive, '@' + items], allow_warning=False, progress_limit=99)
			except _7zipError as error:
				raise OSError(EIO, _cannot_pack(error)) from error
			self.check_canceled()
			os.rename(archive, self._destination)
			fman.fs.notify_file_added(as_url(self._destination))
			self.set_progress(self.get_size())
		finally:
			_cleanup_extraction(self, temporary)

def _cannot_pack(error):
	lines = [line.strip() for line in (error.output or '').splitlines() if line.strip()]
	for index, line in enumerate(lines):
		if 'duplicate' in line.lower():
			# 'Duplicate filename on disk:' is followed by the name, once per item.
			name = lines[index + 1] if line.endswith(':') and index + 1 < len(lines) else ''
			return 'Two chosen items have the same name' + (': ' + name if name else '.')
	reason = _reason_in(lines)
	return 'Could not pack: ' + reason if reason else 'Could not pack.'

def _add_to_manifest(manifest, explicit, path, is_directory):
	parts = path.split('/')
	for part in parts:
		if not part or part in ('.', '..') or part.endswith(('.', ' ')) or \
			any(ord(character) < 32 or character in '<>:"|?*' for character in part) or \
			re.fullmatch(r'(?i:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])', part.split('.')[0]):
			raise OSError(EIO, 'Archive entry name may be changed by extraction: ' + path)
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

def _basename(zip_path, path_in_zip):
	sep = ('/' if path_in_zip else '')
	return (zip_path + sep + path_in_zip).rsplit('/', 1)[-1]

def _create_temp_dir_next_to(path):
	return TemporaryDirectory(
		dir=str(Path(path).parent), prefix='', suffix='.tmp'
	)

class _7zip:
	"""One 7-Zip run; with `pipe_from`, it reads the archive's decompressed stream."""

	_7ZIP_WARNING = 1

	def __init__(self, args, cwd=None, allow_warning=True, pipe_from=None, on_progress=None):
		self._args = args
		self._cwd = cwd
		self._killed = False
		self._allow_warning = allow_warning
		self._pipe_from = pipe_from
		self._on_progress = on_progress
		self._reported = None
		self._process = None
		self._source = None
		self._stdout_lines = deque(maxlen=100)
	def __enter__(self):
		if self._pipe_from is None:
			self._process = Popen7ZipWindows(self._args, self._cwd)
			return self
		self._source = _Decompressor(self._pipe_from)
		try:
			self._process = Popen7ZipWindows(self._args, self._cwd, stdin=PIPE)
		except BaseException:
			self._source.kill()
			self._source.close()
			raise
		self._source.pump_into(self._process.stdin)
		return self
	def kill(self):
		self._killed = True
		self._process.kill()
		if self._source is not None:
			self._source.kill()
	def wait(self):
		return self._process.wait()
	def _running(self):
		return self._process.poll() is None or \
			(self._source is not None and self._source.poll() is None)
	def _report_progress(self):
		if self._source is None or self._on_progress is None:
			return
		percent = self._source.percent
		if percent is not None and percent != self._reported:
			self._reported = percent
			self._on_progress(percent)
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
		try:
			reader = Thread(target=read, name='7zip-output')
			reader.start()
		except BaseException:
			try:
				self.kill()
				self.wait()
			except Exception:
				pass
			raise
		separators = re.compile('[\r\n\b]')
		limit = 4096 if truncate else None
		buffer = ''
		try:
			while not done.is_set() or not chunks.empty():
				check()
				self._report_progress()
				try:
					chunk = chunks.get(timeout=.1)
				except Empty:
					continue
				pieces = separators.split(chunk)
				if len(pieces) == 1:
					if limit is None or len(buffer) < limit:
						buffer += chunk
					continue
				pieces[0] = buffer + pieces[0]
				buffer = pieces.pop()
				for line in pieces:
					if line:
						line = line[:limit] if limit else line
						self._stdout_lines.append(line[:4096])
						yield line
				if limit is not None:
					buffer = buffer[:limit]
			if buffer:
				buffer = buffer[:limit] if limit else buffer
				self._stdout_lines.append(buffer[:4096])
				yield buffer
			while self._running():
				check()
				self._report_progress()
				stopped.wait(.1)
			check()
			self._report_progress()
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
			exit_code = self._process.wait()
			failed = exc_type is not None or self._killed
			main_failed = exit_code and not (self._allow_warning and exit_code == self._7ZIP_WARNING)
			source_code = 0
			if self._source is not None:
				if failed or main_failed:
					self._source.kill()
				source_code = self._source.wait()
			if not failed:
				if main_failed:
					raise _7zipError(exit_code, self._args, '\n'.join(self._stdout_lines))
				if source_code:
					raise _7zipError(source_code, self._source.args, self._source.output())
		finally:
			self._process.stdout.close()
			if self._source is not None:
				self._source.close()

class _Decompressor:
	"""A 7-Zip writing an archive's single decompressed stream, pumped into another process.

	The pump reads to the end even after the reader stops, so the exit code still
	reports a damaged stream. The percentage comes from standard error.
	"""
	def __init__(self, archive):
		self.args = ['x', '-so', '-bso0', '-bsp2', archive]
		self.percent = None
		self._errors = deque(maxlen=20)
		self._process = Popen([_7ZIP_BINARY] + _get_7zip_args_windows(self.args),
			stdout=PIPE, stderr=PIPE, stdin=DEVNULL, startupinfo=_hidden_window())
		self._threads = [Thread(target=self._read_errors, name='7zip-decompressor-errors', daemon=True)]
		self._threads[0].start()
	def pump_into(self, target):
		thread = Thread(target=self._pump, args=(target,), name='7zip-decompressor', daemon=True)
		self._threads.append(thread)
		thread.start()
	def _pump(self, target):
		source = self._process.stdout
		try:
			while True:
				chunk = source.read1(1 << 20)
				if not chunk:
					break
				if target is not None:
					try:
						target.write(chunk)
					except OSError:
						target = self._close(target)
		except (OSError, ValueError):
			pass
		finally:
			self._close(target)
	@staticmethod
	def _close(stream):
		if stream is not None:
			try:
				stream.close()
			except OSError:
				pass
	def _read_errors(self):
		decoder = getincrementaldecoder('utf-8')(errors='replace')
		separators = re.compile('[\r\n\b]')
		buffer = ''
		try:
			while True:
				chunk = self._process.stderr.read1(4096)
				if not chunk:
					break
				pieces = separators.split(buffer + decoder.decode(chunk))
				buffer = pieces.pop()[-4096:]
				for piece in pieces:
					match = re.match(r'\s*(\d{1,3})%', piece)
					if match:
						self.percent = min(100, int(match.group(1)))
					elif piece.strip():
						self._errors.append(piece.strip())
		except (OSError, ValueError):
			pass
		if buffer.strip():
			self._errors.append(buffer.strip())
	def output(self):
		return '\n'.join(self._errors)
	def poll(self):
		return self._process.poll()
	def kill(self):
		try:
			self._process.kill()
		except OSError:
			pass
	def wait(self):
		code = self._process.wait()
		for thread in self._threads:
			thread.join()
		return code
	def close(self):
		self.kill()
		self.wait()
		self._close(self._process.stdout)
		self._close(self._process.stderr)

class _7zipError(CalledProcessError):
	def __str__(self):
		result = '7-Zip with args %r returned non-zero exit status %d' % \
				 (self.cmd, self.returncode)
		if self.output:
			result += '. Output: %r' % re.sub('(\r?\n)+', ' ', self.output)
		return result

class Popen7Zip:
	def __init__(self, args, cwd, env, encoding=None, stdin=DEVNULL, **kwargs):
		# We need to supply stdin and stderr != None because otherwise on
		# Windows, when fman is run as a GUI app, we get:
		# 	OSError: [WinError 6] The handle is invalid
		# This is likely caused by https://bugs.python.org/issue3905.
		self._process = Popen(
			[_7ZIP_BINARY] + args, stdout=PIPE, stderr=DEVNULL, stdin=stdin,
			cwd=cwd, env=env, **kwargs
		)
		self.stdin = self._process.stdin
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
	def __init__(self, args, cwd, stdin=DEVNULL):
		args = _get_7zip_args_windows(args)
		super().__init__(
			args, cwd, env=None, encoding='utf-8', stdin=stdin,
			startupinfo=_hidden_window()
		)

def _hidden_window():
	from subprocess import STARTF_USESHOWWINDOW, SW_HIDE, STARTUPINFO
	result = STARTUPINFO()
	result.dwFlags = STARTF_USESHOWWINDOW
	result.wShowWindow = SW_HIDE
	return result

def _get_7zip_args_windows(args):
	return ['-sccUTF-8'] + args

class ZipFileSystem(_7ZipFileSystem):
	scheme = 'zip://'

class SevenZipFileSystem(_7ZipFileSystem):
	scheme = '7z://'

class TarFileSystem(_7ZipFileSystem):
	scheme = 'tar://'

class CompressedTarFileSystem(_7ZipFileSystem):
	"""A .tar.gz, .tar.bz2, .tar.xz or .tar.zst, read through a pipe without a temporary tar."""
	scheme = 'ctar://'
	@property
	def _reader(self):
		return _PIPED

class SourceClosingTextIOWrapper(TextIOWrapper):
	def close(self):
		super().close()
		self.buffer.close()