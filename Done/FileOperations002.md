# File Operations 002: Robocopy Plug-In

Status: Implemented locally on 2026-10-08 after the user's approval of native
Robocopy policies. The bundled public-API plug-in, destination-only wizard, owned process,
progress, logs and user documentation are implemented. Focused native and Qt checks
pass, with the symlink-privilege skip and environment-specific delivery checks
explicitly recorded below. No Core transfer or refresh implementation changed.

Implementation reviews I1-I8 and S1-S4 were addressed on 2026-10-08; see
[Review Fix Validation Results](#review-fix-validation-results) for the 46-test
Windows gate and seven offscreen checks. The unrelated Everything changelog
deletion remains unconfirmed and was not reversed.

The user subsequently clarified that plug-in architecture does not mean separate
installation: Robocopy must be part of the application. The current distribution
decision below supersedes the earlier standalone-installation decisions; historical
review and implementation records remain unchanged.

## Task

Offer **Copy with robocopy** and **Move with robocopy** for the active pane's
selection, falling back to its highlighted entry. A destination-only QuickSearch
wizard defaults to the opposite pane. Run Windows' Robocopy with cancellable
progress and a concise outcome, without replacing normal Copy/Move.

Motivation: give users a fast native alternative for copying files and folders,
especially large selections, directory trees and network transfers. Keep the
wrapper lean: select operands, launch Robocopy, show progress and report outcomes.
Do not rebuild Core's transfer policies around it. Measure speed rather than
promise that every workload is faster.
Normal same-volume Move may remain much faster because it can rename instead of
copying bytes. This is separate from [FileOperations001](../Done/FileOperations001.md)
and the small-buffer experiment.

## Scope

- One bundled plug-in named **Robocopy**, repository source directory
  `src/main/resources/base/Plugins/Robocopy` and unique Python package
  `robocopy_plugin`. Keep third-party-style public-API boundaries while shipping
  it automatically like the other feature plug-ins. No Core integration, custom
  loader or special PyInstaller payload rule. Remove older manual user copies
  before using the bundled version; preserve settings and logs.
- Command IDs `copy_with_robocopy` and `move_with_robocopy`, with the exact aliases
  above. No default shortcuts, interception of F5/F6, or additional commands.
- Windows local-drive and UNC filesystem files/directories from one captured pane
  folder. Reject virtual/archive/process locations rather than resolving them into
  a wider or different operation. Include selected hidden entries and empty folders.
- The wizard asks only for a destination. Approximate progress is acceptable;
  tuning belongs in JSON settings, not additional wizard questions.
- Optional native Unicode logs and automatic post-transfer viewing are settings,
  not wizard questions. No in-app log viewer or additional command is required.
- Follow Robocopy's native directory merges, overwrite comparisons, skipped files
  and source-removal behavior. No added conflict confirmation, forced recopy or
  recursive destination audit. Explain these attributes in user-facing documentation.
- Keep pane-refresh scheduling, models, public APIs and Core's copier unchanged.
  No refresh flags, bulk-operation IDs, rate limiting or per-file pane notifications.
- Exclude mirroring, destination cleanup, elevated/backup mode, arbitrary switches,
  scheduled monitoring, pause/resume UI, unattended queue persistence, undo,
  filesystem-provider replacement and copying via a shell.
- This command deliberately has Robocopy's copy/skip/overwrite/move semantics,
  not Core's staged-replacement or destination-object isolation guarantees.
  Writes through destination links can affect aliased data outside the lexical
  target. This is a documented native-policy consequence, not protection supplied
  by a link-exclusion switch or a successful exit code.

## Design

### Ownership And Integration

Use public [command, pane, settings and Task APIs](../PlugIn.md), `fman.url` and
`fman.ui.UiController`/`UiOwner`/`settings_resource`, plus the standard library.
Do not import `fman.impl`, Core or another plug-in. The independent
[Batch File Renamer](../plugins/BatchFileRenamer/batch_file_renamer/__init__.py)
is a reference for public command capture and tests, not a runtime dependency.

Standard source discovery loads the package from bundled resources. The existing
PyInstaller resource rule collects the same tree for frozen builds; `build.py`
includes its directory among development plug-in import paths. Keep one canonical
package, not an additional runtime copy under `plugins/Robocopy`. The original
independent installation and separate packaging alternatives are superseded by
the user's distribution clarification.

Implemented internal ownership, keeping responsibilities separate without a generic
transfer framework:

- Package initializer: expose the two `DirectoryPaneCommand` classes and an
  `UiController` owner carrier; wizard, invocation lifetime and result presentation.
- Engine module: immutable request/job/result records, settings validation,
  path/selection validation, argv batching and exit classification.
- Windows process helper: owned native process/pipes, cancellation, bounded output
  and handle cleanup. It contains no Qt code or file-operation policy.
- Log module: exclusive Unicode files, append validation and completion-only retention.
- `Robocopy.json` and README: defaults, installation, behavior and limitations.

The `UiController` subclass is an owner carrier only. The loader assigns its owner
and commands call `require_owner()`; they never call `show()` or `build()`. The
current loader and public examples support an empty subclass for this route.
The `build()` method is needed only for the separate Qt-hosted window route.

Use `settings_resource('Robocopy operation').try_claim()` for a single shared
operation lease across both commands and plug-in reloads. Acquire it before the
wizard. Reject a second invocation with a short status message; do not queue it.
Release only after the child and reader have stopped, including cancellation.

### Destination Wizard

1. Capture `get_chosen_files()`, active folder, opposite pane's path, and immutable
  settings on the command worker. Empty selection/cursor reports an error. Since
  public reads are separate calls, validate that every captured entry belongs to
  the captured folder; reject a navigation race rather than mixing two locations.
2. Seed `show_quicksearch(..., query=...)` with the opposite pane's native absolute
   folder when it is a supported filesystem location. Otherwise start empty and
   require the user to type a destination; never silently choose another folder.
3. Keep "Use this path" first, reflecting the exact draft, with the captured
  opposite folder as an optional additional suggestion. Do not suggest the active
  folder, which maps selected entries onto themselves. The query callback only filters
   strings: no directory enumeration, network probing or filesystem checks on Qt.
   No persistent history or dependency on Favorites is required in V1.
4. Accept the chosen path, or the query text when acceptance returns `(query, None)`.
   Cancellation (`None`) or an empty path makes no filesystem changes. Preserve
   spaces; validate rather than silently trimming or correcting the path.
5. Validate off Qt and report invalid input without starting a transfer process.
  Enter starts the selected Copy/Move using the documented Robocopy policy.
  No additional conflict confirmation, switch page or policy warning wizard is
  added. Native behavior belongs in the plug-in README; the picker stays focused
  on the destination and identifies the selected command.

Require an absolute drive/UNC destination directory path, existing or creatable.
Reject relative/drive-relative paths, application URLs, wildcard/NUL/CR/LF input,
device namespaces and alternate-stream syntax. Accept spaces and Unicode.
The user may navigate either pane afterward; that does not retarget the captured
request. Pane destruction or owner invalidation cancels the invocation.

### Exact Selection And Jobs

Capture and validate all selected roots before the first job. Deduplicate identical
entry paths, retain exact spelling, and reject unsupported selected entries rather
than silently dropping them. Do not use snapshot display identity as permission to
mutate files. Recheck each job's selected roots immediately before launching it.

| Selected Entry | Source Argument | Destination Argument | File Arguments / Traversal |
| --- | --- | --- | --- |
| Loose files in the active folder | Active folder | Chosen destination | Explicit names only; no `/S` or `/E` |
| A directory named `Photos` | Active folder / `Photos` | Destination / `Photos` | Recursive `/E`, including empty directories |

Robocopy copies a directory's contents. Appending the selected directory's name to
the destination preserves the normal selected-folder behavior rather than flattening
its contents into the destination. File operands are not directory operands.

Group loose filenames into the largest argv batches that fit a **24,000 UTF-16
code-unit** budget, including the executable, roots, quotes, escaping, options and
terminator. Measure `subprocess.list2cmdline(argv)` encoded as UTF-16LE; do not split
by a fixed file count or manually quote arguments. Reject a single operand that
cannot fit before any mutation. Never launch an empty file batch: Robocopy would
otherwise default to `*.*`. Exact-selection tests must include names with spaces,
Unicode and leading punctuation. No user-supplied wildcard file operands.

Native probes returned exit 16 for loose filenames beginning with a hyphen, including attempts
using relative or absolute file operands. V1 refuses these selected loose filenames before
mutation; it does not widen masks or introduce shell/job-file escaping workarounds.
Hyphen-named directories use full-path folder jobs and are supported.
Spaces, Unicode, extensionless names, brackets and `@` prefixes passed native tests.

Build one recursive job per selected directory. Robocopy enumerates that tree;
do not materialize every descendant into Python jobs. Process file batches first,
then selected directories in captured order. All jobs execute sequentially; `/MT`
controls parallelism inside the single active Robocopy process.

### Path Validation And Native Policy

- Refuse source/destination equality and directory copies/moves into themselves
  or descendants, including aliases. Compare canonical existing ancestors and
  available identities, not just string prefixes. Missing destination suffixes
  are checked against their nearest existing ancestor, without creating them.
- Reject selected symbolic links/junctions and linked source roots in V1. Use
  explicit `/XJD /XJF` for nested source directory/file exclusions; verify file
  symlinks, directory symlinks and junctions separately. This is source-selection
  scope, not destination isolation. Refuse a source case if the selected flags
  cannot keep native traversal within the supported source scope.
- Allow existing destination folder merges and native in-place overwrites.
  The reviews reproduced writes through a nested destination junction and an
  existing multi-linked destination file despite `/XJ`. Accept those native effects
  under the user's clarified policy; `/XJD /XJF` are not claimed to prevent them.
  Do not require absent folder targets or add a recursive destination/link-count
  inspection to emulate Core. Documentation must explicitly say that destination
  links and hard-link aliases can affect data outside the displayed target path.
- Do not treat sparse/cloud files as ordinary links solely because the reparse
  attribute is set. Require a deliberate tested policy for offline/placeholder
  behavior; do not promise universal placeholder support from the initial probes.
- Reject unknown top-level identity when it prevents proving non-overlap. An
  access error is an error, not proof that a destination is absent.
- Query `FileCaseSensitiveInfo` for loose-file source folders and refuse
  known case-sensitive folders. Errors 1, 50 and 87 mean the query is unsupported,
  not proof of case-insensitive semantics; other errors propagate. Stream the
  immediate folder's primary/alternate names once using Win32 enumeration for
  both supported and unsupported queries. Retain only selected-name matches;
  reject aliases, missing names and conservative uppercase/casefold collisions.
  This includes short aliases without `~`; no tilde-only heuristic is used.
  Do not silently deduplicate distinct captured names or claim this snapshot locks
  a remote filesystem against later changes.
- Resolve the shared source/destination ancestry once. Keep selected-root metadata
  capture/rechecks and cheap identity checks for existing destination files.
  Selected directories retain their per-root canonical subtree checks. The ctypes
  API is initialized lazily once per module, not once per file.
- These checks are not locks or protection against hostile concurrent path changes.
  Other applications must not edit the participating files during a move.

### Robocopy Invocation And Settings

Resolve the Windows system `robocopy.exe` from the system directory, not PATH or the
current directory. Use native argument serialization with no `cmd.exe` and no
`shell=True`. Do not download, bundle or replace Robocopy. Resolve/probe support
only after destination acceptance, during cancellable preparation; wizard
cancellation starts no probe process. An unavailable executable or required option
fails clearly. Verify supported options without transferring data.

Resolve the executable with standard-library `ctypes` `GetSystemDirectoryW`.
Probe required options using `/L` between two owned empty temporary folders via
the same job-owned runner, after wizard acceptance. This is not a user-tree prepass.
Use bounded runtime/cancellation and native return codes rather than localized
help parsing; the reviewer observed an unknown switch returning 16.

Read `Robocopy.json` at invocation and freeze the validated values for the run:

| Setting | Default | Validation / Effect |
| --- | --- | --- |
| `threads` | `8` | Integer 1-32; `/MT:n` |
| `retries` | `1` | Integer 0-10; `/R:n` |
| `retry_wait_seconds` | `1` | Integer 0-30; `/W:n` |
| `restartable` | `false` | Boolean; opt into `/Z` |
| `unbuffered` | `false` | Boolean; opt into `/J`, mainly for large files |
| `log_enabled` | `false` | Boolean; save one Unicode log for the complete transfer |
| `open_log_on_finish` | `false` | Boolean; open the finalized log on completion, failure or user cancellation; requires logging |
| `log_retention_count` | `20` | Integer 1-100; retain the current and newest completed plug-in logs |

Reject invalid types/ranges, including booleans as integers. No unrestricted argv,
job-file input or executable override in V1. Store changes only through the existing
portable settings mechanism; no Registry writes or wizard settings pages.
Reject `open_log_on_finish=true` when logging is disabled rather than silently
enabling disk writes. Ignore retention operationally when logging is off: no log
directory creation, enumeration or cleanup on that path.

Host-controlled invocation policy:

- `/COPY:DAT`: native data/attribute/time behavior, including Robocopy's alternate
  stream handling. No `/COPYALL`, `/SEC`, `/SECFIX` or owner/audit copying. This is
  intentionally not identical to Core's metadata/stream behavior.
- Loose-file batches use `/NODCOPY` so source-root directory attributes are not
  transferred to the destination, particularly when copying from a drive root.
  Directory jobs use `/E` and `/DCOPY:DAT`; verify the latter's supported behavior.
- Use `/XJD /XJF` for the tested source-selection policy; never add `/SL` or `/SJ`
  implicitly and never claim destination-object protection from these switches.
- Bound retries explicitly rather than accepting Robocopy's very large defaults.
- Keep summary output and request `/NP /UNICODE /FP /BYTES`. Approximate job
  progress does not need the interleaved per-file percentages removed by `/NP`.
  The implementation spike must establish the actual pipe encoding and CR/LF
  behavior. Never assume localized words or concurrent percentages form a stable
  machine-readable protocol.
- The local spike found mixed ANSI/UTF-16 pipe records despite `/UNICODE`.
  The bounded pipe tail is decoded best-effort for diagnostics only. Native
  `/UNILOG+` output was valid UTF-16 across sequential jobs without embedded BOMs.
- Forbid `/MIR`, `/PURGE`, `/REG`, `/B`, `/ZB`, monitoring/scheduling flags and any
  switch that widens the captured selection. Traversal and move switches are not
  user-configurable tuning settings.

Existing matching files may be skipped using Robocopy's metadata comparison;
older sources may overwrite newer destinations without Core's conflict dialogs.
Do not add `/XO`, `/IS`, `/IT` or `/IM` to change that native policy in V1. This is
not content-hash verification. The user-facing documentation must disclose native
merges, skips, newer-file replacement, destination alias effects and partial output
after interruption. No staging, verification or rollback guarantee is added.

### Move Semantics

Both commands share planning, runner and result handling. Only the engine mode
differs: loose-file Move jobs use `/MOV`, directory Move jobs use `/MOVE` on the
selected directory root, never on the active pane folder merely to move some files.
Do not widen enumeration to unselected source siblings or purge unrelated
destination entries. This lexical selection scope is not destination-object
isolation: native writes can affect hard-linked or redirected targets.

Let Robocopy perform its own source removal. Never follow a batch exit code with
Python deletion of all selected sources. In particular, code 0 or metadata equality
is not independent proof of byte equality or permission for additional deletion.
The Opus probe established that `/MOV` can return 0, leave the source present and
leave different destination contents unchanged when size/time match. Retain that
native skip behavior rather than forcing `/IS /IT`; report it instead of claiming
every selected item moved. The remaining native tests cover failed overwrites,
missing sources, excluded source links and cancellation.

After each Move job's process cleanup, use non-following metadata checks on its
captured selected roots, O(roots), to report present, absent and uncheckable roots
with at most ten examples. Remaining/uncheckable roots prevent an all-moved claim;
a surviving directory means a remaining subtree, not a precise remaining-file count.
This is reporting only: no Python deletion, content hash or recursive walk. Check
owner/cancellation state between calls; on shutdown skip further reporting. A blocked
network metadata call is not bounded by the process-cancellation polling interval.
Root disappearance alone does not prove copy success under concurrent edits.

Robocopy can leave a partially moved selection: some sources removed, others
retained, and a partial destination file. Report partial/failure/canceled outcomes
truthfully; do not roll back successful jobs or promise source retention after a
file was already moved. Retrying the entire selection is an explicit new user action.

### Process Lifetime And Cancellation

One command worker coordinates one child at a time. Own the process with a private
Windows Job Object configured to terminate members when its last handle closes;
the job handle must not be inherited. Start the child suspended, assign it to the
job, then resume, so failure to establish ownership occurs before transfer work.
Use standard-library `ctypes` `CreateProcessW` with `CREATE_SUSPENDED`,
`EXTENDED_STARTUPINFO_PRESENT` and `CREATE_NO_WINDOW`. Retain the primary thread
handle for `ResumeThread`; `subprocess.Popen(CREATE_SUSPENDED)` is not sufficient
because it closes that handle. Use `STARTUPINFOEXW` with a
`PROC_THREAD_ATTRIBUTE_HANDLE_LIST` limited to child pipe ends; parent pipe ends
and the job handle remain non-inheritable. Declare typed signatures and close the
attribute list and all pipe/thread/process/job handles on every failure path.
Test failed assignment/resume and nested jobs on Windows CI. No pywin32 dependency,
elevation or system policy modification is added.

A single operation-scoped reader drains the merged output pipe in bounded chunks.
Use a bounded diagnostic tail (64 KiB) and status line (512 characters), retaining
only the latest progress/activity text. Output overflow drops old diagnostic text,
not pipe draining; the UI must never block the child through pipe backpressure.
The optional disk log below is independent of the 64 KiB in-memory diagnostic
tail; logging does not require retaining every output record in Python memory.

The reader uses `PeekNamedPipe` and reads no more than the available bytes, with
a 50 ms event wait while empty. After the owned process is reaped, it drains a
fixed available-byte snapshot and exits even if an unrelated process inherited a
writer during startup. The lease is still held until the reader actually stops.
This avoids synchronous-read cancellation races and extra thread-handle ownership;
it is not a hard bound on stalled kernel calls. Decode the tail once per activity tick.

The worker checks `Task.check_canceled()` and its owner/pane cancellation event
while waiting for process/output, targeting a 100 ms polling interval, not a hard
OS termination guarantee. Cancellation stops the owned job, waits/reaps the child,
closes streams and joins the reader off Qt before releasing the shared lease.
No later job starts. If shutdown stalls, show a stopping state and retain ownership;
do not report success or admit a replacement operation while the old process lives.

Owner invalidation and pane-close callbacks only set the cancellation event and
request cleanup; no Qt-thread join. Parent exit/crash closes the job handle and
terminates its child even if Python callbacks cannot run. `finally` covers all
normal failures and `Task.Canceled` (which is not an `Exception`).

### Progress And Outcomes

Use one public `Task` and `submit_task` from the command worker. No plug-in-created
Qt widgets, new panel or new public progress API is needed.

- Preparation uses indeterminate progress. Do not run `/L` or recursively walk
  all source files merely to calculate a precise total; the user accepts approximation.
  Use `Task.set_size(0)` for the existing busy bar and verify it in `RobocopyIT`.
  The empty-folder option probe is separate from transfer-size discovery.
- For multiple jobs, count completed Robocopy invocations, equally weighted:
  `Job 2/7 (approximate)` plus Copying/Moving, elapsed time, and captured job details.
  The bar describes completed jobs, not bytes/files; a directory can be much larger
  than a loose-file batch. Do not treat one file's `100%` as an entire job's progress.
- For a single large job, use an indeterminate activity bar and engine status text
  rather than inventing an overall percentage. Display captured folder/file details
  instead of raw native columns. Cancellation remains available.
- Once cancellation is requested, stop routine activity text/progress updates so
  they cannot overwrite the host's `Canceling...` message; continue pipe draining.
- Finish only after process exit, output drain and result classification. A failed
  or canceled run never displays an unconditional success result.

Classify each native exit separately: 0-7 mean no reported native copy failure,
not that every requested entry was transferred. They carry different
copied/skipped/extra/mismatch information; 8 or higher is a failure. Codes are
bitfields, not counts to add. Stop remaining jobs on failure or an unrecognized
termination; preserve earlier results. Surface mismatch/extra information without
claiming every selected file was copied or content-verified. Combine native status
with cancellation and Move remaining-root information; exit 0 alone cannot mean
"all moved". Unknown file counts remain unavailable, not fabricated zeros.

An obtained native exit/tail is returned and recorded, including its log entry,
before checking late cancellation. Cancellation then stops root reporting and later
jobs; Move explicitly counts roots not checked rather than discarding the receipt.
Extra-only exit bits use status reporting, while mismatches, failures, cancellation
and remaining/uncheckable Move roots retain alerts.

Present a single-line status on success/no changes containing completed jobs, native
flags and the last exit code. Do not put log paths, raw output or multi-line reports
in the status bar. Warnings, failures and cancellation retain bounded detailed alerts
and optional logs; distinguish unavailable counts from zero. Result presentation must
not create an unbounded list of all transferred paths. On owner invalidation or
application exit, suppress late dialogs and still clean up the owned process.

Progress has two concise lines: Copying/Moving, approximate job index when relevant
and elapsed `mm:ss`, then the selected file count or folder name. Folder labels are
middle-shortened to 28 characters for display only; source paths are unchanged.
This avoids the raw tab-separated columns and partially decoded filenames shown
by the earlier implementation. Native output remains diagnostic/log data only.

### Optional Transfer Log

The user reconfirmed that both logging and automatic opening stay disabled by
default after reporting that no log opened. With those defaults, no log is created
or opened. Enable both settings explicitly to request external viewing; existing
enabled-log cleanup and viewer behavior are unchanged.

Example settings, with no change to the destination wizard:

```json
{
  "log_enabled": true,
  "open_log_on_finish": true,
  "log_retention_count": 20
}
```

1. After destination acceptance and validation, choose a fixed-format timestamp
   and random ID for one `.txt` file in `DATA_DIRECTORY/Local/Robocopy/Logs`.
   Include this exact log path in every job's serialized 24k argument budget.
   Create it exclusively only after the empty-folder option probe succeeds.
   Logging requested but unavailable is reported before the first user-data job.
2. Use native `/UNILOG+:<path>` and `/TEE` for every sequential job. Initialize one
   UTF-16LE BOM, append bounded job headers between child processes and a final
   outcome after reaping. The plug-in closes its writer before Robocopy writes.
   Native append/BOM behavior is a feasibility gate, not an assumption; do not
   launch another job on an unreadable or incompatible log format.
3. The log contains operation type, captured roots, validated arguments, job
   boundaries, native output/codes, cancellation/failure status and Move root
   outcomes. Paths/filenames are intentional; do not dump credentials, environment
   variables or unrelated settings. No fixed user-supplied log path or raw logging
  switches. Reject symlink/name-surrogate log directories/candidates rather than following
  them. Non-redirecting cloud-placeholder tags alone are allowed, matching source
  metadata policy; actual cloud hydration remains unverified. Refuse a generated log location overlapping any selected source tree
   or destination tree: the transfer must not copy, move or overwrite its own log.
4. Keep draining the status pipe independently of log success. If a log failure is
   detected after transfers begin, stop later jobs, retain completed transfers and
   report the logging failure separately. Do not retry mutation to recreate a log.
   Footer/viewer failures must not turn confirmed transfers into "nothing copied".
   Native output can grow large: the retention count bounds file count, not bytes.
   Disk-full, forced exit or cancellation can leave an incomplete log; never call
   it complete merely because the in-memory tail exists.
5. Finalize/close the log after child reaping and reader shutdown, close the Task
   progress dialog, and release the operation lease. If `open_log_on_finish` is true
   and the invocation's owner/pane is still active, use standard-library
   `os.startfile` to open exactly that `.txt` in the user's associated text viewer.
   Open once on completion, warnings, failure or user cancellation. Do not open on
   wizard cancellation, owner invalidation or application exit. Catch missing-file
   or association errors, keep the log and report its path; no Core editor import
   or new configured executable is needed. A launched viewer may remain open.
6. Before releasing the operation lease, prune only older generated regular logs
   in the owned directory to the configured count, keeping the current file. Never
   delete unrelated files, open/current logs from this process or reparse entries.
   Retention failure is a bounded warning, not transfer failure. Pruning runs only
   after a logging-enabled operation, never on startup, idle or settings load.

Order within finalization is: reap/drain, write outcome and close log, prune older
logs, close progress, release the lease, then optionally open the current log.
The empty-folder option probe should include native logging options with a separate
temporary log, never this user-visible transfer log. Its artifacts are removed.

### User-Facing Documentation

Maintain [the plug-in README](../src/main/resources/base/Plugins/Robocopy/README.md)
for users, not just implementers.
Lead with the motivation: **a fast native alternative to copy or move selected
files and folders through Windows Robocopy**, without changing normal F5/F6.
The root application README links to usage and native behavior. Explain automatic
availability in new builds and removal of any earlier manual plug-in copy.

Required sections and concrete examples:

- Installation, the two command names, selection-to-highlight fallback, the
  destination-only wizard and the opposite pane's default. A mixed-selection example
  shows two files copied to the target and `Photos` copied into `target/Photos`.
- Native behavior: existing folders merge; older sources can overwrite newer
  destinations; metadata-equal files can be skipped without content comparison;
  Move may leave skipped sources. No extra conflict dialogs, verification, automatic
  retries of the whole selection or Python source deletion.
- Links and interruption: source-link exclusions are distinct from destination
  links. Destination junctions/symlinks can redirect writes, and hard-linked
  destinations can change their other aliases. Cancellation/error may leave a
  partial destination and a partially moved selection; no Core-style staging or undo.
- Settings, defaults and trade-offs: thread count, bounded retries, restartable and
  unbuffered I/O; large/unknown totals use approximate job progress or an activity
  bar. Normal same-volume F6 can be faster than native copy/delete.
- Logging: the example above, portable location, one log across batches, automatic
  opening on enabled terminal outcomes, retention count, potentially large files,
  path/filename privacy and incomplete-log/error behavior. Show how to read the
  native return code and remaining Move roots without treating code 0 as all moved.
- State supported/refused source locations and unverified Windows/network cases.
  Keep policies in the README, not new wizard pages or repetitive warning dialogs.

### Pane Refresh And Persistence

Robocopy writes externally and does not call host notifications per file. On every
terminal outcome, use public pane APIs to request normal reloads of still-live panes
displaying affected source/destination locations. Inspect their current locations:
do not navigate them back, restore a stale selection or refresh only the originally
opposite pane if the user moved elsewhere. Account for displayed descendants and
ancestors whose direct child was created or removed. Do not claim completion of a
reload from the return of its nonblocking API; use `reload(on_done=...)` if needed.

This does not modify refresh scheduling or suppress host events. Intermediate
external changes are not promised to appear continuously; progress is in the Task
dialog. Normal application-activation refresh remains unchanged. A destination not
shown in a pane needs no forced navigation or background model scan.

No persisted queue or resumable runtime state. Optional logs are the only new
operation artifacts. Load plug-in settings lazily; use the shared resource for
the operation lease. Settings and logs stay in portable `UserSettings`.
Host cache invalidation and deletion of a displayed moved directory must be checked
with the real public-API integration tests, not assumed from a mocked `reload()`.

## Alternatives

- Replace Core Copy/Move or change pane-refresh logic: rejected; the user wants an
  explicit independent plug-in and rejected refresh changes as too risky.
- One process per file: rejected; loses batching and adds substantial startup cost.
- Multiple concurrent Robocopy processes: deferred; one child with `/MT` is simpler
  for disk contention, progress, cancellation and ownership.
- A single whole-folder invocation for arbitrary selected files: rejected; omitted
  operands/recursive switches could include unselected entries.
- Exact byte-total progress with a `/L` prepass: deferred; doubles discovery and
  delays startup. Job-level approximation/activity is sufficient for V1.
- Custom job files or unrestricted user switches: deferred; quoting, scope and
  deletion behavior become harder to validate. Bounded argv and typed settings win.
- Python copy-verify-delete around Robocopy: rejected for V1; extra I/O and new
  deletion policy would obscure the explicit native Move behavior.
- Forced `/IS /IT` recopy, `/XO` protection, absent-target-only directory copies
  and an extra overwrite confirmation: not selected after the user explicitly
  chose native Robocopy policy. Document and report those native outcomes instead.
- Recursive destination link/hard-link inspection: not selected for this fast
  native alternative. It adds discovery I/O and still does not lock paths; remove
  the unsupported isolation promise rather than imply `/XJ` solves it.
- Raw `/LOG` switches, custom log locations and an in-app viewer: not needed for
  V1. Generated Unicode logs with optional default-association opening provide the
  requested access without more host APIs or wizard controls.

## Runtime Effects

- Disabled/uninstalled: no jobs, I/O, scans, timers, child processes or recurring
  signals. Installed but unused: lightweight command/owner registration only; no
  executable probing or settings/network discovery at import time.
- Invocation: capture O(selected roots) plain data and build O(file batches plus
  selected directories) jobs. Do not enumerate descendants for planning/progress.
  Cancellation checks cover long selection validation and batching.
- Name validation adds one streaming immediate-folder enumeration, O(source-folder
  entries) work with O(selected roots) retained memory. Partial selections in very
  large folders still pay this scan. It replaces per-file long-path resolution;
  shared loose-file canonical ancestry is O(1), with per-entry identities retained.
- Each loose-file batch can re-enumerate source and destination directories, so
  cost grows with batch count times folder entries. Opus's list-only 10k-file probe
  took 0.42 s for one `*` job versus 1.96 s for seven explicit-name batches. This is
  reviewer evidence, not implemented throughput. Do not substitute `*` for a partial
  selection to avoid that overhead.
- Steady transfer: one coordinator, one bounded pipe reader and one native process,
  with 1-32 Robocopy threads. Python memory is selection/jobs plus bounded diagnostics,
  not all descendant files. Windows/Robocopy caches and memory are not capped by that.
- I/O is native copy/metadata work plus bounded retries. `/Z` and `/J` are opt-in;
  their performance depends on storage and file size. Do not predict speedups from
  Core's small-buffer or pane-refresh experiments.
- Cancellation can leave completed and partial filesystem changes. Cleanup waits
  off Qt; OS/network stalls can exceed the polling interval. No automatic rollback.
- Move outcome reporting adds O(selected roots) metadata reads, not a recursive
  verification scan. Native destination merge/alias effects remain part of the
  documented policy; there is no extra Python source-deletion pass.
- Logging off adds no feature-specific disk I/O. Logging on adds native log writes,
  bounded headers/footer and completion-only retention enumeration, plus an optional
  external viewer launch. A full log is not constrained by the RAM-tail bound and
  may be large; no truncation or performance-equivalence guarantee is implied.
- Completion reloads only relevant live panes through existing APIs. No new idle
  polling, file watchers, recurring refresh scheduler or Registry writes.

## Tests

The modules/classes below now exist. Their exact executed checks and remaining
environmental gates are recorded in the final Validation Results section.
Tests use existing unittest/Qt helpers and temporary copies of the user plug-in, following
the [independent plug-in tests](../src/integrationtest/python/fman_integrationtest/impl/plugins/test_plugin.py)
and [test-only import helper](../src/unittest/python/fman_unittest/batch_file_renamer_fixture.py).
Do not load writable configuration from the repository's plug-in source directory.

### Native Feasibility Gate

Before implementing the complete UI, use disposable data to establish:

1. Loose-file filters leave unselected files/subdirectories intact; `/E` preserves
   selected directory names and empty folders. Mixed jobs and forced-small argv
  budgets retain exact scope, including Unicode, spaced and punctuation names,
  case-only siblings and 8.3 aliases. Refusal is required where exact native
  matching cannot be guaranteed.
2. `/MOV` and `/MOVE` retain the agreed native policy for same-metadata/different-
  content files, newer destinations, failures, source links and empty roots.
  Verify remaining-source reporting. Reproduce destination junction/hard-link
  effects as documented native outcomes, not as isolation passes. Stop adoption
  if source enumeration widens beyond the supported selected scope.
3. Pipe Unicode/CR records, `/MT` interleaving, quiet waits and exit codes can be
   consumed without hangs or invented progress. Job ownership works unelevated,
   during cancellation and inside a Windows runner's enclosing job.
4. Two sequential jobs append to one readable Unicode log with both native
  summaries and the plug-in outcome. Probe BOM/encoding, cancellation, large
  output, log creation/write failure and no-lock handoff to the viewer. Option
  probes use only empty temporary roots and a separate temporary log.

Historical review sections retain their original probe scope. Implementation checks
now cover the owned launcher, wizard, progress and local native contracts; they do
not certify every Windows version, privilege configuration or network environment.

### Unit And Regression

`fman_unittest.test_robocopy`: immutable capture/settings, command IDs and
aliases, destination draft/empty-result acceptance, exact argv serialization and
24k UTF-16 budget, no empty batches, directory job paths, case/alias/descendant
refusal, safe settings allowlist, exit bitfields, bounded diagnostics, cleanup and
no-op paths. Use fake processes for startup failure, assignment failure, pipe errors,
quiet cancellation, failed later jobs and lease retention until reaping.
Cover native skip/remaining-root classification, draft-first suggestions without
the active folder, case-sensitive-folder refusal, log path budgeting/overlap,
exclusive creation, append order, settings combinations, retention and disabled
zero-I/O. Verify owner invalidation suppresses late presentation without losing
cleanup, and that viewer errors do not change the recorded transfer outcome.

```powershell
python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_robocopy','-v'],env=build._environment(),timeout=120).returncode)"
```

### Integration

`fman_integrationtest.test_robocopy_engine`: real small temporary trees,
copy/move selection parity, same-volume and simulated failures, bounds/retries,
empty folders, attributes/streams, source-link exclusions, documented destination
alias effects, native skip/overwrite semantics, partial cancellation and no orphan
process/reader. Hash source/destination fixture bytes outside any measured interval.
Real second-volume/UNC behavior is separate; mocks do not certify those environments.

`fman_integrationtest.test_qt.RobocopyIT`: temp-copy plug-in discovery/unload,
both commands and mutual exclusion, real QuickSearch default/typed path/cancel,
responsive progress/Cancel, thread affinity, pane navigation/destruction, owner
invalidation, terminal status and affected-pane refresh without stale navigation.
Verify `set_size(0)` produces a busy bar, late output cannot replace cancellation
text, and the empty owner carrier does not call `show`/`build`. Mock `os.startfile`:
opening must follow log/progress closure and lease release, exactly once, and never
follow wizard cancellation or unload. Check the retained log after viewer failure.
Repeat the same focused class offscreen for CI-style validation.

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_robocopy_engine','fman_integrationtest.test_qt.RobocopyIT','-v'],env=env,timeout=180).returncode)"
```

### Performance And Manual

- Opt-in performance procedure: reuse the existing flat 10k x 4 KiB and tree
  1k x 8 KiB [Copy fixtures](../src/performancetest/catalog.yaml), three alternating
  Core/Robocopy repetitions in fresh processes and isolated settings. Include real
  selection, destination acceptance, first file, completion and final pane state;
  retain command options and failures. Verification/setup/cleanup are untimed.
  Agree the runtime budget before adding a runner/workload; do not alter regular
  `measure`, its report, or historical definitions to add this plug-in.
- Include one explicitly budgeted partial selection, such as 128 files from the
  existing 10k flat folder, to expose per-batch enumeration overhead. Report batch
  count and selection/setup separately from transfer time. Logging on/off is a
  separate comparison if requested; do not multiply the regular catalog implicitly.
- Before large-file/network claims, separately run a declared disposable large-file
  case and a real UNC copy/cancel/reconnect case. Before Move certification, test
  an actual second volume; compare same-volume behavior with normal F6 without
  promising Robocopy wins. Record exact counts/bytes, options, storage and timings.
- Manual: Windows 10/11 and a non-English locale; deep/Unicode paths; default and
  manually typed destinations; selection of folders from a drive root; very large
  selections; unavailable shares; cancellation and closing the application mid-run.
- Manual documentation examples must match native folder merges, newer-destination
  overwrite and Move skips. Check logging off/on, non-English logs, default viewer
  association, retention failures and a canceled transfer's incomplete log.
- Packaging smoke: install the single plug-in into an existing portable host using
  isolated writable settings; run both commands without development Python paths,
  third-party packages, admin rights or bundled Robocopy. No automatic freeze.
- The public API, standard F5/F6 behavior and refresh scheduler must remain unchanged.
  Full suite/build/release validation runs only when separately requested.

## Implementation Steps

1. Review the clarified native policy, user-documentation requirements, approximate
  progress and optional logging. Resolve remaining feasibility gates before enabling
   mutation commands; no silent policy change if a probe disagrees.
2. Add the independent plug-in skeleton and pure planner/settings tests. Verify
   exact selection and bounded arguments before launching a real process.
3. Implement the owned Windows runner, bounded output and cleanup, testing Copy
   first and then native Move failure/cancellation cases through the same runner.
4. Add both commands, destination-only QuickSearch and public Task integration;
  verify owner/lease lifecycle, Move root reporting, ordinary terminal pane refresh
  and optional logs with post-cleanup viewing.
5. Add the user-facing README sections above and brief application README linkage;
   add the implemented feature to the changelog. Do not bundle it or add Core hooks.
6. Run focused unit/native/Qt tests and the agreed optional measurements. Document
   expected skips and outstanding delivery checks. Complete provenance and move
   this canonical task to Done only after implementation and acceptance review.

## Acceptance Criteria

- One automatically loaded, bundled **Robocopy** plug-in exposes both exact commands.
  Normal Copy/Move, shortcuts and pane-refresh internals are untouched.
- Selection falls back to the highlighted entry; cancellation of the destination
  wizard creates no files, directories or child process. The opposite filesystem
  pane is the default, with no switch questions.
- File batches contain only selected source names; selected folder trees retain
  their names/empty folders; large selections split by serialized command length.
  Do not widen source enumeration or purge unrelated destination entries. Native
  destination alias effects are explicitly not an object-isolation guarantee.
  Invalid captured paths fail before the first mutation.
- Settings expose only documented tuning. No Registry, elevation, mirror/purge,
  monitoring, arbitrary job-file or raw-switch route exists.
- Visible progress is honest about approximation; Cancel stops the owned child
  and prevents later jobs. All terminal paths reap/close resources before releasing
  the lease. Nothing runs when the plug-in is unused.
- Native Move semantics and partial outcomes are proven on disposable fixtures;
  native skips and remaining/uncheckable roots prevent all-moved claims even with
  exit 0. No forced recopy or extra source deletion is inferred from exit codes.
- Existing destinations may use native in-place overwrite; user documentation
  must include replacement of newer files, skipped Move sources and destination
  aliases. No extra conflict wizard; do not imply Core's staged publication,
  destination-object isolation or content-verification guarantees.
- Logging is optional, portable and one file per transfer across all jobs. Disabled
  logging performs no log-directory work. Enabled post-transfer viewing opens once,
  after cleanup, not on wizard cancellation/unload. Logs cannot overlap transfer
  roots; retention/viewer failures never trigger mutation retries or false outcomes.
- The implemented plug-in README explains the native policies and logging with
  examples; the destination wizard has no new switch or confirmation pages.
- Real public-API tests show final affected pane state without per-file refresh
  traffic or navigation changes. All required focused checks pass, and unrun
  environment/delivery checks remain explicit rather than implied approvals.

## Reviewers

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Designed one independent Robocopy plug-in with both requested commands,
  destination-only QuickSearch, settings-only tuning, bounded sequential jobs,
  approximate progress and explicit native Move/overwrite limitations. Public
  host APIs and the Microsoft Robocopy reference were consulted. Independent
  review, native feasibility and implementation remain pending; no runtime change.

Reference: [Microsoft Robocopy documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/robocopy).

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 872K
- Outcome: Design sound in scope, ownership, lease, cancellation and refresh.
  Two P1 decisions before implementation: Move keeps "same" files with exit 0
  (D1) and Copy replaces newer destinations with older sources (D2), both
  reproduced. D3 (suspended start needs ctypes) and D4 (per-batch rescans)
  belong to the feasibility gate. No repository code changed.

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 1M
- Outcome: Request changes. Four bounded native probes show that /XJ does not
  prevent writes through a nested destination junction or an existing hard-linked
  destination file. Both Copy and Move modified unselected target data with exit
  code 1; Move also removed its selected source. Resolve the destination policy
  before implementation. Scope, explicit commands and process ownership remain
  appropriate; no application code changed. See Design Review 2.

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Addressed D1-D7 and S1-S2 under the user's clarified fast native-copy
  motivation: preserve Robocopy merge/overwrite/skip policies, document alias and
  partial-Move effects for users, and add no conflict wizard. Specified the ctypes
  launcher, honest progress/outcomes and optional Unicode logs with post-cleanup
  viewing. The conversation assigned 1M; preserve historical metadata. No plug-in
  implementation or fresh native certification is claimed.

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Implementer acceptance check confirms the selected native policies,
  public-only integration, bounded jobs, process ownership and optional logs.
  Local Windows and offscreen gates pass. This is not an independent implementation
  review or release/platform certification; the privilege skip and unrun checks
  remain explicit. Historical Opus/Sol records and their dispositions are unchanged.

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 872K
- Outcome: Request changes. Loose files from a UNC share always fail: the
  case-sensitivity query returns WinError 50 (I1, reproduced through the
  loopback share). Planning 10,000 files takes 5.2-12.0 s before the first job
  (I2). Process ownership, native policies, logs and lease handling match the
  design; the focused gate passes (37, one skip). See Implementation Review.

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 1M
- Outcome: Request changes. Fresh bounded probes confirm UNC loose-file rejection,
  cleanup blocked by an unrelated inherited pipe writer, and loss of completed
  job outcomes on late cancellation. Small-selection call counts confirm repeated
  planner path queries. Native baseline: 37 tests, 36 passed and one expected
  privilege skip. The approved destination/native policies are not reopened;
  no application code changed. See Implementation Review 2.

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Implementer verification resolves I1-I8 and S1-S4 with focused
  regressions and aligned runtime/documentation policy. Unsupported case queries
  use fresh name/alias validation, not an unconditional false result; tilde-only
  alias detection was rejected. The owned reader drains a fixed exit snapshot
  rather than releasing a live thread after a timeout. Native policies remain
  unchanged. This is not an independent re-review; environment limits and the
  unconfirmed unrelated changelog deletion remain explicit.

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Applied the user's distribution clarification: preserve plug-in API
  independence but include Robocopy in the application, using the same resource
  layout and loader as other bundled features. No special loader, duplicate
  source tree, Core hooks or shortcut changes. Packaging/discovery and Qt command
  registration are the focused acceptance checks; no freeze is required here.

### 2026_10_08 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Reviewed progress/status presentation against the supplied screenshot.
  Raw native columns do not belong in the progress label, and the multi-line
  diagnostic report does not belong in the status bar. Chose bounded captured-job
  labels and a dedicated single-line completion summary using existing public
  Task/status APIs. The user explicitly retained disabled optional-log defaults.
  Native styled captures and geometry checks validate the presentation; no shared
  widget, refresh, transfer-policy or logging-default change is needed.

## Review Resolution (2026_10_08)

This revision follows the user's decisions after reviewing D1/D2 and S1/S2:
an explicit fast Robocopy alternative using native policy, with those attributes
in user-facing documentation. It does not claim to fix Robocopy's behavior.

| Finding | Disposition |
| --- | --- |
| D1: same-file Move skips | Keep native skips; do not force `/IS /IT`. Report remaining/uncheckable selected roots, and never equate exit 0 with all moved. No extra deletion. |
| D2: older source replaces newer target | Native overwrite is intended. Document it; no `/XO` or extra confirmation page. This is not a limitation of interactive integration. |
| D3: suspended launch | Specify ctypes `CreateProcessW`, `STARTUPINFOEXW`, an explicit inherited-handle list, retained thread handle, Job assignment and resume/cleanup tests. |
| D4: per-batch enumeration | Record the observed cost and add an opt-in partial-selection comparison. Keep explicit selected filenames; do not silently replace them with `*`. |
| D5: progress/cancel text | Require `Task.set_size(0)` coverage and stop ordinary activity updates after cancellation. Progress remains approximate. |
| D6: active-folder suggestion | Remove it; keep typed draft first and the captured opposite path as the default. |
| D7: flags/probe/case/naming | Use `/XJD /XJF`, `/NP`, an empty-folder `/L` option probe and explicit source case-sensitivity checks. Name the product Robocopy consistently. |
| D7: owner `build()` | No change required: the loader assigns `UiOwner` without calling `build`; public examples use an empty controller for owner-only services. This plug-in never calls its `show()` route. |
| D7: attribution | The user explicitly assigned GPT-6 Astra, Extra High, 1M in this conversation. That session assignment takes precedence over the reusable prompt's 272K; no historical record is rewritten. |
| S1: nested destination junction | Accept/document native destination traversal under the user's policy. Remove the unsupported isolation promise; no destination audit or absent-target-only restriction. Source selection and overlap checks remain. |
| S2: hard-linked destination | Accept/document that native in-place overwrite changes aliases. Do not present `/XJ` or a successful exit as isolation. Normal Core Copy/Move remains unchanged. |
| Optional log request | Add logging, open-on-finish and retention settings, generated portable Unicode logs across all jobs, and user-facing usage/privacy/error documentation. |

Validation for this revision is document-level: all required sections, local links,
review IDs, settings, unchanged Pending index and preserved review history are
checked. The earlier reviewer probes remain attributed below; owned-process/logging
and platform tests remain planned, not newly passed.

## Design Review (2026_10_08, Opus)

Checked against [PlugIn.md](../PlugIn.md) (QuickSearch, Task, `settings_resource`,
`UiController`, `on_closed`), `ProgressDialog` in
[widgets.py](../src/main/python/fman/impl/widgets.py), command threads in
[command_registry.py](../src/main/python/fman/impl/plugins/command_registry.py)
and the local provider's no-op `watch`. Robocopy was probed with the system
`robocopy.exe` on disposable temporary folders. No repository code was changed.

- **D1 [P1] Move silently keeps "same" files.** Probe: equal size and time,
  different content. `/MOV` exited 0, kept the source and left the destination
  unchanged. The plan reads exit 0 as success, yet the file was not moved.
  With `/IS`, the file was copied and the source removed (exit 1).
  - Recommend `/IS /IT` for both Move modes. Each selected file is then copied
    before Robocopy removes it, matching the overwrite policy. Cost: files
    already present are copied again.
  - After each Move job, stat its selected roots (O(roots)). Report any that
    remain (locked, excluded links, failures) as partial. Reporting only; no
    Python deletion.
- **D2 [P1] Copy replaces newer destination files with older sources.** Probe:
  an older source overwrote a newer, different destination file (exit 1). Core
  asks first. The plan makes Enter the approval and discloses only "changed files".
  - Decision needed. Recommended: before the first job, stat each selected name
    at the destination (O(roots)). If any exist, show one bounded confirmation:
    count, first names, and that differing files are replaced, including newer
    ones. No per-file wizard and no switch page.
  - Alternative: a `skip_older` setting mapped to `/XO`. For Move it leaves
    older sources behind, so D1's report must cover it.
  - Add the chosen behavior to Acceptance Criteria and `RobocopyIT`.
- **D3 [P2] Suspended start is not reachable through `subprocess`.** `Popen`
  closes the child's primary thread handle, so `ResumeThread` is impossible.
  `STARTUPINFO.lpAttributeList` supports only `handle_list`, not a job list.
  Name the mechanism: ctypes `CreateProcessW` with `CREATE_SUSPENDED`, a
  `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` limited to the pipe ends, and a
  non-inheritable job handle. Test handle leaks and assignment failure.
  The build's `_run_restricted` shows the sequence with pywin32, which a
  standard-library plug-in cannot use.
- **D4 [P2] Each loose-file batch rescans the source folder.** Probe, list-only
  (`/L`) over 10,000 empty files: one `*` job took 0.42 s; seven 24k batches of
  1,588 names took 1.96 s. Each batch enumerates source and destination and
  matches its names, so cost grows with batches x folder entries. Add this to
  Runtime Effects. Add a partial selection from a large folder to the opt-in
  performance procedure.
- **D5 [P3] Indeterminate progress is undocumented.** `set_size(0)` becomes
  `QProgressDialog.setMaximum(0)`, a busy bar, so it works today. Document
  `set_size(0)` in PlugIn.md or cover it in `RobocopyIT`. After Cancel, the
  dialog shows `Canceling...` only until the next `set_text`; stop activity
  updates once cancellation is requested.
- **D6 [P3] The active folder is never a valid destination.** For loose files it
  equals the source. For a selected folder, `Destination\Name` is the source.
  Drop it from the suggestions, or offer it only through Tab completion. Keep the
  draft item first so Enter accepts the typed path.
- **D7 [P3] Minor.**
  - Use explicit `/XJD /XJF` instead of `/XJ`. Probe file symlinks, directory
    symlinks and junctions separately; Robocopy follows file symlinks by default.
  - Add `/NP`. Per-file percentages are noise with `/MT` and add CR-delimited
    output to drain.
  - Option probe: run the frozen switch set with `/L` between two empty
    temporary folders. Probe: `/NODCOPY /XJD /XJF /MT:8 /UNICODE` exited 0; an
    unknown switch exited 16. No localized help parsing is needed.
  - Detect case-sensitive source folders (`FileCaseSensitiveInfo`) and refuse
    loose-file batches there, instead of inferring from names.
  - Scope names the plug-in `robocopy`; `plugins/Robocopy` and `Robocopy.json`
    imply `Robocopy`. Use one name.
  - The `UiController` owner carrier still needs the required `build` classmethod.
  - Astra's record lists Context Window `1M`; [PRROMPT.md](../PRROMPT.md)
    assigns the developer `272K`. Confirm that session's assignment.

Verified:

- `/MOVE /E` on a selected folder removed the source root and kept its empty
  subfolder at the destination (exit 1).
- Each command runs on its own daemon thread, so a long run does not block other
  commands. Exit skips `finally`; the job's kill-on-close is the only exit cleanup.
- Local `watch` is a no-op. Panes do not refresh during the run, so the planned
  terminal reload is required.
- All required sections exist and the task is under Pending in [Plan.md](../Plan.md).
  The referenced test helpers and the `copy-flat-v1`/`copy-tree-v1` fixtures exist.

Recommendation: resolve D1 and D2 before implementation. Settle D3 and D4 in
the native feasibility gate.

## Design Review 2 (2026_10_08, Sol)

Request changes before implementation. The independent plug-in, destination-only
wizard, sequential jobs and explicit native semantics are appropriate. Two
destination-side cases contradict the selected scope and link-safety promises.
Source-root checks and a nonfailure Robocopy exit do not establish destination
isolation.

### Findings

- **S1 [P1] Nested destination junctions escape the approved destination.**
  Rejecting only linked source/destination roots does not protect entries below
  an ordinary destination root. A source `Photos/nested/report.txt` was copied
  through an existing `destination/Photos/nested` junction into an unrelated
  temporary folder, despite `/XJ`. Copy and Move both replaced that target's
  bytes and returned 1; Move then removed the source. Add an explicit nested
  destination no-traversal rule and native regression. `/XJD /XJF` must also be
  proved for destination behavior; they are not an assumed fix. If enforcing the
  rule needs recursive destination inspection, reconcile that with the current
  no-recursive-planning requirement before implementation. A narrower V1 that
  requires selected-directory destination subtrees to be absent is a credible
  alternative; validate their existing ancestors and document refused merges.
- **S2 [P1] In-place overwrite changes unselected hard-link aliases.**
  A selected loose file overwrote an ordinary destination file with two hard
  links. Its unselected alias in another temporary folder changed too. Both
  modes returned 1; Move removed its selected source. Hard links are not reparse
  points, so `/XJ` and symbolic-link/junction checks do not cover them. The promise
  that unrelated destination data stays untouched needs an explicit hard-link
  overwrite policy. Prefer refusing known multi-link destinations. Define how
  recursive jobs establish that policy without violating planning constraints,
  and how unavailable link-count information is handled. Otherwise explicitly
  seek approval to relax the isolation guarantee; do not imply staged replacement.

The earlier D1 skip/remaining-source decision still needs an agreed outcome policy.
Adding `/IS /IT` is not a fix for S1/S2: copying more files does not isolate writes.
For D2, warn explicitly that differing newer destinations can be replaced, but do
not silently add an extra wizard/confirmation page to the destination-only scope.
Any proposed confirmation or `/XO` policy remains a user decision.

### Validation Results

- Reviewed the Microsoft Robocopy reference and the current public API, snapshot
  reload/cache invalidation path and earlier design review. The source contains
  no Robocopy plug-in yet; its planned test names are not runnable regression tests.
- Four native probes ran through `python -B -` with the standard library only.
  Resolve `robocopy.exe` and `cmd.exe` using `GetSystemDirectoryW`, not PATH. Use
  separate `TemporaryDirectory` fixtures for Copy/Move and each alias case.
  Hard links use `os.link`; the directory junction uses system `cmd.exe /c mklink /J`.
  Only these disposable source/destination/alias fixtures were mutated.
- Common arguments: `/COPY:DAT /XJ /R:0 /W:0 /MT:8 /NP /UNICODE`. Loose-file jobs
  use an explicit `report.txt` operand and `/NODCOPY`; recursive jobs use `/E
  /DCOPY:DAT` on the selected `Photos` root. Move adds `/MOV` or `/MOVE`
  respectively. Give source/destination distinct contents and different fixed
  modification times so Robocopy copies rather than skipping. Bound each run to
  20 seconds, capture output through pipes, and compare actual bytes afterward.
  Remove the junction itself before disposing its temporary tree.

  | Destination case | Mode | Exit | Unselected target changed | Selected source remains |
  | --- | --- | ---: | --- | --- |
  | Hard-linked file | Copy | 1 | Yes | Yes |
  | Hard-linked file | Move | 1 | Yes | No |
  | Nested junction | Copy | 1 | Yes | Yes |
  | Nested junction | Move | 1 | Yes | No |

- The destination hard-link count remained two; the junction remained in place.
  These are reproduced failures of the proposed isolation contract, not passes
  of the native feasibility gate. No symbolic-link privilege was required.
- No plug-in implementation, full suite, benchmark, freeze/package, new dependency,
  private-settings/user-data inspection or Registry write. Real UNC/second-volume,
  non-English output, Windows-version coverage and suspended/job-owned launch
  remain unverified. No native process-lifetime certification is implied by these
  short `subprocess.run` observations.

## Implementer

### 2026_10_08 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Implemented [Robocopy](../src/main/resources/base/Plugins/Robocopy/README.md), using only public
  fman APIs and the standard library. Added immutable planning/settings, owned
  suspended Windows processes, bounded output, native Copy/Move, destination-only
  QuickSearch, progress/cancellation, terminal pane reloads and optional Unicode
  logs/retention/external viewing. No Core, refresh scheduler, packaging, dependency
  or shortcut changes. Final local gate: 37 tests, 36 passed and one privilege skip;
  all seven offscreen Qt tests passed. Documentation links/defaults and editor
  diagnostics passed. Source installation is documented, not performed in the
  user's live settings directory.

### 2026_10_08 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Addressed both implementation reviews: UNC loose files, shared planner
  work, late-cancel receipts, inherited-writer cleanup, hyphen folders, non-modal
  extra-only merges, placeholder-tag log policy and installation/site documentation.
  Windows gate: 46 tests, 45 passed and one expected symlink skip; all seven
  offscreen Qt tests passed. No Core, refresh, API, dependency or build change.
  No separate fixes entry was added for the unreleased plug-in; its existing
  changelog feature entry remains intact.

### 2026_10_08 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Moved the canonical Robocopy package into bundled resources and added
  its development import path. Existing discovery and PyInstaller resource
  collection now include it automatically; no special spec entry, Core change or
  plug-in implementation change was needed. Updated isolated loader tests,
  documentation, migration guidance and the Unreleased entry. Final focused gate:
  50 tests, 49 passed and one expected symlink skip; seven offscreen Qt tests passed.
  No freeze or live installation was performed; existing executables need rebuilding.

### 2026_10_08 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Replaced raw native progress rows with Copying/Moving, elapsed time and
  bounded captured-job details; successful completion uses a dedicated one-line
  status. Optional detailed logs and warning alerts remain intact. Confirmed both
  log defaults are still false and enabled log opening still passes its lifecycle
  test. Added unit and styled Qt geometry regressions, inspected two captures,
  and made the existing deleted-folder test await its public path-change event.
  Final native gate: 50 tests, 49 passed and one expected symlink skip; eight
  offscreen Qt tests passed. Root README edits were left untouched.

## Validation Results

### Focused Commands

From the repository root, using the existing `python` and `build._environment()`:

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_unittest.test_robocopy','fman_integrationtest.test_robocopy_engine','fman_integrationtest.test_qt.RobocopyIT','-v'],env=env,timeout=180).returncode)"
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.RobocopyIT','-v'],env=env,timeout=120).returncode)"
```

- Windows: **37 tests, 36 passed, one skipped**, 6.570 s in the final run.
- Offscreen: **7 passed**, 2.553 s. Expected Qt `propagateSizeHints` notices only.
- Expected skip: selected/nested symbolic-link test, Windows error 1314 (privilege
  unavailable). Native junction, hard-link, case-sensitive directory, 8.3 alias
  and alternate-stream tests all ran and passed; these are not symlink substitutes.
- Native scope: exact mixed selection and forced-small batches, empty directories,
  same-metadata Move skips, newer-destination overwrite, failed locked-target Move,
  source junction exclusions and documented destination alias effects.
- Lifetime/failure: failed Job assignment/resume, reader failure, handle counts,
  200k output into a bounded tail, quiet cancellation, nested Jobs and abrupt parent
  exit, stopped later jobs and retained partial Move changes.
- UI: real installed temporary plug-in, exact command IDs, real QuickSearch default,
  typed destination/cancel/cursor fallback, busy progress, mutual exclusion,
  navigation independence, real pane destruction, unload and final pane snapshots.
  A displayed moved directory uses the existing host reload fallback correctly.
- Logs: multi-job native Unicode append, exclusive creation, retention, malformed
  output, failures before/after copying, disabled no-I/O path, viewer failure and
  handoff after progress/lease closure. Logging-enabled unload finalizes without
  importing removed modules and never opens a late viewer.
- Earlier harness failures were corrected: construct command registries on Qt,
  and assert the public `Listing.names` field. Final runs had no worker tracebacks.
- A PowerShell check resolved each local Markdown link in the plug-in README,
  application README, changelog and task, and parsed the JSON defaults. The final
  task move also checks required sections, preserved reviewer signatures, one
  Completed index entry and absence of a second Pending copy. Editor diagnostics
  report no errors in the implementation, settings or changed Python tests.

### Remaining Environment And Release Checks

- Symbolic-link traversal with an account permitted to create those links.
- Real UNC copy/cancel/reconnect, unavailable-share stalls and second-volume Move.
- Windows 10/11 coverage, an actual CI runner's enclosing Job policy, non-English
  output, deep/very large selections, cloud/offline hydration and large-file I/O.
- Frozen portable-host installation without development paths and actual default
  text-viewer association. The automated viewer is mocked; native source transfers
  and temporary public-loader installation are real.
- Mid-file native copy interruption, application-close during a real large transfer,
  actual disk exhaustion and storage-failure behavior. Quiet-process cancellation,
  between-job partial Move and injected log failures are narrower evidence.
- No performance comparison or large/network throughput claim. The opt-in benchmark
  still requires an agreed runtime budget. No full suite, clean, freeze, build or
  release validation was run. No packages/environments were created or installed.

## Implementation Review (2026_10_08, Opus)

Request changes for I1; I2 is strongly recommended. The rest is sound: public
APIs only (no `fman.impl`, Core, Qt or pywin32 import), owned suspended launch
with a handle list and kill-on-close Job, bounded output, lease held until
reaping, native policies as approved, and logs finalized before the viewer opens.

### Findings

- **I1 [P1] Loose files from network shares always fail.** `windows.case_sensitive`
  raises when the filesystem does not support `FileCaseSensitiveInfo`. Through
  `\\localhost\C$`, the query raised WinError 50, so `prepare` refused a loose
  file with "The request is not supported." A folder from the same share copied
  (exit 1). FAT32/exFAT volumes probably fail the same way; none was available here.
  - Treat errors 1, 50 and 87 as "no per-directory case sensitivity". Keep
    refusing when the flag is set.
  - Add a mocked-error unit test, and a loopback-UNC native test that skips when
    the administrative share is unavailable.
- **I2 [P2] Planning is slow for large selections.** 10,000 selected empty files
  took 5.15 s to plan into a new folder and 12.02 s into a populated one, before
  any Robocopy job. Core Copy prepares the same flat case in 361 ms
  ([FileOperations001](FileOperations001.md)). A profile of 3,000 files puts 46%
  in `long_path` and 39% in `canonical`.
  - Loose files share one parent. Check the destination against the source
    folder once (canonical path and identity), not per file. Keep per-entry checks
    for selected folders.
  - Run the 8.3 check only for names containing `~`.
  - Build the ctypes API once per module. `api()` costs 39 µs per call, and
    `long_path` also allocates a 64 KiB buffer each time.
- **I3 [P3] A finished job can be reported as unfinished.** `run()` calls
  `check()` after the process exits, so a late Cancel drops the exit code. The
  summary then undercounts finished jobs and skips that Move job's root check.
  Record the code before checking for cancellation.
- **I4 [P3] `close()` joins the reader without a bound.** The pipe's write end is
  inheritable from `CreatePipe` until the parent closes it. An unrelated child
  that inherits handles in that window keeps the pipe open, so the join never
  returns and the lease stays held. The window is short. Bound the join after
  process exit, for example with `CancelSynchronousIo`.
- **I5 [P3] The hyphen rule also refuses folders.** Folders are passed as full
  paths. A folder named `-dir` copied correctly as a folder job (exit 1). Apply
  the rule to loose files only.
- **I6 [P3] Ordinary merges raise a modal alert.** Exit bit 2 (extra destination
  entries) counts as a warning, so copying a folder into a populated one shows an
  alert. Consider a status message when bit 2 is the only signal.
- **I7 [P3] Logs refuse any reparse ancestor.** `safe_directory` rejects every
  reparse attribute, including cloud-placeholder folders. Sources reject only
  name surrogates. A portable install in a OneDrive folder likely cannot log. Use
  the source rule. Not tested here.
- **I8 [P3] Documentation.**
  - The plug-in README installs to `Plugins/User/`. The docs site and the Batch
    File Renamer README use `Plugins/Third-party/`, which **Remove plugin** manages.
    Both folders load.
  - The root README says "Optimized for large transfers". No measurement backs it yet.
  - The documentation site does not mention the plug-in; Batch File Renamer has
    an entry in [Plug-ins](../docs/plugins/index.md).

Aside: the Unreleased `Fixed` entry for the Everything download fallback is no
longer in [CHANGELOG.md](../CHANGELOG.md). Confirm that was intended.

### Verified

- A Unicode log under a path with spaces received native output and stayed valid.
- Loose-file batches budget the quoted UTF-16 command, including the log switch.
  No empty batch is built.
- Cancellation, pane closure and unload stop the Job, reap the child and join the
  reader before the lease is released. The viewer opens after progress closure
  and release, and never after unload.
- Move reports remaining roots from O(roots) `lstat` calls and deletes nothing.
- The settings allowlist rejects booleans as integers, unknown keys and
  `open_log_on_finish` without logging.

### Validation Results

- Focused gate, native Qt (command in Validation Results): 37 tests, OK, one
  expected symbolic-link skip, 7.9 s.
- Probes in temporary folders: UNC loose file and folder through
  `\\localhost\C$`; a log path with spaces; a `-dir` folder job; planning time for
  10,000 files into new and populated destinations; a planning profile for 3,000
  files; the output-tail decode cost (3.4 ms per 100 ms tick).
- No source change, full suite, benchmark run, freeze or package.

## Implementation Review 2 (2026_10_08, Sol)

Request changes. The earlier destination-isolation findings were resolved by the
user's explicit native-policy choice, not by adding Core-style protections. This
review preserves that choice and confirms implementation defects identified by
the first implementation review with fresh, bounded checks.

### Findings

- **S1 [P1], confirms I1: supported UNC loose-file planning fails.**
  [case_sensitive](../src/main/resources/base/Plugins/Robocopy/robocopy_plugin/windows.py) unconditionally
  requires `FileCaseSensitiveInfo`. On the disposable loopback administrative-share
  fixture it raised WinError 50, so [prepare](../src/main/resources/base/Plugins/Robocopy/robocopy_plugin/engine.py)
  rejected one ordinary file before starting a job. A selected directory on the
  same share copied successfully with exit 1 and verified bytes. Resolve unsupported
  query handling and add a regression without treating every unknown remote case
  policy as proven case-insensitive. Preserve refusal for known case-sensitive
  loose-file locations and exact-selection guarantees.
- **S2 [P2], confirms I4: reader cleanup can wait on an unrelated process.**
  [OwnedProcess._start/close](../src/main/resources/base/Plugins/Robocopy/robocopy_plugin/windows.py) leaves
  its parent-side writer inheritable until startup finishes. A concurrent child
  launched with general handle inheritance can retain it outside the owned Job.
  The native probe confirmed the owned child had exited 0, but `close()` and its
  reader remained blocked; killing the unrelated fixture child released them.
  The active operation lease is therefore stuck for that unrelated process's
  lifetime, including after Cancel. Add a deterministic regression and an explicit
  way to cancel/finish the pending read after owned-process teardown. Do not simply
  time out the join and release the lease while the reader still runs.
- **S3 [P2], confirms I2: preparation repeats expensive per-file path work.**
  [prepare](../src/main/resources/base/Plugins/Robocopy/robocopy_plugin/engine.py) made 32 `long_path` calls
  and 64 canonical-path calls for 32 ordinary files sharing one source folder and
  one new destination. Source and destination canonical ancestry are invariant
  across those loose files; this reproduces the scaling surface behind I2's earlier
  multi-second timings, not a new speed measurement. Reduce verified redundant
  work while preserving source rechecks and short-name/identity safety. Do not
  assume all possible 8.3 aliases contain a tilde without validating that rule.
- **S4 [P3], confirms I3: late Cancel discards a completed native outcome.**
  [run](../src/main/resources/base/Plugins/Robocopy/robocopy_plugin/windows.py) checks cancellation after
  process reaping but before returning the code. A controlled cancellation set
  immediately after real cleanup left complete Copy/Move target bytes, yet the
  [task](../src/main/resources/base/Plugins/Robocopy/robocopy_plugin/__init__.py) recorded no exit code and
  reported `0/1 jobs finished; 1 remaining`. Move had already removed its source,
  but no root was checked. Preserve the obtained exit/tail before stopping later
  work, and explicitly label root checks skipped on cancellation rather than
  losing the completed job receipt. Add a deterministic boundary regression.

### Validation Results

- Fresh native baseline: **37 tests, 36 passed, one expected symlink-privilege
  skip**. No worker tracebacks. Exact focused command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_unittest.test_robocopy','fman_integrationtest.test_robocopy_engine','fman_integrationtest.test_qt.RobocopyIT','-v'],env=env,timeout=180).returncode)"
  ```

- Two bounded `python -B -` launchers ran probe scripts in child processes using
  `build._environment()` and `-B -X faulthandler`, with 90/30-second outer bounds.
  Both loaded temporary plug-in copies through `robocopy_fixture.plugin_module`;
  every source, destination and UNC path referred only to their disposable data.
- UNC procedure: expose the same temporary source through its loopback drive
  share, verify fixture access, call `prepare` for a loose file and for a selected
  folder, then run the latter through the actual owned runner with a 15-second
  bound. Loose-file planning reproduced WinError 50 with no destination created;
  the folder job returned 1 and its bytes matched. The share was accessible here;
  this is not arbitrary-server, disconnected-share or non-NTFS certification.
- Late-cancel procedure: skip only the empty-folder option probe, perform one real
  Copy or same-volume Move, wrap `OwnedProcess.close` to set the cancellation event
  after actual cleanup, then inspect task receipts and all fixture bytes. Both
  completed targets matched; only Move removed its source. Both reported no job
  codes, zero roots checked and one remaining job.
- Planner procedure: create 32 ordinary files, wrap `long_path` and `canonical`
  with call-count mocks, and prepare a new destination. Counts were 32 and 64;
  preparation created no destination. No large performance workload was added.
- Reader procedure: during owned startup, launch an unrelated quiet Python child
  with `close_fds=False` before forwarding the real `CreateProcessW`. Wait up to
  five seconds for the owned child to exit, start cleanup on a test thread and
  observe it still blocked after 300 ms. Terminate/reap the unrelated child;
  cleanup and reader shutdown then completed within the five-second check.
  All fixture processes/threads were reaped; no unbounded probe was left running.
- No application edits, full suite, large benchmark, new package/environment,
  live plug-in installation, freeze/package or user-data inspection. The approved
  native overwrite/alias effects remain intentional. Earlier symlink, actual
  second-volume, locale, cloud and frozen-host/CI delivery limits remain open.

## Implementation Review Resolutions (2026_10_08)

| Finding | Resolution And Evidence |
| --- | --- |
| I1 / S1: UNC loose files | Unsupported case-query errors 1/50/87 return unknown. Fresh primary/alternate-name validation still rejects ambiguous case matches and aliases; access errors propagate. Real loopback UNC Unicode Copy and Move pass, preserving unselected siblings. Other servers and FAT32/exFAT are not certified. |
| I2 / S3: repeated planning work | One immediate-folder name stream replaces all per-file long-path queries; shared source/destination canonical paths are resolved once. Existing-target file identities, source rechecks and directory subtree guards remain. The 32-file regression performs two canonical calls and one enumeration for both new and populated destinations. No tilde assumption or new throughput claim. |
| I3 / S4: late cancellation | Return and record the reaped native receipt and log entry before cancellation checks. Real Copy/Move tests cancel immediately after cleanup: completed bytes and exit 1 remain recorded, later jobs stay unstarted, and skipped Move-root checks are explicit. |
| I4 / S2: inherited writer hang | Availability-checked reads and an exit drain budget stop dependence on EOF from unrelated writers. Native regression leaks the writer to a live unrelated child and verifies cleanup/reader shutdown within two seconds without killing that child. No early lease release or abandoned reader. |
| I5: hyphen directories | Restrict the hyphen refusal to loose file operands. Real `-copy` and `-move` selected-folder jobs pass. |
| I6: merge alerts | Codes 2/3 use status reporting with extra-entry information. Codes 4-8, other failures and existing warning conditions retain alerts; presentation regression covers codes 0-8. |
| I7: cloud log ancestors | Allow non-name-surrogate reparse tags for log paths, retaining symlink/junction rejection. Retention skips all reparse candidates. Synthetic cloud-tag creation/append/finalization tests pass; this is not a OneDrive hydration test. |
| I8: documentation | Install under managed `Plugins/Third-party`, explain old User installations, remove the unmeasured optimization claim, and add a Robocopy entry to the documentation site's plug-in page. |
| Everything changelog aside | The entry was already absent at the start of this follow-up. Git was unavailable on PATH and at the checked installations, so deletion intent cannot be established. No unrelated release-note deletion was reversed; confirmation remains with the user. |

## Review Fix Validation Results

Exact final focused commands, from the repository root using the existing Python:

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_unittest.test_robocopy','fman_integrationtest.test_robocopy_engine','fman_integrationtest.test_qt.RobocopyIT','-v'],env=env,timeout=180).returncode)"
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.RobocopyIT','-v'],env=env,timeout=120).returncode)"
```

- Windows: **46 tests, 45 passed, one expected symlink-privilege skip**, 10.304 s.
- Offscreen: **7 passed**, 3.083 s; expected `propagateSizeHints` notices only.
- No worker tracebacks. Loopback UNC, native case-sensitive directory and 8.3
  tests actually ran. Placeholder-tag behavior and no-tilde alias/collision cases
  use injected metadata; real cloud hydration and custom remote case policies
  remain environment-specific checks.
- Edited Markdown links, managed installation path, site entry and removal of the
  performance claim passed a focused PowerShell check. Editor diagnostics are clear.
- No full suite, large benchmark, package/freeze, new environment/package or live
  plug-in installation. Other UNC/reconnect, second-volume, cloud, locale, actual
  viewer and frozen-host/CI checks remain unrun; earlier records retain their
  historical test counts and scope.

## Bundled Distribution Validation

The user-approved application inclusion supersedes earlier manual-installation
guidance. Robocopy now lives alongside the other bundled feature plug-ins in
`src/main/resources/base/Plugins/Robocopy`, preserving its public-API package and
both command IDs. Batch File Renamer's separate distribution was not changed.

- New packaging regression initially failed because bundled Robocopy was absent,
  then passed after moving the one package. It checks standard source discovery,
  the development import path and actual PyInstaller data expansion for defaults,
  documentation and all four Python modules. No special `application.spec` rule.
- Qt tests load an isolated bundled resource layout through the existing plug-in
  discovery/loader and confirm both command IDs, real wizard/transfer behavior,
  progress, pane refresh, cancellation and unload. They do not install a live user copy.
- Final commands:

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_unittest.test_robocopy','fman_unittest.test_app_name.BuildNamingTest','fman_integrationtest.test_robocopy_engine','fman_integrationtest.test_qt.RobocopyIT','-v'],env=env,timeout=180).returncode)"
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.RobocopyIT','-v'],env=env,timeout=120).returncode)"
```

- Windows: **50 tests, 49 passed, one expected symlink-privilege skip**, 11.314 s.
- Offscreen: **7 passed**, 2.900 s; expected Qt `propagateSizeHints` notices only.
- Editor diagnostics, moved-source Markdown links, automatic-availability guidance
  and the single canonical package location passed focused checks.
- No full suite, clean, freeze or actual frozen-binary run. Packaging tests inspect
  PyInstaller's collected payload without compiling an executable. Rebuild and
  restart an older executable to obtain the included commands in Command Center.
  F5/F6, right-click menus and native transfer policies are unchanged. Prior
  environment-specific runtime limitations remain as recorded above.

## Progress Presentation Validation

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_unittest.test_robocopy','fman_integrationtest.test_robocopy_engine','fman_integrationtest.test_qt.RobocopyIT','-q'],env=env,timeout=180).returncode)"
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.RobocopyIT','-v'],env=env,timeout=120).returncode)"
```

- Native: **50 tests, 49 passed, one expected symlink-privilege skip**, 11.816 s.
- Offscreen: **8 passed**, 3.048 s; expected Qt `propagateSizeHints` notices only.
- Styled Qt checks cover ordinary and long Unicode folder names, font-metric text
  fit, label/bar/button separation, unchanged width across activity updates,
  preserved Canceling text and a one-line status that does not resize the window
  or status bar. Two locally captured PNGs were visually inspected; no clipped
  columns or control overlap remained. These are synthetic layout captures, not
  timing or a fresh frozen-build test.
- The first Unicode layout assertion exposed a three-pixel overflow; reducing
  the displayed folder-name limit to 28 characters fixed the same check. An
  offscreen deleted-folder test exposed a reload timing race; it now waits for
  the public path-change event rather than inferring completion from model idle.
  No production refresh code changed.
- `test_log_viewer_after_real_progress_closure_and_lease_release` passes with both
  log options explicitly enabled. The external viewer is mocked. Log defaults
  remain off by the user's choice; no user settings were edited.
- Plug-in documentation links and unchanged JSON defaults were checked; editor
  diagnostics are clear. No full suite, freeze, package, dependency installation,
  root README edit or shared progress-widget modification. Rebuild older binaries
  to see the new presentation; prior environment-specific checks remain unrun.