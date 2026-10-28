"""QuickView CSV/TSV helper. Runs DuckDB in a child process; imports neither fman nor Qt."""

import csv
import io
import json
import os
import queue
import shutil
import stat
import sys
import threading
import uuid

from _quick_view_pdf_worker import (
	MAX_HEADER, PdfError, binary_stream, decode_header, encode_frame, read_exact
)


IDENTITY = ('epoch', 'generation', 'operation', 'revision')
COMMANDS = ('open', 'query', 'page', 'copy', 'cell', 'find', 'release', 'cancel', 'close')
DELIMITERS = {'comma': ',', 'semicolon': ';', 'tab': '\t', 'pipe': '|'}
ENCODINGS = ('auto', 'utf-8', 'utf-16', 'latin-1')
HEADERS = ('auto', 'yes', 'no')
MAX_COLUMNS = 256
FIELD_CHARS = 1048576
RECORD_CHARS = 4194304
MAX_LINE_BYTES = 16 * 1024 * 1024
# Twice the line limit: a 64 MiB buffer could not be allocated within a 128 MiB memory limit.
BUFFER_BYTES = 32 * 1024 * 1024
PREVIEW_ROWS = 200
PAGE_ROWS = 100
DISPLAY_CHARS = 512
FRAME_BYTES = 4 * 1024 * 1024
COPY_BYTES = 8 * 1024 * 1024
SAMPLE_BYTES = 256 * 1024
FREE_RESERVE = 64 * 1024 * 1024
MiB = 1024 * 1024
# Upper bound of UTF-8 text fetched into Python per batch; rows are batched by their byte-size class.
FETCH_BYTES = 4 * MiB
FOLD_BUCKETS = ((-1, 4096), (4096, 65536), (65536, MiB), (MiB, 4 * FIELD_CHARS))
# Casefolding can triple a field's code points and CSV quoting doubles quotes.
FOLD_LINE_BYTES = 2 * FIELD_CHARS * 4 * 3 + 64
PARSE_HINT = (' Table View follows DuckDB\'s strict CSV rules; for example, a field that starts with " '
	'must be a complete quoted field.')


class CsvError(ValueError):
	"""A user-facing failure; `kind` is 'parse', 'encoding', 'limit', 'resource', 'access' or 'query'."""

	def __init__(self, message, kind='parse'):
		super().__init__(message)
		self.kind = kind


class Canceled(Exception):
	pass


def cache_quota(size):
	return min(8 * 1024 ** 3, max(16 * MiB, 2 * size))


def fingerprint(info):
	return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def fold_pattern(query):
	"""LIKE pattern equal to QuickTable's fuzzy subsequence test on casefolded text."""
	parts = ['%']
	for character in query.casefold():
		parts.append(character.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_'))
		parts.append('%')
	return ''.join(parts)


def quote_tsv(value):
	if any(character in value for character in '\t\r\n"'):
		return '"' + value.replace('"', '""') + '"'
	return value


def recover_abandoned(root, minimum_age=60):
	"""Delete owned session folders left by crashed helpers; live ones hold open files and cannot be renamed."""
	import time
	try:
		entries = list(os.scandir(root))
	except OSError:
		return
	for entry in entries:
		if not entry.name.startswith('s-') or not entry.is_dir(follow_symlinks=False) or entry.is_symlink():
			continue
		try:
			if time.time() - entry.stat(follow_symlinks=False).st_mtime < minimum_age:
				continue
			trash = entry.path + '.deleting'
			os.rename(entry.path, trash)
		except OSError:
			continue
		shutil.rmtree(trash, ignore_errors=True)


def directory_size(path):
	total = 0
	for root, folders, files in os.walk(path):
		for name in files:
			try:
				total += os.stat(os.path.join(root, name)).st_size
			except OSError:
				pass
	return total


def _literal(value):
	return "'" + value.replace("'", "''") + "'"


def _tsv_bytes(name):
	"""SQL for the UTF-8 size of `quote_tsv(name)`."""
	return (("(strlen({0}) + CASE WHEN strpos({0}, chr(9)) > 0 OR strpos({0}, chr(10)) > 0 OR strpos({0}, chr(13)) > 0 "
		"OR strpos({0}, '\"') > 0 THEN 2 + strlen({0}) - strlen(replace({0}, '\"', '')) ELSE 0 END)").format(name))


def labels(values):
	"""Display labels: empty labels get their position, duplicates a numeric suffix."""
	result, seen = [], set()
	for index, value in enumerate(values):
		label = value or 'Column %d' % (index + 1)
		candidate, suffix = label, 2
		while candidate.casefold() in seen:
			candidate = '%s (%d)' % (label, suffix)
			suffix += 1
		seen.add(candidate.casefold())
		result.append(candidate)
	return result


class _Limited(io.RawIOBase):
	def __init__(self, stream, limit):
		self.stream, self.remaining = stream, limit

	def readable(self):
		return True

	def readinto(self, buffer):
		if self.remaining <= 0:
			raise CsvError('The first record exceeds the 16 MiB Table View line limit.', 'limit')
		data = self.stream.read(min(len(buffer), self.remaining))
		self.remaining -= len(data)
		buffer[:len(data)] = data
		return len(data)


def sample_line(path, encoding):
	"""First physical line of the bounded detection sample, for a delimiter plausibility check."""
	codec = {'utf-8': 'utf-8-sig', 'utf-16': 'utf-16', 'latin-1': 'latin-1'}[encoding]
	with open(path, 'rb') as stream:
		sample = stream.read(SAMPLE_BYTES)
	text = sample.decode(codec, errors='ignore')
	return text.replace('\r\n', '\n').replace('\r', '\n').split('\n', 1)[0]


def first_record(path, encoding, delimiter):
	"""Fields of the first nonblank record; it defines the column count for the strict import."""
	csv.field_size_limit(FIELD_CHARS)
	codec = {'utf-8': 'utf-8-sig', 'utf-16': 'utf-16', 'latin-1': 'latin-1'}[encoding]
	with open(path, 'rb') as raw:
		text = io.TextIOWrapper(io.BufferedReader(_Limited(raw, MAX_LINE_BYTES + 4)), encoding=codec, errors='strict', newline='')
		try:
			for row in csv.reader(text, delimiter=delimiter, quotechar='"', doublequote=True, strict=True):
				if row:
					if encoding == 'latin-1' and any('\x80' <= character <= '\x9f' for value in row for character in value):
						raise CsvError('The file is not Latin-1 text (it contains C1 control bytes, for example Windows-1252 '
							'quotes or currency signs).', 'encoding')
					return row
		except UnicodeError as error:
			raise CsvError('The first record is not valid %s text: %s' % (encoding.upper(), error.reason), 'encoding') from None
		except csv.Error as error:
			raise CsvError('Cannot parse the first record: %s' % error) from None
	return None


def detect_encoding(path, requested):
	with open(path, 'rb') as stream:
		head = stream.read(4)
	if head.startswith(b'\xef\xbb\xbf'):
		if requested not in ('auto', 'utf-8'):
			raise CsvError('The file starts with a UTF-8 byte order mark; choose UTF-8 or Auto.', 'encoding')
		return 'utf-8'
	if head.startswith(b'\xfe\xff'):
		raise CsvError('UTF-16 big-endian is not supported by Table View.', 'encoding')
	if head.startswith(b'\xff\xfe'):
		if head.startswith(b'\xff\xfe\x00\x00'):
			raise CsvError('UTF-32 is not supported by Table View.', 'encoding')
		if requested not in ('auto', 'utf-16'):
			raise CsvError('The file starts with a UTF-16 byte order mark; choose UTF-16 or Auto.', 'encoding')
		return 'utf-16'
	if requested == 'utf-16':
		raise CsvError('UTF-16 Table View requires a little-endian byte order mark.', 'encoding')
	return 'utf-8' if requested == 'auto' else requested


def describe(error):
	text = str(error).strip()
	lines = [line.strip() for line in text.splitlines() if line.strip()]
	message = lines[0] if lines else type(error).__name__
	for line in lines[1:]:
		if line.lower().startswith(('original line', 'possible fixes', '*')):
			break
		if len(message) < 300:
			message += ' ' + line
	# The sniffer's list of tried options does not help the user.
	message = message.split(' The search space used was', 1)[0]
	return message[:512]


def classify(error):
	text = describe(error)
	lowered = text.lower()
	if 'out of memory' in lowered or ('disk' in lowered and 'space' in lowered):
		return 'resource'
	# The sniffer lists its encoding among the options it tried.
	if 'parsing dialect' in lowered:
		return 'parse'
	if 'not latin-1 encoded' in lowered or 'unicode' in lowered or 'encoding' in lowered:
		return 'encoding'
	if 'maximum line size' in lowered or 'max_line_size' in lowered:
		return 'limit'
	return 'parse'


class Engine:
	def __init__(self, root):
		self.root = root
		self.connection = None
		self.directory = None
		self.path = None
		self.info = None
		self.columns = ()
		self.count = 0
		self.folded = set()
		self.projection = None
		self.quota = 0
		self.read_options = ''
		self.operation = None
		self.canceled = None
		self.recovered = False
		self._interrupted = threading.Event()
		self._resource_error = None
		self._lock = threading.Lock()

	# -- lifecycle -----------------------------------------------------------------------

	def release(self):
		with self._lock:
			connection, self.connection = self.connection, None
		if connection is not None:
			try:
				connection.close()
			except Exception:
				pass
		if self.directory is not None:
			shutil.rmtree(self.directory, ignore_errors=True)
		self.directory = self.path = self.info = None
		self.columns = ()
		self.count = 0
		self.folded = set()
		self.projection = None

	def begin(self, operation):
		with self._lock:
			self.operation = operation
			self._resource_error = None
			if self.canceled == operation:
				self._interrupted.set()
			else:
				self._interrupted.clear()

	def interrupt(self, operation=None):
		with self._lock:
			if operation is not None:
				self.canceled = operation
				if operation != self.operation:
					return
			self._interrupted.set()
			connection = self.connection
		if connection is not None:
			try:
				connection.interrupt()
			except Exception:
				pass

	def check(self):
		if self._interrupted.is_set():
			raise Canceled()

	def _failure(self, error, kind=None):
		if self._interrupted.is_set() or type(error).__name__ == 'InterruptException':
			return Canceled()
		kind = kind or classify(error)
		return CsvError(describe(error) + (PARSE_HINT if kind == 'parse' else ''), kind)

	def _space_problem(self):
		if self.directory is None:
			return None
		if directory_size(self.directory) > self.quota:
			return 'Table View cache quota exceeded (%s allowed). Choose a smaller file or free disk space.' % _bytes(self.quota)
		try:
			free = shutil.disk_usage(self.directory).free
		except OSError:
			return None
		if free < FREE_RESERVE // 2:
			return 'The disk is almost full (%s free); Table View stopped.' % _bytes(free)
		return None

	def check_space(self):
		problem = self._space_problem()
		if problem:
			raise CsvError(problem, 'resource')

	def _limit_spill(self):
		"""Give DuckDB's spill only the quota not already used by the database and other owned files."""
		temporary = os.path.join(self.directory, 'tmp')
		remaining = self.quota - directory_size(self.directory) + directory_size(temporary)
		self.connection.execute("SET max_temp_directory_size='%d bytes'" % max(MiB, remaining))

	def _run(self, work):
		"""Run `work` within the cache quota: checked before and after, with spill limited and a 200 ms watcher."""
		if self.directory is not None:
			self.check_space()
			if self.connection is not None:
				self._limit_spill()
		done = threading.Event()
		def watch():
			while not done.wait(.2):
				problem = self._space_problem()
				if problem:
					self._resource_error = problem
					self.interrupt()
					return
		watcher = threading.Thread(target=watch, daemon=True)
		watcher.start()
		try:
			result = work()
		except Exception as error:
			if self._resource_error is not None:
				raise CsvError(self._resource_error, 'resource') from None
			if self._interrupted.is_set() or type(error).__name__ == 'InterruptException':
				raise Canceled() from None
			raise
		finally:
			done.set()
			watcher.join()
		if self._resource_error is not None:
			raise CsvError(self._resource_error, 'resource')
		self.check_space()
		return result

	# -- open/import ---------------------------------------------------------------------

	def open(self, path, limit, memory_mib, options, emit, directory=None):
		try:
			return self._open(path, limit, memory_mib, options, emit, directory)
		except BaseException:
			self.release()
			raise

	def _open(self, path, limit, memory_mib, options, emit, directory):
		import duckdb
		self.release()
		if not isinstance(path, str) or not os.path.isabs(path):
			raise CsvError('Invalid path', 'access')
		try:
			info = os.stat(path)
		except OSError as error:
			raise CsvError('Cannot read file: %s' % (error.strerror or error), 'access') from None
		if not stat.S_ISREG(info.st_mode):
			raise CsvError('Not a regular file', 'access')
		if info.st_size > limit:
			raise CsvError('File exceeds the %s Table View limit.' % _bytes(limit, decimal=True), 'limit')
		self.info, self.path = info, path
		self.quota = cache_quota(info.st_size)
		os.makedirs(self.root, exist_ok=True)
		if not self.recovered:
			self.recovered = True
			recover_abandoned(self.root)
		free = shutil.disk_usage(self.root).free
		if free < self.quota + FREE_RESERVE:
			raise CsvError('Not enough free space for the Table View cache: %s required, %s available.' % (
				_bytes(self.quota + FREE_RESERVE), _bytes(free)), 'resource')
		if directory is None:
			directory = os.path.join(self.root, 's-%d-%s' % (os.getpid(), uuid.uuid4().hex[:12]))
		elif (not isinstance(directory, str) or os.path.normcase(os.path.dirname(directory)) != os.path.normcase(self.root)
				or not os.path.basename(directory).startswith('s-') or os.path.lexists(directory)):
			raise CsvError('Invalid cache folder', 'access')
		self.directory = directory
		os.makedirs(os.path.join(self.directory, 'tmp'))
		encoding = detect_encoding(path, options.get('encoding', 'auto'))
		connection = duckdb.connect(os.path.join(self.directory, 'table.duckdb'), config={
			'memory_limit': '%dMiB' % memory_mib, 'threads': 1,
			'temp_directory': os.path.join(self.directory, 'tmp'),
			'max_temp_directory_size': '%dMiB' % max(1, self.quota // MiB),
			'autoinstall_known_extensions': False, 'autoload_known_extensions': False,
			'preserve_insertion_order': False})
		with self._lock:
			self.connection = connection
		for statement in ('SET allowed_paths=[%s]' % _literal(path),
				'SET allowed_directories=[%s]' % _literal(self.directory + os.sep),
				'SET enable_external_access=false'):
			connection.execute(statement)
		self.check()
		delimiter, header = self._dialect(path, encoding, options)
		self.check()
		width, labels = self._shape(path, encoding, delimiter, header)
		self.columns = tuple('c%d' % index for index in range(width))
		self.read_options = ', '.join((
			'delim=%s' % _literal(delimiter), "quote='\"'", "escape='\"'", 'header=%s' % ('true' if header else 'false'),
			'auto_detect=false', 'columns={%s}' % ', '.join("'%s': 'VARCHAR'" % name for name in self.columns),
			'strict_mode=true', 'allow_quoted_nulls=false', 'null_padding=false', 'ignore_errors=false',
			'force_not_null=[%s]' % ', '.join(_literal(name) for name in self.columns),
			'max_line_size=%d' % MAX_LINE_BYTES, 'buffer_size=%d' % BUFFER_BYTES, 'encoding=%s' % _literal(encoding)))
		source = 'read_csv(%s, %s) WITH ORDINALITY' % (_literal(path), self.read_options)
		names = ', '.join(self.columns)
		bad = ' OR '.join('strpos(%s, chr(0)) > 0 OR length(%s) > %d' % (name, name, FIELD_CHARS) for name in self.columns)
		def convert(item):
			if item[1]:
				raise CsvError('Record %d contains NUL characters or exceeds the Table View field limit.' % item[0], 'limit')
			return self._display_row(item[0], item[2:])
		def preview():
			result = connection.execute('SELECT ordinality, %s, %s FROM %s LIMIT %d' % (
				bad, self._display_columns(self.columns), source, PREVIEW_ROWS))
			return self._collect(result, convert)
		try:
			rows = self._run(preview)
		except (Canceled, CsvError):
			raise
		except Exception as error:
			raise self._failure(error) from None
		emit('preview', {'labels': labels, 'delimiter': delimiter, 'encoding': encoding, 'header': header,
			'fingerprint': list(fingerprint(info)), 'quota': self.quota, 'directory': self.directory},
			{'rows': rows})
		def load():
			connection.execute('CREATE TABLE data AS SELECT ordinality AS rid, %s FROM %s' % (names, source))
			self.check()
			checks = ' OR '.join(['strpos(%s, chr(0)) > 0 OR length(%s) > %d' % (name, name, FIELD_CHARS) for name in self.columns] +
				['(%s) > %d' % (' + '.join('length(%s)' % name for name in self.columns), RECORD_CHARS - width + 1)])
			bad = connection.execute('SELECT min(rid) FROM data WHERE ' + checks).fetchone()[0]
			if bad is not None:
				raise CsvError('Record %d contains NUL characters or exceeds the Table View field/record limits.' % bad, 'limit')
			return connection.execute('SELECT count(*) FROM data').fetchone()[0]
		try:
			self.count = self._run(load)
		except (Canceled, CsvError):
			raise
		except Exception as error:
			raise self._failure(error) from None
		connection.execute('SET preserve_insertion_order=true')
		if fingerprint(os.stat(path)) != fingerprint(info):
			raise CsvError('File changed while loading', 'access')
		self.projection = None
		return {'count': self.count}

	def _dialect(self, path, encoding, options):
		delimiter = DELIMITERS.get(options.get('delimiter', 'auto'))
		header = {'yes': True, 'no': False}.get(options.get('header', 'auto'))
		if delimiter is None and path.lower().endswith('.tsv'):
			delimiter = '\t'
		if delimiter is not None and header is not None:
			return delimiter, header
		arguments = ['sample_size=2048', 'encoding=%s' % _literal(encoding), "quote='\"'", "escape='\"'", 'strict_mode=true',
			'max_line_size=%d' % MAX_LINE_BYTES, 'buffer_size=%d' % BUFFER_BYTES]
		if delimiter is not None:
			arguments.append('delim=%s' % _literal(delimiter))
		try:
			sniffed = self.connection.execute('SELECT Delimiter, HasHeader FROM sniff_csv(%s, %s)' % (
				_literal(path), ', '.join(arguments))).fetchone()
		except Exception as error:
			failure = self._failure(error)
			if isinstance(failure, CsvError):
				failure = CsvError('Cannot detect the table format: ' + str(failure), failure.kind)
			raise failure from None
		found = sniffed[0] if delimiter is None else delimiter
		if found not in DELIMITERS.values():
			raise CsvError('Cannot detect a comma, semicolon, tab or pipe delimiter; choose one explicitly.')
		if delimiter is None:
			first_line = sample_line(path, encoding)
			if found not in first_line and any(candidate in first_line for candidate in DELIMITERS.values()):
				raise CsvError('The delimiter could not be detected consistently; the file may be malformed. '
					'Choose a delimiter explicitly.')
		return found, sniffed[1] if header is None else header

	def _shape(self, path, encoding, delimiter, header):
		first = first_record(path, encoding, delimiter)
		width = len(first) if first is not None else 1
		if width > MAX_COLUMNS:
			raise CsvError('Table View supports at most %d columns; this file has %d.' % (MAX_COLUMNS, width), 'limit')
		if first is None or not header:
			return width, ['Column %d' % (index + 1) for index in range(width)]
		return width, labels(first)

	@staticmethod
	def _display_columns(names):
		"""Elide natively so a display row never fetches more than DISPLAY_CHARS per cell."""
		return ', '.join('left(%s, %d), length(%s) > %d' % (name, DISPLAY_CHARS, name, DISPLAY_CHARS) for name in names)

	@staticmethod
	def _display_row(rid, values):
		return [rid, list(values[0::2]), [index for index, elided in enumerate(values[1::2]) if elided]]

	def _collect(self, result, convert):
		"""Fetch display rows in byte-bounded batches until the frame budget is reached."""
		batch = max(1, FETCH_BYTES // (len(self.columns) * DISPLAY_CHARS * 4))
		rows, size = [], 0
		while True:
			self.check()
			items = result.fetchmany(batch)
			if not items:
				return rows
			for item in items:
				row = convert(item)
				size += sum(len(cell) for cell in row[1]) * 3 + 32
				if rows and size > FRAME_BYTES:
					return rows
				rows.append(row)

	# -- queries -------------------------------------------------------------------------

	def _require(self):
		if self.connection is None:
			raise CsvError('No table is open', 'query')

	def prepare_folds(self, columns):
		"""Store Python-casefolded copies of `columns`; ASCII natively, other values in Python once."""
		self._require()
		for index in sorted(set(columns) - self.folded):
			self.check()
			folded = 'f%d' % index
			staging = os.path.join(self.directory, 'fold-%d.csv' % index)
			try:
				self._run(lambda: self._fold(self.columns[index], folded, staging))
			except BaseException:
				try:
					self.connection.execute('ALTER TABLE data DROP COLUMN IF EXISTS %s' % folded)
				except Exception:
					pass
				raise
			finally:
				try:
					os.remove(staging)
				except OSError:
					pass
			self.folded.add(index)

	def _fold(self, name, folded, staging):
		connection = self.connection
		# A canceled earlier attempt may have left a partial column behind.
		connection.execute('ALTER TABLE data DROP COLUMN IF EXISTS %s' % folded)
		connection.execute('ALTER TABLE data ADD COLUMN %s VARCHAR' % folded)
		connection.execute('UPDATE data SET %s = lower(%s) WHERE strlen(%s) = length(%s)' % (folded, name, name, name))
		self.check()
		base = directory_size(self.directory)
		reader = connection.cursor()
		written = 0
		try:
			counts = reader.execute('SELECT %s FROM data WHERE %s IS NULL' % (', '.join(
				'count(*) FILTER (WHERE strlen(%s) > %d AND strlen(%s) <= %d)' % (name, low, name, high)
				for low, high in FOLD_BUCKETS), folded)).fetchone()
			with open(staging, 'w', encoding='utf-8', newline='') as stream:
				writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator='\n')
				for (low, high), count in zip(FOLD_BUCKETS, counts):
					if not count:
						continue
					result = reader.execute('SELECT rid, %s FROM data WHERE %s IS NULL AND strlen(%s) > %d AND strlen(%s) <= %d' % (
						name, folded, name, low, name, high))
					while True:
						self.check()
						batch = result.fetchmany(max(1, FETCH_BYTES // high))
						if not batch:
							break
						for rid, value in batch:
							writer.writerow((rid, value.casefold()))
							written += 1
						if base + stream.tell() > self.quota:
							raise CsvError('Table View cache quota exceeded while preparing filters.', 'resource')
		finally:
			reader.close()
		if written:
			connection.execute(("UPDATE data SET %s = s.f FROM read_csv(%s, delim=',', quote='\"', escape='\"', "
				"header=false, auto_detect=false, columns={'rid': 'BIGINT', 'f': 'VARCHAR'}, strict_mode=true, "
				"allow_quoted_nulls=false, force_not_null=['f'], max_line_size=%d, buffer_size=%d) s "
				"WHERE data.rid = s.rid") % (folded, _literal(staging), FOLD_LINE_BYTES, FOLD_LINE_BYTES + MiB))

	def query(self, filters, text, sort):
		"""Build the whole-file projection for column `filters`, global Contains `text` and `sort`."""
		self._require()
		filters = tuple(self._check_filter(item) for item in filters or ())
		if not isinstance(text, str):
			raise CsvError('Invalid filter text', 'query')
		if sort is not None and (not isinstance(sort, list) or len(sort) != 2 or type(sort[0]) is not int or
				not 0 <= sort[0] < len(self.columns) or type(sort[1]) is not bool):
			raise CsvError('Invalid sort', 'query')
		needed = {column for column, operator, value in filters}
		if text:
			needed.update(range(len(self.columns)))
		if sort is not None:
			needed.add(sort[0])
		self.prepare_folds(needed)
		conditions, parameters = [], []
		for column, operator, value in filters:
			if operator == 'substring':
				conditions.append('contains(f%d, ?)' % column)
				parameters.append(value.casefold())
			else:
				conditions.append("f%d LIKE ? ESCAPE '\\'" % column)
				parameters.append(fold_pattern(value))
		if text:
			conditions.append('(%s)' % ' OR '.join('contains(f%d, ?)' % index for index in range(len(self.columns))))
			parameters.extend([text.casefold()] * len(self.columns))
		if not conditions and sort is None:
			self.projection = None
			return {'count': self.count, 'folded': sorted(self.folded)}
		order = 'rid' if sort is None else 'f%d %s, rid' % (sort[0], 'DESC' if sort[1] else 'ASC')
		where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
		connection = self.connection
		def build():
			connection.execute('DROP TABLE IF EXISTS proj_next')
			connection.execute('CREATE TABLE proj_next AS SELECT (row_number() OVER (ORDER BY %s) - 1)::BIGINT AS pos, rid '
				'FROM data%s ORDER BY pos' % (order, where), parameters)
			self.check()
			self.check_space()
			connection.execute('DROP TABLE IF EXISTS proj')
			connection.execute('ALTER TABLE proj_next RENAME TO proj')
			return connection.execute('SELECT count(*) FROM proj').fetchone()[0]
		try:
			count = self._run(build)
		except (Canceled, CsvError):
			raise
		except Exception as error:
			raise CsvError(describe(error), 'resource' if classify(error) == 'resource' else 'query') from None
		self.projection = count
		return {'count': count, 'folded': sorted(self.folded)}

	def _check_filter(self, item):
		if (not isinstance(item, list) or len(item) != 3 or type(item[0]) is not int or
				not 0 <= item[0] < len(self.columns) or item[1] not in ('fuzzy', 'substring') or not isinstance(item[2], str)):
			raise CsvError('Invalid filter', 'query')
		value = item[2].strip()
		if not value:
			raise CsvError('Enter text to filter.', 'query')
		return item[0], item[1], value

	@property
	def size(self):
		return self.count if self.projection is None else self.projection

	def _range(self):
		"""Position expression, source with position bounds as parameters, and order for the current projection."""
		if self.projection is None:
			return 'd.rid - 1', 'data d WHERE d.rid > ? AND d.rid <= ?', 'd.rid'
		return 'p.pos', 'proj p JOIN data d ON d.rid = p.rid WHERE p.pos >= ? AND p.pos < ?', 'p.pos'

	def _rows(self, start, end, columns=None):
		"""Yield (position, rid, values) for projection positions start..end-1."""
		names = ['d.' + self.columns[index] for index in (range(len(self.columns)) if columns is None else columns)]
		position, source, order = self._range()
		cursor = self.connection.cursor()
		try:
			result = cursor.execute('SELECT %s, d.rid, %s FROM %s ORDER BY %s' % (position, ', '.join(names), source, order), [start, end])
			while True:
				self.check()
				batch = result.fetchmany(1024)
				if not batch:
					return
				for row in batch:
					yield row[0], row[1], row[2:]
		finally:
			cursor.close()

	def page(self, start, count):
		self._require()
		if type(start) is not int or type(count) is not int or start < 0 or not 0 < count <= 1000:
			raise CsvError('Invalid page request', 'query')
		position, source, order = self._range()
		sql = 'SELECT %s, d.rid, %s FROM %s ORDER BY %s' % (
			position, self._display_columns(['d.' + name for name in self.columns]), source, order)
		def fetch():
			cursor = self.connection.cursor()
			try:
				result = cursor.execute(sql, [start, min(self.size, start + count)])
				return self._collect(result, lambda item: self._display_row(item[1], item[2:]))
			finally:
				cursor.close()
		rows = self._run(fetch)
		return {'start': start, 'count': len(rows)}, {'rows': rows}

	def copy(self, rows, columns, headers, labels):
		self._require()
		if (not isinstance(rows, list) or len(rows) != 2 or not isinstance(columns, list) or not columns or
				any(type(value) is not int for value in rows + columns) or not 0 <= rows[0] < rows[1] <= self.size or
				any(not 0 <= value < len(self.columns) for value in columns)):
			raise CsvError('Invalid copy range', 'query')
		parts, size = [], 0
		if headers:
			line = '\t'.join(quote_tsv(labels[index] if isinstance(labels, list) and index < len(labels) else '') for index in columns)
			parts.append(line)
			size += len(line.encode('utf-8')) + 2
		_, source, _ = self._range()
		measure = 'SELECT coalesce(sum(%s + %d), 0) FROM %s' % (
			' + '.join(_tsv_bytes('d.' + self.columns[index]) for index in columns), len(columns) + 1, source)
		def collect():
			nonlocal size
			# Measure natively first so a refused copy never fetches the values.
			if size + self.connection.execute(measure, rows).fetchone()[0] > COPY_BYTES:
				raise CsvError('The selection exceeds the 8 MiB clipboard limit; nothing was copied.', 'query')
			for position, rid, values in self._rows(rows[0], rows[1], columns):
				line = '\t'.join(quote_tsv(value) for value in values)
				size += len(line.encode('utf-8')) + 2
				if size > COPY_BYTES:
					raise CsvError('The selection exceeds the 8 MiB clipboard limit; nothing was copied.', 'query')
				parts.append(line)
		self._run(collect)
		return {}, {'text': '\r\n'.join(parts)}

	def cell(self, position, column):
		self._require()
		if type(position) is not int or type(column) is not int or not 0 <= position < self.size or not 0 <= column < len(self.columns):
			raise CsvError('Invalid cell', 'query')
		values = self._run(lambda: [values for _, _, values in self._rows(position, position + 1, [column])])
		if not values:
			raise CsvError('Row is no longer available', 'query')
		return {'position': position, 'column': column}, {'text': values[0][0]}

	def find(self, text, column, case, position, current, backwards):
		self._require()
		if (not isinstance(text, str) or not text or type(case) is not bool or type(backwards) is not bool or
				type(position) is not int or type(current) is not int or
				(column is not None and (type(column) is not int or not 0 <= column < len(self.columns)))):
			raise CsvError('Invalid find request', 'query')
		columns = list(range(len(self.columns))) if column is None else [column]
		if not case:
			self.prepare_folds(columns)
		needle = text if case else text.casefold()
		def matches(values):
			return [index for index, value in zip(columns, values) if needle in (value if case else value.casefold())]
		size = self.size
		if not size:
			return {'position': -1, 'column': -1, 'wrapped': False}, b''
		position = max(0, min(position, size - 1))
		names = ['c%d' % index if case else 'f%d' % index for index in columns]
		test = '(%s)' % ' OR '.join('contains(%s, ?)' % name for name in names)
		parameters = [needle] * len(names)
		def search():
			current_row = list(self._rows(position, position + 1, columns))
			if current_row:
				found = [index for index in matches(current_row[0][2]) if (index < current if backwards else index > current)]
				if found:
					return position, (found[-1] if backwards else found[0]), False
			for wrapped in (False, True):
				if self.projection is None:
					bounds = ('rid - 1 < ?' if backwards else 'rid - 1 > ?') if not wrapped else ('rid - 1 >= ?' if backwards else 'rid - 1 <= ?')
					sql = 'SELECT rid - 1 FROM data WHERE %s AND %s ORDER BY rid %s LIMIT 1' % (
						bounds, test, 'DESC' if backwards else 'ASC')
				else:
					bounds = ('p.pos < ?' if backwards else 'p.pos > ?') if not wrapped else ('p.pos >= ?' if backwards else 'p.pos <= ?')
					sql = 'SELECT p.pos FROM proj p JOIN data d ON d.rid = p.rid WHERE %s AND %s ORDER BY p.pos %s LIMIT 1' % (
						bounds, test.replace('contains(', 'contains(d.'), 'DESC' if backwards else 'ASC')
				row = self.connection.execute(sql, [position] + parameters).fetchone()
				self.check()
				if row is not None:
					values = list(self._rows(row[0], row[0] + 1, columns))[0][2]
					found = matches(values)
					return row[0], (found[-1] if backwards else found[0]), wrapped
			return -1, -1, False
		found_position, found_column, wrapped = self._run(search)
		return {'position': found_position, 'column': found_column, 'wrapped': wrapped}, b''


def _bytes(value, decimal=False):
	if decimal:
		return '{:,} MB'.format(value // 1000000) if value % 1000000 == 0 else '{:,} bytes'.format(value)
	for unit, size in (('GiB', 1024 ** 3), ('MiB', MiB), ('KiB', 1024)):
		if value >= size:
			return '%.1f %s' % (value / size, unit)
	return '%d bytes' % value


def read_command(stream):
	import struct
	length = struct.unpack('<I', read_exact(stream, 4))[0]
	if not 0 < length <= MAX_HEADER:
		raise PdfError('Invalid CSV helper header length')
	header = decode_header(read_exact(stream, length))
	if header['length'] or header.get('type') not in COMMANDS:
		raise PdfError('Invalid CSV helper command')
	if any(type(header.get(key)) is not int or header[key] < 0 for key in IDENTITY):
		raise PdfError('Invalid CSV helper operation identity')
	return header


def main(root=None):
	reader = binary_stream('stdin', -10, 'rb')
	writer = binary_stream('stdout', -11, 'wb')
	commands = queue.Queue()
	engine = Engine(root)
	write_lock = threading.Lock()
	def send(header, payload=None):
		data = b'' if payload is None else payload if isinstance(payload, bytes) else \
			json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
		with write_lock:
			writer.write(encode_frame(header, data))
			writer.flush()
	def receive():
		try:
			while True:
				command = read_command(reader)
				if command['type'] == 'cancel':
					engine.interrupt(command['operation'])
				else:
					commands.put(command)
		except (EOFError, OSError, PdfError):
			commands.put(None)
	threading.Thread(target=receive, name='csv-commands', daemon=True).start()
	send({'type': 'ready'})
	try:
		while True:
			command = commands.get()
			if command is None or command['type'] == 'close':
				return 0
			identity = {key: command[key] for key in IDENTITY}
			kind = command['type']
			engine.begin(command['operation'])
			try:
				engine.check()
				if kind == 'open':
					if engine.root is None:
						engine.root = command.get('cache')
					if not isinstance(engine.root, str) or not os.path.isabs(engine.root):
						raise CsvError('Invalid cache folder', 'access')
					options = command.get('options') if isinstance(command.get('options'), dict) else {}
					result = engine.open(command.get('path'), command.get('limit'), command.get('memory'), options,
						lambda name, header, payload: send(dict(identity, type=name, **header), payload), command.get('directory'))
					send(dict(identity, type='imported', **result))
				elif kind == 'query':
					send(dict(identity, type='projection', **engine.query(command.get('filters'), command.get('text', ''), command.get('sort'))))
				elif kind == 'page':
					header, payload = engine.page(command.get('start'), command.get('count', PAGE_ROWS))
					send(dict(identity, type='page', **header), payload)
				elif kind == 'copy':
					header, payload = engine.copy(command.get('rows'), command.get('columns'), command.get('headers') is True, command.get('labels'))
					# Raw UTF-8: JSON would expand control characters up to six times past the frame limit.
					send(dict(identity, type='copy', **header), payload['text'].encode('utf-8'))
				elif kind == 'cell':
					header, payload = engine.cell(command.get('position'), command.get('column'))
					send(dict(identity, type='cell', **header), payload)
				elif kind == 'find':
					header, _ = engine.find(command.get('text'), command.get('column'), command.get('case') is True,
						command.get('position', 0), command.get('current', -1), command.get('backwards') is True)
					send(dict(identity, type='found', **header))
				elif kind == 'release':
					engine.release()
					send(dict(identity, type='released'))
			except Canceled:
				send(dict(identity, type='error', kind='canceled', message='Canceled'))
			except CsvError as error:
				if kind == 'open':
					engine.release()
				send(dict(identity, type='error', kind=error.kind, message=str(error)[:1024]))
			except MemoryError:
				if kind == 'open':
					engine.release()
				send(dict(identity, type='error', kind='resource', message='Table View ran out of memory'))
			except Exception as error:
				if kind == 'open':
					engine.release()
				send(dict(identity, type='error', kind='resource' if classify(error) == 'resource' else
					('parse' if kind == 'open' else 'query'), message=describe(error)))
			finally:
				engine.begin(None)
	finally:
		engine.release()


if __name__ == '__main__':
	sys.exit(main())
