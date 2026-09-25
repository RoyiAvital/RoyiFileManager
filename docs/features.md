# Features

{{ app_name }} is a fast, keyboard-focused file manager for Windows.

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
- Search names and file contents with `ripgrep`.
- Find by name, date, size or type with `fd`.

See the [tools](tools.md) and [search guide](search.md).

## Preview and Inspect

- Preview images, text, Markdown and highlighted source code with QuickView.
- Fit, zoom, pan or copy the displayed image.
- Calculate directory sizes in the Size column.
- Calculate hashes with a choice of algorithms.
- Cycle file and selection statistics in the status bar.

See [QuickView](tools.md#quickview), [Directory Size](tools.md#directory-size) and [File Hash](tools.md#file-hash).

## Work with Files

- Create files and folders.
- Send files to the Recycle Bin or delete permanently.
- Pack and unpack archives.
- Move or copy files into and out of archives.
- Copy full paths to the clipboard.

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