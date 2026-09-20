# Favorites

Favorites keeps a curated list of directory locations.

## Commands

- `Ctrl+B` / **Open favorites manager**: Open or focus Favorites Manager for the invoking pane.
- `Add Current Folder to Favorites`: Add or promote the active pane's folder,
  regardless of which file is highlighted or selected. Individual files cannot
  be added.

These are the two Favorites commands shown in the Command Center. The manager
can also be found by the aliases **Favorites Manager**, **Favorites**, and
**Show favorites**. It displays Name and Path in QuickList, with a fuzzy filter. Its separate action panel
spans the main window immediately above the status bar; both file panes shrink to
make room and recover that space when it closes.
Action buttons adapt to the application width without growing indefinitely;
their default maximum is 160 logical pixels, with room preserved for labels.
Recent is the initial default sort: most recently added or re-added first. The
drop-down saves its choice in `Favorites UI.json` through the existing settings
system and restores it when reopened. Name and Path sort alphabetically without
changing stored recency or capacity eviction order.
Filtering preserves the chosen sort, including Unicode name/path matches.

Click moves the current highlight without changing selection. Space toggles the
highlighted item; Insert toggles and advances. Right-click or Ctrl-click toggles individual rows,
Shift-click toggles a range, and Ctrl+A selects all visible rows. Shift+Up/Down
toggles the current row before moving, like the file pane. Current highlight and
selection are separate. Filtering retains hidden selections and displays
their count. Delete removes selected bookmarks, including hidden ones; with no
selection it removes the highlighted bookmark. The Delete button and list Del
key remove bookmarks immediately without confirmation. Files and folders are
never deleted; the manager stays open.

Rename changes only the highlighted name. Go To uses the highlighted location
in the invoking pane and closes after navigation succeeds; failures keep the
manager open. Enter in the query/list and double-click invoke Go To. Del in the
list invokes bookmark deletion; Del in text fields edits text. Tab moves focus
between the filter, list and bottom controls; Space in the filter inserts a space.
Up/Down and Page Up/Down in the filter move focus to the list and navigate;
subsequent Space toggles selection instead of editing the filter. Click the filter
or use keyboard focus traversal to resume typing. Right-click does not activate a
favorite, and right-clicking empty list space leaves selection unchanged.
QuickList is frameless, like QuickSearch. Click the small `x` at the far right of
the dock to end the UI session, closing both surfaces and canceling pending UI
work. Escape also closes it without undoing saved changes. Prompts consume Escape
first. Rename and Delete otherwise keep the manager open. The plug-in remains
loaded, so Ctrl+B can reopen it.

Each main window has one docked session. Opening a manager for another pane closes
the previous session; reopening for the same pane focuses it. Add/re-add and changes from another window
refresh open views without clearing query, sort or surviving selections. A fresh
session restores the saved sort and starts with an empty query. No manager reopens automatically.

Favorites are saved under `UserSettings` and support every location scheme
understood by the active pane.

Re-adding a favorite moves it to the top without changing its display name.
Missing or inaccessible locations report an error. For UNC locations, availability
checks can wait for the network off the UI thread. Closing prevents a late check
from starting navigation; a pane transition already started is not rolled back.

Go To checks that the saved location is a folder before navigating. An old or
manually edited entry pointing to a file reports an error and keeps the manager
open without dispatching navigation. Such entries are not automatically deleted
or converted; they can be removed in the manager.

Navigation has a 30-second deadline, including availability checks and command
dispatch. Cancellation releases its completion wait immediately. Filesystem calls already
running cannot be interrupted; at most two tracked initializations run at once.
New navigation can report that earlier checks are still finishing until they exit.

Custom key bindings can prefill the search query:

```json
{ "keys": ["Ctrl+Alt+B"], "command": "show_favorites", "args": {"query": "pro"} }
```

A nonempty supplied query also replaces the query in an existing manager. Ordinary
Ctrl+B focuses the existing manager without resetting it. The legacy command IDs
`remove_from_favorites` and `rename_favorite` remain callable from custom bindings
but are omitted from discovery; `show_favorites` and
`add_current_folder_to_favorites` keep their existing IDs.

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

Favorites is a reference plug-in, not a privileged UI feature. External plug-ins
can compose the same panels and use QuickList alongside the existing QuickSearch
API. All host access uses exported APIs; no fman.impl, Core imports or private
host attributes are needed.

It uses these provisional `fman.ui` exports: `UiController`,
`QuickList`, `ListItem`, `Panel`, `TextButton`, `DropDown`, `JsonSettings`,
`settings_resource`, `matchers` and `navigate`. Resource transactions, bounded
workers, prompts, theme hooks and loader lifetime are host services. The controller
calls `show()` from a command; the host calls `FavoritesController.build(window,
pane)` on Qt. This is the single construction hook. FavoritesSession is a plain
Python object holding records and actions; Favorites does not subclass the host
window. It connects the host's `shown`, `busy_changed` and `disposed` notifications.
`PaneToolWindow.set_panel(panel)` mounts the controls above the main-window
status bar and owns the close affordance and paired lifecycle. No custom window
layout changes are needed in a plug-in.
Use `Panel` and `set_panel`; the pre-release BottomPanel/set_bottom_panel aliases
have been removed. General `fman.Window`/`DirectoryPane` APIs expose no Qt host
bridges. `pane.on_closed(callback)` calls a no-argument callback and returns an
unsubscribe function; parenting, theme lookup and docking stay inside the host.
The opt-in `fman.ui` component layer still uses Qt widgets and supports standard
Qt layout/control APIs, as this plug-in demonstrates.
IconButton is available for boolean options; Favorites currently needs only a
sort drop-down and action buttons. See the
[plug-in UI guide](../../../../../../Plan/UIElements.md#plug-in-api).