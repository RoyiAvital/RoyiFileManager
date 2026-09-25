# Favorites 003: Favorites as a Pane Location

Status: Design complete, 2026-09-25, ready for review. Application code is
unchanged. All [decisions](#decisions) are recorded; implementation requires
review of this design and separate authorization.

## Task

Show Favorites as an ordinary pane location, `favorites://`, instead of the
floating QuickList and docked action panel from
[Favorites 002](../Done/Favorites002.md). Every favorite is a row, so the pane's
existing keys, selection, filtering, sorting, context menu and custom key
bindings apply without a separate UI. This removes the two-window layout and its
focus bridging, and closes the open split-layout item in Favorites 002.

## Scope

Included:

- `Ctrl+B` opens `favorites://` in the **active pane** (user decision 1). In a
  Favorites pane it reloads the list, like **Show processes** in Process Pane.
- Columns: **Name**, **Path**, **Added**, **Used** and **Count**. Enter or
  double-click opens the real folder in the same pane. `Ctrl+Left`/`Ctrl+Right`
  open it in the left/right pane.
- Opening a favorite records its last use time (**Used**) and increments its open
  count (**Count**). It never changes the Added order (user decision 4).
- Rename with the existing Rename command (`Shift+F6` or user bindings) in place.
- `F8`, `Delete` and `Shift+Delete` remove favorites after confirmation. Folders
  on disk are never touched.
- `F11` copies the real folder paths.
- `F5` from a file pane into a Favorites pane, or dropping folders onto it, adds
  them as favorites (user decision 5). `F6` into Favorites is refused.
- Filtering and fuzzy find stay exactly as they are in panes (user decision 2):
  typing uses the substring/glob Filter Bar, `Ctrl+F` uses fuzzy Quicksearch over
  the favorite names.
- Missing or inaccessible folders are reported only when opened (user decision 3).
  Listing never checks targets.
- The saved sort is restored, with Recent (Added, newest first) as the default.

Excluded: groups, editable paths, manual ordering, file favorites, drag reorder,
network availability checks while listing, and changes to QuickList, Panel or
any other `fman.ui` component.

Compatibility:

- `Favorites.json` data, duplicate identity rules, `max_favorites` and the
  replace-oldest prompt are unchanged. Eviction still removes the oldest added
  favorite, regardless of use.
- Favorite entries gain two optional keys, `last_used` (UTC ISO 8601 string) and
  `use_count` (non-negative integer). They are written only after a favorite is
  opened. Missing or invalid values mean never used and do not invalidate the
  entry. Older versions ignore both keys when reading, but drop them on save.
- Command IDs `show_favorites`, `add_current_folder_to_favorites`,
  `remove_from_favorites` and `rename_favorite` stay callable.
- `show_favorites` keeps its `query` argument; see [Commands](#commands).
- `Favorites UI.json` keeps its `sort` key and gains the values `Used` and
  `Count`, plus an optional boolean `ascending`, default `true`.
- The public plug-in API is unchanged. Favorites is implemented as if it were a
  third-party plug-in: public APIs only, no host or Core changes. See
  [Public API Boundary](#public-api-boundary).
- Favorites stops being the reference consumer of `QuickList` and `Panel`.
  Those components stay exported and tested by their existing demo.

## Design

### Provider

A new `Favorites(FileSystem)` with `scheme = 'favorites://'` in the Favorites
plug-in. It reads the same store under the existing settings lock.

| Member | Behavior |
| --- | --- |
| Row key | Lowercase hex of a 16-byte BLAKE2b digest of `FavoritesStore.key(url)`. Stable across renames and unique because the store rejects duplicate keys. Display names are not keys: they may repeat or contain `/`. |
| `scan('')` | `Listing.create('favorites://', keys, labels=names, is_dir=True for all, identities=digests, extra=(('path', readable paths), ('order', recency positions), ('used', last-use epoch nanoseconds or None), ('count', open counts)))`. No filesystem I/O. Other paths raise `NotADirectoryError`. |
| `get_default_columns` | `('core.Name', 'favorites.Path', 'favorites.Added', 'favorites.Used', 'favorites.Count')`. |
| `is_dir(key)` / `exists(key)` | In-memory lookup only. Root is a directory. Unknown keys raise `FileNotFoundError` / return `False`. |
| `resolve(key)` | Returns the stored `file://` (or other scheme) URL. Root resolves to `favorites://`. Unknown keys raise `FileNotFoundError`. |
| `name(path)` | Favorite name; root is `Favorites`. |
| `move(src, dst)` | Rename only: both URLs must be `favorites://`; the favorite of `src` gets `basename(dst)` as its new name. Anything else raises `io.UnsupportedOperation`. |
| Mutations | `mkdir`, `touch`, `copy`, `delete` and `move_to_trash` stay unimplemented, so Core hides commands that check for them. |

After every committed store change (add, rename, remove, open, from any pane or
window), the provider calls `notify_file_changed('')`. Open Favorites panes then
refresh; selection survives via the stable identities.

### Store

`Favorite` gains `last_used` and `use_count`, defaulting to `None` and `0`.
`FavoritesStore.record_use(url, now)` sets `last_used` to `now` and increments
`use_count`. It does not move the favorite. Rename and re-add keep both values;
remove and eviction drop them. `to_json` writes each key only when it is set.

### Columns

- `core.Name`: unchanged Core column; it already displays and sorts `labels`.
- `favorites.Path` (`display_name = 'Path'`): `text` and `keys` from the `path`
  extra, compared case-insensitively.
- `favorites.Added` (`display_name = 'Added'`): `text` is the 1-based position;
  `keys` are the recency positions, so ascending means newest first.
- `favorites.Used` (`display_name = 'Used'`): local date and time in the same
  format as Core's Modified column, using `PyQt5.QtCore.QLocale` directly rather
  than importing Core; empty when never used. `keys` are
  `(used is not None, nanoseconds)`, so descending lists the most recent first
  and never-used favorites last.
- `favorites.Count` (`display_name = 'Count'`): the open count, `0` when never
  used; `keys` are the counts.
- `keys_depend_on_external_data = False` for all four new columns.
- `Ctrl+F1`/`F2`/`F3` sort by Name/Path/Added. Used and Count sort by header
  click or custom `sort_by_column` bindings with `column_index` 3 and 4.

### Commands

| Key / command | Mechanism in a Favorites pane |
| --- | --- |
| `Ctrl+B` / `show_favorites(query='')` | Navigate the active pane to `favorites://`, or reload it there. A nonempty `query` then runs `search_files_in_current_folder` with that query, replacing the old prefilled manager filter. |
| Enter, double-click | Core `open` sees a directory and runs `open_directory`. A `FavoritesListener.on_command` rewrites `open_directory` for a `favorites://` row to a hidden `open_favorite` command. It resolves the stored URL, checks it is a folder, records the use (Used and Count), then runs `open_directory` with the stored URL. Everything runs on the command worker, never on Qt. |
| `Ctrl+Left` / `Ctrl+Right` | Core calls `open_directory` on the destination pane; the same rewrite applies there and the use is recorded. |
| Rename | Core's in-place edit shows the name (the Name column text). Core's `RenameListener` then prepares a move to `favorites://<new name>`, which the provider's `move` turns into a rename. The row key is unchanged, so the cursor stays on it. Names containing `/` or `\` are refused by Core, as for files. |
| `F8`, `Delete`, `Shift+Delete` | Rewritten to a hidden `remove_favorites` command that works on the chosen rows and asks "Remove N favorites? Folders on disk are not deleted." with default No. |
| `F11` | Rewritten to copy the stored folder paths instead of `favorites://` keys. |
| `F5` into Favorites, drop onto Favorites | Rewritten to a hidden `add_favorites` command; see [Adding by Copy and Drop](#adding-by-copy-and-drop). |
| `F6` into Favorites | Rewritten to an alert: "Moving is not supported; use F5 to add folders." |
| Copy, move or drag out of Favorites; pack, new file, create folder in Favorites | Rewritten to a hidden alert: "Favorites are shortcuts, not files." |
| Add current folder to favorites | Unchanged. Hidden and refused while the pane itself shows `favorites://`. |

A missing target: `open_favorite` alerts "Favorite location not found: <path>"
without recording a use. The pane stays in Favorites and the favorite is kept,
as today. A stored file target alerts "<path> is not a folder." A failed save of
the use record reports the error and still opens the folder.

### Sorting

A `FavoritesListener.before_location_change` supplies the saved sort only when
entering `favorites://` with no sort column requested: `sort` maps `Recent`,
`Name`, `Path`, `Used` and `Count` to `favorites.Added`, `core.Name`,
`favorites.Path`, `favorites.Used` and `favorites.Count`, with
`ascending`. It only rewrites when the requested column is empty, so it cannot
loop against Core's `RememberSortSettings`. When a pane leaves `favorites://`,
the listener saves the current column and direction to `Favorites UI.json`.

### Adding by Copy and Drop

- `F5`/`F6` run `copy`/`move` in the active file pane. The `FavoritesListener`
  of that pane finds the destination with `self.pane.window.get_panes()`, as
  Process Pane does. When it is `favorites://`, `copy` becomes `add_favorites`
  and `move` becomes the refusal alert. Core's Copy never runs, so no destination
  prompt appears.
- A drop runs Core's `DragAndDropListener` in the Favorites pane, which issues
  `copy` with `files` and `dest_dir`. Drops from another scheme, including
  Explorer, are always `copy`. The listener rewrites them to `add_favorites`.
  A drop onto a favorite row (`favorites://<key>`) is treated as the list.
- `add_favorites` runs on the command worker. It checks every item is a folder
  (skipping files and missing items), then adds them under the existing lock.
  The first chosen folder ends up at the top of Added.
- Existing favorites are re-added: moved to the top of Added, keeping their name,
  Used and Count, like **Add current folder to favorites**.
- Capacity: one prompt for the batch, "Favorites is full. Replace the N oldest?",
  default No. No adds nothing.
- The result is a status message, for example "Added 3 folders, skipped 2 files."
  Adding happens without a confirmation; `F8` undoes a mistaken add.

### Public API Boundary

The plug-in uses only APIs available to a third-party plug-in in
`UserSettings/Plugins/User`, following
[Process Pane](../src/main/resources/base/Plugins/ProcessPane/process_pane/__init__.py):

| Need | Public API |
| --- | --- |
| Location, rows, rename | `fman.fs.FileSystem`, `fman.listing.Listing`, `fman.url` |
| Columns | `core.Name` and `fman.fs.Column` |
| Rewrites and default sort | `DirectoryPaneListener.on_command`, `before_location_change` |
| Commands | `DirectoryPaneCommand`; hidden commands return `False` from `is_visible` |
| Storage and locking | `load_json`, `save_json`, `fman.ui.settings_resource` |
| Messages and clipboard | `show_alert`, `show_status_message`, `fman.clipboard` |
| Refresh | `FileSystem.notify_file_changed`; `pane.reload()` through `window.get_panes()` as fallback |

No `fman.impl` imports, private host attributes, Core imports or host/Core
changes. Accepted dependencies and caveats:

- **Core command behavior**, as fman plug-ins have always relied on: Open runs
  `open_directory`; Rename prepares a move to `favorites://<new name>`; drops
  from another scheme become `copy`; Core remembers sort per location and binds
  `sort_by_column` to `Ctrl+F1`-`F3`. Tests guard each of these.
- **SearchFileFuzzy**: `show_favorites(query=...)` runs
  `search_files_in_current_folder`. When that command is not registered, the
  query is ignored.
- **Refresh**: if the host does not refresh an open snapshot pane on
  `notify_file_changed('')`, the changing command reloads the Favorites panes of
  its window.
- **Provisional API**: `settings_resource` belongs to provisional `fman.ui`.
- **Single provider**: another plug-in registering `favorites://` or the same
  command IDs cannot be installed alongside, as Process Pane notes for ProcessFS.

### Removal

Delete `FavoritesController`, `FavoritesSession`, the QuickList window, the
docked Panel, the Favorites `Ctrl+B` window shortcut and their JSON settings
binding. Keep `favorites/store.py` and the command-level store logic.

### Threading and Failure

- `scan` and provider lookups run on pane workers and read a snapshot of the
  store taken under the existing lock.
- The `on_command` rewrites run synchronously in the command worker, as all
  listener rewrites do. No Qt objects are touched by the provider.
- Store save failures keep the previous file and report the error, as today.

### Decisions

1. `Ctrl+B` uses the active pane.
2. Filtering and fuzzy find keep their current pane behavior.
3. Targets are checked only when a favorite is opened.
4. Opening never reorders Added; it records Used and Count instead.
5. `F5` and drops add folders; `F6` into Favorites is refused.
6. Default sort is Recent (Added ascending), retaining today's default through
   the Favorites listener and `Favorites UI.json`. The rejected option was plain
   pane behavior: default Name ascending with no Favorites sort code.

## Alternatives

- **Keep the Favorites 002 manager.** Rejected: two top-level windows with focus
  bridging, an unresolved Alt+Tab/second-monitor check, and a separate copy of
  selection, filter and sort logic that ignores user key bindings.
- **Pane-like QuickList docked in the main window.** Rejected: it changes shared
  QuickList behavior for all plug-ins (or adds a mode), and still duplicates the pane.
- **Open Favorites in the other pane.** Rejected by user decision 1.
- **Names as row keys.** Rejected: duplicate names and `/` are invalid Listing
  names, and a rename would change identity and drop marks.
- **Promote on open.** Rejected by user decision 4: moving an opened favorite to
  the top of Added makes rows jump; Used and Count give the same information
  without changing the Added order.
- **Refuse `F5` and drops.** Rejected by user decision 5: the refusal rewrite is
  needed anyway, and adding costs only one command.
- **Plain pane default sort (Name).** Rejected by decision 6 to keep today's
  Recent default.
- **Host or Core hooks for Favorites.** Rejected: every behavior is reachable
  through public plug-in APIs.
- **Resolve-only navigation (no `open_directory` rewrite).** Kept only as a
  fallback for direct `set_path` calls; the rewrite makes Enter behave like
  opening the real folder, records the use and keeps the check on the command
  worker.

## Runtime Effects

- Startup: registering one provider, four columns and one listener. No scan until
  a pane opens `favorites://`.
- Listing: in memory, O(n) hashing for at most `max_favorites` rows (200 by
  default). No filesystem, network or target checks.
- Opening: one `is_dir` on the target and one atomic `Favorites.json` save in the
  command worker. A slow UNC target
  blocks that pane's navigation until the OS returns; the Favorites 002 30-second
  deadline and cancel no longer exist, like opening any UNC folder today.
- Adding by copy or drop: one `is_dir` per item and one atomic save, on the
  command worker. A slow network folder in a large drop delays that command.
- Memory: less than today; no QuickList window, panel or subscriptions.
- No threads, timers, polling or background jobs. The unused path costs nothing
  beyond registration.

## Tests

- Unit (`src/unittest/python/fman_unittest/test_favorites.py`):
  - Provider `scan`: keys, labels, identities, extras, order, and no I/O
    (patched `os`/`fman.fs` calls not invoked).
  - Stable keys across rename; distinct keys for different URLs; duplicate names
    allowed.
  - `resolve`, `is_dir`, `exists`, unknown keys, non-root paths.
  - `move` renames only and rejects other schemes; unsupported mutations raise.
  - Store: `record_use` sets time and count without reordering; rename and
    re-add keep them; remove drops them; missing, invalid and legacy entries load
    as never used; `to_json` omits unset keys.
  - Used/Count columns: text, never-used rows, and ascending/descending keys.
  - `open_favorite`: records only after a successful folder check, not for
    missing or file targets; a failed save still opens the folder.
  - Listener rewrites: `open_directory`, `move_to_trash`, `delete_permanently`,
    `copy_paths_to_clipboard`, copy/move/pack/new file, and no rewrite in file panes.
  - Sort mapping and persistence, including the no-loop rule with a requested
    column.
  - `remove_favorites` confirmation default No, selection vs cursor, store errors.
  - `add_favorites`: folders only with skip counts, re-add keeps name and usage,
    batch order, one capacity prompt (Yes replaces, No adds nothing).
  - `copy`/`move` rewrites for `F5`/`F6` from a file pane (destination from the
    other pane), drops with `dest_dir` on the root or a row, and refusal of copy,
    move and drops out of Favorites.
  - Public API guard: the plug-in imports no `fman.impl`, `core` or other
    bundled plug-in modules.
- Qt integration (replace `FavoritesManagerIT` in
  `src/integrationtest/python/fman_integrationtest/test_qt.py`):
  - `Ctrl+B` opens Favorites in the active pane; again reloads.
  - Enter and double-click open the real folder; `Ctrl+Left/Right` target panes.
  - Opening updates Used and Count in another open Favorites pane without
    changing the Added order.
  - Inline rename keeps cursor and selection; F8 removes after Yes, keeps after No.
  - Filter Bar and `Ctrl+F` over names; `show_favorites` with `query`.
  - Missing and file targets alert and stay in Favorites.
  - Another pane's add/rename/remove refreshes an open Favorites pane with marks kept.
  - `F5` of selected folders and a drop add favorites without a Copy prompt;
    `F6` alerts; files are skipped; nothing is written to disk.
  - Without SearchFileFuzzy loaded, `show_favorites` with `query` still opens
    Favorites.
- Plug-in load/unload: update
  `src/integrationtest/python/fman_integrationtest/impl/plugins/test_favorites_plugin.py`.
- Native smoke: rewrite `favorites_smoke.py` for the pane flow, including a
  native drop from another pane and dragging a Favorites row to Explorer
  (expected: nothing happens).
- Documentation screenshots: the `favorites` capture in
  `src/misc/generate_docs_screenshots.py` shows the Favorites pane; update
  `test_generate_docs_screenshots.py` if its behavior changes.

## Implementation Steps

1. Add the store usage fields, provider, columns and row-key helper with unit tests.
2. Add the listener rewrites, `open_favorite`, `remove_favorites`,
   `add_favorites` and the new `show_favorites` with unit tests.
3. Add sort mapping/persistence with unit tests.
4. Remove the manager UI and its tests; add the Qt integration tests.
5. Update the plug-in load test, public API guard, native smoke and screenshot
   capture.
6. Update the Favorites README, `docs/tools.md`, `docs/shortcuts.md`,
   `README.md` and `CHANGELOG.md`.

## Acceptance Criteria

- `Ctrl+B` shows `favorites://` in the active pane with Name, Path, Added, Used
  and Count.
- Enter, double-click and `Ctrl+Left/Right` open the stored folder and update
  Used and Count without reordering Added; a missing or file target alerts,
  records nothing and leaves the pane in Favorites.
- Rename, remove (with confirmation) and `F11` work through the normal pane keys
  and user key bindings; folders on disk are never changed.
- `F5` and drops add folders (skipping files) with one capacity prompt; `F6`
  into Favorites and any copy/move/drag out of Favorites are refused.
- Filter Bar, `Ctrl+F`, selection and column sorting behave as in file panes.
  The saved sort is restored, defaulting to Recent.
- No QuickList window or docked panel is created; `Favorites.json` data and all
  listed command IDs keep working.
- Listing performs no filesystem I/O; all focused tests above pass.
- The plug-in uses only public APIs and works unchanged when installed under
  `UserSettings/Plugins/User` instead of bundled; no host or Core file changes.

## Reviewers

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Initial design. User decisions: active pane, existing filtering and
  fuzzy find, target check only on open. Decisions 4 (reorder on open) and 5
  (add by copy/drop) are pending; both are recommended as No.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Resolved decision 4: opening never reorders Added; added Used (last
  open time) and Count (open count) columns, stored as optional entry keys and
  recorded by a hidden `open_favorite` command after a successful folder check.
  Added decision 6 (default sort Recent vs Name). Decisions 5 and 6 pending.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Design complete. Decision 5: `F5` and drops add folders through
  `add_favorites`, `F6` refused. Decision 6: keep Recent as the default sort.
  Added the public-API-only requirement with accepted Core command dependencies,
  SearchFileFuzzy fallback, refresh fallback and single-provider caveat. Ready
  for independent review.
