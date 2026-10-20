# Tweaks and Tricks

| #   | Feature                         | Why it fits                                                                  | Size          |
| --- | ------------------------------- | ---------------------------------------------------------------------------- | ------------- |
| 1   | Swap panes                      | Only *Sync pane location* exists. Total Commander uses `Ctrl+U`.             | Very small    |
| 2   | Select / deselect by pattern    | Today only Select all, Clear and Invert. Reuses the Filter Bar syntax.       | Small         |
| 3   | Bind Invert selection           | The command exists without a shortcut. `Num*` is the common key.             | Very small    |
| 4   | Show in Explorer with selection | `F10` opens the folder but does not highlight the file.                      | Very small    |
| 5   | Copy names of several files     | `Shift+F11` handles one item; `F11` already copies many paths.               | Very small    |
| 6   | Free space in the status bar    | No free-space display exists. Runs only while the extended status bar is on. | Small         |
| 7   | Go to link target               | Links can be created (`Shift+F5`) but not followed to their target.          | Small         |
| 8   | Sort by extension               | Only Name, Size and Modified exist.                                          | Small, medium |
| 9   | Select the same extension       | Mark visible files like the cursor file without typing a pattern.            | Very small    |
| 10  | New folder and enter            | Create a folder and immediately navigate into it.                            | Small         |
| 11  | Command Center synonyms         | Find Favorites with "Bookmarks" or Unpack archive with "Extract".            | Very small    |
| 12  | Optional ISO date display       | Show consistent, unambiguous local dates and 24-hour time in pane columns.   | Small         |
| 13  | Go to clipboard path            | Open a copied folder path or reveal a copied file using existing navigation. | Very small    |

## 1. Swap Panes

1. Add `SwapPanes(DirectoryPaneCommand)` beside `SyncPaneLocation` in
   [commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py).
2. Capture both URLs first: `left, right = self.pane.window.get_panes()[:2]`.
3. Mirror `SyncPaneLocation`: hidden with fewer than two panes, refuse `null://`,
   no-op when both URLs are equal.
4. Call `left.set_path(right_url)` and `right.set_path(left_url)`. Focus stays on
   the same side.
5. Bind `Ctrl+U` in `Key Bindings (Windows).json` (currently unused).
6. Unit test with mock panes: both `set_path` calls, the no-op and the refusal.

## 2. Select / Deselect by Pattern

1. Add `SelectByPattern` and `DeselectByPattern` commands. Aliases: *Select group*,
   *Deselect group*.
2. Prompt with `show_prompt`. Default to `*.<ext>` of the file under the cursor.
3. Compile with `compile_filter` from
   [filter_pattern.py](../src/main/python/fman/impl/filter_pattern.py). Same syntax
   as the Filter Bar: `*`, `?`, `[...]`, `^`, `$`, `!`.
4. Match against the names of `pane.get_listing()`. No I/O.
5. Mark only rows visible in the pane, like `select_all`. Hidden or filtered rows
   must stay unmarked. Add a small host helper if no visible-row accessor exists.
6. Apply with one batched `pane.select(urls)` / `pane.deselect(urls)` call.
7. Bind keypad `+` / `-` after verifying the Qt key names.
8. Unit test the matching and the visible-row restriction.

## 3. Bind Invert Selection

1. Add a keypad `*` binding for `invert_selection` (verify the Qt key name).
2. Replace its `iterdir` scan with the visible rows used in item 2. This avoids
   disk I/O and keeps hidden or filtered rows unmarked.
3. Unit test with a filtered pane.

## 4. Show in Explorer with the File Selected

1. Add a `ShowInExplorer` command. Keep `F10` unchanged.
2. Accept only a `file://` item under the cursor.
3. Launch `['explorer.exe', '/select,' + native_path]` with `shell=False`.
   Ignore Explorer's nonzero exit code; it is normal.
4. Fall back to opening the folder when nothing is under the cursor.
5. Add it to `File Context Menu (Windows).json`.
6. Unit test the argument list with a patched `subprocess`.

## 5. Copy Names of Several Files

1. Let `CopyFileName` accept all chosen files; join their basenames with newlines.
2. Report with `_report_clipboard_action`, as `F11` does.
3. Remove the single-item `is_visible` check. Keep *Copy file path* single-item;
   `F11` covers many paths.
4. Update the single-item notes in [shortcuts](../docs/shortcuts.md) and the Core README.
5. Unit test one and several names.

## 6. Free Space in the Status Bar

1. In `calculate_status_summary` in
   [status_bar.py](../src/main/python/fman/impl/status_bar.py), call
   `shutil.disk_usage` for `file://` locations. It already runs on the status worker.
2. Show `Free: <free> of <total>` with the configured `size_divisor`.
3. Omit the field for other schemes and on errors, such as disconnected drives.
4. Disabled mode keeps its no-work path.
5. Unit test the formatting and the error path.

## 7. Go to Link Target

1. Add `GoToLinkTarget`. Visible when the item under the cursor is a local
   symlink or junction (`os.path.islink` / `os.path.isjunction`).
2. Resolve on the command worker with `os.path.realpath` (follows chains).
3. Directory target: `pane.set_path(target)`.
4. File target: `set_path(parent)`, then `place_cursor_at(target)` in the callback.
5. Missing target: alert *Broken link* and leave the pane unchanged.
6. Unit test with the existing `symlinks_supported()` skip helper.

## 8. Sort by Extension

1. Add a `core.Extension` column in [Core](../src/main/resources/base/Plugins/Core/core/__init__.py).
2. `text`: the extension; `keys`: `(not is_dir, extension.casefold(), natural name)`.
   Folders first, natural order within each extension. No I/O.
3. Set `keys_depend_on_external_data = False`.
4. Make it optional: off by default, enabled by a setting, so default layouts and
   saved widths are unchanged.
5. Bind a sort key (e.g. `Ctrl+F5`) through `sort_by_column`.
6. Unit test the keys for files, folders, no extension and descending order.

## 9. Select the Same Extension

1. Add `SelectSameExtension`. Alias: *Select files with the same extension*.
2. Capture the cursor file and committed listing. Use its final filename suffix:
   `archive.tar.gz` means `.gz`. Compare case-insensitively and exclude folders.
3. Reuse the visible-row helper from item 2. Do not enumerate or stat files.
4. Apply one batched `pane.select(urls)` call. Keep the current filter and
   unrelated marks; do not newly mark hidden or filtered rows.
5. With no cursor file, a folder or no extension, show a short status message
   without changing selection. Add no default shortcut.
6. Unit test mixed case, compound names, extensionless files, folders,
   visible-row restrictions and preservation of unrelated marks.

## 10. New Folder and Enter

1. Add `CreateDirectoryAndEnter`. Alias: *New folder and enter*.
2. Reuse or extract the prompt and creation logic from `CreateDirectory`.
   Capture the invoking pane's URL and requested destination before creation.
3. After successful creation, navigate to the normalized destination, including
   nested folders. Cancellation, an existing destination or a creation error
   must not navigate.
4. Do not retarget a pane that closed or changed location while creation ran.
   A navigation failure reports the error and leaves the created folder intact.
5. Keep ordinary New Folder and `F7` unchanged. Add no default shortcut.
6. Unit test ordinary and nested creation, cancellation, existing destinations,
   creation failure and stale navigation. Add a Qt check for successful entry
   and pane focus.

## 11. Command Center Synonyms

1. Extend existing command `aliases`; do not add a keyword registry or new API.
2. Add useful vocabulary, such as *Bookmarks* for Favorites, *Extract archive*
   for Unpack Archive and *Preview* for Toggle QuickView.
3. Preserve command IDs, the first alias, shortcuts, visibility checks and
   existing ranking/recent-command rules. Keep the current matched-alias display
   behavior and one result per command.
4. Unit test synonym matching, original aliases, duplicate suppression, correct
   dispatch and recent-command identity.
5. Add concise discovery examples to the
   [Command Center guide](../docs/basics.md#command-center).

## 12. Optional ISO Date Display

1. Continue [DateFormat](DateFormat.md), the canonical design; do not create a
   second task or duplicate its implementation plan here.
2. Offer locale formatting (default) or `yyyy-MM-dd HH:mm` for the built-in
   Modified column. Keep timestamps, sorting and other date surfaces unchanged.
3. Before implementation, update that design's legacy column references to the
   current snapshot `text(listing, index)` / `keys(listing, ascending)` contract.
4. Resolve the display pattern once; add no scans, timers or background work.
   Treat clearer presentation as the benefit, not an unmeasured speed claim.
5. Test locale/ISO output, local-time conversion, missing dates and unchanged
   sort keys. Document the setting and its restart requirement.

## 13. Go to Clipboard Path

1. Add `GoToClipboardPath(DirectoryPaneCommand)`. Alias: *Open clipboard location*.
2. Read `clipboard.get_text()` once when invoked. Trim surrounding whitespace
   and one enclosing pair of double quotes, as produced by Explorer's Copy as path.
   Preserve application URLs; convert native paths with `fman.url.as_url`.
3. Dispatch `pane.run_command('open_directory', {'url': url})`. Reuse its folder
   navigation, file-parent navigation with cursor placement, and error handling;
   do not add a separate filesystem-check or navigation path.
4. An empty clipboard shows a short status message without navigating. Leave
   Paste and `Ctrl+V` unchanged; add no default shortcut.
5. No clipboard monitoring, persistence, timers or new background service.
6. Unit test plain and quoted paths, UNC paths, application URLs, empty text and
   dispatch. Verify folder navigation and file highlighting through the existing
   `OpenDirectory` tests; keep Paste behavior unchanged.

## Reviewers

### 2026_10_20 - Copilot

- Role: Reviewer
- Activity: Review
- Agent: Copilot SDK in VS Code
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 1M
- Outcome: Added three small feature candidates; retained the existing pattern-selection
  and Explorer-selection entries without duplication. No implementation authorized.

### 2026_10_20 - Copilot

- Role: Reviewer
- Activity: Review
- Agent: Copilot SDK in VS Code
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Added optional ISO date display by reference to its canonical design.
  Pattern selection, same-extension selection, multi-name copying and command
  synonyms were already covered and were not duplicated. No implementation authorized.

### 2026_10_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Added Go to clipboard path using existing navigation. Swap panes,
   multi-name copying, same-extension selection and command synonyms were already
   covered by items 1, 5, 9 and 11 and were not duplicated. No implementation authorized.
