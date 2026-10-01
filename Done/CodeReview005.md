# Code Review 005: fman Leftovers and Non-Windows Code

Status: Completed on 2026-10-01. All three phases, the approved native regression
follow-up, post-implementation and completion-review fixes pass their
focused gates. Full-suite and
freeze/package execution remain excluded; unverified limits are recorded below.

Completion review C1 was reproduced and fixed with additional bounded-date
regressions. See [C1 Resolution](#c1-resolution); the original
[Completion Review](#completion-review) is preserved below.

## Task

Remove code inherited from fman that no longer fits RoyiFileManager:

- macOS and Linux branches that never run, because startup is Windows-only.
- Telemetry, GitHub plug-in installation and stale fman texts that still run
  on Windows. The onboarding tours and shortcut dialogs stay functional.
- Legacy per-URL column methods that the snapshot pane no longer calls.

Motivation: reduce noise for maintainers, remove misleading user-visible behavior,
and let documentation describe only supported features.

## Scope

Included: the decided items in [Decisions](#decisions), their tests, resources
and the documentation that references them.

Excluded:

- Tutorial and Cleanup guide text and interactivity (kept verbatim).
- Unshipped developer tools in `src/misc` and `src/performancetest`, and `build.py`.
- The `requests` entry in `environment.yml` (Q10).
- The full `python build.py test` suite and freeze/package builds unless requested.

Compatibility: the public `fman.fs.Column` methods `get_str` and
`get_sort_value` are removed without a shim (Q7). `fman.PLATFORM` stays and is
always `Windows`. Commands, key bindings and settings files are unchanged except
the removed **Install plugin** command.

Policy note: this task supersedes the [Code Review 001](../Done/CodeReview001.md)
policy that Windows-only startup does not authorize removing non-Windows code.
Merging future upstream fman changes becomes harder; this is an accepted
fork-specific divergence.

### Why Group A Never Runs

- [main.py](../src/main/python/fman/main.py) raises on any platform other than
  `win32`.
- Configuration loads only generic and `(Windows)` variants, so `(Mac)` and
  `(Linux)` resources are never read. They are still packaged.

## Inventory

### Group A: macOS and Linux Code (Never Runs)

| ID | Item                   | Where                                                                      | Notes                                                                   |
| -- | ---------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| A1 | Core command branches  | `commands/__init__.py`                                                     | Mac/Linux file opening, volumes URL, Cut alert, `.app` tip, `Cmd` hints |
| A2 | Mac-only commands      | `commands/__init__.py`                                                     | `GetInfo` (AppleScript), `QuickLook` (`qlmanage`)                       |
| A3 | Core helpers           | `os_.py`, `trash.py`, `zip.py`, `goto.py`                                  | Linux terminal/explorer fallbacks, `rm -rf` trash, 7za paths, `/media`  |
| A4 | Host branches          | `application_context.py`, `clipboard.py`, `widgets.py`, `drag_and_drop.py` | Mac help menu, Linux `LD_LIBRARY_PATH` fix, GNOME clipboard, Mac keys   |
| A5 | Host Mac/GNOME modules | `mac.py`, `mac_clipboard_fix.py`, `icon_provider.py`                       | CoreServices, Mac clipboard fix, `GnomeFileIconProvider`                |
| A6 | Core resources         | `* (Mac).*`, `* (Linux).*`                                                 | 10 files; never loaded, still packaged                                  |
| A7 | Tests                  | `test___init__.py`, `test_goto.py`, `test_fileoperations.py`               | `PLATFORM == 'Linux'` branches and skips                                |

Effect today: no user-visible behavior. Cost is reading and review noise, and
the impression that the application is cross-platform.

Source files:

- Core: [commands/__init__.py](../src/main/resources/base/Plugins/Core/core/commands/__init__.py),
  [goto.py](../src/main/resources/base/Plugins/Core/core/commands/goto.py),
  [os_.py](../src/main/resources/base/Plugins/Core/core/os_.py),
  [trash.py](../src/main/resources/base/Plugins/Core/core/trash.py),
  [zip.py](../src/main/resources/base/Plugins/Core/core/fs/zip.py).
- Host: [application_context.py](../src/main/python/fman/impl/application_context.py),
  [clipboard.py](../src/main/python/fman/clipboard.py),
  [widgets.py](../src/main/python/fman/impl/widgets.py),
  [view/drag_and_drop.py](../src/main/python/fman/impl/view/drag_and_drop.py),
  `src/main/python/fman/impl/mac.py`,
  `src/main/python/fman/impl/mac_clipboard_fix.py`,
  [icon_provider.py](../src/main/python/fman/impl/model/icon_provider.py).
- Tests: [test___init__.py](../src/main/resources/base/Plugins/Core/core/tests/commands/test___init__.py),
  [test_goto.py](../src/main/resources/base/Plugins/Core/core/tests/commands/test_goto.py),
  [test_fileoperations.py](../src/main/resources/base/Plugins/Core/core/tests/test_fileoperations.py).

### Group B: fman Features Still Active on Windows

| ID | Item                       | Behavior Today                                        | Problem                                                      |
| -- | -------------------------- | ----------------------------------------------------- | ------------------------------------------------------------ |
| B1 | Tutorial                   | Auto-starts on first run; Command Center **Tutorial** | Teaches fman "type to jump"; typing now opens the Filter Bar |
| B2 | Cleanup guide              | Command Center tour for deleting files                | Same stale "type to jump" steps                              |
| B3 | Usage helper               | First-run alerts when the mouse is used               | Interruptive pop-ups with stale hints                        |
| B4 | Undefined-shortcut dialogs | Left, Right, F2, Ctrl+T open dialogs                  | F2 documented as unassigned; offers fman plug-ins            |
| B5 | Plug-in installer          | Downloads GitHub `fman` plug-ins and loads them       | Incompatible plug-ins; no integrity check; network access    |
| B6 | Zen of RoyiFileManager     | Shows fman's philosophy                               | Mentions auto-updates that do not exist                      |
| B7 | Disabled metrics           | Sends nothing; appends every event to `past_events`   | Unbounded list; only feeds B3 and B4                         |

Details:

- B1: first run means an empty `Session.json`, i.e. every fresh portable extraction.
- B4: Ctrl+T says tabs are "not yet supported". Dialogs write
  `UserSettings/Local/Dialogs.json`, offer fman's `ArrowNavigation` and
  `SwitchPanesWithArrowKeys` from GitHub, and "Other (please specify)" thanks
  the user for feedback that goes nowhere. [shortcuts.md](../docs/shortcuts.md)
  lists F2 as unassigned.
- B5: Install, Remove and List plugin. Install searches repositories tagged
  `fman` + `plugin` and loads the latest release or commit ZIP from
  `Plugins/Third-party`. fman filesystem and column plug-ins cannot work with
  the snapshot API. It is the only network access besides user-configured tools.
- B6: `ZenOfFman` states "Updates should be transparent and continuous".
- Compatibility of `ArrowNavigation` and `SwitchPanesWithArrowKeys` with the
  current API was not verified.

Source files: [tutorial.py](../src/main/python/fman/impl/onboarding/tutorial.py),
[cleanup_guide.py](../src/main/python/fman/impl/onboarding/cleanup_guide.py),
[usage_helper.py](../src/main/python/fman/impl/usage_helper.py),
[nonexistent_shortcut_handler.py](../src/main/python/fman/impl/nonexistent_shortcut_handler.py),
[commands/__init__.py](../src/main/resources/base/Plugins/Core/core/commands/__init__.py),
`src/main/resources/base/Plugins/Core/core/github.py`,
`src/main/python/fman/impl/metrics.py`.

### Group C: Legacy Column Methods (Partly Used)

| ID | Item                  | Where                                                                                  | Current Use                       |
| -- | --------------------- | -------------------------------------------------------------------------------------- | --------------------------------- |
| C1 | Legacy column methods | `fs.py`, `plugin.py`, `core/__init__.py`, ProcessPane                                  | Pane calls only `text` and `keys` |
| C2 | `DriveName.get_str`   | `drives.py`                                                                            | Builds drive labels during scan   |
| C3 | Parity tests          | `test_listing.py`, `test_directory_size.py`, `test_process_pane.py`, `test_columns.py` | Use legacy methods as oracles     |

C1 covers `get_str` and `get_sort_value`. C3 also includes the integration
plug-in test helper.

Source files: [fs.py](../src/main/python/fman/fs.py),
[plugin.py](../src/main/python/fman/impl/plugins/plugin.py),
[core/__init__.py](../src/main/resources/base/Plugins/Core/core/__init__.py),
[ProcessPane](../src/main/resources/base/Plugins/ProcessPane/process_pane/__init__.py),
[drives.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/drives.py),
[test_listing.py](../src/unittest/python/fman_unittest/test_listing.py),
[test_directory_size.py](../src/unittest/python/fman_unittest/test_directory_size.py),
[test_process_pane.py](../src/unittest/python/fman_unittest/test_process_pane.py),
[test_columns.py](../src/main/resources/base/Plugins/Core/core/tests/fs/test_columns.py).

## Decisions

User decisions from 2026-10-01. Details are in [Questions](#questions).

| IDs   | Item              | Recommendation                       | Decision                                  |
| ----- | ----------------- | ------------------------------------ | ----------------------------------------- |
| A1-A7 | Non-Windows code  | Remove in one task                   | Remove all macOS/Linux paths (Q6)         |
| B1    | Tutorial          | Remove                               | Keep all; remove macOS and telemetry (Q2) |
| B2    | Cleanup guide     | Remove                               | Keep all; remove macOS and telemetry (Q1) |
| B3    | Usage helper      | Remove                               | Keep; use minimal tour state (Q3)         |
| B4    | Shortcut dialogs  | Remove                               | Keep all choices; bind keys (Q4, Q9)      |
| B5    | Plug-in installer | Remove Install; keep List and Reload | Remove GitHub install; keep manual (Q5)   |
| B6    | Zen               | Rewrite                              | Remove the update line only               |
| B7    | Metrics           | Remove                               | Remove; minimal tour state only (Q3)      |
| C1-C3 | Legacy columns    | Follow-up after A and B              | Remove; no API compatibility (Q7)         |
| Tests | Obsolete tests    | Remove with their code               | Remove tests of removed code (Q8)         |

Notes:

- A1-A7 supersedes the Code Review 001 policy on non-Windows code.
- B1 and B2 keep their current text, including the stale "type to jump" steps.
  User docs should not describe the tours until they are revised.
- C1-C3 changes the public `fman.fs.Column` API without a compatibility shim;
  it needs a changelog migration note and a [PlugIn.md](../PlugIn.md) update.

## Questions

### Resolved

- **Q1: Onboarding scope.** Keep all tour functionality: Tutorial, Cleanup
  guide and Usage helper.
- **Q2: Tour cleanup.** Remove macOS branches and telemetry from the tours.
  Keep all interactivity: command hooks (`before_command`/`after_command`),
  location-change hooks, dialog-shown hooks and step buttons. Windows text and
  behavior stay identical.
- **Q3: Minimal tour state.** The Usage helper only needs to know whether the
  last event was `AbortedTour` (first time) or `CompletedTour`. Replace metrics
  with a small tour-outcome state: the last outcome, cleared by the next command
  or mouse action, plus an "aborted before" flag. No event list, no growth,
  no network code. All other `track()` calls are removed.
- **Q4: Undefined-shortcut dialogs.** Kept. Verified on Windows: the pane widget
  calls them when no binding matches Left, Right, F2 or Ctrl+T. "Don't ask again"
  is stored in `Local/Dialogs.json`. Remove the "Other (please specify)" choice,
  its text field and the "Thank you for your feedback" alert; nothing is stored.
  Four choices that offered GitHub plug-ins get key-binding offers; see Q9.
- **Q5: Plug-in installation.** Manual installation stays: copy a plug-in folder
  under `UserSettings/Plugins/Third-party/<PluginName>/`, then run **Reload plugins**. Remove
  `InstallPlugin`, `core/github.py`
  and every GitHub download path. Keep **Reload plugins**, **List plugins** and
  **Remove plugin**; drop the `ref` hint and `Plugin.json` writing that only
  Install produced.
- **Q6: Platform boundaries.** Accepted as proposed:
  - Keep the public `PLATFORM` constant (always `Windows`) and the `(Windows)`
    settings variants.
  - Keep the startup guard in [main.py](../src/main/python/fman/main.py) as a
    fail-fast check.
  - Make Windows branches unconditional (about 100 `is_windows()`,
    `PLATFORM == 'Windows'` and `skipUnless` sites, including POSIX path
    dispatch in [url.py](../src/main/python/fman/url.py)). Preserve forward-slash
    URL operations, `posixpath`, `PurePosixPath`, archive/virtual URLs and UNC paths.
  - Trim vendored [fbs_runtime/platform.py](../src/main/python/fbs_runtime/platform.py)
    to what remains used.
  - Exclude unshipped developer tools in `src/misc` and `src/performancetest`.
- **Q7: Column API.** Remove `get_str`/`get_sort_value` from the public `Column`
  base, `ColumnWrapper`, Core columns and ProcessPane. Migrate drive labels to
  snapshot data. No compatibility stubs.
- **Q8: Tests.** Delete tests that only cover removed code. Make Windows-only
  skips unconditional. Rewrite legacy-oracle tests to assert explicit expected
  values.
- **Q10: `requests` dependency.** Leave it in [environment.yml](../environment.yml)
  for now, even though only `core/github.py`
  uses it. Revisit separately.
- **Q9: Choices that offered a GitHub plug-in.** Keep every choice in the
  Arrow-Left and Arrow-Right dialogs. Four choices currently end in a GitHub
  install offer; replace each with the existing key-binding offer used by the
  other choices:

  | Dialog      | Choice                     | New offer                    |
  | ----------- | -------------------------- | ---------------------------- |
  | Arrow-Left  | Go to the parent directory | Bind Left to `go_up`         |
  | Arrow-Left  | Switch to the left pane    | Bind Left to `switch_panes`  |
  | Arrow-Right | Open the directory         | Bind Right to `open`         |
  | Arrow-Right | Switch to the right pane   | Bind Right to `switch_panes` |

  Right to `open` also opens files, not only folders. Choices are still shown
  only when they apply (for example, Switch appears only in the other pane).

### Open

None. Both reviews are incorporated; the user authorized implementation.

## Design

One plan, three phases, implemented in order A, B, C. Phases A and B edit some
of the same files (tours, shortcut handler), so they run sequentially. Each
phase has its own focused test gate.

### Phase A: Windows-Only Code

Rule: shipped code (`src/main`) and tests (`src/unittest`, `src/integrationtest`,
Core tests) have no OS dispatch. Windows branches become unconditional;
macOS/Linux branches are deleted.

Kept:

- The startup guard in [main.py](../src/main/python/fman/main.py).
- `fman.PLATFORM` and the `(Windows)` settings layering in `Config`.
- [fbs_runtime/platform.py](../src/main/python/fbs_runtime/platform.py) reduced
  to `name()` returning `Windows`; all other helpers deleted.

Removed, by area:

| Area          | Change                                                                                  |
| ------------- | --------------------------------------------------------------------------------------- |
| Host modules  | Delete `mac.py`, `mac_clipboard_fix.py`, `GnomeFileIconProvider`, `GnomeNotAvailable`   |
| App context   | Drop Mac help menu, Mac clipboard fix, Linux `LD_LIBRARY_PATH` block, non-Windows icons |
| Host widgets  | `widgets.py`, `view/__init__.py`, `quicksearch.py`, `key_event.py`, `context_menu.py`   |
| Host helpers  | `drag_and_drop.py`, `clipboard.py` (Linux MIME), `url.py`, `util/path.py`, `util/qt`    |
| Core          | Mac/Linux code in `commands/__init__.py`, `goto.py`, `os_.py`, `trash.py`, `zip.py`     |
| Core commands | Delete Mac-only `GetInfo` and `QuickLook`                                               |
| Plug-ins      | ProcessPane `sys.platform` check; QuickView visible with two panes                      |
| Resources     | Delete the 10 Core `(Mac)`/`(Linux)` JSON and CSS files                                 |

`MainWindow` loses its `help_menu_actions` parameter. `core.os_` keeps the
settings-driven terminal and Explorer launch and its "configure Core Settings"
alert; the `x-terminal-emulator`/`xdg-open` fallbacks go. `cut_files` no longer
has a `NotImplementedError` path.

Migrate every direct and `run_in_app` MainWindow caller, preserving behavior
assertions. Run the 12 Qt classes named in R1 and any further affected fixtures.
Also cover Windows clipboard MIME, drag/drop and prompt/message-box behavior.
Preserve privilege-dependent skips, not platform-only skips.

### Phase B: fman Features

**Tours (B1, B2).** Remove `is_mac()`/`is_windows()` branches; Windows strings
stay verbatim. `Tour`, `Tutorial` and `CleanupGuide` take `tour_state` instead
of `metrics`. Interactivity is unchanged: `CommandCallback` listeners
(`before_command`/`after_command`), `location_changed` hooks,
`AfterDialogShown` and step buttons.

**Telemetry (B7) replaced by `TourState`.** Delete
`fman/impl/metrics.py`. Add
`fman/impl/tour_state.py` with one class, guarded by a `Lock`:

| Member              | Behavior                                                         |
| ------------------- | ---------------------------------------------------------------- |
| `finished(outcome)` | Store `aborted` or `completed`; saturate abort count at 2       |
| `activity()`        | Clear last                                                       |
| `take()`            | Return `(last, aborts)`, then clear last                         |

At location-bar clicks, double-clicks and all context menus, `Controller` calls
atomic `take()` instead of `activity()`. It asks `UsageHelper` after releasing
the lock. Keyboard/Other context menus consume the outcome without a mouse hint.
Other former tracking sites use `activity()`: command start before listeners,
rename, drop, undefined shortcut, accepted dialog answer and tour step start,
including folder selection. The saturating count retains first/later-abort
behavior without unbounded growth.

`UsageHelper` (B3) keeps its rules on the new inputs: on first run, prompt to
restart the tutorial when last is `aborted` and aborts is 1; show keyboard tips
when last is `completed`. State is in memory for the session only, as today.
The application context provides one `tour_state` instead of `metrics`.

**Undefined-shortcut dialogs (B4).** Keep Left, Right, F2 and Ctrl+T handling,
"Don't ask again" and `Local/Dialogs.json`. Replace the GitHub offers with the
existing `_offer_to_customize_keybindings`:

| Choice                     | Pretext names | Offer                        |
| -------------------------- | ------------- | ---------------------------- |
| Go to the parent directory | Backspace     | Bind Left to `go_up`         |
| Switch to the left pane    | Tab           | Bind Left to `switch_panes`  |
| Open the directory         | Enter         | Bind Right to `open`         |
| Switch to the right pane   | Tab           | Bind Right to `switch_panes` |

Remove the "Other (please specify)" choice, its text field, event filter,
`get_other_text` and the thank-you alert.

**Plug-in installer (B5).** Delete `InstallPlugin`, `core/github.py`,
`_record_plugin_installation` and the `URLError` import. **List plugins** stops
reading `Plugin.json`. **Reload plugins**, **Remove plugin** and **List plugins**
stay. Existing third-party plug-ins and their `Plugin.json` files are left
alone and keep loading.

**Zen (B6).** Remove the line "Updates should be transparent and continuous".

### Phase C: Column API

- Remove `get_str` and `get_sort_value` from `fman.fs.Column`, `ColumnWrapper`,
  Core `Name`/`Size`/`Modified`, `NullColumn`, `DriveName` and ProcessPane `Pid`.
  Remove helpers and `fs` constructor parameters that become unused.
- Move the drive volume-label lookup from `DriveName.get_str` into
  `DrivesFileSystem`, called by `scan` on the worker. Labels stay identical
  (`C: Windows`, `Network...`).
- Extra legacy methods are harmless only when snapshot `text`/`keys` are
  implemented and no removed base/wrapper methods are called. Legacy-only
  columns are unsupported; no shim is retained.

### Documentation

- [PlugIn.md](../PlugIn.md): remove the `/Volumes` exception, the `cut_files`
  platform note and the legacy column sentence; state `PLATFORM` is `Windows`;
  note the Column API removal.
- [Core README](../src/main/resources/base/Plugins/Core/README.md): remove the
  macOS and Linux install paths.
- [shortcuts.md](../docs/shortcuts.md): F2 shows the rename suggestion; F12 is
  unassigned.
- [plugins/index.md](../docs/plugins/index.md): add manual installation: copy
  a plug-in folder to `UserSettings/Plugins/Third-party/<PluginName>/`, then run
  **Reload plugins**.
- Tours are not documented until their text is revised.
- [CHANGELOG.md](../CHANGELOG.md) Unreleased: Removed (GitHub installation,
  macOS/Linux code, telemetry, Column methods with a migration note), Changed
  (dialog offers, Zen), Documentation.

### Persistence and Failure

No migration. `Session.json` first-run detection, `Dialogs.json` flags, user key
bindings and third-party plug-ins keep their meaning. Key-binding offers reuse
the existing save-and-reload path and its error handling.

### Approved Native Follow-Up

The user explicitly authorized fixes outside the original cleanup for the three
native regression failures. No existing assertion was weakened:

- [OptionalDateInput](../src/main/python/fman/impl/ui/panel.py) disables Qt
  keyboard tracking so partially typed dates may cross the minimum-date
  boundary. Complete dates commit on Enter or focus loss; calendar selection
  and programmatic updates remain immediate. Tests give the editor real focus
  and cover leap/minimum/maximum dates with four fixed current-date seeds.
- [PanelForm](../src/main/python/fman/impl/ui/facade.py) reflows on field-label
  font/style events and releases old width constraints before measurement.
  Tests cover growth and shrinkage with aligned controls. Work stays on Qt's
  thread, only for an existing form; no worker, timer, I/O or persistence added.
- The DockedPanel regression now activates the main-window layout before
  measuring its baseline. A no-panel probe proved the initial two-pixel drift
  came from the status bar settling, not panel removal. The exact restoration
  assertion and production dock code are unchanged.

### Post-Implementation Review Follow-Up

The reviewer confirmed that a non-focusing Search button could submit a stale
date: keyboard tracking was off, and clicking that button did not cause focus
loss. The action boundary now commits each date editor with Qt's `interpretText`,
captures a fresh immutable snapshot and only then calls the action handler.
Change callbacks still run before the action; if they close the panel or invalidate
its owner, dispatch stops. Inactive panels do not read widgets or commit edits.
This preserves boundary-date entry and does not change tool-button focus policy.
Work is synchronous on the Qt thread, only when an active panel handles an action;
there are no added timers, workers, I/O or background jobs.

Native coverage uses the actual Search button without Enter or focus loss, both
date bounds, blank/existing values, leap/boundary dates and close-on-change.
The fixture selects the year section and verifies pending text before clicking;
silent programmatic resets also resynchronize the Search enabled state.

Removed orphaned `_get_local_filepaths`, both unused internal `get_user` helpers,
obsolete keyboard/graphics/installer imports and the ProcessPane platform mock.
Kept local filesystem provider imports required by discovery and re-exports.

### Completion Review Follow-Up

`OptionalDateInput.value()` exposes canonical, in-range pending ISO text to
snapshots and form validation. Incomplete or invalid text falls back to Qt's
committed date; blank values remain `None`. Text changes notify the existing
form callback, allowing both Start and End bounds to enable or disable Search
without Enter or focus loss. Qt keyboard tracking remains disabled, preserving
minimum-boundary entry. The existing action-boundary `interpretText`, snapshot
capture and close/invalidation checks are unchanged.

## Alternatives

- Keep metrics as a bounded event list: rejected; only two outcomes matter.
- Remove tours or shortcut dialogs: rejected by the user (Q1, Q4).
- Drop the four GitHub-offer choices: rejected; key-binding offers keep them useful (Q9).
- Keep `get_str`/`get_sort_value` as stubs: rejected by the user (Q7).
- Three separate task documents: rejected by the user; one plan, three phases.
- Remove `requests` now: deferred (Q10).
- Keep date validation on committed values until an action: rejected for C1;
  stale bounds can disable the action itself. Committing each keystroke instead
  would reintroduce the partial minimum-date rejection. Pending ISO values let
  validation update without forcing Qt's commit.

## Runtime Effects

- No new threads, timers, workers, I/O or settings.
- Memory: the per-session event list is replaced by two fields.
- Network: no GitHub installation or telemetry HTTP client remains. UNC and
  network providers remain supported; normal external documentation links stay.
- Startup: slightly fewer imports; no first-run behavior change.
- Drives listing: same volume-label calls, now made directly by `scan`.
- Package: ten Core resource files and `github.py` fewer.
- Approved follow-up: date snapshots/validation track valid pending ISO text;
  Qt commits on Enter, focus loss or an action. Parsing is bounded by the fixed
  date format, on the Qt thread. Notifications reuse existing change callbacks
  and preference saving; no new timer, executor or persistence mechanism exists.
  Field-label alignment recalculates on existing resize/font/style events.

## Tests

Use the bounded repository-environment launcher and exact module lists in
[Validation Results](#validation-results). Native Windows Qt is required for
the 12 MainWindow caller classes listed in R1, `WindowsCleanupIT`,
`SnapshotFilterBarIT` and the actual `SortedFileSystemModelIT` subclass; importing
its abstract fixture module alone does not collect the model tests.

Test changes:

- Delete tests that only cover removed code (Q8). Make Windows-only skips
  unconditional. Do not add tests that only prove a symbol is gone.
- `fman_unittest.impl.test_tour_state`: `finished`/`activity`/`take`
  semantics, bounded abort state, concurrent consumption and real
  Controller/CommandCallback wiring, including intervening commands and
  keyboard context menus. Preserve first-abort and completion hints.
- Extend `fman_unittest.impl.test_shortcuts`: the four choices map to
  `(key, command)` binding offers; the dialog has no "Other" choice.
- Update `test_app_name` for the new tour constructors.
- Rewrite `core.tests.fs.test_columns` on `keys(listing, ascending)` with
  `Listing.create`; replace the integration `StubDirectoryPaneWidget` legacy
  calls; turn parity assertions into explicit expected values.
- `core.tests.fs.test_drives`: labels from mocked drives and volume names.
- Native `WindowsCleanupIT`: Qt MIME payloads in isolated storage, drag actions,
  real dialogs and suppression. System clipboard/Explorer round-tripping is
  unverified after unsafe native backup/restore attempts; do not repeat them.
- `NativeWindowsCleanupTest`: fresh source application with temporary settings;
  automatic Tutorial, folder choice, Ctrl+P/F10 hooks, Cleanup steps, persisted
  Left/Right bindings including opening files, Filter Bar caret precedence,
  drive labels and actual metadata-free manual plug-in load/run/list/remove.

Static inventories (classify text matches against definitions, imports and AST):

```powershell
Get-ChildItem -Recurse src/main, src/unittest, src/integrationtest -Include *.py | Select-String -CaseSensitive -Pattern 'is_windows|is_mac|is_linux|is_gnome_based|is_kde_based|is_ubuntu|is_fedora|is_arch|linux_distribution|darwin|PLATFORM\s*[!=]=|sys\.platform|os_name'
Get-ChildItem -Recurse src/main/resources -File | Where-Object Name -match '\((Mac|Linux)\)'
Get-ChildItem -Recurse src/main -Include *.py | Select-String -Pattern '^\s*(from|import)\s+(requests|urllib|http|socket|ssl)\b'
Get-ChildItem -Recurse src/main, src/unittest, src/integrationtest -Include *.py | Select-String -Pattern 'get_str|get_sort_value|metrics\.track|past_events|fman\.impl\.metrics|core\.github|_track_current_step'
```

The startup guard and Windows-only test patch strings are legitimate matches,
not live non-Windows dispatch. Check aliased imports against the removed-symbol
inventory as well. Retain URL parsing, UNC providers, Qt font metrics and
unrelated performance metrics; those are not telemetry or installation clients.

Native smoke (isolated `ROYIFILEMANAGER_USER_SETTINGS`):

1. Empty settings: the Tutorial starts; the GoTo (Ctrl+P) and F10 steps react.
2. Abort the Tutorial, click the location bar: the restart prompt appears once.
3. Run Cleanup guide from Command Center; its first steps react.
4. Left/Right dialogs: no "Other"; each of the four choices offers its binding.
   Accept Left to `go_up` and Right to `open`; verify both. Type in the Filter
   Bar and press Right: the caret moves, nothing opens.
5. Command Center: no **Install plugin**; **Reload plugins**, **List plugins**,
   **Remove plugin** work; Zen has no update line.
6. Alt+F1: drive labels show volume names.

Package check: inspect source/resources and spec data only. Freeze/package
execution requires separate authorization and remains unrun for this task.

## Implementation Steps

1. Phase A: delete non-Windows code and resources; update tests; run the A gate
   and the first two static checks.
2. Phase B: add `TourState`, rewire tours, controller, command callback, handler
   and usage helper; delete metrics; update dialogs, installer and Zen; run the
   B gate and the network static check.
3. Phase C: move drive labels, remove Column methods, rewrite tests; run the C
   gate and the last static check.
4. Update documentation and `CHANGELOG.md`; run `python build.py doc`.
5. Native smoke; record results, skips and unrun checks.

## Acceptance Criteria

- Removed definitions, direct/aliased imports and resources are absent. The
  startup guard, Windows configuration layers and archive/virtual/UNC URLs remain.
- Phase A, B and C gates pass; symlink-privilege skips are listed.
- All affected native MainWindow fixtures pass with their assertions intact.
- Tours, the Usage helper and the shortcut dialogs behave as in the native smoke.
- **Install plugin** and all GitHub download code are gone; manual installation
  is documented.
- `python build.py doc` passes; changelog and docs match the behavior.

## Reviewers

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Inventory verified against source (definitions, call sites, startup
  guard, configuration loading and tests). Recommendations recorded; all
  decisions pending user review. No application changes.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Recorded user decisions. Raised Q1-Q8: onboarding scope, conflict
  between keeping the tutorial and removing OS branches/telemetry, tutorial
  event state, remaining shortcut dialogs, plug-in Remove/List, platform
  boundaries, Column API removal and test policy. Design blocked on answers.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Q5 resolved by the user: keep manual plug-in installation, remove
  all GitHub installation. Q1-Q4 and Q6-Q8 remain open.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Recorded user answers to Q1-Q4 and Q6-Q8. Verified that the
  undefined-shortcut dialogs run on Windows and that `github.py` is the only
  built-in network code. Raised Q9 (three dialog choices lose their action)
  and Q10 (`requests` dependency becomes unused).

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Q9 resolved: keep every Arrow-Left/Arrow-Right choice and replace the
  four GitHub offers with key-binding offers. Q10: keep `requests` for now.
  All questions resolved; design pending.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Wrote the three-phase design (A platform, B fman features with
  `TourState`, C Column API), runtime effects, phase test gates with verified
  module names, static checks, native smoke and acceptance criteria. "Other"
  dialog choice removal recorded. Ready for independent review; package check
  decision deferred until after review.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Accepted the recorded user decisions as scope, including Windows-only
  cleanup and the explicit Column API break. Requested the concrete design/test
  revisions below before implementation. No application code changed.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Source-only follow-up confirmed R1-R3 and the incomplete platform
  static gate. Keep revisions required; incorporate the findings into the main
  design and test gates before implementation. No application changes or tests
  rerun. Details are in Maintainer Review below.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Integrated R1-R3 and all boundary clarifications under the user's
  implementation authorization. Chose saturating abort state, preserved URL/UNC
  behavior, migrated live callers and expanded native/source workflow gates.
  Restored the two preceding reviews verbatim from editor history after the
  canonical document reverted to its six-record version during implementation.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User approved extending this task to resolve the three native
  date/layout failures. Runtime probes identified partial-date validation,
  missing label-font reflow and an unsettled test baseline. Accepted the focused
  fixes documented above; retained every existing behavioral assertion.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Post-implementation review. Static inventories clean; TourState,
  dialogs, installer removal, Zen, Column API, drive labels, docs and changelog
  match the design; independent offscreen rerun of the B/C gates plus URL and
  API-export tests: 313 run, one symlink skip. One regression in the approved
  date follow-up: with keyboard tracking off, a typed date is not committed when
  the icon-only Search button (a non-focusing `QToolButton`) is clicked, so the
  panel action receives the previous value; reproduced with a Qt probe. Also
  orphaned helpers/imports from removed branches. Follow-up fix required.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Confirmed the Search-click regression with a native failing test.
  Selected action-boundary date commitment with lifecycle checks, preserving
  the minimum-date fix and existing focus behavior. Verified orphan helpers
  and imports against included source/tests while retaining provider exports.
  The post-implementation findings are addressed by the follow-up below.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Completion review confirmed the earlier tour/path/test corrections.
  Fresh native focused baseline: 96 passed without skips. A new in-memory
  opposite-date-bound probe failed: valid pending text leaves Search disabled
  by the captured seed date. P2 follow-up required; application code unchanged.
  See Completion Review for the reproduction and validation limits.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Confirmed C1 with native tests for both bounds, including blank,
  valid and invalid existing values. Selected live pending-date snapshots while
  preserving Qt's deferred commit and action lifecycle checks. Kept the engine's
  unsupported local-time boundary rejection; no Search-enabling bypass added.

## Independent Review

### R1 (P2): Migrate and Test the Native MainWindow Callers

Phase A removes `help_menu_actions` from `MainWindow`, but
[test_qt.py](../src/integrationtest/python/fman_integrationtest/test_qt.py) still
constructs it directly in many widget/feature fixtures. The phase gates omit
this module entirely. Updating only the application-context constructor would
leave those fixtures passing an extra argument, while the listed gates could
miss the regression.

An AST/signature check found 21 incompatible calls in 12 existing classes:
`MainWindowIT`, `FilterBarIT`, `ProcessPaneIT`, `TextEditorIT`, `ComparatorIT`,
`FindFilesIT`, `SearchFilesIT`, `TableIT`, `HashResultIT`, `DockedPanelIT`,
`PanelIT` and `FavoritesManagerIT`. No excluded developer-tool dependency was
established by the caller search; the verified problem is in included tests.

Required revision: explicitly migrate every constructor caller and include
the affected existing Qt test classes in Phase A's focused gate. Retain their
behavior assertions; they are not obsolete Mac-only tests. Also cover Windows
clipboard copy/cut MIME behavior, drag/drop and ordinary prompt/message-box
behavior, since those implementations are being simplified in the same phase.
Use native Windows Qt for behavior that offscreen cannot validate.

### R2 (P2): Use One Discoverable Manual Plug-In Path

Q5 directs users to `UserSettings/Plugins`, but the Documentation section uses
`UserSettings/Plugins/Third-party`. Only the latter is the third-party discovery
root supplied by [application_context.py](../src/main/python/fman/impl/application_context.py#L72).
[find_plugin_dirs](../src/main/python/fman/impl/plugins/discover.py) enumerates
children of that root and the separate `User` root; it does not discover an
arbitrary plug-in placed directly below `Plugins`. `RemovePlugin` likewise
enumerates only `Third-party`.

Required revision: use `UserSettings/Plugins/Third-party/<PluginName>/` throughout
Q5, the implementation instructions and user documentation. Add a disposable
manual-install/Reload/List/Remove test that does not depend on `Plugin.json` or
any GitHub helper. Preserve existing User/Settings and third-party directories.

### R3 (P2): Specify Tour Outcome Consumption Order

The `TourState` paragraph requires `activity()` at the old mouse/context-menu
tracking sites and also requires `take()` at those sites. Calling `activity()`
first erases the outcome before `UsageHelper` can use it, breaking the promised
first-abort restart prompt and post-completion hint.

The current [Controller](../src/main/python/fman/impl/controller.py#L26) snapshots
history before tracking activity. A direct probe passed `['AbortedTour']` to the
helper while stored history became `['AbortedTour', 'ClickedLocationBar']`.

Required revision: make `take()` atomically read and clear the last outcome and
replace `activity()` at these consumption sites. Call `activity()` only at the
remaining old tracking sites, before command listeners where applicable. Release
the lock before any helper/dialog/listener callback. Test the real Controller
and CommandCallback wiring, not just a standalone state/decision table: first
abort, later aborts, completion, intervening command, repeated mouse action and
keyboard-triggered context menu. The latter consumes the outcome without a
mouse hint, matching the current behavior.

### Boundary Clarifications

- Keep POSIX-style URL operations that are live on Windows. Q6's mention of
  POSIX handling must mean removing OS dispatch, not deleting `posixpath`,
  `PurePosixPath` or generic URL tests merely because examples use `/`. Runtime
  probes on Windows returned `zip://C:/data.zip/folder` for an archive parent,
  `folder/item.txt` for its relative path and `zip://C:/data.zip/item.txt` for
  normalization. Add explicit archive/virtual/UNC URL parity requirements.
- Qualify Phase C's "Plug-ins that still define the methods keep working": this
  is true only when their active implementation already supplies snapshot
  `text` and `keys` and does not call removed super/wrapper methods. A legacy-only
  Column subclass raises `NotImplementedError` from both snapshot methods today.
  Keep the approved API removal; document its actual migration conditions.
- Narrow "no built-in network code" to no built-in GitHub installation or
  telemetry HTTP client. Retained drive/network providers and UNC file operations
  intentionally access network resources. No network-provider removal was
  approved. Keep ordinary external project/documentation links.
- Strengthen the static gate: its platform expression omits `is_windows`, despite
  removing that helper. Use the actual deleted-symbol inventory (including
  direct/aliased imports) rather than treating the current grep's empty output
  as sufficient proof. Retain legitimate Qt font metrics and unrelated
  performance metrics; these are not telemetry.
- Keep package verification explicit: no freeze/package is authorized by this
  review. Source/resource and spec-data checks can run during implementation;
  actual frozen validation remains separately authorized and must not be
  reported as passed without execution.

### Review Validation

This review changed only this task document, not application code, tests,
dependencies, resources, user settings or the changelog. The approved design
decisions above are preserved; the findings are requirements for a revision,
not an implementation or a new scope authorization.

Focused baseline, run from the repository root:

```powershell
@'
import build, subprocess, sys
modules = ['fman_unittest.test_url', 'fman_unittest.impl.util.test_path', 'fman_unittest.impl.onboarding.test_tutorial', 'fman_unittest.impl.test_shortcuts', 'fman_unittest.test_application_context', 'fman_unittest.test_listing', 'core.tests.fs.test_columns', 'fman_integrationtest.impl.plugins.test_discover', 'fman_integrationtest.test_qt.MainWindowIT']
environment = build._environment()
environment['QT_QPA_PLATFORM'] = 'offscreen'
sys.exit(subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'unittest', *modules, '-q'], env=environment, timeout=180).returncode)
'@ | python -
```

- Result: **119 passed**, no skips, in 0.394 seconds. Qt printed missing-default-
  font-directory warnings; this is not a native visual validation. The eventual
  Windows Qt launcher should set `QT_QPA_FONTDIR` to the existing Windows Fonts
  directory and keep a bounded subprocess timeout.
- Constructor probe: removed only `help_menu_actions` from the inspected Python
  signature and bound the AST call arguments without constructing widgets;
  21 call sites would fail argument binding.
- Disposable discovery probe: a direct `Plugins/DirectProbe` was not discovered;
  `Plugins/Third-party/ManualProbe` was discovered. No existing plug-in or user
  directory was modified and no plug-in was downloaded or executed.
- Read-only/isolated probes confirmed current tour event ordering, Windows
  archive URL results and legacy-only Column failure behavior described above.
- Document links and editor diagnostics passed. No full suite, actual native
  tour/clipboard/shortcut smoke, build, freeze, package or remote operation ran.

## Maintainer Review

Source-only follow-up on 2026-10-01. The independent review is sound. Its
requirements remain unresolved in the main Design and Tests sections:

1. **P2: Tour outcome consumption (R3).** The design requires both `activity()`
  and `take()` at mouse-action sites. Specify that `take()` replaces
  `activity()` there, matching the current
  [Controller](../src/main/python/fman/impl/controller.py#L26) ordering.
  Add real Controller wiring tests for intervening commands and keyboard
  context menus, not only a standalone state decision table.
2. **P2: MainWindow callers and Qt gates (R1).** Removing `help_menu_actions`
  changes constructor calls in
  [test_qt.py](../src/integrationtest/python/fman_integrationtest/test_qt.py).
  Explicitly migrate those callers and include the affected existing Qt
  classes in Phase A's focused gates.
3. **P2: Manual installation path (R2).** Q5 still says `UserSettings/Plugins`,
  but [discovery](../src/main/python/fman/impl/plugins/discover.py) uses the
  third-party and User roots separately. Use
  `UserSettings/Plugins/Third-party/<PluginName>/` consistently and test
  Reload/List/Remove without `Plugin.json`.
4. **P3: Incomplete platform static gate.** The platform expression omits
  `is_windows`, although that helper will be removed. Check the complete
  removed-symbol inventory, including direct and aliased imports.

Verdict: keep **revisions required**. Incorporate R1-R3 and the boundary
clarifications into the main design and test gates before implementation.
The approved scope and user decisions are unchanged.

Validation: inspected the task document and current Controller, UsageHelper,
metrics, shortcut handler/tests, application context and discovery code;
searched relevant callers and dependencies. No tests were rerun. The earlier
119-test result belongs to the independent review, not this follow-up.
Only this task document was edited to record the review.

## Implementer

### 2026_10_01 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented all three phases and the review corrections. Focused
  state/column tests, isolated native source workflows and strict documentation
  pass. The user-approved native follow-up passes the expanded 157-test gate.
  No required failures remain. No full suite, freeze/package or dependency changes.

### 2026_10_01 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Fixed deferred date commitment before panel actions, added Search
  click and close-during-commit regressions, and removed verified orphan helpers
  and imports. Follow-up gates: 159 native/UI tests and 154 focused utility,
  command, ProcessPane and source-smoke tests passed without skips. Existing
  reviewer/implementer history is preserved; no full suite or freeze/package ran.

### 2026_10_01 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Fixed C1 by publishing valid pending dates for validation. Added
  bounded-date and owner-invalidation regressions; retained action commitment,
  minimum-date coverage and true invalid-range rejection. Native completion
  baseline: 98 passed; engine checks: 24 passed and one expected symlink skip;
  strict docs build passed. Earlier review and implementation records remain
  unchanged, and the index points to this single completed task.

## Validation Results

### Results

Counts are per invocation and overlap; they are not unique-test totals.

| Gate | Result |
| --- | --- |
| Phase A | 642 run: 631 passed, 11 expected skips (115.006s) |
| Phase B | 161 passed (1.858s), including isolated native source workflows |
| Phase C | 115 run: 114 passed, one expected skip (5.666s) |
| Initial native callers + Windows behavior + snapshot model | 109 run: 106 passed, three failures (8.455s), resolved below |
| Final native callers + Windows behavior + snapshot models + UI contracts | 157 passed, no skips (13.176s) |
| Post-review native/UI gate, including new date/action regressions | 159 passed, no skips (13.276s) |
| Post-review orphan cleanup, utilities, commands, ProcessPane and source smoke | 154 passed, no skips (1.515s) |
| C1 focused date regressions | Four passed (0.627s) |
| C1 full native FindFiles fixture | 10 passed, no skips (1.304s) |
| C1 completion-review baseline with new regressions | 98 passed, no skips (1.317s) |
| C1 FindFiles unit/engine checks | 25 run: 24 passed, one expected skip (1.354s) |
| C1 strict documentation build | Passed (0.36s) |
| Final platform fixture cleanup | 142 passed, native Windows (2.517s) |
| Final local filesystem/watcher cleanup | 77 run: 73 passed, four symlink skips, native Windows (3.184s) |
| Initial three-test Fusion probe | All three failed (0.385s); style override was not a fix |
| Source/spec inventory | 217 Python files parsed; removed symbols/imports/aliases and resources absent; startup guard and portable Core spec path verified |
| Documentation/editor checks | Seven changed documents' local links pass; requested editor diagnostics report no errors |
| Source documentation screenshots | Existing generator produced 17 nonblank PNGs with isolated settings |
| Strict documentation build | Passed (0.38s) after generating the missing assets |

The final platform-helper gate also passed 113 tests after fixing a race in the
new source smoke: it now waits for the expected step's connected, visible screen,
not merely a worker-updated step index. Production tour transitions were unchanged.

Post-review validation: the Search-click reproduction failed before the fix;
the final regression covers eight valid pending edits while focus remains in the
date editor. A second test confirms that closing during date commitment prevents
action dispatch. Both pass, including in the 159-test native gate. All 217 included
Python files parse, removed orphan helpers have no references, and changed-source
editor diagnostics report no errors.

### Resolved Failures and Limits

- Native Qt: FindFiles date entry produced `1752-10-14` instead of `1752-09-14`;
  SearchFiles label width was 85 versus required 125, and DockedPanel restored
  height was 580 versus initial 582. All reproduce under native Fusion. A direct
  unchanged `OptionalDateInput` probe, without MainWindow, reproduced the date
  error with a `2026-10-01` seed but passed with `2026-09-20`. The two layout
  failures were investigated under the user's explicit follow-up authorization.
  Font reflow now responds to actual label changes; the dock fixture measures
  settled geometry. The exact failures and a new fixed-date matrix pass in the
  final native gate. No assertion was weakened.
- System clipboard preservation attempts produced COM teardown errors and an OLE
  restoration stack overflow. Automated tests now use real Qt MIME objects in
  isolated storage. Explorer clipboard round-tripping remains unverified; the
  system clipboard may contain the test value `preserved name`.

The initial strict docs build failed on six missing screenshots referenced by
the archive/tools pages. Running the existing source-only screenshot generator
resolved this prerequisite; no generator source or ignore rules changed.

### Commands

Run from the repository root, using the existing environment. The launcher sets
the Windows font directory, keeps a subprocess timeout and prints exact skips:

```powershell
function Invoke-FocusedTests {
    param([string[]]$Modules, [string]$Platform = 'offscreen', [int]$Limit = 180)
    python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']=sys.argv[1]; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); runner='import sys, unittest\nresult = unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:]))\nfor test, reason in result.skipped: print(\'SKIP:\', test.id(), reason)\nsys.exit(not result.wasSuccessful())'; sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-c',runner,*sys.argv[3:]],env=env,timeout=int(sys.argv[2])).returncode)" $Platform $Limit @Modules
    if ($LASTEXITCODE -ne 0) { throw 'Focused tests failed' }
}

Invoke-FocusedTests -Modules @('fman_unittest.test_url','fman_unittest.test_util','fman_unittest.impl.util.test_path','fman_unittest.impl.util.qt.test___init__','fman_unittest.impl.util.qt.test_key_event','fman_unittest.impl.plugins.test_context_menu','fman_unittest.test_application_context','fman_unittest.test_process_pane','fman_unittest.test_quick_view','fman_unittest.test_quick_view_text','fman_unittest.test_search_file_fuzzy','fman_unittest.impl.onboarding.test_tutorial','fman_integrationtest.impl.model.test___init__','fman_integrationtest.impl.plugins.test_config','fman_integrationtest.test_search_files_engine','core.tests.commands.test___init__','core.tests.commands.test_goto','core.tests.fs.test_local','core.tests.fs.test_zip','core.tests.test_fileoperations','fman_unittest.test_portable','fman_unittest.test_favorites','fman_integrationtest.impl.util.test_css') -Limit 240

Invoke-FocusedTests -Modules @('fman_unittest.impl.test_tour_state','fman_unittest.impl.onboarding.test_tutorial','fman_unittest.impl.test_shortcuts','fman_unittest.test_app_name','fman_unittest.test_application_context','fman_unittest.impl.plugins.test_plugin','fman_integrationtest.impl.plugins.test_discover','core.tests.commands.test___init__') -Limit 180

Invoke-FocusedTests -Modules @('core.tests.fs.test_columns','core.tests.fs.test_drives','fman_unittest.test_listing','fman_unittest.test_directory_size','fman_unittest.test_process_pane','fman_integrationtest.impl.plugins.test_plugin','fman_integrationtest.plugin_tests.test_directory_pane_listener') -Limit 180

Invoke-FocusedTests -Modules @('fman_integrationtest.test_qt.MainWindowIT','fman_integrationtest.test_qt.FilterBarIT','fman_integrationtest.test_qt.ProcessPaneIT','fman_integrationtest.test_qt.TextEditorIT','fman_integrationtest.test_qt.ComparatorIT','fman_integrationtest.test_qt.FindFilesIT','fman_integrationtest.test_qt.SearchFilesIT','fman_integrationtest.test_qt.TableIT','fman_integrationtest.test_qt.HashResultIT','fman_integrationtest.test_qt.DockedPanelIT','fman_integrationtest.test_qt.PanelIT','fman_integrationtest.test_qt.FavoritesManagerIT','fman_integrationtest.test_qt.WindowsCleanupIT','fman_integrationtest.test_qt.SortedFileSystemModelIT') -Platform windows -Limit 300

Invoke-FocusedTests -Modules @('fman_integrationtest.test_qt.MainWindowIT','fman_integrationtest.test_qt.FilterBarIT','fman_integrationtest.test_qt.ProcessPaneIT','fman_integrationtest.test_qt.TextEditorIT','fman_integrationtest.test_qt.ComparatorIT','fman_integrationtest.test_qt.FindFilesIT','fman_integrationtest.test_qt.SearchFilesIT','fman_integrationtest.test_qt.TableIT','fman_integrationtest.test_qt.HashResultIT','fman_integrationtest.test_qt.DockedPanelIT','fman_integrationtest.test_qt.PanelIT','fman_integrationtest.test_qt.FavoritesManagerIT','fman_integrationtest.test_qt.WindowsCleanupIT','fman_integrationtest.test_qt.SortedFileSystemModelIT','fman_integrationtest.test_qt.SnapshotFilterBarIT','fman_unittest.test_ui_elements') -Platform windows -Limit 300

Invoke-FocusedTests -Modules @('core.tests.fs.test_local.ListdirTest','core.tests.fs.test_local.WatchTest','core.tests.commands.test_goto','core.tests.commands.test___init__','fman_integrationtest.test_qt.SnapshotFilterBarIT') -Platform windows -Limit 90

Invoke-FocusedTests -Modules @('core.tests.fs.test_local','fman_integrationtest.test_qt.SnapshotFilterBarIT') -Platform windows -Limit 90

Invoke-FocusedTests -Modules @('core.tests.commands.test___init__','fman_unittest.impl.plugins.test_context_menu','fman_unittest.test_application_context','fman_integrationtest.test_qt.WindowsCleanupIT') -Platform windows -Limit 90

Invoke-FocusedTests -Modules @('fman_integrationtest.test_qt.FindFilesIT.test_search_click_commits_date_without_focus_change') -Platform windows -Limit 60

Invoke-FocusedTests -Modules @('fman_integrationtest.test_qt.FindFilesIT.test_search_click_commits_date_without_focus_change','fman_integrationtest.test_qt.FindFilesIT.test_date_commit_can_close_panel_before_search_action') -Platform windows -Limit 60

Invoke-FocusedTests -Modules @('fman_unittest.test_util','fman_unittest.impl.util.qt.test___init__','fman_unittest.impl.util.qt.test_key_event','core.tests.commands.test___init__','core.tests.commands.test_goto','fman_unittest.test_process_pane','fman_unittest.test_application_context.NativeWindowsCleanupTest','fman_integrationtest.test_qt.WindowsCleanupIT') -Platform windows -Limit 120

& { $previous = $env:QT_STYLE_OVERRIDE; try { $env:QT_STYLE_OVERRIDE = 'Fusion'; Invoke-FocusedTests -Modules @('fman_integrationtest.test_qt.FindFilesIT.test_controls_optional_bounds_validation_and_wrapping','fman_integrationtest.test_qt.SearchFilesIT.test_root_follows_invoking_pane_and_fields_align','fman_integrationtest.test_qt.DockedPanelIT.test_main_window_panel_geometry_close_and_replacement') -Platform windows -Limit 90 } finally { $env:QT_STYLE_OVERRIDE = $previous } }

python src/misc/generate_docs_screenshots.py --mode source
python build.py doc
```

Earlier local/native invocations used the same environment/timeout wrapper with
`-m unittest <modules> -q`; final A/B/C invocations used the skip-reporting runner.
The final 157-test invocation supersedes the initial 109-test native failure.
After the post-implementation review, the same native/UI command runs 159 tests
and passes with the two new regression methods. The focused follow-up commands
above record the failing reproduction, its fix and the orphan-cleanup gate.

### Expected Skips and Limits

- Phase A: nine tests cannot create symlinks without Windows privilege, plus
  the SearchFiles engine symlink test (ten total). The remaining skip is
  `FzfReferenceTest.test_all_extended_syntax_against_installed_fzf`, enabled only
  by `FZF_REFERENCE_TESTS=1`. No privileges were requested.
- Phase C: `CalculatorTest.test_root_symlink` skipped for Windows privilege.
  Local filesystem reruns contain four of Phase A's same symlink skips.
- Fixture output included a libpng read error, duplicate ZIP-name warning,
  7-Zip pipe progress and an explicit-operand flag diagnostic; no test failed
  because of those messages and no worker traceback remained in passing gates.
- Source smoke uses disposable settings and an actual locally created plug-in;
  no installed plug-in is removed or metadata rewritten. External Explorer/file
  launches are mocked. Human visual inspection and Explorer clipboard
  interoperability are not verified.
- No full suite, clean, freeze/package, environment/package installation or
  dependency removal ran. Source/spec checks do not establish frozen behavior.
  Git is unavailable, so no worktree diff/status verification is claimed.
- All required gates pass. The canonical task and index link move to Done and
  Completed; there is no Pending duplicate. Earlier failure evidence is retained.

## Completion Review

### C1 (P2): Valid Pending Date Bounds Can Leave Search Disabled

[OptionalDateInput](../src/main/python/fman/impl/ui/panel.py#L61) seeds an empty
editor with today's date and emits `value_changed` while keyboard tracking is
off. [FindSession.enable_form](../src/main/resources/base/Plugins/FindFiles/find_files/__init__.py#L153)
validates the captured date value, not the pending text. If today's date is
outside the opposite bound, it disables Search before the valid date is committed.
The [action-boundary fix](../src/main/python/fman/impl/ui/facade.py#L539) cannot
run when the Search button is disabled.

Native reproduction in a disposable `FindFilesIT` fixture:

1. Fix today's date to `2026-10-01`.
2. Set End to `2024-12-31` and leave Start blank. Search is enabled.
3. Focus Start and type `2024-02-29`, without Enter or focus loss.
4. The editor shows `2024-02-29`, but the panel snapshot contains Start
   `2026-10-01`. Search becomes disabled; clicking it dispatches zero actions.

This valid interval cannot be submitted through the intended Search-click path.
Enter or focus loss is a workaround. The existing Search-click regression clears
the opposite bound in every case, so it misses this failure.

Required follow-up: make valid pending date input eligible for Search without
reintroducing partial-date rejection. Preserve real invalid-range rejection,
action-boundary snapshots and close/invalidate-during-commit guards. Add native
coverage with a populated opposite bound for both Start and End, including
blank-to-value entry, correction of existing values and invalid intervals.
The Start case above is reproduced; the symmetric End case remains a test
requirement, not a claimed runtime observation.

### Validation and Verdict

Fresh focused baseline: **96 passed**, no skips, native Windows Qt, 1.369 seconds.
The new single-test in-memory reproduction failed its Search-dispatch assertion
in 0.296 seconds. An initial probe lacked Qt harness initialization and errored
before exercising the widget; the reproduced failure uses `_QtApp.start()` and
the normal worker/main-thread test dispatch with cleanup.

Exact baseline command, run from the repository root:

```powershell
@'
import os
import subprocess
import sys
import build
modules = [
  'fman_unittest.impl.test_tour_state',
  'fman_unittest.impl.test_shortcuts',
  'fman_unittest.test_url',
  'fman_unittest.test_ui_elements',
  'core.tests.fs.test_columns',
  'core.tests.fs.test_drives',
  'fman_integrationtest.test_qt.FindFilesIT',
  'fman_integrationtest.test_qt.PanelIT',
]
environment = build._environment()
environment['PYTHONDONTWRITEBYTECODE'] = '1'
environment['QT_QPA_PLATFORM'] = 'windows'
environment['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
raise SystemExit(subprocess.run([sys.executable, '-B', '-X', 'faulthandler',
  '-m', 'unittest', '-v', *modules], env=environment, timeout=180).returncode)
'@ | python -B -
```

The reproduction used the same environment with a 90-second subprocess bound,
an in-memory subclass of `FindFilesIT`, a mocked current date and an action spy.
It ran exactly the four steps above and asserted one Search action; actual
dispatch count was zero. No test file or application source was edited.

Verdict: the cleanup and earlier review corrections pass the focused baseline,
but the shared date follow-up still needs C1 fixed before completion approval.
Only this task document changed. Earlier review and implementation records are
preserved. No system-clipboard probe, full suite, documentation build, freeze,
package build, dependency installation or remote operation ran in this review.

## C1 Resolution

The new regression failed six subcases before the fix: both Start and End with
blank, valid or invalid existing values. It now verifies direct blank-to-valid
entry, populated opposite bounds, invalid intervals and valid corrections, with
today fixed to `2026-10-01`. Search clicks keep focus in the date editor and
receive the exact final bounds. Separate cases verify close and owner
invalidation during commitment suppress dispatch and reject later stale actions.

The older positive Search-click test now uses `2000-01-01` instead of
`1752-09-14`: the latter is accepted by the date widget but rejected by the
Windows search engine's local-time boundary check. That rejection remains;
the fixed-seed date-entry matrix still covers `1752-09-14`, leap dates and
`9999-12-31`. It was not appropriate to require Search dispatch for a date the
engine cannot represent.

Exact passing commands from the repository root:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.FindFilesIT.test_pending_date_bounds_update_search_eligibility','fman_integrationtest.test_qt.FindFilesIT.test_search_click_commits_date_without_focus_change','fman_integrationtest.test_qt.FindFilesIT.test_date_entry_is_independent_of_current_month','fman_integrationtest.test_qt.FindFilesIT.test_date_commit_can_close_panel_before_search_action','-q'],env=env,timeout=90).returncode)"

python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.FindFilesIT','-q'],env=env,timeout=120).returncode)"

python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest','fman_unittest.impl.test_tour_state','fman_unittest.impl.test_shortcuts','fman_unittest.test_url','fman_unittest.test_ui_elements','core.tests.fs.test_columns','core.tests.fs.test_drives','fman_integrationtest.test_qt.FindFilesIT','fman_integrationtest.test_qt.PanelIT','-q'],env=env,timeout=180).returncode)"

python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest','fman_unittest.test_find_files','fman_integrationtest.test_find_files_engine','-q'],env=env,timeout=180).returncode)"

python build.py doc
```

Counts overlap. The engine's `test_links_and_cycles` skipped because symbolic
links require Windows privilege; no elevation was requested. No full suite,
freeze/package, new dependencies or system clipboard operations were run for
C1. Historical gate results above are not claimed as rerun by this follow-up.
