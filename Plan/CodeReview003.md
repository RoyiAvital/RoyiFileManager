# Code Review 003: Low-Risk Safety and Performance

Status: Implemented hardening changes, 2026-09-25; release validation remains
pending. The user approved implementation of the consolidated proposal. The
implementation record below supersedes planning-only statements in the historical
inventory. This task remains in Plan because native/release gates are not all met.

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

Inventory: twenty-seven findings below, grouped by their existing owners. They
are not all approved as written; use the Release Proposal for their disposition.
The original batch needs no new dependency, setting, command, background service
or public API.
Preserve portable UserSettings paths, plug-in contracts, Qt thread ownership,
ordinary overwrite prompts, case-only rename behavior and disabled-feature cost.

Excluded from the original batch: redesigning snapshots, file-transfer transactions, archive verification,
plug-in lifecycles, shared command concurrency, search-engine redesigns,
packaging or release policy. The release proposal recommends separately approved
work on destructive transfer risks; exclusion from this batch is not acceptance
of those risks for a wide-use release. No README, changelog, application or test
edits in this planning pass.

## Implementation Record (2026_09_25)

### Delivered and Deferred

- Implemented items 1-12, 15, 17-25, the listing-error half of 26, and 27.
  Item 11 uses owned staging rather than deleting a possibly pre-existing output.
  Item 12 guards command merges and provider fallback; unsafe link moves refuse.
- Item 14 needed no QuickView signal change: existing empty/disappeared coverage
  and new native permission/not-directory/device-not-ready refresh cases pass
  through the corrected model fallback. Unexpected errors remain reportable.
- Item 13 remains deliberately refused rather than unlinking an old destination.
  Item 16's first optimization already existed; viewport-only invalidation and
  blanket case folding from 26 remain deferred. No snapshot/search redesign.
- Local-to-archive Move now refuses before gathering mutation tasks and at the
  provider API. Copy and existing verified archive-out/archive-to-archive moves
  remain available. Both source and archive retention are regression-tested.
- Regular local copies stage to an exclusively created sibling file. Existing
  Windows destinations must be regular, writable and not known-multiply-linked.
  Missing identity uses the existing resolved-path alias fallback; zero link
  counts are accepted as unknown. See the follow-up limitations below.
  The destination DACL is applied before writing staging data. Publication uses
  `ReplaceFileW` without ignore-ACL flags, with a backup in an owned sibling
  `.fb-*` directory. Partial failure restores the original name or
  retains the backup and reports its recovery path. Successful publication removes
  the old backup when possible. This addresses documented errors 1176/1177;
  `ReplaceFileW` without backup was rejected after checking its failure contract.
  Native tests cover protected DACLs and existing named streams. Source named
  streams are not copied; Windows can normalize inherited ACL flags. Non-Windows
  overwrites refuse rather than silently weakening metadata guarantees.
- Temporary pane targets are thread-local, with nested exception-safe restoration.
  A barrier test forces simultaneous commands and verifies separate targets.
- Go To no longer runs background existence pruning; bounded popularity shrinking
  and explicit invalid-suggestion handling remain. No UNC/mapped-drive probes added.
- Natural sort uses fixed-width encoding for common numeric runs and a general
  length encoding for larger runs, with Unicode decimal normalization. Snapshot
  and legacy column methods share the key; the old exact `%06d` golden now checks
  ordering, ties and API parity. No benchmark repetitions were reduced.
- Documentation and changelog describe the new refusal/recovery workflows. No
  dependency, environment, public method signature, build or packaging change.

### Runtime and Failure Costs

Ordinary new-file copies retain bounded 1 MiB buffers and add sibling-file creation
and final rename; overwrites also read identity/DACL information and manage a
backup directory. A complete new file's free space is required alongside existing
data. Cancellation is checked between chunks and before publication, not inside
the short native replacement call. Original-copy errors are not masked by cleanup
failure. Recovery files may remain after a crash or unsuccessful cleanup.

Thread-local context has no recurring work. Startup rollback introduces no retry
timer or new worker; successful worker ownership is unchanged. Settings serialize
before disk mutation, write a unique sibling file, close it, then replace the live
JSON; non-object roots reset to defaults and linked settings refuse writes. No
power-loss durability or hostile concurrent path-substitution guarantee is made.
Resource/status/sort-write optimizations remove measured work; disabled features
retain their existing no-op paths.

### Implementation Validation

Use the existing application interpreter; no environment creation or installation.
The final combined command was this Python script piped to that interpreter:

```python
import build
import os
import subprocess
import sys
environment = build._environment()
environment['QT_QPA_PLATFORM'] = 'offscreen'
environment['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
modules = [
    'core.tests.fs.test_local', 'core.tests.fs.test_zip', 'core.tests.test_fileoperations',
    'core.tests.fs.test_columns', 'core.tests.commands.test___init__', 'core.tests.commands.test_goto',
    'fman_unittest.impl.test_session', 'fman_unittest.impl.test_command_context',
    'fman_unittest.test_listing', 'fman_unittest.test_ui_elements', 'fman_unittest.impl.test_status_bar',
    'fman_unittest.test_search_files', 'fman_unittest.test_find_files',
    'fman_unittest.impl.plugins.test_json_encoding', 'fman_unittest.impl.plugins.test_plugin',
    'fman_unittest.impl.test_shortcuts', 'fman_integrationtest.impl.plugins.test_config',
    'fman_integrationtest.test_qt.QuickViewImagesIT', 'fman_integrationtest.test_qt.SnapshotFilterBarIT',
    'fman_integrationtest.test_qt.SortedFileSystemModelIT', 'fman_integrationtest.test_qt.ArchiveTransferIT',
    'fman_integrationtest.test_qt.FindFilesIT', 'fman_integrationtest.test_qt.SearchFilesIT',
    'fman_integrationtest.test_qt.PublicUiIT',
]
sys.exit(subprocess.run([sys.executable, '-m', 'unittest', *modules],
    env=environment, timeout=180).returncode)
```

- Final combined result: **607 tests, 599 passed, 8 symlink-privilege skips**.
  Native filesystem/ACL/junction tests still execute on Windows with offscreen Qt.
  The duplicate-ZIP-entry fixture warning and offscreen window-manager warnings
  are expected; no assertion was weakened or skipped to suppress them.
- Earlier native Qt aggregate: **560 tests, 551 passed, 8 skips, 1 failure**.
  `SearchFilesIT.test_root_follows_invoking_pane_and_fields_align` reports a label
  width of 85 versus required 125 pixels. The same test failed identically with
  all changed production modules loaded from `HEAD` in memory; no files were
  reverted. This existing native layout failure is not fixed by this task.
- Native focused recovery command: `python -m unittest
  fman_integrationtest.test_qt.QuickViewImagesIT.test_quickview_unreadable_refresh_finishes_parent_recovery
  fman_integrationtest.test_qt.QuickViewImagesIT.test_empty_and_disappeared_locations_finish_loading
  fman_integrationtest.test_qt.SnapshotFilterBarIT.test_failed_scan_preserves_displayed_pane`
  with `build._environment()` and `QT_QPA_PLATFORM=windows`: **3 passed**.
- Final transfer command: `python -m unittest core.tests.fs.test_local
  core.tests.test_fileoperations`, through `build._environment()`: **110 tests,
  104 passed, 6 privilege skips**. Includes real merged hardlinks/junctions,
  same-volume link rename, forced copy fallback refusal, failed/canceled copies,
  competing destination creation, protected staging/final DACLs, named streams,
  and injected partial Windows publication failure with retained recovery data.
- Tooling command: `python -m unittest
  src/performancetest/python/fman_performancetest/test_filter_find_benchmark.py`,
  through `build._environment()`: **43 passed**. The only unique ordinary-suite
  test was moved unchanged before deleting that duplicate module.
- Narrow natural-key A/B: 20,000 names `report_%06d_part_%d.txt`, second numeric
  value `index % 97`; `timeit.repeat(number=1, repeat=9)`, median milliseconds,
  with equal existing-range ordering. Original `%06d`: **19.139 ms**; final key:
  **16.590 ms**. An earlier general-only candidate was slower (17.908 versus
  19.443 ms), so the common-number path was added and all ordering checks rerun.
  These are warm in-process key timings, not whole-app or release performance.
- Editor diagnostics on touched Python files: no errors. Focused tests ran
  immediately after each change; initial reproductions failed before fixes.

### Open Release Gates

No full `python build.py test`, source restart smoke, portable build or
clean-machine artifact validation was run. A later user-requested performance
catalog completed before these review fixes, as recorded below. No automatic
elevation or dependency installation was performed. Required
remaining checks include a real second-volume transfer, executing privilege-skipped
symlink cases, live unavailable/network/removable storage, storage-failure/crash
recovery, and full candidate performance/persistence/packaging validation. Native
layout failure and independent review of the broader staged-overwrite policy remain
open. The implementation is not a wide-use release approval; keep this task pending.

### Implementation Review Follow-Up (2026_09_25)

Disposition of the seven remarks in Claude Fable 5.1's implementation review:

1. **Fixed, native reproduction.** Read-only source overwrite failed with
  WinError 5 before the fix. Staging is made writable for `ReplaceFileW`, then
  the captured source mode is restored on the published destination. Failure
  after publication explicitly says the content was published, emits the changed
  notification, and raises so a copy-based move cannot proceed to source deletion.
  New-file read-only copies, timestamps and cleanup remain covered.
2. **Fixed, simulated missing identity.** Only use `samestat` when both source
  and destination supply device/inode identity; otherwise compare freshly resolved
  paths. Known hardlinks (`st_nlink > 1`) still refuse. Zero identity and link
  count no longer make unrelated files aliases or prohibit ordinary overwrites.
  This fallback cannot prove distinctness for every alias on a provider that
  withholds identity. No live Google Drive or SMB compatibility claim is made.
3. **Fixed.** Settings accepts an unknown zero link count; symlink, junction and
  known-hardlink refusals remain. Round-trip and retained hardlink data are tested.
4. **Deferred for per-file cost.** After discussing transfer performance with the
  user, removed the attempted hidden-staging implementation and its tests.
  Temporary entries can remain visible during rescans. No hide/unhide attribute
  reads/writes or extra staging `stat` are added to every ordinary copy.
5. **Policy retained, error clarified.** Local-to-archive Move, non-Windows
  overwrite and known-hardlinked-destination overwrite remain refused. Symlink
  overwrite now reports `Symlink overwrite refused; destination retained` before
  attempting creation. A separate link-policy design is requested; no such
  policy is implemented by this follow-up.
6. **Fixed.** Publication compares `(st_ino, st_dev, st_size, st_mtime_ns)` and
  retains regular-file, writable and known-hardlink guards. Access-only changes
  are accepted. A native 1,000 ns modification-time regression demonstrated that
  the old tuple equality also missed sub-second changes; it now refuses them.
7. **Accepted trade-off.** Keep bounded Go To history without background
  existence probes. No additional pruning or recurring work.

Runtime impact is confined to operations/saves, not pane scanning or rendering.
Ordinary identified writable copies use the existing metadata reads; two mode
changes apply only to read-only overwrites. Path resolution runs only when file
identity is unavailable. The bounded copy loop, worker count and cancellation
checks are unchanged. Fault-injected mode failure tests exercise the new error
branch; they do not add checks to normal execution. No transfer timing speedup is
claimed from call-count tests.

### Review Follow-Up Validation

Run through the existing interpreter with `build._environment()`:

```python
import build
import os
import subprocess
import sys
environment = build._environment()
environment['QT_QPA_PLATFORM'] = 'offscreen'
environment['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
modules = ['core.tests.fs.test_local', 'core.tests.test_fileoperations',
   'core.tests.fs.test_zip', 'fman_unittest.impl.test_session',
   'fman_integrationtest.test_qt.ArchiveTransferIT']
sys.exit(subprocess.run([sys.executable, '-m', 'unittest', *modules],
   env=environment, timeout=180).returncode)
```

- **230 tests: 222 passed, 8 symlink-privilege skips.** Includes native copy,
  ACL/stream/recovery, directory merge and archive workflows. Expected duplicate
  ZIP fixture warning only. Earlier focused regressions reproduced before fixes.
- The copy metadata-call regression rejects added staging `stat` or Windows
  attribute calls on ordinary new-file and overwrite copies. Read-only final-mode
  failure is injected; missing identity/link counts are simulated on native files.
- Editor diagnostics on the four touched Python files: no errors. No full suite,
  packaging, performance rerun or environment changes in this follow-up.
- Earlier full performance run `05fe923d-6caf-4a70-a5b7-7df15278e215` completed
  all 11 workloads with three repetitions. It predates these operation-only fixes;
  it is not a before/after transfer measurement or a compatible historical delta.
- Existing native UI layout failure, privilege and live-storage/release gates
  remain open. Reviewer history below is preserved; no release approval implied.

### Latest Implementation Review Follow-Up (2026_09_25)

All seven remarks from Claude Opus 5.5's implementation review are addressed:

1. **Fixed.** `LatestJobs._run` delivers a queued worker-start error once, without
  also calling cancellation retirement. The new regression failed before the
  fix for both constructor and `start()` failures; it now verifies one delivery,
  no cancellation callback, released capacity and callback execution outside the
  lock. All 44 listing tests passed.
2. **Fixed.** Comparator captures the invoking pane's effective cursor on the
  command thread and passes it to the Qt snapshot. Other-pane reads and mark
  precedence remain unchanged. Real Qt tests cover both invoking panes, selected
  files overriding the cursor and restoration of the ordinary cursor.
  [PlugIn.md](../PlugIn.md) documents that overrides are command-thread-local.
3. **Fixed.** Cross-format archive Move has a distinct same-format-required
  refusal, not the local-file warning. Tests assert no 7-Zip call and unchanged
  source/destination bytes for ZIP-to-7z/tar attempts. Archive usage and README
  now say that cross-archive Move requires the same format; no new move support.
4. **Hardened; native configuration gate remains.** Copy staging uses `.fc-*`
  (12-character basename), recovery uses `.fb-*/o` (14-character suffix), and
  private Windows staging paths use extended syntax with correct UNC handling.
  This is string conversion only: no new attributes/stat calls or Registry
  writes. A native 259-character destination succeeds for creation and overwrite
  while a test adapter enforces legacy limits on unprefixed staging names.
  Existing ACL/stream and partial-replacement recovery tests still pass. The
  machine's long-path setting was not changed; an actual disabled-setting host
  run is not claimed. The change does not promise general long-path support.
5. **Suggestion adopted as documentation and coverage.** Keep Copy and Move's
  shared source/destination directory-link merge refusal. Expanded direct and
  native nested-junction tests to both commands. Usage docs and
  [Link Operation Policy](LinkOperationPolicy.md) explicitly record this
  tightening; the broader link policy remains unimplemented.
6. **Fixed.** Both session-save call sites use one failure-reporting helper.
  Failed saves report once per SessionManager through the existing application
  error handler, including on close. Ordinary logs are suppressed in the frozen
  app and a closing-window status message could disappear, so this uses the
  existing user-visible error path instead. A native hardlink fixture verifies
  repeated saves report once without replacing linked settings. No startup
  probe, retry job or change to Settings' link refusal.
7. **Removed.** Deleted the unused `_remove_nonexistent` helper and its exclusive
  `shuffle`/`time` imports. Existing bounded-history, offline-history and location
  suggestion tests pass; selected-location validation remains unchanged.

Runtime effects: no new pane scans or idle/background work. Comparator captures
one invoking cursor value before Qt dispatch; staging adds only path-string work;
session failure deduplication adds one boolean. Queued-start reporting does less
work. No benchmark method, repetition count or saved performance record changed.

### Latest Review Validation

Run through the existing interpreter from the repository root:

```python
import build
import os
import subprocess
import sys
environment = build._environment()
environment.update(QT_QPA_PLATFORM='offscreen',
  QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))
modules = ['fman_unittest.test_listing', 'fman_unittest.impl.test_session',
  'fman_unittest.impl.test_command_context', 'core.tests.test_comparator',
  'core.tests.commands.test_goto', 'core.tests.fs.test_local',
  'core.tests.fs.test_zip', 'core.tests.test_fileoperations',
  'fman_integrationtest.test_qt.ComparatorIT',
  'fman_integrationtest.test_qt.ArchiveTransferIT']
sys.exit(subprocess.run([sys.executable, '-m', 'unittest', *modules],
  env=environment, timeout=240).returncode)
```

- **324 tests in 104.262 s: 315 passed, 9 privilege-related skips.** Expected
  duplicate ZIP fixture and offscreen Qt size-hint warnings only.
- Immediate focused gates passed after each change: listing 44; comparator
  unit/Qt 29 (one skip); archive refusal 2; local filesystem 49 (four skips);
  session 11; Go To 15; Copy/Move merge/error 7.
- Changed Python files have no editor diagnostics. Documentation validation checks
  required sections, local task links, pending indexes and changed-line whitespace.
- No full suite, performance rerun, build/packaging, dependency installation,
  Registry change or source restart smoke. Existing release gates remain open,
  including a real long-paths-disabled host and live UNC/second-volume tests.
  This is author validation, not independent release approval; keep the task pending.

### Footer Coverage Review Follow-Up (2026_09_25)

The latest review identified one coverage issue: the documentation-footer
assertion was commented out. The user confirmed this was intentional so footer
wording could change freely. Do not restore an exact-sentence assertion.

The existing `DocumentationNamingTest` now checks that the footer is text and
contains the configured test application name. This tests the dynamic-name
contract without pinning editorial copy. The documentation hook and current
footer wording are unchanged. No changelog entry is needed for this test-only fix.

The review's other observations confirm the prior implementation and retain the
existing privilege, full-suite, packaging, clean-machine, second-volume,
live-storage and long-path-disabled release gates. None is claimed completed by
this follow-up; the task remains pending.

Focused validation, using the existing application interpreter:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_app_name.DocumentationNamingTest'], env=build._environment(), timeout=60).returncode)"
```

Result: **1 test passed**, including metadata, token substitution and invalid-name
checks; no editor diagnostics. No broad application, performance or packaging
checks were rerun. An exact-footer mutation check was canceled and not run;
exact wording is not an acceptance condition under the clarified requirement.

## Release Proposal (2026_09_25)

### Recommendation

Prioritize preservation of source data, existing destinations and settings over
micro-optimizations. Implement small owner-specific changes with a failing
regression first. Do not apply all twenty-seven designs mechanically: several
need correction, one optimization already exists, and the archive source-loss
finding cannot be left enabled merely because it is outside the original batch.

The table dispositions and corrections below supersede conflicting implementation
advice in the original inventory. Original findings and all reviewer records are
retained for provenance, not treated as verified fixes.

### Disposition of Every Item

| Item | Recommended Disposition | Release Reason / Constraint |
| --- | --- | --- |
| 1 | Required safety fix | Remove junctions themselves; never traverse or change target permissions. |
| 2 | Required safety fix | Fresh leaf-level same-file/hardlink checks before truncation; unknown identity is not proof of distinct files. |
| 3 | Required safety fix | Propagate failed deletes and suppress false success notifications. |
| 4 | Required safety fix | Atomic settings publication, object-root validation and linked-file refusal, with failure injection. |
| 5 | Required safety fix | Restore prior command context on exceptions/nesting; concurrent overrides remain a distinct safety gate. |
| 6 | Implement | Make skipped merges cancellable between children. |
| 7 | Implement | Release UI worker capacity on construction/start failure. |
| 8 | Implement, after safety | Avoid resource construction on cache hits; prove constructor counts. |
| 9 | Implement | Display unreadable totals as incomplete, retaining correct selected totals. |
| 10 | Implement, after safety | Construct each status URL once; preserve the disabled path. |
| 11 | Revise, then implement | Prove ownership before deleting partial output; a pre-copy existence check is insufficient. |
| 12 | Required safety fix, revised | Guard both provider recursion and command-layer merges. Refuse unsafe link moves rather than invent junction recreation now. |
| 13 | Defer overwrite convenience | Never unlink an existing destination before replacement is known to succeed. Existing refusal is safer than the proposed fix. |
| 14 | Reproduce before changing | Existing disappeared-folder coverage already exists; the proposed signal is not exposed by the pane model facade. |
| 15 | Implement with 14's recovery tests | Handle classified filesystem access failures through bounded fallback/status, not the crash dialog. |
| 16 | Drop first bullet; defer second | Unchanged-identity sentinel already exists. Viewport-only model notifications have no demonstrated benefit or correctness proof. |
| 17 | Implement | Reap and unregister search children if required reader/writer startup fails. |
| 18 | Implement | Roll back snapshot worker capacity and retire jobs once, without callbacks under the scheduler lock. |
| 19 | Implement | Restore icon-worker state so later requests can retry. |
| 20 | Implement | Restore preference-saver state while preserving the latest pending values. |
| 21 | Required archive liveness fix | Kill/reap before waiting if the archive reader cannot start. |
| 22 | Implement | Read UTF-8/BOM settings correctly; fallback only on decoding failure, not malformed JSON. |
| 23 | Implement, after safety | Avoid unchanged sort-setting saves; prove identical persisted results and zero no-op writes. |
| 24 | Revise, then implement if validated | Fix numeric ordering without breaking Unicode numeric equivalence, long runs or text/punctuation ordering. |
| 25 | Revise, then implement | Preserve inaccessible/offline history; UNC checks alone miss mapped drives and `isdir(False)` does not prove deletion. |
| 26 | Split | Handle listing failures before mutating selections; defer blanket Windows case folding until actual directory case semantics are specified. |
| 27 | Implement on approval | Preserve the product-name regression in opt-in tooling tests, then remove the duplicate normal-suite module. |

### Required Safety Design Corrections

1. **Archive source retention is a release blocker.** Local-to-archive
   `prepare_move` still returns packing and source deletion as independent tasks.
   Approve a separate change that couples successful, verified packing to source
   deletion and covers warnings, cancellation, changed sources and Continue after
   error. Existing `AddToArchive(for_move=True)` is a reuse candidate, not proof
   the whole move is safe. If that change cannot pass its gates, refuse this move
   direction before mutation and direct users to copy plus explicit verification;
   do not silently turn Move into Copy. Keep existing archive contents in scope
   when testing failed updates.
2. **Link moves must be checked before either traversal layer.**
   `FileTreeOperation._merge_directory` follows directory links before invoking
   the provider. Guard selected and nested source links, and destination link
   redirections, before merge recursion as well as `_prepare_move`. Include
   same-volume merges, not only cross-device moves. Retain safe standalone rename;
   refuse unsupported fallback/merge cases before changing source or target. A
   private `_winapi.CreateJunction` dependency is not needed for the release fix.
3. **Partial-output cleanup must prove ownership.** `dst_existed == False` can
   also mean a dangling link or a destination created concurrently. Track actual
   successful exclusive creation, distinguish create-new from approved overwrite,
   and close handles before cleanup. Preserve the original copy/cancel exception
   if cleanup fails; do not delete a path merely because opening it failed.
   Concurrent path replacement is not solved by an existence check.
4. **Failed overwrite preservation needs its own decision.** Current `open(dst,
   'wb')` destroys old content before copy success. Item 11 cannot restore it,
   and item 13's remove-then-create would add another destructive failure window.
   Recommend separately reviewed staged publication for supported ordinary-file
   overwrites, or explicit refusal of unsupported cases. Define free-space,
   ACL/streams/link semantics and cancellation first; never silently change those
   contracts with a blanket `os.replace`. This is broader than a low-risk cleanup
   and is not authorized by this proposal alone.
5. **Command context remains a safety boundary.** Item 5 fixes exceptions and
   nesting, not shared mutable overrides between concurrent commands. Force an
   interleaving in a test before release. If one command can act on another's
   temporary target, block release until a separately reviewed capture/ownership
   fix or safe refusal prevents it. Do not claim finally-blocks solve concurrency.

### Edge-Case and Performance Corrections

- **14-15:** the facade already handles the inner model's
  `location_disappeared`; adding that signal connection directly to the facade
  would fail. Extend the existing empty/disappeared QuickView regression to
  permission failures, failed refresh, removed volumes and recovery to a readable
  parent/root. Clear loading only for the current request's terminal outcome;
  an unrelated sort/filter snapshot commit is not necessarily navigation success.
- **16:** a single full-range `dataChanged` signal does not prove 200,000 rows are
  repainted. The model clears cached text, and a sorting dependency flag does not
  describe every column's display dependencies. Keep invalidation correct for
  offscreen rows and plug-ins; defer narrowing until profiling justifies it.
- **17-21:** successful workers retain their current ownership. Cleanup must
  preserve the original failure, join only started threads, reap children and
  avoid double release/retirement. Scheduler callbacks must run outside locks.
- **24:** the proposed `%02d` length prefix fails for 100-digit runs, and ASCII
  `lstrip('0')` changes Unicode-decimal/leading-zero equivalence. An in-memory
  probe reproduced both problems. Specify a numerically canonical key and test
  complete ordering, ties and descending behavior before adopting it; do not
  claim only seven-plus-digit names can be affected by a new key encoding.
- **25:** mapped network drives can block just like UNC paths, and permission
  failures must not erase history. Lowest-risk release choice: stop background
  filesystem-existence pruning, retain the bounded popularity shrink and explicit
  invalid-suggestion handling. This trades stale suggestions for preserved history
  and no new network probes. A narrower fixed-local-drive policy can be reviewed
  later; the current 10 ms budget cannot interrupt one blocked OS call.
- **26:** Windows directories may be case-sensitive; `file://` can also refer to
  UNC/mapped storage. OS-wide `normcase` is not an adequate filesystem policy.
  Read both listings successfully before changing either selection. Keep current
  comparison semantics until case-sensitive, insensitive and unknown cases have
  an explicit, tested rule.
- **Other exclusions:** retain safe comparator refusal when identity is unknown;
  do not weaken it to path-string equality. Defer cosmetic icon retry, speculative
  callback/unload changes and the unused clipboard string cleanup. Mismatched-type
  merges should refuse clearly without mutation; prompt redesign is unnecessary.
  The six rejected candidates remain rejected. No snapshot/search rewrite.

### Proposed Delivery Order

1. **Safety:** items 1-3, 12, 4-5; approve archive-move containment/fix and the
   overwrite policy separately. Exercise real command merges, not just leaf tasks.
   Add item 11 only with proven output ownership; do not implement item 13 as written.
2. **Failure recovery:** 6-7, 9, 17-22, 15 with a distinct repro for 14, 25 and
   the error-handling half of 26. Keep each owner as an independently tested change.
3. **Small measurable savings:** 8, 10, 23; then the corrected sorting behavior
   (24) and test-discovery maintenance (27). Do not delay safety fixes for these.
4. **Release validation and freeze:** stop adding optimizations, validate the
   actual portable candidate and approve only with explicit results and limitations.

### Wide-Use Release Gates

- A fail-before/pass-after regression for every implemented finding. Native
  temporary-file tests for direct, prepared, nested and merged operations: same
  path, hardlinks, live/dangling links, junctions, readonly/locked destinations,
  disk-full/write/close/replace failures, cancellation and Continue/No-to-all.
  Assert source bytes, pre-existing destination bytes and unrelated link targets,
  not only raised exceptions or notifications. Test refusal paths as well.
- Symlink privilege skips are acceptable for routine local runs, but the release
  needs at least one recorded Windows run where those safety cases execute.
  Include a real cross-volume check, not only mocked device IDs; no automatic
  privilege elevation or modification of user data/settings.
- Source startup/shutdown and restart with disposable UserSettings; failed and
  malformed settings saves, Unicode paths/configuration, navigation failure and
  search/archive cancellation. Confirm threads/processes do not remain orphaned.
- After fixes, request an explicit full `python build.py test` run and authorized
  portable build/smoke on a clean supported Windows machine without developer
  PATH/Qt. A focused green subset is not final release evidence. Validate the
  delivered artifact, non-ASCII paths, normal unelevated operation and upgrade
  with an existing UserSettings copy. These commands are proposed, not run here.
- Use deterministic counts for 8/10/23. Run the existing demand-only performance
  suite before/after with matching workloads/settings and unchanged repetitions,
  retaining statistical results. Report main-thread latency, startup/navigation,
  transfer throughput and peak memory; do not equate micro-checks with whole-app
  speedups. Investigate regressions rather than reducing repetitions or thresholds.
- Release only when known reproducible source-loss paths are fixed or unavailable,
  overwrite/failure guarantees are explicitly approved, required safety tests pass,
  and remaining non-blocking limitations are documented. No safety claim against
  power loss or hostile concurrent filesystem substitution without separate work.

### Proposal Evidence and Limits

This pass read all four review records and all twenty-seven findings, then
rechecked local copy/move/delete, command merge traversal, archive preparation,
settings, snapshot/QuickView recovery, sort persistence and directory comparison.
The natural-sort probe used the current `Name.keys` and an in-memory implementation
of the proposed key: it confirmed the reported seven-digit bug and falsified the
proposed key's Unicode/long-number compatibility. The duplicate report-test copy
and existing QuickView recovery test were confirmed in current source.

Earlier reviewers' runtime probes remain attributed to those reviews. This pass
did not repeat destructive-operation probes, run test suites/benchmarks, build,
install dependencies or change application code. Release readiness is not yet
established. Only this existing task document is revised.

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
  **Correction (2026_09_25 review):** already implemented. `reconcile` returns
  `None` when names, identities and creation times are unchanged and every
  identity is nonzero; the dict is built only when some identity is unknown
  (zero). Drop this bullet unless the mixed-zero-identity case is measured.
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

### 22. Read Hand-Edited JSON Configuration as UTF-8 (P2)

Owners: [config.load_json](../src/main/python/fman/impl/plugins/config.py#L98),
[Plugin._configure_component_from_json](../src/main/python/fman/impl/plugins/plugin.py#L236)
and [collect_shortcuts](../src/main/python/fman/impl/shortcuts.py#L15).

Evidence: all three readers call `open(path, 'r')` without an encoding. The
application runs Python 3.14 without UTF-8 mode, so the locale code page
(`cp1252` here) is used. A UTF-8 `Core Settings (Windows).json` containing
`C:\Users\Rój\wt.exe` loaded as `C:\Users\RÃ³j\wt.exe`; a file saved as
"UTF-8 with BOM" raised `JSONDecodeError` in `load_json` and is silently
skipped by the F1 shortcut list. The documentation tells users to hand-create
settings, key bindings and context menus, so non-ASCII paths and captions reach
these readers. Files the application writes are unaffected: `json.dump` emits
ASCII escapes.

Design: open with `encoding='utf-8-sig'`; on `UnicodeDecodeError`, retry once
with the previous locale encoding so existing ANSI files stay readable. Keep
writers, merge rules and error reporting unchanged.

Risk: very low; ASCII and application-written files decode identically. Tests:
UTF-8, UTF-8 with BOM, legacy ANSI and malformed files through `load_json`, key
bindings/context menus and `collect_shortcuts`.

### 23. Skip Unchanged Sort-Settings Saves on Every Navigation (P3)

Owner: [RememberSortSettings._remember_curr_sort_column](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L2035).

Evidence (code path; not timed): `before_location_change` calls `save_json('Sort
Settings.json')` on every location change, even when the sort did not change.
`Config.save_json` then runs `get_differential_json`, which re-reads every layer
from disk (two filenames per plug-in directory plus the user file) before
deciding nothing needs writing. `Sort Settings.json` grows with every folder
whose sort was ever changed, and the work runs on the navigating thread.

Design: compute the new record first; return without saving when the entry is
already absent for the default sort, or already equal to the new record.
Otherwise mutate and save exactly as today.

Risk: very low; persisted content is identical. Test: repeated navigation with
an unchanged sort makes no `save_json` call; changing or resetting the sort still
saves once.

### 24. Natural Name Sort Misorders Numbers With Seven or More Digits (P3)

Owner: [core.Name.keys and get_sort_value](../src/main/resources/base/Plugins/Core/core/__init__.py#L31).

Evidence: digit runs are padded with `'%06d' % int(part)` and compared as
strings. Sorting `frame_2`, `frame_999999`, `frame_1000000`, `frame_1000001`
gave `frame_2, frame_1000000, frame_1000001, frame_999999`. Frame sequences and
large datasets exceed six digits.

Design: replace the padding with a length-prefixed canonical number, for
example `n = part.lstrip('0') or '0'` and `'%02d%s' % (len(n), n)`, in both
`keys` and the legacy `get_sort_value`. Numbers up to six digits keep their
relative order, equal values with different leading zeros still tie, and a digit
run still compares to adjacent text as before because both forms start with a
digit. Keys become shorter for short numbers.

Risk: very low; only runs of seven or more digits change position. Tests: mixed
lengths, leading zeros, digits next to letters and punctuation, descending sort.
Update any test that asserts exact key strings to assert order instead.

### 25. Keep Go To History for Temporarily Unavailable Volumes (P3)

Owner: [_remove_nonexistent](../src/main/resources/base/Plugins/Core/core/commands/goto.py#L179).

Evidence: after each navigation, `GoToListener` checks random visited paths with
`os.path.isdir` and removes those that return `False`, including all children.
`os.path.isdir('Z:\\Photos\\2024')` on an unmapped drive returned `False`
without an error, so entries on an unplugged USB drive, a disconnected mapped
drive or an unreachable UNC share are gradually deleted from Go To suggestions.
An unreachable UNC path can also block the listener thread for the SMB timeout,
despite the 10 ms budget, because the budget is checked only between calls.

Design: skip UNC paths in this background pruning, and remove a local path only
when its drive root exists. Keep the explicit removal when a user selects a
nonexistent suggestion, the 500/250 shrink rule and the time budget.

Risk: very low; unavailable locations stay suggested until they are chosen and
found missing, as with any other stale entry. Test with a mocked absent drive
root and a UNC path; existing-drive removal unchanged.

### 26. Compare Directories Counts Case-Only Differences on Windows (P3)

Owner: [CompareDirectories._select_nonexistent_in_other](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L2331).

Evidence (code path): names from both panes are compared as exact strings. For
two local Windows folders containing `Report.txt` and `report.txt`, each side
reports and selects the other's file as missing, although a copy between them
would overwrite it. An `OSError` from either `iterdir` (vanished or inaccessible
folder) propagates to the generic command error handler.

Design: when both panes are `file://` on Windows, compare `os.path.normcase`
keys and select the original names; keep exact comparison for other schemes.
Catch `OSError` from listing and show an alert naming the folder.

Risk: very low; only case-only pairs stop being reported. Test in
[test_comparator](../src/main/resources/base/Plugins/Core/core/tests/test_comparator.py),
which already exercises this command.

### 27. Remove the Stale Benchmark Test Copy From Normal Discovery (P3, tests)

Owner after consolidation: [fman_performancetest/test_filter_find_benchmark.py](../src/performancetest/python/fman_performancetest/test_filter_find_benchmark.py).

Evidence: the module is tracked in both `src/unittest` and
[src/performancetest](../src/performancetest/python/fman_performancetest/test_filter_find_benchmark.py).
`build.py test` discovers `test*.py` under `src/unittest/python`, so report and
benchmark tooling tests run in normal verification and CI, contrary to the
policy in [DEVELOPMENT.md](../DEVELOPMENT.md#tests-and-packaging). The copies
differ by one test: the unittest copy alone has
`test_report_product_name_comes_from_settings`, added by the application-name
change.

Design: move that test into the performancetest copy, then delete the unittest
copy. No application change.

Risk: none for the application; normal discovery loses only tooling tests that
remain runnable through the documented development-tool checks. Deleting the
tracked file needs owner approval.

Also trivial: [CopyPathsToClipboard](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L993)
builds an unused `files` string; remove it when touching that command.

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
- **Candidates checked and rejected in the 2026_09_25 Opus review:**
  `_query_info_attr` returning the folder default after the first listed entry
  (deliberate: an implied archive folder lists children first); `DirEntry`
  junction/symlink checks in directory sizing (cached on Windows, no extra
  system calls); the local scan's link-metadata fallback (documented
  missing-target behavior); highlight skipping on elided table/QuickList text
  (safe by design); FindFiles DST boundary rejection (deliberate and tested);
  the fuzzy query's escaped trailing space (handled). No change proposed.

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
| 22 | UTF-8, UTF-8 BOM, legacy ANSI and malformed JSON through settings, key bindings/context menus and the F1 shortcut list | [load/save JSON tests](../src/integrationtest/python/fman_integrationtest/plugin_tests/test_load_save_json.py), [key binding tests](../src/integrationtest/python/fman_integrationtest/plugin_tests/test_key_bindings.py) |
| 23 | Unchanged sort makes no save; changed and reset sorts save once | [Core command tests](../src/main/resources/base/Plugins/Core/core/tests/commands/test___init__.py) |
| 24 | Seven-plus-digit runs, leading zeros, adjacent text/punctuation and descending order | [Core column tests](../src/main/resources/base/Plugins/Core/core/tests/fs/test_columns.py) |
| 25 | Absent drive root and UNC paths are kept; missing paths on present drives are removed | [GoTo tests](../src/main/resources/base/Plugins/Core/core/tests/commands/test_goto.py) |
| 26 | Case-only pairs on Windows local panes; exact comparison for other schemes; listing error alerts | [comparator tests](../src/main/resources/base/Plugins/Core/core/tests/test_comparator.py) |
| 27 | Moved report test passes in the performancetest module; unittest discovery no longer imports it | [performance tool tests](../src/performancetest/python/fman_performancetest/test_filter_find_benchmark.py) |

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

Original batch sequence below is retained for context. The Release Proposal's
dispositions and delivery order take precedence; obtain user approval before
implementation or creating separate archive/overwrite safety tasks.

1. Independently review the twenty-seven proposed items and exclusions. Do not absorb the
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
11. Implement items 22-26 owner by owner with their focused tests. Apply item 27
   only after the owner approves deleting the tracked unittest copy.
12. Run the focused aggregate and required native/manual gates, record exact
   commands/results and any remaining limitations. Update changelog only for
   qualifying implemented application changes. Add implementation provenance,
   then move this canonical document to Done and its index link to Completed.

## Acceptance Criteria

These original criteria apply only to approved items with the corrections above;
deferring an item does not mean it passed. Wide-use release additionally requires
the Release Proposal's safety decisions and release gates.

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
- Hand-edited UTF-8 (with or without BOM) configuration loads correctly; legacy
  ANSI files still load. Unchanged sorts cause no settings save on navigation.
- Names with seven or more digits sort numerically; Go To keeps entries on
  unavailable volumes; Compare Directories ignores case-only differences on
  Windows local panes; tooling tests leave normal unittest discovery.
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
- Items 22-27 (2026_09_25): JSON decoding reproduced with temporary UTF-8 and
  UTF-8-BOM files against the real `config.load_json`; the natural-sort order
  reproduced with the Core key function; `os.path.isdir` on an unmapped drive
  returned `False`; the benchmark copies were compared with
  `git diff --no-index`. Items 23 and 26 are code-path findings, not executed.
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

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Reviewed host API/plug-in system, Core commands and filesystems,
  bundled plug-ins, UI components, tests and build tooling. Added items 22-27:
  locale-decoded hand-edited JSON (P2, reproduced), per-navigation sort-settings
  saves, seven-plus-digit natural-sort misorder (reproduced), Go To history loss
  on unavailable volumes, case-only Compare Directories differences and a stale
  benchmark test copy in normal discovery. Marked item 16's first bullet as
  already implemented. Rejected six candidates with reasons. No application
  code changed.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Consolidated all twenty-seven findings into a release proposal.
  Elevated local-to-archive source retention, overwrite-failure policy and
  concurrent command targeting to explicit release decisions. Required link
  guards at both merge and provider boundaries; rejected unsafe cleanup and
  unlink-before-replacement shortcuts. Corrected QuickView signal assumptions,
  reproduced proposed numeric-sort regressions, deferred unmeasured repaint
  changes and blanket Windows case folding. Proposed focused implementation
  followed by separately authorized full-suite, portable and performance gates.
  No application implementation, full audit or release approval claimed.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review of items 1–27. **Approved for continued
  work; not for release** — one reproduced functional regression and two
  over-strict identity rules must be fixed first. Re-ran the documented
  combined gate: 607 tests, OK, 8 privilege skips. Verified by reading the
  diffs: junction/symlink classification before recursion in `prepare_delete`
  and `_do_delete` re-raising on links and on writable files (1, 3);
  `_prepare_move` renames links on the same device via `lstat` and refuses
  cross-device link moves with `UnsupportedOperation`, surfaced as an alert
  by `_gather_files` before any task runs (12); merge refuses to traverse a
  link on either side and iterates through `_iter` (6, 12); exclusive
  staging + `ReplaceFileW` with an owned backup and identity re-check (2, 11);
  thread-local cursor override with `finally` restoration and `nullcontext`
  in the registry (5); `LatestJobs`/`submit_work` release capacity on thread
  start failure (7, 18); `resource()` allocates on miss only (8); status
  completeness tracks failed sizes (9); one URL per status row (10);
  `PermissionError`/`NotADirectoryError`/WinError 2,3,5,21 routed to
  `location_disappeared` (15); settings serialize-then-replace with non-dict
  root fallback (4, 22). Natural-sort key (24) probed on 30,000 random
  numeric names: numeric order exact, punctuation/letter ordering unchanged,
  6/7/8-digit boundaries correct. Findings:
  1. **Regression (reproduced): copying a read-only source over an existing
     writable destination fails with `PermissionError [WinError 5]`.**
     `copystat(src, temporary)` sets `FILE_ATTRIBUTE_READONLY` on the
     replacement file and `ReplaceFileW` rejects a read-only replacement. The
     destination is retained and no staging file is left behind, so data is
     safe, but a common case (files from CDs, git checkouts, extracted
     archives) that worked before now fails. Fix: copy timestamps to the
     temporary, publish, then apply the mode/read-only bit to the destination
     (or clear READONLY on the temporary before `ReplaceFileW` and restore it
     after). New-file copies of read-only sources work.
  2. **Over-strict overwrite identity rule.** `not destination.st_ino or
     destination.st_nlink != 1` refuses *every* overwrite on volumes that
     report zero identity (Google Drive File Stream, some SMB shares — the
     same case `samefile()` already special-cases with a resolved-path
     fallback). Reproduced by mocking `lstat`. Suggest: refuse only when
     `st_nlink > 1`; when `st_ino == 0`, fall back to resolved-path equality
     for the alias check and allow the overwrite.
  3. Same rule in `Settings._check_destination` (`st_nlink != 1`) refuses to
     save Session/Dialogs JSON on such volumes; relax to `> 1`.
  4. Staging names `.fman-copy-*` and `.fman-previous-*` are created in the
     destination folder without the hidden attribute; with the snapshot
     pane, a rescan triggered by an earlier task's `notify_file_added` shows
     them mid-operation. Set `FILE_ATTRIBUTE_HIDDEN` on both so the default
     filter hides them (one `SetFileAttributesW`/`os.chmod`-equivalent call).
  5. Behaviour changes broader than the original items, all documented but
     worth the user's explicit awareness: local→archive **Move is now
     refused** outright (feature removal, not a fix); overwrite on non-Windows
     refuses (`UnsupportedOperation`); overwriting a hardlinked destination
     refuses; symlink copy onto an accepted overwrite still fails, now with a
     bare `FileExistsError` (13, deferred — the message should say the
     overwrite was refused).
  6. `_publish` compares the full `stat_result` (including integer-second
     `st_atime`); an antivirus touching the destination during the copy
     yields "Destination changed while copying; replacement refused" as a
     bare `OSError`. Rare; acceptable, but compare only
     `(st_ino, st_dev, st_size, st_mtime_ns)`.
  7. Go To no longer prunes non-existent history in the background (25);
     stale entries persist until the bounded shrink. Acceptable trade.
  Items 1–3 are small and should land before the task moves to Done; the rest
  are notes. No application code changed by this review.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Addressed all seven implementation-review remarks with explicit
  dispositions and focused evidence. Confirmed the three required fixes, retained
  link/source-retention guards, and deferred hidden staging to avoid routine
  metadata overhead. Author validation only, not an independent release review.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Independent implementation review of the current working tree,
  including the follow-up fixes. **Approved for continued work; not for
  release.** No blocking defect found. Re-ran the documented combined gate plus
  `core.tests.test_comparator`: 638 tests, OK, 9 skips. Read every production
  diff; the staged copy/`ReplaceFileW` recovery, identity fallback, link guards,
  settings publication, worker rollbacks, JSON decoding, natural-sort key,
  sort-save skip and comparison ordering match their approved dispositions.
  Findings, all small:
  1. **Double terminal notification (reproduced).** When a queued job's worker
     fails to start in `LatestJobs._run`'s `finally`, the job receives both its
     canceled callback and `deliver(None, error)`. An in-memory probe recorded
     `canceled` then `deliver RuntimeError`. For refresh scans both callbacks
     call `_deliver` for the same revision. The approved item 18 requires one
     retirement. Call only `deliver(None, error)`, matching ordinary worker
     failure, and add a test; the existing test covers only the `submit` path.
  2. **Thread-local cursor override is invisible on Qt helpers (code path).**
     `comparator._capture` runs `@run_in_main_thread` and reads
     `get_file_under_cursor()` there, so `compare_files` from a (user-added)
     file context menu compares the real cursor, not the right-clicked file.
     Bundled menu commands read the cursor on their worker and are unaffected.
     Capture the invoking pane's cursor on the command thread and pass it in;
     note in PlugIn.md that overrides apply only on the command's thread.
  3. **Misleading refusal for cross-format archive moves.** `_7ZipFileSystem.
     prepare_move`'s final branch also handles zip to 7z/tar moves (different
     schemes), which now fail with "Moving local files into archives...".
     [docs/archives.md](../docs/archives.md) says F6 works between two
     archives. Use a separate message and document "same archive format".
  4. **Staging names can exceed MAX_PATH (not reproduced).** `.fman-copy-*`
     (~19 characters) and `.fman-previous-*\original` (~33) can push a deep
     destination with a short name past 260 characters, where the old direct
     write succeeded. This machine has `LongPathsEnabled=1`, the Windows default
     is off. Use shorter prefixes and test a near-limit path with long paths off.
  5. **Copy merges now refuse source directory links too.** The guard in
     `_merge_directory` is shared by Copy and Move; copying through a source
     link only duplicates data. Keep as-is or narrow to Move and destination
     links in [Link Operation Policy](LinkOperationPolicy.md); it is a behavior
     tightening worth recording.
  6. **Silent session loss for linked settings.** `Settings.flush` refuses a
     linked `Session.json`; its callers swallow `OSError`, so window/pane state
     is silently never saved. Report once via status or log.
  7. Trivia: `goto._remove_nonexistent` is now dead code.
  Items 1-4 should land before this task moves to Done; 5-7 are notes. No
  application code changed by this review.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Addressed all seven remarks in the latest implementation review,
  including the link-merge documentation/coverage suggestion and dead helper.
  Queued double retirement reproduced and fixed; combined affected-area gate
  passed 324 tests with 9 privilege skips. Real disabled-long-path configuration,
  live storage and existing release gates remain unverified; no release approval.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context Window: 272K
- Outcome: Independently reviewed the implemented findings and follow-up fixes.
  No blocking implementation defect remained after tracing the production archive
  cleanup path. Found one low-severity coverage regression: the only assertion for
  the changed documentation copyright footer is commented out instead of updated,
  so the new text is untested. Independent focused validation passed 650 application
  tests with 9 privilege skips, and 43 opt-in performance-tooling tests passed.
  Privileged link behavior and the documented full-suite, portable-build,
  clean-machine, second-volume, live-storage and long-path-disabled release gates
  remain open; no release approval.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Addressed the latest footer-coverage remark under the user's explicit
  requirement that wording remain freely editable. Validate text and configured
  app-name substitution, not a fixed sentence. Other remarks retain existing
  release gates; no release approval.

## Implementer

### 2026_09_25 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented approved owner-local hardening, archive-move containment,
  Windows staged overwrite with protected temporary data and recovery backup,
  thread-local command context, worker cleanup and measured small optimizations.
  Final focused gate: 607 tests, 599 passed and 8 privilege skips; opt-in tooling
  43 passed. Native Search Files layout failure reproduced against HEAD. Explicit
  refusal/deferred items and remaining release gates are recorded above; task
  remains pending, without claiming release completion.

### 2026_09_25 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Fixed read-only overwrite, missing identity/link-count compatibility,
  explicit symlink overwrite errors and destination revalidation. Removed cosmetic
  staging metadata calls. Focused gate: 230 tests, 222 passed and 8 privilege skips;
  task remains pending the documented release checks.

### 2026_09_25 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Fixed queued-start double delivery, comparator context capture,
  cross-format archive errors and silent session saves; shortened/extended private
  staging paths and removed dead Go To pruning. Retained and tested Copy/Move link
  merge refusals. Combined focused gate: 324 tests, 315 passed and 9 privilege
  skips. Usage, policy and dispositions updated; task remains pending release gates.

### 2026_09_25 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Replaced the commented footer assertion with text/type and configured
  app-name checks, leaving prose unconstrained. DocumentationNamingTest passed
  (1 test); production hook unchanged. Existing release gates remain open.