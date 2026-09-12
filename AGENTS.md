# Repository Instructions

These instructions apply to the entire repository.

## Task Documents

Every task starts with a dedicated Markdown document under `Plan/` before
implementation begins, including features, refactors, bug fixes, documentation,
build changes, and repository-maintenance work.

- Use one canonical file per task: `Plan/TaskName.md`.
- Use descriptive PascalCase filenames without spaces, for example
  `Plan/ExtendedQuicksearchUI.md`.
- Add the task to the Pending section of `Plan.md`.
- Do not keep a second copy of the task body in `Plan.md`; it is an index only.
- Keep unrelated work in separate task documents so each task can be planned,
  reviewed, implemented, tested, and completed independently.

Each task document must contain these sections:

1. `Task`: user-visible goal and motivation.
2. `Scope`: included behavior, explicit exclusions, and compatibility constraints.
3. `Design`: ownership boundaries, data flow, threading, persistence, and failure behavior.
4. `Alternatives`: credible alternatives considered and why the selected design won.
5. `Runtime Effects`: startup cost, steady-state CPU and memory cost, I/O, threading or process use, cancellation, and the disabled/no-op path.
6. `Tests`: exact unit, integration, regression, performance, and manual checks required.
7. `Implementation Steps`: ordered, independently verifiable changes.
8. `Acceptance Criteria`: observable completion conditions.
9. `Reviewers`: planning and review provenance using the format below.

Use `Not applicable` with a short reason when a required section genuinely does
not apply. Do not silently omit it.

## Reviewer Records

Append a record whenever a task is designed or reviewed:

```markdown
## Reviewers

### YYYY_MM_DD - <Contributor name>

- Role: Reviewer
- Activity: Design
- Agent: <Acting agent>
- Model: <Model identifier or Not exposed by host>
- Effort: <Low, Medium, or High>
- Context window: <Context-window size or Not exposed by host>
- Outcome: <Review outcome>
```

Rules:

- Dates use `YYYY_MM_DD`.
- The acting contributor supplies its own metadata for every record.
- `Agent` identifies the product or agent performing the work.
- `Model` identifies the underlying model when exposed by the host; otherwise
  write `Not exposed by host`. Do not infer a model or copy the agent name.
- `Effort` reflects the effort used for that activity and is `Low`, `Medium`,
  or `High`.
- `Context window` records the size exposed to the acting agent; otherwise
  write `Not exposed by host`.
- Only the first planning record for a task uses `Activity: Design`.
- Every later planning pass uses `Activity: Review`, including revisions by the
  original designer.
- `Role` states `Reviewer` in this section.
- `Outcome` briefly records the decision, important concerns, or approval state.
- Preserve previous records; reviewer history is append-only.

## Implementation And Completion

Before implementation, ensure the task design is reviewed and its acceptance
criteria are testable. During implementation, keep the task document aligned
with deliberate design changes.

Once implementation is complete:

1. Add an `Implementer` section using the same metadata fields:

   ```markdown
   ## Implementer

  ### YYYY_MM_DD - <Contributor name>

   - Role: Implementer
   - Activity: Implementation
  - Agent: <Acting agent>
  - Model: <Model identifier or Not exposed by host>
  - Effort: <Low, Medium, or High>
  - Context window: <Context-window size or Not exposed by host>
  - Outcome: <Implementation outcome and decisive checks>
   ```

2. `Role` must explicitly be `Implementer` or `Reviewer`. Use `Reviewer` when
   the contributor only validated an implementation and did not author it.
3. Add a `Validation Results` section containing commands or procedures run,
   outcomes, expected skips, and any checks that could not be run.
4. Move the canonical task file from `Plan/TaskName.md` to
   `Done/TaskName.md`; do not copy it and leave a duplicate behind.
5. Move its link from Pending to Completed in `Plan.md`.
6. Update `CHANGELOG.md` in the same change. A task is not complete until its
   user-visible result is represented there.

## Runtime And Compatibility Requirements

- Disabled optional features must avoid feature-specific background jobs, I/O,
  model scans, timers, and recurring signal work unless the task explicitly
  documents and justifies otherwise.
- Qt widgets and models stay on the Qt thread. Workers receive immutable plain
  data and return results through queued signals or equivalent safe dispatch.
- Long-running work must support cancellation or stale-result rejection.
- Preserve the public `fman` plug-in API unless a task explicitly approves a
  compatibility break and migration path.
- Keep Windows portability: mutable state belongs under `UserSettings`, and
  changes must not intentionally write to the Windows Registry.
- Prefer existing repository abstractions and keep upstream mergeability in
  mind; document unavoidable fork-specific coupling.

## Test Requirements

- Add focused regression tests for behavior changed by the task.
- Match test breadth to risk: unit tests for pure logic, Qt integration tests
  for signals/widgets/thread affinity, and end-to-end smoke tests for startup,
  persistence, packaging, or external tools.
- State the exact validation command in the task document and final report.
- Run the narrowest relevant test immediately after the first substantive edit,
  then run `python build.py test` before completion when the environment allows.
- Do not mark a task complete when required tests fail. Document unrelated or
  environmental failures rather than hiding them.

## Changelog

Follow Keep a Changelog structure. Every release section, including
`Unreleased`, must contain an explicit API compatibility statement, for example:

```markdown
API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.
```

If compatibility changes, state the affected API, migration path, and rationale
instead. Do not rely on a feature bullet to imply compatibility.

## Documentation Quality

- Keep task documents factual and implementation-oriented.
- Link to real repository files with relative paths where useful.
- Record decisions and rejected alternatives, not a transcript of discussion.
- Keep secrets, credentials, private keys, tokens, and machine-specific paths
  out of task documents and changelogs.
- Update README usage instructions whenever a completed task changes commands,
  shortcuts, setup, packaging, configuration, or user-visible workflows.
