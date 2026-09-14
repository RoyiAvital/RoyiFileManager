from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from search_file_content.engine import Collector, Options, Runner, command_fits, masks, records


class SearchEngineTest(TestCase):
	def test_pattern_mode_settings_migration(self):
		from search_file_content import DEFAULTS, SETTINGS_NAME, settings_snapshot
		import search_file_content
		base = json.loads((Path(search_file_content.__file__).parents[1] / SETTINGS_NAME).read_text(encoding='utf-8'))
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
		from search_file_content import DEFAULTS, SearchSession
		from threading import Event, Lock
		from types import SimpleNamespace
		session = SearchSession.__new__(SearchSession)
		session.save_lock = Lock()
		session.pending_settings = tuple(dict(DEFAULTS, content_mode='glob').items())
		session.saving = True
		session.owner = SimpleNamespace(active=True)
		session.panel = SimpleNamespace(cancelled=Event())
		with patch('search_file_content.load_json', return_value={'name_regex': True, 'content_regex': False, 'other': 7}), \
				patch('search_file_content.save_json') as save:
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
		from search_file_content.engine import glob_to_regex
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
			cases = (('literal', 'cuda', (1, 2)), ('glob', 'cuda', (1,)),
				('glob', '*cuda*', (1, 2)), ('regex', '^cuda$', (1,)),
				('glob', 'a.b+(x){2}$', (3,)), ('glob', '[!x]ud[a-z]', (1,)),
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
		from search_file_content import engine
		with patch.object(engine.sys, 'prefix', 'C:\\conda'), \
				patch.object(engine.sys, 'frozen', False, create=True), \
				patch.object(Path, 'open', side_effect=AssertionError('Unexpected verification I/O')), \
				patch.object(Path, 'stat', side_effect=AssertionError('Unexpected verification I/O')):
			self.assertEqual('C:\\conda\\bin\\rg.exe', engine.resolve_engine())
			with patch.object(engine.sys, 'frozen', True):
				self.assertEqual(str(Path(engine.__file__).parent.parent / 'bin/rg.exe'), engine.resolve_engine())

	def test_bounded_pipes_malformed_output_and_cancellation(self):
		import sys
		from search_file_content.engine import Cancelled
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
				result = Runner(Options(str(junction), 'needle')).run()
				self.assertEqual('Error', result.status)
				self.assertFalse(result.validated)
			finally:
				junction.rmdir()

	def test_search_slot_survives_engine_reload(self):
		from importlib import reload
		from threading import Event
		import search_file_content.engine as engine
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
		import search_file_content
		for source in Path(search_file_content.__file__).parent.glob('*.py'):
			content = source.read_text(encoding='utf-8')
			for forbidden in ('PyQt', 'fman.impl', '._widget', '.build(', '.show('):
				self.assertNotIn(forbidden, content, str(source))
		self.assertEqual(search_file_content.DEFAULTS, search_file_content.settings_snapshot(None))
		self.assertEqual(10000, search_file_content.settings_snapshot({'max_rows': -1})['max_rows'])

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
		with patch('search_file_content.engine.resolve_engine') as resolve:
			self.assertEqual('Stopped', runner.run().status)
		resolve.assert_not_called()