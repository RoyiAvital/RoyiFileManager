# RoyiFileManager

`RoyiFileManager` is a Windows only, portable fork of the [`fman`](https://github.com/mherrmann/fman) 
(By [Michael Herrmann](https://github.com/mherrmann)) dual pane file manager. 
It retains the `fman` plug-in API so existing plug-ins can be used
without changing their imports.

## Planning and Implementation Workflow

[Plan.md](Plan.md) is the task index. Each pending task has one standalone
document under [Plan](Plan/), and completed tasks move to [Done](Done/). Task
documents record design and review provenance, alternatives, runtime effects,
tests, acceptance criteria, implementation provenance, and validation results.

Repository-wide contribution and task-lifecycle requirements are defined in
[AGENTS.md](AGENTS.md). Completed user-visible work must also be reflected in
[CHANGELOG.md](CHANGELOG.md).

## Features

Significant additions compared with `fman`:

- **Search File Fuzzy:** Find files in the current folder or recursively using fuzzy or regular matching.
- **Extended Status Bar:** Press `Ctrl+S` to cycle through disabled, active-pane, and per-pane file statistics.
- **Sync Pane Location:** Send the inactive pane to the active pane's current folder from the Command Center.
- **Favorites:** Press `Ctrl+B` to search and manage saved folders; unavailable locations are reported without navigation.
- **New Empty File:** Press `Ctrl+N` to create an empty file without opening an editor.

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

## Tests and Packaging

```powershell
python build.py test
python build.py freeze
python build.py package
```

`run`, `test`, and `freeze` download the pinned x64 `7za.exe` from the official
7-Zip distribution when it is not already present under the Core plug-in.
These commands therefore require internet access on their first run.

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

See [UPSTREAM.md](UPSTREAM.md) for the upstream merge policy.