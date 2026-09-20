# Search Files 002: File Name Only Search

Renamed to Search Files on 2026-09-20. Dated review and validation records below
retain the identifiers used at the time; current paths use `SearchFiles` / `search_files`.

## Task

Let Search Files (`Alt+F7`) list files by name alone. When the Content
Pattern box is empty and the File Name Pattern box is not, Search returns one
row per matching file instead of one row per matching line, using the same
ripgrep engine, the same Glob / Literal / RegEx name modes, the same recursion
toggle and the same results Table.

Also fix four defects reported against the shipped 001 results Table and Panel:

1. Content Glob mode matches whole lines: `Commander` and `?Commander?`
   return zero results while `*Commander*` returns eight, and the whole
   snippet is highlighted instead of the matched text.
2. Double-click or right-click > Go To on a File Path cell does not leave the
   file highlighted in the active pane.
3. Closing the results window puts keyboard focus on the Stop button.
4. The Content Pattern tooltip is not shown when hovering its label, and the
   Glob mode button's tooltip does not explain the matching rule.

Motivation: the Panel already has a filename filter with three modes, but it is
only a pre-filter for content search. Today an empty Content Pattern is rejected
with `Content Pattern is required`. Users who want "every `*.log` under here" or
"files whose name matches `^report_\d{4}`" have no ripgrep-backed option; the
fuzzy search plug-in has no glob or regex mode.

Follow-up to [Search Files 001](../Done/SearchFiles001.md).

## Scope

Included:

- Empty Content Pattern plus non-empty File Name Pattern runs a name-only
  search. Both empty remains an error (`Enter a file name or content pattern.`).
- All three existing name modes: Glob (`*.log;!*.tmp` masks), Literal
  (case-insensitive substring of the basename), RegEx (ripgrep regex on the
  basename), exactly as they filter today.
- Existing recursion toggle, row cap, Stop,
  status text, Limited/Incomplete marking, and the modal results Table with
  Copy Path / Go To.
- All name-only modes use `eligible()`: exclude dotfiles, Windows-hidden files
  and ancestors, symlinks/junctions, nonregular and oversized files. Binary and
  empty regular files remain eligible. Existing content-search eligibility is
  unchanged, including positive Glob masks admitting matching hidden files.
- Results rows show the relative path in the File Path column and an empty
  Snippet column. Enter / Go To navigates to the file as today.
- Bug 1: content Glob semantics in the engine
  ([engine.py](../src/main/resources/base/Plugins/SearchFiles/search_files/engine.py)).
- Bugs 2 and 3: focus after the modal Table closes, in the Table host
  ([facade.py](../src/main/python/fman/impl/ui/facade.py)).
- Bug 4: `TextField` label tooltip in `PanelForm.create` and the plug-in's
  mode-button tooltips.

Excluded:

- Any new control, mode, setting, shortcut or column. No date or size filters.
- Changes to content search when the Content Pattern is non-empty, other
  than the Glob semantics change in Bug 1; Literal and RegEx rows, limits
  and pipeline are untouched.
- Directory results: ripgrep `--files` lists files only, matching today's
  content search which never reports directories.
- Changes to public `fman` / `fman.ui` signatures or data types, packaging or
  the ripgrep dependency. Internal Table/Panel host fixes are explicitly included.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
`Options` dataclass gains no field; only its validation relaxes. Existing
The search options are unchanged. Current preferences use `SearchFiles.json`
with a fallback to legacy `SearchFileContent.json` overrides.

## Design

Application changes are inside
[search_files/engine.py](../src/main/resources/base/Plugins/SearchFiles/search_files/engine.py)
and [search_files/__init__.py](../src/main/resources/base/Plugins/SearchFiles/search_files/__init__.py),
plus [facade.py](../src/main/python/fman/impl/ui/facade.py) for internal Table/Panel
focus and tooltip behavior. Plug-in code uses only public APIs.

### Mode selection

`Options.__post_init__`: replace `if not self.content` with
`if not self.content and not self.name: raise ValueError('Enter a file name or
content pattern.')`. Keep the single-line check for a non-empty content. Add a
read-only property `names_only = not self.content`.

### Engine

`Runner.run` routes name-only searches through existing enumeration:

```
if options.names_only or options.name_mode != 'glob':
  self.search_filtered_names()
else:
    ... single --iglob content traversal   # unchanged
```

The enumeration and batching path reuses what exists:

- **Glob mode**: one child, `rg --files --null --no-config --no-ignore
  --no-follow [--max-depth 1] [--iglob <mask>]... -- <root>`. `--files`
  honours `--iglob` and `--max-depth`, so this is the existing enumeration
  command from `search_filtered_names` plus the masks already produced by
  `masks()`. Each NUL-terminated record goes through eligibility and then
  `Collector.accept_path`, publishing progress without waiting for enumeration
  to finish. No content or basename-filter child is needed.
- **Literal / RegEx mode**: enumerate with `--files --null` and batch into
  `search_batch`. In `search_batch`, after the basename filter and the
  existing `eligible()` check, when `options.names_only` call
  `Collector.accept_path(path)` for each accepted path and return instead of
  building the content-search argv. No content child is launched.

`Runner.preflight`: skip the content-pattern validation child
(`self.read_child(arguments + ['--', '-'], ..., b'')`) when `names_only`; the
name-pattern validation child runs as today for Literal / RegEx.

### Collector

Add `Collector.accept_path(path)`:

- Applies the same root-containment check as `make_hit`.
- Builds `Hit(path, relpath, line=0, column=0, offset=0, snippet='', spans=())`.
- Charges UTF-8 bytes of the native path, `as_url(path)` and relative path,
  plus 72 bytes reserved for the generated row ID/overhead, against
  `max_text_bytes`. This conservatively covers the public TableRow/Location
  payload without importing private TableSchema code into the plug-in.
  Increments `row_count` and `files`, and raises `Limited` at `max_rows`,
  retaining already accepted rows. Validate near-limit Unicode paths against
  the real Table schema in tests.

`max_file_lines` does not apply (one row per file).

### Progress and status

`Progress` is an immutable snapshot: publish after name-only collection, not
just during name-filter child output. `SearchSession.progress_text` and completion
change their noun from `matching lines` to `files` when `options.names_only`
(`'%d files, %.1f s'`). No other UI change; the Panel, Table and details
string (`path | 0:0` becomes `path`) are reused.

### Failure behaviour

Unchanged: Stop kills the live child and returns `Stopped` with collected
rows; enumeration errors set `Incomplete`; invalid regex is caught by the
existing name-pattern preflight child. Both patterns empty is a validation
error shown in the status bar without starting a process.

### Bug 1: content Glob is whole-line

`content_args` adds `--line-regexp` when `content_mode == 'glob'`, so a
content glob must match the *entire line*, the way a filename glob must match
the entire basename. Consequences observed by the user: `*Commander*` finds
eight lines, `Commander` and `?Commander?` find none, and because ripgrep's
submatch is the whole line, the Table highlights every snippet end to end.
The rule is only stated in a tooltip (see Bug 4). For content, users expect a
glob to match anywhere in the line, as the pane filter and every editor do.

Fix, in the engine only: content Glob becomes a *substring* glob.

- Remove `--line-regexp` from `content_args` for Glob mode.
- Translate with substring semantics: trim outer wildcard tokens, not arbitrary
  regex text, so `*Commander*` compiles to `Commander`; inner wildcards stay
  (`EF*Commander` -> `EF.*Commander`). Preserve `.*` for wildcard-only `*`/`**`:
  these match whole lines, including blank lines, without one empty submatch per
  character. Do not increase the transport limit. Bracketed stars remain literal.
- `Commander`, `*Commander*`, `Comm*der` and `?ommander` then all match the
  screenshot lines, and ripgrep's own submatch is the matched text, so the
  existing highlight is correct with no post-processing. Whole-line matching
  remains available through RegEx mode (`^Commander$`).

File Name Glob is unchanged: `--iglob` masks are whole-basename, which is what
`*.cmd` users expect.

### Bugs 2 and 3: focus after the results window closes

Both came from `TableWindow.cleanup`
([facade.py](../src/main/python/fman/impl/ui/facade.py)), which ran
`panel_session.focus_panel()` unconditionally and *before* the `on_closed`
callback.

- Bug 2: navigation works. `go_to` -> `navigate` -> Core `OpenDirectory` ->
  `set_path(dirname(url), callback=place_cursor_at)` under a tracked request
  (the same-directory short-circuit is skipped for tracked requests), so the
  cursor lands on the file. Then the modal closes and `focus_panel()` moves
  keyboard focus to the Panel; the pane has the current row but not focus, so
  the theme's `QTableView::item:focus` highlight is not drawn.
- Bug 3: `focus_panel()` picks the first visible *and enabled* control in the
  dock. While the Table is open the form is still disabled from the search;
  `results_closed` -> `enable_form()` runs only afterwards via `on_closed`.
  At focus time the only enabled control is Stop.

Fix in `cleanup`:

1. Record `self.navigated = True` on `go_to`'s success path before `close()`.
2. Fire the `on_closed` callback *before* deciding focus, so the plug-in has
   re-enabled its form.
3. After the callback, recheck the owner and visible, live main window. A panel
  must still be alive, own the current dock, and have no replacement Table.
  Another active modal blocks restoration.
4. If `navigated`, focus the still-live, visible and enabled pane widget with
  `setFocus(Qt.OtherFocusReason)`; otherwise call `panel.focus_panel()`, which
  now lands on the first text field. No deferred timer or public API is needed.

Modeless Tables with `close_on_navigate=False` retain their navigation behavior;
ordinary closure still receives the safe callback-before-focus ordering.

### Bug 4: undiscoverable tooltip

`PanelForm.create` ([facade.py](../src/main/python/fman/impl/ui/facade.py))
sets the `TextField` tooltip on the `QLineEdit` only; the visible
`QLabel('Content Pattern')` has none, so hovering the label shows nothing.
The `Choice` option tooltips are the bare words `Literal` / `Glob` / `RegEx`.

Fix: `create` also calls `label.setToolTip(record.tooltip or record.label)`
for `TextField`. The plug-in's `MODE_OPTIONS` tooltips become descriptive, and
the two `TextField` tooltips are reworded for the new semantics:

| Control | Tooltip |
| --- | --- |
| File Name Pattern | `Text within the name, globs matching the whole name (*.cmd;!*.bak), or a regular expression` |
| Content Pattern | `Text within the line, a glob matched anywhere in the line (Comm*der), or a regular expression; leave empty to list files by name` |
| Literal | `Literal text, case-insensitive` |
| Glob | `Glob: * any text, ? one character, [ab] a set` |
| RegEx | `Regular expression (ripgrep syntax), case-insensitive` |

## Alternatives

- New "Files only" toggle or a fourth mode: rejected; the empty Content box is
  an unambiguous, discoverable signal and adds no control.
- Reusing the content pipeline with pattern `^` and `--max-count 1`: simpler
  branch, but reads every file, skips empty and binary files, and reports a
  line rather than a file. Rejected.
- Emitting directories as well (`--files` cannot; would need `os.walk`):
  rejected as out of scope and inconsistent with content search.
- Rich Snippet (size, modified time): would need to retain eligibility metadata
  and define formatting; deferred, the column is simply empty. ripgrep `--files`
  emits paths only and rejects `--json`.
- Bug 1 via span narrowing in `make_hit` while keeping `--line-regexp`: fixes
  the highlight but not the zero-result surprise. Rejected in favour of
  substring semantics, which fixes both and removes code.
- Bug 1 via QSS or a delegate colour change: the colour is not the problem.
  Rejected.
- Bug 2 via `close_on_navigate=False` for content search: leaves the modal
  Table open over the pane, which contradicts the 001 design. Rejected.
- Bug 3 via keeping Stop disabled until after focus: fragile ordering in the
  plug-in; the host running `on_closed` first is the general fix. Rejected.

## Runtime Effects

- Unused path: none; no new settings, timers or workers.
- Name-only Glob: one ripgrep `--files` process, no file-content reads. Cost is
  directory traversal plus per-result file/ancestor metadata checks for eligibility.
- Name-only Literal / RegEx: retains enumeration, name preflight and bounded
  name-filter subprocesses, but omits all content children and content reads.
- Memory: bounded by the existing 10,000-row / 16 MiB caps; rows are smaller
  than content rows (no snippet).
- Cancellation, threading and process lifetime are the existing `Runner` /
  `Child` mechanisms.

## Tests

Focused commands using [build.py](../build.py)'s environment:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_unittest.test_search_files', 'fman_integrationtest.test_search_files_engine', '-v'], env=build._environment()))"
python -c "import build, os, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.SearchFilesIT', 'fman_integrationtest.test_qt.TableIT', 'fman_integrationtest.test_qt.PanelIT', '-v'], env=dict(build._environment(), QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))))"
```

- `Options`: empty content + name accepted; both empty rejected with the new
  message; non-empty content keeps the existing single-line validation.
- Engine (real ripgrep, temporary tree): for each of glob (`*.txt;!skip*`),
  literal (`report`) and regex (`^rep.*\.txt$`), name-only search returns
  exactly the expected relative paths, `line == 0`, empty snippet, no file
  contents read (fixture files are binary/empty and still listed).
- Recursion off lists the top level only. All name-only modes exclude hidden,
  oversized and nonregular files and hidden/reparse ancestors via `eligible()`.
- Row cap: `max_rows=3` over five matches returns `Limited` with three rows.
- Stop during enumeration returns `Stopped` and leaves no child process.
- Preflight: names-only skips the content validation child (assert one
  fewer `Popen` via the existing fake); invalid regex still fails before
  enumeration.
- `SearchFilesIT`: empty Content + `*.txt` opens the Table with File
  Path filled, Snippet empty, status text `Complete: N files`, Go To
  navigates to the file.
- Bug 1 (engine, real ripgrep): with content Glob over the line
  `echo PORTABLE EF Commander`, each of `Commander`, `*Commander*`,
  `Comm*der`, `?ommander` and `[Cc]ommander` matches and the span covers
  `Commander` only; `EF*Commander` spans `EF Commander`; `Commande` does not
  match `Commander` when written as `^Commande$` in RegEx (whole-line still
  available). `content_args` contains no `--line-regexp` in Glob mode.
  Literal and RegEx results are unchanged.
- Bugs 2 and 3 (`SearchFilesIT`): after Enter on a File Path cell the
  Table is closed, `QApplication.focusWidget()` is inside the target pane and
  `pane.get_file_under_cursor()` is the navigated file. After Escape, focus
  is on the File Name Pattern `QLineEdit`, not the Stop button, and the form
  is enabled. Assert `on_closed` ran before focus moved.
- Bug 4 (`PanelIT`): a `TextField` with a tooltip exposes it on both the
  `QLabel` and the `QLineEdit`; the plug-in test asserts the five tooltip
  strings above.
- Review regressions: wildcard-only Globs on blank/long lines and their spans;
  near-budget Unicode paths produce a usable Limited Table; hidden attributes,
  links and oversized files in every name-only mode; nonzero progress while
  enumeration is blocked; no surviving child after Stop or limits.
- Shared Table: ordinary close and successful navigation, modal/modeless modes,
  callbacks that close/replace panels, create a new Table or invalidate owners.
  Native Qt must retain focus only on live intended targets after disposal.

## Implementation Steps

1. Relax `Options` validation, add `names_only`; unit tests.
2. Add `Collector.accept_path`; add the `names_only` short-circuit in
  `search_batch` and glob masks to the shared enumeration child;
   wire the branch in `run` and skip the content preflight child; engine tests.
3. Adjust the status noun in `SearchSession`; extend `SearchFilesIT`.
4. Bug 1: drop `--line-regexp` and trim outer wildcard tokens, preserving a
  consuming wildcard-only pattern; engine tests.
5. Bugs 2 and 3: add the `navigated` flag to `TableWindow`, run `on_closed`
   before focusing, focus the pane after navigation; `SearchFilesIT`
   cases.
6. Bug 4: set the `TextField` label tooltip in `PanelForm.create`; update the
   plug-in's tooltip strings; `PanelIT` and plug-in tests.
7. Plug-in README: one paragraph under usage and the revised Glob rule;
   CHANGELOG `Added` entry for name-only search and `Fixed` entries for the
   four defects.

## Acceptance Criteria

- With an empty Content Pattern and a File Name Pattern, Search lists one row
  per matching file in the current Table, for Glob, Literal and RegEx modes,
  honouring the recursion toggle.
- Both boxes empty shows `Enter a file name or content pattern.` and starts no
  process.
- No file contents are read in name-only mode; binary and empty files are
  listed.
- Literal and RegEx content search is byte-for-byte unchanged in results.
- Content Glob matches anywhere in the line: `Commander`, `*Commander*` and
  `Comm*der` all find `echo PORTABLE EF Commander`, and only the matched text
  is highlighted. File Name Glob remains whole-basename.
- After Go To or double-click on a File Path cell, the Table closes and the
  target file is the highlighted current row in the focused pane. After
  Escape, focus is on the first text field and the form is enabled.
- Hovering the Content Pattern label or box shows its tooltip; the Glob mode
  button explains `*`, `?` and `[ab]`.
- Focused tests pass. Application changes are confined to SearchFiles and
  `fman/impl/ui/facade.py`, with focused tests, usage/changelog updates and this
  task's completion/index bookkeeping.

## Reviewers

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Initial design. Verified against `engine.py` that
  `search_filtered_names` / `search_batch` already enumerate with `--files
  --null`, filter basenames in all three modes and run `eligible()` before the
  content child, so name-only search is a short-circuit plus one `--files
  --iglob` child for Glob mode. Confirmed the bundled ripgrep 15.2.0 `--files`
  honours `--iglob` and `--max-depth`. No new control, setting or API.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Added two user-reported bugs from the shipped 001 Table with root
  causes traced in code. Bug 1: Glob content mode's `--line-regexp` makes
  ripgrep's submatch the whole line, so `make_hit` highlights every snippet
  end to end; fix narrows the span to the glob's literal segments, rendering
  unchanged. Bug 2: `TableWindow.cleanup` unconditionally calls
  `panel_session.focus_panel()` after a successful Go To, so the pane has the
  cursor but not focus and the theme's `:focus` row highlight is not drawn.
  Fixes are confined to the engine and the Table host; metadata in the
  Snippet column is deferred per user direction.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: User clarified Bug 1: the highlight colour is fine; only the span
  width is wrong. Removed the delegate/colour change; the fix is now span
  narrowing in `make_hit` for Glob content mode only. `table.py` is no longer
  touched and the `TableIT` pixel test was dropped.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: User reported that content Glob `Commander` and `?Commander?`
  return nothing while `*Commander*` returns eight lines, that closing the
  results focuses the Stop button, and that no tooltip explains the Glob rule.
  Root causes: `--line-regexp` makes content Glob whole-line (the same cause
  as the whole-snippet highlight); `TableWindow.cleanup` focuses the Panel
  before `on_closed` re-enables the form, so Stop is the only enabled
  control; `PanelForm.create` sets the `TextField` tooltip on the edit box
  only. Redesigned Bug 1 as substring Glob semantics (drop `--line-regexp`,
  strip outer `.*`), which supersedes span narrowing; merged the Stop-focus
  defect into the `cleanup` fix as Bug 3; added Bug 4 for the tooltips.
  Still no public API change; one line in `PanelForm.create` is the only
  addition to host scope.

  ### 2026_09_17 - GitHub Copilot

  - Role: Reviewer
  - Activity: Review
  - Agent: GitHub Copilot
  - Model: GPT-6 Astra
  - Effort: High
  - Context Window: Not exposed by host
  - Outcome: Needs revision before implementation. Reproduced wildcard-only Glob
    transport failure, result-budget undercount and name-only Glob eligibility
    mismatch. Progress publication and shared Table validation are also missing
    from the proposed changes. Application code and prior records are unchanged.

  #### Findings

  1. **P1: stripping outer wildcards can turn an ordinary search into a transport
    error.** Bug 1 converts `*` / `**` to an empty regex. Against one 100,000-character
    line, the proposed conversion made ripgrep emit 100,001 submatches and about
    4.88 MB of JSON. The existing 1 MiB record bound in
    [engine.py](../src/main/resources/base/Plugins/SearchFiles/search_files/engine.py)
    then returned `Error: Search transport record exceeds its size limit.` with
    no rows; the current `.*` whole-line search returned one complete result.
    Define wildcard-only behavior explicitly and preserve a nonempty consuming
    match for this case. Do not raise the transport limit to mask the expansion.
    Add real-ripgrep `*` / `**`, blank-line and long-line regressions, including
    the resulting highlight spans.
  2. **P1: the proposed row budget can discard the entire results window.**
    `72 + len(path) + len(relative_path)` counts characters rather than UTF-8
    bytes and omits the URL stored alongside the path in `Location`.
    [TableSchema.snapshot](../src/main/python/fman/impl/ui/table_data.py) counts
    the complete immutable Table payload. A 4,000-row Unicode-path probe charged
    4,772,000 bytes under the plan but 19,758,890 bytes in the Table, exceeding
    its 16 MiB cap. `SearchSession.completed` catches that rejection and displays
    `Could not show search results.` instead of the collected rows. Budget the
    actual row representation conservatively, including URL, path, relative path
    and ID, before accepting a row. Keep the plug-in's public-API-only boundary;
    add a regression feeding near-limit name-only results through the real Table
    schema and requiring a usable `Limited` result, not total presentation failure.
  3. **P2: name-only Glob bypasses the promised eligibility rules.** The proposed
    `--files --iglob` command has no size limit, and sends paths directly to
    `accept_path`, whose only filesystem check is containment. With a ten-byte
    configured limit, the exact command returned `visible.txt`, `.hidden.txt`
    and an eleven-byte `large.txt`; existing `Runner.eligible()` accepted only
    `visible.txt`. Apply eligibility before collection, preserving skipped/error
    accounting, or explicitly revise the contract. Positive `--iglob` also includes
    matching hidden files in today's Glob content search, unlike the filtered
    Literal/RegEx path; decide and document that policy instead of assuming the
    modes already agree. Cover oversized files, dotfiles, Windows hidden attributes
    and links in all three name-only modes.
  4. **P2: name-only progress is not a live view of collector counters.**
    `Progress` is an immutable snapshot, updated by `Runner.publish()`, normally
    called in `read_child()`. The new Glob enumeration does not use that JSON
    reader, and no publish call is specified after `accept_path`. Its displayed
    counts therefore stay unchanged until finalization. Literal/RegEx name-filter
    publication happens before the batch's accepted paths are collected, leaving
    counts behind there too. Publish after accepted batches, using the existing
    polling/status mechanism, and test nonzero progress while enumeration remains
    blocked. Merely changing the status noun does not implement live file counts.
  5. **P2: scope and validation omit the shared behavior being changed.** Scope
    excludes Table/Panel facade changes and Design says only two plug-in files
    change, yet Bugs 2-4 require shared `facade.py` changes. Declare that host
    scope consistently and include `TableIT`, not only `SearchFileContentIT` and
    `PanelIT`. Cover navigation and ordinary close, modal/modeless variants,
    close callbacks that close/replace the panel or invalidate the owner, and
    focus restoration only to still-live targets. The first listed command,
    `python -m unittest fman_unittest.test_search_file_content`, failed from the
    repository root with `ModuleNotFoundError: No module named 'fman_unittest'`.
    Replace the implicit PYTHONPATH prerequisite with the established
    `build._environment()` launcher and an explicit native Qt focus gate.

  #### Review Validation

  - Runtime probes used the installed ripgrep through `resolve_engine()` and
    disposable fixtures; no packages, virtual environments or application source
    edits were needed. The planned Glob conversion was simulated by overriding
    `Runner.content_pattern` and removing `--line-regexp` in memory only.
  - Eligibility reproduction used the exact proposed command:
    `rg --files --null --no-config --no-ignore --no-follow --iglob *.txt -- <root>`.
    The payload probe used 4,000 unique paths with three 180-character Unicode
    directory segments and the current `TableRow` / `Location` construction.
  - `_finished_callback` was verified to be synchronous. A native Windows
    `ToolWindow` probe confirmed that focusing the target during disposal survives
    modal close. Thus the ordinary focus reorder is plausible; it is not rejected
    as an asynchronous-callback bug. Full SearchSession navigation and reentrant
    close behavior still require the tests above.
  - The plan's first test command was run verbatim and failed at import as noted
    above. No full suite or freeze was run; the unimplemented feature is not claimed
    to pass tests. This is a plan review, not implementation approval.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Complexity assessment only. Filename-only search is low-to-moderate
  effort because enumeration, name filtering, child cancellation and result UI
  already exist. The combined task is moderate, with the highest regression risk
  in shared Table close/focus ordering and callback-driven panel/owner disposal.
  Content Glob changes require explicit wildcard-only semantics; tooltips are
  low effort. The five preceding findings remain unresolved and should be folded
  into the operative design before implementation, with engine and shared UI
  changes validated independently. Name-only avoids content reads but eligibility
  still performs file/ancestor metadata reads; Literal/RegEx retain name-filter
  subprocesses per batch. No new idle activity is needed. Assessment grounded in
  current Runner, Collector, SearchSession and Table/Panel host source; prior
  runtime reproductions were not rerun. No application edits or tests in this pass.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: User approved implementation. Resolved the five review gaps in the
  operative design: consuming wildcard-only Globs; UTF-8 path/URL result budgeting;
  consistent name-only eligibility with existing content policies preserved;
  explicit progress publication; declared shared host scope and native/reentrant
  focus tests. Reuse enumeration and batching without new public APIs. These
  decisions require the focused regression gates above before completion.

## Implementer

### 2026_09_17 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented filename-only enumeration in all three modes, eligibility,
  bounded UTF-8 Table payloads, live file counts and path-only details. Content
  Globs now use substring spans with consuming wildcard-only patterns. Shared
  Table cleanup restores focus after callbacks with live-target/replacement
  guards; labels and modes expose descriptive tooltips. Public APIs and settings
  are unchanged. All focused gates passed with one expected privilege skip.

### 2026_09_17 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation review; approved. Independently re-ran both focused
  gates in one process: 51 tests, OK, one symlink-privilege skip (5.8 s,
  offscreen). Verified against `engine.py`, `__init__.py` and
  `fman/impl/ui/facade.py` that the design and all five GPT-6 Astra findings
  are implemented: `Options` rejects only both-empty with the new message and
  exposes `names_only`; `run` routes name-only through `search_filtered_names`,
  whose `file_args` adds `--iglob` masks for Glob so one enumeration process
  covers all three modes; `search_batch` applies `eligible()` (hidden, size,
  nonregular, reparse ancestors) before `Collector.accept_path` and publishes
  progress per accepted path, so counts are live and policy matches the
  filtered content path; `accept_path` budgets UTF-8 bytes of path, URL and
  relative path (the `Location`/`TableRow` payload the Table will count) and
  raises `Limited` at the row cap; preflight skips the content child when
  name-only; `glob_to_regex(substring=True)` drops `--line-regexp`, strips
  outer `.*` and returns a consuming `.*` for wildcard-only patterns so
  `Commander`, `*Commander*` and `Comm*der` all match with the matched text as
  the span; `TableWindow.cleanup` runs `on_closed` first, then focuses the
  pane when `navigated` (guarded by owner, main-window, dock, live-target and
  active-modal checks) and otherwise `focus_panel()`, which now lands on the
  re-enabled first field; `PanelForm.create` sets the `TextField` tooltip on
  the label; the five tooltip strings match the design; `get_details` is
  path-only when `line == 0`; status noun switches to files. README, plug-in
  README and CHANGELOG (`Added` and `Fixed`) describe the change. No public
  `fman` API change. Observations, no action required: (1) `accept_path`
  marks `Limited` when exactly `max_rows` files exist, the same pre-existing
  semantics as the content path. (2) Name-only Glob calls `search_batch` once
  per enumerated path (no subprocess involved), which is fine but means
  `eligible()` walks ancestors per file; a per-directory memo would help only
  for very deep trees and is not needed now. (3) The `cleanup` guard chain is
  long; it is correct, but a short comment naming the three reentrant cases
  it protects against (panel replaced, owner invalidated, main window closed)
  would help future edits.

## Validation Results

The two exact commands in **Tests** were run from the repository root:

- Engine unit and real-ripgrep integration: **31 tests, 30 passed, 1 skipped**
  (5.306 s). Windows directory-symlink creation requires a privilege unavailable
  here; the separate junction regression passed, including all name-only modes.
- Native Windows `SearchFileContentIT`, `TableIT` and `PanelIT`: **20 passed**
  (2.422 s). Real binary-file search through Core navigation passed for Enter,
  double-click and context-menu Go To; Escape restored the first enabled field.
  Modal/modeless callbacks closing/replacing panels, replacing Tables, invalidating
  owners, deleting panes and closing the main window passed. Both label/input
  tooltips and all five plug-in tooltip strings were checked.
- Review regressions passed: 100,000-character and blank-line wildcard searches,
  Unicode rows at the 16 MiB boundary through the real Table schema, eligibility
  and recursion in every mode, row limits, preflight process counts, live progress
  during blocked enumeration, Stop and child-process cleanup. The existing
  10,000-row Table gate measured 0.038 s construction and 0.010 s fuzzy filtering
  on this run; these are local observations, not performance guarantees.
- Editor diagnostics reported no errors in the three application files and
  three touched test files. The public-only plug-in import regression passed.
- PowerShell local-link checks passed for the main/plugin READMEs, changelog and
  task document; all required task sections were present.
- Iteration failures were corrected and rerun: a test imported the plug-in's
  `Location` from `fman.ui`; an eligibility command used an incorrect test-class
  selector. Neither required a public API change.
- No full suite, clean, freeze, packaging, separate human visual inspection or
  new large-directory benchmark was run. Existing native workflow/geometry tests
  supply the focused UI checks; no release validation is implied.
