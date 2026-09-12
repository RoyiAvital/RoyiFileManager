# Correct Provenance Metadata

## Task

Distinguish the agent identity from the underlying model identity in task
reviewer and implementer records.

## Scope

Update `AGENTS.md`, existing task records, the plan index, and the changelog.
Do not infer or invent an underlying model identifier that the host does not
expose.

## Design

Add a required `Agent` field. Record `GitHub Copilot` as the agent and
`Not exposed by host` as the model until the host supplies an explicit model
identifier.

## Alternatives

Keeping `Model: GitHub Copilot` was rejected because it conflates product/agent
identity with model identity. Guessing a model from behavior was rejected
because provenance must be factual.

## Runtime Effects

Documentation-only change. It has no startup, CPU, memory, I/O, threading,
packaging, or application runtime effect.

## Tests

- Search all task documents for metadata lines matching
	`^- Model: GitHub Copilot$` and require zero matches.
- Confirm every provenance record contains both `Agent` and `Model`.
- Run workspace documentation diagnostics.

Required final command for product regression coverage: not applicable because
no executable source or configuration changes.

## Implementation Steps

1. Update the templates and rules in `AGENTS.md`.
2. Correct all existing reviewer and implementer records.
3. Record completion in the changelog and move this task to `Done/`.

## Acceptance Criteria

- Agent and model are represented by separate fields.
- No record claims that GitHub Copilot is the underlying model.
- Unknown model identifiers are explicitly recorded as not exposed by the host.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context window: Not exposed by host
- Outcome: Defined a factual agent/model provenance split.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context window: Not exposed by host
- Outcome: Added separate Agent and Model fields to the policy and all existing
	provenance records, without guessing the underlying model.

## Validation Results

- No metadata line matches `^- Model: GitHub Copilot$`.
- Every existing provenance record contains adjacent Agent and Model fields.
- Documentation diagnostics report no errors.
- Product regression tests were not run because no executable source or
	configuration changed.
