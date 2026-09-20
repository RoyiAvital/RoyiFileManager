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
- Flat View lists files only. Directories, including empty directories and
  directory links, never appear as rows; there is no option to show them.
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
- The flat state is saved separately alongside the pane's root location and
  restored on restart; it does not change the root or file URL scheme.

## Scope

This task adds a reversible flat listing for local directory trees, including
normal pane sorting, selection, file operations, hidden-file behavior, and
session restoration. Directory rows and a folder-display option are excluded.
Archive contents, remote schemes, following directory links, and unbounded
traversal are excluded from the first version.

Compatibility: preserves the existing public `fman` plug-in API from fman 1.7.5
and adds `DirectoryPane.get_listing_mode()` and
`DirectoryPane.on_listing_mode_changed(callback)`. Existing signatures and URL
contracts are unchanged. These are planned, backward-compatible additions,
not APIs already available in the application.

### Feature Parity Requirement

Flat View changes how a local tree is listed, not which regular-pane features
are available. Existing commands, plug-ins, columns, filters, selection, file
operations, clipboard/drag and drop, archive opening, search, hashing, status
and navigation must retain their normal behavior for the underlying files.
Pane-scoped operations use the real root; item-scoped operations use each real
file. Folder-targeted operations require normal view because folders cannot be
selected in Flat View. Creating a folder remains a pane-scoped action at the
root, but the empty folder does not appear as a row. Any other necessary
difference must be explicit and approved, not a silent disabled command or an
assumed exception.

The public mode contract below is approved for the design. The remaining
listing architecture is not implementation-ready; the 2026_09_17 review records
the compatibility blockers and recommended revision.

## Design

### Public Pane Mode API

Add two methods to [DirectoryPane](../src/main/python/fman/__init__.py), keeping
Qt objects and signals private to the host:

| Method | Contract |
| --- | --- |
| `pane.get_listing_mode()` | Return `'normal'` for an ordinary directory listing or `'flat'` for the recursive files-only listing. |
| `pane.on_listing_mode_changed(callback)` | Register a no-argument callback for this pane's committed mode changes; return an idempotent unsubscribe function. |

- The host owns the mode per pane. `get_path()` remains the real root URL and
  selection/cursor getters return real item URLs (`file://` for local files).
  Mode is independent of filesystem scheme: an ordinary archive pane is
  `'normal'`. Plug-ins must not inspect URL prefixes to infer Flat View.
- The getter reads current committed state, not a pending toggle or a scan's
  completion state. A callback runs after the new mode is readable. If navigation
  changes both root and mode, commit both before either path or mode notification.
- Notify once for each actual transition, including returning to normal listing
  through navigation. Do not notify for a no-op, rejected transition, sort,
  filter, selection, reload that retains the mode, or arriving scan batches.
  A mode-only transition is not a path change. Stale worker results cannot
  change the mode or emit notifications.
- Follow the [path subscription contract](../PlugIn.md): no
  callback on registration; read the getter for initial state. Getter,
  registration and unsubscription can be called on the UI thread or a command
  worker; worker calls dispatch synchronously to the UI thread. Callbacks run
  on the UI thread and must be fast. Do not hold locks needed by that thread
  while making these calls.
- Reject a non-callable callback with `TypeError`. Getter and registration
  require a live pane; otherwise raise `RuntimeError`. Pane destruction stops
  delivery without a synthetic mode change. Unsubscription remains safe after
  destruction and prevents later delivery, including queued callbacks.
  Plug-ins unsubscribe when their tool closes or unloads, as with path callbacks.
- These are read-only hints, not a mode setter or a requirement that every
  plug-in branch on mode. Existing commands must continue operating on real
  files. New plug-ins targeting older hosts may feature-detect the methods.
  Do not change existing `DirectoryPaneListener` hook signatures.

### Previous Filesystem Sketch (Needs Revision)

The original sketch below is retained as context, not as implementation
approval. Its synthetic URLs and URL-keyed mode persistence are superseded by
the pane-owned mode and real-URL contract above. The listing, notification,
presentation and persistence implementation still needs the earlier review's
revision before coding; adding the two methods alone does not resolve it.

The original proposal was a filesystem scheme, `flat://`, in Core
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
  and not `is_junction()`/directory symlink. Directories are traversal inputs
  only, never yielded rows. Archives are regular files at the filesystem level,
  so they are leaves by construction; add an explicit test so a future
  "browse archives" feature cannot regress this.
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

- Inferring mode from `flat://` URLs is rejected for the approved public
  contract: it breaks local-file assumptions and confuses identity with display.
  Polling pane state is unnecessary; an explicit query and disposable change
  subscription follow the existing public pane API pattern.
- Including directory rows, even optionally, was rejected: files-only selection
  avoids selecting both a parent directory and its descendants for an operation
  and removes an unnecessary setting and test branch.
- A custom pane/view implementation was rejected because it would duplicate
  sorting, filtering, columns, selection, and file-operation behavior.
- Materializing search results into an unrelated temporary directory model was
  rejected because URLs and mutation notifications would lose their natural
  semantics.
- A `flat://` filesystem was the original selection, but its externally visible
  URL changes are superseded by the approved real-URL contract. Reusing the
  pane/model remains the goal; recursive listing ownership still needs revision.
- Following junctions or symbolic links was rejected because it can create
  cycles and escape the selected tree.
- Assigning Total Commander's `Ctrl+B` shortcut was rejected because Favorites
  already owns that binding. Flat View remains available through the Command
  Center and custom key bindings.

## Runtime Effects

- Normal directory panes are unaffected until Flat View is activated.
- Mode queries and subscriptions add no filesystem I/O, polling, timers, scans
  or background jobs. Memory is one mode value per pane plus registered
  callbacks; delivery work is proportional to subscribers only on a transition.
  With no subscribers, there are no plug-in callbacks. Session persistence
  stores the mode separately from the root URL.
- Traversal runs through the existing model worker and is bounded by
  `max_entries`; rows retain normal lazy loading behavior.
- Breadth-first traversal stores pending directories and yielded relative paths
  proportional to the visited tree.
- Files-only rows reduce row metadata and display work, but directories must
  still be inspected and queued; traversal limits and cancellation remain needed.
- Junctions, directory symlinks, and archive contents are never traversed.
- Leaving Flat View stops its recursive listing and returns to the normal
  directory listing; no recurring background task remains. The approved API
  reports `'normal'` once the mode transition commits.

## Settings

`Core Settings.json`:

```json
{
  "flat_view": {
    "max_entries": 100000
  }
}
```

`max_entries` bounds traversal; when reached, `iterdir` stops and the command
shows `Flat view limited to the first 100,000 entries.` Invalid values fall
back to the default. Files-only listing is fixed behavior, not a setting.

## Implementation Steps

First revise the previous filesystem sketch to honor the approved pane-mode
and real-URL contracts. Its enumeration/mutation steps below are provisional.

1. Move the `os.scandir` traversal from `SearchFileFuzzy` into
   `core/fs/flat.py`; update the plug-in import and keep its tests green.
2. Implement files-only `FlatFileSystem` (read operations, `resolve`, `name`)
  and register the `flat://` scheme with Core.
3. Delegate mutating operations to `file://` and emit notifications on the
   flat URLs.
4. Extend `_hidden_file_filter` for `flat://` and prune hidden directories in
   traversal when the pane hides hidden files.
5. Add `ToggleFlatView`, the `GoUp` handling, and the location bar marker.
6. Add the two public `DirectoryPane` methods and host-owned transition
  delivery, with focused query, lifecycle, threading and compatibility tests.
7. Add settings, README, changelog and the new method contracts in
  [PlugIn.md](../PlugIn.md) when implemented. Do not publish proposed methods
  in the implemented API reference before they exist.

## Tests

The original sketch's proposed test commands below include modules not yet
implemented. Before implementation, replace them with verified focused
`build._environment()` launchers as requested in the architecture review:

```powershell
python -m unittest core.tests.fs.test_flat
python -m unittest fman_unittest.test_search_file_fuzzy
python -m unittest fman_integrationtest.impl.test_flat_view
```

Unit tests (`core/tests/fs/test_flat.py`, temp directories):

- Breadth-first listing with relative POSIX paths; directories are always
  excluded, including empty directories and directory links. Nested files
  remain listed and no folder-display setting exists.
- Creating an empty folder adds no row; files later created inside it appear
  on the next listing, subject to the normal hidden-file and traversal rules.
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

Public pane-mode API tests (required additions to existing pane/Qt coverage):

- Initial mode is `'normal'`; entering and leaving Flat View reports the correct
  mode independently in two panes. Ordinary archive panes remain `'normal'`.
  Session restoration exposes the restored mode without changing real URLs.
- A registered callback receives no arguments, runs exactly once per committed
  transition on the UI thread and can read the committed mode and current root.
  Registration itself does not call back. No-op/failed transitions, reload,
  sorting, filtering, selection and scan batches emit no mode notification.
- A mode-only toggle leaves `get_path()` unchanged and does not emit a path
  change. Navigation that exits Flat View reports the committed new path and
  `'normal'`; existing path notification contracts remain intact.
- Worker-thread getter/registration/unsubscription dispatch safely. Repeated
  unsubscribe, unsubscribe during delivery, queued delivery after unsubscribe,
  pane destruction and tool/unload cleanup cannot call an inactive subscriber.
  Invalid callbacks and getter/registration on a closed pane raise the specified
  errors. No late worker result can resurrect a closed or superseded mode.
- Existing plug-ins need no new method calls to operate on listed files; the
  root, selected-file and cursor APIs return canonical real URLs. Keep existing
  signatures and listener hooks compatible. Query/subscribe and unused mode
  paths cause no feature-specific I/O or background work.

## Acceptance Criteria

- Flat View always lists files only, with no folder-display option. Existing
  operations on listed files retain regular-pane behavior.
- The two documented public methods expose per-pane mode with the specified
  thread and subscription lifecycle guarantees. Existing API callers keep real
  URLs and require no migration; the hint does not excuse parity regressions.
- Toggling is per pane, reversible, and restores the cursor sensibly.
- Flat View has no default shortcut; `Ctrl+B` remains assigned to Favorites.
- Archives never expand inside the flat view; they are single, openable
  entries.
- Hidden-file state, sorting, columns, status bar, and file operations retain
  their behavior. Host-owned listing changes and the two public method additions
  must be covered by the compatibility matrix before implementation approval.
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

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Needs design revision before implementation. The user requires
  regular-pane feature parity. The current `flat://` design does not preserve
  local URL contracts, root-relative presentation, mutation notifications or
  per-pane traversal policy automatically. No application code changed.

#### Findings

1. **P1: a synthetic scheme disables existing local-file features.**
   [CalculateFileHash](../src/main/resources/base/Plugins/CalculateFileHash/calculate_file_hash/__init__.py#L78)
   checks both pane and item URLs for `file://`;
   [SearchFileContent](../src/main/resources/base/Plugins/SearchFiles/search_files/__init__.py#L90)
   and [directory size](../src/main/resources/base/Plugins/Core/core/directory_size/__init__.py)
   also gate on local URLs. These callers do not first call `resolve()`.
   [DragAndDrop](../src/main/python/fman/impl/model/drag_and_drop.py)
   exports row URLs directly as MIME URLs, so external interoperability also
   requires real local identities. Updating a few bundled commands would not
   establish compatibility with existing third-party plug-ins.
2. **P1: filesystem identity lacks the presentation root.**
   `flat://C:/root/sub/report.txt` is the same item URL whether the flat root
   is `C:/root` or `C:/root/sub`, but its displayed relative name must differ.
   [Name.get_str](../src/main/resources/base/Plugins/Core/core/__init__.py#L22)
   receives only the item URL. A scheme-wide current-root variable would mix
   two panes and overlapping roots; the proposed `name(path)` cannot supply
   both presentations without an additional pane-owned context.
3. **P1: nested mutations do not work with the unchanged model.**
   [FileWatcher](../src/main/python/fman/impl/model/file_watcher.py#L41)
   accepts only direct children. The
   [model mutation methods](../src/main/python/fman/impl/model/model.py#L405)
   assert the same relationship, and
   [MotherFileSystem](../src/main/python/fman/impl/plugins/mother_fs.py)
   updates direct-parent listing caches. Emitting nested `flat://` notifications
   is insufficient. Membership, nested directory changes, rename selection and
   updates from the other pane need a shared, tested listing contract.
4. **P2: traversal and per-pane ownership are underspecified.**
   [Model._initialize](../src/main/python/fman/impl/model/model.py#L93)
   finishes enumeration before publishing initial rows; lazy metadata loading
   is not progressive tree listing. The proposed reused
   [indexer](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/indexer.py#L30)
   collects a complete result and has no cancellation input. Its entry budget
   counts inspected entries, not just results. Cancellation, partial errors,
   limits and progress need explicit ownership. `iterdir(root)` also has no
   pane-hidden-state input and is cached by URL: two panes at one root with
   different hidden settings must not share a pruned listing accidentally.

#### Recommended Revision

- Model Flat View as a **per-pane listing mode**, retaining `file://` for the
  root and every row exposed to commands/plug-ins. Store the mode separately
  in pane/session state rather than encoding it in a filesystem URL.
- Reuse the existing pane, table, columns and command pipelines. Introduce the
  smallest internal listing abstraction needed for recursive membership,
  per-pane root-relative presentation, change handling and cancellable scans.
  Regular mode must retain direct-child behavior without new background work.
- Separate displayed relative paths from editable basenames and operation
  URLs. Specify duplicate-basename conflicts, incoming copy/move/new-item
  destinations, parent navigation, history/Favorites/sync restoration and
  overlapping directory/file selections when directories are included.
- Replace the narrow smoke checklist with a parity matrix exercised in normal
  and flat panes: selection/filter/sort/custom columns; copy/move/rename/delete;
  clipboard and internal/external drops; new file/folder; pack/unpack/archive
  opening; hashing/search/directory sizes; hidden-state changes; two-pane
  notifications; status; reload; cancellation; history and restart persistence.
  Current exclusions concern recursive enumeration, not permission to disable
  operations that already work on a listed file.
- Use verified `build._environment()` launchers for focused tests; the proposed
  new test modules do not exist yet. Do not expand public APIs or promise
  arbitrary third-party direct-child assumptions work unchanged without review.

#### Review Validation

- Read-only runtime probe using `build._environment()` confirmed three existing
  contracts: `CalculateFileHash.is_visible` is false for a flat pane/item;
  `FileWatcher._is_in_root` rejects a nested flat URL; and two overlapping roots
  produce the same item URL but different `relpath` values.
- Source review covered pane getters, column naming, model initialization and
  mutations, filesystem caches, drag/drop, hidden filters and the local indexer.
- No application tests, full suite, build or implementation were run. These
  findings assess the proposed design, not an implemented Flat View.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: The current design lists files by default and offers
  `include_directories`. The user is comfortable with files only; recommend
  omitting folder rows and that option in the first version. This avoids
  overlapping parent/descendant selections during copy, move and delete.
  Subdirectories are still traversed, archives remain individual file entries,
  and regular operations on listed files must retain parity. Folder-targeted
  operations require returning to normal view; pane-scoped actions such as
  creating a folder can still use the real root, though an empty new folder
  would not appear in Flat View. This is a recommendation, not an implemented
  change or resolution of the preceding architecture blockers.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: User approved files-only Flat View with no folder-display option.
  Removed the option from operative behavior, settings and tests; aligned scope,
  traversal, alternatives, runtime effects and acceptance criteria. Directories
  remain traversal inputs, archives remain file rows, and existing file operations
  retain parity. This reduces selection and testing complexity, but does not
  resolve the previously identified URL, notification and scan-lifecycle design
  blockers. Prior reviewer records are preserved; no application code changed.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: User approved adding `get_listing_mode()` and
  `on_listing_mode_changed(callback)` to the design. Specified normal/flat values,
  committed-state notifications, UI-thread dispatch, unsubscribe/destruction
  behavior, read-only scope and backward-compatible real URLs. Added runtime,
  implementation and test requirements; marked the conflicting original scheme
  sketch as needing revision. Existing architecture blockers remain open.
  No public API implementation, API reference or changelog changes in this pass.
