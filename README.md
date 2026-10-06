[![Visitors](https://api.visitorbadge.io/api/combined?path=https%3A%2F%2Fgithub.com%2FRoyiAvital%2FStackExchangeCodes&labelColor=%23f47373&countColor=%23555555&style=plastic)](https://github.com/RoyiAvital/RoyiFileManager) <!-- https://www.visitorbadge.io -->
[![Documentation](https://img.shields.io/badge/documentation-online-brightgreen?style=plastic)](https://royiavital.github.io/RoyiFileManager)

# RoyiFileManager

`RoyiFileManager` is a portable, keyboard workflow focused, dual pane _file manager_ inspired by [SublimeText](https://en.wikipedia.org/wiki/Sublime_Text).  
It began as a fork of [`fman`](https://github.com/mherrmann/fman) by [Michael Herrmann](https://github.com/mherrmann). 

The _File Manager_ focuses on:
 - **Minimalistic** and focused UI.
 - High performance to generate **reactive** experience.
 - **Commands** through _Command Center_.
 - **Keyboard** oriented workflow.
 - Advanced search tools with **known syntax** (`fzf` / `fd` / `ripgrep` / `Everything`).
 - Easy **integration** of 3rd party tools (Text Editor, File Comparison, Grep Tool, File Find Tool, etc...).
 - Developed and verified on **Windows OS**.

Development prioritizes _correctness_ and _performance_.  
Each release is validated by hundreds of correctness tests and accompanied by a detailed performance report.

![](https://i.imgur.com/2t8CmJF.png)

## Installation

1. Open the [latest release](https://github.com/RoyiAvital/RoyiFileManager/releases/latest).
2. Download `RoyiFileManager-<version>-windows-x86_64.zip`.
3. Extract the ZIP file to a folder of your choice.
4. Run `RoyiFileManager.exe` from the extracted folder.

> [!TIP]
> _RoyiFileManager_ is portable. Keep the extracted files together and move the folder whenever needed.

## Features

Significant additions compared with `fman`:

- **Data Safety**: Safeguards protect data integrity during file copies and moves, archive operations and work with file system links.
- **Performance**: A file system abstraction with an order of magnitude faster performance to deliver **reactive experience**. The system utilizes bulk `NTFS`/`ReFS` listing for a snapshot model, virtual rows and background filter/find projections. See [measured gains and remaining limits](CHANGELOG.md#performance-compared-with-081).
- **Fuzzy Find Files**: Open the _Quicksearch_ dialog with <kbd>Ctrl</kbd>+<kbd>F</kbd> or search recursively with <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd>. Supports [`fzf`](https://github.com/junegunn/fzf) style exact terms, anchors, negation, `AND` / `OR` and match highlights, separately from the substring/glob Filter Bar. Using **Toggle find result metadata** adds metadata to results. See [Usage, Syntax and Performance](src/main/resources/base/Plugins/SearchFileFuzzy/README.md).
- **Search Files**: Press <kbd>Alt</kbd>+<kbd>F7</kbd> for [`ripgrep`](https://github.com/burntsushi/ripgrep) based filename and content search in _Glob_, _Literal_ or _RegEx_ mode. **Extended** mode adds _Size_ and _Date Modified_ columns with header filters. See [Search Files Usage](src/main/resources/base/Plugins/SearchFiles/README.md).
- **Find Files with `fd`**: Press <kbd>Shift</kbd>+<kbd>F7</kbd> for [`fd`](https://github.com/sharkdp/fd) based filename search with date, size, type and traversal filters. See [Find Files Usage](src/main/resources/base/Plugins/FindFiles/README.md).
- **Search Files with Everything**: Built in [_Everything_](https://www.voidtools.com) search engine for an instant file and content search based on pre built database. Add indexed folders with **Add folder to Everything database**, then press <kbd>Ctrl</kbd>+<kbd>E</kbd> to search them with [Everything syntax](https://www.voidtools.com/support/everything/search_syntax), highlights and metadata. Use **Manage Everything database folders** for a fully featured bookmarks manager. See [Everything Usage](src/main/resources/base/Plugins/Everything/README.md).
- **Pane Filter / Files Filter**: Type to filter file names with globs, anchors and negation with [`fzf`](https://github.com/junegunn/fzf) inspired syntax. See [Pane Filter Usage](src/main/resources/base/Plugins/Core/README.md#pane-filter).
- **Hidden Files**: Windows panes reuse entry attributes to reduce repeated visibility checks. Press <kbd>Ctrl</kbd>+<kbd>R</kbd> after external hidden-attribute changes. See [Hidden Files](src/main/resources/base/Plugins/Core/README.md#hidden-files).
- **QuickView Layer**: Press <kbd>Ctrl</kbd>+<kbd>Q</kbd> to preview the cursor file over the other pane: images, PDFs, plain text, MarkDown and highlighted source code. See [QuickView Usage](src/main/resources/base/Plugins/Core/README.md#quickview).
- **UI Components**: New building blocks that expand what plug-ins can do. [Plug-in UI guide](PlugIn.md#ui-extension).
- **Docked Panel**: Controlling states and operations. Exposed to be used by Plug-In's.
- **Favorites**: Press <kbd>Ctrl</kbd>+<kbd>B</kbd> for a fully featured Favorites Manager, built entirely with the plug-in APIs.
- **Recent Commands**: <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> pins the last three commands run from the palette.
- **Process Pane**: Run **Show the OS' processes** for a flat Name/PID list of the system running processes. Press <kbd>F8</kbd> to force terminate it. See [Process Pane Usage](src/main/resources/base/Plugins/ProcessPane/README.md).
- **Extended Status Bar**: Press <kbd>Ctrl</kbd>+<kbd>S</kbd> to toggle file statistics of the active pane in the status bar.
- **Sync Panes**: Select **Sync pane location** in Command Center to sync the inactive pane to the active pane's path.
- **Checksum Files**: Generate checksum files for selected files or folders, including subfolders and verify file integrity against existing checksum files. Compatible with [Total Commander](https://www.ghisler.com) and [Double Commander](https://github.com/doublecmd/doublecmd). See [algorithms and TC/DC compatibility status](src/main/resources/base/Plugins/ChecksumFiles/README.md).
- **File Hash**: Press <kbd>Ctrl</kbd>+<kbd>H</kbd> for centered checksum output; use Calculate File Hash By to pick an algorithm in QuickSearch, then view the result. See [File Hash Calculation Usage](src/main/resources/base/Plugins/CalculateFileHash/README.md).
- **Directory Size**: Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>D</kbd> to toggle progressive directory size calculation in both panes, or <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Enter</kbd> for a one time total of selected directories. See [Directory Size Usage](src/main/resources/base/Plugins/Core/README.md#directory-sizes).
- **New File**: Press <kbd>Ctrl</kbd>+<kbd>N</kbd> to create an empty file without opening an editor.
- **Text Editor / Viewer**: Set external programs on <kbd>F4</kbd> / <kbd>F3</kbd>, configured through **Set text editor** / **Set text viewer** in the Command Center. Presets include [CudaText](https://github.com/Alexey-T/CudaText), [EmEditor](https://www.emeditor.com), [Notepad++](https://github.com/notepad-plus-plus/notepad-plus-plus) and [Notepad 4](https://github.com/zufuliu/notepad4). See [Text Editor and Viewer Usage](src/main/resources/base/Plugins/Core/README.md#text-editor-and-viewer).
- **File / Folder Comparators**: Configure independent external tools with **Set file comparator** / **Set folder comparator**, then run **Compare files** / **Compare folders**. Presets include [Meld](https://meldmerge.org), [Beyond Compare](https://www.scootersoftware.com), [WinMerge](https://github.com/winmerge/winmerge), [SmartSynchronize](https://www.syntevo.com/smartsynchronize). See [Comparator Usage](src/main/resources/base/Plugins/Core/README.md#file-and-folder-comparators).
- **Archive Transfers**: Extraction progress and cancellation, with verified output before source deletion when moving out of an archive or between archives of the same format. See [Archive Transfers Usage](src/main/resources/base/Plugins/Core/README.md#archive-transfers).
- **Unpack Archive**: Works like `Extract Here` in `7-Zip` / `WinRar`. See [Unpack Archive Usage](src/main/resources/base/Plugins/Core/README.md#unpack-archive).

> [!TIP]
> Open an issue for new feature requests.  
> Feedback is highly appreciated.

## Performance

> [!IMPORTANT]
> We take performance seriously.
> We aim to minimize _Time to render a pane_ (TTRP), _Time to apply a filter_ (TTAF) and _Time to apply a fuzzy find_ (TTAFF).
    
Results of the performance test suite per version. Run time in [ms], lower is better.

| Test                            |   0.9.0 |   0.9.3 | 0.10.3 | 0.13.0 | 0.13.1 |
|---------------------------------|--------:|--------:|-------:|-------:|-------:|
| Pane Load - Small Folder        |   42.23 |   35.20 |  33.93 |  37.52 |  37.02 |
| Pane Load - Large Folder        | 1001.54 |  964.31 | 958.23 | 758.64 | 266.27 |
| Filter Bar - Small Folder       |    8.96 |    8.69 |   8.79 |  10.88 |   9.77 |
| Filter Bar - Large Folder       |  332.17 |  331.28 | 338.27 | 364.34 | 289.53 |
| Fuzzy Find - Small Folder       |    4.57 |    4.55 |   7.17 |   5.28 |   4.86 |
| Fuzzy Find - Large Folder       |  408.47 |  407.95 | 441.02 | 357.29 | 354.73 |
| Fuzzy Find (Recursive)          |   91.68 |   91.05 |  91.91 |  92.54 |  91.28 |
| QuickView Images - Small Folder |  122.09 |  122.61 | 122.04 | 121.09 | 116.37 |
| QuickView Images - Large Folder |  123.29 |  121.14 | 135.86 | 119.46 | 120.62 |
| QuickView Text - Small Folder   |       - |       - | 133.03 | 129.55 | 132.58 |
| QuickView Text - Large Folder   |       - |       - | 129.47 | 132.35 | 131.50 |
| Selections - Small Folder       |   15.67 |   15.24 |  15.35 |  16.18 |  15.79 |
| Selections - Large Folder       |   88.18 |   87.85 |  88.36 |  89.65 |  87.64 |
| Selections Readback             | 1994.44 | 1974.51 |  73.78 |  69.86 |  65.65 |
| Navigation                      |    7.17 |    7.36 |   7.17 |   7.05 |   6.97 |
| Refresh / Selection             |  581.97 |  592.84 | 585.17 | 355.99 |  67.59 |

Comparisons with previous versions:

[CelebA](https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html) folder with about 200,000 entries. Lower is better.

| Measurement                | Ver. 0.8.0  | Ver. 0.8.1  | Ver. 0.9.0  | Ver. 0.9.2  | Ver. 0.13.0 | Ver. 0.13.1 |
|----------------------------|-------------|-------------|-------------|-------------|-------------|-------------|
| First Populated Pane Paint | 8.949 [s]   | 5.663 [s]   | 0.583 [s]   | 0.506 [s]   | 0.257 [s]   | 0.112 [s]   |
| Metadata Loading Complete  | 17.786 [s]  | 11.498 [s]  | 0.571 [s]   | 0.494 [s]   | 0.244 [s]   | 0.100 [s]   |
| Post Paint Qt Commit Work  | 2.765 [s]   | 1.282 [s]   | 0 [s]       | 0 [s]       | 0 [s]       | 0 [s]       |
| Settled Working Memory     | 771.1 [MiB] | 771.3 [MiB] | 165.6 [MiB] | 167.4 [MiB] | 160.3 [MiB] | 145.5 [MiB] |

> [!NOTE]
> * Version `0.13.x` added a native `C` directory parser, enumeration and a fast path for `NTFS`/`ReFS` folders.
> * Versions `0.10.x` optimized the existing code and remove the slower legacy paths.
> * Version `0.9.x` is the 1st version with the new architecture (_Snapshot Architecture_) which is an order of magnitude faster than `0.8.1`.
> * Version `0.8.1` had an improved version of the `fman` architecture (About 30% faster than `0.8.0`).
> * Version `0.8.0` and earlier versions use the `fman` architecture and performance.

## Development

> [!TIP]
> Development uses [`micromamba`](https://github.com/mamba-org/mamba).
> Micromamba is largely compatible with `conda`. See the [Mamba documentation](https://mamba.readthedocs.io).
> The examples below use `conda` and `micromamba` interchangeably.

### Environment

The development workflow is based on architecture design by the developer and implementation by an AI Agent.  
Each feature is first defined by its tests and success criteria.  
The design is reviewed by at least 2 different agents.  
Implementation is verified by tests and 2 agent reviewers.

Install a conda compatible package manager then create the environment:

```powershell
conda create -f environment.yml
conda activate RoyiFileManager
python build.py run
```

After updating an existing checkout, refresh its runtime dependencies with
`conda env update -f environment.yml` before running it.

The lock can also be generated manually:

```powershell
conda-lock lock -f environment.yml -p win-64
```

See [`DEVELOPMENT.md`](DEVELOPMENT.md) for more details.

`python build.py package` checks the frozen PDF helper's binary pipes and rendered
page pixels before creating the ZIP. A failed or timed-out check stops packaging.

### Documentation

Build the documentation:

```powershell
python build.py doc
```

Start the local documentation server from the repository root:

```powershell
micromamba run mkdocs serve --dev-addr 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/RoyiFileManager>.