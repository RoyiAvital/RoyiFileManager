"""Compare real pane performance on explicitly prepared synthetic fixtures."""

import argparse
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def default_directories():
	return [ROOT / 'target/performance/fixtures' / identity / 'data'
		for identity in ('flat-small-v1', 'flat-large-v1')]


def benchmark_environment():
	if str(ROOT) not in sys.path:
		sys.path.insert(0, str(ROOT))
	import build
	environment = build._environment()
	environment['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'src/performancetest/python'), environment['PYTHONPATH']))
	environment['QT_QPA_PLATFORM'] = 'windows'
	environment['QT_QPA_FONTDIR'] = str(Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts')
	return environment


def summarize(results, labels, baseline, repeat, show_hidden):
	current = 'snapshot' if baseline == 'current' else 'after'
	expected = {(label, mode, iteration) for label in labels
		for mode in (baseline, current) for iteration in range(1, repeat + 1)}
	seen = set()
	for result in results:
		key = result['label'], result['mode'], result['iteration']
		if key not in expected or key in seen:
			raise ValueError('Unexpected or duplicate sample: %r' % (key,))
		seen.add(key)
		if result['errors'] or not result['settings_isolated']:
			raise ValueError('Application errors or settings isolation failure: %r' % (key,))
		if result['show_hidden'] != show_hidden or show_hidden and result['hidden_queries']:
			raise ValueError('Hidden-filter configuration mismatch: %r' % (key,))
	if seen != expected:
		raise ValueError('Incomplete benchmark results')
	lines = [
		'Medians in milliseconds; warm OS caches; baseline: %s.' % baseline,
		'Loading paint p95 is the median of per-run p95 values, not a pooled p95.',
		'| Folder | Entries | First paint (baseline -> current) | Complete (baseline -> current) | Loading paint p95 (baseline -> current) |',
		'| --- | ---: | ---: | ---: | ---: |',
	]
	for label in labels:
		group = [result for result in results if result['label'] == label]
		fingerprints = {(result['entries'], result['rows'], result['fingerprint']) for result in group}
		if len(fingerprints) != 1:
			raise ValueError('Row/metadata parity failed for %s; timings are not comparable' % label)
		values = []
		for metric in ('first_paint_ms', 'complete_ms', 'loading_paints_ms'):
			pair = []
			for mode in (baseline, current):
				samples = [result[metric] for result in group if result['mode'] == mode]
				if metric == 'loading_paints_ms':
					samples = [sample['p95'] for sample in samples if sample['count']]
				pair.append('%.1f' % median(samples) if samples else 'n/a')
			values.append(' -> '.join(pair))
		lines.append('| %s | %d | %s |' % (label, group[0]['entries'], ' | '.join(values)))
	return '\n'.join(lines)


def main(argv=None):
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('directories', nargs='*', type=Path,
		help='Override the two prepared synthetic folders')
	parser.add_argument('--repeat', type=int, default=3, help='Alternating pairs per folder')
	parser.add_argument('--baseline', choices=('before', 'reviewed', 'current'), default='current',
		help='current: committed pre-snapshot application; before/reviewed: historical hidden-cache comparisons')
	parser.add_argument('--baseline-ref', help='Override the pinned historical application commit')
	parser.add_argument('--show-hidden', action='store_true', help='Measure with hidden filtering off')
	parser.add_argument('--output', type=Path,
		default=ROOT / 'target/diagnostics/pane-rendering-three-folders.json')
	args = parser.parse_args(argv)
	if args.repeat < 1:
		parser.error('--repeat must be positive')
	if sys.platform != 'win32':
		parser.error('This application benchmark requires Windows')
	directories = args.directories or default_directories()
	for directory in directories:
		if not directory.is_dir():
			parser.error('Folder does not exist: %s. Supply folder arguments to override defaults.' % directory)
	directories = [directory.resolve() for directory in directories]
	labels = [directory.parent.name if directory.name == 'data' else directory.name or 'DriveRoot' for directory in directories]
	if len(set(labels)) != len(labels):
		parser.error('Folders must have distinct names for benchmark grouping')
	output = args.output.resolve()
	command = [sys.executable, '-m', 'fman_performancetest.pane_rendering_benchmark',
		*map(str, directories), '--baseline', args.baseline, '--repeat', str(args.repeat),
		'--output', str(output)]
	if args.baseline_ref:
		command.extend(('--baseline-ref', args.baseline_ref))
	if args.show_hidden:
		command.append('--show-hidden')
	print('Measuring %d folders, %d pairs each. Raw results: %s' % (
		len(directories), args.repeat, output), flush=True)
	try:
		run = subprocess.run(command, cwd=ROOT, env=benchmark_environment(),
			capture_output=True, text=True, timeout=180 * 2 * args.repeat * len(directories) + 30)
		if run.returncode:
			print(run.stdout + run.stderr, file=sys.stderr)
			return run.returncode
		results = json.loads(output.read_text(encoding='utf-8'))
		print(summarize(results, labels, args.baseline, args.repeat, args.show_hidden))
		print('Row/metadata parity and settings isolation: PASS. Raw results: %s' % output)
	except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
		print('Benchmark failed: %s. Inspect raw results: %s' % (error, output), file=sys.stderr)
		return 1
	return 0


if __name__ == '__main__':
	sys.exit(main())