# Find Files Panel

A docked file-name search panel backed by [`fd`](https://github.com/sharkdp/fd),
assigned to <kbd>Shift</kbd> + <kbd>F7</kbd>. Status: Design; not implemented.

## Task

Add a bundled `FindFiles` plug-in with the Command Center command
**Find files with `fd`** (`find_files`). It opens a docked Panel, in the style
of [Search Files](../src/main/resources/base/Plugins/SearchFiles/search_files/__init__.py),
whose controls abstract the capabilities of [`fd`](https://github.com/sharkdp/fd):
name pattern in Literal / Glob / Regex mode, Sensitive / Insensitive / Smart
case selection, extensions, exclusions, integer size bounds, optional start/end
modification dates, entry type, recursion, hidden entries, `.gitignore` handling
and optional symlink following. Results appear in the shared results Table
with Path, Size and Modified columns and the built-in Go To / Copy Path actions.

Motivation: the fuzzy picker (`Ctrl+F`) must stay instant and is therefore
capped at 50,000 entries and cannot host controls; Search Files is content
oriented and has no date/size filters. `fd` supplies a parallel, cancellable
walk with native metadata filters and regex, so a Panel can expose them without
writing a search grammar or matcher. There is no pre-enumeration tree-size cap;
the search stops when the displayed-result limit is reached.

## Scope

Included:

- Plug-in `Plugins/FindFiles/` with package `find_files`, command `find_files`
  (aliases `Find files with fd`, `Find files`), default binding `Shift+F7`
  (unbound today; adjacent to Search Files' `Alt+F7`). `Ctrl+E` and
  `Ctrl+Shift+E` remain reserved for Find Files 003.
- Panel controls and their `fd` mapping (Design). Query text is session-only;
  modes and toggles persist in `FindFiles.json` like Search Files.
- Nullable start/end date pickers, integer size bounds with unit dropdowns,
  three-way case selection, a type dropdown and optional symlink following.
  Add the missing plain control descriptors to the shared Panel API; preserve
  existing descriptors and Search Files behavior.
- Streaming `--print0` output parsing, row cap with a `Limited` marker, Stop,
  progress text, one runner at a time, Panel/Table lifecycle and stale-result
  rejection identical in policy to Search Files.
- Size and Modified columns filled by Python `os.stat` of collected rows
  (bounded by the row cap), with link metadata matching the selected follow mode.
- Delivery of `fd.exe` through the conda-forge `fd-find` package, bundled by
  PyInstaller with its notices, mirroring ripgrep.
- README, CHANGELOG, tests.

Excluded:

- Content search (Search Files), fuzzy ranking (`Ctrl+F`), the pane filter bar
  and Flat View listing. Live search-as-you-type (explicit Search only in v1).
- Creation/access-date filters (the pinned `fd` filters modification time),
  owner/attributes, `--exec`/`--exec-batch` actions, output-format/terminal options,
  arbitrary extra CLI arguments and remote schemes (`file://` roots only).
- A complete frontend for every `fd` switch. All eleven requested search/filter
  controls are included; additional patterns (`--and`), custom ignore files,
  prune rules, thread tuning and multiple roots are outside this version.
- Breaking changes to the public `fman` API or existing `show_panel`/`show_table`
  consumers. Additive Panel controls are permitted for the requested inputs.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
provisional `fman.ui` extension gains additive descriptors without changing
existing controls/consumers. No existing command, binding or setting changes.
The plug-in is removable.

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
  The spec change is planned, not a claim that it already bundles `fd`.

Rationale versus the `7za.exe` download: the lock file already pins and hashes
the package, CI needs no network beyond conda, no custom download/retry/SHA
code is added to `build.py`, licences ship from the package metadata, and
upgrades are one lock regeneration. The 7-Zip download exists only because that
exact binary layout is not packaged; `fd-find` is.

### Plug-in layout

- `find_files/__init__.py` - command, settings snapshot, `FindSession`
  (Panel, Table, progress, persistence), metadata formatting.
- `find_files/engine.py` - `Options` validation, size/date conversion, argument
  builder, `Child`/`Runner` process handling, `--print0` parser. Pure Python
  where possible; no Qt.
- `FindFiles.json`, `Key Bindings (Windows).json`, `icons/` (Lucide SVGs, LFS
  like the existing plug-in icons), `licenses/`, `README.md`.

### Panel

Match the existing Search Files Panel, not a separate settings dialog: same
dock, theme, aligned labels, field widths, 28 px icon controls with 16 px Lucide
icons, selected-state treatment, pane-side root icon, activity status, Search/
Stop actions, Escape close and Tab/Shift+Tab pane bridging. Reuse pattern-mode
icons but replace Search Files' hard-coded case-insensitive tooltips with
accurate tooltips for this engine. Do not add explanatory text inside the form.

Proposed `show_panel` rows; keep paired bounds together when reflowing:

| Row | Controls |
| --- | --- |
| 1 | Name Pattern text (max width 480), Literal / Glob / Regex icon choice, case dropdown, Full path toggle |
| 2 | Extensions text, Exclude text, Type dropdown |
| 3 | Modified: optional Start date picker, optional End date picker |
| 4 | Size: optional Minimum integer + unit dropdown, optional Maximum integer + unit dropdown |
| 5 | Root label, Recursive / Hidden / Honor .gitignore / Follow symbolic links toggles, optional Maximum depth, Search / Stop icons |

Defaults: Glob, Smart case, Files, Recursive on, Honor .gitignore on; Hidden,
Full path and Follow symbolic links off. Both date/size bounds and maximum
depth are unset. Empty pattern matches all entries passing other filters.

On narrow windows, wrap rows into labeled groups; never squeeze two bounds,
unit menus and action icons into overlapping cells. Calendar popups stay inside
the available screen and do not close the panel when interacting with them.

### Shared Control Additions

Current [descriptors](../src/main/python/fman/impl/ui/table_data.py) provide
TextField/Toggle/Choice/Label/Action, and Choice renders icon buttons, not a
dropdown. Add `Select`, `DateField` and `IntegerField` descriptors through
the existing [facade](../src/main/python/fman/impl/ui/facade.py) and
[fman.ui](../src/main/python/fman/ui.py); cover schema validation, snapshots,
update/enabled/focus behavior, reflow and notifications. These are prerequisites,
not controls the current host already supplies.

- `Select`: labeled dropdown using the existing `DropDown` widget; plain unique
  option values. Use for case, type and size units, without Choice's 8-option cap.
- `DateField`: `QDateEdit` with `calendarPopup=True`, ISO `yyyy-MM-dd` display,
  optional enable checkbox and calendar button. Unchecked means `None`, not a
  minimum-date sentinel. Each bound enables/clears independently; retain its
  last selected date within the open session. Values crossing the UI boundary
  are `None` or validated ISO date strings, never `QDate` objects.
- `IntegerField`: nonnegative integer input/stepper with optional enable
  checkbox. Use exact Python integer parsing and bounds, not QDoubleSpinBox or
  floating-point conversions. Do not rely on QSpinBox's signed 32-bit ceiling;
  values such as 5,000,000,000 bytes must be representable. Return `int`/`None`.
  Unit selectors disable with their associated bounds. Maximum depth uses the
  same control with minimum 1.

Construct and mutate widgets only on the Qt thread. Preserve existing public
descriptor contracts and styling; no plug-in-created widgets on worker threads.

### Filter Mapping

| Requested feature | `fd 10.5.0` mapping and semantics |
| --- | --- |
| Literal / Glob / Regex | `--fixed-strings` / `--glob` / `--regex`. Literal is substring matching, Glob whole-name matching, Regex uses fd's regex engine. No Python regex interpretation. |
| Modification date | Start/end day conversion below; no flag for an unset bound. |
| Size | Inclusive minimum `--size=+<bytes>b`, maximum `--size=-<bytes>b`; no flag for an unset bound. |
| Hidden off/on | `--no-hidden` / `--hidden`; independent of ignore rules. Use fd's hidden-entry semantics, not an extra Python filter. |
| Honor .gitignore off/on | `--no-ignore-vcs` / `--ignore-vcs --no-require-git`. On honors rules even outside a Git worktree; off bypasses VCS rules. `.ignore`, `.fdignore` and fd's own global ignore rules remain active in both modes. Do not use the broader `--no-ignore` under this label. |
| Recursive off/on | Off: `--max-depth=1`; on: no depth flag unless Maximum depth is set. Disable depth input while off, retaining its session value. |
| Exclude | One `--exclude=<glob>` per entry; exclusions are independent of the main pattern mode and still apply with gitignore disabled. |
| Sensitive / Insensitive / Smart | `--case-sensitive` / `--ignore-case` / neither. Smart lets fd determine case from uppercase characters in the pattern; do not lowercase user input. |
| Type dropdown | All entries (no flag), Files (`f`), Folders (`d`), Symbolic links (`l`), Executables (`x`), Empty files (`e` + `f`), Empty folders (`e` + `d`), Sockets (`s`), Named pipes (`p`), Block devices (`b`), Character devices (`c`), using repeated `--type`. Non-native Windows types may have no matches. |
| Follow symbolic links off/on | `--no-follow` / `--follow`. Delegate traversal, type matching and cycle handling to fd; on can traverse targets outside the root. Preserve returned link paths rather than resolving/deduplicating aliases. |
| Extensions | One `--extension=<ext>` per value; multiple values are ORed. Normalize one leading dot, preserve compound extensions (`tar.gz`), reject empty internal tokens and wildcards/separators. fd can match extension-suffixed directories too; the Type filter controls this. |
| Full path | Off matches the entry name; on adds `--full-path` and matches the absolute path, as fd defines it. |

Extension/exclusion inputs use semicolon-delimited entries; trim delimiter
whitespace, not pattern contents, and omit a completely empty field. Preserve
spaces within values. Exclusions allow `\;` for a literal semicolon; otherwise
preserve backslashes for fd's glob parser. This is a list parser, not shell
syntax; malformed lists fail before launching.

### Date Range

Start and End are independently optional: None/None, start-only, end-only or
both. No restriction to today; past and future dates are allowed throughout
the supported calendar/conversion range. Invalid/unrepresentable boundary
dates or Start > End disable Search and report a field-specific error, never
silently clamp. Equal dates select the whole single day.

Use local calendar days: include modification times from Start 00:00 inclusive
through the end of End inclusive, expressed as `[start, midnight_after_end)`.
Compute the next *calendar day*, not an elapsed 24 hours, so DST days work.
Reject ambiguous/nonexistent local boundary instants rather than guessing.

fd's date comparisons are strict. Emit `--changed-within` with one nanosecond
before Start midnight, serialized as the preceding calendar day's
`23:59:59.999999999`; emit `--changed-before` with midnight after End. For
example, Start=End=2026-01-15 emits:

```text
--changed-within "2026-01-14 23:59:59.999999999"
--changed-before "2026-01-16 00:00:00"
```

Each timestamp is a single argv element; quotes above illustrate grouping only.
Use integer/calendar calculations, not float timestamp rounding. Fractional
calendar syntax is verified on the pinned binary; fractional `@epoch` syntax
was rejected. No relative-duration text grammar or post-cap Python date filter.
Test supported range edges and DST transitions before implementation approval.

### Size Range

Minimum and Maximum each have an enable checkbox, integer stepper and dropdown:
**Bytes / Kilo Bytes / Mega Bytes / Giga Bytes**. Use decimal multipliers
1 / 1,000 / 1,000,000 / 1,000,000,000, matching fd's `b/k/m/g` semantics;
tooltips state the byte multiplier. Binary KiB/MiB/GiB are not implied.

Multiply exactly into bytes and emit byte-unit flags. Bounds are inclusive;
equal bounds mean exact size. Zero is a valid enabled value, distinct from
None. Reject negatives, fractions, exponents, overflow beyond unsigned 64-bit
bytes, and minimum > maximum after conversion. Changing units reinterprets the
visible integer (1 MB becomes 1 GB), without a rounding conversion. Size filters
retain fd's file-size semantics; folder metadata size is not recursive content
size. The result Size cell remains blank for directories.

### Settings and Run State

Persist only modes/toggles/type and unit choices: `pattern_mode`, `case_mode`,
`full_path`, `recursive`, `hidden`, `honor_gitignore`, `follow_symlinks`, `type`,
`min_size_unit`, `max_size_unit`. Pattern, extensions, excludes, date/size bounds
and depth are session-only and preserved while the panel stays open. Validate
loaded values against the defaults above and preserve unknown settings keys.
Use Search Files' copy/lock/save/publish pattern; no autosave on every date digit.

Search snapshots immutable plain options and the current local root, disables
all editable fields and Search, and leaves Stop enabled. Activity status uses
Search Files' style with `Searching: N entries, T s`; use entries because folders
and links can match. Validation failures identify the field and launch nothing.
Owner close, root change or unload invalidates the generation and cancels work;
implement these guards explicitly rather than assuming a path subscription alone
already cancels a Search Files run. On completion/error/cancel restore enabled
states according to each optional bound and Recursive setting.

### Engine

Mirror Search Files' [Child/Runner](../src/main/resources/base/Plugins/SearchFiles/search_files/engine.py):
`subprocess.Popen` with `CREATE_NO_WINDOW`, stderr tail thread, `kill()` on
Stop/close, `command_fits` 24,000 UTF-16 units check, single runner via
`settings_resource('FindFiles runner').try_claim()`. Resolve only the bundled/
environment binary. Use an argv list with `shell=False`, `cwd=root`, fixed
`--color=never --hyperlink=never --print0 --strip-cwd-prefix=always
--path-separator=/`, filter arguments, then `--`, pattern. Do not append a
positional root: fd rejects it with `--strip-cwd-prefix`. The captured cwd is
the root; explicit `--` and equals-form filter values protect leading dashes.

Read stdout in chunks, split on `\0`, decode UTF-8 and convert returned paths
relative to root. Normalize an optional `./` prefix: the pinned fd still emits
it for dash-prefixed names despite `--strip-cwd-prefix=always`. Do not allow
absolute/parent-escaping output records to become navigation targets.
Preserve unusual valid names; malformed/nonrepresentable
records produce an explicit diagnostic, not silent byte corruption.

Use `--max-results=<max_rows + 1>`; hold at most `max_rows` rows plus one sentinel.
Only an observed extra match marks the result `Limited`; exactly the cap is
not automatically truncation. Bound buffered records and total Table text/payload
to the host's 16 MiB limit, leaving space for metadata. Stop and mark Limited
on a byte cap too. The default/hard row maximum is 10,000, matching Table limits.
No need to enumerate the rest of the tree once limited. Empty exit 0 is a valid
empty result. Nonzero exits report bounded stderr or a fallback exit-code error;
cancellation is not misreported as a process failure.

Because fd's parallel order is nondeterministic, sort collected rows by
`(casefolded_relative_path, relative_path)` before display. A limited subset can
differ across runs; sorting it does not make it the first N paths globally.

After collection the worker stats each retained row using the selected follow
mode, retrying a missing target without following so broken links can remain
visible. Failures leave metadata blank; do not remove successful fd matches.
Cancellation/generation checks run between calls. Display metadata can change
after fd evaluated its filters; do not silently apply a second filter to newer
values. No Qt access or extra per-row worker. Keep the runner claim through
metadata enrichment so repeated searches cannot accumulate blocked stat work.

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
- **Python walk/matcher instead of `fd`**: would require implementing ignore,
  pattern and traversal semantics already provided by the pinned engine.
  Reject without claiming an unmeasured Python tree-size threshold.
- **Raw date/size syntax fields**: concise for CLI users but do not satisfy the
  requested date pickers and integer/unit controls. Use structured bounds;
  arbitrary CLI input remains out of scope.
- **Custom plug-in-only Qt form**: avoids descriptor work but duplicates Panel
  layout, focus, state and lifecycle code. Prefer additive shared controls.
- **Map Honor .gitignore to `--no-ignore`**: bypasses unrelated ignore files too.
  Use the narrower VCS flags and document the independent hidden/exclude rules.
- **Metadata from `fd --list-details`**: it shells out to GNU `ls`, absent on
  Windows, and produces locale-dependent text. Rejected; Python `stat` on
  displayed rows is bounded and exact.

## Runtime Effects

- Startup: normal plug-in/command/binding registration only; no search-specific
  filesystem walk, metadata scan, timer or process. Settings are read on opening.
- Idle: none. Opening the Panel spawns nothing until Search.
- Search: one `fd` process, multithreaded walk owned by `fd`; Python reads a
  pipe and collects at most `max_rows` rows plus a sentinel, then queries retained
  metadata (one stat normally, two for a missing-target fallback). Memory is
  bounded by row and byte caps. Follow links can expand the traversal beyond
  the root; fd owns cycle/error handling. Progress text
  updates at most five times per second through the host's status timer.
- Cancellation: Stop, Panel close, pane navigation and unload terminate/reap
  the child and discard stale output. Request cancellation immediately on the
  UI thread; process waits and pipe joins must not block it. A blocked Python
  metadata stat cannot be forcibly interrupted; reject its eventual result and
  keep the single-runner claim until cleanup, rather than start unlimited work.
- Persistence: save only changed preferences under UserSettings using existing
  bounded/coalesced settings work. Date/size editing causes no search process.
- No-op path: with the plug-in unused there is no feature work; removing the
  plug-in directory removes the command, binding and bundled executable use.

## Tests

Focused commands from the repository root (after the plug-in exists):

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/FindFiles', 'src/main/resources/base/Plugins/SearchFiles') -join [IO.Path]::PathSeparator
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_find_files
python -m unittest fman_unittest.test_ui_elements
python -m unittest fman_integrationtest.test_find_files_engine
python -m unittest fman_integrationtest.test_qt.FindFilesIT fman_integrationtest.test_qt.PanelIT fman_integrationtest.test_qt.PublicUiIT fman_integrationtest.test_qt.SearchFilesIT
```

- Unit (`test_find_files`): every control/flag mapping and combined filters;
  leading-dash patterns/values, empty patterns, extension/exclusion lists,
  captured cwd-only invocation and command-length rejection. None/one/two date
  bounds, equal days, leap days, past/future dates, inverted ranges, supported
  calendar edges and local DST boundary validation. Exact integer conversions
  in all four units, zero/unset, equal bounds, mixed units, >32-bit values and
  overflow. NUL parser split chunks, non-BMP/unusual names, malformed/truncated
  output, byte/row caps, sentinel-only Limited detection, deterministic sorting
  within a subset, settings snapshots and link-aware/blank metadata.
- Shared UI tests: new descriptor validation, JSON-compatible snapshots,
  `update` values/enabled states, no duplicate change notifications, exact large
  integers, calendar popups, None clearing and existing descriptor compatibility.
- Engine integration (`test_find_files_engine`): real `fd.exe` on a temporary
  tree: all three pattern/case modes (including uppercase Smart), literal regex
  characters, compound/multiple extensions, multiple excludes, byte equality
  boundaries and dates exactly before/at/after both midnights. Hidden and ignore
  controls independently, `.gitignore` inside/outside a Git worktree and
  `.ignore` still active with VCS ignoring off. Every type mapping, recursion
  off and numeric depth, followed/non-followed/broken links, link cycles and
  targets outside root. Unsupported native types and unavailable link privileges
  are explicit skips, not claimed coverage. Cap/bytes, Stop, root-change/unload
  cancellation, stderr/exit handling and non-ASCII names.
  Skip with a clear message when `fd.exe` is absent.
- Qt (`FindFilesIT` in the shared harness): real loader registers the
  command and `Shift+F7`; Panel controls, disabled form during a run, progress
  text, Stop, all eleven features, three-way case/type dropdowns, unit changes,
  independent date/size bounds, calendar keyboard/mouse/clear behavior, no child
  on edit/invalid input, Table/Go To, close/navigation/unload cancellation and
  persistence/session-only distinctions. Regression-run SearchFilesIT and PanelIT
  because the shared form changes. Cover narrow layouts and Tab/Shift+Tab focus.
- Build declarations: spec contains the `fd.exe` data entry, `build.py` test
  path includes the plug-in, `conda-lock.yml` contains `fd-find`, licences
  present and non-empty.
- Manual/performance: use a >200k-entry tree with both sparse matches and >10k
  matches; verify no pre-indexing cap, Limited for truncated results, bounded
  memory and responsive Stop during walk/enrichment. Native 100/125/150/200% DPI
  and narrow/wide windows: labels, bounds, menus and popup calendars do not
  overlap. Compare screenshots beside Search Files for style consistency.
- Frozen smoke only when the user requests a build: extracted ZIP runs bundled
  fd without development Python/fd on PATH, including date/unit controls and
  licensing. Otherwise record packaged validation as unrun.

### Review Evidence (2026_09_20)

- Installed `sys.prefix/bin/fd.exe --version` reports 10.5.0; `--help` verifies
  flags, case defaults, type options, decimal units and VCS-ignore distinction.
- Temporary-file probes executed through `python -`/`subprocess.run`: exact
  Start midnight is excluded by an unadjusted `--changed-within`; next midnight
  is excluded by `--changed-before`. Fractional preceding-day calendar cutoff
  includes Start midnight. Fractional `@epoch` input was rejected.
- Fixtures at 0, 1, 1000, 1001 and 2000 bytes confirmed inclusive `+1000b` and
  `-1000b`, including exact size with both flags.
- A non-repository fixture verified `--no-require-git` honors `.gitignore`;
  `--no-ignore-vcs` restores its excluded file while `.ignore` still applies.
- Initial probes with `--strip-cwd-prefix` plus a positional root failed;
  cwd-only invocation succeeded. The argument builder must retain that fix.
- Dash-prefixed result names retain `./`; parser normalization is required.
  Case fixtures must use distinct names, not just a casing change that Windows
  treats as the same path. Final `python -` temporary-fixture assertions passed
  for same-day/start-only/end-only dates, inclusive/equal sizes, decimal KB,
  independent hidden/VCS/other-ignore behavior, leading dashes and all case modes.
- Shared source inspection confirmed calendar/integer/dropdown descriptors do
  not yet exist. This is design validation, not implemented UI, live symlink,
  DST, cancellation or frozen-package verification.

## Implementation Steps

1. Copy the `fd-find 10.5.0` licence files into the plug-in; add the spec
   data entry and `build.py` test path. (Environment and lock already updated.)
2. Add the three shared control descriptors/widgets and focused schema/PanelIT
  regressions; verify existing Search Files layout and behavior unchanged.
3. Implement `engine.py` (structured bounds, arguments, parser, `Child`/`Runner`) with
   unit tests; run `test_find_files` after the first edit.
4. Add real-fd integration tests for mappings, exact boundaries and independent
  toggles; resolve date-range/platform gaps before wiring the panel.
5. Implement the command, settings and `FindSession` (Panel, Table, metadata,
   persistence, lifecycle); add `FindFilesIT`.
6. Icons, `FindFiles.json`, key binding, plug-in README, main README usage and
  CHANGELOG `Added` entry with explicit public API compatibility. Document unit,
  date, ignore and follow semantics; record additive provisional UI controls.
7. Run focused tests and native UI smoke; frozen smoke only on request. Record
  outcomes/gaps; move the document to Done only after acceptance, update Plan.md.

## Acceptance Criteria

- **Find files with fd** appears in the Command Center and on `Shift+F7`; every
  one of the eleven requested filters is visible and maps to fd as specified.
- Start/End independently support None or a calendar selection; both selected
  days are inclusive, including exact midnight. Size uses exact integer inputs
  and the four named decimal units. Invalid/overflowed ranges launch nothing.
- Sensitive/Insensitive/Smart are distinct, Type is a dropdown, and Follow
  symbolic links, Hidden, Recursive and Honor .gitignore are independent toggles.
- Searching >100,000 entries has no pre-enumeration cap; row/byte limits stop
  collection with an accurate Limited marker. In local smoke tests, Stop reaps
  fd within one second without blocking Qt. Blocked metadata calls do not cause
  stale publication or unlimited replacement workers.
- Results show Path, Size and Modified; Go To highlights the file in the pane;
  rows are sorted by path and filterable in the Table.
- Named preferences persist under UserSettings; query text and filter bounds
  remain session-only. Settings writes preserve unrelated keys.
- Panel matches Search Files in layout/style/interaction; calendar popups and
  integer/unit controls fit narrow/wide windows at all tested DPI scales.
- The frozen application runs the bundled `fd.exe` with no external
  dependency; licences ship with it.
- Host changes are limited to additive Panel control support and its tests;
  Search Files, the fuzzy picker and the pane filter behave exactly as before.
  Focused tests pass.

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

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Revised all eleven requested controls to structured date/size inputs,
  three-way case, type dropdown and link following while preserving Search Files
  styling. Identified missing shared descriptors, strict date boundaries, overly
  broad ignore mapping, result-cap ambiguity and the cwd/strip-prefix conflict.
  Verified selected fd 10.5.0 semantics with temporary fixtures; expanded tests
  and documented remaining UI/platform gates. Design only; no feature implemented.
