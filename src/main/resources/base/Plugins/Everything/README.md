# Everything Search

1. Run **Add folder to Everything database** from Command Center. The prompt
   defaults to the folder under the cursor, otherwise the current local folder.
   Or run **Add favorite folders to Everything database** to import saved local favorites.
2. Press **Ctrl+E**, or run **Search file by Everything**. Enter an
   [Everything query](https://www.voidtools.com/support/everything/searching/),
   such as `*.pdf dm:thisweek`, `ext:txt`, or `folder: reports`.
3. Press **Enter** to enter a result folder or navigate to and highlight a file.
   **Escape** cancels. Results include match highlights, modification date and size.

Search covers the shared indexed-root list, independently of either pane.
It searches names and paths, not file contents. Results are capped at 100 by
default; a count row after the results reports truncation. During startup or a busy query, wait
for the ready status and edit or retry the query. Quicksearch does not refresh
automatically while its text remains unchanged.
If the managed process exits or its identity changes, reopen search to retry.
A foreign process using the same instance name is never stopped or adopted.

See [worked syntax examples with screenshots](../../../../../../docs/tools.md#everything-search)
for extension lists, size filters, exclusions and grouped alternatives.

## Indexed Folders

**Add folder to Everything database** requires an existing absolute local directory.
Network paths and mapped network drives are rejected. Adding a parent asks before
replacing redundant child roots. Spaces, commas and Unicode are supported.

**Add favorite folders to Everything database** imports all valid local favorite folders
in one batch, including unavailable local paths. Invalid entries, duplicates,
non-local favorites and existing files are skipped and reported. The Favorites
list is unchanged. This is a one-time import; run it again after changing favorites.
Canceling a parent-replacement confirmation leaves the indexed list unchanged.

Every folder-list write normalizes separators and `.`/`..`, removes case-insensitive
duplicates and omits children already covered by a parent. A batch requests one
background update. Already covered folders do not restart Everything; cleaning up
redundant saved entries alone also avoids a restart.
Unloading or replacing the plug-in rejects any pending root change before saving.

Offline roots remain configured until explicitly removed; removing the last root stops the
managed process. Changes are persisted before a serialized background restart.
If activation fails, the desired roots remain saved and the failure is shown in
the status bar and search. Reopen search to retry after resolving the problem.

## Folder Manager

Run **Manage Everything database folders** to open `everything-folders://` in the active
pane. The list contains only configured roots, with Name and Path columns.
It performs no availability scans and does not start Everything just to display
the list. Use normal selection, column sorting, typing to filter and Ctrl+F to
fuzzy-find names.

- Enter or double-click opens the actual folder. An unavailable root is kept.
- F11 copies the selected real folder paths.
- F8, Delete or Shift+Delete removes selected roots after a default-No confirmation.
   Files and folders on disk are never deleted.
- F5 from the other pane, or dropping local folders onto the manager, adds them
   in one batch without copying files. Invalid items are skipped; validation can
   be canceled before saving. Parent replacements still require confirmation.
- Open manager panes refresh after a saved change, preserving surviving selections.
   Ctrl+R reloads the list manually.
- Rename, move, archive and file-creation operations are refused for index entries.

Favorites import stays in Command Center, not as a manager row. The old
`remove_folder_from_everything_database` command is removed; use manager selection
and Delete instead. This does not remove Core's ordinary Delete commands.

See the [manager screenshot](../../../../../../docs/tools.md#folder-manager).

## Settings

Edit `UserSettings/Plugins/User/Settings/Everything.json`; omitted keys use defaults.

| Key | Default | Meaning |
| --- | --- | --- |
| `folders` | `[]` | Shared absolute local indexed roots |
| `executable` | `""` | Bundled binary, or an absolute compatible 1.4 portable executable path |
| `instance` | `"RoyiFileManager"` | Nonempty private name; letters, digits, `_`, `.`, `-` |
| `max_results` | `100` | Result limit, 1-1000 |
| `sort` | `"name"` | Name/path ascending, or `date_modified`/`size` descending |
| `show_metadata` | `true` | Show modification date and file size |
| `exit_with_application` | `true` | Stop the managed process on quit or plug-in unload |
| `query_timeout_ms` | `50` | Total synchronous query deadline, 1-500 ms |

Everything starts lazily only when configured roots are used. Its INI, database,
lock and process identity live under `UserSettings/Local/Everything`. No volume
indexing, service installation, elevation, HTTP server or Registry configuration
is used. The user's unnamed Everything instance is never controlled. A named
collision without matching ownership metadata is rejected.

With `exit_with_application: false`, a later session reuses the owned process
only when its identity, executable, generated configuration and ready state match.
Changed configurations and old ownership records without a configuration hash
use the checked restart path. IPC is prepared on the worker before readiness is
reported. Shutdown cancels work on Qt, then performs bounded waits on a cleanup
thread; the UI does not wait for Everything to finish exiting.

## Portable Dependency

`python build.py run`, `test` and `freeze` automatically obtain the official
**Everything 1.4.1.1032 x64 portable ZIP** from voidtools. The reviewed
[redistribution license](licenses/Everything.txt) is included in the repository,
not downloaded. The archive and extracted executable have pinned SHA-256 checks;
the license pin normalizes CRLF to LF for portable checkouts.
Verified local files work offline. `publish`/`release` inherit provisioning;
`package` only verifies frozen files. `clean` and `doc` do not download it.

No installer or SDK DLL is used. Frozen distributions include the executable and
license, plus the plug-in's Python dependencies. Existing frozen builds must be
rebuilt; copying the plug-in alone cannot fix a missing bundled `uuid` module.
Everything 1.5 overrides are not supported by this implementation.