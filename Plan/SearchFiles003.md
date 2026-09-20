# Search Files 003: Extended Mode

Status: Design only; review before implementation.

## Task

Add **Extended** mode to Search Files. Its exact tooltip is
**Everything inspired mode**. Ripgrep searches first; only in Extended mode,
collect Size and Date Modified for returned files. Filter the captured results
with ordinary substring text and Everything-inspired `size:` / `dm:` conditions.

Follow-up to [Search Files 002](../Done/SearchFiles002.md).

## Scope

- A Panel toggle labeled **Extended**, off by default, for both content and
  filename-only searches. Initial filename/content patterns still use ripgrep
  and the existing Literal / Glob / RegEx controls.
- Extended results add Size and Date Modified columns. Preserve one row per
  matching line, or per file for filename-only searches.
- Plain text uses case-insensitive contiguous substring matching, not fuzzy
  subsequences. Only `size:` and `dm:` have special function meaning.
- Off mode retains the current two-column fuzzy Table without extra metadata
  collection. Preserve search eligibility, limits, navigation and focus.
- Exclude other Everything functions/aliases, result wildcard/regex matching,
  OR/NOT/grouping, live refresh, search refills and an Everything service/SDK.

Compatibility: no backward-compatibility layer or legacy-query migration is
required. Plain text is supported directly, not by falling back to fuzzy matching.
The proposed Table hooks are additive; no public API break is currently needed.

## Design

### Panel And Persistence

Place the toggle beside Recursive using an appropriate existing icon. Label and
accessible name: **Extended**. Tooltip: **Everything inspired mode**. Add a strict
boolean `extended` setting/Options field, default false, and use SearchSession's
existing coalesced settings writer. Missing/invalid values use the default.

Capture the mode when Search starts; disable its toggle with the other inputs
until results close. Show metadata progress through existing activity reporting;
Stop remains available. Persist only the toggle, not metadata or Table queries.

### Ownership And Data Flow

1. [Runner](../src/main/resources/base/Plugins/SearchFiles/search_files/engine.py)
   runs ripgrep and retains bounded accepted hits as today.
2. After children are reaped and provisional binary matches discarded, Extended
   mode attempts one additional `os.stat(path, follow_symlinks=False)` per distinct
   returned path, not per match. Reuse the existing worker and runner claim.
   Existing eligibility stats are separate; do not stat rejected candidates.
3. Capture logical `st_size` and last-write `st_mtime_ns` from the same stat result
   in a frozen metadata record shared by all hits of that path. Missing values
   are None, not zero. No path resolution or hard-link scan for deduplication.
4. [SearchSession](../src/main/resources/base/Plugins/SearchFiles/search_files/__init__.py)
   passes raw metadata in immutable TableRow.value plus formatted display cells.
   Retain owner/generation guards. No metadata I/O on Qt.
5. A small Qt-free parser in the search plug-in compiles the filter once per edit;
   the Table evaluates it entirely in memory. No private host UI imports.

Metadata is observed after search, not atomically with the searched content.
A file can change between ripgrep and stat. Only an explicit rerun refreshes it.

### Results Table

[Table.project](../src/main/python/fman/impl/ui/table.py) currently fuzzy-matches
cells and sorts strings. Add two optional hooks through
[show_table](../src/main/python/fman/impl/ui/facade.py):

- `compile_filter(query)` returns a pure row predicate, replacing fuzzy matching
  for Extended results. Empty query accepts all. Keep the filter box visible.
- `get_sort_key(row, column)` returns integers for metadata, casefolded strings
  for text, or None. Unknown sorts last in both directions. Preserve stable
  ordering and the existing ascending/descending/unsorted cycle.

Callbacks run on Qt and must be bounded and I/O-free. Reuse approximately 6 ms
projection slices, checking deadlines even for rejected rows. Metadata-only
queries must not bypass predicates through an empty-text fast path. Preserve
source hit highlights and selection by row ID; no fuzzy ranking in Extended mode.
Retain captured order until sorting. Document hooks in [PlugIn.md](../PlugIn.md).

Invalid/partial reserved clauses clear the projection and selection, retain source
rows, and show a concise inline error in the counts area. No modal typing errors.
Handle malformed callback results/exceptions. Invalidate queued projections and
actions on edits/refresh/close; disable row actions while invalid or pending.

Columns: **File Path**, **Size**, **Date Modified**, **Snippet**. Keep navigation
at column 0; remap snippet spans to column 3. Display grouped exact bytes with
` B`, local `YYYY-MM-DD HH:MM:SS`, or `Unknown`. Compare raw numbers, never cells.
Constrain metadata widths, stretch Snippet, allow horizontal scrolling at minimum
window size. Counts show visible / captured rows, not filesystem-wide totals.

### Query Contract

Reference: [Everything Search Functions](https://www.voidtools.com/support/everything/search_functions/).
This is a defined subset, not full Everything compatibility.

| Query | Meaning |
| --- | --- |
| `report` | Substring in File Path or Snippet, case-insensitive |
| `annual report` | Both substrings must match; they may match different text columns |
| `"annual report"` | One contiguous phrase |
| `report size:>1mb dm:>=2026-01-01` | Text AND size AND modified-date conditions |
| `size:1kb` | 1,024 through 2,047 bytes, following Everything's unit granularity |
| `size:=1kb` | Exactly 1,024 bytes |
| `size:1mb..10mb` | Inclusive exact-byte range, 1,048,576 through 10,485,760 |
| `size:0` | Exactly zero bytes |
| `dm:2026-09-17`, `dm:2026-09`, `dm:2026` | Within that local day/month/year |
| `dm:2026-01-01..2026-06-30` | Includes the entire first and last days |
| `dm:today`, `dm:yesterday` | Corresponding local calendar day |
| `"size:large"` | Literal text, not a size clause |

- Whitespace outside double quotes separates ANDed terms. Quotes form literal
  phrases; doubled quotes inside a phrase represent a quote. Backslashes remain
  literal. Reject unterminated quotes; do not use shell/argv parsing.
- Only unquoted tokens starting with `size:` or `dm:` are functions, ignoring
  case. Malformed reserved clauses are errors, never literal/fuzzy fallback.
  Other prefixes such as `error:` are plain text. `*`, `?`, `!`, `|` and grouping
  characters have no special matching meaning in plain text.
- Text searches File Path/Snippet, not formatted metadata: an intentional
  Table-specific difference from Everything's default filename-only matching.
  Metadata filters act on all file rows; snippet terms can select individual lines.
- Initial sizes: nonnegative integers, bytes by default, or B/KB/MB/GB/TB using
  powers of 1024. Support bare unit-granularity values, exact `=`/`==`, `<`, `<=`,
  `>`, `>=`, inclusive `a..b`. Comparisons/range endpoints use exact converted
  bytes; no unit inheritance. Reject missing/reversed bounds and signed-64-bit
  overflow. Decimals, extra suffixes and constants are deferred.
- Initial dates: YYYY, YYYY-MM, YYYY-MM-DD, today/yesterday; bare periods, `<`,
  `<=`, `>`, `>=`, inclusive `a..b`. Expand periods to `[start, next_start)`.
  Bare means within; `>=` compares to start; `>` accepts from next_start onward;
  `<` is before start; `<=` before next_start. Ranges include both endpoint periods.
  Reject invalid/reversed/unrepresentable boundaries. Time-of-day, locale dates,
  durations, explicit equality operators and other constants are deferred.
- Convert local calendar boundaries to epoch ns once per compilation using OS
  historical timezone/DST rules, not a fixed current offset. Advance by calendar
  days, not 86,400 seconds. Freeze today/yesterday when results open; no timer.
  Inject clock/boundary conversion for deterministic tests.
- Cap queries at 4096 characters/32 terms; use linear standard-library parsing.
  Unknown metadata fails conditions on that property but remains available for
  text-only/empty queries. Clearing the query restores captured rows.

### Failures, Cancellation And Limits

- Missing/denied/nonregular/reparse targets get Unknown metadata; retain matches.
  Report failures per distinct file separately from search failures/skips, with
  bounded state rather than arbitrary per-row error text.
- Check Stop/cancellation before each stat and publication. Already Stopped/Error
  or empty searches skip enrichment. Stop during enrichment retains completed
  values, leaves remaining values Unknown and returns Stopped, preserving earlier
  Limited/Incomplete reasons. Closing/unloading rejects stale completion.
- A blocked OS stat cannot safely be forcibly interrupted. Qt stays responsive;
  start no subsequent stat after cancellation and release the claim when it returns.
- Enrich Complete/Limited/Incomplete snapshots without changing initial limits.
  Filtering never refills omitted rows or reruns ripgrep. The default 50 MiB file
  eligibility cap still applies before filtering.
- Budget new cells/payload during both Collector admission paths, including pending
  content rows. A bounded extra 128 bytes per Extended row is proposed; verify
  full accounting against [TableSchema](../src/main/python/fman/impl/ui/table_data.py)'s
  actual 16 MiB cap. Require usable Limited results, not late all-row rejection.

## Alternatives

- Metadata per enumerated file/per match: rejected; unnecessary or duplicate I/O.
- Pre-search filtering/live rescans: rejected; this feature refines captured rows.
- Metadata-only queries or fuzzy auto-detection: rejected; Extended consistently
  supports substring text plus optional size/date conditions.
- Full Everything grammar/compatibility adapters: unnecessary for this scope.
- Custom result widgets/private host access: rejected; reuse Table lifecycle and
  navigation through small hooks, with grammar owned by the plug-in.

## Runtime Effects

- Off/startup/idle: no extra metadata stat/map, worker, scan, timer or recurring
  signal work. Existing normal-search costs remain.
- On: existing ripgrep work plus at most one added stat per returned path on the
  same worker. Metadata can require disk/network I/O, but no content reread.
- Memory: O(rows + files), bounded by existing row/payload caps; shared records,
  no permanent cache. Dispose releases snapshots/callbacks.
- Filtering is time-sliced in-memory work; sorting O(rows log rows). No I/O or
  processes after publication. Cancellation has the blocked-stat limitation above.
- Only user toggle changes write preferences. No Registry writes/new packages.

## Tests

Required implementation checks, not claims about unimplemented behavior:

- Parser: every example, substring versus fuzzy, phrases/quotes, AND across cells,
  literal unknown prefixes, invalid clauses, size granularity/boundaries/overflow,
  leap/month/year/DST boundaries, fixed relative dates, Unknown and input caps.
- Engine: both search kinds/all name modes, one added stat per returned path,
  shared raw values, missing/denied/replaced targets, no added metadata work off,
  no rejected-candidate stat and no content reread.
- Lifecycle: Stop before/during enrichment, controlled blocked-stat release,
  close/unload/stale generation, claim release, child cleanup and partial reasons.
- Budgets: 10,000 rows, near-16-MiB Unicode/path/snippet snapshots through real
  TableSchema, repeated matches and both admission paths; no all-results loss.
- Qt: exact Extended label/tooltip, temporary settings persistence, busy lock,
  progress, columns/spans, mixed and metadata-only queries, invalid-to-valid edits,
  clear, typed sorting/Unknown last, selection/actions, 002 navigation/focus cases.
- Performance: 10,000-row accepting/rejecting/mixed scans; one compilation per edit,
  no stat/Popen after publication, event-loop heartbeat during scanning. Record
  filter/sort p50/p95; target metadata-only p95 below 100 ms locally, with a generous
  1 s regression ceiling, not a storage-performance guarantee.
- Native manual: both modes/search kinds, examples, deleted file, Stop/close,
  minimum/wide window geometry/scrolling, Enter/double-click/Go To/Escape focus.
  Record unavailable environmental checks, including slow-share testing.

Focused commands using [build.py](../build.py)'s environment:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_unittest.test_search_files', 'fman_integrationtest.test_search_files_engine', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'fman_integrationtest.qt_runner', 'fman_integrationtest.test_qt.SearchFilesIT', 'fman_integrationtest.test_qt.TableIT', 'fman_integrationtest.test_qt.PanelIT'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_unittest.test_ui_elements', 'fman_unittest.test_portable.PluginApiCompatibilityTest', '-v'], env=build._environment()))"
```

Reuse existing test modules. No full suite, clean or freeze unless asked.

## Implementation Steps

1. Review substring targets, initial value subset and Table hook contracts.
2. Add parser/example tests; validate immediately with focused tests.
3. Add Options, cancellable enrichment and admission budgeting; run engine checks.
4. Add Table predicate/sort hooks and error states; run shared Table checks.
5. Wire Extended toggle/settings/results; run native Qt workflow checks.
6. Measure bounds/performance; update main/plug-in usage, API docs and application
   changelog. Record implementation/validation, then move the canonical task to
   Done and its index link to Completed. No application edits in this design pass.

## Acceptance Criteria

- Panel label is **Extended**; tooltip is exactly **Everything inspired mode**.
- Only Extended collects extra metadata, after ripgrep, once per returned path.
- Plain/quoted substring text and only `size:`/`dm:` functions combine with AND.
- Filtering/sorting is in-memory, uses raw metadata, preserves limits/status and
  never refills results. Unknown/invalid input has the defined behavior.
- Off mode adds no feature-specific I/O/background work. Cancellation, persistence,
  budgets and navigation/focus pass focused checks; limitations are recorded.

## Reviewers

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Grounded in Runner lifecycle, immutable payload limits and Table
  projection. Final user wording is Extended / Everything inspired mode.
  Metadata is mode-only; plain text uses substrings plus size:/dm: conditions.
  No compatibility layer or full Everything grammar. Awaiting design review.