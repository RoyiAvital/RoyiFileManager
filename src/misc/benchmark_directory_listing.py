"""Compare directory enumeration plus pane metadata, without changing the app."""

import argparse
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from stat import S_ISDIR


def _pane_metadata(info):
    is_directory = S_ISDIR(info.st_mode)
    return is_directory, None if is_directory else info.st_size, info.st_mtime_ns


def listdir_metadata(directory):
    rows = {}
    errors = {}
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            try:
                info = os.stat(path)
            except FileNotFoundError:
                info = os.stat(path, follow_symlinks=False)
        except OSError as error:
            errors[name] = (error.errno, getattr(error, 'winerror', None))
        else:
            rows[name] = _pane_metadata(info)
    return rows, errors


def scandir_metadata(directory):
    rows = {}
    errors = {}
    with os.scandir(directory) as entries:
        for entry in entries:
            try:
                try:
                    info = entry.stat()
                except FileNotFoundError:
                    info = entry.stat(follow_symlinks=False)
            except OSError as error:
                errors[entry.name] = (error.errno, getattr(error, 'winerror', None))
            else:
                rows[entry.name] = _pane_metadata(info)
    return rows, errors


def _positive_int(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return result


def _nonnegative_int(value):
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError('must be at least 0')
    return result


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description='Compare listdir + stat with scandir pane metadata (read-only, one level).',
        epilog='Use a quiet folder. OS caches are not flushed; these are not controlled cold-cache timings.'
    )
    parser.add_argument(
        'directories', nargs='*', type=Path, default=[Path('.')],
        help='folders to benchmark, non-recursively (default: current folder)'
    )
    parser.add_argument(
        '--repeat', type=_positive_int, default=20,
        help='measured runs per method (default: 20)'
    )
    parser.add_argument(
        '--warmup', type=_nonnegative_int, default=2,
        help='unmeasured runs per method (default: 2)'
    )
    parser.add_argument(
        '--first', choices=('listdir', 'scandir'), default='listdir',
        help='method to run first; order alternates each pair (default: listdir)'
    )
    return parser.parse_args(argv)


def benchmark(directory, repeat, warmup, first):
    methods = [('listdir + stat', listdir_metadata), ('scandir', scandir_metadata)]
    if first == 'scandir':
        methods.reverse()
    samples = {name: [] for name, _ in methods}
    first_times = {}
    reference = None
    mismatches = 0
    max_errors = 0
    error_examples = {}
    for run_number in range(warmup + repeat):
        ordered = methods if run_number % 2 == 0 else methods[::-1]
        for name, function in ordered:
            started = time.perf_counter_ns()
            result = function(directory)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            if run_number == 0:
                first_times[name] = elapsed_ms
            if run_number >= warmup:
                samples[name].append(elapsed_ms)
            if reference is None:
                reference = result
            elif result != reference:
                mismatches += 1
            errors = result[1]
            max_errors = max(max_errors, len(errors))
            for filename, error in errors.items():
                if len(error_examples) >= 5:
                    break
                error_examples[filename] = error

    rows = reference[0]
    directory_count = sum(metadata[0] for metadata in rows.values())
    print(f'  Entries: {len(rows):,} successful ({directory_count:,} directories)')
    print(f'  Runs per method: {warmup} warmup, {repeat} measured; alternating order')
    print(f'  First observed, not necessarily cold ({first} first):')
    for name, _ in methods:
        print(f'    {name:16} {first_times[name]:10.3f} ms')
    print(f'  {"Method":16} {"Median ms":>10} {"Min ms":>10} {"Max ms":>10}')
    medians = {}
    for name, _ in methods:
        values = samples[name]
        medians[name] = statistics.median(values)
        print(f'  {name:16} {medians[name]:10.3f} {min(values):10.3f} {max(values):10.3f}')
    if mismatches or max_errors:
        print(f'  INVALID comparison: {mismatches} differing results; up to {max_errors} metadata errors per run.')
        for filename, error in error_examples.items():
            print(f'    {filename!r}: errno={error[0]}, winerror={error[1]}')
        print('  Folder changes, metadata differences or errors require investigation; speedup withheld.')
        return False
    print('  Metadata agreement: PASS across both methods and all runs')
    baseline = medians['listdir + stat']
    candidate = medians['scandir']
    print(f'  Median time saved by scandir: {baseline - candidate:.3f} ms')
    if candidate > 0:
        print(f'  listdir/scandir time ratio: {baseline / candidate:.2f}x (>1 favors scandir)')
    return True


def main(argv=None):
    args = _parse_args(argv)
    print(f'Python: {platform.python_version()} ({sys.executable})')
    print(f'Platform: {platform.platform()}')
    print('Work: names, directory flag, file size and modification time; one stat result per entry.')
    print('Symlinks: follow targets, falling back to link metadata on FileNotFoundError, like LocalFileSystem.')
    print('Fresh enumeration each run; no application cache. OS caches are NOT flushed.')
    print('Excludes icons, sorting, date formatting, Qt, plug-ins and full file identity.')
    valid = True
    for directory in args.directories:
        directory = directory.absolute()
        print(f'\nFolder: {directory}', flush=True)
        try:
            if not benchmark(directory, args.repeat, args.warmup, args.first):
                valid = False
        except OSError as error:
            print(f'  Cannot benchmark: {error}', file=sys.stderr)
            valid = False
    return 0 if valid else 1


if __name__ == '__main__':
    raise SystemExit(main())