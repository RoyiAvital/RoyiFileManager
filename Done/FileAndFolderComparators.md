# File and Folder Comparators

## Task

Add external file/folder comparator setup wizards, following the text editor/viewer
workflow, and **Compare files** / **Compare folders** commands with predictable
operand selection.

Status: implemented and validated on 2026-09-20. The user explicitly accepted
deferral of live vendor/new-window and unavailable UNC/link checks. Those limits
remain unverified, not simulated passes; see Validation Results.

## Scope

- Windows commands: **Set file comparator**, **Set folder comparator**,
  **Compare files**, and **Compare folders**. No default shortcuts in this change;
  all commands support user bindings and appear in Command Center.
- Independent executable/argument settings. Built-in presets, in order: Meld,
  Beyond Compare, WinMerge, SmartSynchronize; then manual configuration and
  clearing either role. Built-in means configuration, not bundled applications.
- Aim for a separate top-level comparison window on every invocation. Use
  documented switches/defaults without changing global tool preferences; do not
  equate a new tab or a transient launcher process with a new window.
- Existing local files/folders, including accessible UNC paths and filesystem
  links to the appropriate target type. Binary files are allowed; rendering and
  format support belong to the selected tool, not every preset supports a hex view.
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
  settings, pre-launch validation and fire-and-forget launching.
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
  folder preset explicitly requests recursion. Meld and SmartSynchronize support
  recursive directory comparison; their filters and Beyond Compare/manual
  traversal/comparison settings remain under the application's control.

### Wizard and Settings

1. Both role wizards offer **Meld**, **Beyond Compare**, **WinMerge**,
   **SmartSynchronize**, **Manual configuration**, then **Clear file comparator**
   or **Clear folder comparator**, in that order.
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

Setup snapshots/commits and launch-time deep copies share `_settings_lock`.
Release it before dialogs, operand validation or process launch; each request
uses an independent configuration snapshot.

### Built-in CLI Presets

CLI research checked on 2026-09-20. These are fixed argument arrays; append the
two absolute file paths for **Compare files**, or the two current directory paths
for **Compare folders**, in left/right order. Do not embed quoting in array items:
the launcher passes `[executable, *arguments, left_path, right_path]` without a shell.
Select the actual installed `.exe`; executable names below are picker guidance,
not installation discovery or hard-coded paths.

| Preset | User-selected executable | File arguments | Folder arguments | New-window strategy |
| --- | --- | --- | --- | --- |
| Meld | `Meld.exe` | `[]` | `[]` | Default invocation opens a new window; omit `--newtab`. |
| Beyond Compare | `BCompare.exe` | `["/solo"]` | `["/solo"]` | `/solo` forces a new instance. |
| WinMerge | `WinMergeU.exe` | `["/s-", "/u"]` | `["/s-", "/u", "/r"]` | `/s-` forces another instance, overriding single-instance preferences. |
| SmartSynchronize | `smartsynchronize.exe` | `[]` | `[]` | Two-path invocation; no force-new-window switch found in the cited manual. Verify window behavior. |

- **Meld:** [CLI help](https://meldmerge.org/help/command-line.html) documents
  `meld file1 file2` and `meld dir1 dir2`. The
  [3.24.0 argument handler](https://gitlab.gnome.org/GNOME/meld/-/blob/3.24.0/meld/meldapp.py)
  defaults `--newtab` to false and creates a new window for a forwarded invocation
  unless that option is supplied. A separate process is unnecessary. Do not invent
  a `--new-window` flag or use `--auto-merge`/`--output`.
- **Beyond Compare:** the [v5 CLI reference](https://www.scootersoftware.com/v5help/command_line_reference.html)
  documents two files opening their associated comparison view, two folders opening
  Folder Compare, and `/solo` forcing a new instance. Do not force Text Compare,
  which would override file-type handling. Use the main GUI executable, not the
  blocking `BComp.com` launcher; omit `/sync`, `/automerge` and script arguments.
- **WinMerge:** the [CLI reference](https://manual.winmerge.org/en/Command_line.html)
  documents `/s-`, `/u` (omit operand paths from recent-path lists), and `/r`
  (recursive folder comparison). `/s` reuses an instance, `/sw` also waits, and
  `/new` opens a blank window; none substitutes for `/s-` with two operands.
  Do not use auto-merge, auto-close, report, or preference-changing `/cfg` switches.
- **SmartSynchronize:** [Starting SmartSynchronize](https://docs.syntevo.com/SmartSynchronize/Latest/Manual/Starting.html#command-line-parameters)
  documents two positional files opening File Compare and two positional directories
  opening Directory Compare. It also documents `--file-compare`/`--dir-compare`
  with `--left=<path>` and `--right=<path>`; prefer the equally documented positional
  form to keep the existing final-two-operands contract. Do not add placeholders,
  mode switches or an undocumented instance flag. Its
  [directory comparison](https://docs.syntevo.com/SmartSynchronize/Latest/Manual/Directory-compare.html)
  is recursive; launching a comparison must not trigger synchronization. The manual
  labels `Latest` as in development, so installed-version checks are required.

New-window behavior is a preset goal, not a generic launcher guarantee. Test both
cold launch and repeated calls while a comparison is open, including the same pair
twice. For SmartSynchronize, new-window behavior remains unverified: if an installed
version reuses a window, record that limitation and obtain explicit acceptance or
find a documented per-call option before claiming this goal is met. Do not alter
global preferences, create temporary profiles, or kill/restart another instance.
Manual configuration remains user-controlled. No comparator was launched during
this documentation-only research; source/documentation evidence is not a runtime pass.

### Validation and Launch

- First resolve selection shape and URL syntax. Unconfigured roles then point to
  their **Set ... comparator** command without opening a wizard, resolving paths
  or performing metadata checks. Invalid settings give configuration advice.
- Use `fman.fs.resolve`, accept only resulting `file://` URLs, and convert with
  `fman.url` helpers inside the cancellable validation Task: resolution can itself
  perform filesystem I/O. No extraction, downloads, or directory scans.
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
  and cursors as immutable data. Workers validate only captured paths; active-pair
  mode ignores the other pane entirely. No pane lifecycle subscriptions or model hooks.
- User clarification (2026-09-20): use a simple fire-and-forget launch. Later focus,
  marks, navigation, reload or pane closure do not retarget or cancel the captured
  pair. Recheck the paths themselves before launch, not the panes' current state.
- Use the existing cancellable `Task` infrastructure for potentially slow metadata
  checks. Check explicit cancellation before and after metadata calls and just
  before `Popen`. Release validation state on every exit, including `Task.Canceled`;
  display errors through existing safe Qt dispatch.
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
- **Force a separate process for every tool:** unnecessary when a shared process
  creates independent windows, as Meld does. Prefer supported window behavior and
  `/solo` or `/s-` where provided; avoid global preference edits or speculative flags.

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
  RoyiFileManager work. Separate instances for Beyond Compare/WinMerge can increase
  external startup time and memory with each call; users close them independently.
  No automatic tool download or installation.

## Tests

Coverage uses [comparator tests](../src/main/resources/base/Plugins/Core/core/tests/test_comparator.py),
the [editor tests](../src/main/resources/base/Plugins/Core/core/tests/test_text_editor.py)
and [Qt test harness](../src/integrationtest/python/fman_integrationtest/test_qt.py).
Executed gates and accepted limitations are recorded in Validation Results.

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
- Launch settings regression: both roles load and deep-copy under the shared lock,
  release it before submitting validation, and retain independent argument lists
  when the source configuration changes.
- Preset tests: exact four-item order and executable guidance in both wizards;
  assert all eight argument arrays from the CLI table and final left/right operands.
  Meld must omit `--newtab`; Beyond Compare must retain `/solo`; WinMerge must
  retain `/s-` and `/u`, with `/r` only for folders. SmartSynchronize uses positional
  paths without invented window flags. Mocked argv tests cannot prove real windows.
- Launch tests: literal argv, spaces/quotes/Unicode/braces/percent signs, trailing
  backslashes, empty arguments, NULs, total UTF-16 length, non-`.exe`/missing programs,
  and launch errors. A real child `sys.executable` records received arguments to
  prove both paths arrive intact. No third-party comparator is needed for CI.
- Preserve all editor/viewer parser/preset/legacy launch tests and existing command
  IDs. Add a regression proving `compare_directories` still marks missing names.
- Add `ComparatorIT` to the existing Qt module: actual pane marks/cursors, both
  focus directions, all command labels/IDs, folder roots, wizard cancel/select/clear,
  persistence, and GUI-thread snapshots versus worker-thread metadata.
- Use events to block a fake metadata call; verify Qt remains responsive, later
  pane changes do not retarget the captured pair, explicit cancellation suppresses
  launch, duplicate requests cannot add validation workers, and every exit releases
  the pending slot. No lifecycle callbacks or sleep-based timing assertions.
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

- Run `fman_integrationtest.comparator_smoke` through `build._environment()` with
  `QT_QPA_PLATFORM=windows`. It uses the normal source application context and
  plug-in loader in two fresh processes, disposable `ROYIFILEMANAGER_USER_SETTINGS`
  and fixture directories: registration, missing-configuration advice, both
  wizards, restart persistence, clearing one role and real child argv handoff.
  Editor/viewer commands are covered by the separate native Qt regression gate.
- With available Meld, Beyond Compare, WinMerge and SmartSynchronize installations,
  run both presets for different/equal files, an active-pane pair, current folders,
  paths with spaces and Unicode, root paths and opposite focus. Check nested folder
  differences, including WinMerge's explicit recursion. For binary files record
  the tool's supported view or limitation; do not promise text-only tools a hex view.
- For each tool and role: launch once while closed, then again with the first
  comparison still open, using both the same pair and a different pair. Confirm a
  distinct top-level comparison window, correct left/right operands, and the first
  comparison remaining intact. For WinMerge also enable its single-instance
  preference manually for the test and verify `/s-` overrides it. Count windows,
  not processes; Meld may share a process. Record SmartSynchronize reuse explicitly.
- Verify interactive comparison, no automatic operand writes or synchronization,
  unchanged tool preferences, no exit wait, and application responsiveness while
  tools run. Check cancellation before handoff still suppresses every preset.
- Record tool versions/results. Missing installations or unavailable UNC/link
  facilities are unverified gates, not simulated passes; obtain explicit acceptance
  of any deferred required gate before marking implementation complete.
- No full suite, package install, freeze, or packaging run without user request.

## Implementation Steps

1. Review/approve operand rules, folder-root semantics, the four CLI presets and
  new-window checks/SmartSynchronize limitation, and no default shortcuts; append
  review provenance before implementation.
2. Extract the minimal shared helpers without changing behavior. Immediately run
   the existing text-editor unit gate.
3. Implement pure operand/configuration/launch validation and focused comparator
   tests; run that module immediately.
4. Add independent setup wizards and persistence tests; rerun comparator/editor gates.
5. Wire commands, Qt snapshots, explicit cancellation, and the per-window request
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
- Both wizards offer Meld, Beyond Compare, WinMerge and SmartSynchronize in the
  requested order and store the exact role-specific arrays above. Repeated calls
  open separate comparison windows with tested versions, or any tool-specific
  limitation is explicitly accepted and documented; no global preference changes.
- Complete file-selection table; no silent fallback, counterpart guessing, batch,
  or wrong-type acceptance. Cross-pane order stays left/right; active-pair order
  is deterministic. Folder comparison always uses current locations.
- Same-object/missing/inaccessible/unsupported inputs fail clearly. Valid commands
  launch exactly two native paths, literal arguments, and no shell or exit wait.
- Invalid/unconfigured/explicitly canceled requests do not launch; no GUI-thread metadata
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

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Expanded both presets lists to Meld, Beyond Compare, WinMerge and
  SmartSynchronize. Checked official CLI references and Meld 3.24.0 source for
  two-path invocation and new-window behavior; selected `/solo`, `/s-`, and Meld's
  default window behavior. SmartSynchronize has no force-window switch in the
  cited manual; repeated-launch validation or explicit limitation acceptance is
  required. Updated test/acceptance gates only; no code or runtime tests changed.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: User approved proceeding with implementation. Reviewed the editor/viewer
  parser and tests; preserve their behavior while extracting only shared validation.
  Operand precedence, independent settings, literal two-path argv and bounded,
  cancellable metadata checks remain the implementation contract. Tool-specific
  new-window claims require actual manual validation or explicit accepted deferral.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: User clarified that comparison should be a simple fire-and-forget launch.
  Removed the proposed pane lifecycle cancellation requirement and need for a host
  hook. Capture paths once; later navigation does not retarget or cancel that pair.
  Retain explicit Task cancellation for slow pre-launch checks, and never wait for,
  monitor or terminate the external comparator after handoff.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Reviewed the implemented fire-and-forget boundary. Resolution is inside
  cancellable worker validation because the filesystem resolver can perform I/O;
  unset roles do no resolution/stat work. Unit/native Qt and source/restart gates
  pass. User explicitly accepted deferral of live vendor/window behavior and
  unavailable UNC/link checks; no third-party GUI behavior is claimed verified.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review of `core/comparator.py`, `core/external_program.py`,
  the four commands in `core/commands/__init__.py`, `core/tests/test_comparator.py`,
  `ComparatorIT`, `comparator_smoke.py`, Core README, root README and CHANGELOG.
  Code matches the design: decision table in `select_operands`, six-option wizard
  order, all eight preset argument arrays, `deepcopy` + conflict check under
  `_settings_lock`, `os.stat`/`samestat` identity in the worker, `_check_argv`
  with `shell=False`, one `_pending` token per window released in `finally`.
  Offscreen gate `core.tests.test_comparator core.tests.commands.test___init__
  fman_integrationtest.test_qt.ComparatorIT` passed: 114 tests, 1 expected skip.
  Approved with notes, none blocking:
  1. Bookkeeping defect: `Plan/FileAndFolderComparators.md` still exists and is
     byte-identical to this file; the task file was copied, not moved. Delete the
     `Plan/` copy.
  2. `validate_operands` rejects `st_ino == 0`. On Windows Python fills `st_ino`
     from the file index, which is 0 on some filesystems and virtual drives
     (e.g. certain FAT/exFAT or cloud-drive providers). Comparisons there fail
     with "Cannot determine the identity". Acceptable for the design's alias
     rule, but worth a README caveat or a fallback to normalized-path equality.
  3. `compare()` reads `_load_settings()` outside `_settings_lock`; harmless
     today since the wizard is Qt-thread synchronous, but inconsistent with
     `configure`.
  4. `configure` validates via `_check_argv`, so setup fails if the executable
     path is temporarily absent (e.g. unmounted drive); intended per design.
  5. `_capture` sets the pending token only after `select_operands` succeeds, so
     early errors leave no token; correct. `_release` is a linear scan of
     `_pending`, fine for the window count involved.
  Deferral of live vendor GUI, UNC and privileged-link checks stands as
  previously accepted by the user.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Accepted notes 1-3 from the implementation review. The stale Plan copy
  contained no unique text; Done additionally held the latest review. Remove the
  duplicate and retain the existing Completed index link. Document unknown file
  identity rather than weakening same-object rejection: normalized paths cannot
  reliably identify hard links or every filesystem alias. Protect the launch
  settings snapshot with the existing wizard lock. Notes 4-5 describe intended
  executable validation and correct pending-token handling; no changes needed.
  Existing external-tool/UNC/link deferrals remain unchanged.

## Implementer

### 2026_09_20 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Added four lazily delegated Core commands, independent conflict-aware
  setup wizards and all eight role/preset argument arrays. Added deterministic
  pane snapshots, filesystem identity/type validation and literal nonblocking
  launches with explicit pre-launch cancellation. Extracted only shared Windows
  parser/validators, preserving editor/viewer behavior. Added focused unit/native
  Qt coverage and normal-loader source/restart smoke; updated usage and changelog.
  Final gate: 137 passed, 1 expected skip. No pane lifecycle hooks or API changes.

### 2026_09_20 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Locked the launch-time settings read/deep copy and added a regression
  for both roles, snapshot independence and release before validation. Removed
  the redundant Plan copy and documented the zero-identity limitation in Core's
  README. The new regression failed before the fix and passed afterward; the
  comparator unit/native Qt gate passed 27 tests with 1 expected skip. No public
  API, selection rules or fire-and-forget behavior changed. No separate changelog
  fix entry is needed for this still-unreleased feature.

## Validation Results

Windows, existing Python/PyQt environment; no new package or environment. All
commands ran from the repository root. The first shared-helper gate passed
20 editor/viewer tests. Comparator slice gates passed after each implementation
step. Two Qt fixture defects (missing `sys` import and an invalid progress palette)
were fixed; the native five-test comparator class then passed.

Exact decisive commands:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.test_text_editor', '-q'], env=build._environment(), timeout=60).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.test_comparator', 'core.tests.test_text_editor', 'core.tests.commands.test___init__', 'fman_integrationtest.test_qt.ComparatorIT', 'fman_integrationtest.test_qt.TextEditorIT', '-q'], env=env, timeout=120).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'fman_integrationtest.comparator_smoke'], env=env, timeout=100).returncode)"
git diff --check -- Plan.md Done/FileAndFolderComparators.md CHANGELOG.md src/main/resources/base/Plugins/Core src/integrationtest/python/fman_integrationtest/test_qt.py src/integrationtest/python/fman_integrationtest/comparator_smoke.py
```

- Final regression gate: 138 tests, 137 passed, 1 expected Windows symlink-privilege
  skip. Covers all presets/roles, real Windows argv, independent settings and
  conflicts, clear/reload persistence, operand rules, hard-link identity, errors,
  Qt-thread snapshots, off-thread validation, explicit cancellation and slot cleanup.
- Source smoke passed in two fresh application processes with normal plug-in
  discovery and disposable UserSettings: command registration, no default bindings,
  unset advice, both setup wizards, restart persistence, clearing one role, and
  actual file/folder operands received by a harmless Python recorder child.
  Commands returned while that child remained alive; test cleanup alone killed it.
- Warm local capture-to-launch measurements: file comparison 0.0058 s, folder
  comparison 0.0055 s, restarted folder comparison 0.0078 s. Informational only;
  no comparison work or third-party GUI startup was awaited.
- Checked diagnostics are clear. Scoped diff checks pass. Root README retains
  unrelated pre-existing trailing whitespace; no unrelated formatting was changed.
- `Get-Command Meld.exe, BCompare.exe, WinMergeU.exe, smartsynchronize.exe
  -ErrorAction SilentlyContinue` found none on PATH; this does not establish that
  they are not installed elsewhere. The user chose **Defer the external-tool checks**.
  Their actual GUI formats, cold/repeated-window behavior, SmartSynchronize reuse,
  UNC shares and unavailable privileged link cases remain unverified.
- No full suite, installer, Registry configuration, freeze or packaging run.

### Implementation Review Follow-up (2026-09-20)

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.test_comparator.ComparatorCommandTest.test_settings_snapshot_is_locked_and_independent_before_validation', '-q'], env=build._environment(), timeout=60).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.test_comparator', 'fman_integrationtest.test_qt.ComparatorIT', '-q'], env=env, timeout=120).returncode)"
```

- The new regression first failed at the unlocked settings read for both roles,
  then passed after the fix. The full focused gate ran 28 tests: 27 passed and
  1 expected Windows symlink-privilege skip. Existing tests retain rejection of
  unknown identity and hard-link aliases, and cover wizard conflict/persistence,
  explicit cancellation, pending-slot release and native Qt interaction.
- The two task documents differed only by the later review in Done; no Plan-only
  content was lost. The Completed index already points to the canonical Done file.
- Source/restart smoke and live vendor checks were not rerun for this narrow
  settings-lock/documentation follow-up. Previously accepted deferrals stand;
  no full suite, packaging or dependency changes.