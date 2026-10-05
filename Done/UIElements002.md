# UI Elements 002: QuickList

Status: Implemented; implementation reviews IR1-IR4 resolved (see Review
Resolution).

## Task

Add `fman.ui.show_quick_list`: a Qt-free list for selecting one or many items.
It blocks and returns the chosen IDs, or `None`, like `show_quicksearch` and
`show_quick_table`. An `on_open` handle lets a driver, such as a Panel, read the
state and replace the items while the list is open. Items may carry metadata,
shown on one line and sortable.

It replaces the public Qt `QuickList` widget, which exposes Qt threading and
lifetime to plug-ins. [Favorites 004](Favorites004.md) is the reference consumer.

## Scope

- Included: `show_quick_list`, its handle, `ListItem.metadata`, sorting with a
  sort bar and saved sort, Ctrl+I / Ctrl+Shift+A, global Tab, and removing the
  Qt widget exports after Favorites 004.
- Excluded: anything that acts on items (operations, caller keys, menus,
  buttons), table layout, filtering by metadata, changes to QuickSearch,
  QuickTable and the Panel service.
- Compatibility: the fman 1.7.5 API is unchanged. `QuickList`, `Panel`,
  `TextButton`, `DropDown`, `IconButton` and `JsonSettings` leave `fman.ui`,
  with migration notes in CHANGELOG and PlugIn.md. `ToolWindow`,
  `PaneToolWindow`, `UiController.build` and `OutputTextBox` stay public Qt
  (Calculate File Hash): accepted debt for the TODO item on a Qt-free
  `fman.ui` layer.

## Design

### API

```python
show_quick_list(*, items, title='', summary='', modal=True, filter='fuzzy',
                query='', selected=(), title_label=None, hint_label=None,
                sort=None, settings=None, on_open=None) -> tuple[str, ...] | None
```

| Argument | Meaning |
| --- | --- |
| `items` | `ListItem`s with unique IDs; at most 10,000; title at most 512, hint at most 2,048 characters (metadata limits below). |
| `title`, `summary` | Window title; one line above the list. |
| `modal` | `True` (default) blocks the main window; `False` for a list driven by a docked Panel. |
| `filter` | `'fuzzy'` (default) or `None`. |
| `query`, `selected` | Initial filter text and selected IDs; unknown IDs raise `ValueError`. |
| `title_label`, `hint_label` | Sort labels, for example `'Name'`, `'Path'`; `None`: not sortable. |
| `sort` | Initial `(label, ascending)`; `None`: input order. |
| `settings` | Plug-in JSON file where the host keeps the sort. |
| `on_open` | `on_open(handle)`, called once before the list is shown. |

- Enter or double-click returns the chosen IDs in input order: the selection
  (including hidden), else the highlighted item. Escape returns `None`.
- Like `show_quick_table`: worker callers wait, Qt-thread callers run a nested
  event loop. Invalid arguments raise in the caller.
- The list closes with the main window and returns `None`.

### Handle

| Member | Behavior |
| --- | --- |
| `snapshot()` | Immutable state: `selected`, `chosen`, `current`, `query`, `sort`. Also valid after closing. |
| `set_items(items)` | Replaces the items; keeps query, sort, surviving selection and current item. Returns once applied. |
| `focus()` | Activates the list window. |
| `close(result=None)` | Closes the list; `show_quick_list` returns `result`, which is `None` or a tuple of current item IDs (else `ValueError`). |
| `is_open` | `False` once closed. |

Safe from any thread; calls after closing do nothing. The window keeps a plain
copy of the state under a lock, refreshed on every selection, query and sort
change; `snapshot()` reads it (R6). `set_items` validates in the caller, then
runs on Qt, so a following `snapshot()` shows the new items.

**Opening and closing (R1, R7).** The handle owns the completion: an `Event`
and the result in plain shared state, not a Qt signal. Order: create the handle,
build the window hidden, call `on_open` on the calling thread, show the window
only if still open, then wait. A `close()` inside `on_open` returns at once. If
`on_open` raises, the list closes and the exception propagates.

**Driver lifetime (R3), for developers.** A driver that keeps the list open
registers `handle.close` with its `UiOwner` (`owner.attach`) inside `on_open`
and detaches in a `finally` after `show_quick_list` returns. If `attach` fails
(the owner is no longer active), it calls `handle.close()`. A Panel's
`on_closed` alone is not enough: it is skipped while the plug-in unloads.

### Keys

This table goes to the QuickList section of
[docs/plugins/ui-elements.md](../docs/plugins/ui-elements.md).

| Key | Focus | Effect |
| --- | --- | --- |
| Space, Insert, Shift+navigation, Ctrl+A, right-click | List | Select |
| Typing, Space, Ctrl+A | Filter box | Edit the filter, as today |
| Ctrl+I, Ctrl+Shift+A | Both | Invert, clear the selection |
| Enter, double-click | Both | Return the chosen items |
| Escape | Both | Return `None` |
| `Ctrl+F<n>` | Both | Sort by field *n*; again reverses |
| Tab, Shift+Tab | Both | Filter box and list; in a modeless list also the docked Panel, and back |

Global Tab is host behavior (R8): each main window keeps a registry of its open
modeless lists in activation order. The list's Tab boundary goes to the docked
Panel; the Panel's goes to the most recently active list. Modal lists, lists
without a docked Panel and Panels without an open list wrap as today (Find Files,
Search Files). Tab in a pane stays Switch Panes.

### Metadata, Display and Sorting

```python
ListItem('1', 'Projects', 'D:\\Work\\Projects', metadata={'Added': 1, 'Used': ()})
```

Rules for developers (R2, R4); they go to the QuickList section of the docs:

| Value | Meaning |
| --- | --- |
| `()` or `[]` | No value: shown empty, sorted last |
| String or number | Shown and sorted as is |
| `(sort_key, text)` | Sorted by `sort_key`, shown as `text` (dates, sizes) |

- Every item lists every label; an absent value is `()`.
- At most 8 labels. Title, hint and metadata labels are unique and nonempty,
  at most 32 characters. Metadata strings and display texts are at most 128
  characters.
- Numbers are `int` or finite `float`; `bool`, NaN and infinity are refused.
  Within a field, sort keys are all strings or all numbers.
- Checked in the calling thread on opening and on every `set_items`; an invalid
  call raises and leaves the list unchanged.
- The sort fields are the labels of the current items; an empty list has none.
  The requested sort (argument, saved or chosen) is remembered and applies
  whenever its label exists, otherwise the list shows input order. Use one
  `settings` file per list.

Display and sorting:

- Shown as a third line of `Label value` cells, aligned across rows. Lists
  without metadata look as today.
- Sort fields: title and hint (when labeled), then metadata. The sort bar under
  the filter box shows each field with its key and the active direction;
  clicking a field sorts by it.
- Stable sort, natural for strings, empty values last. No sort means input
  order. Filtering keeps the order when the list is sortable, else ranks as
  today.
- With `settings`, the host restores `sort`/`ascending` on open and saves them
  on change through the shared settings resource on a worker, never on Qt (R9);
  a failed save shows a status message. A saved sort overrides the `sort`
  argument.

## Alternatives

- **Public Qt list and Panel widgets:** rejected; Qt threading, lifetime and
  PyQt5 coupling leak into plug-ins. The remaining Qt exports are listed under
  Compatibility.
- **Operations or caller keys in the list:** rejected; too many edge cases.
  Actions live in a Panel.
- **List/Panel pairing argument:** rejected; global Tab suffices.
- **Non-blocking call or mode flag:** rejected; one blocking call, like
  QuickSearch and QuickTable, plus `on_open`.
- **Metadata as columns:** rejected; that is QuickTable.

## Runtime Effects

- Nothing runs until `show_quick_list` is called.
- Filtering and sorting run on Qt, bounded by the item caps; measured at the
  limits.
- Settings: one read on open, one worker write per sort change.

## Tests

- Unit (`fman_unittest.test_ui_elements`): metadata limits, value forms,
  non-finite numbers, label uniqueness, argument validation, sort order,
  settings handling, `fman.ui` exports, `close(object())` and unknown
  `selected` raise.
- Qt (`QuickListIT`, offscreen and native): worker and Qt callers, out-of-order
  modeless closes, Enter/Escape/chosen rule, handle members from a worker,
  `snapshot()` after a worker `set_items()`, `close()` and `close(result)`
  inside `on_open`, Escape impossible before a slow `on_open` returns,
  `on_open` failure, invalid `set_items` leaves the list unchanged, owner
  deactivation and main-window close release the caller, keys in both focuses,
  global Tab (no list, two lists, Find Files Panel alone), metadata line, sort
  bar, requested sort across empty and refilled lists, saved sort with a
  read-only settings file not blocking Qt.
- Opt-in performance test: filter and sort at 10,000 items with maximum
  metadata, with a pass/fail limit set from the first measurement.

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_ui_elements','fman_integrationtest.test_qt.QuickListIT'], env=env).returncode)"
```

## Implementation Steps

1. `ListItem.metadata` and validation.
2. `show_quick_list` on the existing widget, now host-private.
3. Handle and `on_open`.
4. Keys and global Tab.
5. Metadata line, sorting, sort bar and saved sort.
6. After Favorites 004: remove the Qt widget exports; update PlugIn.md,
   UIElements.md, `docs/plugins/ui-elements.md` (key table, metadata rules,
   driver lifetime) and CHANGELOG.

## Acceptance Criteria

- `show_quick_list` works without Qt code and returns the chosen IDs or `None`.
- A driver reads the state and replaces items through the handle.
- The list never acts on items; Tab reaches a docked Panel from a modeless list.
- Metadata shows on one aligned line and is sortable; the sort is saved.
- Lists without metadata look and behave as today.
- `fman.ui` exports no Qt list or Panel widgets after Favorites 004.
- Focused tests pass offscreen and native.

## Reviewers

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Clean restart at the user's request; earlier drafts and reviews
  discarded. Qt-free `show_quick_list` that blocks and returns the chosen IDs,
  with an `on_open` handle (`snapshot`, `set_items`, `focus`, `close`), caller
  keys reported to `on_key`, immutable metadata with an aligned line, sorting
  by `Ctrl+F<n>` and a sort bar, and optional saved sort. Qt widget exports
  removed after Favorites 004. Ready for review.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: User decisions: QuickList is for selection only (Space selects,
  Enter returns); `keys`/`on_key` removed to avoid their edge cases; no
  list/Panel pairing argument; global Tab between a modeless list and the
  docked Panel instead; the `current` argument removed; the key table becomes
  the user documentation. Ready for review.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Compacted to the final design at the user's request; no design
  change. Ready for review.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revisions required. Review of the restarted selection-only design;
  R1-R5 cover opening completion, metadata bounds, driver lifetime, sort-field
  identity and focus-sensitive keys. Settled interaction choices retained.
  Findings and validation below. No application implementation changes.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: R1-R5 resolved without API changes: handle-owned completion before
  `on_open` (R1); metadata limits, `()` as the only empty value, finite numbers,
  validation on every `set_items` (R2); driver attaches `handle.close` to its
  `UiOwner`, list closes with the main window (R3); unique labels, fields taken
  from the current items, requested sort applied whenever its label exists
  (R4); focus column in the key table (R5). Developer rules marked for the docs.
  Ready for review.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Revisions required. R1-R5 resolutions hold against the source. Added
  R6-R11: the thread-safe `snapshot`/`set_items` mechanism is unspecified;
  `on_open` runs after the window is interactive, so a user can close the list
  before the driver has attached; global Tab needs a host registry because
  `PanelSession.focus_from_panel` wraps inside the Panel today and the list
  window has no pane or Panel reference; sort persistence would write JSON on
  the Qt thread; `close(result)`/`selected` validation and the remaining Qt
  exports (`ToolWindow`, `PaneToolWindow`, `UiController.build`) need a
  stated position. No application code edited.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: R6-R11 resolved without API changes: locked state copy for
  `snapshot()`, `set_items` returns once applied (R6); `on_open` before the
  window is shown (R7); per-main-window list registry for global Tab, Panels
  used alone keep wrapping (R8); sort saved on a worker through the shared
  settings resource (R9); `close(result)` and `selected` validated, metadata
  limit scoped (R10); remaining Qt exports listed as accepted debt (R11).
  Ready for review.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implementation revisions required. The tuple metadata path bypasses
  validation; findings and independent checks are recorded below. Review only,
  no application implementation changes.

## Design Review (2026_10_05)

- **R1 [P1]: Install completion tracking before invoking `on_open`.**
  The handle permits `close()` from any thread and the opening callback may
  use it immediately. QuickTable's
  [watched opener](../src/main/python/fman/impl/ui/facade.py#L825) connects
  `disposed` only after its opener returns; copying that order and calling
  `on_open` in the opener would miss a synchronous close. The worker event
  would never be set, or the Qt caller would enter a loop after its quit signal.
  Specify an opening state machine: register completion first, invoke the
  callback once on a defined thread, and wait only if still open. Store the
  result/exception in plain shared state rather than depending on a destroyed
  Qt object. Test immediate `handle.close()`, `close(result)`, callback failure
  before and after closing, and each case from worker and Qt callers.
- **R2 [P2]: Metadata escapes the advertised bounds and numeric contract.**
  Only title and hint have text limits. A valid metadata string, label or
  `(sort_key, text)` display value can be arbitrarily large, so the item caps
  do not bound Qt layout, natural sorting or allocation. "A number" also
  includes non-finite floats unless excluded; NaN does not provide the promised
  numeric ordering. Specify limits for IDs, labels, string sort keys and display
  text, an aggregate input budget, accepted numeric types and finite-value
  checks. Apply them on opening and every `set_items` before changing live state;
  reject invalid updates in the calling thread. Reuse the existing
  [text validator](../src/main/python/fman/impl/ui/table_data.py#L27) and numeric
  validation where suitable. Test over-limit metadata, Unicode expansion,
  non-finite values and invalid worker updates; give limit-sized timing and
  heartbeat checks an observable pass/fail threshold. No performance failure
  has been measured in this review.
- **R3 [P2]: Define driver teardown independently of Panel close callbacks.**
  The reference consumer relies on `on_closed=handle.close`, but
  [Panel callback dispatch](../src/main/python/fman/impl/ui/facade.py#L120)
  skips callbacks when its plug-in owner is inactive. During unload, its Panel
  closes without that callback; a live QuickList with no stated owner remains
  open and its command worker keeps waiting. Specify the driver contract using
  public [UiOwner.attach/detach](../src/main/python/fman/impl/ui/__init__.py#L99)
  to register `handle.close`, handle failed attachment to an inactive owner, and
  detach/unsubscribe in a finally block after the blocking call. An equivalent
  host-managed lifetime is acceptable, but cannot be inferred from QuickTable's
  permanent static owner. Define how main-window close releases the waiter and
  how the final snapshot remains usable. Test owner invalidation, main-window
  close, pending item updates and subscription cleanup. Preserve the no-pairing
  decision; explicit cleanup does not require a list/Panel pairing argument.
- **R4 [P2]: Sort labels need unique identities and replacement rules.**
  The sort argument and saved state address fields by label, but no rule forbids
  `title_label='Added'` with metadata `{'Added': 1}`, identical title/hint labels,
  or empty labels. The public tuple cannot identify which field should sort.
  Require unique nonempty labels across enabled title, hint and metadata fields,
  or introduce unambiguous stable field identities. State whether metadata schema
  is fixed for the window: `set_items` currently permits a new schema while
  promising to keep sort. Define empty-list schema, removed/changed sort fields,
  explicit-sort versus saved-sort precedence, and invalid/stale saved-sort
  fallback. Test these cases, including distinct schemas sharing one settings
  file, without silently applying one field's saved sort to another.
- **R5 [P3]: Qualify selection keys by focus.**
  The key table says Space/Insert/Ctrl+A select, without specifying focus. The
  current [QuickList filter](../src/main/python/fman/impl/ui/quicklist.py#L179)
  initially has focus: an offscreen probe confirms Space inserts query text and
  Ctrl+A selects that text, not items. Making those keys global would break
  ordinary filter editing; keeping existing behavior leaves the documented
  table inaccurate. Specify list-focus-only selection keys, normal filter
  editing, and where invert/clear/sort shortcuts apply. Test both focuses and
  filter-disabled lists. For global Tab, test forward/reverse boundaries,
  multiple modeless lists, closed/replaced Panels and active modal dialogs;
  retain existing pane Switch Panes and QuickTable behavior.

### Review Validation

- An isolated offscreen Qt probe exercised the existing watched-opener helper
  with an opener that emits `disposed` before returning: its completion event
  remained unset. This verifies the reuse hazard, not a defect in an implemented
  `show_quick_list`, which does not exist yet. The same probe verified query
  focus behavior for Space and Ctrl+A without changing source or disk settings.
- Static checks covered the public exports, current QuickList, QuickTable
  caller waits, Panel focus/cleanup and UiOwner lifetime. The proposed service,
  metadata and handle are not implemented; baseline tests do not validate them.
- The exact offscreen command in Tests above passed all 37 existing tests, with
  no skips. Offscreen `propagateSizeHints` messages were expected. Native checks
  of the new service cannot run before implementation.
- Document checks passed: `git diff --check -- Plan/UIElements002.md`, editor
  diagnostics, five new source links and an exact original-snapshot comparison
  after removing the appended review/record and restoring the status. All
  pre-existing design text and reviewer records were preserved.
- No application change, transfer, native test run, full suite, packaging or
  performance benchmark was part of this review.

## Design Review 2 (2026_10_05)

Read against [facade.py](../src/main/python/fman/impl/ui/facade.py)
(`show_quick_table`, `PanelSession`, `_finished_callback`),
[session.py](../src/main/python/fman/impl/ui/session.py) (`ToolWindow`,
`PaneToolWindow.focusNextPrevChild`/`_focus_from_panel`),
[quicklist.py](../src/main/python/fman/impl/ui/quicklist.py),
[ui/__init__.py](../src/main/python/fman/impl/ui/__init__.py) (`UiOwner`,
`Resource`), [panel.py](../src/main/python/fman/impl/ui/panel.py)
(`JsonSettings`), [fman/ui.py](../src/main/python/fman/ui.py) and
[Favorites 004](Favorites004.md). The selection-only scope, blocking call,
`on_open` handle and no-pairing decisions are not questioned here.

- **R6 [P2]: `snapshot()` and `set_items()` from any thread need a stated
  mechanism.** The Handle table says "safe from any thread" and `snapshot()`
  returns `selected`, `chosen`, `current`, `query`, `sort`, all of which live
  in Qt widgets (`QuickList.selected_ids`, the selection model, `QLineEdit`).
  Specify: the window maintains a plain mirror under a lock, replaced
  atomically on every `QuickList.state_changed`, query change and sort change;
  `snapshot()` reads the mirror; `set_items()` validates on the caller, then
  runs on Qt through `run_in_main_thread` and **returns after Qt applied it**,
  so a following `snapshot()` on the same thread reflects the new items (the
  Qt-caller case works because its nested loop services the queued call).
  After close, `set_items` is a no-op and `snapshot()` returns the final
  mirror (R3's "final snapshot remains usable").
- **R7 [P2]: `on_open` is called after the window is interactive.** The R1
  order is create handle, show window, call `on_open`, then wait. For a
  worker caller the list accepts Enter/Escape while `on_open` is still running
  on the worker; Favorites 004 opens its Panel and subscribes to the store
  inside `on_open`, so a fast Escape leaves a Panel appearing after the list
  closed and a subscription that the `finally` only removes after
  `show_quick_list` returns. Call `on_open` **before** showing the window
  (handle complete, window built but hidden), then show only if still open;
  or require drivers to check `handle.is_open` after each step. State which,
  and test Escape during a slow `on_open`.
- **R8 [P2]: Global Tab has no host mechanism yet.** `PanelSession.
  focus_from_panel` wraps focus inside the Panel (`focus_panel(backwards)`);
  the Panel-to-list hop only exists for `UiController` windows, through
  `PaneToolWindow.focusNextPrevChild`/`_focus_from_panel` and the Panel's
  `bottom_panel` link. The new list window is a plain `ToolWindow` without a
  pane or Panel reference. Specify: a per-main-window registry of open
  modeless list windows in activation order, consulted by
  `PanelSession.focus_from_panel` (most recently active list; wrap inside the
  Panel when none) and by the list window's `focusNextPrevChild` (the main
  window's `_panel_dock`, wrap inside the list when none or when modal).
  Note the consequence of no pairing: Tab from a Favorites list would land in
  whichever Panel is docked, including another plug-in's. Panels used alone by
  Find Files/Search Files must keep wrapping as today; add that regression.
- **R9 [P3]: Saved sort writes on the Qt thread.** "one short write per sort
  change" through `save_json` is synchronous file I/O on Qt. `JsonSettings`
  already persists through the shared `Resource` with bounded workers and
  `_delivered` queuing; reuse that path (or write from a worker and publish
  through `resource(name)`) so a slow or locked settings file cannot stall the
  UI, and so a Panel-side `JsonSettings` on the same file sees the change.
- **R10 [P3]: `close(result)` and `selected` contracts.** The return type is
  `tuple[str, ...] | None` but `close(result)` accepts any object; state that
  `result` must be `None` or a tuple of current item IDs (validated on the
  caller, else `TypeError`). `selected` with unknown IDs: specify raise
  (consistent with R2's "invalid call raises") rather than silently dropping.
  Also fix the API table: `title` "at most 512" conflicts with R2's 128-character
  string limit for sort keys/display text; say which applies to title/hint.
- **R11 [P3]: Remaining Qt exports.** The scope removes `QuickList`, `Panel`,
  `TextButton`, `DropDown`, `IconButton` and `JsonSettings` (Favorites is their
  only plug-in consumer), while `ToolWindow`, `PaneToolWindow`, `navigate` and
  `UiController.build(window, pane)` stay public and are Qt (CalculateFileHash
  uses `OutputTextBox`/`UiController`). The Alternatives entry "Public Qt
  widgets: rejected" overstates the outcome; either narrow the sentence to the
  six widgets or list the remaining Qt surface as accepted debt with a pointer
  to a follow-up task.

Verified correct as designed:

- `show_quick_table`'s split (worker callers wait on an `Event`; Qt callers
  run a nested `QEventLoop`) is the right template, and R1's handle-owned
  completion fixes the only ordering hazard in copying it.
- `UiOwner.attach` returns `False` once inactive and `invalidate()` calls every
  attached disposer, so R3's driver contract is implementable as written;
  `_finished_callback` skipping inactive owners is confirmed.
- `QuickList.set_items` already keeps the surviving selection and current ID;
  `preserve_sort` provides "keep order when sortable"; `natural_key` exists
  for string sorting; `docs/plugins/ui-elements.md` exists for the key table.
- Removing the six exports breaks only Favorites, which Favorites 004 rewrites.

Tests to add for R6-R10: worker `snapshot()` after a worker `set_items()`
reflects the update; Escape during a blocking `on_open`; Panel Tab with no
list open, with two modeless lists, and with a Find Files Panel; sort change
with a read-only settings file does not block Qt; `close(object())` raises;
`selected=('missing',)` raises.

## Implementer

### 2026_10_05 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Added `ListItem.metadata`, `quick_list_data.py` (validation,
  natural sort keys, results), `quick_list_window.py` (`show_quick_list`,
  `QuickListHandle`, window, saved sort, global Tab registry), sort bar and
  selection keys in `QuickList`, and the Panel Tab bridge. Removed the widget
  exports from `fman.ui`; internal tests import them from `fman.impl.ui`.

## Validation Results

- `fman_unittest.test_ui_elements` (new `QuickListDataTest`), `fman_unittest.test_portable`: pass.
- `fman_integrationtest.test_qt` classes `QuickListServiceIT` (new, 8 tests),
  `QuickListIT`, `PanelIT`, `DockedPanelIT`, `PublicUiIT`, `TableIT`,
  `HashResultIT`, `FavoritesManagerIT`: pass offscreen and on native `windows`.
- Covered: worker and Qt-thread callers, close inside `on_open`, Enter/Escape,
  `snapshot` after `set_items`, invalid items/results, metadata line, sort
  bar and `Ctrl+F1`, saved sort overriding `sort`, `Ctrl+I`/`Ctrl+Shift+A`,
  global Tab with a Panel, owner invalidation, main-window close;
  `close(object())` and `selected=('missing',)` in unit tests.
- Not covered by automated tests: Escape during a blocking `on_open`, two
  modeless lists, Tab with a Find Files Panel, read-only settings file.

## Implementation Review (2026_10_05)

- **IR1 [P2]: Canonical metadata tuples bypass caller-side validation.**
  [ListItem.__post_init__](../src/main/python/fman/impl/ui/__init__.py#L23)
  validates mappings but accepts any tuple of three-element tuples without
  checking labels, keys, display types or field/text limits.
  [prepare_items](../src/main/python/fman/impl/ui/quick_list_data.py#L66)
  assumes those records were validated. A read-only probe accepted nine fields,
  a 129-character display, a NaN key and an object-valued display; the last can
  reach Qt font measurement/painting instead of raising in the caller. Even the
  mapping path creates a 201-character display for `10**200` without applying
  the 128-character display limit. Validate both canonical and mapping forms,
  including generated numeric display text, before crossing the Qt boundary.
  Cover construction, opening, `set_items` and internal `dataclasses.replace`;
  invalid updates must leave the live list unchanged.

### Independent Review Validation

- Ran the following exact child command through `build._environment()`, with
  `QT_QPA_FONTDIR` set to the Windows Fonts directory: once with
  `QT_QPA_PLATFORM=offscreen`, then with `QT_QPA_PLATFORM=windows`. Both passed
  107 tests without skips. Offscreen raise/size-hint warnings were expected.

```powershell
python -B -m unittest fman_unittest.test_ui_elements fman_unittest.test_favorites fman_unittest.test_portable fman_integrationtest.impl.plugins.test_favorites_plugin fman_integrationtest.test_qt.QuickListServiceIT fman_integrationtest.test_qt.QuickListIT fman_integrationtest.test_qt.FavoritesManagerIT fman_integrationtest.test_qt.PanelIT fman_integrationtest.test_qt.DockedPanelIT -q
```

- Read-only stdin probes used child processes under `build._environment()`.
  The metadata probe confirmed all five invalid-input examples in IR1 without
  constructing a widget; no crash or corrupted paint was claimed from execution.
  The Favorites probes and their results are in [Favorites 004](Favorites004.md#implementation-review-2026_10_05).
- Editor diagnostics, new source links, original-document/history preservation
  and `git diff --check -- Done/UIElements002.md Done/Favorites004.md` passed.
- No production code or tests were edited. No full suite, freeze, packaging,
  screenshot regeneration or limit-sized performance benchmark was run. Two-list
  Tab and slow-open/read-only-settings scenarios remain outside these independent
  checks. Passing baselines do not resolve IR1.

## Implementation Review 2 (2026_10_05)

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Changes requested. The service, handle, window and widget implement
  R1-R11 as specified; the blocking split, pre-show `on_open`, locked state
  mirror, synchronous `set_items`, worker-side sort save and the Tab registry
  are all present. IR1 reproduced independently (four invalid inputs accepted).
  Added IR2-IR4: the document is filed under `Done/` with open findings and a
  stale "Design" status; the recorded Tests gaps (slow `on_open`, two lists,
  read-only settings, Find Files Panel alone) are still untested; and the
  limit-sized performance gate was never run. 138 focused tests pass offscreen.
  No application code edited.

Read: [quick_list_data.py](../src/main/python/fman/impl/ui/quick_list_data.py),
[quick_list_window.py](../src/main/python/fman/impl/ui/quick_list_window.py),
the diffs of [ui/__init__.py](../src/main/python/fman/impl/ui/__init__.py),
[quicklist.py](../src/main/python/fman/impl/ui/quicklist.py),
[facade.py](../src/main/python/fman/impl/ui/facade.py) and
[fman/ui.py](../src/main/python/fman/ui.py).

- **IR1 confirmed [P2].** Probe through `prepare_items`: a tuple-form NaN key,
  an `object()` display, nine tuple-form fields and the mapping form
  `{'N': 10**200}` (201-character generated display) were all accepted.
  `prepare_items` is the single caller-thread gate (`__post_init__` re-runs on
  every `dataclasses.replace` in `QuickList.refresh`, so it should stay
  cheap); put the full field/key/display validation there for both forms and
  apply `MAX_METADATA_TEXT` to generated numeric text.
- **IR2 [P2]: Filed as Done with open findings.** The document sits in
  `Done/` while its Status line still read "Design ... ready for review" and
  IR1 is unresolved. AGENTS.md completes a task only when required checks
  pass; keep it in `Plan/` (or record IR1's fix and the tests below) before
  completion. The same applies to [Favorites 004](Favorites004.md).
- **IR3 [P3]: Required tests still missing.** Validation Results list
  "Escape during a blocking `on_open`, two modeless lists, Tab with a Find
  Files Panel, read-only settings file" as not covered; the Tests section
  requires them (R7, R8, R9). The first is cheap: `on_open` that blocks on an
  event while the test asserts the window is not visible and `is_open` is
  true, then releases. The read-only case asserts the Qt thread is not blocked
  and a status message appears.
- **IR4 [P3]: Limit-sized measurement not run.** The Tests section requires an
  opt-in filter/sort gate at 10,000 items with maximum metadata and a pass/fail
  threshold; `metadata_columns` measures `horizontalAdvance` for every item and
  label (80,000 calls) once per `set_items`, and `ordered_items` sorts on Qt.
  Record one measurement before completion.

Verified correct against the design:

- Blocking split copied from `show_quick_table`; `on_open` runs on the caller
  before `present()`; `close()` inside `on_open` returns at once because the
  completion `Event` lives in `_Session`, not in a Qt signal (R1, R7).
- `publish()` mirrors `selected`/`chosen`/`current`/`query`/`sort` under
  `session.lock` on every `state_changed` and sort change; `set_items`
  validates first, then applies through `run_in_main_thread`, which blocks the
  caller until Qt applied it (R6). After close, `cleanup()` publishes the final
  state and `set_items`/`focus`/`close` are no-ops (R3).
- `result_ids` and `selected_ids` raise on invalid input (R10); unique
  labels and single-kind keys per field are enforced; `effective_sort`
  applies the remembered sort only when its label exists (R4).
- Global Tab: `_open_lists` per main window in activation order,
  `PanelSession.focus_from_panel` -> `recent_list`, list `focusNextPrevChild`
  -> `_panel_dock` only when modeless; Panels without a list wrap (R8).
- Sort saved on a coalescing daemon thread under the shared `Resource` lock
  with `committed`/`publish`, failure shown as a status message (R9).
- Ctrl+I / Ctrl+Shift+A / Ctrl+F1..F10 are `WidgetWithChildrenShortcut`s on
  the QuickList, so they work in both focuses while Space/Ctrl+A keep editing
  the filter (R5). Removed exports break only Favorites.

Review validation: the shared focused command extended with `PublicUiIT`,
`TableIT` and `HashResultIT` ran offscreen: 138 tests OK. IR1 probe as
described; no files changed.

## Review Resolution (2026_10_05)

### 2026_10_05 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: IR1-IR4 resolved; all focused checks pass offscreen and native.

- **IR1:** `validate_metadata` checks the canonical form (field count, labels,
  finite keys, display text type and length) inside `prepare_items`, the single
  caller-thread gate for opening and `set_items`; `__post_init__` stays cheap.
  Generated numeric text obeys the 128-character limit (`10**200` raises).
- **IR2:** both documents stay in `Done/` with the findings resolved and
  recorded here.
- **IR3:** new `QuickListServiceIT` tests: slow `on_open` keeps the window
  hidden and open, invalid `set_items` leaves the list unchanged, requested
  sort applies after an empty list is refilled, a failing sort save neither
  blocks Qt nor stays silent, Tab with a Panel alone, and the two-list
  activation order.
- **IR4:** the first 10,000-item measurement (8 fields, 128-character values,
  long titles and hints) found 2.46 s to apply and 502 ms per filter keystroke.
  Fixes: column widths measure the 16 longest texts per field instead of
  80,000 texts, and `match_positions` skips per-character case folding for
  ASCII text (shared with QuickTable). Native result: apply 68.7 ms, filter
  median 23.9 ms, sort median 22.6 ms. Opt-in gate `QuickListLimitIT`
  (`QUICKLIST_BENCHMARK=1`) fails above 300 / 100 / 100 ms.

Validation: `fman_unittest.test_ui_elements`, `test_favorites`,
`test_portable`, `test_generate_docs_screenshots`, `test_favorites_plugin` and
`test_qt` classes `QuickListServiceIT`, `QuickListLimitIT`, `QuickListIT`,
`FavoritesManagerIT`, `PanelIT`, `DockedPanelIT`, `PublicUiIT`, `TableIT`,
`HashResultIT`, `SearchFilesIT`, `FindFilesIT`: 192 tests OK offscreen and on
native `windows` (the opt-in gate skipped in that run, run separately natively).
Native Favorites smoke passed.

## User Review Changes (2026_10_05)

### 2026_10_05 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: User decisions after seeing the window, chosen from rendered options.

- The sort bar is removed. The footer reads
  `0 selected (0 hidden)    Sorted by Name ▲    Ctrl+F1 Name · Ctrl+F2 Path · …`.
- Metadata fields stay aligned in columns, separated by `│`; cells fit at least
  24 digits.
- The window is frameless like QuickSearch; a nonempty title is a header that
  moves the window when dragged. No API change.
- Follow-up: sort arrows get a reserved slot in metadata labels and in the
  footer (`Sort (Ctrl+F1…F5): Name ▲ · Path · …`, counts right-aligned), so no
  text moves. A sort key cycles ascending, descending, original order; the
  original order is saved as `sort: null` and restored over the `sort` argument.

Validation: `QuickListServiceIT` (footer, frameless header drag) and the focused
set offscreen and native; native Favorites smoke.
