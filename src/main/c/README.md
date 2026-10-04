# Building `_fsparser.pyd`

`fsparser.c` is a CPython extension using the limited API (`abi3`, Python 3.12+).
It is compiled with the llvm-mingw toolchain so the resulting `.pyd` depends only
on `python3.dll`, `KERNEL32.dll` and the Windows UCRT.

## Toolchain

- llvm-mingw `20260922` (LLVM 23.1.2, UCRT, x86_64):
  <https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/llvm-mingw-20260922-ucrt-x86_64.zip>
- SHA-256: `e3ad77d117a4bea19a7a3b333341824d79a5a371004a10e25b8504e7b3047666`
- Extract anywhere; no installation. `clang.exe` is in `bin\`.

The Python headers and `python3.lib` come from the active conda environment
(`RoyiFileManager`, Python 3.14). Nothing else is required.

## Build

From the repository root, in the activated conda environment:

```powershell
$llvm = 'D:\Path\To\llvm-mingw-20260922-ucrt-x86_64'
$prefix = (python -c "import sys; print(sys.base_prefix)")
New-Item -ItemType Directory -Force target\native | Out-Null

& "$llvm\bin\clang.exe" --target=x86_64-w64-mingw32 -O2 -Wall -Wextra -shared -static `
    -DPy_LIMITED_API=0x030C0000 `
    "-I$prefix\include" `
    src\main\c\fsparser.c `
    "$prefix\libs\python3.lib" `
    -o target\native\_fsparser.pyd
```

Flags:

- `-DPy_LIMITED_API=0x030C0000`: limited API for 3.12+, so one `.pyd` works
  across Python minor versions.
- `-static`: no dependency on `libwinpthread` or other MinGW runtime DLLs.
- `python3.lib`: the stable-ABI import library, not `python314.lib`.

The module exposes three shapes over one record decoder: `Columns(link_tags)`
(`add`/`entry`/`patch`/`finish(frozen=)`, the shape the scanner integrates),
`parse_records` (whole directory) and `parse_batch` (append per batch), the
latter two kept as reference shapes for the gauge. `natural_keys(names,
is_dir, ascending)` builds the Name-column sort keys (`core.Name.keys`); it
must equal the Python `natural_key` reference for every code point, and
`UNICODE_VERSION` must equal `unicodedata.unidata_version` of the Python the
binary ships with (regenerate `DECIMAL_RUN_STARTS` when Python's Unicode
database changes). There is no version constant: the committed binary is
paired with this source by SHA-256. Tests: `core.tests.fs.test_fsparser`;
gauge: `src/misc/benchmark_fsparser.py`.

## Verify

```powershell
python -c "import sys; sys.path.insert(0, 'target/native'); import _fsparser; print(_fsparser.HEADER_SIZE, sorted(n for n in dir(_fsparser) if not n.startswith('_')))"
```

Expected output: `88 ['Columns', 'HEADER_SIZE', 'UNICODE_VERSION', 'natural_keys', 'parse_batch', 'parse_records']`.

Dependency check (should list only `python3.dll`, `KERNEL32.dll` and
`api-ms-win-crt-*.dll`):

```powershell
& "$llvm\bin\llvm-objdump.exe" -p target\native\_fsparser.pyd | Select-String 'DLL Name'
```

Parity and timing against the Python parser, then the edge-case validation.
**Both are mandatory after any change to `fsparser.c`**, before the binary is
recorded: the scanner trusts this module's output without re-validation.

```powershell
python src\misc\benchmark_fsparser.py "<large folder>" --native target\native\_fsparser.pyd
python src\misc\validate_fsparser.py --native target\native\_fsparser.pyd
python -X dev -m unittest core.tests.fs.test_fsparser fman_unittest.test_listing
```

## Record the hashes

```powershell
python src\main\c\write_hashes.py --from target\native\_fsparser.pyd
python src\main\c\check_hashes.py
```

`write_hashes.py` copies the built module to `src\main\c\_fsparser.pyd` and
writes `fsparser.sha256` with the digest of `fsparser.c` (CRLF normalised to
LF, so Git line-ending conversion does not matter) and of the binary.
`check_hashes.py` verifies both and reports a Git LFS pointer file as such.
