# TODO

- [x] CHANGE: Generate a plan to replace legacy `tinycss 0.4` usage with `tinycss2`.
- [ ] CHANGE: Reevaluate RapidFuzz as a future replacement for the pure Python fuzzy matcher.
  The benchmark in `src/misc/benchmark_fuzzy_search.py` measured RapidFuzz
  `QRatio` at approximately 8.5 ms per query over 75,000 paths, compared with
  approximately 19-103 ms for the Python subsequence matcher. Avoid the slower
  `WRatio` scorer. Before switching, use the dependency-light PyPI wheel or find
  a conda-forge package that does not pull in NumPy and MKL, verify collection
  and execution in the PyInstaller build, rerun the benchmark, and add ranking
  regression tests for representative filename queries.
- [x] FEATURE: Add "Quick View" mode where there inactive pane is used for previewing the current file.
- [x] FEATURE: Integrate a Terminal into the file manager. Or at least open the current folder in Windows Terminal.
- [ ] FEATURE: Add option to replace a (sub) string in file names in the _Batch Rename Tool_. See [FManPowerRenamerAndReplacer](https://github.com/BenjaminKobjolke/FManPowerRenamerAndReplacer).
- [ ] FEATURE: Add "Synchronized Browsing" feature. See [SynchronizedBrowsing](https://github.com/mherrmann/SynchronizedBrowsing).
- [x] FEATURE: Add option to compare 2 files using external file comparison or integrate Meld view. See [SimpleCompare](https://github.com/rjwojcicki/SimpleCompare).
- [x] FEATURE: Show System Process in a Pane with the ability to kill a process. See [ProcessFS](https://github.com/mherrmann/ProcessFS).
- [x] BUG: On launch the status bar shows `v1.7.5`. It should show the version from `base.json`.
- [ ] CHANGE: Move to `PyQt6`.
- [x] FEATURE: Add support for `Notepad 4` as a text editor / viewer. Use the flags `-ro -ns` for view mode and `-ns` for edit mode.
- [x] CHANGE: Update `Notepad++` settings for viewer: `-multiInst -nosession -notabbar -ro` and for editor: `-multiInst -nosession -notabbar`.
- [x] CHANGE: Update `CudaText` settings for viewer: `-r -n -ns -nh` and for editor: `-n -ns -nh`.
- [x] FEATURE: Add support for `EmEditor` as a text editor / viewer. Use the flags `-nr -sp -r` for view mode and `-nr -sp` for edit mode.
- [x] CHANGE: Rename the file creation commands: "Edit new file" (`Shift+F4`) creates a file and opens it in the editor, "New file" (`Ctrl+N`) creates an empty file without opening the editor.
- [x] CHANGE: Evaluate using [`fd`](https://github.com/sharkdp/fd) to accelerate searching.
- [ ] CHANGE: Use ISO Style date (`YYYY-mm-dd`) and 24 Hours format for time. Should be a tiny run time improvement.
- [ ] FEATURE: Enable the file watching mechanism on Windows.
- [x] CHANGE: Implement [Commit `f3e48d2`](https://github.com/mherrmann/fman/commit/f3e48d23308689c4d3ffc90753a73bf6bb24a55b) from [`fman`](https://github.com/mherrmann/fman).
- [x] CHANGE: Update naming to match the logic: "Find files" -> Find files by their names or metadata, "Search files" -> Searches file by their content and metadata.
- [x] BUG: When closing a panel ("Search files" / "Find files with `fd`") with <kbd>Esc</kbd> the focus does not return to the last active pane.
- [x] BUG: <kbd>Ctrl</kbd>+<kbd>F</kbd> ("Find files in current folder") does not yield the UI from version `0.8.1` (Quick Search based).
- [x] FEATURE: Add a button "Copy Image" to copy the image to the clipboard in "QuickView" for images mode.
- [x] FEATURE: Add a plan to support for GIF, APNG and other animated images formats in "QuickView" for images mode.
- [x] CHANGE: Update the structure of the "About" box.
- [x] CHANGE: Use `app_version` and `APP_VERSION` instead of `fman_version` and `FMAN_VERSION`.
- [x] CHANGE: Rename the command "Show processes" to "Show OS' processes".
- [x] FEATURE: Add _synonyms_to commands in _Command Palette_ for better search. For example, searching "Bookmarks" should give the "Favorites" result.
- [ ] CHANGE: Update to Everything 1.5 when released. It supports tags on Windows files.
- [ ] CHANGE: Update to Everything 1.5 when released. It supports searching for duplicates.
- [ ] FEATURE: _Folder Diff_ based on names, dates and hash.
- [ ] FEATURE: Evaluate [Editpad](https://github.com/imluyg/editpad) for a text viewer / editor preset.
- [ ] FEATURE: Evaluate [Dan](https://github.com/dfallman/dan) for a text viewer / editor preset.
- [ ] FEATURE: Evaluate [FastPad](https://github.com/coccor/Fastpad) for a text viewer / editor preset.
- [ ] FEATURE: Evaluate [Lite Anvil](https://github.com/danpozmanter/lite-anvil) for a text viewer / editor preset.
- [ ] FEATURE: Evaluate [Noter](https://github.com/blisspixel/noter) for a text viewer / editor preset.
- [ ] FEATURE: Evaluate [Token](https://github.com/HelgeSverre/token) for a text viewer / editor preset.
- [ ] FEATURE: Evaluate [Fulgur](https://github.com/fulgur-app/Fulgur) for a text viewer / editor preset.
- [x] CHANGE: Remove the extended status bar for 2 panes. Leave only the option for a single pane (Active pane).
- [x] BUG: Resetting the geometry of the application does not make it move to the default position on next run.
- [x] CHANGE: Using _Fuzzy Find File_ should respect the active pane settings for hidden files.
- [x] CHANGE: The saved `json` files of the application and plug ins should be saved in a `pretty` mode.
- [ ] CHANGE: Use `fman.fs.rename_no_replace(source, destination)` in all rename use cases. Review its logic.
- [x] CHANGE: Minimize delay before copying a folder with many files.
- [x] FEATURE: Implement multithreaded high performance copy with option for verification like `FastCopy`.
- [x] BUG: Fix Move preparation failing when the destination folder does not exist.
- [x] FEATURE: Add a preset for [`ecode`](https://github.com/SpartanJ/ecode) editor. Use `--zen-mode` for edit and `--zen-mode --read-only` for view.
- [ ] FEATURE: Copy the status callback in `QuickBoard` to `QuickTable` and `QuickList`. Add modes like callouts (Error, Alert, Text).
- [x] FEATURE: Add `Copy file name` and `Copy file path` to file or dir right menu (_Context Menu_).
- [x] CHANGE: Bundle Batch File Renamer in the frozen application while keeping its public plug-in API implementation.
- [x] FEATURE: Add random letter (`{c}`) and digit (`{d}`) fields to the rename tool.
- [x] FEATURE: Add `Create a duplicate file` with alias `Copy file here`, using the existing Copy command with the active folder as its default destination.
- [x] FEATURE: Add `Pack here` to pack the selected files / highlighted item into an archive in the current folder by default.
- [x] CHANGE: Rename the right click menu item: `Copy file name` to `Copy name`.
- [x] CHANGE: Rename the right click menu item: `Copy file path` to `Copy path`.
- [x] BUG: Running the `fd` based search on `C:\` and all sub folders raised access issues and gabbled text.
- [x] FEATURE: Add support in QuickView for viewing `CSV` and `TSV` as tables with `RAW` as view potion for text.
- [x] FEATURE: Add support for `Royi Text Editor` as a text editor / viewer. Use the flag `--read-only` for view mode.
- [x] CHANGE: Rename the right click menu item: `Create a duplicate file...` to `Duplicate...`.
- [x] CHANGE: Rename the _Command Palette_ menu item: `Create a duplicate file` to `Duplicate item`.
- [x] CHANGE: Rename the _Command Palette_ menu item: `Copy file name` to `Copy item(s) name`.
- [x] CHANGE: Rename the _Command Palette_ menu item: `Copy file path` to `Copy item(s) path` and show its shortcut key.
- [x] BUG: The _Command Palette_ item `Copy paths to clipboard` is a duplicate.
- [x] BUG: Choosing `Properties` on the _Right Click Menu_ on a file / folder crash the application.
- [x] FEATURE: Add option in _Command Palette_ for "Edit settings" which opens the settings file in the text editor (If defined, else shows alert).
- [x] CHANGE: Application level settings file should be called `AppSettings.json`. It should be at the top level of `UserSettings`.
- [x] CHANGE: The general settings file should not have OS level variants.
- [x] CHANGE: Convert the settings file into YAML / TOML (Which is faster to parse). Add comments to hint the options and valid values.
- [x] CHANGE: Group the _Command Palette_ items into groups: "Application: About", "Application: Edit settings", "File System: Edit".
- [x] CHANGE: Merge the _Zen_ into the _About_ window.
- [x] FEATURE: Add a _Context Menu_ for a single file / folder to show which process / task blocks it.
- [x] FEATURE: Add "Update settings file template" to append missing application settings as commented defaults, preserving existing values and comments.
- [x] FEATURE: The context menu for empty space in a pane shows "New folder" and "New file".
- [x] FEATURE: The context menu for empty space in a pane shows "New folder" and "New file".
- [x] FEATURE: Add `{UUID}`, `{HASHID}` and `{SQIDS}` aliases to the Batch Rename Tool.
- [x] BUG: Hitting `Backspace` at the root of a drive yields [error](https://i.imgur.com/DI23zZb.png).
- [x] FEATURE: Add support to _copy and paste_ from archives into pane (Windows Explorer in a `zip` file to a pane).
- [x] FEATURE: Add support to _drag and drop_ from archives into pane (Windows Explorer in a `zip` file to a pane).

## Performance

List of small performance focused optimization.  
Each task should be pretty localized and low risk.

- [ ] CHANGE: When adopting Python 3.15, use `identities.take_bytes()` instead of
  `bytes(identities)` at the end of `scan` in the
  [Windows listing scanner](src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py).
  Taking the entire private bytearray transfers its contents to immutable bytes
  without copying in CPython and empties the builder. Avoids a 3.2 MB payload
  copy for 200,000 16-byte file IDs; runtime benefit is not yet measured.
  Preserve a fallback if older Python versions remain supported; verify
  snapshot parity and benchmark on the intended Python 3.15 build.
  See [bytearray.take_bytes](https://docs.python.org/3.15/builtins/stdtypes.html#bytearray.take_bytes).
- [x] CHANGE: `reconcile` ([listing.py](src/main/python/fman/listing.py)): in the changed-listing
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