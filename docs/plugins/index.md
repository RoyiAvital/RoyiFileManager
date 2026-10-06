# Your First Plug-in

{{ app_name }} keeps fman's Python plug-in model.

Create this folder:

```text
UserSettings/Plugins/User/Hello World/
├── hello_world/
│   └── __init__.py
└── Key Bindings.json
```

Add a key binding:

```json title="Key Bindings.json"
[
  { "keys": ["Ctrl+Alt+H"], "command": "say_hi" }
]
```

Add the command:

```python title="hello_world/__init__.py"
from fman import DirectoryPaneCommand, show_alert


class SayHi(DirectoryPaneCommand):
    def __call__(self):
        show_alert("Hello World!")
```

Open the Command Center. Run **Reload plugins**.

Press ++ctrl+alt+h++.

## What Happened?

The class name `SayHi` became the command ID `say_hi`.

The host created the command and supplied its pane.

Next, see the [API overview](../api/index.md).

## Manual Installation

Place trusted plug-in files under `UserSettings/Plugins/Third-party/<PluginName>/`.
The Python package and configuration files belong directly inside `<PluginName>`.

Run **Reload plugins** in Command Center. **List plugins** opens a plug-in's
folder; **Remove plugin** deletes an installed third-party plug-in.
There is no built-in downloader, and no `Plugin.json` installation metadata is required.

## Batch File Renamer Example

The independent [Batch File Renamer](https://github.com/RoyiAvital/RoyiFileManager/tree/main/plugins/BatchFileRenamer)
demonstrates mapped QuickBoard previews, optional caller status and public
no-overwrite renaming. Install it manually as described above; it is not bundled
automatically. Its README lists the required host API and template syntax.
