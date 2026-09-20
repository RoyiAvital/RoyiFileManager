# File and Folder Comparators

## Task

Add external file/folder comparator setup wizards, following the text editor/viewer
workflow, and **Compare files** / **Compare folders** commands with predictable
operand selection.

Status: proposed design, awaiting review before implementation. This task currently
changes documentation only.

## Scope

- Windows commands: **Set file comparator**, **Set folder comparator**,
  **Compare files**, and **Compare folders**. No default shortcuts in this change;
  all commands support user bindings and appear in Command Center.
- Independent executable/argument settings. Initial proposed presets: WinMerge
  and Beyond Compare, plus manual configuration and clearing either role.
- Existing local files/folders, including accessible UNC paths and filesystem
  links to the appropriate target type. Binary files are allowed.
- Preserve the public `fman` plug-in API from fman 1.7.5, existing editor/viewer
  behavior, and all existing command IDs and bindings.
- Exclude built-in diff rendering, batch/three-way comparison, same-name guessing,
  archive extraction, remote downloads, scripts, tool installation/discovery,
  and automatic merging or synchronization.

## Design

### Ownership

- Add thin `DirectoryPaneCommand` classes to
  [Core commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py):
  `SetFileComparator`, `SetFolderComparator`, `CompareFiles`, `CompareFolders`.
  IDs: `set_file_comparator`, `set_folder_comparator`, `compare_files`,
  `compare_folders`. Use the exact sentence-case labels in Scope.
- A lazily imported Core `comparator` module owns operand resolution, the wizard,
  settings, validation, request lifetime, and launching.
- Reuse the [editor/viewer pattern](../src/main/resources/base/Plugins/Core/core/text_editor.py).
  Extract only its argument parser, Windows command-length constant, and text/argv
  validators into a small Core `external_program` helper shared by both modules.
  Preserve existing imports/signatures and legacy editor/viewer launch behavior;
  do not generalize their wizard or introduce a generic external-tool framework.
- Existing `CompareDirectories` / `compare_directories` remains unchanged: it
  marks names missing in the opposite pane, not content differences. Documentation
  must distinguish it from the new external **Compare folders** command.
- Use the [pane API](../src/main/python/fman/__init__.py) for snapshots. The
  [view's selection API](../src/main/python/fman/impl/view/__init__.py) does not
  promise click order or display order. The only private-host coupling is the
  existing Qt-thread dispatch helper; no direct model traversal or public API change.

### Compare Files

"Marked" means explicit selection. The cursor is a fallback, not an additional
selected entry. Apply these rules in order:

| Active pane | Other pane | Result |
| --- | --- | --- |
| Exactly two marked entries | Any state | Compare that pair; ignore the other pane. |
| More than two marked entries | Any state | Reject ambiguous input; no arbitrary pair or batch. |
| Zero or one marked entry | More than one marked entry | Reject ambiguous opposite-pane input. |
| Zero or one marked entry | Zero or one marked entry | One candidate per pane: mark if present, otherwise cursor. |

- Require both chosen entries to be existing files. A folder, parent entry, or
  invalid selection is an error, never a reason to fall back to another candidate.
- Missing candidate: identify the pane needing a file. Never infer a same-named
  counterpart or scan for a replacement. Different filenames are valid.
- Cross-pane mode requires exactly two panes. Arguments stay physically
  left-to-right regardless of the invoking pane or later focus changes.
- Active-pair mode works without a usable opposite pane. Sort the two captured
  URLs by `(url.casefold(), url)` for stable first/second order, independent of
  marking history, cursor position, or display sort. Within one directory this is
  deterministic filename order, not selection order.
- Active-pair precedence applies even when the inactive pane has stale marks,
  an unsupported location, or no cursor. A mixed file/folder pair still fails;
  it does not switch to cross-pane mode.
- No normal-case confirmation dialog. Invalid input gives one actionable message
  and never changes selections, cursor positions, settings, or pane locations.

Examples: no marks compares the two cursor files; one mark on the left and none
on the right compares the left mark with the right cursor; two marks in the active
pane compares those files even when the other pane is an archive.

### Compare Folders

- Always compare the current locations of the two panes, in left/right order.
  Ignore marked entries and cursors, including a cursor on a child folder.
- Require exactly two existing filesystem directories. Empty folders, drive/share
  roots, and distinct parent/child folders are valid.
- To compare child folders, open one in each pane first. A selection-based folder
  action would need a separate name, not another selection heuristic.
- Recursion and comparison criteria belong to the external tool. The WinMerge
  folder preset requests recursion; Beyond Compare/manual configuration uses the
  application's preferences.

### Wizard and Settings

1. Quicksearch offers **WinMerge**, **Beyond Compare**, **Manual configuration**,
   then **Clear file comparator** or **Clear folder comparator**.
2. Show **Set file comparator** / **Set folder comparator** executable picker,
   prefilled from the current role. Accept an existing absolute `.exe` path only.
3. Presets supply fixed arguments. Manual setup prompts for **Arguments:**,
   prefilled using `list2cmdline` and parsed by the shared Windows parser.
4. Validate without launching. Reload settings, copy them, update only this role,
   and save. Canceling at any step leaves configuration unchanged.
5. Clear stores `null` to mask inherited configuration. Clearing an already
   missing/null role performs no write.

Store `file_comparator` and `folder_comparator` separately in `Core Settings.json`
through existing `load_json`/`save_json`, under
`UserSettings/Plugins/User/Settings`. Missing/null means unconfigured. Each role
stores an object with `executable` (absolute path string) and `arguments` (string
array). Do not bundle machine-specific defaults or probe installations.

Never mutate the shared loaded dictionary. Preserve editor/viewer settings and
unrelated changes made while the wizard was open. Snapshot this role's initial
value; if it changed before saving, report a conflict and require retry instead
of overwriting. Failed saves report failure without a success message or launch.

Proposed preset arguments, based on official CLI documentation:

| Preset | User-selected executable | Files | Folders |
| --- | --- | --- | --- |
| WinMerge | `WinMergeU.exe` | `["/u"]` | `["/u", "/r"]` |
| Beyond Compare | `BCompare.exe` | `[]` | `[]` |

[WinMerge](https://manual.winmerge.org/en/Command_line.html) documents positional
left/right paths, `/u` (omit operands from recent paths), and `/r` (recursive
folders). [Beyond Compare](https://www.scootersoftware.com/v5help/command_line_reference.html)
documents two file/folder operands. Avoid its blocking `.com` launcher and all
automatic merge/sync/script switches. Real tool/version checks remain required.

### Validation and Launch

- First resolve selection shape and supported URL schemes. Unconfigured roles
  then point to their **Set ... comparator** command without opening a wizard or
  performing operand metadata checks. Invalid settings give configuration advice.
- Use `fman.fs.resolve`, accept only resulting `file://` URLs, and convert with
  `fman.url` helpers. No internal URLs, extraction, downloads, or directory scans.
  Reject archive/process/null locations; aliases resolving to local paths are valid.
- Off the Qt thread, require the appropriate existing file/directory type. Follow
  symlinks/junctions; report dangling links, disappearing paths, permissions, and
  unavailable shares. Do not pre-read or inspect file contents.
- Reject the same filesystem object on both sides using stat-based same-file
  identity, including hard links, symlinks, and case aliases. Do not just lowercase
  paths, which can collapse different files in case-sensitive directories. If
  identity cannot be determined, report failure. Distinct equal-content files are valid.
- Launch `[executable, *arguments, left_path, right_path]` with `shell=False`.
  Validate the complete Windows UTF-16 command length, strings, NULs, and executable.
  Both paths are separate absolute final arguments; preserve root separators.
  Arguments are literal: no placeholders or environment-variable expansion.
- Inherit environment/cwd like the existing new-format editor/viewer launcher;
  never change the app cwd. New roles accept no legacy shell mapping or extra
  `shell`/`cwd`/`env` fields. The wizard never launches the selected program.
- Catch launch errors with setup advice. Success means process creation, not
  equality or tool acceptance. Never wait for exit or interpret comparison exit
  codes; some tools forward requests to an existing instance.
- Presets start interactive comparison without automatic writes. This is not a
  read-only sandbox: the external UI can allow user-directed edits/merges. No new
  refresh watcher; existing manual pane refresh remains available. RoyiFileManager
  does not configure the Registry; external tools retain their own settings policy.

### Threading and Cancellation

- In one Qt-thread callback, capture required pane identities, locations, marks,
  and cursors as immutable data. Subscribe to involved panes' path-change/close
  callbacks while acquiring the snapshot; callbacks only invalidate a request token.
  Workers receive no models/widgets. Active-pair mode ignores the other pane entirely.
- Focus/cursor/mark changes do not retarget captured operands. Navigation, reload
  of an involved location, or pane closure cancels a pending launch. Ensure the
  existing callbacks cover these events with Qt tests; add only an invocation-scoped
  reload guard if the current notification does not cover it.
- Use the existing cancellable `Task` infrastructure for potentially slow metadata
  checks. Check cancellation/staleness before and after blocking calls and just
  before `Popen`. Clean up subscriptions and request state on every exit, including
  `Task.Canceled`; display results through existing safe Qt dispatch.
- At most one validation request per window. Further requests report running or
  stopping. Cancellation cannot interrupt a blocked Windows filesystem call: keep
  its slot until it unwinds, suppress late launch, and do not pile up replacement workers.
- Process creation is the handoff boundary. Cancellation is best-effort before
  that boundary; a launched comparator remains independent and is closed by its user.

## Alternatives

- **One explicit mark in each pane:** straightforward but requires unnecessary
  marking and excludes two files in the same folder. Prefer the explicit active
  pair, then selection-or-cursor behavior.
- **Guess matching names or pick the first two of many:** risks comparing the
  wrong data. Reject ambiguity instead.
- **Active pane always first:** reverses left/right interpretation when focus
  changes. Use physical pane order across panes and stable URL order within one.
- **Always show an operand picker:** explicit but adds friction to every request.
  Deterministic rules are the initial design; a picker can be separately requested.
- **Infer child folders from marks:** conflicts with comparing current locations.
  Keep **Compare folders** root-based regardless of selection.
- **One shared tool setting or a generic launcher framework:** the former prevents
  independent tools/options; the latter exceeds scope. Reuse low-level helpers only.

## Runtime Effects

- Startup: four command registrations only, lazily loaded implementation; no
  executable discovery, new dependency, stat, Registry access, or tool launch.
- Idle/unused: no feature-specific jobs, timers, listeners, settings writes, or
  recurring signal work. Unconfigured invocation reads settings but performs no
  operand stat or process launch.
- Snapshot cost is O(explicit selected entries), due to the existing pane API;
  never enumerate unselected rows or directory contents. Retain only the snapshot,
  small configuration, and request state.
- Configured invocation validates two operands and one executable off the Qt
  thread. One in-flight validation per window bounds worker retention. Network
  latency is OS-controlled with the cancellation limitation above.
- One nonblocking external launch per success, no process monitoring. Recursive
  scans and subsequent CPU/memory/I/O belong to the external tool, not hidden
  RoyiFileManager work. No automatic tool download or installation.

## Tests

Names below are implementation targets, not tests already present or passing.
Reuse the [editor tests](../src/main/resources/base/Plugins/Core/core/tests/test_text_editor.py)
and [Qt test harness](../src/integrationtest/python/fman_integrationtest/test_qt.py).

### Automated Coverage

- Add `core.tests.test_comparator`: every decision-table row, both active sides,
  no cursor, folders/parent entries, mixed pairs, inactive multiple marks, invalid
  opposite locations, stable ordering with reversed selection and Unicode/case,
  one/more-than-two panes, and current-folder selection independence.
- Temporary-filesystem tests: distinct/same identity, equal-content files, hard
  links, symlinks, broken links, empty/nested folders, drive/UNC-root conversion,
  disappearance, permission failures, and unsupported schemes. Skip only real link
  cases requiring unavailable platform support/privileges, with explicit reasons.
- Wizard tests: both roles, every preset/manual choice, cancellation at each step,
  clear/null inheritance, independent settings, same-role conflict, unrelated
  concurrent changes, malformed settings, failed saves, and real `Config` reload.
- Launch tests: literal argv, spaces/quotes/Unicode/braces/percent signs, trailing
  backslashes, empty arguments, NULs, total UTF-16 length, non-`.exe`/missing programs,
  and launch errors. A real child `sys.executable` records received arguments to
  prove both paths arrive intact. No third-party comparator is needed for CI.
- Preserve all editor/viewer parser/preset/legacy launch tests and existing command
  IDs. Add a regression proving `compare_directories` still marks missing names.
- Add `ComparatorIT` to the existing Qt module: actual pane marks/cursors, both
  focus directions, all command labels/IDs, folder roots, wizard cancel/select/clear,
  persistence, and GUI-thread snapshots versus worker-thread metadata.
- Use events to block a fake metadata call; verify Qt remains responsive, navigation,
  reload, closure and cancellation suppress late launch, duplicate requests cannot
  add workers, and every exit cleans callbacks. No sleep-based timing assertions.
- Performance gates are call-count based: no idle feature activity, no metadata
  when unconfigured, and no traversal/content reads regardless of directory size.
  Record warm local capture-to-launch latency excluding external startup as
  informational data, not an arbitrary CI wall-clock threshold.

Exact focused implementation gates, ordered by touched slice:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', '-q'], env=build._environment(), timeout=60).returncode)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.test_comparator', 'core.tests.test_text_editor', 'core.tests.commands.test___init__', '-q'], env=build._environment(), timeout=120).returncode)"
$env:QT_QPA_PLATFORM = 'windows'
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.ComparatorIT', 'fman_integrationtest.test_qt.TextEditorIT', '-q'], env=build._environment(), timeout=120).returncode)"
```

### Source Startup and Manual Gates

- Run `python build.py run` with disposable `ROYIFILEMANAGER_USER_SETTINGS` and
  fixture directories: registration, missing-configuration advice, both wizards,
  restart persistence, clearing one role, and unchanged editor/viewer commands.
- With available WinMerge/Beyond Compare installations, exercise different/equal
  files, an active-pane pair, binary files, current folders, paths with spaces and
  Unicode, root paths, opposite focus, and WinMerge folder recursion. Verify
  interactive comparison, no automatic writes, and responsiveness while tools run.
- Record tool versions/results. Missing installations or unavailable UNC/link
  facilities are unverified gates, not simulated passes; obtain explicit acceptance
  of any deferred required gate before marking implementation complete.
- No full suite, package install, freeze, or packaging run without user request.

## Implementation Steps

1. Review/approve operand rules, folder-root semantics, presets, and no default
   shortcuts; append review provenance before implementation.
2. Extract the minimal shared helpers without changing behavior. Immediately run
   the existing text-editor unit gate.
3. Implement pure operand/configuration/launch validation and focused comparator
   tests; run that module immediately.
4. Add independent setup wizards and persistence tests; rerun comparator/editor gates.
5. Wire commands, Qt snapshots, cancellation/staleness, and the per-window request
   bound; run command and native Qt gates.
6. Update Core/root README with setup, operand precedence/order, current-folder
   semantics, and the distinction from **Compare directories**. Add the implemented
   feature to CHANGELOG, preserving its API compatibility statement.
7. Run startup/manual gates, record results and accepted limitations, then complete
   this task document and move its canonical file/index entry to Done/Completed.

## Acceptance Criteria

- Four exact labels/IDs, no changed default shortcuts or public plug-in API.
- Independent persistent roles; cancel/clear/conflict/failure cannot overwrite
  other roles, editor/viewer settings, or unrelated configuration.
- Complete file-selection table; no silent fallback, counterpart guessing, batch,
  or wrong-type acceptance. Cross-pane order stays left/right; active-pair order
  is deterministic. Folder comparison always uses current locations.
- Same-object/missing/inaccessible/unsupported inputs fail clearly. Valid commands
  launch exactly two native paths, literal arguments, and no shell or exit wait.
- Invalid/unconfigured/canceled/stale requests do not launch; no GUI-thread metadata
  work, idle feature activity, unbounded replacement workers, Registry configuration,
  or automatic modifications to compared data.
- Planned unit/Qt regressions and source startup checks pass. External preset gates
  pass or have an explicitly accepted deferral; no unverified tool is claimed tested.
  README and CHANGELOG describe the implemented behavior before completion.

## Reviewers

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed independent setup wizards, active-pair then cross-pane file
  selection, current-root folder comparison, and bounded cancellable validation.
  Grounded in Core editor/viewer, pane/selection code, existing name comparison,
  and official comparator CLI references. Awaiting review before implementation;
  no runtime validation claimed for this design-only task.