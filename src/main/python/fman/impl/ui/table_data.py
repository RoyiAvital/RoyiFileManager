from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date
from itertools import islice
import math
import ntpath


MAX_ROWS = 10000
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_COLUMNS = 64
TYPED_SLOT_BYTES = 8
INT64_MIN, INT64_MAX = -2 ** 63, 2 ** 63 - 1
# Kind -> (comparison policy, cell-menu copy label, navigation role).
COLUMN_KINDS = {
	'text': ('text', 'Copy Text', None),
	'file_name': ('natural', 'Copy Name', 'file'),
	'folder_name': ('natural', 'Copy Name', 'folder'),
	'file_path': ('natural', 'Copy Path', 'file'),
	'folder_path': ('natural', 'Copy Path', 'folder'),
	'entry_path': ('natural', 'Copy Path', 'entry'),
	'date': ('date', 'Copy Date', None),
	'numeric': ('number', 'Copy Value', None),
}


def text(value, name, limit=None):
	if not isinstance(value, str):
		raise TypeError('%s must be a string.' % name)
	if '\x00' in value or (limit is not None and len(value) > limit):
		raise ValueError('%s contains NUL or exceeds its length limit.' % name)
	return value


@dataclass(frozen=True, slots=True)
class QuickTableRow:
	cells: tuple
	highlights: tuple = ()
	# Host-filled: the caller's raw cells, kept when Date/Numeric cells are formatted.
	values: tuple = ()
	# Optional absolute paths per column; when given, Go To/Copy Path use them instead of the cell text.
	targets: tuple = ()

	def __post_init__(self):
		if not isinstance(self.cells, (tuple, list)):
			raise TypeError('Row cells must be a sequence.')
		object.__setattr__(self, 'cells', tuple(self.cells))
		object.__setattr__(self, 'highlights', tuple(
			tuple(tuple(span) for span in column) for column in self.highlights))
		if not isinstance(self.targets, (tuple, list)):
			raise TypeError('Row targets must be a sequence.')
		object.__setattr__(self, 'targets', tuple(self.targets))


@dataclass(frozen=True, slots=True)
class QuickTableColumn:
	label: str
	kind: str = 'text'
	sortable: bool = True
	filterable: bool = True
	searchable: bool | None = None
	unit: str | None = None
	date_display: str = 'timestamp'
	format: object = None
	missing: str = 'Unknown'

	@property
	def policy(self):
		return COLUMN_KINDS[self.kind][0]

	@property
	def copy_label(self):
		return COLUMN_KINDS[self.kind][1]

	@property
	def role(self):
		return COLUMN_KINDS[self.kind][2]

	@property
	def typed(self):
		return self.policy in ('date', 'number')


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


def _validate_columns(columns):
	if isinstance(columns, (str, bytes)) or not isinstance(columns, Sequence):
		raise TypeError('columns must be a sequence of QuickTableColumn descriptors.')
	columns = tuple(columns)
	if not 1 <= len(columns) <= MAX_COLUMNS:
		raise ValueError('Tables require 1-64 columns.')
	for column in columns:
		if type(column) is not QuickTableColumn:
			raise TypeError('columns must contain QuickTableColumn descriptors.')
		if not text(column.label, 'Column label', 128):
			raise ValueError('Column labels must not be empty.')
		if column.kind not in COLUMN_KINDS:
			raise ValueError('Unknown column kind: %s' % column.kind)
		if any(type(value) is not bool for value in (column.sortable, column.filterable)) or \
				column.searchable is not None and type(column.searchable) is not bool:
			raise TypeError('Column capabilities must be boolean.')
		if column.unit not in (None, 'bytes') or column.unit and column.kind != 'numeric':
			raise ValueError('Only numeric columns accept the bytes unit.')
		if column.date_display not in ('timestamp', 'date'):
			raise ValueError('date_display must be timestamp or date.')
		if column.format is not None and (column.kind != 'numeric' or not callable(column.format)):
			raise TypeError('format must be a callable on a numeric column.')
		text(column.missing, 'Missing text', 128)
	return columns


def _checked_value(column, value):
	if type(value) is int:
		if not INT64_MIN <= value <= INT64_MAX:
			raise ValueError('Typed integers must fit signed 64 bits.')
		if column.unit == 'bytes' and value < 0:
			raise ValueError('Byte values must be nonnegative.')
	elif type(value) is float and column.policy == 'number' and column.unit is None:
		if not math.isfinite(value):
			raise ValueError('Numeric values must be finite.')
	else:
		raise TypeError('%s values must be %s or None.' % (column.label,
			'integer UTC epoch nanoseconds' if column.policy == 'date' else
			'integer bytes' if column.unit else 'integers or finite floats'))


def _number_text(column, value):
	if column.format is not None:
		return text(column.format(value), 'Formatted value', 128)
	if column.unit == 'bytes':
		return '{:,} B'.format(value)
	return format(value, ',' if type(value) is int else ',.6g')


class TableSchema:
	def __init__(self, columns, base_path=None, dates=None):
		self.columns = _validate_columns(columns)
		self.headers = tuple(column.label for column in self.columns)
		self.num_columns = len(self.columns)
		self.roles = {index: column.role for index, column in enumerate(self.columns) if column.role}
		self.base = absolute_path(base_path) if base_path is not None else None
		self.searchable = tuple(index for index, column in enumerate(self.columns)
			if (column.searchable if column.searchable is not None else not column.typed))
		self.typed = tuple(index for index, column in enumerate(self.columns) if column.typed)
		self.dates = None
		if any(column.policy == 'date' for column in self.columns):
			if dates is None:
				from fman.impl.ui.table_dates import LocalDates
				dates = LocalDates()
			self.dates = dates

	def column(self, index):
		return self.columns[index]

	def _display(self, row, check_canceled=None):
		cells = list(row.cells)
		for index in self.typed:
			if check_canceled is not None:
				check_canceled()
			value = cells[index]
			if row.highlights and row.highlights[index]:
				raise ValueError('Date and Numeric cells do not accept highlights.')
			column = self.columns[index]
			if value is None:
				cells[index] = column.missing
				continue
			_checked_value(column, value)
			if column.policy == 'date':
				try:
					cells[index] = self.dates.format(value, column.date_display == 'date')
				except (OverflowError, ValueError) as error:
					raise ValueError('Date value cannot be displayed: %s' % error) from None
			else:
				cells[index] = _number_text(column, value)
			if check_canceled is not None:
				check_canceled()
		return replace(row, cells=tuple(cells), values=row.cells)

	def target(self, row, column):
		if column not in self.roles:
			return None
		if row.targets:
			value = row.targets[column]
			return None if value is None else absolute_path(value)
		value = text(row.cells[column], 'Path')
		if not value:
			return None
		drive, tail = ntpath.splitdrive(value)
		if drive or tail.startswith(('\\', '/')):
			return absolute_path(value)
		if ':' in value:
			raise ValueError('Expected a native Windows path, not a URL.')
		return ntpath.normpath(ntpath.join(self.base, value)) if self.base else None

	def snapshot(self, rows, *, check_canceled=None):
		if isinstance(rows, (str, bytes)) or not isinstance(rows, Iterable):
			raise TypeError('rows must be an iterable of QuickTableRow records.')
		result, seen = [], set()
		size = 0
		width = self.num_columns
		typed_bytes = TYPED_SLOT_BYTES * len(self.typed)
		for row in rows:
			if check_canceled is not None:
				check_canceled()
			if len(result) >= MAX_ROWS:
				raise ValueError('Table exceeds the 10,000-row limit.')
			if not isinstance(row, QuickTableRow):
				raise TypeError('rows must contain QuickTableRow records.')
			if len(row.cells) != width:
				raise ValueError('Each row needs one cell per column.')
			if row.highlights and len(row.highlights) != width:
				raise ValueError('Highlights must have one entry per column.')
			if row.targets:
				if len(row.targets) != width:
					raise ValueError('Targets must have one entry per column.')
				for index, target in enumerate(row.targets):
					if target is not None:
						if index not in self.roles:
							raise ValueError('Only name and path columns accept targets.')
						absolute_path(target)
			if self.typed:
				row = self._display(row, check_canceled)
				if check_canceled is not None:
					check_canceled()
			elif row.values:
				row = replace(row, values=())
			for cell in row.cells:
				text(cell, 'Cell')
			if row.highlights:
				for cell, spans in zip(row.cells, row.highlights):
					if len(spans) > 128:
						raise ValueError('Too many highlight spans.')
					for span in spans:
						if len(span) != 2 or any(type(value) is not int for value in span):
							raise TypeError('Highlight spans must contain two integers.')
						if not 0 <= span[0] <= span[1] <= len(cell):
							raise ValueError('Highlight outside cell text.')
			size += plain_size(row, seen) + typed_bytes
			if size > MAX_TEXT_BYTES:
				raise ValueError('Table exceeds the 16 MiB text limit.')
			result.append(row)
		if check_canceled is not None:
			check_canceled()
		return tuple(result)


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