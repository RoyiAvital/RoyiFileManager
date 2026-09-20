# Find Files Panel

A docked file-name search panel backed by [`fd`](https://github.com/sharkdp/fd),
assigned to <kbd>Shift</kbd> + <kbd>F7</kbd>. Status: Implemented; packaged smoke unrun.

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
writing a search grammar or matcher. There is no pre-enumeration tree-size cap.
Optional Maximum results limits the search independently of table capacity;
unset means count all matches while keeping retained rows bounded.

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
- Streaming `--print0` output parsing, bounded table storage, exact completed
  counts, optional search limit, Stop,
  progress text, one runner at a time, Panel/Table lifecycle and stale-result
  rejection identical in policy to Search Files.
- Size and Modified columns filled by Python `os.stat` of collected rows
  (bounded by the row cap), with link metadata matching the selected follow mode.
- Delivery of `fd.exe` through the conda-forge `fd-find` package, bundled by
  PyInstaller with its notices, mirroring ripgrep.
- README, CHANGELOG, tests.
- User-approved forced 960 x 600 logical-pixel application minimum, with
  application-window test fixtures at or above that size.

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
  consumers. Additive Panel controls, Table count formatting and mixed-entry
  path roles are permitted for the requested inputs/results.

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
  The spec declares the binary; packaged runtime validation remains conditional
  on an explicitly requested build.

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

Compact `show_panel` bands; keep paired bounds together when reflowing:

| Row | Controls |
| --- | --- |
| 1 | Name Pattern, mode icons, Case, Full path, Extensions, Exclude, Type |
| 2 | Modification Date Start/End, File Size Min/Max with unit dropdowns, Max Results |
| 3 | Root on the left; traversal toggles and Search/Stop aligned right |

User approved using the available width to match Search Files' height. Both
measure 111 logical pixels at 1280/1440 widths; the refined Find Files panel
wraps to 183 at 960. Context dividers separate sections; controls share a
28-pixel height, with bottom-aligned rows and bounded text-field expansion.
The user then explicitly required a forced application minimum. Selected
960 x 600 logical pixels rather than 1100 x 700 for wider high-DPI compatibility,
without a screen-size fallback. The first-run/reset size stays 1280 x 800.
All application-window fixtures use at least 960 x 600; smaller standalone
widgets and result dialogs are not application windows. Native smoke skips
requested widths larger than the physical display's logical available width.

Max Results defaults to blank (`None`) and is session-only; blank means no
search limit. It does not remove the table safety limits. Tab and Shift+Tab
follow descriptor order through logical controls, skipping disabled inputs.
Search/Stop use the same icons, coloring, size and spacing as Search Files.
Stop stays enabled and red while idle; clicking it without a runner is a no-op.
The Git-branch toggle controls .gitignore; .fdignore remains always honored.

Defaults: Glob, Smart case, Files, Recursive on, Honor .gitignore on; Hidden,
Full path and Follow symbolic links off. Date/size bounds are blank. The
recursive icon is the sole depth control. Empty pattern matches all entries
passing other filters.

On narrow windows, wrap rows into labeled groups; never squeeze two bounds,
unit menus and action icons into overlapping cells. Calendar popups stay inside
the available screen and do not close the panel when interacting with them.

### Shared Control Additions

Current [descriptors](../src/main/python/fman/impl/ui/table_data.py) provide
TextField/Toggle/Choice/Label/Action, and Choice renders icon buttons, not a
dropdown. Add `Select`, `DateField`, `IntegerField` and `Separator` descriptors through
the existing [facade](../src/main/python/fman/impl/ui/facade.py) and
[fman.ui](../src/main/python/fman/ui.py); cover schema validation, snapshots,
update/enabled/focus behavior, reflow and notifications. These are additive
prerequisites for this plug-in.

- `Select`: labeled dropdown using the existing `DropDown` widget; plain unique
  option values. Use for case, type and size units, without Choice's 8-option cap.
- `DateField`: clearable `QDateEdit` with `calendarPopup=True` and ISO
  `yyyy-MM-dd` display. Blank returns `None`; the internal empty-state date
  is never exposed in snapshots. Each bound can be typed, selected or cleared
  independently. Opening a blank calendar shows the current month. Values
  crossing the UI boundary are `None` or ISO strings, never `QDate` objects.
- `IntegerField`: clearable nonnegative integer input/stepper; blank returns
  `None`. Use exact Python integer parsing and bounds, not QDoubleSpinBox or
  floating-point conversions. Do not rely on QSpinBox's signed 32-bit ceiling;
  values such as 5,000,000,000 bytes must be representable. Return `int`/`None`.
  Unit selectors disable with their associated blank bounds.
- `Separator`: unique ID, vertical divider attached to the following control;
  no value in snapshots and no value updates.

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
| Recursive off/on | Off: `--max-depth=1`; on: no depth flag. No separate depth input. |
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

Minimum and Maximum each have a clearable integer stepper and dropdown:
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
and result limits are session-only and preserved while the panel stays open. Validate
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
After child cleanup, cancellation takes precedence over generic transport errors:
a Stop or external cancellation that truncates a record reports `Stopped`, with
no transport-error reason. Without cancellation, truncated output remains `Error`.
Retain complete records already accepted in either case; never accept the fragment.

Emit `--max-results=N` only for an enabled Maximum results field. Count every
returned path but retain at most 10,000 rows / 16 MiB of Table text/payload,
reserving space for metadata. Once storage fills, discard additional paths
after validation/counting, without statting them. No sentinel or approximate
denominator is shown. fd 10.5.0 has no count option; an exact total requires a
successful complete traversal. Reaching an explicit search limit conservatively
marks the count incomplete, even when it might equal the full total. Stop/errors
also mark counts incomplete. Use `--show-errors` to report traversal warnings.
Any stderr warning, including one inaccessible folder with exit 0, marks the run
`Incomplete`: the total covers collected entries, not necessarily all matches.
Empty exit 0 is valid; nonzero exits report bounded stderr or a fallback error.

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
entry_path_column=0, base_path=root, modal=True, title='Find files')`. The additive
entry role accepts both files and folders; existing strict roles stay unchanged. Size
uses `fman.impl.status_bar.format_size` (the documented coupling Find Files
002 already uses); Modified uses `YYYY-MM-DD HH:MM` local time. Go To and Copy
Path come from the Table's path role; for folder rows Go To enters the folder
(Core `open_directory` behaviour), which is acceptable and documented.
`get_details` shows the absolute path. The Table's fuzzy filter narrows the
displayed rows without re-running `fd`.

Count text updates as the Table filter changes: `Showing xx / yy entries`, where
xx is visible retained rows and yy is the match count from the run. Append
`(Maximum table size reached)` when matches could not be retained. Completed
uncapped runs have exact totals; stopped, failed or search-limited runs append
the state and `total incomplete`. Never show a sentinel such as `10,001+`.
The additive `get_count_text(visible, retained)` callback preserves existing
consumers' default count text. Also keep the result summary in panel activity.

FindSession uses the existing Qt dispatcher and status-bar size formatter as
localized fork-private imports. Workers never construct or mutate widgets.

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
- **Six vertically separated filter rows**: left excess width unused. Three
  wrapping bands match Search Files' height at the default window width.
- **1100 x 700 or screen-capped minimum**: user required a hard minimum and
  allowed either 960 x 600 or 1100 x 700. Choose 960 x 600 to fit more high-DPI
  work areas. Screens smaller than the enforced minimum remain a limitation.
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
  pipe, counts all returned matches and collects at most `max_rows`, then queries retained
  metadata (one stat normally, two for a missing-target fallback). Memory is
  bounded by row and byte caps. Uncapped runs continue walking/counting after
  table storage fills. Follow links can expand the traversal beyond
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
- Window sizing: one static Qt minimum-size constraint, independent of plug-in
  use; no screen-change callbacks, timers or background work.

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
  output, byte/row caps, exact counting beyond capacity, incomplete-count labels,
  independent search limits, deterministic sorting
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
  matches; verify no pre-indexing cap, exact totals beyond table capacity, bounded
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
  retaining rows, not counting. Unset Maximum results counts all matches, with
  accurate final/filtered counters. In local smoke tests, Stop reaps
  fd within one second without blocking Qt. Blocked metadata calls do not cause
  stale publication or unlimited replacement workers.
- Results show Path, Size and Modified; Go To highlights the file in the pane;
  rows are sorted by path and filterable in the Table.
- Named preferences persist under UserSettings; query text and filter bounds
  remain session-only. Settings writes preserve unrelated keys.
- Panel matches Search Files in layout/style/interaction; calendar popups and
  integer/unit controls fit narrow/wide windows at all tested DPI scales.
- The spec includes bundled `fd.exe` and licences; frozen runtime smoke is
  required only when a build is explicitly requested, otherwise recorded unrun.
- Host changes are limited to additive Panel controls, mixed-entry path roles,
  count formatting, the explicitly approved application minimum and their tests;
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

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: User confirmed the layout and implementation, then approved optional
  Maximum results and exact completed counts with bounded storage. A seven-file
  fd probe returned three paths with `--max-results=3`, no total; `--count` was
  rejected. This supersedes early-stop/sentinel handling. Added count formatting
  and mixed-entry navigation to shared Table scope because strict file roles
  cannot enter matching folders. Gates cover counting, filtering and consumers.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Applied the user's compact-height request and explicit hard-minimum
  decision. Selected 960 x 600, removed undersized application-window fixtures,
  retained standalone widget/dialog tests. Native measurements match Search
  Files at 1280 width across 100/125/150/200% DPI. Reviewed additive contracts,
  lifecycle, exact counts and delivery declarations; focused gates pass with
  documented environment/platform skips.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Applied the user's panel refinement: explicit context dividers,
  blank inactive bounds instead of checkboxes, equal-height bottom-aligned
  controls, and recursive toggle without a Max depth input. Kept exact integer
  semantics, cancellation and existing Search Files layout unchanged.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the requested keyboard and layout follow-up. Use explicit
  logical tab order, descriptive labels/tooltips, blank Max Results on row two,
  and right-aligned toolbar controls matching Search Files. The user confirmed
  .fdignore remains always honored; no extra toggle or ignore-policy change.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Confirmed Stop parity also requires the enabled state, not just
  normal-mode icon equality. Retain Search Files' idle no-op behavior.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Accepted the implementation review's three follow-ups. A deterministic
  truncated-stream regression reproduced `Error` for both Stop and external
  cancellation; the uncanceled case correctly remains an error. Use `entries`
  for all result Types and document that even an exit-0 traversal warning makes
  the total incomplete. Keep existing warning semantics and child cleanup.

## Implementer

### 2026_09_20 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented the fd engine, compact panel, optional bounds and limits,
  exact match counters, cancellation and result navigation. Added provisional
  shared controls/table hooks, fd packaging declarations/notices, documentation
  and the hard application minimum. The focused 110-test gate passed with two
  expected skips; opt-in 200,100-file and native DPI smoke passed separately.

### 2026_09_20 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented clearable bounds and grouped panel layout. Existing Qt
  coverage now verifies typed dates, blank values, exact integers, equal
  heights and section containment. The 53-test focused gate and native smoke
  at 100/150/200% DPI passed.

### 2026_09_20 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented logical Tab traversal, labels/tooltips, uncapped default,
  second-row Max Results and right-aligned toolbar. Focused checks passed
  (62 passed, 2 expected skips); native keyboard, geometry and action-parity
  checks passed at 100% and 200% scaling.

### 2026_09_20 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Kept Stop enabled. Existing tests verify idle no-op, active button
  cancellation and native enabled-state/icon parity. All four FindFilesIT
  tests and the native smoke passed.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation matches the approved design; approved, released in
  v0.7.0. Re-ran offscreen: `test_find_files`, `test_ui_elements`,
  `test_portable`, `test_find_files_engine` (real fd 10.5.0) and
  `FindFilesIT`/`SearchFilesIT`/`TableIT`/`PanelIT`/`PublicUiIT`, 80 tests OK,
  2 documented skips. Verified: `arguments()` emits the tabulated flags, `--`
  before the pattern, cwd-only invocation, equals-form values and the 24,000
  UTF-16 unit check; inclusive date bounds via previous-day
  `23:59:59.999999999` and next-midnight `--changed-before` with local-boundary
  validation; exact decimal size units with unsigned 64-bit overflow rejection;
  `--ignore-vcs --no-require-git` / `--no-ignore-vcs` mapping; `./` prefix
  normalization and root-escape rejection in `Collector.accept`; bounded
  retention with exact counting; deterministic sort; link-aware `enrich` with
  missing-target fallback; single runner claim held through enrichment; stale
  generation checks in `completed`/`refresh_root`/`dispose`; settings copied
  under the resource lock. Declarations present: spec `fd.exe` data entry,
  `build.py` test path, `fd-find 10.5.0 h18a1a76_0` licences and README note,
  `Shift+F7` binding, `fman.ui` exports and PlugIn.md sections for the four
  new descriptors, `entry_path_column` and `get_count_text`, CHANGELOG entry,
  Plan/Done move and index. Probes: six Stop attempts on `%WINDIR%` all
  reported `Stopped`; a warm 270,927-record `WinSxS` run completed in 2.4 s
  including 10,000 stats, so Python per-record overhead is negligible (the
  13.9 s figure above includes tracemalloc and a cold fixture). Notes, not
  fixes: (1) `Runner.run` orders `except Cancelled` before `except Exception`,
  but a kill that leaves no complete record in the buffer makes `records()`
  raise `Incomplete fd output record` before `check()` runs, surfacing as
  `Error`; check `stopped`/`cancelled` in the generic handler for robustness.
  (2) `count_text` says `files` for every Type, including Folders; `entries`
  would match the progress text. (3) Any `--show-errors` warning (one denied
  folder) marks the whole count `Incomplete` - by design, worth a README line.
  Packaged smoke remains unrun as documented.

### 2026_09_20 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Addressed all three review suggestions. Cancellation now takes
  precedence over generic runner errors while preserving complete records;
  uncanceled malformed output still reports `Error`. Counts use `entries`, with
  mixed and folder-only Qt assertions. Documented warning-driven incomplete
  totals and added Unreleased fixes. Focused validation: 26 passed, 2 expected
  skips; native smoke passed. Historical review records remain unchanged.

## Validation Results

Environment: Windows, Python 3.14.7, PyQt5/Qt 5.15, installed fd 10.5.0. No new
environment/packages or intentional Registry writes. No clean, freeze, package
or full test suite was run.

Focused gate (108 passed, 2 expected skips):

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/SearchFiles', 'src/main/resources/base/Plugins/FindFiles', 'src/main/resources/base/Plugins/CalculateFileHash', 'src/main/resources/base/Plugins/Favorites') -join [IO.Path]::PathSeparator
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_find_files fman_unittest.test_ui_elements fman_unittest.impl.test_session fman_integrationtest.test_find_files_engine fman_integrationtest.test_qt.MainWindowIT fman_integrationtest.test_qt.FindFilesIT fman_integrationtest.test_qt.SearchFilesIT fman_integrationtest.test_qt.TableIT fman_integrationtest.test_qt.PublicUiIT fman_integrationtest.test_qt.PanelIT fman_integrationtest.test_qt.DockedPanelIT fman_integrationtest.test_qt.HashResultIT fman_integrationtest.test_qt.FavoritesManagerIT
python -m py_compile src/integrationtest/python/fman_integrationtest/favorites_smoke.py src/integrationtest/python/fman_integrationtest/search_files_smoke.py src/integrationtest/python/fman_integrationtest/find_files_smoke.py
git diff --check
```

- Skips: Windows symlink creation privilege unavailable; opt-in performance
  fixture disabled in the ordinary gate. Special native filesystem types and
  privileged link/cycle/outside-root traversal are not claimed as verified.
- Real fd tests cover pattern/case/ignore/depth/bounds, exact midnight edges,
  storage/search caps, errors and incomplete counts. Qt tests cover nullable
  fields, exact large integers, calendar Escape, wrapping, counts/filtering,
  file/folder navigation, focus, inactive-result locking and stale-result guards.
- Stop during blocked metadata retains the runner claim until cleanup; no
  replacement worker accumulation. All checked changed-file diagnostics clear.
- Hash centering fixtures now account for the existing screen-edge clamping
  when the hard-minimum main window exceeds the small offscreen display.
- Offscreen Qt reports missing bundled fonts and unsupported window-manager
  operations. Native checks below provide the visual/interaction evidence.

Large-tree gate (passed separately):

```powershell
$env:FIND_FILES_PERFORMANCE_TESTS = '1'
python -m unittest fman_integrationtest.test_find_files_engine.FindFilesEngineTest.test_large_tree_exact_count_and_bounded_storage
Remove-Item Env:FIND_FILES_PERFORMANCE_TESTS
```

Temporary 200,100-file tree, warm after creation, timings include tracemalloc:
100 sparse matches in 0.083 s; 200,100 matches counted with 10,000 retained in
13.863 s. Peak traced Python memory was 4,535,048 bytes (not total process RSS).
The retained rows passed the actual Table schema limits. Real fd Stop/reap took
0.001 s; blocked metadata cancellation was tested separately. Fixture creation,
both searches, cancellation and cleanup took 53.109 s.

Native smoke (passed at all four scales):

```powershell
$env:QT_QPA_PLATFORM = 'windows'
foreach ($scale in @('1', '1.25', '1.5', '2')) {
  $env:QT_SCALE_FACTOR = $scale
  $env:FIND_FILES_SMOKE_IMAGE = "target/find-files-$scale.png"
  python -m fman_integrationtest.find_files_smoke --isolated-plugins
  if ($LASTEXITCODE -ne 0) { throw "Native smoke failed at scale $scale" }
}
Remove-Item Env:QT_SCALE_FACTOR, Env:FIND_FILES_SMOKE_IMAGE
```

Verified real plug-in loading, Shift+F7 registration, preference persistence,
session-only inputs, full/filtered counters, result navigation and nonblank
icons. Captured and inspected native screenshots. Find Files/Search Files both
measure 111 logical pixels at 1280 width; Find Files wraps to 179 at 960.
All application-window requests are at least 960 x 600. At 200%, 1440 exceeds
this monitor's logical width and is explicitly skipped; 960/1280 pass. A final
200% rerun passed the strengthened non-elided section-label assertion.

Initial validation: unrestricted startup smoke encountered an unrelated leftover
`Plugins/SearchFileContent` folder whose `search_file_content.engine` is absent.
It was left untouched; isolated smoke loads Core, FindFiles, SearchFiles and
temporary Settings through the real loader. Accidental settings files from an
initial test-isolation mistake were removed before successful reruns. No frozen
executable/ZIP smoke or physical multi-monitor migration check was performed.

Follow-up (2026_09_20): removed the obsolete SearchFileContent initializer and
cache-only directories at the user's request. With `QT_QPA_PLATFORM=windows`,
`python -m fman_integrationtest.find_files_smoke` passed using normal plug-in
discovery, without isolation. The startup blocker is resolved; SearchFiles
retains the legacy command alias and settings fallback. No new tests were added.

### Panel Refinement (2026_09_20)

All 53 tests passed using the Python path and offscreen setup above:

```powershell
python -m unittest fman_unittest.test_find_files fman_unittest.test_ui_elements fman_unittest.test_portable.PluginApiCompatibilityTest fman_integrationtest.test_qt.FindFilesIT fman_integrationtest.test_qt.SearchFilesIT fman_integrationtest.test_qt.PublicUiIT fman_integrationtest.test_qt.PanelIT fman_integrationtest.test_qt.DockedPanelIT
```

The control test was also run directly after each edit:

```powershell
python -m unittest fman_integrationtest.test_qt.FindFilesIT.test_controls_optional_bounds_validation_and_wrapping
```

Native `python -m fman_integrationtest.find_files_smoke` passed with normal
plug-in discovery, `QT_QPA_PLATFORM=windows`, and `QT_SCALE_FACTOR` set to
1, 1.5 and 2. Screenshots checked at 960/1280/1440 logical widths; 1440 at 200%
was skipped because it exceeds this monitor's available logical width. The
refined panel measures 111 pixels high at 1280/1440 and 183 at 960. Captures
confirm visible section headings, no overlapping groups and 28-pixel controls.
Earlier height measurements above describe the initial implementation.

Checked diagnostics are clear. Existing offscreen font/window-manager warnings
remain non-failing. No full suite, freeze or packaging build was run.

### Keyboard and Layout Follow-up (2026_09_20)

Focused gate: 64 tests, 62 passed, 2 expected skips (link privileges and opt-in
performance fixture). Uses the Python path and offscreen setup above:

```powershell
python -m unittest fman_unittest.test_find_files fman_unittest.test_ui_elements fman_unittest.test_portable.PluginApiCompatibilityTest fman_integrationtest.test_find_files_engine fman_integrationtest.test_qt.FindFilesIT fman_integrationtest.test_qt.SearchFilesIT fman_integrationtest.test_qt.PublicUiIT fman_integrationtest.test_qt.PanelIT fman_integrationtest.test_qt.DockedPanelIT
```

Native `python -m fman_integrationtest.find_files_smoke` passed using
`QT_QPA_PLATFORM=windows` at 100% and `QT_SCALE_FACTOR=2`. Verified forward and
reverse Tab through every control, blank Max Results on reopening, row-two fit
at 1280/1440, toolbar edge alignment, and matching Search Files action icons,
dimensions, tooltips and spacing. Native heights remain 111 at 1280/1440 and
183 at 960. At 200%, 1440 exceeds the available logical screen and is skipped.
Screenshots, changed-file diagnostics and `git diff --check` were checked.
The full suite and packaging build were not run.

### Stop Button Parity (2026_09_20)

Passed using the existing Python path; the first two commands used offscreen
Qt and the native smoke used `QT_QPA_PLATFORM=windows`:

```powershell
python -m unittest fman_integrationtest.test_qt.FindFilesIT.test_controls_optional_bounds_validation_and_wrapping
python -m unittest fman_integrationtest.test_qt.FindFilesIT
python -m fman_integrationtest.find_files_smoke
```

All four panel tests passed, including idle no-op and active cancellation.
The native comparison includes enabled state and the corresponding icon mode;
Find Files now matches Search Files while idle. Diagnostics and diff checks
are clear. No full suite or packaging build was run.

### Implementation Review Follow-up (2026_09_20)

The first direct unittest invocation could not import `fman_unittest` because the
terminal lacked the repository Python path. Rerunning through `build._environment()`
reproduced two failures: Stop and external cancellation both returned `Error` for
a truncated record. The uncanceled case passed. After the fix all cases passed,
including retained complete records and child cleanup. A four-test intermediate
gate also passed: cancellation, table capacity, real process Stop and Qt counts.

Exact decisive commands:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_find_files.FindFilesTest.test_truncated_output_respects_cancellation'], env=build._environment()).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_find_files', 'fman_integrationtest.test_find_files_engine', 'fman_integrationtest.test_qt.FindFilesIT'], env=env).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'fman_integrationtest.find_files_smoke'], env=env).returncode)"
git diff --check
git diff --check -- CHANGELOG.md Done/FindFilesPanel.md src/main/resources/base/Plugins/FindFiles src/unittest/python/fman_unittest/test_find_files.py src/integrationtest/python/fman_integrationtest/test_find_files_engine.py src/integrationtest/python/fman_integrationtest/test_qt.py src/integrationtest/python/fman_integrationtest/find_files_smoke.py
```

Final focused gate: 28 tests, 26 passed and 2 expected skips (Windows link
privileges and opt-in large-tree performance). Includes real fd searches,
partial-record process termination, blocked metadata cancellation, exit-0
warnings/nonzero errors, and mixed/folder-only filtered counters. Native smoke
passed at 100% scaling and 960/1280/1440 widths with real plug-in discovery,
persistence, `entries` counts and navigation. Changed-file diagnostics are clear;
existing offscreen font/window-manager warnings remain non-failing. No full suite,
large-tree benchmark rerun, freeze or packaged smoke was performed.

The global diff check reported existing trailing whitespace at root README line 16,
outside this follow-up; it was left untouched. The scoped diff check covering every
follow-up file passed.
