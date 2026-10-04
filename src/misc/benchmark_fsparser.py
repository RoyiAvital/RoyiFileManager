"""Gauge for the native directory-record parser (Done/FSParser.md).

Runs, outside the application and on identical captured buffers:

* ``python_scan``  -- the reference: the previous pure-Python scan body
  (``records()`` per batch, link follow-up, validated ``Listing``).
* ``native_scan``  -- the application's ``scan()`` from
  core/fs/local/windows/listing.py (``_fsparser.Columns`` per batch, link
  follow-up through ``entry()``/``patch()``, ``finish(frozen=True)``,
  ``Listing._trusted``).

The three parser shapes of the module are also timed on their own, without
link follow-up: ``parse_records`` (whole), ``parse_batch`` (batch) and
``Columns`` (columns, lists; columns-frozen, tuples). Run this and
``validate_fsparser.py`` after every change to ``fsparser.c``.

    python src/misc/benchmark_fsparser.py <folder> [--repeat 7] [--warmup 1]
                                          [--native path/to/_fsparser.pyd]
                                          [--json out.json]
    python src/misc/benchmark_fsparser.py --synthetic 1000000 ...

Exit code 0: parity holds (or the native module is absent and only the Python
baseline was measured). Exit code 1: parity mismatch. Exit code 2: bad input.
Read-only; standard library plus the repository's own listing module.
"""

import argparse
import importlib.machinery
import importlib.util
import json
import os
import platform
import random
import statistics
import sys
import time
from pathlib import Path
from stat import S_ISDIR, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src' / 'main' / 'python'),
    str(ROOT / 'src' / 'main' / 'resources' / 'base' / 'Plugins' / 'Core')]

from core.fs.local.windows import listing as scanner  # noqa: E402
from fman.listing import Listing  # noqa: E402

BATCH_SIZE = 65536
SYNTHETIC_SCOPE = (0, bytes(16))


def enumerate_batches(folder):
    started = time.perf_counter_ns()
    with scanner.NativeDirectory(folder) as directory:
        scope = directory.scope()
        if scope is None:
            raise SystemExit('Folder is not on an NTFS/ReFS volume with file IDs: %s' % folder)
        batches = list(directory.batches(lambda: None))
    return batches, scope, time.perf_counter_ns() - started


def synthetic_batches(entries, seed=1):
    """64 KiB batches of plausible records: 8-24 char names, mixed sizes, 5 % folders."""
    generator = random.Random(seed)
    now = scanner._EPOCH + int(time.time()) * 10**7
    batches = []
    current = []
    used = 0

    def flush():
        last = current[-1]
        current[-1] = (0).to_bytes(4, 'little') + last[4:]
        batches.append(b''.join(current) + b'\0' * (BATCH_SIZE - used))

    for remaining in range(entries, 0, -1):
        length = generator.randint(8, 24)
        name = ('%0*d' % (length - 4, remaining) + '.jpg').encode('utf-16-le')
        is_dir = generator.random() < 0.05
        attributes = FILE_ATTRIBUTE_DIRECTORY if is_dir else 0x20
        size = 0 if is_dir else generator.randint(0, 5 * 2**20)
        modified = now - generator.randint(0, 3 * 365 * 86400) * 10**7
        record_length = scanner._RECORD.size + len(name)
        padded = (record_length + 7) // 8 * 8
        if used + padded > BATCH_SIZE:
            flush()
            current, used = [], 0
        header = scanner._RECORD.pack(padded, 0, modified - 10**9, 0, modified, 0, size, 0,
            attributes, len(name), 0, 0, generator.getrandbits(128).to_bytes(16, 'little'))
        current.append(header + name + b'\0' * (padded - record_length))
        used += padded
    if current:
        flush()
    return batches


class CapturedDirectory:
    """Stands in for NativeDirectory so the real scan() runs on captured batches."""

    def __init__(self, batches, scope):
        self._batches = batches
        self._scope = scope

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def scope(self):
        return self._scope

    def batches(self, check_canceled):
        for batch in self._batches:
            check_canceled()
            yield batch


def python_scan(location, path, batches, scope, check_canceled=lambda: None):
    """Reference: the previous pure-Python scan body (records() + validated Listing)."""
    names, directories, sizes, mtimes, attributes, created = ([] for _ in range(6))
    identities = bytearray()
    for batch in batches:
        check_canceled()
        for name, size, modified, own_attributes, tag, identity, birth in scanner.records(batch):
            is_dir = bool(own_attributes & FILE_ATTRIBUTE_DIRECTORY)
            if own_attributes & FILE_ATTRIBUTE_REPARSE_POINT and tag in scanner._LINK_TAGS:
                check_canceled()
                try:
                    metadata = os.stat(os.path.join(path, name))
                except OSError:
                    pass
                else:
                    is_dir, size, modified = S_ISDIR(metadata.st_mode), metadata.st_size, metadata.st_mtime_ns
            names.append(name)
            directories.append(is_dir)
            sizes.append(size)
            mtimes.append(modified)
            attributes.append(own_attributes)
            created.append(birth)
            identities.extend(identity)
    check_canceled()
    return Listing(location, names, directories, sizes, mtimes, attributes,
        created, bytes(identities), scope)


def native_scan(native, location, path, batches, scope, check_canceled=lambda: None):
    """The application's scan() (Columns + Listing._trusted) with the given module."""
    with patch.object(scanner, '_fsparser', native), \
            patch.object(scanner, 'NativeDirectory', lambda _: CapturedDirectory(batches, scope)):
        return scanner.scan(location, path, check_canceled)


def python_columns(batches):
    """Parser only, no link follow-up: records() plus per-record appends."""
    names, directories, sizes, mtimes, attributes, created, tags = ([] for _ in range(7))
    identities = bytearray()
    for batch in batches:
        for name, size, modified, own_attributes, tag, identity, birth in scanner.records(batch):
            names.append(name)
            directories.append(bool(own_attributes & FILE_ATTRIBUTE_DIRECTORY))
            sizes.append(size)
            mtimes.append(modified)
            attributes.append(own_attributes)
            created.append(birth)
            identities.extend(identity)
            tags.append(tag)
    return names, directories, sizes, mtimes, attributes, created, bytes(identities), tags


def native_columns(parse_batch, batches):
    """Reference shape: one parse_batch call per batch, appending into the scanner's lists."""
    names, directories, sizes, mtimes, attributes, created, tags = ([] for _ in range(7))
    identities = bytearray()
    for batch in batches:
        parse_batch(batch, names, directories, sizes, mtimes, attributes, created, identities, tags)
    return names, directories, sizes, mtimes, attributes, created, bytes(identities), tags


def accumulator_columns(columns_type, batches, frozen=False):
    """Reference shape: Columns without link follow-up."""
    columns = columns_type(scanner._LINK_TAGS)
    for batch in batches:
        columns.add(batch)
    return columns.finish(frozen=frozen)


def load_native(explicit_path):
    """Load _fsparser from `explicit_path`, else the module the scanner loaded; None when absent."""
    if explicit_path:
        path = Path(explicit_path)
        if not path.is_file():
            raise SystemExit('Native module not found: %s' % path)
        loader = importlib.machinery.ExtensionFileLoader('_fsparser', str(path))
        spec = importlib.util.spec_from_file_location('_fsparser', str(path), loader=loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    return scanner._fsparser


COLUMN_LABELS = ('names', 'is_dir', 'sizes', 'mtimes_ns', 'attributes', 'created_ns', 'identities', 'reparse_tags')


def compare_columns(expected, actual, labels=COLUMN_LABELS):
    """None when equal element by element including types; else a description."""
    if len(actual) != len(labels):
        return 'returned %d values, expected %d' % (len(actual), len(labels))
    for label, left_column, right_column in zip(labels, expected, actual):
        if label == 'identities':
            if type(right_column) is not bytes or left_column != right_column:
                return 'identities differ'
            continue
        if type(right_column) not in (list, tuple):
            return '%s: unexpected type %s' % (label, type(right_column).__name__)
        if len(left_column) != len(right_column):
            return '%s: %d entries vs %d' % (label, len(left_column), len(right_column))
        for index, (left, right) in enumerate(zip(left_column, right_column)):
            if left != right or type(left) is not type(right):
                return '%s[%d]: %r (%s) vs %r (%s)' % (
                    label, index, left, type(left).__name__, right, type(right).__name__)
    return None


def compare_listings(expected, actual):
    """Field-by-field equality of two Listing objects, the gate for the trusted construction."""
    if type(actual) is not Listing:
        return 'not a Listing'
    for field in ('location', 'scope', 'labels', 'extra'):
        if getattr(expected, field) != getattr(actual, field):
            return '%s differs' % field
    fields = ('names', 'is_dir', 'sizes', 'mtimes_ns', 'attributes', 'created_ns', 'identities')
    mismatch = compare_columns([getattr(expected, f) for f in fields], [getattr(actual, f) for f in fields], fields)
    if mismatch:
        return mismatch
    if any(type(getattr(actual, f)) is not tuple for f in fields[:-1]):
        return 'columns are not tuples'
    return None


def timed(function, *args):
    started = time.perf_counter_ns()
    result = function(*args)
    return result, time.perf_counter_ns() - started


def summarize(samples_ns):
    values = [sample / 1e6 for sample in samples_ns]
    return {
        'median_ms': statistics.median(values),
        'min_ms': min(values),
        'max_ms': max(values),
        'samples': len(values),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('folder', nargs='?', help='folder to enumerate; omit with --synthetic')
    parser.add_argument('--synthetic', type=int, metavar='ENTRIES',
        help='use generated in-memory batches with this many entries instead of a folder')
    parser.add_argument('--repeat', type=int, default=7, help='timed samples per method')
    parser.add_argument('--warmup', type=int, default=1, help='untimed passes per method')
    parser.add_argument('--native', help='path to _fsparser.pyd; default: import from the Core plug-in package')
    parser.add_argument('--json', help='write results to this file')
    args = parser.parse_args(argv)
    if args.repeat < 1 or args.warmup < 0:
        parser.exit(2, 'repeat must be >= 1 and warmup >= 0\n')
    if (args.folder is None) == (args.synthetic is None):
        parser.exit(2, 'Give either a folder or --synthetic ENTRIES\n')

    if args.synthetic is not None:
        if args.synthetic < 1:
            parser.exit(2, '--synthetic must be >= 1\n')
        folder = 'synthetic:%d' % args.synthetic
        path = 'C:\\synthetic'
        batches, scope, enumeration_ns = synthetic_batches(args.synthetic), SYNTHETIC_SCOPE, 0
    else:
        folder = path = os.path.abspath(args.folder)
        if not os.path.isdir(folder):
            parser.exit(2, 'Not a folder: %s\n' % folder)
        batches, scope, enumeration_ns = enumerate_batches(folder)
    location = 'file:///' + path.replace('\\', '/')
    native = load_native(args.native)

    # Scan models: the current and the planned scan() body, both ending in a Listing.
    scans = {'python_scan': lambda: python_scan(location, path, batches, scope)}
    if native is not None:
        scans['native_scan'] = lambda: native_scan(native, location, path, batches, scope)
    # Parser-only shapes: the parser's share and the three-way comparison.
    parsers = {'python': lambda: python_columns(batches)}
    if native is not None:
        parsers['whole'] = lambda: native.parse_records(batches)
        parsers['batch'] = lambda: native_columns(native.parse_batch, batches)
        parsers['columns'] = lambda: accumulator_columns(native.Columns, batches)
        parsers['columns-frozen'] = lambda: accumulator_columns(native.Columns, batches, frozen=True)
    methods = {**scans, **parsers}

    results = {}
    for name, function in methods.items():
        for _ in range(max(args.warmup, 1)):
            results[name] = function()
    entries = len(results['python'][0])

    mismatches = {}
    for name in parsers:
        if name != 'python':
            mismatches[name] = compare_columns(results['python'], results[name])
    if 'native_scan' in scans:
        mismatches['native_scan'] = compare_listings(results['python_scan'], results['native_scan'])
    mismatch = next((m for m in mismatches.values() if m), None)

    samples = {name: [] for name in methods}
    order = list(methods)
    for round_index in range(args.repeat):
        for name in (order if round_index % 2 == 0 else order[::-1]):
            _, elapsed = timed(methods[name])
            samples[name].append(elapsed)

    report = {
        'folder': folder,
        'entries': entries,
        'batches': len(batches),
        'bytes': sum(len(batch) for batch in batches),
        'platform': platform.platform(),
        'python': platform.python_version(),
        'enumeration_ms': enumeration_ns / 1e6,
        'scans': {name: summarize(samples[name]) for name in scans},
        'parsers': {name: summarize(samples[name]) for name in parsers},
        'parity': 'not tested (native module absent)' if not mismatches else
            {name: (m or 'identical') for name, m in mismatches.items()},
    }
    if native is not None:
        report['scan_speedup'] = report['scans']['python_scan']['median_ms'] / report['scans']['native_scan']['median_ms']
        report['parser_speedup'] = {name: report['parsers']['python']['median_ms'] / report['parsers'][name]['median_ms']
            for name in parsers if name != 'python'}

    def line(label, summary):
        print('%-28s %8.1f ms  [%.1f - %.1f], %d samples' % (
            label, summary['median_ms'], summary['min_ms'], summary['max_ms'], summary['samples']))

    print('Folder: %s' % folder)
    print('Entries: %d in %d batches (%.1f MiB); %s, Python %s' % (
        entries, len(batches), report['bytes'] / 2**20, report['platform'], report['python']))
    print('Kernel enumeration:          %8.1f ms' % report['enumeration_ms'])
    for name, summary in report['scans'].items():
        line('Scan after kernel (%s):' % name.split('_')[0], summary)
    for name, summary in report['parsers'].items():
        line('  parser only (%s):' % name, summary)
    if native is not None:
        print('Scan speedup (python/native):%8.2fx' % report['scan_speedup'])
    print('Parity: %s' % report['parity'])
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 1 if mismatch else 0


if __name__ == '__main__':
    sys.exit(main())
