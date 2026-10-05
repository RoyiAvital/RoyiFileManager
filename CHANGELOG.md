# Changelog

Notable implemented changes to the application are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- QuickView PDF preview with continuous page scrolling, page navigation, Fit
  Page, Fit Width and zoom. A bundled pypdfium2/PDFium helper isolates rendering
  failures and timeouts; page rendering and caching are bounded.
- Plug-in API: `fman.ui.show_quick_list`, a Qt-free blocking multi-select list.
  Items can carry a metadata line; title, hint and metadata are sortable with
  `Ctrl+F1`…`Ctrl+F10`, and the sort can be saved. `Ctrl+I` inverts and
  `Ctrl+Shift+A` clears the selection. An `on_open` handle (`QuickListHandle`)
  reads its state, replaces items, focuses or closes it. Tab moves between a
  modeless list and the docked Panel.

### Changed

- Favorites Manager uses `show_quick_list` and `show_panel` and no longer
  imports Qt. It shows an `Added` position and sorts by Name, Path or Added with
  `Ctrl+F1`–`Ctrl+F3` instead of the sort drop-down. Enter or Go To opens one
  chosen favorite; the Delete key no longer deletes (use the Delete button).
- QuickTable text and column filters match ASCII text without per-character
  case folding, which makes filtering large result tables faster.

### Removed

- Plug-in API: the Qt widget exports `QuickList`, `Panel`, `IconButton`,
  `TextButton`, `DropDown` and `JsonSettings` were removed from `fman.ui`.
  Migrate to `show_quick_list`, `show_panel` controls and `load_json`/`save_json`.

### Fixed

- Resetting window geometry now keeps the saved placement cleared through
  shutdown, so the next launch uses the default size and position.
- The application could crash with an access violation when exiting, while
  Python tore down PyQt objects. After background threads and exit handlers
  finish, the process now exits without that teardown.

## [0.13.1] - 2026-10-04

This release focuses on performance. Name sort keys are now built in native
code. Refreshing an unchanged folder no longer re-sorts or resets the
table. Large folders load and refresh faster and the UI stays responsive
while they do.
Rendering time is now close to its lower bound. _RoyiFileManager_ should be
competitive with the fastest file managers available for Windows.

### Changed

- Name-column sort keys are built in C (`_fsparser.natural_keys`, same
  extension as the directory parser): 94 ms to 7 ms for 200k short names and
  515 ms to 67 ms for 200k long names, identical ordering (verified against the
  Python `natural_key` over every Unicode code point).
- Refreshing a folder whose contents did not change no longer re-sorts, resets
  the table or drops marks, the rename editor or a drag in progress; cells are
  repainted and the usual completion notifications are still sent.
- The projection worker yields to the UI thread every ~16 ms instead of
  every 4 ms (`sleep(0)` was measured and rejected: it does not reliably hand
  the GIL to the UI thread).
- The row map a projection carries covers only the cursor and marked entries
  the view will restore (full map above eight entries), saving ~14 ms and
  ~10 MB per sort, filter keystroke and refresh of a 200k-row pane.

Results on the _test suite_ (milliseconds, medians of three fresh processes,
native Qt, warm cache):

| Measurement                                           |   0.13.0 |  0.13.1 |   Target |
|-------------------------------------------------------|---------:|--------:|---------:|
| `pane.load.large` first paint (200k, long names)      |      759 | **262** |    < 500 |
| `refresh.large` unchanged refresh, no marks           |     ~356 |     123 |          |
| `refresh.large` unchanged refresh, all marked         |     ~356 |     128 |          |
| `filter.large` substring query paint                  |      137 |     115 |          |
| `filter.large` UI heartbeat gap, typical query        |       11 |      17 |     ≤ 16 |
| `filter.large` UI heartbeat gap, worst query          |       23 |      38 |     ≤ 16 |

### Performance

Results of the performance test suite per version. Run time in [ms], lower is better.

| Test                            |   0.9.0 |   0.9.3 | 0.10.3 | 0.13.0 | 0.13.1 |
|---------------------------------|--------:|--------:|-------:|-------:|-------:|
| Pane Load - Small Folder        |   42.23 |   35.20 |  33.93 |  37.52 |  37.02 |
| Pane Load - Large Folder        | 1001.54 |  964.31 | 958.23 | 758.64 | 266.27 |
| Filter Bar - Small Folder       |    8.96 |    8.69 |   8.79 |  10.88 |   9.77 |
| Filter Bar - Large Folder       |  332.17 |  331.28 | 338.27 | 364.34 | 289.53 |
| Fuzzy Find - Small Folder       |    4.57 |    4.55 |   7.17 |   5.28 |   4.86 |
| Fuzzy Find - Large Folder       |  408.47 |  407.95 | 441.02 | 357.29 | 354.73 |
| Fuzzy Find (Recursive)          |   91.68 |   91.05 |  91.91 |  92.54 |  91.28 |
| QuickView Images - Small Folder |  122.09 |  122.61 | 122.04 | 121.09 | 116.37 |
| QuickView Images - Large Folder |  123.29 |  121.14 | 135.86 | 119.46 | 120.62 |
| QuickView Text - Small Folder   |       - |       - | 133.03 | 129.55 | 132.58 |
| QuickView Text - Large Folder   |       - |       - | 129.47 | 132.35 | 131.50 |
| Selections - Small Folder       |   15.67 |   15.24 |  15.35 |  16.18 |  15.79 |
| Selections - Large Folder       |   88.18 |   87.85 |  88.36 |  89.65 |  87.64 |
| Selections Readback             | 1994.44 | 1974.51 |  73.78 |  69.86 |  65.65 |
| Navigation                      |    7.17 |    7.36 |   7.17 |   7.05 |   6.97 |
| Refresh / Selection             |  581.97 |  592.84 | 585.17 | 355.99 |  67.59 |

[CelebA](https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html) folder with about 200,000 entries. Lower is better.

| Measurement                | Ver. 0.8.0  | Ver. 0.8.1  | Ver. 0.9.0  | Ver. 0.9.2  | Ver. 0.13.0 | Ver. 0.13.1 |
|----------------------------|-------------|-------------|-------------|-------------|-------------|-------------|
| First Populated Pane Paint | 8.949 [s]   | 5.663 [s]   | 0.583 [s]   | 0.506 [s]   | 0.257 [s]   | 0.112 [s]   |
| Metadata Loading Complete  | 17.786 [s]  | 11.498 [s]  | 0.571 [s]   | 0.494 [s]   | 0.244 [s]   | 0.100 [s]   |
| Post Paint Qt Commit Work  | 2.765 [s]   | 1.282 [s]   | 0 [s]       | 0 [s]       | 0 [s]       | 0 [s]       |
| Settled Working Memory     | 771.1 [MiB] | 771.3 [MiB] | 165.6 [MiB] | 167.4 [MiB] | 160.3 [MiB] | 145.5 [MiB] |

> [!NOTE]
> * Version `0.13.1` added native `C` natural sort keys, an unchanged-refresh path without re-sorting or a table reset, a per-projection row map limited to the entries the view restores and a once-per-frame worker yield cadence.
> * Version `0.13.0` added a native `C` directory parser and a validation free snapshot fast path for `NTFS`/`ReFS` folders.
> * Versions `0.10.x` optimized the existing code and remove the slower legacy paths.
> * Version `0.9.x` is the 1st version with the new architecture (_Snapshot Architecture_) which is an order of magnitude faster than `0.8.1`.
> * Version `0.8.1` had an improved version of the `fman` architecture (About 30% faster than `0.8.0`).
> * Version `0.8.0` and earlier versions use the `fman` architecture and performance.

## [0.13.0] - 2026-10-04

This release focuses on performance. It replaces a Python code with native code
for parsing the file system chucked data. It greatly improves the rendering 
time of large folders and the UI responsivity while parsing the data.

### Added

- Native NTFS directory parser (`src/main/c/fsparser.c`, abi3 extension,
  Git LFS binary paired with its source by `src/main/c/fsparser.sha256`):
  the local Windows scanner parses `FileIdExtdDirectoryInfo` batches in C and
  builds the pane snapshot through a validation-free `Listing` reserved for
  that scanner. Post-kernel scan of a 202,603-entry folder drops from 275 ms
  to 22 ms (1M entries: 1419 ms to 122 ms); link follow-up, cancellation
  points and results are identical to the previous Python loop, which is kept
  only as the reference the tests compare against. `build.py test`, `freeze`
  and `package` verify the source/binary pairing and fail on a mismatch.

### Performance

Results on the _test suite_:

| Test                            |   0.9.0 |   0.9.1 |   0.9.2 |   0.9.3 |  0.10.0 |  0.10.1 |  0.10.2 | 0.10.3 | 0.13.0 |
|---------------------------------|--------:|--------:|--------:|--------:|--------:|--------:|--------:|-------:|-------:|
| Pane Load - Small Folder        |   42.23 |   42.78 |   44.66 |   35.20 |   37.20 |   39.10 |   33.25 |  33.93 |  37.52 |
| Pane Load - Large Folder        | 1001.54 | 1014.82 |  978.07 |  964.31 |  956.75 |  971.12 |  975.83 | 958.23 | 758.64 |
| Filter Bar - Small Folder       |    8.96 |    9.21 |    8.70 |    8.69 |    8.84 |    9.28 |    8.80 |   8.79 |  10.88 |
| Filter Bar - Large Folder       |  332.17 |  331.48 |  333.62 |  331.28 |  335.02 |  332.78 |  332.76 | 338.27 | 364.34 |
| Fuzzy Find - Small Folder       |    4.57 |    4.52 |    4.51 |    4.55 |    4.53 |    4.51 |    4.51 |   7.17 |   5.28 |
| Fuzzy Find - Large Folder       |  408.47 |  379.09 |  389.25 |  407.95 |  416.37 |  421.48 |  439.31 | 441.02 | 357.29 |
| Fuzzy Find (Recursive)          |   91.68 |   91.09 |   91.12 |   91.05 |   91.06 |   91.78 |   91.39 |  91.91 |  92.54 |
| QuickView Images - Small Folder |  122.09 |  120.89 |  120.60 |  122.61 |  120.78 |  121.67 |  121.21 | 122.04 | 121.09 |
| QuickView Images - Large Folder |  123.29 |  128.92 |  125.64 |  121.14 |  123.83 |  136.21 |  131.20 | 135.86 | 119.46 |
| QuickView Text - Small Folder   |       - |       - |       - |       - |  132.81 |  132.11 |  133.05 | 133.03 | 129.55 |
| QuickView Text - Large Folder   |       - |       - |       - |       - |  132.65 |  131.57 |  131.73 | 129.47 | 132.35 |
| Selections - Small Folder       |   15.67 |   15.64 |   15.40 |   15.24 |   15.38 |   15.56 |   15.55 |  15.35 |  16.18 |
| Selections - Large Folder       |   88.18 |   88.37 |   88.94 |   87.85 |   87.42 |   87.53 |   87.51 |  88.36 |  89.65 |
| Selections Readback             | 1994.44 | 1987.26 | 1967.05 | 1974.51 | 1946.02 | 1980.19 |   72.84 |  73.78 |  69.86 |
| Navigation                      |    7.17 |    7.20 |    7.17 |    7.36 |    7.15 |    7.14 |    7.06 |   7.17 |   7.05 |
| Refresh / Selection             |  581.97 |  581.73 |  582.82 |  592.84 |  594.40 |  578.61 |  573.50 | 585.17 | 355.99 |

[CelebA](https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html) folder with about 200,000 entries. Lower is better.

| Measurement                | ver. 0.8.0  | ver. 0.8.1  | ver. 0.9.0  | ver. 0.9.2  | ver. 0.13.0 |
|----------------------------|-------------|-------------|-------------|-------------|-------------|
| First Populated Pane Paint | 8.949 [s]   | 5.663 [s]   | 0.583 [s]   | 0.506 [s]   | 0.257 [s]   |
| Metadata Loading Complete  | 17.786 [s]  | 11.498 [s]  | 0.571 [s]   | 0.494 [s]   | 0.244 [s]   |
| Post Paint Qt Commit Work  | 2.765 [s]   | 1.282 [s]   | 0 [s]       | 0 [s]       | 0 [s]       |
| Settled Working Memory     | 771.1 [MiB] | 771.3 [MiB] | 165.6 [MiB] | 167.4 [MiB] | 160.3 [MiB] |

> [!NOTE]
> * Version `0.13.0` added a native `C` directory parser and a validation free snapshot fast path for `NTFS`/`ReFS` folders.
> * Versions `0.10.x` optimized the existing code and remove the slower legacy paths.
> * Version `0.9.x` is the 1st version with the new architecture (_Snapshot Architecture_) which is an order of magnitude faster than `0.8.1`.
> * Version `0.8.1` had an improved version of the `fman` architecture (About 30% faster than `0.8.0`).
> * Version `0.8.0` and earlier versions use the `fman` architecture and performance.

## [0.12.0] - 2026-10-04

This release focuses on the `QuickTable` UI element and defines its API and
rationale. The features that present results in it were revised: _Search Files_,
_Find files with fd_ and _Verify checksum file_.
`QuickTable` lets the user narrow the results with a text filter and a filter per
column.
In _Search Files_, the new **Extended** mode extends
[`ripgrep`](https://github.com/burntsushi/ripgrep) with filtering by date and size.

### Added

- Search Files **Extended** mode (tooltip "Extended metadata mode"): Size and
  Date Modified columns read once per returned file after ripgrep, plus a
  substring/quoted-phrase AND filter over File Path and Snippet. The toggle
  persists as `extended`; off mode is unchanged.
- Typed QuickTable columns via `fman.ui.QuickTableColumn`: text, file/folder
  name, file/folder/entry path, date and numeric kinds with natural,
  chronological and numeric sorting. Date and numeric cells take raw values;
  the host formats them (ISO 8601 dates, `12,345 B` sizes). Missing values sort
  last.
- QuickTable header icons: a sort arrow on the sorted column and a filter funnel
  on filterable columns. The funnel, Alt+Down or **Filter This Column...** opens
  a menu with date/number operators, byte units, Clear Filter, Clear All Filters
  and sort commands.
- `show_quick_table(truncated=...)`: truncated tables show a `truncated` note
  beside the row count.
- Find Files results sort and filter Size and Modified by value.

### Changed

- **Breaking plug-in API:** the results table is now **QuickTable**, a
  buttonless, blocking table for narrowing a static set:
  `show_quick_table(*, columns, rows, pane=None, title='', summary='',
  modal=True, text_filter='fuzzy', base_path=None, truncated=None)`.
  <kbd>Enter</kbd> returns the input positions of the visible rows, Escape
  returns `None`; Ctrl+Enter and double-click Go To. Migration from `show_table`:
  - Rename `show_table` / `TableColumn` / `TableRow` to `show_quick_table` /
    `QuickTableColumn` / `QuickTableRow`.
  - Describe columns with `QuickTableColumn(label, kind)` instead of
    `num_columns`, `columns_header` and the `*_path_column` indices; navigation
    follows the kind. `text_filter` replaces `fuzzy`.
  - Pass `rows` directly (no `get_rows`, row IDs or values); pass raw
    numbers/epoch nanoseconds in Date/Numeric cells. Optional
    `QuickTableRow(targets=...)` supplies absolute navigation paths per column
    when the displayed text differs from the real path (replaces `resolve_path`).
  - Removed: `owner`, `panel`, `TableHandle`/refresh, `TableAction`, `get_menu`,
    `get_background_menu`, `get_details`, `on_activate`, `on_closed`,
    `get_count_text`, `resolve_path` and `close_on_navigate`.
- Search Files, Find Files and Verify checksum file results: Enter closes the
  results; Go To is Ctrl+Enter or double-click.
- Table cells containing tabs, such as indented Search Files snippets, no longer
  render as an ellipsis.
- Verify checksum file shows every retained result in a non-modal table (problems
  only when the display limit is exceeded); the Show all results / Show only
  mismatches menus are gone.
- Find Files and Search Files show the search root and run summary above the
  results.
- QuickTable cell menus always offer the column's Copy action and filter commands.
- Find Files shows Modified as ISO 8601 with the UTC offset.
- Natural name sorting moved to a host helper shared by Core and QuickTable.

### Removed

- The Per pane mode of the Extended Status Bar, whose footers below each pane did
  not match the rest of the interface. Ctrl+S now toggles between Disabled and
  Active pane. A saved `"mode": "dual"` in `Status Bar.json` is invalid and
  falls back to Disabled. The theme selector `.statusbar-pane[active="true"]`
  was removed; themes that use it are ignored for that rule.

### Documentation

- PlugIn.md and UIElements.md document QuickTable: signature, keys, column
  kinds, the filter menu, `text_filter` and truncation status. The Search Files
  README documents Extended mode. Checksum, Find Files and Search Files docs
  describe the results keys; the checksum screenshot shows the results table.
- New Plug-ins documentation page **UI Elements**: the rationale, API and a
  screenshot of QuickSearch, QuickList, QuickTable, Panel and OutputTextBox.
  The screenshot generator captures the element-only images.
- Search and Find documents the results table of Search Files and Find Files:
  keys, sorting, the filter box, column filters and Go To, with a results
  screenshot for each.

## [0.11.0] - 2026-10-03

This release integrates the [Everything search engine](https://www.voidtools.com) for fast indexed file search.  
Together with fuzzy matching, filename search and content search, it gives the application a flexible suite of tools for finding files.

### Added

- Everything Search: Ctrl+E searches explicitly indexed local folders with
  Everything syntax, match highlights, modification dates and sizes. Manage
  Everything database folders opens shared roots in a pane with Name/Path columns,
  filtering, sorting, safe bulk removal and F5/drop additions. It replaces the
  old Remove folder command, retains offline roots and confirms parent replacement.
  Add favorite folders remains a command and imports local favorite folders in one batch without
  changing Favorites. Every folder-list update normalizes paths and removes
  duplicates and covered children. An isolated portable instance starts lazily,
  serializes folder updates and stops when no roots remain. Opening the manager
  does not start Everything or probe its roots. Runtime state stays under UserSettings;
  the user's unnamed Everything instance is untouched.
- Source run, test and freeze commands automatically provision hash-verified
  Everything 1.4.1.1032 x64 portable files. A reviewed redistribution license is
  included in the repository instead of fetched from a mutable URL. Frozen packages include
  both and the plug-in's Python dependencies; packaging verifies the portable
  files without downloading an installer or SDK DLL.

## [0.10.3] - 2026-10-03

This release brings the Files Checksum feature to generate and validate checksum files.

### Added

- Bundled ChecksumFiles plug-in with Generate checksum file and Verify
  checksum file commands, twelve algorithms including native BLAKE3, SHA256 defaults,
  recursive selection handling, staged publication and standalone problem-first
  results. Verification uses the highlighted supported manifest, otherwise the
  first in case-insensitive filename order. Normal application builds include
  its ABI-pinned private BLAKE3 dependency and license; no separate installation
  is needed. Supports navigated junction roots while refusing links below them.
  Results keep the summary above the table; result-row and empty-background
  menus switch between all results and mismatches without a synthetic row.
  See [usage and compatibility](src/main/resources/base/Plugins/ChecksumFiles/README.md).
- Optional `get_background_menu` callback in `fman.ui.show_table` for table-wide
  actions, including empty or fully filtered results. Existing row-menu callbacks
  are unchanged.

### Performance Retest - 2026-10-03

Fresh measurements of every release from `0.9.0` through `0.10.2` and current
application source `cb51127d46b9`. All eight versions used one harness, interpreter,
environment and shared fixtures, with alternating version order and three fresh
processes per workload. All 312 native repetitions and 120 companion search
algorithm measurements passed. These results do not replace earlier tables.

All timings are in milliseconds. Small folders contain 256 files, large folders
200,000 files, and recursive search uses 50,000 files. Each individual case uses
the **median of its three repetitions**, not the minimum or maximum repetition.
The row summaries follow the regular sixteen-row report:

- **Pane Load and QuickView Images:** the case median.
- **Filter Bar and Fuzzy Find:** the largest (slowest) query median.
- **QuickView Text, Selections, Navigation and Refresh / Selection:** the mean
  of their case medians. Refresh / Selection averages 16 case medians.
- **Selections Readback:** the largest (slowest) of ten case medians.

Values use two decimal places; `-` means text preview was unavailable in that
release. All other values, including historical readback, are measured.

| Test                            |   0.9.0 |   0.9.1 |   0.9.2 |   0.9.3 |  0.10.0 |  0.10.1 |  0.10.2 | Unreleased |
|---------------------------------|--------:|--------:|--------:|--------:|--------:|--------:|--------:|-----------:|
| Pane Load - Small Folder        |   42.23 |   42.78 |   44.66 |   35.20 |   37.20 |   39.10 |   33.25 |      33.93 |
| Pane Load - Large Folder        | 1001.54 | 1014.82 |  978.07 |  964.31 |  956.75 |  971.12 |  975.83 |     958.23 |
| Filter Bar - Small Folder       |    8.96 |    9.21 |    8.70 |    8.69 |    8.84 |    9.28 |    8.80 |       8.79 |
| Filter Bar - Large Folder       |  332.17 |  331.48 |  333.62 |  331.28 |  335.02 |  332.78 |  332.76 |     338.27 |
| Fuzzy Find - Small Folder       |    4.57 |    4.52 |    4.51 |    4.55 |    4.53 |    4.51 |    4.51 |       7.17 |
| Fuzzy Find - Large Folder       |  408.47 |  379.09 |  389.25 |  407.95 |  416.37 |  421.48 |  439.31 |     441.02 |
| Fuzzy Find (Recursive)          |   91.68 |   91.09 |   91.12 |   91.05 |   91.06 |   91.78 |   91.39 |      91.91 |
| QuickView Images - Small Folder |  122.09 |  120.89 |  120.60 |  122.61 |  120.78 |  121.67 |  121.21 |     122.04 |
| QuickView Images - Large Folder |  123.29 |  128.92 |  125.64 |  121.14 |  123.83 |  136.21 |  131.20 |     135.86 |
| QuickView Text - Small Folder   |       - |       - |       - |       - |  132.81 |  132.11 |  133.05 |     133.03 |
| QuickView Text - Large Folder   |       - |       - |       - |       - |  132.65 |  131.57 |  131.73 |     129.47 |
| Selections - Small Folder       |   15.67 |   15.64 |   15.40 |   15.24 |   15.38 |   15.56 |   15.55 |      15.35 |
| Selections - Large Folder       |   88.18 |   88.37 |   88.94 |   87.85 |   87.42 |   87.53 |   87.51 |      88.36 |
| Selections Readback             | 1994.44 | 1987.26 | 1967.05 | 1974.51 | 1946.02 | 1980.19 |   72.84 |      73.78 |
| Navigation                      |    7.17 |    7.20 |    7.17 |    7.36 |    7.15 |    7.14 |    7.06 |       7.17 |
| Refresh / Selection             |  581.97 |  581.73 |  582.82 |  592.84 |  594.40 |  578.61 |  573.50 |     585.17 |

Measured on the same development PC with Windows 11 build 26300, Python 3.14.7,
Qt 5.15.15 / PyQt 5.15.11, Balanced power policy, warm filesystem caches and a
1280 x 800 viewport at 1x DPI. Each historical version uses its original
application sources but the currently installed dependencies. QuickView uses
the same v2 fixtures for all releases; only unavailable text cases are omitted.
Local source exports, raw repetitions and immutable records are retained under
`UserSettings/Performance/Retest20261003/`. Harness fingerprint:
`ff0f8831ec3030fac471a10f4db86f2520a711ca5307ffe3d492cd57e4b4983a`.
See [reproduction instructions](DEVELOPMENT.md#historical-performance-retesting).

#### Regression Analysis

- **Refresh / Selection:** the previous approximately 56% increase from `0.9.2`
  to `0.10.2` did not recur: 582.82 versus 573.50 ms in this run. The Windows bulk
  scanner is byte-identical across all eight versions; projection, update and
  Qt commit functions have identical syntax trees. The `0.9.2` natural-sort
  correction predates the apparent increase. The `0.10.1` unknown-identity check
  optimization does not add work to the unchanged-listing fast path, and the
  `0.10.2` readback optimization is outside the refresh timing endpoint.
- **Fuzzy Find:** the full-run medians still differ, so a separate nine-pair,
  alternating, fresh-process `0.9.2`/`0.10.2` UI comparison was run. The slowest
  query measured **355.09 versus 356.48 ms**, a **0.4%** difference; observed
  ranges overlap (351.88-361.03 and 354.59-361.53 ms). All seven queries returned
  equal row counts. These supplementary results are not substituted into the
  full-run table.
- The only substantive matcher rewrite in this range is `0.9.3` (`3f122db`):
  reuse identical name/path normalization and stream ranked candidates into
  the bounded result heap. Scoring and subsequence functions are unchanged.
  A separate nine-pair in-memory comparison measured the difficult no-match
  query at **369.83 versus 370.18 ms** (0.09%); the other two tested queries were
  slightly faster. Ordered results and highlights matched for all seven catalog
  queries over 200,000 entries. No later matcher change explains the large gap.
- **Conclusion:** the earlier large increases are not reproduced as stable
  code-caused regressions. Run conditions substantially affect these timings;
  the specific environmental cause is not established. Three-sample overview
  differences alone are not regression verdicts. Existing duplicate name/path
  scoring remains an optimization opportunity, not an explanation for a newly
  introduced slowdown. No application optimization was applied during this retest.

## [0.10.2] - 2026-10-02

The focus of this release is an optimization of selections and solving few edge cases bugs.

This release speeds up retrieval of the selected file and metadata list. Readback now has a
dedicated measurement, separate from selection responsiveness.

| Test                            | Version: `0.9.0` | Version: `0.9.2` | Version: `0.10.1` | Version: `0.10.2` |
|---------------------------------|------------------|------------------|-------------------|-------------------|
| Pane Load - Small Folder        | 44.14 [ms]       | 42.37 [ms]       | 37.26 [ms]        | 33.54 [ms]        |
| Pane Load - Large Folder        | 1030.26 [ms]     | 983.77 [ms]      | 998.90 [ms]       | 985.29 [ms]       |
| Filter Bar - Small Folder       | 9.72 [ms]        | 10.08 [ms]       | 9.34 [ms]         | 9.05 [ms]         |
| Filter Bar - Large Folder       | 332.28 [ms]      | 328.40 [ms]      | 329.17 [ms]       | 330.71 [ms]       |
| Fuzzy Find - Small Folder       | 4.67 [ms]        | 4.82 [ms]        | 4.60 [ms]         | 4.66 [ms]         |
| Fuzzy Find - Large Folder       | 350.86 [ms]      | 349.39 [ms]      | 425.89 [ms]       | 463.02 [ms]       |
| Fuzzy Find (Recursive)          | 89.82 [ms]       | 89.72 [ms]       | 90.21 [ms]        | 90.15 [ms]        |
| QuickView Images - Small Folder | 109.73 [ms]      | 111.81 [ms]      | 118.97 [ms]       | 121.36 [ms]       |
| QuickView Images - Large Folder | 118.74 [ms]      | 115.70 [ms]      | 120.15 [ms]       | 120.92 [ms]       |
| QuickView Text - Small Folder   | -                | -                | -                 | 128.44 [ms]       |
| QuickView Text - Large Folder   | -                | -                | -                 | 128.44 [ms]       |
| Selections - Small Folder       | -                | -                | 15.12 [ms]        | 15.73 [ms]        |
| Selections - Large Folder       | -                | -                | 97.87 [ms]        | 86.39 [ms]        |
| Selections Readback             | ~2481.61 [ms]    | ~2481.61 [ms]    | 2481.61 [ms]      | 67.65 [ms]        |
| Navigation                      | 6.79 [ms]        | 6.80 [ms]        | 6.86 [ms]         | 7.40 [ms]         |
| Refresh / Selection             | 482.95 [ms]      | 471.10 [ms]      | 739.78 [ms]       | 733.36 [ms]       |

Versions `0.10.1` and earlier use the unoptimized readback implementation.
`~` marks estimates based on the `0.10.1` baseline, not measured results;
`-` marks unavailable results. Benchmark definitions and fixtures changed between
runs, limiting direct comparisons.
See [measurement details](Done/CodeReview006.md#expanded-regular-report-and-grouping-2026-10-02).

### Changed

- Reduced Qt overhead when retrieving selected file lists, preserving selection
  membership and ordering without changing selection commands.
  A same-environment, same-harness comparison reduced readback of 200,000 selected
  files from **2,481.61 ms to 67.65 ms** (97.3% less time, about **36x** faster).
  Both medians use three samples. See [readback results](Done/CodeReview006.md).

- Simplified clipboard, Explorer and Recycle Bin command handling without changing
  their existing behavior.

### Fixed

- QuickView's Find field now forwards modified Enter shortcuts such as Alt+Enter
  (Properties) to the source pane, while preserving local Find and text editing.
- Compare directories now reports selected visible differences, distinguishes
  unselectable differences from matching names, and keeps exact-name comparison.
- Packing multiple entries at a drive root suggests `C.zip` instead of `C:.zip`;
  nameless roots use `archive.zip`, and trailing separators preserve folder names.
- Delete continuation prompts now use the task dialog, preventing automatic
  progress popups over the question and setting an explicit Yes default.

## [0.10.1] - 2026-10-01

This version focuses on code cleanup, removing unused features inherited from
`fman` and remaining non Windows support. The codebase is focused and easier 
to understand and maintain.

### Removed

- Removed unused macOS/Linux runtime branches and bundled settings; the application
  remains Windows-only, with archive URLs and network-drive support preserved.
- Removed the GitHub plug-in installer and installation-revision hints. Existing
  plug-ins still load; manual installation uses `UserSettings/Plugins/Third-party/<PluginName>/`.
- Removed telemetry/event history. Retained tours use bounded, session-only state.
- Removed legacy Column `get_str`/`get_sort_value` methods and the bundled columns'
  filesystem constructor arguments. Plug-ins must implement snapshot `text` and
  `keys`; there is no compatibility shim. See [Column migration](PlugIn.md#columns).

### Changed

- Renamed **Show processes** to **Show OS' processes** in Command Center;
  the `show_processes` command ID is unchanged.
- Reduced unknown-identity checking overhead when reconciling changed directory
  listings.
- Arrow-key suggestions now offer local bindings for parent navigation, opening
  files/directories, and pane switching. Removed the unused "Other" feedback field.
- Drive-label lookup now belongs to the filesystem scanner instead of the
  column. Removed the obsolete update statement from Zen.
- Optional date edits commit on Enter, focus loss or a panel action, allowing
  minimum-boundary dates regardless of today's date and preventing stale Search
  values. Valid pending bounds update Search availability before commit.
  Form labels realign when their font changes.

### Documentation

- Documented manual plug-in installation and the snapshot Column migration;
  corrected F2/F12 shortcut notes and the portable Core location.

## [0.10.0] - 2026-09-26

This release focuses on extending the QuickView mode to support text based files.

### Added

- QuickView now previews plain text, Markdown and common source-code languages
  in one read-only text widget, with syntax highlighting, Markdown Source mode,
  selection/copy and local Find. Text reads are bounded to 2 MiB and formatting
  to 512 KiB; larger content remains plain with explicit limits and encoding warnings.
  Markdown resources and automatic link navigation are blocked. Existing image
  preview and source-pane commands are preserved; no new settings or helper process.

## [0.9.3] - 2026-09-25

This release focuses on targeted optimizations that reduce redundant work and temporary memory use.

### Changed

- Reduced redundant pane column sizing, icon-key calculation and status
  completeness checks.
- Find reuses identical name/path normalization and streams ranked candidates
  into bounded top-result selection without changing results or highlights.
- Command Center avoids repeated lowercase conversions while keeping command
  visibility, aliases and shortcuts live on each suggestion pass.

#### Performance Report

Local before/after component probes for the responsiveness changes, not a rerun
of the full performance suite:

| Measurement                                    | Before   | After    | Change                  |
| ---------------------------------------------- | -------: | -------: | ----------------------- |
| Find preparation, 20,000 entries               | 44.53 ms | 24.91 ms | 44.1% less time         |
| Ordinary ranked query, 20,000 entries          | 36.98 ms | 36.70 ms | Essentially unchanged   |
| Extended ranked query, 20,000 entries          | 47.79 ms | 47.71 ms | Essentially unchanged   |
| Peak ordinary-query allocation, 20,000 entries | 2.745 MB | 26 KB    | 99.1% less              |
| No-match query, 20,000 entries                 | 15.13 ms | 15.36 ms | 0.23 ms slower          |
| Native resize/paint cycle, three window sizes  | 33.34 ms | 33.42 ms | No measured improvement |

Matcher timings are medians from nine batches of three calls, alternating
before/after order; memory is peak traced allocation. The native cycle measures
warm resizing/painting with cached icon fallbacks. Small, 100-entry ranked
searches added approximately 0.02 ms and 10 KB of overhead. These results do not
establish faster overall folder loading or directory-size sorting.
See [measurement details](Done/CodeReview004.md#baseline-and-cost-probes).

## [0.9.2] - 2026-09-25

This release is mainly focused on solving edge cases, improve data safety and optimize performance.

### Fixed

- File operations no longer traverse junction targets during deletion or merge
  through source or destination directory links in Copy and Move.
  Same-file/hardlink copies are refused before writing,
  and failed deletes no longer emit success notifications.
- Regular copies stage output before publication. Windows overwrites preserve
  destination DACLs and named streams, retain recovery data on partial replacement
  failure, support read-only sources and missing identity metadata, and refuse
  linked or known-hardlinked overwrite targets. Compact, extended Windows staging
  paths avoid adding legacy path-length restrictions to deep destinations. Local-to-archive
  Move is disabled; use Copy, verify the archive, then delete originals explicitly.
- Session/dialog saves publish atomically and refuse linked settings files.
  Failed session saves report once instead of silently losing state.
  Temporary command targets are isolated between threads and restored after errors;
  file comparison captures context-menu targets before dispatching to Qt.
- Worker/process startup failures release capacity and clean up launched children;
  queued jobs report startup failure once. Icon and preference workers can retry
  on a later request. Skipped merges remain
  cancellable, and unreadable status totals are marked incomplete.
- Expected folder-access failures recover through normal navigation, including
  QuickView refreshes. UTF-8/BOM configuration works across settings, plug-in
  components and the shortcut list.
- Natural sorting handles long numeric runs and Unicode decimal digits. Go To
  retains offline history without background existence probes, and failed directory
  comparisons leave both selections unchanged.

### Changed

- Resource cache hits avoid allocation; status snapshots join each URL once;
  unchanged sort preferences no longer trigger disk writes.
- Replaced the stale public `FMAN_VERSION` compatibility value with
  `APP_VERSION`, backed by the RoyiFileManager product version. Session state
  now writes `app_version` while migrating the legacy `fman_version` key.
- The About dialog now shows the product version, a provisional plug-in API
  version of `0.0.0` and clickable project and documentation links.
- Removed obsolete pre new architecture snapshot row loading, unused internal helpers and
  unreachable shortcut suggestion branches, preserving current plug-in contracts.
- Application identity, build/release names, screenshot discovery and generated
  documentation now derive from `app_name` in `src/build/settings/base.json`.
  Custom names are validated; portable settings and compatibility identifiers
  remain unchanged. The packaging specification is now `application.spec`.

### Documentation

- Added documentation to more tools: Favorites, Directory Size, File Hash and
  Process Pane, each with a generated screenshot.
- Added an Archives page covering browsing, Pack, Unpack and archive transfers.
- Renamed the **Main Tools** page to **Tools**.
- Completed the keyboard shortcut reference with find/search, clipboard,
  Go To and drive-root shortcuts, using Command Center names.
- The plug-in UI guide links now point to the
  [UI extension reference](PlugIn.md#ui-extension) instead of a pending plan.
- Added a Troubleshooting section to [DEVELOPMENT.md](DEVELOPMENT.md) and
  removed its broken `UPSTREAM.md` link.

#### Performance Report

The new architecture is the baseline for the performance suite.

| Test                      	| Run Time (ms) 	|
|---------------------------	|---------------	|
| Pane Load - Small Folder  	| 42.37          	|
| Pane Load - Large Folder  	| 983.77         	|
| Filter Bar - Small Folder 	| 10.08          	|
| Filter Bar - Large Folder 	| 328.40         	|
| Fuzzy Find - Small Folder 	| 4.82           	|
| Fuzzy Find - Large Folder 	| 349.39         	|
| Fuzzy Find (Recursive)     	| 89.72          	|
| QuickView - Small Folder  	| 111.81         	|
| QuickView - Large Folder  	| 115.70         	|
| Navigation                	| 6.80           	|
| Refresh / Selection       	| 471.10         	|

The results were measured on the main development PC:
 - CPU: AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD.
 - Memory (RAM): 93.60 [GiB].
 - OS: Windows-11-10.0.26200-SP0.
 - Machine ID: `352fff5e51b22dfd`.
 - Python: 3.14.7 | Packaged by conda-forge | (main, Sep 2 2026, 21:12:42) [MSC v.1944 64 bit (AMD64)].
 - Qt / PyQt: 5.15.15 / 5.15.11.
 - Viewport: 1280 x 800 / 1x DPI.

## [0.9.1] - 2026-09-22

### Added

- QuickView's **Copy Image** button copies the loaded full-resolution still image
  to the clipboard without changing normal file-copy shortcuts.

## [0.9.0] - 2026-09-22

Probably the biggest change since the project started.  
The whole architecture of the _File Manager_ is replaced with the _Snapshot Architecture_.  
The new architecture make the application far more responsive and being able to handle large folders with ease.  
Internal testing on folders with more than 200,000 files showed almost instant rendering.
Performance should be on par with high performance _File Managers_ (Total Commander / RF Commander / Double Commander).

### API Compatibility

The current version breaks the `fman 1.7.5` filesystem, column and pane filter
extension contracts. Providers must implement `scan(path, check_canceled)`;
columns must implement `text(listing, index)` and `keys(listing, ascending)`;
custom pane filters must capture a snapshot predicate.  
Commands, URL-based file operations, settings and Task signatures
remain unchanged. See [migration contracts](PlugIn.md#filesystems-and-columns).

Later version will have dedicated guide for 3rd party Plug In's.

### Added

- Dedicated, demand-only performance tests with a commented YAML catalog,
  stable test/query IDs and immutable per-run JSON records attributed to the
  application version, source, harness, dependencies and machine configuration.
  New records retain per-metric statistics and sample counts instead of raw
  observations, without reducing repetitions. Older records remain readable.
  Comparisons reject incompatible fixtures, definitions and environments.
  Run them with `python build.py measure`, separately from `python build.py test`;
  the full suite updates its `X.Y.Z` or `Unreleased` result and opens an offline
  HTML report. History survives `clean`, and failed runs preserve successful
  version results. Eleven overview rows include aggregated Navigation and
  Refresh / Selection latency;
  previous-version comparisons, charts and detailed timings expose regressions.
- Reproducible synthetic 256-file and 200,000-file folders and a 50,000-file
  recursive tree replace the private CelebA dependency for new benchmarks.
  Fixtures include challenging names, valid PNG/JPEG/BMP images, fixed metadata
  and content-hash validation. Historical CelebA timings remain historical.
- Native Filter Bar, Fuzzy Find, recursive Find and small/large-folder QuickView
  workloads record runtime, completed paints, active event-loop stalls and
  memory. QuickView checks pixels, rapid navigation, controls, error states and
  cleanup. Page Up/Down, Home/End and simulated wheel scrolling have separate
  movement/paint latency measurements with QuickView off and on. Heavy speed
  tests are outside regular correctness verification; CPU profiles run separately.

### Changed

- Replaced per-row incremental pane loading with immutable snapshots and one
  virtual model for all bundled providers. Local NTFS/ReFS enumeration captures
  full 128-bit identities and display metadata in bulk; provider-specific scans
  support archives, drives, network roots and processes. Refresh rejects stale
  results and keeps operation-time metadata checks separate from display data.
  Unreadable link targets retain their own entry metadata. Traversal clients use
  lightweight name enumeration without populating a redundant attributes cache.
  Unchanged refreshes with verified identities avoid a full identity-remapping
  dictionary. Windows no-op OS watching skips Qt dispatch while retaining
  application notifications and scan-to-watch handoff.
- Filter Bar projections run off the Qt thread with existing substring/glob
  semantics. `Ctrl+F` retains the Quicksearch dialog and fuzzy/`fzf` matching,
  using the current pane snapshot for indexing when possible. Enter accepts a
  result; Escape cancels without changing the pane's filter, marks or columns.
- Icons and formatted cell text load lazily through bounded caches. Marked
  selection no longer makes the unhighlighted header inspect every selected cell
  during painting. External metadata delivery repaints without resetting the pane
  when the active sort depends only on the snapshot.

#### Performance Report

The new architecture is the baseline for the performance suite.

| Test                      	| Run Time (ms) 	|
|---------------------------	|---------------	|
| Pane Load - Small Folder  	| 44.14         	|
| Pane Load - Large Folder  	| 1030.26       	|
| Filter Bar - Small Folder 	| 9.72          	|
| Filter Bar - Large Folder 	| 332.28        	|
| Fuzzy Find - Small Folder 	| 4.67          	|
| Fuzzy Find - Large Folder 	| 350.86        	|
| Fuzzy Find (Recursive)     	| 89.82         	|
| QuickView - Small Folder  	| 109.73        	|
| QuickView - Large Folder  	| 118.74        	|
| Navigation                	| 6.79          	|
| Refresh / Selection       	| 482.95        	|

The results were measured on the main development PC:
 - CPU: AMD64 Family 26 Model 68 Stepping 0, AuthenticAMD.
 - Memory (RAM): 93.60.
 - OS: Windows-11-10.0.26200-SP0.
 - Machine ID: `352fff5e51b22dfd`.
 - Python: 3.14.7 | Packaged by conda-forge | (main, Sep 2 2026, 21:12:42) [MSC v.1944 64 bit (AMD64)].
 - Qt / PyQt: 5.15.15 / 5.15.11.
 - Viewport: 1280 x 800 / 1x DPI.

Earlier `Unreleased` snapshot, measured on 2026-09-21 with `python build.py measure`.
Windows/NTFS, warm caches, three fresh-process runs per test. Small folders contain
256 files; large folders contain 200,000 files; recursive search uses 50,000 files.

Pane Load and QuickView report median time to first populated paint and first
preview paint, respectively. Search rows report the slowest query's median time
to paint. Navigation is the mean of 28 action medians covering Page Up/Down,
Home/End and wheel scrolling across both folder sizes, with QuickView off/on.
These are observed interaction timings, not total benchmark execution times.

Refresh / Selection is the mean of 16 unchanged-refresh case medians: eight
selection patterns in both folder sizes, three fresh-process repetitions each.
Patterns cover no marks, first/middle/last single marks, a 10% middle block,
100 scattered marks, all except the cursor, and all entries. Timing starts after
selection setup and ends after the new snapshot paints; snapshot data, row order,
marks, cursor and scroll must be preserved. Its value uses the extended-suite run;
the other rows retain their earlier same-day measurements. Detailed timings and
cumulative process peak memory are available in the HTML report.
The Fuzzy Find rows predate restoration of the Quicksearch dialog and do not
measure its current performance.

#### Performance Compared With 0.8.1

Three alternating fresh-process pairs per folder on Windows, warm OS caches,
hidden filtering enabled, QuickView and extended status disabled. Baseline:
the pre-change application from commit `56e840a`, extracted only by the benchmark.
All 24 runs passed ordered row/text parity and settings-isolation checks.

**CelebA Folder - 202,603 Entries**

| Measurement                     	| Version `0.8.1` 	| Snapshot Architecture   	| Time Reduction 	|
|---------------------------------	|-----------------	|-------------------------	|----------------	|
| First Populated Pane Paint      	| 5.663 s         	| 0.583 s                 	| 89.7%          	|
| Metadata Loading Complete       	| 11.498 s        	| 0.571 s                 	| 95.0%          	|
| Total Post Paint Qt Commit Work 	| 1.511 s         	| 0 s                     	| 100%           	|

Metadata is ready before first paint, with no loading tail. Settled working set
fell from **771.3 MiB to 165.6 MiB** (78.5%). System32 first paint fell from
219 ms to 54 ms; WinSxS (24,315 entries) from 863 ms to 219 ms; C: root from
86 ms to 32 ms. These are directory-loading measurements, not application-startup
or cold-storage guarantees.

Heavy interaction remains a performance limitation: a separate 202,603-entry
full-candidate Find/sort/refresh run peaked at 285 MiB, and selected-all sorting
had 36 ms arrow-to-paint p95. Initial loading gains do not establish uniformly
frame-budget interaction. Reproduction and known limits are recorded in
[FSPaneArch001](Done/FSPaneArch001.md); further investigations are tracked in
[FSPaneArch002](Done/FSPaneArch002.md).

### Fixed

- Closing the Search files or Find files with fd panel with Escape returns
  keyboard focus to the last active pane after panel cleanup.
- Archive panes include deeply implied directories even when the archive has
  no explicit parent-directory records.

## [0.8.1] - 2026-09-21

API compatibility: Preserves the public `fman` plug-in API signatures from fman
1.7.5. `load_json` and `save_json` now merge nested dictionaries to preserve
inherited settings; override individual entries rather than relying on `{}` or
omitted nested keys to clear defaults. Deleting inherited nested keys on save
raises `ValueError`.

### Changed

- Reuse ordinary Windows directory entries' hidden attributes to reduce repeated
  pane visibility checks, with parent-node reuse to avoid repeated full-path cache
  traversal. Roots, UNC paths and reparse entries retain Qt fallback;
  full file metadata and operation semantics are unchanged. Refresh with `Ctrl+R`
  after external hidden-attribute changes.

#### Performance Compared With 0.8.0

Windows reference folder with 202,603 entries; medians of three alternating
fresh-process pairs, warm OS caches, hidden filtering enabled, QuickView and
extended status disabled. The benchmark reconstructs the 0.8.0 listing path;
these are folder-loading measurements, not packaged-application startup times.

**CelebA Folder - ~200,000 Files**

| Measurement                     	| Version `0.8.0` 	| This Version 	| Time Reduction 	|
|---------------------------------	|-----------------	|--------------	|----------------	|
| First Populated Pane Paint      	| 8.949 s         	| 5.823 s      	| 34.9%          	|
| Metadata Loading Complete       	| 17.786 s        	| 11.873 s     	| 33.2%          	|
| Total Post Paint Qt Commit Work 	| 2.765 s         	| 1.282 s      	| 53.7%          	|

This adds to previous improvements over the original code.  
In future version whole architecture is to be replaced to bring even greater gains.

### Fixed

- Ported upstream [f3e48d2](https://github.com/mherrmann/fman/commit/f3e48d23308689c4d3ffc90753a73bf6bb24a55b):
  nested plug-in settings merge recursively, so added archive handlers retain
  built-in formats; saves write only changed nested keys.

## [0.8.0] - 2026-09-21

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Windows image **QuickView** (`Ctrl+Q`): cursor-following JPEG/PNG/BMP preview
  over the opposite pane, without replacing its layout or directory state.
  Tab focuses the preview; Fit, physical-pixel 100%, zoom, pan, EXIF orientation
  and transparency are supported. Loading is bounded and asynchronous, with
  stale-result rejection, inline errors and limits of 128 MP / 65,536 pixels per
  edge / 64 MiB encoded. Starts off and remembers explicit Fit/100% preferences.

### Changed

- Replaced the unmaintained `tinycss` theme parser with `tinycss2`, removing its
  Python 3.14 syntax warning while preserving application styling. Invalid
  themes retain file/line/column diagnostics with updated parser reason text.

### Fixed

- Avoid recalculating every file-list row height on metadata updates in large
  folders, preventing repeated UI stalls and delayed image previews. Uniform
  row heights still follow font and theme changes.
- Qt tests now use a nonblocking completion notification to avoid a deadlock when 
  the event loop exits before worker cleanup.

## [0.7.1] - 2026-09-20

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Independent **Set file comparator** / **Set folder comparator** wizards with
  [Meld](https://meldmerge.org), [Beyond Compare](https://www.scootersoftware.com), [WinMerge](https://github.com/winmerge/winmerge), [SmartSynchronize](https://www.syntevo.com/smartsynchronize) and manual configuration.
  **Compare files** uses an active-pane marked pair or one file per pane;
  **Compare folders** uses the two current folders. Launches are fire-and-forget,
  with no default shortcuts, shell, automatic merge or synchronization.

### Fixed

- Find Files cancellation reports **Stopped**, not **Error**, when terminating fd
  leaves a partial output record. Completed matches remain available.
- Find Files result counts use **entries** rather than **files**, including for
  folder and link results.

## [0.7.0] - 2026-09-20

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- **Find files with fd** (`Shift+F7`): compact docked name search with case,
  extension, exclusion, date, exact size, type and traversal controls, grouped
  with dividers and equal-height inputs. Blank optional bounds are inactive;
  subfolder search uses a single recursive toggle. Optional
  search limits are independent of bounded result storage; searches are
  uncapped by default and count every match. Results support filtering, Go To
  and Copy Path.
- Additive provisional `fman.ui` dropdown, clearable date/integer Panel fields, section dividers,
  mixed file/folder Table paths and customizable filtered count text.
- [EmEditor](https://www.emeditor.com) preset in **Set text editor** and **Set text viewer**, using
  `-nr -sp` for editing and `-nr -sp -r` for viewing.

### Changed

- Named `Ctrl+F` and `Ctrl+Shift+F` **Find files in current folder** and
  **Find files recursively**, with **Toggle find result metadata** for their
  optional details. The fd panel remains **Find files with fd**; only the
  ripgrep panel is **Search files**. Shortcuts, command IDs and settings are unchanged.
- Enforced a 960 x 600 logical-pixel minimum application window size. The
  default size remains 1280 x 800.
- Renamed the Favorites command to **Open favorites manager**, retaining
  **Favorites Manager**, **Favorites**, and **Show favorites** as search aliases.
  `Ctrl+B` and the `show_favorites` command identifier are unchanged.
- Standardized Command Center capitalization for **Sync pane location** and
  **Reset window geometry**; command identifiers and behavior are unchanged.
- Removed the trailing ellipsis from **Calculate file hash by** in the Command Center.
- Renamed **Search File Content** to **Search files** (`Alt+F7`), including the
  results title, `SearchFiles` plug-in, `search_files` command and settings file.
  Existing `search_file_content` bindings and preferences remain supported;
  filename and content matching behavior is unchanged.
- File creation commands are now named **New file** (`Ctrl+N`, create only)
  and **Edit new file** (`Shift+F4`, create and open in the editor).
  Command identifiers and shortcut behavior are unchanged.

## [0.6.4] - 2026-09-19

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Changed

- [CudaText](https://github.com/Alexey-T/CudaText) presets now use `-n -ns -nh` for editing and `-r -n -ns -nh` for
  viewing. Select the preset again in **Set text editor** or **Set text viewer**
  to update an existing configuration.

## [0.6.3] - 2026-09-18

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Changed

- Added [Notepad 4](https://github.com/zufuliu/notepad4) built in preset in **Set text editor** and **Set text viewer**, using `-ns`
  for editing and `-ro -ns` for viewing.
- [Notepad++](https://github.com/notepad-plus-plus/notepad-plus-plus) presets now use `-multiInst -nosession -notabbar` for editing and
  `-multiInst -nosession -notabbar -ro` for viewing. Select the preset again in
  **Set text editor** or **Set text viewer** to update an existing configuration.

## [0.6.2] - 2026-09-18

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Notepad 4 preset in **Set text editor** and **Set text viewer**, using `-ns`
  for editing and `-ro -ns` for viewing.

## [0.6.1] - 2026-09-18

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Optional modified date and size beneath fuzzy file-search results. Use
  **Toggle search result metadata** in the Command Center to save the preference,
  or override it per search with `metadata`. Empty files display `0 B`; missing
  metadata retains a blank second line. Metadata indexing supports cancellation
  and discards results after pane navigation or closure.

## [0.6.0] - 2026-09-18

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- ProcessPane plug-in: a flat Windows process list with Name/PID columns,
  filtering, manual refresh and single-process F8 termination after a default-No
  confirmation. Uses current Windows permissions, validates process identity,
  refuses critical/self targets, and leaves ordinary file deletion unchanged.
- Fuzzy file search (`Ctrl+F` / `Ctrl+Shift+F`) supports `fzf` extended query
  operators: exact terms, path anchors, negation, inverse fuzzy matching,
  word boundaries, adjacent-term OR and escaped spaces. Matching text is
  highlighted, including Unicode filenames. Ordinary fuzzy ranking and
  regular mode are preserved; `fzf` is not a runtime dependency.

## [0.5.1] - 2026-09-17

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Support for setting external text viewer editor.  
  Using <kbd>F3</kbd> for viewing the current file and <kbd>F4</kbd> for editing.
- Added 2 wizards in Command Center: **Set text viewer** / **Set text editor** to set user defined viewer / editor.
  The wizard allows setting command line parameters to launch the viewer / editor.  
  Built in settings for Read Only mode for [`CudaText`](https://github.com/Alexey-T/CudaText) and [Notepad++`](https://github.com/notepad-plus-plus/notepad-plus-plus).

### Fixed

- `About` shows the RoyiFileManager product version from
  `src/build/settings/base.json` instead of the fman plug-in API level, which it
  now lists separately. Removed an unused hard-coded version copy from
  `fbs_runtime`.

## [0.5.0] - 2026-09-17

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Pane filters (Files Filter) support `?`, bracket classes, leading `^` / trailing `$`
  anchors, leading `!` negation and backslash escapes, while retaining
  case-insensitive substring matching. Bounded segment matching avoids
  exponential wildcard backtracking; queries are limited to 255 characters.
  The active pane shows live matched/total counts in the existing status bar,
  including after loading, file changes and navigation. Space remains selection.
- Search File Content lists files by name when Content Pattern is empty, using
  Glob, Literal or RegEx with the existing recursion, limits and Stop controls.
  Binary and empty files are included without content reads; results and progress
  report files, with empty snippets and path-only details.

### Fixed

- Content Glob matches anywhere in a line and highlights the matched text;
  outer stars no longer widen the highlight. Wildcard-only patterns still match
  whole lines, including blank lines.
- Closing a Table after successful navigation leaves the target file current in
  the focused pane. Ordinary close restores panel focus after its callback
  re-enables controls, without targeting disposed or replaced panels/Tables.
- TextField labels show their input tooltips, and Search File Content's field
  and mode tooltips explain the matching rules.

## [0.4.4] - 2026-09-17

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Optional directory totals in Core's existing `Size` column in both local
  panes, with incremental background calculation and unchanged file sizes.
  Toggle through the Command Center or `Ctrl+Shift+D`, with a persisted
  setting and brief On/Off notification. `Ctrl+F4` sorts by directory size;
  `Ctrl+Shift+Enter` calculates chosen directories independently, showing a
  calculating message and then the result in the status bar without a dialog.
  A newer request cancels and replaces the previous one.
  Scans skip links/junctions, mark partial totals and recompute without a
  cross-location cache; navigation and toggle-off do not wait for recursive work.
  The configurable limit defaults to 10,000,000 files per directory root, with
  `0` allowing unlimited progressive calculation; directories do not consume it.

### Fixed

- Restore non-stretching column widths by name across optional-column changes
  and restarts, while retaining compatibility with legacy session widths.
- Ignore queued pane-reload results after model shutdown, preventing updates
  to a deleted Qt model during teardown.

## [0.4.3] - 2026-09-16

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- `Unpack archive` extracts one local archive into a new suffix-free folder in
  the invoking pane, with existing progress/Cancel and no destination chooser.
  Existing or late-created output is never replaced. Exact-source and filename
  checks reject misidentified archives and colliding or rewritten names without
  modifying the source. Extraction reads the source directly, with no snapshot
  copy or post-extraction tree scan; temporary space holds extracted contents only.

## [0.4.2] - 2026-09-16

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Changed

- Archive extraction reports 7-Zip progress, supports cancellation during quiet
  process phases, and cleans staged output after process teardown.
- Moving out of or between archives verifies copied contents before source
  deletion. Cross-archive Move verifies by re-extracting the destination;
  additional hashing and I/O prioritize correctness over speed. Cancellation
  waits for active archive updates to finish.

### Fixed

- Failed, canceled, or warning-producing extraction cannot trigger dependent
  source deletion. Source-update failure retains copied output and stops the
  operation, including after a prior Continue-all choice.
- Archive-to-archive Move no longer deletes the source before destination
  packing succeeds. Detected source changes and same-file archive aliases stop
  the transfer before deletion.
- Windows directory publication refuses late destination conflicts and emits
  filesystem notifications only after success.
- Builds retry transient HTTP failures when downloading the pinned 7-Zip
  tools, with bounded backoff and unchanged SHA-256 verification.

## [0.4.1] - 2026-09-16

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- The Command Palette pins its three most recent matching commands, marked
  `Recent` beside their shortcuts. Palette only history is shared across panes
  and saved on exit, retaining unsaved entries through plug-in reloads.
- Added opt-in `load_json(..., preserve_on_reload=True)` for session-owned JSON
  data. Existing calls and ordinary settings reload behavior remain unchanged.

### Changed

- Search File Content uses scalable half filled square pane indicators matching
  the original StatusBarExtended symbols.

## [0.4.0] - 2026-09-14

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Added Search File Content on <kbd>Alt</kbd>+<kbd>F7</kbd>, based on [`ripgrep`](https://github.com/burntsushi/ripgrep).  
  File name and content patterns support Literal, Glob and RegEx modes.
- Added a table UI component (`fman.ui.show_table`).  
  Displays multi column data with optional file path and folder path actions.
- Added a docked panel UI component (`fman.ui.show_panel`) for plug in forms,
  with text fields, icon controls and status feedback.
- Added disposable `DirectoryPane.on_path_changed` subscriptions for pane bound
  tools, delivered on the UI thread without polling.

### Changed

- Shared fuzzy matching now prefers contiguous matches, so a query such as
  `cmd` highlights the whole extension in `CudaText.cmd` instead of an earlier `C`.

### Fixed

- Fixed a test suite timing issue that could produce a misleading
  permission error traceback during successful test runs.

## [0.3.1] - 2026-09-13

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Added Calculate File Hash on `Ctrl+H` and an algorithm picker command, with
  cancellable local file hashing and concurrent-change detection. Both show
  centered results with the file path as the window title and the hash algorithm
  beside Copy. Calculate File Hash By selects the algorithm in QuickSearch;
  neither command opens a docked Panel.
- Added public `fman.ui.OutputTextBox`: selectable read only output with a
  top left copy icon, optional adjacent title, Return / Enter copy all and normal
  selected text copying.

### Fixed

- Startup status messages now use the application version from the build
  settings instead of the upstream fman API version.

## [0.3.0] - 2026-09-13

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Added a vector `SVG` icon matching the current bitmap icon.
- Added reusable `fman.ui` components: an embeddable QuickList, a compact bottom
  panel, icon toggles, text buttons, drop-downs and asynchronous JSON settings
  bindings. Controls preserve unrelated settings and synchronize committed state.
- Added public host-owned UI construction, pane tool windows, resource transactions,
  shared matchers, theme hooks and cancellable tracked navigation. Favorites now
  demonstrates these exported services without internal host or Core imports.
- Added a persistent Favorites Manager on `Ctrl+B`, with Name/Path fuzzy
  filtering, Recent/Name/Path sorting, multi-selection, immediate bookmark-only
  deletion, rename and tracked Go To navigation. Open managers synchronize saved
  changes and close safely on plug-in unload; legacy command IDs remain callable.

## [0.2.2] - 2026-09-13

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Fixed

- Extended Status Bar summaries now display directory, file, size, and
  selected-item details correctly on 64-bit builds in both display modes.
- Active Extended Status Bar panes now use one continuous background instead
  of drawing separate background rectangles behind each text field.
- In Per pane mode, only the active pane's Extended Status Bar footer now
  displays the `Active` marker.

## [0.2.1] - 2026-09-13

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Fixed

- ZIP filesystem tests now generate their fixture in clean checkouts and
  accept fractional timestamps emitted by 7-Zip 26.03.
- Windows archive operations now decode Unicode 7-Zip output consistently,
  including on Python installations running in UTF-8 mode.
- Release builds now materialize the Git LFS-managed application icon and
  reject missing or invalid icon payloads before starting the build.

## [0.2.0] - 2026-09-13

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Added the bundled `SearchFileFuzzy` plug-in with configurable fuzzy or regular
  current-folder and recursive file search.
- Added an optional extended status bar for the active pane or both panes,
  toggled with `Ctrl+S`.
- Added a `Sync Pane Location` Command Center command that navigates the
  inactive pane to the active pane's current folder.
- Added a bundled Favorites plug-in with `Ctrl+B` search plus commands to add,
  remove, and rename saved folder locations.
- Added `Ctrl+N` to create an empty file without opening an editor; existing
  paths are left unchanged, unsupported locations hide the command, and
  filesystem errors are reported without a traceback.

### Changed

- Condensed the README feature overview into one-line descriptions of
  significant user-facing additions.
- Task provenance records now distinguish the acting agent from the underlying
  model, with each acting contributor supplying its own metadata.
- Reserved `Ctrl+B` for Favorites and made focused task-related tests the
  default validation policy instead of an automatic full-suite run.
- Hardened `Sync Pane Location` for single-pane, empty-location, and
  already-synchronized states without changing focus.
- Hardened Favorites validation, matching, concurrent updates, and inaccessible
  location handling, with clearer settings documentation.
- Hardened release builds with SHA-256-verified 7-Zip 26.03 downloads,
  immutable GitHub Action revisions, annotated SemVer tag enforcement,
  committed-lock-only CI builds, least-privilege publication, and refusal to
  create missing tags or replace existing releases.

## [0.1.0] - 2026-09-12

`RoyiFileManager` is based on [fman `1.7.5`](https://github.com/mherrmann/fman).

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Added

- Windows only portable distribution with settings stored in `UserSettings`
  beside the executable.
- Conda environment and lock file workflow for reproducible builds.
- PyInstaller based portable ZIP packaging.
- Automatic retrieval of the official 7-Zip command line executable required
  for archive operations.
- Windows compatible tests that do not require symbolic link privileges.

### Changed

- Rebranded the application as `RoyiFileManager` while preserving the public
  `fman` plug-in API.
- Replaced the external fbs runtime dependency with a local compatibility
  implementation.
- Improved responsiveness when sorting large directories and resizing panes.
- Improved natural name sorting performance.
- Improved local file copy throughput with a larger transfer buffer.
- Improved Windows startup by skipping unused Gnome icon provider detection.
- `F1` now opens a searchable keyboard shortcut guide with dedicated built in
  and plug-in sections.
- New sessions start in a 1280x800 window; subsequent sessions restore the
  previous window geometry and state.
- Added a `Reset Window Geometry` command that immediately restores the default
  window size and clears saved geometry for the next launch.

### Removed

- Non Windows packaging and platform resources.
- Legacy installers, signing assets, telemetry, licensing and online service
  integrations.

### Fixed

- Frozen Qt dependency collection for conda environments.
- Application context lifetime handling that caused native Qt startup crashes.
- `Worker`, `file-watcher` and `QApplication` shutdown races in the test suite.
- The application icon is now used in the window title bar and Windows taskbar.
- `freeze` now detects a locked previous build before PyInstaller starts and
  reports how to release the output directory.
- File list painting failed silently after the resize optimisation because the
  view iterated a boolean; visible rows are again loaded on demand.
- `Worker.submit` now forwards keyword arguments instead of unpacking their
  keys as positional arguments.
- `WorkItem.__eq__` compared tuples incorrectly and always evaluated as true.
- Changing the sort column and then relaxing a filter (for example showing
  hidden files) raised `Sort value is not loaded`; sort values are now loaded
  for filtered-out files as well, and files that vanished meanwhile are dropped.
- Moving a file over an existing one in the same directory duplicated its name
  in the cached directory listing, leaving the pane empty on the next visit.
- Duplicate additions to lazy plug-in directory listings could leave stale
  entries after the file was removed.