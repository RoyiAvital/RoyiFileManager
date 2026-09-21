# Improve Pane Scan

Status: Proposed design; review before implementation. Only the standalone
benchmark and its tests are implemented. Application scanning is unchanged.

## Task

Compare and support two local directory-scanning approaches:

- **Per-file scan:** `os.listdir()` for names, then `os.stat()` for metadata.
- **Optimized scan:** `os.scandir()` with reuse of enumeration metadata and
  selective `os.stat()` calls where complete metadata is required.

Make the approaches selectable while preserving filesystem-operation safety.
The user extended the task on 2026_09_21 to cover sluggish Up/Down navigation
after large folders first render. Priority: correctness and smooth interaction
once the pane is shown, then shorter initial loading. A reasonable initial wait
is preferable to a faster first paint followed by seconds of unresponsiveness.

### Existing Benchmark

[benchmark_directory_listing.py](../src/misc/benchmark_directory_listing.py)
is a standard-library-only, read-only, one-level comparison. A `DirEntry` can
represent a file, directory or link; neither approach automatically recurses.

- Baseline: `listdir()` plus one stat result per entry, not one per column.
- Candidate: fresh `scandir()` plus `entry.stat()` for each entry.
- Both follow targets and retry without following only on `FileNotFoundError`.
- Compare names, directory flags, file sizes and exact `st_mtime_ns` values.
  Normalize directory size to `None`; record errno/winerror for failures.
- Time enumeration and result construction with `perf_counter_ns()`. Alternate
  method order and exclude warmups from timing statistics.
- Compare every result, including warmups, with the first outside timing.
  Differences or metadata errors withhold speedups and cause exit code 1.
  Missing folders also fail; invalid run counts produce exit code 2.
- OS caches are not flushed. First-observed does not mean cold-cache.
  Sorting, icons, formatting, Qt, plug-ins and application caches are excluded.

### Recorded Performance

Collected on 2026_09_20 using Python 3.14.7 on Windows 11 build 26200
(`Windows-11-10.0.26200-SP0`). Times below are milliseconds. Ratios were
calculated before rounding displayed medians.

| Folder | Entries / directories | Listdir + stat median | Scandir median | Median saved | Ratio | Equality |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Repository root | 24 / 9 | 0.098 | 0.029 | 0.069 | 3.43x | Pass |
| `src/main/python/fman` | 8 / 2 | 0.042 | 0.018 | 0.024 | 2.30x | Pass |
| `%WINDIR%/System32` | 4,757 / 180 | 25.105 | 3.762 | Withheld | Withheld | Invalid |
| `%WINDIR%/SysWOW64` | 2,883 / 151 | 14.012 | 2.241 | 11.771 | 6.25x | Pass |
| `%WINDIR%/WinSxS` | 24,315 / 24,313 | 192.694 | 46.268 | 146.426 | 4.16x | Pass |

Additional retained measurements:

| Folder | Listdir min / max | Scandir min / max |
| --- | ---: | ---: |
| System32 | 24.572 / 28.788 | 3.719 / 4.191 |
| SysWOW64 | 13.460 / 15.804 | 2.211 / 2.302 |
| WinSxS | 190.125 / 195.760 | 45.417 / 48.086 |

System32 first-observed times: 40.104 ms for listdir + stat and 6.357 ms for
scandir, with scandir first. Folder selection/counting had already warmed
enumeration caches. WinSxS subdirectory contents were not scanned.

Small-folder savings were only 24-69 microseconds. The larger-folder savings
justify evaluating metadata reuse, but these are not whole-pane timings.

Commands originally run from the repository root:

```powershell
python src/misc/benchmark_directory_listing.py . src/main/python/fman --repeat 10
python src/misc/benchmark_directory_listing.py "$env:WINDIR\System32" "$env:WINDIR\SysWOW64" "$env:WINDIR\WinSxS" --repeat 30 --warmup 2 --first scandir
```

The first command used two warmups, ten measured runs and listdir first. The
second used two warmups and thirty measured runs per method; it exited 1 due
to System32 while still measuring the other folders.

### Observed Differences

System32 produced 32 results differing from the first reference and zero
metadata errors. Two subsequent comparisons both isolated this same entry:
`5E37410B-D6F1-471D-AE27-563CEAC0D6B2`.

| Query | Directory | Bytes | Modification time, ns |
| --- | --- | ---: | ---: |
| Scandir | False | 17,374 | 1789421446454543200 |
| Stat | False | 17,520 | 1789421491294898800 |

The cause is unknown. Neither hard links nor concurrent writes were established
as the explanation. Fresh enumeration did not remove the difference in those
two probes. This historical entry is not a permanent test fixture; do not omit
it merely to report a speedup.

A separate Windows probe on the benchmark script found equal display metadata
but incomplete identity in the enumeration result:

| Field | `os.stat()` | `DirEntry.stat()` |
| --- | ---: | ---: |
| `st_dev` | 6522454556174564065 | 0 |
| `st_ino` | 30399297484824109 | 0 |
| `st_nlink` | 1 | 0 |

The numbers identify the observed sample, not test constants. This matches
[Python's documented Windows behavior](https://docs.python.org/3.14/library/os.html#os.DirEntry.stat).

### Whole-Pane Profile (2026_09_21)

Read-only measurements on the CelebAAligned dataset: 202,603 entries, including
202,599 JPEGs. QuickView was never imported. The separate uniform-row-height fix
was already active; this measures the remaining first-list-display delay.

| Phase | Lightweight timing | Detail |
| --- | ---: | --- |
| Worker preparation | 6.04 s | Row/name/directory metadata setup: 3.73 s; filtering/sorting: 1.86 s. |
| Qt-thread model commit | 2.19 s | Repeated filtering/sorting: 1.86 s; initial row diff/application: 0.30 s. |
| Remaining dispatch and first paint | 0.03 s | Paint callback itself: 15 ms. |
| First populated paint | 8.26 s | Includes the preceding phases; not image decoding. |

Separate raw enumeration took 71 ms. Only 34 visible rows needed full-column
preloading. Profile captures identify `Name.get_sort_value -> is_dir -> stat`
during every row's construction. Both filtering passes invoke
[the hidden-file helper](../src/main/resources/base/Plugins/Core/core/commands/util.py),
which creates a fresh `QFileInfo(...).isHidden()` rather than using the stat cache:
202,603 calls per pass. Name comparisons are not the dominant sorting cost.

Method: disposable application settings, existing Python 3.14.7/Qt runtime,
`perf_counter()` boundaries around row preparation, Qt commit and first populated
paint, plus separate `cProfile` captures of preparation and commit. OS caches
were not flushed. Full profiling increased total time to 15.74 s, so its elapsed
times are not the baseline. This Python build's cProfile captures other threads;
the captures describe sequential regions, not exclusive per-thread CPU time.

The lazy-stat alternative targets metadata acquisition within the 3.73 s row
setup; it does not remove Python row/cache construction. Its provider-only form
does not affect hidden-file checks, which bypass that cache. Reusing Windows
hidden attributes would be an additional consumer change requiring parity tests
for attributes, links, errors and invalidation. Reusing the worker's filtered,
sorted rows at Qt commit is complementary but remains outside this scan task:
it needs sort/filter/navigation-state guards, not merely a faster iterator.

## Scope

Included: selectable local scan methods, enumeration metadata reuse, selective
full-stat fallback, metadata lifetime/invalidation, compatibility and focused
correctness/performance tests. Also include the explicitly requested post-render
responsiveness investigation and bounded metadata publication described below.

Excluded: recursive scanning, unrelated pane-loading changes, new background
workers/timers, and changes to unrelated application features.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5.
The original design below retains full-stat query semantics; unsupported
providers/custom columns continue through their existing paths. The reviewed
lazy-stat alternative has additional return-object compatibility qualifications
documented under Alternatives; it is not yet the selected design.

## Design

### Selectable Methods

| Choice | `pane_scan_method` | Behavior |
| --- | --- | --- |
| Per-file scan | `listdir` | Existing enumeration/cache path and complete-stat queries; proposed default. |
| Optimized scan | `scandir` | Reuse enumeration metadata for display/sorting, with required stat fallbacks. |

Store the choice in `Core Settings.json` through existing differential
configuration under `UserSettings/Plugins/User/Settings`. Missing/invalid
values use `listdir`. Provide a Command Palette choice for the two methods,
showing the current selection; no new default shortcut or toolbar is needed.

The setting applies to both panes and survives restart. Capture it once per
scan. Changing it successfully saves the preference, invalidates old scan
results/caches and reloads both panes through existing dispatch, preserving
their paths and surviving view state. Reject previous-method results after a
switch. Cancel/same-value choices do nothing; save failure leaves the old method
active and restores any modified in-memory setting. Never run both scans in
normal use or silently change the saved choice on an error.

### Metadata Separation

[LocalFileSystem](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py)
already caches full stat per path. Keep that cache and its public `stat()`,
`is_dir()`, `size_bytes()` and `modified_datetime()` behavior unchanged.

The optimized collector returns names plus immutable, plain display metadata:
directory flag, byte size and modification time. Convert modification times
as today. Do not retain `DirEntry`, open iterators or handles in these records.
The listing/model owns these snapshots; they are not a second shared full-stat
cache. Obtain names and metadata from the same scan, not different cached scans.

Use a narrow private adapter between the local provider,
[filesystem dispatch](../src/main/python/fman/impl/plugins/mother_fs.py) and
[model](../src/main/python/fman/impl/model/model.py). In optimized mode the
built-in [columns](../src/main/resources/base/Plugins/Core/core/__init__.py)
and row directory flags consume available snapshots. Replacing only the names
iterator would leave per-entry stat calls in place and lose the main benefit.

Keep existing formatting/sort semantics. Snapshot support must be explicit;
do not bypass custom column overrides, including subclasses of built-ins.
Missing metadata or unsupported consumers use their existing full-query path.
This adapter is private host/Core coupling, not a new public plug-in contract.

Full identity remains on demand: `samefile()` compares actual device/file IDs,
recognizing hard-link aliases, while move decisions compare device IDs. These
calls retain complete stat results. Never seed the shared `'stat'` cache with
`DirEntry.stat()` or globally redirect operational queries to display records.

### Differences and Fallbacks

| Case | Difference / solution |
| --- | --- |
| Stable ordinary entries | Enumeration metadata normally supplies the required display fields without a separate path-based stat. |
| Changed/disappeared entry | Uncached stat can observe a later state; DirEntry may retain enumeration-time data. Neither is atomic and the current app also caches stat. Accept snapshot timing for display, retaining operational error checks. |
| Symlink/junction/reparse point | Detect reparse entries and use full path-based stat following the target; expect reduced savings. Unknown required attributes also take the full-query fallback. |
| Broken target | Preserve the existing retry without following only on `FileNotFoundError`; an entry itself gone still fails. `DirEntry.is_dir()` returning False for missing entries is not equivalent to an operational query that raises. |
| Permission/sharing failure | Preserve errors/fallback behavior rather than fabricating zero metadata. Enumeration success does not imply permission to open/copy. |
| Hard links | No need to detect every alias during enumeration. Keep complete identity checks for operations; separately test display metadata after writes through either alias. |
| Network/cloud entries | Metadata and reparse behavior depend on the filesystem/provider; do not promise no additional I/O or hydration. |
| Persistent metadata mismatch | Investigate the System32 observation and controlled fixtures. Explain differences or explicitly accept their display consequences before adopting optimized scan. |

Cheap classification cannot identify every stale ordinary entry or hard link.
Selective stat protects identity consumers and detectable special cases; it
does not guarantee display equality in every case. A user-selectable fallback
does not replace correctness testing.

### Lifetime and Failure Handling

- Use context-managed scandir; close on exhaustion, errors, cancellation and
  navigation away. Check existing cancellation between entries; a blocked
  native call retains existing interruption limits.
- Keep scanning on the existing worker and Qt/model changes on existing safe
  dispatch. Plain results carry the owning scan generation/method so stale
  work cannot publish after refresh or switching.
- Refresh/notifications invalidate affected display snapshots as well as the
  existing cached metadata. Targeted updates may use full stat instead of
  rescanning the directory. Panes do not share mutable snapshots.
- Per-entry metadata failures use existing query/error handling; preserve
  directory-level error behavior and do not cache failures as successful values.

## Alternatives

### Reviewed Alternative: Lazy Identity Stat (2026_09_20)

Added by review; not part of the original design. Three architectures compared:

| | Current | Proposed above | Lazy identity stat |
| --- | --- | --- | --- |
| Enumeration | `os.listdir` in `LocalFileSystem.iterdir`; names cached by `MotherFileSystem` | `os.listdir` or `os.scandir`, chosen by a persisted setting | `os.scandir` always |
| Metadata source | One `os.stat` per entry via `@cached stat`, first triggered by `Name.get_sort_value` -> `is_dir` before the pane shows | Optimized mode: new plain display records (dir flag, size, mtime) owned by the listing/model; full stat kept separately for operations | Same `'stat'` cache entry as today, seeded during the scan with a `LazyStat` proxy over `DirEntry.stat()` |
| Identity (`st_dev`, `st_ino`, `st_nlink`) | Always present | Full stat on demand through a separate path | Proxy performs one real `os.stat` on first access of an identity field and memoizes it; display fields never wait for it |
| Code touched | - | `LocalFileSystem`, `MotherFileSystem`, `Model`, Core columns, settings, palette command, two-pane reload | `LocalFileSystem` only (`iterdir`, `LazyStat`, reparse-point exclusion) |
| Public API / columns | - | Unchanged semantics but a private adapter with explicit snapshot support per consumer | Existing named-attribute consumers keep their calls; `query(url, 'stat')` can return a proxy with different type/protocol/error behavior, detailed below |
| Invalidation | `clear_cache(dir)` drops the subtree; `notify_file_changed` clears one path | Must invalidate display records *and* the stat cache in step | Identical to current: the proxy lives in the same cache node |
| Reparse points | Full stat | Full stat | Not seeded; existing full-stat path |
| Memory | One `stat_result` per entry | Display records plus stat results for touched entries | One proxy per entry, upgraded to a full result only when identity is read |
| Failure surface | Existing | New: stale snapshots vs cache, mode switching, adapter bypass by custom columns | Proxy return contract, deferred full-stat errors, concurrent upgrade and cache-seeding races |

Data flow of the lazy design: `iterdir(dir)` opens `os.scandir`, appends each
name, and for non-reparse entries calls `cache.put(dir + '/' + name, 'stat',
LazyStat(entry.stat(follow_symlinks=False), os_path))`. Later `is_dir`,
`size_bytes` and `modified_datetime` hit the cache and read `st_mode`,
`st_size`, `st_mtime` from the enumeration data. `samefile` (`samestat`) and
`_prepare_move` (`st_dev`) read identity fields; the proxy then runs the
existing stat-with-fallback once and serves every field from the full result.
Reload and `notify_file_changed` clear the same cache nodes as today, so a
subsequent direct stat cache miss obtains a full result. A directory rescan can
seed another proxy instead; refresh does not guarantee fresh full-stat display
metadata for every entry.

Why this resolves the plan's objections to seeding the shared cache: the
objection was that `DirEntry.stat()` returns zero identity on Windows, which
would defeat `samefile` and cross-device move detection. The proxy never
uses incomplete enumeration identity for these decisions; it obtains the real
stat values, retaining the existing fallback when the filesystem itself returns
zero IDs. Current named-attribute consumers need no proxy-specific changes.
This does not establish compatibility with every third-party consumer of the
returned object. Enumeration staleness is a separate metadata difference; the
specific System32 cause remains unconfirmed as recorded above.

#### Plug-in Compatibility and Return-Object Differences

For a local `file://` URL, `query(url, 'stat')` forwards to the provider's
`stat(path)`; it does not automatically materialize a proxy. Today this returns
a cached or newly obtained `os.stat_result`, or raises on an uncached failure.
In the lazy alternative, a seeded entry returns `LazyStat`; an unseeded entry
or excluded reparse point uses the existing full-stat path. The result type can
therefore depend on scan history, not just the URL.

| Consumer behavior | Current full-stat result | Seeded lazy result |
| --- | --- | --- |
| Read display fields such as `st_mode`, `st_size`, `st_mtime` | Values from the cached full stat | Enumeration values until upgraded; no new path stat for these reads |
| Read `st_dev`, `st_ino`, `st_nlink` | Already present; no I/O on attribute access | First read performs full stat with existing missing-target fallback; successful result is memoized |
| Read fields before and after an identity read | The same immutable snapshot | After upgrade, all fields use the full result; a previously read size/time can differ |
| Check `isinstance(result, os.stat_result)` | True | False; `os.stat_result` cannot be subclassed to make the proxy its subtype |
| Index, slice, unpack, call `len()` or `tuple()` | Supported sequence interface | Not supplied by attribute forwarding; fails unless explicitly implemented. Sequence access must not expose incomplete enumeration identity |
| Compare/hash/serialize the result, inspect its representation or use other stat fields | Native stat-result behavior | Not automatically equivalent; supported protocols/fields need explicit design and tests |
| Handle full-stat failures | Uncached full-stat failure occurs during `query()`; cached fields do not perform I/O | `query()` can return the proxy, then an identity read can raise an OS error |

The [documented fman API](https://fman.io/docs/api) exposes generic `query()` but
does not specify a standard `stat()` method or an `os.stat_result` return type.
The lazy alternative can preserve that documented interface and existing
named-attribute consumers without changing columns, the model or operation
call sites. Other filesystem providers and direct Python `os.stat()` calls are
unaffected. This is not a guarantee that every existing plug-in remains
compatible: a plug-in using Core's provider-specific stat result may reasonably
rely on its previous concrete behavior. Documenting a difference does not make
such a consumer work unchanged.

Compatibility conclusion: no known current consumer breakage due to the proxy's
representation, but a potential backward-compatibility break for third-party
consumers of `query(file_url, 'stat')`. Do not claim unconditional drop-in fman
compatibility for this alternative. Before adopting it, explicitly accept and
document this limitation, or keep proxies private and return a real full stat
from the externally reachable `stat()` method. The latter requires provider
display helpers to use a private cheap metadata accessor; it is a possible
refinement, not selected or implemented here. Retaining listdir mode provides
a fallback, not compatibility while the proxy-returning mode is active.

Evidence collected on 2026_09_20: a source audit found no current consumer
requiring the concrete type or sequence protocol. A temporary runtime probe
seeded attribute-only `SimpleNamespace` objects in the local stat cache and
passed directory/size/time queries, hard-link identity, copy/delete preparation
and an actual same-device move. It did not exercise lazy upgrades, concurrency,
all operations or external plug-ins; it is not implementation acceptance.

Acceptance tests for this alternative are written ahead of implementation in
[test_local_scan.py](../src/main/resources/base/Plugins/Core/core/tests/fs/test_local_scan.py)
(19 cases, skipped until `core.fs.local.LazyStat` exists): zero path stats for
display queries after a scan, exactly one memoized full stat on identity
access, hard-link `samefile`, same/cross-device `prepare_move` decisions,
symlink and broken-link fallback, directory/single-entry invalidation,
disappearing entries, handle closure, existing error behaviour, and a
1,000-entry zero-stat check.

```powershell
$env:PYTHONPATH = 'src/main/python;src/unittest/python;src/main/resources/base/Plugins/Core'
$env:PYTHONUTF8 = '1'
python -m unittest core.tests.fs.test_local_scan core.tests.fs.test_local
```

### Current Suggestion: Whole-Pane Reduction With Minimal Risk (2026_09_21)

Added by review after the whole-pane profile above. Goal stated by the user:
measurable gains with very little risk. The suggestion is ordered so that each
step is independently measurable and the riskier steps can be dropped.

**Where the 8.26 s goes** (202,603 entries; per-row figures derived from the
profile): worker row setup 3.73 s (18 µs/row: one `os.stat` + one new
`CacheItem` per file, the name queried twice, three `Cell`s built for one
loaded column); worker filter + sort 1.86 s (9 µs/row, dominated by
`QFileInfo(path).isHidden()` in
[`_hidden_file_filter`](../src/main/resources/base/Plugins/Core/core/commands/__init__.py));
Qt-thread commit 2.19 s (`update()` repeats the identical filter + sort, then a
0.30 s diff against an empty table). `RecordFiles` evaluates the hidden filter a
third time per row during background loading, also on the Qt thread.

**Measured options for the hidden check** (this machine, CelebAAligned, warm):

| Check | Semantics vs `QFileInfo.isHidden()` | Cost / entry |
| --- | --- | ---: |
| `QFileInfo(path).isHidden()` (today) | reference | 9.6 µs |
| Cached followed `stat().st_file_attributes` | **Wrong**: a junction to a hidden target becomes hidden (probe: `QFileInfo=False`, `stat(follow)=True`); drive roots `C:/`, `D:/` carry `HIDDEN\|SYSTEM` and Qt special-cases them | ~0 |
| `os.lstat(path).st_file_attributes` | Matches for links; roots still need the special case | 4.7 µs |
| `DirEntry.stat(follow_symlinks=False).st_file_attributes` from `scandir` | Same source `FindFirstFile` gives Qt; matches for links; roots are never entries of a listing | 0.7 µs incl. enumeration |

Conclusion: the cheap hidden check is correct only as a consumer of the scandir
scan. The followed-stat shortcut must not be used.

**Steps**

1. **Scandir + `LazyStat`** (the reviewed alternative above), with one addition:
   the proxy keeps the entry's own `st_file_attributes` in a private field
   (`entry_attributes`) for every entry, including reparse points whose display
   fields still come from the full followed stat. Expected: −1.4 s worker
   (202k `os.stat` calls replaced by the 71 ms enumeration).
2. **Hidden filter from entry attributes.** `_hidden_file_filter` reads
   `fs.query(url, 'stat')`; if the object carries `entry_attributes`, test
   `FILE_ATTRIBUTE_HIDDEN`; otherwise, and on any `OSError`, fall back to
   `QFileInfo` exactly as today. Expected: −1.4 s worker, −1.4 s Qt commit, and
   the third pass in `RecordFiles`.
3. **Re-profile** with the same boundaries as the whole-pane profile. Decide on
   steps 4–5 from the new numbers; after step 2 the commit-time recompute is
   expected near 0.4 s (sort of precomputed keys + cheap filter).
4. *Optional.* Commit the worker's sorted/filtered list in `_on_rows_inited_main`
   instead of `update()`. Only together with the `FilterBar` guard described
   under Risks; otherwise skip.
5. *Optional.* Measure whether `ComputeDiff(empty, N)` is the 0.30 s or the
   insert itself; special-case only if the diff dominates.
6. *Optional, independent.* Slim `CacheItem` (`__slots__`, lazily created
   `_children` / `_attr_locks`): measured 132 MiB and 1.65 s to create 202k nodes.

**Risk assessment and effect on other operations**

| Area | Step 1 (scandir + proxy) | Step 2 (hidden filter) | Step 4 (commit worker rows) |
| --- | --- | --- | --- |
| Copy / move / delete / rename | `samefile`, `_prepare_move` (`st_dev`) read identity through the proxy, which performs one real `os.stat` on first access. Same decisions as today; the 19 acceptance tests cover hard links and same/cross-device moves | Not involved | Not involved: operations arrive as file events and go through `RecordFiles` on `_files`/`_rows` |
| Display columns (Name/Size/Modified) | Values come from enumeration data instead of a path stat. NTFS may report a stale size/mtime for a file another process holds open for writing (the System32 case); Explorer shows the same value. Documented display consequence, no operational effect | None | None |
| Links / junctions | Display fields still follow the target (full stat for reparse points, as today); `entry_attributes` is the link's own | Matches `QFileInfo` by construction (probe above); parity tests: hidden junction → visible target, visible link → hidden target, broken link | None |
| Hidden-files toggle, drive roots, `drives://`, `zip://`, `network://` | Unaffected (other providers keep their paths) | Non-`file://` URLs return early as today; roots and unseeded paths hit the `QFileInfo` fallback | Toggle goes through `add_filter`/`remove_filter` transactions → `update()`; unaffected |
| Filter bar | Unaffected | Unaffected | **The one real race**: `FilterBar._accepts` has mutable state changed on the GUI thread while the worker filters. Guard: `FilterBar` connects to `location_loaded` and calls `sourceModel().update()` when active. Without the guard, typing during a load shows unfiltered rows until the next keystroke |
| Sort, `reload()`, `sort()` | `reload()` clears the cache and rescans; proxies are re-seeded | None | `sort()` and `reload()` keep their own `update()`/`sort()`; only the first commit changes |
| Cache invalidation, file watcher | `clear_cache` / `notify_file_changed` drop the same nodes as today; the Windows watcher is a stub, so no new event paths | A cold cache on the Qt thread means one real stat, the same syscall `QFileInfo` performs today | None |
| Status bar, DirectorySize, Search/Find plug-ins, QuickView | Status bar reads `size_bytes` via the cached object (proxy field). DirectorySize, `fd`/`rg` panels and QuickView use their own `scandir`/`os.stat`; unaffected | None | None |
| Third-party plug-ins | `query(file_url, 'stat')` may return the proxy instead of `os.stat_result` (documented above; no in-tree consumer needs the concrete type). Keep the `listdir` setting as an escape hatch for the first release | Private to Core | Host model change; upstream-mergeability cost only |
| Failure modes | Full-stat failure now surfaces on first identity read instead of at `query()`; existing callers already handle `OSError` there | Any exception inside `filter()` would empty the pane — the fallback must catch `OSError` | Inconsistent first view (see Filter bar) |

Recommendation: implement steps 1–3; they remove roughly 4 s of the 8.26 s with
`QFileInfo`-identical visibility and unchanged operation decisions. Treat steps
4–6 as separate, optional follow-ups gated on the step 3 profile.

### Post-Render Responsiveness: Ready Before Fast (2026_09_21)

The user reports several seconds of sluggish Up/Down navigation after the
CelebAAligned folder becomes visible. First paint alone is not a success metric.
Minimize initial waiting conservatively, but do not shift expensive work into
the period when the user expects to navigate or issue commands.

**Code path and measured contribution:** after initial publication,
[Model._load_remaining_files](../src/main/python/fman/impl/model/model.py)
continues loading icons and columns in nominal 200 ms worker batches. Each batch
synchronously enters `_record_files_main` on the Qt thread. That publication
time, `RecordFiles` filtering and transaction listeners are outside the worker
deadline. The batch also traverses already-loaded rows from the start again.
Visible-row loading has higher queue priority, but cannot preempt an executing
batch. The third hidden-file pass identified by Fable is therefore directly
relevant to this symptom; cheaper enumeration alone does not establish a fix.

**Conservative implementation order:**

1. Measure from first populated paint through background completion and an idle
   comparison window. Attribute Qt commits, hidden filtering, view/layout and
   enabled status/preview listeners separately; do not assume all are expensive.
2. Apply the selected, compatibility-verified metadata/hidden-filter optimization
   and remeasure the post-render tail as well as initial loading.
3. If input still stalls, bound worker batches and Qt publication separately.
   The existing worker must yield between small batches so visible rows,
   navigation, refresh and cancellation can take precedence. Use existing model
   transactions and dispatch, not new threads, recurring timers or nested event
   pumping. Bound publication work, not just time spent preparing rows.
4. Prefer doing unavoidable global preparation before publishing a usable pane
   over showing it early and immediately blocking it again. Keep offscreen
   details lazy only when their loading demonstrably leaves interaction smooth.
   Do not eagerly load every icon merely to move the same cost before paint.
5. Optimize repeated loaded-prefix traversal or listener work only if the profile
   identifies it; preserve mutable sort/filter state, custom columns, refresh,
   disappearing files and stale-result rejection. Retain the current safe scan
   path until the replacement passes both correctness and responsiveness gates.

**Interaction contract:** Up/Down, Page Up/Down, scrolling, marking/selecting,
pane switching, opening a file and command invocation must respond from the
first usable frame while metadata continues loading. Copy/move/delete and other
long operations need prompt dispatch/progress and cancellation, not instantaneous
completion; preserve identity checks and error handling. Navigation away must
not wait for all offscreen metadata or accept late results into a replacement
pane. Do not hide the delay by dropping key events, suppressing correctness
notifications, or disabling ordinary operations until background loading ends.

**Measurement and gates:**

- Post real arrow events at a controlled repeat rate; measure posting-to-cursor
  change and cursor-to-paint latency, not merely time inside `keyPressEvent`.
  Record first paint, final metadata completion, p50/p95/max input latency,
  event-loop gaps, maximum Qt commit time and longest nonpreemptible worker batch.
- Compare the first five seconds after paint, the remaining loading tail and a
  settled interval. A lower first-paint time cannot compensate for a worse tail.
  Initial performance target on the reference machine: p95 input-to-cursor
  latency <=50 ms and maximum <=100 ms, with no multi-second settling period;
  these are proposed performance gates, not existing measurements or CI timing
  assertions. Report scheduling/system noise rather than silently excluding it.
- Test QuickView and extended status summaries off first, then on independently;
  test pane filters and both scan methods. No feature-specific work when off.
- Add deterministic regressions to existing model/Qt tests for urgent visible-row
  work between batches, bounded commit sizes, eventual metadata completion,
  navigation/shutdown cancellation, no duplicate or missing rows, and unchanged
  order/cursor/selection after interleaved updates. Slow custom columns require
  explicit coverage; a single blocking native/plugin call remains an existing
  cancellation limit, not permission to stall the Qt thread.
- Exercise operations only on disposable fixtures, never by altering the user's
  large dataset. Use read-only navigation/selection for the large-folder probe.

#### Observed Baseline

Read-only native Windows probe on 2026_09_21, 202,603 entries, existing application
Python 3.14.7/Qt runtime, disposable settings and an empty opposite pane. QuickView
was not imported and extended status tracking was off. No application source or
dataset files changed. OS caches were not flushed; these are instrumented local
observations, not cold-cache measurements or an optimized implementation.

| Measurement | While metadata loads | After metadata completes |
| --- | ---: | ---: |
| Posted arrow to actual cursor change, median | 250 ms | 1.1 ms |
| Posted arrow to actual cursor change, p95 / maximum | 417 / 567 ms | 1.4 / 2.0 ms |
| Posted arrow to completed paint, median | 435 ms | 2.1 ms |
| Posted arrow to completed paint, p95 / maximum | 740 / 760 ms | 2.9 / 3.3 ms |
| Completed arrow samples | 25 | 34 |

First populated paint took 8.678 s. Metadata completion required **another
8.442 s**. There were 26 synchronous Qt commits, median 111 ms and maximum
121 ms, totaling 2.636 s. Their 202,569 filter evaluations took 1.991 s (about
76% of commit time); the view's transaction-end callback totaled only 0.494 ms.
All expected single-row Up/Down movements completed, with no timeouts; the final
row count remained 202,603. Other operations were not exercised in this probe.

This confirms substantial post-render Qt work with optional features disabled.
Fable's cheap hidden-attribute proposal targets a measured contributor, but does
not by itself prove smooth input: the worker batches, command dispatch and
paint scheduling also span this interval. Do not assign all remaining time to
icons, the GIL, or any one unprofiled callback. Remeasure end-to-end interaction
after the selected change, not only the hidden-check microbenchmark.

Procedure: use `build._environment()` with `QT_QPA_PLATFORM=windows` and a
temporary `ROYIFILEMANAGER_USER_SETTINGS`; launch a bounded child process with
the dataset and an empty folder as its two pane arguments. Instrument first
populated `FileListView.paintEvent`, `Model._record_files_main` on the Qt thread,
its filter calls and `all_rows_loaded`. Post ten Down then ten Up repeatedly
from a separate producer, with one event awaiting `currentChanged` at a time
and a 50 ms gap after acknowledgement. Timestamp the subsequent paint, continue
for two seconds after metadata completion, then shut down/join model workers.
Use a 30-second post-paint cap and an 85-second subprocess timeout. The producer
is diagnostic-only, not an application scheduling proposal.

An earlier fixed-rate probe gave similar phase times (8.349 s first paint,
8.344 s tail) and up to 599 ms waiting for key-event dispatch, but all key handlers
returned before asynchronous cursor movement. Those handler-return timings are
not reported as cursor latency; the signal-based measurements above supersede
them. Held-key/backlog and the wider operation/feature matrix remain required
implementation checks. No application optimization has been applied yet.

### Original Alternatives

- **Scandir for names only:** insufficient while consumers still stat every entry.
- **Replace full-stat cache with DirEntry data:** rejected because identity/link
  count fields are zero on Windows and operations require them.
- **Stat every entry to identify hard links:** largely loses the benefit;
  determine identity when operations need it instead.
- **Retain DirEntry objects or a global snapshot cache:** unnecessary lifetime
  and invalidation risk; use scan-owned plain records.
- **Unconditionally replace listdir:** rejected in favor of the requested
  runtime choice, with listdir retained as the conservative default.

## Runtime Effects

- Startup: no eager scan/service. Read the method through existing cached
  configuration once per listing; the initial configuration read is needed
  to honor the preference, not a per-entry or recurring settings read.
- CPU/I/O: both enumerate O(N) entries. Scandir reduces ordinary Windows metadata
  calls; special entries and operations still need full stat. Measure against
  existing listdir/stat cache reuse, including repeated and second-pane visits.
- Memory: O(N) compact display records for optimized listings; measure overhead
  and avoid duplicate maps. No long-lived DirEntry or open scan handles.
- Concurrency/cancellation: no new threads/processes/timers; reuse existing
  dispatch and reject stale results. Native calls are not forcibly interrupted.
- Post-render: smaller batches may trade total metadata throughput and more
  dispatches for lower input latency. Measure that tradeoff and avoid repeated
  whole-directory snapshots/rescans; do not assume background work is free.
- Switching: one settings save and reload of both panes, never parallel A/B scans.
- Disabled/no-op: listdir mode performs no optimized scan, snapshot allocation
  or recurring comparison work. Unsupported providers retain their baseline.

## Tests

### Existing Test Case and Results

[test_directory_listing_benchmark.py](../src/unittest/python/fman_unittest/test_directory_listing_benchmark.py)
contains 11 tests covering:

- Real files/directories, Unicode names, size/time equality and nonrecursion.
- Empty directories; file/directory symlinks and broken links.
- Missing-target-only fallback and scandir context cleanup.
- Permission errors without inappropriate fallback.
- Alternating order and warmup exclusion for either starting method.
- Withholding speedups for unequal results or errors, including matching errors.
- Missing folders and invalid repeat/warmup counts.

Original run: 11 tests in 0.059 seconds; 10 passed, one skipped because symlink
creation was not permitted. Mocked fallback/error checks passed; live symlinks,
junctions, network/cloud behavior and hard-link integration remain unverified.

```powershell
python -m unittest src/unittest/python/fman_unittest/test_directory_listing_benchmark.py -v
```

Use the direct-file invocation. Earlier narrow `unittest discover` also imported
unrelated nested packages and failed with `ModuleNotFoundError: No module named
'fman'`; the benchmark cases were not the cause. Original script/test/README
diagnostics and focused `git diff --check` passed. No full suite/build was run.

### Required Regressions

Extend existing local filesystem/model tests and the existing benchmark tests:

- Count path-based stat calls: optimized ordinary built-in metadata consumption
  avoids one per entry; listdir mode never calls scandir or creates snapshots.
  A later full-stat request must still return complete identity fields.
- Create hard links with `os.link()` in temporary supported storage. In both
  modes, aliases compare equal, unrelated files do not, same-file copy protection
  remains, and same/cross-device move decisions remain correct. Mock device IDs
  for portable decision tests; record unavailable live cases as gaps.
- Write through each hard-link alias and re-enumerate; compare metadata without
  assuming that this explains System32. Never hide unequal results in benchmarks.
- Valid/broken links, junctions, unknown attributes, permission errors,
  disappearance during scanning and iterator cleanup on every exit path.
- Snapshot/full-query display and sorting parity for stable fixtures; custom
  column overrides and unsupported providers retain behavior.
- Refresh/notifications discard stale metadata; switching either way during
  idle/loading rejects old results and refreshes both panes without losing
  surviving pane state. Repeated switching releases resources.
- Missing/invalid settings, persistence across restart, current-choice display,
  cancel/no-op, save failure and preservation of unrelated Core settings.

If the lazy alternative is selected, additionally test the actual public
`query(file_url, 'stat')` dispatch before/after enumeration, after invalidation
and in both scan modes. Cover named attributes, the chosen sequence/protocol
contract, concrete result types, full-stat upgrade failures and fields changing
after upgrade. Assert current operation consumers still work without changes;
separate these checks from concurrent upgrade/cache-seeding tests. A
private-proxy refinement must instead prove that public stat queries always
return real full results while display helpers still avoid per-entry stat.

Focused implementation commands (new cases above are planned, not implemented):

```powershell
$paths = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python')
$paths += Get-ChildItem src/main/resources/base/Plugins -Directory | ForEach-Object { $_.FullName }
$env:PYTHONPATH = $paths -join [IO.Path]::PathSeparator
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest core.tests.fs.test_local core.tests.test_fileoperations
python -m unittest fman_unittest.impl.test_fs_cache fman_unittest.impl.model.test_model
python -m unittest fman_integrationtest.test_qt.SortedFileSystemModelIT
```

### Performance and Manual Checks

- Repeat the recorded commands without suppressing differences/errors. Add
  quiet temporary 1k/10k/25k-entry file/directory mixtures and link fixtures.
- Compare the actual production enumeration/metadata path through both runtime
  choices, not just isolated Python APIs. Alternate order, separate preference
  save time from scan time, and restore the user's original setting afterward.
- Report entry counts, warmups, medians, ranges, absolute savings, stat counts
  and added memory, including repeated/second-pane cache effects. Label timings
  as first-observed or repeated, not controlled cold-cache.
- Manually select both methods, refresh after external changes, switch while
  scanning, and restart to verify persistence. No timing thresholds in ordinary
  unit tests; no full suite, clean/freeze or package build without request.
- Run the post-render interaction matrix above before declaring a speedup:
  arrows/scroll/selection, command dispatch and cancellation during metadata
  loading, then the same actions after completion. Report both windows.

## Implementation Steps

1. Review this comparison design and proposed listdir default. Investigate the
   mismatch read-only and with controlled hard-link fixtures; explain or
   explicitly accept persistent display differences before optimized adoption.
2. Add method validation/persistence and the optimized plain-data collector,
   preserving the original path and full-stat cache. Run narrow collector tests.
3. Integrate metadata reuse through the private adapter and built-in consumers;
   prove reduced stat calls without changing public/custom-column semantics.
4. Complete method selection, refresh/invalidation and stale-result rejection;
   run both-mode, operation-safety and persistence checks before exposing the option.
5. Measure production enumeration/metadata costs, memory and post-render input
  latency in both modes. Resolve measured metadata-publication stalls before
  optional first-paint shortcuts; run the interaction and cancellation gates.
  Keep listdir as default unless the user explicitly approves changing it.
6. On implementation acceptance, update README with the method choice and
   metadata tradeoff, and CHANGELOG with the delivered change/API statement.
   Record implementer/validation and move the canonical task to Done per policy.

## Acceptance Criteria

- Both methods are selectable and persistent; missing/invalid settings use
  listdir, and its disabled path performs no optimized work.
- Optimized ordinary metadata consumption avoids per-entry path-based stat;
  unsupported consumers/providers and special entries fall back appropriately.
- Full-stat API, hard-link identity and device-dependent operations remain
  correct. Enumeration metadata never replaces a complete cached stat result.
- Mode switching/refresh reject stale snapshots and preserve surviving pane
  state; iterators/resources close correctly without new asynchronous paths.
- Persistent metadata differences are explained or explicitly accepted, never
  reported as equal-work speedups. The System32 observation remains visible.
- Integration measurements justify the optimization after overhead/cache effects;
  small-folder savings and memory costs are reported without whole-pane claims.
- From first usable paint, navigation and command dispatch meet the post-render
  responsiveness gates while background metadata is still loading; there is no
  multi-second settling phase. Operations retain their safety and cancellation
  semantics. A faster first paint with worse responsiveness is not accepted.
- Focused tests pass and environmental gaps are recorded. Application docs and
  changelog/completion records are updated only when implementation is complete.

## Reviewers

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Designed only listdir-versus-scandir selection and metadata reuse,
  recording measured results, existing test coverage, identity protection and
  unresolved differences. Proposed listdir default with explicit correctness
  and performance gates; implementation/review approval remains pending.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Not approved as designed; the measurements and safety analysis are
  sound, the proposed architecture is disproportionate to the gain. Re-ran
  `test_directory_listing_benchmark` (11 tests, 10 OK, 1 symlink skip).
  Findings: (1) **Proportionality.** The saving is about 4.5 us per entry on a
  warm cache (System32: 25.1 ms vs 3.8 ms for 4,757 entries), i.e. ~4 ms per
  1,000 files, once per visit because `LocalFileSystem.stat` is already cached.
  The plan's own "not whole-pane timings" caveat applies: Python row
  construction (~7 us/row), icons and Qt dominate. A model/`MotherFileSystem`/
  columns adapter, a second metadata record type, a user-facing mode setting
  with palette command and two-pane reload is too much machinery for that.
  (2) **Simpler alternative not considered - lazy identity stat.** Implement
  `LocalFileSystem.iterdir` with `os.scandir` and seed the *existing* `'stat'`
  cache with a small stat proxy built from `entry.stat()`: display fields
  (`st_mode`, `st_size`, `st_mtime*`, `st_file_attributes`) answer directly;
  the identity fields (`st_dev`, `st_ino`, `st_nlink`) perform one real
  `os.stat` on first access and memoize it. The only identity consumers
  (`samefile` via `samestat`, `_prepare_move`'s `st_dev` comparison) then get
  complete data transparently, the public API and every column keep their
  semantics, no host, model or column code changes, and the "never seed the
  shared cache with DirEntry.stat" rule becomes unnecessary because the proxy
  is never incomplete when read. Reparse points still use a full stat as
  designed. This shrinks the task to Core's local provider plus tests.
  (3) **System32 mismatch is explainable.** NTFS keeps a duplicate of size and
  last-write time in the directory index and updates it lazily, typically when
  the writing handle closes; `FindFirstFile`/`DirEntry` read the index,
  `os.stat` reads the MFT record. A GUID-named System32 file held open by a
  service is the classic case, and Explorer shows the same staleness. Record
  this as a known display consequence for files open for writing rather than
  "cause unknown", and make the benchmark classify such differences instead of
  failing the run. (4) **Default.** With (2) and tests passing there is no
  reason to ship the slower path as default; keep a hidden `Core Settings.json`
  fallback (`listdir`) without a palette command or reload choreography, or
  drop the setting entirely. (5) Minor: the `unittest` invocation should use
  the standard `PYTHONPATH` setup rather than the note about `discover`
  importing unrelated packages; `st_mtime_ns` equality in tests must allow the
  staleness case from (3) on open files. Added the "Reviewed Alternative:
  Lazy Identity Stat" comparison under Alternatives and the acceptance test
  module `core/tests/fs/test_local_scan.py` (19 cases, all skipped until
  implemented; verified to import and skip cleanly).

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Prefer the provider-local lazy metadata direction over the original
  model/column adapter, subject to explicit compatibility and concurrency gates.
  Existing identity consumers use attributes, so a lazy full-stat upgrade can
  preserve their decisions. A proxy is not an `os.stat_result`: define/test
  tuple/index access and other supported consumers rather than claim automatic
  plug-in compatibility. Hydrate through an uncached stat-with-fallback helper,
  synchronize concurrent upgrades, and do not overwrite an existing full result
  or repopulate invalidated cache nodes from a stale scan. Retain the requested
  scan-method choice; unconditional scandir/default changes are not approved by
  this review. NTFS enumeration staleness is documented by Microsoft but is not
  proof of this particular System32 mismatch; preserve the unequal-result report.
  `python -m unittest core.tests.fs.test_local_scan -v` imported successfully
  with the documented PYTHONPATH, but all 19 tests skipped. A focused runtime
  probe confirmed the handle-closure test cannot assign to native iterator.close
  (read-only); use a tracking context-manager wrapper. Add concurrency, proxy
  protocol and upgrade-failure tests before treating this as verified. This
  record does not rewrite the selected design or implement the alternative.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Documented lazy-stat return-type, protocol, snapshot and error-timing
  differences. No current consumer was found to require the concrete result
  type; the attribute-only runtime probe passed the listed operations. This
  supports current consumer compatibility, not unconditional third-party
  compatibility. Recorded conditional public-query tests and a private-proxy
  refinement for stricter compatibility. No architecture adoption, application
  implementation or compatibility-break approval is implied by this update.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Added "Current Suggestion: Whole-Pane Reduction With Minimal Risk"
  under Alternatives, at the user's request, after tracing the 8.26 s profile to
  code and probing the candidate fixes. Key finding: the hidden-file filter
  (`QFileInfo.isHidden()`, 9.6 µs/entry, evaluated three times per row, twice
  on the Qt thread) is the largest removable cost, but a shortcut through the
  cached followed stat is wrong for junctions and drive roots (verified by
  probe); the correct cheap source is the entry's own attributes from the
  scandir scan (0.7 µs/entry including enumeration). Recommended order: scandir
  + `LazyStat` carrying `entry_attributes`, hidden filter with `QFileInfo`
  fallback, re-profile; committing the worker's rows is optional and needs a
  `FilterBar` guard against a real GUI-thread race. Also measured and ruled
  out for the "slow drive root" report: shell icon extraction (109 ms cold for
  37 entries), cache clearing (20 ms) and model teardown (30 ms). No
  application code changed; the selected design section is unchanged.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Added the user's priority of smooth navigation and operations from
  first usable paint, ahead of risky initial-load shortcuts. Traced post-render
  metadata batches and synchronous Qt publication; recorded a falsifiable
  hypothesis, separate input/commit measurements, conservative follow-ups and
  deterministic regression requirements. No production optimization or scan
  architecture selection is implied by this planning update.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Reproduced the post-render delay read-only with optional features off:
  an 8.442 s metadata tail, arrow-to-cursor p95 417 ms versus 1.4 ms settled,
  and 2.636 s in Qt commits including 1.991 s filtering. Actual cursor signals
  and paint timings supersede handler-return timings. Added these results and
  the diagnostic procedure; production code remains unchanged and the task
  remains pending implementation and its full interaction checks.