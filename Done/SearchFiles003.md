# Search Files 003: Extended Mode

Status: Implemented 2026_10_03.

## Task

Add **Extended** mode to Search Files. Its exact tooltip is
**Extended metadata mode** (renamed 2026_10_03 from "Everything inspired mode":
the filter no longer uses Everything syntax). Ripgrep searches first; only in Extended mode,
collect Size and Date Modified for returned files. Filter the captured results
with ordinary substring text plus typed Size / Date Modified column filters.

Follow-up to [Search Files 002](../Done/SearchFiles002.md).

## Scope

- A Panel toggle labeled **Extended**, off by default, for both content and
  filename-only searches. Initial filename/content patterns still use ripgrep
  and the existing Literal / Glob / RegEx controls.
- Extended results add Size and Date Modified columns. Preserve one row per
  matching line, or per file for filename-only searches.
- Plain text uses case-insensitive contiguous substring matching, not fuzzy
  subsequences. Size and date conditions use Table column filters.
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
accessible name: **Extended**. Tooltip: **Extended metadata mode**. Add a strict
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

Revised for [UI Elements 001](UIElements001.md): the earlier `size:` / `dm:`
clauses and raw-row `compile_filter` / `get_sort_key` hooks are superseded.
Size and Date Modified filtering and sorting use typed QuickTable columns.

Columns: `QuickTableColumn('File Path', 'file_path')`,
`QuickTableColumn('Size', 'numeric', unit='bytes')`, `QuickTableColumn('Date Modified', 'date')`,
`QuickTableColumn('Snippet')` (see [UI Elements 001](UIElements001.md#columns)).
The File Path kind provides navigation; snippet spans move to column 3. Cells are
`(relative_path, st_size, st_mtime_ns, snippet)` with `None` for missing values.
Size shows grouped bytes (`12,345 B`) or `Unknown`; the host formats dates as
ISO 8601 with offset.
Header funnels and Alt+Down open the QuickTable's size/date filter menus. Counts show
visible / captured rows; `truncated` is True for Limited/Stopped, False for
Complete and None otherwise.

Results open with a blocking modal `show_quick_table(rows=...)` showing the
captured root and run summary ([UI Elements 001](UIElements001.md#keys)).
Search Files ignores the Enter result: Enter closes the results; Ctrl+Enter or
double-click goes to the file.

### Query Contract

The filter box uses [query.py](../src/main/resources/base/Plugins/SearchFiles/search_files/query.py)
through `show_quick_table(text_filter=compile_text_filter)`. It sees only File Path and Snippet.

| Query | Meaning |
| --- | --- |
| `report` | Substring in File Path or Snippet, case-insensitive |
| `annual report` | Both substrings must match; they may match different columns |
| `"annual report"` | One contiguous phrase |
| `"say ""hi"""` | Phrase containing `say "hi"` |

- Whitespace outside double quotes separates ANDed terms. Backslashes and other
  characters are literal. Unterminated quotes are errors shown inline.
- Caps: 4,096 characters, 32 terms. Linear standard-library parsing.
- Clearing the query restores captured rows; column filters still apply.

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

- Panel label is **Extended**; tooltip is exactly **Extended metadata mode**.
- Only Extended collects extra metadata, after ripgrep, once per returned path.
- Plain/quoted substring text combines with typed Size/Date column filters (AND).
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

### 2026_10_03 - Maintainer and Documenter Claude Opus 5.5

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Aligned with UI Elements 001. `size:` / `dm:` clauses and raw-row
  hooks replaced by typed Table columns; the text hook keeps substring/phrase AND.

## Implementer

### 2026_10_03 - Maintainer and Documenter Claude Opus 5.5

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Extended toggle (custom `table-columns.svg`), persisted `extended`
  setting, `Options.extended`, 128-byte per-row budget in both admission paths,
  one `os.stat(follow_symlinks=False)` per distinct returned path after ripgrep
  with per-stat cancellation, `Result.metadata` / `metadata_missing`, four typed
  columns, [query.py](../src/main/resources/base/Plugins/SearchFiles/search_files/query.py)
  text hook and `truncated` mapping. Off mode unchanged.

### 2026_10_03 - Maintainer and Documenter Claude Opus 5.5 (Static Table)

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Migrated to the blocking static Table: `result_row()` builds rows,
  `completed()` captures the root before re-enabling the form, then shows
  results modally. Validation is recorded in
  [UI Elements 001](UIElements001.md#validation-results).

## Validation Results

Commands and shared results are recorded in
[UI Elements 001](UIElements001.md#validation-results). Specific to this task:

- `fman_unittest.test_search_files`: new `ExtendedModeTest` covers the query
  parser and caps, settings/Options validation, budget, one stat per path,
  failure count, Stop during metadata and typed-row schema fit.
- `SearchFilesIT.test_extended_mode_typed_results_and_text_query`: real ripgrep
  search, toggle tooltip/icon, persistence, columns, raw values, phrase query,
  error text and size sort. Existing layout/lock tests updated for the toggle.
- Not run: slow-share/blocked-stat test, denied-file manual check.