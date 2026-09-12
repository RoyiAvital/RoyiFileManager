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
own their respective behavior. With fewer than two panes, the command raises
`NotImplementedError` because no inactive sibling exists.

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
- Unit test the existing failure contract when no opposite pane exists.
- Run `python -m unittest core.tests.commands.test___init__.SyncPaneLocationTest`
  with the repository test `PYTHONPATH`.
- Run `python build.py test` before completion.

## Implementation Steps

1. Add `SyncPaneLocation` beside the existing pane-navigation commands in Core.
2. Add focused command tests using pane and window doubles.
3. Update user documentation and the changelog.
4. Run focused and full test suites, record results, and move this task to
   `Done/`.

## Acceptance Criteria

- The Command Center lists `Sync Pane Location`.
- Invoking `sync_pane_location` navigates only the inactive pane to the active
  pane's current URL.
- The active pane retains focus and location.
- Both left-to-right and right-to-left invocation work.
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

## Validation Results

- Focused command suite passed: 4 tests covering the generated
  `sync_pane_location` identifier, display alias, both synchronization
  directions, focus preservation, and the no-opposite-pane failure contract.
- Command:
  `python -X faulthandler -u -m unittest core.tests.commands.test___init__.SyncPaneLocationTest`
  with the repository test `PYTHONPATH`.
- Workspace diagnostics reported no errors before task completion.
- `python build.py test` was offered but skipped by the user, so the full unit,
  integration, and Core suites were not rerun for this task.
