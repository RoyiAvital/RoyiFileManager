# UI Elements 003: QuickBoard

Status: Implemented and locally validated on 2026-10-06 after user authorization
on 2026-10-05. Portable-artifact and physical mixed-monitor checks remain
unverified. The Batch Renamer plug-in remains a separate task.

## Task

Provide a reusable, Qt-free UI element that helps a user compose one string
through a caller-generated, typed tabular preview. Preserve the compact,
buttonless interaction and appearance of the existing Quick elements.

## Overview and Concept

QuickBoard assists the user in composing a string through a caller-generated
tabular preview. The string is the result; the rows are feedback, not operation
targets or returned selections.

### API

```python
text, accepted = show_quick_board(
  owner=owner,
  columns=columns,
  get_rows=get_rows,
  text="",
  title="",
    summary="",
)
```

| Argument      | Contract                                                              |
| ------------- | --------------------------------------------------------------------- |
| `owner`       | Existing plug-in `UiOwner`; invalidation cancels the board.            |
| `columns`     | Fixed `QuickTableColumn` descriptors; unspecified types mean text.     |
| `get_rows`    | `get_rows(text)` returns an iterable of `QuickTableRow` records.        |
| `text`        | Initial string, empty by default; returned without trimming.           |
| `title`       | Window title supplied by the caller.                                  |
| `summary`     | Optional plain secondary text; its meaning belongs to the caller.     |

Reuse the existing column types, formatting, highlights and per-column
`filterable` / `sortable` options. There is no separate row-ID system, public
widget, mutable handle, operation callback or QuickBoard-specific row class.
Use the existing table bounds: 1-64 columns, at most 10,000 rows and 16 MiB of
text per preview. Input is single-line, at most 4,096 UTF-16 code units, matching
Qt's field limit without silently truncating astral characters.
Title and summary limits are 512 and 2,048 characters. Reject NUL in all three
strings and CR/LF in initial text; preserve spaces and the exact draft on cancel.
`summary` matches QuickList/QuickTable. Unlike `show_prompt`, cancellation retains
the draft rather than returning an empty string. No `description` alias is added.

### Interaction

- Use QuickTable's window, theme, typography, table and filter menus. Its text
  filter is replaced by the composition field; there is no second search field.
- Show the optional summary in the same secondary-text style as the other
  Quick elements. No dedicated syntax controls, help drawer, reset button,
  custom title strip or operation-specific footer are required.
- Call the row handler initially and when the text changes. Replace the complete
  preview; keep column filters and ordering, which affect presentation only.
- Enter closes with `(text, True)`. While a preview/projection is pending, it
  requests acceptance of that exact input revision after successful publication.
  Any subsequent text edit, failure, cancellation or invalidation clears it.
  Esc or window close returns `(text, False)`,
  including the text entered before cancellation. Both work from the input or
  table; an open column-filter menu handles its own Enter/Esc first.
- Empty previews are valid. Row selection, sorting and filtering never alter
  the returned string or silently redefine the caller's operation targets.
- The call blocks until the board closes. The window is modal to its owning
  application window. Owner invalidation or application-window closure cancels
  it and releases the caller.
- Keep the framed `Qt.Dialog` window and QuickTable dimensions/margins. The input
  starts focused; Up/Down/Page Up/Page Down move focus into the table. Tab and
  Shift+Tab move between input and table; Ctrl+F focuses/selects the input, and
  Alt+Down opens the current column filter. No pane argument or Go To action:
  path cells are preview data; Copy uses the displayed cell text.

### Preview Contract

Construct the schema, including the captured `LocalDates`/reentrant `QTimeZone`
value, on Qt. A dedicated `LatestJobs(capacity=1)` lane per admitted board runs
the initial callback only after the window is shown, and retains at most one
latest pending input. The callback, iterable consumption, numeric formatters and
snapshot validation all run off Qt, with cancellation checks during validation
and before/after caller code. Qt receives only the validated immutable snapshot;
formatters are never called again during publication. Callers must not access
widgets, mutate shared state or perform filesystem mutations from callbacks.

Two process-wide QuickBoard leases bound open boards and closed boards whose
worker has not finished. Reserve before construction/thread creation; an open
board retains its lease even when its lane is idle. Closing releases it only
after the lane drains, including start-failure paths. This conservative limit
bounds all active callbacks, not merely dead boards, without using the two
shared Panel/navigation worker slots. Saturation shows a short alert and returns
`(initial_text, False)` without calling the handler. Modal-only presentation
remains; simultaneous independent programmatic callers are still accounted for.

Keep old rows unchanged during work and show `Updating...` in a reserved board
status label; no delegate dimming or custom theme. Store preview failure
separately from `Table.error` so sorting/filtering cannot clear it. `ValueError`
is plain inline feedback; other exceptions additionally use an owned host alert.
Failure clears queued acceptance; Escape remains immediate. Acceptance requires
the same input revision, a successful preview and the corresponding settled
table projection. No row/status text is interpreted as validity or operation
policy. A new text edit cancels acceptance even if the later string is identical.

Closing drops pending work and rejects late results without waiting on Qt.
It cannot forcibly interrupt a running Python callback or OS call. Callers must
bound work and use timeouts for I/O; captured metadata or a prepared sample is
preferable to scanning a filesystem on every keystroke. No preview jobs or
recurring activity exist before opening the board.

### File Management Use Cases

The example strings below belong to their plug-ins. QuickBoard does not define
their grammar, variables, expansion, validation or execution.

| Use case                       | Example string                         | Caller-generated preview                    |
| ------------------------------ | -------------------------------------- | ------------------------------------------- |
| Batch rename                   | `{name}_{index:03d}.{ext}`              | Original name, proposed name, status        |
| Copy/move destination template | `{modified:%Y-%m}/{ext}/{name}.{ext}`   | Source, destination, conflicts              |
| File-list export format        | `{name}\t{size}\t{modified:%Y-%m-%d}`   | Source file, generated output line          |
| Saved search query             | `ext:pdf size:>10mb`                    | Matching paths, sizes, dates                |
| Include/exclude patterns       | `*.tmp;*.bak;cache*`                    | Entry, included/excluded, matching pattern  |
| External-tool arguments        | `--output "{name}.txt" "{path}"`        | File, expanded arguments, validation        |

All fit the same text-to-rows contract. The caller captures its data/context,
supplies a summary and handler, then interprets the accepted string.
If the preview is sampled or limited, the caller states that in its summary
or row data; visible rows are never implied to be the complete operation scope.
Filesystem freshness, collisions, safe quoting and confirmation before mutation
remain the caller's responsibility after acceptance.

Streaming search results and unbounded remote jobs need a separate lifecycle;
the callback is not a general search-job API. Selecting files belongs to
QuickList/QuickTable, and multiple independent inputs belong to a Panel.

## Scope

- Include the generic string input, plain summary, typed preview, optional
  per-column filtering/sorting, blocking result and owner-bound lifetime.
- Keep the existing QuickTable appearance and reuse its data descriptors and
  rendering. Leave QuickSearch, QuickList and QuickTable return contracts intact.
- Exclude editable cells, returned selections, operation buttons, syntax engines,
  variable registries, syntax-specific help and filesystem mutations.
- Exclude implementation of any consumer plug-in, including Batch Rename.
- Add the public service through `fman.ui`; third-party consumers must not need
  Qt imports, host-private fields or another bundled plug-in's internals.

## Design

### Ownership and Data Flow

- Public export: [fman/ui.py](../src/main/python/fman/ui.py). Host presentation
  and lifetime live in [quick_board.py](../src/main/python/fman/impl/ui/quick_board.py),
  alongside [facade.py](../src/main/python/fman/impl/ui/facade.py).
  Reuse [table.py](../src/main/python/fman/impl/ui/table.py) and
  [table_data.py](../src/main/python/fman/impl/ui/table_data.py); do not fork a
  second table renderer or change the meaning of QuickTable's filter field.
- Capture the callback, text and input revision on Qt. Materialize bounded plain
  rows on the worker. Publish only a matching revision into the Qt-owned model,
  then apply the host's retained column filters and sort order.
- Add internal `Table.replace_rows(snapshot)`: close stale menus, invalidate
  pending projection work, replace the snapshot, clear identity-based sort keys
  and matches, preserve filters/sort/current column, and reproject. QuickTable's
  public immutable API and its ordinary construction path remain unchanged.
- The board owns a separate composition field. Construct the shared table with
  `text_filter=None` and keep `Table.query` hidden and empty. Clear All Filters
  and Ctrl+F must never erase or search-match the composition string.
- Deliver worker results through alive/owner-guarded `ToolWindow.post`. Add only
  the closed-lane callback needed to release the dedicated admission lease to
  `LatestJobs`; existing pane lanes retain their defaults and behavior.
- Acceptance is tied to the current input and completed projection, not row IDs,
  row selection, visible counts or strings in a status column. Return the exact
  input on either outcome. Mutations happen only in the caller after return.
- Use the existing loader-assigned `UiOwner` contract. Host window closure and
  owner invalidation request cancellation on Qt; stop accepting work immediately
  and release the waiting caller independently of any slow preview callback.
- Match the existing blocking UI services: workers wait for their own result;
  a Qt caller requires a local event loop, never a blocking thread wait on Qt.
- Persistence: not applicable. Text, preview rows, filters and ordering are
  dialog state only. A plug-in may separately persist an accepted string through
  the existing public settings API under `UserSettings`.

### Review Resolutions

| Feedback | Resolution |
| --- | --- |
| R1, F6 | Use `summary`; retain `(text, accepted)` and exact draft on cancel as explicitly requested by the user. Apply the existing title/summary limits and single-line text validation. |
| R2, R13, F3 | Reuse one LatestJobs lane per board with two dedicated process-wide leases covering open and retiring boards. A dead-board-only cap is insufficient; do not use shared UI worker slots. |
| R3, R12, F4 | Queue Enter for the exact input revision; edits/failure/disposal clear it. Wait for the matching settled projection. Keep old rows and use a status message, not dimming. |
| R4, R9, F1 | Numeric formatting is caller code. Consume and validate bounded iterables on the worker, check cancellation, and reuse Qt-captured date context without rerunning formatters on Qt. |
| R10, R11, F2 | Separate composition input from hidden table search. Add an internal snapshot-replacement method that clears identity caches and invalidates older projections. |
| R5 | No pane or navigation. Keep a guarded Copy cell action; path columns remain preview values. |
| R6, F8 | Match QuickTable's framed window. Specify input/table focus transfer and filter-menu key precedence; no global frame redesign. |
| R7 | Gate host publication-to-paint at 10,000 rows at 150 ms, controlled preview heartbeat gaps at 50 ms, and release all leases/threads after close plus callback completion. Measure callback time separately. |
| R8 | Owner is required because callbacks/formatters outlive edits, unlike static tables. Normalize continuation indentation in revised text; retain reviewer history verbatim. |
| F5 | Keep modal-only API. Test independent programmatic callers and close/reopen under admission limits; no modeless argument is needed for composition. |
| F7, F9 | Board-level preview error and queued, guarded publication; show before the first callback, no Qt joins, no stale alerts. |
| F10 | Preserve all historical attribution. New records follow the user's explicit current-session assignment: GPT-6 Astra / Extra High / 1M, not a reviewer-inferred 272K default. |

## Alternatives

- A rename-specific dialog: rejected; the element must support unrelated
  string-composition consumers without knowing their grammar or operation.
- Add mutability to QuickTable: rejected at the public-contract level;
  QuickTable returns filtered row positions, while QuickBoard returns a string.
  Sharing internal rendering remains desirable.
- A full editable grid with IDs, action callbacks and a mutable handle:
  unnecessary for this task; the caller already owns the data and operation.
- Dedicated syntax hints, a help drawer and extra toolbar controls: rejected
  for the minimal UI; use a generic caller-supplied summary.
- Run every handler synchronously on Qt, like legacy Quicksearch suppliers:
  simpler but can block typing and cancellation. Prefer bounded worker delivery;
  keep the existing Quicksearch contract unchanged.

## Runtime Effects

- Before opening: no preview jobs, I/O, timers, subscriptions or recurring work.
- Opening: construct the existing-style table and validate the fixed columns;
  start one initial preview request. No filesystem scan is implicit.
- Editing: one active callback and one replaceable pending input per board;
  at most two admitted boards including retiring callbacks process-wide.
  No worker queue proportional to keystrokes. Sorting/filtering are in-memory.
- Memory: one displayed bounded snapshot and bounded in-flight result storage;
  intermediate overlap, renderer caches and callback-owned memory must be
  measured, not described as covered by the 16 MiB text allowance.
- I/O/processes: none required by the element. Any read-only preview I/O and its
  timeouts belong to the callback. No renderer process or new dependency.
- Closing: discard pending input, reject late results and detach callbacks;
  do not join blocked workers on Qt. Already-running OS calls may finish later.

## Tests

Contract tests are in
[test_ui_elements.py](../src/unittest/python/fman_unittest/test_ui_elements.py),
worker tests in [test_listing.py](../src/unittest/python/fman_unittest/test_listing.py),
and `QuickBoardIT` / replacement regressions in
[test_qt.py](../src/integrationtest/python/fman_integrationtest/test_qt.py).
`QuickBoardPluginIT` exercises loader-owned public-only consumers in the existing
[plug-in tests](../src/integrationtest/python/fman_integrationtest/impl/plugins/test_plugin.py).

- Unit: arguments, reused descriptors, single-line/NUL/length limits, exact
  string preservation, empty results, generator and payload limits, and exports.
- Qt: initial and changed text, off-Qt serial callbacks and numeric formatters,
  formatter failure/invalidation, latest-only admission,
  blocked/failed/stale previews, rapid edits, Enter/Esc from input and table,
  column-menu precedence, retained sorting/filtering and empty-preview acceptance.
  Queue Enter for A, edit B, complete A/B: B must stay open. Replace under both
  sort directions and pending old projections; Clear All Filters preserves text.
- Lifecycle: close/unload during work, parent closure, simultaneous callers,
  rapid reopen, failed worker admission and no callbacks into disposed widgets.
- Third-party integration: a disposable public-API-only plug-in supplies different
  handlers and unloads safely; extend the existing plug-in loader test module.
- Regression: unchanged QuickTable returns, appearance, typed filtering and
  menus. No field or row content may become an implicit operation directive.

Focused correctness commands (132 tests per platform):

```powershell
@'
import build, os, subprocess, sys
for platform in ('windows', 'offscreen'):
    env = build._environment()
    env['QT_QPA_PLATFORM'] = platform
    env['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
    result = subprocess.run([
        sys.executable, '-B', '-X', 'faulthandler', '-m', 'unittest',
        'fman_unittest.test_ui_elements',
        'fman_unittest.test_listing',
        'fman_unittest.test_portable.PluginApiCompatibilityTest',
        'fman_integrationtest.test_qt.QuickBoardIT',
        'fman_integrationtest.test_qt.TableIT',
        'fman_integrationtest.impl.plugins.test_plugin',
        '-q',
      ], env=env, timeout=120)
    if result.returncode:
        sys.exit(result.returncode)
'@ | python -
```

Performance: opt-in `QuickBoardPerformance` in the existing
[legacy.py](../src/performancetest/python/fman_performancetest/legacy.py), outside
normal correctness discovery. Exercise the 10,000-row/text limits, rapid input,
slow callbacks and close/reopen. Record input-to-paint latency, Qt heartbeat gaps,
peak memory and live-worker counts against the budgets agreed during review.

```powershell
@'
import build, subprocess, sys
code = (
    "import sys, unittest; sys.path.insert(0, 'src/performancetest/python'); "
    "unittest.main(module=None, argv=['quickboard', "
    "'fman_performancetest.legacy.QuickBoardPerformance', '-v'])"
)
env = build._environment()
env['QT_QPA_PLATFORM'] = 'windows'
sys.exit(subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-c', code], env=env, timeout=120).returncode)
'@ | python -
```

Source/visual smoke:

```powershell
@'
import build, subprocess, sys
for scale, folder in (('1', '100'), ('1.5', '150'), ('2', '200')):
  env = build._environment()
  env.update(QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=scale,
    QT_AUTO_SCREEN_SCALE_FACTOR='0', QUICK_BOARD_SMOKE_OUTPUT='target/quickboard/' + folder)
  result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m',
    'fman_integrationtest.quick_board_smoke'], env=env, timeout=60)
  if result.returncode:
    sys.exit(result.returncode)
'@ | python -B -
```

The smoke uses disposable settings and normal main-window closure. Compare
QuickBoard/QuickTable at 820x520 and the 460x280 minimum; check summary
elision/tooltips, menus, keyboard-only use and 100%/150%/200% Windows scaling.
The public-only loader fixture covers rename, destination, export, query,
exclusion and argument previews without performing operations. Physical monitor
transitions and a separately authorized portable artifact remain release checks.
Do not run the full correctness suite, build/freeze or performance catalog merely
to complete this plan.

## Implementation Steps

1. Review the concept and resolve the admission, snapshot, focus and performance
   decisions above. Obtain explicit implementation approval.
2. Add failing focused contract tests in the existing test modules; establish
   the immutable data and generic error boundaries.
3. Reuse QuickTable presentation and implement caller-driven preview delivery;
   immediately run the narrow new regression after the first substantive edit.
4. Complete owner/window teardown, string acceptance and typed projection tests;
   verify native and offscreen behavior plus the public-only plug-in fixture.
5. Run the agreed opt-in measurements and visual checks. Add packaging inputs
   only if new runtime modules need explicit collection.
6. Update the public API reference and usage/changelog for the implemented
   service. Record results and complete the task lifecycle only after its gates.

## Acceptance Criteria

- A third-party caller needs only public APIs and plain data to compose a string
  with a typed tabular preview; no Qt object or host-private dependency leaks.
- Enter and cancellation return the exact current string with the correct flag;
  empty rows work. Pending acceptance waits for its exact successful revision;
  failed/stale previews never accept and later edits clear the request.
- Column filters/sorting affect presentation only and survive row replacement.
- The element remains grammar- and operation-agnostic, with only a generic
  summary and the established QuickTable appearance.
- All six use-case fixtures fit the same API, without case-specific UI options.
- Worker admission, memory and teardown remain bounded, including close/reopen;
  two open/retiring board leases never starve the shared UI worker slots.
  disabled/closed paths create no continuing feature work except finishing calls.
- Focused unit/integration/native/offscreen tests and agreed performance and
  visual gates pass; unavailable release checks remain explicitly recorded.

## Reviewers

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Moved the user-edited QuickBoard material into Overview and Concept;
  recorded generic API boundaries, reusable consumers and required design/test
  decisions. Ready for planning review, not application implementation approval.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revisions required. The concept, scope and API shape are sound and
  fit the existing elements. Findings R1-R8 below; R2-R4 propose concrete
  answers to Decisions 1-3. No blocking architectural objection.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Revisions required before implementation. R9-R13 clarify callback,
  table-replacement, acceptance and admission boundaries; R9 corrects R4's
  formatter claim. Existing reviewer history and application code are unchanged.

## Design Review (2026_10_05)

Checked against [table_data.py](../src/main/python/fman/impl/ui/table_data.py)
(1-64 columns, 10,000 rows, 16 MiB text, per-column `sortable`/`filterable`,
row `highlights`: all confirmed), [facade.py](../src/main/python/fman/impl/ui/facade.py)
(`show_quick_table`), [quick_list_window.py](../src/main/python/fman/impl/ui/quick_list_window.py)
and `submit_work` in [ui/\_\_init\_\_.py](../src/main/python/fman/impl/ui/__init__.py).

- **R1 [P2] Naming.** `show_quick_table` and `show_quick_list` call the secondary
  line `summary`; use `summary` instead of `description`. The `(text, accepted)`
  return differs from the other elements (`None` on cancel). Keep it only if
  returning the draft on Escape is wanted; otherwise return the text or `None`.
  User decision.
- **R2 [P2] Worker admission (Decision 1).** Do not use the shared `submit_work`
  slots: there are only two, shared with Panels and navigation, and a slow
  callback would starve them. Proposal: each open board owns one daemon thread
  running a latest-only loop (the coalescing pattern of the QuickList sort save).
  Closing marks the board dead and the loop exits after the running call. A
  global cap (for example 2) on dead boards whose callback is still running:
  opening another board past the cap shows an alert instead of a board. Thread
  start failure closes the board with an alert and releases the caller.
- **R3 [P2] Enter while a preview is pending (Decision 3).** Ignoring Enter
  feels like a lost key while typing quickly. Proposal: Enter during a pending
  preview is remembered and accepts when that preview succeeds; a failure cancels
  it and shows the error. Old rows stay visible, dimmed, until the new preview
  lands. Escape always closes at once.
- **R4 [P2] Snapshot boundary (Decision 2).** On the worker:
  `tuple(islice(get_rows(text), MAX_ROWS + 1))`, checking the dead flag every 256
  rows, then the existing table validation; Qt receives only the validated
  snapshot. QuickTable has no formatting callbacks (the host formats typed
  cells), so drop that item from the decision.
- **R5 [P3] Go To and Copy.** QuickTable's Ctrl+Enter / double-click Go To needs
  `pane`. State that QuickBoard has no `pane`: path columns are display-only
  and the cell Copy menu stays.
- **R6 [P3] Focus and keys (Decision 4).** The field has focus on open;
  Up/Down/Page keys move into the table as in QuickList; Tab moves between field
  and table; Alt+Down opens the column filter as in QuickTable. Window frame:
  match QuickTable (dialog) or QuickList (frameless with title header); pick one
  for all elements.
- **R7 [P3] Performance budgets (Decision 5).** Starting points from the
  QuickList limit gate: preview publish to paint at 10,000 rows ≤ 150 ms,
  heartbeat gaps ≤ 50 ms while typing, zero board threads after close and
  callback return.
- **R8 [P3] Minor.** The `owner` argument is justified (repeated plug-in
  callbacks, like `show_panel`); say so, since `show_quick_list` has none. The
  Interaction bullets use 8-space continuation lines; use 2 like the rest.

## Follow-up Review (2026_10_05)

R1-R8 are proposals, not resolved requirements. Keep the task pending until the
selected admission, validation, acceptance and performance policies are part of
the main design and acceptance criteria.

- **R9 [P2] R4 incorrectly removes formatting callbacks from the boundary.**
  `QuickTableColumn.format` accepts a caller-supplied numeric formatter, and
  `TableSchema.snapshot()` invokes it through `_number_text()`. Reusing these
  descriptors therefore introduces plug-in code beyond `get_rows`. Define either
  worker-only formatting, under the same read-only, lifetime and failure rules
  as row generation, or an explicit QuickBoard restriction on formatters. Never
  rerun one during Qt publication. Test thread affinity, a blocked formatter,
  formatter exceptions and invalidation during formatting. A runtime probe
  confirmed one call for value `7`, producing display `custom:7` and raw `7`.

- **R10 [P2] Keep composition separate from the table's search query.**
  `Table.query.textChanged` triggers text matching, and `clear_all_filters()`
  clears that field. Rebinding it to composition would hide generated rows when
  the template does not match their cells, and a presentation command could
  erase the returned string. Give composition its own host-owned input and
  reuse the table with its search query disabled and empty. Column filters must
  never modify composition. Test a nonmatching template, Clear All Filters and
  Ctrl+F focus behavior. An offscreen probe confirmed that `rename-{index}` hides
  a `report-001.txt` row and Clear All Filters clears the current table query.

- **R11 [P2] Specify the row-replacement boundary before retaining sorting.**
  The current `Table` has static input rows and caches sort keys by row identity.
  Merely replacing `rows` preserves keys for the old snapshot; sorting new rows
  then raises `KeyError`. Define one internal replacement operation that rejects
  old projection completions, installs the validated snapshot, clears identity
  caches/matches and retains column filters and sort direction. Gate acceptance
  on both the input revision and the new projection settling. Test replacement
  under ascending/descending sorting and while an older projection is pending.
  The offscreen probe reproduced the stale-key failure and confirmed that
  invalidating the cache permits sorting the replacement.

- **R12 [P2] R3's queued Enter needs an explicit revision policy.** The main
  contract disables acceptance during pending work; R3 instead remembers Enter.
  Choose one behavior. If queued acceptance is selected, bind it to the exact
  input revision and clear it on any edit, failure, Escape or invalidation. It
  must wait for that revision's successful preview and presentation projection,
  never accept a later string automatically. Add the sequence: slow preview A,
  Enter, edit B, finish A, finish B; B remains open until a fresh acceptance.

- **R13 [P2] R2's dead-board cap does not bound active workers.** A cap counting
  only closed boards with running callbacks still permits arbitrarily many
  simultaneously open boards and threads. Define a process-wide admission
  limit on live preview workers, including idle workers owned by open boards
  and workers surviving board closure. Reserve a slot atomically before thread
  creation and retain it until the worker exits; release it on start failure.
  A saturated request must return cancellation without starting another callback or
  stranding its caller. Test concurrent opens, blocked close/reopen cycles,
  saturation and slot recovery after a closed board's worker exits or starting
  a worker fails.

### Review Validation

- Inspected the current public exports, owner contract, `TableSchema`, `Table`,
  QuickTable window and shared worker admission. QuickBoard does not exist yet.
- Ran read-only subprocess probes through `build._environment()`: numeric
  formatting during snapshot validation; offscreen table query/clear behavior;
  and sort-cache behavior after replacing rows. All assertions passed; the last
  probe expected and caught `KeyError` before clearing the stale cache.
- Existing-behavior baseline through `build._environment()`, with
  `QT_QPA_PLATFORM=windows`:
  `python -B -m unittest fman_unittest.test_ui_elements fman_integrationtest.test_qt.TableIT -q`
  passed 50 tests. These do not validate a QuickBoard implementation.
- Required task sections and 20 local link references passed structural checks.
- No application code, consumer plug-in, implementation tests or performance
  budgets were added. No full suite, build/freeze or performance catalog was run.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Revisions required before implementation approval. Concept, scope
  and API fit the existing elements. R4 contains a factual error (F1); the
  plan lacks the Table row-replacement design its core contract needs (F2);
  worker admission should reuse `LatestJobs` (F3). R1 is already decided by
  [UIElements.md](../UIElements.md). Findings F1-F10 below.

## Design Review 2 (2026_10_05)

Checked against [table.py](../src/main/python/fman/impl/ui/table.py) (`Table`,
`project`, `sort_keys`, `visible_positions`, `settled`, query `eventFilter`),
[table_data.py](../src/main/python/fman/impl/ui/table_data.py) (`TableSchema._display`,
`_number_text`, `QuickTableColumn.format`), [table_dates.py](../src/main/python/fman/impl/ui/table_dates.py),
[facade.py](../src/main/python/fman/impl/ui/facade.py) (`QuickTableWindow`,
`show_quick_table`, `_table_owner`), [session.py](../src/main/python/fman/impl/ui/session.py)
(`ToolWindow.post`, owner attach/invalidate) and `LatestJobs` in
[impl/model/listing.py](../src/main/python/fman/impl/model/listing.py).

- **F1 [P2] R4 is incorrect: caller code does run during snapshot.**
  `QuickTableColumn.format` is a caller-supplied callable for numeric columns
  and `TableSchema._display` invokes it through `_number_text` while building
  the snapshot. `LocalDates.format` also calls `QTimeZone.offsetFromUtc`. Keep
  the formatting-callback item in Decision 2 and state: `format` runs on the
  board worker, its exceptions are a failed preview (not a crash), and the
  `TableSchema` (with its `LocalDates`) is built once on Qt and reused by the
  worker; `QTimeZone` is a reentrant value type, so no Qt-thread hop is needed.
- **F2 [P2] Row replacement and the composition field are undesigned.**
  `Table.rows` is fixed at construction; `project()` reads it, `sort_keys` and
  `visible_positions` are keyed by `id(row)`, and the `query` field is wired to
  `project()` with placeholder `Filter` and the `Ctrl+F` shortcut. The plan says
  "reuse the table" and "replace the text filter", but there is no API for
  either. Specify: (a) construct `Table(schema, (), text_filter=None)` so the
  filter field is hidden and the focus proxy is the view; (b) the board owns the
  composition `QLineEdit` (`setMaxLength(4096)`) above the table and `Ctrl+F`
  focuses it; (c) add a host-internal `Table.replace_rows(snapshot)` that sets
  `rows`, clears `sort_keys`, bumps `generation`, keeps `filters`, sort state and
  the current column, then calls `project()`. This touches the shared renderer,
  so the QuickTable regression in Tests must cover the unchanged
  construction path explicitly (`TableIT` plus a `replace_rows` unit).
- **F3 [P2] Reuse `LatestJobs` for admission (Decision 1 / R2).** The
  one-active/one-pending rule, cancellation flag, `close()` without joining,
  `canceled_callback` and thread-start failure reporting already exist in
  `LatestJobs(capacity=1)`. A board owns one instance; `dispose` calls `close()`.
  The worker runs `tuple(islice(get_rows(text), MAX_ROWS + 1))` with the
  supplied `check` between 256-row chunks, then `schema.snapshot`. Prefer this
  over a new per-board loop (AGENTS: existing abstractions). R2's cap on dead
  boards with a running callback stays valid as a documented bound; a running
  callback cannot be interrupted either way. Importing from `fman.impl.model`
  into `fman.impl.ui` is host-internal; move the class to `fman.impl.util` if
  the dependency direction is objectionable.
- **F4 [P2] Remembered Enter (R3) needs two guards and a cheaper visual.**
  A remembered Enter must be cleared by any later text edit and may fire only
  when the landing preview's revision equals the current input revision.
  Dimming stale rows requires a `TableDelegate` change shared with QuickTable;
  prefer a counts-label state (`Updating…`) and keep the old rows undimmed
  unless the visual-parity gate explicitly includes a renderer change.
- **F5 [P2] Modality contradicts "simultaneous boards".** The Interaction
  section makes the board window-modal to its main window, but Decision 1 and
  the Lifecycle tests assume several boards. With `Qt.WindowModal` a second
  board on the same window cannot be used, and a Qt-thread caller would nest
  event loops under a modal. Either keep modal-only and reduce the multi-board
  case to "reopen while the previous callback is still running", or add
  `modal=True` like the other elements and keep the tests. Decide explicitly.
- **F6 [P3] R1 is decided; align limits.** [UIElements.md](../UIElements.md)
  already specifies `(text, accepted)` with the draft returned on Esc. Record
  that decision and note the divergence from `show_prompt`, which returns `''`
  on cancel. Rename `description` to `summary` with the `show_quick_list`
  limits (`title` 512, `summary` 2048, `text` 4096 via `text()`), and reject
  `\n`/`\r` in the initial text since the field is single-line.
- **F7 [P3] Keep handler errors out of `Table.error`.** `Table.settled` is
  `not closed and not pending and not error`, and `count_text` prints
  `Table.error` for filter failures. A handler `ValueError` shown through the
  same slot would be cleared by the next projection and confuse acceptance
  gating. Hold board-level `preview_error` in the window, show it in a board
  status label, and gate Enter on `preview_error is None and revision matches
  and table.settled`. Other exceptions: `self.alert(str(error))`, board stays
  open, acceptance disabled until a later preview succeeds.
- **F8 [P3] Frame and focus (R6).** QuickTable is `Qt.Dialog` framed; QuickList
  is frameless with a drag header (Unreleased changelog). Since the board
  reuses QuickTable's window, keep it framed here and move "one frame for all
  elements" to a separate task rather than deciding it inside this plan.
  Up/Down from the field into the table already exists in `Table.eventFilter`
  for the filter field; replicate it for the composition field.
- **F9 [P3] Delivery and teardown.** State that worker results are published
  through `ToolWindow.post`, which is alive-guarded and queued, so late results
  after `dispose` are dropped without touching widgets; `LatestJobs.close()`
  does not join. The initial `get_rows(text)` call runs on the worker after
  `window.show()`, so a slow first preview never delays showing the board.
- **F10 [P3] Provenance.** The first record lists GPT-6 Astra with a 1M context
  window while the second lists 272K for the same signature. Leave history as
  is; new Astra records should use the assigned 272K.

Verified: the test modules named in Tests exist (`TableIT`, `QuickListIT`,
`fman_integrationtest.impl.plugins.test_plugin` with `PluginTest` and
`ExternalPluginTest`, `fman_performancetest.legacy`), and
[Plan.md](../Plan.md) indexes this task under Pending. No tests or builds run.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Addressed R1-R13 and F1-F10 in the main design, including corrections
  to formatter ownership, global admission and attribution. User authorized
  implementation after this review synthesis. Existing reviewer text preserved.

## Implementer

### 2026_10_06 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Implemented the reviewed QuickBoard service and all R1-R13/F1-F10
  resolutions. Public-only loader consumers, 132 native and 132 offscreen
  correctness checks, two opt-in performance cases and three source/DPI smokes
  pass. Historical reviewer text is unchanged. Batch Rename was not implemented.

## Validation Results

- The exact correctness, performance and source-smoke launchers are in Tests
  above. Correctness: 132 passed on Windows, 132 passed offscreen; no skips.
  Offscreen emits expected unsupported raise/keyboard-grab platform messages.
- Regressions cover exact draft/empty returns, early and revision-bound Enter,
  matching projection completion, callback/formatter affinity and failure,
  owner/parent close, blocked formatting, global open/retiring admission,
  independent shared UI slots, initial/queued thread-start failure, filter/menu
  keyboard behavior, Copy-only paths and all six public-only consumer fixtures.
- Unloading between admission and construction returns cancellation, releases
  its lease and starts no callback; the deterministic regression also passes.
- The first two row-replacement regressions failed without `replace_rows`,
  then passed after it was added. Existing QuickTable construction, sorting,
  filtering and return behavior pass alongside the new replacement checks.
- Native performance, 10,000 rows / approximately 15.4 MiB text, three updates:
  input-to-completed-paint median/max 62.7/66.3 ms; publication-to-paint
  12.1/13.2 ms (150 ms limit); callback median 12.9 ms; heartbeat maximum
  16.6 ms (50 ms limit). These are controlled local measurements, not guarantees
  for arbitrary caller code or OS calls.
- Separate memory pass: replacement retained/peak Python allocation
  18.22/20.84 MiB; process working set before/after 117.60/135.43 MiB and
  process peak 144.96 MiB. The text cap is not a total process-memory cap.
- 200 rapid edits invoked only the active and final callbacks. Close-to-return
  was 1.71 ms; ten reopen cycles left zero extra threads or admission leases.
- Source smoke passed at native DPR 1.0, 1.5 and 2.0: 18 PNGs under
  `target/quickboard/{100,150,200}`. Normal/narrow board, error, menu and
  QuickTable reference captures were checked for geometry and nonblank pixels;
  source startup and exactly one normal main-window close passed each time.
  Screenshot inspection confirmed the shared table appearance and summary
  elision; the extra reserved line holds updating/error feedback.
- `python -B -m mkdocs build --strict --site-dir target/quickboard-docs` passed.
  Edited Python editor diagnostics are clear. Pylance found one resolved
  `TableSchema.snapshot` call compatible; constructor call-site discovery did
  not resolve `LatestJobs.__init__`, so its compatibility is covered by the
  existing worker regression suite rather than that static check.
- Packaging inputs need no change: the spec already includes `fman.ui`, which
  directly imports the new module. No frozen artifact was built or launched;
  this source-import inspection is not artifact verification. Physical
  mixed-monitor transitions and Windows CI remain unverified.
- No full suite, performance catalog, clean/freeze/package, dependency install,
  git staging or commit. Existing UIElements comparison hard breaks and its
  pre-existing trailing blank line were preserved.

## Implementation Review (2026_10_06)

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved. The implementation matches the reviewed design and the
  F1-F10/R1-R13 resolutions; the documented focused gate was reproduced
  (132 passed native, 132 passed offscreen). Four non-blocking P3 remarks
  I1-I4 below; no application code changed by this review.

Checked [quick_board.py](../src/main/python/fman/impl/ui/quick_board.py),
the `replace_rows`/`project` edits in [table.py](../src/main/python/fman/impl/ui/table.py),
`LatestJobs(on_closed=...)` in [impl/model/listing.py](../src/main/python/fman/impl/model/listing.py),
`snapshot(check_canceled=...)` in [table_data.py](../src/main/python/fman/impl/ui/table_data.py),
the `fman.ui` export, [PlugIn.md](../PlugIn.md#qt-free-quickboard),
[docs/plugins/ui-elements.md](../docs/plugins/ui-elements.md) (in the MkDocs nav),
[UIElements.md](../UIElements.md), the Unreleased changelog entry, the Completed
index entry and the absence of a `Plan/` copy.

Confirmed by reading: the lease is reserved before window/thread creation and
released only when the lane drains, including construction failure and both
thread-start failure paths; acceptance requires `accept_revision == revision ==
preview_revision`, no pending work, no preview error and a settled projection;
results reach Qt only through alive/owner-guarded `ToolWindow.post`; the
composition field is separate from the hidden, empty `Table.query`; the
`LatestJobs` and `snapshot` changes are additive with unchanged defaults; the
loader fixture consumes only `fman.ui` names and unloads cleanly.

- **I1 [P3] Shared `project()` change alters QuickTable's initial column.**
  `finish()` now uses `self.last_column` instead of `0` when there is no current
  cell. For a QuickTable whose first column is `filterable=False`, the initial
  current cell is now the first filterable column (offscreen probe: column 1,
  previously 0). No bundled consumer has such a column, so the change is latent,
  but the task text says the ordinary construction path is unchanged. Either
  limit the fallback to the replacement path or record the new behavior with a
  `TableIT` assertion.
- **I2 [P3] Cancelled drafts may contain CR/LF.** `QLineEdit` keeps line breaks
  on paste (probe: `'first\nsecond\r\nthird'` retained). The board then shows
  the inline single-line error and blocks Enter, which is correct, but Escape
  returns that draft although `show_quick_board(text=...)` rejects it as input.
  Document the asymmetry in PlugIn.md, or replace line breaks on paste.
- **I3 [P3] `_prepare` catches `BaseException`.** This is the right choice (a
  `KeyboardInterrupt`-derived error escaping `work` would leave the board on
  `Updating...` until the next edit), but PlugIn.md should state that any
  exception from caller code, including `Task.Canceled`, is a failed preview.
- **I4 [P3] A landing preview closes an open column-filter editor.**
  `replace_rows` calls `close_filter_menu()`, so a slow handler can discard a
  half-typed filter value. Acceptable for the stated design; mention it in the
  Interaction notes or defer `replace_rows` while a filter menu is open.

Validation performed by this review, through `build._environment()`:

- The Tests section's focused correctness launcher, unchanged apart from a
  300 s child timeout: `fman_unittest.test_ui_elements`,
  `fman_unittest.test_listing`, `fman_unittest.test_portable.PluginApiCompatibilityTest`,
  `fman_integrationtest.test_qt.QuickBoardIT`, `fman_integrationtest.test_qt.TableIT`,
  `fman_integrationtest.impl.plugins.test_plugin`: 132 passed with
  `QT_QPA_PLATFORM=windows`, 132 passed with `offscreen`, no skips.
- Two read-only offscreen probes: `QLineEdit` paste/`setText`/`insert` retain
  CR/LF; a two-column `Table` with `filterable=False` on column 0 starts with
  current column 1 and `last_column == 1`.
- Not run: `quick_board_smoke`, `QuickBoardPerformance`, strict docs build,
  full suite, freeze/package. Portable-artifact and physical mixed-monitor
  checks remain unverified as recorded above.

## Implementation Review 2 (2026_10_06)

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Approved with follow-ups. The code matches the design; the lease,
  revision-bound acceptance, guarded delivery and teardown paths are correct.
  One P2 user-facing remark (J1) and three P3 remarks; I1-I4 above remain open.

Read [quick_board.py](../src/main/python/fman/impl/ui/quick_board.py) and the
diffs of `table.py`, `table_data.py`, `listing.py`, `fman/ui.py`, the
screenshot generator and the docs.

- **J1 [P2] The `?` button is back.** `Qt.Dialog` adds Windows' context-help
  button, which does nothing here (see the generated
  `royifilemanager-ui-quickboard.png`). The user rejected it on QuickList.
  Clear `Qt.WindowContextHelpButtonHint` on QuickBoard (and QuickTable, which
  has the same button), or set `Qt.AA_DisableWindowContextHelpButton` once.
- **J2 [P3] An empty band between the field and the table.** The reserved status
  line is blank whenever no preview is pending, so the board shows a gap QuickTable
  does not have. Consider showing `Updating...` / errors in the existing footer
  (`3 / 3 rows`) instead of a dedicated line.
- **J3 [P3] The documentation capture grabs the desktop.** `_grab_framed_dialog`
  uses `QScreen.grabWindow(0, ...)`, unlike every other capture (widget
  grabs). It worked locally, but an overlapping window or a desktop without
  screen access (restricted Pages child) would save wrong pixels silently. Add a
  sanity check (not uniform, title bar present) or grab the widget.
- **J4 [P3] On I1:** keep the new initial column (first filterable column; also
  used when an empty filter result refills). It is the better behavior; add the
  `TableIT` assertion and a CHANGELOG line rather than restricting it.

Verified: the lease is released exactly once on every path (construction
failure, start failure, close while idle, close while a callback runs); the
deferred initial preview is skipped when the user types first; non-`ValueError`
alerts are window-modal, so a failing handler cannot stack dialogs while typing;
`TableSchema.snapshot(check_canceled=...)` and `LatestJobs(on_closed=...)` keep
their defaults for existing callers; the Plan index and `Done/` placement are
correct; Up/Down from the field matches QuickTable's filter field.

Validation by this review (through `build._environment()`):

- `fman_unittest.test_ui_elements`, `fman_unittest.test_listing`,
  `fman_unittest.test_portable.PluginApiCompatibilityTest`,
  `fman_integrationtest.test_qt.QuickBoardIT`, `TableIT`, `QuickListServiceIT`,
  `FavoritesManagerIT` and `fman_integrationtest.impl.plugins.test_plugin`:
  163 passed offscreen and 163 passed native.
- `python src/misc/generate_docs_screenshots.py --mode source`: all captures
  generated, including `royifilemanager-ui-quickboard.png` (822x552).
- Not run: performance cases, full suite, freeze/package.

## Implementation Review 3 (2026_10_06)

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Changes requested for K1: cancellation during one numeric formatter
  still permits subsequent formatters after owner invalidation. The 132-test
  focused gate passes on both platforms but misses this case. Application code
  and historical review records are unchanged.

- **K1 [P2] Cancellation does not stop subsequent numeric formatters in the
  current row.** [TableSchema._display](../src/main/python/fman/impl/ui/table_data.py#L254)
  runs all typed-cell formatters without cancellation checks.
  [snapshot](../src/main/python/fman/impl/ui/table_data.py#L290) checks only
  before and after the row. With two numeric columns, block the first formatter,
  invalidate the board owner and wait for the canceled caller to return, then
  release the formatter. The second formatter still runs with `owner.active ==
  False` before the eventual check discards the snapshot. This is new caller
  execution after unload, not merely allowing an already-running callback to
  finish. Another slow formatter can prolong the retiring worker and admission
  lease. Thread the optional cancellation check into `_display`, checking before
  and after every caller-supplied formatter while preserving QuickTable's default
  behavior. Add a regression with two formatters; after cancellation/unload the
  first may finish, the second must not start, and the lease must drain. The
  existing blocked-formatter test has one numeric formatter and cannot catch it.

### Review Validation

These results are from the implementation review performed on 2026-10-06;
restoring this record did not rerun application tests.

- Re-ran the Tests section's focused correctness launcher through
  `build._environment()`, with `QT_QPA_PLATFORM=windows` and `offscreen`:
  132 tests passed on each platform, no skips. Exact child command:

  ```text
  python -B -X faulthandler -m unittest fman_unittest.test_ui_elements fman_unittest.test_listing fman_unittest.test_portable.PluginApiCompatibilityTest fman_integrationtest.test_qt.QuickBoardIT fman_integrationtest.test_qt.TableIT fman_integrationtest.impl.plugins.test_plugin -q
  ```

- Pure-data reproduction: two numeric columns whose formatter cancels the check
  during value `1`; `_prepare` eventually raises `Canceled`, but the observed
  formatter calls are `[1, 2]`. Expected after correction: `[1]`.
- Offscreen reproduction: a temporary in-memory `QuickBoardFixture` subclass,
  using the Qt module's `setUpModule`/`tearDownModule`, blocks the first numeric
  formatter with Events, invalidates the owner, verifies `('draft', False)` is
  returned, then releases it. The second formatter recorded `[False]` for owner
  activity. The test intentionally asserted the defect and passed; the admission
  lease drained afterward. An initial standalone harness attempt lacked the Qt
  module setup and failed before reaching application behavior; the corrected
  reproduction above supersedes it.
- No production or test source edits. Existing I1-I4/J1-J4 remarks are historical
  and are not resolved by this review. Performance/screenshot regeneration, full
  suite, freeze/package, Windows CI and physical mixed-monitor checks were not
  run; portable-artifact checks remain unverified.