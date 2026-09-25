# Code Review 099: Deferred Work and Release Gates

Status: Backlog, 2026-09-25. Items require individual review and approval; this
document does not authorize implementation or certify a release.

## Task

Preserve unfinished work from [CodeReview003](../Done/CodeReview003.md), larger
responsiveness proposals and unresolved validation gates. Keep these independent
of the six completed optimizations in [CodeReview004](../Done/CodeReview004.md).

## Scope

- Retain C01-C15, R01-R07, M01 and the investigation/rejection notes below.
  Sizes describe potential implementation, not approval or measured benefit.
- Retain unselected CodeReview004 proposals N05-N08 and N11-N13. Only
  N01-N04, N09 and N10 were authorized and delivered there.
- [LinkOperationPolicy](LinkOperationPolicy.md) and
  [FSPaneArch002](FSPaneArch002.md) remain their own canonical designs; link to
  their decisions rather than duplicate or silently supersede them.
- Preserve existing safety refusals, public plug-in APIs, Qt thread ownership,
  cancellation, stale-result rejection and portable UserSettings persistence.
- No automatic implementation, full suite, build or performance-catalog run.
  No changes to measurement semantics, repetitions or historical records.

## Design

### Carried Forward From 003

| ID | Previous Item / Unfinished Work | Size And Next Decision |
| --- | --- | --- |
| C01 | Item 13 and link follow-ups: safe symlink overwrite, dangling/directory-link type preservation and cross-volume link recreation | Larger policy work in LinkOperationPolicy. Never unlink-before-create or traverse a target as fallback. |
| C02 | Item 16: avoid unnecessary text invalidation/model notifications | Small only if a measured cache/dependency problem is found. A full-range signal does not mean all rows repaint; preserve offscreen and plug-in correctness. The unchanged-identity sentinel already exists and is not open work. |
| C03 | Item 26: case-aware Compare Directories | Policy decision first. Windows local/UNC/mapped folders can differ in case semantics; no blanket normcase. Listing-error retention is already fixed. |
| C04 | Restore local-to-archive Move with verified source retention | Major transfer design. Current pre-mutation refusal contains the original source-loss bug. Couple packing, warnings, verification, cancellation and source deletion in one safe operation; preserve existing archive data. |
| C05 | Broader overwrite/metadata compatibility | Larger decision for known-hardlinked destinations, non-Windows overwrite and source named streams. Ordinary Windows staged overwrite/ACL recovery is implemented; do not redo it or weaken retained refusals. Cross-format archive moves remain unsupported. |
| C06 | Cross-device move cancellation and partial completion | Investigate real-volume behavior and failure sequencing; do not claim mocked device IDs validate it. Preserve source after failed composite copy and truthful partial outcomes. |
| C07 | Merge source/destination type mismatch | Small early refusal is preferred to a prompt redesign. Currently safe but late task errors; decide clear file-versus-directory behavior before mutation. |
| C08 | Comparator on providers returning unknown identity | Retain refusal until alias policy is reviewed. Path-string equality alone cannot prove distinct objects; zero inode does not characterize every FAT/exFAT volume. |
| C09 | Generic icon cached after transient shell extraction failure | Cosmetic retry policy, not worker-start rollback (already fixed). No retry timer or unbounded per-paint shell requests. |
| C10 | Cosmetic hiding of copy/recovery staging | Previously deferred for per-file metadata cost. Keep visible staging unless a separately measured design justifies its cost; no automatic hide/unhide restoration. |
| C11 | Malformed individual session fields | Focused schema/consumer review. Non-object JSON roots and atomic saves are already handled; do not swallow arbitrary errors. |
| C12 | Callback mutation, broader command concurrency and plug-in unload recovery | Potentially larger lifecycle investigations. Thread-local cursor isolation and comparator handoff are already fixed; do not reopen those as unresolved defects. |
| C13 | Unused string construction in CopyPathsToClipboard | Confirmed in `CopyPathsToClipboard.__call__` in [Core commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py): `files = '\n'.join(to_copy)` is unused before a second, human-readable join. Remove only the unused allocation; no large performance claim. |
| C14 | Optional fixed-local-drive Go To history pruning | Earlier alternative only, not a requirement. Bounded history without background probes is the accepted default; do not reintroduce mapped-drive/UNC blocking. |
| C15 | Broader search, archive enumeration, directory-size and painting optimization | Unselected investigations, not proven defects. Preserve existing bounds/generations; use current-code evidence and FSPaneArch002 before any larger design. |

The six previously rejected candidates remain rejected: implied archive-folder
defaults, cached DirEntry link checks in directory sizing, missing-target scan
fallback, elided highlight handling, DST boundary rejection and escaped trailing
spaces in fuzzy queries. Already delivered staging, command isolation and worker
rollback work is not an unimplemented backlog.

### Unselected CodeReview004 Proposals

The original evidence remains in [CodeReview004](../Done/CodeReview004.md). None of
these proposals was implemented as part of its completed six-item batch:

| ID | Disposition And Next Decision |
| --- | --- |
| N05 | Deferred: identical-listing rescan suppression needs signal, cursor-restoration and Qt-thread equality-cost review. |
| N06 | Deferred: cooperative yield changes need a separate scheduler/interaction benchmark and cancellation budget. |
| N07 | Rejected in its current form: a visible-row URL cache adds substantial retained memory and invalidation work. |
| N08 | Rejected in its current form: lazy row maps risk repeated linear searches on Qt and greater mapping complexity. |
| N11 | Unapproved: snapshot-size status totals require explicit freshness, fallback, file-cap and memory decisions. |
| N12 | Unapproved: consider only a per-suggestion shortcut map with live visibility/aliases/bindings; no per-opening candidate cache. |
| N13 | Unapproved: optional Locale/ISO dates remain in the canonical [DateFormat](DateFormat.md) task. |

### N05 Next-Design Requirements

The implementation reviewer recommends a no-change refresh path that retains
notifications while avoiding projection/reset. Worth designing separately;
still deferred and not approved for implementation. Current source shows that
retaining only `transaction_ended`/`files_changed` is insufficient:

- Define eligibility against both the immutable listing and the committed
  filter/search/sort/column revision. Preserve dynamic filter/column refresh
  semantics; equal filesystem metadata alone does not establish an equal view.
- Preserve or deliberately resolve pending cursor requests, initial navigation
  and column callbacks, `committed`/`all_rows_loaded`/sort notifications and
  cache invalidation. Fall back to the normal commit when that contract cannot
  be fulfilled without a reset; do not replay view-restoration signals blindly.
- Measure equality placement off Qt with cancellation/stale-result rejection.
  Test unchanged reloads, changed metadata, pending/missing cursor targets,
  concurrent filter/column changes, callback ordering, selection/scroll and
  QuickView. Benchmark the complete retained-notification path before claiming
  the originally estimated projection savings.

Owners: [scan delivery and commit](../src/main/python/fman/impl/model/listing.py),
[cursor restoration](../src/main/python/fman/impl/view/__init__.py).

### Carried Validation And Release Gates

Task 003 closure accepts the delivered batch, not a wide-use release certification.
These checks transfer here without being labeled passed:

- R01: reproduce/reassess the native SearchFiles label-width failure before
  claiming native layout coverage; offscreen success is not equivalent.
- R02: execute privilege-skipped link cases and real second-volume transfers;
  live offline/reconnected UNC, mapped/cloud and removable-volume behavior.
- R03: disk-full/write/close/replacement errors, crash/storage interruption and
  recovery limitations; independently review the broader overwrite policy.
- R04: source startup/shutdown/restart using disposable UserSettings, malformed
  settings and Unicode paths; search/archive cancellation and orphan cleanup.
- R05: explicitly authorized full correctness suite, portable build and clean
  supported Windows artifact smoke, unelevated operation and upgrade persistence.
- R06: actual long-paths-disabled Windows host and live UNC staging. Native long
  paths with emulated unprefixed limits do not certify that configuration.
- R07: compatible candidate performance/persistence validation after changes.
  Existing full catalog evidence predates the latest operation fixes; no automatic
  rerun or relaxed compatibility checks. Keep the historical results intact.

### M01: Asynchronous Find-Dialog Matching

**Requires major changes and separate approval.**
`Quicksearch._on_text_changed -> _update_items` in
[Quicksearch](../src/main/python/fman/impl/quicksearch.py) synchronously consumes
the supplier on the Qt thread. SearchFileFuzzy's `get_items` closure in
[search commands](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/__init__.py)
calls `matcher.matches` there, so a broad ranked query scores its entire index
before the input handler returns. The small matcher optimizations in CodeReview004
do not remove this blocking boundary. Potential benefit: keep typing, painting
and cancel responsive on large recursive results, without making results compute
faster. No new latency measurement proves its magnitude; GIL and GUI-commit costs
remain relevant.

Do not move arbitrary public `show_quicksearch` suppliers to workers: plug-ins may
depend on Qt-thread execution. A separately reviewed, opt-in Find-specific result
path would need immutable inputs, a bounded latest-query queue, cancellation and
generation rejection, GUI-only item/model updates, Escape/close cleanup and
explicit Enter behavior while results are pending. Python CPU work can still
contend for the GIL; a worker alone is not proof of responsiveness. No process or
native matcher rewrite is selected. Profile query-to-paint and cancellation first;
approve a separate design only if the benefit justifies the added lifecycle and
API surface. Keep the ordinary synchronous Quicksearch contract unchanged.

### Investigations Not Promoted To New Work

- No duplicate initial Quicksearch evaluation or unconditional duplicate initial
  folder enumeration was established. Initial text is installed before signal
  connection; scan observation can reuse the initial listing. Do not remove the
  observation/watch handshake as an optimization.
- `ListingModel.find` builds a name map on its first lookup, and enabled status
  capture materializes entries on Qt before worker aggregation. These are real
  scaling surfaces, but a cache/payload redesign is not yet a small proven win.
  Keep them under C15 and FSPaneArch002; do not eagerly allocate more maps for
  every projection or silently change status-size freshness/limits.
- A whole-range `dataChanged` signal is not evidence that Qt repaints every row.
  C02 still needs dependency and cache evidence before narrowing notifications.

## Alternatives

- Drop deferred work when closing 003: rejected; retain an explicit handoff.
- Keep 003 pending indefinitely: superseded by user acceptance of its delivered
  batch, not by waiving the remaining release checks.
- Bundle this backlog with small optimizations: rejected; independent decisions
  keep CodeReview004 focused and avoid approving larger work implicitly.
- Add caching, timers or workers preemptively: prefer removing proven redundant
  work; retained memory, invalidation and thread/GIL costs need justification.

## Runtime Effects

This backlog has no runtime effect. Each selected item needs its own startup,
CPU, memory, I/O, cancellation and disabled-path assessment before implementation.
No new recurring work or settings persistence is approved. C13 removes one unused
clipboard string; other carried safety/policy investigations have no defensible
speed estimate yet. M01 could reduce input blocking, not total matching work.

## Tests

- Preserve all C/R/M definitions and the rejected/investigation notes during the
  split. Validate required sections, local links, unique index entries and
  historical record preservation; explicitly check untracked-file whitespace.
- C13: Core command tests with mocked clipboard must preserve chosen files,
  order, human-readable text and status, with no unused URL-string join.
- M01: a future design must specify delayed/out-of-order suppliers, rapid typing,
  stale acceptance, Escape/close and unchanged public Quicksearch tests first.
- Other candidates need exact focused regression commands and native prerequisites
  when selected. Existing implementation evidence remains in CodeReview003;
  R01-R07 are outstanding checks, not newly successful validations.
- Historical planning checks passed sections/IDs, local links, canonical paths,
  index placement, editor diagnostics and whitespace. The prior command was
  `git diff --check -- Plan.md Plan/CodeReview003.md Plan/CodeReview004.md Plan/LinkOperationPolicy.md Done/CodeReview003.md`,
  with explicit untracked-file checks. This is not runtime/release evidence.
- Current split check:
  `git diff --check -- Plan.md Plan/CodeReview004.md Plan/CodeReview099.md Done/CodeReview003.md`.
  No application suite, build or performance-catalog rerun is needed for relocation.

## Implementation Steps

1. Review and select individual backlog items; do not approve this as one batch.
2. Resolve each selected item's policy, owner, failure behavior, runtime cost and
   test prerequisites, coordinating with its existing canonical design.
3. Implement only approved work with a failing regression and immediate focused
   validation, then relevant native/integration checks and compatible measurements.
4. Run applicable release gates only with required approval and prerequisites;
   record unavailable checks as unrun and preserve historical results.

## Acceptance Criteria

- All unfinished 003 proposals/checks remain explicit; delivered and rejected
  work is not mislabeled as pending implementation.
- Each selected change has a reviewed, testable design and focused validation.
- Public APIs, safety refusals, Qt ownership and disabled-feature no-op behavior
  remain intact unless a separately approved design explicitly changes them.
- Major work and release certification cannot be inferred from the completion of
  CodeReview004 or relocation of this backlog.

## Reviewers

The first three records are preserved from the combined review before the split.
Their references describe that historical scope, not new work approved here.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Prepared the carry-forward inventory and release gates under the
  user's clarified small-new-change scope. Current-code responsiveness review
  follows before this draft is presented for implementation approval.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Completed the source/caller/test review with disposable deterministic
  probes for N01-N04. Retained all C01-C15 and R01-R07 handoffs; separated M01 as
  major-change design work, not implementation approval. No application changes,
  benchmark rerun or release approval; native/timing gates remain explicit.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: At the user's request, corrected this design's two existing attribution
  records to the assigned signature, effort and context size; other task records
  are unchanged. Added component-level gain estimates and user benefits, separating
  observed counts, extrapolated memory and unmeasured interaction latency. Focused
  arithmetic/document checks passed; no application change or speedup certification.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Separated C01-C15, R01-R07, M01, investigation notes and prior combined
  review provenance into this backlog at the user's request. CodeReview004 owns
  only its four small optimizations; no deferred item or release gate is waived.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Retained N05-N08 and N11-N13 after the user's authorization and
  completion of N01-N04, N09 and N10 only. Preserved the original evidence and
  historical reviews; DateFormat remains canonical for N13. No deferred work
  was authorized or release gate waived by closing CodeReview004.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Addressed the implementation review's N05 suggestion by recording
  the broader commit, pending-cursor, callback and view-revision constraints
  found in current source. Recommend a separately approved no-change refresh
  design; no production implementation, performance claim or waived gate.