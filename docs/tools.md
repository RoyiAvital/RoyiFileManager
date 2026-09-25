# Tools

## QuickView

Press ++ctrl+q++.

QuickView previews the image under the cursor over the other pane.

<figure class="product-shot" markdown>
  ![QuickView showing a Windows wallpaper](assets/royifilemanager-quickview.png)
  <figcaption>Preview an image without leaving its folder.</figcaption>
</figure>

- View JPEG, PNG and BMP images.
- Fit, zoom and pan the image.
- Show it at 100% or copy its decoded pixels.
- Keep both folder locations unchanged.

## Fuzzy Find

Press ++ctrl+f++ for the current folder.

Press ++ctrl+shift+f++ to include subfolders.

<figure class="product-shot product-shot--compact" markdown>
  ![Recursive fuzzy find showing Windows image files](assets/royifilemanager-fuzzy-find-recursive.png)
  <figcaption>Recursive results use paths relative to the current folder.</figcaption>
</figure>

- Match incomplete names and paths.
- Combine terms, such as `wall img`.
- Use `'text` for exact text, `^src` for a prefix, `.py$` for a suffix or `!tmp` to exclude.
- Press ++enter++ to open the containing folder and select the file.

## Search Files

Press ++alt+f7++.

Search file names, file contents or both.

<figure class="product-shot" markdown>
  ![Search Files panel with name and content patterns](assets/royifilemanager-search-files.png)
  <figcaption>Search INI files containing “fonts” under C:\Windows.</figcaption>
</figure>

- Choose Literal, Glob or RegEx for each field.
- Leave Content Pattern empty for a name-only search.
- Include subfolders with Recursive.
- Stop background work and keep results collected so far.
- Open results by path and matching snippet.

## Find Files with `fd`

Press ++shift+f7++.

Use `fd` for precise file-system searches.

<figure class="product-shot" markdown>
  ![Find Files panel configured to locate Notepad executables](assets/royifilemanager-find-files-fd.png)
  <figcaption>Find Notepad executables under C:\Windows.</figcaption>
</figure>

- Filter by name, extension, exclusion, date, size or type.
- Choose Glob, Literal or RegEx matching.
- Control hidden files, ignore rules and symbolic links.
- View path, size and modified time in the results.

## Favorites

Press ++ctrl+b++.

Favorites keeps a list of frequently used locations.

<figure class="product-shot" markdown>
  ![Favorites Manager listing Windows folders](assets/royifilemanager-favorites.png)
  <figcaption>Open, rename or delete saved locations.</figcaption>
</figure>

- Run **Add current folder to favorites** to save the active pane's folder.
- Type to filter by name or path. Sort by Recent, Name or Path.
- Press ++enter++ or **Go To** to open the highlighted favorite.
- **Rename** changes only the display name. **Delete** removes favorites, never files.
- Press ++esc++ to close.

See [Favorites usage](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/Favorites/README.md).

## Directory Size

Press ++ctrl+shift+d++.

Folder totals appear in the Size column of both panes.

<figure class="product-shot" markdown>
  ![Directory sizes in the Size column](assets/royifilemanager-directory-size.png)
  <figcaption>Folder totals under C:\Windows\Web.</figcaption>
</figure>

- `...` marks a total still being calculated.
- `+` marks a total that reached the file limit. `?` marks an error.
- Press ++ctrl+f4++ to sort by directory size.
- Press ++ctrl+shift+enter++ for a one-time total of the selected folders.
- The setting is kept across restarts. Links and junctions are not followed.

See [Directory Size usage](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/Core/README.md#directory-sizes).

## File Hash

Press ++ctrl+h++.

Calculate the SHA-256 hash of the file under the cursor.

<figure class="product-shot" markdown>
  ![SHA-256 hash of win.ini](assets/royifilemanager-file-hash.png)
  <figcaption>SHA-256 of C:\Windows\win.ini.</figcaption>
</figure>

- Run **Calculate file hash by** to choose SHA-384, SHA-512, SHA3, BLAKE2, MD5, SHA-1 or CRC32.
- Press ++enter++ or click the copy icon to copy the hash.
- Large files show progress and can be canceled.
- Press ++esc++ to close.

See [File Hash usage](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/CalculateFileHash/README.md).

## Process Pane

Run **Show processes** from the Command Center.

The active pane lists running processes by Name and PID.

<figure class="product-shot" markdown>
  ![Process pane filtered to svchost](assets/royifilemanager-process-pane.png)
  <figcaption>Filter processes by name.</figcaption>
</figure>

- Type to filter. Click a column to sort. Press ++ctrl+r++ to refresh.
- Press ++f8++ to end the process under the cursor after confirmation.
- Ending is forced: unsaved data in that process is lost.
- Only your current permissions are used. System and critical processes are refused.

See [Process Pane usage](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/ProcessPane/README.md).