# Concise README Features

## Task

Make the main README's Features section a concise overview of significant
user-facing additions compared with upstream fman.

## Scope

Include Search File Fuzzy, Extended Status Bar, Sync Pane Location, Favorites,
and New Empty File as one-line entries. Exclude implementation details, failure
behavior, persistence internals, and minor maintenance changes. Do not change
feature behavior or public APIs.

Compatibility: documentation-only; preserves the public `fman` plug-in API from
fman 1.7.5.

## Design

Use a flat Markdown bullet list under `## Features`. Each bullet names one
significant feature in bold and gives a short user-oriented description,
including its primary shortcut where applicable. Detailed behavior remains in
task documents, plug-in READMEs, and the changelog.

## Alternatives

- Separate subsections were rejected because they encourage multi-paragraph
  implementation detail for what should be a scannable overview.
- Listing every repository change was rejected because Features is for notable
  user capabilities, not release history.

## Runtime Effects

Not applicable: documentation-only change with no startup, CPU, memory, I/O,
threading, process, cancellation, or disabled-path effects.

## Tests

- Run Markdown diagnostics on `README.md`, this task document, and `Plan.md`.
- Check that the Features section contains the five intended one-line entries
  and no nested feature headings.
- Run `git diff --check`.

## Implementation Steps

1. Add this task to the Pending index.
2. Replace the README feature prose with concise one-line bullets.
3. Validate Markdown and the diff.
4. Record implementation and validation, move the task to `Done/`, and update
   the Completed index.

## Acceptance Criteria

- The Features section contains only significant new user-facing features.
- Every feature has a single short line describing its purpose.
- The section contains no implementation details.
- Search File Fuzzy is represented.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context window: Not exposed by host
- Outcome: Approved a flat five-item user-facing feature summary; detailed
  behavior remains in task and release documentation.

## Validation Results

- README, task-document, task-index, and changelog diagnostics reported no
  errors.
- The Features section contains five one-line entries and no feature
  subsections; Search File Fuzzy is included.
- `git diff --check` passed. Line-ending warnings apply to unrelated existing
  Core working-tree changes.
- No runtime tests were required for this documentation-only task.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context window: Not exposed by host
- Outcome: Replaced detailed feature subsections with five concise one-line
  summaries of significant user-facing additions.
