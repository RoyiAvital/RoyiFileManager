# TODO

- [ ] Add a constrained abstraction layer for `fman.ui`: keep Qt widgets,
  models and signals private, and expose only explicitly supported operations
  and plain-data callbacks through small wrappers, without unrestricted Qt
  method forwarding. Keep layout, focus, threading and lifecycle host-owned;
  migrate Favorites as the reference consumer, document API migration, and add
  focused tests for the boundary and preserved behavior. Preserve the upstream
  fman 1.7.5 plug-in API.
- [ ] Replace legacy `tinycss 0.4` usage with `tinycss2` to remove Python 3.14
  invalid-escape warnings. Preserve existing CSS selector, declaration, value,
  Unicode, and parse-error behavior; add focused parser and theme regression
  tests; regenerate `conda-lock.yml`; and verify the PyInstaller build.
- [ ] Reevaluate RapidFuzz as a future replacement for the pure-Python fuzzy matcher.
  The benchmark in `src/misc/benchmark_fuzzy_search.py` measured RapidFuzz
  `QRatio` at approximately 8.5 ms per query over 75,000 paths, compared with
  approximately 19-103 ms for the Python subsequence matcher. Avoid the slower
  `WRatio` scorer. Before switching, use the dependency-light PyPI wheel or find
  a conda-forge package that does not pull in NumPy and MKL, verify collection
  and execution in the PyInstaller build, rerun the benchmark, and add ranking
  regression tests for representative filename queries.
 - [ ] Add "Quick View" mode where there inactive pane is used for previewing the current file.
 - [ ] Integrate "Quick Look Win". See [QuickLook-Win](https://github.com/BenjaminKobjolke/QuickLook-Win).
 - [ ] Integrate a Terminal into the file manager. Or at least open the current folder in Windows Terminal.
 - [ ] Add a "Rename Tool" as a Plug In. See [FManPowerRenamerAndReplacer
](https://github.com/BenjaminKobjolke/FManPowerRenamerAndReplacer).
 - [ ] Add "Synchronized Browsing" feature. See [SynchronizedBrowsing](https://github.com/mherrmann/SynchronizedBrowsing).
 - [ ] Add option to compare 2 files using external file comparison or integrate Meld view. See [SimpleCompare
](https://github.com/rjwojcicki/SimpleCompare).
 - [ ] Show System Process in a Pane with teh ability to kill a process. See [ProcessFS](https://github.com/mherrmann/ProcessFS).
 - [x] Bug: On launch the status bar shows `v1.7.5`. It should show the version from `base.json`.
 - [ ] Move to `PyQt6`.
