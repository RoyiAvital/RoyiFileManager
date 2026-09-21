import base64
import importlib.util
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[3] / 'performancetest/python/fman_performancetest/search_fixture.py'
SPEC = importlib.util.spec_from_file_location('search_fixture', SCRIPT)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)

RECORD_SPEC = importlib.util.spec_from_file_location('performance_records', SCRIPT.with_name('records.py'))
records = importlib.util.module_from_spec(RECORD_SPEC)
RECORD_SPEC.loader.exec_module(records)

sys.path.insert(0, str(SCRIPT.parents[1]))
try:
	from fman_performancetest import fixtures as synthetic, suite
	from fman_performancetest.navigation import valid_move
	REPORT_SPEC = importlib.util.spec_from_file_location('performance_report', SCRIPT.parents[3] / 'misc/performance_report.py')
	report = importlib.util.module_from_spec(REPORT_SPEC)
	REPORT_SPEC.loader.exec_module(report)
finally:
	sys.path.pop(0)


class PerformanceReportTest(TestCase):
	def test_report_labels_recursive_fuzzy_find(self):
		html = report.render_html(self.record(), {})
		self.assertIn("'recursive.tree':'Fuzzy Find (Recursive)'", html)
		self.assertNotIn('Recursive Find', html)

	def test_statistics_record_preserves_every_report_metric_without_samples(self):
		current = self.refresh_record()
		before = deepcopy(current)
		compact = records.statistics_record(current)
		self.assertEqual(2, compact['schema_version'])
		self.assertEqual(before, current)
		self.assertEqual(compact, records.statistics_record(compact))
		self.assertEqual(report.overview(current), report.overview(compact))
		for raw, result in zip(current['results'], compact['results']):
			self.assertNotIn('samples', result)
			self.assertEqual(len(raw['samples']), result['completed_repetitions'])
			self.assertEqual(records.summarize(raw), result['summary'])

	def refresh_record(self):
		current = self.navigation_record()
		for identity in report.REFRESH_TESTS:
			result = deepcopy(self.record()['results'][0])
			result['test_id'] = identity
			result['samples'] = [dict(ui=dict(samples=[dict(action_id='refresh.' + pattern,
				paint_ms=10 if identity == 'refresh.small' else 100, qt_commit_ms=3,
				working_set_before_mib=50, working_set_mib=60,
				peak_working_set_before_mib=65, peak_working_set_mib=70)
				for pattern in report.REFRESH_SELECTIONS]))]
			current['results'].append(result)
			current['catalog']['tests'].append(dict(id=identity))
		return current

	def test_refresh_aggregate_keeps_case_timings_and_memory(self):
		current = self.refresh_record()
		value = next(test for test in report.overview(current) if test['test_id'] == 'refresh.selection')
		self.assertEqual(16, value['headline']['count'])
		self.assertEqual(55, value['headline']['median'])
		self.assertEqual(100, value['headline']['maximum'])
		self.assertEqual(70, value['metrics']['refresh.large.refresh.all.peak_working_set_mib']['median'])
		self.assertEqual(3, value['metrics']['refresh.large.refresh.all.qt_commit_ms']['median'])
		self.assertFalse(any(test['test_id'] in report.REFRESH_TESTS for test in report.overview(current)))
		current['results'][-1]['samples'][0]['ui']['samples'].pop()
		value = next(test for test in report.overview(current) if test['test_id'] == 'refresh.selection')
		self.assertEqual('incomplete', value['status'])
		self.assertIsNone(value['headline']['median'])

	def test_refresh_comparison_exposes_individual_regression(self):
		previous = self.refresh_record()
		current = deepcopy(previous)
		current['application']['version_id'] = 'Unreleased'
		current['results'][-1]['samples'][0]['ui']['samples'][-1]['paint_ms'] = 150
		data = report.report_data(current, {'1.0.0': previous})
		detail = next(row for row in data['previous'][0]['changes'] if row['test_id'] == 'refresh.selection'
			and row['metric'] == 'refresh.large.refresh.all.paint_ms')
		self.assertEqual(50, detail['change_percent'])

	def navigation_record(self):
		current = self.record()
		current['results'] = []
		for identity in report.NAVIGATION_TESTS:
			result = deepcopy(self.record()['results'][0])
			result['test_id'] = identity
			result['samples'] = [dict(ui=dict(navigation=[dict(action_id='navigation.' + action,
				input_to_paint_ms=10 if action != 'wheel-burst-down' else 20)
				for action in report.NAVIGATION_ACTIONS for iteration in range(5)]))]
			current['results'].append(result)
		current['catalog']['tests'] = [dict(id=identity) for identity in report.NAVIGATION_TESTS]
		return current

	def record(self, version='1.0.0', milliseconds=10):
		result = dict(test_id='pane.load.small', test_revision=1, fixture_id='small',
			fixture_sha256='fixture', definition_sha256='definition', status='passed',
			samples=[{'ui': {'first_paint_ms': milliseconds}}])
		return dict(schema_version=1, run_id=records.new_record({}, {}, {})['run_id'],
			status='passed', application=dict(version='1.0.0', version_id=version, commit='abc123', dirty=False),
			environment=dict(machine_id='local', configuration_sha256='environment'),
			harness=dict(source_sha256='harness'), results=[result],
			catalog=dict(tests=[dict(id='pane.load.small')]), parameters=dict(repetitions=1),
			started_at='2026-09-21T00:00:00+00:00', finished_at='2026-09-21T00:01:00+00:00')

	def save(self, directory, record):
		records.save_record(Path(directory) / 'runs', record)
		return report.update_history(directory, record)

	def test_first_version_has_no_fabricated_comparison(self):
		with TemporaryDirectory() as directory:
			current = self.record('Unreleased')
			versions = self.save(directory, current)
			self.assertEqual([], report.report_data(current, versions)['previous'])
			self.assertEqual(versions, report.read_history(directory))
			self.assertEqual('Unreleased', report.report_data(current, versions)['version'])

	def test_saved_run_comparison_uses_json_semantics_for_dependency_tuples(self):
		with TemporaryDirectory() as directory:
			current = self.record('Unreleased')
			current['environment']['configuration'] = dict(dependencies=[('PyYAML', '6.0.3')])
			versions = self.save(directory, current)
			self.assertEqual(versions, report.read_history(directory))
			self.assertEqual([['PyYAML', '6.0.3']],
				versions['Unreleased']['environment']['configuration']['dependencies'])
			current['environment']['configuration']['dependencies'] = [('PyYAML', '0.0.0')]
			with self.assertRaisesRegex(ValueError, 'does not match'):
				report.update_history(directory, current)

	def test_rerun_replaces_version_pointer_and_preserves_statistics_runs(self):
		with TemporaryDirectory() as directory:
			first, second = self.record(), self.record(milliseconds=8)
			self.save(directory, first)
			versions = self.save(directory, second)
			self.assertEqual({'1.0.0': records.statistics_record(second)}, versions)
			self.assertEqual(2, len(list((Path(directory) / 'runs').glob('*.json'))))

	def test_failed_or_partial_run_cannot_replace_previous_version(self):
		with TemporaryDirectory() as directory:
			previous = self.record()
			self.save(directory, previous)
			for status in ('failed', 'passed'):
				current = self.record()
				current['status'] = status
				current['results'] = []
				self.assertEqual({'1.0.0': records.statistics_record(previous)}, self.save(directory, current))
				self.assertEqual(1, report.report_data(current, {'1.0.0': previous})['saved_versions'])

	def test_comparison_reports_improvements_regressions_and_mismatches(self):
		baseline = self.record()
		for milliseconds, change in ((8, -20), (12, 20)):
			current = self.record('1.1.0', milliseconds)
			data = report.report_data(current, {'1.0.0': baseline})
			self.assertTrue(data['previous'][0]['compatible'])
			self.assertAlmostEqual(change, data['previous'][0]['changes'][0]['change_percent'])
		current['environment']['configuration_sha256'] = 'different'
		comparison = report.report_data(current, {'1.0.0': baseline})['previous'][0]
		self.assertFalse(comparison['compatible'])
		self.assertIn('Environment mismatch', comparison['reason'])

	def test_statistics_and_legacy_history_produce_identical_report_and_comparison(self):
		baseline = self.refresh_record()
		current = deepcopy(baseline)
		current['run_id'] = self.record()['run_id']
		current['application']['version_id'] = 'Unreleased'
		current['results'][-1]['samples'][0]['ui']['samples'][-1]['paint_ms'] = 150
		compact = records.statistics_record(current)
		self.assertTrue(report.complete(compact))
		self.assertEqual(report.report_data(current, {'1.0.0': baseline}),
			report.report_data(compact, {'1.0.0': records.statistics_record(baseline)}))
		self.assertEqual(records.compare(baseline, current), records.compare(baseline, compact))
		with TemporaryDirectory() as directory:
			path = Path(directory) / 'runs' / (baseline['run_id'] + '.json')
			path.parent.mkdir()
			path.write_text(json.dumps(baseline), encoding='utf-8')
			report.update_history(directory, baseline)
			versions = self.save(directory, compact)
			self.assertEqual({'1.0.0', 'Unreleased'}, set(versions))
			self.assertEqual(1, report.read_history(directory)['1.0.0']['schema_version'])
			self.assertEqual(2, report.read_history(directory)['Unreleased']['schema_version'])
		compact['results'][0]['completed_repetitions'] = 0
		self.assertFalse(report.complete(compact))

	def test_statistics_saved_values_are_verified_before_publication(self):
		current = records.statistics_record(self.record())
		with TemporaryDirectory() as directory:
			records.save_record(Path(directory) / 'runs', current)
			current['results'][0]['summary']['first_paint_ms']['median'] = 123
			with self.assertRaisesRegex(ValueError, 'does not match'):
				report.update_history(directory, current)

	def test_unreleased_does_not_replace_numeric_version(self):
		with TemporaryDirectory() as directory:
			self.save(directory, self.record())
			versions = self.save(directory, self.record('Unreleased'))
			self.assertEqual({'1.0.0', 'Unreleased'}, set(versions))
		for identity in ('v1.0.0', '1.0', '../1.0.0', '1.0.0-dirty', '01.0.0'):
			with self.subTest(identity=identity), self.assertRaises(ValueError):
				report.version_id(self.record(identity))

	def test_corrupt_history_is_not_silently_replaced(self):
		with TemporaryDirectory() as directory:
			index = Path(directory) / 'versions.json'
			index.write_text('{broken', encoding='utf-8')
			with self.assertRaises(ValueError):
				self.save(directory, self.record())
			self.assertEqual('{broken', index.read_text(encoding='utf-8'))

	def test_measure_runs_full_suite_saves_report_and_opens_browser(self):
		for use_parent_alias in (False, True):
			with self.subTest(use_parent_alias=use_parent_alias), TemporaryDirectory() as directory:
				history = Path(directory)
				if use_parent_alias:
					(history / 'alias').mkdir()
					history = history / 'alias' / '..'
				current = self.record('Unreleased')
				def run_suite(arguments, *, record_saved):
					self.assertEqual(['--results', str(history / 'runs')], arguments)
					path = records.save_record(history / 'runs', current)
					record_saved(current, path)
					return 0
				with patch.object(report, 'HISTORY', history), \
					patch.object(suite, 'main', side_effect=run_suite) as run, \
					patch.object(report, 'render_html', return_value='<html>report</html>'), \
					patch.object(report.webbrowser, 'open', return_value=True) as browser, \
					redirect_stdout(io.StringIO()):
					self.assertEqual(0, report.main())
					run.assert_called_once()
					browser.assert_called_once_with((history / 'index.html').resolve().as_uri())
				self.assertEqual('<html>report</html>', (history / 'index.html').read_text())
				self.assertEqual({'Unreleased'}, set(report.read_history(history)))

	def test_failed_suite_opens_failure_report_without_promoting_result(self):
		with TemporaryDirectory() as directory:
			current = self.record('Unreleased')
			current.update(status='failed', error='Expected failure')
			def run_suite(arguments, *, record_saved):
				path = records.save_record(Path(directory) / 'runs', current)
				record_saved(current, path)
				return 1
			with patch.object(report, 'HISTORY', Path(directory)), \
				patch.object(suite, 'main', side_effect=run_suite), \
				patch.object(report, 'render_html', return_value='<html>failed</html>'), \
				patch.object(report.webbrowser, 'open', return_value=True) as browser, \
				redirect_stdout(io.StringIO()):
				self.assertEqual(1, report.main())
				browser.assert_called_once()
			self.assertFalse((Path(directory) / 'versions.json').exists())

	def test_release_identification_requires_matching_tag_and_clean_tree(self):
		version = json.loads(suite.ROOT.joinpath('src/build/settings/base.json').read_text())['version']
		for dirty, tag, expected in ((b'', 'v' + version, version), (b'', version, version),
			(b'M file', 'v' + version, 'Unreleased'), (b'', '', 'Unreleased')):
			with self.subTest(dirty=dirty, tag=tag), \
				patch.object(suite, 'git', side_effect=[b'abc123', dirty, tag.encode()]), \
				patch.object(suite, 'source_hash', return_value='source'):
				self.assertEqual(expected, suite.provenance()['version_id'])

	def test_navigation_aggregates_fixed_cases_with_equal_weight(self):
		current = self.navigation_record()
		metric = report.overview(current)[-1]
		self.assertEqual('navigation', metric['test_id'])
		self.assertEqual(28, metric['headline']['count'])
		self.assertAlmostEqual(80 / 7, metric['headline']['median'])
		self.assertEqual(28, len(metric['metrics']))
		current['results'].pop()
		self.assertIsNone(report.overview(current)[-1]['headline']['median'])

	def test_navigation_comparison_exposes_individual_regression(self):
		previous = self.navigation_record()
		current = deepcopy(previous)
		current['application']['version_id'] = 'Unreleased'
		for observation in current['results'][0]['samples'][0]['ui']['navigation']:
			if observation['action_id'] == 'navigation.home':
				observation['input_to_paint_ms'] = 30
		data = report.report_data(current, {'1.0.0': previous})
		details = [row for row in data['previous'][0]['changes'] if row['test_id'] == 'navigation']
		self.assertEqual(28, len(details))
		self.assertEqual(200, next(row for row in details if row['metric'] ==
			'pane.load.small.navigation.home.input_to_paint_ms')['change_percent'])
		self.assertGreater(data['tests'][-1]['headline']['median'],
			data['previous'][0]['headlines']['navigation']['median'])

	def test_headlines_keep_queries_separate_and_exclude_open_time(self):
		result = dict(test_id='fuzzy.large', samples=[dict(ui=dict(open=dict(paint_ms=500),
			samples=[dict(query_id='fast', paint_ms=10), dict(query_id='slow', paint_ms=20)]))])
		value = report.headline(result['test_id'], records.summarize(result))
		self.assertEqual('slow.paint_ms', value['metric'])
		self.assertEqual(20, value['median'])

	def test_html_uses_tracked_icon_without_generated_png(self):
		icon_path = Path('src/main/icons/Icon.svg')
		icon = (report.ROOT / icon_path).read_bytes()
		with TemporaryDirectory() as directory:
			root = Path(directory)
			(root / icon_path).parent.mkdir(parents=True)
			(root / icon_path).write_bytes(icon)
			with patch.object(report, 'ROOT', root):
				html = report.render_html(self.record(), {})
		self.assertEqual(2, html.count('data:image/svg+xml;base64,' + base64.b64encode(icon).decode('ascii')))

	def test_html_is_offline_and_escapes_embedded_record_text(self):
		current = self.record('Unreleased')
		current['application']['commit'] = '</script><script>alert(1)</script>'
		html = report.render_html(current, {})
		self.assertIn('Previous versions', html)
		self.assertIn('data:image/svg+xml;base64,', html)
		self.assertNotIn('__PERFORMANCE_', html)
		self.assertNotIn(current['application']['commit'], html)
		payload = html.split('<script id="performance-data" type="application/json">')[1].split('</script>')[0]
		self.assertEqual(current['application']['commit'], json.loads(payload)['application']['commit'])
		self.assertNotIn('src="https:', html)
		self.assertNotIn('href="https:', html)


class BuildMeasureCommandTest(TestCase):
	def setUp(self):
		import build
		self.build = build

	def test_measure_defaults_to_suite_without_running_verification(self):
		verification = Mock()
		with patch.object(self.build, '_require_windows'), \
			patch.object(self.build.subprocess, 'run', return_value=Mock(returncode=0)) as run, \
			patch.dict(self.build.COMMANDS, test=verification):
			self.assertEqual(0, self.build.main(['measure']))
		verification.assert_not_called()
		run.assert_called_once_with([
			sys.executable, str(self.build.ROOT / 'src/performancetest/run.py'), 'measure'
		], cwd=self.build.ROOT)

	def test_measure_rejects_workload_and_profile_options(self):
		for arguments in (['--test', 'quickview.*'], ['--repeat', '1'], ['--profile']):
			with self.subTest(arguments=arguments), \
				patch.object(self.build.subprocess, 'run') as run, \
				redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
				self.build.main(['measure', *arguments])
			self.assertEqual(2, raised.exception.code)
			run.assert_not_called()

	def test_measure_preserves_failure_exit_code(self):
		with patch.object(self.build, '_require_windows'), \
			patch.object(self.build.subprocess, 'run', return_value=Mock(returncode=7)):
			self.assertEqual(7, self.build.main(['measure']))

	def test_other_commands_keep_zero_argument_dispatch(self):
		verification = Mock(return_value=None)
		with patch.dict(self.build.COMMANDS, test=verification):
			self.assertIsNone(self.build.main(['test']))
		verification.assert_called_once_with()

	def test_other_commands_reject_measurement_options(self):
		verification = Mock()
		with patch.dict(self.build.COMMANDS, test=verification), \
			redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
			self.build.main(['test', '--profile'])
		self.assertEqual(2, raised.exception.code)
		verification.assert_not_called()


class SyntheticFixtureTest(TestCase):
	def test_reproducible_contents_metadata_and_tamper_detection(self):
		images = {name: ('test-' + name).encode('ascii') for name in synthetic.ASSETS}
		specification = dict(revision=1, kind='flat', files=8, seed=1729)
		with TemporaryDirectory() as temporary:
			first = synthetic.prepare(temporary, 'first', specification, images)
			second = synthetic.prepare(temporary, 'second', specification, images)
			self.assertEqual(first['sha256'], second['sha256'])
			self.assertEqual(first, synthetic.prepare(temporary, 'first', specification, images))
			path = Path(first['directory']) / synthetic.ASSETS[0]
			path.write_bytes(b'changed')
			with self.assertRaises(ValueError):
				synthetic.prepare(temporary, 'first', specification, images)

	def test_png_is_deterministic_and_decodable(self):
		from PyQt5.QtGui import QImage
		data = synthetic.png(64, 48)
		self.assertEqual(data, synthetic.png(64, 48))
		image = QImage.fromData(data, 'PNG')
		self.assertEqual((64, 48), (image.width(), image.height()))
		self.assertEqual((30, 160, 60, 255), image.pixelColor(0, 0).getRgb())


class PerformanceRecordTest(TestCase):
	def test_statistics_only_save_keeps_all_repetitions_and_partial_failure(self):
		for fail_after in (None, 2):
			with self.subTest(fail_after=fail_after), TemporaryDirectory() as temporary:
				calls, published = [], []
				def invoke(test, directory, catalog_path, algorithm=False):
					iteration = len(calls) // 2 + 1
					calls.append(algorithm)
					if fail_after is not None and iteration > fail_after:
						raise RuntimeError('Expected later child failure')
					if algorithm:
						return dict(truncated=False, queries=[dict(query_id='substring-report', returned=1,
							samples=[dict(wall_ms=iteration * 5, cpu_ms=1)])])
					return dict(errors=[], settings_isolated=True, samples=[dict(
						query_id='substring-report', rows=1, paint_ms=iteration * 10,
						heartbeat_samples_ms=[1, 2, 3])])
				with patch.object(suite, 'provenance', return_value={'commit': 'test', 'version': 'test'}), \
					patch.object(suite, 'environment', return_value={}), \
					patch.object(suite, 'source_hash', return_value='test'), \
					patch.object(suite.fixtures, 'assets', return_value={}), \
					patch.object(suite.fixtures, 'prepare', return_value=dict(id='fixture', sha256='hash', directory=temporary)), \
					patch.object(suite, 'invoke', side_effect=invoke), \
					redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
					self.assertEqual(int(fail_after is not None), suite.main(
						['--test', 'filter.small', '--results', temporary],
						record_saved=lambda record, path: published.append((record, path))))
				current, path = published[0]
				self.assertEqual(current, json.loads(path.read_text(encoding='utf-8')))
				self.assertEqual(2, current['schema_version'])
				self.assertEqual(3, current['parameters']['repetitions'])
				self.assertEqual(5, current['parameters']['navigation_repetitions'])
				self.assertEqual([False, True] * 3 if fail_after is None else [False, True] * 2 + [False], calls)
				result = current['results'][0]
				self.assertNotIn('samples', result)
				self.assertEqual(3 if fail_after is None else 2, result['completed_repetitions'])
				self.assertEqual(dict(count=3, median=20, minimum=10, maximum=30, p95=None)
					if fail_after is None else dict(count=2, median=15, minimum=10, maximum=20, p95=None),
					result['summary']['substring-report.paint_ms'])
				self.assertEqual('passed' if fail_after is None else 'failed', result['status'])
				if fail_after is not None:
					self.assertIn('Expected later child failure', current['error'])

	def test_statistics_keep_p95_and_do_not_trust_cached_summary(self):
		result = dict(samples=[dict(ui=dict(first_paint_ms=number)) for number in range(1, 21)],
			summary={'stale': dict(median=-1)})
		compact = records.statistics_record(dict(schema_version=1, results=[result]))['results'][0]
		self.assertEqual(20, compact['completed_repetitions'])
		self.assertEqual({'first_paint_ms': dict(count=20, median=10.5, minimum=1, maximum=20, p95=20)},
			compact['summary'])

	def test_refresh_dispatch_uses_catalog_cases_without_navigation(self):
		from fman_performancetest import pane_rendering_benchmark
		catalog = records.load_catalog()
		self.assertEqual(list(pane_rendering_benchmark.REFRESH_SELECTIONS), catalog['protocol']['refresh_selections'])
		for test in catalog['tests']:
			if test['workload'] != 'refresh':
				continue
			with patch.object(pane_rendering_benchmark, 'child', return_value=0) as child:
				self.assertEqual(0, suite.child(test, catalog, Path('fixture'), False, None))
				child.assert_called_once_with(Path('fixture'), test['id'], 'snapshot', True,
					viewport=catalog['protocol']['viewport'], navigation_repetitions=0,
					refresh_patterns=catalog['protocol']['refresh_selections'])

	def test_failed_child_is_recorded_without_running_other_workloads(self):
		with TemporaryDirectory() as temporary, \
			patch.object(suite, 'provenance', return_value={'commit': 'test', 'version': 'test'}), \
			patch.object(suite, 'environment', return_value={}), \
			patch.object(suite, 'source_hash', return_value='test'), \
			patch.object(suite.fixtures, 'assets', return_value={}), \
			patch.object(suite.fixtures, 'prepare', return_value=dict(id='fixture', sha256='hash', directory=temporary)), \
			patch.object(suite, 'invoke', side_effect=RuntimeError('Expected child failure')) as invoke, \
			redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
			self.assertEqual(1, suite.main(['--test', 'filter.small', '--repeat', '1', '--results', temporary]))
			invoke.assert_called_once()
			paths = list(Path(temporary).glob('*.json'))
			self.assertEqual(1, len(paths))
			record = json.loads(paths[0].read_text(encoding='utf-8'))
			self.assertEqual('failed', record['status'])
			self.assertEqual('failed', record['results'][0]['status'])
			self.assertIn('Expected child failure', record['error'])

	def test_performance_path_is_not_added_to_verification_environment(self):
		import build
		self.assertNotIn('performancetest', build._environment()['PYTHONPATH'])

	def test_navigation_must_move_and_reach_correct_boundary_or_direction(self):
		for key, destination in (('home', 0), ('end', 255), ('page-up', 100), ('page-down', 156)):
			self.assertTrue(valid_move(key, 128, destination, 256))
			self.assertFalse(valid_move(key, 128, 128, 256))
			self.assertFalse(valid_move(key, 128, -1, 256))
		self.assertFalse(valid_move('page-down', 128, 129, 256))
		self.assertFalse(valid_move('page-up', 128, 127, 256))

	def test_comparison_requires_matching_environment_fixture_and_definition(self):
		result = dict(test_id='pane.load.small', test_revision=1, fixture_sha256='fixture',
			definition_sha256='definition', status='passed', samples=[{'ui': {'first_paint_ms': 10}}])
		baseline = dict(schema_version=1, status='passed', environment=dict(machine_id='local',
			configuration_sha256='environment'), harness=dict(source_sha256='harness'), results=[result])
		current = deepcopy(baseline)
		current['results'][0]['samples'][0]['ui']['first_paint_ms'] = 5
		self.assertEqual(-50, records.compare(baseline, current)[0]['change_percent'])
		self.assertIsNone(records.summarize(result)['first_paint_ms']['p95'])
		for section, field in (('environment', 'machine_id'), ('environment', 'configuration_sha256'), ('harness', 'source_sha256')):
			altered = deepcopy(current)
			altered[section][field] = 'changed'
			with self.assertRaises(ValueError):
				records.compare(baseline, altered)
		for field in ('test_revision', 'fixture_sha256', 'definition_sha256', 'status'):
			altered = deepcopy(current)
			altered['results'][0][field] = 'changed'
			with self.assertRaises(ValueError):
				records.compare(baseline, altered)

	def test_catalog_has_unique_ids_and_keeps_comments_untouched(self):
		before = records.CATALOG.read_bytes()
		catalog = records.load_catalog()
		self.assertEqual(11, len(catalog['tests']))
		self.assertEqual(before, records.CATALOG.read_bytes())
		self.assertEqual(records.digest(catalog), records.digest(json.loads(json.dumps(catalog))))

	def test_duplicate_keys_and_test_ids_are_rejected(self):
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / 'catalog.yaml'
			path.write_text('schema_version: 1\nschema_version: 1\n', encoding='utf-8')
			with self.assertRaises(ValueError):
				records.load_catalog(path)
			catalog = records.load_catalog()
			catalog['tests'].append(catalog['tests'][0])
			path.write_text(json.dumps(catalog), encoding='utf-8')
			with self.assertRaises(ValueError):
				records.load_catalog(path)

	def test_records_are_unique_and_never_overwrite(self):
		catalog = records.load_catalog()
		record = records.new_record(catalog, {'version': 'test'}, {})
		self.assertNotEqual(record['run_id'], records.new_record(catalog, {}, {})['run_id'])
		with TemporaryDirectory() as temporary:
			path = records.save_record(temporary, record)
			self.assertEqual(record, json.loads(path.read_text(encoding='utf-8')))
			with self.assertRaises(FileExistsError):
				records.save_record(temporary, record)


class SearchFixtureTest(TestCase):
	def test_seeded_names_are_unique_portable_and_challenging(self):
		names = list(fixture.names(32, 1729))
		self.assertEqual(names, list(fixture.names(32, 1729)))
		self.assertNotEqual(names, list(fixture.names(32, 1730)))
		self.assertEqual(32, len(set(names)))
		self.assertTrue(any(name.startswith('common_') for name in names))
		self.assertTrue(any('annual report' in name and name.endswith('.pdf') for name in names))
		self.assertTrue(all(len(name) < 150 and not set(name) & set('<>:"/\\|?*') for name in names))
		for token in ('a' * 72, 'ab' * 42, '[draft]', 'annual report', 'Stra\u00dfe'):
			self.assertTrue(any(token in name for name in names))

	def test_prepare_creates_exact_counts_and_reuses_only_matching_manifest(self):
		with TemporaryDirectory() as temporary:
			root = Path(temporary) / 'fixture'
			configuration = fixture.prepare(root, 8, 9)
			self.assertEqual(8, sum(path.is_file() for path in (root / 'flat').iterdir()))
			self.assertEqual(9, sum(path.is_file() for path in (root / 'recursive').rglob('*')))
			self.assertEqual(configuration, fixture.prepare(root, 8, 9))
			with self.assertRaises(ValueError):
				fixture.prepare(root, 9, 9)
			with self.assertRaises(ValueError):
				fixture.prepare(Path(temporary), 8, 9)

	def test_invalid_counts_do_not_create_files(self):
		with TemporaryDirectory() as temporary:
			root = Path(temporary) / 'fixture'
			with self.assertRaises(ValueError):
				fixture.prepare(root, 0, 9)
			self.assertFalse(root.exists())

	def test_reuse_rejects_missing_extra_and_changed_files(self):
		for change in ('missing', 'extra', 'changed'):
			with self.subTest(change=change), TemporaryDirectory() as temporary:
				root = Path(temporary) / 'fixture'
				fixture.prepare(root, 2, 2)
				path = next((root / 'flat').iterdir())
				if change == 'missing':
					path.unlink()
				else:
					if change == 'extra':
						path = root / 'flat/extra'
					path.write_bytes(b'changed')
				with self.assertRaises(ValueError):
					fixture.prepare(root, 2, 2)