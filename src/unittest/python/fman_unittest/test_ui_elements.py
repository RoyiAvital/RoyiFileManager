from core.quicksearch_matchers import contains_chars
from fman.impl.ui import Resource, UiOwner, match_positions, resource, utf16_span
from unittest import TestCase
from unittest.mock import Mock
from fman.impl.navigation import NavigationRequest, current_request


class QuickBoardDataTest(TestCase):
	def test_public_arguments_fail_before_ui_or_worker_creation(self):
		from fman.ui import QuickTableColumn, show_quick_board
		from unittest.mock import patch
		valid = dict(columns=(QuickTableColumn('Preview'),), get_rows=lambda text: ())
		invalid = (dict(owner=None), dict(get_rows=None), dict(columns=()), dict(columns=('Name',)),
			dict(text='a\nb'), dict(text='a\rb'), dict(text='\0'), dict(text='x' * 4097),
			dict(text='\U0001f600' * 2049), dict(title='x' * 513), dict(summary='x' * 2049))
		with patch('fman.impl.ui.quick_board._open') as opening:
			for values in invalid:
				with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
					show_quick_board(**dict(valid, **values))
			opening.assert_not_called()

	def test_preview_formats_once_and_closes_failed_iterators(self):
		from fman.impl.ui.quick_board import _prepare
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		formatter = Mock(side_effect=lambda value: 'custom:%d' % value)
		schema = TableSchema((QuickTableColumn('Value', 'numeric', format=formatter),))
		rows, error = _prepare(schema, lambda text: (QuickTableRow((7,)),), 'anything', lambda: None)
		self.assertIsNone(error)
		self.assertEqual(('custom:7',), rows[0].cells)
		self.assertEqual((7,), rows[0].values)
		formatter.assert_called_once_with(7)
		closed = []
		def invalid(text):
			try:
				yield QuickTableRow(('bad',))
			finally:
				closed.append(True)
		rows, error = _prepare(schema, invalid, '', lambda: None)
		self.assertIsNone(rows)
		self.assertFalse(error[0])
		self.assertEqual([True], closed)
		from fman import Task
		for failure in (ValueError('syntax'), RuntimeError('broken'), KeyboardInterrupt('canceled'), Task.Canceled()):
			rows, error = _prepare(schema, Mock(side_effect=failure), '', lambda: None)
			self.assertEqual((isinstance(failure, ValueError), str(failure) or type(failure).__name__), error)

	def test_admission_is_global_bounded_and_release_is_idempotent(self):
		from fman.impl.ui.quick_board import _reserve
		first, second = _reserve(), _reserve()
		try:
			self.assertIsNotNone(first)
			self.assertIsNotNone(second)
			self.assertIsNone(_reserve())
		finally:
			first()
			first()
			second()
		third = _reserve()
		self.assertIsNotNone(third)
		third()


class QuickListDataTest(TestCase):
	def test_metadata_value_forms_and_hashable_items(self):
		from fman.impl.ui import ListItem
		item = ListItem('a', 'A', metadata={'Added': 3, 'Size': 1.5, 'Used': (7, 'Monday'), 'Tag': 'x', 'None': ()})
		self.assertEqual((('Added', 3, '3'), ('Size', 1.5, '1.5'), ('Used', 7, 'Monday'),
			('Tag', 'x', 'x'), ('None', None, '')), item.metadata)
		self.assertEqual(hash(item), hash(ListItem('a', 'A', metadata={'Added': 3, 'Size': 1.5,
			'Used': [7, 'Monday'], 'Tag': 'x', 'None': []})))
		from dataclasses import replace
		self.assertEqual(item.metadata, replace(item, title_matches=(0,)).metadata)

	def test_metadata_limits_and_refused_values(self):
		from fman.impl.ui import ListItem
		for metadata in ({'': 1}, {'x' * 33: 1}, {'A': True}, {'A': float('nan')}, {'A': float('inf')},
				{'A': None}, {'A': (1, 2, 3)}, {'A': (1, 2)}, {'A': 'x' * 129}, {'A': (True, 'x')},
				{str(index): index for index in range(9)}):
			with self.subTest(metadata=metadata), self.assertRaises((TypeError, ValueError)):
				ListItem('a', 'A', metadata=metadata)
		with self.assertRaises(TypeError):
			ListItem('a', 'A', metadata=[('A', 1)])
		with self.assertRaises(ValueError):
			ListItem('a', 'A', metadata={'N': 10**200})

	def test_prepare_validates_canonical_metadata(self):
		from fman.impl.ui import ListItem
		from fman.impl.ui.quick_list_data import prepare_items
		for metadata in ((('A', float('nan'), 'x'),), (('A', 1, object()),), (('A', 1, 'x' * 129),),
				(('', 1, 'x'),), (('A', True, 'x'),), tuple((str(index), index, 'x') for index in range(9))):
			with self.subTest(metadata=metadata), self.assertRaises((TypeError, ValueError)):
				prepare_items((ListItem('a', 'A', metadata=metadata),))
		prepare_items((ListItem('a', 'A', metadata=(('A', None, ''),)),))

	def test_prepare_requires_consistent_unique_labels_and_kinds(self):
		from fman.impl.ui import ListItem
		from fman.impl.ui.quick_list_data import prepare_items
		with self.assertRaises(ValueError):
			prepare_items((ListItem('a', 'A', metadata={'X': 1}), ListItem('b', 'B', metadata={'Y': 1})))
		with self.assertRaises(TypeError):
			prepare_items((ListItem('a', 'A', metadata={'X': 1}), ListItem('b', 'B', metadata={'X': 'one'})))
		with self.assertRaises(ValueError):
			prepare_items((ListItem('a', 'A', metadata={'Name': 1}),), 'Name')
		with self.assertRaises(ValueError):
			prepare_items((), 'Same', 'Same')
		with self.assertRaises(ValueError):
			prepare_items((ListItem('a', 'A'), ListItem('a', 'B')))
		with self.assertRaises(ValueError):
			prepare_items((ListItem('a', 'x' * 513),))
		with self.assertRaises(TypeError):
			prepare_items('ab')
		prepared = prepare_items((ListItem('a', 'file10', metadata={'X': ()}), ListItem('b', 'File2', metadata={'X': 4})), 'Name')
		self.assertEqual(('Name', 'X'), prepared.labels)
		self.assertLess(prepared.keys['Name'][1], prepared.keys['Name'][0])
		self.assertEqual((None, 4), prepared.keys['X'])
		self.assertEqual((), prepare_items(()).labels)

	def test_selected_sort_settings_and_result_validation(self):
		from fman.impl.ui import ListItem
		from fman.impl.ui.quick_list_data import prepare_items, requested_sort, result_ids, \
			selected_ids, settings_name
		prepared = prepare_items((ListItem('a', 'A'),))
		self.assertEqual({'a'}, selected_ids(('a',), prepared))
		with self.assertRaises(ValueError):
			selected_ids(('missing',), prepared)
		self.assertEqual(('Name', False), requested_sort(['Name', False]))
		for invalid in (('Name',), ('Name', 1), ('', True)):
			with self.subTest(sort=invalid), self.assertRaises((TypeError, ValueError)):
				requested_sort(invalid)
		self.assertEqual('List UI.json', settings_name('List UI.json'))
		for invalid in ('List.txt', 'a/b.json', 'a\\b.json'):
			with self.subTest(settings=invalid), self.assertRaises(ValueError):
				settings_name(invalid)
		self.assertEqual(('a',), result_ids(('a',), frozenset({'a'})))
		self.assertIsNone(result_ids(None, frozenset()))
		for invalid in (object(), ['a'], ('b',)):
			with self.subTest(result=invalid), self.assertRaises(ValueError):
				result_ids(invalid, frozenset({'a'}))


class TableDataTest(TestCase):
	def test_snapshot_checks_cancellation_during_iteration_and_after_formatting(self):
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		from fman.impl.model.listing import Canceled
		consumed = []
		def rows():
			for value in range(10):
				consumed.append(value)
				yield QuickTableRow((str(value),))
		check = Mock(side_effect=[None, Canceled()])
		with self.assertRaises(Canceled):
			TableSchema((QuickTableColumn('Text'),)).snapshot(rows(), check_canceled=check)
		self.assertEqual([0, 1], consumed)
		check = Mock(side_effect=[None, None, Canceled()])
		formatter = Mock(return_value='formatted')
		schema = TableSchema((QuickTableColumn('Value', 'numeric', format=formatter),))
		with self.assertRaises(Canceled):
			schema.snapshot((QuickTableRow((7,)),), check_canceled=check)
		formatter.assert_called_once_with(7)
		self.assertEqual(3, check.call_count)

	def test_cancellation_stops_remaining_formatters_in_the_row(self):
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		from fman.impl.model.listing import Canceled
		calls = []
		def formatter(value):
			calls.append(value)
			return str(value)
		def check():
			if calls:
				raise Canceled()
		schema = TableSchema((QuickTableColumn('First', 'numeric', format=formatter),
			QuickTableColumn('Second', 'numeric', format=formatter)))
		rows = (QuickTableRow((1, 2)),)
		with self.assertRaises(Canceled):
			schema.snapshot(rows, check_canceled=check)
		self.assertEqual([1], calls)
		calls.clear()
		self.assertEqual(('1', '2'), schema.snapshot(rows)[0].cells)
		self.assertEqual([1, 2], calls)

	def test_structured_panel_fields(self):
		from fman.impl.ui.table_data import DateField, IntegerField, Select, Separator, panel_records, validate_field_value
		options = tuple((str(index), 'Type %d' % index) for index in range(11))
		rows = ((Select('type', 'Type', options, '0'), DateField('start', 'Start'),
			DateField('end', 'End', '2026-09-20'), IntegerField('size', 'Size', 5000000000), Separator('section')),)
		self.assertEqual(rows, panel_records(rows))
		for field in (DateField('date', 'Date', '2026-02-30'), DateField('date', 'Date', '20260920'),
				DateField('date', 'Date', '1700-01-01'), IntegerField('size', 'Size', True),
				IntegerField('size', 'Size', -1), IntegerField('size', 'Size', 1.5),
				IntegerField('depth', 'Depth', 0, minimum=1), IntegerField('size', 'Size', 2**64),
				Select('type', 'Type', options, 'unknown'), Select('type', 'Type', (('a', 'A'), ('a', 'B')), 'a')):
			with self.subTest(field=field), self.assertRaises((TypeError, ValueError)):
				panel_records(((field,),))
		validate_field_value(rows[0][1], None)
		validate_field_value(rows[0][3], 0)
		with self.assertRaises(ValueError):
			validate_field_value(rows[0][3], '12')
		with self.assertRaises(ValueError):
			panel_records(((Separator('same'), Separator('same')),))

	def test_choice_descriptors_validate_plain_options(self):
		from fman.impl.ui.table_data import Choice, panel_records
		options = [('literal', 'text.svg', 'Literal'), ('glob', 'asterisk.svg', 'Glob')]
		choice = Choice('mode', 'Mode', options, 'glob')
		self.assertEqual((tuple(options[0]), tuple(options[1])), choice.options)
		self.assertEqual(((choice,),), panel_records(((choice,),)))
		for invalid in (Choice('mode', 'Mode', options, 'unknown'),
				Choice('mode', 'Mode', (options[0], options[0]), 'literal')):
			with self.assertRaises(ValueError):
				panel_records(((invalid,),))
		for invalid in ([], options * 5, ['abc', 'def']):
			with self.assertRaises((TypeError, ValueError)):
				Choice('mode', 'Mode', invalid, 'literal')

	def test_column_kinds_define_roles_and_default_resolution(self):
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		row = QuickTableRow(('nested/file.txt', 'C:\\elsewhere'))
		self.assertIsNone(TableSchema((QuickTableColumn('A'), QuickTableColumn('B'))).target(row, 0))
		schema = TableSchema((QuickTableColumn('File', 'file_path'), QuickTableColumn('Folder', 'folder_path')), base_path='C:\\base')
		self.assertEqual({0: 'file', 1: 'folder'}, schema.roles)
		self.assertEqual('C:\\base\\nested\\file.txt', schema.target(row, 0))
		self.assertEqual('C:\\elsewhere', schema.target(row, 1))
		self.assertIsNone(TableSchema((QuickTableColumn('A', 'file_path'), QuickTableColumn('B'))).target(row, 0))
		self.assertIsNone(schema.target(QuickTableRow(('', '')), 0))
		kinds = ('file_name', 'folder_name', 'entry_path')
		self.assertEqual({0: 'file', 1: 'folder', 2: 'entry'},
			TableSchema(tuple(QuickTableColumn(kind, kind) for kind in kinds)).roles)

	def test_paths_are_lexical(self):
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		from unittest.mock import patch
		schema = TableSchema((QuickTableColumn('Path', 'file_path'),), base_path='C:\\base')
		with patch('os.stat', side_effect=AssertionError('No filesystem probe')):
			for value, expected in (('..\\a.txt', 'C:\\a.txt'),
					('\\\\server\\share\\a.txt', '\\\\server\\share\\a.txt'),
					(' spaced .txt', 'C:\\base\\ spaced .txt')):
				self.assertEqual(expected, schema.target(QuickTableRow((value,)), 0))
			for value in ('C:relative', '\\rooted', 'file:///C:/a', 'https://a', 'bad\x00path'):
				with self.subTest(value=value), self.assertRaises(ValueError):
					schema.target(QuickTableRow((value,)), 0)

	def test_snapshot_schema_bounds(self):
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		from unittest.mock import patch
		schema = TableSchema((QuickTableColumn('Path'), QuickTableColumn('Snippet')))
		row = QuickTableRow(['one', 'text'], ((), ((0, 4),)))
		self.assertEqual((row, row), schema.snapshot([row, row]))
		self.assertEqual((row,), schema.snapshot(iter([row])))
		for rows in ([QuickTableRow(('one',))], [QuickTableRow(('one', 'two'), ((), ((0, 4),)))],
				[QuickTableRow(('one', 2))], ['one'], 'rows', None):
			with self.subTest(rows=rows), self.assertRaises((TypeError, ValueError)):
				schema.snapshot(rows)
		with patch('fman.impl.ui.table_data.MAX_ROWS', 1), self.assertRaises(ValueError):
			schema.snapshot(QuickTableRow(('a', 'b')) for index in range(3))
		with patch('fman.impl.ui.table_data.MAX_TEXT_BYTES', 1), self.assertRaises(ValueError):
			schema.snapshot([row])

	def test_panel_descriptors_validate_without_qt(self):
		from fman.impl.ui.table_data import Action, Label, TextField, Toggle, panel_records
		rows = ((TextField('query', 'Query', max_width=480),
			Toggle('regex', 'regex.svg', 'Regex')),
			(Label('root', 'C:\\', 'panel-left.svg', 'Left pane'), Action('search', 'Search')))
		self.assertEqual(rows, panel_records(rows))
		for invalid in (((rows[0][0], rows[0][0]),),
				((Toggle('bad', 'regex.svg', 'Regex', value=1),),),
				((Label('root', 'C:\\', icon=True),),),
				((Label('root', 'C:\\', tooltip=True),),), ((),)):
			with self.assertRaises((TypeError, ValueError)):
				panel_records(invalid)
		for width in (True, 0, -1, '480'):
			with self.assertRaises(ValueError):
				panel_records(((TextField('query', 'Query', max_width=width),),))


def utc_dates():
	from fman.impl.ui.table_dates import LocalDates
	return LocalDates(lambda seconds: 0)


def typed_schema(dates=None):
	from fman.impl.ui.table_data import QuickTableColumn, TableSchema
	columns = (QuickTableColumn('Path', 'file_path'), QuickTableColumn('Size', 'numeric', unit='bytes'),
		QuickTableColumn('Modified', 'date'), QuickTableColumn('Note'))
	return TableSchema(columns, base_path='C:\\root', dates=dates or utc_dates())


class TypedTableTest(TestCase):
	def test_column_descriptors_validate(self):
		from fman.impl.ui.table_data import QuickTableColumn, TableSchema
		schema = typed_schema()
		self.assertEqual((0, 3), schema.searchable)
		self.assertEqual((1, 2), schema.typed)
		self.assertEqual(('Path', 'Size', 'Modified', 'Note'), schema.headers)
		self.assertEqual(('Copy Path', 'Copy Value', 'Copy Date', 'Copy Text'),
			tuple(column.copy_label for column in schema.columns))
		for columns in ((), (QuickTableColumn('A'),) * 65, (QuickTableColumn(''),), (QuickTableColumn('A', 'unknown'),),
				(QuickTableColumn('A', unit='bytes'),), (QuickTableColumn('A', 'date', date_display='time'),),
				(QuickTableColumn('A', sortable=1),), (QuickTableColumn('A', format=str),),
				(QuickTableColumn('A', 'numeric', format='x'),), (QuickTableColumn('A', missing=None),), ('A',), 'A'):
			with self.subTest(columns=columns), self.assertRaises((TypeError, ValueError)):
				TableSchema(columns)

	def test_typed_cells_are_formatted_and_bounded(self):
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		schema = typed_schema()
		row = QuickTableRow(['a.txt', 5, 86400 * 10 ** 9, 'n'])
		snapshot = schema.snapshot((row, QuickTableRow(('b', None, None, ''))))
		self.assertEqual(('a.txt', '5 B', '1970-01-02T00:00:00Z', 'n'), snapshot[0].cells)
		self.assertEqual(('a.txt', 5, 86400 * 10 ** 9, 'n'), snapshot[0].values)
		self.assertEqual(('b', 'Unknown', 'Unknown', ''), snapshot[1].cells)
		self.assertEqual((), TableSchema((QuickTableColumn('A'),)).snapshot((QuickTableRow(('a',), values=('stale',)),))[0].values)
		for cells in (('a', -1, None, ''), ('a', True, None, ''), ('a', 1.5, None, ''), ('a', '5 B', None, ''),
				('a', None, 2 ** 63, ''), ('a', None, 1.0, ''), (None, None, None, ''), ('a', None, None, 3)):
			with self.subTest(cells=cells), self.assertRaises((TypeError, ValueError)):
				schema.snapshot((QuickTableRow(cells),))
		with self.assertRaises(ValueError):
			schema.snapshot((QuickTableRow(('a', None, 0, ''), highlights=((), (), ((0, 1),), ())),))
		numbers = TableSchema((QuickTableColumn('N', 'numeric'),))
		self.assertEqual(('1,234,567', '1.5', '-2'), tuple(row.cells[0] for row in numbers.snapshot(
			(QuickTableRow((1234567,)), QuickTableRow((1.5,)), QuickTableRow((-2,))))))
		for value in (float('nan'), float('inf')):
			with self.assertRaises(ValueError):
				numbers.snapshot((QuickTableRow((value,)),))
		custom = TableSchema((QuickTableColumn('S', 'numeric', unit='bytes', format=lambda value: '%d KiB' % (value // 1024), missing=''),))
		self.assertEqual(('2 KiB', ''), tuple(row.cells[0] for row in custom.snapshot(
			(QuickTableRow((2048,)), QuickTableRow((None,))))))
		with self.assertRaises(TypeError):
			TableSchema((QuickTableColumn('S', 'numeric', format=lambda value: value),)).snapshot((QuickTableRow((1,)),))
		days = TableSchema((QuickTableColumn('D', 'date', date_display='date'),), dates=utc_dates())
		self.assertEqual(('1970-01-01',), days.snapshot((QuickTableRow((0,)),))[0].cells)

	def test_local_day_bounds_handle_gaps_and_overlaps(self):
		from datetime import date
		from fman.impl.ui.table_dates import LocalDates, NS, parse_date
		hour = 3600
		# Midnight on 2001-01-02 is skipped: clocks move from 00:00 to 01:00 local.
		gap_utc = 978393600
		gap = LocalDates(lambda seconds: hour if seconds >= gap_utc else 0)
		self.assertEqual(gap_utc * NS, gap.day_start(date(2001, 1, 2)))
		# Midnight on 2001-01-02 occurs twice: clocks move from 01:00 back to 00:00 local.
		overlap = LocalDates(lambda seconds: 0 if seconds >= gap_utc else hour)
		self.assertEqual((gap_utc - hour) * NS, overlap.day_start(date(2001, 1, 2)))
		skipped = LocalDates(lambda seconds: 86400 if seconds >= gap_utc else 0)
		with self.assertRaises(ValueError):
			skipped.day_start(date(2001, 1, 2))
		self.assertEqual('1970-01-01T05:30:00+05:30', LocalDates(lambda seconds: 19800).format(0))
		self.assertEqual('1969-12-31T23:00:00-01:00', LocalDates(lambda seconds: -hour).format(0))
		for value in ('2026-02-30', '2026-1-1', 'today'):
			with self.subTest(value=value), self.assertRaises(ValueError):
				parse_date(value)

	def test_column_filters(self):
		from fman.impl.ui.table_data import QuickTableRow
		from fman.impl.ui.table_filters import compile_filter, operators
		schema = typed_schema()
		day = 86400 * 10 ** 9
		rows = (QuickTableRow(('Alpha.txt', 1024, 0, 'a')),
			QuickTableRow(('beta.txt', 4096, day, 'b')),
			QuickTableRow(('gamma.txt', None, None, 'c')))
		rows = schema.snapshot(rows)
		def ids(column, *arguments, **keywords):
			flt = compile_filter(schema.columns[column], column, *arguments, dates=schema.dates, **keywords)
			return ''.join(row.cells[3] for row in rows if flt.predicate(row))
		self.assertEqual('a', ids(0, 'substring', 'ALP'))
		self.assertEqual('ac', ids(0, 'fuzzy', 'aa'))
		self.assertEqual('b', ids(1, '>', '1', unit='KiB'))
		self.assertEqual('ab', ids(1, 'between', '1,024', '4096'))
		self.assertEqual('a', ids(1, '<=', '1024'))
		self.assertEqual('c', ids(1, 'missing'))
		self.assertEqual('a', ids(2, 'on', '1970-01-01'))
		self.assertEqual('a', ids(2, 'before', '1970-01-02'))
		self.assertEqual('b', ids(2, 'after', '1970-01-01'))
		self.assertEqual('ab', ids(2, 'between', '1970-01-01', '1970-01-02'))
		self.assertEqual('c', ids(2, 'missing'))
		self.assertEqual(('fuzzy', 'substring'), tuple(key for key, label in operators(schema.columns[3])))
		for column, arguments in ((0, ('substring', ' ')), (1, ('>', 'abc')), (1, ('>', 'nan')),
				(1, ('between', '5', '1')), (1, ('>', '1', '', 'TB')), (2, ('on', '1970-13-01')),
				(2, ('between', '1970-01-02', '1970-01-01')), (2, ('=', '1970-01-01')), (0, ('>', 'x'))):
			with self.subTest(arguments=arguments), self.assertRaises(ValueError):
				compile_filter(schema.columns[column], column, *arguments, dates=schema.dates)

	def test_extreme_byte_exponents_are_validation_errors(self):
		from fman.impl.ui.table_filters import compile_filter
		size = typed_schema().columns[1]
		self.assertIsNotNone(compile_filter(size, 1, '>=', '1e999999', unit='B').predicate)
		for unit in ('B', 'GiB'):
			for value in ('1e1000000', '-1e1000000'):
				with self.subTest(unit=unit, value=value), self.assertRaises(ValueError):
					compile_filter(size, 1, '>=', value, unit=unit)

	def test_float_cells_match_their_typed_bounds(self):
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		from fman.impl.ui.table_filters import compile_filter
		column = QuickTableColumn('Ratio', 'numeric')
		schema = TableSchema((column,))
		rows = schema.snapshot(QuickTableRow((value,)) for value in (0.1, 0.3, 1.5, 2, None))
		self.assertEqual(('0.1', '0.3', '1.5', '2', 'Unknown'), tuple(row.cells[0] for row in rows))
		def kept(*arguments):
			predicate = compile_filter(column, 0, *arguments).predicate
			return tuple(row.cells[0] for row in rows if predicate(row))
		self.assertEqual(('0.1',), kept('=', '0.1'))
		self.assertEqual(('0.3',), kept('=', '0.3'))
		self.assertEqual(('0.1',), kept('<=', '0.1'))
		self.assertEqual(('0.3', '1.5', '2'), kept('>=', '0.3'))
		self.assertEqual(('0.1', '0.3'), kept('between', '0.1', '0.3'))
		self.assertEqual(('2',), kept('=', '2'))
		self.assertEqual(('1.5', '2'), kept('>', '0.3'))
		# Integers keep exact comparison against the typed bound.
		self.assertEqual((), kept('=', '2.0000000000000000001'))

	def test_day_before_a_skipped_date_can_be_filtered(self):
		from datetime import date
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		from fman.impl.ui.table_dates import LocalDates, NS
		from fman.impl.ui.table_filters import compile_filter
		# At 2001-01-02 00:00 UTC the zone moves from UTC+00 to UTC+24: local 2001-01-02 never happens.
		skip = 978393600
		dates = LocalDates(lambda seconds: 86400 if seconds >= skip else 0)
		self.assertEqual(skip * NS, dates.next_day_start(date(2001, 1, 1)))
		column = QuickTableColumn('Modified', 'date', date_display='date')
		schema = TableSchema((column,), dates=dates)
		jan_1, jan_3 = (skip - 3600) * NS, (skip + 3600) * NS
		rows = schema.snapshot((QuickTableRow((jan_1,)), QuickTableRow((jan_3,))))
		self.assertEqual(('2001-01-01', '2001-01-03'), tuple(row.cells[0] for row in rows))
		def kept(*arguments):
			predicate = compile_filter(column, 0, *arguments, dates=dates).predicate
			return tuple(row.cells[0] for row in rows if predicate(row))
		self.assertEqual(('2001-01-01',), kept('on', '2001-01-01'))
		self.assertEqual(('2001-01-03',), kept('after', '2001-01-01'))
		self.assertEqual(('2001-01-01',), kept('between', '2001-01-01', '2001-01-01'))
		self.assertEqual(('2001-01-03',), kept('on', '2001-01-03'))
		self.assertEqual(('2001-01-01',), kept('before', '2001-01-03'))
		self.assertEqual(('2001-01-01', '2001-01-03'), kept('between', '2001-01-01', '2001-01-03'))
		with self.assertRaises(ValueError):
			compile_filter(column, 0, 'on', '2001-01-02', dates=dates)

	def test_row_targets_override_cell_text_for_navigation(self):
		from fman.impl.ui.table_data import QuickTableColumn, QuickTableRow, TableSchema
		schema = TableSchema((QuickTableColumn('Path', 'file_path'), QuickTableColumn('Note')), base_path='C:\\base')
		displayed, target = 'report\\u200b.txt', 'C:\\base\\report\u200b.txt'
		navigable, diagnostic = schema.snapshot((QuickTableRow((displayed, 'a'), targets=(target, None)),
			QuickTableRow(('bad record', 'b'), targets=(None, None))))
		self.assertEqual(target, schema.target(navigable, 0))
		self.assertIsNone(schema.target(diagnostic, 0))
		self.assertEqual('C:\\base\\report\\u200b.txt', schema.target(QuickTableRow((displayed, 'a')), 0))
		for targets in ((target,), (target, 'C:\\note'), ('relative.txt', None), ('C:\\bad\x00', None), (1, None)):
			with self.subTest(targets=targets), self.assertRaises((TypeError, ValueError)):
				schema.snapshot((QuickTableRow((displayed, 'a'), targets=targets),))

	def test_natural_key_orders_numbers_and_case(self):
		from fman.impl.util.natural import natural_key
		names = ['file10.txt', 'File2.txt', 'file1.txt', 'file02.txt']
		self.assertEqual(['file1.txt', 'File2.txt', 'file02.txt', 'file10.txt'], sorted(names, key=natural_key))

class UiStateTest(TestCase):
	def test_resource_hit_does_not_construct(self):
		from fman.impl import ui
		from unittest.mock import patch
		with patch.object(ui, '_resources', {}), patch.object(ui, 'Resource') as factory:
			self.assertIs(ui.resource('same'), ui.resource('same'))
			factory.assert_called_once()
	def test_worker_start_failure_releases_slot(self):
		from fman.impl import ui
		from threading import BoundedSemaphore
		from unittest.mock import patch
		slots = BoundedSemaphore(1)
		with patch.object(ui, '_work_slots', slots), patch.object(ui, 'Thread') as thread:
			thread.return_value.start.side_effect = RuntimeError('start failed')
			with self.assertRaises(RuntimeError):
				ui.submit_work(lambda: None, lambda *args: None)
			self.assertTrue(slots.acquire(blocking=False))
	def test_controller_requires_loader_owner(self):
		from fman.ui import UiController
		class Controller(UiController):
			pass
		with self.assertRaisesRegex(RuntimeError, 'active plug-in owner'):
			Controller.require_owner()
		Controller.owner = UiOwner()
		self.assertIs(Controller.owner, Controller.require_owner())
		Controller.owner.invalidate()
		with self.assertRaises(RuntimeError):
			Controller.require_owner()

	def test_casefold_offsets_refer_to_original_characters(self):
		self.assertEqual((2,), match_positions(contains_chars, 'Ma\u00dfe', 'ss'))
		self.assertEqual((4,), match_positions(contains_chars, 'Stra\u00dfe', 'sS'))
		self.assertIsNone(match_positions(contains_chars, 'Alpha', 'z'))

	def test_shared_fuzzy_matcher_prefers_contiguous_text(self):
		from fman.impl.ui.matchers import contains_chars as shared_matcher
		self.assertIs(contains_chars, shared_matcher)
		self.assertEqual([9, 10, 11], contains_chars('cudatext.cmd', 'cmd'))
		self.assertEqual([0, 2, 3], contains_chars('crmd', 'cmd'))
		self.assertEqual([], contains_chars('file.cmd', ''))
		self.assertEqual((9, 10, 11), match_positions(contains_chars, 'Cud\u00e1Text.cmd', 'CMD'))

	def test_astral_highlights_use_utf16_positions(self):
		self.assertEqual((0, 2), utf16_span('\U0001f600Name', 0))
		self.assertEqual((2, 1), utf16_span('\U0001f600Name', 1))

	def test_resource_is_stable_and_snapshots_are_revisioned(self):
		self.assertIs(resource('test'), resource('test'))
		state = Resource()
		received = []
		callback = lambda revision, rows: received.append((revision, rows))
		self.assertEqual((0, ('old',)), state.subscribe(callback, lambda: ('old',)))
		with state.lock:
			notification = state.committed(('new',))
		self.assertEqual([], received)
		state.publish(notification)
		self.assertEqual([(1, ('new',))], received)
		state.unsubscribe(callback)
		with state.lock:
			notification = state.committed(())
		state.publish(notification)
		self.assertEqual(1, len(received))

	def test_owner_disposes_once_and_rejects_new_sessions(self):
		owner = UiOwner()
		disposed = []
		self.assertTrue(owner.attach(lambda: disposed.append(True)))
		owner.invalidate()
		owner.invalidate()
		self.assertEqual([True], disposed)
		self.assertFalse(owner.attach(lambda: None))

	def test_navigation_preserves_command_arguments_and_rejects_untracked(self):
		outcomes = []
		request = NavigationRequest(lambda *result: outcomes.append(result))
		pane = Mock()
		pane.run_command.side_effect = lambda *args: self.assertIs(request, current_request())
		request.dispatch(pane, 'file:///C:/Target')
		pane.run_command.assert_called_once_with('open_directory', {'url': 'file:///C:/Target'})
		self.assertEqual('failure', outcomes[0][0])
		self.assertIsNone(current_request())
		request.finish('success')
		self.assertEqual(1, len(outcomes))

	def test_canceled_navigation_never_dispatches(self):
		pane = Mock()
		request = NavigationRequest(lambda *args: None, allowed=lambda: False)
		request.dispatch(pane, 'file:///C:/Target')
		pane.run_command.assert_not_called()

	def test_navigation_keeps_command_and_location_rewrite_hooks(self):
		from fman import DirectoryPane
		from fman.impl.navigation import tracking
		registry, widget, listener = Mock(), Mock(), Mock()
		pane = DirectoryPane(None, widget, registry)
		pane._add_listener(listener)
		listener.on_command.side_effect = [('open_directory', {'url': 'zip:///C:/a.zip'}), None]
		listener.before_location_change.side_effect = [('zip:///C:/a.zip/folder', '', True), None]
		request = NavigationRequest(lambda *args: None)
		def command(name, args, target):
			self.assertIs(pane, target)
			self.assertEqual('zip:///C:/a.zip', args['url'])
			target.set_path(args['url'])
			request.started = True
		registry.execute_command.side_effect = command
		request.dispatch(pane, 'file:///C:/a.zip')
		self.assertEqual('zip:///C:/a.zip/folder', widget.set_location.call_args.args[0])
		other = DirectoryPane(None, Mock(), registry)
		with tracking(request):
			other.set_path('file:///C:/Other')
		other._widget.set_location.assert_not_called()

	def test_cancel_before_initialization_settles_and_releases_work_slot(self):
		from fman.impl.ui import submit_work
		from threading import Event
		for attempt in range(3):
			request = NavigationRequest(lambda *args: None)
			finished = Event()
			request.started = True
			self.assertTrue(submit_work(lambda: request.wait(1), lambda *args: finished.set()))
			request.cancel()
			self.assertTrue(request.settled.wait(1))
			self.assertTrue(finished.wait(1))
			self.assertFalse(request.begin_initialization())

	def test_timeout_settles_once_and_running_initializations_stay_bounded(self):
		outcomes = []
		requests = [NavigationRequest(lambda *args: outcomes.append(args)) for index in range(3)]
		try:
			self.assertTrue(requests[0].begin_initialization())
			self.assertTrue(requests[1].begin_initialization())
			requests[0].wait(0)
			requests[1].cancel()
			self.assertFalse(requests[2].begin_initialization())
			self.assertTrue(all(request.settled.is_set() for request in requests))
			requests[0].finish('success')
			self.assertEqual(3, len(outcomes))
		finally:
			for request in requests:
				request.end_initialization()