"""Catalog validation and immutable, version-attributed performance evidence."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import uuid

import yaml


ROOT = Path(__file__).resolve().parents[4]
CATALOG = ROOT / 'src/performancetest/catalog.yaml'
WORKLOADS = {'pane', 'refresh', 'filter', 'fuzzy', 'recursive', 'quickview'}


def digest(value):
	return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
		separators=(',', ':'), allow_nan=False).encode('ascii')).hexdigest()


class CatalogLoader(yaml.SafeLoader):
	pass


def mapping(loader, node):
	result = {}
	for key_node, value_node in node.value:
		key = loader.construct_object(key_node)
		if key in result:
			raise ValueError('Duplicate YAML key: ' + str(key))
		result[key] = loader.construct_object(value_node)
	return result


CatalogLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def positive(value):
	return type(value) is int and value > 0


def load_catalog(path=CATALOG):
	catalog = yaml.load(Path(path).read_text(encoding='utf-8'), Loader=CatalogLoader)
	if not isinstance(catalog, dict) or catalog.get('schema_version') != 1:
		raise ValueError('Unsupported catalog schema')
	if not positive(catalog.get('suite_revision')) or not catalog.get('suite_id'):
		raise ValueError('Invalid suite identity')
	protocol = catalog['protocol']
	if not positive(protocol['repetitions']) or protocol['cache'] != 'warm' or protocol['dpi_scale'] != 1:
		raise ValueError('Unsupported measurement protocol')
	if len(protocol['viewport']) != 2 or not all(positive(size) for size in protocol['viewport']):
		raise ValueError('Invalid viewport')
	if protocol['metadata'] is not False or protocol['max_results'] != 100 or not positive(protocol['max_entries']):
		raise ValueError('Unsupported search settings')
	if protocol['navigation_keys'] != ['page-up', 'page-down', 'home', 'end'] or not positive(protocol['navigation_repetitions']):
		raise ValueError('Unsupported navigation protocol')
	if protocol['wheel'] != dict(delta=120, scroll_lines=3, burst_events=10):
		raise ValueError('Unsupported wheel protocol')
	if protocol['refresh_selections'] != ['none', 'single-first', 'single-middle', 'single-last',
		'middle-block', 'scattered', 'all-except-current', 'all']:
		raise ValueError('Unsupported refresh selection protocol')
	for fixture in catalog['fixtures'].values():
		if fixture['revision'] != 1 or fixture['kind'] not in ('flat', 'recursive') or not positive(fixture['files']) or fixture['files'] < 8 or type(fixture['seed']) is not int:
			raise ValueError('Invalid fixture definition')
	identities = set()
	for test in catalog['tests']:
		identity = test['id']
		if not isinstance(identity, str) or not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', identity) or identity in identities:
			raise ValueError('Invalid or duplicate test ID: ' + str(identity))
		identities.add(identity)
		if not positive(test['revision']) or test['workload'] not in WORKLOADS or test['fixture'] not in catalog['fixtures']:
			raise ValueError('Invalid test definition: ' + identity)
	for workload in ('filter', 'fuzzy', 'recursive'):
		queries = catalog['queries'][workload]
		identities = [query['id'] for query in queries]
		if not queries or len(set(identities)) != len(identities) or not all(
			re.fullmatch(r'[a-z0-9-]+', query['id']) and isinstance(query['text'], str) and query['text'] for query in queries):
			raise ValueError('Invalid query IDs or text: ' + workload)
	return catalog


def new_record(catalog, application, environment):
	return dict(schema_version=1, run_id=str(uuid.uuid4()),
		started_at=datetime.now(timezone.utc).isoformat(),
		application=application, environment=environment,
		catalog=catalog, catalog_sha256=digest(catalog), results=[])


def save_record(directory, record):
	directory = Path(directory)
	directory.mkdir(parents=True, exist_ok=True)
	payload = json.dumps(record, indent=2, allow_nan=False) + '\n'
	path = directory / (record['run_id'] + '.json')
	with path.open('x', encoding='utf-8') as output:
		output.write(payload)
	return path


def measurements(result):
	values = {}
	def add(name, value):
		if type(value) in (int, float):
			values.setdefault(name, []).append(value)
	for sample in result['samples']:
		ui = sample['ui']
		for name in ('first_paint_ms', 'complete_ms', 'working_set_mib', 'peak_working_set_mib'):
			add(name, ui.get(name))
		add('open.paint_ms', ui.get('open', {}).get('paint_ms'))
		for navigation in ui.get('navigation', []):
			for name in ('event_dispatch_ms', 'key_to_cursor_ms', 'input_to_scroll_ms', 'input_to_paint_ms'):
				add(navigation['action_id'] + '.' + name, navigation.get(name))
		for phase in ui.get('samples', []):
			identity = phase.get('query_id', phase.get('action_id'))
			for name in ('paint_ms', 'input_to_paint_ms', 'cpu_ms', 'qt_commit_ms',
				'working_set_before_mib', 'working_set_mib', 'peak_working_set_before_mib', 'peak_working_set_mib'):
				add(identity + '.' + name, phase.get(name))
			for name in ('heartbeat_gap_ms', 'queue_dispatch_ms'):
				add(identity + '.' + name + '.max', phase.get(name, {}).get('max'))
		algorithm = sample.get('algorithm', {})
		for name in ('scan_ms', 'index_ms', 'matcher_construction_ms'):
			add('algorithm.' + name, algorithm.get(name))
		for query in algorithm.get('queries', []):
			for observation in query['samples']:
				for name in ('wall_ms', 'cpu_ms'):
					add('algorithm.' + query['query_id'] + '.' + name, observation[name])
	return values


def summarize(result):
	return {name: dict(count=len(values), median=statistics.median(values),
		minimum=min(values), maximum=max(values),
		p95=sorted(values)[min(len(values) - 1, int(len(values) * .95))] if len(values) >= 20 else None)
		for name, values in measurements(result).items()}


def compare(baseline, current):
	for record in (baseline, current):
		if record.get('schema_version') != 1 or record.get('status') != 'passed':
			raise ValueError('Only successful schema-1 runs can be compared')
	for field in ('machine_id', 'configuration_sha256'):
		if baseline['environment'][field] != current['environment'][field]:
			raise ValueError('Environment mismatch: ' + field)
	if baseline['harness']['source_sha256'] != current['harness']['source_sha256']:
		raise ValueError('Harness source differs; rerun both versions with the same harness')
	previous = {result['test_id']: result for result in baseline['results']}
	comparisons = []
	for result in current['results']:
		old = previous.get(result['test_id'])
		if old is None:
			continue
		for field in ('test_revision', 'fixture_sha256', 'definition_sha256', 'status'):
			if old[field] != result[field] or result['status'] != 'passed':
				raise ValueError('Incompatible test: ' + result['test_id'] + ' (' + field + ')')
		before, after = summarize(old), summarize(result)
		if before.keys() != after.keys() or not before:
			raise ValueError('Incomplete metrics: ' + result['test_id'])
		for metric in before:
			previous_value, current_value = before[metric]['median'], after[metric]['median']
			comparisons.append(dict(test_id=result['test_id'], metric=metric,
				baseline_median=previous_value, current_median=current_value,
				change_percent=(current_value / previous_value - 1) * 100 if previous_value else None))
	if not comparisons:
		raise ValueError('No common tests')
	return comparisons