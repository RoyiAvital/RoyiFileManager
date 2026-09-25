from dataclasses import replace
from io import BytesIO
import os
from threading import Event
from unittest import TestCase
from unittest.mock import patch

from find_files.engine import Collector, Options, Result, Runner, arguments, count_text, date_arguments, records, size_bytes, split_list


class FindFilesTest(TestCase):
	def test_child_start_failure_reaps_and_unregisters(self):
		from find_files.engine import Child
		from unittest.mock import Mock
		runner = Runner(self.options)
		process = Mock()
		with patch('find_files.engine.subprocess.Popen', return_value=process), \
			patch('find_files.engine.Thread', side_effect=RuntimeError('start failed')):
			with self.assertRaises(RuntimeError):
				Child(runner)
		process.kill.assert_called_once()
		process.wait.assert_called_once()
		process.stdout.close.assert_called_once()
		process.stderr.close.assert_called_once()
		self.assertIsNone(runner.child)
	def test_saver_start_failure_retains_pending_values(self):
		from find_files import FindSession, DEFAULTS
		from threading import Lock
		from unittest.mock import Mock
		session = FindSession.__new__(FindSession)
		session.settings = dict(DEFAULTS)
		session.save_lock = Lock()
		session.saving = False
		session.enable_form = Mock()
		values = dict(DEFAULTS, recursive=False)
		with patch('find_files.Thread', side_effect=RuntimeError('start failed')):
			with self.assertRaises(RuntimeError):
				session.changed(values)
		self.assertFalse(session.saving)
		self.assertEqual(values, dict(session.pending_settings))
	def test_fd_command_uses_find_label(self):
		from find_files import FindFiles
		self.assertEqual(('Find files with fd', 'Find files'), FindFiles.aliases)

	def test_settings_and_session_only_inputs(self):
		from find_files import DEFAULTS, options_from_values, settings_snapshot
		settings = settings_snapshot({'pattern_mode': 'bad', 'recursive': 1, 'type': 'ed', 'max_results': None})
		self.assertEqual('glob', settings['pattern_mode'])
		self.assertIs(True, settings['recursive'])
		self.assertEqual('ed', settings['type'])
		self.assertNotIn('max_results', settings)
		options = options_from_values(self.options.root, dict(DEFAULTS, pattern='test', max_results=None, root='ignored', size_label='Size'))
		self.assertEqual('test', options.pattern)
		self.assertIsNone(options.max_results)
		self.assertEqual(self.options.root, options.root)

	def setUp(self):
		self.options = Options(os.path.abspath('.'))

	def test_all_modes_and_flags(self):
		self.assertIsNone(self.options.max_results)
		for mode, flag in (('literal', '--fixed-strings'), ('glob', '--glob'), ('regex', '--regex')):
			args = arguments(replace(self.options, pattern='-report', pattern_mode=mode, extensions='.txt;tar.gz', exclude='build;*.bak'))
			self.assertIn(flag, args)
			self.assertEqual(['--', '-report'], args[-2:])
			self.assertIn('--extension=tar.gz', args)
			self.assertIn('--exclude=build', args)
			self.assertNotIn(self.options.root, args)
		self.assertIn('--no-require-git', args)
		self.assertNotIn('--max-results=10000', args)
		for case, flag in (('sensitive', '--case-sensitive'), ('insensitive', '--ignore-case')):
			self.assertIn(flag, arguments(replace(self.options, case_mode=case)))
		args = arguments(replace(self.options, full_path=True, recursive=False, max_depth=8, hidden=True,
			honor_gitignore=False, follow_symlinks=True, type='ed', max_results=20000))
		for flag in ('--full-path', '--max-depth=1', '--hidden', '--no-ignore-vcs', '--follow', '--type=e', '--type=d', '--max-results=20000'):
			self.assertIn(flag, args)
		self.assertNotIn('--no-ignore', args)

	def test_delivery_declarations_and_assets(self):
		import ast
		import json
		from pathlib import Path
		root = Path(__file__).parents[4]
		plugin = root / 'src/main/resources/base/Plugins/FindFiles'
		spec = (root / 'application.spec').read_text()
		ast.parse(spec)
		self.assertIn("'fd.exe'), 'resources/Plugins/FindFiles/bin'", spec)
		build = (root / 'build.py').read_text()
		ast.parse(build)
		self.assertIn("'FindFiles'", build)
		self.assertIn('fd-find', (root / 'conda-lock.yml').read_text())
		self.assertEqual([{'keys': ['Shift+F7'], 'command': 'find_files'}], json.loads((plugin / 'Key Bindings (Windows).json').read_text()))
		for name in ('LICENSE-MIT', 'THIRDPARTY.yml'):
			self.assertGreater((plugin / 'licenses' / name).stat().st_size, 0)

	def test_exact_sizes(self):
		self.assertEqual(5000000000, size_bytes(5, 'g', 'Size'))
		self.assertEqual(0, size_bytes(0, 'k', 'Size'))
		self.assertIsNone(size_bytes(None, 'b', 'Size'))
		args = arguments(replace(self.options, min_size=1, min_size_unit='k', max_size=1000))
		self.assertIn('--size=+1000b', args)
		self.assertIn('--size=-1000b', args)
		for value in (-1, 1.5, True, '1e3', 2**64):
			with self.subTest(value=value), self.assertRaises(ValueError):
				size_bytes(value, 'b', 'Size')
		with self.assertRaises(ValueError):
			replace(self.options, min_size=2, min_size_unit='g', max_size=1)

	def test_preferences_preserve_unknown_keys_without_query_fields(self):
		from find_files import DEFAULTS, FindSession
		from threading import Lock
		from unittest.mock import Mock
		session = object.__new__(FindSession)
		session.owner = Mock(active=True)
		session.panel = Mock()
		session.panel.cancelled.is_set.return_value = False
		session.save_lock = Lock()
		session.pending_settings = tuple(dict(DEFAULTS, type='ed').items())
		session.saving = True
		loaded = {'unknown': 'preserved'}
		with patch('find_files.load_json', return_value=loaded), patch('find_files.save_json') as save:
			session.save_preferences()
		self.assertEqual({'unknown': 'preserved'}, loaded)
		self.assertEqual(dict(DEFAULTS, type='ed', unknown='preserved'), save.call_args.args[1])
		self.assertFalse(session.saving)

	def test_local_boundary_rejects_dst_gaps_and_ambiguity(self):
		from datetime import datetime
		from find_files.engine import local_boundary
		boundary = datetime(2026, 1, 15)
		stamp = boundary.timetuple()
		with patch('find_files.engine.mktime', side_effect=(10, 10, 10)), patch('find_files.engine.localtime', return_value=stamp):
			local_boundary(boundary)
		with patch('find_files.engine.mktime', side_effect=(10, 10, 20)), patch('find_files.engine.localtime', return_value=stamp):
			with self.assertRaisesRegex(ValueError, 'ambiguous'):
				local_boundary(boundary)
		with patch('find_files.engine.mktime', return_value=10), patch('find_files.engine.localtime', return_value=datetime(2026, 1, 15, 1).timetuple()):
			with self.assertRaisesRegex(ValueError, 'nonexistent'):
				local_boundary(boundary)

	def test_dates_are_independent_inclusive_days(self):
		with patch('find_files.engine.local_boundary'):
			self.assertEqual([], date_arguments(None, None))
			self.assertEqual(['--changed-within=2026-01-14 23:59:59.999999999', '--changed-before=2026-01-16 00:00:00'], date_arguments('2026-01-15', '2026-01-15'))
			self.assertEqual(['--changed-before=2024-03-01 00:00:00'], date_arguments(None, '2024-02-29'))
			self.assertEqual(1, len(date_arguments('2040-01-01', None)))
		for start, end in (('2026-02-30', None), ('20260101', None), ('2026-02-01', '2026-01-01'), (None, '9999-12-31')):
			with self.subTest(start=start, end=end), self.assertRaises(ValueError):
				date_arguments(start, end)
		with patch('find_files.engine.local_boundary', side_effect=ValueError('ambiguous')), self.assertRaisesRegex(ValueError, 'ambiguous'):
			date_arguments('2026-01-01', None)

	def test_lists_and_command_limit(self):
		self.assertEqual(('*.bak', 'name;part', 'dir\\*'), split_list(r'*.bak;name\;part;dir\*', True))
		self.assertEqual(('tar.gz', 'txt'), split_list('.tar.gz;txt'))
		for value in ('txt;;cmd', '*.txt', 'a/b', '.'):
			with self.assertRaises(ValueError):
				split_list(value)
		with self.assertRaisesRegex(ValueError, '24,000'):
			arguments(replace(self.options, pattern='a' * 25000))

	def test_transport_chunks_and_errors(self):
		class Chunks:
			def __init__(self):
				self.chunks = iter((b'one\0tw', b'o\0', b''))
			def read(self, count):
				return next(self.chunks)
		self.assertEqual([b'one', b'two'], list(records(Chunks())))
		for raw in (b'unterminated', b'a' * 131073 + b'\0'):
			with self.assertRaises(ValueError):
				list(records(BytesIO(raw)))

	def test_truncated_output_respects_cancellation(self):
		for cancellation in (None, 'stop', 'external'):
			with self.subTest(cancellation=cancellation), patch('find_files.engine.Child') as child_type:
				cancelled = Event()
				runner = Runner(self.options, cancelled)
				chunks = iter((b'complete.txt\0unfinished', b''))
				def read_chunk(count):
					chunk = next(chunks)
					if not chunk:
						if cancellation == 'stop':
							runner.stop()
						elif cancellation == 'external':
							cancelled.set()
					return chunk
				child = child_type.return_value
				child.process.stdout.read.side_effect = read_chunk
				child.finish.return_value = (0, '')
				result = runner.run()
				self.assertEqual('Stopped' if cancellation else 'Error', result.status)
				self.assertEqual('' if cancellation else 'Incomplete fd output record.', result.reason)
				self.assertFalse(result.complete)
				self.assertEqual(1, result.total)
				self.assertEqual(['complete.txt'], [hit.relative_path for hit in result.rows])
				self.assertEqual(result.status, runner.progress.phase)
				child.finish.assert_called_once_with()

	def test_exact_count_after_table_fills(self):
		collector = Collector(replace(self.options, max_rows=2))
		for index in range(20000):
			collector.accept(('file-%d.txt' % index).encode())
		self.assertEqual(20000, collector.total)
		self.assertEqual(2, len(collector.rows))
		self.assertTrue(collector.limited)
		result = Result(tuple(collector.rows), collector.total, True, True, 'Complete', '')
		self.assertEqual('Showing 2 / 20,000 entries (Maximum table size reached)', count_text(2, result))
		self.assertEqual('Showing 1 / 20,000 entries (Maximum table size reached)', count_text(1, result))
		self.assertIn('total incomplete', count_text(2, replace(result, complete=False, status='Stopped')))

	def test_byte_capacity_exact_capacity_and_paths(self):
		collector = Collector(replace(self.options, max_rows=1))
		collector.accept(b'./-file.txt')
		self.assertFalse(collector.limited)
		self.assertEqual('-file.txt', collector.rows[0].relative_path)
		collector.accept('nonascii-\U0001f600.txt'.encode('utf-8'))
		self.assertTrue(collector.limited)
		collector = Collector(replace(self.options, max_text_bytes=1))
		collector.accept(b'file.txt')
		self.assertEqual(1, collector.total)
		self.assertEqual([], collector.rows)
		for raw in (b'../escape', b'/absolute', b'C:/absolute', b'file:stream', b'', b'\xff'):
			with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeError)):
				collector.accept(raw)