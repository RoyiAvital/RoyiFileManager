# RoyiFileManager

`RoyiFileManager` is a Windows only, portable fork of the [`fman`](https://github.com/mherrmann/fman) 
(By [Michael Herrmann](https://github.com/mherrmann)) dual pane file manager. 
It retains the `fman` plug-in API so existing plug-ins can be used
without changing their imports.

## Planning workflow

[Plan.md](Plan.md) is the task index. Each pending task has one standalone
document under [Plan](Plan/), and completed tasks move to [Done](Done/). Task
documents record design and review provenance, alternatives, runtime effects,
tests, acceptance criteria, implementation provenance, and validation results.

Repository-wide contribution and task-lifecycle requirements are defined in
[AGENTS.md](AGENTS.md). Completed user-visible work must also be reflected in
[CHANGELOG.md](CHANGELOG.md).

## Extended status bar

Press `Ctrl+S` to cycle the extended status bar between `Disabled`,
`Active pane`, and `Per pane`. The selected mode is saved immediately under
`UserSettings`. Directory counts and file sizes are calculated in a background
thread; disabling the feature stops status calculations entirely.

## Sync pane location

Run `Sync Pane Location` from the Command Center to navigate the inactive pane
to the active pane's current folder. The command does not change pane focus.

## Development

Install a conda package manager then create the environment:

```powershell
conda env create -f environment.yml
conda activate RoyiFileManager
python build.py run
```

The environment intentionally constrains PyQt to the 5.15 branch. Other
packages use compatibility bounds rather than patch pins, so recreating the
environment for a release selects their latest compatible versions. `freeze`
generates the Windows release lock when it is missing or older than
`environment.yml`. It can also be generated manually:

```powershell
conda-lock lock -f environment.yml -p win-64
```

## Tests and packaging

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