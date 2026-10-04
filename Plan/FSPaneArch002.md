# File System and Pane Architecture 002: Performance

Status: Planned; no application changes implemented.

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
| R02 Selective native record unpacking | `records()` | 200 ms parse of 202k records | Five discarded values fewer per record; gate on parity + non-regression |
| R03 No-change refresh fast path | `ListingModel._receive` / `_commit` | ~300 ms projection + full model reset per unchanged rescan | Skip projection and reset; keep notifications |
| R04 Cooperative worker yield cadence | `LatestJobs._run` | 1 ms `sleep` every 4 ms ≈ 113 ms asleep per 300 ms projection | Yield per ~16 ms frame or `sleep(0)` |
| R05 Per-projection row map | `project()` / `Projection.rows` | 12 ms and ~10 MB per keystroke, sort, refresh | Build only for entries the view asks about |
| R06 Unchanged-rescan identity map | `reconcile()` fast path | 20 ms identity `dict` per unchanged rescan | Sentinel meaning "same order" |
| R09 Native record parser (C, abi3, Python fallback) | `records()` and column building in the Windows scanner | 183 ms parse + ~85 ms list/`Listing` build of a 295 ms scan; kernel enumeration itself is 27 ms | One C call per scan returning the columns; scan ≈ 50 ms |
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
unchanged. `natural_key`, Unicode decimal handling, long digit runs and the
sort call in [project](../src/main/python/fman/impl/model/listing.py) stay as
they are. Gate: lower median key-build time on both datasets; parity of the
full sorted order in both directions.

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

### R04: Cooperative Worker Yield Cadence

Owner: `LatestJobs._run` with `cooperative=True`. The check sleeps 1 ms after
each 4 ms of work; `time.sleep(0.001)` measured ~1.5 ms on Windows, so a
300 ms projection spends ~113 ms asleep. Design: yield every ~16 ms, and use
`sleep(0)` (releases the GIL to a waiting Qt thread without the timer wait) or
keep `sleep(0.001)` at the longer cadence. Cancellation checks keep their
positions. Gate: projection completion time drops on the reference folder;
idle and loaded arrow-to-paint p95 and the Qt heartbeat gap from the
interaction benchmark do not regress.

### R05: Per-Projection Row Map

Owner: `project()` building `{entry: row}` for every visible entry; readers are
the cursor, the preferred-prefix entry and the marked entries in
`_restore_snapshot_state`. Design: pass the entries the view will ask about
(cursor, preferred, marks — captured on Qt when the projection is requested)
into `project()` and build the map for those only; when marks exceed a fixed
threshold (e.g. 1,024) build the full map as today. No lazy linear lookups on
the Qt thread. Gate: restoration identical for none/few/all marked; projection
time and allocation drop for the common case.

### R06: Unchanged-Rescan Identity Map

Owner: `reconcile()` fast path in [fman/listing.py](../src/main/python/fman/listing.py).
When names, identities and creation times are equal it still builds
`{i: i}` over all known entries. Design: return a small identity-mapping
object whose `get`/`__getitem__` return the key when the entry has a known
identity; the view only calls `remap.get(entry)`. Gate: identical restoration;
20 ms and the dict allocation removed at 202k.

### R07 and R08: Refused

R07 (revisit from a bounded listing cache) and R08 (reuse sort keys across
rescans) were proposed in review and **refused by the developer**: no caching
mechanism and no cross-snapshot state. The preferred direction is a simple
path fast enough that no such edge-case logic is needed; see R09.

### R09: Native Record Parser

Owner: `records()` and the column-building loop in `scan()` of the
[Windows scanner](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py).
Of the 295 ms scan at 202,603 entries, the kernel's
`GetFileInformationByHandleEx` batches take 27 ms; everything else is Python
per-record work: `Struct.unpack_from`, bounds checks, UTF-16 name decode, a
yielded tuple, seven list appends and a `bytearray.extend`.

Design: one C function, `parse_records(buffers) -> (names, is_dir, sizes,
mtimes_ns, attributes, created_ns, identities, reparse_tags)`, that walks the
64 KiB buffers already collected by `NativeDirectory.batches`, performs the
same bounds checks, skips `.`/`..`, decodes names with
`PyUnicode_DecodeUTF16(..., "surrogatepass")`, and fills tuples plus one
`bytes` of packed IDs. Follow-up of reparse links (`os.stat`) stays in Python
using the returned tags, as today. Expected scan ≈ kernel 27 ms + C parse
~15–20 ms + Python link follow-ups; first visit ≈ 300 ms before R01–R06,
~250 ms after. The function releases the GIL while parsing, so the Qt thread
is never blocked by it.

Conditions that keep the risk low:

- Hand-written C against the **limited API** (`Py_LIMITED_API = 0x030C0000`,
  `abi3`): one `.pyd` works across Python 3.12+ minor versions; no Cython, no
  generated code, no new Python dependency.
- **Pure-Python fallback**: `records()` stays; the scanner imports the
  extension and falls back when the import fails or the module version does
  not match. Behaviour is identical either way, only speed differs.
- **Parity gate**: on every batch of the reference folder and of the seeded
  fixtures, the C result must equal the Python result field by field; fuzzed
  malformed buffers (bad offsets/lengths, truncation) must raise `ValueError`
  in both.
- **Build**: compiled by `build.py` with the conda-forge MSVC toolchain
  (`vs2022_win-64` added to `environment.yml`; user installs), committed
  source under `src/main/c/`, output collected by
  [RoyiFileManager.spec](../RoyiFileManager.spec) as a binary. If the
  toolchain is absent the build proceeds without the extension and the
  fallback is used.

Second candidate for the same treatment, only if R09 proves the toolchain:
`natural_key` over a tuple of names (97 ms → ~10 ms). Not proposed now.

Gate: scan ≤ 70 ms on the reference folder with the extension, identical
`Listing` to the Python path, fallback exercised in CI by forcing the import to
fail, packaged artifact loads the `.pyd`.

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
- R05 as a lazily materialised map with `visible.index()`: rejected; linear
  lookups on the Qt thread.

## Runtime Effects

- R01/R02/R06 remove temporary objects on the worker; no new state, I/O,
  timers or threads. Inactive when the native scanner is bypassed (R02) or no
  rescan happens (R06).
- R03 adds one listing comparison per rescan on the worker (sub-millisecond for
  ordinary folders, ~11 ms at 202k) and saves projection + reset when unchanged.
- R04 changes only how often the projection worker yields; Qt still receives the
  GIL at least once per frame.
- R05 adds the cursor/marks capture (already available on Qt) to the projection
  request; saves ~12 ms and ~10 MB per projection in the common case.
- R09 adds one native module load at first scan (sub-millisecond); parsing
  runs without the GIL; no new threads, timers or state. With the extension
  absent the Python path runs unchanged.
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
