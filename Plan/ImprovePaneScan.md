# Improve Pane Scan

Status: Proposed design; review before implementation. The standalone benchmark
and its tests are implemented; the lazy prototype below is diagnostic-only.
Application scanning is unchanged.

## Task

Compare and support two local directory-scanning approaches:

- **Per-file scan:** `os.listdir()` for names, then `os.stat()` for metadata.
- **Optimized scan:** `os.scandir()` with reuse of enumeration metadata and
  selective `os.stat()` calls where complete metadata is required.

Make the approaches selectable while preserving filesystem-operation safety.
This task concerns only enumeration and metadata reuse, not other pane-loading
optimizations.

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
correctness/performance tests.

Excluded: recursive scanning, other pane-loading changes, new background
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

#### Isolated Whole-Pane Trial (2026_09_21)

Tested the alternative on the same 202,603-entry CelebAAligned folder through
real application startup, navigation and first populated paint. No application
source, saved settings or dataset files were changed. Each run used a fresh
Python 3.14.7 process, disposable settings and native Qt; QuickView remained
unimported and the uniform-row-height fix remained active.

The process-local prototype seeded ordinary entries with a slotted proxy holding
enumeration stat, path, optional full stat and an upgrade lock. Cache `query`
preserved an existing full result instead of unconditionally overwriting it.
Reparse entries stayed on the existing full-stat path. Identity accessed an
uncached stat-with-fallback, once under the lock. This does **not** solve stale
scan publication after cache invalidation, cancellation, or proxy protocol/API
compatibility; it is a quiet single-scan performance experiment.

Three modes, run in order `baseline`, `lazy`, `lazy-hidden`, then reverse order:

- `baseline`: existing listdir/stat and Qt hidden-file checks.
- `lazy`: provider-only lazy stat; existing hidden-file checks unchanged.
- `lazy-hidden`: same proxy plus an experimental Windows hidden-filter consumer
  reading the cached proxy's `st_file_attributes`. Reject the entry when
  `attributes & FILE_ATTRIBUTE_HIDDEN` is nonzero, instead of constructing
  `QFileInfo` and calling `isHidden()`. Non-proxy entries retain the Qt helper;
  identity access still performs the real stat described above.

No explicit warmups or OS-cache flush. Two observations per mode are too few for
a stable performance guarantee. Phase columns are arithmetic means; ranges show
both first-paint observations. Counter/proxy overhead is included; exhaustive
metadata/order verification and identity reads occurred after the timed paint.

| Mode | Worker preparation | Qt commit | First paint mean | First paint range | Path stats before paint | Qt hidden checks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 6.229 s | 2.481 s | 8.742 s | 8.342-9.142 s | 202,603 | 405,206 |
| Lazy provider | 5.030 s | 2.853 s | 7.917 s | 7.805-8.029 s | 0 | 405,206 |
| Lazy + hidden attributes | 3.496 s | 1.107 s | 4.634 s | 4.612-4.655 s | 0 | 0 |

Provider-only lazy stat saved 0.825 s (9%) on average, not the entire row setup.
It showed no Qt-commit improvement; the cause of its slower commit was not
isolated. Adding hidden-attribute reuse saved 4.108 s (47%, 1.89x overall) versus
baseline while still evaluating the filter 405,206 times. It did not remove the
second filter/sort pass or change model publication.

Memory is a tradeoff: mean working-set growth at first paint was 524.9 MiB for
baseline and 561.2 MiB for either lazy mode, approximately 36.4 MiB extra.
Process peak working set minus pre-navigation working set was 569.4 versus
605.8 MiB. These are process measurements, not isolated proxy allocation sizes;
the prototype retains enumeration results and per-entry paths/locks.

All six runs had identical fingerprints over names, directory status, normalized
size, exact modification time, Windows attributes, hidden classification and
displayed order. All 202,603 entries were visible, so this folder does not prove
behavior for hidden entries. Each lazy run also verified a sampled file's
device/inode/link count against real stat: two identity reads caused exactly
one path stat. This does not resolve the earlier System32 mismatch.

Validation: the process-injected prototype ran the 19 existing acceptance cases
plus three focused checks for concurrent identity access, failed upgrade, and
preserving an existing full stat. Result: **20 passed, two symlink-privilege
skips**, 0.268 s. The handle-closure fixture used a temporary context-manager
wrapper because native `iterator.close` is read-only; the tracked test file was
not changed. All three modes passed a small-folder startup/navigation/paint/
shutdown smoke before the dataset runs. Production still has no `LazyStat`;
these results are not a passing production implementation gate.

Local diagnostic artifacts are under `target/diagnostics/directory-load/`:
`lazy_probe.py`, `large-1-baseline.json` through `large-6-baseline.json` (mode in
each filename), and `lazy-summary.json`. They are ignored, not shipped source.
The batch required matching entry/visible-row counts, metadata fingerprints and
visible-order fingerprints across every run before producing its summary.

Reproduction commands from the repository root, with the existing application
Python on PATH and `$Dataset` set to the read-only folder under test:

```powershell
$probe = 'target/diagnostics/directory-load/lazy_probe.py'
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, *sys.argv[1:]], env=build._environment(), timeout=120).returncode)" "$probe" --self-test
$run = 0
foreach ($mode in @('baseline', 'lazy', 'lazy-hidden', 'lazy-hidden', 'lazy', 'baseline')) {
    $run++
    python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, *sys.argv[1:]], env=env, timeout=240).returncode)" "$probe" "$Dataset" --mode "$mode" --output "target/diagnostics/directory-load/large-$run-$mode.json"
    if ($LASTEXITCODE -ne 0) { throw "Probe failed: $mode" }
}
git diff --check -- Plan/ImprovePaneScan.md
```

Design implications, not adoption decisions:

- Here, **lazy means identity metadata on demand**, not progressive display of
  only visible rows. Enumeration, proxy/cache creation and initial row creation
  remain O(N); both filtering/sorting passes still precede first display.
- Evaluate hidden-attribute reuse explicitly alongside either scan architecture.
  It is an additional Core consumer change, not a provider-only benefit. A
  private cheap metadata accessor could support it while public `stat()` keeps
  returning a real full result; that compatibility refinement remains untested.
- Hidden reuse needs Windows hidden/system/dot-name fixtures, special-entry and
  error parity, and attribute-change refresh/invalidation tests. Nonlocal and
  unsupported cases must keep existing behavior; do not promise general parity
  from this all-visible, stable folder.
- Reusing the worker's prepared order at Qt commit is complementary, untested
  and outside this task's current scope. It requires sort/filter/navigation
  state validation, not changes to the lazy proxy.
- Resolve public return-object compatibility, cache publication races,
  cancellation and the additional memory cost before adopting lazy stat. The
  requested runtime choice and proposed listdir default remain unchanged.

#### Further Headroom (Analysis Only, 2026_09_21)

Going below the measured 4.634 s is plausible, not demonstrated. The remaining
mean time is 3.496 s worker preparation, 1.107 s Qt commit and approximately
0.031 s other dispatch/paint work. These are whole-phase measurements; they do
not establish how much of either phase is removable.

- **Reuse the prepared order.** [Model._initialize](../src/main/python/fman/impl/model/model.py)
  already filters and sorts the rows. Its Qt commit calls `update()`, which
  [filters and sorts again](../src/main/python/fman/impl/model/sorted_table.py).
  Reusing the prepared result could remove part of the 1.107 s commit and reduce
  the UI stall. Required row insertion/model notifications still cost time, so
  subtracting the entire commit would overstate the saving. Reuse needs matching
  navigation, sort, filter and row-data state; arbitrary plug-in filters may
  depend on external state. Fall back to recomputation when validity cannot be
  established. This is the strongest next experiment candidate, not approval
  to run it or an extension of the current scan scope.
- **Reduce per-entry Python work.** Lazy stat still builds cache entries,
  proxies, rows and cells for all 202,603 entries. Fewer allocations and repeated
  cache/path lookups might reduce worker time and the measured memory overhead.
  The optimized worker needs its own profile before choosing a change; the
  baseline profile cannot quantify its remaining allocation/lookup costs.
- **Defer more row construction.** Creating additional display cells only when
  needed could reduce upfront work, but this is a broader model design change.
  Only visible rows currently receive full-column preloading, so this proposal
  concerns the initial row/cell structures, not deferring that work a second
  time. Correct global sorting/filtering still requires examining all relevant
  entries; loading only the first 34 enumerated names is not equivalent.

Any future comparison must preserve displayed order, selection and cursor,
custom-column/filter behavior and stale-result rejection, and report memory as
well as first-paint time and Qt-thread blocking. No specific lower-time target
is justified by the existing measurements. Per the user's instruction, this
follow-up records analysis only: no further experiment or application change.

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
5. Measure production enumeration/metadata costs and memory in both modes.
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
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Added the remaining first-paint profile and isolated whole-pane lazy
  trial. On 202,603 stable entries, provider-only lazy stat averaged 7.917 s
  versus 8.742 s baseline; adding hidden-attribute reuse averaged 4.634 s with
  equal metadata and displayed order. Recorded approximately 36.4 MiB extra
  working set, 20 passing prototype checks and two symlink skips. Lazy identity
  alone does not eliminate repeated Qt hidden checks or make display progressive.
  Recommend evaluating a compatible cheap-metadata/hidden-consumer path before
  architecture adoption; proxy API, invalidation races, cancellation and special
  files remain gates. No production scan, scope, default or compatibility-break
  change is approved by this diagnostic review.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Clarified the hidden-attribute check and documented possible further
  gains from prepared-order reuse, reduced per-entry Python work and deferred
  row construction. Distinguished measured phase totals from unmeasured savings
  and recorded correctness boundaries. Documentation only at the user's request;
  no additional experiment, implementation or scope/default change.