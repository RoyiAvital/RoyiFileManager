from dataclasses import dataclass, replace
from datetime import date, datetime, time as day_time, timedelta
import ntpath
import os
from pathlib import Path
import stat
import subprocess
import sys
from threading import Event, Lock, Thread
from time import localtime, mktime, monotonic


UNITS = (('b', 'Bytes'), ('k', 'Kilo Bytes'), ('m', 'Mega Bytes'), ('g', 'Giga Bytes'))
MULTIPLIERS = {'b': 1, 'k': 1000, 'm': 1000000, 'g': 1000000000}
TYPES = (('all', 'All entries'), ('f', 'Files'), ('d', 'Folders'), ('l', 'Symbolic links'),
	('x', 'Executables'), ('ef', 'Empty files'), ('ed', 'Empty folders'), ('s', 'Sockets'),
	('p', 'Named pipes'), ('b', 'Block devices'), ('c', 'Character devices'))
MAX_INTEGER = 2**64 - 1
CHUNK_BYTES = 65536
RECORD_BYTES = 131072
STDERR_BYTES = 65536


def split_list(value, exclusions=False):
	if not value.strip():
		return ()
	parts, current, index = [], [], 0
	while index < len(value):
		if exclusions and value[index:index + 2] == '\\;':
			current.append(';')
			index += 2
			continue
		if value[index] == ';':
			parts.append(''.join(current).strip())
			current = []
		else:
			current.append(value[index])
		index += 1
	parts.append(''.join(current).strip())
	if any(not part for part in parts):
		raise ValueError(('Exclude' if exclusions else 'Extensions') + ': empty list entry.')
	if not exclusions:
		parts = [part[1:] if part.startswith('.') else part for part in parts]
		if any(not part or any(char in part for char in '*?[]/\\;') for part in parts):
			raise ValueError('Extensions: use extensions without wildcards or path separators.')
	return tuple(parts)


def size_bytes(value, unit, label):
	if unit not in MULTIPLIERS:
		raise ValueError(label + ': unknown unit.')
	if value is None:
		return None
	if type(value) is not int or value < 0 or value * MULTIPLIERS[unit] > MAX_INTEGER:
		raise ValueError(label + ': enter a nonnegative integer fitting unsigned 64-bit bytes.')
	return value * MULTIPLIERS[unit]


def local_boundary(value):
	stamp = value.timetuple()
	candidates = set()
	for daylight in (-1, 0, 1):
		try:
			candidate = mktime(tuple(stamp[:8]) + (daylight,))
			if tuple(localtime(candidate)[:6]) == tuple(stamp[:6]):
				candidates.add(candidate)
		except (OverflowError, OSError, ValueError):
			pass
	if len(candidates) != 1:
		raise ValueError('Modified date has an ambiguous, nonexistent or unsupported local boundary.')


def date_arguments(start, end):
	values = []
	for label, value in (('Start date', start), ('End date', end)):
		try:
			parsed = None if value is None else date.fromisoformat(value)
			if parsed is not None and (parsed.isoformat() != value or parsed < date(1752, 9, 14)):
				raise ValueError()
		except (TypeError, ValueError):
			raise ValueError(label + ': enter an ISO calendar date from 1752-09-14.') from None
		values.append(parsed)
	start_day, end_day = values
	if start_day and end_day and start_day > end_day:
		raise ValueError('Modified: Start must not be after End.')
	arguments = []
	try:
		if start_day:
			midnight = datetime.combine(start_day, day_time())
			local_boundary(midnight)
			previous = midnight - timedelta(seconds=1)
			local_boundary(previous)
			arguments.append('--changed-within=' + previous.isoformat(sep=' ') + '.999999999')
		if end_day:
			midnight = datetime.combine(end_day + timedelta(days=1), day_time())
			local_boundary(midnight)
			arguments.append('--changed-before=' + midnight.isoformat(sep=' '))
	except OverflowError:
		raise ValueError('Modified: date boundary is outside the supported calendar range.') from None
	return arguments


@dataclass(frozen=True, slots=True)
class Options:
	root: str
	pattern: str = ''
	pattern_mode: str = 'glob'
	case_mode: str = 'smart'
	extensions: str = ''
	exclude: str = ''
	type: str = 'f'
	full_path: bool = False
	recursive: bool = True
	hidden: bool = False
	honor_gitignore: bool = True
	follow_symlinks: bool = False
	start_date: str | None = None
	end_date: str | None = None
	min_size: int | None = None
	max_size: int | None = None
	min_size_unit: str = 'b'
	max_size_unit: str = 'b'
	max_depth: int | None = None
	max_results: int | None = None
	max_rows: int = 10000
	max_text_bytes: int = 16 * 1024 * 1024

	def __post_init__(self):
		for name in ('root', 'pattern', 'extensions', 'exclude'):
			value = getattr(self, name)
			if not isinstance(value, str) or '\x00' in value or len(value) > 32768:
				raise ValueError('Invalid ' + name + '.')
		if not os.path.isabs(self.root):
			raise ValueError('Root: an absolute local directory is required.')
		for name in ('full_path', 'recursive', 'hidden', 'honor_gitignore', 'follow_symlinks'):
			if type(getattr(self, name)) is not bool:
				raise ValueError(name + ' must be boolean.')
		for name, allowed in (('pattern_mode', ('literal', 'glob', 'regex')),
				('case_mode', ('sensitive', 'insensitive', 'smart')), ('type', tuple(key for key, label in TYPES))):
			if getattr(self, name) not in allowed:
				raise ValueError('Invalid ' + name + '.')
		for name in ('max_depth', 'max_results'):
			value = getattr(self, name)
			if value is not None and (type(value) is not int or not 1 <= value <= MAX_INTEGER):
				raise ValueError(name.replace('_', ' ').capitalize() + ': enter a positive integer or leave unset.')
		for name, ceiling in (('max_rows', 10000), ('max_text_bytes', 16 * 1024 * 1024)):
			if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= ceiling:
				raise ValueError('Invalid ' + name + '.')
		minimum = size_bytes(self.min_size, self.min_size_unit, 'Minimum size')
		maximum = size_bytes(self.max_size, self.max_size_unit, 'Maximum size')
		if minimum is not None and maximum is not None and minimum > maximum:
			raise ValueError('Size: Minimum must not exceed Maximum.')
		date_arguments(self.start_date, self.end_date)
		split_list(self.extensions)
		split_list(self.exclude, True)


def resolve_engine():
	return str(Path(__file__).parent.parent / 'bin/fd.exe') if getattr(sys, 'frozen', False) else str(Path(sys.prefix) / 'bin/fd.exe')


def arguments(options, binary=None):
	result = [binary or resolve_engine(), '--color=never', '--hyperlink=never', '--print0',
		'--strip-cwd-prefix=always', '--path-separator=/', '--show-errors',
		{'literal': '--fixed-strings', 'glob': '--glob', 'regex': '--regex'}[options.pattern_mode],
		'--hidden' if options.hidden else '--no-hidden',
		'--follow' if options.follow_symlinks else '--no-follow']
	if options.honor_gitignore:
		result.extend(('--ignore-vcs', '--no-require-git'))
	else:
		result.append('--no-ignore-vcs')
	if options.case_mode != 'smart':
		result.append('--case-sensitive' if options.case_mode == 'sensitive' else '--ignore-case')
	if options.full_path:
		result.append('--full-path')
	depth = options.max_depth if options.recursive else 1
	if depth is not None:
		result.append('--max-depth=%d' % depth)
	if options.max_results is not None:
		result.append('--max-results=%d' % options.max_results)
	if options.type != 'all':
		result.extend('--type=' + kind for kind in options.type)
	result.extend('--extension=' + value for value in split_list(options.extensions))
	result.extend('--exclude=' + value for value in split_list(options.exclude, True))
	result.extend(date_arguments(options.start_date, options.end_date))
	for value, unit, prefix in ((options.min_size, options.min_size_unit, '+'), (options.max_size, options.max_size_unit, '-')):
		converted = size_bytes(value, unit, 'Size')
		if converted is not None:
			result.append('--size=%s%db' % (prefix, converted))
	result.extend(('--', options.pattern))
	if len(subprocess.list2cmdline(result).encode('utf-16-le')) // 2 > 24000:
		raise ValueError('Search command exceeds 24,000 UTF-16 units.')
	return result


def records(stream):
	buffer = bytearray()
	while chunk := stream.read(CHUNK_BYTES):
		buffer.extend(chunk)
		while True:
			end = buffer.find(0)
			if end < 0:
				break
			if end > RECORD_BYTES:
				raise ValueError('fd output record exceeds its size limit.')
			yield bytes(buffer[:end])
			del buffer[:end + 1]
		if len(buffer) > RECORD_BYTES:
			raise ValueError('fd output record exceeds its size limit.')
	if buffer:
		raise ValueError('Incomplete fd output record.')


@dataclass(frozen=True, slots=True)
class Hit:
	path: str
	relative_path: str
	size: int | None = None
	modified: str = ''


@dataclass(frozen=True, slots=True)
class Progress:
	phase: str
	matches: int = 0
	stored: int = 0
	elapsed: float = 0


@dataclass(frozen=True, slots=True)
class Result:
	rows: tuple
	total: int
	complete: bool
	table_limited: bool
	status: str
	reason: str


def count_text(shown, result):
	message = 'Showing {:,} / {:,} files'.format(shown, result.total)
	if result.table_limited:
		message += ' (Maximum table size reached)'
	if not result.complete:
		message += ' (' + result.status + '; total incomplete)'
	return message


class Collector:
	def __init__(self, options):
		self.options = options
		self.rows = []
		self.total = self.text_bytes = 0
		self.limited = False

	def accept(self, raw):
		relative = raw.decode('utf-8', errors='strict')
		if relative.startswith('./'):
			relative = relative[2:]
		if not relative or '\x00' in relative or ntpath.splitdrive(relative)[0] or relative.startswith(('/', '\\')) or '..' in relative.replace('\\', '/').split('/') or ':' in relative:
			raise ValueError('Invalid fd result path.')
		root = os.path.normpath(self.options.root)
		path = os.path.normpath(os.path.join(root, relative))
		if os.path.commonpath((root, path)) != root or path == root:
			raise ValueError('fd result escapes the captured root.')
		relative = os.path.relpath(path, root).replace(os.sep, '/')
		self.total += 1
		size = len(path.encode('utf-8')) + len(relative.encode('utf-8')) + 256
		if self.limited or len(self.rows) >= self.options.max_rows or self.text_bytes + size > self.options.max_text_bytes:
			self.limited = True
			return
		self.rows.append(Hit(path, relative))
		self.text_bytes += size


class Cancelled(Exception):
	pass


class Child:
	def __init__(self, runner):
		self.runner = runner
		self.tail = bytearray()
		command = arguments(runner.options)
		with runner.lock:
			runner.check()
			self.process = subprocess.Popen(command, cwd=runner.options.root, shell=False, bufsize=0,
				stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
				creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
			runner.child = self
		self.reader = Thread(target=self.read_errors, daemon=True)
		self.reader.start()

	def read_errors(self):
		try:
			while chunk := self.process.stderr.read(CHUNK_BYTES):
				self.tail.extend(chunk)
				del self.tail[:-STDERR_BYTES]
		finally:
			self.process.stderr.close()

	def kill(self):
		try:
			self.process.kill()
		except OSError:
			pass

	def finish(self):
		self.kill()
		code = self.process.wait()
		self.reader.join()
		self.process.stdout.close()
		with self.runner.lock:
			self.runner.child = None
		return code, bytes(self.tail).decode('utf-8', errors='replace')


class Runner:
	def __init__(self, options, cancelled=None):
		self.options, self.cancelled = options, cancelled
		self.stopped = Event()
		self.lock = Lock()
		self.child = None
		self.collector = Collector(options)
		self.started = monotonic()
		self.progress = Progress('Searching')

	def start(self, completed):
		from fman.ui import settings_resource
		release = settings_resource('FindFiles runner').try_claim()
		if release is None:
			return False
		def operation():
			try:
				result = self.run()
			finally:
				release()
			completed(result)
		try:
			Thread(target=operation, name='find-files', daemon=True).start()
		except Exception:
			release()
			raise
		return True

	def stop(self):
		self.stopped.set()
		with self.lock:
			if self.child is not None:
				self.child.kill()

	def check(self):
		if self.stopped.is_set() or self.cancelled is not None and self.cancelled.is_set():
			raise Cancelled()

	def publish(self, phase='Searching'):
		self.progress = Progress(phase, self.collector.total, len(self.collector.rows), monotonic() - self.started)

	def enrich(self):
		self.collector.rows.sort(key=lambda hit: (hit.relative_path.casefold(), hit.relative_path))
		for index, hit in enumerate(self.collector.rows):
			self.check()
			try:
				try:
					info = os.stat(hit.path, follow_symlinks=self.options.follow_symlinks)
				except FileNotFoundError:
					info = os.stat(hit.path, follow_symlinks=False)
				modified = datetime.fromtimestamp(info.st_mtime).strftime('%Y-%m-%d %H:%M')
				self.collector.rows[index] = replace(hit, size=None if stat.S_ISDIR(info.st_mode) else info.st_size, modified=modified)
			except (OSError, ValueError, OverflowError):
				pass
			self.publish('Reading metadata')

	def run(self):
		complete, status, reason = False, 'Complete', ''
		try:
			self.check()
			if not os.path.isdir(self.options.root):
				raise ValueError('Root: directory is missing or inaccessible.')
			child = Child(self)
			try:
				for record in records(child.process.stdout):
					self.check()
					self.collector.accept(record)
					self.publish()
				code = child.process.wait()
			finally:
				finished_code, errors = child.finish()
			self.check()
			if code or finished_code:
				raise OSError(errors or 'fd exited with code %d.' % code)
			if errors:
				status, reason = 'Incomplete', errors
			elif self.options.max_results is not None and self.collector.total >= self.options.max_results:
				status = 'Search limit reached'
			else:
				complete = True
			self.enrich()
			self.check()
		except Cancelled:
			complete, status = False, 'Stopped'
		except Exception as error:
			complete, status, reason = False, 'Error', str(error)
		finally:
			self.publish(status)
		rows = tuple(sorted(self.collector.rows, key=lambda hit: (hit.relative_path.casefold(), hit.relative_path)))
		self.collector.rows.clear()
		return Result(rows, self.collector.total, complete, self.collector.limited, status, reason[:STDERR_BYTES])