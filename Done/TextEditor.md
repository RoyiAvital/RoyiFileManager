# Text Editor

Status: Implemented and focused validation passed. Independent executable/arguments
settings serve F4 editing and F3 viewing, with presets or Manual configuration.
Read-only behavior belongs to the chosen program and user, not to RoyiFileManager.

## Task

Let users set an external text editor and viewer independently through Command
Center wizards. Every new configuration launches as
`<executable> <configured arguments> <file path>`. The file path is appended as
one argument; the user needs no placeholder.

## Scope

- `view_file` on F3; retain `open_with_editor` on F4 and
  `create_and_edit_file` on Shift+F4.
- `set_text_editor` / `set_text_viewer`, visible only as **Set text editor** /
  **Set text viewer** in the Command Center.
- Presets Notepad++, CudaText, **Manual configuration**, then
  **Clear editor** / **Clear viewer** last. Clearing adds no Command Center commands.
- Native executable picker supports browsing or typing/pasting an exe path.
  Only Manual configuration prompts for arguments. Empty arguments are valid.
- Local files only after normal URL resolution; directories, missing files
  and unsupported schemes alert without opening setup.
- No embedded editor, detection, downloads, Registry access, linked roles,
  preset metadata, file sniffing, placeholders in new settings, process tracking,
  read-only enforcement, automatic Lua fallback or per-extension configuration.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5 and
existing command identifiers. New settings use the same `editor` key and an
independent `viewer` key. Existing `editor` Popen mappings are read without
rewriting them; explicit reconfiguration replaces only that role with the new
shape. Existing `cwd`/`shell` options remain honored for legacy mappings.

## Design

### Ownership

- Core commands delegate configuration and launch to `core/text_editor.py`.
  This Qt-free module owns preset data, Windows parsing, settings validation,
  wizard flow and launch preparation. Keep the existing create-then-edit flow.
- Use public `show_quicksearch`, `show_file_open_dialog`, `show_prompt`,
  `show_alert`, `show_status_message`, `load_json` and `save_json` helpers.
  No public API additions or new host widgets.
- Commands run on the existing command thread; public dialogs dispatch to Qt.
  Parsing and launches occur on that command thread. Settings writes affect
  only the selected role and preserve unrelated keys and the other role.

### Presets

| Preset | Editor arguments | Viewer arguments |
| --- | --- | --- |
| Notepad++ | `[]` | `["-ro"]` |
| CudaText | `[]` | `["-r"]` |
| Manual configuration | User-entered, defaults empty | User-entered, defaults empty |

Presets are argument conveniences, not a read-only guarantee.
Manual configuration lets users change any program's arguments.
Removing a preset does not modify existing executable/arguments settings.
Do not execute programs to detect or verify their capabilities.

### Wizard Flow

1. Invoke **Set text editor** or **Set text viewer** in the Command Center.
2. QuickSearch offers Notepad++, CudaText, Manual configuration, then
  Clear editor/viewer last. Clear saves the role as unset, shows a brief status
  message and returns without any more dialogs or process launch.
3. Pick the executable in a native `Applications (*.exe)` dialog, which also
   accepts a typed/pasted path. Prefill the current role's executable when known.
4. Presets supply arguments immediately. Manual configuration prompts for one
   Windows argument line, prefilled from that role's existing arguments.
5. Validate and save only that role; show a short saved-status message.

Cancel at any dialog changes nothing. Errors produce an alert without saving.
No detection, role-linking, read-only check or automatic program launch occurs
in the configuration commands. F3/F4 never open setup automatically. An unset
viewer displays `No text viewer was set. Use "Set text viewer" in Command Center to define a text viewer.`;
the editor uses the same message with `editor` substituted. A nonempty invalid
configuration reports its error and directs the user to the matching Set command.

### Parsing and Launch

- Parse manual arguments with Windows `CommandLineToArgvW` via standard-library
  ctypes, prepending a dummy executable to avoid argv[0]'s special parsing.
  Free the returned allocation with `LocalFree`. Empty input means no arguments.
  Use `subprocess.list2cmdline` for prefill; never `shlex` or ad hoc quote stripping.
- Validate executable and argument types, embedded NULs and launch length. The
  selected executable must be an existing `.exe` file for new configurations.
  Argument text is literal: braces, percent signs and shell metacharacters are
  not expanded. Quoted arguments and empty arguments remain intact.
- After target resolution/validation, form `[executable, *arguments, file_path]`
  and launch with `Popen(..., shell=False)`. Inherit the application's cwd;
  no new configurable cwd or shell option. Catch configuration and process
  errors directing users to **Set text editor** or **Set text viewer**.
- Preserve the legacy Popen-mapping path only for old settings without the new
  `executable` key: expand the existing `{file}` templates on a copy and pass
  through all original options. Validate malformed mappings/templates and
  report their errors; do not append the file a second time. A legacy setting
  is replaced only after explicitly completing its role's wizard.

### Settings

`Core Settings.json`, user layer (example only, no bundled defaults):

```json
{
  "editor": {"executable": "C:\\Tools\\notepad++.exe", "arguments": []},
  "viewer": {"executable": "C:\\Tools\\cudatext.exe", "arguments": ["-r"]}
}
```

No preset identifiers or linked state are persisted. Save only after the last
successful wizard step. Reload the cached settings after the dialogs, copy the
top-level dictionary and replace only the chosen role via `save_json(name, value)`.
A save failure alerts and does not launch; the original cache and persisted role
remain unchanged. Other role/unrelated settings remain untouched.

Clearing saves `null` for only the chosen role, masking any lower-priority legacy
or configured value instead of deleting the key and exposing it again. Missing
or already-null roles need no write. Clear uses a fresh top-level settings copy;
save failures retain the original cache and persisted values and show an error.

## Alternatives

- Embedded editor, automatic detection, role linking, read-only verification
  and placeholder editing: rejected in favor of the user's simpler workflow.
- Shell command strings / shlex parsing: rejected; use Windows argv parsing
  and a shell-free argument list, validated against actual received child argv.
- Forcing old Popen settings into the new shape: rejected as a compatibility
  regression. A small legacy read path preserves them until reconfiguration.
- New host wizard UI: unnecessary; native file dialogs allow browsing and path
  entry, and existing QuickSearch/prompt APIs cover the remaining steps.
- Automatic first-use setup: removed at the user's request; show an informational
  message and let the user explicitly invoke the matching Command Center command.
- Separate Clear viewer/editor commands: rejected to avoid Command Center clutter.
  Put the matching Clear action after Manual configuration inside each setup list.
- Additional program presets: deferred at the user's request; keep only Notepad++
  and CudaText. Other programs remain configurable manually.

## Runtime Effects

- Startup/idle: register three new commands and F3; no detection, I/O, scans,
  timers, additional workers or recurring signals. Native parser DLLs load only
  when parsing manual arguments.
- Launch: cached settings plus target/executable metadata checks and one child
  process. No content reads; child is not waited on, monitored or killed at exit.
- Wizard: bounded command text and small preset list; native dialogs, executable
  metadata checks, one settings save. Cancellation discards unsaved choices.
- Clear: cached settings and at most one save, without executable checks, native
  argument parsing, additional dialogs or process work. Already-unset roles skip saving.
- No-op: an unset role displays one alert without opening a wizard, saving settings
  or launching a process. Canceled setup also changes nothing. Memory is
  proportional to the bounded argument text; no process output is retained.

## Tests

Focused commands from the repository root:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.commands.test___init__', 'fman_unittest.impl.test_shortcuts', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'fman_integrationtest.qt_runner', 'fman_integrationtest.test_qt.TextEditorIT'], env=build._environment()))"
```

- Unit/real child: all preset/role argv, quoted Windows paths, empty arguments,
  embedded quotes, trailing backslashes, spaces/Unicode/braces in filenames,
  no interpolation in new arguments, malformed configuration, length/NUL checks.
- Wizard: both roles, Clear last after Manual, presets ask only for executable, manual asks
  for both; current path/arguments prefill; cancel at each step; invalid exe;
  save failure rollback; only the selected role changes; no detection/launch.
  Assert the exact two preset names and the four-item Qt list order.
- Clear: both roles, inherited/legacy settings masked after reload, other settings
  preserved, failure rollback, already-unset no-write path and no extra dialogs/launch.
- Compatibility: legacy expansion/cwd/shell retained; no settings mutation during
  launch. F4 and Shift+F4 identifiers and create-then-edit behavior retained.
- Commands: target validation, exact missing-role message for both roles, no
  automatic setup/save/launch for missing or invalid settings, launch errors,
  independent roles, exact sole Set text editor/viewer aliases, F3 default
  and F1 shortcut collection, no bundled F3 collision.
- Persistence integration: temporary Config directory, save/reload and opposite
  role/unrelated key preservation. No real UserSettings writes in tests.
- Qt smoke: preset and manual wizard using existing public dialogs, clear, cancel,
  independent roles and launching an argv-echo executable. The automated picker
  substitutes Qt's non-native file dialog for deterministic acceptance/cancel;
  Windows shell-picker browsing and typed/pasted paths remain manual checks.
  Third-party editor read-only semantics are not an acceptance gate.
- No full suite, clean, freeze or editor installations for this task.

## Implementation Steps

1. Implement parser, new/legacy launch preparation and focused tests; run them.
2. Implement shared wizard and command integration; test cancellation, persistence,
   preset/manual flows and target/launch failure behavior.
3. Add F3 and validate command/shortcut compatibility plus native smoke.
4. Update Core/main usage and changelog; record actual validation, then move
   the canonical task to Done and its index entry to Completed.

## Acceptance Criteria

- Command Center exposes both Set commands. Each offers the two presets and
  Manual configuration, then Clear editor/viewer last. No new commands are added;
  preset flow requires only exe selection, manual flow also accepts arguments.
  No hidden role linking or program detection.
- Each configured role contains only executable and arguments; clearing stores
  null and preserves the other role, with no further dialogs. New launches pass
  executable, arguments, then exactly one file-path argument, without a shell.
- Viewer may be writable; preset arguments are convenience defaults only.
- Existing F4 settings remain usable until explicitly replaced. F3 is independent;
  canceled setup/launch errors preserve settings and never launch a substitute.
- An unset role displays only its Command Center instruction; neither F3 nor F4
  starts configuration automatically.
- Quoting, metadata validation, errors, persistence and shortcut regressions pass.
  Public API is unchanged; unrun manual/release checks are explicitly recorded.

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

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: External editor/viewer integration is a focused alternative to an
  embedded editor, and existing public dialogs support both wizards without
  new APIs or dependencies. Needs revision before implementation for Windows
  argument parsing, launch compatibility, read-only and configuration failures.
  Operative design and prior reviewer records are unchanged; no application
  implementation was attempted.

#### Findings

1. **P1: `shlex.split(posix=False)` produces incorrect launch arguments.**
   The proposed line `--session "C:\My Files\session.ini" {file}` produces a
   path containing literal quote characters. A real argv-echo child confirmed
   those quotes arrive at the program. Specify Windows argument-list parsing
   using an existing system parser or structured argv input, plus matching
   serialization for confirmation/prefill. Do not substitute POSIX shlex or
   strip quotes ad hoc. Test actual child argv for spaces, empty arguments,
   embedded quotes, backslashes before quotes, trailing backslashes and `{file}`.
2. **P1: launch and settings compatibility contracts contradict each other.**
   Launch Behavior specifies `Popen(args, cwd=dirname(path))`, no shell, but
   Settings promises to preserve `cwd`, `shell` and other Popen keys.
   [OpenWithEditor](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L417)
   currently expands and passes the entire mapping to `Popen(**popen_kwargs)`.
   Preserve legacy mappings, including explicit options and inherited cwd when
   absent, while using shell-free defaults for new wizard configurations; or
   explicitly approve a migration. Do not silently discard configured options.
   Test complete Popen kwargs, not just argv.
3. **P2: read-only acceptance exceeds the preset guarantees.**
   Textadept `-r` remains unverified and the plan allows View = Edit when both
   read-only routes fail, yet acceptance requires read-only F3 for every known
   preset. A confirmation note does not meet that contract. Keep Textadept
   viewer support conditional on the version-specific spike; failure should
   require another viewer or explicit custom configuration, not writable
   fallback. Test the same file already open, F4 -> F3 and F3 -> F4, as well as
   cold launches. Omitting a flag does not prove a reused buffer becomes writable.
4. **P2: validation does not cover the promised no-traceback behavior.**
   The proposed validator checks argv shape and executable existence, but
   [strformat_dict_values](../src/main/resources/base/Plugins/Core/core/util.py#L9)
   uses `str.format`: unknown placeholders/unmatched braces can raise
   `KeyError`/`ValueError` before Popen. Malformed mappings/keyword values can
   cause other non-`OSError` failures. Define template syntax, mapping validation
   and an actionable configuration-error path without rewriting valid legacy
   settings. Validate the target before detection or any wizard. Test malformed
   templates/mappings, unsupported placeholders, target validation order and
   cancel-without-save behavior.

#### Review Validation

- Read the current editor/create-and-edit path, template expansion and public
  QuickSearch fields. No host UI addition is needed for the proposed descriptions.
- A standard-library probe parsed the quoted path with the proposed shlex call
  and launched a harmless Python argv-echo child, confirming literal surrounding
  quotes reached it. No editor or user document was opened.
- No installed-editor validation or application tests were run. Upstream-switch
  assertions were not independently reverified; read-only support remains
  conditional on the planned spike, including reused-buffer behavior.
- Replace implicit-PYTHONPATH test commands with verified `build._environment()`
  launchers when implementing; the new wizard module is still proposed. Use
  focused wizard, Core-command and shortcut tests plus the native editor matrix.
  Mocked Popen success does not establish read-only behavior.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: User approved simplified design and implementation. Replaced the
  operative plan with independent executable/arguments records, Manual last,
  preset arguments and file-last argv. Windows native parsing resolves quoting;
  a legacy-only reader preserves existing Popen mappings. User explicitly owns
  read-only behavior, so no verification/fallback workflow remains. Configuration
  validation and focused tests are specified. Prior review history is preserved.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Approved the user-requested informational-only first-use behavior.
  Missing roles use the exact matching Set viewer/editor message; invalid
  configurations retain actionable errors without automatic setup. Preserve
  command IDs and old aliases while making the shorter aliases primary.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Accepted the user's Clear-last placement inside the existing Set
  lists, superseding Manual-last ordering without adding commands. Use a null
  override to clear inherited settings durably; preserve other keys and the
  existing no-automatic-setup behavior. Test persistence, no-op and failed saves.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Accepted the user's exact Set text editor / Set text viewer names
  as the sole setup aliases, superseding the shorter labels. Match all alerts
  and usage documentation; preserve command IDs and Clear-last behavior.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Accepted removal of Textadept from both preset lists after the user
  reported no built-in read-only mode. Retain Notepad++, CudaText, Manual and Clear;
  preserve existing settings without detection or migration.

## Implementer

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented independent editor/viewer setup, presets and Manual last,
  Windows argument parsing, file-last shell-free launches, legacy mapping support,
  target/configuration errors and save-without-cache-mutation on failure. Added F3;
  retained F4/Shift+F4 and public APIs. Updated usage and Unreleased changelog.
  Final focused gates passed 107 tests with no skips.

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Replaced automatic first-use setup with the requested viewer/editor
  messages. Set viewer/editor are primary aliases; old aliases and command IDs
  remain supported. Missing or invalid settings never open setup or launch.
  Updated regression tests and usage; removed an identical stale pending task
  copy after comparison. The focused editor/Core command gate passed 101 tests.

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Added role-specific Clear as the final setup option, with immediate
  null persistence and status feedback, no extra dialogs and no new commands.
  Added layered-settings, no-op, failed-save and Qt selection regressions.
  Focused gates passed 20 editor tests and 3 Qt tests without skips.

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Restored the exact sole setup aliases and aligned unset/error messages
  and current documentation. Command IDs, settings and Clear-last flow are unchanged.
  All 23 focused editor and command-routing tests passed.

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Removed Textadept from the shared preset table, asserted the two
  remaining names and updated Qt list expectations and current documentation.
  No saved settings changed. All 20 editor and 3 Qt tests passed.

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Updated unset alerts to say text viewer/editor throughout, including
  after clearing. Aligned exact-message tests and documentation; 20 editor tests
  passed. User-edited changelog and runtime behavior otherwise remain unchanged.

## Validation Results

### Initial Implementation

Final focused commands from the repository root:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', 'core.tests.commands.test___init__', 'fman_unittest.impl.test_shortcuts'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'fman_integrationtest.qt_runner', 'fman_integrationtest.test_qt.TextEditorIT'], env=build._environment()))"
```

- Unit/command/shortcut gate: 105 passed. Includes 16 editor tests, all preset/role
  argv in real child processes, quoting/empty/literal arguments, UTF-16 length/NUL
  rejection, legacy options, target validation, cancellation, first-use launch,
  failed saves, concurrent unrelated settings changes and temporary Config reload.
- Qt gate: 2 passed using the existing main-thread runner, production public
  QuickSearch/prompt dispatch and a deterministic Qt executable picker. Covers
  both roles, preset/manual flows, cancellation at every modal stage and a real
  argv-echo launch. An initial test-only syntax error was corrected before this
  successful run; no failing checks remain.
- Editor diagnostics: no errors in touched application, test, binding or Markdown
  files. Documentation links, required task headings and changelog structure passed.
- No expected skips. No complete suite, clean, freeze, package build or installation
  was run. Public `fman` modules were not modified.
- Not run: manual Windows shell-picker browsing and typed/pasted-path checks, and
  launches of actual Notepad++, CudaText or Textadept installations. Automated tests
  substitute Qt's non-native file dialog only at the file-picker boundary.
  Third-party read-only behavior remains user-owned and is not an acceptance gate.

### 2026_09_17 - Informational-Only First Use

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', 'core.tests.commands.test___init__'], env=build._environment()))"
```

- Immediate editor check: 16 passed. Final editor/Core command gate: 101 passed,
  no skips. Both roles assert the exact unset message, no setup dialogs, no save,
  no process launch and unchanged persisted settings. Invalid settings also avoid
  setup; configured launches and F4/Shift+F4 behavior remain covered.
- Primary Set viewer/editor aliases and retained old aliases are asserted.
- Qt dialogs were not changed or rerun for this follow-up. No full suite or
  packaging checks were run; previous manual-check limitations still apply.

### 2026_09_17 - Clear From Setup List

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'fman_integrationtest.qt_runner', 'fman_integrationtest.test_qt.TextEditorIT'], env=build._environment()))"
```

- Editor gate: 20 passed, including final-option order, both roles, null overrides
  masking lower layers after reload, unrelated settings preservation, failed-save
  rollback, already-unset no-write behavior and the existing F3/F4 unset messages.
- Qt gate: 3 passed, including choosing Clear for each role through real
  QuickSearch, persisted results and status feedback with no further dialog or
  process launch. Existing preset/manual setup, cancellation and argv echo passed.
- No skips. Code diagnostics reported no errors. No full suite or packaging checks;
  the earlier native shell-picker and third-party editor manual limitations remain.

### 2026_09_17 - Exact Setup Names

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', 'core.tests.commands.test___init__.TextEditorCommandsTest', '-v'], env=build._environment()))"
```

- 23 passed, no skips. Tests assert the exact sole Set text editor/viewer aliases,
  unchanged command IDs/routing, matching unset/error messages and clearing behavior.
- Qt widgets were unchanged and Qt tests were not rerun for this naming-only change.
  No full suite or packaging checks; earlier manual-check limitations remain.

### 2026_09_17 - Reduced Presets

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'fman_integrationtest.qt_runner', 'fman_integrationtest.test_qt.TextEditorIT'], env=build._environment()))"
```

- 20 editor tests and 3 Qt tests passed, no skips. Exact preset names and Qt list
  order are asserted; remaining presets, Manual, Clear, persistence, cancellation
  and real argv-echo launches retain their coverage.
- No third-party editor launches, full suite or packaging checks were run.
  Earlier manual-check limitations remain; read-only behavior is not guaranteed.

### 2026_09_17 - Unset Alert Wording

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', '-v'], env=build._environment()))"
```

- 20 passed, no skips. Both missing and cleared roles assert the exact text
  viewer/editor wording and no automatic setup or process launch.
- Qt widgets are unchanged; no Qt, full-suite or packaging checks were rerun for
  this wording-only change. Earlier manual-check limitations remain.
