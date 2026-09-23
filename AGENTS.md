# Repository Instructions

These instructions apply to the entire repository.

## Guidelines

 - Do not create new virtual Python environments.
 - Do not install new Python packages. You may ask the user to install.
 - Do not change `.gitattributes` or `.gitignore` without permission or explicitly being asked for.
 - Make the code easy to grasp for human and agents.
 - Be focused and short on documentation and text.
 - Do not apply `git add` or `git commit` unless explicitly asked for.

## Task Documents

Create a dedicated Markdown task document under `Plan/` only when the user
explicitly requests a plan or task document. A plan us mostly needed for new features or change of the code.
Do not create one automatically for documentation, build changes, or repository
maintenance. Do not create or update `Plan.md` entries for tasks without a task
document, or create a document under `Done/` to bypass this rule.

When a task document is explicitly requested:

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

When a task document exists, append a record whenever that task is designed or
reviewed. Do not create a task document solely to record provenance:

```markdown
## Reviewers

### YYYY_MM_DD - <Contributor name>

- Role: Reviewer
- Activity: Design
- Agent: <Acting agent>
- Model: <Model identifier>
- Effort: <Low, Medium, or High>
- Context Window: <Context-window size>
- Outcome: <Review outcome>
```

Rules:

- Dates use `YYYY_MM_DD`.
- The acting contributor supplies its own metadata for every record.
- `Agent` identifies the product or agent performing the work.
- `Model` records the model signature. First check the session host or an
  available official API for an explicit identifier of the model running the
  current session. Use that identifier when available. Do not infer it from a
  model catalog, configured default, agent name, or another session's metadata.
- If no explicit current session identifier is available, use the exact model
  signature assigned by the user. If neither source provides a signature, write
  `Not exposed by host`. Do not add a separate user-supplied label field or a
  qualification suffix to the signature.
- An assigned signature is a user directed attribution convention, not independent
  verification of the underlying model. This policy does not change `Agent`,
  `Effort`, or `Context Window`, and does not rewrite historical records.
- `Effort` reflects the effort used for that activity and is `Low`, `Medium`,
  or `High`.
- `Context Window` records the size exposed to the acting agent; otherwise
  write `Not exposed by host`. Use exactly this field capitalization in new records.
- Only the first planning record for a task uses `Activity: Design`.
- Every later planning pass uses `Activity: Review`, including revisions by the
  original designer.
- `Role` states `Reviewer` in this section.
- If user assigned you a signature, use that for any field not exposed by the agent.
- `Outcome` briefly records the decision, important concerns, or approval state.
- Preserve previous records; reviewer history is append only.
- If any signature info is missing, use what you were assigned to by the user.

## Implementation and Completion

When a task document exists, ensure its design is reviewed and its acceptance
criteria are testable before implementation. Keep that document aligned with
deliberate design changes. Without a task document, proceed with the requested
work and report the changes and validation results in the final response; no
formal plan or provenance document is required.

Once implementation is complete, apply the following steps only when a task
document exists:

1. Add an `Implementer` section using the same metadata fields:

   ```markdown
   ## Implementer

  ### YYYY_MM_DD - <Contributor name>

  - Role: Implementer
  - Activity: Implementation
  - Agent: <Acting agent / As assigned by user>
  - Model: <Model identifier / As assigned by user>
  - Effort: <As assigned by user>
  - Context Window: <As assigned by user>
  - Outcome: <Implementation outcome and decisive checks>
   ```

2. `Role` must explicitly be `Implementer` or `Reviewer`. Use `Reviewer` when
   the contributor only validated an implementation and did not author it.
3. Add a `Validation Results` section containing commands or procedures run,
   outcomes, expected skips, and any checks that could not be run.
4. Move the canonical task file from `Plan/TaskName.md` to
   `Done/TaskName.md`; do not copy it and leave a duplicate behind.
5. Move its link from Pending to Completed in `Plan.md`.

Update `CHANGELOG.md` when a task makes an implemented application change covered
by the Changelog policy below, whether or not a task document exists. Plans,
reviews, and documentation only work do not require a changelog entry.  
Unless a features is in released version, no need to add fixes to it in the 
changelog.

Use the information assigned to you by the user for the signature.

## Runtime and Compatibility Requirements

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
- State the exact focused validation commands in the final report and, when one
  exists, the task document.
- Run the narrowest relevant test immediately after the first substantive edit,
  then run focused tests covering the task and every file changed by it before
  completion.
- Do not run the complete `python build.py test` suite automatically at the end
  of a task. Run it only when the user explicitly requests the full suite.
- No need to run `build.py clean` / `build.py freeze`.  
  Avoid running them unless explicitly asked.
- Do not mark a task complete when required tests fail. Document unrelated or
  environmental failures rather than hiding them.

## Changelog

Record implemented application features, fixes, and code changes only, including
application assets or build/packaging changes that affect the delivered product.
Do not record planned or proposed features, work on task documents, review or
provenance bookkeeping, agent instructions, development-process policies, or
documentation-only and test-only changes. Document an application's actual change,
not the planning or review activity that preceded it. A task with a qualifying
application change is not complete until that change is represented here.

Follow Keep a Changelog structure. Keep `## [Unreleased]` as the first section
and use `## [X.Y.Z]` for each release. A ` - YYYY-MM-DD` date suffix is optional.
Section bodies are free-form and may be empty; no API compatibility statement
is required. Describe compatibility changes and migration guidance when relevant.

## Documentation Quality

- Keep task documents factual and implementation-oriented.
- Link to real repository files with relative paths where useful.
- Record decisions and rejected alternatives, not a transcript of discussion.
- Keep secrets, credentials, private keys, tokens, and machine-specific paths
  out of task documents and changelogs.
- Update README usage instructions whenever a completed task changes commands,
  shortcuts, setup, packaging, configuration, or user-visible workflows.
