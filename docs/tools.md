# Main Tools

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