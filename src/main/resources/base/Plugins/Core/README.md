# Core
The Core plugin implements most RoyiFileManager features, including copying
files and navigating to folders. It retains the public `fman` plug-in API for
compatibility with existing plug-ins.

## Archive Transfers

Enter an archive as a folder, select items, then use the existing Copy or Move
workflow. Extraction reports 7-Zip progress when available. Cancel stops
extraction and removes unfinished staging; completed items remain.

Moving out of or between archives verifies file contents before removing source
entries. Cross-archive Move re-extracts the destination for verification. These
checks deliberately add reads, temporary space, and time. During an archive
update, Cancel waits for that update and empty-parent restoration to finish.
Source-update failure stops the operation and retains the copied output.

Avoid editing either archive or the destination concurrently. Change detection
does not lock files or guarantee recovery from crashes or storage failure.
Verified Moves reject symbolic links, junctions, and the archive root itself;
select its contents instead. Local-to-archive Move and same-archive rename keep
their existing behavior.

## Unpack Archive

Select one local archive (or leave it under the cursor), then run **Unpack archive**
from the Command Center. In a pane showing `C:\Work`, `Reports.zip` creates
`C:\Work\Reports\`. The other pane is not used; there is no destination chooser.
The source archive stays unchanged. Any existing destination file, folder or
link, including an empty folder, causes an alert and stops extraction. Unpack
never merges, overwrites or automatically renames the destination.

The existing progress dialog supports Cancel. Before publication, cancellation
removes unfinished output; a folder already published is retained. A temporary
sibling holds extracted contents until publication, requiring free space only
for those contents. Unpack reads the archive directly, without a snapshot copy
or a post-extraction tree scan.

Core's ZIP-family, 7Z and TAR handlers are used; custom extraction tasks are not
supported. Naming collisions and names that 7-Zip may rewrite are rejected before
extraction. Links, attributes and extraction errors use 7-Zip's normal behavior;
no password prompt is provided. Concurrent archive changes are unsupported;
a size/mtime comparison detects some changes, not all.

The existing archive-path parser can confuse overlapping suffixes such as
`.zip`/`.zipx` or archive-looking parent names such as `backup.zip.old`.
Unpack rejects a misidentified source instead of extracting the wrong archive.
`archive.zip.7z` can produce the ordinary folder `archive.zip`; browsing it is
local, but later archive operations beneath it may hit the same parser limitation.

## Examples

* [Key Bindings.json](Key%20Bindings.json) defines the default key bindings
* [Theme.css](Theme.css) defines fman's visual appearance (to [some extent](https://github.com/fman-users/fman/issues/45))
* [commands/](core/commands/__init__.py) implements virtually all commands
* [local/](core/fs/local/__init__.py) lets fman work with the files on your local hard drive
* [zip.py](core/fs/zip.py) adds support for ZIP files

## Location in your installation directory
You can also find these source files in your fman installation directory. Their exact path depends on your operating system:

 * **Windows:** `C:/​Users/​<username>/​AppData/​Local/​fman/​Versions/​<version>/​Plugins/​Core`
 * **Mac:** `/​Applications/​fman.app/​Contents/​Resources/​Plugins/​Core`
 * **Linux:** `/opt/​fman/​Plugins/​Core`
