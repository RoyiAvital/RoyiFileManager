# TODO

- [ ] Add a constrained abstraction layer for `fman.ui`: keep Qt widgets,
  models and signals private, and expose only explicitly supported operations
  and plain-data callbacks through small wrappers, without unrestricted Qt
  method forwarding. Keep layout, focus, threading and lifecycle host-owned;
  migrate Favorites as the reference consumer, document API migration, and add
  focused tests for the boundary and preserved behavior. Preserve the upstream
  fman 1.7.5 plug-in API.
- [x] Generate a plan to replace legacy `tinycss 0.4` usage with `tinycss2`.
- [ ] Reevaluate RapidFuzz as a future replacement for the pure-Python fuzzy matcher.
  The benchmark in `src/misc/benchmark_fuzzy_search.py` measured RapidFuzz
  `QRatio` at approximately 8.5 ms per query over 75,000 paths, compared with
  approximately 19-103 ms for the Python subsequence matcher. Avoid the slower
  `WRatio` scorer. Before switching, use the dependency-light PyPI wheel or find
  a conda-forge package that does not pull in NumPy and MKL, verify collection
  and execution in the PyInstaller build, rerun the benchmark, and add ranking
  regression tests for representative filename queries.
- [x] Add "Quick View" mode where there inactive pane is used for previewing the current file.
- [ ] Integrate "Quick Look Win". See [QuickLook-Win](https://github.com/BenjaminKobjolke/QuickLook-Win).
- [ ] Integrate a Terminal into the file manager. Or at least open the current folder in Windows Terminal.
- [ ] Add a "Rename Tool" as a Plug In. See [FManPowerRenamerAndReplacer](https://github.com/BenjaminKobjolke/FManPowerRenamerAndReplacer).
- [ ] Add "Synchronized Browsing" feature. See [SynchronizedBrowsing](https://github.com/mherrmann/SynchronizedBrowsing).
- [x] Add option to compare 2 files using external file comparison or integrate Meld view. See [SimpleCompare
](https://github.com/rjwojcicki/SimpleCompare).
- [x] Show System Process in a Pane with the ability to kill a process. See [ProcessFS](https://github.com/mherrmann/ProcessFS).
- [x] BUG: On launch the status bar shows `v1.7.5`. It should show the version from `base.json`.
- [ ] Move to `PyQt6`.
- [x] Add support for `Notepad 4` as a text editor / viewer. Use the flags `-ro -ns` for view mode and `-ns` for edit mode.
- [x] Update `Notepad++` settings for viewer: `-multiInst -nosession -notabbar -ro` and for editor: `-multiInst -nosession -notabbar`.
- [x] Update `CudaText` settings for viewer: `-r -n -ns -nh` and for editor: `-n -ns -nh`.
- [x] Add support for `EmEditor` as a text editor / viewer. Use the flags `-nr -sp -r` for view mode and `-nr -sp` for edit mode.
- [x] Rename the file creation commands: "Edit new file" (`Shift+F4`) creates a file and opens it in the editor, "New file" (`Ctrl+N`) creates an empty file without opening the editor.
- [x] Evaluate using [`fd`](https://github.com/sharkdp/fd) to accelerate searching.
- [ ] Use ISO Style date (`YYYY-mm-dd`) and 24 Hours format for time. Should be a tiny run time improvement.
- [ ] Enable the file watching mechanism on Windows.
- [x] Implement [Commit `f3e48d2`](https://github.com/mherrmann/fman/commit/f3e48d23308689c4d3ffc90753a73bf6bb24a55b) from [`fman`](https://github.com/mherrmann/fman).
- [x] Update naming to match the logic: "Find files" -> Find files by their names or metadata, "Search files" -> Searches file by their content and metadata.

## Performance

List of small performance focused optimization.  
Each task should be pretty localized and low risk.
