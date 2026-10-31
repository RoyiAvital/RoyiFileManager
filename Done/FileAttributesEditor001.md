# File Attributes Editor 001

## Task

Let the user view and edit the Windows attributes (Read-only, Hidden, System,
Archive, Not content indexed, Temporary) of the chosen files and folders, from
one keyboard-driven list. For folders, the user chooses on approval whether the
change applies to the chosen items only or recursively.

Build it as a third-party style plug-in on public APIs only, like
[Batch File Renamer](../Done/BatchFileRenamer.md), and ship it in the frozen build.
It is the first consumer of [QuickCheckList](UIElements004.md).

## Scope

- One command, **Edit Attributes** (ID `edit_attributes`, category `File`), for
  local `file://` panes with chosen items (selection, or the cursor item).
  No default shortcut (<kbd>Alt</kbd>+<kbd>Enter</kbd> is Properties); users can bind one.
- Editable attributes:

  | Item ID       | Title               | Hint | Flag     | Notes                                         |
  | ------------- | ------------------- | ---- | -------- | --------------------------------------------- |
  | `readonly`    | Read-only           | R    | `0x1`    | Not enforced on folders by Windows; stored only. |
  | `hidden`      | Hidden              | H    | `0x2`    |                                               |
  | `system`      | System              | S    | `0x4`    |                                               |
  | `archive`     | Archive             | A    | `0x20`   |                                               |
  | `not_indexed` | Not content indexed | I    | `0x2000` |                                               |
  | `temporary`   | Temporary           | T    | `0x100`  | Files only; disabled when a folder is chosen. |

- Enter applies to the chosen items. Shift+Enter applies recursively; it is offered
  only when a folder is chosen.
- Only attributes the user changed are ever written. When the final states equal
  the starting states, nothing happens, whether Enter or Shift+Enter was used.
- Attributes are gathered once and treated as static; nothing is re-read or
  revalidated before writing ([Static Model](#static-model)).
- Exclude Compressed and Encrypted (they need `FSCTL_SET_COMPRESSION` /
  `EncryptFile`), cloud Pinned/Unpinned, timestamps, ACLs and undo.
- Paths: drive-letter paths, including mapped network drives. UNC paths,
  archives and other file systems are rejected in v1.
- Exclude chosen links and junctions: reject the selection before opening, as
  Batch File Renamer does. Never silently drop a chosen item.
- The plug-in uses only public `fman`, `fman.fs`, `fman.url`, `fman.ui` and the
  standard library (`os`, `stat`, `ctypes`). No Qt, `fman.impl`, `core` or private names.

## Design

### Package

- Source: `plugins/FileAttributesEditor/` with `README.md`,
  `file_attributes_editor/__init__.py` (command and tasks) and
  `file_attributes_editor/engine.py` (pure logic: masks, merge, walk, apply).
- Frozen: add `('plugins/FileAttributesEditor', 'resources/Plugins/FileAttributesEditor')`
  to the [application.spec](../application.spec) datas, next to Batch File Renamer.
  Add hidden imports for any standard-library module the app does not already bundle.
- Source runs: install a copy under `UserSettings/Plugins/Third-party/FileAttributesEditor`.
- `supported_host()` checks the version and `callable(getattr(fman.ui, 'show_quick_check_list', None))`;
  an older host gets an alert asking to update.

### Data Flow

1. **Capture** (a cancellable `fman.Task`), when the command starts: for each
   chosen URL, take the local drive-letter path and `os.lstat` it. Reject the
   selection when a path is UNC, when an item is missing or when it is a
   link or junction (a name-surrogate reparse tag, `st_reparse_tag & 0x20000000`).
   Other reparse points (cloud placeholders, deduplication) are allowed. Record
   the attribute bits and the folder flag. See [Static Model](#static-model).
2. **Starting states**: per attribute, `on` when all chosen items have it, `off`
   when none do, `mixed` otherwise. Temporary counts files only and is disabled
   when a folder is chosen.
3. **Dialog**: `show_quick_check_list(states='checkbox3', alternate=<any folder>)`.
   Title `Attributes: <name>` or `Attributes: N items (M folders)`; summary is the
   parent folder; status `Enter: Apply · Esc: Cancel`, plus
   `Shift+Enter: Apply recursively` when a folder is chosen.
4. **Masks**: from `changed`, `add` collects attributes set to `on`, `remove`
   those set to `off`. Only these attributes are written, for Enter and
   Shift+Enter alike; attributes the user left unchanged are never written,
   including on descendants that differ from the chosen folder.
   When `changed` is empty (no edit, or every edit cycled back), the editor does
   nothing: no task, no I/O and no refresh, only the status message
   "No attributes changed." Cancellation does nothing either.
   - Consequence: Shift+Enter cannot push an attribute the chosen folders already
     share (folder Hidden on, a descendant off). The user sets it off and then on
     in two runs, or chooses the differing items. This keeps every write explicit.
5. **Apply** (a cancellable `fman.Task`):
   - Targets: the chosen items; with `'alternate'`, also every descendant of the
     chosen folders, walked top-down with `os.scandir`. Descendant attributes come
     from the listing (`DirEntry.stat(follow_symlinks=False)`, no extra call).
     Links and junctions met in the walk are skipped and counted; they are
     never written or traversed.
   - Per item, `new = (read & SETTABLE & ~remove) | add`, where `read` is the
     captured or listed value. `SETTABLE` holds the bits `SetFileAttributesW`
     documents as settable (R, H, S, A, T, Offline, Not content indexed,
     No scrub data, Pinned, Unpinned), so unrelated settable bits are passed
     back unchanged. Use `FILE_ATTRIBUTE_NORMAL` when `new` is 0. Skip the write
     when `new` equals `read`.
   - Write with `ctypes.WinDLL('kernel32', use_last_error=True).SetFileAttributesW`
     on the `\\?\`-prefixed path, raising `ctypes.WinError` on failure.
   - Progress: determinate for chosen items; text-only (current path) for a
     recursive walk, with no pre-scan. `check_canceled()` before each item.
   - The engine receives `lstat`, `scandir`, the writer and the notifier as
     parameters, so tests inject failures.
6. **Publish**: a folder whose direct children had at least one successful
   write is announced once with `fman.fs.notify_file_changed(folder_url)` when
   the walk leaves it; the chosen items' parent folder is announced at the end.
   Pending announcements are made in a `finally` block, so a cancelled or
   failing run still publishes its committed writes. A write is counted before
   its announcement; a failing notification is ignored and never retried.
   The host's file watcher then reloads every pane showing such a folder,
   deferred to the end of the task when live refresh is off. This replaces an
   explicit `pane.reload()` and the pane location tracking.
7. **Finalize**, after the apply task returns or is cancelled. Counters live on
   the task object, so they survive `Task.Canceled`, which `submit_task` absorbs:
   - Status message: changed, unchanged, skipped and failed counts, marked
     "Cancelled" when the run was cancelled.
   - Failures, if any: a `show_quick_table` (Path, Error) with the number of
     failures not listed.
   - Cancelling the capture changes nothing: status message only.
8. **Failure retention**: per-item failures (access denied, in use, vanished,
   unreadable folder) never stop the run. At most 1,000 failures are kept,
   paths elided in the middle to 1,024 characters and errors truncated to 256,
   well inside QuickTable's 16 MiB budget. Further failures are only counted.

### Static Model

User decision: attributes are gathered once and treated as static. The user is
responsible for other programs not changing them during the run.

- Chosen items are read when the command starts; descendants when the walk
  lists their folder. Nothing is read again before writing.
- Apply writes what the user chose on top of the values read: no re-reads,
  identity checks or revalidation. An item changed by another program in
  between gets the read value plus the user's changes; a vanished item fails
  with its OS error.
- Kept, as traversal rules on data already read rather than checks: chosen
  links and junctions are rejected at capture, and links and junctions in the
  walk are neither written nor traversed. This avoids junction cycles (such as
  `Application Data` in a user profile) and writes outside the chosen tree.
- Reading needs no write access (`os.lstat`, `os.scandir`). Only
  `SetFileAttributesW` needs it; a denied write is a per-item failure, and the
  walk still enters a readable folder whose own attributes could not be changed.

### Threading and Persistence

- Capture and apply run in `fman.Task` workers. The dialog call blocks the
  command's worker; QuickCheckList owns its Qt objects.
- No settings, files or Registry writes besides the attributes themselves.
  Mutable state does not exist between runs.

## Alternatives

- **Open Explorer Properties:** already available; it is mouse-driven, per
  selection and does not offer recursion for files.
- **Run `attrib.exe`:** a process per batch, locale-dependent output and weaker
  error reporting; rejected in favor of `SetFileAttributesW`.
- **Core command instead of a plug-in:** rejected by the user; this demonstrates
  a public-API plug-in shipped with the build.
- **QuickList or a Panel for the attributes:** rejected; see
  [UI Elements 004](UIElements004.md#alternatives).
- **Ask for recursion in a second dialog:** rejected; Shift+Enter keeps it one step.
- **Descendant-aware starting states or forced recursive reapplication:**
  rejected by the user. They need a recursive scan before the dialog opens or a
  wider QuickCheckList result, and could write attributes the user never changed.
- **Handle-based access with identity revalidation (previous revision):**
  rejected by the user in favor of the [static model](#static-model). The extra
  native calls and checks are not justified for an interactive edit whose
  inputs the user controls.

## Runtime Effects

- Startup: one more plug-in loaded with one command; no work until invoked.
- Per run: one `lstat` per chosen item at capture. Per target: at most one
  `SetFileAttributesW` call; descendants are read from the walk's listings.
  One notification per folder with changes. All I/O runs in cancellable tasks;
  an unchanged result runs none.
- Memory: at most 1,000 retained failures with bounded text.
- No threads beyond the tasks, no processes, timers or background jobs.
- Disabled path: the command is hidden outside local panes and does nothing else.

## Tests

- Unit, `fman_unittest/test_file_attributes_editor.py` (temporary folders),
  importing the plug-in through a fixture like `batch_file_renamer_fixture.py`.
  Junctions use `_winapi.CreateJunction`; symbolic-link cases skip when the
  privilege or Developer Mode is missing (expected skip):
  - Starting states: all, none, mixed; Temporary disabled with a folder.
  - Masks and merge: add/remove, preserving unrelated bits, `NORMAL` for 0.
  - No-op: no edit and edits cycled back produce no task and no I/O, for both
    approvals; folder on / child off and folder off / child on stay untouched
    with Shift+Enter; unrelated attributes are never written.
  - Apply to chosen items; recursive apply; links and junctions rejected when
    chosen and skipped (not traversed) when met during the walk.
  - Static model: apply performs no `lstat` of chosen items; an item changed
    after capture gets the captured value plus the user's changes.
  - Write access: a write-denied file still shows its state and can be
    cancelled; its failed write is reported and other targets continue; a
    write-denied folder with a writable child is still traversed.
  - Per-item failures are collected and the run continues; cancellation stops it.
  - Retention: more than 1,000 failures and long, non-ASCII paths and errors;
    retained data stays bounded and the rest is counted.
  - Publishing, through the injected notifier: each folder with changed children
    is announced once, the chosen items' parent at the end; a cancelled run
    announces its committed prefix; unchanged runs and runs cancelled before a
    write announce nothing; a failing notifier leaves the counts unchanged.
  - The plug-in imports no Qt, `fman.impl` or `core` module.
- Integration, `FileAttributesEditorPluginIT` next to `BatchFileRenamerPluginIT`:
  installed copy and spec-bundled copy (datas entry and discovery), driving the
  command through QuickCheckList with Enter and Shift+Enter, and checking the
  attributes on disk. Two panes on the affected folder and a third inside a
  recursively changed folder all update.
- Category test: add `plugins/FileAttributesEditor` to
  `BundledCommandCategoryTest` in
  [test_plugin.py](../src/integrationtest/python/fman_integrationtest/impl/plugins/test_plugin.py).
- Manual: toggle Hidden on a folder recursively and confirm the pane and Explorer
  agree; confirm a mapped network drive without write access reports failures
  cleanly.

Focused commands (from the repository root, with the environment on `PATH`):

```powershell
python -c "import build, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM']='offscreen'; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_unittest.test_file_attributes_editor'], env=env))"
python -c "import build, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_integrationtest.impl.plugins.test_plugin.FileAttributesEditorPluginIT', 'fman_integrationtest.impl.plugins.test_plugin.BundledCommandCategoryTest'], env=env))"
```

## Implementation Steps

1. Requires [UI Elements 004](UIElements004.md) to be implemented first.
2. Add `engine.py` (constants, starting states, masks, walk, apply) and its unit tests.
3. Add the command, capture and apply tasks, and the report in `__init__.py`.
4. Add the `application.spec` datas entry and any hidden imports; add
   `FileAttributesEditorPluginIT` and the category test entry.
5. Add the plug-in `README.md`; update [docs/tools.md](../docs/tools.md),
   [docs/features.md](../docs/features.md), [README.md](../README.md) and
   `CHANGELOG.md` (Added).

## Acceptance Criteria

- **Edit Attributes** opens a QuickCheckList showing the attribute states of the
  chosen items, with mixed states for differing items.
- Enter applies only the changed attributes to the chosen items; Shift+Enter,
  offered only with a folder chosen, applies them recursively without following
  links or junctions.
- When the final states equal the starting states, nothing is written for
  either approval.
- Attributes are read once and applied as read plus the user's changes; apply
  re-reads nothing. Writes never go through a link or junction.
- Unchanged attributes and unrelated bits are preserved; failures are listed and
  do not stop the run; cancellation stops it and keeps the partial results.
- At most 1,000 failures are retained.
- Every pane showing a folder with changed items updates, including after a
  cancelled run.
- The plug-in uses public APIs only and is present in a frozen build.
- Focused unit and integration tests pass.

## Review Findings (2026-10-31)

Planning review only. FAR01-FAR03 remain open decisions; they do not authorize
application changes. The public `DirectoryPane.reload(on_done=None)` exists,
so the planned refresh does not require a private host API.

### FAR01 - P2: Final-State Diffs Cannot Express Recursive Reapplication

- Failure case: a selected folder already has Hidden on, but a descendant has
  it off. QuickCheckList starts at `on`; Shift+Enter without changing that row
  returns no change. Cycling off and back on also returns no change. The plan
  exits on an empty `changed`, so neither interaction can apply Hidden on to
  those descendants. The same gap exists when a selected folder is off and
  descendants need that attribute cleared.
- Required decision: distinguish leave-unchanged from an explicit recursive
  target state. Choose whether the editor uses a separate operation-state model,
  descendant-aware starting states, or a deliberately extended result contract.
  Do not assume that all unchanged attributes should be propagated recursively;
  that would modify attributes the user never requested. Keep QuickCheckList's
  generic diff API unchanged unless its plan explicitly approves a revision.
- Checks: root on/child off and root off/child on, both approval modes, cycling
  back to the starting state, mixed selections, cancellation and a genuinely
  empty operation. Verify that unrelated attributes remain untouched.

### FAR02 - P2: Apply Does Not Revalidate Captured Targets or Link Policy

- Failure case: after capture or while the dialog is open, a chosen file can be
  replaced by another file, a link or a junction. The apply step rereads attribute
  bits but does not require identity/type/reparse revalidation before writing.
  A descendant directory can also become a junction after discovery and before
  `scandir`. This can change a replacement item or traverse outside the chosen
  tree, contrary to the exclusions and no-follow acceptance criterion.
- Required decision: record chosen-item identity/type/reparse metadata, reject
  stale chosen targets, and recheck the link policy before writes and descent.
  Address replacement of ancestor path components too. `lstat` followed by a
  path-based `SetFileAttributesW` or `scandir` is not atomic: either explicitly
  document best-effort no-follow behavior and its residual race, or select a
  compatible handle-based design for the stronger promise. Define deduplication
  for overlapping chosen folders and descendants so progress/counts are stable.
- Checks: replace a chosen item while the dialog is open; replace a discovered
  directory with a junction before traversal; replace a target before writing;
  choose both a parent folder and its child. Outside-tree sentinels must remain
  unchanged under the selected safety contract.

### FAR03 - P2: Failure Reports and Cancellation Need Bounded Finalization

- Evidence: capping the displayed report at 10,000 rows does not bound an error
  accumulator or its text. Many long paths/errors can exceed QuickTable's
  default 16 MiB text budget even within that row cap. The cancellation section
  gives only a status message; it does not require finalizing partial results or
  refreshing attributes already changed before cancellation.
- Required decision: cap retained error rows and aggregate bytes as failures
  occur, truncate display text to the table's field limits, and count discarded
  failures without retaining them. Finalize changed/unchanged/skipped/failure
  counts and perform the guarded pane refresh on success, partial failure and
  cancellation before showing any modal report. Define what is returned when
  cancellation interrupts capture versus apply and when the pane closes.
- Checks: more than 10,000 failures, long/non-ASCII path/error text reaching the
  byte budget, cancellation after a successful Hidden change, and pane closure
  during work. Memory must remain bounded, partial results must survive task
  cancellation, and the pane must not retain stale rows for committed changes.

### Review Validation

- Checked the public pane reload/location/closure API and Batch File Renamer's
  capture/report/refresh pattern. Checked the current QuickTable limits and
  Microsoft's [SetFileAttributesW contract](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileattributesw).
  No tests or runtime probes ran; this is an unimplemented design review.
- Read-only is not enforced on directories by Windows; documentation and manual
  checks should distinguish the stored bit from file write-protection semantics.
- The original design, exclusions and reviewer record are preserved. Resolve
  FAR01-FAR03 and the QuickCheckList validation contracts before implementation.

### Review Resolutions

| Finding | Resolution                                                                                                                                                                                                                                                                            |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FAR01   | User decision: only changed attributes are written; when the final states equal the starting states nothing happens, for Enter and Shift+Enter alike. Pushing an attribute the folders already share takes two runs or choosing the differing items. QuickCheckList's diff stays unchanged. |
| FAR02   | Superseded by the user's [static model](#static-model): attributes are read once and applied as read plus the user's changes, with no revalidation; the user owns concurrent changes. Links and junctions stay rejected when chosen and are never written or traversed in the walk. |
| FAR03   | Data-flow steps 7-8: at most 1,000 failures with truncated text and a counter for the rest; counters survive cancellation. Read-only on folders is documented as stored only. |
| FAR04   | Resolved by the static model: reading uses `os.lstat` / `os.scandir` without write access; only `SetFileAttributesW` needs it. A denied write is a per-item failure and the walk continues into readable folders. |
| FAR05   | Data-flow step 6: each folder with changed children is announced once through `fman.fs.notify_file_changed`, including after cancellation; the host's file watcher reloads every pane showing it. Replaces the explicit `pane.reload()` and pane tracking. |

## Implementation Review (2026-10-31)

The user-approved static model, no-change/no-operation behavior, bounded report
and per-folder publication were reviewed as the current contract. No concurrent
identity/revalidation requirement is reintroduced. IR01-IR02 are confirmed
implementation follow-ups; application code remains unchanged.

### IR01 - P2: Folder Publication Does Not Invalidate Cached Child Attributes

- Owner: `_notify` in
  [file_attributes_editor/__init__.py](../plugins/FileAttributesEditor/file_attributes_editor/__init__.py),
  `apply` in [engine.py](../plugins/FileAttributesEditor/file_attributes_editor/engine.py)
  and the host's
  [notification path](../src/main/python/fman/impl/plugins/mother_fs.py).
- Failure: native attribute writes bypass the local provider's cached `stat`.
  The parent-folder notification invokes callbacks but does not itself clear
  that cache. A later `ListingModel` rescan can invalidate it, but without such
  a rescan, cached public queries continue returning the pre-edit attributes.
  Observers querying metadata during publication can also see stale values.
- Probe: captured an owned file through the real local provider to populate its
  cache, then applied Hidden with the real engine/writer and public notifier.
  Two parent callbacks both ran and one write was counted. Native `lstat` showed
  Hidden on; `MotherFileSystem.query(file_url, 'stat')` still showed Hidden off.
  Explicitly clearing the parent cache made the query return Hidden on. The
  file's attributes were reset afterward.
- Follow-up: make publication invalidate affected metadata before observers
  query it, while preserving bounded/coalesced folder refresh. Keep the
  implementation on public APIs; do not misuse remove/add events or add an
  attribute reread to evade the approved static-input model.
- Coverage gap: the integration test uses a `Silent` filesystem and records
  callback names, so it cannot detect stale local-provider data. Add a real
  provider with a prepopulated child cache, including publication without an
  active pane and after partial cancellation.
- Limit: real provider/cache/writes and observers, not fully instantiated panes.
  This does not claim that a pane remains stale after its normal rescan finishes.

### IR02 - P2: Empty Selection Raises Instead of Returning Cleanly

- Owner: `EditAttributes.__call__` in
  [file_attributes_editor/__init__.py](../plugins/FileAttributesEditor/file_attributes_editor/__init__.py).
- Failure: `is_visible` is false without chosen items, but visibility is not an
  execution guard. A user-bound shortcut or direct command call in an empty
  pane can still invoke it. Capture returns an empty list and the dialog's
  summary indexes `entries[0]`, raising an uncaught `IndexError`.
- Probe: invoked the real command with an empty selection and no cursor item,
  an immediate task runner and mocked UI boundaries. One capture task ran,
  no checklist or normal alert opened, and `IndexError: list index out of range`
  escaped. Ordinary dispatch then routes that exception to plug-in error reporting.
- Follow-up: guard the chosen-item snapshot before capture and handle an empty
  result cleanly. Add a direct/key-bound invocation case in an empty folder;
  it should be a no-op or a concise user-facing alert, not a plug-in error.

### Review Validation

- Inspected capture/masks, native writer, traversal, failure retention,
  cancellation counters, notifications, public-only imports, spec inclusion and
  nearby tests. Editor diagnostics reported no errors in either plug-in module.
- Bounded generated probes ran as `python -X faulthandler -u -`, through
  `build._environment()` with a 20-second parent timeout. All file and settings
  inputs were disposable. No existing test targets or build/freeze ran; earlier
  implementation results were not independently rerun.
- Both Plan and Done copies of this task currently exist; the canonical move
  requirement still needs cleanup. No existing copy was removed by this review.

### Resolution (2026-10-31)

| Finding     | Resolution                                                                                                                                                                                                                                                                  |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| IR01        | Host: `MotherFileSystem.notify_file_changed`, behind the public `fman.fs.notify_file_changed`, clears the provider cache for the URL and everything below it before callbacks run. The plug-in is unchanged: each announced parent folder drops its children's cached metadata, with or without a pane and after cancellation. No re-read and no remove/add events. Documented in `PlugIn.md`. |
| IR02        | `EditAttributes.__call__` returns before any task with the status message "Edit attributes: no files selected." when nothing is chosen.                                                                                                                                   |
| Plan copies | The stale `Plan/` copy was deleted; only this `Done/` copy remains.                                                                                                                                                                                                         |

## Reviewers

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Designed with the user as a public-API plug-in shipped like Batch File
  Renamer, on QuickCheckList (`checkbox3`), with Enter for the chosen items and
  Shift+Enter for recursive application. Compressed/Encrypted, links and
  non-local file systems are out of scope. Depends on UI Elements 004.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Recorded FAR01 (recursive intent beyond final-state diffs), FAR02
  (stale targets, link races and overlapping recursion) and FAR03 (bounded error
  reports and cancellation finalization). Confirmed public pane reload support
  and checked the Win32 API contract. No implementation, tests or probes;
  original design and reviewer provenance preserved. Resolve the open contracts
  before implementation.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Resolved FAR01 with the user's decision (no change, no operation, for
  either approval), FAR02 (handle-based no-follow access, identity rechecks,
  deduplication, documented ancestor race) and FAR03 (bounded failure retention,
  cancellation-safe counters, ordered finalization). Ready for another review.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Request changes before implementation for FAR04-FAR05 below, in
  addition to the QuickCheckList custom-SVG dependency findings UIR03-UIR04.
  Keep the user's explicit no-change/no-operation behavior; FAR01 is resolved
  by that decision. Bounded failure retention and same-handle target checks are
  improvements over the earlier plan. No application implementation was made.

#### FAR04 - P2: Capture and Traversal Unnecessarily Require Write Access

- [Item Access](#item-access) requires `FILE_READ_ATTRIBUTES | FILE_WRITE_ATTRIBUTES`
  for the helper used during capture and descendant inspection, before the user
  chooses any edit. A readable item with an ACL denying attribute writes therefore
  prevents opening the editor at all. It also risks blocking descent through a
  readable folder whose own attributes cannot be changed, even when its children
  are writable, contrary to continuing after per-item write failures.
- Reproduced on an owned temporary file with an explicit deny for
  `FILE_WRITE_ATTRIBUTES`: `CreateFileW` with `FILE_READ_ATTRIBUTES` succeeded
  and returned metadata; the plan's combined access failed with WinError 5.
  The file contents and original DACL were restored/preserved afterward.
- Required: distinguish read-only inspection/capture/traversal from mutation.
  Request write access only when applying a non-no-op change, then re-read and
  validate identity/type/tag on that same writable handle before setting bits.
  Define whether a denied folder write still permits safe traversal of readable
  descendants. Close all acquired handles on every exit path.
- Tests: a selected readable/write-denied file can display its state and cancel;
  a changed write is reported without aborting other targets; a readable parent
  with denied attribute writes and a writable child follows the chosen recursive
  continuation policy. No-change approval must not request write handles.

#### FAR05 - P2: Direct Attribute Writes Do Not Publish Host Changes

- Finalization only reloads the original pane if it is open at the original
  folder. The apply path has no filesystem notification step. A second pane
  showing the same folder or an affected descendant remains stale; navigating
  or closing the invoking pane can also leave provider metadata cached after
  successful writes.
- Confirmed with the current local provider: after caching `stat`, a native
  Hidden-bit change was visible to `os.stat` but not the cached query, and two
  registered parent observers received no callback. Explicit parent notification
  reached both observers; invalidating that cache restored current metadata.
- The public [fman.fs notification functions](../src/main/python/fman/fs.py)
  already exist. [FileWatcher](../src/main/python/fman/impl/model/file_watcher.py)
  subscribes to the displayed directory and can defer/coalesce refreshes during
  tasks; a bare notification for a child URL is not a substitute for defining
  the required parent-directory notifications and cache invalidation.
- Required: specify host publication for every confirmed mutation, including
  partial failure/cancellation and an invoking pane that moved or closed. Use
  the public notification path and existing refresh policy, with bounded
  bookkeeping; do not introduce a full reload for every file. Keep the final
  guarded pane refresh for the caller's UX, not as the only publication step.
  Record a successful write before notification so callback failures cannot
  misreport it as an unmodified failure or cause a retry of the mutation.
- Tests: two panes on the affected directory; another pane inside a recursively
  changed folder; invoking-pane navigation/closure after a write; cancellation
  after a committed prefix; cached attribute queries and a failing notification
  callback. Unchanged and cancelled-before-write runs emit no change notifications.

#### Review Validation

- Reviewed the existing public pane/notification APIs, `LocalFileSystem.stat`,
  `ListingModel._request_scan`, and task-scoped `FileWatcher` refresh handling.
  Checked Microsoft's [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
  [SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle)
  and [FILE_BASIC_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_basic_info)
  contracts. Existing ancestor-replacement risk remains explicitly best-effort;
  this review does not demand a new native handle-relative traversal layer.
- Ran isolated `python -B -c <probe>` children through `build._environment()`,
  each with a 30-second timeout. FAR04 used a temporary file and temporary DACL,
  checking read-only success versus combined-access WinError 5. FAR05 used an
  owned file, real local provider cache and two parent callbacks; attributes,
  handles and callbacks were restored or closed in `finally` blocks.
- Initial access probes used constants absent from `win32con`; corrected to
  `ntsecuritycon` access masks and documented open flags before obtaining the
  decisive result. These are dependency/host probes, not tests of the proposed
  editor. No full suite, freeze, installations, user-file inspection or feature
  implementation. Current plan text and prior reviewer records are preserved.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Applied the user's static model: attributes are gathered once and
  applied as chosen without re-reads or revalidation, which supersedes FAR02 and
  resolves FAR04. Kept link/junction non-traversal as a traversal rule. FAR05:
  per-folder `notify_file_changed` replaces the explicit pane reload. FAR03
  simplified to 1,000 retained failures. Ready for another review.

### 2026_10_31 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the implementation within the approved static model.
  Recorded IR01 (cached attribute publication) and IR02 (empty selection) with
  disposable-probe evidence. No concurrent revalidation requirement reopened,
  application code changed or existing test targets rerun. Historical design,
  reviewer and implementer validation records preserved; both follow-ups remain
  open.

## Implementer

### 2026_10_31 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented after the user approved the static model.
  `plugins/FileAttributesEditor/` holds the README, the **Edit Attributes**
  command (`file_attributes_editor/__init__.py`) and the standard-library engine
  (`engine.py`: capture, starting states, masks, `SetFileAttributesW` writes,
  iterative walk with per-folder announcements, bounded report). The plug-in is
  bundled through the `application.spec` datas and uses public APIs only.
  Documented in `docs/tools.md`, `docs/features.md`, `README.md`, `UIElements.md`
  and `CHANGELOG.md`.

### 2026_10_31 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: User follow-up. Added the plug-in's `File Context Menu.yaml`
  (**Edit attributes...** after Properties), a Design Decisions table and a
  generated screenshot (`edit-attributes` capture in
  `generate_docs_screenshots.py`, also used for QuickCheckList), and
  `build._verify_bundled_plugins()`: `freeze` and `package` stop when any
  `plugins/` folder is missing from or differs in the frozen build.

### 2026_10_31 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Resolved implementation review IR01 (host cache invalidation in
  `notify_file_changed`) and IR02 (empty-selection guard) with regression tests.
  `CHANGELOG.md` (0.20.0) and `PlugIn.md` updated.

## Validation Results

- `fman_unittest.test_file_attributes_editor` (offscreen): 12 tests, 11 passed;
  the symbolic-link part of `test_capture_rejects_links_unc_and_missing_items`
  skipped as expected without Developer Mode (its junction, UNC and missing-item
  checks ran first and passed).
- `fman_integrationtest.impl.plugins.test_plugin.FileAttributesEditorPluginIT`
  (windows platform): installed and spec-bundled copies passed, driving the real
  QuickCheckList with Enter and Shift+Enter. Pane updates are verified through
  file-changed observers on a host `MotherFileSystem` (two on the parent folder,
  one inside the recursive folder), the path `FileWatcher` uses; full panes were
  not instantiated.
- `BundledCommandCategoryTest` and `BatchFileRenamerPluginIT` passed with the new
  spec entry.
- Not run: the manual Explorer comparison and the mapped network drive without
  write access. No frozen build was produced.
- Follow-up: `test_file_attributes_editor` (context menu after Properties, hidden
  outside `file://`), `test_app_name` (spec lists every `plugins/` folder;
  frozen copies must match), `EverythingBuildTest`, `test_generate_docs_screenshots`
  and `test_context_menu` passed (88 tests, one expected skip).
  `FileAttributesEditorPluginIT` (context menu loaded), `BundledCommandCategoryTest`
  and `BatchFileRenamerPluginIT` passed. The gallery test
  `test_edit_attributes_capture_shows_states_without_writing` and the batch renamer
  gallery test passed. A strict MkDocs build reported only screenshots that are
  generated in CI and absent locally. `freeze` itself was not run.
- Implementation review fixes: `fman_unittest.test_file_attributes_editor`
  (new `test_command_without_chosen_items_returns_cleanly` and
  `test_publication_refreshes_cached_local_metadata`: Core's real
  `LocalFileSystem`, prepopulated cache, no pane, full and cancelled recursive
  apply), `fman_unittest.impl.plugins.test_mother_fs` (new
  `test_notify_file_changed_clears_cached_children_before_callbacks`),
  `test_quick_check_list_data`, `test_listing`, `test_batch_file_renamer`,
  `test_everything` and `core.tests.fs.test_local` (offscreen): 248 tests passed,
  5 expected skips. `FileAttributesEditorPluginIT` (windows platform): 2 passed.
