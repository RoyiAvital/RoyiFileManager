# File Management, Focused

RoyiFileManager shows two folders at once (Dual Pane).

Open a source on one side. Open a destination on the other. Then copy or move.

<figure class="product-shot" markdown>
  ![RoyiFileManager showing C drive and Windows folder](assets/royifilemanager-dual-pane.png)
  <figcaption>RoyiFileManager showing C:\ and C:\Windows.</figcaption>
</figure>

## Start Here

| Action | Key |
| --- | --- |
| Switch panes | ++tab++ |
| Open | ++enter++ |
| Go up | ++backspace++ |
| Select | ++space++ |
| Copy | ++f5++ |
| Move | ++f6++ |
| New folder | ++f7++ |
| Delete to Recycle Bin | ++f8++ |

## Transfer Files Between Panes

1. Open the source folder in one pane and the destination folder in the other. Press ++tab++ to switch panes.
2. In the source pane, use ++space++ to mark the files you want. With no marked files, the file under the cursor is the target.
3. Press ++f5++ to copy or ++f6++ to move the chosen files into the other pane's folder. Review any confirmation before proceeding.
4. Switch to the destination pane to check the result.

See [Keyboard Shortcuts](shortcuts.md) for more file operations.

## Command Center

Press ++ctrl+shift+p++.

Type an action. Press ++enter++.

The Command Center is the fastest way to discover features.

<figure class="product-shot" markdown>
  ![RoyiFileManager Command Center](assets/royifilemanager-command-center.png)
</figure>

## Find a Location

Press ++ctrl+p++.

Type part of a folder path. Choose a result.

<figure class="product-shot" markdown>
  ![RoyiFileManager Find a Location window](assets/royifilemanager-find-location.png)
</figure>

## Filter a Pane

Start typing while a pane has focus.

Use `*.pdf` for PDF names. Use `^report` for names that start with `report`.

Press ++esc++ to clear the filter.

<figure class="product-shot" markdown>
  ![RoyiFileManager pane filtered to executable files](assets/royifilemanager-filter-pane.png)
</figure>

## Start in Specific Folders

From PowerShell in the extracted application folder, pass one or two directory paths:

```powershell
.\RoyiFileManager.exe "C:\Work\Incoming" "C:\Work\Archive"
```

The first path opens in the left pane; the second opens in the right. Replace the example folders with ones that exist on your computer. With no paths, RoyiFileManager restores the previous pane locations.