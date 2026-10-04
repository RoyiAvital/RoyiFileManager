# UI Elements 002: QuickList for Selecting and Working With Items

Status: Design, awaiting review.

## Task

Make QuickList the element for **selecting items and working with them**.
QuickTable narrows a set by filters and is immutable; QuickList lets the user pick
an explicit set and act on it. Third-party plug-ins should be able to present
files, folders or virtual file items and let the user run familiar pane
operations on them without writing Qt code or reimplementing file operations.

Motivation: many-file tools (cleanup, duplicate review, archive pickers,
Everything results, batch targets) need "pick these, then Copy / Move / Delete
them" with pane semantics. Today QuickList is a Qt widget that only Favorites
uses, items are text only and every operation must be written by the plug-in.

## Scope

Included:

- A Qt-free blocking service `show_list(...)`, built on the existing QuickList
  widget, hosted like `show_quick_table`.
- `ListItem` gains an optional `url` (any fman URL: `file://`, `zip://`, ...).
- Caller opt-in file operations with pane keys, no buttons:
  Go To, Copy, Move, Delete (Recycle Bin), Delete permanently, Rename.
  Copy, Move and both Deletes act on a **batch**; Rename and Go To act on a
  **single** item (the current one).
- Host-maintained items after operations (removed, or renamed in place).
- A result without buttons or labels: Enter returns the chosen items (the
  selection, else the highlighted item); Escape returns `None`.

Excluded:

- Any change to QuickTable (immutable; no operations besides Go To).
- Any change to QuickList's look: item rendering, filter box, footer text and
  layout stay as they are; right-click keeps toggling selection.
- Batch rename (the future File Renamer: Panel rules, Preview, QuickTable Enter result).
- Results as a pane / Flat View, drag and drop, Quick View, pack/unpack,
  symlink, new file/folder, open-with and external tools.
- Watching the file system for changes the list did not make.
- Buttons inside the list window.

Compatibility:

- The Qt `QuickList` widget API and Favorites behavior stay unchanged
  (its Delete still emits `delete_requested`; no operations are implied).
- `ListItem(id, title, hint='', title_matches=(), hint_matches=())` keeps its
  fields; `url=None` is added last.
- Core's pane rename behavior is unchanged; its logic moves into a shared
  function (see Design).

## Design

### API

```python
show_list(*, items, pane=None, title='', summary='', modal=True, filter='fuzzy',
          selected=(), operations=frozenset()) -> tuple[str, ...] | None
```

| Argument | Meaning |
| --- | --- |
| `items` | Iterable of `ListItem`; unique string IDs; at most 10,000 items, 16 MiB text. |
| `pane` | Required when `operations` is not empty: Go To target, Copy/Move default destination (its opposite pane) and command context. |
| `title`, `summary` | Window title and one elided line above the list. |
| `modal` | Default `True`: blocks the main window, as QuickTable. `False` keeps it usable. |
| `filter` | `'fuzzy'` (default, existing subsequence matcher) or `None` (no filter box). |
| `selected` | IDs selected initially (e.g. all, for "review then act"). |
| `operations` | Subset of `{'go_to', 'copy', 'move', 'delete', 'rename'}`. Empty: no file behavior. |

The call blocks until the window closes, exactly like `show_quick_table`.

### Keys and Result

All operations are defined by the selection and by what the caller does with
the result. There is no `accept` label and no button:

| Key | Effect |
| --- | --- |
| Enter (list or filter box), double-click | Close and return the **chosen** IDs in input order |
| Escape, window close | Close and return `None` |
| Ctrl+Enter | Go To the highlighted URL item (when `go_to` is enabled) |

- **Chosen** = the selection (including selected items hidden by the filter),
  else the highlighted item as a 1-tuple (pane `get_chosen_files` rule).
- Enter does nothing when nothing is selected and nothing is highlighted
  (empty list or no matches), so a result is never empty and `None` always
  means cancelled.
- A working list (operations only) simply ignores the result. Lists of
  non-file items (bookmarks, processes, commands) use the result directly.

### Selection, Not Narrowing

The filter box only helps **find** items. Selection is independent of it:

- Existing QuickList keys: Space toggles; Insert toggles and advances;
  Shift+navigation; Ctrl+A selects visible items; right-click/Ctrl-click toggle.
- Added: Ctrl+I inverts the selection over all items; Ctrl+Shift+A clears it.
- Hidden selected items stay selected and **are included** in batch operations
  and in the Enter result. The existing footer shows `N selected (M hidden)`.

### Operations

Enabled per call through `operations`; only items with a `url` take part.
Targets that include an item without `url` refuse the operation with a status
message. Keys follow the user's **Core key bindings** for the same command
names, resolved once per window, falling back to the defaults:

| Operation | Command used | Default keys | Targets |
| --- | --- | --- | --- |
| Go To | tracked `navigate` | Ctrl+Enter | Current: file -> parent folder with cursor on it; folder -> open folder |
| Copy | `copy(files, dest_dir)` | F5 | Chosen batch |
| Move | `move(files, dest_dir)` | F6 | Chosen batch |
| Delete | `move_to_trash(urls)` | F8, Delete | Chosen batch |
| Delete permanently | `delete_permanently(urls)` | Shift+Delete | Chosen batch |
| Rename | `rename_url(url, new_name)` (new hidden Core command) | Shift+F6 | Current only |

- **Batch rule:** chosen = selected (including hidden), else the current item.
- **Reuse:** the host executes the registered Core commands through the pane's
  command registry, with explicit targets. Core keeps its confirmations,
  destination prompt (default: the pane's opposite pane), overwrite handling,
  progress dialog, cancellation, archive support and file-system notifications.
- **No pane listener rewriting:** commands are executed directly, not through
  `pane.run_command`, because `on_command` listeners reflect the pane's location
  (for example the process pane rewrites Delete), not the listed items.
- **Rename** is inline: Shift+F6 opens an editor on the current item's title
  with the name stem preselected; Enter commits, Escape cancels. Core's
  `RenameListener.on_name_edited` validation and `_Rename` task move into one
  pane-independent function used by both the pane listener and the new hidden
  `rename_url` command. Rules stay identical: empty/unchanged ignored, `\`,
  `/`, `.`, `..` refused ("use Move"), existing target refused except a
  case-only change.
- **Discoverability without changing the look:** the keyboard context menu
  (Menu key or Shift+F10) lists the enabled operations with their shortcuts
  and Copy Path for URL items. Right-click keeps toggling selection, as today;
  no footer hint or other visible element is added.
- Without `operations`, only selection and the Enter/Escape result apply.

### Item Maintenance After Operations

The host, not the caller, keeps the list truthful:

- **Delete / Delete permanently / Move:** after the command returns, each
  target URL is checked with `fman.fs.exists`; missing items are removed from
  the list and the selection. Moved items leave the list like moved files leave
  a pane.
- **Copy:** no change.
- **Rename:** on success the item's `url` becomes the new URL; its `title` is
  replaced when it equals the old base name, its `hint` when it equals the old
  human-readable path. Other caller text is kept. Selection and current stay.
- Canceled or failed operations remove only items that no longer exist.

### Ownership, Threading and Failure

- `show_list` is `@run_in_main_thread` and runs a nested event loop, as
  `show_quick_table`. The window is a `ToolWindow` (`busy`, `post`, `alive`).
- Operations run one at a time on a worker (`ToolWindow.work`): the window is
  busy and operation keys are ignored meanwhile. Core's `submit_task` is
  synchronous on that worker and shows its own progress dialog.
- The worker captures immutable targets, runs the command, then checks
  existence; results are posted to Qt, which updates items. Results for a
  disposed window are dropped.
- Closing the window during an operation does not cancel it (use the progress
  dialog's Cancel); item updates are then discarded.
- Exceptions from commands are reported with `window.alert`; the list stays
  consistent because only verified-missing items are removed.

### Persistence

None. Items, selection and filter are session-only.

## Alternatives

- **Operations in QuickTable:** rejected; QuickTable is an immutable snapshot and rows
  would go stale or require mutation.
- **Results as a pane / Flat View:** unrelated feature; leaves the results
  window and loses list semantics.
- **Buttons (Delete, Copy, OK):** rejected by the buttonless design; pane keys
  and the context menu cover discovery.
- **Host-implemented file operations:** rejected; duplicates Core's
  confirmations, overwrite logic, archives and notifications.
- **`pane.run_command` with listeners:** rejected; location-specific rewrites
  could change the meaning of an operation on unrelated items.
- **Caller callbacks per operation:** rejected; keeps the API static and
  avoids plug-in code running inside UI event handling.
- **Visible-only batches (narrowing):** rejected; QuickList is for explicit
  selection, so hidden selected items stay targets and are counted.
- **`accept` label (Ctrl+Enter or Enter returning a result only when set):**
  rejected for simplicity; every list returns the chosen items on Enter.
- **Enter for the highlighted item, Ctrl+Enter for the selection:** rejected;
  one key with the pane rule is simpler and matches QuickList's focus on
  selection.
- **Right-click context menu or footer key hints:** rejected; they would
  change QuickList's existing look and right-click toggling.

## Runtime Effects

- Startup/idle: none. Nothing is created until `show_list` is called.
- Open list: memory proportional to items (bounded by 10,000 items / 16 MiB);
  filtering is existing in-memory QuickList work on Qt.
- Operations: Core's existing I/O and progress; plus one `exists` check per
  target after Delete/Move. One worker at a time; no timers or polling.
- Disabled path: `operations` empty means no key bindings lookup, no worker,
  no extra I/O.
- Cancellation: through Core's progress dialog; window close drops late updates.

## Tests

Unit:

- `ListItem.url` validation; `show_list` argument validation (operations set,
  `pane` required, limits, duplicate IDs, `selected` unknown IDs).
- Chosen-target rule (selected incl. hidden, else current; non-URL refusal).
- Core: shared rename function keeps all `RenameListener` rules (existing pane
  tests plus direct calls), `rename_url` command hidden from the palette.

Qt integration (`QuickListServiceIT`, offscreen and native):

- Blocking from worker and Qt thread; modal by default; Escape and close
  return `None`; Enter and double-click return the selection in input order
  (including hidden selected items), else the highlighted item; Enter with no
  selection and no matches does nothing.
- Ctrl+I / Ctrl+Shift+A; footer counts with a filter active.
- Delete (F8, Delete) with patched confirmation: deleted items disappear,
  others stay; cancel keeps everything. Delete permanently via Shift+Delete.
- Move to a temporary folder removes moved items; Copy keeps items.
- Rename: inline edit, success updates url/title/hint, conflict and
  relative-name refusals keep the item.
- Go To (Ctrl+Enter) file and folder; modal closes, modeless stays (as QuickTable).
- Process-pane style `on_command` rewrite is **not** applied to list items.
- Custom Core key binding (e.g. Delete rebound) is honored.
- No operations: F5/F8/Ctrl+Enter do nothing; Favorites Manager tests unchanged.
- Right-click still toggles selection; the Menu key / Shift+F10 opens the
  operations menu.
- `gc.collect()` after closing context menus and the inline editor.

Manual: native 100/150% look compared with the current QuickList (Favorites
Manager) to confirm no visual change, context menu shortcuts, progress dialogs
over the list window, archive (`zip://`) items for Copy.

Focused command (offscreen and `windows`):

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_ui_elements','core.tests.commands.test___init__','fman_integrationtest.test_qt.QuickListServiceIT','fman_integrationtest.test_qt.FavoritesManagerIT'], env=env).returncode)"
```

## Implementation Steps

1. Core: extract pane-independent rename; add hidden `rename_url`; run Core
   command tests.
2. `ListItem.url`; validation and limits; unit tests.
3. `ListWindow` + `show_list`/`open_list` in the facade (blocking, modal by
   default, summary, filter, `selected`, Enter/Escape result) reusing the
   QuickList widget unchanged; Qt tests.
4. Selection helpers (Ctrl+I, Ctrl+Shift+A) in QuickList's view, opt-in for
   the service so Favorites is unchanged; Qt tests.
5. Operations: key resolution, worker execution through the command registry,
   existence checks and item maintenance; Qt tests per operation.
6. Inline rename editor; Qt tests.
7. Keyboard context menu (Menu key, Shift+F10) with shortcuts and Copy Path;
   GC regression check.
8. Docs: PlugIn.md, UIElements.md, CHANGELOG; record validation; move to Done.

## Acceptance Criteria

- A plug-in can show URL items with `show_list(..., operations=...)` and,
  without Qt code, the user can Copy/Move/Delete a selected batch and Rename or
  Go To the current item with pane keys.
- Batch operations include hidden selected items; counts are visible first.
- Deleted/moved items disappear; renamed items update; nothing else changes.
- Core confirmations, prompts and progress are used; pane listeners are not.
- Enter returns the selection, else the highlighted item; Escape returns
  `None`; there is no `accept` argument and no button.
- Without `operations`, behavior has no file semantics.
- QuickList looks exactly as before; right-click still toggles selection.
- QuickTable and the Qt `QuickList` widget API are unchanged; Favorites tests pass.
- Focused tests pass offscreen and native.

## Reviewers

### 2026_10_03 - Maintainer and Documenter Claude Opus 5.5

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Initial design from the user discussion: QuickList selects and
  works with items (Table only narrows). Buttonless, opt-in pane operations
  reusing Core commands; Rename and Go To single item, others batch. Open
  points for review: modal default for a working list, and whether accept
  should fall back to the current item.

### 2026_10_04 - Maintainer and Documenter Claude Opus 5.5

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: User decisions: modal by default (confirmed); `accept` removed
  because the list is interactive and acts through its operations; Table
  `accept` remains the way to hand a subset to a caller. `show_list` returns
  `None`. No open design points remain.

### 2026_10_04 - Maintainer and Documenter Claude Opus 5.5

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Correction: the user asked for the motivation of `accept`, not its
  removal. `accept` is restored as originally designed; its fate is an open
  decision. Modal by default stays confirmed.

### 2026_10_04 - Maintainer and Documenter Claude Opus 5.5

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: User decision: no `accept`. Enter (and double-click) returns the
  selection, else the highlighted item; Escape returns `None`; Ctrl+Enter is
  Go To. QuickList's look must not change: no footer hints, right-click keeps
  toggling, operations menu only via Menu key / Shift+F10. No open points.
