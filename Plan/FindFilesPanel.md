# Find Files Panel

Status: Design; not approved for implementation. Coexists with
[Find Files 003](FindFiles003.md): the Everything-style query grammar keeps
`Ctrl+E`; this Panel tool exposes `fd` through controls on `Shift+F7`.

## Task

Add a bundled `FindFiles` plug-in with the Command Center command
**Find files with `fd`** (`find_files`). It opens a docked Panel, in the style
of [Search Files](../src/main/resources/base/Plugins/SearchFiles/search_files/__init__.py),
whose controls abstract the capabilities of [fd](https://github.com/sharkdp/fd):
name pattern in Glob / Literal / RegEx mode, case sensitivity, extensions,
exclusions, size and modification-date filters, file/folder type, depth, hidden
entries and ignore-file awareness. Results appear in the shared results Table
with Path, Size and Modified columns and the built-in Go To / Copy Path actions.

Motivation: the fuzzy picker (`Ctrl+F`) must stay instant and is therefore
capped at 50,000 entries and cannot host controls; Search Files is content
oriented and has no date/size filters. `fd` supplies a parallel, cancellable
walk with native metadata filters and regex, so a Panel can expose them without
writing a grammar or a matcher, and without a cap on the tree size.

## Scope

Included:

- Plug-in `Plugins/FindFiles/` with package `find_files`, command `find_files`
  (aliases `Find files with fd`, `Find files`), default binding `Shift+F7`
  (unbound today; adjacent to Search Files' `Alt+F7`). `Ctrl+E` and
  `Ctrl+Shift+E` remain reserved for Find Files 003.
- Panel controls and their `fd` mapping (Design). Query text is session-only;
  modes and toggles persist in `FindFiles.json` like Search Files.
- Streaming `--print0` output parsing, row cap with a `Limited` marker, Stop,
  progress text, one runner at a time, Panel/Table lifecycle and stale-result
  rejection identical in policy to Search Files.
- Size and Modified columns filled by Python `os.stat` of the *displayed* rows
  (bounded by the row cap), formatted like Find Files 002.
- Delivery of `fd.exe` through the conda-forge `fd-find` package, bundled by
  PyInstaller with its notices, mirroring ripgrep.
- README, CHANGELOG, tests.

Excluded:

- Content search (Search Files), fuzzy ranking (`Ctrl+F`), the pane filter bar
  and Flat View listing. Live search-as-you-type (explicit Search only in v1).
- Creation-date filters (`fd` has none), owner/attributes, `--exec` actions,
  symlink following, remote schemes (`file://` roots only).
- Changes to the public `fman` API or to `show_panel`/`show_table`.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. No
existing command, binding or setting changes. The plug-in is removable.

## Design

### Delivery: conda-forge package, not a download

Use the conda-forge `fd-find` package, exactly as ripgrep is delivered.
Verified on 2026_09_20: `environment.yml` lists `fd-find`, `conda-lock.yml`
pins `fd-find 10.5.0 h18a1a76_0` (win-64), the executable installs to
`sys.prefix/bin/fd.exe` (`fd 10.5.0`), and the package ships
`info/licenses/LICENSE-MIT` and `info/licenses/THIRDPARTY.yml`.

- [RoyiFileManager.spec](../RoyiFileManager.spec) copies
  `sys.prefix/bin/fd.exe` to `resources/Plugins/FindFiles/bin/fd.exe`, as it
  does for `rg.exe`.
- Copy the two licence files of the locked package into
  `Plugins/FindFiles/licenses/`, with a README note naming
  `fd-find 10.5.0 h18a1a76_0`, as Search Files does for `ripgrep 15.2.0`.
- Engine path resolution as in Search Files: bundled `bin/fd.exe` when frozen,
  `sys.prefix/bin/fd.exe` in source runs. No system `fd` on `PATH` is used.

Rationale versus the `7za.exe` download: the lock file already pins and hashes
the package, CI needs no network beyond conda, no custom download/retry/SHA
code is added to `build.py`, licences ship from the package metadata, and
upgrades are one lock regeneration. The 7-Zip download exists only because that
exact binary layout is not packaged; `fd-find` is.

### Plug-in layout

- `find_files/__init__.py` - command, settings snapshot, `FindSession`
  (Panel, Table, progress, persistence), metadata formatting.
- `find_files/engine.py` - `Options` validation, size/date grammar, argument
  builder, `Child`/`Runner` process handling, `--print0` parser. Pure Python
  where possible; no Qt.
- `FindFiles.json`, `Key Bindings (Windows).json`, `icons/` (Lucide SVGs, LFS
  like the existing plug-in icons), `licenses/`, `README.md`.

### Panel

`show_panel` rows (all descriptors from `fman.ui`):

| Row | Controls | `fd` |
| --- | --- | --- |
| 1 | `TextField pattern` "Name Pattern" (max_width 480); `Choice pattern_mode` Glob / Literal / RegEx (reuse Search Files' icons); `Toggle case_sensitive`; `Toggle full_path` "Match full path" | `--glob` / `--fixed-strings` / regex (default); `--case-sensitive` else `--ignore-case`; `--full-path` |
| 2 | `TextField extensions` "Extensions" (`pdf;txt`); `TextField exclude` "Exclude" (`;`-separated globs) | `-e pdf -e txt`; `-E <glob>` each |
| 3 | `TextField size` "Size" (`>1mb`, `<10k`, `1k..10m`, or fd's `+1m`/`-10k`); `TextField modified` "Modified" (`2d`, `3w`, `2024-06-01`, `2024-01-01..2024-06-30`, `>2024-01-01`, `<1h`) | `--size +1m --size -10m`; `--changed-within` / `--changed-before` |
| 4 | `Label root` (pane-side icon); `Toggle recursive` (default on); `Toggle hidden`; `Toggle ignore_files` "Respect .gitignore"; `Choice type` Files / Folders / Both; `Action search`; `Action stop` | `--max-depth 1` when off; `--hidden`; omit `--no-ignore` when on; `--type f` / `--type d` / none |

Fixed arguments: `--color never --print0 --no-follow --strip-cwd-prefix
--path-separator /`, run with `cwd=root`, plus `--max-results <max_rows + 1>`
to detect truncation. An empty pattern lists everything that passes the
filters. The size and date fields are parsed in Python into exact `fd`
arguments before spawning; invalid text is reported in the activity status
and nothing runs. Both fields accept `fd`'s native forms unchanged.

Search disables the form, shows `Searching: N files, T s` through
`set_activity_status(get_text=...)`, and Stop kills the process. The Panel
persists `pattern_mode`, `case_sensitive`, `full_path`, `recursive`, `hidden`,
`ignore_files` and `type` through the Search Files save pattern (copy loaded
dict, `settings_resource` lock, `save_json`, publish).

### Engine

Mirror Search Files' [Child/Runner](../src/main/resources/base/Plugins/SearchFiles/search_files/engine.py):
`subprocess.Popen` with `CREATE_NO_WINDOW`, stderr tail thread, `kill()` on
Stop/close, `command_fits` 24,000 UTF-16 units check, single runner via
`settings_resource('FindFiles runner').try_claim()`. Read stdout in chunks,
split on `\0`, decode UTF-8 with `surrogateescape`, join to `root` for the
URL. Stop at `max_rows` rows and mark the result `Limited`. Exit code 0 with no
output is an empty result, not an error; a non-zero code with stderr text is
reported as the fd message.

Because `fd`'s parallel output order is nondeterministic, rows are sorted by
casefolded relative path before display.

After the walk, the worker `stat`s each collected row (`follow_symlinks=False`)
for size and `st_mtime_ns`; failures leave blank cells. This is bounded by
`max_rows` (default 10,000), not the tree.

### Results

`show_table(num_columns=3, columns_header=('Path', 'Size', 'Modified'),
file_path_column=0, base_path=root, modal=True, title='Find files')`. Size
uses `fman.impl.status_bar.format_size` (the documented coupling Find Files
002 already uses); Modified uses `YYYY-MM-DD HH:MM` local time. Go To and Copy
Path come from the Table's path role; for folder rows Go To enters the folder
(Core `open_directory` behaviour), which is acceptable and documented.
`get_details` shows the absolute path. The Table's fuzzy filter narrows the
displayed rows without re-running `fd`.

## Alternatives

- **Download `fd.exe` like `7za.exe`**: adds a second download/hash/retry path
  and hand-maintained licences for a binary conda-forge already packages; the
  ripgrep precedent shows the package route works end to end. Rejected.
- **Everything-style query grammar (Find Files 003)**: a typed grammar in the
  modal picker serves users who prefer one query line; this Panel serves users
  who prefer explicit controls and unbounded trees. Both remain planned as
  separate tools with separate bindings; neither replaces the other.
- **Extend Search Files with `fd` filters**: mixes two engines in one Panel and
  makes content search depend on `fd`. Keep two focused tools sharing the UI
  services; a later task may pre-filter Search Files with `fd` if wanted.
- **Live search per keystroke**: re-spawns `fd` on every change; acceptable on
  small trees, laggy on large ones. Explicit Search in v1; a debounced live mode
  can be added later without design change.
- **Python `os.scandir` walk instead of `fd`**: adequate to about 100k entries
  but single-threaded, no ignore-file support, and regex cannot be cancelled on
  the Qt thread. `fd` is the reason this tool has no tree-size cap.
- **Metadata from `fd --list-details`**: it shells out to GNU `ls`, absent on
  Windows, and produces locale-dependent text. Rejected; Python `stat` on
  displayed rows is bounded and exact.

## Runtime Effects

- Startup: registers one command and one binding; no I/O, timers or process.
- Idle: none. Opening the Panel spawns nothing until Search.
- Search: one `fd` process, multithreaded walk owned by `fd`; Python reads a
  pipe and builds at most `max_rows` rows, then performs up to `max_rows`
  `stat` calls on the worker. Memory is bounded by the row cap. Progress text
  updates at most five times per second through the host's status timer.
- Cancellation: Stop, Panel close, pane navigation and plug-in unload kill the
  process; late output is discarded by generation checks. A blocked filesystem
  call inside `fd` ends when the process dies.
- No-op path: with the plug-in unused there is no feature work; removing the
  plug-in directory removes the command, binding and bundled executable use.

## Tests

Focused commands from the repository root (after the plug-in exists):

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/FindFiles') -join [IO.Path]::PathSeparator
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_find_files
python -m unittest fman_integrationtest.test_find_files_engine
python -m unittest fman_integrationtest.test_qt.FindFilesIT
```

- Unit (`test_find_files`): argument builder for every control combination;
  size and date grammar (friendly and native forms, ranges, invalid input,
  boundary units); `--print0` parser with UTF-8, non-BMP and invalid bytes,
  split chunks and a trailing partial record; sorting; `Limited` detection;
  settings snapshot validation and migration-free defaults; metadata
  formatting including blank cells.
- Engine integration (`test_find_files_engine`): real `fd.exe` on a temporary
  tree: glob/literal/regex, extensions, exclude, size and date filters, hidden
  and `.gitignore` handling, type filter, depth off, cap and `Limited`, Stop
  mid-walk kills the process, exit-code/stderr mapping, non-ASCII names.
  Skip with a clear message when `fd.exe` is absent.
- Qt (`FindFilesIT` in the shared harness): real loader registers the
  command and `Shift+F7`; Panel controls, disabled form during a run, progress
  text, Stop, Table columns and Go To on a file and a folder, Panel close
  cancels, pane navigation refreshes the root, settings persistence, unload.
- Build declarations: spec contains the `fd.exe` data entry, `build.py` test
  path includes the plug-in, `conda-lock.yml` contains `fd-find`, licences
  present and non-empty.
- Manual/frozen: open on a large tree (>200k files), verify no cap and Stop
  latency; 100/150% DPI; extracted ZIP runs `fd` from the bundle with no
  development Python or `fd` on `PATH`.

## Implementation Steps

1. Copy the `fd-find 10.5.0` licence files into the plug-in; add the spec
   data entry and `build.py` test path. (Environment and lock already updated.)
2. Implement `engine.py` (grammar, arguments, parser, `Child`/`Runner`) with
   unit tests; run `test_find_files` after the first edit.
3. Add the real-`fd` engine integration tests.
4. Implement the command, settings and `FindSession` (Panel, Table, metadata,
   persistence, lifecycle); add `FindFilesIT`.
5. Icons, `FindFiles.json`, key binding, plug-in README, main README feature
   line, CHANGELOG `Added` entry.
6. Run focused tests, frozen smoke; record results; move the document to
   `Done/`, update `Plan.md`.

## Acceptance Criteria

- **Find files with fd** appears in the Command Center and on `Shift+F7`; every
  Panel control changes the `fd` arguments as tabulated and invalid size/date
  text is rejected before spawning.
- Searching a tree with more than 100,000 entries completes without a cap
  other than the displayed-row limit; Stop ends the process within one second.
- Results show Path, Size and Modified; Go To highlights the file in the pane;
  rows are sorted by path and filterable in the Table.
- Toggles and modes persist under `UserSettings`; query text does not.
- The frozen application runs the bundled `fd.exe` with no external
  dependency; licences ship with it.
- No `src/main/python/fman` change; Search Files, the fuzzy picker and the pane
  filter behave exactly as before; focused tests pass.

## Reviewers

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Designed an `fd`-backed Find Files Panel mirroring Search Files'
  Panel/Table/Runner architecture. Chose conda-forge `fd-find` delivery over a
  download, following the ripgrep precedent. Proposed superseding Find Files 003
  and taking its reserved `Ctrl+E`. Open for user decision: the `Ctrl+E`
  binding, retiring Find Files 003, and whether folder rows need a distinct
  Go To behaviour.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: User decision applied: `Ctrl+E`/`Ctrl+Shift+E` stay reserved for
  the Everything-based Find Files 003, which remains a separate planned tool.
  This Panel binds `Shift+F7`, verified unbound across all bundled key-binding
  files and adjacent to Search Files' `Alt+F7`. Removed the supersession
  wording; folder-row Go To behaviour remains open.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: User added `fd-find` to `environment.yml`, installed it and
  regenerated the lock. Verified `fd-find 10.5.0 h18a1a76_0` in
  `conda-lock.yml`, `sys.prefix/bin/fd.exe` reporting `fd 10.5.0`, and
  `LICENSE-MIT` plus `THIRDPARTY.yml` in the package's `info/licenses`.
  Closed the delivery verification items; step 1 now covers only licences,
  spec and test path.
