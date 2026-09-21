# Pane Rendering 001: Reuse Entry Hidden Attributes

Status: Design only; not approved. Cache publication remains unresolved after review.

## Task

Reduce repeated hidden-file queries before and after first pane display by
collecting ordinary Windows entries' own attributes during `os.scandir()` and
reusing them in Core's hidden-file filter. Keep real, complete `os.stat_result`
objects for all existing metadata and filesystem-operation consumers.

Date-format configuration is a separate task in [DateFormat.md](DateFormat.md).
It is not part of this task's implementation or acceptance gates.

This independent first step follows [ImprovePaneScan.md](ImprovePaneScan.md).
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
   result. Do not publish entries marked `FILE_ATTRIBUTE_REPARSE_POINT`.
   Attribute failure excludes only that entry from the fast path, not the listing.
3. Store eligible attributes under a private key distinct from `stat`, alongside
   the existing provider cache entries. Do not overwrite any full-stat result.
4. Expose one private Core-provider method, provisionally `_pane_hidden_state`,
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
  A cache miss returns `None` inside the provider. Do not catch every
  `AttributeError` around `fs.query`: the same dispatch also invokes the method,
  so an error inside an existing implementation must propagate. The narrow
  missing-method distinction needs a regression test; other errors propagate.

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

Review disposition: the following epoch/subclass proposal is not approved.
Fable recommends reusing the ordinary entry-cache lifetime without this extra
machinery. That is the preferred simplification direction, but late
`cache.put(path, ...)` is not equivalent to the current cached-stat publication:

- `Cache.query` resolves a `CacheItem` before computing. Clearing its path while
  computation runs detaches that item. The old caller may still receive an old
  result, but completing that computation does not overwrite the replacement node.
- `Cache.put` resolves the path when called. A scan that publishes after a clear
  can recreate the node or overwrite attributes from a newer scan.
- A deterministic in-memory probe of the actual Cache confirmed this difference
  for entry, parent-directory and whole-cache clears. It does not establish that
  the existing cache is generally race-free.

Before implementation, choose a smaller publication approach that respects node
invalidation, or explicitly review a weaker guarantee. Do not adopt raw late
`put` on the claim that stat already behaves identically. The lifecycle target
is the existing stat-cache invalidation path, without hidden-only notification
hooks or general cache hardening. Update the proposal and its tests together when
that choice is resolved; this review does not authorize the original machinery.

Original proposal, retained pending that decision:

Use a small provider-local specialization of the existing
[Cache](../src/main/python/fman/impl/fs_cache.py), installed only for the optimized
local provider. Keep inherited `get`, `put`, `query` and ordinary attribute
behavior; add private snapshot operations and intercept `clear`. No shared-cache
rewrite or new long-lived path-to-metadata dictionary.

- Maintain one invalidation epoch and a short-held lock for hidden-attribute
  publication/lookup and `clear`. Capture the epoch before enumeration and store
  immutable `(epoch, attributes)` values under the private key.
- Every `clear`, including entry/subtree/root clear and a clear of a missing path,
  advances the epoch while invalidating through the inherited implementation.
  An invalidation anywhere in this provider conservatively invalidates all hidden
  snapshots and in-flight fills, even when ordinary stat entries elsewhere survive.
  This avoids per-path generation bookkeeping; measure the fallback cost.
- Local `notify_file_added/changed/removed` must invalidate hidden snapshots before
  forwarding the existing event, even without model listeners. Release the lock
  before callbacks. Do not add unrelated stat invalidation; a later existing
  `clear` advancing the epoch again is harmless.
- A guarded publish checks the captured epoch and writes only if still current.
  The check and write share the same lock as `clear`; plain `cache.put` after a
  separate epoch check is unsafe. Once invalidated, an old scan may not acquire
  a new epoch and resume publishing. Overlapping same-epoch scans must not replace
  an already published eligible value; refresh starts a new epoch.
- Lookup accepts only the current epoch. Removed/recreated paths cannot inherit
  a previously valid snapshot after their cache is cleared. Use existing provider
  path conventions, not new case-folding or alias normalization rules.
- Never hold this lock during `scandir`, entry metadata I/O, full-stat computation,
  Qt calls, plug-in callbacks or waits. It must not acquire ordinary cache
  computation locks, preventing lock-order cycles with `cache.query`.

Windows watching remains a stub: unnotified attribute changes can be seen later
than with uncached Qt queries. Refresh/invalidation discards the snapshot; hidden
toggling alone does not promise a new scan. This display-only freshness contract
requires design approval. If live per-pass freshness is required, retain Qt
checks; adding a watcher or polling is outside scope.

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
- **Per-path epochs/shared Cache rewrite:** deferred; a provider-local epoch is
  simpler, at the cost of broader fallback after invalidation.
- **Delayed reveal/smaller batches:** separate scheduling experiments.

## Runtime Effects

- Startup/loading: one directory enumeration, plus attribute extraction per entry;
  existing per-file full stats remain. No promise of Fable's complete LazyStat gain.
- CPU/I/O: eligible filter passes become cache/bit checks instead of repeated
  `QFileInfo` calls. Special entries retain their original Qt work. Entry-stat cost
  can depend on filesystem behavior; verify Windows results rather than assume zero I/O.
- Memory: one small epoch/attribute record per eligible cached entry, with no
  retained handles or second full-stat snapshot. Measure process working-set change.
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
  and scans preserve full stat values and never deadlock. Check broad epoch
  invalidation, same-epoch first publication, path recreation and local
  notifications both with and without subscribed model listeners.
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
- Full-stat compatibility before/after enumeration: `type(result) is os.stat_result`,
  indexing/tuple conversion, errors, device/inode/link count, hard-link `samefile`,
  same/cross-device operation decisions and target-following directory/size/date
  behavior stay unchanged. Use temporary files only for destructive operations.
- [SortedFileSystemModelIT](../src/integrationtest/python/fman_integrationtest/test_qt.py):
  two panes sharing the provider, hidden toggle and refresh, notification-driven
  invalidation, navigation during collection, final row/order parity, and intact
  cursor/selection. Check thread affinity; no new timer/job when filtering is off.
- Existing unimplemented `LazyStat` tests remain outside this task's gates.

Focused commands after implementation, from the application environment:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_local', 'core.tests.commands.test___init__', '-q'], env=build._environment(), timeout=120).returncode)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.impl.test_fs_cache', 'fman_unittest.impl.plugins.test_mother_fs', 'core.tests.test_fileoperations', '-q'], env=build._environment(), timeout=120).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.SortedFileSystemModelIT', '-q'], env=env, timeout=120).returncode)"
```

Run each new failing case before/after its implementation slice, then these
commands. No automatic full suite or clean/freeze/package. Design-only validation
checks documents/links, not application behavior.

### Performance and Manual Checks

- Compare baseline and candidate in alternating order, three fresh-process runs
  each, on small fixtures and the read-only 202,603-entry reference folder. Use
  disposable settings; report OS-cache conditions, counts, medians and ranges.
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