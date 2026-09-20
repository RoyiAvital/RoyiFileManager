from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from itertools import islice
import ntpath


MAX_ROWS = 10000
MAX_TEXT_BYTES = 16 * 1024 * 1024


def text(value, name, limit=None):
	if not isinstance(value, str):
		raise TypeError('%s must be a string.' % name)
	if '\x00' in value or (limit is not None and len(value) > limit):
		raise ValueError('%s contains NUL or exceeds its length limit.' % name)
	return value


@dataclass(frozen=True, slots=True)
class TableRow:
	id: str
	cells: tuple
	value: object = None
	highlights: tuple = ()

	def __post_init__(self):
		if not text(self.id, 'Row ID', 4096):
			raise ValueError('Row IDs must not be empty.')
		if not isinstance(self.cells, (tuple, list)):
			raise TypeError('Row cells must be a sequence of strings.')
		object.__setattr__(self, 'cells', tuple(self.cells))
		object.__setattr__(self, 'highlights', tuple(
			tuple(tuple(span) for span in column) for column in self.highlights))


@dataclass(frozen=True, slots=True)
class TableAction:
	id: str
	label: str
	callback: object


@dataclass(frozen=True, slots=True)
class TextField:
	id: str
	label: str
	value: str = ''
	tooltip: str = ''
	max_width: int | None = None


@dataclass(frozen=True, slots=True)
class Toggle:
	id: str
	icon: str
	label: str
	value: bool = False
	tooltip: str = ''


@dataclass(frozen=True, slots=True)
class Choice:
	id: str
	label: str
	options: tuple
	value: str
	tooltip: str = ''

	def __post_init__(self):
		if not isinstance(self.options, (tuple, list)) or not 2 <= len(self.options) <= 8:
			raise ValueError('Choice requires 2-8 options.')
		if any(not isinstance(option, (tuple, list)) or len(option) != 3 for option in self.options):
			raise TypeError('Choice options must be (value, icon, tooltip) triples.')
		object.__setattr__(self, 'options', tuple(tuple(option) for option in self.options))


@dataclass(frozen=True, slots=True)
class Select:
	id: str
	label: str
	options: tuple
	value: str
	tooltip: str = ''

	def __post_init__(self):
		if not isinstance(self.options, (tuple, list)) or not 1 <= len(self.options) <= 128:
			raise ValueError('Select requires 1-128 options.')
		if any(not isinstance(option, (tuple, list)) or len(option) != 2 for option in self.options):
			raise TypeError('Select options must be (value, label) pairs.')
		object.__setattr__(self, 'options', tuple(tuple(option) for option in self.options))


@dataclass(frozen=True, slots=True)
class DateField:
	id: str
	label: str
	value: str | None = None
	tooltip: str = ''


@dataclass(frozen=True, slots=True)
class IntegerField:
	id: str
	label: str
	value: int | None = None
	minimum: int = 0
	maximum: int = 18446744073709551615
	tooltip: str = ''


def validate_field_value(record, value):
	if isinstance(record, Select):
		if not isinstance(value, str) or value not in tuple(option[0] for option in record.options):
			raise ValueError('Unknown selection: ' + record.id)
	elif isinstance(record, DateField) and value is not None:
		if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value or value < '1752-09-14':
			raise ValueError('Date must be an ISO calendar date from 1752-09-14: ' + record.id)
	elif isinstance(record, IntegerField) and value is not None:
		if type(value) is not int or not record.minimum <= value <= record.maximum:
			raise ValueError('Integer outside allowed range: ' + record.id)


@dataclass(frozen=True, slots=True)
class Separator:
	id: str


@dataclass(frozen=True, slots=True)
class Label:
	id: str
	text: str
	icon: str | None = None
	tooltip: str = ''


@dataclass(frozen=True, slots=True)
class Action:
	id: str
	label: str
	icon: object = None
	tooltip: str = ''


class TableSchema:
	def __init__(self, num_columns, columns_header, file_path_column=None,
			folder_path_column=None, resolve_path=None, base_path=None, entry_path_column=None):
		if type(num_columns) is not int:
			raise TypeError('num_columns must be an integer.')
		if num_columns <= 0:
			raise ValueError('num_columns must be positive.')
		if isinstance(columns_header, str) or not isinstance(columns_header, Sequence):
			raise TypeError('columns_header must be a sequence of strings.')
		if len(columns_header) != num_columns:
			raise ValueError('columns_header must contain num_columns labels.')
		self.headers = tuple(text(label, 'Column header', 128) for label in columns_header)
		if not all(self.headers):
			raise ValueError('Column headers must not be empty.')
		self.num_columns = num_columns
		self.roles = {}
		for column, role in ((file_path_column, 'file'), (folder_path_column, 'folder'), (entry_path_column, 'entry')):
			if column is None:
				continue
			if type(column) is not int:
				raise TypeError('Path column indices must be integers or None.')
			if not 0 <= column < num_columns or column in self.roles:
				raise ValueError('Path columns must be distinct and within the column range.')
			self.roles[column] = role
		if resolve_path is not None and not callable(resolve_path):
			raise TypeError('resolve_path must be callable or None.')
		self.resolver = resolve_path
		self.base = absolute_path(base_path) if base_path is not None else None

	def target(self, row, column):
		if column not in self.roles:
			return None
		if self.resolver is not None:
			result = self.resolver(row, column)
			return None if result is None else absolute_path(result)
		value = text(row.cells[column], 'Path')
		if not value:
			return None
		drive, tail = ntpath.splitdrive(value)
		if drive or tail.startswith(('\\', '/')):
			return absolute_path(value)
		if ':' in value:
			raise ValueError('Expected a native Windows path, not a URL.')
		return ntpath.normpath(ntpath.join(self.base, value)) if self.base else None

	def snapshot(self, provider):
		if not callable(provider):
			raise TypeError('get_rows must be callable.')
		rows, ids, seen = [], set(), set()
		size = 0
		for row in provider():
			if len(rows) >= MAX_ROWS:
				raise ValueError('Table exceeds the 10,000-row limit.')
			if not isinstance(row, TableRow):
				raise TypeError('get_rows must yield TableRow records.')
			if row.id in ids or len(row.cells) != self.num_columns:
				raise ValueError('Duplicate row ID or incorrect cell count.')
			for cell in row.cells:
				text(cell, 'Cell')
			if row.highlights:
				if len(row.highlights) != self.num_columns:
					raise ValueError('Highlights must have one entry per column.')
				for cell, spans in zip(row.cells, row.highlights):
					if len(spans) > 128:
						raise ValueError('Too many highlight spans.')
					for span in spans:
						if len(span) != 2 or any(type(value) is not int for value in span):
							raise TypeError('Highlight spans must contain two integers.')
						if not 0 <= span[0] <= span[1] <= len(cell):
							raise ValueError('Highlight outside cell text.')
			size += plain_size(row, seen)
			if size > MAX_TEXT_BYTES:
				raise ValueError('Table exceeds the 16 MiB text/payload limit.')
			ids.add(row.id)
			rows.append(row)
		return tuple(rows)


def absolute_path(value):
	text(value, 'Path')
	drive, tail = ntpath.splitdrive(value)
	if not value or not drive or not (tail.startswith(('\\', '/')) or
			(drive.startswith(('\\\\', '//')) and not tail)):
		raise ValueError('Expected an absolute Windows drive or UNC path.')
	if ':' in tail or (':' in drive and not (len(drive) == 2 and drive[1] == ':')):
		raise ValueError('Expected a native Windows path, not a URL or stream.')
	return ntpath.normpath(value)


def plain_size(value, seen=None, depth=0):
	if seen is None:
		seen = set()
	if depth > 12 or len(seen) > 500000:
		raise ValueError('Table payload is too complex.')
	if id(value) in seen:
		return 0
	seen.add(id(value))
	if value is None or type(value) in (bool, int, float):
		return 0
	if type(value) is str:
		return len(value.encode('utf-8'))
	if type(value) is bytes:
		return len(value)
	if isinstance(value, (tuple, frozenset)):
		return sum(plain_size(item, seen, depth + 1) for item in value)
	if is_dataclass(value) and value.__dataclass_params__.frozen:
		return sum(plain_size(getattr(value, field.name), seen, depth + 1) for field in fields(value))
	raise TypeError('Table payload must contain only immutable plain data.')


def panel_records(rows):
	result, ids = [], set()
	for row in rows:
		items = tuple(islice(row, 17))
		if not items or len(items) > 16 or len(result) >= 16:
			raise ValueError('Panel rows must contain 1-16 controls, with at most 16 rows.')
		for item in items:
			if type(item) not in (TextField, Toggle, Choice, Select, DateField, IntegerField, Separator, Label, Action):
				raise TypeError('Expected a plain panel control descriptor.')
			if not text(item.id, 'Control ID', 128) or item.id in ids:
				raise ValueError('Panel control IDs must be nonempty and unique.')
			ids.add(item.id)
			if isinstance(item, Separator):
				continue
			if isinstance(item, Label):
				text(item.text, 'Label')
				text(item.tooltip, 'Tooltip')
			else:
				text(item.label, 'Label', 128)
				text(item.tooltip, 'Tooltip')
			if isinstance(item, TextField):
				text(item.value, 'Field value', 4096)
				if item.max_width is not None and (type(item.max_width) is not int or item.max_width <= 0):
					raise ValueError('Field max_width must be a positive integer or None.')
			if isinstance(item, Toggle) and type(item.value) is not bool:
				raise TypeError('Toggle value must be bool.')
			if isinstance(item, Select):
				values = set()
				for value, label in item.options:
					if not text(value, 'Select value', 128) or value in values or not text(label, 'Select label', 128):
						raise ValueError('Select requires unique values and nonempty labels.')
					values.add(value)
			if isinstance(item, IntegerField):
				if type(item.minimum) is not int or type(item.maximum) is not int or not 0 <= item.minimum <= item.maximum <= 18446744073709551615:
					raise ValueError('Integer bounds must fit unsigned 64-bit integers.')
			if isinstance(item, (Select, DateField, IntegerField)):
				validate_field_value(item, item.value)
			if isinstance(item, Choice):
				values = set()
				for value, icon, tooltip in item.options:
					if not text(value, 'Choice value', 128) or value in values:
						raise ValueError('Choice values must be nonempty and unique.')
					values.add(value)
					if not text(icon, 'Icon resource name') or not text(tooltip, 'Choice tooltip', 256):
						raise ValueError('Choice options require icons and tooltips.')
				if text(item.value, 'Choice value', 128) not in values:
					raise ValueError('Choice value must be one of its options.')
			if isinstance(item, (Toggle, Action, Label)) and item.icon is not None:
				text(item.icon, 'Icon resource name')
		result.append(items)
	if not result:
		raise ValueError('Panel requires at least one row.')
	return tuple(result)