# Find Files 002: Result Metadata

Status: Design; not approved for implementation.

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
  when both are missing the description stays empty.
- Metadata collected during the existing index walk for `file://` locations
  and, best effort, for other schemes through the public filesystem API.
- README and CHANGELOG updates; tests.

Excluded:

- New columns, sorting or filtering by date or size (query filters such as
  `size:` and `dm:` are [Find Files 003](FindFiles003.md)).
- Creation time, attributes, owner, or details for hint rows.
- Any change to `show_quicksearch`, `QuicksearchItem`, the Quicksearch widget,
  other pickers, or the public `fman` API.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. With
`show_metadata` false, index contents, ranking and cost are unchanged.

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
[Find Files 003](FindFiles003.md) later adds `created_ns` the same way; both
tasks share this record and the collection point below.

`build_index(..., collect_metadata=False)` in
[indexer.py](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/indexer.py):

- Local walk: when enabled, call `child.stat(follow_symlinks=False)` once per
  regular file and store `st_size` and `st_mtime_ns`. On Windows `DirEntry`
  already holds this data from the directory listing, so no extra system call
  is made for non-reparse entries. Reuse the same `stat` result for the
  hidden-attribute check instead of calling it twice. `OSError` leaves both
  fields `None`; the entry is still indexed.
- Other schemes: when enabled, after the existing `is_dir(url)` call, read
  `fman.fs.query(url, 'size_bytes')` and `query(url, 'modified_datetime')`.
  `is_dir` already populated the provider's stat cache, so these are cache
  hits for the local provider and cheap for `zip://`. Convert the datetime to
  nanoseconds. `OSError`, `NotImplementedError` and `AttributeError` yield
  `None`. Cancellation and `max_entries` behavior are unchanged.
- When disabled nothing is read; the walk is byte-for-byte today's.

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

`get_items` passes `description=describe_metadata(entry)` only when metadata is
enabled; formatting happens per yielded row, so at most `max_results` (100)
strings are built per keystroke on the Qt thread. Hint rows from Find Files
001 keep their own description and are never decorated.

### Settings And Command

`_get_settings` validates `show_metadata` as a boolean (default `false`) and
applies the `metadata` argument when given, like `mode`. `_search` passes
`collect_metadata=settings['show_metadata']` to `build_index`.

`ToggleSearchResultMetadata(ApplicationCommand)`:

1. `current = _get_settings()['show_metadata']`.
2. `values = dict(load_json('SearchFileFuzzy.json', default={}))`; set
   `values['show_metadata'] = not current`; `save_json('SearchFileFuzzy.json',
   values)`. The loaded dict is copied, never mutated in place, and unrelated
   keys survive. A save `OSError` is reported with `show_status_message` and
   the state is left unchanged.
3. `show_status_message('Search result metadata: On', timeout_secs=3)` or
   `... Off`.

The toggle affects the next search. The Quicksearch dialog is modal, so the
command cannot run while results are open.

## Alternatives

- **Put the metadata in `hint`** (right-aligned on the title line): the title
  is a relative path that is often long and would collide with or elide the
  hint. The description line keeps the path readable. Rejected.
- **Always collect metadata, toggle display only**: on Windows the local
  cost is nil, but non-local schemes would pay two queries per entry for
  nothing, and the repository requires disabled features to do no
  feature-specific work. Rejected; collection follows the setting.
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
- Disabled (default): identical index walk, matcher input and per-keystroke
  cost; `describe_metadata` is never called.
- Enabled, `file://`: one `DirEntry.stat()` per regular file during indexing,
  served from the listing on Windows; memory grows by two small ints per
  entry (about 50,000 x 2 fields at the default cap). Per keystroke: at most
  `max_results` string formats on the Qt thread, microseconds each.
- Enabled, other schemes: two cached provider queries per entry, on the
  command worker, bounded by `max_entries`.
- The description makes each row taller, so the dialog shows roughly half as
  many rows; no dialog geometry code changes.
- Toggle: one JSON read and one atomic JSON write on the command worker.
- Cancellation: unchanged; nothing outlives the invocation.

## Tests

Focused commands:

```powershell
$env:PYTHONPATH="src/main/python;src/unittest/python;src/integrationtest/python;src/main/resources/base/Plugins/Core;src/main/resources/base/Plugins/SearchFileFuzzy"
$env:PYTHONUTF8="1"
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest fman_unittest.test_search_file_fuzzy
```

Extend `fman_unittest.test_search_file_fuzzy`:

- `BuildIndexTest`: with `collect_metadata=True` local entries carry the
  fixture file's exact `st_size` and `st_mtime_ns`; with the default they are
  `None`; a file that disappears between listing and `stat` is indexed with
  `None` fields; hidden-attribute filtering still works with a single `stat`
  per entry (patched `DirEntry.stat` call count). Non-local path: patched
  `fman.fs.query` returning values, raising `OSError` and raising
  `NotImplementedError`.
- `DescribeMetadataTest`: both values, size only, date only, neither (empty
  string); `format_size` divisor 1000 and 1024; the date renders as
  `YYYY-MM-DD HH:MM` regardless of the process locale (patched
  `locale.setlocale`); an out-of-range timestamp yields the size only;
  existing three-field `SearchEntry` construction still works.
- `SettingsTest`: `show_metadata` default `false`; non-boolean values fall
  back; `metadata=True|False` argument overrides the setting.
- `SearchCommandTest`: with metadata on, yielded items have the expected
  description and `build_index` receives `collect_metadata=True`; with
  metadata off, descriptions are empty and `collect_metadata=False`; hint
  rows keep their own description.
- `ToggleTest`: flips `false -> true -> false`, `save_json` receives a copy
  containing unrelated keys unchanged, the correct status message is shown,
  and a save `OSError` leaves the setting untouched and reports it.
- Performance: build a 50,000-file synthetic tree with and without
  `collect_metadata`; record both times in the validation results. No hard
  bound is claimed before measurement.
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

- Default behavior, index contents, ranking and per-keystroke cost are
  unchanged when `show_metadata` is false.
- `Toggle search result metadata` in the Command Center flips the setting,
  persists it under `UserSettings`, preserves unrelated keys and reports
  `Search result metadata: On|Off`.
- With metadata on, every local result shows `<modified>, <size>` on its
  description line: the date as `YYYY-MM-DD HH:MM` local time in every
  locale, the size formatted like the pane's `Size` column; unavailable
  values are omitted rather than shown as placeholders.
- `zip://` results show metadata when the provider supplies them; providers
  without metadata produce entries without a description and no error.
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
