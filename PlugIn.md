# Plug-in API Reference

This document describes the plug-in APIs implemented in this repository,
including the legacy fman 1.7.5 API and the provisional RoyiFileManager additions.
It documents current behavior, not proposed APIs. Source links are provided for
contracts whose details matter when extending the application.

## Contents

- [Compatibility and boundaries](#compatibility-and-boundaries)
- [Plug-in structure and discovery](#plug-in-structure-and-discovery)
- [Commands](#commands)
- [Panes and windows](#panes-and-windows)
- [Directory listeners](#directory-listeners)
- [Configuration](#configuration)
- [Dialogs and status messages](#dialogs-and-status-messages)
- [Legacy Quicksearch](#legacy-quicksearch)
- [Tasks](#tasks)
- [Filesystems and columns](#filesystems-and-columns)
- [URL helpers](#url-helpers)
- [Clipboard](#clipboard)
- [UI extension](#ui-extension)
- [Threading and failure handling](#threading-and-failure-handling)
- [Examples](#examples)

## Compatibility and Boundaries

| Module | Purpose | Status |
| --- | --- | --- |
| [fman](src/main/python/fman/__init__.py) | Commands, listeners, pane/window handles, settings, dialogs, tasks | Legacy API plus additive host features |
| [fman.fs](src/main/python/fman/fs.py) | Filesystem operations, filesystem providers, columns | Legacy API |
| [fman.url](src/main/python/fman/url.py) | Application URL manipulation | Legacy API |
| [fman.clipboard](src/main/python/fman/clipboard.py) | Text and file clipboard operations | Legacy API |
| [fman.ui](src/main/python/fman/ui.py) | QuickList, Panel, controls, hosting, settings binding, navigation | Provisional RoyiFileManager extension |

The upstream fman 1.7.5 plug-in API is preserved. `FMAN_VERSION` is the upstream
compatibility value, not a feature-negotiation version for `fman.ui`. Consult
[CHANGELOG.md](CHANGELOG.md) for extension changes and migration notes.

- Do not import `fman.impl`, access private host fields such as `_widget` or
  `_theme`, or depend on another bundled plug-in's internals as though they were
  host APIs. A plug-in may organize its own implementation into private modules.
- Use explicit imports. Imported implementation dependencies visible in a module
  are not additional public exports. Pane/window objects are supplied by the
  host; their constructors are not plug-in construction APIs.
- `fman.ui` currently exposes Qt-derived components. Its documented methods are
  the intended integration surface, but inherited Qt methods remain technically
  accessible. This is not a sandbox or a toolkit-independent wrapper API. The
  stricter abstraction in [TODO.md](TODO.md) is not implemented yet.
- Raw parent widgets and Qt closure signals are not exposed through the general
  `Window`/`DirectoryPane` API. Use `pane.on_closed(callback)` and UI hosting.
- The unshipped `BottomPanel` and public `set_bottom_panel` aliases were removed.
  Use `Panel` and `PaneToolWindow.set_panel(panel)`.
- Treat plug-ins as trusted Python code. Keep mutable data under `UserSettings`
  and do not write to the Windows Registry.

## Plug-in Structure and Discovery

Install user plug-ins beneath `UserSettings/Plugins/User`. A plug-in directory
contains one or more immediate Python package directories with an `__init__.py`.
For example:

```text
UserSettings/Plugins/User/MyPlugin/
    my_plugin/
        __init__.py
        ui.py
    Key Bindings.json
    MyPlugin.json
    Theme.css
```

The loader inspects classes exposed in each package's `__init__.py` namespace.
Define extension classes there or import them there from submodules. Recognized
bases are `ApplicationCommand`, `DirectoryPaneCommand`, `DirectoryPaneListener`,
`FileSystem`, `Column`, and `UiController`. An unimported class in a submodule is
not discovered automatically. Use unique package names to avoid module collisions.
Avoid importing other plug-ins' concrete extension classes into that namespace.

Loading also registers JSON configuration, root-level `.ttf` fonts, `Theme.css`,
key bindings, and context menus. Platform variants such as
`Key Bindings (Windows).json` and `Theme (Windows).css` are supported. On unload,
UI owners are invalidated before registrations and package modules are removed.
There is no general documented `plugin_loaded()`/`plugin_unloaded()` hook; do not
assume arbitrary import-time threads will be cleaned up by the loader.

### Key Bindings and Context Menus

`Key Bindings.json` is a list of records with a registered `command`, nonempty
`keys` list, and optional `args` dictionary. Keys use the host's Qt-style shortcut
notation. The current dispatcher uses only `keys[0]`; use separate binding
records for alternative shortcuts. Additional entries are not multi-step chords.

```json
[
  { "keys": ["Ctrl+Alt+J"], "command": "show_example", "args": {"query": ""} }
]
```

`File Context Menu.json` applies when a file item is under the mouse;
`Folder Context Menu.json` applies to empty pane space. Records accept `command`,
optional `args`, optional `caption`, and optional grouping `id`. A caption of
`"-"` is a separator. Without a caption, the first command alias is used. Pane
commands see the clicked item's context for visibility and execution, which may
differ from the ordinary cursor context.

```json
[
  { "id": "my_plugin", "command": "show_example", "caption": "Example" }
]
```

Source: [loader](src/main/python/fman/impl/plugins/plugin.py),
[bindings](src/main/python/fman/impl/plugins/key_bindings.py),
[menus](src/main/python/fman/impl/plugins/context_menu.py). These are implementation
references, not modules to import in a plug-in.

## Commands

Import these APIs from `fman`.

### ApplicationCommand

Subclass `ApplicationCommand`; the host constructs it with `window` and exposes
`self.window`. Implement `__call__(self, ...)`; command arguments are keyword
arguments. `aliases` defaults to a human-readable class name and can be
overridden with a sequence of names. Keep constructors lightweight.

### DirectoryPaneCommand

Subclass `DirectoryPaneCommand`; the host supplies `self.pane`. Implement:

| Member | Contract |
| --- | --- |
| `__call__(self, ...)` | Execute the command with supplied keyword arguments. |
| `is_visible(self)` | Default `True`; return false to hide it from pane-command discovery/context menus. This is not authorization and does not block direct invocation. |
| `get_chosen_files(self)` | Return selected URLs, otherwise the URL under the cursor as a one-element list, otherwise `[]`. |
| `aliases` | Optional class-level sequence overriding aliases derived from the class name. |

Class names become snake-case command IDs: `ShowExample` becomes `show_example`.
Application command instances are reused; pane command instances are cached per
pane. Do not put invocation-specific state in attributes without considering
concurrent calls.

### Command and Loader Functions

| Function | Contract |
| --- | --- |
| `get_application_commands()` | Return registered application command names. |
| `run_application_command(name, args=None)` | Dispatch a registered application command; `args` is a keyword-argument dictionary. No command return-value/future contract. |
| `get_application_command_aliases(command_name)` | Return aliases for a registered application command. |
| `load_plugin(plugin_path)` | Load a plug-in directory by native filesystem path; return a success boolean, with load errors reported by the host. |
| `unload_plugin(plugin_path)` | Unload a previously loaded plug-in directory; an unloaded path raises `ValueError`. |

Commands dispatched from the main thread run in daemon workers; dispatch from
an existing worker executes inline. Constructors and visibility checks are not
general worker-operation hooks. Ordinary command exceptions are reported by the
host. Do not assume `run_command()` returning means navigation has finished.

## Panes and Windows

The host supplies `DirectoryPane` and `Window` handles. They are defined in the
`fman` module but are not entries in its wildcard `__all__` export list. Do not
construct them with internal widgets yourself.

### DirectoryPane

`pane.window` is its public parent-window handle.

| Method | Contract |
| --- | --- |
| `get_commands()` | Registered pane command names. |
| `run_command(name, args=None)` | Run a pane command, honoring command rewrite listeners. |
| `get_command_aliases(command_name)` | Aliases for a registered pane command. |
| `is_command_visible(command_name)` | Evaluate visibility in this pane's context. |
| `get_selected_files()` | Selected file URLs; current highlight is separate. |
| `get_file_under_cursor()` | Current file URL, or no current value. |
| `get_path()` | Current directory URL, not a native path. |
| `set_path(dir_url, callback=None, onerror=host_default)` | Request a directory change, honoring location rewrite listeners. `callback()` signals initialization; do not treat it as a complete navigation outcome. |
| `reload()` | Reload the pane's location. |
| `edit_name(file_url, selection_start=0, selection_end=None)` | Start inline name editing and select the specified text range. |
| `select_all()` / `clear_selection()` | Select all visible pane entries or clear selection. |
| `toggle_selection(file_url)` | Toggle one entry. |
| `select(file_urls)` / `deselect(file_urls)` | Update selection for URLs; missing-entry errors are ignored by these wrappers. |
| `place_cursor_at(file_url)` | Move the current highlight to a URL. |
| `focus()` | Focus this pane. |
| `get_columns()` | List of current qualified column-name strings. |
| `set_sort_column(column, ascending=True)` | Set a displayed column by qualified name and direction; a missing column raises `ValueError`. |
| `get_sort_column()` | Return `(qualified_column_name, ascending_bool)`. |
| `on_closed(callback)` | RoyiFileManager addition: register no-argument pane-destruction callback; return an idempotent unsubscribe function. |

Cursor movement methods all accept `toggle_selection=False`:
`move_cursor_down`, `move_cursor_up`, `move_cursor_home`, `move_cursor_end`,
`move_cursor_page_down`, and `move_cursor_page_up`. Setting the flag combines
selection changes with the corresponding file-pane movement behavior.

`set_path`'s error callback receives `(exception, attempted_url)` and may return
a replacement URL or raise. The host default retries the parent for a missing
location. The initialization callback can run on different threads depending
on the model path; it is not a UI-thread callback guarantee. For a hosted UI
operation requiring success/failure/cancellation, use `fman.ui.navigate` instead.

`on_closed` callbacks run once on the UI thread. Registration and unsubscription
may be called from a command worker or the UI thread; worker calls dispatch
synchronously. Unsubscription is safe after destruction. Register while the
pane is still alive, and do not hold a lock needed by the UI during registration.

### Window

| Method | Contract |
| --- | --- |
| `get_panes()` | Return this window's pane handles. Do not mutate the host-owned list. |
| `add_pane()` | Add and return a host-managed directory pane. |
| `minimize()` | Minimize the window. |
| `reset_geometry(width, height)` | Reset window geometry using the supplied dimensions. |
| `set_extended_status_bar(settings)` | RoyiFileManager host entry point for extended status-bar settings; use the settings contract documented below. |

The removed methods `tool_parent`, `get_quicklist_item_css`, `set_panel`,
`set_bottom_panel`, and `remove_bottom_panel` are not general Window APIs. Mount
plug-in panels through `PaneToolWindow.set_panel()`.

## Directory Listeners

Subclass `fman.DirectoryPaneListener`. The host supplies `self.pane`; default
hooks are no-ops.

| Hook | Contract |
| --- | --- |
| `on_doubleclicked(file_url)` | Notification of a double-clicked file. |
| `on_name_edited(file_url, new_name)` | Notification of an inline name edit. |
| `on_path_changed()` | Notification that the pane path changed. |
| `before_location_change(url, sort_column='', ascending=True)` | Return a replacement `(url, sort_column, ascending)` or no replacement. |
| `on_files_dropped(file_urls, dest_dir, is_copy_not_move)` | Notification of dropped URLs and copy/move intent. |
| `on_command(command_name, args)` | Return a replacement `(command_name, args)` or no replacement. |
| `on_location_bar_clicked()` | Notification of a location-bar click. |

Notification hooks run in host-created daemon threads. Rewrite hooks run
synchronously in their caller's context. A rewrite restarts listener processing;
never create an endlessly repeating command rewrite or mutually cycling rewrites.
Do not manipulate Qt widgets from notification threads.

## Configuration

| Function | Contract |
| --- | --- |
| `load_json(name, default=None, save_on_quit=False)` | Load merged configuration by filename. Return `default` when no value exists. Can return a shared cached mutable object. |
| `save_json(name, value=None)` | Persist a differential override; omitted/`None` value uses the cached value. Save completes before replacing the cache. |

Names are shared across loaded plug-ins, not automatically package-namespaced.
Use distinctive filenames. Layers include generic and platform-specific files;
later dictionaries shallowly override earlier dictionaries, and later lists are
prepended to earlier lists. Mismatched JSON types raise `ValueError`.

User overrides are normally written to
`UserSettings/Plugins/User/Settings/<Name> (Windows).json`. Saves use a temporary
file followed by atomic replacement. Values equal to defaults can be omitted
from the on-disk override. Inherited dictionary keys cannot simply be deleted,
and inherited list suffixes cannot be arbitrarily edited through differential
saving; such requests may raise `ValueError`.

Copy loaded data before editing when save failure must leave the cache intact.
Use a shared `settings_resource(name).lock` for multi-step read/modify/write
transactions shared by commands and UI. `save_on_quit=True` schedules cached
values for persistence at shutdown; explicit saving is preferable for completed
user actions. `JsonSettings` supplies asynchronous control bindings.

### Constants

| Name | Meaning |
| --- | --- |
| `PLATFORM` | Host platform label used for platform-specific configuration. |
| `FMAN_VERSION` | Upstream compatibility version, currently `'1.7.5'`. |
| `DATA_DIRECTORY` | Native path to portable `UserSettings`; `ROYIFILEMANAGER_USER_SETTINGS` overrides it when set before importing fman. |
| `OK`, `CANCEL`, `YES`, `NO`, `YES_TO_ALL`, `NO_TO_ALL`, `ABORT` | Dialog result/button constants. Combine choices with bitwise OR. |

## Dialogs and Status Messages

Import from `fman`. Legacy dialog functions dispatch to the UI thread and block
the calling command until the dialog completes; they are not asynchronous
callbacks. For modeless plug-in UI, prefer the owned ToolWindow prompt methods.

| Function | Return and behavior |
| --- | --- |
| `show_alert(text, buttons=OK, default_button=OK)` | Show an alert and return the selected button constant. Text is converted to a string. |
| `show_prompt(text, default='', selection_start=0, selection_end=None)` | Return `(text, True)` on acceptance or `('', False)` on cancellation. |
| `show_file_open_dialog(caption, dir_path, filter_text='')` | Return the selected native filename, or an empty string on cancellation. This does not return an application URL. |
| `show_status_message(text, timeout_secs=None)` | Display status text. A truthy timeout clears it through the host timer; no timeout leaves it until replaced. |
| `clear_status_message()` | Restore the default `Ready.` status text. |

For file filters, use Qt-style patterns such as `Text files (*.txt);;All files (*)`.
For alerts, use public button constants, for example `buttons=YES | NO` with
`default_button=NO`; do not import QMessageBox merely to obtain these constants.

### Extended Status Bar

`window.set_extended_status_bar(settings)` configures the live host status bar.
Pass a complete dictionary with valid values; this method does not sanitize or
persist plug-in input:

```python
settings = {'mode': 'single', 'max_entries': 5000, 'size_divisor': 1024}
```

- `mode`: `'disabled'`, `'single'` (active pane), or `'dual'` (per pane).
- `max_entries`: positive non-boolean integer limiting size queries.
- `size_divisor`: `1000` or `1024`; affects displayed size units.

Disabled mode removes the feature-specific service and focus tracking. Enabled
mode uses host-managed background calculations. Treat this as a window-wide
host setting, not a place to mount plug-in widgets. Do not import internal
status-bar classes or constants; this addition is separate from status text.

## Legacy Quicksearch

```python
show_quicksearch(get_items, get_tab_completion=None, query='', item=0)
QuicksearchItem(value, title=None, highlight=None, hint='', description='')
```

- `get_items(query)` returns an iterable of `QuicksearchItem` records; it is
  called synchronously on the UI thread for the initial query and text changes.
  Keep it fast and free of blocking I/O. The host materializes the iterable.
- `get_tab_completion(query, item)` receives the highlighted **record**, or
  `None`, and returns replacement query text or `None` for no completion.
- `query` seeds the field; `item` selects the initial visible row by index.
- Acceptance returns `(query_text, selected_value)`. `selected_value` is `None`
  if no row is current. Canceling the dialog returns `None`, not a tuple.
- `QuicksearchItem.value` is the result payload. `title` defaults to `value`;
  `highlight` defaults to an empty list of title character positions. `hint` and
  `description` provide secondary presentation text.

Legacy Quicksearch is a single-result modal picker: clicking a row or pressing
Enter accepts. It is different from QuickList's independent current/selected
state and persistent modeless hosting. Do not substitute one for the other
without accounting for those interaction and return-value differences.

## Tasks

Import `Task` and `submit_task` from `fman`.

```python
Task(title, size=0, fn=lambda: None, args=(), kwargs=None)
submit_task(task)
```

The base `Task.__call__()` invokes `fn(*args, **kwargs)`; alternatively subclass
Task and implement `__call__`. `submit_task` attaches a progress dialog and runs
the task **synchronously in the calling thread**. It does not create a worker.
Use it from a command worker, not a Qt callback doing long-running work.

| Method | Contract |
| --- | --- |
| `get_title()` | Task title. |
| `set_text(text)` | Update progress detail text. |
| `set_size(size)` / `get_size()` | Set/read the task's total progress units. |
| `set_progress(progress)` / `get_progress()` | Set/read completed progress units. |
| `check_canceled()` | Raise `Task.Canceled` when the attached progress dialog was canceled. Call cooperatively during work. |
| `run(subtask)` | Run a child task synchronously using the parent's progress context; finish its progress on normal return. |
| `show_alert(*args, **kwargs)` | Show an alert through the attached progress dialog using the host alert arguments. |

`Task.Canceled` derives from `KeyboardInterrupt`, not `Exception`. `submit_task`
catches it, closes/cancels the progress dialog, and restores the previous dialog
binding. Other exceptions propagate to the calling command's error handling.
Cancellation does not forcibly interrupt an OS call or undo completed mutations.

## Filesystems and Columns

### Filesystem Functions

Import from `fman.fs`. All URL arguments below are application URLs. Operations
delegate to the registered scheme provider and can raise `OSError` subclasses,
`NotImplementedError`, or provider-specific failures. They do not add user
confirmation automatically. Unknown schemes can surface as `FileNotFoundError`.

| Function | Contract |
| --- | --- |
| `exists(url)` | Whether the target exists according to its provider. |
| `is_dir(existing_url)` | Whether an existing target is a directory; missing paths should raise `FileNotFoundError`, unlike `os.path.isdir`. |
| `touch(url)` | Ask the provider to create/touch a file. Exact overwrite behavior is provider-specific. |
| `mkdir(url)` | Create one directory; existing target/missing parent follow provider errors. |
| `makedirs(url, exist_ok=False)` | Create parents recursively; module-level default rejects an existing destination. |
| `iterdir(url)` | Iterable of child **names**, not full URLs. Results can be cached/lazy. Join names to the directory URL. |
| `query(url, fs_method_name)` | Invoke the named provider metadata method with the scheme-free path; return its result. This is provider extensibility, not an arbitrary method on the public pane. |
| `resolve(url)` | Resolve a provider URL, including its existence/normalization semantics. |
| `samefile(url1, url2)` | Resolve both and compare provider identity semantics. |
| `copy(src_url, dst_url)` | Copy to the complete destination URL, not merely its parent. |
| `move(src_url, dst_url)` | Move to the complete destination URL. |
| `delete(url)` | Delete according to the provider; no implicit trash or confirmation. |
| `move_to_trash(url)` | Ask the provider to trash the target. |
| `prepare_copy(src_url, dst_url)` | Return provider-defined tasks for a copy, without running them. |
| `prepare_move(src_url, dst_url)` | Return provider-defined tasks for a move. |
| `prepare_delete(url)` | Return provider-defined deletion tasks. |
| `prepare_trash(url)` | Return provider-defined trash tasks; see the legacy default caveat below. |
| `notify_file_added(url)` | Announce a created entry to the host. |
| `notify_file_changed(url)` | Announce a changed entry to subscribed consumers. |
| `notify_file_removed(url)` | Announce removal so cached listings and consumers can update. |

Cross-scheme copy/move first asks the source provider. On `NotImplementedError`
or `io.UnsupportedOperation`, the host may try the destination provider. There
is no general host-provided byte-stream copy API or cross-provider fallback that
guarantees every pair of schemes works.

### FileSystem Providers

Subclass `fman.fs.FileSystem`, set `scheme` including `://`, and expose the class
in your package namespace. Providers are constructed without arguments. Call
the base constructor if overriding `__init__`, and keep shared provider state
thread-safe. Listing and metadata requests can run concurrently on workers.

Single-target provider methods receive a **scheme-free path**. Copy/move methods
receive full source/destination URLs so they can negotiate cross-scheme transfers.

| Provider member | Contract/default |
| --- | --- |
| `scheme = 'example://'` | Unique registered URL scheme. Base default is empty and should be overridden. |
| `iterdir(path)` | Implement for browsable directories; yield child names as strings. Not supplied by the base class. |
| `get_default_columns(path)` | Qualified column identifiers; default `('core.Name',)`. |
| `name(path)` | Display name; default final slash-separated path component. |
| `is_dir(existing_path)` | Override to distinguish directories and raise on missing entries. Base returns `False`. |
| `exists(path)` | Default calls `is_dir` and maps `FileNotFoundError` to `False`. |
| `resolve(path)` | Default validates existence and returns normalized `scheme + path`. |
| `samefile(path1, path2)` | Default compares resolved URLs. |
| `watch(path)` / `unwatch(path)` | Optional subscription hooks; default no-ops. |
| `notify_file_added(path)` / `notify_file_removed(path)` / `notify_file_changed(path)` | Announce scheme-free paths from the provider. |
| `mkdir(path)` / `touch(path)` / `delete(path)` / `move_to_trash(path)` | Implement supported mutations; defaults raise `NotImplementedError`. |
| `makedirs(path, exist_ok=True)` | Base recursive implementation using `mkdir`; note its default differs from the module-level wrapper. |
| `copy(src_url, dst_url)` / `move(src_url, dst_url)` | Implement supported transfers; defaults raise `NotImplementedError`. |
| `prepare_copy(src_url, dst_url)` / `prepare_move(src_url, dst_url)` | Default wraps an implemented operation in a list containing a Task. |
| `prepare_delete(path)` | Default wraps implemented `delete` in a size-1 Task. |
| `prepare_trash(path)` | Override for correct trash tasks; see caveat. |

**Legacy caveat:** the current base `FileSystem.prepare_trash` checks that
`move_to_trash` is implemented but constructs a task calling `delete`. Providers
must override it to guarantee trash semantics; do not rely on this default to
protect recoverability. This reference describes the implementation and does
not silently change that behavior.

### Caching and Metadata

`@fman.fs.cached` wraps a provider method of shape `method(self, path)`. Results
are cached by path and method name. No automatic expiry is promised. Providers
expose `self.cache` with `put(path, attr, value)`, `get(path, attr)`,
`query(path, attr, compute_value)`, and `clear(path)`; missing cache entries raise
`KeyError` on get, and `clear('')` clears the cache. Avoid direct dependence on
its implementation class.

Custom metadata methods can be consumed through `query(url, method_name)`. Agree
on method names and value types with your columns; there is no universal promise
that every filesystem supports a method such as `size`.

### Columns

Subclass `fman.fs.Column` and expose the class in your package namespace.

| Member | Contract |
| --- | --- |
| `get_str(url)` | Required display string for an entry. |
| `get_sort_value(url, is_ascending)` | Comparable sort value; default is `get_str(url).lower()`. The host reverses order for descending sorts, so normally do not reverse it yourself. |
| `display_name` | Property used for the heading; defaults to the class name. |

The host identifier is `module.ClassName`; providers return these identifiers
from `get_default_columns`. `get_qualified_name()` exists for host registration
and is marked internal-use in the source. Columns should return consistent,
comparable types and keep display/sort work bounded; use provider metadata/cache
rather than manipulating Qt models.

## URL Helpers

Import from `fman.url`. Filesystem APIs consume application URLs, not native
Windows paths. These URLs are deliberately **not percent-encoded**: a space
stays a space. Do not substitute URI encoders for these helpers.

| Function | Contract |
| --- | --- |
| `splitscheme(url)` | Return `(scheme, path)`; scheme includes `://`. Raise `ValueError` if the separator is absent. |
| `as_url(local_file_path, scheme='file://')` | Convert native separators to forward slashes and prepend the scheme. Does not resolve a relative path to an absolute path. |
| `as_human_readable(url)` | Render `file://` paths in native form; on Windows a bare drive gets a trailing backslash. Other schemes remain unchanged. |
| `dirname(url)` | Return the parent URL, preserving the scheme. |
| `basename(url)` | Return the final path component. |
| `join(url, *paths)` | Append nonempty slash-separated path pieces while retaining the scheme; not native `os.path.join` semantics. |
| `relpath(dst, src)` | Return a POSIX-style relative path from `src` to `dst`; different schemes raise `ValueError`. |
| `normalize(url)` | Normalize the path with the host's path rules, preserving the scheme. This is lexical normalization, not an existence or identity check. |

```python
from fman.url import as_url, as_human_readable, join

folder = as_url(r'C:\Work')
file_url = join(folder, 'notes.txt')
display_path = as_human_readable(file_url)
```

## Clipboard

Import `clipboard` from `fman`, or import `fman.clipboard`. These helpers dispatch
synchronously to the UI thread. An application instance must already exist.

| Function | Contract |
| --- | --- |
| `clear()` | Clear clipboard contents. |
| `set_text(text)` | Store text; also updates the PRIMARY selection on platforms supporting it. |
| `get_text()` | Return clipboard text. |
| `copy_files(file_urls)` | Store application file URLs with copy metadata. Existing clipboard text is preserved. |
| `cut_files(file_urls)` | Store URLs with cut metadata. Supported by the Windows implementation; unsupported platforms can raise `NotImplementedError`. |
| `get_files()` | Return decoded application URLs; skip clipboard entries that cannot be converted. |
| `files_were_cut()` | Report whether the clipboard's file metadata denotes a cut operation. |

Clipboard functions do not themselves copy, move, delete, or paste files.

## UI Extension

Import from `fman.ui`. The complete explicit export list is:

```python
ListItem, QuickList, Panel, IconButton, TextButton, DropDown, JsonSettings,
UiController, UiOwner, Resource, settings_resource, matchers,
ToolWindow, PaneToolWindow, NavigationHandle, navigate, OutputTextBox
```

This is an additive **provisional** API, not upstream fman 1.7.5. Public names
do not imply permission to change host widget parenting, lifetime or internal
model state arbitrarily. Standard Qt layout/control APIs are currently necessary
for composition, but a future constrained facade may replace them.

### UiController

Subclass `UiController` and expose the subclass in the plug-in's root package.
Use its class methods rather than constructing a controller instance:

| Member | Contract |
| --- | --- |
| `owner` | Loader-assigned `UiOwner` for this class/load generation; initially `None`. |
| `require_owner()` | Return the active owner or raise `RuntimeError` before UI construction. |
| `show(pane, query='')` | Synchronously dispatch construction/reuse to the UI thread and return the hosted window. |
| `build(window, pane)` | Required classmethod and canonical construction hook. Compose controls and bind short callbacks; do not perform I/O here. |
| `window_type` | Optional existing hook for a host-window class; `None` selects `PaneToolWindow`. Ordinary plug-ins should keep the generic host and plain domain objects rather than subclassing a Qt window. |

`show` reuses one alive window per controller/pane. It validates the loader owner,
constructs on the UI thread, calls `build`, shows/raises the host, invokes its
query-seeding hook, and focuses `focus_widget`. A build exception closes the
partially built host and is propagated. Reopening without a query preserves an
existing query; a nonempty supplied query replaces it for a QuickList focus widget.

Do not assign `owner` in production plug-ins. Explicit `UiOwner()` instances are
for tests or deliberately managed tools. `show` is a synchronous UI dispatch;
never hold a worker/model lock needed by UI code while calling it.

### UiOwner

| Member | Contract |
| --- | --- |
| `UiOwner()` | Create an active owner. |
| `active` | Current lifetime flag; inspect rather than modifying directly. |
| `attach(dispose)` | Register a disposal callable; return `False` if already inactive, otherwise `True`. |
| `detach(dispose)` | Remove a callable if registered. |
| `invalidate()` | Mark inactive and invoke registered disposal callbacks outside the owner's lock. |

Invalidation can come from a worker. Custom disposal callables must not assume
they run on Qt; the built-in window invalidation safely queues closure. No new
work should start once the owner is inactive. This lifetime guard is not forced
termination of Python threads or OS I/O.

### ToolWindow and PaneToolWindow

`ToolWindow(parent, owner)` is the low-level Qt tool-window class;
`PaneToolWindow(pane, owner)` adds invoking-pane ownership, theme and docking.
Both require an active owner and UI-thread construction. Ordinary plug-ins
receive a `PaneToolWindow` in `UiController.build` instead of constructing either.

| Attribute | Meaning |
| --- | --- |
| `owner` | Session owner. |
| `alive` | Thread-safe Event; `alive.is_set()` is a cooperative lifetime check. |
| `busy` | Host operation/prompt busy state. |
| `focus_widget` | Assign the primary control, normally QuickList, for focus and query seeding. |
| `prompt` | Current prompt object or `None`; Qt-specific, not a portable dialog handle. Prefer public prompt methods. |
| `pane` | Invoking public pane, on PaneToolWindow. |
| `item_css` | Host theme data passed to `QuickList(css=...)`, on PaneToolWindow. Treat it as host-owned. |
| `bottom_panel` | Currently mounted Panel or `None`, on PaneToolWindow; use `set_panel`, do not assign it directly. This attribute is not the removed BottomPanel class alias. |

| Method/signal | Contract |
| --- | --- |
| `set_panel(panel)` | PaneToolWindow: mount one Panel across the main window above the status bar, with host-owned close control. `None` removes this session's panel without closing the tool. Reject a closed/inactive session. |
| `close()` | UI-thread session dismissal; closes paired surfaces and prompts and emits disposal. |
| `invalidate()` | Clear lifetime immediately and queue closure; safe for owner invalidation from workers. |
| `post(callback, *args)` | Queue a short callback to Qt; discard delivery if session/owner is no longer active. |
| `work(operation, completed)` | Start bounded worker work and return whether it was admitted; details below. |
| `set_busy(busy)` | Set host busy state and emit `busy_changed`; update through this method, not direct field assignment. |
| `on_shown(query)` | Host hook for query seeding and shown notification. Normally connect `shown` instead of overriding. |
| `shown(query)` | Qt signal after query seeding on show/reuse. |
| `busy_changed(busy)` | Qt signal when `set_busy` is called. |
| `disposed()` | Once-only Qt signal for session disposal; release bindings/subscriptions here. |

Internal transport signals (`delivered`, `close_requested`) and Qt event-handler
overrides are implementation details, not plug-in command channels. Inherited
Qt widget APIs are available, but are outside the stable host-service contract.

Dock ownership is **one session per main window**, not one per controller.
Mounting another session's panel closes the previous docked session, even when
it belongs to a different pane. Different main windows are independent.
QuickList stays in its frameless tool window while Panel is docked; Tab/Shift+Tab
bridge both surfaces. The dock's close icon and Escape end the UI session, not
the plug-in package. Prompts consume Escape first. Pane destruction and owner
invalidation close the hosted session. Do not reparent these surfaces yourself.

#### Background Work

`window.work(operation, completed)` runs a zero-argument callable off Qt and
delivers `completed(result)` on Qt. It sets busy state and uses a generation guard
to reject stale completion. Operation exceptions become host alerts rather than
being delivered as successful results.

There are two shared on-demand worker slots across UI work, navigation and
settings bindings, with no pending work queue or idle worker pool. A busy,
closed or inactive session returns `False`; global saturation returns `False`
and displays an alert. Call from Qt. Workers must use captured plain data and
must not read/write widgets. Already-running work may continue after close, but
late results are discarded. Check `alive.is_set()` cooperatively where useful.

#### Hosted Prompts

These methods are nonblocking and UI-thread-only. They create window-modal,
session-owned prompts, set the host busy, and guard callbacks by session lifetime.
Do not stack multiple prompts or call them as worker-thread UI shortcuts.

| Method | Contract |
| --- | --- |
| `alert(text)` | Show a message. No result callback. |
| `confirm(title, records, hidden, footer, accepted)` | `records` is a sized, sliceable sequence of `(name, path)` strings. Show total/hidden counts and at most ten records, truncating displayed names/paths; default No. Call `accepted()` only for Yes. |
| `rename_prompt(label, name, accepted)` | Prompt with initial text; call `accepted(new_text)` only on acceptance. Blank-name validation belongs to the caller. |

Capture operation targets before prompting; never reread mutable selection in
the acceptance callback to choose different targets. The bounded preview does
not reduce the full operation target set. Favorites deliberately bypasses
confirmation for bookmark deletion; the shared `confirm` API is unchanged.

### ListItem and QuickList

```python
ListItem(id, title, hint='', title_matches=(), hint_matches=())
QuickList(parent=None, matcher=None, css=None, preserve_sort=False, fuzzy=False)
```

`ListItem` is a frozen dataclass. Supply unique stable string IDs and string
title/hint fields; these caller requirements are not a comprehensive runtime
schema validator. Match tuples contain Python character positions, not UTF-16
offsets. The renderer maps them for Qt, including non-BMP text.

QuickList is an embeddable widget, not a dialog. It supplies no operation buttons,
window close controls or filesystem behavior.

| Member | Contract |
| --- | --- |
| `set_items(items)` | Materialize ListItems; prune selections whose IDs disappeared and refresh the projection. |
| `refresh()` | Rebuild filtered/sorted view, restoring current/selection by ID where possible. |
| `items` | Full input tuple. Replace through `set_items`. |
| `current_id` / `current_item` | Highlighted visible ID/record or `None`. |
| `selected_ids` | Selected ID set, including filtered-out records. If changing it programmatically, call `refresh()` to synchronize the view. |
| `selected_items` | Selected records in original input order, including hidden selections. |
| `hidden_selected_count` | Number of selected IDs not in the current visible projection. |
| `query` | Current Qt line edit: e.g. `setText`, `text`, `clear`, `setFocus`. Hidden if no matcher. |
| `view` | Underlying Qt item view for focus/accessibility; do not replace its model or selection rules. |
| `model` | Host-owned projection; do not mutate it instead of using `set_items`. |
| `matcher`, `preserve_sort` | Filtering policy and input-order preservation; changing either requires refresh. |
| `activated()` | No-argument signal for Enter/double-click activation; caller decides the action and whether to close. |
| `delete_requested()` | No-argument signal from list Delete; caller decides deletion policy. |
| `state_changed()` | No-argument signal for current, selection and refreshed projection state. |

Filtering is optional: `QuickList()` or `QuickList(fuzzy=False)` without a custom
matcher hides the filter and focuses the list. `fuzzy=True` chooses the built-in
subsequence matcher if no matcher was supplied; a supplied matcher enables the
filter regardless of the default fuzzy flag. Empty queries bypass matching.
Both title and hint are matched with Unicode casefolding and original-position
mapping. With `preserve_sort=True`, filtering retains input order. Otherwise
matches are ordered by title preference, tighter match span and earlier position.

A matcher has shape `matcher(text, query) -> positions | None`: return `None`
for no match, or valid matched character positions. It receives casefolded text
and query from QuickList. For a nonempty query, successful matches used in default
ranking must contain positions. Matchers run on Qt and must be fast and pure.

Interaction contract:

- Current highlight and multi-selection are independent; plain left-click moves
  current without selecting or activating. Right-click/Ctrl-click toggle rows;
  Shift-click toggles a range. Right-clicking empty space leaves selection alone.
- Space toggles current; Insert toggles then advances. Shift navigation follows
  file-pane toggling semantics; Ctrl+A selects visible rows.
- Up/Down and Page Up/Down in the filter transfer focus to the list and navigate.
  Subsequent Space toggles selection. Deliberately refocusing the filter restores
  text editing, including spaces and Delete.
- Filtering retains hidden selections and displays their count. Empty/no-match
  projections have no current item. Consumers must decide whether actions apply
  to current, selected, hidden-selected, or fallback targets.

### Panel and Controls

`Panel(parent=None)` provides a themed horizontal layout.
`add(widget, stretch=None)` adds and returns the widget; default stretch is 1
for TextButton and 0 otherwise. `add_stretch()` inserts expanding space.
Use `window.set_panel(panel)` to mount it; adding it to a list layout does not
create the host dock. `window.set_panel(None)` removes the tool's own panel and
keeps the result window alive. Detached controls are disposed by the host;
create a new Panel when mounting again. Unrelated docks are not removed.

| Component | Construction and behavior |
| --- | --- |
| `IconButton(icon, label, parent=None)` | Requires a non-null `QIcon` and accessible label; compact checkable boolean control, with label as tooltip. |
| `TextButton(text, parent=None, checkable=False, max_width=160)` | Action button by default; optional boolean toggle. Positive integer width cap in Qt logical pixels; label minimum width can exceed the cap to prevent clipping. |
| `DropDown(choices, label, parent=None)` | Nonempty sequence of `(title, value)` pairs. Values must be distinct typed JSON scalars: str, int, float or bool; `None` is not accepted. |

All three provide `accepts(value)`, `value()`, `set_value(value)`, and the Qt
signal `value_changed(value)`. Invalid values raise `ValueError` from set_value.
Only checkable TextButtons accept boolean settings. DropDown distinguishes values
by exact type as well as equality. Use normal button `clicked` signals for
commands; a clicked signal may supply a boolean argument.

### OutputTextBox

`OutputTextBox(text='', parent=None, *, title='')` displays selectable, read-only
plain text with a small top-left copy button and optional title beside it.
Construct and use it on the Qt thread, normally
inside `UiController.build`. Add it to the window layout and assign it to
`window.focus_widget` when it is the primary output surface.

- `set_title(title)` replaces the plain-text header; `title()` returns the full
  supplied title. Both require the Qt thread; the title must be a string.
  Long titles elide to fit and retain their full text in a tooltip. Titles are
  never included in the copied output. Existing positional text/parent calls work.
- `set_text(text)` replaces the complete string and resets selection/scroll;
  non-string values raise `TypeError`.
- `text()` returns the supplied string without display newline normalization.
- `copy_text()` copies that complete string regardless of selection. Empty or
  disabled output does not change the clipboard.
- `copied` is a no-argument Qt signal emitted once for each nonempty copy-all
  action. Connect it to caller-owned feedback; the widget starts no timer.
- Return or keypad Enter in the text invokes copy-all. The icon is also
  keyboard-accessible. Ctrl+C copies the selected text using normal Qt behavior;
  Ctrl+A selects all. Copy does not close the owning window.

Long lines wrap and tall output scrolls. HTML is literal text; editing, file I/O,
streaming, syntax highlighting, and persistence are not provided. The control
bundles its own theme-tinted SVG icon; callers do not access the private editor
or button. Both hash commands embed it beneath a file-path window heading, with
`Hash Algorithm: <Algorithm>` as its title. Calculate File Hash By selects the
algorithm through QuickSearch first; neither command mounts a Panel.

### JsonSettings

```python
JsonSettings(filename, parent, owner=None)
```

Use a plug-in-specific `.json` filename without slash/backslash, not a path.
Construct on Qt with an owning QObject parent, normally the Panel. Supply the
controller's owner for unload handling.

| Member | Contract |
| --- | --- |
| `bind(key, control, default)` | Bind a unique nonempty string key before load begins. Default must satisfy control.accepts. Initializes the control and disables it until loaded. |
| `load()` | Start asynchronous snapshot/subscription using the shared worker slots. No synchronous data-return contract. |
| `loaded` | Whether an initial revision has been received. |
| `busy` | Whether a load/save is in progress. |
| `filename` | Bound configuration filename. |
| `dispose()` | Stop accepting results and unsubscribe; safe for lifecycle cleanup. |
| `changed(values)` | Qt signal carrying a copy of the settings dictionary when applied, including rollback/error paths; not proof of a disk write. |
| `failed(message)` | Qt signal on validation, load/save or saturation errors. |
| `busy_changed(busy)` | Qt signal for binding busy state. |

Control changes save asynchronously under the shared resource lock. Unrelated
keys are retained, other bindings to the same resource receive committed changes,
and controls roll back to the last known values on failure. Invalid stored values
display the control default; loading does not silently rewrite them on disk.
Binding controls are disabled during load/save. A plain action button does not
save a setting. Dispose on session closure even if the parent will later be
destroyed. There is no polling or filesystem watcher for external JSON edits.

### Resource and settings_resource

`settings_resource(name)` returns the same host-owned `Resource` for a name across
plug-in reloads. Names are shared and must be chosen deliberately. `Resource()`
creates an independent coordinator, not a settings file or automatic persistence.

| Member | Contract |
| --- | --- |
| `lock` | Reentrant lock for snapshot/transaction serialization. |
| `revision` | In-memory revision counter; read consistently under the lock. Not persisted. |
| `subscribe(callback, snapshot)` | Under the lock, register `callback` and return `(revision, snapshot())`. |
| `unsubscribe(callback)` | Remove if registered. |
| `committed(snapshot)` | Increment revision under the lock and return a notification containing revision, snapshot and the captured subscriber set. Does not save JSON. |
| `publish(notification)` | Invoke captured subscribers as `callback(revision, snapshot)` in the publishing thread. No automatic Qt dispatch or exception isolation. |

Hold `resource.lock` through load/modify/save/committed, then publish **outside**
the lock. Publish only after a successful write. Share immutable snapshots, or
copy them, to avoid races. Subscribers should queue GUI delivery through the
host and guard lifetime: a captured notification can outlive unsubscription.
If snapshot creation raises during subscribe, clean up the subscription in your
failure/disposal path. Resource itself does not manage owner lifetime.

### Matchers

`from fman.ui import matchers` exposes the legacy matcher algorithms without
requiring an import from the Core plug-in.

| Function | Contract |
| --- | --- |
| `path_starts_with(path, query)` | Case-insensitive native-path prefix positions; strips trailing native separators from query. |
| `basename_starts_with(path, query)` | Case-insensitive native basename prefix, with positions relative to the whole path. |
| `contains_chars(text, query)` | In-order subsequence positions; case-sensitive when called directly. |
| `contains_substring(text, query)` | Contiguous substring positions; case-sensitive when called directly. |
| `contains_chars_after_separator(separator)` | Return a matcher that follows matching characters from separated-part starts, skipping the remainder of mismatching parts. |

Successful matchers return position lists; failures return `None`. The native-path
matchers are not URL parsers. QuickList adds its own casefolding/offset mapping;
direct callers must choose their own normalization policy.

### Tracked Navigation

```text
navigate(pane, url, on_done, *, window, check=None, timeout=30)
```

Call on Qt with an alive hosted window. Return value is a `NavigationHandle`:
`done` is a boolean property and `cancel()` requests thread-safe cancellation.
The exported `NavigationHandle(request)` constructor is for host-created
requests; plug-ins obtain handles from navigate rather than creating internal
NavigationRequest objects.

`check(url)`, when supplied, runs off Qt before dispatch; return normally to
allow navigation or raise to reject it. Existing command/location rewrite hooks
still apply. `on_done(outcome, message)` runs on Qt for a terminal outcome while
the session is alive: `success`, `failure`, or `superseded`. Close/unload suppresses
late callbacks. Do not start a second navigation while the host is busy.

Timeout must be positive and covers precheck, dispatch and waiting. Failures,
timeout, busy state and worker saturation are delivered through the outcome
path. The operation uses host busy state and the shared worker limit; a rejected
request must not clear a different operation's busy state. A separate bound
limits tracked model initialization that outlives cancellation.

Cancel/timeout does not interrupt blocked OS I/O or roll back an already-started
pane transition. A slow operation can therefore report failure while underlying
I/O is still finishing. Close can discard results, not guarantee external work
has stopped. Consumers decide whether success closes their UI and how to display
failure messages. Favorites additionally checks that targets are folders; the
generic API does not impose that consumer policy.

### Theme Integration

Supply `Theme.css` in the plug-in root, optionally with a platform variant.
Supported selector mappings include `*`, `th`, `.locationbar`, `.statusbar`,
`.statusbar-pane`, `.statusbar-pane[active="true"]`, `.quicksearch-query`,
`.quicksearch-item`, `.panel`, `.plugin-panel-dock`, and `.plugin-tool-window`.
Legacy `.bottom-panel` remains a CSS selector mapping even though the Python
BottomPanel alias was removed.

Quicksearch rendering also reads `.quicksearch-item-title`,
`.quicksearch-item-title-highlight`, `.quicksearch-item-hint`, and
`.quicksearch-item-description` properties for text styling. This is the host's
restricted CSS mapping, not a browser DOM/CSS engine. Unknown widget selectors
are not automatically exposed as theme APIs. Pass `window.item_css` to QuickList;
do not read private theme objects or add Favorites-specific host styles.

## Threading and Failure Handling

| Context | Safe contract |
| --- | --- |
| Ordinary command body | Worker execution through registry; perform bounded I/O and call public host services. |
| Listener notification | Worker thread; no Qt widget access. |
| Listener rewrite/visibility | Synchronous caller context; short, nonblocking and free of long I/O. |
| Quicksearch callbacks and QuickList matchers | UI thread; fast in-memory work only. |
| UiController.build and widget signals | UI thread; construct controls and queue operations. |
| ToolWindow.work operation / navigate check | Worker; immutable/captured plain data only. |
| ToolWindow.work completion / navigate outcome | Qt delivery guarded by session lifetime. |
| Resource.publish subscribers | Publisher's thread; marshal UI work explicitly through the host. |
| UiOwner disposal callbacks | Invalidating thread; use a safe host disposal operation. |

Public synchronous dispatch helpers can wait for Qt; never hold a lock that Qt
needs while calling them. Do not import internal thread-dispatch utilities.
Use `UiController.show` for construction and `window.post` for queued results.
Not every inherited Qt method checks thread affinity, so constructor guards do
not make arbitrary later calls safe.

Choose and document confirmation, failure and cancellation policy per operation.
No general filesystem API guarantees user confirmation or undo. Cooperatively
cancel long work, reject stale results, release subscriptions, and avoid work
when optional features are disabled. Do not treat command completion, a pane
path change, and successful model initialization as interchangeable events.

## Examples

### Minimal Pane Command

Put this class in your plug-in package's `__init__.py`. It registers as
`show_current_folder` without importing implementation modules.

```python
from fman import DirectoryPaneCommand, show_alert
from fman.url import as_human_readable


class ShowCurrentFolder(DirectoryPaneCommand):
  aliases = ('Show current folder',)

  def __call__(self):
    show_alert(as_human_readable(self.pane.get_path()))
```

### Legacy Picker

Prepare data in the command before opening the picker; filtering then stays
in-memory on Qt.

```python
from fman import DirectoryPaneCommand, QuicksearchItem, show_quicksearch
from fman.fs import iterdir
from fman.url import join


class PickChild(DirectoryPaneCommand):
  def __call__(self):
    folder = self.pane.get_path()
    names = tuple(iterdir(folder))

    def get_items(query):
      for name in names:
        if query.casefold() in name.casefold():
          yield QuicksearchItem(join(folder, name), title=name)

    result = show_quicksearch(get_items)
    if result is not None:
      query, selected_url = result
      if selected_url is not None:
        self.pane.place_cursor_at(selected_url)
```

### Hosted QuickList and Panel

This is the currently supported Qt-component API, not the future Qt-free facade.
The controller is discoverable from the package namespace; no owner assignment,
host subclass or private import is needed. QuickList supports selection but does
not assign application meaning to it; this example acts on the current item.

```python
from fman import DirectoryPaneCommand
from fman.ui import (
  DropDown, JsonSettings, ListItem, Panel, QuickList, TextButton, UiController
)
from PyQt5.QtWidgets import QVBoxLayout


class ExampleUI(UiController):
  @classmethod
  def build(cls, window, pane):
    rows = (ListItem('alpha', 'Alpha'), ListItem('beta', 'Beta'))
    view = QuickList(window, fuzzy=True, css=window.item_css,
             preserve_sort=True)
    window.focus_widget = view
    QVBoxLayout(window).addWidget(view)

    panel = Panel(window)
    order = panel.add(DropDown(
      (('Name ascending', 'ascending'), ('Name descending', 'descending')),
      'Order'
    ))
    panel.add_stretch()
    inspect = panel.add(TextButton('Inspect'))
    window.set_panel(panel)

    def project(*args):
      view.set_items(sorted(rows, key=lambda row: row.title,
                  reverse=order.value() == 'descending'))

    def inspect_current():
      if not window.busy and view.current_item is not None:
        window.alert(view.current_item.title)

    settings = JsonSettings('Example UI.json', panel, cls.owner)
    settings.bind('order', order, 'ascending')
    settings.changed.connect(project)
    settings.failed.connect(window.alert)
    window.disposed.connect(settings.dispose)
    order.value_changed.connect(project)
    inspect.clicked.connect(lambda checked=False: inspect_current())
    view.activated.connect(inspect_current)
    project()
    settings.load()


class ShowExample(DirectoryPaneCommand):
  def __call__(self, query=''):
    ExampleUI.show(self.pane, query)
```

For the complete reference consumer, see the
[Favorites plug-in](src/main/resources/base/Plugins/Favorites/favorites/ui.py)
and its [usage guide](src/main/resources/base/Plugins/Favorites/README.md).
Favorites adds its own store transactions, folder validation and direct bookmark
deletion; those policies are not implicit behavior of QuickList or Panel.

### Validation Guidance

Test pure plug-in logic independently of Qt, then exercise actual controls,
signals, owner invalidation and worker completion with the shared
[Qt integration harness](src/integrationtest/python/fman_integrationtest/test_qt.py).
Offscreen Qt warnings about raise/lower/size hints do not prove native focus or
window-manager behavior works; use native source smoke for those behaviors.
Changes to dependencies, dynamic imports or assets also need packaging validation.
Run focused checks by default; the full `python build.py test` suite is a separate
explicit action. This document itself does not claim that an untested packaged
plug-in is supported merely because its source imports work.