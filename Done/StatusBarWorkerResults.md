# Status Bar Worker Results

## Task

Restore directory, size, and selected-item details in both Extended Status Bar
display modes. Calculations currently finish, but the result owner identifier is
truncated by the Qt signal and the pane widget rejects the summary as stale.

## Scope

Preserve full Python widget identifiers while delivering completed status
summaries, and add focused regression coverage. Preserve the three modes,
debounce, cancellation, generation checks, settings, layout, and public `fman`
plug-in API. Changes to status text or recursive directory sizing are excluded.

## Design

`StatusCalculationService` remains the owner of its single-worker executor.
Its completion signal will carry the owner identifier as a Python object rather
than a Qt `int`. On 64-bit Python, `id(widget)` exceeds the 32-bit Qt integer
range; converting it to `int` truncates the value and makes the widget reject
every valid result. Widgets continue to reject genuinely stale owner and
generation identifiers, and Qt continues to queue the cross-thread signal.

## Alternatives

Adding a second main-thread forwarding signal was rejected after tracing showed
that delivery already occurred and the owner comparison was failing. Replacing
the owner with an allocated integer sequence was rejected because preserving
the existing identity scheme only requires a correct signal type. Broadening
filesystem exception handling was rejected because an end-to-end probe
reproduced the failure with a successful size query.

## Runtime Effects

Worker count, signal count, memory use, filesystem I/O, cancellation, and
debounce behavior are unchanged. Disabled mode still creates no service,
worker, timers, or status widgets.

## Tests

- Run the focused status-bar unit module and verify a worker completion retains
  a real 64-bit widget ID and renders selected details.
- Retain calculation, selection, settings, formatting, and cancellation tests.
- Run editor diagnostics and `git diff --check` for all changed files.
- Manually verify selected-file details in Active pane and Per pane modes in a
  packaged Windows build; this visual packaged-build check cannot be automated
  locally by the unit test.

## Implementation Steps

1. Change the completion signal's owner field from Qt `int` to Python object.
2. Declare the widget callback's matching slot signature.
3. Add focused worker-to-widget rendering regression coverage.
4. Update the changelog and record validation results.

## Acceptance Criteria

- Active pane mode displays counts, total size, and selected-item details.
- Per pane mode displays those details independently for both panes.
- Result rendering occurs on the Qt thread.
- Stale and post-shutdown results remain suppressed.
- Public `fman` plug-in API compatibility is preserved.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Approved preserving Python widget identity across the Qt signal
  after tracing proved 64-bit `id(widget)` truncation caused valid summaries to
  fail the owner guard.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Changed the result signal to preserve 64-bit widget identifiers,
  declared the matching Qt slot, and added worker-to-widget rendering coverage.

## Validation Results

- `python -m unittest fman_unittest.impl.test_status_bar` passed all 10 focused
  tests with `QT_QPA_PLATFORM=offscreen` and the main/unit source roots on
  `PYTHONPATH`.
- The regression verified that a selected file renders as
  `Selected: 0 dirs, 1 files, 42 B` after asynchronous calculation.
- Editor diagnostics and `git diff --check` were run for the changed files.
- Manual visual verification in a newly packaged Windows build was not run;
  it remains the release smoke check for both Active pane and Per pane modes.