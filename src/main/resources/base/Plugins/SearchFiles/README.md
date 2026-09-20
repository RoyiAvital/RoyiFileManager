# Search Files

Press **Alt+F7** in a local folder, or use **Search files** in the command
palette. The Panel stays tied to that pane. A half-filled square marks it; hover for
"Left pane" or "Right pane". Its folder follows that pane while idle. Changing
the other pane has no effect.
An active search and its results keep their captured root until results close,
then the form catches up. Search is disabled when that pane is not in a local folder.

Each field has three mutually exclusive icon buttons: text lines for **Literal**,
an asterisk for **Glob**, and the regex symbol for **RegEx**. Hover for the matching
rule; field labels and inputs share their tooltips.

| Mode | File Name Pattern | Content Pattern |
| --- | --- | --- |
| Literal | Literal text anywhere in the basename. | Literal text anywhere in a line; default. |
| Glob | Basename masks such as `*.txt;*.md;!secret*`; default. | A glob matched anywhere in a line: `cuda`, `*cuda*` and `cu?a` find `cuda`. |
| RegEx | One expression searched against the basename. | One expression searched against each line. |

All modes are case-insensitive and spaces are significant. Leave Content Pattern
empty to list files by name alone in any name mode, for example `*.log` in Glob
or `^report_\d{4}` in RegEx. Each result is one file with an empty Snippet and
path-only details; binary and empty files are included without reading contents.
Directories are not results. Both patterns empty shows
`Enter a file name or content pattern.` without starting a search.

With content supplied, an empty filename selects all eligible files.
Regex uses ripgrep's default engine, without lookaround/backreferences.
For example, select Filename Glob
with `*.cmd` and Content Glob with `*cuda*`. Content Literal with `cuda` also
finds lines containing cuda, while Literal `*cuda*` includes the asterisks.

Content globs support `*`, `?`, `[abc]`, `[a-z]` and `[!abc]`. Use `[*]`, `[?]`
and `[[]` for literal wildcard characters. An initial `]` within a set and
edge-position `-` are literal; invalid sets/ranges report an error. Other regex
characters and backslashes are literal. Slash and repeated stars have no path
meaning. No content brace expansion, exclusion masks or semicolon splitting.
Leading and trailing `*` do not widen the highlight; internal wildcards remain
part of the match. `*` or `**` alone matches whole lines, including blank ones.
For whole-line matching, use RegEx anchors such as `^cuda$`.

- **Recursive:** include subfolders. **Search** starts background work;
  **Stop** keeps collected results and does nothing while idle.
  These three icon buttons align below the mode buttons, with 3-pixel gaps.
  Hover for labels. Stop stays enabled and its square icon is red.
  Closing/replacing the Panel cancels the run and prevents a later results window.

After collection, the form stays locked while results await an active window
and while the modal is open. Dismiss results to edit the form or search again.

Results appear only after collection finishes. Each row is one matching line
or, in name-only searches, one file, with File Path and Snippet columns.
Filter matches either column, preferring a
contiguous match before a fuzzy subsequence; Ctrl+F focuses it. Click a header
to cycle ascending, descending and original order.
Double-click or press Enter on a File Path cell to open its parent and highlight
the file. Its context menu offers **Copy Path** and **Go To**. Snippet cells do
not navigate. Navigation leaves focus on the target pane and its current file.
Escape/window close dismisses results, retains the Panel and focuses its first
text field after re-enabling the form.
F1 and its shortcuts dialog are unchanged.

## Scope and Limits

Ignore files are not used. All name-only modes exclude dotfiles, Windows-hidden
files and ancestors, links/junctions, nonregular files and files over the size
limit. Enumeration reads directory entries and file/ancestor metadata, not contents.
Content search retains its existing eligibility: a positive filename Glob mask
can include hidden files, while Literal/RegEx exclude them and recheck explicit
file size/type and hidden/reparse ancestors. Negative basename Glob masks can
prune matching directories. Links/junctions are not intentionally followed;
concurrent filesystem changes are not a snapshot guarantee.

Defaults: 10,000 result rows, 200 matching lines per file, 50 MiB per file,
16 MiB retained text/payload, 512-character snippets, 128 highlight spans and
two engine threads. Name-only searches ignore the per-file line cap and report
file counts during progress and on completion.
Transport is bounded to 1 MiB per record and a 64 KiB stderr tail. Limits/errors
are labeled; no hits means no results dialog. Binary matches are discarded after
the engine's file-end marker. Stop/error may omit the unfinished file because its
binary status is not yet known. No archives, converters, multiline matching or
association launch are included.

One search runs application-wide; a stopping worker retains its slot until
cleanup. Name-only Glob uses one enumeration process; Literal/RegEx retain
bounded name-filter batches but omit content processes. For content search,
Filename Literal/RegEx use bounded name/content batches and are more expensive
than native globs. On the recorded warm 100,000-file content fixture, glob
search took 2.54 s with two process starts, versus 29.12 s and 877 starts for
filename regex. These are local measurements, not throughput guarantees.

## Settings and Distribution

[SearchFiles.json](SearchFiles.json) is the settings entry point; engine and
recursion defaults live in [search_files/__init__.py](search_files/__init__.py).
The two modes (`name_mode`, `content_mode`), recursion and validated limits persist
under `UserSettings`; queries and results are session-only. Mode values are
`literal`, `glob` and `regex`, defaulting to filename Glob/content Literal.
Old `name_regex`/`content_regex` booleans migrate automatically; valid new modes
take precedence. Old keys are removed on the next settings save.
Preferences from `SearchFileContent.json` remain readable as a fallback;
explicit `SearchFiles.json` values take precedence. New preferences are saved
to `SearchFiles (Windows).json` without modifying the legacy file. The bundled
settings file is empty so defaults cannot mask migrated preferences.
`encoding` accepts `auto` (UTF-8/UTF-16 BOM detection) or
`windows-1252`. Limits may be lowered, not raised above the defaults.

The command ID is `search_files`; the old `search_file_content` ID remains
callable for custom bindings but is hidden from the command palette. When
updating plug-ins manually, replace the old `SearchFileContent` folder with
`SearchFiles` rather than keeping both copies. The public `fman` API is unchanged.

Source execution uses conda-forge's installed `bin/rg.exe` under `sys.prefix`.
PyInstaller includes that executable and the notices in [licenses](licenses)
as ordinary binary/data inputs, without requiring the conda package cache.
The notices are unchanged copies of `info/licenses/LICENSE-MIT` and
`info/licenses/THIRDPARTY.yml` from conda-forge's win-64
`ripgrep 15.2.0 h18a1a76_1`, matching `conda-lock.yml`. Refresh both files when
updating the locked ripgrep package. Frozen execution uses only the bundled executable.
There are no custom downloads, version/hash checks, integrity manifests or
registry writes. Missing executables surface through normal process/build errors.

The implementation uses only public `fman` APIs and Qt-free `fman.ui` services.
See [icon sources and pane symbols](icons/README.md).