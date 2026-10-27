# Command Palette 001: Categories

Status: Completed

## Task

Group Command Palette entries VS Code style: each command shows as
`Category: Title`, for example `Settings: Edit settings` or `File: Edit`. Users
see related commands together and can narrow the list by typing a category name.

## Scope

Included:

- A required `category` attribute on `ApplicationCommand` and
  `DirectoryPaneCommand`. The base classes define `category = ''`, meaning no
  category and no prefix.
- Registry and public accessors for the category.
- Palette labels, matching, highlighting and ordering based on the category.
- A category for every bundled command, from the fixed list below.
- QuickView image command aliases lose their `QuickView: ` prefix, because View
  now supplies it.
- QuickSearch rows elide a hint that would overlap the title. Middle elision
  keeps the first shortcut and `Recent`. Longer labels made this overlap
  reachable, for example `Navigation: Move cursor down` with five shortcuts and
  `Recent`.

Excluded:

- File and folder context menus. Captions and their fallback to the first alias
  are unchanged.
- Key bindings, command IDs, the Help (keyboard shortcuts) dialog and Recent
  history storage.
- Dimmed category text, section headers and multiple categories per command.

Compatibility: none required. The API is unreleased. Third-party commands
without `category` inherit `''` and show without a prefix.

### Categories

| Category | Bundled commands (class names) |
| --- | --- |
| Application | `About`, `Help`, `CommandPalette`, `Quit`, `ZenOfFman`, `ReloadPlugins`, `RemovePlugin`, `ListPlugins`, `OpenDataDirectory`, `Minimize`, `ResetWindowGeometry`, `Tutorial`, `CleanupGuide` |
| Settings | `EditSettings`, `SetTextEditor` (+`SetTextViewer`), `SetFileComparator` (+`SetFolderComparator`), `SetQuickViewTableLimit`, `ToggleLiveRefreshDuringFileOperations` |
| File | `Open`, `OpenFile`, `OpenDirectory`, `OpenSelectedFiles`, `OpenWith`, `OpenWithEditor` (+`ViewFile`, `CreateAndEditFile`), `NewEmptyFile`, `CreateDirectory`, `_TreeCommand` (`Copy`, `DuplicateFile`, `Move`, `Symlink`), `Rename`, `MoveToTrash`, `DeletePermanently`, `ShowExplorerProperties`, `Pack` (+`PackHere`), `UnpackArchive`, `CopyWithRobocopy`, `MoveWithRobocopy` |
| Clipboard | `CopyFilePath`, `CopyFileName`, `CopyToClipboard`, `Cut`, `Paste`, `PasteCut` |
| Selection | `SelectAll`, `Deselect`, `InvertSelection`, `SelectSameExtension`, `SelectByPattern`, `DeselectByPattern`, `ToggleSelection` |
| Navigation | `GoUp`, `GoBack`, `GoForward`, `GoTo`, `GoToClipboardPath`, `GoToLinkTarget`, `GoToRootOfCurrentDrive`, `ShowVolumes`, `_OpenInPaneCommand` (`OpenInLeftPane`, `OpenInRightPane`), `MoveCursor*` |
| View | `ToggleHiddenFiles`, `SortByColumn`, `Reload`, `SwitchPanes`, `SwapPanes`, `SyncPaneLocation`, `ToggleFullscreen`, `ToggleExtendedStatusBar`, `ToggleDirectorySizeColumn`, `SortByDirectorySize`, `ShowDirectorySize`, `RecalculateDirectorySizes`, `ToggleQuickView`, `_ImageCommand` (QuickView fit, 100%, zoom in/out, pan) |
| Search | `FindFiles`, `SearchFilesInCurrentFolder`, `SearchFilesRecursively`, `ToggleSearchResultMetadata`, `SearchFiles`, all Everything commands |
| Favorites | `ShowFavorites`, `AddCurrentFolderToFavorites`, `RemoveFromFavorites`, `RenameFavorite` |
| Tools | `CompareFiles` (+`CompareFolders`), `CompareDirectories`, `CalculateFileHash`, `GenerateChecksumFile`, `VerifyChecksum`, `BatchFileRenamer`, `ShowProcesses`, `EndProcess`, `ProcessOperationUnsupported`, `OpenTerminal`, `OpenNativeFileManager` |

`none` keeps `''`. Subclasses inherit the category of the class noted in
parentheses. Alias changes:

- `QuickView: Fit`, `QuickView: 100%`, `QuickView: Zoom in`, `QuickView: Zoom out`
  and `QuickView: Pan` become `QuickView fit`, `QuickView 100%`,
  `QuickView zoom in`, `QuickView zoom out` and `QuickView pan`.
- `Find files: toggle modified date and size` becomes
  `Toggle modified date and size in find results`.

## Design

### API, [fman/\_\_init\_\_.py](../src/main/python/fman/__init__.py)

- `ApplicationCommand.category = ''` and `DirectoryPaneCommand.category = ''`
  are class attributes.
- `DirectoryPane.get_command_category(name)` and
  `fman.get_application_command_category(name)` are added to `__all__`.
- [command_registry.py](../src/main/python/fman/impl/plugins/command_registry.py):
  both registries gain `get_command_category(name)`. It reads the class (pane)
  or instance (application) attribute and returns `''` for a missing or
  non-string value. Leading and trailing whitespace is stripped.
- [PluginSupport](../src/main/python/fman/impl/plugins/__init__.py) forwards
  `get_application_command_category`.

### Palette, `CommandPalette` in [core/commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)

- `_get_all_commands()` also returns each command's category.
- Label: `f'{category}: {alias}'`, or just `alias` when the category is `''`.
  The `QuicksearchItem` title is the label; the hint stays as shortcuts plus
  `Recent`.
- Matching, for a non-empty query, per command:
  - Each alias is tried against each matcher in order: word start
    (`contains_chars_after_separator(' ')`), then `contains_chars`.
  - For each matcher, the alias is tried before the full label. That gives
    buckets: alias word start, label word start, alias contains, label contains.
  - The command takes the best bucket over all its aliases; ties go to the
    earlier alias. Today the first alias that matches anything wins. The new
    rule only lets a later alias improve the rank.
  - An alias match shifts its highlight by `len(category) + 2`. A label match
    highlights the label directly.
- Ordering:
  - Non-empty query: by bucket. Within a bucket, `(len(alias), label)` for alias
    buckets and `(len(label), label)` for label buckets. This keeps today's
    "shortest title first" feel.
  - Empty query: all commands sorted by `label.casefold()`, so categories form
    contiguous groups and uncategorized commands sort by title.
  - Recent commands stay pinned first in both cases, as today.
- Restoring the last item when the palette reopens still uses command identity.

### Hint fitting, [quicksearch.py](../src/main/python/fman/impl/quicksearch.py)

`QuicksearchItemRenderer.fitted_hint()` elides the hint (`Qt.ElideMiddle`) to
the row width minus the title width and a 12 px gap (`HINT_GAP`). Hints that
fit are drawn unchanged. This applies to every QuickSearch list.

### Ownership and threading

Categories are static class data. The palette already runs its provider on a
worker and reads aliases there. Categories are read the same way, with no new
Qt access.

### Failure behavior

A bad `category` value in a third-party plug-in falls back to `''`. It does not
fail plug-in loading.

## Alternatives

- Prefix the aliases (`Application: About`): rejected. Context menus without a
  caption would show the prefix, every synonym would need it, and length-based
  ranking would degrade.
- Multiple categories per command: rejected. A command would either appear in
  several rows or match on categories the user can't see. Aliases already
  provide extra search terms.
- An enum or registry of allowed categories: rejected. Free-form strings are
  simpler for plug-ins. The bundled list is enforced by a test.
- Section headers in Quicksearch: rejected for now. They need new
  widget/renderer support, and the prefix plus sorting gives the grouping.
- Showing the category in the hint column: rejected. The hint holds shortcuts.

## Runtime Effects

- Startup: none. Categories are class attributes.
- Per keystroke: at most twice the current matcher calls (alias, then label)
  over about 150 commands, plus one string concatenation per alias. Measured
  about 2 ms per suggestion pass over the 105 bundled pane commands, including
  the existing shortcut lookup.
- Rendering: one `elidedText` call per painted row with a hint.
- Memory, I/O, threads, timers: none added.
- Disabled/no-op path: commands with `''` behave exactly as today, apart from
  the best-alias rule.

## Tests

- Unit, `fman_unittest` command registry tests:
  - `get_command_category` for both registries: explicit value, inherited
    value, the base default `''`, a non-string value giving `''`, and
    whitespace stripping.
  - `fman.get_application_command_category` and
    `DirectoryPane.get_command_category` forwarding.
- Unit, [core palette tests](../src/main/resources/base/Plugins/Core/core/tests/commands/test___init__.py):
  - Label format with and without a category.
  - Highlight offset for an alias match; label highlight for a category-only
    match.
  - Bucket order: an alias word-start match beats a category-only match
    (`fi` lists `Search: Find files` before `File: Alpha`); a category
    word-start match beats a substring inside a title.
  - Best alias across buckets.
  - Empty query sorted into contiguous categories.
  - Recent items keep their labels and stay pinned.
  - Existing expectations updated to the new titles.
- Integration, [test_plugin.py](../src/integrationtest/python/fman_integrationtest/impl/plugins/test_plugin.py):
  load every bundled plug-in (`src/main/resources/base/Plugins/*` and
  `plugins/BatchFileRenamer`). Assert that every registered command has a
  category from the fixed list; only `none` may be `''`.
- Regression: `fman_unittest.impl.plugins.test_context_menu` and
  `ClipboardCommandsIT` pass unchanged, so menu captions show no category.
- Qt: `CommandPaletteRecentIT` and `ClipboardCommandsIT` with updated palette
  titles; `CommandPaletteRecentIT` checks hint elision keeps the first shortcut
  and `Recent`.
- End to end: `fman_integrationtest.recent_commands_smoke` asserts no bundled
  palette row has a hint overlapping its title, at every scale factor.
- Manual:
  - An empty query shows the groups.
  - `file` shows File commands after direct title matches.
  - `zoom` shows `View: QuickView zoom in`.
  - `settings` shows `Settings: Edit settings`.
  - Right-click menus are unchanged.

## Implementation Steps

1. Add the API attribute, the registry and support accessors, and their unit
   tests.
2. Assign categories and the alias renames in Core, the builtin plug-in and the
   bundled plug-ins. Add the all-commands integration test.
3. Update `CommandPalette` labels, matching and ordering. Add the palette unit
   tests and update the existing palette and Qt expectations.
4. Docs:
   - [PlugIn.md](../PlugIn.md): `category`, the accessors and the bundled list.
   - [docs/api/index.md](../docs/api/index.md).
   - Command Center mentions in docs and READMEs, including the QuickView alias
     names in the [Core README](../src/main/resources/base/Plugins/Core/README.md).
5. Add a CHANGELOG entry, tick the TODO item, then run the focused tests.

## Acceptance Criteria

- Every bundled palette entry shows `Category: Title` from the fixed list.
  `none` is the only uncategorized command.
- Typing a category name lists that category's commands. Direct title matches
  rank first.
- An empty query lists commands grouped by category, after Recent.
- Context menus, key bindings, command IDs and the Help dialog are unchanged.
- Third-party commands without `category` work and show without a prefix.
- The focused tests above pass.

## Implementation Review (2026-10-27)

### CP01 - P3: Unicode Categories Can Misalign Highlights

- Owner: [_match_command_alias](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L1540)
  and [QuicksearchItemRenderer](../src/main/python/fman/impl/quicksearch.py).
- Failure: label matching returns indexes from `prefix.lower() + alias.lower()`
  without mapping them back to the original label. Lowercasing a category can
  expand its length. With category `\u0130`, alias `Edit` and query `i edit`,
  the returned label has 7 code points but the highlights are
  `[0, 3, 4, 5, 6, 7]`; index 7 is outside the label. The command still matches
  and dispatches, but its highlight is incorrect.
- Related boundary: an alias match offsets by Python `len(prefix)`, while Qt
  text layout uses UTF-16 positions. With category `\U0001f527 Tools`, alias
  `Edit` and query `edit`, the returned highlight starts at 9; the alias starts
  at UTF-16 position 10. ASCII bundled categories do not expose either case.
- Evidence: a bounded inline probe under the selected Python 3.14.7 interpreter
  (`-I -`). It parsed the matcher source and Core command module with `ast`,
  compiled only `contains_substring`, `contains_chars`,
  `contains_chars_after_separator` and `_match_command_alias`, and printed the
  results above. An ASCII `File` category control had no out-of-range indexes.
  No application imports, settings access, tests or application changes.
- Limits: source-level index results, not a rendered Qt screenshot or a full
  plug-in workflow. Existing Unicode alias handling has related limitations;
  the category feature introduces the same boundary for otherwise ASCII aliases.
- Follow-up: map normalized match positions back to original text, then honor
  Qt's UTF-16 index contract at the rendering boundary. Add focused regression
  coverage for expanding lowercase mappings and non-BMP category prefixes.
  No implementation change is authorized by this review.
- Resolution (2026-10-27, user-approved): the same issue applied to Go to
  (`Ctrl+P`) paths, which share the matchers. `display_positions` in
  [matchers.py](../src/main/python/fman/impl/ui/matchers.py) maps positions in
  the lowercased text back to UTF-16 positions in the title, so emoji cover two
  units. The Command Center and Go to map only matching items. ASCII text,
  and text whose lowercase keeps its length without non-BMP characters,
  returns positions unchanged. Measured on 5,000 synthetic paths with 10%
  matches: ASCII 0.56 to 0.50 ms (no change); every path with `İ` and an emoji
  1.55 to 4.92 ms per keystroke.

### Coverage and Validation Limits

- Registry normalization/forwarding, the four matching buckets, best-alias
  selection, Recent identity/pinning, context-menu captions and hint fitting
  were inspected. No P1/P2 regression was confirmed in those paths.
- The bundled-category check imports modules and validates category membership;
  it does not exercise every plug-in's registration or assert the exact
  class-to-category table. This is a coverage limitation, not evidence that a
  bundled command is currently miscategorized.
- Editor diagnostics reported no errors in the palette command module,
  `command_registry.py` or `quicksearch.py`. Earlier implementer test/smoke
  results above and below remain historical; they were not independently rerun.
- Existing unit, integration, smoke and performance targets were not run under
  the review's no-tests constraint. Only the bounded matcher probe ran.

## Reviewers

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Single category per command, ten fixed categories (Compare merged
  into Tools, QuickView into View), no context menu changes. Ready for review.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: User approved the design, including Settings as a separate category,
  Toggle fullscreen under View and Terminal/Explorer under Tools. Revised during
  implementation: QuickSearch hints are elided instead of overlapping longer
  labels; corrected the ranking example.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the implemented category API, palette matching/ranking and
  shared hint renderer. Recorded CP01 with bounded source-only probe evidence
  and the bundled-category coverage limitation. No P1/P2 regression confirmed
  in the reviewed paths. No existing tests rerun or application code changed;
  previous implementation and validation records preserved.

## Implementer

### 2026_10_27 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented the category API, bundled categories, palette labels,
  matching and ordering, and hint elision. Focused unit, integration, Qt and
  smoke checks pass.

### 2026_10_27 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Resolved CP01 for the Command Center and Go to with a shared
  position mapping and regression tests for `İ`, emoji categories and emoji
  paths. Raised the QuickSearch list width to `165ex` at the user's request.

## Validation Results

- `python -m unittest core.tests.commands.test___init__
  fman_unittest.impl.plugins.test_command_registry
  fman_unittest.impl.plugins.test_context_menu fman_unittest.test_search_file_fuzzy
  fman_unittest.test_process_pane fman_unittest.test_checksum_files
  fman_unittest.test_search_files fman_unittest.test_robocopy
  fman_unittest.test_calculate_file_hash fman_unittest.test_find_files
  fman_unittest.test_directory_size`: 450 tests OK (3 skipped).
- `python -m unittest fman_integrationtest.impl.plugins.test_plugin
  fman_integrationtest.impl.plugins.test_favorites_plugin` (native Qt platform):
  11 tests OK, including `BundledCommandCategoryTest`.
- `python -m unittest` on `test_qt` classes `CommandPaletteRecentIT`,
  `ClipboardCommandsIT`, `SearchFileSyntaxIT`, `QuickViewImagesIT`,
  `DirectorySizeIT`, `EverythingIT` (native Qt platform): 37 tests OK.
- `python -m fman_integrationtest.recent_commands_smoke`: all phases pass,
  102 bundled hint widths checked per phase.
- Timing: about 2 ms per suggestion pass over 105 bundled pane commands.
- Running Core unit tests and `test_qt` classes in one process aborts in the Qt
  test harness (`cannot join thread before it is started`); each group passes
  in its own process. Context menu tests pass unchanged.
- All commands run through `build._environment()`. The full suite was not run.
- CP01: `python -m unittest core.tests.test_quicksearch_matchers
  core.tests.commands.test_goto core.tests.commands.test___init__`: 186 tests OK.
  `fman_unittest.test_ui_elements` and `fman_unittest.impl.plugins.test_command_registry`:
  44 tests OK. `CommandPaletteRecentIT`, `ClipboardCommandsIT`,
  `SearchFileSyntaxIT`: 7 tests OK. `recent_commands_smoke`: all phases pass
  with the `165ex` list width.
