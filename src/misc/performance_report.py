"""Retained version history and offline presentation for the benchmark suite."""

import base64
import json
from pathlib import Path
import re
import statistics
import sys
from tempfile import NamedTemporaryFile
import webbrowser

from fman_performancetest.records import ROOT, compare, digest, summarize
from fman_performancetest.pane_rendering_benchmark import REFRESH_SELECTIONS


HISTORY = ROOT / 'UserSettings' / 'Performance'
NAVIGATION_TESTS = ('pane.load.small', 'pane.load.large', 'quickview.small', 'quickview.large')
NAVIGATION_ACTIONS = ('page-up', 'page-down', 'home', 'end', 'wheel-up', 'wheel-down', 'wheel-burst-down')
REFRESH_TESTS = ('refresh.small', 'refresh.large')


def atomic_write(path, text):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary = None
	try:
		with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
			delete=False, suffix='.tmp') as output:
			temporary = Path(output.name)
			output.write(text)
		temporary.replace(path)
	finally:
		if temporary is not None:
			temporary.unlink(missing_ok=True)


def version_id(record):
	identity = record['application'].get('version_id', 'Unreleased')
	if identity != 'Unreleased' and not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', identity):
		raise ValueError('Version identifier must be X.Y.Z or Unreleased')
	return identity


def complete(record):
	definitions = record['catalog']['tests']
	results = record['results']
	repetitions = record['parameters']['repetitions']
	return (record['schema_version'] == 1 and record['status'] == 'passed'
		and len(results) == len(definitions) and bool(definitions)
		and {result['test_id'] for result in results} == {test['id'] for test in definitions}
		and all(result['status'] == 'passed' and len(result['samples']) == repetitions
			for result in results))


def read_history(directory):
	directory = Path(directory)
	index_path = directory / 'versions.json'
	if not index_path.exists():
		return {}
	index = json.loads(index_path.read_text(encoding='utf-8'))
	if index['schema_version'] != 1:
		raise ValueError('Unsupported performance history schema')
	versions = {}
	for version, identity in index['versions'].items():
		if not re.fullmatch(r'[a-f0-9-]{36}', identity):
			raise ValueError('Invalid run identity in performance history')
		record = json.loads((directory / 'runs' / (identity + '.json')).read_text(encoding='utf-8'))
		if record['run_id'] != identity or version_id(record) != version or not complete(record):
			raise ValueError('Invalid version result: ' + version)
		versions[version] = record
	return versions


def update_history(directory, record):
	directory = Path(directory)
	versions = read_history(directory)
	identity = version_id(record)
	if complete(record):
		stored = json.loads((directory / 'runs' / (record['run_id'] + '.json')).read_text(encoding='utf-8'))
		if digest(stored) != digest(record):
			raise ValueError('Version result does not match its saved run')
		versions[identity] = stored
		index = dict(schema_version=1, versions={version: item['run_id'] for version, item in versions.items()})
		atomic_write(directory / 'versions.json', json.dumps(index, indent=2, allow_nan=False) + '\n')
	return versions


def report_data(current, versions):
	tests = overview(current)
	previous = []
	for version, record in sorted(versions.items(), key=lambda item: item[1]['started_at'], reverse=True):
		if version == version_id(current):
			continue
		item = dict(version=version, run_id=record['run_id'], started_at=record['started_at'],
			application=record['application'])
		try:
			if not complete(current):
				raise ValueError('Current run is incomplete; saved version results are unchanged')
			item['changes'] = compare(record, current)
			prior_tests = overview(record)
			item['headlines'] = {test['test_id']: test['headline'] for test in prior_tests}
			prior = {test['test_id']: test for test in prior_tests}
			for test in tests:
				identity = test['test_id']
				if identity not in ('navigation', 'refresh.selection') or identity not in prior:
					continue
				before, after = prior[identity]['metrics'], test['metrics']
				if before.keys() == after.keys():
					for metric in before:
						first, last = before[metric]['median'], after[metric]['median']
						item['changes'].append(dict(test_id=identity, metric=metric,
							baseline_median=first, current_median=last,
							change_percent=(last / first - 1) * 100 if first else None))
			item['compatible'] = True
		except ValueError as error:
			item.update(compatible=False, reason=str(error), changes=[])
		previous.append(item)
	return dict(run_id=current['run_id'], version=version_id(current), started_at=current['started_at'],
		saved_versions=len(versions),
		expected_tests=len(current['catalog']['tests']),
		completed_tests=sum(result['status'] == 'passed' for result in current['results']),
		finished_at=current['finished_at'], status=current['status'],
		application=current['application'], environment=current['environment'],
		parameters=current['parameters'], tests=tests, previous=previous,
		error=current.get('error'), complete=complete(current))


def headline(identity, metrics):
	if identity.startswith('pane.'):
		metric, label = 'first_paint_ms', 'First populated paint'
	elif identity.startswith('quickview.'):
		metric, label = 'enable.png.input_to_paint_ms', 'First preview paint'
	else:
		candidates = {name: value for name, value in metrics.items()
			if name.endswith('.paint_ms') and name != 'open.paint_ms'}
		metric = max(candidates, key=lambda name: candidates[name]['median']) if candidates else ''
		label = 'Slowest query median'
	return dict(label=label, metric=metric, count_label='samples', **metrics.get(metric, dict(
		median=None, minimum=None, maximum=None, count=0, p95=None)))


def overview(record):
	tests = [dict(test_id=result['test_id'], status=result['status'],
		fixture_id=result['fixture_id'], metrics=summarize(result)) for result in record['results']]
	refresh = [test for test in tests if test['test_id'] in REFRESH_TESTS]
	tests = [test for test in tests if test['test_id'] not in REFRESH_TESTS]
	for test in tests:
		test['headline'] = headline(test['test_id'], test['metrics'])
	if any(test['id'] in REFRESH_TESTS for test in record['catalog']['tests']):
		metrics = {test['test_id'] + '.' + name: value for test in refresh
			if test['status'] == 'passed' for name, value in test['metrics'].items()}
		expected = [test + '.refresh.' + pattern + '.paint_ms'
			for test in REFRESH_TESTS for pattern in REFRESH_SELECTIONS]
		values = [metrics[name]['median'] for name in expected if name in metrics]
		valid = len(values) == len(expected)
		tests.append(dict(test_id='refresh.selection', status='passed' if valid else 'incomplete',
			fixture_id='Small + large / eight selection patterns', metrics=metrics,
			headline=dict(label='Mean of refresh case medians', metric='refresh.aggregate',
				median=statistics.mean(values) if valid else None,
				minimum=min(values) if valid else None, maximum=max(values) if valid else None,
				count=len(values), count_label='case medians', p95=None)))
	components = {}
	for test in tests:
		if test['test_id'] not in NAVIGATION_TESTS or test['status'] != 'passed':
			continue
		for action in NAVIGATION_ACTIONS:
			metric = 'navigation.' + action + '.input_to_paint_ms'
			if metric in test['metrics']:
				components[test['test_id'] + '.' + metric] = test['metrics'][metric]
	values = [component['median'] for component in components.values()]
	valid = len(values) == len(NAVIGATION_TESTS) * len(NAVIGATION_ACTIONS)
	tests.append(dict(test_id='navigation', status='passed' if valid else 'incomplete',
		fixture_id='Small + large / QuickView off + on', metrics=components,
		headline=dict(label='Mean of action medians', metric='navigation.aggregate',
			median=statistics.mean(values) if valid else None,
			minimum=min(values) if valid else None, maximum=max(values) if valid else None,
			count=len(values), count_label='case medians', p95=None)))
	return tests


def render_html(current, versions):
	payload = json.dumps(report_data(current, versions), ensure_ascii=True, allow_nan=False)
	payload = payload.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
	template = Path(__file__).with_suffix('.html').read_text(encoding='utf-8')
	icon = base64.b64encode((ROOT / 'src/main/icons/base/32.png').read_bytes()).decode('ascii')
	return template.replace('__PERFORMANCE_ICON__', icon).replace('__PERFORMANCE_DATA__', payload)


def main():
	from fman_performancetest import suite
	saved = []
	try:
		read_history(HISTORY)
		status = suite.main(['--results', str(HISTORY / 'runs')],
			record_saved=lambda record, path: saved.append(record))
		if not saved:
			raise ValueError('The benchmark suite returned no run record')
		current = saved[0]
		versions = update_history(HISTORY, current)
		output = HISTORY / 'index.html'
		atomic_write(output, render_html(current, versions))
		print('Performance report: ' + str(output), flush=True)
	except Exception as error:
		print('Measurement/report failed: ' + str(error), file=sys.stderr)
		return 1
	try:
		if not webbrowser.open(output.resolve().as_uri()):
			print('Browser did not open; the HTML report is available at the path above.', file=sys.stderr)
	except OSError as error:
		print('Browser could not open: ' + str(error), file=sys.stderr)
	return status if complete(current) else 1


if __name__ == '__main__':
	sys.exit(main())