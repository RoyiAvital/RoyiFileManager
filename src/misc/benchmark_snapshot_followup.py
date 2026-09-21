"""Isolated A/B experiment for unchanged remapping and Windows stub watching."""

import argparse
import ast
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import inspect
import json
import os
from pathlib import Path
import random
import statistics
import sys
import textwrap
from time import perf_counter
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import build
os.environ['PYTHONPATH'] = build._environment()['PYTHONPATH']
sys.path[:0] = os.environ['PYTHONPATH'].split(os.pathsep)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QPA_FONTDIR', str(Path(os.environ['WINDIR']) / 'Fonts'))

from core.fs import local
from fman import listing as snapshots
from fman.impl.model import listing as model
from fman.impl.util.qt.thread import run_in_main_thread
from fman.impl.view import FileListView


SHIPPED_RECONCILE = snapshots.reconcile
ORIGINAL_RESTORE = FileListView._restore_snapshot_state


def baseline_reconcile(previous, current, check_canceled=lambda: None):
    if previous.location == current.location and previous.scope == current.scope \
            and previous.names == current.names \
            and previous.identities == current.identities \
            and previous.created_ns == current.created_ns:
        result = {}
        unknown = bytes(16)
        for start in range(0, len(previous.names), 256):
            check_canceled()
            result.update((index, index) for index in range(start, min(start + 256, len(previous.names)))
                if previous.identities[index * 16:(index + 1) * 16] != unknown)
        return result
    return SHIPPED_RECONCILE(previous, current, check_canceled)


@run_in_main_thread
def baseline_watch(provider, path):
    provider._get_watcher().addPath(provider._url_to_os_path(path))


@run_in_main_thread
def baseline_unwatch(provider, path):
    provider._get_watcher().removePath(provider._url_to_os_path(path))


def candidate_reconcile(previous, current, check_canceled=lambda: None):
    if previous.location == current.location and previous.scope == current.scope \
            and previous.names == current.names \
            and previous.identities == current.identities \
            and previous.created_ns == current.created_ns:
        offset = 0
        unknown = bytes(16)
        while True:
            check_canceled()
            offset = previous.identities.find(unknown, offset)
            if offset < 0:
                return None
            if offset % 16 == 0:
                break
            offset += 16 - offset % 16
    return baseline_reconcile(previous, current, check_canceled)


def candidate_watch(provider, path):
    if local.PLATFORM != 'Windows':
        return baseline_watch(provider, path)


def candidate_unwatch(provider, path):
    if local.PLATFORM != 'Windows':
        return baseline_unwatch(provider, path)


def restore_function(candidate):
    tree = ast.parse(textwrap.dedent(inspect.getsource(ORIGINAL_RESTORE)))
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'same' for target in node.targets)]
    if len(assignments) != 1:
        raise RuntimeError('Snapshot restoration no longer matches this experiment')
    expression = 'previous is projection.listing'
    if candidate:
        expression += ' or projection.remap is None'
    assignments[0].value = ast.parse(expression, mode='eval').body
    namespace = dict(ORIGINAL_RESTORE.__globals__)
    exec(compile(ast.fix_missing_locations(tree), '<candidate-restore>', 'exec'), namespace)
    return namespace[ORIGINAL_RESTORE.__name__]


def install_candidate(stack):
    stack.enter_context(patch.object(snapshots, 'reconcile', candidate_reconcile))
    stack.enter_context(patch.object(model, 'reconcile', candidate_reconcile))
    stack.enter_context(patch.object(FileListView, '_restore_snapshot_state', restore_function(True)))
    stack.enter_context(patch.object(local.LocalFileSystem, 'watch', candidate_watch))
    stack.enter_context(patch.object(local.LocalFileSystem, 'unwatch', candidate_unwatch))


def materialize(remap, count):
    return {index: index for index in range(count)} if remap is None else remap


def verify():
    generator = random.Random(1729)
    for iteration in range(500):
        count = generator.randrange(1, 30)
        previous = snapshots.Listing.create('file://C:/probe',
            tuple('entry%d' % index for index in range(count)),
            identities=b''.join(generator.randrange(0, 10).to_bytes(16, 'little') for _ in range(count)),
            created_ns=tuple(generator.randrange(1, 4) for _ in range(count)))
        changes = ({}, {'sizes': (2,) * count}, {'names': tuple(reversed(previous.names))},
            {'created_ns': (8,) * count}, {'identities': bytes(count * 16)},
            {'scope': (1, bytes(16))}, {'location': 'file://C:/other'})
        current = replace(previous, **changes[iteration % len(changes)])
        expected = baseline_reconcile(previous, current)
        actual = candidate_reconcile(previous, current)
        assert materialize(actual, count) == expected
    previous = snapshots.Listing.create('file://C:/probe', ('first', 'second'),
        identities=(1).to_bytes(16, 'little') + (1 << 120).to_bytes(16, 'little'))
    assert candidate_reconcile(previous, replace(previous)) is None
    with patch.object(local, 'PLATFORM', 'Windows'), \
            patch.object(local.LocalFileSystem, '_get_watcher', side_effect=AssertionError('No OS watcher')):
        provider = local.LocalFileSystem()
        callback = lambda path: None
        candidate_watch(provider, 'C:/probe')
        candidate_unwatch(provider, 'C:/probe')
        with ExitStack() as stack:
            install_candidate(stack)
            provider._add_file_changed_callback('C:/probe', callback)
            assert callback in provider._file_changed_callbacks['C:/probe']
            provider._remove_file_changed_callback('C:/probe', callback)
            assert not provider._file_changed_callbacks
    print('PASS: 500 differential identity cases, cross-boundary zero bytes, callback retention', flush=True)


def source_hashes():
    paths = (ROOT / 'src/main').rglob('*.py')
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def measure(repetitions, merged=False):
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer
    from threading import Event, Thread
    from fman.impl.util.qt.thread import Executor
    app = QApplication.instance() or QApplication([])
    Executor.instance()
    count = 200000
    previous = snapshots.Listing.create('file://C:/probe',
        tuple('entry%06d.txt' % index for index in range(count)),
        identities=b''.join((index + 1).to_bytes(16, 'little') for index in range(count)),
        created_ns=(1700000000000000000,) * count)
    current = replace(previous, names=tuple(name.encode().decode() for name in previous.names),
        identities=memoryview(previous.identities).tobytes(), created_ns=tuple(list(previous.created_ns)))
    assert candidate_reconcile(previous, current) is None
    print('Timing synthetic snapshots: 200000 entries, equal but separately allocated names/ID columns', flush=True)
    order = tuple(range(len(previous.names)))
    rows = dict.fromkeys(order)
    rows.update((index, index) for index in order)
    results = {}
    reconcile = snapshots.reconcile if merged else candidate_reconcile
    watch = local.LocalFileSystem.watch if merged else candidate_watch
    unwatch = local.LocalFileSystem.unwatch if merged else candidate_unwatch
    for count in (1, len(order)):
        selected = order[:count]
        observations = [[], []]
        for repeat in range(repetitions):
            for variant in ((0, 1) if repeat % 2 == 0 else (1, 0)):
                started = perf_counter()
                remap = (baseline_reconcile, reconcile)[variant](previous, current)
                prepared = perf_counter()
                restored = sorted(rows.get(index if remap is None else remap.get(index)) for index in selected)
                finished = perf_counter()
                assert restored == list(selected)
                observations[variant].append(dict(prepare_ms=(prepared - started) * 1000,
                    restore_ms=(finished - prepared) * 1000, total_ms=(finished - started) * 1000,
                    remap_shallow_bytes=sys.getsizeof(remap)))
        results['identity_%d_selected' % count] = observations
    observations = [[], []]
    errors = []
    finished = Event()
    def worker():
        try:
            provider = local.LocalFileSystem()
            callback = lambda path: None
            for repeat in range(repetitions):
                for variant in ((0, 1) if repeat % 2 == 0 else (1, 0)):
                    with ExitStack() as stack:
                        stack.enter_context(patch.object(local.LocalFileSystem, 'watch',
                            (baseline_watch, watch)[variant]))
                        stack.enter_context(patch.object(local.LocalFileSystem, 'unwatch',
                            (baseline_unwatch, unwatch)[variant]))
                        started = perf_counter()
                        for iteration in range(100):
                            provider._add_file_changed_callback('C:/probe', callback)
                            provider._remove_file_changed_callback('C:/probe', callback)
                        observations[variant].append(dict(pair_ms=(perf_counter() - started) * 10))
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()
    thread = Thread(target=worker, daemon=True)
    timer = QTimer()
    timer.timeout.connect(lambda: app.quit() if finished.is_set() else None)
    timer.start(5)
    thread.start()
    app.exec_()
    thread.join(5)
    if errors:
        raise errors[0]
    results['watcher_registration_pair'] = observations
    for label, variants in results.items():
        print(label, [{metric: round(statistics.median(sample[metric] for sample in samples), 4)
            for metric in samples[0]} for samples in variants], flush=True)
    return results


def measure_qt_restore(repetitions, merged=False):
    from fman_integrationtest.test_qt import FilterBarIT, _QtApp
    _QtApp.start()
    observations = [[], []]
    restorers = (restore_function(False), ORIGINAL_RESTORE if merged else restore_function(True))
    reconcile = snapshots.reconcile if merged else candidate_reconcile
    active = [0]
    def restore(view, projection):
        return restorers[active[0]](view, projection)
    class RestoreProbe(FilterBarIT):
        def test_large_restore(self):
            pane = self.panes[0]
            source = self.run_in_app(pane._model.sourceModel)
            count = 200000
            original = self.run_in_app(lambda: source._displayed)
            previous = snapshots.Listing.create(original.location,
                tuple('entry%06d.txt' % index for index in range(count)),
                identities=b''.join((index + 1).to_bytes(16, 'little') for index in range(count)))
            current = replace(previous, names=tuple(name.encode().decode() for name in previous.names),
                identities=memoryview(previous.identities).tobytes())
            visible = tuple(range(count))
            rows = {index: index for index in visible}
            def projection(listing, remap):
                return model.Projection(listing, visible, rows, remap, 0, True, columns=source._columns)
            def prepare():
                source._listing = previous
                source._commit(projection(previous, {}))
                pane._file_view.setCurrentIndex(pane._model.index(count // 2, 0))
                pane._file_view.scrollTo(pane._file_view.currentIndex())
                pane._file_view.selectAll()
                return pane._file_view.verticalScrollBar().value()
            def commit(remap, scroll):
                source._listing = current
                started = perf_counter()
                source._commit(projection(current, remap))
                elapsed = (perf_counter() - started) * 1000
                selected = pane._file_view.selectionModel().selection()
                self.assertEqual(count, sum(selection.bottom() - selection.top() + 1 for selection in selected))
                self.assertEqual(count // 2, pane._file_view.currentIndex().row())
                self.assertEqual(scroll, pane._file_view.verticalScrollBar().value())
                return elapsed
            with patch.object(source, '_icons', None):
                for repeat in range(repetitions):
                    for variant in ((0, 1) if repeat % 2 == 0 else (1, 0)):
                        active[0] = variant
                        scroll = self.run_in_app(prepare)
                        remap = (baseline_reconcile, reconcile)[variant](previous, current)
                        elapsed = self.run_in_app(commit, remap, scroll)
                        observations[variant].append(dict(qt_commit_ms=elapsed))
    with patch.object(FileListView, '_restore_snapshot_state', restore):
        result = unittest.TextTestRunner().run(unittest.TestSuite([RestoreProbe('test_large_restore')]))
    if not result.wasSuccessful():
        raise AssertionError('Large Qt restoration parity failed')
    print('Qt all-selected commit median ms:',
        [round(statistics.median(sample['qt_commit_ms'] for sample in samples), 3)
            for samples in observations], flush=True)
    return {'qt_all_selected_restore': observations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--qt-tests', action='store_true')
    mode.add_argument('--measure', action='store_true')
    mode.add_argument('--qt-restore', action='store_true')
    parser.add_argument('--merged', action='store_true', help='Exercise merged application functions instead of prototypes')
    parser.add_argument('--repeat', type=int, default=9)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    before = source_hashes()
    verify()
    if args.qt_tests:
        with ExitStack() as stack:
            if not args.merged:
                install_candidate(stack)
            suite = unittest.defaultTestLoader.loadTestsFromNames([
                'fman_unittest.test_listing', 'core.tests.fs.test_local',
                'fman_integrationtest.test_qt'])
            result = unittest.TextTestRunner().run(suite)
            if not result.wasSuccessful():
                return 1
    if args.measure or args.qt_restore:
        results = (measure_qt_restore if args.qt_restore else measure)(args.repeat, args.merged)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as output:
                json.dump(dict(repetitions=args.repeat, merged=args.merged, measurements=results, source_sha256=before,
                    experiment_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), output, indent=2)
    assert before == source_hashes(), 'Application source changed during the experiment'
    print('PASS: application source unchanged', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())