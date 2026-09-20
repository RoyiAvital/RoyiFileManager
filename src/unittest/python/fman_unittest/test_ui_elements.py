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

	def test_optional_column_roles_and_default_resolution(self):
		from fman.impl.ui.table_data import TableRow, TableSchema
		row = TableRow('one', ('nested/file.txt', 'C:\\elsewhere'))
		resolver = Mock(side_effect=AssertionError('Not a path cell'))
		self.assertIsNone(TableSchema(2, ('A', 'B'), resolve_path=resolver).target(row, 0))
		resolver.assert_not_called()
		schema = TableSchema(2, ('File', 'Folder'), 0, 1, base_path='C:\\base')
		self.assertEqual('C:\\base\\nested\\file.txt', schema.target(row, 0))
		self.assertEqual('C:\\elsewhere', schema.target(row, 1))
		self.assertIsNone(TableSchema(2, ('A', 'B'), 0).target(row, 0))
		self.assertIsNone(schema.target(TableRow('empty', ('', '')), 0))
		for invalid in (True, '0', -1, 2):
			with self.subTest(invalid=invalid), self.assertRaises((TypeError, ValueError)):
				TableSchema(2, ('A', 'B'), invalid)
		with self.assertRaises(ValueError):
			TableSchema(2, ('A', 'B'), 0, 0)

	def test_paths_are_lexical_and_custom_resolver_is_authoritative(self):
		from fman.impl.ui.table_data import TableRow, TableSchema
		from unittest.mock import patch
		schema = TableSchema(1, ('Path',), 0, base_path='C:\\base')
		with patch('os.stat', side_effect=AssertionError('No filesystem probe')):
			for value, expected in (('..\\a.txt', 'C:\\a.txt'),
					('\\\\server\\share\\a.txt', '\\\\server\\share\\a.txt'),
					(' spaced .txt', 'C:\\base\\ spaced .txt')):
				self.assertEqual(expected, schema.target(TableRow(value, (value,)), 0))
			for value in ('C:relative', '\\rooted', 'file:///C:/a', 'https://a', 'bad\x00path'):
				with self.subTest(value=value), self.assertRaises(ValueError):
					schema.target(TableRow('row', (value,)), 0)
		row = TableRow('label', ('Friendly label',), ('D:\\actual.txt',))
		self.assertEqual('D:\\actual.txt', TableSchema(1, ('Path',), 0,
			resolve_path=lambda record, column: record.value[0]).target(row, 0))
		self.assertIsNone(TableSchema(1, ('Path',), 0,
			resolve_path=lambda record, column: None).target(row, 0))
		with self.assertRaises(ValueError):
			TableSchema(1, ('Path',), 0, resolve_path=lambda *args: 'relative').target(row, 0)

	def test_snapshot_schema_bounds_and_immutable_payload(self):
		from fman.impl.ui.table_data import TableRow, TableSchema
		from unittest.mock import patch
		schema = TableSchema(2, ('Path', 'Snippet'))
		row = TableRow('one', ['one', 'text'], ('value',), ((), ((0, 4),)))
		provider = Mock(return_value=[row])
		self.assertEqual((row,), schema.snapshot(provider))
		provider.assert_called_once_with()
		for rows in ([row, row], [TableRow('short', ('one',))],
				[TableRow('mutable', ('one', 'two'), {})],
				[TableRow('span', ('one', 'two'), highlights=((), ((0, 4),))) ]):
			with self.assertRaises((TypeError, ValueError)):
				schema.snapshot(lambda: rows)
		with patch('fman.impl.ui.table_data.MAX_ROWS', 1), self.assertRaises(ValueError):
			schema.snapshot(lambda: (TableRow(str(index), ('a', 'b')) for index in range(3)))
		with patch('fman.impl.ui.table_data.MAX_TEXT_BYTES', 1), self.assertRaises(ValueError):
			schema.snapshot(provider)

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


class UiStateTest(TestCase):
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