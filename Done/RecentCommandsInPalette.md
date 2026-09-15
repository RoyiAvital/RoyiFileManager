# Recent Commands in Command Palette

Status: Implemented on 2026-09-15; reload retention corrected and validated on
2026-09-16 after user approval of opt-in Config support.

## Task

Show the three most recently executed commands at the top of the Command
Palette (`Ctrl+Shift+P`) so repeated operations are one keystroke away.

Motivation: the palette currently restores only the single last query and
re-selects the last command. Users who alternate between a few commands must
retype or scroll every time. A short most-recently-used (MRU) block at the top
mirrors editors such as VS Code and costs nothing while the palette is closed.

## Scope

Included:

- `core.commands.CommandPalette` lists up to three recently executed palette
  commands first, most recent on top, followed by the existing ranked results
  with those commands removed.
- With a non-empty query, only recent commands whose alias matches the query
  stay pinned; non-matching recent commands are omitted like any other item.
- Recent rows carry a `Recent` marker in the existing hint field, after any
  shortcut text.
- Recording happens only when a command is executed from the palette. Both
  pane commands and application commands use a scoped `(kind, name)` identity.
- The MRU list is shared by all panes and windows of the process and persists
  across restarts in `Command Palette History.json` under `UserSettings`,
  using `load_json(..., save_on_quit=True, preserve_on_reload=True)`.
  Unsaved history survives plug-in loads/unloads and interrupted config reloads.
- Unregistered commands are pruned when the palette opens. Temporarily hidden
  commands are omitted from display without deleting their history.

Excluded:

- Recording commands triggered by shortcuts, menus, or other plug-ins.
- A user setting for the MRU size or a toggle to disable the feature.
- Changes to the QuickSearch widget, `QuicksearchItem`, section headers, icons,
  or any other palette-like UI (Go To, Favorites, Open With, Calculate File
  Hash By).
- Recording command arguments; entries contain only command kind and name.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5, the
`command_palette` command identifier and aliases, the `Ctrl+Shift+P` binding,
and the existing last-query/last-command cursor restoration.

## Design

Ownership stays inside the Core plug-in, in
[core/commands/__init__.py](../src/main/resources/base/Plugins/Core/core/commands/__init__.py).
The 2026-09-16 reload fix adds opt-in Config retention and public `load_json`
forwarding with user approval. QuickSearch and command registries are unchanged.

### Data

- `_RECENT_COMMANDS_LIMIT = 3` module constant.
- `_recent_commands(registered=None, executed=None)` uses the lock from public
  `fman.ui.settings_resource('Command Palette History.json')`. Loading, pruning
  and recording run under that lock on the existing command thread.
- Load with `default={'recent': []}` before registering save-on-quit. Only valid
  dict roots are registered with `preserve_on_reload=True`. Config retains those
  cached values through any plug-in directory add/remove without rereading them.
  Ordinary settings use the existing reload path. Catch `OSError`, `ValueError` and `TypeError`;
  unreadable or wrong-root history uses a session-only dict held by the named
  resource. Do not attempt to repair or overwrite the bad file.
- Entries are `{'kind': 'pane'|'application', 'name': <identifier>}`. Inspect at
  most 256 entries, reject blank names or names over 256 characters, deduplicate
  in MRU order and retain at most three. No legacy string format was shipped.
- Replace only the cached dict's `recent` value with a fresh plain list; preserve
  the dict identity and other keys. Readers receive immutable identity tuples.
- Registry pruning uses both unfiltered registries, never the display list.
  Recording prepends the selected scoped identity before command execution.
  The named resource also preserves synchronization and fallback across reloads.

### Suggestion order

`CommandPalette._suggest_commands(query)`:

1. Capture history in `__call__`, before opening the modal; no history loading,
  pruning or locking occurs in the suggestion callback.
2. Build the existing ranked suggestions using unchanged alias/matcher precedence
  and per-tier sorting. Each `CommandPaletteItem` also carries its command kind.
3. Index matched rows by scoped identity. Emit matching recent rows in MRU order
  with shortcut text followed by ` · Recent`, or just `Recent` without a shortcut.
4. Append ranked rows excluding the identities already emitted. Empty history
  leaves the existing suggestions unchanged.

Retain last-query and last-command restoration, adding command kind to the cursor
identity so equal pane/application names cannot select the wrong row. A restored
non-empty query still filters the recent block; cancelling clears the restored
query/selection, not history.

### Threading and failure behavior

- History I/O and updates run on command threads. QuickSearch invokes suggestion
  callbacks on Qt; these read only the captured tuple. Do not hold the history
  lock across the modal or command execution. No workers or timers are added.
- Bad history cannot block opening. Save failures follow Config's existing
  quit-time handling. Valid history uses cached save-on-quit and survives reloads
  even if the palette is not reopened before exit. History file edits are read
  next launch, not on plug-in reload; explicit `save_json` still replaces cached
  state. Cross-process writes retain host last-writer semantics.
- A `DirectoryPaneListener.on_command` rewrite changes the executed command
  after recording; the palette records the name the user selected.

### Public API usage

The palette uses only public API: `show_quicksearch`, `QuicksearchItem`,
`load_json`, `pane.get_commands`, `pane.is_command_visible`,
`pane.get_command_aliases`, `pane.run_command`, `get_application_commands`,
`get_application_command_aliases`, `run_application_command`. `load_json` gains
an optional keyword-only `preserve_on_reload=False`; all existing calls remain
compatible and retain their default behavior. The public `settings_resource` API supplies the
reload-stable lock and fallback. Other QuickSearch providers are not wrapped or
modified. The only new settings artifact is `Command Palette History.json`.

## Alternatives

- Record every pane command through a `DirectoryPaneListener.on_command`
  listener: captures shortcut-triggered commands too, but floods the list with
  cursor movement and `open_directory`, needs a visibility/alias filter, and
  misses application commands, which bypass listeners. Rejected for noise.
- Session-only MRU in a module variable: zero persistence surface, but loses
  the list on every restart. Rejected for valid history; retained only as the
  non-destructive fallback for unreadable or wrong-root history.
- Immediate `save_json` on each execution: adds a synchronous UserSettings
  write to a user-facing command for no benefit over save-on-quit. Rejected.
- Rendering a section header or separator row: needs QuickSearch widget
  changes and a non-selectable item concept that the public API lacks. The
  hint marker achieves the distinction without host changes. Rejected.
- Boosting recent commands within the ranking instead of pinning: subtler but
  invisible to the user and harder to test; the request is an explicit top
  block. Rejected.
- Wrapping only Core's reload/install/remove commands to restore history:
  misses other plug-ins calling the public load/unload API. Rejected in favor
  of opt-in Config retention at the actual cache-reload boundary.
- Changing all save-on-quit settings to retain memory across reloads: would
  change existing settings refresh behavior. Rejected; retention defaults off.

## Runtime Effects

- Startup: none. The JSON is first loaded when the palette opens, then served
  from the host cache.
- Steady state: existing matching plus an O(number of matched rows) index and
  O(3) recent lookup per query on Qt; no new timers, threads or recurring signals.
- Memory: three bounded scoped identities, an immutable per-open snapshot and
  the cached JSON dict. The public JSON loader still reads the whole file;
  normalization inspects at most 256 entries off Qt.
- I/O: one small write at application quit through the existing
  `Config.on_quit` save-on-quit path; no writes during the session.
- Config retention: one filename in a set after opt-in; cache reload carries
  retained values forward before reading ordinary settings. No new threads,
  signals, timers or writes. With no opted-in names, normal settings still reload.
- Cancellation: not applicable; no long-running work.
- Disabled/no-op path: not applicable; the feature has no toggle. With an
  empty history the palette output is byte-for-byte the current output.

## Tests

Focused commands from the repository root:

```powershell
python -c "import build, subprocess, sys; environment = dict(build._environment(), QT_QPA_PLATFORM='offscreen'); sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'unittest', 'fman_integrationtest.impl.plugins.test_config', 'core.tests.commands.test___init__', 'fman_integrationtest.test_qt.CommandPaletteRecentIT', '-q'], env=environment))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', '-m', 'fman_integrationtest.recent_commands_smoke'], env=build._environment()))"
```

`CommandPaletteHistoryTest` and `CommandPaletteRecentTest` in
[core/tests/commands/test___init__.py](../src/main/resources/base/Plugins/Core/core/tests/commands/test___init__.py)
use real Config fixtures and a `Mock` pane whose `get_commands`, `is_command_visible`,
`get_command_aliases` and `run_command` are stubbed, patching
`core.commands.load_json`, `core.commands.get_application_commands`,
`core.commands.get_application_command_aliases` and
`core.commands.show_quicksearch`:

- Empty history: suggestion titles and order equal the pre-change ranking.
- Executing a command from the palette records it; cancelling the palette
  records nothing.
- Order is most recent first; repeating a command moves it to the top without
  duplicates; the fourth distinct command evicts the oldest.
- Recent items appear first and are excluded from the tiered results below.
- Non-empty query: only recent commands with a matching alias stay pinned;
  the rest of the ranking is unchanged.
- Recent hint equals `<shortcut> · Recent` with a shortcut and `Recent` without.
- Missing identities are pruned; visible -> hidden -> visible pane contexts
  preserve history and redisplay the item when it becomes visible again.
- Application commands are recorded and displayed like pane commands.
- Real Config coverage: malformed JSON, null/list roots and read failures use
  session-only fallback without registering a bad root for save-on-quit. Valid
  dicts normalize malformed entries and preserve dict identity and other keys.
- Duplicate pane/application names retain both rows and correct execution targets.
- Oversized/repeated entries are bounded before any execution. Concurrent
  recording/pruning uses the same named lock; no updates are lost or duplicated.
- Quit/restart round-trip, zero session writes, and reload-stable named resource
  synchronization/fallback. Saved-A -> record-B -> reload -> quit without reopening
  retains B. Default-path settings, explicit save replacement, missing/failed loads,
  and unrelated reload errors have real Config regression coverage.
- Cursor restoration: with `_last_cmd_name` set and empty last query, the
  initial item index is 0; with a non-empty last query it still resolves to
  the last command's position.
- The loaded dict object identity is preserved after recording (in-place
  mutation, required for save-on-quit).

The native smoke performs the manual workflow with temporary UserSettings:
run three harmless pane commands from the real palette, reopen, confirm the
block and filtering, exit and restart. On the second launch, update history,
run real Reload Plugins and quit without reopening the palette; a third launch
checks the unsaved entry survived. It also verifies a non-palette command
is not recorded and the Sort By Column picker has unchanged hints. Screenshots
and bundled hint widths are checked at 100%, 150% and 200% scaling.

## Implementation Steps

1. Add the locked, bounded history helper and real Config regression coverage;
  run the history tests immediately.
2. Wire history snapshots, scoped item identity, recent ranking and recording
  into CommandPalette; test unchanged baseline, matching, dispatch and cursor.
3. Run Qt integration for callback affinity and real widget layout, plus native
  startup/restart smoke in temporary UserSettings. Verify other providers stay
  unchanged. Check bundled long labels/multiple shortcuts at 100/150/200%.
4. Update `CHANGELOG.md` (Unreleased, Added) and add one README line under the
   features list describing the recent block.

## Acceptance Criteria

- Opening the palette after running commands A, B, C from it shows C, B, A at
  the top, each marked `Recent`, followed by the normal ranked list without
  duplicates of A, B, C.
- Typing a query keeps only matching recent commands pinned above the ranked
  results.
- Running a fourth command evicts the oldest; rerunning an existing recent
  command moves it to the top.
- The block survives an application restart via `Command Palette History.json`
  under `UserSettings`; no writes occur during the session.
- Unsaved history survives all plug-in directory add/remove paths and remains
  available if another settings file interrupts reload; exit persists it even
  without reopening the palette. Ordinary settings still reload as before.
- Missing commands are pruned. Hidden commands do not appear but remain in history.
- Unreadable/wrong-root history never blocks opening or overwrites the bad file;
  that fallback lasts for the process and does not promise restart persistence.
- Duplicate registry names stay distinct; history is bounded before display.
- History loading/updates never run in Qt suggestion callbacks. Concurrent
  record/prune operations serialize without holding a lock across the modal.
- With an empty history the palette output and cursor restoration are
  unchanged from the current release.
- `python -m unittest core.tests.commands.test___init__` passes.
- Host changes are limited to Config retention and its `load_json` forwarding;
  existing public calls remain compatible. Shared QuickSearch widgets, command
  registries and other picker behavior are unchanged.

## Reviewers

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Initial design. Verified against `CommandPalette._suggest_commands`,
  `CommandPaletteItem`, `Config.load_json`/`save_on_quit` and the
  `Visited Paths.json` precedent in `core/commands/goto.py`. Confined to the
  Core plug-in using public API only; no host or QuickSearch widget changes.
  Open user decisions: persist across restarts (designed) versus session-only,
  and whether shortcut-triggered commands should also count (rejected here for
  noise).

### 2026_09_14 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: User decisions recorded: the MRU list is persistent
  (`Command Palette History.json`, save-on-quit) and records only commands
  executed from the palette; shortcut-triggered commands are out of scope for
  simplicity. Both match the designed text; no section changes required.
  Design approved for implementation.

  ### 2026_09_14 - GitHub Copilot

  - Role: Reviewer
  - Activity: Review
  - Agent: GitHub Copilot
  - Model: GPT-6 Astra
  - Effort: Medium
  - Context Window: Not exposed by host
  - Outcome: Requires revisions before implementation. Verified the public config
    forwarding path, palette matching, separate command registries and Qt callback
    dispatch. Persistence recovery, context-sensitive pruning, threading, command
    identity and load-time bounds need the changes below. No application code changed.

  #### Findings

  1. **P1: History failures can prevent the palette from opening.**
    [Config.load_json](../src/main/python/fman/impl/plugins/config.py#L22)
    supplies the default only when loading returns None. Malformed JSON raises
    `JSONDecodeError`; JSON `null` raises `TypeError` in the file loader. A valid
    root list remains a list in the cache, so replacing a local variable with a
    dict does not repair the object saved on quit. The differential writer also
    rejects replacing a stored list with a dict. Define an explicit recoverable
    session-only fallback for unreadable/wrong-root-type history, or an approved
    repair mechanism; do not promise in-place type conversion. Test real Config
    behavior, read errors and quit/restart, not only mocked `load_json` values.

  2. **P2: Display filtering must not delete temporarily hidden history.**
    [_get_all_commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L1248)
    already removes commands hidden for the invoking pane. Pruning against its
    index would permanently forget a local-only command merely because the user
    opens the palette in an archive or another unsupported context. Skip hidden
    entries for display without deleting them; only prune commands absent from
    the unfiltered registries. Add a visible -> hidden -> visible regression
    across two pane contexts that preserves the shared MRU entry.

  3. **P2: The single-command-thread assumption is incorrect.**
    [show_quicksearch](../src/main/python/fman/impl/widgets.py#L443) marshals to
    the Qt thread, where [Quicksearch._update_items](../src/main/python/fman/impl/quicksearch.py#L107)
    invokes the provider synchronously on initialization and text changes.
    Initial cursor lookup and recording also call the proposed helpers from
    command threads. Config's lock protects loading, not mutations of the returned
    list. Specify synchronized snapshot/update ownership; keep disk loading off
    the Qt callback and avoid holding a lock while opening the modal. Cover
    concurrent recording/pruning and actual callback thread affinity, and correct
    the Runtime Effects section accordingly.

  4. **P2: A name-only index conflates pane and application commands.**
    The [registries](../src/main/python/fman/impl/plugins/command_registry.py#L19)
    have independent namespaces. The existing palette can display both commands
    with the same name; indexing by name collapses them, and name-based exclusion
    can hide one or pin the wrong command. Persist and compare a plain scoped
    identity such as `(kind, name)`, without recording arguments or changing the
    public API. Test duplicate names with distinct aliases and execution targets,
    including the promised unchanged output when history is empty.

  5. **P2: Normalize valid history on load, not just after execution.**
    A list of strings currently passes validation regardless of length or
    duplicates. Step 2 would pin every entry, violating the three-row bound before
    the next execution; duplicate names can also produce duplicate recent rows.
    Deduplicate in MRU order, discard empty/invalid identifiers and cap to three
    before display. Specify a sensible identifier length bound and test oversized
    lists and repeated entries without executing a command first.

  #### Review Validation

  - Ran `python -` with in-memory `Config` and `CommandPalette` probes using
    `unittest.mock`; no application settings or source files were written.
  - Mocked file contents `{`, `null` and `[]` respectively produced
    `JSONDecodeError`, `TypeError` and a cached list. A local dict replacement did
    not update that cache; differential list-to-dict saving raised `ValueError`.
  - A pane command and application command both named `same_name` produced two
    existing palette rows but only one name-index entry. A registered hidden
    command was absent from the display index.
  - Thread dispatch verified from the decorated host entry point and synchronous
    Quicksearch provider invocation. Concurrency and proposed MRU behavior have
    not been executed because the feature is not implemented. No test suite run.

### 2026_09_15 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Visual preview only; implementation remains blocked by the preceding
  review. The feature can be confined to Core's CommandPalette, without changing
  the shared QuickSearch widget, public API, Go To, Favorites, Open With or
  Calculate File Hash By. This is an ownership constraint, not proof that the
  unimplemented persistence and concurrency behavior is safe.

#### Required Before Implementation

- Resolve all five preceding findings: recoverable history loading, retention of
  temporarily hidden entries, synchronized snapshots without Qt-thread disk I/O,
  scoped pane/application identity, and normalization to three unique entries.
- Keep last-query restoration explicit: reopening with a non-empty query shows
  only matching recent commands, not necessarily all three.
- Test long aliases and multiple shortcuts with the longer hint. The existing
  renderer draws title and hint independently without reserving separate space;
  sample rows fit, but arbitrary plug-in aliases are not guaranteed to fit.
  Do not change the shared renderer as part of this task without scope approval.

#### Preview and Validation

- Rendered the existing Quicksearch widget with the shipped Windows theme,
  sample commands, and `Recent` appended after shortcut text. Empty-query and
  `file` previews show three and two recent rows respectively. No headers,
  icons, theme changes, command execution or history persistence were added.
- Preview/probe script and PNGs are disposable artifacts under `target/`, not
  application implementation. The preview used temporary UserSettings.
- Ran:

  ```powershell
  python -c "import build, subprocess, sys; environment = dict(build._environment(), QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1'); sys.exit(subprocess.call([sys.executable, '-X', 'faulthandler', 'target/recent_commands_preview.py'], env=environment))"
  ```

- Passed real Config probes for malformed JSON, null and list roots; confirmed
  list-to-dict differential writes fail. Confirmed duplicate pane/application
  names remain distinct and hidden commands remain registered but undisplayed.
- Passed native preview checks: provider runs on the Qt thread, sample titles
  and hints do not overlap, and no pane commands execute. Both screenshots were
  inspected. An initial dialog-only harness failure was fixed within the
  disposable script by disconnecting its unused pane-refresh activation hook.
- Full persistence, concurrency, reload, high-DPI and other-picker regression
  tests remain implementation gates; they were not run for this preview.

### 2026_09_15 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: User approved the preview and implementation. Revised design resolves
  the five prior findings using Core-local snapshots and the public named resource
  lock, scoped identities, bounded normalization, non-destructive fallback and
  unfiltered-registry pruning. Acceptance criteria are testable. No shared host
  edits are authorized; arbitrary oversized alias rendering retains the existing
  widget limitation, with bundled labels and multiple shortcuts checked here.

### 2026_09_15 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review; approved. Verified against the code that all
  five earlier findings are resolved: recoverable loading with a session-only
  fallback that never registers a bad root for save-on-quit, pruning against
  the unfiltered pane/application registries with hidden commands retained,
  history captured on the command thread before `show_quicksearch` and only the
  immutable `self._recent` tuple read in the Qt callback, `(kind, name)`
  identities carried by `CommandPaletteItem.identity`, and bounded
  normalization (256 inspected, 3 retained, deduplicated, trimmed names).
  Confirmed `Config._reload_cache` keeps the cached dict identity across plug-in
  reloads because save-on-quit is registered, so the in-place `recent`
  replacement survives `ReloadPlugins`. Reran the documented focused command:
  81 tests, OK. Corrected a hyphen in the changelog entry. Non-blocking
  follow-ups:
  - [ ] Move the session-only fallback dict off the host-owned `Resource`
    instance (currently a private attribute that works only because
    `Resource` has no `__slots__`) into a Core-owned holder that still
    survives Core reloads.
  - [ ] Decide whether pruning should be permanent: a command whose plug-in
    fails to load on one start is dropped from saved history at the next
    palette open and does not return when the plug-in loads again.
  - [ ] Reset `_last_cmd_kind` together with `_last_cmd_name` on cancel;
    harmless today because `_last_cmd_name` gates cursor restoration.
  - [ ] Provenance: the implementer and two preceding review records use
    `Not exposed by host` for Model and Context Window although a developer
    signature was assigned in PRROMPT.md; records are append-only, so this is
    noted for future records rather than rewritten.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: 272K
- Outcome: Reviewed Fable 5.1's approval and follow-ups. Normal palette behavior
  remains covered, but the claim that dictionary identity preserves unsaved
  history through plug-in reloads is too strong. Reproduced the missing case;
  no application or test files changed. Attribution follows the Developer
  convention in [PRROMPT.md](../PRROMPT.md), not independent host verification.

#### Reload Clarification

- **P2:** [Config._reload_cache](../src/main/python/fman/impl/plugins/config.py#L68)
  keeps a dict's identity but clears and replaces its contents when an on-disk
  dict exists. With saved history `copy`, recording `paste` gives
  `[paste, copy]`; adding a plug-in config directory restores `[copy]`.
  The next quit can therefore save history without the session's newer entry.
- [The existing reload test](../src/main/resources/base/Plugins/Core/core/tests/commands/test___init__.py#L91)
  calls `on_quit()` before reloading, so it tests already-saved state rather than
  retention of unsaved changes. Add the saved-A -> record-B -> reload regression
  before treating reload persistence as guaranteed. The design's host-reload
  caveat remains applicable; Fable's stronger approval statement does not.
- Validation: ran a `python -c` probe through `build._environment()` using real
  Config and `_recent_commands`, with `mock_open` supplying the saved JSON and
  an isolated Resource. Asserted before `(('pane', 'paste'), ('pane', 'copy'))`,
  after `(('pane', 'copy'),)`, and identical dict objects. No real settings I/O.
  An initial shell-quoted JSON fixture failed before the reload; generating JSON
  with `json.dumps` fixed the probe. No test suite rerun was needed for this review.

Reproduction from the repository root:

```powershell
$probe = @'
import json
from unittest.mock import mock_open, patch
from core.commands import _recent_commands, _COMMAND_PALETTE_HISTORY
from fman.impl.plugins.config import Config
from fman.ui import Resource
config = Config('Windows')
config.add_dir('fixture')
disk = json.dumps(dict(recent=[dict(kind='pane', name='copy')]))
with patch('builtins.open', mock_open(read_data=disk)), patch('core.commands.load_json', side_effect=config.load_json), patch('fman.ui.settings_resource', return_value=Resource()):
    assert _recent_commands() == (('pane', 'copy'),)
    document = config.load_json(_COMMAND_PALETTE_HISTORY)
    assert _recent_commands(executed=('pane', 'paste')) == (('pane', 'paste'), ('pane', 'copy'))
    config.add_dir('another_plugin')
    assert _recent_commands() == (('pane', 'copy'),)
    assert document is config.load_json(_COMMAND_PALETTE_HISTORY)
    print('Confirmed: unsaved history lost; dict identity preserved.')
'@
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-c', sys.argv[1]], env=build._environment()))" $probe
```

#### Follow-up Assessment

- Resource ownership: valid maintainability concern, not a current runtime
  failure. A Core-owned replacement must preserve shared state and locking under
  the actual plug-in unload lifecycle, not only `importlib.reload`.
- Pruning: permanent removal is the current explicit design, not an accidental
  implementation mismatch. Retaining temporarily unavailable plug-in commands
  would be a deliberate policy change; recommend skipping them without deleting
  history if recovery after a failed plug-in load is preferred.
- Cancel state: resetting `_last_cmd_kind` is harmless cleanup. The empty
  `_last_cmd_name` already prevents an incorrect cursor restoration.
- Provenance: preserve historical records. Future records can use the assigned
  Developer attribution convention where host metadata is unavailable.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: User authorized a simple shared fix covering all plug-in operations.
  Approved opt-in `load_json(..., preserve_on_reload=True)` retention in Config;
  default callers retain existing reload semantics. Palette history opts in only
  after root validation. The failing saved-A -> record-B -> reload -> quit test
  proves the defect without reopening the palette. Require opt-in/default-path,
  API forwarding, failed-load, native reload and restart regressions. Preserve
  pruning policy; Resource fallback ownership remains a non-blocking follow-up.

## Implementer

### 2026_09_15 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented Core-local recent history and palette ranking with scoped
  identities, immutable per-open snapshots, reload-stable synchronization and
  non-destructive fallback. Preserved existing matcher/alias precedence, shortcut
  hints and query/selection restoration. README and Unreleased changelog updated.
  Passed 81 focused tests and native record/restart runs at three scale factors.
  No shared host or public API implementation files changed.

### 2026_09_16 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Fixed unsaved history loss with the approved opt-in Config retention
  and backward-compatible `load_json` keyword. Retained values survive directory
  changes and unrelated reload failures without disk I/O; default settings still
  refresh. Reset scoped cursor state on cancel. Passed 119 focused tests and
  nine native record/reload/restart runs across three scales. Updated API docs,
  README and the Unreleased feature entry; pruning and Resource fallback policy
  remain unchanged.

## Validation Results

### 2026_09_15 - Initial Implementation

- Both commands in Tests passed. The combined Core command module and focused
  Qt run passed 81 tests, including 26 new history/palette unit tests and one new
  Qt integration test. The first substantive storage change was immediately
  checked with `CommandPaletteHistoryTest` (9 tests at that stage).
- Real Config tests cover quit/restart, no session writes, malformed JSON,
  wrong roots, permission errors, normalization, bounds and dict identity.
  Concurrent update/prune tests retain all three unique identities. The isolated
  reload probe verifies the same named resource and fallback survive Core reload;
  valid cached-dict identity is also checked through Config reload.
- Native Windows smoke passed six application runs: record then restore at
  `QT_SCALE_FACTOR=1`, `1.5` and `2`. Each checked 68 bundled command hint widths,
  recent filtering, absence of duplicate rows and unchanged Sort picker hints.
  History was absent on disk during recording and present on the next launch.
  The 100% and 200% restored-palette screenshots were visually inspected.
- Qt callbacks were verified on the Qt thread and history loading off it.
  A separate plain QuickSearch provider retained its original items and hints.
- Development harness failures were repaired and rerun: an indentation error,
  startup column readiness race, and an in-process module-reload test that
  invalidated older tests' class mocks. Reload testing now runs in a child process.
- Expected warnings: offscreen Qt font-directory and `propagateSizeHints`
  messages. No package or environment changes were made. Editor diagnostics
  reported no errors in the changed Python files.
- No full suite, freeze, packaging, external downloads or release-note validation
  was run. Arbitrarily long third-party aliases/custom fonts retain the shared
  widget's existing title/hint layout limitation; no host renderer change was
  made. Multi-process writes and external config reloads retain host semantics.

### 2026_09_16 - Reload Retention

- Ran the two current commands in Tests. Config + Core command + Qt palette tests:
  **119 passed**. Native Windows smoke: record -> real Reload Plugins -> immediate
  quit -> restart passed at 100%, 150% and 200% (nine application runs).
- Red/green regression command:

  ```powershell
  python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.commands.test___init__.CommandPaletteHistoryTest.test_unsaved_history_survives_plugin_reload_and_quit', '-v'], env=build._environment()))"
  ```

  Failed before the fix (Paste lost, only Copy saved), then passed. History file
  bytes remain unchanged until quit. No palette reopening is needed to restore it.
- Added Config coverage for default dictionary/list reload behavior, opt-in
  retention with no reload I/O or implicit writes, explicit `save_json`
  replacement, missing/failed loads, interrupted reloads, lists/scalars and public
  API forwarding. Existing positional `load_json` calls remain valid.
- The cancelled palette now resets `_last_cmd_kind` together with query/name;
  the scoped cursor regression checks all three fields.
- Editor diagnostics found no errors in changed Python files. Offscreen font
  and `propagateSizeHints` warnings are unchanged. No installs, environment
  changes, full suite, freeze, packaging or release-note validation were run.
- Pruning policy remains unchanged. The Resource fallback holder remains a
  non-blocking ownership follow-up; no new lifetime abstraction was introduced.
  Retained history ignores external file edits until restart; save-on-quit still
  has the host's cross-process and failure semantics.
