# Process Pane

## Task

Provide a simple Windows process list in either file pane, with F8 to end one
chosen process using existing Windows permissions. The user approved this reduced
design on 2026_09_18. It supersedes the expanded proposal archived below.

Status: implemented and source-validated; packaged execution has not been tested.

## Scope

- `Show processes`: flat Name/PID list at `process://`, using ordinary pane
  filtering, numeric PID sorting, selection and Ctrl+R manual refresh.
- F8, Shift+Delete and the Delete palette action route to `End process` only
  within the process pane. Accept exactly one selected row or the cursor row.
- Default-No process-specific confirmation, forced termination, identity checks,
  current-permission errors and one refresh of the initiating pane.
- Exclude child navigation, additional columns, live monitoring, batch operations,
  graceful closing, descendant termination, exit waiting and cross-pane refresh.
- No elevation, privilege adjustment, settings, Registry writes or public API
  changes. Generic file deletion, copy/move/create/rename remain unsupported.
- A removable ordinary plug-in, not a host process-management feature. Do not
  install alongside ProcessFS because both claim the same URL scheme.

Compatibility: preserves the public fman 1.7.5 plug-in API. Windows only; the host
must supply compatible pywin32 and Windows `IsProcessCritical` support.

## Design

### Ownership And Dependencies

[process_pane/__init__.py](../src/main/resources/base/Plugins/ProcessPane/process_pane/__init__.py)
owns the filesystem, PID column, commands and listener using public fman APIs.
[processes.py](../src/main/resources/base/Plugins/ProcessPane/process_pane/processes.py)
owns immutable records, the flat snapshot, injectable provider and typed Win32
adapter. No private host imports or new widgets are used.

Reuse the already-declared pywin32 `EnumProcesses` for PIDs. Lazy-load it on first
use; query names and raw creation FILETIME with query-limited handles. Use the
same handle for each name/identity pair, so they describe the same kernel object.
Denied entries display `Unavailable` (known System/Idle names excepted) with no
terminable identity; processes that have exited during enumeration are skipped.
PID 0 is listed as `System Idle Process` without opening a handle and has no
terminable identity. Missing Windows API exports produce an actionable
`ProcessError` naming the required API, surfaced by the command as an alert.
No psutil installation or environment/lock change is needed. The spec explicitly
collects `win32process`; the resource tree already includes plug-in source.

### Flat Rows And Cache

Return Core Name and the plug-in PID column. Rows are non-directories and use
`<sanitized-name>~<pid>~<creation-hex>` paths for name filtering and stable identity.
Restricted rows use `unknown-<generation>`. Names retain Unicode for display;
path delimiters/control characters are sanitized. No OS queries occur in row,
column, existence or resolution methods.

Retain only the current immutable record map, O(P) for P processes. A refresh
lock serializes enumeration; a separate short lock replaces/reads the map. Host
root listing caching is retained; explicitly refreshing clears it. An older
pane may display stale rows, but a missing identity is refused, never mapped to
the new owner of a PID. If the OS changes after snapshot capture, termination's
same-handle check is authoritative. The host rejects stale navigation results.

### F8 And Termination

A public pane listener rewrites `move_to_trash`/`delete_permanently` into
`end_process` only at the process root, preserving explicit `urls` arguments.
Capture one immutable record before confirmation. Reject multiple selections,
roots and foreign URLs. Generic filesystem deletion is deliberately unimplemented.

After a default-No plain-text warning naming the process/PID and unsaved-data
risk, submit one short host Task. Preserve the original name and line breaks,
without HTML escaping. Refuse PID 0, PID 4, self and unknown identities. Open the
target with `PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION`, compare raw
creation time, and check `IsProcessCritical`. Refuse an unsuccessful safety check.
Check cancellation immediately before `TerminateProcess` on that same handle.
Close handles in `finally` on every outcome. No new PID lookup can substitute a
different process between validation and termination.

Report `Termination requested` for five seconds, not confirmed exit, with no wait
or rollback. Access denial, already-exited/stale targets and safety refusal are
actionable alerts. Error 5 acknowledges either permissions or an already exiting
process and suggests refresh; no extra query or exit wait is added.
Only the originating pane reloads, only if it is still at the root.
Ordinary file deletion keeps Core's original confirmation and default.

Copy/move commands, including Core drop routing, are intercepted for process
sources/destinations before Core's directory preparation. No process-specific
Core change was needed. Enter/open and interactive create/rename are refused;
direct filesystem mutation remains unsupported as a second boundary.

### Threading And Persistence

Enumeration uses the host model worker. Commands and submitted tasks use the
existing command worker and public pane/UI dispatch; no persistent worker or
timer is introduced. Cancellation before termination is supported; there is no
batch or exit wait to cancel. Model disposal/navigation is owned by the host.

The only process location is the root. Cold stale saved row URLs fall back there
with no enumeration during existence probes. Opening/restoring the root is use
and may enumerate. No process snapshots or termination history are saved. Unload
unregisters the filesystem, columns and commands using the normal plug-in loader.

## Alternatives

- Expanded ProcessFS-style tree: rejected by user-approved simplification; adds
  ancestry, subtree cache and navigation work without serving the basic workflow.
- psutil: unnecessary for Name/PID after removing optional columns; existing
  pywin32 supplies PIDs, avoiding another native dependency and lock update.
- Handwritten native enumeration: unnecessary because pywin32 is already present.
- PID-only termination: rejected because a stale row can target another process.
- Filesystem delete implementation: rejected because recursive file operations
  should never terminate processes. Retain F8 through a scoped public listener.
- Graceful window close, elevation and exit waiting: outside the approved scope.

## Runtime Effects

- Unused/disabled: no feature scans, native enumerator import, I/O, timers or jobs.
  Registered listeners only inspect URLs for relevant commands while enabled.
- Refresh: O(P) PID enumeration and one query-limited handle per accessible
  process, with O(P) current-snapshot memory and no retained handles. Two panes
  can share the host listing; manual refresh updates it. Rendering does no OS I/O.
- Termination: one process handle, bounded native calls, no polling or waiting.
  Cancellation cannot undo an already issued termination request.
- No subprocess is launched by the feature; only the tests launch disposable
  children. No network, disk scan, process-metadata persistence or Registry write.
- Five native non-elevated snapshots: 285 records, 107 restricted records,
  median 4.06 ms, maximum 5.06 ms. These local measurements are not a portable SLA.

## Tests

Focused modules:

- [test_process_pane.py](../src/unittest/python/fman_unittest/test_process_pane.py):
  record/URL identity, 10,000-row replacement, no per-cell scans, same-handle
  safety, denied/critical/self/stale targets, cancellation, handle closure,
  captured selection, confirmation, routing, unsupported mutation and lazy import.
  Review regressions cover PID 0 without a handle, missing `IsProcessCritical`,
  literal ampersands/newlines, five-second status and ambiguous error 5 wording.
- [ProcessPaneIT](../src/integrationtest/python/fman_integrationtest/test_qt.py):
  real plug-in registry, model, filtering, numeric sorting, reload, actual Core
  F8 binding/controller dispatch, normal file deletion, file/folder drops, stale
  session root restoration, two-pane stale rows and unload while panes are alive.
- Native owned-child test: non-elevated enumeration, reject altered identity,
  terminate only its own disposable child, always clean up. Elevated runs skip
  the standard-user assertion; never test against arbitrary or system processes.

Commands from repository root:

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/ProcessPane') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'windows'
python -m unittest fman_integrationtest.test_qt.ProcessPaneIT fman_unittest.test_process_pane
git diff --check
```

Repeat the focused command with `QT_QPA_PLATFORM=offscreen` for the headless gate.
Check `_environment()` includes the plug-in test path and parse the spec to
assert its `hidden_imports` includes `win32process`; do not invoke a build.
Manual/frozen smoke remains unrun: opening either pane, readable confirmation,
refresh and owned-child termination in a package without development Python.
No full suite, clean, freeze or ZIP generation is authorized for this task.

## Implementation Steps

1. Record the reduced design and review before code; test immutable identities.
2. Add/test the lazy existing-library provider and same-handle Windows safeguards.
3. Register the flat filesystem, commands, single-target task and F8 listener.
4. Verify unit, native owned-child and real Qt integration tests.
5. Add test path/native import declarations and concise user documentation.
6. Record results/limitations, move the canonical document to Done and update links.

## Acceptance Criteria

- Show processes lists Name/PID and supports existing filter/sort/manual refresh.
- F8 ends one confirmed process within current permissions; file panes retain
  ordinary deletion. Multiple targets are rejected and cancellation does nothing.
- Stale identities, self, System, critical and unverifiable targets cannot be
  terminated; the safety checks and action use the same native handle.
- Disabled/unused work is absent, handle closure is tested, and metadata remains
  O(P) without per-cell OS access or feature-specific polling.
- Real registry/Qt and non-elevated owned-child checks pass, including drops,
  session restore, navigation away and another pane invalidating an old row.
- Required focused source tests and build declaration checks pass; packaged and
  human visual smoke are explicitly unverified, with no unauthorized build.

<details>
<summary>Superseded Expanded Proposal (Historical, Not Implemented)</summary>

## Task

Add a bundled `ProcessPane` plug-in inspired by
[mherrmann/ProcessFS](https://github.com/mherrmann/ProcessFS). Users can open the
Windows process list in either file pane, inspect parent/child relationships,
and terminate selected processes when their existing Windows permissions allow
it. Administrator privileges are not required to use the plug-in.

Status: design only; implementation and runtime validation are pending.

## Scope

Included:

- `Show Processes` Command Center command opens `process://` in the active pane.
- Root lists all enumerated processes, not only the user's processes or only
  parentless processes. Enter opens a process's immediate children, matching the
  reference's virtual-directory approach. Back/Up retain ordinary pane behavior.
- Default columns: Name and PID. Additional registered columns: Parent PID,
  User, and Working Set (bytes, formatted for display and sorted numerically).
  Working set is resident memory, not private memory or committed memory.
- Existing selection, sorting, quicksearch, and manual pane reload are reused.
- `Terminate Processes` acts on chosen rows. Existing Delete and permanent-delete
  commands route to it only for process-pane operations.
- Explicit confirmation, safe defaults, permission failures, process-exit races,
  PID-reuse protection, partial results, and cancellation between selected items.
- Current Windows-compatible `psutil` dependency, lock-file update, and frozen
  application verification. Do not vendor the reference's old Python binaries.

Excluded from the first version:

- UAC prompts, elevation helpers, debug privilege enablement, service control,
  bypassing Windows security, or running the file manager as administrator.
- Automatic polling, live CPU graphs, process-tree termination, graceful window
  closing, suspend/resume, priority changes, debugging, and process launch.
- Command lines, environment variables, handles, or executable-specific icons.
  These add privacy, permission, or scanning costs beyond a basic process pane.
- File copy/move/rename/create, trash, archive, or export operations on process
  entries. Processes are not files and cannot be restored from the Recycle Bin.
  Directory-like rows may expose drop affordances; F5/F6 or a drop into the root
  or a process row must produce a clear not-supported alert without invoking the
  process provider. This is deliberate, not a missing `copy` implementation.
- Changes to the public `fman` plug-in API or to upstream ProcessFS's URL contract.
  Do not install this plug-in and upstream ProcessFS simultaneously: both would
  claim `process://`; document the conflict rather than silently overriding it.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. This is
a Windows-only bundled plug-in. Existing file-pane commands remain unchanged.

## Design

### Ownership And Layout

Proposed files under `src/main/resources/base/Plugins/ProcessPane/`:

- `process_pane/__init__.py`: commands, listener, filesystem, and columns.
- `process_pane/processes.py`: snapshot records, identity validation, provider,
  and a narrowly scoped Windows process-handle adapter.
- `README.md`: navigation, refresh, termination, restrictions, and dependency.

Keep enumeration and termination behind an injectable provider so unit tests
never need to inspect or terminate unrelated host processes. The native adapter
owns and closes all handles in `finally` blocks. It must use explicit 64-bit-safe
Win32 function signatures and preserve native error codes.

Use the public abstractions in [fman/fs.py](../src/main/python/fman/fs.py) and
[fman/__init__.py](../src/main/python/fman/__init__.py): `FileSystem`, `Column`,
`DirectoryPaneCommand`, `DirectoryPaneListener`, `Task`, and `submit_task`.
Do not reach through `pane._widget` or import Core's private deletion tasks.

Return `('core.Name', 'process_pane.Pid')` from `get_default_columns`. Reuse
Core's Name column for display/natural sorting and the model's eagerly loaded
column-0 prefix-selection behavior. `name(path)` supplies the original display
name from the snapshot; do not add a second Name column. Implement Parent PID,
User, and Working Set as additional plug-in columns. Format available working
set values with `fman.impl.status_bar.format_size`, already used by Core Size,
and sort by raw bytes, with a consistent separate sort key for unavailable
values. This shared formatter is intentional, tested fork-internal coupling,
not a new public API; reuse the configured 1000/1024 divisor without altering it.

### Process Enumeration And Identity

Use `psutil.process_iter()` for PID, parent PID, and basic name enumeration.
Read optional details once per snapshot as needed for supported columns, not
once for every paint, comparison, or name lookup. A denied optional field is
displayed as `Unavailable`, never as zero. Use `Process.oneshot()` where useful;
catch per-process `AccessDenied` and `NoSuchProcess` without discarding the list.
Do not infer termination permission from the username or an available name.

Each immutable record contains PID, parent PID, display name, optional username
and working set, and a stable creation identity. Obtain the identity from raw
Windows creation `FILETIME` using a query-limited handle and `GetProcessTimes`.
Do not round timestamps or use PID alone as the identity. Verify that details
read through psutil still correspond to the captured identity before publishing
the record; discard records that changed during inspection. Read access may
fail even for visible entries, which remain browsable as restricted records.

Each URL segment is `<sanitized-name>~<pid>~<creation-filetime-hex>`. Root entries have the form
`process://<identity>`; a child is `process://<parent-identity>/<child-identity>`.
Here `<identity>` denotes the complete name-bearing segment, but the authoritative
identity is only its PID and FILETIME suffix. Duplicate names and sanitization
collisions are harmless because that suffix distinguishes the process objects.
Replace `/`, `\`, `~`, and control characters in names with `_`; use `Process`
for an empty name and guard `.`/`..` path components. Keep other name text,
including Unicode, compatible with the host's URL helpers and test round trips.
Never derive a termination identity from the name or silently replace a supplied
suffix with the process currently using that PID.

The name must be in the path because
[FilterBar._accepts](../src/main/python/fman/impl/widgets.py) searches
`basename(url)`, not the Name column. With this format, typing `chr` keeps
`chrome.exe` visible, and prefix selection uses the original name in column 0.
Filtering can also match the PID/suffix; this is acceptable in v1. Queries for
characters replaced during sanitization cannot exactly match those characters
in the basename; document this limited difference from the displayed name.

For an inaccessible creation time, use
`<sanitized-name>~<pid>~unknown-<snapshot-generation>`;
these entries are explicitly non-terminable and must not be upgraded to a live
PID-only target. Strictly validate all URL segments and reject malformed paths.
Keep each segment stable for the lifetime of its snapshot; `resolve` must not
rebuild a URL from a newly observed display name. `GoUp` should find the same
parent-row URL after returning to the containing directory when that record is
still present. An exited/changed row may use the host's normal cursor fallback.

The root includes every process once. Child listings select immediate parent-PID
matches from a fresh snapshot, validate the parent identity, and reject ancestor
cycles. A child created before the proposed parent cannot be its child: exclude
that edge because the parent PID may have been reused. When creation identity is
unavailable, do not invent an authoritative parent-child link; keep the entry at
the root. The relationship remains a best-effort snapshot, not an OS guarantee
that parents and children are still running together.

### Filesystem And Refresh

Implement `iterdir`, `name`, `is_dir`, `exists`, `resolve`, and column query
methods. Every process is an enterable directory, including one with no current
children; empty child lists are valid. This avoids probing processes just to
decide whether Enter should navigate. `name`, `is_dir`, `exists`, `resolve`, and
column methods use bounded URL parsing and O(1) snapshot lookups, never per-row
enumeration or handle opens. This matters because the model and icon provider
query them repeatedly. Root `exists`/`is_dir` return True without a snapshot.
For non-root paths, `exists` returns False if no matching snapshot record exists;
`is_dir`/`resolve` raise `FileNotFoundError` for such paths. A record's presence
does not prove the process remains alive. `iterdir` validates the target identity
against its fresh enumeration and raises `FileNotFoundError` for exited/reused
targets, allowing existing missing-location handling. Unknown-identity records
may open an empty child view while their snapshot remains available; do not
query by PID to invent children or upgrade their identity.
The root always exists, including when enumeration returns an empty list.

`iterdir` captures a coherent snapshot and caches row metadata by complete
identity-bearing path. Column and name queries use these records without fresh
OS calls; missing/evicted display fields show unavailable data until refresh, never
silently resolve to a new process sharing the PID. Use a bounded, lock-protected
snapshot cache (at most eight directory snapshots); evict whole snapshots and
never hold the lock while enumerating or making OS calls. Release old records
on replacement and unload. Lookup and rendering must tolerate eviction while
multiple panes refer to different snapshots.

The host's [model reload](../src/main/python/fman/impl/model/model.py) calls
`MotherFileSystem.clear_cache` before `iterdir`. `MotherFileSystem` caches
directory listings and icons in the child filesystem's `Cache`, not just
`iterdir`. [Cache.clear](../src/main/python/fman/impl/fs_cache.py) removes the
whole cache tree for path `''`, and the named subtree for a non-root path.

On each filesystem `iterdir(path)` invocation, invalidate the corresponding
plug-in snapshot subtree before building the fresh listing; root enumeration
invalidates all plug-in directory snapshots. Descendant metadata must not survive
a root refresh merely because it is held outside the host cache. Issue a
generation ticket before scanning and publish only if it is still current for
that subtree. A concurrent root refresh supersedes older child scans as well as
older root scans. Discard/retry superseded builds under the current generation
instead of republishing them into current metadata. Verify the host cache and
plug-in cache together, including two panes refreshing the same subtree.

`Show Processes` reloads if already at the root. Ordinary host activation reloads
remain allowed; do not add polling, watchers, or a second automatic reload loop.
`watch` and `unwatch` do no work. If another pane still displays invalidated rows,
queries fail safely until its next reload, rather than resolve the PID anew.

### Existing Pane Presentation

The existing icon provider resolves non-local directory URLs and returns its
shared folder icon. Accept that icon for all process rows, including leaves;
do not change `is_dir` to obtain an executable/file icon.

The location bar uses the raw non-file URL, for example
`process://chrome.exe~1234~01dc...`. This readable but technical identity suffix
is a known v1 limitation. A future shared virtual-location display improvement
should consider both this plug-in and [Flat View](../Plan/FlatView.md), not introduce a
process-specific location-bar patch here.

### Commands And Delete Routing

`ShowProcesses` uses command identifier `show_processes`, with alias
`Show processes`. `TerminateProcesses` uses `terminate_processes`, visible only
in a process pane with a chosen row. Visibility checks inspect existing URLs
only, perform no enumeration, and request no process handles.

Use `DirectoryPaneListener.on_command` to rewrite Core `move_to_trash` and
`delete_permanently` to `terminate_processes` when the pane's location is
`process://`. Preserve explicit `urls` arguments and honor them instead of
silently substituting the current selection. Validate the complete target set
before any action; reject mixed schemes and the root. Do not intercept the
replacement command again. Other panes retain the exact existing commands and
arguments. No new global key binding is required.

Core `MoveToTrash.is_visible()` remains true with a process row under the cursor,
so the Command Center can show both `Delete` and `Terminate Processes`. Selecting
either invokes the same process-specific confirmation through the rewrite.
Listeners cannot filter the palette listing; do not promise to hide the Core
entry or change its visibility in file panes.

The existing [Core delete commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)
use file/Recycle Bin wording and can fall back to permanent deletion. Therefore,
do not implement filesystem `delete`, `prepare_delete`, or trash methods as
termination. Leave destructive file APIs unsupported. Only the explicit
termination task can invoke the provider; third-party `fs.delete()` calls,
recursive file operations, and drag/drop cannot unexpectedly terminate anything.

Snapshot chosen records before prompting. Confirmation includes process names,
PIDs, count, and: `Force termination may lose unsaved data. Child processes will
not be terminated automatically.` Default to No, intentionally differing from
Core's default-Yes file-deletion prompt because termination is forcible.
Bound long confirmation lists
and state the remaining count. Canceling starts no termination task. Revalidate
the captured identities after confirmation; never reread the selection to choose
different targets. Deduplicate repeated identities, including nested aliases.

Unsupported transfers must be checked through the real Core copy/move/drop
paths, including folder sources, before implementation is accepted. Target
behavior is an alert such as `Copying files to process:// is not supported.`
(or `Moving ...`), no process-provider calls, and no transfer subtasks executed.
Do not assume every `NotImplementedError` from preparation is already caught:
Core also prepares directory creation and recursive transfers. Use the existing
supported-operation error path if it handles these cases; if not, propose the
smallest owning Core error-handling fix with focused tests before changing Core.
Do not implement filesystem transfer mutations to suppress the error.

### Termination And Windows Permissions

The task opens each captured PID with only `PROCESS_TERMINATE`,
`PROCESS_QUERY_LIMITED_INFORMATION`, and `SYNCHRONIZE`. On that same handle:

1. Compare raw creation `FILETIME` to the selected identity. Refuse a mismatch.
2. Refuse PID 0, the System PID, the file manager's own PID, and unknown identities.
3. Query `IsProcessCritical`; refuse critical processes. If the safety check
   cannot be completed, refuse termination rather than assume it is safe.
4. Check cancellation immediately before calling `TerminateProcess`.
5. Call `TerminateProcess` and wait for exit on the same handle, with short,
   cancellable waits and a two-second maximum confirmation timeout per target.

Using the same handle binds validation and termination to one kernel object,
closing the PID-reuse race between a separate creation-time check and a new
PID-based termination call. Use psutil for enumeration, but not a naive
`Process(pid).terminate()` reconstructed from a stale row.

Normal non-elevated processes owned by the user will usually be accessible.
Elevated applications, other users' processes, services, and protected processes
may deny access. Report `Access denied; your current Windows permissions do not
allow this operation.` Do not offer automatic elevation or imply administrator
rights guarantee success. Keep restricted rows visible where enumeration allows.

Distinguish terminated, already exited, stale identity, refused by safety policy,
access denied, termination requested but exit not confirmed, and unexpected OS
failure. Continue after expected per-target failures and summarize the outcome
once; no cascade of confirmation dialogs. Unexpected programming errors retain
normal plug-in error reporting. A terminated parent does not imply its children
have exited. Never recursively traverse targets for termination.

`TerminateProcess` is asynchronous and forcible. No claim of graceful exit or
rollback is made. Cancellation prevents subsequent calls but cannot undo one
already issued. Only confirmed exits may be described as terminated.

### Threading, Navigation, And Persistence

Enumeration follows the existing filesystem/model worker path. Termination uses
an existing submitted `Task`, not a new persistent worker. Workers operate on
immutable records and local native handles; all model/widget changes use host
dispatch and the public pane APIs. A provider lock protects only short cache
operations, never callbacks or modal dialogs.

After termination, refresh affected process panes in the originating window
through the public window/pane APIs. Recheck each pane's current path before
reload; never navigate a pane back after the user has left it. Other windows
refresh normally on explicit reload or activation. Verify safe dispatch in Qt
integration tests and preserve the host's navigation transaction ordering so a
late listing cannot replace a newer location.

No process snapshots, usernames, or termination history are persisted. Existing
pane history may contain identity-bearing process URLs; stale history navigation
must fail safely and never target the current owner of a recycled PID. No custom
settings or Registry writes are added. Removing/disabling the plug-in must leave
no worker, timer, process handle, or recurring scan behind.

### Session Restore

[SessionManager._init_pane](../src/main/python/fman/impl/session.py) probes saved
locations on a thread pool with `exists`/`is_dir`, then walks existing parents.
On a cold session, non-root process URLs have no snapshot and fail those probes
without importing psutil or enumerating. Parent probing reaches `process://`,
which exists without OS work. Opening that root performs one enumeration for the
listing, not an extra scan for each saved ancestor. Count this per restored pane
load; simultaneous panes may each legitimately request a listing. A warm cached
identity may pass the cheap probe but must still be revalidated by `iterdir`.

Restoring a process pane (or explicitly opening a process URL at launch) is
legitimate feature use during startup: it can import psutil and enumerate.
The no-startup-work guarantee applies when no process pane is requested or
restored. If the dependency is unavailable, preserve the host's normal restore
error/fallback behavior with a concise actionable error, not a crash or retry
loop. Test stale and missing-dependency restoration separately.

### Dependencies And Packaging

Add a maintained `psutil` release compatible with Python 3.14/win-64 to
[environment.yml](../environment.yml) and regenerate
[conda-lock.yml](../conda-lock.yml). Select the version from verified available
packages during implementation, rather than embedding an unverified version here.
Lazy-load it on process-pane use so an unused plug-in does not import the native
extension. Missing/broken dependencies produce one actionable alert on invocation,
not an application startup failure.

The resource tree already bundles plug-in source. Since PyInstaller does not
necessarily discover imports inside resource plug-ins, explicitly collect psutil
and its Windows extension through its supported hook/hidden imports in
[application.spec](../application.spec). Reuse the spec's existing
collection patterns without broad unrelated dependency collection. Add the
plug-in root to [build.py](../build.py)'s test environment. At implementation
completion, document commands and limitations in the main README and changelog.

## Alternatives

- Copy upstream ProcessFS unchanged: rejected. Its PID-only paths, old vendored
  binaries, generic delete behavior, and limited permission handling do not meet
  the intended safety and packaging requirements.
- Use psutil for both listing and PID-based termination: simpler, but a retained
  Windows handle provides an explicit identity check and critical-process check
  on the exact object being terminated.
- Use only native APIs: possible, but adds detail-enumeration code already handled
  by psutil. Keep native code limited to identity and safe termination.
- Parse `tasklist`/`taskkill` or PowerShell output: rejected due to process launch
  overhead, quoting/localization concerns, and weaker snapshot/identity control.
- Automatically elevate: rejected; browsing and managing ordinary user processes
  are useful without increasing the entire file manager's privileges.
- Live one-second refresh: deferred. Manual and existing host reloads give a
  useful first version with predictable cost and stable selections.
- Flat list only: simpler, but child navigation is a defining part of ProcessFS.
- Implement termination as filesystem deletion: rejected to prevent recursive
  file operations and misleading Recycle Bin behavior.

## Runtime Effects

- Startup with no requested/restored process pane: register commands, listener,
  filesystem, and columns. No psutil native import, process scan, process handles,
  timers, or added threads until use. Session restore is first use and is allowed
  to enumerate; ancestor existence probes themselves remain I/O-free.
- Unused/disabled: listener routing performs bounded command/scheme checks only;
  disabled plug-in performs no feature work. Visibility performs no I/O.
- Listing/reload: O(P) process enumeration, metadata, and parent indexing for P
  processes; no O(P squared) parent lookup or per-cell OS access. At most eight
  snapshots retained, with O(P) memory per snapshot and no retained native handles.
- Raw identity acquisition costs at least one `OpenProcess`/`GetProcessTimes`
  pair per accessible process per snapshot, plus detail validation and close
  calls; psutil may open additional handles for details. Measure this separately
  from total enumeration, optional columns, and GUI painting. Provisional target:
  identity acquisition below 100 ms for about 500 processes on the recorded test
  machine, with warm median and p95 over 20 refreshes. This is a benchmark target,
  not an observed guarantee or a portable test timeout. Record process count,
  denied entries, hardware, and psutil version. If exceeded, first profile/reduce
  redundant calls; evaluate bulk `NtQuerySystemInformation` process creation
  timestamps only as a separately reviewed alternative with Windows layout,
  buffer-race, and identity-equivalence tests. Do not automatically substitute an
  additional native enumeration backend based on a timing result.
- Repeated views: share only immutable cached records under a short lock; do not
  introduce a background synchronization service or an unbounded history cache.
- Termination: O(S) native calls for S unique selected identities, one open target
  handle at a time, and at most two seconds of exit waiting per target.
- Cancellation: check between enumeration items where the host exposes task
  cancellation; otherwise rely on host stale-navigation rejection. Submitted
  termination tasks check between targets and while waiting. No indefinite wait.
- I/O: local OS queries only during use; no network, disk scan, subprocess, or
  Registry write. Dependency install/build I/O happens only during development.
- Performance measurements are pending. Before completion, record idle scan
  count, representative refresh latency, repeated-refresh memory behavior, and
  cancellation latency; do not claim measured results in advance.

## Tests

Create `src/unittest/python/fman_unittest/test_process_pane.py` and
`src/integrationtest/python/fman_integrationtest/test_process_pane.py`, reusing
existing unittest/Qt helpers. These filenames are proposed, not existing tests.

Unit coverage with a fake provider:

- Root and immediate-child listings; duplicate names; empty lists; malformed
  URLs; numeric sorting; unknown fields; parent PID reuse and ancestor cycles.
- Name-bearing URL sanitation and Unicode round trips, duplicate sanitized
  names, stable PID/FILETIME suffix parsing, and no identity derivation from names.
- Shared Working Set formatting in decimal/binary modes, unknown-vs-zero display,
  and numeric sort keys; Name remains `core.Name` at column 0.
- Partial access denial and exit during enumeration preserve other records.
- Snapshot replacement/eviction, no per-cell enumeration, and concurrent readers.
- Root refresh invalidates child snapshots; child refresh invalidates descendants;
  out-of-order builds cannot republish stale metadata after a root generation change.
- Delete rewrite arguments, no rewrite loop, file-pane no-op behavior, mixed URL
  rejection, selection freezing, deduplication, and default-No confirmation.
- Unknown/stale identity, self/System/critical processes, failed critical check,
  denied handles, and PID reuse never call `TerminateProcess`.
- Native adapter validates and terminates on the same handle; every success,
  failure, timeout, and cancellation branch closes it exactly once.
- Already-exited, partial success, timeout, canceled wait, and no descendant
  termination; generic filesystem destructive methods remain unsupported.
- Lazy dependency loading and idle path have zero provider calls.

Integration/regression coverage:

- Load plug-in through the real registry; register columns; browse, sort,
  quicksearch, enter children, navigate Up, and reload through the real model.
- Real FilterBar accepts `chrome.exe` when filtering by `chr` and selects its
  Name-column prefix; include PID queries, Unicode, and sanitization cases.
- `GoUp` from a child places the cursor on its parent row when still present.
- Stale session restore with an empty cache falls back to root without enumerating
  in `exists`/`is_dir` or once per ancestor; one listing scan per isolated restore.
  Test simultaneous restored panes and a missing dependency without a retry loop.
- Copy/move/drop from file panes into process root/rows gives the not-supported
  alert, no process-provider calls, and no executed transfer task; test file and
  directory sources. All process rows retain the shared folder icon.
- Two panes, rapid navigation, reload while a listing is outstanding, stale
  history, pane closure, and unload do not mutate Qt models off-thread or restore
  old locations. Verify host cache invalidation actually refreshes metadata.
- Verify actual Delete/permanent-delete routing and no impact on file panes.
- Both visible palette entries reach the same default-No process confirmation;
  normal file-pane deletion keeps Core's existing wording/default.
- Non-admin Windows test launches only an owned disposable child, lists it,
  confirms identity, and terminates it through the provider. Never select or kill
  arbitrary host processes. Clean up the child in `finally`.
- Mock permission/protected-process failures; do not terminate real system or
  elevated applications. Skip the non-admin assertion when the test runner is
  elevated, reporting the skip rather than claiming standard-user validation.
- Deterministic synthetic 10,000-record test asserts one enumeration per reload,
  linear parent indexing, bounded cache size, and no enumeration during sorting.
- Manual source/frozen smoke: process pane in either side, restricted entries,
  permission message, canceled confirmation, owned disposable child termination,
  navigation away, and unchanged file-pane operations. Check package works without
  development Python on PATH and contains psutil's native extension.

Focused commands after the proposed tests exist, from repository root:

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/ProcessPane') -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_process_pane
python -m unittest fman_integrationtest.test_process_pane
conda-lock lock -f environment.yml -p win-64
python build.py freeze
git diff --check
```

Run the narrowest new unit check immediately after the first implementation edit.
Add focused existing tests for any shared file deliberately changed during
implementation. Run the two test modules and frozen smoke before completion.
Do not run `python build.py test` unless explicitly requested. For interactive
source smoke, launch `python build.py run` without the offscreen Qt setting.

## Implementation Steps

1. Implement and test immutable records, URL identities, snapshot indexing, and
   the injected provider using fake processes. No real termination yet.
2. Add the lazy psutil provider and typed native adapter; test identity, safety
   checks, handle ownership, access errors, and owned-child behavior.
3. Register filesystem, columns, and Show Processes; verify real model reload,
   tree navigation, permissions, cache limits, and stale-result handling.
4. Add explicit termination command/task and scoped delete-command routing;
   validate confirmation, selection capture, cancellation, and partial outcomes.
5. Add dependency/lock/build changes; verify source and frozen non-admin smoke.
6. Update README/changelog and record exact results, skips, and implementation
   provenance. Move this canonical task to Done and update the index only after
   acceptance criteria pass. Preserve reviewer history.

## Acceptance Criteria

- Standard users can open a process list in either pane and inspect child
  relationships without UAC prompts; denied details do not break the list.
- PID and names remain distinct, sorting is numeric where appropriate, and manual
  refresh updates process state without recurring polling or per-cell scans.
- Name type-ahead, prefix selection, and parent cursor restoration work through
  the existing pane implementations with the name-bearing URL format.
- Cold saved process locations restore to root without OS work in existence
  probes; root refresh invalidates all cached descendants and rejects stale builds.
- Confirmed termination works for an owned disposable non-elevated process.
- Stale/reused PIDs, unknown identities, critical processes, and the file manager
  itself cannot be terminated by the plug-in's action.
- Windows permission failures are clear; no automatic elevation, descendant
  termination, generic filesystem deletion, or Recycle Bin promise occurs.
- Cancellation and navigation do not cause wrong-target actions, leaked handles,
  stale UI replacement, or off-thread Qt access.
- Focused unit/Qt tests, standard-user smoke, bounded-cache checks, and packaged
  psutil execution pass; expected skips and remaining gaps are documented.
- Public API and ordinary file operations are preserved; disabled/unused behavior
  has no feature-specific scans, I/O, jobs, timers, or native dependency load.
- File-to-process transfers fail with a clear not-supported alert and no mutation;
  folder icons and technical location-bar suffixes are documented limitations.

</details>

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Designed against upstream ProcessFS and local filesystem, command
  rewrite, task, model reload, and packaging interfaces. Selected non-admin
  operation, explicit termination routing, and same-handle identity validation.
  Implementation must prove cache refresh, Qt dispatch, non-admin permissions,
  and frozen native-extension collection with the focused checks above.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Not yet approved. The safety design (same-handle identity check,
  `IsProcessCritical`, explicit termination command instead of filesystem
  deletion, listener-based delete routing) is correct and verified against
  `DirectoryPane.run_command`, Core `MoveToTrash`/`_Delete`, and `GoUp`. One
  design decision breaks an existing pane feature (task 1) and must be
  changed before implementation; the rest are gaps to fill in the document.

#### Follow Up Tasks

Checklist updated at the user's request: checked means incorporated into the
design or planned tests, not implemented or runtime-validated. Qualifications
for transfer handling, identity cost, and cache behavior are recorded under
Prior Review Disposition. The process item was initially rejected there, then
closed after the user explicitly standardized the repository label as
`Context Window`.

Blocking:

- [x] **URL segments must contain the process name.** The pane's type-ahead
      filter (`FilterBar._accepts` in `fman/impl/widgets.py`) matches the typed
      text against `basename(url)`, not against the `Name` column. With
      segments of the form `<pid>-<filetime-hex>`, typing `chr` to jump to
      `chrome.exe` hides every row. The plan's "names are column values, not
      path components" therefore has to be reversed: use
      `<sanitized-name>~<pid>~<filetime-hex>` (replace `/`, `\`, `~` and
      control characters in the name; identity is still the PID+FILETIME
      suffix, so duplicate names remain harmless). Side benefit: `GoUp` from a
      child places the cursor by rebuilding the URL, and the location bar
      becomes readable. Add a unit test that the pane filter accepts a row
      when the typed text is a prefix of the process name.

Design gaps to close in the document:

- [x] **Reuse `core.Name` as column 0.** `Model` loads column 0 eagerly for
      every row as the type-ahead anchor and `FilterBar._select_row_with_prefix`
      reads its `DisplayRole`. Declaring `get_default_columns` as
      `('core.Name', 'process_pane.Pid')` gives natural sort and the existing
      hidden-file filter behaviour for free; the plug-in only needs to answer
      `name(path)` from the snapshot. State explicitly that `name`, `is_dir`
      and every column query are O(1) snapshot lookups because the model calls
      them on the worker for all rows.
- [x] **Session restore path.** Pane locations are persisted; if the user quits
      inside `process://…`, `SessionManager._init_pane` calls `exists()` on the
      stale identity at startup (from a thread pool), falls back to the root via
      `get_existing_pardir`, and the pane opens on the process list. This is a
      legitimate first use but it imports psutil during startup and contradicts
      the literal "no native import at startup" wording; document it, and make
      `exists()` on a stale identity return `False` without enumerating (parse
      the segment, compare against the current snapshot only if one exists).
- [x] **Drag and drop / copy into a process pane.** `is_dir=True` makes every
      row drop-enabled (`DragAndDrop.canDropMimeData`) and `F5`/`F6` from a file
      pane into `process://` reach `prepare_copy`/`prepare_move`, which raise
      `NotImplementedError` → Core shows "not supported". Acceptable, but list
      it under Scope/Excluded with the resulting alert text and add a test so
      nobody "fixes" it by implementing `copy`.
- [x] **Icons.** `IconProvider.get_icon` shows the folder icon for every
      `is_dir` entry on a non-`file://` scheme. Either accept and state it, or
      return `is_dir=False` for leaf processes (loses the "enter children"
      affordance) — the former is consistent with the design; say so.
- [x] **Identity acquisition cost.** Obtaining raw creation `FILETIME` needs one
      `OpenProcess` + `GetProcessTimes` per process per snapshot (≈300 handle
      opens per refresh). Fine, but state the measured cost target
      (< 100 ms for 500 processes) and the alternative if it is exceeded:
      `NtQuerySystemInformation(SystemProcessInformation)` returns
      `CreateTime` for all processes in one call without handles.
- [x] **`Working Set` formatting.** Reuse the shared size formatter introduced
      by the Status Bar task rather than a new one; name it in Design.
- [x] **Location bar.** `as_human_readable` returns the raw URL for non-`file://`
      schemes, so the bar shows `process://chrome.exe~1234~01dc…`. Acceptable
      for v1 once task 1 lands; note it as a known limitation alongside the
      Flat View plan's location-bar remark so both are solved together.
- [x] **Confirmation dialog default.** Core's `MoveToTrash` defaults to `YES`;
      the plan defaults to `NO`. Correct choice for a forcible kill; state that
      this intentionally differs from the file-deletion prompt so the routing
      does not look inconsistent.
- [x] **Command palette visibility.** `MoveToTrash.is_visible()` returns
      `True` in a process pane, so the palette shows both `Delete` and
      `Terminate processes`; the former is rewritten on execution. State this,
      or hide `Delete` via `on_command` only (palette listing cannot be
      filtered by a listener) — the former is the honest option.
- [x] **Model cache interaction.** Confirm in Design that `MotherFileSystem`
      caches only `iterdir` (per path) and that `clear_cache('')` on root reload
      resets the whole `process://` cache tree; the plug-in snapshot cache must
      be keyed so a reload of `process://` also invalidates child listings
      cached under it, otherwise a child directory shows stale rows after a
      root refresh until the user reloads there.

Tests to add:

- [x] Type-ahead filter acceptance by process name (task 1).
- [x] Session restore with a stale `process://` location lands on the root
      without enumerating twice.
- [x] Drop/copy into the process pane produces the "not supported" alert and no
      provider call.
- [x] `GoUp` from a child places the cursor on the parent row.

Process:

- [x] Reviewer records: standardized `Context Window` in both repository templates
  and this plan's field labels at the user's request. Recorded values are
  unchanged; the earlier rejection is superseded by this policy change.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Integrated the justified prior review findings into the design and
  acceptance tests. This remains a plan, not an implemented or runtime-validated
  feature. Earlier reviewer records and checklists are preserved verbatim;
  disposition below supersedes their pending design actions without rewriting
  another contributor's record.

#### Prior Review Disposition

- Accepted: name-bearing URL segments, explicit `core.Name` column 0, snapshot-only
  row queries, session-restore first-use exception, shared folder icons, shared
  `fman.impl.status_bar.format_size`, raw location-bar limitation, intentional
  default-No confirmation, and the two visible palette entries.
- Accepted: filter acceptance, session restore, unsupported transfer, and GoUp
  cursor regression tests, now listed explicitly in Tests.
- Accepted with correction: subtree cache invalidation. `MotherFileSystem` caches
  both listings and icons. Root `Cache.clear('')` clears the host tree; the design
  now invalidates matching plug-in snapshots and rejects superseded scan results.
- Accepted with qualification: unsupported transfer behavior is the required
  result, not a verified assertion that every current Core preparation branch
  catches `NotImplementedError`. Integration must prove it for files/directories
  and drop/F5/F6; any required Core fix needs a focused scope decision.
- Accepted as a measurement target: per-process native identity costs and the
  suggested 100 ms/500-process goal. No timings have been measured. Bulk NT
  enumeration is a candidate requiring further review, not a selected fallback.
- Rejected: changing provenance field spelling to `Context Window`. The current
  repository template explicitly uses `Context window`; this record follows it.
  Historical records, including other contributors' supplied metadata, are intact.

#### Design Validation

- Compared the findings with FilterBar filtering/prefix selection, Core GoUp and
  transfer preparation, SessionManager restoration, IconProvider, the shared size
  formatter, host Cache clearing, and the current repository provenance template.
- Documentation-only checks: required sections, relative-link targets, preserved
  prior reviewer records, and `git diff --check`. No plug-in code exists yet, so
  proposed unit/Qt tests, performance measurements, and package checks remain pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Marked 15 incorporated review items as checked at the user's request,
  including qualified acceptances; left the rejected capitalization item unchecked.
  Checkmarks record design incorporation only. This explicitly supersedes the
  previous record's statement that checklists remained verbatim; review wording
  and existing signatures are unchanged. No implementation or test completion is
  claimed. Validation checks checklist counts and `git diff --check`.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Applied the user's explicit `Context Window` spelling to the repository
  templates and this plan's field labels. Closed the capitalization item. This
  supersedes the earlier rejection and unchecked status, not the historical
  reasoning or recorded values. Case-sensitive label checks and
  `git diff --check` validate this documentation-only change.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Feasibility/difficulty assessment only; no implementation approval
  or runtime validation. Estimated medium-high difficulty (7/10), about 5-8
  focused developer-days for the full planned safety, integration and packaging
  checks, assuming familiarity with this repository. A read-only process-list
  prototype is roughly 1-2 days and is not equivalent to the complete task.

#### Third-Party Plug-In Assessment

- The user requires a third-party-style plug-in. Public `FileSystem`, `Column`,
  pane commands/listeners and tasks cover the primary workflow; process logic
  should not require a custom host widget or process-specific host API.
- The current plan is not fully independent: it imports the private
  `fman.impl.status_bar.format_size` and assumes host environment/spec changes
  for psutil. Before implementation, replace the private formatting dependency
  with plug-in-owned formatting or an already public utility, and decide how a
  separately installed plug-in supplies a compatible native psutil dependency.
  A bundled removable plug-in and an independently installable distribution
  can share source, but do not have identical dependency-delivery requirements.
- Upstream [ProcessFS source](https://github.com/mherrmann/ProcessFS/blob/master/processfs/__init__.py)
  uses the public filesystem/command APIs. It did target Windows: its
  [vendored psutil](https://github.com/mherrmann/ProcessFS/tree/master/psutil)
  includes `cp35-win32` and `cp36-win32` native modules. Those binaries cannot
  be reused with this project's Python 3.14/win-64 runtime. Modern psutil
  supports Windows; exact package and frozen-import compatibility remain to
  be verified, not assumed from the old example.
- Most effort is in wrong-process prevention (PID reuse and same-handle
  termination), Windows permission/critical-process handling, snapshot cache
  consistency, two-pane refresh/session restore, and owned-child tests.
  Enumeration and column registration are the simpler parts.
- One concrete integration risk remains: Core's `_TreeCommand.__call__` calls
  `makedirs(dest_dir, exist_ok=True)` before its transfer task, while base
  `FileSystem.mkdir` raises `NotImplementedError`. Thus friendly rejection of
  transfers into `process://` is not proven merely by leaving `copy`/`move`
  unsupported. Verify command-level interception or generic unsupported-
  operation handling without embedding process-specific logic in Core.
- Checked the plan, upstream source/native filenames, current public filesystem
  and listener interfaces, and Core transfer entry point. Only the appended
  assessment was edited. No process was enumerated or terminated, no package
  installed, and no build, test suite or frozen smoke was run. Documentation
  validation: `git diff --check -- Plan/ProcessPane.md` and editor diagnostics.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed and approved the user's reduced flat-list/F8 design above
  for implementation, with focused, observable safety and integration gates.
  Removed tree browsing, optional columns, multi-target tasks, cross-pane refresh,
  exit waiting and the private formatter dependency. Keep one-target confirmation,
  same-handle identity checks and existing-permission-only operation. Earlier
  expanded-scope estimates and acceptance criteria are superseded.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Approved reuse of existing pywin32 PID enumeration for the reduced
  Name/PID scope instead of adding psutil. Native handle queries supply coherent
  name/creation identity and same-handle termination. Tests proved current-user
  operation, F8 dispatch, denied/stale safeguards and ordinary file behavior.
  Source gates passed; packaged execution is explicitly unverified, not a claimed
  result. The archived expanded proposal no longer controls acceptance.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Accepted implementation-review items (1)-(4) and reproduced each with
  focused regressions. Also addressed note (5) through accurate error wording.
  The fixes preserve the reduced design, same-handle safeguards and public API;
  no additional native queries, polling, privileges or dependencies are needed.
  Packaged smoke remains a release gate, not authorization to build here.

## Implementer

### 2026_09_18 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented the standalone-layout flat ProcessPane using public fman
  APIs and existing pywin32, with scoped F8 termination and no process-specific
  host changes. Added 23 unit/native tests and 3 real-registry Qt tests. Updated
  test discovery, native import declaration, usage documentation and changelog.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation matches the approved reduced design. Re-ran the focused
  gate offscreen: `fman_integrationtest.test_qt.ProcessPaneIT` plus
  `fman_unittest.test_process_pane`, 26 tests OK, no skips. Verified `win32process`
  in the spec hidden imports, the plug-in on `build.py`'s test path, README and
  CHANGELOG entries, the Plan/Done move and index update. Code review confirmed:
  same-handle validation and termination with `PROCESS_TERMINATE |
  PROCESS_QUERY_LIMITED_INFORMATION`, `IsProcessCritical` refusal, PID 0/4/self
  and unknown-identity refusal, cancellation check immediately before
  `TerminateProcess`, handles closed in `finally`, `ProcessError` not swallowed by
  the `OSError` handler, O(1) snapshot lookups in `name`/`is_dir`/`resolve`/PID
  column, cold-restore probes without enumeration, and listener interception of
  `copy`/`move` for process sources or destinations (covering F5 from a file pane
  before Core's `makedirs`). Open items for the implementer, not fixed here:
  (1) `OpenProcess(0)` fails with error 87 on this machine, so `snapshot()` skips
  PID 0 and the `'System Idle Process'` name mapping is unreachable; either
  special-case PID 0 before opening or drop the mapping. (2) `html.escape` in the
  confirmation is counterproductive: QMessageBox renders plain text unless it
  detects markup, so a name containing `&` shows `&amp;`, and when markup is
  detected the `\n\n` collapses; image basenames cannot contain `<`/`>`, so pass
  the raw name. (3) On Windows older than 8.1, `WindowsApi()` raises
  `AttributeError` for `IsProcessCritical`, escaping `get_provider` as a traceback
  instead of the actionable `ProcessError`. (4) The `Termination requested` status
  message has no timeout, unlike the other messages. (5) `TerminateProcess` can
  return error 5 for a process that is already exiting; the "Access denied"
  wording is then misleading, note only. Packaged execution remains unverified as
  documented; run the frozen smoke before the next release.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Follow-up pass. Plug-in source is unchanged since the previous review
  (`html.escape` at `__init__.py:87`, untimed status at `:96`, unguarded
  `IsProcessCritical` binding and unreachable PID 0 name mapping in
  `processes.py`). Focused gate re-run offscreen: `ProcessPaneIT` plus
  `test_process_pane`, 26 tests OK, no skips. Design conformance and the
  same-handle safety path stand; open items (1)-(4) above remain for the
  implementer, and packaged smoke is still unverified.

### 2026_09_18 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Closed review items (1)-(4): emit a restricted PID 0 row without a
  handle, preserve literal confirmation text, translate missing Windows exports
  to `ProcessError`, and expire status after five seconds. Also clarified note
  (5), the ambiguous error 5 response. Added three regressions and strengthened
  existing assertions. All 29 focused tests pass with offscreen and native
  Windows Qt, without skips; earlier reviewer records are preserved.

## Validation Results

- First code gate: `python -m unittest fman_unittest.test_process_pane.SnapshotTest`
  passed (3 tests at that stage), immediately after the first code edit.
- `python -m unittest fman_integrationtest.test_qt.ProcessPaneIT fman_unittest.test_process_pane`
  passed all 26 tests with both offscreen and native Windows Qt. No skips in
  either final run. The owned-child test confirmed a non-elevated process.
- Initial Qt fixture failures were corrected: unload before widget destruction,
  restore previously imported plug-in modules after real-loader tests, and
  explicitly refresh the second pane to invalidate the host's shared root cache.
  The same focused command passed after repair; no production host workaround.
- A focused `runpy`/AST check called only `build._environment()` and parsed the
  spec: ProcessPane is on the test path, `win32process` is in hidden imports, and
  the existing installed extension exposes `EnumProcesses`. No build executed.
- Five read-only snapshots measured aggregate count/latency only: 285 records,
  107 restricted, median 4.06 ms, max 5.06 ms; no process names/paths were logged.
- Editor diagnostics and `git diff --check` reported no new errors at the checks
  run. Documentation links/sections and final diff are checked before completion.
- Not run: full test suite, clean/freeze/package, portable ZIP, frozen executable
  smoke, and human visual inspection. No packages installed, environment created,
  arbitrary process terminated, elevation requested, or Registry write added.

### 2026_09_18 Review Fixes

Use the repository-root `PYTHONPATH` command in Tests above.

- `python -m unittest fman_unittest.test_process_pane.ProviderTest.test_idle_process_is_listed_without_opening_a_handle`
  failed before the PID 0 fix and passed immediately afterward.
- `python -m unittest fman_unittest.test_process_pane.ProviderCompatibilityTest fman_unittest.test_process_pane.PaneCommandTest.test_confirmation_preserves_plain_process_name_and_line_breaks fman_unittest.test_process_pane.PaneCommandTest.test_confirm_uses_captured_record_and_only_reloads_current_pane`
  reproduced all three remaining findings, then passed all three after repair.
- `python -m unittest fman_unittest.test_process_pane.ProviderTest` passed all
  nine provider tests after refining error 5 and the PID 0 error-87 fixture.
- `python -m unittest fman_integrationtest.test_qt.ProcessPaneIT fman_unittest.test_process_pane`
  passed 29 tests with `QT_QPA_PLATFORM=offscreen` and again with `windows`,
  without skips. Offscreen Qt reported missing-font-directory and sizing-plugin
  warnings; native Windows Qt completed without those warnings. The native test
  terminated only its own disposable child and confirmed non-elevated execution.
- Packaged smoke, human visual inspection and older-Windows execution remain
  unverified. The missing-export path is tested with an injected kernel lacking
  `IsProcessCritical`. No full suite, clean, freeze, package or ZIP was run.
- No separate changelog fix entry: ProcessPane is already under `Unreleased`.