import errno
import importlib.util
import io
import os
from contextlib import redirect_stderr, redirect_stdout
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, Mock, call, patch


SCRIPT = Path(__file__).resolve().parents[3] / 'misc' / 'benchmark_directory_listing.py'
SPEC = importlib.util.spec_from_file_location('benchmark_directory_listing', SCRIPT)
if SPEC is None or SPEC.loader is None:
	raise ImportError(str(SCRIPT))
benchmark_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark_module)


class DirectoryListingBenchmarkTest(TestCase):
	def setUp(self):
		self._temporary = TemporaryDirectory()
		self.addCleanup(self._temporary.cleanup)
		self._directory = Path(self._temporary.name)

	def test_real_file_and_directory_metadata_agree_without_recursion(self):
		file_path = self._directory / 'caf\u00e9.txt'
		file_path.write_bytes(b'hello')
		folder = self._directory / 'folder'
		folder.mkdir()
		(folder / 'nested.txt').write_bytes(b'not enumerated')
		expected = {
			file_path.name: (False, 5, file_path.stat().st_mtime_ns),
			folder.name: (True, None, folder.stat().st_mtime_ns),
		}
		for method in self._methods():
			with self.subTest(method=method.__name__):
				self.assertEqual((expected, {}), method(self._directory))

	def test_empty_directory(self):
		for method in self._methods():
			with self.subTest(method=method.__name__):
				self.assertEqual(({}, {}), method(self._directory))

	def test_symlink_targets_and_broken_link(self):
		file_path = self._directory / 'file.txt'
		file_path.write_bytes(b'hello')
		folder = self._directory / 'folder'
		folder.mkdir()
		try:
			os.symlink(file_path, self._directory / 'file-link')
			os.symlink(folder, self._directory / 'folder-link', target_is_directory=True)
			os.symlink(self._directory / 'absent', self._directory / 'broken-link')
		except OSError as error:
			if error.errno in (errno.EPERM, errno.EACCES) or getattr(error, 'winerror', None) == 1314:
				self.skipTest('Creating symlinks is not permitted by this environment')
			raise
		baseline = benchmark_module.listdir_metadata(self._directory)
		self.assertEqual(baseline, benchmark_module.scandir_metadata(self._directory))
		rows, errors = baseline
		self.assertFalse(errors)
		self.assertEqual(rows['file.txt'], rows['file-link'])
		self.assertEqual(rows['folder'], rows['folder-link'])
		self.assertIn('broken-link', rows)
		self.assertFalse(rows['broken-link'][0])

	def test_listdir_falls_back_only_on_missing_target(self):
		info = SimpleNamespace(st_mode=0o100644, st_size=7, st_mtime_ns=123)
		with patch.object(benchmark_module.os, 'listdir', return_value=['link']), \
			patch.object(benchmark_module.os, 'stat', side_effect=[FileNotFoundError(), info]) as stat_call:
			self.assertEqual(({'link': (False, 7, 123)}, {}),
				benchmark_module.listdir_metadata(self._directory))
		path = os.path.join(self._directory, 'link')
		self.assertEqual([call(path), call(path, follow_symlinks=False)], stat_call.call_args_list)

	def test_scandir_fallback_and_context_cleanup(self):
		info = SimpleNamespace(st_mode=0o100644, st_size=7, st_mtime_ns=123)
		entry = SimpleNamespace(name='link', stat=Mock(side_effect=[FileNotFoundError(), info]))
		context = MagicMock()
		context.__enter__.return_value = iter([entry])
		with patch.object(benchmark_module.os, 'scandir', return_value=context):
			self.assertEqual(({'link': (False, 7, 123)}, {}),
				benchmark_module.scandir_metadata(self._directory))
		self.assertEqual([call(), call(follow_symlinks=False)], entry.stat.call_args_list)
		context.__exit__.assert_called_once()

	def test_permission_errors_are_reported_by_both_methods(self):
		error = PermissionError(errno.EACCES, 'denied')
		expected = ({}, {'blocked': (errno.EACCES, None)})
		with patch.object(benchmark_module.os, 'listdir', return_value=['blocked']), \
			patch.object(benchmark_module.os, 'stat', side_effect=error) as stat_call:
			self.assertEqual(expected, benchmark_module.listdir_metadata(self._directory))
		stat_call.assert_called_once()
		entry = SimpleNamespace(name='blocked', stat=Mock(side_effect=error))
		context = MagicMock()
		context.__enter__.return_value = iter([entry])
		with patch.object(benchmark_module.os, 'scandir', return_value=context):
			self.assertEqual(expected, benchmark_module.scandir_metadata(self._directory))
		entry.stat.assert_called_once()
		context.__exit__.assert_called_once()

	def test_alternating_order_and_warmup_exclusion(self):
		for first in ('listdir', 'scandir'):
			with self.subTest(first=first):
				order = []
				def listdir(directory):
					order.append('listdir')
					return {}, {}
				def scandir(directory):
					order.append('scandir')
					return {}, {}
				output = io.StringIO()
				with patch.object(benchmark_module, 'listdir_metadata', side_effect=listdir), \
					patch.object(benchmark_module, 'scandir_metadata', side_effect=scandir), \
					patch.object(benchmark_module.time, 'perf_counter_ns', side_effect=count(step=1_000_000)), \
					patch.object(benchmark_module.statistics, 'median', wraps=benchmark_module.statistics.median) as median, \
					redirect_stdout(output):
					self.assertTrue(benchmark_module.benchmark(self._directory, 2, 1, first))
				other = 'scandir' if first == 'listdir' else 'listdir'
				self.assertEqual([first, other, other, first, first, other], order)
				self.assertEqual([call([1.0, 1.0]), call([1.0, 1.0])], median.call_args_list)
				self.assertIn('Metadata agreement: PASS', output.getvalue())

	def test_differing_metadata_withholds_speedup(self):
		with patch.object(benchmark_module, 'listdir_metadata', return_value=({'file': (False, 1, 1)}, {})), \
			patch.object(benchmark_module, 'scandir_metadata', return_value=({'file': (False, 2, 1)}, {})), \
			redirect_stdout(io.StringIO()) as output:
			self.assertFalse(benchmark_module.benchmark(self._directory, 1, 0, 'listdir'))
		self.assertIn('INVALID comparison', output.getvalue())
		self.assertNotIn('time ratio:', output.getvalue())

	def test_errors_withhold_speedup_even_when_both_methods_agree(self):
		result = ({}, {'blocked': (errno.EACCES, None)})
		with patch.object(benchmark_module, 'listdir_metadata', return_value=result), \
			patch.object(benchmark_module, 'scandir_metadata', return_value=result), \
			redirect_stdout(io.StringIO()) as output:
			self.assertFalse(benchmark_module.benchmark(self._directory, 1, 0, 'listdir'))
		self.assertIn('metadata errors', output.getvalue())
		self.assertNotIn('time ratio:', output.getvalue())

	def test_missing_folder_returns_failure(self):
		with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
			result = benchmark_module.main([str(self._directory / 'missing'), '--repeat', '1'])
		self.assertEqual(1, result)
		self.assertIn('Cannot benchmark', errors.getvalue())

	def test_invalid_run_counts(self):
		for arguments in (['--repeat', '0'], ['--repeat', '-1'], ['--warmup', '-1']):
			with self.subTest(arguments=arguments), redirect_stderr(io.StringIO()):
				with self.assertRaises(SystemExit) as raised:
					benchmark_module.main(arguments)
				self.assertEqual(2, raised.exception.code)

	def _methods(self):
		return benchmark_module.listdir_metadata, benchmark_module.scandir_metadata