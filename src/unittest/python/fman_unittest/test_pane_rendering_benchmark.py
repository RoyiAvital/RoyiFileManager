import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[3] / 'misc' / 'benchmark_pane_rendering.py'
SPEC = importlib.util.spec_from_file_location('benchmark_pane_rendering', SCRIPT)
if SPEC is None or SPEC.loader is None:
	raise ImportError(str(SCRIPT))
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class PaneRenderingBenchmarkTest(TestCase):
	def records(self, labels=('large',), baseline='before', repeat=3):
		return [dict(label=label, mode=mode, iteration=iteration, entries=12, rows=10,
			fingerprint=label, errors=[], settings_isolated=True, show_hidden=False,
			hidden_queries=0, first_paint_ms=iteration * 10, complete_ms=iteration * 20,
			loading_paints_ms={'count': 1, 'p95': iteration * 2})
			for label in labels for mode in (baseline, 'after') for iteration in range(1, repeat + 1)]

	def test_default_directories(self):
		with patch.dict(benchmark.os.environ, {'WINDIR': r'X:\Windows'}):
			self.assertEqual([Path(r'D:\TMP\CelebAAligned'), Path(r'X:\Windows') / 'System32',
				Path(r'X:\Windows') / 'WinSxS'], benchmark.default_directories())

	def test_summary_uses_medians_and_handles_no_loading_samples(self):
		rows = self.records()
		self.assertIn('| large | 12 | 20.0 -> 20.0 | 40.0 -> 40.0 | 4.0 -> 4.0 |',
			benchmark.summarize(rows, ['large'], 'before', 3, False))
		for row in rows:
			row['loading_paints_ms'] = {'count': 0}
		self.assertIn('n/a -> n/a', benchmark.summarize(rows, ['large'], 'before', 3, False))

	def test_invalid_or_incomplete_results_withhold_summary(self):
		for field, value in [('fingerprint', 'changed'), ('rows', 9), ('entries', 13),
			('errors', ['failure']), ('settings_isolated', False), ('show_hidden', True)]:
			with self.subTest(field=field):
				rows = self.records()
				rows[-1][field] = value
				with self.assertRaises(ValueError):
					benchmark.summarize(rows, ['large'], 'before', 3, False)
		for rows in (self.records()[:-1], self.records() + self.records()[:1]):
			with self.assertRaises(ValueError):
				benchmark.summarize(rows, ['large'], 'before', 3, False)

	def test_filter_off_rejects_hidden_queries(self):
		rows = self.records()
		for row in rows:
			row['show_hidden'] = True
		benchmark.summarize(rows, ['large'], 'before', 3, True)
		rows[0]['hidden_queries'] = 1
		with self.assertRaises(ValueError):
			benchmark.summarize(rows, ['large'], 'before', 3, True)

	def test_main_runs_three_defaults_with_repository_environment(self):
		with TemporaryDirectory() as temporary:
			root = Path(temporary)
			folders = [root / name for name in ('large', 'System32', 'WinSxS')]
			for folder in folders:
				folder.mkdir()
			output = root / 'results.json'
			rows = self.records([folder.name for folder in folders], 'reviewed', 1)
			for row in rows:
				row['show_hidden'] = True
			def run(command, **kwargs):
				self.assertEqual(benchmark.ROOT, kwargs['cwd'])
				self.assertEqual({'test': 'environment'}, kwargs['env'])
				self.assertEqual([benchmark.sys.executable, '-m', 'fman_integrationtest.pane_rendering_benchmark',
					*map(str, folders), '--baseline', 'reviewed', '--repeat', '1',
					'--output', str(output), '--show-hidden'], command)
				output.write_text(json.dumps(rows), encoding='utf-8')
				return SimpleNamespace(returncode=0)
			with patch.object(benchmark.sys, 'platform', 'win32'), \
				patch.object(benchmark, 'default_directories', return_value=folders), \
				patch.object(benchmark, 'benchmark_environment', return_value={'test': 'environment'}), \
				patch.object(benchmark.subprocess, 'run', side_effect=run), \
				redirect_stdout(io.StringIO()) as stdout:
				self.assertEqual(0, benchmark.main(['--baseline', 'reviewed', '--repeat', '1',
					'--show-hidden', '--output', str(output)]))
			self.assertIn('parity and settings isolation: PASS', stdout.getvalue())

	def test_main_preserves_child_failure(self):
		with TemporaryDirectory() as temporary, \
			patch.object(benchmark.sys, 'platform', 'win32'), \
			patch.object(benchmark, 'benchmark_environment', return_value={}), \
			patch.object(benchmark.subprocess, 'run', return_value=SimpleNamespace(
				returncode=7, stdout='', stderr='child failed')), \
			redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr:
			self.assertEqual(7, benchmark.main([temporary]))
			self.assertIn('child failed', stderr.getvalue())

	def test_invalid_inputs_never_launch_children(self):
		with TemporaryDirectory() as temporary, \
			patch.object(benchmark.sys, 'platform', 'win32'), \
			patch.object(benchmark.subprocess, 'run') as run, redirect_stderr(io.StringIO()):
			for arguments in ([str(Path(temporary) / 'missing')], [temporary, '--repeat', '0']):
				with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as raised:
					benchmark.main(arguments)
				self.assertEqual(2, raised.exception.code)
			run.assert_not_called()