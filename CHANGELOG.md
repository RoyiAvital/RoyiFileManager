# Changelog

Notable implemented changes to the application are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

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