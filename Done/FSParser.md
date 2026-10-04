# FS Parser: Native Directory Record Parsing

Status: Implemented and re-reviewed. C module, `Listing._trusted`, the
native-only `scan()`, build/packaging verification and tests are in place;
design findings 1–16 and implementation findings IR1–IR8 resolved. Remaining
user step: commit the binary (`git add -f`, it is matched by `*.py[cod]` in
`.gitignore`) and `fsparser.sha256`; the `*.pyd` LFS rule already applies.
Any later change to `fsparser.c` must run both `src/misc/benchmark_fsparser.py`
and `src/misc/validate_fsparser.py` (plus the unit tests) before the binary and
`fsparser.sha256` are regenerated.

## Task

Replace the Python loop that converts `FileIdExtdDirectoryInfo` buffers into
listing columns with one C function, so that a first visit of a large folder is
bounded by the kernel enumeration and the Qt paint rather than by Python
per-record work. Source: [src/main/c/fsparser.c](../src/main/c/fsparser.c).
Owner of the replaced code: `records()` and the column-building loop in
[core/fs/local/windows/listing.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py).

## Scope

- Included: the C module `_fsparser` (three shapes over one record decoder);
  its parity contract with the Python reference parser; the integration in
  `scan()` with a private validation-free `Listing` construction for that
  producer only; an equivalent-Python comment next to every use of the
  extension; build, distribution (Git LFS + hash sidecar) and packaging.
- Excluded: natural-key acceleration (separate decision); any change to
  `Listing` column types, identity rules or the scanner's reparse handling;
  intrinsics/SIMD; Cython or any new Python dependency; array-typed columns;
  a Python fallback path in the scanner (decision: the binary is a build
  requirement; a missing binary fails the build and the import, loudly).
- Compatibility: no public API change. `Listing(...)` and `Listing.create(...)`
  keep full validation for every other producer (`zip://`, `network://`,
  `drives://`, Everything, ProcessPane, plug-ins). `records()` stays in
  `listing.py` only as the readable reference the tests, gauge and validation
  script compare the C module against. The module is internal and carries no
  version constant: its interface changes together with `listing.py`, and the
  committed binary is paired with its source by SHA-256.

## Design

### Module

Source: [src/main/c/fsparser.c](../src/main/c/fsparser.c); build notes:
[src/main/c/README.md](../src/main/c/README.md). Constant `HEADER_SIZE = 88`.

| Entry point                            | Shape                                                        | Role                                   |
| -------------------------------------- | ------------------------------------------------------------ | -------------------------------------- |
| `Columns(link_tags)`                   | one batch at a time into C arrays (doubling from 1,024);     | **integrated**                         |
| `.add(batch) -> [link indices]`        | link follow-up on the reported indices; one hand-over into   |                                        |
| `.entry(i) -> (name, attributes, tag)` | exact-size lists or tuples, freeing each array as it moves   |                                        |
| `.patch(i, is_dir, size, mtime_ns)`    |                                                              |                                        |
| `.finish(frozen=False) -> 8 columns`   |                                                              |                                        |
| `parse_records(batches) -> 8 columns`  | whole directory in one call; validation with the GIL         | gauge reference; fastest, but holds    |
|                                        | released; exact-size lists                                   | every batch and the GIL for the fill   |
| `parse_batch(batch, *8 cols) -> count` | one batch appended to the caller's lists via pre-sized       | gauge reference; pays CPython list     |
|                                        | staging lists; rollback on failure                           | growth                                 |

Input: `bytes`, each one 64 KiB batch returned by
`GetFileInformationByHandleEx(FileIdExtdDirectoryRestartInfo | FileIdExtdDirectoryInfo)`
as collected by `NativeDirectory.batches()` (`buffer.raw`). Records are the
88-byte `FILE_ID_EXTD_DIR_INFO` header followed by the UTF-16LE name:

| Offset | Field                          | Used as                              |
| -----: | ------------------------------ | ------------------------------------ |
|      0 | `NextEntryOffset` (u32)        | record chaining                      |
|      8 | `CreationTime` (i64 FILETIME)  | `created_ns`                         |
|     24 | `LastWriteTime` (i64 FILETIME) | `mtimes_ns`                          |
|     40 | `EndOfFile` (i64)              | `sizes`                              |
|     56 | `FileAttributes` (u32)         | `attributes`, `is_dir` (bit `0x10`)  |
|     60 | `FileNameLength` (u32, bytes)  | name extent                          |
|     68 | `ReparseTag` (u32)             | `reparse_tags`                       |
|     72 | `FileId` (16 bytes)            | `identities`                         |

Output: eight sequences of equal length n (entries `.` and `..` skipped):
`names` of `str`; `is_dir` of `bool`; `sizes`, `mtimes_ns`, `created_ns` of
`int` (FILETIME converted to Unix nanoseconds, `(t − 116444736000000000) × 100`,
exact for every 64-bit input); `attributes` and `reparse_tags` of `int`;
`identities` one `bytes` of 16·n. Lists by default; `Columns.finish(frozen=True)`
returns tuples for the trusted path, where links were patched beforehand.

Errors: `ValueError` with the same three messages as the Python parser
("Truncated directory record", "Invalid directory record", "Invalid directory
record offset") under the same conditions; `TypeError` for anything but
`bytes`. On any error the caller's lists (`parse_batch`) or the accumulated
entries (`Columns`) are exactly as before the call.

### Implementation

- One decoder: `read_record` (bounds and validity in `Py_ssize_t`),
  `count_records` (validate and count a batch, pure C), `make_entry` (the seven
  Python objects of one record, stopping at the first failed allocation) and
  `fill_batch`, which hands each entry to a store callback. The three shapes
  differ only in the callback and the hand-over.
- Every batch is validated completely before any Python object for it is
  created, so malformed input never leaves partial results.
- Names decode with `PyUnicode_DecodeUTF16(..., "surrogatepass", little-endian)`
  — the same codec call the Python code makes.
- Timestamps take the `int64` path when
  `INT64_MIN/100 + EPOCH ≤ filetime ≤ INT64_MAX/100 + EPOCH`, otherwise
  subtract and multiply with Python integers.
- `Columns(link_tags)` stores the tags as `uint32`; `add()` reports only
  entries with `FILE_ATTRIBUTE_REPARSE_POINT` and a matching tag, so cloud
  placeholders or AppExecLinks cost nothing extra. `patch()` requires exact
  `bool`/`int` and a non-negative size because the trusted `Listing` skips
  those checks. `finish()` frees each C array right after moving its column.
  One scan worker owns a `Columns` object from construction to `finish()`;
  it has no lock.
- No GIL release in `Columns.add`/`parse_batch`: validating one 64 KiB batch
  takes microseconds. `parse_records` releases the GIL for its validation pass.
- Limited API `Py_LIMITED_API = 0x030C0000` (abi3, CPython ≥ 3.12); `Columns`
  is a heap type via `PyType_FromSpec`. Plain portable C at `-O2`: `-O3`,
  `-march=x86-64-v3`, `-march=native -flto` and `-Os` measured within noise
  (±1 ms at 200k, ±3 ms at 1M); ~90 % of the time is CPython object creation
  behind the `python3.dll` boundary.

### Integration

Two paths produce a `Listing` for `file://` on NTFS/ReFS; every other producer
has only the regular one.

| Path | Producer | Parser | `Listing` constructor | Validation |
| ------- | ----------------------------------------------------- | ----------------------- | ------------------------ | ---------------------------- |
| Safe    | `scan()` in `core/fs/local/windows/listing.py`        | `_fsparser.Columns`     | `Listing._trusted`       | by the kernel and the C code |
| Regular | `os.scandir` fallback for non-NTFS volumes, `zip://`, | Python / provider code  | `Listing(...)`,          | `__post_init__`, every       |
|         | `network://`, `drives://`, Everything, ProcessPane,   |                         | `Listing.create(...)`    | column, every call           |
|         | plug-ins                                              |                         |                          |                              |

Implemented in:

1. [core/fs/local/windows/listing.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py):
   `_load_native_parser()` loads `_fsparser.pyd` from the package directory
   (frozen build) or from `src/main/c` (repository checkout) and raises
   `ImportError` with a `git lfs pull` hint otherwise — no Python fallback.
   `scan()` is the code shown earlier in this plan: enumeration, `Columns`
   per batch, link follow-up (`os.stat` for tags in `_LINK_TAGS`) on the
   indices `add()` reports, `finish(frozen=True)`, `Listing._trusted`. Each
   extension call carries its equivalent-Python comment; the docstrings link
   here. `records()` remains as the documented reference parser.
2. [fman/listing.py](../src/main/python/fman/listing.py): `Listing._trusted(...)`,
   private classmethod building the frozen dataclass through
   `object.__new__`/`object.__setattr__` over `dataclasses.fields`, skipping
   `__post_init__`. Its docstring states the safe/regular distinction, links
   here, and lists why each skipped check holds: kernel-provided non-empty
   names without `/`, `\`, NUL; `.`/`..` dropped in C; no exact duplicates in
   one directory; `bool`/`int` created in C or checked by `Columns.patch`;
   sizes ≥ 0 by record validation; identities 16·n; scope from
   `NativeDirectory.scope()`; columns already tuples (`finish(frozen=True)`).
3. Every other producer is the regular path: `Listing(...)`/`Listing.create(...)`
   validate as before.

**Readability rule.** Every call into the extension in application code
carries a comment with the equivalent Python, so the data flow can be followed
without the C file; `scan()`, `_load_native_parser` and `Listing._trusted`
reference this document.

**Change rule.** After any edit to `fsparser.c`: rebuild, run
`python -X dev -m unittest core.tests.fs.test_fsparser fman_unittest.test_listing`,
`python src/misc/benchmark_fsparser.py <large folder> --native target/native/_fsparser.pyd`
(parity identical, numbers within 10 % of the tables) and
`python src/misc/validate_fsparser.py --native target/native/_fsparser.pyd`
(no problems), then `python src/main/c/write_hashes.py --from target/native/_fsparser.pyd`.
The safe path trusts the module's output, so these runs are the validation.

### Build and distribution

Toolchain: llvm-mingw 20260922 (LLVM 23.1.2, UCRT, x86_64), not MSVC — no
Visual Studio locally and conda-forge `msvc-headers-libs` is Linux-only.
URL, SHA-256 and the exact command are in
[src/main/c/README.md](../src/main/c/README.md). The module is CRT-independent
(limited API, `PyMem_*` only), so the MinGW `.pyd` loads in the MSVC-built
interpreter; imports are `python3.dll`, `KERNEL32.dll` and `api-ms-win-crt-*`
only (~62 KB).

Distribution: no compiler on developer machines or the runner. The built
`.pyd` is committed via Git LFS at `src/main/c/_fsparser.pyd`, next to its
source, with the tracked sidecar `src/main/c/fsparser.sha256` written by
`src/main/c/write_hashes.py` and checked by `src/main/c/check_hashes.py`
(shared code in `fsparser_hashes.py`). The source digest is taken with CRLF
normalised to LF, so Git line-ending conversion on either side cannot break
the pairing; the binary digest is raw bytes; the sidecar is read tolerant of
either line ending. Current values:

```
source c80b126ce6358ea42801cced661c42a498b8c46b9b58f8073ab6535131358b7f
binary a69a69a178cc57cb2455d69de1616fd048b0f45c848657fff7ec290fb9fe626f
```

(binary of 2026_10_04 after the implementation reviews, 61,440 bytes,
llvm-mingw 20260922, imports `python3.dll`, `KERNEL32.dll`,
`api-ms-win-crt-*`). Loading: in a repository checkout `listing.py` loads
`src/main/c/_fsparser.pyd` directly; in the frozen application it loads the
copy next to itself, which `application.spec` places there from `src/main/c`
as a `binaries` entry so PyInstaller analyses it and bundles `python3.dll`.
The package-local candidate is checked first and the checkout candidate only
when the module sits deep enough for one to exist, so a drive-root portable
install loads (IR1). A Git LFS pointer in place of the binary is reported with
the `git lfs pull` hint before any load attempt (IR7). Git: `.gitignore` line
`*.py[cod]` matches `_fsparser.pyd` (IR5), so the binary must be added with
`git add -f` or an exception `!src/main/c/_fsparser.pyd` must be added to
`.gitignore` (user decision; `.gitattributes` already applies the LFS filter
through its `*.pyd` rule). Checks: `check_hashes.check()` runs in
`build.py test` and `freeze`
(source hash differs → "fsparser.c changed; rebuild and run
write_hashes.py"; LFS pointer → "run `git lfs pull`"; binary hash differs →
"does not match the recorded build") and in
`core.tests.fs.test_fsparser.SourceBinaryPairingTest`, which also asserts the
scanner loaded that very file. `build.py package` and `smoke-everything`
require the packaged copy to be byte-identical to the verified binary.
`release.yml` runs `check_hashes.py` in its "Verify Git LFS assets" step.

Rejected: build on every machine (toolchain requirement); release-asset
download keyed by source hash (download code, publishing step); plain commit
without LFS (acceptable at 62 KB; LFS keeps history clean if rebuilt often).

### Gauge

[src/misc/benchmark_fsparser.py](../src/misc/benchmark_fsparser.py) models
both `scan()` bodies on identical buffers — `python_scan` (current loop, link
follow-up, validated `Listing`) and `native_scan` (planned loop, trusted
`Listing`) — and times the three parser shapes on their own. It enumerates a
folder once through `NativeDirectory`, or with `--synthetic N` generates N
realistic records in 64 KiB batches in memory. Parity: every parser output
field and type against `records()`, and the native `Listing` against the
validated one field by field (tuple columns required).

```powershell
python src/misc/benchmark_fsparser.py "<large folder>" --repeat 7 --native target/native/_fsparser.pyd --json target/diagnostics/fsparser.json
python src/misc/benchmark_fsparser.py --synthetic 1000000 --native target/native/_fsparser.pyd
```

Measured 2026_10_04 (Python 3.14.7, Windows 11 26300, warm cache, medians of
7 alternating samples, ms; JSON in `target/diagnostics/fsparser-*.json`).
Parity identical in every cell.

Parser only, no link follow-up:

| Entries                    | Python | `whole` | `batch` | `columns` | `columns-frozen` |
| -------------------------: | -----: | ------: | ------: | --------: | ---------------: |
| 10k                        |   10.3 |     0.5 |     0.7 |       0.7 |              0.9 |
| 100k                       |  104.7 |     6.6 |    11.0 |       9.2 |              9.1 |
| 200k                       |  215.9 |    17.8 |    30.3 |      23.5 |             23.2 |
| 202,603 (reference folder) |  220.7 |    16.0 |    29.3 |      22.0 |             22.3 |
| 500k                       |  551.3 |    46.8 |    87.3 |      60.8 |             60.3 |
| 1M                         | 1102.7 |    96.1 |   180.2 |     120.9 |            121.5 |

`batch` pays CPython's 1.125× list growth in 584-entry steps (12 ms of pure
`extend` at 200k); `columns` removes two thirds of that, the rest is
`finish()` moving 1.4 M references through stable-ABI setters.

Scan after the kernel call (parse + link follow-up + `Listing`):

| Entries                          | Python scan (validated `Listing`) | Native scan (trusted `Listing`) | Ratio |
| -------------------------------: | --------------------------------: | ------------------------------: | ----: |
| 10k                              |                              13.3 |                             0.9 | 15.2× |
| 100k                             |                             134.1 |                             9.6 | 14.0× |
| 200k                             |                             274.9 |                            23.6 | 11.7× |
| 202,603 (reference, kernel 23.6) |                             275.1 |                            21.8 | 12.6× |
| 500k                             |                             707.0 |                            60.2 | 11.7× |
| 1M                               |                            1418.9 |                           122.0 | 11.6× |

`Listing.__post_init__` at 200k: `tuple()` × 6 = 6.0, name checks 15.7,
`set(names)` 12.2, `is_dir` types 3.2, numeric types 14.9, negative sizes 4.7
— 52.1 in total; the trusted construction is below timer resolution. A
native validator in C was estimated at ~18 ms (the `set(names)` hashing is
irreducible) and rejected in favour of trusting this one producer.

Earlier runs (first build, whole-call only): WinSxS 24,315 entries 26.1 →
2.2 ms; System32 4,757 entries 5.1 → 0.3 ms; parity identical.

### Final Scores

Final binary (`a69a69a1…`, after implementation reviews IR1–IR8), measured
2026_10_04 on the same machine; medians, ms; the native scan is the integrated
`scan()` (`Columns` + `Listing._trusted`), the Python scan is the previous
loop plus the validated `Listing`. Parity identical in every cell. JSON for
the reference folder in `target/diagnostics/fsparser-reference-final.json`.

| Entries                          | Python scan | Native scan | Ratio | Parser `whole` | Parser `columns` | `columns` vs `whole` |
| -------------------------------: | ----------: | ----------: | ----: | -------------: | ---------------: | -------------------: |
| 202,603 reference (kernel 25.3)  |       279.2 |        21.9 | 12.8× |           15.9 |             22.1 |      +6.2 ms (+39 %) |
| 200k synthetic                   |       286.2 |        25.6 | 11.2× |           20.2 |             25.4 |      +5.2 ms (+26 %) |
| 1M synthetic                     |      1462.5 |       130.0 | 11.3× |          110.0 |            129.9 |     +19.9 ms (+18 %) |

Reading:

- Versus Python: the post-kernel scan is 11–13× faster at every size; the
  parser alone 10×. With the kernel call the reference folder's scan goes
  from ≈ 304 ms to ≈ 47 ms.
- Versus the single-pass whole-batch shape: the integrated `Columns` parser
  pays 18–39 % on the parser alone for per-batch accumulation and the final
  hand-over — the price of bounded GIL holds, per-batch cancellation and not
  holding every batch (Alternatives). On the full scan the gap is the same
  absolute 5–20 ms, since both shapes would use the same trusted `Listing`.
- Versus the pre-review build (`65bdc1e0…`): no measurable change
  (22.8 → 21.9 ms scan, 22.5 → 22.1 ms `columns`, 16.8 → 15.9 ms `whole`,
  all within run-to-run noise). The name-character check runs in the cached
  validation pass; allocate-first `finish()` does the same work in a different
  order; freeing arrays directly removed a no-op loop.

## Changes

Every file the task touches. Paths below `Core/` are relative to
`src/main/resources/base/Plugins/Core/core/`.

| File                                  | Change                                                        | State   |
| ------------------------------------- | ------------------------------------------------------------- | ------- |
| `src/main/c/fsparser.c`               | the module: three shapes, `Columns(link_tags)`, strict        | done    |
|                                       | `patch`, per-column free                                      |         |
| `src/main/c/_fsparser.pyd`            | official binary built from the source above                   | done    |
| `src/main/c/fsparser.sha256`          | `sha256(fsparser.c)` (LF-normalised), `sha256(_fsparser.pyd)` | done    |
| `src/main/c/fsparser_hashes.py`,      | sidecar writer and checker, line-ending tolerant, LFS-pointer | done    |
| `write_hashes.py`, `check_hashes.py`  | detection                                                     |         |
| `src/main/c/README.md`                | toolchain pin, build/verify commands, mandatory script runs,  | done    |
|                                       | hash recording                                                |         |
| `Core/tests/fs/test_fsparser.py`      | 36 extension tests + source/binary pairing test               | done    |
| `fman_unittest/test_listing.py`       | native vs Python `scan()` on identical batches (junction,     | done    |
|                                       | cloud tag, failed stat), cancellation between links,          |         |
|                                       | `_trusted` private and public constructors still validate;   |         |
|                                       | mocked-`records()` tests pinned to the regular path           |         |
| `src/misc/benchmark_fsparser.py`      | gauge: Python reference body vs the real `scan()` on captured | done    |
|                                       | batches, plus the three parser shapes                         |         |
| `src/misc/validate_fsparser.py`       | edge-case folders, system folders, crafted buffers, contract  | done    |
|                                       | and leak checks against the Python parser and `os.stat`       |         |
| `src/main/python/fman/listing.py`     | `Listing._trusted` (safe path) with its comment               | done    |
| `Core/fs/local/windows/listing.py`    | `_load_native_parser` (loud failure), native-only `scan()`    | done    |
|                                       | with comments, `records()` kept as the reference              |         |
| `build.py`                            | `_verify_native_parser()` in `test` and `freeze`; packaged    | done    |
|                                       | copy byte-check in `package`/`smoke-everything`               |         |
| `application.spec`                    | `src/main/c/_fsparser.pyd` in `binaries`, destination         | done    |
|                                       | `resources/Plugins/Core/core/fs/local/windows`                |         |
| `.github/workflows/release.yml`       | "Verify Git LFS assets" also runs `check_hashes.py`           | done    |
| `environment.yml`                     | `CONDABUILDWINSDK` already absent; no change needed           | done    |
| `CHANGELOG.md`, `README.md`           | Unreleased entry; Git LFS note in Development                 | done    |
| `.gitattributes`                      | LFS rule for `src/main/c/*.pyd`                               | user    |

## Alternatives

- `parse_records` as the integrated shape: fastest (16.0 ms at 202k, 96.1 ms
  at 1M) but holds every batch (22 MB / 118 MB), holds the GIL for the whole
  fill (~15 ms / ~72 ms, blocking Qt) and cannot cancel until the parse ends.
  Kept as a reference shape.
- `parse_batch` as the integrated shape: same robustness as `Columns`, no
  stateful type, but 29.3 ms / 180.2 ms because of list growth. Kept as a
  reference shape.
- Native `Listing` validator in C: ~52 → ~18 ms at 200k; `set(names)` is
  irreducible. Rejected for trusting the one producer whose columns are
  guaranteed by construction; validation stays for every other producer.
- Cython: same speed, adds a dependency and generated code. Rejected.
- `array('q')`/`array('I')` columns: fewer allocations, but changes `Listing`
  column types. Deferred; the next lever if ever needed.
- Compiler flags beyond `-O2`: measured within noise. Rejected.
- `os.scandir`: 175 ms (C) but no file IDs. Rejected.
- SIMD/AVX2: negligible for this payload. Rejected.
- Distribution by release-asset download or per-machine build: see Build and
  distribution. Rejected for LFS + hash sidecar.

## Runtime Effects

Measured, first visit of the 202,603-entry reference folder (warm, Python
3.14.7, Windows 11); other sizes in the Gauge tables.

| Step                                                |   Today | With `Columns` + trusted `Listing` |
| --------------------------------------------------- | ------: | ---------------------------------: |
| Kernel `GetFileInformationByHandleEx`, 347 × 64 KiB |   24 ms |                              24 ms |
| Parse, link follow-up, `Listing`                    |  275 ms |                              22 ms |
| **Scan total**                                      | ~299 ms |                             ~46 ms |
| Natural keys, sort, filter, row map                 | ~125 ms |            ~125 ms (FSPaneArch002) |
| Model reset + first paint                           |  ~80 ms |                             ~80 ms |

At 1M entries the post-kernel scan goes 1419 → 122 ms.

- CPU: the scan becomes kernel-bound; the ratio stays 11–12× from 100k to 1M.
- GIL: held per call. Measured on the official binary (three runs, C-call
  wall time): `add()` at most 1.4 ms at 200k and 4.7 ms at 1M — the slow
  calls are the ones that double the arrays; typical calls are tens of µs;
  `finish(frozen=True)` 3.8 ms at 200k, 18.1 ms at 1M; discarding an
  unfinished accumulator (cancelled scan) 6.6 ms at 200k, 33.5 ms at 1M.
  Qt frame budget is ~16 ms, so at 1M entries the hand-over and the discard
  are each one to two frames; the Python path held the GIL for the entire
  1.4 s. Gate: no single C call above 5 ms at 200k, 35 ms at 1M.
- Cancellation: between batches and before each link `os.stat`, as today; a
  cancelled scan discards the `Columns` object (bounded above).
- Duplicate names: the trusted path does not check uniqueness (a `set` over
  200k fresh strings costs ~12 ms, half the parser's gain). One NTFS/ReFS
  handle enumeration does not return a name twice; a concurrent
  delete/recreate race is documented for `FindNextFile` and not reproduced
  here. Accepted policy: should it happen, two rows name the same path (no
  operation is misaddressed) and `reconcile` maps one of them; the next
  refresh converges. The validated path would instead fail the whole scan.
- Memory, transient on top of the parsed objects (~160 B per entry, identical
  for every path): one 64 KiB batch; C arrays at a power-of-two capacity
  (≤ 2× the final pointer volume: 19 MB at 200k, 56 MB at 1M); during
  `finish()` at most one column's array coexists with its tuple. Against
  today: no 1.125× list slack, no intermediate `bytearray`, no six `tuple()`
  copies, no validation sets.
- I/O and threading unchanged. No startup cost; the module imports with
  `listing.py`.
- Disabled/no-op path: none by decision. A missing or mismatched binary fails
  `build.py test`/`freeze`; a missing binary at run time raises `ImportError`
  with a `git lfs pull` hint when the scanner module is imported.

## Tests

[core/tests/fs/test_fsparser.py](../src/main/resources/base/Plugins/Core/core/tests/fs/test_fsparser.py)
(37 tests; the parser tests use the module the scanner loaded, or
`FSPARSER_PYD`, and skip when neither exists):

- Shared contract for all three shapes: parity with `records()` on mixed
  records (dot entries, non-BMP, lone surrogate, BOM, trailing dot and space,
  case-only pair, link, cloud and AppExecLink reparse points, `INT64_MAX`
  size), across five batches, fifteen FILETIME boundaries including
  `INT64_MIN`, 0 and the fast-path edges ±1, nine malformed cases with
  identical messages, non-`bytes` rejection, live NTFS temporary folder.
- `parse_records`: sequences and iterators accepted; bare `bytes` rejected.
- `parse_batch`: count, appends after existing entries, columns unchanged
  after every malformed case, wrong column types rejected.
- `Columns`: frozen tuples equal the lists; `add()` reports only link tags
  (cloud/AppExecLink keep their own metadata); `link_tags` argument
  validation; `entry()`/`patch()` semantics; `patch()` rejects `int`/`bool`
  subclasses, floats, `None`, negative sizes; previous entries kept after a
  malformed batch; reuse after `finish()` rejected; discard without `finish()`.
- `SourceBinaryPairingTest`: `check_hashes.check()` is clean, the binary is
  not an LFS pointer, and `listing._fsparser` was loaded from that file.

[fman_unittest/test_listing.py](../src/unittest/python/fman_unittest/test_listing.py),
all through the real `scan()` on record bytes built with `_RECORD`:

- `scan()` versus `records()` (junction patched from `os.stat`, cloud
  placeholder untouched, symlink whose stat fails keeps its own metadata):
  names, attributes, created, identities, sizes and mtimes equal the
  reference; `check_canceled` count 6; `os.stat` called for link tags only;
  tuple columns.
- Cancellation per batch and per followed link (5 checks for 2 batches and
  one link); cancellation between two links of one batch stops after one
  stat; the handle is closed in every case.
- Unreadable link targets keep their own metadata for `PermissionError`,
  `OSError` and `FileNotFoundError`.
- A missing binary raises `ImportError` mentioning `git lfs pull`.
- `Listing._trusted` is private; `Listing.create`/`Listing(...)` still raise
  on bad names, duplicates, non-`bool`, negative or non-`int` sizes; trusted
  equals validated for the same columns and is frozen.

Scripts (mandatory after any `fsparser.c` change): the gauge and
`validate_fsparser.py`, which run the real `scan()` over captured batches and
compare it with the Python reference body.

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-X', 'dev', '-m', 'unittest', 'fman_unittest.test_listing', 'core.tests.fs.test_local', 'core.tests.fs.test_fsparser'], env=build._environment(), timeout=300).returncode)"
python src/main/c/check_hashes.py
python src/misc/benchmark_fsparser.py "<reference folder>" --repeat 7
python src/misc/validate_fsparser.py
```

## Implementation Steps

1. C module, tests, gauge, validation script, README. Done.
2. `Listing._trusted` with its comment and guard tests. Done.
3. Native-only `scan()` with comments; `records()` kept as reference;
   parity, cancellation and missing-binary tests. Done.
4. `build.py` verification and packaged byte-check; `application.spec`
   binary entry; `release.yml` check. Done.
5. CHANGELOG, README. Done.
6. User: commit the binary (`git add -f src/main/c/_fsparser.pyd`, or add a
   `.gitignore` exception) and `fsparser.sha256`; the existing `*.pyd` LFS
   rule applies. The first release build then exercises the packaged copy
   through `package`/`smoke-everything`.

## Acceptance Criteria

- Every shape equals the Python parser on every tested buffer; malformed
  buffers raise the same `ValueError` messages; the extension tests pass. Met.
- Native `scan()` yields a `Listing` equal to the Python `scan()` on the
  reference folder and on folders with links and non-link reparse points.
  Met (gauge, validation script, unit tests).
- Post-kernel scan of the reference folder ≤ 30 ms with the extension
  (measured 22.8 through the integrated `scan()`); results identical to the
  Python reference. Met.
- Every application call into the extension has an adjacent equivalent-Python
  comment and links to this document; `Listing._trusted` is private and
  unreachable from the plug-in API. Met.
- `test`/`freeze` fail on a source/binary hash mismatch or an LFS pointer;
  `package` fails unless the packaged copy is byte-identical. Met (freeze not
  run in this session).
- No new Python dependency; one abi3 `.pyd` paired with its source by SHA-256.
  Met.

## Review Findings

Resolution status after the third review (2026_10_04):

| Finding                                      | Resolution                                                      |
| -------------------------------------------- | --------------------------------------------------------------- |
| 1 GIL-held fill, no cancellation             | `Columns.add` per batch; cancellation between batches and       |
|                                              | before each link stat                                           |
| 2 FILETIME lower-bound overflow              | range check on `filetime`; Python-int path outside; 15 boundary |
|                                              | tests                                                           |
| 3 mutable input across passes                | `bytes` only; each batch validated and consumed in one call     |
| 4 / 8 stale timing text and gate             | rewritten from measurements                                     |
| 5 `uint32` wrap, exception precedence        | `Py_ssize_t` bounds; precedence identical with the per-batch    |
|                                              | loop                                                            |
| 6 per-batch appending API                    | provided as `parse_batch`; 13 ms slower than whole-call at 200k |
|                                              | (list growth), so `Columns` was added and selected              |
| 7 fill loop near floor                       | confirmed by compiler-flag measurements                         |
| 9 plan out of sync; one production API;      | rewritten; `Columns` integrated, the other two shapes kept for  |
|   trusted `Listing` in scope                 | the gauge by decision; no version constant (internal module,    |
|                                              | hash-paired)                                                    |
| 10 filter link tags in C                     | `Columns(link_tags)`; `add()` reports matching tags only        |
| 11 `patch()` invariants                      | exact `bool`/`int`, size ≥ 0                                    |
| 12 C API after failed allocation             | `make_entry` stops at the first NULL                            |
| 13 arrays held through `finish()`            | each array freed after its column moves                         |
| 14 single-thread ownership                   | documented in the type doc and header comment                   |
| 15 silent fallback, stale binary, packaging  | no fallback at all (decision): missing binary fails the build  |
|                                              | and the import; hash check in `test`/`freeze`; packaged copy    |
|                                              | byte-checked in `package`/`smoke-everything`                    |
| 16 edge-case tests                           | parser-level cases added (36 tests); scan-level cases listed    |
|                                              | under Tests                                                     |

Implementation reviews (IR1–IR8 below), resolved 2026_10_04:

| Finding                                      | Resolution                                                      |
| -------------------------------------------- | --------------------------------------------------------------- |
| IR1 drive-root loader `IndexError`           | package-local candidate first; checkout candidate only when     |
|                                              | the module has enough parents; regression test                  |
| IR2 packaged check fails open                | `_verify_native_parser_packaged` verifies the official pair,    |
|                                              | then requires a readable packaged file with the same digest     |
| IR3 allocation-failure contracts             | `parse_batch` creates its return value before committing;       |
|                                              | `finish()` allocates every destination first, so a failure      |
|                                              | leaves the accumulator intact; verified with `set_nomemory`     |
| IR4 GIL/cancellation bounds                  | Runtime Effects rewritten from measured call times with a gate  |
| IR5 binary ignored by `*.py[cod]`            | documented; user adds with `git add -f` or an exception         |
| IR6 `\`/`/`/NUL in names                     | rejected in `count_records` and in `records()` with             |
|                                              | "Invalid directory entry name"; tests and validator cases       |
| IR7 LFS pointer without hint                 | loader reads the pointer prefix and raises with the hint        |
| IR8 stale header, redundant release loop     | header fixed; `finish()` frees each array directly              |
| Open assumption: duplicate names             | accepted policy recorded under Runtime Effects                  |

Original findings follow unchanged.

1. **Bound the GIL-held fill phase and preserve cancellation.** In
   [parse_records](../src/main/c/fsparser.c), only validation/counting releases
   the GIL; all list allocation and `fill_records` calls run in one GIL-held
   phase without a cancellation callback or signal checkpoint. Calling this
   once for a whole directory prevents Python Qt handlers and cancellation
   requests from running during that phase. Process bounded batches/chunks
   with existing worker cancellation/yield checkpoints between them. Do not
   release the GIL around Python object APIs. The claim that Qt is never
   blocked by parsing is not supported.
2. **Check FILETIME subtraction before performing it.** `filetime_to_ns`
   computes `filetime - FILETIME_EPOCH_DELTA` in signed 64-bit arithmetic
   before deciding whether to use Python integers. Values below
   `INT64_MIN + FILETIME_EPOCH_DELTA` overflow; the multiplication fallback
   receives an already-corrupted value. At `INT64_MIN`, the compiled module
   returned `910692730085477580800` instead of `-933981677285477580800`.
   Guard the subtraction and perform both subtraction and multiplication with
   Python integers when it cannot fit; add lower-bound and boundary-neighbor
   regressions, not only the planned `INT64_MAX` case.
3. **Require stable immutable input across both passes.** `PyObject_GetBuffer`
   with `PyBUF_SIMPLE` accepts writable exporters. Holding a buffer view pins
   its storage but does not stop another thread from changing record contents
   while the GIL is released. A read-only memoryview over a bytearray still has
   a mutable backing owner. Concurrently changing a counted name to `.`
   reproducibly raised `RuntimeError: Directory record count changed between
   passes`. Accept immutable bytes, as `NativeDirectory.batches()` already
   produces, or snapshot other exporters under an explicit ownership contract.
   Do not treat `view.readonly` alone as an immutability guarantee.
4. **Reconcile the timing gate with current measurements.** The recorded
   kernel/parse/Listing components sum to about 96.8 ms (26.3 + 17.5 + 53),
   while Runtime Effects and acceptance still target a 70 ms scan using an
   older Listing estimate. No integrated scan or complete-pane result proves
   that target. Separate parser measurements from scan/paint measurements and
   agree a consistent gate before integration.

### Review Validation

- Used the existing `target/native/_fsparser.pyd` (`API_VERSION=1`,
  `HEADER_SIZE=88`) on CPython 3.14.7 with the GIL enabled; no rebuild/install.
- In-memory boundary probe: build records with the Python `_RECORD` struct,
  compare `benchmark_fsparser.python_columns` with `native.parse_records`.
  Two timestamp mismatches reproduced: `INT64_MIN` and
  `INT64_MIN + 116444736000000000 - 1`. Zero, epoch, upper bound and adjacent
  non-overflow boundaries passed. Empty input, dot entries, BOM/non-BMP/lone
  surrogate names and six malformed-record cases matched the Python parser.
- Thread probe: 500 synthetic records per padded 64 KiB immutable batch;
  parse 405 and 2,000 batches while a Python thread samples
  `perf_counter_ns()`, including its final interval after a completion event.
  Observed maximum Python-thread gaps: 14.5-15.3 ms at 202,500 entries and
  71.9-72.1 ms at 1,000,000 entries. This instrumented probe is not a Qt
  paint benchmark or an uninstrumented parser speed measurement.
- Mutation probe: a read-only memoryview over one mutable record followed by
  2,000 immutable batches; another Python thread changes its name from `a`
  to `.` after an event immediately before parsing. All three runs raised
  the between-pass count error. No out-of-bounds write or crash was observed.
- Three existing Python scanner regressions passed with the command below.
  These establish the reference contract, not automated extension coverage;
  the planned extension-specific test module is still absent. No full suite,
  sanitizer run, integrated Qt/cancellation test or packaging test was run.

### Second Review: Parity and Efficiency

5. **Parity holds except the FILETIME lower bound.** Verified against
   `records()`: header offsets match `_RECORD` (`<IIqqqqqqIIII16s`, 88 bytes);
   the three validation conditions and their order are identical; the raw-byte
   `.`/`..` check equals the decoded comparison; `PyUnicode_DecodeUTF16` with
   byte order `-1` and `surrogatepass` is the call behind
   `bytes.decode('utf-16-le', 'surrogatepass')` (BOM kept, lone surrogates
   kept); `bool`/`int`/`bytes` types and the identity concatenation match.
   Remaining differences:
   - Finding 2. Fix by range-checking `filetime` itself: take the `int64` path
     when `INT64_MIN / 100 + EPOCH <= filetime <= INT64_MAX / 100 + EPOCH`
     (neither bound overflows), otherwise compute
     `(PyLong(filetime) - PyLong(EPOCH)) * 100` with Python integers.
   - Exception precedence. The Python scan interleaves link `os.stat` and
     `check_canceled()` with parsing, so a cancellation can win over a later
     malformed record. The whole-directory C call raises `ValueError` before
     any link follow-up. Harmless, and gone with finding 6.
   - `HEADER_SIZE + record->name_length` is `uint32` arithmetic and wraps for a
     buffer above 4 GiB. Cast to `Py_ssize_t` like the other bounds.
     Unreachable from the scanner (64 KiB batches).
6. **Parse per batch and append in C.** The whole-directory call keeps every
   batch alive until parsing ends (22 MB at 202k entries, about 110 MB at 1M),
   holds the GIL for the whole fill phase (finding 1), needs immutable input
   across two passes (finding 3) and moves cancellation after parsing. Replace
   it with `parse_batch(batch, names, is_dir, sizes, mtimes, attributes,
   created, identities, tags) -> count`, called inside the existing
   `for batch in directory.batches(check_canceled)` loop:
   - Validate the batch, then append with `PyList_Append` and extend the
     `bytearray` identities; on allocation failure truncate the lists back with
     `PyList_SetSlice`. No GIL release: validating 64 KiB takes microseconds,
     and a release per batch only adds contention.
   - Link follow-up, `check_canceled()` per batch and per link, and the error
     order stay exactly as in the Python path. One batch is parsed before the
     next `GetFileInformationByHandleEx`, so the buffer cannot change during
     the call. Accept `bytes` only (`PyBytes_AsStringAndSize`).
   - Measured with the current module on the reference folder: the longest
     single-batch call is 69 µs. Emulating per-batch use with
     `parse_records((batch,))` plus Python `list.extend` costs 35.8 ms against
     23.3 ms for the whole call (medians of 7). The extra time is the
     intermediate lists and `extend`, which the appending API avoids. The
     `memset` plus `.raw` copy of 347 batches costs 0.5 ms, so passing the
     ctypes buffer instead of `bytes` is not worth an ownership contract.
   - Benefit is robustness, not speed. Total time stays within about 1 ms of
     the whole call: the same objects are created, plus 347 calls and growing
     lists. Neither path renders earlier, because the pane needs the complete
     sorted snapshot. A scan is canceled by a new navigation, a superseding
     refresh or closing the pane or window while the previous folder stays
     shown. With the whole call the cancellation waits for the full parse,
     about 20 ms at 202k entries plus `Listing` construction; per batch it
     waits at most one batch (69 µs). Recommended, not required for
     integration; confirm the total with the gauge after building it.
7. **The fill loop is near the floor for list output.** Per entry it creates
   one `str` and three multi-digit `int`s (size, mtime, created). Attributes,
   tags and `is_dir` come from the small-int cache and the `bool` singletons
   (reference folder: every attribute `0x20`, every tag 0), so memoizing them
   gains nothing; SIMD gains nothing. The re-validation in pass 2 re-reads
   headers only. The next lever remains the deferred array columns.
8. **Plan text is stale.** Runtime Effects still uses the pre-gauge split
   (183 ms parse, ~60 ms appends, Listing ~25 ms) while the gauge measured
   223.1 ms Python parse and 53.0 ms `Listing`. "The scan worker releases the
   GIL for pass 1, so Qt is never blocked by parsing" is not true for pass 2.
   Update both with finding 4.

### Second Review Validation

- Read `src/main/c/fsparser.c` against `records()` and `scan()` in
  `core/fs/local/windows/listing.py`.
- Using the existing `target/native/_fsparser.pyd` and
  `benchmark_fsparser.enumerate_batches` on the reference folder (202,603
  entries, 347 batches, warm cache): whole call 23.3 ms; per-batch emulation
  35.8 ms; longest single-batch call 69 µs. The whole-call median is above the
  recorded 17.5 ms; treat run-to-run variance as unmeasured.
- `ctypes.memset` plus `.raw` for 347 × 64 KiB: 0.5 ms.
- No rebuild, no source change, no tests run.

### Third Review: Edge Cases, Integration and C Robustness

Resolved since the second review: finding 2 (range check on the raw FILETIME;
probe below), finding 3 for `parse_records` (accepts `bytes` only) and the
`uint32` length addition (cast to `Py_ssize_t`).

9. **The plan no longer describes the code.** `fsparser.c` now has three entry
   points (`parse_records`, `parse_batch`, `Columns`), and
   `benchmark_fsparser.py` models a scan with `Columns`, `finish(frozen=True)`
   and a validation-free `Listing` (`trusted_listing`). Scope still excludes
   any `Listing` change; Design, Integration, Tests and Acceptance still
   describe `parse_records(list(batches))`. `API_VERSION` is still 1 although
   the interface grew. Recorded but unlisted results
   (`target/diagnostics/fsparser-reference-merged.json`, `-scan.json`):
   whole 16.8 ms, `parse_batch` 30.4 ms, `Columns` 22.6 ms, frozen 23.0 ms;
   scan model 276.1 ms (Python, validated `Listing`) against 23.1 ms (native,
   trusted `Listing`). Both scan models start from enumerated batches, so add
   ~24 ms of kernel time; the native figure also omits ~52 ms of `Listing`
   validation. Before integration:
   - Pick one production API. `Columns` fits the scanner loop (per-batch
     cancellation, link follow-up, frozen tuples). Remove `parse_batch` (slowest,
     unused); keep `parse_records` only if the gauge needs it.
   - Either add the trusted `Listing` constructor to Scope with its invariants
     and a test proving trusted equals validated, or measure without it.
   - Bump `API_VERSION` and rewrite Design, Integration, Tests, Acceptance and
     Runtime Effects from the recorded numbers.
10. **Filter link tags in C.** `add()` returns every entry with
    `FILE_ATTRIBUTE_REPARSE_POINT`; Python then calls `entry()` and tests the
    tag for each. A probe batch returned both the link (`0xA000000C`) and a
    cloud placeholder (`0x9000601A`). Synthetic 202,500 entries: 31.2 ms
    plain, 61.1 ms when every entry is a non-link reparse point. The Python
    path pays nothing extra, since it tests `tag in _LINK_TAGS` inline. Pass
    the link tags to `Columns(link_tags)` and return only matching indices.
    How many reparse entries real cloud or app folders report to this process
    is unmeasured; the filter removes the dependency either way.
11. **`patch()` must keep the trusted invariants.** It accepted `True` for
    size and mtime and a negative size (probe). `O!` with `PyLong_Type` admits
    `int` subclasses. Validated `Listing` would reject these, but the trusted
    path skips the checks. Require `PyLong_CheckExact` and size ≥ 0.
12. **Stop at the first failed allocation.** `make_entry` keeps calling the C
    API after a NULL result with an exception set, which the C API does not
    allow (debug builds assert). Release the created objects and return at the
    first NULL. Reached only under `MemoryError`.
13. **Release arrays during `finish()`.** All seven pointer arrays (capacity
    up to 2n each) and the identity buffer live until every column has been
    moved into its list or tuple. At 1M entries that is up to 112 MB of arrays
    plus 56 MB of new sequences. Free each array right after moving it.
14. **Document single-thread ownership of `Columns`.** It has no lock; one
    scan worker must own it from `Columns()` to `finish()`.
15. **Integration must not fail silently.**
    - A missing or stale module falls back to the Python path (about 10×
      slower) without any signal. The packaged smoke must assert the module is
      loaded with the expected `API_VERSION`. The release build must fail when
      no compiler is found; only local builds may skip.
    - `target/native/_fsparser.pyd` (15:56) is older than `fsparser.c` (16:00)
      but reports the same `API_VERSION`. Rebuild when the source hash changes.
    - Keep the build output out of the source tree: `.gitignore` has no `.pyd`
      rule, so a module next to `listing.py` can be committed. Copying
      `src/main/resources/base` as data would also package it without
      dependency analysis. Collect it as a binary, like the ChecksumFiles
      `.pyd`, so `python3.dll` (abi3) is bundled, and state the import path.
16. **Add these edge cases to Tests.** FILETIME 0 and the fast-path bounds
    ±1; non-link reparse tags (cloud, AppExecLink `0x8000001B`) not followed;
    broken link keeps its own metadata; cancellation between links within one
    batch; `patch()` type and sign checks; `add()` failure leaves `Columns`
    unchanged; use after `finish()` raises; names with a trailing dot or space
    or a lone surrogate (the `os.stat` follow-up path); case-only name
    differences in a case-sensitive folder; trusted versus validated `Listing`
    on the reference folder and synthetic batches.

### Third Review Validation

- Read the current `fsparser.c`, `benchmark_fsparser.py`, `scan()`/`records()`
  in `listing.py`, `fman/listing.py`, `application.spec` and `.gitignore`.
- Probes with the existing `target/native/_fsparser.pyd` (all three APIs
  present, `API_VERSION` 1), synthetic batches built with `_RECORD`:
  - FILETIME 0, 1, fast-path bounds ±1, `INT64_MIN`, `INT64_MIN + 1`,
    `INT64_MAX`, epoch, dot entries and a lone-surrogate name: names, mtimes
    and created times equal `records()`.
  - `add()` returned indices of the `0xA000000C` link and the `0x9000601A`
    entry; `patch(0, True, True, True)` and `patch(0, True, -1, 0)` succeeded.
  - `Columns` plus `entry()` loop, 405 batches × 500 entries, median of 5:
    31.2 ms plain, 61.1 ms all non-link reparse points.
- Did not rebuild (the source is newer than the binary), run unit tests,
  packaging or a real cloud-files folder.

```powershell
python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-B', '-m', 'unittest', 'fman_unittest.test_listing.NativeListingTest.test_record_bounds_and_128_bit_identity', 'fman_unittest.test_listing.NativeListingTest.test_native_cancellation_checks_batches_and_each_followed_link', 'fman_unittest.test_listing.NativeListingTest.test_cancel_and_failure_close_handle'], env=build._environment(), timeout=120).returncode)"
```

## Reviewers

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Wrote the plan and `src/main/c/fsparser.c` (limited API, two-pass,
  GIL released during validation, exact FILETIME conversion, Python-identical
  error messages). Not compiled: no MSVC toolchain in the environment yet; the
  user will add it via conda-forge. No application code changed; integration,
  build step and tests are listed for the next step. Timing analysis from a
  measured split of the 295 ms scan: 27 ms kernel, 183 ms Python parsing,
  ~60 ms appends; expected scan ~70 ms, first visit ~350 ms before the
  FSPaneArch002 Python items.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Added `src/misc/benchmark_fsparser.py` as the task's gauge (one
  enumeration, alternating Python/native timing on identical buffers,
  field-and-type parity, JSON output, exit 1 on mismatch) and updated the
  build section for the `clang_win-64` + `msvc-headers-libs` toolchain the
  user declared in `environment.yml`. Nothing compiled or executed; no
  application code changed.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Toolchain decision changed to MinGW-w64 (UCRT): no local Visual
  Studio and `msvc-headers-libs` is Linux-only. Compiled `fsparser.c` with
  llvm-mingw 20.1.1 (`-O2 -Wall -Wextra -static`, limited API) into
  `target/native/_fsparser.pyd`, 71 KB, zero warnings; import table is
  `python3.dll`, `KERNEL32.dll` and `api-ms-win-crt-*` only. Gauge results:
  parity identical on the reference folder, WinSxS and System32; parse
  223.1 → 17.5 ms at 202,603 entries (12.8×), 26.1 → 2.2 ms and 5.1 → 0.3 ms.
  Recorded the verified build command, the import check and the measurements.
  No application code changed; integration, build step and tests remain.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Integration not approved yet. Reproduced signed FILETIME subtraction
  overflow, Python-thread stalls in the GIL-held fill phase and mutable-buffer
  count changes; flagged the inconsistent scan-time gate. Basic boundary/parity
  probes and three reference scanner tests ran; extension regression coverage,
  integrated cancellation/Qt and packaging validation remain required. C,
  scanner and benchmark source unchanged; review findings recorded above.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Integration still not approved. Parity with `records()` holds field
  by field except the FILETIME lower bound (finding 2; concrete range-check fix
  given). Recommended a per-batch appending API (finding 6), which resolves the
  GIL-hold, mutable-input and cancellation-order findings and bounds memory.
  The fill loop is near the floor for list output (finding 7). Plan text is
  stale (finding 8). Measured whole vs emulated per-batch parsing; no source
  changed.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Integration not approved. FILETIME and `bytes`-only fixes
  confirmed. The plan is out of sync with the three-API code and the
  trusted-`Listing` scan model (finding 9). Cloud or other non-link reparse
  entries double the `Columns` path cost until tags are filtered in C
  (finding 10). `patch()` breaks trusted invariants (finding 11). Smaller
  C robustness items in findings 12–14. Silent-fallback, stale-binary and
  packaging risks in finding 15; edge-case tests in finding 16. No source
  changed.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Resolved findings 10–14 in `fsparser.c` (`Columns(link_tags)`
  filtering in C, exact-type and non-negative `patch()`, `make_entry` stops at
  the first failed allocation, per-column array release in `finish()`,
  ownership documented); removed the version constant by decision (internal
  module, hash-paired); kept `parse_records` and `parse_batch` as gauge
  reference shapes by decision. Rebuilt with llvm-mingw 20260922, zero
  warnings. Tests extended to 36 (`-X dev` clean): link-tag filtering, cloud
  and AppExecLink entries untouched, `patch()` type and sign rejection,
  trailing dot/space and case-only names. Gauge now models `python_scan` and
  `native_scan` verbatim (with the equivalent-Python comments) and times all
  three shapes; measured 10k–1M: post-kernel scan 275.1 → 21.8 ms at 202,603
  entries (12.6×), 1418.9 → 122.0 ms at 1M, parity identical including the
  trusted `Listing` against the validated one. Plan rewritten from the current
  code with a full change list (finding 9); the earlier rewrite had been lost
  when the third review was appended. No application code changed.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Implementation review requires changes (IR1-IR4 below). Reproduced
  drive-root loader failure, fail-open packaged verification and both C
  allocation-error contract violations on the official hash-paired binary.
  Measured growth, finish and discard exceeding the documented latency bounds.
  Focused tests: 136 run, four expected skips; isolated live/synthetic validator
  passed with 13 expected skips. Exact patch types now reject the earlier
  subclass vulnerability. Trusted-name uniqueness remains an open assumption.
  Only this document changed; no rebuild, freeze, package or full test suite.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Changes requested beyond IR1–IR4 (Implementation Review 2). The
  binary is ignored by Git (`*.py[cod]`), so a clean checkout breaks the build
  and the Core plug-in (IR5). The trusted `Listing` accepts `\` in names from
  non-Windows NTFS writers and would mis-address later operations (IR6). An LFS
  pointer fails without the documented hint (IR7). Stale comment and a
  redundant release loop (IR8). Focused tests, hash check and validator pass.

## Implementer

### 2026_10_04 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Integrated the safe path. `Listing._trusted` (private, documented
  safe-versus-regular path, links here); `scan()` is native-only by decision:
  `Columns(_LINK_TAGS)`, `entry`/`patch` link follow-up, `finish(frozen=True)`,
  equivalent-Python comments; `records()` stays as the reference parser;
  `_load_native_parser` finds the binary next to the module (frozen) or in
  `src/main/c` (checkout) and raises `ImportError` otherwise. Official binary
  rebuilt from the reviewed source and committed at `src/main/c/_fsparser.pyd`
  with `fsparser.sha256` (LF-normalised source digest). `build.py` verifies
  the pairing in `test` and `freeze` and byte-checks the packaged copy in
  `package` and `smoke-everything`; `application.spec` collects the binary;
  `release.yml` runs `check_hashes.py`. Gauge runs the real `scan()` against
  the Python reference body. Tests: 136 focused tests pass under `-X dev`;
  gauge and validation script clean on the integrated code. Freeze/package
  not run in this session.

### 2026_10_04 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Resolved IR1–IR8. Loader checks the package-local binary first and
  derives the checkout path only when it can exist; LFS pointers are detected
  before loading. `parse_batch` creates its return value before committing;
  `finish()` allocates all destinations first and frees each array directly
  (state preserved on failure, verified by allocation injection). Names with
  `\\`, `/` or NUL are rejected by `count_records` and by `records()` with the
  `Listing` message. Packaged verification now verifies the official pair and
  requires a readable packaged copy. Header comment corrected. Rebuilt with
  zero warnings; new binary `e929a168…` from source `7fcecb0d…`, sidecar
  regenerated. Runtime Effects rewritten from measured C-call times with a
  gate; the duplicate-name assumption recorded as an accepted policy. IR5
  documented: the binary is matched by `*.py[cod]` and needs `git add -f` or
  a `.gitignore` exception (user decision). 137 focused tests, gauge and
  validator (17 malformed sets) pass. Final binary `a69a69a1…` from source
  `c80b126c…` after the comment references moved to `Done/`. Freeze/package
  not run.

## Validation Results

Run 2026_10_04 (after IR1–IR8) on Windows 11 26300, Python 3.14.7, binary
`a69a69a1…` built from source `c80b126c…` (LF-normalised; the IR3/IR4
probes below ran on the functionally identical `e929a168…` build that
preceded a comment-only source change).

| Check | Command | Result |
| ------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Focused unit tests              | `python -c "import build, subprocess, sys; ... '-X', 'dev', '-m', 'unittest', 'fman_unittest.test_listing', 'core.tests.fs.test_local', 'core.tests.fs.test_fsparser' ..."` | 137 tests OK, 4 skipped (symlink privilege, as before) |
| Source/binary pairing           | `python src/main/c/write_hashes.py --from target/native/_fsparser.pyd`; `check_hashes.py` inside `build.py test`/`freeze` | written; matches |
| Gauge, reference folder         | `python src/misc/benchmark_fsparser.py <reference> --repeat 7`                  | final: post-kernel scan 279.2 → 21.9 ms (12.8×) through the real `scan()`; whole 15.9, batch 29.1, columns 22.1, frozen 22.3; parity identical for all (see Final Scores for 200k/1M synthetic) |
| Validation script               | `python src/misc/validate_fsparser.py`                                          | 1,300 entries, 1,324 cases, 13 expected skips; all extra and system folders; 8 synthetic sets, 17 malformed (incl. `\\`, `/`, NUL names), 32 bytes traced growth; no problems in six runs. One run started seconds after the rebuild reported two `os.stat` mismatches that did not recur; treated as a live-folder timing artefact (metadata still settling), not reproduced |
| IR3 allocation injection        | `_testcapi.set_nomemory(i, i+1)` for `finish()` i = 0–11 and `parse_batch` i = 0–39, isolated subprocess | `finish()`: 529 entries before and after every failure, retry succeeds; `parse_batch`: no partial commit on any failure |
| IR4 call times                  | three runs, `perf_counter_ns` around every `add`, `finish(frozen=True)`, discard | 200k: max add 1.42 ms, finish 3.85 ms, discard 6.61 ms; 1M: 4.66 / 18.15 / 33.47 ms — within the gate |
| IR5 facts                       | `git check-ignore -v`, `git check-attr -a`                                      | `.gitignore:65:*.py[cod]`; `filter: lfs` from the existing `*.pyd` rule |
| Not run                         | `python build.py freeze` / `package` / `smoke-everything`                        | packaged byte-check and `python3.dll` bundling to be confirmed by the first release build |

Earlier results (first implementation pass, binary `65bdc1e0…`):

| Check | Command | Result |
| ------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Focused unit tests              | `python -c "import build, subprocess, sys; ... '-X', 'dev', '-m', 'unittest', 'fman_unittest.test_listing', 'core.tests.fs.test_local', 'core.tests.fs.test_fsparser' ..."` | 136 tests OK, 4 skipped (symlink privilege, as before) |
| Source/binary pairing           | `python src/main/c/check_hashes.py` (also inside `build.py test`/`freeze`)      | matches                                                    |
| Gauge, reference folder         | `python src/misc/benchmark_fsparser.py <reference> --repeat 5`                  | post-kernel scan 276.9 → 22.8 ms (12.1×) through the real `scan()`; whole 17.3, batch 31.5, columns 23.0, frozen 23.2; parity identical for all |
| Validation script               | `python src/misc/validate_fsparser.py`                                          | main folder 1,300 entries, 1,324 cases created, 13 skipped (symlink privilege, C0 name); empty/single/2,500-entry/case-sensitive/above-MAX_PATH folders; profile junctions, ProgramData, OneDrive cloud files, System32; 8 synthetic sets, 14 malformed, 32 bytes traced growth; no problems |
| Hash scripts robustness         | scratch copies: CRLF source, CRLF sidecar, LFS pointer, edited source           | exit 0, 0, 1 (pointer message), 1 (rebuild message)        |
| Not run                         | `python build.py freeze` / `package` / `smoke-everything`                        | packaged byte-check and `python3.dll` bundling to be confirmed by the first release build |

## Implementation Review (2026_10_04)

Disposition: changes requested. The implementation and its normal-path tests
work, but completion above is not release approval for the cases below.

### Findings

- **IR1 / P1: drive-root portable installations cannot load the parser.**
  [_load_native_parser](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py#L27)
  eagerly evaluates `here.parents[8]` even when the package-local binary exists.
  With the frozen layout rooted at a drive root (`_internal/resources/Plugins/Core/core/fs/local/windows`),
  that parent does not exist. A simulated frozen-path probe raised `IndexError: 8`
  before the first `is_file` check; adding one installation directory reached
  the extension import normally. Check the package-local candidate first and
  compute the checkout candidate only when applicable. Add a loader regression
  for the shallow layout; a real frozen executable was not run here.
- **IR2 / P2: packaged verification succeeds when both binaries are missing.**
  [_verify_native_parser_packaged](../build.py#L513) compares two hashes, while
  [_sha256](../build.py#L168) returns `None` for any read failure. Two missing
  files therefore pass (`None == None`). Two identical invalid files also pass:
  this helper never verifies the source/binary sidecar. Both outcomes reproduced
  with disposable fixtures. Require readable files, verify the official pair,
  then compare the packaged digest. Earlier CI checks reduce exposure, but the
  standalone `package` and `smoke-everything` entry points still use this guard.
- **IR3 / P2: allocation errors violate the promised unchanged-state contract.**
  [parse_batch](../src/main/c/fsparser.c#L469) allocates its return count after
  committing every column and bypasses rollback if that allocation fails.
  Failure injection with 600 records left seven lists of 600 entries and 9,600
  identity bytes while raising `MemoryError`; retrying appends duplicates. This
  is the reference API, not the production scanner's path. Separately,
  [finish](../src/main/c/fsparser.c#L731) marks the accumulator finished and
  releases its entries on allocation failure: 600 rows became zero. Allocate
  the parse-batch return value before committing. For finish, either preserve
  state by allocating destinations first or explicitly accept and test a
  consuming-on-failure contract; the current document promises preservation.
- **IR4 / P2: the documented GIL and cancellation bounds are not established.**
  [columns_reserve](../src/main/c/fsparser.c#L528) can copy directory-sized
  arrays in one `add()`. Final handover and canceled-scan destruction also do
  directory-sized work under the GIL. Three isolated runs on the official
  binary produced these call times:

  | Entries | Maximum add | Median frozen finish | Median discard |
  | ---: | ---: | ---: | ---: |
  | 200,000 | 1.454 ms | 4.102 ms | 6.686 ms |
  | 1,000,000 | 4.871 ms | 19.674 ms | 35.022 ms |

  The slowest adds crossed capacity boundaries. This contradicts the claimed
  70-us maximum and omits substantial cancellation cleanup. Correct Runtime
  Effects and set measurable worker/Qt latency gates including these phases.
  These are C-call wall times, not Qt frame measurements or a new whole-scan
  speedup comparison.

### Open Assumption

`Listing._trusted` still assumes that a multi-call enumeration cannot return
duplicate names. The real integrated scanner accepted two synthetic batches
with the same name and different identities; the Python reference rejected
them. The resulting two rows collapse to one key in the name dictionary used
by [reconcile](../src/main/python/fman/listing.py#L131). Windows describes
possible duplicates during concurrent deletion/recreation for
[FindFirstFile/FindNextFile](https://devblogs.microsoft.com/oldnewthing/20160210-00/?p=93011);
that is not proof about this handle-based NTFS/ReFS enumerator. No live duplicate
race was reproduced. Establish the stronger guarantee or retain an explicit
uniqueness check/duplicate policy before treating this assumption as verified.

### Review Validation

- Official source/binary sidecar check passed; no C source or binary rebuilt.
  The reviewed binary is the `65bdc1e0...` artifact recorded above.
- Focused suites: 136 tests ran, 132 passed, four expected symlink-privilege
  skips. Exact `patch()` type validation rejects integer subclasses; FILETIME,
  link-tag filtering, scanner parity and cancellation checks pass.
- Validator with `--no-external`: 1,300 main-folder entries in four batches;
  empty, single-entry, 2,500-entry, case-sensitive and long-path folders passed.
  Eight valid synthetic sets, 14 malformed sets and lifecycle checks passed;
  traced growth 32 bytes. Thirteen expected creation skips: 12 symlinks without
  privilege and one forbidden C0 filename. Personal/system folders not scanned.
- Loader procedure: substitute a drive-root frozen `__file__`, report the
  package binary present, call `_load_native_parser`; repeat with one containing
  install directory. Packaging procedure: redirect both binary paths to a
  temporary tree, test both absent, then both containing identical invalid bytes.
- OOM probes ran in isolated subprocesses with `_testcapi.set_nomemory(index,
  index + 1)` and unconditional hook removal in `finally`. For this interpreter,
  finish failures at indices 1-16 discarded all 600 rows; parse-batch index 1131
  raised after commit. Index 0 failed before entering finish and preserved rows.
  Allocation indices are interpreter/build-specific.
- Timing procedure: `synthetic_batches(200000)` and
  `synthetic_batches(1000000)`; three runs each, `perf_counter` around every add,
  frozen finish, and destruction of an unfinished accumulator. No other test
  workload ran concurrently with these measurements.
- No actual frozen startup, dependency bundling, Qt latency, sanitizers or other
  Python versions tested. No full suite, clean, freeze, package or release run.

Commands from the existing activated environment:

```powershell
python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-B', '-X', 'dev', '-m', 'unittest', 'fman_unittest.test_listing', 'core.tests.fs.test_local', 'core.tests.fs.test_fsparser'], env=build._environment(), timeout=300).returncode)"
python -B src/main/c/check_hashes.py
python -B -X dev src/misc/validate_fsparser.py --no-external
```

## Implementation Review 2 (2026_10_04)

Disposition: changes requested, in addition to IR1–IR4.

- **IR5 / P1: Git ignores the binary.** `.gitignore` line 65 `*.py[cod]` matches
  `_fsparser.pyd` (`git check-ignore -v`); `git ls-files src/main/c` lists only
  `fsparser.c`. A plain `git add` skips it, so a clean checkout has no
  binary: `check_hashes.py` reports it missing, `build.py test`/`freeze` stop,
  and importing `listing.py` raises, which disables the Core plug-in. Add a
  `.gitignore` exception for `src/main/c/_fsparser.pyd` (needs the user's
  approval per AGENTS.md) or commit with `git add -f`. The `.gitattributes`
  user step is already covered by the existing `*.pyd` LFS rule. Correct
  Status, "Build and distribution" ("no `.gitignore` change") and step 6.
- **IR6 / P1: the trusted path accepts `\` in names.** `_trusted` states that
  kernel names never contain `/`, `\` or NUL. NTFS stores `\` when another
  driver wrote it: ntfs-3g without `windows_names` creates names with
  `\ " * : < > ? |` and control characters. The validated `Listing` rejected
  such a folder ("Invalid directory entry name"). The trusted one lists it,
  and every `os.path.join`/URL join then addresses a different path
  (`a\b` → folder `a`, file `b`), so later operations can act on another
  entry. Reject `\` (0x5C) and `/` (0x2F) code units in `count_records` with
  the same message, before any object is created. The cost is one pass over
  name bytes already in cache. Add synthetic tests for both characters.
  Not reproduced on a Linux-written volume.
- **IR7 / P3: an LFS pointer fails without the hint.** `_load_native_parser`
  checks `is_file()` only. A checkout without `git lfs pull` holds a text
  pointer, so `exec_module` fails with a DLL load error instead of the
  documented `git lfs pull` message. This affects `build.py run` and
  IDE-launched tests, which do not call `check_hashes`. Read the first bytes
  (`fsparser_hashes.LFS_POINTER_PREFIX`) before loading.
- **IR8 / P3: small items.**
  - The `fsparser.c` header still says the Python implementation "stays as the
    fallback"; the scanner has none.
  - `finish()` calls `columns_release_column` after moving each column. That
    loop runs `Py_XDECREF` over all `count` NULL slots (7 × n). Free the
    array directly once moved. This is part of the finish time in IR4; the
    share is unmeasured.

### Review 2 Validation

- `git check-ignore -v src/main/c/_fsparser.pyd` → `.gitignore:65:*.py[cod]`;
  `git check-attr` shows the `lfs` filter from the existing `*.pyd` rule;
  `git ls-files src/main/c` → `fsparser.c` only.
- `python src/main/c/check_hashes.py` → pair matches.
- Focused suites (command above, without `-B`): 136 run, OK, four symlink
  privilege skips.
- `python src/misc/validate_fsparser.py` with external folders: no problems,
  13 expected skips; profile junctions, ProgramData, OneDrive and System32
  compared.
- IR6 from the ntfs-3g `windows_names` documentation and the `Listing` checks;
  no volume with such names was available. IR7 by reading the loader.
- No rebuild, freeze, package or full suite. Only this document changed.
