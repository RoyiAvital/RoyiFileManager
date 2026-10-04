# UI Elements

UI elements available to plug-ins. `fman.ui` is a provisional RoyiFileManager extension.

## Elements

| Element         | Import                  | Purpose                              | Hosting                                                          | Qt Exposure                  | Interaction                                                                                                                                                    | Consumers                                                               |
| --------------- | ----------------------- | ------------------------------------ | ---------------------------------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| QuickSearch     | `fman.show_quicksearch` | Pick **one** item                    | Own modal dialog                                                 | None                         | Query callback supplies items; click/Enter returns the choice and closes                                                                                       | Command Palette, Favorites rename/remove pickers, hash algorithm choice |
| QuickList       | `fman.ui.QuickList`     | Navigate and select **many** items   | Widget embedded in a `PaneToolWindow` via `UiController.build()` | Qt widget                    | Optional fuzzy filter; Space/Insert/Shift/Ctrl/right-click selection; signals `activated`, `state_changed`, `delete_requested`                                 | Favorites Manager                                                       |
| Panel (widget)  | `fman.ui.Panel`         | Operation controls and actions       | Docked above the status bar via `window.set_panel()`             | Qt widget                    | `IconButton`, `TextButton`, `DropDown`; values persisted with `JsonSettings`                                                                                   | Favorites Manager                                                       |
| Panel (service) | `fman.ui.show_panel`    | Operation controls and actions       | Docked above the status bar; host owns layout                    | None (returns `PanelHandle`) | Plain descriptors: `TextField`, `Toggle`, `Choice`, `Select`, `DateField`, `IntegerField`, `Label`, `Action`, `Separator`; `on_change` / `on_action` callbacks | Search Files, Find Files                                                |
| QuickTable      | `fman.ui.show_quick_table` | Narrow a static, typed table      | Modal (default) or modeless window owned by the host             | None (blocks; Enter returns visible row positions, Escape `None`) | `QuickTableColumn` kinds (text, name, path, date, numeric) define headers, sorting, header filter menus and Copy / Go To; static `QuickTableRow` snapshot with raw date/number cells; fuzzy, substring or caller text filter; Ctrl+Enter / double-click Go To; `truncated` count note | Search Files, Find Files, Checksum Files                                |
| OutputTextBox   | `fman.ui.OutputTextBox` | Selectable plain-text output         | Widget embedded in a tool window                                 | Qt widget                    | Copy icon and Return/Enter copy all                                                                                                                            | Calculate File Hash                                                     |

Supporting services: `UiController` / `UiOwner` (loader-bound lifetime),
`ToolWindow` / `PaneToolWindow` (host window, prompts, `work()`), `navigate`
(tracked navigation), `settings_resource` (shared JSON transactions), `matchers`.

New plug-ins should prefer the Qt-free services (`show_panel`, `show_quick_table`).

### Rationale for Elements

We strive for a _buttonless_ experience. Hence for all elements:
 - <kbd>Enter</kbd> returns the result.
 - <kbd>Esc</kbd> cancels.

 - `QuickSearch` - Text list with fuzzy search. Made for a **single element** selection. <kbd>Enter</kbd> sends the caller the selected item.
 - `QuickList` - Text list with fuzzy search. Made for a **multiple elements** selection. <kbd>Enter</kbd> sends the caller the selected item(s). Allows batch operations on URLs with context menu (<kbd>Menu</kbd> / <kbd>Shift</kbd>+<kbd>F10</kbd>): Delete, Copy, Move, Rename (single element). <kbd>Ctrl</kbd>+<kbd>Enter</kbd> as a _Go To_ shortcut on URL.
 - `QuickTable` - Multi-column table with typed columns. Made for narrowing a predefined immutable table with filters per column and fuzzy search. <kbd>Enter</kbd> sends the caller the filtered (remaining) item(s). <kbd>Ctrl</kbd>+<kbd>Enter</kbd> as a _Go To_ shortcut on URL.

## `QuickSearch` vs. `QuickList`

The purpose of `QuickSearch` is the simplest and fastest list with fuzzy search with text elements in mind.  
The `QuickList` extend that to allow interaction with multiple elements and apply operations on the selected elements.  
`QuickList` may interact with a Panel to allow extended functionality.

|                      | QuickSearch                                                | QuickList                                                                       |
| -------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Origin               | Original `fman` API                                        | RoyiFileManager `fman.ui` extension                                             |
| Purpose              | Pick **one** item                                          | Navigate and select **many** items                                              |
| Window               | Own modal dialog                                           | Embeddable widget; no window of its own                                         |
| Result               | Returns the chosen item and closes                         | Stays open; plug-in reacts to signals                                           |
| Filtering            | Always shows a query; the callback supplies matching items | Optional (`fuzzy=True` or `matcher=`); without it no query box, all items shown |
| Selection            | Current item only                                          | Current item and selected set are separate; file-pane style keys and mouse      |
| Filter and Selection | Not applicable                                             | Hidden selections are kept and counted; stable `ListItem.id`                    |
| Actions              | None; accepting is the action                              | In a separate docked Panel                                                      |
| Threading            | Called from a command worker, blocks until closed          | Built on the Qt thread in `UiController.build()`; command does not block        |
| Use Cases            | Command Palette, Go To, choose an algorithm                | Favorites Manager, multi-item remove                                            |

Both share the `QuickSearch` theme (`.quicksearch-item`) and fuzzy matchers.