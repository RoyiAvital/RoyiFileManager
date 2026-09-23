# Configuration

RoyiFileManager is portable.

Settings live in `UserSettings` beside the application.

Copy this folder to back up or move your configuration.

## Application Settings

Most preferences save automatically as you use the application:

- Pane locations and sorting.
- Favorites.
- QuickView display mode.
- Directory size state.
- Search modes and options.
- Status bar mode.

Close RoyiFileManager before editing configuration files by hand.

User overrides live in:

```text
UserSettings\Plugins\User\Settings
```

Leave `Local`, `Panes`, `Sort Settings` and `Visited Paths` to the application.

## Behavior and Limits

Create these files in the user Settings folder. A `(Windows)` variant takes precedence over the generic filename.

Restart RoyiFileManager after external edits.

### Fuzzy Find

Use `SearchFileFuzzy.json`.

| Parameter | Default | Effect |
| --- | ---: | --- |
| `mode` | `fuzzy` | Use `fuzzy` subsequence matching or `regular` substring matching. |
| `max_recursive_entries` | 50,000 | Maximum files and folders inspected while building a find index. |
| `max_results` | 100 | Maximum results shown in Quicksearch. |
| `include_hidden` | `true` | Include hidden entries and hidden directory trees. |
| `show_metadata` | `false` | Show modified time and size below each result. |

Limits must be positive integers. Larger values can use more time and memory.

```json
{
  "max_recursive_entries": 100000,
  "max_results": 250,
  "include_hidden": false
}
```

### Search Files

Use `SearchFiles.json`.

| Parameter | Default | Effect |
| --- | ---: | --- |
| `name_mode` | `glob` | Filename matching: `literal`, `glob` or `regex`. |
| `content_mode` | `literal` | Content matching: `literal`, `glob` or `regex`. |
| `recursive` | `true` | Include subfolders. |
| `encoding` | `auto` | Use `auto` or `windows-1252`. |
| `max_rows` | 10,000 | Maximum result rows retained. |
| `max_text_bytes` | 16 MiB | Maximum retained result text and payload. |
| `max_file_lines` | 200 | Maximum matching lines retained per file. |
| `max_file_bytes` | 50 MiB | Largest file eligible for content search. |

Numeric limits must be positive. They can be lowered, but not raised above their defaults.

### Find Files with `fd`

Use `FindFiles.json` or change these options in the Find Files panel.

| Parameter | Default | Effect |
| --- | ---: | --- |
| `pattern_mode` | `glob` | Name matching: `literal`, `glob` or `regex`. |
| `case_mode` | `smart` | Use `smart`, `sensitive` or `insensitive` matching. |
| `type` | `f` | Search for files by default. |
| `full_path` | `false` | Match the absolute path instead of only the name. |
| `recursive` | `true` | Include subfolders. |
| `hidden` | `false` | Include hidden entries. |
| `honor_gitignore` | `true` | Honor `.gitignore` rules. |
| `follow_symlinks` | `false` | Follow symbolic links. |
| `min_size_unit`, `max_size_unit` | `b` | Default size units for panel bounds. |

**Max Results** is a per-search field. Leave it blank to count all matches, or enter a positive integer.

The results table retains at most 10,000 rows or 16 MiB. An uncapped search can continue counting after the table is full.

### Other Behavior Settings

| File | Parameter | Default | Effect |
| --- | --- | ---: | --- |
| `Status Bar.json` | `mode` | `disabled` | Use `disabled`, `single` or `dual`. ++ctrl+s++ cycles the mode. |
| `Status Bar.json` | `max_entries` | 5,000 | Maximum pane entries inspected for status totals. |
| `Status Bar.json` | `size_divisor` | 1,024 | Use 1,024 for KiB or 1,000 for KB. |
| `DirectorySize.json` | `enabled` | `false` | Enable automatic directory totals. |
| `DirectorySize.json` | `max_files` | 10,000,000 | Regular files counted per root. Use `0` for unlimited. |
| `Favorites.json` | `max_favorites` | 200 | Maximum saved favorites before replacement is offered. |
| `CalculateFileHash.json` | `default_algorithm` | `sha256` | Initially selected hash algorithm. |
| `CalculateFileHash.json` | `remember_last_algorithm` | `false` | Remember the last accepted algorithm. |
| `CalculateFileHash.json` | `auto_copy` | `false` | Copy a completed current result automatically. |
| `CalculateFileHash.json` | `chunk_size_mib` | 4 | Read chunk size. Values are clamped to 1–64 MiB. |
| `QuickView.json` | `image_mode` | `fit` | Use `fit` or `actual_size`. |

### Fixed Safety Limits

These values are not user-configurable.

| Feature | Limit |
| --- | ---: |
| Shared result tables | 10,000 rows |
| Shared result-table payload | 16 MiB |
| QuickView encoded image | 64 MiB |
| QuickView image dimensions | 65,536 pixels per edge |
| QuickView decoded image | 128 million pixels |

## Keyboard Shortcuts

Press ++f1++ to view active shortcuts.

Create `Key Bindings (Windows).json` in the user Settings folder to add custom bindings:

```json
[
  {
    "keys": ["Ctrl+Alt+F"],
    "command": "find_files"
  }
]
```

Restart RoyiFileManager after editing the file.

See the [keyboard shortcut reference](shortcuts.md).

## Appearance

Create `Theme (Windows).css` in the user Settings folder for visual overrides.

The file uses Qt Style Sheet syntax. Restart after changing it.

## Text Editor and Viewer

Press ++ctrl+shift+p++ and run **Set text editor** or **Set text viewer**.

1. Choose Notepad++, CudaText, Notepad 4, EmEditor or **Manual configuration**.
2. Select the program's `.exe` file.
3. Enter arguments when using Manual configuration.

Press ++f4++ to edit. Press ++f3++ to view.

Do not add a file placeholder to manual arguments. RoyiFileManager appends the selected file path.

The editor and viewer are independent. Each setup list also has a Clear option.

## File and Folder Comparators

Press ++ctrl+shift+p++ and run **Set file comparator** or **Set folder comparator**.

Choose Meld, Beyond Compare, WinMerge, SmartSynchronize or **Manual configuration**.

Run **Compare files** or **Compare folders** from the Command Center.

Manual arguments must not contain path placeholders. RoyiFileManager appends both paths.

The file and folder comparators are independent. Each setup list also has a Clear option.

## Terminal and Explorer

Press ++f9++ to open a terminal in the current folder.

Press ++f10++ to open the folder in Explorer.

Windows defaults work without configuration. Advanced users can override them in `Core Settings (Windows).json`:

```json
{
  "terminal": {
    "args": ["C:\\Tools\\Terminal\\terminal.exe"],
    "cwd": "{curr_dir}",
    "shell": false
  },
  "native_file_manager": {
    "args": ["C:\\Tools\\FileManager\\manager.exe", "{curr_dir}"],
    "shell": false
  }
}
```

Replace the example executable paths with installed programs.

## Advanced Configuration

Configuration files are layered. User values override bundled defaults.

Use `Core Settings (Windows).json` for advanced Core overrides. Tool setup commands write only their changed values there.

Back up `UserSettings` before manual changes. Invalid JSON is reported when the related plug-in loads.