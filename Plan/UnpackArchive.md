# Unpack Archive

## Task

Add the command `Unpack archive`: unpack one chosen archive into a new folder
in the current pane's directory, named after the archive without its recognized
suffix. For example, `Reports.zip` produces `Reports/` and keeps `Reports.zip`.

This is task (1). Shared extraction progress and cancellation belong to task
(2), [Archive Transfers](../Done/ArchiveTransfers.md), whose implementation and
focused checks are complete. This command remains pending; this document
replaces the old design.

## Scope

Included:

- One Core `DirectoryPaneCommand`, `UnpackArchive`, identified by
  `unpack_archive` and discoverable as `Unpack archive` in the Command Center.
- Exactly one chosen local archive. Use `get_chosen_files()`, including its
  cursor fallback when nothing is explicitly selected.
- The archive must be a file directly inside the invoking pane's captured local
  directory. Its new destination is inside that same directory.
- Core's configured `archive_handlers`; bundled suffixes are `.zip`, `.zipx`,
  `.jar`, `.xpi`, `.7z`, and `.tar`. Use the longest case-insensitive suffix
  match and a registered filesystem backend.
- Existing task/progress UI, concise errors, completion status, and best-effort
  cursor placement on the new folder without changing focus or navigation.

Excluded: a destination chooser or companion destination command, multiple
archives, merging/overwriting existing output, removing the source archive,
password prompts, new formats, nested/non-local archive extraction, and new
shortcuts or context-menu entries. Users extract elsewhere by entering the
archive and using the existing Copy workflow.

API compatibility: preserves the public `fman` plug-in API from fman 1.7.5.
This is an addition to the bundled Core plug-in, not a new public API or a
separate plug-in package. No build-path or packaging changes are needed.

## Design

### Ownership And Data Flow

Place the command and a small composite task beside `Pack` in
[Core commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py).
Reuse Core's archive-handler lookup. If returning the matched suffix requires
a private helper, preserve existing callers' behavior and return types. Keep
filename derivation pure and separate from filesystem validation.

1. Capture the invoking pane's directory and chosen URL through existing pane
   APIs. Validate exactly one direct-child local file and valid handler settings.
2. Remove the longest matching configured suffix. Reject an empty name, `.` or
   `..`; form the archive-root URL and the local destination URL.
3. Reject any existing destination entry, including a file, directory, or
   dangling link. Honor Windows case-insensitive conflicts. Never auto-number,
   merge, overwrite, or remove existing output.
4. Submit the composite task. On the command worker, prepare the whole archive
   with `fman.fs.prepare_copy(archive_root_url, destination_url)`, materialize
   the prepared tasks, and set the parent size to their summed sizes before
   `Task.run` delegates progress and cancellation to each child.
5. Set an explicit success flag only after all children finish successfully.
   `submit_task` swallowing `Task.Canceled` must not imply success.
6. Show a short completion status. If the original pane still exists and shows
   the captured directory, attempt cursor placement without stealing focus.
   Missing/filtered/not-yet-loaded rows are a best-effort miss, not extraction
   failure. Do not navigate the pane back if the user moved elsewhere.

Keep the command available like `Pack`; validate selection on invocation rather
than adding an I/O-performing palette visibility hook. This also avoids cursor
and selection disagreeing about command visibility.

### Backend Contract And Failures

The command never runs 7-Zip or implements extraction itself. Task (2) owns the
Core backend's progress, cancellation, temporary output, process lifetime, and
non-overwriting directory publication. Preflight is not race protection: a
destination created while extraction runs must survive unchanged, and the
command must report the conflict without success feedback.

Map expected missing-source, unsupported/unavailable-handler, malformed-archive,
permission, and process errors to concise existing alerts. Report a destination
conflict when the backend identifies one; do not mislabel every PermissionError
as a conflict. Unexpected programming errors use normal plug-in reporting.

Configured custom archive backends still use their registered `prepare_copy`
implementation and its directory-copy contract; progress/cancellation quality
depends on that backend. Do not claim Core's new guarantees for arbitrary
third-party filesystems. Unsupported configurations fail without source mutation.

Cancellation before publication leaves no final folder. After the short publish
commit, a completed folder is not rolled back. Cleanup failures preserve the
primary result and report leftover temporary output, as specified in task (2).

Core's existing archive-path splitter can misidentify an archive when a parent
directory contains an archive suffix, such as `backup.zip.old/Reports.zip`.
Correcting that parser is outside these two tasks. Cover the failure with a
concise alert and no false success; document the limitation until fixed.

### Threading And Persistence

Normal command dispatch already runs on a worker. Task execution stays on that
worker; UI calls use existing marshaling, and widgets/models stay on Qt. Capture
plain URLs before background work and do not read a changing pane as a target.

No persistent state, settings file, watcher, listener, timer, or dedicated worker
is added by the command. Core continues to own archive process execution.

## Alternatives

- Separate `UnpackArchive` plug-in: unnecessary packaging and handler-rule
  duplication. Core already owns the neighboring archive commands and settings.
- Destination prompt or second command: rejected. Existing archive-as-folder
  copying already supports arbitrary destinations.
- Merge into an existing folder: rejected for this command's deterministic
  new-folder workflow; ordinary Copy retains its existing conflict choices.
- Direct `7za.exe` or Python `zipfile` use: duplicates/bypasses the filesystem
  backend and its progress, cancellation, notifications, and format support.

## Runtime Effects

- Startup/unused path: one additional command registration, no feature-specific
  scans, settings reads, filesystem I/O, workers, timers, or recurring signals.
- Invocation: read existing cached Core settings (normal loader I/O on a cache
  miss), bounded selection validation and filesystem metadata checks, then one
  Core extraction. Invalid input starts no extraction process.
- CPU/disk cost scales with archive extraction; no duplicate archive scan or
  Python buffering of contents is added by the command. Prepared-task metadata
  is small for Core's single whole-archive task.
- The backend reads the archive, stages output beside the destination, and
  publishes on the same filesystem. Temporary siblings can be visible.
- Existing command worker and backend process/reader lifetime follow task (2).
  No persistent resources remain after success, failure, or cancellation.
- No new persistence or Registry writes. No separately configurable enable
  toggle is introduced; when unused this command performs no work.

## Tests

Add a focused `core.tests.commands.test_unpack_archive` module beside existing
Core command tests, and `UnpackArchiveIT` in the existing
`fman_integrationtest.test_qt` harness. These test IDs are planned, not yet
implemented. Required checks:

- Registration as `unpack_archive`, Command Center discoverability, and no new
  shortcut or context-menu registration.
- Cursor fallback, explicit selection overriding the cursor, zero/multiple
  chosen items, non-local/nested URLs, missing files, directories, malformed
  handler settings, and unavailable backends.
- `Reports.zip`, uppercase suffixes, spaces, `.zipx`, and longest-match custom
  suffixes such as `.tar.gz`; reject empty/dot/dot-dot output names.
- Existing files/directories/dangling links and Windows case variants are
  unchanged; late destination conflicts also produce no success feedback.
- Prepared task sizes are summed before running children; cancellation and
  preparation/extraction errors never set the success flag or delete the archive.
- Success status and best-effort cursor behavior when the pane stays, navigates
  elsewhere, closes, filters the output, or has not received its model update.
- Existing Pack/archive-open handler lookup behavior is preserved if its private
  implementation changes. Parent paths containing archive suffixes fail cleanly.
- Qt integration through the registered command and real Core backend: ZIP
  extraction creates the exact tree, retains the archive, updates the pane, and
  refuses reinvocation onto existing output. No worker touches Qt directly.

Focused commands from the repository root:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.commands.test_unpack_archive', 'core.tests.commands.test___init__', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_integrationtest.test_qt.UnpackArchiveIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='offscreen')))"
```

Manual: invoke the command on ZIP, 7Z, and TAR; inspect names, contents, retained
sources, status, and pane behavior. Cancel a large extraction, then retry with a
conflict and a malformed archive. Verify the source never changes. Performance:
compare with copying the same whole archive through the existing backend; the
command should add only validation/dispatch, not another extraction or scan.

Run the narrowest new command test immediately after its first code edit, then
the focused command and Qt checks. Reuse task (2)'s backend regression results
when its code is unchanged. Do not run the full suite, clean, or freeze unless
explicitly requested.

## Implementation Steps

1. Review the replacement design and complete the Core backend guarantees and
   focused validations specified by task (2).
2. Add naming/validation helpers and the command with focused Core command
   tests; run the narrowest relevant check immediately.
3. Add composite task sizing, outcome handling, and guarded completion feedback;
   verify failures, cancellation, and existing handler consumers.
4. Add the real registered-command Qt integration case and run manual checks.
5. When implemented, update the main README with the command, destination rule,
   conflict/cancellation behavior, and known path limitation; add an application
   CHANGELOG entry. No separate plug-in README or build-path registration.
6. Record exact validation results and implementation provenance, then move
   this canonical document to `Done/` and its index entry to Completed.

## Acceptance Criteria

- `Unpack archive` creates the suffix-free new folder inside the invoking pane's
  captured directory, preserves the source archive, and extracts the expected tree.
- Invalid input, existing output, and destination races do not modify existing
  entries or produce false success. Expected errors have concise alerts.
- Core extraction progress/cancellation uses task (2), not a command-specific
  implementation. Cancellation before publication produces no final folder.
- Completion does not steal focus or undo later pane navigation; cursor placement
  is explicitly best effort.
- No destination prompt/second command, shortcut, context-menu entry, idle work,
  packaging change, or public API break is introduced.
- Focused tests pass and required manual/performance outcomes are recorded;
  unavailable checks remain explicitly outstanding rather than claimed as passed.

## Reviewers

Historical records below are preserved verbatim for provenance. Their old
design recommendations and approval do not apply to this replacement; the
2026_09_16 replacement review at the end records the new scope.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context window: Not exposed by host
- Outcome: Designed a no-shortcut bundled extraction command that preserves the
  reference plug-in's sibling-folder workflow while reusing Core archive
  handlers, rejecting destructive conflicts, and adding required cancellation
  support to the owning extraction task.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved for implementation with the corrections below. The design
  is sound: reusing `prepare_copy` on the archive scheme means the plug-in is
  ~150 lines of validation plus one composite `Task`, and the `Extract`
  hardening is the right place for cancellation. The review verified the plan
  against `core/fs/zip.py`; the items below are gaps between what the plan
  claims and what Core actually does.

#### Follow Up Tasks

Design corrections (update the document before implementing):

- [ ] **Composite task size.** `Task.run(subtask)` reports progress through a
      `ChildProgressDialog` relative to the *parent's* size, and `submit_task`
      creates the progress dialog with `task.get_size()`. `_UnpackArchiveTask`
      must therefore call `self.set_size(sum(t.get_size() for t in subtasks))`
      after `prepare_copy` and before running them (as Core's `_Pack` does),
      otherwise the dialog shows 0/0 and the hardened `Extract` progress is
      invisible.
- [ ] **Destination race exception type.** With `path_in_zip == ''`, `Extract`
      finishes with `fman_fs.move(tmp_dir, dst)` →
      `LocalFileSystem._rename` → `Path.replace`. On Windows, replacing onto
      an existing *directory* raises `PermissionError` (`WinError 5`) or
      `FileExistsError` (`WinError 183`) depending on state. State that both
      are mapped to the `Destination already exists` alert; the current text
      names only `FileExistsError`.
- [ ] **Temporary-directory cleanup after cancel.** When `run_7zip_with_progress`
      kills `7za.exe`, the `finally: tmp_dir.cleanup()` in `Extract` can hit
      `PermissionError` on Windows while the killed process's handles are
      released, which would mask `Task.Canceled` with an unrelated error.
      Specify `TemporaryDirectory(..., ignore_cleanup_errors=True)` in
      `_create_temp_dir_next_to` (or a short retry) and add it to the Core
      cancel test.
- [ ] **Core `_split` limitation.** `_7ZipFileSystem._split` locates the
      archive by the *first* occurrence of a suffix in the lower-cased path.
      For `C:\backup.zip.old\Reports.zip` it splits at `backup.zip`, so
      `prepare_copy` raises `FileNotFoundError` or operates on the wrong
      path. Fixing `_split` is out of scope, but the plan must (a) list this
      as a known limitation in the README, (b) ensure the resulting
      `FileNotFoundError`/`_7zipError` surfaces as the concise alert, and
      (c) add a unit test with such a parent path asserting no traceback.
- [ ] **Cursor placement race.** `fman_fs.move` emits `notify_file_added`,
      which updates the pane model asynchronously on the worker; an immediate
      `place_cursor_at(destination)` may raise `ValueError` before the row
      exists and the plan currently swallows it, leaving the cursor on the
      archive. Either call `self.pane.reload()` first, or retry once after
      the model's next `location_loaded`/`transaction_ended`, or state
      explicitly that best-effort placement is acceptable. `CreateDirectory`
      has the same pattern; if best-effort is chosen, say so.
- [ ] **`is_visible()` vs `get_chosen_files()` mismatch.** Visibility uses the
      file under the cursor while invocation uses the selection. With one
      archive selected and the cursor elsewhere the command is hidden yet
      valid; with a non-archive selected and the cursor on an archive it is
      visible yet fails. Use the same rule for both: prefer
      `get_chosen_files()` when its length is 1 and fall back to the cursor.
- [ ] **`Extract` size and `-bsp1`.** `AddToArchive` relies on 7-Zip printing
      percentages to the pty without `-bsp1`. Confirm during step 1 that
      `7za x` does the same for the bundled 25.x build; if not, add `-bsp1`
      to the extract arguments. Record the observed output in the Core test
      fixture.
- [ ] **Existing-destination check must be case-insensitive on Windows.**
      `fman.fs.exists` on `file://` uses `Path.exists`, which is already
      case-insensitive on NTFS, so `reports/` blocks `Reports.zip`. State this
      so the behaviour is not read as a bug, and cover it in a test.

Clarifications (no design change):

- [ ] Scope says "user-added handlers are honored when their filesystem scheme
      is registered". Specify what happens when the suffix is configured but
      the scheme is not registered (`MotherFileSystem._split` raises
      `FileNotFoundError`): alert `No filesystem handles <scheme>`, no task.
- [ ] Runtime Effects: `is_visible()` calls `load_json('Core Settings.json')`
      on every palette open. It is served from the `Config` cache, so this is
      a dict lookup, but say so, since the section claims "no settings reads".
- [ ] Tests: the Core cancel test needs a fake `_7zip` that yields progress
      lines and records `kill()`; name the fixture so the `AddToArchive` test
      can share it later.
- [ ] Note in the README that the temporary `<name><random>.tmp` directory
      appears beside the destination during extraction (pre-existing Core
      behaviour) and disappears on completion or cancel.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Compared the plan with the current repository. Still pending: Core
  already provides archive browsing and extraction, but no UnpackArchive plug-in
  or dedicated tests exist. No application code changed. The preceding design
  corrections remain prerequisites, not implemented behavior.

#### Current Capability Comparison

- Existing: configured ZIP/ZIPX/JAR/XPI/7Z/TAR handlers, archive opening in a
  pane, copy/drag extraction and archive packing. `prepare_copy` already returns
  an `Extract` task for archive-to-local copies, including the entire archive.
- Existing: extraction into a temporary sibling directory, followed by the
  normal filesystem move and cache notifications. This is reusable machinery,
  not the planned one-command suffix-free destination workflow.
- Missing: `unpack_archive` registration, selection validation, automatic
  sibling naming, dedicated conflict/error alerts, completion status and cursor
  placement, plug-in documentation and test-path registration.
- Missing: extraction progress and cancellation. `Extract` still derives from
  `Task`, has default size zero and calls blocking `_run_7zip`; the progress
  helper exists for packing/renaming but is not used by extraction.
- Still relevant: composite task sizing, Windows destination-race handling,
  temporary cleanup/cancellation guarantees, cursor synchronization and matching
  selection/visibility rules. `_split` still uses the first suffix occurrence;
  directories such as `backup.zip.old` remain problematic.
- Update before implementation: the progress-output review refers to 7-Zip
  25.x, while `build.py` now pins 26.03. Validate extraction progress against
  that version. `_Pack` preallocates `len(files) * 100`; it does not dynamically
  sum prepared task sizes as the earlier review wording suggests.

#### Comparison Validation

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip.ZipFileSystemTest.test_extract_entire_zip', 'core.tests.fs.test_zip.ZipFileSystemTest.test_extract_subdir', 'core.tests.fs.test_zip.ZipFileSystemTest.test_extract_empty_directory', 'core.tests.fs.test_zip.ZipFileSystemTest.test_extract_file', '-v'], env=build._environment()))"
```

All four existing real-ZIP extraction tests passed. This verifies existing
whole-archive, subfolder, empty-directory and single-file extraction, not the
unimplemented command or cancellation guarantees. No full suite, build,
downloads, 7Z/TAR extraction or native cancellation checks were run.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Replaced the operative design with task (1), a Core `Unpack archive`
  command creating a new suffix-free folder in the current pane. Moved shared
  progress/cancellation design to task (2), Archive Transfers. No destination
  command or application implementation added; replacement awaits review.
