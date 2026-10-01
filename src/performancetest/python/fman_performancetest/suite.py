"""Versioned synthetic benchmark suite. All workloads are explicitly requested."""

import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import traceback

from fman_performancetest import fixtures
from fman_performancetest.records import CATALOG, ROOT, compare, digest, load_catalog, new_record, save_record, statistics_record, summarize


def git(*arguments):
	return subprocess.check_output(['git', *arguments], cwd=ROOT)


def source_hash(*paths):
	names = git('ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', *paths).decode('utf-8').split('\0')
	values = []
	for name in sorted(set(names) - {''}):
		path = ROOT / name
		values.append((name, hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None))
	return digest(values)


def provenance():
	settings = json.loads((ROOT / 'src/build/settings/base.json').read_text(encoding='utf-8'))
	version = settings['version']
	if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
		raise ValueError('Application version must be X.Y.Z')
	commit = git('rev-parse', 'HEAD').decode().strip()
	dirty = bool(git('status', '--porcelain', '--untracked-files=normal'))
	tags = git('tag', '--points-at', 'HEAD').decode().splitlines()
	identity = version if not dirty and (version in tags or 'v' + version in tags) else 'Unreleased'
	return dict(version=version, version_id=identity, commit=commit, dirty=dirty,
		source_sha256=source_hash('src/main', 'src/build', 'environment.yml', 'conda-lock.yml'))


def environment(directory):
	from PyQt5.QtCore import QLocale, QT_VERSION_STR, PYQT_VERSION_STR
	import win32api
	import win32com.client
	devices = []
	errors = []
	try:
		service = win32com.client.GetObject('winmgmts:')
		for disk in service.ExecQuery('SELECT Model, MediaType, InterfaceType, Size FROM Win32_DiskDrive'):
			devices.append(dict(model=disk.Model, media_type=disk.MediaType,
				interface=disk.InterfaceType, bytes=int(disk.Size or 0)))
	except Exception as error:
		errors.append(type(error).__name__ + ': storage inventory unavailable')
	dependencies = sorted((item.metadata['Name'], item.version) for item in importlib.metadata.distributions() if item.metadata['Name'])
	root = str(Path(directory).resolve().anchor)
	volume = win32api.GetVolumeInformation(root)
	config = dict(python=sys.version, qt=QT_VERSION_STR, pyqt=PYQT_VERSION_STR,
		os=platform.platform(), cpu=platform.processor(), logical_cpus=os.cpu_count(),
		ram_bytes=win32api.GlobalMemoryStatusEx()['TotalPhys'], disks=devices,
		filesystem=volume[4], volume_id=digest(volume[1]), locale=QLocale.system().name(),
		timezone=list(time.tzname), utc_offset_seconds=time.timezone,
		power_scheme=subprocess.check_output(['powercfg', '/getactivescheme'], text=True).strip(),
		dependencies=dependencies, errors=errors)
	return dict(machine_id=hashlib.sha256(platform.node().encode()).hexdigest()[:16],
		configuration=config, configuration_sha256=digest(config))


def invoke(test, directory, catalog_path, profile_directory=None, algorithm=False, selection_case=None, timeout=300):
	command = [sys.executable, '-m', 'fman_performancetest.suite', '--catalog', str(catalog_path),
		'--child', test['id'], '--directory', str(directory)]
	if algorithm:
		command.append('--algorithm')
	if selection_case is not None:
		command.extend(('--selection-case', selection_case['action_id']))
	if profile_directory is not None:
		command.extend(('--profile-directory', str(profile_directory)))
	env = dict(os.environ, QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1',
		QT_AUTO_SCREEN_SCALE_FACTOR='0', QT_ENABLE_HIGHDPI_SCALING='0',
		QT_FONT_DPI='96', PYTHONHASHSEED='0', TZ='UTC')
	result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
	if result.returncode:
		raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)
	for line in result.stdout.splitlines():
		for prefix in ('SUITE_RESULT ', 'SEARCH_UI_RESULT ', 'PANE_RESULT ', 'QUICKVIEW_RESULT '):
			if line.startswith(prefix):
				return json.loads(line[len(prefix):])
	raise RuntimeError('Child returned no structured result')


def selection_run(test, directory, catalog_path, catalog):
	from fman_performancetest.selection import selection_cases
	cases = selection_cases(test['selection_count'])
	samples, failures = [], []
	timeout = catalog['protocol']['selection_timeout_seconds']
	for index, case in enumerate(cases, 1):
		try:
			result = invoke(test, directory, catalog_path, selection_case=case, timeout=timeout)
			if result['errors'] or not result['settings_isolated']:
				raise RuntimeError('Application errors or settings isolation failure')
			measurement, = result['samples']
			if measurement['action_id'] != case['action_id'] or measurement['status'] != 'passed':
				raise RuntimeError('Invalid selection case result')
		except Exception as error:
			measurement = dict(case)
			output = getattr(error, 'stdout', '') or ''
			if isinstance(output, bytes):
				output = output.decode('utf-8', errors='replace')
			for line in output.splitlines():
				if line.startswith('SELECTION_PROGRESS '):
					progress = json.loads(line.removeprefix('SELECTION_PROGRESS '))
					if progress.get('action_id') == case['action_id']:
						measurement.update(progress)
			timed_out = isinstance(error, subprocess.TimeoutExpired)
			measurement['status'] = 'timeout' if timed_out else 'failed'
			if timed_out:
				measurement['timeout_count'] = 1
			reason = 'Child exceeded %ds including startup' % timeout if timed_out else getattr(error, 'stderr', None) or str(error)
			failures.append(dict(action_id=case['action_id'], status=measurement['status'],
				stage=measurement.get('stage', 'startup'), error=reason))
		samples.append(measurement)
		print('%s: case %d/%d %s %s' % (test['id'], index, len(cases), case['action_id'], measurement['status']), flush=True)
	return dict(samples=samples, failures=failures)


def child(test, catalog, directory, algorithm, profile_directory, selection_case=None):
	workload = test['workload']
	protocol = catalog['protocol']
	if workload == 'selection':
		from fman_performancetest.selection import selection_cases
		from fman_performancetest.pane_rendering_benchmark import child as pane
		case = next(case for case in selection_cases(test['selection_count']) if case['action_id'] == selection_case)
		case['row_count'] = catalog['fixtures'][test['fixture']]['files']
		return pane(directory, test['id'], 'snapshot', True,
			viewport=protocol['viewport'], selection_case=case)
	if workload in ('filter', 'fuzzy', 'recursive'):
		queries = catalog['queries'][workload]
		if algorithm:
			from fman_performancetest.filter_find import algorithms
			result = algorithms(directory, workload, 1, protocol['max_entries'], profile_directory,
				[query['text'] for query in queries])
			for query, measurement in zip(queries, result['queries']):
				measurement['query_id'] = query['id']
			print('SUITE_RESULT ' + json.dumps(result), flush=True)
			return 0
		from fman_performancetest.search_ui import child as search
		return search(directory, workload, 1, protocol['max_entries'], queries, True, protocol['viewport'])
	if workload in ('pane', 'refresh'):
		from fman_performancetest.pane_rendering_benchmark import child as pane
		return pane(directory, test['id'], 'snapshot', True, viewport=protocol['viewport'],
			navigation_repetitions=protocol['navigation_repetitions'] if workload == 'pane' else 0,
			refresh_patterns=protocol['refresh_selections'] if workload == 'refresh' else ())
	from fman_performancetest.quickview import child as quickview
	return quickview(directory, protocol['viewport'], protocol['navigation_repetitions'])


def main(argv=None, *, record_saved=None):
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--catalog', type=Path, default=CATALOG)
	parser.add_argument('--test', action='append', default=[], help='Test ID or glob; repeat for multiple selections')
	parser.add_argument('--repeat', type=int, help='Override fresh-process repetitions; recorded in the result')
	parser.add_argument('--list', action='store_true')
	parser.add_argument('--prepare-only', action='store_true')
	parser.add_argument('--fixtures', type=Path, default=ROOT / 'target/performance/fixtures')
	parser.add_argument('--results', type=Path, default=ROOT / 'target/performance/runs')
	parser.add_argument('--profile', action='store_true')
	parser.add_argument('--compare', nargs=2, type=Path, metavar=('BASELINE', 'CURRENT'))
	parser.add_argument('--note', default='')
	parser.add_argument('--child', help=argparse.SUPPRESS)
	parser.add_argument('--directory', type=Path, help=argparse.SUPPRESS)
	parser.add_argument('--algorithm', action='store_true', help=argparse.SUPPRESS)
	parser.add_argument('--profile-directory', type=Path, help=argparse.SUPPRESS)
	parser.add_argument('--selection-case', help=argparse.SUPPRESS)
	args = parser.parse_args(argv)
	if args.compare:
		try:
			rows = compare(*(json.loads(path.read_text(encoding='utf-8')) for path in args.compare))
			print(json.dumps(rows, indent=2, allow_nan=False))
			return 0
		except ValueError as error:
			parser.error(str(error))
	catalog = load_catalog(args.catalog)
	if args.child:
		test = next(test for test in catalog['tests'] if test['id'] == args.child)
		return child(test, catalog, args.directory.resolve(strict=True), args.algorithm, args.profile_directory, args.selection_case)
	if args.repeat is not None and args.repeat < 1:
		parser.error('--repeat must be positive')
	selected = [test for test in catalog['tests'] if not args.test or any(fnmatch.fnmatchcase(test['id'], pattern) for pattern in args.test)]
	if not selected:
		parser.error('No matching test IDs')
	if args.list:
		for test in selected:
			print('%-24s revision=%d fixture=%s' % (test['id'], test['revision'], test['fixture']))
		return 0
	if sys.platform != 'win32':
		parser.error('The native suite requires Windows')
	args.results = args.results.resolve()
	repetitions = args.repeat or catalog['protocol']['repetitions']
	record = new_record(catalog, provenance(), environment(args.fixtures))
	record['harness'] = dict(commit=record['application']['commit'], source_sha256=source_hash('src/performancetest'))
	record['parameters'] = dict(catalog['protocol'], repetitions=repetitions)
	record['notes'] = args.note
	record['status'] = 'failed'
	record['artifacts'] = []
	try:
		image_assets = fixtures.assets()
		prepared = {}
		for test in selected:
			identity = test['fixture']
			if identity not in prepared:
				prepared[identity] = fixtures.prepare(args.fixtures, identity, catalog['fixtures'][identity], image_assets)
				print('Verified fixture: %s (%d files)' % (identity, catalog['fixtures'][identity]['files']), flush=True)
		record['fixtures'] = [{key: value for key, value in item.items() if key != 'directory'} for item in prepared.values()]
		if not args.prepare_only:
			for test in selected:
				fixture = prepared[test['fixture']]
				result = dict(test_id=test['id'], test_revision=test['revision'], fixture_id=test['fixture'],
					fixture_sha256=fixture['sha256'], definition_sha256=digest(dict(test=test,
					queries=catalog['queries'].get(test['workload']), protocol=record['parameters'])), status='failed', samples=[])
				record['results'].append(result)
				try:
					for iteration in range(repetitions):
						if test['workload'] == 'selection':
							ui = selection_run(test, fixture['directory'], args.catalog.resolve(), catalog)
							result.setdefault('failures', []).extend(dict(failure, iteration=iteration + 1) for failure in ui['failures'])
						else:
							ui = invoke(test, fixture['directory'], args.catalog.resolve())
							if ui['errors'] or not ui['settings_isolated']:
								raise ValueError('Application errors or settings isolation failure')
						sample = dict(iteration=iteration + 1, ui=ui)
						if test['workload'] in ('filter', 'fuzzy', 'recursive'):
							sample['algorithm'] = invoke(test, fixture['directory'], args.catalog.resolve(), algorithm=True)
							if sample['algorithm']['truncated']:
								raise ValueError('Catalog workload was truncated')
							counts = {query['query_id']: query['returned'] for query in sample['algorithm']['queries']}
							if any(query['rows'] != counts[query['query_id']] for query in ui['samples']):
								raise ValueError('UI and algorithm result counts differ')
						result['samples'].append(sample)
						print('%s: repetition %d/%d completed' % (test['id'], iteration + 1, repetitions), flush=True)
					if args.profile and test['workload'] in ('filter', 'fuzzy', 'recursive'):
						profile_directory = args.results / (record['run_id'] + '-profiles') / test['id']
						invoke(test, fixture['directory'], args.catalog.resolve(), profile_directory, True)
						record['artifacts'].append(profile_directory.relative_to(args.results).as_posix())
					result['status'] = 'failed' if result.get('failures') else 'passed'
					if result['status'] == 'failed':
						result['error'] = '%d selection case failures' % len(result['failures'])
				except Exception as error:
					result['error'] = str(error)
					traceback.print_exc()
				result['summary'] = summarize(result)
		failed = [result for result in record['results'] if result['status'] != 'passed']
		record['status'] = 'prepared' if args.prepare_only else 'failed' if failed else 'passed'
		if failed:
			record['error'] = '\n'.join(result['test_id'] + ': ' + result.get('error', 'Failed') for result in failed)
		if record['application'].get('source_sha256') is not None and record['application']['source_sha256'] != source_hash(
			'src/main', 'src/build', 'environment.yml', 'conda-lock.yml'):
			raise RuntimeError('Application source changed during measurement; reference is invalid')
		if record['harness']['source_sha256'] != source_hash('src/performancetest'):
			raise RuntimeError('Benchmark harness changed during measurement; reference is invalid')
	except Exception as error:
		record['status'] = 'failed'
		record['error'] = str(error)
		traceback.print_exc()
	finally:
		record['finished_at'] = datetime.now(timezone.utc).isoformat()
		record = statistics_record(record)
		path = save_record(args.results, record)
		print('Run record: ' + str(path), flush=True)
	if record_saved is not None:
		record_saved(record, path)
	return 0 if record['status'] in ('prepared', 'passed') else 1


if __name__ == '__main__':
	sys.exit(main())