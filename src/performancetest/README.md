# On-Demand Performance Tests

Use the existing Windows application environment from the repository root.
`import yaml` is PyYAML, not a Python standard-library module. PyYAML 6.0.3 is
already in the dependency lock; the runner installs nothing. Catalog loading
uses a SafeLoader subclass that also rejects duplicate keys.

```powershell
python build.py measure
```

This runs the thirteen regular workloads, three repetitions each, without profiling;
updates the version's result; generates a standalone HTML report; and opens it in
the default browser. No arguments or profile selection are required. It does not
run correctness verification, build the application or install dependencies.
`build.py test` does not run performance workloads or their development-tool
checks. A failed measurement run returns nonzero and displays its failure without
replacing the last successful version result.

The regular suite keeps the original eleven workloads and two selection workloads,
with five patterns per size. It does not prepare or run the Copy fixture. To also
measure medium folders and Copy:

```powershell
python build.py measure --full
```

Full mode adds six workloads on a 50,000-file flat folder: pane loading, refresh,
Filter Bar, Fuzzy Find, QuickView and selections, plus two Copy workloads.
Navigation is included in pane
and QuickView workloads. It runs twenty-one workloads with the same three
repetitions and protocols; it does not enable profiling or legacy stress tests.

## Report and Version History

Retained output lives under `UserSettings/Performance`, outside `build.py clean`:

- `runs/<uuid>.json`: immutable statistics-only results, including failed attempts.
- `versions.json`: atomically updated version-to-run index, one current result per version.
- `index.html`: regenerated offline report; embedded data, charts and icon, no network requests.

Full runs use the same structure under `UserSettings/Performance/Full`. Their
version index and report are separate; they never replace regular-run history.

Version identifiers are exactly `X.Y.Z` or `Unreleased`. A clean checkout at tag
`vX.Y.Z` or `X.Y.Z` matching the application version is a release measurement.
All other checkouts are `Unreleased`. Source version, commit and dirty state remain
in the result record. Repeating a version replaces its index entry, not its old run.
Corrupt history is reported, never silently reset. Earlier diagnostic runs under
`target` are not imported as previous versions.

The regular overview has sixteen rows: pane loading, Filter Bar, Fuzzy Find, QuickView Images
and QuickView Text in
small/large folders, Fuzzy Find (Recursive), Refresh / Selection,
Selections / Small, Selections / Large, Selections Readback, and Navigation. Headlines are first populated
paint, slowest query median, first PNG preview paint, or the mean of TXT/Python/Markdown
paint medians, respectively. QuickView Images/Text rows are consecutive; Selections
Readback immediately follows the Selections rows and shows the slowest of ten selected-file
readback case medians: five patterns in each folder size. These derived rows reuse
the thirteen workloads, without extra measurement processes. Navigation is
the arithmetic mean of 28 case medians: seven actions across small/large panes with
QuickView off/on, equally weighted. Refresh / Selection is the mean of 16 case
medians: eight selection patterns across small/large folders. Each Selections row
is the mean of five full selection-interaction case medians for its folder size. Missing
or failed selection cases suppress that aggregate. Details
retain every case so the aggregate cannot conceal individual regressions.

Full reports have twenty-four rows, including the additional medium pane, Filter
Bar, Fuzzy Find, QuickView Images, QuickView Text, Selections / Medium and two Copy rows.
Readback spans fifteen case medians. Refresh remains
one aggregate, now across 24 case medians; Navigation averages 42. Both require
all expected medium cases as well as small/large cases before showing an average.

Previous-version comparisons show absolute/percentage changes, not significance
claims. Charts show compatible versions in measurement-date order and observed
ranges; aggregate ranges span their case medians. First-version and incompatible
states have no invented deltas. Reporting lives in `src/misc/performance_report.py`
and its HTML template, outside the measured harness hash.

## Definitions and Fixtures

[catalog.yaml](catalog.yaml) is human-maintained and never rewritten. Comments
explain intent; `notes` fields survive in JSON records. Test and query IDs are
stable names, not list positions. A query/action is identified by the pair
`test_id` and `query_id`/`action_id`. Increment test revisions when changing
semantics or measurement boundaries. Change fixture IDs when changing contents.

`tests` defines the regular suite; `full_tests` contains the six optional medium
definitions and both Copy cases. Records store the effective mode's definitions. Regular runs
do not create, verify or scan medium or Copy fixtures. Explicit diagnostic `--test` patterns
can match either list, independently of `--full`.

The fixtures are `flat-small-v1` (256 files), `flat-large-v1` (200,000 files),
optional `flat-medium-v1` (50,000 files), and `recursive-v1` (50,000 files with
fixed branching and depth). Names use SHA-256
of seed/index with long repeated strings, Unicode, numbers, spaces and literal
punctuation. PNG pixels use integer bands; JPEG/BMP conversions use the recorded
Qt encoder. Small images are 1280x960; large images are 4096x3072. Flat fixtures
also contain corrupt images and a plain-text preview input. Filler files are empty,
including those with image extensions; QuickView targets named preview assets.
QuickView revision 3 uses separate `flat-small-v2`, `flat-large-v2` and optional
`flat-medium-v2` fixtures with the same counts plus representative Python and
Markdown content replacing two empty fillers. Plain TXT remains an explicit case.
Existing v1 fixtures and manifests are never changed. Preparing v2 requires an
additional folder per measured size; setup and verification are untimed.

Creation/modification timestamps are fixed to 2024-01-01 UTC; file/directory
attributes are fixed. Names, bytes, metadata and directory layout are verified
before timing. OS-assigned file IDs, physical placement and last-access times
are not portable fixture properties. Changed encoder output is rejected; it
does not silently replace existing data.

Files live under `target/performance/fixtures`. Mismatched, modified, linked or
incomplete fixtures are refused, never overwritten or automatically deleted.
The diagnostic launcher accepts another `--fixtures` directory to regenerate. Do not edit fixtures or run
file operations against them. Generation and verification are untimed. All
fixtures and results are local; nothing is uploaded.

## Protocol

### Copy Workload

Copy runs only with `python build.py measure --full` (or an explicit diagnostic
selection). The two cases are:

- `copy.flat`: 10,000 ordinary files, exactly 4,096 bytes each, seed 1732.
- `copy.tree`: 1,000 files, exactly 8,192 bytes each, seed 1733. Ten root branches
  contain five buckets each and nested chains of one to six levels, exercising
  breadth and depth. Selected root entries and copied files are counted separately.

Sources are verified read-only fixtures; every repetition uses a new disposable
destination outside them. Allow about 94 MiB for both sources plus destinations,
with filesystem overhead and staging headroom. No user files are copied. The
old `copy-files-v1` fixture and its results remain historical, not reinterpreted.

The native app receives Ctrl+A and F5, and its actual destination prompt is
accepted. Selection paint/input/readback, prompt latency, task gathering, first
completed file, total copy and final destination refresh are separate metrics.
Copy workload revision 2 (catalog revision 14) measures `input_ready_ms` from
Ctrl+A dispatch through the verified Down-key response and completed paint.
The next input follows selection paint without a settled-idle delay; queued
work and dispatch time remain inside the interval. Selected-URL readback runs
afterward and is not added to it. Revision 1 instead timed only the follow-up
key; those historical values remain unchanged and are not comparable to revision 2.
Fixture contents, repetitions and first-file/total-copy boundaries are unchanged.
The Copy headline includes preparation but excludes source setup, content
verification and cleanup. All source/destination bytes and file counts must match.
Tree verification also requires matching relative paths and directory structure.
Three repetitions are used; a failed or timed-out copy is never a successful result.
When a short run finishes before progress appears, `progress_shown_count` is zero
and `progress_visible_ms` is zero; this is not an instantaneous visible dialog.

Memory details include before/after working set, process peak and preparation
delta per queued task. The 200,000-task estimate includes allocator and other
preparation overhead; it is not a measured 200,000-file copy or exact object size.
The parent owns scratch storage so a timed-out child cannot leave its copy tree.

### Copy Reference Results

Retained medians from three successful runs per version, 15,000 x 8 KiB, warm
caches, real Ctrl+A/F5 and destination-pane refresh. `Unreleased` is the measured
Option A implementation, not a clean release. Moving the workload to full mode
does not rewrite these reference results or their original catalog/harness hashes.

| Metric                   | 0.14.0    | Unreleased |
| ------------------------ | --------- | ---------- |
| Select All paint         | 9.94 ms   | 6.02 ms    |
| Progress first visible   | 14.62 s   | 1.02 s     |
| Task preparation         | 14.53 s   | 0.538 s    |
| First completed file     | 28.15 s   | 0.555 s    |
| Copy complete            | 129.03 s  | 113.09 s   |

Source run IDs: `55eba804-8f59-4661-a7a3-4d74029c263a` and
`95092cdd-d9b4-47a7-9f24-a2db21f1010f`. The raw records and comparison are retained
under `UserSettings/Performance/CodeReview010`; full provenance is in
[FileOperations001](../../Done/FileOperations001.md#baseline-and-comparison).

An earlier corrected-baseline attempt crashed during repetition two with a native
access violation while copy and destination refresh were active. Its traceback
and failed record are retained; the root cause is unresolved. Three subsequent
baseline runs and three A runs passed. This does not establish that A fixed the
crash or that future runs cannot encounter it. Only disposable files were involved.

### Shared Settings

- Three fresh processes per test; diagnostic `--repeat` overrides are recorded.
- Native Windows Qt, 1280x800 window, 1x DPI, isolated settings, hidden files
  included, metadata display and extended status off.
- Warm OS caches after fixture verification; no cold-storage timing claim.
- Refresh performs one real unchanged-folder reload per selection pattern per
  process: none, first/middle/last single mark, a middle block (10% of rows),
  100 evenly scattered marks including both ends, all except the cursor, and all.
  Cursor and scroll vary with the pattern. Setup is untimed; the interval starts
  before reload dispatch to Qt and ends after a new snapshot commits and paints.
  Snapshot columns, row order, marks, cursor and scroll must remain unchanged.
  CPU time, Qt commit time and working set before/after are retained per case.
  Peak working set is the process high-water mark, including startup and earlier
  cases, not isolated refresh allocation. A full row-text fingerprint is omitted
  for these workloads to avoid warming every formatted cell before refresh.
  No arrow input is injected during the refresh interval; this does not measure
  loaded-input p95, selection setup speed, changed-folder refresh, or cold caches.
- Filter/Fuzzy/recursive tests drive the real UI and independently measure the
  production algorithms; result counts must agree. Search covers the entire
  fixture with a 100-result limit. The application default candidate cap is
  intentionally overridden and recorded.
- Fuzzy test revision 2 measures the restored Quicksearch dialog, including
  snapshot-backed current-folder indexing. Filter Bar timing remains in-pane.
  Earlier in-pane fuzzy results are historical and cannot be compared with this
  changed harness.
- One posted replacement-query event per query measures pasted-query latency,
  not character-by-character typing or held-arrow backlog.
- Active-only 10 ms heartbeat and posted-event probes, without idle padding.
  Paint means completed Qt paint cycle, not compositor presentation.
  QuickView registers Python paint dispatch before creating panes so Qt can see
  the later navigation hook. Navigation still timestamps immediately after the
  original paint handler returns; no queued acknowledgement is used.
- QuickView includes its normal 100 ms debounce and first lazy renderer import.
  Revision 3 measures separate TXT, syntax-highlighted Python and rendered Markdown
  switches. Exact content, Python keyword colours, and Markdown heading/list/link
  formatting must match. Text headlines require all three; older records with only
  TXT do not receive a fabricated text aggregate. Image and text timings have
  separate report rows, using the same fresh-process workloads.
  Scenarios cover disabled navigation, PNG/JPEG/BMP/text switching, invalid images,
  fit/actual size/zoom/pan, 30 ms rapid navigation, close/reopen and cancellation
  before the debounce fires. Pixels, dimensions/format and target-pane state
  are checked after timing. In-flight decode cancellation is not stressed here.
- Page Up/Down, Home/End, wheel-up/down and a ten-event wheel burst each have
  stable action IDs and five samples per process, in normal and QuickView-enabled
  panes. Keys start at the middle row, and wheel events start away from scroll
  boundaries. The final cursor/scroll position and actual paint are checked.
  Wheel events use 120 angle units and three scroll lines; wheel scrolling must
  leave the cursor unchanged. These are posted Qt events, not hardware/driver
  measurements. QuickView navigation measures pane paint, separately from preview
  completion. Touchpad pixel scrolling and kinetic scrolling are not simulated.
- Diagnostic `--profile` adds separate algorithm cProfile passes; `measure` never
  requests them. Profiled samples are not
  included in timing/peak-memory summaries. Python 3.14 profiling can include
  other threads; profiles are not isolated per-thread CPU measurements.

Keep other heavy processes idle. Reproducibility fixes inputs and procedures,
not elapsed times. Storage, antivirus, temperature and background activity can
still affect results. NTFS and ReFS are distinct runs; select another volume
with `--fixtures`. Dependencies and encoder versions must match for comparison.
Historical CelebA measurements are not substituted into synthetic histories.

## Selection Measurements

Selection is separate from the existing untimed refresh setup. It uses the real
pane API without changing application code.

| Pattern | Small (256 files) | Medium (50,000; full only) | Large (200,000 files) |
| --- | ---: | ---: | ---: |
| Single file | 1 | 1 | 1 |
| All files, using `select_all` | 256 | 50,000 | 200,000 |
| Contiguous block | 64 | 1,000 | 1,000 |
| Alternating rows | 64 | 1,000 | 1,000 |
| Seeded scattered rows | 64 | 1,000 | 1,000 |

All five patterns share one loaded pane per size and repetition. Three fresh
processes per size give six selection processes in regular mode, nine in full
mode. Status stays disabled; selection is cleared before each pattern, outside
timing. There is no status matrix or reselect/deselect/invert stress matrix.

The regular selection added-runtime target is at most two to three minutes. Each selection process
has a 25-second limit including startup, setup, all five patterns, verification
and shutdown: 150 seconds of child-runtime allowance across the six processes.
This leaves headroom for orchestration; it is not a measured total-runtime claim.
Existing fixtures are reused. A timeout fails the workload, preserves completed
stages and marks unstarted patterns as not run. Later repetitions/workloads are
still attempted; fixture preparation remains a prerequisite.

Full mode adds three medium selection processes with the same 25-second limit,
plus the other medium workloads and fixture preparation/verification. Full mode
takes longer and is not subject to the regular selection's added-runtime target;
its actual duration has not been measured.

Selection revision 5 records `input_ready_ms`: elapsed time from selection
dispatch through a posted Down key, verified cursor movement and completed paint.
The all-files case uses the public `select_all` API; the other cases use `select`
with explicit URLs. The headline averages five case medians, not their sum.
Queued selection observers are included. Regular measurements keep status disabled.
The separate native regression enables status and waits for its real refresh timer
and Qt-thread snapshot before posting the key; it does not wait for background
size-calculation I/O. This is a verified next-input response, not physical-device
latency, an arbitrary empty callback or a claim about every future observer.

The cursor and scroll are checked before the probe, then restored outside timing.
Standalone `get_selected_files` diagnostics and membership assertions run only
after the endpoint. Fixture preparation and initial selection reset are excluded.

Retained diagnostic metrics include mutation wall/CPU time, dispatch-to-completed pane paint,
independent readback wall/CPU time, requested/initial/expected/selected counts and
actual pane rows. Active-only heartbeat and queue probes include the final blocked
interval even when no timer fires. Cursor, scroll and duplicate-free membership
are checked after timing. No row-text fingerprint or loading-arrow probe runs in
selection cases; initial pane loading itself is outside selection timing.

Older records retain their phase details, including revision 4's composite
`responsive_ms`, but receive no fabricated input-ready headline. Catalog revision
9 and selection revision 5 prevent comparisons with the older definition. A fast
next-input response does not imply fast enumeration of every selected URL; the
independent readback metric exposes that cost without adding it to the headline.

Completed stages are retained when a later stage times out. Failures retain case,
repetition and last completed stage; missing durations are not zero samples.
The HTML details show these failures and distinguish counts from milliseconds.
Failed runs stay in `runs/` and have a report, but do not replace a successful
version entry. Start/end application and harness hashes must agree for a valid
reference. Keep both source trees unchanged during a measurement run.

For selection-only diagnostics across all three sizes:
`python src/performancetest/run.py suite --test "selection.*"`.
For medium only: `python src/performancetest/run.py suite --test "selection.medium"`.
Use `python build.py measure` for the regular thirteen-workload report and history.
Use `python build.py measure --full` for all nineteen workloads and separate full history.

## JSON Records

Each regular measurement creates `UserSettings/Performance/runs/<uuid>.json` with
exclusive creation; full measurements use `UserSettings/Performance/Full/runs`.
The diagnostic launcher defaults to `target/performance/runs` and accepts
`--results` and `--note`. Failed attempts retain statistics for completed
repetitions and an error. New records use `schema_version: 2`; schema-1 records
remain readable and are not rewritten.

| Field | Meaning |
| --- | --- |
| `run_id`, `started_at`, `finished_at`, `status` | Unique run, UTC bounds and outcome |
| `suite_mode` | `regular` or `full`; older records without this field are regular |
| `application` | Version identifier, source version, Git commit, dirty flag, actual application-source hash |
| `harness` | Harness commit and actual harness-source hash |
| `environment` | Anonymous machine/volume IDs, OS, CPU, RAM, disk inventory, filesystem, power plan, locale, Python/Qt and dependencies |
| `catalog`, `catalog_sha256`, `parameters` | Definition snapshot, semantic hash and effective parameters |
| `fixtures` | Fixture IDs, generator specifications and manifest hashes |
| `results` | Test ID/revision/definition hash, fixture hash, status, completed repetition count and metric summaries |
| `artifacts`, `notes` | Separate profile locations and persistent annotation |

Times use `_ms`; memory uses `_mib`. Each metric retains count, median, minimum,
maximum and p95; p95 is `null` below 20 observations. Individual observations,
per-repetition payloads and raw event-loop probes are discarded after aggregation,
not saved in a second file. All repetitions, queries and correctness checks still
run unchanged. `completed_repetitions` counts finished test repetitions, while
metric counts can include repeated actions within each process. Report details,
Navigation/Refresh aggregates and comparison values are unchanged. Application,
environment, fixture and definition metadata remain for compatible comparisons.

Existing schema-1 files still contain their original raw data. Comparisons accept
either format but continue to require matching harness and definition hashes;
this storage change does not bypass those checks.

Run the same harness/catalog against each application version and retain its
JSON output. Comparison emits median deltas for common test IDs; negative values
mean lower time or memory. It rejects failed runs and mismatched machine,
environment, harness, fixture, definition or revision. It does not claim
statistical significance. Dirty-tree records are identified by content hash and
are not labeled as clean release measurements.

## Legacy Diagnostics

These commands do not update the version index or open the HTML report:

```powershell
python src/performancetest/run.py suite --list
python src/performancetest/run.py suite --full --list
python src/performancetest/run.py suite --test "pane.*" --prepare-only
python src/performancetest/run.py suite --test "refresh.*"
python src/performancetest/run.py suite --test "fuzzy.*" --profile
python src/performancetest/run.py suite --compare baseline.json current.json
```

`run.py legacy-search`, `legacy-metadata`, `pane-filter`, `ui-table`, `poc`,
`image`, `fd`, `archive-copy` and `archive-move` preserve earlier opt-in
measurements outside verification discovery. `image` includes the separate
128 MP stress case. These print diagnostics; they are not catalog-versioned
history. `run.py search` retains the earlier configurable seeded Filter/Find
runner. `run.py pane` retains historical application A/B comparisons.

## Development-Tool Checks

Normal application and release verification does not test benchmark harnesses,
catalogs, synthetic performance fixtures, result summaries, HTML generation or
standalone PoCs. Their checks live alongside the tooling in
`python/fman_performancetest/test_*.py`, outside `build.py test` and CI discovery.
Do not add this directory to normal discovery.

Run these checks explicitly when changing the development tools:

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'src/performancetest/python', '-p', 'test_*.py'], env=env).returncode)"
```

This uses small fixtures and mocked measurement runs plus small PoC smoke checks;
it does not run the full performance catalog or publish a retained report. Neither
`build.py test` nor `build.py measure` invokes these checks automatically.