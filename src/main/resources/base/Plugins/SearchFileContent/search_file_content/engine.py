import base64
from dataclasses import dataclass
from functools import cached_property
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic


CHUNK_BYTES = 65536
RECORD_BYTES = 1024 * 1024
STDERR_BYTES = 65536
COMMAND_UNITS = 24000


@dataclass(frozen=True, slots=True)
class Options:
	root: str
	content: str
	name: str = ''
	name_regex: bool = False
	content_regex: bool = False
	recursive: bool = True
	encoding: str = 'auto'
	max_rows: int = 10000
	max_text_bytes: int = 16 * 1024 * 1024
	max_file_lines: int = 200
	max_file_bytes: int = 50 * 1024 * 1024
	name_mode: str | None = None
	content_mode: str | None = None

	def __post_init__(self):
		for name in ('root', 'content', 'name'):
			value = getattr(self, name)
			if not isinstance(value, str) or '\x00' in value or len(value) > 32768:
				raise ValueError('Invalid %s.' % name)
		if not self.content or '\n' in self.content or '\r' in self.content:
			raise ValueError('Content Pattern is required and must be a single line.')
		if '\n' in self.name or '\r' in self.name:
			raise ValueError('File Name Pattern must be a single line.')
		if not os.path.isabs(self.root):
			raise ValueError('Search requires an absolute local directory.')
		for name in ('name_regex', 'content_regex', 'recursive'):
			if type(getattr(self, name)) is not bool:
				raise ValueError('%s must be boolean.' % name)
		for name, legacy, default in (('name_mode', self.name_regex, 'glob'), ('content_mode', self.content_regex, 'literal')):
			mode = getattr(self, name)
			if mode is None:
				mode = 'regex' if legacy else default
			if mode not in ('literal', 'glob', 'regex'):
				raise ValueError('%s must be literal, glob or regex.' % name)
			object.__setattr__(self, name, mode)
		for name, ceiling in (('max_rows', 10000), ('max_text_bytes', 16 * 1024 * 1024),
				('max_file_lines', 200), ('max_file_bytes', 50 * 1024 * 1024)):
			if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= ceiling:
				raise ValueError('Invalid %s limit.' % name)
		if self.encoding not in ('auto', 'windows-1252'):
			raise ValueError('Encoding must be auto or windows-1252.')


@dataclass(frozen=True, slots=True)
class Hit:
	path: str
	relative_path: str
	line: int
	column: int
	offset: int
	snippet: str
	spans: tuple


@dataclass(frozen=True, slots=True)
class Progress:
	phase: str
	lines: int = 0
	files: int = 0
	skipped: int = 0
	elapsed: float = 0


@dataclass(frozen=True, slots=True)
class Result:
	rows: tuple
	status: str
	reason: str
	progress: Progress
	validated: bool = False


class Cancelled(Exception):
	pass


class Limited(Exception):
	pass


def masks(pattern):
	positive, negative = [], []
	for part in pattern.split(';'):
		part = part.strip()
		if not part:
			continue
		if '/' in part or '\\' in part or part == '!':
			raise ValueError('File Name Pattern accepts basename masks only.')
		(negative if part.startswith('!') else positive).append(part)
	return tuple(positive + negative)


def command_fits(arguments):
	return len(subprocess.list2cmdline(arguments).encode('utf-16-le')) // 2 <= COMMAND_UNITS


def glob_to_regex(pattern):
	if any(char in pattern for char in ('\x00', '\r', '\n')):
		raise ValueError('Content glob must be a single line without NUL.')
	parts, position = [], 0
	while position < len(pattern):
		char = pattern[position]
		position += 1
		if char == '*':
			if not parts or parts[-1] != '.*':
				parts.append('.*')
		elif char == '?':
			parts.append('.')
		elif char == '[':
			negated = pattern[position:position + 1] == '!'
			position += negated
			start = position
			if pattern[position:position + 1] == ']':
				position += 1
			end = pattern.find(']', position)
			if end < 0 or end == start:
				raise ValueError('Content glob has an unclosed or empty character set.')
			members = []
			position = start
			while position < end:
				if position + 2 < end and pattern[position + 1] == '-' and pattern[position] != '-' and pattern[position + 2] != '-':
					first, last = pattern[position], pattern[position + 2]
					if first > last:
						raise ValueError('Content glob has a reversed character range.')
					members.append(re.escape(first) + '-' + re.escape(last))
					position += 3
				else:
					members.append(re.escape(pattern[position]))
					position += 1
			parts.append('[' + ('^' if negated else '') + ''.join(members) + ']')
			position = end + 1
		else:
			parts.append(re.escape(char))
	return ''.join(parts)


def resolve_engine():
	if getattr(sys, 'frozen', False):
		return str(Path(__file__).parent.parent / 'bin' / 'rg.exe')
	return str(Path(sys.prefix) / 'bin' / 'rg.exe')


def data_bytes(value):
	if not isinstance(value, dict):
		raise ValueError('Invalid ripgrep string record.')
	if 'text' in value:
		return value['text'].encode('utf-8')
	return base64.b64decode(value['bytes'], validate=True)


def records(stream, delimiter=b'\n', maximum=RECORD_BYTES):
	buffer = bytearray()
	while True:
		chunk = stream.read(CHUNK_BYTES)
		if not chunk:
			break
		buffer.extend(chunk)
		while True:
			end = buffer.find(delimiter)
			if end < 0:
				break
			if end > maximum:
				raise ValueError('Search transport record exceeds its size limit.')
			record = bytes(buffer[:end])
			del buffer[:end + len(delimiter)]
			yield record
		if len(buffer) > maximum:
			raise ValueError('Search transport record exceeds its size limit.')
	if buffer:
		raise ValueError('Incomplete search transport record.')


def make_hit(root, record):
	path = os.fsdecode(data_bytes(record['path']))
	if not os.path.isabs(path):
		path = os.path.join(root, path)
	path = os.path.normpath(path)
	if os.path.commonpath((root, path)) != os.path.normpath(root):
		raise ValueError('Search result is outside the captured root.')
	raw = data_bytes(record['lines'])
	content = raw.decode('utf-8', errors='replace').rstrip('\r\n')
	spans = []
	for match in record['submatches'][:128]:
		start, end = match['start'], match['end']
		if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(raw):
			raise ValueError('Invalid match offsets.')
		spans.append((len(raw[:start].decode('utf-8', errors='replace')),
			len(raw[:end].decode('utf-8', errors='replace'))))
	first = spans[0][0] if spans else 0
	start = max(0, first - 96)
	end = min(len(content), start + 506)
	prefix = '...' if start else ''
	snippet = prefix + content[start:end] + ('...' if end < len(content) else '')
	highlights = tuple((max(begin, start) - start + len(prefix), min(finish, end) - start + len(prefix))
		for begin, finish in spans if begin <= end and finish >= start)
	line, offset = record['line_number'], record['absolute_offset']
	if type(line) is not int or line < 1 or type(offset) is not int or offset < 0:
		raise ValueError('Invalid matching line metadata.')
	return Hit(path, os.path.relpath(path, root), line, first + 1, offset, snippet, highlights)


class Collector:
	def __init__(self, options):
		self.options = options
		self.rows = []
		self.pending = {}
		self.text_bytes = 0
		self.row_count = 0
		self.files = 0
		self.limited = ''

	def accept(self, message):
		kind, data = message['type'], message['data']
		if kind not in ('begin', 'match', 'end', 'summary', 'context'):
			raise ValueError('Unknown ripgrep record type.')
		if kind not in ('begin', 'match', 'end'):
			return
		path = data_bytes(data['path'])
		if kind == 'begin':
			if path in self.pending or len(self.pending) >= 2:
				raise ValueError('Unexpected concurrent file records.')
			self.pending[path] = []
		elif kind == 'match':
			if path not in self.pending:
				raise ValueError('Match without file begin record.')
			hit = make_hit(self.options.root, data)
			size = 72 + sum(len(value.encode('utf-8')) for value in (hit.path, hit.path, hit.relative_path, hit.snippet))
			if self.row_count >= self.options.max_rows or self.text_bytes + size > self.options.max_text_bytes:
				raise Limited('Result row/text limit reached.')
			self.row_count += 1
			self.text_bytes += size
			self.pending[path].append((hit, size))
			if len(self.pending[path]) > self.options.max_file_lines:
				raise Limited('Per-file matching-line limit exceeded.')
		elif kind == 'end':
			items = self.pending.pop(path)
			if data.get('binary_offset') is not None:
				self.row_count -= len(items)
				self.text_bytes -= sum(size for hit, size in items)
			else:
				self.rows.extend(hit for hit, size in items)
				self.files += bool(items)
				if len(items) >= self.options.max_file_lines:
					self.limited = 'Per-file matching-line limit reached; coverage may be incomplete.'
				if len(self.rows) >= self.options.max_rows:
					raise Limited('Result row limit reached; coverage may be incomplete.')


class Child:
	def __init__(self, runner, arguments, input_data):
		if not command_fits(arguments):
			raise ValueError('Search command exceeds 24,000 UTF-16 units.')
		self.runner = runner
		self.tail = bytearray()
		self.input_error = None
		self.writer = None
		with runner.lock:
			runner.check()
			self.process = subprocess.Popen(arguments, shell=False, bufsize=0,
				stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
				stdout=subprocess.PIPE, stderr=subprocess.PIPE,
				creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
			runner.children.add(self)
		self.reader = Thread(target=self.read_errors, daemon=True)
		self.reader.start()
		if input_data is not None:
			self.writer = Thread(target=self.write_input, args=(input_data,), daemon=True)
			self.writer.start()

	def read_errors(self):
		try:
			while chunk := self.process.stderr.read(CHUNK_BYTES):
				self.tail.extend(chunk)
				del self.tail[:-STDERR_BYTES]
		finally:
			self.process.stderr.close()

	def write_input(self, data):
		try:
			view = memoryview(data)
			while view:
				written = self.process.stdin.write(view[:CHUNK_BYTES])
				if not written:
					raise OSError('Search input pipe closed.')
				view = view[written:]
		except OSError as error:
			self.input_error = error
		finally:
			self.process.stdin.close()

	def kill(self):
		try:
			self.process.kill()
		except OSError:
			pass

	def finish(self, kill=False):
		if kill:
			self.kill()
		code = self.process.wait()
		self.reader.join()
		if self.writer is not None:
			self.writer.join()
		self.process.stdout.close()
		with self.runner.lock:
			self.runner.children.discard(self)
		return code, bytes(self.tail).decode('utf-8', errors='replace')


class Runner:
	def __init__(self, options, cancelled=None):
		self.options = options
		self.cancelled = cancelled
		self.stopped = Event()
		self.lock = Lock()
		self.children = set()
		self.collector = Collector(options)
		self.started = monotonic()
		self.progress = Progress('Validating')
		self.skipped = 0
		self.error = ''
		self.engine = None

	def start(self, completed):
		from fman.ui import settings_resource
		release = settings_resource('SearchFileContent runner').try_claim()
		if release is None:
			return False
		def operation():
			try:
				result = self.run()
			finally:
				release()
			completed(result)
		try:
			Thread(target=operation, name='content-search', daemon=True).start()
		except Exception:
			release()
			raise
		return True

	def stop(self):
		self.stopped.set()
		with self.lock:
			for child in tuple(self.children):
				child.kill()

	def check(self):
		if self.stopped.is_set() or self.cancelled is not None and self.cancelled.is_set():
			raise Cancelled()

	def publish(self, phase='Searching'):
		self.progress = Progress(phase, len(self.collector.rows), self.collector.files,
			self.skipped, monotonic() - self.started)

	@cached_property
	def content_pattern(self):
		return glob_to_regex(self.options.content) if self.options.content_mode == 'glob' else self.options.content

	def content_args(self):
		options = self.options
		arguments = [self.engine, '--no-config', '--no-ignore', '--no-follow', '--no-mmap',
			'--json', '--line-buffered', '--line-number', '--crlf', '--ignore-case',
			'--threads', '2', '--max-count', str(options.max_file_lines),
			'--max-filesize', str(options.max_file_bytes), '--encoding', options.encoding]
		if options.content_mode == 'literal':
			arguments.append('--fixed-strings')
		elif options.content_mode == 'glob':
			arguments.append('--line-regexp')
		arguments.extend(('-e', self.content_pattern))
		return arguments

	def read_child(self, arguments, consume, input_data=None):
		child = Child(self, arguments, input_data)
		try:
			for record in records(child.process.stdout):
				self.check()
				consume(json.loads(record))
				self.publish()
		except BaseException:
			child.finish(kill=True)
			raise
		code, errors = child.finish()
		self.check()
		if code not in (0, 1):
			raise OSError(errors or 'ripgrep exited with code %d.' % code)
		if child.input_error is not None:
			raise child.input_error
		if errors:
			self.error = errors

	def preflight(self):
		self.check()
		self.engine = resolve_engine()
		info = os.stat(self.options.root, follow_symlinks=False)
		if not stat.S_ISDIR(info.st_mode):
			raise ValueError('Search root is missing or not a directory.')
		if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
			raise ValueError('Search root must not be a symlink or junction.')
		arguments = self.content_args()
		if self.options.name_mode == 'glob':
			for pattern in masks(self.options.name):
				arguments.extend(('--iglob', pattern))
			final_arguments = arguments + ([] if self.options.recursive else ['--max-depth', '1']) + ['--', self.options.root]
			if not command_fits(final_arguments):
				raise ValueError('Search command exceeds 24,000 UTF-16 units.')
		self.read_child(arguments + ['--', '-'], lambda message: None, b'')
		if self.options.name_mode != 'glob' and self.options.name:
			self.read_child(self.name_args(), lambda message: None, b'')

	def name_args(self):
		return [self.engine, '--no-config', '--null-data', '--json', '--line-number',
			'--ignore-case'] + (['--fixed-strings'] if self.options.name_mode == 'literal' else []) + [
			'-e', self.options.name, '--', '-']

	def eligible(self, path):
		root = os.path.normpath(self.options.root)
		path = os.path.normpath(path)
		if os.path.commonpath((root, path)) != root:
			raise ValueError('Enumerated path escapes the search root.')
		current = path
		while True:
			self.check()
			info = os.stat(current, follow_symlinks=False)
			attributes = getattr(info, 'st_file_attributes', 0)
			if stat.S_ISLNK(info.st_mode) or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024):
				return False
			if current != root and (os.path.basename(current).startswith('.') or attributes & getattr(stat, 'FILE_ATTRIBUTE_HIDDEN', 2)):
				return False
			if current == path and (not stat.S_ISREG(info.st_mode) or info.st_size > self.options.max_file_bytes):
				return False
			if current == root:
				return True
			current = os.path.dirname(current)

	def search_batch(self, paths):
		accepted = set()
		if self.options.name:
			def collect(message):
				if message['type'] == 'match':
					index = message['data']['line_number'] - 1
					if not 0 <= index < len(paths):
						raise ValueError('Invalid filename input record number.')
					accepted.add(index)
			payload = b''.join(os.path.basename(path).encode('utf-8') + b'\x00' for path in paths)
			self.read_child(self.name_args(), collect, payload)
		else:
			accepted.update(range(len(paths)))
		arguments = self.content_args() + ['--max-depth', '0', '--']
		batch = []
		for index, path in enumerate(paths):
			self.check()
			if index not in accepted:
				continue
			try:
				if not self.eligible(path):
					self.skipped += 1
					continue
			except OSError as error:
				self.skipped += 1
				self.error = str(error)
				continue
			if batch and not command_fits(arguments + batch + [path]):
				self.read_child(arguments + batch, self.collector.accept)
				batch = []
			if not command_fits(arguments + [path]):
				self.error = 'A file path exceeds the command-line limit: ' + path
				self.skipped += 1
			else:
				batch.append(path)
		if batch:
			self.read_child(arguments + batch, self.collector.accept)

	def search_filtered_names(self):
		arguments = [self.engine, '--files', '--null', '--no-config', '--no-ignore', '--no-follow']
		if not self.options.recursive:
			arguments.extend(('--max-depth', '1'))
		child = Child(self, arguments + ['--', self.options.root], None)
		try:
			batch, size = [], 0
			for record in records(child.process.stdout, b'\x00', 131072):
				self.check()
				if batch and (len(batch) >= 128 or size + len(record) > 256 * 1024):
					self.search_batch(batch)
					batch, size = [], 0
				batch.append(os.fsdecode(record))
				size += len(record)
			if batch:
				self.search_batch(batch)
		except BaseException:
			child.finish(kill=True)
			raise
		code, errors = child.finish()
		if code not in (0, 1) or errors:
			self.error = errors or 'File enumeration failed.'

	def run(self):
		status, reason = 'Complete', ''
		validated = False
		try:
			self.preflight()
			validated = True
			self.check()
			if self.options.name_mode != 'glob':
				self.search_filtered_names()
			else:
				arguments = self.content_args()
				for pattern in masks(self.options.name):
					arguments.extend(('--iglob', pattern))
				if not self.options.recursive:
					arguments.extend(('--max-depth', '1'))
				self.read_child(arguments + ['--', self.options.root], self.collector.accept)
			self.check()
			if self.error:
				status, reason = 'Incomplete', self.error
			elif self.collector.limited:
				status, reason = 'Limited', self.collector.limited
		except Cancelled:
			status, reason = 'Stopped', 'Search stopped; collected text-file matches only.'
		except Limited as error:
			status, reason = 'Limited', str(error)
		except Exception as error:
			status, reason = 'Error', str(error)
		finally:
			for child in tuple(self.children):
				child.finish(kill=True)
			self.collector.pending.clear()
			self.publish(status)
		rows = tuple(self.collector.rows)
		self.collector.rows.clear()
		return Result(rows, status, reason[:STDERR_BYTES], self.progress, validated)