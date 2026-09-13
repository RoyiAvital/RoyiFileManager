# Context Window Capitalization

## Task

Standardize the provenance field spelling as `Context Window` at the user's
request.

## Scope

Update both templates and the field rule in [AGENTS.md](../AGENTS.md), normalize
field labels in [ProcessPane.md](../Plan/ProcessPane.md), and close its review
item. Preserve recorded values and unrelated historical documents.

## Design

The repository instruction owns the canonical label. This is a label-only
correction, not a change to model metadata or context-size reporting. Preserve
historical review outcomes and append a note superseding the earlier rejection.
Threading, persistence, and failure handling: not applicable to documentation.

## Alternatives

Retain lowercase spelling: rejected because the user explicitly selected title
case. Rewrite every old task: unnecessary; only the current plan is normalized.

## Runtime Effects

Not applicable: no runtime, I/O, worker, startup, or disabled-feature changes.

## Tests

Run `git diff --check`. Use PowerShell case-sensitive checks to confirm two
`Context Window` template fields, no lowercase field labels in the current plan,
and a checked capitalization item. Verify the completed task/index links resolve.
Application tests and README changes are not applicable to a provenance label.

## Implementation Steps

1. Update the templates and canonical-label rule.
2. Normalize current-plan labels and close the review item with a superseding note.
3. Validate spelling, update the changelog, and move this task to Done.

## Acceptance Criteria

- New signatures are instructed to use exactly `Context Window`.
- Current Process Pane field labels match; values remain unchanged.
- The capitalization review item is closed and earlier reasoning remains visible.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Reviewed a label-only update with case-sensitive documentation checks.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Updated both repository templates, the canonical-label rule, and current
	Process Pane labels; closed the review item and preserved historical values.

## Validation Results

- `git diff --check`: passed after the initial document and substantive edits.
- PowerShell case-sensitive assertions: both instruction templates use
	`Context Window`, no lowercase field labels remain in Process Pane, and its
	capitalization item is checked. Changelog entry verified present.
- Completion checks: task/index links resolve and the canonical file exists only
	under Done; whitespace checks pass for all changed documents.
- No runtime tests: documentation only. No application behavior or API changes.