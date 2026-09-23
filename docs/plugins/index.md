# Your First Plug-in

RoyiFileManager keeps fman's Python plug-in model.

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
