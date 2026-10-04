# UI Elements 001: QuickTable

Status: Implemented 2026_10_04; ready for independent review.

## Task

Give plug-ins a multi-column table with typed columns for **narrowing** a
predefined, immutable set of rows. The user filters and sorts; <kbd>Enter</kbd>
returns the remaining rows to the caller. The element is buttonless and needs
no Qt code. Element rationale: [UIElements.md](../UIElements.md).

## Scope

Included:

- Qt-free blocking `fman.ui.show_quick_table(...)` with `QuickTableColumn` and
  `QuickTableRow` descriptors.
- Typed columns: text, file/folder name, file/folder/entry path, date, numeric.
- Two filter layers: the text filter box and per-column header filters.
- Sorting per column; Copy, Go To and filter commands in the cell menu.
- Result keys: Enter returns the visible rows; Escape returns `None`.
- Go To for name/path cells only: Ctrl+Enter, double-click or cell menu.
- Consumers: Search Files, Find Files, Checksum Files.

Excluded:

- Any file operation other than Go To; rows and files are never modified.
- Buttons, caller menus, callbacks, row IDs, refresh or row replacement.
- A caller instructions line: callers use `title`, `summary` and the main
  status bar (`show_status_message`).

Compatibility: replaces `show_table` / `TableColumn` / `TableRow` (provisional
`fman.ui` API, not in a released version). No compatibility aliases.

## Design

### API

```python
show_quick_table(*, columns, rows, pane=None, title='', summary='', modal=True,
                 text_filter='fuzzy', base_path=None, truncated=None) -> tuple[int, ...] | None

QuickTableColumn(label, kind='text', sortable=True, filterable=True, searchable=None,
                 unit=None, date_display='timestamp', format=None, missing='Unknown')
QuickTableRow(cells, highlights=(), targets=())
```

| Argument | Meaning |
| --- | --- |
| `columns` | 1-64 `QuickTableColumn` descriptors. |
| `rows` | Iterable of `QuickTableRow`, validated once: at most 10,000 rows, 16 MiB text (plus 8 bytes per typed cell), 128 highlight spans per cell. Optional `targets`: one absolute path or `None` per column (name/path columns only), used by Copy Path and Go To instead of the cell text. |
| `pane` | Go To target. Without it Go To is disabled; Copy still works. |
| `title`, `summary` | Window title; one elided line above the table. |
| `modal` | `True` (default) blocks the main window; `False` keeps it usable. |
| `text_filter` | `'fuzzy'`, `'substring'`, `None` (no filter box) or `compile(query) -> predicate(cells) -> bool`. |
| `base_path` | Base for relative path cells; default: the pane's local folder at call time. |
| `truncated` | `True` adds `· truncated` to the row count; `False`/`None` add nothing. |

The call blocks until the window closes. A worker thread waits on its own
window's event, so modeless tables opened from different workers return in
close order; on the Qt thread it runs a nested event loop. The result is the
input positions of the visible rows in **input order** (not display order), or
`None`.

### Keys

| Key | Effect |
| --- | --- |
| Enter (table or filter box) | Close and return the visible rows |
| Escape, window close | Close and return `None` |
| Ctrl+Enter, double-click | Go To the current name/path cell |
| Alt+Down | Filter menu of the current column |
| Ctrl+F | Focus the filter box |

- Enter is ignored while a projection is pending, after a filter error and
  when no row is visible, so `None` always means cancelled.
- Go To (all three paths) is ignored while a projection is pending: the view
  still shows the previous rows, which the new filter may exclude.
- Go To on a file opens its parent folder in the pane and selects the file; on
  a folder it opens the folder. Modal tables close after a successful Go To
  (result `None`); modeless tables stay open and focus the pane.
- The table closes with its pane or main window.

### Columns

| Kind | Cell value | Sort | Column filter | Go To |
| --- | --- | --- | --- | --- |
| `text` | `str` | Case-insensitive | Fuzzy / Contains | - |
| `file_name`, `file_path` | `str` | Natural | Fuzzy / Contains | File |
| `folder_name`, `folder_path` | `str` | Natural | Fuzzy / Contains | Folder |
| `entry_path` | `str` | Natural | Fuzzy / Contains | File or folder |
| `numeric` | `int`, finite `float` or `None` | By value | `=`, `<`, `≤`, `>`, `≥`, Between, Missing | - |
| `date` | `int` UTC epoch ns or `None` | By value | On, Before, After, Between, Missing | - |

- `unit='bytes'` (numeric only): nonnegative integers shown as `12,345 B`,
  filters offer B/KiB/MiB/GiB. `format` (numeric only) supplies display text.
- Numeric bounds are parsed as decimals: integers compare exactly, floats with
  the nearest float to the bound (`0.1` matches `= 0.1`). Bounds beyond the
  decimal range (for example `1e1000000` bytes) are input errors that disable
  Apply and clear the previous predicate.
- Dates display as ISO 8601 (`date_display='timestamp'` with offset, or
  `'date'`) in the system time zone, captured once per table through
  `QTimeZone`. Date filters take `YYYY-MM-DD`; days are `[start, next_day)` with
  historical offsets; ambiguous/nonexistent midnights are handled. A day ends
  where the next existing day starts, so the day before a skipped calendar date
  filters normally; selecting the skipped date itself is an input error.
- `None` shows `missing`, sorts last both ways and matches only Missing.
- The host formats typed cells and keeps the raw values for sorting/filtering;
  display text is used for text matching and Copy.
- Path cells resolve lexically (absolute, or relative to `base_path`) unless the
  row supplies `targets`; the file system is touched only by Go To.

### Filters

- **Text filter box:** matches the searchable columns (text-like by default).
  Fuzzy and substring rank better matches first and underline them; a caller
  callable keeps input order, compiles once per query edit and must return
  `True`/`False` (errors show inline).
- **Column filters:** header funnel, Alt+Down or the cell menu. Typed columns
  compare raw values; several filters combine with AND.
- A row is visible when it passes both layers. The status line shows
  `visible / total rows · N column filters · truncated` and updates live.
- Header labels sort (ascending, descending, original); funnels only filter.

### Ownership, Threading and Lifetime

- Host modules: [table_data.py](../src/main/python/fman/impl/ui/table_data.py)
  (descriptors, validation, snapshot), [table_dates.py](../src/main/python/fman/impl/ui/table_dates.py),
  [table_filters.py](../src/main/python/fman/impl/ui/table_filters.py),
  [table.py](../src/main/python/fman/impl/ui/table.py) (widget, header, delegate,
  filter editor) and [facade.py](../src/main/python/fman/impl/ui/facade.py)
  (`QuickTableWindow`, `open_quick_table`, `show_quick_table`).
- All widgets stay on the Qt thread. Projections run in ~6 ms slices with
  stale-generation rejection; deferred callbacks use timers owned by the widget.
- Menus are deleted through `aboutToHide -> deleteLater` (a direct Python
  `deleteLater()` lets garbage collection clear a live menu).
- Tables are independent of plug-in owners and Panels. No persistence.

### Consumers

| Consumer | Mode | Result use |
| --- | --- | --- |
| Search Files | Modal; root and run summary in `summary`; Extended mode adds Size and Date Modified and a phrase/AND `text_filter` | Ignored |
| Find Files | Modal; root and counts in `summary` | Ignored |
| Checksum Files | Modeless, so files can be inspected; `targets` carry each verified raw path (display cells escape non-printable characters), diagnostic rows have none | Ignored |

## Alternatives

- **Buttons (Accept/Cancel) or an `accept` label:** rejected; buttonless keys
  match QuickSearch and QuickList.
- **Enter as Go To:** rejected; Enter returns the result in all Quick elements.
  Go To uses Ctrl+Enter and double-click.
- **File operations in the table:** rejected; the table is immutable. Working
  with items belongs to QuickList ([UIElements002](../Plan/UIElements002.md)).
- **Caller menus, callbacks, refresh or row IDs:** rejected for a static design.
- **Parsing display text for dates/sizes:** rejected; typed raw values are exact.
- **A caller status argument:** rejected; `title`, `summary` and the main status
  bar cover instructions.

## Runtime Effects

- Nothing runs until a table is shown. Opening validates one bounded snapshot;
  tables with date columns resolve the time zone once.
- Filtering is in-memory, time-sliced on Qt; sorting caches keys per column.
- No I/O except Go To navigation; no threads, processes, timers or polling
  beyond the projection slices. Closing disposes the snapshot.

## Tests

Focused command (repository root; set `QT_QPA_PLATFORM` to `offscreen` or
`windows`):

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_ui_elements','fman_unittest.test_search_files','fman_unittest.test_find_files','fman_unittest.test_checksum_files','fman_unittest.test_portable.PluginApiCompatibilityTest','fman_unittest.test_generate_docs_screenshots','core.tests.fs.test_columns','fman_integrationtest.impl.plugins.test_checksum_files_plugin','fman_integrationtest.test_qt.TableIT','fman_integrationtest.test_qt.SearchFilesIT','fman_integrationtest.test_qt.ChecksumFilesIT','fman_integrationtest.test_qt.FindFilesIT','fman_integrationtest.test_qt.PanelIT'], env=env).returncode)"
```

Coverage:

- Unit: descriptors and limits, typed formatting, lexical paths, row `targets`
  validation and resolution, date bounds (gaps, overlaps, skipped days, the day
  before a skipped date), every column-filter operator, fractional equality and
  inclusive ranges, extreme decimal exponents.
- Qt: blocking from worker and Qt thread; modeless worker callers returning in
  close order; Enter result in input order with sort and both filter layers;
  Enter ignored while pending / with no rows; Ctrl+Enter, double-click and menu
  Go To ignored across a deferred projection (injected clock); modifier
  handling; header icons and filter menu (Between width, extreme exponents via
  real text changes, `gc.collect()` after closing menus); text hook; Copy Path
  and Go To from `targets`; real modal/modeless navigation and focus; panel
  interplay.
- Consumers: Search Files (Escape, Enter, Ctrl+Enter, double-click, menu Go To),
  Find Files (Ctrl+Enter navigation), Checksum Files (modeless results; a real
  U+200B filename navigates to the verified file, diagnostic rows do not).
- Manual: native look at 100/150%, keyboard-only filter menus.

## Implementation Steps

1. Descriptors, snapshot validation and typed formatting (`table_data`,
   `table_dates`, `table_filters`).
2. Table widget: header icons, filter editor, projection, keys.
3. Window and blocking service (`QuickTableWindow`, `show_quick_table`).
4. Consumers and their tests; docs (PlugIn.md, UIElements.md, READMEs, CHANGELOG).

## Acceptance Criteria

- `show_quick_table` blocks and returns the visible rows' input positions on
  Enter, `None` on Escape/close; no buttons exist in the window.
- Ctrl+Enter and double-click Go To; modal closes, modeless stays; no Go To
  while a projection is pending.
- Modeless tables from different workers return to their callers in close order.
- Typed sorting/filtering uses raw values; unknowns sort last and match Missing;
  fractional values match their own bounds; out-of-range bounds are input errors.
- Days before skipped calendar dates filter normally.
- Copy Path and Go To use row `targets` when given; Checksum Files navigates to
  verified raw paths.
- Both filter layers combine with AND; the status line reflects them live.
- Search Files, Find Files and Checksum Files work with the new API.
- Focused tests pass offscreen and native.

## Reviewers

### 2026_10_04 - Maintainer and Documenter Claude Opus 5.5

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Document rewritten to the concluded QuickTable design at the user's
  request (earlier iterations are in git history): narrowing only, buttonless,
  Enter returns visible rows, Ctrl+Enter/double-click Go To, full API rename.
  Ready for independent review.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revisions required for R1-R4 below. Reviewed the concluded QuickTable
  contract, not the superseded Table design. Existing focused tests pass, but
  isolated runtime probes reproduce four uncovered defects. No application or
  test source changes.

#### Independent Implementation Review

1. **R1 (P2): Modeless callers cannot finish independently.**
   [show_quick_table](../src/main/python/fman/impl/ui/facade.py#L824) always enters
   a nested Qt event loop, including calls dispatched from workers. Open A and
   then B on separate workers, both modeless; close A while B remains open.
   A's window is disposed but its caller remains blocked until B closes. Keep
   worker-side waiting outside the Qt dispatcher; reserve nested loops for
   actual Qt-thread callers. Add an out-of-order two-window closure regression.
2. **R2 (P2): A byte-filter exponent escapes validation and retains the old filter.**
   [_number](../src/main/python/fman/impl/ui/table_filters.py#L43) multiplies a
   Decimal by the unit even for B; `1e1000000` raises `decimal.Overflow`.
   [FilterEditor.validate](../src/main/python/fman/impl/ui/table.py#L390) catches
   only ValueError. After entering valid `1`, replacing it with that exponent
   reaches `sys.excepthook`, leaves the previous compiled predicate intact and
   shows no inline error. Convert decimal failures to validation errors, clear
   the compiled predicate and disable Apply. Cover extreme exponents through
   real text-change signals, not only direct parser calls.
3. **R3 (P2): Ordinary fractional values cannot match their own equality filter.**
   [Numeric comparisons](../src/main/python/fman/impl/ui/table_filters.py#L80)
   compare raw floats with Decimal bounds. A numeric cell containing `0.1`
   displays `0.1`, but both `= 0.1` and `<= 0.1` reject it; for `0.3`, `= 0.3`
   and `>= 0.3` reject it. Define float-bound conversion while preserving exact
   integer/byte comparisons. Add fractional equality and inclusive-range tests;
   the existing `1.5` formatting case does not exercise this mismatch.
4. **R4 (P2): Go To can act on a stale row during filtering.**
   [activate_cell/go_to](../src/main/python/fman/impl/ui/facade.py#L682) check
   busy/current state but not `table.settled`. A projection keeps the previous
   model visible between slices: Ctrl+Enter then navigates its current row even
   when the new filter excludes every row. The probe dispatched `old.txt` while
   `pending` was True. Guard navigation against pending/error projections at
   execution time, as Enter already is, and test Ctrl+Enter, double-click and
   menu Go To across a deferred projection.

### 2026_10_04 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Revisions required. Independently reproduced R1-R4 in the current
  implementation and found R5 loss of checksum navigation targets and R6
  rejection of valid-day filters before a skipped date. Existing focused tests
  pass; their coverage misses these defects. Application and test source unchanged.

#### Sol Implementation Review Follow-Up

The concluded QuickTable contract is the review baseline; no requirements from
the superseded Table design are applied. R1-R4 remain open: modeless worker
callers finish in nested-loop order rather than window-close order, extreme
byte bounds escape the editor's exception handler, fractional equality compares
floats against Decimal bounds, and pending projections allow stale navigation.
Fresh Qt probes reproduced R1, R2 and R4; R4 was exercised through Ctrl+Enter,
double-click and the cell-menu Go To action. The direct numeric probe reproduced
R3 for `0.1` and `0.3` (with `1.5` as a passing control).

5. **R5 (P2): Checksum Go To is reconstructed from escaped display text.**
  [show_results](../src/main/resources/base/Plugins/ChecksumFiles/checksum_files/commands.py#L122)
  passes only `ResultRow.cells`, discarding each row's authoritative raw
  `target`. The engine deliberately escapes non-printable characters in its
  display strings. A real SHA256 verification of `report\u200b.txt` (U+200B
  in the filename) succeeds, but the new table resolves its escaped cell into
  a nonexistent `report/u200b.txt` path instead of the verified
  file. Preserve raw navigation targets independently of display text, and
  keep diagnostic rows without targets non-navigable. Add a real filename
  regression covering Copy/Go To and a target-less diagnostic row.
6. **R6 (P2): Valid-day filters fail before a skipped calendar date.**
  [next_day_start](../src/main/python/fman/impl/ui/table_dates.py#L61) requires
  the immediately following calendar date to exist. With the existing
  injectable offset provider changed from UTC+00 to UTC+24 at midnight on
  2001-01-02, January 2 is skipped but January 1 is valid. On January 1, After
  January 1 and Between January 1/January 1 all raise an error about January 2;
  a valid January 1 row cannot be filtered. Resolve upper day boundaries to
  the first representable instant after the selected day, independently of
  the policy for a nonexistent date selected directly. Test the preceding
  day, the skipped day and the next valid day, including inclusive Between.

## Implementer

### 2026_10_04 - Maintainer and Documenter Claude Opus 5.5

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Renamed the API (`show_quick_table`, `QuickTableColumn`,
  `QuickTableRow`, `QuickTableWindow`, `open_quick_table`); removed `accept` and
  its buttons; Enter returns visible input positions; Ctrl+Enter and
  double-click Go To; consumers, tests, smokes and docs updated.

### 2026_10_04 - Maintainer and Documenter Claude Opus 5.5 (Review Fixes)

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Addressed R1-R6 and their recommended regressions.
  - R1: worker callers open the window and wait on their own `Event`
    (`show_quick_table` in [facade.py](../src/main/python/fman/impl/ui/facade.py));
    only Qt-thread callers use a nested loop.
  - R2: [table_filters.py](../src/main/python/fman/impl/ui/table_filters.py)
    turns decimal arithmetic failures into "out of range" validation errors;
    the editor also treats `ArithmeticError` as invalid input.
  - R3: float cells compare with the nearest float to each bound; integers
    keep exact Decimal comparison.
  - R4: `go_to` requires `table.settled` at execution time; the menu's Go To
    is disabled while pending.
  - R5: new `QuickTableRow.targets` (absolute path or `None` per name/path
    column, validated at snapshot); Checksum Files passes each row's verified
    raw `target`, and `None` for diagnostic rows.
  - R6: `LocalDates.next_day_start` ends a day at the next existing day.

## Validation Results

- Focused command above: 219 tests OK (1 expected skip: packaged-app checksum
  probe needs `CHECKSUM_FILES_PORTABLE_EXE`) offscreen and native `windows`.
- Broad check, 2026_10_04: the whole `fman_integrationtest.test_qt` module plus
  `test_checksum_files_plugin`, `test_search_files_engine`, `test_ui_elements`,
  `test_search_files`, `test_find_files`, `test_checksum_files`, `test_portable`,
  `test_generate_docs_screenshots` and `core.tests.fs.test_columns`: 433 tests,
  native OK (2 expected skips). Offscreen: 3 of 4 runs OK; one run had a single
  failure in the unrelated `UnpackArchiveIT` (Core Unpack archive), not
  reproduced in 40 isolated repeats or 2 further full runs.
- `TableIT` repeated 60 times in one process: 780 tests OK.
- Native smokes: `search_files_smoke` and `find_files_smoke` PASS (startup,
  layout, modal results and navigation).
- Real `checksum-files` docs screenshot capture: produced the results image.
- `python src/performancetest/run.py ui-table`: 10,000 rows, snapshot and
  construction 0.033 s, fuzzy query 0.010 s. A stale import that broke every
  `run.py` legacy diagnostic was fixed; the development-tool checks
  (`unittest discover -s src/performancetest/python`) pass: 108 tests, 1 skip.
- Not run: full `build.py test`, clean, freeze, strict MkDocs build, packaged
  smoke.

### Independent Review Validation - 2026_10_04

Existing project environment: CPython 3.14.7. Commands from the repository root:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_ui_elements','fman_unittest.test_portable.PluginApiCompatibilityTest','core.tests.fs.test_columns','fman_integrationtest.test_qt.TableIT','-v'], env=env, timeout=120).returncode)"
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_search_files','fman_unittest.test_find_files','fman_unittest.test_checksum_files','fman_integrationtest.test_qt.TableIT','fman_integrationtest.test_qt.SearchFilesIT','fman_integrationtest.test_qt.FindFilesIT','fman_integrationtest.test_qt.ChecksumFilesIT','-q'], env=env, timeout=120).returncode)"
```

- Offscreen: 58 tests passed; native Windows: 137 tests passed; no skips.
- Read-only numeric probe: `0.1` and `0.3` fail equality against their displayed
  text; `1.5` succeeds. Byte bound `1e999999` compiles; `1e1000000` raises Overflow.
- Three in-memory QtIT probes confirmed R1, R2 and R4 under offscreen Qt. R1's
  first caller remained blocked for the 200 ms observation after its window
  closed, then both returned after the second window closed. R2 intercepted
  the real Qt exception hook to avoid an error dialog. R4 forced one projection
  slice using an injected clock and sent an actual Ctrl+Enter key event; the
  navigation dispatcher was mocked, so no files or pane locations changed.
- These probes assert the observed defects, not corrected behavior. No permanent
  regression tests or fixes were added. Source editor diagnostics were clear.
- No full suite, package/build, strict docs build, new performance run or manual
  DPI review. Earlier implementer results above were not independently rerun
  beyond the two focused commands listed here.

### Sol Review Validation - 2026_10_04

Existing project environment: CPython 3.14.7. Both commands were rerun in this
review, rather than relying on the earlier reviewer results:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_ui_elements','fman_unittest.test_portable.PluginApiCompatibilityTest','core.tests.fs.test_columns','fman_integrationtest.test_qt.TableIT','-q'], env=env, timeout=120).returncode)"
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_search_files','fman_unittest.test_find_files','fman_unittest.test_checksum_files','fman_integrationtest.test_qt.TableIT','fman_integrationtest.test_qt.SearchFilesIT','fman_integrationtest.test_qt.FindFilesIT','fman_integrationtest.test_qt.ChecksumFilesIT','-q'], env=env, timeout=120).returncode)"
```

- Offscreen: 58 tests passed; native Windows: 137 tests passed; no skips.
- Three temporary in-memory QtIT probes passed their defect-observation
  assertions: R1's closed window held its worker caller until a second modeless
  window closed; R2 reached `sys.excepthook` with Overflow and retained the old
  predicate without an inline error; R4 dispatched the stale file three times
  through keyboard, double-click and menu while the new filter was pending.
  Navigation was mocked; the exception hook was intercepted to avoid a dialog.
- Pure filter probe: displayed `0.1` and `0.3` reject equality, `1.5` accepts;
  byte bound `1e1000000` raises Overflow; On/After/Between for the valid day
  preceding an injected skipped date all raise ValueError.
- Real disposable SHA256 fixture: a filename containing U+200B verifies as
  Matched, its engine target exists, but the path captured from `show_results`
  and resolved through `TableSchema.target` differs and does not exist. The
  fixture is removed by TemporaryDirectory; no real navigation was performed.
- Probes were executed from stdin in isolated child processes through
  `build._environment()`; no source or permanent test files were added.
- Reviewed-source editor diagnostics were clear. Document checks cover prior
  content preservation, reviewer placement, local links, scoped whitespace and
  unchanged reviewed-source hashes.
- Not run: full suite, clean/freeze/package, performance catalog, strict docs
  build, portable artifact smoke or manual DPI review. These passing baseline
  tests and defect-observation probes do not establish corrected behavior.


### Review Fix Validation - 2026_10_04

- New regressions: `TableIT.test_modeless_worker_callers_return_in_close_order`
  (R1), `test_filter_editor_rejects_extreme_exponents_through_text_changes` (R2),
  `test_go_to_waits_for_pending_projection` (R4, injected clock; Ctrl+Enter,
  double-click, menu and direct call), `test_row_targets_drive_copy_path_and_go_to`
  (R5); `TypedTableTest.test_extreme_byte_exponents_are_validation_errors` (R2),
  `test_float_cells_match_their_typed_bounds` (R3),
  `test_day_before_a_skipped_date_can_be_filtered` (R6),
  `test_row_targets_override_cell_text_for_navigation` (R5); Checksum
  `test_results_navigate_to_verified_raw_paths_not_escaped_cells` (R5, real
  U+200B filename and a diagnostic row).
- Broad set (whole `test_qt` plus the nine related modules): 442 tests OK,
  2 expected skips, offscreen and native.
- `TableIT` repeated 60 times in one process: 1,020 tests OK.
- Native `search_files_smoke` and `find_files_smoke` PASS; real
  `checksum-files` docs capture produced the results image.
- Not run: full `build.py test`, clean, freeze, strict MkDocs build, packaged
  smoke.