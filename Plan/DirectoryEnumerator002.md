# Directory Enumerator 002: Release Gates and Follow-ups

This task closes what [Directory Enumerator 001](../Done/DirectoryEnumerator001.md) left open:
- the operator-approved measurements and frozen build;
- the 1,000,000-entry and empty-volume-root checks;
- four small deferred changes to the native enumerator `_fsenum`.

It adds no feature. The plug-in API, the `Listing` contract and parity with the reference scan (`records()` plus `os.stat` for links) stay as they are.

## Task & Guidelines

- **Goal**: Operator direction (2026-11-26): collect the remaining items of Directory Enumerator 001 in one task instead of `TODO.md`. Release `_fsenum` with measured and verified numbers, and settle each deferred item.
- **Scope**:
  - **Included**:
    - Release gates, each needing operator approval:
      - G1: `python build.py measure`, then the `CHANGELOG.md` load times.
      - G2: `python build.py freeze` and `python build.py package`.
    - Checks not yet made:
      - C1: a folder of 1,000,000 entries.
      - C2: an empty NTFS volume root.
    - Deferred changes:
      - D1: thread-start fallback.
      - D2: parallel sort of a dominant bucket.
      - D3: the tuple build.
      - D4: the scope check's path query.
  - **Excluded**:
    - The native Filter Bar, change sets and Qt model work: FSPaneArch003 tasks.
    - Native Size and Modified sorting.
    - UNC, FAT and exFAT enumeration.
  - **Compatibility**:
    - Every change to `src/main/rust/fsenum` is rebuilt and recorded with `python src\main\rust\fsenum\build_fsenum.py --test`.
    - `core.tests.fs.test_fsenum` and `src/misc/benchmark_fsenum.py` parity must hold.
- **Acceptance Criteria**:
  - G1: `build.py measure` reports `pane.load.large` first paint ≤ 150 ms and reports `refresh.large`. The load times in `CHANGELOG.md` are the measured ones.
  - G2: `freeze` and `package` pass their `_fsenum` checks, and the frozen application lists an NTFS folder through `_fsenum.pyd`.
  - C1: at 1,000,000 entries, the worst Qt heartbeat gap during load and refresh is ≤ 16 ms, and the working set is reported against 0.21.0.
  - C2: an empty NTFS volume root lists as empty, without an error.
  - D1–D4: each change lands with a measurement and a test, or is recorded here as rejected with the reason.

## Design Review

### Initial Design - Claude Opus 5.5

- Date: 2026_11_26
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 1M

- **Architecture & Data Flow**:
  - **G1, measurement**. Known numbers on the reference machine, from the performance suite (`src/performancetest/run.py suite`, three fresh processes):

    | Build | `pane.load.large` complete | first paint | `refresh.large` unchanged |
    | --- | ---: | ---: | ---: |
    | 0.21.0 (`HEAD`) | 425.0 ms | 458.3 ms | not measured |
    | Directory Enumerator 001, first build | 133.9 ms | 158.7 ms | 90.3 ms |
    | After the Claude Fable 5.2 review fixes | 99.2 ms | 124.8 ms | 74.5 ms |

    `CHANGELOG.md` still quotes the first build: complete in 134 ms instead of 425 ms, first paint after 159 ms instead of 458 ms. Replace both with the `build.py measure` results.
  - **G2, frozen build**. `application.spec` bundles `src/main/rust/fsenum/_fsenum.pyd` as a binary, so PyInstaller also collects `python3.dll` (abi3). `build.py` checks the source pairing in `freeze` and the frozen copy in `package` (`_verify_native_enumerator_packaged`). After `package`, open the frozen application on an NTFS folder and on `C:\Windows\System32`, and check the order and the hidden-file filter.
  - **C1, 1,000,000 entries**. The suite has no such fixture; create a disposable folder like `flat-large-v1`, outside the repository. Measure:
    - the scan and rescan with `benchmark_fsenum.py`;
    - the Qt heartbeat during load and refresh, with the pane benchmark or a heartbeat probe;
    - the peak and settled working set.

    Native retention is about 51 bytes per entry plus names; the Python column objects dominate.
  - **C2, empty volume root**. Only a volume root has no `.` and `..` entries. Its first directory query fails with `ERROR_FILE_NOT_FOUND`, which `read_batch` now treats as the end of the folder, as `FindFirstFileW` and `os.listdir` do. Never reproduced. Use an empty NTFS VHD (`New-VHD` and `Mount-VHD`, which need admin) or an NTFS-formatted USB stick, and compare with `os.listdir`.
  - **D1, thread-start fallback**. A reader, enumerator or key thread that cannot start fails the scan with `RuntimeError`. Key helpers and sort helpers already leave their work to the calling thread. Run the reader's, the enumerator's and the key builder's stage on the calling thread instead, in sequence, as the single-batch path does (`opened.complete()` in `python.rs`). Test it by injecting a spawn failure behind a test-only switch, or argue it unreachable and record the decision.
  - **D2, dominant bucket**. `sort.rs` splits work by the two key bytes after the leading bytes every first chunk shares. A folder whose names fall mostly into one bucket is sorted on one thread: 5.6 ms at 200,000 entries in near-Name enumeration order, 14 ms shuffled. A recursive split of an oversized bucket (its own common prefix, then the next two bytes) would use every thread. Measure with `bench_name_shapes` before and after.
  - **D3, tuple build**. P's 1.2 million `PyTuple_SetItem` calls take 6.6 ms at 200,000 entries, the limited API's floor; with the sort they form the scan's tail. Writing tuple memory directly would leave the limited API and was rejected in 001 for robustness. Likely outcome: rejected here and left to lazy columns (FSPaneArch003 P1).
  - **D4, scope check**. `GetFinalPathNameByHandleW` (DOS form) takes 36 µs of the 130 µs an empty folder costs; it is the reference's UNC check. The NT form is cheaper, but redirected drives (`\Device\Mup`, `\Device\LanmanRedirector`, WebDAV) would need their own rule, and parity with the reference's rule must hold. Change it only with a parity test over a mapped drive and a `subst` drive.
- **Alternatives Considered**: Keeping these as `TODO.md` items. The operator moved them here so the release gates and the deferred changes share one record and one review.
- **Runtime Effects**:
  - G1, G2, C1 and C2 change no code, unless C2 fails.
  - D1 adds a path only for a failed thread start.
  - D2 changes the sort's work split, not its result.
  - D3 and D4 are expected to be rejected or to be small.
  - No new background work, timers or I/O.
- **Planned Tests**:
  - G1, G2, C1, C2: the commands above, with results recorded here.
  - D1: a test with an injected spawn failure.
  - D2: the existing sort tests (stable-sort parity, ties, both directions) plus `bench_name_shapes`.
  - D4: if changed, the parity test above.
  - Every change: `core.tests.fs.test_fsenum`, `fman_unittest.test_listing` and `benchmark_fsenum.py` parity.

## Hand-off from Directory Enumerator 001 (2026_11_26, session ended)

- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 1M

Directory Enumerator 001 is **not closed yet**. It is still at `Plan/DirectoryEnumerator001.md`, and links to `../Done/DirectoryEnumerator001.md` here and in `TODO.md` and `FSPaneArch003.md` resolve only after the move.

**Done in that session:**
- OR1, link parity, in `src/main/rust/fsenum/src/pipeline.rs` (`follow_link`) and `win.rs`:
  - When a query fails with `ERROR_INVALID_FUNCTION`, `ERROR_INVALID_PARAMETER` or `ERROR_NOT_SUPPORTED`, the entry gets the zeroed block device `os.stat` reports.
  - When the open fails with `ERROR_INVALID_PARAMETER`, it is retried with `GENERIC_READ` and read/write sharing, as CPython's `win32_xstat_slow_impl` does.
  - Test: `ScanTest.test_link_to_a_device_reports_what_os_stat_reports`, a junction to `\??\C:`.
  - Rebuilt and recorded: binary `d54ac0cf…`, 16 Rust tests. `core.tests.fs.test_fsenum` and the other focused modules: 409 OK, 4 skipped.
- The Implementation Review - Claude Opus 5.5 section was appended to 001.
- TODO items moved here; FSPaneArch003 decision 1 marked settled.

**OR2, the hang probe.** A disposable harness ran the set `fman_integrationtest.test_qt`, `test_application_context`, `test_favorites` and `test_search_file_fuzzy`, alternating this tree and a clean `HEAD` worktree. Each run used `faulthandler.dump_traceback_later(120, repeat=True)` and was killed after 300 s. The results are in the final status below. The worktree was removed when the probe stopped. To repeat it, create a `HEAD` worktree with `git worktree add --detach`, and run each tree's own `build._environment()` with `QT_QPA_PLATFORM=offscreen`.

**Remaining steps to close 001**, in order:
1. Replace `Plan/DirectoryEnumerator001.md` with `Done/DirectoryEnumerator001.md` in: `build.py`, `application.spec`, `release.yml`, `benchmark_fsenum.py`, `fman/listing.py` (2), `core/__init__.py`, `windows/listing.py` (2), `test_fsenum.py`, and in the crate's `README.md`, `fsenum_hashes.py`, `Cargo.toml`, `src/lib.rs` and `src/python.rs`.
   - Some of the crate files are hashed sources. Re-run `build_fsenum.py --test` afterwards: the binary should stay `d54ac0cf…`, and only the source digest should change.
2. Append "Review Fixes - Claude Opus 5.5" (OR1, OR2) and `## Final Implementation` to 001, with provenance and validation results. Fix 001's relative links to sibling `Plan/` files, such as `(FSPaneArch003.md)` → `(../Plan/FSPaneArch003.md)`.
3. Move the file to `Done/`. In `Plan.md`:
   - move its entry from Pending to Completed, before "Directory Size";
   - remove the dangling Pending entry "Rust Directory Enumerator" (`Plan/RustDirectoryEnumerator.md` does not exist; it is the same subject);
   - keep this task under Pending.
4. `CHANGELOG.md` needs no new entry: these are fixes to an unreleased feature. Its load times are G1 above.

**Binary not committed (operator, 2026_11_26).** `src/main/rust/fsenum/_fsenum.pyd` is left out of the commit until this task and 001 are done and working.
- The committed `fsenum.sha256` therefore has no binary next to it, so `check_hashes.py`, `build.py test`/`freeze`/`package`, the release workflow and the `_fsenum` loader fail until it is rebuilt.
- First step of the next session: `python src\main\rust\fsenum\build_fsenum.py --test`, then `python src\main\rust\fsenum\check_hashes.py`. Rust 1.99.1 `x86_64-pc-windows-gnu` is needed.
- The build is reproducible, so the sources of this commit should give binary `d54ac0cf…`, unless the reference updates in step 1 have already been made. Those change only the source digest.
- Commit the binary (Git LFS) and `fsenum.sha256` together once everything passes.
- Without the binary, Core's import of `_fsenum` fails, so the application does not start from this commit. A push to `main` also runs `.github/workflows/pages.yml` (`build.py test-docs` and source-mode screenshots), which is expected to fail until the binary is committed. Push to a branch, or accept that failure. No release tag before then: `release.yml` fails at `check_hashes.py`.

**Hang probe, final (stopped at 05:58 for the move to another computer).** 15 runs, 8 on `HEAD` and 7 on this tree; none hung. Each took 52.9–60.5 s.
- Every run of this tree failed four tests, which also fail on `HEAD`:
  - `WindowsCleanupIT.test_explorer_archive_items_paste_and_drop_as_copies`
  - `QuickBoardMappingIT.test_optional_caller_status_and_trailing_debounce` (text elision)
  - `PatternSelectionIT.test_preview_paint_changes_not_selection_cursor_scroll_or_geometry` (geometry)
  - `RobocopyIT.test_progress_text_fits_and_status_stays_on_one_line`
- Every `HEAD` run failed five more archive tests, because the worktree lacked the `7za.exe` that `build.py` downloads.
- **New failure, this tree only, 1 of 7 runs (run 05)**: `ProcessPaneIT.test_real_registry_filter_sort_reload_and_f8`:

  ```text
  File "src/integrationtest/python/fman_integrationtest/test_qt.py", line 4836, in unload_process_plugin
    self.drain(pane)
  File ".../test_qt.py", line 2099, in drain
    self.drain_model(pane._model)
  File ".../test_qt.py", line 47, in drain_model
    self.fail('Snapshot model did not settle')
  AssertionError: Snapshot model did not settle
  ```

  - The pane leaves the process pane for a folder, so the native scan runs. `HEAD` passed it in 8 of 8 runs.
  - Run `ProcessPaneIT` alone about 20 times on each tree. If only this tree fails, debug the scan path while `drain_model` waits: the cancellation and order hand-off in `python.rs` (`await_order`, `Tuples` drop) and `LatestJobs` delivery.
- The 001-session hang (more than 10 minutes, no dump) and the Fable-session hang (16 minutes) remain unexplained, after 15 hang-free runs here.
- The logs stayed on the old computer; this section is their summary.

**Fixtures and test data on a new computer.** None of this is in Git: `target/` is ignored, and the data below was deleted with it.
- **Suite fixtures** `flat-small-v1` (256 files) and `flat-large-v1` (200,000 files, seed 1729, names of about 77 characters), defined in `src/performancetest/catalog.yaml`, are created and verified by the suite itself under `target/performance/fixtures/<id>/data`:

  ```powershell
  python src\performancetest\run.py suite --test pane.load.large --test pane.load.small --prepare-only
  ```

  - Allow about a minute for the large one.
  - Use an NTFS or ReFS drive; `--fixtures <folder>` puts them elsewhere.
  - `refresh.large`, `filter.large` and `selection.large` use the same `flat-large-v1`.
  - A suite run writes its record to `target/performance/runs/<uuid>.json`, which holds statistics only; read `results[i].summary.<metric>.median`.
- **The kernel state matters (F1 in 001).** Reading every fixture file, as the suite's verification does, puts NTFS in the slow state for buffers of 64 KiB and more. Measure the scan gauge in both states:
  - as found;
  - after `for e in os.scandir(folder): open(e.path, 'rb').read()`.
- **The gauge and Rust benchmarks** take any folder:
  - `python src\misc\benchmark_fsenum.py <flat-large-v1 data> C:\Windows\System32 C:\Users C:\Windows --repeat 9`
  - `cargo test --release ... bench -- --ignored --nocapture --test-threads=1`, with `FSENUM_BENCH=<flat-large-v1 data>` and the linker environment `build_fsenum.py` sets. See the crate README.
- **C1, 1,000,000 entries**: there is no catalog fixture, and adding one is a catalog revision. For a disposable folder outside the repository:
  - Fastest: write the files directly, in name batches. Names like `flat-large-v1`'s: about 77 characters, a shared stem with digits, some non-ASCII, a few folders.
  - Or call the suite's generator in `src/performancetest/python/fman_performancetest/fixtures.py` with `files: 1000000`.
  - 1M empty files take several minutes and about 1 GB of MFT on NTFS. Delete the folder afterwards.
- **C2, an empty volume root**: an elevated PowerShell can create one:

  ```powershell
  New-VHD -Path $env:TEMP\empty.vhdx -SizeBytes 64MB -Dynamic
  Mount-VHD $env:TEMP\empty.vhdx -Passthru | Initialize-Disk -PassThru | New-Partition -AssignDriveLetter -UseMaximumSize | Format-Volume -FileSystem NTFS
  ```

  - Hyper-V's `New-VHD` may be missing. Then use `diskpart` (`create vdisk`, `attach vdisk`, `create partition primary`, `format fs=ntfs quick`, `assign`) or an NTFS-formatted USB stick.
  - An empty NTFS root still holds `System Volume Information` and `$RECYCLE.BIN` (hidden, system) once Windows touches it. Check the first query's result before deciding that `ERROR_FILE_NOT_FOUND` handling ran.
- **Link and junction cases** need no fixture:
  - `test_fsenum` creates ordinary and dangling junctions (`_winapi.CreateJunction`) and a junction to `\??\<drive>:` with a hand-built mount-point reparse buffer (`device_junction`).
  - Symbolic links need Developer Mode or the privilege.
