# Recent Commands in Command Palette

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
  pane commands and application commands are recorded by command name.
- The MRU list is shared by all panes and windows of the process and persists
  across restarts in `Command Palette History.json` under `UserSettings`,
  using `load_json(..., save_on_quit=True)` like `Visited Paths.json`.
- Commands that no longer exist or are not visible for the invoking pane are
  skipped at display time and pruned from the stored list.

Excluded:

- Recording commands triggered by shortcuts, menus, or other plug-ins.
- A user setting for the MRU size or a toggle to disable the feature.
- Changes to the QuickSearch widget, `QuicksearchItem`, section headers, icons,
  or any other palette-like UI (Go To, Favorites, Open With, Calculate File
  Hash By).
- Recording command arguments; entries are command names only.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5, the
`command_palette` command identifier and aliases, the `Ctrl+Shift+P` binding,
and the existing last-query/last-command cursor restoration.

## Design

Ownership stays inside the Core plug-in, in
[core/commands/__init__.py](../src/main/resources/base/Plugins/Core/core/commands/__init__.py).
The host (`fman/__init__.py`, `fman.impl.quicksearch`, `command_registry`) is
not changed.

### Data

- `_RECENT_COMMANDS_LIMIT = 3` module constant.
- `_recent_commands()` returns the cached list from
  `load_json('Command Palette History.json', default={'recent': []}, save_on_quit=True)`.
  If the loaded value is not a dict with a `recent` list of strings, the helper
  resets it in place to `[]`. The cached object must be mutated in place so the
  host's save-on-quit hook writes the current contents.
- `_record_recent_command(name)` removes `name` if present, inserts it at index
  0 and truncates to the limit. Called from `CommandPalette.__call__` right
  before `command()` executes, alongside the existing `_last_cmd_name` update.

### Suggestion order

`CommandPalette._suggest_commands(query)`:

1. Build `commands = self._get_all_commands()` once (unchanged helper). Index
   it by command name.
2. For each name in the recent list, in order: skip and prune if the name is
   not in the index. Match the aliases with the existing `_MATCHERS`; the first
   alias/matcher pair that matches produces a `QuicksearchItem` whose hint is
   the shortcut text followed by ` · Recent` (or just `Recent` when no
   shortcut). If no alias matches the query, the item is omitted.
3. Run the existing tiered matching over the remaining commands, excluding names
   already emitted in step 2, and keep the current per-tier sort.
4. Return recent items followed by the tiered results.

The existing `__call__` cursor restoration is unchanged: it searches the same
suggestion list for `_last_cmd_name`, so the last command is item 0 when the
last query is empty and is otherwise found in its usual position.

### Threading and failure behavior

- All work runs on the command thread that already executes `CommandPalette`;
  no timers, workers, or Qt objects are added.
- `load_json` failures (corrupt file) surface as the host's default value or a
  reset list; the palette must never fail to open because of history state.
- A `DirectoryPaneListener.on_command` rewrite changes the executed command
  after recording; the palette records the name the user selected.

### Public API usage

The palette uses only public API: `show_quicksearch`, `QuicksearchItem`,
`load_json`, `pane.get_commands`, `pane.is_command_visible`,
`pane.get_command_aliases`, `pane.run_command`, `get_application_commands`,
`get_application_command_aliases`, `run_application_command`. None of these
signatures change, so other QuickSearch consumers and third-party plug-ins are
unaffected. The only new artifact is the `Command Palette History.json` user
settings file.

## Alternatives

- Record every pane command through a `DirectoryPaneListener.on_command`
  listener: captures shortcut-triggered commands too, but floods the list with
  cursor movement and `open_directory`, needs a visibility/alias filter, and
  misses application commands, which bypass listeners. Rejected for noise.
- Session-only MRU in a module variable: zero persistence surface, but loses
  the list on every restart while `save_on_quit` already provides free,
  I/O-free persistence. Rejected; persistence is the expected behavior.
- Immediate `save_json` on each execution: adds a synchronous UserSettings
  write to a user-facing command for no benefit over save-on-quit. Rejected.
- Rendering a section header or separator row: needs QuickSearch widget
  changes and a non-selectable item concept that the public API lacks. The
  hint marker achieves the distinction without host changes. Rejected.
- Boosting recent commands within the ranking instead of pinning: subtler but
  invisible to the user and harder to test; the request is an explicit top
  block. Rejected.

## Runtime Effects

- Startup: none. The JSON is first loaded when the palette opens, then served
  from the host cache.
- Steady state: an O(3) list scan and one dictionary index per palette query
  keystroke, on the existing command thread; no timers, threads, signals, or Qt
  allocations.
- Memory: at most three short strings plus the cached JSON dict.
- I/O: one small write at application quit through the existing
  `Config.on_quit` save-on-quit path; no writes during the session.
- Cancellation: not applicable; no long-running work.
- Disabled/no-op path: not applicable; the feature has no toggle. With an
  empty history the palette output is byte-for-byte the current output.

## Tests

Focused command (from the repository root, PYTHONPATH as in `build.py`):

```powershell
$env:PYTHONPATH = @('src/main/python', 'src/unittest/python',
    'src/main/resources/base/Plugins/Core') -join ';'
python -m unittest core.tests.commands.test___init__
```

Add `CommandPaletteRecentTest` to
[core/tests/commands/test___init__.py](../src/main/resources/base/Plugins/Core/core/tests/commands/test___init__.py)
with a `Mock` pane whose `get_commands`, `is_command_visible`,
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
- A recorded name that is missing or `is_command_visible` returns False is
  skipped and removed from the stored list.
- Application commands are recorded and displayed like pane commands.
- Corrupt history (`None`, list, dict without `recent`, non-string entries)
  is reset in place and does not raise.
- Cursor restoration: with `_last_cmd_name` set and empty last query, the
  initial item index is 0; with a non-empty last query it still resolves to
  the last command's position.
- The loaded dict object identity is preserved after recording (in-place
  mutation, required for save-on-quit).

Manual check: open the palette, run three different commands, reopen and
confirm the block, hint marker and cursor position; restart the application
and confirm the block persists.

## Implementation Steps

1. Add `_RECENT_COMMANDS_LIMIT`, `_recent_commands()` and
   `_record_recent_command()` with validation and in-place reset; unit test
   validation and eviction.
2. Refactor `_suggest_commands` to index commands by name, emit pinned recent
   items with the `Recent` hint, and exclude them from the tiered results;
   run the focused command.
3. Record the executed command in `CommandPalette.__call__`; add the
   execution/cancel and cursor restoration tests.
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
- Missing or hidden commands never appear and are pruned from the file.
- With an empty history the palette output and cursor restoration are
  unchanged from the current release.
- `python -m unittest core.tests.commands.test___init__` passes.
- No file under `src/main/python/fman` changes; the public `fman` API is
  untouched.

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
