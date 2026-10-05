# Favorites 004: Favorites Manager on QuickList

Status: Design, 2026_10_05. Ready for review. Depends on
[UI Elements 002](UIElements002.md).

## Task

Rebuild the Favorites Manager on `show_quick_list` and a docked `show_panel`,
with public APIs only, as a third-party plug-in would. Sorting moves to the
QuickList; the Panel only offers **Rename**, **Delete** and **Go To**.

## Scope

- Included: `Ctrl+B` / `show_favorites(query='')` opens a modeless list (Name,
  Path, Added) and a Panel; sorting by Name, Path and Added; live refresh.
- Excluded: Used/Count, file favorites, changes to the store, adding favorites
  or the hidden legacy commands.
- Compatibility: `Favorites.json` and command IDs unchanged. In
  `Favorites UI.json`, `sort` = `Name`/`Path` restores that sort; `Recent`
  means input order.
- Behavior changes: the Sort By drop-down becomes the sort bar; the Delete key
  in the list no longer deletes.

## Design

```python
result = show_quick_list(items=project(records), title='Favorites Manager',
	modal=False, query=query, title_label='Name', hint_label='Path',
	settings='Favorites UI.json', on_open=session.attach)
```

- Items: ID = `FavoritesStore.key(url)`, title = name, hint = path, metadata
  `{'Added': position}` (1 = most recent, so Added ascending = Recent).
- `session.attach(handle)` registers `handle.close` with the plug-in's
  `UiOwner` (closing at once if the owner is inactive), opens the Panel and
  subscribes to store changes, which call `handle.set_items`. After
  `show_quick_list` returns, a `finally` detaches, unsubscribes and closes the
  Panel.
- When the list closes, the Panel closes; when the Panel closes, the list closes.

```python
show_panel(owner=owner, pane=pane, rows=((Action('rename', 'Rename'),
	Action('delete', 'Delete'), Action('go_to', 'Go To')),),
	on_action=session.on_action, on_closed=handle.close)
```

| Action | Trigger | Behavior |
| --- | --- | --- |
| Go To | Panel, Enter, double-click | One chosen favorite (one selected, or the highlighted one). From the Panel the list stays open until navigation succeeds. Enter closes the list first. A failure shows an alert. Several chosen: status "Select one favorite for Go To". |
| Delete | Panel | Chosen favorites; no confirmation, as today. |
| Rename | Panel | Highlighted favorite, through `show_prompt`. |

- Actions read `handle.snapshot()`, change the store on a worker and call
  `handle.set_items`. Go To keeps today's folder checks and `navigate`.
- One manager per main window; `Ctrl+B` while open calls `handle.focus()`.
- Imports only `fman`, `fman.url`, `fman.fs` and `fman.ui`; no PyQt5,
  `fman.impl` or Core.
- Removed: `FavoritesController.build`, the widget session, Qt widgets and the
  window `QShortcut`.

## Alternatives

- **Favorites as a pane (Favorites 003):** superseded by user decision.
- **Keep the Qt widget manager:** rejected; it cannot serve as a third-party
  example.
- **Sort drop-down in the Panel:** rejected; sorting is a QuickList feature.

## Runtime Effects

Nothing runs until `Ctrl+B`. An open manager holds one waiting command worker,
one list, one Panel and one store subscription; actions save once each.

## Tests

- Unit (`fman_unittest.test_favorites`): projection, Delete, Rename, Go To
  rules, legacy `sort`, no Qt or host imports.
- Qt (`FavoritesManagerIT`, offscreen and native): open, every action and
  trigger, Go To failure from Panel and Enter, sorting and saved sort, live
  refresh, Tab to the Panel, `Ctrl+B` focus, closing either surface, plug-in
  unload and main-window close release the command, starting with no favorites.
- `test_favorites_plugin` load/unload; `favorites` screenshot capture.

## Implementation Steps

1. Projection and actions with unit tests.
2. Manager on `show_quick_list` and `show_panel`; remove the widget code.
3. Qt, plug-in and screenshot tests.
4. Favorites README, `docs/tools.md`, `docs/shortcuts.md`, CHANGELOG.

## Acceptance Criteria

- The manager uses a QuickList (sortable by Name, Path, Added) and a Panel with
  Rename, Delete and Go To only.
- All Favorites 002 features remain except the listed behavior changes.
- No Qt or host-internal imports; focused tests pass offscreen and native.

## Reviewers

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Initial design at the user's request: Favorites Manager on
  `show_quick_list` plus a docked `show_panel` with Rename, Delete and Go To;
  sorting moved to the QuickList; public APIs only. Ready for review.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: User decisions: Enter keeps QuickList's return and Favorites runs
  Go To on a single chosen favorite, a failure after Enter only alerts (D1);
  Panel Go To keeps the list open until navigation succeeds; Rename and Delete
  are Panel buttons only (no list keys); global Tab reaches the Panel (D2).
  Ready for review.

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
- Effort: High
- Context Window: 272K
- Outcome: Applied UI Elements 002 review R3: `handle.close` registered with
  the plug-in owner and released in a `finally`; unload, main-window close and
  empty-start tests added. Ready for review.
