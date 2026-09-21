[![Visitors](https://api.visitorbadge.io/api/combined?path=https%3A%2F%2Fgithub.com%2FRoyiAvital%2FStackExchangeCodes&labelColor=%23f47373&countColor=%23555555&style=plastic)](https://github.com/RoyiAvital/RoyiFileManager) <!-- https://www.visitorbadge.io -->

# RoyiFileManager - Development

## Development

Install a conda package manager then create the environment:

```powershell
conda env create -f environment.yml
conda activate RoyiFileManager
python build.py run
```

After updating an existing checkout, refresh its runtime dependencies with
`conda env update -f environment.yml` before running it.

The lock can also be generated manually:

```powershell
conda-lock lock -f environment.yml -p win-64
```

## Planning and Implementation Workflow

The [`Plan.md`](Plan.md) file is the task index. Each pending task has one standalone
document under [Plan](Plan/), and completed tasks move to [Done](Done/). Task
documents record design and review provenance, alternatives, runtime effects,
tests, acceptance criteria, implementation provenance, and validation results.

Repository-wide contribution and task-lifecycle requirements are defined in
[AGENTS.md](AGENTS.md). Completed user-visible work must also be reflected in
[CHANGELOG.md](CHANGELOG.md).

## Tests and Packaging

```powershell
python build.py test
python build.py freeze
python build.py package
```

`test` checks application behavior and release/build inputs. Benchmark harnesses,
synthetic performance fixtures, report generation and standalone PoCs are outside
normal discovery and CI. Their optional [development-tool checks](src/performancetest/README.md#development-tool-checks)
run separately; they are not release validation.

`test` prints each test name as it runs. Each discovery group emits Python
thread stacks every two minutes while still running and has a ten-minute timeout.
For a stalled CI run, use the last test name and thread dump to locate the wait;
the full GitHub Actions build also has a sixty-minute job limit.

`run`, `test`, and `freeze` download the pinned x64 `7za.exe` from the official
7-Zip distribution when it is not already present under the Core plug-in.
These commands therefore require internet access on their first run.
Transient HTTP download failures are retried three times, after 1, 2, and 4
seconds. SHA-256 checks remain mandatory; permanent HTTP errors and hash
mismatches fail the build. A persistent server outage still requires a later
retry of the failed workflow.

Content search uses conda-forge's installed `bin/rg.exe` from the active Python
prefix. PyInstaller bundles it with the notices under
[SearchFiles/licenses](src/main/resources/base/Plugins/SearchFiles/licenses),
without requiring the conda package cache. Refresh these notices when updating
ripgrep in the lock file. There are no custom downloads, version/hash checks or
integrity manifests. Packaged searches use the bundled executable, not a system
`rg` or Python installation.

Find Files similarly uses conda-forge's `bin/fd.exe` and bundles it with
[fd notices](src/main/resources/base/Plugins/FindFiles/licenses). Refresh those
notices when updating `fd-find` in the lock file.

`freeze` creates a PyInstaller onedir build. `package` produces
`target/RoyiFileManager-<version>-windows-x86_64.zip` with an empty
`UserSettings` directory. Both outputs include `environment.yml` and the
generated `conda-lock.yml`. Extract the archive to a writable directory before
running it.

All mutable application data is stored in `UserSettings` beside the
executable. Development and tests can override this path with the
`ROYIFILEMANAGER_USER_SETTINGS` environment variable.

RoyiFileManager does not intentionally write to the Windows Registry. Release
validation should confirm this with Process Monitor, filtering on the
RoyiFileManager process and Registry write operations.

## Releasing

Releases are built by the `Release` GitHub Actions workflow
(`.github/workflows/release.yml`). It never runs on ordinary pushes; it runs
only when a version tag is pushed:

1. Set `version` in `src/build/settings/base.json`.
2. In `CHANGELOG.md`, add `## [X.Y.Z]` below the first section,
   `## [Unreleased]`, and move this release's entries into it. A
   ` - YYYY-MM-DD` date suffix is optional. Section bodies are free-form and
   may be empty; no `API compatibility:` statement is required.
3. Commit (`Release vX.Y.Z`), Tag and push.

   ```powershell
   git add -A
   git commit -m "Release vX.Y.Z"
   git push origin main
   git tag -a vX.Y.Z -m "RoyiFileManager vX.Y.Z"
   git push origin vX.Y.Z
   ```

The workflow verifies that the tag matches `version`, that `## [Unreleased]`
is the first changelog section and that a matching `## [X.Y.Z]` section exists.
It runs `python build.py test`, `freeze` and `package`, then publishes a GitHub
release whose notes are that version's section and whose assets are the ZIP
and its SHA-256. Draft entries under `Unreleased` are not included in the
release notes. Tags with a suffix (`v1.0.0-rc.1`) are published as pre-releases.

Run the workflow manually from the Actions tab (`workflow_dispatch`) to build
without publishing; the ZIP is then available as a workflow artifact. The
changelog check can be previewed locally:

```powershell
python .github/scripts/release_notes.py --version X.Y.Z
```

### Retrying a Failed Release

In case of a failure of the GitHub Action, assuming fix is applied run:

```powershell
git add -A
git commit -m "Release vX.Y.Z"
git push origin main
git tag -f -a vX.Y.Z -m "RoyiFileManager vX.Y.Z"
git push --force origin refs/tags/vX.Y.Z
```

## Miscellaneous Scripts

Developer utilities that are not included in release packages live under
`src/misc`.

### Fuzzy Search Benchmark

`benchmark_fuzzy_search.py` compares the built-in regular substring baseline
and three fuzzy-search implementations: a pure Python subsequence matcher,
RapidFuzz `QRatio`, and Jellyfish Jaro-Winkler similarity. By default, it scans
up to 75,000 files under the Windows and Program Files known folders and runs a
representative set of filename queries. RapidFuzz and Jellyfish must be
installed in the active Python environment.

```powershell
python src/misc/benchmark_fuzzy_search.py
```

Use `--max-files`, `--repeat`, `--limit`, and repeatable `--query` options to
change the workload. Folder paths supplied as positional arguments replace the
default roots:

```powershell
python src/misc/benchmark_fuzzy_search.py --max-files 50000 `
	--query "power shell" C:\Windows C:\Program Files
```

### Pane Snapshot Benchmark

[pane_arch_poc.py](src/misc/pane_arch_poc.py) compares the original simplified
matchers with the current Filter Bar and Fuzzy Find algorithms on a standalone
snapshot model. It does not replace the application's pane.

```powershell
python src/misc/pane_arch_poc.py "C:\Path\To\Folder" --platform windows --algorithms current --json target/diagnostics/pane-current.json
python src/misc/pane_arch_poc.py "C:\Path\To\Folder" --platform windows --algorithms simple --json target/diagnostics/pane-simple.json
```

Current mode is the default. `--queries` and `--fuzzy` accept query sequences;
`--max-results` limits fuzzy output (default 100, zero means all). Both modes
search pane-visible entries by default. Use `--fuzzy-scope files
--fuzzy-include-hidden` for file-only candidates independent of pane visibility.
The current wrapper computes highlights but this table does not draw them.
Reports separate index construction, matching, completed reset/paint and memory.
These are synchronous query calls, not real keyboard-latency measurements.
The simplified regex can stall on adversarial inputs; use current mode for those.
See [measurements and limits](Done/FSPaneArch001.md#current-matcher-experiment).

For the isolated unchanged-refresh and Windows watcher A/B experiment, use the
existing application Python environment:

```powershell
python src/misc/benchmark_snapshot_followup.py --qt-tests --merged
python src/misc/benchmark_snapshot_followup.py --measure --merged
python src/misc/benchmark_snapshot_followup.py --qt-restore --merged
```

These compare a retained baseline with the merged implementation using synthetic
200,000-entry snapshots; no disk fixture is needed. Omit `--merged` to exercise
the process-local prototypes. Application source files are never edited by the
runner. `--repeat` controls alternating pairs (default nine); optional `--output`
writes a new JSON file and refuses to overwrite one. The probes are separate
from `build.py measure` and do not establish end-to-end latency or memory limits.

### Directory Listing Benchmark

[benchmark_directory_listing.py](src/misc/benchmark_directory_listing.py) compares
`os.listdir()` plus one `os.stat()` per entry with `os.scandir()` metadata reuse.
It uses only the standard library, reads one directory level, and leaves files and
application behavior unchanged. Pass the folder that feels slow:

```powershell
python src/misc/benchmark_directory_listing.py "C:\Path\To\Folder" --repeat 30 --warmup 2
```

Multiple folder arguments are supported; no arguments uses the current directory.
Run order alternates; `--first scandir` reverses the initial order. Output includes
first-observed time, median/min/max, absolute milliseconds saved and a time ratio.
OS caches are not flushed: neither the first observation nor repeated runs prove
cold-storage performance. Each run enumerates afresh without the application's cache.

Names, directory flags, file sizes and modification times must agree across methods
and runs. Links follow targets, with the application's missing-target fallback.
Metadata errors or differences suppress the speedup and return exit code 1; use a
quiet folder. This is not a full pane benchmark: icons, sorting, date formatting,
Qt and plug-ins are excluded. Full identity fields are also excluded; on Windows,
`DirEntry.stat()` cannot replace the application's complete `stat()` cache used by
same-file checks and moves. A large ratio can still mean negligible absolute savings.

Focused regression tests:

```powershell
python -m unittest src/performancetest/python/fman_performancetest/test_directory_listing_benchmark.py -v
```

### Pane Rendering Benchmark

[benchmark_pane_rendering.py](src/misc/benchmark_pane_rendering.py) compares the
prepared 256-file and 200,000-file synthetic folders. Use the existing
application Python environment on Windows:

```powershell
python src/performancetest/run.py suite --test "pane.*" --prepare-only
python src/misc/benchmark_pane_rendering.py
```

The runner sets up application import paths automatically, performs three
alternating baseline/current pairs per folder, and prints median first-paint,
completion and loading arrow-to-paint timings. The default compares the snapshot
implementation with pre-change commit `56e840a`, extracted into temporary storage.
Git and that commit must be available; `--baseline-ref` overrides it. Raw samples go to
`target/diagnostics/pane-rendering-three-folders.json`; `--output` changes that
destination. A missing folder, failed child or row/metadata mismatch returns
nonzero; invalid comparisons do not produce a summary. OS caches are not flushed.

Folder arguments override the defaults; `--repeat 1` is a shorter smoke run:

```powershell
python src/misc/benchmark_pane_rendering.py --baseline reviewed --repeat 1
python src/misc/benchmark_pane_rendering.py "C:\Path\To\Folder" --show-hidden
python -m unittest src/performancetest/python/fman_performancetest/test_pane_rendering_benchmark.py -v
```

[pane_rendering_benchmark.py](src/performancetest/python/fman_performancetest/pane_rendering_benchmark.py)
measures actual pane loading and arrow-to-paint latency in isolated fresh
processes. `--baseline current` compares the historical application with snapshots.
`--baseline before` and `--baseline reviewed` retain historical hidden-cache
experiments within the extracted application, not comparisons with snapshots.
Use `--repeat 3`, `--show-hidden` for the
filter-off control, and `--output` to retain JSON results. Child-only
`--rows-output` records final rows after timing to diagnose parity differences.
Run directly through `python src/performancetest/run.py pane` with folder arguments.
Historical CelebA results are not comparable to the new synthetic baseline.

### Repeatable Performance Suite

Performance workloads live under [src/performancetest](src/performancetest/README.md),
outside verification discovery. Definitions and comments live in
[catalog.yaml](src/performancetest/catalog.yaml); each run writes a new JSON record
with application version, source/harness hashes, environment, fixture hashes and
summary statistics. Repetition counts are unchanged; new records retain metric
counts, medians, ranges and p95 instead of raw observations. The runner never
rewrites the YAML or an existing result, and older raw records remain readable.

```powershell
python build.py measure
```

`python build.py test` runs correctness verification; `python build.py measure`
runs the full performance suite, updates the version result, generates an offline
HTML report and opens it in the browser. No workload/profile selection is needed.
Results and `index.html` live under `UserSettings/Performance`, surviving `clean`.
Version identifiers are `X.Y.Z` for clean matching release tags, or `Unreleased`;
the source version and commit are retained separately. Reruns replace the version's
current result but preserve earlier runs. Failed runs never replace successful results.

The report has eleven overview rows, including Refresh / Selection and a Navigation
aggregate of Page Up/Down, Home/End and wheel scrolling. Previous-version comparisons, charts
and detailed measurements use compatible results only; the first run establishes
a baseline. The original `src/performancetest/run.py suite` remains available for
developer diagnostics without updating this version history.

The default suite uses three fresh processes per test, synthetic 256-file and
200,000-file folders, and a 50,000-file recursive tree. It measures real pane
loading, Filter Bar, Quicksearch Fuzzy Find, recursive Find (`Ctrl+Shift+F`) and
QuickView image paints, responsiveness and memory. Page Up/Down, Home/End and
mouse-wheel latency are measured in both normal and QuickView-enabled panes.
Refresh / Selection averages 16 unchanged-refresh case medians: eight selection
patterns in both folder sizes, from no marks through scattered and all-marked
selections. Reload-to-completed-paint timings check snapshot, marks, cursor and
scroll preservation; per-case timings and process peak memory remain in the report.
See the [protocol and result format](src/performancetest/README.md).

### Everything Search Backend Probe

[everything_probe.py](src/misc/everything_probe.py) evaluates
[voidtools Everything](https://www.voidtools.com/) as a search backend. It runs a
portable Everything 1.4 executable as a *named* background instance with standard
privileges and folder indexing only, queries it through the built-in loopback HTTP
JSON API and reports index build time, memory, per-query latency and instance
isolation. Settings and the database are written to the work directory, never
beside the executable, and the instance is exited at the end. Standard library only.

```powershell
python src/misc/everything_probe.py --exe "D:\Tools\Everything\Everything.exe"
python src/misc/everything_probe.py --exe ... --all-drives --build-timeout 1800
python src/misc/everything_probe.py --exe ... --collision
```

Everything 1.5 moved the HTTP server into a plugin, so use a 1.4 build. Everything
prints nothing to a console and opens its options window on an unknown switch. The
`--collision` check verifies that a user's own unnamed Everything instance keeps
running untouched beside ours. Findings are recorded in
[Find Files 003](Plan/FindFiles003.md).

See [UPSTREAM.md](UPSTREAM.md) for the upstream merge policy.