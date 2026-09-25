import importlib.util
import io
import json
import os
import subprocess
import sys
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

PANE_SPEC = importlib.util.spec_from_file_location('pane_measurement',
	SCRIPT.parents[1] / 'performancetest/python/fman_performancetest/pane_rendering_benchmark.py')
pane_measurement = importlib.util.module_from_spec(PANE_SPEC)
PANE_SPEC.loader.exec_module(pane_measurement)


class PaneRenderingBenchmarkTest(TestCase):
	def test_navigation_paint_hook_after_initial_paint(self):
		script = '''
from unittest.mock import patch
from PyQt5.QtWidgets import QApplication, QTableView
from fman.impl import view as views
from fman_performancetest.quickview import _install_paint_dispatch

application = QApplication([])
class View(QTableView):
    pass
with patch.object(views, 'FileListView', View):
    _install_paint_dispatch()
view = View()
view.resize(320, 200)
view.show()
application.processEvents()
completed = []
original = View.paintEvent
def measured(widget, event):
    result = original(widget, event)
    completed.append(widget)
    return result
with patch.object(View, 'paintEvent', measured):
    view.viewport().repaint()
assert completed == [view], completed
view.close()
application.processEvents()
'''
		environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
		environment['PYTHONPATH'] = os.pathsep.join((str(SCRIPT.parents[1] /
			'performancetest/python'), environment.get('PYTHONPATH', '')))
		result = subprocess.run([sys.executable, '-c', script], env=environment,
			capture_output=True, text=True, timeout=30)
		self.assertEqual(0, result.returncode, result.stdout + result.stderr)

	def test_refresh_selection_patterns(self):
		for count in (8, 256, 200000):
			for pattern in pane_measurement.REFRESH_SELECTIONS:
				with self.subTest(count=count, pattern=pattern):
					cursor, ranges = pane_measurement.refresh_selection(pattern, count)
					self.assertTrue(0 <= cursor < count)
					selected = {row for first, last in ranges for row in range(first, last + 1)}
					self.assertEqual(len(selected), sum(last - first + 1 for first, last in ranges))
					self.assertTrue(all(0 <= first <= last < count for first, last in ranges))
					expected = {'none': 0, 'single-first': 1, 'single-middle': 1, 'single-last': 1,
						'middle-block': max(1, count // 10), 'scattered': min(100, count),
						'all-except-current': count - 1, 'all': count}[pattern]
					self.assertEqual(expected, len(selected))
					if pattern == 'all-except-current':
						self.assertNotIn(cursor, selected)
		for pattern, count in (('unknown', 256), ('none', 0)):
			with self.assertRaises(ValueError):
				pane_measurement.refresh_selection(pattern, count)

	def records(self, labels=('large',), baseline='before', repeat=3):
		return [dict(label=label, mode=mode, iteration=iteration, entries=12, rows=10,
			fingerprint=label, errors=[], settings_isolated=True, show_hidden=False,
			hidden_queries=0, first_paint_ms=iteration * 10, complete_ms=iteration * 20,
			loading_paints_ms={'count': 1, 'p95': iteration * 2})
			for label in labels for mode in (baseline, 'after') for iteration in range(1, repeat + 1)]

	def test_default_directories(self):
		self.assertEqual([benchmark.ROOT / 'target/performance/fixtures' / identity / 'data'
			for identity in ('flat-small-v1', 'flat-large-v1')], benchmark.default_directories())
		self.assertEqual('v0.8.0', benchmark.normalize_release_ref('0.8.0'))
		self.assertEqual('feature/ref', benchmark.normalize_release_ref('feature/ref'))
		self.assertEqual(Path('results-v0.8.0.json'),
			benchmark.comparison_output(Path('results.json'), 'v0.8.0'))

	def test_summary_uses_medians_and_handles_no_loading_samples(self):
		rows = self.records()
		self.assertIn('| large | 12 | 20.0 -> 20.0 | 40.0 -> 40.0 | 4.0 -> 4.0 |',
			benchmark.summarize(rows, ['large'], 'before', 3, False))
		for row in rows:
			row['loading_paints_ms'] = {'count': 0}
		self.assertIn('n/a -> n/a', benchmark.summarize(rows, ['large'], 'before', 3, False))

	def test_current_comparison_requires_snapshot_samples(self):
		rows = self.records(baseline='current')
		with self.assertRaises(ValueError):
			benchmark.summarize(rows, ['large'], 'current', 3, False)
		for row in rows:
			if row['mode'] == 'after':
				row['mode'] = 'snapshot'
		self.assertIn('| large | 12 |', benchmark.summarize(rows, ['large'], 'current', 3, False))

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
			root = Path(temporary) / 'nested'
			root.mkdir()
			root = root / '..'
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
				self.assertEqual([benchmark.sys.executable, '-m', 'fman_performancetest.pane_rendering_benchmark',
					*[str(folder.resolve()) for folder in folders], '--baseline', 'reviewed', '--repeat', '1',
					'--output', str(output.resolve()), '--show-hidden'], command)
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

	def test_main_adds_release_comparison(self):
		with TemporaryDirectory() as temporary:
			folder = Path(temporary)
			output = folder / 'results.json'
			rows = self.records([folder.name], 'current', 1)
			for row in rows:
				if row['mode'] == 'after':
					row['mode'] = 'snapshot'
			commands = []
			def run(command, **kwargs):
				commands.append(command)
				result_path = Path(command[command.index('--output') + 1])
				result_path.write_text(json.dumps(rows), encoding='utf-8')
				return SimpleNamespace(returncode=0)
			with patch.object(benchmark.sys, 'platform', 'win32'), \
				patch.object(benchmark, 'benchmark_environment', return_value={}), \
				patch.object(benchmark.subprocess, 'run', side_effect=run), \
				redirect_stdout(io.StringIO()):
				self.assertEqual(0, benchmark.main([temporary, '--repeat', '1',
					'--compare-version', '0.8.0', '--output', str(output)]))
		self.assertEqual(2, len(commands))
		self.assertNotIn('--baseline-ref', commands[0])
		self.assertEqual('v0.8.0', commands[1][commands[1].index('--baseline-ref') + 1])
		self.assertEqual(str(output.with_name('results-v0.8.0.json').resolve()),
			commands[1][commands[1].index('--output') + 1])

	def test_invalid_inputs_never_launch_children(self):
		with TemporaryDirectory() as temporary, \
			patch.object(benchmark.sys, 'platform', 'win32'), \
			patch.object(benchmark.subprocess, 'run') as run, redirect_stderr(io.StringIO()):
			for arguments in ([str(Path(temporary) / 'missing')], [temporary, '--repeat', '0']):
				with self.subTest(arguments=arguments), self.assertRaises(SystemExit) as raised:
					benchmark.main(arguments)
				self.assertEqual(2, raised.exception.code)
			run.assert_not_called()