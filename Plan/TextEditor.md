# Text Editor

Status: Revised design, not implemented. This revision replaces the earlier
built-in QScintilla editor service with two wizards that integrate external
programs: one for the text **editor** (`F4`) and one for the text **viewer**
(`F3`). The user directed the change: no embedded viewer or editor; guided
setup for Notepad++, CudaText, Textadept, or a user-defined program, with the
read-only launch command derived automatically for the three known editors.

## Task

Let the user choose two programs once: an editor with advanced editing features
for `F4`, and a fast viewer with a read-only mode for `F3`. They may be the same
program or different ones. Each wizard guides the choice for its role, derives
the launch command from the executable for the three known editors, and asks a
user-defined program for its arguments.

### Current Behavior

Core already has a minimal editor picker in `OpenWithEditor._get_editor()`
([commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)):

- `F4` (`open_with_editor`) and `Shift+F4` (`create_and_edit_file`) read the
  `editor` dictionary from `Core Settings.json`, a Popen keyword mapping such as
  `{"args": ["C:\\...\\editor.exe", "{file}"]}`; `{file}` is replaced through
  `strformat_dict_values` and launched with `Popen(**kwargs)`.
- If `editor` is missing, or `args[0]` no longer exists, an OK/Cancel alert
  (`Editor is currently not configured. Please pick one.` or `Could not find
  your editor. Please select it again.`) leads to a native open dialog rooted at
  Program Files with an `Applications (*.exe)` filter. The result is stored as
  `{"args": [<exe>, "{file}"]}` through `get_popen_kwargs_for_opening` and saved.
- There is no viewer command, no read-only mode, no preset knowledge, no
  argument editing, no executable validation, and a Popen failure surfaces as a
  plug-in traceback. A directory under the cursor is handed to the editor.
- `Open with...` maintains a separate `Apps.json`/`File Associations.json`
  picker for arbitrary applications; it is not an editor configuration.

## Scope

Included:

- Core command `view_file` (`F3`, aliases `View`, `View file`) launching the
  configured viewer command; `open_with_editor` (`F4`) and `create_and_edit_file`
  (`Shift+F4`) keep their identifiers and launch the configured editor command.
- Core commands `configure_text_editor` (`Configure text editor`, `Choose text
  editor`) and `configure_text_viewer` (`Configure text viewer`, `Choose text
  viewer`). Each runs at any time from the Command Center; `F4`/`Shift+F4` run
  the editor wizard and `F3` runs the viewer wizard automatically when their own
  setting is missing or invalid.
- Presets: Notepad++, CudaText, Textadept, and User defined. The editor wizard
  derives Edit arguments and the viewer wizard derives read-only View arguments
  from the executable path; the user-defined preset prompts for one argument
  line per wizard. The viewer wizard offers `Same as editor` when an editor is
  configured; the editor wizard offers to reuse the choice as viewer.
- Best-effort executable detection for presets from well-known install
  locations and `PATH`, confirmed by the user, with a browse fallback.
- Settings stored in `Core Settings.json` under `UserSettings`; existing `editor`
  configurations keep working.
- Local `file://` files only. Directories and other schemes are refused with a
  short alert, as today for non-local URLs.

Excluded:

- Any embedded viewer/editor, QScintilla, syntax highlighting, save handling,
  find/replace, or editor windows owned by RoyiFileManager.
- Jump-to-line, multiple files per launch, per-extension editors, editor
  process tracking, waiting for the editor to exit, or reloading panes on save.
- File-type or binary detection. `F3`/`F4` are text-oriented and hand any
  local file to the configured viewer/editor; the user is assumed to know what
  they are opening. Images and other non-text files belong to `Open with...`
  (`Apps.json` / `File Associations.json`) or `Enter`.
- Non-Windows presets, Registry lookups, and downloading editors.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. Command
identifiers `open_with_editor` and `create_and_edit_file` and the `editor`
settings shape are unchanged; `viewer`, `editor_preset`, and `viewer_preset` are
additive keys. `F3` is a new default binding (currently unassigned in Core and
bundled plug-ins); user overrides in `Key Bindings.json` continue to win.

## Design

### Ownership

Everything lives in the Core plug-in beside the existing editor code:

- `core/commands/__init__.py`: `ViewFile`, `OpenWithEditor`, `CreateAndEditFile`,
  `ConfigureTextEditor`, `ConfigureTextViewer`, and one shared
  `_launch_program(url, role, pane)` helper that replaces `_get_editor()`.
- `core/text_editor.py` (new, pure Python, no Qt): preset table with per-role
  guidance text, executable detection, command derivation, settings validation,
  and `{file}` expansion. One `run_wizard(role, ui, settings)` function drives
  both wizards; the role (`editor` or `viewer`) selects titles, list order,
  descriptions, argument template, and the settings keys. Unit-testable with a
  stub UI, as the existing `StubUI` tests do.
- Dialogs use only the existing public API: `show_quicksearch`,
  `show_file_open_dialog`, `show_prompt`, `show_alert`, `show_status_message`.
  No host changes, no `fman.ui` window, no new UI element.

### Presets

| Preset | Executable detection candidates (first existing wins) | Edit arguments | View arguments |
| --- | --- | --- | --- |
| Notepad++ | `%ProgramFiles%\Notepad++\notepad++.exe`, `%ProgramFiles(x86)%\Notepad++\notepad++.exe`, `notepad++.exe` on `PATH` | `["{file}"]` | `["-ro", "{file}"]` |
| CudaText | `%LocalAppData%\Programs\CudaText\cudatext.exe`, `%ProgramFiles%\CudaText\cudatext.exe`, `cudatext.exe` on `PATH` | `["{file}"]` | `["-r", "{file}"]` |
| Textadept | `%ProgramFiles%\Textadept\textadept.exe`, `%LocalAppData%\Programs\Textadept\textadept.exe`, `textadept.exe` on `PATH` | `["{file}"]` | `["-r", "{file}"]` |
| User defined | Browse only | Prompted; default `["{file}"]` | Prompted; default `["{file}"]` |

Role guidance shown as QuickSearch item descriptions (hint = detected path or
`Not found - browse`):

| Preset | Editor wizard description | Viewer wizard description |
| --- | --- | --- |
| Notepad++ | Full-featured: plugins, macros, multi-editing, tabs and sessions | Read-only tab (`-ro`) in the running instance |
| CudaText | Multi-carets, 300+ lexers, Python plugins, LSP add-on | Fast startup, read-only mode (`-r`), portable |
| Textadept | Minimalist, Lua-scriptable, very light | Very light, read-only mode (`-r`), portable |
| Same as editor | (not offered) | `<preset>` opened read-only, when its read-only switch is known |
| User defined | Any editor; you enter the command arguments | Any program; enter arguments including its read-only switch, if it has one |

List order carries the recommendation: the editor wizard lists Notepad++,
CudaText, Textadept, User defined; the viewer wizard lists Same as editor (when
available), CudaText, Textadept, Notepad++, User defined. The initial highlight
is the currently saved preset for that role, else the first item.

Verified against upstream documentation during planning:

- Notepad++ `-ro` marks the opened `filepath` read-only. `-multiInst`/`-nosession`
  are not added by default: users who prefer a separate viewer window can edit
  the arguments.
- CudaText `-r` opens files read-only and is honored by the single-instance
  activation path.
- Textadept View uses `-r {file}` as directed by the user. The Textadept 13.1
  manual does not list `-r`, so step 1 must confirm it on the installed version.
  If it is not accepted, the fallback is `{file} -e "buffer.read_only = true"`:
  `-e <code>` runs Lua in the single running instance as if typed in its
  command entry, which the manual suggests for a read-only mode; the file must
  precede `-e` so `buffer` is the just-opened file. If neither works, the preset
  degrades to View = Edit with a note in the confirmation.
- Textadept on Windows only opens filenames representable in the system code
  page; the preset description mentions it so the limitation is not reported as
  a RoyiFileManager bug.

Detection reads `os.environ` and `shutil.which`; it never touches the Registry.
CudaText and Textadept are portable applications that are often unpacked to
arbitrary folders, so a missed detection is expected and just skips to Browse.

### Wizard Flow

Both wizards run on the command worker and chain blocking dialogs, like `Open
with...` does today. They differ only in role text, list order, argument
template, and the keys they save.

**Intro (auto-triggered only).** When `F4`/`Shift+F4` or `F3` start a wizard
because the setting is missing or invalid, one `OK | CANCEL` alert replaces
today's `Editor is currently not configured. Please pick one.`:

- Editor: `No text editor is configured. Choose an editor with the editing
  features you want: plugins, multi-carets, macros. It is used by F4.`
- Viewer: `No text viewer is configured. Choose a program that starts fast and
  can open files read-only. It is used by F3.`
- Invalid existing setting: the same text prefixed by `Could not find
  <basename>.` Cancel returns without saving. Running a wizard from the Command
  Center skips the intro. With a valid setting, `F3`/`F4` launch immediately
  and show no dialog at all; the intro appears only on the one press that
  starts a wizard.

**Step 1 - Choose.** `show_quicksearch` over the role's preset list with the
descriptions above. Escape cancels without saving.

**Step 2 - Locate.** Skipped for `Same as editor`. If a preset path was
detected, `show_alert` `Use <path>?` with `YES | NO`; No or no detection opens
`show_file_open_dialog` (`Pick <preset>`, initial directory from the first
existing candidate parent or Program Files, filter `Applications (*.exe)`). An
empty result cancels.

**Step 3 - Arguments (User defined only).** One prompt per wizard:

- Editor: `show_prompt('Edit command arguments:', '{file}')`.
- Viewer: `show_prompt('View command arguments (add the read-only switch if
  the program has one):', '{file}')`.

Arguments are split with `shlex.split(posix=False)`; a missing `{file}` is
appended as the last argument and reported in the confirmation. Cancel aborts
without saving.

**Step 4 - Confirm and save.** One `OK | CANCEL` alert shows the resulting
command line (`Edit: <exe> {file}` or `View: <exe> -ro {file}`). OK writes the
role's two keys (`editor` + `editor_preset`, or `viewer` + `viewer_preset`) with
`save_json` and shows `Text editor: <preset> (<basename>)` or `Text viewer: ...`
in the status bar.

**Step 5 - Link (editor wizard only).** If no valid `viewer` exists and the
chosen preset has a known read-only switch, ask `Also use <preset> as the text
viewer (opened read-only with -ro)? YES | NO`. Yes derives and saves `viewer` +
`viewer_preset` from the same executable; No leaves the viewer for `F3` to ask
later. A user-defined editor skips this step because its read-only arguments
are unknown.

**Same as editor (viewer wizard).** Offered only when `editor` is valid and
`editor_preset` is a known preset; it reuses `editor.args[0]` with that preset's
View arguments and jumps to Step 4. A user-defined editor is not offered as
`Same as editor`; the user picks `User defined` and enters View arguments,
prefilled with the editor's arguments so the common case is one Enter.

Neither wizard launches a program. After a successful auto-triggered run the
original command continues with the new settings; a canceled wizard returns
silently, as the current picker does.

### Launch Behavior

`_launch_program(url, role, pane)`:

- `_validated_settings(role)` returns the role's Popen mapping or `None` when
  the key is missing, `args` is not a non-empty list of strings, or `args[0]`
  is not an existing file. `None` runs that role's wizard (with intro) and
  retries once.
- Resolve the URL as `OpenWithEditor` does now; non-`file://` schemes show the
  existing `Editing files from <scheme> is not supported...` alert (`Viewing`
  for `F3`). A directory shows `<name> is a folder.` and returns; a missing
  file shows `<name> no longer exists.`.
- Expand `{file}` with `strformat_dict_values` on a copy of the stored mapping;
  the native path comes from `as_human_readable`. Braces in filenames are safe
  because expansion formats the argument templates, not the path.
- `Popen(args, cwd=dirname(path))`, no shell. `OSError` (missing executable,
  access denied) shows `Could not start <exe>: <strerror>. Run "Configure text
  editor" to fix it.` (`viewer` for `F3`) instead of a traceback.
- `CreateAndEditFile` keeps its current create-then-edit flow and calls the
  editor launch. `view_file` on a file just created by `Shift+F4` is not
  special-cased.

### Settings

`Core Settings.json` (Windows layer):

```json
{
  "editor_preset": "notepad++",
  "editor": {"args": ["C:\\Program Files\\Notepad++\\notepad++.exe", "{file}"]},
  "viewer_preset": "cudatext",
  "viewer": {"args": ["C:\\Users\\me\\AppData\\Local\\Programs\\CudaText\\cudatext.exe", "-r", "{file}"]}
}
```

- `editor` keeps today's Popen-mapping shape, so hand-written configurations and
  the previous picker's output remain valid. Extra Popen keys (`cwd`, `shell`)
  are passed through unchanged; the wizards only ever write `args`.
- `viewer` is independent of `editor`. When it is absent or invalid, `F3` runs
  the viewer wizard; with a valid known-preset editor the first list entry is
  `Same as editor`, so accepting it is Enter, Enter. There is no silent
  fallback to the editor.
- `editor_preset` / `viewer_preset` are informational (`notepad++`,
  `cudatext`, `textadept`, `custom`); they seed the wizard's initial selection
  and enable `Same as editor`. A missing preset key is treated as `custom`.
- No bundled defaults are added: an unconfigured role must trigger its wizard,
  and a bundled path would be wrong on most machines.

### Key Bindings

Core `Key Bindings.json` adds `{ "keys": ["F3"], "command": "view_file" }`
beside the existing `F4`/`Shift+F4` rows. `F3` conflicts with no bundled binding
(only `Ctrl+F3` is used, for `sort_by_column`). The F1 shortcut dialog and the
Command Center pick the new command up automatically.

### Threading and Failure Behavior

Commands run on the command worker; all dialogs are the blocking public helpers
that already dispatch to Qt. `Popen` returns immediately; the child is not
tracked, waited on, or killed on exit. Settings writes go through `save_json`
under the config lock. No timers, workers, watchers, or signals are added.

## Alternatives

- **Built-in QScintilla viewer/editor (previous revision)**: rejected by the
  user. It added a bundled dependency, save/encoding fidelity, dirty-close and
  exit gates, multi-caret mapping, and a large test surface for a file manager
  whose users already have a preferred editor.
- **Keep only the current F4 picker and let users hand-edit `viewer` in JSON**:
  smallest change, but `F3` would be unusable until the user discovers the
  setting and knows each editor's read-only switch. Presets encode that once.
- **A `fman.ui` Panel/QuickList wizard**: nicer than chained dialogs, but the
  wizard runs once and the existing blocking helpers already cover a list, a
  file dialog, two prompts, and a confirmation without touching the host.
- **Registry-based detection (App Paths, uninstall keys)**: more reliable for
  installed Notepad++, but the repository policy avoids Registry dependence and
  two of the three editors are typically portable. Fixed locations plus `PATH`
  plus Browse is enough.
- **One wizard configuring both roles from one program** (previous revision):
  fewer commands, but forces viewer = editor and asks a user-defined editor two
  argument questions in a row. Rejected by the user in favor of two role-specific
  wizards that can guide toward a feature-rich editor and a fast read-only
  viewer; the editor wizard's final link question keeps the one-program case to
  a single extra Yes.
- **One wizard with a "different viewer?" fork**: fewer palette entries than two
  wizards, but reconfiguring only the viewer would replay the editor steps.
- **`View = Edit` for user-defined viewers without a prompt**: simpler, but
  programs with a read-only switch (for example Vim `-R`, EmEditor `/r`) would
  lose the feature. The viewer wizard asks one argument line, prefilled with
  `{file}` (or the editor's arguments), so the simple path stays one Enter.
- **Silent `F3` fallback to the editor when no viewer is configured**: kept
  `F3` working for old configurations, but hid that a viewer exists at all.
  With a viewer wizard whose first entry is `Same as editor`, running it is
  just as quick and leaves an explicit setting behind.
- **Track the editor process to reload the pane on exit**: not needed on
  Windows because panes reload on application activation, and single-instance
  editors return immediately anyway.
- **Binary sniff on `F3`/`F4` with a fallback to the default application**:
  considered for images and other non-text files; rejected by the user. It
  would second-guess an explicit view/edit request, duplicate `Open with...`,
  and add a setting nobody asked for. Both commands stay text-oriented.

## Runtime Effects

- Startup: registers four commands and one binding; no settings read, detection,
  or I/O until `F3`, `F4`, `Shift+F4`, or a wizard runs.
- Launch: one `load_json` (cached), one `os.path.isfile` on the executable, one
  `Popen` without waiting. The child process is independent of RoyiFileManager.
- Wizard: at most a handful of `os.path.isfile`/`shutil.which` probes plus the
  dialogs; one `save_json` write on confirmation (two when the editor wizard
  also saves the viewer).
- No workers, timers, watchers, recurring signals, or persistent state beyond the
  four JSON keys. Cancellation is the user closing a dialog.
- Disabled path: with no configuration, `F3`/`F4` open their wizard; canceling
  it leaves no state behind.

## Tests

Focused commands from the repository root with the `build.py test` environment
(`PYTHONPATH` including `src/main/resources/base/Plugins/Core`,
`QT_QPA_PLATFORM=offscreen`):

```powershell
python -m unittest core.tests.test_text_editor
python -m unittest core.tests.commands.test___init__
python -m unittest fman_unittest.impl.test_shortcuts
```

Unit tests in `core/tests/test_text_editor.py` (pure Python, temp directories,
stub UI recording the dialog sequence):

- Each preset derives the documented Edit/View `args` from a given executable
  path; `{file}` appears exactly once in each.
- Detection honors candidate order, skips missing files, uses `shutil.which`
  last, and returns `None` when nothing exists (environment patched).
- Per-role list content and order: editor list has no `Same as editor`; viewer
  list has it first only when `editor` is valid and `editor_preset` is known;
  descriptions match the role table; initial highlight follows the saved preset.
- Intro alert text per role and per missing/invalid state; skipped when run
  from the Command Center.
- User-defined argument parsing: quoted paths with spaces, missing `{file}`
  appended, `shlex` errors reported; viewer prompt prefilled with the editor's
  arguments when the editor is user-defined.
- Editor wizard link step: offered only when `viewer` is invalid and the preset
  has a read-only switch; Yes writes `viewer` + `viewer_preset`; No writes
  nothing for the viewer; skipped for user-defined editors.
- `Same as editor` writes the editor executable with the preset's View
  arguments without opening Locate or Arguments.
- Settings validation: missing keys, non-list `args`, non-string entries, empty
  list, executable not a file; legacy `{"args": [exe, "{file}"]}` accepted;
  extra Popen keys preserved; missing `*_preset` treated as `custom`.
- `{file}` expansion with a path containing braces, spaces, and non-ASCII.

Command tests in `core/tests/commands/test___init__.py` (existing `StubUI`
pattern with patched `show_*`, `load_json`, `save_json`, `Popen`):

- `view_file` with a valid `viewer` launches `Popen` with the expanded args and
  `cwd`; with only `editor` it runs the viewer wizard, not the editor.
- `F3`/`F4` on a directory, a non-`file://` URL, or a missing file alert and do
  not launch or start a wizard.
- Unconfigured settings run the matching role's wizard; cancel at each dialog
  leaves settings untouched and does not launch; success continues the
  original command once.
- Wizard preset path: detected executable accepted, rejected then browsed, and
  saved JSON matches the preset table; the role's `*_preset` written.
- Wizard user-defined path: one prompt per role, defaults, confirmation text.
- `Popen` raising `OSError` shows the actionable alert naming the right
  configure command, no traceback.
- `create_and_edit_file` still creates the file and then launches the editor
  through the shared helper (existing tests keep passing).
- Command identifiers/aliases: `view_file`, `configure_text_editor`,
  `configure_text_viewer`, and the unchanged legacy names.

Shortcut regression: the `F3` binding is listed by `collect_shortcuts` for the
Core `Key Bindings.json` and does not collide with any bundled binding.

Manual checks (native run, each installed editor when available): `F3` opens
read-only and `F4` writable in Notepad++, CudaText, and Textadept; editor and
viewer set to different programs; `Same as editor`; the editor wizard's link
question; a user-defined viewer with and without a read-only switch; a file
with spaces and non-ASCII in its path; both configure commands rerun after a
valid configuration; uninstalling the viewer and pressing `F3` reruns the viewer
wizard with the `Could not find` intro.

## Implementation Steps

1. Spike on the machine with the three editors installed: confirm Notepad++
   `-ro`, CudaText `-r`, and Textadept `-r` open read-only (including the
   single-instance case with the editor already running). If Textadept rejects
   `-r`, test `<file> -e "buffer.read_only = true"`. Record results in this
   document and adjust the preset table before implementing step 2.
2. Add `core/text_editor.py` with presets, role guidance, detection, derivation,
   validation, expansion, and `run_wizard(role, ui, settings)`; add
   `core/tests/test_text_editor.py` and run it.
3. Replace `_get_editor()` with `_validated_settings(role)`/`_launch_program()`;
   add `ViewFile`, `ConfigureTextEditor`, `ConfigureTextViewer`; keep
   `OpenWithEditor`/`CreateAndEditFile` identifiers. Run
   `core.tests.commands.test___init__`.
4. Add the `F3` binding to Core `Key Bindings.json`; run the shortcut tests.
5. Update the Core README/[README.md](../README.md) feature list (`F3` view, `F4`
   edit, `Configure text editor`, `Configure text viewer`),
   [CHANGELOG.md](../CHANGELOG.md), and remove the TextEditor entry from Plan.md
   pending on completion.
6. Manual checks above; record results and move this document to Done.

## Acceptance Criteria

- With nothing configured, `F4` opens the editor wizard and `F3` opens the
  viewer wizard; each intro states what the role is for (editing features
  versus fast read-only viewing) and each preset row carries a role-specific
  description.
- Choosing Notepad++, CudaText, or Textadept in either wizard requires at most
  confirming a detected path or browsing to one; the role's command is saved
  without typing arguments.
- The editor wizard offers to reuse the chosen preset as the viewer when no
  viewer exists; the viewer wizard offers `Same as editor` when the editor is a
  known preset. Editor and viewer can be different programs.
- `F3` opens the file read-only in the three presets; `F4` opens it writable.
- The user-defined preset asks one argument line per wizard and validates the
  `{file}` placeholder.
- Existing `editor` settings from the old picker keep working for `F4`; `F3`
  with no viewer runs the viewer wizard rather than failing or silently
  reusing the editor.
- Directories, non-local URLs, missing files, and a missing executable produce
  short alerts naming the relevant configure command, never tracebacks, and
  never launch anything else.
- No Registry access, no bundled executable paths, no background work.
- The listed focused tests pass; manual checks are recorded or explicitly left
  pending.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed host editor service with reused Panel controls and editor-local
  command/lifetime handling. Placement, API, file limits, and regex deferral need
  review before implementation; no implementation or runtime validation claimed.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Not yet approved. Verified QScintilla 2.14.1 (47 lexers, all required
  `SCI_*` multi-selection messages) imports in the active environment and that
  `qscintilla2` is present in the committed `conda-lock.yml`. Blocking revisions:
  (1) add `PyQt5.Qsci` and the new `fman.editor`/`fman.impl.editor.*` hidden
  imports, DLL collection and an import-probe test to the plan; (2) name the
  required host change for the exit gate (`MainWindow.closeEvent` must consult the
  service and `event.ignore()`; `Quit`, `Application.exit` and `closed -> quit`
  all funnel through it); (3) give the editor its own bounded executor instead
  of the shared two-slot `submit_work` pool, so a slow UNC read/save cannot block
  Favorites/JsonSettings and Ctrl+S never yields a "retry" state; (4) specify
  where default settings live (Core-shipped `Text Editor.json`, following the
  `Status Bar.json` precedent). Design gaps to state explicitly: Scintilla
  hard-codes Ctrl+Click as add-selection, so Alt+Click/Shift+Alt+Drag need
  Python mouse-event mapping; the default `QsciCommandSet` (Ctrl+D, Ctrl+L,
  Ctrl+T, Ctrl+Shift+L, ...) must be cleared before VS Code bindings; name the
  commit primitive (temp sibling + `os.replace`, attribute copy, documented ACL
  inheritance limitation); decide editor window parenting (recommend parentless
  top-level); define the concrete non-UTF-8 fallback rule; record Python `re`
  on the immutable snapshot as the intended regex path.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Replaced the built-in QScintilla editor service with an external
  editor wizard at the user's direction. Reviewed the current `F4` picker
  (`OpenWithEditor._get_editor`, `Core Settings.json` `editor` Popen mapping,
  native open dialog, no viewer/validation) and the `Open with...` app picker.
  Verified read-only switches against upstream documentation: Notepad++ `-ro`,
  CudaText `-r`, Textadept via `-e "buffer.read_only = true"` (no native
  switch; ordering to be confirmed in step 1). Presets, user-defined prompts,
  `viewer`/`editor_preset` settings, `F3` binding, and Core-only ownership are
  proposed; the earlier records describe the superseded design. Plan revision
  only; no implementation or runtime validation.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: Textadept View preset changed to `-r {file}` per user direction; the
  `-e` Lua route is retained as the spike fallback because the 13.1 manual does
  not document `-r`. Confirmed with the user that `F4` keeps one editor for all
  file types; per-extension editors stay excluded.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: User decided `F3`/`F4` remain text-oriented with no binary or
  file-type detection; non-text files are handled by `Open with...`. Recorded
  in Scope exclusions and Alternatives.

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Split the single wizard into `configure_text_editor` and
  `configure_text_viewer` per user direction (option B). Each wizard carries
  role guidance: intro alert when auto-triggered, role-specific preset
  descriptions, and list order recommending feature-rich editors versus fast
  read-only viewers. Added `viewer_preset`, `Same as editor`, the editor
  wizard's link question, one argument prompt per role, and replaced the silent
  `F3` fallback with the viewer wizard. Tests and acceptance criteria updated.
  Plan revision only.
