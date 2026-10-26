# QuickView 005: CSV and TSV Tables

## Task

Add read-only CSV/TSV tables to QuickView, with a single toggle button switching
between **Text View** and **Table View** only when both modes support the file.
Make ordinary files up to the default 2048 MB Table View limit practical to
browse, filter and sort without loading their contents into application memory.
Faulty CSV/TSV must never silently display repaired data. Fall back to Text View
only within its full-file size limit; larger files remain Table-only and show
the actual failure instead.

Status: Completed on 2026-10-26 by user decision. Implemented after the Opus
re-review, with implementation-review fixes IR1-IR6 and presets of 192/384/768 MiB.
Focused unit and Qt tests pass on native and offscreen Qt; the regular `csv.load`
performance workload passes. Deferred, not run: the exact-cap
`quickview.csv.large` workload, the frozen-artifact smoke run and manual DPI/theme
checks; see Validation Results.

## Scope

- Case-insensitive `.csv` and `.tsv` local/UNC regular files, following existing
  QuickView resolution and link policy. No archive or other provider support.
- Default to Table View when the format can be identified. Text View reuses the
  existing text loader, selection and Find, but is available for CSV/TSV only
  when the entire source is at most 2 MiB. Do not offer a truncated text prefix
  for larger CSV/TSV; unrelated text previews retain their existing behavior.
- Include delimiter/encoding/header controls, table navigation, whole-file
  filtering and sorting, bounded copy, Find and selected-cell inspection.
- No editing, saving, formulas, spreadsheet import, automatic value conversion,
  numeric/date column modes, multi-column sorting, or public plug-in API changes.
  Values remain strings: leading zeros, long identifiers and empty fields survive.
- Use DuckDB as the sole table parser/storage/query engine, selected by the user
  after the comparison below. The conda-forge dependency is `python-duckdb`.
  SQLite remains a historical benchmark alternative, not a runtime fallback.
  No Qt upgrade or prerequisite change to QuickTable's data API.
- User-selected Table View policy: exactly three maximum-file-size presets,
  512 / 1024 / 2048 MB, mapped respectively to 128 / 256 / 512 MiB of DuckDB
  managed memory. Default: 2048 MB with 512 MiB. No independent cache setting,
  arbitrary numeric input or automatic budget escalation. The measured 4 GB
  success does not expand these supported limits or guarantee arbitrary CSVs.
- Do not implement video support from [QuickView002.md](../Plan/QuickView002.md) as part
  of this task. Images, PDFs and other text previews remain unchanged.

## Design

### File-Size Presets and Mode Availability

Expose one global **Table View maximum file size (MB)** setting with exactly
three choices. Persist `quickview_table_max_file_mb` through the existing Core
`Core Settings.json` mechanism under UserSettings; do not persist a second cache value.
Missing, invalid, boolean or unsupported values use the default 2048, without
silently coercing or rounding an arbitrary number into another preset.

Provide a Core command-palette command **Set QuickView table limit**
(`set_quick_view_table_limit`), opening the existing QuickSearch chooser with
only the three presets below, their derived memory budgets and the current
selection. Cancel changes nothing. Save through the existing settings layer,
preserve unrelated keys and notify active sessions only after a successful save.
No new Settings window, numeric input or default keyboard binding. The chooser
must not start DuckDB or read the selected source. Manual JSON editing remains
supported. Document the command and key in
[configuration.md](../docs/configuration.md) when the feature is implemented.

| Maximum File MB | DuckDB Memory MiB | Default |
| --------------- | ----------------- | ------- |
| 512             | 192               | No      |
| 1024            | 384               | No      |
| 2048            | 768               | Yes     |

File-size MB means 1,000,000 bytes; engine-memory MiB means 1,048,576 bytes.
The default source limit is therefore 2,048,000,000 bytes, not the earlier
2,000,000,000-byte recommendation and not 2 GiB. Equality is accepted. Derive
the memory limit solely from the selected preset; do not select a smaller cache
automatically for a small file or expand it when import/sort runs out of memory.
These are user-chosen admission margins, not measured universal maxima.

Text eligibility uses the existing `READ_LIMIT` of 2,097,152 source bytes, not
decoded string size, delimiter detection or whether a prefix can be displayed.
Apply the following policy to every CSV/TSV activation, retry and fallback:

| Source Size                    | Text View | Table View         | Mode Toggle |
| ------------------------------ | --------- | ------------------ | ----------- |
| At most 2,097,152 bytes        | Available | Attempt by default | Available   |
| Above 2 MiB, within preset cap | No        | Attempt only       | Hidden      |
| Above the selected preset cap  | No        | Unavailable        | Hidden      |

All table attempts remain subject to parsing, encoding and runtime resource
limits. Above the selected cap, show an inline size-limit reason without
initializing DuckDB or reading a text prefix. Do not automatically increase the
preset; the user may select a larger supported preset and retry. If file size
cannot be established, show the access/stat failure rather than guessing a mode.
Check metadata off Qt before mode publication and enforce the cap during reads;
file growth or replacement invalidates the generation and recomputes eligibility.
Never publish a truncated Text View if a source grows beyond the text limit.

When the preference changes for an active CSV/TSV selection, invalidate work,
cancel/reap the old helper and release its cache before applying the new budget.
Recheck the selected file against the new cap before restarting Table View.
If Text View is selected and remains eligible, keep it without starting DuckDB.
Preference changes while QuickView is inactive cause no CSV jobs or I/O; a future
activation reads the stored preset. All windows observe the global preference.

User documentation must describe lower presets as the lower-memory,
lower-latency choice, at the cost of accepting smaller files. Distinguish the
engine budget from total process RAM. The latency benefit is a profile goal,
not a measured guarantee for the same file: a smaller cache may spill more and
slow import/sort, and cold helper/module startup is not removed by this setting.
Measure first paint and whole-file operations for each preset before publishing
quantitative performance claims. Preserve the cold/warm measurements below as
evidence for helper reuse, not evidence that smaller cache settings are faster.

### Ownership and Integration

Extend [QuickViewSession](../src/main/python/fman/impl/quick_view.py) and its
overlay with one lazy CSV view/controller. Route CSV/TSV before the text fallback
in [load_preview](../src/main/python/fman/impl/quick_view_images.py). Text View
explicitly requests the existing
[text loader](../src/main/python/fman/impl/quick_view_text.py), avoiding a routing
loop back into Table View. No general viewer registry is required.

The session owns the selected-file generation, mode and file fingerprint. All
widgets, models, presentation state and result acceptance stay on Qt. One lazy
helper process per window owns DuckDB parsing, file I/O and query execution;
it receives immutable requests and returns bounded plain-data pages. Keep the
worker importable without `fman` or Qt, as for the existing PDF helper. Reuse its
source/frozen launch, parent-ownership and teardown conventions where suitable,
without sharing PDF document state or introducing a general worker framework.

Use one active operation and one latest pending request, not an unbounded queue.
Replies carry helper identity, file generation and presentation revision. Reject
stale pages, queries, errors and copy results. Navigation, settings changes,
mode switches, owner unload and window close invalidate work immediately.
Cooperative checks handle ordinary cancellation; terminate and reap a blocked
helper after a bounded deadline. At most one active/retiring CSV helper exists
per window, including rapid close/reopen.

### Parsing and Faulty Input

- Read at most 256 KiB for initial encoding/header hints. TSV defaults to tab;
  CSV tries comma, semicolon, tab and pipe using DuckDB dialect detection or
  explicit options. Detection is a heuristic, not validation. Verify DuckDB's
  actual sampling/buffering I/O; a logical sample-size setting is not a hard byte
  limit. A sample ending inside a quoted record is inconclusive, not malformed.
  Ambiguous/no credible table format uses the size-aware failure path below;
  retain explicit parsing controls so a large file can be retried.
- Offer explicit delimiter, encoding, quoting and first-record-is-header controls.
  Header detection is only a suggestion. Table encodings are UTF-8 (optional BOM,
  default), UTF-16 little-endian (BOM required), and explicit ISO-8859-1/Latin-1.
  A UTF-16 big-endian BOM is refused: DuckDB 1.5.6 returned zero rows for it
  without an error, and decoded a BOM-less UTF-8 file as UTF-16 without an error.
  Verify this exact set in the bundled DuckDB; no encodings extension, downloads,
  Windows-ANSI autodetection or second table parser. A BOM selects its supported
  encoding; otherwise try UTF-8 strictly and require an explicit override on
  failure. Do not automatically retry Latin-1, which accepts every byte.
  Unsupported encodings use the size-aware failure path. Do not insert replacement
  characters or change encodings halfway through a file. Changed options start
  a fresh generation.
- Reject Latin-1 results containing C1 controls U+0080-U+009F, including header
  labels, before publishing each provisional page and throughout full validation.
  Report unsupported/ambiguous encoding, not malformed CSV: cp1252 currency and
  smart quotes must not silently become C1 controls. Text View keeps its existing
  locale-ANSI/replacement behavior; preserve the Table refusal reason alongside
  its actual encoding warning when falling back within 2 MiB. A successful Text
  decode does not certify strict Table decoding. Document this intentional
  difference and the supported Table encodings; do not change other text previews.
- Use DuckDB `read_csv` with explicit string column types, strict parsing and no
  ignored errors/null-padding. Preserve empty fields as strings, including quoted
  empty fields: set `allow_quoted_nulls=false` and `force_not_null` for every
  detected/generated column, with no additional NULL spellings. Assert both an
  unquoted empty field and `""` return `''`, not NULL; strings such as `NULL`
  remain literal values. Apply these settings to first-page reads and full import.
  Disable automatic extension installation/loading and unintended external URL
  access in the helper. Define accepted grammar by that parser/dialect, not a
  claim of universal RFC validation. Preserve quoted delimiters/newlines and
  escaped quotes; never split records at physical lines.
- All nonblank data records must have the same field count as the selected header
  or first data record. Skip truly blank records; a record containing explicit
  empty fields remains data. Duplicate/empty header labels use stable internal
  column IDs and display disambiguation; they are not malformed data.
- Decode errors, parser errors, inconsistent field counts and binary/NUL content
  invalidate the table. Do not skip bad records, pad missing fields, truncate
  extra fields or switch dialect silently. A valid single-column file is not
  inherently faulty, though automatic delimiter detection may be inconclusive.
- Start with limits of 256 columns, 1,048,576 Unicode characters per field and
  4,194,304 per serialized logical record, including CSV quotes/separators.
  Explicit normal-path settings: `max_line_size=16777216` (16 MiB encoded bytes)
  and `buffer_size=33554432` (32 MiB, twice that limit), in all presets. The
  earlier 64 MiB buffer failed the feasibility gate: a 100 MB import at the
  128 MiB preset could not allocate it. 32 MiB passed at every preset and still
  reads a 15 MiB record, so the advertised limits are unchanged.
  A UTF-8 scalar can occupy four bytes; character limits alone are not buffer
  limits. Validate decoded-character limits separately without dropping the
  encoded-byte bound, and count parser buffers against memory accounting.
  Verify DuckDB's treatment of quoted multiline records, quote expansion, BOMs,
  UTF-16/transcoded bytes and boundary equality before accepting these settings.
  If they cannot enforce bounded reads without rejecting advertised inputs,
  stop at the feasibility gate and revise explicitly; do not quietly lower limits.
  Reject over-limit input as unsupported for Table View, not corrupt CSV.
  The reduced first-page buffer experiment is not the initial production path;
  enable it only after retry/parity and actual preset-memory gates pass.

Show first rows provisionally with a **Validating** state while sequential parsing
continues. Complete validation requires EOF; a bounded probe cannot establish
that a file within the selected preset cap is valid. On any later fault,
invalidate provisional rows and queued operations and dispose the incomplete
cache. At or below 2 MiB, switch automatically to Text View. Above 2 MiB, remain
in the Table View error state without a mode toggle or prefix-text escape path.
Show the reason and logical record/physical line where available in either case.

Remember the rejected fingerprint/options for this selection so the same error
does not cause automatic retry loops. Text View remains usable only when size
permits it. The toggle does not retry the same rejected configuration; explicit
Retry Table or changed parsing options permits another eligible attempt. Read
failures, resource limits and disk-full errors use the same size-aware policy,
retaining their actual reason rather than mislabeling the file as malformed.
Missing/inaccessible files show the access error; a failed text load shows the
existing inline error. Never invent a successful fallback. Large-file failures
retain parsing controls and explicit retry; the task does not add an external
editor command or a third preview mode.

### Large-File Storage and Queries

Use one disposable DuckDB store instead of source-byte checkpoints and a separate
query engine. Keep a lazy bootstrap connection while Table View is active and
attach one owned per-file database at a time. Release the previous file's handles,
cache and query state on replacement; reuse the imported module/engine only after
in-flight work is canceled. A failed/hung helper still retires normally.

Fetch an initial bounded page directly from `read_csv` without importing the whole
file. Then import strictly into generated string columns and stable source-record
IDs using verified native ordinals (`WITH ORDINALITY`), with physical insertion
order relaxed. Preserve original strings; never execute input/filter text as SQL.
Verify how DuckDB numbers blank/header records against the documented displayed
data-record ordinal. Do not equate physical database insertion order with source
order. All file-order queries explicitly order by that source identity.

The prototype rereads the small first-page prefix when full import begins; no
claim of a single total source pass. Show provisional first rows during import;
the initial CTAS design does not expose uncommitted rows from the importing
statement. Requesting a later page/End/row waits with progress and Cancel until
import commits. Exact counts and full projections become available after EOF.
Investigate batch publication separately if required; do not promise incremental
browsing from committed batches that this DuckDB prototype has not implemented.

After validation, execute whole-file filters natively in DuckDB. Send validated
operator/value descriptors, never `ColumnFilter` closures, across IPC. Trim
column queries and reject empty input exactly like QuickTable. Bind query values
as parameters and generate column identifiers only from internal IDs:

- Contains: `contains(folded_column, ?)` with the Python-casefolded query.
- Fuzzy: `folded_column LIKE ? ESCAPE '\'`, where the bound pattern is `%`,
  then each casefolded query character separated by `%`, then `%`. Escape literal
  `\`, `%` and `_` in each character before adding wildcard separators. This is
  a subsequence test, not regex, ranking, or fuzzy edit distance.
- AND between active column filters; OR across data columns for the global
  case-insensitive Contains input, then AND with the column filters. Inspect
  complete strings, not elided display values. Empty global input adds no test.

Prepare disk-backed folded columns once per file/column on first filter, Find or
sort use. Native ASCII detection (`strlen(value) = length(value)`) plus `lower`
handles ASCII without Python cell callbacks. For non-ASCII only, fetch bounded
batches keyed by source ID, apply Python `str.casefold`, and stream the folded
values into a staging CSV in the owned cache; one native `UPDATE ... FROM
read_csv(staging)` writes them back. A DuckDB Python UDF is not an option: in
DuckDB 1.5.6 it requires NumPy, which the build excludes. Bound batches by encoded bytes
as well as row count; do not retain an unbounded distinct-string dictionary.
Publish the completed fold cache atomically and reuse it across revisions and
sorts. Global matching may prepare every column; show that one-time cost with
progress/cancellation. This is preprocessing, never a per-revision Python scan.
An Arrow/vectorized UDF is not a prerequisite and must not add an unapproved
dependency. Measure this bounded non-ASCII path before choosing a UDF alternative.

Use binary ordering on folded UTF-8 keys for sorting; verify exact Python
`str.casefold`/code-point order, including expansions, combining marks and emoji.
Keep original record order as the tie breaker in both directions. QuickTable's
Python predicates remain unchanged and are the parity oracle in tests, not the
production large-file query engine. The helper must not import Qt or `fman`.
Build a disk-backed result mapping `(position INTEGER PRIMARY KEY, source_record)`
for the entire matching set; read pages by indexed position ranges, never deep
`OFFSET`. Keep fold caches, old/new projections and staging writes within the
same memory/disk quotas. No Python collation callback per sort comparison.

Publish a new projection atomically after completion, never a sorted subset of
cached rows. During work, keep the last settled view visibly marked as pending;
disable copy and selection actions that could use a stale projection. Controls
remain usable; a new revision cancels the old one. Filters/sorts requested during
validation are pending and execute only if validation succeeds. Cancellation or
query resource failure retains the last settled view and offers Text View only
when size permits; otherwise show the query error with retry/clear controls.
A query failure is not evidence of malformed CSV.

Store the database, result mappings and DuckDB spill files in an exclusively owned
directory under `UserSettings/Cache/QuickViewCsv`. No source-side files, Registry
writes or durable imported database. Set DuckDB `memory_limit` from the selected
preset (192/384/768 MiB), with one query thread, explicit owned `temp_directory`
and bounded spill allowance. The default is `memory_limit='512MiB'`.
This setting is not total process RAM; measured child working sets reach about
600 MiB. Verify allocations and temporary files outside DuckDB's managed buffers.

Per-window owned-cache quota in bytes:
`min(8 * 1024**3, max(16 * 1024**2, 2 * source_size_bytes))`. The 16 MiB floor
allows tiny/empty-file database overhead; the quota is a ceiling, not eagerly
allocated space. Include database/WAL, spill, folded columns and old/new/staging
projections, not the source. At the default exact source cap this is
4,096,000,000 bytes, not a flat 8 GiB allocation for every window.
Before import, require free space on the cache volume of at least the quota plus
a 64 MiB reserve; report required/available bytes and the quota in the error.
Recheck before fold/projection operations and watch growth during active work.
Set the DuckDB spill allowance from the remaining total quota, not another 8 GiB.
Concurrent windows can race for free space, so allocation failures remain local.
DuckDB spill settings alone do not bound database/WAL growth, and sampled directory
sizes are not proof of enforcement. Verify bounded total growth/interruption
before integration; stop if this quota cannot be enforced. A file within the
source cap may still exceed its cache quota. Do not silently enlarge it or affect
the source/other previews; show the actual disk-limit/free-space failure.
Enforcement contract: before each operation the owned total is checked and DuckDB
spill is limited to the quota not used by other owned files; the total is checked
again before a projection is published and after every operation; a 200 ms watcher
interrupts active work. A transient overshoot is bounded by about 200 ms of writes
and fails the operation. Folding long, incompressible non-ASCII text needs about
three times the source size and therefore fails within this quota.

Keep validated cache files only for the currently selected file. Switching to
Text View stops CSV work, closes the helper and deletes its cache; only files up
to 2 MiB can switch, so re-importing on return is cheap. The small presentation
state (filters, global text, sort and position) is kept for switching back. On selection change/close, delete the owned
cache after the helper exits. Recover abandoned owned directories only on the
next Table View activation, not on application startup. No file watchers or
background polling; fingerprints are stale-data guards, not transactional
protection against hostile same-size/same-timestamp changes.

### QuickTable Appearance and Controls

Match [QuickTable's presentation](../src/main/python/fman/impl/ui/table.py): theme,
font, row height, alternating rows, gridless cells, selection colors, header
spacing, elision, icons, tooltips, filter popup and count footer. Reuse `TableHeader`,
`FilterEditor`, icon/delegate helpers and the minimal private presentation contract
where practical. If extraction is necessary, keep it small and behavior-preserving.
Do not instantiate `Table` with millions of rows, reuse its materialized mappings,
or raise QuickTable's row limits. Its public behavior remains unchanged.

- One toggle button switches **Text View / Table View** only for sources at or
  below 2 MiB. Hide it above that boundary; do not leave a disabled Text choice
  or introduce a RAW mode. Keep separate scroll, focus and view state within
  the same eligible selected file. Large CSV/TSV sources are Table-only within
  the selected preset cap, not truncated text previews.
- Click a column header to cycle ascending, descending, original order, exactly
  as QuickTable. Only one text sort column is active; no automatic numeric/date
  inference. Empty strings sort as strings, not missing numeric values.
- Header filter icons and `Alt+Down` open the same-style popup: **Fuzzy** and
  **Contains**, **Apply Filter**, **Clear Filter**, **Clear All Filters**,
  **Sort Ascending**, **Sort Descending**, and **Original Order**. Apply filters
  on different columns with AND, matching QuickTable. Reuse matching functions
  and validation. The private native query compiler must prove `LIKE` subsequence
  equivalence, including wildcard escaping and Unicode folding, against those
  existing predicates; do not reuse their Python execution loop on large files.
- The global Filter input uses case-insensitive Contains over all data columns;
  combine it with column filters using AND. `Ctrl+F` focuses it while Table View
  has focus. Debounce edits by 200 ms and cancel obsolete scans. Do not show an
  exact filtered count until its whole-file projection completes.
- Include resizable/hideable columns, a source-record gutter, bounded column
  autosizing from visible/sample rows, and optional frozen first data column.
  Never autosize by scanning the complete model. Use a windowed row model and
  bounded scrollbar mapping to avoid Qt integer/pixel limits at extreme counts.
- Allow cell/range/row/column selection without one Qt selection index per record.
  Copy cell/range or rows as quoted TSV, optionally including headers. Retrieve
  full values in the worker; cap output at 8 MiB and refuse larger copies with
  a clear reason. No silent clipboard truncation or automatic export feature.
- Provide next/previous Find in the settled view, optional column scope and case
  sensitivity, separate from filtering. It scans complete values with progress
  and cancellation; never retain all matches in RAM. Inspect the full selected
  cell, up to the field limit, in a lazily populated plain-text area.
- Elide table display cells to 512 characters; inspection/copy/filter/sort still
  use full values. Keep row numbers tied to source records after sort/filter.
  Table-specific shortcuts act only while the preview has focus; retain existing
  QuickView Escape/Tab/source-pane routing.

## Alternatives

- **Load a DataFrame or enlarge QuickTable:** rejected; decoded strings, copies,
  row mappings and sort keys can greatly exceed a 2 GB source's memory size.
- **Sparse CSV checkpoints only:** lean for browsing, but full filtering/sorting
  need external storage. One DuckDB store also gives positional pages and avoids
  reparsing the original CSV after every presentation change.
- **CSV/SQLite:** lower measured memory and no extra dependency, but slower
  import/native queries on the measured fixture. User selected DuckDB instead;
  preserve the comparison, not a second runtime implementation.
- **DuckDB:** selected for native parsing, import speed, compression and query
  execution. Use the three coupled file-size/memory presets and require bounded-input,
  packaging, full-file semantics and failure-path verification before delivery.
- **Polars:** another credible native engine, not measured or selected. No need
  to add a third benchmark/backend to implement the user's DuckDB decision.
- **Sort/filter only loaded rows:** rejected; results would depend on scrolling
  and omit unseen matches. No preview-only mode disguised as whole-file results.
- **Repair faulty CSV or wait for complete validation before showing anything:**
  reject silent repairs; complete upfront validation would delay useful opening.
  Provisional first rows plus size-aware fallback/error on discovery is explicit.
- **Offer prefix Text View for large CSV/TSV:** rejected by the user; the mode
  choice must mean full-file support, not access to only the first 2 MiB. A table
  failure on a large file is visible rather than disguised as successful text.
- **Independent cache control, free-form limits or adaptive budgets:** rejected;
  three file-size presets couple admission limits to reviewed memory profiles
  and keep resource choices predictable. No automatic escalation after failure.
- **Python matching on every filter revision:** rejected after Opus V1. Native
  Contains/subsequence queries over reusable folded values preserve semantics
  without repeated Python calls per cell. One-time non-ASCII folding still needs
  measurement. No new vectorization dependency or offline encoding extension.

## Runtime Effects

- Inactive QuickView, non-CSV previews and initial Text View: no CSV helper,
  DuckDB initialization, cache scan, source read, timer or recurring signal work.
- Active Table View: one helper process, sequential source read/write during
  validation, bounded UI page cache and at most one active/latest pending job.
  DuckDB import/search/sort may use substantial CPU and disk bandwidth; neither
  exact counting nor whole-file sorting is promised to be instantaneous.
  First use of a column may write a full folded cache; ASCII uses native lower,
  non-ASCII uses bounded Python preprocessing once. Warm query revisions run
  natively; folded caches increase disk and possibly import-to-query readiness.
- Initial cache budgets: 32 MiB decoded UI pages, 192/384/768 MiB DuckDB managed
  memory according to the selected preset (512 MiB default),
  4 MiB maximum result frame, one undelivered page and bounded parser input.
  Model `data()` only reads cached display values; cache misses schedule work.
  These component limits do not themselves prove a process-memory ceiling.
- The original 256 MiB combined-memory target is incompatible with the measured
  selected path. Proposed replacement target: below 768 MiB incremental combined
  application/helper peak at the default 2048 MB cap, subject to review and
  measurement of interpreter, strings, IPC copies, sorting and cleanup. Neither
  512 nor 768 MiB is a measured universal process cap; use a watchdog/failure path.
- Text View switching cancels query/import work and reaps the helper; completed
  cache files may remain idle for that selection. Close/replacement removes them.
  No source locks intentionally survive those transitions. UNC I/O can block;
  worker termination must leave the Qt UI responsive.
- The one global file-size preset persists under UserSettings. Other preview
  state is session-only, apart from disposable cache files under UserSettings.
  No per-path preferences/history or application-startup cache maintenance.
- Size checks run before DuckDB initialization. Rejected oversized files perform
  only required resolution/metadata checks, with no parser, text-prefix read or
  cache directory scan. Lower presets reduce the allowed engine-memory budget,
  not a guaranteed total-process ceiling or universal per-file latency bound.

## Tests

Required new unit target: `fman_unittest.impl.test_quick_view_csv`; Qt integration
target: `fman_integrationtest.test_qt.QuickViewCsvIT` in the existing Qt harness.
These targets are planned and do not exist yet.

1. Parser: delimiters, BOM/explicit encodings, CR/LF/CRLF, quoted multiline fields,
   escaped quotes, empty/header-only/single-column input, duplicate/empty headers,
   blank versus explicitly empty records, exact strings and all input limits.
   Assert empty unquoted and quoted fields are `''`, never NULL, in both first
   pages and full imports, including explicit `NULL` strings. Exercise UTF-8,
   both BOM-marked UTF-16 endians and explicit Latin-1; cp1252 currency/smart
   quotes must refuse Latin-1 C1 results, including in headers and late records.
   Assert small-file Text ANSI/warning consistency and large-file Table-only
   errors; no extension/network loading. Test byte/character/column limits at
   minus one/equal/plus one with ASCII, four-byte Unicode, quotes and multiline.
2. Faults: unterminated/bad quotes accepted or rejected according to the documented
   dialect, ragged rows, late decode errors, NUL/binary input and errors beyond
   the text limit. Assert Text fallback only at or below 2 MiB; larger failures
   show the Table-only error with cleared stale table/copy results, useful reason,
   no retry loop and successful explicit retry with corrected options.
3. Query parity: identical IDs/order to QuickTable's text sort and Fuzzy/Contains
   predicates for Unicode casefolding, ties, empty strings and multiple AND filters.
   Include matches and sort extrema only at EOF to reject cached-page-only results.
   Compare native Contains/Fuzzy/global queries against real QuickTable predicates
   for literal `%`, `_`, `\`, quotes, newlines, repeated characters, sharp S,
   final sigma, ligatures, combining marks and emoji. Verify native ASCII fold,
   exact non-ASCII fold staging, canceled staging cleanup and reuse without
   another Python cell scan on query changes. Test binary sort and stable ties.
4. DuckDB/process: positional random pages, bounded memory/disk/IPC, spill location,
   low disk/quota failure, Unicode/UNC/long paths, changed-file invalidation,
   source access errors, cancellation during import/filter/sort and cleanup.
   Assert the exact source-derived quota/floor/ceiling, quota-plus-reserve free
   space check, combined database/WAL/fold/spill/projection growth, concurrent
   windows, bounded interruption and errors naming required/available/cap bytes.
5. Qt: real header clicks/popups/Alt+Down, global filter, busy/revision/count states,
   cell copy, mode round trips, preserved positions, late-error fallback, keyboard
   routing and rapid file/window/owner changes. Assert model/widget thread affinity,
   no Qt-thread file I/O, no orphan helpers and no CSV work while inactive.
6. Regression: existing image/text/PDF QuickView and QuickTable/QuickBoard tests,
   plus a source and supplied portable-worker launch/exit smoke. New helper dispatch
   and PyInstaller collection must not create a second GUI or break PDF launch.
7. Manual: light/dark theme and 100%/150%/200% DPI; compare the actual QuickTable
   filter/sort UI, narrow opposite pane, huge/multiline cells, unavailable UNC,
   malformed files, cancellation and file rename/delete after switching/closing.
8. Presets/persistence: exactly 512/1024/2048 MB mapped to 192/384/768 MiB;
   default 2048, missing/invalid/boolean settings, restart round trip, all-window
   preference changes and cache/helper replacement without overlapping budgets.
   Never silently coerce settings or escalate after an allocation failure.
   Exercise the command-palette chooser, exactly three choices, current selection,
   Cancel, successful save notification and failed save without changing sessions.
   Choosing a preset must not initialize DuckDB or inspect the selected file.
9. Eligibility: use metadata fixtures for limit minus one / equal / plus one
   byte at each of 512,000,000 / 1,024,000,000 / 2,048,000,000 bytes and at
   `READ_LIMIT` 2,097,152 bytes. Assert mode visibility, default routing, no text
   loader call above `READ_LIMIT`, no DuckDB startup above the selected cap,
   size-aware detection/parse/query/resource fallback and rechecking after growth
   or replacement. Repeat while Text View is selected and after a preset change.
   Existing non-CSV text prefix behavior must remain unchanged.

Focused command once the targets exist; run it on both `windows` and `offscreen`:

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts')); sys.exit(subprocess.run([sys.executable, '-B', '-m', 'unittest', 'fman_unittest.impl.test_quick_view_csv', 'fman_integrationtest.test_qt.QuickViewCsvIT', '-q'], env=env, timeout=120).returncode)"
```

Add an opt-in `quickview.csv.large` workload to the existing QuickView performance
harness, not the ordinary correctness suite. Generate owned CSV and TSV fixtures
at each exact preset cap: 512,000,000 / 1,024,000,000 / 2,048,000,000 bytes,
using the corresponding engine budget and narrow/wide, less-compressible and
multiline/Unicode cases. Verify actual one-byte-over-cap rejection separately.
Measure per-column and global Contains plus per-column and all-column Fuzzy test
queries at each cap (the shipped global control remains Contains). Record first
fold construction separately from warm query revisions, ASCII-heavy and
non-ASCII-heavy folding throughput, query cancellation and the cost of the new
16 MiB line/64 MiB parser buffer settings at all engine budgets. Verify all result
IDs/order against the oracle outside timing. The old one-column ASCII Contains
measurements do not satisfy these gates or estimate global/Fuzzy cost.
Three runs per case; record hardware, storage, cache conditions, first painted rows, validation
time/throughput, filter/sort duration, peak combined memory, maximum disk use,
posted-input/paint latency and cancellation. Keep setup/verification outside timing;
never read private user data or claim cold-cache measurements without control.

```powershell
python src/performancetest/run.py suite --test quickview.csv.large --repeat 3 --results UserSettings/Performance/QuickView005
```

This command is a future opt-in gate, not an existing/passing workload. Large
fixtures, benchmarks, freeze/package and the full test suite are not run as part
of writing this plan. Source performance is not portable-artifact certification.

## Implementation Steps

1. Independently review the user-selected presets, mode policy and failure paths;
   resolve Opus V1/V2 feasibility first: native whole-file Contains/Fuzzy and
   bounded Unicode folding, strict supported encodings and C1 rejection. Validate
   all three exact caps with representative data, explicit byte limits, total
   disk containment and cancellation before UI changes. Review total-process
   ceilings; stop and revise if gates cannot be met.
2. Implement the private native query compiler, bounded fold-cache preparation
   and parser/spool/query worker with focused tests. Use unchanged QuickTable
   predicates as the test oracle. Verify full-file results and complete-failure
   cleanup without importing `fman` or Qt in the helper.
3. Add lazy source/frozen helper dispatch/controller, bounded result transport,
   generation guards and owned cache lifecycle. Add the persisted preset mapping
   and metadata-first eligibility checks; test boundaries and process failures.
4. Reuse/extract the minimum QuickTable presentation helpers with existing tests
   unchanged, then add the windowed CSV model and matching filter/sort controls.
5. Wire size-aware routing and toggle visibility, strict fallback/error states,
   copy/Find/inspection, preset chooser and retained session state; validate on
   both Qt platforms.
6. Complete focused regression/source/portable smokes, opt-in performance and
   manual gates. Update README/Core README, user docs and CHANGELOG only when
   application functionality is implemented. Update `docs/configuration.md` with
   the chooser, JSON key, all presets/default and lower-memory/lower-latency
   profile caveats; document supported encodings, text cutoff and large-file
   error behavior. Record measured results and gaps.

## Acceptance Criteria

- Valid CSV/TSV within the selected cap defaults to Table View. Only sources at
  or below 2,097,152 bytes offer the Text View/Table View toggle and restore
  per-view state for the same unchanged file. Larger sources never invoke Text
  View, including on late parse/resource errors; over-cap sources show a reason
  without starting DuckDB or reading a text prefix.
- Exactly three persisted file-size choices, 512/1024/2048 MB, derive engine
  budgets of 192/384/768 MiB. The default is 2048 MB / 768 MiB. Boundary values,
  invalid settings, changes across windows and restart persistence are tested;
  no independent cache override or automatic memory/size escalation exists.
- Every discovered decoding/structural parse fault, including after provisional
  display, clears invalid rows and uses Text View only if size permits; otherwise
  show the Table-only error and retry/parsing controls. No silent row repair,
  retry loops or assertion of complete validity before EOF.
- Header filtering/sorting looks and behaves like QuickTable's text-column UI;
  global filtering and every settled projection cover the whole validated file.
  Native Contains/Fuzzy and binary sort pass the real Python-predicate oracle;
  no per-revision Python cell scan or Python sort comparator. Initial Unicode
  folding, warm queries and cancellation are measured at every preset cap.
- Table decoding is limited to the documented offline UTF-8/UTF-16/Latin-1 set;
  Latin-1 C1 controls fail explicitly, empty fields remain strings, and strict
  first-page/full-import settings agree. Exact character/encoded-byte boundaries
  and 16 MiB line/64 MiB buffer behavior are verified in the shipped engine.
- Representative local-SSD files at each of the three supported caps paint
  first populated rows within 1 second, including existing selection
  debounce. Review/approve the proposed 768 MiB incremental combined-memory target
  at the default 2048 MB preset and source-derived total cache quota before
  implementation; record separate peaks for lower presets. The quota includes
  fold caches/projections and free-space checks, not just DuckDB spill files.
  Larger sources show
  the size-limit error, not Text View. Size checks do not replace runtime bounds.
  These are proposed gates, not achieved application numbers.
- Warm cached navigation has p95 posted-input-to-paint below 100 ms; ordinary
  cooperative cancellation acknowledges within 250 ms. A blocked helper is
  terminated/reaped within 2 seconds while Qt remains responsive. Record maximum
  stalls too; do not hide violations in averages or claim those deadlines for UNC
  read completion itself. Measure parsing/query completion without inventing a
  universal sort-time target across different row shapes and storage devices.
- No work or unbounded memory growth in the inactive/Text View paths; no leaked
  process, source lock, stale result or cache after ordinary close/replacement.
- Focused unit/Qt/regression gates and measured large-file/source/portable/manual
  gates are recorded; no unsupported claim that planning checks validate runtime.

## Engine Measurements - 2026-10-26

### Protocol and Limits

Executed the isolated, opt-in
[engine benchmark](../src/performancetest/python/fman_performancetest/quickview_csv_engines.py),
not QuickView application code. Windows 11 build 26300, AMD Ryzen 9 9950X,
Samsung SSD 850 EVO SATA, conda-forge Python 3.14.7, SQLite 3.53.4 and DuckDB 1.5.6.
The user installed `python-duckdb` for this comparison; no installation was
performed by the benchmark and no delivered backend has changed.

- Exact decimal sizes: 100,000,000, 500,000,000 and 2,000,000,000 bytes, not MiB/GiB.
  Eight string columns, approximately 256 encoded bytes per record, UTF-8 Unicode,
  escaped quotes and embedded newlines. Counts: 390,624 / 1,953,124 / 7,812,499.
  Repeated prefixes/padding make this fixture compressible; it is not a claim
  about arbitrary real-world CSVs or wide/tiny-record worst cases.
- Three fresh child processes per engine/size, alternating engine order. Tables
  below report medians. Both engines use one query thread. SQLite uses a 16 MiB
  page cache and no mmap; final DuckDB measurements use a 512 MiB engine budget,
  with native `WITH ORDINALITY` source IDs and physical insertion order relaxed.
- All columns remain strings. Verify complete row counts, identifier checksums,
  every source-record ordinal, exact first-page values and filter/sort page order.
  Both engines parse strictly and materialize a disposable on-disk database.
- First 200 measures engine initialization plus fetching strings; it excludes
  Python process launch, Qt/IPC delivery, selection debounce, dialect inference
  and first paint. It is not measured time until a QuickView table is visible.
- Fully Ready includes initial page and complete import/checkpoint, not subsequent
  filter/sort time. Import verification scans are outside reported phase times.
- Filter materializes all matching source IDs for one ASCII-column Contains
  predicate (5% match rate). Sort materializes all source IDs by a unique,
  normalized ASCII key in reverse source order, not just a top-200 query.
  These are not full QuickTable Fuzzy/Unicode casefold performance measurements.
- Source generation and verification are excluded. OS cache is uncontrolled;
  repeated runs and post-import queries benefit from caching. No cold-cache,
  disk-flush durability, UNC, packaged-launch or GUI responsiveness claim.

### Measured Times

| CSV MB | Engine     | First 200 ms | Fully Ready s | Filter s | Full Sort s |
| ------ | ---------- | ------------ | ------------- | -------- | ----------- |
| 100    | CSV/SQLite | 7.72         | 1.335         | 0.062    | 0.185       |
| 100    | DuckDB     | 53.47        | 0.613         | 0.005    | 0.044       |
| 500    | CSV/SQLite | 10.10        | 7.000         | 0.299    | 1.036       |
| 500    | DuckDB     | 57.16        | 2.813         | 0.020    | 0.204       |
| 2000   | CSV/SQLite | 10.25        | 29.059        | 1.293    | 4.485       |
| 2000   | DuckDB     | 58.09        | 10.707        | 0.051    | 0.771       |

### Memory, Disk and Failed Configurations

- At 2,000 MB, median child peak working set was 68.85 MiB for SQLite and
  599.97 MiB for DuckDB; maximum observed peaks were 69.26 and 600.20 MiB.
  Median peak private commit was 66.31 versus 631.88 MiB. These include each
  engine process but exclude the parent and any QuickView/Qt view cache.
- Median sampled output-directory disk peak was 2,327.04 MiB for SQLite and
  174.78 MiB for DuckDB, excluding the shared source file. Sampling is every
  100 ms; brief/hidden spill files can be missed. These are observed directory
  sizes, not a proven hard disk ceiling. DuckDB's compression helps this fixture.
- DuckDB's 128 MiB setting passed 100/500 MB but failed the 2,000 MB import with
  an out-of-memory error. Disabling insertion-order buffering and using native
  ordinals did not resolve it. A separate 256 MiB setting also failed import.
  The successful 512 MiB setting is explicitly a different resource experiment,
  not evidence that DuckDB meets the plan's 256 MiB combined-memory target.
- SQLite completed the large fixture without that failure. This does not prove
  its full UI/cache integration or pathological-file memory bounds.

### Evidence and Reproduction

Raw JSON records are retained under
`UserSettings/Performance/QuickView005/Engines`. Final protocol is
`quickview-csv-engines-v3`; 18 verified samples comprise six groups of three:

- `20261026-105100-9f73d29b`: final 100/500 MB results.
- `20261026-105229-f9dccfd3`: final 2,000 MB results.
- Failed profiles retained separately: `20261026-104533-938ed48b` (128 MiB,
  original insertion order), `20261026-104723-2d31f118` (128 MiB, native ordinals),
  `20261026-104848-0943e5cc` (256 MiB). Do not fold partial runs into final medians.

Initial comparison source SHA-256 (before capacity/latency additions):
`328565E6BDA64E391C192BF1D037C7DE1BA0366613D9A29D43F460252D495A0A`.
The source contains no application changes and is outside correctness discovery.
Owned source fixtures/databases were removed after each run; JSON evidence remains.

Commands executed in the selected RoyiFileManager environment (`python`):

```powershell
python -B src/performancetest/python/fman_performancetest/quickview_csv_engines.py --sizes 1 --repeat 1 --duckdb-memory 256
python -B src/performancetest/python/fman_performancetest/quickview_csv_engines.py --sizes 100 500 --repeat 3 --duckdb-memory 512
python -B src/performancetest/python/fman_performancetest/quickview_csv_engines.py --sizes 2000 --repeat 3 --duckdb-memory 512
```

Smoke checks and all final samples passed their correctness assertions. Lower
memory DuckDB failures above are retained outcomes, not passing gates. No full
application suite, freeze, package, large TSV run or UI implementation was run.

### Decision Implications

DuckDB was approximately 2.7 times faster to full readiness at 2,000 MB and much
faster for this native filter/sort workload, at substantially higher memory use.
The initial recommendation was to retain CSV/SQLite if the 256 MiB total-memory
target was binding; the later user selection below supersedes that recommendation.
DuckDB is a credible speed-oriented alternative only after approving
a larger budget or demonstrating another bounded import path. Do not claim that
these failures prove every DuckDB ingestion strategy needs 600 MiB, or ship two
backends as a workaround without a separate design decision.

The earlier 40-200 second large-file estimate was conservative: the measured
fixture reached full readiness in about 29 seconds with SQLite or 11 seconds with
DuckDB. Neither number is time to first visible rows, a general performance
guarantee, or approval of application integration. Independent review and the
remaining acceptance gates still apply.

## Selected DuckDB Path, Capacity and Latency - 2026-10-26

The user selected DuckDB after the initial comparison. The current design above
now uses one DuckDB parser/store, not SQLite plus an optional DuckDB path. The
later user-selected presets and mode policy below supersede the initial 2 GB
recommendation. Independent review of integration and resource targets is pending.

### Capacity Is Not a Universal File-Size Formula

Additional single-run coarse probes used the same eight-column, compressible
256-byte-record UTF-8 CSV shape, one thread and native source ordinals. A pass
requires import, count/checksum/ordinal verification, filtering and full sorting.
Failure points below ran out of memory during import, not during first-page read.

| Engine Budget MiB | Largest Verified CSV MB | Failed CSV MB | Peak Process MiB at Largest Pass |
| ----------------- | ----------------------- | ------------- | -------------------------------- |
| 128               | 500                     | 750, 1000     | 186                              |
| 256               | 1500                    | 2000          | 327                              |
| 512               | 4000                    | Not reached   | 612                              |

These are observations, not supported maxima. In particular, 4 GB passed at 512
MiB; no upper failure bound was established for that setting. Row width/count,
distinct strings, compression, dialect, encoding and operation change memory
needs. A fixed source-byte limit alone cannot guarantee success. The initial
512 MiB / 2 GB recommendation has been superseded by the user's three presets
below; failures use the size-aware policy, not unconditional Text View fallback.
The 4 GB measurement is not production certification.

Capacity records under `UserSettings/Performance/QuickView005/Engines`:

- `20261026-110623-0d5dee3b`: 128 MiB; 500 passed, 750/1000 failed.
- `20261026-110720-92bd034a`: 256 MiB; 1000/1250/1500 passed. The previous
  `20261026-104848-0943e5cc` record retains the 2000 MB failure.
- `20261026-110841-32ff6393`: 512 MiB; 2500/3000 passed.
- `20261026-111032-627a5a87`: 512 MiB; 4000 passed, fully ready in 20.95 seconds.

### Text View and the Crossover

The existing text loader reads at most 2,097,152 bytes, normalizes newlines and
marks larger files as truncated. It can preview a prefix of a 100 MB, 500 MB or
2 GB text file without reading the rest. It cannot browse/search/copy the full
file through today's Text View. Thus 2 MiB is the full-content coverage boundary,
not the maximum source size Text View can open. There is no measured file-size
crossover at which Text becomes a full-file alternative to Table View.
The new CSV/TSV design deliberately restricts mode choice to that full-content
boundary, even though the underlying loader can still preview larger non-CSV
sources. The measurements below remain prefix-loader measurements, not supported
large-file Text View behavior in the proposed CSV/TSV feature.

Measured the actual loader, not a replacement decoder, in three fresh child
processes per source size with three loader calls per child. Median per-child
medians were 3.99 ms at 100 MB, 3.96 ms at 500 MB and 4.04 ms at 2000 MB; every
result contained exactly 2 MiB and was marked truncated. This measures loading
only, excluding Qt text layout/paint, and ran after reads that warmed the prefix.

### First-Read Improvements

Latency record: `20261026-111309-4011a428`. Three fresh processes per source size;
ten warm default-buffer and ten reduced-buffer queries per child. Repeated
queries reused one connection and verified the exact 200 returned rows.

- Cold total medians: 58.84 / 56.48 / 53.74 ms at 100 / 500 / 2000 MB. Module
  import accounts for roughly 36-39 ms and connection setup about 8 ms. These
  timings exclude helper process launch and Qt delivery/layout/paint.
- Reused-connection median-of-medians: 7.44 / 6.94 / 7.33 ms. Reuse the lazy helper
  and bootstrap connection across Table-to-Table file changes, with safe detach/
  attach and generation rejection. File attachment/reset costs are not measured
  by repeatedly querying the same file and must be included in UI acceptance.
- A warm 4 MiB buffer plus `max_line_size=1048576` yielded 2.57 / 2.39 / 2.49 ms.
  This experiment imposes a smaller line limit, so it is not an unconditional
  production default. A bounded first-page fast path may retry with the normal
  supported limits if a record is too large; it must not reject or silently
  truncate otherwise supported data. Full import keeps its reviewed limits.
- An initial 2000 MB query stalled at 364 ms; capacity probes also saw 0.6-0.85
  second first reads. Warm medians do not promise cold-I/O deadlines. Retain the
  unchanged 100 ms selection debounce and measure the complete UI path.
- No DuckDB import/helper prewarming at application startup or in Text View.
  Switching to Text View/closing still stops work and reaps the helper; the next
  Table activation may pay the cold setup cost again.

Extended benchmark source SHA-256:
`8C5DC6FD765B3D5C894065AEE7EEDE7311ED72778E1339B0F9368EC9E06DC1DC`.
New failed probes are retained as `completed_with_failures`, not successful gates.
Commands (selected project environment, from repository root):

```powershell
$bench = 'src/performancetest/python/fman_performancetest/quickview_csv_engines.py'
python -B $bench --sizes 1 --repeat 1 --engines duckdb --duckdb-memory 128 --continue-on-error
python -B $bench --sizes 500 750 1000 --repeat 1 --engines duckdb --duckdb-memory 128 --continue-on-error
python -B $bench --sizes 1000 1250 1500 --repeat 1 --engines duckdb --duckdb-memory 256 --continue-on-error
python -B $bench --sizes 2500 3000 --repeat 1 --engines duckdb --duckdb-memory 512 --continue-on-error
python -B $bench --sizes 4000 --repeat 1 --engines duckdb --duckdb-memory 512 --continue-on-error
python -B $bench --sizes 1 --repeat 1 --engines duckdb --duckdb-memory 512 --latency
python -B $bench --sizes 100 500 2000 --repeat 3 --engines duckdb --duckdb-memory 512 --latency
```

No application implementation, helper-reuse UI integration, modified text loader,
larger-record buffer certification or dependency installation occurred in this
follow-up. The large TSV, real-world/less-compressible, packaging and manual gates
remain open; none is established by these targeted measurements.

### User-Selected Policy for Review - 2026-10-26

- Three Table View source-size presets only: 512 MB with 128 MiB engine memory,
  1024 MB with 256 MiB, and default 2048 MB with 512 MiB. These deliberately
  leave margin relative to observed coarse failures; they are not certified
  capacities for more complex input. Exact preset-boundary workloads remain open.
- The 2 MiB full-file text limit controls mode eligibility. Above it, only Table
  View is available within the chosen cap. Over-cap or invalid large files show
  an inline reason; no prefix Text View fallback or automatic resource increase.
- Documentation presents lower presets as lower-memory/lower-latency profiles
  while stating that latency depends on the workload and smaller budgets can
  increase spill/query time. This was not established by the warm-read tests.
- Ready for independent review. Presets and mode rules are user decisions;
  total-process memory containment, native parser limits/strictness, total disk
  quota enforcement, packaged helper launch and integrated performance remain
  review/implementation gates, not approved or passing application behavior.

## Response to Opus 5.5 Review - 2026-10-26

- **V1:** Replaced per-revision Python matching with native parameterized
  Contains/escaped-LIKE subsequence queries, reusable native-ASCII/bounded-Python
  Unicode fold caches and binary text sorting. No extra vectorization dependency.
  Added parity and all-preset global/column/Fuzzy/folding performance gates.
  The estimated minute per edit in the review is an extrapolation, not a measured
  result; the old native ASCII benchmark does not validate the revised design.
  V1 remains a feasibility/approval gate until the new path is measured.
- **V2:** Selected strict offline UTF-8, BOM-marked UTF-16 and explicit Latin-1
  with C1-control rejection, rather than bundling the encodings extension.
  Preserved existing Text decoder behavior and required consistent refusal/
  encoding-warning presentation. ANSI/Latin-1 success is not assumed equivalent.
- **V3:** Named `allow_quoted_nulls=false` and per-column `force_not_null` on
  every read/import, with quoted/unquoted empty-string regression requirements.
- **V4:** Replaced the flat disk allowance with twice-source-size quota, 16 MiB
  metadata floor and 8 GiB ceiling, including fold/projection/spill/WAL data.
  Added free-space reserve, explicit diagnostics and total-growth enforcement gate.
- **V5:** Specified **Set QuickView table limit**, an existing-style three-choice
  QuickSearch command; persist the existing proposed key in Core Settings and
  document the chooser/key in the configuration guide when implemented.
- **V6:** Consolidated status and specified 16 MiB `max_line_size` / 64 MiB
  `buffer_size`, with separate character validation and encoding/multiline probes.

Design revision only. Opus's review and all prior reviewer records are retained
verbatim below. No application/benchmark code, package installation or new
large-file experiment is part of this response. Exhaustive native-query parity, exact-cap
performance, total disk enforcement and packaged encoding/parser behavior remain
unvalidated; the design awaits re-review, not an approval claim.

### Focused Validation

- Document checks passed: V1-V6 dispositions, one status, exact preset/mode table
  preservation, all required sections/links/fences, four aligned tables and
  `git diff --no-index --check -- NUL Plan/QuickView005.md`. Compared the full
  original Opus review, previous reviewer records and historical measurements
  against a pre-edit in-memory baseline; all were retained verbatim.
- Used `pylanceRunCodeSnippet` in the existing selected project interpreter with
  DuckDB 1.5.6 and an in-memory database, no input files. Compared native Contains
  and escaped-LIKE Fuzzy with actual `compile_filter` predicates over 24 strings
  and 23 queries in each mode: 1,104 cell/query comparisons passed. Cases include
  literal `%`, `_`, backslash, quotes, CR/LF, query trimming, repeated characters,
  sharp S, sigma, ligatures, combining marks and emoji. Native ASCII plus Python
  non-ASCII folding and binary folded-string sort agreed with Python exactly
  on this sample. Parser byte-limit and default quota arithmetic also passed.
- This is a small semantic probe, not the production compiler/fold cache, global
  composition test, CSV/encoding/empty-field test, performance workload, Qt test
  or packaged-engine certification. Those required gates remain open.

## Reviewers

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed strict Text View fallback, whole-file disk-backed filtering
  and sorting, QuickTable presentation reuse and bounded-memory 2 GiB gates.
  Independent review, backend feasibility and implementation remain pending.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Compared CSV/SQLite and DuckDB with 18 verified final samples and
  retained failed 128/256 MiB DuckDB profiles. DuckDB is faster on this fixture
  but the tested successful path exceeds the proposed memory target. No backend
  switch or application implementation is approved by these measurements.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Integrated the user's DuckDB selection, coarse 128/256/512 MiB capacity
  probes, actual Text View prefix-loader measurements and cold/warm first-read
  phases. Proposed a conservative 2 GB initial cap and revised memory target;
  helper reuse and reduced-buffer correctness remain application validation gates.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Prepared the design for independent review with the user's three
  coupled file-size/memory presets, 2048 MB / 512 MiB default, persisted global
  setting, full-file Text eligibility and size-aware fallback/error states.
  Added exact-boundary, persistence and all-preset performance gates. No
  application implementation or independent approval is claimed.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Revisions required. The DuckDB choice, the size presets, the strict
  failure policy and the helper-process ownership are sound. V1 is blocking:
  the filter design runs Python predicates over every cell, and the benchmark
  never measured that. V2 is P2 and V3-V6 are smaller. No code changed or run.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Revised the design in response to Opus V1-V6, preserving the review
  and preset/mode decisions. Native matching with reusable Unicode fold caches,
  explicit encoding/empty-field policy, source-derived disk quota, preset chooser
  and parser byte limits now have focused acceptance gates. Feasibility,
  performance and independent re-review remain pending; no implementation.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implementation review requires changes: IR1-IR6 reproduced below,
  including cancellation poisoning fold caches and allocations preceding byte
  limits. Existing CSV tests pass on both Qt platforms but miss these cases.
  No application fixes authored; implementation approval is withheld.

## Design Review (2026_10_26, Opus)

Checked against `compile_filter` in [table_filters.py](../src/main/python/fman/impl/ui/table_filters.py),
`match_positions` in [ui/\_\_init\_\_.py](../src/main/python/fman/impl/ui/__init__.py),
`contains_chars` in [matchers.py](../src/main/python/fman/impl/ui/matchers.py),
`decode_text`/`READ_LIMIT` in [quick_view_text.py](../src/main/python/fman/impl/quick_view_text.py)
and [environment.yml](../environment.yml), which already lists `python-duckdb`.

- **V1 [P1] Whole-file filtering must run natively, not as Python predicates.**
  - **The gap:** the design scans every row in the helper with QuickTable's
    Python predicates. The 0.051 s filter in the benchmark was a native DuckDB
    `contains` on one ASCII column. At the 2,000 MB fixture (7.8 M rows, 8
    columns), a global filter makes about 62 M Python calls per revision. At
    roughly 1 µs per call that is about a minute per edit.
  - **Native equivalents exist:**
    - **Contains** is `casefold(query) in casefold(cell)`.
    - **Fuzzy** (`contains_chars` through `match_positions`) is a subsequence
      test on casefolded text, so it equals
      `folded LIKE '%a%b%c%' ESCAPE '\'` with `%`, `_` and `\` escaped.
    - DuckDB compares VARCHAR in binary order, and UTF-8 byte order equals code
      point order. A folded key therefore also sorts exactly like Python `str`.
  - **What remains:** only the fold. DuckDB `lower()` differs from Python
    `casefold()` for some non-ASCII characters (`ß` to `ss`, final sigma,
    ligatures). Keep exact parity by applying `lower()` to ASCII values
    (`strlen(x) = length(x)`) and a vectorized Python UDF to the non-ASCII rest.
    Store or cache the folded values per column, as the plan already proposes
    for sort keys.
  - **Measure:** global and per-column Fuzzy and Contains, plus non-ASCII
    folding, at each preset cap before approval. Keep the Python predicates only
    as the parity oracle in tests.
- **V2 [P2] Encodings: Table and Text can disagree, and Latin-1 can hide
  mis-decoding.**
  - **Text View:** `decode_text` falls back to the Windows ANSI code page (for
    example cp1252), or to replacement characters with a warning.
  - **DuckDB without its `encodings` extension:** it decodes only UTF-8,
    UTF-16 and Latin-1, and the plan blocks extension downloads.
  - **Consequences:**
    - An Excel "ANSI" CSV under 2 MiB opens correctly as text but fails as a
      table.
    - Worse, forcing Latin-1 on cp1252 bytes succeeds silently: `€` becomes
      U+0080. That breaks "never silently display repaired data".
  - **Decide:** either reject Latin-1 decoding that produces C1 control
    characters (U+0080-U+009F), or bundle the `encodings` extension offline. In
    both cases, list the supported encodings and make Text View's warning and
    Table View's refusal consistent for the same file.
- **V3 [P3] Empty fields.** With all-VARCHAR columns, an empty unquoted field
  becomes NULL, and with the default `allow_quoted_nulls=true` so does a quoted
  `""`. Name the settings: `allow_quoted_nulls=false`, plus a NULL string that
  cannot occur or `force_not_null` on every detected column. Add a regression
  test that both kinds of empty field come back as `''`.
- **V4 [P3] Disk use for a portable app.** An 8 GiB allowance per window,
  for two windows, all under `UserSettings`, is a lot for a portable install on
  a small drive. Derive the cap from the source size (for example 2x the source,
  at most 8 GiB). Check free space before import, and report the cap in the
  error message.
- **V5 [P3] Where is the preset chosen?** The plan persists
  `quickview_table_max_file_mb` but does not say which UI changes it: a
  command, a Settings entry or JSON only. State it and document it in
  `docs/configuration.md`.
- **V6 [P3] Minor.**
  - The header has two `Status:` lines; keep one.
  - Planned limits are stated in characters while DuckDB's `max_line_size` is
    in bytes. A 4,194,304-character record can reach 16 MiB in UTF-8, so state
    the byte values (`max_line_size`, `buffer_size`) explicitly.

Verified: QuickTable's text filters are pure predicates (`casefold` substring,
and subsequence `contains_chars`); `READ_LIMIT` is 2,097,152 bytes; the text
loader falls back to the locale ANSI code page; `python-duckdb` is in
`environment.yml`. No code, benchmark or test was changed or run.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Approved with revisions, applied in the design text above. V1-V6 are
  resolved. Probes of the bundled DuckDB 1.5.6 found W1-W6; W1 changes a stated
  limit setting, W2 an encoding claim and W3 the fold mechanism. The user
  authorized implementation in the same request.

## Design Re-review (2026_10_26, Opus)

Probed DuckDB 1.5.6 in the project environment on disposable temporary files.

- **W1 [P1] The 64 MiB parser buffer does not fit the 128 MiB preset.** A 100 MB
  import at `memory_limit='128MiB'` failed: "could not allocate block of size
  64.0 MiB". A 32 MiB buffer (twice the 16 MiB line limit) passed at all presets
  and still read a 15 MiB record. Revised to `buffer_size=33554432`; the
  advertised line, field and record limits are unchanged.
- **W2 [P2] UTF-16 big-endian is silently empty.** With a `FE FF` BOM and
  `encoding='utf-16'`, DuckDB returned zero rows without an error. It also
  decoded a BOM-less UTF-8 file as UTF-16 without an error. Table View now
  accepts UTF-16 only with a little-endian BOM and refuses big-endian.
- **W3 [P2] A DuckDB Python UDF needs NumPy**, which the build excludes. The
  fold cache streams non-ASCII folded values to a staging CSV in the owned cache
  and applies them with one native `UPDATE ... FROM read_csv(...)`.
- **W4 [P2] The sniffer can pick a delimiter that is not in the file.** For a
  ragged comma file, `sniff_csv` returned `|`, which read every line as one
  column without an error. That is a silent misreading. Auto-detection is
  now rejected when the detected delimiter is absent from the first line but
  another candidate is present.
- **W5 [P2] A short header is not validated.** With `header=true`, DuckDB skips
  the header line, so a header with fewer fields than the data passed
  unnoticed when the column count was auto-detected. The column count now
  comes from a strict Python `csv` parse of the first record, so every later
  record is checked against it.
- **W6 [P3] Confirmed behaviors.**
  - Latin-1 refuses bytes 0x80-0x9F natively ("File is not latin-1 encoded").
  - `allowed_paths` / `allowed_directories` must be set after connecting,
    followed by `enable_external_access=false`; reading another file is then
    refused.
  - NUL bytes inside fields are accepted by DuckDB, so an explicit post-import
    check rejects them.
  - `WITH ORDINALITY` numbers data records only, skipping the header and blank
    lines.
  - `allow_quoted_nulls=false` with `force_not_null` keeps both `""` and empty
    fields as `''`.

## Implementer

### 2026_10_26 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented Table View with the W1-W5 revisions.
  - **Helper:** `_quick_view_csv_worker.py` is a Qt-free DuckDB helper with a
    strict import, native Contains/Fuzzy/global filters and sort over fold
    caches, paging, copy, cell and Find. It interrupts by operation ID,
    enforces the cache quota, and recovers abandoned cache folders.
  - **Controller:** `CsvController` runs one helper per window, with one
    active operation and the latest pending requests. Generation and revision
    guards reject stale replies; cancellation has a 2 s deadline.
  - **View:** `CsvPreview` reuses QuickTable's header, delegate and filter
    editor. Rows come from a windowed, page-cached model. It adds Find,
    Inspect, copy, hidden and frozen columns, and parsing options with Retry.
  - **Session:** routing, size-aware Text View fallback, and the toggle with
    retained state.
  - **Command:** **Set QuickView table limit**, saved in `Core Settings.json`.
  - **Delivery:** PyInstaller collection and a packaged helper smoke in
    `build.py package`.
  - **Docs:** user, configuration and Core README pages, plus the CHANGELOG.

### 2026_10_26 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Fixed implementation-review findings IR1-IR6 (see Response to
  Implementation Review). Added 7 regression tests; the CSV unit and Qt tests
  pass (23 on `windows` and 23 on `offscreen`).

## Validation Results

- **Unit:** `fman_unittest.impl.test_quick_view_csv` has 11 engine tests.
  - Strings, quotes, newlines and empty fields.
  - Faults: ragged records, extra fields, unterminated quotes, NUL bytes and
    invalid UTF-8.
  - Encodings: UTF-8 BOM, UTF-16 LE/BE, Latin-1 including C1 bytes, and
    cp1252 quotes.
  - Dialects, headers and duplicate labels; column, size and quota limits.
  - Display elision versus full copy/cell values.
  - Native Contains/Fuzzy/global/sort parity against the real
    `compile_filter` predicates. The cases include `ß`, sigma, ligatures,
    combining marks, emoji, `%`, `_`, `\` and quotes, ties in both directions,
    and empty-query rejection.
  - Page, copy, cell and Find over projections; interruption; and cache
    release.
- **Qt:** `fman_integrationtest.test_qt.QuickViewCsvIT` has 5 tests with the real
  source helper.
  - Header-click sort without selecting the column; column and global
    filters; Ctrl+Shift+C copy.
  - Text View round trip that keeps filters and sort, and retires the helper.
  - Keyboard: Ctrl+F, F3 Find, Inspect of a 700-character cell, Alt+Down,
    forwarded F8, Tab/Escape, Ctrl+End and the record-number gutter.
  - A small ragged file falls back to Text View, the toggle back does not
    retry, and Retry with explicit options fails again.
  - A large faulty file stays table-only with Retry; over-cap refusal starts
    no helper.
  - The preset command saves, notifies and cancels.
  - Main-thread page delivery and cache cleanup after exit.
- **Focused gate:** passed with 285 tests on `windows` and 285 on `offscreen`
  (54 s and 53 s; the only stderr noise is the existing `libpng error: Read
  Error`). The command was the focused command in Tests, extended with
  `fman_unittest.test_quick_view`, `test_quick_view_images`,
  `test_quick_view_pdf`, `test_quick_view_text`, `test_app_name`,
  `test_portable.PluginApiCompatibilityTest`, `core.tests.commands.test___init__`
  and the `QuickViewIT`, `QuickViewPdfIT`, `QuickViewTextIT`, `QuickViewImagesIT`
  and `TableIT` classes.
- **Source helper smoke:** `src/main/python/fman/main.py --quick-view-csv-worker`
  ran the framed protocol: ready, preview, imported, a 1-row projection for
  `STRASSE` matching `Straße`, and the page. Its cache folder was removed on close.
- **Indicative engine measurements:** local SATA SSD, warm cache, disposable
  100 MB, 1,180,191-record, 8-column mixed-Unicode CSV.

  | Engine Memory | First Rows | Validated | Global Fold (Once) | Warm Global | Fuzzy | Sort | Mid Page | Process Peak | Cache Peak |
  | ------------: | ---------: | --------: | -----------------: | ----------: | ----: | ---: | -------: | -----------: | ---------: |
  | 128 MiB       | 0.078 s    | 1.66 s    | 2.78 s             | 0.10 s      | 0.09 s | 0.26 s | 48 ms  | 174 MiB      | 60 MiB     |
  | 256 MiB       | 0.037 s    | 1.62 s    | 2.51 s             | 0.10 s      | 0.09 s | 0.22 s | 41 ms  | 191 MiB      | 58 MiB     |
  | 512 MiB       | 0.029 s    | 1.54 s    | 2.57 s             | 0.10 s      | 0.09 s | 0.21 s | 41 ms  | 206 MiB      | 57 MiB     |

  These are engine-only numbers: no UI or IPC, and the cache sampled every
  100 ms. They are not the exact-cap acceptance gate.
- **Docs:** `python -B -m mkdocs build --strict` passed.
- **Implementation-review fixes:** `fman_unittest.impl.test_quick_view_csv` (18,
  including 5 new engine regressions and 2 controller/model regressions) and
  `fman_integrationtest.test_qt.QuickViewCsvIT` (5) passed on `windows` and
  `offscreen`, with the command from the implementation review. The Python heap
  regression uses `tracemalloc` and is no process-memory claim.
- **Regular performance workload `csv.load`:** 64,000,000-byte, 32-column CSV,
  three fresh processes, default preset. Median first painted rows 298 ms, painted
  full import 916 ms, largest UI heartbeat gap 24 ms, helper peak working set
  170 MiB. It does not replace the open exact-cap `quickview.csv.large` gate.
- **Not run or open:**
  - The catalogued `quickview.csv.large` workload at the exact 512/1,024/2,048 MB
    caps, including TSV, wide and less-compressible fixtures, and UI
    input-to-paint.
  - `build.py freeze`/`package`, so the packaged helper smoke is untested
    against a frozen artifact.
  - Manual light/dark and 100/150/200% DPI checks, and UNC sources.
  - The full test suite.
- **Known limits:**
  - Selection is one rectangle.
  - Above 10,000,000 rows the model shows a sliding 10 M-row window, so a
    selection does not survive a window shift.
  - Find matches literal text, per row and then per column.

  ## Implementation Review - 2026-10-26

  Verdict: Changes required. Findings are reproduced on the existing project
  interpreter with DuckDB 1.5.6. This review does not modify application code or
  supersede the existing implementation/validation records above.

  ### Findings

  1. **IR1 [P1]: Canceled fold preparation permanently breaks later queries.**
    [prepare_folds](../src/main/python/_quick_view_csv_worker.py#L462) commits
    `ALTER TABLE ... ADD COLUMN fN` before folding finishes; cancellation does
    not remove that column or mark it complete. Reproduced cancellation after
    column creation, then a new query: `Catalog Error: Column with name f1 already
    exists!`. Typing a new filter during initial preparation can therefore break
    filtering/sorting on that column until reopening the file. Stage/rollback
    incomplete folds and add a cancel-then-retry regression, not just a cancel test.
  2. **IR2 [P1]: Byte limits are applied after full-value Python allocations.**
    [initial preview](../src/main/python/_quick_view_csv_worker.py#L369) fetches
    200 complete rows; [fold preparation](../src/main/python/_quick_view_csv_worker.py#L482)
    and [row retrieval](../src/main/python/_quick_view_csv_worker.py#L577) fetch
    1024 rows without a byte bound. `page()` additionally materializes the whole
    requested page before elision/frame checks; copy checks its 8 MiB output cap
    only after a full batch has been fetched. With 35 valid 600,000-character
    fields, a page displaying 17,980 characters peaked at 20.07 MiB Python heap;
    refusing copy peaked at 20.61 MiB. Supported row sizes can scale these
    allocations far beyond the configured engine budget, which does not constrain
    Python objects. Elide in native page queries and bound full-value retrieval
    by bytes before allocation, including preview, folding and copy.
  3. **IR3 [P2]: Short worker pages leave permanently blank model rows.**
    [page](../src/main/python/_quick_view_csv_worker.py#L585) stops at its frame
    budget, but [CsvModel.row](../src/main/python/fman/impl/quick_view_csv.py#L528)
    assumes every cached page covers 100 positions. Reproduced a valid 20-row,
    256-column table with 512-character cells: the worker returns only 10 rows;
    model row 15 is `None` with no follow-up request. After projection reset or
    a cache miss, these records remain blank. Support partial-page continuation
    or negotiate a shared byte-bounded page shape; test wide tables after queries.
  4. **IR4 [P2]: Copy/Find/Inspect results can cross query revisions.**
    [query](../src/main/python/fman/impl/quick_view_csv.py#L191) leaves pending
    actions intact, and [action reply dispatch](../src/main/python/fman/impl/quick_view_csv.py#L400)
    checks generation but not the current revision. Reproduced a revision-1 copy
    reply being emitted while revision 2 is current, and a queued copy surviving
    another query change. `CsvPreview.action_done` writes accepted copy data
    directly to the clipboard. Drop actions/replies tied to obsolete projections
    instead of retagging queued row positions against the new projection.
  5. **IR5 [P2]: The disk quota is a sampler, not an enforced total limit.**
    [_run](../src/main/python/_quick_view_csv_worker.py#L285) checks growth only
    every 200 ms and does not check quota before returning success. A short probe
    completed with 4096 owned bytes under a 1024-byte injected quota, without
    failure. Non-ASCII staging writes also run outside that watcher and compare
    only the staging stream size, not database/WAL/other files; spill is given
    the full quota rather than remaining space. Add pre/post total checks,
    bounded active containment and fold/projection free-space checks, or explicitly
    revise the promised resource contract before approval.
  6. **IR6 [P2]: Auto-detection does not use the advertised parser byte limits.**
    [_dialect](../src/main/python/_quick_view_csv_worker.py#L409) calls `sniff_csv`
    without the import's explicit line/buffer settings. A valid row of three
    900,000-character fields fails with Auto options but imports successfully
    with explicit comma/header choices; each field and the 2.7 MB record are
    within the advertised limits. Default Table View therefore refuses supported
    input before import. Align bounded detection and import settings, and test
    supported long/multiline records through the default route.

  ### Validation

  Focused baseline command, from the repository root with the existing project
  interpreter; executed once with each value of `QT_QPA_PLATFORM`:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts')); sys.exit(subprocess.run([sys.executable, '-B', '-m', 'unittest', 'fman_unittest.impl.test_quick_view_csv', 'fman_integrationtest.test_qt.QuickViewCsvIT', '-q'], env=env, timeout=120).returncode)"
  ```

  - `offscreen`: 16 tests passed in 11.144 s; expected Qt platform warnings only.
  - `windows`: same 16 tests passed in 13.394 s.
  - Two disposable `pylanceRunCodeSnippet` probes exercised the real Engine,
    CsvController and CsvModel for IR1-IR6; temporary fixtures/caches were removed.
    IR2 uses `tracemalloc` for Python heap, not total process memory or a performance
    claim. IR5 uses an injected small quota to expose the enforcement gap.
  - Editor diagnostics for the worker, controller/view, session and new unit tests:
    no errors. No full suite, exact-cap benchmark, frozen artifact or manual
    DPI/theme/UNC validation was run. Previously open delivery gates remain open.
  - Required follow-up regression cases: cancel/retry fold publication, byte-bounded
    long-field fetches, partial pages after projection changes, stale action
    replies/queues, fast/staging total-disk overflow and default long-record detection.

## Response to Implementation Review - 2026-10-26

All six findings were accepted and fixed.

- **IR1:** Each fold column is built inside one guarded operation. Any failure or
  cancellation drops the partial column and its staging file; a new attempt first
  drops a leftover column.
- **IR2:** Preview and page cells are elided natively (`left`, `length`), and rows
  are fetched in batches bounded to 4 MiB of display text. Fold staging fetches by
  byte-size class (4 KiB, 64 KiB, 1 MiB, 4 MiB), at most 4 MiB per batch. Copy
  measures its TSV size natively and refuses before fetching any value. One cell
  and one Find row stay bounded by the field and record limits.
- **IR3:** The model requests the remainder of a short page and merges the
  continuation into the aligned page; stale continuations are dropped.
- **IR4:** A new query drops the queued action. Copy, cell and Find replies, and
  action errors, are accepted only for the current revision.
- **IR5:** Enforced as stated in the design: pre/post totals, a check before a
  projection is published, spill limited to the remaining quota, a free-space
  check, and the watcher now also covers fold staging. Staging is checked against
  the owned total, not only its own size.
- **IR6:** `sniff_csv` uses the import's 16 MiB line and 32 MiB buffer settings.
- **Measured cache use after a global fold:** 17.9 MB of mixed Hebrew/Cyrillic
  text used 23.3 MB (quota 35.7 MB), 17.5 MB of random Cyrillic used 22.0 MB
  (quota 35.0 MB), and 28.8 MB of 600,000-character `é` fields used 58.5 MB
  (quota 57.6 MB), so that last case is refused.
- **Presets (user decision):** engine memory raised to 192/384/768 MiB. The
  earlier 128 MiB budget passed a 500 MB file but failed at 750 MB, too thin a
  margin for the 512 MB cap. The 32 MiB parser buffer stays fixed. Exact-cap
  measurements remain open.