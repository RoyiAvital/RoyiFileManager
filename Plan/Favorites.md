# Favorites

## Task

Add a bundled `Favorites` plug-in that keeps a user-maintained list of
bookmarked locations, comparable to Total Commander's *Directory Hotlist*
(`Ctrl+D`) and Double Commander's *Directory Hotlist*. Two primary commands
are required, with two management commands described below:

- `Add Current Folder to Favorites` — Command Center only, no default
  shortcut. Bookmarks the active pane's current location.
- `Show Favorites` — Command Center and default shortcut `Ctrl+B`. Opens a
  Quicksearch listing the favorites; `Enter` navigates the active pane to the
  chosen location.

Motivation: `GoTo` (`Ctrl+P`) ranks *visited* paths by frequency and forgets
rarely used ones, so a deliberately curated, stable list is missing.

## Scope

Included:

- Add, show/open, remove, and rename (display name) favorites.
- Persistence in `UserSettings` through the existing JSON configuration
  mechanism.
- Any location URL the pane can hold (`file://`, `drives://`, `network://`,
  `zip://`, ...); stale locations remain listed and are handled gracefully
  when selected.
- Keyboard-only workflow plus mouse click in the Quicksearch.

Excluded:

- Bookmarking individual files (a favorite is always a directory URL).
- Folders/groups, arbitrary reordering, raw JSON editing, drag-and-drop,
  import from Total Commander `wincmd.ini`, per-pane favorite lists, and a
  sidebar. These can be later tasks. Re-adding a favorite still moves it to
  the top.
- Changes to the public `fman` plug-in API. Runtime integration uses public
  APIs except for one documented dependency on bundled Core matchers.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
plug-in can be removed without affecting Core.

## Design

Plug-in layout `Plugins/Favorites/`:

- `favorites/__init__.py` — commands, listener-free.
- `favorites/store.py` — pure-Python store (load, validate, add, remove,
  rename, serialize); no Qt, unit-tested in isolation.
- `Favorites.json` — bundled default (`{"favorites": []}`).
- `Key Bindings (Windows).json` — `Ctrl+B` → `show_favorites`.
- `README.md`.

Data model (`Favorites.json`, saved via `save_json` so only the final Windows
settings layer at
`UserSettings/Plugins/User/Settings/Favorites (Windows).json` changes):

```json
{
  "favorites": [
    {"name": "Projects", "url": "file:///D:/Projects"},
    {"name": "Downloads", "url": "file:///C:/Users/me/Downloads"}
  ]
}
```

- `url` is the pane URL as returned by `pane.get_path()`, normalized with
  `fman.url.normalize` (no trailing slash, forward slashes). Identity uses a
  separate canonical key: normalized `file://` URLs are case-folded on Windows
  while other schemes remain case-sensitive. The stored URL preserves its
  normalized spelling. Adding an existing identity again does not duplicate;
  it moves the entry to the top and updates nothing else.
- `name` defaults to the last path component (`basename`), or the human
  readable URL for roots such as `file:///C:` → `C:\`. Names need not be
  unique.
- Order is recency-based: new and re-added favorites move to the top, while
  rename and removal preserve the relative order of remaining entries.
- Invalid entries (missing `url`, non-string fields, unparsable scheme) are
  dropped from the in-memory snapshot. Store loading returns the number of
  rejected entries so the command can show one status message; the file is
  not rewritten until the next mutation.

Commands can overlap because each `DirectoryPaneCommand` invocation may run on
a separate worker thread. A plug-in-level `RLock` therefore guards each complete
load-copy-mutate-save transaction. The pure store never mutates the object
returned by `load_json`; it validates into a private copy and passes a new dict
to `save_json`. Dialogs are never shown while holding the lock. Remove and
rename re-load and revalidate the selected URL after their dialog closes. The
existing configuration mechanism remains last-writer-wins across separate
application processes; cross-process merging is outside this task.

Commands (`DirectoryPaneCommand` so `self.pane` is the active pane):

- `AddCurrentFolderToFavorites` (`add_current_folder_to_favorites`, alias
  `Add current folder to favorites`): reads `self.pane.get_path()`, refuses
  `null://` with a status message, otherwise inserts/moves to top and shows
  `Added <name> to favorites.` for 3 s. `is_visible()` returns `False` for
  `null://`. If adding a new entry at the limit, obtain confirmation before
  the mutation, then re-load under the transaction lock and evict the current
  bottom entry only if the limit still requires it.
- `ShowFavorites` (`show_favorites`, alias `Show favorites`): opens
  `show_quicksearch(get_items, get_tab_completion, query)`. Each item is
  `QuicksearchItem(value=url, title=name, hint=as_human_readable(url),
  highlight=...)`. Filtering uses the Core matcher chain already used by
  `GoTo` (`path_starts_with`, `basename_starts_with`,
  `contains_substring`, `contains_chars`) against name first, then path, so
  `pro` finds `Projects` and `d:\pro` finds `D:\Projects`. Empty query lists
  everything in stored order. Name matches provide title-relative highlight
  indexes; path-only matches use an empty highlight because Quicksearch applies
  indexes to the title, not the hint. The command snapshots favorites before
  opening Quicksearch so its `get_items` callback performs no I/O or shared
  mutation on the Qt thread. `Tab` completes the human-readable URL of the
  current item, like `GoTo`.

  On `Enter` or click, check only the selected URL with `fman.fs.exists`. A
  definite missing result shows an alert and leaves the pane unchanged. If the
  filesystem does not implement `exists`, defer to Core's `open_directory`
  behavior; otherwise run `open_directory` with the URL. This avoids eager
  filesystem probes and still handles stale favorites without a traceback.
- `RemoveFromFavorites` (`remove_from_favorites`, alias
  `Remove from favorites`): if the active pane's location is a favorite,
  removes it after a `YES | NO` confirmation; otherwise opens the same
  Quicksearch with the prompt `Remove favorite:` and removes the chosen
  entry. Command Center only.
- `RenameFavorite` (`rename_favorite`, alias `Rename favorite`): Quicksearch
  to pick, then `show_prompt` with the current name preselected. Cancel and
  blank or whitespace-only names make no change. Command Center only.

Threading: commands run in the command thread as all plug-in commands do;
`show_quicksearch`, `show_prompt`, `show_status_message` are already
main-thread safe. The plug-in lock provides transaction-level serialization;
the `Config` lock only protects individual cache and save calls.

Integration points, all existing: `load_json`/`save_json`,
`show_quicksearch`, `show_prompt`, `show_alert`, `show_status_message`,
`pane.get_path()`, `pane.run_command('open_directory', ...)`, and
`fman.fs.exists`. Importing matchers from `core.quicksearch_matchers` is an
intentional bundled-plug-in dependency, not part of the public `fman` API; keep
it isolated in the matching adapter and covered by tests for upstream
mergeability.

## Alternatives

- **Extending `GoTo` with pinned entries** — rejected: `GoTo` mixes visited,
  indexed and typed paths with frequency ranking; a pinned list inside it
  would be hard to see and to manage, and `GoTo`'s pruning logic would need
  exceptions.
- **A `favorites://` filesystem scheme** (browse favorites as a folder) —
  rejected for the first version: it needs Core registration, columns,
  `resolve` semantics and rename/delete mapping, for a list that rarely
  exceeds a few dozen entries. Quicksearch gives instant filtering with zero
  new UI.
- **Sidebar/toolbar with bookmark buttons** — rejected: no toolbar exists in
  this application; keyboard-first is the design language.
- **Storing display names only, deriving URL** — rejected: URL is the stable
  identity; names may collide.
- **`Ctrl+D` as in Total Commander** — rejected: `Ctrl+D` is `deselect` in
  Core. `Ctrl+B` is currently free in every bundled binding file and is
  reserved here for Favorites. The pending Flat View task mentions Total
  Commander's `Ctrl+B` convention but does not assign that shortcut.
- **Editing the user JSON for reordering** — rejected for the first version:
  `Config` caches loaded JSON, so edits made by an external editor would not be
  observed reliably and a later command could overwrite them.

## Runtime Effects

- Startup: the plug-in registers four commands and one key binding; no
  timers, threads, I/O or model work. `Favorites.json` is read lazily on the
  first command through the shared `Config` cache.
- Steady state: zero background cost. Each command does one JSON read from
  the cache and, on change, one differential write of a file of at most a
  few kilobytes.
- `Show Favorites` snapshots at most `max_favorites` entries; keystroke
  filtering is pure string matching over that immutable snapshot. Opening a
  selection performs at most one existence query before navigation.
- A module-level `RLock` serializes in-process mutations. No lock is held while
  Quicksearch, prompts, or confirmation dialogs are open.
- No feature toggle is needed: unused, the plug-in only occupies the command
  registry.

## Settings

`Favorites.json` (bundled default and user override):

```json
{
  "favorites": [],
  "max_favorites": 200
}
```

`max_favorites` prevents unbounded growth (adding beyond the cap removes the
oldest bottom entry after a confirmation). Invalid values fall back to
defaults. The bundled generic file supplies defaults; `save_json` writes user
changes to `Favorites (Windows).json` in the Settings plug-in.

## Implementation Steps

1. `store.py`: `FavoritesStore` with `load(json_dict)`, `add(url, name)`,
  `remove(url)`, `rename(url, name)`, `to_json()`, defensive copying,
  normalization and validation; unit tests.
2. `__init__.py`: `AddCurrentFolderToFavorites` and `ShowFavorites` with
  immutable snapshots, matcher chain, title-only highlighting, tab completion,
  selected-item existence handling, and `open_directory`.
3. Add the shared transaction lock, then implement `RemoveFromFavorites` and
  `RenameFavorite` with post-dialog revalidation.
4. Add `Favorites.json` defaults and `Key Bindings (Windows).json`. Add the
  plug-in directory to `build.py`'s test `PYTHONPATH`; no spec-file entry is
  needed because the complete base resources tree is already bundled.
5. Update the plug-in README, main README, and changelog.

## Tests

Required final command from the repository root:

```powershell
python build.py test
```

Unit tests (`src/unittest/python/fman_unittest/test_favorites.py`, no Qt):

- `FavoritesStore`: add inserts at top; adding an existing URL moves it to
  the top without duplicating; URL normalization (`file:///D:/Projects/` and
  `file:///D:/Projects` are the same); Windows `file://` identity is
  case-insensitive without changing the stored spelling; non-file identity is
  case-sensitive; default name from basename and from drive root;
  remove/rename by URL; invalid entries dropped on load and reported;
  `max_favorites` cap; `to_json()` round trip.
- `ShowFavorites.get_items`: empty query returns stored order; name match
  ranks before path match; title highlight indexes are valid; path-only
  matches do not highlight the title; filtering performs no filesystem I/O.
- `AddCurrentFolderToFavorites`: `null://` refused with a status message and
  `is_visible()` is `False`; success message text; `save_json` called with
  the updated dict.
- Command wiring with a `Mock` pane, patching `show_quicksearch` to return
  `(query, url)`: an existing or unsupported-scheme URL invokes
  `open_directory`; a definitely missing URL shows an alert and leaves the
  pane unchanged; `None` (cancel) invokes nothing.
- `RemoveFromFavorites` on the current location asks `YES | NO` and removes
  only on `YES`.
- `RenameFavorite` leaves data unchanged on cancel or a blank name.
- Concurrent add/remove/rename calls cannot lose an in-process update, and
  dialog-based mutations revalidate the selected URL after the dialog closes.

Integration (existing plug-in loading test pattern): the plug-in loads, the
four commands appear in the palette, `Ctrl+B` maps to `show_favorites`, and
the bundled `Favorites.json` merges with an empty user file. Saving writes the
override to `UserSettings/Plugins/User/Settings/Favorites (Windows).json`.

Manual: add a `zip://` location, restart, and confirm `Show Favorites` opens
it; delete a bookmarked folder on disk and confirm selecting it reports the
missing location without navigating or raising a traceback.

## Acceptance Criteria

- `Add Current Folder to Favorites` is available in the Command Center,
  bookmarks the active pane's location, and never creates duplicates.
- `Show Favorites` opens on `Ctrl+B`, filters as the user types, and `Enter`
  navigates the active pane to the chosen location.
- Favorites persist across restarts in
  `UserSettings/Plugins/User/Settings/Favorites (Windows).json`; re-adding an
  existing favorite moves it to the top.
- Remove and rename are possible without leaving the keyboard.
- Selecting a missing location reports it and leaves the active pane unchanged
  instead of navigating or raising a traceback.
- No background work exists when the commands are not used; the public
  `fman` API is unchanged.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Initial design created: Quicksearch-based favorites plug-in using
  only the public API, `Ctrl+B` chosen because `Ctrl+D` is taken by
  `deselect`.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context window: Not exposed by host
- Outcome: Revised persistence, concurrency, stale-location handling,
  Quicksearch highlighting, URL identity, packaging, shortcut ownership, and
  test coverage; approved the plan for implementation with those corrections.
