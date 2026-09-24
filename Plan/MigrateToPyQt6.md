# Migrate to PyQt6

Status: Deferred. Implement only together with, or immediately before, the
QuickLook feature (see [Gains and Trigger](#gains-and-trigger)).

## Task

Move the application, bundled plug-ins, tests and packaging from PyQt 5.15 to
PyQt 6 while preserving the public `fman` Python plug-in API. Motivation: Qt 5
is out of upstream support, conda-forge's PyQt 5 builds lag new Python
releases, and the [TODO](../TODO.md) item `Move to PyQt6` is open. The
concrete functional driver is QuickLook, below.

### Gains and Trigger

Assessment on this codebase (2026_09_15):

- Performance: neutral. Hot paths (model worker, sorting, diff, Python
  delegates, `run_in_main_thread` round trips) are Python-bound; PyQt6 enum
  objects add a small cost in `data()` hot paths that the module-level
  constant binding already in use absorbs. See Runtime Effects.
- High-DPI: not a Qt 6 exclusive. Qt 5.14+ supports
  `AA_EnableHighDpiScaling` plus the `PassThrough` rounding policy today; that
  improvement can ship as a separate small Qt 5 task.
- Filesystem watching: not a Qt 6 exclusive. Qt 5.15 already contains
  removable-drive handling; reassess the Windows disable independently of
  migration (see [Windows Filesystem Watcher](#windows-filesystem-watcher)).
- Maintenance: open-source Qt 5.15 is end of life; Qt 6 receives the Windows
  font, IME, DPI and dark-mode fixes. Real but not urgent while conda-forge
  ships `pyqt 5.15` for the pinned Python.
- **QuickLook (the trigger):** the TODO items `Quick View`/`QuickLook-Win`
  need PDF, video and Markdown previews. PyQt6 bundles `QtPdf` and
  `QtPdfWidgets` (6.4+) and a FFmpeg-backed `QtMultimedia` with working
  Windows video playback; PyQt5 offers neither in a usable form, so a Qt 5
  QuickLook would need external viewers or extra native dependencies.
  `QTextDocument.setMarkdown` exists in both (Qt 5.14+).

Recommendation (accepted by the user): do not migrate for its own sake. Start
this task only when the QuickLook plan is approved and depends on `QtPdf` or
`QtMultimedia`; run it as the first implementation step of that feature so the
binding switch is validated before the viewer code is written. Other triggers
that would also justify starting it: a Python upgrade without a conda-forge
PyQt5 build, or a Windows rendering defect fixed only in Qt 6. Until then the
plan stays as the ready procedure.

## Scope

Included:

- Every `PyQt5` import under [src](../src) (56 files: host, `fbs_runtime`,
  bundled plug-ins, unit and integration tests, smoke scripts).
- Enum and flag usage, removed APIs, moved classes, `sip`, event positions,
  key combinations and dialog result handling (inventory below).
- [environment.yml](../environment.yml), `conda-lock.yml`,
  [application.spec](../application.spec), [build.py](../build.py)
  checks, README, PlugIn.md and CHANGELOG.
- Removal of dead non-Windows Qt code that has no Qt 6 binding
  (`QtMacExtras` in [mac_clipboard_fix.py](../src/main/python/fman/impl/mac_clipboard_fix.py)).

Excluded:

- Any UI redesign, theme rework, or replacing `tinycss`
  (separate TODO item).
- Supporting PyQt5 and PyQt6 at the same time in a release, or adding an
  abstraction dependency such as `qtpy`.
- Changing `fman.ui` semantics or the constrained-abstraction TODO item.
- Third-party plug-ins that import `PyQt5` directly; they are documented as
  breaking, not shimmed.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5 at the
Python level (names, arguments, return contracts). The Qt binding changes from
PyQt5 to PyQt6; plug-ins importing `PyQt5` must import `PyQt6`, and dialog
constants (`YES`, `NO`, ...) become `enum.Flag` members that still support
`|` and `&` but are no longer plain integers. This is a documented
compatibility note, not an API break of the fman contract.

## Design

### Inventory of Incompatibilities (verified by grep)

| Category | Occurrences | Files |
| --- | --- | --- |
| Unscoped enums (`Qt.Key_*`, `Qt.AlignLeft`, `QMessageBox.Yes`, `QStyle.SP_*`, `QAbstractItemView.MoveUp`, ...) | ~150+ host, many in tests | most of `fman/impl`, `fman/__init__.py`, plug-ins |
| `exec_()` | 4 | [application_context.py](../src/main/python/fman/impl/application_context.py), [qt_runner.py](../src/integrationtest/python/fman_integrationtest/qt_runner.py), [test_qt.py](../src/integrationtest/python/fman_integrationtest/test_qt.py) |
| `import sip` / `from PyQt5 import sip` | 6 | [model/__init__.py](../src/main/python/fman/impl/model/__init__.py), [model/drag_and_drop.py](../src/main/python/fman/impl/model/drag_and_drop.py), test_qt.py |
| `QVariant()` return values | 7 | [model/table.py](../src/main/python/fman/impl/model/table.py), [quicksearch.py](../src/main/python/fman/impl/quicksearch.py), [uniform_row_heights.py](../src/main/python/fman/impl/view/uniform_row_heights.py) |
| `QAction`, `QShortcut` from `QtWidgets` (moved to `QtGui`) | 6 | widgets.py, view/__init__.py, ui/panel.py, ui/table.py, Favorites `ui.py` |
| `event.pos()` / `event.globalPos()` on mouse/context events | 7 | view/__init__.py, view/drag_and_drop.py, ui/table.py |
| `Qt.CTRL + shortcut` (enum arithmetic) | 1 (mac only) | [widgets.py](../src/main/python/fman/impl/widgets.py) |
| `QKeySequence(modifiers \| key)` with `int` key, `int(modifiers)` | 2 | [key_event.py](../src/main/python/fman/impl/util/qt/key_event.py) |
| `event.reason() == event.Keyboard` | 1 | ui/table.py |
| `QFontDatabase.FixedFont`, `QFont.Bold`, `QPainter.CompositionMode_*`, `QPalette.Inactive` | several | ui/output.py, ui/facade.py, quicklist.py, table.py, application_context.py |
| `QtMacExtras` | 1 | mac_clipboard_fix.py (never imported on Windows) |
| Public button constants exposed to plug-ins | 7 | [fman/__init__.py](../src/main/python/fman/__init__.py) |
| Packaging | 3 | environment.yml (`pyqt=5.15.*`), spec (`PyQt5.QtSvg`), README |

Not affected: `QFileIconProvider`, `QFileSystemWatcher` (Windows stub kept),
`QSvgRenderer` (`PyQt6.QtSvg`), `QFontDatabase.systemFont` (already static),
`QDesktopServices`, `QLocale`/`QDateTime`, QSS files, `pywinpty`, `pywin32`,
`send2trash`, `tinycss`.

### Strategy: Two Source States, One Switch

1. **PyQt6-ready PyQt5** (suite stays green on 5.15): rewrite everything that
   PyQt5 ≥ 5.11 and PyQt6 both accept: fully scoped enums
   (`Qt.Key.Key_Escape`, `QMessageBox.StandardButton.Yes`), `exec()`,
   `None` instead of `QVariant()`, and route the few genuinely divergent
   points through one small compatibility module.
2. **Switch**: replace `PyQt5` with `PyQt6` in imports, flip the compatibility
   module branches, update environment/lock/spec, and fix whatever the probe
   and suite reveal.

This keeps every step independently testable and lets the diff of step 2 be
almost mechanical. Rejected alternatives are listed below.

### Compatibility Module

Add `fman/impl/util/qt/compat.py` (internal, not a plug-in API) that owns the
binding-specific differences:

- `QAction`, `QShortcut`: imported from `QtGui` when available, else
  `QtWidgets`.
- `sip`: `from PyQt6 import sip` / `from PyQt5 import sip`.
- `event_position(event)` → `QPoint`: `event.position().toPoint()` when the
  method exists, else `event.pos()`; `event_global_position(event)` likewise.
- `key_sequence(modifiers, key)` → `QKeySequence`: builds
  `QKeyCombination(modifiers, Qt.Key(key))` on Qt 6 and `modifiers | key` on
  Qt 5. Used by [key_event.py](../src/main/python/fman/impl/util/qt/key_event.py)
  and the mac-only shortcut in widgets.py.
- `flag_value(flag)` → `int`: `.value` for `enum` members, `int()` otherwise;
  used by `QtKeyEvent.__hash__`.
- `standard_button(result)` → `QMessageBox.StandardButton`: converts the
  `int` returned by `QDialog.exec()` so `show_alert` keeps returning a value
  that supports `& YES` and `== YES` for plug-ins.

The existing constant re-exports in
[util/qt/__init__.py](../src/main/python/fman/impl/util/qt/__init__.py)
(`Key_*`, `NoModifier`, `AlignRight`, ...) stay and are rewritten to scoped
names; they already centralize most key/modifier constants for the host.

### Enum Type Probe

Before step 2, run a probe script in the PyQt6 environment that prints the
base classes of every enum the code relies on arithmetically or compares
against integers: `Qt.ItemDataRole` (`Qt.UserRole + 1` in
[ui/table.py](../src/main/python/fman/impl/ui/table.py), role comparison in
`data()` overrides), `Qt.Key`, `Qt.KeyboardModifier`,
`QMessageBox.StandardButton`, `QDialogButtonBox.StandardButton`,
`Qt.SortOrder`. Riverbank documents enums as `enum.Enum` and flags as
`enum.Flag`; the probe confirms which are `IntEnum`/`IntFlag` in the pinned
version so `data()` role comparisons and custom roles are written correctly
(`Qt.ItemDataRole.UserRole + 1` vs `.value + 1`). The probe output is recorded
in Validation Results.

### Dialog Result Contract

`MainWindow.show_alert` ([widgets.py](../src/main/python/fman/impl/widgets.py))
returns `standard_button(self.exec_dialog(alert))`. `Task.show_alert` and
`ProgressDialog` follow the same path. Core call sites (`if choice & YES`,
`answer & YES_TO_ALL`) therefore keep working. `MessageDialog` in
[ui/session.py](../src/main/python/fman/impl/ui/session.py) already compares
against `QDialogButtonBox` buttons; it converts with
`QDialogButtonBox.StandardButton(result)` before comparing.

### High-DPI Policy

Current state (Qt 5.15): the application never sets
`AA_EnableHighDpiScaling`, so Qt scales only fonts (point sizes follow the
monitor's logical DPI). Everything specified in pixels stays at 1:1 device
pixels: the 28 px icon buttons and 16 px SVG icons in
[ui/facade.py](../src/main/python/fman/impl/ui/facade.py), the 24 px copy
button in [ui/output.py](../src/main/python/fman/impl/ui/output.py), the 22 px
dock close button in [ui/panel.py](../src/main/python/fman/impl/ui/panel.py),
delegate paddings and hand-painted rectangles. `devicePixelRatioF()` is 1.0,
so the existing SVG tinting code renders 16 device pixels at every scale; the
earlier 100/150/200 % validations accepted that mix.

Qt 6 enables logical scaling unconditionally. The remaining choices are the
rounding policy (`QGuiApplication.setHighDpiScaleFactorRoundingPolicy`, set
before `Application` is constructed, or `QT_SCALE_FACTOR_ROUNDING_POLICY`) or
opting out through `QT_ENABLE_HIGHDPI_SCALING=0`. Rounding applies to fonts
and pixels together, so only the opt-out can reproduce today's mix.

| Option | Factor at 125 / 150 / 175 / 200 % | Text | Pixel-sized widgets and icons | Mixed-DPI monitors |
| --- | --- | --- | --- | --- |
| A. Opt out (`QT_ENABLE_HIGHDPI_SCALING=0`) | 1 / 1 / 1 / 1; fonts still follow DPI | Scales | Stay small, exactly as today | Fonts re-scale per monitor, widgets do not |
| B. `PassThrough` (Qt 6 default) | 1.25 / 1.5 / 1.75 / 2 | Scales | Scale by the exact factor; SVG icons crisp via `devicePixelRatioF()`; raster icons resampled; possible 1 px seams in custom painting at odd factors | Exact per screen, no jumps |
| C. `Round` (Qt 5 `AA_EnableHighDpiScaling` behaviour) | 1 / 2 / 2 / 2 | Scales with the rounded factor | Crisp, integer | Jumps when a window crosses monitors |
| D. `RoundPreferFloor` | 1 / 1 / 2 / 2 | As C | Crisp | Jumps |
| E. `Floor` | 1 / 1 / 1 / 2 | As C | Crisp | Jumps |
| F. `Ceil` | 2 / 2 / 2 / 2 | As C | Crisp | Jumps |

Comparison:

- Fidelity to the current look: A is identical; B changes proportions at every
  non-100 % scale because controls grow to match text; C-F change text size,
  which users notice most.
- Correctness at the common Windows scales (125 %, 150 %): B is right at both.
  C is wrong at both (125 % renders as 100 %, 150 % as 200 %), D and E render
  150 % as 100 %, F oversizes every non-100 % display, and A keeps today's
  undersized controls.
- Rendering risk: A and C-F are integer factors with no fractional-pixel
  artefacts. B can expose off-by-one seams in hand-painted rectangles
  (`adjusted(1, 1, -2, -2)` in the QuickList and Table delegates, the splitter
  handle, status-bar backgrounds) and slight softness in resampled raster icons
  at 125/175 %; both are local fixes found by the manual DPI pass.
- Longevity: A relies on an environment override that Qt documents as legacy;
  B is the platform default and matches other Qt 6 applications on the
  machine.

Recommendation and decision (accepted by the user on 2026_09_15): **B,
`PassThrough`**. It is the only option that is correct at 125 % and 150 %,
it fixes the pre-existing undersized-controls flaw instead of carrying it
forward, it keeps SVG icons crisp with the code already in place, and it
handles mixed-DPI monitors without jumps. Its cost is a paint audit at
fractional factors, which the Tests section covers. Implementation sets
`QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)`
explicitly in `application_context.py` before creating `Application`, so the
choice is visible in code rather than inherited from the Qt default. Option A
is the documented fallback only if the audit finds artefacts the user does not
want fixed in this task; choosing it must be recorded here with the reason.
Options C-F are rejected.

### Windows Filesystem Watcher

Assessment on 2026_09_20: the
[local filesystem](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py)
uses `StubFileSystemWatcher` on Windows. Its comment records excessive
file/directory locks and blocked USB-drive ejection as the reasons. The stub
does no native watching; updates come from application file-operation
notifications, explicit refresh and
[application reactivation](../src/main/python/fman/impl/widgets.py).
External background changes can therefore remain unseen until refresh.

Verified upstream evidence:

- Qt added Windows removable-drive notifications on 2016-10-18, before Qt 6.
  The [upstream change](https://code.qt.io/cgit/qt/qtbase.git/log/src/corelib/io/qfilesystemwatcher_win.cpp?h=6.10&qt=grep&q=WM_DEVICECHANGE&showmsg=1)
  explicitly releases watched paths when Windows requests a volume lock for
  removal, allowing ejection.
- Both [Qt 5.15](https://code.qt.io/cgit/qt/qtbase.git/plain/src/corelib/io/qfilesystemwatcher_win.cpp?h=5.15)
  and [Qt 6.10](https://code.qt.io/cgit/qt/qtbase.git/plain/src/corelib/io/qfilesystemwatcher_win.cpp?h=6.10)
  contain the removable-drive listener. The
  [Qt 6.10 watcher](https://code.qt.io/cgit/qt/qtbase.git/plain/src/corelib/io/qfilesystemwatcher.cpp?h=6.10)
  releases watches for removal and restores them if the volume-lock request
  fails.
- Qt 6 has later fixes, including a
  [2021 watcher crash fix](https://code.qt.io/cgit/qt/qtbase.git/log/src/corelib/io/qfilesystemwatcher_win.cpp?h=6.10&qt=grep&q=crashes&showmsg=1)
  for invalidated `QHash` iterators. This is not evidence that every original
  locking problem is resolved.

Decision: keep the Windows stub during the binding migration. Its historical
justification may be outdated even on Qt 5.15, but re-enabling watching is a
separate behavior change, not a reason by itself to migrate. Source/history
review is complete; native notification, locking and USB-ejection tests have
not been run. Use the separate reassessment checks below before changing this
policy. Keeping the stub adds no watcher threads, handles, timers or I/O.

### Packaging and Environment

- `environment.yml`: `pyqt=6.*` (pin the minor that conda-forge ships for
  Python 3.14 once verified; PyQt6 uses `PyQt6-sip`, pulled automatically).
  Regenerate `conda-lock.yml` with the documented command.
- `RoyiFileManager.spec`: hidden import `PyQt6.QtSvg`; verify PyInstaller 6
  collects `Qt6Svg.dll`, `platforms/qwindows.dll` and `styles/` (Fusion is
  built in). Remove nothing else.
- `build.py`: no code path is Qt-specific; `QT_QPA_PLATFORM=offscreen`
  remains valid.
- Minimum OS becomes Windows 10 (Qt 6.5+). Note it in README.

### Removals

- `mac_clipboard_fix.py` and its `cached_property` in
  `application_context.py`: `QtMacExtras` has no Qt 6 binding. The app is
  Windows-only; deleting it removes an unreachable import.
- `disable_window_animations_mac` and other `is_mac()` branches stay; they are
  Python-only and harmless.

### Documentation

- [PlugIn.md](../PlugIn.md): state the Qt binding (PyQt6), that `fman.ui`
  widget components are PyQt6 objects, that dialog constants are Flag members,
  and update the example import (`from PyQt6.QtWidgets import QVBoxLayout`).
- [README.md](../README.md): replace the 5.15 constraint paragraph; mention
  Windows 10 minimum.
- [CHANGELOG.md](../CHANGELOG.md): `Changed` entry plus the compatibility
  statement below.
- [TODO.md](../TODO.md): tick `Move to PyQt6`.

## Alternatives

- **Big-bang rewrite directly to PyQt6**: fewer commits but no green
  intermediate state; every enum edit and every real incompatibility fail
  together. Rejected in favour of the two-state strategy.
- **`qtpy` (or a home-grown dual-binding layer) to support both bindings**:
  adds a dependency and permanent indirection; the project ships one binding.
  Rejected. The compatibility module is deliberately tiny and branches on
  attribute presence, not on a supported-binding matrix.
- **Automated tools (`pyqt5-to-pyqt6` style regex/AST converters)**: useful
  as a first pass for scoped enums, but they misplace `QAction`/`QShortcut`,
  cannot fix `int`/`Flag` arithmetic and would touch the public constants
  blindly. May be used locally for the enum pass; output must be reviewed and
  the suite must stay green.
- **Keep `int` results from `show_alert` and change Core to `==` comparisons**:
  breaks the documented plug-in contract (`buttons=YES | NO`,
  `choice & YES`). Rejected; the host converts once instead.
- **Wait for upstream fman to migrate**: upstream is unmaintained on this
  axis; UPSTREAM.md mergeability is already limited to Python-level changes.

## Runtime Effects

- Startup: Qt 6 DLLs are larger; expect a small increase in cold start and a
  larger frozen directory (measure before/after with `python build.py freeze`
  when the user asks).
- Steady state: no new threads, timers, I/O or scans. Fractional DPI scaling
  can change paint costs marginally.
- Memory: Qt 6 baseline is somewhat higher; no application-level change.
- Cancellation / disabled path: not applicable; the binding change has no
  feature toggle.
- Removed code (`mac_clipboard_fix`) only reduces import surface.

## Tests

Focused validation commands (run after each step; the full suite only on
request):

```powershell
$env:PYTHONPATH="src/main/python;src/unittest/python;src/integrationtest/python;src/main/resources/base/Plugins/Core;src/main/resources/base/Plugins/SearchFileFuzzy;src/main/resources/base/Plugins/Favorites;src/main/resources/base/Plugins/CalculateFileHash;src/main/resources/base/Plugins/SearchFiles"
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest fman_unittest.test_qt_binding
python -m unittest fman_unittest.impl.util.qt.test_key_event fman_unittest.impl.test_status_bar
python -m unittest fman_integrationtest.test_qt
python -m unittest fman_integrationtest.plugin_tests.test_key_bindings
python -m unittest discover -s src/main/resources/base/Plugins/Core -p "test*.py"
```

New unit tests (`fman_unittest/test_qt_binding.py`):

- AST scan of `src/**/*.py` asserts no `PyQt5` import remains and that
  `QAction`, `QShortcut`, `sip` are only imported through `compat`.
- `compat.standard_button(int(QMessageBox.StandardButton.Yes))` equals `YES`
  and `(YES | NO) & YES` is truthy, `(YES | NO) & CANCEL` is falsy.
- `compat.key_sequence(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_S)`
  matches `QKeySequence('Ctrl+S')` exactly; numpad `Enter` aliasing and
  `Num+Down` bindings from [Key Bindings.json](../src/main/resources/base/Plugins/Core/Key%20Bindings.json)
  still match through `QtKeyEvent.matches`.
- Probe assertions for the enum bases recorded during design (fail loudly if a
  future PyQt6 minor changes them).

Regression coverage reused unchanged: `test_qt.py` (QuickList, Panel, Table,
OutputTextBox, docked panel, Favorites manager), `test_key_event.py`,
`test_status_bar.py`, Core `test_fileoperations.py`, `test_portable.py`
(`PluginApiCompatibilityTest` asserts the public name list including
`OK`/`YES`/...).

Manual checks (record in Validation Results):

- `python build.py run`: startup, both panes, F1 shortcuts dialog, Ctrl+Shift+P
  palette, Ctrl+B Favorites (Tab/Shift+Tab dock bridging, Escape),
  Alt+F7 content search (Panel icons tinted, modal Table, Go To), Ctrl+H hash
  window centered, Ctrl+S status bar modes, context menus via mouse and
  keyboard, drag and drop between panes, `.lnk` and archive opening.
- Windows display scaling 100/125/150/175/200 % with `PassThrough`: icon
  buttons and SVG icons (28/16/24/22 px targets) scale with text, no 1 px
  seams in QuickList/Table delegate frames, splitter handle and status-bar
  backgrounds, elided labels, Quicksearch item rendering, resampled
  `QFileIconProvider` icons acceptable. Move the window between monitors of
  different scale and confirm no layout jump.
- Frozen build smoke only when the user asks for `freeze`: launch the
  packaged executable, confirm `QtSvg` icons render and 7-Zip/ripgrep paths
  resolve.

### Watcher Reassessment (Separate Follow-up)

These checks are prerequisites for a future re-enable decision, not migration
acceptance gates while the stub remains. Start with the installed Qt 5.15;
compare a pinned Qt 6 build only when available, recording exact versions.

- In a disposable directory, keep the watcher application active while a
  separate process creates, edits, renames and deletes files. Check native
  signals and, in an integration probe, cache invalidation and pane updates
  without an activation-triggered reload masking missed notifications.
- From the separate process, rename/delete watched files and a watched empty
  directory; confirm no access/sharing failures or hangs. Remove watches and
  close the probe; verify handles and watcher threads are released.
- On a disposable USB test drive, request safe ejection while watching it.
  Check successful removal and loss-of-path handling; where safely
  reproducible, check that failed ejection restores notifications. Record
  unavailable hardware or untested cases explicitly, not as passes.

## Implementation Steps

1. Add `fman/impl/util/qt/compat.py` with the helpers above (PyQt5 branch
   active) and `test_qt_binding.py` for the helpers; run it.
2. Rewrite `fman/impl/util/qt/__init__.py` constants, `key_event.py`,
   `widgets.py`, `view/*.py`, `ui/*.py` to scoped enums, `compat` imports,
   `event_position`, `exec()`, and `None` instead of `QVariant()`. Run
   `test_key_event`, `test_qt`, Core tests.
3. Rewrite remaining host modules (`application_context.py`, `quicksearch.py`,
   `shortcuts.py`, `nonexistent_shortcut_handler.py`, `status_bar.py`,
   `model/*.py`, `clipboard.py`, `fman/__init__.py` with
   `standard_button` in `show_alert`), plug-ins (Core, Favorites,
   CalculateFileHash, SearchFileFuzzy) and tests/smoke scripts to scoped enums.
   Run the focused set; the suite must stay green on PyQt5.
4. Delete `mac_clipboard_fix.py` and its context property.
5. Ask the user to create/update the conda environment with `pyqt=6.*`
   (no package installation by the agent). Run the enum probe and record
   results; adjust `compat` and role arithmetic accordingly.
6. Switch imports `PyQt5` → `PyQt6` across `src`, flip `compat` branches,
   set the `PassThrough` rounding policy explicitly, update
   `RoyiFileManager.spec` hidden import. Run the focused set and fix residual
   failures.
7. Update `environment.yml`, regenerate `conda-lock.yml`, update README,
   PlugIn.md, CHANGELOG, TODO.
8. Manual UI and DPI checks at 100/125/150/175/200 %; fix seams or icon
   sizing found by the audit; record outcomes. Frozen build only on request.

## Acceptance Criteria

- No `PyQt5` import remains under `src`; `test_qt_binding` passes.
- All focused tests listed above pass under PyQt6 in the conda environment.
- `python build.py run` starts and every manual check passes at 100 %, 125 %
  and 150 % scaling under `PassThrough`, with any accepted visual difference
  noted; 175/200 % are checked and deviations recorded.
- `show_alert(..., YES | NO) & YES` semantics work from Core and from the
  Simple Plugin test resource.
- `environment.yml`, `conda-lock.yml`, spec, README, PlugIn.md, CHANGELOG and
  TODO reflect PyQt6; CHANGELOG carries the compatibility statement:
  `API compatibility: Preserves the public fman plug-in API from fman 1.7.5;
  the Qt binding is now PyQt6, so plug-ins importing PyQt5 must switch to
  PyQt6 and dialog constants are enum.Flag members.`

## Reviewers

### 2026_09_15 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Designed a two-state migration (PyQt6-ready PyQt5, then a
  mechanical switch) with a minimal internal `compat` module, an enum-type
  probe gate, explicit dialog-result and high-DPI policies, and a documented
  binding-change compatibility note. Open questions for the user: conda-forge
  availability of PyQt6 for Python 3.14, and acceptance of `PassThrough`
  DPI scaling as the default.

### 2026_09_15 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: User will provide the PyQt6 conda package. Compared the six
  high-DPI options (opt-out and the five rounding policies) against the
  current fonts-only scaling; user accepted the `PassThrough` recommendation.
  Recorded the decision, the explicit policy call, the widened 125/175 %
  audit and the opt-out fallback rule.

### 2026_09_15 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Assessed the gains: performance neutral, high-DPI achievable on
  Qt 5, maintenance benefit real but not urgent, QuickLook (`QtPdf`,
  `QtMultimedia`) the only concrete functional driver. Marked the task
  Deferred; recommended and user accepted implementing it only with the
  QuickLook feature.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Documented the Windows watcher disable and upstream removable-drive
  handling already present in Qt 5.15. Kept the migration's stub policy;
  specified separate notification, locking and USB-ejection checks before
  reconsidering it. Runtime watcher behavior remains unverified.
