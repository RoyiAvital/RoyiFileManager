# UI Elements 002: QuickList

Status: Design, 2026_10_05. Design Review R1-R5 resolved; ready for review.

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
  with migration notes in CHANGELOG and PlugIn.md.

## Design

### API

```python
show_quick_list(*, items, title='', summary='', modal=True, filter='fuzzy',
                query='', selected=(), title_label=None, hint_label=None,
                sort=None, settings=None, on_open=None) -> tuple[str, ...] | None
```

| Argument | Meaning |
| --- | --- |
| `items` | `ListItem`s with unique IDs; at most 10,000; title at most 512, hint at most 2,048 characters. |
| `title`, `summary` | Window title; one line above the list. |
| `modal` | `True` (default) blocks the main window; `False` for a list driven by a docked Panel. |
| `filter` | `'fuzzy'` (default) or `None`. |
| `query`, `selected` | Initial filter text and selected IDs. |
| `title_label`, `hint_label` | Sort labels, for example `'Name'`, `'Path'`; `None`: not sortable. |
| `sort` | Initial `(label, ascending)`; `None`: input order. |
| `settings` | Plug-in JSON file where the host keeps the sort. |
| `on_open` | `on_open(handle)`, called once when the list is shown. |

- Enter or double-click returns the chosen IDs in input order: the selection
  (including hidden), else the highlighted item. Escape returns `None`.
- Like `show_quick_table`: worker callers wait, Qt-thread callers run a nested
  event loop. Invalid arguments raise in the caller.
- The list closes with the main window and returns `None`.

### Handle

| Member | Behavior |
| --- | --- |
| `snapshot()` | Immutable state: `selected`, `chosen`, `current`, `query`, `sort`. Also valid after closing. |
| `set_items(items)` | Replaces the items; keeps query, sort, surviving selection and current item. |
| `focus()` | Activates the list window. |
| `close(result=None)` | Closes the list; `show_quick_list` returns `result`. |
| `is_open` | `False` once closed. |

Safe from any thread; calls after closing do nothing.

**Opening and closing (R1).** The handle owns the completion: an `Event` and
the result in plain shared state, not a Qt signal. Order: create the handle,
show the window, call `on_open` on the calling thread, then wait only if the
list is still open. A `close()` inside `on_open` therefore returns at once. If
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

Global Tab is host behavior: modal lists and lists without a docked Panel wrap
inside the list; the Panel returns to the most recently active list. Tab in a
pane stays Switch Panes.

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
  at most 32 characters. Strings and display texts are at most 128 characters.
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
  on change; a saved sort overrides the `sort` argument.

## Alternatives

- **Public Qt widgets:** rejected; Qt threading, lifetime and PyQt5 coupling
  leak into plug-ins.
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
- Settings: one read on open, one short write per sort change.

## Tests

- Unit (`fman_unittest.test_ui_elements`): metadata limits, value forms,
  non-finite numbers, label uniqueness, argument validation, sort order,
  settings handling, `fman.ui` exports.
- Qt (`QuickListIT`, offscreen and native): worker and Qt callers, out-of-order
  modeless closes, Enter/Escape/chosen rule, handle members from a worker,
  `close()` and `close(result)` inside `on_open`, `on_open` failure, invalid
  `set_items` leaves the list unchanged, owner deactivation and main-window
  close release the caller, keys in both focuses, global Tab, metadata line,
  sort bar, requested sort across empty and refilled lists, saved sort.
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
