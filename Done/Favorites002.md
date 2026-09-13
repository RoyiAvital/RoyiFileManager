# Favorites 002: Favorites Manager

## Task

Replace the Ctrl+B favorite picker with a compact Favorites Manager built from
QuickList and a separate bottom Interaction Panel. Keep Add current folder to favorites for
the active pane's current path. Priorities: correctness, simple UI, performance.
Status: Done, accepted by the user on 2026_09_13. Source implementation and
focused/native validation are complete. The user reported completion of the
full test suite and explicitly waived the remaining checks for task closure.
Frozen packaging and outstanding manual checks remain unverified, not passed.
The completion record below supersedes historical Pending/gate statements.

This follows [Favorites 001](../Done/Favorites001.md) and consumes the proposed
[UI Elements](../Plan/UIElements.md) toolkit. It supersedes that plan's Favorites
Move Up/Move Down pilot: this manager uses Recent/Name/Path sorting, not manual order.

Favorites is also the reference plug-in for exported UI components. An external
plug-in must be able to recreate its QuickList, configuration panel, prompts,
background work and tracked navigation without fman.impl, Core imports or private
host attributes. The provisional fman.ui extension is the chosen public surface.

## Scope

- Ctrl+B opens/focuses Favorites Manager for the invoking directory pane.
- QuickList displays each bookmark's Name and human-readable Path, with its
  optional fuzzy text filter enabled and multi-selection by Ctrl/Shift gestures.
- A separate bottom panel contains Sort By (Recent/Name/Path), Delete, Rename and
  Go To. It spans the main window directly above its status bar. The dock's small
  close icon and Escape end the paired panel/QuickList session.
- Favorites are folder-only. Add current folder to favorites saves the active
  pane's folder path, never the highlighted or selected file. Saved file targets
  are rejected on Go To, without automatic deletion or conversion.
- These are the only two discoverable bookmark commands in the Command Center.
- No Move Up/Move Down, drag reorder, editable paths, groups, file deletion,
  recursive filesystem search, or checkbox selection inside QuickList.
- Preserve the public fman 1.7.5 plug-in API, existing bookmark data, duplicate
  identity rules, capacity limit and add/eviction confirmation behavior.

## Design

### Revised Component Composition

The shared component is now called Panel, with exported `set_panel(panel)` hosting.
Favorites action buttons expand with application width, capped at 160 logical
pixels per button. Content-derived minimum widths prevent clipped labels; icon
controls stay compact. Older names are compatibility aliases only. This changes
layout sizing without new timers, settings, I/O or file-pane model work.

Follow the revised three-component contract in [UI Elements](../Plan/UIElements.md).
QuickList is a reusable view, not a window, and supports file-pane selection
keys including Space and Insert. Favorites uses a frameless QuickList host and a
separate themed Panel docked across both file panes, directly above the main
window status bar. A native close icon at the dock's upper right ends the UI
session, including QuickList, prompts, subscriptions and pending navigation. It
does not unload the plug-in package or undo committed edits. Escape also closes
the session. The Sort By drop-down binds to the sort key in
Favorites UI.json; Recent is the default only when no setting exists. Reopening
restores the saved sort and starts with an empty filter. Actions do not write
configuration. This supersedes prior title-bar/close-icon and session-only sort
requirements; historical reviewer records remain unchanged.

The shared exported `PaneToolWindow.set_panel(panel)` owns placement and
disposal; Favorites adds no private host access. The main-window layout reserves
space beneath the existing splitter and reclaims it when closed. One docked
session is allowed per main window; opening from another pane replaces the old
one. No new background jobs, persistence or filesystem work is introduced by
docking. A floating footer and a movable/undockable QDockWidget were rejected in
favor of the requested fixed strip. Tests cover geometry, native close/reopen,
Tab/Escape, prompt rejection, unload, replacement and stale completion; native
source smoke verifies 100/150/200% DPI. This supersedes earlier same-window
multi-manager and no-close-icon requirements, not historical review records.

### Existing Ownership

The bundled [Favorites commands](../src/main/resources/base/Plugins/Favorites/favorites/__init__.py)
currently use show_quicksearch for navigation and separate remove/rename commands.
The [store](../src/main/resources/base/Plugins/Favorites/favorites/store.py)
owns Name/URL records, normalized URL identity, validation and recency-based
storage. Reuse that store and its transaction semantics. The current module-local
lock is insufficient across plug-in reload while an old commit is finishing;
use the reload-safe transaction owner described below. Do not introduce a second
bookmarks file, duplicate navigation logic or a new identity scheme.

The shared toolkit owns QuickList, the bottom panel, focus, stable selection and
Qt widgets/models. A bundled Favorites UI adapter owns operation dispatch and
store integration. Only exported host APIs may be imported by that adapter. No operation
controls or action widgets are embedded in the list rows.

FavoritesController.build(window, pane) is the canonical construction hook.
It composes the exported controls in a generic PaneToolWindow and attaches a
plain FavoritesSession for records/actions. There is no Favorites host-widget
subclass. Shown/busy/disposed notifications connect domain behavior to the host.
General Window/DirectoryPane APIs expose no widgets or Qt signals; pane closure
uses on_closed(callback), returning an unsubscribe function. Parent/theme/dock
access is internal, while fman.ui remains an opt-in Qt component API. Only Panel
and PaneToolWindow.set_panel are exported; the unshipped aliases are removed.

### Layout and Navigation

QuickList now transfers focus from its filter to the list on Up/Down and
Page Up/Down, allowing the next Space to toggle selection. Right-click toggles
one row without activation and preserves other selections. Favorites enables
the optional fuzzy filter; other plug-ins may omit it entirely. Focus and mouse
behavior are implemented in the shared exported component, not this adapter.

QuickList occupies the main area with a fuzzy query field and rows showing both
Name and Path, so duplicate names remain distinguishable. Use the existing
application theme, reusing Quicksearch fonts, colors, spacing, row/search styling
and match highlights, with distinct current and multi-selection states. Long
paths elide visually with full text available in a
tooltip; this is a list presentation, not a dependency on Phase B table widgets.
The compact Sublime Text-style main-window dock owns the sort drop-down and actions.

On opening, highlight the first visible item but start with no selected items.
Keep current/highlight and selection separate. Clicking selects without closing;
Ctrl/Shift and keyboard selection follow the shared QuickList contract. Moving
focus to the bottom panel preserves both current identity and selected IDs.
Show total-selected and hidden-selected counts.

Enter from the list and double-click invoke Go To. Enter in the fuzzy query
field invokes Go To when a current item exists; inside a rename prompt
or a focused panel control it retains that control's normal behavior. Never
bind global Enter to Delete. Escape closes the manager without
performing a new action; an open prompt consumes Escape before the manager.
Previously saved rename/delete operations are not undone by closing.

Del while the list owns focus invokes the same target capture and immediate deletion
as the Delete button. In the query field or rename prompt it edits text normally;
do not let the key fall through to file deletion in the directory pane.

Keep one docked manager per main window; repeated Ctrl+B from the same pane focuses
the existing one. Opening for another pane closes the previous session.
Route Ctrl+B locally while the manager or its children own focus; it focuses the
same manager without resetting its query or sending the key to a directory pane.
Do not forward arbitrary manager keystrokes into the pane command dispatcher.
The manager retains its target pane even if another pane becomes active. Close
it if that pane/window is destroyed. Empty bookmarks still open the manager with
an empty state and disabled actions rather than silently refusing to open.

### Fuzzy Filter and Sort

- Fuzzy filtering is enabled for this consumer. Match the query against Name or
  human-readable Path using the shared fuzzy matcher; no path existence checks
  or filesystem enumeration on query changes. Highlight matches in the field
  that matched, with correct Unicode character offsets.
- Sort By is a fixed-choice bottom-panel drop-down: Recent (default), Name or Path.
  Recent displays store order, most recently added or re-added first; no sort key
  or access timestamp is required. Opening a favorite does not change this order.
  Name and Path are ascending, case-insensitive, deterministic text orders. For
  Name use name.casefold(), displayed_path.casefold(), then canonical identity;
  for Path swap the first two keys. Names need not be unique.
- The selected sort remains authoritative during fuzzy filtering: filtering
  determines membership/highlights, not relevance order. Add a consumer-selectable
  preserve-sort mode to the shared filter contract rather than hard-coding a
  Favorites exception. Other consumers may retain relevance ranking.
- Sorting/filtering never changes the underlying store order or bookmark
  identities. Preserve selected IDs even when hidden; clearing the query restores
  all items in the chosen sort. Keep current if visible, otherwise highlight the
  first visible result or none without changing the selected set.
- Rename can move a row or hide it under the active filter. Recompute the view
  using its stable identity; preserve selections and apply the same current-row
  fallback. No-match filters may still have hidden selections eligible for Delete.
- Sort choice persists via JsonSettings in Favorites UI.json; query is session-local.
  Restore the saved sort (Recent if unset) and an empty query on an ordinary
  fresh manager session. Preserve the existing show_favorites(query='...') command
  argument: a nonempty supplied query seeds a new session or replaces the query
  in an existing session using the usual selection-preserving filter rules.
  An empty/default query only focuses an existing session without clearing it.
  Bookmark schema stays unchanged; only the separate UI settings file stores sort.

On refresh after an Add/re-add, Recent reflects the new store order; re-adding an
unchanged entry does not move it in Name/Path order. Rename preserves Recent order.

### Bottom Actions

| Control | Targets and Behavior |
| --- | --- |
| Delete | All selected favorites, including hidden selections; if selection is empty, the highlighted favorite only. |
| Rename | The highlighted favorite only, regardless of multi-selection. |
| Go To | Navigate the invoking pane to the highlighted favorite, then close on successful navigation. |
| Escape | Close the host; perform no bookmark operation. |

Delete is enabled when selection is nonempty or a highlighted item exists. Its
tooltip/accessibility description states the fallback, for example "Delete
selected favorites, or the highlighted favorite when none are selected". This
is an explicit consumer exception to the toolkit's default no-current-fallback
destructive-action rule. Rename and Go To are disabled without a highlighted item.

Delete captures immutable bookmark records when invoked and immediately submits
them to the existing mutation worker, without confirmation. This applies to the
button and list Del key, including hidden selections and highlighted fallback.
Only bookmarks are removed, never files/folders. Keep the manager open; retain
busy guards, conflict checking, failure alerts and committed-snapshot refresh.
This user-directed exception is local to Favorites; shared confirmation APIs,
other plug-ins, legacy commands and Add/capacity prompts are unchanged. This
supersedes the confirmation requirements in historical reviewer records below.

Rename opens a prompt prefilled with the highlighted Name. Cancel or blank input
does not write; otherwise apply existing name validation and keep Path unchanged.

### Navigation Completion Prerequisite

Go To retains the current exists() pre-check and alert policy, including supported
virtual filesystem URLs and the existing NotImplementedError fallback. Run checks
off Qt, then require is_dir before dispatch. A file target reports an error and
leaves the manager open without dispatching navigation. Keep saved data intact;
do not scan all entries on load or silently convert files to their parents.
Shared OpenDirectory retains its file behavior for other callers; Favorites
does not offer file navigation. This folder-only decision supersedes the earlier
file-favorite requirements and historical review responses below.

The current [set_path](../src/main/python/fman/__init__.py) callback is useful but
not a complete success/failure contract. The [model](../src/main/python/fman/impl/model/model.py)
can consume iteration errors, omit callbacks on disappearance, or acknowledge
initial rows before a revisit reload. Same-path callbacks can be synchronous;
empty-directory callbacks can run on the worker. Location-changed alone is not
success. Nor is a normal return from run_command proof of completed navigation.

Before manager integration, define and test an internal navigation request with
one terminal outcome: success, failure or superseded. Correlate it with the pane,
source-model instance and request generation; marshal results to Qt. Set pending
state before starting work. Success requires the requested transition's initial
folder listing to finish without a listing failure. Same-path requests must
verify that initialization is complete; revisit
reload failures must not be hidden behind an earlier cached acknowledgement.
Attribute errors to this request, clear busy state on failure/supersession, retain
the manager and report failures once. Reject late results and unrelated location
events. An ordinary pane navigation supersedes a pending manager request.

Preserve the existing open_directory command/listener interception path and
before_location_change hooks. Directly substituting set_path would bypass
on_command hooks. Add only the narrow internal request/result plumbing needed
through dispatch and model initialization, leaving public command arguments and
the fman API unchanged. A rewritten command that cannot participate in tracked
navigation must produce an explicit unsupported/failure outcome, not an inferred
success or an indefinitely busy manager. Do not send it an extra callback argument
that existing plug-ins do not accept. Prove ordinary, rewritten and untracked
command behavior in prerequisite tests; resolve the exact internal integration
in UI Elements before implementing this adapter.

Closing invalidates the request and prevents checks that finish later from
starting navigation. Recheck authorization at the pane-mutation handoff, not only
before a potentially blocking exists/is_dir call. Once a pane transition has
started, closing does not roll it back or promise to interrupt filesystem I/O;
it only detaches the manager and rejects late UI results. Bound outstanding
checks across repeated open/close and do not wait for them on Qt.

### Commands and Compatibility

Expose Favorites Manager on Ctrl+B and Add current folder to favorites in the
Command Center. Retain Favorites terminology in UI, data and documentation;
"bookmark" may be an additional search alias, not a product rename.
Keep the existing show_favorites command ID routed to the manager and
add_current_folder_to_favorites routed to the unchanged add behavior, preserving
custom bindings, the query argument and saved command invocations. Keep remove_from_favorites and
rename_favorite callable as compatibility entry points, but omit them and their
aliases from discovery. They may reuse the new adapter without creating another
discoverable command. Return False from RemoveFromFavorites.is_visible() and
RenameFavorite.is_visible(): CommandPalette._get_all_commands filters through
is_command_visible(), which calls is_visible() before enumerating aliases.
Direct run_command and key-binding execution do not check that visibility flag.
Test both palette omission and direct invocation; do not unregister those IDs.

The main README and bundled Favorites README must document the new Ctrl+B flow,
two visible commands, sorting/filtering, Delete fallback, and compatibility IDs
when implemented. Do not add planning work to the changelog.

### Threading, Persistence and Failure

Command bodies/operation I/O run off Qt. Toolkit callbacks and widget/model
updates run on Qt and remain short. Pass immutable bookmark snapshots and action
targets across the boundary. Never hold the store lock while prompting, waiting
for Qt, or navigating. Use queued results with session/generation checks.

Keep the manager open across Rename/Delete, including canceled prompts and failed
operations. A modeless controller is appropriate for this consumer; the generic
blocking run_quicklist remains optional and must not force close/reopen for every
management action. Disable duplicate action submissions while busy; query, sort,
highlight and surviving selections persist across updates.

For requested mutations, reload the latest store under its transaction lock,
compare captured (url, name) records with current records, mutate by canonical
URL and save once per batch. Skip/report missing or changed records and preserve
unrelated concurrent additions. An identical remove/re-add is equivalent for
these operations; no store mutation-generation mechanism is required.
Report conflicts, refresh from the authoritative store, and retain failed targets
where they still exist. A save failure must not be presented as success.
Config.save_json writes differential JSON before replacing its cache entry;
FavoritesStore.load/to_json produce independent data. Keep that fresh-object
pattern rather than mutating the cached object in place. A failed save then
leaves the previous cache value intact; retain the manager's last committed view
and report the failure rather than attempting a speculative cache rollback.

Sorting is only a projection: keep existing stored recency for capacity eviction
and Add/re-add behavior. Mutable data remains under UserSettings through existing
JSON APIs. No Registry writes, automatic directory scans or external JSON edits.

### Live Refresh and Reload Ownership

All successful Add/re-add, manager mutations and legacy remove/rename commands
publish a committed-change notification after releasing the transaction lock.
Assign an in-memory snapshot revision under that lock and deliver an immutable
snapshot through queued Qt delivery. No-op/canceled operations and failed saves
do not publish a successful change. These revisions order UI snapshots only;
they are not persistent bookmark versions or a new conflict-detection scheme.

Open managers subscribe while alive. Apply only newer snapshots, preserving sort,
query and surviving selected/current identities; remove vanished selections and
recompute hidden counts. Capture the initial snapshot and subscription without
a lost-update window. A refresh never changes already captured prompt targets;
mutation still validates them against the latest store. Two panes' managers
and old command IDs must converge on the same committed data without polling.
An idle application has no manager subscriptions or refresh work.

Register the Favorites adapter/controller with the toolkit's loader-bound owner
and load generation. Unload must invalidate sessions and pending prompts/actions
before unregistering code, disconnect notifications and dispose widgets on Qt.
Callbacks from the old generation cannot start new work after reload.

The transaction owner must outlive a Favorites module reload: use a narrowly
scoped internal host-owned coordinator for this settings resource, shared by old
and new generations. It owns transaction serialization and snapshot revision,
not Favorites validation or a second data cache. Keep the existing reload-latest,
compare, save-once transaction body and fresh JSON objects. Commits already begun
finish under the same serialization boundary used by the new generation; never
wait for them on Qt or while holding a UI lock. Pending old-generation mutations
that have not begun are rejected. Specify and test this owner in the prerequisite
toolkit integration; a new module-local lock is not sufficient.

### Toolkit Requirements

- Modeless QuickList with Ctrl/Shift selection, separate current item and
  total/hidden-selection counts; one session per pane with focus-existing behavior.
- Quicksearch-themed title/hint rows, full-path tooltips and accessible current
  and selection states.
- Fuzzy filtering over Name/Path with preserve-sort mode and Unicode highlight
  offsets; stale-filter rejection and disabled/no-op support in the shared element.
- Main-window bottom panel with fixed-choice drop-down, action buttons and a
  host-owned close icon; explicit current/selected target capture and immediate fallback deletion.
- Prompt-free bookmark deletion, list-scoped
  Del routing and query Enter navigation; safe focus and Escape handling.
- Persistent sessions across management actions, queued Qt updates, disposal
  guards, loader-bound controller ownership and prerequisite shared Qt integration
  helpers. Internal navigation outcomes and reload-safe transaction ownership
  must be resolved before this consumer's integration.

### Implemented Public and Host Contracts

Favorites commands call `UiController.show(pane, query)`. The host performs Qt
dispatch, owner validation, window construction, reuse, query seeding and focus.
The controller's `build(window, pane)` composes public widgets; its optional
PaneToolWindow subclass contains Favorites reaction methods, not construction or
thread dispatch. Public services and exact signatures are documented in
[UI Elements](../Plan/UIElements.md#plug-in-api). No private host access is permitted.

- [Shared primitives](../src/main/python/fman/impl/ui/__init__.py) provide immutable
  ListItem records, Unicode offset mapping, loader-invalidated UiOwner sessions,
  a reload-stable settings Resource and two nonqueued, on-demand worker slots.
  There are no idle feature threads. Saturation reports that existing operations
  must finish; repeating the manager command can retry an unsuccessful initial load.
- [QuickList](../src/main/python/fman/impl/ui/quicklist.py) and
  [BottomPanel](../src/main/python/fman/impl/ui/panel.py)
  keep current and selected identities separate; Favorites selects preserve-sort
  filtering. Matching reuses Core's subsequence matcher with original-code-point
  offsets and UTF-16 conversion during painting. Theme selectors explicitly cover
  QuickList; compact button padding overrides the wide Windows dialog default.
- [ToolWindow](../src/main/python/fman/impl/ui/session.py) delivers queued results,
  uses nonblocking owned prompts and invalidates on close/Escape/unload. The
  [Favorites adapter](../src/main/resources/base/Plugins/Favorites/favorites/ui.py)
  captures immutable action records, projects Recent/Name/Path and coalesces
  committed snapshots before Qt delivery. Session query is not persisted;
  the panel's Sort By choice is saved separately through JsonSettings.
- [NavigationRequest](../src/main/python/fman/impl/navigation.py) travels through
  existing command and location hooks using worker-local internal context. No
  callback argument is added to public commands. A source-model instance owns the
  tracked initialization; pane generations reject supersession. Tracked same-path
  and revisit navigation use fresh initialization/cache clearing rather than an
  early cached acknowledgement. Tracked filesystem wrappers propagate listing
  failures; ordinary wrapper behavior is unchanged. Favorites rejects file targets
  before dispatch; shared command cursor handling remains compatible for other
  callers. Every terminal outcome settles its
  waiter; public navigate also enforces a configurable 30-second Qt deadline from
  admission, including prechecks and command dispatch. A
  separate two-slot semaphore covers actual tracked initialization, including
  filesystem I/O that continues after cancellation. This prevents cancellation
  from admitting unbounded blocked model workers. Existence checks and command
  dispatch can still block on external filesystem calls within the original
  bounded operation slots; the timeout cannot interrupt those calls.
- Public PaneToolWindow uses Window.tool_parent(), Window.get_quicklist_item_css()
  and DirectoryPane.closed; private Qt storage stays in the host. These are
  additive extension accessors, preserving legacy fman signatures. MessageDialog uses standard dialog,
  label, scroll area and button-box widgets; confirmation defaults to No and is
  window-modal. BottomPanel composes plug-in-provided controls and uses theme-owned
  padding. Resource.committed acquires its own reentrant lock; callers continue
  to hold the same transaction lock around snapshot creation and persistence.
- The loader binds UiController subclasses to a new owner for every load,
  invalidates owners before unregistering code, and removes package submodules
  on unload. Favorites' settings resource and transaction lock live in the host,
  so old and new generations share serialization. No store schema changes.

## Alternatives

- Separate picker/remove/rename commands: rejected for the normal UI; one manager
  keeps Name, Path and action targets visible. Old IDs remain for compatibility.
- Manual Move Up/Move Down: rejected by the user; Recent/Name/Path is sufficient.
- Operation buttons or selection checkboxes in QuickList: rejected; the view
  chooses items and the bottom panel owns actions and settings.
- Fuzzy relevance overriding the sort drop-down: rejected for this manager;
  the selected sort must remain meaningful while filtering.
- Sort the stored JSON array: rejected; that would accidentally change which
  bookmark is evicted at capacity. Sort the view only.
- Delete requires explicit selection every time: rejected for this consumer;
  the requested highlighted-item fallback is explicit.
- Confirm every bookmark deletion: rejected by the user for Favorites. Submit
  the captured targets directly; preserve confirmations for other operations.
- Treat set_path's callback as unconditional success: rejected because listing
  failures/revisit reloads are not fully represented and direct calls bypass
  command interception. Resolve internal completion plumbing first.
- Poll settings or introduce persistent mutation versions: rejected; commit-driven
  snapshots and transient revisions suffice for open-manager synchronization.
- Use a fresh module-local lock after reload: rejected because an old commit may
  still be running. Share transaction ownership across load generations instead.

## Runtime Effects

- Startup/unused: no manager widgets, scans, workers, subscriptions or timers.
- Open: load a bounded snapshot using existing settings; build display/sort keys
  once per snapshot. Retain O(N) records and selected identities within store caps.
- Filtering is in-memory fuzzy matching; Name/Path sorting is O(N log N), while
  Recent uses the O(N) snapshot in store order without sorting. Measure at the
  configured cap. Use bounded immutable worker snapshots only if needed to keep
  Qt responsive, with stale query/snapshot rejection.
- No I/O on sort/query/current/selection changes. Writes occur only on requested
  mutations or Add; Go To performs the existing location checks/navigation.
  Folder-only Go To adds an is_dir metadata check in its existing worker before
  dispatch. Add continues using get_path without scanning or checking selected
  files. No new startup scans, workers or idle work are introduced.
- Notifications are commit-driven and carry bounded snapshots; no manager means
  no snapshot delivery work. The reload-safe coordinator retains only small
  serialization/revision state, with no idle thread, timer or settings cache.
- Close/unload disconnects handlers and rejects stale callbacks. Closing cancels
  navigation not yet started and UI work; already-started pane transitions are
  not rolled back. Blocking filesystem calls may finish later, with bounded
  outstanding work and rejected stale results. A store commit already begun
  finishes coherently without updating closed widgets. No polling or idle filter
  work remains.

## Tests

Extend existing [store/command unit tests](../src/unittest/python/fman_unittest/test_favorites.py)
and [plug-in integration tests](../src/integrationtest/python/fman_integrationtest/impl/plugins/test_favorites_plugin.py).
The shared UI Elements Qt test helpers are a prerequisite; reuse them rather
than duplicate the toolkit test suite.

- Unit: Name/Path sort, deterministic duplicate/case ties, default sort, filtered
  membership preserving sort, Name and Path fuzzy matches, Unicode highlights,
  empty/no-match queries and clear-query restoration.
- Unit/regression: Recent is the unset-setting default and exactly store order;
  re-add moves an entry to the top only under Recent, not Name/Path. Opening a
  favorite and renaming it do not change its stored recency.
- Unit: selected/hidden-selected Delete targets, highlighted fallback only with
  zero selection, current-only Rename/Go To, missing/changed targets, canceled
  rename, concurrent mutations and save/cache failure handling.
- Regression: Add/current path, null pane, deduplication, capacity confirmation,
  recency eviction unaffected by view sorting, invalid entries and virtual URLs.
- Qt: Ctrl+B opens/focuses one manager, rows show Name/Path, fuzzy enabled, initial
  highlight without selection, Ctrl/Shift selection, panel focus preservation,
  sort/filter/rename selection retention, empty state and disabled controls.
- Qt: Delete/Rename keep the manager open; Enter/double-click Go To closes only
  on acknowledged success. Test invalid targets, navigation failure, pane switch,
  pane destruction, Escape/prompt precedence and unload during work.
- Qt: query Enter invokes Go To; list Del and the Delete button produce identical
  immediate deletion without prompts. Shared confirmation defaults and Rename
  cancellation remain tested separately. Del in text inputs
  edits text and never reaches directory file-delete commands.
- Qt: Go To waits for set_path's callback, PermissionError keeps the manager
  open, and callbacks after close or supersession are ignored. Callback receipt
  alone must not close on partial-listing failure. File targets report an error
  without dispatching navigation. Add ignores highlighted/selected files and
  persists only the pane folder. Folder checks run off Qt.
- Navigation prerequisite: immediate and iterator-time errors, disappearance,
  empty/same-path initialization, revisit reload failure, file cursor failure,
  unrelated pane navigation, on_command rewrites and before_location_change hooks.
  Untracked rewritten commands fail explicitly without changing public arguments.
  Assert one terminal outcome and no stuck busy state for each completed request.
- Qt/concurrency: close during a blocked existence check never navigates when it
  returns; close after a transition starts never rolls the pane back. Repeated
  open/close does not accumulate unbounded blocked checks or stale UI deliveries.
- Qt/integration: two open managers reflect Add/re-add and legacy remove/rename;
  out-of-order snapshots and changes during initial subscription cannot regress
  or lose state. Failed saves emit no success; prompt targets stay captured.
- Reload: unload during a prompt, queued mutation and active commit; reload and
  mutate again. Reject old unstarted work, serialize old/new commits without lost
  updates, dispose old widgets and reject old UI callbacks. No Qt-thread waits.
- Compatibility: custom show_favorites(query='...') seeds/replaces the query;
  default invocation focuses without reset. Ctrl+B works from the query, list and
  panel, and manager keys never fall through to directory operations.
- Integration: exactly two discoverable bookmark commands and Ctrl+B mapping;
  old IDs remain directly callable. No file deletion API is called by Delete.
- Integration: remove/rename is_visible() is False; their names and aliases are
  absent from the palette, but run_command and custom key bindings execute them.
- Performance: filter/sort at the configured cap without filesystem calls or
  recurring idle work; target p95 event-loop gaps below 50 ms. Record measured
  timing, row count and stable handle/session counts over repeated open/close.
- Manual/source/frozen: keyboard-only flow, both themes, narrow windows,
  100/150/200% DPI, Name/Path readability, tooltips, settings persistence after
  restart and no manager automatically reopened.

Focused commands from the repository root:

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_favorites
python -m unittest fman_integrationtest.impl.plugins.test_favorites_plugin
```

For actual widget/dialog checks in this environment, use `QT_QPA_PLATFORM=windows`
and the main-thread `fman_integrationtest.qt_runner` command recorded below.
The offscreen platform crashed on native confirmation dialogs; it is not the
validated runner for the new manager's Qt tests.

Run the prerequisite shared UI tests, including changed QuickList/filter/panel tests,
plus focused command-dispatch, navigation-model and plug-in reload tests for the
internal contracts above, and record exact selectors. Run the narrowest test immediately after the first
implementation edit. Source smoke: remove QT_QPA_PLATFORM and run
`python build.py run`. Packaging gate: `python build.py freeze`, then launch the
frozen app and exercise the workflow. No automatic full `python build.py test`.
Design-only checks: required headings/local links and
`git diff --check -- Plan/Favorites002.md Plan.md`.

## Implementation Steps

The user approved delivering the Favorites-required subset of UI Elements Phase A
first in this implementation: shared QuickList/filtering, separate action panel,
bounded confirmations, modeless lifecycle, navigation results and reload-safe
transaction ownership. Implement these reusable primitives and their focused Qt
tests before the Favorites adapter. Trees, previews, streaming search and other
unneeded UI elements remain in UI Elements; they do not block this subset.

1. Review this consumer design and align UI Elements' Favorites pilot: remove
   reorder, support preserve-sort fuzzy filtering, explicit Delete fallback and
  persistent management sessions. Resolve tracked navigation with command hooks,
  loader-bound disposal, reload-safe transactions and commit-driven snapshots
  with focused tests before integration. Preserve command discovery and query
  argument behavior. Do not treat callback receipt as unconditional success.
2. Implement pure sort/filter projection and action-target rules against existing
   bookmark identity/store helpers; test independently of Qt.
3. Compose QuickList and its bottom panel, enabled fuzzy filter, Recent/Name/Path choice
   and Close control; verify navigation/selection without writes.
4. Integrate immediate Delete, Rename, acknowledged Go To and transaction/error
  handling, then live refresh across managers and legacy commands. Validate each
  action, cancellation boundary, snapshot ordering and unload/reload case.
5. Route Ctrl+B and command visibility, preserve Add and callable old IDs; update
   user documentation and application changelog only with implemented behavior.
6. Complete focused tests, performance and source/frozen smoke. Record results
   and implementation provenance, then move this canonical task to Done and
   update the plan index only when acceptance criteria pass.

## Acceptance Criteria

- Ctrl+B opens the QuickList Favorites Manager, with Name and Path visible and
  fuzzy filtering enabled; there are no manual reorder controls.
- Recent is the default; the drop-down offers Recent/Name/Path and governs order
  even during filtering. Recent uses add/re-add order, never last-opened time;
  Name/Path sorting does not change stored eviction order.
- Selected identities survive filtering/sorting, with total/hidden counts.
- Bottom Delete immediately removes selected bookmarks or the highlighted
  fallback without confirmation; no files/folders are deleted and the manager
  remains open. Hidden selections are included; busy/empty actions are no-ops.
- Rename affects only highlighted Name; Go To targets the invoking pane and
  closes only on success. Failures retain the manager and explain the outcome.
- Navigation preserves command/location hooks, reports terminal outcomes without
  mistaking initialization for success, and never starts from a late check after
  close. Already-started transitions are not rolled back by closing the manager.
- Open managers converge after committed changes without polling or lost updates;
  plug-in reload cannot overlap commits under different locks or revive old UI.
- Escape works without new actions; Add current folder to favorites still adds
  the active path. Only Manager and Add appear as bookmark commands in discovery.
- Ctrl+B works within manager controls; custom query arguments remain supported,
  and a default repeat invocation preserves the current query and selections.
- Existing data/API/command IDs remain compatible; focused tests and required
  source/frozen checks pass with documented results before completion.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Planned the user's QuickList manager with enabled fuzzy filtering,
  Name/Path sorting and bottom Delete/Rename/Go To/Close controls, retaining Add.
  Supersedes manual reorder and relevance-first ordering for this consumer.
  Grounded in the shipped Favorites store/commands; toolkit alignment, command
  discovery, save failure and navigation acknowledgement require implementation
  review/tests. No application code or runtime validation is claimed.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved as the Phase A pilot consumer of UI Elements, subject to
  the corrections below. The behavioural design (view-only sorting, hidden
  selection accounting, confirmation-protected Delete fallback, manager stays
  open across actions) is sound and consistent with the shipped store. Two of
  the open questions the document defers to implementation are already
  answered by existing code and are resolved here; the concurrency section is
  over-specified for the data involved; and the terminology change from
  Favorites to Bookmarks should be reverted.

#### Follow Up Tasks

Resolved by existing code (update the document accordingly):

- [ ] **Command discovery.** `CommandPalette._get_all_commands` skips any pane
      command whose `is_command_visible()` is false, and `is_command_visible`
      simply calls the command's `is_visible()`. Returning `False` from
      `RemoveFromFavorites.is_visible()`/`RenameFavorite.is_visible()` hides
      them from the palette while `run_command('remove_from_favorites')` and
      key bindings keep working — exactly "hide from discovery, not from
      direct invocation". Core's `none` command uses the same trick. Replace
      the "verify how command visibility and aliases are enumerated" clause
      with this fact and one test.
- [ ] **Navigation acknowledgement.** `DirectoryPane.set_path(url, callback,
      onerror)` already provides it: `set_path` raises `FileNotFoundError` /
      `PermissionError` synchronously from `resolve`/`get_columns`, and
      `callback` fires only after the new model's rows are initialised
      (`Model._on_rows_inited_main`). Go To should therefore *not* go through
      `run_command('open_directory')` (fire-and-forget on another thread) but
      call `self.pane.set_path(url, callback=ack, onerror=None)` from the
      adapter's worker, mirroring `OpenDirectory`'s try/except for
      `PermissionError`, and close the manager from `ack` after checking the
      session is still open. No "narrow internal acknowledgement" needs to be
      added. Keep the existing `exists()` pre-check for the alert text.

Design corrections:

- [ ] **Keep the Favorites name.** The plug-in, JSON file, command IDs,
      aliases, README and changelog all say Favorites; this document
      introduces "Bookmarks Manager" and "Add to Bookmarks". Renaming buys
      nothing and forces alias/README churn. Use `Favorites Manager` and keep
      `Add current folder to favorites`; "bookmark" may appear as an extra
      alias for palette search only.
- [ ] **Add a `Recent` sort option (store order).** With Name as the default
      and no manual order, the store's recency — which still drives capacity
      eviction and is updated on every re-add — becomes invisible to the user.
      `Recent` is a zero-cost third choice (no sort key at all) that makes the
      eviction order legible and preserves the one behaviour Favorites 001
      shipped. Default stays Name.
- [ ] **Bind `Del` in the list to Delete.** The document forbids global Enter
      → Delete (correct) but does not say whether the `Delete` key acts on the
      list. It should, with the same capture-and-confirm path as the button;
      state it and add it to the Qt tests.
- [ ] **Decide, do not "may".** "Enter in the fuzzy query field *may* also
      invoke Go To" — make it definite: Enter in the query field invokes Go To
      on the current item, mirroring Quicksearch.
- [ ] **Trim the concurrency section.** For a single-user list capped at 200
      entries, the shipped pattern is sufficient: reload under `_LOCK`,
      compare captured `(url, name)` with current, mutate by canonical URL,
      skip and report mismatches, save once. Drop the "lock-protected
      mutation generation" requirement; the identical remove/re-add case it
      guards against yields the same end state either way. Keep the
      save-failure rule (never report success on a failed `save_json`).
- [ ] **Consolidate toolkit requirements.** The toolkit features this consumer
      needs are scattered across sections. Add a short *Toolkit Requirements*
      list so UI Elements Phase A can be scoped from it: modeless QuickList
      with Ctrl/Shift multi-selection and hidden-selection counts; title+hint
      rows with tooltip; fuzzy filter with a *preserve-sort* mode and Unicode
      highlight offsets; bottom panel with fixed-choice, action buttons and a
      close icon; bounded list confirmation; `Del` key routing; one session
      per pane with focus-existing semantics.
- [ ] **State the blocking dependency explicitly.** Add "Blocked on UI
      Elements Phase A" at the top of Implementation Steps, and drop the
      phrase "once available" from Tests — the shared Qt helpers are a
      prerequisite, not an option.
- [ ] **Delete fallback wording.** The fallback to the highlighted item is an
      explicit exception to the toolkit's default and is confirmation
      protected — acceptable. Require that the confirmation dialog title
      differs between the two cases (`Delete 3 selected favorites` vs `Delete
      favorite "Projects"`) so the user can tell which path fired.

Tests to add:

- [ ] Hidden commands: `is_visible()` false for remove/rename, palette omits
      them, `run_command` still executes them.
- [ ] Go To closes only after `set_path`'s callback; a `PermissionError`
      leaves the manager open; a stale callback after close is ignored.
- [ ] `Recent` sort equals store order; re-adding moves an entry to the top
      under `Recent` and does not move it under Name/Path.
- [ ] `Del` key triggers the same confirmation as the button.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Incorporated Fable's corrections and the user's subsequent choice of
  Recent as default (superseding the review's Name default). Retained Favorites
  terminology, existing visibility/navigation APIs and simple store transactions.
  Original review records remain unchanged; checked resolutions below describe
  plan changes, not implementation or runtime test completion.

#### Fable Review Resolutions

- [x] Command discovery: is_visible(False) hides remove/rename from palette
  discovery while keeping direct invocation and custom bindings; tests specified.
- [x] Navigation acknowledgement: use existing set_path callback, retain the
  existence/error policy and OpenDirectory file-target behavior; no new API.
- [x] Naming: Favorites Manager and Add current folder to favorites retained.
- [x] Recent: third sort option using store order; default changed to Recent by
  the user after Fable's review, not the originally recommended Name.
- [x] Del: list-scoped routing shares button capture and confirmation.
- [x] Query Enter: definite Go To behavior, without overriding text/panel controls.
- [x] Concurrency: compare captured URL/name under the existing lock; no mutation
  generation for identical remove/re-add. Save-failure reporting remains required.
- [x] Toolkit requirements: consolidated navigation, filtering, controls, focus,
  confirmation, lifecycle and Qt helper requirements.
- [x] Dependency: explicitly blocked on Phase A toolkit/helpers, with prerequisite
  delivery distinguished from pilot integration to avoid a circular gate.
- [x] Delete fallback: distinct selected-count and highlighted-name titles.
- [x] Hidden-command tests cover visibility, aliases and direct invocation.
- [x] Navigation tests cover callback timing, PermissionError, file targets and
  stale callbacks after close/supersession.
- [x] Sort tests cover Recent default/store order, re-add and stable Name/Path order.
- [x] Del tests cover parity with the button and text-input/directory isolation.

#### Design Validation

Required section, local-link, default-sort and review-resolution checks plus
`git diff --check -- Plan/Favorites002.md Plan.md` are the documentation gates.
Application implementation, runtime tests and packaging remain pending.

Source familiarization covered application startup, plug-in registration and
command dispatch, Quicksearch rendering/theming, pane/model navigation, Qt
dispatch and JSON persistence. Existing baseline command:

```powershell
python -m unittest fman_unittest.test_favorites fman_integrationtest.impl.plugins.test_favorites_plugin
```

With the Tests section's PYTHONPATH and offscreen settings, all 27 existing tests
passed. This validates the current Favorites baseline, not the proposed manager.
Documentation section/link/default/resolution checks and
`git diff --check -- Plan/Favorites002.md Plan.md` passed. No application code
was changed; new-feature tests and source/frozen workflow checks remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Architecture-informed revision retains the agreed interaction design
  but makes tracked navigation and loader-safe ownership prerequisite contracts.
  Supersedes the earlier conclusion that the existing set_path callback alone
  needs no internal completion support; public API compatibility remains required.
  Added commit-driven multi-manager refresh, reload-safe transaction serialization,
  explicit close/navigation boundaries, manager-local Ctrl+B and query argument
  compatibility. Tests and acceptance criteria now cover these cases. Historical
  review records are unchanged. Design only; exact internal navigation/toolkit
  integration must be resolved and tested before implementing the manager.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: User approved implementing the shared Favorites prerequisite subset
  first, without unrelated Phase A tree/preview/search surfaces. Preserve reusable
  widget and lifecycle boundaries, command hooks, and existing public arguments.
  Complete and test these internal contracts before integrating the manager.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed and repaired Fable's findings against executable evidence.
  Retain the usable model on column lookup failure and the measured sub-millisecond
  ordinary navigation hop; document partial file-target navigation. Source
  blockers are addressed, but frozen/manual delivery approval remains pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Adopted the user's folder-only Favorites scope. Add already uses the
  pane folder rather than file selection; lock that behavior down with a test.
  Reject saved file targets during Go To rather than scanning/migrating settings.
  Keep shared OpenDirectory file behavior for non-Favorites callers.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Revised composition against the user's Sublime Text reference:
  QuickList is an embeddable view with file-pane selection, BottomPanel is
  independent, and configuration controls persist JSON separately from actions.
  Use a frameless Favorites host and persisted sort; preserve folder-only scope.
  Public component imports are additive; historical internal-only constraints
  are superseded for this implemented surface. Frozen/manual gates remain open.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Accepted the new general-API Qt boundary and canonical controller
  construction requirements. Keep the user-approved split presentation and test
  focus recovery rather than changing its placement. Physical Alt+Tab and
  second-monitor validation remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Adopted the user's Favorites-only immediate Delete requirement.
  Button and list Del retain the same captured targets and existing mutation
  worker. Shared confirmation APIs, Rename and Add/capacity prompts are unchanged.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Recorded user acceptance and explicit waiver of remaining completion
  checks. Favorites is Done based on implemented behavior and documented source
  validation. Frozen/manual checks are unverified, not represented as passing.
  UI Elements and the constrained UI abstraction TODO remain separate open work.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Revised placement to the main-window strip above the status bar and
  accepted close-icon termination of the paired UI session. One slot per main
  window supersedes concurrent same-window per-pane managers.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Favorites now docks via exported PaneToolWindow.set_bottom_panel;
  native close icon and Escape end the UI session, preserving committed settings.
  Passed 132 focused tests and native close/reopen smokes at three DPI scales.

The following records are historical and append-only. The resolution record
after the Fable review describes the current implementation and remaining gates.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented the shared Favorites-required UI subset and persistent
  manager, commit-driven synchronization, loader lifetime, internal tracked
  navigation, preserved legacy IDs/query arguments, documentation and packaging
  imports. Focused source checks pass; completion is not claimed because frozen
  validation was skipped by the user and remaining manual checks are pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Not approved. The manager itself (QuickList selection model,
  preserve-sort filtering, hidden-selection Delete, coalesced snapshot refresh,
  loader-bound ownership) is well built and the 50 unit/plug-in tests pass under
  the CI configuration. Two defects block completion: the new Qt integration
  tests crash the interpreter under `QT_QPA_PLATFORM=offscreen`, which is what
  `build.py test` and the release workflow use, and `NavigationRequest` can
  leave a worker slot blocked forever when a superseded model is shut down
  before its `_init` runs. A third concern is architectural: the tracked
  navigation plumbing touches five shared modules and inverts layering
  (`fman/__init__.py`, `model.py`, `plugin.py` import `fman.impl.ui`).

#### Follow Up Tasks

Checkboxes reflect the implementation follow-up; the original review text is
preserved. Checked items include justified alternatives documented in
[Fable Review Resolution](#fable-review-resolution), not necessarily the exact
remedy originally proposed. Frozen validation remains pending.

Blocking:

- [x] **Offscreen crash is a CI failure, not a harness choice.** Reproduced:
      `python -m unittest fman_integrationtest.test_qt.FavoritesManagerIT` with
      `QT_QPA_PLATFORM=offscreen` dies with `Windows fatal exception: access
      violation` in `test_delete_captures_hidden_selection_and_never_files`
      (the first test that opens `ToolWindow.confirm`); the same 16 tests pass
      with `QT_QPA_PLATFORM=windows`. `build.py test` sets offscreen by
      default, so `python build.py test` and the tag-triggered release
      workflow will crash. An access violation indicates a C++ object used
      after deletion, most likely in `_open_prompt` (`deleteLater()` inside the
      `finished` handler while `dialog.open()` is still unwinding, combined
      with `WA_DeleteOnClose` on the parent) — a real lifetime bug that the
      native platform happens to tolerate. Fix the root cause (e.g. defer
      `deleteLater` with a zero-timer, or keep a reference until `destroyed`,
      or use `QMessageBox.question` semantics via `exec` on the tool window's
      own event loop) and make the suite pass under offscreen. Only then may
      `qt_runner.py` remain as an *additional* native check. Do not skip
      these tests under offscreen; that hides the bug.
- [x] **`NavigationRequest.settled` can stay unset → permanent slot leak.**
      `Model._init` is decorated with `@transaction`, which returns early when
      `self._shutdown` is already true, so the `finally: settled.set()` inside
      `_init` never runs if the model is shut down (superseded by a newer
      navigation, or the pane destroyed) before its worker processes `_init`.
      `FavoritesWindow._go_to`'s `navigate()` then blocks in
      `request.settled.wait()` for ever, holding one of the two global
      `submit_work` slots; two such events leave every Favorites manager
      reporting "Other operations are still finishing" until restart.
      Fix: set `settled` inside `NavigationRequest.finish()` (every terminal
      outcome, including `cancel()` from `Model.shutdown`), and add a bounded
      `settled.wait(timeout)` with a failure outcome as a last resort. Add a
      regression test that supersedes a tracked navigation before `_init`
      runs and asserts the slot is released.
- [x] **Layering.** `fman/__init__.py` (public API), `fman/impl/model/*.py`,
      `fman/impl/plugins/plugin.py` and Core `OpenDirectory` now import
      `fman.impl.ui.navigation`. Move `NavigationRequest`, `tracking` and
      `current_request` to a neutral module (`fman/impl/navigation.py` or
      `fman/impl/util/navigation.py`) so the model and loader do not depend
      on the UI package. No behaviour change; import paths only.

Shared-code regressions to verify (each needs a focused test or a note):

- [x] `SortedFileSystemModel._begin_navigation` is `@run_in_main_thread` and is
      now called on **every** `set_location`, including startup pane
      initialisation from the session thread pool and `_on_file_removed`
      callbacks. That is one synchronous main-thread round-trip per
      navigation that did not exist before. Measure startup with two panes;
      if measurable, only perform the hop when `request is not None`.
- [x] `FileSystemWrapper.iterdir` tracked branch bypasses the wrapper's
      plug-in error reporting: a non-`OSError` exception from a third-party
      filesystem during a tracked navigation is turned into a manager alert
      and never reaches the plug-in error handler. Report it through both.
      The new `TypeError('non-string name')` check exists only on the tracked
      path; either apply it to both paths or drop it.
- [x] `_set_location` now skips `old_model.shutdown()` when `get_columns`
      raises (shutdown moved into `_set_location_main`). Confirm the old model
      still ends up shut down on that error path, or restore the early call.
- [x] Core `OpenDirectory`: the `if request: raise` in the cursor callback turns
      a hidden-file favourite into a *failed* navigation although the pane has
      already moved to the parent directory. Documented as intended, but the
      user sees the pane change and an error alert together. Prefer
      `finish('success')` with an informational message, or state the
      trade-off in the README.

Manager code quality (non-blocking):

- [x] `FavoritesWindow` reaches into `pane.window._widget`, `parent._theme`
      and `pane._widget`. Add a host factory (`MainWindow.create_tool_window
      (owner)` returning the parent and theme css) so the adapter uses no
      private attributes.
- [x] `ShowFavorites.aliases` dropped `Show favorites`; users who type
      "show fav" in the palette lose the match. Keep it as a third alias.
- [x] `InteractionPanel` hard-codes the `Sort By` label and injects a
      per-button stylesheet. Take the label from the constructor and move the
      padding rule into the theme (`QuickList QPushButton`), which UI Elements
      names as a requirement.
- [x] `ItemDelegate`: replace `option.fontMetrics.__class__(font)` with
      `QFontMetrics(font)`, guard `option.widget is None`, and derive the
      `sizeHint` width from the view rather than the constant 200.
- [x] `Resource.committed` increments `revision` without taking
      `Resource.lock`; it is correct only because every caller holds
      `favorites._LOCK`, which *is* that lock. Assert or document this
      precondition in `Resource`.
- [x] `RoyiFileManager.spec` hidden imports list `fman.impl.ui.quicklist` and
      `session` but not `fman.impl.ui.navigation`; it is imported lazily from
      five places, so add it (or verify PyInstaller picks it up) before the
      frozen smoke.

Process:

- [x] Validation Results state "138 tests passed" under `QT_QPA_PLATFORM =
      'windows'`; add the offscreen result explicitly once fixed, since that
      is the configuration the repository policy and the release workflow
      run.
- [ ] `python build.py freeze` and the frozen smoke were skipped; they are
      required gates for a change that adds dynamic imports to the spec.
- [x] Update the README statement on `Ctrl+B` behaviour (manager stays open on
      Delete/Rename, closes on Go To) — verify the text in
      `Plugins/Favorites/README.md` matches the implemented Recent default.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Addressed the Fable review's source blockers and quality findings.
  Offscreen Qt, cancellation before initialization, bounded ongoing scans,
  neutral navigation layering, error attribution, aliases, pane ownership,
  prompt safety and row sizing have focused regression coverage. Frozen and
  remaining manual gates are still pending; no completion or approval is claimed.

#### Fable Review Resolution

- Offscreen crash: reproduced with a minimal QMessageBox without a finished
  callback or deletion. The suggested deleteLater use-after-free cause was not
  established. Standard QDialog widgets avoided that platform crash; moving the
  ordinary unittest harness's QApplication to the process main thread fixed the
  separate teardown crash. No offscreen skips or font-directory workaround.
- Cancellation: finish sets settled exactly once, including shutdown before
  initialization. A bounded wait and an independent initialization semaphore
  protect waiter liveness and the limit on actual running scans. Tests supersede
  three never-started models and check slot reuse, timeout and saturation.
- Layering: navigation lives in neutral fman.impl.navigation; all runtime/test
  imports and the explicit PyInstaller hidden import use the new location.
- Startup: native two-pane measurements recorded 0.11-0.19 ms per synchronous
  navigation hop. Keep the hop: ordinary navigation must also cancel a tracked
  request and advance its generation. These are local hop timings, not a full
  before/after startup benchmark or a network-latency bound.
- Filesystem reporting: tracked non-OSError failures reach the plug-in error
  handler and propagate to the manager. Both paths already reject non-string
  listing entries; ordinary reporting/skipping behavior remains compatible.
- Column lookup failure: intentionally retain the still-displayed old model
  rather than shut it down. Regression verifies it remains usable, then is shut
  down on the next successful replacement.
- File cursor failure: retain failure semantics rather than claiming success;
  the bundled README explicitly explains the already-open parent directory.
- Host boundary: use internal PaneToolWindow instead of a new public factory.
  Favorites no longer reads private pane/window attributes. Pane destruction is
  tested; there is no public API expansion.
- Remaining quality items: restored Show favorites alias; configurable panel
  label and stylesheet padding; explicit QFontMetrics and widgetless rendering;
  viewport-derived row size with resize relayout; Resource revision locking.
- Documentation states Recent is the fresh-session default, ordinary Ctrl+B
  focuses without resetting, Delete/Rename stay open, and successful Go To closes.
- Frozen build/smoke remain blocked by the earlier user skip; they were not retried.
  The original review text above is preserved; its checkboxes now show addressed
  items, including the alternatives explained here.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Verified Add's existing folder-path behavior with a selected-file
  regression; added off-Qt folder validation before Go To dispatch, with tests
  for file rejection and successful folder navigation. Updated usage and scope.
  The 45 focused tests passed; frozen and existing manual gates remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Source approved. All three blockers from the previous review are
  resolved and independently re-verified: the Qt integration suite passes under
  `QT_QPA_PLATFORM=offscreen` (45 tests, no fault), `NavigationRequest.finish`
  sets `settled` on every terminal path and a bounded `wait()` guards the slot,
  and the tracking primitives live in `fman.impl.navigation` with the spec
  hidden import updated. The shared-code follow-ups are either fixed or
  explicitly decided and documented. Completion remains gated on the frozen
  build and manual checks the implementer lists; the task must stay under
  `Plan/` until those run.

#### Verification

- `python -X faulthandler -m unittest fman_integrationtest.test_qt
  fman_integrationtest.impl.model.test___init__
  fman_integrationtest.impl.plugins.test_favorites_plugin` (offscreen): 45 OK.
- `python -m unittest fman_unittest.test_favorites fman_unittest.test_ui_elements
  fman_unittest.impl.plugins.test_plugin fman_unittest.impl.model.test_model
  core.tests.commands.test___init__`: 119 OK.
- Code read: `fman/impl/navigation.py`, `model.py` `_init`, `ui/session.py`,
  `ui/quicklist.py` delegate, `favorites/ui.py` `_go_to`/`_dispose`,
  `favorites/__init__.py` aliases, `styles.qss`, `RoyiFileManager.spec`.

#### Follow Up Tasks

Required before moving to `Done/`:

- [ ] Run `python build.py freeze` and the frozen smoke
      (`favorites_smoke --frozen ...`). The change adds three dynamic hidden
      imports to the spec; this is the only gate that proves they are
      collected.
- [ ] Run `python build.py test` once (the user must request it per policy).
      The new Qt tests now run under the platform that suite uses; the full
      run confirms no interaction with unrelated modules (e.g. `test_tutorial`,
      which has a pre-existing `core` import issue when run outside
      `build.py`).

Residual notes (no action required unless they recur):

- [ ] The offscreen crash root cause was not established; it disappeared when
      `QMessageBox` was replaced by a plain `QDialog`-based `MessageDialog`.
      `rename_prompt` still uses `QInputDialog` and passes offscreen. If a
      similar fault appears elsewhere, the first suspect remains dialog
      teardown order under `WA_DeleteOnClose`.
- [ ] `NavigationRequest.wait(timeout=30)` turns a slow network probe into a
      failure alert after 30 s while the pane may still navigate later. The
      README explains the folder pre-check; consider mentioning the timeout
      there as well.
- [ ] `_begin_navigation` main-thread hop measured at 0.11–0.19 ms per
      navigation; acceptable and documented. Revisit only if startup
      profiling on a slow machine shows it.
- [ ] `PaneToolWindow` now encapsulates the private `pane.window._widget` and
      `_theme` access inside the host's `fman.impl.ui` — correct place. A
      public factory can be added if a third-party consumer ever appears.
- [ ] Main `README.md` line 27 says "Bookmarks / Favorites manager"; the
      product wording elsewhere is "Favorites Manager". Harmonise when the
      README is next touched.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Favorites now consumes fman.ui. Removed the title bar and close
  controls, added file-pane keyboard/mouse selection, a separate flat panel and
  JSON-bound sorting. Source tests and native DPI smokes pass; no frozen artifact
  was rebuilt. See the revised component validation record below.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved with one required fix and one decision. The three-component
  revision (QuickList / BottomPanel + JSON-bound controls / PaneToolWindow) is
  cleaner than the previous InteractionPanel, and the file-pane selection model
  (click moves the cursor, Space/Insert toggle, Ctrl+A) is the right call for
  consistency with the directory panes. Verified under offscreen: 45 Qt
  integration, 29 favorites unit, 288-test unit directory discovery all pass;
  spec hidden imports cover `fman.ui`, `panel`, `quicklist`, `session`,
  `navigation`; README documents the new interaction model, the frameless
  window and `Favorites UI.json`. The required fix is a test-isolation defect
  caused by loader-owner invalidation; the decision is whether `fman.ui` is
  public API.

#### Verification

- Offscreen: `fman_integrationtest.test_qt` + model + plug-in integration →
  45 OK; `fman_unittest.test_favorites` alone → 29 OK; `python -m unittest
  discover -s src/unittest/python` → 288 tests, only failure is the
  `test_search_file_fuzzy` import (SearchFileFuzzy plug-in not on my
  `PYTHONPATH`; `build.py test` adds it).
- Reproduced: `python -m unittest
  fman_integrationtest.impl.plugins.test_favorites_plugin
  fman_unittest.test_favorites` in one process → 8 failures, 2 errors.

#### Follow Up Tasks

Required:

- [x] **Order-dependent test failure.** When the plug-in integration test
      (which loads and unloads the real Favorites plug-in) runs before
      `fman_unittest.test_favorites` in the same interpreter, every command
      test fails: unload calls `FavoritesController.owner.invalidate()`, and
      the unit-test module still holds the pre-unload `favorites` module, so
      `AddCurrentFolderToFavorites` etc. return early on
      `if not FavoritesController.owner.active`. `build.py test` runs the two
      directories in separate processes and so does not hit it today, but any
      combined run (IDE test explorer, `-m unittest` with both modules, a
      future single-process runner) will. Fix in `test_favorites.setUp`:
      reset `FavoritesController.owner = UiOwner()` (and re-bind
      `favorites._resource`/`_LOCK` if they are owner-scoped), or have the
      integration test restore the owner in `tearDown`. Add both modules to
      one focused command in Validation so the ordering is exercised.

Decision needed before `Done/`:

- [x] **`fman.ui` is now a public module exporting Qt widget classes**
      (`QuickList`, `BottomPanel`, `IconButton`, `TextButton`, `DropDown`,
      `JsonSettings`). This contradicts the UI Elements plan ("no public Qt
      types") and the recommendation to keep the toolkit internal until two
      shipped consumers exist. Favorites itself still imports
      `fman.impl.ui.session.PaneToolWindow`, `fman.impl.ui.resource` and
      `fman.impl.navigation`, so the public surface does not even cover the
      one consumer. Either (a) move `fman/ui.py` back to `fman.impl.ui`
      (Favorites is bundled; nothing is lost), or (b) keep it and mark it
      provisional in its docstring, add its names to `test_portable.py`'s
      public-name check, and state in the CHANGELOG API line that `fman.ui`
      is an unstable RoyiFileManager extension. (a) is recommended.

  **Decision (user, 2026_09_13): the goal is that an *external* plug-in can
  recreate Favorites using only exported components.** Option (b) therefore
  applies, and the acceptance criterion becomes: *`Plugins/Favorites` imports
  nothing from `fman.impl`, `core`, or private attributes.* The current code
  fails that criterion in the places listed below; each is a blocker for this
  task, not a note.

#### Public API Gaps Blocking An External Favorites

Internal imports and private access in `favorites/ui.py` and
`favorites/__init__.py` that must be replaced by exported equivalents:

- [x] `from fman.impl.ui import resource` → export a settings-resource API
      (`fman.ui.settings_resource(filename)` or fold it into `JsonSettings`)
      so a plug-in can share one transaction lock/revision between its
      commands and its window without touching `impl`.
- [x] `from fman.impl.ui.session import PaneToolWindow` → export
      `fman.ui.PaneToolWindow` (or `open_tool_window(pane, owner)`), and move
      its private reads (`pane.window._widget`, `parent._theme`,
      `pane._widget.destroyed`) inside the host behind public accessors
      (e.g. `Window.tool_parent()`, `Theme.quicksearch_item_css()`,
      a `pane.destroyed`/`closed` notification). Until then the host module
      itself reaches into private attributes on behalf of the plug-in.
- [x] `from fman.impl.navigation import NavigationRequest` → export a
      tracked-navigation entry point: `fman.ui.navigate(pane, url, on_done)`
      (or `pane.set_path_tracked(url)` returning a future/outcome) that owns
      `NavigationRequest`, the worker slot and the bounded wait. The
      thread-local `tracking()` context must stay internal.
- [x] `from fman.impl.util.qt.thread import run_in_main_thread` → not
      exported; the host-owned `UiController.show()` performs the dispatch (see
      *Host-owned construction* below), so the plug-in has no reason to import
      any thread helper.
- [x] `from core.quicksearch_matchers import …` in `favorites/__init__.py`
      (legacy picker) — Core is a plug-in, not API. Export the matcher set
      through `fman.ui` (`fman.ui.matchers.contains_chars` …) or move the
      legacy commands onto `QuickList`'s built-in `fuzzy=True` matcher and
      drop the import.
- [x] `favorites._LOCK = _resource.lock`, `favorites._commit`,
      `favorites._load_store` cross-module privates are fine *inside* the
      plug-in, but they rely on `resource.lock` being an `RLock` owned by the
      host; document `Resource.lock` as part of the exported contract.
- [x] `FavoritesController(UiController)` relies on the loader assigning
      `cls.owner = UiOwner()` per load generation. Document `UiController` as
      the exported base and `owner` as the exported attribute; add a
      `require_owner()`-style guard with a clear error when a plug-in
      instantiates UI without the loader having bound an owner (the exact
      failure the order-dependent test exposed).

Missing exported capabilities (no import today, but an external author would
need them to reach parity):

- [x] **Host-owned construction instead of thread guards.** Plug-in commands
      already run on worker threads (`PaneCommandRegistry._run_outside_main_thread`),
      so a plug-in that instantiates `QuickList` in `__call__` crashes Qt;
      Favorites avoids this only via the internal `@run_in_main_thread` on
      `FavoritesController.open`. Make the exported `UiController` own the
      lifecycle: the plug-in implements `build(window, pane)` (layout: add
      `QuickList`, panel, controls, bind settings) and short reaction hooks
      (`on_action`, `on_activated`, `on_state_changed`); the host provides
      `Controller.show(pane, query='')`, which dispatches to the Qt thread,
      attaches the loader-bound owner, reuses one window per pane, seeds the
      query and focuses. Plug-ins never call `run_in_main_thread` and never
      construct a window themselves. Keep a Qt-thread assert in the widget
      constructors only as a readable error for misuse. Favorites is the demo
      of this pattern; `FavoritesController.open` and most of
      `FavoritesWindow.__init__` move into the host base.
- [x] **Worker slots** (`submit_work`) are host-global and undocumented;
      export as `fman.ui.submit_work` with its saturation contract, or make
      `ToolWindow.work` the only path and document that.
- [x] **Theme integration**: the plug-in cannot add selectors to `theme.py`
      or `styles.qss`. Export the object names/class names that themes style
      (`QuickList`, `bottom-panel`, tool window class) and document how a
      plug-in's window inherits them (the `FavoritesWindow {}` rule in
      `styles.qss` is a host-side special case that an external plug-in could
      not add).
- [x] **Bounded confirmation / rename prompt** are methods on `ToolWindow`;
      fine, but they need to be part of the documented surface
      (`confirm(title, records, hidden, footer, accepted)`,
      `rename_prompt(label, name, accepted)`, `alert(text)`).
- [x] **Public-name and compatibility bookkeeping**: add every `fman.ui`
      export to `test_portable.py`, add a "Public API" section to the
      Favorites README that lists the `fman.ui` names it uses (proof of the
      criterion), and word the CHANGELOG API line as: preserves fman 1.7.5;
      adds the provisional `fman.ui` extension.
- [x] **Exit test**: a test that greps `Plugins/Favorites/**/*.py` for
      `fman.impl`, `from core`, `._widget`, `._theme` and fails on any match.
      This is the mechanical form of the acceptance criterion and stops
      regressions once the imports are gone.
- [x] Mirror this list into [UIElements.md](../Plan/UIElements.md) as the concrete
      Phase A export surface (it supersedes the generic "descriptors only"
      wording there, since the user has chosen to export widget components).

Design notes (accepted, record only):

- [x] Frameless `Qt.Tool | FramelessWindowHint` window: no native frame means
      the user cannot move or resize it with the mouse and there is no visible
      close affordance; Escape and Ctrl+B are the only ways out, documented in
      the README. Acceptable for a Quicksearch-like transient tool. If users
      report it, add drag-by-panel (`mousePress/MoveEvent` on `BottomPanel`)
      before reintroducing a frame.
- [x] Shift+click *toggles* a range (`command & ~Select | Toggle`) rather than
      selecting it; unusual but symmetric with Shift+Up/Down toggling, and the
      README says so. Leave as is.
- [x] Persisted sort moved to a second file, `Favorites UI.json`, because
      `FavoritesStore.to_json()` would drop foreign keys from
      `Favorites.json`. Correct choice; README documents it.
- [x] `ToolWindow.confirm` compares against `QMessageBox.Yes` while
      `MessageDialog` returns `int(QDialogButtonBox.Yes)`; the enums share the
      value 0x4000 so it works — compare against `QDialogButtonBox.Yes` to
      remove the coincidence.
- [x] `BottomPanel` sets `WA_StyledBackground` and object name `bottom-panel`
      but no theme rule targets it yet; harmless (inherits the window
      background) — add a rule when the panel gets its own look.

Still required before `Done/` (unchanged):

- [ ] `python build.py freeze` and the frozen smoke; the spec now lists five
      hidden imports for this feature and only the frozen run proves them.
- [ ] One full `python build.py test` on the user's request.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: FavoritesController now builds the generic host; FavoritesSession is
  plain Python state/actions. Public-only imports remain enforced. Updated the
  reference guide and native smoke; 117 focused tests passed. Existing full-suite,
  frozen and physical focus checks remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Removed Favorites Delete confirmation, added button regressions and
  native button-to-persistence coverage. All 64 focused tests and native source
  smoke passed; no full-suite or frozen run was performed for this revision.

## Validation Results

### Completion Acceptance - 2026_09_13

- The user requested marking Favorites Done and explicitly selected "Mark Done;
  waive remaining checks" after being told that frozen-build and physical
  Alt+Tab/multi-monitor checks were unverified. Outstanding packaging/manual
  checks are waived for this task's closure, not silently recorded as successes.
- Source evidence remains the earlier 117-test combined regression run and the
  latest immediate-Delete revision's 64 focused tests and native source smoke.
  Exact commands and outcomes are retained below. No code changed for closure.
- User-provided full-suite evidence: `python build.py test` completed an earlier
  run with 320 unit, 111 integration and 221 Core tests, all OK (5 total skips).
  After `python build.py clean`, the supplied output shows 321 unit tests OK
  (1 skip) and 114 integration tests run; the user subsequently confirmed the
  run completed. Its final tail was not supplied, so no additional final count
  or independently verified result is claimed. These runs preceded the latest
  Delete revision, which has separate focused/native validation.
- Remaining limitations include unverified frozen collection/startup, physical
  Alt+Tab/multi-monitor behavior and the outstanding manual checks listed in
  historical validation. The broader UI Elements task and the constrained Qt
  abstraction item in TODO are not completed by this acceptance.
- Documentation closure checks: editor diagnostics and local Markdown link/file
  existence checks for the moved document and updated index/cross-references.
  No application tests, full suite or packaging commands were rerun for this
  documentation-only move.

### Immediate Delete Validation

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -X faulthandler -m unittest fman_integrationtest.test_qt.FavoritesManagerIT
python -X faulthandler -m unittest fman_unittest.test_favorites fman_unittest.test_ui_elements fman_integrationtest.test_qt.FavoritesManagerIT
$env:QT_QPA_PLATFORM = 'windows'
python -X faulthandler -m fman_integrationtest.favorites_smoke
```

- Manager checks: 25 passed. Combined focused set: 64 passed. Actual button clicks
  cover hidden selection and current fallback without a prompt. Busy/empty actions
  are no-ops. Shared confirmation defaults and Rename cancellation remain tested.
- Native source smoke passed: click Delete, no prompt, committed list empty,
  saved JSON reflects the empty default, folder intact and manager still open.
  The first smoke assertion incorrectly required an explicit favorites key;
  differential config omits defaults. The default-aware assertion passed on rerun.
- No new worker, timer, scan or persistence format. Existing bounded mutation
  work and stale-result/cancellation rules are reused. Full suite and frozen
  checks were not rerun for this revision; broader task gates are unaffected.

### Qt Boundary Review Resolution

The three source/API requirements are implemented. General Window/DirectoryPane
no longer expose Qt host bridges; the callback API supports unsubscribe and UI
thread delivery. Unshipped aliases are removed. Favorites builds only through
its controller and no longer subclasses a host widget. The opt-in fman.ui widget
layer remains Qt-based; the public-only import criterion remains enforced.

For the split-layout decision, retain the user's floating QuickList and bottom
dock. A reusable Qt/native smoke checks partial-offscreen placement and activation
and stacking recovery, including Tab/Shift+Tab and selection preservation. Native
source smoke passed; 117 combined focused tests passed. Exact commands and
remaining manual procedures are recorded in
[Qt boundary validation](../Plan/UIElements.md#qt-boundary-review-validation).
The split-layout checkbox stays open for physical Alt+Tab and a second monitor
(unavailable here). Full build suite and frozen gates remain unrun.

### QuickList Input Revision

The shared component now transfers filter focus on navigation keys and toggles
row selection on right-click. Favorites inherits this without adapter changes.
[QuickList Input Revision](../Plan/UIElements.md#quicklist-input-revision) records exact
commands: 64 offscreen Qt tests and 9 native QuickList tests passed, including
optional-filter regressions and existing Favorites workflows. Packaging/full-suite
gates remain unrun.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Confirmed Favorites should inherit the shared input fix with no private
  adapter overrides; user-visible keyboard/mouse instructions updated.

### Adaptive Panel Revision

The shared component is named Panel; Favorites uses Panel and set_panel directly.
Old exported names remain aliases for compatibility. Adaptive sizing is provided
by the shared TextButton/Panel layout, not Favorites-specific resize handlers.
Exact commands and outcomes are in
[Adaptive Panel Naming and Sizing](../Plan/UIElements.md#adaptive-panel-naming-and-sizing):
111 focused tests passed; native compact/medium/wide sizing passed at
100/150/200% DPI, including close, reopen, saved sort and button-label fit.
Frozen packaging and the full build test suite remain unrun.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Applied the sole Panel name and bounded responsive action sizing through
  shared public components; no Favorites-specific sizing or persistence required.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Migrated Favorites to Panel/set_panel and verified capped action sizing,
  public-only imports, persistence and native session workflow. Source checks pass;
  existing frozen delivery gates remain pending.

### Main-Window Dock Revision

Exact commands and outcomes are recorded in
[Docking Validation](../Plan/UIElements.md#docking-validation). The 27-test dock/manager/theme
check and final 132-test focused cross-module run passed. Native source smokes
passed at 100/150/200% DPI, verifying status-bar adjacency, full width, pane-height
restoration, actual close-icon clicks and reopening with saved sort. Tab and
Shift+Tab preserve selection when moving between QuickList and the dock.

Close during a prompt rejects it without mutation; navigation is canceled and late
worker results cannot revive closed UI. Unload, pane/window closure and replacement
remove the dock. The independent public demo and Favorites API guard still pass.
Frozen build/smoke and the full test suite remain unrun; existing delivery gates
are not marked complete by this source-only revision.

### Public-Only Reference Plug-in

Resolution of the latest feedback: Favorites is intentionally an external-style
reference plug-in. Its entire runtime package passes the forbidden-import/private
host-access guard. The public export set, controller worker-to-Qt construction,
query/reuse, loader ownership, settings, prompts, theme hooks and navigation are
tested. The host owns window construction; Favorites keeps only its layout and
reaction methods in an optional public PaneToolWindow subclass. This avoids
moving Favorites-specific domain behavior into shared infrastructure.

The order defect required more than resetting owner: unload also replaced
sys.modules entries, so string-based mocks patched a different generation than
the imported command classes. The integration fixture restores its original
module generation and owner; unit commands receive an explicit test owner.
The integration-first sequence now passes. No product behavior is weakened to
accommodate test ordering.

Accepted design notes are recorded, not new feature promises: keep the frameless
transient host, Shift-toggle semantics and separate UI settings. Ctrl+B focuses
the manager; Escape closes it. Confirmation now compares QDialogButtonBox enums
directly. BottomPanel already had base styling; a public CSS hook now exposes it.

Exact commands and outcomes are in
[Public API Validation](../Plan/UIElements.md#public-api-validation): 192 focused tests
passed; native source smokes passed at 100/150/200% DPI. Frozen build/smoke and the
complete build test suite were not run and remain unchecked delivery gates.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Adopted the user's exported-only reference-plug-in criterion. The
  provisional widget API supersedes internal-only recommendations. Source checks
  pass; packaging gates remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Replaced internal Favorites dependencies with exported construction,
  hosting, resource, matcher and navigation APIs; fixed module/owner test
  isolation. Passed 192 focused tests and three native DPI smokes.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: **Source approved.** The exported-only criterion is met and
  mechanically enforced; the host-owned construction pattern is implemented
  as specified; the order-dependent test failure is fixed. Independently
  re-ran the three test directories exactly as `build.py test` does
  (offscreen, one process each): unit 320 OK (1 skipped), integration 111
  OK, Core 221 OK (4 skipped) — the Core directory takes ~2 minutes because
  of the 7-Zip tests, which is pre-existing. Only the frozen build and one
  user-requested full `build.py test` remain before `Done/`.

#### Verification

- Exit criterion: `Select-String` over `Plugins/Favorites/favorites/*.py`
  for `fman.impl`, `from core`, `import core`, `._widget`, `._theme`,
  `run_in_main_thread` → no matches. `test_portable.py` line 43 enforces the
  same list and asserts `fman.ui.__all__` exactly.
- `favorites/ui.py` imports only `fman.fs`, `fman.ui`, `fman.url`, PyQt5 and
  its own package; `favorites/__init__.py` uses `fman.ui.matchers`. Core's
  `quicksearch_matchers` now re-exports from `fman.impl.ui.matchers`, so
  there is one matcher implementation.
- Host-owned construction: `UiController.show()` → `run_in_main_thread` →
  `_show()` → `require_owner()` → `window_type(pane, owner)` →
  `cls.build(window, pane)` → one window per pane, `on_shown(query)`,
  focus. Favorites implements `FavoritesWindow.build(pane)` and reaction
  methods only; no `__init__` override, no thread helper.
- `require_ui_thread()` guards all exported widget constructors, `set_panel`
  and `navigate` (9 call sites).
- Private access moved behind public accessors: `Window.tool_parent()`,
  `Window.get_quicklist_item_css()`, `Window.set_panel/remove_bottom_panel`,
  `DirectoryPane.closed`. `styles.qss` no longer contains a
  `FavoritesWindow` rule; only `QuickList` selectors remain.
- Order-dependent combination `test_favorites_plugin` + `test_favorites` in
  one process: 30 OK.
- CHANGELOG API line reads "preserves fman 1.7.5; adds the provisional
  `fman.ui` extension"; `fman/ui.py` docstring states provisional status;
  Favorites README has a *Public API* section listing the names it uses.

#### Follow Up Tasks

Required before `Done/` (unchanged):

- [ ] `python build.py freeze` + `favorites_smoke --frozen`; the spec lists
      five hidden imports for this feature and only the frozen run proves
      them.
- [ ] One full `python build.py test` on the user's request (expect ~3–4
      minutes; the Core directory alone is ~2 minutes).

Required fixes (user decision 2026_09_13: address in this task, not deferred):

- [x] **Keep public classes Qt-free.** `DirectoryPane.closed` returns the raw
      `QWidget.destroyed` signal and `Window.tool_parent()` hands out the
      `MainWindow` QWidget. Replace them with Qt-free public shapes: a callback
      registration such as `pane.on_closed(callback)` (host connects it to the
      widget internally), and have `PaneToolWindow` obtain its parent widget
      inside the host so `Window` never exposes a widget. Update
      `test_portable.py` if the public names change.
- [ ] **Panel/list split across two top-level widgets.** The bottom panel is
      docked in the main window's central layout (`PanelDock`) while the list
      lives in a frameless tool window; `focusNextPrevChild` bridges focus
      between them. Decide and implement one of: (a) dock the QuickList in
      the main window as well, or (b) keep the split and add a Qt integration
      test plus a native smoke for the tool window being partially
      off-screen / on another monitor / behind the main window after
      Alt+Tab, asserting Tab and Shift+Tab still reach both parts. (a) is
      recommended; it removes the bridging code.
- [x] **Drop pre-release aliases.** Remove `BottomPanel` (alias of `Panel`)
      and `set_bottom_panel` (alias of `set_panel`) from `fman.ui`,
      `PaneToolWindow` and `Window`; update `__all__`, `test_portable.py`
      and the Favorites README. `fman.ui` has not shipped, so there is nothing
      to stay compatible with.
- [x] **One canonical `build` location.** Favorites implements
      `FavoritesWindow.build(pane)` and its controller merely forwards; the
      plan describes `UiController.build(window, pane)`. Choose one (the
      controller is recommended so a plug-in never subclasses a host widget),
      make Favorites follow it, and state it in the `fman/ui.py` docstring and
      the Favorites README *Public API* section so the next plug-in does not
      have to guess.

### Three-Component Revision

The [UI Elements component validation](../Plan/UIElements.md#three-component-validation)
records exact commands and results for this revision. The focused set passed
125 tests under offscreen Qt; the final component/manager rerun passed 27 tests.
Native source smoke passed at 100/150/200% DPI, including real Space selection,
frameless hosting, sort saved on disk and restored on reopen, folder navigation,
and label-fit checks. Screenshots of the manager and generic icon-toggle/action
panel were inspected. Filter/sort p95 was 5.06/4.46/4.86 ms at 200 rows.

This changes the earlier default-on-every-open behavior: Recent is now only the
unset-setting default. The manager's selected item has a filled background;
the independent current row has an outline even when also selected. No title-bar
or panel close control is supplied. Escape remains host-owned. Frozen/manual
acceptance remains pending; the full build test suite was not run.

### Folder-Only Follow-Up

With the PYTHONPATH setup below and QT_QPA_PLATFORM=offscreen:

```powershell
python -m unittest fman_unittest.test_favorites.FavoriteCommandTest.test_add_current_folder_saves_favorite
python -X faulthandler -m unittest fman_unittest.test_favorites fman_integrationtest.test_qt.FavoritesManagerIT
```

The first regression passed; the focused combined run passed 45 tests, exit 0.
It verifies that Add does not query the highlighted/selected files, file targets
are rejected before command dispatch, folder navigation still succeeds, and the
folder metadata check runs off Qt. No settings migration or public API change.
Historical file-favorite review wording below/above describes the superseded
scope, not a currently supported workflow. Frozen/manual gates remain unchanged.

Native source validation also passed with QT_QPA_PLATFORM=windows:

```powershell
python -X faulthandler -m fman_integrationtest.favorites_smoke
```

The real folder workflow passed, including Add, rename persistence, Go To,
bookmark-only deletion and reopening. Filter/sort p95 was 4.76 ms for 200 rows.
Changed files had no editor diagnostics and the scoped git diff whitespace check
passed. No full suite or frozen build was run.

### Review Fix Validation

Setup and final focused regression command (not the complete build test suite):

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -X faulthandler -m unittest fman_unittest.test_favorites fman_unittest.test_ui_elements fman_unittest.impl.test_theme fman_unittest.impl.plugins.test_plugin fman_unittest.impl.model.test_model fman_unittest.test_portable fman_unittest.test_release_support fman_integrationtest.impl.plugins.test_plugin core.tests.commands.test___init__ fman_integrationtest.test_qt fman_integrationtest.impl.plugins.test_favorites_plugin
```

The final combined run passed 185 tests, exit 0. The focused QuickListIT run passed
all five tests, exit 0. Offscreen font and
unsupported raise/size-hint warnings remain diagnostic noise, not skipped tests.

First checks after each implementation slice, all exit 0:

```powershell
python -X faulthandler -m unittest fman_integrationtest.test_qt.FavoritesManagerIT
python -X faulthandler -m unittest fman_unittest.test_ui_elements fman_integrationtest.test_qt.SortedFileSystemModelIT
python -m unittest fman_unittest.impl.plugins.test_plugin fman_integrationtest.test_qt.SortedFileSystemModelIT
python -m unittest fman_unittest.test_ui_elements fman_unittest.test_favorites fman_integrationtest.test_qt.QuickListIT
python -X faulthandler -m unittest fman_integrationtest.test_qt
python -X faulthandler -m unittest fman_integrationtest.test_qt.SortedFileSystemModelIT
python -X faulthandler -m unittest fman_integrationtest.test_qt.QuickListIT
```

The model helpers now drain initialization before mutating filesystem fixtures;
this fixed a fixture-removal/watcher-start race observed in the first full Qt run.
Manager tests additionally verify No as default, window modality, Escape and pane
destruction. After moving navigation cancellation into the shared disposal path,
the final manager-only offscreen run passed 15 tests, exit 0, including immediate
settlement on Escape before deferred destruction.

Native source workflow, button-fit and two-pane startup-hop measurements:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
foreach ($scale in @('1', '1.5', '2')) {
    $env:QT_SCALE_FACTOR = $scale
    python -X faulthandler -m fman_integrationtest.favorites_smoke
    if ($LASTEXITCODE -ne 0) { throw "Source smoke failed at scale $scale" }
}
Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue
```

All three passed with filter/sort p95 5.13/4.96/4.85 ms. After row-resize repair,
the same smoke at scale 2 passed again (5.20 ms); the captured layout was inspected.
An initial external measurement probe imported fman before temporary settings were
configured and failed startup isolation. Measurement now lives inside the smoke
driver after that setup. Model workers are stopped before dispatcher teardown.
No packaged artifact was built, and remaining delivery/manual gates listed below
still apply. No full `python build.py test` run was requested or performed.

### Earlier Implementation Validation

Environment setup from the repository root:

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'windows'
```

- First implementation validation: `python -m unittest fman_unittest.test_ui_elements`.
  Corrected one test expectation for an earlier subsequence match; all four initial
  tests passed. The module now includes navigation-hook regressions as well.
- Final focused existing/new regression command: 138 tests passed:

```powershell
python -m unittest fman_unittest.test_favorites fman_unittest.test_ui_elements fman_unittest.impl.test_theme fman_unittest.impl.plugins.test_plugin fman_unittest.impl.model.test_model fman_unittest.test_portable fman_unittest.test_release_support fman_integrationtest.impl.plugins.test_plugin core.tests.commands.test___init__
```

- Native Qt/model/loader integration: 38 tests passed, exit code 0, including
  rejection of old worker completions during newer operations:

```powershell
python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt fman_integrationtest.impl.plugins.test_favorites_plugin
```

- Real source application smoke uses temporary settings/folders, real plug-in
  loading and native widgets. It verifies startup, manager reuse/query handling,
  rename on disk, Go To closure, reopen defaults, bookmark-only deletion, empty
  controls and a 200-row filter/sort benchmark:

```powershell
python -m fman_integrationtest.favorites_smoke
$env:QT_SCALE_FACTOR = '1.5'
python -m fman_integrationtest.favorites_smoke
$env:QT_SCALE_FACTOR = '2'
python -m fman_integrationtest.favorites_smoke
Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue
```

- Source workflows passed at 100%, 150% and 200% scaling. Visual inspection of
  narrow-window captures exposed action-label clipping from inherited Windows
  button padding; local padding was corrected. The final 200% smoke includes a
  button-content-width assertion and passed with filter/sort p95 4.92 ms at
  200 rows. These are synchronous filter/sort timings, not a full event-loop-gap
  or operating-system handle-leak benchmark. The final screenshot was inspected.
- After the final ownership and operation-generation changes, the 150% source
  smoke passed again with label-fit assertions and a 4.67 ms filter/sort p95.
  Task-related whitespace checks and task section/local-link checks passed.
- Initial offscreen dialog tests crashed inside Qt. Native dialogs also crashed
  during teardown with the old worker-owned QApplication harness. A minimal
  main-thread dialog exited cleanly; the new main-thread runner reuses the existing
  test cases/helpers and passes the native integration suite. Smoke-driver startup
  ordering and a real pane/window ownership mismatch were corrected and rerun.
- Changed application files have no editor diagnostics. Focused tests were used;
  the full `python build.py test` suite was not run.
- `python build.py freeze`: user skipped the command; it was not retried. The
  spec includes dynamic UI imports, but no new frozen artifact or frozen workflow
  validation is claimed. When the gate is authorized, run:

```powershell
python build.py freeze
python -m fman_integrationtest.favorites_smoke --frozen target/RoyiFileManager/RoyiFileManager.exe
```

- Remaining acceptance checks: frozen workflow, real network/virtual-filesystem
  navigation, alternate-theme visual inspection, full keyboard-only manual pass,
  restart persistence and repeated-session OS handle/event-loop-gap measurements.
  Source tests cover persistence on disk and reopen behavior, not process restart.
- Keep this task under Plan and its index entry Pending until required delivery
  gates pass. The UI Elements task also remains pending for its deferred surfaces.