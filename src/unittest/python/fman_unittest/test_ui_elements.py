from core.quicksearch_matchers import contains_chars
from fman.impl.ui import Resource, UiOwner, match_positions, resource, utf16_span
from unittest import TestCase
from unittest.mock import Mock
from fman.impl.navigation import NavigationRequest, current_request


class TableDataTest(TestCase):
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
		from fman.impl.ui.table_data import TableColumn, TableRow, TableSchema
		row = TableRow(('nested/file.txt', 'C:\\elsewhere'))
		self.assertIsNone(TableSchema((TableColumn('A'), TableColumn('B'))).target(row, 0))
		schema = TableSchema((TableColumn('File', 'file_path'), TableColumn('Folder', 'folder_path')), base_path='C:\\base')
		self.assertEqual({0: 'file', 1: 'folder'}, schema.roles)
		self.assertEqual('C:\\base\\nested\\file.txt', schema.target(row, 0))
		self.assertEqual('C:\\elsewhere', schema.target(row, 1))
		self.assertIsNone(TableSchema((TableColumn('A', 'file_path'), TableColumn('B'))).target(row, 0))
		self.assertIsNone(schema.target(TableRow(('', '')), 0))
		kinds = ('file_name', 'folder_name', 'entry_path')
		self.assertEqual({0: 'file', 1: 'folder', 2: 'entry'},
			TableSchema(tuple(TableColumn(kind, kind) for kind in kinds)).roles)

	def test_paths_are_lexical(self):
		from fman.impl.ui.table_data import TableColumn, TableRow, TableSchema
		from unittest.mock import patch
		schema = TableSchema((TableColumn('Path', 'file_path'),), base_path='C:\\base')
		with patch('os.stat', side_effect=AssertionError('No filesystem probe')):
			for value, expected in (('..\\a.txt', 'C:\\a.txt'),
					('\\\\server\\share\\a.txt', '\\\\server\\share\\a.txt'),
					(' spaced .txt', 'C:\\base\\ spaced .txt')):
				self.assertEqual(expected, schema.target(TableRow((value,)), 0))
			for value in ('C:relative', '\\rooted', 'file:///C:/a', 'https://a', 'bad\x00path'):
				with self.subTest(value=value), self.assertRaises(ValueError):
					schema.target(TableRow((value,)), 0)

	def test_snapshot_schema_bounds(self):
		from fman.impl.ui.table_data import TableColumn, TableRow, TableSchema
		from unittest.mock import patch
		schema = TableSchema((TableColumn('Path'), TableColumn('Snippet')))
		row = TableRow(['one', 'text'], ((), ((0, 4),)))
		self.assertEqual((row, row), schema.snapshot([row, row]))
		self.assertEqual((row,), schema.snapshot(iter([row])))
		for rows in ([TableRow(('one',))], [TableRow(('one', 'two'), ((), ((0, 4),)))],
				[TableRow(('one', 2))], ['one'], 'rows', None):
			with self.subTest(rows=rows), self.assertRaises((TypeError, ValueError)):
				schema.snapshot(rows)
		with patch('fman.impl.ui.table_data.MAX_ROWS', 1), self.assertRaises(ValueError):
			schema.snapshot(TableRow(('a', 'b')) for index in range(3))
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
	from fman.impl.ui.table_data import TableColumn, TableSchema
	columns = (TableColumn('Path', 'file_path'), TableColumn('Size', 'numeric', unit='bytes'),
		TableColumn('Modified', 'date'), TableColumn('Note'))
	return TableSchema(columns, base_path='C:\\root', dates=dates or utc_dates())


class TypedTableTest(TestCase):
	def test_column_descriptors_validate(self):
		from fman.impl.ui.table_data import TableColumn, TableSchema
		schema = typed_schema()
		self.assertEqual((0, 3), schema.searchable)
		self.assertEqual((1, 2), schema.typed)
		self.assertEqual(('Path', 'Size', 'Modified', 'Note'), schema.headers)
		self.assertEqual(('Copy Path', 'Copy Value', 'Copy Date', 'Copy Text'),
			tuple(column.copy_label for column in schema.columns))
		for columns in ((), (TableColumn('A'),) * 65, (TableColumn(''),), (TableColumn('A', 'unknown'),),
				(TableColumn('A', unit='bytes'),), (TableColumn('A', 'date', date_display='time'),),
				(TableColumn('A', sortable=1),), (TableColumn('A', format=str),),
				(TableColumn('A', 'numeric', format='x'),), (TableColumn('A', missing=None),), ('A',), 'A'):
			with self.subTest(columns=columns), self.assertRaises((TypeError, ValueError)):
				TableSchema(columns)

	def test_typed_cells_are_formatted_and_bounded(self):
		from fman.impl.ui.table_data import TableColumn, TableRow, TableSchema
		schema = typed_schema()
		row = TableRow(['a.txt', 5, 86400 * 10 ** 9, 'n'])
		snapshot = schema.snapshot((row, TableRow(('b', None, None, ''))))
		self.assertEqual(('a.txt', '5 B', '1970-01-02T00:00:00Z', 'n'), snapshot[0].cells)
		self.assertEqual(('a.txt', 5, 86400 * 10 ** 9, 'n'), snapshot[0].values)
		self.assertEqual(('b', 'Unknown', 'Unknown', ''), snapshot[1].cells)
		self.assertEqual((), TableSchema((TableColumn('A'),)).snapshot((TableRow(('a',), values=('stale',)),))[0].values)
		for cells in (('a', -1, None, ''), ('a', True, None, ''), ('a', 1.5, None, ''), ('a', '5 B', None, ''),
				('a', None, 2 ** 63, ''), ('a', None, 1.0, ''), (None, None, None, ''), ('a', None, None, 3)):
			with self.subTest(cells=cells), self.assertRaises((TypeError, ValueError)):
				schema.snapshot((TableRow(cells),))
		with self.assertRaises(ValueError):
			schema.snapshot((TableRow(('a', None, 0, ''), highlights=((), (), ((0, 1),), ())),))
		numbers = TableSchema((TableColumn('N', 'numeric'),))
		self.assertEqual(('1,234,567', '1.5', '-2'), tuple(row.cells[0] for row in numbers.snapshot(
			(TableRow((1234567,)), TableRow((1.5,)), TableRow((-2,))))))
		for value in (float('nan'), float('inf')):
			with self.assertRaises(ValueError):
				numbers.snapshot((TableRow((value,)),))
		custom = TableSchema((TableColumn('S', 'numeric', unit='bytes', format=lambda value: '%d KiB' % (value // 1024), missing=''),))
		self.assertEqual(('2 KiB', ''), tuple(row.cells[0] for row in custom.snapshot(
			(TableRow((2048,)), TableRow((None,))))))
		with self.assertRaises(TypeError):
			TableSchema((TableColumn('S', 'numeric', format=lambda value: value),)).snapshot((TableRow((1,)),))
		days = TableSchema((TableColumn('D', 'date', date_display='date'),), dates=utc_dates())
		self.assertEqual(('1970-01-01',), days.snapshot((TableRow((0,)),))[0].cells)

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
		from fman.impl.ui.table_data import TableRow
		from fman.impl.ui.table_filters import compile_filter, operators
		schema = typed_schema()
		day = 86400 * 10 ** 9
		rows = (TableRow(('Alpha.txt', 1024, 0, 'a')),
			TableRow(('beta.txt', 4096, day, 'b')),
			TableRow(('gamma.txt', None, None, 'c')))
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