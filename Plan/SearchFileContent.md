# Search File Content

## Task

Add a bundled `SearchFileContent` plug-in that searches *inside* files below
the active pane's directory. The user filters the files by name mask (e.g.
`*.txt;*.md`), enters the text or regular expression to look for, sets a few
matching options, and gets a list of matching files. Moving through the list
(or through the individual matches) shows the matching line with its
neighbourhood, and `Enter` places the pane cursor on the file.

## Scope

This task adds a bundled Windows content-search plug-in using ripgrep, with
streaming results, text preview, encoding controls, cancellation, persistence,
and navigation to matching files. Searching inside archives, hex search,
external document converters, and a pure-Python fallback are excluded from the
first version.

## References from other file managers

- **Total Commander – Find Files (`Alt+F7`)**: "Search for" (name mask,
  `;`-separated), "Search in" (path + "Search subdirectories" / depth),
  "Find text" with `Whole words only`, `Case sensitive`, `RegEx`,
  `ASCII/UTF-8/Unicode/Hex`, `Find files NOT containing the text`; results
  list with `View` (Lister opens at the match), `Go to file`, `Feed to
  listbox`, and saved search presets. This is the feature set users of a
  dual-pane manager expect; the plan mirrors it minus hex search and presets.
- **Double Commander – Find Files (`Alt+F7`)**: same layout, plus a "Find
  text" encoding drop-down and a results list with `View`/`Feed to listbox`.
- **Far Manager – Find file (`Alt+F7`)**: "Containing text", `Case sensitive`,
  `Whole words`, `Regular expressions`, `Search in archives`, results list
  with `View`/`Goto`.
- **VS Code – Search view**: the modern UI model for *presentation*: one
  query field with three toggles (`Match Case`, `Match Whole Word`, `Use
  Regular Expression`), include/exclude glob fields, results as a tree
  (file → matches) with the match highlighted inside its line, streaming
  results while the search runs, and a running count with a "limited"
  notice. VS Code also uses ripgrep as its engine.

## Engine options reviewed

| Option | Verdict |
| --- | --- |
| **ripgrep (`rg.exe`)** via subprocess, `--json` output | **Recommended.** Rust, parallel, SIMD literal search, memory maps; Unicode-aware `-i`; UTF-16 BOM sniffing and `-E <encoding>` (incl. `windows-1252`); binary detection; `-g` globs; `-F` literal, `-w` word, `-U` multiline, `-C` context; PCRE2 (`-P`) for look-around/back-references in the Windows msvc build; `--pre`/`--pre-glob` for PDF/Office text extraction later. Streaming JSON lines (`begin`, `match`, `context`, `end`, `summary`) with byte offsets and `submatches` give everything the UI needs, including transcoded line text. Single 2 MB executable, MIT/Unlicense. Same distribution pattern as `7za.exe` in `build.py`. |
| ugrep (`ugrep.exe`) | Comparable speed, C++; searches inside `.zip`/`.7z`/`.tar` and PDFs via filters; `--json`. Fewer users, Boost.Regex syntax, larger binary. Keep as a later alternative if searching *inside archives* becomes a requirement; not now (archives are single files everywhere else in this project). |
| Pure Python (`os.scandir` + `re`/`mmap` + thread pool) | 10–50× slower on large trees, no encoding sniffing, binary heuristics to write and maintain. Rejected, also as a fallback: a fallback doubles the test matrix. `rg.exe` is a build-time requirement like `7za.exe`. |
| Python bindings (`ripgrepy`, PyO3 wrappers) | `ripgrepy` is a thin subprocess wrapper adding nothing over `QProcess`; PyO3 bindings are immature and complicate the PyInstaller build. Rejected. |
| Windows Search index (OLE DB) | Only indexed locations, content filters vary per machine, no regex. Rejected. |

## Alternatives

The engine comparison above records the evaluated alternatives. Ripgrep was
selected because it provides bounded, cancellable, streaming JSON output with
strong Windows performance, Unicode and encoding support, glob filtering, and
PCRE2 without introducing a Python extension ABI. ugrep remains a future option
if archive-content search becomes a requirement. A pure-Python fallback was
rejected because it would be substantially slower and double the behavior and
packaging test matrix.

## User-visible behaviour

Command `search_file_content` (alias `Search file content`, palette entry,
default binding `Alt+F7` as in Total Commander/Double Commander/Far; the
binding is free in Core and the two `SearchFileFuzzy` bindings). Opens a
modal dialog through `MainWindow.exec_dialog`, like Quicksearch.

Top form:

- **Search for** — text or regex; combo box with history (last 20).
- **File mask** — `;`-separated globs, empty means all files; combo with
  history. `*.txt;*.md` → `-g *.txt -g *.md`; a leading `!` excludes.
- **Search in** — the active pane path, read-only; **Include subfolders**
  checkbox (default on).
- Toggles: **Regular expression**, **Match case**, **Whole word**,
  **Multiline**, **Files NOT containing** (invert), **Hidden files**,
  **Binary files as text**.
- **Encoding** drop-down: `Auto` (BOM sniffing, default), `UTF-8`,
  `UTF-16`, `Windows-1252`, `Latin-1`, `Latin-9`, plus a free-text entry
  validated against ripgrep's encoding list.
- **Context lines** spin box (0–10, default 2).
- Buttons: **Search/Stop** (same button, toggles), **Go to file** (`Enter`),
  **Open file** (`Ctrl+Enter`), **Close** (`Escape`).

Results:

- Left: `QTreeView` with two levels — file (relative path, match count) →
  match (`line:col`, line text with the match highlighted by a delegate using
  `submatches`). Results stream in while ripgrep runs; a status line shows
  `N matches in M files (K files searched)` and `Searching…`/`Done`/
  `Stopped`/`Limited to N matches`.
- Right: read-only preview (`QPlainTextEdit`) of the selected match with its
  neighbourhood — the `context` lines ripgrep already emitted, the match line
  highlighted, matched spans in a second highlight. No file is re-read: the
  text comes from the JSON stream, already transcoded to UTF-8, so UTF-16 and
  Windows-1252 files preview correctly.
- `Up`/`Down` move through matches across files (flat traversal),
  `Left`/`Right` collapse/expand a file, `Ctrl+Up`/`Ctrl+Down` jump to the
  previous/next file.
- In *invert* mode there are no matches; the tree lists files only and the
  preview is empty.
- `Go to file` closes the dialog and runs `open_directory` on the file URL
  (existing Core behaviour: navigates to the parent and places the cursor).
  `Open file` runs `open_file`.

## Design

Plug-in layout `Plugins/SearchFileContent/`:

- `search_file_content/__init__.py` — the command, settings, history.
- `search_file_content/engine.py` — argument builder, `QProcess` runner,
  JSON line parser, result model (pure Python where possible).
- `search_file_content/ui.py` — the dialog. This module imports PyQt5 and
  `fman.impl.util.qt.thread.run_in_main_thread` directly. That is acceptable
  for a *bundled* plug-in in this fork and is confined to this one module;
  document the dependency in the README. (Alternative considered: a generic
  "results browser" dialog in the main application behind a new public API.
  Rejected for now — it splits one feature over two places and no second
  consumer exists.)
- `bin/windows/rg.exe` + `LICENSE-ripgrep` — downloaded by `build.py`.
- `SearchFileContent.json`, `Key Bindings (Windows).json`, `README.md`.

Engine:

- Argument builder is a pure function `build_args(options) -> list[str]`,
  unit-tested. Always: `--json --no-config --no-ignore --no-messages
  --max-count <n> --max-filesize <size> --context <c> -- <pattern> <root>`.
  Never `--follow` (junction loops), never a shell. Pattern via `-e` so a
  leading `-` is safe. `-F` unless *Regular expression*; `-i` unless *Match
  case*; `-w`, `-U`, `--files-without-match`, `--hidden`, `-a`,
  `-E <encoding>` per toggle; `--max-depth 1` unless *Include subfolders*;
  one `-g` per mask; `-P` automatically when the regex fails to compile in
  the default engine (`rg` exits 2 with a syntax error) and *Regular
  expression* is on — retry once and tell the user.
- Runner uses `QProcess` on the Qt thread: `readyReadStandardOutput` →
  split complete lines → parse → append to a pending batch; a 50 ms
  single-shot `QTimer` flushes the batch into the model. `Stop`/close calls
  `kill()` and discards late output. Exit codes: 0 matches, 1 none, 2 error
  (show stderr tail). No worker threads are needed; ripgrep is the parallel
  part.
- Parser turns JSON lines into `FileHit(path, matches)` and
  `Match(line_number, absolute_offset, text, submatches, before, after)`.
  `lines.text` is used when present; `lines.bytes` (base64, non-UTF-8 lines)
  is decoded with `errors='replace'`. `context` messages are attached to the
  nearest match by line number. Unit-tested from recorded fixture lines.
- Result cap: `max_matches` total (default 10 000) and `--max-count` per
  file (default 200). On reaching the cap the runner kills the process and
  the status says `Limited`.
- Accented and other non-ASCII text: ripgrep's `-i` is Unicode casefolding
  (`é`/`É`, `ç`/`Ç`); the pattern is passed as UTF-8 (`QProcess` handles
  argument encoding on Windows). Files in `windows-1252`/`latin-1` (legacy
  French text) need the *Encoding* drop-down; files with a UTF-16 BOM work in
  `Auto`.

Archives are single files here as well: no `-z` and no `--pre` in the first
version; `search_archives` is reserved in settings for a later ugrep or
`--pre` based extension.

## Runtime Effects

- No search process or recurring timer exists until the command opens and a
  search starts.
- Ripgrep performs filesystem traversal and matching in a child process; the
  Qt thread only parses ready output and flushes result batches every 50 ms.
- JSON buffering and the result model are bounded by `max_matches` and
  `max_count_per_file`; `max_filesize` bounds work per file.
- Stop or dialog close kills the child process and rejects late output.
- The packaged application grows by the pinned ripgrep executable and licence.
- Normal pane navigation and applications that never invoke content search are
  unaffected apart from plug-in discovery and settings loading.

Distribution (`build.py`):

- `_ensure_rg()` alongside `_ensure_7za()`: download the pinned
  `ripgrep-<version>-x86_64-pc-windows-msvc.zip` from the GitHub release,
  verify its SHA-256 against a constant in `build.py`, extract `rg.exe` and
  the licence into `Plugins/SearchFileContent/bin/windows/`. `run`, `test`,
  and `freeze` call it. Add the same SHA-256 verification to `_ensure_7za`
  while touching that code.
- The plug-in resolves `rg.exe` relative to its own directory (as
  `core/fs/zip.py` does for `7za`) and allows an `rg_path` override in
  settings. A missing executable shows one alert with the expected path.

## Settings

`SearchFileContent.json`:

```json
{
  "regex": false,
  "match_case": false,
  "whole_word": false,
  "multiline": false,
  "include_subfolders": true,
  "include_hidden": false,
  "binary_as_text": false,
  "encoding": "auto",
  "context_lines": 2,
  "max_matches": 10000,
  "max_count_per_file": 200,
  "max_filesize": "50M",
  "history_size": 20,
  "rg_path": "",
  "search_archives": false
}
```

Toggle states and the two histories (`pattern_history`, `mask_history`) are
saved with `save_json` when the dialog closes (accept or cancel), so the next
search starts from the previous options — Total Commander behaviour. Invalid
values fall back to defaults; unknown encodings fall back to `auto` with a
status-line notice.

## Implementation Steps

1. `build.py`: `_ensure_rg()` with SHA-256 verification; wire into `run`,
   `test`, `freeze`; include the licence file.
2. `engine.py`: `build_args`, JSON parser, result model — pure Python, unit
   tests from fixtures.
3. `engine.py`: `QProcess` runner with batching, cancel, exit-code handling,
   result cap.
4. `ui.py`: dialog form, tree + delegate highlight, preview pane, keyboard
   traversal, streaming status line.
5. `__init__.py`: command, settings/history persistence, `Go to file`/`Open
   file` via existing Core commands.
6. Theme selectors (`.search-content-*`) in `theme.py` and Core themes for
   the highlight colours.
7. README (usage, encoding notes, ripgrep licence) and changelog.

## Tests

Required final command from the repository root:

```powershell
python build.py test
```

Unit tests (no Qt):

- `build_args` for every toggle, mask splitting (`;`, `!` exclusion), depth,
  encoding, invert, and the `-P` retry decision.
- Parser: `begin`/`match`/`context`/`end`/`summary` fixtures, `lines.bytes`
  fallback, context attachment, multi-submatch lines, result cap.
- Settings validation and history trimming.

Integration tests (real `rg.exe`, temp directory; skipped with a clear
message if the binary is absent):

- Literal vs regex, case, whole word, multiline, invert.
- UTF-8, UTF-16 with BOM (`Auto`), and `windows-1252` with the explicit
  encoding — French text such as `Résumé annuel — année écoulée` is found
  (case-insensitively, `résumé` matches `RÉSUMÉ`) and previewed correctly.
- Hidden file excluded/included; binary file skipped/searched; junction loop
  not followed; unreadable file counted, not fatal.
- Streaming: model receives results before the process exits; `Stop` kills
  the process and no late rows appear.
- `Go to file` calls `open_directory` with the file URL.

Manual: dialog styling in both themes; performance on a 100k-file tree
(results start appearing within a second).

## Acceptance Criteria

- Searching a 100k-file tree streams results without freezing the UI and can
  be stopped at any time.
- Literal, regex (incl. PCRE2 fallback), case, whole-word, multiline, invert,
  mask, hidden, binary, and encoding options behave as documented.
- French text with accents in UTF-8, UTF-16 and `windows-1252` files is found
  and shown correctly in the preview.
- The preview never re-reads files; it shows ripgrep's context lines with the
  match highlighted.
- `Enter` places the pane cursor on the selected file; options and history
  persist between invocations.
- `rg.exe` is fetched and verified by `build.py`; the packaged application
  contains it and its licence; the plug-in never spawns a shell.
- Archives are not searched inside in this version.

## Reviewers

### 2026_09_12 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context window: Not exposed by host
- Outcome: Initial ripgrep-backed streaming search design created after engine
  alternatives were evaluated.
