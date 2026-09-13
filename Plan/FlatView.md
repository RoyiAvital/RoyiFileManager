# Flat View

## Task

Add a per pane *flat view* that lists every file below the current directory
in one flat list, similar to Total Commander's "Branch View". The view is
toggled per pane with a `Toggle Flat View` command available from the Command
Center and bindable as `toggle_flat_view`. It has no default shortcut because
`Ctrl+B` is reserved for Favorites. Leaving the flat view returns to the normal
listing of the same directory.

## User-visible behavior

- The pane lists files from the current directory and all its subdirectories.
  The `Name` column shows the path relative to the root directory with
  backslashes (`sub\dir\file.txt`). `Size` and `Modified` behave as usual.
- Directories are not listed (files only). A setting can include them as
  entries of their own.
- **Archives (`.zip`, `.7z`, `.tar`, `.jar`, ... — anything in
  `archive_handlers`) are always shown as a single file entry.** The flat view
  never descends into an archive, even though the normal view can browse it as
  a folder. `Enter` on an archive entry behaves exactly as in the normal view
  (the `ArchiveOpenListener` may open it as `zip://`, which leaves the flat
  view).
- Hidden files and files below hidden directories follow the pane's
  hidden-file state.
- Directory symbolic links and junctions are not followed.
- Traversal stops at a configurable entry limit; a status message reports
  that the listing is limited.
- `Enter` on a file opens it; `Backspace`/`GoUp` returns to the normal view of
  the root directory. Copy, move, rename, delete, and drag and drop act on the
  underlying files.
- The location bar shows the root directory with a `[flat]` marker.
- The flat state is part of the location and therefore survives restarts via
  the saved pane location.

## Scope

This task adds a reversible flat listing for local directory trees, including
normal pane sorting, selection, file operations, hidden-file behavior, and
session restoration. Archive contents, remote schemes, following directory
links, and unbounded traversal are excluded from the first version.

## Design

Implement the flat view as a filesystem scheme, `flat://`, in Core
(`core/fs/flat.py`), following the pattern of `zip://`. A `flat://` path is
the `file://` path of the root directory. This keeps `Model`, the views, the
columns, sorting, filtering, and the status bar unchanged; only the filesystem
is new.

`FlatFileSystem`:

- `iterdir(root)` yields the relative POSIX paths of all files below `root`,
  breadth-first, using the `os.scandir` traversal already written for
  `SearchFileFuzzy`. Move that traversal into Core (`core/fs/flat.py`) and let
  the plug-in import it from there; plug-ins may depend on Core, Core must not
  depend on a plug-in.
- Descends only into real directories: `entry.is_dir(follow_symlinks=False)`
  and not `is_junction()`/directory symlink. Archives are regular files at the
  filesystem level, so they are leaves by construction; add an explicit test
  so a future "browse archives" feature cannot regress this.
- `is_dir`, `stat`, `size_bytes`, `modified_datetime`, `resolve` delegate to
  the underlying `file://` URL. `resolve(flat:///C:/dir/a/b.txt)` returns
  `file:///C:/dir/a/b.txt`, which makes `open_file`, `_open_files`, and the
  status bar work without changes.
- `name(path)` returns the relative path with backslashes; the natural sort of
  the `Name` column then orders by relative path.
- Mutating operations (`copy`, `move`, `delete`, `move_to_trash`, `mkdir`,
  `touch`, `prepare_*`) translate `flat://` URLs to `file://` and delegate to
  `fman.fs`, as `zip://` does, and emit `notify_file_*` on the flat URLs so
  the flat model updates. Files created by other programs appear on the next
  reload (application activation), like everywhere else on Windows.
- `get_default_columns` returns `core.Name`, `core.Size`, `core.Modified`.

Hidden files: Core's `_hidden_file_filter` currently accepts every non
`file://` URL. Extend it to resolve `flat://` URLs (or expose an `is_hidden`
query on `FlatFileSystem`) and treat a file as hidden when it or any
directory between it and the root is hidden. The traversal prunes hidden
directories when the pane hides hidden files, so their contents are never
listed nor counted.

Commands (Core):

- `ToggleFlatView`: if the pane is at `file://X`, `set_path('flat://X')`,
  placing the cursor on the same file when it exists in the flat list; if at
  `flat://X`, `set_path('file://X')` and place the cursor on the top-level
  entry containing the previously selected file. Invisible for other schemes.
- `GoUp` at `flat://X` returns to `file://X` (analogous to the existing
  `zip://` root handling).
- `Reload` works unchanged.
- `Pack`, `Copy`, `Move`, `Delete`, `Rename` work unchanged because they
  operate on URLs; `Rename` of `sub\dir\file.txt` renames only the file name.

Location bar: `as_human_readable` handles only `file://`; render
`flat:///C:/dir` as `C:\dir [flat]` in `LocationBar` without changing
`fman.url`.

Sort settings are keyed by URL (`Sort Settings.json`); the flat view therefore
gets its own remembered sort order, which is desirable (sorting by `Modified`
is the common use).

## Alternatives

- A custom pane/view implementation was rejected because it would duplicate
  sorting, filtering, columns, selection, and file-operation behavior.
- Materializing search results into an unrelated temporary directory model was
  rejected because URLs and mutation notifications would lose their natural
  semantics.
- A `flat://` filesystem was selected because it reuses the existing model and
  command architecture while preserving underlying `file://` identities.
- Following junctions or symbolic links was rejected because it can create
  cycles and escape the selected tree.
- Assigning Total Commander's `Ctrl+B` shortcut was rejected because Favorites
  already owns that binding. Flat View remains available through the Command
  Center and custom key bindings.

## Runtime Effects

- Normal directory panes are unaffected until Flat View is activated.
- Traversal runs through the existing model worker and is bounded by
  `max_entries`; rows retain normal lazy loading behavior.
- Breadth-first traversal stores pending directories and yielded relative paths
  proportional to the visited tree.
- Junctions, directory symlinks, and archive contents are never traversed.
- Leaving Flat View destroys the `flat://` model and returns to the normal
  directory listing; no recurring background task remains.

## Settings

`Core Settings.json`:

```json
{
  "flat_view": {
    "max_entries": 100000,
    "include_directories": false
  }
}
```

`max_entries` bounds traversal; when reached, `iterdir` stops and the command
shows `Flat view limited to the first 100,000 entries.` `include_directories`
adds directories as entries (still not descended into when they are links).
Invalid values fall back to defaults.

## Implementation Steps

1. Move the `os.scandir` traversal from `SearchFileFuzzy` into
   `core/fs/flat.py`; update the plug-in import and keep its tests green.
2. Implement `FlatFileSystem` (read operations, `resolve`, `name`) and register
   the `flat://` scheme with Core.
3. Delegate mutating operations to `file://` and emit notifications on the
   flat URLs.
4. Extend `_hidden_file_filter` for `flat://` and prune hidden directories in
   traversal when the pane hides hidden files.
5. Add `ToggleFlatView`, the `GoUp` handling, and the location bar marker.
6. Add settings, README, and changelog.

## Tests

Required focused commands from the repository root with the repository test
`PYTHONPATH`:

```powershell
python -m unittest core.tests.fs.test_flat
python -m unittest fman_unittest.test_search_file_fuzzy
python -m unittest fman_integrationtest.impl.test_flat_view
```

Unit tests (`core/tests/fs/test_flat.py`, temp directories):

- Breadth-first listing with relative POSIX paths; directories excluded by
  default and included with the setting.
- **An archive inside the tree is listed once as a file and its contents are
  not listed**, both for `.zip` and for a nested `.7z`.
- Hidden file and hidden directory pruning.
- Directory symlink and junction are not followed.
- `max_entries` truncation flag.
- `resolve` maps to the `file://` URL; `size_bytes`/`modified_datetime` match
  the underlying file.
- `delete`/`move` through the flat URL changes the underlying file and emits
  `file_removed`/`file_added` on the flat URLs.
- `ToggleFlatView` cursor placement in both directions.

Integration: entering and leaving the flat view from a pane, `Enter` on an
archive entry inside the flat view, sort order remembered per scheme.

## Acceptance Criteria

- Toggling is per pane, reversible, and restores the cursor sensibly.
- Flat View has no default shortcut; `Ctrl+B` remains assigned to Favorites.
- Archives never expand inside the flat view; they are single, openable
  entries.
- Hidden-file state, sorting, columns, status bar, and file operations work
  in the flat view without special cases outside `core/fs/flat.py` and the
  two Core commands.
- Large trees stay responsive: traversal is bounded and rows load lazily as in
  the normal view.
- `SearchFileFuzzy` behaviour is unchanged after the traversal moves to Core.

## Reviewers

### 2026_09_12 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context window: Not exposed by host
- Outcome: Initial `flat://` filesystem design created with bounded traversal
  and existing pane behavior reused.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: Low
- Context window: Not exposed by host
- Outcome: Reserved `Ctrl+B` for Favorites, left Flat View without a default
  shortcut, and replaced full-suite validation with focused test commands.
