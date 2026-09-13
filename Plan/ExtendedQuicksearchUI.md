# Extended Quicksearch UI

## Task

Add a backward-compatible extended Quicksearch API that supports simple,
declarative controls. Keep the current Quicksearch variant unchanged for all
existing callers.

Use the extended variant in `SearchFileFuzzy` to display:

- A `Mode` drop-down with `Fuzzy` and `Regular` choices.
- A `Case sensitive` checkbox.

Unicode awareness stays a JSON-only setting (`unicode_aware`); it is a
developer knob, not a per-search choice, and keeping it out of the dialog
halves the variant cache and the test matrix.

Changing a control refreshes the current results without rebuilding the file
index. Search settings are saved in `SearchFileFuzzy.json` and restored the
next time the dialog opens. Defaults are fuzzy, case-insensitive, and
Unicode-aware matching.

## Scope

This task adds declarative checkbox and choice controls to Quicksearch and uses
them for SearchFileFuzzy mode and case sensitivity. It preserves all existing
Quicksearch callback arguments, return values, geometry, and plug-in callers.
Unicode awareness remains JSON-only; arbitrary caller-owned Qt widgets and a
general form-building API are explicitly excluded.

## Design

Extend the existing Quicksearch implementation through immutable public
descriptors and one shared controls-aware dialog path. The public legacy API is
a compatibility wrapper over the extended result. Control values are copied
into read-only mappings, callbacks remain on the Qt thread, and filesystem
indexing remains outside the dialog.

## Public API

Preserve the current API and result contract:

```python
show_quicksearch(
    get_items, get_tab_completion = None, query = '', item = 0,
)
```

It continues to call `get_items(query)` and return `(query, value)` or `None`.
Existing plug-ins require no source changes.

Add a second API:

```python
show_quicksearch_extended(
    get_items, controls=(), get_tab_completion=None, query='', item=0,
    on_controls_changed=None
)
```

The extended callback receives the query and current control values:

```python
def get_items(query, values):
    mode = values['mode']
    case_sensitive = values['case_sensitive']
```

`values` is a read-only mapping (`types.MappingProxyType`) from descriptor
name to the current *value* (the choice value, not its label; `bool` for
checkboxes).

`on_controls_changed(values)` is the persistence hook. It is called on the Qt
thread whenever a control changes, *before* the result refresh, and is
independent of `get_items` so that query callbacks stay side-effect free.
`SearchFileFuzzy` uses it to call `save_json`. Exceptions raised by either
callback are reported through the normal plug-in error handler and do not
close the dialog.

Return `QuicksearchResult(query, value, controls)` when accepted and `None`
when cancelled. `QuicksearchResult` is a `NamedTuple`, so both attribute
access and unpacking work; `controls` is the same read-only mapping type as
`values`. The legacy `show_quicksearch` wrapper returns `result[:2]`.

Controls are public immutable data descriptors (frozen dataclasses or
`NamedTuple`s), not caller-created Qt widgets. `checked` and `value` are the
*initial* values only:

```python
QuicksearchCheckbox(
    name='case_sensitive', label='&Case sensitive', checked=False
)

QuicksearchChoice(
    name='mode', label='&Mode',
    choices=(('fuzzy', 'Fuzzy'), ('regular', 'Regular')),
    value='fuzzy'
)
```

Labels may contain a `&` mnemonic; Qt turns it into `Alt+<letter>`, which
gives every control a deterministic keyboard path regardless of Tab handling.

Initially support both `QuicksearchCheckbox` and `QuicksearchChoice`, because
`SearchFileFuzzy` has immediate uses for both. Future controls can implement the
same descriptor protocol without changing the dialog contract.

Validate descriptors before opening the dialog:

- Names are unique, non-empty `str` identifiers (they become JSON keys).
- A choice has at least one entry, choice values are unique, and the initial
  value exists.
- Labels and values contain plain serializable data.
- Unsupported descriptors raise `TypeError` before creating Qt widgets.

Do not allow plug-ins to supply arbitrary `QWidget` objects. Declarative
controls preserve Qt thread ownership, consistent styling, keyboard behavior,
accessibility, and API stability.

## Shared Implementation

There must be one Quicksearch implementation. Do not create separate regular
and extended dialog classes or duplicate the query field, result model,
filtering, sizing, keyboard handling, or acceptance logic.

Refactor the existing `Quicksearch` constructor to accept an optional sequence
of validated descriptors. When controls exist, it creates a reusable
`QuicksearchControls` child responsible for:

- Mapping descriptors to native Qt widgets.
- Holding the current values.
- Emitting one `values_changed` signal.
- Returning an immutable final values mapping.

When the sequence is empty, no controls container is created and the current
dialog geometry remains unchanged. There is a single constructor path;
`controls=()` must produce a layout identical to today's dialog.

Both public functions delegate to one internal implementation in `MainWindow`:

```python
def _show_quicksearch(
    self, get_items, get_tab_completion, query, item, controls
):
    ...
```

`show_quicksearch` passes no controls and converts the shared result back to the
legacy tuple. `show_quicksearch_extended` returns the complete result. This
keeps layout, styling, threading, and behavior synchronized between variants.

## UI Behavior

Place controls in one compact horizontal row between the query field and the
result list. Use native `QCheckBox` and `QComboBox` widgets with visible labels,
accessible names, and standard focus indicators. The row gets the object name
`controls-container` so themes can style it like `query-container` and
`items-container`.

Keep initial focus in the query field. Existing result navigation (`Up`,
`Down`, `PageUp`, `PageDown`), `Enter`, `Escape`, and the quit shortcut remain
unchanged while the query field has focus.

Tab handling is caller dependent and must be documented as such: the query
field consumes `Tab` only when `get_tab_completion` returns a completion (as
today, e.g. `GoTo`); otherwise `Tab`/`Shift+Tab` follow Qt focus traversal
and reach the controls (the result list has `NoFocus`). Mnemonics (`Alt+C`,
`Alt+M`) are the deterministic way to reach a control in every dialog.

While a control has focus, `Enter` accepts the current result item and
`Escape` cancels, exactly as from the query field. Implement this in
`Quicksearch.keyPressEvent` (or an event filter on the controls row) because
`returnPressed` and the key filter currently live on the `LineEdit` only.
`Space` toggles a checkbox and `Up`/`Down` change a combo box natively.

A query or control change goes through one refresh path. Add a 0 ms
single-shot `QTimer` in front of `_update_items` so a query edit and a control
change in the same event-loop turn produce exactly one refresh; today
`textChanged` calls `_update_items` synchronously. A control change resets
the cursor to item 0, like `_on_text_changed` does. Do not recreate the dialog
or replace its list model.

Control callbacks run on the Qt thread. Filesystem indexing stays outside the
dialog. Building a new normalized variant for 50k entries costs about 0.2 s
on the Qt thread on the first toggle; either accept this (state it in the
README) or precompute the other variants in a background thread right after
the dialog opens, since they do not depend on the query.

## Alternatives

- A second extended dialog class was rejected because it would duplicate and
  eventually diverge from legacy Quicksearch behavior.
- Caller-supplied `QWidget` controls were rejected because they expose thread
  ownership, styling, accessibility, and lifetime hazards as public API.
- Replacing `show_quicksearch` was rejected because it would break existing
  plug-ins. A second API with a shared internal implementation preserves
  compatibility.
- Putting Unicode awareness in the dialog was rejected for the first version
  because it is a developer setting and would double cache variants and tests.

## Runtime Effects

- Legacy Quicksearch calls create no controls container and retain their
  current runtime behavior.
- Extended dialogs add only a compact row of native Qt controls and a 0 ms
  coalescing timer while open.
- Control changes never traverse the filesystem again; they reuse the command's
  existing index.
- Normalized matcher variants are cached for the dialog lifetime. At most two
  variants are reachable from the UI while Unicode awareness is fixed.
- The first switch to an uncached normalization variant may cost about 0.2 s
  for 50,000 entries; background precomputation is the fallback if profiling
  shows unacceptable UI latency.

## `SearchFileFuzzy` Settings

Extend `SearchFileFuzzy.json`:

```json
{
  "mode": "fuzzy",
  "case_sensitive": false,
  "unicode_aware": true,
  "max_recursive_entries": 50000,
  "max_results": 100,
  "include_hidden": true
}
```

Semantics:

- With `case_sensitive: false`, use Unicode `casefold()` when Unicode awareness
  is enabled and `lower()` otherwise.
- With `case_sensitive: true`, preserve case during comparison.
- With `unicode_aware: true`, apply NFKC normalization, retain Unicode letters
  and digits, and split camel case using Unicode character properties
  (`(?<=[^\W\d_])(?=[A-Z])`, i.e. any letter followed by an upper-case
  letter).
- With `unicode_aware: false`, skip NFKC normalization and casefolding, but
  never delete non-ASCII characters. Separators are still `[\W_]+` (already
  Unicode-safe); camel case is split with the ASCII rule
  `(?<=[a-z0-9])(?=[A-Z])`. Matching remains literal at the code-point level.

Case sensitivity and Unicode awareness are independent. Test all four
combinations. Disabling Unicode awareness must never restore the earlier bug
that removed accented or non-Latin names.

The mode drop-down and the checkbox supply the matcher options; `unicode_aware`
comes from the JSON file. Build the filesystem index once per command
invocation. Changing controls creates or reuses a matcher over that same index
and never scans the filesystem again. Cache normalized candidate forms lazily
by `(case_sensitive, unicode_aware)` for the dialog lifetime; at most four
variants can exist, and with `unicode_aware` fixed per invocation only two are
reachable from the UI.

Persist changed controls immediately from `on_controls_changed` with
`save_json`, including changes made before cancelling the dialog. `save_json`
without a `value` writes the object cached by `load_json`, whereas
`_get_settings` returns a merged *copy*; therefore either mutate the cached
dict or pass `value=` explicitly. `Config.save_json` writes a differential
against the bundled plug-in JSON, so only changed keys appear in
`UserSettings/Plugins/User/Settings/SearchFileFuzzy.json`. Existing command
arguments such as `mode='regular'` provide the initial value for that
invocation but do not alter the saved default unless the user changes a
control.

## Implementation Steps

1. Add immutable `QuicksearchCheckbox`, `QuicksearchChoice`, and
   `QuicksearchResult` types to the public `fman` API and list them in
   `test_portable.py` next to `show_quicksearch`.
2. Refactor Quicksearch and `MainWindow` around one controls-aware private
   implementation while preserving the legacy wrapper and return type.
3. Add descriptor validation and the optional `QuicksearchControls` row with
   the `controls-container` object name; add `.quicksearch-controls`,
   `Quicksearch QCheckBox`, and `Quicksearch QComboBox` selectors to
   `theme.py` and defaults to Core's `Theme.css` and `Theme (Windows).css`.
4. Route query and control changes through one 0 ms-coalesced refresh path;
   handle `Enter`/`Escape` from focused controls.
5. Extend `SearchFileFuzzy` configuration and matcher behavior with
   `case_sensitive` and the JSON-only `unicode_aware`.
6. Add the mode choice and the case checkbox without rebuilding the filesystem
   index; persist via `on_controls_changed`.
7. Update `test_search_file_fuzzy.py` to patch `show_quicksearch_extended` and
   call `get_items(query, values)`.
8. Update API documentation and the plug-in README, and add a changelog entry.

## Tests

Required final command from the repository root:

```powershell
python build.py test
```

Public API tests:

- Existing Quicksearch callers receive the same callback arguments and return
  values as before.
- Regular Quicksearch has no controls row and retains its current geometry.
- Extended results contain an immutable controls mapping and support both
  attribute access and unpacking.
- Invalid, duplicate, empty-choice, and unsupported descriptors fail before
  dialog creation.
- `on_controls_changed` is called before the refresh with the new values; an
  exception in it does not close the dialog.

Qt integration tests:

- Checkbox and choice initial values render correctly.
- Mouse, keyboard, and mnemonic (`Alt+C`) changes refresh results exactly
  once; a query edit and a control change in the same event-loop turn refresh
  once and reset the cursor to item 0.
- `Tab` reaches the controls when no completion is available and completes
  the query when `get_tab_completion` returns a value.
- `Enter` and `Escape` work from a focused control.
- Accept and cancel return the documented result types.
- The controls row is styled by the theme selectors (no native-looking
  widgets on the dark panel).

SearchFileFuzzy tests:

- Fuzzy and regular selection changes results without rebuilding the index.
- Case-sensitive matching distinguishes `Report.txt` from `report.txt`.
- Case-insensitive Unicode matching handles French and Spanish names.
- Unicode-aware matching handles NFKC-equivalent forms.
- Unicode-disabled matching is literal but preserves non-ASCII text.
- All four case/Unicode combinations produce deterministic rankings.
- Changed controls persist (only changed keys in the user JSON) and are
  restored on the next invocation; `mode='regular'` as a command argument does
  not change the saved default.

## Acceptance Criteria

- Existing Quicksearch plug-ins remain source- and behavior-compatible.
- Regular and extended Quicksearch share all dialog and model logic; the
  `Quicksearch` class has a single constructor path and `controls=()` yields
  today's layout.
- Extended Quicksearch supports native checkboxes and drop-down choices through
  declarative public descriptors, each reachable by mnemonic.
- SearchFileFuzzy exposes mode and case sensitivity in the dialog and persists
  them; Unicode awareness remains a JSON setting.
- Matching controls never trigger another filesystem traversal.
- Accessibility, keyboard navigation (including `Enter`/`Escape` from a
  control), threading, and existing Quicksearch behavior remain intact.

## Reviewers

### 2026_09_12 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context window: Not exposed by host
- Outcome: Initial backward-compatible API and SearchFileFuzzy integration
  design created.
