# Status Bar Active Background

## Task

Remove the segmented background rectangles behind text in the active Extended
Status Bar pane while retaining a clear, full-width active-pane background.

## Scope

Change only the CSS-to-QSS selector mapping for the active pane footer and add
focused regression coverage. Preserve status content, layout, theme colors,
modes, settings, and the public `fman` plug-in API.

## Design

Keep `.statusbar-pane` mapped to both `PaneStatusWidget` and its labels so font
and text properties continue to inherit as designed. Map
`.statusbar-pane[active="true"]` only to the container widget. Its background
color will then paint one continuous footer instead of separately painting each
label with gaps between them.

## Alternatives

Making every label transparent in the base QSS was rejected because themes can
still emit explicit label backgrounds through the active selector. Removing
the active background entirely was rejected because it would eliminate the
only visual active-pane distinction.

## Runtime Effects

Not applicable: this changes only generated QSS selectors and adds no runtime
work, memory, I/O, timers, threads, or disabled-mode behavior.

## Tests

- Verify the normal status-pane selector includes labels.
- Verify the active status-pane selector excludes labels.
- Run focused theme and status-bar tests.
- Run editor diagnostics and `git diff --check`.
- Manually confirm a packaged Windows build paints one continuous active footer.

## Implementation Steps

1. Narrow the active status-pane selector mapping to the container.
2. Add focused selector regression coverage.
3. Update the changelog and complete the task record.

## Acceptance Criteria

- Active-pane text has no separate background rectangles.
- The active footer retains its configured background color.
- Inactive footer styling and status text are unchanged.
- Public `fman` plug-in API compatibility is preserved.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context window: Not exposed by host
- Outcome: Approved scoping the active background to the pane footer container.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context window: Not exposed by host
- Outcome: Scoped the active background selector to `PaneStatusWidget` and
	added regression coverage for normal and active status-pane mappings.

## Validation Results

- `python -m unittest fman_unittest.impl.test_theme
	fman_unittest.impl.test_status_bar` passed all 12 focused tests with
	`QT_QPA_PLATFORM=offscreen` and the main/unit source roots on `PYTHONPATH`.
- Editor diagnostics and `git diff --check` were run for all changed files.
- Manual confirmation in a newly packaged Windows build remains the final
	visual smoke check.