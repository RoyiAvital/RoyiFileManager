# Find Files 001: fzf-Style Query Syntax

Status: Completed. The user accepted the measured incremental performance
cost on 2026-09-18; no separate fzf mode or window is added.
This task extends the existing fuzzy search (`Ctrl+F` /
`Ctrl+Shift+F`) with fzf's extended-search operators. The Everything-style
grammar with metadata filters is a separate later iteration,
[Find Files 003](../Plan/FindFiles003.md); both option tables are kept below for
reference.

## Task

Let users refine the existing SearchFileFuzzy dialog while typing, using the
fzf extended-search syntax: exact-substring terms, prefix/suffix anchors,
negation and OR, on top of the fuzzy ranking that exists today. Quicksearch
cannot host controls, so the plug-in's `get_items(query)` parses these
operators from the typed text. The host is unchanged.

Motivation: `Ctrl+F` already accepts several space-separated fuzzy terms, but
there is no way to say "must contain exactly this", "must start with", "must
end with" or "must not contain" without switching the JSON `mode` and
reopening the dialog. fzf's operators are the smallest well-known grammar that
adds those four abilities to a fuzzy matcher without changing its feel.

## Scope

Included:

- The fzf operators in the existing `search_files_in_current_folder` (`Ctrl+F`)
  and `search_files_recursively` (`Ctrl+Shift+F`) commands when `mode` is
  `fuzzy`:

  | Term | Meaning |
  | --- | --- |
  | `report pdf` | fuzzy match of each term, AND, ranked (unchanged) |
  | `'report` | exact substring |
  | `'word'`, `!'word'` | exact word boundary, positive or inverse |
  | `^src` | prefix anchor |
  | `.py$` | suffix anchor |
  | `^report.txt$` | entire relative path |
  | `!tmp` | negation (exact substring must be absent) |
  | `!'tmp` | inverse fuzzy subsequence |
  | `!^src`, `!.py$` | negated anchors |
  | `a \| b` | OR between adjacent terms |
  | `'two\ words` | escaped space inside a term |

- New highlights for positive fuzzy, exact and anchored terms.
- Permissive partial queries: stripped-empty terms are ignored, not invalid.
  A lone `$` is literal; `''` matches a quote.
- README syntax table naming fzf as the reference; tests.

Excluded:

- Smart-case; matching stays case-insensitive as today (see Design).
- Regular expressions, wildcards, date/size filters and any `xxx:` modifier:
  those are [Find Files 003](../Plan/FindFiles003.md).
- Changes to `regular` mode, to the JSON `mode` default, to command
  identifiers, aliases or bindings, or to `show_quicksearch`,
  `QuicksearchItem`, the Quicksearch widget, the pane filter bar or other
  pickers (Command Palette, Go To, Favorites, Open With, hash picker).
- Porting fzf's Smith-Waterman scorer; the existing scorer is kept.
- Runtime use or bundling of fzf, `iterfzf`, `pyfzf`, `pfzy` or new packages.
  Opt-in reference tests use installed fzf without pinning its version.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. Every
ordinary query without `'`, `^`, `$`, `!`, `|`, `\` or tabs ranks exactly as
before. Tabs in extended queries follow fzf's embedded-space handling.

## Tools at Initial Design

Two ways exist today to find a file by name from a pane. They overlap in the
current folder but are different mechanisms.

**Start typing (pane filter)** — host code,
[FilterBar](../src/main/python/fman/impl/widgets.py#L236). Any printable key
opens a small box at the bottom-right of the pane; `Escape` closes it,
`Backspace` edits. Rows that do not match are hidden in place; the cursor
jumps to the first row whose name starts with the text. The predicate is a
case-insensitive substring with `*` as a wildcard on the file name
([Filter Files 001](../Done/FilterFiles001.md) extends it).

**`Ctrl+F` / `Ctrl+Shift+F` (SearchFileFuzzy)** — plug-in,
[search_file_fuzzy](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/__init__.py).
Builds an index of the folder (or subtree) once, opens the modal Quicksearch,
and its `get_items` ranks entries with the plug-in's
[Matcher](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/matcher.py).
Fuzzy mode already splits the query on spaces and requires every token as a
subsequence (`_score`); selecting a result places the cursor on the file,
navigating to its folder if needed.

| | Start typing (pane filter) | `Ctrl+F` (current folder) | `Ctrl+Shift+F` (recursive) |
| --- | --- | --- | --- |
| Where it lives | Host `FilterBar` | Plug-in, `show_quicksearch` | Plug-in, `show_quicksearch` |
| Scope | Current folder | Current folder | Whole subtree, up to `max_recursive_entries` (50,000) |
| Targets | Files **and** folders, any scheme | Files only | Files only |
| Matching | Case-insensitive substring, `*` wildcard | Fuzzy (NFKC, casefold, camel-case tokens, ranked) or substring via `mode` | Same |
| Exact / anchors / negation | No | No | No |
| Result | Pane stays filtered; act on rows directly | Cursor jumps to one file; dialog closes | Cursor jumps to one file in its folder |

## Design

### Implementation Clarifications

The user approved complete fzf extended-query syntax coverage, not score or
ranking parity. The implemented design is:

- AND across sets, OR between adjacent terms; only spaces are backslash-
  escaped. Follow permissive fzf parsing, including partial/empty operators.
- Cover inverse fuzzy (`!'text`) and exact word boundaries (`'word'`) too.
- Preserve the existing ordinary-query ranking and case-insensitive search.
  Extended literal operators preserve punctuation and match the whole
  displayed relative path. Highlights are new, not already implemented.
- Installed fzf is an optional, unpinned test reference, never a runtime
  dependency. Tests report its version and compare match sets, not scores.
- Replace speculative timing guarantees with measured query latency.
- On 2026-09-18 the user accepted the measured incremental cost and approved
  keeping syntax in the existing dialog. The 30 ms whole-query target is no
  longer a completion gate: preserve ordinary matching, report highlight and
  initialization overhead, and document the additional cost of extended terms.


### Constraints

- **Dispatch point.** `get_items(query)` runs synchronously on the Qt thread
  for every keystroke ([quicksearch.py](../src/main/python/fman/impl/quicksearch.py#L107)).
  The index is built once before the dialog opens; a keystroke may only parse
  and scan. Per-entry casefolded names and paths are precomputed at index
  time. The original 30 ms total-latency target is superseded by the approved
  measured-cost decision above; broad fuzzy queries already exceeded it.
- **No package.** The parser is hand-written and small. Only the standard
  library.
- **Highlights.** Map normalized text to the displayed title in Qt UTF-16
  units, only for visible results. Cover surrogate pairs, NFKC composition,
  case-fold expansion and inserted camel-case boundaries.
- **Errors while typing.** Follow fzf's permissive parser. Partial operators
  never raise or create an invalid-query hint row.
- **Ordering.** Ranked results require a full scan; the scorer's existing
  cost (19-103 ms for 75,000 paths, [TODO](../TODO.md)) is the baseline.
  Extended predicates run before ranking. Keep OR alternatives in source
  order: the first matching positive alternative supplies its contribution.

### Options Considered

Two grammars were evaluated. Option A is this task; Option B is
[Find Files 003](../Plan/FindFiles003.md).

#### Option A: fzf Extended-Search Syntax

| Term | Meaning |
| --- | --- |
| `report pdf` | fuzzy match of each term, AND, ranked |
| `'report` | exact substring |
| `^src`, `.py$` | prefix / suffix anchors |
| `!tmp` | negation |
| `a \| b` | OR |
| `'two\ words` | escaped space inside a term |
| case | fzf: smart-case (insensitive unless the term contains an uppercase letter) |

Pitfalls:

- **No regular expressions and no metadata filters.** Adding `regex:` or
  `dm:` would be a private extension; the grammar is then no longer fzf.
  This is why Option B exists as a separate dialog.
- **Marker collisions.** `'`, `^`, `$` and `!` are legal in Windows filenames
  (`Don't panic.txt`, `$RECYCLE.BIN`, `!important.txt`). Only the leading
  `'`/`^`/`!` and trailing `$` are special. Like fzf, backslash escapes only
  spaces. A leading quote makes a leading marker literal.
- **Smart-case is implicit.** Users cannot force case-insensitive matching of
  an uppercase term without lowering it. Excluded here; matching stays
  case-insensitive like every other picker in the application.
- **Scoring.** fzf's ranking has no Python package; the existing scorer in
  `matcher.py` is kept, so the result only resembles fzf's order.
- **Audience.** Familiar to terminal users; not a Windows file-manager idiom.
  Mitigated by the README table and by the operators being optional.

#### Option B: Everything Syntax (Subset) — deferred to Find Files 003

| Term | Meaning |
| --- | --- |
| `report pdf` | case-insensitive substring per term, AND, unranked |
| `a \| b`, `!tmp`, `< >` | OR, NOT, grouping |
| `"annual report"` | phrase with spaces |
| `*.py`, `img_??.jpg` | wildcards |
| `case:Report`, `nocase:` | per-term case control |
| `regex:rep.*\.pdf$` | regular expression |
| `ext:pdf;txt` | extension list |
| `path:src\core`, `file:` | scope modifiers |
| `size:>1mb`, `size:1kb..10mb`, `size:empty` | size filters |
| `dm:today`, `dm:lastweek`, `dm:2024-06`, `dm:>=2024-01-01`, `dc:` | modified / created date filters |
| `wholeword:` | whole-word match |

Its pitfalls (grammar size, semantic divergences from Everything, whole-name
wildcards, no fuzzy matching, metadata cost) and its design are recorded in
[Find Files 003](../Plan/FindFiles003.md). Kept here so the two options can be
compared in one place.

### Decision

Option A on the existing commands. It extends what users already do in
`Ctrl+F` (multi-term fuzzy AND) with extended operators and no new command,
binding or mode. Option B needs regex, metadata and a different matching
model, so it gets its own dialog and its own task.

### Parsing

`search_file_fuzzy/query.py`, pure Python:

- AND across sets, OR between adjacent alternatives: `foo bar | baz` means
  `foo AND (bar OR baz)`. Leading, trailing and repeated bars follow fzf.
- Split on ASCII spaces after protecting `\ `; tabs become embedded spaces.
  Other backslashes stay literal. Trim outer unescaped spaces.
- `Term(kind, text, negate)` supports `fuzzy`, `exact`, `boundary`, `prefix`,
  `suffix`, and `equal`. Operator ordering is inverse, trailing dollar,
  boundary quotes / leading quote / leading caret, matching the reference.
- `!'text` switches inverse exact to inverse fuzzy. `'word'` matches word
  boundaries including underscores. Empty stripped terms are ignored.
- Preserve original text during parsing; normalize for matching separately.
  Prepare an extended query once and share it between selection and highlights.

### Matching

1. Ordinary queries retain the existing whole-query `_fuzzy` / `_score`
  path, filename bonuses and stable index ties; they never call the parser.
2. Extended queries match NFKC + casefold paths with punctuation and spaces
  preserved. Every AND set must pass; any alternative can satisfy a set.
  Fuzzy predicates require the entire term as a subsequence, including an
  escaped space. Anchors apply to the whole displayed relative path, not
  independently to the basename. Anchor whitespace and boundary rules follow fzf.
3. Select the first matching positive alternative in each set. Inverse-only
  success adds no score or highlights. Sum the existing `_score` for selected
  fuzzy terms; score text is normalized once per query. Literal terms are
  filters without arbitrary bonuses. Queries with no positive fuzzy term
  retain index order and stop at `max_results`.
4. `Matcher.__call__` still returns entries. `Matcher.matches` adds UTF-16
  highlights for only those bounded results. `get_items` passes them through
  the unchanged `QuicksearchItem` API; no host or public API changes.

Reference comparisons use fzf `--extended --ignore-case --literal --no-sort`.
Scoring and Unicode normalization intentionally differ. Existing ordinary
fuzzy separator/camel-case normalization can also change matched sets; these
matching policies are not omitted syntax operators.

`regular` mode is untouched: it keeps its plain substring test and ignores
operators (the README says so).

## Alternatives

- **Everything grammar on the existing commands**: rejected because fuzzy
  ranking cannot be mixed with `regex:`/`dm:` filter terms cleanly, and
  users of `Ctrl+F` expect fuzzy behaviour like every other picker. It gets
  its own dialog in Find Files 003.
- **Controls row inside Quicksearch**: rejected; [UIElements](../Plan/UIElements.md)
  keeps the modal picker free of controls.
- **Panel + Table** like Search Files: two surfaces for a
  one-keystroke picker. Rejected.
- **Smart-case**: an invisible mode switch inconsistent with the rest of the
  application. Rejected; RegEx in Find Files 003 covers case-sensitive needs.
- **Separate fzf mode/window**: considered during performance review; the
  user accepted the measured costs and retained the existing dialog. Ordinary
  queries already bypass extended evaluation. Another window alone would not
  reduce matching cost or make synchronous work nonblocking.
- **Porting fzf's scorer**: not required for syntax coverage; keep `_score`.
- **Packages** (`iterfzf`/`pyfzf` spawn the fzf binary; `pfzy` is a scorer
  without syntax). Rejected: repository policy against new packages.

## Runtime Effects

- Startup: none.
- Per invocation: unchanged index walk plus a punctuation-preserving path
  cache in fuzzy mode. No persistent state; the cache lasts for the dialog.
- Per keystroke on Qt: ordinary matching is unchanged plus bounded highlight
  work. Extended queries parse once, evaluate predicates per candidate, then
  score surviving fuzzy terms. Some matching work is repeated during scoring;
  selective filters can offset this, but broad operators add per-file cost.
- I/O, threading and processes: no query-time I/O, timers or workers; fzf runs
  only in explicitly requested development tests, never in the application.
- Cancellation: nothing outlives the query; UI input waits for the synchronous
  scan to return. This accepted limitation is visible on large broad searches.
- No-op path: no recurring work while closed. Regular mode skips the new
  literal cache, parser and highlights. Ordinary fuzzy queries skip parsing
  and extended predicates, but retain the one-time cache and result highlights.

### Performance Summary

Measured on Windows/Python 3.14 on 2026-09-18. Synthetic entries use
`src/folderNNN/reportNNNNN.py`; filesystem indexing is excluded. Nine warm
paired samples alternate old/new order and assert identical returned entries
and ordering. New measurements include highlighting at most 100 results.
Old measurements use the unchanged `_fuzzy(normalize(query))` scorer.

Median paired additional query time in milliseconds:

| Files | Ordinary queries | Broad extended queries |
| ---: | ---: | ---: |
| 1,000 | 1.12-1.39 | 1.43-1.66 |
| 10,000 | 1.07-1.36 | 6.30-7.59 |
| 50,000 | 1.20-2.37 | 29.50-37.72 |

Ordinary cases: `report`, `rpt`, `report py`. Extended cases compare `report`
with `report !missing`, and `rpt` with `rpt !missing` / `^src rpt`. The extra
conditions reject no candidates, isolating overhead rather than filtering
benefits. These synthetic figures are not universal performance bounds.

Construction comparison uses otherwise identical normalization with/without
the literal-path cache, ten paired samples after warmup:

| Files | Added construction time | Extra cache memory |
| ---: | ---: | ---: |
| 1,000 | 0.11 ms | 0.07 MiB |
| 10,000 | 1.10 ms | 0.74 MiB |
| 50,000 | 5.89 ms | 3.71 MiB |

Separately, seven warm 50,000-entry samples measured total latency:
`report py` old baseline 162.06 ms versus 164.14 ms including highlights;
broad literal-only queries 0.84-0.97 ms for the first 100 results; literal
no-match/exclude-all scans 5.94-9.43 ms. `^src rpt` took 122.79 ms whereas
`^missing rpt` took 9.36 ms by pruning all candidates before scoring.
Full matcher construction took 134.7 ms with 13.5 MiB traced allocation
(excluding the prebuilt entries). Query parsing/preparation alone was measured
earlier at about 2-7 microseconds, not per file. No end-to-end fzf speed
comparison is claimed; its executable is used as a syntax oracle only.

Decision: preserve ordinary matching, accept the measured incremental cost,
and document it. The old scorer already exceeded 30 ms on broad queries; the
user explicitly accepted proceeding without a universal 30 ms guarantee.

## Tests

Focused commands:

```powershell
$env:PYTHONPATH="src/main/python;src/unittest/python;src/integrationtest/python;src/main/resources/base/Plugins/Core;src/main/resources/base/Plugins/SearchFileFuzzy"
$env:PYTHONUTF8="1"
python -m unittest fman_unittest.test_search_file_fuzzy
$env:FZF_REFERENCE_TESTS="1"
try { python -m unittest fman_unittest.test_search_file_fuzzy }
finally { Remove-Item Env:FZF_REFERENCE_TESTS }
$env:SEARCH_PERFORMANCE_TESTS="1"
try {
  python -m unittest fman_unittest.test_search_file_fuzzy.SearchPerformanceTest.test_incremental_cost
  python -m unittest fman_unittest.test_search_file_fuzzy.SearchPerformanceTest.test_fifty_thousand_entries
}
finally { Remove-Item Env:SEARCH_PERFORMANCE_TESTS }
try {
  foreach ($scale in @('1', '1.5')) {
    $env:QT_SCALE_FACTOR=$scale
    python -m unittest fman_integrationtest.test_qt.SearchFileSyntaxIT
  }
}
finally { Remove-Item Env:QT_SCALE_FACTOR }
```

- Parser: all operators, escaped spaces, literal backslashes, marker/bar
  edge cases and every prefix of representative queries.
- Matcher: whole-path anchors, punctuation, inverse fuzzy, word boundaries,
  adjacent OR precedence and first-positive selection. Ordinary ranking is
  compared with the old whole-query formula. Assert parsing once for extended
  `matches` and never for ordinary/regular queries. Verify all nine README cases.
- Reference: opt-in installed-fzf comparison, with default environment options
  isolated, UTF-8 NUL records, timeouts and explicit failure if requested but
  unavailable. Compare matched sets, not ranking, and print the version.
- Highlights: contiguous spans for exact/anchored terms, subsequence for
  fuzzy, mapped to the backslash title, non-BMP characters.
- `regular` mode ignores operators.
- Performance: opt-in incremental measurements at 1,000/10,000/50,000 entries,
  initialization/cache cost, plus absolute 50,000-entry timings and allocation.
  Report measured costs without hardware-dependent assertions in normal tests.
- Existing `SearchCommandTest` with patched `show_quicksearch` proves the
  index is built once and `get_items` never touches the filesystem.
- Native Qt: real temporary folder, query changes, selection/cancel and UTF-16
  rendering at 100 % and 150 % scaling. Human visual review and a rebuilt
  executable are not required or claimed for this plug-in-only change.

## Implementation Steps

1. Add `search_file_fuzzy/query.py` with focused parser tests.
2. Add extended predicates, ranking and mapped highlights; retain ordinary
  whole-query scoring and `_regular`; tests.
3. Wire highlights into `get_items`; verify index reuse and cancellation.
4. README syntax table; CHANGELOG `Added` entry.
5. Reference comparisons, paired performance checks and native Qt smoke.

## Acceptance Criteria

- `Ctrl+F` / `Ctrl+Shift+F`, their palette rows, bindings and `mode` default
  are unchanged; operator-free queries rank exactly as before.
- `'exact`, `^prefix`, `suffix$`, `^equal$`, `!negation` and `a | b` work as
  documented, case-insensitively, with correct highlights.
- Full extended operators, including inverse fuzzy and boundary quotes, are
  covered by offline and installed-reference tests. Only spaces are escaped.
- Partial queries never raise; empty stripped terms follow fzf without a hint row.
- No file under `src/main/python/fman` changes; no new command, binding,
  setting or package.
- Focused tests pass; ordinary matching/ranking remains unchanged; measured
  initialization, highlight and extended-query costs are disclosed in this
  record and user documentation with tested examples. The accepted performance
  tradeoff replaces the original unachieved 30 ms total-latency gate.

## Reviewers

Records before 2026_09_17 belong to the combined document
`ExtendedQuicksearchUI.md`, from which this task and Find Files 002 were split.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Designed explicit text-query configuration for SearchFileFuzzy with
  two candidate grammars, fzf and Everything, each with its table and pitfalls
  (Qt-thread budget, hand-written parser, filename marker collisions, regex
  safety, metadata cost, semantic divergences). Decision pending; user leans
  toward Everything for `regex:` and date/size filters. Six open items listed.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: User decided: Everything syntax on two new additive commands
  (`..._everything`, `Ctrl+E` / `Ctrl+Shift+E`); fuzzy retained unchanged on
  the existing commands and shortcuts; no `fuzzy:` modifier; no change to the
  pane filter. Recorded the shortcut rationale (`Alt+Shift` layout toggle),
  the palette-row reason for separate commands, and the in-dialog mode hint.
  Four open items remain (wildcards, match target, date/size subset and regex
  cap, ordering).

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Split at the user's request. This document (Find Files 001) now
  designs Option A, the fzf operators on the existing `Ctrl+F` fuzzy commands,
  which extends current behaviour without a new command or mode. Option B,
  the Everything grammar on `Ctrl+E`, moved to Find Files 002 with its
  decision, open items and the natural-language front-end note. Both option
  tables are kept here for comparison. Verified against `matcher.py` that
  fuzzy mode already ANDs space-separated tokens, so the operators are
  additive filters evaluated before the existing scorer.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Difficulty estimate only: medium-high (6/10), roughly 3-5 focused
  developer-days including tests, assuming familiarity with this plug-in.
  Scope is local, but existing normalization removes punctuation and inserts
  camel-case spaces; literal operators need a separate matching representation.
  The plug-in currently supplies no highlight positions, so Unicode-aware
  source-span mapping is new work. Preserve the whole-query scorer for plain
  queries; summing term scores is not equivalent. Clarify OR precedence,
  negation semantics, and scoring when several groups match before coding.
  Per-keystroke timing targets remain unverified and may require additional
  optimization. Checked source and ran read-only normalization/scoring examples;
  no feature implementation or performance benchmark was performed.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: User clarified full syntax coverage, not identical scoring.
  Approved plug-in-local implementation with fzf operator ordering, adjacent
  OR precedence, inverse fuzzy and word-boundary terms, permissive partial
  queries, and explicit literal matching. Retain ordinary-query ranking.
  Use the installed latest fzf as an optional unpinned test oracle; no
  runtime executable or package dependency. Acceptance checks compare match
  sets and separately test existing ranking, highlights and query latency.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: User accepted approximately 1 ms extra for ordinary queries and
  28-37 ms extra for broad extended queries on the measured 50,000-entry
  fixture, plus about 6 ms/3.7 MiB of per-dialog preparation. Approved keeping
  one dialog and completing the task with these costs documented, replacing
  the unachieved 30 ms total-latency gate. Share query preparation between
  matching and highlighting; retain the old scorer and validate usage examples.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Post-implementation review of `query.py`, `matcher.py`,
  `__init__.py`, tests and documentation. Parser follows fzf's operator order
  (inverse, trailing `$`, boundary quotes, quote, caret), bar handling and
  trimming. Extended matching uses a literal NFKC/casefold path cache; ordinary
  and regular queries bypass the parser. Highlights map to UTF-16 units. No
  host file changed; `SearchEntry`/`Matcher.__call__` unchanged. Focused module
  re-run: 51 tests OK, 4 expected skips. Ad-hoc probes of camel-case and
  backslash terms confirmed extended fuzzy scores never fall to `-inf`.
  Notes: `environment.yml` gained `fzf` as a test-only entry while
  `conda-lock.yml` was not regenerated; the working-tree `copy.svg` diff is a
  pre-existing LFS filter artefact unrelated to this task. Approved.

## Implementer

### 2026_09_18 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented all fzf extended-query operators in the existing search
  dialog, retained ordinary fuzzy ranking and regular mode, and added bounded
  Unicode-aware highlights. Extended matching/highlighting share one query
  preparation. Added offline regressions, unpinned installed-fzf comparisons,
  paired performance checks, native Qt coverage and nine tested usage examples.
  Published the accepted performance costs; no runtime executable dependency,
  host/API change, new package or separate search window.

## Validation Results

Validation environment: Windows, Python 3.14, PyQt5 5.15 and installed
`fzf 0.74 (conda-forge)`. Reproduction commands are in Tests above.

- Immediate focused check after the final matcher edit:
  `python -m unittest fman_unittest.test_search_file_fuzzy.ExtendedMatcherTest fman_unittest.test_search_file_fuzzy.MatcherTest`:
  19 passed, including single preparation, parser bypass and README examples.
- Offline search module: 51 tests, OK, four expected skips (one unavailable
  directory-symlink creation check, one opt-in reference check, two opt-in
  performance checks).
- Search module with `FZF_REFERENCE_TESTS=1`: 51 tests, OK, three expected
  skips (symlink and two performance checks). All 162 query comparisons over
  46 candidates agreed with the installed reference's matching sets.
- Both `SearchPerformanceTest` methods passed with
  `SEARCH_PERFORMANCE_TESTS=1`; results are recorded in Performance Summary.
  Incremental comparisons also assert identical result ordering.
- `python -m unittest fman_integrationtest.test_qt.SearchFileSyntaxIT` passed
  on native Windows with `QT_SCALE_FACTOR=1` and `1.5`. Covered real temporary
  files, query changes, Enter selection, Escape cancellation and UTF-16 ranges.
- No editor diagnostics in the changed Python files. Local Markdown link
  targets and `git diff --check` passed.
- No full test suite, build, clean, freeze or package command was run. Human
  visual review and rebuilt-executable verification were not performed.

Completion accepts the measured incremental cost, not a claim that total
latency is always below 30 ms. Broad fuzzy matching remains synchronous.
