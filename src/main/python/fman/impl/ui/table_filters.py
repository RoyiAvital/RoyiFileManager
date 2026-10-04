from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from fman.impl.ui import match_positions, matchers
from fman.impl.ui.table_dates import parse_date

TEXT_MODES = (('fuzzy', 'Fuzzy'), ('substring', 'Contains'))
NUMBER_OPERATORS = (('=', '='), ('<', '<'), ('<=', '\u2264'), ('>', '>'), ('>=', '\u2265'),
	('between', 'Between'), ('missing', 'Missing'))
DATE_OPERATORS = (('on', 'On'), ('before', 'Before'), ('after', 'After'),
	('between', 'Between'), ('missing', 'Missing'))
BYTE_UNITS = (('B', 1), ('KiB', 1024), ('MiB', 1024 ** 2), ('GiB', 1024 ** 3))


@dataclass(frozen=True)
class ColumnFilter:
	column: int
	operator: str
	first: str = ''
	second: str = ''
	unit: str = 'B'
	description: str = ''
	predicate: object = None


def operators(column):
	policy = column.policy
	if policy == 'number':
		return NUMBER_OPERATORS
	if policy == 'date':
		return DATE_OPERATORS
	return TEXT_MODES


def _number(text, unit, label):
	cleaned = text.strip().replace(',', '').replace('_', '')
	try:
		value = Decimal(cleaned)
	except InvalidOperation:
		value = None
	if not cleaned or value is None or not value.is_finite():
		raise ValueError('Enter a number for %s.' % label)
	if not unit:
		return value
	try:
		return value * dict(BYTE_UNITS)[unit]
	except ArithmeticError:
		# Decimal signals Overflow for exponents beyond its context, e.g. 1e1000000.
		raise ValueError('%s is out of range.' % label) from None


def compile_filter(column, index, operator, first='', second='', unit='B', dates=None):
	label = column.label
	if column.policy in ('text', 'natural'):
		query = first.strip()
		if operator not in dict(TEXT_MODES):
			raise ValueError('Unknown text filter mode.')
		if not query:
			raise ValueError('Enter text to filter %s.' % label)
		if operator == 'substring':
			folded = query.casefold()
			predicate = lambda row: folded in row.cells[index].casefold()
			description = '%s contains "%s"' % (label, query)
		else:
			predicate = lambda row: match_positions(matchers.contains_chars, row.cells[index], query) is not None
			description = '%s matches "%s"' % (label, query)
		return ColumnFilter(index, operator, query, '', unit, description, predicate)
	if operator == 'missing':
		return ColumnFilter(index, operator, '', '', unit, '%s is missing' % label,
			lambda row: row.values[index] is None)
	if column.policy == 'number':
		if operator not in dict(NUMBER_OPERATORS):
			raise ValueError('Unknown numeric operator.')
		scale = unit if column.unit == 'bytes' else None
		if scale is not None and scale not in dict(BYTE_UNITS):
			raise ValueError('Unknown size unit.')
		low = _number(first, scale, label)
		high = _number(second, scale, label) if operator == 'between' else None
		suffix = ' ' + scale if scale else ''
		if operator == 'between':
			if high < low:
				raise ValueError('The second value must not be smaller than the first.')
			test = lambda value, low, high: low <= value <= high
			description = '%s between %s and %s%s' % (label, first.strip(), second.strip(), suffix)
		else:
			test = {'=': lambda value, low, high: value == low, '<': lambda value, low, high: value < low,
				'<=': lambda value, low, high: value <= low, '>': lambda value, low, high: value > low,
				'>=': lambda value, low, high: value >= low}[operator]
			description = '%s %s %s%s' % (label, dict(NUMBER_OPERATORS)[operator], first.strip(), suffix)
		# Integers compare exactly with the Decimal bounds; floats with the nearest float, so 0.1 = 0.1 holds.
		exact = low, high
		nearest = float(low), None if high is None else float(high)
		def predicate(row):
			value = row.values[index]
			if value is None:
				return False
			return test(value, *(nearest if type(value) is float else exact))
		return ColumnFilter(index, operator, first.strip(), second.strip(), unit, description, predicate)
	if column.policy != 'date' or operator not in dict(DATE_OPERATORS):
		raise ValueError('Unknown date operator.')
	day = parse_date(first)
	if operator == 'on':
		low, high = dates.day_start(day), dates.next_day_start(day)
		description = '%s on %s' % (label, day.isoformat())
	elif operator == 'before':
		low, high = None, dates.day_start(day)
		description = '%s before %s' % (label, day.isoformat())
	elif operator == 'after':
		low, high = dates.next_day_start(day), None
		description = '%s after %s' % (label, day.isoformat())
	else:
		last = parse_date(second)
		if last < day:
			raise ValueError('The end date must not be before the start date.')
		low, high = dates.day_start(day), dates.next_day_start(last)
		description = '%s from %s to %s' % (label, day.isoformat(), last.isoformat())
	def predicate(row):
		value = row.values[index]
		return value is not None and (low is None or value >= low) and (high is None or value < high)
	return ColumnFilter(index, operator, first.strip(), second.strip(), unit, description, predicate)
