# Directory Enumerator 001: Native Folder Table

Generate a local NTFS/ReFS folder as a native table in a Rust extension (`_fsenum`) and deliver it to the pane complete and sorted by Name within the 150 ms target of [FSPaneArch003](FSPaneArch003.md) at 200,000 entries (today 254 ms). Enumeration, record validation, link follow-up, natural sort keys and the sort run on native threads without the GIL, overlapped with the Python objects the current `Listing` contract still needs. The table stays attached to its `Listing`: the Name order and the hidden-file filter come from it, and an unchanged refresh costs one enumeration and no new Python objects. The plug-in API, the `Listing` columns and every non-NTFS path are unchanged. This is the first slice of the native item table; filtering, change sets and the Qt model build on it in their own tasks.

## Task & Guidelines

- **Goal**: Operator direction (2026-11-25): be the fastest file manager, with an architecture that reaches the [FSPaneArch003](FSPaneArch003.md) targets: a complete, sorted 200k-entry folder in ≤ 150 ms (today 254 ms), the slowest Filter Bar query ≤ 100 ms (today 290 ms), a single-file update ≤ 10 ms and Qt heartbeat gaps ≤ 16 ms. This task delivers the load target and the native table the other targets build on. It settles FSPaneArch003 decision 1: enumeration moves into the Rust engine, and `_fsparser` is retired.
- **Scope**:
  - **Included**:
    - A read-only Rust crate `src/main/rust/fsenum/`, built as `_fsenum.pyd` (PyO3, `abi3`, CPython ≥ 3.12).
    - A pipelined scan of local NTFS/ReFS folders: native enumeration, validation and link follow-up; the `Listing` column objects built concurrently on the scan worker; native natural keys; a stable parallel Name sort.
    - A native folder table attached to its `Listing`, used for the Name order, the hidden-file filter and unchanged-refresh detection.
    - An optional `Column.order(listing, ascending, check)` hook in the projection, documented in [PlugIn.md](../PlugIn.md).
    - Retiring `_fsparser`: Name keys for other listings move to `_fsenum`; `fsparser.c`, its binary, its hashes and the `ctypes` scanner are removed.
    - Build, hash verification, packaging, license notices, documentation, gauge and suite updates.
  - **Excluded** (owned elsewhere, see Path to the Remaining Targets in the Final Design):
    - Native Filter Bar (≤ 100 ms): the next task, on this table.
    - Change sets and single-entry re-reads (≤ 10 ms updates, Copy without rescans): the FSPaneArch003 store (P2, F06, F16).
    - Native Size and Modified sorting: needs a decision on local-time (DST) ordering parity.
    - Qt model changes (row insert/remove, model-owned marks), the plug-in API replacement, recursive walking, UNC/FAT/exFAT native enumeration and a single-entry lookup API.
    - Any filesystem mutation.
  - **Compatibility**:
    - The `fman` plug-in API is unchanged; `Listing` columns remain immutable tuples with identical values. `Listing` gains a private, non-compared `_native` field and a weak-reference slot.
    - Non-NTFS volumes, UNC paths, archives and plug-in listings take today's paths.
    - No production fallback or A/B switch between `_fsparser` and `_fsenum`.
- **Acceptance Criteria**:
  - **Load**: `pane.load.large` first paint median ≤ 150 ms (suite, three fresh processes), complete and sorted by Name with the default hidden-file filter; Name descending within the same bound.
  - **Responsiveness**: worst Qt heartbeat gap ≤ 16 ms during load and refresh at 200k and 1M entries; each GIL-held native step (one chunk, one tuple slice, one discard slice) ≤ 5 ms.
  - **Refresh**: scanning an unchanged folder returns the previous `Listing` object and creates no Python objects; `refresh.large` is reported against the baseline.
  - **Parity**: `Listing` columns equal the reference (`records()` plus `os.stat` per link entry) on every validation folder. The Name order equals Python's stable `sorted` over `natural_key`, ascending and descending, with ties in enumeration order, for every code point; `UNICODE_VERSION` equals the shipped Python's.
  - **Robustness**: cancellation propagates the exception of `check_canceled` unchanged; a Rust panic becomes `RuntimeError` and an allocation failure `MemoryError`; no handle or thread outlives a scan.
  - **Memory**: retained native data ≤ 64 bytes per entry plus the name bytes; peak and settled working set at 200k and 1M reported against the baseline.
  - **Packaging**: one native module importing only `python3.dll`, `KERNEL32.dll` and `api-ms-win-crt-*`; a hash-verified Git LFS binary; notices for every linked crate; the frozen build loads it.

## Design Review

### Initial Design - Gemini 4 Neon

- Date: 2026_11_25
- Agent: GitHub Copilot
- Model: Gemini 4 Neon
- Effort: High
- Context Window: 1M

- **Architecture & Data Flow**:
  - **Boundary & Ownership**:
    - All filesystem I/O and record parsing live in a self-contained crate `src/main/rust/fsenum/`, compiled to `_fsenum.pyd` using `pyo3` (`abi3-py312`, `extension-module`) and `windows-sys` (thin Win32/NT bindings, MIT/Apache-2.0, zero async/runtime crates).
    - The crate is strictly read-only: it opens directory handles with `FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES` (`0x81`), share flags `FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE` (`0x7`), and `FILE_FLAG_BACKUP_SEMANTICS` (`0x02000000`). An RAII `OwnedHandle` wrapper guarantees `CloseHandle` on every exit path (normal return, error, cancellation, or unwind).
  - **Two-Stage Internal Pipeline (Separation of Native Arena from Python Materialization)**:
    1. **Stage 1 — GIL-Free Native Enumeration (`enumerate_native`)**:
       - Converts the input path to an extended Windows path (`\\?\...`, rejecting relative paths and UNC paths `\\...` by returning `None` so Python falls back to `LocalFileSystem._scan_entries`).
       - Checks directory scope on the open handle:
         - `GetFinalPathNameByHandleW` → reject `\\?\UNC\` or paths exceeding 32,768 UTF-16 units (`None`).
         - `GetVolumeInformationByHandleW` → require filesystem in `("NTFS", "ReFS")` and `FILE_SUPPORTS_OPEN_BY_FILE_ID` (`0x01000000`), else `None`.
         - `GetFileInformationByHandleEx(FileIdInfo = 18)` → capture `(volume_serial: u64, dir_file_id: [u8; 16])`.
       - Allocates one reusable 64 KiB aligned buffer on the heap (reused across all kernel calls — no per-batch `memset` or Python `bytes` copy; F12 in [FSPaneArch003](FSPaneArch003.md) proved NTFS caps each call at ~64 KiB and larger buffers are slower).
       - Loops `GetFileInformationByHandleEx` with `FileIdExtdDirectoryRestartInfo` (20) then `FileIdExtdDirectoryInfo` (19) until `ERROR_NO_MORE_FILES` (18):
         - Checks atomic `CancelToken` before every kernel call.
         - Parses and validates every `FILE_ID_EXTD_DIR_INFO` (88-byte header + UTF-16LE name) directly from the buffer slice using safe bounds checks (`usize` / checked arithmetic):
           - Skips `.` and `..`.
           - Rejects truncated headers, zero/odd `FileNameLength`, misaligned or backward/out-of-bounds `NextEntryOffset`, negative `EndOfFile`, and forbidden UTF-16 code units (`'/'`, `'\\'`, `'\0'`).
           - Appends raw UTF-16 code units into **one contiguous `Vec<u16>` name arena** plus `(offset: u32, len: u32)` spans — zero per-file heap allocations and 100% lossless preservation of unpaired UTF-16 surrogates (avoiding `String::from_utf16_lossy` corruption!).
           - Appends primitive columns (`Vec<bool>` `is_dir`, `Vec<i64>` `sizes`, `Vec<i128>` or `(Vec<i64>, overflow_map)` for `FILETIME`, `Vec<u32>` `attributes`, `Vec<u8>` packed 16-byte `identities`).
           - Records indices of entries where `(attributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0` and `reparse_tag` is in `link_tags` (`0xA0000003`, `0xA000000C`).
       - **Link-target follow-up (still off the GIL)**:
         - For each recorded link index, checks `CancelToken`, constructs the child extended path in a reusable `Vec<u16>` scratch buffer, and calls `CreateFileW` (following reparse points, `FILE_READ_ATTRIBUTES`, `FILE_FLAG_BACKUP_SEMANTICS`, `share=7`) + `GetFileInformationByHandle` (or `GetFileAttributesExW`) to obtain target `is_dir`, `size`, and `mtime`.
         - Updates only `is_dir`, `size`, and `mtime` on success; keeps the link's own `attributes` (including `FILE_ATTRIBUTE_HIDDEN`, per [PaneRendering001](../Done/PaneRendering001.md)), `created`, and 128-bit `identity`. On any Win32 error (broken/inaccessible target), leaves the entry's own metadata unchanged, matching current `os.stat` `except OSError: continue`.
       - **Duplicate-name safety invariant**: Checks/guarantees unique names before handing off to `Listing._trusted` (NTFS enforces unique names within one directory; a fast duplicate check or hash verification on case-colliding/non-standard drivers prevents malformed duplicates from reaching `Listing._trusted`).
    2. **Stage 2 — Single-Pass Python Column Materialization (`to_python_columns`)**:
       - Reacquires the GIL once after Stage 1 completes, checks cancellation every 4,096 entries, and constructs exact-size CPython tuples directly via CPython Limited API (`PyTuple_New`, `PyUnicode_DecodeUTF16` with `"surrogatepass"` and little-endian byteorder, `PyLong_FromLongLong` with `i128` fallback for extreme FILETIME values outside `i64` nanosecond range, `PyBytes_FromStringAndSize` for packed 16·n identities).
       - Note on Qt responsiveness: constructing 200k Python objects takes ~35–45 ms; yielding the GIL briefly every ~16,384 entries (checking `CancelToken`) keeps Qt heartbeat gaps ≤ 16 ms even during materialization, at negligible (< 1 ms) total overhead.
       - Keeping Stage 1 (`RawEntries`) cleanly decoupled from Stage 2 allows a future `FSPaneArch003` native item table to consume `RawEntries` directly with zero Python tuple allocation.
  - **Single-Entry Authoritative Lookup (`query_entry(dir_path, name, link_tags)`)**:
    - Validates `name` up front: rejects empty names, `.`, `..`, `/`, `\`, `\0`, and Windows wildcard characters (`*`, `?`, `<`, `>`, `"`) with `ValueError`.
    - Opens `dir_path` (or accepts an optional reusable native directory handle in future store work), verifies NTFS/ReFS scope, and calls `NtQueryDirectoryFile` (resolved dynamically from `ntdll.dll` via `GetModuleHandleW`/`GetProcAddress`) with `FileIdExtdDirectoryInformation` (class 60), `ReturnSingleEntry = TRUE`, `RestartScan = TRUE`, and `UNICODE_STRING` set to `name`.
    - Parses the single record through the exact same `parse_record` validator and link follow-up used by `scan_directory`.
    - Verifies that the returned name equals the requested `name` case-insensitively (rejecting 8.3 short-name or unexpected matches by returning `None` / signaling rescan, per F06 in [FSPaneArch003](FSPaneArch003.md)). Returns `None` on `STATUS_NO_SUCH_FILE` / `STATUS_NO_MORE_FILES`, or the single-entry tuple `(name, is_dir, size, mtime_ns, attributes, created_ns, identity_16bytes)`.
  - **Python Integration & Cancellation**:
    - Expose a lightweight `CancelToken` pyclass (backed by `AtomicBool` with `cancel()` / `is_canceled()`), bridged cleanly to `LatestJobs` cancellation in [listing.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py): wiring `CancelToken` directly into `LatestJobs` lets Stage 1 poll cancellation off the GIL without calling back into Python on every batch (with a fallback that polls a Python `check_canceled()` callable if a direct caller supplies one).
    - Unsupported OS errors (`_UNSUPPORTED = (1, 50, 87, 120, 124)`) return `None` so `LocalFileSystem.scan` falls back to `_scan_entries`, identical to today. Other Win32 errors (`ERROR_FILE_NOT_FOUND`, `ERROR_PATH_NOT_FOUND`, `ERROR_ACCESS_DENIED`, `ERROR_NOT_READY`, etc.) map to standard Python `OSError` / `FileNotFoundError` / `PermissionError` with preserved `winerror`.
  - **Build, Hashing & Packaging**:
    - Follow the exact verification model proven by [Done/FSParser.md](../Done/FSParser.md):
      - `src/main/rust/fsenum/` holds `Cargo.toml`, committed `Cargo.lock`, `src/*.rs`, `README.md`, `licenses/` (MIT/Apache-2.0 notices for `pyo3` and `windows-sys`), `write_hashes.py`, `check_hashes.py`, and `fsenum.sha256` pairing normalized source files + `Cargo.lock` with `src/main/rust/fsenum/_fsenum.pyd` (Git LFS).
      - Compile with `--target x86_64-pc-windows-msvc` (static CRT `+crt-static` or UCRT-only dynamic linkage — verify DLL imports with `dumpbin` / `llvm-objdump` so no extra runtime DLLs are required; preinstalled on GitHub Actions `windows-latest`).
      - `panic = "unwind"` in release profile (`Cargo.toml`) so any unexpected Rust panic converts to `pyo3::panic::PanicException` instead of terminating the host process.
      - [build.py](../build.py) verifies `_fsenum.pyd` against `fsenum.sha256` in `test`, `freeze`, and `package`, and verifies the frozen copy under `_internal/resources/Plugins/Core/core/fs/local/windows/_fsenum.pyd` matches byte-for-byte.
      - [application.spec](../application.spec) bundles `_fsenum.pyd` as a binary (ensuring `python3.dll` is collected) and includes `src/main/rust/fsenum/licenses` in `datas`.

- **Alternatives Considered**:
  - **Extend `fsparser.c` in C instead of Rust**: Avoids adding a Rust toolchain, and C already compiles with `llvm-mingw`. Rejected because the user specifically requested a Rust enumerator, and Rust provides memory-safe bounds checking over raw kernel buffers, RAII handle cleanup, safe `AtomicBool` cancellation, and a reusable `RawEntries` arena that directly feeds future native table work without hand-written C memory management.
  - **2-thread overlapped I/O + parsing inside Rust**: Thread 1 reads 64 KiB kernel batches into a channel while Thread 2 parses them. Rejected for this task: pure-Rust parsing of 200k records into primitive `Vec`s takes only ~2–4 ms (unlike CPython object creation), so a worker thread + channel buffer copying would add synchronization complexity and memory copies for negligible gain. Keep enumeration + parsing single-threaded off the GIL; revisit parallelism only if a future stage adds expensive per-entry computation (like natural sort keys).
  - **Port `_fsparser.natural_keys` in the same task**: Would remove `_fsparser.pyd` immediately, leaving one `.pyd`. Rejected for this task to keep scope laser-focused on the enumerator, avoid coupling Unicode 16 decimal-table parity risks to directory enumeration, and allow direct A/B benchmarking against `_fsparser.Columns`. A clean follow-up can either move `natural_keys` into the same Rust crate and delete `_fsparser.c` or keep them cleanly separated based on measurements.
  - **Decode NTFS names to Rust `String` (UTF-8) during Stage 1**: Simpler PyO3 bindings, but Rust `String` cannot represent unpaired UTF-16 surrogates that are legal in NTFS filenames (`String::from_utf16_lossy` silently corrupts names into `U+FFFD`, causing data-safety bugs when later opening or deleting those files!). Storing raw `u16` slices in a contiguous `Vec<u16>` arena and decoding via CPython's `surrogatepass` UTF-16 decoder is both faster (zero per-name heap allocations) and 100% lossless.
  - **Build `_fsenum.pyd` from source on every `build.py test` / `freeze` without a committed LFS binary**: Would require every Python-only contributor or doc builder to install Rust. Keeping the [FSParser](../Done/FSParser.md) hash-verified LFS binary pattern lets Python workflows stay zero-setup while guaranteeing binary-source integrity and reproducible builds.

- **Runtime Effects**:
  - **Startup**: One additional small `.pyd` (~300–600 KiB) imported lazily or with `Core/core/fs/local/windows/listing.py`. Zero background threads, timers, or I/O at startup.
  - **Steady-state CPU & I/O**:
    - Same kernel I/O call count as today (~733 calls at 64 KiB for 200k entries); eliminates `ctypes` buffer `memset` (~733 × 64 KiB = 47 MiB of redundant zeroing!), Python `buffer.raw` copies (~47 MiB), and Python per-batch/per-link orchestration overhead.
    - All kernel I/O, record validation, and symlink/junction stat calls run with the GIL released; Stage 2 yields periodically to keep Qt frame gaps ≤ 16 ms.
  - **Memory**:
    - Peak transient native arena for 200k entries (73-char UTF-16 names): ~29 MiB `Vec<u16>` + ~10 MiB primitive/identity `Vec`s ≈ ~40 MiB, freed immediately after Stage 2 builds the Python `Listing` tuples (lower than holding copied `bytes` batches + incremental CPython staging). Measure peak working set at 200k and 1M entries.
  - **Cancellation**: Atomic `CancelToken` stops Stage 1 at the next kernel batch (~0.1 ms granularity) or before the next link stat, closing the directory handle immediately via RAII. Note: an OS call already blocked inside the kernel (e.g., an offline/slow link target) cannot be interrupted mid-syscall, but runs off Qt and off the GIL so the UI remains responsive and ignores the stale result on completion.
  - **Disabled / fallback path**: Non-NTFS volumes (FAT32, exFAT), UNC shares, archives, and plug-in filesystems take `None` immediately (zero extra handles for UNC paths) and continue using `os.scandir` / provider scanners unchanged.

- **Planned Tests**:
  - **Rust unit tests (`cargo test`)**:
    - Pure record decoder tests (valid records, `.`/`..` skipping, truncated header, zero/odd name length, misaligned/backward/out-of-bounds `NextEntryOffset`, negative `EndOfFile`, forbidden `/`, `\`, `\0`, extreme `FILETIME` boundaries including `i64::MIN`/`i64::MAX`, lone UTF-16 surrogates, duplicate-name handling).
    - `query_entry` wildcard/name validation unit tests.
  - **Python parity & integration unit tests (`core.tests.fs.test_fsenum`, `fman_unittest.test_listing`)**:
    - Hash verification test (`src/main/rust/fsenum/_fsenum.pyd` matches `fsenum.sha256` and is not an LFS pointer).
    - Strict field-by-field parity between `_fsenum.scan_directory` and the Python `records()` reference + `NativeDirectory` across normal files, empty dirs, Unicode/astral/surrogate names, hidden files, symlinks/junctions (when symlink privilege is available; skip cleanly otherwise), broken links, and long `\\?\` paths.
    - `query_entry` parity against `scan_directory` over a 10,000-file temporary folder, plus missing files, case-insensitive lookup returning on-disk casing, wildcard rejection, and short-name mismatch rejection.
    - Error mapping tests (`FileNotFoundError`, `PermissionError`, unsupported filesystem/UNC returning `None`).
    - Cancellation tests (pre-canceled token, cancel mid-scan, verify handle closure so the temporary directory can be deleted immediately on Windows).
    - Frozen-build / DLL-dependency verification (only `python3.dll`, `KERNEL32.dll`, `ntdll.dll`, UCRT).
  - **Performance benchmark (disposable script / gauge, matching `benchmark_fsparser.py`)**:
    - Alternating paired comparison of current `NativeDirectory` + `_fsparser.Columns` vs `_fsenum.scan_directory` on 256, 50,000, and 200,000-entry NTFS folders: report Stage 1 (GIL-free Rust time), Stage 2 (Python materialization), total `scan()` time, peak memory, and Qt heartbeat gap during scan.
    - Single-entry `query_entry` latency median over 10,000 lookups.
  - **Focused validation commands (planned)**:
    - `cargo test --manifest-path src/main/rust/fsenum/Cargo.toml`
    - `python src/main/rust/fsenum/check_hashes.py`
    - `python -c "import build, os, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM'] = 'offscreen'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_fsenum', 'core.tests.fs.test_fsparser', 'fman_unittest.test_listing', '-v'], env=env).returncode)"`

### Review - Claude Opus 5.5

- Date: 2026_11_25
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 1M

- **Verdict**: Changes requested.
- **Kept as designed**: the read-only handle and access mask equal `NativeDirectory`; raw UTF-16 names decoded with `surrogatepass` match `fsparser.c`; a link keeps its own attributes, birth time and identity ([FSPaneArch003](FSPaneArch003.md) F21); the `_UNSUPPORTED` and UNC fallback is unchanged; the hash-paired Git LFS binary model is reused (`*.pyd` is already LFS-tracked); natural keys stay out of scope.
- **Findings**:
  1. **R1 - High: the design keeps the measured cost and gives up the measured lever.**
     - Evidence: [FSParser](../Done/FSParser.md) measured 24 ms kernel and 22 ms post-kernel scan at 202,603 entries, "~90 % of the time is CPython object creation", and 0.5 ms for `ctypes.memset` plus `.raw` over 347 batches. [FSPaneArch003](FSPaneArch003.md) F12 (200k, 73-character names) measured 77-100 ms kernel and 52.4 ms `_fsparser` parse and `finish`; overlap is the lever (a reader thread: 195 → 173 ms).
     - This plan issues the same kernel calls with the same 64 KiB cap, then creates the same Python objects after enumeration ends (Stage 2, its own estimate 35-45 ms). What it removes (memset and `.raw` ≈ 1 ms at 733 batches, the per-batch Python loop, microseconds of C validation per batch) is within run-to-run noise. Overlap is rejected because Rust parsing costs 2-4 ms, but the work to overlap is materialization, not parsing.
     - Required: record the operator's goal and choose one. (a) A Rust infrastructure slice with parity, gated on no regression (alternating pairs, scan median within ±5 %), not "measurably faster". (b) Lower latency: a native thread enumerates and validates batches off the GIL into a bounded queue while the calling worker materializes completed batches, so the scan approaches max(kernel, materialization); gate it with numbers. Delete the memset/`.raw` claim. Reconcile with the operator condition in FSPaneArch003 ("The existing C `_fsparser` stays until a port is measured and justified") and settle its Decision 1 (F23).
  2. **R2 - High: a Rust panic stalls the pane; a failed allocation ends the application.**
     - Evidence: PyO3 raises `PanicException`, derived from `BaseException`. `LatestJobs._run` in [model/listing.py](../src/main/python/fman/impl/model/listing.py) catches only `Canceled` and `Exception`, so `deliver` never runs: a navigation silently never commits, and a refresh leaves `ListingModel._scanning` set, so every later reload only sets `_dirty` and the pane never rescans. Rust aborts on allocation failure, while `fsparser.c` returns `MemoryError`; the Stage 1 arena is the largest allocation of the scan.
     - Required: `catch_unwind` in every exported function, mapped to `RuntimeError`; grow arenas with `try_reserve` and raise `MemoryError`. One test that an internal failure reaches the caller as an `Exception`.
  3. **R3 - High: link-target metadata is not specified to match today.**
     - `GetFileAttributesExW`, offered as an alternative, does not follow links: it returns the symlink's own attributes and the mount-point directory's own attributes (Microsoft documentation). Target `is_dir`, size and mtime would be lost silently.
     - Today's follow-up is `os.stat(os.path.join(path, name))` on the non-extended path ([windows/listing.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py)); the plan builds `\\?\` child paths. Results differ beyond `MAX_PATH` when the host lacks long-path support and for names ending in a dot or space. "Byte-identical" for long paths cannot hold as written.
     - Required: one API (`CreateFileW` following links, then `GetFileInformationByHandle`; keep the entry's own metadata on any error, as `except OSError: continue` does). Choose the path form and either match today or list the intentional differences. Use `os.stat` per link entry as the parity oracle: file symlink, directory symlink, junction, broken link, long path.
  4. **R4 - Medium: cancellation crosses the host/plug-in boundary.**
     - Wiring a Rust `CancelToken` into `LatestJobs` changes `fman.impl.model` for one Core provider (the plan also promises no model changes) and adds a second mechanism. The contract is `FileSystem.scan(path, check_canceled)` with any callable; [test_drives.py](../src/main/resources/base/Plugins/Core/core/tests/fs/test_drives.py) passes a `Mock` raising `RuntimeError`.
     - Required: call the given `check_canceled` with the GIL before each kernel batch (or every ~1 ms) and before each link follow-up; propagate its exception unchanged. The cost matches today, where `ctypes` reacquires the GIL after each foreign call, at least twice per batch. Acceptance should read "the callable's exception propagates", not a module-specific `Canceled`.
  5. **R5 - Medium: Stage 2 holds the GIL without a working yield.**
     - Native code holding the GIL never reaches the eval breaker, so Qt cannot force a switch. "Yielding the GIL briefly" is unspecified; `LatestJobs` records that `sleep(0)` does not hand the GIL over (gaps up to 85 ms).
     - Required: materialize in bounded chunks that return to Python between calls (the `core.Name.keys` 4,096-name precedent measured 11-13 ms worst gap), or per batch as in R1 (b). Adopt the FSParser gate: no single GIL-holding call above 5 ms at 200k or 35 ms at 1M, including discarding a canceled partial result. Measure the Qt heartbeat, not only call times.
  6. **R6 - Medium: the memory claim is inverted.** Today the scan holds one 64 KiB batch plus object-pointer arrays. Stage 1 holds the whole arena (the plan's ~40 MiB at 200k, about five times that at 1M with similar names), and it is alive alongside the finished Python columns at the end of Stage 2. Required: correct Runtime Effects and measure peak working set at 200k and 1M; per-batch materialization removes the arena.
  7. **R7 - Medium: `query_entry` has no consumer.** It is not wired in this task, and FSPaneArch003 F06 already read 10,000 of 10,000 entries through `NtQueryDirectoryFile` with `_fsparser` unchanged at 12 µs. It adds `ntdll` lookup, wildcard and short-name rules, handle-reuse questions and a 10,000-entry acceptance test for an API nothing calls. Required: remove it; design it with the store task that consumes it (F15 step 3).
  8. **R8 - Medium: the toolchain is not available or pinned.**
     - `x86_64-pc-windows-msvc` needs Visual Studio Build Tools (`link.exe`, Windows SDK). FSParser chose llvm-mingw because neither exists on the development machine; this machine has no `cargo`, `rustc` or `link`. With the dynamic MSVC CRT the module imports `VCRUNTIME140.dll`, failing the plan's own DLL criterion; "UCRT-only dynamic linkage" is not an MSVC option. No `rustc` version is pinned.
     - Required: prefer `x86_64-pc-windows-gnullvm` (Tier 2 with host tools; needs an LLVM MinGW toolchain with static libunwind), linked by the already pinned llvm-mingw 20260922, giving UCRT imports like `_fsparser`. Otherwise MSVC with mandatory `+crt-static` and Build Tools documented as a prerequisite. Pin `rust-toolchain.toml` (version and target), build with `--locked`, use PyO3 `abi3-py312` with `generate-import-lib`. The hash manifest covers `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml` and every source; record URLs and SHA-256 as [src/main/c/README.md](../src/main/c/README.md) does.
  9. **R9 - Low: end state and deletion are missing.** After the switch, `NativeDirectory`, `_fsparser.Columns`, `parse_records` and `parse_batch` have no production caller. State that there is no production A/B switch or fallback between the modules ([CodeReview099](CodeReview099.md) FO03; FSParser's no-fallback rule). Remove them here (rebuild and re-hash `_fsparser.pyd`, keeping `natural_keys`) or name the follow-up. Update the producer list in `Listing._trusted`, [src/main/c/README.md](../src/main/c/README.md) and [DEVELOPMENT.md](../DEVELOPMENT.md). Extend `src/misc/benchmark_fsparser.py` and `src/misc/validate_fsparser.py` instead of a disposable script: they already give alternating pairs, edge-case folders and malformed buffers.
  10. **R10 - Low: license notices are incomplete.** Cover every crate linked into the binary per `Cargo.lock` (for example `pyo3-ffi` and the `windows-targets` import-library crates), not only `pyo3` and `windows-sys`; build-only proc-macro crates excluded.
  11. **R11 - Low: smaller undecided points.**
      - Duplicate names: keep the kernel invariant documented in `Listing._trusted` (no check, as today) or define the check and its route to a validated `Listing.create`; "a fast duplicate check or hash verification" is not a design.
      - FILETIME: store the raw `i64` and convert with `fsparser.c`'s fast and slow paths; no `i128` column.
      - Path normalization stays in Python (`os.path.abspath`, as in `NativeDirectory`): `\\?\` disables `..` and trailing-dot processing.
      - Keep the record decoder free of PyO3 types so `cargo test` runs without an interpreter.
      - A blocked link-target open (offline share) still blocks the scan worker, as `os.stat` does today; state it as unchanged, since F21 asks for it to be defined.
  12. **R12 - Low: process.** [Plan.md](../Plan.md) has no Pending entry for this task. Frozen-load acceptance needs an approved `python build.py freeze`, which the validation commands omit.
- **Recommendations**:
  1. Confirm the goal with the operator (R1), then narrow scope to `scan_directory` plus build and packaging; drop `query_entry` and `CancelToken`.
  2. Specify R2, R3, R5 and R8 exactly in the Final Design.
  3. Replace the performance criteria with numbers: scan median on the FSParser reference folder (202,603), the F12 fixture (200k) and 1M; the GIL gate; the Qt heartbeat; peak working set.
  4. Validation: `cargo test --locked`; hash checks for both modules; the extended gauge and validator; then `core.tests.fs.test_fsenum`, `core.tests.fs.test_fsparser`, `core.tests.fs.test_local` (scan and fallback) and `fman_unittest.test_listing` through `build._environment()`.
- **Review validation**: read this plan, [FSParser](../Done/FSParser.md), FSPaneArch003 (measurements, F05, F06, F12, F15, F21, F23), [windows/listing.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py), [fsparser.c](../src/main/c/fsparser.c), [model/listing.py](../src/main/python/fman/impl/model/listing.py), [build.py](../build.py), [application.spec](../application.spec) and `.gitattributes`; checked that `cargo`, `rustc`, `link` and `clang` are not on `PATH`; confirmed `PanicException`'s base class (PyO3 documentation), `GetFileAttributesExW` link behavior (Microsoft documentation) and the `gnullvm` target tier (rustc book). No tests, probes or builds were run.

### Final Design - Claude Opus 5.5

- Date: 2026_11_25
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 1M

- **Consolidated Design**: the subsections below. Today's 254 ms is scan ~122 ms + projection ~110 ms + Qt ~20 ms ([FSPaneArch003](FSPaneArch003.md), preliminary measurements). The projection spends ~106 ms building 200,000 Python natural keys and sorting them. This design turns the scan into a pipeline whose length is the kernel enumeration plus a short tail, and turns the Name projection into a few milliseconds of native array work.

#### Target Budget

200,000 entries, warm cache, Name ascending, hidden-file filter on.

| Stage                            | Thread      | GIL       | Budget                                   | Evidence                                                                  |
| -------------------------------- | ----------- | --------- | ---------------------------------------- | ------------------------------------------------------------------------- |
| Kernel enumeration               | E           | no        | floor                                    | 77-100 ms (F12, 73-character names); ~55 ms estimated for `flat-large-v1` |
| Validation, link follow-up       | E           | no        | overlapped                               | microseconds per 64 KiB batch ([FSParser](../Done/FSParser.md))           |
| `Listing` column objects         | P           | per chunk | overlapped, ≤ kernel                     | 52.4 ms for `_fsparser` parse and `finish` (F12)                          |
| Natural keys                     | K           | no        | overlapped, ≤ 30 ms CPU                  | 59 ms allocating, single-thread Rust probe                                |
| Tail: last chunk, column tuples  | P           | chunked   | ≤ 5 ms                                   | `finish(frozen=True)` 3.8 ms ([FSParser](../Done/FSParser.md))            |
| Stable Name sort                 | S           | no        | ≤ 10 ms                                  | 20 ms single-thread on precomputed keys (Rust probe)                      |
| Projection: order, hidden filter | view worker | briefly   | ≤ 3 ms                                   | native array operations                                                   |
| Qt commit and first paint        | Qt          | yes       | ≤ 20 ms                                  | ~20 ms today; 6.9 ms plain reset and repaint                              |
| **Total**                        |             |           | **max(kernel, objects, keys) + ≤ 40 ms** | 95-140 ms for a 55-100 ms kernel                                          |

The target holds when the kernel enumeration of `flat-large-v1` takes ≤ ~110 ms on the reference machine and the column objects keep pace with it. Step 1 measures both before any application change. Expected at 1M entries: kernel time plus about 100 ms, reported only.

#### Threads and Data Flow

One call, `_fsenum.scan(location, path, link_tags, check_canceled, previous)`, runs on the existing scan worker (`LatestJobs`). It returns a `Listing`, or `None` for an unsupported volume. Its threads are scoped to the call and joined before it returns, including on error and cancellation.

- **E, enumerator** (native thread, no Python): opens the directory as today (`0x81`, share 7, backup semantics, the `\\?\` path built by `os.path.abspath` in Python) and checks scope (no UNC; NTFS or ReFS; open by file ID; `FileIdInfo`). It reads `FileIdExtdDirectoryRestartInfo` and `FileIdExtdDirectoryInfo` batches into one reused 64 KiB buffer, validates every record exactly as `records()` does, follows link tags, appends the entries to the table and publishes each batch as an immutable chunk. It checks the cancel flag before every kernel call and link follow-up.
- **K, key builder** (native thread, no Python): builds the natural key and an 8-byte comparison prefix of every published entry.
- **P, materializer** (the calling worker): for each chunk, creates the Python objects of the `Listing` columns with the GIL held (`str` decoded as Latin-1, or UTF-16 with `surrogatepass`; exact `int` and `bool`), calls `check_canceled`, and waits for the next chunk with the GIL released. After 12 ms of GIL time without a wait it releases the GIL for 1 ms, as the cooperative `LatestJobs` lane does; a bare release does not hand the GIL to Qt (measured gaps up to 85 ms).
- **S, sorter** (up to four scoped threads, no Python): after the last chunk, sorts entry indices by (directory first, key, index) with a stable parallel merge sort and marks positions whose key equals the previous one.
- **Hand-over** (P): builds the six column tuples in slices of at most 5 ms of GIL time and returns `Listing._trusted(..., native=table)`.

Threads share only immutable chunks, an atomic published count and an atomic cancel flag.

#### Native Folder Table

`FolderTable` (a PyO3 class, immutable once returned) is the scan's result in native form and the base of the later item table.

- Retained per entry: name span (8 bytes), directory flag, size, modification and birth times, own attributes, 128-bit identity, ascending Name order position (4 bytes) and a tie bit: about 57 bytes plus the name. Names are stored as Latin-1 when every UTF-16 unit is below 256, otherwise as UTF-16. About 25 MiB at 200k ASCII names of 73 characters. Keys exist only during the scan.
- Methods, for Core only:
  - The Name order as `array('I')`. Ascending is stored; descending is derived in one pass by reversing the runs of equal keys within each group, so directories stay first and ties keep enumeration order.
  - The subset of an order whose entries lack an attribute bit (the hidden-file filter).
- Attached as `Listing._native` (`init=False`, `compare=False`, `repr=False`). `dataclasses.replace` and the regular constructors produce `None`; equality and hashing are unchanged. `Listing._trusted` takes the table as an argument and must set the field explicitly, since it bypasses `__init__`; its docstring names `_fsenum` as the trusted producer.

#### Link Follow-up

- For an entry with `FILE_ATTRIBUTE_REPARSE_POINT` and a tag in `_LINK_TAGS` (symlink, mount point), E opens the same string today's `os.stat(os.path.join(path, name))` opens, following links (`CreateFileW`, `FILE_READ_ATTRIBUTES`, backup semantics), and reads `GetFileInformationByHandle`.
- It replaces only `is_dir`, size and modification time. On any error the entry keeps its own values, as `except OSError: continue` does today. Attributes, birth time and identity remain the link's own ([FSPaneArch003](FSPaneArch003.md) F21).
- The same path string keeps Win32 path rules (`MAX_PATH`, trailing dots and spaces) identical. `GetFileAttributesExW` is not used: it does not follow links.
- A target that blocks (an offline share) blocks E, as `os.stat` blocks the worker today; cancellation takes effect when the call returns, off Qt and off the GIL.

#### Natural Keys and Order

- Each key equals `natural_key(name)` code point for code point: lower-casing, then digit runs normalized (`lstrip('0')`, six-digit padding, long-run prefix), as `fsparser.c` computes today.
- Lower-casing is native for every name, using tables that `generate_unicode.py` writes from the shipped Python: `chr(c).lower()` for every code point, the Final_Sigma rule of `str.lower` (its cased and case-ignorable sets derived by probing `str.lower`), and `unicodedata.decimal` digit runs. `UNICODE_VERSION` is recorded, and a test fails when it differs from `unicodedata.unidata_version`. Lone surrogates pass through, as with `surrogatepass`.
- Order: directories first in both directions, keys ascending or descending, equal keys in enumeration order. This is today's stable `sorted(..., reverse=not ascending)` over the same keys.
- `_fsenum.natural_keys(names, is_dir, ascending)` returns today's key strings for listings without a table (archives, network, the `os.scandir` fallback), replacing `_fsparser.natural_keys`.

#### Projection and Core Integration

- `project()` in [model/listing.py](../src/main/python/fman/impl/model/listing.py) asks the sort column for `order(listing, ascending, check)` when the column has that method, and falls back to `keys` when it returns `None`.
- A returned `array('I')` stays an array rather than a 200k-int tuple. Consumers of `Projection.visible` index, slice, iterate and call `index`, which arrays support: [view](../src/main/python/fman/impl/view/__init__.py), [status_bar.py](../src/main/python/fman/impl/status_bar.py) and [quick_view.py](../src/main/python/fman/impl/quick_view.py); `FilterBar` already copies to a tuple.
- `core.Name.order` returns the table's order, or `None` without a table. Size, Modified and plug-in columns are unchanged.
- The hidden-file filter's `filter_indices` uses the table when the listing has one and the order is an array; otherwise its Python loop runs as today.
- `LocalFileSystem.scan` calls `_fsenum.scan` and keeps the `os.scandir` fallback for `None`.

#### Unchanged Refresh and Prefix Reuse

Panes rescan on every application activation and after file notifications; today each 200k rescan builds every object again and compares the `Listing` (11 ms).

- `LocalFileSystem` keeps a lock-guarded `WeakValueDictionary` from location to the last native `Listing`. It keeps nothing alive, so it is not the snapshot cache the operator ruled out.
- With a previous listing of the same location and scope, E compares every finished record with the previous entry at the same index. P and K wait while every entry so far is equal.
- At the first difference, P takes the prefix's objects from the previous `Listing` (references only) and creates objects from there on; K builds the keys from the start. The remaining work is a first load.
- If every entry is equal and the count matches, `scan` returns the previous `Listing` object. The model's existing `result == current` check then compares identical column objects, and `_refresh_unchanged` repaints without a projection.

#### Failure, Cancellation and Lifetime

- Win32 errors become `OSError(0, message, path, winerror)`, so Python selects the subclass and keeps `winerror`. The `_UNSUPPORTED` codes return `None`; malformed records raise `ValueError`, as today.
- Cancellation: P calls `check_canceled` between chunks. Its exception sets the cancel flag, joins E, K and S, discards partial objects in slices and propagates unchanged.
- Every entry point and thread body runs under `catch_unwind`; a panic becomes `RuntimeError`, because PyO3's `PanicException` derives from `BaseException` and would bypass `LatestJobs`. Growth proportional to the entry count uses `try_reserve`; failure becomes `MemoryError` instead of a process abort.
- No thread pool, idle thread or timer exists between scans; non-NTFS paths start no thread. Handles close through RAII on every path.
- Duplicate names: the kernel invariant documented in `Listing._trusted` stands, as today.

#### Toolchain and Packaging

- Target `x86_64-pc-windows-gnullvm` (Tier 2 with host tools), linked by the llvm-mingw 20260922 toolchain already pinned for `_fsparser`: UCRT only, static libunwind. `rust-toolchain.toml` pins the compiler version and target; builds use `cargo build --release --locked`.
- Dependencies: `pyo3` (`abi3-py312`) and `windows-sys` only. No `rayon`: its global pool keeps idle threads for the life of the process.
- `fsenum.sha256` pairs the binary with `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml`, the generator, the generated tables and every source (line endings normalized), as `fsparser.sha256` does. The binary is committed through Git LFS (`*.pyd` is already tracked). `build.py` verifies it in `test`, `freeze` and `package` and checks the frozen copy; `application.spec` collects it as a binary.
- License notices cover every crate linked into the binary, generated from `Cargo.lock`; build-only crates are excluded.
- The crate README records toolchain URLs and SHA-256, the build command, the import check and the change rule, as [src/main/c/README.md](../src/main/c/README.md) does today; [DEVELOPMENT.md](../DEVELOPMENT.md) links it.

#### Path to the Remaining Targets

| Target                     | Mechanism on this table                                                                                     | Owner                               | Evidence                                                                            |
| -------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------- | ----------------------------------------------------------------------------------- |
| Filter Bar ≤ 100 ms        | Folded names built natively at the first filter; linear-time glob and substring kernels on the stored order | Next task                           | Substring 2.5-2.8 ms at 200k (Rust probe); slowest suite query 290 ms               |
| Single-file update ≤ 10 ms | Re-read the entry through the same decoder; its key; binary insertion into the order; a row insert signal   | FSPaneArch003 store (F06, F07, F16) | Re-read 12 µs; insertion 2.2 ms (Python upper bound); Qt insert plus remove 11.9 ms |
| Copy without full rescans  | Change sets; this task only makes each rescan cheaper                                                       | FSPaneArch003 P2                    | [CodeReview007](../Done/CodeReview007.md)                                           |
| Qt gaps ≤ 16 ms            | GIL bounds here; model-owned marks for large selections (F13)                                               | This task; FSPaneArch003            | Mark restore 26 ms at 200k marked rows                                              |

#### Review Decisions

- R1: option (b), at the operator's direction, extended with native keys and sort. Overlapping enumeration with object creation alone cannot reach 150 ms while the projection spends ~106 ms on keys and sort.
- R2-R6, R8 and R11: accepted as specified above.
- R7: `query_entry` dropped; the store task designs it with its consumer.
- R9: `_fsparser` retired in step 6, with no production fallback.
- R10: notices generated from `Cargo.lock`.
- R12: indexed in [Plan.md](../Plan.md); `freeze` and `package` require operator approval (step 6).
- Kept from the Initial Design: the read-only handle, the information classes and the 64 KiB buffer, raw UTF-16 names decoded with `surrogatepass`, link-owned attributes and identity, the hash-paired LFS binary, and `records()` as the reference.
- Rejected:
  - Lazy, native-backed `Listing` columns: they would save ~50 ms of CPU, but name lookup, filters, the status bar, icons and plug-ins read the tuples. That is the item model of FSPaneArch003 P1, not this task.
  - Native Size and Modified sorting now: `datetime.fromtimestamp` orders local wall time, which differs from nanosecond order around DST changes; parity needs a decision first.
  - A helper process (FSPaneArch003 F05): one bounded, read-only folder scan stays in process, as `_fsparser` does today. Reconsider for walkers and searchers.
- Open:
  - An independent design review before implementation (two reviewers, per [README.md](../README.md)).
  - FSPaneArch003 still lists decision 1 as open; it should reference this task.

#### Implementation Steps

1. **Feasibility probe** (disposable, no application change): on `flat-large-v1` and the F12 fixture, measure kernel-only enumeration, column objects created concurrently with it, native keys and the stable sort. Gate: max(kernel, objects, keys) + tail + 20 ms ≤ 140 ms; otherwise stop and report.
2. **Crate and packaging**: toolchain pin, crate skeleton, generated Unicode tables, hashes, `build.py`, `application.spec` and notices. Gate: `cargo test --locked`; hash check; the module loads from the checkout with the expected imports.
3. **Pipelined scan**: E, P, link follow-up, errors, cancellation, and panic and allocation mapping; replaces the `ctypes` scanner. Gate: parity against `records()` and `os.stat`; gauge scan ≤ max(kernel, objects) + 5 ms; every GIL-held step ≤ 5 ms.
4. **Keys, order and projection**: K, S, `Column.order`, `core.Name.order`, the native hidden-file filter and array orders. Gate: order parity for every code point, ties and both directions; `pane.load.large` ≤ 150 ms; heartbeat ≤ 16 ms during load (the pane workload gains a heartbeat metric and a catalog revision).
5. **Unchanged refresh and prefix reuse**. Gate: an unchanged scan returns the previous object; reused listings equal fresh scans for insertions, removals, renames and metadata changes at the start, middle and end; `refresh.large` reported.
6. **Retire `_fsparser`**: `Name.keys` through `_fsenum.natural_keys`; remove `fsparser.c`, its binary and hashes, `NativeDirectory` and the C build check; rename the gauge and validator for `_fsenum`; update [PlugIn.md](../PlugIn.md), [DEVELOPMENT.md](../DEVELOPMENT.md) and [CHANGELOG.md](../CHANGELOG.md). Gate: focused tests; `freeze` and `package` with operator approval.

#### Validation Plan

- `cargo test --locked --manifest-path src/main/rust/fsenum/Cargo.toml`
- `python src/main/rust/fsenum/check_hashes.py`
- `python src/misc/benchmark_fsenum.py <folder> --repeat 7` on the FSParser reference folder, the F12 fixture and 1M synthetic entries, alternating with the baseline (`benchmark_fsparser.py` until step 6).
- `python src/misc/validate_fsenum.py`: live folders, links, long paths, Unicode and surrogate names, malformed buffers.
- `python -c "import build, os, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM'] = 'offscreen'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_fsenum', 'core.tests.fs.test_local', 'core.tests.commands.test___init__', 'fman_unittest.test_listing', 'fman_integrationtest.impl.model.test___init__', '-v'], env=env).returncode)"`
- With operator approval: `python build.py measure` (`pane.load.large`, `refresh.large`, load heartbeat), then `python build.py freeze` and `python build.py package`.

## Implementation

### Implementer - Claude Opus 5.5

- Date: 2026_11_25
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 1M

- **Changes**:
  - **Crate** [src/main/rust/fsenum](../src/main/rust/fsenum/README.md), no dependencies:
    - `pipeline.rs`: the calling thread opens the folder, checks its scope and reads up to two 256 KiB batches with the GIL released. A folder that ends there is decoded, keyed and sorted on that thread, with no other thread. Otherwise a reader thread continues the kernel calls (up to four pooled buffers, created on demand). The decoder validates records, follows links, compares with the previous table and publishes 4096-entry segments. Two key builders claim segments, and the sort runs after the last one.
    - `record.rs`: `records()` validation and messages.
    - `keys.rs` and the generated `unicode.rs`: `natural_key`, including Final_Sigma and `unicodedata.decimal` runs, with a Latin-1 fast path.
    - `sort.rs`: most-significant-first sort on 8-byte key chunks with common-prefix skipping, tie bits for the descending order, and up to eight threads; groups under 4096 entries are sorted directly.
    - `segment.rs`: the folder table.
    - `python.rs`: hand-written limited-API bindings. P creates the column objects per segment and hands the GIL over after 4 ms. A previous table supplies the objects of the unchanged prefix, and an unchanged folder returns `previous` itself. Panics map to `RuntimeError`, allocation failures to `MemoryError`, and Win32 errors to `ctypes.WinError`'s `OSError`.
    - Tooling: `build_fsenum.py` (pinned rustc, self-contained linker, import check, record), `fsenum_hashes.py`, `check_hashes.py` and `generate_unicode.py`.
  - **Core**:
    - [windows/listing.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py) loads `_fsenum` and keeps `records()` as the reference.
    - [LocalFileSystem](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py) keeps a lock-guarded `WeakValueDictionary` of the last native `Listing` per location.
    - `core.Name.order` returns the table's order as `array('I')`, and `Name.keys` uses `_fsenum.natural_keys`.
    - The hidden-file filter uses `without_attributes` for native orders.
  - **Host**:
    - `Listing._native` (no init, compare or repr) and a weak-reference slot; `Listing._trusted(..., native=)`.
    - `Column.order` hook in [fman/fs.py](../src/main/python/fman/fs.py).
    - `project()` consults the hook and keeps an `array('I')` order and visible list.
    - The inactive Filter Bar passes the order through instead of calling a predicate per entry.
  - **Retired**: `src/main/c` (`fsparser.c`, `_fsparser.pyd`, its hashes and scripts), `NativeDirectory`, `benchmark_fsparser.py`, `validate_fsparser.py` and `core.tests.fs.test_fsparser`.
  - **Build and release**: `build.py` (`_verify_native_enumerator`, plus the packaged check), [application.spec](../application.spec) and [release.yml](../.github/workflows/release.yml).
  - **Notices**: [Core/licenses](../src/main/resources/base/Plugins/Core/licenses/README.md) for the statically linked Rust standard library, the MinGW-w64 runtime and the libgcc unwinder.
  - **Tests**:
    - New `core.tests.fs.test_fsenum`:
      - hash pairing;
      - `parse_batches` against `records()` for mixed, malformed, FILETIME-extreme and multi-segment buffers;
      - natural keys for every code point;
      - the sort against stable `sorted`;
      - live scans against `os.lstat`/`os.stat`, including a junction and a dangling junction;
      - native order and hidden filter, `project()` keeping the array, the unchanged rescan returning `previous`;
      - prefix reuse after five kinds of change equal to fresh scans;
      - `LocalFileSystem` reuse;
      - unsupported paths, a missing folder and cancellation.
    - Updated `test_listing`, `test_app_name`, `test_everything` and two `test_qt` cases that inject failures into `Name.keys` (they now also return `None` from `Name.order`).
  - **Gauge**: [benchmark_fsenum.py](../src/misc/benchmark_fsenum.py).
  - **Docs**: [PlugIn.md](../PlugIn.md), [DEVELOPMENT.md](../DEVELOPMENT.md), [CHANGELOG.md](../CHANGELOG.md) and the crate README.
- **Deviations**:
  - No PyO3 or `windows-sys`: the CPython limited API (abi3, 3.12+) and kernel32 are declared by hand and imported with `raw-dylib`. With no crates there are no crate notices; the linked Rust standard library and MinGW-w64 runtime are noticed instead.
  - Toolchain: `x86_64-pc-windows-gnu` with the Rust distribution's self-contained MinGW-w64 linker, not `gnullvm` with llvm-mingw, which is not installed. There is no `rust-toolchain.toml`: rustup would try to download the pinned name. `build_fsenum.py` refuses another rustc release instead. The module imports `python3.dll`, `kernel32.dll`, `ntdll.dll`, `msvcrt.dll` and `api-ms-win-core-synch-l1-2-0.dll`, not the UCRT. A rebuild of identical sources gives an identical binary.
  - Pipeline:
    - A reader thread overlaps the kernel calls with decoding; it saved ~30 ms at 200k.
    - Kernel buffers are 256 KiB instead of 64 KiB: 80.8 ms against 88.6 ms for 200k entries, with 1 and 4 MiB not faster.
    - Two key builders replace one K thread; keys now finish 2–4 ms after E instead of 10–20 ms.
    - The sort is a most-significant-first chunk sort on up to eight threads instead of a stable parallel merge on four. An incremental run merge measured 165 ms on long shared stems.
    - Single-batch folders run without threads: 0.33 ms against 0.53 ms before for 256 entries, where the threaded pipeline cost 0.93 ms.
  - The hook is `Column.order(listing, ascending)` without `check`: the native order costs about 1 ms.
  - The GIL is held at most 4 ms before a 1 ms release, instead of 12 ms.
  - Win32 errors are raised as `ctypes.WinError` raises them, `OSError(None, message, None, winerror)`, which is unchanged behavior. The Final Design said `OSError(0, message, path, winerror)`.
  - No `validate_fsenum.py`: crafted buffers, links, Unicode and surrogate names, cancellation and errors are in `test_fsenum`; real folders go through `benchmark_fsenum.py`.
- **Validation Results**:
  - `python src\main\rust\fsenum\build_fsenum.py --test`: 14 Rust tests pass, 2 ignored benchmarks. The module is rebuilt and recorded, and the import check passes.
  - `python src\main\rust\fsenum\check_hashes.py`: the pairing holds. `python src\main\rust\fsenum\generate_unicode.py --check`: Unicode 16.0.0 is current.
  - Through `build._environment()` with `QT_QPA_PLATFORM=offscreen`:
    - `unittest core.tests.fs.test_fsenum core.tests.fs.test_local core.tests.commands.test___init__ fman_unittest.test_listing fman_integrationtest.impl.model.test___init__ fman_unittest.test_app_name fman_unittest.test_everything`: 404 tests OK, 4 skipped.
    - `unittest fman_integrationtest.test_qt fman_unittest.test_application_context fman_unittest.test_favorites fman_unittest.test_search_file_fuzzy`: 439 tests, 4 failures. All four also fail on a clean `HEAD` worktree in the same environment: `PatternSelectionIT` geometry, `QuickBoardMappingIT` text elision, `RobocopyIT` text fit, and `WindowsCleanupIT` archive clipboard (order-dependent; it passes alone).
  - `python src\misc\benchmark_fsenum.py <flat-large-v1> C:\Windows\System32 C:\Users C:\Windows <flat-small-v1>`: parity holds on all five, including the system junctions under `C:\Users`. At 200k: kernel 90–103 ms, scan 103–121 ms, unchanged rescan 82–100 ms, native order and hidden filter 1.3 ms, Python reference 1.9–2.1 s.
  - `python src\performancetest\run.py suite --test pane.load.large --test pane.load.small`: the final build against clean `HEAD` (a temporary worktree with the same fixtures, harness and machine; three fresh processes each):

    | Workload | Metric | `HEAD` | This task |
    | --- | --- | ---: | ---: |
    | `pane.load.large` | complete | 425.0 ms | 133.9 ms |
    | `pane.load.large` | first paint | 458.3 ms | 158.7 ms |
    | `pane.load.large` | working set | 155.5 MiB | 155.1 MiB |
    | `pane.load.small` | complete | 41.4 ms | 24.8 ms |
    | `pane.load.small` | first paint | 66.5 ms | 65.9 ms |

  - Python heartbeat thread during 200k scans: largest gap 7.4–13.2 ms. During unchanged rescans: 3.3–3.8 ms, and the rescan returns the same object.
  - Not run: `build.py freeze` and `package` (operator approval), 1M entries, `refresh.large`, and `build.py measure`.
- **Acceptance status**:
  - Load: complete is 133.9 ms, but first paint is 158.7 ms against the ≤ 150 ms criterion. The scan now ends 10–15 ms after the kernel enumeration. The remainder is the Qt commit (~13 ms) and the first paint (~22 ms), which cost the same for 256 entries: view-layer work for FSPaneArch003 P1.
  - Responsiveness, Refresh (unchanged), Parity and Robustness: met as measured above.
  - Memory: about 51 bytes per entry plus names in segments, plus 4 bytes of order and one tie bit; the working set is unchanged.
  - Packaging: the hash-verified binary and its notices are in place. The frozen build is not verified.
  - The uncommitted `.gitignore` line `*.pyd` (not from this task) ignores `src/main/rust/fsenum/_fsenum.pyd`. Committing it needs `git add -f` or an exception.

### Implementation Review - Gemini 4 Neon

- Date: 2026_11_26
- Agent: GitHub Copilot
- Model: Gemini 4 Neon
- Effort: High
- Context Window: 1M

- **Verdict**: Changes requested
- **Findings**:
  - **Strengths**: The zero-dependency Rust crate is clean, compact (~476 KiB, importing only inbox Windows DLLs + `python3.dll`), and delivers a large measured speedup (`pane.load.large` complete 425.0 → 133.9 ms, first paint 458.3 → 158.7 ms; `C:\Windows\System32` 3.34 ms vs 20.68 ms Python reference) at ~55 bytes/entry retained native memory. Channel teardown in `pipeline.rs` is deadlock-free, `Final_Sigma` / `natural_keys` matched Python with 0 mismatches across all 1,114,112 code points probed before, after, and between `U+03A3`, and all 318 focused unit/model tests plus `check_hashes.py`, `generate_unicode.py --check`, and `benchmark_fsenum.py` (`C:\Windows\System32`, `C:\Users`) pass.
  - **IR1 - High: Undefined Behavior in `without_attributes` on empty folders ([python.rs](../src/main/rust/fsenum/src/python.rs))**.
    - An empty `array('I')` has `ob_item == NULL` (verified empirically: `Name().order(empty_listing, True).buffer_info() == (0, 0)`). `PyObject_GetBuffer` returns `view.buf = NULL, view.len = 0`, and `without_attributes` passes `view.buf` directly to `std::slice::from_raw_parts(view.buf.cast::<u8>(), view.len as usize)` — unconditional Rust Undefined Behavior (`slice::from_raw_parts` requires a non-null pointer even for length 0). Every empty NTFS folder with the default hidden-file filter hits this path. Guard `view.len == 0` (and reject `view.len < 0`) before constructing the slice; apply the same zero-length guard in `parse_batches` and `wide`.
  - **IR2 - High: Silent name corruption in `Segment::push` for `units >= 32768` ([segment.rs](../src/main/rust/fsenum/src/segment.rs))**.
    - `self.name_meta.push(units as u16 | if record.latin1 { 0 } else { UTF16 })` packs `UTF16 = 0x8000` into bit 15, leaving 15 bits (`0..=32767`) for UTF-16 code units, while `record::for_each` accepts any even `u32` `FileNameLength`. Verified empirically: passing a 32,768-character (`65,536`-byte) record to `_fsenum.parse_batches` overflows into `UTF16` and silently returns `""` (`len == 0`) instead of raising an error. Enforce `units < UTF16 as usize` (`name_length < 65536`, matching Win32 `UNICODE_STRING`) and `u32::try_from(start)` explicitly so `Segment::push` can never silently truncate or flip the encoding bit.
  - **IR3 - Medium: Cancellation ignored during sort/key catch-up wait, and unchunked tuple drop on late `order` failure ([python.rs](../src/main/rust/fsenum/src/python.rs))**.
    - When `previous` differs late in a large folder, `materialize` copies the unchanged prefix and `into_tuples` finishes quickly while `K` + `S` still have to key and sort the whole folder. `scan_folder` then blocks in `shared.wait(None, |state| state.ordered.is_some(), |_| ())` without waking on `WAKE` to call `check_canceled()`, ignoring cancellation for the entire key/sort catch-up window.
    - If `state.ordered` returns `Err` (or `identities`/`table_capsule` fails) after `into_tuples()` succeeded, `tuples: Vec<Owned>` drops in one unchunked GIL-held burst instead of sliced `discard()`, risking > 5 ms GIL holds on error at 200k–1M entries.
  - **IR4 - Medium: Redundant `FILE_BASIC_INFO` syscall in `follow_link` ([pipeline.rs](../src/main/rust/fsenum/src/pipeline.rs))**.
    - `follow_link` calls both `GetFileInformationByHandle` and `GetFileInformationByHandleEx(FILE_BASIC_INFO)` and discards the update if either fails. `ByHandleFileInformation` already returns `information.write` (the same 64-bit 100 ns `FILETIME`), so the second syscall adds extra kernel work per link and can fail with `ERROR_INVALID_FUNCTION` on targets hosted on non-NTFS/virtual/network drivers where `os.stat` succeeds.
  - **IR5 - Medium: `name_order` misorders NUL characters, plus test/acceptance gaps ([sort.rs](../src/main/rust/fsenum/src/sort.rs), [test_fsenum.py](../src/main/resources/base/Plugins/Core/core/tests/fs/test_fsenum.py))**.
    - Verified empirically: `_fsenum.name_order(['a\x00', 'a'], [False, False], True)` returns `[0, 1]` instead of `[1, 0]` because `chunk_at` zero-pads past end. Real `scan()` rejects `\0` in `record::for_each`, so folder tables are safe, but `name_order` should reject `\0` with `ValueError` rather than silently misordering.
    - Missing regression tests: empty-folder `Name().order` + `without_attributes`, `Name().order` returning `None` when `listing.labels is not None` or `_native is None`, and a check that `parse_batches` rejects `name_length >= 65536`.
    - Open acceptance gates (transparently noted by Implementer, still required before moving to `Done/`): `refresh.large`, 1M-entry responsiveness/memory, operator-approved `build.py freeze` / `package` verification, and operator sign-off on `pane.load.large` first paint (`158.7 ms` vs `≤ 150 ms`).
  - **IR6 - Low: Stale docstring and minor doc formatting**.
    - [core/fs/local/windows/listing.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py) (`records()` docstring) still cites non-existent `src/misc/validate_fsenum.py` (should be `src/misc/benchmark_fsenum.py`).
    - [CHANGELOG.md](../CHANGELOG.md) is missing a blank line before `## [0.21.0] - 2026-11-23`.
    - Note: `.gitignore` already comments out `# *.pyd` and `# *.py[cod]`, resolving the Implementer's closing note about `_fsenum.pyd`.
- **Required Changes**:
  1. Fix IR1 (`without_attributes` null-pointer UB on empty buffers; also guard zero-length slices in `parse_batches` and `wide`) and add an empty-folder `Name().order` + hidden-filter test.
  2. Fix IR2 (reject `units >= UTF16` / `name_length >= 65536` and checked `u32` offsets in `segment.rs` / `record.rs`) and add a regression test in `test_fsenum.py`.
  3. Fix IR3 (poll `check_canceled()` while waiting for `state.ordered`, and ensure `tuples` is not dropped in one unchunked GIL burst if `state.ordered` or final assembly fails).
  4. Fix IR4 (read `modified` from `ByHandleFileInformation.write` in `follow_link`, dropping the redundant `FILE_BASIC_INFO` call).
  5. Fix IR5 & IR6 (reject `\0` in `name_order`, add the missing `Name.order` fallback tests, fix the stale `validate_fsenum.py` reference in `listing.py` and the blank line in `CHANGELOG.md`), rebuild `_fsenum.pyd` with `build_fsenum.py --test`, re-verify hashes and focused tests, and obtain operator decision on the remaining gates (`refresh.large`, 1M, `freeze`/`package`, and the 158.7 ms vs 150 ms first-paint criterion).
- **Review Validation**:
  - `python src\main\rust\fsenum\check_hashes.py` — passed (`_fsenum.pyd matches its sources`).
  - `python src\main\rust\fsenum\generate_unicode.py --check` — passed (`Unicode 16.0.0`).
  - DLL import inspection via `pefile` on `_fsenum.pyd` — 476,160 bytes; imports only `api-ms-win-core-synch-l1-2-0.dll`, `kernel32.dll`, `msvcrt.dll`, `ntdll.dll`, `python3.dll`.
  - `python -c "import build, os, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM'] = 'offscreen'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_fsenum', 'core.tests.fs.test_local', 'core.tests.commands.test___init__', 'fman_unittest.test_listing', 'fman_integrationtest.impl.model.test___init__'], env=env).returncode)"` — 318 tests OK, 4 skipped.
  - `python src\misc\benchmark_fsenum.py C:\Windows\System32 C:\Users --repeat 3` — parity holds on both (`System32`: 4,747 entries, scan 3.34 ms vs Python 20.68 ms; `Users`: 6 entries, scan 0.27 ms).
  - Targeted Python probes confirmed: 0 `Final_Sigma` mismatches across all 1,114,112 code points before/after/between `U+03A3`; `follow_link` `share=0` with `FILE_READ_ATTRIBUTES` succeeds on open/exclusive files; IR1 (`array('I').buffer_info() == (0, 0)` on empty folder); IR2 (`32768`-char name returns length `0`); IR5 (`name_order(['a\x00', 'a'], [False, False], True) == [0, 1]`).
  - No application code changed. Not run: `cargo test` (direct Rust rebuild), `refresh.large`, 1M fixture, `build.py freeze`, `build.py package`.


### Implementation Review - Claude Fable 5.2

- Date: 2026_11_26
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M

- **Verdict**: Changes requested. They are made in Review Fixes below.
- **Findings**: Read every file of the crate, the Core and host integration, the tests, the gauge and the build scripts. The findings come from disposable probes and from A/B runs of the binary as found against rebuilt ones, loaded side by side and alternating. The numbers are in Review Fixes.
  - **Status of the Gemini 4 Neon findings**:
    - IR1: not reproduced as stated. `PyObject_GetBuffer` on an empty `array('I')` returns a non-null pointer (CPython's `emptybuf`); `buffer_info()`, which that review read, reports the raw `ob_item`. `bytes`, `bytearray` and `PyUnicode_AsWideCharString` always return storage too, so `parse_batches` and `wide` need nothing. The buffer protocol as such does not promise a pointer for an empty buffer, so one guard in `without_attributes` is right. Low, not High.
    - IR2: confirmed. A name of 32,768 units comes back empty and one of 40,000 units with 7,232 characters, for Latin-1 and UTF-16 names alike.
    - IR3: confirmed. With the first difference at the last of 120,000 entries, a cancel request waited up to 25.5 ms for the keys and the sort.
    - IR4: rejected. `follow_link` makes the two queries `os.stat` makes for a followed link (`win32_xstat_slow_impl`) and fails when either fails. That is the contract of this task: the entry gets what `os.stat` reports, or keeps its own values. Without the second query the entry would get values where `os.stat` raises. It costs one query per link, not per entry.
    - IR5: confirmed for `name_order`, which only tests call. The scan rejects NUL in names.
    - IR6: confirmed. `_UNSUPPORTED` in `listing.py` is also unused: the native module owns that list.
  - **F1 - High, performance: the kernel buffer size**. A directory query with a buffer of 65,536 bytes or more costs 1.4 to 2.4 times as much per record while the folder's files have recently been created, read or opened. A query with a smaller buffer does not. The step is exact: 46 ms at 65,535 bytes and 88 ms at 65,536 bytes for the same 200,000 entries. The performance suite reads every fixture file before it measures, so the 256 KiB buffer of this task was chosen and measured in the slow state: "81 ms instead of 89 ms with 64 KiB" compared two slow sizes. Folders in use are what a file manager shows.
  - **F2 - Medium, performance: quadratic copying in `Sorter::add`**. It reserved exactly, so each segment reallocated and copied the whole group: 19 of 73 ms of key time for one builder at 200,000 entries, growing with the square of the entry count.
  - **F3 - Medium, performance: the tail after the last batch**. The two builders' items were concatenated before the sort (1.2 ms). The 49 key buffers of about 1 MiB each were freed before the order was published (2.5 ms). P built its result only after it had joined the key thread.
  - **F4 - Medium, performance: one bucket for keys that share their first bytes**. The sort splits its work by the first two key bytes. Digit-led names all start with zero padding, and names often share a short stem, so such folders were sorted on one thread.
  - **F5 - Low, robustness**: a sort thread that cannot start failed the scan, while a key helper that cannot start is tolerated.
  - **F6 - Medium, robustness: an empty volume root**. The first directory query of a folder without any entry fails with `ERROR_FILE_NOT_FOUND`, and only a volume root has no `.` and `..`. The scan raised `FileNotFoundError` for a folder that exists; `os.listdir` treats the same error of `FindFirstFileW` as an empty folder. The scanner before this task behaved the same. Not reproduced: it needs an empty NTFS root, which this session could not create without elevation.
  - **F7 - Low, robustness**: keys of UTF-16 names grew the key buffer with infallible pushes, so memory exhaustion there would abort the process instead of raising `MemoryError`.
  - **F8 - Low, responsiveness**: `into_tuples` started a new GIL budget, so the last segments and the first columns could hold the GIL for two budgets in a row.
  - **F9 - Low, tooling: the build was not reproducible**. Two compilations of the same sources differed in three bytes: the PE time stamp, the checksum over it and the export directory's time stamp. "A rebuild of identical sources gives an identical binary" held only while cargo reused its output.
  - **F10 - Low, tooling**: the gauge's `kernel` figure included a copy of every batch into a `bytes` object: 96.6 ms where the calls took about 81 ms.
  - **Checked and kept**:
    - The reader thread: decoding on the reader's own thread takes 94 ms against 65 ms, and two buffers in flight are slower than four.
    - Zero-filling each buffer before reuse: no measurable cost, and a malformed chain then fails instead of reading the previous batch.
    - `follow_link` opens with share mode 0 and backup semantics, as `os.stat` does.
    - Channel teardown, the cancel flag, `difference` and the prefix reuse: no race found. A rescan after 112 cancelled scans equals a fresh scan.
  - **Open, not changed**:
    - A reader, enumerator or key thread that cannot start still fails the scan with `RuntimeError`.
    - `GetFinalPathNameByHandleW` takes 36 µs of the 130 µs a scan of an empty folder costs. It is the UNC check of the reference; the cheaper NT form would change which paths count as UNC.
    - Folders whose first key chunk is the same for every entry, and mixed folders with one dominant bucket, are still sorted on one thread. At 200,000 entries that is 5.6 ms when the enumeration order is close to the Name order, which NTFS usually gives, and 14 ms when it is shuffled. A recursive parallel sort would be needed.
    - P's tuple build (6.6 ms at 200,000 entries, 1.2 million `PyTuple_SetItem` calls) is the floor of the limited API. With the sort, which now ends at the same time, it is the tail.
- **Required Changes**:
  1. IR2, IR3, IR5, IR6 and the IR1 guard, each with a test where one can reach it.
  2. F1: a buffer below 64 KiB, with the thread-free path kept for the folders that fit one 256 KiB batch today.
  3. F2 to F5: amortized growth, one key buffer per builder, no merge copy, buckets after the shared leading bytes, the keys freed after the order is published, a shared work list for the sort.
  4. F6 to F10.
- **Review Validation**: the probes and commands are listed under Validation Results in Review Fixes. Nothing was changed for this record.

### Review Fixes - Claude Fable 5.2

- Date: 2026_11_26
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M

- **Changes**:
  - [pipeline.rs](../src/main/rust/fsenum/src/pipeline.rs):
    - F1: `BUFFER_BYTES` is 60 KiB instead of 256 KiB; the comment has the measurements.
    - F1: `open` reads up to five batches on the calling thread instead of two: four with entries (240 KiB, about the one 256 KiB batch before) and the call that ends the folder. A longer folder keeps these five buffers in flight; the reader allocates none, so `BUFFERS` and its on-demand allocation are gone.
    - F6: `ERROR_FILE_NOT_FOUND` from the first directory query ends the folder.
    - F3: `order` publishes the order and frees the keys afterwards. `append_key` replaces `segment_keys`. F7: its UTF-16 path reserves 7 bytes per unit before it writes, as the Latin-1 path does.
  - [sort.rs](../src/main/rust/fsenum/src/sort.rs):
    - F2: reservations are amortized.
    - F3: a `Sorter` is one builder's share and keeps the keys of all its segments in one buffer. `Sorter::add(index, is_dir, append)` appends them. `Sorter::finish(builders, threads)` sorts from the builders' item lists without concatenating them and leaves the keys to the caller. `merge` is gone.
    - F4: the buckets are the two bytes after the leading bytes every first chunk shares.
    - F5: the bucket ranges are a work list that the calling thread and the helpers take from. A helper that cannot start leaves its range to the others, and a range without items starts no thread.
  - [record.rs](../src/main/rust/fsenum/src/record.rs), [segment.rs](../src/main/rust/fsenum/src/segment.rs) and `records()` in [listing.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py): IR2. A name longer than 32,767 units, the longest Windows path, is an invalid record on both sides; NTFS and ReFS names have at most 255 units. Its length then fits the 15 bits of `name_meta`, and a segment's names stay below 4 GiB.
  - [python.rs](../src/main/rust/fsenum/src/python.rs):
    - IR3: `await_order` waits for the order with the GIL released and calls `check_canceled` every 10 ms.
    - IR3: `Columns` and the new `Tuples` release their objects in GIL-bounded slices when dropped, on every exit path. `discard` and its explicit call are gone. Abandoned tuples first give up their items with `PyTuple_SetItem(..., NULL)`. Tuples left by a failure are released after the threads have stopped.
    - F8: `into_tuples` continues the GIL budget of the last segments.
    - F3: `columns_and_table` builds the result before the threads are joined, while the key thread frees its keys.
    - IR1: `without_attributes` takes no slice from an empty buffer. IR5: `name_order` raises `ValueError` for a name with NUL.
  - [build_fsenum.py](../src/main/rust/fsenum/build_fsenum.py): F9. The linker gets `--no-insert-timestamp`. Four forced compilations, one of them with LF line endings, gave the same binary. A comment-only change afterwards changed the source digest and not the binary.
  - [benchmark_fsenum.py](../src/misc/benchmark_fsenum.py): F10. `kernel` times the calls alone, with the module's buffer size.
  - [listing.py](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py): IR6. The docstring names the gauge, and the unused `_UNSUPPORTED` is removed.
  - Tests:
    - `core.tests.fs.test_fsenum`: the longest name and one unit more against `records()`; `name_order` with digit-led names, a short stem and a stem longer than a chunk; NUL rejected; an empty folder with its order and hidden filter, and `Name.order` returning `None` without a table; cancellation at every `check_canceled` call until a scan needs no further one. `test_code_points_across_planes` starts at U+0001: U+0000 cannot be a name.
    - Rust: the name bound; buckets for keys that share 6, 7 and 8 leading bytes, on four threads; an ignored benchmark of the sort on six name shapes.
  - Docs: the crate [README](../src/main/rust/fsenum/README.md) (batches, buffer size, reproducible build) and the blank line in [CHANGELOG.md](../CHANGELOG.md).
- **Deviations**:
  - The buffer is 60 KiB; the Final Design said 64 KiB and the implementation 256 KiB. The cost is nearly flat from 48 KiB up to the step at 64 KiB, and 60 KiB keeps a margin below it.
  - IR4 is not applied; see the review.
  - F6 is implemented from the documented status and CPython's handling of it, without a reproduction.
  - `CHANGELOG.md` keeps the load times of the first implementation (134 ms and 159 ms). Today's suite gives 99 ms and 125 ms, but the release baseline was not measured again on the same day.
  - No `## Final Implementation` yet: the gates under Acceptance status are the operator's.
- **Validation Results**:
  - `python src\main\rust\fsenum\build_fsenum.py --test`: 16 Rust tests pass, 3 ignored benchmarks; recorded source `d8322e32…`, binary `41f57694…`. `python src\main\rust\fsenum\check_hashes.py` and `python src\main\rust\fsenum\generate_unicode.py --check` pass.
  - `python -c "import build, os, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM'] = 'offscreen'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_fsenum', 'core.tests.fs.test_local', 'core.tests.commands.test___init__', 'fman_unittest.test_listing', 'fman_integrationtest.impl.model.test___init__', 'fman_unittest.test_app_name', 'fman_unittest.test_everything'], env=env).returncode)"`: 408 tests OK, 4 skipped. The first five modules alone ran 322 tests, 318 before this review.
  - The same launcher with `fman_integrationtest.test_qt fman_unittest.test_application_context fman_unittest.test_favorites fman_unittest.test_search_file_fuzzy`, six times:
    - Four runs: 439 tests, the four failures recorded above as failing on `HEAD`.
    - One run: a fifth failure, `EverythingFoldersIT.test_f5_drop_navigation_and_refusal_do_not_mutate_target_files`. `EverythingFoldersIT` alone failed in 5 of 105 runs with this binary and in 6 of 80 with the binary as found: its `manage` helper sometimes reads the pane's location before the navigation has finished.
    - One run, the first, with the build before the last change to `open`: it stopped making progress and was ended after 16 minutes. The process had four threads, all waiting, so no scan thread was among them. Not reproduced; the cause is unknown.
  - `python src\misc\benchmark_fsenum.py target\performance\fixtures\flat-large-v1\data C:\Windows\System32 C:\Windows\WinSxS C:\Users C:\Windows target\performance\fixtures\flat-small-v1\data --repeat 15`: parity holds on all six. At 200,000 entries: kernel 48.5 ms, scan 62.4 ms, unchanged rescan 55.5 ms, order and hidden filter 1.3 ms.
  - Kernel enumeration alone (`ctypes`, the module's calls, medians of 5 to 9 runs that alternate the sizes), in milliseconds:

    | Folder and state | 60 KiB | 64 KiB | 256 KiB |
    | --- | ---: | ---: | ---: |
    | `flat-large-v1`, 200,000 entries, at the start of the session | 47.3 (63 KiB) | 88.0 | 80.6 |
    | `flat-large-v1`, files not used for a while | 47.3 | 49.1 | 43.8 |
    | `flat-large-v1`, every file just read, as the suite verifies it | 47.1 | 69.1 | 63.9 |
    | 120,000 files, one minute after they were created | 22.6 | 54.0 | 49.9 |
    | 7,448 files of an installed package, as found | 1.45 | 1.47 | 1.38 |
    | The same, every file opened once for its attributes | 1.15 | 1.88 | 1.79 |
    | `C:\Windows\System32`, 4,747 entries | 1.15 | 1.52 | 1.51 |

    The slow state ended after some minutes of other file activity for the new folder and for `C:\Windows\WinSxS`, and lasted more than eight minutes for the opened package folder. A second handle or a change watcher on the folder does not cause it. Why NTFS does this was not determined.
  - Scan and unchanged rescan, the binary as found against the recorded one (medians of 31 runs, alternating; results identical):

    | Folder and state | Scan before | Scan after | Rescan before | Rescan after |
    | --- | ---: | ---: | ---: | ---: |
    | `flat-large-v1`, files just read | 83.8 ms | 62.8 ms | 70.9 ms | 53.3 ms |
    | 120,000 files created minutes before | 59.6 ms | 36.6 ms | 53.8 ms | 36.7 ms |
    | `C:\Windows\System32`, 4,747 entries | 2.61 ms | 2.27 ms | 2.27 ms | 1.85 ms |
    | `flat-small-v1`, 256 entries, files just read | 0.36 ms | 0.33 ms | 0.26 ms | 0.21 ms |

    Measured with the build before the last change to `open`: for `flat-large-v1` with files not used for a while, the scan took 62.5 ms against 63.2 ms and the unchanged rescan 54.7 ms against 52.4 ms. There the smaller buffer costs about 4 ms of kernel time, which the shorter tail returns to the scan and not to the unchanged rescan. An earlier build of the new pipeline with the old buffer took 61.5 ms against 62.6 ms.
  - Folders of 0 to 8,000 files created just before, the binary as found against the recorded one, twice each in turn: faster at every size. For example 1,500 names of 24 characters 0.77 ms to 0.59 ms, and 8,000 names of 100 characters 5.2 ms to 3.3 ms.
  - `python src\performancetest\run.py suite --test pane.load.large --test refresh.large --results <a folder outside the repository>`, once with each binary in place, back to back (three fresh processes each):

    | Workload | Metric | Binary as found | This review |
    | --- | --- | ---: | ---: |
    | `pane.load.large` | complete | 115.3 ms | 99.2 ms |
    | `pane.load.large` | first paint | 140.7 ms | 124.8 ms |
    | `pane.load.large` | working set | 155.9 MiB | 155.4 MiB |
    | `refresh.large` | unchanged refresh to paint | 90.3 ms | 74.5 ms |
    | `refresh.large` | the seven other refresh cases to paint | 88.8–102.1 ms | 72.2–85.6 ms |
    | `refresh.large` | peak working set | 183.3 MiB | 182.6 MiB |

    An earlier pair, with the build before the last change to `open`, gave 112.5 ms and 137.9 ms against 93.0 ms and 120.4 ms. `pane.load.small` with `--repeat 9`, twice per binary in turn, that build: complete 26.4 and 26.4 ms against 28.0 and 26.5 ms, first paint 65.6 and 64.3 ms against 64.3 and 65.4 ms; single repetitions of complete spread from 22 to 41 ms in every run.
  - Sort and keys (`cargo test --release … bench_keys_and_sort bench_name_shapes -- --include-ignored --nocapture --test-threads=1`, `FSENUM_BENCH` set to `flat-large-v1`): for one builder, keys 73 ms to 60 ms, sort 8.3 ms to 5.5 ms, freeing the keys 2.5 ms to 1.0 ms. For 200,000 generated names on eight threads: numbers of varying width 4.0 ms and a short stem with such numbers 4.5 ms, against 5.6 ms and 9.0 ms on one thread, which is what one bucket gets.
  - Cancellation and responsiveness (disposable probe: a rescan of 120,000 entries whose first difference is the last entry, a cancel request every millisecond over its duration, a heartbeat thread that needs the GIL every 0.5 ms), the binary as found against the recorded one:
    - Requests in the last quarter of the rescan stopped it within 7.9 ms, 25.5 ms before.
    - Largest heartbeat gap: scan 4.4 ms (4.2 ms before), unchanged rescan 3.0 ms (3.0 ms), late-change rescan 5.9 ms (8.1 ms), across the cancelled scans 7.7 ms (13.9 ms).
  - References (disposable probe): 112 cancelled late-change rescans, 37 of them while the order was awaited, left the reference counts of sampled names and values of the previous listing unchanged, and the next rescan equalled a fresh scan.
  - Not run: `python build.py test`, `freeze`, `package`, `measure` and `doc`; 1M entries; an empty volume root (F6).
- **Acceptance status**:
  - Load: `pane.load.large` first paint is 124.8 ms and complete 99.2 ms in today's suite run, within the 150 ms criterion. The binary as found gave 140.7 ms today against the 158.7 ms recorded above, so the operator's `build.py measure` decides.
  - Refresh: `refresh.large` is reported above against the binary as found. A release baseline was not measured.
  - Responsiveness, Parity and Robustness: as measured above. Memory: the working set is unchanged.
  - Open, as before: 1M entries, `build.py freeze` and `package`, and the operator's sign-off.

### Implementation Review - Claude Opus 5.5

- Date: 2026_11_26
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 1M

- **Verdict**: Approved with changes. Fable's Review Fixes are kept; OR1 and OR2 below are handled in the next section.
- **Findings**:
  - **Gemini 4 Neon**:
    - IR2, IR3 and IR5 are real defects of my implementation.
    - IR1's severity was overstated: `array.buffer_info()` reports the raw `ob_item`, while the buffer protocol hands out CPython's `emptybuf`. The guard is still right.
    - IR4 is correctly rejected: `os.stat` makes the same two queries (`win32_xstat_slow_impl`).
  - **Claude Fable 5.2**: measured every finding with A/B runs and applied the fixes. F1, the buffer size, is the main gain. F9 corrects my claim of a reproducible build, which held only while cargo reused its output. IR2, IR3, F2 (quadratic copying) and the 256 KiB choice in F1 were my errors. I measured only sizes of 64 KiB and above, so I missed the step below 64 KiB.
  - **Re-checked here, with the binary Fable recorded**:
    - `python src\main\rust\fsenum\check_hashes.py`: the pairing holds.
    - A forced recompile with `build_fsenum.py --test --no-record` gave a byte-identical binary (`41f57694…`), so F9 holds; 16 Rust tests pass.
    - F1 reproduced with `ctypes`, on `flat-large-v1`, as found and after reading every file. Kernel enumeration, medians of 7:

      | State | 61,440 B | 65,535 B | 65,536 B | 262,144 B |
      | --- | ---: | ---: | ---: | ---: |
      | As found | 47.1 ms | 46.9 ms | 70.5 ms | 64.1 ms |
      | After reading every file | 46.6 ms | 46.4 ms | 69.4 ms | 63.5 ms |

    - The focused unit tests (the seven modules of Fable's run): 408 OK, 4 skipped.
    - `benchmark_fsenum.py` on `flat-large-v1`, `System32`, `C:\Users` and `C:\Windows`: parity holds. At 200,000 entries: kernel 48.7 ms, scan 62.4 ms (103–121 ms in my implementation), unchanged rescan 55.9 ms.
    - Read the riskiest changes. `PyTuple_SetItem(tuple, i, NULL)` is valid on a tuple's only reference. `await_order` calls `check_canceled` every 10 ms. `ERROR_FILE_NOT_FOUND` ends a folder only on the first query, as `FindFirstFileW` does.
  - **OR1 - Low, parity: link targets where `os.stat` succeeds without the target's metadata**. CPython's `win32_xstat_slow_impl` has two branches `follow_link` did not mirror:
    - When either query fails with `ERROR_INVALID_FUNCTION`, `ERROR_INVALID_PARAMETER` or `ERROR_NOT_SUPPORTED`, `os.stat` returns a zeroed block device. `follow_link` kept the link's own values. Reproduced with a junction to `\??\C:`, the volume itself: `os.stat` gives `(False, 0, 0)` and the scan gave `(True, 0, <the link's mtime>)`. Both reviews missed it.
    - When the open fails with `ERROR_INVALID_PARAMETER`, `os.stat` retries with `GENERIC_READ` and read/write sharing, for console devices. Junctions to `\??\CON` and `\??\CONIN$` make `os.stat` raise `ERROR_INVALID_REPARSE_DATA` instead, so this branch could not be reached here.
    - The other branches match: access denied, unhandled tags and non-disk handles.
  - **OR2 - Open: an intermittent hang in the Qt integration modules**. The set `fman_integrationtest.test_qt`, `test_application_context`, `test_favorites` and `test_search_file_fuzzy` normally takes 54–64 s. It stopped making progress once in my implementation session (stopped after more than 10 minutes, without a thread dump; I did not report it then) and once in Fable's (16 minutes, four waiting threads, no scan thread). `HEAD` had been run once, so it was unknown whether the hang predates this task.
- **Required Changes**:
  1. OR1: mirror both branches in `follow_link`, with a test where it can be reached.
  2. OR2: run the module set repeatedly on this tree and on a clean `HEAD` worktree, with thread dumps, to find whether this task causes the hang.
  3. Move the open operator gates (`build.py measure`, `freeze`, `package`, 1M entries, an empty volume root) and the deferred items to [Directory Enumerator 002](../Plan/DirectoryEnumerator002.md), then close the task.
