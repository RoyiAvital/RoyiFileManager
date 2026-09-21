# File System and Pane Architecture 001: Columnar Snapshots

Status: Completed with user/main-developer acceptance (2026_09_22).
One snapshot pane serves every bundled provider, with native optimization
focused on NTFS/ReFS.
Breaks the fman 1.7.5 plug-in API by design (user decision, 2026_09_21).

Based on the real-world experience of the user/main developer, the new design
works immensely well and is about an order of magnitude better than the previous
design. This is the user's acceptance assessment, not a claim that every measured
operation is ten times faster.

The user explicitly accepted the implementation and closed its original adoption
gates with documented limitations. Remaining performance and validation work is
tracked in [FSPaneArch002](../Plan/FSPaneArch002.md). Historical review records and
measurements below are preserved; their pending/adoption-blocked statements
describe the state at the time, not the current task status. PoC timings remain
observations, not application guarantees.

## Task

Make browsing large folders fast and, above all, smooth after the first paint:
Filter Bar and Fuzzy Find must respond within a frame, sorting and refresh
within a few hundred milliseconds. Target for the 202,603-entry reference folder
(`CelebAAligned`): first paint in 1–2 s. Simplicity over caching: one obvious
data structure, no per-path cache tree, no incremental diff machinery, few edge
cases, an API a third party can implement in an afternoon.

Proof of concept: [src/misc/pane_arch_poc.py](../src/misc/pane_arch_poc.py),
tests in [test_pane_arch_poc.py](../src/performancetest/python/fman_performancetest/test_pane_arch_poc.py).
Measured on the reference folder, real Windows platform plug-in, warm cache:

| Phase | Today (PaneRendering001 "after") | PoC |
| --- | ---: | ---: |
| Enumeration | 555 ms | 180 ms (scandir + own attributes) |
| Sort by name, natural order, dirs first | part of 4.9 s worker prepare | 153 ms |
| Hide hidden entries | part of the above | 4 ms |
| Model construction + first populated paint | 1.17 s commit + paint | 14 ms + 65 ms |
| **Scan → first paint** | **6.1 s** (plus a 6.5 s metadata tail) | **0.42 s**, no tail |
| Filter Bar keystroke (202k → 142k rows) | ~1 s (three `QFileInfo` passes fixed, still Python row filter + diff) | 4–6 ms filter + 4–6 ms reset/paint |
| Fuzzy keystroke, worst case full scan | 19–103 ms per 75k entries (current matcher) | ≤ 31 ms for 202k, then 0.3–10 ms incremental |
| Sort by size / modified / name descending | seconds (reload of sort values per row) | 79 / 26 / 174 ms |
| Full refresh after a file operation | incremental `RecordFiles` on the Qt thread, seconds for large folders | 334 ms (rescan + sort) |
| Process working set after paint | 807 MiB | 131 MiB (37 MiB baseline) |

Later reviews disproved the original inference that these PoC timings establish
application performance. Adoption depends on the real application checks below.

## Scope

Included: the pane data model (listing, order, visibility, cursor/marks), the
local Windows provider's scan, columns, Filter Bar, Fuzzy Find (in-folder), sort,
refresh after operations, icons, hidden files, and the replacement plug-in API
for these concerns.

Included provider migration: local files, archives, drive/network roots, processes
and the empty startup provider. They share a listing contract, not an enumeration
algorithm. QuickView and optional columns must continue working with resets.

Excluded: rewriting copy/move/delete tasks, adding new remote providers, changing
panels or Command Palette, and Everything integration. Operation-time metadata
and authorization remain independent of display snapshots.

Compatibility: **breaks** the public `fman` plug-in API for file systems, columns
and pane listing access (details under Plug-in API). Commands, key bindings,
settings, `show_quicksearch`, `show_alert`, panels and the `Task` API are unchanged.

## Design

### Implementation Decisions (2026_09_21)

The user authorized implementation with correctness and fewer edge cases ahead
of performance, incorporating all later reviews. These decisions supersede
conflicting exploratory proposals below:

- Use one virtual snapshot model for every bundled provider. The user explicitly
  authorized removing the old design and breaking plug-in APIs; no runtime
  legacy switch, row-model fallback or automatic old-provider adapter remains.
- Use native 128-bit bulk enumeration on supported local NTFS/ReFS volumes.
  Other local paths use a provider-owned scandir scan with unknown identity.
  Archives, drives, network roots and processes implement their own acquisition.
- Keep production filter/fuzzy semantics and Core formatting. Do not substitute
  the PoC regex or unsafe incremental narrowing. Pane projection work stays off
  Qt; the restored Quicksearch dialog retains its existing query callback model.
- Validate immutable tuple columns and packed 128-bit IDs. Reconciliation uses
  directory/volume scope, object ID and creation time, exact name first, then
  IDs unique in both complete snapshots. Ambiguous hardlinks and replacements
  do not inherit marks. Identity remains UI continuity, not operation authority.
- Keep authoritative operation queries and cache invalidation separate from
  display snapshots. Rescans coalesce mutation events and reject stale results.
- Reproduce the pre-change application only in benchmark children, extracted
  from Git commit `56e840a`. This is test instrumentation, not shipped fallback.
  Required adoption gates remain open. No PoC timing is an implementation result.

### Current Ownership and Data Flow

- `fman.listing.Listing` detaches and validates tuple columns, packed 128-bit IDs,
  scope, optional display labels and immutable scalar provider columns. Unknown
  size/time is `None`; missing identity is zero and never inferred from a name.
- `FileSystem.scan(path, check_canceled)` runs off Qt and returns one complete
  listing. Ordinary NTFS/ReFS entries need no child stat. Only symlinks/junctions
  use followed metadata; cloud and other reparse tags are not followed blindly.
  Failed target reads retain the link's own metadata. Native cancellation checks
  occur at each 64 KiB batch and before each followed link.
- `ListingModel` owns the displayed snapshot on Qt. Worker projections supply
  ordered visible indices, row lookup and conservative identity remapping.
  Every revision is checked before commit. Text and icons are bounded lazy caches.
- Per pane: at most two navigation scans, one refresh, one cooperative projection
  worker and a bounded lazy icon lane. Each work lane has at most one latest
  pending request. Stale work is canceled or rejected; blocked native calls can
  outlive cancellation but cannot publish into a newer location.
- Observation covers scan-to-watch handoff. Mutation events coalesce rescans;
  operation caches are invalidated independently. Failed scans do not publish
  partial rows. Navigation error callbacks and tracked requests retain their
  explicit failure/supersession behavior.
- Columns implement `text(listing, index)` on Qt without I/O and
  `keys(listing, ascending)` on a worker. Optional columns update the current
  source. Filters capture plain state through `snapshot_filter()` on Qt.
  Snapshot-only sort columns opt out of external-metadata reprojection; other
  columns retain conservative invalidation. Filters can select batches with
  bounded cancellation, preserving input order and scalar-predicate semantics.
- Production Filter Bar grammar, fuzzy ranking and UTF-16 highlights remain.
  No prefix-only incremental narrowing is assumed. In-folder Find reuses the
  snapshot for indexing but retains the separate Quicksearch dialog, including
  fuzzy/fzf syntax, metadata descriptions and Enter/Escape behavior. Recursive
  and reparse traversal use the same dialog with their existing indexer.
- No persistence format changes. Settings stay under UserSettings; no registry
  writes or dependencies added. Commands and authoritative operation checks
  remain separate from UI identity continuity.

### Isolated Follow-up Experiment (2026_09_21)

The user requested side-code validation before merging two residual optimizations.
[benchmark_snapshot_followup.py](../src/misc/benchmark_snapshot_followup.py) patches
only its own process and verifies unchanged application-source hashes.

- For equal location/scope, names, packed IDs and creation times, return `None`
  instead of an identity dictionary only after proving every ID nonzero. Search
  for zero runs with 16-byte alignment; cross-boundary padding is not an unknown
  identity. Check cancellation between searches. Mixed/unknown IDs retain the
  existing conservative mapping. The view treats `None` as unchanged indices,
  with no lazy per-mark identity work on Qt.
- Windows `LocalFileSystem.watch/unwatch` return before Qt dispatch. Non-Windows
  watcher calls remain Qt-bound; subscription bookkeeping, app events and
  scan-to-watch handoff are unchanged. No new I/O, background work or persistence.
- Rejected alternatives: blindly treating equal unknown IDs as stable, moving
  identity checks into Qt lookups, and skipping application subscriptions.
- Merge gates: differential identity/cancellation cases; existing focused Qt and
  provider tests; preserved all-selected marks/cursor/scroll; faster preparation
  without a Qt-commit regression; Windows no-dispatch and non-Windows Qt-affinity
  regressions after merge. No full measurement-catalog or adoption claim.

### Superseded First Proposal

The remainder of the original Design section is retained as historical review
context. In particular, name-based identity, Qt-thread matching, automatic legacy
adapters, inferred performance bounds and incremental narrowing are not adopted.

### One idea

A pane shows an **immutable columnar snapshot** of one directory, plus two index
arrays. Everything the UI does is index arithmetic on those arrays.

```python
@dataclass(frozen=True, slots=True)
class Listing:            # produced once per scan, never mutated
    path: str
    names: list[str]
    is_dir: list[bool]
    sizes: list[int]      # 0 for directories
    mtimes_ns: list[int]
    attributes: list[int] # Windows own attributes; 0 elsewhere
    lower_names: list[str]

class PaneState:          # owned by the pane, Qt thread only
    listing: Listing
    order: list[int]      # all entries, sorted for the current column/direction
    visible: list[int]    # order minus hidden filter minus Filter Bar / Fuzzy
    cursor: int | None    # entry index, not a row number
    marks: set[int]       # entry indices
```

- Rows are computed on demand: `data(row, column)` = `column.text(listing,
  visible[row])`. No `File`, `Cell`, `Row` objects; no per-cell strings for
  200k entries; the model is `QAbstractTableModel` with `rowCount = len(visible)`.
- Sorting produces a new `order` (`sorted(range(n), key=...)`, 25–175 ms at 202k).
- Filtering produces a new `visible` from `order` (or from the previous `visible`
  when the query only got longer: incremental narrowing).
- Any change of `visible` is one `beginResetModel/endResetModel`; the cursor and
  marks survive because they are entry indices, not rows: `row = visible.index(cursor)`
  (or a `dict` built on demand when `len(visible)` is large).
- A new scan replaces the whole `PaneState`; cursor and marks are carried over by
  **name** (`names.index(old_name)`, or a name→index dict for the 200k case).

There is no metadata cache: the snapshot *is* the cache, its lifetime is "until
the next scan", and its invalidation rule is "replace it". `os.scandir` on Windows
delivers size, mtime and attributes with the enumeration (0.7 µs/entry), so a
rescan of the reference folder costs 180 ms and a full refresh 334 ms; for ordinary
folders both are sub-millisecond. That is the price paid for removing
`fs_cache.Cache` (132 MiB and 1.65 s for 202k nodes today), `CachedIterator`,
`RecordFiles`, `ComputeDiff` and the per-row stat.

### Data flow

```mermaid
flowchart LR
    Nav[navigate / refresh / after operation] --> W[worker thread\nprovider.scan(path) -> Listing\nsort_order(listing) -> order]
    W -->|"generation ok"| Q[Qt thread\nPaneState = listing, order, visible\nendResetModel, restore cursor/marks by name]
    K[Filter Bar / Fuzzy keystroke] --> F[Qt thread\nvisible = narrow(previous or order)\nendResetModel, cursor by entry]
    S[sort column click] --> W2[worker or Qt thread\norder = sort_order(listing, column)] --> Q
    P[paint] --> D["data(row, col) = column.text(listing, visible[row])\nicon = per-suffix cache"]
```

- **Worker**: scan + sort for navigation, refresh and sort-column changes. One
  worker per pane, one job at a time, generation counter; a stale result is
  dropped. The worker returns only the immutable `Listing` and a plain `list`.
- **Qt thread**: everything that touches `PaneState`, the model and the view.
  Filter and fuzzy run here because their worst case at 202k entries is 6 ms
  (substring) and 31 ms (fuzzy); typing narrows incrementally after that. If a
  future folder class exceeds ~50 ms, move `narrow` to the worker with the same
  generation rule; no other change.
- **File operations**: the `Task`s run as today. When a task finishes (or every
  ~200 ms while a long task runs), the pane whose `listing.path` is the affected
  directory schedules a rescan. No incremental insert/remove/update paths, no
  file-watcher-driven per-file diffs. The cost is one scan+sort per affected
  directory per batch; the benefit is that "what the pane shows" has one source
  of truth. On Windows the watcher is a stub today anyway.
- **Hidden files**: `visible` excludes entries with `FILE_ATTRIBUTE_HIDDEN` unless
  the pane shows hidden files; on other platforms the provider fills `attributes`
  with `HIDDEN` for dot-names. Roots never appear as entries, links carry their own
  attributes: `QFileInfo` parity by construction (probed 2026_09_21).
- **Icons**: one `QIcon` per suffix, requested lazily at paint; `.exe`, `.lnk`,
  `.ico`, `.url` per file (they carry their own icon). Folders share one icon.
  202k JPEGs need one shell call, not 202k; this is where most of the 807 MiB went.
- **Links**: `scan` performs one followed stat for reparse points only (so a link
  to a directory sorts and opens as a directory, as today); everything else uses
  the enumeration data unchanged.
- **Failure**: a scan that fails to open the directory raises and the pane keeps
  its previous state with the existing error dialog; an entry that vanishes
  between enumeration and stat is skipped; a failed followed stat on a link shows
  it as a file with zero size.

### Columns

A column is two pure functions over a listing and no state:

```python
class Column:
    name = 'Size'
    def text(self, listing, i) -> str: ...        # called for visible rows only
    def keys(self, listing) -> Sequence:  ...     # one key per entry, used by sort
```

`Name.keys` returns natural-sort keys (`re.split(r'(\d+)')` with `int` parts,
101 ms at 202k); `Size.keys` returns `listing.sizes`; `Modified.keys` returns
`listing.mtimes_ns`. Directories-first is applied by the pane, not by columns.
Formatting (dates, sizes) happens only for the ~50 painted rows, so ISO dates or
any other format cost nothing.

### Filter Bar and Fuzzy Find

Both are `narrow(candidates: list[int], query) -> list[int]` over
`listing.lower_names`:

- Filter Bar keeps today's grammar (`*`, `^`, `$`, `!`) compiled to regexes by the
  existing `filter_pattern.compile_filter`; the fast path for a plain literal is
  `query in lower_names[i]`.
- Fuzzy Find compiles the query to `a.*?b.*?c` and ranks matches by `(span, start)`;
  highlighting reuses the match object's span for the ~100 displayed rows only.
- Incremental rule: if the new query extends the previous one in the same mode,
  narrow the previous result; otherwise narrow `order`. That is the whole cache.

The earlier proposal to make in-folder Fuzzy Find a pane mode is superseded:
`Ctrl+F` retains the separate Quicksearch UI, with snapshot-backed indexing when
available. The Filter Bar remains substring/glob matching, not fuzzy search.
The recursive variant (`Ctrl+Shift+F`) retains its own indexer and Quicksearch UI.

### Plug-in API (breaking)

| Today | New | Why |
| --- | --- | --- |
| `FileSystem.iterdir(path) -> names`, `stat/is_dir/size_bytes/modified_datetime(path)` per entry, `@cached` | `FileSystem.scan(path) -> Listing` (required); the per-path query methods remain for operations only and are no longer called during listing | One call, one object, no cache to invalidate |
| `Column.get_str(url)`, `Column.get_sort_value(url, ascending)` | `Column.text(listing, i)`, `Column.keys(listing)` | Vectorised, no per-row URL/query round trips |
| `pane.get_file_under_cursor()`, `get_selected_files()` return URLs | Unchanged signatures, implemented as `listing.names[cursor]` joined to `listing.path` | Same for commands |
| `DirectoryPaneListener.before_location_change` etc. | Unchanged | — |
| `fs.query(url, 'stat')` during display | Not called by the pane; still available to commands | Display never stats |
| Third-party `FileSystem` without `scan` | Adapter: `scan` built from `iterdir` + per-entry `is_dir/size_bytes/modified_datetime` (slow path, correct) | Keeps old providers working, just not fast |

The adapter is the migration path: shipped providers (`zip://`, `7z://`,
`tar://`, `drives://`, `network://`, `process://`) either implement `scan`
natively (trivial for archives, whose index already is columnar) or run through
the adapter until they do.

## Alternatives

- **Keep the incremental model and optimise it** (PaneRendering001 route):
  measured ceiling ≈ 6 s first paint and a 6.5 s tail on the reference folder;
  the per-row objects and the Qt-thread `RecordFiles` diff remain. Rejected as
  the primary direction; its hidden-attribute step is compatible with this design.
- **Keep `fs_cache.Cache` and seed it from scandir (LazyStat)**: removes the
  stat syscalls but keeps 202k cache nodes, the row objects and every invalidation
  rule. Rejected for "no cache heavy" — the snapshot makes the cache redundant.
- **Compiled extension / RapidFuzz / SQLite index**: not introduced. Existing
  semantics and dependencies take priority; measured GIL stalls remain an open
  performance concern, not proof that pure Python meets every target.
- **Everything as the listing backend**: measured elsewhere (Find Files 003);
  not applicable to arbitrary paths, archives or shares.
- **Chunked/progressive first paint**: not needed at 0.42 s; revisit only if a
  folder class exceeds ~2 s (network shares are the candidate; there the scan is
  the floor for any design).
- **Per-file icons as today**: 202k shell icons and QIcon objects; the dominant
  memory cost. Per-suffix cache with a per-file exception list is what Explorer
  effectively does.

## Runtime Effects

- Startup creates an empty model; real navigation performs provider I/O and a
  worker projection before populated paint. No per-row metadata loading tail.
- Idle panes do not scan or match. Directory change subscriptions remain active;
  Windows uses the existing stub watcher. Optional status/preview work remains
  opt-in. Lazy icons use bounded queues and caches.
- Refresh temporarily holds old/new snapshots and reconciliation maps. Full-set
  fuzzy indexing adds normalized candidates; measure peak, not just settled RSS.
- Cancellation checkpoints exist between native batches, provider records and
  projection phases. Python sorting and blocked OS calls are not interruptible;
  generations prevent stale publication but do not establish a latency bound.
- No new processes in ordinary local navigation. Archive providers retain their
  existing 7-Zip process lifecycle. Benchmarks use isolated child processes.
- Disabled path: not applicable to the pane replacement itself. No compatibility
  engine runs in parallel; disabled optional features must do no feature work.

## Tests

Implemented now (PoC, 8 tests, `fman_unittest.test_pane_arch_poc`):
scan columns and non-following attributes; directories first and natural order
ascending/descending, size order; Windows hidden attribute from the entry;
substring filter case-insensitivity and incremental ≡ full; fuzzy ranking and
incremental ≡ full with mode switch; virtual model `data()` for name/size/date,
`set_visible` reset and cursor-by-entry survival; a 100k synthetic timing budget
(printed: sort 69 ms, substring 1.6 ms, fuzzy 9.7 ms).

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_pane_arch_poc', '-v'], env=env, timeout=120).returncode)"
python src/misc/pane_arch_poc.py "<large folder>" --platform windows
```

Required before adoption:

- Unit: transitions preserve cursor and marks by verified identity, reject
  replacements/ambiguous renames, and validate each provider's immutable scan;
  every shipped column's `text`/`keys` equals prior formatting and sort order
  on a fixture folder (golden comparison of the full row order).
- Qt integration: Filter Bar and Fuzzy Find on a 200k synthetic listing keep
  arrow-to-paint under 16 ms; file operation → rescan → cursor/marks intact; two
  panes on the same folder; navigation away during a scan drops the stale result.
- Regression: the existing command tests (`core.tests.commands.test___init__`)
  run against the new pane with the unchanged command API.
- Performance: the PoC table above re-measured through the real application on
  the reference folder, System32 and WinSxS, fresh process, three runs each.

## Implementation Steps

1. Freeze golden fixtures from the current application: full row order and
   column texts for a fixture folder in each sort mode, with and without hidden
   files. These make every later step verifiable.
2. Add validated `Listing` and provider-owned scans; verify native NTFS/ReFS
  identity, link semantics and unknown-identity acquisition separately.
3. Add `PaneState` and the virtual `ListingModel`; port the three built-in
  columns to `text`/`keys`. Wire it into `DirectoryPaneWidget` without a legacy
  switch; isolate historical comparisons outside the production path.
4. Port the Filter Bar to `narrow`; then the in-folder Fuzzy Find. Golden tests
   for both grammars.
5. Route file-operation completion and refresh to "rescan the affected pane";
   remove `RecordFiles`, `ComputeDiff`, `CachedIterator` and the `stat` cache
   from the listing path (operations may keep `fs.query` for their own checks).
6. Icons per suffix; hidden files from attributes; drop `QFileInfo.isHidden`.
7. Port shipped providers to native `scan` (archives first), delete the switch
   and the old model, update `PlugIn.md`, README, CHANGELOG with the API break
   and migration notes.

## Acceptance Criteria

### Closure Decision (2026_09_22)

- The user/main developer accepts the implemented architecture based on real-world
  use and the recorded correctness and performance evidence.
- The original 16 ms loaded-input p95 and 250 MiB peak-memory targets, together
  with unrun adoption checks, are no longer completion blockers for this task.
  They were not retroactively passed. Remaining investigations are captured in
  [FSPaneArch002](../Plan/FSPaneArch002.md).
- Existing provider, identity, selection, query-semantics and plug-in migration
  requirements are retained; acceptance does not waive known correctness defects.
  No new application changes or broad validation run are implied by this closure.

### Original Targets (Historical)

- Reference folder: first paint ≤ 2 s in the application (PoC: 0.42 s), no
  post-paint metadata tail, Filter Bar and Fuzzy Find keystrokes ≤ 16 ms
  arrow-to-paint at the 95th percentile, sort switch ≤ 300 ms.
- Working set for the reference folder ≤ 250 MiB (PoC: 131 MiB).
- Golden row order and column texts identical to today for the fixture folder
  in every sort mode, hidden on/off; junction and drive-root visibility identical
  to `QFileInfo`.
- Cursor and marks survive filter, sort, refresh and file operations by identity.
- No per-entry display cache tree or metadata loading tail; bounded work lanes,
  event-driven invalidation and no idle polling. Authoritative operation caches
  remain, as required by the later safety review.
- The `FileSystem`/`Column` migration contract fits on one page of `PlugIn.md`;
  all bundled providers implement it. Old plug-ins must migrate explicitly.

## Review Findings

### 2026_09_21 - Adoption Gates

The snapshot direction remains viable, but the current proposal is not ready for
adoption. The PoC is a performance experiment, not a compatibility implementation.

1. **P1: Incremental filtering needs a semantic subset rule.** Extending the raw
  query does not imply a narrower result with today's grammar. For names `a`,
  `ab`, `b`, changing `!a` to `!ab` must reintroduce `a`; completing `[ab` to
  `[ab]` can also broaden results. Restrict previous-result reuse to proven
  monotone transitions; otherwise start from the complete current base order.
  Required tests: incremental equals full evaluation after every prefix, edit,
  backspace, operator/escape/class completion, mode switch, hidden toggle,
  sort and listing replacement. Include negation, anchors and fuzzy OR terms.
  The plain-literal fast path also needs Unicode parity with the current parser,
  whose `re.IGNORECASE` behavior is not identical to `casefold` containment.
  Confirmed examples: `ss` against `stra\u00dfe` changes false to true;
  `i` against `\u0131` changes true to false.

  The proposed fuzzy matcher also drops existing exact/prefix/suffix/negation,
  AND/OR, normalization, ranking and UTF-16 highlight semantics. Actual matcher
  comparisons for `!alpha`, `^alpha`, `'beta` and `alpha | beta` returned matches
  that the PoC missed. Reuse the existing
  [matcher contract/tests](../src/unittest/python/fman_unittest/test_search_file_fuzzy.py)
  or explicitly approve the user-visible changes. Define pane-mode Enter/Escape,
  prior filter/cursor restoration, `include_hidden` (currently independent of
  pane visibility), regular mode, metadata settings and result limits. Never
  incrementally narrow a truncated top-N result set.

2. **P1: The fuzzy regex has unbounded practical UI latency.** A read-only probe
  of the actual PoC exceeded a two-second subprocess timeout for one candidate
  named `'a' * 64` and query `'a' * 16 + 'b'`. Non-greedy `.*?` still backtracks;
  the measured numeric filenames do not establish a worst-case bound. Use a
  bounded matcher with the agreed grammar/ranking, and keep expensive ranking
  off Qt. Moving this exact regex to a Python worker alone does not establish
  responsiveness because matching can hold the GIL. Required tests: repeated
  characters, long near-misses, maximum supported query/name lengths, broad
  matches and empty queries, measured by externally posted input and a timeout.
  The eight current tests pass, but their 100k timing ceilings are 500 ms for
  substring and 1000 ms for fuzzy, not the proposed 16 ms application gate.

3. **P1: Names are not refresh identity, and resets do not preserve Qt state.**
  A rename loses name-based cursor/marks; deleting and recreating the same name
  can transfer them to a different object. Names shared by unrelated directories
  must not inherit selection on navigation. Define provider entry keys separately
  from display names, rename remapping and replacement policy. Do not assume
  Windows `DirEntry.stat` supplies usable device/inode identity. If path identity
  is deliberately retained instead of object identity, qualify the acceptance
  criterion and command-safety implications explicitly.

  Specify whether invisible marks remain actionable: today's
  [view](../src/main/python/fman/impl/view/__init__.py) derives command selection
  from visible Qt selection. Retaining hidden entry indices must not silently
  change delete/copy targets. Test actual `QItemSelectionModel` state, range
  anchors, select-all, cursor fallback after deletion/empty results, scroll
  position, rename editor and drag/drop during resets, plus identity remapping
  after each operation. The PoC cursor test checks only `row_of`, not a view.
  Bound remapping to O(N + marked entries), not repeated `names.index` scans.

4. **P1: Asynchronous rescans break the stated unchanged-command contract.**
  [NewEmptyFile and _Rename](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)
  call `place_cursor_at` immediately after a mutation; a rescan scheduled later
  leaves the destination absent and cursor placement is swallowed as `ValueError`.
  New file creation is not itself a `Task`, so task-completion hooks alone miss
  it. Define a generation-bound commit acknowledgment or pending cursor target,
  and subscribe to mutation notifications from all providers/plug-ins, not only
  built-in task completion. Cover both source and destination parents, both panes,
  recursive operations, ancestor removal, partial failure and cancellation after
  some successful mutations. Retained per-path operation caches must still be
  invalidated: replacing a display snapshot does not clear `@cached stat`.

  Define coalescing and a guaranteed final refresh when events arrive faster
  than scan time. Repeated 200 ms invalidation of a 334 ms scan can starve commits
  or accumulate jobs. Resolve the periodic-update/no-timer contradiction using
  operation-driven progress or a scoped, explicitly justified timer. Test event
  bursts, dirty-during-scan, no changes, two simultaneous operations and zero idle
  work. Preserve current navigation completion/error callbacks exactly once.

5. **P1: Cancellation and publication need a complete job protocol.**
  `provider.scan(path) -> Listing` exposes no cancellation token/callback, so the
  coordinator cannot check a generation between entries inside an arbitrary
  provider. A blocked UNC enumeration or followed reparse stat can occupy the
  sole worker indefinitely; result rejection does not let that worker start a
  new local navigation. Define cancellation inside scanning and sorting, bounded
  pending work, blocked-I/O policy and shutdown behavior without claiming a
  millisecond bound for native I/O. Do not spawn unbounded replacement workers.

  Specify listing revision versus requested navigation/sort/filter revision.
  Validate results on the Qt thread at publication, use order indices only with
  their originating snapshot, and restore the latest cursor/marks, not a capture
  taken before the job. Barrier tests must cover sort-during-refresh, typing and
  hidden toggles during scans, queued old completion after navigation, A/B/A
  navigation, an event during a pending commit, and pane/window destruction.
  Distinguish requested and displayed locations so commands never combine old
  rows with a new address. Define iterator-midstream failure, inaccessible root,
  deleted current/ancestor directory and empty-success behavior separately.

6. **P1: The fixed Listing/Column schema cannot satisfy the legacy adapter claim.**
  [Process Pane](../src/main/resources/base/Plugins/ProcessPane/process_pane/__init__.py)
  already has opaque identity-bearing entry paths, distinct display names and a
  PID column, but no `size_bytes` or `modified_datetime`. An unconditional adapter
  that calls those methods fails; filling zero invents metadata. Drives/network
  providers have similar capability differences. Define URL/path conventions,
  separate entry keys/display names, optional/unknown fields, extension columns
  and per-entry error behavior. Keep display metadata separate from authoritative
  full stat used by operations. A `FileSystem` adapter alone does not adapt old
  columns or listeners; specify supported legacy surfaces and deliberate breaks.

  `frozen=True` does not freeze the lists: mutating `listing.names[0]` succeeded
  in the actual PoC. Choose immutable storage or an enforceable ownership-transfer
  contract without retained writable aliases. Validate column lengths, unique
  entry keys, index ranges, supported key types and missing timestamps before
  publication. Require minimal Name-only, Process/PID, archive, drive/network
  and custom-column providers, malformed responses, provider unload, and mutation
  attempts in the adapter/contract tests.

7. **P2: Sort/format goldens and dynamic-column behavior are not preserved yet.**
  Direct comparison with [Core columns](../src/main/resources/base/Plugins/Core/core/__init__.py)
  confirmed reversed ordering for `file999999`/`file1000000`, descending Size
  ordering of directories (`alpha,Zeta` versus `Zeta,alpha`), and `1.5 KiB` versus
  the PoC's `1.5 KB`. Modified also uses a different format in the PoC. Some changes
  may be desirable, but need explicit acceptance instead of identical-output
  claims. Test equal-key stability in both directions, leading zeros, large digit
  groups, case/Unicode, unknown/invalid dates, time-zone/DST boundaries, large
  sizes and configurable formatting. Preserve or deliberately revise directional
  sort-key behavior in the new `Column.keys` API.

  The existing Size column reads progressive directory totals; a stateless
  function of an enumeration-only snapshot has no path for these updates.
  Specify dynamic metadata revisions and optional-column lifecycle without
  rescanning a directory for every total. Add directory-size toggle/result/stale
  result/sort tests and status-bar off/on tests against the real replacement model.

8. **P1: Paint-time shell icon lookup reintroduces unbounded Qt-thread I/O.**
  PoC `ListingModel.icon` calls `QFileIconProvider.icon(QFileInfo(path))` directly
  from `data`. One uncached shortcut, executable or network icon can block a
  paint regardless of the suffix-cache hit rate on JPEGs. Establish a nonblocking
  icon contract, immediate fallback, bounded request/cache lifetime and safe Qt
  object ownership. If this needs an additional service, amend the one-worker
  constraint; do not hide it in `data`. Decide explicitly whether custom folder
  icons, link/cloud overlays and extensionless executables can lose distinct icons.
  Test mixed suffixes, slow/failing handlers, association/DPI changes, navigation
  while icons are pending and cache memory after many folders. The small suffix
  exception list is not a demonstrated universal Windows shell-icon rule.

9. **P2: Reset-heavy integration and the benchmark need stronger evidence.**
  Existing [QuickView](../src/main/python/fman/impl/quick_view.py) clears its image
  on `modelAboutToBeReset` and schedules a reload after reset. Resetting on every
  keystroke/rescan can therefore clear and decode an unchanged cursor image.
  QuickView need not be redesigned, but its model-event contract cannot be
  excluded from compatibility tests. Also cover status counts, filter counts,
  navigation history, external-editor return/reload, column widths, focus and
  command/context-menu/drag-drop dispatch with the actual replacement view.

  PoC `PaintWatch` timestamps the paint event *before* its handler, while filter
  timing calls a helper directly, not a real key through application dispatch.
  Empty results skip the paint wait; refresh timing omits the completed paint.
  The 31 ms sample already exceeds a 16 ms budget before reset/paint. Re-measure
  post-handler first paint and externally posted key-to-cursor/key-to-paint,
  including p95/max, held-key backlog, select-all/marked-state restoration and
  peak old+new snapshot memory. Use both panes, mixed/long Unicode names and
  expensive columns/icons, not just numeric JPEG names. Treat speedup and memory
  attribution as provisional until isolated real-application A/B measurements;
  one existing implementation's timing is not an architectural ceiling.

### Required Test Matrix

These supplement, rather than replace, the Tests and Acceptance Criteria above:

| Area | Required discriminating coverage |
| --- | --- |
| Query correctness | Existing Filter Bar and Fuzzy Find goldens; incremental/full equality for all editing transitions; Unicode normalization and UTF-16 highlights; independent hidden-search setting; untruncated candidates. |
| Input latency | Bounded adversarial fuzzy cases; actual key-to-cursor/completed-paint p95 and maximum during filtering, sorting, refresh and icon misses; empty and very broad results. |
| Identity/selection | Real Qt cursor/marks and chosen command URLs across sort/filter/refresh, rename, case-only rename, delete/recreate, same names in different folders, hardlinks and aliases; 200k select-all; editing and drag/drop. |
| Worker lifecycle | Event-barrier stale-result cases in finding 5; slow/blocked provider, close during scan, iteration failure, latest-only queue, bounded memory and exactly-once completion; no Qt access by worker. |
| Operations | Native temporary create/edit-new/mkdir/rename/copy/move/delete, same/cross-provider transfers, partial failure/cancel, both affected panes, ancestor removal and fresh full-stat operation checks. |
| Local paths | Read-only `C:` and `C:/` plus a non-system drive; child/root Qt visibility parity; UNC/share roots, drive-relative/noncanonical paths, long/Unicode paths, unplugged drives and permission changes. |
| Special entries | Visible/hidden/broken/looping symlinks and junctions, reparse target errors, offline/cloud placeholders, sparse/compressed files, system-only/dot-prefixed names; own attributes versus followed metadata; disappearance during scan. |
| Provider contract | Name-only legacy provider, Process/PID, drives/network, native/adapter archive including virtual directories, custom columns, nullable/unsupported metadata, malformed immutable snapshots and plug-in reload/unload. |
| Application integration | Enabled/disabled QuickView, status and directory totals; existing filter/fuzzy command modes and preferences; model reset signal order, persistent-index invalidation, view editing, selection, focus and navigation callbacks. |
| Performance | Reference folder, System32, WinSxS and C root; three alternating fresh-process A/B pairs with isolated settings and retained raw results; hidden on/off, optional features off/on, warm-cache limits, mixed names and slow-backend fixtures. |

The current command unit tests are not sufficient unchanged-pane evidence: many
use mocks. Native workflow tests must exercise the real replacement pane and
command dispatch. Live UNC/cloud and symlink privilege gaps must be recorded,
not silently counted as covered by ordinary local fixtures.

### Review Validation

Executed on 2026-09-21 with the existing application interpreter (Python 3.14.7):

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_pane_arch_poc', '-v'], env=env, timeout=120).returncode)"
python src/misc/pane_arch_poc.py C:/ --platform windows
```

- Eight PoC tests passed in 0.141 s. Synthetic 100k sample: sort 66 ms,
  substring 1.6 ms and fuzzy 10.1 ms. These are not real-application latency gates.
- Read-only native C-root smoke completed: 19 entries, nine visible, reported
  scan-to-paint-event 87.3 ms and 66.5 MiB working set. This checks execution,
  not automated Qt visibility parity or root operation safety.
- Read-only probes confirmed the filtering/Unicode, fuzzy grammar, column-order/
  text and shallow-immutability counterexamples listed above. The adversarial
  fuzzy child was terminated by a two-second `subprocess.run` timeout; no process
  was left running. Reproduce that case with PoC `fuzzy`, a one-entry Listing
  named `'a' * 64`, candidates `[0]`, and query `'a' * 16 + 'b'` in a bounded child.
- No PoC/runtime/test code was modified, no new packages or environments, and no
  full suite or packaging. The large-folder timing table was not independently
  rerun during this review. Documentation links/whitespace and preservation of
  the original reviewer record were checked.

## Proposed Resolutions

These are recommendations for the next design revision, not implementation
approval. Preserve the columnar snapshot and virtual model; do not restore
per-entry stat/cache nodes to solve identity.

### Separate Row and Object Identity

- Within a snapshot, keep the existing integer entry index. Sorting/filtering
  only changes index arrays and requires no filesystem identity lookup.
- Across snapshots, retain an entry's exact provider key/name separately from an
  optional object ID. On Windows the object ID is the provider/volume scope plus
  the filesystem's 128-bit file ID. A pathname alone is not object identity.
  Provider scope includes the mount/connection instance, not just a drive letter.
  Reconcile only within the same directory/navigation context. Do not casefold
  entry keys: display normalization is not identity normalization.
- A file ID alone is not a row key either: two hard links have the same ID but
  are distinct directory entries. Match exact name plus object ID first; use
  successful operation rename mappings next. Only follow an unmatched ID across
  an external rename when it occurs exactly once in each complete snapshot, not
  merely once among unmatched entries. Keep hardlink rows distinct; ambiguous
  groups require exact name/ID matches or a verified operation mapping. Drop
  marks on a known replacement. Cursor fallback may remain at a visible name or
  nearby row without restoring old marks; subsequent commands capture that newly
  visible target normally. Only visible marks feed the command-selection API.
- Candidate Windows backend: one directory handle and batched
  `GetFileInformationByHandleEx(FileIdExtdDirectoryInfo)` enumeration, returning
  names, metadata, reparse tags and file IDs together; `FileIdInfo` supplies the
  directory's volume scope. IDs describe entries themselves, not followed link
  targets. This needs capability detection and measured parity/performance before
  adoption; unsupported providers retain an explicit unknown-identity mode.
- This is short-lived UI reconciliation, not an authorization or race-free
  operation guarantee. IDs can be reused after deletion. File operations must
  still validate captured targets at execution; a true no-replacement guarantee
  requires operation/handle-level support, outside a listing-only change.

Keep native IDs in an immutable packed byte column, with one scope per listing.
Use transient O(N) reconciliation maps in the worker, not permanent per-file
cache objects. An old-index/new-index mapping lets Qt remap the latest selection
at commit. Do not keep a handle per listed file. Full-stat/operation checks remain
separate, and checking a path then acting on it is not an atomic safety guarantee.

### Identity Probe Results

On 2026-09-21, in-memory `ctypes` probes used the existing Python 3.14.7 environment:
one directory handle, one `FileIdInfo` query, and 64 KiB
`FileIdExtdDirectoryRestartInfo`/`FileIdExtdDirectoryInfo` batches until
`ERROR_NO_MORE_FILES`, with bounded UTF-16 record parsing and handle cleanup.
The candidate built immutable tuple columns plus packed IDs; both versions used
the unchanged PoC sort/hidden filter. Ordinary entries needed no child opens or
path stats. Reparse target metadata used explicit `os.stat(path)`.

Three alternating pairs per folder, warm cache, one process, garbage collection
outside timing. All columns matched by exact name on the three large folders.
These are scan/sort/filter measurements, not application first-paint timings:

| Folder | Entries | PoC median [min-max], ms | With IDs median [min-max], ms |
| --- | --- | --- | --- |
| CelebAAligned | 202603 | 330.65 [328.80-335.17] | 365.47 [362.93-366.74] |
| System32 | 4757 | 7.13 [6.98-7.40] | 8.51 [8.29-8.64] |
| WinSxS | 24315 | 115.38 [115.22-115.63] | 96.93 [95.36-97.51] |

Per-pair values before -> after (ms): CelebAAligned 335.17 -> 365.47,
330.65 -> 366.74, 328.80 -> 362.93; System32 6.98 -> 8.64, 7.13 -> 8.29,
7.40 -> 8.51; WinSxS 115.63 -> 97.51, 115.38 -> 96.93, 115.22 -> 95.36.
At 202603 entries, packed IDs used 3.091 MiB and 347 data batches. Median scan
alone was 176.67 -> 223.98 ms; scan/sort/filter overhead was 34.82 ms. Payload is
not peak memory: old/new snapshots, temporary maps and tuple conversion still
need application-level measurement.

Temporary fixtures passed rename identity, shared hardlink identity and
delete/recreate with a different ID while another hardlink retained the old
object. The ID matched full `os.stat().st_ino` on this NTFS fixture. This does not
prove absence of ID reuse after final deletion; inject reuse in unit tests.
Read-only C-root enumeration returned 19 entries with nonzero IDs in one batch.
The full-column root comparison stopped on a junction timestamp difference:
PoC `DirEntry.stat()` returned the entry's own mtime for `Documents and Settings`,
while explicit `os.stat(path)` and current Core returned the target mtime. The
candidate matched Core for that field. No three-pair root timing is claimed.

No runtime/PoC code changed. The native probe is not a retained backend or
benchmark implementation; add it as an explicit PoC mode with parser/identity
regressions before treating these exploratory results as adoption evidence.

### Storage Capabilities

The pane must require an opaque **entry key**, not a universal Windows file ID.
Each provider returns display names separately, nullable metadata, an optional
opaque object ID, its identity scope/lifetime, and operation capabilities.
The packed 128-bit column is a Windows optimization, not the generic provider
format. A provider may return strings or no reliable object identity at all.

| Storage | Enumeration and identity policy | Limits / required behavior |
| --- | --- | --- |
| USB mass-storage disk with NTFS | Same filesystem provider and capability-tested bulk-ID path as a local disk. Scope IDs to the volume/mount instance. | USB transport is not an identity scheme. Unplug/replug, drive-letter reuse and a different volume invalidate continuity. |
| USB FAT/exFAT or unsupported filesystem | Ordinary enumeration remains supported; enable native IDs only with a verified stability contract. Otherwise identity is unknown beyond the snapshot. | FAT IDs can change on rename; do not assume NTFS behavior for exFAT or an arbitrary driver. Keep fast listing without a per-file-stat fallback. |
| MTP phone/camera | Separate Windows Portable Devices provider. Entry keys use current WPD object IDs; persistent IDs can support reconciliation when reliably supplied/resolved, scoped to device/storage. | Object IDs can change across connection sessions. MTP is not an `os.scandir` filesystem and no bundled MTP provider exists today; browsing and transfers need a separate implementation. Missing dates/sizes remain unknown. |
| Local cloud-sync folder | Filesystem provider can enumerate placeholder names/metadata and local entry IDs, with cloud/reparse-aware handling. | Inspect reparse tags; do not follow every reparse point or fetch content/icons/thumbnails merely to list it. Directory enumeration may still request remote metadata. Hydration/eviction/resync can change local identity; do not equate it with a remote cloud object ID. |
| SMB/UNC or mapped network drive | Use the provider's supported bulk enumeration; accept IDs only within the verified server/share/connection scope. Fall back to ordinary listing if unsupported. | Reconnect, failover, disconnect, permissions and unsupported ID classes need explicit behavior. A mapped drive letter does not imply a local NTFS backend. |
| WebDAV/SFTP/remote-only cloud | Provider-specific listing and opaque IDs if available; same snapshot consumer. | Not automatically supported by the Win32 backend. Provider implementation, authentication, transfer and cancellation semantics are separate work. |

Without reliable identity, sorting/filtering within a snapshot still preserve
cursor/marks by index. On a new scan, cursor may fall back by entry key/name, but
unverified marks should be cleared rather than transferred to possibly replaced
objects. A weaker path-based preservation policy must be an explicit decision,
not a silent claim of object identity. Known successful operation mappings can
restore deliberate cursor placement after a committed rescan.

Reconnection invalidates old session-scoped keys and pending results. Commands
must not apply an old selection to a newly mounted device/share simply because
the path is identical. Validate scope and target at execution. IDs are not
globally unique forever; even reliable filesystem IDs may be reused after deletion.

The performance promise is **cheap in-memory interaction**, not local-SSD scan
latency on every medium. Keep all provider I/O off Qt and batch metadata requests
where supported. A slow MTP/SMB/cloud directory may take seconds to enumerate;
keep the current snapshot responsive while loading. A blocked native call needs
a proven cancellation/isolation policy, not merely a stale-generation check.
If early partial display is required for those backends, design explicit bounded
partial snapshots; do not quietly reintroduce per-cell metadata loading/diffs.

Required device/provider tests: USB unplug during scan/operation and replug with
the same letter; FAT/exFAT rename/replacement; MTP lock/disconnect/reconnect and
persistent-ID resolution failure; cloud online-only enumeration without content
hydration, offline failures, eviction and replacement; SMB latency, disconnect,
failover and ID capability failure. Verify no stale marks or command targets,
bounded queues/cleanup, nullable metadata and no Qt-thread I/O. None of these
live removable/MTP/cloud/network scenarios has been validated in this session.

Platform references checked: [bulk directory IDs](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_extd_dir_info),
[filesystem ID lifetime](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-by_handle_file_information),
[WPD properties](https://learn.microsoft.com/en-us/windows/win32/wpd_sdk/object-properties),
[WPD persistent-ID resolution](https://learn.microsoft.com/en-us/windows/win32/api/portabledeviceapi/nf-portabledeviceapi-iportabledevicecontent-getobjectidsfrompersistentuniqueids),
[cloud placeholders](https://learn.microsoft.com/en-us/windows/win32/cfapi/cloud-files-api-portal).

### Review of the Adoption Gates and Identity Proposal (2026_09_21, Claude Fable 5.1)

Verdict per finding, measured where a claim could be checked on this machine:

| Finding | Verdict | Resolution kept simple |
| --- | --- | --- |
| 1 Incremental narrowing is not monotone for the grammar; `casefold` differs from `re.IGNORECASE` | **Valid** | Drop incremental narrowing except for one case: substring mode, plain literal (no operator characters), query extended by appended characters. Everything else re-evaluates from `order`; a full pass costs 6 ms (substring) / ~25 ms (fuzzy) at 202k, so the optimisation was never needed for the gate. Case handling: one rule for both modes, decided explicitly (Unicode casefold is the better one; `IGNORECASE` parity is the conservative one). |
| 2 `.*?` fuzzy regex backtracks (`'a'*64` vs `'a'*16+'b'` timed out) | **Valid** | Build the subsequence pattern as `[^a]*a[^b]*b[^c]*c` (each class excludes the next character): no backtracking beyond linear scanning. Probe: adversarial case 0.12 ms instead of >2 s; 202k throughput 29 ms vs 24 ms for the lazy pattern. It yields the greedy-earliest match; compute tight spans for ranking only on displayed rows. |
| 3 Names are not identity | **Valid**, with the caveat below | Adopt object IDs on NTFS/ReFS via the 128-bit bulk enumeration (see next section). Minimal reconciliation: match `(id, name)`; else `id` if unique in both snapshots; else drop the mark, cursor falls back to the same name or the neighbouring row. Operation-known renames map explicitly. No hard-link group logic beyond that. |
| 4 Commands place the cursor right after a mutation; rescan is asynchronous | **Valid, important** | `place_cursor_at(url)` stores a pending target on the pane; the next commit applies it. Mutation events set one dirty flag; one scan runs at a time; a dirty flag set during a scan triggers exactly one more. No timer; the 200 ms wording is withdrawn. |
| 5 `scan(path)` has no cancellation; a blocked UNC scan holds the worker | **Valid** | `scan(path, check_canceled)` like the repository `Task` convention; the coordinator drops stale results by generation and may start one replacement worker while a blocked one retires (the QuickView loader pattern, bounded to two threads). |
| 6 Fixed schema breaks Process/drives providers; lists are mutable | **Valid** | Optional vectors (`sizes`/`mtimes` may be `None` per provider), `extra: dict[str, tuple]` for provider columns, `tuple` storage. Validation of equal lengths at publication. |
| 7 Sort/format goldens differ (`file999999` vs `file1000000`, KiB vs KB, descending dirs) | **Valid** | The PoC's natural order is the correct one (today's `%06d` padding mis-sorts 7-digit runs); the rest must reuse `format_size` and today's directional rules. Accept the one fix explicitly, keep the others identical. |
| 8 Shell icon extraction at paint can block | **Partially** | Extraction happens at paint today as well (`QIcon` engines are lazy; Windows resolves on `pixmap()`), so this is not a regression. Bound it: per-suffix cache for ordinary files, per-file only for `.exe/.lnk/.ico/.url` in visible rows. An async icon service is a later refinement, not an adoption gate. |
| 9 QuickView clears on `modelAboutToBeReset` | **Valid** | QuickView compares the cursor URL after reset and keeps the image when unchanged; a five-line change in `fman/impl/quick_view.py`. |
| Storage Capabilities table (MTP, WebDAV, SFTP, cloud) | **Over-scoped** | No MTP/WebDAV/SFTP provider exists in this application; these rows are not adoption gates. Keep: local NTFS/ReFS, removable NTFS/ReFS, UNC (scandir path, unknown identity), cloud placeholders (reparse tag, not followed). FAT32/exFAT: deferred by the user; unknown identity, name fallback. |

The review is correct on substance and its test matrix is the right one; where
it adds machinery (multi-stage hard-link reconciliation, per-medium identity
contracts, an icon service), the table above records the simpler resolution.

### NTFS and ReFS Identity Backend

Facts established on this machine (Python 3.14.7, Windows 11): volumes `C:`/`D:`
are NTFS, `E:`/`F:` are ReFS. `GetVolumeInformationW` reports for all four
`FILE_SUPPORTS_OPEN_BY_FILE_ID`, `FILE_SUPPORTS_HARD_LINKS`,
`FILE_SUPPORTS_REPARSE_POINTS` and `FILE_SUPPORTS_USN_JOURNAL`; ReFS lacks only
`FILE_SUPPORTS_OBJECT_IDS`, which this design does not use. `os.stat().st_ino`
is 128-bit capable in this Python: 55 significant bits on NTFS, 75 on ReFS, i.e.
CPython reads `FILE_ID_INFO`, so identity from the bulk enumeration and from a
later `os.stat` agree on both filesystems.

Rules:

- **One code path for NTFS and ReFS.** Use only the 128-bit classes:
  `FileIdExtdDirectoryRestartInfo`/`FileIdExtdDirectoryInfo` for entries and
  `FileIdInfo` for the volume scope. Never `FileIdBothDirectoryInfo` or
  `BY_HANDLE_FILE_INFORMATION.nFileIndex*`: on ReFS the 64-bit forms are not
  unique and may read as all-ones.
- **Capability gate, not filesystem-name gate.** Enable IDs when the directory's
  volume reports `FILE_SUPPORTS_OPEN_BY_FILE_ID` and the info class succeeds;
  otherwise (`ERROR_INVALID_PARAMETER`, `ERROR_NOT_SUPPORTED`, FAT32/exFAT, UNC,
  unknown drivers) fall back to `os.scandir` with identity unknown. The name of
  the filesystem is recorded for diagnostics only.
- **Scope** = `FileIdInfo.VolumeSerialNumber` (64-bit) of the scanned directory.
  IDs from different scopes never match; a re-plugged removable volume that
  reports the same serial is the same scope.
- **Lifetime.** Both filesystems keep the ID across rename and move within the
  volume; both may reuse an ID after deletion (ReFS is not documented to
  guarantee otherwise). Reconciliation is therefore a UI convenience: operations
  validate their targets at execution as today.
- **Hard links** exist on both; the `(id, name)` rule keeps rows distinct.
- **Reparse points** on both: use `ReparsePointTag` from the record to classify
  symlink/junction/cloud placeholder without following; one followed `os.stat`
  only for symlinks and junctions (today's behaviour), none for placeholders.
- **Attributes** are identical in meaning; the hidden rule is unchanged.
- **Tests.** The unit tests inject records and simulated ID reuse; the live
  gate runs the parity test (names, sizes, mtimes, attributes, IDs vs
  `os.stat`) on one NTFS and one ReFS temporary folder; `E:`/`F:` make the ReFS
  half runnable on this machine. FAT32/exFAT is a later iteration and is recorded
  as an expected skip, not silently omitted.

Cost (from the probe above): +35 ms scan and +3.1 MiB for 202,603 entries,
which leaves the 0.42 s first paint intact.

### Other Performance-Preserving Resolutions

- Keep the real query grammars. Incrementally narrow only proven monotone
  transitions; otherwise reevaluate the index array. Restrict literal fast paths
  to cases with verified Unicode equivalence. No filesystem work is needed.
- Replace the fuzzy backtracking regex with bounded subsequence matching and
  existing ranking/normalization semantics. Keep full candidates independently
  of top-N display limits. Use latest-request computation separate from blocked
  I/O; the current matcher is not assumed to meet the 16 ms result-latency gate.
- Separate navigation, snapshot and view-request revisions. One latest pending
  job per lane; filter changes must not restart directory enumeration. Compute
  immutable index results on workers and validate their revisions on Qt.
- Coalesce mutation events with one dirty flag and a guaranteed final rescan.
  Carry pending cursor intent/commit acknowledgment for create and rename.
  Preserve operation-cache invalidation; snapshot replacement alone is not enough.
- Keep Core formatting and directional sort rules first. Use optional immutable
  column vectors and a versioned directory-total overlay, rather than rescanning
  whenever an optional calculated value changes. Keep disabled services dormant.
- Return generic/cached icons synchronously; a bounded platform-safe service
  fetches misses off the paint path and publishes only affected cells. This is
  an explicit amendment to the one-worker restriction, not hidden work in `data`.
- Preserve logical cursor/content notifications through resets so QuickView does
  not repeatedly decode an unchanged image. Still invalidate on replacement or
  content change. Measure real Qt selection/Select All restoration and peak
  snapshot memory before promising the existing performance gates.

## Current Matcher Experiment

Implemented on 2026-09-21 at the user's request, limited to the standalone PoC
and its tests. The application redesign is still pending; this task remains in
`Plan/`. No change to production matching, file operations or the plug-in API.

### Method

- `--algorithms current` (default) imports the existing `compile_filter` and
  `Matcher`. Filter evaluates the full base every time; fuzzy uses the existing
  parser, normalization, scoring, result limit and UTF-16 highlights unchanged.
  `SearchEntry.url` carries an integer snapshot index inside this experiment;
  these records never reach file operations. The current wrapper still creates
  per-entry tuples and normalized strings; this is a correctness baseline, not
  the final no-duplicate-record adapter.
- `--algorithms simple` preserves the original incremental substring/regex
  algorithms. A displayed fuzzy limit does not truncate their next candidate set.
  The known adversarial regex issue remains in this explicitly selected mode.
- Both modes use identical candidate order and output limits for comparison.
  Default scope includes all pane-visible entries, including directories.
  `--fuzzy-scope files --fuzzy-include-hidden` uses file-only enumeration order
  independently of hidden pane entries. It does not reproduce the application's
  separate indexer, inspection limit, error handling or complete reparse policy.
- Current fuzzy timing includes highlight generation; simple timing does not.
  Highlights are returned/tested but not drawn by the PoC table. Different
  grammar/ranking means output equality between simple/current is not expected.
  For example, current fuzzy normalizes `no-match` into two tokens and finds 25
  System32 files; simple treats the hyphen literally and returns none.
- The harness now timestamps after the paint handler returns, including empty
  results, and fails on paint timeout. Calls are synchronous, not posted input;
  this still does not measure held-key backlog or application event dispatch.
  Fuzzy setup happens after first paint and is reported separately. Listing
  refresh timing explicitly excludes rebuilding the fuzzy index.

Python 3.14.7 / Qt 5.15, native Windows platform, three fresh-process pairs per
case, simple/current order reversed on pair 2, disposable application settings,
warm OS caches, no cache flushing. Full scan of each one-level folder, no 50k
application index cap. Default fuzzy limit 100. Query vectors below include
extensions, deletions and misses; each is followed by an empty-query reset.

| Folder | Filter queries, in order | Fuzzy queries, in order |
| --- | --- | --- |
| CelebAAligned | 1, 12, 123, 1234, 12345, 1234, 12, no-match | 1, 19, 199, 1998, 19981, 1998, 19, no-match |
| System32 | s, sy, sys, syst, system, sys, no-match | s, sh, shl, shll, shl, no-match |
| WinSxS | m, mi, mic, micro, microsoft, mic, no-match | m, mc, mcs, mcso, mcsof, mcs, no-match |
| C root | p, pr, pro, program, pr, no-match | p, pg, pgf, pg, no-match |

### Results

Matching medians pool nonempty query steps over the three runs, in milliseconds.
Setup/paint/memory values are medians over runs. These are sampled costs, not
worst-case bounds; the two algorithm modes have deliberately different semantics.

| Folder / entries | Filter simple -> current | Fuzzy simple -> current | Current fuzzy setup | Current match + paint median (Filter / Fuzzy) |
| --- | ---: | ---: | ---: | ---: |
| CelebAAligned / 202603 | 2.99 -> 23.51 | 17.08 -> 152.15 | 427.52 | 26.61 / 155.42 |
| System32 / 4757 | 0.10 -> 1.07 | 0.78 -> 6.04 | 12.97 | 4.99 / 14.59 |
| WinSxS / 24315 | 0.59 -> 5.41 | 5.61 -> 53.73 | 230.36 | 10.69 / 58.87 |
| C root / 19 (9 pane candidates) | 0.003 -> 0.038 | 0.043 -> 0.080 | 0.043 | 0.30 / 0.56 |

For 202603 entries, first completed paint was 454.4 -> 458.9 ms, excluding fuzzy
setup. Working set after matcher setup was 141.1 -> 208.2 MiB, not peak memory.
Current largest observed Filter/Fuzzy match + paint was 30.2 / 174.4 ms. System32
paint/icon work occasionally exceeded matching cost (Filter total max 37.8 ms).
The 16 ms interaction gate is **not met** by this synchronous compatibility mode.

Retained pair summaries below are `first paint / median Filter / median Fuzzy`,
milliseconds; medians exclude empty-query resets. More precise per-query values,
row counts, memory and setup measurements are in the local generated JSON reports
under `target/diagnostics/pane-current-algorithms/` (`paired-results.json`,
`scope-results.json`, `highlight-cost.json`); these are not release artifacts.

| Folder | Mode | Pair 1 | Pair 2 | Pair 3 |
| --- | --- | --- | --- | --- |
| CelebAAligned | simple | 454.4 / 3.0 / 17.0 | 455.2 / 2.8 / 17.3 | 453.0 / 2.9 / 17.1 |
| CelebAAligned | current | 462.1 / 23.5 / 152.7 | 454.7 / 23.6 / 151.6 | 458.9 / 23.4 / 152.2 |
| System32 | simple | 98.7 / 0.1 / 0.8 | 100.2 / 0.1 / 0.8 | 102.5 / 0.1 / 0.8 |
| System32 | current | 99.7 / 1.0 / 6.1 | 97.4 / 1.1 / 6.1 | 105.3 / 1.1 / 6.0 |
| WinSxS | simple | 226.1 / 0.6 / 5.6 | 204.8 / 0.5 / 5.6 | 217.4 / 0.6 / 5.7 |
| WinSxS | current | 221.2 / 5.4 / 51.1 | 213.8 / 5.4 / 50.4 | 209.5 / 10.1 / 56.8 |
| C root | simple | 110.5 / <0.1 / <0.1 | 109.7 / <0.1 / <0.1 | 107.7 / <0.1 / <0.1 |
| C root | current | 110.2 / <0.1 / 0.1 | 113.6 / <0.1 / 0.1 | 108.5 / <0.1 / 0.1 |

Additional three-pair scopes:

- File-only, include hidden, limit 100: System32 had 4577 candidates, 12.52 ms
  current index setup, and 4.69 / 5.11 / 5.99 / 5.76 ms for `s`, `sh`, `shll`,
  `no-match`. WinSxS had only two direct files, with 0.03 ms setup and 0.86 / 0.04 /
  0.02 / 0.01 ms for `m`, `mc`, `mcs`, `no-match`. Thus its all-pane timings above
  are not representative of today's file-only Fuzzy Find workflow.
- All results, 202603 candidates: simple -> current for `1` was 35.35 -> 1232.11
  ms (142417 rows); `19` 23.01 -> 631.08 ms (49420 rows); `19981` 9.37 -> 150.87 ms
  (47 rows). Current computes highlights for every returned row in this mode.
  Post-query working set was 136.4 -> 246.1 MiB, not peak.
- A separate three-pair, one-process probe called unchanged `Matcher(query)`
  versus `Matcher.matches(query)` on the same unlimited index. For `1`, ranking
  alone took 104.87 ms versus 1212.18 ms with highlights; for `19`, 171.48 versus
  599.80 ms; for `19981`, 154.38 versus 154.28 ms (timing noise for 47 highlights).

Conclusion: existing algorithms work with snapshot indices and preserve the
listing speed advantage, but their costs must not be replaced by the simplified
PoC timings. The next adapter should avoid duplicate entry/normalization storage,
compute highlights only for displayed results, and schedule expensive matching
away from Qt with stale-result guards. These improvements are not implemented
or performance-guaranteed by this experiment. Neither benchmark mode includes
the proposed native bulk-ID backend or real application integration.

### Reproduction

Use the existing application environment, without installing packages. Set
`$Folder`, `$Label`, `$FilterQueries` and `$FuzzyQueries` to a row above; use the
same inputs for both modes. Use a disposable `ROYIFILEMANAGER_USER_SETTINGS`
directory and ensure `QT_QPA_PLATFORM=windows` for native runs.

```powershell
foreach ($Pair in 1..3) {
    $Modes = if ($Pair % 2) { @('simple', 'current') } else { @('current', 'simple') }
    foreach ($Mode in $Modes) {
        python src/misc/pane_arch_poc.py $Folder --platform windows --algorithms $Mode --max-results 100 --queries $FilterQueries --fuzzy $FuzzyQueries --json "target/diagnostics/pane-current-algorithms/$Label-$Pair-$Mode.json"
        if ($LASTEXITCODE -ne 0) { throw 'PoC benchmark failed' }
    }
}
```

For the all-results case use `--max-results 0`, Filter `1,12,no-match` and Fuzzy
`1,19,19981,no-match`. For file-only cases add `--fuzzy-scope files
--fuzzy-include-hidden` and the four fuzzy queries recorded above. The direct
highlight probe reuses one `CurrentFilter(..., max_results=0).prepare()` matcher,
alternates `matcher(query)` / `matcher.matches(query)` three times per query,
collects garbage outside each timer and discards results between samples.

## Reviewers

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Initial design at the user's request, with compatibility breaks
  permitted. Proposed a single immutable columnar `Listing` per pane with
  `order`/`visible` index arrays, a virtual model, pure-function columns,
  rescan-on-change instead of incremental diffs, per-suffix icons and hidden
  attributes from the enumeration. Built and measured a proof of concept
  (`src/misc/pane_arch_poc.py`, 8 passing tests): 0.42 s scan-to-first-paint,
  4–6 ms filter keystrokes, ≤ 31 ms worst-case fuzzy, 334 ms full refresh and
  131 MiB working set on the 202,603-entry reference folder, against 6.1 s,
  ~1 s, seconds and 807 MiB today. Not scheduled; migration steps and golden
  fixtures are defined for when it is.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Snapshot/virtual-model direction is viable, but adoption is not
  approved yet. Confirmed unsafe grammar-wide incremental narrowing, Unicode and
  fuzzy compatibility differences, a single-entry fuzzy timeout, column golden
  mismatches and shallow immutability. Added explicit identity/selection,
  mutation acknowledgment, cancellation/publication, provider/column, icon-I/O
  and reset-integration gates with a concrete test matrix. Eight PoC tests and a
  read-only native C-root smoke passed; neither establishes application parity or
  worst-case responsiveness. Review only; original design record preserved.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed measured bulk-ID identity with hardlink-aware reconciliation
  and optional provider-specific identity contracts. Three-pair local probes
  measured 331 -> 365 ms scan/sort/filter for 202603 entries and 3.091 MiB packed
  ID payload; native rename/hardlink fixtures and C-root IDs passed. A junction
  timestamp discrepancy was traced to the PoC; followed stat matched Core.
  Added USB/filesystem, MTP, cloud and network capability/fallback policies and
  live-test gates, plus bounded query/refresh/icon alternatives. These backends
  are not universally implemented or validated. Recommendations only; runtime
  and PoC code remain unchanged, and prior reviewer records are preserved.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the current-matcher adapter against production contracts and
  clarified candidate scope, result limits, index setup and highlight costs.
  Compatibility reuse is feasible; the measured synchronous implementation does
  not meet the 16 ms interaction gate. PoC-only experiment, not architecture
  adoption approval or an independent implementation review.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Reviewed the GPT-6 Astra adoption gates and identity proposal at
  the user's request; added "Review of the Adoption Gates and Identity
  Proposal" and "NTFS and ReFS Identity Backend". Findings 1–7 and 9 are
  valid; 8 is not a regression (icons resolve at paint today too); the
  MTP/WebDAV/SFTP rows are out of scope for this application. Verified by probe:
  a `[^c]*c` subsequence pattern removes the fuzzy backtracking case (0.12 ms
  instead of a timeout) at equal throughput; `C:`/`D:` are NTFS and `E:`/`F:`
  are ReFS with `FILE_SUPPORTS_OPEN_BY_FILE_ID`, hard links and reparse points
  on all four; this Python's `st_ino` is 128-bit (75 bits on ReFS), so the
  bulk 128-bit IDs and `os.stat` agree on both filesystems. Recommended one
  128-bit code path gated on volume capability (never the 64-bit classes),
  scandir fallback with unknown identity for FAT32/exFAT/UNC (deferred by the
  user), and the minimal `(id, name)` reconciliation rule. Design only; no
  application or PoC code changed.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: User authorized NTFS/ReFS implementation incorporating every later
  review. Correctness takes precedence over initial performance targets; retain
  production matchers, immutable native identity, authoritative operation checks
  and unsupported-provider fallback. Adoption tests remain required, not waived.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Incorporated the user's explicit approval to remove the old design
  and migrate every bundled provider with breaking APIs. One snapshot consumer,
  provider-specific acquisition, no automatic compatibility adapter. Historical
  baseline runs only from a temporary Git archive. Performance and edge-case
  adoption gates remain open; earlier fallback recommendations are superseded.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review focused on correctness, edge cases and
  performance. **Approved for continued adoption work; not for closing the
  task** (the implementer's open gates stand). Re-ran both documented gates:
  `fman_integrationtest.test_qt` 182 OK; unit/provider/command batch 425 OK,
  7 skips. Read `fman/listing.py`, `core/fs/local/windows/listing.py`,
  `LocalFileSystem.scan`, `impl/model/listing.py`, `impl/model/__init__.py`,
  `listing_icons.py`, the view's snapshot capture/restore, Core columns and the
  filter snapshots. Live probes of the native scan: `C:/ProgramData`,
  `C:/Users`, `C:/`, `E:/` (ReFS), System32 and the reference folder all match
  `os.listdir` exactly with 128-bit IDs for every entry; the deny-ACL legacy
  junctions are followed without error; 202,603 entries scan in 291 ms.
  Verified correct: `FILE_ID_EXTD_DIR_INFO` layout and unpack order (88-byte
  header), `.`/`..` skipped, record bounds validated, `ERROR_NO_MORE_FILES`
  termination, NTFS/ReFS + `FILE_SUPPORTS_OPEN_BY_FILE_ID` gate, UNC and
  unsupported-error fallback to `scandir`, scope = volume serial + directory
  ID, reconcile by `(id, created)` with exact name first then IDs unique in
  both snapshots, filter state captured on Qt (`snapshot_filter`) which closes
  the Filter Bar race, `_order_cache` reuse so a keystroke re-filters without
  re-sorting, pending cursor target for create/rename, icons resolved off the
  paint path with reparse/offline/recall entries never touched, selection
  restored as contiguous ranges.
  Findings, none blocking:
  1. **Followed-link errors abort the whole listing.** In both the native scan
     and `_scan_entries`, the followed `os.stat` for a symlink/junction handles
     only `FileNotFoundError`; any other `OSError` (access denied on the target,
     unreachable network target) propagates and the directory fails to list.
     The old per-entry path degraded to `is_dir=False`. Catch `OSError`, keep
     the entry with its own record. Could not reproduce with a deny-RA ACL
     (Windows still answers the attribute query), so this is a robustness fix.
  2. **`refresh_files` always re-projects and resets.** DirectorySize results
     trigger `update()` → full sort + `beginResetModel` + selection/scroll
     restore for every delivery, even when the sort column is Name. When the
     sort column does not depend on the changed values, clearing the text cache
     and emitting `dataChanged` for visible rows is enough; re-project only
     when sorting by Size. Cheap change, avoids reset churn in folders with
     many subdirectories.
  3. **`Modified.keys` builds 202k `datetime` objects; `Size.keys` builds
     per-character `ord` tuples for directories.** Sorting on the raw
     `mtimes_ns` integers (`-1` for `None`) and on lowercase name strings is
     equivalent and several times cheaper; `sorted()` is the one uncancellable,
     GIL-holding step (measured up to 134 ms Qt stall on all-marked name sort),
     so key cost is the lever.
  4. **PaneRendering001 machinery is now dead weight.** `iterdir` still runs
     `scandir` + per-entry `cache.put` (539 ms at 202k) to feed
     `_pane_hidden_state`, but the pane reads `listing.attributes` directly.
     Revert `iterdir` to `os.listdir` and remove `_EntryAttributesCache`; the
     URL form of `_hidden_file_filter` only needs the `QFileInfo` fallback.
  5. **`project()` cancellation check uses the entry index** (`index % 256`)
     rather than the loop counter; statistically fine, not strictly bounded.
  6. **`Listing` rejects names containing a backslash** — legal on POSIX; a
     Windows-first decision, but it should be stated in `PlugIn.md`.
  7. The Mac `/Volumes` exception exists only in the URL filter, not in the
     snapshot filter (`attributes & 2`). Windows-only impact none; note it.
  8. Documentation drift: the record says 184/427 tests; today's runs give
     182/425. Update the numbers when the gates are re-run.
  Performance evidence in Validation Results is sound and matches the
  reviewed code paths; the remaining gates (16 ms p95 under load, 250 MiB
  peak) are Python sort/key cost and marked-state restoration, which items 2–3
  partly address.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Follow-up to the implementation review at the user's request:
  measured the removable per-pass overhead on the 202,603-entry reference
  folder (in-process probe against the implemented modules, warm cache). The
  native enumeration itself is ~200 ms; everything below is Python work on top
  of it and executes identically on every platform — a Windows-only focus does
  not remove it, it only means it can be optimised without parity concerns.

  | Overhead | Measured | Removal | Saves |
  | --- | ---: | --- | ---: |
  | `iterdir` still runs `scandir` + `cache.put` per entry for `_pane_hidden_state` (PaneRendering001 leftover; the pane reads `listing.attributes`) | 539 ms per `iterdir` call | Revert to `os.listdir`; delete `_EntryAttributesCache` and the URL branch of `_hidden_file_filter` | 539 ms per caller (Search plug-ins, `fs.iterdir`) |
  | Hidden filter via `all(predicate(...) for predicate in filters)` in `project()` | 44.6 ms per projection (every keystroke, sort, rescan) | No filters → `visible = order`; let a filter expose a vector form so hidden becomes `[i for i in order if not attributes[i] & 2]` (5.5 ms) | ~40 ms per keystroke |
  | `Name.keys` regex `sub` + lambda per name | 131 ms per sort/rescan | Cheaper key with identical order (`re.split` + `int`) or cache keys per listing | 60–80 ms per rescan |
  | `Modified.keys` builds 202k `datetime`s | 59 ms | Raw `mtimes_ns` ints, `-1` for `None` (10.5 ms, same order) | ~50 ms |
  | `Listing.__post_init__` validation (8 full passes) | 45 ms per scan | Trust bundled scanners; validate third-party providers only; keep the length check | ~40 ms per scan |
  | `reconcile()` on an unchanged rescan (16-byte slices + tuple compares per entry) | 60 ms per refresh | Short-circuit when `names`, `identities`, `created_ns` are equal (4 ms) → identity mapping | ~55 ms per refresh |
  | `check_canceled()` per record in `scan()` | 20–30 ms | Once per 64 KiB batch, as `batches()` already does | ~25 ms |
  | `ListingIcons.key()` with `PureWindowsPath(name).suffix`, computed twice per painted cell | ~3 µs × cells per repaint | `rpartition('.')`, compute once | paint-path hygiene |
  | `ScanObservation`/`FileWatcher.start()` per navigation | one worker→Qt `run_in_main_thread` round trip | Skip on Windows: the watcher is a stub | removes a sync point |

  Only the last row and the `_scan_entries` dot-name branch are actually
  platform-specific. Reference for `sorted()` itself once keys exist: 7.9 ms —
  key construction, not sorting, is the cost. Net effect if applied: a Filter
  Bar keystroke drops from ~70 ms of framework work plus matcher to ~15 ms
  plus matcher; a rescan after an operation loses ~200 ms of ~560 ms; peak
  memory shrinks with the per-keystroke `rows` dicts and key tuples. Items are
  each a few lines and order-preserving except `Name.keys`, which needs the
  golden-order check because of the `%06d` padding quirk. No code changed.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Addressed both Fable review records. Accepted correctness fixes and
  order-preserving optimizations; retained full validation, notification handoff
  and Size ordering. Rejected raw timestamp ordering and timestamp caches after
  parity analysis and measured distinct-timestamp regressions. Final comparison
  validates 499 compatible metrics; adoption gates remain open.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Reviewed the response to my two records; **approved**. Verified in
  code: followed-link `os.stat` now catches `OSError` and keeps the entry's own
  record in both the native scan and `_scan_entries`; per-record
  `check_canceled()` replaced by per-batch and per-link checks; `iterdir` is
  `os.listdir` again and `_EntryAttributesCache`/`_pane_hidden_state` are gone;
  `refresh_files` repaints via `dataChanged` unless the sort column declares
  `keys_depend_on_external_data` (default `True`, Name/Modified opt out, Size
  stays dependent — the right default for third-party columns); hidden filter
  exposes `filter_indices` with 256-row batches and keeps the Mac `/Volumes`
  exception; `reconcile` short-circuits on equal names/IDs/creation times;
  `Name.keys` uses split/rejoin — checked byte-identical to the old `sub`
  form on 20,012 names including 7-digit runs, Unicode digits, empty and
  punctuation-heavy names; `PlugIn.md` documents the backslash rule,
  `filter_indices` and `keys_depend_on_external_data`. Re-ran both gates:
  Qt 184 OK, unit/provider/command 410 OK (7 skips), matching the record.
  Dispositions I disagreed with and accept: keeping `Listing` validation
  (45 ms on the worker, not Qt — a fair trade for one safety boundary);
  rejecting raw-nanosecond Modified keys (parity with local-time ordering
  across DST and microsecond ties is a legitimate choice; chronological order
  would be the more correct behaviour if parity is ever dropped); keeping the
  watcher handoff (my suggestion concerned only the stub OS watcher, and the
  application-level callbacks are indeed required). Residual notes, none
  blocking: the unchanged-rescan fast path still materialises a 202k-entry
  identity dict (~20 ms) where a sentinel would do; `refresh_files` emits one
  `dataChanged` over the whole visible range, which Qt clips to the viewport
  but is worth knowing when reading profiles; the new `src/performancetest`
  harness and `build.py measure` were not reviewed in depth here. Adoption
  gates remain as the implementer recorded.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the isolated sentinel and Windows no-op dispatch prototypes
  before application edits. 500 differential identity cases and 249 existing
  checks pass (three expected skips). Nine alternating 200,000-entry Qt reset
  pairs preserve all marks, cursor and scroll; median commit 24.774 -> 19.775 ms.
  Source hashes unchanged. Approve the two narrow merges subject to dedicated
  production regressions; broader architecture adoption remains pending.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Reviewed refresh benchmark coverage: eight deterministic selection
  patterns on both synthetic folder sizes, real reload through new-snapshot
  completed paint, and unchanged snapshot/order/marks/cursor/scroll assertions.
  Setup and correctness checks are untimed. The single overview value equally
  weights 16 case medians; detailed cases retain regressions. Process peaks are
  cumulative, not refresh-only allocations. Existing loaded-input and memory
  adoption gates remain open; earlier harness records are not comparable.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: User requires the 0.8.1 Quicksearch experience for current-folder Find.
  Reuse the existing snapshot-indexing branch and production fuzzy matcher;
  remove only the command's in-pane diversion. Keep Filter Bar syntax distinct.
  Verify dialog query/highlight/metadata/accept/cancel behavior and no rescan.
  Retarget fuzzy timing to Quicksearch and revise its workload identity; preserve
  historical measurements without claiming comparable latency or closed gates.

### 2026_09_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Recorded explicit user/main-developer acceptance from real-world use.
  Closed the implementation with the original performance thresholds and unrun
  adoption checks documented as follow-up work in FSPaneArch002, not as passed
  tests. Preserved previous reviews, implementation records and measurements.

## Implementer

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Added current/simple matcher selection, production-result parity
  coverage, completed-paint timing and JSON reports to the standalone PoC.
  Ran three-pair native comparisons on the reference folder, System32, WinSxS
  and C root, plus file-only/all-results scopes and isolated highlight costs.
  Only the PoC experiment is implemented; production architecture remains pending.

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented immutable listings, native NTFS/ReFS 128-bit scans,
  virtual panes, bounded work, production filter/Find integration and bundled
  provider migration. Removed the incremental engine. Verified native source
  startup/restart, provider/operation regressions and real application A/B parity.
  Adoption remains incomplete: loaded interaction and peak-memory gates below
  are not all met. No release or completion approval is implied.

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented link-error isolation, metadata repaint without unnecessary
  resets, batch filtering, bounded cancellation, removal of enumeration caches,
  exact-order Name keys, bound datetime conversion, unchanged-snapshot
  reconciliation and single-pass icon keys. Qt gate: 184 passed. Focused
  unit/provider/command gate: 410 run, seven expected skips. Final snapshot
  regressions: 36 passed. Full measurement catalog: nine workloads, three fresh
  processes each, all passed. Task remains pending adoption.

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Merged the two separately validated prototypes: known-identity
  unchanged-index sentinel and Windows-only no-op watcher dispatch bypass.
  Dedicated identity/alignment/cancellation, selection and thread-affinity
  regressions pass. Post-merge focused gate: 255 checks, three expected skips.
  Actual merged functions retain the isolated performance gains; no claim of
  satisfying the broader loaded-input or peak-memory adoption gates.

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Added small/large native refresh workloads with eight selection
  patterns, completed-paint and memory measurements, and unchanged-state checks.
  Added the single Refresh / Selection report/table aggregate while retaining
  individual timings and guarded comparisons. Focused correctness: 44 passed.
  Full catalog: eleven workloads times three processes passed, including 48
  refresh observations. This establishes a refresh baseline, not a speedup claim
  or completion of the architecture adoption gates.

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Restored snapshot-backed fuzzy Quicksearch for Ctrl+F without changing
  the Filter Bar matcher. Retargeted fuzzy UI benchmarks to the dialog and bumped
  their revision. Focused search/filter/panel checks: 168 tests, two expected
  skips. Native Windows dialog/focus checks: three passed. Both fuzzy sizes and
  small Filter Bar benchmark smoke passed. Architecture remains pending adoption.

## Validation Results

### Completion Review (2026_09_22)

Reviewed the existing unit, provider, Qt, native smoke and benchmark evidence
below. This closure adds no application code and does not rerun the full test
suite, packaging or environment-specific checks. User acceptance supersedes the
original adoption-blocking decision, not the recorded test outcomes.

The latest focused Fuzzy Find run used the restored Quicksearch dialog:

```powershell
python src/performancetest/run.py suite --test 'fuzzy.*' --test recursive.tree --results UserSettings/Performance/runs --note 'Fuzzy Find-only measurement after restoring Quicksearch; three default repetitions.'
```

All three workloads passed all three repetitions, including UI/algorithm result
count parity. Slowest-query paint medians were 4.67 ms (256 files), 350.86 ms
(200,000 files) and 91.08 ms (recursive, 50,000 files). These exclude dialog
opening and do not measure loaded-input p95. The statistics-only record is
`UserSettings/Performance/runs/3b559f28-d64e-49f5-8e0f-ef0aaba508ca.json`;
its version identifier is `Unreleased`, with source version 0.9.0.

Documentation closure verification passed: this task has one canonical file
under `Done`, FSPaneArch002 is indexed under Pending, both task documents retain
the required sections, and incoming architecture links resolve after the move.
The move preserved the file's SHA-256 hash. `git diff --check` also passed.
These checks do not replace the deferred runtime checks.

### Restored Find Dialog and Panel Focus

The two TODO bugs are fixed: Ctrl+F opens the fuzzy Quicksearch dialog, and Escape
on Search files / Find files with fd restores the last active pane after cleanup.
Snapshot-backed indexing retains fuzzy subsequence matching, fzf operators,
highlights, metadata descriptions, Enter acceptance and Escape cancellation.
Tests require no provider rescan for a suitable snapshot. The shared panel close
path checks for closed windows, replaced panels, other active dialogs and deleted
or disabled target widgets before restoring focus. Filter Bar retains its
substring/glob grammar; full fzf query operators were not part of that grammar.

Commands run from the existing application environment:

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); tests=['fman_unittest.test_search_file_fuzzy','fman_unittest.impl.test_filter_pattern','fman_unittest.test_filter_find_benchmark','fman_integrationtest.test_qt.SearchFileSyntaxIT','fman_integrationtest.test_qt.SearchFileMetadataIT','fman_integrationtest.test_qt.FilterBarIT','fman_integrationtest.test_qt.SnapshotFilterBarIT','fman_integrationtest.test_qt.TableIT','fman_integrationtest.test_qt.FindFilesIT','fman_integrationtest.test_qt.SearchFilesIT']; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', *tests], env=env, timeout=180).returncode)"
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.TableIT.test_panel_escape_returns_focus_to_last_active_pane', 'fman_integrationtest.test_qt.FindFilesIT.test_escape_closes_both_search_panels_and_focuses_pane', 'fman_integrationtest.test_qt.SearchFileMetadataIT.test_reserved_rows_reorder_filter_accept_and_cancel'], env=env, timeout=180).returncode)"
python src/performancetest/run.py suite --test 'fuzzy.*' --test filter.small --repeat 1
```

Outcomes: 168 focused tests, two skips (opt-in external fzf reference and
unavailable directory-symlink creation); three native Windows checks passed.
The three native benchmark workloads passed UI/algorithm count parity in
`target/performance/runs/229865b2-179e-4b65-86a5-11a525c3cccf.json`.
These are one-process smoke checks, not a version-history update or evidence of
improved speed. Fuzzy test revision 2 and changed harness prevent comparison
against earlier in-pane results. No full correctness suite, full measurement
suite, packaging, dependencies or environments were created.

### Refresh / Selection Baseline

The refresh-enabled catalog run is
`UserSettings/Performance/runs/89b9c834-e23f-439c-9581-8e828cbd0424.json`.
All eleven workloads passed three fresh-process repetitions on Windows/NTFS.
The 48 refresh observations preserve exact selection counts, cursor, scroll,
snapshot columns and row order. Setup and correctness checks are outside timing;
no files change and no input is injected during reload. Both sizes include no
marks, first/middle/last single marks, a 10% middle block, 100 scattered marks,
all except the cursor, and all entries. All work remains demand-only.

| Refresh Result | Measured Value |
| --- | ---: |
| Mean of 16 case medians | 482.95 ms |
| Small-folder case-median range | 8.22-10.15 ms |
| Large-folder case-median range | 938.85-978.24 ms |
| Large-folder all-selected Qt commit median | 29.58 ms |
| Large-folder all-selected process peak median | 307.41 MiB |

The process peak includes startup and preceding cases, not isolated refresh
allocation. Full row-text fingerprinting is omitted before these cases to avoid
artificially warming every formatted cell. Native reload checks compare immutable
snapshot columns and row order after completed paint. The catalog/harness changed;
do not compare this baseline to earlier runs using the strict comparison command.
No ReFS rerun, cold-cache claim, changed-folder refresh, loaded-input p95 gate,
full correctness suite or packaging run. The task remains pending adoption.

Focused checks, from the existing application Python environment:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_filter_find_benchmark', 'fman_unittest.test_pane_rendering_benchmark'], env=build._environment()).returncode)"
python src/performancetest/run.py suite --test refresh.small --repeat 1
python build.py measure
```

The small-fixture native smoke passed all eight cases. The focused unit gate
passed 44 tests without skips; the full measurement passed 33 fresh-process
workloads. Raw-record inspection also verified all 48 selected counts against
the pattern definitions and confirmed the 16-case aggregate and eleven-row
overview. Diagnostics reported no errors in the changed benchmark/report code.
Generated HTML passed browser checks at 1440 and 390 pixels: eleven overview
rows, all 16 refresh paint metrics, correct aggregate range, nonblank chart,
no page errors or page-width overflow. The changelog value was checked against
the retained record's aggregation. `git diff --check` passed with only existing
line-ending warnings.

### Isolated Follow-up Results

Application sources remained unchanged throughout prototype testing (SHA-256
checks). The final prototype passed 500 differential identity cases and 249
existing checks with three expected skips. Only then were the two application
changes merged. Post-merge gate: 255 checks, three expected skips (local-provider
environment/platform prerequisites), without prototype substitutions. Native
NTFS/ReFS provider checks are included; mocked non-Windows watcher calls verify
Qt affinity but do not constitute a native non-Windows run.

Nine alternating warm pairs use 200,000 synthetic entries, separately allocated
equal names/ID columns, and assert equivalent restored state. Watcher timing is
per registration/removal pair from a worker while Qt services its event loop.
The all-selected commit probe executes the real Qt model reset/restore path,
with icon loading disabled equally in both variants:

| Measurement | Retained Baseline | Merged |
| --- | ---: | ---: |
| Identity preparation, one selected entry | 22.067 ms | 2.955 ms |
| Identity preparation plus lookup, all selected | 31.638 ms | 9.913 ms |
| Actual Qt commit, all selected | 24.388 ms | 19.303 ms |
| Watch registration/removal pair | 0.0615 ms | 0.0005 ms |
| Remap shallow object size | 10,485,848 bytes | 16 bytes (`None` singleton) |

All 200,000 marks, cursor and scroll survive each Qt commit. The avoided roughly
10 MiB dictionary is an object-size result, not a measured process-peak reduction.
Watch dispatch gains are small in absolute time; neither probe measures whole
navigation latency. Keep earlier full-catalog numbers unchanged: `build.py measure`
was not rerun for this narrow follow-up. No full correctness suite or packaging.

Raw observations under `target/diagnostics/`: `snapshot-followup-prototype.json`,
`snapshot-followup-qt-prototype-final.json`, `snapshot-followup-merged.json`, and
`snapshot-followup-qt-merged.json`. The runner stores source hashes with results;
current output also records the experiment hash and merged/prototype selection.

Commands, from the existing application Python environment:

```powershell
python src/misc/benchmark_snapshot_followup.py --qt-tests
python src/misc/benchmark_snapshot_followup.py --measure --output target/diagnostics/snapshot-followup-prototype.json
python src/misc/benchmark_snapshot_followup.py --qt-restore --repeat 9 --output target/diagnostics/snapshot-followup-qt-prototype-final.json
python src/misc/benchmark_snapshot_followup.py --qt-tests --merged
python src/misc/benchmark_snapshot_followup.py --measure --merged --output target/diagnostics/snapshot-followup-merged.json
python src/misc/benchmark_snapshot_followup.py --qt-restore --merged --repeat 9 --output target/diagnostics/snapshot-followup-qt-merged.json
```

Use new output filenames for reruns: raw records are not overwritten. Initial
runner failures were corrected before merge: missing inherited subprocess paths,
absent disk fixture, explicit standalone Qt startup and callback binding. The
prototype's first zero-run shortcut was safely too conservative; alignment-aware
search fixed the missed optimization and has cross-boundary/unknown-ID regressions.
The first production Qt regression used the wrong fixture location accessor;
corrected and rerun successfully. No failures are hidden by skips.

### Review Response and Measurements

Disposition of the implementation findings and all nine overhead proposals:

| Area | Decision |
| --- | --- |
| Followed-link failures | Catch target `OSError` in both scanners and retain own metadata; directory enumeration failures still propagate. |
| Metadata delivery | Name/Modified repaint without worker projection or model reset. Size and custom columns default to reprojection through `keys_depend_on_external_data=True`. Cursor/marks are covered by Qt tests. |
| Name keys | Split/rejoin numeric runs into the same `%06d` strings, including Unicode digits, leading zeros and long numbers. Do not replace historical order with integer natural sorting. |
| Modified keys | Bind the datetime converter once. Raw nanoseconds change local-time/DST order and microsecond ties; `-1` is not below every valid pre-epoch timestamp. Dictionary and adjacent-value caches were tried and discarded after 26% and 11% distinct-timestamp regressions. |
| Size keys | Retain direction-dependent code-point tuples and DirectorySize ranks. Plain lowercase strings change descending directory order and cannot replace the mixed rank contract directly. |
| Enumeration cache | Delete `_EntryAttributesCache`, `_pane_hidden_state` and its URL-filter branch. `iterdir` uses `os.listdir`; operation caches remain independent. Historical benchmark-only code remains isolated. |
| Projection/hidden filtering | No-filter projections reuse cached order. Optional batch predicates remove per-row generator overhead. Scalar cancellation counts visited rows, not entry IDs; hidden batches check every 256 rows. Preserve the Mac root `/Volumes` exception. |
| Listing validation | Retain validation for bundled and third-party providers. Trusting bundled output bypasses the shared immutability/type/name safety boundary for a speed-only gain. |
| Reconciliation | Fast-path equal names, packed IDs and creation times after checking scope/location. Exclude unknown IDs, preserve exact-name hardlinks and check cancellation every 256 entries. |
| Native scan checkpoints | Check each 64 KiB batch and every followed link, instead of every ordinary record. Blocking native calls still cannot be interrupted mid-call. |
| Icons | Compute suffix/key once and avoid full paths for shared extension icons. Retain `PureWindowsPath` semantics rather than introduce another suffix parser. Shell arguments and queue bounds are tested. |
| Scan observation/watchers | Retain subscriptions and handoff. The Windows OS watcher stub does not remove application file-added/removed notifications or other providers' change callbacks. |
| POSIX names | Document the Windows-first rejection of literal backslashes in `PlugIn.md`; no expansion of platform scope. |
| Validation counts | Current gates are 184 Qt and 410 unit/provider/command checks, seven skips. Private-cache tests were removed/replaced; historical counts below are not current claims. |

Final before/after records, both `Unreleased`, on the same machine, NTFS,
fixtures, harness and configuration:

- Before: `UserSettings/Performance/runs/c3b25fff-6aef-4e93-b1b8-aabcb034d9a0.json`.
- Final: `UserSettings/Performance/runs/da05f2e0-ca6c-443f-914e-10df3e0a3ac4.json`.
- Intermediate experiment: `c37bdd5b-a158-4aff-9a90-c4978299f70a`, retained but
  superseded after removing timestamp caching. No harness changes during comparison.

| Overview Median | Before ms | Final ms | Change |
| --- | ---: | ---: | ---: |
| Small pane first paint | 42.04 | 44.14 | +5.0% |
| Large pane first paint | 1218.72 | 1030.26 | -15.5% |
| Small Filter Bar, slowest query | 9.38 | 9.72 | +3.6% |
| Large Filter Bar, slowest query | 374.67 | 332.28 | -11.3% |
| Small Fuzzy Find, slowest query | 10.78 | 11.68 | +8.4% |
| Large Fuzzy Find, slowest query | 486.90 | 476.94 | -2.0% |
| Recursive Find, slowest query | 91.10 | 89.82 | -1.4% |
| Small QuickView first preview | 116.98 | 109.73 | -6.2% |
| Large QuickView first preview | 122.56 | 118.74 | -3.1% |
| Navigation aggregate | 7.15 | 6.79 | -5.0% |

All eight large Filter Bar query medians improve by 11.3%-40.4%. Other small
movements are not conclusive from three process samples: QuickView was slower
in the intermediate run, and several ranges overlap. No statistical-significance
claim. Memory did not improve: large Fuzzy peak is 286.99 -> 289.30 MiB, and
large-pane settled working set is 175.43 -> 176.58 MiB. The catalog does not
revalidate the all-marked loaded-input p95 gate; adoption remains incomplete.

Hot-path probes assert equal results and alternate old/new order over seven warm
pairs on the canonical 200,000-entry fixture. Old enumeration uses the removed
cache implementation from `56e840a`; other probes reproduce the pre-review
algorithms. Unchanged reconciliation excludes the old no-op checkpoint overhead.
Timestamp probes use eleven pairs on repeated and distinct synthetic values.
These timings isolate function costs, not complete user interactions:

| Hot Path | Before ms | Final ms |
| --- | ---: | ---: |
| `iterdir` | 531.68 | 82.87 |
| Name keys | 730.46 | 545.09 |
| Hidden filtering | 34.81 | 6.04 |
| Unchanged reconciliation | 52.43 | 20.70 |
| Modified keys, repeated timestamps | 49.93 | 43.58 |
| Modified keys, distinct timestamps | 49.32 | 43.37 |

Exact focused commands, from the existing application Python environment:

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt', 'fman_integrationtest.impl.model.test___init__'], env=env, timeout=180).returncode)"
python -c "import build, subprocess, sys; modules=['fman_unittest.test_listing','fman_unittest.test_process_pane','fman_unittest.test_search_file_fuzzy','fman_unittest.impl.plugins.test_mother_fs','fman_unittest.impl.plugins.test_plugin','fman_unittest.impl.test_fs_cache','fman_unittest.test_pane_rendering_benchmark','core.tests.fs.test_local','core.tests.fs.test_zip','core.tests.commands.test___init__']; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', *modules], env=build._environment(), timeout=240).returncode)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_listing'], env=build._environment(), timeout=120).returncode)"
python build.py measure
python src/performancetest/run.py suite --compare UserSettings/Performance/runs/c3b25fff-6aef-4e93-b1b8-aabcb034d9a0.json UserSettings/Performance/runs/da05f2e0-ca6c-443f-914e-10df3e0a3ac4.json
```

All passed; comparison accepts all 499 metrics. Qt emits expected offscreen
platform warnings; seven unit/provider skips cover opt-in/platform/environment
prerequisites. No full correctness suite, clean/freeze, installs, new environments
or Registry writes. Mac behavior has mocked parity coverage, not a native Mac run.
The generated `UserSettings/Performance/index.html` was opened by `measure`.

### Initial Production Integration (Historical)

- `fman_integrationtest.test_qt`: 184 passed after migrating old worker fixtures.
  Includes actual ProcessPane commands/unload, ZIP deep implicit folders, two-pane
  hidden state, navigation cancellation/errors, reset selection/editor/drag
  handling, Filter/Find, QuickView, directory-size columns and hosted result focus.
- Focused unit/provider/command batch below: 427 run, 10 expected skips (opt-in
  checks and environment/platform prerequisites). No failures. Following the
  archive cutoff removal, reran the full archive module: 101 run, 2 skips.
- Benchmark wrapper after mode migration: 8 passed. Identity/provider Find:
  100 run, 5 expected skips. Final native QuickView smoke passed both source
  and fresh-process restart, with disposable settings and snapshot-worker cleanup.
- Earlier failing fixture assumptions were migrated, not suppressed: old worker
  barriers, iterator fault injection and synchronous mutation expectations.
  Real failures fixed included post-navigation refresh errors, watch-registration
  rollback and successful result-navigation focus ordering.

Run from the existing application Python environment; no installation, full
`build.py test`, clean/freeze/package or Registry writes were performed:

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt'], env=env, timeout=180).returncode)"
python -c "import build, subprocess, sys; modules=['fman_unittest.test_listing','fman_unittest.test_process_pane','fman_unittest.test_search_file_fuzzy','fman_unittest.impl.plugins.test_mother_fs','fman_unittest.impl.plugins.test_plugin','fman_unittest.impl.test_fs_cache','fman_unittest.test_pane_rendering_benchmark','core.tests.fs.test_local','core.tests.fs.test_zip','core.tests.commands.test___init__']; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', *modules], env=build._environment(), timeout=240).returncode)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_zip'], env=build._environment(), timeout=240).returncode)"
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'fman_integrationtest.quick_view_smoke'], env=env, timeout=150).returncode)"
python -m unittest src/unittest/python/fman_unittest/test_pane_rendering_benchmark.py
```

### Application Performance

Three alternating fresh-process pairs per folder; native Qt, warm OS caches,
hidden filtering enabled, QuickView/status disabled. Historical sources and
resources come from `56e840a72e4eda0cf957c1b1bd19fe905f00dcd0` in temporary storage,
not a production compatibility switch. All 24 ordered row/text fingerprints
matched, settings were isolated and error lists were empty.

| Folder | Entries | First Paint ms, Old/New | Metadata Ready ms, Old/New | Settled MiB, Old/New |
| --- | ---: | ---: | ---: | ---: |
| CelebAAligned | 202,603 | 5663.4 / 583.4 | 11497.9 / 570.6 | 771.3 / 165.6 |
| System32 | 4,757 | 219.4 / 53.9 | 345.8 / 41.1 | 116.2 / 89.0 |
| WinSxS | 24,315 | 862.9 / 218.9 | 1607.4 / 203.5 | 197.0 / 98.7 |
| C root | 19 | 86.2 / 31.6 | 88.0 / 24.5 | 96.6 / 87.3 |

Reference-folder post-paint Qt commit work: 1511.0 ms to zero; metadata tail:
5834.5 ms to zero. These are folder-loading, not application-startup timings.
Raw paired evidence: `target/diagnostics/fs-pane-unified-final.json`.

A separate full-candidate interaction run retained all 202,603 marks, with no
errors. Default Find cap is 50,000 inspected entries; this stress run raises it
to one million and therefore indexes all reference entries.

| Phase | Completed Paint ms | Arrow-to-Paint p95 ms | Maximum ms |
| --- | ---: | ---: | ---: |
| Filter | 259.1 | 17.0 | 28.8 |
| Clear filter | 137.0 | 11.4 | 15.6 |
| Full-candidate Find | 1142.8 | 12.0 | 38.1 |
| Exit Find | 141.1 | 14.2 | 15.4 |
| Modified sort | 191.3 | 20.3 | 57.5 |
| Refresh | 830.7 | 14.8 | 125.7 |
| Name sort, all marked | 287.0 | 36.2 | 134.1 |

Idle arrow-to-paint p95: 6.7 ms. Interaction peak: 285.1 MiB, down from the
earlier 332.2 MiB run after avoiding full identity ambiguity tables on ordinary
refresh. Raw evidence: `target/diagnostics/fs-pane-interactions-unified.json`.
Input sampling acknowledges one posted arrow at a time, not held-key backlog;
short phases include follow-on settled samples. Maxima remain important.

Reproduction (set the first argument to the reference folder):

```powershell
python src/misc/benchmark_pane_rendering.py "<reference-folder>" "$env:WINDIR/System32" "$env:WINDIR/WinSxS" C:/ --baseline current --repeat 3 --output target/diagnostics/fs-pane-unified-final.json
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'fman_integrationtest.pane_rendering_benchmark', sys.argv[1], '--child', 'snapshot', '--interactions', '--output', 'target/diagnostics/fs-pane-interactions-unified.json'], env=env, timeout=180).returncode)" "<reference-folder>"
```

### Deferred Follow-up Work

The following items were open adoption gates before the user's 2026_09_22
acceptance. They are preserved as limitations and copied into
[FSPaneArch002](../Plan/FSPaneArch002.md), not claimed as passed:

- Not all loaded interaction phases meet 16 ms p95; peak interaction memory
  exceeds 250 MiB. Python sort/key generation, large marked-state restoration
  and snapshot validation remain measured costs, not solved by worker dispatch.
- Held-key backlog, two simultaneous large panes with optional services,
  adversarial full-scale queries and broader mixed-entry workload measurements.
- Live cloud/offline/access-denied/removable/network cases, icon DPI/association
  behavior and external drag automation. Native NTFS/ReFS identity and ordinary
  file-operation regressions passed; these do not substitute for the remaining
  environment-specific checks.
- Portable artifact smoke was not requested or run. The user explicitly revised
  the completion criteria; this unrun check no longer blocks closing this task.

### Earlier PoC

- Immediate first-edit check: `fman_unittest.test_pane_arch_poc.FilterTest`,
  eight tests passed, including the bounded adversarial child.
- Full touched PoC module: 15 tests passed, including current grammar/Unicode,
  ranking/highlights/limits, independent candidates, empty listings, both CLI
  modes and existing scan/model/timing tests. Offscreen Qt for automated tests;
  native Windows Qt for the measurements above.
- Focused invocation from the existing application environment:

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_pane_arch_poc', '-v'], env=env, timeout=120).returncode)"
```

- No full suite, package build, new packages, application code changes or live
  USB/MTP/cloud/network tests. Application integration, real input latency,
  identity reconciliation and peak memory remain unverified adoption gates.
