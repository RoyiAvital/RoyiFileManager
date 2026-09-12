# Status Bar

## Task

Add an optional extended status bar directly to RoyiFileManager. It will show
useful information for both directory panes without replacing transient status
messages used for progress, warnings, and errors.

The feature has three layout modes, selected by configuration (the internal
values remain stable for compatibility):

- `Disabled` (`disabled`): no extended status information is shown.
- `Active pane` (`single`): one status area in the main window's status bar shows the
  information of the *active* pane only.
- `Per pane` (`dual`): each pane shows its own status footer directly below its
  file list.

The mode can be changed from the Command Center (`Ctrl+Shift+P` Command
Palette) using a `Toggle Extended Status Bar` command that cycles
`disabled -> single -> dual -> disabled`. The selected mode must persist across
application restarts and is saved immediately when changed. `Ctrl+S` invokes
the command, whose bindable identifier is `toggle_extended_status_bar`.

## Scope

This task adds optional active-pane and per-pane status summaries, immediate
mode persistence, hidden and selection state, visible entry counts, and file
size totals. It preserves transient status messages and the public `fman`
plug-in API. Recursive directory sizing, a separate process, and status work
while the feature is disabled are excluded.

## User Visible Behavior

For each pane, display:

- Whether the pane is active (`dual` mode only; in `single` mode the shown
  pane is by definition the active one).
- Whether hidden files are shown.
- Number of visible directories and files.
- Total size of visible files in the current directory. Show an ellipsis until
  all rows of the directory have been loaded by the model.
- Number and total size of selected files and directories when a selection
  exists. Selected directories are counted, not sized.

Locations whose filesystem does not provide sizes (`drives://`, `network://`,
`zip://`, ...) show counts and a dash for size. `null://` renders empty rather
than zeros.

Both panes must be initialized at startup. Status information must update after:

- Keyboard or mouse pane activation.
- Navigation and reload.
- Selection changes made with the keyboard or mouse.
- Showing or hiding hidden files.
- File operations that change the current directory.

When disabled, hide the extended status widgets and cancel pending calculations.
The ordinary transient status area must continue to work in every mode.

While a dialog or the quicksearch is open both file views lose focus. The
status must keep showing the *last focused* pane as active and never show "no
active pane".

## Design

Implement the feature in the main application rather than as a plug-in. Keep the
public `fman` plug-in API compatible by making any listener additions optional
and additive.

One reusable `PaneStatusWidget` renders the information of a single pane. It
is placed differently per mode:

- `single`: one instance is added to the main window's `QStatusBar` as a
  permanent widget, next to the transient message label, and is re-bound to
  whichever pane becomes active.
- `dual`: one instance lives inside each `DirectoryPaneWidget`, appended to
  its vertical `Layout` below the file view. This aligns each footer with its
  pane automatically, follows the splitter, needs no left/right glyph, and ties
  the widget's lifetime to the pane.

The transient message label stays in the main window's status bar in every
mode and is never touched by the extended status code.

`PaneStatusWidget` uses separate Qt labels for hidden-file state, directory
count, file count, and size. Use layouts and right-aligned numeric labels
instead of padding one string with spaces. This keeps alignment stable with
proportional fonts, Unicode text, DPI scaling, and changing values. The active
pane is marked with a dynamic style property (`active="true"`) so themes can
highlight it.

Expose pane state changes from the owning widgets:

- Pane activation: connect once to `QApplication.focusChanged(old, new)` in
  `MainWindow` and resolve the pane with `pane_widget.isAncestorOf(new)`. This
  covers keyboard, mouse, and location-bar clicks (the bar is a focus proxy)
  without overriding `focusInEvent` in every view. Remember the last focused
  pane so dialogs do not clear the active state.
- Selection: connect once to
  `QItemSelectionModel.selectionChanged(selected, deselected)`. Snapshot the
  selected URLs with the visible rows after the debounce. This avoids fragile
  running state across model resets, removed rows, and navigation.
- Directory contents: use `location_loaded` and `transaction_ended`, plus a
  new additive `Model.all_rows_loaded` signal emitted where
  `_load_remaining_files` determines that every row is loaded. Coalesce these
  triggers with a ~150 ms single-shot `QTimer`, since `transaction_ended`
  fires for every 0.2 s loading batch.
- Hidden files: Core's `_toggle_hidden_files` currently applies the filter
  *before* it writes `Panes.json`, so reading the JSON on a filter-changed
  signal would observe the old value. Add an optional
  `DirectoryPaneWidget.set_hidden_files_shown(bool)` (or signal) that Core
  calls at the *end* of `_toggle_hidden_files`. The status code must never
  read `Panes.json` itself.

Do not intercept or reimplement Core commands. The status implementation must
observe completed state changes, preventing the first-toggle failure present in
the reference plug-in. (That specific `ValueError` cannot occur here because
`InitHiddenFilesFilter` installs the filter at pane creation.)

## Alternatives

- A plug-in implementation was rejected because it would need private model
  access, duplicate command state, and fragile interception of hidden-file
  behavior.
- One padded status string was rejected because proportional fonts, DPI
  scaling, and changing values would make columns unstable.
- Performing counts and size queries on the Qt thread was rejected because
  large directories or slow filesystems could stall interaction.
- A separate process was rejected because Qt models cannot cross process
  boundaries safely and serialization/startup costs exceed this workload.
- A single application-owned worker was selected to serialize filesystem
  queries while immutable snapshots and generation checks protect the UI.

## Calculation Model

Do not re-walk the directory. On the Qt thread, snapshot immutable
`(url, is_dir, is_loaded, is_selected)` records from the stable proxy model.
Never pass `QModelIndex`, model objects, selections, or widgets to a worker.
Consequently:

- The Qt thread only copies plain row state and updates labels.
- A dedicated application-owned single-worker executor performs directory and
  file counts and every size query. Results return through a queued Qt signal.
- Until every visible row is loaded, show an ellipsis for total size.

Each pane owns a monotonically increasing generation identifier:

1. Increment the generation when its path, filters, contents, or the layout
   mode change.
2. Start a calculation for the new generation.
3. Discard results whose generation or path no longer matches the pane.
4. Cancellation is cooperative: the worker checks the generation every N
   entries. Disabling the feature or destroying the pane bumps the generation.

`max_entries` limits size queries per calculation. Display an explicit `+`
limited indicator when the cap is reached.

Selected sizes come from the same cache; selected directories are counted but
not recursively sized.

Use the model's visible rows rather than reimplementing hidden-file rules.
Filesystem errors, `NotImplementedError` from filesystems without sizes, and
files disappearing during calculation must be skipped without invalidating the
remaining summary.

## Runtime Effects

- `Disabled` creates no status widgets, executor, status timers, row snapshots,
  or recurring focus/model/selection listeners.
- Enabling the feature creates one single-worker executor for the application
  and one status widget per required display area.
- The Qt thread copies immutable row and selection state after a 150 ms
  debounce and updates labels; counting and size queries run on the worker.
- Memory use is proportional to the number of visible rows in the current
  snapshot. Only one calculation executes at a time.
- Size queries are capped by `max_entries`; cancellation tokens and generation
  checks discard obsolete work after navigation, mode changes, or shutdown.
- No directory is recursively walked and selected directories are never sized.

## Settings

Persist settings under `UserSettings` using the existing JSON configuration
mechanism (`Status Bar.json`). Initial settings:

```json
{
  "mode": "disabled",
  "max_entries": 5000,
  "size_divisor": 1024
}
```

`mode` is one of `disabled`, `single`, or `dual` and controls both visibility
and background work. `max_entries` limits size queries per calculation.
`size_divisor` selects binary (`1024`, units `KiB`/`MiB`) or
decimal (`1000`, units `KB`/`MB`) size formatting; unit labels must follow the
divisor. Invalid values fall back to defaults.

The toggle command writes the setting with `save_json` immediately (as Core
does for hidden files), not only on quit, so a crash does not lose the choice.

Share one size formatter between the status bar and the `Size` column so both
agree. Note that the current column picks the unit with `log(size, 1000)` but
divides by `1024 ** n` (1,000,000 B shows as "1.0 MB"); fix this while
introducing the shared formatter.

## Implementation Steps

1. Add the additive signals: `Model.all_rows_loaded`,
   `DirectoryPaneWidget.set_hidden_files_shown`, and the `focusChanged`-based
   active-pane tracking in `MainWindow`; call `set_hidden_files_shown` from
   the end of Core's `_toggle_hidden_files`.
2. Add the shared size formatter and switch the `Size` column to it.
3. Implement `PaneStatusWidget` (labels + layout) and the generation-aware
   summary calculator (immutable UI snapshots and worker-based counts/sizes).
4. Implement the three layout modes: placement in the status bar (`single`,
   re-bound on activation) or in each `DirectoryPaneWidget.Layout` (`dual`).
5. Add persistent settings and the `Toggle Extended Status Bar` application
   command to `BuiltinPlugin` next to `ToggleFullscreen`.
6. Wire the widgets in `MainWindow.add_pane` so startup needs no special
   handling; signals drive the first render.
7. Add theme selectors in `theme.py` (e.g. `.statusbar-pane`,
   `.statusbar-pane[active="true"]`) and defaults in Core's `Theme.css` and
   `Theme (Windows).css`.
8. Update the README and changelog after implementation.

## Tests

Unit tests (`src/unittest`, no `QApplication`):

- Size formatter for both divisors, including unit labels and the `Size`
  column agreement.
- Summary from a fake row list: counts, sizes with cached and uncached rows,
  `max_entries` indicator, `NotImplementedError`/`OSError` skipping.
- Selection totals for select, deselect, and clear.
- Generation mismatch discards a late result; bumping the generation stops a
  running calculation.
- Settings validation: unknown `mode`, non-numeric values, mode cycling order.

Integration tests (`src/integrationtest`, with `QSignalSpy`/`QTest`):

- Mode cycling through the command, immediate persistence, and restore on
  restart.
- Both panes render at startup in `dual`; the active pane renders in `single`.
- Mouse click and keyboard `Tab` both change the active pane; opening a dialog
  does not clear it.
- First and subsequent hidden-file toggles update the indicator and counts.
- Keyboard and mouse selection changes update selected totals.
- Directory reload, file operations, and `all_rows_loaded` update counts and
  replace the ellipsis with the final size.
- Rapid navigation publishes no stale result for the previous location.
- Transient messages remain independent of the pane information in every mode.

Manual check only (not automated): stable layout with proportional fonts,
Unicode text, and large values.

## Acceptance Criteria

- The feature is `disabled` by default, cycles modes through `Ctrl+Shift+P`,
  and has `Ctrl+S` as its direct shortcut.
- The mode survives application restart and is saved immediately.
- In `dual` both panes always show current information; in `single` the active
  pane does.
- Mouse interactions update status just like keyboard interactions, and
  dialogs never clear the active pane.
- Hidden-file toggling never requires command interception or reading
  `Panes.json`.
- Status alignment does not depend on a monospaced font.
- Counts never require I/O; size calculations do not block the UI or publish
  stale results.
- Disabled mode creates no status widgets, snapshots, timers, or worker jobs.
- Existing status messages, the `Size` column's values (apart from the unit
  fix), and public plug-in behavior remain unchanged.

## Reviewers

### 2026_09_12 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context window: Not exposed by host
- Outcome: Initial three-mode status-bar design created.

### 2026_09_12 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context window: 1M
- Outcome: Corrected model lifecycle, configuration ownership, worker split,
  disabled-mode overhead, and selection-accounting assumptions before implementation.

## Implementer

### 2026_09_12 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context window: Not exposed by host
- Outcome: Implemented all three modes, `Ctrl+S`, persistence, worker-based
  summaries, shared size formatting, styling, documentation, and tests.

## Validation Results

- Focused status calculation tests passed, including settings validation,
  formatting, cancellation, query limits, unsupported sizes, and selections.
- Focused model, Core command, and Size column tests passed after their
  respective changes.
- `python build.py test` completed with exit code `0`: 259 unit tests passed
  with one expected skip, 64 integration tests passed, and the Core suite
  passed.
- Offscreen application smoke tests cycled
  `Disabled -> Active pane -> Per pane -> Disabled`, confirmed executor
  teardown in Disabled mode, and restored `Active pane` after restart.
- Workspace diagnostics reported no errors. Git whitespace validation was not
  available because Git was not installed on the terminal `PATH`.
