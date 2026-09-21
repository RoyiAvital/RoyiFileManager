# File System and Pane Architecture 002: Responsiveness and Memory

Status: Proposed follow-up; no implementation started (2026_09_22).

## Task

Explore the remaining responsiveness, memory and validation improvements after
the user/main developer accepted [FSPaneArch001](../Done/FSPaneArch001.md).
Real-world use established that the new design works immensely well and is about
an order of magnitude better than the previous design. This assessment closes
the first task; it does not establish a universal tenfold benchmark improvement.

## Scope

- Prioritize loaded-input responsiveness during sort, filtering, fuzzy search
  and refresh, especially with many marks or two large panes.
- Investigate Python sort/key generation, marked-state restoration, snapshot
  validation and overlapping allocations before selecting an optimization.
- Extend adversarial-query, held-key and mixed-entry coverage where existing
  measurements do not answer the user-visible question.
- Retain unrun cloud/offline/access-denied/removable/network, icon DPI/association,
  external drag and portable-artifact checks as a validation backlog, not known
  defects. Native optimization remains focused on NTFS/ReFS.
- Preserve current query syntax/ranking/highlights, identity rules, authoritative
  operation checks, all bundled providers and the implemented plug-in contracts.
  No further API break, speculative cache layer, dependency change or provider
  rewrite is approved by this plan. Do not reopen the completed first task.

## Design

Use existing immutable listings, snapshot workers, Qt models and benchmark
infrastructure. Workers receive plain immutable inputs; widgets and models stay
on Qt. Preserve bounded work lanes, cancellation, stale-result rejection and
failure behavior that retains the previous valid pane.

Separate measurement from optimization:

1. Add demand-only measurements for loaded input and simultaneous large panes.
   Record request-to-completed-paint latency, queued input, Qt commit time,
   steady working set and process peak separately.
2. Profile only separate diagnostic runs. Attribute sorting, mark restoration,
   validation and query costs before proposing changes.
3. Trial one measured optimization at a time with a correctness comparison and
   fresh-process A/B runs. Review the selected design before production edits.

Historical stress evidence reached 36.2 ms arrow-to-paint p95 and 285.1 MiB peak;
the later refresh suite recorded a 307.41 MiB cumulative process peak. These are
different workloads, not directly comparable results. Existing one-at-a-time
input sampling does not prove held-key behavior. The restored Quicksearch dialog
also requires its own input-responsiveness baseline.

No settings or persistence change is planned. Benchmark output remains under
the existing diagnostic/results paths, with statistics-only records and strict
provenance checks. Do not rewrite earlier results or reduce repetitions.

## Alternatives

- Leave the accepted implementation unchanged: appropriate when a proposed
  improvement lacks reproducible benefit or adds disproportionate complexity.
- Optimize from the original PoC or old in-pane Find timings: rejected because
  they do not measure the current application's behavior.
- Add caches, a new matcher, native extension or process offloading immediately:
  defer until profiling demonstrates a need and the added semantics, cancellation
  and resource costs have a separately reviewed design.

## Runtime Effects

Planning has no startup, steady-state CPU, memory, I/O, threading or persistence
effects. New diagnostics must be opt-in and outside ordinary correctness tests.
The disabled path must create no feature-specific jobs, scans, timers or probes.
Any later production proposal must quantify allocation lifetimes, peak memory,
Qt/GIL contention and cancellation behavior. Never claim bounded cancellation
for an OS call that can block.

## Tests

Run these focused checks when implementing the affected measurements or behavior,
using the existing application environment; do not install packages or create an
environment:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_listing', 'fman_unittest.test_search_file_fuzzy'], env=build._environment()).returncode)"
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.TableIT', 'fman_integrationtest.test_qt.SnapshotFilterBarIT', 'fman_integrationtest.test_qt.SearchFileMetadataIT'], env=env, timeout=180).returncode)"
python src/performancetest/run.py suite --test 'filter.*' --test 'fuzzy.*' --test recursive.tree --test 'refresh.*'
```

Changes to benchmark/report tooling use the separate
[development-tool checks](../src/performancetest/README.md#development-tool-checks),
not normal application or release verification.

- Unit/regression: retain query result/ranking parity, verified-identity mark
  restoration, unknown/ambiguous identity handling and cancellation tests.
- Integration: add deterministic queued-input and stale-result tests alongside
  the existing Qt tests; assert final cursor/marks and no worker access to Qt.
- Performance: use synthetic 256/200,000-file and 50,000-file recursive fixtures,
  three fresh-process repetitions, native Qt and warm caches. Extend the existing
  harness with a fixed-rate input stream through active work, no settled padding;
  define and record that protocol and its exact command before using results.
  Repeat with both panes large and with QuickView/extended status off and on.
  Report query latency separately from opening and input latency; do not report
  p95 from too few observations. Keep profiling separate from timing.
- Manual: verify held navigation keys during sort/filter/refresh and dialog
  search, all-marked refresh, navigation away and window close during work.
  Check mixed files/directories, long names, Unicode and permitted links.
- Environment backlog: exercise disconnect/reconnect and denied/offline paths
  with disposable data; check high-DPI/icon association changes and external drag.
  Record unavailable prerequisites as unrun, not passed. Artifact smoke uses an
  existing ZIP and writable disposable directory; creating a package requires
  separate permission. Verify launch, navigation, Find, refresh and settings on
  restart without intentionally writing to the Registry.

## Implementation Steps

1. Review the follow-up scope and choose one measurable problem. Capture a
   current baseline and define its acceptance thresholds before optimization.
2. Add the missing focused measurement/test and validate it independently.
3. Profile separately, propose the smallest justified change, and review its
   correctness, cancellation and runtime costs.
4. Implement and run the narrow regression first, then the affected Qt/provider
   checks and comparable A/B measurements. Retain changes only with clear value.
5. Work through relevant manual/environment checks; document remaining limits
   and update user documentation only for actual behavior changes.

## Acceptance Criteria

- Each selected optimization has a reproducible current baseline, agreed numeric
  targets, compatible measurements and passing correctness regressions.
- Loaded input and memory are reported independently of query/first-paint time;
  no success claim relies on idle padding, fewer repetitions or changed semantics.
- The original 16 ms p95 and 250 MiB limits are reference aspirations, not
  retroactive blockers for FSPaneArch001. Set realistic workload-specific targets
  before implementing this task; do not silently redefine a failing target.
- Unrun environment checks and rejected experiments are documented explicitly.
  Disabled features introduce no recurring work and settings remain portable.

## Reviewers

### 2026_09_22 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Captured worthwhile investigations and unrun checks from the accepted
  first architecture task. Planning only; select a scoped problem, review its
  design and agree numeric targets before implementation.