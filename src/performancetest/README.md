# On-Demand Performance Tests

Use the existing Windows application environment from the repository root.
`import yaml` is PyYAML, not a Python standard-library module. PyYAML 6.0.3 is
already in the dependency lock; the runner installs nothing. Catalog loading
uses a SafeLoader subclass that also rejects duplicate keys.

```powershell
python build.py measure
```

This runs all eleven catalog workloads, three repetitions each, without profiling;
updates the version's result; generates a standalone HTML report; and opens it in
the default browser. No arguments or profile selection are required. It does not
run correctness verification, build the application or install dependencies.
`build.py test` does not run performance workloads or their development-tool
checks. A failed measurement run returns nonzero and displays its failure without
replacing the last successful version result.

## Report and Version History

Retained output lives under `UserSettings/Performance`, outside `build.py clean`:

- `runs/<uuid>.json`: immutable statistics-only results, including failed attempts.
- `versions.json`: atomically updated version-to-run index, one current result per version.
- `index.html`: regenerated offline report; embedded data, charts and icon, no network requests.

Version identifiers are exactly `X.Y.Z` or `Unreleased`. A clean checkout at tag
`vX.Y.Z` or `X.Y.Z` matching the application version is a release measurement.
All other checkouts are `Unreleased`. Source version, commit and dirty state remain
in the result record. Repeating a version replaces its index entry, not its old run.
Corrupt history is reported, never silently reset. Earlier diagnostic runs under
`target` are not imported as previous versions.

The overview has eleven rows: pane loading, Filter Bar, Fuzzy Find and QuickView in
small/large folders, Fuzzy Find (Recursive), Refresh / Selection, and Navigation. Headlines are first populated
paint, slowest query median, or first preview paint, respectively. Navigation is
the arithmetic mean of 28 case medians: seven actions across small/large panes with
QuickView off/on, equally weighted. Refresh / Selection is the mean of 16 case
medians: eight selection patterns across small/large folders. Missing cases suppress the aggregate. Details
retain every case so the aggregate cannot conceal individual regressions.

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

The fixtures are `flat-small-v1` (256 files), `flat-large-v1` (200,000 files), and
`recursive-v1` (50,000 files with fixed branching and depth). Names use SHA-256
of seed/index with long repeated strings, Unicode, numbers, spaces and literal
punctuation. PNG pixels use integer bands; JPEG/BMP conversions use the recorded
Qt encoder. Small images are 1280x960; large images are 4096x3072. Flat fixtures
also contain corrupt and unsupported preview inputs. Filler files are empty,
including those with image extensions; QuickView targets named preview assets.

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
  Scenarios cover disabled navigation, PNG/JPEG/BMP switching, invalid inputs,
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

## JSON Records

Each measurement creates `UserSettings/Performance/runs/<uuid>.json` with exclusive
creation. The diagnostic launcher defaults to `target/performance/runs` and accepts
`--results` and `--note`. Failed attempts retain statistics for completed
repetitions and an error. New records use `schema_version: 2`; schema-1 records
remain readable and are not rewritten.

| Field | Meaning |
| --- | --- |
| `run_id`, `started_at`, `finished_at`, `status` | Unique run, UTC bounds and outcome |
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