# Find Files 001: fzf-Style Query Syntax

Status: Design. This task extends the existing fuzzy search (`Ctrl+F` /
`Ctrl+Shift+F`) with fzf's extended-search operators. The Everything-style
grammar with metadata filters is a separate later iteration,
[Find Files 002](FindFiles002.md); both option tables are kept below for
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
  | `^src` | prefix anchor |
  | `.py$` | suffix anchor |
  | `!tmp` | negation (exact substring must be absent) |
  | `!^src`, `!.py$` | negated anchors |
  | `a \| b` | OR between adjacent terms |
  | `'two\ words` | escaped space inside a term |

- Highlighting for exact and anchored terms (their span) alongside the
  existing fuzzy subsequence highlights.
- A hint row for a term that cannot match anything (`'` alone, `^$`), with
  `value=None` so selecting it does nothing.
- README syntax table naming fzf as the reference; tests.

Excluded:

- Smart-case; matching stays case-insensitive as today (see Design).
- Regular expressions, wildcards, date/size filters and any `xxx:` modifier:
  those are [Find Files 002](FindFiles002.md).
- Changes to `regular` mode, to the JSON `mode` default, to command
  identifiers, aliases or bindings, or to `show_quicksearch`,
  `QuicksearchItem`, the Quicksearch widget, the pane filter bar or other
  pickers (Command Palette, Go To, Favorites, Open With, hash picker).
- Porting fzf's Smith-Waterman scorer; the existing scorer is kept.
- Bundling or depending on fzf, `iterfzf`, `pyfzf`, `pfzy` or any package.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. Every
query without `'`, `^`, `$`, `!`, `|` or `\` ranks exactly as today.

## Current Tools

Two ways exist today to find a file by name from a pane. They overlap in the
current folder but are different mechanisms.

**Start typing (pane filter)** — host code,
[FilterBar](../src/main/python/fman/impl/widgets.py#L236). Any printable key
opens a small box at the bottom-right of the pane; `Escape` closes it,
`Backspace` edits. Rows that do not match are hidden in place; the cursor
jumps to the first row whose name starts with the text. The predicate is a
case-insensitive substring with `*` as a wildcard on the file name
([Filter Bar Improvements 001](FilterBarImprovements001.md) extends it).

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

### Constraints Common to Both Syntaxes

- **Dispatch point.** `get_items(query)` runs synchronously on the Qt thread
  for every keystroke ([quicksearch.py](../src/main/python/fman/impl/quicksearch.py#L107)).
  The index is built once before the dialog opens; a keystroke may only parse
  and scan. Budget: about 30 ms for 50,000 entries. Per-entry casefolded name
  and relative path are already precomputed at index time.
- **No package.** The parser is hand-written and small. Only the standard
  library.
- **Highlights.** Positions index the displayed title (relative path with
  backslashes). Exact and anchored terms give contiguous spans; fuzzy terms
  give subsequence positions, as today.
- **Errors while typing.** A half-typed operator must not raise on the Qt
  thread. Yield one `QuicksearchItem(None, 'Invalid ...', description=...)`;
  selecting it does nothing. Never show a traceback dialog for a query.
- **Ordering.** Ranked results require a full scan; the scorer's existing
  cost (19-103 ms for 75,000 paths, [TODO](../TODO.md)) is the baseline.
  Exact/anchored/negated terms are cheap `in`/`startswith`/`endswith` checks
  and are evaluated *before* fuzzy scoring so they prune the candidate set.

### Options Considered

Two grammars were evaluated. Option A is this task; Option B is
[Find Files 002](FindFiles002.md).

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
  `'`/`^`/`!` and trailing `$` are special; `\` escapes them. Rules are
  documented and tested.
- **Smart-case is implicit.** Users cannot force case-insensitive matching of
  an uppercase term without lowering it. Excluded here; matching stays
  case-insensitive like every other picker in the application.
- **Scoring.** fzf's ranking has no Python package; the existing scorer in
  `matcher.py` is kept, so the result only resembles fzf's order.
- **Audience.** Familiar to terminal users; not a Windows file-manager idiom.
  Mitigated by the README table and by the operators being optional.

#### Option B: Everything Syntax (Subset) — deferred to Find Files 002

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
[Find Files 002](FindFiles002.md). Kept here so the two options can be
compared in one place.

### Decision

Option A on the existing commands. It extends what users already do in
`Ctrl+F` (multi-term fuzzy AND) with four operators and no new command,
binding or mode. Option B needs regex, metadata and a different matching
model, so it gets its own dialog and its own task.

### Parsing

`search_file_fuzzy/query.py`, pure Python:

```
query    := group ('|' group)*        # OR between groups
group    := term (' ' term)*          # AND within a group
term     := ['!'] ( "'" text | '^' text ['$'] | text '$' | text )
text     := chars with '\ ' for a literal space and '\x' for a literal x
```

- Tokenise on unescaped spaces; a term consisting only of `|` separates OR
  groups. `\ ` keeps a space inside a term; `\'`, `\^`, `\$`, `\!`, `\|`,
  `\\` are literals.
- Each term becomes `Term(kind, text, negate)` with `kind` in
  `fuzzy | exact | prefix | suffix | equal` (`^x$`). `'`, `^`, `!` are
  special only in the leading position (after an optional `!`); `$` only in
  the trailing position. A term that is only markers (`'`, `^`, `$`, `!`,
  `^$`) is invalid and produces the hint row.
- Normalisation uses the existing `normalize` (NFKC + casefold) on both term
  text and candidates, so matching is case-insensitive.

### Matching

In `Matcher._fuzzy`:

1. For each candidate `(name, relative_path)`, a group matches if every term
   in it matches. `exact` uses `in`, `prefix` `startswith`, `suffix`
   `endswith`, `equal` `==`, each tested on `relative_path` (and `name` for
   `prefix`/`equal`, so `^rep` finds `docs\report.txt`). `negate` inverts
   the term. `fuzzy` uses the existing `_score` on the term.
2. A candidate passes if any OR group matches.
3. Score: the existing `_score` summed over the fuzzy terms of the matched
   group; exact/anchored terms add fixed bonuses (`exact` 8,000,
   `prefix`/`suffix` 9,000, `equal` 10,000, mirroring `_score`'s tiers) so a
   precise term ranks its matches above loose fuzzy ones. Negated terms add
   nothing. A query with no fuzzy terms falls back to index order among
   passing candidates, bounded by `max_results`, like `regular` mode.
4. Highlights: exact/anchored spans plus fuzzy subsequence positions, mapped
   to the backslash title as today.

`regular` mode is untouched: it keeps its plain substring test and ignores
operators (the README says so).

## Alternatives

- **Everything grammar on the existing commands**: rejected because fuzzy
  ranking cannot be mixed with `regex:`/`dm:` filter terms cleanly, and
  users of `Ctrl+F` expect fuzzy behaviour like every other picker. It gets
  its own dialog in Find Files 002.
- **Controls row inside Quicksearch**: rejected; [UIElements](UIElements.md)
  keeps the modal picker free of controls.
- **Panel + Table** like Search File Content: two surfaces for a
  one-keystroke picker. Rejected.
- **Smart-case**: an invisible mode switch inconsistent with the rest of the
  application. Rejected; RegEx in Find Files 002 covers case-sensitive needs.
- **Porting fzf's scorer**: a few hundred lines of Go to port and test for a
  marginal ranking difference. Rejected; keep `_score`.
- **Packages** (`iterfzf`/`pyfzf` spawn the fzf binary; `pfzy` is a scorer
  without syntax). Rejected: repository policy against new packages.

## Runtime Effects

- Startup: none.
- Per invocation: unchanged index walk.
- Per keystroke on Qt: parse (microseconds) plus one scan. Exact/anchored
  terms are single C-level string operations per candidate and prune before
  fuzzy scoring, so a query with at least one such term is *faster* than the
  same fuzzy query today. A pure fuzzy query costs exactly what it costs
  today. No timers, workers or I/O.
- Cancellation: not applicable; nothing outlives the keystroke.
- No-op path: queries without operators produce identical results and cost.

## Tests

Focused commands:

```powershell
$env:PYTHONPATH="src/main/python;src/unittest/python;src/integrationtest/python;src/main/resources/base/Plugins/Core;src/main/resources/base/Plugins/SearchFileFuzzy"
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest fman_unittest.test_search_file_fuzzy
```

- Parser: one test per operator, escaped space and escaped markers, markers
  in non-special positions (`Don't`, `$RECYCLE.BIN`, `a!b`) as literals,
  partial input at every prefix of representative queries (never raises),
  marker-only terms produce the hint row.
- Matcher: each operator on `name` and `relative_path`; negation; OR groups;
  combined `'exact !neg fuzzy`; fixed bonuses rank exact above fuzzy;
  operator-free queries produce byte-for-byte today's ranking on a fixture.
- Highlights: contiguous spans for exact/anchored terms, subsequence for
  fuzzy, mapped to the backslash title, non-BMP characters.
- `regular` mode ignores operators.
- Performance: synthetic 50,000-entry index; `'report`, `^src`, `.py$` and
  `!tmp` each under 15 ms; `'report fuzzy` not slower than `report fuzzy`.
- Existing `SearchCommandTest` with patched `show_quicksearch` proves the
  index is built once and `get_items` never touches the filesystem.
- Manual: real folder, all README examples, 100 % and 150 % scaling for the
  hint row.

## Implementation Steps

1. Add `search_file_fuzzy/query.py` (tokeniser, `Term`, validation, hint
   reasons); unit tests first.
2. Extend `Matcher._fuzzy` with group/term evaluation, pruning before scoring,
   bonuses and span highlights; keep `_regular` unchanged; tests.
3. Wire the hint row into `get_items`; test the empty-value item.
4. README syntax table; CHANGELOG `Added` entry.
5. Performance test and manual checks.

## Acceptance Criteria

- `Ctrl+F` / `Ctrl+Shift+F`, their palette rows, bindings and `mode` default
  are unchanged; operator-free queries rank exactly as before.
- `'exact`, `^prefix`, `suffix$`, `^equal$`, `!negation` and `a | b` work as
  documented, case-insensitively, with correct highlights.
- Markers in non-special positions and `\`-escaped markers are literal.
- Invalid or partial queries never raise; the hint row explains why.
- No file under `src/main/python/fman` changes; no new command, binding,
  setting or package.
- Focused tests pass; the performance cases meet their bounds on the
  development machine.

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
