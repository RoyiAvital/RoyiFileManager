# `_fsenum`: Native Folder Tables

`_fsenum.pyd` scans an NTFS or ReFS folder for Core's local file system
([Done/DirectoryEnumerator001.md](../../../../Done/DirectoryEnumerator001.md)).
One call returns the `Listing` columns, the folder's scope and its Name order;
`core/fs/local/windows/listing.py` is the only caller.

- Rust, no crate dependencies. The CPython limited API (abi3, Python 3.12+)
  and kernel32 are declared by hand and imported with `raw-dylib`.
- The module imports only `python3.dll`, `kernel32.dll`, `ntdll.dll`,
  `msvcrt.dll` and `api-ms-win-core-synch-l1-2-0.dll`. The Rust standard
  library and the MinGW-w64 runtime are linked statically; their notices are in
  [Core/licenses](../../resources/base/Plugins/Core/licenses/README.md).
- The committed binary is paired with its sources by SHA-256 in
  `fsenum.sha256` and stored with Git LFS.

## Layout

| File | Role |
| --- | --- |
| `src/pipeline.rs` | Opening, scope, the reader and decoder threads (E), the key builders and sort (K) |
| `src/python.rs` | The module: the calling thread creates the column objects (P) and owns the GIL hand-over |
| `src/record.rs` | Record validation, as `records()` in `listing.py` |
| `src/keys.rs`, `src/unicode.rs` | Natural keys, as `fman.impl.util.natural.natural_key` |
| `src/sort.rs` | The Name order: directories first, keys, then enumeration order |
| `src/segment.rs` | The folder table: 4096-entry column segments |
| `generate_unicode.py` | Writes `src/unicode.rs` from the running Python's Unicode database |

A folder of up to four kernel batches (60 KiB each) is read, keyed and sorted
on the calling thread. Larger folders use a reader thread, a decoder thread,
two key builders and, for the final sort, up to eight threads; all are joined
before `scan` returns. The sort splits a bucket of keys that holds more than one
thread's share again, after the bytes its keys share, so a folder of one stem
(`IMG_2024...`) still sorts on every thread. The column tuples hold only `str`,
`int` and `bool`, so they are not tracked by Python's garbage collector, which
would otherwise visit every item once after a load.

Kernel calls use a buffer below 64 KiB on purpose. While a folder's files have
recently been created, read or opened, a call with 64 KiB or more on NTFS is
1.4 to 2.4 times slower per record and a smaller call is not; ReFS has no such
step. `BUFFER_BYTES` in `pipeline.rs` has the measurements. Compare builds on
the same folder in the same state, alternating.

## Toolchain

- Rust `1.99.1` (`stable-x86_64-pc-windows-gnu`, host and target
  `x86_64-pc-windows-gnu`), with its `rust-mingw` component. Nothing else.
- `build_fsenum.py` refuses another `rustc` release. It links with the
  toolchain's own self-contained MinGW-w64 (`-C link-self-contained=yes`), so
  a MinGW, LLVM or Visual Studio installation on `PATH` is never used.
- Build output goes to `target/fsenum`.

## Build, Test and Record

From the repository root, in the `RoyiFileManager` environment:

```powershell
python src\main\rust\fsenum\build_fsenum.py --test
python src\main\rust\fsenum\check_hashes.py
```

`--test` runs `cargo test` first. The build checks the module's DLL imports,
copies it to `_fsenum.pyd` and writes `fsenum.sha256`. `--no-record` builds
without touching either. The linker writes no build time
(`--no-insert-timestamp`), and the standard library's source paths are named
`/rustc/<commit>` whether or not the `rust-src` component is installed. So
rebuilding unchanged sources gives the recorded binary byte for byte, on any
machine, from any folder, with CRLF or LF line endings. The source digest covers
`Cargo.toml`, `Cargo.lock`, `build_fsenum.py`, `generate_unicode.py` and
`src/*.rs`, with CRLF normalized to LF. `check_hashes.py` reports a Git LFS
pointer as such. `build.py` checks the pairing in `test`, `freeze` and
`package`, and that the frozen copy is identical.

## Change Rule

`listing.py` trusts the module's output without re-validation, so every
change to the sources needs, before the binary is recorded:

```powershell
python -c "import build, os, subprocess, sys; env = build._environment(); env['QT_QPA_PLATFORM'] = 'offscreen'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_fsenum', 'fman_unittest.test_listing'], env=env).returncode)"
python src\misc\benchmark_fsenum.py "<large folder>" C:\Windows\System32 C:\Users
```

The gauge compares the scan with a pure-Python reference (kernel batches,
`records()`, `os.stat` for links, `sorted()` over `natural_key`) and prints the
timings. Benchmarks in `cargo test` are ignored by default:

```powershell
$env:FSENUM_BENCH = '<large folder>'
cargo test --release --manifest-path src\main\rust\fsenum\Cargo.toml bench -- --ignored --nocapture --test-threads=1
```

Run `cargo` directly with the environment `build_fsenum.py` sets
(`CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER`, `RUSTFLAGS`, `CARGO_TARGET_DIR`).

When the shipped Python's Unicode database changes, run
`python src\main\rust\fsenum\generate_unicode.py` (`--check` reports whether
`src/unicode.rs` is current); `core.tests.fs.test_fsenum` compares
`UNICODE_VERSION` with `unicodedata.unidata_version`.

## Module

| Function | Use |
| --- | --- |
| `scan(path, join_prefix, link_tags, check_canceled, previous)` | The folder's columns and table; `None` outside the native scope; `previous` itself when unchanged |
| `order(table, ascending)` | Name order, `bytes` of `uint32` entry indices |
| `without_attributes(table, order, mask)` | The entries of `order` without any `mask` attribute bit |
| `natural_keys(names, is_dir, ascending)` | Name sort keys for listings without a table |
| `name_order(names, is_dir, ascending)` | The sort on given names (tests) |
| `parse_batches(batches, link_tags)` | Decoding and object creation on given buffers (tests) |
