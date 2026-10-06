from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import ntpath
import os
import re
import stat
from string import Formatter

from fman.ui import QuickTableColumn, QuickTableRow
from fman.url import as_human_readable, as_url, splitscheme


CHECK, CROSS = '\u2713', '\u2717'
MAX_FILES = 25000
MAX_PREVIEW_BYTES = 16 * 1024 * 1024
DEFAULT_TEMPLATE = '{name}{ext}'
REPARSE_NAME_SURROGATE = 0x20000000
COLUMNS = (
	QuickTableColumn('Index', 'numeric', sortable=False, filterable=False, missing=''),
	QuickTableColumn('File Index', 'numeric'),
	QuickTableColumn('Original Name', 'file_name'),
	QuickTableColumn('File Date', 'date', date_display='date'),
	QuickTableColumn('New Name', 'file_name', sortable=False, filterable=False),
	QuickTableColumn('Valid Name', sortable=False, filterable=False),
)


def natural_key(name):
	parts = []
	for part in re.split(r'([0-9]+)', name.casefold()):
		parts.append((1, int(part)) if part.isascii() and part.isdecimal() else (0, part))
	return tuple(parts), name


def bounded_text(value, limit):
	if len(value.encode('utf-8')) <= limit:
		return value
	return value.encode('utf-8')[:limit - 3].decode('utf-8', errors='ignore') + '...'


def display_name(value, limit=768):
	value = ''.join('\\u%04x' % ord(char) if ord(char) < 32 or 0xd800 <= ord(char) <= 0xdfff else char for char in value)
	return value if limit is None else bounded_text(value, limit)


def identity(metadata):
	return metadata.st_dev, metadata.st_ino, getattr(metadata, 'st_birthtime_ns', metadata.st_ctime_ns)


def is_link(metadata):
	return bool(stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_reparse_tag', 0) & REPARSE_NAME_SURROGATE or
		(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1))


@dataclass(frozen=True, slots=True)
class Source:
	url: str
	path: str
	name: str
	file_index: int
	identity: tuple
	size: int
	mtime_ns: int
	date: datetime


@dataclass(frozen=True, slots=True)
class Capture:
	parent: str
	parent_identity: tuple
	sources: tuple
	occupied: frozenset
	current_date: datetime


def capture(urls, check=lambda: None):
	urls = tuple(urls)
	if not 1 <= len(urls) <= MAX_FILES or len(set(urls)) != len(urls):
		raise ValueError('Choose between 1 and {:,} distinct files.'.format(MAX_FILES))
	paths = []
	for url in urls:
		check()
		if splitscheme(url)[0] != 'file://':
			raise ValueError('Batch File Renamer supports local-drive files only.')
		path = os.path.abspath(as_human_readable(url))
		drive = ntpath.splitdrive(path)[0]
		if len(drive) != 2 or drive[1] != ':':
			raise ValueError('UNC and virtual locations are not supported.')
		paths.append(path)
	parent = os.path.dirname(paths[0])
	if any(os.path.normcase(os.path.dirname(path)) != os.path.normcase(parent) for path in paths):
		raise ValueError('Choose files in one folder.')
	parent_stat = os.lstat(parent)
	if is_link(parent_stat):
		raise ValueError('Open the actual folder and select files, not links or junctions.')
	if not parent_stat.st_ino or not parent_stat.st_dev:
		raise ValueError('The parent folder must have a stable local identity.')
	current_date = datetime.now().astimezone()
	occupied, regular = [], []
	with os.scandir(parent) as entries:
		for entry in entries:
			check()
			occupied.append(entry.name.casefold())
			metadata = entry.stat(follow_symlinks=False)
			if stat.S_ISREG(metadata.st_mode) and not is_link(metadata):
				regular.append(entry.name)
	indices = {name: index for index, name in enumerate(sorted(regular, key=natural_key))}
	sources = []
	for url, path in zip(urls, paths):
		check()
		metadata = os.lstat(path)
		name = os.path.basename(path)
		if is_link(metadata):
			raise ValueError('Select actual files, not links or junctions: ' + display_name(name))
		if (not stat.S_ISREG(metadata.st_mode) or
				not metadata.st_dev or not metadata.st_ino or name not in indices):
			raise ValueError('Select regular files with stable identity: ' + display_name(name))
		sources.append(Source(url, path, name, indices[name], identity(metadata), metadata.st_size,
			metadata.st_mtime_ns, datetime.fromtimestamp(metadata.st_mtime_ns / 1e9).astimezone()))
	return Capture(parent, identity(parent_stat), tuple(sorted(sources, key=lambda source: source.file_index)),
		frozenset(occupied), current_date)


def parse(template):
	if not isinstance(template, str) or len(template.encode('utf-16-le', 'surrogatepass')) > 8192 or any(char in template for char in '\0\r\n'):
		raise ValueError('Use one line of at most 4,096 UTF-16 units.')
	result = []
	for literal, field, specification, conversion in Formatter().parse(template):
		offset = 0
		if field is not None:
			if conversion is not None or '{' in specification or '}' in specification:
				raise ValueError('Conversions and nested replacement fields are not supported.')
			if field not in ('name', 'ext', 'current_date', 'file_date', 'index', 'file_index'):
				expression = field.strip(' \t')
				if expression.startswith('(') and expression.endswith(')'):
					expression = expression[1:-1].strip(' \t')
				match = re.fullmatch(r'(index|file_index)[ \t]*\+[ \t]*([0-9]{1,255})', expression)
				if match is None or int(match[2]) <= 0:
					raise ValueError('Use a named variable or index/file_index + a positive integer.')
				field, offset = match[1], int(match[2])
			if field in ('index', 'file_index'):
				if specification not in ('', 'd') and (re.fullmatch(r'0?[1-9][0-9]?d', specification) is None or not 1 <= int(specification[:-1]) <= 32):
					raise ValueError('Index width must be 1-32, for example 03d.')
			elif field in ('current_date', 'file_date'):
				specification = specification or '%Y-%m-%d'
				if len(specification) > 128 or re.search(r'%(?:[^YymdHMS%]|$)', specification.replace('%%', '')):
					raise ValueError('Date formats allow %Y, %y, %m, %d, %H, %M, %S and %%.')
			elif specification:
				raise ValueError('Name and extension do not accept format specifications.')
		result.append((literal, field, specification, offset))
	return tuple(result)


def render(parts, values):
	length, byte_count, full = 0, 0, []
	for literal, field, specification, offset in parts:
		chunks = [literal]
		if field is not None:
			value = values[field] + offset if field in ('index', 'file_index') else values[field]
			chunks.append(format(value, specification))
		for chunk in chunks:
			length += len(chunk.encode('utf-16-le', 'surrogatepass')) // 2
			byte_count += len(chunk.encode('utf-8', errors='backslashreplace'))
			if byte_count > MAX_PREVIEW_BYTES:
				raise ValueError('Preview exceeds the 16 MiB limit. Reduce the template or candidate set; nothing will be renamed.')
			full.append(chunk)
	value = ''.join(full)
	if length > 255:
		return None, display_name(value, None), 'Name too long: %d UTF-16 units' % length
	if (not value or value in ('.', '..') or any(ord(char) < 32 or 0xd800 <= ord(char) <= 0xdfff or char in '<>:"/\\|?*' for char in value)
			or value.endswith((' ', '.')) or ntpath.isreserved(value)):
		return None, display_name(value, None), 'Invalid Windows name'
	return value, value, None


@dataclass(frozen=True, slots=True)
class Candidate:
	source: Source
	index: int | None
	target: str | None
	display: str
	problem: str | None


def plan(captured, template, mapping):
	parts = parse(template)
	if not isinstance(mapping, tuple) or len(mapping) != len(captured.sources):
		raise ValueError('Invalid row mapping.')
	visible = [position for position in mapping if position is not None]
	if any(type(position) is not int for position in visible) or sorted(visible) != list(range(len(visible))):
		raise ValueError('Visible positions must be unique and consecutive.')
	entries = []
	preview_bytes = 0
	for source, index in zip(captured.sources, mapping):
		preview_bytes += len(display_name(source.name, None).encode('utf-8')) + 64 + 10 + 24 + 5 + 25
		if index is None:
			if preview_bytes > MAX_PREVIEW_BYTES:
				raise ValueError('Preview exceeds the 16 MiB limit. Select fewer candidates; nothing will be renamed.')
			entries.append(Candidate(source, None, None, '', None))
			continue
		name, extension = os.path.splitext(source.name)
		values = dict(name=name, ext=extension, index=index, file_index=source.file_index,
			current_date=captured.current_date, file_date=source.date)
		target, display, problem = render(parts, values)
		preview_bytes += len(display.encode('utf-8'))
		if preview_bytes > MAX_PREVIEW_BYTES:
			raise ValueError('Preview exceeds the 16 MiB limit. Reduce the template or candidate set; nothing will be renamed.')
		if target is not None and len(os.path.join(captured.parent, target)) > 32760:
			problem = 'Destination path is too long'
		entries.append(Candidate(source, index, target, display, problem))
	counts = Counter(entry.target.casefold() for entry in entries if entry.index is not None and entry.target is not None)
	result = []
	for entry in entries:
		problem = entry.problem
		if entry.index is not None and entry.target is not None and problem is None:
			if counts[entry.target.casefold()] > 1:
				problem = 'Duplicate target'
			elif entry.target != entry.source.name and entry.target.casefold() == entry.source.name.casefold():
				problem = 'Case-only rename unsupported' if entry.target.isascii() and entry.source.name.isascii() else 'Conflicts ignoring case'
			elif entry.target != entry.source.name and entry.target.casefold() in captured.occupied:
				problem = 'Target exists'
		result.append(Candidate(entry.source, entry.index, entry.target, entry.display, problem))
	return tuple(result)


def preview(captured, template, mapping, *, with_status=False):
	parse(template)
	entries = plan(captured, template, mapping) if mapping is not None else tuple(
		Candidate(source, None, None, '', None) for source in captured.sources)
	rows = tuple(QuickTableRow((entry.index, entry.source.file_index, display_name(entry.source.name, None),
		entry.source.mtime_ns, entry.display, '' if entry.index is None else bounded_text(
			CROSS + ' ' + entry.problem if entry.problem else CHECK + (' Unchanged' if entry.target == entry.source.name else ' Ready'), 64)))
		for entry in entries)
	if not with_status:
		return rows
	if mapping is None:
		return rows, None
	invalid = sum(entry.problem is not None for entry in entries if entry.index is not None)
	changed = sum(entry.index is not None and entry.target != entry.source.name for entry in entries)
	status = ('Rename blocked: %d invalid or conflicting names.' % invalid) if invalid else \
		('%d files ready to rename.' % changed if changed else 'No files need renaming.')
	return rows, status


def preflight(captured, entries, check=lambda: None):
	if any(entry.problem for entry in entries if entry.index is not None):
		raise ValueError('The visible preview contains invalid names. Nothing was renamed.')
	if identity(os.lstat(captured.parent)) != captured.parent_identity:
		raise ValueError('The parent folder changed. Start a fresh rename.')
	for entry in entries:
		check()
		if entry.index is None:
			continue
		verify_source(entry.source)
		if entry.target == entry.source.name:
			continue
		try:
			os.lstat(os.path.join(captured.parent, entry.target))
		except FileNotFoundError:
			pass
		else:
			raise FileExistsError('Target exists (possibly a short-name alias): ' + entry.target)


def verify_source(source):
	metadata = os.lstat(source.path)
	if is_link(metadata):
		raise ValueError('Select actual files, not links or junctions: ' + display_name(source.name))
	if (identity(metadata) != source.identity or metadata.st_size != source.size or metadata.st_mtime_ns != source.mtime_ns or
			not stat.S_ISREG(metadata.st_mode)):
		raise ValueError('Source changed; start a fresh rename: ' + display_name(source.name))


def execute(captured, entries, rename, check=lambda: None, progress=lambda value: None):
	from fman import Task
	if any(entry.problem or entry.target is None for entry in entries if entry.index is not None):
		raise ValueError('Invalid active rename plan; nothing was renamed.')
	report = {entry.source.url: (entry.source.name, entry.source.name,
		'Excluded by filter' if entry.index is None else 'Unchanged' if entry.target == entry.source.name else 'Unattempted') for entry in entries}
	confirmed = []
	active = sorted((entry for entry in entries if entry.index is not None), key=lambda entry: entry.index)
	for position, entry in enumerate(active):
		committed = False
		try:
			check()
			if entry.target == entry.source.name:
				progress(position + 1)
				continue
			if entry.problem or entry.target is None:
				raise ValueError('Invalid active rename plan')
			verify_source(entry.source)
			result = rename(entry.source.url, as_url(os.path.join(captured.parent, entry.target)))
			committed = True
			confirmed.append(result.destination_url)
			report[entry.source.url] = (entry.source.name, entry.target,
				'Renamed; refresh warning: ' + '; '.join(result.notification_warnings) if result.notification_warnings else 'Renamed')
			progress(position + 1)
			if result.notification_warnings:
				break
		except Task.Canceled:
			break
		except Exception as error:
			report[entry.source.url] = (entry.source.name, entry.target if committed else entry.source.name,
				('Renamed; reporting warning: ' if committed else 'Failed: ') + str(error))
			break
	return tuple(report[entry.source.url] for entry in entries), tuple(confirmed)