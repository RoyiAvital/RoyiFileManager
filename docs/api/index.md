# API Overview

Plug-ins use the public `fman` modules.

| Module | Use it for |
| --- | --- |
| `fman` | Commands, panes, settings, dialogs, tasks |
| `fman.fs` | File systems and columns |
| `fman.listing` | Immutable directory snapshots |
| `fman.url` | Application URLs |
| `fman.clipboard` | Text and file clipboard access |
| `fman.ui` | Panels, controls and navigation |

## Commands

Use `ApplicationCommand` for window-wide actions.

Use `DirectoryPaneCommand` for actions tied to a pane.

```python
from fman import DirectoryPaneCommand, show_status_message


class ShowCurrentFile(DirectoryPaneCommand):
    def __call__(self):
        file_url = self.pane.get_file_under_cursor()
        show_status_message(file_url or "No file selected")
```

## Pane Essentials

| Method | Result |
| --- | --- |
| `get_path()` | Current directory URL |
| `get_file_under_cursor()` | Current file URL, or `None` |
| `get_selected_files()` | Selected file URLs |
| `get_chosen_files()` | Selection, then cursor fallback |
| `set_path(url)` | Request navigation |
| `reload()` | Reload the current location |
| `run_command(name, args)` | Run a pane command |

Paths in the API are URLs. Use `fman.url` helpers to convert them.

## Settings

```python
from fman import load_json, save_json

settings = load_json("MyPlugin.json", {"enabled": True})
settings["enabled"] = False
save_json("MyPlugin.json", settings)
```

Keep mutable data under `UserSettings`.

## Threading

Commands normally run in workers.

Qt widgets and models stay on the Qt thread.

Long work must support cancellation or stale-result rejection.

## Complete Reference

The [full plug-in API reference](https://github.com/RoyiAvital/RoyiFileManager/blob/main/PlugIn.md) documents commands, listeners, filesystems, snapshots, tasks, UI controls and compatibility boundaries.
