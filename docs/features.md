# Features

{{ app_name }} is a fast, keyboard-focused file manager for Windows.

For step-by-step examples, see [Everyday Workflows](workflows.md).

## Availability

Some guides describe the current development build, not just the latest release.

| Capability | Available In |
| --- | --- |
| Bundled Robocopy | 0.16.0 and newer |
| Bundled Batch File Renamer, including random letter/digit fields | 0.16.3 and newer |
| Create a duplicate file and Pack here | 0.16.4 and newer |
| Pane swapping, pattern selection and keypad selection shortcuts | Unreleased development builds |
| Select same extension, clipboard/link navigation and Command Center synonyms | Unreleased development builds |
| Numbered duplicate suggestions, copying multiple names and local free-space display | Unreleased development builds |

Check the [release notes](https://github.com/RoyiAvital/RoyiFileManager/blob/main/CHANGELOG.md)
for your installed version. An Unreleased instruction may not work in a released build.

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

- Preview images, PDFs, text, Markdown and highlighted source code with QuickView.
- Fit, zoom, pan or copy the displayed image.
- Calculate directory sizes in the Size column.
- Calculate hashes with a choice of algorithms.
- Generate recursive checksum files and verify their contents with twelve algorithms.
- Cycle file and selection statistics in the status bar.

See [QuickView](tools.md#quickview), [Directory Size](tools.md#directory-size), [File Hash](tools.md#file-hash) and [Checksum Files](tools.md#checksum-files).

## Work with Files

- Create files and folders.
- Send files to the Recycle Bin or delete permanently.
- Pack and unpack archives.
- Move or copy files into and out of archives.
- Copy full paths to the clipboard.
- Rename a filtered, ordered group with [Batch File Renamer](tools.md#batch-file-renamer).
- Copy or move with [Robocopy](tools.md#robocopy) as an alternative to F5/F6,
  using its different native overwrite and skip policies.

See [Archives](archives.md).

## Data Safety

- Files are copied completely before replacing an existing destination.
- Failed or canceled copies preserve existing data whenever possible.
- Risky operations involving file-system links are refused.
- Archive moves verify copied files before deleting their sources.

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