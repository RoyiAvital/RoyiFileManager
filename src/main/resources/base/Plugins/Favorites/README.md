# Favorites

Favorites keeps a curated list of directory locations.

## Commands

- `Ctrl+B` / **Open favorites manager**: Open or focus Favorites Manager for the invoking pane.
- `Add Current Folder to Favorites`: Add or promote the active pane's folder,
  regardless of which file is highlighted or selected. Individual files cannot
  be added.

These are the two Favorites commands shown in the Command Center. The manager
can also be found by the aliases **Favorites Manager**, **Favorites**, and
**Show favorites**.

## Manager

The manager is a modeless QuickList with a fuzzy filter, plus a Panel docked
above the status bar with **Rename**, **Delete** and **Go To**. Both file panes
shrink to make room and recover it when the manager closes. Each favorite shows
its name, path and a line with **Added** (date), **Last opened** (date) and
**Opened** (how often Go To opened it). Favorites saved before this version show
empty dates and keep their order. The footer lists the sort keys; drag the title
to move the window.

| Key | Action |
| --- | --- |
| Space, Insert, Shift+navigation, Ctrl+A | Select in the list |
| Ctrl+I / Ctrl+Shift+A | Invert / clear the selection |
| Ctrl+F1 … Ctrl+F5 | Sort by Name / Path / Added / Last opened / Opened; again reverses |
| Tab | Move between the list and the Panel |
| Enter | Go To the chosen favorite |
| Escape or the dock's `x` | Close the manager |

- **Delete** removes the chosen bookmarks (the selection, or the highlighted one)
  without confirmation. Folders are never deleted; the manager stays open. The
  Delete key does not delete.
- **Rename** renames the highlighted bookmark.
- **Go To** opens the chosen favorite in the invoking pane and closes the manager
  once the pane has loaded it, counting it as opened. It needs exactly one chosen
  favorite. Missing locations, files and failed navigation show an alert and keep
  the manager open.
- The sort is saved in `Favorites UI.json` and restored next time. Sorting never
  changes the stored order, which drives `Added` and capacity eviction.
  Re-adding a favorite updates its Added date and keeps its Opened count.

One manager is open per main window. Opening it for another pane, or with a
query, replaces it; plain Ctrl+B focuses it. Changes from other commands or
windows refresh it without clearing the query or surviving selections.

Re-adding a favorite moves it to the top without changing its display name.
Favorites support every location scheme understood by the active pane.

Custom key bindings can prefill the search query:

```json
{ "keys": ["Ctrl+Alt+B"], "command": "show_favorites", "args": {"query": "pro"} }
```

The legacy command IDs `remove_from_favorites` and `rename_favorite` remain
callable from custom bindings but are omitted from discovery.

## Settings

The bundled defaults are stored in `Favorites.json`:

```json
{
	"favorites": [],
	"max_favorites": 200
}
```

Create
`UserSettings/Plugins/User/Settings/Favorites (Windows).json` to override the
defaults. `max_favorites` limits the saved list; adding beyond the limit asks
before replacing the oldest favorite.

## Public API

Favorites is the reference third-party plug-in: it imports no Qt, no `fman.impl`
and no Core modules. It uses `show_quick_list` with an `on_open` driver,
`show_panel` with `Action` controls, `UiController` as an owner carrier,
`settings_resource` for store transactions, and `load_json`/`save_json`,
`show_prompt`, `show_alert` and `run_command('open_directory')` from `fman`.
See the [plug-in UI guide](../../../../../../PlugIn.md#ui-extension).
