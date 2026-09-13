# Sync Pane Location

## Task

Add a bundled Core plug-in command named `Sync Pane Location` that navigates
the inactive pane to the active pane's current location. The command must be
available from the Command Center as `sync_pane_location`.

## Scope

Include two-pane location synchronization initiated from the active pane.
Preserve focus on the active pane and preserve the public `fman` plug-in API.
Do not add a keyboard shortcut, persistent setting, file copying, selection
synchronization, or bidirectional ongoing synchronization.

## Design

Implement `SyncPaneLocation` as a `DirectoryPaneCommand` in the bundled Core
plug-in. The command receives the active pane from the existing command dispatch,
uses the existing `_get_opposite_pane` helper to identify its sibling, reads the
active URL through `get_path()`, and navigates the sibling through `set_path()`.

Navigation remains asynchronous under the existing pane API. Existing location
listeners, URL rewriting, error handling, history, and model loading continue to
own their respective behavior. The command is hidden when fewer than two panes
exist, and direct invocation reports that there is no pane to synchronize. A
`null://` active location is not propagated. If both panes already have the same
URL, the command returns without reloading the inactive pane.

## Alternatives

An application command in the private built-in plug-in was rejected because the
Core plug-in already owns pane navigation commands and a directory-pane command
receives the active pane directly. Reusing `open_directory` was rejected because
`set_path()` is the direct public navigation API and avoids cursor-dependent
command behavior. A persistent synchronization mode was rejected because the
requested behavior is a one-shot command.

## Runtime Effects

The command has no startup or steady-state CPU, memory, I/O, timer, thread, or
process cost while idle. When invoked, it reads one pane URL and starts the same
asynchronous navigation used by normal pane location changes. Cancellation and
stale loading behavior remain owned by the existing model. There is no enabled
or disabled state.

## Tests

- Unit test synchronization from the left pane to the right pane.
- Unit test synchronization from the right pane to the left pane.
- Unit test command identifier, alias, and one-pane/two-pane visibility.
- Unit test graceful direct invocation with one pane.
- Unit test rejection of `null://` and no-op behavior for matching locations.
- Assert neither directional synchronization changes focus.
- Run `python -m unittest core.tests.commands.test___init__.SyncPaneLocationTest`
  with the repository test `PYTHONPATH`.

## Implementation Steps

1. Add `SyncPaneLocation` beside the existing pane-navigation commands in Core.
2. Add focused command tests using pane and window doubles.
3. Update user documentation and the changelog.
4. Run the focused Core command test module, record results, and move this task
      to `Done/`.

## Acceptance Criteria

- The Command Center lists `Sync Pane Location`.
- Invoking `sync_pane_location` navigates only the inactive pane to the active
  pane's current URL.
- The active pane retains focus and location.
- Both left-to-right and right-to-left invocation work.
- The command is hidden without an opposite pane; direct invocation is handled
      without an exception.
- `null://` is not synchronized and an already matching pane is not reloaded.
- No shortcut, setting, background work, or public API change is introduced.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: Low
- Context window: Not exposed by host
- Outcome: Approved a one-shot Core pane command using the existing public pane
  navigation API and opposite-pane helper.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: Low
- Context window: Not exposed by host
- Outcome: Added the Core `Sync Pane Location` command, Command Center naming,
  focused regression coverage, and user documentation.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation is functionally correct and minimal. Not approved as
  complete until the follow-up tasks below are done; the validation record
  overstates test coverage and the full suite was not run.

#### Follow Up Tasks

Process And Documentation:

- [x] Reopened the canonical task under `Plan/` while resolving the review;
      completion moves it back to `Done/` and removes the Pending entry.
- [x] Expanded the focused suite to 7 tests, including the identifier and
      exact display alias.
- [x] Full-suite execution is no longer an automatic completion requirement
      under the repository's focused-validation policy. The affected Core
      command test module is run instead.
- [x] README: state that only the location is synchronized; sort order,
      selection, and cursor are not carried over (sort is decided per URL by
      `RememberSortSettings`).

Code (`core/commands/__init__.py`, `SyncPaneLocation`):

- [x] Add `is_visible()` returning `len(self.pane.window.get_panes()) > 1`
      so the command is hidden in the Command Center when no opposite pane
      exists.
- [x] Replace `raise NotImplementedError()` for the single-pane case with a
      silent return or `show_status_message('No other pane to sync.',
      timeout_secs=3)`. Raising surfaces a "Command raised error" dialog with
      a traceback for a normal condition. (`_OpenInPaneCommand` has the same
      inherited rough edge; fixing it there is optional and out of scope.)
- [x] Guard `null://`: if `self.pane.get_path()` is the null location, return
      without navigating so both panes cannot end up empty.
- [x] No-op when the opposite pane is already at the same URL to
      avoid an unnecessary reload.

Tests (`core/tests/commands/test___init__.py`, `SyncPaneLocationTest`):

- [x] Use well-formed URLs (`file:///C:/source`, three slashes) in fixtures;
      the current `file://C:/source` would break if the fixture is reused
      with `splitscheme`/`as_human_readable`.
- [x] Assert focus is untouched: `opposite_pane.focus.assert_not_called()`
      in both direction tests, matching the acceptance criterion.
- [x] Add a test that `is_visible()` is `False` with one pane and `True`
      with two.
- [x] Add a test that the single-pane invocation neither raises nor calls
      `set_path` (after the behaviour change above).
- [x] Add a test that `null://` as the active location does not call
      `set_path`.
- [x] Add a test for the palette identifier/alias because the record keeps
      claiming it (`_get_default_aliases(SyncPaneLocation)` yields
      `Sync pane location`; command name `sync_pane_location`).

## Validation Results

- Focused command suite passed: 7 tests covering the generated
  `sync_pane_location` identifier, display alias, both synchronization
      directions, focus preservation, visibility, graceful single-pane handling,
      `null://` rejection, and same-location no-op behavior.
- Command:
  `python -X faulthandler -u -m unittest core.tests.commands.test___init__.SyncPaneLocationTest`
  with the repository test `PYTHONPATH`.
- Workspace diagnostics reported no errors before task completion.
- The complete `python build.py test` suite was not run because repository
      policy now requires focused task-related validation unless the user
      explicitly requests the full suite.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: Low
- Context window: Not exposed by host
- Outcome: Resolved every implementation-review follow-up with guarded command
      behavior, exact command metadata, expanded focused tests, and clarified user
      documentation.

## Follow-up Validation Results

- `python -X faulthandler -u -m unittest
      core.tests.commands.test___init__.SyncPaneLocationTest` passed all 7 focused
      Sync Pane Location tests.
- `python -X faulthandler -u -m unittest
      core.tests.commands.test___init__` passed all 38 tests in the changed Core
      command test module.
- README, changelog, and task-document diagnostics reported no errors.
- Pylance reports unresolved `fman` imports for the Core resource module and
      test because their import paths are injected by the repository test
      environment; the executable tests resolved those imports and passed.
- The complete build suite was not run under the focused-validation policy.
