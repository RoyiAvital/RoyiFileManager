# Focused Validation Policy

## Task

Reserve `Ctrl+B` for Favorites by removing it from the Flat View plan, and make
focused task-related tests the repository's default completion requirement
instead of the complete build test suite.

## Scope

Update `AGENTS.md` and `Plan/FlatView.md`. Preserve existing implementation and
historical validation records. Do not change runtime code or key bindings.

## Design

Flat View remains available through the Command Center as `toggle_flat_view`
and receives no default shortcut in its first version. Repository policy will
require the narrowest tests covering changed behavior and other files affected
by a task. Full `python build.py test` runs are optional and reserved for an
explicit request or when broad impact makes them necessary.

## Alternatives

Reassigning Favorites was rejected because `Ctrl+B` is already implemented and
documented for it. Continuing to require the complete suite was rejected because
focused validation provides faster feedback and matches the requested workflow.

## Runtime Effects

Documentation-only change with no startup, CPU, memory, I/O, threading,
process, cancellation, or disabled-path effects.

## Tests

- Verify Flat View explicitly has no default shortcut and does not claim
  `Ctrl+B`.
- Verify `AGENTS.md` requires focused tests and does not mandate
  `python build.py test` for every implementation.
- Run documentation diagnostics for changed files.

## Implementation Steps

1. Update Flat View shortcut decisions and acceptance criteria.
2. Replace the repository-wide full-suite requirement with focused validation.
3. Record validation and archive this task.

## Acceptance Criteria

- `Ctrl+B` is unambiguously reserved for Favorites.
- Flat View remains bindable but has no default shortcut.
- New implementations run tests focused on changed behavior and affected files.
- Full-suite testing is optional unless explicitly requested or justified by
  broad impact.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: Low
- Context window: Not exposed by host
- Outcome: Approved explicit shortcut ownership and focused-only default
  validation.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: Low
- Context window: Not exposed by host
- Outcome: Updated repository test policy and resolved the Favorites/Flat View
  shortcut ownership conflict.

## Validation Results

- `AGENTS.md` requires focused tests for the task and every changed file and
  prohibits automatic end-of-task `python build.py test` runs.
- Flat View explicitly has no default shortcut and reserves `Ctrl+B` for
  Favorites in its task, alternatives, and acceptance criteria.
- Documentation diagnostics reported no errors.
- Runtime tests were not run because no executable source or configuration
  changed.
