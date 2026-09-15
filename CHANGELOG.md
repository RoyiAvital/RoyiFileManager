# Changelog

Notable implemented changes to the application are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

API compatibility: Preserves the public `fman` plug-in API from fman 1.7.5.

### Fixed

- Windows release builds now bundle ripgrep's license notices from repository
  resources instead of depending on a conda package-cache directory that may be
  absent after CI environment restoration.

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