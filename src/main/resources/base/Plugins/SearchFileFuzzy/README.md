# SearchFileFuzzy

Searches files from the active pane without modifying the pane's file model or
the main window. Local searches build a fresh index with `os.scandir` for every
invocation, so changes made by other programs are reflected in the results.
Other filesystem schemes use the public fman filesystem API.

## Commands

- `Ctrl+F`: Search files in the current folder.
- `Ctrl+Shift+F`: Search files recursively using breadth-first traversal.

Selecting a result opens its containing folder and places the cursor on the
file. Directories are traversed but are not included in the results. Unreadable
directories are skipped. Recursive local searches do not follow directory
symbolic links or junctions.

Searches are case-insensitive. When hidden entries are disabled, hidden
directories are pruned together with all of their descendants.

## Settings

The defaults are stored in `SearchFileFuzzy.json`:

```json
{
	"mode": "fuzzy",
	"max_recursive_entries": 50000,
	"max_results": 100,
	"include_hidden": true
}
```

Create
`UserSettings/Plugins/User/Settings/SearchFileFuzzy.json` to override individual
values without changing the bundled plug-in. Set `mode` to `fuzzy` for
subsequence matching or `regular` for normalized, case-insensitive substring
matching. `max_recursive_entries` bounds the number of files and directories
inspected during either search command. `max_results` bounds the quicksearch
results. When `include_hidden` is false, dot-prefixed and Windows-hidden entries
are excluded, including entire hidden directory trees.

The commands also accept an optional `mode` argument from custom key bindings,
which overrides the configured mode for that invocation.