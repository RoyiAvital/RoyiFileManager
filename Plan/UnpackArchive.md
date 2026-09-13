# Unpack Archive

## Task

Add a bundled plug-in named `UnpackArchive` with a Command Center command
`Unpack Archive`. The command extracts one chosen local archive into a sibling
directory whose name is the archive filename without its recognized suffix.
For example, `Reports.zip` is unpacked into `Reports/`.

The behavior is inspired by
[thomas-haslwanter/fman_unzip](https://github.com/thomas-haslwanter/fman_unzip),
but uses RoyiFileManager's existing archive filesystems and bundled `7za.exe`
instead of Python's `zipfile`. No default keyboard shortcut is added.

## Scope

Included:

- One `DirectoryPaneCommand`, `UnpackArchive`, with command identifier
  `unpack_archive` and aliases `Unpack archive` and `Extract archive`.
- Exactly one chosen local archive per invocation. Selection follows
  `get_chosen_files()`, so the file under the cursor is used when there is no
  explicit selection.
- Archive formats configured in Core's `archive_handlers` mapping. Bundled
  defaults are `.zip`, `.zipx`, `.jar`, `.xpi`, `.7z`, and `.tar`; user-added
  handlers are honored when their filesystem scheme is registered.
- A destination beside the archive, named by removing the longest matching
  configured suffix case-insensitively.
- Background extraction through `submit_task`, `fman.fs.prepare_copy`, and the
  existing archive filesystem task. On success, place the cursor on the new
  directory and show a short status message.
- Progress and cancellation for Core archive extraction.
- Command Center access only. Do not add a key binding or context-menu entry.

Excluded:

- Multiple archives in one invocation, destination prompting, merging into or
  overwriting an existing destination, password prompting, deleting archives
  after extraction, and adding new archive formats.
- Extracting non-local archive URLs. Core archive backends currently require an
  operating-system path for the containing archive.
- A second 7-Zip process wrapper or direct use of Python `zipfile`.
- Changes to the public `fman` plug-in API.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
plug-in can be removed without affecting Core. The Core extraction change is
internal, additive, and applies equally to existing drag, copy, and move
extraction workflows.

## Design

### Plug-in Layout

`src/main/resources/base/Plugins/UnpackArchive/`:

- `unpack_archive/__init__.py` - command, archive recognition, destination
  derivation, and composite extraction task.
- `README.md` - supported behavior, formats, destination rule, and conflict
  handling.

There is no settings or key-bindings file. Packaging needs no dedicated spec
entry because the complete base resources tree is already bundled. Add the
plug-in package to `build.py`'s test `PYTHONPATH`.

### Archive Recognition

A pure helper loads `Core Settings.json`, validates `archive_handlers` as a
mapping of non-empty suffix strings to non-empty scheme strings, and sorts
entries by descending suffix length. The longest case-insensitive suffix match
wins, matching Core's `Pack` and archive-open behavior.

The helper accepts only a `file://` URL and returns:

- the archive root URL formed by replacing `file://` with the configured
  archive scheme while preserving the path; and
- the sibling `file://` destination formed from the filename with the matched
  suffix removed.

Reject a non-local URL, directory, missing file, unsupported suffix, invalid
handler mapping, empty destination name (for example a file named only
`.zip`), or more than one chosen item with a clear alert and no mutation.

This duplicates only the small suffix-selection rule rather than importing
Core's private `_get_handler_for_archive`. The dependency on the
`archive_handlers` settings shape is intentional bundled-plug-in coupling and
is covered by focused tests.

### Destination And Conflicts

The destination must not exist when extraction begins. If it already exists,
show `Destination already exists: <path>` and return. Do not merge, overwrite,
delete, or rename existing content. This matches Core's whole-directory copy
contract and avoids ambiguous partial results.

A race that creates the destination after the preflight check is handled by the
extraction task's `FileExistsError` path and produces the same alert. Core's
archive extraction first writes to a temporary directory beside the destination
and moves it into place only after successful extraction, so failed and canceled
operations do not expose a partially populated destination.

### Command And Task Flow

`UnpackArchive(DirectoryPaneCommand)`:

1. Read `get_chosen_files()` and require exactly one URL.
2. Validate that the URL is local, exists, is not a directory, and has a
   configured archive handler.
3. Derive the archive root and destination URLs.
4. Reject an existing destination.
5. Submit `_UnpackArchiveTask(archive_url, destination_url)`.
6. If the task reports success, place the cursor at the destination (ignore
   `ValueError` when filtered or hidden) and show
   `Unpacked <archive> to <directory>.` for three seconds.

`is_visible()` performs no filesystem I/O. It returns true only when the file
under the cursor is a local URL whose basename has a configured archive suffix.
Invocation still performs authoritative validation because selection and the
filesystem may change after visibility is computed.

`_UnpackArchiveTask(Task)` calls `prepare_copy(archive_root_url,
destination_url)` inside the task, runs each returned subtask with `self.run`,
and sets `succeeded = True` only after all subtasks complete. Expected
`FileExistsError`, `FileNotFoundError`, `OSError`, `NotImplementedError`,
`UnsupportedOperation`, and `subprocess.CalledProcessError` failures are shown
through the task's alert mechanism and leave `succeeded = False`. Unexpected
programming errors continue to propagate to the normal plug-in error handler.

### Core Extraction Cancellation

Core's `core.fs.zip.Extract` currently calls blocking `_run_7zip` and has no
cancellation checkpoints, although archive extraction can be long-running.
Change it to subclass `_7zipTaskWithProgress`, use a task size of 100, and call
`run_7zip_with_progress`. That existing helper parses 7-Zip progress, checks the
progress dialog's cancellation state, kills the child process, and raises
`Task.Canceled`. Keep the current temporary-directory cleanup and final
`fman.fs.move` notification behavior unchanged.

The composite plug-in task delegates its progress dialog to the Core extraction
subtask through `Task.run`. Cancellation prevents the final move, cleans the
temporary directory, and leaves any pre-existing filesystem state untouched.

### Threading And Failure Behavior

The command runs on the normal command worker. Archive inspection and
extraction run in the submitted task; no Qt widget or model is accessed from a
new thread. `show_alert`, `show_status_message`, and `place_cursor_at` use the
existing thread-safe command APIs.

There is no persistent worker, timer, cache, listener, or startup I/O. Expected
bad archives, missing sources, unsupported operations, permission errors,
destination races, and 7-Zip process failures produce concise alerts instead of
plug-in tracebacks.

## Alternatives

- **Copy the reference plug-in's `zipfile.extractall` implementation** -
  rejected because it supports ZIP only, assumes a four-character suffix,
  bypasses Core progress and filesystem notifications, has no cancellation,
  and historically permits unsafe archive paths on older Python versions.
- **Run bundled `7za.exe` directly from the plug-in** - rejected because Core
  already owns binary discovery, archive scheme configuration, temporary
  extraction, notifications, and process error handling.
- **Import Core's private `_get_handler_for_archive` or `Extract` directly** -
  rejected in favor of the public configuration and filesystem/task APIs. The
  only Core code change improves the owning extraction abstraction.
- **Merge into an existing destination like `ZipFile.extractall`** - rejected
  because overwrite semantics and partial failures are unclear. A future task
  can add an explicit conflict policy.
- **Prompt for an arbitrary destination** - rejected for the first version;
  deterministic sibling extraction is the defining behavior of the reference
  plug-in.
- **Add a shortcut matching the reference plug-in's `Shift+U`** - rejected at
  the user's request. The command remains available from the Command Center.

## Runtime Effects

- Startup: registers one directory-pane command. There are no settings reads,
  filesystem probes, workers, timers, or recurring signals at startup.
- Disabled/no-op path: removing the plug-in removes all behavior. Unsupported
  selections return after bounded validation and start no task.
- Invocation: a few filesystem metadata queries, then one existing Core archive
  extraction process. Disk and CPU cost scale with compressed and extracted
  archive size.
- Memory: bounded by Core and 7-Zip streaming behavior; the plug-in does not
  load archive contents into Python memory.
- Process use: one bundled `7za.exe` child during extraction.
- Cancellation: the existing progress dialog cancels and kills 7-Zip through
  the hardened Core extraction task. Temporary output is cleaned and never
  moved to the final destination.
- I/O: source archive reads, temporary writes beside the destination, and one
  final same-filesystem move on success.

## Tests

Focused commands from the repository root with the test environment configured
by `build.py`:

```powershell
python -m unittest fman_unittest.test_unpack_archive
python -m unittest fman_integrationtest.impl.plugins.test_unpack_archive_plugin
python -m unittest core.tests.fs.test_zip
```

Unit tests in `src/unittest/python/fman_unittest/test_unpack_archive.py`:

- Command identifier and aliases; no bundled key-bindings file.
- Longest, case-insensitive configured suffix matching, including `.zipx` and a
  test mapping containing both `.gz` and `.tar.gz`.
- Destination derivation for `Reports.zip`, `archive.tar`, spaces, and uppercase
  suffixes.
- No chosen item, multiple items, non-local URL, directory, missing source,
  unsupported suffix, malformed handler settings, and empty destination name
  each alert and never submit a task.
- Existing destination alerts and neither calls `prepare_copy` nor mutates it.
- Successful extraction submits one task, runs all prepared subtasks, places the
  cursor, and shows the success status.
- Cancellation and expected preparation/extraction errors do not place the
  cursor or show success; a destination race is reported.
- `is_visible` is pure and depends only on the cursor URL and configured suffix.

Core tests in `core.tests.fs.test_zip`:

- Whole-archive extraction still produces the expected tree.
- `Extract` reports increasing progress from representative 7-Zip output.
- Canceling the extraction task kills the process, skips the final move, and
  removes temporary output.
- Successful extraction retains the existing final move and cache notification
  behavior.

Integration test in
`src/integrationtest/python/fman_integrationtest/impl/plugins/test_unpack_archive_plugin.py`:

- The bundled plug-in loads and registers `unpack_archive` with its aliases.
- Loading adds no default key binding.
- A temporary real ZIP is unpacked through the registered Core archive
  filesystem into the suffix-free sibling directory with expected contents.
- Reinvocation with the destination present leaves it unchanged and reports the
  conflict.

Manual checks:

- Unpack one `.zip`, `.7z`, and `.tar`; verify destination naming, contents,
  cursor placement, and status text.
- Cancel a large archive and verify there is no final or temporary extraction
  directory.
- Try a malformed archive and an existing destination; verify concise alerts
  and no traceback or content mutation.
- Confirm no shortcut invokes the command and it remains available in the
  Command Center.

The complete `python build.py test` suite is not run automatically; run it only
when explicitly requested under repository policy.

## Implementation Steps

1. Harden `core.fs.zip.Extract` with existing progress and cancellation support,
   preserving temporary extraction and notification behavior; add focused Core
   tests and run them immediately.
2. Add `Plugins/UnpackArchive/unpack_archive/__init__.py` with pure archive
   recognition/destination helpers, `UnpackArchive`, and the composite task.
3. Add the plug-in README. Do not add key bindings, context menus, or settings.
4. Add the package path to `build.py`'s test `PYTHONPATH` and add focused unit
   tests.
5. Add the plug-in loading and real-archive integration test.
6. Update the main README's concise Features list and `CHANGELOG.md` without
   adding implementation detail to the README.
7. Run the focused test commands, manual checks where available, diagnostics,
   and `git diff --check`; record exact results and any release-only checks.
8. Add implementation provenance, move this document to `Done/UnpackArchive.md`,
   and move its link from Pending to Completed in `Plan.md`.

## Acceptance Criteria

- `Unpack Archive` appears in the Command Center with no default shortcut or
  context-menu entry.
- Exactly one chosen supported local archive extracts into a suffix-free sibling
  directory using Core's configured archive handler and bundled 7-Zip.
- Existing destinations and invalid selections are never modified and produce a
  clear alert.
- Successful extraction leaves a complete destination, places the cursor on it,
  and reports success.
- Cancellation terminates extraction, cleans temporary output, and never
  publishes a partial destination.
- Bad archives and expected filesystem/process failures produce an alert rather
  than a plug-in traceback.
- No background work or startup I/O exists when the command is unused.
- The public `fman` plug-in API remains compatible with fman 1.7.5.

## Reviewers

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
