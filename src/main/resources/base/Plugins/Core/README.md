# Core
The Core plugin implements most RoyiFileManager features, including copying
files and navigating to folders. It retains the public `fman` plug-in API for
compatibility with existing plug-ins.

## Pane Filter

Start typing in a pane to filter file and folder names in place. Matching is
case-insensitive and searches anywhere in the name unless anchored.

| Input | Matches |
| --- | --- |
| `rep` | Names containing `rep`, including `Annual Report.pdf` |
| `rep*2024` | `rep` followed anywhere by `2024` |
| `r?p` | `r`, one character, then `p` |
| `[abc]`, `[a-z]`, `[!x]` | One character in the set/range, or anything except `x` |
| `^rep`, `.py$` | Names starting with `rep`, or ending in `.py` (not `.pyc`) |
| `!tmp` | Names that do not contain `tmp` |
| `\$`, `\[`, `\!` | Literal `$`, `[` or `!` |

`*` still means any sequence: `*.py` can match `.pyc`; add `$` for an exact
ending. Only leading `!`/`^` and trailing `$` are operators; `!`, `^`, `$`
and `^$` alone are literal. `\` escapes the next character, and a trailing
lone `\` is ignored. `[$]` also matches a literal dollar sign. An unfinished
`[` is literal; invalid ranges fall back to the whole query as literal text.
Queries are limited to 255 characters, including escapes.

The active pane reports `Filter "<text>": <matched> of <total> items` in the
existing status bar. Counts refresh after edits, reloads and file changes.
Other command messages can replace the count until the next update.
`Backspace` edits; deleting the final character, pressing `Escape`, or
navigating clears the filter and resets its status message to `Ready.`.
`Space` still toggles selection, even while filtering. Multiple-term AND
matching is not implemented; spaces supplied as filter text remain literal.

## Directory Sizes

- `Ctrl+Shift+D`: toggle automatic recursive totals for all directories listed
	in both local panes, inside the existing `Size` column. Alternatively, press
	`Ctrl+Shift+P` and run `Toggle directory
	sizes`. Starts Off and persists across restarts; successful toggles show an
	On/Off notification for five seconds. No column is added or removed.
- `Ctrl+F4` / `Sort by directory size`: sort by `Size` while directory totals
	are enabled; repeat to reverse direction. `Ctrl+F2` remains normal Size sorting.
- `Recalculate directory sizes`: clear current results and rescan both panes.
- `Ctrl+Shift+Enter` / `Show directory size`: calculate only the selected
	directories, or the directory under the cursor when nothing is selected.
	Shows `Calculating <path> size...` in the status bar, then a five-second result.
	Multiple selections show the directory count, then a combined total.
	No progress dialog opens. A new request replaces and cancels the previous
	one; closing the application also cancels it. Does not enable automatic
	totals or update column values, and works while automatic totals are Off.

File sizes are unchanged in both states. Enabled directory cells show `...`
while pending, a subtotal followed by `...` while running, and a plain size when
complete. `+` marks the configured file cap: `11.4 GiB+` means at least 11.4 GiB,
not a complete total. `?` marks an error or an unavailable total.
Linked directories are skipped. Off restores blank directory cells and Core's
normal directory-name ordering; it keeps the current sort column/direction,
location, filter, cursor, selection and widths.

Calculations are metadata-only and run off the UI/model threads. Results arrive
incrementally, without a cross-location cache. Enabling, navigating or running
Recalculate starts a fresh scan; external changes are not watched. Navigation
and Off never wait for a recursive walk, although an in-flight OS call must
return before its canceled worker can exit.

Only local `file://` directories are scanned. Root and descendant symlinks and
junctions are not followed. Totals are logical bytes, not allocated disk space
or a snapshot of concurrently changing files. Explicit totals retain cap/error
warnings; cancellation does not report an unfinished total as complete.

Core owns this feature, including its background service and commands. No
separate DirectorySize plug-in, column override or plug-in-to-Core hook is used.
Restart the updated application to discard a previously loaded standalone column.
Defaults are in code; overrides retain the existing settings location:
`UserSettings/Plugins/User/Settings/DirectorySize (Windows).json`.

```json
{
	"enabled": false,
	"max_files": 10000000
}
```

The default limit is 10,000,000 regular files per directory root, for both
automatic and one-time calculations. Directories do not consume the file limit.
Set `max_files` to `0` for unlimited progressive calculation, or a positive integer
for a custom cap. Invalid values use the default; restart after external settings
edits. Legacy `max_entries` is ignored so the former 200,000-entry default cannot
cap new scans. Legacy `show_file_sizes` is also ignored: ordinary file sizes are
always shown. Units follow
`size_divisor` in `Status Bar.json`. Existing custom command IDs remain valid:
`toggle_directory_size_column`, `sort_by_directory_size`,
`recalculate_directory_sizes` and `show_directory_size`.

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
