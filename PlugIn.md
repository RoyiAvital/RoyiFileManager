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
| [fman.fs](src/main/python/fman/fs.py) | Filesystem operations, filesystem providers, columns | Operation signatures retained; snapshot provider/column migration required |
| [fman.listing](src/main/python/fman/listing.py) | Immutable display snapshots | New provider contract |
| [fman.url](src/main/python/fman/url.py) | Application URL manipulation | Legacy API |
| [fman.clipboard](src/main/python/fman/clipboard.py) | Text and file clipboard operations | Legacy API |
| [fman.ui](src/main/python/fman/ui.py) | QuickList, QuickTable, QuickBoard, Panel services, hosting, navigation | Provisional RoyiFileManager extension |

The upstream fman 1.7.5 listing/column contracts are not preserved. Implement
the snapshot methods below; old per-row display methods are not an adapter.
`APP_VERSION` reports the RoyiFileManager product version; it is not a plug-in
API compatibility or feature-negotiation guarantee. Consult
[CHANGELOG.md](CHANGELOG.md) for extension changes and migration notes.

- Do not import `fman.impl`, access private host fields such as `_widget` or
  `_theme`, or depend on another bundled plug-in's internals as though they were
  host APIs. A plug-in may organize its own implementation into private modules.
- Bundled-host exception: Everything uses `PluginService`, `format_size` and
  `run_in_main_thread` from `fman.impl`, plus the bundled Favorites parser.
  These are reviewed, version-coupled dependencies, not public plug-in APIs.
  They require matching host releases and loader/lifecycle tests; independently
  distributed plug-ins must not rely on this exception. See the
  [Everything design](Done/EverythingPlugIn.md#design).
- Use explicit imports. Imported implementation dependencies visible in a module
  are not additional public exports. Pane/window objects are supplied by the
  host; their constructors are not plug-in construction APIs.
- `fman.ui` still exposes Qt-derived hosting (`ToolWindow`, `PaneToolWindow`,
  `OutputTextBox`). Their documented methods are the intended integration
  surface, but inherited Qt methods remain technically accessible. This is not
  a sandbox. Lists, tables and Panels are Qt-free services; prefer them.
- Raw parent widgets and Qt closure signals are not exposed through the general
  `Window`/`DirectoryPane` API. Use `pane.on_closed(callback)` and UI hosting.
- The unshipped `BottomPanel` and public `set_bottom_panel` aliases were removed.
  Dock controls with `show_panel`.
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

The cursor override applies only on the command's thread. Capture
`pane.get_file_under_cursor()` there before passing the URL to a Qt-thread helper
or another worker; reading it on that other thread returns the ordinary cursor.

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

| Method                                                             | Contract                                                                                                                                                                                                                                                                          |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_commands()`                                                   | Registered pane command names.                                                                                                                                                                                                                                                    |
| `run_command(name, args=None)`                                     | Run a pane command, honoring command rewrite listeners.                                                                                                                                                                                                                           |
| `get_command_aliases(command_name)`                                | Aliases for a registered pane command.                                                                                                                                                                                                                                            |
| `is_command_visible(command_name)`                                 | Evaluate visibility in this pane's context.                                                                                                                                                                                                                                       |
| `get_selected_files()`                                             | Selected file URLs; current highlight is separate.                                                                                                                                                                                                                                |
| `get_file_under_cursor()`                                          | Current file URL, or no current value.                                                                                                                                                                                                                                            |
| `get_path()`                                                       | Current directory URL, not a native path.                                                                                                                                                                                                                                         |
| `get_listing()`                                                    | Current immutable `fman.listing.Listing`, or `None` before commit. Retaining it retains that snapshot's memory.                                                                                                                                                                   |
| `find_in_listing(search, query='', metadata=False, accepted=None)` | Start in-pane Find; return false if no snapshot is ready. `search(listing, query, check_canceled)` runs on a worker and returns `(entry_indices, highlights_by_entry)` with UTF-16 highlight offsets. `accepted(url)` runs on Qt after accepting and restoring normal projection. |
| `set_path(dir_url, callback=None, onerror=host_default)`           | Request a directory change, honoring location rewrite listeners. `callback()` signals initialization; do not treat it as a complete navigation outcome.                                                                                                                           |
| `reload(on_done=None)`                                             | Reload the pane; an optional no-argument callback runs on Qt after a fresh successful scan and projection settle. Failed scans leave it pending for a successful retry; navigation/closure cancels it.                                                                            |
| `edit_name(file_url, selection_start=0, selection_end=None)`       | Start inline name editing and select the specified text range.                                                                                                                                                                                                                    |
| `select_all()` / `clear_selection()`                               | Select all visible pane entries or clear selection.                                                                                                                                                                                                                               |
| `toggle_selection(file_url)`                                       | Toggle one entry.                                                                                                                                                                                                                                                                 |
| `select(file_urls)` / `deselect(file_urls)`                        | Update selection for URLs; missing-entry errors are ignored by these wrappers.                                                                                                                                                                                                    |
| `place_cursor_at(file_url)`                                        | Move the current highlight to a URL.                                                                                                                                                                                                                                              |
| `focus()`                                                          | Focus this pane.                                                                                                                                                                                                                                                                  |
| `get_columns()`                                                    | List of current qualified column-name strings.                                                                                                                                                                                                                                    |
| `set_sort_column(column, ascending=True)`                          | Set a displayed column by qualified name and direction; a missing column raises `ValueError`.                                                                                                                                                                                     |
| `get_sort_column()`                                                | Return `(qualified_column_name, ascending_bool)`.                                                                                                                                                                                                                                 |
| `on_path_changed(callback)`                                        | RoyiFileManager addition: register a no-argument path-change callback on the UI thread; return an idempotent unsubscribe function.                                                                                                                                                |
| `on_closed(callback)`                                              | RoyiFileManager addition: register no-argument pane-destruction callback; return an idempotent unsubscribe function.                                                                                                                                                              |

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

`on_path_changed` has the same registration/unsubscription threading contract.
It does not call back on registration; read `get_path()` for the initial URL.
Callbacks must be fast and may read the current path or update plain UI handles.
Unsubscribe when the owning tool closes. No polling or new worker is created.

### Window

| Method | Contract |
| --- | --- |
| `get_panes()` | Return this window's pane handles. Do not mutate the host-owned list. |
| `add_pane()` | Add and return a host-managed directory pane. |
| `minimize()` | Minimize the window. |
| `reset_geometry(width, height)` | Reset window geometry using the supplied dimensions. |
| `set_extended_status_bar(settings)` | RoyiFileManager host entry point for extended status-bar settings; use the settings contract documented below. |

The removed methods `tool_parent`, `get_quicklist_item_css`, `set_panel`,
`set_bottom_panel`, and `remove_bottom_panel` are not general Window APIs. Dock
plug-in controls with `show_panel`.

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
| `load_json(name, default=None, save_on_quit=False, *, preserve_on_reload=False)` | Load merged configuration by filename. Return `default` when no value exists. Can return a shared cached mutable object. |
| `save_json(name, value=None)` | Persist a differential override; omitted/`None` value uses the cached value. Save completes before replacing the cache. |

Names are shared across loaded plug-ins, not automatically package-namespaced.
Use distinctive filenames. Layers include generic and platform-specific files;
dictionaries merge recursively, with later values winning unless both values are
dictionaries. Nested lists replace earlier lists; top-level lists are prepended
to earlier lists. Mismatched top-level JSON types raise `ValueError`; nested
values can change type. An empty dictionary does not clear an inherited
dictionary: override individual entries instead.

User overrides are normally written to
`UserSettings/Plugins/User/Settings/<Name> (Windows).json`. Saves use a temporary
file followed by atomic replacement. Only changed keys are written, recursively
omitting values equal to defaults. Removing inherited dictionary keys at any
depth raises `ValueError`; keys present only in the user override can be removed.
Inherited top-level list suffixes cannot be arbitrarily edited through
differential saving; such requests may raise `ValueError`.

Copy loaded data before editing when save failure must leave the cache intact.
Use a shared `settings_resource(name).lock` for multi-step read/modify/write
transactions shared by commands and UI. `save_on_quit=True` schedules cached
values for persistence at shutdown; explicit saving is preferable for completed
user actions.

`preserve_on_reload=True` is an opt-in RoyiFileManager extension for session-owned
data such as command history. It retains both the cached object's identity and
contents across plug-in loads/unloads, even if another settings reload fails.
It does not save data; combine it with `save_on_quit=True` for exit-time persistence.
Once retained, file edits and new configuration layers are not read for that name
until the next process starts. Explicit `save_json` can still replace its cached
value. Missing values without a default and failed loads are not retained.
Leave this option off for ordinary settings that should refresh on plug-in reload.

### Constants

| Name | Meaning |
| --- | --- |
| `PLATFORM` | Always `'Windows'`; generic and `(Windows)` configuration layers are loaded. |
| `APP_VERSION` | RoyiFileManager product version from the bundled build settings. |
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

- `mode`: `'disabled'` or `'single'` (active pane).
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

### No-Overwrite Rename

`fman.fs.rename_no_replace(source_url, destination_url)` changes a basename
within the same provider and parent. It never falls back to replacing Move,
merge or copy/delete. Windows local storage implements it; other providers
currently raise `NotImplementedError`. Cross-provider/parent requests raise
`io.UnsupportedOperation` before mutation. Existing `move`/`prepare_move` behavior
is unchanged. Ordinary Rename uses this operation where supported and retains
the existing route for providers that have not implemented it, such as archives.
Local rename URLs must use forward slashes; backslashes are rejected with
`io.UnsupportedOperation` before filesystem access. Convert native paths with
`fman.url.as_url`.

Local Rename rejects symbolic links, junctions and files with multiple hard links
with `io.UnsupportedOperation`; ordinary Rename shows the refusal as an alert.
Sparse files and cloud placeholders remain supported. Detection uses Windows'
name-surrogate tag, not a blanket rejection of reparse points.

The immutable public `RenameResult(source_url, destination_url, changed,
notification_warnings=())` confirms the outcome. `changed=False` means an existing
source and identical destination spelling. An occupied destination raises before
commit, including one introduced after a precheck; Windows same-entry case-only
rename remains supported. An existing 8.3 alias of the source is refused, not
reported as a successful rename. Post-commit notification failures return bounded warning
strings (at most 16, each at most 512 characters), not an ambiguous mutation error.
Unformattable exceptions produce a fixed warning; later listeners still run.
Do not retry a committed rename because its view refresh failed.

Providers implement `FileSystem.rename_no_replace` and return `RenameResult`
without emitting the normal removed/added events themselves: the host updates
caches and dispatches those notifications independently, isolating listener errors.
The base method raises `NotImplementedError`; a strict API call never uses the
ordinary command's legacy-provider fallback.

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
| `scan(path, check_canceled)` | Required for pane browsing; return a complete `fman.listing.Listing` whose location is `scheme + path`. Runs off Qt; call cancellation between bounded units of work and close resources on failure/cancellation. |
| `iterdir(path)` | Yield child names for operation/traversal clients. Panes do not call it or automatically adapt it to `scan`. |
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

### Snapshot Migration

Return `Listing.create(location, names, ...)`. Names are unique immediate child
keys without separators, NUL, `.` or `..`; they form action URLs. `labels` can
provide separate display strings. All columns are detached into immutable tuples.
This is a Windows-first contract: both `/` and `\` are rejected, including a
literal backslash in an otherwise valid POSIX filename.
Use `is_dir`, `sizes`, `mtimes_ns`, own `attributes`, `created_ns`, and optional
`extra=((column_name, scalar_values), ...)`. Missing size/time is `None`, not zero.
Provider extras allow only `None`, strings, numbers, booleans and bytes.

Stable identity is optional: `identities` contains exactly 16 bytes per entry,
and `scope` is `(volume_id, directory_id_bytes16)`. Unknown IDs are zero. Only
verified nonzero identity, scope and creation-time matches preserve marks across
refresh. Ambiguous renamed hardlinks and replacements do not inherit marks;
unknown-identity providers still preserve state across filter/sort of the same
snapshot. Never invent identity from names or use display identity to authorize
file operations.

Providers own acquisition strategy: native directory records, archive indexes,
process records or network enumeration all feed the same model. No Qt objects
belong in a listing. Scans may overlap; shared provider state must be protected.
Raise on failure instead of returning partial or stale results.

Custom pane filters must expose `snapshot_filter()` on the callable or its bound
owner. The host calls it on Qt; return a worker-safe predicate
`predicate(listing, index)` capturing plain immutable state, not widgets.
The predicate must not perform filesystem I/O. Old URL-only filters are rejected.
It may also expose `filter_indices(listing, order, check_canceled)`, returning
the same accepted indices in their input order. Check cancellation between
bounded chunks. Predicates must be side-effect-free; evaluation order and call
counts are not guaranteed. The bundled hidden filter uses this batch path.

### Caching and Metadata

`@fman.fs.cached` wraps a provider method of shape `method(self, path)`. Results
are cached by path and method name. No automatic expiry is promised. Providers
expose `self.cache` with `put(path, attr, value)`, `get(path, attr)`,
`query(path, attr, compute_value)`, and `clear(path)`; missing cache entries raise
`KeyError` on get, and `clear('')` clears the cache. Avoid direct dependence on
its implementation class.

Custom metadata methods can be consumed through `query(url, method_name)`. Agree
on method names and value types with operation clients; there is no universal
promise that every filesystem supports a method such as `size`. Enumeration
snapshots never populate authoritative operation caches. Operation clients still
need fresh identity/permission checks before acting.

### Columns

Subclass `fman.fs.Column` and expose the class in your package namespace.

| Member | Contract |
| --- | --- |
| `text(listing, index)` | Required display string; called lazily on Qt. Read snapshot/configuration data only; no I/O or widget mutation. |
| `keys(listing, ascending)` | Required sequence of one comparable key per entry; computed on a worker. The host reverses order for descending sorts. Direction-dependent grouping must account for that reversal. |
| `keys_depend_on_external_data` | Defaults to `True`. Set `False` only when keys depend solely on the snapshot and direction; external metadata delivery then repaints without re-sorting or resetting the pane. Bundled Name/Modified opt out; Size remains dependent. |
| `display_name` | Property used for the heading; defaults to the class name. |

The host identifier is `module.ClassName`; providers return these identifiers
from `get_default_columns`. `get_qualified_name()` exists for host registration
and is marked internal-use in the source. Columns should return consistent,
comparable types and keep display/sort work bounded. Do not manipulate Qt models
or query per-path metadata for display.

Legacy `get_str` and `get_sort_value` methods have been removed from the base
class, wrappers and bundled columns. Migrate display logic to `text(listing, index)`
and sorting to `keys(listing, ascending)`. Acquire metadata in the filesystem's
`scan`, not in the column. Remove calls to legacy `super()`/wrapper methods and
filesystem arguments to bundled `Name`, `Size` and `Modified` constructors.
There is no compatibility shim. Extra legacy methods in a plug-in are harmless
only when it already implements the snapshot API and does not call removed methods.

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
| `set_text(text)` | Store clipboard text. |
| `get_text()` | Return clipboard text. |
| `copy_files(file_urls)` | Store application file URLs with copy metadata. Existing clipboard text is preserved. |
| `cut_files(file_urls)` | Store URLs with Windows/Qt cut metadata, preserving existing clipboard text. |
| `get_files()` | Return decoded application URLs; skip clipboard entries that cannot be converted. |
| `files_were_cut()` | Report whether the clipboard's file metadata denotes a cut operation. |

Clipboard functions do not themselves copy, move, delete, or paste files.

## UI Extension

Import from `fman.ui`. The complete explicit export list is:

```python
ListItem, UiController, UiOwner, Resource, settings_resource, matchers,
ToolWindow, PaneToolWindow, NavigationHandle, navigate, OutputTextBox,
QuickTableRow, QuickTableColumn, TextField, Toggle, Choice, Select, DateField, IntegerField, Separator, Label, Action,
PanelHandle, show_quick_table, show_quick_board, show_panel, show_quick_list, QuickListHandle, QuickListState
```

This is an additive **provisional** API, not upstream fman 1.7.5. Public names
do not imply permission to change host widget parenting, lifetime or internal
model state arbitrarily. QuickList, QuickTable, QuickBoard and Panel are plain services;
plug-ins need no Qt import for them. The widget exports `QuickList`, `Panel`,
`IconButton`, `TextButton`, `DropDown` and `JsonSettings` were removed: use
`show_quick_list`, `show_panel` controls and `load_json`/`save_json` instead.

### Qt-Free QuickBoard

```python
show_quick_board(*, columns, get_rows, text='', title='', summary='')
get_rows(text, mapping) -> (rows, caller_status)
text, accepted, mapping = show_quick_board(...)
```

QuickBoard helps compose one string. `get_rows(text, mapping)` supplies read-only feedback
using the same `QuickTableColumn` and `QuickTableRow` records described below.
Every callback must return a two-item tuple: an iterable of rows and a status
string or `None`. Rows-only returns are rejected as preview errors; migrate
`return rows` to `return rows, None` when no status is needed.
The columns stay fixed; each successful callback replaces the whole preview.
There is no public handle, pane, Go To or operation API. A source-to-view mapping
lets the caller interpret the exact preview it approved.
The built-in cell menu copies the **displayed text**, including path columns;
`targets` does not enable navigation or change Copy in a QuickBoard.

```python
from fman.ui import QuickTableColumn, QuickTableRow, show_quick_board

def compose_prefix(names):
  names = tuple(names)
  return show_quick_board(
    columns=(QuickTableColumn('Original'),
      QuickTableColumn('Preview', sortable=False, filterable=False)),
    get_rows=lambda prefix, mapping: (
      tuple(QuickTableRow((name, prefix + name)) for name in names), None),
    title='Compose prefix', summary=f'{len(names)} captured names',
  )
```

No owner or `UiController` subclass is required. The host owns the dialog;
unloading the calling plug-in does not automatically close it. Omit the former
`owner` argument when updating an earlier QuickBoard caller.
The modal call blocks its worker caller until close; a Qt
caller uses a local event loop. Enter returns `(text, True, mapping)`, including for an
empty preview. Escape/window close returns `(text, False, None)` with the exact draft,
unlike `show_prompt`; spaces are never trimmed. Enter during work is queued for
that exact input revision and waits for its successful, settled preview. Another
text/view edit, error or disposal clears the request. Filters and sorting persist
between previews; the caller decides whether hidden rows are excluded from its
operation. Clear All Filters never edits the string.

The window is frameless, with `title` in a draggable header, optional `summary`
below it, the composition field and table, and one footer: host counts/errors on
the left and optional caller status on the right. Return `(rows, None)` for no
caller message. A status string is plain text (at most 512 characters,
no NUL), elided with a tooltip; it is never interpreted as validity or permission.
The message publishes with its matching rows and is hidden while newer work is
pending, so stale advice cannot remain alongside a different revision.
The field starts focused. Up/Down/Page Up/Page Down focus the table; Tab and
Shift+Tab move between them, Ctrl+F focuses/selects the field, and Alt+Down opens
the column filter. A filter menu handles its own Enter/Escape first.
Editing the composition or publishing a new preview closes any open column
filter editor and discards its unapplied draft; already-applied filters survive.

The callback, iteration, numeric `format` callbacks and row validation run on a
dedicated worker, initially after showing the window. Text edits restart a 100 ms
trailing debounce; Enter flushes it and waits for the mapped preview. View changes
regenerate immediately. Escape cancels without waiting for a blocked callback.
They must not access Qt or mutate files/shared state. Calls are serial per board,
with at most one replaceable pending input. The host checks cancellation before
and after each formatter, around the handler, and during validation, but cannot interrupt a blocked callback:
bound its work and apply I/O timeouts. Date context is captured on Qt once.
Validated, immutable snapshots reach Qt; formatters are not rerun there.

The host retains old rows and shows `Updating...` in the counts footer while
working. Failed previews label retained rows `Stale preview`, including after
sorting or filtering. Any caller exception, including `Task.Canceled` and other
`BaseException` subclasses, is a failed preview: `ValueError` is inline feedback;
other exceptions also open a dialog-owned alert. Internal worker cancellation
silently discards stale work instead. Failed or stale previews cannot approve
the string. Closing the board or main window cancels pending work and suppresses
late results/alerts without joining workers on Qt. A running callback may finish,
but cancellation prevents subsequent formatters in its row from starting.
Nothing persists or runs before a board is opened.

Limits: 1-16 columns, 25,000 rows and the shared 16 MiB preview text/typed-value
budget. Input is one line, at most 4,096 UTF-16 code units (matching Qt's field);
title/summary are at most 512/2,048 characters. NUL is forbidden in all three;
initial CR/LF is rejected. Invalid arguments fail before UI/worker creation.
Qt may retain CR/LF pasted after opening: these drafts show an error and cannot
be accepted, but Escape returns them exactly. A cancelled draft therefore may
not be valid as a new `text` argument without correction.
Two process-wide leases cover open boards and closed boards whose workers are
still finishing. A third caller receives an alert and `(initial_text, False, None)`
without invoking its callback; Panel/navigation worker capacity is independent.

The caller owns grammar, sampling, freshness, validation and any subsequent
operation. Accepted text is not an operation plan or proof that files are safe
to mutate. This API requires a host containing QuickBoard; copying a consumer
plug-in into an older portable release does not add the host service.

#### Row Mapping

`mapping` is an immutable `tuple[int | None, ...]` indexed by generator row
position. Each integer is that row's zero-based visible position; `None` means
filtered out. For generated rows `[A, B, C, D]` displayed as `[C, A]`, the map
is `(1, None, 0, None)`. Non-None positions are unique and consecutive. It is a
single source-to-view map, not a second unfiltered-order map or a set of row IDs.

The initial callback receives `mapping=None` to establish the fixed source snapshot.
Once projected, the callback receives its mapping. Later text edits reuse the
current map; sorting/filtering changes regenerate the mapped preview. Every call
retains row count and generator order, including hidden rows, and keeps all
sortable/filterable cells and typed values fixed for the dialog lifetime.
Cells computed from view positions must use `sortable=False, filterable=False`,
preventing their values from feeding back into the projection that defines them.
Observable source changes produce a preview error rather than a bootstrap loop.
Mappings use input positions, never Python object identity.

Enter waits for matching text, mapping and completed preview. A later text,
sort or filter edit clears an earlier pending acceptance request. Successful
return is `(text, True, mapping)` for that exact snapshot; cancellation returns
the current draft as `(text, False, None)`, without waiting for pending work.
An empty visible set is represented by all-None entries (or `()` for zero rows),
not by `mapping=None`.

QuickBoard only projects rows and exchanges plain data. The caller decides
whether hidden rows are operation exclusions and owns all filename generation,
validation and collision checks. In Batch File Renamer, only visible rows are
renamed; hidden entries still occupy their original names. The complete preview
must fit the row/column/payload limits or acceptance is blocked with a clear error;
the host does not silently truncate it. QuickTable's separate 10,000-row/64-column
limits are unchanged. See the independent
[Batch File Renamer](plugins/BatchFileRenamer/README.md) for an example consumer.

### Qt-Free QuickTable and Panel

Panels need an owner: expose a `UiController` subclass in the plug-in's root
package as an owner carrier. Do not implement/call `build` or `show` when using
these services; obtain its loader-owned lifetime with `require_owner()`.
QuickTables are static snapshots and need no owner.

```python
from fman.ui import QuickTableColumn, QuickTableRow, show_quick_table

COLUMNS = (QuickTableColumn('File Path', 'file_path'),
  QuickTableColumn('Size', 'numeric', unit='bytes'), QuickTableColumn('Snippet'))

def choose_results(pane, hits):
  rows = [QuickTableRow((hit.path, hit.size, hit.snippet)) for hit in hits]
  kept = show_quick_table(columns=COLUMNS, rows=rows, pane=pane, title='Results',
    summary='Filter the results, then press Enter')
  if kept is not None:
    process([hits[index] for index in kept])
```

```python
show_quick_table(*, columns, rows, pane=None, title='', summary='', modal=True,
  text_filter='fuzzy', base_path=None, truncated=None) -> tuple[int, ...] | None

show_panel(*, owner, pane, rows, on_change=None, on_action=None, on_closed=None)
```

QuickTable narrows a predefined, immutable set of rows. `show_quick_table`
**blocks until the window closes**: a command worker thread waits for its own
window only, so several modeless tables can close in any order; on the Qt
thread it runs a nested event loop. Rows cannot be
replaced while the table is open; call it again for new results.
Returned positions identify individual source rows. Reusing the same row object
does not collapse positions or visibility.

The window is buttonless:

| Key | Effect |
| --- | --- |
| Enter (table or filter box) | Close and return the positions in `rows` of the visible rows, in input order (not display order) |
| Escape, window close | Close and return `None` |
| Ctrl+Enter, double-click | Go To the current name/path cell |
| Alt+Down | Filter menu of the current column |
| Ctrl+F | Focus the filter box |

Enter and Go To do nothing while filtering runs, and Enter also after a filter
error or when no row is visible, so `None` always means cancelled and Go To
never acts on a row the new filter is about to hide. Callers explain the task through
`title`, `summary` and, when useful, `show_status_message`.

`columns` is a sequence of 1-64 `QuickTableColumn` descriptors; it defines
headers, navigation, sorting, filtering and formatting (see below).

`QuickTableRow(cells, highlights=(), targets=())` is frozen. `cells` holds one value per column:
a string for text, name and path kinds; an `int`/`float`/`None` for Numeric;
integer UTC epoch nanoseconds or `None` for Date. Optional highlights contain
one tuple of `(start, end)` character spans per column (text-like columns only).
Optional `targets` holds one entry per column: an absolute native path for a
name/path column, or `None`. When given, Copy Path and Go To use it instead of
the cell text, so display text can be escaped or shortened; `None` makes that
cell non-navigable. Other columns must be `None`.
`rows` is any iterable, validated once: at most 10,000 rows, 16 MiB text and
128 spans per cell.

`summary` is a single elided line above the table. `title` is the window title.

Name and path kinds navigate. Without `targets`, cell text is resolved lexically: absolute native
paths, or paths relative to `base_path` (default: the supplied local pane's
folder, captured once). No filesystem/CWD/environment expansion occurs during
resolution. File kinds require files, folder kinds require folders and
`entry_path` accepts either; the check happens at Go To. Without a pane, Copy
works but Go To is disabled; no active pane is silently selected.

Go To on a file opens its folder in the pane and selects it; on a folder it
opens the folder. With `modal=True` (the default) the table blocks its main
window and closes after a successful Go To (result `None`); focus returns to the
pane. With `modal=False` the main window stays usable and Go To keeps the table
open while focusing the pane. The table closes with its pane or main window.

The table has no file operations besides Go To, and no caller menus, callbacks,
details or refresh. Its built-in cell menu offers the column's Copy action, Go To
for name/path kinds, **Filter This Column...** and **Clear All Filters**.

QuickTable and QuickList use the shared fuzzy matcher: prefer a contiguous match
when available, otherwise use an in-order subsequence. Highlight positions map
back to the original text after casefolding. F1 Shortcuts has its own substring
filter and is not a fuzzy-matcher consumer.

#### Columns and Filters

```python
QuickTableColumn(label, kind='text', sortable=True, filterable=True, searchable=None,
  unit=None, date_display='timestamp', format=None, missing='Unknown')
```

| Kind | Cell | Filter | Sort | Cell menu |
| --- | --- | --- | --- | --- |
| `text` | `str` | Fuzzy / Contains | Case-insensitive | Copy Text |
| `file_name`, `folder_name` | `str` | Fuzzy / Contains | Natural | Copy Name, Go To |
| `file_path`, `folder_path`, `entry_path` | `str` | Fuzzy / Contains | Natural | Copy Path, Go To |
| `date` | ns or `None` | On, Before, After, Between, Missing | Chronological | Copy Date |
| `numeric` | number or `None` | `=`, `<`, `<=`, `>`, `>=`, Between, Missing | Numeric | Copy Value |

- Copy Path copies the resolved absolute path; other kinds copy the displayed text.
- Dates display as ISO `YYYY-MM-DDTHH:MM:SS±HH:MM` (or `YYYY-MM-DD` with
  `date_display='date'`) in the system zone, captured once per QuickTable.
  Date filters cover whole local days; a day ends where the next existing day
  starts, so a day before a skipped calendar date filters normally. Selecting a
  date that does not exist in the zone is an input error.
- Numeric values are signed 64-bit integers or finite floats. `unit='bytes'`
  requires nonnegative integers, displays `12,345 B` and adds a B/KiB/MiB/GiB
  filter unit. `format(value) -> str` overrides numeric display.
- Numeric filters compare integers exactly with the typed bound and floats with
  the nearest float to it, so a cell holding `0.1` matches `= 0.1`. Bounds
  outside the representable range (for example `1e1000000` bytes) are input
  errors.
- `None` displays `missing`. Missing values fail comparisons, match the Missing
  filter and sort last both ways.
- `searchable` defaults to text-like columns only. Each Date/Numeric column adds
  8 bytes per row to the 16 MiB budget.

Header layout, left to right: label, sort arrow (sorted column only), filter
funnel (filterable columns). The funnel is dim when idle and uses the theme
Highlight color when active. Clicking the label sorts; clicking the funnel opens
the filter menu only.

The initial current cell is in the first filterable column, or column zero if
none are filterable. After an empty result refills, the last current column is
restored. This also applies to QuickBoard.

```text
| File Path        ▽ | Size        ↓ ▼ | Date Modified  ▽ | Snippet         ▽ |
```

Alt+Down (or **Filter This Column...** in the cell menu) opens the current
column's menu: operator, value(s), unit, inline error, **Apply Filter**,
**Clear Filter**, **Clear All Filters**, **Sort Ascending/Descending** and
**Original Order**. Enter applies a valid filter. Clear All Filters also clears
the text query and keeps sorting. Filters and sort are session-only.

A row is visible when it passes the text query **and** every column filter.
`text_filter` selects the query box:

| Value | Behavior |
| --- | --- |
| `'fuzzy'` | Fuzzy subsequence with ranking and highlights (default) |
| `'substring'` | Case-insensitive contiguous match |
| `None` | No query box |
| `compile(query) -> predicate(cells)` | Caller matching, compiled once per edit |

`cells` is the tuple of searchable display strings. The predicate must be pure,
fast and return a strict `bool`. Compile errors, exceptions and non-bool results
show `Filter error: ...` and an empty view until the query changes. Empty text
never calls the hook.

`truncated` (`True`, `False` or `None`) reports whether the producer omitted
rows. `True` appends `· truncated` to the row count, even for zero matches.

Panel `rows` is a tuple of tuples of frozen descriptors, at most 16 by 16:
`TextField(id, label, value='', tooltip='', max_width=None)`,
`Toggle(id, icon, label, value=False, tooltip='')`,
`Label(id, text, icon=None, tooltip='')`,
`Choice(id, label, options, value, tooltip='')`,
`Action(id, label, icon=None, tooltip='')`. IDs are unique. SVG icon names are
relative to the loader-assigned `UiOwner.resource_root`; traversal/escaping
resources are rejected. The host loads/tints icons on demand. Actions are not
toggles; their labels/icons do not appear in value snapshots.

Text-field labels align across rows using their styled size hints.
`max_width` optionally caps the input in Qt logical pixels; it must be a
positive integer or `None` (uncapped). Capped fields remain left-aligned and
shrink within narrow Panels. Search Files uses `max_width=480`.
In forms with at least one capped field, when each row starts with one capped
field or label followed only by icon controls/actions, the trailing controls
share a left-aligned column. Extra width stays after the controls. Other forms
retain their existing action wrapping. Control colors remain host-owned; the
existing `stop` action uses a red icon. Empty action labels with an icon produce
28-pixel icon buttons with tooltips. Choice and action groups have 3-pixel gaps.
Optional label icons are noninteractive, render at 20 logical pixels and use
the label descriptor's tooltip; label value snapshots still contain only text.

`Choice` renders 2-8 mutually exclusive icon buttons. `options` contains unique
`(value, icon_resource, tooltip)` string triples, normalized to immutable tuples.
The initial `value` must name an option. Each option has a tooltip and accessible
name; clicking the selected button leaves it selected and emits no change.
Snapshots contain the selected string. Use `update(values={'mode': 'glob'})` to
select silently, or `update(enabled={'mode': False})` to disable the entire group.
An unknown value fails before any update is applied. Search Files uses
Choice for Literal/Glob/RegEx; Toggle remains for independent boolean settings.

`Select(id, label, options, value, tooltip='')` renders a dropdown with 1-128
unique `(value, label)` string pairs. `DateField(id, label, value=None, tooltip='')`
renders an optional calendar picker; values are canonical ISO dates from
1752-09-14 or `None`. Typed dates commit on Enter, focus loss or before a panel
action; calendar selection and programmatic updates remain immediate.
Snapshots and change callbacks expose complete, in-range pending ISO dates for
live validation; incomplete text falls back to the editor's committed date.
`IntegerField(id, label, value=None, minimum=0,
maximum=18446744073709551615, tooltip='')` renders an optional exact integer
stepper without a 32-bit ceiling. Booleans, fractions and out-of-range values
are rejected. A blank date/integer field returns `None`; clearing removes the
previous value, and zero remains a valid integer. No activation checkbox is
used. Snapshots contain no Qt objects.

`Separator(id)` inserts a vertical context divider before the following control.
It has no snapshot value and rejects value updates; its ID must be unique.

Forms containing these structured descriptors use 28-pixel controls and
bottom-aligned wrapping rows. Text fields grow within their width limits;
date/integer controls keep compact widths. An IntegerField immediately followed
by Select stays together (e.g. a size bound and its unit). Existing Search Files
aligned forms stay unchanged.
Programmatic updates are validated and silent, as for existing descriptors.
Structured rows beginning with an icon Label and containing Actions keep the
label left and the remaining controls right, with 3-pixel toolbar spacing.
Select tooltips also cover their labels. Tab and Shift+Tab follow descriptor
order, visiting each logical control once and skipping disabled controls.

`PanelHandle.snapshot()` returns an immutable value mapping.
`update(values=None, enabled=None)` validates and applies changes atomically
without echoing `on_change(values)`. User actions call
`on_action(action_id, values)`. `set_activity_status(text=None, *, get_text=None)`
owns a separate status label; a fast `get_text()` supplies immutable progress at
most five times a second. Terminal text or clear/disposal stops its timer.
`close()`, `is_open`, and the read-only `cancelled.is_set()` token manage lifetime.
One dock belongs to each main window; replacement closes the previous session.
Tables and Panels are independent: closing one does not close the other.

No new widget, signal, Qt enum or arbitrary layout bridge is exposed by these
services. Existing widget-based consumers remain supported.

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
| `UiOwner(resource_root=None)` | Create an active owner; the optional resource root is keyword-only. Production roots are assigned by the loader. |
| `resource_root` | Read-only registered plug-in directory; registration performs no asset I/O. |
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
| `focus_widget` | Assign the primary control for focus and query seeding. |
| `prompt` | Current prompt object or `None`; Qt-specific, not a portable dialog handle. Prefer public prompt methods. |
| `pane` | Invoking public pane, on PaneToolWindow. |
| `item_css` | Host theme data for list items, on PaneToolWindow. Treat it as host-owned. |
| `bottom_panel` | Host-mounted panel or `None`, on PaneToolWindow. Read-only for plug-ins. |

| Method/signal | Contract |
| --- | --- |
| `set_panel(panel)` | Host use: the panel widget is no longer exported, so plug-ins dock controls with `show_panel` instead. |
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
A modeless `show_quick_list` stays in its own window while a Panel is docked; Tab/Shift+Tab
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

### QuickList

```python
ListItem(id, title, hint='', metadata={})
show_quick_list(*, items, title='', summary='', modal=True, filter='fuzzy', query='',
  selected=(), title_label=None, hint_label=None, sort=None, settings=None,
  on_open=None) -> tuple | None
```

`ListItem` is a frozen dataclass with unique string IDs (≤512 characters),
titles ≤512 and hints ≤2048 characters.
`metadata` maps up to 8 unique labels (≤32 characters, distinct from
`title_label`/`hint_label`) to `()` (empty), a string, an `int` or finite `float`,
or `(sort_key, text)`; texts are ≤128 characters. All items share the same labels
in the same order (an item without a value lists the label with `()`) and the
same key kind per label. At most 10,000 items.

The call blocks: workers wait on an event, Qt callers run a nested loop. The
window is built hidden, `on_open(handle)` runs, then the window is shown unless
already closed. Enter returns the chosen IDs (selection in item order, else the
current item); Escape, the close button, owner invalidation through an attached
`handle.close` and main-window close return `None`.

| `QuickListHandle` member | Contract |
| --- | --- |
| `snapshot()` | Thread-safe `QuickListState(selected, chosen, current, query, sort)`. |
| `set_items(items)` | Validate, then replace; returns once applied. Removed selections are dropped. No-op after close. |
| `focus()` | Show and raise the open list. |
| `close(result=None)` | `None` or a tuple of current IDs; unknown IDs raise `ValueError`. |
| `is_open` | `False` once closed. |

Sorting: fields are `title_label`, `hint_label` (when given) and the metadata
labels; `Ctrl+F1`…`Ctrl+F10` sort by a field: ascending, descending, then the
original item order. The footer lists the keys and marks the current sort; sort
arrows have reserved space, so no text moves.
Empty values stay last. `sort=(label, ascending)` applies whenever its label
exists. With `settings='Name.json'` the user's choice is saved on a worker under
keys `sort` and `ascending` (`sort: null` for the original order), and a saved
choice overrides `sort`.

Keys: Space, Insert, Shift+navigation and Ctrl+A select in the list. Ctrl+I
inverts, Ctrl+Shift+A clears, Enter accepts and Escape cancels in both the list
and the filter. Tab moves between a modeless list and the docked Panel.

A driver attaches `handle.close` to its owner in `on_open` and detaches it in a
`finally`. Callbacks such as Panel actions should start their own thread for
blocking work (prompts, I/O), since the list keeps the Qt thread responsive.

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
| `try_claim()` | Acquire one nonblocking work lease for this named resource; return an idempotent release callable, or `None` if occupied. Retain until actual worker cleanup, including across owner unload/reload. |

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
| `contains_chars(text, query)` | Prefer contiguous substring positions; otherwise use an in-order subsequence. Case-sensitive when called directly. |
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
`.statusbar-pane`, `.quicksearch-query`,
`.quicksearch-item`, `.panel`, `.plugin-panel-dock`, and `.plugin-tool-window`.
Legacy `.bottom-panel` remains a CSS selector mapping even though the Python
BottomPanel alias was removed.

Quicksearch rendering also reads `.quicksearch-item-title`,
`.quicksearch-item-title-highlight`, `.quicksearch-item-hint`, and
`.quicksearch-item-description` properties for text styling. This is the host's
restricted CSS mapping, not a browser DOM/CSS engine. Unknown widget selectors
are not automatically exposed as theme APIs. QuickList uses the quicksearch item
styles; do not read private theme objects or add Favorites-specific host styles.

## Threading and Failure Handling

| Context | Safe contract |
| --- | --- |
| Ordinary command body | Worker execution through registry; perform bounded I/O and call public host services. |
| Listener notification | Worker thread; no Qt widget access. |
| Listener rewrite/visibility | Synchronous caller context; short, nonblocking and free of long I/O. |
| Quicksearch callbacks | UI thread; fast in-memory work only. |
| `show_quick_list` / `show_quick_table` | Blocking; call from a command or another worker. `on_open` runs on the calling thread. |
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

### QuickList and Panel

A Qt-free driver: a modeless list with a docked Panel, tied to the plug-in
owner. The controller only carries the owner.

```python
from threading import Thread

from fman import DirectoryPaneCommand, show_alert
from fman.ui import Action, ListItem, UiController, show_panel, show_quick_list


class ExampleUI(UiController):
  pass


class ShowExample(DirectoryPaneCommand):
  def __call__(self, query=''):
    owner = ExampleUI.require_owner()
    items = (ListItem('alpha', 'Alpha', metadata={'Size': 3}),
      ListItem('beta', 'Beta', metadata={'Size': 1}))
    handles = []

    def inspect(name, values):
      current = handles[0].snapshot().current
      Thread(target=show_alert, args=(current or 'Nothing',), daemon=True).start()

    def on_open(handle):
      handles.append(handle)
      owner.attach(handle.close)
      show_panel(owner=owner, pane=self.pane, rows=((Action('inspect', 'Inspect'),),),
        on_action=inspect, on_closed=handle.close)

    try:
      result = show_quick_list(items=items, modal=False, query=query,
        title_label='Name', settings='Example UI.json', on_open=on_open)
    finally:
      for handle in handles:
        owner.detach(handle.close)
    if result:
      show_alert(', '.join(result))
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