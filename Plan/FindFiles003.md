# Find Files 003: `Everything` Style Query Syntax

Status: Design; grammar decided (Everything syntax on new `Ctrl+E` commands,
fuzzy retained on `Ctrl+F`). Open items 1-4 under Decision remain. Split from
`ExtendedQuicksearchUI.md`; the fzf operators for the existing fuzzy dialog are
[Find Files 001](../Done/FindFiles001.md). Metadata-view integration builds on the
implemented [Find Files 002](../Done/FindFiles002.md), not a new results widget.

## Task

Add a second file-search mode to SearchFileFuzzy whose behaviour is configured
explicitly in the query text: substring, case sensitivity, wildcards, regular
expressions and metadata filters (modification/creation date, size), following
the Everything search syntax. Quicksearch cannot host controls, so the plug-in's
`get_items(query)` parses the grammar from the typed text and dispatches to the
matching matcher. The host is unchanged.

The existing fuzzy search stays as it is, on its existing commands and
shortcuts, because most search surfaces in the application (Command Palette,
Go To, Favorites) are fuzzy and users expect `Ctrl+F` to behave that way. The
Everything-style search is an addition with its own commands and shortcuts, so
each dialog has exactly one matching model and neither grammar leaks into the
other. Both dialogs support the existing optional two-line metadata view: the
same toggle and per-command override show modified date and size beneath paths.
Filtering by metadata is independent of whether that second line is visible.

Motivation: there is no case-sensitive, wildcard, regex or date/size filename
search in the application, and no way to express one while a dialog is open.

## Scope

Included:

- Two new SearchFileFuzzy commands sharing the existing index walk:

  | Command id | Alias | Windows binding |
  | --- | --- | --- |
  | `search_files_in_current_folder_everything` | Search files in current folder (Everything syntax) | `Ctrl+E` |
  | `search_files_recursively_everything` | Search files recursively (Everything syntax) | `Ctrl+Shift+E` |

  `search_files_in_current_folder` (`Ctrl+F`) and `search_files_recursively`
  (`Ctrl+Shift+F`) keep their identifiers, aliases, bindings and fuzzy
  behaviour. Separate commands, not `args`, so the Command Palette shows four
  rows with the correct title and shortcut for each.
- The Everything grammar subset, parsed and matched in plug-in code with the
  standard library only; highlighting; a hint row for invalid or incomplete
  queries; a visible mode indicator in the dialog.
- Reuse indexed size/modification values from Find Files 002 and add local
  creation time for the Everything grammar; collect once before opening the
  dialog, not when typing a filter.
- Reuse `show_metadata`, `Toggle search result metadata`, the `metadata`
  per-command override and the existing date/size formatter in both dialogs.
  Preserve two-line reservation, zero-byte display and partial metadata handling.
- README syntax table naming Everything as the reference; tests.

Excluded:

- Any change to `show_quicksearch`, `QuicksearchItem`, the Quicksearch widget,
  the pane filter bar or other pickers (Command Palette, Go To, Favorites,
  Open With, hash picker).
- fzf syntax, a `fuzzy:` modifier inside the Everything grammar, or any other
  mixing of the two models; bundling or depending on fzf, Everything, `pfzy`,
  `luqum`, `everything-sdk` or any other package.
- Content search (Search File Content keeps its Panel controls). No separate
  Extended toggle, Table columns or additional metadata-view setting here.
- Creation time in the displayed second line: `dc:` is a filter only; the line
  stays modified date plus size, as in Find Files 002.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
existing command identifiers, aliases, bindings and the `mode`/`query`/`metadata`
arguments are unchanged; `mode` gains the value `everything`, and the two new
commands are additive. Existing fuzzy/regular metadata behavior and persisted
preferences remain valid without migration. The extra record-slot cost is
documented under Runtime Effects; disabled metadata is not claimed to be free
of allocation changes.

## Design

### Constraints

- **Dispatch point.** `get_items(query)` runs synchronously on the Qt thread
  for every keystroke ([quicksearch.py](../src/main/python/fman/impl/quicksearch.py#L107)).
  The index is built once before the dialog opens; a keystroke may only parse
  and scan. Budget: about 30 ms for 50,000 entries. Precompute per-entry
  casefolded name and relative path at index time; matchers are single loops
  over tuples; unranked modes stop at `max_results`.
- **No package.** The parser is hand-written (expected 100-250 lines plus
  tests). Only `re`, `fnmatch.translate`, `datetime` and `shlex`-style
  tokenizing from the standard library. Every grammar element needs its own
  unit tests; there is no upstream implementation to lean on.
- **Highlights.** Positions index the displayed title (relative path with
  backslashes). Substring and regex give exact spans; wildcards give spans via
  a translated regex with groups.
- **Errors while typing.** A half-typed `regex:[a` or `dm:2024-` must not
  raise on the Qt thread. Yield one hint item with value `None`; selecting it
  does nothing. Use the display policy below for its title/description so it
  cannot introduce mixed row heights. Never show a traceback dialog for a query.
- **Regex safety.** Python `re` cannot be interrupted; a pathological pattern
  over 50,000 paths of up to 260 characters can freeze the UI for seconds.
  Mitigations: cap pattern length (256), compile once per keystroke, match
  the relative path only, and document the residual risk. No timeout exists
  without a third-party engine.
- **Metadata.** Reuse the collection and file-link semantics of Find Files 002,
  with independent decisions for filter data and display data, detailed below.
  Metadata filters remain local-only: `size:`/`dm:`/`dc:` on other schemes
  produce a hint, even when their provider supplies metadata for display.
- **Ordering.** Unranked results return the first `max_results` in index
  order (breadth-first), as today's `regular` mode does, unless open item 4
  adds a sort.

### Metadata Collection And Lifecycle

Reuse [build_index](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/indexer.py)
and the existing immutable
[SearchEntry](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/matcher.py).
It already holds `url`, `name`, `relative_path`, `size_bytes` and `modified_ns`.
Append only `created_ns=None`, retaining both three- and five-argument
construction and existing field meanings. Do not add a second metadata cache or
recollect values for presentation.

Resolve display from the existing strict-boolean `show_metadata` setting and
optional `metadata=True|False` override at invocation. The two new commands
accept `query=''` and `metadata=None`, delegating with `mode='everything'`;
the override does not persist. The existing toggle remains shared by all four
commands, defaults off, and affects the next invocation.

| Search mode/root | Metadata view | Collect before opening |
| --- | --- | --- |
| Fuzzy/regular, any scheme | Off | No metadata collection; existing path unchanged |
| Fuzzy/regular, any scheme | On | Existing size/modified collection only |
| Everything, `file://` | Off or on | Size, modified and created, needed for later query edits |
| Everything, other schemes | Off | No metadata collection; metadata clauses yield a hint |
| Everything, other schemes | On | Existing best-effort size/modified display; metadata clauses still yield a hint |

Keep `collect_metadata=False` for size/modified and add an optional
`collect_created=False` to the plug-in indexer. Set `collect_metadata` when the
view is enabled OR the mode is Everything on a local root; set `collect_created`
only for Everything on a local root. These are internal plug-in options, not
changes to the public `fman` API. An initial empty/text-only Everything query
still collects local filter data because a later edit may add metadata clauses.
Turning display off suppresses formatting, not data needed by the selected
Everything mode; document this cost explicitly.

- Extend the existing local metadata helper, reusing its selected stat result
  for all requested fields and the hidden-filter stat when suitable. File links
  follow their targets; retain the existing missing-target fallback to link
  metadata. Directory links remain excluded. Do not add an extra stat for `dc:`.
  Use `st_birthtime_ns` for creation when available, with a Windows-only
  `st_ctime_ns` compatibility fallback; never use Unix change time as creation.
  Missing creation time does not discard valid size/modified values.
- Preserve provider size/modified queries independently when display is on;
  caching is provider-specific. Do not add provider creation queries or broaden
  the local-only filtering contract. Unavailable values remain `None`; zero
  size/timestamps are valid. Evaluate metadata predicates on raw values, never
  the formatted/minute-rounded description. A missing property does not satisfy
  its positive predicate; other available properties and text remain usable.
- Generalize the existing `_IndexFiles` task to receive the collection flags
  rather than hard-code `collect_metadata=True`. Use the existing `Task`,
  progress dialog and scoped pane subscriptions whenever metadata is collected,
  including Everything with the view off. Check cancellation between entries
  and provider calls; publish only a complete index. Navigation, pane closure
  and same-root load completion invalidate results; unsubscribe on every exit.
- Preserve `File search canceled.` after indexing-status cleanup for non-stale
  cancellation; stale results remain silent. A blocked filesystem call can delay
  cancellation until it returns. Data is a per-dialog snapshot: no live refresh,
  reindex, filesystem I/O or provider queries during typing. Metadata-off
  fuzzy/regular searches gain no task, lifecycle subscription or polling.

### Metadata View And Hint Rows

Reuse [describe_metadata](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/__init__.py)
for files in either dialog. Titles stay relative paths with backslashes; existing
UTF-16 title highlights and navigation values are unchanged. The second line
remains local `YYYY-MM-DD HH:MM` plus the pane's configured size units, joined
by `, `. Zero size is `0 B`; omit unavailable parts, and use
`description=describe_metadata(entry) or ' '` when display is on. Creation time
is not added to this line. Format only returned file rows, bounded by
`max_results`, and never format when display is off.

[Quicksearch](../src/main/python/fman/impl/quicksearch.py) uses uniform item sizes
and derives dialog height from the first row. Every emitted row must therefore
follow the same line-count policy, including mode/error hints:

- **View on:** file rows always reserve two lines, including all-missing values.
  Hint rows keep their own concise explanation in `description`, or `' '` if
  empty; never apply the file metadata formatter to a hint.
- **View off:** all file and hint descriptions are `''`. Put a concise hint or
  error reason in the hint's title so an empty-query mode hint can coexist with
  single-line files without clipping or adding a hidden second line.
- Hints have value `None`, do not consume the file-result limit and never open a
  path. Invalid queries yield only the error hint; clearing/fixing the query
  restores the normal mode/file rows. The empty-query mode hint is Everything
  only; no new hints appear in fuzzy/regular searches.

Keep this policy in the plug-in; no Quicksearch renderer or public API changes.
Test transitions between mode hints, valid results, no matches and errors, not
just the initial list. Metadata-only conditions add no title highlight spans.

### Grammar (Subset)

| Term | Meaning |
| --- | --- |
| `report pdf` | case-insensitive substring per term, AND, unranked |
| `a \| b`, `!tmp`, `< >` | OR, NOT, grouping |
| `"annual report"` | phrase with spaces |
| `*.py`, `img_??.jpg` | wildcards; whole-name match when a term contains one |
| `case:Report`, `nocase:` | per-term case control |
| `regex:rep.*\.pdf$` | regular expression (Python `re` flavour) |
| `ext:pdf;txt` | extension list |
| `path:src\core`, `file:` | scope modifiers (`folder:` moot: files only) |
| `size:>1mb`, `size:1kb..10mb`, `size:empty` | size filters |
| `dm:today`, `dm:lastweek`, `dm:2024-06`, `dm:>=2024-01-01`, `dm:a..b`, `dc:` | modified / created date filters |
| `wholeword:` | whole-word match |

Pitfalls:

- **Grammar size.** Dates (`today`, `yesterday`, `thisweek`, `lastmonth`,
  `last3days`, `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, comparisons, ranges) and sizes
  (units, `empty`, ranges) are most of the parser and the test matrix. The
  supported subset must be enumerated; unknown Everything functions
  (`dupe:`, `attrib:`, `content:`, `parent:`) must be rejected with the hint
  row rather than silently matching nothing.
- **Semantic divergences to document.** Everything matches the *filename*
  unless a term contains `\`; our index displays the relative path and
  today's substring mode matches the path. Everything's regex flavour is
  PCRE-like; ours is Python `re`. Everything sorts results by name/path with
  its own index; we return the first `max_results` in walk order unless a
  sort rule is added.
- **Wildcard whole-name default.** `rep*` does not match `Annual Report.pdf`
  in Everything, but `rep*` in the pane filter does. Either follow Everything
  (consistent with the reference) or the pane filter (consistent with the
  app); document the choice.
- **No fuzzy matching.** Camel-case and subsequence matching (`pow sh` ->
  `PowerShell`) disappear unless kept as a non-standard `fuzzy:` modifier,
  which breaks the single-syntax rule. Fuzzy users keep `Ctrl+F`.
- **Marker collisions are minimal.** `:`, `"`, `|`, `<`, `>` cannot appear in
  Windows filenames; only `!` can, and only its leading position matters.
- **Metadata cost.** Size/modified storage and collection already exist in Find
  Files 002. Creation adds a record slot and, when collected, another retained
  value. Ordinary Windows stat often uses listing data, but Python work, links,
  network paths and provider queries are not free. Measure the increment over
  the current implementation, separating collection from description formatting.

### Decision

**Everything syntax**, on dedicated commands. Reasons: `regex:` subsumes every
other matching mode, `dm:`/`dc:`/`size:` add filters fzf cannot express, and
its markers (`:`, `"`, `|`, `<`, `>`) cannot collide with Windows filenames.

Fuzzy matching is neither dropped nor folded into the grammar as a `fuzzy:`
modifier: without ranking a fuzzy term is just a permissive filter, and with
ranking it cannot be mixed cleanly with AND/OR/NOT terms. It stays a separate
mode on the existing commands, extended by [Find Files 001](../Done/FindFiles001.md).
`Ctrl+E` was chosen over `Alt+F` because `Alt+Shift` is Windows' input-language
toggle and `Ctrl+E` is the search shortcut in Everything and Explorer;
`Ctrl+E` / `Ctrl+Shift+E` are unbound in every bundled `Key Bindings*.json`.

Because the two dialogs look identical, the Everything dialog shows its mode:
an empty query yields one leading hint row identifying `Everything syntax` and
its markers (`"phrase"  *.ext  !not  case:  regex:  ext:  size: dm:`). Use the
title for a compact single-line hint when metadata is off, or the description
when it is on, following Metadata View And Hint Rows. Its value is `None` so
selecting it does nothing. The fuzzy dialog is unchanged.

Open items still to settle, each to be recorded here:

1. Wildcard semantics: whole-name (Everything) or substring (pane filter).
2. Default match target: filename (Everything) or relative path (today).
3. The exact date and size subset, and the `regex:` length cap.
4. Result ordering: walk order with `max_results` cut, or a sort by path.

Settled: `mode` keeps `fuzzy` and `regular` and gains `everything`; the JSON
default stays `fuzzy` so the unchanged commands behave as today.

Settled for metadata-view integration: share Find Files 002's toggle and override;
do not force the view on for metadata filters. Collect all local Everything
filter fields before opening, reuse the same snapshot for display, and keep
provider display support separate from local-only metadata filtering.

### Long-Term Path: Natural-Language Front End (Royi)

Royi's long-term direction: a small local language model with structured
output, wrapped so the user describes what they are looking for in free
language and the model emits an Everything-syntax query that this search then
runs. Example request: *"a file edited last week in Word and was pretty heavy
with 20 images"*.

Analysis:

- The formal grammar decided above is what makes this feasible: it is a small,
  enumerated, documented target for the model, and the parser validates every
  generated query (unknown modifier -> hint row, never a crash).
- The wrapper is a thin command: free-text prompt -> model -> Everything string
  -> `_search(pane, recursive, mode='everything', query=<string>)`. The `query`
  argument already seeds the dialog, so the user sees the generated string, can
  edit it and gets live results. No host change.
- The model should emit a **structured filter object** (JSON: name terms,
  extensions, modified/created, size, negations), and plug-in code renders it to
  the grammar. Schema validation removes hallucinated modifiers; the same
  renderer can produce a human-readable explanation. Emit relative dates
  (`dm:lastweek`) so the grammar resolves "now" and the model never needs the
  current date.
- The example splits into two kinds of constraints:

  | Constraint | Expressible by this task | Grammar |
  | --- | --- | --- |
  | edited last week | yes | `dm:lastweek` |
  | Word document | yes | `ext:docx;doc;docm` |
  | pretty heavy | yes, with a threshold | `size:>5mb` |
  | about 20 images inside | **no**; needs content inspection | future `meta:` hook |

  Counting images means opening each `.docx` (a ZIP) and counting
  `word/media/*`. That is a **content/metadata provider**, not a grammar
  feature: it runs off-thread over candidates already narrowed by the cheap
  filters, with per-format inspectors, caching, cancellation and scope limits.
  It is a separate future task; the grammar may later gain a generic
  `meta:<provider>:<expr>` term for it.
- Constraints: a local model means a runtime (llama.cpp/ONNX bindings) and
  weights of hundreds of MB to GBs, a packaging and licensing decision against
  the portable-ZIP, no-new-packages posture; an opt-in user-run local server
  over HTTP avoids bundling but is a service dependency. Either way it must be
  optional and off by default with no background work when disabled
  ([AGENTS.md](../AGENTS.md)). Inference takes seconds on CPU and runs as bounded
  background work with cancellation, never on the Qt thread. The generated
  query is always shown and editable, for trust and to teach the grammar.

Constraints on this task so the path stays open: keep the grammar subset
formal and enumerated (already true), and have the parser expose its AST so a
renderer can produce grammar text from a structured object. The model, the
content providers and any online service are excluded from this task.

## Alternatives

- **Separate metadata-view toggle or mandatory second line for Everything.**
  Rejected: the existing preference/override works for both dialogs; selecting a
  matching grammar should not change the user's presentation preference.
- **Collect only when the view is on or the initial query uses metadata.**
  Rejected: later `size:`/`dm:`/`dc:` edits would require I/O on Qt or rebuilding
  the index. Everything opts into upfront local collection independently of view.
- **Keep two-line hints beside single-line results.** Rejected: uniform row
  sizing can clip content. Match hint line count to the selected metadata view.
- **Controls row inside Quicksearch** (checkbox/choice descriptors passed to
  a `show_quicksearch_extended` host API). Rejected: [UIElements](UIElements.md)
  keeps the modal picker free of controls, and the goal is reachable without
  host changes.
- **Panel + Table** like Search File Content. Rejected: two surfaces for a
  one-keystroke picker; slower interaction than the modal Quicksearch.
- **fzf syntax for this dialog** (see the comparison in
  [Find Files 001](../Done/FindFiles001.md)): no regex or metadata, and its markers
  (`'`, `^`, `$`, `!`) are legal filename characters. Rejected here; adopted
  for the fuzzy dialog in 001.
- **Mixing fzf and Everything**, or a `fuzzy:` modifier inside the Everything
  grammar. Rejected by the user: one syntax per dialog, one reference to
  point at; fuzzy without ranking adds little and with ranking mixes badly
  with filter terms.
- **Fuzzy in the pane filter bar instead of a command.** Rejected: the inline
  filter cannot rank, so subsequence matching only makes it less selective;
  it is also host code shared by every scheme.
- **`Alt+F` / `Alt+Shift+F` for the second mode.** Rejected: `Alt+Shift` is
  the Windows input-language toggle.
- **Four bindings with `args` on the two existing commands.** Rejected: the
  Command Palette lists commands, so both modes would collapse into one row
  per scope with an ambiguous shortcut hint and no way to pick the mode.
- **Packages** (`iterfzf`/`pyfzf` spawn the fzf binary; `pfzy` is a scorer
  without syntax; `luqum` parses Lucene, not either grammar;
  `everything-sdk` requires a running Everything). Rejected: repository
  policy against new packages, and none implements the needed grammar.

## Runtime Effects

- Startup: registers two commands; no metadata I/O, scans, timers or workers.
- Per invocation: reuse the bounded index walk. Local Everything collects three
  fields even with the view off; fuzzy/regular collect only the existing two when
  the view is on. Other providers are queried for display only. Reuse stat data
  and the existing worker, but allow I/O costs for links/network paths/providers.
- Memory: adding one trailing `created_ns` slot costs 8 bytes per record on the
  current 64-bit Python, about 0.38 MiB at 50,000 entries even when uncollected;
  verify this during implementation. Collected values add further memory. Measure
  against Find Files 002 rather than counting its two fields as new work.
- Per keystroke on Qt: parse and scan, then format only returned descriptions
  when enabled. No metadata I/O, timers, new processes or workers. Existing
  30-50 ms matching budgets are targets, not measured guarantees; benchmark
  matching and formatting separately at 50,000 entries. Regex retains the
  synchronous-execution risk described above.
- Cancellation: metadata collection uses the existing progress task and scoped
  stale-result guards, including view-off local Everything. Blocked calls must
  return before cancellation finishes. No index is published on cancellation;
  subscriptions are removed on success, errors and abandonment.
- No-op path: unused Everything adds no recurring work. Metadata-off fuzzy/regular
  gains no collection, formatting, task or subscription; metadata-on behavior is
  preserved. Plain Everything text is substring matching, but its index includes
  filter metadata, so total invocation cost is not claimed equal to regular mode.
- Persistence: the existing shared toggle writes the existing setting; queries,
  metadata snapshots and per-command overrides are not persisted.

## Tests

Focused commands:

```powershell
$env:PYTHONPATH="src/main/python;src/unittest/python;src/integrationtest/python;src/main/resources/base/Plugins/Core;src/main/resources/base/Plugins/SearchFileFuzzy"
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest fman_unittest.test_search_file_fuzzy
python -m unittest fman_integrationtest.test_qt.SearchFileMetadataIT fman_integrationtest.test_qt.SearchFileSyntaxIT
```

Extend these existing test modules/classes; repeat the Qt command with
`QT_QPA_PLATFORM=windows`, `QT_AUTO_SCREEN_SCALE_FACTOR=0`,
`QT_ENABLE_HIGHDPI_SCALING=1` and `QT_SCALE_FACTOR=1` / `1.5`.

- Parser: one test per grammar element, escaping, phrases, precedence,
  unknown modifiers, partial input at every prefix of representative queries
  (never raises).
- Matcher: each mode with highlight positions mapped to the backslash title;
  case handling; wildcard whole-name vs substring per decision.
- Metadata: size and date parsing edge cases (`today` across midnight, month
  ends, ranges, comparisons), `file://` only, hint row on other schemes even if
  metadata can be displayed. Raw size/modified values shared by filters and view;
  missing properties, zero bytes, zero timestamps and minute-rounded display.
- Collection matrix: both Everything commands with shared setting on/off and
  `metadata=True|False` overrides. Start with an empty/text query, then add all
  metadata filters with no new stat/provider call. Fuzzy/regular off remains free
  of metadata tasks/subscriptions/I/O; on retains existing size/modified behavior.
- Record/local walk: preserve three- and five-argument `SearchEntry` construction;
  collect creation from the same selected stat with Windows-only fallback and
  missing-value handling. Reuse hidden-filter stats; retain file-link target,
  missing/denied target and directory-link behavior. No provider creation query.
- Cancellation/staleness: reuse the blocked-provider and pane-lifecycle tests;
  cover local Everything with the view off, cancellation before publication,
  navigation away/back, same-root load completion and pane disposal. Confirm
  cleanup and cancellation feedback, with no picker/navigation from partial data.
- Presentation: reuse the formatter/divisor tests, including `0 B`, partial and
  all-missing metadata. In real Qt, verify equal row heights for both mixed-value
  orders, all-missing rows, hints mixed with files and hint-only errors. Exercise
  empty/valid/metadata-only/invalid/no-match/cleared queries, title highlights,
  Return and Escape with the view on and off at 100%/150% scaling. Hints neither
  consume the file limit nor trigger navigation or file metadata formatting.
- Settings: one existing persisted preference across all four commands; explicit
  false overrides true, invalid values use false, overrides do not persist and
  no new toggle/configuration key is introduced. Keep save-error tests green.
- Regex: invalid pattern -> hint row; pattern over the cap -> hint row.
- Performance: synthetic 50,000-entry index; substring, wildcard and simple
  regex each under 50 ms on the development machine. Extend the opt-in
  `SearchMetadataPerformanceTest` with `SEARCH_METADATA_PERFORMANCE_TESTS=1`;
  measure incremental indexing, retained/peak memory, disabled-slot overhead and
  returned-description formatting separately for the collection matrix.
- Existing `SearchCommandTest` with patched `show_quicksearch` proves the
  index is built once and `get_items` never touches the filesystem; the
  fuzzy commands' results are byte-for-byte unchanged.
- Commands: the two new identifiers register, carry the stated aliases and
  `Ctrl+E`/`Ctrl+Shift+E` bindings, and the empty-query hint row is present
  only in the Everything dialog.
- Manual: real folder, all documented examples from the README, all four
  palette rows with correct shortcut hints, 100 % and 150 % scaling for
  hint-row rendering.

## Implementation Steps

1. Settle the four remaining Decision items and record them in this document.
2. Reuse Find Files 002's size/modified fields; append defaulted creation time.
  Implement the collection matrix and extend the existing task/guards to accept
  collection flags independently of display. Validate local/provider/off paths.
3. Add `search_file_fuzzy/everything.py`: tokenizer, grammar, validation,
   hint reasons, AST; unit tests first. (Find Files 001's `query.py` holds the
   fzf tokenizer; keep the two grammars in separate modules.)
4. Add the `everything` mode to `_search`/`Matcher`: parse, select matcher,
  compute highlights, reuse `describe_metadata` and emit mode/error hints with
  the shared line-count policy. Keep fuzzy/regular results and metadata behavior
  unchanged; validate real Qt transitions before adding command bindings.
5. Add the two `_everything` commands, aliases and `Ctrl+E`/`Ctrl+Shift+E`
  bindings, forwarding `query` and `metadata` without persisting overrides.
6. Docs: README syntax/command tables, shared metadata view, upfront collection
  with the view off, snapshot/cancellation limitations and CHANGELOG entry.
7. Performance test and manual checks.

## Acceptance Criteria

- `Ctrl+F` / `Ctrl+Shift+F` and their palette rows behave exactly as before
  with the implemented Find Files 001 syntax and Find Files 002 metadata view.
- `Ctrl+E` / `Ctrl+Shift+E` open the Everything dialog with the mode hint row;
  plain text is an AND of case-insensitive substrings.
- Every grammar element in the README works and has a test.
- Invalid or partial queries never raise; the hint row explains why.
- The Command Palette shows four search rows, each with its own shortcut.
- No file under `src/main/python/fman` changes.
- Substring, wildcard and simple regex queries over 50,000 entries stay under
  50 ms on the development machine.
- Metadata filters are correct for local files and show the hint row elsewhere.
- Both Everything commands honor the existing metadata preference and invocation
  override. Filters work with the view off; enabling it formats the same captured
  size/modified values, including `0 B`, without re-querying or reindexing.
- Enabled file/hint rows reserve two lines; disabled rows are single-line.
  Missing values and transitions through mode/error hints never clip descriptions
  or change title highlights/navigation. Creation remains filter-only.
- Metadata-enabled fuzzy/regular and non-local display retain Find Files 002
  behavior; metadata-off fuzzy/regular gains no metadata work. Existing setting
  persistence/error behavior remains valid with no migration or extra setting.
- Metadata collection supports cancellation and stale rejection independently of
  view state; indexing, memory and formatting costs are recorded separately.

## Reviewers

Records before 2026_09_17 belong to the combined document
`ExtendedQuicksearchUI.md`, from which this task and Find Files 001 were split.

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
- Effort: Low
- Context Window: 1M
- Outcome: Split at the user's request. This document (Find Files 003, then
  numbered 002) keeps
  the Everything grammar, its `Ctrl+E` commands, the four open items and the
  natural-language front-end note, unchanged in substance. The fzf operators
  for the existing fuzzy dialog moved to Find Files 001, which is the earlier
  iteration. The fzf comparison table remains in 001; a cross-reference
  replaces it here.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Updated the design to support the implemented Find Files 002 metadata
  view in both Everything commands. Reuse the shared preference/override,
  formatter, size/modified snapshot and cancellation lifecycle; collect local
  filter data independently of display. Added uniform file/hint row rules,
  provider-display compatibility, creation-only record extension, cost accounting
  and focused regression requirements. Source inspection confirmed current record,
  task and renderer behavior. The four grammar/ordering decisions remain open;
  this is a design-only revision, not implementation approval or a claim that
  the proposed Everything behavior has passed tests.
