# Archive Transfers

## Task

Improve progress, cancellation, and failure handling when users copy or move
items from an archive into a local directory. Reuse the same extraction backend
for [Unpack archive](../Plan/UnpackArchive.md). This is task (2), implemented and
validated below. The separate Unpack command remains pending.

## Scope

Included:

- Existing archive-to-local Copy, Move, and drag-and-drop extraction, including
  selected files and folders. Whole-archive Copy is supported; Move rejects the
  archive root and asks the user to select its contents.
- Meaningful extraction progress, cancellation during quiet process phases,
  temporary-output cleanup, and safe publication of completed output.
- A distinct source-archive update phase for Move, with deferred cancellation
  while that update is running.
- Regression coverage for other callers of the shared extraction machinery.
- Approved safety exception: archive-to-archive Move must finish and verify
  destination packing before source deletion. Correctness takes priority over
  speed, including an extra destination verification pass.

Unchanged: archive browsing and navigation, selection, destination prompts,
overwrite decisions, folder merging, and the modeless progress dialog. Browsing
lists archive entries; it does not unpack the entire archive. Ordinary local
copy/move and Windows Explorer's transfer interface are outside this task.

Excluded: new archive formats, passwords, archive-path parsing fixes, browsing
speed improvements, pause/resume, speed/ETA displays, a new transfer manager,
transactional rollback of an entire selection, and general redesign of archive
packing. The narrow archive-to-archive Move ordering exception above is included.
Local-to-archive Move and same-archive rename retain their existing behavior.
Shared-helper changes must not regress other operations. Verified Moves reject
symbolic links and junctions rather than authorize deletion on uncertain data.

API compatibility: preserves the public `fman` plug-in API from fman 1.7.5.
Changes stay internal to Core and do not change public task/filesystem signatures.

## Design

### Pre-Implementation Behavior

- [Archive filesystems](../src/main/resources/base/Plugins/Core/core/fs/zip.py)
  returned size-zero `Extract` tasks for archive-to-local copies, waiting in
  `_run_7zip` without progress or cancellation checkpoints.
- [FileTreeOperation](../src/main/resources/base/Plugins/Core/core/fileoperations.py)
  totals prepared task sizes and runs them through `Task.run`. Extraction-only
  operations consequently showed a busy bar, not a percentage.
- Move prepared extraction followed by independently queued source deletion.
  Deletion could rewrite the archive without useful progress or cancellation.
- Commands already run on workers. The existing progress dialog is modeless;
  pane interaction is not deliberately blocked during a transfer.

### Ownership And Process Lifetime

Keep binary discovery, process execution, progress parsing, staging, and archive
notifications in Core's archive filesystem. Extend the existing `_7zip` and
`_7zipTaskWithProgress` abstractions; do not introduce a second process wrapper
or invoke 7-Zip from the new command.

The command worker owns each child process and all task decisions. A bounded
output reader may drain the child's pipe on one operation-scoped thread; it
receives plain data and never accesses Qt. The worker polls cancellation with
100 ms queue/process waits, independently of whether stdout produces a complete
line. This is not a hard real-time bound.
Use bounded buffering and bounded diagnostic records; split carriage-return
progress, newline output, and backspace (`\b`) erase sequences without buffering
an arbitrarily long record. Normalize these across read boundaries, preserving
the progress records that precede an erase sequence.

For `Extract`, select the existing `Popen7ZipWindows` transport explicitly with
`-bsp1` and `pty=False`: progress travels over stdout and cancellation calls
`Popen.kill()`, followed by wait/reap. Make transport selection explicit in the
private progress helper while retaining the existing default for packing/rename.
Native 7-Zip 26.03 pipe capture confirmed `  0%` and `100% 1` progress records.
Fake readers additionally cover split CR/LF/backspace records and pty output.
Do not silently fall back to winpty: its `sendcontrol('c')` is not guaranteed
process termination. If pipe progress is insufficient, revisit transport before
claiming the acceptance criteria. Drain stdout, including bounded diagnostics,
while the child runs to prevent pipe backpressure.

Every exit path reaps the child, closes its streams, and joins any reader before
cleanup. Cancellation must also work when the process is quiet or stdout ends
before the process exits. No orphan process, reader, or blocked queue producer
may remain. Process termination latency is separate from the polling interval.

### Extraction Progress And Publication

Give `Extract` a fixed size of 100. Report monotonic progress from parsed 7-Zip
output; tolerate split records, repeated/reset percentages, and absent progress.
Reserve completion for successful publication: extraction contributes at most
99 units, and the last unit follows the final move. Do not invent intermediate
percentages when 7-Zip supplies none.

### Task Sizes And Preparation Counts

Leaf sizes and nested composite budgets are fixed before attachment through
`Task.run`; `ChildProgressDialog.set_task_size` raises after attachment. A root
such as `FileTreeOperation` may still set its total from prepared children before
running them, as today. Do not change the public Task API or that root behavior.

Composite size equals the sum of its fixed child budgets: extraction 100,
source-archive update 100, packing 100, destination verification 100, and
existing local cleanup 0. `MoveOutOfArchive` and `CopyBetweenArchives` are 200;
`MoveBetweenArchives` is 400. Its `AddToArchive(for_move=True)` child reserves
200 for packing and verification; ordinary packing remains 100.
When temporary paths do not exist until execution, derive the constructor's
budget from those fixed phase definitions, instantiate the corresponding
children when paths are available, and verify their sizes fit the reserved
budget. Never resize an already attached composite in `__call__` or create
temporary directories during preparation solely to discover its task size.

Expose archive-to-local Move as one prepared composite task with internal
extraction and source-update children. This makes `_enqueue` count one transfer,
not extraction plus deletion as two files, without changing its behavior for
ordinary or third-party tasks. Counts describe prepared transfer roots, not
members inside an extracted folder. Multiple extractions retain equal task
weights, not byte- or time-weighted progress.

### Publication

Continue extracting into a temporary directory beside the destination. Check
cancellation before spawning and immediately before publishing. On cancellation,
terminate and reap 7-Zip, discard that task's staged output, and propagate
`Task.Canceled`; do not publish it or execute its source-deletion step.

Directory publication must fail if the target appeared after preparation,
including an empty directory or differently cased Windows name. Keep `Extract`
routing publication through `fman_fs.move`, not directly to an OS path helper.
In Core's local `LocalFileSystem._rename`, use `os.rename` for Windows directory
sources and retain `Path.replace` for files. Keep the existing
`notify_file_removed` and `notify_file_added` calls after successful publication;
emit neither on a failed rename. No duplicate notification path in `Extract`.

`os.rename` refuses an existing destination on Windows; do not claim that its
POSIX behavior provides the same protection. Preserve the existing non-Windows
path. This makes Windows directory non-replacement explicit without changing
normal file overwrite or directory merge choices. A second existence check
alone is not race protection. Regression-test ordinary moves and directory
links as well as extraction, since the private rename helper is shared.

The final rename is a short commit boundary, not interruptible halfway through.
If cancellation arrives after commit, that completed output remains. Earlier
completed items also remain; the selection is not rolled back.

### Moving Out Of An Archive

Preserve extract-then-delete ordering for each item. Check cancellation again
before starting source deletion. A failed or canceled extraction never deletes
its source entry. Copy never modifies the source archive. The prepared Move
composite runs both phases internally and propagates extraction failure before
entering deletion. Do not leave deletion as an independent item in
`FileTreeOperation._tasks`: choosing Continue after a failed extraction would
otherwise execute that deletion. This follows the dependency rule already used
by local `MoveByCopying`, without making the transfer transactional.

Before extraction, fingerprint the full source archive using file identity,
size, modification time, and SHA-256. Hash again just before deletion; reject a
changed fingerprint or a stat change during hashing. Hash the staged extracted
tree and published local output, comparing names, node types, empty directories,
and file bytes. Verification does not promise preservation of all metadata.

Represent deletion as an explicit task phase, with a label such as
`Updating <archive>`. Report progress where 7-Zip supplies it and otherwise keep
the phase label and last known progress; no fabricated ETA. Budget this phase
in the parent total so extraction does not show 100% while Move is still running.

Once source-archive mutation starts, defer cancellation until the update and
existing empty-parent preservation finish. Do not kill a process rewriting the
original archive. The dialog must indicate that cancellation is waiting for the
archive update; after the phase finishes, stop before the next selected item.
This is operation-boundary cancellation, not a crash/power-loss guarantee.

If deletion fails, keep the successfully extracted destination, stop the Move,
and report that source removal failed and the archive may need inspection.
Never delete the output as compensation. Do not promise the original archive
is unchanged after a failed in-place update.

### Archive-To-Archive Move Safety

Never implement this bridge as move-to-temporary followed by move-to-destination.
Use extract-to-temporary, pack destination with strict exit checking, verify the
destination archive and requested entries, then delete source entries. Keep the
source on failure, warning, or cancellation before source mutation. Temporary
cleanup is permitted because source deletion cannot precede verified destination
success. Cancellation during destination archive mutation is deferred until the
mutation finishes; then stop before source deletion.

Destination verification may require additional I/O. A successful process exit
or an existing directory alone is not sufficient to authorize deletion. Verify
the destination contains the staged entries with matching contents before
discarding the source. Source changes detected between extraction and deletion
must stop the Move without removing source entries. Crash/power-loss recovery
for in-place archive mutation is still not guaranteed.

`AddToArchive(for_move=True)` hashes the staged source, packs with strict exit
checking, then runs `Extract(expected_digest=...)` against the destination.
Verification uses a separate temporary directory from packing input so archive
entry names cannot collide with its output. Literal entry operands use `-i!`
and `-spd`, including names starting with `@`. Reject source/destination archive
aliases detected by `samefile`, and extraction over the source archive itself.

There is no exclusive file lock or atomic link between the final verification
and deletion. External edits after either check remain a race; users must not
edit the archives or output during Move. In-place packing can damage an existing
destination on process/storage failure, even though source deletion has not yet
started. Stronger isolation and crash recovery are outside this task.

### Errors, Cleanup, And UI

Preserve existing overwrite/merge decisions and filesystem notifications.
Keep `_7zipError` as `CalledProcessError` for existing non-transfer callers.
At the extraction task boundary, translate it to `OSError(errno.EIO, message)`
with bounded diagnostic text and exception chaining. `FileTreeOperation` can
then use its existing Continue/Abort alert policy; continuation skips the whole
failed transfer, including any dependent source deletion. Do not catch
`Task.Canceled` in that translation. Native filesystem errors retain their
original useful types; programming errors retain normal error reporting.

Source-update failure requires stronger handling than a skippable extraction
failure. Define a private `OSError` subclass in Core's file-operations layer
for that outcome, raised by the Move composite around its update phase.
`FileTreeOperation` catches it before generic `OSError`, reports the retained
output and possible archive damage, and unconditionally stops. Do not route it
through Continue/Yes-to-All, including when an earlier error enabled that policy.

### Exit Codes And Output Validation

Add a private strict-exit policy to the process runner for extraction and the
Move source-update phase; keep the legacy warning policy for unrelated callers.
Extraction succeeds only with exit code 0 and the requested `path_in_zip`
present under the staging directory. When `path_in_zip` is empty, an empty
staging root is valid for a successfully extracted empty archive.

Exit code 1 is an extraction failure even if the requested path exists. A
folder can exist while some children are missing, and the staging root exists
before 7-Zip runs, so existence is only a sanity check, not a completeness proof.
Do not publish or delete source entries after warnings. A warning during source
mutation uses the source-update failure path: preserve extracted output, stop,
and report that the archive may have changed. Do not claim rollback.

### Cleanup

Cleanup follows process teardown. Allow bounded retries for transient Windows
file locks. Preserve the primary failure or cancellation if cleanup also fails;
report the residual temporary path separately rather than silently ignoring it.
A visible temporary sibling is possible while working or after cleanup failure.

Use the existing Qt-thread marshaling and throttled dialog updates. No pane
widgets or models move to worker threads. No new persistent settings are needed.

## Alternatives

- Keep the busy indicator: simpler, but does not address progress or ineffective
  cancellation during extraction.
- Change `Extract` to the current progress helper without hardening it: rejected
  because cancellation would still depend on output arriving.
- Kill 7-Zip at any stage: rejected for in-place archive updates. Defer cancel
  at that commit boundary instead.
- Rewrite a separate full archive and atomically replace the original: stronger
  update isolation, but adds full-archive I/O and temporary space. Defer to a
  separate task; do not imply transactional Move in this design.
- Delegate to Explorer or create a new extraction engine: incompatible with the
  existing archive URLs and unnecessary duplication of Core behavior.

## Runtime Effects

- Startup/unused path: no new scans, settings reads, processes, workers, timers,
  or recurring signal work. Browsing incurs no new extraction work.
- Active extraction: the existing command worker and one 7-Zip child at a time,
  plus at most one bounded output-reader thread. Cancellation polling exists
  only during an active process; Qt uses its existing progress timer.
- Move adds two full source-archive hash reads, extracted-tree hashing, and
  archive rewriting. Local publication is rehashed; cross-archive destinations
  are re-extracted and hashed. No full source-archive staging copy is introduced.
- Temporary disk usage scales with extracted output. A cross-archive Move can
  hold the source extraction, a packing copy when symlink staging is unavailable,
  and a verification extraction simultaneously, plus 7-Zip's update workspace.
- Pipe buffering is capped at 16 chunks of 4096 characters and 100 diagnostic
  records of at most 4096 characters. Hashing reads 1 MiB blocks; sorting tree
  names retains per-directory metadata. 7-Zip memory remains format-dependent.
- Cancellation discards uncommitted extraction output. Active archive mutation
  finishes before cancellation is honored. Cleanup failures are visible.
- Persistence: none. Local extraction stages beside its destination; bridge,
  packing, and verification directories use the existing OS temporary location.
  No Registry writes or application-install-directory state is introduced.

## Tests

Coverage lives in the existing `core.tests.fs.test_zip`,
`core.tests.fs.test_local`, and `core.tests.test_fileoperations` modules, plus
`ArchiveTransferIT` in the existing Qt harness. `FakePipeProcess` drives pipe
reads; reader tests also cover existing pty decoding, control characters and EOF.
Required checks:

- Whole archive, file, subfolder, and empty-directory extraction still match
  expected contents and notifications for ZIP; native 7Z and TAR smoke cases.
- Progress records split across chunks, CR/LF/backspace boundaries, zero/100, resets,
  malformed/oversized output, absent output, and bounded diagnostic retention.
- Real 26.03 `-bsp1` pipe capture; extraction selects Popen rather than winpty.
  Fake pipe/pty coverage preserves existing packing and rename reader behavior.
- Quiet-process cancellation and early stdout closure; kill/reap/close/join
  ordering; no publish or source deletion; no surviving child/reader.
- Cancellation immediately before publish and between extraction and source
  deletion; cancellation after commit retains completed output.
- Destination races involving files/directories, case-insensitive conflicts,
  permissions, failed extraction, warning exit codes, and cleanup failure that
  must not mask the primary outcome.
- Multiple selected items and nested archive tasks have monotonic bounded
  progress. Verify 200 for copy-between-archives and 400 for move-between-
  archives, no nested `set_task_size`, and one preparation count per Move root.
  Existing file overwrite and directory merge behavior is preserved.
- Move updates source only after success; cancel during update does not kill
  the child and stops before the next item; update failure retains output.
- Archive-to-archive destination failure, warning, verification mismatch, and
  cancellation preserve source entries. Successful transfers verify destination
  contents before deletion, including folders and empty directories. A changed
  source aborts deletion. Check ordering with fault injection and real archives.
- A valid source rewrite preserving device, inode, size and mtime still blocks
  deletion. A changed published local output also blocks deletion.
- Measure 20 sequential Moves from a 64 MiB stored ZIP payload, recording each
  item's wall time and Python hashing read bytes. Check moved contents, retained
  source entries and staging cleanup; timing has no pass/fail speed threshold.
- A translated process error reaches the existing task alert. Choosing Continue
  after failed extraction skips its source deletion but allows an unrelated
  later transfer. Source-update failure stops even after prior Yes-to-All.
- Warning exit 1 with a present but incomplete output directory still fails;
  missing requested output on exit 0 fails; a valid empty archive succeeds.
- Qt integration: progress remains modeless, updates are delivered on Qt,
  cancellation works while output is quiet, and panes remain interactive.
  Add `ArchiveTransferIT` to the existing `fman_integrationtest.test_qt` harness.
- Cover the non-overwriting directory publication primitive in existing
  `core.tests.fs.test_local` tests, including `os.rename` versus `Path.replace`,
  directory-link behavior, success-only notifications, and late conflicts.

Focused command, using the repository test environment:

```powershell
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip', 'core.tests.fs.test_local', 'core.tests.test_fileoperations', 'fman_integrationtest.test_qt.ArchiveTransferIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

Run the narrowest affected test immediately after the first code edit.

Manual/performance procedure: browse ZIP/7Z/TAR; copy a large file and a folder
out; cancel extraction; move selected items out; cancel during source update;
inspect source/destination and temporary siblings after every outcome. Keep
using the other pane throughout. Compare the same archives before/after for
elapsed time and bounded Python buffering; document results without claiming a
speedup. No full suite, clean, freeze, or package installation is required.

## Implementation Steps

1. Review the revisions below. Capture real 26.03 `-bsp1` pipe progress records
  and add focused fake-process regression cases for pipe and pty readers.
2. Harden process draining/cancellation/teardown; immediately run the relevant
   process-helper tests and retain packing/rename behavior.
3. Add extraction progress, guarded directory publication, cleanup handling,
   and warning/error behavior; run focused extraction regressions.
4. Group Move phases, add deferred cancellation and mandatory-stop update
  errors; verify fixed budgets, preparation counts, and source-deletion
  ordering in direct and nested callers.
  Replace the archive-to-archive bridge with copy/verify/delete and exercise
  failed or canceled destination packing before any source deletion.
5. Add Qt and real-format smoke coverage. Update README transfer/cancellation
   behavior and CHANGELOG only when the application changes are implemented.
6. Record exact validations and implementation provenance, then move this
   canonical document to `Done/` and update the index when criteria pass.

## Acceptance Criteria

- Archive navigation and existing destination/overwrite choices remain unchanged;
  verified Move rejects archive roots, links, and junctions as documented.
- Extraction reports real progress when available and Cancel stops quiet as
  well as output-producing children. Cancellation polling uses 100 ms waits;
  tests exercise quiet output and EOF-before-exit without a real-time guarantee.
- Canceled/failed extraction does not publish unfinished output or remove its
  source. Successful completion preserves notifications and conflict behavior.
- Move distinguishes source update, defers cancellation during mutation, and
  retains completed output if deletion fails. No whole-batch rollback is implied.
- Continue after failed extraction cannot run its source deletion; source-update
  failures always stop. Warning exit codes never authorize source deletion.
- Archive-to-archive Move deletes source entries only after verified destination
  success. Failures, canceled packing, and source changes preserve the source.
- Nested task sizes are fixed before attachment, match their child budgets,
  and do not inflate the displayed preparation count.
- Normal cancellation leaves no child, reader, or temporary output; injected
  cleanup failures preserve the primary result and report residual output.
- Focused unit, Qt, and ZIP/7Z/TAR checks pass; performance observations and any
  unavailable manual checks are recorded honestly before completion.
- No new idle work or public `fman` API break is introduced.

## Reviewers

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Separated task (2) from the new command. Designed shared extraction
  progress and quiet-process cancellation, with deferred cancellation during
  source-archive mutation. Pending review and implementation; no code changed.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved in principle; five design gaps to close before
  implementation. Verified against `core/fs/zip.py`, `core/fileoperations.py`,
  `fman.Task`/`fman.impl.task` and `core/fs/local/__init__.py`.
  Confirmed: `Extract` is size 0 and runs `_run_7zip` (plain `Popen`, no
  progress on a pipe); `_7zip.__exit__` already accepts exit code 1; the
  progress dialog is modeless; `Extract = 100` makes `CopyBetweenArchives`
  and `MoveBetweenArchives` sum to exactly their declared 200 (today they
  stop at 100 of 200).
  Gaps: (1) `FileTreeOperation.__call__` catches only `(OSError, IOError)`;
  `_7zipError` is a `CalledProcessError`, so a failed extraction today is an
  unhandled-exception report, not the Skip/Abort task alert the plan
  promises. State the fix (derive `_7zipError` from `OSError`, or translate in
  `Extract`) and test it. (2) `ChildProgressDialog.set_task_size` raises, so
  every size must be fixed at construction. If the Move deletion `Task` gains a
  positive size, `MoveBetweenArchives` (declared 200) overflows; replace
  "audit" with a rule: composite sizes are computed from prepared children.
  (3) `_enqueue` counts every task with `size > 0` as a file in
  "Preparing to move N files"; a sized deletion phase double-counts. Decide:
  accept, or count only transfer tasks. (4) Make `-bsp1` the primary
  transport for `Extract`, not a fallback: it emits percentages on a pipe, so
  `Extract` stays on `Popen7ZipWindows` and cancels with `Popen.kill()`
  (reapable), avoiding winpty whose `kill` is `sendcontrol('c')` with no
  delivery guarantee. Record splitting must handle `\b` erase sequences as
  `Run7ZipViaPty.Stdout` does, not only `\r`/`\n`; step 1's capture decides.
  (5) Publication today is `fman_fs.move` -> local `_rename` -> `Path.replace`;
  on Windows that already refuses to replace a directory, including a
  differently cased one, while replacing files. Name the primitive
  (`os.rename`, not `replace`, for the directory case) and whether `Extract`
  keeps routing through `fman_fs.move` for cache notifications or calls the
  local filesystem directly. Corrections: `core.tests` has no fake-process
  fixture; `test_zip` runs the real `7za`, so Tests must say "add", and the
  fake must cover both `Popen` and pty readers. For the warning-exit
  completeness check, name the criterion: the requested `path_in_zip` exists
  under the temporary directory before publication. Planning review only.

#### Follow Up Tasks

Resolve each item in the Design text before coding; tick it and name the
section that resolves it.

- [ ] **Error class.** `FileTreeOperation.__call__` catches only
      `(OSError, IOError)`; `_7zipError` is a `CalledProcessError`, so a
      failed extraction is an unhandled-exception report today. State the fix
      (derive `_7zipError` from `OSError`, or translate in `Extract`) and add
      a `test_fileoperations` case showing the Skip/Abort alert.
- [ ] **Fixed sizes.** `ChildProgressDialog.set_task_size` raises, so all
      sizes are set at construction. Add the rule "composite task size = sum
      of prepared children" and apply it to `MoveBetweenArchives` (declared
      200) if the Move deletion `Task` gains a positive size.
- [ ] **File count.** `_enqueue` counts every `size > 0` task in "Preparing to
      move N files". Decide whether a sized deletion phase may double-count or
      whether only transfer tasks are counted; record the decision.
- [ ] **Transport.** Make `-bsp1` on the existing `Popen7ZipWindows` path the
      primary choice for `Extract` (progress on a pipe, cancel via
      `Popen.kill()`), with winpty only if the capture in step 1 shows `-bsp1`
      is insufficient.
- [ ] **Record splitting.** Handle `\b` erase sequences as
      `Run7ZipViaPty.Stdout` does, in addition to `\r` and `\n`.
- [ ] **Publication primitive.** Name `os.rename` (not `Path.replace`) for the
      directory case and state whether `Extract` keeps routing through
      `fman_fs.move` for cache notifications or calls the local filesystem
      directly with explicit `notify_file_added`.
- [ ] **Warning exit code.** Define the completeness criterion as "the
      requested `path_in_zip` exists under the temporary directory before
      publication".
- [ ] **Tests wording.** `core.tests` has no fake-process fixture; change
      "extend" to "add", and require the fake to drive both the `Popen` and
      pty readers.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Incorporated the review into the operative design with the
  resolutions below. Rejected output existence as sufficient evidence after
  a warning, and added dependent Move grouping so Continue cannot delete an
  unextracted source. Prior reviewer records remain unchanged. Design changes
  only; implementation and native pipe capture remain pending.

#### Feedback Resolutions

- [x] **Error class:** [Errors, Cleanup, And UI](#errors-cleanup-and-ui)
  translates extraction process errors locally and makes source-update failures
  stop unconditionally. [Moving Out Of An Archive](#moving-out-of-an-archive)
  groups extraction/deletion before permitting Continue on unrelated items.
- [x] **Fixed sizes:** [Task Sizes And Preparation Counts](#task-sizes-and-preparation-counts)
  fixes nested budgets before attachment, defines 200/300 composite totals,
  and retains supported root-level sizing. Temporary-path-dependent children
  use reserved phase budgets rather than late nested resizing.
- [x] **File count:** [Task Sizes And Preparation Counts](#task-sizes-and-preparation-counts)
  exposes one Move task to `_enqueue`; source deletion is an internal phase.
- [x] **Transport:** [Ownership And Process Lifetime](#ownership-and-process-lifetime)
  selects `-bsp1` on Popen explicitly; no silent downgrade to winpty cancellation.
- [x] **Record splitting:** [Ownership And Process Lifetime](#ownership-and-process-lifetime)
  requires CR, LF, and backspace handling across read boundaries.
- [x] **Publication primitive:** [Publication](#publication) retains
  `fman_fs.move` and its local notification path, using Windows `os.rename`
  for directories and retaining file replacement behavior.
- [x] **Warning exit code:** [Exit Codes And Output Validation](#exit-codes-and-output-validation)
  deliberately uses a stronger rule than suggested: exit 0 plus requested
  output presence. Exit 1 always fails extraction, even when output exists.
- [x] **Tests wording:** [Tests](#tests) now adds fake pipe/pty fixtures and
  explicit error-policy, size, count, publication, and warning regressions.

These checks resolve design feedback, not implementation acceptance. Native
26.03 progress capture and the specified application tests have not been run
as part of this documentation revision.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Ready to begin extraction/progress implementation, but not a full
  safety approval for shared Move changes. The readiness check below found a
  concrete pre-existing data-loss path in the archive-to-archive bridge. A
  narrow scope decision is needed before changing its shared Move dependency.

#### Remaining Safety Gate

**[P1] A temporary extraction destination is not the final transfer commit.**
Current `MoveBetweenArchives` in
[zip.py](../src/main/resources/base/Plugins/Core/core/fs/zip.py) prepares a Move
from the source archive to a temporary directory, then a Move from that
directory to the destination archive. Source deletion therefore precedes final
packing. If destination packing fails or is canceled, `TemporaryDirectory`
cleanup discards the staged copy after the source entry has already been removed.

The new archive-to-local Move composite is a dependency of this bridge. Its
guarantee that a published destination remains safe does not hold when that
destination is a temporary directory owned by an enclosing task. Merely changing
the bridge's progress budget to 300 does not resolve the dependency.

Before shared Move implementation, approve a narrow exception to the current
archive-to-archive redesign exclusion: require successful final-destination
publication before source deletion. Add regressions for destination packing
failure and cancellation that prove the original source survives and the only
remaining copy cannot be removed by temporary cleanup. No implementation or
scope expansion has been applied by this review.

An isolated probe ran the actual `MoveBetweenArchives` composite with mock
transfer tasks for both `OSError` and `Task.Canceled`. Both confirmed the order
extract-to-temp, delete-source, fail-final-packing, followed by removal of the
temporary directory. No real archives were modified; this establishes the
control-flow risk, not a native archive-corruption test.

Separate residual risk: source-archive mutation is not application-level
transactional recovery. Deferring Cancel avoids deliberately interrupting an
update, but does not guarantee recovery after process failure, power loss, or
storage failure. Copy/Unpack preserve the source archive and have a lower-risk
failure model. Stronger archive-update recovery remains a distinct design choice.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: User approved the narrow archive-to-archive Move safety exception
  and implementation, prioritizing correctness over speed. Design now requires
  destination copy/verification before deletion and source-change rejection.
  Implement Archive Transfers first; the separate Unpack command remains pending.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Author review aligned the implemented four-phase cross-archive
  budget, source/output hashing, link/root rejection, separate verification
  staging, and deferred empty-parent restoration with the design. Recorded
  concurrency and crash limitations rather than claiming transactional safety.
  Native and Qt focused checks pass; unavailable checks are listed below.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Addressed all five runtime follow-ups from the implementation review
  in this document, as requested. Retained production verification under the
  user's correctness-first constraint; added two safety regressions and the
  requested multi-item cost measurement. No separate task document was created.

#### Runtime Feedback Resolutions

The original review and its checkboxes remain unchanged as history. These are
the current dispositions, not an acceptance of every proposed optimization.

- [x] **Source fingerprint without full hashing: rejected.** A stat-only
  fingerprint misses a valid same-size archive rewrite with its mtime restored.
  `test_move_rejects_source_rewrite_with_unchanged_stat` proves the existing hash
  detects that case and retains the changed source entry after publishing the
  old contents. Extracted-output verification alone cannot detect this source
  divergence. Keep hashing enabled, without an opt-out that weakens safety.
- [x] **One archive read per item instead of two: rejected as proposed.** A
  hash after `d` is too late to authorize that deletion. A cached post-delete
  fingerprint can be a baseline for the next item, but a pre-delete comparison
  is still needed to detect changes during its extraction. Keeping both checks
  means one post-delete and one pre-delete hash per item in steady state, not
  one read. Skipping the pre-delete hash loses the protection exercised above;
  cross-task state propagation would add complexity without the claimed saving.
- [x] **Single output verification: rejected.** Same-volume rename preserves
  the staged file, but the published path is externally writable before source
  deletion. `test_move_rejects_changed_published_output` changes it immediately
  after publication and confirms the current second hash retains the source
  archive byte-for-byte. Removing that hash changes failure behavior. Retaining
  it reduces risk; it still does not close the documented later race.
- [x] **Measure before and after: accepted as a baseline measurement.** Added
  `test_multi_item_move_verification_cost` beside the existing 8 MiB timing test.
  It records per-item time and actual bytes returned to Python hash reads,
  asserting two source-archive scans and two output scans. Results are below.
  There is no optimized implementation, so no before/after speedup is claimed.
  Total 7-Zip I/O and physical-disk reads remain unmeasured. A roughly 2x
  wall-time multiplier cannot be inferred from scan counts alone.
- [x] **Leave cross-archive verification unchanged: accepted.** Destination
  re-extraction and content comparison remain mandatory before source deletion;
  the existing success/failure regressions pass in the affected module run.

No production change is needed for the accepted items. The private error-type
layering observation remains non-blocking; no relocation or unrelated refactor
was made. README and CHANGELOG already describe the retained application
behavior and are unchanged for this documentation/test-only follow-up.

## Implementer

### 2026_09_16 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented bounded pipe progress/cancellation, staged extraction,
  verified dependent Moves, mandatory-stop source-update failures, and Windows
  non-overwriting directory publication. Final focused run: 161 tests, OK with
  four expected privilege skips. Unpack command is not part of this implementation.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review; approved. Independently re-ran the exact
  focused command from Tests: 161 tests, OK, 4 expected symlink-privilege
  skips (110 s); native `-bsp1` capture printed `['  0%', '100% 1']`, 7Z/TAR
  smoke 0.14 s each. Verified against the design in `core/fs/zip.py`,
  `core/fileoperations.py` and `core/fs/local/__init__.py`: all eight
  Follow Up Tasks from my design review are implemented as resolved -
  `_7zipError` translated to `OSError(EIO)` at the `Extract`/`AddToArchive`
  boundary with chaining; `ArchiveUpdateError(OSError)` caught before generic
  `OSError` in `FileTreeOperation.__call__` with an unconditional stop; fixed
  sizes 100/200/200/400 with no nested `set_task_size`; `MoveOutOfArchive`
  is one prepared root so `_enqueue` counts one transfer; `Extract` uses
  `Popen` with `-bsp1 -bse1 -y -spd -i!`, `pty=False`, strict exit
  (`allow_warning=False`) and `Popen.kill()`; `progress_records` splits on
  `\r`, `\n` and `\b`, bounds records to 4,096 characters and the queue to 16
  chunks, polls `check()` every 100 ms, and its `finally` kills/waits/joins;
  `LocalFileSystem._rename` uses `os.rename` for Windows directories and keeps
  `Path.replace` for files with notifications after success only; output
  existence plus path-traversal guard (`resolve().is_relative_to`) before
  publication; `_cleanup_extraction` retries three times and preserves the
  primary error via `add_note`. Deferred cancellation during `d`/`a` is
  implemented by `cancellable=False` with the `Canceling after archive update
  finishes...` label. Observations, no action required: (1) `_archive_state`
  SHA-256 hashes the whole source archive twice per moved item; since 7-Zip
  `d` already rewrites the whole archive per item, this is a roughly 2x
  constant on an existing O(items x archive size) pattern, not a new
  complexity class, and README documents the deliberate cost. (2)
  `Extract(verify_output=True)` hashes the extracted tree before and after the
  same-volume rename; the second pass guards only against a race on the
  published path. (3) `core.fs.zip` now imports `core.fileoperations` for
  `ArchiveUpdateError`, inverting the fs-to-operations layering; acceptable
  for a private Core type but worth moving to `core.fs` if it grows.
  Corrected the `Plan.md` regression noted in Validation Results: the
  `Pane Filter Patterns` entry was stale after that task's rename and now
  points to [FilterFiles001](FilterFiles001.md). Completion in `Done/` and
  the CHANGELOG/README entries are consistent with the implemented change.

#### Follow Up Tasks

Run-time improvements derived from observations (1) and (2). None changes
user-visible behavior or the verification of extracted output; all stay inside
`core/fs/zip.py`. Track them in a separate task document (for example
`Plan/ArchiveTransfers002.md`) when picked up.

- [ ] **Source fingerprint without full hashing.** `_archive_state` SHA-256s
      the entire source archive twice per moved item. Change the default
      fingerprint to the stat identity already computed
      (`st_dev, st_ino, st_size, st_mtime_ns`) and drop the content hash, or
      keep hashing behind a private opt-in. Accepted trade-off to record: a
      same-size, same-mtime in-place rewrite of the archive between the two
      checks is no longer detected; extracted output remains verified.
- [ ] **One archive read per item instead of two.** If hashing is retained,
      have `UpdateArchive` hash the archive once after its own `d` and pass
      that state to the next `MoveOutOfArchive` in the same
      `FileTreeOperation`, so each item costs one read (of data 7-Zip just
      wrote, likely cached) rather than a pre-extract and a pre-delete hash.
- [ ] **Single output verification.** `Extract(verify_output=True)` hashes the
      staged tree, renames it on the same volume, then hashes the published
      path again. Drop the post-rename hash; the rename moves the same inodes
      and the second pass only guards a millisecond race on the destination.
- [ ] **Measure before and after.** Extend the existing 8 MiB timing sample in
      `test_zip` with a multi-item Move (for example 20 files out of a 64 MiB
      ZIP) and record per-item wall time and bytes read, so the change is
      justified by numbers rather than reasoning.
- [ ] **Leave cross-archive verification unchanged.** Re-extraction in
      `AddToArchive(for_move=True)` is the only proof that the destination
      archive holds the packed entries; it is not a run-time target.

### 2026_09_16 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Added two fault-injection regressions using real archive transfers
  and one 20-item timing/read-count test in the existing `test_zip` module.
  Production code is unchanged. All 79 tests in that module passed with no
  skips; measurements and scope limitations are recorded below.

## Validation Results

- Ran the exact combined focused command in [Tests](#tests) on final code:
  **161 tests in 109.604 seconds, OK (skipped=4)**. The four skips were existing
  Windows symlink-privilege checks: local delete/stat of links and Copy/Move
  symlink cases. No elevation or package installation was attempted.
- Incremental checks ran immediately after substantive edits. Final staging-name
  regression first reproduced `FileExistsError`, then passed after separating
  packing and verification paths. Exact post-fix command:

  ```powershell
  python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip.ZipFileSystemTest.test_move_directory_named_like_verification_output', 'core.tests.fs.test_zip.ZipFileSystemTest.test_move_between_archives_verification_failure_retains_source', '-v'], env=build._environment()))"
  ```

  Both tests passed; the final combined run includes them.
- Real 7-Zip 26.03 ZIP progress emitted `  0%` and `100% 1`. Native extraction
  cancellation and a separate quiet Python child were terminated and reaped;
  tests checked closed streams, staging cleanup, and reader teardown.
- ZIP transfers, cross-archive files/folders/empty directories, literal `@`
  names, aliases, source changes, verification failure, and cancellation after
  deletion through empty-parent restoration passed. 7Z and TAR extraction smoke
  tests compared tree digests, taking 0.156 s and 0.161 s in the final run.
- An 8 MiB ZIP timing sample took 0.186 s for baseline extraction and 0.333 s
  for staged/verified extraction with matching digests. This is one local sample,
  not a throughput benchmark or a speedup claim. It excludes full Move hashing
  and archive mutation. Buffer bounds were tested structurally, not via RSS.
- The offscreen Qt test used the actual modeless progress dialog and a Qt timer
  to cancel a quiet worker. The parent stayed enabled; no modal widget appeared.
- Editor diagnostics: no errors in the seven changed Python implementation/test
  files. Documentation structure and moved task links were checked separately.
- An index-wide link check found the pre-existing missing
  `Plan/PaneFilterPatterns.md` target in `Plan.md`. That unrelated entry was not
  changed; task-scoped completion-link checks exclude it.
- Not run: interactive full-application two-pane/drag-and-drop inspection,
  privileged symlink cases, large-archive RSS/throughput measurements, release
  packaging, or Process Monitor Registry checks. These are not claimed as
  validated. No full suite, clean, freeze, new environment, or installation ran.

The automated completion gates pass with the stated expected skips. Manual and
release observations above remain unverified; no exclusive-lock, all-metadata,
whole-selection rollback, or crash-recovery guarantee is made.

### Runtime Feedback Validation - 2026_09_16

Exact commands run from the repository root, in order:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip.ZipFileSystemTest.test_move_rejects_source_rewrite_with_unchanged_stat', 'core.tests.fs.test_zip.ZipFileSystemTest.test_move_rejects_changed_published_output', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip.SevenZipExecutableTest.test_multi_item_move_verification_cost', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'core.tests.fs.test_zip', '-v'], env=build._environment()))"
```

- First two regressions: 2 passed in 0.444 s immediately after their addition.
- Multi-item measurement: 1 passed in 8.040 s immediately after its addition;
  measured Move time was 7.940 s, excluding fixture setup and test assertions.
- Final affected module: **79 tests in 115.678 s, OK, no skips**. Existing
  cross-archive verification, source mutation, cancellation and 7Z/TAR extraction
  tests also passed. Editor diagnostics reported no errors in the changed test.
- Only the test module and this document changed. The prior Qt/local/transfer
  checks above were not rerun because production code is unchanged. No full
  suite, clean, freeze, installation, or new environment was used.

The following sample is from the final module run. The ZIP initially contains
twenty 3 MiB selected files and one retained 4 MiB file, stored without compression
(64 MiB payload plus ZIP headers). Each row times one real Move, including
hashing, extraction, publication and archive update. The counting wrapper adds
test overhead. Output contents, the retained source entry and temporary cleanup
are asserted outside the measured interval.

Read counts are logical bytes returned by file reads inside `_tree_digest`,
not inferred file sizes, physical-disk traffic, or 7-Zip subprocess I/O. Both
hash counts are also checked against the expected current file sizes. No
cold-cache control or timing threshold is used.

| Item | Seconds | Source Hash Bytes | Output Hash Bytes |
| --- | ---: | ---: | ---: |
| 00 | 0.462 | 134221892 | 6291456 |
| 01 | 0.449 | 127930240 | 6291456 |
| 02 | 0.448 | 121638588 | 6291456 |
| 03 | 0.430 | 115346936 | 6291456 |
| 04 | 0.433 | 109055284 | 6291456 |
| 05 | 0.428 | 102763632 | 6291456 |
| 06 | 0.402 | 96471980 | 6291456 |
| 07 | 0.395 | 90180328 | 6291456 |
| 08 | 0.397 | 83888676 | 6291456 |
| 09 | 0.416 | 77597024 | 6291456 |
| 10 | 0.399 | 71305372 | 6291456 |
| 11 | 0.410 | 65013720 | 6291456 |
| 12 | 0.400 | 58722068 | 6291456 |
| 13 | 0.362 | 52430416 | 6291456 |
| 14 | 0.384 | 46138764 | 6291456 |
| 15 | 0.347 | 39847112 | 6291456 |
| 16 | 0.346 | 33555460 | 6291456 |
| 17 | 0.345 | 27263808 | 6291456 |
| 18 | 0.348 | 20972156 | 6291456 |
| 19 | 0.314 | 14680504 | 6291456 |
| Total | 7.914 | 1489023960 | 125829120 |

Total time uses unrounded samples. This baseline confirms substantial logical
read amplification but does not establish an optimization benefit. Safety
checks remain enabled; future performance comparisons must preserve them or
obtain explicit approval for weaker guarantees.
