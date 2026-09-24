# Search Files 001

Renamed to Search Files on 2026-09-20. Dated review and validation records below
retain the identifiers used at the time; current paths use `SearchFiles` / `search_files`.

## Task

Add a bundled `SearchFiles` plug-in with a compact search Panel and a
reusable Table in a modal results dialog. Search inside files below the invoking
pane's directory in the background, show progress in the main-window status bar,
then present the collected results when the search ends. Fuzzy-filtering the
Table never searches the disk again. This is the first `fman.ui.show_table`
consumer; the public result is a Qt-free handle, not a widget.

Table follows `show_quicksearch`'s small callable-provider/display/value
philosophy. The host supports modal and modeless windows; content search chooses
modal. The internal Table widget does not impose a window lifetime. Optional
file/folder column roles add cell-specific path actions; ordinary data needs no
paths. F1 Shortcuts is a visual reference only and stays
independent and unchanged in this task. A later File Rename / Replace consumer must be able to show
current names and virtual proposed names using the same read-only element.

Status: source implementation and review follow-ups completed on 2026-09-14.
Frozen-artifact execution is outside this source task, retained as a release
follow-up rather than an inferred pass. PyInstaller directly includes the
conda-forge executable and notices, without custom package verification.
No freeze, clean, full test suite, downloads, package installation or virtual
environment creation was run during the review follow-up.
The latest user decision supersedes
both the old modal tree/preview and progressive modeless Table proposals:
Panel -> background search with status-bar progress -> modal result snapshot.
F1 migration and progressive search-result population are deferred. Modeless
hosting is included for reuse, not a live-search requirement. The latest Qt-free
facade and cell-role design supersedes the earlier public-widget/row-menu design.
The contract is canonical for
this increment of [UI Elements](../Plan/UIElements.md).

## Scope

- Windows local `file://` directories, including accessible network paths;
  ripgrep-backed background search, Stop, status-bar progress, bounded completed
  or explicitly partial result snapshots, and file
  navigation. Nonlocal providers and archive locations report unsupported scope.
- A separate Panel with File Name Pattern, Content Pattern, independent regex
  Literal/Glob/RegEx icon groups, Include Subdirectories icon toggle, and Search/Stop actions.
- A Qt-free Table service with population callback, column count, headers,
  optional file/folder columns, default path resolution, stable row/cell
  identity, fuzzy filter, sorting and bounded snapshot refresh. Both modal and
  modeless hosting are required, with a modeless synthetic rename/Panel fixture.
- No F1 migration: retain its own implementation, substring filter, grouping,
  tabs, keyboard behavior and style. Use it only as the visual reference.
- Exactly two initial search columns: **File Path** and **Snippet**. No tree,
  editable cells, embedded operation controls or separate preview pane.
- Preserve the public `fman` 1.7.5 API and existing `show_quicksearch` behavior.
  Services, plain records and handles are additive provisional exports through
  [fman.ui](../src/main/python/fman/ui.py). This plug-in imports neither Qt nor
  private host modules and never constructs widgets, connects Qt signals or
  handles UI-thread dispatch. Existing widget exports remain compatible; their
  migration in other plug-ins is outside this increment.

Deferred from the older proposal: progressive search-result updates, F1 migration,
multiline, files-without-match, binary-as-text,
context preview, free-form encoding selection, PCRE2 fallback, persistent query
histories and advanced matching controls. Archive contents, document converters,
content replacement, real renaming and a Python content-search fallback remain
excluded. Suggestions below are not additional first-version acceptance gates.

## Design

### Panel and Placement

Command `search_files`, title `Search files`, appears in the
palette with proposed binding `Alt+F7`; verify effective bindings before adding
it. The plug-in calls the proposed `show_panel` service with plain control
descriptors, callbacks and its registered UI owner/public pane. The host
constructs and mounts the form, returning a Qt-free PanelHandle. It docks
full-width above the status bar and
is the only search UI while idle or searching. Both panes stay usable during
the scan. No empty floating window or Table is shown before results are ready.
Use the existing single-dock replacement policy, not a new docking system.

The existing UiController.show/build path exposes widgets and unconditionally
shows a tool window. Keep that legacy path compatible, but do not make the new
plug-in use its build hook. Implement the facade in fman.impl.ui, reusing the
existing owner, dock and dispatch services internally. A panel-only session
must not briefly show a blank floating window or create a taskbar entry. The
host owns its coordinator and focus routing; plug-ins receive no window object.

After the runner settles, the plug-in calls `show_table` with its finalized
snapshot provider, `modal=True`, and the returned PanelHandle as `panel`.
The host creates an internal `TableWindow(ToolWindow)`, also a QDialog, containing
its Table, result summary and current-cell details. Before showing it, replace
ToolWindow's Qt.Tool flags with Qt.Dialog and apply the requested modality.
This reuses the existing navigation/lifetime surface without exposing the
window to plug-ins; the navigation contract below names its dependencies.
The results surface has no toolbar, action footer,
inline row buttons, selection checkboxes or custom Close button. The text filter
has no clear/search button. The ordinary window close control remains host
chrome, outside Table; Escape also dismisses results. Search/Stop and option
buttons remain in the separate search Panel. The host builds Copy Path / Go To
menus only for designated path cells. Optional custom actions are plain records
and callbacks, never plug-in QMenus.
For modal presentation use Qt.WindowModal and `open()` internally: input blocking
does not require blocking Qt or another worker in `exec()`. Only one owned
result window is allowed per PanelHandle; session disposal closes it and
invalidates callbacks. `show_table` always returns a handle without waiting for
the user to dismiss the window; modality does not mean a blocking call.
Closing this results dialog returns focus to the still-mounted Panel and keeps
the entered options; it does not itself dispose the search session. Table and
its snapshot are released on dialog close. General Window/DirectoryPane APIs
still expose no raw widgets; these additions stay in the opt-in `fman.ui` host.

With `modal=False`, the same host uses nonmodal presentation. The panes and
associated Panel remain interactive; Panel edits can compute a new immutable
preview and call `table.refresh()`. The host bridges Tab/Shift+Tab at window/
Panel boundaries without exposing widgets and preserves filter/current cell
on refresh without stealing focus. Go To retains modeless results by default.
Closing the Table leaves its Panel; closing/replacing the Panel disposes the
associated Table and rejects pending refresh/navigation/menu callbacks.
Content search remains modal; the modeless gate uses a synthetic rename preview,
not an implementation of rename or progressive search.

The panel has two labeled rows. Each expanding text box has its own three-option
mode group immediately to its right. A scope/action row contains the read-only
root path, recursion toggle and Search/Stop. Recursion and Search/Stop start in
the same column as the mode groups, not at the panel's far right. All nine
buttons are 28x28 logical pixels, arranged in three columns with 3-pixel gaps.
Search/Stop are icon-only with tooltips. Stop remains enabled, uses a red square
icon and does nothing while idle. At narrow widths the fields shrink so these
controls remain on the third row. A noninteractive 20-pixel pane icon precedes
the path, with "Left pane" or "Right pane" as its tooltip and no visible label.

`Panel` currently owns a single horizontal layout. Keep that legacy contract:
the host renderer creates the nested QWidget/QGridLayout and passes it through
Panel.add internally. The plug-in only supplies rows of plain descriptors;
it never imports PyQt, creates layouts, calls addWidget or manipulates signals.
For forms with capped fields, the renderer aligns trailing controls when every
row starts with one capped field or label. A capped, shrinkable first column
and a trailing expanding spacer preserve alignment and compact window sizing.
Other forms retain their existing action wrapping. Budget about 120 logical
pixels for the search panel's three rows, including margins; derive minimums
from styled size hints. This reduces both file panes' visible height, not the
status bar's. Verify actual window width, unclipped labels and remaining pane
area at minimum size. Layout remains bounded work on the Qt thread, with no
extra workers, I/O, timers or disabled-feature cost.

Appearance remains host-owned. The host exposes existing action IDs through an
internal widget property; `stop` receives a `#ff5252` icon. The Action descriptor
stays unchanged. Rejected a public color parameter and plug-in-specific Qt access.
Equal icon buttons were selected over right-aligning unequal-width rows.

Proposed companion surface, bounded to this form rather than a general layout
language: `show_panel(*, owner, pane, rows, on_change=None, on_action=None,
on_closed=None) -> PanelHandle`. `rows` is a tuple of tuples containing immutable
`TextField(id, label, value='', tooltip='', max_width=None)`, `Toggle(id, icon, label,
value=False, tooltip='')`, `Label(id, text, icon=None, tooltip='')` and
`Action(id, label, icon=None, tooltip='')` records, plus
`Choice(id, label, options, value, tooltip='')` for exclusive icon groups.
Choice options are 2-8 immutable `(value, icon, tooltip)` string triples.
IDs are unique strings;
values are strings/bools; icons are plug-in-local resource names, not QIcons.
Descriptor validation and rendering belong to the shared host. This is an
additive facade, not a change to existing Panel/IconButton constructors.

The host aligns text-field labels using their styled size hints. Optional
`max_width` is a positive integer cap for the input in logical pixels, or None
for uncapped fields. Both search inputs use 480; narrow forms may shrink them.

PanelHandle exposes `snapshot()` (an immutable ID/value mapping),
`update(values=None, enabled=None)` (atomic validated control changes),
`set_activity_status(text=None, *, get_text=None)`, `close()`, `is_open` and a
read-only plain cancellation token `cancelled.is_set()`. Host disposal sets
the token before dropping callbacks, including on owner unload. Callbacks are ordinary
`on_change(values)`, `on_action(action_id, values)` and `on_closed()` functions;
the host captures values before dispatch. Programmatic updates do not echo
on_change. Settings load/save remains on-demand through existing resources and
transactions, passing only plain values through the handle. No widget/signal,
arbitrary parent/layout, QObject, screen coordinates or Qt enum crosses this API.

| Control | Default and meaning |
| --- | --- |
| File Name Pattern | Empty selects all eligible files. Literal searches for literal text within the basename. Glob (default) keeps native `;`-separated basename masks, positive masks before exclusions, with no path syntax. RegEx searches one default-engine expression against the basename; anchors may require a whole name. |
| Filename mode | Exactly one of Literal, Glob and RegEx. Literal/RegEx use bounded basename filtering; neither splits semicolons nor interprets leading `!`. |
| Content Pattern | Required; preserve spaces. Literal (default) searches for literal text anywhere in a line. Glob matches a whole line. RegEx uses ripgrep's default engine; unsupported lookaround/backreferences are errors. |
| Content mode | Exactly one of Literal, Glob and RegEx, independent of the filename mode. |
| Include Subdirectories | On; off searches only immediate files in the captured root. Do not follow directory symlinks/junctions in either mode. |
| Search / Stop | Search starts an explicit scan; Stop is enabled only while running. Editing inputs or filtering results never starts a scan. |

Filename matching and content matching are case-insensitive initially. Explain
glob/regex dialects and case behavior in tooltips and eventual README examples.
Reject NUL/newline input and invalid patterns before starting engine traversal.
File-name mask whitespace around separators is trimmed; content is not trimmed.
Use Literal mode for literal semicolons or wildcard characters in filenames.

### Three Pattern Modes

Each input has a host-owned `Choice(id, label, options, value)` group with three
mutually exclusive 28-pixel icon buttons. Options are immutable
`(value, icon_resource, tooltip)` triples; clicking the selected option never
deselects it. Selection is a string in Panel snapshots; programmatic updates
validate atomically and emit no user callback. Disabling the group disables all
its buttons. Retain ordinary Toggle for recursion. Use pinned Lucide `text`,
`asterisk` and `regex` icons with Literal/Glob/RegEx tooltips and accessible names.

Content glob syntax: `*` matches zero or more non-newline characters, `?` one,
`[abc]` a set, `[a-z]` an ascending range, and `[!abc]` a negated set. A first `]`
inside a set and edge-position `-` are literal. Unclosed/empty sets and reversed
ranges report an input error. Regex metacharacters outside glob syntax are
escaped, including backslashes; use `[*]`, `[?]` and `[[]` for literal wildcard
characters. Slash and repeated stars have no directory/recursive meaning.
No brace expansion, leading exclusions or semicolon splitting applies to content.
Use ripgrep's `--line-regexp` with the translated expression and existing
`--crlf` handling. Thus `cuda` matches a whole line and `*cuda*` contains cuda.
All modes remain case-insensitive. Whole-line matches highlight the whole line.

The converter is a bounded linear scan in the existing engine module using
`re.escape` for regex literals. Preflight compiles the final expression through
the same ripgrep arguments as the real search. A failed conversion starts no
traversal. No new engine/package, Python regex execution of user expressions,
download, path lookup or shell invocation is introduced.

Alternatives: directly using `fnmatch.translate` was rejected because its atomic
groups are unsupported by ripgrep. `glob.translate` has pathname-specific rules
and can emit unsupported empty-set lookarounds. Explicit small-dialect conversion
keeps the public semantics independent of Python's regex translation format.

Persist `name_mode` and `content_mode` as `literal`, `glob` or `regex`. Migrate old
boolean `name_regex` to regex/glob and `content_regex` to regex/literal; a valid
new mode takes precedence. Ignore invalid modes and use migrated/default values.
Remove obsolete boolean keys on the next settings save. No patterns are saved.
Filename Literal shares the bounded filename-RegEx pipeline, with `--fixed-strings`.
Filename Glob retains the single-traversal fast path and existing hidden behavior.

Runtime effects: O(pattern length) conversion once per worker preflight, bounded
by the existing pattern/command limits; immutable prepared arguments are reused.
Each open Panel adds six buttons instead of two toggles, with no new timers,
workers or recurring subscriptions. Unused/closed features do no mode-specific
work. Cancellation, row/text/process bounds and fixed-pane ownership are unchanged.

Required checks: native ripgrep Literal/Glob/RegEx content and filename cases;
whole-line/CRLF/Unicode, metacharacter escaping, empty wildcard matches, repeated
stars, ranges, negation, literal brackets, invalid sets; legacy settings migration;
Choice validation/exclusivity, selected-button clicks, callback counts, atomic
updates, disabled groups; search locking/disposal; native compact layout and
persisted modes. Use existing engine/unit/Qt tests and source smoke, not a freeze
or full test suite. Completion requires these checks and aligned API/usage docs.

Glob mode adopts ripgrep's native ignore/hidden interaction: ignore files are
disabled, hidden entries are normally skipped, but explicit positive globs can
whitelist matching hidden entries. Document and test this rather than claiming
all hidden entries are always excluded. Filename-regex mode enumerates without
positive glob overrides and excludes hidden candidates. An Include Hidden
control remains deferred; neither mode follows symlinks/junctions intentionally.

Keep the session bound to its invoking pane, identified by a fixed left/right
symbol and label beside the root. No pane-switching control is needed. While
idle, follow that pane through the public `DirectoryPane.on_path_changed(callback)`
subscription; changes in the other pane have no effect. Read the current URL
on opening, before Search, and on returning to idle; non-local locations disable
Search. Unsubscribe on disposal. Notifications run on Qt and add no polling,
workers or subscriptions while the feature is unused.

Capture the root separately for each Search. Pane navigation never retargets a
running search or existing Table; the form catches up when results close or a
run settles without rows. Search snapshots all inputs and locks matching
controls until results close, or until the runner settles without rows. Stop is
available only while the runner is active; Panel Close remains available while
results are deferred. The form stays locked throughout deferred/modal results.
Only one generation runs per session; restart waits for child cleanup. The
modal starts with an empty local filter and a finalized snapshot, not a live
connection to the runner. While it is open, the invoking main window and its
Panel are intentionally blocked; dismiss results before changing the query.

### Status Bar and Completion

Search immediately displays `Validating`, then `Searching` with collected
matching-line/file counts and elapsed time in the invoking window's status bar.
Use indeterminate progress, not a percentage: a total file count is not known
without an extra scan. Update at most five times a second; no Table/model is
created or mutated during the scan. Zero-hit and slow/network searches must
still show an active state. Stream and parse rg internally, but collect rows
off Qt and publish only one immutable terminal result snapshot.

The existing `fman.show_status_message` replaces a shared message without an
ownership token. Do not repeatedly overwrite/clear unrelated operations with
that API. Use `panel.set_activity_status(text=None)` on the Qt-free handle: it
owns a temporary plain-text activity label in the existing QStatusBar, separate
from the legacy message and optional pane-summary widgets. The host parents,
themes and elides it, supplies a full tooltip, and removes only that session's
label when cleared/disposed. It works even when extended pane statistics are
disabled, without enabling their scans/timers. It performs no work until used.

| Terminal outcome | Presentation |
| --- | --- |
| Completed with rows | After process cleanup, stop progress and open the modal Table once with the final counts. |
| Completed with zero rows | Show `No results` in the status bar; unlock the Panel without opening an empty modal. |
| Stop with rows | Stop means finish early: kill/reap children, freeze collected rows, then show a modal explicitly marked `Stopped - partial results`. |
| Stop with zero rows | Show `Stopped`; unlock the Panel without a modal. |
| Row/text/per-file limit | Finish with a clearly marked `Limited` snapshot and the limiting reason, never an unqualified Complete. |
| Read errors with usable rows | After cleanup show `Incomplete - read errors` results with bounded error details; do not silently report full coverage. |
| Validation/startup/protocol failure | No results modal; report an actionable error, retain the form and allow correction. |
| Panel close, replacement, pane destruction or plug-in unload | Cancel, discard any pending presentation, remove owned status and never show a late modal. |

Terminal events bypass progress throttling. Owner/generation checks reject late
progress and duplicate completion before any status change or dialog opening.
If the invoking window is inactive or already has a modal, retain the bounded
snapshot and show `Results ready` in its status bar. The host defers presentation
until that window is active and the other modal has closed, using lifetime-bound
events, not a polling timer. Do not stack dialogs or steal focus from another
application. Closing/disposal while deferred discards the snapshot.
Deferred presentation uses a host-owned application-wide event filter and a
lifetime-bound `QApplication.applicationStateChanged` connection only while
pending. The filter observes WindowActivate, Hide, Close and DeferredDelete from
any widget, including a blocking modal; this is a deliberate superset of scoped
window/modal filters. Each trigger schedules at most one queued retry after Qt
has processed the event; no window is shown synchronously inside the filter.
Immediately before opening,
re-check the alive owner/session/generation, active application, active invoking
main window and `QApplication.activeModalWidget() is None`. A different active
window or any remaining modal leaves the result pending. Modal replacement needs
no subscription replacement. Remove the application filter and state connection
after presentation/disposal; never poll or schedule recurring idle retries.
The ordinary invoking-window Close filter remains until Table disposal. Pending
event work is bounded to a small type check and a coalesced retry, with no I/O.
Once a modal opens, clear the activity label; its summary carries the terminal
state. Without a modal, terminal status stays until the next Search or panel
close, without a recurring timer. Disallow another Search while a completed
snapshot awaits presentation, so it cannot be replaced silently.

### Icons and Tooltips

Use actual upstream SVGs, bundled locally at implementation time, not text
buttons spelling out `RegEx` or a downloaded icon package. Selected sources:

| Button | SVG | Tooltip / accessible name |
| --- | --- | --- |
| File-name regex | [Lucide regex](https://lucide.dev/icons/regex), the familiar `.*` symbol | `Use regular expression for file name` |
| Content regex | Same regex SVG | `Use regular expression for content` |
| Recursion | [Lucide folder-tree](https://lucide.dev/icons/folder-tree) | `Include subdirectories` |
| Search | Lucide `search` + `Search` label | `Search file contents` |
| Stop | Lucide `square` | `Stop search; keep collected results` |
| Panel Close | Existing host close icon | `Cancel search and close panel` |

The host maps Toggle, Choice and Action descriptors to the appropriate controls. It
may add an internal action-mode option to IconButton while preserving its
existing public default; Stop must be noncheckable and unbound to settings.
Only the host constructs QIcon/QtSvg objects and connects clicked/toggled.
Search uses the existing noncheckable text-plus-icon control internally. No
plug-in-side setCheckable call, QIcon construction or Qt signal connection.
Cover existing Favorites toggles and JsonSettings bindings in regressions.
Show checked fill/border, keyboard focus and accessible checked state; do not
rely on color alone. Tooltips append current On/Off state. Keep a fixed 28-logical-
pixel hit target and 16-18-pixel glyph, subject to DPI checks and theme sizing.
Every search-panel button needs a tooltip and accessible name. Results have
no buttons, including no filter-clear button; context-menu actions use ordinary
accessible menu labels. Render panel icons with the QtSvg/palette-aware approach used by
[OutputTextBox](../src/main/python/fman/impl/ui/output.py).

Record a pinned Lucide release/commit and preserve the applicable
[ISC and derived Feather MIT notices](https://lucide.dev/license) with the
bundled assets. These permissive licences allow open-source use, modification
and redistribution, including commercial redistribution, with their notices
retained. Use only icons with verified open-source licences: `regex`
and `folder-tree` are Lucide originals under ISC; `search` and
`square` are Feather-derived and also require the upstream
MIT notice. Verify every chosen asset at the pinned revision, including any
replacement/host close icon; reject unlicensed or unclear-provenance assets.
Verify monochrome recoloring in QtSvg; do not assume browser
`currentColor` inheritance works in QSvgRenderer. No network requests at runtime.

### Reusable Table API

Proposed plug-in code after the runner settles and transfers immutable results.
`owner` is the plug-in's registered UiOwner (not a QObject); `pane` is the public
DirectoryPane wrapper. Reuse the existing loader registration: a plain
`SearchUI(UiController)` class obtains its owner through `require_owner()` and
calls the services from its own command methods, never UiController.show/build.
This UiController subclass with no build override is the intended owner carrier
for this increment; do not add a second marker base. Registration and
require_owner() do not call build. Legacy show/build retains its existing
behavior and is not the entry point for this facade.

Resource-root association is a new loader hook, not existing functionality:
extend `UiOwner` with an optional keyword-only `resource_root=None` constructor
argument and a read-only `resource_root` property. In
[ExternalPlugin._load_classes](../src/main/python/fman/impl/plugins/plugin.py),
create `UiOwner(resource_root=self._path)` for each registered UiController
subclass and keep the existing owner list/unload invalidation. Store a lexical
absolute normalized root; registration performs no icon reads or scans. The
default preserves manual/legacy UiOwner construction, but an owner without a
root cannot resolve plug-in-local icon names. Report a clear resource error
instead of falling back to CWD or another plug-in's assets. Do not require
plug-ins to discover roots, assign them or create unmanaged owners.

The host resolves descriptor resource names lazily when rendering: allow only
relative names contained within the owner's root, reject absolute/escaping
paths and reparse/symlink escapes, and never fetch remotely. Scope cached icons
to that owner/root and release them on unload; source and frozen loading must
supply their respective plug-in resource roots through the same hook. This is
resource ownership, not a filesystem sandbox for arbitrary plug-in code.

```python
from fman.ui import show_table

def get_rows():
  return results

table = show_table(
  owner=owner,
  pane=pane,
  panel=panel,
  title="Search Results - " + search_root,
    get_rows=get_rows,
    num_columns=2,
    columns_header=("File Path", "Snippet"),
  file_path_column=0,
  folder_path_column=None,
  base_path=search_root,
  modal=True,
)
```

`show_table(*, owner, get_rows, num_columns, columns_header, pane=None,
panel=None, title='', fuzzy=True, file_path_column=None,
folder_path_column=None, resolve_path=None, base_path=None, modal=True,
close_on_navigate=None, summary='', get_details=None, on_activate=None,
get_menu=None, on_closed=None) -> TableHandle` is the canonical proposed entry.
No public QWidget constructor, Qt signal or raw window API is needed. Supplying
`panel` associates lifetime/focus and supplies its pane if omitted; a conflicting
owner or pane is rejected. Without a Panel, the host uses the supplied pane's
window, or captures the active main window for a data-only Table. It never
silently captures an active pane as a navigation destination when pane is absent.

| Contract | Definition |
| --- | --- |
| `get_rows() -> Iterable[TableRow]` | Required population callback, once on construction and explicit refresh only. Supplies a finite already-available snapshot; never from painting, sorting or filter keystrokes. No I/O, waiting, search process or asynchronous generator. |
| `num_columns: int` | Required positive integer, excluding bool; fixed for the Table lifetime. |
| `columns_header: Sequence[str]` | Required nonempty column labels; copied to a tuple. Length must equal `num_columns`. |
| `TableRow(id, cells, value=None, highlights=())` | Immutable plain record; nonempty stable string ID, exactly num_columns string cells, bounded immutable opaque payload and optional per-cell highlights. Identity never comes from display indices. Path interpretation is opt-in by column, not an assumption about every row. |
| `file_path_column`, `folder_path_column` | Optional zero-based logical column indices. Each is None or int excluding bool, within range; when both are set they must be distinct. Both None disables all built-in path behavior. Column reordering is not offered initially; resizing/sorting cannot change these roles. |
| `resolve_path(row, column)` | Optional pure callback returning an absolute native path string or None. Omitted/None selects the default resolver below; it does not disable path behavior. Used only for a designated path cell on menu/activation, never for painting, selection, filtering or sorting. |
| `base_path` | Optional absolute native directory string. If omitted and a path role is configured, capture the supplied pane's local directory when opening the Table. An explicit value wins and never changes on navigation. No captured local base means relative paths cannot resolve. |
| `modal: bool` | True by default. Host input modality only; creation always returns the handle without waiting for dismissal. False keeps the associated Panel and panes interactive. |
| `close_on_navigate` | None defaults to modal: successful Go To closes modal results and retains modeless results. Explicit bool overrides this. Never close on failed, canceled, superseded or stale navigation. |
| `summary`, `get_details(row, column)` | Optional plain summary text and a fast plain-text details callback for the current cell; no implicit path resolution/I/O. Host renders passive labels, not caller widgets. |
| `on_activate(row, column)` | Optional ordinary Python callback for non-path cells. Without it, ordinary-cell activation does nothing. Path columns always use host path behavior and never fall through to this hook. |
| `get_menu(row, column)` | Optional pure callback returning a bounded tuple of `TableAction(id, label, callback)` records. Action callbacks receive captured (row, column). Host owns QMenu, position, focus, accessibility and disposal. No callback means no custom menu; path cells still receive standard Copy Path / Go To. |
| `on_closed()` | Optional ordinary callback, at most once on ordinary close while the owner is alive. On owner unload, discard plug-in callbacks and release references rather than calling unloaded code. |

TableHandle is not a QObject and exposes only `refresh()`, `close()`, `is_open`,
`current_cell` (immutable (TableRow, logical-column) pair or None), and read/write
`filter_text`. No view/model/parent/window/signal attribute escapes. `refresh()`
atomically replaces rows, preserving query, sort, current row ID/column and
scroll anchor when possible. If current is filtered out, choose the first visible
row with the same column; no visible rows means current_cell is None. Initially
current column is 0. The whole current row is highlighted, with a visible focused
cell indicator to make keyboard path actions unambiguous.

Handle calls are safe from ordinary command/worker callbacks; the facade owns
marshaling using the existing main-thread dispatcher. Calls validate/apply before
returning, but never wait for a dialog to close. Do not hold plug-in locks while
calling a handle. Providers, resolvers, details/menu callbacks and action hooks
run serialized on the host UI dispatcher and must be fast, nonblocking pure
Python; callbacks do not need or receive Qt access. They may schedule existing
bounded work but cannot join workers or run filesystem/engine work inline.
The search runner publishes a completed immutable snapshot before requesting UI;
no live worker-owned list is shared. Modeless consumers explicitly publish a new
snapshot before refresh, with their own computation-generation check.

Type/schema/column-role errors use TypeError or ValueError before showing a
window. A provider error during refresh leaves the old snapshot intact and
propagates through the handle call. Callback errors during interaction use the
host's owned error reporting, retain the window and perform no default/fallback
action. Close is idempotent; after close is_open=False/current_cell=None and
filter_text retains its last value. Mutation/refresh after close raises
RuntimeError before calling providers. PanelHandle has the same closed-mutation
rule; snapshot retains the last plain values and the cancellation token is set.
Queued requests check owner/window generation, so late work never reopens UI.
Owner unload/window destruction sets cancellation tokens before invalidation.
Only registered nonblocking runner-cleanup hooks are allowed during teardown;
ordinary UI callbacks are suppressed. Producer cleanup reaps children off Qt.

The internal Table remains a standalone QWidget/model/view implementation,
testable inside an ordinary QDialog without a pane or producer; the public
facade supplies lifetime and presentation. Shared internals may use Qt; plug-ins
may not import it or obtain its objects, even via a wrapper. No widget per cell
or directory-pane model reuse. Row payloads are not deep-copied; they must be
bounded immutable plain data. Highlights are half-open Python code-point ranges
per cell, converted to UTF-16 only inside the host delegate. An append API stays
deferred; refresh supports modeless previews without progressive search output.

### Path Resolution and Navigation

The default resolver reads the full underlying designated cell string, not
elided painted text. Absolute drive/UNC paths are used directly; ordinary
relative paths are joined lexically to the captured base. Normalize separators
and dot components with standard path utilities, preserving spelling/case and
spaces. Do not stat, resolve symlinks, expand environment variables/home, parse
shell syntax or consult process CWD. Empty strings return None. Reject NUL,
nonlocal URLs, drive-relative forms such as `C:notes.txt` and rooted-but-not-
absolute forms such as `\notes.txt`, rather than borrowing a current drive.
The first version uses native Windows local/UNC paths, not arbitrary provider
URLs. With no local base, a relative value has no target. Both role parameters
None skip resolution entirely, even if ordinary text resembles a path.

A supplied resolver replaces text interpretation and returns an absolute native
path or None; it may read the captured row payload but must perform no I/O.
None suppresses built-in path actions for that cell. Wrong types/relative return
values are reported as callback errors without navigation or clipboard changes.
For content search set `base_path=search_root`: the search root was captured
before the later results window opens, and the pane may have moved meanwhile.
The default resolver therefore handles the initial relative File Path column
without a custom callback. A friendly display label can instead use a resolver
that returns an authoritative path from the payload.

On path-cell right-click the host captures row ID, column, role, resolved path
and snapshot generation. Its standard menu has exactly Copy Path and Go To.
Copy Path copies the resolved absolute native path without checking existence.
Go To uses the captured public pane; with no pane, Copy Path remains available
but Go To is disabled and double-click does not navigate. Never silently choose
the currently active or left pane. Navigation is asynchronous via shared tracked
navigation: file role opens its parent and highlights that file; folder role
navigates into the folder. Do not infer the role by stat or extension. At action
time, missing/inaccessible/wrong-type targets report an error and retain results.
Host-owned checks must not block Qt; no filesystem work occurs just to select,
paint, filter, sort or open a menu. Reuse public path/URL conversion and navigation
services, not file-operation commands that open an associated application.

The facade calls the existing
[session.navigate](../src/main/python/fman/impl/ui/session.py) with
`window=table_window`, never TableHandle, PanelHandle or a bare QDialog.
The internal TableWindow inherits ToolWindow's QObject identity for
`QTimer(window)`, `busy`/`set_busy`, guarded queued `post`, `alive`, `owner` and
`disposed` signal. This is the selected adapter; do not change navigate's public
signature or introduce a new host protocol in this increment. Busy navigation
state belongs to that results window, not the associated Panel's coordinator.
Callbacks resolve only the still-current request and snapshot generation.

Use ToolWindow's idempotent disposal path to clear alive and emit disposed,
which cancels the NavigationHandle; parent-owned timers are destroyed with the
window and late post callbacks are rejected. TableWindow does not inherit
PaneToolWindow's panel-removal behavior: closing results leaves the Panel alive.
The shared facade links Panel disposal/pane close/owner unload to TableWindow
closure separately. Both modalities exercise this same lifecycle contract.

Only terminal success for the still-current navigation request applies
close_on_navigate; superseded navigation never closes another/current Table.
During a navigation request suppress duplicate Go To activation; closing the
Table cancels or invalidates that request. Pane navigation never retargets the
captured base or a modeless operation's source data. No plug-in navigation wiring,
clipboard call, QMenu construction or Qt event handling is required.

### Table Interaction

Table contains only its text filter, headers, rows and passive counts/details.
There are no command buttons, clear icon, toolbar, row-action icons or selection
checkboxes. Standard scrolling, column resizing and header sorting remain.
Keep single whole-row selection for this increment; selecting multiple rows
and bulk actions require a separate consumer decision.

| Input | Behavior |
| --- | --- |
| Left click in any cell | Highlight the row, make the clicked column current and update passive details. No action, even if the row was already selected. |
| Left double-click in a path cell | File column: reveal the file in its parent; folder column: navigate into the folder. One Go To request; no target means no operation. |
| Left double-click in an ordinary cell | No built-in operation; call on_activate(row, column) only when explicitly supplied. Never borrow a path from another cell in the row. |
| Right click in a cell | Make that row and column current. Resolvable path cell: host Copy Path / Go To menu. Ordinary cell: no built-in menu; only explicitly supplied custom actions. No activation or selection toggle. |
| Click in empty row space | No row action or context menu and no fallback to a previously selected row. Preserve current selection. |
| Header click / separator drag | Sort / resize the column, without activating or opening a row menu. |
| Arrow, Home/End, Page Up/Down keys in the view | Normal table current-cell navigation, including Left/Right between columns; highlight one row. Filter focus retains ordinary text editing. |
| Enter / keypad Enter | Same as double-click on current visible cell, from filter or view. No current means no-op; no fallback to the first path column. Ctrl+Enter has no built-in file-opening action. |
| Menu key / Shift+F10 | From the view, same menu as right-click on current visible cell; no current means no-op. From the filter, keep its standard text-edit menu. |
| Ctrl+F | Focus the filter and select its text; editing/clearing it is local and never launches search. The filter retains its normal text-edit context menu. |
| Escape | Close an open context menu first; otherwise dismiss the Table window (either modality) and return focus to its Panel/pane. The normal window close control also dismisses it. |

The host creates its QMenu internally and uses popup, never asking the plug-in
for a position/widget. Capture row/column, resolved target and generation when
building actions, not a later current selection. Dismiss on current-cell change,
filter, sort, refresh, window close or owner disposal and reject stale callbacks.
Never retarget an old menu choice to another cell. Custom action IDs/labels are
validated, limited to 32 records and 128-character labels, and cannot replace
reserved built-in IDs; show them after a separator. Content search supplies no
custom menu/activation hooks in this increment. A synthetic ordinary-data fixture
proves callback reuse without assuming any file/folder column.

### Filtering and Presentation

The built-in fuzzy field searches every column independently using the
existing QuickList matcher and Unicode offset mapping. Rank by best cell match
with stable source-order ties. Empty query restores source order. Explicit
header sorting takes precedence over fuzzy rank, uses casefolded display text
and stable ties, and remains active when the filter clears. Header clicks cycle
ascending, descending, unsorted. Filtered-out rows remain in the snapshot;
counts distinguish visible and total rows. Filter arrows move to the view;
Modal Tab/Shift+Tab stay inside its enabled controls; modeless hosting can bridge
to the associated Panel at the boundary. These are host-internal focus rules,
not public widget hooks. Initial focus is the filter, or the view if fuzzy is
off. Close/Escape returns to the Panel/pane. Keep existing QuickList behavior.

Fuzzy positions come from the shared `contains_chars` matcher used by Table,
QuickList and Core's re-export: prefer a contiguous substring when present,
otherwise retain in-order subsequence matching. Casefold offsets map back to
original characters. This preference is shared, not a Table-specific branch.

F1 is a visual reference only: its
[current implementation](../src/main/python/fman/impl/shortcuts.py) stays intact,
including substring filtering and plug-in grouping. Match its header treatment,
alternating rows, compact spacing, selection and theme, using new scoped hooks
in [styles.qss](../src/main/resources/base/styles.qss), not a shared-widget migration.
Give the wrapper object name `results-table` and its QTableView
`results-table-view`. Scope all new header/item/selected/focus rules beneath
those names, including explicit item padding for `:has-children` and `:open`.
The existing global QTableView rules serve the file-pane delegate's first/last-
column State_Children/State_Open padding workaround; do not repurpose them or
emit those flags from the Table delegate. Higher-specificity Table rules must
override inherited directory colors/padding for every state without altering
directory-pane selection, cursor, first/last-column spacing or inline rename.
Columns are user-resizable; start search at roughly 40% path / 60%
snippet, with minimum widths and horizontal scrolling if needed. Do not run
ResizeToContents over all result rows. Elide long cells with a tooltip of
their retained text; keep row heights fixed and content as plain text.

For future rename preview use `modal=False`, a live PanelHandle and headers
`("Current Name", "Proposed Name")`. Only the current/source column has a path
role; the proposed name remains ordinary text even if it looks like an existing
path. Stable source IDs survive preview refresh. A resolver may return the
captured original path if the source display is a friendly label. Computation,
collision checks, Apply, rollback and writes belong to that future feature.
A synthetic Panel-driven preview must verify modeless refresh/navigation/focus
now, without implementing real rename or editable cells.

### Search Rows and Actions

One row represents one matching line, not one file or every submatch. Repeated
paths are intentional. Multiple occurrences in that line are highlighted in the
same Snippet cell; counts say `matching lines` and `files`, not ambiguous matches.
The File Path cell is root-relative, with the captured root visible above.

Keep an immutable payload with absolute file URL, one-based line number,
first-match character column, and submatch offsets. IDs combine the generation
and immutable snapshot ordinal; each row remains stable within that snapshot.
Decode ripgrep byte offsets before
highlighting; transcoded offsets are not original-file seek offsets. Create a
bounded snippet around the first match, mark truncation, and never reread files
for selection or fuzzy filtering. A pure get_details callback formats the
captured payload's full path and `line:column` into a host-rendered passive label,
so the initial Table still has exactly two columns. This callback does not
resolve paths or probe the filesystem.

Search progress belongs in the main-window status bar, not a fake Table row.
The modal shows finalized total/visible line counts, distinct files, elapsed
time and any partial-result reason. Distinguish no disk matches (no modal)
from no rows matching the local fuzzy filter (an empty filtered view). Do not
invent scanned-file totals from ripgrep `begin` events, which omit nonmatching
files. Reaching the per-file line cap marks coverage as potentially incomplete.

Content search designates `file_path_column=0`, `folder_path_column=None` and
uses the default resolver with the captured search base. It supplies no custom
menu or activation callback. This replaces the older row-wide file-action menu.

| Cell | Interaction |
| --- | --- |
| File Path | Double-click/Enter: navigate to its parent and highlight the file. Right-click: Copy Path and Go To. |
| Snippet | Select/update passive details only. No built-in navigation/menu, even if snippet text resembles a path. |

No Open File, Ctrl+Enter association launch, Copy Snippet, delete/rename/write,
native shell menu or bulk actions are included in the initial search results.
Copy Path uses the full resolved native path and does not access the filesystem.
The filter retains its own normal text selection/copy behavior. The host owns
tracked navigation, keyboard/menu dispatch and close-on-success; the plug-in
supplies only data and options. No scan runs while browsing modal results.
Failure/supersession keeps the dialog; success closes only results, retaining
the Panel, root and entered options. Selection/right-click alone never navigates.
Escape (after dismissing any menu) or the window close control dismisses only
the results dialog and returns to
the form. Panel Close/Escape, dock replacement, pane destruction and plug-in
unload dispose the entire session and invalidate callbacks before cancellation.

### Engine and Ownership

Plug-in modules own command/session, pure argument/parser logic and the search
runner. Shared row/model/filter/delegate code lives under
[fman.impl.ui](../src/main/python/fman/impl/ui); only its exports are used by the
plug-in through Qt-free services/handles. Reuse the existing owner, session,
Panel, controls, settings resources, queued delivery and navigation internally;
do not expose UiController.build, PaneToolWindow, guarded Qt post, widgets or
private threading helpers to this plug-in. The plug-in entry receives an owned
plain lifetime/cancellation token from the facade; runner terminal delivery uses
only thread-safe handle/service calls and immutable data. Panel/status, path
menus, navigation, modal/modeless parenting and disposal belong to the host.
Long scans use a dedicated on-demand runner,
not the two shared lightweight UI/settings work slots.

The live-search lease belongs to the persistent host Resource registry, not a
reloadable plug-in module. Specifically, `settings_resource('SearchFiles runner')`
returns the named `Resource`, whose `try_claim()` slot returns an idempotent
release callback or `None`; the runner releases it only after process/pipe/thread
cleanup. This prevents a reloaded plug-in from starting a second worker while
its predecessor is still stopping. Unused resources allocate no workers/timers.

Retain the ripgrep executable decision. Run `subprocess.Popen` without a shell
or console window; pass Unicode argument lists, content/regex patterns via
`-e <pattern>`, then `--` before explicit paths. Use `--no-config`,
`--no-ignore`, `--no-follow`, `--no-mmap`, `--json`, `--line-buffered`,
`--line-number`, `--crlf`, `--max-count 200`, `--max-filesize 50M`, and at most
two search threads. Literal content adds `--fixed-strings`; translated Glob adds
`--line-regexp`; all modes add
`--ignore-case`. Default regex engine only; no automatic retry. No `--pre`,
`--search-zip`, multiline or binary-as-text. Keep stderr instead of suppressing
read errors. UTF-8 and UTF-16 BOM sniffing work in `auto`; a validated settings-
only `windows-1252` override handles legacy text without another initial control.

The search engine is bundled **ripgrep (`rg.exe`)**, an open-source Rust tool
under MIT/Unlicense. It supplies literal matching and its default Rust regex
engine, producing structured JSON match records. Table fuzzy filtering uses
the existing in-process QuickList matcher; it does not launch ripgrep. Filename
globs use native `--iglob`; filename Literal/RegEx require the pipeline below.

**Filename Glob (common path):** use one content-search process with the
captured directory as its only path operand. Pass positive masks using repeated
`--iglob <mask>`, then all `--iglob !<mask>` exclusions, regardless of their
order in the input. Do not add an implicit positive `*` for empty/exclusion-only
input, because it changes hidden-file behavior. Add `--max-depth 1` when recursion
is off. Ripgrep performs traversal, glob filtering, size eligibility and content
matching in that one run. No filename inventory, Python fnmatch, explicit-file
batches or per-batch process starts in this mode. Validate native glob syntax
during preflight; never substitute a second glob dialect. Reject an oversized
combined command line as input validation, rather than splitting it into
multiple traversals with incorrect exclusion/limit semantics.

**Filename Literal/RegEx:** filter basenames before reading contents using this
bounded pipeline:

1. Lazily enumerate with `rg --files --null --no-config --no-ignore --no-follow`
   under the captured root; omit hidden files/directories and add
   `--max-depth 1` when recursion is off. Drain into bounded candidate batches,
   not a complete path inventory. Do not mix `--files` with `--json`.
2. Send one bounded batch of NUL-delimited UTF-8 basenames to a
   separate `rg --null-data --json --line-number --ignore-case -e <pattern> -`
  invocation with `--no-config`; add `--fixed-strings` for Literal. Map its input record numbers back to the
   original paths, so duplicate basenames in different folders remain distinct.
   This keeps untrusted regex outside Python/Qt and uses the same regex dialect.
3. Search only accepted absolute files in bounded command-line batches. Add
   `--max-depth 0` so a file replaced by a directory cannot trigger traversal.
   Never run with an empty path batch, which would otherwise search stdin/CWD.
  Before explicit dispatch, the worker rechecks that each candidate is a
  regular non-symlink file, has no disallowed junction/reparse ancestor, is not
  hidden (dot name or Windows hidden attribute) and is within the 50 MiB size
  cap. Recheck ancestor visibility/eligibility under the captured root; cache
  metadata only within the bounded batch, not across runs. Skip ineligible
  files with counters and report metadata/read errors as incomplete coverage.
  Enforce these checks even if an rg version currently honors the flags:
  explicit path operands can bypass traversal filters. Keep `--max-filesize`
  as defense in depth, not the sole explicit-file guard. Changes after the
  check remain a race; this is not a filesystem snapshot or security sandbox.

The name-regex JSON/input-record mapping and Windows explicit-file behavior
require the focused engine spike in step 1 below. Compare a directory search
against an explicit hidden/oversized-file operand with the locked rg build and
record whether hidden/size flags are bypassed; test plug-in enforcement with a
fake runner that bypasses both. Bound encoded Windows command
lines to 24,000 UTF-16 units including quoting and flags; split batches and
report an individual overlong operand rather than silently omitting it.
In filename-regex mode, enumeration can coexist with one name/content process;
name matching and content matching run sequentially per batch. This costs
process starts and metadata I/O and delays first results by one batch; measure
it separately from the single-traversal glob fast path before acceptance.

One runner thread supervises the pipeline and parses capped byte chunks; at
most two on-demand stderr readers drain the live children into capped tails.
During filename-regex filtering, one temporary stdin writer feeds the bounded
name batch while the runner drains stdout, then closes stdin; never finish a
blocking stdin write before starting output reads. Enumeration stdout may stay
backpressured while a candidate batch is processed; stderr must still drain.
No widgets, models or live pane objects enter these threads. Before clearing
old results, preflight regex/literal inputs and glob arguments against empty
input and validate scope off Qt. Preflight processes are sequential and do not
traverse the root; neither mode launches a separate validation process per
candidate file. The runner collects capped plain row records locally and updates
a latest-count snapshot; it never sends individual rows to Qt. The plug-in
supplies a fast `get_text()` callback to PanelHandle.set_activity_status; it
formats only that latest immutable snapshot. The host owns the optional 200 ms
timer and elapsed-time refresh, including while output is quiet. No plug-in Qt
timer/signal is needed. Setting terminal text without get_text stops the timer;
clearing status or disposal also stops it before dropping the callback. One
generation-guarded completion transfers the final immutable tuple
after children are reaped; no row queue, duplicate full snapshot or growing
mutable list crosses to Qt. Do not use unbounded `communicate()`/line reads.

`Runner.start` invokes its completion callback on the supervisor worker thread
after cleanup and lease release. `SearchSession.completed` builds immutable rows
there, then each PanelHandle/show_table call marshals through the host's
`run_in_main_thread` dispatcher. Qt mutations remain on Qt; completion must not
hold a lock needed by the UI while making these synchronous handle calls.

The locked-engine spike showed provisional `match` records for binary files,
followed by `end.binary_offset`. Stage at most two bounded per-file groups until
their end records, then discard binary groups. On Stop/error/transport or global
cap termination, discard unfinished groups because their text/binary status is
unknown; already confirmed groups remain available. Account for staged and
confirmed rows together, including the eventual Table path/URL payload. A
per-file cap marks Limited only for a confirmed text file. Reparse-point roots
and oversized complete glob commands fail preflight before replacing results.

Stop invalidates further progress and requests one terminal Stopped snapshot;
Close/disposal invalidates all publication. Both kill every owned child; the runner reaps
children, closes pipes and releases its slot without a Qt-thread join. Exit 0
means matching output, 1 means no matches, 2 means error. Preserve collected
rows on read failures with incomplete/error status and bounded diagnostics;
startup, malformed output or oversized transport records stop the run. Never
label a killed or failed run Complete. Disposal also cancels pending status
updates and deferred modal presentation. A late exit cannot reopen results.
An OS metadata call already blocked on a network path cannot be interrupted by
a Python cancellation flag; reject its eventual result and retain the global
slot until that runner exits. Do not start replacement workers without a bound.

### Persistence and Distribution

Load settings only when invoked. Save the two pattern modes, recursion and validated
engine limits through the existing plain resource transaction service, under
`UserSettings`. Failed saves leave working controls usable with an error.
Defaults: filename Glob, content Literal, recursion true, encoding `auto`; engine
limits below. Patterns, results and local fuzzy filter remain session-only in
v1, avoiding content-query history on disk. No Registry writes or file watchers.

Migrate legacy booleans as specified under Three Pattern Modes. Bundled JSON
omits mode keys; code defaults apply only after reading user keys, so merged
defaults cannot mask legacy regex settings. Remove old keys on the next save.

The user supplies ripgrep through conda-forge in [environment.yml](../environment.yml)
and [conda-lock.yml](../conda-lock.yml). Conda owns dependency installation and
integrity; do not repeat package verification in the application or build helper.
The user's 2026-09-14 instruction supersedes the earlier custom version/hash and
packaging-manifest requirements. Leave 7-Zip acquisition and the lock unchanged.

Source runs/tests use `Path(sys.prefix) / 'bin' / 'rg.exe'` directly, without
metadata scans, version probes, hashes, downloads or PATH fallback.
[application.spec](../application.spec) adds that executable to `binaries`
under `resources/Plugins/SearchFiles/bin`; PyInstaller performs its normal
native dependency analysis. Its conda helper locates the package cache solely
to copy `info/licenses` as ordinary data. No custom validation or generated
integrity manifest remains. Frozen runs use the bundled plug-in `bin/rg.exe`.
Missing inputs fail through normal PyInstaller/process errors, not a second
dependency provisioning system. Build child PYTHONPATH includes the plug-in.
Frozen-artifact execution requires explicit authorization and is outside this
source implementation task; no freeze or portable execution result is claimed.

### Suggested Follow-ups

- **Line / Column** is the most useful optional third column, especially for
  repeated paths. Keep it in the payload/status initially; add a numeric sort
  key contract if this becomes a configurable column. File size/date would add
  I/O without helping identify a text match, so do not add them now.
- Match Case and Whole Word toggles, as in VS Code, are the next useful search
  controls; keep separate case settings for filenames and content.
- Include Hidden, an encoding menu, exclusion paths and saved search presets
  suit Total Commander/Double Commander-style searches of mixed file trees.
- Copy selected results/paths, optional surrounding-text preview and editor
  navigation to a line are useful later. Any history should be opt-in and
  clearable; replace/rename needs a separately reviewed preview/apply contract.

## Alternatives

- Modal tree plus preview: superseded by the requested Panel and flat Table;
  a separate context viewer is not needed to prove this reusable element.
- Progressive modeless results: useful for inspecting early hits but not the
  selected first-version workflow. Collect in the background, report status,
  then use a modal snapshot. The cost is waiting for completion/Stop before
  inspection; modal input blocking is intentional after that point.
- Modal during the scan: rejected because it would block the docked form and
  panes prematurely. Modal results via QDialog.open keep Qt's event loop alive;
  modality and synchronous/blocking execution are separate decisions.
- F1 migration: deferred by the user. A synthetic three-column/rename fixture
  proves reuse without changing the existing shortcuts dialog or filter.
- Public widgets/signals or plug-in-created menus: rejected by the Qt-free
  guideline. Host-owned services and plain handles hide Qt while reusing its
  existing components internally. Do not break/migrate the shipped widget APIs
  or other plug-ins as part of this increment.
- Row-wide file actions/path inference: rejected because ordinary cells and
  non-file tables must remain generic. Two optional column roles are sufficient
  now; multiple columns of each role or mixed per-cell kinds are deferred.
- Require a resolver for every table: unnecessary for real path text. Default
  lexical resolution with an immutable base handles ordinary consumers; a pure
  optional callback handles labels/payloads. Resolving against live pane/CWD or
  statting cells would introduce changing targets, I/O and UI stalls.
- Modal-only hosting: insufficient for the rename consumer's interactive Panel.
  Keep modality and close-on-navigation in the shared host, not in row data.
- Fable's reduced-first-increment recommendation: retain the approved modeless
  hosting and synthetic Panel-driven rename fixture because interactive Panel
  reuse is an explicit user requirement. Keep the already specified optional
  plain callback hooks and close policy; get_details also supplies the current
  search-result location label. Test ordinary-data hooks separately from path
  navigation, then test both window modes with the same internal host. Do not
  add further customization or silently defer these accepted capabilities.
- Navigation host protocol refactor: not needed now. An internal ToolWindow
  subclass supplies the exact existing QObject/signal/lifetime contract, while
  leaving legacy callers and public Qt-free handles unchanged.
- Derive count only from headers: less redundant, but does not expose the
  explicitly requested column count. Keep both and reject mismatches early.
- Plug-in-private QTreeWidget: quick to prototype, but duplicates filtering,
  styling and lifecycle for the upcoming virtual-rename consumer.
- QProcess parsing on Qt: possible with careful limits, but match-count limits
  alone do not bound its buffers or JSON decode time. Choose bounded pipe reads
  and parsing off Qt. Do not put Python backtracking regex on Qt or a thread
  that can hold the GIL indefinitely.
- Post-filter content hits by filename regex: simpler, but scans excluded files
  and can consume caps before eligible results appear. Pre-filter names instead.
- Enumerate/filter/batch for glob mode: rejected because native `--iglob` allows
  one traversal and avoids process/argv overhead in the common case. Native
  glob hidden-whitelist and directory-pruning semantics are documented, not
  emulated with fnmatch; the more costly pipeline is reserved for filename regex.
- Independently downloaded ripgrep: superseded by the user's locked conda
  dependency. One package source avoids divergent source/CI/release engines.
- ripgrep remains preferred over ugrep (archive/converter needs are deferred),
  Python content scanning (duplicates encoding/search behavior), bindings (ABI
  and packaging cost), or Windows Search (index-dependent coverage). Native
  process termination also supplies cancellation for regex and blocked scans.

## Runtime Effects

- Unused/disabled: discovery only; no feature settings read, scan, process,
  thread, watcher, timer or recurring signal subscription. Opening loads the
  small form/settings only; Search launches engine work and temporary status.
  The Table/model is allocated only for a settled nonempty result snapshot.
- Search: directory enumeration plus reads of eligible files; one supervisor,
  glob mode has one content process and one stderr reader after sequential
  preflight. Filename-regex mode has at most two children, two stderr readers
  and one temporary stdin writer, plus bounded eligibility metadata I/O per
  candidate/ancestor. Limit to one live search application-wide; a second request reports
  busy rather than queuing scans. Hold the slot until actual cleanup completes.
- Search retains at most one bounded result store off Qt, plus one latest-count
  progress record. At completion ownership transfers once to the modal snapshot;
  avoid copying all cell strings. The status timer runs only during a live search.
- Table filtering/sorting is in-memory only, with time-sliced fuzzy projection
  and stale-query rejection; no per-keystroke workers. Provider code must be
  fast. Retained result memory is released on Table close/session disposal.
  F1 has no new initialization, timers, allocations or behavior from this task.
- With both path roles None, no resolver, path conversion, navigation work or
  filesystem probe is performed. With roles enabled, resolution is lexical and
  occurs only on explicit menu/activation. Clipboard copying requires no I/O.
  Go To performs bounded asynchronous host navigation, not background scans.
- Modal and modeless Tables allocate the same bounded model/snapshot and differ
  only in host focus/input/lifetime policy. Modeless refresh is explicit, not a
  polling job. Menus retain only bounded captured action data and are released
  on dismissal/state change. No new process/thread is needed for either mode.
- The Qt-free facade marshals handle calls through the existing dispatcher;
  it adds no recurring jobs. A modeless provider update temporarily retains old
  and candidate snapshots for atomic replacement: each must meet the 10,000-row/
  16 MiB limits, with at most one replacement being validated at a time. Reject
  oversized/infinite providers at the bound, preserving the prior snapshot.
- The nested three-/four-row Panel consumes roughly 120/155 logical pixels of
  file-pane height while open; layout reflows only on size/font/style changes.
  No recurring geometry timer, extra dock, or layout activity while closed.

| Bound | Initial value / enforcement |
| --- | --- |
| Retained result rows | 10,000 matching lines; stop with Limited at cap |
| Matching lines per file | 200 via `--max-count`; flag potentially incomplete coverage at cap |
| Retained display/payload text | 16 MiB combined, counting shared text once; cap before publishing; row metadata is additionally bounded by row count |
| Snippet | 512 code points centered near first match; visible truncation, at most 128 retained highlight ranges per row |
| File size | 50 MiB eligibility cap, not a bound on files changing during search or on child RSS |
| Pattern / header length | 4,096 / 128 code points; validate before work |
| Candidate batch (filename Literal/RegEx) | At most 128 paths and 256 KiB of path data; further split for Windows argv bound; no inventory in glob mode |
| One encoded JSON record | 1 MiB; kill and report oversized result before parsing, not silent loss |
| Read chunk / stderr tail | 64 KiB / 64 KiB per live child |
| Producer-to-Qt delivery | One latest progress record and one immutable capped terminal snapshot; no incremental row queue |
| Status refresh | At most 5 Hz while searching; terminal events bypass throttling; no timer after settlement/disposal |
| Qt projection work | Target 8 ms per event-loop turn for filter projection; measure initial snapshot validation/model population and sorting separately |

These are transport/result bounds, not a hard process-memory guarantee: ripgrep
must buffer long source lines and regex state. Record host and child peak RSS,
including oversized/minified files. An 8 ms target must be measured; a single
unbounded decode, provider call or full sort cannot be made safe by a timer.
Stop/close must remain responsive while cleanup proceeds asynchronously. No
background activity persists after cleanup, and no results are written to disk.
Delivered size increases by the verified executable, licences and small SVGs.

## Tests

### Focused Commands

Implementation must add the planned `TableIT` and `SearchFilesIT` classes
to the existing Qt harness, unit coverage to the existing UI tests and one
feature unit module, plus `test_search_files_engine.py` as the real-engine
module. Its `test` prefix matches build.py's `test*.py` discovery; do not leave
the engine checks only in a manually invoked smoke module. These names are planned, not
claims that tests already exist. From the repository root, with the existing
configured Python environment and provisioned pinned ripgrep:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONPATH = @(
    'src/main/python', 'src/unittest/python', 'src/integrationtest/python',
    'src/main/resources/base/Plugins/Core',
    'src/main/resources/base/Plugins/Favorites',
    'src/main/resources/base/Plugins/CalculateFileHash',
    'src/main/resources/base/Plugins/SearchFileFuzzy',
    'src/main/resources/base/Plugins/SearchFiles'
) -join ';'
python -m unittest fman_unittest.test_ui_elements fman_unittest.test_portable
python -m unittest fman_unittest.test_search_files
python -m unittest discover -s src/integrationtest/python -p test_search_files_engine.py
python -m unittest fman_integrationtest.test_qt.TableIT fman_integrationtest.test_qt.SearchFilesIT
python -m unittest fman_integrationtest.test_qt.PublicUiIT
python -m unittest fman_unittest.impl.plugins.test_plugin fman_integrationtest.impl.plugins.test_plugin
python -m unittest fman_integrationtest.test_qt.QuickListIT fman_integrationtest.test_qt.DockedPanelIT
python -m unittest fman_integrationtest.test_qt.PanelIT
python -m unittest fman_unittest.impl.test_status_bar
python -m unittest fman_unittest.test_release_support
```

Run the narrowest relevant test immediately after each first substantive code
edit, then the commands covering the changed surfaces. Extend existing suites
where suitable, rather than scattering helper files. Do not automatically run
the complete `python build.py test`, `clean` or `freeze`. Missing ripgrep is a
reported engine-validation blocker, not a successful skipped acceptance gate.
Junction/ACL cases may capability-skip with reasons; require a capable Windows
manual run before claiming those behaviors verified.

### Required Coverage

- Facade: exact show_table/get_rows/num_columns/columns_header keywords, plain
  TableRow/TableAction and descriptor validation, TableHandle/PanelHandle with
  no QObject/widget/signal/Qt enum exposure, inactive-owner errors and handle
  calls from command/worker threads. Verify callback thread serialization,
  callback/provider exceptions, no calls after owner unload and reference release.
  Reuse loader-owned UiController registration without invoking show/build;
  test owner-local icon resources, cross-owner/pane handle rejection and legacy
  registration/construction compatibility. Review/source-test the new plug-in
  for zero Qt/private-host imports, subclassing or raw widget/signal access.
- Loader/resource regression: _load_classes assigns the correct resource_root
  to a UiController subclass with no build override and require_owner works
  without invoking show/build. UiOwner() stays compatible. Missing roots,
  missing assets, cross-root/path traversal/reparse escapes and unload/reload
  cannot use another plug-in's icons. Registration performs no asset I/O;
  source/frozen roots and owner-scoped cache invalidation are exercised.
- Table: exact `num_columns`/`columns_header` keyword construction, provider
  call timing/count, wrong schema/header count, duplicate IDs,
  invalid cells/spans, exception atomicity, snapshot refresh, empty results,
  caps and source/current identity after updates. Three-column synthetic input
  proves the reusable element is not hardcoded to search's two columns.
- Fuzzy match either column, stable ranks/ties, explicit sorting, clear filter,
  hidden current fallback, accented text, casefold expansion, non-BMP UTF-16
  highlights; content-match highlighting remains distinct from fuzzy highlighting.
- Table interaction: no command/clear buttons, row-action widgets or checkboxes
  in the result content; search-panel buttons remain available as designed.
  Left click selects row and current column only. Double-click on a file cell
  highlights the file in its parent; folder cell enters the folder; ordinary
  cell does nothing without a callback. Right-click uses exactly the pointed
  cell's menu, never a different path cell in the same row. Empty space/headers
  do not operate on a prior row. Sorting preserves logical column roles.
- Path unit tests: both roles None, one/both distinct roles, wrong types/bool,
  negative/out-of-range/equal indices, zero resolver calls for ordinary tables.
  Default full cell text versus elision, drive/UNC absolute paths, relative paths
  with/without base, frozen pane base after navigation, explicit search_root
  overriding a moved pane, dot segments, spaces and Unicode, empty text, NUL,
  URLs and ambiguous drive/root-relative rejection. Custom absolute/None return,
  wrong type/relative result/exception. No stat, symlink resolution, cwd lookup,
  environment expansion or resolver calls during selection/filter/sort/painting.
- Menu/keyboard: Menu key/Shift+F10, Ctrl+F, Enter/keypad Enter and Left/Right,
  normal filter text editing/menu, Escape-menu-then-dialog behavior and native
  window close. Verify captured-cell/path targeting across sort/filter/refresh,
  disposal and queued callbacks; no stale action or implicit command execution.
  The path menu has Copy Path / Go To only without custom actions; no Open File
  or Ctrl+Enter association launch. Copy resolved paths without existence I/O.
  With no pane Copy works but Go To is disabled. Missing/access/wrong-type errors
  keep results; successful file/folder navigation uses the captured pane and
  requested close policy. Reject duplicate/stale navigation. Validate bounded
  plain custom-action records, captured callback arguments and reserved IDs.
- Navigation adapter: use the real session.navigate with internal TableWindow
  in both modalities, not a stub that bypasses its window dependencies. Verify
  QObject timer parenting, busy reset on success/error/timeout, queued delivery,
  disposed cancellation and owner/pane close before completion. Table close
  retains the Panel; Panel close tears down results. Repeat alongside existing
  ToolWindow/PaneToolWindow navigation tests without signature changes.
- Qt: no Table or visible tool window during search; panes remain interactive;
  exactly one modal opens only after the terminal snapshot and child cleanup.
  Parent-window input blocks while modal open, Qt processing does not; Closing
  results restores Panel focus/options, while panel/session disposal cancels all.
- Cover zero hits, Stop with/without rows, limits, read errors, validation errors,
  inactive-window/other-modal deferral and disposal while deferred. No duplicate
  completion, stale status, late modal, nested modal, focus theft or timer leak.
- Deferred-trigger regression: WindowActivate, applicationStateChanged and
  blocking-modal Hide/Close/Destroy/finished each queue a coalesced retry that
  rechecks activeModalWidget after the event. Test closing a modal without an
  application activation change, replacing one modal with another, inactive
  invoking windows and disposal with a retry queued. Subscriptions disappear
  after presentation/cancel; no periodic polling remains.
- Construct the internal Table in a plain QDialog without a pane/UiOwner; the
  public service always uses the registered owner. Close/destroy
  during queued projection and confirm no late delivery or callback retention.
  Exercise fuzzy-off focus and modal Tab/Shift+Tab containment. Panel-only mode
  must never raise its hidden coordinator; default tool/QuickList behavior stays
  unchanged. Both modal=True/False return a non-Qt handle immediately; no nested
  dialog execution loop. Callback dispatch/model/delegate calls stay on Qt.
- Status integration in SearchFilesIT: initial Validating/Searching text,
  <=5 Hz counter updates, quiet-output activity, immediate terminal status and
  owner-only cleanup. Legacy messages and extended pane summaries coexist; the
  activity label still works with pane statistics disabled and starts no scans.
- Panel facade/renderer: plain descriptors, snapshot/update and callbacks,
  unique IDs/types, programmatic update without callback echo, read-only labels,
  enable/disable state, cancellation token on close/unload and resource errors.
  Three-/four-row host-owned composition at minimum window size,
  dock height and visible pane area at each DPI; default checkable behavior,
  explicit action-mode clicks, no action value binding, invalid `checkable`
  type and existing Favorites/JsonSettings toggle behavior.
- TableIT includes `test_directory_pane_styles_unchanged`: render the file pane
  before/after Table construction in both themes, comparing selected/current
  rows, first/last-column padding and inline rename. Exercise Table's own
  normal/selected/focus/has-children/open states and header rules by object name.
- Rename-preview fixture: modeless Table with a Qt-free Panel; editing inputs
  refreshes virtual names while panes/Panel stay interactive. Source column has
  a file role, proposed column none; a proposed existing-looking name cannot
  navigate. Preserve stable IDs/current column/query/scroll and reject stale
  computations. Go To retains preview and captured base, unless explicit close
  policy overrides it. Modal default closes only on success; override false
  keeps it open. Focus bridges only in modeless mode; closing Table keeps Panel,
  closing/replacing Panel/unloading owner closes both. No actual rename or I/O
  for preview computation/filtering. Plain-data fixture with both roles None
  proves non-file activation/menu callbacks and no navigation dependency.
- F1 regression only: existing implementation, grouping, tabs, substring filter,
  binding rules and visual treatment remain unchanged after new Table styles.
  Do not add ShortcutsTableIT or make F1 migration an acceptance dependency.
- Engine: Literal/Glob/RegEx cross-product for both fields, empty filename and blank
  content, meaningful spaces, glob exclusions, literal semicolons in regex,
  unsupported/invalid regex, names repeated under different parents, Unicode,
  patterns beginning `-`, quoted paths, no accepted files and argv splitting.
- Glob fast path: one root traversal after preflight regardless of file count;
  positive masks first/exclusions last, empty and exclusion-only masks, native
  glob syntax errors, matching directory exclusions, positive-mask hidden
  overrides, size cap, recursion and oversized combined argv rejection. Assert
  no candidate enumeration or per-file process launches in this mode. The real
  engine fixture includes `nested/does-not-match-mask/hit.txt` with `--iglob
  '*.txt'`: positive masks must still descend directories that do not match the
  file mask, finding nested hits; recursion-off must omit the nested hit.
- Verify filename-regex filtering excludes files before content reads; validate
  NUL input record mapping, recursive/nonrecursive scope, hidden files, junction
  loops, files replaced by directories, binary detection, no-match exit 1,
  read errors/exit 2, missing binary and malformed/oversized/fragmented JSON.
- Compare hidden/size handling for directory versus explicit operands in the
  locked rg build. In filename-regex mode, test plug-in rejection of oversized,
  hidden, nonregular and reparse candidates/ancestors even when the child ignores
  traversal filters. Record eligibility skips separately from read errors.
- UTF-8, UTF-16 BOM and configured Windows-1252 accented text, CRLF anchors,
  multiple/zero-width submatches, snippet cropping and correct character offsets.
- Cancel during validation, enumeration, regex, content, full stdin/stdout/stderr
  pipes, final snapshot transfer and navigation; no stale dialogs, deadlocks, zombies or terminal status overwritten by
  late exit. Repeated open/close leaves process/thread/notification counts stable.
- Settings defaults, legacy-mode migration, corrupt settings/save failure, independent modes and recursion,
  no persisted patterns/results and no feature work while unused/disabled.
- Build: direct conda/bundled path selection without verification I/O; spec wiring
  for binary, license data and normal native dependency analysis; no custom
  downloader/version/hash/manifest path; bundle resources/SVGs, public exports/private-import guards,
  unchanged F1 and legacy Quicksearch/QuickList regression checks when touched.
- Run the focused `unittest discover` command above and assert the engine test
  count is nonzero. The module must also be discoverable through build.py's
  existing integration root/pattern without special registration.

### Performance and Manual Checks

Use a reproducible local 100,000-file fixture with recorded sizes, matching-file
distribution and warm/cold cache conditions. Measure both filename modes: time
to first engine hit (not displayed), total scan time, completion-to-dialog
latency, host/child peak RSS and process starts. Target initial status/Stop
feedback within 100 ms, activity refresh within 200 ms, and final-snapshot-to-
visible-dialog latency within 250 ms for the 10,000-row fixture. Browsing waits
for completion or Stop; no one-second first-visible-result promise. Target fuzzy
updates within 100 ms and projection slices near 8 ms. Test quiet/slow/long-line
producers separately and record any initial model work exceeding the Qt budget.
For glob mode, compare the runner with the equivalent single rg invocation;
record startup/parse overhead and ensure process count does not scale with files.
For filename regex, record candidate/ancestor metadata cost and extra batch starts.

Manually compare the unchanged F1 reference and the content-search Table in both
themes at 100/150/200% DPI and small/large
windows: headers, widths, long paths/snippets, every tooltip, toggle/focus states,
Alt+F7, cell-sensitive Enter/double-click/right-click, keyboard menu access,
Escape, status visibility, pane focus while scanning and modal focus return.
Also exercise modeless synthetic rename/Panel edits, focus traversal and retained
window on Go To. Confirm Snippet/proposed-name cells do not navigate. Exercise real
startup, toggle persistence and two-window search contention with isolated
temporary UserSettings. When a portable artifact is available or packaging is
explicitly authorized, repeat search/Stop/navigation with no system Python,
ripgrep or development PATH; verify licences/assets and no runtime downloads.
Unrun packaging/native checks remain documented release follow-ups, not inferred
passes. Frozen execution is outside this source task as selected in review.

## Implementation Steps

1. Review this revised contract before implementation. Use conda-forge's installed
  executable directly, without changing or verifying the environment/package.
  Add a discoverable narrow real-engine spike for
  glob fast-path semantics, filename-regex record mapping, directory versus
  explicit-file size/hidden handling, binary/junction behavior and cancellation.
  Explicitly prove positive `--iglob '*.txt'` masks descend non-matching
  directories to nested eligible files, while recursion-off omits those hits.
  Record results and resolve failures before UI integration.
2. Add immutable row/action/control records and pure schema/default path-resolver
  logic with focused UI unit tests. Add the internal model/view, scoped styles,
  fuzzy sorting/current-cell logic and host-owned menus; run TableIT including
  directory-pane regressions. Do not export the widget or Qt signals.
3. Add show_panel/show_table and plain handles through fman.ui, reusing registered
  owners/dispatch/docking internally. Add UiOwner.resource_root and the explicit
  ExternalPlugin._load_classes constructor hook; retain UiController subclasses
  as owner carriers without a build override. Host results in TableWindow,
  preserving session.navigate unchanged, and implement the named deferred-
  presentation triggers. Verify Qt-free calls,
  cancellation/status, modal/modeless focus/close policies and callback failures
  using PublicUiIT/TableIT plus adjacent Panel/QuickList/loader tests. Prove
  ordinary-data and modeless virtual-rename reuse with a Panel-driven refresh.
  Keep F1 independent; check F1 and file panes for style regressions only.
4. Implement the glob single-traversal and regex bounded-pipeline runners,
  explicit-file eligibility guards, parser, bounded result collector and
  generation cancellation with one terminal snapshot and throttled counters;
   run pure unit and real-ripgrep tests before connecting results to Table.
5. Connect the plug-in using only plain form descriptors/services/handles and
  on-demand settings transactions. Licensed icon rendering, panel-only layout,
  action-mode controls and status timers remain host-owned. Present the settled
  snapshot with file_path_column=0, captured base, default resolver and modal=True.
  Run SearchFilesIT/engine tests and Qt-free import/API guards plus focused
  status/Panel/dock regressions. No plug-in Qt construction, signal access or
  private navigation/menu wiring.
6. Complete build/resource wiring and document commands, pattern dialects,
   limits, settings and the provisional API in README/plug-in docs. Add the
   implemented application change to CHANGELOG, not this planning revision.
7. Run the scoped performance/native/available portable checks above; record
   results and pending gates. Only then apply the repository's completion rules.
8. Address the Review Follow-ups below before completion.
9. Add canonical modes and content-glob conversion in the existing engine; run
   native pattern/escaping/line-boundary tests before UI integration.
10. Add the bounded Qt-free Choice descriptor and exclusive icon group; test
  selection, callback counts, atomic updates and disabled state.
11. Wire the three modes, pinned icons and settings migration; run native mode
  persistence/layout/search smoke and update usage/API documentation.

### Review Follow-ups

Source: Claude Fable 5.1 implementation review, 2026_09_14. Tick each item when
done and reference the commit or record that resolves it.

- [x] Keep the Panel form locked while a completed snapshot awaits deferred
  presentation. `SearchSession.completed` in
  [search_files/__init__.py](../src/main/resources/base/Plugins/SearchFiles/search_files/__init__.py)
  now re-enables the form on Table close, using `on_closed`, and rejects repeat
  Search while a Table is alive. Stop disables when the runner settles.
- [x] Add a `SearchFilesIT` case: search completes while the main window
  is inactive; Search stays disabled throughout deferred/modal results. Tested
  closing both before and after presentation.
- [x] Align the Design text with the implemented deferral mechanism.
  `TableWindow.present` in [facade.py](../src/main/python/fman/impl/ui/facade.py)
  installs an application-wide event filter plus `applicationStateChanged`
  while pending. The deliberate superset, coalesced work and subscription cleanup
  are now documented in Status Bar and Completion.
- [x] Document in Design that the application-wide search lease is the
  `try_claim()` slot of the named `Resource('SearchFiles runner')`.
- [x] Document in Design that the Runner completion callback executes on the
  worker thread and marshals each handle call through `run_in_main_thread`.
- [x] Decide the frozen-artifact gate: recorded as outside this source task;
  portable execution remains a release follow-up requiring explicit authorization.
- [x] Once the gate is decided, move this document to `Done/` and update the
  `Plan.md` index.

Resolution record: [Review Follow-up Validation](#review-follow-up-validation).

## Acceptance Criteria

- Both fields expose exactly-one-selected Literal/Glob/RegEx icon groups with
  tooltips. Defaults and old settings migrate without changing prior behavior.
  Literal searches substrings; content Glob matches whole lines with the
  documented bounded converter, and invalid sets/ranges fail preflight.
- Qt-free show_table accepts a population callable, explicit column count and
  headers using the exact names `get_rows`, `num_columns`, `columns_header`;
  validates their contract; supports snapshot refresh and fuzzy filtering;
  and passes content-search, ordinary-data and modeless virtual-rename fixtures.
  Plug-ins receive only plain records/handles and supply ordinary callbacks;
  neither the new Panel nor Table API leaks Qt or requires a widget build hook.
- file_path_column/folder_path_column default to None, validate zero-based
  distinct indices and affect only their cells. The default resolver uses full
  text and a fixed base without I/O/CWD; custom callbacks remain optional.
  Both None means no path behavior. Each Search uses its own captured root;
  the idle form follows only its visibly identified invoking pane.
- Results contain no explicit buttons, including a filter-clear button. Single
  selection/left click never operates on a file. Double-click/Enter on file cells
  highlights the file in its parent, and on folder cells enters the folder.
  Ordinary cells have no built-in action. Right-click/current-cell keyboard menu
  offers host-owned Copy Path / Go To for resolvable path cells only; captured
  cell/target and generation guards prevent stale actions. No extra initial
  search menu commands, Open File or Ctrl+Enter application launch.
- F1 remains independent and unchanged, including its existing substring filter.
  It is a visual reference, not a migration target or implementation gate.
- The internal Table works without a pane/producer; the public facade enforces
  owner lifetime. Modal/modeless focus, thread dispatch, errors and disposal are
  tested. Scoped Table styling leaves F1 and file-pane visuals
  and inline rename unchanged.
- TableWindow satisfies the actual session.navigate timer/busy/dispatch/disposed
  contract without a public signature change. Resource ownership is explicitly
  loader-supplied and remains lazy at registration. Deferred presentation uses
  the named Qt events with activeModalWidget checks and removes its subscriptions.
- The docked search Panel remains usable with both file panes during scanning;
  status-bar activity reports progress. No result window/Table appears until
  a terminal snapshot is ready. Then a window-modal Table shows the snapshot
  without progressive population. Dismissing results returns to the Panel.
- modal=False leaves Panel/panes interactive; explicit refresh preserves cell
  identity and query. Default Go To closes modal windows only after success and
  retains modeless ones; close_on_navigate overrides are tested. Navigating does
  not retarget the base or preview source. Panel disposal closes its Table.
- Both pattern fields have independent three-option SVG mode groups; recursion is
  also an SVG toggle. Every button has a meaningful tooltip/accessibility name.
- The plug-in supplies plain control descriptors/resource names; the host renders
  the nested form with measured dock height and no clipping. Search/Stop are
  noncheckable. Legacy widget exports/defaults/Favorites remain compatible.
- Search produces exactly File Path/Snippet columns with matching-line rows,
  highlights and correct navigation payloads. Results visually follow F1;
  fuzzy filtering reads no files and changes neither search options nor results.
- Filename globs/regex, literal/content regex, recursion, Unicode and configured
  encoding match the documented semantics. Invalid input is actionable and
  preserves previous results. No automatic PCRE2 fallback or silent omitted hits.
- Glob mode uses one content traversal after preflight; only filename regex
  uses candidate batching. Native glob hidden overrides are documented; regex
  explicit-file hidden/size eligibility is enforced independently of rg flags.
- Status, Stop, errors and limits remain responsive and truthful; late progress
  or completion cannot alter another generation or open an unwanted modal.
  No unbounded transport, status-message clobbering or idle work. Zero hits and
  disposed searches never open a modal; partial snapshots are clearly marked.
- Navigation closes the results dialog only on tracked success and retains the
  Panel. Path actions are available through the cell context menu and keyboard
  equivalents. Modes and recursion persist in UserSettings;
  result text and queries do not. No actual rename/replace or archive traversal.
- Scoped unit/Qt/engine/performance checks pass; additional native/portable checks
  are run or explicitly recorded as release follow-ups. Packaging includes conda's ripgrep and
  required SVG/licence assets, with no runtime network or shell dependency.
- Real-engine tests are found by the normal `test*.py` discovery. Source and
  package builds use the locked conda ripgrep dependency; no duplicate downloader
  or reliance on system PATH. PyInstaller handles native dependencies normally;
  custom executable/package verification is excluded by the user's instruction.
- All selected SVGs have verified open-source licences at their pinned source
  revision, with applicable ISC/MIT notices retained in the delivered product.

## Reviewers

### 2026_09_12 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context window: Not exposed by host
- Outcome: Initial ripgrep-backed streaming search design created after engine
  alternatives were evaluated.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Revised around the requested Panel and reusable provider-based Table;
  specified two-column results, true fuzzy filtering, SVG toggles/tooltips and
  virtual-rename reuse. Replaced private modal hosting and unbounded Qt parsing;
  scoped advanced controls separately and added explicit engine/performance
  gates. Planning only; no application implementation or runtime validation.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Applied requested `num_columns`/`columns_header` names; made F1 a
  required shared-Table/fuzzy-filter consumer while retaining help-only behavior.
  Confirmed open-source SVG licensing requirements and clarified ripgrep versus
  local fuzzy matching. Plan revision only; implementation remains pending.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved in principle; revision requested before implementation.
  Verified ripgrep flags (`--no-follow`, `--no-mmap`, `--crlf`, `--null-data`,
  `--files --null`, `--max-depth 0`, `-e`, `-j`) against upstream flag
  definitions and F1/host claims against `fman/impl/shortcuts.py`,
  `fman/impl/ui/panel.py`, `fman/impl/ui/session.py` and `styles.qss`.
  Concerns: (1) the glob (regex-off) filename mode should use one `rg`
  traversal with `--iglob` masks (exclusions last) instead of the
  enumerate/`fnmatch`/explicit-file-batch pipeline, which multiplies process
  starts and argv splitting for the common case; keep the pipeline only for
  filename regex, and verify in the spike whether explicit-path operands bypass
  `--max-filesize`/hidden filtering so the plug-in enforces the size cap itself.
  (2) `Panel` is a single horizontal `QHBoxLayout`; the two-row form plus
  scope/action row must be specified as a nested child widget added through
  `Panel.add`, and its dock height cost stated. (3) `IconButton` is always
  checkable; non-toggle actions need an additive `checkable` constructor
  option or an explicit statement, not inherited `setCheckable(False)` calls.
  (4) Table must not require a `UiOwner`/`PaneToolWindow` so the host F1 dialog
  can construct it; `PaneToolWindow._focus_from_panel`/`on_shown` special-case
  QuickList and need a Table-aware focus path. (5) Global `QTableView::item`
  rules in `styles.qss` (including the file-pane `:has-children`/`:open`
  padding hack) will apply to Table; scope Table rules by object name and add a
  directory-pane regression check. (6) The engine test module
  `fman_integrationtest.search_file_content_engine` is not matched by the
  `test*.py` discovery pattern used by `build.py test`; rename or justify.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Addressed all six Claude Fable 5.1 findings in the design and test
  gates. Aligned distribution with the user's locked conda ripgrep dependency.
  Source and document checks only; engine spikes, Qt behavior and packaging
  remain unverified implementation gates. Prior reviewer records are unchanged.

#### Feedback Resolution

1. Common filename-glob mode now uses one rg traversal with positive `--iglob`
   masks before exclusions. Only filename regex uses enumeration/batches.
   Explicit-file hidden/size checks are worker-owned; the spike must compare
   flags on directory/explicit operands. Native glob hidden overrides are
   documented instead of inheriting the earlier unconditional-hidden claim.
2. The multirow form is a nested QWidget/grid passed to Panel.add, with explicit
   three-/four-row dock-height budgets and required minimum-size/DPI checks.
3. IconButton gains additive `checkable=True`; command actions pass False,
   existing toggle defaults remain, and action settings bindings are rejected.
4. Table is independently constructible in QDialog, with widget-owned cleanup.
   ToolWindow.on_shown and PaneToolWindow._focus_from_panel receive explicit
   Table branches; both directions, initial query and QuickList are tested.
5. Table styles use named wrapper/view selectors, override all inherited item
   states and do not reuse file-pane State_Children/State_Open semantics.
   A directory-pane selection/padding/inline-rename regression is required.
6. The real-engine module is named `test_search_file_content_engine.py`, with
   an exact focused discovery command and a nonzero discovered-test gate.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Applied the user's status-bar-first, modal-after-collection workflow.
  Search remains asynchronous and bounded; results open only after settlement,
  with explicit partial/zero-hit/cancel behavior and owner/generation guards.
  Proposed opt-in panel-only hosting, owned status activity and modal content
  hosting after checking UiController and MainWindow message handling. Deferred
  append_rows, modeless Table focus branches and F1 migration from prior reviews;
  F1 stays unchanged. Retained the other engine, icon, composition, styling and
  discovery resolutions. Planning only; runtime/engine/packaging gates remain
  unverified, and prior reviewer records are preserved.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Applied the user's buttonless Table constraint, removing the results
  footer and filter-clear button. Defined single-row selection, left-double-click
  activation, consumer-owned right-click menus, keyboard equivalents and stale
  menu guards. Content search supplies Go to File, Open File, Copy Full Path and
  Copy Snippet; search-panel controls and F1 remain unchanged. Planning only;
  interaction tests are specified but have not been implemented or executed.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revised to Qt-free show_table/show_panel services, plain handles and
  callbacks, with Qt/menu/navigation/lifetime ownership entirely in the host.
  Added optional file/folder column indices, default lexical resolution with a
  captured base, custom resolver support and cell-specific Copy Path / Go To.
  Included modal/modeless hosting and a Panel-driven synthetic rename fixture;
  content search remains modal, Snippet/proposed cells remain ordinary, and F1
  is unchanged. Reuse existing loader-created UiOwner registration without a
  widget build hook. Supersedes public QWidget/signals and row-wide menus in
  prior reviews; preserves history and engine/distribution decisions. Planning
  only: runtime, engine and packaging gates remain unverified.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved for implementation after two named design gaps are filled;
  one scope recommendation is non-blocking. Verified: all six earlier findings
  are resolved in the operative text; `ripgrep` is declared in
  `environment.yml` and locked as win-64 15.2.0 `h18a1a76_1`; every test module
  referenced in Focused Commands exists or is planned with a `test*` name;
  the status-bar, `--iglob` precedence, `--null-data` stdin and `--max-depth`
  claims are consistent with the host code and upstream flag definitions.
  Gaps to state in Design before coding: (1) `fman.impl.ui.session.navigate`
  requires a ToolWindow-shaped `window` (`busy`, `set_busy`, `post`, `alive`,
  `owner`); the host results QDialog must implement that surface or `navigate`
  must accept a small host protocol - name which. (2) Associating a plug-in
  resource root with its `UiOwner` for descriptor icons is a new loader hook in
  `ExternalPlugin._load_classes` (for example `UiOwner.resource_root`), not
  reuse; name it, and decide whether a `UiController` subclass with no `build`
  is the intended owner carrier or a marker base should be added. Also list in
  the step-1 spike that positive `--iglob` masks still descend non-matching
  directories, and name the deferred-presentation trigger (invoking window
  `WindowActivate`/`applicationStateChanged`, re-checking `activeModalWidget`).
  Recommendation: the facade now carries ~17 `show_table` parameters, modeless
  hosting, custom menus/activation/details hooks and a rename fixture that the
  only real consumer does not use. Consider shipping increment 1 with
  `show_panel`, modal `show_table`, path roles, default resolver, refresh and
  filter plus the ordinary-data fixture, and gating modeless hosting,
  `get_menu`/`on_activate`/`get_details`, `close_on_navigate` and the rename
  fixture on the rename consumer plan. This roughly halves the Qt test matrix
  without changing the public names. Planning review only.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Resolved Fable 5.1's two named integration gaps and two additional
  clarifications in the operative design. Selected internal TableWindow inheriting
  ToolWindow for unchanged session.navigate, including QObject timer parenting
  and disposed cancellation. Named the additive UiOwner.resource_root loader
  hook and retained UiController without build as the owner carrier. Specified
  deferred-presentation events/rechecks and the positive-glob nested-descent
  spike. Retained the approved modeless/callback/rename-fixture scope rather than
  deferring user-required Panel interaction. Added focused gates; existing
  reviewer records are unchanged. Source/document review only, not runtime or
  engine verification and not an implementation-completion claim.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Applied verified runtime findings: binary matches require bounded
  end-marker staging; explicit hidden/oversized operands bypass native flags;
  the search lease must survive module unload/reload in the host Resource.
  Kept the approved modal/modeless and cell-specific API. Native source smoke,
  focused regressions and packaging-input checks pass; full acceptance remains
  pending the specifically unrun checks below. Historical records preserved.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Addressed Fable 5.1's deferred-form and documentation follow-ups.
  Selected results-close unlocking; documented the application-wide pending
  filter, named Resource lease and worker-thread completion dispatch. Applied
  the user's direct conda-forge policy, removing custom ripgrep verification.
  Frozen execution is outside this source task and remains a release follow-up.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Applied UI feedback: contiguous fuzzy preference belongs in the shared
  matcher; retain literal content semantics. Selected aligned capped fields and
  idle root following with a fixed pane hint, per the user's simplified scope.
  No source-pane toggle, cross-pane navigation or F1 migration was introduced.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Reviewed the requested three-mode extension and its testable contract.
  Approved whole-line content globs, substring Literal mode, native filename
  globs, a reusable exclusive Choice control and backward-compatible settings
  migration. Selected explicit conversion after checking standard-library
  translators against ripgrep syntax. Implementation validation follows below.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Reviewed the aligned search-control column and red Stop text with
  reduced disabled opacity. Retained the existing Action API per user feedback;
  styling belongs to the host. Required actual window widths, unclipped labels
  and rendered color-state checks; no engine or persistence changes.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Selected the user's equal-size 3x3 icon layout over right-aligned
  unequal rows. Added 3-pixel gaps, a larger tooltip-only pane indicator and idle
  Stop no-op. Kept color host-owned; approved layout-only validation for this pass.

## Implementer

### 2026_09_14 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented Qt-free Table/Panel services, plain descriptors/handles,
  loader-owned SVG resources, modal/modeless hosting, lexical cell-path actions,
  status activity, bounded ripgrep worker/pipelines, search command/settings,
  packaging inputs, usage/API documentation and scoped tests. Native source
  startup/search/persistence/file navigation passes at 100/150/200% scaling.
  The task remains Pending; no portable build or full manual acceptance claim.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review; approved with follow-ups recorded as
  Implementation Step 8. Re-ran independently: the plan's focused set plus
  adjacent suites (114 tests, OK, one privilege skip), engine discovery through
  `discover -p test_search_file_content_engine.py` (exit 0) and the native
  source smoke at 100% (PASS, dock 145/111 px, search-to-visible 207 ms).
  Verified against the approved contract: exact `show_table`/`show_panel`
  signatures; plain handles marshalled through `run_in_main_thread`;
  `UiOwner.resource_root` assigned in `ExternalPlugin._load_classes`;
  `TableWindow(ToolWindow)` satisfies the `navigate` window surface; scoped
  `#results-table-view` styles with the directory-pane regression; single
  `--iglob` traversal in glob mode; bounded NUL/JSON pipelines with root
  containment, argv-limit checks and `--` before operands; no shell, no PATH
  lookup, hash-verified `rg.exe`; licence/manifest packaging inputs and
  `PyQt5.QtSvg` hidden import; README, plug-in README and CHANGELOG updated;
  F1 untouched. Deviations from the plan (both low severity): Search is
  re-enabled while a snapshot awaits deferred presentation, and deferral uses an
  application-wide event filter rather than the specified window/modal filters.
  Filename-regex mode's ~9x cost and ~900 process starts per 100k files are
  documented, not hidden. Frozen-artifact execution remains an explicit gate.

### 2026_09_14 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Kept Search/options locked through deferred/modal results and unlocked
  them on close; guarded repeat actions and added inactive-window regressions.
  Simplified source resolution and spec inputs to use installed conda ripgrep
  directly, with license data but no download/version/hash/manifest machinery.
  Focused follow-up tests: 32 run, 31 passed, one expected privilege skip. Native
  source smoke passed, including tracked navigation and form unlocking.

### 2026_09_14 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Updated the shared fuzzy matcher, styled field alignment/width caps,
  public pane-path subscription, fixed pane hint and idle root synchronization.
  Documented public APIs and literal-content examples. All 57 focused tests and
  the extended native source smoke passed; screenshots inspected at 640/960 widths.

### 2026_09_14 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Implemented Literal/Glob/RegEx modes, bounded whole-line glob
  conversion, filename Literal filtering, saved-mode migration, reusable Choice
  groups and pinned text/asterisk icons. Focused tests: 59 run, 58 passed, one
  symlink-privilege skip. Native mode/layout/persistence/search smoke passed.

### 2026_09_14 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Aligned recursion/Search/Stop with the pattern-mode buttons and
  themed Stop red with faded disabled text, without extending the plug-in API.
  All 50 focused tests and the native smoke passed at actual 640/960/1440 widths;
  the dock stays 111 logical pixels tall. Added geometry and color regressions.

### 2026_09_14 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Implemented equal icon controls, pane SVG labels and always-enabled
  Stop. Native layout-only checks passed for both panes at 640/960/1440 widths;
  screenshots inspected. Updated existing assertions but skipped their execution
  at the user's request. No new search workers, timers or persistence changes.

## Validation Results

### Icon Grid Follow-up

```powershell
& { $previous = $env:QT_QPA_PLATFORM; $env:QT_QPA_PLATFORM = 'windows'; try { python -X faulthandler -m fman_integrationtest.search_content_smoke --layout-only } finally { $env:QT_QPA_PLATFORM = $previous } }
```

Passed for both pane icons at actual 640/960/1440 window widths: 28x28 buttons
in three aligned columns with 3-pixel gaps, nonblank pane icons and correct
tooltips, red enabled Stop and idle no-op. Dock height remained 111 pixels.
Native screenshots inspected. Unit/integration suites and actual content search
were deliberately skipped for this pass as requested; older results below are
historical, not validation of this revision.

### Panel Alignment and Stop Opacity

```powershell
python -X faulthandler -m unittest fman_unittest.test_ui_elements fman_unittest.test_search_file_content fman_integrationtest.test_qt.TableIT fman_integrationtest.test_qt.SearchFileContentIT fman_integrationtest.test_qt.DockedPanelIT fman_integrationtest.test_qt.PanelIT -v
& { $previous = $env:QT_QPA_PLATFORM; $env:QT_QPA_PLATFORM = 'windows'; try { python -X faulthandler -m fman_integrationtest.search_content_smoke } finally { $env:QT_QPA_PLATFORM = $previous } }
```

All 50 focused tests passed. The initial regression reproduced the original
misalignment; native captures also exposed a fixed-width resize constraint,
replaced by Qt-managed shrinkable columns. Tests now assert actual window width,
shared control edges and readable labels. Native smoke passed at 640/960/1440
widths with a 111-pixel dock, verifying bright red Stop pixels while enabled
and the same RGB with reduced opacity before/after work. Editor diagnostics are
clean. No full suite, freeze or packaging checks were run for this UI follow-up.

### Focused Regressions

Use the configured `python`, with repository main/unit/integration and bundled
plug-in directories on `PYTHONPATH` as in Focused Commands. Qt unit/integration
checks used `QT_QPA_PLATFORM=offscreen` and the Windows fonts directory.

Initial implementation focused command: **99 tests run, 98 passed, one expected capability skip**:

```powershell
python -X faulthandler -m unittest `
  fman_unittest.test_search_file_content `
  fman_unittest.test_ui_elements `
  fman_unittest.test_portable `
  fman_unittest.test_release_support.RipgrepPackagingTest `
  fman_integrationtest.test_search_file_content_engine `
  fman_integrationtest.test_qt.TableIT `
  fman_integrationtest.test_qt.SearchFileContentIT `
  fman_integrationtest.test_qt.PublicUiIT `
  fman_integrationtest.test_qt.DockedPanelIT `
  fman_integrationtest.test_qt.QuickListIT `
  fman_integrationtest.test_qt.PanelIT `
  fman_integrationtest.test_qt.FavoritesManagerIT `
  fman_integrationtest.impl.plugins.test_favorites_plugin `
  fman_integrationtest.impl.plugins.test_calculate_file_hash_plugin -v
```

Normal engine discovery also passed: **nine tests, eight passed, one skip**:

```powershell
python -m unittest discover -s src/integrationtest/python -p test_search_file_content_engine.py -v
```

The skipped directory-symlink fixture requires a privilege unavailable to this
process (WinError 1314). A separate native Windows junction fixture passed for
both filename modes, explicit eligibility and junction-root rejection.
Qt's offscreen backend emitted expected unsupported raise/keyboard/size-hint
warnings. Final editor diagnostics reported no errors in the touched Python
implementation and test files.

Decisive regressions include real-engine glob descent/exclusions, filename-regex
NUL record mapping with duplicate basenames, UTF-16/CRLF, binary suppression,
hidden/size guards, malformed/oversized transport, pipe pressure/cancellation,
reload contention, invalid-preflight result retention, atomic refresh, stale
menus, actual navigation adapter, modeless Tab focus, resource-root rejection,
status cleanup and adjacent legacy UI/API behavior. No complete build test suite
was run.

### Native Source Smoke

```powershell
$env:QT_QPA_PLATFORM = 'windows'
$env:QT_SCALE_FACTOR = '1' # Repeated with '1.5' and '2'.
python -X faulthandler -m fman_integrationtest.search_content_smoke
```

Passed at 100/150/200%: real application startup with temporary UserSettings,
loader-owned command/Panel, SVGs, toggle persistence, background search, modal
results, stopped progress timer, tracked parent navigation/file highlighting,
and Panel retention/disposal. No blank coordinator window appeared. Captures
were reviewed at narrow width and 200% scaling. The dock measured 111 logical
pixels at normal width and 145 when actions wrapped. Search-to-visible time was
169/179/207 ms for the small fixture. The monitor constrained oversized requested
windows at 150/200%; unconstrained large multi-monitor geometry is not verified.
Generated captures stay under ignored `target/`, outside application settings.

### Performance

```powershell
python -m fman_integrationtest.search_content_smoke --benchmark
python -X faulthandler -m unittest fman_integrationtest.test_qt.TableIT.test_large_snapshot_projection_timing -v
python -W error::SyntaxWarning -m py_compile src/integrationtest/python/fman_integrationtest/search_content_smoke.py
```

Warm fixture: 100 directories, 1,000 files each; one seven-byte matching file and
999 fourteen-byte nonmatching files per directory; 1,399,300 bytes total and
100 matching lines. No cold-cache flush was attempted. Second run measurements:

| Mode | Total | First engine hit | Process starts | Host peak working set | Largest child peak |
| --- | --- | --- | --- | --- | --- |
| Glob | 2.51 s | 103 ms | 2 | 43.1 MiB | 9.6 MiB |
| Filename regex | 22.29 s | 147 ms | 874 | 43.4 MiB | 55.9 MiB |
| Equivalent direct rg | 1.35 s | Not measured | 1 | Not measured | Not measured |

The earlier run measured 2.54/29.12 s and 2/877 starts; enumeration order affects
the number of batches containing accepted names. The filename-regex design is
bounded but its process-start overhead is substantial. It is documented, not
hidden by a second dialect or per-file engine. Host peak includes fixture/setup
and imports; largest-child peak is not aggregate concurrent process memory.

10,000-row Table fixture: snapshot/construction 36 ms, fuzzy update 8-9 ms after
adding an ASCII fast path. The Unicode/casefold-aware path is retained. The
initial 550 ms fuzzy result failed the design target and was corrected. These
are local measurements, not hard timing guarantees or full adversarial metrics.

### Packaging Inputs

Historical validation before the user's direct-use clarification:

Verified installed ripgrep 15.2.0 `h18a1a76_1` executable SHA-256 against conda
file metadata; no arbitrary PATH lookup or download. Installed-file inventory
contains no license entries, but the matching package cache provides
`info/licenses/LICENSE-MIT` and `THIRDPARTY.yml`. Packaging validates cache
identity, requires both notices, includes them and records binary/license hashes.
PyInstaller native-import inspection passed; declared VC/UCRT dependencies were
recorded. This was input validation, not a frozen execution result. The custom
checks and manifest have since been removed; the spec now copies conda's binary
and notices directly, as recorded below.

### Review Follow-up Validation

2026-09-14: **32 tests run, 31 passed, one expected symlink-privilege skip**:

```powershell
python -X faulthandler -m unittest fman_unittest.test_search_file_content fman_unittest.test_release_support.RipgrepPackagingTest fman_integrationtest.test_search_file_content_engine fman_integrationtest.test_qt.SearchFileContentIT fman_integrationtest.test_qt.TableIT -v
```

New cases prove direct source/frozen engine resolution performs no verification
I/O; the spec passes conda's executable/license inputs to PyInstaller; completed
searches in an inactive window cannot restart or edit options before results
close; closing before or after presentation restores the form. Existing search,
path-menu/navigation, modeless focus and binary/junction regressions also pass.
The first test invocation lacked repository PYTHONPATH; setting the documented
test paths resolved that import error without changing the Python environment.

Native smoke passed at the current Windows scale, with temporary UserSettings:

```powershell
$env:QT_QPA_PLATFORM = 'windows'
python -X faulthandler -m fman_integrationtest.search_content_smoke
```

Dock height 145/111 logical pixels; search-to-visible 163 ms. Verified actual
conda executable search, persistence, modal navigation, released result handle
and re-enabled Search. No package download, version/hash check, freeze, full
suite, install or new virtual environment was run during this follow-up.
Frozen artifact execution is out of scope for this source task, not a pass.

### UI Feedback Validation

2026-09-14: **57 focused tests passed**:

```powershell
python -X faulthandler -m unittest fman_unittest.test_ui_elements fman_unittest.test_search_file_content core.tests.test_quicksearch_matchers fman_integrationtest.test_qt.PublicUiIT fman_integrationtest.test_qt.QuickListIT fman_integrationtest.test_qt.TableIT fman_integrationtest.test_qt.SearchFileContentIT -v
```

Covered shared contiguous/fallback positions, Unicode offsets, public callback
thread/unsubscribe behavior, styled label alignment and width caps at 640/960/1440,
both fixed pane hints, ignored other-pane changes, captured busy roots, non-local
folder disabling and disposal. The 10,000-row Table fuzzy check took 11 ms.

With `QT_QPA_PLATFORM=windows`, ran:

```powershell
python -X faulthandler -m fman_integrationtest.search_content_smoke
```

Passed real-pane navigation/root following, unchanged other-pane ownership,
settings, search, contiguous extension highlights and tracked result navigation.
Native screenshots inspected: aligned shorter inputs, fixed left-pane hint,
unclipped actions and full highlighted extension. Dock heights 145/111 logical
pixels; search-to-visible 198 ms. No freeze, install, new environment or full
test suite was run. Existing portable release follow-ups remain unverified.

### Three-Mode Validation

2026-09-14: **59 tests run, 58 passed, one expected symlink-privilege skip**:

```powershell
python -X faulthandler -m unittest fman_unittest.test_ui_elements fman_unittest.test_search_file_content fman_integrationtest.test_qt.TableIT fman_integrationtest.test_qt.SearchFileContentIT fman_integrationtest.test_qt.PublicUiIT fman_integrationtest.test_search_file_content_engine -v
```

Covered native content/filename modes, whole-line and empty wildcard matches,
CRLF/Unicode, literal metacharacters/brackets, ranges/negation/edge hyphens,
invalid patterns, old/new/invalid settings, obsolete-key removal, preserved
unrelated settings, bounded Choice descriptors, exactly-one selection, silent
selected clicks, atomic updates, callbacks, disabling and search disposal.

Also ran the expanded nine-mode-pair matrix explicitly:

```powershell
python -X faulthandler -m unittest fman_unittest.test_search_file_content.SearchEngineTest.test_real_engine_three_filename_modes -v
```

Native smoke with `QT_QPA_PLATFORM=windows`:

```powershell
python -X faulthandler -m fman_integrationtest.search_content_smoke
```

Passed real mode-button clicks, saved-mode restoration on reopen, filename
RegEx/content Glob search, lock/unlock behavior and tracked navigation. Pixel
checks found three distinct nonblank icons; screenshots inspected at 640/960
widths, with geometry checked also at 1440. Dock heights remain 145/111 logical
pixels; search-to-visible was 198 ms. Existing late-result, root-following and
public API checks pass. No install, virtual environment, freeze or full suite.
The previous portable-release caveat remains unchanged.

### Release Follow-ups

- Frozen artifact packaging/search/Stop/navigation without development Python,
  PATH or rg remains unrun. No freeze/clean was requested or performed.
- Complete native visual/keyboard review across both themes, F1 comparison,
  inline rename, all menu shortcuts and unconstrained multi-monitor geometry.
- Full planned adversarial matrix, including every modal replacement/destroy
  trigger, blocked network metadata, cancellation in every pipeline stage,
  settings-save failure and repeated lifecycle resource measurements.
- Cold-cache throughput, aggregate simultaneous child RSS, Unicode-heavy
  10,000-row timing and 10,000-row completion-to-visible latency.

These unrun checks are not inferred passes. Fable's source-review follow-ups are
resolved; frozen execution is a separately authorized release check. Completion
of this source task does not mark the broader UI Elements roadmap complete.
