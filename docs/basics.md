# File Management, Focused

{{ app_name }} shows two folders at once (Dual Pane).

Open a source on one side. Open a destination on the other. Then copy or move.

!!! info "Release Availability"
  Some instructions below require an Unreleased development build, including
  pane swapping, pattern selection and numbered duplicate suggestions.
  Check [feature availability](features.md#availability) for the full list.

<figure class="product-shot" markdown>
  ![{{ app_name }} showing C drive and Windows folder](assets/royifilemanager-dual-pane.png)
  <figcaption>{{ app_name }} showing C:\ and C:\Windows.</figcaption>
</figure>

## Start Here

| Action                | Key           |
| --------------------- | ------------- |
| Switch panes          | ++tab++       |
| Open                  | ++enter++     |
| Go up                 | ++backspace++ |
| Select                | ++space++     |
| Copy                  | ++f5++        |
| Move                  | ++f6++        |
| New folder            | ++f7++        |
| Delete to Recycle Bin | ++f8++        |

See [Everyday Workflows](workflows.md) for complete tasks and
[which items a command uses](workflows.md#which-items-will-change).

## Transfer Files Between Panes

1. Open the source folder in one pane and the destination folder in the other. Press ++tab++ to switch panes.
2. In the source pane, use ++space++ to mark the files you want. With no marked files, the file under the cursor is the target.
3. Press ++f5++ to copy or ++f6++ to move the chosen files into the other pane's folder. Review any confirmation before proceeding.
4. Switch to the destination pane to check the result.

See [Keyboard Shortcuts](shortcuts.md) for more file operations.

Press ++ctrl+u++ to swap the two pane locations without moving files.

### Drag and Drop

Drag files onto a pane or a folder in it, from the other pane or from Explorer.
As in Explorer:

| Drop                            | Action |
| ------------------------------- | ------ |
| Onto a folder on another drive  | Copy   |
| Onto a folder on the same drive | Move   |
| With ++ctrl++ held              | Copy   |
| With ++shift++ held             | Move   |

Network shares count as separate drives. Files dragged out of archives are
always copied.

### Duplicate In The Same Folder

**Duplicate item** in Command Center, or **Duplicate...** in the context menu,
suggests `name Copy 1.ext` in the current folder.
Existing numbered copies continue the series; you can edit the suggested name.

<figure class="product-shot" markdown>
  ![Copy prompt suggesting report Copy 2.txt because report Copy 1.txt already exists](assets/royifilemanager-duplicate-file.png)
  <figcaption>The next available name is suggested. Enter copies; Cancel creates nothing.</figcaption>
</figure>

## Command Center

Press ++ctrl+shift+p++.

Type an action. Press ++enter++.

The Command Center is the fastest way to discover features.

Commands are grouped by category, for example **File: Copy** or
**Settings: Edit settings**. Type a category name such as `view` to list its
commands, or type the command name directly.

Try **Bookmarks** for Favorites, **Extract archive** for Unpack, or **Preview**
for QuickView. These are alternate names for the same commands.

<figure class="product-shot" markdown>
  ![{{ app_name }} Command Center](assets/royifilemanager-command-center.png)
</figure>

## Find a Location

Press ++ctrl+p++.

Type part of a folder path. Choose a result.

<figure class="product-shot" markdown>
  ![{{ app_name }} Find a Location window](assets/royifilemanager-find-location.png)
</figure>

**Go to clipboard path** opens one copied absolute path or application URL.
A file path opens its folder and highlights the file. Relative paths, multiple
lines and standard percent-encoded `file:///` URIs are refused.
File paths normalize separators and `.`/`..` before navigation; literal `%20` stays literal.

**Go to link target** resolves the highlighted symbolic link or junction on demand.
Folders open at the target; files are highlighted in their parent folder.
Missing paths, link cycles, access errors and unsupported Windows namespace targets
are reported without navigation.

## Filter a Pane

Start typing while a pane has focus.

Use `*.pdf` for PDF names. Use `^report` for names that start with `report`.

Press ++esc++ to clear the filter.

While the Filter Bar is open, keypad `+`, `-` and `*` type into it; Space still toggles marks.
With NumLock off, keypad navigation and Insert retain their normal actions.

<figure class="product-shot" markdown>
  ![{{ app_name }} pane filtered to executable files](assets/royifilemanager-filter-pane.png)
</figure>

### Match An Exact Extension

Pane patterns search within names unless anchored. A trailing `$` means the end
of the name. Compare the same three entries:

| Name             | `*.pdf`  | `*.pdf$` |
| ---------------- | -------- | -------- |
| `report.pdf`     | Matches  | Matches  |
| `report.pdf.bak` | Matches  | No match |
| `report.txt`     | No match | No match |

Use `*.pdf$` when you want only `.pdf` endings. The same rule applies to
Select/Deselect by pattern, not to every search tool's Glob mode.

## Select By Pattern

With the Filter Bar closed, press keypad **+** to select a group or keypad **-**
to deselect a group. With a filter open, use Command Center to start these modes.

### Add Matching Marks

1. Mark any files you want to keep, such as `README.md`.
2. Highlight `report.txt` and press keypad **+**. The suggested `*.txt$` matches
   `.txt` endings, not `.txt.bak`.
3. Review the preview count. **Enter** applies it; **Esc** keeps the original marks.

<figure class="product-shot" markdown>
  ![Select preview for three text files, retaining the existing README.md mark](assets/royifilemanager-select-preview.png)
  <figcaption>Three matching files plus the existing mark: four prospective marks. No rows are hidden.</figcaption>
</figure>

### Remove Matching Marks

Press keypad **-** and type `^draft` to preview removing marks from names starting
with `draft`. Unrelated marks stay. Enter applies; Esc cancels.

<figure class="product-shot" markdown>
  ![Deselect preview removing two draft-file marks while retaining README.md and report.txt](assets/royifilemanager-deselect-preview.png)
  <figcaption>Removing the two draft marks would leave two marked files.</figcaption>
</figure>

| Pattern     | Matches                               |
| ----------- | ------------------------------------- |
| `*.txt$`    | Names ending in `.txt`, ignoring case |
| `^draft`    | Names beginning with `draft`          |
| `!*.txt$`   | Names not ending in `.txt`            |
| Empty input | Keep the original marks               |

Only visible rows participate, including folders. Existing filters stay applied.
Space and keypad punctuation edit the pattern while a preview is open.

!!! info "Preview Is Not Applied Yet"
    Other commands dismiss the preview and use only the original committed marks.
    Press Enter before copying or deleting the previewed group.

### Invert Or Match An Extension

Keypad **\*** swaps marked and unmarked visible entries when the Filter Bar is
closed. In Command Center, **Invert selection** also works with a filter open.

**Select same extension** immediately marks visible files matching the highlighted
file's final extension. `archive.tar.gz` matches `.gz`; folders are excluded and
unrelated marks stay. There is no default shortcut.

<figure class="product-shot" markdown>
  ![archive.tar.gz and backup.gz marked by Select same extension, with README.md still marked](assets/royifilemanager-select-extension.png)
  <figcaption>The final .gz extension matches both archives; the existing README.md mark is retained.</figcaption>
</figure>

See the [selection shortcuts](shortcuts.md#selection-and-display) and
[full pattern syntax](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/Core/README.md#pane-filter).

## Free Space

Press ++ctrl+s++ for extended status. Local NTFS/ReFS locations show
**Free: available of total**. Unsupported locations leave this field empty.
When extended status is disabled, no free-space queries run.

<figure class="product-shot" markdown>
  ![Extended status bar showing available and total space for the active local volume](assets/royifilemanager-free-space.png)
  <figcaption>Free space appears at the right of the status bar. Values depend on the active volume.</figcaption>
</figure>

## Start in Specific Folders

From PowerShell in the extracted application folder, pass one or two directory paths:

```powershell
.\{{ app_name }}.exe "C:\Work\Incoming" "C:\Work\Archive"
```

The first path opens in the left pane; the second opens in the right. Replace the example folders with ones that exist on your computer. With no paths, {{ app_name }} restores the previous pane locations.