# Everyday Workflows

Combine the panes, selection tools and commands to finish a task.
Open Command Center with ++ctrl+shift+p++ for commands without shortcuts.

!!! info "Release Availability"
    Pattern previews in the first workflow require an Unreleased development
    build. On a released build, mark files with ++space++ instead.
    See [feature availability](features.md#availability).

## Which Items Will Change?

| Term | Meaning |
| --- | --- |
| Cursor / highlighted item | The row reached with the arrow keys. QuickView uses this item, even when others are marked. |
| Committed marks | The applied pane selection. Built-in Copy/Move use these items; with no marks, they use the cursor item. |
| Preview marks | A proposed Select/Deselect-by-pattern result. Enter applies it; Esc keeps the original marks. Other commands cancel the preview and use committed marks. |
| Filtered table rows | Results left after narrowing a search table. They are not pane marks or a bulk Copy/Move/Delete selection. |

"Visible" means passing the current filters, not just fitting on screen.
Scrolling does not exclude items from a group.

Commands can use different targets. **Generate checksum file** uses the whole
current folder when nothing is marked; it does not fall back to the cursor.
Check the command's guide before acting on a group.

## Copy A Particular Group

1. Open the source and destination in opposite panes. In the source, press
   ++ctrl+d++ to clear old marks.
2. Run **Select by pattern** and enter `*.pdf$`. Review the preview, then press
   ++enter++ to commit. `report.pdf` matches; `report.pdf.bak` does not.
3. Press ++f5++, check the proposed destination and confirm. Only the committed
   group is copied. A folder with a matching name can be part of that group too.

See [illustrated selection](basics.md#select-by-pattern) and
[F5/F6 versus Robocopy](tools.md#f5f6-or-robocopy).

## Rename An Ordered Subset

1. Mark the regular files in one local folder. Run **Batch File Renamer**.
2. Sort **Original Name** or **File Date**, then filter the source columns to
   keep only the files you want. Filtered-out files will not be renamed.
3. Enter `{(index + 1):03d}_{name}{ext}`. Review **New Name** and **Valid Name**.
   The first visible `report.txt` becomes `001_report.txt`.
4. Press ++enter++ to rename the visible results, or ++esc++ to cancel.

Keep `{ext}` to retain extensions. Invalid or occupied names block the rename;
there is no automatic undo. See [templates and limits](tools.md#batch-file-renamer).

## Find Large, Old Files

1. Open the folder to search and press ++shift+f7++ for **Find files with fd**.
2. Set **Name Pattern** to `*.log` in Glob mode, **Min** size to `100` Mega Bytes
   and **End** date to `2026-09-30`. Enable **Recursive**, then Search.
3. Sort results by Size or narrow the Modified column. On a path cell, press
   ++ctrl+enter++ to open its folder and highlight that one file.

This finds logs of at least 100 MB modified on or before the chosen date.
It does not mark all search results in the pane. See [Find with fd](search.md#find-with-fd).

## Find And Edit Matching Content

1. Open the project folder and press ++alt+f7++. Set File Name Pattern to
   `*.ini` in Glob mode and Content Pattern to `fonts` in Literal mode.
2. Enable **Recursive** and **Extended**, then Search. Narrow results using
   Size, Date Modified or the text filter.
3. Press ++ctrl+enter++ on a File Path cell. In the pane, use ++ctrl+q++ to
   inspect the file. Close QuickView with ++ctrl+q++, then press ++f4++ to edit.

Set up the [editor](configuration.md#text-editor-and-viewer) once before using F4.
Search results show matching lines; navigating opens the file's folder, not an
editor at that line. See [Search Files](search.md#search-files).

## Verify A Delivery

1. In the source folder, clear any pane filter with ++esc++ and ensure hidden
   files are shown (toggle with ++ctrl+period++ if needed). Clear marks with
   ++ctrl+d++. Run **Generate checksum file**, choose SHA256 and save the manifest
   there. With no marks, generation covers the current folder recursively,
   including hidden files.
2. Select the data and manifest with ++ctrl+a++ and copy them with ++f5++ into
   an empty destination folder in the other pane. Keep the relative folder layout.
3. In the destination, highlight the manifest and run **Verify checksum file**.
   Inspect the summary and any problem rows.

Verification checks the manifest's entries, not files absent from it. Generate
the manifest after renaming: later name changes invalidate its recorded paths.
See [Checksum Files](tools.md#checksum-files).

## Compare Two Versions

1. Configure **Set file comparator** once, choosing an installed program.
2. Highlight one file in each pane and clear old marks in both. Run **Compare
   files**. Alternatively, mark exactly two files in the active pane to compare
   that pair instead.
3. To compare folder trees, open one folder in each pane and run **Compare
   folders**. It uses the pane locations, not highlighted child folders.

The external program controls its views and edits; no automatic synchronization
is performed. See [comparator setup](configuration.md#file-and-folder-comparators).

For folder totals before choosing what to transfer, see
[one-time versus automatic directory sizes](tools.md#one-time-or-automatic-totals).