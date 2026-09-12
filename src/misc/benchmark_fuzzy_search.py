import argparse
import heapq
import os
import re
import statistics
import time
from pathlib import Path

import jellyfish
from rapidfuzz import fuzz, process


DEFAULT_QUERIES = (
    'explorer exe',
    'window def',
    'power shell',
    'system config',
    'python dll',
    'security health',
)
_CAMEL_CASE_BOUNDARY = re.compile(r'(?<=[a-z0-9])(?=[A-Z])')
_SEPARATORS = re.compile(r'[^0-9a-z]+')


def _parse_args():
    parser = argparse.ArgumentParser(
        description='Compare fuzzy-search implementations on real file paths.'
    )
    parser.add_argument(
        '--max-files', type=int, default=75_000,
        help='maximum number of files to collect (default: 75000)'
    )
    parser.add_argument(
        '--limit', type=int, default=5,
        help='number of top matches to display (default: 5)'
    )
    parser.add_argument(
        '--repeat', type=int, default=4,
        help='timed runs per query after warmup (default: 4)'
    )
    parser.add_argument(
        '--query', action='append', dest='queries',
        help='query to benchmark; may be supplied more than once'
    )
    parser.add_argument(
        'roots', nargs='*', type=Path,
        help='folders to scan; defaults to Windows and Program Files'
    )
    return parser.parse_args()


def _default_roots():
    roots = [Path(os.environ['WINDIR']), Path(os.environ['ProgramFiles'])]
    program_files_x86 = os.environ.get('ProgramFiles(x86)')
    if program_files_x86:
        roots.append(Path(program_files_x86))
    return roots


def _collect_paths(roots, max_files):
    paths = []
    for root in roots:
        for directory, _, filenames in os.walk(root):
            for filename in filenames:
                paths.append(str(Path(directory, filename)))
                if len(paths) >= max_files:
                    return paths
    return paths


def _normalize(value):
    value = _CAMEL_CASE_BOUNDARY.sub(' ', value)
    return _SEPARATORS.sub(' ', value.casefold()).strip()


def _python_score(query, candidate):
    total = 0
    for token in query.split():
        positions = []
        cursor = 0
        for character in token:
            cursor = candidate.find(character, cursor)
            if cursor < 0:
                return None
            positions.append(cursor)
            cursor += 1
        span = positions[-1] - positions[0] + 1
        boundaries = sum(
            position == 0 or candidate[position - 1] == ' '
            for position in positions
        )
        total += boundaries * 30 - span * 3 - positions[0]
    return total - len(candidate) * 0.01


def _top_scored(paths, scores, limit):
    matches = heapq.nlargest(
        limit,
        ((score, index) for index, score in enumerate(scores) if score is not None)
    )
    return [(paths[index], score) for score, index in matches]


def _benchmark(function, query, repeat):
    function(query)
    samples = []
    result = None
    for _ in range(repeat):
        started = time.perf_counter()
        result = function(query)
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples), result


def main():
    args = _parse_args()
    roots = args.roots or _default_roots()
    queries = args.queries or DEFAULT_QUERIES

    started = time.perf_counter()
    paths = _collect_paths(roots, args.max_files)
    scan_seconds = time.perf_counter() - started
    normalized_paths = [_normalize(path) for path in paths]

    def regular(query):
        normalized_query = _normalize(query)
        return [
            (path, 1.0)
            for path, candidate in zip(paths, normalized_paths)
            if normalized_query in candidate
        ][:args.limit]

    def python_fuzzy(query):
        normalized_query = _normalize(query)
        return _top_scored(
            paths,
            (_python_score(normalized_query, path) for path in normalized_paths),
            args.limit,
        )

    def rapidfuzz_qratio(query):
        matches = process.extract(
            _normalize(query),
            normalized_paths,
            scorer=fuzz.QRatio,
            processor=None,
            limit=args.limit,
        )
        return [(paths[index], score) for _, score, index in matches]

    def jellyfish_jaro_winkler(query):
        normalized_query = _normalize(query)
        return _top_scored(
            paths,
            (
                jellyfish.jaro_winkler_similarity(normalized_query, path)
                for path in normalized_paths
            ),
            args.limit,
        )

    methods = (
        ('regular baseline', regular),
        ('python subsequence', python_fuzzy),
        ('rapidfuzz QRatio', rapidfuzz_qratio),
        ('jellyfish Jaro-Winkler', jellyfish_jaro_winkler),
    )

    print(f'Corpus: {len(paths):,} files from {len(roots)} root(s)')
    print(f'Scan: {scan_seconds:.3f} s')
    for query in queries:
        print(f'\nQuery: {query!r}')
        for name, function in methods:
            elapsed_ms, matches = _benchmark(function, query, args.repeat)
            print(f'  {name:24} {elapsed_ms:8.2f} ms')
            for path, score in matches:
                print(f'    {score:8.2f}  {path}')


if __name__ == '__main__':
    main()