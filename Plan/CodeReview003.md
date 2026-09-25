# Code Review 003: Low-Risk Safety and Performance

Status: Design only, 2026-09-24. Application code is unchanged. Implementation
requires review of this design and separate authorization.

## Task

Find small, independently testable improvements to data safety, correctness,
edge-case handling and performance. Preserve ordinary successful behavior and
avoid architecture changes. "Low risk" means narrow ownership and measurable
regression checks, not a promise of zero risk.

## Scope

The review covered first-party runtime, bundled plug-ins, build/release support,
documentation tools and performance tooling through a repository-wide static
sweep and risk-directed source/caller/test inspection. The initial inventory
parsed 144 Python/spec files, 29,310 lines and 2,590 functions, excluding test
modules, generated output and installed dependencies. This is not a claim that
every branch was executed or every line received an exhaustive audit.

Selected work: twenty-one small changes below, grouped by their existing owners. No
new dependency, setting, command, background service or public API is needed.
Preserve portable UserSettings paths, plug-in contracts, Qt thread ownership,
ordinary overwrite prompts, case-only rename behavior and disabled-feature cost.

Excluded: redesigning snapshots, file-transfer transactions, archive verification,
plug-in lifecycles, shared command concurrency, search-engine redesigns,
packaging or release policy. No README, changelog, application or test edits in
this planning pass. Larger findings are recorded below, not silently included
in the batch.

## Design

### 1. Do Not Recurse Through Junctions During Delete (P1)

Owner: [LocalFileSystem.prepare_delete](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L212).

Evidence: the directory check follows targets and excludes symbolic links, but
not Windows junctions. A disposable selected directory containing a junction
to a sibling target produced a delete task for the target's `keep.txt`. Only
task enumeration was performed; no target-delete task was executed.

Design: recognize a junction before recursive enumeration and yield only its
own removal using `os.rmdir`. Check links before following target metadata so
dangling junctions are handled too. Preserve ordinary directory recursion,
existing symbolic-link handling and notifications for the selected link itself.
Use the existing supported Python junction API; do not classify every reparse
point as a junction. Junction-removal failures must propagate without entering
the target-following read-only permission retry. Do not change target contents
or permissions. This does not solve concurrent path substitution attacks.

Risk: low and Windows-specific; native junction target-retention tests are a
mandatory gate. No copy/move junction policy changes in this item.

### 2. Reject Copying Onto the Same File (P1)

Owner: [CopyFile.__call__](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L364).

Evidence: direct copy onto a hardlink alias truncated the source to zero bytes.
The same failure was reproduced through real `CopyFiles` directory merging with
an existing destination hardlink and overwrite accepted. Top-level ancestry
checks do not protect individual merged descendants.

Design: before opening the destination for writing, perform a fresh OS identity
comparison when the destination exists; raise `shutil.SameFileError` for an
alias. Do not trust cached provider stat values for this destructive decision.
Treat only a missing destination as the normal create case; preserve other
errors. Keep the existing symbolic-link copy branch unchanged. Locate the guard
in the leaf copy task so direct, prepared and merged copies are protected.

Risk: low; one extra destination identity check on existing-file copies. Preserve
the existing file and both names on refusal. No rename changes, full-file
hashing or transactional overwrite staging in this item. A pre-open check does
not eliminate every concurrent filesystem race.

### 3. Propagate Failed Deletes Truthfully (P2)

Owner: [LocalFileSystem._do_delete](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L232).

Evidence: an injected `PermissionError` for a writable file returned normally
and emitted `notify_file_removed`. The exception handler only retries read-only
files; its writable branch currently falls through as if deletion succeeded.

Design: re-raise the original failure when the read-only retry does not apply.
Retry only after successfully observing read-only metadata; a failed stat must
re-raise the original deletion error. Retain the permission adjustment and
single retry for ordinary read-only files.
Emit removal notification only after a successful deletion. Preserve the
existing caller's continue/abort error UI and exception identity.

Risk: very low; failed operations become visible instead of falsely succeeding.

### 4. Preserve Session/Dialogs JSON on Failed Saves (P2)

Owner: [Settings](../src/main/python/fman/impl/util/settings.py), used by
[SessionManager](../src/main/python/fman/impl/session.py) and dialog preferences.

Evidence: adding an unserializable value then calling `flush()` left an existing
valid JSON file truncated and invalid. Valid JSON roots `[]`, `null` and `1`
also caused `get()` to raise `AttributeError`. The separate
[Config writer](../src/main/python/fman/impl/plugins/config.py#L116) already uses
temporary-file replacement; it is not part of this defect.

Design: serialize before touching the live file, write a unique sibling temporary
file, close it, then publish with `os.replace`. Always clean up the owned
temporary file, preserving the original exception if cleanup also fails.
Use an exclusively created temp file and close its handle before replacement
for Windows compatibility. Preserve JSON shape, existing serialization/encoding
behavior, synchronous call ownership and last-writer-wins behavior. Validate
the loaded root as a dictionary; otherwise use the existing empty-settings
fallback without rewriting anything during load.

An existing linked settings file must not be silently replaced by a regular file.
For this batch, refuse that save with `OSError`, leaving link and target untouched;
transparent linked-settings persistence requires a separately reviewed policy.

Risk: low but broader than a one-line fix; require injected serialization,
write/close and replacement failures. No new lock, schema migration, backup
rotation or durability guarantee against sudden power loss. Do not move Config
onto a new shared abstraction solely for this change.

### 5. Restore Temporary Command Context on Exceptions (P2)

Owners: [DirectoryPane._override_file_under_cursor](../src/main/python/fman/__init__.py#L218)
and [PaneCommandRegistry._set_context](../src/main/python/fman/impl/plugins/command_registry.py#L152).

Evidence: raising inside the registry context left the pane pointing at the
temporary filename. Nested overrides restored the ordinary cursor too early,
instead of restoring the outer override. A later command can see the wrong file.

Design: use structured context management in the registry; in the pane helper,
capture the previously installed getter and restore it in `finally`. Exceptions
must propagate unchanged. No public signatures or command dispatch changes.

Risk: low for normal, exceptional and nested same-thread use. Concurrent command
overrides remain a separate ownership problem; do not claim this fixes them.

### 6. Check Cancellation While Skipping Merge Entries (P2)

Owner: [FileTreeOperation._merge_directory](../src/main/resources/base/Plugins/Core/core/fileoperations.py#L109).

Evidence: merging 100 existing files with "No to all" made zero cancellation
checks inside the loop. `_enqueue` checks cancellation only for accepted work,
so a large skipped merge continues scanning after cancel.

Design: iterate through the existing cancellation-aware `self._iter(...)` helper.
Keep traversal order, prompts and planned tasks unchanged. Do not replace eager
provider `iterdir` implementations or add cancellation threads/timers.

Risk: very low; one existing cancellation check per enumerated child. A blocked
OS enumeration still cannot be interrupted by this change.

### 7. Release Work Capacity When Thread Start Fails (P2)

Owner: [submit_work](../src/main/python/fman/impl/ui/__init__.py#L179).

Evidence: two mocked `Thread.start()` failures exhausted both semaphore slots;
no worker existed to execute the existing `finally` release.

Design: protect thread construction/start and release the acquired slot on
startup failure before re-raising. A successfully started worker keeps sole
ownership of its existing release. Preserve the Boolean busy result, exception
behavior and two-worker limit; do not change the executor model.

Risk: very low; cover construction failure, start failure, work/delivery failure
and successful reuse to prevent double release.

### 8. Allocate Shared Resources Only on Cache Miss (P3)

Owner: [resource](../src/main/python/fman/impl/ui/__init__.py#L80).

Evidence: eleven lookups of one key constructed eleven `Resource` objects,
although all returned the same cached instance. `setdefault` eagerly evaluates
its default, constructing unused locks and a semaphore on every hit.

Design: use explicit lookup/miss insertion while holding the existing lock.
Preserve stable identity, revision/subscriber state, key semantics and locking.

Risk: very low. Deterministic constructor-count tests prove the saved work;
do not claim a measured end-to-end speedup.

### 9. Mark Unreadable File Totals Incomplete (P2)

Owner: [calculate_status_summary](../src/main/python/fman/impl/status_bar.py#L80).

Evidence: an unreadable loaded file produced `size_bytes=0` and
`size_complete=True`; the status bar can display a partial sum as an exact total.

Design: track failure to obtain a file's size and include it in the total's
completeness flag. Preserve visible counts, successful subtotals, query limits,
unsupported-size behavior and selected-only completeness. Reuse the existing
incomplete display; no new UI state or retry work.

Risk: very low; failed unselected files must affect the total without incorrectly
making a fully measured selection incomplete. Successful zero-byte files remain
complete. Keep disabled mode free of new work.

### 10. Build Each Status URL Once (P3)

Owner: [ListingModel.get_status_entries](../src/main/python/fman/impl/model/listing.py#L451).

Evidence: a 10,000-row snapshot called `join` 20,000 times: once for the entry URL
and again for selection membership. This work runs when the Qt thread captures
the enabled status bar's snapshot.

Design: build the URL once per visible row and reuse it in `StatusEntry`.
Preserve tuple output, order, selected membership and immutable-worker input.
No additional cache, scan, worker or changes to snapshot APIs.

Risk: very low. Require exactly one URL construction per row and equivalent
results, not a noisy wall-clock threshold.

### 11. Remove a Partially Written Copy on Cancellation or Error (P2)

Owner: [CopyFile.__call__](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L364).

Evidence: `check_canceled()` raises inside the `with open(dst, 'wb')` block, and
any read/write `OSError` does the same. The destination is left as a truncated
file with no `copystat` and no `notify_file_added`; a later listing shows a
plausible-looking file with the wrong size. When the destination did not exist
before the copy, the partial file is pure garbage.

Design: wrap the data loop in `try/except BaseException`; if `dst_existed` is
false, `os.remove(dst)` (ignoring `FileNotFoundError`) before re-raising. When
the destination existed, leave it as is (restoring the old content needs the
atomic-replacement design already excluded) and keep re-raising. Cancellation
and error identity are unchanged.

Risk: very low; only the create-new case removes a file, and only the one this
task created. Test: cancel after the first chunk, injected write error, existing
destination untouched, notification still suppressed on failure.

### 12. Do Not Move Through a Junction or Directory Symlink (P1)

Owner: [LocalFileSystem._prepare_move](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L133) and `_prepare_copy`.

Evidence (code path; not executed): both helpers classify the source with
`self.is_dir(src_path)`, which follows the link. A cross-device move of a
junction or directory symlink therefore recurses into the *target*, yields
`MoveByCopying` (copy + delete) for every target file and `DeleteIfEmpty` for
the link. The result is that the target directory is emptied and the link
dangles. Same-device moves rename the link and are safe; copy follows the target
(as Explorer does) and only duplicates data. Item 1 fixes the same class of
bug for delete and explicitly leaves move/copy out.

Design: in `_prepare_move`, before the `is_dir` check, detect
`islink(os_src_path) or os.path.isjunction(os_src_path)`. For the rename branch
nothing changes. For the copy branch yield one task that recreates the link at
the destination (`os.symlink(readlink, dst, target_is_directory=...)`, or
`_winapi.CreateJunction` for a junction) and removes the source link, without
entering the target. If recreating a junction is considered out of scope,
refuse with `UnsupportedOperation` naming the link; refusing is still strictly
safer than today. `_prepare_copy` may keep following (documented behaviour).

Risk: low; the branch is only reached for cross-device moves of links, which
today destroy data. Native tests: junction and directory-symlink source moved to
another drive letter or a mocked `st_dev`, target contents retained, source link
removed or refused; ordinary directory move unchanged.

### 13. Replace an Existing Destination When Copying a Symlink (P3)

Owner: [CopyFile.__call__](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L364), symlink branch.

Evidence: after the user accepts the overwrite prompt, `os.symlink(readlink,
dst)` raises `FileExistsError` because the branch never removes the existing
destination; the regular-file branch overwrites through `open(dst, 'wb')`.
Additionally `target_is_directory` is not passed, so a dangling directory
symlink (the only way a directory link reaches this branch, since `is_dir`
follows live ones) is recreated as a file symlink on Windows.

Design: when `dst_existed`, remove the destination first (`os.remove`, falling
back to `os.rmdir` for a directory link); pass
`target_is_directory=os.path.isdir(src)` — for a dangling link use the source's
lstat mode. No change for the regular-file branch.

Risk: very low; only the symlink branch after an accepted overwrite.

### 14. QuickView Stays on "Loading folder" After a Failed Scan (P3)

Owner: [QuickViewSession](../src/main/python/fman/impl/quick_view.py#L418).

Evidence: `_location_changed` sets `_loading_location`; only `location_loaded`
clears it. The snapshot model emits `location_loaded` from `_commit`, which
never runs when the scan fails (`PermissionError`, vanished folder →
`location_disappeared`, or the navigation `onerror` fallback). Until the next
successful navigation the overlay ignores every cursor change.

Design: also clear `_loading_location` on `location_disappeared` and on
`snapshot_committed` (a commit implies the location is loaded), then call
`cursor_changed()`. Three connections, no new state.

Risk: very low; covered by a Qt test that fails the scan and asserts the
overlay leaves the loading state.

### 15. Inaccessible Folder on Refresh Raises the Crash Dialog (P3)

Owner: [ListingModel._receive](../src/main/python/fman/impl/model/listing.py#L319).

Evidence: a scan error with no active navigation request is routed to
`sys.excepthook` unless it is `FileNotFoundError`. A folder whose permissions
change while displayed, or a removable volume that is ejected, therefore shows
the application's exception dialog on the next mutation-driven rescan; the old
model reported the same condition through `location_disappeared`/status.

Design: treat `PermissionError` and `OSError` subclasses that mean "no longer
readable" (`ENOENT`, `EACCES`, `ENOTDIR`, Windows 2/3/5/21) like
`FileNotFoundError` — emit `location_disappeared` so the pane falls back to the
parent as it does today for deleted folders. Keep `excepthook` for genuinely
unexpected exceptions.

Risk: low; the change only reclassifies which UI a known OS error reaches.

### 16. Small Snapshot Hot-Path Trims (P3)

Owners: [reconcile](../src/main/python/fman/listing.py#L86),
[ListingModel.refresh_files](../src/main/python/fman/impl/model/listing.py#L487).

- The unchanged-rescan fast path builds a `{i: i}` dict over every known
  entry (~20 ms at 202k) that the view then uses only as `remap.get(entry)`.
  Returning a small identity-mapping object (`__getitem__`/`get` returning the
  key when the identity is known) or a `None` sentinel meaning "same order"
  removes the allocation. Keep the current dict for the changed case.
- `refresh_files` emits one `dataChanged` over the entire visible range; Qt
  clips it to the viewport, but delegates and proxies still receive a 202k-row
  range. Emitting only for rows in the visible viewport region (via the
  view's `indexAt`) is optional; at minimum restrict the columns to those whose
  `keys_depend_on_external_data` or text depends on external data (Size).

Risk: very low; equality tests on the projection/selection outcome.

### 17. Reap Search Children When Reader/Writer Thread Startup Fails (P2)

Owners: [SearchFiles Child](../src/main/resources/base/Plugins/SearchFiles/search_files/engine.py#L302),
[FindFiles Child](../src/main/resources/base/Plugins/FindFiles/find_files/engine.py#L278).

Evidence: both constructors spawn and register a subprocess before starting the
stderr-reader thread; SearchFiles may then start a stdin-writer thread. Injecting
`Thread.start()` failure left SearchFiles with one child in `runner.children`
and FindFiles with `runner.child` set; neither subprocess received `kill()`.
The constructors raise before their normal `finish()` cleanup is reachable.

Design: on reader or writer startup failure, kill and reap the subprocess,
join only threads that started successfully, close owned pipes and unregister
the child under the runner lock before re-raising the original exception.
Preserve normal process arguments, output/error collection and cancellation.

Risk: very low; only failed child initialization changes. Test first-reader and
second-writer startup failures independently and assert no registered/live child.

### 18. Roll Back Snapshot Job Capacity When Worker Startup Fails (P2)

Owner: [LatestJobs._start](../src/main/python/fman/impl/model/listing.py#L76).

Evidence: `_start` adds a cancellation token to `_active` and removes the pending
job before `Thread.start()`. An injected startup failure left one active token
with no worker. At capacity one, the next submission remained pending forever;
at capacity two, each failure permanently consumes a scan slot.

Design: if construction/start fails, remove the token, retire the unstarted job
exactly once using its existing cancellation callback, and re-raise. Keep the
rollback lock-safe and preserve latest-only replacement, capacity and delivery
semantics for successfully started workers.

Risk: low because this shared scheduler owns scans, refreshes and projections;
the failure branch is isolated, but tests must cover capacity one/two, callback
identity, retry, cancel and close to prevent double retirement.

### 19. Let Shell-Icon Loading Retry After Worker Startup Failure (P3)

Owner: [ListingIcons.icon](../src/main/python/fman/impl/model/listing_icons.py#L97).

Evidence: the method marks `_running = True` and queues the key before starting
its worker. Injecting `Thread.start()` failure left `_running` true with one
pending key and no thread. Later icon requests returned the generic fallback
without attempting another worker, so asynchronous shell icons stayed disabled
for that `ListingIcons` instance.

Design: on startup failure, restore `_running` and remove the just-queued item
before re-raising, allowing the next request to enqueue and retry normally.
Preserve queue bounds, cache behavior, Qt-thread delivery and close handling.

Risk: very low; only the startup exception path changes.

### 20. Clear Search Preference-Saver State When Worker Startup Fails (P3)

Owners: [SearchSession.changed](../src/main/resources/base/Plugins/SearchFiles/search_files/__init__.py#L103),
[FindSession.changed](../src/main/resources/base/Plugins/FindFiles/find_files/__init__.py#L110).

Evidence: each session sets `saving = True` and records pending settings before
calling `Thread.start()`. Injected startup failure left both `saving` flags true
and the pending snapshots unwritten. Every later change then assumes a saver is
already running and returns, disabling preference persistence for the session.

Design: if thread construction/start fails, reset `saving` under `save_lock`
before re-raising. Keep the latest pending snapshot available for the next real
change/save attempt; do not add retries, timers or synchronous disk I/O.

Risk: very low; successful coalescing and save behavior are unchanged. Test both
plug-ins, a later successful start and concurrent replacement of pending values.

### 21. Terminate 7-Zip When Its Output Reader Cannot Start (P2)

Owner: [_7zip.progress_records](../src/main/resources/base/Plugins/Core/core/fs/zip.py#L755).

Evidence: the subprocess already exists when the output-reader thread starts.
Injected `Thread.start()` failure escaped before the generator's cleanup block;
the surrounding `_7zip.__exit__` then called `wait()` without killing the child
or draining its pipe. A real 7-Zip process can block on a full output pipe and
make that wait unbounded.

Design: if the reader cannot start, kill and reap the owned subprocess before
re-raising. Preserve the original startup exception, normal progress parsing,
cancellation and warning handling; do not add a timeout to successful archives.

Risk: very low; only an archive operation whose required reader did not start is
terminated. A fake process/reader regression can prove kill-before-wait ordering.

### Findings Outside This Low-Risk Batch

- **P1: local-to-archive move can delete its source after a packing error.**
  [prepare_move](../src/main/resources/base/Plugins/Core/core/fs/zip.py#L161)
  returns packing and cleanup as independent tasks. Injecting an `OSError` in
  packing and choosing continue in real `MoveFiles` invoked the mocked source
  delete once. No real source was deleted. A composite move is necessary, but
  warning handling, cancellation during archive updates and verification must
  also be defined. Existing `AddToArchive(for_move=True)` supplies part of this
  machinery at additional hashing/extraction cost. Treat as a priority separate
  archive-safety design, not a casual one-line change. This task does not make
  local-to-archive moves safe.
- Atomic replacement of large copied files could retain an overwritten
  destination after failure, but changes free-space needs, ACL/link behavior,
  progress and partial-output policy. Excluded from this small-fix batch.
- Cross-device move cancellation, malformed individual session fields, callback
  mutation semantics, concurrent command contexts and plug-in unload recovery
  warrant separate investigation. No unverified fixes or blanket exception
  swallowing are proposed here.
- No broad optimization of search, archive enumeration, directory-size scanning
  or painting is justified by these probes. Their existing cancellation, limits
  and generation protections must remain intact.
- **Merge onto a mismatched type** ([FileTreeOperation._merge_directory](../src/main/resources/base/Plugins/Core/core/fileoperations.py#L109)):
  a source directory whose destination exists as a *file*, or a source file
  whose destination is a *directory*, is enqueued without an overwrite prompt
  and fails at task time (`FileExistsError` from `mkdir`, `PermissionError`
  from `open`). Behaviour is safe (nothing is destroyed) but the error surfaces
  late and per task. A prompt or an early refusal needs a UX decision; recorded,
  not batched.
- **Comparator identity on filesystems without inodes**
  ([validate_operands](../src/main/resources/base/Plugins/Core/core/comparator.py#L164)):
  `st_ino == 0` (FAT/exFAT, some cloud drives) is rejected as "cannot determine
  identity", making comparison impossible there. Falling back to normalized
  path equality is a small change but alters a documented refusal; flagged in
  the task's implementation review and left for the owner.
- **Failed shell-icon extraction is cached as the generic icon**
  ([ListingIcons._receive](../src/main/python/fman/impl/model/listing_icons.py#L140)):
  a transient failure (`SHGetFileInfoW` returning 0 while the shell is busy)
  stores `None` for that key until LRU eviction (256 keys). Cosmetic; a retry
  policy is not worth its complexity now.

## Alternatives

- Broad cleanup/refactoring: rejected because it increases regression surface
  without improving the evidenced behaviors.
- Put file guards only in commands: rejected because prepared/direct filesystem
  calls and merged descendants bypass top-level command validation.
- New persistence framework: rejected; a local atomic write follows an existing
  repository pattern without coupling independent settings owners.
- Add caches or workers for tiny hot-path changes: rejected; removing duplicated
  work and eager allocation preserves lifecycle behavior.
- Include the archive move redesign: deferred because its runtime/compatibility
  decisions exceed the user's near-zero-risk constraint.

## Runtime Effects

- Startup: no new background work. Settings root validation is constant-time;
  valid settings still require the existing read. No new dependencies/import-time
  scans or recurring signals.
- Steady state: resource hits avoid allocation; enabled status snapshots halve
  URL construction calls. Status aggregation adds only a Boolean; merge traversal
  adds a cancellation check per child. No additional long-lived memory.
- I/O: same-file copy detection adds fresh metadata checks before overwriting;
  junction classification adds bounded metadata checks during deletion. Atomic
  settings writes add one small sibling temp file and rename per flush.
- Threading/processes: no new workers or processes. Existing locks and worker
  budgets remain; failed starts no longer consume capacity, wedge service state
  or leave search/archive children running. Qt widgets/models stay on Qt thread.
- Cancellation: skipped merge entries become responsive between enumeration
  results. No guarantee of interrupting a blocked OS call. No new polling/timer.
- Disabled/no-op path: no status feature work is introduced while disabled;
  unused settings/transfer helpers start no job or scan. Cached resource hits
  retain identity without constructing replacement objects.

## Tests

Add regressions to existing test modules wherever possible. Do not create a
large generic review-test module or run the complete suite automatically.

| Items | Required Regressions | Existing Test Home |
| --- | --- | --- |
| 1-3 | Live/dangling/nested junction, target retained; ordinary/readonly delete; injected writable/permission/stat/retry errors emit no false notification; direct/prepared/merged hardlink and same-path copy preserve bytes; ordinary overwrite/new file and case-only rename unchanged | [Core local tests](../src/main/resources/base/Plugins/Core/core/tests/fs/test_local.py), [transfer tests](../src/main/resources/base/Plugins/Core/core/tests/test_fileoperations.py) |
| 4 | Existing JSON unchanged after serialization/write/close/replace failure; owned temp cleanup; successful round-trip; missing/malformed/nonobject root fallback; load never rewrites; linked file save refused without replacement; actual session/dialog consumers remain compatible | [test_util](../src/unittest/python/fman_unittest/test_util.py), [test_session](../src/unittest/python/fman_unittest/impl/test_session.py) |
| 5 | Normal/exceptional/nested override restores preceding getter; registry visibility/command exception propagation; next command sees actual cursor; no override remains a no-op | [test_ui_elements](../src/unittest/python/fman_unittest/test_ui_elements.py), [pane listener tests](../src/integrationtest/python/fman_integrationtest/plugin_tests/test_directory_pane_listener.py) |
| 6 | Cancel before first skipped child and between nested children; No-to-all, Abort and ordinary merge unchanged; no post-cancel transfer scheduled | [transfer tests](../src/main/resources/base/Plugins/Core/core/tests/test_fileoperations.py) |
| 7-8 | Construction/start failures release exactly once; normal delivery/work errors release; busy rejection unchanged; same-key resource identity and one constructor, distinct keys and concurrent lookups | [test_ui_elements](../src/unittest/python/fman_unittest/test_ui_elements.py) |
| 9 | Selected/unselected unreadable and vanished files; real zero sizes; supported/unsupported providers; partial/limited/empty/canceled totals and rendered incomplete label | [test_status_bar](../src/unittest/python/fman_unittest/impl/test_status_bar.py) |
| 10 | Empty/filtered/reordered/selected rows produce identical immutable entries; 10,000 visible rows construct 10,000 URLs; no feature work while disabled | [test_status_bar](../src/unittest/python/fman_unittest/impl/test_status_bar.py) |
| 11-13 | New-destination partial copy cleanup; existing destination retention; cross-device junction/directory-link move retains target or refuses; accepted symlink overwrite and dangling directory-link type | [Core local tests](../src/main/resources/base/Plugins/Core/core/tests/fs/test_local.py), [transfer tests](../src/main/resources/base/Plugins/Core/core/tests/test_fileoperations.py) |
| 14-16 | Failed/disappeared QuickView load recovers; inaccessible refresh uses expected fallback; unchanged/changed remap and refresh results stay equivalent without full-size avoidable work | [test_quick_view](../src/unittest/python/fman_unittest/test_quick_view.py), [test_listing](../src/unittest/python/fman_unittest/test_listing.py), [Qt integration tests](../src/integrationtest/python/fman_integrationtest/test_qt.py) |
| 17 | Reader and writer startup failures kill/reap, close pipes and unregister children; later searches start normally | [test_search_files](../src/unittest/python/fman_unittest/test_search_files.py), [test_find_files](../src/unittest/python/fman_unittest/test_find_files.py) |
| 18 | Capacity-one/two startup failures leave no active token; unstarted callback retires once; retry/cancel/close and successful delivery remain correct | [test_listing](../src/unittest/python/fman_unittest/test_listing.py) |
| 19 | Failed icon-worker start restores idle/queue state; next request starts and delivers; close and queue bounds unchanged | [Qt integration tests](../src/integrationtest/python/fman_integrationtest/test_qt.py) |
| 20 | Both preference savers clear `saving` after start failure, preserve the latest pending values and save after a later change | [test_search_files](../src/unittest/python/fman_unittest/test_search_files.py), [test_find_files](../src/unittest/python/fman_unittest/test_find_files.py) |
| 21 | Reader startup failure kills before waiting, preserves the startup exception and leaves normal/canceled progress behavior unchanged | [Core ZIP tests](../src/main/resources/base/Plugins/Core/core/tests/fs/test_zip.py) |

Run the single new failing test first, then its owning module immediately after
each implementation edit. The focused aggregate is:

```powershell
@'
import build, subprocess, sys
modules = ['core.tests.fs.test_local', 'core.tests.fs.test_zip', 'core.tests.test_fileoperations', 'fman_unittest.impl.test_status_bar', 'fman_unittest.impl.test_session', 'fman_unittest.test_find_files', 'fman_unittest.test_listing', 'fman_unittest.test_quick_view', 'fman_unittest.test_search_files', 'fman_unittest.test_ui_elements', 'fman_unittest.test_util']
environment = build._environment()
environment['QT_QPA_PLATFORM'] = 'offscreen'
sys.exit(subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'unittest', *modules, '-q'], env=environment, timeout=180).returncode)
'@ | python -
```

The listener/native widget gate is:

```powershell
@'
import build, os, subprocess, sys
modules = ['fman_integrationtest.plugin_tests.test_directory_pane_listener', 'fman_integrationtest.test_qt.MainWindowIT', 'fman_unittest.impl.test_status_bar.PaneStatusWidgetTest']
environment = build._environment()
environment['QT_QPA_PLATFORM'] = 'windows'
environment['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
sys.exit(subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'unittest', *modules, '-q'], env=environment, timeout=120).returncode)
'@ | python -
```

Also require source startup/shutdown using disposable UserSettings for settings
persistence. Add native junction removal tests using temporary siblings, never
a user directory, including failure without target metadata/permission changes.
Privilege-dependent symlink tests may skip explicitly; junction target retention
is mandatory on the supported Windows environment.

Manual acceptance on disposable files: delete a junction and inspect its target;
cancel a large all-skipped merge; test a locked-file delete error; restart and
check saved pane geometry/location and dialog preferences; toggle status off/on.
Performance checks are deterministic constructor/URL call counts. No full suite,
benchmark workload, freeze, package or remote release is required by this plan.

## Implementation Steps

1. Independently review the twenty-one proposed items and exclusions. Do not absorb the
   archive redesign or other deferred findings without separate scope approval.
2. Implement items 1-3 as separate local-file changes, each with its first failing
   regression and focused rerun. Complete native junction target-retention checks.
3. Implement item 4 and its injected-failure tests; validate actual session
   startup/shutdown using disposable settings before considering it complete.
4. Implement item 5 across both context managers in one coherent change; verify
   nested/exceptional cleanup and existing listener behavior.
5. Implement item 6 and test skipped/nested merge cancellation.
6. Implement items 7-8 in the existing UI utility owner, checking failure cleanup
   and allocation counts separately.
7. Implement items 9-10 with pure aggregation/call-count tests and native status
  widget checks. Preserve off-mode behavior.
8. Implement items 11-13 separately with failure cleanup and native link-target
  retention gates before changing transfer behavior.
9. Implement items 14-16 with focused model/QuickView tests and only the measured
  snapshot work reductions described above.
10. Implement items 17-21 owner by owner. Inject the first thread-start failure,
   prove cleanup/state rollback, then rerun the owning module before proceeding.
11. Run the focused aggregate and required native/manual gates, record exact
   commands/results and any remaining limitations. Update changelog only for
   qualifying implemented application changes. Add implementation provenance,
   then move this canonical document to Done and its index link to Completed.

## Acceptance Criteria

- Each selected issue has a regression that fails against its reviewed behavior
  and passes after its narrow fix; unrelated public behavior is unchanged.
- Junction targets, hardlink source contents and previously saved JSON survive
  the specified deletion/copy/save failure cases.
- Failed deletes are reported and never emit a successful removal notification.
- Exceptional/nested contexts restore the prior cursor getter, and failed
  thread starts leave both work slots reusable.
- Skipped merges check cancellation; unreadable sizes are not shown as complete.
- Resource construction occurs only on misses; status URL construction occurs
  once per visible row. No unmeasured end-to-end speedup claim is required.
- Failed worker starts leave no search/archive child, active scheduler token,
  stuck icon loader or stuck preference saver; a later attempt can proceed.
- Required focused/native tests pass; skips and deferred risks are explicit.
  Application implementation is not marked complete based on this review alone.

## Review Validation

- Existing focused aggregate above: **133 tests run, 128 passed, 5 skipped** in
  1.105 seconds. These are baseline tests, not proof that proposed fixes exist.
- Listener/native widget command above: **7 passed** in 0.580 seconds. This
  validates the current integration baseline, not future regression coverage.
- Disposable/mocked probes reproduced the initial ten selected issues. Junction tasks
  were enumerated but not executed; archive cleanup was mocked. Real direct and
  merged hardlink copies used only temporary files. No user files were modified.
- No editor diagnostics were reported. The static inventory parsed the recorded
  144 files successfully; this does not replace semantic or behavioral testing.
- Additional source reads covered the release-notes helper and performance
  launcher, outside that initial inventory count. No selected change affects
  those tools, release publication, generated documentation or packaging.
- Injected startup failures reproduced items 17-21 without launching a real
  search or archive executable: both search children remained registered and
  un-killed; snapshot capacity, icon loading and both preference savers stayed
  wedged; the archive path reached `wait()` without first killing its process.
- No full suite, real archive mutation, production startup, package/freeze,
  environment/package installation, remote workflow or release was performed.
- Review scope limitations: exhaustive execution, hostile concurrent path
  replacement, filesystem power-loss durability and third-party plug-in behavior
  were not validated. Manual/native implementation acceptance remains pending.

## Reviewers

### 2026_09_24 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Proposed ten small, evidence-backed fixes with owner-specific tests.
  Highlighted a separately reproduced local-to-archive source-loss risk but
  deferred its larger verification design. Baseline: 128 focused tests passed,
  5 skipped, and 7 listener/native tests passed. No application implementation
  authorized or performed in this pass.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Reviewed items 1–10 against the code; all ten owners, evidence and
  designs check out and stay within the low-risk constraint (item 4 is the
  broadest; its atomic-write design mirrors the existing `Config` writer).
  Added items 11–16 from a read of the local provider, transfer operations,
  snapshot model, QuickView and icon service: partial-copy cleanup on
  cancel/error (11); the cross-device move of a junction/directory symlink
  that empties the *target* because `_prepare_move` follows links (12, P1 —
  the move-side twin of item 1, which the batch explicitly left out);
  symlink copy over an accepted overwrite raising `FileExistsError` (13);
  QuickView stuck on "Loading folder" after a failed scan (14); inaccessible
  folder on rescan routed to the crash dialog instead of the disappeared path
  (15); two snapshot hot-path allocations (16). Recorded three further
  observations outside the batch (mismatched-type merge, comparator inode
  rule, cached icon failures). Items 12 and 15 are code-path findings, not
  executed reproductions; item 12 must be reproduced on a disposable second
  volume or a mocked `st_dev` before implementation. No application code
  changed.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context Window: 272K
- Outcome: Reviewed first-party runtime, bundled plug-ins and test/build tooling
  for additional none-to-low-risk findings. Added five injected and reproduced
  thread-start failure cases (17-21): leaked search children, stranded snapshot
  capacity, a wedged icon loader, disabled search preference saving and an
  archive reader failure that waits without draining output. Rejected unsupported
  candidates concerning hash completion, scandir cleanup, Favorites commits,
  build measurement, test teardown, hidden imports and deliberate blocking test
  fixtures. No application code changed.