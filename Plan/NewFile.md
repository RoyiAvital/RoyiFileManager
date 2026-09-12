# New File

## Task

Add a bundled `NewFile` plug-in with a Command Center command `New Empty
File` that creates an empty file in the active pane's current directory. The
user is prompted for the name; the default suggestion is derived from the
file under the cursor with the extension preselected, as other Core prompts
do. After creation the cursor is placed on the new file. The editor is *not*
opened.

Motivation: Core's `CreateAndEditFile` (`Shift+F4`, aliases `New file`,
`Create file`) always launches the configured editor. Users frequently want
only a placeholder (`.gitkeep`, `notes.txt`, an empty `__init__.py`) without
an editor round trip, matching Explorer's "New → Text Document" and Total
Commander's `Shift+F4` followed by closing the editor.

## Scope

Included:

- One `DirectoryPaneCommand`: `new_empty_file`, aliases `New empty file`,
  `Create empty file`, `Touch`.
- Name prompt with default and extension preselection; support for a
  relative sub-path (`docs/readme.md`) creating missing parent directories,
  mirroring `CreateDirectory`.
- Handling of existing files, permission errors, filesystems that do not
  support `touch`, and invalid Windows names.
- Cursor placement on the created file; the pane model updates through the
  existing `notify_file_added` path.
- Optional default key binding `Ctrl+N` (free in all bundled binding files).

Excluded:

- Templates or non-empty content, multiple files at once, timestamps update
  of existing files (`touch` semantics on an existing file), and changes to
  `CreateAndEditFile`.
- Changes to the public `fman` plug-in API.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
plug-in can be removed without affecting Core. The new alias set does not
overlap Core's `CreateAndEditFile` aliases, so the palette shows both
commands unambiguously.

## Design

Plug-in layout `Plugins/NewFile/`:

- `new_file/__init__.py` — the command.
- `Key Bindings (Windows).json` — `Ctrl+N` → `new_empty_file`.
- `README.md`.

No settings file: there is nothing to configure.

Command `NewEmptyFile(DirectoryPaneCommand)`:

1. Determine the default name: if the file under the cursor is not a
   directory, use its `basename`; otherwise `''`. Preselect up to the
   extension start using Core's `_find_extension_start` behaviour (import
   `core.commands._find_extension_start`; plug-ins may depend on Core). This
   is the same logic as `CreateAndEditFile` so the two prompts feel
   identical.
2. `show_prompt('New empty file:', default, selection_end=ext_start)`.
   Cancel or empty name → return without side effects.
3. Normalize: on Windows replace `\` with `/` so `sub\name.txt` becomes a
   relative URL path; `join(self.pane.get_path(), name)`. Reject names whose
   final component is empty or `.`/`..`, contains characters invalid on
   Windows (`<>:"|?*`, control characters) or ends with a space/dot, with a
   `show_alert` message. Validate before touching the filesystem so no
   partial parent directories are created.
4. If a parent component is missing, `makedirs(dirname(url))` (Core
   `fman.fs.makedirs`, `exist_ok=True`).
5. If `exists(url)`: `show_alert('%s already exists.' % name)` and place the
   cursor on the existing entry if it is in the current directory. Do not
   modify the existing file (no timestamp update).
6. `touch(url)` via `fman.fs.touch`. `PermissionError` → alert `You do not
   have enough permissions to create <path>.`; `NotImplementedError` → alert
   `Creating files is not supported here.`; other `OSError` → alert with
   `strerror`.
7. Place the cursor on the first path component of the created path relative
   to the pane (`relpath(normalize(url), base_url).split('/')[0]`), exactly
   as `CreateDirectory` does, so creating `docs/readme.md` selects `docs`.
   `ValueError` (hidden file, filter) is ignored.

`is_visible()` mirrors `CreateDirectory`: `True` only when the pane's scheme
implements `touch` (reuse `core.commands._fs_implements(scheme, 'touch')`).
This hides the command on `drives://`, `network://`, and `null://`.

Threading: runs in the command thread like every plug-in command;
`show_prompt`, `show_alert`, `place_cursor_at` are already main-thread safe.
`LocalFileSystem.touch` emits `notify_file_added`, which updates the pane
model through the existing worker path.

## Alternatives

- **Adding an `edit=False` argument to Core's `CreateAndEditFile`** — a
  smaller change, but it modifies Core behaviour that upstream plug-ins may
  key-bind, and the palette would still show one entry. Rejected in favour of
  a separate, removable plug-in; the shared helpers are imported instead of
  duplicated.
- **Creating `New Text Document.txt` without a prompt (Explorer style)** —
  rejected: the request is to let the user name the file, and a follow-up
  rename costs the same keystrokes as the prompt.
- **Opening the editor optionally after creation** — rejected: that is
  exactly `Shift+F4`.
- **`Shift+F7`/`Alt+F7` bindings** — rejected: `Alt+F7` is reserved by the
  Search File Content plan; `Ctrl+N` is free and conventional.

## Runtime Effects

- Startup: registers one command and one key binding; no timers, threads,
  I/O or settings reads.
- Steady state: zero cost until invoked. One invocation performs at most one
  `exists`, an optional `makedirs`, and one `touch`, all through the cached
  `MotherFileSystem`.
- Disabled/no-op path: not applicable — the plug-in has no background
  behaviour to disable; removing the plug-in directory removes the command.

## Settings

Not applicable — the command has no configurable behaviour. The key binding
can be changed through the standard user `Key Bindings.json`.

## Implementation Steps

1. Create `Plugins/NewFile/new_file/__init__.py` with `NewEmptyFile`,
   name validation, and `is_visible`.
2. Add `Key Bindings (Windows).json` (`Ctrl+N`) and `README.md`.
3. Register the plug-in directory in `build.py`'s bundled plug-in list and
   in `RoyiFileManager.spec`.
4. Unit tests (see below).
5. Changelog entry under `Unreleased / Added`; add `Ctrl+N` to the main
   README shortcut list.

## Tests

Required final command from the repository root:

```powershell
python build.py test
```

Unit tests (`src/unittest/python/fman_unittest/test_new_file.py`, `Mock`
pane, patched `show_prompt`/`show_alert`/`touch`/`exists`/`makedirs`):

- Default name and `selection_end`: file under cursor `report.tar.gz` →
  default `report.tar.gz`, selection ends before `.tar.gz`; directory under
  cursor → `''`; no cursor → `''`.
- Cancelled prompt and empty name create nothing and show no alert.
- Plain name: `touch` called with `join(pane_path, name)`,
  `place_cursor_at` called with that URL.
- Relative sub-path `docs\readme.md` on Windows: `makedirs` called for
  `docs`, `touch` for `docs/readme.md`, cursor placed on `docs`.
- Existing file: `touch` not called, alert shown, cursor placed on the
  existing entry.
- Invalid names (`con:`, `a?b`, `name.`, `..`, empty final component):
  alert shown, neither `makedirs` nor `touch` called.
- `PermissionError`, `NotImplementedError`, generic `OSError` from `touch`
  each produce the documented alert and no traceback.
- `is_visible()` is `True` for `file://` and `False` for `drives://` and
  `null://` (patched `_fs_implements`).

Integration (temp directory, real `LocalFileSystem` through the existing
plug-in test harness): the command creates a zero-byte file, the pane model
lists it, and a second invocation with the same name leaves the file's
mtime unchanged.

Manual: `Ctrl+N` from the palette and from the binding; the prompt shows the
extension preselected; the created file is under the cursor.

## Acceptance Criteria

- `New Empty File` appears in the Command Center and on `Ctrl+N`, prompts for
  a name, creates a zero-byte file in the active pane's directory, and places
  the cursor on it.
- The editor is never launched; `Shift+F4` behaviour is unchanged.
- Existing files are never modified; invalid names and permission problems
  produce an alert, not a traceback.
- Relative sub-paths create the missing directories first.
- The command is hidden on filesystems without `touch` support.
- No background work exists; the public `fman` API is unchanged.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Initial design created as a separate plug-in reusing Core prompt
  and validation helpers; distinguished from Core's `CreateAndEditFile`
  (`Shift+F4`), which always opens the editor.
