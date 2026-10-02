# Code Review 006: Bugs and Unneeded Edge Cases

Status: Implemented scope complete and archived for independent implementation
review at the user's request. F01 readback/report work, F02-F04 and U04-U06 are
implemented; U01-U03 remain unchanged. The previous focused gate passed 160 of
161 tests per native/offscreen mode, with one expected skip each. The bounded
closure check passed both native selection regressions, all five patterns at
256 and 200,000 rows, and the separate small-pane startup path.
Historical startup/state failures were not reproduced; their root causes are
not established. Earlier failed records and the qualified readback comparison
remain unchanged. Selection mutation, its ordering/notification contract and
20,000-URL budgets remain deferred. No complete benchmark was rerun for closure.

The recommendations below incorporate the 2026-10-01 reviews. Review sections
record earlier proposal versions; their historical text is preserved.

## Task

Fix verified bugs and remove unneeded edge-case handling found in the 2026-10-01
code review. Focus on real-world effect: large folders and user interactions.

## Scope

Implemented: F01 readback, F02 count/message correctness, F03/F04, U04-U06,
their focused regressions, and the versioned performance workload/report.
The user approved the small command fixes and limited cleanup on 2026-10-02.
F01 mutation remains a separate, deferred decision, not part of that approval.
Closure covers the implemented scope and passing bounded checks, not resolution
of historical failure causes or completion of the deferred mutation proposal.
The approved benchmark tooling also includes opt-in medium versions of all
folder-based workloads. On 2026-10-02 the user separately approved readback-only
optimization: split its costs, read ranges, bulk-convert snapshot URLs, preserve
behavior and compare through regular `build.py measure`. No mutation change,
new selection state, background worker or full-mode measurement is included.
The user also requested a standalone Readback row, separate QuickView Images/Text
rows, TXT/Python/Markdown cases and measured improvement in the changelog.

Excluded: new features, refactoring beyond each finding, performance work
outside F01, case-insensitive filename matching, removal of U01-U03, and the
rejected claims below. Replacing Qt's selection model or introducing asynchronous
selection requires a separate design decision if the focused F01 approach fails.

Compatibility: `DirectoryPane.select`/`deselect` keep their signatures and
missing-URL behavior. Strict calls retain successful-prefix effects on errors,
including iterator failures. The implemented readback changes no mutation or
selection notifications and preserves Qt's existing readback order. Proposed
mutation batching remains a separate decision. No settings, command identifiers
or provider contracts change.

## Handoff Summary

### Confirmed Findings

- User definition: selection latency is the interval from the selection action
  until the UI can respond to the next operation, including work naturally
  triggered by that action. A quick paint alone does not establish responsiveness.
- Selecting 1,000 explicit URLs takes roughly 240 ms in mutation on the Qt thread.
  [FileListView.select/deselect](../src/main/python/fman/impl/view/__init__.py#L97)
  updates Qt once per URL. This is a real stall in that API path, relevant to
  commands such as Invert, Compare directories and plug-ins using the API.
- Select All follows [Qt's bulk path](../src/main/python/fman/impl/widgets.py#L106),
  not that per-URL loop. For 200,000 files, mutation was 0.05 ms and paint 8.51 ms.
  These are phase measurements, not proof of the full input-ready latency.
- [Selected-file readback](../src/main/python/fman/impl/view/__init__.py#L117)
  previously stalled in Qt enumeration and per-index URL conversion. A separate
  diagnostic measured those phases at 1745.06 and 218.60 ms; direct snapshot URL
  construction took 74.63 ms. Ordered-range readback is now implemented, with
  exact-order compatibility checks. The comparable large-folder medians are
  2481.61 to 66.17 ms, not a claim about normal Select All input latency.
- The benchmark explicitly calls `get_selected_files()` after selection paint.
  Revision 4's `responsive_ms` includes this injected operation and then a Qt
  callback. Calling that value user-visible selection latency was misleading.
- Revision 5 records `input_ready_ms` through a posted Down key, verified cursor
  movement and completed paint, before diagnostic readback. Native regressions
  include blocking queued observers and the actual enabled-status refresh timer.
- Regular complex patterns select 64 of 256 rows or 1,000 of 200,000 rows.
  Earlier 20,000-row Qt stress probes used different operations/shapes; their
  30-plus-second costs do not predict bulk Select All. The latest catalog-10
  selection cases passed; an earlier small-selection state failure remains
  unresolved and must not be dismissed as harmless.

### Baseline And Completed Work

- F02-F04 and U04-U06 passed command/comparator checks and native/offscreen Qt
  regressions. Comparison counts use actual selections, archive root suggestions
  are usable, and delete continuation uses the task-owned dialog. No selection
  mutation, benchmark definition or saved measurement changed in this follow-up.
- Corrected baseline `49ad1a06-e227-4d64-8e7a-c9d9aa7e9aba`: regular `measure`,
  thirteen workloads, three repetitions, 284.04 seconds. Catalog revision 9 and
  selection revision 5; input-ready headlines are 15.12 ms small and 97.87 ms
  large. Published as `Unreleased`; all twelve older run files remain unchanged.
- Successful run `bca3f29b-00ce-4065-a95e-5b720f15e681`: regular `measure`,
  thirteen workloads, three repetitions, 264.64 seconds; published as `Unreleased`
  under `UserSettings/Performance`. Application source was unchanged between
  attempts. Keep its immutable JSON; do not relabel its composite timings as a
  newly measured input-ready baseline.
- Its selection headline means, 12.25 ms small and 1,280.79 ms large, average
  five case medians including explicit readback. Large select-all's composite
  median was 5,147.95 ms. Neither the row mean nor the case median sums repetitions.
- QuickView's old unsupported-text assertion caused both workloads to fail.
  Revision 2 now verifies the existing text fixture's content/paint and image
  restoration. Fixture bytes and application behavior were not changed.
- Regular mode stays at thirteen workloads; `measure --full` adds six medium
  workloads on 50,000 files, with isolated `UserSettings/Performance/Full` history.
  Full mode has not been measured. Do not restore the oversized status/stress matrix.
- Report labels are `Pane Loading / Small`, `/ Large`, `/ Medium` and
  `Selections / Small`, `/ Large`, `/ Medium`. IDs and measurements are unchanged.

### Deferred Follow-Ups

1. The earlier wrong-folder startup and small-selection cursor/scroll failures
  were not reproduced in the bounded closure checks. Investigate their causes
  if they recur; neither these checks nor the expanded run explains the old
  failures or supplies a complete comparable before/after measurement.
2. Before mutation batching, define ordering and notification compatibility.
   Sorting rows can change readback order even when membership is identical;
   prefix effects on lookup/iterator errors must remain explicit.
3. Future before/after comparisons require the same final harness, environment
   and fixtures. Preserve the revision-5 baseline and all failed records, but do
   not bypass the catalog-10 compatibility rejection to claim a complete pair.
4. Run only regular `python build.py measure` when another benchmark is requested.
   Status remains disabled by default. Full-mode measurement, broad correctness
   runs and 20,000-URL performance budgets remain unapproved. The completed small
   fixes do not depend on accepting those future mutation gates.

## Findings

### Bugs

| ID  | Severity    | Finding                                                    | Where                                  |
| --- | ----------- | ---------------------------------------------------------- | -------------------------------------- |
| F01 | Medium-High | Per-row selection is quadratic and blocks the UI thread    | `FileListView.select`/`deselect`       |
| F02 | Low         | Compare-directory counts include unselectable entries      | `CompareDirectories`                   |
| F03 | Low         | Pack from a drive root suggests the invalid name `C:.zip`  | `Pack.__call__`                        |
| F04 | Low         | Delete "continue?" prompt bypasses the progress dialog     | `_Delete.__call__`                     |

**F01.** [FileListView.select/deselect](../src/main/python/fman/impl/view/__init__.py#L97-L116)
call `selectionModel().select(row)` once per URL on the Qt thread. The earlier
offscreen probe showed roughly quadratic growth for its per-row selection
patterns and expensive later `selectedRows()` calls. This does not establish
the same cost for Qt's bulk Select All path or every selection shape:

| Rows   | Per-row select | `selectedRows` | One range select |
| -----: | -------------: | -------------: | ---------------: |
| 10,000 | 8.8 s          | 4.1 s          | < 1 ms           |
| 20,000 | 36 s           | 16 s           | < 1 ms           |

Callers: [Invert selection](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L993),
[Compare directories](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L2057)
and plug-ins using `pane.select`. Snapshot restore already coalesces ranges
([view/__init__.py](../src/main/python/fman/impl/view/__init__.py#L197-L209)).

**F02 (fixed).** [CompareDirectories](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L2057)
compares `iterdir` name sets exactly. Case-insensitive matching can be useful for
some Windows directories, but is not safe for every provider or Unicode name;
that behavior change is deferred. Counts previously included unselectable
hidden/filtered entries. The message now reports actual selected visible
differences and distinguishes unselectable differences from true name equality.

**F03 (fixed).** [Pack](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L1615)
previously suggested `C:.zip` at a canonical drive root or `.zip` with a trailing
slash. It now suggests `C.zip` for local drive roots and `archive.zip` for
nameless roots, preserving folder/UNC names and single-file naming.

**F04 (fixed).** [_Delete](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L161)
now asks "Do you want to continue?" through `self.show_alert`, preventing automatic
progress popups while the question is shown. The explicit default is `YES`;
stop, continue and continue-all behavior is covered without real deletion.

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
| F01 mutation | Decide ordering/notifications before batching | Deferred; not approved |
| F01 readback | Ordered ranges and bulk snapshot URL conversion | Implemented; complete paired comparison unresolved |
| F01 measurements | Five patterns per small/large folder; revision 5 input-ready metric implemented | Corrected baseline passed |
| Full medium benchmarks | Opt-in `measure --full` adds all six medium workloads and separate history | Approved |
| F02     | Fix selectable counts/messages; keep exact names     | Implemented |
| F02 case matching | Defer provider-aware case-insensitive matching | Deferred |
| F03     | Fix: `C.zip` at drive roots; `archive.zip` for nameless roots | Implemented |
| F04     | Fix: use `self.show_alert` with default `YES`         | Implemented |
| U01-U03 | Keep execution and final-operand guards               | Retained unchanged |
| U04-U06 | Remove only the unused local, constant locals and stale comment | Implemented |

## Design

- **F01 mutation (deferred, not approved).** The sorting/batching proposal below
  is a candidate, not an accepted compatibility contract. Resolve exact readback
  order and observer notification semantics before implementation.
  Keep ownership in `FileListView`. Resolve URLs with
  `model().find`, preserving string rejection and both `ignore_errors` modes.
  Collect successful rows, deduplicate/sort and coalesce contiguous runs into
  full-width `QItemSelection` ranges. Apply once with `Select`/`Deselect`;
  full-width ranges need no additional `Rows` expansion. Flush the successful
  prefix before propagating a lookup or iterator error. Empty/no-op input does
  not move the cursor, scroll or emit an artificial notification. Selection
  observers receive the final batch, including the prefix on failure, rather
  than a signal for each URL.
- **F01 readback (implemented).** `FileListView` reads existing full-width Qt
  ranges in their current order. One range uses a constant-size Python range;
  multiple ranges use insertion-ordered deduplication. Partial-column selections
  and models without the bulk method retain the original `selectedRows(0)` path.
  The identity proxy delegates `urls_for_rows` to `ListingModel`, which uses the
  existing visible-row mapping and immutable listing to build URLs with the
  existing `join` utility, without per-row Qt indexes or proxy mapping. Bounds
  are checked. All access remains on Qt; no cache, model scan, I/O, new selection
  authority, mutation change or snapshot-restore change is introduced.
- **F02 (implemented).** Obtain both complete name sets before changing either selection;
  retain the existing listing-failure behavior. Compare exact names across all
  providers, then clear/select the full differences through the public pane API.
  Read each pane's resulting selection once for selectable counts, using F01's
  readback improvement. Never filter the comparison sets first: a hidden match
  in the opposite pane still counts as present. Base the true-equality message
  on complete sets; distinguish differences that exist but cannot currently be
  selected. Counts/messages explicitly refer to selected visible differences.
  When only some differences are selectable, report that the remainder is hidden,
  filtered or otherwise unselectable.
- **F03 (implemented).** Use the drive letter for a local drive root (`C.zip`), accepting both
  canonical and trailing-slash forms. Use `archive.zip` for nameless roots.
  Preserve ordinary folder, UNC share and single-file naming.
- **F04 (implemented).** Replace the global call with `self.show_alert(message,
  YES | NO | YES_TO_ALL, YES)`.
- **U01-U03.** Retain all current guards; visibility is not an execution check.
- **U04-U06 (implemented).** Delete the unused join result, inline the two constant strings
  without changing messages, and remove only the stale Unix comment.

Qt widgets/models and selection access remain on the Qt thread. No persistence
or threading change. Existing exceptions/messages remain except F02's corrected
comparison result. No new worker, cancellation protocol or stale-result channel
is needed for these synchronous changes.

F01 performance instrumentation belongs in
[src/performancetest](../src/performancetest/README.md), not the application.
The separate selection workload implements the corrected timing contract below.
The existing
Refresh / Selection workload times reloads after untimed mark setup; it does not
measure the freeze described in F01. Route the new workload through the real
pane and retain its measurements in versioned records and the HTML report.

### Selection Latency Contract (Revision 5)

- Start at dispatch of the real selection action. Record whether a case uses a
  user command/input or the public multi-URL API; they are not interchangeable.
- Include synchronous work and naturally triggered queued callbacks that block
  the next operation. Verify a follow-up input is actually processed and required
  selection feedback is painted; neither first paint nor an arbitrary empty Qt
  callback alone proves the whole interaction has recovered.
- Trace selection-owned deferred work before choosing the completion barrier.
  Avoid arbitrary sleeps and do not require unrelated background work to finish.
- Do not inject `get_selected_files()` before the input-ready endpoint solely
  for the benchmark. If a production observer naturally invokes it, include that
  cost. Standalone readback and membership assertions run afterward as diagnostics.
- Keep active heartbeat/queue probes and per-case failure details. Preserve the
  five patterns, row counts, three repetitions and regular runtime budget. Keep
  the configured status mode explicit; investigate enabled status separately
  without silently doubling the default catalog.
- Use `input_ready_ms` and selection revision 5, introduced in catalog revision 9
  and retained in current catalog revision 10. Keep
  [selection.py](../src/performancetest/python/fman_performancetest/selection.py),
  the metric allowlist in [records.py](../src/performancetest/python/fman_performancetest/records.py),
  [report aggregation](../src/misc/performance_report.py), its template and usage
  docs together. Current headlines accept only the new metric; revision-4
  composite details remain readable without being substituted for input readiness.
- Preserve old records and identify incompatible definitions; never substitute
  old `paint_ms` or composite `responsive_ms` values for a missing input-ready
  metric. Capture a corrected baseline only when requested, before optimizing.

The concrete endpoint posts Down after the selection feedback paint and known
selection-owned Qt work, verifies the next row, and waits for its completed paint.
The enabled-status regression waits on the actual 150 ms refresh timer through
Qt-thread snapshot capture, not a sleep or background size-worker completion.
Regular runs remain status-disabled. Diagnostic readback and cursor restoration
occur after the endpoint. The probe includes event-dispatch overhead; it does not
certify physical input, arbitrary future observers or every selection command.

## Alternatives

For the report extension, reuse existing readback diagnostics and QuickView child
processes rather than adding duplicate timing workloads. Version only QuickView
fixtures to add real Python/Markdown content: changing v1 bytes would invalidate
historical fixtures silently. Text uses the mean of all three case medians;
readback uses the slowest case median so the expensive all-selected path remains
visible. Missing/failed cases suppress these aggregates.

- Use `QTableView.selectAll` plus deselect for Invert: covers one caller only.
- Leave F01 to plug-ins: every caller would need its own workaround.
- Coalesce mutation only: leaves the measured fragmented `selectedRows` cost.
- Make selection all-or-nothing: unnecessarily changes strict error behavior.
- Include an explicit post-selection readback in the headline: rejected for
  user-latency measurement unless the normal action itself requires that readback.
- Use unconditional `casefold()`: merges distinct names; directory/provider-aware
  case handling is deferred rather than adding per-file filesystem queries.
- Maintain independent selection state or select asynchronously: broader changes
  to painting, keyboard/mouse behavior and snapshot restore; consider only if
  measured Qt mutation costs prevent the focused implementation meeting its gates.

For the approved full-mode extension, use one catalog with optional definitions
instead of duplicating the complete catalog or expanding regular runs. Store an
effective catalog snapshot and separate full history so completeness and version
publication stay mode-specific without changing legacy record handling.

## Runtime Effects

The report extension is demand-only tooling. It adds no application startup or
idle work. QuickView adds two preview actions per repetition, no extra child
processes, and untimed content/format checks. New v2 flat folders replace two
empty fillers with Python/Markdown content at unchanged row counts; their first
preparation uses additional disk space and verified setup I/O. Regular mode never
prepares either medium fixture. Existing worker cancellation and benchmark child
bounds remain unchanged. Report aggregation is a small pass over saved statistics.

Implemented readback performs one pass over selected rows. A single range adds
no row-index collection; multiple ranges use O(k) temporary deduplication storage.
The returned O(k) URL list is still allocated on the Qt thread. No state survives
the call and the disabled/no-selection path returns an empty list without scanning.

Proposed, unapproved F01 batching adds O(k) temporary row storage and O(k log k) sorting for k requested rows.
Full-row readback visits ranges/selected rows once instead of repeatedly asking
Qt whether each row is selected. Coalescing benefits contiguous runs; Qt's cost
for fragmented or overlapping mutation remains a measured risk, not a claimed
linear-time guarantee. F02 adds one selected-file read per pane but no additional
directory listing. F03/F04 and cleanup add no recurring work.

No application startup cost, background jobs or persistent selection caches are
added. Only invoked commands/readback do work; the disabled status-bar path remains
inactive. Existing selection/status observers still operate on the Qt thread.

Selection probes run only when the performance suite is explicitly
requested. They add no application startup work, recurring signals or idle
timers. Reuse isolated settings and read-only synthetic fixtures. Heartbeat and
queue probes are active only during timed operations; child processes have a
documented timeout and record failures rather than hanging indefinitely.

Regular mode does no medium-fixture I/O. Full mode adds a 50,000-file flat
fixture, six workloads with three UI processes each, and six separate algorithm
passes for medium Filter/Fuzzy cases. Medium selections share five patterns per
process with a 25-second limit. Other workloads retain their existing limits.
Full mode takes longer and has no measured duration or two-to-three-minute cap.
Its reports and version index live under `UserSettings/Performance/Full`.

## Tests

Launcher (repository environment, native Windows Qt, 180-second timeout):

```powershell
python -c "import build, os, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM'] = 'windows'; env['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-X', 'faulthandler', '-m', 'unittest', '-v'] + sys.argv[1:], env=env, timeout=180).returncode)" <modules>
```

| IDs     | Existing modules                                                  | Coverage                                |
| ------- | ----------------------------------------------------------------- | --------------------------------------------------- |
| F01 | `fman_integrationtest.test_qt.SortedFileSystemModelIT` | Mutation/readback equivalence, contiguous/scattered rows, duplicates, empty/string input, both error modes, prefix effects, failing iterators, partial-column fallback, signal counts, cursor/scroll and snapshot restore |
| F02 | `core.tests.commands.test___init__`, `core.tests.test_comparator` | Exact case/Unicode distinctions, mixed/archive providers, hidden opposite matches, unequal filters, no visible differences versus true equality, listing failure preserves selections |
| F03 | `core.tests.commands.test___init__` | Canonical `as_url('C:\\')`, trailing-slash root, normal folder, UNC share, virtual/nameless root and unchanged single-file suggestion; cancel prompt to avoid archive creation |
| F04 | `core.tests.commands.test___init__`, `fman_integrationtest.test_qt.FilterBarIT` | Task alert/default/answers; real Qt popup suppression and restoration; no real deletion |
| U01-U06 | `core.tests.commands.test___init__` | Retained single-pane behavior and symlink guards; unchanged clipboard text and Explorer/Recycle Bin messages without using the system clipboard |

Use the F01 class above immediately after each view edit; add cases to its existing
`SortedFileSystemModelAT` owner. For F02-F04 and cleanup, run the commands module
immediately after each localized edit; run the comparator module after F02 as
the neighboring compatibility gate. Performance-tool edits use the adjacent
tooling checks, never the application-wide test suite. Real filtered comparison
and delete-dialog suppression now have native/offscreen Qt regressions.
Manual multi-row marking and inversion remain future mutation checks.

### Selection Measurements (Approved)

Use stable workload IDs `selection.small` and `selection.large` in
[catalog.yaml](../src/performancetest/catalog.yaml) and route it through
[suite.py](../src/performancetest/python/fman_performancetest/suite.py).
Reuse the existing 256-file and 200,000-file flat fixtures and preserve the original
eleven workloads. The regular suite excludes medium. The user's latest request
adds optional full mode, without restoring the earlier stress matrix.

- Exactly five patterns per size: single file, all files through `select_all`,
  contiguous block, alternating rows and deterministically scattered rows.
  The three complex patterns select 64 rows in the small folder and 1,000 in
  the large folder. Record actual pane and selected counts without silent caps.
- All five patterns share one loaded pane per repetition; clear selection
  outside timing before each pattern. Use three fresh processes per size,
  isolated settings, fixed viewport/DPI, warm caches and disabled status.
- Time `get_selected_files` independently from mutation. Verify exact selected
  membership, duplicate-free readback and unchanged cursor/scroll after timing.
- Record operation wall time, process CPU time, dispatch-to-completed-paint
  latency, maximum active heartbeat gap and posted-event queue delay. Include
  the final blocked interval even if no timer fires while the UI is frozen.
- Retain every size/pattern/action metric through the statistics-only storage in
  [records.py](../src/performancetest/python/fman_performancetest/records.py).
  Keep the two selection overview rows: `Selections / Small` and `Selections / Large`,
  followed by the separate `Selections Readback` row.
  Their target is the equal-weight mean of five real action-to-input-ready
  medians under the corrected contract above. Revision 4 still measures
  selection plus explicit readback and must not be mistaken for this target.
  Keep all phase metrics in details; fixture setup and benchmark-only assertions are excluded;
  suppress aggregates with missing or failed cases. The original eleven workloads,
  retained history location and `python build.py measure` behavior remain; regular
  mode now has thirteen workloads and sixteen rows including QuickView Images/Text.
- Increment catalog/relevant test revisions and retain compatibility checks.
  Collect before/after with the same final harness and fixture definitions.
  Timeouts are recorded failures, not zero-duration samples or omitted cases.

Added runtime must target at most two to three minutes beyond the original suite.
Six children have a 25-second limit each, including startup, untimed setup and
shutdown, giving 150 seconds of child-runtime allowance plus orchestration.
This limit is checked by tooling tests; actual added runtime remains unmeasured.
Progress records preserve completed stages on failure; unstarted patterns are
reported as not run, while later repetitions/workloads continue. Failed runs do
not replace successful history. Start/end source hashes must agree. Do not delete
the previously generated medium fixture or rewrite historical timing tables.

Existing focused tooling regressions cover catalog validation, dispatch, row
counts, timed paint boundaries, blocked-loop probes, metric retention and
report/history presentation. These remain outside normal application discovery;
the performance-suite usage documentation includes the implemented workloads.

The corrected native selection tests prove
that mutation stalls and blocking automatic selection observers increase the
input-ready metric, while an explicitly requested diagnostic readback after the
endpoint does not. Verify follow-up input handling, queued-observer delays,
paint completion, case membership and unchanged cursor/scroll. Update report
tests for the new metric, missing/incompatible data and persisted summaries.
The old injected-readback composite assertion was replaced; diagnostic readback
must start after the recorded input-ready endpoint.

Regular measurement command, only when a new run is requested:

```powershell
python build.py measure
```

### Full Medium Coverage (Approved)

`python build.py measure --full` adds `pane.load.medium`, `refresh.medium`,
`filter.medium`, `fuzzy.medium`, `quickview.medium` and `selection.medium` from
the catalog's `full_tests` list. Reuse `flat-medium-v1` (50,000 files, seed 1729).
Queries and protocols match the existing small/large workloads; recursive Find
remains the existing tree workload. Medium selections use five patterns, with
1,000 rows each for contiguous, alternating and scattered selections.

The full report has nineteen workloads and twenty-two rows. Its third selection
row is `Selections / Medium`; refresh averages 24 case medians and
navigation 42. QuickView uses `flat-medium-v2` and separate image/text rows;
Readback spans fifteen case medians. Missing/failed medium cases suppress those
aggregates. Regular mode has thirteen workloads and sixteen report rows; its
history location is unchanged. Full records use an
effective nineteen-test catalog and separate `UserSettings/Performance/Full`
history; incomplete runs never replace successful version entries.

Check default/full CLI forwarding, default fixture exclusion, full fixture
preparation, medium child dispatch, identical workload protocols, record
completeness, aggregate counts, separate history and old record readability.
Mocked runs and existing tiny-fixture tooling tests cover these contracts.
Full measurements are not requested.

### Future F01 Acceptance Probes (Not Approved)

These are conditional future mutation gates, not requirements for the completed
readback and command fixes. The regular suite does not certify 20,000-URL performance.
Before mutation implementation, explicitly approve separate operation/paint and stall
budgets and probes for those cases. Proposed limits on the recorded reference
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
model design for approval. Readback, F02-F04 and U04-U06 were approved separately
and are implemented. Mutation changes, these budgets and full-mode measurement
remain unapproved. Corrected regular measurements already exist; no new run is
requested by this command-fix follow-up.

## Implementation Steps

1. Completed: corrected input-ready measurement, ordered-range readback and its
   compatibility regressions. Preserve the qualified before/after results.
2. Completed: separate Selections Readback and QuickView Images/Text reporting;
   retain immutable fixtures, records and compatibility checks.
3. Completed: F03, F04, F02 and U04-U06, with immediate focused checks and final
   native/offscreen gates. Keep U01-U03 unchanged; update usage and changelog.
4. Completed: bounded current-code checks of both native selection regressions,
  all five patterns on each real fixture, and the small-pane startup path.
  All passed with unchanged guards; historical root causes remain unconfirmed.
5. Deferred: agree mutation ordering, notification and prefix-error semantics,
   then approve a bounded implementation and any additional performance gates.
6. Future measurements use regular `python build.py measure` only when requested.
  Archive the implemented scope for independent review, as the user requested
  after passing simple checks. Keep mutation and any recurring-failure
  investigation as explicit follow-ups, not silently completed work.

## Acceptance Criteria

- Current approved scope: readback/report work and F02-F04/U04-U06 are implemented.
  Remaining F01 mutation work is deferred and cannot be inferred as approved.
- User-approved archive gate: bounded current startup/selection checks pass.
  Historical failures remain documented as not reproduced, not fixed; a complete
  paired performance comparison is not claimed by this closure.
- U01-U03 still enforce existing direct-invocation and operand behavior.
- Exact-name comparison remains provider-neutral; displayed counts match actual
  selections without reporting equality when only hidden differences exist.
- Root archive suggestions are usable; delete prompts use the task dialog and
  retain their specified continuation behavior.
- Implemented readback preserves selection membership/order, cursor, scroll and
  notifications. Existing strict mutation prefix behavior remains unchanged.
- Selection responsiveness is validated using real action-to-next-input timing
  and automatic work, not first paint or benchmark-injected readback. Identify the
  tested settings and retain per-case results. The complete paired readback
  comparison remains unresolved; the later expanded run does not replace it.
- Conditional future mutation acceptance: approve ordering/notification semantics
  and numerical limits first. Only then require the agreed 20,000-URL shapes to
  meet them or return for a revised decision. These are not current closure gates
  for readback or the independently completed command fixes.
- Regular `build.py measure` preserves eleven original workloads and adds five
  selection patterns at each of two sizes. The report has sixteen rows, including
  separate Selections Readback and QuickView Images/Text entries.
  Six 25-second children bound added measurement work; all case details and
  failures remain visible. No medium fixture is accessed in regular runs.
- `measure --full` adds all six medium workloads, with the same modest five
  selection patterns. Full history is isolated and all nineteen workloads are
  required for publication; reports show medium rows and 24/42 refresh/navigation
  aggregates. Legacy records remain readable; full-mode measurements remain
  unrequested.
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

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Applied the user's scope correction: five patterns per small/large
  folder, two named aggregate rows in regular measure, no medium/status/stress
  matrix or full mode. Share one pane per repetition and bound six children to
  25 seconds each for the two-to-three-minute added-runtime target. Leave the
  benchmark stopped; application fixes and separate 20,000-row gates stay pending.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User clarified that opt-in full mode should add all medium-folder
  benchmarks, not selections alone. Keep regular scope and runtime unchanged,
  use six optional definitions and effective record catalogs, and isolate full
  history. Full refresh/navigation include medium; no stress matrix or run restart.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User requested a regular baseline, then required selection timing to
  include all interaction stalls. Add a paired end-to-end metric through paint,
  readback and Qt response instead of using paint-only headlines. Keep five
  patterns, existing sizes and disabled status. The first run failed QuickView's
  obsolete unsupported-text check; user approved updating that benchmark and
  rerunning regular measure without changing application code or fixture data.

### 2026_10_01 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Consolidated the handoff and corrected the earlier latency claim.
  Revision-4 readback is injected by the harness; its five-second cost does not
  establish normal Select All latency. Recorded measured mutation/readback
  stalls, unknown observer and cost splits, a real input-ready measurement gate,
  unchanged approvals, and unverified optimization proposals. Historical records
  remain intact; current guidance supersedes their composite-latency interpretation.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User approved a regular measure baseline and necessary timing fixes,
  explicitly excluding full-mode measurement and broad correctness-suite runs.
  Selected a verified Down-key response/paint endpoint, with queued observers and
  a separate real Status Bar timer regression. Diagnostic readback stays outside
  input-ready timing; earlier composite records remain incompatible. Application
  optimizations and selection-order changes are not approved.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User approved the readback-only proposal and regular before/after
  measurement. The bounded phase split supports ordered range enumeration and
  bulk snapshot URL conversion. Keep selection mutation, notifications, exact
  readback ordering, partial-column behavior and the revision-5 harness unchanged.
  No wider F01 redesign or other pending finding is approved. Compatibility gates
  are 27 owning Qt tests offscreen and 29 focused native checks; performance must
  be demonstrated against the preserved corrected baseline.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Incorporated the user's separate Readback and QuickView Images/Text
  requests with TXT/Python/Markdown coverage. Reuse existing processes, preserve
  immutable v1 fixtures and comparison guards, and require complete case sets for
  derived headlines. The observed 37.5x readback gain is a three-sample large-folder
  phase result, not approval of the failed whole-run comparison. New-harness
  measurement validates the expanded report, not a compatible before/after pair.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User approved F03/F04/F02 and U04-U06 after the recommendations.
  Accept these independently of deferred mutation batching. Preserve U01-U03,
  exact-name matching, current readback and benchmark definitions. Require focused
  command/comparator checks and real Qt comparison/dialog regressions. Keep the
  unresolved measurement failures explicit; no new benchmark or full suite.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User requested a simple validation investigation and archival if
  current checks passed. Both native selection regressions, ten real-fixture
  selection cases and the separate small-pane startup path passed unchanged.
  Archive the implemented scope for independent review. Historical failure
  causes are unconfirmed; mutation batching and numerical budgets stay deferred.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Independent implementation review. Code approved: readback, F02-F04
  and U04-U06 match the approved design; U01-U03 unchanged. Focused gate rerun:
  161 per native/offscreen mode, 160 passed, one expected skip. Changelog figure,
  wording and version label, the README row count and the untracked deferred F01
  mutation work need correction. See Implementation Review.

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

### 2026_10_01 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Replaced the oversized matrix with two five-pattern workloads,
  batched pane reuse, bounded failure retention and two mean-of-case-medians
  report rows. Native pane checks: 14 passed; report/record checks: 38 passed;
  performance-tool discovery: 88 run, 87 passed, one expected skip. No benchmark
  restart or application change. The application-fix task remains in Plan.

### 2026_10_01 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Added measure-only `--full`, six optional medium workloads, effective
  catalog snapshots, separate full history and medium-aware report aggregates.
  Regular scope and fixture I/O are unchanged. Focused dispatch/record checks:
  17 passed; CLI/report checks: 32 passed. Performance-tool discovery: 94 run,
  93 passed, one expected skip. No benchmark restart or application change.

### 2026_10_01 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Selection revision 4 records the full interaction through readback
  and Qt response; headline/statistics tests include injected readback stalls.
  QuickView revision 2 verifies the existing text fixture instead of waiting for
  an unsupported-image state. Native checks passed; 96 tooling tests ran with
  95 passes and one expected skip. Regular baseline passed all thirteen workloads
  with three repetitions each. Application source and fixture data are unchanged.

### 2026_10_01 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Standardized Pane Loading/Selections size labels and updated the
  design handoff. Report tests: 27 passed. No measurement semantics, application
  code or stored run data changed; no benchmark was rerun.

### 2026_10_02 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented selection revision 5 and catalog revision 9 with verified
  Down-key handling/paint, known observer completion and independent diagnostic
  readback. Updated record retention, report aggregation and usage documentation.
  All 46 focused checks passed. Regular measure passed thirteen workloads with
  three repetitions; run 49ad1a06-e227-4d64-8e7a-c9d9aa7e9aba is published as
  Unreleased. No application code, full-mode measurement or broad test suite ran.

### 2026_10_02 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented ordered-range/bulk-URL readback without changing selection
  mutation, plus the requested Readback and QuickView Images/Text report rows.
  Catalog 10 / QuickView 3 adds versioned TXT/Python/Markdown fixtures and actual
  content, formatting and paint checks. Owning application checks passed (27
  offscreen, 29 native); the two edited tooling modules passed all 76 tests.
  Comparable large readback has three samples per side and a 37.5x observed gain;
  the whole comparison remains incomplete because a small-selection state guard
  failed. Other application findings and full-mode measurement remain pending.

### 2026_10_02 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented root archive naming, task-owned delete continuation,
  selectable comparison counts and limited cleanup. Added focused unit and real
  Qt regressions; 161 tests per native/offscreen mode, 160 passed and one expected
  skip each. Updated usage and changelog. No mutation batching or new measurements;
  the broader task remains Pending for the recorded F01 work and validation.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Validation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Validated the existing implementation without source or harness edits.
  Bounded native checks did not reproduce the historical failures. Moved the
  canonical task to Done and updated its index and incoming links, preserving
  previous records and the limited performance claim. Ready for others to review.

## Validation Results

### Bounded Closure Check (2026-10-02)

The user approved moving the implemented task to Done if a simple investigation
found the current paths working. No application or harness code was changed.
The earlier failure guards check exact fixture row count and cursor/scroll state
plus real follow-up input; they were neither disabled nor relaxed.

Two existing native regressions passed in 2.134 seconds, with no skips. They
exercise all five selection patterns with blocking observers/readback, plus the
real enabled-status refresh path. Executed with the existing project interpreter,
`build._environment()`, Windows Qt/Fonts and the performance-test import path:

```powershell
python -B -X faulthandler -m unittest -v `
  fman_performancetest.test_pane_rendering_benchmark.PaneRenderingBenchmarkTest.test_native_selection_measures_real_pane_patterns `
  fman_performancetest.test_pane_rendering_benchmark.PaneRenderingBenchmarkTest.test_native_selection_waits_for_status_refresh
```

Three additional fresh-process diagnostic children each had a 40-second parent
timeout. They reused the existing v1 fixture data, native 1280x800/1x viewport,
isolated settings, disabled status, hash seed 0 and UTC. Each returned zero with
no application errors:

| Path | Exact Rows | Checks | Result |
| --- | ---: | --- | --- |
| Small selection | 256 | Single, all, contiguous, alternating, scattered; 64 rows for complex patterns | All five passed |
| Large selection | 200,000 | Same patterns; 1,000 rows for complex patterns | All five passed |
| Small pane load | 256 | Startup/metadata completion, settled cursor/paint and row fingerprint | Passed |

Selection children called the unchanged
`fman_performancetest.pane_rendering_benchmark.child` with:

```python
cases = [dict(case, row_count=count) for case in selection.selection_cases(requested)]
child(directory, 'validation-followup', 'snapshot', True,
      viewport=(1280, 800), selection_cases=cases)
```

Here `directory` was the relevant `target/performance/fixtures/flat-small-v1/data`
or `flat-large-v1/data`, with `(count, requested)` equal to `(256, 64)` or
`(200000, 1000)`. Parsed `PANE_RESULT` output verified isolation, exact row/selection
counts, duplicate-free membership, unchanged cursor/scroll, verified follow-up
input and disabled status. The small-pane child used the same directory and
viewport with label `startup-followup` and no `selection_cases` argument.

Conclusion: not reproduced on current code in these bounded checks. This is not
a root-cause fix, repeated-run reliability certification or a new comparable
performance result. Earlier failed records remain failed. No benchmark record,
history entry or report was published; no full suite, full-mode measurement,
package build or installation ran. The user-approved archival condition is met,
with the historical uncertainty and deferred mutation work retained for reviewers.

### Command Fixes And Limited Cleanup (2026-10-02)

F03 was reproduced before the fix: canonical/trailing roots produced `C:.zip`
or `.zip`. The first correction exposed Windows UNC basename handling; keeping
the URL prefix preserved the share name. Both the new root cases and existing
command checks then passed. F02 required giving one existing comparator mock an
explicit selected-file result. The native dialog fixture required a real Qt
palette instead of its default mock theme. These were test/fix iterations, not
ignored failures.

Final gate: 161 tests in native Windows Qt (2.089 s) and 161 in offscreen Qt
(1.952 s), with 160 passes and one existing symlink-permission skip per mode.
The harmless offscreen `propagateSizeHints` warning was emitted. Coverage includes
actual filtered panes, exact-name/provider cases, root suggestions, all delete
continuation responses, a real Qt confirmation with popup suppression/restoration,
readback ordering/fallbacks and unchanged clipboard/Explorer/Recycle Bin behavior.
No real deletion, archive creation or external application launch was performed.

Editor diagnostics and scoped `git diff --check` passed. All four changed Python
files parse, test method names are unique, and AST comparison confirms U01-U03
are unchanged. Required document sections and append-only histories passed;
the performance table, released changelog and earlier validation records are
unchanged.

The following command uses the existing project interpreter from the repository
root; no environment or packages were created:

```powershell
@'
import build, os, subprocess, sys
modules = [
    'core.tests.commands.test___init__',
    'core.tests.test_comparator',
    'fman_integrationtest.test_qt.SortedFileSystemModelIT',
    'fman_integrationtest.test_qt.FilterBarIT.test_compare_directories_counts_real_filtered_selections',
    'fman_integrationtest.test_qt.FilterBarIT.test_delete_continuation_suppresses_progress_popup',
]
for platform in ('windows', 'offscreen'):
    env = build._environment()
    env['QT_QPA_PLATFORM'] = platform
    env['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
    print('Focused validation: ' + platform, flush=True)
    result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m', 'unittest', *modules], env=env, timeout=180)
    if result.returncode:
        raise SystemExit(result.returncode)
'@ | python -B -
```

No new `measure` run, full correctness suite, full-mode measurement, packaging,
installation or Git staging was requested or performed. The benchmark table
still represents the earlier saved runs, not a new measurement of these fixes.
The earlier startup and small-selection failure causes remain unresolved;
20,000-URL mutation budgets and manual mutation/inversion checks remain deferred.

### Expanded Regular Report And Grouping (2026-10-02)

`python build.py measure` passed all thirteen regular workloads with three
repetitions in 277.825258 seconds. Run `e0190d90-f52f-47cc-ad35-2bb2d319ab12`
is published as `Unreleased`, with all thirty selection cases and sixteen report
rows complete. All thirteen earlier records are SHA-256-identical; both failed
attempts are retained. The successful run has a new harness and is not a
compatible before/after comparison with the corrected baseline.

The Selections Readback headline is 67.6520 ms. QuickView Images headlines are
121.3574/120.9228 ms for small/large; Text means are 128.4443/128.4389 ms.
TXT, Python and Markdown each have three samples per size. Browser checks at
1440x900 and 390x900 passed Complete status, sixteen rows and no page overflow.
The isolated record verifier initially lacked runtime import paths; it passed
after using `build._environment()` paths.

On the user's follow-up, the displayed Readback label became Selections Readback,
immediately after all Selections rows. QuickView Images/Text rows are consecutive.
Stable test IDs, values and stored measurements are unchanged. The focused report
class passed all 31 tests, including regular/full grouping. HTML is regenerated
from the saved record; no new benchmark is needed for this presentation change.

### Readback Retry And Text Coverage (2026-10-02)

Unchanged-harness `python build.py measure` retry:
`401e1070-a655-4f8c-9ff8-b07e85dbf791`. All three large-selection repetitions
passed, including exact membership/state checks. Environment and harness hashes,
selection definitions and fixtures match baseline
`49ad1a06-e227-4d64-8e7a-c9d9aa7e9aba`. Three-sample large-folder medians:

| Pattern | Baseline (ms) | Optimized (ms) | Speedup |
| --- | ---: | ---: | ---: |
| Single | 0.0569 | 0.0577 | No meaningful change |
| All 200,000 | 2481.6091 | 66.1746 | 37.50x |
| Contiguous 1,000 | 19.5302 | 1.1722 | 16.66x |
| Alternating 1,000 | 18.3473 | 1.2291 | 14.93x |
| Scattered 1,000 | 20.7411 | 2.1142 | 9.81x |

All-selected readback uses 97.33% less time. These are phase observations, not
statistical significance or normal Select All input latency. The second small
repetition failed its cursor/scroll/follow-up guard at `selection.all`, before
readback; remaining cases in that repetition were not run. Root cause remains
unresolved. The failed record remains immutable and did not replace the successful
version pointer. The changelog uses this newer three-sample result with a caveat.

The subsequent report/text extension changes the harness. Strict cross-harness
comparison remains rejected; a new regular run validates new coverage, not the
old-versus-new readback claim. Report tests cover independent metrics, raw/compact
parity, missing/failed/legacy cases, strict comparisons, full-mode row counts and
labels. Native QuickView verifies TXT bytes, Python text/keyword colours and
Markdown content/heading/list/link formatting, followed by restored image pixels.

Focused tooling command, using the existing project environment (no installs):

```python
import build, os, subprocess, sys
env = build._environment()
env['QT_QPA_PLATFORM'] = 'offscreen'
env['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
code = "import sys, unittest; sys.path.insert(0, 'src/performancetest/python'); unittest.main(module=None, argv=['unittest', *sys.argv[1:]])"
tests = ['fman_performancetest.test_filter_find_benchmark',
     'fman_performancetest.test_pane_rendering_benchmark']
raise SystemExit(subprocess.run([sys.executable, '-B', '-X', 'faulthandler',
  '-c', code, *tests], env=env, timeout=150).returncode)
```

Outcome: 76 tests passed in 6.625 seconds, no skips. Narrow intermediate checks
also passed: 30 report tests and 21 fixture/record/native QuickView tests. Catalog
validation initially rejected revision 2 and was fixed; the same checks then
passed. Changed-file editor diagnostics are clear. No full application suite,
full-mode measurement, clean/freeze/package, dependency installation or Git staging.

### Readback Optimization: Provisional Comparison (2026-10-02)

The optimized regular run `bdba2d1f-d820-4a58-a3da-23621e6ca65d` is retained as
failed and was not promoted over baseline `49ad1a06-e227-4d64-8e7a-c9d9aa7e9aba`.
Environment, harness hash and selection definitions/fixtures match. Completed
readback samples show the following medians; these are provisional phase results,
not a successful whole-run comparison or permission to bypass compatibility checks.

| Selected Files | Baseline (ms) | Optimized (ms) | Speedup | Samples Before / After |
| --- | ---: | ---: | ---: | ---: |
| All 256 | 2.7411 | 0.1421 | 19.29x | 3 / 3 |
| Contiguous 1,000 | 19.5302 | 1.4053 | 13.90x | 3 / 2 |
| Scattered 1,000 | 20.7411 | 1.6997 | 12.20x | 3 / 2 |
| All 200,000 | 2481.6091 | 65.8839 | 37.67x | 3 / 2 |

Large all-selected readback uses 97.35% less time in the completed samples.
Single-file readback remains too small for a useful improvement claim (small
0.0452 to 0.0568 ms; large 0.0569 to 0.0513 ms).

`pane.load.small` failed during its child run. The second large-selection child
failed before timing because its initial pane had 6 rows instead of 200,000;
later patterns in that repetition were recorded as not run. The other two
large-selection repetitions completed. Do not mark performance verification
complete until startup is resolved and a complete regular measurement succeeds.
This was the first provisional 37.7x result; the retry above supersedes its
changelog figure without altering this historical record.

### Corrected Input-Ready Baseline (2026-10-02)

Command: `python build.py measure`, using the existing project interpreter.
Saved interval: 284.04 seconds, regular mode, thirteen workloads, three repetitions
per workload. All thirty selection cases passed. The version index and generated
report point to `49ad1a06-e227-4d64-8e7a-c9d9aa7e9aba`. The runner's application
and harness stability checks passed; SHA-256 checks preserved all twelve older
run files. No medium workload ran. Application version is 0.10.1, recorded as
Unreleased because the worktree contains the benchmark corrections.

Each number below is a three-repetition median in milliseconds. Readback is a
separate diagnostic after input readiness, not part of the headline.

| Pattern | Small Input Ready | Large Input Ready | Large Mutation | Large Readback |
| --- | ---: | ---: | ---: | ---: |
| Single | 13.53 | 42.70 | 26.61 | 0.06 |
| All | 14.23 | 14.91 | 0.06 | 2481.61 |
| Contiguous | 16.64 | 132.59 | 110.40 | 19.53 |
| Alternating | 15.74 | 139.35 | 107.55 | 18.35 |
| Scattered | 15.48 | 159.82 | 115.57 | 20.74 |

Headlines are equal-weight means of the five medians: **15.12 ms small** and
**97.87 ms large**. Small/large folders contain 256/200,000 files; complex cases
select 64/1,000 rows. Status is disabled. The 14.91 ms large Select All result is
not a claim about its 2481.61 ms URL readback, enabled-status large folders, every
selection command or physical input hardware. This is a new baseline definition,
not an application optimization or a valid speedup comparison with revision 4.

Focused validation: **46 passed, no skips**, 2.659 seconds. Exact launcher from
the repository root with the existing project interpreter:

```powershell
@'
import build
import subprocess
import sys
checks = [
    'fman_performancetest.test_pane_rendering_benchmark.PaneRenderingBenchmarkTest.test_native_selection_measures_real_pane_patterns',
    'fman_performancetest.test_pane_rendering_benchmark.PaneRenderingBenchmarkTest.test_native_selection_waits_for_status_refresh',
    'fman_performancetest.test_filter_find_benchmark.PerformanceReportTest',
    'fman_performancetest.test_filter_find_benchmark.PerformanceRecordTest',
]
script = "import sys, unittest; sys.path.insert(0, 'src/performancetest/python'); unittest.main(module=None, argv=['unittest', *sys.argv[1:]])"
raise SystemExit(subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', script, *checks], env=build._environment(), timeout=180).returncode)
'@ | python -B -
```

The initial regression rejected the old missing input endpoint. Fixture import
isolation, main-window lookup and a test-launcher PYTHONPATH leak were corrected;
the same affected checks passed on rerun. The native tests cover a blocking
queued observer, the actual 150 ms status refresh and a blocked snapshot,
follow-up cursor movement/paint, state restoration and readback after the endpoint.
Report/record tests cover retained statistics and refusal to substitute older
paint-only or composite timings. Editor diagnostics and scoped whitespace checks
passed. No `build.py test`, test discovery, `measure --full`, packaging, dependency
installation or application optimization was performed.

### Handoff And Report Labels

The run below passed the implemented benchmark checks; its selection headline
is NOT a validated user-input-latency baseline. The injected readback caveat in
Handoff Summary supersedes earlier descriptions of it as full user interaction.
Historical timing and contributor records are retained without rewriting them.

Report-label validation: 27 tests passed with this exact command:

```powershell
@'
import build
import subprocess
import sys
script = "import sys, unittest; sys.path.insert(0, 'src/performancetest/python'); unittest.main(module=None, argv=['unittest', 'fman_performancetest.test_filter_find_benchmark.PerformanceReportTest', '-q'])"
raise SystemExit(subprocess.run([sys.executable, '-X', 'faulthandler', '-c', script], env=build._environment(), timeout=180).returncode)
'@ | python -
```

### Full Responsiveness Baseline

- `python build.py measure` completed in 264.64 seconds (4m 25s), regular mode,
  thirteen workloads and three repetitions each. Published as `Unreleased`, run
  `bca3f29b-00ce-4065-a95e-5b720f15e681`, under `UserSettings/Performance`.
  The version index points to this run; no medium workloads were executed.
  Application-source hashes match the earlier attempt. Git was exposed through
  a temporary process `PATH` change, restored after the command.
- Selection headline means: small 12.25 ms; large 1,280.79 ms. Large select-all
  selected exactly 200,000 files: mutation 0.05 ms, paint 8.51 ms, readback
  5,138.24 ms, full interaction 5,147.95 ms (each is its own three-run median).
  Large complex patterns select 1,000 files each and took 400.96/402.27/409.75 ms
  for contiguous/alternating/scattered shapes. The headline averages five cases;
  it is neither their sum nor whole-suite runtime. Status remains disabled.
- Initial regular attempt `2212f62f-ba61-4d6e-b1a3-c9f4060c9ad0` is retained as
  failed: eleven workloads passed, both QuickView workloads failed. A direct
  small QuickView child reproduced `TimeoutError: unsupported-file`. The old
  benchmark expected a supported text fixture to be rejected. No result was
  promoted from that attempt; fixture contents were not rewritten to fix it.
- Immediate native regressions passed:
  `PaneRenderingBenchmarkTest.test_native_selection_measures_real_pane_patterns`
  (40 ms readback stall included in every full timing), and
  `PaneRenderingBenchmarkTest.test_native_quickview_measures_supported_text_and_image_restore`
  (text content/paint, image restore, navigation and cleanup).
- Report/record checks passed 44 tests. The first attempt exposed the missing
  statistics allowlist entry for `responsive_ms`; adding it and rerunning the
  same checks passed. Final performance-tool discovery used the exact command
  below: 96 run, 95 passed, one expected symlink-privilege skip, 7.016 seconds.
  Edited-code diagnostics and local links in all four updated documents passed.
- No application-wide tests, build/freeze, full-mode measurement, application
  optimizations or separate 20,000-row acceptance probes were run.

### Optional Full Mode

- Immediate checks used the existing environment and a 180-second child timeout:

```powershell
@'
import build
import subprocess
import sys
script = "import sys, unittest; sys.path.insert(0, 'src/performancetest/python'); unittest.main(module=None, argv=['unittest', 'fman_performancetest.test_filter_find_benchmark.PerformanceRecordTest', '-q'])"
raise SystemExit(subprocess.run([sys.executable, '-X', 'faulthandler', '-c', script], env=build._environment(), timeout=180).returncode)
'@ | python -
```

- The record/dispatch class passed 17 tests. The same launcher with
  `BuildMeasureCommandTest` and `PerformanceReportTest` instead passed 32 tests.
  Initial failures were an outdated explicit-glob expectation and a nonexistent
  mock child directory; both were corrected and the same checks rerun successfully.
- Final performance-tool discovery used the exact command recorded below:
  94 run, 93 passed, one expected symlink-privilege skip, 2.711 seconds.
- `python build.py measure --help` passed and lists `--full`.
- `python src/performancetest/run.py suite --full --list` passed and lists all
  nineteen workloads, including six medium definitions, without fixture I/O.
- Local-link checks passed for the four updated Markdown documents and all
  required task sections. No measurements ran; full-mode elapsed time, new timing
  values and previously reported QuickView benchmark failures remain unverified.

### Earlier Regular-Suite Correction

- Immediate native check: `fman_performancetest.test_pane_rendering_benchmark.PaneRenderingBenchmarkTest`,
  14 passed; all five patterns share one temporary 16-file pane.
- Report/record check: `fman_performancetest.test_filter_find_benchmark.PerformanceReportTest`
  and `PerformanceRecordTest`, 38 passed; covers five-to-one aggregation,
  exact row labels, six bounded processes and interrupted-stage retention.
- Performance-tool discovery: 88 run, 87 passed, one expected symlink-privilege
  skip. Exact command from the repository root:

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest','discover','-s','src/performancetest/python','-p','test_*.py','-q'],env=env,timeout=300).returncode)"
```

- The oversized run was stopped and its partial record retained as
  `f5f5259d-f6d3-401d-b607-ff9ebba495bd`. It included QuickView failures and
  medium-selection timeouts, is not a successful reference, and produced no
  final HTML after interruption. The revised benchmark was not run; its actual
  added wall time and new timing-table values remain unverified.
- No full application suite, build, freeze, packaging or application-fix gates
  were run for this benchmark correction. Historical review gates below remain.

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

## Implementation Review (2026-10-02)

Verdict: **code approved; documentation corrections required before release.**

### Code

- **Readback is equivalent to Qt.** `ListingModel.flags` marks every valid cell
  selectable, so a row inside a full-width range is exactly a row that
  `isRowSelected` accepts. Multi-range `dict.fromkeys` keeps Qt 5's first-seen
  `selectedRows` order. Partial-width ranges and models without `urls_for_rows`
  keep the old path. `Rows`-flag selection and snapshot restore store full-width
  ranges, so normal marking uses the fast path.
- **F02-F04 and U04-U06 match the design.** Pack handles `file://C:`,
  `file://C:/`, UNC shares and nameless roots. The delete prompt goes through
  `Task.show_alert` with a `YES` default. U01-U03 are unchanged.
- **Optional (P3):** `urls_for_rows` checks bounds and calls `join` per row.
  A single-range path could check bounds once. Not required; 66 ms is acceptable.

### Documentation and Process

| ID | Priority | Finding | Where |
| --- | --- | --- | --- |
| C1 | P2 | "about **36x**" contradicts 2,481.61 / 66.17 ms = 37.5x | [CHANGELOG.md](../CHANGELOG.md) Changed |
| C2 | P2 | "selected file and metadata list": readback returns URLs only | CHANGELOG intro |
| C3 | P2 | Column `0.10.2` is unreleased; `base.json` is `0.10.1` and the run is recorded as Unreleased | CHANGELOG table |
| C4 | P3 | `~2481.61` estimates sit in a measured-results table; use `-` | CHANGELOG table |
| C5 | P3 | Unrelated rows moved between runs (Fuzzy Large +8.7%, Refresh 471 to 740 ms across harnesses). Selections Large 97.87 to 86.39 ms is within that spread and is not an improvement claim | CHANGELOG table |
| D1 | P2 | README says the regular report has 13 rows; it now has sixteen | [README.md](../README.md#L141) |
| P1 | P2 | Deferred F01 mutation batching (Medium-High) has no Pending plan after archiving | [Plan.md](../Plan.md) |
| P2 | P3 | A `Role: Reviewer`, `Activity: Validation` record sits under Implementer; keep it (append-only), but use Reviewers/Review for future validation records | Implementer |

Recommended: fix C1-C3 and D1, and record P1 in
[CodeReview099](../Plan/CodeReview099.md) or a dedicated plan. C4/C5 are wording.

### Validation

Reran the documented command-fix gate from
[Command Fixes And Limited Cleanup](#command-fixes-and-limited-cleanup-2026-10-02),
unchanged: **161 tests per native Windows and offscreen Qt, 160 passed, one
expected symlink-privilege skip** (2.132 s / 1.994 s). Offscreen printed the
known `propagateSizeHints` warning. No benchmark, full suite, build or package
ran. Only this document was edited.
