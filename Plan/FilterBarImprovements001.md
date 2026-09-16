# Filter Bar Improvements 001

## Task

Extend the pattern language of the pane filter (the box that opens at the
bottom-right of a file pane when the user starts typing) while keeping its
per-keystroke cost bounded and comparable to today: a small number of
fixed-length compiled regular expressions tested against each row's
basename, with no possibility of catastrophic backtracking. While a filter is
active, report how many rows match in the status bar, because the small
filter box gives no feedback about what was hidden.

Today the filter is a case-insensitive substring match where `*` is the only
wildcard ([widgets.py](../src/main/python/fman/impl/widgets.py#L306-L310)):

```python
text_re = '.*'.join(map(re.escape, text.split('*')))
self._filter_re = re.compile(text_re, re.I)
```

Consequences users hit: `?` and `[...]` are literals, `*.py` also shows
`foo.pyc`, there is no "starts with" or "ends with", there is no way to hide
rows that match, and nothing tells the user how many rows the filter kept.

## Scope

Included. Items 1-4 are implemented purely as changes to how `text` is
compiled into a matcher; item 5 adds one status-bar message while a filter is
active; item 6 is optional and gated on explicit confirmation:

1. **Glob characters**: `?` matches one character; `[abc]`, `[a-z]`, `[!x]`
   match one character from a set. `*` keeps its meaning. Matching remains a
   *substring* search, so `rep` still matches `Annual Report.pdf`; this is
   unchanged from today and differs from `fnmatch`'s whole-name rule.
2. **Anchors**: a leading `^` anchors to the start of the name, a trailing
   `$` to the end. `^rep` = starts with, `.py$` = ends with, `^a*z$` = whole
   name. `^` and `$` are legal filename characters; only the leading/trailing
   position is special, and they match literally elsewhere. A text consisting
   only of anchors (`^`, `$`, `^$`) is matched literally.
3. **Negation**: a leading `!` inverts the filter; `!tmp` hides rows whose
   name contains `tmp`. Only the leading `!` is special. `!` alone is a
   literal `!`.
4. **Escape**: `\` makes the next character literal: `\$`, `\^`, `\!`,
   `\*`, `\?`, `\[`. `\` cannot appear in a Windows filename, so it is
   free for this role and never collides. A trailing lone `\` is ignored.
   `[$]` is an equivalent spelling via the bracket class.
5. **Match count in the status bar**: while a filter is active (non-empty
   text) in the active pane, the main status bar text reads
   `Filter "<text>": <matched> of <total> items`; it is refreshed on every
   keystroke and whenever the pane's file set changes under an active filter.
   On the single active-to-inactive transition (text becomes empty by
   `Backspace`, `Escape` or location change) the status bar is reset with the
   existing `clear_status_message()` (`Ready.`). Uses the existing
   `show_status_message` path, so it behaves exactly like a plug-in status
   message: it replaces whatever was shown and is itself replaced by any
   later message.
6. **Multiple terms (AND)** — **optional; to be confirmed explicitly by the
   user before implementation.** `rep 2024` would require every
   space-separated term to match, in any order. This item is the only one
   that changes behavior beyond regex compilation and the status message:
   `Space` is bound to `toggle_selection` and never reaches the filter today,
   so it would need routing to the bar while the bar is visible, the same way
   `Backspace` is special-cased in `_on_key_pressed`. If declined, `rep*2024`
   remains the ordered-AND spelling and this section is removed.

Excluded:

- Regular expressions, fuzzy matching, smart case, date/size filters,
  persisting the filter across navigation, folder-only/file-only
  visibility rules. Regex and metadata belong to
  [ExtendedQuicksearchUI](ExtendedQuicksearchUI.md).
- Showing the match count inside the extended per-pane status widget
  (`PaneStatusWidget`); that widget is optional (default disabled) and its
  counts are recomputed off-thread with debouncing, which is unnecessary for
  two integers already known on the Qt thread.
- Any change to which rows the filter applies to (files and folders, current
  pane, basename only), to cursor placement (`_select_row_with_prefix` keeps
  its case-insensitive prefix rule), to how the bar opens/closes, or to key
  routing — except item 6 if confirmed. The filter input gains
  `setMaxLength(255)` (Windows' component limit; today it is Qt's 32767
  default), which bounds pattern length without affecting any real query.
- Any change to `fman`, `fman.ui`, plug-in APIs, settings or key bindings.
  One additive private signal, `Model.files_changed`, is added to
  `fman.impl.model.model.Model` (see Design).

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5.
`FilterBar` is private host code with no plug-in callers. Every filter string
that contains none of `? [ ^ $ ! \` produces the same accepted row set as
today, so existing habits are unaffected. The new special characters were
previously matched literally; names containing them (`$RECYCLE.BIN`,
`[draft] notes.txt`, `!important`) are still reachable: `^`/`$`/`!` are
literal away from their special position, and `\` escapes any of them
anywhere. The status-bar message shares the text slot plug-ins use via
`show_status_message`; a plug-in message shown while a filter is active
overwrites the count until the next keystroke or file-set change, and
deactivating the filter resets the slot to `Ready.` as `clear_status_message`
already does.

## Design

### Ownership

- New pure function `compile_filter(text) -> FilterMatcher` in a new Qt-free
  module `fman/impl/filter_pattern.py`. `FilterMatcher` is a small frozen
  object with `matches(name) -> bool`; it has no Qt imports so it can be
  unit-tested directly.
- `FilterBar._on_text_changed` calls `compile_filter` and stores the matcher;
  `FilterBar._accepts` becomes `self._matcher.matches(basename(url))`.
- `FilterBar` tracks one boolean `_active` (text non-empty). It gains two
  signals: `filter_changed = pyqtSignal(str, int, int)` (text, matched,
  total), emitted after every `_on_text_changed` that leaves the filter
  active and after every file-set change while active; and
  `filter_cleared = pyqtSignal()`, emitted exactly once on the
  active-to-inactive transition. `close()` only sets the text to `''`; the
  transition logic lives solely in `_on_text_changed`, so `close()` on an
  already inactive bar emits nothing.
- `DirectoryPaneWidget` re-exposes both signals unchanged.
- `MainWindow.add_pane` connects them to two private slots. The slots act only
  when the emitting pane `is self._active_pane`; `_set_active_pane` republishes
  the new active pane's count if its filter is active, and clears the slot if
  the previous active pane's filter was active and the new one's is not.
  `MainWindow` is the widget that owns `show_status_message`; the
  `DirectoryPaneWidget.window` property resolves to the central `QWidget`
  (pane, splitter, central widget, main window) and is not used.
- `Model` gains `files_changed = pyqtSignal()`, emitted at the end of
  `_record_files_main` and `_on_files_reloaded`, the two places that replace
  or mutate `self._files`. Both already run on the Qt thread. Nothing else in
  the model changes.

### Match count

`SortFilterTableModel.update()` is synchronous on the Qt thread and rebuilds
the filtered row list ([sorted_table.py](../src/main/python/fman/impl/model/sorted_table.py#L25-L29)).
Immediately after it returns, `self._model.rowCount()` is the matched count
and `len(self._model.sourceModel().get_rows())` is the unfiltered total
(`get_rows` returns the `dict_values` of the loaded files). Both are O(1);
no second pass over the rows is made.

The unfiltered total can change without any proxy `modelReset`,
`rowsInserted` or `rowsRemoved`: a nonmatching file added or removed by the
file watcher, `F5` or a transfer changes `_files` but not the displayed rows,
and `transaction_ended` fires only when the displayed diff changed
([table.py](../src/main/python/fman/impl/model/table.py#L113-L118)). The
plan therefore observes `Model.files_changed` (above). `FilterBar` connects
it to a slot that re-emits `filter_changed` only while `_active`; when
inactive the slot returns after one boolean check.

Ownership between panes: both panes may hold an active filter, but only the
active pane's events reach the status bar. The status text therefore always
describes the pane that has keyboard focus.

The message is shown without a timeout so it stays until the filter is
deactivated. No new label, widget or timer is added to the status bar.

### Compilation

```
text := ['!'] ['^'] body ['$']
body := segment ('*' segment)*
```

1. Strip a leading unescaped `!` → `negate = True`.
2. Strip a leading unescaped `^` → `anchored_start`; strip a trailing
   unescaped `$` → `anchored_end`. If the remaining `body` is empty, undo
   steps 1-2 and treat the whole text as literal characters.
3. Split `body` on unescaped `*` into segments. Translate each segment
   character by character into a **fixed-length** regex: `\` followed by any
   character → `re.escape` of that character (a trailing lone `\` is
   dropped); `?` → `.`; a bracket expression `[...]` → the equivalent regex
   class (with `[!x]` → `[^x]`, and `]` allowed as the first member); any
   other character → `re.escape(ch)`. An unterminated `[` is a literal `[`.
   Empty segments (from `**` or a leading/trailing `*`) are dropped.
4. Compile each segment with `re.compile(pattern, re.I)`. The first segment
   is compiled with a `^` prefix if `anchored_start`; the last with a `$`
   suffix if `anchored_end`. If compilation raises `re.error` (defensive;
   the translator should never emit an invalid pattern), fall back to the
   fully escaped literal text so a keystroke can never raise on the Qt
   thread.
5. `FilterMatcher.matches(name)` scans the segments left to right with
   `segment.search(name, pos)`, setting `pos = match.end()` after each hit,
   and returns `all found != negate`. Greedy leftmost placement is sufficient
   for existence because `*` matches any string.

Why segments: a single regex `a.*b.*c` or `.*.*.*.Z` lets Python's
backtracking engine explore exponentially many splits on a nonmatching name;
the review timed `?*?*?*?*?*?*?*?Z` at over one second against one
96-character name. A fixed-length segment contains no quantifier, so each
`search` is O(len(name) × len(segment)) in C, and the scan does
at most one search per segment. The worst case is therefore
O(len(name) × len(text)) ≤ 255 × 255 elementary steps per row, with no
exponential path. For text without `*` there is exactly one segment and one
`search`, the same as today.

Empty `text` yields a matcher with no segments that accepts everything, as
today.

### Item 6 (only if confirmed)

- `_on_key_pressed` gains `if self._filter_bar.isVisible() and event.key()
  == Key_Space:` beside the existing `Backspace` branch.
- `compile_filter` returns a `FilterMatcher` holding one segment list per
  space-separated term; `!` applies to the whole expression; `^`/`$` apply
  per term. `matches` becomes `all(term scan) != negate`. Consecutive or
  trailing spaces are ignored. The bound becomes O(len(name) × len(text))
  summed over terms, still polynomial.
- `Space` reverts to `toggle_selection` as soon as the bar is closed.

### Threading and failure behavior

All work stays on the Qt thread inside the existing `textChanged` handler.
Compilation is a single pass over at most 255 characters. No I/O, no timers,
no new signals beyond `FilterBar.filter_changed`, `FilterBar.filter_cleared`
and `Model.files_changed`. Invalid input cannot raise (step 4). `MainWindow`
owns both the panes and the status bar, so the slots cannot outlive their
target; `remove_pane` disconnects the pane's signals before deletion.

## Alternatives

- `fnmatch.translate` directly: whole-name semantics would break today's
  substring behavior (`rep` no longer matches `Report.pdf`) and it emits
  `(?s:...)\Z`, which complicates anchoring. A ten-line hand translator is
  simpler and keeps the substring default. Rejected.
- Regex mode (`re:` prefix): pathological patterns cannot be interrupted on
  the Qt thread and a regex home already exists in the `Ctrl+E` plan.
  Rejected.
- Smart case (case-sensitive when the text has an uppercase letter): cheap,
  but an invisible mode switch in a feature that has no mode indicator.
  Deferred; can be added later as a compile-time flag.
- Treating `^`/`$`/`!` as special anywhere in the text: collides with legal
  filename characters. Leading/trailing-only keeps collisions to one position
  each. Rejected.
- One regex for the whole pattern (`*` → `.*`): the first design. Rejected
  after the review demonstrated catastrophic backtracking on `?*?*...Z`; a
  compiled regex is not a cost bound when it contains repeated `.*`.
- Pure-Python greedy wildcard matcher (two-pointer with backtrack to the last
  `*`): the same polynomial bound, but a Python loop per character per row is
  roughly 20-50× slower than C `search`; 5,000 rows × 30 characters would
  approach the frame budget. Rejected in favor of per-segment C searches.
- Observing the proxy's `modelReset`/`rowsInserted`/`rowsRemoved` for the
  count: the first design. Rejected after the review showed a nonmatching
  addition changes the total with no proxy signal. `Model.files_changed` is
  the narrowest change that covers every `_files` mutation.
- Forwarding through `DirectoryPaneWidget.window`: resolves to the central
  widget, not `MainWindow`. Rejected; `MainWindow.add_pane` wires the pane
  signals directly, as it already owns both objects.
- Match count inside the filter box (`rep  12/340`): no status-bar interplay,
  but the box is tiny, bottom-right and auto-sized; widening it on every
  keystroke jitters. The user prefers the status bar. Rejected.
- Match count in `PaneStatusWidget` (extended status bar): only visible when
  that optional mode is enabled, and its refresh is debounced 150 ms and
  computed off-thread, which would delay a value already known synchronously.
  Rejected; can be added to `StatusSummary` later without conflict.
- A dedicated permanent status-bar label for the filter: avoids sharing the
  message slot with plug-ins, but adds a widget that is empty almost always.
  Rejected in favor of the existing message slot.

## Runtime Effects

- Startup: none.
- Per keystroke: one translation pass plus one `re.compile` per segment
  (usually one or two), then per row one fixed-length `search` per segment.
  Worst case per row is O(len(name) × len(text)) with no exponential path;
  for text without `*` it is a single search, identical to today. The match
  count adds two O(1) reads and one `QLabel.setText`.
- File-set change while filtering: one `files_changed` dispatch and, if
  active, the same two reads and `setText`. With the filter inactive, one
  boolean check per change.
- Memory: one `FilterMatcher` (a tuple of compiled segments and two
  booleans) and three signal connections per pane.
- Cancellation, threads, I/O: not applicable.
- Disabled/no-op path: not applicable; with no special characters the
  matcher performs the same single `search` as the current implementation.

## Tests

Focused commands:

```powershell
$env:PYTHONPATH = 'src/main/python;src/unittest/python;src/integrationtest/python;src/main/resources/base/Plugins/Core'
python -m unittest fman_unittest.impl.test_filter_pattern
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_integrationtest.test_qt.FilterBarIT
```

New `fman_unittest/impl/test_filter_pattern.py` over `compile_filter`,
asserting acceptance per name (not regex text) for:

- Backward compatibility: `''`, `rep`, `rep*pdf`, `a*b*c`, text with regex
  metacharacters (`a.b`, `a+b`, `(x)`), case-insensitivity — all matching
  exactly the current implementation's results on a fixture list.
- Glob: `?` single character; `[abc]`, `[a-z]`, `[!x]`, `[]a]`; unterminated
  `[` as literal; `*` unchanged.
- Anchors: `^rep`, `.py$` excludes `foo.pyc`, `^a*z$`, `^`/`$`/`^$` alone
  are literals, `$` in the middle and `^` not at the start are literals,
  `$RE` matches `$RECYCLE.BIN`.
- Negation: `!tmp`, `!^tmp`, `!` alone is a literal, `!` in the middle is
  literal.
- Escape: `share\$` matches `share$` and not `share`; `\^x`, `\!x`, `\*`,
  `\?`, `\[a]` are literals; `[$]` equals `\$`; trailing lone `\` is
  ignored; `\\` is never needed but compiles.
- Never raises: every prefix of representative queries and a fuzz of the
  special characters compiles without exception.
- Bounded cost: `?*?*?*?*?*?*?*?Z`, `a*a*a*a*a*a*a*a*Z` and `*` repeated 100
  times, each against `'a' * 255`, complete in under 1 ms per name; the
  test asserts a wall-clock bound of 50 ms for 1,000 such names.
- Item 6 (if confirmed): `rep 2024` unordered, `!a b` negates the whole
  expression, `^a b$` anchors per term, repeated/trailing spaces.

Qt: add `FilterBarIT` to `fman_integrationtest.test_qt` using the real
`MainWindow`, `add_pane` and a `Model` fixture (not a stand-in parent). Existing
`FilterBar` behavior (open on printable key, close on `Escape`, close on
location change, prefix cursor placement) is covered there for the first time;
it types `!tmp` and `^rep` into a pane and asserts the visible row set. If
item 6 is confirmed, add a case that `Space` edits the filter while visible
and toggles selection when it is not.

Match count (same `FilterBarIT`), asserting `MainWindow._status_bar_text`:

- First printable key over a fixture of 5 rows with 2 matches sets
  `Filter "r": 2 of 5 items`; typing further updates it.
- Final `Backspace` (bar hidden by `setVisible(False)`, `close()` never
  called), `Escape`, and navigating away with an active filter each reset the
  text to `Ready.` exactly once.
- Navigating away with no active filter leaves a preceding
  `show_status_message('Copied')` untouched.
- `Model._record_files_main` adding a **nonmatching** file changes the text
  to `2 of 6`; adding a matching file to `3 of 7`; removing a nonmatching
  file back to `3 of 6`; a filter with zero matches shows `0 of N`. With the
  filter inactive, the same commits leave the status text untouched.
- `show_status_message('Copied')` while filtering replaces the count; the
  next keystroke restores it.
- Two panes: with an active filter in the inactive pane, its commits do not
  touch the status bar; focusing that pane republishes its count; focusing
  back to a pane without a filter clears to `Ready.`.

Manual: `?`, `[...]`, `^`, `$`, `!`, `\$` in a real folder containing
`$RECYCLE.BIN`; confirm the bar still opens, closes on `Escape`, and clears on
navigation.

## Implementation Steps

1. Add `fman/impl/filter_pattern.py` with `compile_filter`/`FilterMatcher`
   and its unit tests, including the bounded-cost cases; run the focused
   command.
2. Wire `FilterBar._on_text_changed`/`_accepts` to `compile_filter`, set the
   input `maxLength` to 255, and add `FilterBarIT` pattern cases.
3. Add `Model.files_changed`; add `_active`, `filter_changed` and
   `filter_cleared` to `FilterBar`; re-expose on `DirectoryPaneWidget`; wire
   in `MainWindow.add_pane`/`remove_pane`/`_set_active_pane`; add the
   match-count `FilterBarIT` cases.
4. README: one feature bullet describing the filter syntax and the status
   count; CHANGELOG entry under Unreleased / Added.
5. Optional, last: ask the user whether item 6 (Space as AND) is in scope and
   record the answer in this document. If confirmed, route `Space` in
   `_on_key_pressed`, extend `compile_filter`, tests, README and CHANGELOG.

## Acceptance Criteria

- Filter strings without `? [ ^ $ ! \` produce exactly the same visible rows
  as before the change.
- `?`, `[...]`, leading `^`, trailing `$`, leading `!` and `\` escapes behave
  as specified; `$`, `^` and `!` alone are literals.
- No keystroke in the filter can raise an exception, and no pattern of up to
  255 characters can take more than O(len(name) × len(text)) per row; the
  adversarial cases in Tests pass their time bound.
- While a filter is active in the active pane the status bar shows
  `Filter "<text>": <matched> of <total> items`, updated on every keystroke
  and on every `_files` change including nonmatching additions/removals;
  the single active-to-inactive transition resets it to `Ready.` once, and
  `close()` on an inactive bar touches nothing.
- No file outside `fman/impl/filter_pattern.py`, `fman/impl/widgets.py`
  (`FilterBar`, `DirectoryPaneWidget` signal re-export, `MainWindow` wiring,
  plus `_on_key_pressed` if item 6), `fman/impl/model/model.py`
  (`files_changed` signal only), tests, README and CHANGELOG changes.
- Item 6 is either implemented with its tests or explicitly recorded as
  declined in this document.

## Reviewers

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Initial design. Verified the current `FilterBar` compilation and
  key routing (`Space` is consumed by `toggle_selection` before the bar sees
  it; `Backspace` is special-cased while visible). Items 1-3 are confined to
  regex compilation via a new Qt-free `compile_filter`; item 4 is the only
  behavior change and is gated on explicit user confirmation before
  implementation.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Added item 5, match count in the main status bar, at the user's
  request. Verified that `SortFilterTableModel.update()` is synchronous so
  `rowCount()` and `len(get_rows())` are available immediately after the
  keystroke; the message reuses `show_status_message`/`clear_status_message`
  and adds no widget or timer. Recorded the shared-slot interaction with
  plug-in messages and rejected the extended-status-widget and in-box
  alternatives. Item 4 remains gated on explicit confirmation.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: User asked how to search for a literal `$`, which Windows allows
  in filenames. Added item 4, `\` as escape character (`\` is forbidden in
  Windows filenames so it never collides), and the rule that a text made only
  of `^`/`$`/`!` is literal. Renumbered Space-as-AND to item 5 and match
  count to item 6; the AND item remains gated on explicit confirmation.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Low
- Context Window: 1M
- Outcome: Per user request, moved the optional Space-as-AND item to the end
  as item 6 and match count to item 5; the confirmation question is now the
  last implementation step so items 1-5 can ship independently.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Not approved for implementation as written. Verified four blockers
  in status forwarding, regex execution cost, count notifications, and filter
  close handling. Appended review only; application code and the operative
  design are unchanged.

#### Findings

1. **[P1] The proposed window forwarding targets the wrong widget.**
   `DirectoryPaneWidget.window` returns two parents up. The current hierarchy
   in [widgets.py](../src/main/python/fman/impl/widgets.py) is pane, splitter,
   central QWidget, MainWindow. A Qt probe confirmed the property resolves to
   the central widget, which has no `show_status_message` or
   `clear_status_message`. The proposed first count update would raise
   AttributeError. Use a verified MainWindow lookup/reference and an explicit
   teardown guard; the current property supplies neither. Test the real main
   window hierarchy, not a stand-in parent with the desired methods.

2. **[P1] The proposed translator can block Qt on a short valid query.**
   Translating `?*?*?*?*?*?*?*?Z` by the specified `? -> .`, `* -> .*` rules
   exceeded a one-second timeout against one 96-character all-`a` filename.
   The current literal-question-mark interpretation returned in microseconds.
   Catching `re.error` does not interrupt successful compilation followed by
   catastrophic backtracking. Choose a translation/matching strategy with a
   justified worst-case bound and test adversarial nonmatches before promising
   identical per-keystroke cost. A single compiled regex alone is not that
   bound. Also, the current QLineEdit limit is 32767, not a few dozen characters.

3. **[P2] The proposed signals miss changes to the unfiltered total.**
   A real [Model](../src/main/python/fman/impl/model/model.py) commit adding
   `backup.tmp` under a `rep` filter changed `(matched, total)` from `(1, 2)`
   to `(1, 3)` without any proxy `modelReset`, `rowsInserted`, or `rowsRemoved`
   signal. Removing a nonmatching file has the same structural gap. Observe
   source-content commits/completed reloads, including unchanged visible row
   sets; allow a narrow model change if necessary. Do not assume
   `transaction_ended` alone fixes this: the table emits it only when the
   displayed-row diff changed. Test nonmatching additions/removals and an empty
   result set, not only insertion of a matching row. `sourceModel().update()`
   refilters in-memory rows; it is not an actual filesystem reload test.

4. **[P2] A signal emitted only from `close()` misses empty-text closure.**
   The existing `handle_keypress` hides the bar with `setVisible(bool(query))`
   after QLineEdit emits `textChanged`. A real final-Backspace probe confirmed
   the empty-text handler runs while the bar is still visible and `close()` is
   never called. The proposed wiring can leave `Filter "": N of N items`
   behind instead of `Ready.`. Conversely, navigation calls `close()` even
   when the bar was already hidden, so unconditional clearing can erase an
   unrelated message. Define one active-to-inactive transition, order count
   publication around it, and test first input, last Backspace, Escape,
   navigation with an active filter, and navigation with no active filter.

#### Additional Design Decisions

- Define which pane owns the shared count when both panes have visible filters
  and the inactive pane reloads; visibility alone does not mean active pane.
  Retain the explicitly chosen plug-in-message replacement policy separately.
- If item 6 is confirmed, reconcile its per-term regex tuple with the hard
  one-regex-per-row and ordinary-space compatibility claims. Keep that approval
  separate from items 1-5. Add an exact offscreen Qt test command and bounded
  performance checks to the required validation, not only the pure unit test.

#### Review Validation

- Offscreen Qt probes used the current MainWindow/splitter hierarchy and
  FilterBar key handling; confirmed the window lookup and final-Backspace
  findings without changing application files.
- An in-memory `Model._record_files_main` probe with a real Qt proxy confirmed
  the missing notifications for the `(1, 2)` to `(1, 3)` count change.
- Timed the exact proposed wildcard translation in an isolated Python child
  against `'a' * 96`, using `subprocess.run(..., timeout=1)`. The child reached
  matching, exceeded the limit, and was terminated/reaped. This tests the
  specified translation, not an implemented `compile_filter` function.
- No application implementation, full suite, build, or package installation
  was performed. The probes establish design defects, not feature acceptance.

### 2026_09_16 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Accepted all four GPT-6 Astra findings and both additional
  decisions; verified each against `widgets.py`, `table.py`
  (`transaction_ended` fires only when `_transaction_made_changes`) and
  `model.py` (`_files` is mutated in `_record_files_main` and
  `_on_files_reloaded` only). Revised the operative design accordingly; the
  Task statement no longer claims "one compiled regex, identical cost".

#### Follow Up Tasks

- [x] **[P1] Window forwarding.** `DirectoryPaneWidget.window` is no longer
      used. `MainWindow.add_pane` connects the pane's `filter_changed` /
      `filter_cleared` signals directly; `remove_pane` disconnects. Resolved
      in Design > Ownership.
- [x] **[P1] Backtracking.** Replaced the single `.*`-joined regex with
      per-segment fixed-length regexes scanned left to right with
      `search(name, pos)`; worst case O(len(name) × len(text)), no
      quantifiers in any compiled pattern. Input `maxLength` set to 255.
      Adversarial timing cases added to Tests. Resolved in Design >
      Compilation and Alternatives.
- [x] **[P2] Total-count notifications.** Added the narrow private signal
      `Model.files_changed`, emitted after `_record_files_main` and
      `_on_files_reloaded`; `FilterBar` observes it instead of proxy row
      signals. Tests cover nonmatching add/remove and zero matches. Resolved
      in Design > Ownership and Match count.
- [x] **[P2] Close transition.** One `_active` boolean owned by
      `_on_text_changed`; `filter_cleared` fires only on active-to-inactive,
      `close()` merely sets empty text. Covers final Backspace, Escape, and
      navigation with and without an active filter. Resolved in Design >
      Ownership; test cases added.
- [x] **Pane ownership.** Only the active pane publishes; `_set_active_pane`
      republishes or clears on focus change. Resolved in Design > Match count.
- [x] **Item 6 reconciliation and validation.** Item 6 now specifies one
      segment list per term under the same polynomial bound; exact offscreen
      command `fman_integrationtest.test_qt.FilterBarIT` and bounded-cost
      tests added. Item 6 remains gated on explicit confirmation.
