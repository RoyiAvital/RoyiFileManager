# Status Bar Active Indicator

## Task

Show the `Active` marker only in the active pane's Extended Status Bar footer.
The inactive pane currently displays the same marker and is therefore
misleading.

## Scope

Bind the marker's visibility to pane activation in Per pane mode and add
focused regression coverage. Preserve the active background, status details,
Active pane mode, settings, and the public `fman` plug-in API.

## Design

`PaneStatusWidget` will retain whether it was created with an active marker.
`set_active(active)` will show the marker only when both the marker is enabled
for this layout and the pane is active. Active pane mode continues to omit the
marker because its single footer is active by definition.

## Alternatives

Changing the inactive label to `Inactive` was rejected because it adds noise
and width to an already compact footer. Relying only on background color was
rejected because the existing `Active` text should remain an explicit cue.

## Runtime Effects

Not applicable: activation already invokes `set_active`; changing one label's
visibility adds no background work, I/O, timers, or threads. Disabled mode is
unchanged.

## Tests

- Verify a Per pane widget hides the marker initially and when inactive.
- Verify `set_active(True)` shows the marker and switching back hides it.
- Verify Active pane mode never shows the marker.
- Run focused status-bar and theme tests, editor diagnostics, and
  `git diff --check`.
- Manually confirm only the focused pane says `Active` in a packaged build.

## Implementation Steps

1. Store whether the widget layout supports the active marker.
2. Update marker visibility in `set_active`.
3. Add focused visibility regressions.
4. Update the changelog and complete the task record.

## Acceptance Criteria

- Exactly one footer says `Active` in Per pane mode.
- Switching pane focus moves the marker to the new active pane.
- Active pane mode does not show the redundant marker.
- Public `fman` plug-in API compatibility is preserved.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context window: Not exposed by host
- Outcome: Approved binding marker visibility to the existing active-pane state.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context window: Not exposed by host
- Outcome: Bound the marker to actual pane activation and added coverage for
  active, inactive, and single-footer states.

## Validation Results

- `python -m unittest fman_unittest.impl.test_status_bar
  fman_unittest.impl.test_theme` passed all 14 focused tests with
  `QT_QPA_PLATFORM=offscreen` and the main/unit source roots on `PYTHONPATH`.
- The new tests verify marker visibility in both status-bar layouts.
- Editor diagnostics and `git diff --check` were run for all changed files.
- Manual confirmation in a newly packaged Windows build remains the final
  visual smoke check.