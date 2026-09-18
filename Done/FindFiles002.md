# Find Files 002: Result Metadata

Status: Implemented and source-validated. Network-share and packaged smoke
checks remain unverified.

## Task

Let the SearchFileFuzzy results (`Ctrl+F` / `Ctrl+Shift+F`) show each file's
last-modified date and size on the item's description line, below the relative
path. The feature is off by default and is switched on and off with a Command
Center command, `Toggle search result metadata`, whose state is persisted.

Motivation: a result list of bare paths does not help choose between
`report.pdf` in three folders; the pane already shows `Modified` and `Size`
for every file, and the same two facts identify the right hit. The toggle
exists because the extra line halves the number of visible rows.

## Scope

Included:

- Setting `show_metadata` (`false` by default) in `SearchFileFuzzy.json`.
- Application command `toggle_search_result_metadata`, aliases `Toggle search
  result metadata` and `Search files: toggle modified date and size`. It flips
  and saves `show_metadata` and shows `Search result metadata: On|Off` for 3 s.
  No default key binding; Command Center only.
- Optional `metadata` argument (`true|false`) on the two existing search
  commands for custom key bindings, mirroring the existing `mode` argument.
- When enabled, each result's `QuicksearchItem.description` is
  `<modified>, <size>`, for example `2026-09-13 22:00, 1.2 MiB`. The date is
  ISO-like local time, identical in every locale. A missing value is omitted;
  when both are missing the second line is visually blank but reserved with
  `description=' '`. Zero bytes is a valid value displayed as `0 B`.
- Metadata collected during the existing index walk for `file://` locations
  and, best effort, for other schemes through the public filesystem API.
- README and CHANGELOG updates; tests.

Excluded:

- New columns, sorting or filtering by date or size (query filters such as
  `size:` and `dm:` are [Find Files 003](../Plan/FindFiles003.md)).
- Creation time, attributes, owner, or details for hint rows.
- Any change to `show_quicksearch`, `QuicksearchItem`, the Quicksearch widget,
  other pickers, or the public `fman` API.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. With
`show_metadata` false, results and ranking are unchanged and there is no extra
metadata I/O or per-row formatting. The wider records add 16 bytes each on
64-bit Python (800,000 bytes at 50,000 entries), even when disabled.

## Design

### Index

`SearchEntry` in
[matcher.py](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/matcher.py)
gains two trailing fields with `None` defaults:

```python
SearchEntry = namedtuple(
    'SearchEntry', 'url name relative_path size_bytes modified_ns',
    defaults=(None, None)
)
```

Existing positional constructions in tests and `indexer.py` stay valid.
[Find Files 003](../Plan/FindFiles003.md) later adds `created_ns` the same way; both
tasks share this record and the collection point below.

`build_index(..., collect_metadata=False)` in
[indexer.py](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/indexer.py):

- Local walk: collect `st_size` and `st_mtime_ns`, reusing the non-following
  stat used by hidden filtering for ordinary files. Follow file symlinks like
  Core's pane; fall back to link metadata only for `FileNotFoundError`.
  Other metadata `OSError`s leave both fields `None`; the entry is retained.
  Existing hidden-filter errors still skip entries, and directory links remain
  excluded. Ordinary Windows entries use listing data; reparse points and
  network paths can require I/O and are not claimed to be free.
- Other schemes: when enabled, after the existing `is_dir(url)` call, read
  `fman.fs.query(url, 'size_bytes')` and `query(url, 'modified_datetime')`.
  Caching is provider-specific, not guaranteed. Read each attribute independently
  so one unavailable value does not discard the other. Convert datetime values
  to nanoseconds; unsupported attributes, invalid values and conversion errors
  yield `None`. Zero remains a valid size and timestamp.
- Metadata-enabled indexing uses the public `Task`/`submit_task` mechanism.
  Check cancellation between entries and provider calls; publish only a completed
  index. Existing pane `on_path_changed`/`on_closed` subscriptions set a stale
  event, including navigation away and back. Unsubscribe in `finally`, and reject
  stale results before opening the picker or navigating to a selected result.
  The path callback also fires when the current location finishes loading, so a
  search started during loading can be discarded; rerun once the folder is ready.
  Stale results remain silent. A canceled or incomplete non-stale task reports
  `File search canceled.` for three seconds after clearing the indexing status.
  The existing lifecycle hooks are a fork dependency; no public signature changes.
  A blocked synchronous provider call cannot be interrupted; stop once it returns.
- Disabled searches use the original indexing path without progress tasks,
  lifecycle subscriptions, cancellation polling or metadata queries.

### Presentation

A pure helper `describe_metadata(entry)` in `__init__.py` (or a small
`metadata.py`) returns the description string:

- Size: `fman.impl.status_bar.format_size(size_bytes)`, the formatter used by
  Core's `Size` column and directory totals, so units and the configured
  `size_divisor` match the pane. This is the same documented fork-specific
  coupling Core already relies on; the plug-in imports nothing else from
  `fman.impl`.
- Modified: `datetime.fromtimestamp(modified_ns / 1e9)` in local time,
  rendered as `%Y-%m-%d %H:%M` (`2026-09-13 22:00`). This deliberately differs
  from the pane's locale-dependent `Modified` column so the description reads
  the same on every system and sorts lexically. Seconds are omitted; the
  pane does not show them either. `OverflowError`, `OSError` and `ValueError`
  from out-of-range timestamps yield an empty part. No Qt import is needed.
- Join the available parts with `, `.

`get_items` uses `description=describe_metadata(entry) or ' '` only when metadata
is enabled. This reserves equal two-line rows without changing Quicksearch or
its API. The helper itself returns `''` when no values exist. Formatting happens
per yielded row, bounded by configured `max_results` (100 by default), with no
query-time I/O. Existing fuzzy search has no synthetic hint rows to decorate.

### Settings And Command

`_get_settings` validates `show_metadata` as a boolean (default `false`) and
applies the `metadata` argument when given, like `mode`. `_search` passes
`collect_metadata=settings['show_metadata']` to `build_index`.

`ToggleSearchResultMetadata(ApplicationCommand)`:

1. `current = _get_settings()['show_metadata']`.
2. `values = dict(load_json('SearchFileFuzzy.json', default={}))`; set
   `values['show_metadata'] = not current`; `save_json('SearchFileFuzzy.json',
   values)`. The loaded dict is copied, never mutated in place, and unrelated
  keys survive. A save `OSError` reports `Could not save search result metadata`;
  a differential-save `ValueError` reports `Search result metadata settings
  conflict`. Both messages include the underlying error, last five seconds and
  leave the state unchanged.
3. `show_status_message('Search result metadata: On', timeout_secs=3)` or
   `... Off`.

The toggle affects the next search. The Quicksearch dialog is modal, so the
command cannot run while results are open.

## Alternatives

- **Put the metadata in `hint`** (right-aligned on the title line): the title
  is a relative path that is often long and would collide with or elide the
  hint. The description line keeps the path readable. Rejected.
- **Always collect metadata, toggle display only**: even listing-backed Windows
  stats require Python work and retained values, while other providers may do
  I/O. Disabled features must avoid that work. Collection follows the setting.
- **Stat lazily in `get_items`**: up to 100 `stat` calls per keystroke on the
  Qt thread, unbounded on network shares. Rejected.
- **Local size/date formatting instead of `format_size`**: avoids the
  `fman.impl` import but the search list would disagree with the pane on
  units (`KiB` vs `KB`) whenever `size_divisor` is 1000. Rejected in favor of
  one documented coupling, following Core's own columns.
- **Locale short date like the pane's `Modified` column** (`13/09/26 22:00`):
  consistent with the pane but ambiguous across locales (`09/13/26` vs
  `13/09/26`) and not lexically sortable. Rejected in favor of ISO-like
  `YYYY-MM-DD HH:MM`.
- **Two-line title with `\n`**: the Quicksearch renderer lays out a single
  title line; description is the supported second line. Rejected.
- **A key binding for the toggle**: the remaining free `Ctrl+<letter>`
  combinations are scarce and the toggle is infrequent. Command Center only.

## Runtime Effects

- Startup: registers one additional application command; no I/O, timers or
  workers.
- Disabled: no extra metadata I/O, formatting, task or subscriptions; each
  record has two additional slots (16 bytes on 64-bit Python).
- Enabled, `file://`: listing-backed stat for ordinary Windows files, additional
  I/O possible for links/network paths; integer metadata adds further memory.
  Measure indexing, allocation and per-keystroke formatting separately.
- Enabled, other schemes: up to two provider queries per file on the existing
  command worker, with count bounded by `max_entries`, not a time guarantee.
- Two-line rows use more vertical space; Quicksearch may increase its height.
  All enabled result rows reserve the second line, including missing metadata.
- Toggle: one JSON read and one atomic JSON write on the command worker.
- Cancellation: existing progress UI plus scoped pane callbacks, no new worker,
  timer or recurring background work. An in-flight provider call can delay exit.

## Tests

Focused commands:

```powershell
$env:PYTHONPATH="src/main/python;src/unittest/python;src/integrationtest/python;src/main/resources/base/Plugins/Core;src/main/resources/base/Plugins/SearchFileFuzzy"
$env:PYTHONUTF8="1"
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest fman_unittest.test_search_file_fuzzy
python -m unittest fman_integrationtest.test_qt.SearchFileMetadataIT fman_integrationtest.test_qt.SearchFileSyntaxIT
```

Repeat with `QT_QPA_PLATFORM=windows`, `QT_ENABLE_HIGHDPI_SCALING=1` and
`QT_SCALE_FACTOR=1` / `1.5`. The real-loader check must also expose the toggle's
aliases and visibility in `ApplicationCommandRegistry`, then unload cleanly.

Extend `fman_unittest.test_search_file_fuzzy`:

- `BuildIndexTest`: with `collect_metadata=True` local entries carry the
  fixture file's exact `st_size` and `st_mtime_ns`; with the default they are
  `None`; a file that disappears between listing and `stat` is indexed with
  `None` fields; hidden-attribute filtering still works with a single `stat`
  per entry (patched `DirEntry.stat` call count). Non-local path: patched
  `fman.fs.query` returning values, raising `OSError` and raising
  `NotImplementedError`.
- `DescribeMetadataTest`: both values, size only, date only, neither (empty
  string); zero size and zero timestamp; `format_size` divisor 1000 and 1024;
  numeric date format `YYYY-MM-DD HH:MM`; an out-of-range timestamp yields the
  size only; existing three-field `SearchEntry` construction still works.
- `SettingsTest`: `show_metadata` default `false`; non-boolean values fall
  back; `metadata=True|False` argument overrides the setting.
- `MetadataCommandTest` and existing `SearchCommandTest`: metadata-on descriptions
  and `collect_metadata=True`; off descriptions empty with no metadata option,
  formatting, task or lifecycle callbacks; incomplete, canceled, stale and errored
  indexing cannot publish results. Verify callback cleanup on every outcome,
  cancellation feedback after status cleanup, and silent stale-result rejection.
- `ToggleMetadataTest`: flips `false -> true -> false`, `save_json` receives a copy
  containing unrelated keys unchanged, the correct status message is shown,
  and save `OSError` / `ValueError` failures leave settings untouched and report
  distinct write-failure / settings-conflict messages.
- `SearchFileMetadataIT`: real progress Cancel and pane signals against an
  event-controlled blocked provider, including same-location load completion,
  navigation away/back and pane destruction; cancellation status survives cleanup.
  Mixed/all-missing row geometry, filtering, highlights, Return and
  Escape with the shipped styles at both scale factors. `SearchFileSyntaxIT`
  continues covering real-folder search and existing syntax behavior.
- Real Config persistence under temporary `UserSettings` and actual ZIP provider
  metadata, including empty-file size and a fixed timestamp.
- Performance: `SEARCH_METADATA_PERFORMANCE_TESTS=1` enables
  `python -m unittest fman_unittest.test_search_file_fuzzy.SearchMetadataPerformanceTest`.
  Build/remove a 50,000-file tree and measure on/off time, retained/peak allocation
  and 100-row formatting separately. No hard performance bound is claimed.
- Manual: real folder at 100 % and 150 % scaling, `Toggle search result
  metadata` from the Command Palette, dates in the dialog match the pane's
  `Modified` values (different format, same instant), a `zip://` folder
  shows sizes and dates, a network share still indexes.

## Implementation Steps

1. Extend `SearchEntry` with defaulted fields; run the existing suite to
   prove nothing changes.
2. Add `collect_metadata` to `build_index`, both walks, with tests.
3. Add `describe_metadata` and its tests.
4. Add `show_metadata`/`metadata` handling to `_get_settings` and `_search`;
   wire `description` into `get_items`; tests.
5. Add `ToggleSearchResultMetadata`; tests.
6. Update `SearchFileFuzzy.json`, the plug-in README and `CHANGELOG.md`.
7. Run the focused suite, record performance and manual checks, then move
   this document to `Done/` and update `Plan.md`.

## Acceptance Criteria

- Default results and ranking are unchanged; disabled metadata performs no
  feature-specific queries, formatting, progress task or lifecycle subscriptions.
- `Toggle search result metadata` in the Command Center flips the setting,
  persists it under `UserSettings`, preserves unrelated keys and reports
  `Search result metadata: On|Off`.
- With metadata on, every local result shows `<modified>, <size>` on its
  description line: the date as `YYYY-MM-DD HH:MM` local time in every
  locale, the size formatted like the pane's `Size` column; unavailable
  values are omitted rather than shown as placeholders. Zero size displays
  `0 B`; missing metadata still reserves a blank second line without clipping.
- `zip://` results show metadata when the provider supplies them; providers
  without metadata produce a blank reserved line and no error. File-link
  metadata follows the pane's target/fallback semantics.
- Canceled/incomplete/stale metadata indexes do not open a picker or navigate;
  scoped subscriptions are removed on success, cancellation and errors. Non-stale
  cancellation reports `File search canceled.` after clearing the indexing status.
- No file under `src/main/python/fman` changes; the only `fman.impl` import
  in the plug-in is `format_size`.
- Focused tests pass; performance figures are recorded.

## Reviewers

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Designed an opt-in `show_details` setting with a Command Center
  toggle. Metadata is collected during the existing index walk only when
  enabled (free from `DirEntry` on Windows; cached provider queries elsewhere)
  and rendered per visible row as `<modified>, <size>` in the Quicksearch
  description line, formatted like Core's `Modified`/`Size` columns. Shares
  the extended `SearchEntry` with Find Files 003. Open for review: the
  `format_size` coupling and the `, ` separator.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: User feedback applied: renamed the feature from "details" to
  "metadata" (`show_metadata`, `metadata` argument,
  `toggle_search_result_metadata`, `collect_metadata`, `describe_metadata`)
  and replaced the locale short date with ISO-like local time
  `YYYY-MM-DD HH:MM` via `datetime.strftime`, removing the Qt dependency from
  the formatter. The pane's locale format is recorded as a rejected
  alternative.

  ### 2026_09_18 - GitHub Copilot

  - Role: Reviewer
  - Activity: Review
  - Agent: GitHub Copilot
  - Model: GPT-6 Astra
  - Effort: High
  - Context Window: Not exposed by host
  - Outcome: Changes requested before implementation. The opt-in collection,
    shared size formatter and copy-before-atomic-save approach fit the existing
    code, but mixed row heights, provider cancellation and file-link semantics
    need explicit decisions. Correct the disabled-cost claim as well. This review
    appends findings only; the proposed design and earlier records are unchanged.

  #### Findings

  1. **P1: Missing metadata can clip another result's description.** The plan
    permits empty descriptions while excluding Quicksearch changes, but
    [Quicksearch](../src/main/python/fman/impl/quicksearch.py) enables
    `setUniformItemSizes(True)` and sizes the dialog from the first row. A
    read-only Qt probe using the current theme and `[metadata, missing]` rows
    measured required heights of 32/18 pixels but allocated 18/18; reversing the
    rows allocated 32/32. Resolve how enabled results reserve a consistent second
    line, or explicitly approve a narrowly scoped host change. Add real Qt tests
    in the existing
    [SearchFileSyntaxIT](../src/integrationtest/python/fman_integrationtest/test_qt.py)
    for both row orders, query-driven reorder/filtering, all-missing results,
    title highlights and acceptance at 100%/150% scaling. Checking description
    strings or doing only a manual happy-path check cannot catch this defect.

  2. **P2: Non-local metadata queries are neither guaranteed cached nor
    cancelable.**
    [MotherFileSystem.query](../src/main/python/fman/impl/plugins/mother_fs.py)
    directly invokes the provider method. The local provider's cached `stat`
    does not establish a contract for other schemes; the local walk bypasses
    this branch anyway. A probe confirmed that two size queries after `is_dir`
    invoke the provider twice. The current
    [indexer](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/indexer.py)
    has no cancellation checks, and
    [_search](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/__init__.py)
    opens the picker after indexing without checking whether the originating
    pane navigated away. `max_entries` bounds count, not time. Specify cancellation
    between metadata calls and stale-result rejection, including the limitation
    that an in-flight synchronous provider call cannot be interrupted, or narrow
    supported metadata providers. Add an event-controlled slow-provider test,
    navigation/disposal coverage, and a disabled-path assertion of zero metadata
    queries. Do not describe arbitrary providers as cheap cache hits.

  3. **P2: File-symlink metadata will disagree with the pane.** The existing
    indexer excludes directory links but retains file symlinks. The proposed
    `child.stat(follow_symlinks=False)` describes the link itself, whereas
    [LocalFileSystem.stat](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py)
    follows links and falls back to the link only for `FileNotFoundError`.
    Consequently the same displayed result can have a different size/date from
    the pane. Choose matching target/fallback semantics or explicitly document
    link metadata as a deviation. Cover file links, broken targets and denied
    targets; account for any extra reparse-point I/O rather than calling it free.
    Preserve existing hidden-attribute and directory-link filtering.

  4. **P3: The disabled path cannot have literally unchanged memory cost.** Two
    trailing namedtuple fields consume two slots even when both values are
    `None`. On the current 64-bit interpreter the proposed record is 16 bytes
    larger, or 800,000 additional bytes at 50,000 entries, before enabled integer
    values. Revise Compatibility, Runtime Effects and Acceptance Criteria to
    distinguish unchanged results/ranking and zero extra metadata I/O from this
    fixed allocation overhead. Record enabled and disabled memory as well as
    index time; separate indexing measurements from per-keystroke formatting.

  #### Review Validation

  - Read-only `python -c` probes against the existing Quicksearch/theme,
    `MotherFileSystem` and namedtuple implementation confirmed the row-height,
    query-forwarding and allocation findings above. Offscreen Qt emitted its
    usual `propagateSizeHints` warning; the geometry assertions completed.
  - Verified formatter defaults and atomic-save ordering directly in
    [status_bar.py](../src/main/python/fman/impl/status_bar.py) and
    [config.py](../src/main/python/fman/impl/plugins/config.py). No defect found
    in those two proposed dependencies.
  - Documentation gate: `git diff --check -- Plan/FindFiles002.md`, local-link
    validation and editor diagnostics. No implementation, package installation,
    full test suite, build or packaged/visual smoke was performed. The proposed
    feature's behavior and performance remain unverified until implemented.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Approved the user-authorized resolutions for implementation: reserve
  the second line using an ASCII-space description, keep zero-byte size as `0 B`,
  follow file-link target/fallback semantics, use cancellable metadata indexing
  with scoped pane lifecycle subscriptions, and document record-slot overhead.
  A real Qt probe passed mixed/all-missing row reservation without host changes.
  Add Qt geometry/acceptance tests at 100%/150%, a slow-provider cancellation
  regression, real settings persistence and ZIP metadata checks, and 50,000-entry
  time/memory measurements. Full suite and freeze/package remain unauthorized.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Accepted the implementation review's three nonblocking notes as useful
  follow-ups. Keep conservative same-location load invalidation and document the
  retry; add explicit cancellation feedback after status cleanup; distinguish
  settings conflicts from write failures. Source inspection confirmed that stale
  results, like cancellation, were previously silent. No host API changes needed.

## Implementer

### 2026_09_18 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented opt-in metadata collection, persisted Command Center
  toggle, per-command overrides and equal two-line results. Zero bytes remains
  `0 B`; unavailable attributes are independent. Added same-semantics file-link
  handling, cancelable indexing and scoped stale-result checks. No host or public
  API files changed. Focused unit, real Config/ZIP, registry and native Qt checks
  passed; benchmark results and unrun manual gates are recorded below.

### 2026_09_18 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation matches the approved design; no blocking defects.
  Re-ran the focused gate offscreen: `fman_unittest.test_search_file_fuzzy` plus
  `SearchFileMetadataIT` and `SearchFileSyntaxIT`, 75 tests OK, the 5 documented
  opt-in/privilege skips. Verified: `SearchEntry` defaulted fields; disabled
  path unchanged (no stat, task, subscriptions or formatting); metadata-enabled
  path subscribes `on_path_changed`/`on_closed` before reading the root, checks
  cancellation per directory, entry and provider call, and rejects stale results
  before opening the picker and before navigating; `describe_metadata` renders
  `%Y-%m-%d %H:%M` and `format_size`, `0 B` preserved, `or ' '` reserves the
  second line; file links follow target with `FileNotFoundError` fallback;
  independent provider attributes; toggle copies the loaded dict and catches
  `OSError`/`ValueError`; `src/main/python/fman` unchanged versus HEAD
  (`on_path_changed` predates this task and is documented in PlugIn.md);
  README, CHANGELOG, `SearchFileFuzzy.json` and the Plan/Done move are done.
  Notes, not fixes: (1) `on_path_changed` fires on `location_loaded`, so a
  search started while the pane is still loading its location is silently
  discarded - acceptable edge, worth a README sentence if reported; (2) when
  the user cancels the progress dialog, `submit_task` swallows `Task.Canceled`
  and `_search` exits without any message, unlike the stale path; (3) the
  `ValueError` branch in the toggle reports differential-save conflicts, good,
  but the message says "Could not save" for both I/O and merge errors.

### 2026_09_18 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Addressed all three review notes. Added non-stale cancellation status
  after cleanup, separate merge/write failure messages and unchanged-settings
  assertions, and a README retry note with same-location signal coverage. Stale
  navigation/closure stays silent and safe; disabled indexing and public APIs are
  unchanged. The focused 75-test gate passed at both native Qt scale factors.

## Validation Results

Use `PYTHONPATH` from Tests above; no new environment or package was installed.

- First substantive code gate: `python -m unittest fman_unittest.test_search_file_fuzzy`
  passed 51 tests, four expected skips, immediately after extending `SearchEntry`.
- `python -m unittest fman_unittest.test_search_file_fuzzy.MetadataIndexTest fman_unittest.test_search_file_fuzzy.BuildIndexTest`
  passed the initial 20 indexing checks, with the native symlink-privilege skip.
- Formatting, toggle, command and settings checks passed after their code edits.
  Real Config restart preserved the toggle and unrelated settings; actual ZIP
  metadata returned `0 B` and the fixture's fixed timestamp.
- Real `ExternalPlugin`/`ApplicationCommandRegistry` smoke initially exposed the
  missing application-command `is_visible` method. Added it and a regression;
  rerunning the same smoke confirmed registration, aliases, visibility, unchanged
  pane commands and clean unload without reported errors.
- Final command:
  `python -m unittest fman_unittest.test_search_file_fuzzy fman_integrationtest.test_qt.SearchFileMetadataIT fman_integrationtest.test_qt.SearchFileSyntaxIT`
  passed 75 tests at `QT_QPA_PLATFORM=windows`, `QT_SCALE_FACTOR=1` and `1.5`,
  with `QT_ENABLE_HIGHDPI_SCALING=1` and auto screen scaling disabled. Five expected
  skips: native symlink creation privilege, opt-in fzf reference, two older search
  benchmarks and the opt-in metadata benchmark. Deterministic file-link mocks
  passed despite the native privilege restriction. Offscreen metadata integration
  also passed; its only warnings were `propagateSizeHints` support notices.
- `SEARCH_METADATA_PERFORMANCE_TESTS=1` with
  `python -m unittest fman_unittest.test_search_file_fuzzy.SearchMetadataPerformanceTest`
  passed on 50,000 empty files in 100 temporary folders. Five paired runs:
  indexing median 90.16 ms off / 123.09 ms on; retained allocation 16.21 / 18.11 MiB;
  peak 16.22 / 18.12 MiB. The enabled path included Task cancellation checks,
  not progress-dialog construction. Formatting 100 descriptions: median 0.166 ms.
  Disabled record-slot increase: 800,000 bytes, measured independently. Fixture
  creation/deletion and tracemalloc runs are excluded from indexing timings.
- Editor diagnostics, `git diff --check`, the moved task's whitespace check,
  required-section checks and local-link checks passed. Parsed JSON confirmed
  `show_metadata` is boolean false. The canonical move preserved the document's
  SHA256 hash and left no copy under `Plan/`.
- Not run: full test suite, freeze/package, frozen smoke, live network-share
  checks (no test share supplied), or human visual/locale-matrix checks. Qt tests
  exercised actual widgets and geometry at both scales. A synchronous blocked
  provider cannot be interrupted until it returns; cancellation and stale-result
  tests verified rejection immediately after release. No public API was changed.

### Review Follow-Up - 2026_09_18

- `python -m unittest fman_unittest.test_search_file_fuzzy.MetadataCommandTest fman_integrationtest.test_qt.SearchFileMetadataIT.test_blocked_provider_cancel_navigation_and_disposal_reject_results`
  passed seven tests immediately after the cancellation edit. Tests assert the
  message survives `clear_status_message`, both direct and swallowed cancellation
  are handled, and stale results do not report user cancellation.
- `python -m unittest fman_unittest.test_search_file_fuzzy.ToggleMetadataTest`
  passed four tests after splitting `ValueError` and `OSError` feedback. Both
  error cases preserve the cached preference and unrelated settings.
- `python -m unittest fman_integrationtest.test_qt.SearchFileMetadataIT.test_blocked_provider_cancel_navigation_and_disposal_reject_results`
  passed after adding the same-folder load-completion signal case. Real progress
  cancellation, navigation away/back and widget destruction also passed. These
  narrow offscreen runs emitted nonfatal `QFontDatabase` font-directory warnings.
- `python -m unittest fman_unittest.test_search_file_fuzzy fman_integrationtest.test_qt.SearchFileMetadataIT fman_integrationtest.test_qt.SearchFileSyntaxIT`
  passed 75 tests at native Windows Qt scale factors `1` and `1.5`, with the same
  five expected skips documented above. Editor diagnostics were clear. No full
  suite, benchmark rerun, freeze/package or network-share test was needed or run;
  the earlier measured costs and unverified scenarios are unchanged.
