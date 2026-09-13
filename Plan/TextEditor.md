# Text Editor Service

Status: Proposed design; not approved for implementation. The user requested a
host service, F3 viewing, F4 editing, syntax highlighting, clipboard editing,
VS Code-like multi-caret bindings, and the existing Sublime Text-inspired Panel
concept. Window placement, initial file scope, and the additional features below
are proposed defaults requiring review, not recorded user approvals.

## Task

View and edit text without leaving RoyiFileManager. Expose the editor as a host
service that plug-ins can call, not as a bundled editor plug-in. Keep document
content separate from compact operation controls, following the
[UI Elements design](UIElements.md) and the shipped
[Favorites UI](../src/main/resources/base/Plugins/Favorites/favorites/ui.py).

## Scope

- F3 views the file under the cursor; F4 edits it. Both use QScintilla and the
  same host-owned document/session implementation, operating on one file per call.
- Syntax highlighting with available QScintilla lexers, automatic language
  selection, manual language override, and plain-text fallback.
- Copy/select/search in View mode; cut/paste/replace/undo/redo/save in Edit mode.
- VS Code-like multi-caret actions, including mouse and keyboard selection.
- Panel-based document actions, Find/Replace, and Go to Line. No modal search
  dialog, operation controls inside the text canvas, or duplicate search engine.
- Proposed first release: local filesystem text files, including extensionless
  files. Virtual/archive write-back, generated editable buffers, inactive-pane
  replacement, tabs, split editors, project features, LSP, automatic formatting,
  autosave, and crash/session document recovery are deferred.
- Regex search is supported by QScintilla but deferred from the initial UI:
  arbitrary native regex calls cannot be reliably canceled on the Qt thread.
  Literal, case-sensitive, and whole-word search are included.
- Licensing assessment is outside this design at the user's request.

Compatibility: preserve the public `fman` plug-in API from fman 1.7.5. Add a
provisional RoyiFileManager service API; do not expose QScintilla widgets through
the general Window/DirectoryPane API. Preserve existing external-editor command
IDs and settings. Rebinding the shipped F4/Shift+F4 defaults is a documented
workflow change; user binding overrides continue to win.

## Design

### Ownership And Placement

The application context lazily owns an EditorService. Its internal implementation
belongs under `fman.impl`, with an additive public `fman.editor` facade. Core
commands select a URL and call the service; loading, documents, saving, and editor
commands belong to the host. The service is not registered as a plug-in.

Proposed placement: a normal resizable, non-modal top-level Qt window per file,
in the existing application process. It supports maximize and multiple monitors;
both directory panes remain usable. Keep the editor widget independent of its
window so later preview placement does not require another text implementation.

Use a host-owned window/controller, not PaneToolWindow: its
[current lifecycle](../src/main/python/fman/impl/ui/session.py) requires a plug-in
owner and unconditionally disposes on close. An editor needs a dirty-document
close gate and must survive the caller plug-in unloading or navigating away.
The service retains windows until approved close; application exit coordinates
all documents before destroying any window. Cancel aborts exit. No dirty document
is disposed merely because its original pane closes.

### Panel And Commands

Reuse [Panel, IconButton, TextButton, DropDown, and PanelDock](../src/main/python/fman/impl/ui/panel.py).
The content canvas stays above a compact bottom Panel, with a thin status row
below it. Use the existing theme, spacing, native controls, button width caps,
accessible labels, and focus conventions. Sublime Text inspires placement and
operation layout; multi-caret shortcuts remain VS Code-like as requested.

- The default document Panel exposes save actions and access to Find/Replace,
  Go to Line, language, indentation, and wrap settings. Keep secondary choices
  in menus/dropdowns instead of permanently displaying every option.
- Find reveals a query field, case/whole-word toggles, previous/next actions, and
  a bounded match-count/result label. Replace adds a second field and explicit
  Replace/Replace All actions. Go to Line replaces those operation fields.
- One operation form is visible at a time. These are editor-local Panel modes,
  not modal dialogs and not nested cards. Preserve their values while switching.
- Panel currently has a horizontal layout and accepts arbitrary Qt widgets.
  Put multi-row fields in a child QWidget/layout through Panel.add; do not
  invent a new public form API solely for this consumer. Reflow controls into
  rows at compact widths; fields expand while icons and actions stay bounded.
- Use IconButton for boolean options and familiar action icons; action icons
  must be non-checkable. Use TextButton for explicit Replace/Replace All actions.
  Missing symbols require theme-consistent assets, not a new icon library.
- The editor instantiates its own internal PanelDock. Its close callback hides
  the Panel and returns focus to the text, not closes the editor. Do not use
  [MainWindow.set_bottom_panel](../src/main/python/fman/impl/widgets.py), which
  replaces the main window's current tool session. Favorites remains unaffected.
- Panel buttons, shortcuts, and any menu entries dispatch the same editor-local
  command IDs with shared enabled-state checks. Do not route editor keystrokes
  through DirectoryPaneCommand against whichever file pane was last active.

| Context / Binding | Command And Behavior |
| --- | --- |
| File pane: F3 | `view_text_file`: open the cursor file in View mode |
| File pane: F4 | `edit_text_file`: open the cursor file in Edit mode |
| File pane: Shift+F4 | `create_and_edit_text_file`: reuse the existing create/prompt helpers, then call the service |
| Editor: F4 | `enable_editing`: upgrade View without reloading or moving the caret |
| Editor: Ctrl+S / Ctrl+Shift+S | `save` / `save_as` |
| Editor: Ctrl+F / Ctrl+H / Ctrl+G | `show_find` / `show_replace` / `show_goto_line` |
| Editor: F3 / Shift+F3 | `find_next` / `find_previous`; never open another file |
| Query field: Enter / Shift+Enter | Find next / previous; never implicitly Replace All |
| Editor: Ctrl+C/X/V/A | Copy / cut / paste / select all, subject to mode |
| Editor: Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z | Undo / redo / redo |
| Editor: Alt+Z | Toggle word wrap |
| Editor: Ctrl+W / Alt+F4 | Request document close through the unsaved-change gate |

Shortcuts are scoped to the editor window and relevant child, not application
global. Ctrl+F must not start SearchFileFuzzy, Ctrl+S must not toggle extended
status, Tab in the canvas indents, and Delete must never delete a filesystem item.
Text fields retain normal editing shortcuts. Tab/Shift+Tab traverse Panel
controls; return focus to the canvas at the boundary, following PanelDock.
Escape first dismisses completion/temporary selection state in its context,
then hides an active Panel; bare Escape never discards or closes an editor.

The existing `open_with_editor` and `create_and_edit_file` commands retain their
external-editor behavior and settings. Add the new thin internal commands and
change only shipped bindings; do not silently change callable legacy IDs.
See [current editor commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)
and [key bindings](../src/main/resources/base/Plugins/Core/Key%20Bindings.json).

### Public Service Contract

Proposed entry point: `fman.editor.open_file(url, *, mode="view", line=None,
column=None) -> EditorHandle`. The signature is subject to design review.
It accepts fman URLs, not percent-encoded QUrls; resolves supported aliases once
and validates a regular filesystem file. Use 1-based line/Unicode-character
column coordinates; clamp beyond end of document and reject invalid values.
Translate to Scintilla UTF-8 byte positions internally.

Calls may originate on a command worker or Qt. Return promptly with an opaque
handle; dispatch UI operations to Qt. The handle supports focus, request_close,
and opened/saved/closed/error subscriptions. Subscriptions return idempotent
unsubscribe functions, deliver on Qt, and can be tied to an existing UiOwner.
Unloading a subscriber removes its callbacks without destroying host-owned
documents. No raw widget, document pointer, unrestricted mutation, or
programmatic bypass of the save/close gate is exposed initially.

Normalize document keys with repository URL/path helpers and Windows path case
rules; deduplicate ordinary aliases. Do not lowercase displayed paths or treat
distinct hard-link paths as independent safe write targets. Opening an already
open file focuses/reuses its buffer. F4 upgrades View. F3 can downgrade a clean
buffer; when an existing buffer is dirty, report `mode_conflict` and focus that
editor instead of claiming a successful read-only open or losing edits.

Opening, ready, failed, and closed outcomes are explicit. A repeated request
cannot reload a dirty buffer. Failed opens do not leave a misleading empty
editable window. Closing a loading window cancels delivery; late results cannot
recreate it. Unsupported schemes/directories/binary files produce a clear error
without executing the file or silently opening an external application.

### Editing And Search

View mode is enforced by QScintilla read-only state and command enabled states;
cut, paste, drag/drop mutation, replace, save, and undo/redo mutation are disabled.
Edit mode enables mutations, tracks QScintilla's save point, and marks dirty state
in the title. Read-only filesystem attributes remain distinct from View mode.

| Multi-Caret Binding | Behavior |
| --- | --- |
| Alt+Click | Add a caret without dropping existing selections |
| Ctrl+Alt+Up/Down | Add carets above/below, retaining the desired visual column |
| Ctrl+D | Select the caret word, then successive occurrences |
| Ctrl+Shift+L | Select all occurrences of the current selection |
| Shift+Alt+Drag | Rectangular selection |
| Escape in canvas | Collapse additional carets before other Escape behavior |

Use Scintilla's multiple-selection, additional-selection-typing, and multi-paste
facilities, not separate Python text buffers. Explicitly map commands and mouse
gestures; high-level QScintilla selection helpers often address only the main
selection. Define document-order clipboard joining with line separators, paste
to every caret, and line-per-caret paste when the copied selection count matches.
Verify those VS Code-like semantics on the installed build; defaults differ.
One multi-caret edit is one undo action. Test Unicode, CRLF, short lines, virtual
space, overlapping selections, and non-US keyboard input. OS-reserved bindings
may require a user remap, never a Registry change.

QScintilla supplies find/replace primitives; the host supplies Panel fields,
options, navigation, highlighting, and Replace All orchestration. Use native
literal search with explicit case/word flags. Empty queries make no changes.
Replace verifies the current match and document revision before changing text.

Replace All captures scope/revision, preflights matches, then edits ranges in
reverse order using one undo group. Find-all and replacement processing yield
between batches (at most 128 matches or 8 ms before yielding). User mutation is
temporarily disabled during Replace All. Cancel before mutation changes nothing;
after mutation begins it stops after the current batch, reports the applied
count, and retains one undoable partial edit. Never save implicitly. Close waits
for the current batch/undo group to settle, then runs the dirty-state gate.
This does not make an individual native search call preemptible.

Basic reading aids: line numbers, brace/current-line highlighting, optional
folding and whitespace, wrap, font zoom, auto-indent, tabs/spaces and width.
Status shows View/Edit, line/column, selection/caret counts, encoding, line ending,
language, and loading/saving/error state. Lexers provide highlighting, not syntax
validation or language-server intelligence. Theme/font changes must update lexer
styles as well as the widget's default font.

### File Fidelity And Saving

Read bytes off Qt with a cancellation token and observed file identity. Detect
BOMs before binary heuristics, accept valid UTF-8, and offer an explicit encoding
choice for ambiguous legacy text. Never decode with silent replacement and then
overwrite the source. Keep original encoding/BOM, per-line endings, and final
newline state. New lines use the detected dominant EOL, defaulting to CRLF for
new Windows documents. Conversion is explicit; opening/saving alone must not
normalize text. Unsupported lexers do not prevent plain-text editing.

Capture an immutable text snapshot and revision on Qt, then encode/write off Qt.
Save to a temporary sibling and atomically commit using an appropriate Qt/Windows
primitive with destructive direct-write fallback disabled. Preserve required
permissions/attributes. Before commit, compare the target with its load/last-save
baseline (identity, size, modification time, and content digest); mismatches offer
Reload with a discard gate or Save As, not a silent overwrite. This is conflict
detection, not a cross-process compare-and-swap guarantee; document the residual
check-to-commit race and the primitive's Windows/network limitations.

Initially refuse in-place saves to reparse points, multiply linked files, or
targets whose required metadata cannot be preserved; offer Save As. Honor
Windows read-only attributes without clearing them. Save As confirms an existing
target and cannot overwrite a different open document's backing file. Save
failure retains text, undo history, dirty state, and the original target. Remove
temporary files on ordinary error/cancel paths. Set the save point only after
successful commit; serialize saves and prevent editing during the short save
operation to keep snapshot/save-point identity unambiguous.

After commit, send the existing filesystem change/add notifications so both
panes and cached metadata refresh. Update the session key only after successful
Save As. External changes are checked on editor reactivation and before save,
without recurring polling; coalesce checks and reject stale deliveries. Never
auto-reload over unsaved edits. Save/Discard/Cancel is asynchronously owned by
the editor; Cancel is the default. Destruction cannot interrupt an active commit.

### Persistence

Store defaults through existing layered JSON settings under UserSettings:
font/size, language mappings, wrap, indentation, and search option booleans.
Use a dedicated editor settings name and fresh snapshots with the existing
resource lock/revision pattern; no mutable shared-cache edits before a successful
save. Window geometry is portable local session state, clamped to current screens.
Do not persist document contents, search/replacement strings, or file history in
the first release. Importing the service performs no settings I/O.

## Alternatives

- Inactive-pane editor: useful for adjacent browsing, but hides a transfer
  destination and complicates pane/command ownership. Defer to a separate preview
  placement design; do not implement both placements in this task.
- Modal editor: easy lifetime, but prevents continued file-manager use. Prefer
  non-modal; only save/discard and file-choice prompts block their own editor.
- Main-window Panel for the editor: matches Favorites' physical location but
  separates controls from a movable document and competes for the single dock.
  Reuse the components locally without altering the existing docking contract.
- Separate viewer and editor implementations: duplicates decoding, search, and
  themes. Prefer one component with explicit mode gates.
- Editor plug-in or raw QScintilla public API: rejected by the host-service
  requirement and lifetime/API coupling. Keep a small additive service facade.
- Native regex on Qt: available but not safely interruptible for arbitrary
  patterns. Defer rather than moving a Qt widget to a worker or writing a regex
  engine. Regex inclusion requires a separately reviewed execution strategy.

## Runtime Effects

- Unused path: lazy QScintilla/lexer imports and EditorService initialization;
  no editor workers, timers, file scans, settings reads, or signal subscriptions.
- All widgets, QsciDocument objects, and Scintilla messages stay on Qt. Use the
  existing bounded shared work facility for file/settings work, with at most one
  I/O operation per document and no unbounded queue. Busy slots produce a retryable
  state. Workers carry plain snapshots/tokens, never widgets or document pointers.
- Proposed initial limits: 8 open document windows, 16 MiB source bytes, 32 MiB
  decoded UTF-8 per load, 1 MiB per line, 2,000 highlighted matches, and 10,000
  preflight Replace All matches. Exceeding load/replace limits refuses the
  operation before mutation; match counts above the highlight cap show a lower
  bound. These are initial policy values to measure and review, not benchmarks.
- Disable highlighting/folding above 2 MiB or 16 KiB lines. Incremental find uses
  one 150 ms single-shot debounce only while its Panel is active and the document
  is at most 1 MiB; larger documents search on explicit Enter/Next. Cancel pending
  debounce/highlight work when the Panel closes. No permanent polling timer.
- Steady-state work is text layout/lexing/undo plus event-driven status updates.
  Memory includes the text, Scintilla metadata, undo history, and bounded in-flight
  copies/results. Undo and subsequent edits can grow memory beyond load limits;
  do not advertise a hard process-memory bound or silently truncate undo.
- File I/O is on demand: open, explicit save, settings changes, and coalesced
  activation checks. No editor-specific subprocesses. Cancellation releases a
  worker slot only after the actual call ends; blocked network/filesystem calls
  may outlive cancellation but cannot publish stale UI or start a canceled save.
- Save can be canceled before commit. Once commit starts, finish and report its
  outcome before closing. Shutdown must not terminate a writer mid-commit.

## Tests

The following are required implementation checks, not results from this design
pass. Add focused modules to the existing
[unit tests](../src/unittest/python/fman_unittest) and
[Qt integration tests](../src/integrationtest/python/fman_integrationtest), reusing
the [shared QApplication harness](../src/integrationtest/python/fman_integrationtest/test_qt.py).
No new environment or Python package installation is part of this task.

1. Unit: language selection; URL identity/mode conflicts; UTF-8/UTF-16 BOM and
   explicit legacy encoding; binary/extensionless/empty files; mixed EOL/final
   newline round trips; size limits; read-only/link/metadata restrictions; failed
   writes, cancellation, external modification, and Save As collisions.
2. Qt: F3 mutation blocking through every input path; F4 promotion; shared
   command/button states; all multi-caret bindings, Unicode clipboard/paste and
   grouped undo; Find/Replace/Go to Line forms; partial Replace All cancellation;
   invalid/empty queries; Panel close versus document close; focus/shortcut
   isolation; theme/DPI changes; no clipped controls at minimum window size.
3. Integration: service called from Qt and command workers; subscriber unload;
   repeated opens and late load/check/save results; pane close/navigation;
   saturated worker slots; Save/Discard/Cancel and canceled application exit;
   post-save pane notifications; external-editor command compatibility.
4. Performance: generated 1/2/16 MiB files, 16 KiB/1 MiB lines, and match-limit
   boundaries. Record load/search/replace/save latency, peak memory, and Qt
   heartbeat delays. Budget: no avoidable >100 ms UI stalls on the agreed Windows
   test machine; lower limits or revise execution before approval if unmet.
   Verify no editor-specific recurring work before first use and after last close.
5. Native/frozen smoke: 100/150/200% DPI, narrow/wide windows, second monitor,
   Alt+Tab, clipboard between editors/external apps, UTF-16 and non-ASCII files,
   permission/locked/UNC targets, dirty exit, and working highlighting in the ZIP.
   Installed QScintilla APIs/DLLs/lexers must be probed and packaged explicitly;
   manifest presence alone does not prove import or runtime behavior.

Planned focused commands, from the repository root in the existing environment:

```powershell
$roots = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites', 'src/main/resources/base/Plugins/SearchFileFuzzy')
$env:PYTHONPATH = ($roots | ForEach-Object { (Resolve-Path $_).Path }) -join [IO.Path]::PathSeparator
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_text_editor
python -m unittest fman_integrationtest.impl.test_text_editor
python -m unittest core.tests.commands.test___init__ fman_unittest.test_ui_elements fman_unittest.test_portable fman_unittest.test_release_support
python -m unittest fman_integrationtest.test_qt
```

`test_text_editor` modules are proposed additions. Run the narrowest new test
immediately after the first implementation edit; run the affected existing
regressions after shared changes. Check each exit code; do not mask earlier
failures with later successes. Do not run the full `python build.py test` suite
without explicit user instruction.

Native validation uses `Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue`
then `python build.py run` for the procedures above. Packaging validation uses
`python build.py freeze`, `python build.py package`, and repeats the smoke checks
from the extracted ZIP with isolated UserSettings. Record exact artifact paths,
commands, outcomes, and any approved skips during implementation.

## Implementation Steps

1. Review placement, Panel lifetime, initial limits/file scope, regex deferral,
   and service contract. Probe installed QScintilla multi-selection/search/clipboard
   behavior and Windows save metadata before finalizing those contracts.
2. Implement pure document identity, decoding/encoding, conflict/save helpers,
   and focused unit tests. No windows or global shortcuts in this step.
3. Add lazy host service and View window with local Panel, highlighting, read-only
   enforcement, request lifecycle, and Qt integration tests.
4. Add Edit mode, transactional save/Save As, dirty close/application-exit gates,
   filesystem notifications, and failure/race regressions.
5. Add shared editor-local command dispatch, multi-carets, Panel Find/Replace and
   Go to Line, then focused keyboard, cancellation, and responsiveness checks.
6. Wire new Core commands/default bindings while preserving legacy external
   commands; update [PlugIn.md](../PlugIn.md), [README.md](../README.md), and
   [CHANGELOG.md](../CHANGELOG.md) for the implemented API/workflow change.
7. Validate source and frozen delivery, record results and implementation metadata,
   and only then move this canonical task to Done and update the index.

## Acceptance Criteria

- Reviewed design resolves the proposed defaults; no application work is claimed
  complete by creating this document.
- F3 safely views text, F4 enables editing/saving, and unsupported inputs fail
  clearly without executing files or affecting directory state.
- Plug-ins call a documented host service without owning or receiving widgets;
  unloading a caller does not lose a document or invoke stale callbacks.
- Commands and fields use the existing Panel concept/components; no modal
  Find/Replace UI, pane replacement, or competing main-window dock is introduced.
- Panel close never closes a document; editor input never invokes pane actions.
- Highlighting, clipboard, and listed multi-caret actions behave as specified in
  native Windows and frozen tests, with Unicode-safe edits and coherent undo.
- Save preserves text fidelity, refuses unsafe/conflicting targets, reports
  failures without clearing dirty state, and refreshes affected file panes.
- No close, reload, repeated open, or shutdown silently discards unsaved changes.
- Work/results remain bounded and stale-safe; unused editor has no feature work.
- Required focused tests and source/frozen checks pass, or explicit user-approved
  deferrals are recorded before completion. Public API compatibility is retained.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed host editor service with reused Panel controls and editor-local
  command/lifetime handling. Placement, API, file limits, and regex deferral need
  review before implementation; no implementation or runtime validation claimed.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Not yet approved. Verified QScintilla 2.14.1 (47 lexers, all required
  `SCI_*` multi-selection messages) imports in the active environment and that
  `qscintilla2` is present in the committed `conda-lock.yml`. Blocking revisions:
  (1) add `PyQt5.Qsci` and the new `fman.editor`/`fman.impl.editor.*` hidden
  imports, DLL collection and an import-probe test to the plan; (2) name the
  required host change for the exit gate (`MainWindow.closeEvent` must consult the
  service and `event.ignore()`; `Quit`, `Application.exit` and `closed -> quit`
  all funnel through it); (3) give the editor its own bounded executor instead
  of the shared two-slot `submit_work` pool, so a slow UNC read/save cannot block
  Favorites/JsonSettings and Ctrl+S never yields a "retry" state; (4) specify
  where default settings live (Core-shipped `Text Editor.json`, following the
  `Status Bar.json` precedent). Design gaps to state explicitly: Scintilla
  hard-codes Ctrl+Click as add-selection, so Alt+Click/Shift+Alt+Drag need
  Python mouse-event mapping; the default `QsciCommandSet` (Ctrl+D, Ctrl+L,
  Ctrl+T, Ctrl+Shift+L, ...) must be cleared before VS Code bindings; name the
  commit primitive (temp sibling + `os.replace`, attribute copy, documented ACL
  inheritance limitation); decide editor window parenting (recommend parentless
  top-level); define the concrete non-UTF-8 fallback rule; record Python `re`
  on the immutable snapshot as the intended regex path.