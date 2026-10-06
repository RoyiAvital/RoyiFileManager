# UI Elements

UI elements available to plug-ins. `fman.ui` is a provisional RoyiFileManager extension.

## Elements

| Element         | Import                  | Purpose                              | Hosting                                                          | Qt Exposure                  | Interaction                                                                                                                                                    | Consumers                                                               |
| --------------- | ----------------------- | ------------------------------------ | ---------------------------------------------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| QuickSearch     | `fman.show_quicksearch` | Pick **one** item                    | Own modal dialog                                                 | None                         | Query callback supplies items; click/Enter returns the choice and closes                                                                                       | Command Palette, Favorites rename/remove pickers, hash algorithm choice |
| QuickList       | `fman.ui.show_quick_list` | Select **many** items            | Modal (default) or modeless window owned by the host             | None (blocks; returns the chosen IDs or `None`; `on_open` handle) | Optional fuzzy filter; Space/Insert/Shift/Ctrl/right-click selection; metadata line; sorting by title, hint or metadata                                        | Favorites Manager                                                       |
| Panel           | `fman.ui.show_panel`    | Operation controls and actions       | Docked above the status bar; host owns layout                    | None (returns `PanelHandle`) | Plain descriptors: `TextField`, `Toggle`, `Choice`, `Select`, `DateField`, `IntegerField`, `Label`, `Action`, `Separator`; `on_change` / `on_action` callbacks | Search Files, Find Files, Favorites Manager                             |
| QuickTable      | `fman.ui.show_quick_table` | Narrow a static, typed table      | Modal (default) or modeless window owned by the host             | None (blocks; Enter returns visible row positions, Escape `None`) | `QuickTableColumn` kinds (text, name, path, date, numeric) define headers, sorting, header filter menus and Copy / Go To; static `QuickTableRow` snapshot with raw date/number cells; fuzzy, substring or caller text filter; Ctrl+Enter / double-click Go To; `truncated` count note | Search Files, Find Files, Checksum Files                                |
| OutputTextBox   | `fman.ui.OutputTextBox` | Selectable plain-text output         | Widget embedded in a tool window                                 | Qt widget                    | Copy icon and Return/Enter copy all                                                                                                                            | Calculate File Hash                                                     |
| QuickBoard      | `fman.ui.show_quick_board` | Compose one string with a typed preview | Modal window owned by the host | None (blocks; returns exact string and approval/cancellation) | Fixed columns; worker-driven row replacement; optional column filters/sorting; Copy displayed text; no Go To | String-composition plug-ins |

Supporting services: `UiController` / `UiOwner` (loader-bound lifetime),
`ToolWindow` / `PaneToolWindow` (host window, prompts, `work()`), `navigate`
(tracked navigation), `settings_resource` (shared JSON transactions), `matchers`.

Plug-ins should use the Qt-free services (`show_quick_list`, `show_panel`, `show_quick_table`, `show_quick_board`).

### Rationale for Elements

We strive for a _buttonless_ experience. Hence for row based elements:
 - <kbd>Enter</kbd> returns the result.
 - <kbd>Esc</kbd> cancels.

Row based elements: 
 - `QuickSearch` - Text list with fuzzy search. Made for a **single element** selection with immutable list. <kbd>Enter</kbd> sends the caller the selected item.
 - `QuickList` - Text list with fuzzy search. Made for selecting **multiple elements** from a mutable list. <kbd>Enter</kbd> returns the selected item(s). Exposes an handler which can read its state and replace its items. Items may carry metadata, optionally sortable.
 - `QuickTable` - Multi column table with typed columns. Made for narrowing a predefined immutable table with filters per column and fuzzy search. <kbd>Enter</kbd> sends the caller the filtered (remaining) item(s). <kbd>Ctrl</kbd>+<kbd>Enter</kbd> as a _Go To_ shortcut on URL.
 - `QuickBoard` - Multi column table with optionally typed columns. Assists the user in composing a string. The input data is mutable by the caller. <kbd>Enter</kbd> sends the caller the string and indication of approval. <kbd>Esc</kbd> sends the caller the string and indication of cancellation. 

## `QuickSearch` vs. `QuickList`

The purpose of `QuickSearch` is the simplest and fastest list with fuzzy search with text elements in mind.  
The `QuickList` element extends `QuickSearch` with multiple elements selection and metadata for display and optionally sorting.  
A `QuickList` can be driven by a Panel to allow extended functionality.

|                      | `QuickSearch`                  | `QuickList`                         |
| -------------------- | ------------------------------ | ----------------------------------- |
| Purpose              | Pick **one** item              | Select **many** items               |
| API                  | `fman.show_quicksearch()`      | `fman.ui.show_quick_list()`         |
| API Returns          | `(query, value)` or `None`     | The chosen items or `None`          |
| Mutability           | Immutable list                 | Mutable list                        |
| Window               | Own modal dialog               | Own window                          |
| Qt Exposure          | None                           | None                                |
| Items                | From a query callback          | Set by the caller; can be replaced  |
| Metadata             | None                           | Optional, per item                  |
| Sorting              | By the callback                | By title, hint or metadata          |
| Filtering            | Always                         | Optional                            |
| Selection            | Current item only              | Current item and selected set       |
| Filter and Selection | Not applicable                 | Hidden selections are kept          |
| Result               | The chosen item                | The chosen items                    |
| State                | Not applicable                 | Via the handle from `on_open`       |
| Actions              | None                           | By the caller, e.g. from a Panel    |
| Modality             | Modal                          | Modal or modeless                   |
| Tab                  | Within the dialog              | Modeless: also to a docked Panel    |
| Threading            | Blocks a worker until closed   | Blocks a worker until closed        |
| Use Cases            | Command Palette, choose one    | Favorites Manager, pick several     |

Both share the `QuickSearch` theme (`.quicksearch-item`) and fuzzy matchers.

## `QuickTable` vs. `QuickBoard`

The purpose of `QuickTable` is to narrow a predefined table through text and column filters.  
The `QuickBoard` element assists the user in composing a string, with rows supplied by the caller as the text changes.  
Both support optional column filtering and sorting. `QuickTable` returns the remaining row positions, while `QuickBoard` returns the composed string with approval or cancellation.

|                       | QuickTable                                     | QuickBoard                                          |
| --------------------- | ---------------------------------------------- | --------------------------------------------------- |
| Purpose               | Narrow predefined data                         | Compose a string with a tabular preview             |
| Data                  | Immutable row snapshot                         | Rows supplied and updated by the caller             |
| Columns               | Typed column descriptors                       | Column names with optional types                    |
| Modality              | Modal (default) or modeless                    | Modal only (blocks its application window)          |
| Text Field            | Filter the existing rows                       | Input to the caller's row handler                   |
| Row Updates           | No replacement while open                      | Handler supplies rows initially and as text changes |
| Sorting               | Optional, by column type                       | Optional, by column type                            |
| Column Filtering      | Optional, by column type                       | Optional, by column type                            |
| Filtering and Result  | Determines which rows are returned             | Presentation only; does not change the string       |
| Enter                 | Visible row positions, in original input order | Composed string and approval                        |
| Esc                   | `None`                                         | Composed string and cancellation                    |
| Cell Editing          | None                                           | None                                                |
| Qt Exposure           | None                                           | None                                                |
| Threading             | Blocks a worker until closed                   | Blocks a worker until closed                        |
| Caller Responsibility | Interpret the returned row positions           | Interpret and act on the accepted string            |
| Use Cases             | Search Files, Find Files, Checksum Files       | Batch rename patterns, query or expression previews |

