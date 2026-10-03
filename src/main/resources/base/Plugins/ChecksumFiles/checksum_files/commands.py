from contextlib import contextmanager
from threading import Event, Lock
from weakref import WeakKeyDictionary
import ntpath
import os

from fman import DirectoryPaneCommand, NO, YES, QuicksearchItem, Task, load_json, show_alert, show_prompt, show_quicksearch, show_status_message, submit_task
from fman.fs import notify_file_added, notify_file_changed
from fman.ui import TableAction, TableRow, UiController, settings_resource, show_table
from fman.url import as_human_readable, as_url

from . import engine


_busy = WeakKeyDictionary()
_tables = WeakKeyDictionary()
_lock = Lock()


class ChecksumController(UiController):
    pass


def _local(url):
    if not isinstance(url, str) or not url.startswith('file://'):
        raise ValueError('Checksums require an ordinary local or UNC folder.')
    path = as_human_readable(url)
    drive, tail = ntpath.splitdrive(path)
    if not os.path.isabs(path) or path.startswith(('\\\\?\\', '\\\\.\\')) or ':' in tail or '\x00' in path:
        raise ValueError('Unsupported local path.')
    return os.path.normpath(path)


class _Run:
    def __init__(self, pane, owner):
        self.pane = pane
        self.owner = owner
        self.canceled = Event()

    def check(self):
        if self.canceled.is_set() or not self.owner.active:
            raise engine.Canceled()


@contextmanager
def _running(pane):
    owner = ChecksumController.require_owner()
    run = _Run(pane, owner)
    with _lock:
        if pane in _busy:
            raise ValueError('A checksum operation is already running in this pane.')
        _busy[pane] = run
    unsubscribe = None
    try:
        if not owner.attach(run.canceled.set):
            raise engine.Canceled()
        unsubscribe = pane.on_closed(run.canceled.set)
        run.check()
        yield run
    finally:
        if unsubscribe is not None:
            unsubscribe()
        owner.detach(run.canceled.set)
        with _lock:
            if _busy.get(pane) is run:
                del _busy[pane]


def _capture(run, selection):
    changed = Event()
    unsubscribe = run.pane.on_path_changed(changed.set)
    try:
        root_url = run.pane.get_path()
        selected = tuple(run.pane.get_selected_files()) if selection else ()
        highlighted_url = run.pane.get_file_under_cursor() if not selection else None
        with settings_resource('ChecksumFiles.json').lock:
            settings = engine.Settings.from_mapping(load_json('ChecksumFiles.json', default={}))
        current_url = run.pane.get_path()
        run.check()
        if changed.is_set() or current_url != root_url:
            raise ValueError('The folder changed during capture. Please retry.')
        highlighted = _local(highlighted_url) if highlighted_url else None
        return _local(root_url), tuple(_local(url) for url in selected), settings, highlighted
    finally:
        unsubscribe()


def _choose(items, default=0):
    prepared = tuple(items)
    def matches(query):
        needle = query.casefold()
        return tuple(item for item in prepared if needle in item.title.casefold())
    choice = show_quicksearch(matches, item=default)
    return None if choice is None else choice[1]


class _ChecksumTask(Task):
    def __init__(self, title, run, operation):
        super().__init__(title)
        self.run_context = run
        self.operation = operation
        self.completed = False
        self.result = None

    def check(self):
        try:
            super().check_canceled()
        except Task.Canceled:
            raise engine.Canceled() from None
        self.run_context.check()

    def __call__(self):
        progress = engine.Progress(lambda amount: self.set_text('%s: %s bytes read' % (self.get_title(), format(amount, ','))))
        try:
            self.result = self.operation(self.check, progress)
        except engine.Canceled:
            return
        self.completed = True


class ResultsTable:
    def __init__(self, results, owner, pane, manifest):
        self.owner = owner
        self.pane = pane
        self.manifest = manifest
        self.handle = None
        self.closed = False
        self.summary = results.summary
        retained = results.all_rows if results.all_rows is not None else results.problems
        self.targets = {row.line: row.target for row in retained if row.target is not None}
        self.details = {row.line: (row.path, row.details) for row in retained if row.details}
        prepared = {row.line: TableRow(str(row.line), row.cells, row.line) for row in retained}
        self.problems = tuple(prepared[row.line] for row in results.problems)
        self.all_rows = None if results.all_rows is None else tuple(prepared[row.line] for row in results.all_rows)
        self.rows = self.problems

    def show(self):
        if not self.owner.attach(self.release):
            raise engine.Canceled()
        try:
            self.handle = show_table(
                owner=self.owner, pane=self.pane, modal=False,
                title='Verify checksum file: ' + engine.display_text(os.path.basename(self.manifest)),
                get_rows=lambda: self.rows, num_columns=5,
                columns_header=('Relative Path', 'Status', 'Expected', 'Actual', 'Details'),
                file_path_column=0, base_path=os.path.dirname(self.manifest),
                resolve_path=lambda row, column: self.targets.get(row.value),
                get_details=self.get_details,
                get_menu=self.menu, summary=self.summary,
                get_background_menu=lambda: self.menu(None, -1),
                get_count_text=lambda visible, total: '%s results loaded' % total,
                on_closed=self.release)
        except Exception:
            self.release()
            raise
        return self.handle

    def get_details(self, row, column):
        return '\n'.join(engine.display_text(value) for value in self.details.get(row.value, ()))

    def menu(self, row, column):
        if self.all_rows is None:
            return ()
        return (TableAction('all', 'Show all results', lambda row, column: self.switch(True)),
                TableAction('problems', 'Show only mismatches', lambda row, column: self.switch(False)))

    def switch(self, all_results):
        if self.closed or not self.owner.active or self.handle is None or not self.handle.is_open:
            return
        if all_results and self.all_rows is None:
            return
        previous = self.rows
        self.rows = self.all_rows if all_results else self.problems
        try:
            self.handle.refresh()
        except Exception:
            self.rows = previous
            raise

    def release(self):
        self.owner.detach(self.release)
        if self.pane is not None and _tables.get(self.pane) is self:
            del _tables[self.pane]
        self.pane = None
        self.closed = True
        self.rows = self.problems = ()
        self.all_rows = None
        self.targets.clear()
        self.details.clear()


class GenerateChecksumFile(DirectoryPaneCommand):
    aliases = ('Generate checksum file',)

    def __call__(self):
        run = None
        try:
            with _running(self.pane) as run:
                root, selected, settings, highlighted = _capture(run, True)
                algorithms = engine.ALGORITHMS
                identifier = _choose((QuicksearchItem(item.identifier, item.label) for item in algorithms),
                                     next(index for index, item in enumerate(algorithms) if item.identifier == settings.default_algorithm))
                if identifier is None:
                    return
                algorithm = engine.BY_ID[identifier]
                run.check()
                scope = '%s selected items, recursively' % len(selected) if selected else 'Entire folder, recursively'
                name = ntpath.basename(root.rstrip('/\\')) or 'checksums'
                filename, accepted = show_prompt('%s\n%s\n%s checksum filename:' % (engine.display_text(root), scope, algorithm.label), name + algorithm.extension)
                if not accepted:
                    return
                relative = engine.relative_path(filename)
                if '/' in relative:
                    raise ValueError('The checksum filename must be in the captured folder.')
                if engine.algorithm_for_path(relative) != algorithm:
                    raise ValueError('Filename extension does not match the selected algorithm.')
                destination = os.path.join(root, relative)
                run.check()
                try:
                    expected = engine._identity(engine._inspect(destination))
                except FileNotFoundError:
                    expected = None
                if expected is not None and show_alert('Replace checksum file?\n' + engine.display_text(destination), YES | NO, NO) != YES:
                    return
                task = _ChecksumTask('Generate ' + algorithm.label, run,
                    lambda check, progress: engine.generate(root, selected, destination, algorithm, settings, check, progress, expected))
                submit_task(task)
                if task.completed:
                    (notify_file_added if expected is None else notify_file_changed)(as_url(destination))
                    run.check()
                    result = task.result
                    show_status_message('Generated %s: %s files, %s bytes; %s linked or special entries skipped.' % (filename, result.files, result.bytes_read, result.skipped), 10)
                else:
                    run.check()
                    show_status_message('Checksum generation canceled; no manifest published.', 5)
        except engine.Canceled:
            pass
        except (OSError, ValueError, RuntimeError) as error:
            if run is None or run.owner.active and not run.canceled.is_set():
                show_alert(self.aliases[0] + ': ' + engine.display_text(error))


class VerifyChecksum(DirectoryPaneCommand):
    aliases = ('Verify checksum file',)

    def __call__(self):
        run = None
        try:
            with _running(self.pane) as run:
                root, selected, settings, highlighted = _capture(run, False)
                discovery = _ChecksumTask('Find checksum files', run, lambda check, progress: engine.discover(root, check))
                submit_task(discovery)
                if not discovery.completed:
                    return
                run.check()
                manifests = tuple(path for path in discovery.result
                                  if ntpath.splitext(path)[1].lower() in engine.BY_EXTENSION)
                if not manifests:
                    show_alert('No checksum file found in the current folder.')
                    return
                manifest = highlighted if highlighted in manifests else min(
                    manifests, key=lambda path: (ntpath.basename(path).casefold(), ntpath.basename(path)))
                run.check()
                task = _ChecksumTask('Verify ' + engine.display_text(os.path.basename(manifest)), run,
                                     lambda check, progress: engine.verify(manifest, settings, check, progress))
                submit_task(task)
                run.check()
                if task.result is not None:
                    table = ResultsTable(task.result, run.owner, self.pane, manifest)
                    run.check()
                    previous = _tables.get(self.pane)
                    if previous is not None and previous.handle is not None:
                        previous.handle.close()
                    table.show()
                    _tables[self.pane] = table
        except engine.Canceled:
            pass
        except (OSError, ValueError, RuntimeError) as error:
            if run is None or run.owner.active and not run.canceled.is_set():
                show_alert(self.aliases[0] + ': ' + engine.display_text(error))