# Find Files

Press **Shift+F7** in a local folder, or run **Find files with fd**. The dock
follows its invoking pane; navigation, panel close and plug-in unload cancel
the current search and reject stale results. Search starts only on request.

## Filters

- **Name Pattern:** Glob (default, whole name), Literal (substring), or Regex
  (fd/Rust syntax). Empty matches all eligible entries. Case is Smart by default:
  uppercase pattern characters make it sensitive. Sensitive and Insensitive
  are explicit alternatives. Full path matches the absolute path.
- **Extensions:** semicolon-separated alternatives, e.g. `txt;tar.gz`; a leading
  dot is optional. **Exclude:** semicolon-separated globs; `\;` means a literal
  semicolon. Exclusions are independent of the main pattern mode.
- **Modification Date:** optional Start and End local calendar days, both inclusive.
  Leave either field blank to omit that bound. Unsupported, ambiguous or
  nonexistent boundary times are rejected.
- **File Size:** optional exact integer Min/Max bounds, inclusive; blank means no
  bound, while zero is an active value. Bytes/Kilo Bytes/Mega Bytes/Giga Bytes
  mean 1/1,000/1,000,000/1,000,000,000 bytes. Changing units reinterprets the number.
- **Type:** files by default; folders, links, executables, empty files/folders
  and special types are available. Some types have no native Windows matches.
- **Recursive:** on searches all subfolders; off searches direct children.
  There is no separate Max depth control.
- **Hidden:** independent of ignore rules. **Honor .gitignore:** the Git-branch
  icon, on by default, also outside Git worktrees. Off bypasses VCS rules;
  `.ignore`, `.fdignore` and fd's global ignore rules are always honored.
  **Follow links:** off by default; on can search
  targets outside the root. Returned aliases are preserved.

## Results and Limits

**Max Results**, on the second row, defaults to blank (`None`): count all
matches. Enter a positive number to limit the search. Search limits and table
capacity are separate: the table retains at most 10,000 rows
and 16 MiB text/payload; excess paths are counted without querying their metadata.
For an uncapped 20,000-match run the footer reads:

`Showing 10,000 / 20,000 files (Maximum table size reached)`

Filtering changes the numerator, not the run's denominator. Reaching an enabled
search limit, stopping, or encountering traversal errors explicitly marks the
total incomplete. No approximate full-tree total is invented. Uncapped searches
continue traversing after the table fills. Stop stays enabled and red, matching
Search Files; it cancels an active search and does nothing while idle.

Results show Path, Size and Modified. Directory sizes stay blank; unavailable
metadata does not remove matches. Enter/double-click a Path or use **Go To** to
highlight a file or enter a folder. **Copy Path** copies its absolute path.
Closing results unlocks the form. Empty searches report their count in the status bar.

Only mode, case, type, toggles and size units persist in `FindFiles.json`.
Patterns, bounds and Max Results are session-only. Section dividers separate
contexts; controls share a 28-pixel height and align along each line's bottom.
At the default 1280-pixel window width this three-band dock matches Search
Files' height; it wraps at the enforced 960 x 600 logical-pixel minimum.
The root indicator stays on the left; traversal and Search/Stop controls align
right. Tab and Shift+Tab visit controls in row order, skipping disabled fields.

Source runs use the active environment's `bin/fd.exe`; packaged runs use the
bundled executable, never PATH lookup. See [fd notices](licenses/README.md).