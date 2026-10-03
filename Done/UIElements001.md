# UI Elements 001: Typed Read Only Table

Status: Implemented 2026_10_03.

## Task

Make Table a reusable way to inspect many immutable rows, with typed column
sorting/filtering and simple non-destructive interactions. The caller supplies
data; Table supplies the UI. Other elements remain in [UIElements](../UIElements.md).

## Scope

- Redesign the Qt-free `show_table` / `TableHandle` contract; no compatibility
  layer (user decision 2026_10_03: "no need to keep the old API").
- Keep modal/modeless hosting, snapshot refresh, stable row IDs and cell focus.
- Add the column kinds below, column-header filters and optional caller
  text filtering. No editing, deletion, renaming, file-transfer drag/drop,
  external application launching or unrestricted shell menus.
- Migrate every bundled consumer (Search Files, Find Files, Checksum Files).
  QuickSearch, QuickList, Panel, file panes and search engines are not redesigned.

## Design

### API Revision (2026_10_03)

The user approved breaking the Table API for a simpler design and better
performance. This revision supersedes the compatibility rules below:

- `show_table(columns=...)` is the single schema source; `num_columns`,
  `columns_header` and the three `*_path_column` indices are removed.
- Kinds own navigation: `file_name`/`file_path` (file), `folder_name`/
  `folder_path` (folder) and the new `entry_path` (either). `resolve_path` and
  `base_path` keep their meaning. `TableColumn` has no ID.
- Date/Numeric cells hold raw values (`int` ns, number or `None`); there is no
  `typed_values`. The host formats display text and keeps the raw cells in the
  host-filled `TableRow.values`. `format` (numeric) and `missing` customize text.
- `text_filter` (`'fuzzy'`, `'substring'`, `None`, or a compile callable)
  replaces `fuzzy`, `text_matching` and `compile_text_filter`.
- Text/natural sort keys are cached per snapshot and column.
- Core's natural-key alias is removed.

### API Revision 2: Static Table (2026_10_03)

The user asked for a modal, static design without caller interactivity. This
revision supersedes the handle, refresh, menu, callback and row-ID rules in this
document:

- `show_table(*, columns, rows, pane=None, title='', summary='', modal=True,
  text_filter='fuzzy', base_path=None, truncated=None)` blocks until the window
  closes and returns `None`. No owner, Panel link, handle or refresh.
- `TableRow(cells, highlights=())`; rows are identified by object identity.
- The only caller interaction is `text_filter`. Removed: `get_menu`,
  `get_background_menu`, `TableAction`, `get_details`, `on_activate`,
  `on_closed`, `get_count_text`, `resolve_path`, `close_on_navigate`.
- In-table UI is kept: header sort/filter icons, filter menu, Alt+Down and the
  cell menu (Copy, Go To, Filter This Column..., Clear All Filters).
- Modal (default) closes after a successful Go To. Modeless keeps the table open
  and focuses the pane; Checksum Files uses it so files can be inspected.
- Menus are deleted through `aboutToHide -> deleteLater`. A direct Python
  `deleteLater()` detaches the wrapper from its parent; with closure cycles,
  garbage collection could clear the live menu and crash Qt later.
- Optional `accept='Label'` (user request 2026_10_03, for a future File
  Renamer) adds **Label (N)** / **Cancel** buttons and Ctrl+Enter. Accepting
  returns the input positions of rows passing all filters, in input order;
  otherwise `None`. Disabled while a projection is pending, on filter errors
  and with zero visible rows. Enter stays Go To.

### Columns And Values

Add optional plain `TableColumn` descriptors: stable ID, label, kind and options
for sorting, text searching, column filtering and units. Keep seven public
presets, backed by four comparison policies: text, natural path/name, date and
number. Callers may disable capabilities. Descriptors and legacy column counts/
headers must agree when both are supplied; absent descriptors preserve behavior.

Navigation remains exclusively in `TableSchema.roles`, populated by existing
`file_path_column`, `folder_path_column`, `entry_path_column`, `resolve_path` and
captured `base_path`. Kinds neither duplicate these options nor grant navigation.
Reject Date/Numeric columns carrying path roles; legacy schemas are unchanged.

| Kind        | Column Filtering / Sorting                   | Cell Menu                             |
| ----------- | -------------------------------------------- | ------------------------------------- |
| Text        | Fuzzy or substring / alphabetical            | Copy Text                             |
| File Name   | Fuzzy or substring / natural name            | Copy Name; Go To when a target exists |
| Folder Name | Fuzzy or substring / natural name            | Copy Name; Go To when a target exists |
| Folder Path | Fuzzy or substring / natural path            | Copy Path; Go To folder               |
| File Path   | Fuzzy or substring / natural path            | Copy Path; Go To file                 |
| Date        | On, before, after, between / chronological   | Copy displayed date                   |
| Numeric     | `=`, `<`, `<=`, `>`, `>=`, between / numeric | Copy displayed value                  |

Keep `TableRow.cells` as display strings; add an immutable `typed_values` tuple
in column order. Date/Numeric columns require a full-length tuple, with `None`
for Missing and for other column kinds. Text/path-only tables may omit it. Never
infer metadata from display strings or expose `row.value` to text matchers.

Date values are integer UTC epoch nanoseconds. Date/Numeric integers must fit
signed 64-bit values; Numeric also accepts finite floats. Neither accepts booleans.
Byte values are nonnegative integers. Reject overflow, unrepresentable dates and omitted/short typed tuples
before replacing valid rows. Charge eight bytes per typed slot plus the final
display text and existing payload charges against the 16 MiB serialized-payload
budget; this is not a process-memory guarantee. Legacy validation is unchanged.

The host formats Date cells from raw values, replacing caller text before final
text-budget/highlight validation. `date_display` is `timestamp` (default) or
`date`: ISO 8601 `YYYY-MM-DDTHH:mm:ss` with `Z` or a numeric UTC offset, or
`YYYY-MM-DD`. Filter inputs use `YYYY-MM-DD`; time is 24-hour and locale-independent.
Missing displays `Unknown`. Reject nonempty source highlights on typed Date
cells; preserve them elsewhere. Text matching and Copy use this canonical text
even when caller text is localized or mismatched. Sorting/comparisons retain raw
nanosecond precision. Tables without descriptors keep their existing display.

Numeric ranges include both bounds. Date ranges include whole endpoint days,
using `[start, next_day)` and historical DST rules. Size controls offer explicit
B/KiB/MiB/GiB units; generic numeric columns do not assume bytes. Unknown is
`None`: sorts last both ways, fails comparisons, and has an explicit Missing
filter. Clearing a filter includes unknowns again. Reject invalid schemas or
snapshots before replacing valid rows.

Use a host-owned adapter around `QTimeZone.systemTimeZone()` and `QDateTime`,
captured once per Table lifetime; display and day bounds share that zone and its
historical rules. No fixed-current-offset fallback, polling or new package.
Ambiguous midnight uses the earlier instant; nonexistent midnight uses the first
valid instant that day. A wholly skipped day, invalid zone or unrepresentable
boundary (including next day) reports an inline error and disables Apply, keeping
the last valid filter. Invalid date formatting rejects the incoming snapshot.
Inject this adapter for deterministic transition tests. The pane's independent
[Date Format](../Plan/DateFormat.md) preference remains locale-based by default.

Move Core's `_natural_name_key` into a Qt-free helper under `fman.impl`, retaining
a Core compatibility alias and its current Unicode-digit/case/tie behavior.
Table imports the host helper, never Core; no filesystem access is needed.

### Two Independent Filter Layers

- **Table text query:** default fuzzy matching, optional substring matching, or
  caller `compile_text_filter(query) -> predicate(cell_texts)`. Compile once per
  text edit. The predicate receives only a tuple of searchable display strings,
  in column order, and returns a strict boolean: no row, payload or typed values.
- **Column UI:** header filter menus use the column's typed value and built-in
  operators. Text columns also offer fuzzy/substring choice. These filters are
  independent of the caller hook; they are not clauses in the text query.
- A row must pass the text filter **AND** every active column filter. Default
  text matching accepts a match in any searchable column. Text-like columns are
  searchable by default; Date/Numeric opt in only as displayed text.
- Both layers inspect retained snapshot rows only, never omitted results or a
  live producer. Show `visible / retained` plus `truncated` beside the count when
  the producer reports truncation, even for zero matches. Add optional immutable
  `truncated: bool | None` status to `show_table`/refresh; `None` means not reported,
  not complete. Publish status atomically with rows. Table rejects over-limit
  snapshots rather than silently truncating.
- Empty text accepts all rows at that layer without invoking the hook; column
  filters still apply. Changing a column filter does not recompile the hook.
- The hook is pure, bounded and I/O-free; no provider calls, stat or engine work.
  A callback can capture external state, so this is a contract, not a sandbox.
  Exceptions, invalid predicates or non-boolean results show an inline error
  and no actionable results; retain the snapshot for recovery.
- Default fuzzy matching keeps ranking/highlights; a boolean hook preserves
  source order and adds no highlights. Preserve source-provided hit highlights.
  Explicit column sorting takes precedence; ties use the prior stable order.

### Interaction And Ownership

Use the existing compact query field plus keyboard-accessible header menus,
filter icons with tooltips, active-filter indicators, Clear Filter and Clear All
Filters menu commands. Numeric menus use operator/value inputs; Date uses date
inputs. No permanent filter row, row buttons, checkboxes or action footer.
Keep ascending/descending/unsorted cycling and visible/captured row counts.

Header-label clicks sort; a separate filter-icon hit target opens only the menu.
Alt+Down or Filter This Column in the cell menu opens the current column's menu;
retain existing sorting shortcuts. With no current cell, use the last active
column (initially the first filterable column), including empty tables. The query
field also accepts Alt+Down. Resolve reordered columns by stable ID, not visual
index. Escape/close restores invoking focus; Clear All Filters clears text and
column filters, keeps sorting, closes the menu and restores focus.

Selection never activates a target. Enter/double-click acts only on a navigable
cell. Names need a caller-supplied target or explicit captured base; never infer
paths from ordinary text or the current pane after navigation. Reuse host-owned
Copy Path / tracked Go To, modality, close policy and focus restoration.
Missing targets report an error only on navigation; copying needs no file I/O.
Go To file navigates the application pane to its parent folder and selects the
file; Go To folder navigates that pane into the folder. Neither launches Explorer.

Rows and underlying files are read-only; filtering/sorting changes only the view.
Caller refresh explicitly replaces the snapshot and retains surviving IDs.
Existing custom actions stay compatible, but callers are responsible for keeping
actions in typed Tables non-destructive. No claim of sandboxing arbitrary code.

Extend [table_data.py](../src/main/python/fman/impl/ui/table_data.py),
[table.py](../src/main/python/fman/impl/ui/table.py) and
[facade.py](../src/main/python/fman/impl/ui/facade.py). Qt objects remain host-owned
on Qt; callbacks run there with bounded work. Invalidate projections and open
menus on edits, refresh, close or owner unload; disable actions while pending.
Filters/sort state are session-only; no new persistence or Registry writes.

### Search Files Consumer

[Search Files 003](SearchFiles003.md) supplies File Path, Size, Date Modified and
Snippet. It owns opt-in metadata collection, cancellation and bounded snapshots;
Table owns Size/Date column controls. Revise that plan before implementation:
its earlier `size:` / `dm:` query clauses and raw-row filter/sort hooks are
superseded for this integration. The caller may still provide text-only matching.
Off mode keeps today's two-column fuzzy results with no added metadata work.

Producer filters constrain discovery before retention and require an explicit
rerun to change the search scope. Table filters refine only the retained snapshot
without rerunning or recovering omitted rows. Keep producer date/size controls
where they prevent unwanted capture; they are not synchronized with Table filters.
Consumers report truncation from their existing capture limits. A later Checksum
Files task may replace summary-row view switching with a Status column filter;
that consumer change is outside this task.

## Alternatives

- Per-consumer numeric/date hooks duplicate shared behavior; use typed columns.
- Removing caller text filtering is too restrictive; keep it independent.
- Parsing formatted cells loses precision and date meaning; use raw values.
- Four public kinds would discard the requested name/path distinctions; keep
  seven presets with shared comparison policies and existing navigation roles.
- Archiving the old toolkit history is superseded by the user's removal request;
  repair obsolete references without restoring that history.
- A generic editor or full search language expands scope; neither belongs here.

## Runtime Effects

- Unopened/disabled: no feature-specific jobs, metadata I/O, scans or timers.
- Opening validates one snapshot within current 10,000-row / 16 MiB payload
  limits, including new values. No per-cell widgets or implicit metadata fetches.
  Date tables resolve the zone once; other tables do no timezone work. Refresh
  may briefly retain both snapshots; account for tuple/scalar and projection RAM
  separately from the logical payload budget when measuring the near-cap case.
- Filtering is in-memory O(rows x active columns); sorting is O(rows log rows).
  Reuse bounded projection slices (about 6 ms), checking even rejected rows.
  Measure final sorting too; no unbounded callback or stale publication.
- No new process/package is required. Only explicit Go To uses existing
  navigation I/O. Close/unload cancels pending UI work and releases snapshots.

## Tests

- Unit: all seven kinds, signed-64-bit boundaries, huge integers, nonfinite
  floats, invalid dates, omitted/short tuples, Missing and near-cap snapshots;
  exact numeric/date bounds, stable sorts and unchanged legacy declarations.
- Hook: text-only arguments, one compilation per text edit, empty text, strict
  results/errors, no metadata access, and AND with active column filters.
- Qt: header controls/indicators/clear, keyboard and cell menus, selection by ID,
  source highlights, refresh, invalid-to-valid recovery and stale-action guards.
  Cover separate sort/filter hit targets, Alt+Down with empty/reordered columns,
  Escape/focus restoration, Clear All Filters and unchanged legacy shortcuts.
- Dates: ISO display, filter input and clipboard text under different OS locales;
  localized/mismatched caller text is replaced before budget/highlight checks;
  timestamp/date/Missing modes and 24-hour offsets across DST transitions.
  Inject historic rule changes, ambiguous/nonexistent midnight, skipped dates,
  invalid zones and next-day overflow; verify zone capture survives OS changes.
- Regression: existing Table, Search Files, Find Files and Checksum Files flows;
  no extra stat/provider calls during filtering or with metadata disabled.
  Truncated snapshots retain their warning after zero matches, clearing and
  refresh; absent status never asserts completeness and producer filters do not
  change. Core natural-key tests remain passing.
- Performance: 10,000 rows near the byte cap, accepting/rejecting/mixed filters;
  measure one Date/Numeric column-filter edit from committed input to completed
  result paint, with an empty text query and no sort: target p95 <100 ms, ceiling
  1 s on the recorded test host. Record p50/p95, peak RAM and Qt heartbeat; measure
  sorting separately. No stale commits after close/refresh.
- Manual: native Windows, both themes, narrow/wide windows, 100/150/200% DPI;
  keyboard-only menus, date/size filters, copy, missing targets and focus return.

Reuse existing tests; focused commands from the repository root:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'fman_unittest.test_ui_elements', 'fman_unittest.test_portable.PluginApiCompatibilityTest', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'unittest', 'core.tests.fs.test_columns', '-v'], env=build._environment()))"
python -c "import build, subprocess, sys; sys.exit(subprocess.call([sys.executable, '-m', 'fman_integrationtest.qt_runner', 'fman_integrationtest.test_qt.TableIT', 'fman_integrationtest.test_qt.SearchFilesIT', 'fman_integrationtest.test_qt.FindFilesIT', 'fman_integrationtest.test_qt.ChecksumFilesIT'], env=build._environment()))"
```

Run the smallest new test immediately after the first implementation edit.
Design-only checks: sections, links and scoped whitespace.
No full suite, clean or freeze without an explicit request.

## Implementation Steps

1. Review the typed/text-hook contracts and align Search Files 003 before code.
2. Add descriptors, bounded typed values, date adapter and shared natural key;
  run focused validation/format/operator tests and Core natural-key tests.
3. Add text-hook composition, typed sorting and header controls; connect existing
  consumers' truncation status and run Table/consumer tests.
4. Verify legacy consumers, limits, responsiveness and native interaction.
5. Update API/usage docs and application changelog at implementation; record
   actual checks before moving this task to Done. Consumer metadata work stays
   in Search Files 003, not this task.

## Acceptance Criteria

- Seven declared kinds provide the specified filters, sorts and safe actions.
- Date displays, filter inputs and copied dates use ISO 8601 regardless of locale.
- Host-formatted Date text agrees with raw values; the captured historical zone,
  midnight policies and budget/value bounds are enforced before publication.
- Caller text filtering remains optional, text-only and independent of column UI.
- Both filter layers combine correctly; raw values, unknowns and clear work as
  specified without modifying data or rerunning producers.
- Counts disclose truncation even with no matches; menus work without a mouse
  on empty/reordered tables and never turn filter clicks into sort actions.
- Existing API/consumers, identity, focus, lifecycle and bounds remain intact.
- Focused tests and manual/performance checks pass; unrun checks stay explicit.

## Reviewers

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Narrowed the active plan to typed, read-only Table. Kept the caller's
  text-only filter hook independent of built-in column UI filters; preserved
  historical records. Design only; consumer alignment and review precede code.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Required ISO 8601 date display, filter input and clipboard text,
  independent of OS locale; retained raw timestamps and timezone-aware filtering.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Revisions required before implementation (T1-T5). The direction is
  sound: one existing Qt-free Table with typed values, independent text/column
  filter layers and read-only data. Simplify the column kinds, define filtering
  of truncated snapshots and keyboard access, fix the timezone source, and
  repair broken plan links. T6-T9 are minor. Design-only review; no tests run.

#### Design Review Findings

Checked against [table.py](../src/main/python/fman/impl/ui/table.py),
[table_data.py](../src/main/python/fman/impl/ui/table_data.py) and
[facade.py](../src/main/python/fman/impl/ui/facade.py).

| ID  | Priority | Finding                                                                                                                                                                                                                                                                                                                         | Required change                                                                                                                                                                                                                                 |
| --- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | P2       | **Path kinds duplicate existing roles.** `TableSchema` already has `file_path_column`, `folder_path_column`, `entry_path_column`, `resolve_path` and `base_path`. File Name, Folder Name, File Path and Folder Path re-declare navigation, which is why the design needs a "reject conflicting declarations" rule.              | Use four kinds: Text, Path (natural sort), Date and Number (with an optional byte unit). Keep navigation in the existing roles and resolver.                                                                                                    |
| T2  | P2       | **Filtering a truncated snapshot.** Find Files, Search Files and Checksum Files keep at most 10,000 rows and already filter by date/size at the producer. A Table filter only sees retained rows, so "no matches" can mean "not retained". Two date/size filters (panel and Table) for one search also need a clear role split. | State that column filters apply to retained rows only. Show the snapshot's truncation state next to the filtered count. Define when consumers use producer filters versus Table filters.                                                        |
| T3  | P2       | **Keyboard access to header menus is undefined.** `QHeaderView` is not focusable, and a header click already cycles sorting (`sort_by`).                                                                                                                                                                                        | Specify the trigger: for example, a "Filter column..." cell-menu entry plus a key such as Alt+Down on the current column, opening the current column's menu. Specify how a header click chooses between sorting and the filter icon. Test both. |
| T4  | P2       | **Timezone source is unspecified.** "Historical DST rules" in local time depend on the source: the CRT `localtime` applies current rules, and `zoneinfo` needs a tz database on Windows.                                                                                                                                        | Pick one source (for example `QTimeZone.systemTimeZone()`, or Windows dynamic-DST APIs). Use it for display, day bounds and tests. Align with [DateFormat](../Plan/DateFormat.md), which keeps the pane's Modified column locale-based.                 |
| T5  | P2       | **Broken links after the rename.** `Plan/UIElements.md` no longer exists, but 15+ links in `Done/CalculateFileHash.md`, `Done/Favorites002.md`, `Done/FindFiles001.md`, `Done/SearchFiles001.md` and `Plan/FindFiles003.md` still point to it, several with section anchors that now live inside the collapsed history.         | Move the superseded toolkit plan and its history to `Done/UIElements.md` (retired, as with `Done/ImprovePaneScan.md`), update the incoming links, and keep this file to the active Table task.                                                  |
| T6  | P3       | Natural sorting is implemented in the Core plug-in, which host code must not import.                                                                                                                                                                                                                                            | Name the host-side natural key to use, or plan to move it into `fman.impl`.                                                                                                                                                                     |
| T7  | P3       | The performance target "metadata-only p95 <100 ms" does not define the operation.                                                                                                                                                                                                                                               | Name it: for example, one column-filter edit over 10,000 rows, measured from the edit to the completed paint.                                                                                                                                   |
| T8  | P3       | "Reveal file in its folder" could be read as launching Explorer, which Scope excludes.                                                                                                                                                                                                                                          | Say "navigate the pane to the parent folder and select the file".                                                                                                                                                                               |
| T9  | P3       | `UIElements.md` at the repository root is untracked, yet Task links to it. Checksum Files' summary-row view switching could become a Status column filter.                                                                                                                                                                      | Track or relocate the root document; note the Checksum Files simplification as a consumer follow-up.                                                                                                                                            |

Read-only review: no source, test or other plan files were changed.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Reviewed only the active typed-Table proposal, excluding toolkit
  history and earlier review conclusions. Clarify N1 date formatting ownership,
  N2 historical timezone source and N3 raw value bounds before implementation;
  N4 keyboard interaction is a smaller clarification. Kept seven kinds and both
  independent filter layers. No implementation changes or completed runtime checks.

#### Active Proposal Review (Sol)

Scope: the Task through Acceptance Criteria at the top of this file only.
Historical toolkit requirements and earlier findings were not evaluated or used
as requirements. The separation of producer data, typed column filters and an
optional text-only hook is coherent; these contract details remain unresolved.

| ID  | Priority | Finding                                                                                                                                                                                                                                                                                                                                                                                                                                  | Required Clarification                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N1  | P2       | **Date formatting ownership is ambiguous.** Columns And Values keeps caller-provided `TableRow.cells` as display strings while also requiring ISO Date display and clipboard text from raw timestamps. A caller's localized cell can disagree with the typed value used for filtering.                                                                                                                                                   | Choose host formatting for typed Date cells, or require and validate caller-supplied canonical text. Define date-only/timestamp options, Unknown display and mismatch handling. Apply formatting before final payload/highlight validation; text matching and Copy must see the same validated display. Legacy tables without descriptors must remain unchanged. Test a localized/mismatched date cell against its raw timestamp.                                                  |
| N2  | P2       | **The historical timezone source is not selected.** Local time plus historical DST is a requirement, but the plan does not identify the Windows-capable provider or when the zone is captured. Display and filter boundaries can otherwise use different rules.                                                                                                                                                                          | Select one provider, such as the existing Qt `QTimeZone` through a host-owned adapter, and use it for both ISO offsets and day boundaries. Define zone capture for the session, ambiguous/nonexistent midnight policy and unrepresentable next-day errors. Inject the conversion boundary for deterministic historical-DST tests; do not substitute a fixed current offset. No new package is needed if the existing Qt provider is chosen.                                        |
| N3  | P2       | **Raw integer/date bounds are missing from the budget contract.** Numeric permits arbitrary integers while Runtime Effects promises the 16 MiB limit includes new values. Existing [plain_size](../src/main/python/fman/impl/ui/table_data.py#L234) charges integers/floats zero bytes, so unrestricted integers cannot inherit that memory guarantee. Raw dates also need a representable range before display and calendar conversion. | Specify bounded integer magnitudes and representable UTC-nanosecond dates, or explicitly account for integer magnitude in typed payload validation. Reject invalid values before replacing a valid snapshot. State whether omitted typed values mean all Missing or are rejected; never infer Date/Numeric from display strings. Add large-integer, invalid-date, omitted-value and near-cap regression cases. This is a static design risk, not a completed runtime reproduction. |
| N4  | P3       | **Header-menu keyboard invocation is unspecified.** The proposal promises keyboard-accessible menus, but the existing [header click](../src/main/python/fman/impl/ui/table.py#L184) cycles sorting.                                                                                                                                                                                                                                      | Name the keyboard invocation and focus return, for example a current-column menu shortcut or Filter This Column in the cell menu. Separate the header-label sort hit target from the filter icon. Cover empty tables, column movement, Escape and Clear All Filters without changing legacy sorting shortcuts.                                                                                                                                                                     |

Design-only validation: the named source boundaries and focused test targets
exist; Markdown diagnostics were clear. The attempted compatibility test and
numeric runtime probe were canceled and have no completed results. They were
not retried after the scope clarification. No typed columns are implemented, so
existing tests would establish a baseline only, not prove the new contract.
Append-only content, active-section preservation, active/new local links and
scoped whitespace are checked separately. No source, consumer plan, index,
changelog, full suite, clean or freeze change was made.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revised the active design for T1-T9 and N1-N4; retained the user's
  seven column presets and independent text-only hook. Implementation and its
  runtime gates remain pending.

#### Review Resolution

- T1: retain seven public presets, share four comparison policies and reuse
  existing path roles/resolver; do not add a second navigation contract.
- T2-T4, T6-T8, N1-N4: specify retained-row filtering/counts, keyboard hit targets,
  captured Qt timezone and day-boundary errors, canonical host date text, bounded
  typed values, host-owned natural sorting, pane navigation and timed paint gates.
- T5: the user requested deletion, not archival. History stays removed; repair
  incoming catalogue/API links and identify deleted historical validation sources
  without redirecting their evidence claims to unrelated documents.
- T9: keep the root catalogue and the separate Checksum Status-filter follow-up.
  The catalogue and this task are untracked; include them when the user stages
  the work. No staging or commit is authorized by this design revision.

Design validation: PowerShell contract/section checks, local-link checks against
the committed baseline, normalized-table checks and scoped `git diff --check`.
Existing reviewer records remain intact apart from table alignment. One unrelated
broken model-source link already exists in Favorites' completed document; it is
not repaired here. Whole-file whitespace checks flag two existing Markdown hard
breaks in the root catalogue; both are unchanged. No new whitespace issues.
No application code changed or runtime tests were run; the
commands under Tests are implementation gates, not completed validation.

## Implementer

### 2026_10_03 - Maintainer and Documenter Claude Opus 5.5

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented with [Search Files 003](SearchFiles003.md) as consumer.
  Added `TableColumn`, `TableRow.typed_values`, host date adapter
  ([table_dates.py](../src/main/python/fman/impl/ui/table_dates.py)), typed
  filters ([table_filters.py](../src/main/python/fman/impl/ui/table_filters.py)),
  shared natural key ([natural.py](../src/main/python/fman/impl/util/natural.py)),
  `TableHeader` with palette-tinted Lucide sort/filter icons, the filter menu,
  Alt+Down, `compile_text_filter`, `text_matching` and `truncated`. Deviations:
  header sections are not movable, so reordered-column handling is not needed;
  Find Files and Checksum Files keep `truncated=None` because their own summaries
  already disclose limits.

## Validation Results

From the repository root, with `QT_QPA_PLATFORM=offscreen` (and
`QT_QPA_FONTDIR=%WINDIR%\Fonts`) unless noted:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-B', '-m', 'unittest', 'fman_unittest.test_ui_elements', 'fman_unittest.test_search_files', 'fman_unittest.test_portable.PluginApiCompatibilityTest', 'core.tests.fs.test_columns'], env=build._environment()).returncode)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-B', '-m', 'unittest', 'fman_integrationtest.test_qt.TableIT', 'fman_integrationtest.test_qt.SearchFilesIT', 'fman_integrationtest.test_qt.ChecksumFilesIT', 'fman_integrationtest.test_qt.FindFilesIT', 'fman_integrationtest.test_qt.PanelIT'], env=build._environment()).returncode)"
```

- Unit: 75 tests OK, including new `TypedTableTest` (descriptor validation,
  INT64/float/bool bounds, ISO formatting, injected DST gap/overlap/skipped day,
  all operators and bounds, natural key).
- Qt offscreen: 36 tests OK. New `TableIT` cases cover funnel click vs label sort,
  sort cycle with Unknown last, filter menu apply/clear, Alt+Down, cell-menu
  Copy/Filter/Clear actions, text hook compile-once, strict bool and errors,
  and truncation note.
- Qt native (`QT_QPA_PLATFORM=windows`): `TableIT`, `SearchFilesIT` and
  `fman_integrationtest.test_search_files_engine`: 31 tests OK (1 expected skip).
- Performance, native, 10,000 rows with ~1.3 KB snippets, 20 runs each:
  open 492 ms; date Between filter p50 31 ms / p95 46 ms; size reject-all
  p50 17 / p95 19 ms; accept-all p50 39 / p95 42 ms; date sort p50 25 / p95 29 ms;
  Python peak 18.4 MiB (tracemalloc). Target p95 < 100 ms met.
- Visual: rendered header and filter menu captures reviewed; icons follow the
  palette and the active funnel uses Highlight.
- Not run: manual DPI 150/200%, dark theme, other OS locales and Qt heartbeat
  measurement. Full suite, clean and freeze not run per policy.

### API Revision Implementation (2026_10_03)

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Applied the [API Revision](#api-revision-2026_10_03) in
  [table_data.py](../src/main/python/fman/impl/ui/table_data.py),
  [table.py](../src/main/python/fman/impl/ui/table.py) and
  [facade.py](../src/main/python/fman/impl/ui/facade.py); migrated Search Files,
  Find Files (raw `size` / `modified_ns`, typed Size/Modified) and Checksum Files;
  removed the Core alias; updated PlugIn.md, consumer READMEs and the changelog.

### API Revision Validation

Offscreen (`QT_QPA_PLATFORM=offscreen`, `QT_QPA_FONTDIR=%WINDIR%\Fonts`):

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-B', '-m', 'unittest', 'fman_unittest.test_ui_elements', 'fman_unittest.test_search_files', 'fman_unittest.test_find_files', 'fman_unittest.test_checksum_files', 'fman_unittest.test_portable.PluginApiCompatibilityTest', 'core.tests.fs.test_columns', 'fman_integrationtest.test_qt.TableIT', 'fman_integrationtest.test_qt.SearchFilesIT', 'fman_integrationtest.test_qt.ChecksumFilesIT', 'fman_integrationtest.test_qt.FindFilesIT', 'fman_integrationtest.test_qt.PanelIT'], env=build._environment()).returncode)"
```

- Offscreen: 191 tests OK.
- Native (`QT_QPA_PLATFORM=windows`): `TableIT`, `SearchFilesIT`, `FindFilesIT`,
  `ChecksumFilesIT` and `test_search_files_engine` passed 8 consecutive runs.
  Before that, the same native sequence ended with an access violation in
  `ChecksumFilesIT.test_empty_truncated_and_maximum_snapshots` (3 runs) and in
  inconsistent bisect subsets. HEAD sources passed the same sequences. The cause
  was not isolated; treat it as an open native-stability item.
- Performance, native, 10,000 rows, no tracemalloc, 20 runs each: open 112 ms;
  date Between filter p50 14 / p95 15 ms; size reject-all p50 4 / p95 5 ms;
  date sort p50 13 / p95 15 ms; natural sort p50 12 / p95 14 ms; query edit
  with active natural sort p50 28 / p95 38 ms.

### API Revision 2 Implementation (2026_10_03)

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Applied [API Revision 2](#api-revision-2-static-table-2026_10_03).
  Search Files and Find Files show results modally with the root and run
  summary; Checksum Files shows all retained rows modelessly. Fixed a Search
  Files regression where results used the pane's new folder instead of the
  captured root. Isolated the earlier intermittent access violation: a closed
  menu whose wrapper had been released by a direct `deleteLater()` was garbage
  collected while Qt still owned it (deterministic with `gc.collect()`).
  Deferred focus and projection callbacks now use timers owned by the widget.
  The checksum docs screenshot now captures the results table.

### API Revision 2 Validation

Same launcher as above with these modules:

```text
fman_unittest.test_ui_elements fman_unittest.test_search_files fman_unittest.test_find_files
fman_unittest.test_checksum_files fman_unittest.test_portable.PluginApiCompatibilityTest
core.tests.fs.test_columns fman_integrationtest.test_qt.TableIT
fman_integrationtest.test_qt.SearchFilesIT fman_integrationtest.test_qt.ChecksumFilesIT
fman_integrationtest.test_qt.FindFilesIT fman_integrationtest.test_qt.PanelIT
```

- 186 tests OK in 4 consecutive offscreen runs and 2 native (`windows`) runs.
- `TableIT` repeated 60 times in one process: 720 tests OK (it crashed before
  the fix). `test_typed_columns_header_icons_filter_menu_and_sort` now calls
  `gc.collect()` after closing both menu types as a regression check.
- `fman_unittest.test_generate_docs_screenshots`: 29 tests OK. The real
  `checksum-files` source capture produced the results screenshot.
- Not run: full suite, clean, freeze, strict MkDocs build.

### Accept Result Implementation (2026_10_03)

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Added `accept` to `open_table`/`show_table` and `TableWindow`;
  `Table.settled` and `Table.visible_positions()`. Tab characters render as one
  space in cells (found while capturing Search Files screenshots).

### Accept Result Validation

- New `TableIT.test_accept_returns_visible_input_positions`: text filter with
  descending sort and Ctrl+Return from the filter box, column filter with
  Ctrl+Enter from the view (modeless), shared row objects, zero visible rows,
  Cancel, no button without `accept`, invalid labels.
- Focused set (without `core.tests.fs.test_columns`): 170 tests OK offscreen
  and native; 56 tests OK offscreen after the tab rendering change.
- Native screenshots of real fd / ripgrep results and an accept-mode table were
  reviewed (temporary capture script, not kept).