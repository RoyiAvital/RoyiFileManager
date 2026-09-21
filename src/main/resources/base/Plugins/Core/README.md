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

## Hidden Files

Windows local panes reuse ordinary entries' own hidden attributes from directory
enumeration. After another application changes these attributes, press `Ctrl+R`
to refresh; toggling hidden-file visibility alone need not rescan the directory.
Roots, UNC paths, links/reparse entries (including cloud placeholders), and
unavailable attributes retain the existing Qt visibility checks. Full file
metadata and file-operation behavior are unchanged.

## QuickView

On Windows, `Ctrl+Q` / **Toggle QuickView** previews the file under the source
cursor over the other pane, including its address bar. Marked files do not choose
the preview. JPEG, PNG and BMP are supported; loading errors appear inline.
QuickView starts off at every launch and does no image work while off.

| Control | Action |
| --- | --- |
| Source `Tab` | Focus QuickView instead of the covered file list |
| QuickView `Tab`, `Shift+Tab`, `Escape` | Return to source without closing |
| `Ctrl+Q` or close icon | Close QuickView |
| Fit / `F` | Fit without enlarging small images |
| 100% / `1` | One image pixel per physical screen pixel |
| `+`, `-`, zoom buttons, `Ctrl+wheel` | Zoom between 5% and 800%; Fit can be smaller |
| Arrows / `Shift+arrows` | Pan 32 / 128 logical pixels |
| Drag, wheel / `Shift+wheel` | Pan with mouse, vertically / horizontally |

Image keys apply only while QuickView has focus. Other keys first focus the
source and use its existing shortcut dispatch, including Command Center.
An unbound key is consumed, not typed into the source filter. Custom source Tab
bindings retain their normal precedence. File operations still use the actual
covered directory as their opposite-pane destination; QuickView does not block
operations or restore old directory state when closed.

Command Center also offers **QuickView: Fit**, **100%**, **Zoom in**, **Zoom out**
and **Pan** when an image is ready. Their command IDs are `quick_view_fit`,
`quick_view_actual_size`, `quick_view_zoom_in`, `quick_view_zoom_out` and
`quick_view_pan`; Pan accepts `direction` (`left`, `right`, `up`, `down`, default
`down`) and `large` (default `false`). These commands have no additional default
bindings. Only explicit Fit/100% preferences are saved to `QuickView.json` under
UserSettings, using `image_mode` values `fit` and `actual_size`.

Local and accessible UNC regular files are supported, including resolved local
symlinks. Limits are 64 MiB encoded, 128 million pixels and 65,536 pixels per edge.
The normalized image can use about 488 MiB; temporary decoding/conversion buffers
can exceed that substantially. Only the first image/frame is shown. No archive
extraction, animation, SVG rasterization, video, text preview, prefetch or image
cache is included. Cancellation discards stale results; it cannot interrupt a
blocked native read, but disabling QuickView and exiting do not wait for it.

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

## Text Editor and Viewer

- `F3` / **View**: open the file under the cursor in the configured viewer.
- `F4` / **Edit**: open it in the independently configured editor.
- `Shift+F4` / **Edit new file**: create a file, if missing, then open it in the editor.
- `Ctrl+N` / **New file**: create an empty file without opening the editor.
  Existing files are left unchanged.

Press `Ctrl+Shift+P` and run **Set text editor** or **Set text viewer**.
Choose Notepad++, CudaText, Notepad 4, EmEditor, or **Manual configuration**.
Browse to the program's `.exe`, or type/paste its path in the file picker.
Presets need only the executable; Manual also asks for arguments, which may be
empty. Cancel leaves settings unchanged. If a role is unset, F3/F4 only display
`No text viewer was set. Use "Set text viewer" in Command Center to define a text viewer.`
(or the equivalent editor message); they never open setup automatically.
Only existing local files can be viewed or edited.

The last item in each setup list is **Clear editor** or **Clear viewer**, after
Manual configuration. It immediately clears only that role and shows a brief
confirmation, without asking for an executable or arguments. The other role is
unchanged. No extra Command Center commands are added.

Manual arguments use Windows quoting, for example
`--session "C:\My Files\session.ini"`. Do not include the executable or a file
placeholder: the selected file's full path is appended automatically as one
argument. `""` passes an empty argument. Braces, `%VARIABLE%` and shell operators
are literal; launches do not use a shell.

| Preset | Editor arguments | Viewer arguments |
| --- | --- | --- |
| Notepad++ | `-multiInst -nosession -notabbar` | `-multiInst -nosession -notabbar -ro` |
| CudaText | `-n -ns -nh` | `-r -n -ns -nh` |
| Notepad 4 | `-ns` | `-ro -ns` |
| EmEditor | `-nr -sp` | `-nr -sp -r` |

These are convenience defaults, **not a read-only guarantee**.
The user is responsible for the chosen program's behavior. Use Manual configuration to
customize the arguments for any program. No detection or installation occurs.
Saved configurations are not updated automatically; select the preset again in
**Set text editor** or **Set text viewer** to apply changed defaults.

Each configured role stores only `executable` and an `arguments` list in the
user-layer Core Settings JSON under `UserSettings/Plugins/User/Settings`.
Clearing stores `null` so inherited settings cannot restore the program after a
restart. Clearing an already-unset role does not save again. The roles are
independent. Existing legacy editor launch mappings, including their `{file}`
templates and `cwd`/`shell` options, still work until explicitly reconfigured.

## File and Folder Comparators

Use **Set file comparator** and **Set folder comparator** in Command Center
(`Ctrl+Shift+P`). Choose Meld, Beyond Compare, WinMerge, SmartSynchronize or
**Manual configuration**, then select the installed `.exe`. The two roles are
independent; no tool is installed or detected automatically. Manual setup also
asks for Windows-quoted arguments. Do not include path placeholders: two absolute
paths are appended as separate arguments, without a shell or variable expansion.

| Preset | File arguments | Folder arguments | Window behavior |
| --- | --- | --- | --- |
| Meld | None | None | Uses default new-window behavior; no `--newtab`. |
| Beyond Compare | `/solo` | `/solo` | Requests a separate instance. |
| WinMerge | `/s- /u` | `/s- /u /r` | Requests a separate instance; folders recurse. |
| SmartSynchronize | None | None | Uses two-path invocation; separate-window behavior is unverified. |

**Compare files** chooses operands as follows:

- Exactly two marked entries in the active pane: compare that pair in stable
	filename order, ignoring the other pane. Both must be files.
- Otherwise use one file from each pane: its marked file, or its cursor file
	when nothing is marked. Keep physical left/right pane order, regardless of focus.
- More than two active marks, multiple opposite marks in cross-pane mode, missing
	files or folders selected as files are errors. No same-name guessing or fallback.

**Compare folders** always compares the two panes' current folders, in left/right
order, ignoring marks and cursors. Open child folders in both panes first to compare
them. These commands have no default shortcuts; custom bindings can use
`compare_files` and `compare_folders`. The existing **Compare directories** command
is different: it only marks names missing from the opposite pane.

Only existing local filesystem paths, including accessible UNC shares and links,
are accepted. Aliases of the same filesystem object are rejected. If a filesystem
or drive provider does not expose a usable file identity (`st_ino` is zero),
comparison stops with "Cannot determine the identity"; path spelling alone cannot
reliably detect aliases. Binary files may be passed through, but available views
and formats depend on the external tool.
Archives and other virtual locations are not extracted or downloaded.

Launches are fire-and-forget: capture the pair once, validate it off the UI thread,
then start the program without waiting for exit or interpreting comparison results.
Later navigation does not retarget or cancel that pair. Slow validation supports
Cancel; a blocked filesystem call must return before cancellation finishes, and
only one validation per window can be pending. After launch, the comparator is
independent. No automatic merge, synchronization, pane refresh or process monitoring
is added; user-directed edits in the external program remain possible.

Canceling setup leaves settings unchanged. **Clear file comparator** or
**Clear folder comparator**, last in the respective setup list, clears only that
role. Unconfigured commands point to setup without opening it automatically.
Settings persist as `file_comparator` / `folder_comparator` objects containing
`executable` and `arguments` in user-layer Core Settings JSON. Clearing stores `null`;
other roles and editor/viewer settings are preserved. A concurrent change to the
same role during setup requires retrying. Preset switches follow vendor CLI
documentation; verify behavior with the installed version, especially new windows.

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
