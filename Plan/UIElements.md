# UI Elements

## Task

Provide a small shared, themed toolkit available to application plug-ins.
Priorities, in order: correctness, clean and simple UI, then performance.
Status: the Favorites-required subset is implemented and source-tested; broader
API names outside the revised three-component contract remain proposed. Frozen validation was skipped. Phase A serves
QuickSearch/QuickList navigation, Favorites management and Search File Content; broader
viewer/editor infrastructure requires separately approved consumer plans.

The file-hash consumer additionally ships `fman.ui.OutputTextBox`: selectable
plain-text output with a top-left copy icon and Return/Enter copy-all. Its source
and portable ZIP workflow are validated at 100/150/200% DPI. See the completed
[Calculate File Hash task](../Done/CalculateFileHash.md); this does not complete
the broader UI Elements roadmap.

The motivating elements are a selectable QuickList and a compact bottom
interaction panel inspired by Sublime Text's find panel. Extend that foundation
with composable results and preview surfaces for the following plug-in ideas:

### Content-search Table Revision

The 2026_09_14 [Search File Content revision](../Done/SearchFileContent.md) is the
canonical contract for the next shared element: Qt-free
`show_table(get_rows=..., num_columns=..., columns_header=...)` returning a plain
TableHandle, with immutable TableRow records, snapshot refresh, fuzzy filtering
and F1-style presentation. F1 remains independent and unchanged,
including its current substring filter; migration is deferred by the user.
The content-search form is a docked Panel. Search runs in the background with
progress in the status bar, then opens a modal Table with collected results.
No Table is created during scanning; progressive population is deferred.
Hosting supports modal=True and modal=False without making plug-ins construct
windows or interact with Qt. Content search selects modal; a synthetic rename
preview uses modeless hosting so its associated Panel remains interactive.
The first real consumer has File Path/Snippet columns; a synthetic current-name/
proposed-name fixture verifies reuse for a later File Rename / Replace feature.

Table has no explicit buttons, including no filter-clear button, row buttons,
checkboxes or action footer. It highlights one row but tracks a logical current
cell. Optional `file_path_column` and `folder_path_column` are distinct zero-based
indices, both defaulting to None. Double-click/Enter reveals a file or enters a
folder only in the designated cell; ordinary cells have no built-in operation.
Right-click offers host-owned Copy Path / Go To for resolvable path cells only.
`resolve_path=None` uses full cell text and a captured base, with an optional
pure callback for labels/payloads; no filesystem/CWD lookup during resolution.
Keyboard equivalents and stale-cell/menu guards live in the canonical plan.
This does not change
QuickList's existing multi-selection or right-click toggle behavior.

This supersedes this roadmap's older search tree/adjacent-preview requirements,
private toolkit imports, public QWidget/signal/menu construction, row-wide file
actions, Qt-thread QProcess choice, progressive search results, F1 migration
and deferral of all tables to Folder Diff. Those historical
sketches are not gates for this increment.
Comparison-specific columns/actions, previews, editors and actual rename/replace
remain deferred. The Qt-free facade is proposed, not an existing export. Preserve
legacy widget exports and the public fman 1.7.5 API without migrating unrelated
plug-ins; new consumers use services/handles instead. API, engine limits and
acceptance tests live in the consumer plan, not a second copy here.

The review resolution there also governs this increment's host integration:
Table is an internal QWidget usable in a plain QDialog; plug-ins get TableHandle,
never widgets, signals, Qt enum/point/icon objects or a raw window. show_panel
accepts immutable control descriptors and returns PanelHandle. The host owns
layout, icon resources, status activity, clipboard, tracked navigation, menus,
focus and disposal. Callbacks receive ordinary rows/column indices or control
values and run through the host dispatcher; plug-ins do not perform Qt wiring.
Existing loader-created UiController owners can be reused with require_owner(),
without calling its legacy show/build hooks; a subclass without a build override
is the chosen owner carrier, not a new marker base. Resource ownership itself
requires an additive loader hook: ExternalPlugin._load_classes supplies the
new read-only UiOwner.resource_root at construction, with no asset I/O during
registration. Keep default UiOwner construction and legacy controllers compatible.

The internal results host is TableWindow(ToolWindow), with dialog flags instead
of tool-window flags. It supplies QObject timer parenting, busy state, guarded
post, alive/owner and disposed cancellation to the unchanged session.navigate;
no Qt object enters the public handles. It does not inherit PaneToolWindow's
panel removal on results close. The canonical plan also names the activation/
blocking-modal events and activeModalWidget rechecks for deferred presentation.
Focused adapter, loader/resource, lifetime and legacy-widget regressions are gates.

Keep panel-only search free of blank floating windows and unrelated status
message overrides. The host contains focus in modal results and bridges to the
associated Panel for modeless results. Go To defaults to closing only modal
results after tracked success, with a plain close_on_navigate override. Preserve
the captured path base and operation inputs across navigation. Host rendering
uses the nested Panel layout internally, with the measured dock-height budget;
plug-ins do not create the grid or change control properties. Keep legacy
IconButton defaults and implement noncheckable actions internally. Scope Table
styles and check directory-pane/F1 regressions. Exact signatures and failure/
completion/Stop/close semantics remain in the consumer plan, not duplicated here.
These additions remain proposed, with the canonical plan's focused tests as
gates; the earlier implemented widget signatures are not silently changed.

### Component Responsibilities

| Component | Responsibility |
| --- | --- |
| QuickSearch | Built-in fuzzy search over items and single-item choice. |
| QuickList | Navigate and select multiple items, with optional built-in fuzzy filtering. |
| Table Service (proposed) | Qt-free data/callback API and handle for buttonless filtered results; optional cell path roles, host navigation/menus and modal/modeless hosting. |
| Bottom Interaction Panel | Configure operation behavior and expose actions on the chosen items. |

Keep the view elements independent of operations. Neither QuickSearch nor
QuickList embeds checkboxes, operation options or action buttons in its list.
QuickList uses selection highlighting and standard Ctrl/Shift interactions, not
selection checkboxes. A navigation query belongs to the view; operation queries,
settings and commands belong in the separate Sublime Text-style panel below it.
Changing the operation does not require a different list-view implementation.
Content-search path commands use the host's standard cell menu; the docked Panel
still owns the search inputs and Search/Stop controls. Consumers may supply plain
custom-action records/callbacks but never create menus or access Qt objects.

| Consumer | Required UI infrastructure | Feature-owned logic |
| --- | --- | --- |
| Bookmarks/Favorites management | Searchable multi-selection list, selection count, remove action | Bookmark identity, persistence, confirmation and removal |
| F1 Shortcuts (reference only) | Existing independent dialog, unchanged; no Table migration | Existing binding collection, substring filtering, grouping and help-only behavior |
| Simple text diff viewer and merger | Two text surfaces, coordinated scrolling, range highlights, hunk actions, dirty-state handling | Diff engine, alignment, merge decisions, conflict checks and saving |
| QuickLook: images, Markdown, video, PDF and other files | Preview host, viewer controls, loading/error states, overlay or pane placement | Format detection, decoding/rendering providers and security policy |
| File content search | Qt-free docked Panel, status-bar progress, then modal Table with File Path/Snippet columns; path-cell Copy Path / Go To | ripgrep, bounded result collection, filename/content semantics, captured base and immutable match payloads |
| File Rename / Replace (future) | Same modeless Table and interactive Qt-free Panel; source path role only, explicit snapshot refresh | Virtual-name computation, fixed source identities/base, conflict checks, explicit Apply, mutations and recovery |
| Folder diff with hash-table comparison | Multi-column comparison results, filters, paired previews, explicit operation actions | Relative-path matching, hash algorithms, file identity, collision/error policy and synchronization |

### Tasks to Support

These workflows explain the long-term direction, not a commitment to implement
all their UI contracts now. Phase A covers the consumers below that already have
task documents; later phases require approval of their own consumer plans.
Domain engines remain separate work.

#### 1. Simple Text Diff Viewer and Merger

The user chooses two text files, sees their differences side by side, moves
between differences, and applies selected changes to a merge result before saving.

- UI needs: two labeled text views, difference highlights, previous/next change
  actions, aligned scrolling, and a compact bottom panel with comparison options.
- Merge needs: per-change apply/reject actions, an explicit editable result
  surface, undo/redo, dirty indication, Save/Save As, and Save/Discard/Cancel on
  close. The user must see which file is the write target.
- Phase C boundary: PreviewHost is read-only. The merger task must choose its
  editor surface alongside its diff engine, encoding and save behavior. This
  document defines no editable-document API, revision protocol or editor events.
- Correctness scenario: if the destination changes externally after comparison,
  the feature rejects a stale save and the UI retains the unsaved merge result.

#### 2. QuickLook for Files

The user previews the current file without opening an external application,
then moves through nearby files while the preview follows the current item.
Required target formats include images, Markdown, video and PDF, plus plain text.

- Phase C UI needs: a modeless tool window with file identity/title and
  loading/error/unsupported states. A provider declares which of a fixed set of
  controls it supports; the host shows those. Choose the controls only after
  selecting decoders, rather than defining a media-control API in Phase A.
- Infrastructure boundary: decoder dependencies, Windows playback reliability,
  packaging, licensing and untrusted-file handling need the QuickLook plan's
  review. Do not assume QtPdf is available in PyQt5 or Windows video works merely
  because QtMultimedia imports. Verify the bundled Qt version before relying on
  QTextDocument.setMarkdown (Qt 5.14+). Inactive-pane placement is deferred to a
  separately approved QuickLook-in-pane design, not the initial viewer.
- Correctness scenario: rapidly changing files never displays a late preview
  under the new file's title; closing/hiding releases or pauses media resources.

#### 3. File Content Search with Table

The user sets File Name Pattern, Content Pattern and Include Subdirectories in
a Panel and explicitly starts Search. The status bar reports progress while
both panes remain interactive. After completion or an explicit Stop, nonempty
results appear in a modal Table for fuzzy filtering and navigation. Each pattern
has an independent regex SVG toggle; recursion also uses an SVG toggle. Every
search-panel button has a tooltip; the results surface has no explicit buttons.

- Table uses the callable population/count/header contract in
  [Search File Content](../Done/SearchFileContent.md), with exactly File Path/Snippet
  columns initially. One matching line is one row; metadata stays in its payload.
- Single click selects row/current column without operating on files. The
  plug-in sets file_path_column=0 and folder_path_column=None. The host resolves
  File Path against the explicit captured search root, offers Copy Path / Go To,
  and reveals the file on double-click/Enter. Snippet remains ordinary text with
  no built-in action, even if it looks like a path. No Open File/Copy Snippet
  commands, row-wide file menu, private-view access or results buttons.
- Reuse F1's visual treatment without modifying its implementation or filter.
  Table filter keystrokes never invoke an engine or population callback. A
  separate preview pane and progressive row delivery are deferred. Use only
  verified open-source SVGs with their applicable notices.
- The shared layer owns presentation, validation, menus, clipboard, navigation
  and lifetime; the plug-in owns bounded engine production and search semantics.
  Use public Qt-free `fman.ui` services/handles, throttled progress and one immutable
  terminal snapshot. Modal Close returns to the retained Panel/options; panel
  Close cancels the session and prevents any late results dialog.
- Correctness scenario: filtering preserves row identity; a disposed session
  cannot accept stale status or open a modal. Zero hits show status without an
  empty dialog; partial results are labeled. Merely selecting never navigates
  or writes files. A virtual-rename fixture proves operation-independent reuse.

#### 4. Folder Diff with Hash-Table Comparison

The user chooses left/right directories, builds or compares hash tables keyed by
relative file path, and inspects equal, different, left-only, right-only and
unreadable/changed-during-scan entries. A hash table here is the comparison
manifest of file paths, observed identities and digests, not a UI widget.

- Phase B UI needs: two explicit directory inputs, comparison/hash options, Start/Stop,
  progress, sortable multi-column results, status filters and multi-selection.
  Selecting a pair can show side-by-side previews or open the text diff tool.
- If later synchronization is offered, show an explicit staged operation list
  with direction and destination before Apply. Selection or equality status alone
  never initiates copying, replacement or deletion.
- Infrastructure boundary: table/tree presentation, actions and progress are
  shared; manifest creation/storage, hash algorithms, path/case rules, file
  change detection and actual synchronization belong to the folder-diff task.
- Correctness scenario: a failed or canceled hash is Unknown/Error, never Equal;
  applying operations revalidates the compared file versions and reports conflicts.

#### Supporting Pilot: Bookmarks/Favorites Management

The user filters bookmarks, selects several, and removes them in one explicit
operation, or uses Move Up/Move Down to change their stored order. QuickList must
retain selection by bookmark ID, show hidden-selected counts, and distinguish
Remove Bookmarks from deleting the bookmarked files. The shipped
[Favorites plan](../Done/Favorites001.md) rejected external JSON editing because
the configuration cache would not observe it; explicit in-process reorder
actions avoid that problem. Reordering is a deliberate extension to its shipped
recency policy, not behavior that already exists.

#### Phase A Reuse: Confirmation and Result Actions

- Bounded list confirmation serves Favorites removal and can later serve
  [Process Pane](ProcessPane.md), [Unpack Archive](UnpackArchive.md), and
  [Calculate File Hash](../Done/CalculateFileHash.md). Show the exact total and the first
  K captured item labels, then the omitted count; default to Cancel/No.
- Both hash commands use a centered OutputTextBox beneath a file-path heading.
  Calculate File Hash By selects the algorithm in QuickSearch before showing
  the result; neither command mounts a Panel. Copy belongs to the output
  control; comparison and alternate copy formats remain deferred. This
  replaces the earlier hash QuickList/action-picker sketch for that consumer.

## Scope

Phase A includes only:

Delivery split approved for Favorites002: implement its shared QuickList/filter,
separate action panel, bounded confirmation, modeless owner lifecycle and required
navigation/transaction integration first. Favorites002 supersedes this document's
older reorder and close/reopen pilot wording. Its manager stays open across
actions, sorts by Recent/Name/Path and uses explicit confirmed Delete fallback.
Table, preview, content-search and other Phase A surfaces remain pending and do
not gate this initial subset. This subset does not complete the UI Elements task.

- QuickSearch as a single-choice fuzzy navigator, without embedded operation
  controls; preserve legacy Quicksearch callbacks and acceptance behavior.
- Modeless QuickList with current/selection separation and optional fuzzy
  filtering, plus a blocking command-thread convenience for simple pickers.
- A separate bottom Interaction Panel for shared operation controls and actions
  scoped to the current item or captured selected set.
- Favorites Manager with Recent/Name/Path sort and confirmed multi-remove,
  following Favorites002 rather than the superseded manual-reorder pilot.
- Qt-free show_panel/show_table, plain descriptors/callbacks/handles, owned status
  activity and optional file/folder roles with default resolution. Search opens
  modal results after collection; a modeless Panel-driven rename fixture proves
  reusable focus, snapshot refresh and navigation/close policy. No real rename,
  adjacent preview, live search results or F1 migration in this increment.
- An owned operation handle accepting worker and Qt-thread producers, bounded
  updates, cancellation, generation rejection and deterministic disposal.
- Bounded list confirmation and a hash-result action-picker fixture.

Phase B, gated on an approved Folder Diff plan: comparison-specific Table
extensions, status filters, staged operation lists and paired read-only previews.
Phase C, gated on approved
QuickLook/Merger plans: provider controls/media lifecycle and an editor surface.
Pane-local panels and pane content replacement need their own consumer approval.

Excluded from this task:

- Shipping all motivating plug-ins, a complete diff/merge engine, hash scanner,
  ripgrep integration, or image/Markdown/video/PDF decoding implementations.
- Arbitrary HTML/JavaScript forms,
  a general docking system, user-defined layouts, or a second theme engine.
- Replacing the directory model, redesigning ordinary file operations, or
  changing existing Quicksearch click/Enter behavior and return values.
- Automatic migration of other plans or global bindings for new elements;
  Search File Content's explicit revision is a gate, not silently implied here.

Compatibility: preserve the public `fman` plug-in API from fman 1.7.5. The user
explicitly requested reusable plug-in components: expose the implemented view,
panel, controls, settings binding and ownership helpers through additive fman.ui.
This is a provisional RoyiFileManager extension, not part of fman 1.7.5;
breaking extension changes require CHANGELOG migration notes. Favorites is the
reference for the shipped widget-based subset and retains that compatibility.
All new consumer UI uses the Qt-free facade; it may reuse loader-provided plain
owners but not widget build hooks. Migrating existing plug-ins is separate work.
Implementation stays under fman.impl.ui. This replaces the earlier internal-only
restriction for this small surface; future tree/preview/editor APIs remain gated.
Do not
implement the proposed checkbox-enabled `show_quicksearch_extended` API under
this design. Its separate plan needs revision before implementation.

## Design

### General API Boundary Revision

For the new Table/search increment, the Qt-free contract above and its canonical
consumer plan take precedence over the widget-construction examples below.
Those document the existing compatible legacy extension, not permission for a
new plug-in to import Qt, connect signals or obtain widgets. Additive facade
tests must prove that both the new plain API and legacy consumers still work.

The general fman Window and DirectoryPane wrappers must not hand out widgets or
signals or accept panel widgets. Internal PaneToolWindow owns private parent,
theme and dock access; external plug-ins continue using only exported host APIs.
DirectoryPane.on_closed accepts a no-argument callback and returns an idempotent
unsubscribe function, with registration/removal dispatched to the UI thread.
The existing opt-in fman.ui widgets remain Qt components; this is not a promise
that the entire UI extension is toolkit-independent.

Controller.build is the canonical construction hook. Favorites demonstrates a
generic host plus a plain domain session instead of a host-widget subclass.
Shown, busy_changed and disposed notifications avoid overriding host behavior.
Rejected: retaining raw bridges under different public names, retaining unshipped
aliases, or relocating the user-approved floating list merely to remove focus
bridging. Retain the split layout and validate focus recovery explicitly.

Runtime: one close subscription per hosted pane session, removed on disposal;
no added polling, workers, scans, timers, persistence or startup I/O. Notifications
run only on show/busy/dispose events. Existing bounded work, cancellation and
stale-result rejection remain unchanged; unopened UI registers no subscriptions.

### Main-Window Panel Docking

The component is named `Panel`, since this is the only supported panel placement.
Use `PaneToolWindow.set_panel(panel)`. The unshipped `BottomPanel` and public
`set_bottom_panel()` aliases have been removed. Historical review/validation
entries retain their original names; current API instructions supersede them.

TextButton uses horizontal expansion with a default cap of 160 Qt logical pixels,
configurable per button as `TextButton('Run', max_width=120)`. Panel.add assigns
text buttons equal stretch by default; explicit stretch values remain supported.
At compact widths, labels retain their style/font-derived minimum widths. At wide
widths, buttons stop growing and unused space belongs to stretch spacers or other
expanding controls. A label's minimum width takes precedence over a smaller cap
to avoid clipping. Font/style changes update the effective cap; fonts themselves
do not scale with window width. Icon and close buttons remain compact.

Sizing runs through Qt layout, without resize timers, polling, workers, I/O or
new configuration files. This replaces fixed text-sized actions, not the existing
single-session dock, close behavior or JSON binding. Test compact/medium/wide
widths, custom caps, label fit, rejected old names and native 100/150/200% DPI.

The user clarified placement: the operation panel belongs at the bottom of the
main application window, immediately above its status bar, not below a floating
QuickList. This supersedes earlier tool-window footer placement. MainWindow wraps
its existing horizontal file-pane splitter in a zero-margin vertical layout and
adds one optional full-width dock below it. File models and splitter persistence
are unchanged; opening reduces pane height and closing restores it.

`PaneToolWindow.set_panel(panel)` is the exported session-owned entry point.
The host reparents the panel into the dock and adds a small native Qt close icon
at the upper right, with tooltip/accessibility name "Close panel". The icon ends
the UI session: close QuickList and prompts, cancel navigation, dispose bindings,
unsubscribe and reject late results. It does not unload the plug-in package or
undo saved settings; the command can start a fresh session afterward. Escape in
either surface closes the same session; prompts consume their own Escape first.
Tab/Shift+Tab bridge the QuickList and dock controls without changing selection.

One dock is available per main window. Claiming it closes the previous session,
including a session belonging to another pane. Distinct main windows remain
independent. No hidden session stack or automatic reopen. Parent, theme and dock
integration belongs entirely to the internal host; general Window APIs neither
return nor accept widgets. Plug-ins use the session method so disposal is
automatic. All docking is Qt-thread-only.

Runtime: no extra worker, scan, polling or persistent settings for placement.
An unused dock is absent and consumes no vertical space; only a small central
layout and a null slot remain. Existing bounded workers handle operations, with
late-result rejection on close and no promise to interrupt already-started I/O.
The existing delayed main-window shown signal now uses an owned single-shot timer
so closing/deleting a window cannot leave a callback to deleted Qt state.

Alternatives: a floating footer is rejected by the requested placement. A general
QDockWidget system adds unrequested dragging/undocking behavior. A single layout
slot preserves the panes and keeps ownership explicit. A shared slot means only
one docked session per window; this deliberately replaces simultaneous per-pane
Favorites managers within that window.

Acceptance: dock spans both panes and touches the status bar; controls and native
close icon fit at 100/150/200% DPI; close reclaims pane height, ends UI work and
allows reopening with saved sort. Public-only demo, replacement, Escape, Tab,
prompt rejection, unload and late-result regressions must pass. Frozen delivery
remains gated separately; this change does not complete deferred toolkit work.

### Revised Three-Component Contract

This user-requested revision supersedes the earlier internal-only Favorites
subset and generic Qt-selection implementation. Provide an additive fman.ui
import surface for any plug-in, preserving all existing fman APIs.

- QuickList is an embeddable QWidget, not a dialog: no title bar, close button,
  actions or configuration persistence. Title/secondary-text rows use QuickSearch
  theme rules. Optional fuzzy filtering retains selected identities, including
  hidden selections. Current highlight and explicit selection remain distinct.
  Space toggles current; Insert toggles and advances; Shift+Up/Down toggles then
  moves, Ctrl+A selects visible rows. Shift+Home/End/Page keys toggle the traversed
  range like the file pane. Plain clicks move current only; Ctrl/Shift-click
  toggles items/ranges like the file pane. Text
  fields retain Space and editing shortcuts; Tab moves focus to the list.
- Panel is a standalone, full-width themed horizontal strip with no
  built-in close control or Favorites-specific actions. It composes IconButton
  (checkable boolean), TextButton (command, or checkable boolean setting), and
  DropDown (explicit label/value choices). Icons require accessible names/tooltips.
- JsonSettings binds panel controls to top-level keys in a plug-in-named JSON
  file via existing load_json/save_json. Deep-copy loaded data; serialize
  reload-latest updates with the host Resource lock, preserve unrelated keys,
  publish successful commits to other bindings, and restore controls on failure.
  Loading/saving runs in existing bounded workers, never on Qt; controls are
  disabled while their write is pending. Disposal/unload rejects late results
  and queued writes; an already-started atomic commit may finish. No polling,
  startup I/O, idle threads, or work when no binding is instantiated.
- Favorites keeps QuickList in a frameless host similar to QuickSearch and docks
  Panel above the main window status bar. Escape and the dock's close icon
  dismiss the paired session; the shared host owns window closing.
  Its Sort By choice persists separately from bookmark data, defaulting to Recent
  only when unset. Delete/Rename/Go To remain commands, not configuration values.

Validation: Qt keyboard/mouse and hidden-selection regressions; embedded-widget
and frameless-host assertions; all three control types; JSON load/save/failure,
unrelated-key preservation, cross-panel refresh and disposal; public imports;
native Favorites workflow and compact panel screenshots at 100/150/200% DPI.
Frozen validation remains subject to the existing user-skipped gate. No unrelated
preview/tree/editor components are included in this revision.

### Plug-in API

Import components and host services from `fman.ui`. Commands call
`Controller.show(pane, query='')`; the host dispatches to Qt, constructs the
window and calls `build(window, pane)`. Neither QuickList nor Panel creates
a window. The plug-in supplies layout, domain actions and error policy. The host
owns window lifetime, focus, query seeding and one-window-per-controller-per-pane
reuse. Existing `fman.show_quicksearch` remains available alongside QuickList.

```python
from fman.ui import (
  Panel, DropDown, IconButton, JsonSettings, ListItem,
  QuickList, TextButton, UiController
)
from fman import DirectoryPaneCommand
from PyQt5.QtWidgets import QStyle, QVBoxLayout


class SearchUI(UiController):
  @classmethod
  def build(cls, window, pane):
    layout = QVBoxLayout(window)
    view = QuickList(window, fuzzy=True, css=window.item_css)
    view.set_items((ListItem('one', 'First result', 'Secondary text'),))
    window.focus_widget = view
    panel = Panel(window)
    icon = panel.style().standardIcon(QStyle.SP_FileDialogDetailedView)
    match_case = panel.add(IconButton(icon, 'Match case'))
    scope = panel.add(DropDown(
      (('Current folder', 'current'), ('All folders', 'all')), 'Scope'
    ), stretch=1)
    inspect = panel.add(TextButton('Inspect'))
    settings = JsonSettings('MySearch UI.json', panel, cls.owner)
    settings.bind('match_case', match_case, False)
    settings.bind('scope', scope, 'current')
    settings.failed.connect(window.alert)
    window.disposed.connect(settings.dispose)
    inspect.clicked.connect(lambda: window.alert(
      view.current_item.title if view.current_item else 'No current item'
    ))
    layout.addWidget(view)
    window.set_panel(panel)
    settings.load()


class ShowSearch(DirectoryPaneCommand):
  def __call__(self, query=''):
    SearchUI.show(self.pane, query)
```

#### Host and Lifetime

`UiController.owner` is bound by the plug-in loader for each load generation.
`require_owner()` raises a readable RuntimeError before construction if no active
owner exists. Do not assign an owner in production plug-ins. Tests and manually
managed tools may explicitly use `UiOwner`; `attach(dispose)`, `detach(dispose)`
and `invalidate()` manage its lifetime. Unload invalidates the owner before code
is removed. Invalidation is safe from a worker; widget closure is queued to Qt.

`show()` can be called from command workers or Qt and returns the hosted window
after synchronous, short Qt dispatch. Never call it while holding a worker/model
lock. `build()` and reaction callbacks run on Qt and must not perform I/O.
All component constructors reject non-Qt construction before invoking Qt.
`UiController.build(window, pane)` is the single canonical construction hook.
Keep domain behavior in a plain Python session object and connect host
notifications; Favorites follows this pattern without subclassing a host widget.
The existing optional window_type hook is not needed for ordinary plug-ins.

`PaneToolWindow` provides `pane`, `owner`, `item_css`, `alive` (thread-safe Event),
`busy`, `focus_widget`, `bottom_panel`, and `disposed` (once, on Qt). Set `focus_widget` to the
QuickList; the host focuses it and seeds nonempty supplied queries without
clearing an existing query on ordinary reopen. Connect `shown(query)` for
retry logic; it is emitted after host query seeding on every show/reuse. Connect
`busy_changed(busy)` for control enablement; it is emitted by set_busy. Use
`disposed` to unsubscribe and
dispose plug-in bindings. `close()`/Escape dismiss; the default host is frameless
and intentionally has no mouse move/resize frame or close button.

The general pane/window API does not expose widgets or Qt signals. Register
`unsubscribe = pane.on_closed(callback)` for a no-argument, once-only callback
on pane destruction, delivered on the UI thread. Registration and idempotent
unsubscribe may be called from command workers or UI callbacks; they dispatch
synchronously and must not be called while holding a lock needed by UI work.
Unsubscribe is safe after pane destruction. Register only while the pane exists.
The host owns parenting, theme and dock integration internally. No plug-in needs
private pane/window/theme fields or a thread-dispatch helper. This restriction
does not remove Qt widgets from the opt-in fman.ui component layer.

#### Work, Navigation and Prompts

`ToolWindow.work(operation, completed) -> bool` is the public worker path.
There are two shared on-demand slots across windows, navigation and JSON bindings,
no queue, idle workers or startup I/O. A busy/closed window rejects work; global
saturation restores busy state, reports an alert and returns False. Work receives
no Qt permission: capture immutable data and use `alive.is_set()` for cooperative
cancellation. `completed(result)` runs on Qt; exceptions become alerts. Closing
or unloading drops late delivery; already-started I/O may finish. `post(callback,
*args)` queues a short callback to Qt with the same lifetime guard. Connect
`busy_changed` to update action controls without overriding host methods.

`navigate(pane, url, on_done, *, window, check=None, timeout=30)` returns
`NavigationHandle` with `done` and thread-safe `cancel()`. Call it on Qt. The host
owns admission, tracked command dispatch, waiting and cancellation; existing
command/location rewrite hooks still run. Optional `check(url)` runs off Qt and
raises to reject a target. Exactly one terminal outcome is queued as
`on_done(outcome, message)`: success, failure or superseded. Closed/unloaded
windows suppress callbacks. Busy rejection does not clear another operation's
busy state. The Qt single-shot deadline covers precheck and dispatch as well as
the completion wait; it exists only while navigation is pending. The default
30 seconds is configurable for slow providers. Timeout/cancel rejects stale work
but cannot interrupt OS I/O or roll back a transition already started; two separate
initialization slots bound model scans that outlive cancellation.

Nonblocking Qt-thread methods: `alert(text)`,
`confirm(title, records, hidden, footer, accepted)` and
`rename_prompt(label, name, accepted)`. Confirmation captures `(name, path)`
records, shows total/hidden count and at most ten bounded labels, defaults to No,
and calls `accepted()` only for Yes. Rename passes the entered string to
`accepted(name)`; the plug-in validates it. Prompts are window-modal and consume
Escape before the tool window. Text is plain, not interpreted HTML.

#### Transactions and Themes

`settings_resource(filename) -> Resource` returns the host-global, reload-stable
coordinator for a plug-in-specific JSON basename. `Resource.lock` is a public
reentrant lock: hold it around reload-latest, validation, `save_json` and
`committed(immutable_snapshot)`. Publish the returned notification *after*
releasing the lock. Failed writes must not call committed. Resource itself does
no I/O and is not a data cache. `subscribe(callback, snapshot_loader)` atomically
returns `(revision, snapshot)`; `unsubscribe(callback)` removes the subscriber.
`publish(notification)` invokes callbacks on the publisher's thread. Callbacks
must be short/nonthrowing and marshal through `window.post`; concurrent commits
can arrive out of order, so receivers reject stale revisions. In-flight captured
notifications can outlive unsubscribe; use owner/alive guards. JsonSettings uses
the same coordinator, so a command and a panel can share commits safely.

`matchers` exports path_starts_with, basename_starts_with, contains_substring,
contains_chars and contains_chars_after_separator. Core forwards to the same
host implementation. Direct legacy matchers preserve their existing case rules;
QuickList handles casefolding and Unicode highlight mapping for its matcher.

Call `window.set_panel(panel)` after composing controls, instead of adding
the panel to the tool window layout. The dock's close icon ends the whole session;
its ownership and single-slot replacement policy are specified above. Panels not
docked remain ordinary reusable widgets. Do not retain/use a panel after disposal.
`window.set_panel(None)` detaches this session's panel without ending the result
window or affecting another session's dock. Recreate controls before remounting.

Theme.css hooks `.quicksearch-query` and `.quicksearch-item` also style QuickList.
`.panel` maps to object name `panel` (`.bottom-panel` is a compatibility alias);
`.plugin-tool-window` maps to
`plugin-tool-window`, inherited by every tool subclass. `.plugin-panel-dock` styles
the full-width dock including its close affordance. Row text uses the existing
Quicksearch item title/hint styles through `window.item_css`. Base QSS styles the
QuickList class and panel QToolButton/QPushButton/QComboBox children. Plug-ins may
provide Theme.css through the normal loader; no host stylesheet edits or
Favorites-specific selectors are needed.

Use `fuzzy=False` (default) for a list without a text filter; `matcher=` optionally
supplies a matcher receiving casefolded strings and returning matched character
offsets (or None). The view maps offsets back to the original text. Set `preserve_sort`
to keep caller ordering during filtering. Stable `ListItem.id` values preserve
selection across refreshed data. `current_item` is one ListItem or None;
`selected_items` includes hidden selections in input order. `state_changed`,
`activated` and `delete_requested` signals let the plug-in implement actions.
No list signal writes configuration or invokes file operations automatically.

IconButton is always checkable and binds boolean values. TextButton normally emits
clicked for operations; `checkable=True` also supports a boolean setting. DropDown
accepts unique scalar JSON values paired with display labels. Each control exposes
value/set_value/value_changed. Bind keys/defaults before calling settings.load().
Settings names must be plug-in-specific JSON basenames, not filesystem paths.
The normal fman settings precedence and UserSettings persistence apply.

JsonSettings.changed carries the committed JSON object, failed carries an error,
and busy_changed indicates background work. Bound controls are disabled during
load/save; invalid stored control values use their defaults without rewriting
the file. Failed saves restore committed values. Unbound operation buttons do not
write JSON. Separate instances bound to the same filename share commits. Reload-
latest saves preserve unrelated keys. Parent destruction or dispose() detaches
the binding; passing the loader-bound UiController.owner also cancels on unload.
UiOwner can be used for manually managed lifetimes. Bindings do not watch external
file edits; call load() explicitly to reload. After a load failure, report it and
offer a retry via load(). No full JSON file is rewritten merely by showing a view.

### Ownership and Existing Integration

Current [Quicksearch](../src/main/python/fman/impl/quicksearch.py) is a modal
picker: click accepts and query changes rebuild its list. Reuse appropriate
delegates/theme helpers, not that selection lifecycle. Leave
`fman.show_quicksearch` unchanged.

QuickSearch's built-in fuzzy item matching is the navigation contract for the
new composition, not a reason to re-filter legacy callback-supplied results.
Reuse the repository's existing fuzzy-matching implementation after checking its
ranking/highlight contract; do not introduce a second matching algorithm. Keep
legacy providers' ordering, callbacks and return values unchanged.

Current [public UI helpers](../src/main/python/fman/__init__.py) dispatch through
the [main window](../src/main/python/fman/impl/widgets.py). `submit_task` executes
its task synchronously; it is not a background scheduler. The existing
[thread dispatcher](../src/main/python/fman/impl/util/qt/thread.py) can wait for
the Qt thread. Do not call it while holding worker/model locks or treat it as a
nonblocking queue.

Proposed ownership boundaries:

- `src/main/python/fman/impl/ui/`: shared descriptors/controls, session handles,
  QuickList, tree model, window panel and text preview. Split by responsibility
  only as the Phase A consumers need it, not into a general widget framework.
- Interaction Panel owns shared checkbox/choice/text descriptors and rendering.
  QuickSearch and QuickList expose navigation/current/selection state only;
  the composing session connects that state to the panel's operation controller.
- Existing main-window widgets own the window panel, modeless tool windows,
  focus and Qt-thread creation/destruction. Theme code owns their theme roles.
- Plug-ins own domain validation, I/O and destructive-operation policy. Panel
  settings persist through JsonSettings; domain data remains consumer-owned.
  Favorites uses exported fman.ui services only; internal host imports are not
  allowed in a consumer adapter. Widgets/models remain on Qt. The search
  adapter may own a Qt-thread QProcess without taking ownership of result widgets.

Use the exported `UiController` base class for modeless tools. Extend
[ExternalPlugin._load_classes](../src/main/python/fman/impl/plugins/plugin.py)
using its existing module-class/MRO scanning and paired register/unregister
actions, as used for commands, listeners, filesystems and columns. Registration
binds the tool ID to the loader's owner and load-generation; never infer it from
the stack or accept an arbitrary owner string. Unload invalidates sessions before
removing their code. Simple blocking pickers obtain the same owner binding from
the command registry/invocation and need no custom controller subclass.

### Deferred Consumer Contracts

The widget-component API above is the implemented public contract. The APIs below
are future consumer proposals, not additional Favorites requirements. The separate
Extended Quicksearch UI plan retains its narrower descriptor model; it does not
replace or restrict public QuickList/panel widgets.

Proposed `open_tool(tool_id, target, content) -> UiSession` and `open_quicklist`
return immediately after short Qt dispatch. Target is an invoking pane's window
or an application-command window; Phase A does not replace pane content. These
surfaces are modeless, not long-running `MainWindow.exec_dialog` calls.

`run_quicklist(...) -> QuickListResult | None` opens the same modeless picker but
waits on the command worker until it closes. It never blocks Qt or pumps a nested
event loop; calling it from Qt raises a clear error. The result captures action
ID from the separate bottom panel, current ID and selected IDs;
close/cancel/unload releases the waiter exactly
once, returning None for cancellation. Command cancellation closes the session.
Favorites uses a persistent modeless controller: capture the action, confirm/apply
under the shared transaction boundary, then publish a new immutable snapshot.
Query, sort and surviving current/selection identities remain in the same window.
Recent/Name/Path replace Move Up/Move Down; see Favorites002 for the current contract.
Streaming search uses UiController events instead.

Author threading: ordinary command bodies run on command worker threads; toolkit
event handlers and Qt-producer callbacks run on Qt; operation callables run on
the lazy executor. Event handlers stay short and dispatch I/O to an operation.
Only the designated Qt-producer adapter may operate its QProcess on Qt; workers
receive copied immutable data and never access QObjects or synchronously wait
for Qt. The blocking picker is for command workers, never event handlers.

Use immutable records with stable IDs and typed values. Validate the fields the
consumers actually use: duplicate IDs, choice defaults, numeric ranges, parents,
span bounds and payload limits. No versioned generic spec/expression language.
Phase A controls are labels, text/search and history inputs, checkboxes, choices,
bounded numeric input (search context count), actions, and progress/status.
These controls belong to the bottom Interaction Panel, not the list views.
Every control has an accessible label; icon actions have theme icons/tooltips.
Values reference IDs, not translated labels. Programmatic updates do not echo
user-change events. Closed handles reject updates deterministically.

Session updates cover controls, result batches, current/selected IDs, text preview
and progress. Events cover value/current/selection changes, activation, actions,
operation completion and closure. They carry copied IDs/values plus owner,
session and operation generations, never Qt indexes. Bottom-panel batch actions
capture the selected set; current-item actions capture the current ID explicitly,
independently of selection. No per-row action widgets are added to QuickList.
Admission distinguishes accepted, retry/full, limited, stale and closed; errors
are reported once through the plug-in handler with busy state restored.

### QuickList Selection Contract

- Up/Down and Page Up/Down in the filter transfer focus to the list before
  navigation. Subsequent Space toggles the current row; deliberately refocusing
  the filter restores ordinary text editing. Right-click toggles only the clicked
  row without activation or clearing other selections; empty-space right-click
  leaves selection intact. These synchronous input changes add no background work.
- Filtering remains opt-in: QuickList() and QuickList(fuzzy=False) without a
  custom matcher hide the filter, focus the list and display all supplied items.
  fuzzy=True or matcher= enables filtering; a supplied matcher intentionally
  enables the filter even when fuzzy is left at its default False.

- Optional fuzzy filtering is a view capability selected by the caller. When
  enabled, show a navigation query and use the shared fuzzy matcher over supplied
  item labels; when disabled, omit the filter and its matching work. It never
  scans files or changes operation parameters. Empty query restores source order;
  nonempty query ranks matches with stable source-order ties and match highlights.
- Fuzzy filtering preserves selected IDs, including hidden items. Show both total
  selected and hidden-selected counts; clearing the query restores the full list.
  If the current item becomes hidden, move current to the first visible match or
  none without changing selection. Reject stale asynchronous filter results by
  query and dataset revision. Filter changes do not start a new domain operation.
- Click and plain arrows move current without changing selection. Ctrl+click
  toggles a row; Shift+click toggles the visible range. Shift+Up/Down toggles then
  moves, matching the file pane. Shift+Home/End/Page toggles the traversed range.
- Current row drives preview, independently of the selected set. Space toggles
  current selection when the list owns focus. Input typing stays in the input.
- Enter/double-click emits activation of the current item. The controller decides
  whether to navigate/close. Activation is never silently a destructive action.
- Bottom-panel actions operate on captured selected IDs. A destructive action is disabled
  with zero selection; no implicit fallback to current unless explicitly specified
  and visibly explained for that action.
- Keep selection across sorting/filtering by stable IDs, not row positions.
  Ctrl+A selects visible rows. Show total selected and hidden-selected counts;
  Clear Selection clears all, including hidden selections. Batch actions include
  hidden selected items only when the action scope and confirmation say so.
- Data removal prunes selection and emits one selection-change event per batch.
  Stable IDs must not be reused for different objects within a session. Query
  changes that replace the domain dataset start a generation and clear selection;
  filtering an unchanged dataset does not.
- Use a themed selection background and separate current/focus outline, including
  inactive selection. Selection must remain understandable without color alone.

Bookmark example: select multiple records, choose `Remove Bookmarks` in the
bottom panel alongside Move Up/Move Down, confirm
captured names/count including hidden selection, then let the feature update its
store. Remove successful records only; retain failed records and report failures.
Never label this operation Delete Files. Escape cancels without applying an action.

Reorder is available only in the unfiltered stored-order view, never a sorted or
filtered projection. Move Up/Down shifts selected contiguous blocks one position
while preserving their internal order; boundary blocks stay put. Use the existing
Favorites identity and transaction lock, not array positions captured before a
dialog. Reject a stale order snapshot without overwriting concurrent changes and
refresh. Keep new/re-added entries moving to the top and rename/remove preserving
relative order. No settings I/O or dialogs while holding a UI/model lock.

### Bounded List Confirmation

Provide a shared confirmation with action/destination labels, exact target count,
the first K names, omitted count and explicit Confirm/Cancel (Cancel default).
Bound each label as well as the preview list. The immutable action snapshot stays
with the caller; truncation of displayed names must never truncate its targets.
The response authorizes only that snapshot, not whatever is selected afterward.
The feature revalidates identities and permissions at execution. No target I/O in
the renderer and no default destructive Enter action. Confirmations may use the
existing short modal-dialog pattern; they are not streaming workspaces.

### Results And Preview Composition

Phase A uses QListView for QuickList and QTreeView for search file/match results,
with stable IDs, parent IDs, display text and highlight spans. Models validate
and apply immutable batches on Qt; no QWidget per row or plug-in I/O in display,
sorting or filtering. A splitter joins the tree to a read-only text PreviewHost.
Comparison tables, paired previews and synchronized scrolling belong to Phase B.

Initial TextPreview accepts bounded decoded text, source identity/revision, line
labels, truncation state, and highlight spans. Public spans use Python Unicode
code-point offsets with explicit line boundaries; the renderer translates to Qt
UTF-16 positions. Byte offsets from ripgrep or a diff engine must be converted by
the producer, never passed straight to Qt. Test non-BMP characters and combining
characters. Show search excerpts as excerpts, not as an authoritative full file.

Phase A has no provider registry or decoder discovery. Search supplies already
decoded, bounded excerpts; changing the current result invalidates old previews.
PreviewHost has no write API. Provider registration, capability controls, media
resource disposal and untrusted-file policies must be designed and tested with
the actual Phase C decoders, not fake editor/media contracts in Phase A.

### Bottom Panels And Placement

The Interaction Panel is a compact Sublime Text-style bottom control strip,
separate from the status bar and the view element. It holds operation inputs,
checkboxes/toggles, choices and actions; the view above stays a navigator.
For example, content-search regex/case/scope settings configure the operation,
not QuickSearch's or QuickList's fuzzy item matching.

A picker tool docks operation controls in the main-window slot immediately above
the status bar; plain navigation can omit the panel. The session captures view
state on action invocation, so moving focus to the dock does not change targets.
The paired QuickList remains a modeless tool window; close either surface to end
the session. Search tree/preview integration remains subject to its own plan.
No pane-local slots, pseudo directories or pane content replacement in Phase A.

Opening an existing tool focuses it. A different tool closes the occupied docked
session before claiming the slot. No dirty-close veto is part of this subset.
Escape affects the active session only. Directory shortcuts must not
execute against an unrelated pane when a tool owns focus; visible panes remain
usable. Multiple windows have independent slots. No editor dirty-close policy
is introduced before a merger consumer exists.

Use theme roles for backgrounds, text, borders, selection, focus, matches,
warnings, errors and diff changes. No plug-in hard-coded palettes or stylesheet
injection. Reflow controls into additional rows at narrow widths, keep result
columns resizable, and respect system DPI, fonts and high-contrast needs. Provide
tooltips for icon controls and accessible names for every input/action.

### Operations, Cancellation and Bounds

Provide an operation handle distinct from synchronous `submit_task`, with two
producer adapters using the same immutable batch and generation checks:

- Worker producer: a lazy bounded executor receives immutable input. Publication
  may wait for bounded capacity only with cancellable backpressure, never for a
  synchronous Qt callback. Global worker and pending-operation limits are fixed
  host settings, selected and measured in the Phase A implementation.
- Qt-thread producer: QProcess readyRead may publish directly through a
  nonblocking `try_publish`. No extra worker/thread/lock is required merely to
  transport search results. On full capacity, do not wait or repeatedly retry
  within the callback. The search adapter retains at most one bounded batch;
  if it cannot bound its own/QProcess buffers, cancel the producer and report
  Limited explicitly. Simply ignoring readyRead does not bound QProcess memory.
  The search-plan revision must specify capped incremental reads, JSON-record
  size, callback work budget and overflow termination/draining. Expensive parsing
  may move to a worker only if measurements require it; QProcess stays on Qt.

One active data-producing operation per session; replacing a query cancels the
old generation and coalesces pending work. Every update checks owner load-generation,
session, operation and dataset revision. Progress coalesces. Canceled/limited
operations retain labeled partial results, never report successful completeness.
No Qt callback waits for a worker or process exit. Feature subprocess adapters
own asynchronous terminate/kill/cleanup; no shell launch.

Initial Phase A limits (proposals to verify, not measurements):

| Limit | Default | Motivating Consumer |
| --- | --- | --- |
| Retained result rows, including tree parents | 10,000 | Content-search file/match tree |
| Retained decoded result text, UTF-8 byte accounting | 16 MiB | Search excerpts across matches |
| One text preview | 1 MiB | Selected search excerpt |
| Queued payload per session | 4 MiB | Worker/Qt search producer saturation |
| Individual result record or control message | 64 KiB | Long match lines; reject oversized records |
| Qt batch-drain time per turn | 8 ms | Search streaming while panes remain usable |
| Confirmation names shown / characters per label | 20 / 256 | Favorites and future multi-item actions |

Also bound queue message count and active sessions in implementation, so empty
messages or many windows cannot bypass byte accounting. Keep consumer-specific
Favorites caps. Account for Python/Qt overhead and process buffers separately in
benchmarks. Show Limited/Truncated; reject oversized messages before admission.
Drain only while pending, rescheduling within the time budget; no idle flush timer.

Lifecycle: open -> idle/running -> closing -> closed. Close invalidates generations,
cancels operations and releases blocking-picker waiters before disposing Qt
content. Disconnect subscriptions; late results are discarded and resources
released without calling unloaded code. Workers require bounded/cancellable I/O;
Python threads cannot be killed. Non-cooperative libraries need a separate
process design. Release idle feature workers after cancellation finishes.

### Destructive Operations and Persistence

Phase A actions declare destructive/busy state. Disable repeat submissions while
busy and confirm captured identities, not row positions. Favorites writes stay
inside its existing transaction policy; cancellation never implies removal.
Search and hash-picker previews authorize no writes. Editor save/discard and
folder synchronization policies belong to their later consumer plans.

The host stores no document content, search results or queries by default.
Features opt into settings/history using existing JSON APIs under UserSettings.
Namespaced host geometry preferences may store split ratios and expanded controls
on close, not on every resize. No Registry writes or automatic session reopening
of a plug-in operation. Sensitive previews must not be written to diagnostic logs.

### Relationship to Existing Plans

- [Extended Quicksearch UI](ExtendedQuicksearchUI.md) conflicts with the user's
  clarified component split: embedding checkbox/choice controls in Quicksearch
  is superseded, not Phase A's first deliverable. Revise that plan separately to
  put SearchFileFuzzy operation options in the bottom Interaction Panel before
  implementing it. Do not change existing Quicksearch behavior or add its
  proposed extended API as a prerequisite for this toolkit.
- [Search File Content](../Done/SearchFileContent.md) is a consumer, not the owner of
  shared UI. Before integration, revise and review that task to replace the modal
  exec_dialog flow with the window panel/modeless tree-preview session, keep
  internal toolkit/PyQt imports confined to its adapter, and specify bounded
  Qt-thread QProcess production instead of an assumed worker-only transport.
  Replace its fixed 50 ms batching design with budgeted pending-only drains and
  settle parser/process-buffer overflow, cancellation and file-navigation behavior
  there. Correct its mandatory full-suite command to focused validation. This
  revision is a blocking Phase A gate; it is not performed implicitly here.
- [Favorites](../Done/Favorites001.md) provides the first real selectable-list use
  case; add multi-remove/reorder management using its existing store and lock,
  keeping navigation commands, current-path removal and shortcuts compatible.
- [Process Pane](ProcessPane.md) can continue using the virtual filesystem/table;
  these components are optional tools, not a mandatory rewrite of every plug-in.
- Hash, archive and process plans adopt the confirmation/action helpers only
  when individually revised; their feature implementation is not added to Phase A.

## Alternatives

- Add many mode flags to Quicksearch: rejected; picker acceptance and multi-select
  management have materially different lifecycle/selection contracts.
- Embed operation controls in QuickSearch or QuickList: rejected by the user's
  clarified design. Share bottom-panel controls across operations while keeping
  both list views focused on navigation and choice.
- Public versioned fman.ui now: rejected; the customers are bundled plug-ins.
  Internal adapters provide reuse without promising speculative external APIs.
- Give each consumer its own widgets and private main-window access: rejected;
  centralized ownership still matters even though the shared toolkit is internal.
- Build a web UI/HTML form engine: unnecessary runtime and security complexity
  for a desktop Qt application with suitable native widgets.
- Implement each feature's private dialog independently: duplicates selection,
  cancellation, previews, styling and error handling across the named consumers.
- A full docking/workbench framework now: unnecessary; one window panel and
  modeless tools cover Phase A. Pane replacement waits for an approved consumer.
- Worker-only production: rejected; QProcess already emits on Qt. Support a
  bounded nonblocking Qt adapter without forcing transport through another thread.
- Callback-only simple pickers: rejected; a blocking command-thread wrapper
  matches existing plug-in commands without blocking the GUI.
- Implement all viewers and comparison engines inside this task: rejected to
  keep infrastructure independently verifiable and limit dependency/behavior risk.

## Runtime Effects

- Startup/disabled: only component imports and controller registration;
  no widget creation, decoder imports, worker, disk scan, process, or timer until
  invocation. Loading ordinary file panes remains unchanged.
- Active UI: O(N) retained model records within explicit limits; selection uses
  stable-ID sets. Filtering is model-side, not repeated file I/O. Large sorts or
  filters must be measured and moved to immutable worker snapshots if they exceed
  the UI time budget without accessing Qt models from workers.
- Fuzzy filtering uses supplied labels only, with bounded retained match data;
  no feature I/O. Measure nonempty-query ranking at the result cap. When optional
  QuickList filtering is disabled, create no filter index, worker or timer.
- Work: bounded concurrent workers and queued bytes, batched Qt updates, and
  generation-based rejection. No per-row widgets or per-keystroke full UI rebuild.
- Hidden/closed: hidden search may continue only as visibly indicated running
  work within its bounds; no new text preview is produced while hidden. Closing
  cancels work, releases handles and picker waiters, and disconnects signals.
  There are no media decoders or playback lifecycles in Phase A.
- I/O/persistence: feature-controlled file reads/writes only on invocation;
  optional namespaced geometry/settings under UserSettings. No network or shell
  launch from the base UI infrastructure.
- Record cold opening cost, streaming latency, peak RSS, Qt responsiveness and
  cancellation/disposal time during implementation. Targets below are not claimed
  measurements. Do not optimize by weakening selection or stale-result checks.

## Tests

Phase A tests use existing unittest and Qt helpers:
`fman_unittest.test_ui_elements` and `fman_integrationtest.test_ui_elements`.
These are proposed modules, not files currently implemented.

Unit tests:

- Bottom-panel checkbox/choice defaults and IDs, tree parents, typed updates without
  event echo, action snapshots, per-item targets and bounded confirmation labels.
- Selection/current separation, Ctrl/Shift behavior, hidden selection, clear-all,
  data pruning, captured action targets, and generation resets.
- Optional fuzzy filtering on/off, ranking and stable ties, Unicode highlights,
  empty/no-match queries, hidden selections, clear-query restoration, current-row
  fallback without selection loss, and stale query/dataset result rejection.
- Favorites remove/reorder including filtered/sorted-view rejection, boundary
  blocks, partial failure and stale/concurrent store updates.
- Lifecycle, cancellation, closed-session rejection, worker backpressure and
  Qt try_publish/full behavior; oversized/stale batches and error reporting.
- Text offset translation for UTF-8-derived matches, non-BMP characters, combining
  marks, newlines and truncated excerpts; no accidental byte/code-point confusion.

Qt integration and compatibility tests:

- Click selects without closing; activation emits an event and closes only if
  the consumer requests it. Test current/selection across sort/filter/insertion.
- Legacy `show_quicksearch` callbacks, return values, click/Enter/Escape, and
  Ctrl+P/Ctrl+Shift+P behavior remain unchanged.
- QuickSearch and QuickList contain no operation controls or row action buttons;
  their separate bottom panel keeps captured targets when focus leaves the list.
  QuickSearch chooses one item; QuickList filters/selects many without closing.
  Existing SearchFileFuzzy callbacks, persistence and acceptance stay unchanged.
- Favorites command loop and hash action fixture need no custom callbacks;
  run_quicklist keeps Qt responsive, rejects Qt-thread invocation and releases
  its waiter on acceptance, cancellation and unload. Confirmation Cancel is safe.
- Controller scan/registration, ownership and unload; creation/model mutation/
  disposal thread affinity; worker and real QProcess producer saturation and
  asynchronous cancellation; no callbacks into unloaded code.
- Window panel plus tree/text tool: two-window isolation, slot replacement,
  Escape/focus, blocked unrelated directory shortcuts and close-either behavior.
  Search integration must pass against its revised plan, not only synthetic data.
- Loading/error/empty/limited/partial states; Unicode preview bounds; no stale
  query results. Theme propagation across the actual Phase A surfaces.

Performance and manual checks:

- Stream synthetic 10,000-row lists and file/match trees, including oversized
  text, with producer saturation. Assert configured row/byte/queue bounds and
  prompt cancellation while the queue is full for both producer adapters. Include
  QProcess/adapter buffer accounting; count zero idle production/drain callbacks.
- Under that load, measure Qt heartbeat gaps (target p95 below 50 ms) and
  selection-to-placeholder feedback (target below 100 ms). Use an event-loop
  heartbeat only in the benchmark, not as a production idle timer.
- Close/reopen 100 times; verify stable worker/handle/subscription counts and no
  retained sessions. Record RSS variation rather than asserting allocator memory
  returns to an exact baseline. Synthetic cooperative work stops within 250 ms.
- Check both application themes, keyboard-only operation, accessible labels,
  narrow windows and 100/150/200% DPI. Controls must not overlap or obscure content.
- Source and frozen Windows smoke of reference plug-ins, no development-only
  imports, and ordinary pane/Quicksearch behavior with no new tools open.

Proposed focused commands from the repository root once tests exist:

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_ui_elements
python -m unittest fman_integrationtest.test_ui_elements
python build.py freeze
git diff --check
```

Run the smallest relevant new test immediately after the first implementation
edit. Add existing focused test modules for every shared subsystem actually
changed; record their exact commands at implementation time. Remove the offscreen
setting for interactive `python build.py run` smoke. Do not run the full
`python build.py test` suite unless explicitly requested. Design-only validation:
required section/link checks and `git diff --check`; runtime gates remain pending.

Later-phase tests are added with their approved plans: Phase B table filtering,
paired navigation and staged targets; Phase C actual decoder lifecycle, editor
save/close and optional pane-replacement command routing. None is a Phase A gate.

## Implementation Steps

### Phase A: Existing Consumers

1. Establish the navigation/operation boundary: QuickSearch single-choice fuzzy
  navigation, QuickList multi-selection with optional shared fuzzy filtering,
  and separate bottom-panel control descriptors/renderer. Verify legacy
  Quicksearch compatibility; no checkbox-enabled extended picker API.
2. Implement QuickList with owned sessions, bottom-panel current/selected-item
  actions, blocking run_quicklist and bounded confirmation. Integrate Favorites
  through its persistent controller and the hash-action fixture; prove store
  concurrency and cancellation. The approved Favorites-first subset does not
  require the unused blocking convenience or hash fixture to ship first.
3. Revise and review Search File Content's own plan for modeless placement,
  internal imports, bounded Qt QProcess production and focused tests. Do not
  begin its integration while those conflicts remain unresolved.
4. Implement the window panel, tree/read-only preview and operation handle with
  both producers against that revised consumer. Prove saturation, limits, stale
  rejection and unload with synthetic data, then the actual search integration
  in its own task. No comparison tables, editors, media or pane replacement.
5. Run Phase A focused tests, measured bounds/latency and source/frozen smoke.
  Document internal adapters and user-facing management/search workflows in the
  corresponding implementation tasks. Changelog entries describe shipped
  application changes only, not this plan revision.

### Phase B: Folder Diff

Requires an approved Folder Diff plan. Add comparison tables/status filters,
staged operation lists and side-by-side read-only previews against that consumer,
with its identity, synchronization and UI tests. No speculative Phase A contracts.

### Phase C: QuickLook and Merger

Requires approved QuickLook/Merger plans and decoder/editor decisions. Add only
the provider controls, media lifecycle or editor surface each consumer requires.
Pane-local panels and content replacement require additional consumer review of
focus, commands and restoration. Re-review shared contracts before promotion;
a public facade requires two shipped consumers of each promoted contract.

## Acceptance Criteria

Phase A completion conditions:

- QuickSearch provides single-item fuzzy navigation and QuickList provides
  multi-selection with optional fuzzy filtering. Legacy fman API behavior remains
  compatible; the implemented three-component surface is importable from fman.ui.
- Neither list embeds operation controls or selection checkboxes. Operation
  settings and current/selected-item actions reside in the separate themed bottom
  panel, without changing the view implementation or losing selection on focus.
- Fuzzy filtering preserves hidden selections and reports both selection counts;
  clearing the query restores source order. Disabled filtering performs no
  filter-specific work, and stale matches never replace current-query results.
- QuickList supports predictable multi-selection, hidden-selection accounting,
  independent preview current-row, and explicit actions without click-to-close.
- Favorites management follows Favorites002's persistent session, stable
  identities, Recent/Name/Path projection and tracked navigation contract.
- Bounded confirmation and hash per-item actions capture exact targets; canceled
  or truncated display never changes the authorized target set.
- Search File Content's revised plan is reviewed and its modeless window panel,
  tree/text integration passes; synthetic demos alone are not sufficient.
- Worker and Qt producers pass bounds/cancellation/unload tests without blocking
  Qt. Picker waiters are released and unrelated pane shortcuts cannot leak.
- Existing fman plug-ins, directory panes and Quicksearch retain their contracts;
  disabled/unused infrastructure adds no feature-specific background work.
- Phase A focused tests, performance reports, theme/DPI checks, source/frozen
  smoke and internal consumer documentation are complete before implementation
  is marked done. Phase B/C remain separate, approval-gated future work.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Designed reusable plug-in UI contracts around QuickList, interaction
  panels and result/preview hosts for the user's named consumers. Grounded in
  current public helpers, modal Quicksearch and synchronous task/Qt dispatch.
  API naming and consumer overlap require review before implementation. No host
  model identifier was exposed; the assigned signing convention is used.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Expanded the motivating-consumer table into explicit task workflows
  for text diff/merge, multi-format QuickLook, content search and hash-table folder
  comparison, plus bookmark management. Added per-task UI requirements and
  correctness scenarios, including editable-document and media-control contracts
  not supplied by a read-only preview. Actual feature engines remain separate.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Not approved in its current scope. The individual contracts
  (stable-ID selection, generation-based stale rejection, bounded transport,
  Qt-thread ownership) are sound, but the document specifies a five-subsystem
  framework ahead of any consumer, including contracts (editable documents,
  media controls, pane content replacement) whose consumers have no approved
  plan. Judged against the tasks it should serve, roughly half of the surface
  is needed by the two consumers that exist today. Reduce to the slice below,
  implement it against those two consumers, and re-review before adding the
  rest.

#### Follow Up Tasks

Strategic (decide before implementing):

- [ ] **Who is the customer of `fman.ui`?** Every named consumer is a bundled
      plug-in in this repository; there is no third-party plug-in ecosystem for
      RoyiFileManager, and `SearchFileContent` already accepts importing PyQt5
      inside one module. A *public, versioned* API (`fman.ui`, spec v1,
      compatibility guarantees, "minimum RoyiFileManager release" declarations)
      is the most expensive shape this work can take. Recommend an internal
      shared toolkit under `fman.impl.ui` used by bundled plug-ins, with a thin
      public facade promoted only when a contract has two shipped consumers.
      This removes the spec-versioning, descriptor-validation-of-everything and
      "do not advertise as stable" clauses and roughly halves the test matrix.
- [ ] **Slice by consumer, not by subsystem.** Phase A must serve exactly the
      two consumers that have approved or shipped plans:
      *Favorites management* (multi-select remove/reorder) and
      *Search File Content*. That needs: shared checkbox/choice/text descriptors
      (see next item), a modeless QuickList with multi-selection and actions,
      one window-level bottom panel, a results tree with a read-only text
      preview, and an operation handle. Everything else moves to later phases
      gated on its consumer's plan being approved: comparison table and filters
      (Folder Diff), editable-document capability (Merger), provider controls
      and media semantics (QuickLook), pane-local panels and pane content
      replacement (QuickLook-in-pane).
- [ ] **Make Extended Quicksearch UI the first deliverable of this work, not a
      plan to "align with".** Its checkbox/choice descriptors are approved and
      are a strict subset of the controls listed here. Implement them once as
      the descriptor module both dialogs use; that resolves the overlap the
      document defers and gives the descriptor validation a real consumer on
      day one.

Fit against each task to support:

- [ ] **Favorites management** — good pilot, but small. Note that the shipped
      Favorites plan rejected reordering because the JSON cache is not
      externally observable; a QuickList with `Move Up`/`Move Down` actions
      resolves that rejection and is a more convincing pilot than multi-remove
      alone. Add it to the pilot scope.
- [ ] **Search File Content** — strongest fit, but the approved plan conflicts
      with this one in three places that must be settled in *that* plan's
      revision, not here: it runs `QProcess` on the Qt thread with 50 ms
      batching (this plan assumes thread workers and a publish channel), it
      uses a modal dialog via `exec_dialog` (this plan is modeless), and it
      imports PyQt5 directly. The operation handle here must admit a
      **Qt-thread producer** (QProcess `readyRead` → batches) as a first-class
      case, not only thread workers; otherwise ripgrep streaming would be
      forced through an unnecessary thread and a lock.
- [ ] **Text diff/merger** — the "editable document capability with revisions,
      undo/redo, dirty state, save requests" is a text editor contract defined
      with no implementation and no approved consumer. Remove it from this
      document; state only that `PreviewHost` is read-only and that the merger
      task will add an editor surface when it is planned. The current text
      commits to an API shape before the diff engine's needs are known.
- [ ] **QuickLook** — the expensive parts are the decoders and their packaging
      (PyQt5 has no `QtPdf`; `QtMultimedia` video on Windows is unreliable;
      Markdown needs `QTextDocument.setMarkdown`, which exists in Qt 5.14+ and
      is fine). The UI shell is small by comparison. Defining
      zoom/rotate/seek/volume controls now, before a decoder set is chosen, is
      speculative. Keep only: "a provider declares which of a fixed set of
      controls it supports; the host shows those". Also drop *inactive-pane*
      placement from v1: a modeless tool window is what Windows and macOS
      QuickLook do, and pane replacement is the single riskiest item in the
      document (focus routing, command fall-through, session persistence).
- [ ] **Folder diff** — fits a `QTableView` results surface with status
      filters; nothing here is wrong, but it is the least urgent consumer.
      Move the table surface and the "staged operation list" to Phase B.

Tasks the document should serve but does not mention:

- [ ] **Bounded list confirmation.** Favorites remove, Process Pane terminate,
      Unpack Archive conflicts and Calculate File Hash all need "confirm this
      action on these N items (showing the first K)". A tiny reusable element
      here removes four ad-hoc `show_alert` string builders. Add to Phase A.
- [ ] **Result-with-actions picker.** Calculate File Hash uses Quicksearch as
      an action menu (copy / copy labeled / compare). A QuickList item with
      per-item actions serves it directly; note it as a Phase A consumer.

Design details to fix regardless of phasing:

- [ ] **Synchronous convenience for simple pickers.** Plug-in commands run on
      worker threads and every existing UI helper blocks until the dialog
      closes. `open_tool` returning immediately with Qt-thread callbacks is a
      new programming model for plug-in authors. Provide
      `run_quicklist(...) -> result` that blocks the command thread until the
      session closes (mirroring `show_quicksearch`), and reserve the
      callback/session model for streaming tools. The Favorites pilot should
      not need callbacks.
- [ ] **Threading statement for authors.** State in one paragraph where plug-in
      code runs: command body on a worker thread; event handlers on the Qt
      thread; operation callables on the executor; nothing else. The current
      text says this implicitly across several sections.
- [ ] **Loader ownership.** Registration by scanning module attributes for a
      new base class matches how `Plugin` registers commands, listeners,
      filesystems and columns; say so and name the base class, rather than
      describing "registered controller class" abstractly.
- [ ] **Limits table.** Move the proposed defaults (10 000 rows, 16 MiB text,
      1 MiB preview, 4 MiB queue, 8 ms drain) into one table with the
      consumer that motivates each, so they can be tuned per phase.
- [ ] **Tests section** lists ~40 categories for a design with no code. Trim
      to the Phase A surface and add the rest with their phases.

Proposed phases (replace Implementation Steps 1–8):

- Phase A (serves Favorites management, Search File Content, list
  confirmations, hash action picker): descriptors shared with Extended
  Quicksearch UI; modeless QuickList (multi-select, actions, per-item actions,
  `run_quicklist` blocking form); window-level bottom panel; results tree +
  read-only text preview with code-point spans; operation handle with thread
  and Qt-thread producers, generations, bounded queue; bounded list
  confirmation. Migrate Favorites remove/reorder and revise the Search File
  Content plan onto it.
- Phase B (Folder Diff plan approved): table results, status filters, staged
  operation list, side-by-side previews.
- Phase C (QuickLook / Merger plans approved): provider capability controls,
  media lifecycle, editor surface, pane-local panel and pane content
  replacement — each only with its consumer.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Addressed all 15 Fable 5.1 findings in the design with a consumer-led
  Phase A and approval-gated later phases. The original review is preserved above;
  the resolution checklist below supersedes its open design items, not its
  historical approval decision. No application code was implemented or validated.
  Search File Content's own plan revision remains a gate before integration;
  this response does not claim Fable's approval of the revised plan.

#### Fable 5.1 Review Resolution

Checked means the design decision is incorporated, not that implementation or
the dependent consumer task is complete.

- [x] Customer/API: internal `fman.impl.ui` for bundled consumers; no general
  public/versioned spec. A later facade requires two shipped consumers per
  promoted contract. The narrow Extended Quicksearch public API is preserved.
- [x] Consumer-led slice: Phase A is Quicksearch, Favorites and content-search
  infrastructure plus bounded confirmation/hash-action reuse; tables, editors,
  media and pane replacement are outside its implementation/acceptance gates.
- [x] Extended Quicksearch first: its shared descriptors/renderer and real
  SearchFileFuzzy use are the first verifiable deliverable.
- [x] Favorites reorder: explicit Move Up/Move Down, stored-order view only,
  stable block semantics and stale-order checks under the existing transaction.
- [x] Search integration: explicitly requires its own reviewed plan revision
  for modeless placement, internal imports and Qt QProcess production; Qt
  publication never blocks, and process-buffer overflow must terminate with a
  visible Limited result rather than grow memory or force transport to a worker.
- [x] Merger: removed the speculative editable-document contract. Read-only
  PreviewHost stays read-only; editor design belongs to the merger plan.
- [x] QuickLook: deferred controls until decoder choice; capability declaration
  is the only retained direction. Initial tool-window placement, packaging
  review and separately gated pane replacement are explicit.
- [x] Folder Diff: tables, filters, staged actions and paired previews move to
  Phase B, conditional on its approved consumer plan.
- [x] Bounded confirmation: captured targets, bounded displayed names and exact
  count, omitted count, safe default and feature-owned revalidation.
- [x] Hash action picker: per-item Copy/Copy Labeled/Compare fixture in Phase A;
  no hash engine implementation or implicit migration of its plan.
- [x] Blocking convenience: run_quicklist waits only on command workers; the
  modeless GUI remains responsive. Favorites uses an action/reopen loop without
  plug-in callbacks; cancel/unload releases its waiter.
- [x] Author threading: command worker, Qt event/producer callbacks and executor
  callables are stated together, with no worker access to QObjects.
- [x] Loader ownership: internal UiController follows ExternalPlugin's existing
  class/MRO registration and paired unload pattern, with loader-owned identity.
- [x] Limits: a single Phase A table ties row/text/preview/queue/drain defaults
  to consumers, plus record/confirmation limits and explicit buffer accounting.
- [x] Tests: Phase A tests cover actual controls/pickers/search producers and
  lifecycle; table/media/editor/pane tests are deferred with their consumers.

#### Design Validation

- PowerShell assertions checked all nine required task sections, Phase A entry
  points and phase gates, removed speculative-contract phrases, and local links.
- `git diff --check -- Plan/UIElements.md` passed after the design rewrite.
- Final checks cover all 15 resolution items and editor Markdown diagnostics.
- Runtime tests, benchmarks and packaging are not run for this design-only
  revision; the proposed implementation commands in Tests remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Incorporated the user's component split: QuickSearch is a single-item
  fuzzy navigator; QuickList is a multi-selection navigator with optional fuzzy
  filtering; operation controls/actions belong in a separate bottom Interaction
  Panel. Updated scope, ownership, tests and acceptance criteria. This supersedes
  the earlier Extended Quicksearch-first recommendation and inline item-action
  presentation, while preserving historical reviews. The separate Extended
  Quicksearch plan still requires revision; no application change is claimed.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: User approved implementing only the reusable components needed for
  Favorites002 now. Replaced active reorder/command-loop wording with the
  persistent manager contract; historical review records remain unchanged.
  Trees, previews, streaming producers, blocking picker convenience and hash
  fixture remain pending rather than blocking this initial subset.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the Favorites-required subset after Fable's implementation
  feedback. Neutral navigation ownership, bounded cancellation, host-owned pane
  integration and generic themed controls preserve the internal toolkit boundary.
  Broader Phase A and frozen acceptance remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Adopted the user's three-component boundary and Sublime Text panel
  reference. Expose only the implemented components via fman.ui, distinguish
  JSON-backed state from command buttons, and keep QuickList window-independent.
  File-pane Space/Insert/Shift/mouse semantics are testable requirements. Defer
  unrelated tree/preview/editor work and keep frozen validation pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Addressed the updated Qt-boundary review: keep general pane/window
  APIs free of Qt objects, retain the explicit Qt component layer, remove
  unshipped aliases, and make controller build canonical. Preserve the selected
  floating-list/docked-panel layout with focus-recovery coverage. Physical
  Alt+Tab and multi-monitor checks remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Aligned the hash consumer with the implemented public OutputTextBox
  and docked algorithm/Calculate Panel. Shared regressions and extracted-ZIP
  checks passed; broader UI Elements work remains pending. Implementation and
  validation provenance is recorded in the completed Calculate File Hash task.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Aligned the hash consumer with the user's command-specific layout:
  centered output only for Ctrl+H, docked controls only for By. Confirmed
  set_panel(None) should detach the owned panel without ending its window.
  Shared Qt regressions passed; broader UI Elements scope remains pending.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Aligned the roadmap with Search File Content as the first reusable
  Table consumer. Its canonical plan supersedes older tree/preview and table-
  deferral sketches; future rename preview reuses presentation without adding
  mutations. Documentation only; broader implementation remains pending.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Aligned exact Table argument names and made F1 migration/fuzzy search
  part of the consumer-driven increment. Search File Content remains the
  canonical contract and test plan; only openly licensed SVGs are permitted.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Aligned the shared roadmap with the content-search review resolution:
  owner-independent Table, explicit focus integration, nested Panel composition,
  additive IconButton action mode and scoped styling with file-pane regressions.
  Planning only; implementation and runtime checks remain pending.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Aligned the roadmap with the user's collect-then-display workflow:
  docked Panel, background search/status-bar progress, then modal results.
  Deferred progressive Table updates, modeless focus integration and F1
  migration; F1 remains an unchanged visual reference. The consumer plan owns
  proposed panel/status/modal hosting and lifecycle gates. Documentation only.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Aligned Table with the user's buttonless interaction constraint.
  Single-row selection, left-double-click activation and consumer-owned row
  context menus replace the results footer; the filter has no clear button.
  Detailed keyboard, payload and stale-menu checks remain in Search File
  Content. Search-panel controls, QuickList and F1 are unchanged. Planning only.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Aligned the roadmap with Qt-free Table/Panel services and plain
  handles/callbacks. Optional file/folder cell roles and default captured-base
  resolution replace row-wide file assumptions; host owns Copy Path / Go To,
  navigation, menus and window lifetime. Both modalities are required, with a
  modeless Panel-driven preview fixture and modal content search. Prior widget
  API examples remain legacy compatibility documentation, not the new contract;
  F1 and unrelated plug-ins stay unchanged. Detailed gates live in the canonical
  search plan. Design/document checks only; runtime behavior is not verified.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Aligned the roadmap with the resolution of Fable 5.1's latest review:
  internal TableWindow adapts to existing navigation, the new resource-root
  loader hook is explicit, and UiController without build remains the owner
  carrier. Deferred-presentation triggers and focused regression gates are
  owned by the canonical search plan. Retained approved modeless Panel reuse;
  no application code or runtime validation in this planning revision.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Adopted the user's main-window placement and close-session requirement.
  Selected one fixed dock above the status bar, public session-owned mounting and
  paired disposal; no file-model rewrite or general docking framework.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented main-window panel docking, native close affordance,
  keyboard traversal and session cleanup. Public demo and Favorites tests pass;
  native close/reopen/geometry checks pass at three DPI scales. See Docking Validation.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented the Favorites-required shared subset in fman.impl.ui:
  immutable records/Unicode matching offsets, QuickList, separate panel,
  nonblocking prompts, owner disposal, bounded worker submission, reload-stable
  resource notifications and internal navigation tracking. No public fman.ui API
  or unrelated tree/preview/search surface was added. The broader task is pending.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Applied shared dialog/host, resource lock, panel and delegate fixes.
  The focused combined offscreen run passed 185 tests; the final disposal-path
  rerun passed 15 manager tests. Native source/DPI smokes passed. Frozen and
  deferred component gates remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented fman.ui exports, standalone BottomPanel, IconButton,
  TextButton, DropDown and asynchronous JsonSettings; revised QuickList selection
  and presentation. Favorites is the real consumer. Focused source checks and
  native 100/150/200% smokes passed; delivery remains pending on existing gates.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Direction changed by the user: the goal is that an **external**
  plug-in can recreate Favorites using only exported components, so `fman.ui`
  is a public (provisional) API and exporting widget components is accepted.
  This supersedes this reviewer's earlier "keep it internal / descriptors
  only" recommendation. The Phase A export surface is therefore defined by
  what Favorites needs and does not yet have; that list lives in
  [Favorites002.md](../Done/Favorites002.md) under *Public API Gaps Blocking An
  External Favorites* and is summarised here so both documents agree.

#### Phase A Export Surface (Required)

Export from `fman.ui`, replacing the `fman.impl` imports Favorites still uses:

- [x] `settings_resource(filename)` / `Resource` (shared lock + revision +
      subscribe/publish) — currently `fman.impl.ui.resource`.
- [x] `PaneToolWindow` / `open_tool_window(pane, owner)` with the host
      providing parent, theme css and pane-destroyed notification through
      public accessors — currently `fman.impl.ui.session` reading
      `pane.window._widget`, `parent._theme`, `pane._widget`.
- [x] `navigate(pane, url, on_done)` tracked navigation with a terminal outcome
      — currently `fman.impl.navigation.NavigationRequest`; the thread-local
      `tracking()` stays internal.
- [x] `run_on_ui_thread` is **not** exported; commands run on worker threads
      and the host-owned `UiController.show()` does the hop — currently
      Favorites uses `fman.impl.util.qt.thread.run_in_main_thread` directly.
- [x] `matchers` (the Core quicksearch matcher set) — currently imported from
      the Core plug-in, which is not API.
- [x] `submit_work` with its saturation contract, or `ToolWindow.work` as the
      only documented path.
- [x] `UiController`/`UiOwner` documented as the loader-bound base, with a
      clear error when UI is created without a bound owner.
- [x] Host-owned construction: `UiController.show(pane, query='')` performs
      the Qt-thread dispatch, owner attachment, one-window-per-pane reuse and
      focus; the plug-in implements `build(window, pane)` and reaction hooks
      only. Replaces the need for plug-ins to know `run_in_main_thread`;
      constructor asserts remain as readable misuse errors.
- [x] Documented theme hooks: object/class names a theme styles and how a
      plug-in window inherits them (no per-plug-in rules in `styles.qss`).
- [x] Documented `ToolWindow.confirm/rename_prompt/alert` signatures.
- [x] `test_portable.py` lists every `fman.ui` name; CHANGELOG API line reads
      "preserves fman 1.7.5; adds the provisional `fman.ui` extension";
      `fman/ui.py` docstring states provisional status.
- [x] Mechanical exit test: no `fman.impl`, `from core`, `._widget`, `._theme`
      in `Plugins/Favorites/**`.

Design section updates to make:

- [x] Replace "No public Qt types" and "descriptors, not caller-created Qt
      widgets" in *Ownership and Existing Integration* and *Small Public
      Contract* with the widget-component model actually shipped, and state
      the compatibility promise for it (provisional; breaking changes listed
      in CHANGELOG with migration notes).
- [x] Keep the descriptor model for Extended Quicksearch UI (it is a
      different, narrower dialog) and say so explicitly, so the two APIs are
      not read as competing.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Removed public widget/signal bridges, added callback registration,
  removed public aliases, and migrated Favorites to controller construction with
  a plain domain session. Passed 117 focused tests and the native source smoke;
  physical Alt+Tab, second-monitor and existing packaging gates remain unverified.

## Validation Results

### Qt Boundary Review Validation

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_portable.PluginApiCompatibilityTest.test_general_api_does_not_expose_qt_host_bridges
python -X faulthandler -m unittest fman_integrationtest.test_qt.PublicUiIT fman_integrationtest.test_qt.FavoritesManagerIT fman_integrationtest.test_qt.DockedPanelIT
python -X faulthandler -m unittest fman_integrationtest.impl.plugins.test_favorites_plugin fman_unittest.test_favorites fman_unittest.test_ui_elements fman_unittest.test_portable fman_unittest.impl.test_theme fman_integrationtest.test_qt
$env:QT_QPA_PLATFORM = 'windows'
python -X faulthandler -m fman_integrationtest.favorites_smoke
git diff --check
```

- First boundary regression failed on the raw closed signal, then passed after
  replacing the bridges. Callback tests cover command-worker registration,
  no-argument delivery on the UI thread, cancellation, repeated unsubscribe and
  unsubscribe after destruction. Existing pane destruction/unload checks pass.
- Host/lifecycle set passed 29 tests after repairing a two-manager fixture: it
  had placed both managers in one real window while a mock hid dock replacement.
  It now uses separate real main windows, matching supported behavior.
- Final combined set: 117 passed, no skips. Includes public exports/alias absence,
  loader-first ordering, a plain FavoritesSession in the shared PaneToolWindow,
  QuickList input, panel settings, navigation, disposal and theme checks.
- Native source smoke passed: persistence, navigation, close/reopen, layout and
  label fit; partial-offscreen placement and activation/stacking focus recovery
  preserve selection and reach both list and dock via Tab/Shift+Tab. Filter/sort
  p95 for 200 rows: 5.20 ms. No visual layout change was introduced.
- Second monitor unavailable. Programmatic activation/stacking exercises the
  focus-recovery state, not physical Alt+Tab. Manual check: partially cover the
  tool behind the main window, switch away/back with Alt+Tab, then use dock
  Shift+Tab and list Tab; repeat with the tool on a second monitor. Both surfaces
  must regain focus and selection must remain unchanged. These checks stay pending.
- Python diagnostics and diff whitespace check pass; existing CRLF warnings are
  informational. Full build suite and frozen build/smoke were not run. Task
  completion remains pending; no additional background work or Registry use.

### QuickList Input Revision

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -X faulthandler -m unittest fman_integrationtest.test_qt.QuickListIT
python -X faulthandler -m unittest fman_integrationtest.test_qt
$env:QT_QPA_PLATFORM = 'windows'
python -X faulthandler -m unittest fman_integrationtest.test_qt.QuickListIT
```

Results: 9 QuickList tests passed offscreen and natively; the focused Qt module
passed 64 tests. New regressions verify arrow-to-list focus, subsequent Space
selection, refocused text editing, empty results, right-click toggle/untoggle,
preservation of other selections, empty-space no-op and no activation. Default
and explicit filter-disabled construction hide the filter, focus the list and
retain all rows; fuzzy-enabled filtering preserves hidden selections. Changed
Python diagnostics are clean. No full build suite or frozen checks were run;
existing broader delivery gates remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Selected focus transfer before forwarding navigation keys, preserving
  explicit filter editing. Right-click toggles a row, not activation; optional
  filtering remains unchanged. No public API or background-work changes.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Implemented shared QuickList focus transfer and right-click selection;
  added keyboard/mouse/optional-filter regressions. Passed 64 offscreen Qt tests
  and 9 native QuickList tests.

### Adaptive Panel Naming and Sizing

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Adopted Panel as the sole component name and Qt-layout-driven action
  sizing with a per-button cap. Rejected unbounded stretching and viewport-scaled
  text; preserved content minimums, compact icons and compatibility aliases.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Added Panel/set_panel naming and responsive TextButton widths with
  configurable 160-logical-pixel caps. Passed 111 focused tests and three native
  DPI runs with compact/medium/wide sizing and label-fit assertions.

Exact focused commands (using the PYTHONPATH setup in Docking Validation):

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -X faulthandler -m unittest fman_integrationtest.test_qt.PanelIT
python -X faulthandler -m unittest fman_integrationtest.test_qt.PanelIT fman_integrationtest.test_qt.DockedPanelIT fman_integrationtest.test_qt.FavoritesManagerIT fman_unittest.test_portable fman_unittest.impl.test_theme
python -X faulthandler -m unittest fman_integrationtest.impl.plugins.test_favorites_plugin fman_unittest.test_favorites fman_unittest.test_ui_elements fman_unittest.test_portable fman_unittest.impl.test_theme fman_integrationtest.test_qt
$env:QT_QPA_PLATFORM = 'windows'
foreach ($scale in @('1', '1.5', '2')) {
    $env:QT_SCALE_FACTOR = $scale
    python -X faulthandler -m fman_integrationtest.favorites_smoke
    if ($LASTEXITCODE -ne 0) { throw "Adaptive panel smoke failed at scale $scale" }
}
Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue
```

- Panel tests: 4 passed; API/dock/theme set: 37 passed; final set: 111 passed,
  no skips. Compact layouts respect unequal label minimums; medium/wide buttons
  share space equally and stop at their cap. Custom cap and invalid-cap checks pass.
  Initial equal-width assertion at the minimum width was corrected after runtime
  size hints proved Qt was preserving label fit, not ignoring stretch.
- Native source smoke requests widths 640/960/1440 at 100/150/200% DPI, checking
  growth, cap, button text fit and unchanged 22-logical-pixel close target. All
  passed; at 200% Windows constrained the widest requested geometry to the physical
  display. Compact and wide panel screenshots were inspected. Existing close,
  navigation, persistence, selection and reopening checks remain passing.
- Changed Python diagnostics: no errors. No new workers, timers, persistence or
  dependencies for responsive sizing. Frozen build/smoke and full build test suite
  remain unrun; broader task completion remains pending.

### Docking Validation

Commands run for the fixed main-window panel revision (not the full build suite):

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -X faulthandler -m unittest fman_integrationtest.test_qt.DockedPanelIT
python -X faulthandler -m unittest fman_integrationtest.test_qt.DockedPanelIT fman_integrationtest.test_qt.FavoritesManagerIT fman_unittest.impl.test_theme
python -X faulthandler -m unittest fman_integrationtest.impl.plugins.test_favorites_plugin fman_unittest.test_favorites fman_unittest.test_ui_elements fman_unittest.test_portable fman_unittest.impl.test_theme fman_unittest.impl.test_session fman_unittest.impl.plugins.test_plugin fman_integrationtest.impl.plugins.test_plugin fman_integrationtest.test_qt
$env:QT_QPA_PLATFORM = 'windows'
foreach ($scale in @('1', '1.5', '2')) {
    $env:QT_SCALE_FACTOR = $scale
    python -X faulthandler -m fman_integrationtest.favorites_smoke
    if ($LASTEXITCODE -ne 0) { throw "Docked panel smoke failed at scale $scale" }
}
Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue
```

- First geometry check exposed clicked(bool) reaching a no-argument callback;
  corrected the signal bridge and the same check passed. Later combined focus
  tests exposed a deleted-window callback from the static delayed shown timer;
  replacing it with an owned, close-canceled timer removed the crash. An indentation
  error in the focus handler was corrected before the same checks were rerun.
- Focused dock/manager/theme run: 27 passed. Final cross-module run: 132 passed,
  no skips. Covers full width and exact status-bar adjacency, pane shrink/reclaim,
  public controller mounting, reuse, close icon, Escape, Tab/Shift+Tab, navigation
  cancellation, prompt rejection, replacement, window closure, unload and late
  worker-result rejection. Existing persistence/session and API guards pass.
- Native source smokes passed at 100/150/200% DPI. Real close-icon clicks ended
  both surfaces, restored pane height, and allowed reopening with saved sort.
  Filter/sort p95 for 200 rows: 4.70/4.46/4.45 ms. Inspected the main-window and
  separate QuickList screenshots; dock controls are above the status bar and the
  close icon sits at the right edge. Qt supplies the icon; no external asset used.
- Changed Python files report no editor errors. Offscreen font/raise/size-hint
  warnings remain nonfatal. Frozen build/smoke and full `python build.py test`
  remain unrun per the existing user gate and focused-testing policy. Both task
  documents remain Pending; broader UI Elements scope is not marked complete.

### Public API Validation

The checked Phase A export items are implemented. The supplied guide uses the
actual widget-component API and host-owned build hook; future descriptor, tree
and preview proposals remain separate. Favorites is a reference plug-in consuming
only exported services. No generic thread-dispatch helper is exported.

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -X faulthandler -m unittest fman_integrationtest.impl.plugins.test_favorites_plugin fman_unittest.test_favorites
python -X faulthandler -m unittest fman_integrationtest.test_qt.PublicUiIT fman_integrationtest.test_qt.QuickListIT fman_integrationtest.test_qt.PanelIT fman_integrationtest.test_qt.FavoritesManagerIT
python -X faulthandler -m unittest fman_integrationtest.impl.plugins.test_favorites_plugin fman_unittest.test_favorites fman_unittest.test_ui_elements fman_unittest.test_portable fman_unittest.impl.test_theme fman_unittest.impl.plugins.test_plugin fman_unittest.test_release_support fman_integrationtest.impl.plugins.test_plugin fman_integrationtest.test_qt core.tests.test_quicksearch_matchers core.tests.commands.test___init__
$env:QT_QPA_PLATFORM = 'windows'
foreach ($scale in @('1', '1.5', '2')) {
    $env:QT_SCALE_FACTOR = $scale
    python -X faulthandler -m fman_integrationtest.favorites_smoke
    if ($LASTEXITCODE -ne 0) { throw "Public API smoke failed at scale $scale" }
}
Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue
```

- Integration-first regression: 30 passed after restoring the original module
  generation and owner. Resetting owner alone failed because mocks still resolved
  the reloaded module; that failed probe was corrected in the integration fixture.
- Component suite: 31 passed. Final focused cross-module set: 192 passed, no skips.
  PublicUiIT proves worker-command construction, reuse/query seeding, owner
  invalidation, readable constructor misuse, precheck timeout, saturation and busy
  rejection. Existing manager checks cover success/failure/cancel, selection,
  settings, prompts and pane closure. Core's matcher tests cover the rehomed code.
- Native source smoke: startup, two panes, reuse, JSON persistence, Go To,
  bookmark-only deletion, empty state, selection and compact control fit passed
  at 100/150/200% DPI. 200-row filter/sort p95: 4.81/4.56/4.43 ms.
- Editor diagnostics reported no errors in the checked source/test files.
  Offscreen font/raise warnings persist; the denied-directory traceback is an
  exercised negative test and the focused process exits 0.
- Frozen build/smoke remains user-skipped; full `python build.py test` was not
  requested and was not run. Both tasks stay Pending; this validates only the
  implemented public Favorites subset, not deferred tree/preview/editor work.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Public provisional widget components plus host-owned construction are
  the selected contract. Favorites must work without internal imports. Kept
  Extended Quicksearch descriptors separate and deferred broader consumer APIs.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented exported hosting, resources, matchers and bounded tracked
  navigation; documented lifecycle, theme and prompt APIs. Passed 192 focused
  tests and native source smokes at three DPI scales; packaging remains pending.

### Three-Component Validation

Environment and focused validation (not the complete build suite):

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -X faulthandler -m unittest fman_integrationtest.test_qt.QuickListIT
python -X faulthandler -m unittest fman_integrationtest.test_qt.PanelIT
python -X faulthandler -m unittest fman_unittest.test_favorites fman_unittest.test_ui_elements fman_unittest.impl.test_theme fman_unittest.impl.plugins.test_plugin fman_unittest.test_portable fman_unittest.test_release_support fman_integrationtest.impl.plugins.test_plugin fman_integrationtest.test_qt fman_integrationtest.impl.plugins.test_favorites_plugin
python -X faulthandler -m unittest fman_integrationtest.test_qt.QuickListIT fman_integrationtest.test_qt.PanelIT fman_integrationtest.test_qt.FavoritesManagerIT
```

- Combined focused set: 125 passed, exit 0. Final component/manager rerun: 27
  passed, exit 0. Selection checks cover Space, Insert, Shift arrows/Home/End,
  Ctrl+A, current-only click, Ctrl multi-select, hidden selections, public widget
  embedding, optional built-in filtering and title/text rendering.
- Panel tests cover all three control types, JSON initialization and save,
  preservation of unrelated keys, cross-panel updates, invalid stored values,
  error rollback and owner disposal before a pending update. Operation buttons
  do not save JSON. Bound controls use existing bounded workers and queued signals.
- Initial validation caught a duplicated test-class header and a Qt bool-to-object
  signal connection mismatch; both were fixed and the same checks rerun.
- No offscreen skips. Qt's missing-font-directory and unsupported raise/size-hint
  messages remain warnings; the processes exit successfully.

Native source workflow and screenshot checks:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
foreach ($scale in @('1', '1.5', '2')) {
    $env:QT_SCALE_FACTOR = $scale
    python -X faulthandler -m fman_integrationtest.favorites_smoke
    if ($LASTEXITCODE -ne 0) { throw "Component smoke failed at scale $scale" }
}
Remove-Item Env:QT_SCALE_FACTOR -ErrorAction SilentlyContinue
```

All three passed. Verified real JSON sort persistence and reopen, actual Space
selection, frameless host, folder-only navigation, bookmark-only deletion and
button label fit. The smoke captures both the manager and a standalone panel
with on/off icon buttons, a drop-down and text operation buttons. Inspected the
100% and 200% images. Filter/sort p95 at 200 rows: 5.06/4.46/4.86 ms.
The benchmark blocks configuration signals while measuring view projection, so
it does not queue artificial settings writes. It does not measure filesystem I/O.

Packaging lists fman.ui and the panel module as hidden imports. The user-skipped
freeze/frozen smoke was not retried; no packaged API availability is claimed yet.
The full build suite and deferred tree/preview/editor surfaces were not run or
implemented. Both task documents remain Pending until their delivery gates pass.

### Review Follow-Up

The Favorites review fixes keep navigation in neutral fman.impl.navigation,
separate cancellation settlement from bounded running initialization, move pane
ownership/theme integration into PaneToolWindow, and use nonblocking standard
dialog widgets with a main-thread QApplication test harness. InteractionPanel
accepts its label and obtains padding from the theme; QuickList supports
widgetless rendering and relayout on resize. Resource revisions are locked.
See the current [review resolution](../Done/Favorites002.md#fable-review-resolution) and
[focused results](../Done/Favorites002.md#review-fix-validation). The frozen gate and
this task's deferred surfaces remain pending.

### Earlier Implementation Validation

See [Favorites002 validation](../Done/Favorites002.md#validation-results) for exact setup,
commands, source smoke/DPI measurements and remaining gates. The final focused
regression set passed 138 tests and the native Qt/model/loader set passed 38.
The user skipped `python build.py freeze`; frozen validation is unverified.
Do not move this broader task to Done: only the approved Favorites subset exists.