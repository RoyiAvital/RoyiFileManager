# Archives

{{ app_name }} works with archives as folders. It uses 7-Zip.

Supported extensions: `.zip`, `.zipx`, `.jar`, `.xpi`, `.7z` and `.tar`.

## Browse an Archive

Press ++enter++ on an archive to open it.

Navigate inside it like any folder. Press ++backspace++ at its root to return to the containing folder.

## Pack Files

Select files, then press ++alt+f5++.

<figure class="product-shot" markdown>
  ![Pack prompt for win.ini](assets/royifilemanager-pack-archive.png)
  <figcaption>The suggested archive goes to the other pane's folder.</figcaption>
</figure>

- Change the extension to `.7z` or `.tar` to choose the format.
- Packing into an existing archive asks before adding or updating files.
- The Command Center name is **Pack to archive (.zip, .7z, .tar)**.

## Unpack an Archive

Place the cursor on an archive, then run **Unpack archive** from the Command Center.

It works like **Extract Here**: `Reports.zip` in `C:\Work` creates `C:\Work\Reports`.

- The archive stays unchanged.
- An existing destination stops the operation. Nothing is merged or overwritten.
- Cancel removes unfinished output.

## Copy and Move

Use ++f5++ and ++f6++ between an archive and a folder, or between two archives.

- Extraction shows progress and can be canceled.
- Moving out of or between archives checks the copied files before removing them from the source. This takes extra time and temporary space.
- Avoid changing the archive or destination while an operation runs.
- There is no password prompt for encrypted archives.

See [Archive usage](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/Core/README.md#archive-transfers).
