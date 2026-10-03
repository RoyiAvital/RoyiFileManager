# Everything Plug In

Machine wide file search backed by a bundled, application managed instance of
[voidtools Everything](https://www.voidtools.com), queried over its `WM_COPYDATA`
IPC channel and presented in the standard Quicksearch dialog. Status: Implemented;
focused unit, native Qt and live portable-runtime checks passed on 2026_10_03.

Groundwork: the facts and measurements in
[Find Files 003, "Evaluated Alternative: voidtools Everything as the Engine"](../Plan/FindFiles003.md#evaluated-alternative-voidtools-everything-as-the-engine-2026_09_20)
and the probe [src/misc/everything_probe.py](../src/misc/everything_probe.py).

## Task

Add a bundled `Everything` plug-in with four Command Center commands:

| Command id | Alias | Windows binding |
| --- | --- | --- |
| `search_file_by_everything` | Search file by Everything | `Ctrl+E` |
| `add_folder_to_everything_database` | Add folder to Everything database | none |
| `add_favorites_to_everything_database` | Add favorite folders to Everything database | none |
| `manage_everything_folders` | Manage Everything database folders | none |

**Search file by Everything** opens Quicksearch; each keystroke is sent verbatim,
in Everything's own search syntax, to a resident Everything index and the top
matches come back with highlighting, size and modification date. The search
scope is the set of folders the user added to the Everything database; it is
unrelated to the panes' current locations. Accepting a result navigates the
invoking pane to the entry (parent folder, cursor on the file).

**Add folder to Everything database** / **Manage Everything database folders**
maintain the indexed roots.

Motivation: the fuzzy picker (`Ctrl+F`), the Everything-syntax picker planned in
[Find Files 003](../Plan/FindFiles003.md) and the `fd` panel all search *from the pane's
folder* and walk it first. There is no "find a file anywhere on my indexed
drives as I type" search. Everything answers that in under a millisecond of real
work over hundreds of thousands of entries, keeps the index live through change
monitoring, and needs no administrative rights for folder indexes.

## Scope

Included:

- Plug-in `Plugins/Everything/` with package `everything_search`, the four
  commands above, `Key Bindings (Windows).json` binding `Ctrl+E`.
- IPC client (`ctypes`, standard library only): named-instance window lookup,
  `EVERYTHING_IPC_COPYDATA_QUERY2W` queries, reply parsing, version and
  database-state probes, per-request stale-reply rejection, timeouts.
- Managed named instance `RoyiFileManager`: lazy start on first search or effective root update, ini and
  database under `UserSettings`, exit with the application.
- Add-folder command and manager F8/Delete: persisted roots, ini regeneration
  and ownership-checked instance updates.
- One-time import of local Favorites roots, including unavailable paths, through
  the shared normalization, parent confirmation and atomic persistence path.
- Root manager at `everything-folders://`, using existing pane controls and a
  read-only virtual filesystem. No special import row or Favorites UI dependency.
- Quicksearch presentation: hint rows, highlight, description with modified
  date and size, "N of M" count, navigation on accept.
- Bundling: `Everything.exe` 1.4.1.1032 x64 portable fetched by `build.py` with
  pinned SHA-256, plus the reviewed repository asset `licenses/Everything.txt`.
  Both are copied by [application.spec](../application.spec).
- Optional `executable` override for a compatible portable binary. The pinned
  1.4.1.1032 release is verified; 1.5 is rejected pending separate certification.
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
  Add/Remove use the verified 1.4 ini format.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. Commands
use `DirectoryPaneCommand`, `show_quicksearch`, `QuicksearchItem`,
`show_prompt`, `show_status_message`, `show_alert`, `load_json`/`save_json` and
`fman.url`. Fork-specific coupling: the existing `PluginService`/`UiOwner`
lifecycle, `fman.impl.status_bar.format_size` and
`fman.impl.util.qt.thread.run_in_main_thread`. A lazy Qt signal receiver delivers
plain immutable worker states. No host implementation or public API changes.

Binding: [Find Files 003](../Plan/FindFiles003.md) originally reserved `Ctrl+E` /
`Ctrl+Shift+E` for its Everything-*syntax* picker over the Python engine. The
user accepted moving that picker to `Ctrl+Alt+F` / `Ctrl+Alt+Shift+F` (beside the
fuzzy `Ctrl+F` / `Ctrl+Shift+F`), so `Ctrl+E` belongs to this plug-in, the one
that actually uses Everything. Find Files 003 has been updated accordingly.

## Design

### Components

Favorites follow-up: the import command lazily uses the bundled `FavoritesStore`
parser and snapshots `Favorites.json` on Qt under its shared settings lock.
Immutable URLs are validated on the command worker; available folders resolve
aliases, unavailable local paths remain eligible, and unsupported entries are
reported. Favorites are never mutated. All root-list loads and writes use the
same lexical canonicalizer, removing case-insensitive duplicates and covered
children without probing existing offline roots. Parent replacements require
confirmation, stale settings abort the commit, and a changed batch requests one
serialized background update. Cleanup-only writes do not restart Everything.

Automatic Favorites synchronization was rejected: this command is explicitly
one-shot and adds no startup scans, subscriptions or recurring work. Import cost
is proportional to the saved Favorites snapshot plus path validation and root
comparisons; it adds no persistent worker. Canceling confirmation saves nothing.
The lazy dependency on the bundled Favorites parser avoids plug-in load-order
coupling; if it is unavailable, the command reports that without a write.
PyInstaller explicitly includes `uuid`, which resource-loaded plug-ins do not
automatically contribute to its import graph. A new frozen build is required.

```
Plugins/Everything/
  Key Bindings (Windows).json      Ctrl+E -> search_file_by_everything
  bin/Everything.exe              downloaded and hash-verified by build.py
  licenses/Everything.txt         reviewed repository asset; normalized hash
  everything_search/
    __init__.py    commands, Quicksearch glue, settings
    ipc.py         Win32 message-only window + WM_COPYDATA client (own thread)
    instance.py    executable lookup, ini generation, start / stop / restart
```

  Tests live in the existing fman_unittest and fman_integrationtest trees.

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
| `query_timeout_ms` | `50` | One total query deadline, bounded to 1-500 ms |

Mutable state under `UserSettings/Local/Everything/`: generated `Everything.ini`,
`Everything.db` (`db_location`) and process ownership metadata, nothing beside the executable, nothing in the
Registry, no `%APPDATA%` (`app_data=0`).

### Instance lifecycle (`instance.py`)

- Executable: `settings['executable']` if set, else
  `Plugins/Everything/bin/Everything.exe` (frozen: next to the plug-in; source
  tree: the same path, populated by `build.py`). Missing binary → every command
  reports "Everything.exe not found; run `python build.py run` or set
  `executable` in Everything.json".
- Nothing runs at application startup. No timers, no scans, no I/O until the
  first command is invoked (the disabled/no-op path is "never
  invoked").
- A single lazy worker serializes desired configuration changes and coalesces
  queued updates. Empty roots do not launch a process. Existing named windows
  are reused or stopped only after checking persisted PID and creation identity;
  a name collision is an error, not permission to control another process.
  Reuse additionally requires a matching executable, generated-configuration
  SHA-256 in `owner.json`, and a ready supported instance. Legacy ownership
  records without the hash restart once through the same checked path.
  Otherwise regenerate the ini from settings and `Popen`
  `[exe, '-instance', name, '-startup', '-config', ini]` with `shell=False`,
  `close_fds=True`, no console. The command returns immediately; the worker
  prepares IPC and waits for process readiness before publishing a ready state.
- Ini template is the probe's, without the HTTP keys: `app_data=0`,
  `run_as_admin=0`, `show_tray_icon=0`, `run_in_background=1`, all
  `auto_include_*_volumes=0`, `folders=<quoted, escaped list>`,
  `folder_monitor_changes=1` per folder, `db_location=<UserSettings/Local/Everything>`,
  `index_size=1`, `index_date_modified=1`, `index_date_created=0`,
  `allow_http_server=0`, `http_server_enabled=0`.
- Add/Remove requests an ownership-checked named exit, waits off Qt with a
  15 s cap, regenerates the ini, and starts again only for nonempty roots.
  Desired settings stay persisted if activation fails; searches report that
  failure rather than using a stale configuration. Restart can rescan existing
  roots; no incremental-rescan performance guarantee is made.
- Shutdown: when `exit_with_application` is true, a lazy
  `QCoreApplication.aboutToQuit` hook, `PluginService.dispose`, and an `atexit`
  fallback close the workers and request `EVERYTHING_IPC_EXIT` on the verified
  owned window. Direct exit IPC avoids a new process and name-only CLI races.
  Everything persists its database on exit. Reuse after a crash requires matching
  ownership metadata; mere window-name equality is insufficient.
  Qt only signals cancellation. A non-daemon cleanup thread performs the bounded
  IPC (0.6 s) and manager (21 s) joins, keeping notification objects alive until
  their producer stops. Empty-root and unused services need no cleanup thread.
- A query reporting `NotRunning` or an identity mismatch invalidates only its
  matching state snapshot. Reopening search retries unchanged settings on the
  manager worker; foreign-instance ownership checks are never bypassed.
- Unnamed instance: never started, never signalled; the user's window class
  `EVERYTHING_TASKBAR_NOTIFICATION` is not touched.

### IPC client (`ipc.py`)

Everything's IPC uses `WM_COPYDATA`. Numeric constants and packed layouts were
verified against `Everything_IPC.h` in the official SDK zip during Step 1.

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
  SMTO_BLOCK | SMTO_ABORTIFHUNG, remaining_deadline_ms)` with `dwData = EVERYTHING_IPC_COPYDATA_QUERY2W`.
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

1. Load settings on Qt; submit them to the lazy manager. Process creation and
  readiness checks run only on its worker.
2. `show_quicksearch(get_items)`; `get_items(query)` runs on the Qt thread per
   keystroke:
   - empty or whitespace query yields a non-navigable title row.
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

Wait behaviour on the Qt thread: the synchronous callback waits at most the
configured total deadline (50 ms default, 500 ms maximum), including queueing,
sending and receiving. Process startup and root changes never run on Qt.
The native disposable fixture measured a 0.049 ms median over 30 warm IPC
round trips. This does not predict latency for large production indexes.

### Root updates

`AddFolderToEverythingDatabase(DirectoryPaneCommand)`:

1. Default path: the entry under the cursor if it is a local folder, else the
   pane's path if `file://`, else empty. `show_prompt('Add folder to Everything
   database:', default)`; cancel → no change.
2. Validate a local absolute existing directory. Reject UNC and relative paths;
  use case-insensitive path components for containment. Duplicates and covered
  children are no-ops. Confirm before replacing redundant child roots with a
  newly added parent. Preserve existing unavailable roots in settings.
3. Persist desired roots, then submit one immutable configuration to the shared
  worker. It coalesces updates and never runs overlapping restarts. Generation
  checks reject results from earlier configurations. Failures remain visible.

### Folder manager

`ManageEverythingFolders` opens or reloads `everything-folders://` in the active
pane. `EverythingFolders.scan` returns immutable Name/Path rows from configured
roots, with case-folded BLAKE2b identities. Listing never checks targets or
starts Everything. Rows are index records (`is_dir=False`) so the shared fuzzy
finder includes them; explicit Open handling checks and navigates the real target.
Provider resolution retains virtual URLs, and filesystem mutations are unsupported.

`EverythingFoldersListener.on_command` routes Enter/double-click and cross-pane
Open to the stored folder, F11 to real paths, and F8/Delete/Shift+Delete to hidden
bulk removal. Removal confirms the captured roots with default No, preserves
offline roots unless selected, and rejects a stale settings snapshot. It cannot
delete filesystem contents. Empty roots stop the managed process.

F5 and cross-scheme drops into the manager collect local folders in a cancelable
Task, then use the existing one-save normalization and parent-confirmation path.
Drops onto a row add to the list. Moving into the manager and file operations on
its entries are refused. Saved changes notify all live providers; normal snapshot
reconciliation preserves surviving selections across panes.

`DirectoryPaneCommand.is_visible()` is the existing public discovery API, not an
authorization mechanism or VFS-specific extension. Pane helper commands return
False; runtime guards and the read-only provider enforce their boundaries.
The old `remove_folder_from_everything_database` command is removed. Favorites
import remains a palette command without a manager row. No host/Core API changes.

Every mutating command captures the initiating service before validation or
confirmation. Collection stops after owner invalidation. The shared Qt commit
checks that service identity, active owner and open lifetime before settings I/O,
provider notifications or activation. Reloading a new service cannot revive old work.

### Threading and ownership

| Work | Thread |
| --- | --- |
| Command entry points | host command worker; Qt work dispatched explicitly |
| `get_items`, Quicksearch, prompts, settings and notifications | Qt thread |
| Win32 window, message pump, `SendMessageTimeoutW`, reply parsing | `everything-ipc` daemon thread |
| `Popen` start/exit, readiness and root updates | one serialized lazy worker |
| User settings read/write | Qt thread; immutable configuration sent to worker |
| IPC initialization | manager worker, before ready publication |
| Shutdown joins | one non-daemon cleanup thread, only when workers exist |

Data crossing threads is immutable (`str`, tuples, `Hit` dataclasses). Widgets and
models stay on Qt; cleanup uses thread-safe `QObject.deleteLater` after joins.
Cancellation: superseded requests are dropped by id;
`restart()` is bounded by the 15 s exit poll; a closed dialog simply stops
calling `get_items`.

### Delivery

- `build.py`: `_ensure_everything()` downloads the official portable
  `Everything-1.4.1.1032.x64.zip`; archive and executable have pinned SHA-256.
  The archive member is `everything.exe`. The repository's reviewed
  `licenses/Everything.txt` supplies redistribution notices without a network
  request; its SHA-256 normalizes CRLF to LF. Missing or changed source notices
  fail verification before provisioning.
  `run`, `test` and `freeze` verify/provision them automatically; `publish` and
  `release` inherit this through `freeze`. Verified files work offline.
  `package` verifies frozen files without downloading. `clean` and `doc` do not
  provision dependencies. No installer or SDK DLL is shipped.
- `application.spec`: executable under `resources/Plugins/Everything/bin`,
  reviewed notices under `resources/Plugins/Everything/licenses`.
- Existing `*.exe` ignore covers the executable; no protected ignore change.
- Versions: 1.4.1.1032 pinned because the 1.4 IPC protocol is the SDK's
  documented baseline and 1.4 is the stable release. Overrides are checked for
  protocol support; other releases require separate compatibility validation.

## Alternatives

- Root manager: reuse the pane model from Favorites 003 without depending on its
  implementation. A separate floating list would duplicate selection/filter/sort.
  Target availability polling and a special import row were excluded.

- Keep the already approved bundled-host coupling rather than introduce a new
  public lifecycle API or copy host formatting/dispatch code. PlugIn.md now names
  this narrow exception; external plug-ins cannot rely on it. Matching-host
  loader, lifetime and Qt tests remain required.

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
  Version-specific; the implemented restart path is validated on 1.4 only.
  Rejected for this release.
- **Docked Panel with controls (like `fd`).** Everything's value is its syntax
  plus reactivity; the Quicksearch dialog delivers that with zero new UI, and the
  user asked for the Quicksearch style. A Panel/Table variant can follow.
- **Automatic indexing of all fixed drives.** Minutes to build, hundreds of MiB,
  rescan I/O per launch (measured in Find Files 003). Rejected; roots are
  explicit and user-chosen.

## Runtime Effects

- Manager-only use registers a provider/column/listener and reads a settings
  snapshot on demand. Listing hashes O(n) roots, with O(n) memory; no target I/O,
  timers, process launch or additional workers. Settings access stays on Qt;
  immutable Listing construction and target validation run off Qt. Addition has
  one availability check per candidate with cancellation between checks. A slow
  OS directory check cannot be interrupted mid-call. No new recurring idle work.

- Startup: none. No import-time work beyond module load; no process, timer or
  I/O until a command runs.
- First search or root mutation: one lazy manager worker launches Everything and
  checks readiness, preparing the IPC worker/message-only window before marking
  the state ready. Empty-root search starts neither worker and creates no state files.
- Steady state: Everything monitors explicitly indexed roots. The manager waits
  on a condition; IPC waits on a native event/message queue. Per query: verify
  process identity, send one request, copy and parse at most `max_results` rows
  with an 8 MiB packet limit. Large-index CPU/memory were not rebenchmarked.
- Add/Remove: serialized exit + start; existing roots may be rescanned.
- Shutdown: one ownership-checked IPC exit; Everything saves its database.
  Cancellation returns on Qt without joining. One short-lived cleanup thread
  retains the existing bounded waits; process termination can outlast UI closure.
- Disabled/no-op path: never invoking the commands means nothing runs; empty
  `folders` leaves the managed process stopped.

## Tests

Manager checks: `fman_unittest.test_everything.EverythingFoldersTest` covers
identities, offline listing, cancellation, unsupported mutations, routing,
normalization, stale rows and one commit per batch. Native
`fman_integrationtest.test_qt.EverythingFoldersIT` covers real pane filter/fuzzy/sort,
two-pane refresh and selection, default-No removal, F5/drop, F11 and navigation.
The existing EverythingIT checks visible/hidden commands and background activation.

Unit and build checks are in
[test_everything.py](../src/unittest/python/fman_unittest/test_everything.py),
with existing build-name regressions in
[test_app_name.py](../src/unittest/python/fman_unittest/test_app_name.py).
They cover official-layout fixtures, malformed packets, Unicode and highlight
escaping, total deadlines, stale replies/results, root containment, offline
roots, escaped INI lists, serialized/coalesced updates, identity rejection,
command navigation, parent confirmation, stale settings commits, no-op startup,
verified provisioning, offline reuse and frozen-resource declarations.

[EverythingIT](../src/integrationtest/python/fman_integrationtest/test_qt.py)
checks native Quicksearch acceptance/cancellation, syntax, metadata and hint
rows; actual plug-in loading, aliases and Ctrl+E; persisted Add/Remove actions;
Qt notification/settings affinity; one non-Qt process worker; unload cleanup.

[everything_smoke.py](../src/integrationtest/python/fman_integrationtest/everything_smoke.py)
uses the bundled executable, unique named instance and disposable UserSettings
fixtures. It checks Unicode/comma paths, metadata, highlights, root replacement,
empty-root shutdown, files created while stopped, owned orphan recovery, worker
exit, and unchanged unnamed instance, executable directory, AppData and
`HKCU\Software\voidtools`. It measures 30 warm `ext:txt` queries with an expected
median below 5 ms. It is opt-in and fails clearly when the runtime is missing.

A full frozen application launch remains a release smoke check; no freeze or
complete correctness suite is required for this focused task.

## Implementation Steps

1. **IPC spike (gate).** Throwaway script under `target/`: message-only window,
  `QUERY2W` against a unique disposable named instance with fixture-only roots;
  never query or control the user's instance. Parse replies; time
   30 round trips. If IPC cannot be made to work reliably, stop and revise this
   document (HTTP 1.4 fallback) before any plug-in code.
2. `ipc.py` with constants verified against `Everything_IPC.h`; official-layout
  fixtures and live reply decoding.
3. `instance.py`: executable lookup, ini generation, start/exit/restart, quit hook;
   unit tests.
4. `__init__.py`: settings, `SearchFileByEverything`, hint rows, highlight
   conversion, navigation; unit tests.
5. Add-folder and Favorites commands, manager bulk removal, prompt defaults,
   validation, serialized worker and captured-lifetime guards; tests.
6. `Key Bindings (Windows).json` with `Ctrl+E`.
7. `build.py` `_ensure_everything()`, `application.spec` entry, focused provisioning
  and frozen-package verification tests; preserve `.gitignore`.
8. `EverythingIT`, `everything_smoke`, README section (usage, syntax pointer to
   voidtools, settings table), CHANGELOG entry.

## Acceptance Criteria

- Manage opens Name/Path rows without target scans or an Everything process.
  Favorites import is palette-only; the old single-root removal command is absent.
- F5/drop additions and selected removal save once, refresh both panes and leave
  filesystem contents untouched. Surviving selections remain selected.
- Manager usage and a real isolated screenshot appear in the documentation.

- `Ctrl+E` opens Quicksearch; typing `*.py dm:today` lists matching entries from
  every added folder with highlighted matches and a "modified, size" description;
  Enter navigates the invoking pane to the entry.
- Results are independent of both panes' locations.
- Application start with the plug-in installed creates no process, thread, timer
  or file until a command runs.
- Add-folder commands / manager F8 or Delete update `Everything.json`, regenerate the ini and
  restart only the named instance; searches during the restart show a hint row
  instead of failing; the user's own Everything instance is unaffected.
- All state lives under `UserSettings`; nothing is written beside
  `Everything.exe`, in `%APPDATA%` or in the Registry.
- Focused tests pass; live smoke passes on a machine with the bundled binary.
- Broad-query Enter selects a real result; lost-process queries can recover on
  reopen without changing roots; matching owned configurations retain identity.
- Disposed/replaced owners cannot commit roots. IPC is ready before search
  readiness, and shutdown waits do not block Qt.

## Decision

Settled:

- `Ctrl+E` is this plug-in's binding; Find Files 003 moved to `Ctrl+Alt+F` /
  `Ctrl+Alt+Shift+F` (user accepted, 2026_09_20).

Open items:

1. Whether to add a read-only attach mode to the user's unnamed instance in a
   follow-up task.

Default sorting is name ascending. Date-modified and size settings are descending;
path is ascending. The existing synchronous Quicksearch API is unchanged and
does not refresh unchanged text automatically.

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

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Accepted the user's automatic portable-download and folder-management
  decisions. Native IPC gate passed on 1.4.1.1032, including Unicode/comma roots,
  highlights, file/folder metadata, isolated shutdown and 30 warm queries.
  Corrected archive contents, query deadline, ownership checks and unsupported
  incremental-rescan claims. No host Quicksearch API or ignore-file change.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Checked implementation against the actual worker-thread command
  registry and corrected Qt notification/settings ownership. Added final
  deadline and stale-commit guards. Focused unit/build, native Qt and production
  live checks pass; full freeze and frozen-host smoke remain unrun.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Reviewed the requested favorites import and frozen launch failure.
  Chose a one-shot, canonical batch using the existing Favorites parser and
  confirmation boundary. Qt integration caught and verified the status dispatch
  correction. Frozen launch still requires a rebuilt distribution.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User approved pane-based root management, palette-only favorites import
  and removal through the manager. Reviewed command visibility separately from
  execution safeguards. Chose virtual index records for shared fuzzy compatibility
  and retained virtual resolution to prevent filesystem mutation through aliases.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Chose "database folders" for the manager and "to Everything database"
  for additions; made "favorite folders" explicit. Retained command IDs,
  shortcuts, settings, virtual location and runtime behavior.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Independent implementation review. Approved with fixes: E1 (Enter
  on a query with more hits than `max_results` closes the dialog without
  navigating) and E2 (no recovery after the managed instance exits) should be
  fixed before release; E3-E8 are minor. Focused gate rerun: 62 unit/build and
  5 native Qt tests passed. See Implementation Review.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Found S1, stale folder-add persistence after owner invalidation;
  confirmed existing E1 broad-query acceptance and E2 missing process recovery.
  62 unit/build and five native Qt checks, isolated live IPC and offline runtime
  pins passed. Changes required before release; production code unchanged.
  See Independent Implementation Review.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Addressed S1 and E1-E8, including recommendations. Preserved checked
  process ownership, public APIs and the unused path. Retained the narrowly
  documented bundled-host exception for E7 instead of expanding the public API.
  Fresh frozen-host validation remains a release check, not claimed here.

## Implementer

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented the bundled portable search plug-in, three commands,
  identity-checked lifecycle, serialized root management, verified automatic
  provisioning, packaging declarations and focused tests. No public API,
  ignore-file, Python-environment or installed-package changes.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Added the fourth command, shared load/save root canonicalization,
  cleanup-only no-restart behavior and the missing `uuid` hidden import. Added
  unit and native Qt coverage for atomic favorites updates, cancellation,
  offline roots, deduplication and command registration. No frozen build run.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented the pane-based root manager, read-only provider, hidden
  actions, cancelable additions and cross-pane refresh. Removed the old removal
  command; favorites import remains palette-only. Added native pane coverage and
  manager documentation/screenshot. Consolidated the older Plan copy into this
  existing canonical Done record, preserving prior provenance.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Updated manager and Favorites aliases, registry assertions, usage docs
  and the existing unreleased entry. The ordinary Add folder label remains unchanged.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Added captured-lifetime commit guards, navigable truncated results,
  lost-process state invalidation, hash-checked owned reuse, worker IPC warmup,
  off-Qt shutdown waits and a reviewed repository license. Expanded existing
  tests and live smoke, updated current design/usage docs, and preserved both
  independent reviews below. Final focused gates passed without skips.

## Validation Results

All child Python commands below used the existing interpreter and
`env=build._environment()` from the repository root. The native Qt run also set
`QT_QPA_PLATFORM=windows`; the exact launcher is documented in
[DEVELOPMENT.md](../DEVELOPMENT.md#tests-and-packaging).

- `python -m unittest fman_unittest.test_everything fman_unittest.test_app_name`:
  47 tests passed, including 31 Everything-specific tests.
- `python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt.EverythingIT`:
  3 native Qt tests passed.
- `python -m fman_integrationtest.everything_smoke`: passed production IPC,
  folder reconfiguration, empty-root stop, owned recovery, shutdown and external
  state isolation. Latest 30-query median: 0.128 ms on the tiny fixture index.
- `python -c "import build; build._ensure_everything(); build._verify_everything(build.EVERYTHING_DIRECTORY)"`:
  actual official portable executable and separate license provisioned and verified.
- `python build.py doc`: strict documentation build passed.
- Editor diagnostics: no errors in changed Python, packaging or task files.
- Initial isolated IPC spike: official packet-layout check and live 1.4.1.1032
  test passed; 30-query median 0.049 ms. Its direct client omits production
  coordination/identity overhead, so that figure is not the production latency.
- Not run: full `python build.py test`, `clean`, `freeze`, frozen-application
  launch, large-index performance, or Everything 1.5. No tests were skipped.

The live smoke report is retained under `UserSettings/Local/EverythingSmokeResults.json`.

### Favorites and Packaging Follow-up

Using the same launcher and Qt environment described above:

- `python -m unittest fman_unittest.test_everything fman_unittest.test_app_name`:
  54 tests passed, including 38 Everything-specific tests. The packaging test
  asserts the `uuid` hidden import; folder tests cover canonical persistence,
  offline favorites, duplicates, cancellation and a single activation request.
- `python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt.EverythingIT`:
  3 tests passed, now covering all four commands, favorites snapshots on Qt,
  one batch update off Qt and repeat-import no-op behavior. An initial status
  thread-affinity failure was corrected and the same test rerun successfully.
- `python -m fman_integrationtest.everything_smoke`: passed production IPC,
  root updates, recovery, shutdown and external-state isolation; 30 warm queries
  had a median of 0.139 ms on the tiny fixture index.
- `python build.py doc`: strict documentation build passed.
- No expected skips. Full suite, `clean`, `freeze` and frozen-application launch
  were not run. The installed application was not modified; it needs a rebuilt
  distribution to include `uuid`.

### Folder Manager Follow-up

The test commands used `build._environment()`; Qt used `QT_QPA_PLATFORM=windows`.

- `python -m unittest fman_unittest.test_everything fman_unittest.test_generate_docs_screenshots`:
  65 passed: 46 Everything tests and 19 screenshot-tool tests.
- `python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt.EverythingIT fman_integrationtest.test_qt.EverythingFoldersIT`:
  5 passed. Includes real command visibility, filter/fuzzy/sort, multi-selection,
  default-No removal, cross-pane refresh and surviving selection, F5/drop, F11,
  Enter navigation and unchanged target filesystem contents.
- Focused source screenshot: load `generate_docs_screenshots`, set
  `SOURCE_CAPTURES = ('everything-folders',)`, run
  `_run_source(_parse_args(['--mode', 'source']))`, then `_validate_image` at
  1280x800. Passed; exactly the two configured rows, no import/action row and
  no Everything manager/process creation. Visually inspected the generated image.
- `python build.py doc`: strict build passed. Editor diagnostics reported no errors.
- Task-location check: no Plan copy; one Completed link to this Done document.
- No expected skips. Full application suite, `clean`, `freeze`, packaged launch
  and new live IPC performance measurements were not run for this follow-up.

### Command Naming Follow-up

- `python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt.EverythingIT.test_plugin_loader_commands_binding_and_unused_lifecycle`:
  1 passed with `build._environment()` and `QT_QPA_PLATFORM=windows`. Verifies
  exact visible labels, stable IDs, Ctrl+E and no runtime startup on plug-in load.
- `python build.py doc`: strict build passed. Changed-file diagnostics were clear.
- No expected skips; full suite and frozen build were not run for this label-only change.

### Reviewer Follow-up Validation

All test commands used the existing interpreter and `build._environment()`.

- `python -m unittest fman_unittest.test_everything fman_unittest.test_app_name fman_unittest.test_generate_docs_screenshots`:
  86 passed (51 Everything, 16 build-name, 19 screenshot-tool tests).
- `python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt.EverythingIT fman_integrationtest.test_qt.EverythingFoldersIT`:
  8 passed with `QT_QPA_PLATFORM=windows`; the same 8 passed with `offscreen`
  and `QT_QPA_FONTDIR` set to the Windows Fonts directory. Covers broad-query
  Return/Escape, five owner-invalidation scenarios, off-Qt warmup/shutdown,
  empty-root no-worker behavior, loader aliases and normal manager workflows.
- `python -m fman_integrationtest.everything_smoke`: passed with the existing
  verified binary. Reused the same owned process identity across manager sessions;
  metadata, reconfiguration, empty-root stop and isolation checks passed.
  Thirty warm queries: median 0.134 ms on the small fixture, not a large-index claim.
- `python -c "import build; build._verify_everything(build.EVERYTHING_DIRECTORY)"`:
  actual executable and reviewed license passed their pins; no download.
- Source-app capture procedure: import `generate_docs_screenshots`, set
  `SOURCE_CAPTURES = ('everything-search', 'everything-folders')`, run
  `_run_source(_parse_args(['--mode', 'source']))`, and validate each image with
  `_validate_image(image, 1280, 800)`. All 3 captures passed real query predicates,
  manager-only no-start checks, source startup and process shutdown.
- `python build.py doc`: strict documentation build passed. Editor diagnostics
  reported no errors in changed source, tests, build/spec and documentation.
- Expected skips: none. Offscreen size-hint notices and the screenshot parser's
  intentional invalid-width error are expected test output, not failures.
- Not run: full application suite, clean/freeze, fresh frozen-application launch,
  large production-index performance or Everything 1.5. No packages or environments
  installed; no ignore-rule, navigation-shortcut, staging or commit changes.

## Implementation Review (2026-10-03)

Verdict: **approved with fixes.** Fix E1 and E2 before release.

The IPC client, packet parsing, stale-reply rejection, ownership-checked
lifecycle, serialized root updates and read-only folder manager match the design.
Thread ownership is respected.

| ID | Priority | Finding | Where |
| --- | --- | --- | --- |
| E1 | P2 | **Enter on a broad query closes the dialog without navigating.** The "Showing N of M" hint is row 0. Quicksearch moves the cursor to row 0 on every text change ([quicksearch.py](../src/main/python/fman/impl/quicksearch.py#L86-L88)), so Enter accepts the hint's empty value. This happens whenever there are more than `max_results` (100) hits, which is common with Everything. The native test only presses Enter on a one-hit query. | `search_items` in [\_\_init\_\_.py](../src/main/resources/base/Plugins/Everything/everything_search/__init__.py) |
| E2 | P2 | **No recovery after the managed instance exits.** The state stays `ready`. `Manager.request` returns early for unchanged settings, so every reopened search shows "Everything instance changed." until the application restarts or a root changes. A fake-runtime probe showed one `apply` call before and after reopening the search. | `Manager.request` in [instance.py](../src/main/resources/base/Plugins/Everything/everything_search/instance.py), `search_items` |
| E3 | P3 | **`exit_with_application: false` has no benefit.** The next session's `apply` adopts the owned instance, then always calls `stop()` and starts a new one. The design says to reuse it. | `ProcessRuntime.apply` |
| E4 | P3 | **The first query of a session can time out.** It must start the IPC thread within the 50 ms deadline; if it misses, a "busy" hint appears and Quicksearch does not query again until the text changes. | `IpcClient.query` |
| E5 | P3 | **Quit can block the Qt thread.** `_dispose` runs on Qt and joins the manager, which can wait up to about 21 s (a 15 s exit poll plus a 5 s process wait) if Everything is slow to exit. | `EverythingService._dispose`, `Manager.close` |
| E6 | P3 | **`License.txt` is fragile and untracked.** It is downloaded from a mutable web page with a pinned SHA-256, so any edit by voidtools breaks `run`/`test`/`freeze` even though the binary is unchanged. Only `*.exe` is ignored, so the downloaded file appears untracked and can be committed by accident. | [build.py](../build.py) `_ensure_everything` |
| E7 | P3 | The plug-in imports `fman.impl` (`PluginService`, `format_size`, `run_in_main_thread`). This is documented as fork coupling, but PlugIn.md asks plug-ins not to import `fman.impl`. | `__init__.py` imports |
| E8 | P3 | Stale text: Scope and Acceptance still describe "Add/Remove folder" commands, but removal now happens through the manager (F8/Delete). | This document |

Recommended fixes:

- **E1:** append the count hint after the hits, or carry the count in the first
  hit's `hint`. Add a regression that presses Return on the `many` query.
- **E2:** on `NotRunning` or an identity mismatch, mark the state as an error, or
  request a forced restart once from the command worker (not from Qt).
- **E3:** reuse an adopted instance whose configuration matches (record an ini
  hash in `owner.json`), or remove the setting.
- **E4:** start the IPC client from `_ensure`, off Qt.
- **E6:** track a reviewed license copy, as `SearchFiles/licenses` does,
  instead of downloading it. Changing ignore rules requires the user's approval.

### Review Validation

Using the existing interpreter and `build._environment()`, with
`QT_QPA_FONTDIR` set to the Windows Fonts folder:

- `python -m unittest fman_unittest.test_everything fman_unittest.test_app_name`:
  62 tests passed.
- `python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt.EverythingIT fman_integrationtest.test_qt.EverythingFoldersIT`
  with `QT_QPA_PLATFORM=windows`: 5 tests passed.

The E2 probe ran `Manager` in-process with a fake runtime and started no real
Everything process. E1 was confirmed by reading the source of Quicksearch's
row-0 cursor placement and accept path. The live `everything_smoke`, the frozen
build and the full suite were not run. No source, test or build files were
changed; only this document was edited.

## Independent Implementation Review (2026-10-03, Sol)

Verdict: **changes required before release.** S1 is new; E1 and E2 below
confirm existing findings, not additional discoveries. The lazy no-op path,
read-only root manager, serialized process updates, IPC ownership/deadline
checks and pinned portable inputs passed focused checks. Prior records and
findings remain unchanged.

| ID | Priority | Finding | Evidence / Required Change |
| --- | --- | --- | --- |
| S1 | P2 | **A folder-add task can persist after plug-in disposal.** [_CollectEverythingFolders](../src/main/resources/base/Plugins/Everything/everything_search/__init__.py#L440) checks only progress-dialog cancellation; [_commit_roots](../src/main/resources/base/Plugins/Everything/everything_search/__init__.py#L349) saves before checking the service's lifetime. | Invalidating a real `UiOwner` during candidate validation disposed the real service, but the command still called `save_json('Everything.json', {'folders': ['C:\\Data']})` once, then alerted that the service was not loaded. The host unload invalidates owners but does not cancel arbitrary `Task` objects. Capture the initiating owner/service generation, cancel or reject stale work, and validate that captured lifetime on Qt before any settings write, provider notification or activation. Check the other root-mutating commands through this shared boundary. Add an owner-invalidation-during-validation regression asserting no persistence, notification or activation. |
| E1 | P2 | **Return on a broad query accepts the count hint.** [search_items](../src/main/resources/base/Plugins/Everything/everything_search/__init__.py#L213) prepends the empty-valued count row, while Quicksearch selects row zero after text changes. | A real native Quicksearch receiving 12,345 total hits selected `(row=0, value='')`; pressing Return closed it and produced zero navigation calls. Keep the first selected row navigable when hits exist, for example by appending the count row. Add native Return coverage for a query exceeding `max_results`, not just the one-hit path. |
| E2 | P2 | **The manager does not recover after the process disappears.** [Manager.request](../src/main/resources/base/Plugins/Everything/everything_search/instance.py#L256) short-circuits unchanged settings while status remains ready; the query failure does not invalidate that state. | With a fake runtime, `NotRunning` produced the instance-changed hint; reopening with the same settings retained ready/generation 1 and only one `apply` call. Mark lost ownership/process state and schedule an ownership-checked retry on the manager worker. A foreign named instance must remain a collision, never permission to stop it. Add unchanged-settings recovery and foreign-instance refusal regressions. |

### Focused Validation

The existing interpreter and `build._environment()` were used throughout.
No Python packages, environment, installed application, ignore rules or
production source were changed. No full suite, clean or freeze was run.

Unit and build gate:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.test_everything','fman_unittest.test_app_name','-q'],env=env,timeout=180).returncode)"
```

Result: 62 passed, no skips. Download messages came from mocked provisioning
fixtures, not network downloads.

Native Quicksearch, loader/lifetime and folder-manager integration:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_SCALE_FACTOR='1',QT_AUTO_SCREEN_SCALE_FACTOR='0',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-m','fman_integrationtest.qt_runner','fman_integrationtest.test_qt.EverythingIT','fman_integrationtest.test_qt.EverythingFoldersIT'],env=env,timeout=180).returncode)"
```

Result: five passed, no skips, covering real pane navigation, filtering/fuzzy
search, two-pane refresh/selection, default-No removal, F5/drop, F11, command
registration and Qt/worker affinity. The existing picker test does not press
Return on its broad-query case, so its success does not disprove E1.

Live IPC/lifecycle smoke against the already provisioned portable executable:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-m','fman_integrationtest.everything_smoke'],env=build._environment(),timeout=180).returncode)"
```

Result: passed metadata, highlights, Unicode/comma and offline roots,
reconfiguration, empty-root stop, changes while stopped, owned recovery and
worker shutdown. The unique named instance and indexed corpus were disposable.
The unnamed instance, executable directory, AppData and voidtools Registry
snapshot remained unchanged. Thirty warm queries had a median of 0.137 ms on
the small fixture, not a production-index performance claim. The smoke updated
its usual ignored `UserSettings/Local/EverythingSmokeResults.json` report.

Offline verification of the actual binary and redistribution license:

```powershell
python -c "import build; build._verify_everything(build.EVERYTHING_DIRECTORY); print('PASS: existing Everything executable and license match pinned SHA256 values')"
```

Result: both existing files matched their pins; no download occurred.

Focused reproduction procedures:

- S1: create the real service with a real `UiOwner`, attach `service.dispose`,
  and run `AddEverythingFolders` with synchronous Task submission. In the
  mocked candidate validator call `owner.invalidate()`, then return the folder.
  With settings and persistence mocked, observed owner inactive, service closed,
  one settings write adding the root, then the service-not-loaded alert. No
  filesystem or real process was involved. Ordinary Task cancellation is covered
  by existing tests; owner invalidation is the missing check.
- E1: construct the real native Quicksearch with production `search_items` and
  mocked ready state/results. Set the query to `many` and press Return using
  `QTest`; observe accepted empty value and no pane navigation.
- E2: activate a real Manager once with a fake runtime, have the fake IPC client
  raise `NotRunning`, then request the same settings as reopening search does.
  Observe ready/generation 1 and one activation call, then close the manager.
- Diagnostics: no errors in the three plug-in modules, build script or spec.

Not run: frozen-application launch, a new freeze, large production-index
performance, Everything 1.5 or a full application correctness suite. Live
owned-orphan recovery passed but does not cover E2's unchanged-settings retry
within the same application session. Only this task document was manually edited.

## Review Response (2026-10-03)

| ID | Disposition | Decisive Check |
| --- | --- | --- |
| S1 | Captured service identity and owner lifetime reach the shared Qt commit guard; stale work returns before settings I/O, notifications or activation. Collection stops on invalidation. | Real owner disposal during drop, Add prompt, Favorites import, removal confirmation and parent confirmation; replaced-service unit check. |
| E1 | Count hint follows real hits, keeping the default selection navigable. | Native Return/Escape on both one-hit and truncated queries. |
| E2 | `NotRunning` invalidates only the matching state; reopening retries unchanged settings on the manager worker. Foreign ownership remains a refusal. | Recovery/collision/stale-generation unit cases plus existing direct foreign-process refusal. |
| E3 | Owner records include a generated-configuration hash. Reuse also verifies executable, name, identity and readiness; changed or legacy records restart safely. | Unit matching/changed/legacy cases and live same-process reuse assertion. |
| E4 | The manager prepares IPC off Qt before publishing ready, outside the first query's deadline. | Native thread-affinity assertion, idempotent client startup test and real source captures. |
| E5 | Qt signals cancellation without joining; a bounded non-daemon cleanup thread performs waits and retains notifications until the producer stops. Empty-root disposal creates no worker. | Blocked runtime shutdown leaves Qt responsive; active and empty lifecycle cases pass. |
| E6 | Repository-owned `licenses/Everything.txt` replaces the mutable license download. Both original notices are preserved; normalized pin, spec and package verification cover the asset. Old generated `bin/License.txt` removed. | Notice-text comparison, offline/tamper/CRLF tests, actual asset verification and spec assertions. |
| E7 | Existing private dependencies retained as an explicit, limited bundled-host exception in PlugIn.md; not exported as public APIs. | Matching-host loader, lifecycle, thread-affinity and source-app checks pass. |
| E8 | Current Scope, Design, Implementation Steps and Acceptance describe Add commands and manager F8/Delete; historical review records remain unchanged. | Current command table and documentation aligned; strict docs build passes. |

Source fixes and recommendations are complete. Rebuilt-distribution validation
remains explicitly unverified; no release approval is implied.
