# UI Elements 002: QuickList

Status: Design, 2026_10_05. Ready for review.

## Task

Add `fman.ui.show_quick_list`, a Qt-free list for selecting **one or many**
items from a mutable list. It blocks and returns the chosen IDs, or `None` on
Escape, like `show_quicksearch` and `show_quick_table`. An optional `on_open`
callback receives a handle, so a driver (a Panel, a command, a subscription) can
read the list's state and replace its items while it is open. Items can carry
immutable metadata, shown on an aligned line and sortable.

Motivation: the current QuickList is a public Qt widget that plug-ins must
embed in a host window, wire through signals and pair with a Qt Panel widget.
That exposes Qt threading and object lifetime to plug-ins and ties them to
PyQt5. A plain-data element lets any plug-in, bundled or third-party, build a
list-based tool without Qt. [Favorites 004](Favorites004.md) is the reference
consumer.

## Scope

Included:

- `show_quick_list(...)` and `ListItem.metadata`.
- `QuickListHandle`: `snapshot()`, `set_items()`, `focus()`, `close()`,
  `is_open`.
- Selection only: Space selects, Enter returns the selection. The list never
  acts on items and reports no other keys.
- Sorting by title, hint and metadata with `Ctrl+F<n>` and a sort bar; optional
  saved sort.
- Selection keys: existing ones plus Ctrl+I (invert) and Ctrl+Shift+A (clear).
- Global Tab between a modeless list and the docked Panel.
- Removing the Qt widget exports once Favorites 004 no longer uses them.

Excluded:

- Operations performed by the list, caller-defined keys, context menus and
  buttons inside it. The widget's `Delete` key signal is not used.
- Table layout and per-field filters (QuickTable), multi-key sorting,
  filtering by metadata.
- Watching the file system; items change only through `set_items`.
- Changes to QuickSearch, QuickTable or the Panel service.

Compatibility:

- `fman.ui` is a provisional extension; the fman 1.7.5 API is unchanged.
- `ListItem(id, title, hint='')` keeps its fields; `metadata=()` is added.
- `QuickList`, `Panel`, `TextButton`, `DropDown`, `IconButton` and
  `JsonSettings` leave the public `fman.ui` exports after Favorites 004.
  CHANGELOG and PlugIn.md record the migration to `show_quick_list` and
  `show_panel`. `UiController`, `UiOwner`, `ToolWindow`, `PaneToolWindow` and
  `OutputTextBox` stay (Calculate File Hash still uses them).

## Design

### API

```python
show_quick_list(*, items, title='', summary='', modal=True, filter='fuzzy',
                query='', selected=(), title_label=None,
                hint_label=None, sort=None, settings=None,
                on_open=None) -> tuple[str, ...] | None
```

| Argument | Meaning |
| --- | --- |
| `items` | Iterable of `ListItem`; unique string IDs; at most 10,000 items; title at most 512, hint at most 2,048 characters. |
| `title`, `summary` | Window title; one elided line above the list. |
| `modal` | `True` (default) blocks the main window. `False` keeps it usable, for example with a docked Panel. |
| `filter` | `'fuzzy'` (default) or `None` (no filter box). |
| `query`, `selected` | Initial filter text and selected IDs. Unknown IDs raise `ValueError`. |
| `title_label`, `hint_label` | Sort labels for the title and hint, for example `'Name'`, `'Path'`. `None`: not sortable. |
| `sort` | Initial sort: `None` (input order) or `(label, ascending)`. |
| `settings` | Optional plug-in JSON filename; the host restores and saves the sort there. |
| `on_open` | `on_open(handle)`, called once when the list is shown. |

- Returns the chosen IDs in input order when the user presses Enter or
  double-clicks, or when a driver calls `handle.close(result)`. Returns `None`
  on Escape, window close or `handle.close()`.
- **Chosen** = the selection, including selected items hidden by the filter,
  else the highlighted item. Enter does nothing when nothing is chosen.
- The call is not `@run_in_main_thread`: a worker caller waits on its own
  event; a Qt-thread caller runs a nested event loop (QuickTable's split).
- Arguments are validated, and sort keys prepared, on the calling thread before
  the window appears. Invalid arguments raise there.

### Handle

`on_open(handle)` runs on the calling thread right after the window is shown
and before waiting. If it raises, the list closes and the exception propagates.

| Member | Behavior |
| --- | --- |
| `snapshot()` | Immutable `QuickListState(selected, chosen, current, query, sort)`. Never blocks; returns the last state the list published. After closing it returns the final state. |
| `set_items(items)` | Validates on the calling thread, then replaces the items on Qt. Keeps the query, the sort, the selection of surviving IDs and the current item if it survives. |
| `focus()` | Raises and focuses the list window. |
| `close(result=None)` | Closes the list; `show_quick_list` returns `result` (a tuple of known IDs) or `None`. |
| `is_open` | `False` once the list closed. |

- Every member is safe from any thread. Calls after closing do nothing.
- `set_items` calls are applied in call order; the last one wins.

### Keys

This table is the user documentation: it goes to the QuickList section of
[docs/plugins/ui-elements.md](../docs/plugins/ui-elements.md) (step 7).

| Key | Effect |
| --- | --- |
| Space, Insert, Shift+navigation, Ctrl+A, right-click | Select (existing QuickList keys; list focus) |
| Ctrl+I, Ctrl+Shift+A | Invert, clear the selection |
| Enter, double-click | Close and return the chosen IDs |
| Escape | Close and return `None` |
| `Ctrl+F<n>` | Sort (see Sorting) |
| Tab, Shift+Tab | Move between the filter box and the list; in a modeless list, past the last (or first) control to the docked Panel, if one is open, and from the Panel back to the list |

No other keys and no caller-defined keys.

**Global Tab** (host behavior, no API):

- Only modeless lists take part; a modal list blocks the main window, so Tab
  wraps inside the list.
- The main-window stop is the docked Panel only. Tab in a pane stays Core's
  Switch Panes.
- Without a docked Panel, Tab wraps inside the list.
- Tab past the Panel's last control returns to the modeless list that was
  active most recently; with none open, the Panel keeps today's behavior.

### Metadata

```python
ListItem('1', 'Projects', 'D:\\Work\\Projects', metadata={
	'Added': 1,
	'Used': (1759580400000000000, '2026-10-04 13:20')})
```

- A mapping from label to value. Every item has the same labels in the same
  order. At most 8 fields; labels are nonempty, unique, at most 32 characters
  and differ from `title_label` and `hint_label`.
- A value is a string or number (`int` or finite `float`; not `bool`), a pair
  `(sort_key, text)`, or `None` (shown empty, sorted last).
- Within a field, sort keys are all strings or all numbers. Strings sort with
  the host's natural, case-insensitive key. Display text is at most 128
  characters.
- Stored on `ListItem` as a tuple, so items stay immutable and hashable.

### Display

```
[ filter                                                       ]
 Name Ctrl+F1 · Path Ctrl+F2 · Added Ctrl+F3 ▲
 Projects
 D:\Work\Projects
 Added ▲ 1
```

- Items with metadata get a third line in the hint style: `Label value` cells.
  Each field has one width for the whole list (label plus widest value, capped
  at 24 average characters, longer values elide), so cells line up across rows.
- The active sort field shows a bold label with ▲ or ▼.
- Without metadata, rows look exactly like today's QuickList.
- The filter matches the title and hint, not metadata.

### Sorting

- Sort fields, in key order: title (when labeled), hint (when labeled), then
  metadata fields; at most 10.
- `Ctrl+F<n>` sorts by field *n* ascending; again reverses. Works from the
  filter box and the list.
- The sort bar, shown only when sort fields exist, lists each field with its
  key; clicking an entry acts like its key; the active entry shows its arrow.
  When narrow, key texts drop first (they stay in tooltips).
- No sort means input order. There is no "unsorted" third state; callers expose
  input order as a field when needed.
- Stable sort; `None` last in both directions. Sorting keeps selection and the
  current item.
- With sort fields, filtering keeps the current order; without them, matches
  are ranked as today.

### Persistence

- With `settings`, the host reads `sort` (label) and `ascending` (boolean) with
  `load_json` when opening; they override the `sort` argument. Unknown labels
  mean input order; invalid values are ignored.
- Each sort change is saved with `save_json` under the file's
  `settings_resource` lock on a short-lived thread, changing only those two
  keys. A failed save shows a status message.

## Alternatives

- **Public Qt widgets (today):** rejected; Qt threading, object lifetime and
  PyQt5 coupling leak into every plug-in.
- **Operations in the list:** rejected; managing items is the caller's job,
  and host-run operations brought most of the complexity of earlier drafts.
- **Caller-defined keys (`keys`/`on_key`):** rejected; focus scope, built-in
  conflicts, concurrent calls and prompt stacking add edge cases. Actions live
  in a Panel.
- **Explicit list/Panel pairing argument:** rejected; global Tab gives keyboard
  access without coupling the two APIs.
- **A mode flag returning a handle or a result:** rejected; one return type, and
  interactivity as an add-on through `on_open`.
- **Non-blocking call returning a handle with `wait()`:** rejected for
  consistency with QuickSearch and QuickTable, which block and return.
- **Metadata as table columns:** rejected; QuickTable is the column element.
- **Footer key hint for sorting:** rejected; not clickable and cannot show the
  current sort.

## Runtime Effects

- Startup and idle: none.
- Open list: memory proportional to items plus prepared sort keys (at most
  10,000 items x 10 fields).
- Filtering and sorting run synchronously on Qt; bounded by the item and text
  caps and measured at the limits.
- Settings: one read when opening, one short-lived thread per sort change.
- Disabled path: without metadata, labels, `on_open` and `settings` there is no
  sort bar, no metadata line and no settings I/O.
- Cancellation: not applicable.

## Tests

Unit (`fman_unittest.test_ui_elements`):

- `ListItem.metadata` validation, normalization and hashability.
- `show_quick_list` argument validation: limits, duplicate IDs, unknown
  `selected`, labels, `sort`, `settings` name.
- Sort order: natural strings, numbers, `None` last both ways, stability.
- Settings: unknown labels, invalid values, other keys kept.
- Public `fman.ui` exports: new names present; Qt widget names absent after
  Favorites 004.

Qt integration (`QuickListIT`, offscreen and native):

- Worker and Qt-thread callers; two modeless worker callers closed out of order
  each return on their own close.
- Enter, double-click, Escape, window close; chosen rule including hidden
  selections; Enter with nothing chosen.
- Handle: `snapshot` during and after the list; `set_items` from a worker keeps
  query, sort, surviving selection and current; `close(result)`; `focus`; calls
  after closing ignored.
- `on_open` raising closes the list and propagates.
- Delete and other unlisted keys do nothing.
- Global Tab: modeless list to docked Panel and back, both directions; wraps
  without a Panel and in a modal list; with two modeless lists the Panel
  returns to the most recently active one; Tab in panes still switches panes.
- Ctrl+I, Ctrl+Shift+A; footer counts with a filter.
- Metadata line alignment, elision, empty cells, active-sort marker; unchanged
  look without metadata.
- Sort bar visibility, keys, reversal, clicks, narrow widths; filter order rules.
- Saved sort restored, saved on change, survives Escape.
- 10,000 items with maximum text and 8 fields: filter and sort latency recorded.

Manual: native 100/150% look of the metadata line and sort bar.

Focused command (offscreen and `windows`):

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_ui_elements','fman_integrationtest.test_qt.QuickListIT'], env=env).returncode)"
```

## Implementation Steps

1. `ListItem.metadata`, validation and sort-key preparation; unit tests.
2. Window and `show_quick_list` on the existing widget, now host-private: caller
   split, modal, summary, filter, initial query and selection, Enter/Escape
   result; Qt tests.
3. Handle (`snapshot`, `set_items`, `focus`, `close`) and `on_open`; Qt tests.
4. Ctrl+I, Ctrl+Shift+A and global Tab; Qt tests.
5. Metadata line, sort bar, `Ctrl+F<n>`, order rules, settings persistence;
   tests.
6. Measurement at the limits.
7. After Favorites 004: remove the Qt widget exports; PlugIn.md, UIElements.md,
   CHANGELOG, and `docs/plugins/ui-elements.md`: replace the widget section
   with `show_quick_list`, the key table above and a new screenshot.

## Acceptance Criteria

- A plug-in shows a list with `show_quick_list` without Qt code and gets the
  chosen IDs, or `None`.
- Through the `on_open` handle, a driver reads the state and replaces items
  while the list is open, from any thread.
- The list only selects and returns; it never acts on items itself.
- In a modeless list, Tab reaches the docked Panel and returns.
- Metadata appears on one aligned line; `Ctrl+F<n>` and the sort bar sort by
  title, hint and each field; a saved sort is restored.
- Lists without metadata look and behave like today's QuickList.
- After Favorites 004, `fman.ui` exports no QuickList or Panel Qt widgets.
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
