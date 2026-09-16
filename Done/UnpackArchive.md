# Unpack Archive

## Task

Add the command `Unpack archive`: unpack one chosen archive into a new folder
in the current pane's directory, named after the archive without its recognized
suffix. For example, `Reports.zip` produces `Reports/` and keeps `Reports.zip`.

This is task (1). Shared extraction progress and cancellation belong to task
(2), [Archive Transfers](../Done/ArchiveTransfers.md), whose implementation and
focused checks are complete. This document describes the new command and its
opt-in extraction guards, including the performance simplification; the
historical reviews below remain unchanged.

Readiness: implemented and focused automated checks passed. The two safety
blockers have regression coverage and guarded rejection paths. Ordinary archive
Copy/Move and the existing archive-path splitter are unchanged. Unverified manual
and environmental checks are listed under Validation Results.

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
  match and a registered Core extraction backend. Ambiguous parsing and other
  prepared-task types fail closed instead of falling back to ordinary copying.
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
Extract the existing lookup into `_get_archive_handler(name, handlers=None) ->
(suffix, scheme) | None`. Load `Core Settings.json` once per lookup (or use the
new command's already validated mapping), keep the stable descending
suffix-length sort and the existing `name.lower().endswith(suffix)` comparison.
Configured suffixes use the existing lowercase convention; filenames match
case-insensitively. `_get_handler_for_archive(name)` becomes a thin wrapper
returning only the matched scheme or `None`, preserving Pack and
ArchiveOpenListener behavior. Do not add backend registration checks or change
configuration normalization in this shared wrapper.

The new command validates handler configuration before using the lookup:
`archive_handlers` must be a mapping with nonempty, lowercase, dot-prefixed
suffix keys and nonempty scheme strings ending in `://`. Malformed settings
produce a concise alert, not a task. Keep suffix-free filename derivation pure
and separate from filesystem validation.

1. Capture the invoking pane's directory and chosen URL through existing pane
  APIs. Validate exactly one local file and valid handler settings. Both URLs
  must use `file://`; test direct-child membership with
  `fman.fs.samefile(dirname(chosen_url), captured_directory_url)`, not URL string
  equality or an unnormalized casefold. This resolves case, trailing separators
  and directory aliases using the existing filesystem identity contract. False
  means outside the captured directory; lookup errors abort with their useful
  filesystem message. Never fall back to a textual match after such an error.
2. Remove the longest matching configured suffix. Reject an empty name, `.` or
   `..`; form the archive-root URL and the local destination URL.
3. Reject any existing destination entry, including a file, directory, or
  dangling symlink/junction, with
  `os.path.lexists(as_human_readable(destination_url))`. `fman.fs.exists` alone
  follows links and is insufficient here. Use this same entry-existence probe
  when classifying a later failure. Native Windows path lookup handles case
  variants; do not enumerate siblings. Record that the destination was absent
  at preflight. Never auto-number, merge, overwrite, or remove existing output.
  Alert `Destination already exists: <name>` and return before task submission,
  metadata listing, staging, or extraction. The other pane is never consulted.
4. Submit the composite task. On the command worker, prepare the whole archive
   with `fman.fs.prepare_copy(archive_root_url, destination_url)`, materialize
   the prepared tasks, and require exactly one Core `Extract` task. Its opt-in
   guard checks an empty member path, `samefile` source identity, and the exact
   requested native destination. Set the parent size before `Task.run`
   delegates progress and cancellation to the guarded child.
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

The command never runs 7-Zip or implements extraction itself. The new opt-in
`Extract.require_new_directory` path reuses task (2)'s process reader,
progress/cancellation and cleanup. Preflight is not race protection: a
destination created while extraction runs must survive unchanged, and the
command must report the conflict without success feedback.

The backend lists and extracts the selected archive directly, without a snapshot
copy. Compare `os.stat` size and `st_mtime_ns` before listing and after extraction;
a mismatch fails without publication. This is a cheap best-effort check, not a
guarantee against concurrent changes. Editing or deleting the archive during
Unpack is unsupported. Unpack never writes or deletes the source archive.

Run a 7-Zip technical listing before extraction to reject duplicate and
casefold-equivalent paths, file/directory conflicts and ambiguous name mappings.
Retain cheap checks for absolute/traversing paths, Windows device names, alternate
data streams, trailing dots/spaces and characters 7-Zip may rewrite. Native probes
showed that 7-Zip can silently collapse or rename such entries with exit zero.
Directory markers support collision detection; other metadata, including sizes,
encryption and link flags, does not pre-reject entries. There are no artificial
entry-count, depth, field-count or record-length limits. Listing records are read
in full, while ordinary progress and retained diagnostics remain bounded. Listings
that cannot be parsed unambiguously may still be rejected.

Extract once into a temporary sibling's `contents` directory with `-y`,
literal-name handling and strict exit-zero policy. 7-Zip owns decompression,
CRC checks, links, attributes and extraction errors. No password UI is added.
There is no post-extraction tree walk or independent content verification.

Check only that the output root is an ordinary directory, not a symlink or
junction. After the final cancellation check, use Windows `os.rename` on that
ordinary directory. Unlike generic file move/replacement, this refuses existing
files, directories and links at the commit boundary. Notify the public filesystem
only after publication succeeds. The staging container is cleaned
on every exit. No new UI is introduced: retain existing progress/Cancel and
alerts, with no output-path chooser or replace/merge question.

Map expected missing-source, unsupported/unavailable-handler, malformed-archive,
permission, and process errors to concise existing alerts. Report a destination
conflict when the backend identifies one; do not mislabel every PermissionError
as a conflict. Unexpected programming errors use normal plug-in reporting.

At the composite's child-error boundary, preserve the original `OSError` unless
there is evidence of a failed publication. A `FileExistsError` or `PermissionError`
with `filename2` identifying the destination is that evidence for Core's native
rename path: compare `os.path.normcase(os.path.normpath(...))` of the native
paths. If preflight found no entry and `lexists` now finds one, report
`Destination already exists: <name>`. Otherwise report the original error.
Missing or different `filename2`, an inconclusive recheck, extraction/process
failure, and cleanup failure must not be relabeled just because the destination
now exists. In particular, publication may have succeeded before cleanup failed;
retain that completed output and report the cleanup problem, without success
feedback. Custom-backend errors lacking publication metadata keep their original
message. Do not catch `Task.Canceled` as an `OSError` or turn it into success.

Configured mappings still dispatch through registered `prepare_copy`, but the
new command accepts only the exact Core `Extract` type and validates its source
and destination before execution. Other task types are unsupported. This private
command restriction leaves existing third-party filesystem APIs and Copy/Move
semantics intact; it does not claim arbitrary plug-in preparation is sandboxed.

Cancellation before publication leaves no final folder. After the short publish
commit, a completed folder is not rolled back. Cleanup failures preserve the
primary result and report leftover temporary output, as specified in task (2).

Core's existing archive-path splitter can misidentify an archive when a parent
directory contains an archive suffix, such as `backup.zip.old/Reports.zip`.
Correcting that parser is outside these two tasks. Cover the failure with a
concise alert and no false success; document the limitation until fixed.

An output stem may itself look like an archive: `archive.zip.7z` produces the
ordinary directory `archive.zip`. Do not strip the second suffix or reject that
valid destination. `ArchiveOpenListener` skips directories, so ordinary browsing
of that output remains local. A later archive operation beneath it can hit the
same parser limitation when its backend recognizes an ancestor's suffix, for
example `archive.zip/Reports.zip`. This is not a failure of every file under
that directory. Cover both the successful initial unpack and a controlled later
parser failure, preserving sources and avoiding false success. The implementation
README must describe these cases and the visible temporary sibling directory.

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
- Unchecked `prepare_copy`: rejected after the reproduced wrong-source overwrite.
  Guard the exact Core task instead of redesigning the shared URL parser.
- Full archive snapshot: rejected for normal local use. Concurrent user changes
  are unsupported; preventing them does not justify an archive-sized copy on
  every invocation. Direct extraction keeps only a cheap size/mtime comparison.
- Post-extraction tree verification: removed as a redundant pass for this
  workflow. Naming checks prevent known collisions; 7-Zip handles extraction.
- Merge, skip or rename collisions: rejected because it can silently lose entries
  or change the requested tree. Lightweight naming checks reject those archives.

## Runtime Effects

- Startup/unused path: one additional command registration, no feature-specific
  scans, settings reads, filesystem I/O, workers, timers, or recurring signals.
- Invocation: read existing cached Core settings (normal loader I/O on a cache
  miss), validate the handler mapping, compare parent identities using `samefile`,
  and probe the destination with `lexists`, then perform guarded Core extraction.
  An error-path `lexists` recheck adds only metadata I/O. Invalid input starts no
  extraction process; validation introduces no directory enumeration or scans.
- CPU/disk cost includes one metadata listing and one extraction, with metadata
  probes before/after and at publication. No full archive copy, content hashing
  or post-extraction tree walk runs. The naming map uses memory proportional to
  represented paths (including implied parents) and their lengths; full listing
  records have no artificial cap. No file contents are buffered in Python.
- Temporary free space must hold extracted contents only, not a second copy of
  the archive. Publication stays on the same filesystem. Temporary siblings can be
  visible. Extraction byte size is not capped; no archive-bomb or crash-recovery
  guarantee is made. Storage failures retain the source and attempt cleanup.
- Existing command worker and backend process/reader lifetime follow task (2).
  No persistent resources remain after success, failure, or cancellation.
- No new persistence or Registry writes. No separately configurable enable
  toggle is introduced; when unused this command performs no work.

## Tests

Add a focused `core.tests.commands.test_unpack_archive` module beside existing
Core command tests, and `UnpackArchiveIT` in the existing
`fman_integrationtest.test_qt` harness. These test IDs now exist. Required checks:

- Registration as `unpack_archive`, Command Center discoverability, and no new
  shortcut or context-menu registration.
- Cursor fallback, explicit selection overriding the cursor, zero/multiple
  chosen items, non-local/nested URLs, missing files, directories, malformed
  handler settings, and unavailable backends.
- Direct-child identity: drive-letter/path case differences, trailing separators,
  and aliases of the same parent pass; genuinely different parents fail. Missing
  or inaccessible parents report their original error with no submitted task.
- `Reports.zip`, uppercase suffixes, spaces, `.zipx`, and longest-match custom
  suffixes such as `.tar.gz`; reject empty/dot/dot-dot output names. Uppercase
  filenames are supported; malformed/uppercase configured suffix keys produce
  a new-command configuration alert without changing the legacy wrapper.
- Existing files/directories/dangling links and Windows case variants are
  unchanged; late destination conflicts also produce no success feedback.
- Stub `exists=False` with `lexists=True` to cover dangling links without Windows
  symlink privileges; also test real dangling symlinks/junctions when supported,
  recording any privilege-related skips. Preflight must not submit a task.
- Inject native rename-shaped `FileExistsError` and `PermissionError` with the
  destination in `filename2`: a new entry maps to the conflict alert; an absent
  entry preserves the original error. Unrelated permission/process failures,
  missing error metadata and cleanup failure after publication preserve their
  own messages even when a destination exists. None emits success feedback.
- Prepared task sizes are summed before running children; cancellation and
  preparation/extraction errors never set the success flag or delete the archive.
- Success status and best-effort cursor behavior when the pane stays, navigates
  elsewhere, closes, filters the output, or has not received its model update.
- Existing Pack/archive-open handler lookup behavior is preserved if its private
  implementation changes. Add wrapper regression cases for matching, overlapping
  suffixes, uppercase filenames and no match: return scheme or `None`, not the
  helper's tuple. Preserve existing matching order and configuration semantics.
- Parent paths containing archive suffixes fail cleanly when the backend parser
  misidentifies the source. Real `archive.zip.7z` extraction creates `archive.zip`
  as a local directory; the listener does not rewrite opening it. A subsequent
  ZIP beneath that directory exercises the known parser failure and concise
  alert, without modifying either archive or claiming successful extraction.
- Qt integration through the registered command and real Core backend: ZIP
  extraction creates the exact tree, retains the archive, updates the pane, and
  refuses reinvocation onto existing output. No worker touches Qt directly.
- Native ZIP, 7Z, TAR and empty-archive extraction retains sources and produces
  exact contents. Wrong source/root/destination, overlapping suffixes, case and
  file/directory collisions, and names 7-Zip may rewrite fail before publication.
- Removing the snapshot and tree walk is verified by making Python archive/file
  opens and `Path.iterdir` fail during a successful extraction. Source size/mtime
  changes prevent publication; root-type checks and cancellation still clean up.
- More than 100000 entries, 128 components, 64 metadata fields and 4096-character
  records are accepted by the naming parser without truncating distinct names.
  Non-naming metadata is ignored. Native TAR symlinks reach 7-Zip, with an explicit
  privilege skip when Windows forbids creation; encrypted input reaches extraction
  and fails normally without a password prompt. Corrupt archives remain intact.
- Shared process-reader tests cover full listing records, bounded diagnostics,
  ordinary progress, quiet cancellation and process teardown. Ordinary archive
  Copy/Move verification must remain unchanged.

Focused commands from the repository root:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip.UnpackExtractionTest', 'core.tests.fs.test_zip.ArchiveProcessTest', '-v'], env=build._environment()))"
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip', 'core.tests.commands.test_unpack_archive', 'fman_integrationtest.test_qt.UnpackArchiveIT', 'fman_integrationtest.test_qt.ArchiveTransferIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

Manual: invoke the command on ZIP, 7Z, and TAR; inspect names, contents, retained
sources, status, and pane behavior. Cancel a large extraction, then retry with a
conflict and a malformed archive. Verify the source never changes. Performance:
the no-copy/no-rescan regression is the required check for removing those I/O
passes; no wall-clock speedup is claimed. Manual timing remains optional.

Run the narrowest new command test immediately after its first code edit, then
the focused command and Qt checks. Reuse task (2)'s backend regression results
when its code is unchanged. Do not run the full suite, clean, or freeze unless
explicitly requested.

## Implementation Steps

1. Review the replacement design and complete the Core backend guarantees and
  focused validations specified by task (2). That prerequisite is complete;
  add the opt-in exact-root, manifest and publication guards to close the later
  safety findings, without changing the shared parser or ordinary transfers.
2. Extract `_get_archive_handler` with the scheme-only compatibility wrapper,
  then add naming, `samefile`/`lexists` validation and the command with focused
  Core tests; run the narrowest relevant check immediately.
3. Add composite task sizing, outcome handling, and guarded completion feedback;
  verify publication-specific conflict classification, cancellation, cleanup
  errors and existing handler consumers.
4. Add the real registered-command Qt integration case and run manual checks.
5. Keep detailed command usage, conflict/cancellation behavior and known path
  limitations in the Core README, with a brief link from the main README.
  Update the application's unreleased CHANGELOG entry; no build-path change.
6. Record exact validation results and implementation provenance, then move
   this canonical document to `Done/` and its index entry to Completed.
7. For the performance follow-up, remove the snapshot and output-tree walk,
  simplify metadata checks, and keep full listing names. Immediately validate
  each edit, then run the focused backend/command/Qt gate and align this document.

## Acceptance Criteria

- `Unpack archive` creates the suffix-free new folder inside the invoking pane's
  captured directory, preserves the source archive, and extracts the expected tree.
- Invalid input, existing output, and destination races do not modify existing
  entries or produce false success. Dangling entries are conflicts; equivalent
  Windows parent spellings pass direct-child validation. Expected errors have
  concise alerts, with unrelated failures retaining their original meaning.
- Core extraction progress/cancellation uses task (2), not a command-specific
  implementation. Cancellation before publication produces no final folder.
- Unpack performs no full archive copy or output-tree verification walk. Naming
  checks retain known collision/rewrite guards without arbitrary metadata limits;
  7-Zip owns attribute handling and extraction failures. Concurrent source changes
  remain unsupported, with only best-effort size/mtime mismatch detection.
- Completion does not steal focus or undo later pane navigation; cursor placement
  is explicitly best effort.
- No destination prompt/second command, shortcut, context-menu entry, idle work,
  packaging change, or public API break is introduced.
- Focused tests pass and required manual/performance outcomes are recorded;
  unavailable checks remain explicitly outstanding rather than claimed as passed.

## Reviewers

Historical records below are preserved verbatim for provenance. Their old
design recommendations and approval do not apply to this replacement; the
2026_09_16 replacement and follow-up reviews record the current scope and
resolutions. Previous checkboxes are historical, not current implementation status.

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

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved for implementation with the four corrections below.
  Verified the replacement design against the post-task-(2) code: with
  `path_in_zip == ''`, `Extract` stages into a sibling `.tmp` directory,
  publishes via `fman_fs.move` -> `LocalFileSystem._rename` -> `os.rename`
  (Windows directory), which refuses an existing destination including a
  differently cased one, and `_cleanup_extraction` tolerates the moved
  staging directory; an empty archive yields an empty folder. `Extract` is
  size 100, so `set_size(sum(...))` on the root composite before `Task.run`
  is correct (the root dialog accepts `set_task_size`; only attached children
  do not). `_get_handler_for_archive` returns the scheme only, as the design
  anticipates. Disposition of my 2026_09_13 Follow Up Tasks, left unticked
  for provenance: composite size, destination race type, cleanup after
  cancel, `-bsp1`/26.03, and case-insensitive conflict are resolved by task
  (2); `_split` limitation, best-effort cursor and the selection/visibility
  rule are carried into this design; the fake `_7zip` fixture exists as
  `FakePipeProcess`; the README temporary-sibling note remains due at step 5.

#### Follow Up Tasks

- [ ] **Dangling links.** Step 3 rejects "dangling link" destinations, but
      `fman.fs.exists` on `file://` uses `Path.exists`, which returns False
      for a dangling symlink/junction. Use `os.path.lexists` (or
      `Path.is_symlink() or Path.exists()`) in the preflight and add the
      test case.
- [ ] **Conflict classification after backend failure.** `Extract` does not
      translate `os.rename`'s `FileExistsError`/`PermissionError`; the
      composite must decide. Specify: on `OSError` from the child, if the
      destination exists now and did not at preflight, report
      `Destination already exists`; otherwise report the original error.
      This satisfies "do not mislabel every PermissionError as a conflict".
- [ ] **Private helper shape.** Name the helper: `_get_archive_handler(name)
      -> (suffix, scheme) | None` using the existing longest-suffix sort, and
      reimplement `_get_handler_for_archive` as a thin wrapper so `Pack` and
      `ArchiveOpenListener` behave identically. Add one regression asserting
      the wrapper's return values are unchanged.
- [ ] **Direct-child check.** "A file directly inside the invoking pane's
      captured directory" should compare `dirname(url)` to the captured
      path after normalisation (`fman.fs.samefile` or `as_human_readable`
      casefold), not by string equality, because pane paths and chosen URLs
      can differ in case or trailing separator on Windows.
- [ ] **Stem containing another suffix.** `archive.zip.7z` unpacks to a
      *directory* named `archive.zip`; `ArchiveOpenListener` already skips
      directories, but `_split` will misparse paths beneath it. Fold this
      case into the documented `_split` limitation and the corresponding
      test.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Resolved all five corrections in the latest review (its outcome
  says four, but five are listed). Accepted four directly and narrowed conflict
  classification to publication-specific evidence so unrelated or post-publication
  cleanup failures retain their meaning. Planning only; command implementation,
  new command tests and Qt/manual validation remain pending.

#### Feedback Resolutions

- [x] **Dangling links:** [Ownership And Data Flow](#ownership-and-data-flow)
  specifies local `lexists` for preflight and error rechecks. Tests include
  privilege-independent stubs and native link cases with explicit skips.
- [x] **Conflict classification:** [Backend Contract And Failures](#backend-contract-and-failures)
  requires a publication-related `FileExistsError`/`PermissionError`, matching
  destination metadata and a newly present entry. Rejected the blanket rule
  for every child `OSError`: a corrupt archive, inaccessible input or failed
  cleanup is not a destination conflict merely because a path exists now.
- [x] **Private helper:** `_get_archive_handler` returns the matched pair or
  `None`; `_get_handler_for_archive` keeps its scheme-only contract and existing
  lookup semantics. New-command configuration validation does not change Pack
  or ArchiveOpenListener behavior. Wrapper regressions are required.
- [x] **Direct-child check:** use public `fman.fs.samefile` on the chosen parent
  and captured directory, after checking both schemes. It honors filesystem
  identity and aliases; comparison errors abort rather than falling back to
  raw strings. Case/separator and different-parent tests are specified.
- [x] **Stem containing another suffix:** retain `archive.zip` as the valid
  local output of `archive.zip.7z`; distinguish normal directory browsing from
  later archive operations affected by the parser limitation. Tests and the
  eventual README must cover both outcomes and temporary siblings.

#### Review Validation

- Checked the existing lookup/listener in
  [Core commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py),
  URL conversion in [fman.url](../src/main/python/fman/url.py), dispatch in
  [MotherFileSystem](../src/main/python/fman/impl/plugins/mother_fs.py), and
  Windows publication in
  [LocalFileSystem](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py).
- Structural, relative-link and editor-diagnostic checks apply to this document
  only. Planned implementation tests above have not been run. No application,
  README, changelog, task index or release files changed in this planning pass.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Safety review found two reproducible blockers in the backend the
  planned command would reuse. Wrong-source parsing can bypass non-overwriting
  directory publication, and colliding archive entries can silently collapse.
  Do not implement the command as an unchecked `prepare_copy` wrapper. Sources
  survived the probes, but an unrelated late destination file was overwritten.
  No application code changed; remediation design and regressions remain due.

#### Safety Findings

1. **P1: wrong archive and destructive file publication.**
   [`_split`](../src/main/resources/base/Plugins/Core/core/fs/zip.py#L220) chooses
   the first suffix occurrence, not necessarily the selected archive boundary.
   With a selected `backup.zip.old/Reports.zip` and a sibling `backup.zip`
   containing `.old/Reports.zip`, preparation selects the sibling archive and
   that member. Extraction can succeed instead of producing the assumed parser
   error. A file member is then published through
   [`Path.replace`](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L159),
   not the non-overwriting directory branch. A destination file appearing after
   preflight is overwritten without an error. The command's error classification
   cannot help when the backend returns success. Overlapping suffixes add another
   ambiguity: testing `.zip` before `.zipx` splits `Reports.zipx` into archive
   `Reports.zip` and member `x`.
2. **P2: successful extraction can silently omit colliding entries.**
   [`Extract`](../src/main/resources/base/Plugins/Core/core/fs/zip.py#L388) invokes
   7-Zip with `-y`. A ZIP containing `report.txt` and `REPORT.TXT` returned success
   on Windows but produced only the second entry's contents. Exit zero and a
   present output directory do not prove every member was represented. The
   original archive remains intact, but reporting a complete unpack is incorrect.

#### Required Safety Gates

- Before extraction, prove that the backend targets exactly the selected local
  archive and its root (empty member path); fail closed for ambiguous parsing.
  A command-side longest-suffix match alone cannot establish that invariant.
  Keep the broad parser redesign excluded unless separately approved, but do
  not replace this guard with a README warning or assume the backend will fail.
- Require publication of a directory, with non-replacement enforced at the
  publication boundary even after preflight. A late file, directory, symlink or
  junction must survive. Custom backend mappings must not silently fall back to
  file-copy semantics for this new-folder command.
- Decide and test a no-silent-loss policy for duplicate and Windows-equivalent
  member paths, including case collisions. Reject unrepresentable collisions
  before publication, or fail extraction without publishing. Do not silently
  rename entries, drop entries or overwrite one member with another.
- Add focused regressions reproducing both findings and overlapping `.zip`/
  `.zipx` suffixes, plus the ordinary successful and canceled whole-root paths.
  Source preservation, exact output contents/type, retained late destinations
  and absence of success feedback on rejection are acceptance conditions.

#### Safety Probe Results

Ran native backend probes using `python` with `build._environment()`, Core's
`ZipFileSystem`/`StubFS`, bundled 7-Zip and disposable `TemporaryDirectory`
fixtures. Archive creation used Python `ZipFile`; no user archives were touched.

- Created the selected and sibling archives described in finding 1. Confirmed
  the destination was absent, prepared the task, then injected creation of a
  destination file after 7-Zip extraction and before publication. The task
  returned success, output was a file rather than a directory, and its previous
  bytes were replaced by the sibling archive's member. SHA-256 comparisons
  confirmed both archive files were unchanged.
- Extracted a two-entry ZIP with the case-colliding names in finding 2. The
  backend returned success with one output file containing the second entry.
  The source archive SHA-256 was unchanged.
- Called `_split('C:/data/Reports.zipx')` with suffix iteration order
  `('.zip', '.zipx')`: returned `('C:/data/Reports.zip', 'x')`. This demonstrates
  the ordering-dependent ambiguity, not a guaranteed order for the default set.

These are confirmed backend counterexamples, not tests of an implemented Unpack
command. No full suite or release checks ran. Malicious link/path traversal,
resource-exhaustion and concurrent parent-directory replacement were not tested;
this review does not establish sandboxing or crash-recovery guarantees.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the opt-in Core extraction design against both reproduced
  safety failures. Require exact source/root/destination, snapshot-based listing
  and extraction, strict entry/tree checks, and non-replacing directory rename.
  Other prepared task types and ambiguous paths fail closed. The user clarified
  that ordinary progress/Cancel and alerts remain, with no destination chooser;
  output belongs to the invoking pane's captured current directory. Extra I/O,
  conservative archive rejection and non-sandbox/crash limitations are explicit.

## Implementer

### 2026_09_16 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented the Core command, opt-in safe extraction path, native
  regressions and registered-command Qt integration. Output is fixed to the
  invoking pane; no path prompt, shortcut or custom UI was added. Both confirmed
  unsafe cases now fail closed. The focused gate passed 204 tests with one
  expected privilege-related skip. README and changelog describe behavior and
  conservative restrictions. No public fman API or release/build setting changed.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review; approved. Independently re-ran the final
  focused gate: 204 tests, OK, one symlink-privilege skip (126 s), 7Z/TAR
  smoke 0.15 s each. Verified against `core/commands/__init__.py` and
  `core/fs/zip.py` that all five of my 2026_09_16 Follow Up Tasks are
  implemented: `os.path.lexists` preflight; conflict classification only for
  `FileExistsError`/`PermissionError` whose `filename2` normcase-matches the
  destination and only when `lexists` now finds an entry; `_get_archive_handler
  -> (suffix, scheme)` with `_get_handler_for_archive` as a scheme-only
  wrapper; `samefile(dirname(source), directory)` for direct-child identity;
  `archive.zip.7z -> archive.zip` documented and tested. Both P1/P2 safety
  gates are closed in code: `Extract.require_new_directory` refuses a
  non-empty member path, a non-`samefile` archive and a different destination
  before any process starts; the guarded path snapshots the archive with a
  size/mtime check, builds a casefold manifest from a strict `-slt` listing
  (collisions, traversal, device names, trailing dot/space, encrypted/linked
  entries, 100000/128/64/4096 bounds), extracts with `-aos`, verifies the
  staged tree by name/type/size/nlink, and publishes with `os.rename` after a
  final cancellation check. `_UnpackArchive` accepts only the exact `Extract`
  type, sums child sizes before `run`, and sets `succeeded` only after all
  children complete; `Task.Canceled` is not caught. Observations, no action
  required: (1) the full-archive snapshot copy doubles I/O for large archives
  (documented in Runtime Effects and the Core README); a same-volume hard link
  would avoid the copy but not the mutability concern, so the copy is the
  correct trade-off. (2) `_unpack_new_directory` raises `UnsupportedOperation`
  off Windows, consistent with the repository's Windows-only scope. (3) The
  extracted-byte size is uncapped, as stated. Noted that the 20-item Move
  timing test requested in the Archive Transfers review now exists in
  `test_zip` and prints 1.49 GB of archive reads for a 64 MiB ZIP, confirming
  the follow-up's premise. README, Core README, CHANGELOG and the `Plan.md`
  index are consistent with the implemented change.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: User decision: the implementation over-protects. Guards that fix
  the two reproduced findings stay; guards that treat a user-chosen local
  archive as hostile input, or that reject archives 7-Zip would extract
  correctly, are to be removed. The user explicitly accepts no protection
  against self-inflicted misuse (for example editing an archive while it is
  being unpacked). Recorded as the follow-up checklist below for a separate
  simplification task (`Plan/UnpackArchive002.md`) so the accepted P1/P2
  regressions remain the acceptance gate.

#### Follow Up Tasks

Keep, unchanged (each closes a reproduced defect or is free):
`Extract.require_new_directory` (`samefile` archive identity, empty member
path, exact destination); exact `Extract` type check in `_UnpackArchive`;
`lexists` preflight and `os.rename` publication; casefold collision rejection
in the manifest; `succeeded` set only after all children; `Task.Canceled`
not swallowed.

- [ ] **Drop the archive snapshot copy.** Remove the 1 MiB block copy to
      `temporary/archive`; list and extract the original path. Keep a single
      `os.stat` before listing and after extraction, comparing size and
      `st_mtime_ns`; on mismatch fail with `Archive changed while being read`
      and do not publish. Update Runtime Effects (no doubled I/O, temporary
      space = extracted contents only) and the Core README.
- [ ] **Reduce the manifest to collision detection.** Keep the `-slt` listing
      and the casefold `explicit`/`manifest` maps that reject duplicate and
      Windows-equivalent paths. Remove: device-name regex, trailing dot/space,
      control-character and `<>:"|?*` checks, `..`/absolute rejection (7-Zip
      already refuses these), encrypted/symlink/hard-link/special-attribute
      rejection, depth 128, 64-field, 4096-character and 100000-entry limits,
      and the `Ambiguous archive metadata` branch. Any entry Windows cannot
      create is left to 7-Zip's exit code.
- [ ] **Drop `_verify_unpack_tree`.** Remove the post-extraction walk that
      compares name/type/size/`st_nlink` against the manifest, and remove
      `-aos` (no longer needed once collisions are rejected up front; restore
      `-y` for parity with ordinary `Extract`). Exit code 0 from 7-Zip is the
      completeness criterion, as for every other extraction in Core.
- [ ] **Update tests.** Delete or invert the fixtures that assert rejection of
      device names, trailing dots, links, encrypted entries, depth/field/record
      limits and staged-tree mismatch. Keep and re-run: wrong-archive/member,
      overlapping `.zip`/`.zipx`, case collision, existing output, late
      destination, cancellation, cleanup failure, `archive.zip.7z`, and the
      new stat-mismatch case. Add one positive case: a tarball containing a
      symlink now unpacks (7-Zip creates it or skips it per its own rules)
      instead of being rejected.
- [ ] **Docs.** Shorten the Core README `Unpack Archive` restrictions to: new
      folder only, one archive, collisions rejected, source never modified.
      Add a CHANGELOG `Changed` entry when implemented.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Agree with removing the full-archive snapshot and post-extraction tree
  walk for normal local archive use. Concurrent user edits/deletion are outside
  the supported workflow; they do not justify an archive-sized read/write copy
  on every unpack. Retain exact source/root/destination checks, no-replacement
  publication, cancellation/cleanup, and lightweight collision detection. The
  simplification checklist needs the correction below before implementation.

#### Simplification Review Correction

- Do not assume 7-Zip rejects every unrepresentable path or that exit zero proves
  distinct archive members survived. Native disposable ZIP probes using the
  bundled `_7zip` with `x -y -spd` and strict exit handling returned exit zero:
  `report.txt` plus `../report.txt` produced only `report.txt`, containing the
  second entry's bytes; `report.txt.` became `report.txt_`; `NUL.txt` became
  `_NUL.txt`. All original archive bytes were retained. These cases require no
  concurrent user action and are not addressed by raw casefold comparison alone.
- Remove the snapshot and tree walk, but retain cheap rejection of path forms
  whose extraction mapping is ambiguous, or validate collisions using verified
  7-Zip output-name semantics. Do not duplicate a full extraction engine to do so.
  This work belongs in the existing metadata pass and needs no content reads.
- Removing the 4096-character manifest check alone is insufficient: the shared
  `progress_records` reader currently truncates records at 4096 characters. A
  simplified metadata parser must not treat truncated names as complete names.
- A size/mtime comparison before/after extraction is an inexpensive best-effort
  check, not a guarantee against concurrent changes. Keep the ordinary extraction
  failure behavior and make no promise to support concurrent archive modification.
- No application code changed in this review. No new task document was created.

### 2026_09_16 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Implemented the reviewed performance simplification in the existing
  task. Removed the archive snapshot and output-tree walk; kept best-effort stat
  checks, exact source/root/destination checks, naming collision/rewrite guards,
  root-directory checks, cancellation/cleanup and non-replacing publication.
  Removed arbitrary metadata limits and attribute bans; listing names are read
  in full with bounded diagnostics. Ordinary Copy/Move verification is unchanged.
  The focused gate passed 126 tests with two Windows symlink-privilege skips.
  Core usage and the existing unreleased feature entry now describe the lighter
  path. No separate follow-up document or redundant unreleased fix entry was
  created; the historical checklist and review correction remain preserved above.

## Validation Results

### Original Implementation

Original focused gate from the repository root, before the simplification:

```powershell
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip', 'core.tests.commands.test_unpack_archive', 'core.tests.commands.test___init__', 'fman_integrationtest.test_qt.UnpackArchiveIT', 'fman_integrationtest.test_qt.ArchiveTransferIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- Result: 204 tests in 124.652 seconds; 203 passed, one skipped because creating
  a symbolic link requires unavailable Windows privileges. Stub dangling-entry
  checks and real preflight/late dangling-junction tests passed. Duplicate ZIP
  name fixture creation emitted the expected Python warning.
- The first code edit was checked immediately with
  `core.tests.fs.test_zip.ArchiveProcessTest.test_unpack_rejects_wrong_archive_or_member`
  and `core.tests.fs.test_zip.ArchiveProcessTest.test_unpack_existing_output_never_extracts`
  using the same `build._environment()` unittest launcher: two passed in 0.004s.
- Incremental checks passed after each subsequent code edit: native Unpack
  extraction, command naming/validation/outcomes, and registered-command Qt
  dispatch. No-path-prompt assertions apply to every command regression.
- Native fixtures cover ZIP, 7Z, TAR, empty directories/archives, exact bytes,
  source retention, wrong-root parsing, overlapping suffixes, case/duplicate
  collisions, unsafe names, links, encrypted/corrupt input, missing staged output,
  late destinations, cancellation, cleanup failure and source changes after
  snapshot creation. Qt tests cover worker dispatch, existing progress handling,
  model publication, cursor placement and existing-output refusal.
- Performance procedure: created a disposable stored ZIP containing 32 files of
  1 MiB each plus an empty directory; ran ordinary `Extract` once, then guarded
  `Extract.require_new_directory` once under `build._environment()`. Checked all
  bytes, source equality and absence of temporary siblings. Baseline 0.321s;
  guarded 0.319s. This warm-cache single sample has no speed threshold and does
  not establish equivalent throughput or remove the documented extra I/O.
- Editor diagnostics: no errors in the five changed Python files. Task required
  sections and relative links passed a PowerShell structural check.
- Not run: a separate interactive GUI session, privileged native symlink cases,
  large-archive manual cancellation, full repository suite, clean/freeze/package,
  or release workflow. Shared native process cancellation and the new task's
  pre-publication cancellation are covered by automated tests; interactive
  release smoke remains outstanding.
- No claim of protection against malicious concurrent parent/staging replacement,
  decompressor vulnerabilities, disk exhaustion, crash/power loss or arbitrary
  third-party plug-in code. Metadata limits are not an extracted-byte limit.

### Performance Simplification

Commands run from the repository root:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip.UnpackExtractionTest', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip.UnpackExtractionTest', 'core.tests.fs.test_zip.ArchiveProcessTest', '-v'], env=build._environment()))"
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip', 'core.tests.commands.test_unpack_archive', 'fman_integrationtest.test_qt.UnpackArchiveIT', 'fman_integrationtest.test_qt.ArchiveTransferIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- Immediately after removing the snapshot/tree walk: 18 tests in 5.055s, one
  Windows destination-symlink privilege skip. The no-copy/no-rescan assertion,
  source-stat mismatch, output-root type, cancellation and conflict cases passed.
- Immediately after simplifying metadata and the reader: 35 tests in 6.237s,
  two privilege skips. Full listing records and bounded ordinary progress passed;
  encrypted input reached 7-Zip extraction instead of being rejected by metadata.
- Final focused gate: 126 tests in 123.363s, 124 passed and two skipped. These
  skips cover native destination symlinks and TAR symlink creation, both requiring
  unavailable Windows privileges. Stub dangling-entry and native junction tests
  passed. The duplicate-name ZIP fixture emitted its expected Python warning.
- Performance evidence is structural: successful native extraction with Python
  archive/file opens and output enumeration disabled proves the removed passes
  do not run. No new throughput benchmark or numeric speedup is claimed. The
  ordinary archive Move verification tests remain unchanged and pass.
- Editor diagnostics reported no errors in all five edited files. A PowerShell
  documentation check passed for three documents and 14 relative links, required
  task sections, removal of obsolete user-facing claims and release API statements.
- Not run: interactive GUI/manual large-archive cancellation, privileged native
  symlink success, full repository suite, clean/freeze/package or release checks.
  Registered-command Qt integration and native process cancellation passed.
