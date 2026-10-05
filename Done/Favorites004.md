# Favorites 004: Favorites Manager on QuickList

Status: Implemented; implementation reviews IR1-IR6 resolved (see Review
Resolution).
Depends on [UI Elements 002](UIElements002.md).

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
  `handle.set_items`. Go To keeps today's folder checks (`exists`, `is_dir`) on
  the action worker, then calls `pane.set_path` with success and error
  callbacks: the list closes only after the pane has loaded the location.
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

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implementation revisions required. IR1-IR3 reproduce premature
  navigation closure, incompatibility with valid saved entries and unreported
  action save failures. Independent checks below. Review only, no application
  implementation changes.

## Implementer

### 2026_10_05 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Rewrote `favorites/ui.py` as a Qt-free driver of a modeless
  `show_quick_list` plus `show_panel` (Rename, Delete, Go To). Go To uses
  `run_command('open_directory')` after worker folder checks. Rewrote
  `FavoritesManagerIT` and the native smoke; all focused checks pass.

## Validation Results

- `fman_unittest.test_favorites`, `fman_integrationtest.impl.plugins.test_favorites_plugin`: pass.
- `fman_integrationtest.test_qt.FavoritesManagerIT` (11 tests), offscreen and native `windows`: pass.
- Native smoke `python -X faulthandler -m fman_integrationtest.favorites_smoke`:
  pass (dock geometry, focus reuse, saved sort, rename, Go To, delete, focus
  recovery; 200-row filter/sort p95 5.02 ms; second monitor unavailable).
- `fman_unittest.test_generate_docs_screenshots`: pass. Screenshots were not regenerated.
- Frozen smoke not run (no freeze requested).

## Implementation Review (2026_10_05)

- **IR1 [P2]: Panel Go To closes on dispatch, not successful navigation.**
  [FavoritesSession.go_to](../src/main/resources/base/Plugins/Favorites/favorites/ui.py#L166)
  returns `True` as soon as `pane.run_command` returns; `action` then closes the
  list. The [command registry](../src/main/python/fman/impl/plugins/command_registry.py#L121)
  has no success return, and [OpenDirectory](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L247)
  starts asynchronous `set_path` and handles permission errors without propagating
  them. Existence/directory checks do not establish that enumeration or navigation
  succeeds. This violates the Panel Go To acceptance rule and removes the user's
  selection/retry surface on failure. Use public navigation completion/error
  callbacks and close only on committed success; reject stale results after
  close/unload or a superseding pane navigation. Add a regression where initial
  checks pass but navigation fails, plus delayed-success and stale-result cases.
- **IR2 [P2]: Existing valid favorites can prevent the manager from opening.**
  [project](../src/main/resources/base/Plugins/Favorites/favorites/ui.py#L21)
  uses the complete normalized URL as its ID and the stored name as its title.
  [QuickList limits](../src/main/python/fman/impl/ui/quick_list_data.py#L12)
  cap each at 512 characters, but FavoritesStore accepts longer URLs and names.
  A pure probe loaded a 569-character URL and, separately, a 513-character name
  with zero invalid entries; projecting either into `prepare_items` raised
  ValueError. One such existing entry prevents all favorites being managed;
  Rename can also save an over-limit name before live refresh then fails.
  Preserve the store's compatibility through bounded stable IDs and safe display
  projection, retaining raw URLs/names for actions, or deliberately expand the
  service bounds. Do not silently drop valid favorites. Test deep Windows paths,
  long stored names, rename across the boundary and later reopening.
- **IR3 [P2]: Action-worker failures are not reported to the user.**
  [on_action/action](../src/main/resources/base/Plugins/Favorites/favorites/ui.py#L125)
  starts a raw daemon thread with only a lock-release `finally`; exceptions from
  `mutate`/saving are not caught. A probe of the actual Delete worker with
  `save_json` raising `OSError('disk full')` reached `threading.excepthook` with
  neither `show_alert` nor `show_status_message` called. The pure mutation test
  checks that failure does not publish, but does not cover this UI boundary.
  Report action failures through the public UI on a live session, preserve the
  selection and records for retry, and suppress stale UI after close/unload.
  Test Delete/Rename write failures and restoration of the action lock; no
  success status or refresh should be published on failed persistence.

### Independent Review Validation

- The [shared focused command and environment](UIElements002.md#independent-review-validation)
  passed all 107 tests offscreen and all 107 on native Windows Qt, without skips.
- Read-only stdin probes under `build._environment()` reproduced IR1-IR3:
  the actual registry/Core OpenDirectory reported a mocked permission denial but
  Favorites still closed; valid saved long URL/name entries failed QuickList
  preparation; a mocked Delete save failure escaped the actual action thread
  through `threading.excepthook`, with no alert/status. All filesystem, pane and
  settings effects were mocked; no favorites were changed.
- Editor diagnostics, source links, exact original-document/history preservation
  and `git diff --check -- Done/UIElements002.md Done/Favorites004.md` passed.
- No production code or tests were edited; no full suite, screenshot regeneration,
  freeze or packaging was run. Passing baseline tests do not resolve IR1-IR3.

## Implementation Review 2 (2026_10_05)

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Changes requested. IR1-IR3 confirmed from the source; the driver
  otherwise follows UI Elements 002's contract (owner attach/detach in a
  `finally`, Panel `on_closed`, store subscription through the handle). Added
  IR4-IR6: a public resolution path for IR1 (`pane.set_path` callbacks), the
  Rename prompt outliving a closed manager, and the task being filed under
  `Done/` with a stale status. 138 focused tests pass offscreen. No application
  code edited.

Read: [favorites/ui.py](../src/main/resources/base/Plugins/Favorites/favorites/ui.py),
the `favorites/__init__.py` diff, `set_bottom_panel`/`remove_bottom_panel` in
[widgets.py](../src/main/python/fman/impl/widgets.py) and `DirectoryPane.set_path`
in [fman/__init__.py](../src/main/python/fman/__init__.py).

- **IR1 confirmed [P2]**, with a public fix: `FavoritesSession.go_to` treats
  `run_command('open_directory')` returning as success. `DirectoryPane.set_path(
  dir_url, callback=None, onerror=...)` is public and already used by Core:
  `callback` fires when the location is loaded, `onerror(exception, url)` on
  failure. Use it directly after the existence/folder checks: `callback` closes
  the list (guarded by `handle.is_open` and a session generation so a result
  from a superseded navigation is ignored), `onerror` alerts and keeps the list
  open. Enter-path Go To (list already closed) can keep `run_command`.
- **IR2 confirmed [P2].** `project()` uses the full normalized URL as the ID
  and the raw stored name as the title; `MAX_ID`/`MAX_TITLE` are 512. Suggest
  `ID = sha1(key).hexdigest()` (stable, 40 chars) with `find()` mapping back
  through the hash, and eliding the display title at the limit while actions
  use the raw record; `rename()` should refuse names over the limit before
  saving.
- **IR3 confirmed [P2].** `action()` runs on a raw daemon thread; `mutate`,
  `save_json` and `show_prompt` exceptions escape to `threading.excepthook`.
  Wrap the body: on exception, `show_alert` when `self.is_open and
  self.owner.active`, release the lock, publish nothing.
- **IR4 [P3]: Rename prompt outlives the manager.** `rename()` blocks the
  action thread in `show_prompt`; if the list closes meanwhile (Escape, unload,
  Find Files docking its Panel, which closes ours through `set_bottom_panel`),
  the prompt stays open and an accepted name still renames. Check `is_open`
  and `owner.active` after the prompt returns before calling `mutate`.
- **IR5 [P3]: Re-open from another pane races the old Panel.** `show_manager`
  closes the previous handle and creates a new session immediately; the old
  session's `dispose()` runs later on its worker and calls `panel.close()` on a
  Panel that `set_bottom_panel` already replaced. `remove_bottom_panel` is
  identity-checked so nothing breaks, but add a test for `Ctrl+B` from the
  other pane while the manager is open, asserting one Panel and one list.
- **IR6 [P3]: Filed as Done with open findings.** Same as UI Elements 002 IR2:
  Status read "Design ... ready for review" while IR1-IR3 are open; keep the
  task in `Plan/` until the fixes and the Qt regressions named above are
  recorded.

Verified correct against the design:

- `attach()` registers `handle.close` with the owner, closes at once when
  `attach` fails, opens the Panel with `on_closed=handle.close`, subscribes to
  the store and seeds the list; `run()`'s `finally` detaches, unsubscribes and
  closes the Panel; `receive()` ignores stale revisions and closed handles.
- Legacy `sort='Recent'` in `Favorites UI.json` maps to input order because
  `Recent` is not a field; `Added` ascending equals Recent.
- `mutate()` releases the store lock before publishing; conflicts are
  reported, not silently dropped; the plug-in imports only `fman`, `fman.fs`,
  `fman.ui` and `fman.url`.
- One manager per main window; `Ctrl+B` from the same pane focuses it.

Review validation: shared focused command (138 tests incl. `FavoritesManagerIT`,
`test_favorites`, `test_favorites_plugin`) OK offscreen; `set_path` signature
read from source. No files changed.

## Review Resolution (2026_10_05)

### 2026_10_05 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: IR1-IR6 resolved; all focused checks and the native smoke pass.

- **IR1:** Go To calls `pane.set_path(url, callback, onerror)`. Panel Go To
  closes the list in `callback`; `onerror` alerts and returns the same URL,
  which ends the navigation without a fallback (and re-raises synchronously,
  caught once). A navigation counter ignores superseded and post-close results.
  Enter Go To uses the same path without closing.
- **IR2:** item IDs are `sha1` of the store key (40 characters); titles and
  hints are shortened with an ellipsis at 512 and 2048 characters. Actions use
  the raw records, so long names and URLs open, rename, delete and Go To.
- **IR3:** action failures show an alert while the manager is open; the lock is
  released and nothing is published, so the action can be retried.
- **IR4:** Rename and Delete pass `allowed=lambda: self.is_open` to `mutate`,
  so a prompt answered after close changes nothing.
- **IR5:** regression test opens the manager from a second pane of the same
  window: one list and one Panel remain.
- **IR6:** see UI Elements 002 IR2.

New `FavoritesManagerIT` tests: navigation failure keeps the list open,
superseded success ignored, late error after close ignored, synchronous
failure alerts once, save failure alerts and retry works, rename after close,
long names and URLs, rename across the 512-character title limit and reopen,
Rename write failure keeps the name, open from another pane. Validation commands and results:
see [UI Elements 002](UIElements002.md#review-resolution-2026_10_05).

## User Review Changes (2026_10_05)

### 2026_10_05 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: User decision: show Added (date), Last opened (date) and Opened (count).

- `FavoritesStore` keeps `Usage(added, opened, count)` per favorite and writes
  optional `added`, `opened` and `count` keys to `Favorites.json`. Invalid values
  are dropped without invalidating the favorite. Add and re-add set `added`;
  eviction and removal drop the usage.
- A successful Go To (Panel or Enter) records `opened` and increments `count` on
  a worker under the store lock.
- The Added sort key is the store position, so favorites saved earlier (no date)
  keep their order; Last opened sorts by time; Opened by count.
- Commit notifications carry `(favorites, usages)`.

Validation: `test_favorites` (usage round trip, eviction, projection) and
`FavoritesManagerIT` (Go To records the use) offscreen and native; native smoke.
