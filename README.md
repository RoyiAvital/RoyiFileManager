[![Visitors](https://api.visitorbadge.io/api/combined?path=https%3A%2F%2Fgithub.com%2FRoyiAvital%2FStackExchangeCodes&labelColor=%23f47373&countColor=%23555555&style=plastic)](https://github.com/RoyiAvital/RoyiFileManager) <!-- https://www.visitorbadge.io -->

# RoyiFileManager

`RoyiFileManager` is a Windows only, portable fork of the [`fman`](https://github.com/mherrmann/fman) 
(By [Michael Herrmann](https://github.com/mherrmann)) dual pane file manager. 

The _File Manager_ focuses on:
 - Minimalistic and focused UI.
 - Commands through _Command Center_.
 - Keyboard oriented workflow.
 - Advanced search tools with reactivity.
 - Easy integration of 3rd party tools (Editors, File Comparison, etc...)

As `fman` states, it is inspired by [SublimeText](https://en.wikipedia.org/wiki/Sublime_Text).

Currently, the _File Manager_ retains the `fman` plug-in API so existing plug-ins can be used
without changing their imports.  
See the [Plug In API Reference](PlugIn.md) for legacy APIs and new extensions.

## Features

Significant additions compared with `fman`:

- **Fuzzy Find Files**: Find files by name with <kbd>Ctrl</kbd>+<kbd>F</kbd> or recursively with <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd>. Supports [`fzf`](https://github.com/junegunn/fzf) style exact terms, anchors, negation, `AND` / `OR` and match highlights. Using **Toggle find result metadata** adds metadata to results. See [Usage, Syntax and Performance](src/main/resources/base/Plugins/SearchFileFuzzy/README.md).
- **Search Files**: Press <kbd>Alt</kbd>+<kbd>F7</kbd> for [`ripgrep`](https://github.com/burntsushi/ripgrep) based filename and content search in Glob, Literal or RegEx mode. Leave content empty to list files by name. See [Search Files Usage](src/main/resources/base/Plugins/SearchFiles/README.md).
- **Find Files with `fd`**: Press <kbd>Shift</kbd>+<kbd>F7</kbd> for [`fd`](https://github.com/sharkdp/fd) based filename search with date, size, type and traversal filters. See [Find Files Usage](src/main/resources/base/Plugins/FindFiles/README.md).
- **Pane Filter / Files Filter**: Type to filter file names with globs, anchors and negation with [`fzf`](https://github.com/junegunn/fzf) inspired syntax. See [Pane Filter Usage](src/main/resources/base/Plugins/Core/README.md#pane-filter).
- **UI Components**: New building blocks that expand what plug-ins can do. [Plug-in UI guide](Plan/UIElements.md#plug-in-api).
- **Docked Panel**: Allows controlling states and operations. Exposed to be used by Plug-In's.
- **Favorites**: Press <kbd>Ctrl</kbd>+<kbd>B</kbd> for a fully features Favorites Manager, built entirely with the plug-in APIs.
- **Recent Commands**: <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> pins the last three commands run from the palette.
- **Process Pane**: Run **Show the OS' processes** for a flat Name/PID list of the system running processes. Press <kbd>F8</kbd> to force terminate it. See [Process Pane Usage](src/main/resources/base/Plugins/ProcessPane/README.md).
- **Extended Status Bar**: Press <kbd>Ctrl</kbd>+<kbd>S</kbd> to cycle through disabled, active-pane and per-pane file statistics.
- **Sync Panes**: Select **Sync pane location** in Command Center to sync the inactive pane to the active pane's path.
- **File Hash**: Press <kbd>Ctrl</kbd>+<kbd>H</kbd> for centered checksum output; use Calculate File Hash By to pick an algorithm in QuickSearch, then view the result. See [File Hash Calculation Usage](src/main/resources/base/Plugins/CalculateFileHash/README.md).
- **Directory Size**: Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>D</kbd> to toggle progressive directory size calculation in both panes, or <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Enter</kbd> for a one time total of selected directories. See [Directory Size Usage](src/main/resources/base/Plugins/Core/README.md#directory-sizes).
- **New File**: Press <kbd>Ctrl</kbd>+<kbd>N</kbd> to create an empty file without opening an editor.
- **Text Editor / Viewer**: Set external programs on <kbd>F4</kbd> / <kbd>F3</kbd>, configured through **Set text editor** / **Set text viewer** in the Command Center. Presets include [CudaText](https://github.com/Alexey-T/CudaText), [EmEditor](https://www.emeditor.com), [Notepad++](https://github.com/notepad-plus-plus/notepad-plus-plus) and [Notepad 4](https://github.com/zufuliu/notepad4). See [Text Editor and Viewer Usage](src/main/resources/base/Plugins/Core/README.md#text-editor-and-viewer).
- **File / Folder Comparators**: Configure independent external tools with **Set file comparator** / **Set folder comparator**, then run **Compare files** / **Compare folders**. Presets include [Meld](https://meldmerge.org), [Beyond Compare](https://www.scootersoftware.com), [WinMerge](https://github.com/winmerge/winmerge), [SmartSynchronize](https://www.syntevo.com/smartsynchronize). See [Comparator Usage](src/main/resources/base/Plugins/Core/README.md#file-and-folder-comparators).
- **Archive Transfers**: Extraction progress and cancellation, with verified output before source deletion when moving out of or between archives. See [Archive Transfers Usage](src/main/resources/base/Plugins/Core/README.md#archive-transfers).
- **Unpack Archive**: Works like `Extract Here` in `7-Zip` / `WinRar`. See [Unpack Archive Usage](src/main/resources/base/Plugins/Core/README.md#unpack-archive).

> [!TIP]
> Open an issue for new feature feature requests.  
> feedback is more than welcome.

## Development

Install a conda package manager then create the environment:

```powershell
conda env create -f environment.yml
conda activate RoyiFileManager
python build.py run
```

The environment intentionally constrains PyQt to the 5.15 branch. Other
packages use compatibility bounds rather than patch pins. Local `freeze`
generates the Windows release lock when it is missing or older than
`environment.yml`; CI always consumes the committed lock and fails if it is
missing. The lock can also be generated manually:

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
2. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`
   and add a fresh `## [Unreleased]` section above it containing only the
   `API compatibility:` statement. Keep that statement in the dated release
   section too.
3. Commit (`Release vX.Y.Z`), Tag and push.

   ```powershell
   git add -A
   git commit -m "Release vX.Y.Z"
   git push origin main
   git tag -a vX.Y.Z -m "RoyiFileManager vX.Y.Z"
   git push origin vX.Y.Z
   ```

The workflow verifies that the tag matches `version`, that the changelog has a
dated `## [X.Y.Z]` section with the compatibility statement and that
`## [Unreleased]` is empty, runs `python build.py test`, `freeze` and
`package`, and publishes a GitHub release whose notes are that changelog
section and whose assets are the ZIP and its SHA-256. Tags with a suffix
(`v1.0.0-rc.1`) are published as pre-releases.

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
python -m unittest src/unittest/python/fman_unittest/test_directory_listing_benchmark.py -v
```

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