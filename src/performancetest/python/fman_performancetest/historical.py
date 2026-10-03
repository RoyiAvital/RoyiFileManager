"""Retest released application sources with one current performance harness."""

import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

from fman_performancetest import fixtures, suite
from fman_performancetest.records import CATALOG, ROOT, digest, load_catalog, new_record, save_record


VERSIONS = ('0.9.0', '0.9.1', '0.9.2', '0.9.3', '0.10.0', '0.10.1', '0.10.2', 'Unreleased')
SOURCE_PATHS = ('src/main', 'src/build', 'environment.yml', 'conda-lock.yml')


def revision(label):
	reference = 'HEAD' if label == 'Unreleased' else 'v' + label
	return subprocess.check_output(['git', 'rev-parse', '--verify', reference + '^{commit}'],
		cwd=ROOT, text=True).strip()


def export_source(destination, commit):
	archive = subprocess.check_output(['git', 'archive', commit, *SOURCE_PATHS], cwd=ROOT)
	destination.mkdir(parents=True, exist_ok=False)
	with tarfile.open(fileobj=io.BytesIO(archive)) as source:
		source.extractall(destination, filter='data')
	return source_digest(destination)


def source_digest(directory):
	return digest([(path.relative_to(directory).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
		for path in sorted(directory.rglob('*')) if path.is_file() and '__pycache__' not in path.parts])


def child_environment(source):
	paths = [ROOT / 'src/performancetest/python', source / 'src/main/python']
	paths.extend(sorted((source / 'src/main/resources/base/Plugins').iterdir()))
	environment = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, paths)),
		PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONHASHSEED='0', TZ='UTC',
		QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1', QT_AUTO_SCREEN_SCALE_FACTOR='0',
		QT_ENABLE_HIGHDPI_SCALING='0', QT_FONT_DPI='96')
	native = Path(sys.prefix) / 'Library/bin'
	if native.is_dir():
		environment['PATH'] = os.pathsep.join((str(native), environment.get('PATH', '')))
	environment['QT_QPA_FONTDIR'] = str(Path(environment.get('WINDIR', r'C:\Windows')) / 'Fonts')
	return environment


def version_order(iteration):
	return VERSIONS if iteration % 2 == 0 else tuple(reversed(VERSIONS))


def has_text_preview(label):
	return label == 'Unreleased' or tuple(map(int, label.split('.'))) >= (0, 10, 0)


def write_json(path, value):
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open('x', encoding='utf-8') as output:
		json.dump(value, output, indent=2, allow_nan=False)
		output.write('\n')


def invoke(source, label, test, directory, catalog_path, algorithm=False):
	command = [sys.executable, '-m', 'fman_performancetest.historical',
		'--child', test['id'], '--source', str(source), '--label', label,
		'--directory', str(directory), '--catalog', str(catalog_path)]
	if algorithm:
		command.append('--algorithm')
	timeout = load_catalog(catalog_path)['protocol']['selection_timeout_seconds'] if test['workload'] == 'selection' else 300
	result = subprocess.run(command, cwd=source, env=child_environment(source),
		capture_output=True, text=True, encoding='utf-8', timeout=timeout)
	if result.returncode:
		raise RuntimeError('Child exit %s\n%s\n%s' % (result.returncode, result.stdout, result.stderr))
	for line in result.stdout.splitlines():
		for prefix in ('SUITE_RESULT ', 'SEARCH_UI_RESULT ', 'PANE_RESULT ', 'QUICKVIEW_RESULT '):
			if line.startswith(prefix):
				return json.loads(line[len(prefix):])
	raise RuntimeError('Child returned no structured result')


def sample(source, label, test, directory, catalog_path):
	ui = invoke(source, label, test, directory, catalog_path)
	if ui['errors'] or not ui['settings_isolated']:
		raise ValueError('Application errors or settings isolation failure')
	result = dict(ui=ui)
	if test['workload'] == 'selection':
		from fman_performancetest.selection import selection_cases
		expected = [case['action_id'] for case in selection_cases(test['selection_count'])]
		if [case['action_id'] for case in ui['samples']] != expected or any(case['status'] != 'passed' for case in ui['samples']):
			raise ValueError('Selection correctness failure')
	if test['workload'] in ('filter', 'fuzzy', 'recursive'):
		result['algorithm'] = invoke(source, label, test, directory, catalog_path, algorithm=True)
		if result['algorithm']['truncated']:
			raise ValueError('Catalog workload was truncated')
		counts = {query['query_id']: query['returned'] for query in result['algorithm']['queries']}
		if any(query['rows'] != counts[query['query_id']] for query in ui['samples']):
			raise ValueError('UI and algorithm result counts differ')
	return result


def prepare(output, selected, catalog_path, repetitions):
	catalog = load_catalog(catalog_path)
	harness = suite.source_hash('src/performancetest')
	manifest_path = output / 'manifest.json'
	if manifest_path.exists():
		manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
		if manifest['harness']['source_sha256'] != harness or manifest['catalog_sha256'] != digest(catalog) or \
			manifest['repetitions'] != repetitions or manifest['tests'] != [test['id'] for test in selected]:
			raise ValueError('Cannot resume with different harness, catalog, tests or repetitions')
		if manifest['environment']['configuration_sha256'] != suite.environment(output)['configuration_sha256']:
			raise ValueError('Cannot resume in a different environment')
		for label, application in manifest['applications'].items():
			if source_digest(output / 'sources' / label) != application['source_sha256']:
				raise ValueError('Exported source changed: ' + label)
		image_assets = fixtures.assets()
		for identity, saved in manifest['fixtures'].items():
			verified = fixtures.prepare(output / 'fixtures', identity, catalog['fixtures'][identity], image_assets)
			if saved['sha256'] != verified['sha256']:
				raise ValueError('Fixture changed: ' + identity)
		return manifest
	if subprocess.check_output(['git', 'status', '--porcelain', '--', *SOURCE_PATHS], cwd=ROOT):
		raise ValueError('Commit application changes before exporting the current HEAD; benchmark-only edits are allowed')
	output.mkdir(parents=True, exist_ok=True)
	applications = {}
	for label in VERSIONS:
		commit = revision(label)
		source = output / 'sources' / label
		fingerprint = export_source(source, commit)
		settings = json.loads((source / 'src/build/settings/base.json').read_text(encoding='utf-8'))
		applications[label] = dict(version=settings['version'], version_id=label, commit=commit,
			dirty=False, source_sha256=fingerprint)
		print('Exported %s: %s' % (label, commit), flush=True)
	prepared = {}
	image_assets = fixtures.assets()
	for test in selected:
		identity = test['fixture']
		if identity not in prepared:
			prepared[identity] = fixtures.prepare(output / 'fixtures', identity, catalog['fixtures'][identity], image_assets)
			print('Verified fixture: ' + identity, flush=True)
	shutil.copyfile(catalog_path, output / 'catalog.yaml')
	manifest = dict(started_at=datetime.now(timezone.utc).isoformat(), applications=applications,
		harness=dict(commit=revision('Unreleased'), source_sha256=harness),
		environment=suite.environment(output), catalog_sha256=digest(catalog),
		fixtures=prepared, tests=[test['id'] for test in selected], repetitions=repetitions)
	write_json(manifest_path, manifest)
	return manifest


def measure(output, selected, catalog_path, repetitions):
	manifest = prepare(output, selected, catalog_path, repetitions)
	if (output / 'index.json').exists():
		paths = json.loads((output / 'index.json').read_text(encoding='utf-8'))
		return 0 if all(json.loads(Path(path).read_text(encoding='utf-8'))['status'] == 'passed' for path in paths.values()) else 1
	catalog_path = output / 'catalog.yaml'
	catalog = load_catalog(catalog_path)
	started = time.perf_counter()
	for test in selected:
		for iteration in range(repetitions):
			for label in version_order(iteration):
				path = output / 'samples' / label / ('%s-%d.json' % (test['id'], iteration + 1))
				if path.exists():
					continue
				print('%s %s repetition %d/%d' % (label, test['id'], iteration + 1, repetitions), flush=True)
				try:
					value = sample(output / 'sources' / label, label, test,
						Path(manifest['fixtures'][test['fixture']]['directory']), catalog_path)
					value.update(status='passed', iteration=iteration + 1)
				except Exception as error:
					value = dict(status='failed', iteration=iteration + 1, error=str(error))
					print(value['error'], flush=True)
				write_json(path, value)
				print('  %s (batch %.1fs)' % (value['status'], time.perf_counter() - started), flush=True)
	if suite.source_hash('src/performancetest') != manifest['harness']['source_sha256']:
		raise ValueError('Harness changed during measurement')
	paths = {}
	for label in VERSIONS:
		if source_digest(output / 'sources' / label) != manifest['applications'][label]['source_sha256']:
			raise ValueError('Application changed during measurement: ' + label)
		record = new_record(catalog, manifest['applications'][label], manifest['environment'])
		record.update(started_at=manifest['started_at'], finished_at=datetime.now(timezone.utc).isoformat(),
			suite_mode='regular', harness=manifest['harness'], parameters=dict(catalog['protocol'], repetitions=repetitions),
			notes='Same-harness historical retest; alternating version order; original released application sources. '
			'Text preview cases omitted before 0.10.0; image and navigation cases unchanged.')
		for test in selected:
			values = [json.loads((output / 'samples' / label / ('%s-%d.json' % (test['id'], iteration + 1)))
				.read_text(encoding='utf-8')) for iteration in range(repetitions)]
			definition = dict(test=test, queries=catalog['queries'].get(test['workload']), protocol=record['parameters'])
			if test['workload'] == 'quickview':
				definition['include_text'] = has_text_preview(label)
			failures = [value for value in values if value['status'] != 'passed']
			record['results'].append(dict(test_id=test['id'], test_revision=test['revision'], fixture_id=test['fixture'],
				fixture_sha256=manifest['fixtures'][test['fixture']]['sha256'], definition_sha256=digest(definition),
				status='failed' if failures else 'passed', failures=failures,
				samples=[value for value in values if value['status'] == 'passed']))
		record['status'] = 'passed' if all(result['status'] == 'passed' for result in record['results']) else 'failed'
		paths[label] = str(save_record(output / 'runs', record))
		print('%s: %s %s' % (label, record['status'], paths[label]), flush=True)
	write_json(output / 'index.json', paths)
	return 0 if all(json.loads(Path(path).read_text(encoding='utf-8'))['status'] == 'passed' for path in paths.values()) else 1


def main(argv=None):
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--list', action='store_true')
	parser.add_argument('--output', type=Path)
	parser.add_argument('--catalog', type=Path, default=CATALOG)
	parser.add_argument('--test', action='append', default=[])
	parser.add_argument('--repeat', type=int, default=3)
	parser.add_argument('--child')
	parser.add_argument('--source', type=Path)
	parser.add_argument('--label', choices=VERSIONS)
	parser.add_argument('--directory', type=Path)
	parser.add_argument('--algorithm', action='store_true')
	args = parser.parse_args(argv)
	if args.list:
		for label in VERSIONS:
			print(label, revision(label), flush=True)
		return 0
	catalog = load_catalog(args.catalog)
	if args.child:
		import importlib.util
		for name in ('fman', 'core'):
			if not Path(importlib.util.find_spec(name).origin).is_relative_to(args.source):
				raise ValueError('Application import escaped historical source: ' + name)
		test = next(test for test in catalog['tests'] if test['id'] == args.child)
		if test['workload'] == 'quickview':
			from fman_performancetest.quickview import child
			return child(args.directory, catalog['protocol']['viewport'], catalog['protocol']['navigation_repetitions'],
				include_text=has_text_preview(args.label))
		return suite.child(test, catalog, args.directory, args.algorithm, None)
	if args.output is None or args.repeat < 1:
		parser.error('--output and a positive --repeat are required')
	selected = [test for test in catalog['tests'] if not args.test or
		any(fnmatch.fnmatchcase(test['id'], pattern) for pattern in args.test)]
	if not selected:
		parser.error('No matching regular workloads')
	return measure(args.output.resolve(), selected, args.catalog.resolve(), args.repeat)


if __name__ == '__main__':
	sys.exit(main())