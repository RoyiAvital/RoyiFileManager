# Directory Size

## Current Revision: Core Size

The 2026_09_17 revision supersedes the standalone-column design below. The user
requires native Core ownership, not a plug-in-to-Core provider or API bypass.
This revision is implemented. Sections Task through Acceptance Criteria preserve
the initial design; earlier reviewer and validation records remain historical.
The final Core revision results are recorded at the end of Validation Results.

- Task and scope: toggle recursive directory totals inside the existing
  `core.Size` column. Keep ordinary file sizes, all three default columns,
  pane state, sort column/direction and widths intact. Off restores Core's
  blank directory cells and normal directory-name ordering.
- Design: the scanner, result state, service and commands live in
  [Core/core/directory_size](../src/main/resources/base/Plugins/Core/core/directory_size/__init__.py).
  Core registers its own service and reads its own current result snapshots.
  The separate DirectorySize plug-in and column have been removed;
  no cross-plug-in callback, column replacement or public API extension is added.
  The normal private host lifecycle and asynchronous model refresh remain in use.
- Compatibility: preserve `DirectorySize.json` enablement,
  `toggle_directory_size_column` and the other command IDs, and all three keys.
  The visible toggle becomes `Toggle directory sizes`, with `Directory sizes:
  On/Off` five-second messages. Ignore legacy `show_file_sizes`; file sizes are
  always the existing Core behavior. No public `fman` API change.
- File limit: the user's final requirement is a configurable default of
  10,000,000 regular files per directory root for both automatic and one-time
  scans. Use `max_files`; `0` means unlimited. Directories do not consume the
  limit. Ignore legacy `max_entries` so old saved 200,000-entry defaults do not
  constrain new scans. A subtotal keeps updating until completion, cancellation,
  an error or the configured cap; `+` marks a cap, not a complete total.
- One-time calculation: `Ctrl+Shift+Enter` uses only the status bar, showing
  `Calculating <path> size...` and then a five-second result. Multiple chosen
  directories show a count followed by a combined summary. No progress dialog
  or Cancel button is created. A newer request cancels the previous request;
  owner disposal cancels all outstanding work. Only the current request may
  publish its result. Invalid selection also reports through the status bar.
  Normal status-bar replacement by other commands remains unchanged.
- Runtime effects: keep the one enabled-only worker, no cross-location cache,
  incremental batches, cancellation and stale-result rejection. Toggle refreshes
  rows without recreating the column schema. Off/disposal performs one final
  local-pane refresh without waiting for scans; disabled steady state has no
  automatic worker, pane callbacks or recurring feature work.
  The higher default permits more metadata I/O and longer scans on large trees,
  but adds no worker, timer or content reads. Memory still tracks pending
  directories and current result snapshots, not all visited files.
  One-time scans reuse the existing command worker thread and scanner, with
  only start/result status updates marshaled to Qt. No progress-update timer,
  preliminary enumeration, extra executor or recurring UI work is added.
  Canceled OS calls may finish after replacement; their results are rejected.
- Reviewer correction, resolved: a pending nested-pane row inherits a parent result only
  when `size_bytes is None and errors`, never a known parent subtotal or total.
  Both the focused lookup and the actual two-pane Qt regression pass.
- Alternatives: a separate column was rejected by the user; a private provider
  connecting a separate plug-in to Core was also explicitly rejected. Moving
  ownership into Core keeps this a normal Size feature without adding an API.
- Implementation steps completed: moved implementation into Core; connected
  display/sorting with comparable directory sort keys across On/Off; migrated
  registrations and tests; updated Core usage, changelog and validation records.
- Tests and acceptance: Core Size tests must preserve files and non-local rows;
  Qt tests must prove unchanged columns/state, actual directory totals, nested
  panes, registered shortcuts, persistence, explicit Task and nonblocking teardown.
  Reuse calculator regressions. Keep independent optional-column host tests from
  the first implementation; the feature no longer calls those hooks.
  Assert the standalone bundled folder is absent; full source startup must keep
  three columns even with legacy saved settings. Cover custom and unlimited
  limits, exact file-limit completion and progressive scans beyond 200,000 entries.
  The registered one-time shortcut must not create a dialog. Hold its scan
  open while checking the actual status bar, UI dispatch, normal completion,
  replacement and owner disposal; stale results must not overwrite newer text.

## Task

Add a bundled `DirectorySize` plug-in that provides an optional `Dir Size`
column showing the total size of each directory's contents, inspired by
[jardous/directory_size](https://github.com/jardous/directory_size) (which
only shows one directory's size in the status bar on demand) and by Total
Commander's `Alt+Shift+Enter` "calculate occupied space". The column is off
by default and has two equivalent toggle paths:

- Press `Ctrl+Shift+P`, then run `Toggle directory size column` in the Command
  Center. `Ctrl+Shift+P` keeps its existing Command Center binding.
- Press `Ctrl+Shift+D` to run that same toggle directly. This shortcut is unused
  in the current bundled bindings and remains user-overridable.

The setting applies to both panes and persists across restarts. Sizes are
computed in the background. After either toggle path succeeds, show
`Directory size column: On` or `Directory size column: Off` in the existing
status bar for five seconds. No permanent label, new status widget or startup
notification is added; the extended status-bar mode remains unchanged.

Keep the implementation simple, even at the cost of repeated scans. Responsive
navigation is more important than avoiding recomputation: neither Qt nor model
workers wait for a recursive walk. Populate completed rows as the scan proceeds
and show a running subtotal for a large directory before its walk finishes.

A second command, `Show Directory Size`, computes the size of the chosen
directories on demand and shows it in the status bar, so the reference
plug-in's behaviour remains available even when the column is disabled.

## Scope

Included:

- Column `directory_size.DirectorySize`, display name `Dir Size`, showing the
  recursive size of directories; files show an empty cell unless
  `show_file_sizes` is enabled.
- Placeholders: `...` while computing, `?` when the walk hit errors, a trailing
  `...` after a running subtotal (`1.2 GiB...`), `+` on a capped result and `?`
  on an error result. A plain size means the walk completed without either flag.
- Sorting by the column: directories by computed bytes (unknown treated as
  `-1`), then files; the `is_dir ^ is_ascending` major key mirrors `core.Size`.
- One simple automatic scan of the currently displayed local folders, restarted
  on enable, navigation or `Recalculate Directory Sizes`. Results are retained
  only for that scan, not cached across locations or enable cycles.
- Column toggle through the Command Center or `Ctrl+Shift+D`; the column is
  removed and a temporary Off notification appears without waiting for worker
  termination.
- `Show Directory Size` status-bar command for the chosen directories.
- Reuse of the shared `format_size`/`size_divisor` from
  `fman.impl.status_bar` so the column, status bar and `Size` column agree.

Excluded:

- Sizes for non-`file://` schemes (`zip://`, `network://`, `drives://`) — the
  cell stays empty.
- Following symlinks or junctions, including a selected/displayed walk root.
- Persisting computed sizes across restarts.
- Showing allocated (cluster) size instead of logical size.
- Parallel scan workers, content reads/hashing, full-tree verification passes,
  filesystem snapshots and protection against concurrent external file changes.
- Cross-request result sharing, priority scheduling, TTL/LRU caches, consumer
  reference counts and a generic background-job framework.
- Watching external file changes. Navigate, re-enable or run Recalculate for
  fresh totals; an ordinary pane reload alone may retain the current size values.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
plug-in uses public commands, `Column`, pane callbacks, configuration and
filesystem APIs. Its documented fork-specific imports are `format_size` and
the private lifecycle/column/refresh hooks below. Do not advertise those hooks
as public `fman` APIs or require changes to third-party plug-ins. No changes to
Core settings, normal filesystem notifications or existing shortcuts are made.

## Design

### Ownership And Lifecycle

Keep the private `PluginService` lifecycle to just `start()`,
`on_pane_added(pane)` and idempotent `dispose()` in
[the plug-in loader](../src/main/python/fman/impl/plugins/plugin.py). Create the
Directory Size controller after column registration, and reuse
[UiOwner.attach/invalidate](../src/main/python/fman/impl/ui/__init__.py#L85) to
dispose it before columns/modules are unregistered, including failed loading.
This is a lifecycle hook only, not a scheduler or service-retirement framework.
Plug-ins without services keep their current behavior.

Read settings when the first pane attaches, after all configuration layers,
including User Settings, have loaded. Do not retain an early default-only config
dict: later plug-in layers can replace it before pane creation. Startup restoration
does not emit a toggle notification.

The controller owns one `ThreadPoolExecutor(max_workers=1)` while automatic mode
is enabled, one current future, one cancellation `Event`, an integer generation
and a locked results dict keyed by URL. Reuse the executor/cancellation approach
already used by [status calculations](../src/main/python/fman/impl/status_bar.py),
but do not share their worker: a recursive walk must not delay ordinary status
statistics. Column methods only read the current results dict.

Connect `pane.on_path_changed` and `pane.on_closed` only while enabled. On a
displayed-location change, cancel the previous batch and submit a fresh snapshot
of both panes' local parent URLs. Identical parent URLs can be collapsed with a
set; there is no subscription accounting or cross-request cache. Restarting the
unchanged pane too is acceptable. Failed navigation keeps the displayed paths.
Only the newest pending batch is useful; cancel superseded futures before submit.

On restart, clear the results and request one ordinary asynchronous pane reload
per displayed local folder to reset cells, then scan the captured locations.
Do not trigger scans from row-result refreshes or column methods. Results carry
the batch generation; queued delivery checks that generation, the live owner
and the current parent before refreshing a pane. Old results cannot restore
values after navigation, disable or reload.

Disable/dispose disconnects callbacks, removes columns and cancels the current
batch. Use `shutdown(wait=False, cancel_futures=True)`;
never call `join()` or `Future.result()` on Qt or a model worker. The standard
executor handles idle-worker wake-up; do not implement a custom queue/sentinel.
An in-flight OS call can delay physical worker exit. A quick re-enable/reload
may briefly overlap a canceled retiring call with a new executor; its results
are rejected. Avoid host-wide retirement coordination solely to prevent that.
Interpreter exit can also wait for such an OS call; no forced thread termination
or prompt-exit guarantee is introduced.

When disabled, retain only configuration and lifecycle ownership:
no result cache, executor, pane callbacks or recurring work. A separately
invoked `Show Directory Size` uses the existing command/task worker, not this
automatic executor.

### Impl Hooks

1. **Optional columns per pane.** `LocalFileSystem.get_default_columns`
  remains the owner of its normal three columns. Add an impl-only
  `DirectoryPaneWidget.set_extra_columns(owner, columns_by_scheme)` hook.
  The widget stores contributions by owner and passes the applicable names
  to `SortedFileSystemModel` whenever it creates a source model. The model
  asks `MotherFileSystem` to resolve registered names and appends valid
  extras after the filesystem defaults. Unknown optional names are reported
  and skipped; invalid names returned by a filesystem retain the current
  `FileSystemWrapper` fallback behaviour. This distinction matters because
  `MotherFileSystem.get_columns` currently raises for unknown names.
  `DirectorySize.json` remains the sole owner of enablement; the plug-in
  never reads or writes `Core Settings.json`.
2. **Recreating columns at the current location.** Changing an owner's
  contribution forces source-model recreation even when the URL is
  unchanged. Preserve location, cursor URL, selected URLs, active filters,
  hidden-files state, and widths keyed by qualified column name. Preserve
  the current sort column and direction when that column remains; otherwise
  fall back to `core.Name` ascending. Widths for newly added columns use the
  normal view default. Separate column recreation from navigation so it neither
  clears the FilterBar nor adds history entries. Restore cursor/selection after
  rows load only if the same pane/model generation is still current. Qt/model
  deletion also invalidates queued restoration callbacks; check before touching
  the native model or view. Qt/model
  changes run on Qt; filesystem resolution and row loading stay off Qt.
3. **Refreshing changed rows in a batch.** Add an impl-only
  `DirectoryPaneWidget.refresh_files(urls)` hook, forwarding current child URLs
  through `SortedFileSystemModel` to a new asynchronous `Model.refresh_files`
  transaction. Recheck membership and model shutdown when it executes; do not
  resurrect removed rows. Reuse warm filesystem metadata since only the size
  results changed. Refresh/re-sort once per delivered batch, not once per scanned
  file or with a full pane reload for every subtotal. Never call synchronous
  `Model.notify_file_changed` from Qt. Do not change
  `FileSystem.notify_file_changed`: its exact-path callback contract remains
  intact, so ordinary filesystem notifications cannot be duplicated.
4. **Consistent width persistence.** Fix the existing getter/setter mismatch:
  `get_column_widths` returns all non-stretching columns (`columnCount() - 1`);
  the positional setter accepts that length and legacy full-length lists.
  The last column continues to stretch and has no independently persisted width.
  Keep a pane-local width map by qualified name across column removal/re-addition.
  In [session storage](../src/main/python/fman/impl/session.py), save that map as
  `column_widths_by_name` alongside the legacy default-column `col_widths` list.
  Prefer the map on restore; migrate old lists against filesystem default column
  names before appending extras, so a legacy two-width list still works when the
  new column is enabled. Apply known widths after the actual columns exist;
  unknown names are harmless, and new names get view defaults. Reuse existing
  portable session storage, not a new settings file or Registry entry.

### Plug-in Layout `Plugins/DirectorySize/`

- `directory_size/__init__.py` - column, commands and lifecycle service.
- `directory_size/calculator.py` - pure-Python walk and immutable progress records;
  no Qt or plug-in registry imports.
- `Key Bindings (Windows).json`, `README.md`. Defaults live in code; there is no
  bundled `DirectorySize.json` override.

### Column

`DirectorySize(Column)`:

- `get_str(url)`: if the scheme is not `file://` or the URL is not a
  directory (via the filesystem query cache) return `''` (file sizes are shown
  only for local files when `show_file_sizes` is on). Otherwise read the latest
  result: missing -> `...`; running -> formatted subtotal plus `...`; complete
  -> formatted size; capped/errors -> size with `+`/`?`. Use the shared formatter,
  so units follow the current divisor. Unreadable roots show `?`; linked roots
  have an empty cell. Do not enqueue, recurse or perform link checks here.
- `get_sort_value(url, is_ascending)`: directory-first major key as in `core.Size`,
  then latest bytes (`-1` when unknown), or a file size/name according to the
  file-size setting. Values within each group have comparable types. Subtotals
  can change sort order; use existing URL-based cursor/selection preservation,
  not focus changes or automatic scrolling after each update.
- Display name `Dir Size`.

Column methods run on model workers and never wait for a result. Their result
lookup is O(1), under a short lock; normal filesystem type/size queries can use
the model-warmed cache. No Qt calls, disk I/O or waits under the result lock.

### Calculator

1. The automatic worker enumerates each captured parent with `os.scandir`, then
   walks its direct child directories sequentially. Enumeration, root validation,
   recursive walking and metadata reads all happen off Qt and off model workers.
   Processing in enumeration order is sufficient; no viewport priority scheduler.
2. Before opening a child root, reject symlinks/junctions without following them.
   Walk iteratively, with context-managed iterators and `follow_symlinks=False`.
   Sum regular-file logical sizes using directory-entry metadata, counting files
   separately from visited entries. Skip descendant links; catch `OSError` and
   retain any known subtotal with an error flag. Stop a root at `max_entries`
   (default 200000), mark it capped and proceed to the next child.
3. Check the cancellation event before each directory open and every 256 entries.
   Cancellation closes iterators and returns without marking an unfinished root
  complete. Re-raise `InterruptedError` before handling `OSError`, its base class,
  so cancellation cannot be mistaken for a filesystem error. A blocked OS call
  itself cannot be interrupted; it must not hold
   a lock or prevent the UI from navigating, disabling or accepting other commands.
4. Yield immutable `DirSize(size_bytes, files, entries, complete, capped, errors,
   skipped_link)` snapshots during and after each root. `size_bytes=None` denotes
   an unreadable/skipped root, not a successful zero. Running counts are lower
   bounds for that traversal, not a coherent snapshot of concurrently changing files.
5. Batch changed root snapshots and publish at most every 200 ms, plus a final
   flush. Check elapsed monotonic time while walking; add no polling timer or
   artificial sleep. Intermediate snapshots of the same root replace its earlier
   subtotal; they are never added together. Small-directory completions may share
   a batch so thousands of tiny folders cannot flood Qt with per-file signals.
6. A queued Qt signal delivers `(generation, changed_results)`. Check the live
   owner/generation, replace current result entries, then issue one asynchronous
   changed-row refresh per affected pane. In-progress bytes display with `...`;
   completed rows become final without waiting for all other roots. Do not wait
   for a whole-pane scan to finish before displaying any data.

The result dict serves only the current display and is cleared on every batch
restart, disable and unload. No TTL, LRU, on-disk cache, pending-URL bookkeeping,
futures shared among consumers or timestamps attached to stored results. A
repeat visit or explicit calculation may walk the same tree again by design.

### Commands

- `ToggleDirectorySizeColumn` (`toggle_directory_size_column`, alias
  `Toggle directory size column`; application command, Command Center and
  `Ctrl+Shift+D`): both entry points execute the same operation. Serialize
  toggles; update `DirectorySize.json`, attach/detach callbacks and set/clear the
  contribution in both panes. Non-local panes gain the column only after local
  navigation. After applying the change, call the public
  `show_status_message('Directory size column: On', timeout_secs=5)` (or `Off`).
  Reuse its existing Qt dispatch and expiry; later messages may replace it normally.
  On disable, detach/remove, cancel automatic work and notify without waiting for
  the worker. On persistence failure, report the error and retain/restore the prior
  setting without a success notification. Startup restoration and plug-in disposal
  do not emit toggle notifications. Neither route may repurpose `Ctrl+Shift+P`
  or alter the extended status-bar setting.
- `ShowDirectorySize` (`show_directory_size`, alias `Show directory size`,
  `Ctrl+Shift+Enter`; pane command): visibility checks only the local pane scheme,
  with no filesystem I/O. On invocation, capture chosen local URLs and validate
  directories off Qt; ignore files/non-local selections and alert if none apply.
  Run the same walker in an existing `Task` on the command worker, with ordinary
  progress/Cancel. This independent request does not join the automatic scan,
  populate its result dict or keep an automatic executor alive while disabled.
  Navigation or column Off does not cancel the explicit task; its Cancel control
  and plug-in disposal do. Owner cleanup only tracks the task's cancellation
  event for its lifetime, not a shared-request service. Duplicate calculations
  are acceptable. Suppress delivery after cancellation or owner invalidation.
  Show a five-second status, for example `name: 1.2 GB (12345 files)` for a
  complete result or `name: at least 1.2 GB (partial; entry limit)` / `(errors)`
  for incomplete results. Multiple roots sum known bytes/files and OR the partial
  flags; report skipped linked roots separately. All-skipped or unreadable roots
  must not produce a successful zero-byte total. These use ordinary temporary
  status messages, including their normal replacement and expiry behavior.
- `RecalculateDirectorySizes` (`recalculate_directory_sizes`, alias
  `Recalculate directory sizes`; application command, Command Center only):
  enabled-only; otherwise a no-op. Cancel the old automatic batch, clear its
  results and rescan both local panes from scratch. Use one pane reload to reset
  existing cells, not repeated full reloads for incremental results.
- `SortByDirectorySize` (`sort_by_directory_size`, alias `Sort by directory
  size`; pane command, `Ctrl+F4`): available only when the actual pane contains
  the column. Sort by its qualified name, never by an assumed index. Repeated
  invocation reverses direction when already sorting this column. If disabled
  between visibility checking and execution, no-op instead of raising an error.
  Resolve a requested sort name after appending optional columns on navigation,
  so navigating while sorted by Directory Size retains the chosen direction.

### Threading Summary

- Qt: capture the two locations, change columns/status text and apply small result
  batches. No recursive I/O, thread joins, future waits or full-tree enumeration.
- Model workers: ordinary row loading and asynchronous `Model.refresh_files`.
  Column methods only inspect current results; scans cannot occupy model workers.
- Automatic executor / explicit command task: plain paths, metadata walking,
  cancellation checks, throttled immutable progress records. No Qt access.
- Queued delivery checks owner/generation before updating results; locks cover
  data access only. No synchronous `Model.notify_file_changed` call from Qt.
- Off/disposal cancels immediately; physical exit is cooperative. No automatic
  callback, feature timer or new scan is allowed afterward. The existing shared
  status-message timer may expire the brief toggle notification as usual.

## Alternatives

- **Show directory sizes inside `core.Size`** (as Total Commander does)
  instead of a new column: fewer impl changes, but the user asked for a
  dedicated column and mixing makes "size of files only" sorting impossible.
  Rejected; could be a later `mode` setting.
- **Compute inside `get_str` synchronously** (reference plug-in style):
  blocks the model worker for seconds per directory and freezes row loading.
  Rejected.
- **Always-registered `DirectoryPaneListener`**: rejected because its wrapper
  dispatches a new thread for every path event even when the feature is off.
  Lazy public pane callbacks and host-owned service disposal cover navigation,
  closure, reload and removal without changing legacy listener behavior.
- **Cache, prioritize and share calculations**: rejected for this version. The
  user prefers a simpler design even when folders are scanned again. One current
  automatic batch plus independent explicit tasks is easier to implement/test.
- **Custom queue, sentinel protocol or coordinated service retirement**: rejected
  in favor of the existing standard-executor pattern and event cancellation.
  A briefly retiring canceled OS call is acceptable; blocking Qt is not.
- **Display only after the whole scan**: rejected. Send completed rows and running
  subtotals in throttled batches so progress is visible while navigation remains usable.
- **Persistent On/Off label**: rejected by the user. A brief notification through
  `show_status_message` is sufficient and needs no status-bar hook or new widget.
- **Change `FileSystem.notify_file_changed` to invoke parent callbacks**:
  activates the existing child-row watcher branch, but silently broadens a
  global callback contract and can duplicate notifications. Rejected in
  favour of the explicit pane/model refresh hook.
- **Store configured columns in `Core Settings.json`**: makes this plug-in
  mutate another component's settings and leaves stale names after plug-in
  removal. Rejected in favour of per-pane contributions owned by the plug-in.
- **Per-pane full `reload()` for each completed size**: uses existing public
  methods but re-stats and re-sorts the entire directory repeatedly. Rejected.
- **`Alt+Shift+Enter` binding for `Show Directory Size`** (Total Commander):
  `Alt+Enter` is `show_explorer_properties` in Core and `Shift+Enter` is
  free; `Ctrl+Shift+Enter` is chosen as free and close to the convention.
  `Space` (TC "calculate under cursor") is `toggle_selection` here and is not
  changed.
- **Bind `Ctrl+Shift+P` directly to the toggle**: rejected; it must keep opening
  the Command Center. `Ctrl+Shift+D` provides a separate direct toggle through
  the same registered command, with ordinary user key-binding overrides.
- **Watching directories to invalidate the cache**: file watching is disabled
  on Windows in this fork (`StubFileSystemWatcher`); navigation/re-enable/manual
  recalculation is sufficient. No watcher or cache invalidation system is added.
- **Persisting sizes on disk** (Everything/WizTree style index): out of
  scope. The result dict lives only for the current scan.

## Runtime Effects

- Startup: register one column, four commands, one lightweight service and three
  key bindings; read `DirectorySize.json` once at first-pane attachment, after
  config layering. Disabled startup installs no pane
  callbacks/contributions and starts no worker, scan, timer or recurring I/O.
  No status label or startup notification is created. Toggle notifications reuse
  the existing status bar and its five-second expiry, with no feature-specific timer.
- Enabled: one metadata-only scan of direct child directories in the current
  local panes, each walk bounded by `max_entries`. Enable/navigation/Recalculate
  discards results and may repeat work, including in the unchanged pane. This is
  intentional. No file contents are read and no expensive validation pass runs.
- Results are queued at most every 200 ms plus the final flush. The model reloads
  only changed rows per batch; small completed directories appear before later
  directories finish and large directories show running subtotals. No recurring
  timer drives progress. Existing sorting cost still applies to each batch.
- Idle enabled: the executor may retain its one worker, without polling or I/O.
  Disabled: shutdown is requested immediately; after in-flight calls return the
  automatic worker is gone. Explicit tasks use existing command workers and do
  not turn automatic mode on.
- Memory: current displayed-directory results plus traversal stack and standard
  executor bookkeeping, not all previously visited locations. Repeated scans
  trade CPU/I/O for simpler ownership. Only settings and named widths persist.
- Off/reload/removal: cancel futures/events, disconnect callbacks, clear results
  and reject old deliveries without waiting on Qt. A retiring blocked OS call
  may briefly overlap re-enable/reload; it cannot publish stale data. No custom
  coordinator is added to prevent this harmless overlap.
- No new process, Registry writes, content verification, periodic filesystem
  scans or idle work when disabled. Root/descendant link checks are metadata
  correctness checks, not a sandbox or concurrent-modification guarantee.

## Settings

Code defaults for `DirectorySize.json`; optional user overrides belong under
`UserSettings/Plugins/User/Settings/DirectorySize (Windows).json`:

```json
{
  "enabled": false,
  "show_file_sizes": false,
  "max_entries": 200000
}
```

No Core settings are added or mutated. Invalid `DirectorySize.json` values
fall back individually to the defaults above: booleans must be booleans;
`max_entries` must be a positive integer (not a boolean). Size formatting follows the
existing `size_divisor` in `Status Bar.json`. Apply configuration at first-pane
attachment and through the toggle command. Restart after external edits; a full
service unload/reload also reads the settings again. The ordinary user plug-in
reload command does not unload this bundled service.

## Implementation Steps

1. Add the private service lifecycle with existing owner cleanup; test startup,
  partial-load failure, pane attachment and nonblocking reload/removal cleanup.
   Verify existing plug-ins do not acquire new lifecycle work.
2. Add owner-scoped extra columns, registered-name resolution and non-navigation
   model recreation. Verify preserved pane state and fallback when a column leaves.
3. Align width getter/setter and named session storage with legacy-list migration;
   verify cold-start restoration with the column enabled and disabled.
4. Add batched asynchronous row refresh and current/missing/stale row tests.
  Preserve filesystem notifications and thread boundaries; no status-bar hook
  or new status widget is needed.
5. Implement the pure incremental walker and simple executor controller with
  native temp-tree, intermediate-result, cancellation and stale-delivery tests.
6. Add the plug-in service, column, four commands, settings and three bindings;
  reuse the public status-message API for toggle notifications and register the
  plug-in in `build._environment()` before running its tests.
7. Add registered-command Qt and restart integration; check both toggle entry
  points, brief On/Off notifications, responsive navigation during a blocked
  scan, incremental rows/subtotals, explicit tasks and owner disposal.
8. Run the focused gates below and manual/performance checks. Put detailed usage
   in the plug-in README and a brief feature link in the main README; update the
   application changelog only when implemented. Record outcomes and move this
   canonical task to Done only after its required acceptance gates pass.

## Tests

Tests live in `fman_unittest.test_directory_size` and
`fman_integrationtest.test_qt.DirectorySizeIT`, with neighboring existing modules
covering shared lifecycle/model/session behavior. Write-capable plug-in tests use
a temporary plug-in copy so layered settings saves cannot modify bundled resources.
Run the smallest relevant case immediately after each implementation edit, then
the affected focused modules. Final gates from the repository root:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_unittest.test_directory_size', 'fman_unittest.impl.plugins.test_plugin', 'fman_unittest.impl.plugins.test_mother_fs', 'fman_unittest.impl.plugins.test_key_bindings', 'fman_unittest.impl.model.test_model', 'fman_unittest.impl.test_session', '-v'], env=build._environment()))"
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_integrationtest.impl.plugins.test_plugin', 'fman_integrationtest.test_qt.DirectorySizeIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

Required automated cases:

- Native nested/empty trees: exact logical bytes, distinct files/visited-entry
  counts, root and descendant symlinks/junctions, missing/inaccessible roots,
  per-entry errors, caps and partial results. Privilege-dependent symlink tests
  may skip explicitly; stub and native junction coverage must still run.
- Idle executor shutdown and active cancellation close scandir handles and never
  report an unfinished root as complete. Block a fake filesystem call behind an
  Event: Qt must still process a navigation command, an independent queued event
  and toggle-off before that Event is released. No timing-dependent sleeps.
- Navigation/recalculation restarts with an empty result dict. Revisited trees may
  be scanned again. Test stale generations, both panes at one location, failed
  navigation, closure and re-enable/reload while a canceled old call is blocked;
  old deliveries cannot alter new rows or emit toggle notifications.
- Pure walker emits a subtotal before completing a large root. A completed small
  root is visible while another remains blocked. Fake monotonic time verifies
  batch throttling/final flush; progress replaces subtotals rather than adding
  them twice. Many tiny roots do not generate one queued signal per file.
- Column methods never schedule/walk/wait. Repeated reads use only current results;
  mock file-content opens to fail during successful metadata-only calculation.
- Local-file option, non-local exclusion, skipped-link and error cells, unknown
  sort values and comparable keys in both directions; both size divisors.
- Both toggle paths resolve the same command; `Ctrl+Shift+P` still opens the
  palette, `Ctrl+Shift+D` toggles, custom bindings override normally, `Ctrl+F4`
  sorts only where the column exists. Both toggle paths call `show_status_message`
  with the correct On/Off text and `timeout_secs=5` after success. Persistence
  failure produces no success message; startup restoration/unload emits none.
  Verify normal message replacement/expiry, no extra status widget and no change
  to any extended status-bar mode.
- Explicit status results distinguish complete, capped, errored and skipped
  inputs, sum partial flags across roots and count files correctly. Cancellation
  never emits a completed total. Invalid selections get a concise alert. Explicit
  tasks remain independent of automatic mode and never emit a toggle notification.
- Optional-column unknown names are skipped without changing filesystem default
  fallback. Recreation preserves filters, hidden state, location/history, cursor,
  selection, sort and named widths; stale restoration cannot undo navigation.
- New async refresh works when initiated on Qt, reloads only supplied existing
  children in one transaction, rejects stale/missing rows and leaves notification
  callback semantics unchanged. Sorting partial values retains cursor/selection.
- Getter/setter round-trip for non-stretching widths; legacy full/two-width lists
  and named maps; cold restart enabled/disabled; removal/re-addition retains known
  widths without pretending the stretching last column has a persisted width.
- Service load/unload/reload/partial-load failure from supported host contexts:
  owner invalidation removes callbacks/contributions before column unregistration,
  cancels work and leaves no worker after blocked calls
  are released. Teardown itself never waits for those calls on Qt.
  Disabled startup/navigation/reload has zero calculator starts, scan calls and
  pane callbacks. Existing plug-ins without services behave as before.

Qt integration must use actual registrations, key dispatch, models and queued
completion, not just mock panes. Observe pending, running and completed cells
before the entire scan ends, navigation while walking, On/Off feedback, sorting,
disable, explicit tasks while disabled and reload cleanup.

Performance/manual gate: enable over a large temporary tree and record entry
count, time to first visible result, time to final result, refresh-batch count
and cancellation behavior. Revisit the tree to confirm recomputation is allowed.
Exercise both toggle paths, both panes, sort, restart persistence, status-message
notification/expiry and an explicit partial result. Confirm scrolling/navigation remain
responsive while values arrive. Do not add timing thresholds based on one machine; report
unavailable checks. No full suite, clean or freeze unless explicitly requested.

## Acceptance Criteria

- The column is absent and no automatic calculation runs until the user
  enables it; `Show Directory Size` remains available as an explicit action.
- `Ctrl+Shift+P` opens the Command Center; its toggle command and the direct
  `Ctrl+Shift+D` binding perform the same persisted application-wide toggle.
- After enabling, both panes show `Dir Size`; cells show `...` and fill in
  incrementally, including running subtotals for large roots, without blocking
  scrolling, navigation or loading. They do not wait for the entire scan.
- Either successful toggle produces a five-second On/Off status notification
  through the existing API, with no permanent label, new status hook or startup
  notification. Off removes the column and notifies without waiting for a scan.
- Walks are bounded, skip links and junctions, report errors and caps in the
  cell, and are cancelled for locations no longer displayed.
- Sorting by the column works in both directions without type errors.
- `Show Directory Size` works regardless of the column state.
- Caps/errors are visible in both cells and aggregate status messages; linked
  roots are not traversed or misreported as successful zero-byte directories.
- Disable/reload/removal cancels work and rejects stale results without blocking
  Qt. Once in-flight calls return, disabled steady state has no automatic worker,
  pane callbacks, scans or feature timer. Explicit tasks can still run while the
  column is Off.
- The design contains no cross-location cache, priority queue, request-sharing
  service or retirement coordinator. Recomputing results is an accepted tradeoff;
  responsiveness and understandable code take priority.
- Enablement and non-stretching named column widths persist across restarts;
  legacy session widths remain readable. The final column retains normal stretch.
- Public `fman` plug-in API remains compatible; the impl hooks are additive
  and introduce no extra lifecycle or column work for plug-ins not using them,
  apart from the explicitly tested pre-existing width-restoration fix.
- Focused unit/Qt, restart, disabled-path and performance/manual checks above
  pass before completion. Record exact commands, results and permitted skips.
  See Validation Results for the automated native smoke and explicitly unrun
  manual/release checks; those are not claimed as passes.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Initial design created. Identified that displaying a plug-in
  column requires a `columns` setting in Core and that single-row refresh
  needs `FileSystem.notify_file_changed` to reach parent-location callbacks;
  both proposed as small additive Core changes with a public-API-only
  fallback.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context window: Not exposed by host
- Outcome: Revised before implementation. Removed cross-plug-in Core settings
  mutation and global filesystem notification changes; specified owner-scoped
  optional columns, targeted row refresh, state-preserving model recreation,
  per-listener lifecycle tracking, and a fully stopped disabled path.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Needs revision before implementation. The separate column and
  metadata-only background walks are reasonable; lifecycle, shutdown, width
  persistence and partial-result contracts need the corrections below. No
  application code or earlier reviewer records were changed.

#### Findings

1. **P1: service and subscription ownership does not cover reload/removal.**
  The Listener section handles navigation, toggle-off and process exit only.
  [Plug-in unloading](../src/main/python/fman/impl/plugins/plugin.py#L225)
  unregisters classes/modules but does not stop arbitrary plug-in workers or
  release this service's subscriptions and column contributions. An old service
  can survive reload alongside its replacement. Also, an always-registered
  [ListenerWrapper](../src/main/python/fman/impl/plugins/plugin.py#L323) starts
  a thread per path event even while disabled. Define lifecycle-owned cleanup
  for workers, callbacks and contributions. Prefer the existing unsubscribeable
  [pane callbacks](../src/main/python/fman/__init__.py#L83), connected only while
  needed; serialize subscription changes and define ownership for overlapping
  explicit requests. Add reload/removal and disabled-navigation regressions.
2. **P1: idle-worker shutdown has no wake-up protocol.** The queue blocks
  without polling, but disabling only changes generation, clears pending work
  and joins. None of those releases a blocked `PriorityQueue.get()`. Specify a
  stop sentinel/wake-up for every worker, distinct from stale work, and test
  disabling with an empty queue. Remove the column on Qt before waiting for
  cooperative shutdown off Qt; the current join-before-removal order also
  contradicts immediate removal while a scan is busy. Cover active cancellation
  and re-enable only after the previous service has stopped.
3. **P2: the width fix still fails session restoration.** Returning
  `columnCount() - 1` widths does not match
  [set_column_widths](../src/main/python/fman/impl/widgets.py#L206), which requires
  exactly `columnCount()`. [Session loading](../src/main/python/fman/impl/session.py#L141)
  catches the resulting `ValueError` and silently discards restoration. Mapping
  names during live model recreation does not fix restart persistence. Align
  the getter, setter and saved format, including legacy two-width settings;
  distinguish the stretching last column from resizable persisted columns.
  Add enabled/disabled restart tests, not just live-toggle width tests.
4. **P2: descendant link checks do not exclude a linked walk root.**
  `entry.is_dir(follow_symlinks=False)` and entry junction checks run only after
  `os.scandir(root)` has opened the root. A selected/displayed junction therefore
  traverses its target, contrary to Scope and Acceptance Criteria. Check the
  root itself before scanning and define its display/on-demand result. A native
  temporary-junction probe confirmed this behavior; add root and descendant
  junction/symlink cases. This requires one root metadata check, not another walk.
5. **P2: Show Directory Size can present partial totals as complete.** Its
  prescribed status message omits `capped` and `errors`, including when several
  directory results are summed. Carry those flags into the aggregate display
  and tests. Also distinguish visited entries from files before labeling the
  count `files`, and explicitly reject/ignore non-local directory selections.
6. **P2: the refresh threading contract contradicts itself.** Impl Hook 3
  correctly requires a new asynchronous transaction, but Threading Summary
  routes completion back to `Model.notify_file_changed`. That method uses
  [a synchronous transaction](../src/main/python/fman/impl/model/model.py#L399),
  which asserts when called from Qt. Make every section target the new async
  operation and add a Qt-thread completion regression with stale/missing rows.

#### Validation And Test Gaps

- Source review covered model transactions, widget widths, session restoration,
  plug-in load/unload, listener dispatch and the existing pane callback APIs.
- Native root-junction probe passed; it used only a disposable temporary tree:

  ```powershell
  python -c "from tempfile import TemporaryDirectory; from pathlib import Path; import os, subprocess; fixture = TemporaryDirectory(); root = Path(fixture.name); target = root / 'target'; (target / 'marker').mkdir(parents=True); junction = root / 'junction'; subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(target)], capture_output=True, check=True); entries = list(os.scandir(junction)); assert junction.is_junction(); assert [entry.name for entry in entries] == ['marker']; fixture.cleanup(); print('Confirmed: os.scandir follows a junction supplied as the walk root.')"
  ```

- `test_directory_size` is proposed, not present. The Tests section should use
  the repository's `build._environment()` unittest launcher and a dedicated
  Directory Size Qt test class, rather than the entire `test_qt` module. Add the
  lifecycle, idle-stop, persistence, root-link and partial-result cases above.
- No application tests or full suite ran: this is a plan review, not an
  implementation. Markdown structure, local links and editor diagnostics are
  checked separately after appending this record.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Revised the operative design for implementation, addressing all six
  prior findings. Both toggle paths invoke one command: Command Center through
  its unchanged Ctrl+Shift+P binding, or direct Ctrl+Shift+D. Selected one worker,
  existing owner-based lifecycle cleanup, lazy pane callbacks, sentinel shutdown,
  named width persistence with legacy migration, root-link checks, partial-result
  reporting and an exclusively asynchronous row refresh. New host hooks and test
  IDs are explicitly planned, not existing. Previous reviewer records remain
  unchanged. This revision authorizes no application implementation by itself;
  implementation and its listed acceptance gates remain pending.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Revised for the user's simplicity and responsiveness priorities.
  Require a persistent Dir Size: On/Off status label, completed rows and running
  subtotals delivered in throttled batches, and no Qt/model wait for a walk.
  Removed TTL/LRU caching, shared-request ownership, priorities, custom queue
  shutdown and coordinated retirement. One standard automatic executor scans
  current locations afresh; explicit calculations reuse the command Task path.
  Repeated computation and briefly retiring canceled OS calls are acceptable.
  Kept owner cleanup, stale-generation checks, root-link handling, partial-result
  markers and state-preserving columns. Inspected existing status widgets,
  executor shutdown and owner invalidation to ground the revision. No application
  code changed; implementation and its unit/Qt/manual gates remain pending.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Applied the user's clarification: successful toggles produce a
  five-second On/Off notification through the existing show_status_message API,
  not a persistent label. Removed the proposed status-bar hook, widget lifecycle
  and startup feedback requirements. No-cache calculation, incremental results
  and nonblocking navigation remain unchanged. Earlier records are historical;
  this is a plan-only revision, with application implementation still pending.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed implementation against the no-cache, nonblocking design.
  Aligned settings with code defaults and first-pane initialization after config
  layering; preserved temporary notifications and the public plug-in API.
  Corrected cancellation classification, optional sort-name resolution after
  navigation and queued column restoration after native Qt deletion. Focused
  regression and native Windows smoke gates pass; unrun checks are listed below.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Revised for the user's explicit Core-only ownership requirement.
  No private plug-in-to-Core provider is approved. Move the feature into Core
  and reuse its existing Size column, preserving file behavior and the public
  API. Reviewer parent-fallback regression passes; migration and integration
  checks remain pending. Original records are retained as history.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Reviewed the user's final 10,000,000-file default and remaining
  standalone-column report. Use a distinct `max_files` setting rather than
  silently treating saved entry budgets as file budgets. Retain configurable
  caps and allow zero for unlimited scans; keep progress, cancellation and
  disabled behavior. Reject the obsolete bundled folder with a regression and
  verify full Core startup with legacy saved settings.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Reviewed the user's status-bar-only one-time workflow. Replace the
  root-count progress dialog instead of adding a percentage, preliminary scan
  or indeterminate dialog. Use the command worker and existing cancellation
  checks; serialize current-request ownership and status publication on Qt to
  prevent superseded or disposed scans from publishing. Automatic totals and
  the public API remain unchanged. Native blocked-scan checks pass.

## Implementer

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented the bundled column, four commands, three bindings,
  metadata-only incremental walker, one automatic executor and independent
  cancellable Task. Added private owner lifecycle, optional columns, asynchronous
  row refresh and named width persistence. Completed startup, cancellation,
  navigation and teardown regressions, plug-in usage, main README and Unreleased
  changelog. Final focused gate: 114 tests, 113 passed and one permitted skip;
  native Windows Qt: eight passed. No background exceptions in the final runs.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review; approved with one medium-severity follow-up.
  Independently re-ran the final focused gate: 114 tests, OK, one
  symlink-privilege skip (4.5 s). Verified against
  `Plugins/DirectorySize/directory_size/{__init__,calculator}.py`,
  `fman/impl/plugins/plugin.py`, `fman/impl/model/__init__.py`,
  `fman/impl/widgets.py` and `fman/impl/session.py`: the walker is
  metadata-only, iterative, rejects link roots before opening them, skips
  descendant links, re-raises `InterruptedError` ahead of `OSError`, checks
  cancellation per directory and every 256 entries, and throttles progress to
  200 ms without a timer; the controller owns one `ThreadPoolExecutor(1)`,
  a cancellation `Event`, a generation and a locked results dict, shuts down
  with `wait=False, cancel_futures=True`, never joins, and rejects stale
  generations in a queued `_Delivery`; results are cleared on every restart;
  disabled state has no executor, callbacks or contributions; both toggle
  paths call the public `show_status_message(..., timeout_secs=5)` only after
  `save_json` succeeds; `PluginService` is `start/on_pane_added/dispose` only;
  `set_extra_columns`, `refresh_files` and `column_widths_by_name` match the
  documented hooks. No public `fman` API change. Observations: (1) `restart`
  reloads every local pane on every navigation, including the pane that just
  loaded; accepted by the design's "simple, repeat work" rule, but reloading
  only the pane whose location did not change would halve listing work
  while enabled. (2) `_receive` reads `self._results` outside the lock;
  safe because all writers are on Qt. (3) `scan_parents` treats a symlink
  entry as a directory candidate; `walk_directory` then yields
  `skipped_link`, so file symlinks correctly show an empty cell.

#### Follow Up Tasks

- [ ] **Parent-result fallback shows the wrong size for nested panes.**
      `DirectorySizeService.result(url)` returns
      `results.get(key(url), results.get(key(dirname(url))))`. The fallback
      exists so children of an unreadable parent show `?`, but it applies to
      any parent entry. When the left pane shows `C:\A` and the right pane
      shows `C:\A\B`, `B` is a scanned child of `C:\A` and has a real result,
      so every row in the right pane displays `B`'s subtotal (and its final
      total) until that row's own result arrives; `B` is walked before its
      children because parents are processed in insertion order. Fix: apply
      the fallback only when the parent's entry is an error record
      (`size_bytes is None and errors`), or key parent errors separately.
      Add a unit test with two panes at `C:\A` and `C:\A\B` asserting the
      right pane's pending rows show `...`, not `B`'s size.

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Completed the Core-owned Size revision and resolved the reviewer's
  parent-result fallback follow-up. The historical unchecked item above records
  the review state at that time. Core now owns calculation, state, lifecycle and
  commands; no standalone plug-in or private cross-plug-in provider remains.
  The same Size column displays ordinary files in both modes and directory
  totals only while enabled. Preserved settings, command IDs, pane state and
  nonblocking no-cache scans. Added a shutdown guard after a late pane reload
  exposed a deleted-Qt-model update during validation. Final gate: 137 tests,
  136 passed and one expected symlink-privilege skip; ten native Qt tests passed,
  including two fresh full-application processes for startup and persistence.

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Removed the remaining standalone DirectorySize module and empty
  folders. Core defaults to 10,000,000 files per root, supports user overrides
  and zero for unlimited scans, and no longer uses legacy entry budgets.
  Clarified automatic two-pane totals versus selected-directory one-time totals.
  Focused native gate: 42 tests, 41 passed and one expected symlink-privilege skip;
  all 11 Qt tests passed, including two fresh full application processes.

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Removed progress-dialog creation from Show directory size. Added
  calculating/result status messages, status-only invalid-selection feedback,
  cancellation of previous one-time requests and rejection of late results.
  Updated registered-command and blocked-scan native tests, usage and changelog.
  Focused gate: 43 tests, 42 passed and one expected symlink-privilege skip;
  all 12 native Qt tests passed with no worker tracebacks.

## Validation Results

Final focused gate, run from the repository root:

```powershell
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_unittest.test_directory_size', 'fman_unittest.impl.plugins.test_plugin', 'fman_unittest.impl.plugins.test_mother_fs', 'fman_unittest.impl.plugins.test_key_bindings', 'fman_unittest.impl.model.test_model', 'fman_unittest.impl.test_session', 'fman_integrationtest.impl.plugins.test_plugin', 'fman_integrationtest.test_qt.DirectorySizeIT', 'fman_integrationtest.test_qt.SortedFileSystemModelIT'], env=dict(build._environment(), QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- 114 tests in 5.923 seconds: 113 passed, one skipped because Windows symlink
  creation requires unavailable privileges. Native root/descendant junctions
  passed. No elevated commands or package installation were attempted.
- An earlier nominally successful gate printed a deleted-Qt-model worker
  traceback. It was treated as a failure, fixed in the owning restoration
  callback and covered by `test_column_restore_ignores_deleted_widget` before
  rerunning. The final gate had no such exceptions.
- Write-capable registration/reload tests now use a disposable plug-in copy;
  the generated source override from the earlier test was removed. Persisted
  enablement is tested through reload and startup config-layer ordering.

Native Windows Qt source smoke:

```powershell
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_integrationtest.test_qt.DirectorySizeIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- Eight tests passed in 0.931 seconds. Actual key dispatch, both panes, running
  cells, sort direction/navigation, explicit progress/Cancel while Off, service
  unload/reload, startup enablement and session width restore are exercised.
- Existing message replacement/expiry is checked by emitting its timeout signal
  and asserting the real five-second interval. All extended status modes remain
  unchanged; no extra label is created. This does not wait five wall-clock seconds.
- The event-controlled scan stayed blocked while Qt rendered `3 B...`, navigated,
  disabled, re-enabled and disposed the owner. Workers ran outside Qt/model
  threads, stale results were rejected and both worker threads exited after
  release. Native test elapsed 0.027 seconds; no timing threshold is imposed.

Real-tree measurement (also included in the final focused gate):

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_unittest.test_directory_size.CalculatorTest.test_native_incremental_scan_sample', '-v'], env=build._environment()))"
```

- Disposable fixture: 20 directory roots, 6,000 regular files, 42,000 logical
  bytes. Two fresh scans returned all exact totals in two batches each. In the
  final gate each scan took 0.007 seconds; first worker delivery rounded to
  0.000 seconds at millisecond precision. Fixture setup/deletion is not included
  in those scan timings. These are worker measurements, not paint latency.
- Separate deterministic tests cover running subtotals, 200 ms batch throttling,
  final flush, caps/errors, metadata-only reads, cancellation and iterator closure.

Other checks and limits:

- Editor diagnostics: no errors in the changed Python, JSON or Markdown files.
  Parsed all three shortcut bindings and checked changed Markdown local links.
- Native automated smoke supplies repeatable workflow evidence; a human scrolling
  check, five-second wall-clock observation, cold full-application process restart
  and frozen/executable smoke were not run. Startup layering and session restore
  were exercised through the source integration harness, not a packaged restart.
- Full `python build.py test`, clean and freeze were not run, per repository policy.
  Git was unavailable on PATH; no commit, branch, tag or release operation ran.

### Core Size Revision Validation - 2026_09_17

Final focused command:

```powershell
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_unittest.test_directory_size', 'core.tests.fs.test_columns', 'fman_unittest.impl.plugins.test_plugin', 'fman_unittest.impl.plugins.test_mother_fs', 'fman_unittest.impl.plugins.test_key_bindings', 'fman_unittest.impl.model.test_model', 'fman_unittest.impl.test_session', 'fman_unittest.test_portable.PluginApiCompatibilityTest', 'fman_integrationtest.impl.plugins.test_plugin', 'fman_integrationtest.test_qt.DirectorySizeIT', 'fman_integrationtest.test_qt.SortedFileSystemModelIT'], env=dict(build._environment(), QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- 137 tests in 5.298 seconds: 136 passed, one expected Windows symlink-privilege
  skip. Native junction coverage passed. Includes Core's existing column tests,
  public API compatibility, the moved walker, lifecycle, model and session gates.
- Nested-pane regression: known parent subtotals, complete totals and known
  partial-error totals leave child directory cells pending. An unknown parent
  error gives `?`; a child's own result takes precedence and displays its bytes.
- Toggle preserves the same three columns, source-model identity, file sizes,
  filter, selected/cursor URLs, named widths and sort column/direction. No
  `set_extra_columns` call is permitted in the feature's toggle regression.
- A test-fixture binding cleanup omission was corrected to mirror the host's
  unload actions. A background reload completion after model shutdown was also
  treated as a failure despite passing assertions; its new guard and focused
  regression pass. The final runs have no worker tracebacks.

Final native Windows Qt command, after removing the retired plug-in directory:

```powershell
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_integrationtest.test_qt.DirectorySizeIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- Ten tests passed in 2.440 seconds. This includes two fresh application
  processes using disposable UserSettings: first startup enables directory totals;
  second startup restores On silently and toggles Off. Both use full Core
  registration, retain exactly Name/Size/Modified and keep ordinary file sizes.
- The blocked-scan case rendered a running subtotal, navigated, disabled,
  re-enabled and disposed the service before releasing the workers. Late results
  were rejected and workers exited after release; native case took 0.008 seconds.
- The 6,000-file, 42,000-byte fixture still completed two fresh scans with exact
  totals and two batches each (0.007 seconds per scan in the focused gate).
- Editor diagnostics and Markdown local links passed; each migrated Core key
  binding is unique. No stale standalone Python import or plug-in folder remains.
- Full source cold restart is now verified, superseding that earlier unrun item.
  Frozen/package tests, manual scrolling and wall-clock notification expiry were
  not run. No full suite, clean, freeze, package, Git or release operation ran.

### File Limit And Standalone Removal - 2026_09_17

```powershell
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_unittest.test_directory_size', 'core.tests.fs.test_columns', 'fman_integrationtest.test_qt.DirectorySizeIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- 42 tests in 5.798 seconds: 41 passed, one expected Windows symlink-privilege
  skip. All 11 native Qt tests passed, without worker tracebacks.
- A synthetic 200,256-file scan emits running results beyond the former cap and
  completes with the exact byte total. Small real trees verify file-only caps,
  exact-limit completion without `+`, unlimited mode, errors and cancellation.
- Settings tests verify the 10,000,000-file default, invalid values, custom and
  unlimited values, and ignored legacy `max_entries`. Qt config-layer testing
  verifies an explicit user limit reaches the scanner.
- Full native source startup and restart use legacy saved settings, restore the
  new default and persisted On/Off state, and retain exactly Name/Size/Modified.
  A separate regression rejects a bundled standalone DirectorySize folder.
- The 6,000-file native fixture still completes twice with exact totals and
  incremental batches (0.008 and 0.007 seconds). A real 10-million-file benchmark,
  manual scrolling, packaged/executable validation, full suite and freeze were
  not run. An already running application must restart with the updated source
  or build to unload the old column; no running user process was stopped.

### Status-Only One-Time Calculation - 2026_09_17

```powershell
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_unittest.test_directory_size', 'core.tests.fs.test_columns', 'fman_integrationtest.test_qt.DirectorySizeIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- 43 tests in 6.340 seconds: 42 passed, one expected Windows symlink-privilege
  skip; all 12 native Qt tests passed. No worker tracebacks.
- Registered `Ctrl+Shift+Enter` shows the full captured path before the scan
  and the final summary afterward while automatic totals are Off. Creating
  a progress dialog raises an assertion in this regression and is never called.
- A held-open scan verifies the actual status bar shows the calculating message
  without an expiry timer while Qt still services dispatch. Normal completion
  replaces it with the total. A newer calculation cancels the old one, and its
  result remains unchanged when the older worker returns. Disposal also cancels
  without waiting and prevents a late result from overwriting another message.
- Existing file-limit, metadata-only, cancellation, nested-pane, file-size,
  persistence and full source startup checks pass. No new dependencies, timers,
  executors or public API changes. Full suite, manual production-tree checks
  and frozen/package builds were not run.
