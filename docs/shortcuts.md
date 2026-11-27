# Keyboard Shortcuts

Open the Command Center with ++ctrl+shift+p++ to see every command.

## Files

| Key                  | Action                          |
| -------------------- | ------------------------------- |
| ++f3++               | View file                       |
| ++f4++               | Edit file                       |
| ++shift+f4++         | Edit new file                   |
| ++ctrl+n++           | New file                        |
| ++f5++               | Copy                            |
| ++f6++               | Move                            |
| ++shift+f5++         | Create symbolic link            |
| ++shift+f6++         | Rename                          |
| ++f7++               | Create folder                   |
| ++f8++ or ++delete++ | Delete (move to Recycle Bin)    |
| ++shift+delete++     | Delete permanently              |
| ++f11++              | Copy chosen paths, one per line |
| ++shift+f11++        | Copy chosen names, one per line |
| ++alt+enter++        | Properties                      |

## Clipboard

| Key           | Action                          |
| ------------- | ------------------------------- |
| ++ctrl+c++    | Copy files to the clipboard     |
| ++ctrl+x++    | Cut files to the clipboard      |
| ++ctrl+v++    | Paste files                     |
| ++f11++       | Copy chosen paths, one per line |
| ++shift+f11++ | Copy chosen names, one per line |

!!! info "Multiple Files / Folders Selection"
    Copy item(s) name and Copy item(s) path support one or multiple items and
    show their shortcuts in Command Center. The context menu uses the same
    commands under Copy name and Copy path. With no chosen item, Copy item(s)
    name leaves the clipboard unchanged and Copy item(s) path copies the current folder.

## Navigation

| Key                            | Action                                   |
| ------------------------------ | ---------------------------------------- |
| ++tab++                        | Switch panes                             |
| ++ctrl+u++                     | Swap pane locations                      |
| ++enter++                      | Open                                     |
| ++backspace++ or ++alt+up++    | Go up                                    |
| ++alt+left++ / ++alt+right++   | Back / forward                           |
| ++ctrl+p++                     | Go to a location                         |
| ++ctrl+backslash++             | Go to root of current drive              |
| ++alt+f1++ / ++alt+f2++        | Choose a drive for the left / right pane |
| ++ctrl+left++ / ++ctrl+right++ | Open in left / right pane                |
| ++ctrl+r++                     | Refresh                                  |

## Selection and Display

| Key                                                     | Action                                                   |
| ------------------------------------------------------- | -------------------------------------------------------- |
| ++space++                                               | Toggle selection                                         |
| ++insert++, NumLock-off keypad Insert or ++shift+down++ | Toggle selection and move down                           |
| ++ctrl+a++                                              | Select all visible entries                               |
| ++ctrl+d++                                              | Clear selection                                          |
| Keypad **+**                                            | Select by pattern / Select group (Filter Bar closed)     |
| Keypad **-**                                            | Deselect by pattern / Deselect group (Filter Bar closed) |
| Keypad **\***                                           | Invert visible selection (Filter Bar closed)             |
| ++ctrl+period++                                         | Toggle hidden files                                      |
| ++ctrl+q++                                              | Toggle QuickView                                         |
| ++ctrl+s++                                              | Toggle extended status and supported local free space    |
| ++ctrl+shift+d++                                        | Toggle directory sizes                                   |
| ++ctrl+shift+enter++                                    | Show directory size                                      |

Pattern selection previews marks without hiding rows. Enter applies; Esc cancels.
Space and keypad punctuation edit the pattern in this mode. Ordinary `+`, `-`
and `*` keys do not invoke these keypad commands.
An open Filter Bar receives keypad text instead of the selection shortcuts.
Close it first, or use Command Center for Select/Deselect by pattern or Invert selection.
NumLock-off keypad navigation and Insert still work while filtering.

!!! info "Keypad, Not Num Lock"
    `Num+` in a binding means the numeric keypad. Keypad `+`, `-` and `*` work with
    Num Lock on or off. Ordinary typing keys do not invoke these shortcuts.

### While Previewing Selection

| Key                             | Action                                                |
| ------------------------------- | ----------------------------------------------------- |
| ++enter++                       | Apply the latest preview; wait if matching is pending |
| ++esc++                         | Cancel and keep the original marks                    |
| ++space++, keypad `+`, `-`, `*` | Edit the pattern, not pane selection                  |
| ++ctrl+a++                      | Select the pattern text, not all pane rows            |
| ++backspace++ / ++delete++      | Edit the pattern text                                 |

See the [illustrated selection guide](basics.md#select-by-pattern).

### Commands Without Default Shortcuts

Open Command Center with ++ctrl+shift+p++.

| Command                                                | Action                                                          |
| ------------------------------------------------------ | --------------------------------------------------------------- |
| **Select same extension**                              | Add visible files with the highlighted file's final extension   |
| **Duplicate item** / **Copy file here**                | Suggest an available numbered name in the current folder        |
| **Go to clipboard path** / **Open clipboard location** | Open one copied location or highlight a copied file path        |
| **Go to link target** / **Reveal link target**         | Open the highlighted link's target or highlight its target file |
| **Sync pane location**                                 | Open the active location in the opposite pane                   |

## Find and Search

| Key              | Action                                 |
| ---------------- | -------------------------------------- |
| ++ctrl+f++       | Find files in current folder           |
| ++ctrl+shift+f++ | Find files recursively                 |
| ++ctrl+e++       | Search indexed folders with Everything |
| ++shift+f7++     | Find files with `fd`                   |
| ++alt+f7++       | Search files                           |

See the [search guide](search.md).

## Tools

| Key              | Action                 |
| ---------------- | ---------------------- |
| ++ctrl+shift+p++ | Command Center         |
| ++f9++           | Open terminal          |
| ++f10++          | Open in Explorer       |
| ++alt+f5++       | Pack archive           |
| ++ctrl+b++       | Open favorites manager |
| ++ctrl+h++       | Calculate file hash    |

## Favorites Manager

| Key                           | Action                                                                                     |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| ++ctrl+f1++ … ++ctrl+f5++     | Sort by Name, Path, Added, Last opened, Opened: ascending, descending, then original order |
| ++ctrl+i++ / ++ctrl+shift+a++ | Invert / clear the selection                                                               |
| ++enter++                     | Go To the chosen favorite                                                                  |
| ++tab++                       | Move between the list and the buttons                                                      |
| ++esc++                       | Close                                                                                      |

See [Sorting Favorites](tools.md#sorting-favorites).

## Commander Style Shortcuts

For a Norton Commander or Total Commander style workflow.

| Key                           | Action                                                     |
| ----------------------------- | ---------------------------------------------------------- |
| ++f1++                        | Show keyboard shortcuts                                    |
| ++f3++                        | View file                                                  |
| ++f4++                        | Edit file                                                  |
| ++f5++                        | Copy                                                       |
| ++f6++                        | Move                                                       |
| ++f7++                        | Create folder                                              |
| ++f8++                        | Delete (move to Recycle Bin)                               |
| ++f9++                        | Open terminal                                              |
| ++f10++                       | Open in Explorer                                           |
| ++f11++                       | Copy paths to clipboard                                    |
| ++ctrl+u++                    | Swap pane locations                                        |
| Keypad **+** / **-** / **\*** | Select group / Deselect group / Invert (Filter Bar closed) |

++f2++ offers a rename binding when a file is under the cursor; ++f12++ is unassigned.

### Modified Function Keys

| Key           | Action                            |
| ------------- | --------------------------------- |
| ++shift+f4++  | Edit new file                     |
| ++shift+f5++  | Create symbolic link              |
| ++shift+f6++  | Rename                            |
| ++shift+f7++  | Find files with `fd`              |
| ++shift+f11++ | Copy chosen names, one per line   |
| ++alt+f1++    | Choose a drive for the left pane  |
| ++alt+f2++    | Choose a drive for the right pane |
| ++alt+f5++    | Pack archive                      |
| ++alt+f7++    | Search files                      |
| ++ctrl+f1++   | Sort by name                      |
| ++ctrl+f2++   | Sort by size                      |
| ++ctrl+f3++   | Sort by modified time             |
| ++ctrl+f4++   | Sort by directory size            |

## QuickView (When Focused)

Press ++tab++ from the file pane to focus QuickView; press ++tab++ or ++esc++ to return.

| Mode        | Key                                                     | Action                                          |
| ----------- | ------------------------------------------------------- | ----------------------------------------------- |
| Any         | ++ctrl+q++                                              | Close QuickView                                 |
| Images      | ++f++ / ++1++                                           | Fit to view / 100% actual pixels                |
| Images      | ++plus++ / ++minus++ or ++ctrl++ + wheel                | Zoom (5% to 800%)                               |
| Images      | Arrows / ++shift++ + Arrows                             | Pan 32 / 128 pixels                             |
| Images      | ++space++                                               | Play or pause an animation                      |
| PDF         | ++f++ / ++w++                                           | Fit page / Fit width                            |
| PDF         | ++plus++ / ++minus++ or ++ctrl++ + wheel                | Zoom (25% to 400%)                              |
| Text / Code | ++ctrl+f++, ++f3++ / ++shift+f3++                       | Find, next match, previous match                |
| CSV / TSV   | ++ctrl+f++, ++alt+down++                                | Filter all columns / open current column filter |
| CSV / TSV   | ++ctrl+c++ / ++ctrl+shift+c++                           | Copy selected cells as TSV / with headers       |

See [QuickView](tools.md#quickview) for full details.

## Edit Attributes and Batch File Renamer

| Tool               | Key                       | Action                                         |
| ------------------ | ------------------------- | ---------------------------------------------- |
| Edit Attributes    | ++space++ / ++shift+space++ | Cycle attribute state forward / backward     |
| Edit Attributes    | ++insert++                | Cycle state and move down                      |
| Edit Attributes    | ++enter++ / ++shift+enter++ | Apply / apply recursively to folder contents |
| Batch File Renamer | ++ctrl+f++                | Focus the template input                       |
| Batch File Renamer | ++alt+down++              | Open the current column filter                 |
| Batch File Renamer | ++enter++ / ++esc++       | Apply visible renames / cancel                 |
