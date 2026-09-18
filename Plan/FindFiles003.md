# Find Files 003: Everything-Style Query Syntax

Status: Design; grammar decided (Everything syntax on new `Ctrl+E` commands,
fuzzy retained on `Ctrl+F`). Open items 1-4 under Decision remain. Split from
`ExtendedQuicksearchUI.md`; the fzf operators for the existing fuzzy dialog are
[Find Files 001](../Done/FindFiles001.md).

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
other.

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
- Index metadata the grammar needs (size, modification and creation time for
  `file://` entries), collected during the existing `os.scandir` walk and
  shared by both modes.
- README syntax table naming Everything as the reference; tests.

Excluded:

- Any change to `show_quicksearch`, `QuicksearchItem`, the Quicksearch widget,
  the pane filter bar or other pickers (Command Palette, Go To, Favorites,
  Open With, hash picker).
- fzf syntax, a `fuzzy:` modifier inside the Everything grammar, or any other
  mixing of the two models; bundling or depending on fzf, Everything, `pfzy`,
  `luqum`, `everything-sdk` or any other package.
- Content search (Search File Content keeps its Panel controls).

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
existing command identifiers, aliases, bindings and the `mode`/`query`
arguments are unchanged; `mode` gains the value `everything`, and the two new
commands are additive.

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
  raise on the Qt thread. Yield one `QuicksearchItem(None, 'Invalid ...',
  description=<reason>)`; selecting it does nothing because its value is
  `None`. Never show a traceback dialog for a query.
- **Regex safety.** Python `re` cannot be interrupted; a pathological pattern
  over 50,000 paths of up to 260 characters can freeze the UI for seconds.
  Mitigations: cap pattern length (256), compile once per keystroke, match
  the relative path only, and document the residual risk. No timeout exists
  without a third-party engine.
- **Metadata.** On Windows `entry.stat(follow_symlinks=False)` from
  `os.scandir` supplies `st_size`, `st_mtime_ns` and `st_ctime_ns` (creation)
  from the directory listing without extra syscalls; the fman-index path for
  other schemes would need `fs.query` per entry and is out of scope: metadata
  terms on non-`file://` roots produce the hint row.
- **Ordering.** Unranked results return the first `max_results` in index
  order (breadth-first), as today's `regular` mode does, unless open item 4
  adds a sort.

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
- **Metadata cost.** Two integers per entry (about 1.6 MB for 50,000 entries)
  and the `stat` call per `scandir` entry, which is free on Windows but is a
  real syscall on other filesystems.

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
an empty query yields one leading hint row `Everything syntax` with a short
description of the markers (`"phrase"  *.ext  !not  case:  regex:  ext:  size:
dm:`); its value is `None` so selecting it does nothing. The fuzzy dialog is
unchanged.

Open items still to settle, each to be recorded here:

1. Wildcard semantics: whole-name (Everything) or substring (pane filter).
2. Default match target: filename (Everything) or relative path (today).
3. The exact date and size subset, and the `regex:` length cap.
4. Result ordering: walk order with `max_results` cut, or a sort by path.

Settled: `mode` keeps `fuzzy` and `regular` and gains `everything`; the JSON
default stays `fuzzy` so the unchanged commands behave as today.

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

- Startup: none.
- Per invocation: the existing index walk plus two integers per entry when
  metadata is collected (about 1.6 MB at 50,000 entries).
- Per keystroke on Qt: parse (well under 1 ms) plus one scan of the index:
  substring 5-15 ms, wildcard/regex 15-50 ms at 50,000 entries. No timers,
  workers or I/O.
- Cancellation: not applicable; nothing outlives the keystroke.
- No-op path: the fuzzy commands are unchanged; an Everything query without
  markers is a plain AND of substrings and costs the same as today's
  `regular` mode.

## Tests

Focused commands:

```powershell
$env:PYTHONPATH="src/main/python;src/unittest/python;src/integrationtest/python;src/main/resources/base/Plugins/Core;src/main/resources/base/Plugins/SearchFileFuzzy"
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest fman_unittest.test_search_file_fuzzy
```

- Parser: one test per grammar element, escaping, phrases, precedence,
  unknown modifiers, partial input at every prefix of representative queries
  (never raises).
- Matcher: each mode with highlight positions mapped to the backslash title;
  case handling; wildcard whole-name vs substring per decision.
- Metadata: size and date parsing edge cases (`today` across midnight, month
  ends, ranges, comparisons), `file://` only, hint row on other schemes.
- Regex: invalid pattern -> hint row; pattern over the cap -> hint row.
- Performance: synthetic 50,000-entry index; substring, wildcard and simple
  regex each under 50 ms on the development machine.
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
2. Extend `SearchEntry` with size, modified and created times from `scandir`.
3. Add `search_file_fuzzy/everything.py`: tokenizer, grammar, validation,
   hint reasons, AST; unit tests first. (Find Files 001's `query.py` holds the
   fzf tokenizer; keep the two grammars in separate modules.)
4. Add the `everything` mode to `_search`/`Matcher`: parse, select matcher,
   compute highlights, emit the mode hint row and error rows; keep index
   construction and the fuzzy/regular paths unchanged.
5. Add the two `_everything` commands, aliases and `Ctrl+E`/`Ctrl+Shift+E`
   bindings.
6. Docs: README syntax table naming Everything, command table, CHANGELOG
   entry.
7. Performance test and manual checks.

## Acceptance Criteria

- `Ctrl+F` / `Ctrl+Shift+F` and their palette rows behave exactly as before
  (or as specified by Find Files 001 if that ships first).
- `Ctrl+E` / `Ctrl+Shift+E` open the Everything dialog with the mode hint row;
  plain text is an AND of case-insensitive substrings.
- Every grammar element in the README works and has a test.
- Invalid or partial queries never raise; the hint row explains why.
- The Command Palette shows four search rows, each with its own shortcut.
- No file under `src/main/python/fman` changes.
- Substring, wildcard and simple regex queries over 50,000 entries stay under
  50 ms on the development machine.
- Metadata filters are correct for local files and show the hint row elsewhere.

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
