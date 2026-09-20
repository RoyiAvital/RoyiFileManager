from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from search_files.engine import Collector, Options, Runner, command_fits, masks, records


class SearchEngineTest(TestCase):
	def test_search_command_label(self):
		from fman.impl.plugins.command_registry import PaneCommandRegistry
		from threading import Event
		from unittest.mock import Mock
		from search_files import SearchFiles
		self.assertEqual(('Search files', 'Search text in files'), SearchFiles.aliases)
		registry = PaneCommandRegistry(Mock(), Mock())
		registry.register_command('search_files', SearchFiles)
		pane = Mock()
		pane.get_path.return_value = 'file:///C:/root'
		self.assertTrue(registry.is_command_visible('search_files', pane))
		completed = Event()
		with patch.object(SearchFiles, '__call__', side_effect=completed.set) as search:
			registry.execute_command('search_files', {}, pane)
			self.assertTrue(completed.wait(2), 'Search command did not run')
			search.assert_called_once()

	def test_settings_survive_plugin_rename(self):
		from fman.impl.plugins.config import Config
		from search_files import DEFAULTS, LEGACY_SETTINGS_NAME, SETTINGS_NAME, SearchSession, load_settings, settings_snapshot
		from threading import Event, Lock
		from types import SimpleNamespace
		import search_files
		plugin_root = Path(search_files.__file__).parents[1]
		with TemporaryDirectory() as root:
			config = Config('Windows')
			config.add_dir(str(plugin_root))
			config.add_dir(root)
			legacy = {'recursive': False, 'max_rows': 37, 'name_regex': True, 'other': 7}
			config.save_json(LEGACY_SETTINGS_NAME, legacy)
			legacy_path = Path(root, 'SearchFileContent (Windows).json')
			original = legacy_path.read_bytes()
			with patch('search_files.load_json', side_effect=config.load_json), \
				patch('search_files.save_json', side_effect=config.save_json):
				self.assertEqual(dict(DEFAULTS, recursive=False, max_rows=37, name_mode='regex'),
					settings_snapshot(load_settings()))
				self.assertFalse(Path(root, 'SearchFiles (Windows).json').exists())
				config.save_json(SETTINGS_NAME, {'recursive': True, 'name_mode': 'literal'})
				settings = settings_snapshot(load_settings())
				self.assertEqual(dict(DEFAULTS, max_rows=37, name_mode='literal'), settings)
				session = SearchSession.__new__(SearchSession)
				session.save_lock = Lock()
				session.pending_settings = tuple(settings.items())
				session.saving = True
				session.owner = SimpleNamespace(active=True)
				session.panel = SimpleNamespace(cancelled=Event())
				session.save_preferences()
			reloaded = Config('Windows')
			reloaded.add_dir(str(plugin_root))
			reloaded.add_dir(root)
			self.assertEqual(dict(settings, other=7), reloaded.load_json(SETTINGS_NAME))
			self.assertEqual(original, legacy_path.read_bytes())

	def test_name_only_options(self):
		for mode in ('glob', 'literal', 'regex'):
			self.assertTrue(Options('C:\\root', '', 'report', name_mode=mode).names_only)
		self.assertFalse(Options('C:\\root', 'needle').names_only)
		with self.assertRaisesRegex(ValueError, 'Enter a file name or content pattern'):
			Options('C:\\root', '')
		with self.assertRaisesRegex(ValueError, 'single line'):
			Options('C:\\root', 'a\nb', '*.txt')

	def test_name_only_lists_binary_empty_and_regular_files(self):
		with TemporaryDirectory() as root:
			for name, content in (('report.bin', b'\x00binary'), ('report.txt', b''), ('other.txt', b'content')):
				Path(root, name).write_bytes(content)
			for mode, pattern in (('glob', 'report.*'), ('literal', 'report'), ('regex', '^report\\.')):
				with self.subTest(mode=mode):
					runner = Runner(Options(root, '', pattern, name_mode=mode))
					with patch.object(runner, 'content_args', side_effect=AssertionError('No content child allowed')):
						result = runner.run()
					self.assertEqual('Complete', result.status, result.reason)
					self.assertEqual({'report.bin', 'report.txt'}, {hit.relative_path for hit in result.rows})
					self.assertTrue(all((hit.line, hit.column, hit.offset, hit.snippet, hit.spans) == (0, 0, 0, '', ()) for hit in result.rows))
					self.assertEqual(2, result.progress.files)
					self.assertEqual(set(), runner.children)

	def test_name_only_budget_fits_table_payload(self):
		from fman.impl.ui.table_data import TableSchema
		from fman.ui import TableRow
		from fman.url import as_url
		from search_files import Location
		from search_files.engine import Limited
		collector = Collector(Options('C:\\root', '', '*'))
		with self.assertRaises(Limited):
			for index in range(10000):
				collector.accept_path(str(Path('C:\\root', *(['\u754c' * 180] * 3), 'report%04d.txt' % index)))
		self.assertGreater(len(collector.rows), 0)
		self.assertLess(len(collector.rows), 10000)
		rows = tuple(TableRow('123456789:%d' % index, (hit.relative_path, hit.snippet),
			Location(as_url(hit.path), hit.path, hit.line, hit.column, hit.spans), ((), hit.spans))
			for index, hit in enumerate(collector.rows))
		schema = TableSchema(2, ('File Path', 'Snippet'), file_path_column=0, base_path='C:\\root')
		self.assertEqual(rows, schema.snapshot(lambda: rows))
		with self.assertRaises(ValueError):
			Collector(Options('C:\\root', '', '*')).accept_path('C:\\outside\\file.txt')

	def test_pattern_mode_settings_migration(self):
		from search_files import DEFAULTS, SETTINGS_NAME, settings_snapshot
		import search_files
		base = json.loads((Path(search_files.__file__).parents[1] / SETTINGS_NAME).read_text(encoding='utf-8'))
		self.assertEqual(DEFAULTS, settings_snapshot(base))
		legacy = dict(base, name_regex=True, content_regex=True)
		self.assertEqual('regex', settings_snapshot(legacy)['name_mode'])
		self.assertEqual('regex', settings_snapshot(legacy)['content_mode'])
		self.assertEqual('literal', settings_snapshot(dict(legacy, name_mode='literal'))['name_mode'])
		self.assertEqual('glob', settings_snapshot(dict(legacy, content_mode='glob'))['content_mode'])
		self.assertEqual('regex', settings_snapshot(dict(legacy, content_mode='invalid'))['content_mode'])
		self.assertEqual('glob', settings_snapshot({'name_regex': False})['name_mode'])
		self.assertEqual('literal', settings_snapshot({'content_regex': False})['content_mode'])
		self.assertEqual('literal', settings_snapshot({'content_mode': []})['content_mode'])

	def test_mode_save_removes_old_flags_and_preserves_other_settings(self):
		from search_files import DEFAULTS, SearchSession
		from threading import Event, Lock
		from types import SimpleNamespace
		session = SearchSession.__new__(SearchSession)
		session.save_lock = Lock()
		session.pending_settings = tuple(dict(DEFAULTS, content_mode='glob').items())
		session.saving = True
		session.owner = SimpleNamespace(active=True)
		session.panel = SimpleNamespace(cancelled=Event())
		with patch('search_files.load_json', return_value={'name_regex': True, 'content_regex': False, 'other': 7}), \
				patch('search_files.save_json') as save:
			session.save_preferences()
			saved = save.call_args.args[1]
			self.assertNotIn('name_regex', saved)
			self.assertNotIn('content_regex', saved)
			self.assertEqual('glob', saved['content_mode'])
			self.assertEqual(7, saved['other'])
			self.assertFalse(session.saving)

	def test_content_glob_dialect(self):
		import fnmatch
		import re
		from search_files.engine import glob_to_regex
		patterns = ('*', '**', '*a*b*', '?', '[abc]', '[!abc]', '[a-z]', '[-a]', '[a-]',
			'[]]', '[[]', '[*]', '[?]', '[&~|^]', 'a.b+(x){2}$', 'C:\\cuda', 'a/b', 'caf\u00e9*')
		values = ('', 'a', 'b', 'x', 'a-b', 'ab', 'xaaby', ']', '[', '*', '?', '&', '^',
			'a.b+(x){2}$', 'C:\\cuda', 'a/b', 'caf\u00e9 noir')
		for pattern in patterns:
			for value in values:
				with self.subTest(pattern=pattern, value=value):
					self.assertEqual(fnmatch.fnmatchcase(value, pattern), bool(re.fullmatch(glob_to_regex(pattern), value)))
		for pattern in ('[', '[]', '[!]', '[z-a]', '*\n*', '\x00'):
			with self.subTest(pattern=pattern), self.assertRaises(ValueError):
				glob_to_regex(pattern)
		for pattern in ('[--a]', '[a--]'):
			self.assertIsNotNone(re.fullmatch(glob_to_regex(pattern), '-'))
			self.assertIsNotNone(re.fullmatch(glob_to_regex(pattern), 'a'))
			self.assertIsNone(re.fullmatch(glob_to_regex(pattern), '0'))

	def test_real_engine_three_content_modes(self):
		with TemporaryDirectory() as root:
			Path(root, 'CudaText.cmd').write_bytes('cuda\r\necho CUDA here\r\na.b+(x){2}$\r\n\r\ncaf\u00e9\r\n'.encode('utf-8'))
			cases = (('literal', 'cuda', (1, 2)), ('glob', 'cuda', (1, 2)),
				('glob', '*cuda*', (1, 2)), ('regex', '^cuda$', (1,)),
				('glob', 'a.b+(x){2}$', (3,)), ('glob', '[!x]ud[a-z]', (1, 2)),
				('glob', 'caf?', (5,)), ('glob', '*', (1, 2, 3, 4, 5)),
				('glob', '**c*u*d*a**', (1, 2)))
			for mode, pattern, lines in cases:
				with self.subTest(mode=mode, pattern=pattern):
					result = Runner(Options(root, pattern, '*.cmd', content_mode=mode)).run()
					self.assertEqual('Complete', result.status, result.reason)
					self.assertEqual(lines, tuple(hit.line for hit in result.rows))
			result = Runner(Options(root, '[z-a]', content_mode='glob')).run()
			self.assertEqual('Error', result.status)
			self.assertFalse(result.validated)
			for value in ('[', '*', '?', ']', '&', '^', 'C:\\cuda', 'a/b'):
				Path(root, 'symbols.txt').write_text(value, encoding='utf-8')
				pattern = {'[': '[[]', '*': '[*]', '?': '[?]', ']': '[]]'}.get(value, value)
				result = Runner(Options(root, pattern, '*.txt', content_mode='glob')).run()
				self.assertEqual('Complete', result.status, result.reason)
				self.assertEqual(1, len(result.rows), value)

	def test_content_glob_substring_spans_and_wildcard_only(self):
		with TemporaryDirectory() as root:
			Path(root, 'line.txt').write_bytes(b'echo PORTABLE EF Commander\r\n')
			for pattern in ('Commander', '*Commander*', 'Comm*der', '?ommander', '[Cc]ommander'):
				with self.subTest(pattern=pattern):
					runner = Runner(Options(root, pattern, '*.txt', content_mode='glob'))
					result = runner.run()
					self.assertNotIn('--line-regexp', runner.content_args())
					self.assertEqual('Complete', result.status, result.reason)
					self.assertEqual(1, len(result.rows))
					self.assertEqual(((17, 26),), result.rows[0].spans)
			result = Runner(Options(root, 'EF*Commander', '*.txt', content_mode='glob')).run()
			self.assertEqual(((14, 26),), result.rows[0].spans)
			result = Runner(Options(root, '^Commande$', '*.txt', content_mode='regex')).run()
			self.assertEqual((), result.rows)
			Path(root, 'line.txt').write_bytes(b'a' * 100000 + b'\n\n')
			for pattern in ('*', '**'):
				with self.subTest(pattern=pattern):
					result = Runner(Options(root, pattern, '*.txt', content_mode='glob')).run()
					self.assertEqual('Complete', result.status, result.reason)
					self.assertEqual((1, 2), tuple(hit.line for hit in result.rows))
					self.assertEqual(((0, 506),), result.rows[0].spans)
					self.assertEqual('', result.rows[1].snippet)
					self.assertTrue(all(span == (0, 0) for span in result.rows[1].spans))

	def test_real_engine_three_filename_modes(self):
		with TemporaryDirectory() as root:
			for filename in ('CudaText.cmd', 'Cuda[1].cmd', 'other.txt'):
				Path(root, filename).write_text('needle', encoding='utf-8')
			for mode, pattern, count in (('literal', 'Cuda', 2), ('literal', '[1]', 1),
					('literal', '*.cmd', 0), ('glob', '*.cmd', 2), ('regex', '^CudaText\\.cmd$', 1)):
				result = Runner(Options(root, 'needle', pattern, name_mode=mode)).run()
				self.assertEqual('Complete', result.status, result.reason)
				self.assertEqual(count, len(result.rows), (mode, pattern))
			for name_mode, name in (('literal', '.cmd'), ('glob', '*.cmd'), ('regex', '\\.cmd$')):
				for content_mode, content in (('literal', 'needle'), ('glob', '*eed*'), ('regex', 'n[e]+dle')):
					with self.subTest(name_mode=name_mode, content_mode=content_mode):
						result = Runner(Options(root, content, name, name_mode=name_mode, content_mode=content_mode)).run()
						self.assertEqual('Complete', result.status, result.reason)
						self.assertEqual(2, len(result.rows))
		self.assertEqual('regex', Options('C:\\root', 'text', name_regex=True).name_mode)
		with self.assertRaises(ValueError):
			Options('C:\\root', 'text', content_mode='unknown')

	def test_engine_resolution_uses_conda_or_bundle_without_io(self):
		from search_files import engine
		with patch.object(engine.sys, 'prefix', 'C:\\conda'), \
				patch.object(engine.sys, 'frozen', False, create=True), \
				patch.object(Path, 'open', side_effect=AssertionError('Unexpected verification I/O')), \
				patch.object(Path, 'stat', side_effect=AssertionError('Unexpected verification I/O')):
			self.assertEqual('C:\\conda\\bin\\rg.exe', engine.resolve_engine())
			with patch.object(engine.sys, 'frozen', True):
				self.assertEqual(str(Path(engine.__file__).parent.parent / 'bin/rg.exe'), engine.resolve_engine())

	def test_bounded_pipes_malformed_output_and_cancellation(self):
		import sys
		from search_files.engine import Cancelled
		runner = Runner(Options('C:\\root', 'needle'))
		command = [sys.executable, '-c',
			"import sys; sys.stderr.buffer.write(b'e'*262144); sys.stderr.flush(); "
			"data=sys.stdin.buffer.read(); print('{\"type\":\"summary\",\"data\":{}}')"]
		messages = []
		runner.read_child(command, messages.append, b'x' * 262144)
		self.assertEqual(1, len(messages))
		self.assertEqual(65536, len(runner.error))
		self.assertEqual(set(), runner.children)
		with self.assertRaises(ValueError):
			runner.read_child([sys.executable, '-c', "print('invalid JSON')"], lambda message: None)
		self.assertEqual(set(), runner.children)
		command = [sys.executable, '-c',
			"import sys; record=b'{\"type\":\"summary\",\"data\":{}}\\n'; "
			"sys.stdout.buffer.write(record*100000); sys.stdout.flush()"]
		with self.assertRaises(Cancelled):
			runner.read_child(command, lambda message: runner.stop())
		self.assertEqual(set(), runner.children)

	def test_junction_is_not_followed(self):
		import _winapi
		if not hasattr(_winapi, 'CreateJunction'):
			self.skipTest('Native junction creation is unavailable.')
		with TemporaryDirectory() as root, TemporaryDirectory() as outside:
			Path(outside, 'outside.txt').write_text('needle', encoding='utf-8')
			junction = Path(root, 'junction')
			_winapi.CreateJunction(outside, str(junction))
			try:
				for regex in (False, True):
					result = Runner(Options(root, 'needle', name_regex=regex)).run()
					self.assertEqual('Complete', result.status, result.reason)
					self.assertEqual((), result.rows)
				self.assertFalse(Runner(Options(root, 'needle')).eligible(str(junction / 'outside.txt')))
				for mode, name in (('glob', '*.txt'), ('literal', '.txt'), ('regex', '\\.txt$')):
					result = Runner(Options(root, '', name, name_mode=mode)).run()
					self.assertEqual('Complete', result.status, result.reason)
					self.assertEqual((), result.rows)
				result = Runner(Options(str(junction), 'needle')).run()
				self.assertEqual('Error', result.status)
				self.assertFalse(result.validated)
			finally:
				junction.rmdir()

	def test_search_slot_survives_engine_reload(self):
		from importlib import reload
		from threading import Event
		import search_files.engine as engine
		started, release, finished = Event(), Event(), Event()
		runner = engine.Runner(engine.Options('C:\\root', 'needle'))
		def blocked():
			started.set()
			release.wait(5)
			return None
		runner.run = blocked
		try:
			self.assertTrue(runner.start(lambda result: finished.set()))
			self.assertTrue(started.wait(2))
			reload(engine)
			replacement = engine.Runner(engine.Options('C:\\root', 'needle'))
			self.assertFalse(replacement.start(lambda result: None))
		finally:
			release.set()
			self.assertTrue(finished.wait(2))

	def test_plugin_uses_plain_public_ui_only(self):
		import search_files
		for source in Path(search_files.__file__).parent.glob('*.py'):
			content = source.read_text(encoding='utf-8')
			for forbidden in ('PyQt', 'fman.impl', '._widget', '.build(', '.show('):
				self.assertNotIn(forbidden, content, str(source))
		self.assertEqual(search_files.DEFAULTS, search_files.settings_snapshot(None))
		self.assertEqual(10000, search_files.settings_snapshot({'max_rows': -1})['max_rows'])

	def test_masks_and_transport_bounds(self):
		self.assertEqual(('*.txt', '!secret*'), masks('!secret*;*.txt'))
		self.assertEqual((), masks(''))
		with self.assertRaises(ValueError):
			masks('nested/*.txt')
		self.assertFalse(command_fits(['rg', 'x' * 24000]))
		self.assertEqual([b'one', b'two'], list(records(BytesIO(b'one\x00two\x00'), b'\x00')))
		for content in (b'incomplete', b'toolong\n'):
			with self.assertRaises(ValueError):
				list(records(BytesIO(content), maximum=4))

	def test_binary_matches_are_discarded_at_end(self):
		options = Options('C:\\root', 'needle')
		collector = Collector(options)
		path = {'text': 'C:\\root\\binary.txt'}
		collector.accept({'type': 'begin', 'data': {'path': path}})
		collector.accept({'type': 'match', 'data': {'path': path,
			'lines': {'text': 'needle\x00'}, 'line_number': 1, 'absolute_offset': 0,
			'submatches': [{'start': 0, 'end': 6}]}})
		self.assertEqual([], collector.rows)
		collector.accept({'type': 'end', 'data': {'path': path, 'binary_offset': 6}})
		self.assertEqual([], collector.rows)
		self.assertEqual(0, collector.row_count)

	def test_real_engine_glob_regex_unicode_and_limits(self):
		with TemporaryDirectory() as root:
			folder = Path(root)
			(folder / 'nested').mkdir()
			(folder / 'report.txt').write_text('needle\nother\nneedle', encoding='utf-8')
			(folder / 'nested/report.txt').write_text('\u00e9 needle\r\n', encoding='utf-16')
			(folder / 'binary.txt').write_bytes(b'\x00needle\x00')
			(folder / '.hidden.txt').write_text('needle', encoding='utf-8')
			result = Runner(Options(root, 'needle', '*.txt')).run()
			self.assertEqual('Complete', result.status, result.reason)
			self.assertEqual(4, len(result.rows))
			self.assertTrue(all('\x00' not in hit.snippet for hit in result.rows))
			result = Runner(Options(root, 'needle', '^report\\.txt$', name_regex=True)).run()
			self.assertEqual('Complete', result.status, result.reason)
			self.assertEqual(3, len(result.rows))
			unicode_hit = next(hit for hit in result.rows if 'nested' in hit.path)
			self.assertEqual(3, unicode_hit.column)
			self.assertEqual(((2, 8),), unicode_hit.spans)
			result = Runner(Options(root, 'needle', '*.txt', max_file_lines=1)).run()
			self.assertEqual('Limited', result.status, result.reason)

	def test_explicit_file_guards_and_invalid_regex(self):
		with TemporaryDirectory() as root:
			folder = Path(root)
			(folder / '.hidden.txt').write_text('needle', encoding='utf-8')
			(folder / 'big.txt').write_text('needle' * 10, encoding='utf-8')
			runner = Runner(Options(root, 'needle', name_regex=True, max_file_bytes=16))
			self.assertFalse(runner.eligible(str(folder / '.hidden.txt')))
			self.assertFalse(runner.eligible(str(folder / 'big.txt')))
			self.assertFalse(runner.eligible(str(folder)))
			result = Runner(Options(root, '(', content_regex=True)).run()
			self.assertEqual('Error', result.status)
			self.assertIn('regex', result.reason)

	def test_cancelled_run_does_not_resolve_engine(self):
		runner = Runner(Options('C:\\root', 'needle'))
		runner.stop()
		with patch('search_files.engine.resolve_engine') as resolve:
			self.assertEqual('Stopped', runner.run().status)
		resolve.assert_not_called()