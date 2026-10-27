# Code Review 007: Live Refresh During File Operations

Status: Completed, 2026-10-27. Design by the user, reviewed by
GitHub Copilot and Sol. Other findings of the review are in
[CodeReview008](../Plan/CodeReview008.md).

## Task

Copy, Move and Delete notify the pane for every file. A pane showing the folder
rescans, re-sorts and resets its model back to back for the whole operation,
competing with the transfer for the GIL. The cost grows with the folder's size,
not the operation's. Copying 10,000 x 4 KiB files took 42-69 s with live
refresh and about 8 s when the pane refreshed once at the end.

Add an application setting that lets the user trade live pane updates for
faster file operations. The default keeps the current behavior.

## Scope

- Setting `live_refresh_during_file_operations` in `Core Settings.json`,
  default `true` (current behavior). `false` defers pane refreshes raised by a
  file operation until it ends.
- Command Palette: **Toggle live refresh during file operations**, with an
  On/Off status message.
- Applies to every task run through `fman.submit_task`: Copy, Move, Delete,
  Rename, Pack, Unpack and plug-in tasks.
- Excluded: per-operation choices, progress-dialog or prompt checkboxes, modal
  progress, throttling rescans and change-set updates (the latter belongs to
  [FSPaneArch003](../Plan/FSPaneArch003.md)).
- Compatibility: public `fman` API unchanged; no new files, timers or threads.

## Design

### Behavior

With live refresh off, only refresh requests raised on the task's own thread
are suppressed; the pane is not frozen. Files usually appear (or disappear, for
Delete/Move) when the task ends, and an item already deleted can still be
selected until then (its command reports "not found"). Any other scan of that
folder (Ctrl+R, navigation, an OS watcher event or another thread's
notification) shows the progress so far.

### Deferral, [file_watcher.py](../src/main/python/fman/impl/model/file_watcher.py)

- `live_refresh_enabled()` reads the setting from the existing application
  context's `config` (`load_json('Core Settings.json', {})`, cached, no I/O per
  call). It never creates a context; without one it returns `true`. A missing
  key, a non-boolean value, a non-object file or a read error also returns
  `true`, so every failure path keeps the current behavior.
- `deferred_refresh(defer)` is a context manager over a `threading.local`
  holding a `WeakSet` of models. `defer=False`, or a scope already active on
  the same thread, makes it a no-op; only the outermost scope flushes. On exit
  (success, error or `Task.Canceled`) it calls `reload()` once per collected
  model and ignores `RuntimeError` from deleted Qt objects. The weak set does
  not keep closed panes alive.
- `FileWatcher` handlers add their model to the set instead of reloading it
  while a scope is active on the calling thread. Only the reload request is
  suppressed; cache invalidation stays immediate:
  - added/removed: `MotherFileSystem._add_to_parent`/`_remove` update the
    cached `iterdir` and `stat` before `FileWatcher` runs; unchanged.
  - changed child: `fs.clear_cache(url)` runs immediately, as
    `ListingModel.notify_file_changed` does today.
  - changed watched folder: live mode clears its cache when the scan starts.
    Deferred mode calls `fs.clear_cache(location)` immediately, so concurrent
    commands never see an older cache than in live mode.
- Notifications themselves, navigate-away when a pane's folder is deleted, and
  `ScanObservation` are unchanged. `place_cursor_at` reloads directly, so
  commands that select a new file after their task still work.

### Scope Ownership

The scope belongs to the thread that runs `submit_task`. Threads a task creates
do not inherit it; their notifications refresh live. Concurrent operations have
separate scopes: when one ends, its reload also shows the other operation's
progress so far, and the other's own flush shows its end state. Nested tasks
flush once, at the outermost exit.

### Entry Point, [submit_task](../src/main/python/fman/__init__.py)

`task()` runs inside `deferred_refresh(not live_refresh_enabled())`. The setting
is read once per task start; toggling during a task affects the next one.

Endpoints, in order:

1. Task completion (success, error or cancellation).
2. Final reload request (scope exit, before the progress dialog closes).
   `reload()` only queues a scan.
3. Pane convergence: the scan commits asynchronously after `submit_task`
   returns.

The UI promises a final reload request on every exit path, not a refreshed pane
when the dialog closes.

### Command and Settings Writes

`ToggleLiveRefreshDuringFileOperations` (`ApplicationCommand`, alias "Toggle
live refresh during file operations") shows "Live refresh during file
operations: On/Off" for 5 s. A save error is shown with `show_alert` and the
setting stays unchanged.

`config.py` locks `load_json` and `save_json` separately, not the
read-modify-save between them. The toggle holds
`fman.ui.settings_resource('Core Settings.json').lock` while it loads, copies,
flips the value read under the lock, and saves; two toggles flip twice and keep
other keys. The other in-process writers of `Core Settings.json`
([comparator.py](../src/main/resources/base/Plugins/Core/core/comparator.py),
[text_editor.py](../src/main/resources/base/Plugins/Core/core/text_editor.py)
and [quick_view_csv.py](../src/main/python/fman/impl/quick_view_csv.py)) move
their read-modify-save under the same lock. Writes from another running
instance stay out of scope, as for all settings.

### Fork Coupling

Host code reads a Core setting name, as
[quick_view_csv.py](../src/main/python/fman/impl/quick_view_csv.py) does.

## Alternatives

- Buffer notifications in `MotherFileSystem`: rejected. The same notifications
  keep provider caches correct, drive navigate-away and feed `ScanObservation`;
  deferring them leaves stale caches for later steps and concurrent commands.
- Throttle rescans in the pane model: rejected as more complex (timers,
  freshness rules, guaranteed final refresh).
- A process-wide deferral counter: same speed, but delays unrelated refreshes
  (New file, a second command); per-thread scope selected.
- Per-operation choice (progress-dialog checkbox, prompt checkbox, modal
  progress): rejected by the user as more complex than one setting.
- Change sets instead of rescans: the architectural fix, planned in
  [FSPaneArch003](../Plan/FSPaneArch003.md).

## Runtime Effects

- Live mode (default): one cached dictionary lookup per task and one
  thread-local lookup per watcher notification; no timers, threads or I/O.
- Deferred mode: one scan per affected pane at the end of a task instead of
  continuous rescans. Measured with a prototype in the real application,
  10,000 x 4 KiB files into a folder shown in the other pane, until the pane
  shows every file:

  | Destination before copy | Live        | Deferred  | UI gap p99 (live -> deferred) |
  | ----------------------- | ----------: | --------: | ----------------------------- |
  | Empty                   | 42.0-43.0 s | 7.8-8.6 s | 23-29 ms -> 11 ms             |
  | 2,000 entries           | 45.7-49.6 s | 7.8-8.6 s | 25-32 ms -> 10-11 ms          |
  | 200,000 entries         | 69.1 s      | 8.1 s     | 29 ms -> 11 ms                |

- Cancellation: unchanged; the final reload runs on cancel too.

## Tests

- Unit (`fman_unittest.test_listing`): deferral per thread (another thread
  still notifies); nesting flushes once; changed-child and watched-folder
  cache clearing stay immediate; `defer=False` is a no-op; a deleted model is
  ignored; setting parsing (missing, `false`, `true`, `0`, non-object, read
  error); a failing or canceled task still requests the final reload.
- Core (`core.tests.commands.test___init__`): toggle On/Off saves and keeps
  other keys; save failure alerts without a status message; two toggles racing
  on threads end at the original value; a toggle racing a comparator or
  text-editor save keeps both keys.
- Qt (`fman_integrationtest.test_qt`, `FilterBarIT`): leave the destination
  and re-enter it during a deferred scope (the new file is visible from the
  provider cache), then the final reload shows files added after re-entry.
  Existing `submit_task`, comparator, text-editor and Table View settings tests
  stay green.
- Performance: four full-mode tests in
  [catalog.yaml](../src/performancetest/catalog.yaml) on `copy-flat-v1`, with
  two optional copy fields: `live_refresh` (default `true`; `false` makes the
  child write the setting into its isolated `UserSettings`) and
  `destination_entries` (default `0`).

  | Test                       | Refresh  | Destination before copy |
  | -------------------------- | -------- | ----------------------: |
  | `copy.flat` (existing)     | Live     | Empty                   |
  | `copy.flat.deferred`       | Deferred | Empty                   |
  | `copy.flat.large`          | Live     | 200,000 entries         |
  | `copy.flat.large.deferred` | Deferred | 200,000 entries         |

  For `destination_entries`, the child creates that many zero-byte
  `filler-NNNNNN` files in its temporary destination before the app starts
  (untimed) and waits for the destination pane to show them. The endpoint is
  `refresh_complete_ms` (pane convergence: the destination shows
  `destination_entries` plus the copied rows); `wall_ms` (task completion) is
  reported alongside. Labels: "Copy / Flat, Deferred Refresh", "Copy / Flat into
  200k" and "Copy / Flat into 200k, Deferred Refresh".

## Implementation Steps

1. Deferral and setting parsing in `file_watcher.py`; scope in `submit_task`;
   unit tests.
2. Toggle command; shared settings lock for all `Core Settings.json` writers;
   Core tests.
3. Qt integration test.
4. Performance catalog fields, child support, report labels, test and README
   counts; run the four copy tests.
5. Documentation and release notes: [configuration.md](../docs/configuration.md)
   (setting and trade-off: with live refresh off, file operations are faster
   and panes update when the operation ends), the Command Palette command, Core
   README, and CHANGELOG `Unreleased` > `Added` with both modes measured.

## Acceptance Criteria

- Default settings behave exactly as before; the focused tests above pass.
- With the setting `false`, a Copy/Move/Delete scans each affected pane once at
  the end, including on error and cancel; leaving and re-entering the
  destination during the task shows current contents.
- The toggle persists, keeps other keys and reports On/Off.
- Documentation explains the trade-off; CHANGELOG reports both modes from the
  four performance tests.

## Reviewers

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Reviewed the user's design, measured it with an out-of-repository
  prototype, specified deferral, cache invalidation, scope ownership and the
  benchmark matrix, and resolved Sol's review comments. Approved.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Sol's review: required contracts for concurrent settings writes,
  refresh endpoints, per-thread freshness, folder-level cache invalidation and
  the benchmark matrix. All were resolved in this design.

## Implementer

### 2026_10_27 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented the design. One deviation: the setting is read from the
  existing application context's `config`, never through `fman.load_json`,
  because that path creates an application context (and a main window) when
  none exists, which hung a Qt test that calls `submit_task` directly.
  Missing context means live refresh. All focused tests pass; both modes
  were measured with the four copy tests.

## Validation Results

- `fman_unittest.test_listing` (59 tests): deferral per thread, nesting,
  immediate cache clearing for child and watched folder, deleted models,
  setting parsing, no context creation, final reload on error and cancel. OK.
- `core.tests.commands.test___init__`, `core.tests.test_text_editor`,
  `core.tests.test_comparator`, `fman_unittest.test_listing` together: 275
  tests, OK (1 expected skip). Includes toggle On/Off, save failure, and two
  toggles racing a text-editor save and a Table View preset save.
- `fman_unittest.impl.test_quick_view_csv`: 19 tests, OK.
- Qt (`QT_QPA_PLATFORM=windows`): `FilterBarIT` and `QuickViewCsvIT` (17
  tests, including leaving and re-entering the destination during a deferred
  scope) OK; `ComparatorIT`, `TextEditorIT` and `RobocopyIT` (18 tests) OK.
- Performance unit tests (`test_filter_find_benchmark.py`, 78 tests): catalog
  matrix, dispatch, invalid copy fields, report headline and labels, and a
  native deferred copy into a pre-filled destination. OK.
- Qt `ArchiveTransferIT`, `UnpackArchiveIT`, `ProcessPaneIT` (5 tests): OK.
  They ran during the first `copy.flat.large` repetitions.
- Performance: `python src/performancetest/run.py suite --test copy.flat --test
  copy.flat.deferred --test copy.flat.large --test copy.flat.large.deferred`,
  run `10228b68-5a46-4855-8209-9d36788c52d0`, all passed. Medians (range) of
  `refresh_complete_ms`:

  | Test                       | Pane shows every file  | Task completion |
  | -------------------------- | ---------------------: | --------------: |
  | `copy.flat`                | 63.5 s (62.5-64.4)     | 63.4 s          |
  | `copy.flat.deferred`       | 10.4 s (10.3-10.6)     | 10.4 s          |
  | `copy.flat.large`          | 71.1 s (68.8-74.3)     | 70.5 s          |
  | `copy.flat.large.deferred` | 10.3 s (10.2-10.4)     | 10.1 s          |

- Not run: the full `build.py test` suite and the full performance suite.
