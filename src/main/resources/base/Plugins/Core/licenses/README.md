# Core Notices

`core/fs/local/windows/_fsenum.pyd`, the native directory enumerator built from
[src/main/rust/fsenum](../../../../../rust/fsenum/README.md), statically links:

| Component | License | Notice |
| --- | --- | --- |
| Rust standard library, Rust 1.99.1 (`58cf8f9c3`) | MIT OR Apache-2.0, with the third-party parts it lists | `Rust-COPYRIGHT-library.html` |
| MinGW-w64 runtime startup code (`x86_64-pc-windows-gnu`, self-contained) | MinGW-w64 runtime licensing | `COPYING.MinGW-w64-runtime.txt` |
| libgcc unwinder (`x86_64-pc-windows-gnu`, self-contained) | GPL-3.0 with the GCC Runtime Library Exception 3.1 | `GCC-COPYING.RUNTIME`, `GCC-COPYING3` |

`Rust-COPYRIGHT-library.html`, `GCC-COPYING.RUNTIME` and `GCC-COPYING3` are
copied unchanged from that Rust distribution (`share/doc/rust/COPYRIGHT-library.html`,
`share/doc/COPYING.RUNTIME`, `share/doc/COPYING3`).
`COPYING.MinGW-w64-runtime.txt` is copied unchanged from the MinGW-w64 project:
https://github.com/mirror/mingw-w64/blob/master/COPYING.MinGW-w64-runtime/COPYING.MinGW-w64-runtime.txt

The module has no crate dependencies. Refresh these files when the pinned Rust
release changes.
