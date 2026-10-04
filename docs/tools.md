# Tools

## QuickView

Press ++ctrl+q++.

QuickView previews the file under the cursor over the other pane.
Both folder locations stay unchanged.

### QuickView for Images

<figure class="product-shot" markdown>
  ![QuickView showing a Windows wallpaper](assets/royifilemanager-quickview.png)
  <figcaption>Preview an image without leaving its folder.</figcaption>
</figure>

- View JPEG (`.jpg`, `.jpeg`), PNG, BMP, GIF, ICO, TIFF (`.tif`, `.tiff`) and WebP images.
- Fit, zoom and pan the image.
- Show it at 100% or copy its decoded pixels.
- Animated images show a still frame. Format availability depends on the bundled Qt codecs.

### QuickView for Text based Files

<figure class="product-shot" markdown>
  ![QuickView showing syntax-highlighted Python code](assets/royifilemanager-quickview-python.png)
  <figcaption>Read Python source with syntax highlighting.</figcaption>
</figure>

- Read plain text and syntax-highlighted source code.
- Switch Markdown between **Rendered** and **Source** modes.
- Select text, then press ++ctrl+c++ or right-click and choose **Copy**.
- With the preview focused, press ++ctrl+f++ to open Find, ++f3++ for the next match or ++shift+f3++ for the previous match.

Text reads stop at 2 MiB, formatting stops at 512 KiB, with plain-text fallback.
Markdown external resources are blocked.

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

## Everything Search

Press ++ctrl+e++ to search your indexed folders, independently of either pane.
Everything searches names and paths, not file contents, and uses its own syntax
rather than fuzzy matching.

1. Open Command Center with ++ctrl+shift+p++ and run **Add folder to Everything database**.
  Or run **Add favorite folders to Everything database** to import local favorites in one batch.
2. Wait for **Everything database is ready**, then press ++ctrl+e++ and enter a query.
3. Press ++enter++ to enter a folder or select a file in its containing folder.
   Press ++esc++ to cancel.

Folder updates normalize paths, remove duplicates and omit children already
covered by a parent. Replacing indexed children with a parent asks for confirmation.
Favorites import is one-time, preserves unavailable local paths and does not
change Favorites; unsupported entries are skipped and reported.

### Folder Manager

Run **Manage Everything database folders** from Command Center. It opens
`everything-folders://` in the active pane with **Name** and **Path** columns.
Opening the manager does not start Everything or check target availability.

<figure class="product-shot" markdown>
  ![Everything folder manager showing Name and Path columns beside a normal file pane](assets/royifilemanager-everything-folders.png)
  <figcaption>Manage indexed roots using the existing pane selection, filtering and sorting controls.</figcaption>
</figure>

| Action | Behavior |
| --- | --- |
| Type / ++ctrl+f++ | Filter the list / fuzzy-find folder names |
| Click a column header | Sort by Name or Path |
| ++enter++ / double-click | Open the real folder; unavailable roots stay listed |
| ++f11++ | Copy the selected roots' real paths |
| ++f8++ / ++delete++ / ++shift+delete++ | Remove selected roots after confirmation, never their files |
| ++f5++ from the other pane | Add selected local folders to the index without copying files |
| Drop folders onto the manager | Add them to the index, including drops onto an existing row |
| ++ctrl+r++ | Reload the configured root list |

Each batch is normalized and saved once. Open manager panes refresh together,
preserving surviving selections. Removing the last root stops the managed process.
Rename, move, archive and file-creation operations are refused for index entries.

**Add folder to Everything database** and **Add favorite folders to Everything database**
remain Command Center commands. Favorites import has no special row in the manager.
The old **Remove folder from Everything database** command has been removed;
use the manager's selection and Delete actions instead.

The following captures use a real, isolated Everything index containing only
`C:\Windows\Web` and `C:\Windows\Fonts`. File names, sizes and dates vary by Windows installation.

### Example: Large Images

```text
ext:jpg;png size:>100kb !img0
```

- `ext:jpg;png` accepts either JPEG or PNG extensions.
- `size:>100kb` requires a file larger than 100 KiB.
- `!img0` excludes names containing `img0`.
- Spaces combine these conditions with AND.

<figure class="product-shot" markdown>
  ![Everything search showing JPEG and PNG files larger than 100 KiB, excluding img0](assets/royifilemanager-everything-images.png)
  <figcaption>Extension alternatives, a size comparison and an exclusion in one query.</figcaption>
</figure>

### Example: Font Alternatives

```text
path:Fonts\ <consola|segoe> ext:ttf !*b.ttf
```

- `path:Fonts\` requires `Fonts\` in the full path.
- `<consola|segoe>` groups an OR: the name contains either `consola` or `segoe`.
- `ext:ttf` keeps TrueType files.
- `!*b.ttf` excludes names ending in `b.ttf`. This tests the filename, not the font's weight.

<figure class="product-shot" markdown>
  ![Everything search showing grouped Consolas or Segoe font matches with path and extension filters](assets/royifilemanager-everything-fonts.png)
  <figcaption>Grouped alternatives combine with path filtering and a wildcard exclusion.</figcaption>
</figure>

Results include match highlights, modification date and size. The default limit
is 100; a count row after the results indicates truncation. If the index is starting or busy, wait
and edit or retry the query; unchanged text does not refresh automatically.
If Everything exits or its process identity changes, reopen search to retry.
The retry will not take over a foreign instance.

Everything starts lazily. Its index and runtime state stay under
`UserSettings/Local/Everything`; configured roots are saved in User Settings.
It does not install a service or control your unnamed Everything instance.

See [Everything settings and portability](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/Everything/README.md)
and the [official Everything syntax reference](https://www.voidtools.com/support/everything/searching).

## Search Files

Press ++alt+f7++.

Search file names, file contents or both based on [`ripgrep`](https://github.com/burntsushi/ripgrep).

<figure class="product-shot" markdown>
  ![Search Files panel with name and content patterns](assets/royifilemanager-search-files.png)
  <figcaption>Search INI files containing “fonts” under C:\Windows.</figcaption>
</figure>

- Choose _Literal_, _Glob_ or _RegEx_ for each field.
- Leave Content Pattern empty for a name only search.
- Include subfolders with Recursive.
- Stop background work and keep results collected so far.
- Narrow, sort and open the results in the [results table](search.md#results-table).

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
- Sort and filter path, size and modified time in the [results table](search.md#results-table).

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

## Checksum Files

Press ++ctrl+p++ and run **Generate checksum file** or **Verify checksum file**.
Both commands are bundled with the application.

- Generate from marked files and folders, recursively. With no marked selection,
  include the entire current folder. SHA256 is the default; twelve algorithms
  are available, including native BLAKE3.
- The suggested output name is the folder name plus the algorithm's extension,
  or `checksums` at a drive/share root. Replacement requires confirmation.
- Verify the highlighted supported checksum file, or the first supported file
  in case-insensitive filename order. Verification checks every manifest entry.
- Results open in a non-modal table with the summary above it. Every result is
  listed when the complete view fits the display limit; otherwise only problems
  are listed and the summary says so. Use the column filters to narrow the view.
- A navigated junction root is supported; redirected paths below that root are
  refused. Cancellation or a read failure prevents publication of a generated file.

<figure class="product-shot" markdown>
  ![Checksum verification results listing three matched files](assets/royifilemanager-checksum-results.png)
  <figcaption>All three sample files matched. The table stays open while you work in the panes.</figcaption>
</figure>

Five supplied Total Commander formats are verified. Other TC/DC profiles and
network-storage checks remain unverified; writer-reader roundtrips alone do not
establish interoperability.

See [Checksum Files usage and compatibility](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/ChecksumFiles/README.md).

## Process Pane

Run **Show OS' processes** from the Command Center.

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