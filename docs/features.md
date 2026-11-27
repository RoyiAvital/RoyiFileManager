# Features

{{ app_name }} is a fast, keyboard-focused file manager for Windows.

For step-by-step examples, see [Everyday Workflows](workflows.md).

## Availability

Recent capabilities and the first release that includes them:

| Capability                                                                          | Available In     |
| ----------------------------------------------------------------------------------- | ---------------- |
| Bundled Robocopy                                                                    | 0.16.0 and newer |
| Bundled Batch File Renamer, including random letter/digit fields                    | 0.16.3 and newer |
| Create a duplicate file and Pack here                                               | 0.16.4 and newer |
| Pane swapping, pattern selection, keypad selection shortcuts and free-space display | 0.17.0 and newer |
| Select same extension, clipboard/link navigation, Command Center synonyms           | 0.17.0 and newer |
| Numbered duplicate suggestions and copying multiple names (`Shift+F11`)             | 0.17.0 and newer |
| QuickView Table View for CSV/TSV files                                              | 0.18.0 and newer |
| Command Palette categories and YAML configuration files                             | 0.19.0 and newer |
| QuickView animated images (GIF, WebP, APNG)                                         | 0.19.2 and newer |
| Bundled File Attributes Editor (`QuickCheckList`)                                   | 0.20.0 and newer |
| Find blocking processes and Explorer archive paste/drop                             | 0.20.1–0.20.4    |
| Compressed tars, Unpack to... and read-only archives                                | 0.21.0 and newer |
| Native Rust directory enumerator (`fsenum`) and `Column.order`                      | 0.22.0 and newer |

Check the [release notes](https://github.com/RoyiAvital/RoyiFileManager/blob/main/CHANGELOG.md)
for details on your installed version.

## Dual-Pane Workflow

- View a source and destination together.
- Copy, move, rename and delete with function keys.
- Sync one pane to the location of the other.
- Open commands from the Command Center.
- Keep settings beside the application.
- Do not intentionally write to the Windows Registry.

See the [keyboard shortcuts](shortcuts.md).

## Find Anything

- Filter the current pane while typing.
- Find names with fuzzy matching.
- Include subfolders with recursive fuzzy find.
- Search indexed folders with [Everything syntax](tools.md#everything-search).
- Search names and file contents with `ripgrep`.
- Find by name, date, size or type with `fd`.

See the [tools](tools.md) and [search guide](search.md).

## Preview and Inspect

- Preview images, PDFs, CSV/TSV tables, text, Markdown and highlighted source code with QuickView.
- Fit, zoom, pan or copy the displayed image.
- Calculate directory sizes in the Size column.
- Calculate hashes with a choice of algorithms.
- Generate recursive checksum files and verify their contents with twelve algorithms.
- Cycle file and selection statistics in the status bar.

See [QuickView](tools.md#quickview), [Directory Size](tools.md#directory-size), [File Hash](tools.md#file-hash) and [Checksum Files](tools.md#checksum-files).

## Work with Files

- Create files and folders.
- Send files to the Recycle Bin or delete permanently.
- Pack and unpack archives: **Unpack here** or **Unpack to...** a chosen folder.
- Browse archives and copy items out of them, including compressed tars such as `.tar.gz`.
- Copy full paths to the clipboard.
- Rename a filtered, ordered group with [Batch File Renamer](tools.md#batch-file-renamer).
- Edit file and folder attributes, optionally recursively, with
  [Edit attributes](tools.md#edit-attributes).
- See which processes keep a file or folder in use with
  [Find blocking processes](tools.md#find-blocking-processes), without
  assuming that every reported user blocks rename or delete.
- Copy or move with [Robocopy](tools.md#robocopy) as an alternative to F5/F6,
  using its different native overwrite and skip policies.

See [Archives](archives.md).

## Data Safety

- Files are copied completely before replacing an existing destination.
- Failed or canceled copies preserve existing data whenever possible.
- Risky operations involving file-system links are refused.
- Archives are never changed. Extraction publishes only complete output.

See [Advanced Notes](advanced.md#file-transfers).

## Use External Tools

- Configure separate text editors and viewers.
- Compare files or folders with an external comparator.
- Open the current folder in a terminal or Explorer.
- Use presets for popular Windows tools.

See [Configuration](configuration.md).

## Organize and Extend

- Save locations in Favorites.
- Reuse recent Command Center actions.
- Browse running processes in a pane.
- Add commands, panels and tables with plug-ins.
- Use the public `fman` plug-in API.

See [Favorites](tools.md#favorites) and [Process Pane](tools.md#process-pane).

Start with [your first plug-in](plugins/index.md) or browse the [API overview](api/index.md).