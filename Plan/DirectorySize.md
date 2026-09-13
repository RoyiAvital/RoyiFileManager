# Directory Size

## Task

Add a bundled `DirectorySize` plug-in that provides an optional `Dir Size`
column showing the total size of each directory's contents, inspired by
[jardous/directory_size](https://github.com/jardous/directory_size) (which
only shows one directory's size in the status bar on demand) and by Total
Commander's `Alt+Shift+Enter` "calculate occupied space". The column is off
by default and is switched on and off per application with a Command Center
command `Toggle Directory Size Column`. Sizes are computed in the background
and appear as they become available; the file list never blocks on them.

A second command, `Show Directory Size`, computes the size of the chosen
directories on demand and shows it in the status bar, so the reference
plug-in's behaviour remains available even when the column is disabled.

## Scope

Included:

- Column `directory_size.DirectorySize`, display name `Dir Size`, showing the
  recursive size of directories; files show an empty cell unless
  `show_file_sizes` is enabled.
- Placeholders: `...` while computing, `?` when the walk hit errors, a trailing
  `+` when the entry cap was reached (`1.2 GB+`).
- Sorting by the column: directories by computed bytes (unknown treated as
  `-1`), then files; the `is_dir ^ is_ascending` major key mirrors `core.Size`.
- Background computation on a dedicated plug-in worker with cancellation of
  work for locations no longer shown, per-URL cache with TTL, and explicit
  `Recalculate Directory Sizes` command.
- Column toggle persisted in settings; the toggle takes effect immediately in
  both panes.
- `Show Directory Size` status-bar command for the chosen directories.
- Reuse of the shared `format_size`/`size_divisor` from
  `fman.impl.status_bar` so the column, status bar and `Size` column agree.

Excluded:

- Sizes for non-`file://` schemes (`zip://`, `network://`, `drives://`) — the
  cell stays empty.
- Following directory symlinks or junctions.
- Persisting computed sizes across restarts.
- Showing allocated (cluster) size instead of logical size.
- Automatic recalculation on file changes made by other programs beyond the
  TTL and the existing activation reload.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
plug-in itself uses only public API (`Column`, `DirectoryPaneCommand`,
`DirectoryPaneListener`, `load_json`/`save_json`, `fman.fs`) plus one
documented import of the shared formatter. The dynamic column and targeted
row refresh require documented fork-specific impl hooks. These hooks are
additive and preserve existing behaviour when unused.

## Design

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
  normal view default. The hook performs Qt/model changes on the Qt thread.
3. **Refreshing one child row.** Add an impl-only
  `DirectoryPaneWidget.refresh_file(url)` hook. It no-ops unless
  `dirname(url)` equals the pane's current location, then forwards to a new
  `SortedFileSystemModel.refresh_file(url)` operation. That operation queues
  a new asynchronous model transaction which clears the URL's filesystem
  cache and reloads only that row; it must not call the existing synchronous
  `Model.notify_file_changed` transaction from the Qt thread. Do not change
  `FileSystem.notify_file_changed`: its exact-path callback contract remains
  intact, so ordinary filesystem notifications cannot be duplicated.
4. **Column widths persistence bug (pre-existing).**
   `DirectoryPaneWidget.get_column_widths` returns widths for columns
   `(0, 1)` only; with three columns the `Modified` width is already lost,
   with four the `Dir Size` width would be too. Change to
  `range(columnCount() - 1)` (the last column stretches). Width restoration
  currently rejects a length mismatch; dynamic recreation therefore maps
  widths by qualified name before calling the existing positional setter.

### Plug-in Layout `Plugins/DirectorySize/`

- `directory_size/__init__.py` — `DirectorySize` column, commands, listener.
- `directory_size/calculator.py` — pure-Python walk, cache, worker; no Qt.
- `DirectorySize.json`, `Key Bindings (Windows).json`, `README.md`.

### Column

`DirectorySize(Column)`:

- `get_str(url)`: if the scheme is not `file://` or the URL is not a
  directory (via the filesystem query cache) return `''`
  (or the file size when `show_file_sizes` is on). Otherwise look up the
  cache: hit → formatted size (with `+` when capped, `?` when errors);
  miss -> enqueue the directory and return `...`. The method performs no
  recursive I/O. Its `is_dir` query normally hits the model-warmed filesystem
  cache but may perform one stat when the row has not yet been loaded.
- `get_sort_value(url, is_ascending)`: `(is_dir ^ is_ascending, bytes)` with
  `bytes = -1` for unknown/pending directories so they sort together at the
  low end, and the file size for files when shown, else the lower-cased name
  as `core.Size` does for directories, keeping the tuple types comparable.
- Display name `Dir Size`.

`get_str` and `get_sort_value` run on the pane's model worker; they must stay
O(1). The cache is a dict guarded by a `Lock`; the queue is a
`queue.PriorityQueue`.

### Calculator

- One daemon worker thread per application (not per pane); a second one is
  optional via `worker_threads` (default 1, max 4) for SSDs.
- Work item: `(priority, generation, url)`. Priority is derived from current
  listener subscriptions. Generation is bumped by recalculation or disable;
  stale items are dropped when dequeued.
- Walk: iterative `os.scandir`, `entry.is_dir(follow_symlinks=False)` and
  not `is_junction()`, sum `entry.stat(follow_symlinks=False).st_size` for
  files (this comes from the directory listing on Windows — no extra syscall
  per file). Stop at `max_entries` (default 200 000) and mark the result
  `capped`. `OSError` on a subdirectory marks `errors=True` and continues.
  Every 2 000 entries check cancellation: the generation changed, or no pane
  remains subscribed to the directory's parent. A walk explicitly requested
  by `Show Directory Size` is independent of pane-location cancellation.
- Result: `DirSize(bytes, entries, capped, errors, computed_at)`, stored in
  the cache, then the service asks subscribed listeners to call the targeted
  pane refresh hook for that URL.
- Cache: `{url: DirSize}`; entries older than `cache_ttl_seconds` (default
  300) are treated as misses on the next `get_str` (recomputed lazily, the
  stale value is shown until the new one arrives). `Recalculate` clears the
  cache and bumps the generation. Memory: one small tuple per directory ever
  displayed; bounded by `max_cache_entries` (default 20 000, LRU by
  `computed_at`).
- Pending set: a directory already queued is not queued twice.

### Listener

Each `DirectorySizeListener` owns its current subscription. On construction
and `on_path_changed`, it compares the pane's current `file://` location with
its stored previous location, unsubscribes the previous value, and subscribes
the new one. It does not unsubscribe in `before_location_change`, because a
failed navigation leaves the old location displayed. Subscriptions are
reference-counted because both panes may show the same location. A result
callback refreshes only its live pane and only if the pane still displays the
result's parent. fman keeps its two panes for the window's lifetime, so there
is no independent pane-removal event; application exit is handled by
daemon-thread process shutdown, and disabling explicitly cancels and joins
the service. No bare module-level set can retain abandoned paths.

### Commands

- `ToggleDirectorySizeColumn` (`toggle_directory_size_column`, alias
  `Toggle directory size column`; Command Center only): flips
  `enabled` in `DirectorySize.json`, saves that file, and sets or clears the
  plug-in's `file://` extra-column contribution on every pane. Enabling
  creates the worker service lazily. Disabling increments the generation,
  rejects new automatic requests, clears pending work, cooperatively stops
  an in-flight walk at its next cancellation check, joins the worker, and
  then removes the column. The cache is retained for re-enabling within TTL.
- `ShowDirectorySize` (`show_directory_size`, alias `Show directory size`,
  default `Ctrl+Shift+Enter`; Command Center + binding): for the chosen
  directories, submit explicit work to the same service without blocking the
  Qt or model threads, then
  `show_status_message('<name>: 1.2 GB (12,345 files)')` for 5 s; multiple
  directories are summed into one result. Non-directories are ignored; if no
  directory is chosen, the command is hidden. Results also enter the cache.
  When the column is disabled, the service exists only for this request and
  exits after delivering the result.
- `RecalculateDirectorySizes` (`recalculate_directory_sizes`, alias
  `Recalculate directory sizes`; Command Center only): clears the cache,
  bumps the generation, and reloads both panes (`pane.reload()`) so cells
  fall back to `…` and are re-queued.
- `SortByDirectorySize` is visible only while the column is enabled and sorts
  by qualified name via `pane.set_sort_column`. The plug-in binding maps
  `Ctrl+F4` to this command; it does not assume a fixed column index.

### Threading Summary

- Column methods: pane model worker (one per pane), O(1), lock-guarded dict
  reads.
- Directory walks: plug-in daemon worker(s), pure `os` calls, no Qt.
- Row refresh: calculator completion -> subscribed listener -> pane refresh
  hook -> `Model.notify_file_changed`. The model transaction reloads one row;
  stale callbacks no-op after checking the current location and generation.
- Commands: command worker; Qt/model mutations are dispatched through the
  pane hooks' main-thread boundary. Settings writes use the config lock.
- Toggle off: the worker exits and is joined after cooperative cancellation;
  no parked feature-specific thread, timer, scan, or recurring I/O remains.

## Alternatives

- **Show directory sizes inside `core.Size`** (as Total Commander does)
  instead of a new column: fewer impl changes, but the user asked for a
  dedicated column and mixing makes "size of files only" sorting impossible.
  Rejected; could be a later `mode` setting.
- **Compute inside `get_str` synchronously** (reference plug-in style):
  blocks the model worker for seconds per directory and freezes row loading.
  Rejected.
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
- **Watching directories to invalidate the cache**: file watching is disabled
  on Windows in this fork (`StubFileSystemWatcher`); TTL + manual
  recalculate is the consistent choice.
- **Persisting sizes on disk** (Everything/WizTree style index): out of
  scope; TTL cache is enough for a file manager column.

## Runtime Effects

- Startup: registers one column, four commands, one listener, two key
  bindings and reads `DirectorySize.json` once. When `enabled` is false:
  no worker thread, timer, scan, or recurring I/O; no extra-column
  contribution is installed, so `get_str` is never called during listing.
- Enabled, steady state: one daemon worker blocked without polling when idle.
  Each newly displayed
  directory costs one queued walk (bounded by `max_entries`) and one
  single-row refresh. Walks of the *current* locations are prioritised;
  walks for locations the user has left are cancelled at the next 2 000-entry
  check.
- Memory: `max_cache_entries` × ~100 bytes, plus the pending set.
- Cancellation: generation counter and reference-counted subscriptions;
  disabling clears queued work, cooperatively stops the active walk, and
  joins the thread.
- Disabled path is a true no-op during listing: no contribution is installed,
  no worker exists, and no plug-in code runs from model column loading.

## Settings

`DirectorySize.json`:

```json
{
  "enabled": false,
  "show_file_sizes": false,
  "max_entries": 200000,
  "cache_ttl_seconds": 300,
  "max_cache_entries": 20000,
  "worker_threads": 1
}
```

No Core settings are added or mutated. Invalid `DirectorySize.json` values
fall back individually to the defaults above. Size formatting follows the
existing `size_divisor` in `Status Bar.json`.

## Implementation Steps

1. Impl: add owner-scoped, scheme-specific extra columns and registered-name
  resolution; force source-model recreation with state preservation; test
  unknown optional names and removal fallback.
2. Impl: add the targeted pane/model row-refresh hook without changing
  filesystem callback dispatch; test current, stale, and missing child URLs.
3. Impl: fix `get_column_widths` to all but the last column and restore widths
  by qualified name during column recreation; tests.
4. Plug-in `calculator.py`: walk, cap, subscriptions, cancellation, cache with TTL/LRU,
   worker, generation; unit tests with temp trees.
5. Plug-in column, listener, `ToggleDirectorySizeColumn`,
  `RecalculateDirectorySizes`, `ShowDirectorySize`, and
  `SortByDirectorySize`; settings and bindings.
6. Register the plug-in in `build.py`'s test path; README (plug-in and main),
   changelog.

## Tests

Focused validation commands:

```powershell
python -m unittest fman_unittest.test_directory_size
python -m unittest fman_integrationtest.test_qt
```

Unit tests (`fman_unittest/test_directory_size.py`, temp directories, no
Qt):

- Walk sums file sizes across nesting; a directory symlink and a junction
  are not followed; unreadable subdirectory sets `errors` and the rest is
  summed; `max_entries` sets `capped` and stops.
- Cancellation predicate stops a walk mid-way; a stale generation item is
  dropped without walking.
- Cache: miss enqueues once (no duplicate for the same URL), hit returns the
  value, TTL expiry re-enqueues while still returning the stale string, LRU
  eviction at `max_cache_entries`.
- Column: `get_str` returns `''` for files and non-`file://` URLs, `...` on
  miss, formatted value on hit, `+` suffix when capped, `?` when errors;
  `get_sort_value` orders pending directories together and keeps tuple
  types comparable across files and directories in both sort orders.
- Formatting agrees with `fman.impl.status_bar.format_size` for both
  divisors.
- Commands with `Mock` panes: toggle writes only `DirectorySize.json` and
  sets/clears every pane contribution; recalculate clears cache and refreshes;
  sorting uses the qualified column name; `ShowDirectorySize` message text
  covers one and several directories; no worker thread exists while disabled
  before and after an explicit one-shot request.

Core/impl tests:

- Extra columns are appended only for their configured scheme; unknown extra
  names are reported and skipped without changing filesystem defaults.
- Targeted refresh reloads one current child row and no-ops for stale or
  absent rows; existing `FileSystem.notify_file_changed` semantics are
  unchanged.
- Column recreation restores cursor, selection, filters, sort and widths by
  qualified name; removing the active sort column falls back to Name.
- `get_column_widths` returns `columnCount() - 1` values.

Integration (`test_qt`-style): enable the column, open a temp tree, assert
the cell shows `...` then the final size after the worker finishes; disable
and assert the column disappears and the worker is gone.

Manual: enable on a large tree (e.g. a `node_modules`), confirm the list
stays responsive and sizes fill in; navigate away and confirm the walk is
cancelled (CPU drops); `Ctrl+F4` sorts by size.

## Acceptance Criteria

- The column is absent and no automatic calculation runs until the user
  enables it; `Show Directory Size` remains available as an explicit action.
- After enabling, both panes show `Dir Size`; cells show `...` and fill in
  without blocking scrolling or loading; disabling removes the column
  immediately.
- Walks are bounded, skip links and junctions, report errors and caps in the
  cell, and are cancelled for locations no longer displayed.
- Sorting by the column works in both directions without type errors.
- `Show Directory Size` works regardless of the column state.
- The enabled state persists across restarts; column widths for all columns
  persist.
- Public `fman` plug-in API remains compatible; the impl hooks are additive
  and behave identically when no extra-column owner is registered.

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
- Model: Not exposed by host
- Effort: High
- Context window: Not exposed by host
- Outcome: Revised before implementation. Removed cross-plug-in Core settings
  mutation and global filesystem notification changes; specified owner-scoped
  optional columns, targeted row refresh, state-preserving model recreation,
  per-listener lifecycle tracking, and a fully stopped disabled path.
