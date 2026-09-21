"""Seeded on-disk Filter/Find workloads; run only through performancetest/run.py."""

import argparse
import cProfile
import json
import os
from pathlib import Path
import platform
import pstats
import statistics
import subprocess
import sys
from time import perf_counter, process_time

from fman_performancetest.search_fixture import (
	FILTER_QUERIES, FUZZY_QUERIES, RECURSIVE_QUERIES, prepare,
)


ROOT = Path(__file__).resolve().parents[4]


def distribution(values):
	ordered = sorted(values)
	if not ordered:
		return {'count': 0}
	return dict(count=len(ordered), median=statistics.median(ordered),
		p95=ordered[min(len(ordered) - 1, int(len(ordered) * .95))], max=ordered[-1])


def memory():
	if sys.platform != 'win32':
		return {}
	import win32api
	import win32process
	values = win32process.GetProcessMemoryInfo(win32api.GetCurrentProcess())
	return dict(working_set_mib=values['WorkingSetSize'] / 1048576,
		peak_working_set_mib=values['PeakWorkingSetSize'] / 1048576)


def algorithms(directory, mode, repeat, max_entries, profile_directory=None, query_texts=None):
	from core.fs.local import LocalFileSystem
	from fman.impl.filter_pattern import compile_filter
	from fman.url import as_url, splitscheme
	from search_file_fuzzy.indexer import build_index
	from search_file_fuzzy.matcher import Matcher
	url = as_url(directory)
	report = dict(mode=mode, cache='warm after fixture creation; no OS cache flush', repeat=repeat)
	started = perf_counter()
	if mode == 'filter':
		listing = LocalFileSystem().scan(splitscheme(url)[1], lambda: None)
		report['candidates'] = len(listing.names)
		report['truncated'] = False
		def evaluate(query):
			matcher = compile_filter(query)
			return sum(matcher.matches(name) for name in listing.display_names)
		queries = FILTER_QUERIES
	else:
		index = build_index(url, recursive=mode == 'recursive', max_entries=max_entries,
			include_hidden=True, collect_metadata=False)
		report['index_ms'] = (perf_counter() - started) * 1000
		report['candidates'], report['truncated'] = len(index.entries), index.truncated
		started = perf_counter()
		matcher = Matcher(index.entries, max_results=100)
		report['matcher_construction_ms'] = (perf_counter() - started) * 1000
		def evaluate(query):
			return len(matcher.matches(query))
		queries = RECURSIVE_QUERIES if mode == 'recursive' else FUZZY_QUERIES
	if mode == 'filter':
		report['scan_ms'] = (perf_counter() - started) * 1000
	report['queries'] = []
	if query_texts is not None:
		queries = query_texts
	for query in queries:
		evaluate(query)
		wall, cpu, counts = [], [], []
		for sample in range(repeat):
			started, cpu_started = perf_counter(), process_time()
			counts.append(evaluate(query))
			cpu.append((process_time() - cpu_started) * 1000)
			wall.append((perf_counter() - started) * 1000)
		if len(set(counts)) != 1:
			raise RuntimeError('Unstable results for ' + repr(query))
		report['queries'].append(dict(query=query, returned=counts[0], wall_ms=distribution(wall), cpu_ms=distribution(cpu),
			samples=[dict(wall_ms=wall_sample, cpu_ms=cpu_sample) for wall_sample, cpu_sample in zip(wall, cpu)]))
	report.update(memory())
	if profile_directory is not None:
		profile_directory.mkdir(parents=True, exist_ok=True)
		profile = cProfile.Profile()
		for query in queries:
			profile.runcall(evaluate, query)
		profile.dump_stats(str(profile_directory / (mode + '.prof')))
		with (profile_directory / (mode + '.txt')).open('w', encoding='utf-8') as output:
			pstats.Stats(profile, stream=output).strip_dirs().sort_stats('cumulative').print_stats(40)
		report['profile'] = mode + '.prof'
	return report


def main(argv=None):
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--dataset', type=Path, default=ROOT / 'target/performance/filter-find/corpus')
	parser.add_argument('--output', type=Path, default=ROOT / 'target/performance/filter-find/results.json')
	parser.add_argument('--flat-files', type=int, default=50_000)
	parser.add_argument('--recursive-files', type=int, default=50_000)
	parser.add_argument('--seed', type=int, default=1729)
	parser.add_argument('--repeat', type=int, default=5)
	parser.add_argument('--max-entries', type=int, default=1_000_000_000,
		help='Inspected-entry cap; default covers the entire fixture')
	parser.add_argument('--prepare-only', action='store_true')
	parser.add_argument('--profile', action='store_true', help='Separate, untimed cProfile pass per workload')
	parser.add_argument('--ui', action='store_true', help='Also measure native application input and paint responsiveness')
	parser.add_argument('--child', choices=('filter', 'fuzzy', 'recursive'), help=argparse.SUPPRESS)
	args = parser.parse_args(argv)
	args.dataset = args.dataset.resolve()
	args.output = args.output.resolve()
	if min(args.flat_files, args.recursive_files, args.repeat, args.max_entries) < 1:
		parser.error('Counts, repeats and entry cap must be positive')
	if args.child:
		directory = args.dataset / ('recursive' if args.child == 'recursive' else 'flat')
		report = algorithms(directory, args.child, args.repeat, args.max_entries,
			args.output.parent / 'profiles' if args.profile else None)
		print('SEARCH_RESULT ' + json.dumps(report), flush=True)
		return 0
	configuration = prepare(args.dataset, args.flat_files, args.recursive_files, args.seed)
	print('Fixture: %s; flat=%d recursive=%d seed=%d' % (
		args.dataset, args.flat_files, args.recursive_files, args.seed), flush=True)
	if args.prepare_only:
		return 0
	report = dict(fixture=configuration, python=sys.version, platform=platform.platform(),
		max_entries=args.max_entries, results=[])
	for mode in ('filter', 'fuzzy', 'recursive'):
		command = [sys.executable, '-m', 'fman_performancetest.filter_find',
			'--child', mode, '--dataset', str(args.dataset), '--output', str(args.output),
			'--repeat', str(args.repeat), '--max-entries', str(args.max_entries)]
		if args.profile:
			command.append('--profile')
		child = subprocess.run(command, capture_output=True, text=True, timeout=300)
		if child.returncode:
			print(child.stdout + child.stderr, file=sys.stderr)
			return child.returncode
		line = next(line for line in child.stdout.splitlines() if line.startswith('SEARCH_RESULT '))
		result = json.loads(line[len('SEARCH_RESULT '):])
		report['results'].append(result)
		print('%s: %d candidates; slowest query median %.1f ms' % (mode, result['candidates'],
			max(query['wall_ms']['median'] for query in result['queries'])), flush=True)
	if args.ui:
		from fman_performancetest.search_ui import run_children
		report['ui'] = run_children(args.dataset, args.repeat, args.max_entries, args.output.parent)
	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
	print('Report: ' + str(args.output), flush=True)
	return 0


if __name__ == '__main__':
	sys.exit(main())