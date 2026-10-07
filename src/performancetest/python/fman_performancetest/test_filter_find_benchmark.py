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


class HistoricalBenchmarkTest(TestCase):
	def test_version_order_and_text_availability(self):
		from fman_performancetest.historical import VERSIONS, has_text_preview, version_order
		self.assertEqual(8, len(VERSIONS))
		self.assertEqual(tuple(reversed(version_order(0))), version_order(1))
		self.assertFalse(has_text_preview('0.9.3'))
		self.assertTrue(has_text_preview('0.10.0'))
		self.assertTrue(has_text_preview('Unreleased'))

	def test_child_environment_excludes_current_application(self):
		import os
		from fman_performancetest.historical import child_environment
		with TemporaryDirectory() as temporary:
			source = Path(temporary).resolve()
			(source / 'src/main/resources/base/Plugins/Core').mkdir(parents=True)
			with patch.dict(os.environ, PYTHONPATH='unrelated-current-application'):
				environment = child_environment(source)
			paths = environment['PYTHONPATH'].split(os.pathsep)
			self.assertEqual(str(source / 'src/main/python'), paths[1])
			self.assertEqual(str(source / 'src/main/resources/base/Plugins/Core'), paths[2])
			self.assertNotIn('unrelated-current-application', paths)
			self.assertEqual('1', environment['PYTHONDONTWRITEBYTECODE'])

	def test_record_writes_are_exclusive(self):
		from fman_performancetest.historical import write_json
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / 'result.json'
			write_json(path, {'status': 'passed'})
			with self.assertRaises(FileExistsError):
				write_json(path, {'status': 'failed'})
			self.assertEqual({'status': 'passed'}, json.loads(path.read_text()))

	def test_digest_detects_source_changes(self):
		from fman_performancetest.historical import source_digest
		with TemporaryDirectory() as temporary:
			root = Path(temporary)
			path = root / 'application.py'
			path.write_text('before')
			before = source_digest(root)
			path.write_text('after')
			self.assertNotEqual(before, source_digest(root))

	def test_sample_rejects_missing_selection_cases(self):
		from fman_performancetest.historical import sample
		with patch('fman_performancetest.historical.invoke', return_value=dict(errors=[], settings_isolated=True, samples=[])):
			with self.assertRaisesRegex(ValueError, 'Selection correctness'):
				sample(None, '0.9.0', dict(workload='selection', selection_count=64), None, None)

	def test_sample_rejects_search_count_mismatch(self):
		from fman_performancetest.historical import sample
		ui = dict(errors=[], settings_isolated=True, samples=[dict(query_id='query', rows=2)])
		algorithm = dict(truncated=False, queries=[dict(query_id='query', returned=1)])
		with patch('fman_performancetest.historical.invoke', side_effect=[ui, algorithm]):
			with self.assertRaisesRegex(ValueError, 'result counts differ'):
				sample(None, '0.9.0', dict(workload='fuzzy'), None, None)


class PerformanceReportTest(TestCase):
	def selection_record(self, full=False):
		current = self.record()
		current['results'] = []
		current['catalog'] = records.load_catalog()
		optional = current['catalog'].pop('full_tests')
		if full:
			current['catalog']['tests'].extend(optional)
		current['suite_mode'] = 'full' if full else 'regular'
		for test in current['catalog']['tests']:
			result = deepcopy(self.record()['results'][0])
			result.update(test_id=test['id'], fixture_id=test['fixture'])
			if test['workload'] == 'quickview':
				result['samples'] = [dict(ui=dict(samples=[dict(action_id=case, input_to_paint_ms=timing)
					for case, timing in (('enable.png', 25), ('switch.text', 100),
						('switch.python', 200), ('switch.markdown', 300))]))]
			if test['workload'] == 'selection':
				count = current['catalog']['fixtures'][test['fixture']]['files']
				selected = test['selection_count']
				patterns = (('single', 1), ('all', count), ('contiguous', selected),
					('alternating', selected), ('scattered', selected))
				result['samples'] = [dict(ui=dict(samples=[dict(action_id='selection.' + pattern,
					wall_ms=10, paint_ms=index * 10, readback_ms=100, row_count=count,
					input_ready_ms=index * 10 + 5,
					selected_count=marked, heartbeat_gap_ms={'max': 12})
					for index, (pattern, marked) in enumerate(patterns, 1)]))]
			if test['workload'] == 'copy':
				result['samples'] = [dict(ui=dict(samples=[
					dict(action_id='copy.selection', paint_ms=2, input_ready_ms=3, readback_ms=1, selected_count=15000),
					dict(action_id='copy.transfer', wall_ms=100, first_file_ms=5, preparation_ms=4, throughput_mib_s=1)]))]
			current['results'].append(result)
		return current

	def test_selection_report_aggregates_five_cases_into_two_rows(self):
		current = self.selection_record()
		compact = records.statistics_record(current)
		self.assertEqual(report.overview(current), report.overview(compact))
		overview = report.overview(compact)
		self.assertEqual(16, len(overview))
		selections = [item for item in overview if item['test_id'].startswith('selection.')]
		self.assertEqual(['selection.small', 'selection.large'], [item['test_id'] for item in selections])
		for item, selected in zip(selections, (64, 1000)):
			self.assertEqual(35, item['headline']['median'])
			self.assertEqual(5, item['headline']['count'])
			self.assertEqual((15, 55), (item['headline']['minimum'], item['headline']['maximum']))
			self.assertEqual('passed', item['status'])
			self.assertEqual(selected, item['metrics']['selection.scattered.selected_count']['median'])
			for pattern in report.SELECTION_PATTERNS:
				self.assertEqual(100, item['metrics']['selection.' + pattern + '.readback_ms']['median'])
		html = report.render_html(compact, {})
		for label in ('Selections / Small', 'Selections / Large'):
			self.assertIn(label, html)
		self.assertNotIn('Selections - ', html)
		self.assertNotIn('selection.medium', [item['test_id'] for item in overview])
		self.assertIn("name.endsWith('_count') ? 'count'", html)
		self.assertIn("test.headline.count_label === 'case medians'", html)

	def test_full_report_adds_medium_selection_and_requires_every_workload(self):
		current = self.selection_record(full=True)
		data = report.report_data(current, {})
		self.assertEqual('full', data['suite_mode'])
		self.assertEqual(21, data['expected_tests'])
		self.assertEqual(24, len(data['tests']))
		self.assertTrue(data['complete'])
		medium = next(item for item in data['tests'] if item['test_id'] == 'selection.medium')
		self.assertEqual(35, medium['headline']['median'])
		self.assertEqual(5, medium['headline']['count'])
		self.assertEqual(50000, medium['metrics']['selection.all.selected_count']['median'])
		self.assertEqual(1000, medium['metrics']['selection.scattered.selected_count']['median'])
		self.assertIn('Selections / Medium', report.render_html(current, {}))
		current['results'].pop()
		self.assertFalse(report.complete(current))
		with TemporaryDirectory() as directory:
			self.assertEqual({}, self.save(directory, current))

	def test_readback_and_quickview_types_have_independent_headlines(self):
		current = self.selection_record()
		next(result for result in current['results'] if result['test_id'] == 'selection.large')['samples'][0]['ui']['samples'][1]['readback_ms'] = 700
		self.assertEqual(report.overview(current), report.overview(records.statistics_record(current)))
		rows = {item['test_id']: item for item in report.overview(current)}
		self.assertEqual(700, rows['readback']['headline']['median'])
		self.assertEqual(10, rows['readback']['headline']['count'])
		self.assertEqual(35, rows['selection.large']['headline']['median'])
		self.assertEqual(25, rows['quickview.large']['headline']['median'])
		self.assertEqual(200, rows['quickview.text.large']['headline']['median'])
		self.assertEqual(3, rows['quickview.text.large']['headline']['count'])
		self.assertNotIn('switch.text.input_to_paint_ms', rows['quickview.large']['metrics'])
		self.assertNotIn('enable.png.input_to_paint_ms', rows['quickview.text.large']['metrics'])

	def test_copy_report_keeps_selection_startup_and_completion_separate(self):
		current = self.selection_record(full=True)
		row = next(item for item in report.overview(current) if item['test_id'] == 'copy.flat')
		self.assertEqual(100, row['headline']['median'])
		self.assertEqual(2, row['metrics']['copy.selection.paint_ms']['median'])
		self.assertEqual(5, row['metrics']['copy.transfer.first_file_ms']['median'])
		html = report.render_html(current, {})
		self.assertIn('Copy / Flat (10,000 Files)', html)
		self.assertIn('Copy / Tree (1,000 Files)', html)
		self.assertIn("name.endsWith('_mib_s') ? 'MiB/s'", html)

	def test_related_report_rows_are_consecutive(self):
		for full in (False, True):
			with self.subTest(full=full):
				rows = [item['test_id'] for item in report.overview(self.selection_record(full=full))]
				sizes = ('small', 'large', 'medium') if full else ('small', 'large')
				quickview = ['quickview.' + size for size in sizes] + ['quickview.text.' + size for size in sizes]
				selections = ['selection.' + size for size in sizes] + ['readback']
				for group in (quickview, selections):
					first = rows.index(group[0])
					self.assertEqual(group, rows[first:first + len(group)])

	def test_readback_and_text_rows_do_not_fabricate_missing_results(self):
		for failure in ('missing-case', 'failed-workload', 'missing-workload'):
			with self.subTest(failure=failure):
				current = self.selection_record()
				for result in list(current['results']):
					if result['test_id'] in ('selection.large', 'quickview.large'):
						if failure == 'missing-case':
							result['samples'][0]['ui']['samples'].pop()
						elif failure == 'failed-workload':
							result['status'] = 'failed'
						else:
							current['results'].remove(result)
				rows = {item['test_id']: item for item in report.overview(current)}
				self.assertIsNone(rows['readback']['headline']['median'])
				if failure == 'missing-workload':
					self.assertNotIn('quickview.text.large', rows)
				else:
					self.assertIsNone(rows['quickview.text.large']['headline']['median'])
		self.assertNotIn('readback', [item['test_id'] for item in report.overview(self.record())])

	def test_derived_readback_and_text_comparisons_preserve_case_changes(self):
		previous = self.selection_record()
		current = deepcopy(previous)
		current['application']['version_id'] = 'Unreleased'
		for result in current['results']:
			if result['test_id'] == 'selection.large':
				result['samples'][0]['ui']['samples'][1]['readback_ms'] = 50
			elif result['test_id'] == 'quickview.large':
				result['samples'][0]['ui']['samples'][-1]['input_to_paint_ms'] = 150
		data = report.report_data(current, {'1.0.0': previous})
		self.assertTrue(data['previous'][0]['compatible'])
		for identity, metric in (('readback', 'selection.large.selection.all.readback_ms'),
			('quickview.text.large', 'switch.markdown.input_to_paint_ms')):
			change = next(item for item in data['previous'][0]['changes']
				if item['test_id'] == identity and item['metric'] == metric)
			self.assertEqual(-50, change['change_percent'])

	def test_selection_report_suppresses_missing_or_failed_cases(self):
		for missing in (False, True):
			with self.subTest(missing=missing):
				current = self.selection_record()
				result = next(item for item in current['results'] if item['test_id'] == 'selection.large')
				if missing:
					result['samples'][0]['ui']['samples'].pop()
				else:
					current['status'] = result['status'] = 'failed'
					result['failures'] = [dict(action_id='selection.scattered', status='timeout',
						iteration=1, stage='painted', error='Timed out')]
				compact = records.statistics_record(current)
				self.assertEqual(report.overview(current), report.overview(compact))
				item = next(item for item in report.overview(compact) if item['test_id'] == 'selection.large')
				self.assertIsNone(item['headline']['median'])
				if not missing:
					self.assertEqual('failed', item['status'])
					self.assertEqual(result['failures'], item['failures'])
					self.assertIn('case-failures', report.render_html(compact, {}))

	def test_selection_headline_does_not_substitute_legacy_paint_only_timings(self):
		current = self.selection_record()
		for result in current['results']:
			if result['test_id'].startswith('selection.'):
				for sample in result['samples'][0]['ui']['samples']:
					del sample['input_ready_ms']
		for item in report.overview(current):
			if item['test_id'].startswith('selection.'):
				self.assertIsNone(item['headline']['median'])
				self.assertIn('selection.all.paint_ms', item['metrics'])
				self.assertIn('selection.all.readback_ms', item['metrics'])
		for result in current['results']:
			if result['test_id'].startswith('selection.'):
				for sample in result['samples'][0]['ui']['samples']:
					sample['responsive_ms'] = sample['paint_ms'] + sample['readback_ms']
		compact = records.statistics_record(current)
		for item in report.overview(compact):
			if item['test_id'].startswith('selection.'):
				self.assertIsNone(item['headline']['median'])
				self.assertIn('selection.all.responsive_ms', item['metrics'])

	def test_report_product_name_comes_from_settings(self):
		with patch.object(report, 'get_build_settings', return_value={'app_name': 'RfmRenameProbe'}):
			html = report.render_html(self.record(), {})
		self.assertIn('<title>RfmRenameProbe | Performance</title>', html)
		self.assertIn('RfmRenameProbe <small>Performance', html)
		self.assertIn('RfmRenameProbe / Performance', html)
		self.assertNotIn('__APP_NAME__', html)

	def test_report_labels_use_consistent_capitalization_and_sizes(self):
		html = report.render_html(self.record(), {})
		self.assertIn("'recursive.tree':'Fuzzy Find (Recursive)'", html)
		self.assertNotIn('Recursive Find', html)
		for size in ('Small', 'Large', 'Medium'):
			self.assertIn('Pane Loading / ' + size, html)
			self.assertIn('Selections / ' + size, html)
			self.assertIn('QuickView Images / ' + size, html)
			self.assertIn('QuickView Text / ' + size, html)
		self.assertIn("'readback':'Selections Readback'", html)
		self.assertNotIn('Pane loading / ', html)

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

	def refresh_record(self, full=False):
		current = self.navigation_record(full=full)
		for identity in report.REFRESH_TESTS + (('refresh.medium',) if full else ()):
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

	def navigation_record(self, full=False):
		current = self.record()
		current['results'] = []
		identities = report.NAVIGATION_TESTS + (('pane.load.medium', 'quickview.medium') if full else ())
		for identity in identities:
			result = deepcopy(self.record()['results'][0])
			result['test_id'] = identity
			result['samples'] = [dict(ui=dict(navigation=[dict(action_id='navigation.' + action,
				input_to_paint_ms=10 if action != 'wheel-burst-down' else 20)
				for action in report.NAVIGATION_ACTIONS for iteration in range(5)]))]
			current['results'].append(result)
		current['catalog']['tests'] = [dict(id=identity) for identity in identities]
		return current

	def test_full_refresh_and_navigation_include_medium_and_reject_missing_cases(self):
		current = self.refresh_record(full=True)
		for identity, count, median in (('refresh.selection', 24, 70), ('navigation', 42, 80 / 7)):
			item = next(item for item in report.overview(current) if item['test_id'] == identity)
			self.assertEqual(count, item['headline']['count'])
			self.assertAlmostEqual(median, item['headline']['median'])
			self.assertIn('medium', item['fixture_id'])
		for identity in ('refresh.medium', 'quickview.medium'):
			result = next(result for result in current['results'] if result['test_id'] == identity)
			result['status'] = 'failed'
		for item in report.overview(current)[-2:]:
			self.assertEqual('incomplete', item['status'])
			self.assertIsNone(item['headline']['median'])

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

	def test_measure_modes_save_separate_history_and_open_report(self):
		for full, use_parent_alias in ((False, False), (False, True), (True, False), (True, True)):
			with self.subTest(full=full, use_parent_alias=use_parent_alias), TemporaryDirectory() as directory:
				history = Path(directory)
				if full:
					self.save(history, self.selection_record())
					regular_index = (history / 'versions.json').read_bytes()
				if use_parent_alias:
					(history / 'alias').mkdir()
					history = history / 'alias' / '..'
				output = history / 'Full' if full else history
				current = self.selection_record(full=full)
				def run_suite(arguments, *, record_saved):
					self.assertEqual(['--results', str(output / 'runs')] + (['--full'] if full else []), arguments)
					path = records.save_record(output / 'runs', current)
					record_saved(current, path)
					return 0
				with patch.object(report, 'HISTORY', history), \
					patch.object(suite, 'main', side_effect=run_suite) as run, \
					patch.object(report, 'render_html', return_value='<html>report</html>'), \
					patch.object(report.webbrowser, 'open', return_value=True) as browser, \
					redirect_stdout(io.StringIO()):
					self.assertEqual(0, report.main(['--full'] if full else []))
					run.assert_called_once()
					browser.assert_called_once_with((output / 'index.html').resolve().as_uri())
				self.assertEqual('<html>report</html>', (output / 'index.html').read_text())
				self.assertEqual({'1.0.0'}, set(report.read_history(output)))
				if full:
					self.assertEqual(regular_index, (history / 'versions.json').read_bytes())

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
				self.assertEqual(1, report.main([]))
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

	def test_measure_full_forwards_flag_without_running_verification(self):
		verification = Mock()
		with patch.object(self.build, '_require_windows'), \
			patch.object(self.build.subprocess, 'run', return_value=Mock(returncode=7)) as run, \
			patch.dict(self.build.COMMANDS, test=verification):
			self.assertEqual(7, self.build.main(['measure', '--full']))
		verification.assert_not_called()
		run.assert_called_once_with([
			sys.executable, str(self.build.ROOT / 'src/performancetest/run.py'), 'measure', '--full'
		], cwd=self.build.ROOT)

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
		for option in ('--profile', '--full'):
			with self.subTest(option=option), patch.dict(self.build.COMMANDS, test=verification), \
				redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
				self.build.main(['test', option])
			self.assertEqual(2, raised.exception.code)
		verification.assert_not_called()


class CopyBenchmarkTest(TestCase):
	def test_catalog_copy_dispatch_and_metrics(self):
		from fman_performancetest import copy
		catalog = records.load_catalog()
		self.assertFalse(any(test['workload'] == 'copy' for test in catalog['tests']))
		tests = [test for test in catalog['full_tests'] if test['workload'] == 'copy']
		self.assertEqual(['copy.flat', 'copy.tree'], [test['id'] for test in tests])
		self.assertEqual([2, 2], [test['revision'] for test in tests])
		for test, count, size in zip(tests, (10000, 1000), (4096, 8192)):
			self.assertEqual(count, catalog['fixtures'][test['fixture']]['files'])
			self.assertEqual(size, catalog['fixtures'][test['fixture']]['bytes_per_file'])
			with patch.object(copy, 'child', return_value=0) as child:
				self.assertEqual(0, suite.child(test, catalog, Path('fixture'), False, None))
				child.assert_called_once_with(Path('fixture'), catalog['protocol']['viewport'], count, size, None)
		result = dict(errors=[], settings_isolated=True, verified=True, samples=[
			dict(action_id='copy.selection', paint_ms=2, input_ready_ms=3, readback_ms=1, selected_count=15000),
			dict(action_id='copy.transfer', wall_ms=100, first_file_ms=5, preparation_ms=4, prompt_ms=1,
				throughput_mib_s=1, queued_task_count=15001, copied_count=15000, bytes_copied=15000 * 8192)])
		copy.validate_result(result, 15000, 8192)
		broken = deepcopy(result)
		broken['samples'][0]['input_ready_ms'] = 1
		with self.assertRaisesRegex(ValueError, 'input-ready'):
			copy.validate_result(broken, 15000, 8192)
		metrics = records.summarize(dict(samples=[dict(ui=result)]))
		self.assertEqual(5, metrics['copy.transfer.first_file_ms']['median'])
		for field, value in (('copied_count', 1), ('first_file_ms', 101), ('wall_ms', float('nan'))):
			broken = deepcopy(result)
			broken['samples'][1][field] = value
			with self.subTest(field=field), self.assertRaises(ValueError):
				copy.validate_result(broken, 15000, 8192)

	def test_timeout_cleans_parent_owned_scratch(self):
		from subprocess import TimeoutExpired
		catalog = records.load_catalog()
		test = next(test for test in catalog['full_tests'] if test['workload'] == 'copy')
		paths = []
		def run(command, **kwargs):
			paths.append(Path(command[command.index('--scratch') + 1]))
			self.assertTrue(paths[-1].is_dir())
			raise TimeoutExpired(command, kwargs['timeout'])
		with patch.object(suite.subprocess, 'run', side_effect=run), self.assertRaises(TimeoutExpired):
			suite.invoke(test, 'fixture', records.CATALOG)
		self.assertFalse(paths[0].exists())

	def test_native_copy_workload_verifies_contents(self):
		import os
		import subprocess
		code = """
from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fman_performancetest import fixtures, copy
offset = [0.0]
clock = copy.perf_counter
@contextmanager
def isolated_scratch(*args, **kwargs):
	with TemporaryDirectory(*args, **kwargs) as temporary:
		os.environ['ROYIFILEMANAGER_USER_SETTINGS'] = str(Path(temporary) / 'UserSettings')
		from fman.impl.view import FileListView
		select = FileListView.selectAll
		def measured_selection(view):
			offset[0] += .25
			return select(view)
		with patch.object(FileListView, 'selectAll', measured_selection):
			yield temporary
with TemporaryDirectory() as temporary:
	fixture = fixtures.prepare(temporary, 'copy-smoke', dict(revision=1, kind='copy', files=8, seed=1732, bytes_per_file=8192))
	with patch.object(copy, 'TemporaryDirectory', isolated_scratch), patch.object(copy, 'perf_counter', lambda: clock() + offset[0]):
		result = copy.child(Path(fixture['directory']), [1280, 800], 8, 8192)
	assert offset[0] == .25
	raise SystemExit(result)
"""
		env = dict(os.environ, QT_QPA_PLATFORM='windows')
		env['PYTHONPATH'] = os.pathsep.join((str(SCRIPT.parents[1]), env.get('PYTHONPATH', '')))
		result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', code], env=env, capture_output=True, text=True, timeout=60)
		self.assertEqual(0, result.returncode, result.stdout + result.stderr)
		payload = json.loads(next(line.removeprefix('SUITE_RESULT ') for line in result.stdout.splitlines() if line.startswith('SUITE_RESULT ')))
		self.assertTrue(payload['verified'])
		self.assertEqual(8, payload['samples'][0]['selected_count'])
		self.assertEqual(8, payload['samples'][1]['copied_count'])
		selection = payload['samples'][0]
		self.assertGreaterEqual(selection['paint_ms'], 250)
		self.assertGreaterEqual(selection['input_ready_ms'], selection['paint_ms'])
		metrics = records.summarize(dict(samples=[dict(ui=payload)]))
		self.assertEqual(selection['input_ready_ms'], metrics['copy.selection.input_ready_ms']['median'])

	def test_native_copy_tree_preserves_structure_and_selected_roots(self):
		import os
		import subprocess
		code = """
from pathlib import Path
from tempfile import TemporaryDirectory
from fman_performancetest import fixtures, copy
with TemporaryDirectory() as temporary:
    fixture = fixtures.prepare(temporary, 'tree-smoke', dict(revision=1, kind='copy', layout='tree', files=20, seed=1733, bytes_per_file=8192))
    raise SystemExit(copy.child(Path(fixture['directory']), [1280, 800], 20, 8192))
"""
		env = dict(os.environ, QT_QPA_PLATFORM='windows')
		env['PYTHONPATH'] = os.pathsep.join((str(SCRIPT.parents[1]), env.get('PYTHONPATH', '')))
		result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', code], env=env, capture_output=True, text=True, timeout=60)
		self.assertEqual(0, result.returncode, result.stdout + result.stderr)
		payload = json.loads(next(line.removeprefix('SUITE_RESULT ') for line in result.stdout.splitlines() if line.startswith('SUITE_RESULT ')))
		self.assertTrue(payload['verified'])
		self.assertEqual(10, payload['samples'][0]['selected_count'])
		self.assertEqual(20, payload['samples'][1]['copied_count'])


class SyntheticFixtureTest(TestCase):
	def test_copy_tree_has_reproducible_breadth_depth_and_payload(self):
		specification = dict(revision=1, kind='copy', layout='tree', files=120, seed=1733, bytes_per_file=8192)
		entries = dict(synthetic.entries(specification, {}))
		self.assertEqual(120, len(entries))
		self.assertEqual(entries, dict(synthetic.entries(specification, {})))
		self.assertEqual(10, len({name.split('/')[0] for name in entries}))
		self.assertEqual(set(range(4, 10)), {len(name.split('/')) for name in entries})
		self.assertTrue(all(len(payload) == 8192 for payload in entries.values()))
		with TemporaryDirectory() as directory:
			fixture = synthetic.prepare(directory, 'copy-tree-test', specification)
			self.assertEqual(fixture, synthetic.prepare(directory, 'copy-tree-test', specification))

	def test_copy_fixture_has_exact_reproducible_payloads_without_images(self):
		specification = dict(revision=1, kind='copy', files=8, seed=1732, bytes_per_file=8192)
		with TemporaryDirectory() as temporary, patch.object(synthetic, 'assets', side_effect=AssertionError('No images')):
			first = synthetic.prepare(temporary, 'copy-test', specification)
			self.assertEqual(first, synthetic.prepare(temporary, 'copy-test', specification))
			paths = sorted(Path(first['directory']).iterdir())
			self.assertEqual(8, len(paths))
			self.assertTrue(all(path.stat().st_size == 8192 for path in paths))
			self.assertNotEqual(paths[0].read_bytes(), paths[1].read_bytes())
			paths[0].write_bytes(b'modified')
			with self.assertRaisesRegex(ValueError, 'Modified fixture'):
				synthetic.prepare(temporary, 'copy-test', specification)

	def test_text_revision_adds_samples_without_changing_legacy_fixtures(self):
		images = {name: ('test-' + name).encode('ascii') for name in synthetic.ASSETS}
		legacy = dict(revision=1, kind='flat', files=8, seed=1729)
		current = dict(legacy, revision=2)
		with TemporaryDirectory() as temporary:
			before = synthetic.prepare(temporary, 'legacy', legacy, images)
			after = synthetic.prepare(temporary, 'text-v2', current, images)
			self.assertNotEqual(before['sha256'], after['sha256'])
			self.assertEqual(before, synthetic.prepare(temporary, 'legacy', legacy, images))
			self.assertEqual(after, synthetic.prepare(temporary, 'text-v2', current, images))
			for name, data in synthetic.TEXT_ASSETS.items():
				self.assertFalse((Path(before['directory']) / name).exists())
				self.assertEqual(data, (Path(after['directory']) / name).read_bytes())
			with self.assertRaises(ValueError):
				synthetic.prepare(temporary, 'legacy', current, images)

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
	def test_full_mode_adds_medium_without_default_fixture_io(self):
		catalog = records.load_catalog()
		self.assertEqual(13, len(catalog['tests']))
		self.assertEqual(['pane.load.medium', 'refresh.medium', 'filter.medium',
			'fuzzy.medium', 'quickview.medium', 'selection.medium', 'copy.flat', 'copy.tree'],
			[test['id'] for test in catalog['full_tests']])
		self.assertEqual(50000, catalog['fixtures']['flat-medium-v1']['files'])
		for test in catalog['full_tests']:
			if test['workload'] == 'copy':
				continue
			reference = next(item for item in catalog['tests'] if item['id'] == test['id'].replace('.medium', '.large'))
			self.assertEqual(dict(reference, id=test['id'], fixture=reference['fixture'].replace('large', 'medium')), test)
		for full in (False, True):
			with self.subTest(full=full), TemporaryDirectory() as temporary:
				prepared, published = [], []
				def prepare(directory, identity, specification, images):
					prepared.append(identity)
					return dict(id=identity, sha256='fixture', directory=temporary)
				with patch.object(suite, 'provenance', return_value={'commit': 'test', 'source_sha256': 'source'}), \
					patch.object(suite, 'environment', return_value={}), \
					patch.object(suite, 'source_hash', return_value='source'), \
					patch.object(suite.fixtures, 'assets', return_value={}), \
					patch.object(suite.fixtures, 'prepare', side_effect=prepare), \
					patch.object(suite, 'invoke') as invoke, redirect_stdout(io.StringIO()):
					self.assertEqual(0, suite.main(['--prepare-only', '--results', temporary] +
						(['--full'] if full else []), record_saved=lambda record, path: published.append(record)))
				invoke.assert_not_called()
				self.assertEqual(['flat-small-v1', 'flat-large-v1', 'recursive-v1', 'flat-small-v2', 'flat-large-v2'] +
					(['flat-medium-v1', 'flat-medium-v2', 'copy-flat-v1', 'copy-tree-v1'] if full else []), prepared)
				self.assertEqual(21 if full else 13, len(published[0]['catalog']['tests']))
				self.assertEqual('full' if full else 'regular', published[0]['suite_mode'])
				self.assertNotIn('full_tests', published[0]['catalog'])

	def test_medium_cases_can_be_listed_explicitly(self):
		with redirect_stdout(io.StringIO()) as output:
			self.assertEqual(0, suite.main(['--test', '*.medium', '--list']))
		self.assertEqual(6, len(output.getvalue().splitlines()))
		self.assertTrue(all('.medium' in line for line in output.getvalue().splitlines()))

	def test_medium_child_dispatch_does_not_require_parent_full_flag(self):
		catalog = records.load_catalog()
		for test in catalog['full_tests']:
			with self.subTest(identity=test['id']), TemporaryDirectory() as directory, \
				patch.object(suite, 'child', return_value=0) as child:
				self.assertEqual(0, suite.main(['--child', test['id'], '--directory', directory]))
				child.assert_called_once()
				self.assertEqual(test, child.call_args.args[0])

	def test_selection_batch_retains_completed_and_interrupted_cases(self):
		from subprocess import CalledProcessError, TimeoutExpired
		from fman_performancetest.selection import selection_cases
		catalog = records.load_catalog()
		test = next(test for test in catalog['tests'] if test['id'] == 'selection.small')
		cases = selection_cases(test['selection_count'])
		for timed_out in (False, True):
			with self.subTest(timed_out=timed_out):
				completed = dict(cases[0], status='passed', wall_ms=1, readback_ms=2, stage='verified')
				partial = dict(cases[1], status='running', wall_ms=123, stage='mutated')
				if not timed_out:
					partial.update(readback_ms=34, stage='readback')
				output = '\n'.join('SELECTION_PROGRESS ' + json.dumps(value) for value in (completed, partial))
				error = TimeoutExpired('probe', 25, output=output.encode()) if timed_out else \
					CalledProcessError(1, 'probe', output=output, stderr='Membership mismatch')
				with patch.object(suite, 'invoke', side_effect=error) as invoke, redirect_stdout(io.StringIO()):
					ui = suite.selection_run(test, 'fixture', records.CATALOG, catalog)
				invoke.assert_called_once_with(test, 'fixture', records.CATALOG, timeout=25)
				self.assertEqual(5, len(ui['samples']))
				self.assertEqual('passed', ui['samples'][0]['status'])
				self.assertEqual(4, len(ui['failures']))
				self.assertEqual('mutated' if timed_out else 'readback', ui['failures'][0]['stage'])
				self.assertEqual(['not-run'] * 3, [item['status'] for item in ui['failures'][1:]])
				compact = records.statistics_record(dict(schema_version=2,
					results=[dict(samples=[dict(ui=ui)], failures=ui['failures'])]))
				result, = compact['results']
				self.assertEqual(ui['failures'], result['failures'])
				self.assertEqual(1, result['summary'][cases[0]['action_id'] + '.wall_ms']['median'])
				self.assertEqual(123, result['summary'][cases[1]['action_id'] + '.wall_ms']['median'])
				if timed_out:
					self.assertNotIn(cases[1]['action_id'] + '.readback_ms', result['summary'])
					self.assertEqual(1, result['summary'][cases[1]['action_id'] + '.timeout_count']['median'])
				else:
					self.assertEqual('Membership mismatch', ui['failures'][0]['error'])
					self.assertEqual(34, result['summary'][cases[1]['action_id'] + '.readback_ms']['median'])

	def test_selection_workloads_use_six_bounded_processes(self):
		from fman_performancetest.selection import selection_cases
		catalog = records.load_catalog()
		tests = [test for test in catalog['tests'] if test['workload'] == 'selection']
		calls = []
		def invoke(test, directory, catalog_path, *, timeout):
			calls.append((test['id'], timeout))
			return dict(errors=[], settings_isolated=True, samples=[dict(case, status='passed')
				for case in selection_cases(test['selection_count'])])
		with patch.object(suite, 'invoke', side_effect=invoke), redirect_stdout(io.StringIO()):
			for test in tests:
				for iteration in range(catalog['protocol']['repetitions']):
					result = suite.selection_run(test, 'fixture', records.CATALOG, catalog)
					self.assertEqual(5, len(result['samples']))
					self.assertEqual([], result['failures'])
		self.assertEqual(6, len(calls))
		self.assertEqual(150, sum(timeout for identity, timeout in calls))

	def test_source_change_invalidates_reference_and_later_workloads_still_run(self):
		for changed in (False, True):
			with self.subTest(changed=changed), TemporaryDirectory() as temporary:
				calls = []
				def invoke(test, directory, catalog_path):
					calls.append(test['id'])
					if test['id'] == 'pane.load.small' and not changed:
						raise RuntimeError('Expected first workload failure')
					return dict(errors=[], settings_isolated=True, first_paint_ms=10)
				with patch.object(suite, 'provenance', return_value={'commit': 'test', 'source_sha256': 'source'}), \
					patch.object(suite, 'environment', return_value={}), \
					patch.object(suite, 'source_hash', side_effect=['harness', 'changed' if changed else 'source', 'harness']), \
					patch.object(suite.fixtures, 'assets', return_value={}), \
					patch.object(suite.fixtures, 'prepare', return_value=dict(id='fixture', sha256='hash', directory=temporary)), \
					patch.object(suite, 'invoke', side_effect=invoke), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
					self.assertEqual(1, suite.main(['--test', 'pane.*', '--repeat', '1', '--results', temporary]))
				self.assertEqual(['pane.load.small', 'pane.load.large', 'pane.load.medium'], calls)
				record = json.loads(next(Path(temporary).glob('*.json')).read_text())
				self.assertEqual('failed', record['status'])
				self.assertEqual('passed', record['results'][1]['status'])
				self.assertIn('source changed' if changed else 'Expected first workload failure', record['error'])

	def test_selection_catalog_has_two_flat_sizes_and_dispatches_five_cases(self):
		from fman_performancetest import pane_rendering_benchmark
		from fman_performancetest.selection import selection_cases
		catalog = records.load_catalog()
		tests = [test for test in catalog['tests'] if test['workload'] == 'selection']
		self.assertEqual(['selection.small', 'selection.large'], [test['id'] for test in tests])
		self.assertEqual([256, 200000], [catalog['fixtures'][test['fixture']]['files'] for test in tests])
		self.assertEqual([64, 1000], [test['selection_count'] for test in tests])
		for test in tests + [test for test in catalog['full_tests'] if test['workload'] == 'selection']:
			cases = selection_cases(test['selection_count'])
			self.assertEqual(5, len(cases))
			expected = [dict(case, row_count=catalog['fixtures'][test['fixture']]['files']) for case in cases]
			with patch.object(pane_rendering_benchmark, 'child', return_value=0) as child:
				self.assertEqual(0, suite.child(test, catalog, Path('fixture'), False, None))
				child.assert_called_once_with(Path('fixture'), test['id'], 'snapshot', True,
					viewport=catalog['protocol']['viewport'], selection_cases=expected)

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
		for test in catalog['tests'] + catalog['full_tests']:
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
		self.assertEqual(13, len(catalog['tests']))
		self.assertEqual(before, records.CATALOG.read_bytes())
		self.assertEqual(records.digest(catalog), records.digest(json.loads(json.dumps(catalog))))

	def test_duplicate_keys_and_test_ids_are_rejected(self):
		with TemporaryDirectory() as temporary:
			path = Path(temporary) / 'catalog.yaml'
			path.write_text('schema_version: 1\nschema_version: 1\n', encoding='utf-8')
			with self.assertRaises(ValueError):
				records.load_catalog(path)
			for section in ('tests', 'full_tests'):
				catalog = records.load_catalog()
				catalog[section].append(catalog['tests'][0])
				path.write_text(json.dumps(catalog), encoding='utf-8')
				with self.subTest(section=section), self.assertRaises(ValueError):
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