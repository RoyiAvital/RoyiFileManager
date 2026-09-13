# Assigned Model Signatures

## Task

Prefer an explicit session-host or official-API model identifier, using the
user-assigned signature when no authoritative identifier is available.

## Scope

Update [AGENTS.md](../AGENTS.md)'s signature policy. Preserve historical records,
agent identity, actual effort, and host-exposed context sizes. No application changes.

## Design

The Model field is a signing identifier: first check the session host and any
available official API that identifies the model running the current session.
Use its explicit identifier; otherwise use the user's explicit assignment,
otherwise `Not exposed by host`. A model catalog, default setting, or another
session's metadata is not an authoritative current-session answer.
An assigned signature is not independent verification of the underlying model.
Do not require a separate label field or suffix on each signature. The rule is
generic and must not hard-code a particular model name.

Threading, persistence, and failure behavior are not applicable to this policy.

## Alternatives

Assignment-first precedence was the initial policy, now superseded by the user's
host-first clarification. Host-only signatures omit the requested fallback.
A separate user-label field was rejected by the user.

## Runtime Effects

Not applicable: documentation only, with no startup, CPU, memory, I/O, or worker changes.

## Tests

Run `git diff --check`. Assert the policy orders official current-session evidence
before the assigned/unavailable fallbacks, retains the verification distinction,
and preserves the Agent rule.
Check completed task links. No runtime tests or README changes are required.

## Implementation Steps

1. Revise the Model rule without changing other metadata requirements.
2. Validate the rule and document the result in the changelog.
3. Record completion and move this task to Done.

## Acceptance Criteria

- An explicit host or official-API identifier for the current session wins.
- Without one, the assigned signature is used directly in Model; absent both,
  use `Not exposed by host`.
- Historical records and unrelated metadata remain unchanged.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Reviewed the requested signing convention, with the verification
  distinction documented once in policy rather than appended to each signature.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Revised precedence to official current-session evidence first and the
  user assignment second. Tool discovery exposed no applicable current-model API;
  no authoritative model identifier was available. Earlier assignment-first
  decisions remain historical and are superseded by this revision.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Updated the generic signature policy and changelog. Assignment,
  fallback, verification-distinction, and unchanged-Agent assertions passed.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Implemented official current-session identity precedence, then assigned
  signature, then unavailable fallback. Ordering and policy assertions passed;
  updated the existing changelog entry without modifying historical signatures.

## Validation Results

- `git diff --check`: passed after the plan and policy edits.
- PowerShell assertions verified explicit assignment precedence, direct use in
  Model, host/unavailable fallbacks, verification distinction, unchanged Agent
  semantics, and absence of a hard-coded model name in the policy.
- Checked completion links and whitespace in all four changed documents.
- Runtime tests: not applicable to documentation-only changes.

### Host-First Revision

- Tool discovery for current-session host model metadata returned unrelated
  capabilities, not an applicable official model-identification API. No explicit
  identifier was supplied by the session host. The assigned-signature fallback
  therefore applies; this does not verify the underlying model.
- PowerShell assertions verified ordered policy clauses: official session identity,
  user assignment, unavailable. Checked rejection of inferred/catalog/default
  identities, unchanged Agent semantics, and no hard-coded model in the policy.
- `git diff --check` passed; completion links and changed-document whitespace
  were checked after moving the canonical task back to Done.