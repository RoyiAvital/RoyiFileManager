from contextlib import contextmanager
from threading import Event, Lock
from weakref import WeakKeyDictionary
import ntpath
import os

from fman import DirectoryPaneCommand, NO, YES, QuicksearchItem, Task, load_json, show_alert, show_prompt, show_quicksearch, show_status_message, submit_task
from fman.fs import notify_file_added, notify_file_changed
from fman.ui import TableColumn, TableRow, UiController, settings_resource, show_table
from fman.url import as_human_readable, as_url

from . import engine


COLUMNS = (TableColumn('Relative Path', 'file_path'), TableColumn('Status'), TableColumn('Expected'),
           TableColumn('Actual'), TableColumn('Details'))
_busy = WeakKeyDictionary()
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


def show_results(results, pane, manifest):
    retained = results.all_rows if results.all_rows is not None else results.problems
    show_table(columns=COLUMNS, rows=tuple(TableRow(row.cells) for row in retained), pane=pane, modal=False,
               title='Verify checksum file: ' + engine.display_text(os.path.basename(manifest)),
               summary=results.summary, base_path=os.path.dirname(manifest),
               truncated=len(retained) < results.total)


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
        results = manifest = None
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
                results = task.result
            # Shown after the pane lock is released: the modeless table stays open while the user works.
            if results is not None:
                show_results(results, self.pane, manifest)
        except engine.Canceled:
            pass
        except (OSError, ValueError, RuntimeError) as error:
            if run is None or run.owner.active and not run.canceled.is_set():
                show_alert(self.aliases[0] + ': ' + engine.display_text(error))