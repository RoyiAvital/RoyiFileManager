# Dynamic Provenance Metadata

## Task

Make repository provenance templates require each acting agent to output its own
metadata instead of forcing GitHub Copilot-specific values.

## Scope

Update `AGENTS.md` templates and rules. Preserve all existing reviewer and
implementer records as historical facts. Do not prescribe any specific agent,
model, effort, or context-window value.

## Design

Use descriptive placeholders for contributor, agent, model, effort, context
window, and outcome. Require the acting agent to populate each field from its
own current metadata. Unknown model or context-window values must be recorded as
`Not exposed by host`; effort must reflect the actual task effort.

## Alternatives

Hard-coded defaults were rejected because they can misidentify later agents and
models. Omitting metadata was rejected because provenance remains useful when
reported by the actor performing the work.

## Runtime Effects

Documentation-only change with no runtime, startup, CPU, memory, I/O, threading,
process, cancellation, or disabled-path effects.

## Tests

- Verify `AGENTS.md` templates contain no fixed agent, model, effort, or context
  metadata.
- Verify the policy explicitly requires the acting agent to provide its own
  metadata and defines unknown-value handling.
- Run workspace documentation diagnostics.

## Implementation Steps

1. Replace hard-coded provenance values with semantic placeholders.
2. Rewrite metadata rules around actor-supplied values.
3. Record validation and archive this task.

## Acceptance Criteria

- `AGENTS.md` does not force any specific agent, model, effort, or context
  window.
- Every provenance record still requires Agent, Model, Effort, and Context
  window fields.
- Existing historical records remain unchanged.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: Low
- Context window: Not exposed by host
- Outcome: Approved actor-supplied provenance metadata with explicit unknown
  handling.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: Low
- Context window: Not exposed by host
- Outcome: Replaced fixed provenance values with actor-supplied placeholders
  and explicit rules for unavailable metadata.

## Validation Results

- `AGENTS.md` contains no hard-coded GitHub Copilot, GPT-5.6 Sol, Low effort,
  or unavailable-context signature values in its templates.
- Both templates require Agent, Model, Effort, and Context window fields.
- Policy text requires each acting contributor to provide its own metadata.
- Documentation diagnostics reported no errors.
- Product tests were not run because no executable source or configuration
  changed.
