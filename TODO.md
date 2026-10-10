# TODO

- [ ] Add a constrained abstraction layer for `fman.ui`: keep Qt widgets,
  models and signals private, and expose only explicitly supported operations
  and plain-data callbacks through small wrappers, without unrestricted Qt
  method forwarding. Keep layout, focus, threading and lifecycle host-owned;
  migrate Favorites as the reference consumer, document API migration, and add
  focused tests for the boundary and preserved behavior. Preserve the upstream
  fman 1.7.5 plug-in API.
- [x] Generate a plan to replace legacy `tinycss 0.4` usage with `tinycss2`.
- [ ] Reevaluate RapidFuzz as a future replacement for the pure Python fuzzy matcher.
  The benchmark in `src/misc/benchmark_fuzzy_search.py` measured RapidFuzz
  `QRatio` at approximately 8.5 ms per query over 75,000 paths, compared with
  approximately 19-103 ms for the Python subsequence matcher. Avoid the slower
  `WRatio` scorer. Before switching, use the dependency-light PyPI wheel or find
  a conda-forge package that does not pull in NumPy and MKL, verify collection
  and execution in the PyInstaller build, rerun the benchmark, and add ranking
  regression tests for representative filename queries.
- [x] Add "Quick View" mode where there inactive pane is used for previewing the current file.
- [ ] Integrate "Quick Look Win". See [QuickLook-Win](https://github.com/BenjaminKobjolke/QuickLook-Win).
- [x] Integrate a Terminal into the file manager. Or at least open the current folder in Windows Terminal.
- [ ] Add a "Rename Tool" as a Plug In. See [FManPowerRenamerAndReplacer](https://github.com/BenjaminKobjolke/FManPowerRenamerAndReplacer).
- [ ] Add "Synchronized Browsing" feature. See [SynchronizedBrowsing](https://github.com/mherrmann/SynchronizedBrowsing).
- [x] Add option to compare 2 files using external file comparison or integrate Meld view. See [SimpleCompare](https://github.com/rjwojcicki/SimpleCompare).
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
- [x] BUG: When closing a panel ("Search files" / "Find files with `fd`") with <kbd>Esc</kbd> the focus does not return to the last active pane.
- [x] BUG: <kbd>Ctrl</kbd>+<kbd>F</kbd> ("Find files in current folder") does not yield the UI from version `0.8.1` (Quick Search based).
- [x] FEATURE: Add a button "Copy Image" to copy the image to the clipboard in "QuickView" for images mode.
- [x] FEATURE: Add a plan to support for GIF, APNG and other animated images formats in "QuickView" for images mode.
- [x] CHANGE: Update the structure of the "About" box.
- [x] CHANGE: Use `app_version` and `APP_VERSION` instead of `fman_version` and `FMAN_VERSION`.
- [x] CHANGE: Rename the command "Show processes" to "Show OS' processes".
- [ ] FEATURE: Add _synonyms_to commands in _Command Palette_ for better search. For example, searching "Bookmarks" should give the "Favorites" result.
- [ ] CHANGE: Update to Everything 1.5 when released. It supports tags on Windows files.
- [ ] FEATURE: _Folder Diff_ based on names, dates and hash.
- [ ] FEATURE: Candidates for presets as text viewer / editor: [Editpad](https://github.com/imluyg/editpad), [Dan](https://github.com/dfallman/dan), [FastPad](https://github.com/coccor/Fastpad), [Lite Anvil](https://github.com/danpozmanter/lite-anvil), [Noter](https://github.com/blisspixel/noter), [Token](https://github.com/HelgeSverre/token), [Fulgur](https://github.com/fulgur-app/Fulgur).
- [x] CHANGE: Remove the extended status bar for 2 panes. Leave only the option for a single pane (Active pane).
- [x] BUG: Resetting the geometry of the application does not make it move to the default position on next run.
- [x] CHANGE: Using _Fuzzy Find File_ should respect the active pane settings for hidden files.
- [x] CHANGE: The saved `json` files of the application and plug ins should be saved in a `pretty` mode.
- [ ] CHANGE: Use `fman.fs.rename_no_replace(source, destination)` in all rename use cases. Review its logic.
- [x] CHANGE: Minimize delay before copying a folder with many files.
- [x] FEATURE: Implement multithreaded high performance copy with option for verification like `FastCopy`.
- [x] BUG: Fix Move preparation failing when the destination folder does not exist.
- [x] FEATURE: Add a preset for [`ecode`](https://github.com/SpartanJ/ecode) editor. Use `--zen-mode` for edit and `--zen-mode --read-only` for view.
- [ ] FEATURE: Copy the status callback in `QuickBoard` to `QuickTable` and `QickList`. Add modes like callouts (Error, Alert, Text).

## Performance

List of small performance focused optimization.  
Each task should be pretty localized and low risk.

- [ ] When adopting Python 3.15, use `identities.take_bytes()` instead of
  `bytes(identities)` at the end of `scan` in the
  [Windows listing scanner](src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py).
  Taking the entire private bytearray transfers its contents to immutable bytes
  without copying in CPython and empties the builder. Avoids a 3.2 MB payload
  copy for 200,000 16-byte file IDs; runtime benefit is not yet measured.
  Preserve a fallback if older Python versions remain supported; verify
  snapshot parity and benchmark on the intended Python 3.15 build.
  See [bytearray.take_bytes](https://docs.python.org/3.15/builtins/stdtypes.html#bytearray.take_bytes).
- [x] `reconcile` ([listing.py](src/main/python/fman/listing.py)): in the changed-listing
  loop, replace `if not any(identity):` with `if identity == unknown:`, defining
  `unknown = bytes(16)` once before the loop. Measured about 2.7 ms per 200,000
  entries. Couples the check to 16-byte identities; update it if that size changes.


## Competition
 
- [RAT Commander](https://github.com/dividebysandwich/rat-commander) - Great viewing options.
- [GPUI FileManager](https://github.com/XPOL555/GPUIFileManager) -  Based on GPUI (Like Zed) inspired by FilePilot with emphasize on memory.
- [The File Ninja](https://thefile.ninja) - They seems to implement my idea about structured answer for natural language to search.
- [Strata](https://github.com/lgse/strata) - Linux only. 
- [Xverb](https://github.com/xsm909/xverb) - Plug In based, [App page](https://xverb.pages.dev).
- [Elio](https://github.com/elio-fm/elio).
- [Tauri Explorer](https://github.com/xnmp/tauri-explorer).
- [NCrs](https://github.com/CosmicDriftGameStudio/ncrs).
- [Furman](https://github.com/fenio/furman).
- [lvdExplorer](https://github.com/lvdsystems/lvdExplorer).