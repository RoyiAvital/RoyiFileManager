# Everything Plug-In

Machine-wide file search backed by a bundled, application-managed instance of
[voidtools Everything](https://www.voidtools.com/), queried over its `WM_COPYDATA`
IPC channel and presented in the standard Quicksearch dialog. Status: Design;
IPC transport is the first item to validate (Implementation Step 1).

Groundwork: the facts and measurements in
[Find Files 003, "Evaluated Alternative: voidtools Everything as the Engine"](FindFiles003.md#evaluated-alternative-voidtools-everything-as-the-engine-2026_09_20)
and the probe [src/misc/everything_probe.py](../src/misc/everything_probe.py).

## Task

Add a bundled `Everything` plug-in with three Command Center commands:

| Command id | Alias | Windows binding |
| --- | --- | --- |
| `search_file_by_everything` | Search file by Everything | `Ctrl+E` |
| `add_folder_to_everything_database` | Add folder to Everything database | none |
| `remove_folder_from_everything_database` | Remove folder from Everything database | none |

**Search file by Everything** opens Quicksearch; each keystroke is sent verbatim,
in Everything's own search syntax, to a resident Everything index and the top
matches come back with highlighting, size and modification date. The search
scope is the set of folders the user added to the Everything database; it is
unrelated to the panes' current locations. Accepting a result navigates the
invoking pane to the entry (parent folder, cursor on the file).

**Add folder to Everything database** / **Remove folder from Everything database**
maintain the indexed roots.

Motivation: the fuzzy picker (`Ctrl+F`), the Everything-syntax picker planned in
[Find Files 003](FindFiles003.md) and the `fd` panel all search *from the pane's
folder* and walk it first. There is no "find a file anywhere on my indexed
drives as I type" search. Everything answers that in under a millisecond of real
work over hundreds of thousands of entries, keeps the index live through change
monitoring, and needs no administrative rights for folder indexes.

## Scope

Included:

- Plug-in `Plugins/Everything/` with package `everything_search`, the three
  commands above, `Key Bindings (Windows).json` binding `Ctrl+E`.
- IPC client (`ctypes`, standard library only): named-instance window lookup,
  `EVERYTHING_IPC_COPYDATA_QUERY2W` queries, reply parsing, version and
  database-state probes, per-request stale-reply rejection, timeouts.
- Managed named instance `RoyiFileManager`: lazy start on first command, ini and
  database under `UserSettings`, exit with the application.
- Add/Remove folder: persisted folder list, ini regeneration, instance restart.
- Quicksearch presentation: hint rows, highlight, description with modified
  date and size, "N of M" count, navigation on accept.
- Bundling: `Everything.exe` 1.4.1.1032 x64 portable plus its `License.txt`
  fetched by `build.py` with pinned SHA-256 (same mechanism as `7za.exe`),
  copied by [RoyiFileManager.spec](../RoyiFileManager.spec).
- Optional `executable` override so a user's own Everything installation (1.4 or
  1.5) can be used instead of the bundled binary.
- README section, CHANGELOG entry, tests.

Excluded:

- Attaching to the user's *unnamed* Everything instance or starting it. The
  application never launches an unnamed instance (it would swallow the user's own
  later launch) and never modifies the user's `Everything.ini`.
- NTFS/ReFS volume indexing, `run_as_admin`, the Everything service, USN
  journals, `-install-*` switches, Registry writes.
- The HTTP JSON server, `es.exe`, the SDK DLL, ETP. HTTP stays a probe-only tool.
- Content search, `zip://` or other non-`file://` schemes, network-index (`ETP`)
  roots. Only local absolute folders can be added.
- Any change to `show_quicksearch`, `QuicksearchItem` or the Quicksearch widget.
- Everything 1.5-only switches (`-add-folder`, `-folders`, `-no-auto-index`).
  Add/Remove work identically on 1.4 and 1.5 through the ini.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
plug-in only uses `DirectoryPaneCommand`, `show_quicksearch`, `QuicksearchItem`,
`show_prompt`, `show_status_message`, `show_alert`, `load_json`/`save_json` and
`fman.url`. Fork-specific coupling: `fman.impl.status_bar.format_size` for the
size text (already used by SearchFileFuzzy and FindFiles) and
`fman.impl.util.qt.thread.run_in_main_thread`. Nothing else in the host changes.

Binding: [Find Files 003](FindFiles003.md) originally reserved `Ctrl+E` /
`Ctrl+Shift+E` for its Everything-*syntax* picker over the Python engine. The
user accepted moving that picker to `Ctrl+Alt+F` / `Ctrl+Alt+Shift+F` (beside the
fuzzy `Ctrl+F` / `Ctrl+Shift+F`), so `Ctrl+E` belongs to this plug-in, the one
that actually uses Everything. Find Files 003 has been updated accordingly.

## Design

### Components

```
Plugins/Everything/
  Key Bindings (Windows).json      Ctrl+E -> search_file_by_everything
  bin/Everything.exe, License.txt  downloaded by build.py (gitignored)
  everything_search/
    __init__.py    commands, Quicksearch glue, settings
    ipc.py         Win32 message-only window + WM_COPYDATA client (own thread)
    instance.py    executable lookup, ini generation, start / stop / restart
    tests/
```

Settings file `Everything.json` in `UserSettings/Plugins/User/Settings/`:

| Key | Default | Meaning |
| --- | --- | --- |
| `folders` | `[]` | Indexed roots, absolute local paths |
| `executable` | `""` | Empty = bundled binary; otherwise a user path to `Everything.exe` |
| `instance` | `"RoyiFileManager"` | Named instance; never empty |
| `max_results` | `100` | Rows requested per keystroke |
| `sort` | `"name"` | `name`, `path`, `date_modified`, `size` (Everything sort constants) |
| `show_metadata` | `true` | Description line with modified date and size |
| `exit_with_application` | `true` | Send `-exit` to the managed instance on quit |
| `query_timeout_ms` | `500` | Per-keystroke IPC wait before showing a hint row |

Mutable state under `UserSettings/Local/Everything/`: generated `Everything.ini`,
`Everything.db` (`db_location`), nothing beside the executable, nothing in the
Registry, no `%APPDATA%` (`app_data=0`).

### Instance lifecycle (`instance.py`)

- Executable: `settings['executable']` if set, else
  `Plugins/Everything/bin/Everything.exe` (frozen: next to the plug-in; source
  tree: the same path, populated by `build.py`). Missing binary → every command
  reports "Everything.exe not found; run `python build.py run` or set
  `executable` in Everything.json".
- Nothing runs at application startup. No timers, no scans, no I/O until the
  first of the three commands is invoked (the disabled/no-op path is "never
  invoked").
- `ensure_running()` (called from the commands, off the Qt thread when it may
  block): if `FindWindowW('EVERYTHING_TASKBAR_NOTIFICATION_(RoyiFileManager)')`
  exists, return. Otherwise regenerate the ini from settings and `Popen`
  `[exe, '-instance', name, '-startup', '-config', ini]` with `shell=False`,
  `close_fds=True`, no console. Return immediately; readiness is observed by the
  IPC client, not awaited.
- Ini template is the probe's, without the HTTP keys: `app_data=0`,
  `run_as_admin=0`, `show_tray_icon=0`, `run_in_background=1`, all
  `auto_include_*_volumes=0`, `folders=<comma-joined>`,
  `folder_monitor_changes=1` per folder, `db_location=<UserSettings/Local/Everything>`,
  `index_size=1`, `index_date_modified=1`, `index_date_created=0`,
  `allow_http_server=0`, `http_server_enabled=0`.
- `restart()` for Add/Remove: `[exe, '-instance', name, '-exit']`, poll
  `FindWindowW` until gone (15 s cap, then report failure), regenerate ini, start
  again. Everything reloads unchanged folder indexes from `Everything.db` and
  scans only the new root; measured build for 328k entries was ~10 s, during
  which queries already answer from the loaded database.
- Shutdown: when `exit_with_application` is true, a `QCoreApplication.aboutToQuit`
  hook (registered on first start via `fman.impl.application_context`, with
  `atexit` as fallback; fork-specific coupling, documented) sends `-exit`.
  Everything persists its database on exit. Orphaned instances from a crash are
  simply reused on the next start.
- Unnamed instance: never started, never signalled; the user's window class
  `EVERYTHING_TASKBAR_NOTIFICATION` is not touched.

### IPC client (`ipc.py`)

Everything's IPC is `WM_COPYDATA` between top-level windows. Constants and struct
layouts are copied verbatim from `Everything_IPC.h` in the official SDK zip
during Step 1; names below are the header's.

- One daemon thread `everything-ipc`, created on first use, owns a message-only
  window (`RegisterClassW`, `CreateWindowExW(..., HWND_MESSAGE, ...)`). Its
  `WNDPROC` handles `WM_COPYDATA` by copying `cbData` bytes out immediately
  (the buffer is valid only during the message) and returns `TRUE`.
- Requests arrive through a `queue.Queue`; the thread blocks in
  `MsgWaitForMultipleObjectsEx(wake_event, INFINITE, QS_ALLINPUT)` so incoming
  sent messages are dispatched while idle. Windows message pumping never touches
  the Qt thread.
- `query(text, max_results, offset, sort, request_flags, timeout)`: build
  `EVERYTHING_IPC_QUERY2` (`reply_hwnd`, `reply_copydata_message` = request id,
  `search_flags` = 0, `offset`, `max_results`, `request_flags`, `sort_type`) +
  UTF-16LE text + NUL; `SendMessageTimeoutW(target, WM_COPYDATA, our_hwnd, &cds,
  SMTO_BLOCK | SMTO_ABORTIFHUNG, 1000)` with `dwData = EVERYTHING_IPC_COPYDATA_QUERY2W`.
  Everything replies asynchronously to `reply_hwnd` with `dwData` = request id and
  an `EVERYTHING_IPC_LIST2` (`totitems`, `numitems`, `offset`, `request_flags`,
  `sort_type`, `EVERYTHING_IPC_ITEM2[numitems]` of `flags`, `data_offset`, then
  packed data: length-prefixed UTF-16 strings, `LARGE_INTEGER` size, `FILETIME`
  dates). Parsing produces immutable `Hit(path, is_folder, size, modified_ns,
  highlight_spans)` tuples.
- Request flags: `FULL_PATH_AND_FILE_NAME | HIGHLIGHTED_FULL_PATH_AND_FILE_NAME |
  SIZE | DATE_MODIFIED | ATTRIBUTES`. Highlight text marks matches with `*`
  (`**` is a literal asterisk); it is converted to index lists for
  `QuicksearchItem.highlight` against the plain path.
- Stale results: each request has a monotonically increasing id; a reply whose
  id is not the newest outstanding request is dropped. Only one request is
  outstanding per dialog; a new keystroke supersedes the previous one.
- Probes: `SendMessageTimeoutW(target, EVERYTHING_WM_IPC, EVERYTHING_IPC_IS_DB_LOADED
  / IS_DB_BUSY / GET_MAJOR_VERSION / GET_MINOR_VERSION / GET_BUILD_NUMBER, 0, ...,
  200 ms)`. `target` is re-resolved with `FindWindowW` when a send fails, so an
  instance restart is transparent.
- Failure behaviour: window not found → `NotRunning`; `SendMessageTimeout`
  failure or no reply within `timeout` → `Timeout`; malformed list → `ProtocolError`.
  All are plain exceptions turned into hint rows by the command; nothing is retried
  inside the client.

### Search command (`__init__.py`)

`SearchFileByEverything(DirectoryPaneCommand)`, always visible.

1. Load settings under a module lock; call `instance.ensure_running()` (returns at
   once; `Popen` cost only when not running).
2. `show_quicksearch(get_items)`; `get_items(query)` runs on the Qt thread per
   keystroke:
   - empty or whitespace query → one hint row "Type an Everything query, e.g.
     `*.pdf dm:thisweek`" with value `''`.
   - `ipc.query(...)` with `settings['query_timeout_ms']`. `NotRunning` →
     hint "Starting Everything…" (or "Everything.exe not found…"); `Timeout` →
     "Everything is busy, keep typing"; `ProtocolError` → "Unsupported Everything
     reply (version X)". Hint rows have value `''` and are ignored on accept.
   - Otherwise yield `QuicksearchItem(url, title=path, highlight=spans,
     description=...)` for each hit, `url = as_url(path)`; description is
     `YYYY-MM-DD HH:MM, size` when `show_metadata`, `' '` otherwise (two-line
     reservation, as in Find Files 002). When `totitems > numitems` the first row
     is a hint "Showing 100 of 12,345".
3. On accept with a non-empty value: `pane.run_command('open_directory',
   {'url': url})` (Core navigates to the parent and places the cursor for files;
   enters folders). Missing entries fall to Core's existing error path.

Wait behaviour on the Qt thread: median IPC round trip measured via HTTP was
0.4-0.7 ms minimum real work; IPC avoids the 15.6 ms HTTP timer tick. The
`query_timeout_ms` bound (500 ms) is the worst case per keystroke while the
database is loading; the hint row makes that state visible. This is the same
synchronous `get_items` contract the fuzzy picker uses.

### Add / Remove folder

`AddFolderToEverythingDatabase(DirectoryPaneCommand)`:

1. Default path: the entry under the cursor if it is a local folder, else the
   pane's path if `file://`, else empty. `show_prompt('Add folder to Everything
   database:', default)`; cancel → no change.
2. Validate: absolute, exists, `S_ISDIR`, resolves to `file://`; not already
   present and not inside an existing root (case-insensitive `os.path.normcase`
   prefix check) → otherwise status message and no change. Adding a parent of an
   existing root is allowed and removes the now-redundant children.
3. Under the module lock: reload settings, append, `save_json`, regenerate ini,
   `instance.restart()` in a `Task`-free daemon thread (no progress dialog; the
   status bar shows "Everything: re-indexing D:\Data…" and the search hint rows
   report readiness). Failures surface as `show_alert`.

`RemoveFolderFromEverythingDatabase`: `show_quicksearch` over `folders` (substring
filter, as the comparator wizard), remove the chosen root, persist, restart.
Empty list → status message "No folders in the Everything database."

Both commands are `is_visible()` = true; they act on settings, not on the pane.

### Threading and ownership

| Work | Thread |
| --- | --- |
| Commands, `get_items`, Quicksearch, `show_prompt` | Qt thread |
| Win32 window, message pump, `SendMessageTimeoutW`, reply parsing | `everything-ipc` daemon thread |
| `Popen` start/exit, `FindWindowW` polling in `restart()` | short-lived daemon thread per restart |
| Settings read/write | any thread, under one module `Lock`, JSON only |

Data crossing threads is immutable (`str`, tuples, `Hit` dataclasses). No Qt
object leaves the Qt thread. Cancellation: superseded requests are dropped by id;
`restart()` is bounded by the 15 s exit poll; a closed dialog simply stops
calling `get_items`.

### Delivery

- `build.py`: `_ensure_everything()` next to `_ensure_7za()`: download
  `Everything-1.4.1.1032.x64.zip` from voidtools with pinned archive and binary
  SHA-256, extract `Everything.exe` and `License.txt` (MIT + PCRE BSD notice) into
  `Plugins/Everything/bin/`. Called from the same entry points as `_ensure_7za`.
- `RoyiFileManager.spec`: add both files to `resources/Plugins/Everything/bin`.
- `.gitignore`: the `bin/` folder, added only with the user's permission (AGENTS
  rule); the doc lists it as a step so it is not forgotten.
- Versions: 1.4.1.1032 pinned because the 1.4 IPC protocol is the SDK's
  documented baseline and 1.4 is the stable release. A user-supplied 1.5 binary
  works over IPC; the ini keys used are common to both.

## Alternatives

- **Everything SDK DLL (`Everything64.dll`) via `ctypes`.** Same IPC underneath,
  hides the struct parsing, but `Everything_Query(TRUE)` pumps messages on the
  calling thread and the DLL must be shipped and loaded into the Qt process.
  Rejected: ~300 lines of `ctypes` against a stable, documented wire format give
  the same result without another binary, and keep pumping on our own thread.
- **HTTP JSON server (1.4 built-in).** Proven by the probe, trivial with
  `urllib`, but 1.5 moved it to a plug-in, it costs a loopback port and the
  ~16 ms timer tick per request. Rejected as the primary transport; kept in the
  probe for diagnostics.
- **`es.exe` per keystroke.** Process spawn per keystroke (tens of ms) and text
  parsing; rejected.
- **Attach to the user's unnamed instance by default.** Best coverage on this
  machine (NTFS volumes), but the application cannot manage its config, Add/Remove
  would have to mutate the user's `Everything.ini`, and results depend on an
  external install. Rejected for the default; a later task may add an
  `instance: ""` read-only attach mode.
- **1.5 `-add-folder` / `-folders` at runtime instead of ini + restart.**
  Version-specific and 1.5 is a preview; the restart costs a few seconds and
  works on both. Rejected.
- **Docked Panel with controls (like `fd`).** Everything's value is its syntax
  plus reactivity; the Quicksearch dialog delivers that with zero new UI, and the
  user asked for the Quicksearch style. A Panel/Table variant can follow.
- **Automatic indexing of all fixed drives.** Minutes to build, hundreds of MiB,
  rescan I/O per launch (measured in Find Files 003). Rejected; roots are
  explicit and user-chosen.

## Runtime Effects

- Startup: none. No import-time work beyond module load; no process, timer or
  I/O until a command runs.
- First command: one `Popen` (Everything loads `Everything.db`, then rescans
  folder indexes in the background; ~10 s for 328k entries, less on reload) and
  one thread with a message-only window.
- Steady state: Everything process 50 MiB working set at 330k entries (measured),
  monitoring change notifications for the indexed roots; our thread idle in a
  kernel wait. Per keystroke: one `SendMessageTimeoutW`, one reply copy of at
  most `max_results` items (a few tens of KiB), parsing in Python (~sub-ms).
- Add/Remove: exit + start of the process, scan of the new root only.
- Shutdown: one `-exit` send; Everything saves its database.
- Disabled/no-op path: never invoking the commands means nothing runs; deleting
  `folders` leaves an empty index (queries return zero rows).

## Tests

Unit (`everything_search/tests/`, standard `unittest`, no Everything process):

- `test_ipc.py`: encode `EVERYTHING_IPC_QUERY2` bytes for a sample query and
  compare against a fixture built from the header layout; decode a captured
  `EVERYTHING_IPC_LIST2` reply fixture (files, a folder, a drive root, a
  non-ASCII name, zero-size, highlighted `*`/`**` markers) into `Hit`s; stale
  reply dropped; malformed list raises `ProtocolError`.
- `test_highlight.py`: `*abc*def.txt` → indices 0-2; `**` literal asterisk;
  markers spanning path separators.
- `test_instance.py`: ini generation from settings (folders joined, monitor
  flags, `db_location`, HTTP disabled, `run_as_admin=0`); executable lookup
  precedence; argument lists for start, exit and restart contain `-instance` and
  never target the unnamed instance; folder validation rules including nested
  roots and case-insensitive duplicates.
- `test_commands.py`: `get_items` hint rows for empty query, `NotRunning`,
  `Timeout`, `ProtocolError`; "Showing N of M" row; description formatting;
  accept path calls `open_directory` with the URL; hint rows ignored.

Qt integration (`fman_integrationtest.test_qt.EverythingIT`): the three commands
register with the expected aliases and `Ctrl+E`; `search_file_by_everything`
opens Quicksearch with a fake IPC client and navigates on accept; Add/Remove
persist settings and call the restart hook exactly once, on a non-Qt thread.

Live smoke (manual or `fman_integrationtest.everything_smoke`, skipped without
`Everything.exe`): start named instance from a temp `UserSettings`, add a small
fixture folder, wait for `IS_DB_LOADED`, query `ext:txt`, assert hits and
highlight, remove the folder, `-exit`, assert the window class disappears and the
user's `EVERYTHING_TASKBAR_NOTIFICATION` window (if any) still exists.

Performance (recorded in Validation Results): 30 warm IPC round trips for the
probe's default queries against the fixture index; expectation median < 5 ms.

Manual: bundled binary present after `python build.py run`; frozen build finds
`bin/Everything.exe`; no files created beside the executable; no Registry keys
under `HKCU\Software\voidtools` change.

## Implementation Steps

1. **IPC spike (gate).** Throwaway script under `target/`: message-only window,
   `QUERY2W` against the user's running instance and against a
   `-instance RoyiFileManager` started with the probe's ini; parse replies; time
   30 round trips. If IPC cannot be made to work reliably, stop and revise this
   document (HTTP 1.4 fallback) before any plug-in code.
2. `ipc.py` with constants copied from `Everything_IPC.h`; unit tests with fixtures
   captured in Step 1.
3. `instance.py`: executable lookup, ini generation, start/exit/restart, quit hook;
   unit tests.
4. `__init__.py`: settings, `SearchFileByEverything`, hint rows, highlight
   conversion, navigation; unit tests.
5. Add/Remove commands, prompt defaults, validation, restart thread; tests.
6. `Key Bindings (Windows).json` with `Ctrl+E`.
7. `build.py` `_ensure_everything()`, `RoyiFileManager.spec` entry, `.gitignore`
   line (ask first).
8. `EverythingIT`, `everything_smoke`, README section (usage, syntax pointer to
   voidtools, settings table), CHANGELOG entry.

## Acceptance Criteria

- `Ctrl+E` opens Quicksearch; typing `*.py dm:today` lists matching entries from
  every added folder with highlighted matches and a "modified, size" description;
  Enter navigates the invoking pane to the entry.
- Results are independent of both panes' locations.
- Application start with the plug-in installed creates no process, thread, timer
  or file until a command runs.
- Add folder / Remove folder update `Everything.json`, regenerate the ini and
  restart only the named instance; searches during the restart show a hint row
  instead of failing; the user's own Everything instance is unaffected.
- All state lives under `UserSettings`; nothing is written beside
  `Everything.exe`, in `%APPDATA%` or in the Registry.
- Focused tests pass; live smoke passes on a machine with the bundled binary.

## Decision

Settled:

- `Ctrl+E` is this plug-in's binding; Find Files 003 moved to `Ctrl+Alt+F` /
  `Ctrl+Alt+Shift+F` (user accepted, 2026_09_20).

Open items:

1. Default `sort`: `name` (Everything default) or `date_modified` descending
   (recently touched files first). Design assumes `name`.
2. Whether to add a read-only attach mode to the user's unnamed instance in a
   follow-up task.

## Reviewers

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Initial design. Built on the Everything facts and measurements
  recorded in Find Files 003 and `src/misc/everything_probe.py`: named instance
  isolation, standard-user folder indexes, 1.4 vs 1.5 switch and HTTP
  differences, ~16 ms HTTP tick vs sub-ms real work. IPC (`WM_COPYDATA`,
  `QUERY2W`) is the primary and first-validated transport; HTTP, SDK DLL and
  `es.exe` rejected. Managed named instance with lazy start, ini + restart for
  Add/Remove (works on 1.4 and 1.5), all state under `UserSettings`. Flagged the
  `Ctrl+E` conflict with Find Files 003 as the one decision needed before
  implementation.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: User accepted the binding proposal: `Ctrl+E` stays here, Find Files
  003 moves to `Ctrl+Alt+F` / `Ctrl+Alt+Shift+F`. Scope note, Implementation
  Step 6 and Decision updated; the conflict is closed.
