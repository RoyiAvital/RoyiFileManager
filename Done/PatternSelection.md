# Select And Deselect By Pattern

## Task

Implement approved item 2 of [Roadmap001](Roadmap001.md): preview file marks in
the existing inline Filter Bar without hiding rows or changing committed selection.

## Scope

- `SelectByPattern` / `DeselectByPattern`, aliases Select group / Deselect group.
- Keypad `Num++` / `Num+-`; ordinary punctuation remains ordinary input.
- Current visible rows only, including folders. Existing Filter Bar syntax and limit.
- No scans, metadata I/O, persistent settings, new modal UI or changed Copy/Delete policy.

## Design

The pane owns the session through its Filter Bar. Opening captures the displayed
Listing, visible indices, original selected row indices and input presentation on
Qt. The existing normal matcher stays applied. A mode/count label identifies the
preview. The default query is an escaped, end-anchored cursor extension or `*`.

Matching uses a lazy, pane-owned `LatestJobs(cooperative=True)` lane: one running
job and one replaceable pending query. Workers receive immutable names, indices
and baseline marks; cancellation checkpoints cover traversal. A queued signal
carries the session identity, input revision, result or error. Only current
results paint prospective rows. No `selectionModel.select` calls occur while typing.
`get_selected_files`, status and transfer commands still see committed selection.

Active-mode key routing precedes pane shortcuts. Space, keypad punctuation,
Backspace, navigation within the input and editing shortcuts go to the QLineEdit.
Enter commits the completed revision, or waits for that revision; further typing
clears pending acceptance. Esc cancels. Other shortcuts dismiss before normal
dispatch. Command-registry dispatch also dismisses before reading the selection.

When the ordinary Filter Bar is already open, printable keypad input belongs to
that editor too; the selection shortcuts apply only with the bar closed. Use
Command Center to open Select/Deselect while retaining an existing filter.

Select computes baseline union matches; Deselect computes baseline minus matches.
Empty input means baseline. Commit uses existing pane select/deselect calls after
the preview session is detached. Exit restores the prior input text, visibility,
placeholder and pane focus without changing the normal filter, cursor or scroll.

Active-only subscriptions cancel on snapshot replacement, sorting, filtering,
selection edits, navigation and close. Disconnect before restoration/commit.
Late worker results are rejected. Cancellation never waits for workers on Qt.
Matching errors show a failed-preview state and cannot commit older matches.

## Alternatives

- Modal pattern prompt: rejected by the approved roadmap.
- Mutate marks on every edit: rejected because commands/status would consume previews.
- Synchronous matching: rejected for typing responsiveness on large listings.
- New selection/provider API: unnecessary; existing snapshot and selection behavior suffice.
- Batched deselection: measure existing commit cost first; optimize only if needed.

The measured 5,000-mark deselect commit took 2936.0 ms and emitted 5,000 signals.
The implementation therefore reuses the existing selection range builder for
deselection too, preserving missing-row and successful-prefix behavior.
The shared builder also sorts unique resolved view rows before forming contiguous
ranges, so input/listing order does not fragment selections sorted by another column.

## Runtime Effects

No scans, worker jobs, timers or recurring preview signals when inactive. A lane
object may remain idle after use to bound work across rapid reopenings. An active
session retains one snapshot, visible indices and O(rows) baseline/result sets.
Each query is O(visible rows); obsolete queries cancel cooperatively. Commit uses
existing Qt selection operations. Range preparation retains O(selected rows) row
indices and sorts them in O(selected rows log selected rows) before coalescing.
No persistence or child process is involved.

## Tests

Planned tests added to existing modules:

- `fman_unittest.impl.test_filter_pattern`: anchored/escaped seed, additive and
  subtractive fixed-baseline matching, empty query, cancellation, display labels.
- `fman_integrationtest.test_qt.PatternSelectionIT`: mode-local editing/keypad
  routing; existing filter, rows/order/cursor/scroll preservation; zero matches;
  pending acceptance, correction and failure; committed-only Copy/Delete selection;
  replacement listing/navigation/sort/filter/selection/close and stale results.
- Keypad matcher checks distinguish Num++ / Num+- / Num+* from ordinary keys.
- Native large-list check: query-to-preview, next-input responsiveness and commit
  duration; report measured size and notification counts, not an assumed single update.

Focused launcher uses the existing Python and `build._environment()`:

```powershell
python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_unittest.impl.test_filter_pattern','fman_integrationtest.test_qt.PatternSelectionIT','-v'],env=build._environment(),timeout=180).returncode)"
```

Repeat the Qt class with `QT_QPA_PLATFORM=offscreen`. No full suite or freeze.

## Implementation Steps

1. Add pure preview matching/seed helpers and focused tests.
2. Add paint-only view override and pane-owned worker lifecycle.
3. Wire commands, keypad bindings, mode-local input and dispatch cancellation.
4. Run native/offscreen lifecycle and large-list measurements; fix demonstrated issues.
5. Document concise usage and record completion with exact checks.

## Acceptance Criteria

- Typing changes only prospective marks; rows and committed selection stay unchanged.
- Enter commits exactly the latest completed query; Esc and outside actions cancel.
- Hidden/filtered rows are never newly selected. Existing filters and unrelated marks survive.
- Space/keypad/editing keys edit the pattern. Ordinary keys are not captured as keypad shortcuts.
- No late result paints or commits after invalidation, and no Qt-thread joins or filesystem I/O.
- Focused checks pass and timings are reported with their actual scope.

## Reviewers

### 2026_10_22 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Extracted the approved roadmap design before implementation. Reviewed
  Filter Bar routing, immutable projection indices, existing LatestJobs and public
  selection APIs. Explicit command-boundary cancellation and paint-only state
  protect committed-selection semantics; no independent review is claimed.

### 2026_10_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Verified preview-only painting, current-revision acceptance, command
  cancellation and no-op selection-edit dismissal. Native tests found deleted-view
  cleanup and modifier-only input edge cases; both were fixed and rechecked.
  Measured deselection justified using the existing range builder for one Qt update.

### 2026_10_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Applied Roadmap001 Opus R1/R2 at the shared input/selection boundary.
  Existing ordinary filters keep keypad text; closed-bar shortcuts are unchanged.
  Sorted unique row coalescing preserves prefix/error semantics and avoids Qt
  fragmentation in differently ordered views. Canonical roadmap records the probes.

## Implementer

### 2026_10_22 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Implemented the approved Select/Deselect inline modes and keypad bindings.
  Temporary marks are delegate state, not committed Qt selection. LatestJobs bounds
  matching and rejects stale results. Existing filters, cursor and scroll survive;
  commands and external changes cancel before consuming selection. No filesystem
  work, persistence or Qt-thread joins were added. Native/offscreen checks passed.

### 2026_10_22 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Updated shared keypad routing and Select/Deselect range construction
  without changing preview ownership or commit semantics. Existing pattern tests
  and the new real-Controller/20k-view-order regressions pass in Roadmap001 gates.

## Validation Results

The exact combined launchers and gate counts are in
[Roadmap001 Validation Results](Roadmap001.md#validation-results).

- `fman_unittest.impl.test_filter_pattern`: **7 passed**, including escaped/end-anchored
  seeds, display-name matching, fixed baseline, empty input and cancellation.
- `fman_integrationtest.test_qt.PatternSelectionIT`: all **8 tests passed** in both
  native and configured offscreen runs. Covers keypad/Space/editing/modifier keys,
  zero/empty queries, pending Enter, corrections, errors, late results, deleted pane,
  visible-only painting, filter/cursor/scroll, Copy/Delete dispatch and invalidation.
- 10,000-row local native measurement: next input 14.7 ms, preview 15.0 ms,
  Select commit 108.2 ms, Deselect commit 327.5 ms; one notification each.
  Before batching: Deselect 2936.0 ms and 5,000 notifications. No broad speed claim.
- Existing Filter Bar, snapshot/model, clipboard, status and command tests passed
  in the roadmap gates. A deleted Qt view originally caused a worker traceback;
  cancellation now checks widget lifetime before restoring UI. Final runs were clean.
- No full suite, freeze, new package/environment or manual release certification.

Review follow-up: see [Roadmap001 review-fix validation](Roadmap001.md#review-fix-validation)
for R1/R2 native/offscreen checks, range counts, measured costs and teardown handling.
Original results above retain their historical scope and timings.