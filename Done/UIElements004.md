# UI Elements 004: QuickCheckList

## Task

Provide a reusable, Qt-free UI element to set a **state per item** over a fixed
list, such as file attributes or favorite flags. Keep the compact, buttonless
QuickSearch look and interaction: the user cycles item states, then approves with
<kbd>Enter</kbd> or <kbd>Shift</kbd>+<kbd>Enter</kbd>, or cancels with <kbd>Esc</kbd>.

QuickList cannot serve this: it shows no state indicator, and its Enter falls back
to the current item, so it cannot express "no change" or a non-binary state.
The first consumer is [File Attributes Editor 001](FileAttributesEditor001.md).

## Overview and Concept

### API

```python
from fman.ui import CheckListItem, show_quick_check_list

changed, approval = show_quick_check_list(
  items=items,
  states='checkbox3',
  title='',
  summary='',
  status='',
  filter=None,
  alternate=False,
)
```

| Argument    | Contract                                                                                   |
| ----------- | ------------------------------------------------------------------------------------------ |
| `items`     | 1-1,000 `CheckListItem` records with unique IDs. Fixed while the window is open.          |
| `states`    | A preset name: `'checkbox'` (default), `'checkbox3'` or `'star'` (see below).              |
| `title`     | Draggable header, as in QuickList. At most 512 characters.                                 |
| `summary`   | Optional secondary line under the title. At most 2,048 characters.                         |
| `status`    | Caller text on the left of the status bar, typically the key labels. At most 512 characters. |
| `filter`    | `'fuzzy'` or `None` (default), as in QuickList.                                            |
| `alternate` | Whether <kbd>Shift</kbd>+<kbd>Enter</kbd> approves. When `False` it does nothing.          |

```python
CheckListItem(id, title, state, hint='', description='', enabled=True)
CheckListResult(changed, approval)  # NamedTuple
```

- `CheckListItem.state` is the starting state ID. Disabled items are dimmed, cannot
  be cycled and are never reported as changed.
- The state label (for example "On") is used in the tooltip and the accessible name.
  A *start-only* state, such as `mixed`, is reachable only on items that started
  in it; see [Cycle Rules](#cycle-rules).
- `changed` maps item ID to its final state ID, for changed items only.
  `approval` is `'primary'`, `'alternate'` or `None` (cancelled). Cancellation still
  returns the changes made before <kbd>Esc</kbd>, as QuickBoard returns its draft.
  An approval with no changes returns an empty mapping; the caller decides.

### Input Validation

All validation runs on the caller thread before any Qt object exists. Invalid
input raises `TypeError` or `ValueError`.

| Field                          | Limit                         |
| ------------------------------ | ----------------------------- |
| Item ID, item title            | 1-512 characters              |
| Hint, description              | 0-2,048 characters            |
| All retained text, combined    | 4 MiB as UTF-8                |

- Text fields are exact `str` without NUL; `enabled` is an exact `bool`.
- `items` may be any iterable. At most 1,001 items are read
  (`itertools.islice`), so an endless generator fails fast.
- Items must be `CheckListItem` instances (frozen dataclasses). They are copied
  into internal tuples, so later caller changes have no effect.
- Item IDs are unique. Every starting state belongs to the preset.
- The combined text covers every item field plus `title`, `summary` and `status`.

### Cycle Rules

- Each item cycles through a ring: the preset's cycleable states in declared
  order, plus the item's own start-only state (if it started in one) at its
  declared position.
- Forward and backward move along the ring and wrap. An item back at its starting
  state is unchanged.
- Example, `checkbox3` starting at `mixed`: forward `mixed` → `off` → `on` →
  `mixed`; backward `mixed` → `on` → `off` → `mixed`. Starting at `on`: `on` ↔ `off`.
- Disabled items never cycle and may start in any state of the preset.

### Presets

Presets are painted by the host; they need no assets.

| Preset      | States, in cycle order            | Look                                                                       |
| ----------- | --------------------------------- | -------------------------------------------------------------------------- |
| `checkbox`  | `off`, `on`                       | Off: olive outline. On: orange box with a brown check.                     |
| `checkbox3` | `off`, `on`, `mixed` (start-only) | As `checkbox`. Mixed: brown box with an orange border and an orange bar.   |
| `star`      | `empty`, `filled`                 | Empty: olive outline. Filled: orange star.                                 |

Candidates for later presets (`eye`, `pin`) are out of scope.

### Look

The element looks like QuickSearch (reviewed against a mock-up rendered with the
real QuickSearch widget and theme):

- Rows use the QuickSearch item theme (`.quicksearch-item*`): borders, `#404040`
  background, `#575757` current row, title with filter highlights, right-aligned
  hint and a description line.
- The state indicator sits in a narrow column on the left of each row, aligned
  with the title line.
- Optional query field as in QuickSearch.
- Frameless window with a draggable title and optional summary, as in QuickList.
- Status bar at the bottom: caller `status` on the left (elided), "N changed" on
  the right, in the description color above a row-border line.

Indicator colors come from the application's palette (app icon and the existing
olive). New `Theme.css` selectors, with these defaults when missing:

```css
.quickchecklist-state        { color: #75715e; } /* Off / empty outline: olive */
.quickchecklist-state-active { color: #f68f33; } /* On / filled / mixed: orange */
.quickchecklist-state-mark   { color: #3c3a2d; } /* Check mark, mixed fill: brown */
```

Disabled items draw their indicator at reduced opacity and their text in the
description color.

### Interaction

- <kbd>Space</kbd> or a click on the indicator moves the current item to the next
  state; <kbd>Shift</kbd>+<kbd>Space</kbd> to the previous one. <kbd>Insert</kbd>
  moves to the next state and then down, as in QuickList. A click elsewhere on a
  row only makes it current.
- With a filter, focus starts in the query; <kbd>Up</kbd>/<kbd>Down</kbd>/
  <kbd>Page Up</kbd>/<kbd>Page Down</kbd> move into the list, as in QuickList.
  <kbd>Space</kbd> in the query types a space.
- Filtering hides items but keeps their states. The changed count covers all items.
- <kbd>Enter</kbd> returns `'primary'`. <kbd>Shift</kbd>+<kbd>Enter</kbd> returns
  `'alternate'` when allowed. <kbd>Esc</kbd>, closing the window or closing the
  main window returns `None`.
- The window is modal to the main window. There is no modeless mode, handle,
  sorting, metadata line or multi-item bulk toggle.

## Scope

- Include the public API in `fman.ui`, the three presets, the optional fuzzy
  filter, the status bar, theme selectors, tests and documentation.
- Exclude caller-defined states and custom SVG icons (user decision; later looks
  are added as presets), mutable items, handles, modeless use, sorting, tree
  items, bulk toggling of a selection and later presets.
- Exclude the File Attributes Editor; it is [a separate task](FileAttributesEditor001.md).
- Additive only: QuickSearch, QuickList, QuickTable and QuickBoard contracts are
  unchanged. Themes without the new selectors keep working with the defaults.

## Design

### Ownership and Data Flow

- Public export: [fman/ui.py](../src/main/python/fman/ui.py) adds
  `show_quick_check_list`, `CheckListItem` and `CheckListResult`.
- Qt-free data in a new `fman/impl/ui/check_list_data.py`: descriptors, argument
  validation, presets, cycle order (including start-only states) and the result
  diff. Pure functions, unit tested without Qt.
- Window in a new `fman/impl/ui/quick_check_list.py`, following
  [quick_list_window.py](../src/main/python/fman/impl/ui/quick_list_window.py):
  `ToolWindow` host, `Qt.Dialog | Qt.FramelessWindowHint`, draggable title,
  session with `done` event, main-window close cancels.
- Rendering reuses the QuickSearch item CSS
  (`main._theme.get_quicksearch_item_css()`) and
  [QuicksearchItemRenderer](../src/main/python/fman/impl/quicksearch.py) with
  extra left padding for the indicator. Matching reuses the QuickList fuzzy
  matcher. Any helper shared with QuickList is extracted without changing its behavior.
- [theme.py](../src/main/python/fman/impl/theme.py) parses the three new selectors
  next to the QuickSearch item CSS, falling back to the defaults above.
- Validation runs on the caller thread before anything is built. The window is
  built on Qt via `run_in_main_thread`. The call blocks like `show_quick_list`:
  a local `QEventLoop` on Qt, `Event.wait()` on a worker.
- State lives only in the Qt window: the starting snapshot and the current state
  per item. The result is computed once when the window closes.

### Threading and Failure

- No worker threads, timers or background jobs. Qt objects stay on the Qt thread.
- Invalid arguments raise `TypeError` / `ValueError` before the window opens.
- Persistence: not applicable. States are dialog state only.

## Alternatives

- **Checkbox mode for QuickList:** rejected. QuickList's Enter falls back to the
  current item, its selection, handle and sorting semantics differ, and a third
  state does not fit selection.
- **Panel with Toggles:** rejected. Panels are docked controls, not a filterable,
  modal row list with descriptions.
- **QuickTable with a state column:** rejected. Rows are immutable and the result
  is the visible row positions.
- **Return a values string:** rejected by the user in favor of structured states.
- **Native `QCheckBox` per row:** rejected. Breaks the QuickSearch look and density
  and cannot show a star.
- **SVG assets for the presets:** rejected. Two-tone indicators would need tinting
  rules; painting uses the theme colors directly.
- **Caller-defined states with custom SVG icons:** dropped by the user for v1.
  Safe SVG input needs external-reference and animation policies (UIR02-UIR04);
  the presets cover the known consumers.

## Runtime Effects

- Startup: none beyond three extra selectors parsed with the theme.
- Per call: one window, at most 1,000 rows, painting only. No file I/O.
- No threads, processes, timers or recurring work. Cancellation is <kbd>Esc</kbd>
  or closing the window.
- Disabled path: nothing runs unless a plug-in calls the element.

## Tests

- Unit, `fman_unittest/test_quick_check_list_data.py`:
  - Validation: unknown or duplicate IDs, unknown presets and starting states,
    every field limit, the 4 MiB combined budget, NUL, non-`bool` flags,
    non-record items, endless generators, and records changed by the caller
    after the call.
  - Cycle rules: forward and backward rings, returning to a start-only starting
    state in both directions, disabled items.
  - Result diff and the cancellation result.
- Theme, `fman_unittest.impl.test_theme`: the new selectors parse and fall back to defaults.
- Qt integration, new `QuickCheckListIT` (windows platform):
  - Space, Shift+Space, Insert and indicator clicks cycle states; row clicks do not.
  - The filter hides items and keeps their states; the changed count updates.
  - Enter returns `'primary'`; Shift+Enter returns `'alternate'` or does nothing
    when `alternate=False`; Esc and main-window close return `None` with the changes.
  - A worker-thread caller blocks and is released; a Qt-thread caller uses a local loop.
  - Each preset paints its states; disabled items are dimmed.
  - Tooltips and accessible names include the state label.
- Manual: compare against the reviewed mock-up at 100% and 150% scaling.

Focused commands (from the repository root, with the environment on `PATH`):

```powershell
python -c "import build, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM']='offscreen'; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_check_list_data'], env=env))"
python -c "import build, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.QuickCheckListIT'], env=env))"
```

## Implementation Steps

1. Add `check_list_data.py` with descriptors, presets, validation, cycling and the
   result diff; add the unit tests.
2. Add the theme selectors to `Theme.css` and parse them in `theme.py`; extend the
   theme tests.
3. Add `quick_check_list.py` with the window, delegate, indicator painting, filter
   and status bar; add `QuickCheckListIT`.
4. Export the API from `fman/ui.py`; add a hidden import in `application.spec` if
   the module is imported lazily.
5. Update [UIElements.md](../UIElements.md) (table row, rationale, a QuickList vs.
   QuickCheckList comparison, the Qt-free services list),
   [docs/plugins/ui-elements.md](../docs/plugins/ui-elements.md),
   [PlugIn.md](../PlugIn.md) and `CHANGELOG.md` (Added).

## Acceptance Criteria

- A plug-in using only `fman.ui` shows a QuickCheckList with each preset,
  without importing Qt.
- Rows look like QuickSearch rows with an olive/orange/brown indicator on the left
  and the status bar at the bottom.
- Space, Shift+Space, Insert and clicks cycle states as specified; start-only and
  disabled rules hold.
- Every input limit is enforced before any Qt object exists.
- Enter, Shift+Enter and Esc return the changed states with `'primary'`,
  `'alternate'` (or nothing when not allowed) and `None`.
- No worker threads or timers exist; QuickList and QuickSearch behavior is unchanged.
- Focused unit and Qt tests pass; documentation lists the element as implemented.

## Review Findings (2026-10-31)

Planning review only. The original design below and above is preserved; these
are open contract gaps, not confirmed defects in an implementation. Resolve
UIR01-UIR02 and the editor's recursive-intent dependency before implementation.

### UIR01 - P2: Public Input and Cycle Validation Is Not Fully Bounded

- Evidence: the API bounds row/state counts and header text, but gives no maximum
  lengths for item/state IDs or state labels and no aggregate retained-text
  budget. Huge IDs or labels therefore remain valid under the stated contract.
  The behavior of a custom state set with no `cycle=True` state is unspecified.
- Required decision: define limits for every retained field and the total UTF-8
  text budget; validate exact boolean fields, canonicalize immutable records,
  and bound iterable materialization before building Qt objects. Either reject
  all-start-only state sets or define cycling as a safe no-op. Specify the cycle
  behavior for an item's own starting-only state in both directions.
- Checks: oversized IDs/labels and aggregate text, mutable descriptor inputs,
  overlong generators, invalid booleans, zero cycleable states, and forward/
  backward return to an item's initial start-only state. Reject invalid inputs
  before opening the window; preserve the intended disabled-item semantics.

### UIR02 - P2: Custom SVG Validation Does Not Freeze the Input

- Evidence: a caller-thread size check followed by `QSvgRenderer` loading a path
  on Qt leaves a change window: a file can be replaced, grow beyond 64 KiB or
  disappear between validation and parsing. The promise that all invalid SVGs
  raise before the window shows also needs a cleanup/result path for Qt-side
  validation failures. Animated SVGs are not excluded despite the no-timer and
  fixed-pixmap contracts.
- Required decision: read each SVG once with a bounded read and carry immutable
  bytes to Qt; parse those bytes before showing the window. Specify whether
  animated SVGs are rejected or made static without starting recurring work.
  On parsing or construction failure, dispose partial Qt objects and propagate
  the error to either caller type without leaving its wait blocked.
- Checks: replace/delete/grow the source after preparation, a failed later SVG
  after an earlier valid one, animated input, worker and Qt callers, and
  main-window close during preparation. No window or renderer timer may remain
  after an invalid-input failure.

### Cross-Plan Dependency

The editor's FAR01 requires an explicit way to express a recursive target state
that equals the selected folder's starting state. A final-state diff alone
cannot express that intent. Reconcile the two plans rather than silently
changing QuickCheckList's generic `changed` contract during editor implementation.

### Review Validation

- Compared the proposed contracts with the existing QuickList data validation,
  modal window/session pattern and public pane API. No tests or runtime probes
  ran; the proposed element does not exist yet.
- Preserve the chosen look, presets and approval meanings. This review does
  not authorize application implementation, extra settings or background work.

### Review Resolutions

| Finding                | Resolution                                                                                                                                                                                                                         |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| UIR01                  | [Input Validation](#input-validation): limits for every retained field, a 4 MiB combined budget, exact `bool` flags, bounded `islice` reads and copied frozen records. [Cycle Rules](#cycle-rules): at least two cycleable states; per-item rings defined in both directions. |
| UIR02                  | Superseded by the user's decision to ship presets only: no caller SVG input exists.                                                                                                                                                |
| UIR03, UIR04           | Same: custom SVG states are dropped for v1, so no external references or SVG animation timers can occur. Later looks are added as host-painted presets.                                                                             |
| Cross-Plan Dependency  | User decision: the File Attributes Editor does nothing when the final states equal the starting states, for Enter and Shift+Enter alike. `changed` stays a final-state diff; no contract extension.                              |

## Implementation Review (2026-10-31)

The presets-only implementation and the user's final-state-diff decision were
reviewed as approved; earlier custom-SVG and recursive-intent proposals are not
reopened. IR01 is a confirmed implementation follow-up. No application code was
changed by this review.

### IR01 - P2: Valid Text Can Size the Dialog Beyond the Screen

- Owner: `QuickCheckListWindow.present` and `QuickCheckList.fit_rows` in
  [quick_check_list.py](../src/main/python/fman/impl/ui/quick_check_list.py).
- Failure: `present` grows the window to its unconstrained size hint, while
  `fit_rows` sets a minimum height from complete row text. Neither is limited to
  the screen's available geometry. The unelided header can force a very wide
  dialog; a description containing line separators can force a very tall one,
  even though every field satisfies the public validation limits.
- Probe: used the real window and validated data with a minimal native Qt main
  window and default CSS. On a 2,560 x 1,552 available desktop, a 512-character
  `W` title produced a 5,646 x 242 dialog. A short title and a 400-character
  description (`x` plus U+2028 repeated 200 times) produced a 560 x 3,089 dialog;
  that row's height was 3,035 pixels. Both windows exceeded the available screen.
- Follow-up: constrain width/height to available geometry, elide or wrap the
  header, and ensure overflowing rows remain scrollable rather than imposing
  an off-screen minimum height. Keep the query, list and footer reachable.
- Coverage gap: the Qt tests use short headers/descriptions. Add legal long-text
  and multiline-description cases on a small available viewport, including
  display scaling. This is a sizing probe, not a full visual acceptance pass.

### Review Validation

- Inspected validation/rings, modal lifecycle, input handlers, rendering, public
  exports, theme defaults, packaging wiring and nearby tests. Editor diagnostics
  reported no errors in the data and window modules.
- Bounded generated probes ran as `python -X faulthandler -u -`, through
  `build._environment()` with native Windows Qt and a 20-second parent timeout.
  Files and settings were isolated; windows were closed after measurement.
- Existing unit/integration targets and a frozen build were not rerun. Earlier
  implementation results remain historical. Both Plan and Done copies of this
  task currently exist; the canonical move requirement still needs cleanup.

### Resolution (2026-10-31)

| Finding     | Resolution                                                                                                                                                                                                                                                                                       |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| IR01        | `QuickCheckListWindow.present` caps width and height to `available_geometry()` (the main window's screen). `fit_rows(limit)` bounds the list's minimum height to half of it. The header is an `ElidedLabel`; header, summary and status collapse line breaks into one elided line with the text in a tooltip. The list scrolls per pixel, so rows taller than the viewport stay reachable. |
| Coverage    | `QuickCheckListIT.test_long_valid_text_stays_within_a_small_screen`: 512-character title, multiline summary and status, a 400-character U+2028 description and the fuzzy filter on a patched 640 x 360 available geometry. The window fits, header, query and status bar lie inside it, the header is elided and the list scrolls. |
| Plan copies | The stale `Plan/` copy was deleted; only this `Done/` copy remains.                                                                                                                                                                                                                              |

## Reviewers

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Designed with the user: structured result, Enter / Shift+Enter
  approvals with caller-defined meanings, optional filter, fixed items, status
  bar, `checkbox` / `checkbox3` / `star` presets plus custom SVG states, and the
  QuickSearch look with olive/orange/brown indicators confirmed on a mock-up.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Recorded UIR01 (bounded input/cycle validation) and UIR02 (immutable
  SVG preparation, timer policy and failure cleanup), plus the editor's FAR01
  recursive-intent dependency. Planning review only; no implementation, tests
  or probes. Original design and reviewer provenance preserved. Resolve the
  open contracts before implementation.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Resolved UIR01 (field limits, combined text budget, exact flags,
  bounded reads, copied records, cycle rings) and UIR02 (bytes read once, Qt
  parsing before show, animated SVGs rejected, failure cleanup). Per the user,
  the cross-plan dependency is resolved in the editor: no change means no
  operation, so the generic `changed` diff stays. Ready for another review.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Request changes to the custom-SVG contract before implementation.
  The revised validation/cycle rules and the user's no-change/no-operation
  decision resolve the earlier input and recursive-intent questions; do not
  reopen that product decision. UIR03-UIR04 below remain open. No application
  implementation or public API changes were made by this review.

#### UIR03 - P2: Immutable SVG Bytes Do Not Bound External Resource Reads

- [Custom SVG States](#custom-svg-states) passes bounded bytes to Qt, but does
  not exclude external resource references. With Qt 5.15.15, a small static SVG
  containing an absolute local `image` / `xlink:href` loaded that image during
  `QSvgRenderer` construction. Replacing the owned PNG between two loads of the
  exact same SVG bytes changed the rendered pixel from red to blue.
- Therefore the 64 KiB limit and caller-thread read do not bound all input or
  keep all file I/O off Qt. A referenced large/unavailable resource can add
  unexpected work before the window opens; dependency replacement also changes
  the promised captured input.
- Required: define a self-contained SVG policy and validate it structurally
  before Qt parsing. Reject external references, or explicitly capture allowed
  dependencies with limits. Distinguish internal `#id` references and any allowed
  embedded raster content from external paths; do not rely on a file-size check
  or regex alone. Add referenced-file replacement/deletion and no-Qt-I/O tests.

#### UIR04 - P2: Post-Load Animation Rejection Already Starts a Timer

- The proposed load-then-`animated()` check does not meet "No SVG timer is ever
  started." A native probe loading a short `animateColor` SVG reported
  `animated() == True` and an active child `QTimer` with a 33 ms interval,
  immediately after `load()` and before processing any events.
- Required: suppress animation before loading with a verified supported Qt 5
  sequence, or reject animation structurally before constructing the renderer.
  Continue rejecting animated inputs and cleaning up failed later states.
  Alternatively, explicitly relax the contract to permit a transient timer that
  is stopped/disposed before event processing; do not describe that as never
  starting a timer.
- Add a test observing timer activation during load, not just an empty timer
  list after cleanup. Include worker and Qt callers and a valid state followed
  by an animated one.

#### Review Validation

- Read the current QuickList window/session pattern and public UI contracts.
  Checked the official [Qt 5.15 QSvgRenderer documentation](https://doc.qt.io/archives/qt-5.15/qsvgrenderer.html).
- Ran isolated `python -B -X faulthandler -c <probe>` children through
  `build._environment()` with offscreen Qt and a 30-second parent timeout.
  UIR03 used only a disposable 16 x 16 PNG and identical SVG bytes; UIR04
  inspected `renderer.findChildren(QTimer)` immediately after `load()`.
  Both behaviors reproduced; renderers and temporary files were disposed.
- These are native dependency probes, not tests of the unimplemented element.
  No full suite, build/freeze, dependency installation, or user-data inspection.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Per the user, v1 ships the three presets only. `CheckState` and
  custom SVG icons are removed, which supersedes UIR02-UIR04. Approved by the
  user for implementation.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the presets-only implementation and recorded IR01 with
  native dialog-size probe evidence. The approved no-change/no-operation and
  no-custom-SVG decisions remain unchanged. No application code changed or
  existing test targets rerun. Original design, reviewer history and implementer
  validation preserved; screen-bounded layout needs follow-up.

## Implementer

### 2026_10_31 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented `check_list_data.py` (validation, presets, rings, result)
  and `quick_check_list.py` (frameless modal `ToolWindow`, QuickSearch renderer
  with a painted indicator column, fuzzy filter, status bar, blocking session as
  in QuickList). Exported `show_quick_check_list`, `CheckListItem` and
  `CheckListResult` from `fman.ui`. Theme: three optional `.quickchecklist-state*`
  selectors with defaults; `QuickCheckList` added to the QuickSearch/QuickList
  QSS selectors and theme mappings so rows, query and selection share their look.
  Documented in `UIElements.md`, `docs/plugins/ui-elements.md`, `PlugIn.md` and
  `CHANGELOG.md`.

### 2026_10_31 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Resolved implementation review IR01: screen-bounded window and list
  height, single-line elided header, summary and status, per-pixel scrolling.
  Regression test added; `PlugIn.md`, `docs/plugins/ui-elements.md` and
  `CHANGELOG.md` (0.20.0) updated.

## Validation Results

- `fman_unittest.test_quick_check_list_data`, `fman_unittest.impl.test_theme`,
  `fman_unittest.test_portable` and `fman_unittest.test_ui_elements` (offscreen):
  passed as part of a 72-test focused run (one unrelated expected skip).
- `fman_integrationtest.test_qt.QuickCheckListIT` (windows platform): 5 tests
  passed, together with `QuickListServiceIT` and `QuickListIT` (32 tests total).
- One earlier combined run had a single failure in
  `QuickListServiceIT.test_global_tab_between_modeless_list_and_panel` (window
  activation). It passed alone twice, after `QuickCheckListIT` twice, and in two
  further combined runs; treated as focus flakiness, not a regression.
- Visual: rendered the real widget with the application theme for all three
  presets and compared it with the reviewed mock-up at the current display
  scale. A 150% scaling check was not run.
- Implementation review fix: `fman_integrationtest.test_qt.QuickCheckListIT`
  (windows platform, 6 tests including
  `test_long_valid_text_stays_within_a_small_screen`) passed at 100% and with
  `QT_SCALE_FACTOR=1.5`. `fman_unittest.test_quick_check_list_data` (offscreen)
  and the gallery test
  `test_edit_attributes_capture_shows_states_without_writing` passed.
