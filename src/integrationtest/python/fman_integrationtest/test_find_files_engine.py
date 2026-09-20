from dataclasses import replace
from datetime import datetime
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
from unittest import TestCase, skipUnless
from unittest.mock import patch

from find_files.engine import Options, Runner, resolve_engine


@skipUnless(Path(resolve_engine()).is_file(), 'The environment fd.exe is not installed')
class FindFilesEngineTest(TestCase):
	def setUp(self):
		self.temp = TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root = Path(self.temp.name)
		self.options = Options(str(self.root), max_results=None)

	def put(self, name, data=b''):
		path = self.root / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_bytes(data)
		return path

	def search(self, **changes):
		result = Runner(replace(self.options, **changes)).run()
		self.assertEqual('Complete', result.status, result.reason)
		self.assertTrue(result.complete)
		return result

	def names(self, **changes):
		return {hit.relative_path.replace('\\', '/') for hit in self.search(**changes).rows}

	def test_patterns_case_extensions_excludes_and_depth(self):
		for name in ('Report-upper.TXT', 'report-lower.txt', 'a+b.txt', '-dash.txt', 'bundle.tar.gz', 'sub/deep.txt', 'emptyfolder/.keep'):
			self.put(name)
		self.assertEqual({'a+b.txt'}, self.names(pattern='a+b', pattern_mode='literal'))
		self.assertEqual({'a+b.txt'}, self.names(pattern=r'^a\+b', pattern_mode='regex'))
		self.assertEqual({'Report-upper.TXT'}, self.names(pattern='Report', pattern_mode='literal'))
		self.assertEqual({'Report-upper.TXT', 'report-lower.txt'}, self.names(pattern='report', pattern_mode='literal'))
		self.assertEqual({'report-lower.txt'}, self.names(pattern='report', pattern_mode='literal', case_mode='sensitive'))
		self.assertEqual({'Report-upper.TXT', 'report-lower.txt'}, self.names(pattern='REPORT', pattern_mode='literal', case_mode='insensitive'))
		self.assertEqual({'bundle.tar.gz'}, self.names(extensions='.tar.gz'))
		self.assertEqual({'-dash.txt', 'a+b.txt'}, self.names(extensions='txt', exclude='*eport*;sub/*', recursive=False))
		self.assertNotIn('sub/deep.txt', self.names(max_depth=1))
		self.assertEqual({'sub/deep.txt'}, self.names(pattern='*sub*', full_path=True))

	def test_hidden_and_vcs_rules_are_independent(self):
		self.put('.gitignore', b'ignored.txt\n')
		self.put('.ignore', b'other.txt\n')
		for name in ('ignored.txt', 'other.txt', 'visible.txt', '.hidden.txt'):
			self.put(name)
		self.assertEqual({'visible.txt'}, self.names())
		self.assertEqual({'ignored.txt', 'visible.txt'}, self.names(honor_gitignore=False))
		self.assertIn('.hidden.txt', self.names(hidden=True))
		self.assertNotIn('ignored.txt', self.names(hidden=True))
		(self.root / '.git').mkdir()
		self.assertNotIn('ignored.txt', self.names())

	def test_types_and_exact_sizes(self):
		self.put('empty.txt')
		self.put('thousand.txt', b'x' * 1000)
		self.put('large.txt', b'x' * 1001)
		(self.root / 'folder').mkdir()
		self.assertEqual({'empty.txt'}, self.names(type='ef'))
		self.assertEqual({'folder'}, self.names(type='ed'))
		self.assertEqual({'folder'}, self.names(type='d'))
		self.assertEqual({'thousand.txt'}, self.names(min_size=1, min_size_unit='k', max_size=1000))
		self.assertEqual({'empty.txt'}, self.names(min_size=0, max_size=0))
		self.assertIsNone(self.search(type='d').rows[0].size)

	def test_exact_date_boundaries(self):
		start = int(datetime(2026, 1, 15).timestamp()) * 1000000000
		end = int(datetime(2026, 1, 16).timestamp()) * 1000000000
		for name, stamp in (('before', start - 100), ('start', start), ('inside', start + 100), ('last', end - 100), ('end', end)):
			path = self.put(name)
			os.utime(path, ns=(stamp, stamp))
		self.assertEqual({'start', 'inside', 'last'}, self.names(start_date='2026-01-15', end_date='2026-01-15'))
		self.assertEqual({'start', 'inside', 'last', 'end'}, self.names(start_date='2026-01-15'))
		self.assertEqual({'before', 'start', 'inside', 'last'}, self.names(end_date='2026-01-15'))

	def test_counts_beyond_table_and_explicit_search_limit(self):
		for index in range(21):
			self.put('match-%d.txt' % index)
		self.put('Unicode-\U0001f600.txt')
		result = self.search(max_rows=3)
		self.assertEqual(22, result.total)
		self.assertEqual(3, len(result.rows))
		self.assertTrue(result.table_limited)
		result = self.search(max_text_bytes=1)
		self.assertEqual(22, result.total)
		self.assertEqual((), result.rows)
		result = Runner(replace(self.options, max_results=5, max_rows=3)).run()
		self.assertEqual(5, result.total)
		self.assertFalse(result.complete)
		self.assertEqual('Search limit reached', result.status)

	def test_empty_invalid_pattern_and_missing_root(self):
		self.assertEqual(0, self.search().total)
		result = Runner(replace(self.options, pattern='[', pattern_mode='regex')).run()
		self.assertEqual('Error', result.status)
		self.assertTrue(result.reason)
		result = Runner(replace(self.options, root=str(self.root / 'missing'))).run()
		self.assertEqual('Error', result.status)

	def test_links_and_cycles(self):
		target = self.put('sub/target.txt', b'abc')
		try:
			(self.root / 'link.txt').symlink_to(target)
			(self.root / 'broken.txt').symlink_to(self.root / 'missing')
			(self.root / 'sub/loop').symlink_to(self.root, target_is_directory=True)
		except OSError:
			self.skipTest('Symbolic links require Windows privilege')
		self.assertIn('link.txt', self.names(type='l'))
		self.assertNotIn('link.txt', self.names())
		result = Runner(replace(self.options, follow_symlinks=True)).run()
		self.assertIn('link.txt', {hit.relative_path for hit in result.rows})
		self.assertLess(result.total, 10)

	def test_stop_reaps_child(self):
		seen, finished = Event(), Event()
		runner = Runner(self.options)
		accept = runner.collector.accept
		def observe(raw):
			accept(raw)
			seen.set()
		command = [sys.executable, '-c', "import os,threading; os.write(1,b'match.txt\\0unfinished'); threading.Event().wait()"]
		results = []
		def run():
			results.append(runner.run())
			finished.set()
		with patch('find_files.engine.arguments', return_value=command), patch.object(runner.collector, 'accept', side_effect=observe):
			thread = Thread(target=run)
			thread.start()
			try:
				self.assertTrue(seen.wait(5))
				process = runner.child.process
				started = monotonic()
				runner.stop()
				self.assertTrue(finished.wait(1))
				self.assertLess(monotonic() - started, 1)
				self.assertIsNotNone(process.poll())
				self.assertEqual('Stopped', results[0].status)
				self.assertEqual('', results[0].reason)
				self.assertEqual(1, results[0].total)
				self.assertEqual(['match.txt'], [hit.relative_path for hit in results[0].rows])
			finally:
				runner.stop()
				thread.join(5)

	def test_runner_claim_survives_blocked_metadata_and_stop(self):
		self.put('match.txt')
		entered, release, completed = Event(), Event(), Event()
		runner = Runner(self.options)
		original_stat = os.stat
		results = []
		def blocked(path, *args, **kwargs):
			if str(path).endswith('match.txt'):
				entered.set()
				if not release.wait(5):
					raise RuntimeError('Metadata test release timed out')
			return original_stat(path, *args, **kwargs)
		def finished(result):
			results.append(result)
			completed.set()
		with patch('find_files.engine.os.stat', side_effect=blocked):
			self.assertTrue(runner.start(finished))
			try:
				self.assertTrue(entered.wait(5))
				started = monotonic()
				runner.stop()
				self.assertLess(monotonic() - started, 1)
				self.assertFalse(Runner(self.options).start(finished))
			finally:
				release.set()
				self.assertTrue(completed.wait(5))
		self.assertEqual('Stopped', results[0].status)
		completed.clear()
		self.assertTrue(Runner(self.options).start(finished))
		self.assertTrue(completed.wait(5))
		self.assertTrue(results[-1].complete)

	def test_stderr_and_exit_counts_are_incomplete(self):
		for code in (0, 2):
			command = [sys.executable, '-c', "import os,sys; os.write(1,b'match.txt\\0'); os.write(2,b'traversal warning'); sys.exit(%d)" % code]
			with self.subTest(code=code), patch('find_files.engine.arguments', return_value=command):
				result = Runner(self.options).run()
			self.assertEqual(1, result.total)
			self.assertFalse(result.complete)
			self.assertIn('traversal warning', result.reason)
			self.assertEqual('Error' if code else 'Incomplete', result.status)

	@skipUnless(os.environ.get('FIND_FILES_PERFORMANCE_TESTS') == '1', 'Opt-in 200,100-file performance fixture')
	def test_large_tree_exact_count_and_bounded_storage(self):
		import json
		import tracemalloc
		from fman.ui import TableRow
		from fman.impl.ui.table_data import TableSchema
		for directory in range(100):
			folder = self.root / ('folder-%03d' % directory)
			folder.mkdir()
			for index in range(2001):
				(folder / ('file-%04d.txt' % index)).touch()
		reports = []
		for pattern, expected in (('file-0000.txt', 100), ('*.txt', 200100)):
			runner = Runner(replace(self.options, pattern=pattern))
			tracemalloc.start()
			started = monotonic()
			try:
				result = runner.run()
				elapsed = monotonic() - started
				retained, peak = tracemalloc.get_traced_memory()
			finally:
				tracemalloc.stop()
			self.assertTrue(result.complete, result.reason)
			self.assertEqual(expected, result.total)
			self.assertEqual(min(expected, 10000), len(result.rows))
			self.assertEqual(expected > 10000, result.table_limited)
			self.assertIsNone(runner.child)
			self.assertLess(peak, 64 * 1024 * 1024)
			rows = tuple(TableRow(str(index), (hit.relative_path, str(hit.size), hit.modified), hit.path) for index, hit in enumerate(result.rows))
			self.assertEqual(rows, TableSchema(3, ('Path', 'Size', 'Modified')).snapshot(lambda: rows))
			reports.append({'pattern': pattern, 'matches': result.total, 'retained': len(rows),
				'seconds_with_tracemalloc': round(elapsed, 3), 'python_peak_bytes': peak,
				'python_retained_bytes': retained, 'cache': 'warm after fixture creation'})
		seen, resume, completed = Event(), Event(), Event()
		runner = Runner(self.options)
		accept = runner.collector.accept
		stopped_results = []
		def first_match(raw):
			accept(raw)
			seen.set()
			if not resume.wait(5):
				raise RuntimeError('Cancellation test timed out')
		def finished(result):
			stopped_results.append(result)
			completed.set()
		with patch.object(runner.collector, 'accept', side_effect=first_match):
			self.assertTrue(runner.start(finished))
			try:
				self.assertTrue(seen.wait(5))
				process = runner.child.process
				started = monotonic()
				runner.stop()
				resume.set()
				self.assertTrue(completed.wait(1))
				elapsed = monotonic() - started
				self.assertLess(elapsed, 1)
				self.assertIsNotNone(process.poll())
				self.assertEqual('Stopped', stopped_results[0].status)
				reports.append({'real_fd_stop_seconds': round(elapsed, 3)})
			finally:
				runner.stop()
				resume.set()
				self.assertTrue(completed.wait(5))
		print(json.dumps(reports), flush=True)