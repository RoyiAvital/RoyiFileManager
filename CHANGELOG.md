# Changelog

Notable implemented changes to the application are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

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
[FSPaneArch002](Plan/FSPaneArch002.md).

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