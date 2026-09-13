# New File

## Task

Add a built-in Core command, `New Empty File`, that uses fman's existing file
creation flow without opening an editor. Bind it to `Ctrl+N`. If the requested
path already exists, the command does nothing.

Motivation: Core's `CreateAndEditFile` (`Shift+F4`) already prompts for a name
and creates a missing file, but always opens the resulting path in the
configured editor. Users need the same lightweight creation flow without the
editor round trip.

The task was initially designed as a separate bundled plug-in. At the user's
request, the accepted design was simplified to a built-in Core command sharing
the existing `CreateAndEditFile` flow.

## Scope

Included:

- Add `NewEmptyFile` to the bundled Core commands with aliases `New empty file`,
  `Create empty file`, and `Touch`.
- Reuse private Core helpers for the filename suggestion, prompt, `exists`,
  `touch`, error handling, and cursor placement shared with
  `CreateAndEditFile`.
- Bind `Ctrl+N` to `new_empty_file` in Core's default key bindings.
- Preserve `Shift+F4`: it creates missing files and opens both new and existing
  files in the configured editor.
- Make an existing destination a no-op for `NewEmptyFile`: no `touch`, cursor
  movement, alert, or editor launch.
- Hide `NewEmptyFile` when the active filesystem does not implement `touch`.
- Report other `OSError` creation failures as alerts instead of plug-in-error
  tracebacks.

Excluded:

- A separate plug-in, settings, templates, non-empty content, multiple files,
  automatic parent-directory creation, and additional filename validation.
- Atomic local creation or stronger race guarantees than existing
  `CreateAndEditFile` behavior.
- Changes to the public `fman` plug-in API.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5 and the
existing `create_and_edit_file` command identifier, aliases, prompt, errors,
cursor placement, and `Shift+F4` behavior.

## Design

Refactor `core.commands.CreateAndEditFile` around private module helpers:

1. A prompt helper derives the current filename suggestion, keeps the existing
   extension selection behavior, and returns the joined destination URL or
   `None` when cancelled or empty.
2. A creation helper uses the existing `exists` and `touch` operations. It
   reports the existing permission and unsupported-filesystem alerts and
  reports other `OSError` reasons without a traceback. Its documented
  tri-state result distinguishes created, already existed, and failed after an
  alert. It does not call `touch` when the path is already known to exist.
3. A cursor helper preserves the existing hidden-file `ValueError` handling.

`CreateAndEditFile` uses the helpers, places the cursor for both newly created
and existing paths, and invokes `OpenWithEditor` exactly as before.

`NewEmptyFile(DirectoryPaneCommand)` uses the same prompt and creation helpers.
If the destination exists or creation fails, it returns. After successful
creation it places the cursor and returns without opening an editor.
Its visibility mirrors `CreateDirectory` through `_fs_implements`, checking
for `touch` support on the active pane's scheme.

Both commands continue to run in the command worker. Existing fman filesystem
operations retain their current model-notification and backend behavior.

## Alternatives

- **Separate bundled plug-in with stricter validation and atomic local
  creation** - rejected because the requested behavior is a small variation of
  an existing Core command and does not require distinct filesystem semantics.
- **An `edit=False` command argument** - rejected because a dedicated command
  gives the Command Center an unambiguous name and permits a direct `Ctrl+N`
  binding without exposing an implementation flag.
- **Duplicate `CreateAndEditFile.__call__`** - rejected because shared private
  helpers keep prompt and creation behavior aligned.

## Runtime Effects

- Startup registers one additional Core command and key binding; there are no
  settings reads, filesystem operations, timers, or background jobs.
- Invocation performs the same prompt and at most one `exists` and `touch` as
  the existing command. An existing path returns after `exists`.
- Cancellation and empty input are no-op paths.

## Tests

Run the focused Core command module from the repository root using the test
environment configured by `build.py`:

```powershell
python -m unittest core.tests.commands.test___init__.NewEmptyFileTest
python -m unittest core.tests.commands.test___init__.CreateAndEditFileTest
python -m unittest core.tests.commands.test___init__
```

Tests cover command identifiers and aliases, filename suggestion and extension
selection (including a directory under the cursor), cancellation, successful
creation, existing-path no-op behavior, permission, unsupported-filesystem and
generic `OSError` handling, visibility, cursor-placement failure, no editor
launch from `NewEmptyFile`, preserved editor launch from `CreateAndEditFile`,
and the bundled `Ctrl+N` binding.

Manual check: invoke `Ctrl+N`, create a new file, verify the cursor moves to it
without opening an editor, then enter the same name and verify nothing changes.
Confirm `Shift+F4` still opens the configured editor.

## Implementation Steps

1. Extract private prompt, creation, and cursor helpers in Core commands.
2. Refactor `CreateAndEditFile` to use the helpers without behavioral changes.
3. Add `NewEmptyFile` and bind `Ctrl+N`.
4. Add focused Core command and key-binding regression tests.
5. Update the README and changelog.
6. Record validation, add implementation provenance, move this task to `Done/`,
   and move its index entry from Pending to Completed.

## Acceptance Criteria

- `Ctrl+N` and the Command Center invoke `New Empty File`.
- A missing path is created with existing fman `touch` behavior, selected in
  the pane, and not opened in an editor.
- An existing path causes no mutation, cursor movement, alert, or editor launch.
- Cancellation, empty input, permission failure, and unsupported filesystems
  retain the documented Core behavior without an editor launch.
- Other filesystem creation errors produce an alert rather than a traceback.
- The command is hidden when the active filesystem does not implement `touch`.
- `Shift+F4` retains its current create-or-open-and-edit behavior.
- No background work or settings are added, and the public `fman` API remains
  compatible with fman 1.7.5.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Initial design created as a separate plug-in reusing Core prompt
  and validation helpers; distinguished from Core's `CreateAndEditFile`
  (`Shift+F4`), which always opens the editor.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context window: Not exposed by host
- Outcome: Revised the plug-in plan for traversal-safe component validation,
  atomic local creation, explicit non-local race semantics, parent-creation
  failures, focused tests, and accurate resource packaging.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Approved the user-selected built-in Core design using shared private
  helpers and existing filesystem semantics; acceptance criteria preserve
  `Shift+F4` and define existing paths as a no-op for `Ctrl+N`.

## Validation Results

- Focused `NewEmptyFileTest` and `CreateAndEditFileTest` suites passed: 12
  tests covering command metadata, prompt behavior, creation, existing-path
  no-op behavior, errors, cursor handling, editor behavior, and `Ctrl+N`.
- The complete affected Core command module passed: 50 tests.
- Commands used `QT_QPA_PLATFORM=offscreen` and repository `PYTHONPATH`:
  `python -m unittest -v core.tests.commands.test___init__.NewEmptyFileTest
  core.tests.commands.test___init__.CreateAndEditFileTest` and
  `python -m unittest core.tests.commands.test___init__`.
- Markdown and key-binding JSON reported no editor diagnostics. The Core
  command and test modules retain known environment-path diagnostics for
  unresolved `fman` imports; executable tests imported and exercised them
  successfully with the repository `PYTHONPATH`.
- Manual UI checks were not run. The focused tests directly verified creation,
  no editor invocation, existing-path behavior, and the key binding.
- The complete `python build.py test` suite was not run, per repository policy.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Added the built-in `NewEmptyFile` command and `Ctrl+N`, refactored
  shared creation behavior without changing `Shift+F4`, and passed all 50
  affected Core command tests.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved. Implementation matches the approved built-in design; the
  helper refactor preserves `CreateAndEditFile` behavior; the 50 Core command
  tests were re-run and pass. Minor follow-ups below; none blocks completion.

#### Follow Up Tasks

Code (`core/commands/__init__.py`):

- [x] `_touch_file_if_missing` returns a tri-state (`True`/`False`/`None`).
      `NewEmptyFile` treats `False` and `None` alike, `CreateAndEditFile`
      distinguishes them. Add a one-line docstring naming the three outcomes
      (created / already existed / failed with alert) so the contract is
      explicit for the next caller.
- [x] `_touch_file_if_missing` catches `PermissionError` and
      `NotImplementedError` only. Other `OSError`s from `touch` (e.g.
      `FileNotFoundError` when the pane's directory vanished, invalid name
      `OSError: [WinError 123]` for `a?b`) propagate as a plugin-error
      traceback. This is pre-existing `CreateAndEditFile` behavior, but
      `Ctrl+N` makes it easier to hit; consider catching `OSError` and
      showing `e.strerror` in the alert.
- [x] Optional: `NewEmptyFile.is_visible()` could mirror `CreateDirectory`
      (`_fs_implements(scheme, 'touch')`) so the command is hidden on
      `drives://`/`network://`/`null://` instead of showing the unsupported
      alert. Not required; the alert path is tested.

Tests (`core/tests/commands/test___init__.py`):

- [x] `test_ctrl_n_binding` reads `Core/Key Bindings.json` by relative path.
      It passes, but a test that loads the merged bindings through
      `Config`/`KeyBindings` would also catch a user-override conflict. Low
  priority. The direct default-binding test is retained: user overrides
  intentionally take precedence, while merge and sanitization behavior is
  covered by the existing plug-in configuration tests.
- [x] Add a case where the file under the cursor is a directory
      (`is_dir` → `True`) asserting the prompt default is `''`; the helper
      branch exists but is untested.

Documentation:

- [x] `Design` still says "Both commands continue to run in the command
      worker" — accurate. `Tests` lists the manual `Ctrl+N` check; the
      Validation Results state it was not run. Either run it once before the
      release or mark it as pending in the record. It remains pending release
      validation and is recorded below.
- [x] The first Reviewer record's Outcome describes the *original* plug-in
      design ("Initial design created as a separate plug-in"), which was
      superseded. Leave it (history is append-only) but the Task section
      could add one sentence noting the design changed to a Core command on
      user request, so the record is readable on its own.

## Follow-up Validation Results

- Focused `NewEmptyFileTest` and `CreateAndEditFileTest` suites passed: 16
  tests, including generic `OSError`, visibility, and directory-under-cursor
  coverage requested by the reviewer.
- The complete affected Core command module passed: 54 tests.
- Commands used `QT_QPA_PLATFORM=offscreen` and repository `PYTHONPATH`:
  `python -m unittest -v core.tests.commands.test___init__.NewEmptyFileTest
  core.tests.commands.test___init__.CreateAndEditFileTest` and
  `python -m unittest core.tests.commands.test___init__`.
- The manual `Ctrl+N` and `Shift+F4` UI check remains pending release
  validation. Equivalent command behavior and the bundled binding are covered
  by focused automated tests.
- The complete `python build.py test` suite was not run, per repository policy.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Completed the reviewer follow-ups with an explicit helper contract,
  generic filesystem-error alerts, capability-based visibility, and expanded
  regression coverage; all 54 affected Core command tests pass.
