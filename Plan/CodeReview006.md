# Code Review 006: Bugs and Unneeded Edge Cases

Status: Selection benchmark implementation and a full current-code reference run
approved on 2026-10-01. Application fixes and performance acceptance budgets remain
pending; no application changes are approved.

The recommendations below incorporate the 2026-10-01 reviews. Review sections
record earlier proposal versions; their historical text is preserved.

## Task

Fix verified bugs and remove unneeded edge-case handling found in the 2026-10-01
code review. Focus on real-world effect: large folders and user interactions.

## Scope

Recommended: F01 mutation/readback improvements, F02 count/message correctness,
F03/F04, U04-U06, their regressions, and F01's versioned performance workload.

Excluded: new features, refactoring beyond each finding, performance work
outside F01, case-insensitive filename matching, removal of U01-U03, and the
rejected claims below. Replacing Qt's selection model or introducing asynchronous
selection requires a separate design decision if the focused F01 approach fails.

Compatibility: `DirectoryPane.select`/`deselect` keep their signatures and
missing-URL behavior. Strict calls retain successful-prefix effects on errors,
including iterator failures. Selection notifications are deliberately batched;
readback retains Qt range order, not a new input-order guarantee. No settings,
command identifiers or provider contracts change.

## Findings

### Bugs

| ID  | Severity    | Finding                                                    | Where                                  |
| --- | ----------- | ---------------------------------------------------------- | -------------------------------------- |
| F01 | Medium-High | Per-row selection is quadratic and blocks the UI thread    | `FileListView.select`/`deselect`       |
| F02 | Low         | Compare-directory counts include unselectable entries      | `CompareDirectories`                   |
| F03 | Low         | Pack from a drive root suggests the invalid name `C:.zip`  | `Pack.__call__`                        |
| F04 | Low         | Delete "continue?" prompt bypasses the progress dialog     | `_Delete.__call__`                     |

**F01.** [FileListView.select/deselect](../src/main/python/fman/impl/view/__init__.py#L97-L116)
call `selectionModel().select(row)` once per URL on the Qt thread. Qt does not
merge these into ranges, so cost grows quadratically, and later
`selectedRows()` (used by `get_selected_files`) is slow too. Offscreen Qt probe:

| Rows   | Per-row select | `selectedRows` | One range select |
| -----: | -------------: | -------------: | ---------------: |
| 10,000 | 8.8 s          | 4.1 s          | < 1 ms           |
| 20,000 | 36 s           | 16 s           | < 1 ms           |

Callers: [Invert selection](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L993),
[Compare directories](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L2057)
and plug-ins using `pane.select`. Snapshot restore already coalesces ranges
([view/__init__.py](../src/main/python/fman/impl/view/__init__.py#L197-L209)).

**F02.** [CompareDirectories](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L2057)
compares `iterdir` name sets exactly. Case-insensitive matching can be useful for
some Windows directories, but is not safe for every provider or Unicode name;
that behavior change is deferred. Counts include hidden/filtered entries that
cannot be selected, so the message can disagree with the selection.

**F03.** [Pack](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L1615)
names a multi-file archive `basename(pane path) + '.zip'`. At a drive root this
is `C:.zip`, which is not a valid ordinary archive filename. A trailing-slash
root fixture instead produces `.zip`.

**F04.** [_Delete](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L161)
asks "Do you want to continue?" with the global `show_alert` instead of
`self.show_alert`, so the progress dialog can pop up over the question. The
prompt has no default button.

### Reviewed Cleanup Candidates

| ID  | Finding                                                           | Where                                  |
| --- | ----------------------------------------------------------------- | -------------------------------------- |
| U01 | Symlink checks `file://` in `is_visible`, `__call__` and per file | `Symlink`                              |
| U02 | Pane-count precondition; retained for direct invocation           | `_OpenInPaneCommand`                   |
| U03 | Re-checks `is_visible()` inside `__call__`                        | `SyncPaneLocation`                     |
| U04 | Unused local `files`                                              | `CopyPathsToClipboard`                 |
| U05 | Constant locals `trash`, `native_fm` left by the platform cleanup | `MoveToTrash`, `OpenNativeFileManager` |
| U06 | Stale comment about `file:///` on Unix                            | `go_up`                                |

All in [commands/__init__.py](../src/main/resources/base/Plugins/Core/core/commands/__init__.py):
[U01](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L721),
[U02](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L1076),
[U03](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L1713),
[U04](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L922),
[U05 trash](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L98),
[U05 native_fm](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L914),
[U06](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L221).

### Rejected Claims

Verified as non-issues: `not x & y` "precedence bugs" in the local filesystem
(Python binds `&` before `not`); 7-Zip wildcard handling (every call passes
`-spd`); an "undefined `code`" in the fd engine (the exception propagates);
ripgrep's doubled path in the byte budget (intentional estimate); UI "races"
and stale focus widgets (synchronous or already guarded paths).

## Decisions

| IDs     | Recommendation                                        | Decision |
| ------- | ----------------------------------------------------- | -------- |
| F01     | Fix: batch full-row mutation and range-based readback | Pending  |
| F01 measurements | Add three-size selection cases and run full current-code reference | Approved |
| F02     | Fix selectable counts/messages; keep exact names     | Pending  |
| F02 case matching | Defer provider-aware case-insensitive matching | Pending |
| F03     | Fix: `C.zip` at drive roots; `archive.zip` for nameless roots | Pending |
| F04     | Fix: use `self.show_alert` with default `YES`         | Pending  |
| U01-U03 | Keep execution and final-operand guards               | Pending  |
| U04-U06 | Remove only the unused local, constant locals and stale comment | Pending |

## Design

- **F01 mutation.** Keep ownership in `FileListView`. Resolve URLs with
  `model().find`, preserving string rejection and both `ignore_errors` modes.
  Collect successful rows, deduplicate/sort and coalesce contiguous runs into
  full-width `QItemSelection` ranges. Apply once with `Select`/`Deselect`;
  full-width ranges need no additional `Rows` expansion. Flush the successful
  prefix before propagating a lookup or iterator error. Empty/no-op input does
  not move the cursor, scroll or emit an artificial notification. Selection
  observers receive the final batch, including the prefix on failure, rather
  than a signal for each URL.
- **F01 readback.** `SingleRowMode` already enforces row selection. Enumerate
  `selectionModel().selection()` in its existing range order, deduplicate row
  indices and map them to URLs once. Verify equality with Qt's `selectedRows(0)`
  ordering/membership on small fixtures. Keep Qt's existing readback for
  partial-column selections so such rows are not incorrectly treated as marked.
  Do not introduce a second authoritative mark store or change snapshot restore.
- **F02.** Obtain both complete name sets before changing either selection;
  retain the existing listing-failure behavior. Compare exact names across all
  providers, then clear/select the full differences through the public pane API.
  Read each pane's resulting selection once for selectable counts, using F01's
  readback improvement. Never filter the comparison sets first: a hidden match
  in the opposite pane still counts as present. Base the true-equality message
  on complete sets; distinguish differences that exist but cannot currently be
  selected. Counts/messages explicitly refer to selected visible differences.
- **F03.** Use the drive letter for a local drive root (`C.zip`), accepting both
  canonical and trailing-slash forms. Use `archive.zip` for nameless roots.
  Preserve ordinary folder, UNC share and single-file naming.
- **F04.** Replace the global call with `self.show_alert(message,
  YES | NO | YES_TO_ALL, YES)`.
- **U01-U03.** Retain all current guards; visibility is not an execution check.
- **U04-U06.** Delete the unused join result, inline the two constant strings
  without changing messages, and remove only the stale Unix comment.

Qt widgets/models and selection access remain on the Qt thread. No persistence
or threading change. Existing exceptions/messages remain except F02's corrected
comparison result. No new worker, cancellation protocol or stale-result channel
is needed for these synchronous changes.

F01 performance instrumentation belongs in
[src/performancetest](../src/performancetest/README.md), not the application.
Add a separate catalog workload for selection setup and readback. The existing
Refresh / Selection workload times reloads after untimed mark setup; it does not
measure the freeze described in F01. Route the new workload through the real
pane and retain its measurements in versioned records and the HTML report.

## Alternatives

- Use `QTableView.selectAll` plus deselect for Invert: covers one caller only.
- Leave F01 to plug-ins: every caller would need its own workaround.
- Coalesce mutation only: leaves the measured fragmented `selectedRows` cost.
- Make selection all-or-nothing: unnecessarily changes strict error behavior.
- Use unconditional `casefold()`: merges distinct names; directory/provider-aware
  case handling is deferred rather than adding per-file filesystem queries.
- Maintain independent selection state or select asynchronously: broader changes
  to painting, keyboard/mouse behavior and snapshot restore; consider only if
  measured Qt mutation costs prevent the focused implementation meeting its gates.

## Runtime Effects

F01 adds O(k) temporary row storage and O(k log k) sorting for k requested rows.
Full-row readback visits ranges/selected rows once instead of repeatedly asking
Qt whether each row is selected. Coalescing benefits contiguous runs; Qt's cost
for fragmented or overlapping mutation remains a measured risk, not a claimed
linear-time guarantee. F02 adds one selected-file read per pane but no additional
directory listing. F03/F04 and cleanup add no recurring work.

No application startup cost, background jobs or persistent selection caches are
added. Only invoked commands/readback do work; the disabled status-bar path remains
inactive. Existing selection/status observers still operate on the Qt thread.

The planned selection probes run only when the performance suite is explicitly
requested. They add no application startup work, recurring signals or idle
timers. Reuse isolated settings and read-only synthetic fixtures. Heartbeat and
queue probes are active only during timed operations; child processes have a
documented timeout and record failures rather than hanging indefinitely.

## Tests

Launcher (repository environment, native Windows Qt, 180-second timeout):

```powershell
python -c "import build, os, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM'] = 'windows'; env['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'unittest', '-v'] + sys.argv[1:], env=env, timeout=180).returncode)" <modules>
```

| IDs     | Existing modules                                                  | New checks (planned)                                |
| ------- | ----------------------------------------------------------------- | --------------------------------------------------- |
| F01 | `fman_integrationtest.test_qt.SortedFileSystemModelIT` | Mutation/readback equivalence, contiguous/scattered rows, duplicates, empty/string input, both error modes, prefix effects, failing iterators, partial-column fallback, signal counts, cursor/scroll and snapshot restore |
| F02 | `core.tests.commands.test___init__`, `core.tests.test_comparator` | Exact case/Unicode distinctions, mixed/archive providers, hidden opposite matches, unequal filters, no visible differences versus true equality, listing failure preserves selections |
| F03 | `core.tests.commands.test___init__` | Canonical `as_url('C:\\')`, trailing-slash root, normal folder, UNC share, virtual/nameless root and unchanged single-file suggestion; cancel prompt to avoid archive creation |
| F04 | `core.tests.commands.test___init__` | Mocked failures use task alert; explicit default `YES`; `NO` stops, `YES` continues, `YES_TO_ALL` suppresses later prompts; no real deletion |
| U01-U06 | `core.tests.commands.test___init__` | Retained single-pane behavior and symlink guards; unchanged clipboard text and Explorer/Recycle Bin messages without using the system clipboard |

Use the F01 class above immediately after each view edit; add cases to its existing
`SortedFileSystemModelAT` owner. For F02-F04 and cleanup, run the commands module
immediately after each localized edit; run the comparator module after F02 as
the neighboring compatibility gate. Performance-tool edits use the adjacent
tooling checks, never the application-wide test suite. Manually check multi-row
marking, inversion, filtered comparison and F04 dialog stacking on native Windows.

### Selection Measurements (Approved)

Add stable workload IDs `selection.small`, `selection.medium`, `selection.large` to
[catalog.yaml](../src/performancetest/catalog.yaml) and route it through
[suite.py](../src/performancetest/python/fman_performancetest/suite.py).
Use flat folders of 256, 50,000 and 200,000 files, as confirmed by the user.
The medium flat fixture is new; the existing 50,000-file recursive tree does not
represent a 50,000-row pane. Preserve the existing eleven workloads unchanged.
Use isolated settings, fixed viewport/DPI and warm caches. Each selection case
gets three fresh-process repetitions, isolating failures and cumulative Qt state.

- Time selecting 10,000 and 20,000 URLs in contiguous, alternating-row and
  deterministically scattered patterns in medium/large folders; use explicit
  64/128-row cases in the small folder. Record actual pane size and requested
  and selected counts; do not reduce large cases silently.
- Cover deselection, selecting already-marked or overlapping rows, select-all,
  clear and the real Invert Selection command. Inversion uses the entire pane;
  report its actual row count separately from the fixed-size URL cases.
- Time `get_selected_files` independently from mutation. Verify exact selected
  membership, duplicate-free readback and unchanged cursor/scroll after timing.
- Record operation wall time, process CPU time, dispatch-to-completed-paint
  latency, maximum active heartbeat gap and posted-event queue delay. Include
  the final blocked interval even if no timer fires while the UI is frozen.
- Keep the standard status-disabled baseline and include separately identified
  per-pane status-enabled cases so selection notifications and status reads are
  covered without depending on which pane has native window focus.
- Retain every size/pattern/action metric through the statistics-only storage in
  [records.py](../src/performancetest/python/fman_performancetest/records.py).
  Show selection as distinct from refresh in the HTML report, with individual
  cases visible rather than only an average.
- Increment catalog/relevant test revisions and retain compatibility checks.
  Collect before/after with the same final harness and fixture definitions.
  Timeouts are recorded failures, not zero-duration samples or omitted cases.

The implemented matrix has 36 cases per size (108 distinct cases, 324 child
executions): selection at both counts for each shape; reselect/overlap/deselect
at the larger count; full-pane select-all/clear/invert; both status modes.
Each child is bounded to 60 seconds including startup and untimed setup. Progress
records preserve completed stages after a timeout, and the parent continues with
remaining cases/workloads. Failed runs retain their report and immutable run ID
without replacing successful version history. Start/end source hashes must agree.

Add focused tooling regressions beside the existing performance tests for
catalog validation, dispatch, row counts, timed paint boundaries, blocked-loop
probes, metric retention and report/history presentation. These remain outside
normal application test discovery. Update performance-suite usage documentation
when the workload is implemented.

Planned measurement commands, after implementation:

```powershell
python build.py measure
python src/performancetest/run.py suite --test "selection.*"
```

Before implementation, agree numerical operation/paint and event-loop-stall
budgets for the 20,000-URL cases. Proposed limits on the recorded reference
machine, checked against the maximum of all three fresh-process repetitions:

| Metric | Proposed Maximum |
| --- | ---: |
| Select or deselect operation | 100 ms |
| Selected-file readback | 50 ms |
| Dispatch to completed pane paint for mutation | 150 ms |
| Active heartbeat gap or posted-event queue delay | 100 ms |

Apply these to every 20,000-URL shape in both status modes, not an average across
cases. Full-pane select-all/clear/inversion measurements report their actual
200,000-entry size separately; these limits are not a claim about those larger
operations. Baseline timeouts remain recorded failures. Retain before/after run
IDs with the same final harness and fixture definitions.

These are proposed acceptance targets, not measured results or promises. If
fragmented Qt mutation misses the agreed gate, do not mark F01 fixed or silently
loosen the limit: return with the failing measurements and a separate selection
model design for approval. Benchmark implementation and the current-code reference
are approved; application optimizations and the proposed budgets are not.

## Implementation Steps

1. Complete the approved benchmark cases and full current-code reference before
  application edits. Separately approve application decisions and numerical budgets.
2. Implement F03, then F04, then U04-U06, each with immediate focused tests.
  Do not remove U01-U03.
3. Add F01 compatibility regressions and the versioned selection workload,
  metric/report coverage and tooling tests. Capture the unchanged application's
  bounded baseline using that final harness before changing view behavior.
4. Batch F01 mutations with prefix-error semantics; run the focused Qt class.
  Implement range-based readback and rerun it, including ordering equivalence.
5. Implement F02 count/message correctness on top of the improved readback;
  run commands/comparator regressions. Keep case matching unchanged.
6. Collect after measurements, compare every shape and validate retained reports.
  Resolve any missed gate before declaring F01 complete; scope expansion needs
  approval. Small fixes can be accepted independently if F01 remains blocked.
7. Run the focused combined/native manual gates, update usage documentation and
  changelog for implemented changes, and complete task bookkeeping only when
  every included item is accepted or explicitly deferred.

## Acceptance Criteria

- Approved findings fixed or explicitly deferred.
- U01-U03 still enforce existing direct-invocation and operand behavior.
- Exact-name comparison remains provider-neutral; displayed counts match actual
  selections without reporting equality when only hidden differences exist.
- Root archive suggestions are usable; delete prompts use the task dialog and
  retain their specified continuation behavior.
- Selection membership, readback order, strict prefix effects, cursor and scroll
  satisfy focused compatibility tests; notifications follow the batched contract.
- Every 20,000-URL shape meets the approved numerical limits, or F01 remains
  incomplete pending an explicit revised decision.
- Large-selection mutation and readback are included in `build.py measure` and
  its retained version reports; all required cases and timeout failures remain
  visible. Agreed numerical latency/stall budgets are checked per case.
- Focused tests pass; skips recorded.

## Reviewers

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Recorded four verified bugs and six unneeded edge cases from a code
  review; F01 measured with an offscreen Qt probe. Rejected false-positive
  claims listed. Decisions pending.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Reviewed the current bugs/edge-cases proposal, not the earlier
  eight-candidate performance plan. Confirmed live execution guards, casefold
  collisions and strict selection error semantics with focused probes. One-call
  scattered Qt selections still have costly reads. Baseline: 143 run, 142 passed,
  one expected symlink-privilege skip. Revisions required; no application changes.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Added the user-requested large-selection performance-suite requirement
  to the plan, including mutation/readback, selection shapes, active UI-stall
  probes, retained records and report coverage. Implementation remains pending;
  this update does not approve code changes or resolve earlier review findings.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Confirmed R1-R5 remain unresolved in the operative proposal. Added
  comparison/filter and drive-root fixture clarifications; reproduced F03's
  suggestion and F04's alert routing. Native Windows baseline: 143 run,
  142 passed, one expected skip. Revisions required; no implementation approval.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revised the recommended plan to retain U01-U03, defer case-insensitive
  matching, fix comparison counts/messages, preserve selection prefix errors and
  address range-based readback. Selected root names, bounded focused gates and
  proposed numerical performance limits. Broader selection redesign requires
  approval if measured gates fail. Decisions remain pending; no code changes.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User approved benchmark implementation and the full current-code
  reference, confirming flat 256/50,000/200,000-file folders. Selected 36 cases
  per size, fresh-process isolation, a 60-second child limit and retained partial
  measurements/failures. Application changes and performance budgets remain pending.

## Implementer

### 2026_10_01 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented the approved benchmark portion only: three selection
  workloads, deterministic shapes/actions, real pane mutation/readback/paint
  timing, event-loop probes, retained failures, source-stability checks and HTML
  presentation. Full reference and final tooling validation are pending. This
  task stays in Plan because the application-fix portion is not implemented.

## Independent Review

This review applies to the current four-bug/six-cleanup proposal. It does not
restore or overwrite the earlier eight performance ideas. Keep user decisions
pending; the findings below are design revisions, not implementation approval.

### R1 (P2): Keep Live Execution Guards in U01-U03

[PaneCommandRegistry](../src/main/python/fman/impl/plugins/command_registry.py#L130)
executes commands without checking `is_visible()`. Visibility controls UI
exposure, not direct plug-in or key-binding invocation. A hidden test command
was still executed by the registry in a synchronous dispatch probe.

- **U01:** Symlink's per-file checks validate explicit operands and the final
  destination, not merely the two pane locations. `_TreeCommand` accepts
  `files`/`dest_dir` and lets the destination prompt change the target. A direct
  `Symlink._call` probe with an archive operand refused before `os.symlink`.
  Removing these checks would remove that safety boundary. Retain final-operand
  checks and local-pane preflight unless an equivalent boundary is proven.
- **U02/U03:** Two panes are the normal application layout, not an invariant
  enforced at every command entry. Single-pane fixtures and direct calls exist.
  `SyncPaneLocationTest.test_single_pane_invocation_reports_without_navigation`
  explicitly preserves the no-navigation/status-message behavior. The matching
  runtime probe passed. Keep that guard and the pane-count precondition in
  `_OpenInPaneCommand`; do not delete supported tests as obsolete edge cases.

Required revision: remove U01-U03 from blanket deletion or identify an
equivalent execution guard. Add direct-dispatch, explicit non-local operand,
changed-destination and single-pane regressions. U04-U06 can remain separately
considered local cleanup.

### R2 (P2): Do Not Use Unconditional Casefold Identity for F02

[CompareDirectories](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)
is not limited to ordinary case-insensitive local folders. Archive and virtual
providers can distinguish case. Unicode `casefold()` also merges names that
Windows can store as separate files: a disposable native-filesystem probe
created both `stra\u00dfe.txt` (Unicode-escaped here) and `strasse.txt`, confirmed
different file identities and confirmed equal casefold keys.

Required revision: decide and document comparison semantics before selecting
the key. Preserve original names and all collisions; do not store a single name
per folded key. Retain exact comparison for providers without an explicit safe
case-insensitive contract, or make the intended alternate semantics an approved
behavior change. Cover Unicode collisions, case-sensitive archive names and
mixed providers. Resolve visible-only versus all-entry counting explicitly,
including an active text filter, before implementation. Keep the existing
listing-failure behavior that preserves both selections.

### R3 (P2): Define F01's Partial-Failure Semantics

The current [FileListView.select/deselect](../src/main/python/fman/impl/view/__init__.py)
applies each successful row immediately. With `ignore_errors=False`, input
`[first, missing, last]` changes `first` and then raises `ValueError`. An
extracted-method probe confirmed this for both methods. The proposed resolve-all
then-apply design would raise before changing anything.

The public `DirectoryPane` wrapper uses `ignore_errors=True`; retain its
missing-URL behavior. The strict view path still exists, and input iterators
can also fail partway through consumption. The Scope's unchanged-semantics
promise needs an explicit decision for those paths.

Required revision: preserve successful-prefix effects before propagating an
error, or approve/document all-or-nothing behavior rather than silently changing
it. Add empty, duplicate, string-input, partial iterator failure and both
`ignore_errors` modes to regressions. Specify selection-notification and returned
selection-order expectations; batching intentionally changes signal frequency.

### R4 (P2): Scope F01's Performance Claim to Selection Shape

One `QItemSelectionModel.select` call is not necessarily one range. Scattered
rows produce many ranges, and Qt still spends substantial time enumerating them.
A three-sample component probe with one-column in-memory Qt models measured:

| Marked Rows | Shape | Ranges | Bulk Select Median | selectedRows Median |
| ----------: | ----- | -----: | -----------------: | ------------------: |
| 1,000 | Contiguous | 1 | 0.004 ms | 0.300 ms |
| 1,000 | Every other row | 1,000 | 2.003 ms | 43.026 ms |
| 2,000 | Contiguous | 1 | 0.006 ms | 0.725 ms |
| 2,000 | Every other row | 2,000 | 7.533 ms | 169.534 ms |

Required revision: describe coalescing as an improvement for contiguous runs,
not a general elimination of quadratic work. Measure contiguous, scattered,
already-selected and deselection paths, including `get_selected_files`, on the
actual pane model. Define a measurable latency budget and fixture shape for
the 20,000-URL acceptance criterion. Either narrow the claim or separately
approve further work if fragmented-selection reads must also meet that budget.
The original 10,000/20,000 timings were not rerun by this reviewer; these smaller
component measurements do not establish end-to-end pane latency.

### R5 (P3): Make the Implementation Gates Focused and Bounded

F01 currently names the whole `fman_integrationtest.test_qt` module. Choose the
existing selection/model classes that own its behavior instead of running every
unrelated feature fixture. The launcher also lacks a subprocess timeout.

Required revision: add a bounded timeout and fault-handler output, and name the
exact immediate gate for each first edit. Keep the native/GUI checks explicit
where offscreen cannot establish behavior. F04 tests should assert task-alert
routing and Yes/No/Yes-to-all/default behavior without deleting real files.
F03 should cover drive roots, UNC share roots, virtual roots and ordinary folders.

### Review Validation

Fresh focused baseline: **143 run, 142 passed, one expected skip**, offscreen Qt,
2.360 seconds. The skipped comparator alias test could not create a symlink
without Windows privilege; no elevation was requested.

Exact baseline command, run from the repository root:

```powershell
@'
import os
import subprocess
import sys
import build
modules = [
    'core.tests.commands.test___init__',
    'core.tests.test_comparator',
    'fman_integrationtest.test_qt.SortedFileSystemModelIT',
]
environment = build._environment()
environment['PYTHONDONTWRITEBYTECODE'] = '1'
environment['QT_QPA_PLATFORM'] = 'offscreen'
environment['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
raise SystemExit(subprocess.run([sys.executable, '-B', '-X', 'faulthandler',
    '-m', 'unittest', '-v', *modules], env=environment, timeout=180).returncode)
'@ | python -B -
```

Five bounded probes confirmed registry visibility bypass, direct single-pane
sync, non-local symlink refusal with the OS call mocked, distinct Windows names
sharing a casefold key, and selection-prefix behavior on errors. Selection timing
used 1,000/2,000 marked rows, contiguous/every-other-row inputs and three-sample
medians; selected row identities were verified after each operation. All models
were in memory, and the filename fixture was a disposable directory.

Verdict: **revisions required before implementation**. F01 remains worthwhile,
but its compatibility and performance claims need qualification. F02 needs safe
name semantics. U01-U03 are not established dead checks. F03/F04 remain plausible
local fixes pending user decisions and the specified regressions.

Only this task document was changed to record the review. No application source,
tests, dependencies, settings or changelog were edited. No full suite, large-folder
GUI benchmark, build, freeze/package, privilege escalation or remote operation
ran. The approved task scope and prior provenance are preserved.

## Maintainer Review

Verdict: **revisions required before implementation**. The added performance
workload is useful, but the Decisions, Design and Runtime Effects sections have
not incorporated R1-R5. The existing blockers remain:

- **P2, U01-U03:** Blanket removal still includes live execution guards.
  Visibility is not dispatch authorization; preserve final symlink operand checks
  and the existing single-pane behavior. See [R1](#r1-p2-keep-live-execution-guards-in-u01-u03).
- **P2, F02:** Unconditional `casefold()` conflates distinct names, including
  case-sensitive archive entries. Decide provider-specific comparison and
  collision handling before implementation. See [R2](#r2-p2-do-not-use-unconditional-casefold-identity-for-f02).
- **P2, F01 compatibility:** Resolve-all-then-apply changes the successful-prefix
  effects of strict selection errors. Preserve those effects or explicitly
  approve the change, including notification/order expectations. See [R3](#r3-p2-define-f01s-partial-failure-semantics).
- **P2, F01 performance:** One selection call does not eliminate fragmented-range
  readback costs. Narrow the runtime claim and agree per-shape mutation/readback
  and UI-stall budgets before accepting the 20,000-URL goal. See [R4](#r4-p2-scope-f01s-performance-claim-to-selection-shape).

F02 needs a precise filtering rule: identical folders containing `alpha` and
`beta`, with opposite panes filtered to different names, must not become different
folders accidentally. To retain current full-directory comparison semantics,
compute differences against both complete name sets, then restrict reported and
selected differences to selectable entries. Comparing only visible subsets is
a separate behavior decision. Test unequal filters and an opposite-side hidden
match, not only hidden unmatched files.

F03's regression must use the canonical root `as_url('C:\\') == 'file://C:'`:
the current suggested name is `C:.zip`. A direct trailing-slash fixture
`file://C:/` instead produces `.zip`; testing only that form misses the stated
defect. An ordinary folder still suggests `work.zip`.

F04 is supported by the task/progress-dialog path: the global call bypasses
`ProgressDialog.show_alert`, which temporarily suppresses delayed progress-dialog
appearance. The proposed task method accepts the explicit default argument.
F03/F04 and U04-U06 remain reasonable localized changes pending user decisions;
retain R5's focused, bounded regression requirements.

### Maintainer Validation

Native Windows Qt baseline: **143 run, 142 passed, one expected skip**, 2.256 s.
The comparator symlink test lacked Windows symlink privilege; no elevation was
attempted. Exact command:

```powershell
@'
import os
import subprocess
import sys
import build
modules = [
    'core.tests.commands.test___init__',
    'core.tests.test_comparator',
    'fman_integrationtest.test_qt.SortedFileSystemModelIT',
]
environment = build._environment()
environment['PYTHONDONTWRITEBYTECODE'] = '1'
environment['QT_QPA_PLATFORM'] = 'windows'
environment['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
raise SystemExit(subprocess.run([sys.executable, '-B', '-X', 'faulthandler',
    '-m', 'unittest', '-v', *modules], env=environment, timeout=180).returncode)
'@ | python -B -
```

A separate 60-second-bounded probe confirmed strict select/deselect prefix
effects with `[first, missing, last]`, all three Pack suggestions above with
the prompt canceled, and global rather than task alert routing after a mocked
delete failure followed by `No`. It also checked Unicode casefold collisions,
distinct case-only entries in an in-memory ZIP, and unequal-filter set semantics.
An initial probe incorrectly expected the canonical-root suggestion from the
trailing-slash fixture; the corrected probe passed in full.

No archive creation or real deletion was attempted by these probes. No large
selection timings were rerun, so this review does not certify performance budgets.
Only this task document was edited; application code and pending decisions remain
unchanged.
