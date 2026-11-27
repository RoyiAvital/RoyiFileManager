# Repository Instructions

These instructions apply to the entire repository.

## Guidelines

### Environment & Git

- Develop on Windows, targeting Windows and GitHub Actions Windows runners.
- Use the `python` on `PATH` (from `environment.yml`).
- If needed, `C` and `Rust` environments will be on `PATH`. Use only them.  
  In case of a need, ask for them.
- Do not create virtual environments or install packages.  
  You may ask the operator if a package is needed.
- Do not modify `.gitattributes` or `.gitignore` unless explicitly asked.
- Do not run `git add`, `git pull`, `git push` or `git commit` unless explicitly asked.
- MarkDown: Use "Title Case" for titles, Ensure width normalized tables.
- Never use elevated privileges without the permission of operator.  
- Never delete files belong to operator (Outside the repository). 

### Engineering Principles

- **Readable code**: keep code clear and easy to grasp for humans and agents.
- **Data correctness**: protect user data above all.
- **Performance**: keep the UI reactive and hot paths lean.
- **Simplicity**: prefer simple, robust solutions that avoid unnecessary edge cases.
- **No over protective code**: validate at real boundaries (user input, OS/FS I/O, thread/process handoffs, public APIs), not impossible internal states.
- **Clean deletion**: remove obsolete code, flags, and shims instead of layering workarounds, unless compatibility is explicitly required.
- **Measure before optimizing**: back non-trivial performance complexity with measurements.

## Runtime & Compatibility

- Disabled optional features must not run background jobs, I/O, scans, timers, or recurring signals unless explicitly justified.
- Keep Qt widgets and models on the Qt thread. Pass immutable plain data to workers and deliver results via queued signals or equivalent safe dispatch.
- Long-running work must support cancellation or stale-result rejection.
- Keep Windows portability: store mutable state under `UserSettings`; never intentionally write to the Windows Registry.
- Preserve the documented plug-in API (`PlugIn.md`) unless a task explicitly approves a break and migration note.
- Prefer existing repository abstractions and keep host/plug-in boundaries clean.

## Testing

- Write fast, focused regression tests for changed behavior and real failure modes.
- Match test weight to risk: prefer pure unit tests; use Qt integration or smoke tests only for signals, widgets, thread affinity, persistence, packaging, or external tools.
- Avoid bloated or redundant tests (trivial accessors, constants, framework behavior, or impossible internal states).
- Run focused `unittest` checks with `build._environment()` and `QT_QPA_PLATFORM=offscreen` (see `DEVELOPMENT.md`).
- Run the narrowest relevant test after the first substantive edit, then focused tests covering all changed files before completion.
- Validate `docs/` edits with `python build.py doc`, and screenshot script changes with `python build.py test-docs`.
- Do not run the full `python build.py test` suite, `build.py clean`, or `build.py freeze` unless explicitly requested.
- Never mark a task complete when required tests fail; report unrelated or environmental failures transparently.
- State the exact validation commands run in your final response (and in the task document when one exists).

## Task Documents

Create a task document under `Plan/` **only** when the user explicitly requests a plan or task document (typically for new features or significant code changes).  
Do not create one automatically for documentation, build, or maintenance work, and do not add `Plan.md` or `Done/` entries without a task document.

- One canonical file per task: `Plan/PascalCaseName.md`, linked under **Pending** in `Plan.md` (index only; no duplicate body).
- Keep unrelated work in separate task documents.
- Write `Not applicable` with a brief reason when a subsection genuinely does not apply.

### Provenance Metadata

Every contributor subsection below begins with this block (append-only; never rewrite prior records):

```markdown
- Date: YYYY_MM_DD
- Agent: <Acting product/agent>
- Model: <Exact operator-assigned signature>
- Effort: <Exact operator-assigned level>
- Context Window: <Exact operator-assigned size>
```

Use the exact `Model`, `Effort`, and `Context Window` assigned by the user/operator. If unassigned, use the current host's exposed value, or `Not exposed by host` — never infer.

### Document Structure

```markdown
# <Task Title>

<One-paragraph high-level summary.>

## Task & Guidelines

- **Goal**: user-visible objective and motivation (starting from operator input).
- **Scope**: included behavior, explicit exclusions, and compatibility constraints.
- **Acceptance Criteria**: observable, testable completion conditions.

## Design Review

### Initial Design - <Model Signature>

<Provenance metadata>

- **Architecture & Data Flow**: ownership boundaries, threading, persistence, and failure behavior.
- **Alternatives Considered**: credible options and why they were rejected.
- **Runtime Effects**: startup, steady-state CPU/memory, I/O, cancellation, and disabled/no-op path.
- **Planned Tests**: focused unit, Qt integration, smoke, or manual checks.

### Review - <Model Signature>

<Provenance metadata>

- **Verdict**: Approved / Approved with changes / Changes requested
- **Findings**: correctness, safety, edge cases, performance, or unnecessary complexity.
- **Recommendations**: concrete simplifications or fixes.

### Final Design - <Model Signature>

<Provenance metadata>

- **Consolidated Design**: single coherent specification incorporating accepted feedback.
- **Review Decisions**: brief note of key feedback accepted or rejected.
- **Implementation Steps**: ordered, independently verifiable steps.
- **Validation Plan**: exact focused test/check commands to run.

## Implementation

### Implementer - <Model Signature>

<Provenance metadata>

- **Changes**: files modified/added, key decisions, and edge cases handled.
- **Deviations**: any deliberate changes from Final Design and why.
- **Validation Results**: exact commands run, outcomes, and expected skips.

### Implementation Review - <Model Signature>

<Provenance metadata>

- **Verdict**: Approved / Approved with changes / Changes requested
- **Findings**: bugs, regressions, data safety, readability, over-engineering, or test gaps.
- **Required Changes**: concrete items to fix before finalizing.

## Final Implementation

<Provenance metadata>

- **Final Summary**: review fixes applied and final delivered state.
- **Validation Results**: exact final commands run, outcomes, skips, or checks not run.
```

### Completion (When a Task Document Exists)

1. Complete `## Final Implementation` with provenance and validation results.
2. Move `Plan/TaskName.md` to `Done/TaskName.md` (no duplicate left behind).
3. Move its link from **Pending** to **Completed** in `Plan.md`.
4. Update `CHANGELOG.md` if the change qualifies below.

## Changelog

Record implemented product changes (features, fixes, assets, packaging) under `## [Unreleased]` using Keep a Changelog subsections (`Added`, `Changed`, `Fixed`, `Removed`, `Documentation`).

- Use `### Documentation` for user/API documentation updates shipped with a feature or release, or notable user-guide additions.
- Do **not** record plans, reviews, agent/process docs, test-only changes, trivial doc edits, or fixes to unreleased features.
- For releases, move entries under `## [X.Y.Z]` (optional ` - YYYY-MM-DD` date). Describe breaking changes and migration steps when relevant.

## Documentation

- Be concise: use short sentences and visual or concrete examples.
- Keep documentation factual, use relative links inside Markdown files, and never include secrets or machine-specific paths.
- Update `README.md`, `docs/`, `PlugIn.md`, and `UIElements.md` whenever a task changes user-visible workflows, shortcuts, configuration, packaging, or plug-in APIs.
