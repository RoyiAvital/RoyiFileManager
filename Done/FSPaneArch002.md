# File System and Pane Architecture 002: Performance

Status: Implemented, awaiting re-review after Implementation Reviews 1 and 2
(IR1–IR7 addressed; see "Response to Implementation Reviews"). R03, R04, R05
and R10 implemented; R06 found already satisfied. R09 was implemented
separately in [Done/FSParser.md](../Done/FSParser.md) (native parser +
trusted `Listing`, released as `0.13.0`); R02 is superseded by it. R01 was
folded into R10 (its compact string key is the Python reference the native
key is compared against).

## Overview

Targets set by the developer on 2026_10_04: the pane must feel instant.

| Measurement | Today (`0.13.0`) | Target | Perceptual bar |
| --------------------------------------------------- | ---------------: | -------: | ---------------------------------- |
| Suite "Pane Load - Large Folder" (200k, long names) | 759 ms | < 500 ms | ~250 ms is the realistic outcome   |
| CelebA "First Populated Pane Paint" (202,603)       | 257 ms | ≤ 350 ms | already met; ~130 ms is reachable  |
| CelebA "Metadata Loading Complete"                  | 244 ms | ≤ 350 ms | already met; same levers           |

"Instant" in HCI terms is ≤ 100 ms perceived latency; 100–300 ms reads as
"fast". Both datasets have a floor of kernel enumeration + native scan +
Qt model reset/paint that no Python change moves: ≈ 130 ms for CelebA,
≈ 170 ms for the suite fixture.

### Where the time goes (measured 2026_10_04, 200k entries)

The two datasets differ only in their names: CelebA names are `000001.jpg`
(10 characters, one digit run); the suite fixture `flat-large-v1` has
77-character names on average, built from long stems (`common_` + 72 × `a`,
`ab` × 42, Unicode, several digit runs) plus a 24-hex token and an 8-digit
counter. That multiplies the key and sort stages, not the scan.

| Stage | CelebA | Suite fixture | Why | Lever |
| ------------------------------------------- | -----: | ------------: | ----------------------------------------------------- | ----------------------- |
| Record bytes / 64 KiB batches               | 21.6 MB / 330 | 48.5 MB / 740 | 7.7× longer names                                | —                       |
| Kernel enumeration                          |  25 ms | ~55 ms (scaled) | 2.2× the bytes                                      | none (OS)               |
| Native scan (`Columns` + trusted `Listing`) |  22 ms | ~35 ms (est.) | longer UTF-16 decodes                                 | done (R09)              |
| **Natural keys** (`Name.keys`)              | **94 ms** | **515 ms** | each key walks the whole name, 2–4 digit runs, Unicode | R01 (−20 %), **R10** (→ ~10 % ) |
| Sort                                        |   4 ms |  63 ms        | 25k names share a 79-char prefix; comparisons walk it | shorter keys (R01/R10)  |
| Cooperative worker sleep (1 ms per 4 ms)    | ~30 ms | ~100–150 ms   | proportional to projection length                     | R04                     |
| Hidden filter, row map                      |  18 ms |  ~18 ms       |                                                       | R05 (row map)           |
| Qt model reset + first paint                | ~80 ms |  ~80 ms       | 200k-row view reset                                   | profile `_commit`       |
| **Measured total**                          | **257** | **759**      | stages overlap on two threads; sums run high          |                         |

Key and sort numbers are from `natural_key` over the actual CelebA names and
over 200,000 names generated with the fixture's stems (`natural_key` list
comprehension and `sorted` with precomputed keys, medians of 3). The kernel
and scan numbers for the fixture are scaled from CelebA by record volume; the
fixture folder was not on disk at measurement time.

### What reaches the targets

| Step | Suite large | CelebA first paint | Note |
| --------------------------------------------- | ----------: | -----------------: | -------------------------------------------- |
| Today                                         |     759     |        257         | |
| R10 native `natural_key` (515 → ~40; 94 → ~10) |   ~285     |        ~170        | the only step that gets the suite under 500 |
| R04 yield cadence                             |   ~200     |        ~140        | removes most of the worker's sleep time     |
| R05 per-projection row map                    |   ~190     |        ~130        | |
| R01 compact keys instead of R10               |   ~650     |        ~225        | not sufficient alone for the suite target   |

R01 is the cheap first move and remains useful as the Python reference the
native key is compared against, but it cannot deliver < 500 ms on the suite:
the key stage is 68 % of that row and R01 removes only the tuple overhead,
not the per-character work. R03 and R06 do not affect first paint; they
target unchanged refreshes ("Refresh / Selection", 356 ms today → ~100–150).
After R10 + R04 + R05 the remaining first-paint cost is the floor plus the
Qt commit, which is the next thing to profile.

### Measured outcome (2026_10_04, after R03 + R04 + R05 + R10)

`python src/performancetest/run.py suite --test "pane.load.*" --test "refresh.*" --test "filter.*" --test "fuzzy.*"`,
medians of three fresh processes, native Qt, warm cache:

| Measurement | Before (`0.13.0`) | After | After IR fixes | Target |
| ----------------------------------------------------- | ----: | ----: | ----: | ------: |
| `pane.load.large` first paint (200k, long names)      |  759  |  239  | **262** | < 500 |
| `pane.load.large` complete                            |  —    |  226  |  247  | |
| `pane.load.medium` first paint (50k)                  |  —    |   83  |  —    | |
| `pane.load.small` first paint (256)                   |   38  |   31  |  —    | |
| `refresh.large` unchanged refresh, none / all marked  | ~356  | 127 / 132 | 123 / 128 | |
| `refresh.medium` unchanged refresh                    |  —    |   35  |  —    | |
| `filter.large` substring query paint / heartbeat gap  | 137 / 23 | 114 / 47 | 115 / 38 (17 on the other seven queries) | gap ≤ one frame |

"After IR fixes" is the final state: the sliced `natural_keys` calls (IR3)
hand the GIL to Qt during key building, which costs ~20 ms of wall time on
the large load (two `pane.load.large` runs: 257–266 ms) in exchange for a
66 → 12 ms worst Qt stall during that stage.

The remaining `pane.load.large` time is kernel enumeration (~55 ms), the
native scan (~35 ms), keys + sort (~130 ms for these prefix-heavy names,
mostly the sort, which holds the GIL) and the Qt reset/paint (~80 ms),
overlapping on two threads. The `refresh.large` 127 ms is enumeration + scan +
`Listing` comparison + one `dataChanged` over 200k proxy rows; no projection
or reset.

## Task

Make the snapshot pane cheaper where measurements show avoidable work: name-key
generation, native record parsing, no-change refreshes, the cooperative worker's
yield cadence and per-projection bookkeeping. Each candidate is a local change in
an existing owner with an isolated timing gate and an exact-parity test. Changes
that only save memory, or whose gain is within noise, are dropped.

Measurements below were taken on the 202,603-entry reference folder (warm cache,
Python 3.14.7, Windows 11) during the FSPaneArch001 and CodeReview004 reviews.
They size the opportunity; acceptance requires fresh before/after runs.

| Candidate | Owner | Measured cost today | Expected effect |
| --- | --- | ---: | --- |
| R01 Compact name-sort keys | `Name.keys` | 131 ms key build per sort/rescan | Fewer per-entry tuples; gate on measured runtime |
| R02 Selective native record unpacking | `records()` | — | **Superseded**: `records()` is no longer on the scan path (R09 / FSParser) |
| R03 No-change refresh fast path | `ListingModel._receive` / `_commit` | ~300 ms projection + full model reset per unchanged rescan | Skip projection and reset; keep notifications |
| R04 Cooperative worker yield cadence | `LatestJobs._run` | 1 ms `sleep` every 4 ms ≈ 113 ms asleep per 300 ms projection | Yield per ~16 ms frame or `sleep(0)` |
| R05 Per-projection row map | `project()` / `Projection.rows` | 12 ms and ~10 MB per keystroke, sort, refresh | Build only for entries the view asks about |
| R06 Unchanged-rescan identity map | `reconcile()` fast path | 20 ms identity `dict` per unchanged rescan | Sentinel meaning "same order" |
| R09 Native record parser (C, abi3) | `records()` and column building in the Windows scanner | 183 ms parse + ~85 ms list/`Listing` build of a 295 ms scan; kernel enumeration itself is 27 ms | **Done** in [Done/FSParser.md](../Done/FSParser.md): post-kernel scan 279 → 22 ms at 202k |
| R10 Native natural keys (C, abi3) | `natural_key` / `Name.keys` | 94 ms (CelebA) to 515 ms (suite fixture) per sort/rescan | **Done**: `_fsparser.natural_keys` in the same module as R09; 7 ms (CelebA) / 67 ms (fixture) at 200k, parity with Python `natural_key` over every code point |
| R07 Revisit from a bounded listing cache | — | — | **Refused by the developer**: no caching layer; make the simple path fast instead |
| R08 Reuse sort keys across rescans | — | — | **Refused by the developer**: same reason; no cross-snapshot state |

Cost split of a first visit at 202,603 entries (probe, warm): kernel
enumeration 27 ms, Python record parsing 183 ms, list appends and `Listing`
construction ~85 ms, natural keys 97 ms (`str.lower` alone is 8 ms), sort
8 ms, hidden filter 6 ms, row map 12 ms, model reset and paint ~80 ms. Pure
Python (R01–R06) can take 583 ms toward ~400 ms. Below that, the single
largest removable block is Python-side record parsing, which is what R09
addresses; natural keys are the second.

## Scope

- Included: R01–R06 as independent changes to the listing pipeline, each with
  its own gate; the loaded-input measurement protocol needed to judge R03–R05;
  R09 as the one native candidate, subject to the build/fallback conditions in
  its section.
- Excluded: caches of any kind across snapshots or navigations (R07, R08
  refused by the developer); new matchers or processes; provider rewrites;
  API changes; memory-only changes; persisted indexes; the environment/validation
  backlog listed under "Open Adoption Gates" in
  [Done/FSPaneArch001](../Done/FSPaneArch001.md) (not duplicated here).
- Related work kept elsewhere: Python 3.15 `take_bytes()` for the identity
  buffer in [TODO Performance](../TODO.md#performance); Qt role batching in
  [PyQt6 Migration](PyQt6Migration.md); review-time dispositions of N05–N08 in
  [CodeReview099](CodeReview099.md), whose N05 next-design requirements apply
  to R03.
- Compatibility: public plug-in API, immutable snapshots, query
  syntax/ranking/highlights, identity rules, cursor/mark restoration, authoritative
  operation checks, cancellation and stale-result rejection are unchanged.

## Design

### R01: Compact Name-Sort Keys

Owner: `Name.keys` in [Core columns](../src/main/resources/base/Plugins/Core/core/__init__.py);
key function [natural_key](../src/main/python/fman/impl/util/natural.py).
Replace `(is_dir ^ ascending, natural_key(name))` with
`('1' if is_dir ^ ascending else '0') + natural_key(name)`. `'0' < '1'` orders
like `False < True`, so directory grouping and `reverse=not ascending` are
unchanged. Implemented as the shape of the R10 key; the Python expression is
the fallback when `_fsparser` is unavailable (non-Windows) and the reference
in the parity tests.

### R02: Selective Native Record Unpacking

Owner: `_RECORD` and `records` in the
[Windows scanner](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py).
Replace `Struct('<IIqqqqqqIIII16s')` with `Struct('<I4xq8xq8xq8xII4xI16s')`:
same 88-byte header and offsets, unpacking only next offset, creation time,
last write, end of file, attributes, name length, reparse tag and file ID.
Bounds checks, UTF-16LE `surrogatepass` decoding, reparse handling, scope checks
and fallback are untouched. Gate: byte-identical `Listing` on replayed buffers;
replay time not slower. A measured speedup is welcome but not required — the
change removes work without adding any.

### R03: No-Change Refresh Fast Path

Owner: `ListingModel._receive` (scan branch) and `_commit` in the
[listing model](../src/main/python/fman/impl/model/listing.py); view side in
[`_restore_snapshot_state`](../src/main/python/fman/impl/view/__init__.py).
Every mutation notification, `Ctrl+R` and post-operation refresh produces a new
`Listing`, so an unchanged folder is re-sorted, re-filtered, reset and its
selection restored. `Listing == Listing` costs 10.7 ms at 202k entries.

Design: on the scan worker, compare the new listing with the one the model
displayed when the scan started; if equal and the filter/search/sort/column
revision is unchanged, deliver a "no change" result. The model then emits the
observable notifications a commit would (`transaction_ended`, `files_changed`,
`all_rows_loaded`, `committed` with the current projection) and resolves a
pending cursor target, but performs no projection and no `beginResetModel`.
Any pending column callback or navigation callback forces the normal commit.
The requirements in CodeReview099 "N05 Next-Design Requirements" are the
checklist. Gate: unchanged-folder refresh completes with no `modelReset`, the
same signals, cursor/marks/scroll/QuickView untouched; changed metadata still
updates.

As implemented: `_request_scan` captures `self._listing` on Qt; the worker
returns that object when `scanner(check) == current` (dataclass equality,
~11 ms at 202k, on the scan worker but GIL-held). `_receive` sees
`result is self._listing` and:

- does nothing when `_projecting` is set (a projection job was submitted and
  has not delivered a result or error yet; it will commit and notify; this
  also covers pending `start`/`set_columns` callbacks, which always bump the
  revision and submit);
- runs the normal `update()` when `_revision != _committed_revision` with no
  job pending (the last projection failed; the reload retries it, IR1), when
  the displayed listing is not that object, no projection was committed yet,
  or the sort column has `keys_depend_on_external_data` (`Size` with
  directory sizes);
- otherwise calls `_refresh_unchanged()`: `about_to_commit`, text-cache drop
  plus one `dataChanged` over the visible rows (cell texts may read external
  data; `DirectorySize` uses `pane.reload()` to redraw), `committed` with the
  stored `_last_projection`, `sort_order_changed`, `transaction_ended`,
  `files_changed`, `all_rows_loaded`.

`_projecting` is set in `update()` when a job is submitted and cleared in the
`view` branch of `_receive` for the current revision, on success or error;
stale results do not clear it because a newer job is still pending.

Behaviour change accepted with the developer's goal: an unchanged refresh no
longer drops marks on identity-less providers, closes an open rename editor
or cancels a drag, because the rows did not change.

### R04: Cooperative Worker Yield Cadence

Owner: `LatestJobs._run` with `cooperative=True`. The check sleeps 1 ms after
each 4 ms of work; `time.sleep(0.001)` measured ~1.5 ms on Windows, so a
300 ms projection spends ~113 ms asleep. Design: yield every ~16 ms, and use
`sleep(0)` (releases the GIL to a waiting Qt thread without the timer wait) or
keep `sleep(0.001)` at the longer cadence. Cancellation checks keep their
positions. Gate: projection completion time drops on the reference folder;
idle and loaded arrow-to-paint p95 and the Qt heartbeat gap from the
interaction benchmark do not regress.

As implemented: `YIELD_INTERVAL = .016` with `sleep(.001)`. The `sleep(0)`
variant was measured and rejected: on `filter.large` it cut paint time most
(137 → 110 ms) but the Qt heartbeat gap rose from 11–23 ms to 27–85 ms, i.e.
it does not reliably hand the GIL to the Qt thread. 16 ms + `sleep(.001)`
gives 115 ms paint and 17 ms gaps; 8 ms + `sleep(.001)` 122 ms and 16 ms
gaps (the 10 ms heartbeat timer bounds the resolution). Cancellation checks
before and after the yield are unchanged.

### R05: Per-Projection Row Map

Owner: `project()` building `{entry: row}` for every visible entry; readers are
the cursor, the preferred-prefix entry and the marked entries in
`_restore_snapshot_state`. Design: pass the entries the view will ask about
(cursor, preferred, marks — captured on Qt when the projection is requested)
into `project()` and build the map for those only; when marks exceed a fixed
threshold (e.g. 1,024) build the full map as today. No lazy linear lookups on
the Qt thread. Gate: restoration identical for none/few/all marked; projection
time and allocation drop for the common case.

As implemented: the file view installs `snapshot_state_provider` on the proxy
model, which forwards it as `state_provider` to each `ListingModel`.
`update()` calls it on Qt and passes `wanted` (cursor entry + marks, in the
`previous` listing's index space; the pending search-restore state when one
is set) to `project()`. With ≤ `ROW_MAP_LIMIT` (8) entries the worker locates
each with `tuple.index` (≤ 0.9 ms each at 200k; measured against 13.8 ms for
the full dict) after mapping through `remap`; above that it builds the full
map. `Projection.complete` records which; `Projection.row_of()` serves the
view and, for a partial map, locates an entry the view asks about that was
not requested (cursor moved while the projection ran) with one `index` call
and remembers it. The preferred-prefix entry is always in the map. The view
calls `Projection.complete_rows()` (one linear pass) before restoring more
than `ROW_MAP_LIMIT` marks against a partial map, and skips restoration
entirely when the committed projection is the one it already restored (the
R03 path), which avoids the quadratic case first seen in `refresh.medium`
(49,999 marks × `tuple.index` = 6 s).

### R06: Unchanged-Rescan Identity Map

Owner: `reconcile()` fast path in [fman/listing.py](../src/main/python/fman/listing.py).
When names, identities and creation times are equal it still builds
`{i: i}` over all known entries. Design: return a small identity-mapping
object whose `get`/`__getitem__` return the key when the entry has a known
identity; the view only calls `remap.get(entry)`. Gate: identical restoration;
20 ms and the dict allocation removed at 202k.

Found already satisfied: `reconcile()` returns `None` ("every entry keeps its
index") when names, identities and creation times are equal and every
identity is known, which is the case for the native Windows scanner. The
`{i: i}` dict is only built when some identities are unknown. No change.

### R07 and R08: Refused

R07 (revisit from a bounded listing cache) and R08 (reuse sort keys across
rescans) were proposed in review and **refused by the developer**: no caching
mechanism and no cross-snapshot state. The preferred direction is a simple
path fast enough that no such edge-case logic is needed; see R09.

### R09: Native Record Parser

Designed, reviewed and implemented in [Done/FSParser.md](../Done/FSParser.md),
which is the authoritative description. In short: `Columns`/`parse_records` in
[fsparser.c](../src/main/c/fsparser.c) (limited API, `abi3`) parse the 64 KiB
`FileIdExtdDirectoryInfo` batches into the snapshot columns; the scanner is
native-only (no pure-Python fallback, no API version check), the committed
binary is paired with its source by SHA-256 (`fsparser.sha256`, verified by
`build.py test`/`freeze`/`package`), and the toolchain is llvm-mingw, not
MSVC. The C code holds the GIL (it builds Python objects); the scan runs on
the scan worker. Measured post-kernel scan 279 → 22 ms at 202,603 entries.
The original R09 proposal text (GIL release, fallback, MSVC) is superseded
and was removed from this document.

### R10: Native Natural Keys

Owner: `natural_keys(names, is_dir, ascending) -> tuple[str]` in
[fsparser.c](../src/main/c/fsparser.c), called by `Name.keys` in
[Core columns](../src/main/resources/base/Plugins/Core/core/__init__.py).
Same module, toolchain, hash pairing and mandatory scripts as R09
([src/main/c/README.md](../src/main/c/README.md)); no separate binary.

Design: one key per entry, `'1'`/`'0'` for `is_dir ^ ascending` followed by
`natural_key(name)`. Lower-casing is done in C for ASCII names and through
`str.lower()` otherwise, so Unicode case mapping is Python's. Digits are the
Unicode `Nd` characters (what `\d` matches): a 76-run table of decimal
starts generated from `unicodedata` for Unicode 16.0.0, exposed as
`UNICODE_VERSION` and asserted equal to `unicodedata.unidata_version` by the
tests. Runs are zero-stripped and encoded exactly like the Python function
(`'0' + zfill(6)` up to six digits, else `'1' + '1' * len(L) + '0' + L +
digits`). Keys whose code points fit Latin-1 are built with
`PyUnicode_DecodeLatin1`; others with `PyUnicode_DecodeUTF32(...,
"surrogatepass")` so lone surrogates in names survive. `Name.keys` falls back
to the Python expression when `_fsparser` is `None` (non-Windows). Gate:
equality with the Python reference over every code point and the edge-name
set; measured 94 → 7 ms (CelebA names) and 515 → 67 ms (suite fixture names)
at 200k, sort 63 → 66 ms unchanged (shorter keys were not the lever; the
prefix-heavy names are).

GIL bound (IR3): the C loop holds the GIL for the whole call, so `Name.keys`
calls it in slices of `_NATIVE_KEY_SLICE = 4096` names and concatenates;
between calls the interpreter's switch interval hands the GIL to Qt. Probe
(worker builds keys for the 200,000 fixture names, 2 ms Qt timer on the main
thread, three alternating runs): single call 60–62 ms with worst Qt gap
66–67 ms; 4096-name slices 67–68 ms with worst gap 11–13 ms (8192: 12–16 ms).
Zero-length names (possible through display labels) use a one-element
scratch buffer; `PyUnicode_AsUCS4` rejects a NULL buffer even for `""` (IR2).

### Measurement Protocol

Use the existing [pane benchmark](../src/integrationtest/python/fman_integrationtest/pane_rendering_benchmark.py)
and the [performance suite](../src/performancetest/README.md). Component gates
(R01, R02, R06) use seven alternating warmed baseline/variant samples in two
batches on the seeded flat fixture (`fixtures.py`, revision 1; the recorded
fixture specification is part of every result) and report median and spread.
Pipeline gates (R03–R05) add a fixed-rate input stream through active work (no
settled padding), the reference folder, two large panes, and QuickView/extended
status off and on, three fresh-process repetitions, native Qt, warm caches.
Report query, opening and input latency separately; keep profiling runs apart
from timing runs. Define the input-stream protocol and its command before
first use.

### Ownership and Failure Behavior

Workers receive immutable inputs and return `Listing`/projection values;
models and widgets stay on Qt. Bounded work lanes, cooperative checkpoints,
stale-result rejection and "keep the previous valid pane on failure" are
unchanged. No settings, persistence or new failure paths.

## Alternatives

- Leave each path as is when its gate fails; none of R01–R06 is required for
  correctness.
- Caches, a new matcher, native extensions or process offloading: deferred
  until profiling shows a need; each needs its own correctness, cancellation
  and resource design.
- R03 as a bare identity short-circuit (`result = self._listing`): rejected;
  it suppresses observable notifications and pending-cursor resolution.
- R05 as a lazily materialised map with `visible.index()`: rejected as the
  only mechanism; linear lookups on the Qt thread. Kept only as the bounded
  fallback for entries not requested up front, with `complete_rows()` above
  `ROW_MAP_LIMIT` lookups.
- R04 with `sleep(0)`: rejected after measurement (Qt heartbeat gaps up to
  85 ms).

## Runtime Effects

- R01/R06 remove temporary objects on the worker; no new state, I/O, timers
  or threads. R02 was superseded; R06 needed no change.
- R03 adds one `Listing` equality per rescan on the scan worker. The
  comparison is C tuple/bytes equality that holds the GIL: sub-millisecond for
  ordinary folders, a ~11 ms Qt stall bound at 202k entries (under one frame;
  it is not free to the Qt thread). It saves the projection and the model
  reset when the folder is unchanged.
- R04 changes only how often the projection worker yields (every 16 ms with
  `sleep(.001)`); measured worst Qt heartbeat gap 17 ms on the 200k filter
  benchmark.
- R05 reads the view's cursor/marks on Qt per projection request (cheap: the
  selection ranges are already there) and builds the requested-entry set only
  when there are at most `ROW_MAP_LIMIT` marks; with more, the worker builds
  the full map as before and nothing is built on Qt (IR6). Saves ~14 ms and
  ~10 MB per projection in the common case.
- R09: see Done/FSParser.md. One native module load at first scan; the C
  parser holds the GIL while building Python objects (bounded per 64 KiB
  batch), no new threads, timers or state.
- R10: `Name.keys` holds the GIL for at most one 4096-name slice (~1.5 ms at
  fixture name lengths) between interpreter switch points; total key cost
  7 ms (short names) to 68 ms (long names) at 200k on the projection worker.
- Disabled paths and startup are unaffected; diagnostics remain opt-in.

## Tests

Run from the repository root in the existing environment, narrowest regression
first after each edit:

```powershell
python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-B', '-m', 'unittest', 'fman_unittest.test_listing', 'core.tests.fs.test_columns'], env=build._environment()).returncode)"
python -B -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable, '-B', '-m', 'unittest', 'fman_integrationtest.test_qt.TableIT', 'fman_integrationtest.test_qt.SnapshotFilterBarIT', 'fman_integrationtest.test_qt.SearchFileMetadataIT', 'fman_integrationtest.test_qt.QuickViewImagesIT'], env=env, timeout=180).returncode)"
python src/performancetest/run.py suite --test 'filter.*' --test 'fuzzy.*' --test recursive.tree --test 'refresh.*'
```

- R01: sorted-index parity both directions; mixed files/directories, empty and
  single listings, ties, leading zeros, Unicode decimal digits, long digit runs.
- R02: 88-byte header, every yielded field and the final `Listing`; multi-record
  batches, malformed offsets/lengths, Unicode names, reparse fallback,
  cancellation, handle cleanup on failure.
- R03: unchanged reload emits the same signals with no reset; changed
  size/mtime/attribute updates; pending cursor target resolved; concurrent
  filter/column change forces a normal commit; QuickView image retained.
- R04: cancellation still observed; heartbeat and arrow-to-paint p95 unchanged
  or better.
- R05/R06: cursor/marks/scroll restoration identical for none, few, all marked
  and after a rename; `preferred` behaviour unchanged.
- R09: field-by-field parity of C and Python parsers on reference-folder and
  fixture buffers; fuzzed malformed buffers raise in both; forced import
  failure exercises the fallback; packaged artifact loads the extension;
  scan timing gate.
- Manual: ascending/descending Name sort, hidden-file toggle, refresh with
  none/one/all marked, held navigation keys during sort/filter/refresh,
  navigation away and window close while work is pending.

## Implementation Steps

1. Capture an unchanged baseline with the pane benchmark and the suite; record
   the exact commands and fixture specification.
2. R02, then R01: parity tests first, then the component gate; drop R01 if its
   isolated runtime gain is not confirmed.
3. R06, then R05: restoration parity tests, then projection timing.
4. Define and add the fixed-rate input protocol; take the R03/R04 baseline.
5. R04, then R03 against the CodeReview099 N05 checklist; run the Qt gates and
   the interaction benchmark after each.
6. R09 after developer approval of the toolchain addition: C source, parity
   and fuzz tests, fallback test, build integration, packaged load check.
7. Record results, rejected candidates and unrun checks; update the changelog
   for retained changes and move this document to `Done/`.

Executed order (2026_10_04): R09 separately (FSParser); then R10 (C,
parity tests, hashes), `Name.keys` switch (R01 shape as fallback), R04, R05,
R03 with the Qt integration tests after each, R06 verified as satisfied, the
suite's refresh benchmark taught the no-change path, and the measurements
above. Step 4's fixed-rate input protocol was not added; the suite's existing
heartbeat and queue probes were used for the R04 gate.

## Acceptance Criteria

- Each retained candidate passes its parity tests and its isolated gate against
  a fresh baseline; component savings are not summed into a whole-app claim.
- Query semantics, record fields, fallback behaviour, cursor/mark restoration,
  signal contracts, Qt-thread ownership and the public API are unchanged.
- No new dependencies, settings, persistence or disabled-feature work; memory
  is reported separately and does not qualify a change on its own.
- Commands, results, dropped candidates and unrun checks are recorded.

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

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Scoped to two timing-positive candidates. Compact-only attribution
  and native Qt/complete-pane validation remain required before acceptance.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Consolidated the allocation-review candidates into this canonical
  performance plan. Removed historical measurements, superseded targets and
  unrelated validation backlog; retained relevant investigations, behavioral
  constraints, acceptance gates and both tasks' reviewer history. Planning only.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Rewrote the document as a candidate list at the user's request.
  Verified R01's prefix ordering and R02's padded struct (88 bytes, eight
  values in the current order) against the code. Replaced the open-ended
  R03/R04 investigations with four measured candidates from earlier reviews
  (no-change refresh path keeping notifications, worker yield cadence,
  per-projection row map, unchanged-rescan identity map), relaxed R02's gate to
  parity plus non-regression, pointed the validation backlog back to
  Done/FSPaneArch001 and the N05 checklist to CodeReview099 instead of
  duplicating them, and corrected the fixture reference. Planning only.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Reviewed the candidate list against the question "is there a
  low-risk way to greatly improve large-folder rendering and navigation".
  Finding: R01–R06 are sound but incremental; the pure-Python first-visit
  floor (scan 180–290 ms + reset/paint ~80 ms) limits them to roughly
  583 → 400 ms. The large, low-risk gains are on the frequent paths: revisits
  and refreshes. Added R07 (per-window bounded LRU of immutable listings,
  painted immediately on revisit while the normal scan runs and R03 converges;
  reuses the existing `listing=` start path, so correctness never depends on
  the cache) and R08 (copy sort keys for entries `reconcile` already matched,
  compute only the remainder). Expected: revisits 583 → ~80 ms, changed-folder
  refresh −130 to −545 ms of key work. Both depend on R03 and are sequenced
  after it. Explicitly not recommended as "low risk": C/Cython record parsing,
  dropping identities on first scan, painting in enumeration order before
  sorting, persisted indexes. Planning only.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Developer refused R07 and R08 (no caching, no cross-snapshot
  state); recorded as refused and removed from scope. Answered the native
  question with a measured cost split of the first visit (kernel enumeration
  27 ms, Python record parsing 183 ms, list/`Listing` build ~85 ms, natural
  keys 97 ms, reset/paint ~80 ms): the single largest removable block is the
  Python record parser. Added R09: one hand-written limited-API (`abi3`) C
  function `parse_records(buffers)` returning the columns, GIL released,
  pure-Python fallback kept, parity/fuzz gate, conda-forge MSVC toolchain in
  the build. Expected scan 295 → ~50 ms, first visit ~250 ms with R01–R06.
  `natural_key` is the second candidate for the same treatment, deferred until
  R09 proves the toolchain. Planning only.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Added the Overview with the developer's targets (suite large pane
  load < 500 ms; CelebA ≤ 350 ms, already at 257/244 ms) and a measured
  per-stage breakdown of both datasets. The suite fixture's 77-character,
  prefix-heavy names make natural keys 515 ms and the sort 63 ms against 94
  and 4 ms on CelebA; that stage is 68 % of the 759 ms row, which is why R09
  moved it only −200 ms. Marked R09 done (FSParser) and R02 superseded; added
  R10, a native `natural_key` built like R09, as the only step that reaches
  the suite target (→ ~285 ms), with R04 and R05 taking it to ~190 ms and
  CelebA to ~130 ms. Planning only; no application code changed.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Changes requested. Reproduced failed-projection refresh starvation,
  first-empty-label failure and native-key Qt blocking; the documented column
  test gate also fails. See Implementation Review below. Application code unchanged.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Changes requested (Implementation Review 2). IR1–IR4 still open on
  the unchanged binary; IR2 and IR4 re-reproduced. Status and R09 text are
  stale against Done/FSParser.md (IR5). R05 builds a discarded frozenset on
  Qt per update, ~8 ms at 200k marks (IR6). R03's equality is a GIL-held
  stall of ~11 ms (IR7). Suggested slice-wise `natural_keys` calls for IR3.
  Only this document changed.

## Implementer

### 2026_10_04 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implemented R10 (`natural_keys` in `fsparser.c`, `Name.keys`
  switched, binary and `fsparser.sha256` regenerated), R04 (16 ms cadence,
  `sleep(.001)` kept after the `sleep(0)` heartbeat regression was measured),
  R05 (requested-entry row map with `Projection.row_of`/`complete_rows`,
  view-provided state) and R03 (`_refresh_unchanged` with eligibility
  checks). R06 verified as already satisfied; R01 folded into R10. Suite
  `pane.load.large` 759 → 239 ms (target < 500), unchanged `refresh.large`
  ~356 → 127–134 ms. Decisive checks: full code-point parity of the C key,
  `fman_integrationtest.test_qt` (237 tests) green, validator clean, suite
  refresh benchmark updated for the no-change path.

## Validation Results

Build and publish (llvm-mingw 20260922, `$prefix = python -c "import sys; print(sys.base_prefix)"`):

```powershell
New-Item -ItemType Directory -Force target\native | Out-Null
& "$llvm\bin\clang.exe" --target=x86_64-w64-mingw32 -O2 -Wall -Wextra -shared -static -DPy_LIMITED_API=0x030C0000 "-I$prefix\include" src\main\c\fsparser.c "$prefix\libs\python3.lib" -o target\native\_fsparser.pyd
python src\main\c\write_hashes.py --from target\native\_fsparser.pyd
python src\main\c\check_hashes.py
```

No compiler warnings. Sidecar: source `c77d846e…`, binary `18587c3e…`
(69,120 bytes; the IR2 fix changed one function, previous pair
`cb1e879a…`/`b27ee1a1…`).

Focused tests (all pass; 4 expected skips are the Python-version/NTFS
fixtures in `test_fsparser`/`test_local`):

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-X', 'dev', '-m', 'unittest', 'fman_unittest.test_listing', 'core.tests.fs.test_local', 'core.tests.fs.test_fsparser', 'core.tests.fs.test_columns', 'fman_unittest.test_ui_elements'], env=build._environment(), timeout=300).returncode)"
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt'], env=env, timeout=2400).returncode)"
```

189 unit tests OK (4 skips), including `core.tests.fs.test_columns` (IR4:
assertion updated to the string prefix, plus a new sliced-call/empty-label
parity test) and `NaturalKeysTest.test_empty_names_in_any_position` (IR2).
`test_qt`: 236 OK, including `test_unchanged_refresh_notifies_without_reset`,
`test_unchanged_refresh_resolves_missing_cursor_request` and
`test_unchanged_refresh_retries_failed_projection` (IR1: an injected
`Name.keys` failure followed by an unchanged reload commits and settles). Two
existing tests were updated for the intended behaviour change: an unchanged
refresh keeps marks on identity-less providers and keeps the rename editor
open.

Mandatory native-parser scripts after the C change:

```powershell
python src\misc\validate_fsparser.py
python src\misc\benchmark_fsparser.py "<reference folder>" --repeat 5
```

Validator: all shapes, the native scan and `os.stat` agree (13 privilege
skips for symlinks and one control-character name, as before). The validator
previously flagged directory `mtime_ns` lagging `lstat` by ~1 ms on freshly
filled folders; this is NTFS updating the parent's index lazily, not a parser
difference (Python and native parsers agreed), and the check now tolerates a
0–2 s lag for folders. Gauge: scan after kernel Python 279.8 → native
24.7 ms, parity identical for all shapes; unchanged from FSParser.

Performance suite (results in `target/performance/runs/`, not tracked):

```powershell
python src/performancetest/run.py suite --test "pane.load.*" --test "refresh.*" --test "filter.*" --test "fuzzy.*"
```

See "Measured outcome" in the Overview. The R04 A/B runs (`sleep(0)`,
8 ms, 16 ms) used `--test filter.large` with the constant edited in place.
The IR3 gate used a throw-away probe (worker builds `Name().keys` for the
200,000 fixture names; 2 ms `QTimer` on the main thread; three alternating
runs of single call / 8192 / 4096 slices); its numbers are in the R10 design
section.

Not run: the complete `python build.py test` suite (per policy), `build.py
freeze`/`package`, and the interaction benchmark's arrow-to-paint p95 (the
suite's `navigation.*` probes within `pane.load.*` passed; medians were not
compared against a stored baseline because none is tracked).

## Implementation Review (2026_10_04)

Changes requested. Review of R03, R04, R05 and R10 against the current paired
source/binary (`cb1e879a...` / `b27ee1a1...`). No application fixes made.

### Findings

- **IR1 [P2]: Failed projections prevent unchanged-refresh recovery.**
  [ListingModel._receive](../src/main/python/fman/impl/model/listing.py)
  equates `_revision != _committed_revision` with an in-flight projection,
  but view-error delivery leaves that inequality after the job has finished.
  In a real pane, one injected `Name.keys` failure left revisions `(2, 1)`;
  a subsequent successful, unchanged reload submitted zero projections and
  stayed at `(2, 1)` with scanning/dirty both false. An explicit `update()`
  recovered to `(3, 3)`. Track an actually pending projection and allow reload
  to retry failed work; cover retry and completion notifications.
- **IR2 [P2]: An empty first display label raises SystemError.**
  [natural_keys](../src/main/c/fsparser.c) leaves the scratch pointer NULL
  for a zero-length first name, then passes it to `PyUnicode_AsUCS4`.
  `natural_keys(('',), (False,), True)` fails, while `('a', '')` succeeds.
  This also fails through `Name.keys` on a valid
  `Listing.create('probe://', ('entry',), labels=('',))`, so it is not limited
  to invalid filesystem names. Handle the zero-length copy and test an empty
  first label through both the native function and the column API.
- **IR3 [P2]: Native keys add a whole-folder, GIL-held Qt stall.**
  The [natural_keys loop](../src/main/c/fsparser.c) processes the complete
  tuple without releasing the GIL or returning to a cancellation checkpoint.
  Three alternating worker runs on the actual 200,000-file suite fixture,
  with a 2 ms Qt timer, measured median key time 481.76 ms Python versus
  60.02 ms native, but median worst Qt gap 10.98 ms versus 60.35 ms.
  Faster completion does not satisfy the once-per-frame responsiveness claim.
  Use bounded native batches with cooperative/cancellation checkpoints, or
  a design that safely releases the GIL without calling Python APIs unlocked.
  These are isolated key-stage timer results, not whole-pane arrow-to-paint p95.
- **IR4 [P2]: The documented column regression gate fails.**
  [NameTest.test_numeric_boundaries_unicode_and_arbitrary_lengths](../src/main/resources/base/Plugins/Core/core/tests/fs/test_columns.py)
  still asserts boolean `key[0]` values; R01/R10 now return string prefixes.
  The focused 110-test run has one failure here. Update this assertion for the
  intended key representation while preserving the numeric, Unicode, length
  and directional-order checks; do not skip the test.

### Review Validation

Run in the existing Python 3.14.7 environment:

```powershell
python -B src/main/c/check_hashes.py
python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-B', '-X', 'dev', '-m', 'unittest', 'fman_unittest.test_listing', 'core.tests.fs.test_fsparser', 'core.tests.fs.test_columns'], env=build._environment(), timeout=180).returncode)"
python -B -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m', 'unittest', 'fman_integrationtest.test_qt.SnapshotFilterBarIT', 'fman_integrationtest.test_qt.SortedFileSystemModelIT', 'fman_integrationtest.test_qt.QuickViewImagesIT', 'fman_integrationtest.test_qt.DirectorySizeIT'], env=env, timeout=300).returncode)"
```

- Hash pairing passes. Focused unit tests: 109 pass, one failure (IR4), no
  skips. Focused Qt tests: 83 pass; expected offscreen `propagateSizeHints`
  warnings. The full-code-point native parity test passes but misses IR2.
- Isolated `python -B -` probes used `build._environment()` and subprocess
  timeouts: first-empty/later-empty native names and valid empty labels;
  a `SnapshotFilterBarIT` pane with one injected key error, completed reload
  and explicit-update control; and worker key construction against a Qt timer.
  All three probes reproduced IR1-IR3 without editing application source.
- Heartbeat procedure: enumerate `flat-large-v1/data` before timing; construct
  native or Python-reference keys on a worker; sample a main-thread
  `QCoreApplication` timer every 2 ms; run three alternating pairs. Native
  worst gaps: 60.78, 60.35, 60.30 ms; Python: 9.99, 11.00, 10.98 ms.
- Still unverified: fixed-rate loaded arrow-to-paint p95, two large panes with
  QuickView/status enabled, and explicit R05 selection-change-during-projection
  coverage. No full suite, benchmark rerun, native rebuild, freeze or package.

## Implementation Review 2 (2026_10_04)

Changes requested. The paired source/binary is unchanged since the first
implementation review (`cb1e879a…` / `b27ee1a1…`), and IR1–IR4 are still open:
`natural_keys(('',), (False,), True)` still raises `SystemError` (IR2), and
`core.tests.fs.test_columns` still fails on the boolean `key[0]` assertion
(IR4). The R03/R05/R10 code and the new binary are uncommitted.

- **IR5 [P2]: The document overstates completion and describes removed
  behaviour.**
  - Status says "Implemented" and Validation Results "all pass", while IR1–IR4
    are open and the plan's own focused command (`core.tests.fs.test_columns`)
    fails.
  - R09 and Runtime Effects still describe `parse_records` releasing the GIL,
    a pure-Python fallback, an `API_VERSION` check and the MSVC toolchain.
    Done/FSParser.md removed all four: native-only scanner, hash pairing,
    llvm-mingw.
  - Update Status to "changes requested", replace the R09 design text with a
    pointer to Done/FSParser.md, and add `core.tests.fs.test_columns` to the
    recorded focused run.
- **IR6 [P3]: R05 builds the requested-entry set on Qt for every `update()`.**
  `update()` calls `snapshot_state()` and then
  `frozenset((cursor, *marks))` on each sort, filter keystroke or rescan.
  With all rows marked, the frozenset is discarded because
  `len(wanted) > ROW_MAP_LIMIT` selects the full map anyway. Measured for
  200,000 marked entries: building the mark set 2.3 ms plus the frozenset
  5.9 ms, about 8 ms of Qt time per keystroke that did not exist before.
  Check `len(state[3]) <= ROW_MAP_LIMIT` before building `wanted`.
- **IR7 [P3]: R03's equality check is a GIL-held stall, not free.**
  `result == current` compares the `Listing` tuples in C without yielding.
  The document puts it at ~11 ms at 202k "off the Qt thread", but Qt cannot
  run during it. That is under one frame, unlike IR3, but Runtime Effects
  should state it as a stall bound, not as zero Qt cost.
- **Note on IR3.** A low-risk fix is to call `natural_keys` in bounded
  slices from `Name.keys` (for example 8–16k names per call) and
  concatenate. The interpreter can then hand the GIL to Qt between calls
  without any C-side GIL release. The measured 60 ms stall would drop to
  about 3–5 ms per slice at fixture name lengths (estimate). Gate it with the
  same 2 ms heartbeat probe as IR3.

Verified correct in this pass:

- `natural_keys` digit encoding matches `natural_key` (length prefix,
  zero-strip, padding); ASCII lower-casing is in C, Python `str.lower()`
  otherwise; the `surrogatepass` UTF-32 path keeps lone surrogates.
- R05 remap handling: `remap is None` and `remap == {}` both use `wanted`
  directly, and `visible.index(entry)` keeps every stored row correct for its
  key.
- R03 eligibility: navigation and column callbacks always bump `_revision`,
  so they never take the unchanged path; `_refresh_unchanged` reuses the
  committed projection only on Qt.

### Review 2 Validation

- `python src/main/c/check_hashes.py`: pair matches (`cb1e879a…`/`b27ee1a1…`).
- `natural_keys(('',), (False,), True)` in the app environment:
  `SystemError ... bad argument to internal function` (IR2 open).
- `python -m unittest core.tests.fs.test_columns`: 17 run, 1 failure
  (`test_numeric_boundaries_unicode_and_arbitrary_lengths`, IR4 open).
- IR6 estimate: set from a 200,000-entry tuple slice 2.3 ms, then
  `frozenset((5, *s))` 5.9 ms, in plain Python (no Qt).
- Read `git diff` of `fman/impl/model/listing.py`, `model/__init__.py`,
  `view/__init__.py`, `natural_keys` in `fsparser.c` and `Name.keys`.
- Not run: Qt suites, heartbeat probe, performance suite, freeze or package.

## Response to Implementation Reviews (2026_10_04)

All seven findings addressed; paired source/binary now `c77d846e…` /
`18587c3e…`.

| Finding | Resolution |
| --- | --- |
| IR1 | `ListingModel._projecting` tracks a submitted-but-undelivered projection; set in `update()`, cleared in the `view` branch for the current revision on success or error. The unchanged-scan branch skips only while a job is pending; `_revision != _committed_revision` without one now calls `update()` (retry). Test: `test_unchanged_refresh_retries_failed_projection`. |
| IR2 | `scratch_reserve` allocates at least one element, so `PyUnicode_AsUCS4` never receives NULL. Tests: `NaturalKeysTest.test_empty_names_in_any_position` and `NameTest.test_keys_match_reference_across_native_slices_and_empty_labels` (empty first and last label through the column API). |
| IR3 | `Name.keys` calls `natural_keys` in `_NATIVE_KEY_SLICE = 4096` slices. Probe: worst Qt gap 66 → 11–13 ms, key time 61 → 68 ms; `pane.load.large` 239 → 262 ms. Recorded in R10 design and the Overview. |
| IR4 | `test_columns` asserts `'1'`/`'0'` prefixes and the `natural_key` remainder; added to the recorded focused command. |
| IR5 | Status reworded; R09 section replaced by a pointer to Done/FSParser.md with the superseded claims (GIL release, fallback, version check, MSVC) removed; Runtime Effects rewritten per candidate. |
| IR6 | `update()` builds `wanted` only when `len(marks) <= ROW_MAP_LIMIT`; otherwise `None` and the worker builds the full map. |
| IR7 | Runtime Effects state the R03 equality as a GIL-held ~11 ms stall bound at 202k, not as free. |

Still unverified, as before: fixed-rate loaded arrow-to-paint p95, two large
panes with QuickView/status enabled, explicit R05 selection-change-during-
projection coverage, `freeze`/`package`.

### 2026_10_04 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Addressed IR1–IR7 as tabulated above; rebuilt and re-paired the
  binary; 189 focused unit tests and 236 `test_qt` tests pass; validator and
  gauge clean; suite re-measured (`pane.load.large` 262 ms, `refresh.large`
  123–128 ms). Ready for re-review.
