# Code Review 010: Large-Selection Copy Startup

Status: Option A implemented with explicit user approval on 2026-10-06, following
all three independent reviews. B and status-capture optimization remain deferred.
On 2026-10-07 the user selected vanilla A as the sole production path. The bulk
transfer experiment was removed; its sources, measurements and history remain
preserved below. Move preparation into missing destination folders was fixed on
2026-10-07 without creating folders before preparation succeeds.
The benchmark was implemented and a tagged `0.14.0` baseline preserved before
application changes. The approximately 100 ms preparation stretch target was not met.
The current full-only workloads are 10,000 flat files at 4 KiB and a 1,000-file
tree at 8 KiB per file. Both measure Select All through copy completion. Earlier
15,000-file results are retained as historical references, not relabeled.

## Task

Make copying a large selection visibly start and remain cancellable without
weakening file-operation safety. Measure Select All separately; do not replace
the existing selection mechanism or couple status optimization to this task.

### Observed Problem

The user reported entering a folder with about 200,000 files, a roughly two-second
Select All, and apparently nothing happening after F5. Whether the destination
prompt appeared was uncertain.

Controlled tests used disposable data and isolated source-app settings. They did
not copy, modify or inspect the user's files. Results from those tests:

| Measurement                                      | Result                           |
| ------------------------------------------------ | -------------------------------- |
| Ctrl+A to repaint, real 200,000-file folder      | 7-11 ms, status bar disabled     |
| Retrieve 200,000 selected URLs                   | 55-58 ms                         |
| F5 to visible destination prompt                 | About 55 ms                      |
| After confirming: first 10,000 parent checks     | 10.15 s; no progress dialog      |
| Separate 1,000-file confirmation probe           | 18,000 native path resolutions   |
| Separate 1,000-file task gathering probe         | 1.06 s; 1,001 queued tasks       |
| Enabled status: build snapshot on Qt             | 218 ms                           |
| Enabled status: selection to completed status    | 446 ms                           |

The enabled-status test used 200,000 displayed rows and 5,000 real files for
size queries, matching the default size-query limit. It was not a second full
200,000-file status benchmark.

The copy probe deliberately stopped after 10,000 checks, before copying files.
At the measured rate, 200,000 checks would take about 203 seconds before progress
creation. This is an extrapolation, not a completed three-minute measurement.
The evidence explains a long silent preparation phase, not a proven deadlock.
The reported two-second Select All delay was not reproduced.

### Comparison Measurements

Three rotated runs copied ordinary 1 KiB files into empty destinations, using
the same existing copy provider. Medians:

| Files  | Approach                            | First File | Total    |
| ------ | ----------------------------------- | ---------- | -------- |
| 1,000  | Current implementation              | 2.039 s    | 3.056 s  |
| 1,000  | Option A: reduced batch preparation | 36.50 ms   | 1.006 s  |
| 1,000  | Option B: individual execution      | 1.57 ms    | 1.054 s  |
| 10,000 | Current implementation              | 19.340 s   | 27.487 s |
| 10,000 | Option A: reduced batch preparation | 361.76 ms  | 10.404 s |
| 10,000 | Option B: individual execution      | 1.16 ms    | 9.810 s  |

These were isolated prototypes, not implemented features. Every source and
destination byte was verified outside the timed interval. UI, pane refresh,
conflicts and nonlocal providers were excluded. Runs used warm caches; timings
are not guarantees for a full application or a 200,000-file transfer. The clear
advantage of B was time to the first file, not a proven throughput improvement
over A. These sizes remain historical evidence; they do not define the requested
current flat/tree workloads or predict their timings.

### Causes

- [_TreeCommand._confirm_tree_operation](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)
  calls `is_parent(selected_file, destination)` for every selected item after the
  prompt is accepted but before `submit_task` creates a progress dialog.
- [is_parent](../src/main/resources/base/Plugins/Core/core/util.py) walks all
  destination ancestors. Each `MotherFileSystem.samefile` resolves both paths
  again. The measured directory depth produced 18 resolutions per selected file,
  including repeated resolutions of the same destination ancestors.
- [FileTreeOperation._gather_files](../src/main/resources/base/Plugins/Core/core/fileoperations.py)
  repeats ancestry checking while gathering tasks. Fixing only the hidden first
  pass would improve feedback but leave expensive preparation.
- [PaneStatusWidget._calculate](../src/main/python/fman/impl/status_bar.py) calls
  [DirectoryPaneWidget.get_status_snapshot](../src/main/python/fman/impl/widgets.py)
  on Qt. That materializes selected URLs, a selection set and a status record for
  every displayed entry before worker processing begins. The size-query limit
  does not limit this Qt work. The Qt Select All operation itself was fast.

Both ancestor-check loops were inherited from upstream fman v1.7.5:
[confirmation](https://github.com/mherrmann/fman/blob/v1.7.5/src/main/resources/base/Plugins/Core/core/commands/__init__.py)
and [task gathering](https://github.com/mherrmann/fman/blob/v1.7.5/src/main/resources/base/Plugins/Core/core/fileoperations.py).

## Scope

- Copy and Move preparation for large selections, including F5/F6 and existing
  command entry points. Preserve destination prompts, overwrite decisions and
  same-file/descendant/link safeguards.
- Status-capture optimization is deferred to a separately approved task per E4/G4.
  Selection is measured, but the selection/status APIs and behavior are unchanged.
- Regression coverage and a catalogued copy workload in the existing on-demand
  performance suite, using disposable fixtures only. Benchmark creation is part
  of this task, not a suggested later exercise.
- Current benchmarks copy only: 10,000 flat files of 4,096 bytes and a deterministic
  tree of 1,000 files of 8,192 bytes. The tree has 10 root branches, 5 buckets per
  branch and 1-6 nested levels (360 directories total). No Move or 200,000-file
  copy benchmark is added.
- Exclude copy-engine replacement, parallel file copying, global path caches,
  new public APIs, new panels, archive/link-policy changes and unrelated cleanup.
- Do not inspect running applications, installed packages, private settings or
  user datasets to diagnose this task. Do not use the real CelebA folder.
- Keep Windows support, portable state under `UserSettings`, and existing
  plug-in compatibility. No dependencies, environments or Registry changes.

## Design

### 1. Shared Startup and Safety Rules

- Keep `_confirm_tree_operation` responsible for input and destination choice,
  not an unbounded selected-item validation loop for Copy/Move.
- After confirmation, enter the existing task/progress path immediately. Show
  `Preparing...` or copying progress as appropriate, with throttled updates.
  Verify actual dialog visibility, not merely object creation; its current
  normal display delay is about one second.
- Move pre-task destination creation inside the cancellable task. Cancellation
  before the first mutation must create/copy/move nothing. Later cancellation
  follows the chosen option's partial-completion rules below.
- Run application safety/policy checks before the operation they protect.
  Keep cancellation checks during validation, traversal and execution; an OS
  call already running cannot be forcibly cancelled. Neither option promises
  an atomic batch or predicts every permission, capacity or availability failure.
- `_TreeCommand` also serves Symlink. Do not blindly remove its shared guard:
  route only Copy/Move to deferred validation and retain other commands' behavior.
  Existing confirmation tests must move safety assertions to the task boundary,
  not simply delete those assertions.

### 2. Execution Options for Review

Both options remove repeated ancestor checks for positively identified ordinary
local files: a file cannot contain the destination directory. Reuse provider
metadata, not stale pane data. Keep same-file/alias checks, overwrite decisions,
safe publication and directory-descendant protections. Ambiguous entries and
nonlocal providers use the existing safe path; string prefixes alone are unsafe.

#### Option A: Reduced Checks, Prepare the Whole Batch

Selected and implemented. Preparation-time overwrite/Abort decisions finish
before executing the queued destination creation and transfer tasks.

- Remove the duplicate pre-task pass, then classify/check candidates and build
  the existing task list inside visible, cancellable preparation.
- Start mutations only after preparation succeeds. Cancellation or refusal in
  preparation leaves the destination unchanged. Execution can still fail later
  and leave a completed prefix.
- Retains known totals and the current preparation/execution structure, reducing
  integration risk. Startup still depends on N candidates and the queued tasks
  use O(N) memory in addition to the selection.
- First-file delay grows with the selected and recursively discovered items that
  must be prepared, approximately linearly for ordinary files on the same storage.
  It is not inherently proportional to all entries in a folder when only a few
  files are selected. Visible progress does not eliminate that preparation delay.

#### Option B: Execute Files Individually, Handle OS Results

Deferred alternative; not shipped or enabled by a production switch.
The user's later preference for B is breadth-first traversal; it is not implemented
by this bulk-enumeration follow-up, which retains A's preparation semantics.

- Do not scan the whole ordinary-file selection before starting. For each item,
  perform necessary policy/identity checks, invoke the existing provider, handle
  its result and continue. Do not predict readability, writability or free space
  with a separate whole-batch pass; let the operation report those failures.
- Keep the current provider's staging, alias/overwrite protection and native
  no-overwrite behavior. This is a scheduling change, not a replacement copy
  engine or a removal of provider safety checks.
- Starts the first file without constructing N tasks. Bound pending tasks to the
  current item or a small fixed batch; the captured selection remains O(N).
- Later errors/cancellation can leave earlier files and created directories in
  place. Preserve existing continue/abort/overwrite decisions and report completed,
  failed and unattempted work accurately. For Move, never delete a source whose
  copy failed.
- Use item counts or an indeterminate total until byte totals are known. Do not
  introduce a full directory walk merely to calculate progress. Directory/link
  and nonlocal paths may need existing provider-specific planning; define those
  fallbacks explicitly and validate them before extending streaming to them.

#### Selected Design and Refinements

Opus, Fable and Sol recommended A. The user approved it after discussing data
safety and latency. A preserves pre-execution conflict decisions, gathered byte
totals and Move's bottom-up task order. B's immediate startup did not establish
a reliable throughput advantage worth new streaming/provider semantics.

- Ordinary local files keep exact-path and destination identity checks but skip
  ancestor walks. Links, missing/zero identities and other providers fall back
  to the existing `samefile` walk.
- Local directory preparation caches destination ancestry identities per parent,
  covering lexical and resolved ancestor paths. Each source uses a following
  stat; uncertain identities fall back. The cache is cleared before execution
  and on cancellation/error; it is not a global cache or transaction guarantee.
- Destination creation is queued inside Copy/Move tasks, including drag-and-drop.
  Symlink retains its original pre-task checks. Native publication protections
  remain unchanged.
- Revisit B or compact prepared records only if further measurements justify the
  extra semantics. Working-set deltas include caches and allocator effects, not
  just Task objects; no claim of exact per-task memory is made.

### Enumeration Choice

- Vanilla A uses ordinary provider metadata and directory traversal, with its
  reduced ancestor checking and existing prepare-before-execute policy.
- No transfer-specific bulk scan, sibling-count threshold, metadata cache or
  adaptive dispatcher remains. Native bulk pane listings are unchanged.
- Bulk saved about 71 ms to the first flat-file copy but roughly doubled this
  tree's preparation time, without a reliable total-throughput improvement.
  The user chose simplicity over an adaptive policy. The preserved bulk source
  and three-way results below remain experimental references, not active modes.

### 3. Deferred Status-Capture Proposal

The following is retained as design context only. It was not implemented in this
task and its acceptance gates require separate approval.

- Retain the existing status debounce, worker service and generation/token checks.
- For snapshot-backed panes, capture references to the immutable `Listing`, its
  displayed-position tuple, location, completeness/hidden flags and compact
  selected row ranges. Select All is one range; do not expand it to 200,000 URLs
  or query `selectedRows()` on Qt.
- Pass only immutable plain data. The worker must not receive a widget, model,
  Qt index or Qt selection object. Add an internal snapshot adapter only where
  necessary; keep public pane/selection contracts unchanged.
- Expand status entries and count membership on the existing worker. Prefer
  iterating against the captured ranges instead of building another full URL set.
  Preserve `max_entries` for size queries, completeness flags and existing totals.
- Cancellation applies while expanding entries as well as querying sizes. A
  later selection, filter, navigation or closure invalidates the result through
  the existing owner/generation checks.
- Disabled status must capture nothing and schedule no status work. Do not move
  Qt calls to a worker or fix this by suppressing accurate selection counts.

### Ownership and Failure Behavior

- Core commands own the destination decision; task orchestration owns preparation,
  cancellation and execution under A or B; providers retain mutation safeguards.
- The pane captures immutable display/selection state on Qt; the status service
  computes it off Qt and publishes only current results through queued signals.
- Under A, preparation refusal/cancellation causes zero transfer mutations. Under
  B, no mutation precedes the initial safety/cancellation boundary, but a later
  refusal or cancellation may follow completed files. Neither option rolls back
  a completed prefix or treats it as unattempted.
- No new persistence or background services. Diagnostic outputs use the existing
  ignored performance area; each disposable fixture is cleaned after model and
  worker shutdown, including timeout/failure paths.

## Alternatives

- **A versus B:** A was selected. It fits the existing task-list model and
  detects preparation errors before mutation; B reduces first-file latency and
  queued-task memory but needs explicit streaming progress and partial-result
  semantics. B remains a future evidence-based option.
- **Only show progress earlier:** useful first step, but leaves repeated native
  path resolution. Combine it with a measured, safety-preserving ordinary-file
  preparation path.
- **Drop parent/identity checks or use string prefixes:** rejected; directory
  aliases, short names and links make this unsafe.
- **Cache all resolved paths globally:** rejected; invalidation after filesystem
  changes is difficult and it adds unrelated browsing cost and memory.
- **Replace Select All:** rejected for now; it was already fast in the controlled
  reproduction. Optimize the measured status observer, not an assumed Qt defect.
- **Raise the status debounce or disable status:** hides or delays useful
  feedback without removing the Qt-thread work.

## Runtime Effects

- Startup/folder entry: no new scan, worker, per-entry query or recurring timer.
  Existing status behavior remains opt-in.
- Copy preparation: keep O(N) source processing; remove the O(N * D) repeated
  ancestor-resolution pattern for ordinary files, where D is destination depth.
  Directory/provider fallbacks may retain their existing costs, now visible and
  cancellable. A retains O(N) queued tasks without a second plan; B bounds queued
  tasks independently of N, but does not eliminate the O(N) captured selection.
- No extra sibling-count pass or transfer-enumeration cache. Vanilla A retains
  its task-local directory-ancestor identities and clears them before execution;
  provider metadata caches and native pane scans retain their existing behavior.
- Deferred status proposal: Qt capture would be proportional to selection ranges, not displayed entries;
  Select All uses one range. Worker counting stays O(N). Reuse immutable listing
  storage; bound new state to captured ranges and active/latest work. Old snapshots
  may live until cancellation completes but must not accumulate across edits.
- I/O: do not read file contents for selection/status capture. Size queries remain
  bounded by `max_entries`; transfer validation still performs necessary fresh
  metadata/identity checks. Final copy I/O is unchanged.
- Threading/cancellation: reuse command/task and status workers. No per-file
  threads. Check cancellation between bounded work items; no Qt-thread joins.
- No-op paths: cancelled destination prompt starts no operation; disabled status
  creates no feature-specific snapshot, I/O or work.
- Copy workloads run with `python build.py measure --full`, not regular measure,
  application startup or the correctness suite. Combined payload is about 47 MiB;
  allow source plus destination storage (about 94 MiB) and staging
  headroom. Check fixture capacity before setup; insufficient space is a reported
  failure, not a silently smaller workload.
- Use an owned source tree and a fresh empty destination per repetition. Reuse
  the verified, read-only source within the invocation; delete each destination
  before the next repeat. Setup, byte verification and cleanup are untimed.
  Never mutate shared fixtures. Three repeats of both cases copy about 141 MiB,
  with additional setup/verification I/O; record the workload's time and disk cost.

## Tests

Regression coverage was added before the corresponding application change:

- `ConfirmTreeOperationTest`: Copy/Move reach task submission without N parent
  checks in the prompt path; prompt cancellation and single-file suggestions
  remain correct; Symlink's existing validation is preserved.
- `core.tests.test_fileoperations`: identical paths, existing hard-link/8.3
  aliases, a directory into itself/its descendants through aliases, missing
  destination, mixed selections, denied metadata and provider fallbacks. Prove
  cancellation before any mutation causes no mkdir/copy/move and later collisions
  are rejected by provider safeguards. A must leave no changes after preparation
  refusal; B must report a completed prefix after a later error/cancellation and
  never delete an uncopied Move source. Native link cases use expected skips only
  when the platform cannot create the fixture.
- Status unit and Qt tests: all/none/contiguous/fragmented selection, filters,
  hidden entries, unknown sizes and the size-query cap. Verify counts and totals
  against the old algorithm. Ensure workers access no Qt objects, stale results
  cannot publish, and disabled status performs no capture or queries. These are
  requirements for the deferred status task, not claims of this implementation.
- Native Qt integration: after confirming a blocked preparation, observe a
  visible progress dialog, issue Cancel and verify no mutation if execution has
  not started. Also cancel after some copies and verify exact partial results.
  Test actual Ctrl+A followed by F5, not only direct command calls.

Focused unit launcher:

```powershell
python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','core.tests.commands.test___init__.ConfirmTreeOperationTest','core.tests.test_fileoperations','core.tests.fs.test_local','fman_unittest.impl.test_status_bar','-q'],env=build._environment()).returncode)"
```

Focused Qt launcher; repeat with `offscreen` after the native run:

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.SnapshotFilterBarIT','-q'],env=env,timeout=120).returncode)"
```

### Required Performance-Suite Addition

- Add copy workloads to [catalog.yaml](../src/performancetest/catalog.yaml), the
  existing runner, result validation and HTML reporting described in the
  [performance guide](../src/performancetest/README.md).
  `python build.py measure --full` runs the flat and tree copy workloads;
  regular `measure` neither prepares nor runs them.
- Ordinary files contain deterministic real data: 4 KiB in the 10,000-file flat
  fixture and 8 KiB in the 1,000-file tree. Copy each complete fixture to a separate
  initially empty destination. Do not substitute synthetic model rows.
- Exercise the real pane and command path: wait for folder loading to settle,
  clear selection, send Ctrl+A, verify all top-level entries selected, then send F5 and
  confirm the destination. Measure Ctrl+A dispatch-to-completed-selection-paint
  and follow-up input latency separately from selected-URL readback, first copied
  file, total copy time and final pane refresh. Keep status completion a separate
  metric; do not replace UI timing with a direct provider call.
- Preserve stable test/action IDs, fixture revisions and comparison boundaries.
  Results must identify strategy, provider, size/count, repeat, cache protocol,
  source revision and whether UI/pane refresh is included. Change revisions if
  measurement semantics differ; never compare incompatible samples as equivalent.
- The benchmark was implemented first, tested, then run against an isolated
  export of exact tag `v0.14.0`. Preserve source/harness fingerprints, raw samples
  and immutable run IDs before changing measured application behavior. Compare
  implemented A using that same harness and fixture. Existing
  prototypes cover only ordinary files with absent destinations; label that
  limitation rather than advertise untested safety parity. Diagnostic comparisons
  may retain isolated A/B variants; do not ship permanent production A/B modes.
- Use the suite's three repetitions, isolated settings and declared warm-cache
  protocol. Record file count/size, selected count, status mode, first completed-file
  latency, preparation time, total time/throughput, peak memory and queued-task
  count. Report medians/ranges; give Select All, first-file latency and copy
  throughput distinct report fields. If diagnostic A/B runs are requested later,
  use this same fixture/protocol and rotate their order; do not add size variants.
- Verify every source/destination byte and entry count outside timing. Failed,
  partial or timed-out samples must not produce success timings or overwrite the
  last successful report. Guarantee teardown of workers and disposable trees.
- Add a small runner/report regression so `build.py measure --full` includes the new
  workloads and their Select All/copy metrics, while normal correctness tests do not
  generate or copy the full payloads. Unit tests may use tiny fixtures for protocol
  checks. Run conflict/failure/cancellation cases separately; never mix them into
  successful-copy throughput aggregates.

### Performance and Manual Gates

- Reuse [selection measurements](../src/performancetest/python/fman_performancetest/selection.py)
  and the [pane harness](../src/performancetest/python/fman_performancetest/pane_rendering_benchmark.py).
  Add F5 preparation stage timings there rather than a separate benchmark system.
- Use the same flat/tree cases for all measured variants. Source
  and destination folders may share the same basename. Preserve the suite's
  declared status mode; test enabled-status capture separately without introducing
  another copy workload. Do not equate a fresh process with cold filesystem caches.
- Measure Ctrl+A dispatch-to-paint/input-ready, Qt snapshot time, status completion,
  F5-to-prompt, confirmation-to-progress, first completed file, total elapsed time,
  preparation throughput, cancellation latency, native resolution counts, peak
  memory and destination mutations. Keep provider-only and end-to-end UI runs
  separately labeled; the earlier provider timings excluded pane refresh.
  Post follow-up input without waiting for the status debounce; keep the harness's
  status-settled timing as a separate metric.
- Each measured case finishes all copies and verifies contents, relative paths,
  directory structure and counts outside timing. Use small correctness fixtures
  for cancellation before the first mutation
  and after a completed prefix; verify exact partial state. Do not add another
  unrequested full-copy size or a 200,000-file copy stress run to this task.
- Hold a provider read in a test: progress must remain responsive; cancellation
  must stop at the next interruptible boundary. Verify no orphan task/thread and
  fixture cleanup. Test normal folder entry separately for added-work regressions.
- No full suite, freeze or packaging unless explicitly requested. These are
  proposed validation gates, not already-passing implementation results.

## Implementation Steps

1. Received three recommendations for A and explicit user implementation approval.
2. Implemented the 15,000 x 8 KiB Ctrl+A/F5 benchmark, catalog and report support.
3. Preserved a verified three-repeat `0.14.0` baseline before application edits.
4. Added failing startup/safety tests, implemented A, then validated provider
   fallbacks, cancellation and actual progress visibility.
5. Ran the identical benchmark against A and recorded latency/memory results.
6. Updated usage and changelog. Deferred status optimization and retained all
   earlier measurements/reviews, including failed/superseded baseline records.
7. At the user's request, revised full-only fixtures to flat 10,000 x 4 KiB and
  tree 1,000 x 8 KiB. Preserved and measured baseline/vanilla A before bulk edits.
8. Implemented bulk metadata reuse, validated lifetime/fallback/mutation safeguards,
  then measured bulk A with the same harness and retained the three-way comparison.
9. At the user's request on 2026-10-07, restored the measured vanilla-A transfer
  modules and removed the bulk experiment from production. Retained both full-only
  benchmarks, all source exports and historical results.

## Acceptance Criteria

- A is selected and no production hybrid/streaming mode is introduced.
- The benchmark is implemented and a verified `0.14.0` baseline preserved before
  application changes, using the same harness and workload as the comparison.
- On the controlled copy benchmarks, no selected-item loop runs between
  destination confirmation and entering the cancellable task.
- Progress is visibly usable within 1.25 s of confirmation, including the existing
  approximate one-second display delay. Cancellation completes within 250 ms
  between provider calls; a blocked OS call is explicitly excluded from that bound.
- Ordinary-file handling no longer resolves every destination ancestor for every
  source. Path-call counts show the reduction; self-copy, alias, descendant and
  overwrite safety tests pass. A reports its whole-batch startup cost; B does not
  visit the entire ordinary-file selection before the first copy.
- Ctrl+A paint/input/readback remain separate metrics. Status optimization is
  deferred; no status or folder-entry behavior is changed by this task.
- Approximately 100 ms preparation is a stretch goal, not an achieved result or
  a reason to weaken safety; report the measured value and remaining delay.
- Small full-copy fixtures are exact; cancellation before execution leaves source
  and destination unchanged. Later error/cancellation retains and accurately
  reports the completed prefix. Plug-in APIs and Move/link semantics are preserved.
- `python build.py measure --full` runs the two requested Copy workloads,
  selected through Ctrl+A and copied through F5. All contents and tree structure
  and selection counts are verified. The report separates Select All latency,
  first-file latency and total throughput with versioned, compatible results.
  Setup/verification/cleanup are untimed, and no additional copy-size workload
  is added. This suite integration is required to complete the task.
- Do not mark the user's two-second observation fixed without a matching
  reproduction. Report measured improvements and remaining uncertainty separately.

## Reviewers

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Proposed visible/cancellable transfer preparation, reduced redundant
  ancestry checks and worker-side status expansion based on controlled probes.
  The two-second Select All report remains unconfirmed. No application code
  changed; independent design review and implementation approval remain pending.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Revised at the user's request to retain both reduced whole-batch
  preparation (A) and individual provider execution (B) for reviewer recommendation.
  Added measured prototype comparisons and required catalog/runner/report work for
  the performance suite. Clarified option-specific partial completion, progress
  and memory behavior. No option selected and no application/benchmark code changed.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Narrowed the planned benchmark at the user's request to one 5,000-file
  copy workload with exactly 1 MiB per file in regular `build.py measure`. Require
  real Ctrl+A/F5 timing and separate selection/startup/throughput reporting;
  removed extra planned copy sizes and documented fixture disk cost. Historical
  measurements and prior records are preserved. A/B choice remains pending;
  no application or performance-suite implementation was changed or run.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Reduced the planned file size to 100 KiB (approximately 0.1 MB) at
  the user's request and recalculated storage/I/O costs. The 5,000-file count,
  regular `build.py measure` integration and Select All/copy metrics are unchanged.
  No application or benchmark code changed.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Recommend Option A for all paths now; defer B. The diagnosis and
  the shared startup rules are sound. E1 explains the recommendation, E2 makes
  the remaining directory check O(N + D) for both options, and E3-E5 are smaller.
  No code changed or run.

## Design Review (2026_10_06, Opus)

Checked against `_TreeCommand.__call__`/`_confirm_tree_operation` in
[commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py),
`FileTreeOperation` in [fileoperations.py](../src/main/resources/base/Plugins/Core/core/fileoperations.py),
`is_parent` in [util.py](../src/main/resources/base/Plugins/Core/core/util.py) and
`ProgressDialog` in [widgets.py](../src/main/python/fman/impl/widgets.py).

- **E1 [P1] Recommendation: Option A.** Both options get the decisive fix from
  the shared rules: no hidden pre-task loop, and no per-file ancestor resolution.
  What is left between them is small for users and large in risk.

  | Criterion | A | B |
  | --- | --- | --- |
  | First-file latency | About 36 µs per file before the first copy (362 ms at 10,000; about 7 s extrapolated at 200,000), visible and cancellable | Immediate |
  | Total time | 1.006 s / 10.40 s | 1.054 s / 9.81 s; no clear gain |
  | Conflict prompts | All asked in preparation, before any copy; the rest runs unattended | Interleaved with copying; the user must stay present |
  | Progress | Exact byte total from task sizes | Item count or indeterminate |
  | Refusal (self-copy, Abort) | Zero mutations | May follow a completed prefix |
  | Move | Bottom-up directory postprocessing keeps its gathered order | Needs per-directory planning anyway |
  | Memory | O(N) queued tasks | Bounded queue |
  | Change size | Remove one loop, add a fast path in `_gather_files` | New scheduler, streaming progress, new partial-result semantics and fallbacks |

  The user's complaint was that nothing visibly happened. That was caused by
  the hidden loop and the O(N·D) resolution, and A fixes both. The existing
  task already shows `Gathering files...` and `Preparing to copy N files.`,
  and `ProgressDialog.set_text` is timer-throttled, so A needs no new progress
  code. Revisit B only for ordinary local files, and only if the benchmark
  shows A's preparation or task memory (E3) as a real cost. That would be a
  separate task.
- **E2 [P2] Make directory sources cheap too, in both options.** The fast path
  in the plan covers ordinary files only; directories keep `is_parent` at
  O(D) resolutions each. For local providers, resolve the destination's
  ancestors once and keep a set of their `(st_dev, st_ino)` identities. Then
  check each source directory with one `os.stat` against that set. Following
  links in both the ancestors and the source still catches junction and
  symlink aliases. Nonlocal providers keep the existing `samefile` walk. Test
  it with a source directory reached through a junction alias of a destination
  ancestor.
- **E3 [P3] Measure A's per-task memory.** The single 5,000-file workload
  cannot show behavior at 200,000. Record peak memory minus the baseline,
  divided by the queued-task count, and report the 200,000-task extrapolation
  as an estimate. Do this before claiming A is fine at the reported scale.
- **E4 [P3] Status capture is independent work.** Section 3 does not affect
  copy startup. Give it its own implementation step and acceptance gate, or its
  own task document (AGENTS: separate tasks for unrelated work), so the copy fix
  can land and be measured alone.
- **E5 [P3] Minor.**
  - Under A, state that every overwrite and Abort decision happens before the
    first mutation (current behavior), and test it.
  - Drag and drop also reaches `_TreeCommand.__call__`, so its `makedirs` move
    into the task covers that path; add it to `ConfirmTreeOperationTest`.

Verified: `_TreeCommand.__call__` calls `makedirs` before `submit_task`.
`_confirm_tree_operation` runs `is_parent` for every selected file, and
`_gather_files` repeats it. `_enqueue` updates the text per file, but
`ProgressDialog` repaints only every 100 ms. No code was changed or run.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Recommend **Option A**, concurring with E1, with three
  refinements: define the ordinary-file fast path as one identity comparison
  when the destination exists (G1), adopt E2's identity set with a
  zero-identity fallback (G2), and defer `Task` materialization inside A only
  if E3's measurement shows real cost (G3). Split Section 3 into its own task
  (G4). B stays a measured future option. No code changed or run.

## Design Review 2 (2026_10_06, Fable)

Checked against `_TreeCommand`, `_confirm_tree_operation` and `_split` in
[commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py),
`FileTreeOperation.__call__`, `_gather_files`, `_merge_directory`,
`_should_overwrite`, `_handle_exception`, `_enqueue` and `_iter` in
[fileoperations.py](../src/main/resources/base/Plugins/Core/core/fileoperations.py),
and `is_parent`/`_iter_parents` in [util.py](../src/main/resources/base/Plugins/Core/core/util.py).

**Why A.** The measured difference between A and B is startup only; total
time is equal within noise (10.40 s versus 9.81 s at 10,000 files), and A's
startup is visible and cancellable because `_gather_files` already shows
`Gathering files...` and `Preparing to copy N files.` and `_iter` already
checks cancellation per item. What A keeps and B would have to re-create:

- Overwrite decisions (`_should_overwrite`: Yes/No/Yes to all/No to all/Abort)
  and the self-copy refusal all happen before the first mutation. Abort means
  zero changes. Under B these prompts interleave with copying, and Abort or a
  `_handle_exception` answer leaves a prefix; two prompt families would then
  compete during execution.
- Exact byte totals from gathered task sizes drive the percentage bar; B has
  counts or an indeterminate bar until it walks the tree anyway.
- Move's bottom-up `_postprocess_directory` ordering and `_merge_directory`
  recursion are already correct in the gathered list; B needs per-directory
  planning to preserve them.
- A removes one loop and adds one fast path; B is a new scheduler plus new
  partial-result semantics, progress model and provider fallbacks, which the
  prototype did not exercise.

The user's symptom (nothing visible after F5) is fully explained by the
hidden pre-task loop and the O(N·D) `samefile` walk; A removes both.

- **G1 [P2] Define the ordinary-file fast path precisely.** "A file cannot
  contain the destination" removes the ancestor walk, but `is_parent` also
  yields `dest` itself first, which is how `src == dest` and alias self-copies
  (hard link, 8.3 name) are caught today and routed to `_can_transfer_samefile`.
  The fast path must therefore be: `exists(dest)` (already performed for the
  overwrite prompt); if it exists, one `samefile(src, dest)` identity
  comparison; otherwise no ancestry work. Zero or unavailable identity falls
  back to the existing resolved-path `samefile`. State this in Design 2 and
  test a hard-linked destination alias and an 8.3 alias explicitly.
- **G2 [P2] Adopt E2 with a fallback rule.** Resolve destination ancestors
  once (following links) into a `(st_dev, st_ino)` set and test each source
  directory with one following `os.stat`. Add: if any ancestor or the source
  reports zero identity (FAT, some network providers), use the existing
  `samefile` walk for that item instead of trusting the set. Nonlocal
  providers keep the walk. This keeps directory sources O(N + D) without
  weakening the junction/symlink alias protection.
- **G3 [P3] Measure before changing A's memory profile.** E3's per-task
  measurement decides whether 200,000 gathered `Task` objects matter. If it
  shows a real cost, keep A's semantics but gather compact
  `(src, dest, size)` records for ordinary local files and construct each
  provider `Task` at execution time; directories and nonlocal providers keep
  the current gathering. Do not pre-empt this with B.
- **G4 [P3] Split Section 3 (status capture) into its own task document**,
  as E4 says. It has independent acceptance gates (Qt capture < 25 ms,
  parity with the old algorithm) and no effect on copy startup; keeping it
  here couples two unrelated validation sets.
- **G5 [P3] Record B's re-entry condition.** B is worth revisiting only if a
  compatible benchmark shows A's visible preparation above a user-noticeable
  threshold at the supported scale, or E3 shows unacceptable task memory that
  G3 cannot fix. Name that condition so the decision is not reopened on
  startup-latency grounds alone.
- **G6 [P3] Minor.** The 1.25 s acceptance bound already includes the
  dialog's ~1 s display delay; make explicit that at 200,000 files A's
  `Preparing to copy N files.` counter is the visible feedback during the
  remaining preparation, and that the benchmark's 5,000-file case measures
  preparation in the ~0.2 s range, so the regression signal for this task is
  confirmation-to-progress and native-resolution counts, not total throughput.

## Design Review 3 (2026_10_06, Sol)

**Recommend Option A for the first implementation across Copy and Move.**
Do not add a production A/B switch or a streaming hybrid in this task. This is
a recommendation, not selection or implementation approval.

The measured defect is silent, expensive work before progress creation.
Deferring that work into the task and removing redundant ordinary-file ancestor
walks addresses it under either option. A also preserves the current operation
semantics; B changes when conflicts, refusals and partial completion occur.
The existing prototypes do not demonstrate a consistent throughput advantage
large enough to justify that additional behavior change.

- **First-file latency:** B wins. A took 361.76 ms before the first file at
  10,000 files, versus 1.16 ms for B. A must make preparation visibly cancellable,
  not claim an immediate first copy. A delay near seven seconds at 200,000 files
  is only an extrapolation; it has not been measured end to end.
- **Throughput:** A was slightly faster at 1,000 files; B was slightly faster at
  10,000. These warm, provider-only medians are not evidence of reliable product
  throughput superiority. Compare the approved 5,000-file, 100 KiB workload
  through real Ctrl+A/F5 before making an application performance claim.
- **Memory:** A retains O(N) queued tasks and B bounds the queue. Keep this
  limitation explicit and measure per-task cost. If necessary, consider G3's
  compact prepared records separately, without dropping A's approval semantics
  or materializing an unbounded second plan. Neither option removes the O(N)
  captured selection.
- **Cancellation and partial completion:** A preserves preparation Abort or
  cancellation with zero transfer mutations. B may already have copied or moved
  a prefix when a later conflict needs approval. Both may leave a completed
  prefix after execution starts; A is not a transactional batch.
- **Progress totals:** A preserves existing task-size totals and percentage
  progress. B requires counted or indeterminate progress and careful aggregation
  while tasks are discovered; walking everything to recover a total defeats
  its main startup advantage.
- **Compatibility:** A preserves `_should_overwrite`, `_handle_exception`,
  `_merge_directory` and Move's bottom-up postprocessing order in
  [FileTreeOperation](../src/main/resources/base/Plugins/Core/core/fileoperations.py).
  Existing providers and mixed/directory selections retain the planned path.
  B's provider fallbacks and mid-operation prompt semantics need a separate
  design and regression effort, not inference from ordinary-file timing.

Before implementation, integrate G1's exact self/alias check and fallback rule;
an ordinary-file fast path must not remove the check against the destination
entry itself. Keep Symlink's guard, move Copy/Move's destination creation after
successful preparation, and test that overwrite Abort creates nothing. Treat
E2/G2's ancestor identity set as task-local only, with conservative fallbacks;
do not introduce a global cache or imply protection against hostile path races.
Verify actual progress visibility during a blocked preparation; existing text
updates alone are not proof that the dialog has appeared.

Keep status capture independently verifiable from transfer scheduling. It is
needed for the enabled-status selection lag, but does not justify choosing B
or substituting status completion for Ctrl+A paint/input timings. Keep the
required single 5,000-file benchmark; do not add another large copy workload.

Revisit B only with evidence that A's remaining first-file delay or task memory
is unacceptable, and explicit agreement to late conflict prompts and partial
completion on preparation refusal. Limit that future evaluation to ordinary
local files first; directory/link/nonlocal adoption requires its own boundary.

### Validation

- Checked the current confirmation path, `is_parent`, task gathering, overwrite
  decisions, Move postprocessing and the progress dialog's one-second initial
  display timer against source. The shared pre-task guard and destination
  creation are still present; neither proposed option is implemented.
- Ran the existing behavior baseline; 83 tests ran, 81 passed and two skipped:

  ```powershell
  python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','core.tests.commands.test___init__.ConfirmTreeOperationTest','core.tests.test_fileoperations','-q'],env=build._environment(),timeout=120).returncode)"
  ```

- No application or benchmark code changed. No performance workload, source-app
  probe, full suite, freeze or package was run. Prototype timings above remain
  historical evidence, not validation of an implemented A or B.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Recommend A for the initial Copy/Move implementation, retaining
  preparation-time decisions and provider ordering while making preparation
  visible and cancellable. B remains a separately justified future option.
  Existing plan/reviews are preserved; selection and implementation are pending.

## Implementer

### 2026_10_06 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Implemented user-approved A after adding and validating the real
  15,000 x 8 KiB Ctrl+A/F5 performance workload and preserving the tagged 0.14.0
  baseline. Copy/Move now enter cancellable preparation before bulk checks or
  destination creation. Ordinary files avoid ancestry walks; directories use
  task-local identity sets with conservative fallbacks. Existing overwrite,
  Symlink, Move, provider and partial-error behavior remains covered. Status
  optimization and streaming B were not implemented.

## Validation Results

### Baseline and Comparison

The baseline uses exact tag `v0.14.0`, commit
`bbe0a1b7a9b1d9f135cab1587eb5ffb51f8aed86`, exported with
`fman_performancetest.historical.export_source`. The new harness was implemented
and tested before editing application Copy/Move behavior. Baseline children used
`historical.child_environment` and `python -B -X faulthandler -m
fman_performancetest.suite --child copy.files`, the current catalog, the verified
`copy-files-v1` fixture and a parent-owned temporary `--scratch` directory.
Three independent children completed and verified all 15,000 files each.

- Corrected baseline run: `55eba804-8f59-4661-a7a3-4d74029c263a`.
  [Baseline report](../UserSettings/Performance/CodeReview010/0.14.0-r3/index.html)
  and [identity record](../UserSettings/Performance/CodeReview010/0.14.0-r3/baseline.json).
- A run: `95092cdd-d9b4-47a7-9f24-a2db21f1010f`, honestly labeled `Unreleased`
  because the workspace has earlier uncommitted application changes.
  [Comparison report](../UserSettings/Performance/CodeReview010/option-a/index.html)
  and [machine-readable comparison](../UserSettings/Performance/CodeReview010/option-a/comparison.json).
- Application and harness fingerprints, fixture/protocol hashes, raw samples,
  environment and run IDs are retained in those local records. The harness was
  unchanged between the corrected baseline and A. This is a copy-only baseline,
  not a claim that every regular performance workload ran for 0.14.0.

Medians for the same 15,000 x 8 KiB workload, including real pane notifications:

| Metric                    | 0.14.0 Baseline | Option A   |
| ------------------------- | --------------- | ---------- |
| Select All paint          | 9.94 ms         | 6.02 ms    |
| Follow-up input paint     | 5.64 ms         | 5.14 ms    |
| Progress first visible    | 14,622 ms       | 1,015 ms   |
| Task preparation          | 14,530 ms       | 538 ms     |
| First completed file      | 28,152 ms       | 555 ms     |
| Copy complete             | 129.03 s        | 113.09 s   |
| Queued tasks              | 15,001          | 15,001     |
| Working set after gather  | 125.09 MiB      | 122.57 MiB |

First-file latency improved about 98%; total time about 12%. These are observed
warm runs, not universal guarantees or proof that selection timing changed because
of A. The source tree contains earlier unreleased changes; the isolated tagged
baseline and current provenance are recorded explicitly.

The approximately 100 ms preparation stretch goal was not met: measured A median
was 538 ms. No safety checks were removed to force it. The preparation working-set
delta was 30.34 MiB for A versus 8.10 MiB for the baseline, but the old measurement
begins after its hidden preflight has already populated caches. These are not
equivalent pure Task allocations. A's total working set after gathering was
slightly lower. The reported 200,000-task estimates include allocator/cache
effects and are not measured large-folder memory results.

### Failed and Superseded Attempts

- Initial run `cae0fbfc-9a45-47e9-adfc-394e049f3427` completed copying, but later
  paints overwrote its follow-up-input timing. The harness was fixed to capture
  that event once; the original record is retained with a supersession marker.
- Corrected attempt `11dd3575-73fe-41f1-abbc-dbe1ba8d2bc5` failed during repetition
  two with a native access violation in unchanged 0.14.0 destination-pane refresh
  (`reconcile`/`project`). Its failed record and traceback are retained under
  `UserSettings/Performance/CodeReview010/0.14.0-r2`. A fresh three-repeat retry
  passed without changing the tagged application or suppressing refresh work.
  The native failure's root cause is not claimed fixed by A.

### Focused Checks

- Benchmark-first checks: 72 benchmark catalog/fixture/runner/report tests passed,
  including real eight-file Ctrl+A/F5 copying, actual settings isolation, exact
  content/count verification, invalid result rejection and parent-owned scratch
  cleanup on timeout. Command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); code='import sys, unittest; sys.path.insert(0, \'src/performancetest/python\'); unittest.main(module=None, argv=[\'benchmark-tests\', \'fman_performancetest.test_filter_find_benchmark\', \'-q\'])'; sys.exit(subprocess.run([sys.executable,'-B','-c',code],env=env,timeout=180).returncode)"
  ```

- New startup/fast-path tests failed before the application edit, then passed.
  Native blocked-preparation test verifies actual dialog visibility within
  1.25 s, cancellation return within 250 ms after release, and no destination
  creation. A test-fixture filesystem binding omission initially opened an alert;
  the fixture was corrected, not the application guard.
- Native gate: 444 tests, 436 passed and eight expected link-privilege skips,
  108.704 s. Includes archive transfers:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.test_fileoperations','core.tests.test_util','core.tests.fs.test_local','core.tests.fs.test_zip','fman_unittest.test_listing','fman_integrationtest.test_qt.SnapshotFilterBarIT','-q'],env=env,timeout=240).returncode)"
  ```

- Final offscreen gate: 341 tests, 335 passed and six expected symlink-privilege
  skips, 2.955 s. Archive tests were not repeated in this run:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.test_fileoperations','core.tests.test_util','core.tests.fs.test_local','fman_unittest.test_listing','fman_integrationtest.test_qt.SnapshotFilterBarIT','-q'],env=env,timeout=150).returncode)"
  ```

- Existing same-path/case-only Move, overwrite Yes/No/Yes to All/No to All/Abort,
  directory postprocessing and provider tests pass. Added directory-junction
  alias, unknown identity/nonlocal fallback, one-resolution-per-destination and
  prepared-prefix refusal tests. Ordinary Rename link policy is unchanged.
- `python -B -m mkdocs build --strict --site-dir target/code-review-010-docs`
  passed. Changed-file editor diagnostics are clear. Regular catalog listing
  includes `copy.files`; the entire fourteen-workload `measure` command was not
  rerun, and no full correctness suite, freeze/package or new dependencies ran.
- No installed app, user dataset or private settings were inspected. No Git
  staging/commit or version change. Existing unrelated edits were preserved.
- Remaining gaps: native baseline refresh crash cause, live cloud/network provider
  behavior, unavailable privileged link cases, packaged/hosted CI and physical
  mixed-monitor tests. The original two-second Select All report remains unproven;
  status-bar optimization is deferred.

## Full-Only Measurement Follow-Up

### 2026_10_06 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: At the user's request, moved `copy.files` from regular `tests` to
  `full_tests` in catalog revision 12. Regular mode returns to 13 workloads/16
  overview rows; full mode retains 20 workloads/23 rows. No transfer behavior or
  measurement protocol changed. Historical run files and reviewer records remain
  unchanged; the performance guide retains a `0.14.0` versus `Unreleased` table.

- Validation: all 72 benchmark-tool tests passed. The regular/full fixture test
  verifies Copy is absent from regular preparation and present in full mode;
  report and child-dispatch tests still exercise its fields. Exact command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); code='import sys, unittest; sys.path.insert(0, \'src/performancetest/python\'); unittest.main(module=None, argv=[\'benchmark-tests\', \'fman_performancetest.test_filter_find_benchmark\', \'-q\'])'; sys.exit(subprocess.run([sys.executable,'-B','-c',code],env=env,timeout=180).returncode)"
  ```

- The native baseline access violation remains an unresolved crash defect, not a
  normal file-operation error. The last Python frames were `reconcile`/`project`
  during destination refresh while copying remained active. No native C stack
  was available, so the failing component and mechanism are not established.
  Successful retries and A's passing runs do not prove the crash fixed. A future
  investigation needs a native dump and a controlled reproduction, not a change
  to the preserved tagged baseline or inspection of user data.
- A still prepares the selected/discovered batch before copying the first file;
  its remaining preparation latency scales with that batch, not unrelated folder
  entries. The measured reference is 538 ms at 15,000 files; other sizes are not
  fresh measurements or timing guarantees.
- No large copy workload, full performance run, freeze or package was rerun for
  this scheduling-only change. The retained reference results are historical,
  not relabeled as newly measured full-suite results.

## Bulk Enumeration Implementation

### 2026_10_06 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Implemented scoped bulk enumeration in A and revised full-only tests
  to flat 10,000 x 4 KiB and complex-tree 1,000 x 8 KiB. Preserved exact 0.14.0,
  vanilla-A and bulk-A application copies and measured all with one frozen harness.
  Final provider safety checks and A's all-preparation-before-execution policy
  remain intact. Bulk improves flat preparation but regresses this tree's
  preparation; total throughput superiority is not established.

### Three-Way Reference

Medians of three successful real Ctrl+A/F5 runs per variant and fixture. Each
run verifies every source/destination byte, relative filename and directory.
Selection and setup/verification are outside copy timing; copy timing starts at
destination confirmation and includes preparation and actual copy execution.

| Fixture              | Metric        | 0.14.0    | Vanilla A | A + Bulk |
| -------------------- | ------------- | --------: | --------: | -------: |
| Flat: 10,000 x 4 KiB | Preparation   | 11,265 ms | 361 ms    | 270 ms   |
| Flat: 10,000 x 4 KiB | First file    | 21,585 ms | 376 ms    | 305 ms   |
| Flat: 10,000 x 4 KiB | Copy complete | 92.07 s   | 67.27 s   | 68.56 s  |
| Tree: 1,000 x 8 KiB  | Preparation   | 31.16 ms  | 27.21 ms  | 53.83 ms |
| Tree: 1,000 x 8 KiB  | First file    | 56.91 ms  | 36.44 ms  | 64.48 ms |
| Tree: 1,000 x 8 KiB  | Copy complete | 2.08 s    | 1.11 s    | 1.22 s   |

The tree selects ten root folders, not 1,000 pane rows. Existing recursive
provider preparation was already cheap, whereas flat selections previously
incurred per-selected-file overhead. Flat preparation improved about 25% versus
vanilla A; tree preparation roughly doubled. Total-time ranges overlap and are
not a reliable bulk-throughput gain: flat bulk 64.27-73.95 s versus vanilla
66.74-67.93 s; tree bulk 1.04-2.79 s versus vanilla 1.06-1.87 s. All 18 runs passed;
no new native crash occurred. The earlier baseline crash remains unresolved.

[Comparison report](../UserSettings/Performance/CodeReview010/BulkEnumeration/index.html),
[raw summary](../UserSettings/Performance/CodeReview010/BulkEnumeration/summary.json)
and [metric comparisons](../UserSettings/Performance/CodeReview010/BulkEnumeration/comparison.json).

- 0.14.0 run: `0f2b097b-2faa-4042-a70a-c483c00039e4`, exact tag commit
  `bbe0a1b7a9b1d9f135cab1587eb5ffb51f8aed86`.
- Vanilla-A run: `8ce8dd93-3bb5-45b1-b5dc-6f39abad55c1`, application copy preserved
  before bulk edits, content hash
  `4c4dd3971f583f00042aeffa2b9dd73e684e73241ca2910335c8739ebddfa956`.
- Bulk-A run: `3926b7e4-e81e-456d-be3a-cb2444fc91e5`, content hash
  `e90f26855d314333f21e395ea58c0b961a815386d39e44d5097b23281f050a58`.
- Catalog revision 13; new `copy.flat`/`copy.tree` IDs and fixtures. Old
  `copy.files` results are not relabeled. Regular measure remains unchanged;
  full mode now has 21 workloads and 24 overview rows.

### Validation Results

- Benchmark tooling: 74 tests passed, including real flat/tree smoke, exact
  structure/payload checks, selected-root counts, timeout cleanup and full-only
  catalog/report behavior. Command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); code='import sys, unittest; sys.path.insert(0, \'src/performancetest/python\'); unittest.main(module=None, argv=[\'benchmark-tests\',\'fman_performancetest.test_filter_find_benchmark\',\'-q\'])'; sys.exit(subprocess.run([sys.executable,'-B','-c',code],env=env,timeout=180).returncode)"
  ```

- Native application gate: 347 tests, 341 passed and six expected privilege skips,
  4.389 s. Final offscreen/archive gate: 450 tests, 442 passed and eight expected
  link-privilege skips, 106.492 s. Tests cover alias/link behavior, bulk/native
  identity parity, one-scan sibling reuse, small-selection admission, unsupported
  scans/identities/reparse fallbacks, cancellation/thread-local scope, and live
  file reads after the preparation scope is gone. Final command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.test_fileoperations','core.tests.test_util','core.tests.fs.test_local','core.tests.fs.test_zip','fman_unittest.test_listing','fman_integrationtest.test_qt.SnapshotFilterBarIT','-q'],env=env,timeout=240).returncode)"
  ```

- Timing procedure: use the current full-only catalog with `suite --child copy.flat`
  and `suite --child copy.tree`, each in an isolated child with a parent-owned
  `--scratch` directory and `historical.child_environment` for the frozen source.
  Verify source/harness/fixture fingerprints before each run. Baseline and vanilla
  A alternated order; bulk ran afterward. Persist raw results outside timing and
  compute comparisons with `records.compare`. Warm caches, three repeats; order
  and storage variability limit causal throughput claims.
- Early local fixes resolved an import cycle and reused metadata conversion on
  cache hits. A read-only preparation probe using StubFS deferred recursion and
  was discarded as noncomparable; the corrected MotherFS probe and final real-app
  runs use the actual recursive provider. A duplicate source-export request was
  refused without overwriting the first export.
- No full correctness suite, complete performance suite, freeze/package, new
  packages/environments, staging or commit. No installed application/private
  settings/user dataset inspection. Live cloud/network behavior, unavailable
  privileged links and the prior native refresh crash remain unverified.
- Documentation: `python -B -m mkdocs build --strict --site-dir target/code-review-010-docs`
  passed. Editor diagnostics were clear; catalog checks confirmed 13 regular
  workloads without Copy and 21 full workloads with both revised Copy cases.
  All historical reviewer/result text and local comparison links were verified.

## Vanilla A Selection

### 2026_10_07 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Restored vanilla A as the only production transfer path after explicit
  user approval. Both transfer orchestration and the local provider match the
  preserved vanilla-A source after newline normalization. Removed bulk hooks,
  their private cache module and the experiment's direct-child URL shortcut.
  No new dispatcher, setting, copy engine or streaming behavior was added.

### Retained Evidence

- The flat 10,000 x 4 KiB and tree 1,000 x 8 KiB cases remain full-only. The
  benchmark harness, fixtures, catalog and reporting were not changed here.
- The three-way table above, source exports and comparison artifacts remain
  historical references. No large timing runs were repeated or relabeled.
- Vanilla-A reference medians remain 376 ms to first file / 67.27 s total for
  flat, and 36.44 ms / 1.11 s for tree. These are the prior measurements, not
  fresh timings after this restoration.

### Validation Results

- Immediate `PreparationSafetyTest`: 9 passed, including no bulk scanner calls
  for 1/32 selected files, recursive Copy and Move, existing-directory merges,
  live execution-time reads, alias refusal and ancestor-cache behavior. Command:

  ```powershell
  python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.test_fileoperations.PreparationSafetyTest','-q'],env=build._environment(),timeout=120).returncode)"
  ```

- Native gate: 345 tests, 339 passed and six expected link-privilege skips,
  4.264 s. The same modules passed offscreen: 345 tests, 339 passed and six
  expected skips, 3.150 s. Commands:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.test_fileoperations','core.tests.test_util','core.tests.fs.test_local','fman_unittest.test_listing','fman_integrationtest.test_qt.SnapshotFilterBarIT','-q'],env=env,timeout=180).returncode)"
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.test_fileoperations','core.tests.test_util','core.tests.fs.test_local','fman_unittest.test_listing','fman_integrationtest.test_qt.SnapshotFilterBarIT','-q'],env=env,timeout=180).returncode)"
  ```

- Benchmark tooling: 74 passed, including small real flat/tree Copy smokes,
  full-only scheduling, content verification and report checks. Command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); code='import sys, unittest; sys.path.insert(0, \'src/performancetest/python\'); unittest.main(module=None, argv=[\'benchmark-tests\',\'fman_performancetest.test_filter_find_benchmark\',\'-q\'])'; sys.exit(subprocess.run([sys.executable,'-B','-c',code],env=env,timeout=180).returncode)"
  ```

- The first expanded no-bulk test run exposed an existing Move failure in three
  missing-destination cases. `_prepare_move` reads the destination parent's
  `st_dev` before queued directory creation executes. Comparison with the saved
  vanilla-A modules confirmed this is not introduced by the restoration. Move
  no-bulk tests now explicitly use existing destination directories; this is not
  a fix or a passing claim for missing destinations. Sources were retained.
- Production code has no remaining transfer-bulk imports or hooks; editor
  diagnostics are clear. No full correctness suite, large benchmark rerun,
  freeze/package, dependency change, staging or commit. Missing-destination Move,
  the earlier native refresh crash and previously unverified delivery checks remain
  open; this selection does not claim to resolve them.
- Documentation: `python -B -m mkdocs build --strict --site-dir target/code-review-010-docs`
  passed. Task sections, command fences and local links were checked; all prior
  reviewer/result text was preserved. SHA256 checks confirmed all 751 retained
  comparison/source files were unchanged.

## Missing-Destination Move Fix

### 2026_10_07 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Fixed local Move preparation into missing destination folders, including
  nested paths. The existing same-volume rename and cross-volume copy/delete
  strategies are unchanged. No bulk transfer scanner or new public API was added.

### Logic and Runtime

- Move needs the destination device before choosing rename or copy/delete.
  Preparation now checks the nearest existing parent directory and reuses that
  expected device in the existing per-preparation map. Missing parents add a
  path-depth walk; known paths reuse the map. No directory enumeration, new worker,
  timer, global cache or early filesystem mutation is introduced.
- Creating the folder before preparation was rejected because cancellation or
  refusal must still leave the destination unchanged. Folder creation stays in
  the queued execution phase. Native rename and copy/publication safeguards remain
  responsible for actual execution; the device estimate is not a filesystem lock.
- Only missing-path errors trigger the parent lookup. Permission errors, invalid
  paths, non-directory ancestors and missing drive/share roots still fail.
- The TODO item is complete and user documentation no longer prescribes creating
  the destination manually. All previous implementation records and performance
  references remain historical evidence, not measurements of this fix.

### Validation Results

- New mixed file/folder, nested-destination regression failed before the fix with
  `FileNotFoundError`, then passed. It uses the real command confirmation with a
  mocked UI, verifies no directory creation or source changes during preparation,
  then executes the queued tasks and verifies the destination contents. Command:

  ```powershell
  python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','core.tests.test_fileoperations.PreparationSafetyTest.test_move_to_missing_destination_prepares_without_mutation','-q'],env=build._environment(),timeout=120).returncode)"
  ```

- Preparation safety: 11 passed, including cancellation after preparation, missing
  destinations for 1/32-file selections and recursive moves, alias safeguards and
  no bulk scans. Removed the prior test-only destination pre-creation workarounds.
- Local provider/transfer gate: 143 tests, 137 passed and six expected link-privilege
  skips. Added simulated cross-device missing-parent coverage, inference reuse,
  non-directory rejection, error propagation and drive/share-root termination.
  Two existing cross-device stat doubles were updated to include directory mode.
  Existing copy-failure tests still verify that uncopied sources are not deleted.

  ```powershell
  python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.test_fileoperations','core.tests.fs.test_local','-q'],env=build._environment(),timeout=120).returncode)"
  ```

- Native integration gate: 351 tests, 345 passed and six expected skips, 4.614 s.
  Offscreen: the same 351 tests, 345 passed and six expected skips, 3.020 s.

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.test_fileoperations','core.tests.test_util','core.tests.fs.test_local','fman_unittest.test_listing','fman_integrationtest.test_qt.SnapshotFilterBarIT','-q'],env=env,timeout=180).returncode)"
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.test_fileoperations','core.tests.test_util','core.tests.fs.test_local','fman_unittest.test_listing','fman_integrationtest.test_qt.SnapshotFilterBarIT','-q'],env=env,timeout=180).returncode)"
  ```

- Cross-device routing and inaccessible share roots were simulated; no real second
  drive or unavailable network share was exercised. No full suite, performance
  rerun, freeze/package, dependency change, staging or commit. The earlier native
  refresh crash remains unrelated and unresolved.
- Documentation: `python -B -m mkdocs build --strict --site-dir target/code-review-010-docs`
  passed. Editor diagnostics were clear; task history, command fences and local
  links were verified without rewriting earlier records.