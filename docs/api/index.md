# API Overview

Plug-ins use the public `fman` modules.

| Module | Use it for |
| --- | --- |
| `fman` | Commands, panes, settings, dialogs, tasks |
| `fman.fs` | File systems and columns |
| `fman.listing` | Immutable directory snapshots |
| `fman.url` | Application URLs |
| `fman.clipboard` | Text and file clipboard access |
| `fman.ui` | Lists, tables, panels and navigation |

## Commands

Use `ApplicationCommand` for window-wide actions.

Use `DirectoryPaneCommand` for actions tied to a pane.

```python
from fman import DirectoryPaneCommand, show_status_message


class ShowCurrentFile(DirectoryPaneCommand):
    category = "Navigation"
    aliases = ("Show current file",)

    def __call__(self):
        file_url = self.pane.get_file_under_cursor()
        show_status_message(file_url or "No file selected")
```

The Command Center lists it as **Navigation: Show current file**. Set
`category = ""` for no category. Bundled categories are `Application`,
`Settings`, `File`, `Clipboard`, `Selection`, `Navigation`, `View`, `Search`,
`Favorites` and `Tools`.

## Pane Essentials

| Method | Result |
| --- | --- |
| `get_path()` | Current directory URL |
| `get_file_under_cursor()` | Current file URL, or `None` |
| `get_selected_files()` | Selected file URLs |
| `set_path(url)` | Request navigation |
| `reload()` | Reload the current location |
| `run_command(name, args)` | Run a pane command |

A `DirectoryPaneCommand` also has `self.get_chosen_files()`. It returns the
selected files, else the file under the cursor, else `[]`.

Paths in the API are URLs. Use `fman.url` helpers to convert them.

## Snapshot File Systems and Columns

Custom file systems return an immutable `fman.listing.Listing` from `scan(...)`.
Columns format visible cells without I/O via `text(...)` and supply sort order
via `keys(...)` or the optional `order(...)` hook:

```python
from array import array
from fman.fs import Column, FileSystem
from fman.listing import Listing


class NotesFileSystem(FileSystem):
    scheme = "notes://"
    read_only_message = "Notes are read-only."

    def get_default_columns(self, path):
        return ("core.Name", "my_plugin.WordCount")

    def scan(self, path, check_canceled):
        check_canceled()
        return Listing.create(
            self.scheme + path,
            ("alpha.txt", "beta.txt"),
            sizes=(120, 45),
            extra=(("words", (24, 9)),),
        )


class WordCount(Column):
    display_name = "Words"

    def text(self, listing, index):
        return str(listing.column("words")[index])

    def keys(self, listing, ascending):
        return listing.column("words")

    def order(self, listing, ascending):
        # Optional fast path: return every entry index in display order,
        # or return None to fall back to keys(...).
        values = listing.column("words")
        indices = sorted(range(len(values)), key=values.__getitem__, reverse=not ascending)
        return array("I", indices)
```

Setting `read_only_message` tells the host to refuse every write operation with
that text before calling any provider. See [Architecture](../architecture.md)
for how snapshots flow through the pane model.

## Settings

User-editable settings are YAML files and may contain comments:

```python
from fman import load_settings, save_settings

settings = load_settings("MyPlugin.yaml", {"enabled": True})
settings["enabled"] = False
save_settings("MyPlugin.yaml", settings)
```

Ship commented defaults as `MyPlugin.yaml` in the plug-in folder. Saving writes
only values that differ from those defaults and keeps the user's comments.

Use `load_json` and `save_json` for internal state that users do not edit.

Keep mutable data under `UserSettings`.

## Threading

Commands normally run in workers.

Qt widgets and models stay on the Qt thread.

Long work must support cancellation or stale-result rejection.

## Complete Reference

The [full plug-in API reference](https://github.com/RoyiAvital/RoyiFileManager/blob/main/PlugIn.md) documents commands, listeners, filesystems, snapshots, tasks, UI controls and compatibility boundaries.
