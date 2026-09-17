# Filter Files 002

## Task

Add **Multiple terms (AND)** to the pane filter: `rep 2024` requires every
space-separated term to match the basename, in any order. This is the optional
feature extracted from [FilterFiles001](../Done/FilterFiles001.md).

Status: deferred. 001 is complete; obtain explicit user confirmation
before implementation. Creating this task is not approval to change Space.

## Scope

- Match all terms against the same basename, case-insensitively, in any order.
- A leading unescaped `!` negates the whole expression; `^` and `$` apply per
  term. Terms retain the glob and escape syntax defined by 001.
- Ignore consecutive and trailing separator spaces.
- Route unmodified Space into the filter while its bar is visible. With the
  bar hidden, retain the existing `toggle_selection` binding. Other shortcuts
  and modifiers are unchanged.
- Reuse 001's status-bar count, input-length bound and filter lifecycle.

Excluded: OR expressions, regular-expression mode, fuzzy matching, metadata
queries, sorting changes, persistence, new settings and public API changes.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5.
This deliberately changes literal-space matching and Space-as-selection while
filtering; these changes require explicit approval. `rep*2024` continues to
require ordered matches and remains available if this task is declined.

## Design

### Ownership And Data Flow

- Extend 001's existing Qt-free `compile_filter`/`FilterMatcher` rather than
  creating a second wildcard engine. Parse the expression once per edit and
  hold one immutable segment tuple per term.
- Scan each term's fixed-length segments left to right. Each term starts its
  own search at position zero; matches in different terms may overlap.
  The result is `all(term_matches) != negate`.
- Add the Space branch beside Backspace in `DirectoryPaneWidget._on_key_pressed`
  in [widgets.py](../src/main/python/fman/impl/widgets.py). Gate it on a visible
  bar and no modifiers before normal command routing, then use the existing
  filter input handler. Closing the bar restores selection routing immediately.
- Keep active-pane ownership, counts, clearing and prefix cursor selection
  as defined by 001. No extra model or status-bar signal is needed.

### Decisions Before Implementation

Define literal-space input, including `rep\ 2024` and `[ ]`, without splitting
inside escapes or character classes. Confirm leading spaces, spaces-only input,
`!` followed only by spaces, and per-term standalone anchors. Quotes are not
part of the extracted design; do not add a quoting language implicitly.
Record these choices with approval before implementation.

### Threading, Persistence And Failure

Compilation and in-memory matching stay on the Qt thread. No I/O, worker,
timer, background scan or persisted state is added. Malformed input follows
001's literal-fallback rules and must never raise from a key handler. Reuse
the existing pane-owned lifetime and signal teardown; no new subscriptions.

## Alternatives

- Keep `rep*2024`: already expresses ordered matching without any Space-key
  change, but cannot express unordered terms. Retain if this task is declined.
- Change the global Space binding: breaks selection outside filtering. Reject;
  intercept only while the filter is visible.
- Build one regex using lookaheads or variable-length wildcards: reintroduces
  backtracking risks and a second matching design. Reject; reuse 001's bounded
  segment matching, with short-circuit evaluation between terms.
- Add quotes or a new mode control: more syntax or UI than the extracted task
  requires. Defer pending a separate user request.

## Runtime Effects

- Startup: no worker, I/O or recurring work; only the existing matcher setup.
- Per keystroke: one bounded tokenization/compilation pass. For N rows, name
  length L and total query length P, matching remains O(N * L * P), summed
  across terms. Several terms add Python dispatch and regex searches per row;
  this is not a promise of identical latency to one substring search.
- Memory: O(P) matcher data plus existing per-pane filter state; no per-file
  cache. Reuse count reads; no extra pass over rows for status reporting.
- Cancellation/processes: not applicable to bounded synchronous matching.
  Measure complete Qt filter updates on large row sets before acceptance.
- Disabled/no-op: hidden-bar Space routing and an empty filter retain their
  normal behavior, with no feature-specific background work.

## Tests

Extend the unit module and `FilterBarIT` implemented by 001; do not create parallel
test helpers. Run these focused commands:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_unittest.impl.test_filter_pattern', '-v'], env=build._environment()))"
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.FilterBarIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- Unit: `rep 2024` in either order; rejection when a term is absent; `!a b`
  negates the whole conjunction; `^a b$` anchors per term; repeated/trailing
  spaces; overlapping hits; single-term equivalence with 001.
- Unit: literal spaces, escapes, brackets and empty/negated-empty expressions
  according to the explicitly approved rules above; every typed prefix compiles.
- Qt: Space edits a visible filter without toggling selection; hidden-bar Space
  toggles selection; modified/custom shortcuts stay unchanged. Escape and
  navigation restore normal routing. Counts and active-pane ownership remain
  correct with multiple terms and after nonmatching source-file changes.
- Performance: adversarial nonmatches and many small terms at the input limit;
  compare single-term 001 and multiple-term matching on 1,000 and 10,000 rows,
  then measure the full Qt key-to-update path. Reuse 001's calibrated gates.
- Manual: type `rep 2024`, verify both orderings match and Space returns to
  selection after closing the filter. Packaging: not applicable; no assets,
  dependencies or delivery changes.

## Implementation Steps

1. Confirm 001 is implemented; record explicit user approval and resolve the
   whitespace/escape questions. Re-review the final semantics and test gates.
2. Extend the existing parser/matcher and focused unit tests; verify bounded
   matching, single-term compatibility and literal-space handling.
3. Add visible-bar Space routing and real Qt regression tests, without changing
   the global binding. Verify counts and cleanup with two panes.
4. Run focused behavior and performance checks; document measured effects.
5. Update usage and changelog only after application behavior is implemented.

## Acceptance Criteria

- User approval and whitespace/escape rules are recorded before implementation.
- Every term must match, in any order; whole-expression negation and per-term
  anchors work as specified, without catastrophic backtracking.
- Literal spaces remain expressible by the approved syntax.
- Space changes only while the filter is visible; closing it restores selection.
- Single-term matching, counts, pane lifecycle and public APIs remain compatible.
- Focused unit/Qt tests and calibrated performance gates pass; no new background
  activity, model scans for counts, I/O or persisted state is introduced.

## Reviewers

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Extracted the optional AND feature from 001 into an independent
  deferred task, retaining its design, tests and explicit approval gate.
  Historical design/review provenance stays in 001. Flagged literal-space and
  whitespace-only semantics for resolution before implementation.