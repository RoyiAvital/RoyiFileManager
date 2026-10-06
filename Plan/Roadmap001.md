# Roadmap 001: Before 1.0.000

Status: Planning recap of the 2026-10-05 discussion, recorded on 2026-10-06.
Recommendations are not an approved implementation queue or a commitment to
ship every item before 1.0.000.

## Task

Prioritize dependable daily file operations before adding more tools. Search,
previews, hashing, favorites and external-tool integration already give the
application substantial breadth. Preserve its minimal, keyboard-focused,
extensible Windows experience while defining the first stable release's scope.

## Scope

- Record recommended priorities, optional additions and the release-quality bar.
- Keep independent features in their own reviewed tasks. This roadmap does not
  authorize implementation, API breaks, cache changes or release builds.
- Batch Rename remains a separate proposed third-party plug-in. Its reusable
  QuickBoard prerequisite is now implemented in
  [UIElements003](../Done/UIElements003.md); the renamer itself is not.
- Use the requested target label `1.0.000` without changing application version
  metadata or the repository's release-numbering policy.

## Design

### Recommended Pre-1.0 Priorities

| Rank | Priority                         |
| ---- | -------------------------------- |
| 1    | Operation tracking and results   |
| 2    | Richer conflict resolution       |
| 3    | Automatic folder refresh         |
| 4    | Consistent link handling         |
| 5    | Versioned public plug-in API     |

1. **Operation tracking and results.** Show active transfers, source/destination,
   progress and cancellation; retain clear completed/skipped/failed outcomes.
   Define application-exit behavior while operations are active. Progress and
   cancellation already exist: improve supervision and outcomes, not replace
   working progress dialogs. Queueing, pause and resumable transfers can wait.
2. **Richer conflict resolution.** Compare both paths, sizes and modification
   dates; offer Replace, Skip, Keep Both and explicitly scoped apply-to-remaining
   choices. The discussion identified the name-oriented overwrite prompt as an
   everyday gap. This was the suggested next independent feature: useful,
   contained and independent of QuickBoard or Batch Rename.
3. **Automatic folder refresh.** Detect external changes in displayed local
   folders, coalesce notifications and preserve cursor, marks and scroll. Keep
   manual refresh for unsupported locations. Local watch/unwatch hooks were
   no-ops when discussed; a reviewed Windows implementation is needed, not
   simply re-enabling the old watcher. This is separate from recursive indexing.
4. **Consistent link handling.** Make symlink/junction operations predictable
   without unintentionally operating on targets. Explicitly refuse unsupported
   reparse types: safe refusal is acceptable, ambiguity is not. Continue the
   existing [LinkOperationPolicy](LinkOperationPolicy.md), not a duplicate policy.
5. **Versioned public plug-in API.** Document the supported fork API, allow
   compatibility declarations, report incompatibility clearly and preserve the
   contract through 1.x. Stability means the fork's API, not restoring upstream
   fman compatibility. Use [PlugIn.md](../PlugIn.md) as the reference; compatibility
   negotiation and migration details need separate design.

These are priority ranks, not a dependency chain. Richer conflict resolution
was recommended as the next implementation candidate even though operation
visibility ranks first in the broader release discussion.

### Strong Additions, Not Automatic Release Gates

| Feature                    | Boundary                             |
| -------------------------- | ------------------------------------ |
| Flat View                  | Indexing feasibility comes first     |
| Limited Undo               | Renames and same-volume moves only   |
| Named pane-pair workspaces | Restore pairs through Command Center |
| Folder comparison          | Comparison, not synchronization      |

- Flat View enables bulk work across subfolders, beyond search and navigation.
- Limited Undo means guarded reversal, not undo for arbitrary overwrites or
  permanent deletion.
- Named pane-pair workspaces restore recurring source/destination pairs without
  requiring a tab-heavy interface.
- Folder comparison identifies missing, newer and different files. Existing
  external comparator integration remains useful; automatic synchronization
  should be a separate, later feature.

### Flat View Performance Constraint

The user's concern is scale: 200,000 files in one folder are not equivalent to
200,000 files across thousands of directories. Recursive acquisition must still
open and inspect those directories, even with fast native enumeration.

- Virtualized rendering reduces painting, not enumeration, sorting or retained
  data costs. Caching visited folders does not cover unseen descendants.
- A maintained recursive index amortizes queries but adds initial indexing,
  change tracking, invalidation, I/O and memory costs.
- Investigate reusing Everything's existing index before building another cache:
  configured indexed roots, index-side filtering/global ordering, bounded
  retrieval and a pane adapter avoiding unnecessary per-file objects.
- Preserve real file URLs and recheck filesystem state before operations. The
  existing Everything picker is not a drop-in solution: paging, large-result
  selection, stale entries and operation targets need their own design.
- Measure recursive acquisition, result transfer and pane publication separately
  on representative large trees. Do not add ordinary-pane caching solely to
  enable Flat View.

**Flat View should not block 1.0.000 while that architecture is unproven.**
Keep [FlatView](FlatView.md) as its owning proposal; reconcile that plan with this
constraint before implementation rather than silently changing it in this recap.

### Ownership and Compatibility

Operation supervision/conflicts belong with host file operations; local refresh
with observation and pane snapshots; link semantics with filesystem operations;
compatibility with the public API and loader. A Batch Rename plug-in owns its
grammar, validation and mutations; QuickBoard supplies composition and preview.

Future designs must keep widgets/models on Qt, pass immutable plain data to
workers, support cancellation/stale-result rejection and define failure behavior.
Any persistent mutable state belongs under `UserSettings`, not the Registry.
Operation-history retention and other persistence schemas remain undecided.

## Alternatives

- More tools as the main pre-1.0 focus: lower priority than dependable operations.
- A full transfer scheduler first: defer queueing, pause and resume while improving
  visibility and outcomes with existing progress support.
- Flat View through virtualized rendering alone: insufficient for recursive
  acquisition cost. A new general pane cache is not the default solution.
- Delaying 1.0 for video previews, another search engine, a built-in editor or
  a Qt migration: not justified without a concrete need.
- Universal Undo or synchronization: separate, higher-risk work, not implicit
  scope of limited Undo or folder comparison.

## Runtime Effects

Not applicable to this documentation-only recap: no startup or steady-state
CPU/memory cost, I/O, threads, processes, timers or persistence are added.

Future feature designs must budget these explicitly: bounded/coalesced refresh
notifications, index acquisition/maintenance and bounded history retention.
Disabled optional features must do no feature-specific background work. Long
work must be cancellable or reject stale completion. No new universal latency
or memory budget was agreed in this discussion.

## Tests

For this recap, verify all five priorities and four optional additions against
the discussion; preserve the suggested next feature and Flat View constraint.
Check the nine required sections, relative links, exactly one Pending index
entry, Markdown diagnostics and whitespace. Validate table column counts,
delimiter positions and matching separator widths without changing cell text.
Application unit/integration/performance tests are not applicable: no runtime
behavior changes. Future tasks must name their exact focused commands.

The proposed release bar is verified behavior for interrupted transfers,
disk-full/read-only failures, disconnected storage, startup/shutdown, upgrades
and the actual portable artifact. Also check keyboard focus and mixed-DPI
usability. Existing safeguards need evidence from the delivered application.
For adopted features, cover conflict choices, refresh state preservation,
link-target safety and plug-in incompatibility handling in their own tests.

Keep unresolved checks in their owning tasks and the existing
[release-gate backlog](CodeReview099.md). No full suite, performance catalog or
build/freeze is authorized by this roadmap request.

## Implementation Steps

1. Review the recap and select actual 1.0.000 blockers; recommendations are not
   release commitments.
2. Design/review the next independent feature, with richer conflict resolution
   as the suggested starting point; obtain implementation approval separately.
3. Plan tracking/results, local refresh and API compatibility independently;
   reuse the existing link-policy task.
4. Prioritize Batch Rename and optional additions separately. Investigate Flat
   View/index feasibility before committing to an architecture.
5. Implement only approved tasks and record focused correctness/performance
   evidence, preserving established workflows.
6. Assess release readiness against failure, lifecycle, upgrade, portable and
   usability checks; record remaining limitations explicitly.

## Acceptance Criteria

- Recommendations, user constraints, optional additions and unresolved decisions
  are clearly distinguished.
- Existing progress/cancellation, external comparators and QuickBoard are not
  misrepresented as wholly missing capabilities.
- Flat View is not a release blocker; no new cache/index architecture is approved
  without scale evidence and separate review.
- Adopted features retain one owning task each; this remains a roadmap rather
  than a duplicate implementation specification.
- Tables are normalized, links resolve and [Plan.md](../Plan.md) indexes this
  document once under Pending. Recording it does not declare release readiness.

## Reviewers

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Recorded the pre-1.0 priorities, optional additions, release bar and
  Flat View indexing constraint. Planning recap only; implementation and final
  release scope require separate approval.