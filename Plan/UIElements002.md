# UI Elements 002: QuickList

Status: Design, 2026_10_05. Ready for review.

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

### Handle

| Member | Behavior |
| --- | --- |
| `snapshot()` | Immutable state: `selected`, `chosen`, `current`, `query`, `sort`. Also valid after closing. |
| `set_items(items)` | Replaces the items; keeps query, sort, surviving selection and current item. |
| `focus()` | Activates the list window. |
| `close(result=None)` | Closes the list; `show_quick_list` returns `result`. |
| `is_open` | `False` once closed. |

Safe from any thread; calls after closing do nothing. If `on_open` raises, the
list closes and the exception propagates.

### Keys

This table goes to the QuickList section of
[docs/plugins/ui-elements.md](../docs/plugins/ui-elements.md).

| Key | Effect |
| --- | --- |
| Space, Insert, Shift+navigation, Ctrl+A, right-click | Select |
| Ctrl+I, Ctrl+Shift+A | Invert, clear the selection |
| Enter, double-click | Return the chosen items |
| Escape | Return `None` |
| `Ctrl+F<n>` | Sort by field *n*; again reverses |
| Tab, Shift+Tab | Filter box and list; in a modeless list also the docked Panel, and back |

Global Tab is host behavior: modal lists and lists without a docked Panel wrap
inside the list; the Panel returns to the most recently active list. Tab in a
pane stays Switch Panes.

### Metadata, Display and Sorting

```python
ListItem('1', 'Projects', 'D:\\Work\\Projects', metadata={'Added': 1})
```

- Metadata maps a label to a string, a number, a `(sort_key, text)` pair or
  `None`. Same labels for every item; at most 8; per field all strings or all
  numbers. Stored as a tuple, so items stay immutable.
- Shown as a third line of `Label value` cells, aligned across rows. Lists
  without metadata look as today.
- Sort fields: title and hint (when labeled), then metadata. The sort bar under
  the filter box shows each field with its key and the active direction;
  clicking a field sorts by it.
- Stable sort, natural for strings, `None` last. No sort means input order.
  Filtering keeps the order when the list is sortable, else ranks as today.
- With `settings`, the host restores `sort`/`ascending` on open and saves them
  on change.

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

- Unit (`fman_unittest.test_ui_elements`): metadata and argument validation,
  sort order, settings handling, `fman.ui` exports.
- Qt (`QuickListIT`, offscreen and native): worker and Qt callers, out-of-order
  modeless closes, Enter/Escape/chosen rule, handle members from a worker,
  `on_open` failure, key table, global Tab, metadata line, sort bar, saved
  sort, 10,000-item timing.

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
   UIElements.md, `docs/plugins/ui-elements.md` and CHANGELOG.

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
