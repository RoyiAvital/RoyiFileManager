"""Proof of concept for a columnar, snapshot-based pane architecture.

Standard library plus PyQt5 only. Nothing here touches the application. Run:

    python src/misc/pane_arch_poc.py <folder> --algorithms current --platform windows

The script scans a folder into plain columnar lists, sorts once, shows the rows
through a virtual Qt model, then measures query calls and completed paints.
Use --algorithms simple for the original experiment, --max-results 0 for all
fuzzy results, and --json <path> to retain measurements. These are synchronous
query calls, not real keyboard events. See Plan/FuturePaneArch.md for limitations.
"""

import argparse
import ctypes
import json
import os
import re
import stat
import sys
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter

_DIGITS = re.compile(r'(\d+)')
HIDDEN = getattr(stat, 'FILE_ATTRIBUTE_HIDDEN', 2)
REPARSE_POINT = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)


# --- Snapshot ---------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Listing:
    """Immutable columnar snapshot of one directory. Index i is one entry."""
    path: str
    names: list          # str
    is_dir: list         # bool
    sizes: list          # int, 0 for directories
    mtimes_ns: list      # int
    attributes: list     # int, Windows file attributes (0 elsewhere)
    lower_names: list    # str, casefolded names for filtering

    @classmethod
    def scan(cls, path):
        names, is_dir, sizes, mtimes, attributes = [], [], [], [], []
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                attribute = getattr(info, 'st_file_attributes', 0)
                if attribute & REPARSE_POINT:
                    # Links: one real stat follows the target, like the app today.
                    try:
                        directory = entry.is_dir()
                        info = entry.stat()
                    except OSError:
                        directory = False
                else:
                    directory = stat.S_ISDIR(info.st_mode)
                names.append(entry.name)
                is_dir.append(directory)
                sizes.append(0 if directory else info.st_size)
                mtimes.append(info.st_mtime_ns)
                attributes.append(attribute)
        return cls(path, names, is_dir, sizes, mtimes, attributes, [n.casefold() for n in names])

    def __len__(self):
        return len(self.names)


# --- Sorting ------------------------------------------------------------------

def natural_key(name):
    parts = _DIGITS.split(name.casefold())
    parts[1::2] = map(int, parts[1::2])
    return parts


def sort_order(listing, column='name', ascending=True):
    """Return entry indices in display order; directories first when ascending."""
    n = len(listing)
    if column == 'name':
        keys = list(map(natural_key, listing.names))
    elif column == 'size':
        keys = listing.sizes
    elif column == 'modified':
        keys = listing.mtimes_ns
    else:
        raise ValueError(column)
    is_dir = listing.is_dir
    order = sorted(range(n), key=lambda i: (not is_dir[i], keys[i]))
    if not ascending:
        directories = [i for i in order if is_dir[i]]
        files = [i for i in order if not is_dir[i]]
        order = directories[::-1] + files[::-1]
    return order


# --- Filtering ----------------------------------------------------------------

def hide_hidden(listing, order):
    attributes = listing.attributes
    return [i for i in order if not attributes[i] & HIDDEN]


class Filter:
    """Substring or fuzzy narrowing over a listing. Narrows incrementally."""

    def __init__(self, listing, base_order):
        self.listing = listing
        self.base = base_order
        self.mode = None
        self.query = ''
        self.result = base_order

    def apply(self, query, mode='substring'):
        query = query.casefold()
        if mode == self.mode and query.startswith(self.query) and self.query:
            candidates = self.result
        else:
            candidates = self.base
        self.mode, self.query = mode, query
        if not query:
            self.result = self.base
        elif mode == 'substring':
            lower = self.listing.lower_names
            self.result = [i for i in candidates if query in lower[i]]
        elif mode == 'fuzzy':
            self.result = fuzzy(self.listing, candidates, query)
        else:
            raise ValueError(mode)
        return self.result


def fuzzy(listing, candidates, query):
    """Subsequence match ranked by span then start; the regex runs in C."""
    pattern = re.compile('.*?'.join(map(re.escape, query)))
    lower = listing.lower_names
    search = pattern.search
    scored = []
    for i in candidates:
        match = search(lower[i])
        if match is not None:
            scored.append((match.end() - match.start(), match.start(), i))
    scored.sort()
    return [i for _, _, i in scored]


def current_algorithms():
    main = Path(__file__).resolve().parents[1] / 'main'
    for path in (main / 'python', main / 'resources/base/Plugins/SearchFileFuzzy'):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from fman.impl.filter_pattern import compile_filter
    from search_file_fuzzy.matcher import Matcher, SearchEntry
    return compile_filter, Matcher, SearchEntry


class CurrentFilter:
    """Unchanged production matchers; SearchEntry.url carries a snapshot index."""

    def __init__(self, listing, base_order, max_results=100, fuzzy_order=None):
        self.listing = listing
        self.base = list(base_order)
        self.fuzzy_base = self.base if fuzzy_order is None else list(fuzzy_order)
        self.max_results = max_results or max(1, len(self.fuzzy_base))
        self.compile_filter, self.Matcher, self.SearchEntry = current_algorithms()
        self.matchers = {}
        self.highlights = {}

    def prepare(self, mode='fuzzy'):
        if mode not in ('fuzzy', 'regular'):
            raise ValueError(mode)
        if mode not in self.matchers:
            self.matchers[mode] = self.Matcher((
                self.SearchEntry(entry, self.listing.names[entry], self.listing.names[entry])
                for entry in self.fuzzy_base
            ), mode=mode, max_results=self.max_results)
        return self.matchers[mode]

    def apply(self, query, mode='substring'):
        self.highlights = {}
        if mode == 'substring':
            matcher = self.compile_filter(query)
            return [entry for entry in self.base if matcher.matches(self.listing.names[entry])]
        matches = self.prepare(mode).matches(query)
        self.highlights = {entry.url: positions for entry, positions in matches}
        return [entry.url for entry, positions in matches]


# --- Qt model over the snapshot -------------------------------------------------

def format_size(size):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1000:
            return '%d %s' % (size, unit) if unit == 'B' else '%.1f %s' % (size, unit)
        size /= 1000
    return '%.1f PB' % size


def build_model_class():
    from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QFileIconProvider
    from PyQt5.QtCore import QFileInfo

    class ListingModel(QAbstractTableModel):
        HEADERS = ('Name', 'Size', 'Modified')

        def __init__(self, listing, visible, parent=None):
            super().__init__(parent)
            self.listing = listing
            self.visible = visible
            self._icons = QFileIconProvider()
            self._icon_cache = {}
            self._folder_icon = self._icons.icon(QFileIconProvider.Folder)

        def rowCount(self, parent=QModelIndex()):
            return 0 if parent.isValid() else len(self.visible)

        def columnCount(self, parent=QModelIndex()):
            return 3

        def headerData(self, section, orientation, role=Qt.DisplayRole):
            if orientation == Qt.Horizontal and role == Qt.DisplayRole:
                return self.HEADERS[section]
            return None

        def data(self, index, role=Qt.DisplayRole):
            entry = self.visible[index.row()]
            listing = self.listing
            column = index.column()
            if role == Qt.DisplayRole:
                if column == 0:
                    return listing.names[entry]
                if column == 1:
                    return '' if listing.is_dir[entry] else format_size(listing.sizes[entry])
                return datetime.fromtimestamp(listing.mtimes_ns[entry] / 1e9).strftime('%Y-%m-%d %H:%M')
            if role == Qt.DecorationRole and column == 0:
                return self.icon(entry)
            return None

        def icon(self, entry):
            if self.listing.is_dir[entry]:
                return self._folder_icon
            name = self.listing.names[entry]
            suffix = os.path.splitext(name)[1].casefold()
            if suffix in ('.exe', '.lnk', '.ico', '.url'):
                key = name  # these carry their own icon
            else:
                key = suffix
            icon = self._icon_cache.get(key)
            if icon is None:
                icon = self._icon_cache[key] = self._icons.icon(QFileInfo(os.path.join(self.listing.path, name)))
            return icon

        def set_visible(self, visible):
            self.beginResetModel()
            self.visible = visible
            self.endResetModel()

        def row_of(self, entry):
            try:
                return self.visible.index(entry)
            except ValueError:
                return -1

    return ListingModel


# --- Measurement harness ----------------------------------------------------------

def working_set_mib():
    if sys.platform != 'win32':
        return float('nan')
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.WorkingSetSize / 2**20


def run(folder, platform, queries, fuzzy_queries, repaint_timeout=10.0,
        algorithms='current', max_results=100, fuzzy_scope='pane',
        fuzzy_include_hidden=False):
    os.environ.setdefault('QT_QPA_PLATFORM', platform)
    if sys.platform == 'win32':
        os.environ.setdefault('QT_QPA_FONTDIR', os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts'))
    from PyQt5.QtWidgets import QApplication, QHeaderView, QTableView
    app = QApplication.instance() or QApplication([])
    report = {
        'folder': os.path.abspath(folder), 'algorithms': algorithms,
        'platform': app.platformName(), 'python': sys.version,
        'max_results': max_results, 'fuzzy_scope': fuzzy_scope,
        'fuzzy_include_hidden': fuzzy_include_hidden,
        'highlights_computed': algorithms == 'current',
        'phases_ms': {}, 'queries': [],
    }

    def measure(label, function, *args):
        started = perf_counter()
        result = function(*args)
        elapsed = (perf_counter() - started) * 1000
        report['phases_ms'][label] = elapsed
        print('%-44s %8.1f ms' % (label, elapsed), flush=True)
        return result

    baseline_mib = working_set_mib()
    print('Folder: %s\nAlgorithms: %s; fuzzy limit: %s; scope: %s' % (
        folder, algorithms, max_results or 'all', fuzzy_scope), flush=True)
    total_started = perf_counter()
    listing = measure('scan', Listing.scan, folder)
    report['entries'] = len(listing)
    print('%-44s %8d' % ('entries', len(listing)))
    order = measure('name_sort', sort_order, listing, 'name')
    visible = measure('hide_hidden', hide_hidden, listing, order)
    ListingModel = build_model_class()
    model = measure('model_construction', ListingModel, listing, visible)

    class MeasuredView(QTableView):
        paint_count = 0
        last_paint = None

        def paintEvent(self, event):
            super().paintEvent(event)
            self.last_paint = perf_counter()
            self.paint_count += 1

    view = MeasuredView()
    view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
    view.verticalHeader().setDefaultSectionSize(20)
    view.verticalHeader().hide()
    view.setModel(model)
    view.resize(900, 600)

    def wait_for_paint(previous):
        deadline = perf_counter() + repaint_timeout
        view.viewport().update()
        while view.paint_count == previous and perf_counter() < deadline:
            app.processEvents()
        if view.paint_count == previous:
            raise TimeoutError('No completed viewport paint')
        return view.last_paint

    shown = perf_counter()
    view.show()
    painted = wait_for_paint(0)
    report['phases_ms']['show_to_paint'] = (painted - shown) * 1000
    report['phases_ms']['scan_to_paint'] = (painted - total_started) * 1000
    report['working_set_after_paint_mib'] = working_set_mib()
    report['baseline_mib'] = baseline_mib
    print('Scan -> completed paint: %.1f ms; working set %.1f MiB (baseline %.1f)' % (
        report['phases_ms']['scan_to_paint'], report['working_set_after_paint_mib'], baseline_mib))

    print('\nSort by other columns (full order, no repaint):')
    measure('size_sort', sort_order, listing, 'size')
    measure('modified_sort', sort_order, listing, 'modified')
    measure('name_descending_sort', sort_order, listing, 'name', False)

    fuzzy_order = order if fuzzy_include_hidden else visible
    if fuzzy_scope == 'files':
        fuzzy_order = [entry for entry in range(len(listing)) if not listing.is_dir[entry]
            and (fuzzy_include_hidden or not (
                listing.attributes[entry] & HIDDEN or listing.names[entry].startswith('.')))]
    report['pane_candidates'] = len(visible)
    report['fuzzy_candidates'] = len(fuzzy_order)
    if algorithms == 'current':
        measure('algorithm_import', current_algorithms)
        filter_ = measure('filter_adapter', CurrentFilter, listing, visible, max_results, fuzzy_order)
        measure('fuzzy_index', filter_.prepare)
        fuzzy_filter = filter_
    else:
        filter_ = measure('filter_adapter', Filter, listing, visible)
        fuzzy_filter = measure('fuzzy_index', Filter, listing, fuzzy_order)
    report['working_set_after_index_mib'] = working_set_mib()
    print('Working set after matcher setup: %.1f MiB' % report['working_set_after_index_mib'])

    def keystroke(filter_, query, mode):
        cursor_entry = model.visible[view.currentIndex().row()] if view.currentIndex().isValid() else None
        started = perf_counter()
        result = filter_.apply(query, mode)
        if algorithms == 'simple' and mode == 'fuzzy' and max_results:
            result = result[:max_results]
        filtered = perf_counter()
        previous_paint = view.paint_count
        model.set_visible(result)
        if cursor_entry is not None:
            row = model.row_of(cursor_entry)
            if row >= 0:
                view.setCurrentIndex(model.index(row, 0))
        done = wait_for_paint(previous_paint)
        sample = {
            'mode': mode, 'query': query, 'rows': len(result),
            'match_ms': (filtered - started) * 1000,
            'reset_paint_ms': (done - filtered) * 1000,
            'total_ms': (done - started) * 1000,
        }
        report['queries'].append(sample)
        print('  %-10s %-12r %7d rows  match %7.1f ms  reset+paint %6.1f ms' % (
            mode, query, len(result), sample['match_ms'], sample['reset_paint_ms']), flush=True)

    view.setCurrentIndex(model.index(min(10, model.rowCount() - 1), 0))
    print('\nFilter queries (current grammar or simple incremental substring):')
    for query in queries:
        keystroke(filter_, query, 'substring')
    keystroke(filter_, '', 'substring')
    print('\nFuzzy queries (current scoring + highlights or simple regex):')
    for query in fuzzy_queries:
        keystroke(fuzzy_filter, query, 'fuzzy')
    keystroke(fuzzy_filter, '', 'fuzzy')
    report['working_set_after_queries_mib'] = working_set_mib()
    print('\nRescan after a simulated file operation (scan + sort + hide):')
    started = perf_counter()
    listing2 = Listing.scan(folder)
    order2 = hide_hidden(listing2, sort_order(listing2, 'name'))
    model.listing = listing2
    previous_paint = view.paint_count
    model.set_visible(order2)
    done = wait_for_paint(previous_paint)
    report['phases_ms']['listing_refresh_to_paint'] = (done - started) * 1000
    print('Listing refresh -> completed paint: %.1f ms (excludes matcher rebuild)' % (
        report['phases_ms']['listing_refresh_to_paint']))
    view.close()
    app.processEvents()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('folder')
    parser.add_argument('--platform', default='offscreen', choices=('offscreen', 'windows'))
    parser.add_argument('--queries', nargs='*', default=['1', '12', '123', '1234', '12345'])
    parser.add_argument('--fuzzy', nargs='*', default=['1', '19', '199', '1998', '19981'])
    parser.add_argument('--algorithms', default='current', choices=('simple', 'current'))
    parser.add_argument('--max-results', type=int, default=100, help='Fuzzy result limit; 0 means all')
    parser.add_argument('--fuzzy-scope', default='pane', choices=('pane', 'files'))
    parser.add_argument('--fuzzy-include-hidden', action='store_true')
    parser.add_argument('--json', type=Path, help='Write raw measurements as JSON')
    args = parser.parse_args(argv)
    if args.max_results < 0:
        parser.error('--max-results must be nonnegative')
    if not os.path.isdir(args.folder):
        raise SystemExit('Not a folder: %s' % args.folder)
    report = run(args.folder, args.platform, args.queries, args.fuzzy,
        algorithms=args.algorithms, max_results=args.max_results,
        fuzzy_scope=args.fuzzy_scope, fuzzy_include_hidden=args.fuzzy_include_hidden)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
