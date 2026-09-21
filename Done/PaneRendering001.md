# Pane Rendering 001: Reuse Entry Hidden Attributes

Status: Implemented and validated on Windows; residual loading stalls remain.

## Task

Reduce repeated hidden-file queries before and after first pane display by
collecting ordinary Windows entries' own attributes during `os.scandir()` and
reusing them in Core's hidden-file filter. Keep real, complete `os.stat_result`
objects for all existing metadata and filesystem-operation consumers.

Date-format configuration is a separate task in [DateFormat.md](../Plan/DateFormat.md).
It is not part of this task's implementation or acceptance gates.

This independent first step follows [ImprovePaneScan.md](../Plan/ImprovePaneScan.md).
Its 202,603-entry baseline measured 1.991 s in post-render filter evaluations,
out of 2.636 s in Qt commits. Removing that repeated work targets the user's
priority of smooth interaction after rendering; it does not promise to eliminate
the whole loading tail or adopt the broader plan's `LazyStat` design.

## Scope

Included: Windows Core local enumeration, private invalidation-aware attribute
lookup, hidden-filter integration and focused correctness/performance tests.

Excluded: `LazyStat`/`LazyItem`, stat-cache seeding, column/date-format changes, delayed reveal,
batch scheduling, sorting/notification/layout changes, new settings/dependencies,
workers/timers, file watching and general cache optimization. Drive/share roots
themselves, UNC/network paths, links/reparse points, unsupported providers and
non-Windows behavior retain their old visibility path. Ordinary children of drive
roots remain eligible.

Compatibility: preserve public `fman` API signatures, real full-stat results and
identity/error/link-target semantics; no change to copy/move/delete decisions.
Stable entries must match Qt visibility. Unnotified external changes have the
explicit snapshot-freshness qualification below. Existing date presentation and
configuration remain unchanged by this task.

## Design

### Ownership and Data Flow

1. [LocalFileSystem.iterdir](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py)
   retains its list-of-names return contract. For supported Windows drive paths,
   use a context-managed `os.scandir()` and materialize the names, as `listdir`
   does today. Unsupported paths/platforms retain `listdir` without new metadata
   collection. Do not sort or change the provider's enumeration ordering policy.
2. Obtain `entry.stat(follow_symlinks=False).st_file_attributes` for each entry.
  Retain only an integer attribute value, never the `DirEntry` or its stat
  result. Reparse entries and failed/unknown attributes publish `None`, replacing
  any earlier eligible value. They retain Qt fallback without losing the name.
3. Store eligible attributes under a private key distinct from `stat`, alongside
   the existing provider cache entries. Do not overwrite any full-stat result.
4. Expose one private Core-provider method, `_pane_hidden_state`,
   returning `True`, `False`, or `None` (no usable snapshot). It performs no
   filesystem I/O and does not fill a miss with a fresh stat. Resolve roots and
   unsupported paths lexically before lookup; never follow links to classify them.
5. [Core._hidden_file_filter](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)
   uses the existing `fman.fs.query` dispatch to request that private capability
   only for eligible Windows `file://` URLs. On a valid boolean, invert it to
   decide visibility. Otherwise use the existing
   [QFileInfo helper](../src/main/resources/base/Plugins/Core/core/commands/util.py).
    Preserve nonlocal and Mac-specific branches. An absent private method
    (`AttributeError` at provider method resolution) or `OSError` falls back.
    A cache miss returns `None` inside the provider. Errors inside an existing
    method propagate, including `AttributeError`; focused tests cover the distinction.

This privately couples bundled Core commands to their provider without adding a
required public `FileSystem` method. Host models, columns and dispatch stay unchanged.

### Roots, Links and Fallback

| Input | Required behavior |
| --- | --- |
| Ordinary local entry with a valid snapshot | Test its own `FILE_ATTRIBUTE_HIDDEN` bit. |
| Drive root, UNC/share root or unsupported path spelling | Existing Qt helper; roots are never seeded merely because their directory was enumerated. |
| Symlink, junction or any reparse entry, including cloud placeholders | Existing Qt helper, even if a followed target has a cached stat. |
| Unseeded, failed, missing or invalidated entry metadata | Existing Qt helper; no extra path stat before fallback. |
| Nonlocal scheme | Existing filter behavior; no new local metadata query. |

Never use followed `stat().st_file_attributes`: a visible junction to a hidden
target must stay visible, and roots with `HIDDEN | SYSTEM` must keep Qt semantics.

OneDrive and other cloud folders may mark every entry as a reparse point. Those
entries get no hidden-query reduction in this task; own-attribute reuse for them
is a separate measured follow-up, not part of this design.

### Cache Lifetime and Concurrency

Use a private local-provider Cache specialization with temporary active-scan
tokens. A clear of
the scan directory, an ancestor or a descendant invalidates its token under the
same short-held lock used for attribute publication and inherited clear. A newer
scan of the same directory supersedes the older token; context exit removes it.
Unrelated clears do not cancel scans. Completed values retain the existing
entry-cache lifetime, with no epochs, per-entry generations or notification hooks.
The lock is never held during enumeration, metadata I/O, cache computation, Qt
calls or waits. Existing get/put/query behavior is inherited, and the shared
Cache implementation is unchanged. Barrier tests must prove late publishers
cannot recreate cleared entries or overwrite a newer scan.

The guard is necessary because late `cache.put(path, ...)` is not equivalent to
the existing cached-stat publication:

- `Cache.query` resolves a `CacheItem` before computing. Clearing its path while
  computation runs detaches that item. The old caller may still receive an old
  result, but completing that computation does not overwrite the replacement node.
- `Cache.put` resolves the path when called. A scan that publishes after a clear
  can recreate the node or overwrite attributes from a newer scan.
- A deterministic in-memory probe of the actual Cache confirmed this difference
  for entry, parent-directory and whole-cache clears. It does not establish that
  the existing cache is generally race-free.

Use existing provider path conventions, not new case-folding or alias rules.
The [shared Cache](../src/main/python/fman/impl/fs_cache.py) and notifications
remain unchanged. An entry clear retains already published siblings. There is no
long-lived second metadata dictionary; the token map contains only active scans.

Following Fable's implementation review, resolve the directory `CacheItem` once
under the scan lock and publish into its children instead of walking from the
root for every entry. Keep the token guard: a detached parent must not receive
new usable attributes after a clear. The lookup path retains only the last
directory path/node pair, resolves its children by name, and drops that pair on
every clear under the same lock. A miss never creates a node. This bounded
reference cache adds no metadata copy, worker or I/O; ordinary Cache APIs remain
unchanged. Two panes may replace the last-directory reference without affecting
correctness. This is private coupling to the existing `CacheItem` traversal.

A single entry clear conservatively cancels the entire active parent scan's
publication. Already published siblings remain cached; later entries keep their
names but fall back to Qt until another scan. This is intentional, not a failed
listing or an attempt to preserve per-entry generations.

Windows watching remains a stub: unnotified attribute changes can be seen later
than with uncached Qt queries. Refresh/invalidation discards the snapshot; hidden
toggling alone does not promise a new scan. This reviewed display-only snapshot
contract is documented in Core usage instructions. No watcher or polling is added.

### Threading, Cancellation and Errors

Enumeration stays on the existing worker; Qt/model ownership is unchanged.
Materialize names to avoid a generator handle retained by `CachedIterator`.
Close the iterator on success/error. Directory-open/iteration failures propagate,
never return a successful partial listing; attribute failures keep the name.

Keep existing navigation/shutdown stale-model rejection. A running enumeration
may finish, but cannot republish hidden snapshots after invalidation. No new joins,
event pumping or cancellation service; blocked I/O retains its existing limits.

Persistence: not applicable; process-local cache only, no settings/Registry writes.

## Alternatives

- **Followed cached stat for hiddenness:** rejected; it misclassifies links and
  roots, as Fable's probes demonstrated.
- **LazyStat or reparse-point optimization:** deferred to keep this step's public
  metadata and special-entry behavior unchanged.
- **Global dictionary or expiry timer:** rejected; separate lifetime and recurring work.
- **Global or per-entry epochs:** rejected; temporary scan tokens protect late
  writes without invalidating unrelated completed snapshots.
- **Raw late put/shared Cache rewrite:** rejected for this task; the former can
  revive invalidated data, while the latter broadens the public provider risk.
- **Delayed reveal/smaller batches:** separate scheduling experiments.

## Runtime Effects

- Startup/loading: one directory enumeration, plus attribute extraction per entry;
  existing per-file full stats remain. No promise of Fable's complete LazyStat gain.
- CPU/I/O: eligible filter passes become cache/bit checks instead of repeated
  `QFileInfo` calls. Special entries retain their original Qt work. Entry-stat cost
  can depend on filesystem behavior; verify Windows results rather than assume zero I/O.
- Memory: one integer or `None` per enumerated cache entry, plus temporary scan
  tokens and one last-directory lookup reference. No retained handles or second
  full-stat snapshot. Working-set results
  below measure the whole process, not isolated allocation size.
- Threading/cancellation: one short-held lock, no new workers/processes/timers;
  stale publication is rejected, existing model cancellation/scheduling unchanged.
- Disabled/no-op: no feature toggle is added. Unsupported providers/platforms use
  their previous paths. When hidden files are shown, the filter performs no lookup;
  one-pass collection is still allowed because the provider cache can serve another
  pane with hidden filtering enabled. This eager per-scan cost is intentional and
  must be measured with the filter off; no separate scan or background job is allowed.

## Tests

### Unit and Integration

Extend existing test modules rather than creating a parallel suite:

- [core.tests.fs.test_local](../src/main/resources/base/Plugins/Core/core/tests/fs/test_local.py):
  names/empty folders/Unicode/missing folders; iterator closure on success and
  failure; per-entry attribute failure keeps the entry; directory failure does
  not publish a successful partial listing. Fake entries assert only non-following
  attribute reads and no full-stat cache seeding.
- In that module, exercise the private cache with Events/barriers, not sleeps:
  invalidate entry, subtree, empty root and missing path between collection and
  publication; late writes are rejected; new scans can publish; concurrent reads
  and scans preserve full stat values and never deadlock. Check missing-path
  clears, unrelated clears, preserved siblings, replaced scans and closed publishers.
- [core.tests.commands.test___init__](../src/main/resources/base/Plugins/Core/core/tests/commands/test___init__.py):
  eligible hidden/visible entries use cached booleans; zero Qt calls across repeated
  passes. Root, UNC, reparse, unknown/failed/stale metadata and missing provider
  capability call the existing helper and return exactly its result. Nonlocal and
  Mac exceptions retain their behavior. A fallback does not introduce a path stat.
  Distinguish an absent provider method from `AttributeError` raised inside an
  existing method; only the former falls back. Test `OSError` fallback separately.
- Real temporary Windows fixtures: ordinary hidden files/directories, dot-prefixed
  visible names, roots, hidden links to visible targets, visible links/junctions
  to hidden targets, broken links, and changed hidden attributes followed by
  refresh. Compare against `QFileInfo` directly. Mock all branches portably; record
  privilege/network skips and require live root/link validation before release.
- Explicit read-only `C:` and `C:/` listing tests compare every child against
  `QFileInfo`, while root lookup itself always falls back. Compare Qt using the
  exact scheme-less path passed by the original helper, not a normalized variant.
- Full-stat compatibility before/after enumeration: `type(result) is os.stat_result`,
  indexing/tuple conversion, errors, device/inode/link count, hard-link `samefile`,
  same/cross-device operation decisions and target-following directory/size/date
  behavior stay unchanged. Use temporary files only for destructive operations.
- [SortedFileSystemModelIT](../src/integrationtest/python/fman_integrationtest/test_qt.py):
  two panes sharing the provider, hidden toggle and refresh, notification-driven
  invalidation, navigation during collection, final row/order parity, and intact
  cursor/selection. Check thread affinity; no new timer/job when filtering is off.
- Existing unimplemented `LazyStat` tests remain outside this task's gates.

Focused commands, from the existing application environment (Python 3.14.7):

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_local', 'core.tests.commands.test___init__', 'core.tests.test_fileoperations', 'fman_unittest.impl.test_fs_cache', 'fman_unittest.impl.plugins.test_mother_fs', 'fman_integrationtest.test_qt.SortedFileSystemModelIT', 'fman_integrationtest.test_qt.FilterBarIT.test_special_filenames_and_status_mode_changes', '-q'], env=env, timeout=120).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.impl.test_status_bar', '-q'], env=env, timeout=60).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'fman_integrationtest.quick_view_smoke'], env=env, timeout=150).returncode)"
```

New cache and provider/filter cases were run failing before implementation and
passing after their respective slices. No full suite or clean/freeze/package.

### Performance and Manual Checks

- Compare baseline and candidate in alternating order, three fresh-process runs
  each, on small fixtures and at least three large read-only folders, including
  the 202,603-entry reference folder. Use disposable settings; report OS-cache
  conditions, counts, medians and ranges. Retain the reproducible procedure and
  per-folder before/after results in this task record, without machine-specific
  absolute paths. Do not modify source folders or flush system caches.
- Count `QFileInfo` hidden queries, full path stats and entry-attribute reads.
  Three filter passes over stable eligible entries should require one attribute
  collection per entry and no Qt hidden queries; full-stat semantics stay intact.
- Report worker preparation, first paint, Qt commit time, metadata tail, time
  until usable, post-render arrow-to-cursor/paint latency and memory. Start with
  QuickView/status off, then check enabled features; include filter-off overhead.
- Require stable-fixture visibility, row order and displayed metadata equality,
  and no new input/cancellation regression. Report residual stalls honestly; this
  step alone is not acceptance of the broader pane-responsiveness project.

## Implementation Steps

1. Resolve and review the private cache lifetime/publication and snapshot-freshness
  contract before hidden-cache implementation. Align the proposal and tests, then
  add failing provider/filter regression cases in existing test modules.
2. Add the approved guarded cache operations and race tests. Preserve all
   inherited ordinary cache behavior and prove stale publication rejection.
3. Add context-managed Windows enumeration and eligible attribute collection;
   retain full-stat and unsupported-path behavior. Run provider tests immediately.
4. Add the private lookup and filter integration with roots/reparse/unknown-data
   fallback. Run filter and Qt integration tests immediately.
5. Run operation-safety tests and the performance/manual matrix; accept only a
   repeatable reduction in repeated hidden checks with acceptable overhead.
6. Document actual behavior and snapshot refresh semantics in README/Core usage
  docs and CHANGELOG. Record results and implementation provenance here;
   move this canonical file to Done and its index entry to Completed only when
   its own gates pass. Leave broader scan/rendering work separate.

## Acceptance Criteria

- Eligible stable entries match Qt visibility while repeated hidden-file passes
  reuse enumeration attributes. Root/link/UNC/unsupported behavior uses Qt unchanged.
- No public proxy or incomplete stat result; ordinary metadata, identity and
  operation safety remain unchanged and tested.
- Invalidation prevents stale scans and recreated paths from reviving cached
  hidden flags. Expected errors fall back without hiding entries or emptying panes.
- Iterator closure, threaded cache tests, shared-provider refresh/navigation and
  row/cursor/selection parity pass; environmental gaps are explicitly recorded.
- Snapshot freshness is reviewed and documented. No unexpected setting, new job,
  timer, model API or metadata cache is introduced.
- Measured filter/commit benefits outweigh collection/locking/memory overhead;
  no claim of guaranteed smoothness or initial-stat elimination from this task alone.
- Focused tests and release-relevant manual checks pass, implemented behavior is
  documented, and the task record is completed according to repository policy.

## Reviewers

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Narrow hidden-attribute reuse design with real stat results, Qt special-
  entry fallback, provider-local invalidation epochs and focused tests. Snapshot
  freshness requires review; no runtime change or implementation approval claimed.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Scope, data flow, root/link fallback table and test plan approved;
  **not approved as written** because "Cache Lifetime and Concurrency" adds
  machinery that raises risk without raising the guarantee. Requested changes:
  1. **Drop the epoch, the extra lock and the `Cache` subclass.** Store the
     integer under a private attribute key on the *same* cache node as `stat`
     (`cache.put(path, '_entry_attributes', value)` during the scan). Every
     invalidation path that protects `stat` today then protects the flag with
     zero new code: `clear_cache(location)` at `_init`/`reload`,
     `MotherFileSystem._remove` on removal, and the model's per-path clear on
     `notify_file_changed`. The stale-publication race the epoch guards against
     exists identically for `stat` (`CacheItem.query` stores whatever `compute`
     returns after a concurrent `clear`) and for the cached `iterdir` list; the
     pane already displays cached size/mtime with exactly that freshness.
     Guarding hidden-ness more strictly than the size shown beside it is
     inconsistent, and the subclass that intercepts `clear` plus a second lock
     is the only part of this design that can deadlock or be ordered wrongly.
     If a stricter contract is ever wanted, apply it to the whole node, in a
     separate task.
  2. **Freshness contract = the stat cache's.** Rewrite the "requires design
     approval" paragraph as: hidden-ness now has the same lifetime as the other
     cached metadata of the entry (arguably more consistent than today, where
     visibility was live but size was not). `FileSystem.notify_file_changed`
     does not clear the cache itself; do not add a hidden-only clear there —
     parity with `stat`, nothing more.
  3. **Catch `AttributeError` narrowly** when `fman.fs.query(url,
     '_pane_hidden_state')` hits a provider without the method (the private
     dispatch is acceptable inside Core); on `OSError` fall back; let anything
     else propagate, as the design already says.
  4. **Reparse points**: excluding them is safe, but note that OneDrive and
     other cloud placeholders set `FILE_ATTRIBUTE_REPARSE_POINT` on every file,
     so such folders get no gain. The probe showed the entry's own attributes
     already match `QFileInfo` for junctions; publishing them for reparse
     points too is a measured follow-up, not a change requested here.
  Confirmed: referenced test modules and `SortedFileSystemModelIT` exist;
  `DirEntry.stat(follow_symlinks=False)` on Windows reads `FindFirstFile`
  data with no syscall (0.7 µs/entry measured including enumeration); scandir
  and listdir return the same enumeration order. Expected gain unchanged:
  the three `QFileInfo` passes (~1.9 s worker, ~1.5 s Qt commit, ~2.0 s
  post-render) become cache reads; the 3.73 s of per-file `os.stat` remains
  for the `LazyStat` step, which can reuse this scandir enumeration.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Agreed with simplifying toward the existing metadata-cache lifecycle,
  keeping roots/reparse entries on Qt, documenting cloud-folder limitations and
  narrowly handling a missing private method. Did not accept the stated equivalence
  between late `Cache.put` and in-flight `Cache.query`: a read-only Python 3.14.7
  probe using the repository Cache preserved the fresh node after query completion
  but overwrote fresh attributes with a late put, for entry/subtree/root clears.
  Recorded this distinction and left publication unresolved; neither raw late put
  nor the original epoch/subclass proposal is approved. No application edits.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Added the user-requested ISO-date/24-hour-only UI policy and an
  independent Modified-column formatting slice. Fixed `yyyy-MM-dd HH:mm` removes
  per-value locale-format discovery and year rewriting while preserving timestamp
  conversion and sorting. Existing search/date-input formats already align; added
  locale/boundary/error tests and a focused column-test command. Design only;
  hidden-cache publication remains unresolved and no application code changed.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: At the user's request, moved active date-format requirements, tests
  and implementation steps to DateFormat.md. This task again covers only hidden-
  attribute optimization; prior date-format records remain historical. Cache
  publication remains unresolved. Documentation only; no application changes.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the implementation choice after the user's implementation
  request: temporary overlapping-scan tokens replace global epochs, with a
  provider-local clear/publication lock but no notification overrides. Ordinary
  completed metadata keeps its existing lifetime. Require deterministic barrier
  tests before integration and retained before/after measurements on at least
  three large folders. Date formatting remains outside this task.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review; approved. Production change is small and
  where the design put it: `_EntryAttributesCache` (scan tokens, one lock,
  `clear` override) and `iterdir`/`_pane_hidden_state` in `core/fs/local`,
  plus a 14-line branch in `_hidden_file_filter`; host code, the shared
  `Cache`, columns and the model are untouched. Verified: no lock-order risk
  (`put`/`clear` acquire nothing beneath `_scan_lock`); `_supports_entry_attributes`
  excludes UNC, backslash and `.`/`..` spellings; `_pane_hidden_state` returns
  `None` for roots (`len <= 3`) and for unseeded/None nodes; the `AttributeError`
  branch distinguishes an absent provider method from one raised inside it;
  non-Windows keeps the plain `Cache` and never queries; `stat.FILE_ATTRIBUTE_*`
  constants exist on all platforms. Re-ran the documented gate: 259 tests, OK
  (5 privilege skips). Probe against the real provider: hidden/visible states
  correct, entry clear and directory clear both drop the flag, a scan
  interrupted by a clear of one of its entries stops publishing (conservative,
  correct). The retained before/after tables are the decisive evidence
  (reference folder first paint 9.0 s → 6.1 s, post-render Qt commits
  2.78 s → 1.15 s, `QFileInfo` calls 607,775 → 0). Non-blocking notes:
  1. Publication and lookup each re-walk the full path through `Cache`
     (`update_child`/`get_child` split eight components per entry): 539 ms to
     publish and 269 ms to look up 202k entries in the probe (~2.3 and ~1.3 µs
     each). Resolving the directory node once per scan and publishing/reading
     on its children would cut both by roughly 5x; the enumeration would return
     to ~150 ms. Pure optimisation, no semantic change.
  2. A `clear` of a single entry cancels the in-flight scan of its parent
     directory, so a `notify_file_changed` during a long scan leaves the
     remaining entries on the `QFileInfo` path until the next scan. Correct and
     rare; worth a line in the design so it is not mistaken for a bug.
  3. `iterdir` now raises mid-iteration errors from `scandir` where `listdir`
     raised before returning; both surface as a failed listing. No caller
     distinguishes them, but it is a behaviour difference worth one test.
  This step delivers what was recommended; the remaining 3.7 s of per-file
  `os.stat` and the 6.5 s tail belong to the scan (`LazyStat`) step or to the
  columnar redesign in `Plan/FuturePaneArch.md`.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Accepted Fable's parent-node reuse suggestion with the existing scan
  guard intact and a bounded last-directory lookup invalidated on every clear.
  Documented conservative parent-scan cancellation after an entry clear. The
  mid-iteration failure test already existed; strengthened exception propagation,
  listdir/scandir failure parity and recovery coverage. Retained three-pair
  application measurements, not the proposed 5x microbenchmark estimate.

## Implementer

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented provider-local scan tokens, own-attribute collection and
  private filter lookup with Qt fallback. Added cache-race, native operation,
  root, junction and shared-pane regressions. Focused gate: 259 tests, five
  privilege skips; 12 status tests and native QuickView source/restart smoke pass.
  Retained isolated three-pair measurements for three large folders and C root,
  including filter-off overhead. Full stat and date formatting remain unchanged.

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reused directory nodes for guarded publication and hidden lookups;
  added five cache regressions and strengthened enumeration-failure/cancellation
  tests. The 264-test compatibility gate passed with five privilege skips;
  12 native status tests and QuickView source/restart passed. Added reviewed
  benchmark baseline and post-timing row diagnostics; fixed benchmark URL casing.
  All 38 final matrix samples passed row/metadata parity and isolation checks.
  Reference first paint improved 6.09 -> 5.78 s versus the reviewed cache;
  remaining loading stalls are not solved by this follow-up.

## Validation Results

### Correctness

The three commands in Tests passed on 2026-09-21 using the existing application
environment, Python 3.14.7 and Qt 5.15:

- Combined regression gate: **259 tests, 254 passed, five skipped** (1.234 s).
  Skips are the new native symlink case, existing nonexistent-symlink stat and
  directory-symlink deletion cases, and inherited copy/move symlink cases. This
  Windows account lacks symlink creation privilege; no elevation was attempted.
- Native status gate: **12 passed** (0.500 s), including queued Qt-thread delivery.
  The combined gate also exercises active-pane, per-pane and disabled status modes
  with a real local pane, filtering and cursor movement.
- Native QuickView source and fresh-process restart smoke: both passed, including
  image pixels, real shortcuts, both source panes, preserved layout and cleanup.
- Live `C:` and `C:/` enumeration matched Qt for every child; root lookup kept
  exact original Qt path semantics. Root tests and benchmarks are read-only.
- Live junction-to-hidden-directory, hardlink identity, copy/rename/delete,
  real `os.stat_result` identity/tuple fields and cross-device dispatch passed.
  Cross-device selection is simulated; no second physical volume was mutated.
- Event barriers passed for stale publication and navigation away during a blocked
  scan. Shared panes passed hidden toggle, cursor/selection preservation, per-file
  invalidation, directory refresh, rename/delete and Qt-thread signal checks.
- No diagnostics in the six changed Python files. Documentation whitespace and
  local-link checks passed. Reviewer records are preserved; no date-format code,
  shared Cache, model scheduling, dependency or packaging changes were made.

Initial failures caught missing cache implementation, native root-test path
normalization, and a test's incorrect notification assumption. Root comparisons
now use the original scheme-less path. Per-file model invalidation is tested
separately from provider directory notifications, which notify exact subscribers.
No production root or notification semantics were changed to accommodate tests.

Live UNC/cloud storage was unavailable; fallback branches are covered with mocks.
The junction test supplies live reparse coverage, not a substitute for future
symlink/UNC release checks. No full test suite, clean, freeze or packaging ran.

### Measurement Procedure

The tracked [benchmark](../src/integrationtest/python/fman_integrationtest/pane_rendering_benchmark.py)
starts a fresh native Windows Qt application for each sample. `before` restores
only the pre-change `listdir`, ordinary Cache and Qt-only hidden filter in that
child process (checkout baseline `3104900`); `after` uses production code.
There are three pairs per folder, in before/after, after/before, before/after order.
System caches were not flushed; these are warm-cache, read-only measurements,
not cold-storage guarantees. No source folder was modified.

Each child creates disposable settings before importing fman, asserts the effective
settings directory and both panes' requested filter state, and starts QuickView
and extended status off. Final benchmark guards also reject an imported QuickView
renderer, an active status service/tracker, or hidden queries with filtering off;
they passed additional before/after C-root runs in both modes. Earlier results
from an import-order isolation bug were discarded and replaced by the runs below.

Timing starts at target-model initialization, not process startup. Preparation
ends at the first Qt row commit; first paint is the first nonempty pane paint;
completion is `all_rows_loaded`. Tail is completion minus first paint. Qt commit
totals below exclude the initial row commit. Working set is sampled after loading,
not peak memory. Hidden helper and path-stat calls are counted; entry-attribute
read counts are derived from enumeration size, with one non-following read per
entry enforced by unit tests. Full path-stat counts did not decrease.

After first paint, a worker posts one arrow at a time and measures delivery to the
expected cursor row and subsequent paint. It waits for acknowledgment, then 50 ms
before the next key; settled sampling lasts two seconds. No synchronous Qt call
precedes each timed post. These measurements exclude the display compositor,
held-key backlog and other file-operation latency. Short loads have very few
loading samples, so their p95 is not a robust distribution estimate.

Reproduce from the application environment after setting `$env:PANE_BENCHMARK_LARGE_FOLDER`
to the chosen read-only large reference folder:

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'fman_integrationtest.pane_rendering_benchmark', os.environ['PANE_BENCHMARK_LARGE_FOLDER'], os.path.join(os.environ['WINDIR'], 'System32'), os.path.join(os.environ['WINDIR'], 'WinSxS'), 'C:/', '--repeat', '3', '--output', 'target/diagnostics/pane-rendering-before-after.json'], env=env, timeout=900).returncode)"
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'fman_integrationtest.pane_rendering_benchmark', os.environ['PANE_BENCHMARK_LARGE_FOLDER'], '--show-hidden', '--repeat', '3', '--output', 'target/diagnostics/pane-rendering-filter-off.json'], env=env, timeout=300).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; command=[sys.executable, '-m', 'fman_integrationtest.pane_rendering_benchmark', 'C:/', '--repeat', '1']; first=subprocess.run(command+['--output', 'target/diagnostics/pane-rendering-root-guards.json'], env=env, timeout=120); sys.exit(first.returncode or subprocess.run(command+['--show-hidden', '--output', 'target/diagnostics/pane-rendering-root-show-hidden.json'], env=env, timeout=120).returncode)"
```

The JSON artifacts remain under ignored `target/diagnostics`; the tables here
retain the results in version control. All 30 matrix samples had zero recorded
application exceptions, verified isolation and an identical ordered name/displayed
cell fingerprint for each folder/filter-mode group. C-root guard runs also matched.

### Retained Before/After Results

Hidden filtering enabled; times are **median [min-max] milliseconds** over three
fresh processes. The reference folder is CelebAAligned, 202,603 entries. System32
has 4,757 entries, WinSxS 24,315, and C root 19 (nine visible with filtering).

| Folder | Mode | First paint | Metadata complete | Post-paint tail | Post-render Qt commits |
| --- | --- | --- | --- | --- | --- |
| CelebAAligned | Before | 8994.9 [8182.5-9222.5] | 17693.7 [16071.8-18072.3] | 8698.8 [7889.3-8849.8] | 2780.1 [2444.4-3186.3] |
| CelebAAligned | After | 6136.9 [5971.8-6259.5] | 12689.6 [12219.1-13230.1] | 6552.7 [6247.3-6970.5] | 1146.7 [1015.8-1362.6] |
| System32 | Before | 266.3 [265.9-299.8] | 435.1 [434.6-471.6] | 168.8 [168.6-171.8] | 65.8 [65.6-65.8] |
| System32 | After | 182.5 [180.8-183.0] | 303.6 [301.2-304.4] | 121.1 [120.5-121.4] | 18.9 [18.8-19.3] |
| WinSxS | Before | 1400.5 [1379.3-1538.1] | 2483.5 [2456.8-2683.0] | 1083.0 [1077.5-1144.9] | 497.8 [497.1-568.9] |
| WinSxS | After | 788.7 [777.5-811.0] | 1511.0 [1493.3-1532.2] | 721.2 [715.8-722.3] | 139.9 [139.6-144.4] |
| C root | Before | 58.0 [57.6-58.1] | 67.8 [67.1-68.8] | 9.7 [9.5-10.7] | 0 |
| C root | After | 64.8 [61.6-66.2] | 74.7 [72.5-75.9] | 9.8 [9.7-10.8] | 0 |

Preparation, enumeration and memory; times are medians in milliseconds and
working set is median [min-max] MiB. Counts were constant within each group.

| Folder | Mode | Enumeration | Worker prepare | Initial Qt commit | Qt hidden queries | Path stats | Working set |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CelebAAligned | Before | 41.8 | 6361.9 | 2555.0 | 607775 | 202603 | 809.4 [809.4-811.3] |
| CelebAAligned | After | 554.6 | 4898.6 | 1170.1 | 0 | 202603 | 807.4 [807.1-807.5] |
| System32 | Before | 3.5 | 124.8 | 61.5 | 14237 | 4757 | 112.4 [112.3-112.4] |
| System32 | After | 12.1 | 86.5 | 16.4 | 0 | 4757 | 112.3 [112.2-112.3] |
| WinSxS | Before | 33.5 | 974.8 | 358.0 | 72911 | 24315 | 193.4 [193.4-193.6] |
| WinSxS | After | 79.5 | 635.1 | 84.6 | 0 | 24315 | 193.9 [193.1-194.0] |
| C root | Before | 0.2 | 5.0 | 0.7 | 38 | 21 | 92.5 [92.1-94.8] |
| C root | After | 0.4 | 12.7 | 0.5 | 2 | 21 | 92.8 [92.5-94.6] |

Candidate attribute reads: respectively 202603, 4757, 24315 and 19; baseline zero.
The two remaining C-root hidden calls use the required special-entry fallback.
Working-set differences are small process-level noise, not evidence of zero
allocation cost or a memory optimization.

Input latency: **median of per-run p95 [min-max] milliseconds**, not a pooled p95.

| Folder | Mode | Loading arrow-to-cursor | Loading arrow-to-paint | Settled arrow-to-cursor | Settled arrow-to-paint |
| --- | --- | --- | --- | --- | --- |
| CelebAAligned | Before | 360.1 [266.7-467.4] | 677.7 [544.3-700.6] | 1.6 [1.4-1.8] | 2.7 [2.1-2.7] |
| CelebAAligned | After | 230.1 [227.9-270.6] | 380.6 [357.6-413.3] | 1.7 [1.6-1.9] | 2.6 [2.5-2.8] |
| System32 | Before | 162.8 [162.7-165.1] | 163.4 [163.4-165.8] | 1.4 [1.4-1.5] | 2.1 [2.0-2.4] |
| System32 | After | 115.4 [114.6-115.5] | 116.1 [115.3-116.2] | 1.4 [1.3-1.6] | 2.2 [2.1-2.3] |
| WinSxS | Before | 418.0 [413.0-461.1] | 569.1 [563.9-588.3] | 1.7 [1.7-1.8] | 2.8 [2.8-3.3] |
| WinSxS | After | 285.0 [282.6-286.2] | 452.7 [419.7-473.2] | 1.5 [1.5-1.6] | 2.6 [2.5-2.7] |
| C root | Before | 4.7 [4.4-4.8] | 5.3 [4.8-5.7] | 1.5 [1.3-1.5] | 2.2 [2.2-2.4] |
| C root | After | 4.8 [4.3-5.4] | 5.6 [5.4-5.9] | 1.4 [1.4-1.5] | 2.2 [2.1-2.3] |

Per-run first-paint / completion pairs (milliseconds), ordered by pair number:

| Folder | Mode | Pair 1 | Pair 2 | Pair 3 |
| --- | --- | --- | --- | --- |
| CelebAAligned | Before | 8994.9 / 17693.7 | 8182.5 / 16071.8 | 9222.5 / 18072.3 |
| CelebAAligned | After | 6136.9 / 12689.6 | 5971.8 / 12219.1 | 6259.5 / 13230.1 |
| System32 | Before | 299.8 / 471.6 | 266.3 / 435.1 | 265.9 / 434.6 |
| System32 | After | 182.5 / 303.6 | 183.0 / 304.4 | 180.8 / 301.2 |
| WinSxS | Before | 1538.1 / 2683.0 | 1379.3 / 2456.8 | 1400.5 / 2483.5 |
| WinSxS | After | 788.7 / 1511.0 | 777.5 / 1493.3 | 811.0 / 1532.2 |
| C root | Before | 57.6 / 67.1 | 58.0 / 68.8 | 58.1 / 67.8 |
| C root | After | 61.6 / 72.5 | 64.8 / 74.7 | 66.2 / 75.9 |

### Filter-Off Cost and Remaining Limits

With hidden files shown in both panes, all six CelebAAligned runs made **zero**
hidden helper calls, retained all 202603 rows and still made 202603 path stats.
One-pass capture remains intentional so the provider can serve another pane with
filtering enabled. It introduces no additional worker, timer or separate scan.

| Metric | Before median [min-max] | After median [min-max] |
| --- | --- | --- |
| Enumeration, ms | 40.1 [39.5-40.8] | 540.2 [534.4-540.7] |
| Worker prepare, ms | 4079.7 [4005.8-4108.2] | 4128.0 [4112.9-4246.3] |
| First paint, ms | 4560.3 [4468.6-4605.2] | 4846.4 [4827.8-5045.2] |
| Metadata complete, ms | 10726.8 [10347.9-10920.9] | 10568.1 [10362.4-11277.1] |
| Post-render Qt commits, ms | 526.1 [506.7-861.3] | 834.7 [497.7-886.0] |
| Loading cursor p95, ms | 245.3 [166.1-425.6] | 346.2 [210.0-419.6] |
| Loading paint p95, ms | 471.6 [297.2-674.1] | 424.3 [412.7-490.8] |
| Settled cursor p95, ms | 1.6 [1.5-1.6] | 1.6 [1.6-1.6] |
| Settled paint p95, ms | 2.5 [2.4-2.7] | 2.5 [2.5-2.6] |
| Working set, MiB | 808.4 [807.0-810.1] | 807.5 [806.9-807.6] |

Filter-off first-paint/completion pairs: before 4468.6/10347.9,
4560.3/10726.8, 4605.2/10920.9; after 4846.4/10568.1,
4827.8/10362.4, 5045.2/11277.1 ms.

The filter-on reference gain is 31.8% earlier first paint, 28.3% earlier metadata
completion and 58.8% less post-render Qt commit time by medians. Collection costs
about 0.50 s on 202603 entries with filtering off; first paint is 0.29 s (6.3%)
later. Completion ranges overlap and loading-latency results vary, so no filter-off
speedup or responsiveness improvement is claimed. The small C-root matrix is
about 7 ms slower overall; this task is a large-folder optimization, not a
universal startup gain.

The optimized reference still has a 6.55 s metadata tail, loading cursor latency
up to 412 ms and paint latency up to 486 ms. Full stat work and existing batching
remain. This completes only hidden-attribute reuse, not the broader requirement
for smooth operations immediately after first display.

### Fable Review Follow-Up Timings

The preceding tables retain the original implementation measurements. This
follow-up compares **reviewed** (hidden-attribute cache with full-path traversal)
against **revised** (parent-node reuse), not against the snapshot PoC. Same
Python/Qt environment and warm-cache procedure, three fresh-process pairs per
folder with reversed order in pair 2, isolated settings, QuickView/status off.
Canonicalize the requested path before instrumentation so `%WINDIR%` casing
agrees with the application's resolved URL. No source folder was modified.

All times below are milliseconds; medians over three runs:

| Folder | Enumeration reviewed -> revised | First paint reviewed -> revised | Completion reviewed -> revised |
| --- | ---: | ---: | ---: |
| CelebAAligned (202603) | 588.3 -> 528.3 | 6090.8 -> 5780.0 | 12735.7 -> 11851.3 |
| System32 (4757) | 12.0 -> 11.3 | 193.1 -> 190.9 | 317.8 -> 314.1 |
| WinSxS (24315) | 77.2 -> 72.8 | 830.9 -> 800.6 | 1593.5 -> 1527.3 |
| C root (19; 9 visible) | 0.238 -> 0.303 | 58.8 -> 58.7 | 68.9 -> 69.1 |

Retained first-paint/completion pairs, milliseconds:

| Folder | Mode | Pair 1 | Pair 2 | Pair 3 |
| --- | --- | --- | --- | --- |
| CelebAAligned | Reviewed | 5861.6 / 11911.5 | 6147.3 / 12735.7 | 6090.8 / 12927.8 |
| CelebAAligned | Revised | 5780.0 / 11851.3 | 5758.2 / 11767.8 | 6017.0 / 12626.4 |
| System32 | Reviewed | 193.1 / 310.3 | 193.2 / 319.4 | 190.1 / 317.8 |
| System32 | Revised | 191.0 / 316.1 | 185.3 / 308.8 | 190.9 / 314.1 |
| WinSxS | Reviewed | 810.4 / 1547.5 | 840.1 / 1593.5 | 830.9 / 1597.7 |
| WinSxS | Revised | 800.6 / 1522.9 | 799.2 / 1527.3 | 807.6 / 1544.7 |
| C root | Reviewed | 58.6 / 68.5 | 65.5 / 75.3 | 58.8 / 68.9 |
| C root | Revised | 58.1 / 68.8 | 58.7 / 69.1 | 67.8 / 70.9 |

The reference median first-paint improvement is 5.1%, completion 6.9%. These are
modest whole-application gains, not a demonstrated 5x lookup/scan speedup.
Post-paint Qt commit totals varied and their median increased 1083.8 -> 1272.9
ms; no separate claim of improved commit latency is made. Reference working set
was 808.7 -> 809.4 MiB (not peak). Hidden Qt queries stayed zero on all three
large folders, two at C root. Full path stats remained 202603/4757/24315/21.

Reference loading arrow-to-cursor median-of-run-medians was 135.6 -> 133.9 ms,
maximum 391.2 -> 345.8 ms; arrow-to-paint 181.7 -> 181.5 ms, maximum 571.9 ->
470.6 ms. Settled medians were about 1.0 ms to cursor and 1.7-2.0 ms to paint.
The revised metadata tail still measured 6071.3 ms by median. Loading smoothness
is not established; small-folder/root differences are mainly millisecond noise.

Original no-cache baseline was rerun in three pairs on the reference folder:

| Metric | Before hidden cache | Revised cache |
| --- | ---: | ---: |
| First paint, median | 8949.1 | 5822.7 |
| Completion, median | 17785.6 | 11872.8 |
| Post-paint Qt commits, median | 2765.5 | 1281.8 |
| Qt hidden queries | 607775 | 0 |
| Pair 1 first/complete | 8949.1 / 17785.6 | 5826.1 / 12191.3 |
| Pair 2 first/complete | 8140.6 / 16113.4 | 5774.1 / 11872.8 |
| Pair 3 first/complete | 9409.8 / 18065.4 | 5822.7 / 11832.7 |

Filter-off control, reference folder, reviewed -> revised medians: enumeration
606.9 -> 519.2 ms, first paint 5072.8 -> 4949.8 ms, completion 10584.7 -> 10455.1
ms. All six runs had zero hidden helper calls. First-paint/completion pairs:
reviewed 5043.8/10533.2, 5072.8/10584.7, 5392.9/11541.8; revised
4914.8/10455.1, 4949.8/10447.9, 5098.3/11190.4. One filter-off C-root pair
passed too: 69.5/82.9 -> 70.5/84.6 ms, zero hidden helper calls. Collection cost
still exists with filtering off; this comparison does not remove that overhead.

### Follow-Up Validation And Reproduction

- First focused check after editing: 23 tests in `EntryAttributesCacheTest` and
  `EntryAttributesTest` passed. Added parent-resolution count, warm lookup
  invalidation, directory switching/miss, and barrier-based concurrent-clear
  regressions. Strengthened existing failure and later-entry fallback cases.
- Re-ran the three exact commands in **Tests / Unit and Integration** above:
  combined gate **264 tests, 259 passed, five symlink-privilege skips** (1.462 s);
  **12 status tests passed** (0.514 s); **QuickView source and restart passed**.
  No full suite, freeze, package, new dependency or production model changes.
- All 38 final timing samples had matching ordered row/metadata fingerprints
  within each group, no application exceptions and verified settings isolation.
  Optional `--rows-output` captured rows after all timed phases; a diagnostic
  reference pair compared all 202603 rows directly with zero differences.
- A preliminary **reviewed baseline** sample had a different fingerprint with
  unchanged counts. Its cause remains undetermined because that run lacked row
  capture. Retained it in `pane-rendering-review-followup.json`, excluded the
  entire preliminary batch from reported medians, and repeated with row capture;
  the mismatch did not recur. This is a residual benchmark uncertainty, not a
  claimed fix. Separately fixed a reproducible harness timeout caused by
  `C:/WINDOWS` versus resolved `C:/Windows`; its native System32 retest passed.

Run the existing benchmark from the application environment with
`PANE_BENCHMARK_LARGE_FOLDER` set to the read-only reference folder:

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'fman_integrationtest.pane_rendering_benchmark', os.environ['PANE_BENCHMARK_LARGE_FOLDER'], os.path.join(os.environ['WINDIR'], 'System32'), os.path.join(os.environ['WINDIR'], 'WinSxS'), 'C:/', '--baseline', 'reviewed', '--repeat', '3', '--output', 'target/diagnostics/pane-rendering-review-followup-validated.json'], env=env, timeout=900).returncode)"
```

The retained runs used the same child commands with `--rows-output` for parity
diagnostics. Use only the large folder with `--baseline before` for the original
control, or `--baseline reviewed --show-hidden` for the filter-off control.
Use `C:/ --baseline reviewed --show-hidden --repeat 1` for the root control.
Raw results are in `target/diagnostics/pane-rendering-` files suffixed
`review-followup-validated.json`, `revised-before-after.json`,
`review-filter-off.json` and `review-root-filter-off.json`. All older results and
review records remain historical; no task index or unrelated plan was changed.