# Batch File Renamer

Status: Consolidated design for the next review cycle. No application or plug-in
implementation is authorized yet. The public API extensions below are proposed,
not available in the current host.

## Task

Provide a small, independently installable third-party file renamer that
demonstrates QuickBoard: compose a template, inspect the proposed names, filter
and order the candidates, then rename exactly the visible files.

The plug-in owns template interpretation, operation scope and collision hints.
QuickBoard owns only generic rows, their view mapping and dialog lifetime.
The application owns a shared no-overwrite Rename operation, not a plug-in bypass.

## Scope

- One Command Center command: **Batch File Renamer**, ID `batch_file_renamer`.
  No default shortcut or new Panel/buttons; use the existing frameless, modal,
  owner-free QuickBoard.
- Capture selected files, falling back to the cursor through public
  `DirectoryPaneCommand.get_chosen_files()`. Later pane selection changes do not
  replace those candidates. Filtering inside QuickBoard determines the final set.
- V1 accepts 1-10,000 regular, non-reparse files in one Windows local-drive folder.
  Reject directories, mixed parents, UNC/archive/virtual sources and unreadable
  required metadata. Never silently drop an unsupported selected item.
- Six variables, date formatting, zero-based indices and positive constant index
  offsets. No Python evaluation, regex replacement, transformations, presets,
  counter controls, recursion, undo or saved session state.
- No overwrites, swaps, rename chains through occupied names, case-only batch
  changes or temporary-name staging. Exact unchanged names are no-ops.
- The plug-in uses only public `fman`, `fman.fs`, `fman.url`, `fman.ui` and standard
  library APIs. No Qt/Core imports, `fman.impl`, private attributes, private query
  names, monkeypatching or direct native file mutation in the delivered plug-in.

## Design

### Template Syntax

Enter the template without an `f` prefix or surrounding quotes.

| Variable         | Meaning                                          |
| ---------------- | ------------------------------------------------ |
| `{current_date}` | Local date/time captured when the command starts |
| `{file_date}`    | Captured last-modified date/time, in local time  |
| `{index}`        | Current visible position, starting at zero       |
| `{file_index}`   | Fixed whole-folder natural-order position        |
| `{name}`         | Original name without its final extension        |
| `{ext}`          | Final extension, including its leading dot       |

- Default template: `{name}{ext}`. Use `os.path.splitext`: `archive.tar.gz` splits
  into `archive.tar` and `.gz`; `.gitignore` and extensionless files have empty
  extensions. Omitting `{ext}` deliberately removes the extension.
- Capture current time, file timestamps and time-zone interpretation once.
  Crossing midnight or changing the template does not change those values.
  Dates default explicitly to `%Y-%m-%d`, never `str(datetime)`.
- Date formats allow `%Y`, `%y`, `%m`, `%d`, `%H`, `%M`, `%S` and `%%`, with at
  most 128 specification characters. `%H:%M` is valid syntax but produces an
  invalid Windows name because of the colon; report that as a name problem.
- Both indices accept an empty format, `d`, or a width of 1-32 with `d`, including
  zero padding such as `03d`. Width is a minimum: `02d` does not truncate `149`.
  Recommend enough padding for the largest index after its offset.
- The only arithmetic adds one positive ASCII decimal integer to `index` or
  `file_index`, optionally inside one pair of parentheses. Allow spaces around
  tokens and at most 255 offset digits. Reject zero/signed offsets, subtraction,
  repeated addition, other operators, reversed operands and nested parentheses.
- Support literal braces through `{{` and `}}`. Reject unknown/empty/positional
  fields, conversions, attribute/index access, nested fields and function calls.
  Name and extension accept no format specification.

Use `string.Formatter.parse()` plus a strict field/specification allowlist and
direct recognition of the small offset grammar. Do not use `eval`, `exec`,
generated f-string source or unrestricted field lookup.

| Template                                    | Example Output          |
| ------------------------------------------- | ----------------------- |
| `{name}{ext}`                               | `report.txt`            |
| `{index:03d}_{name}{ext}`                   | `000_report.txt`        |
| `{(index + 5):03d}_{name}{ext}`             | `005_report.txt`        |
| `{(file_index + 1):03d}_{name}{ext}`        | `003_report.txt`        |
| `{current_date}_{name}{ext}`                | `2026-10-06_report.txt` |
| `{file_date:%Y%m%d}_{(index + 1):03d}{ext}` | `20260930_001.txt`      |

Examples use `report.txt`, visible index 0, file_index 2, current date 2026-10-06
and modification date 2026-09-30.

### Candidate Capture and Indices

On the command worker, use a cancellable `Task` to capture immutable records:
source URL, raw name, split name/extension, file_index, identity, size and mtime.
Use fresh `os.lstat` on full paths for selected-file and parent identity; reject
missing/zero identity. Do not use Windows `DirEntry.stat()` for identity.

Enumerate the parent with fresh `os.scandir`, not cached `fman.fs.iterdir`.
Record all occupied names, including hidden entries, directories and reparse
points. Close the iterator on every exit path. Separately identify every regular,
non-reparse file for file_index; classification failures abort incomplete capture.

`file_index` starts at zero and includes hidden/unselected regular files, ignoring
pane filters. Directories and reparse entries do not consume an index in this v1
scope, but still occupy names. Sort decimal digit runs numerically and text
case-insensitively, with exact name as the final tie-breaker: `IMG_2` precedes
`IMG_10`. Define the pure key in the plug-in, without a private host import.

Candidate generator rows retain this captured natural order. `{index}` is their
current visible rank supplied by QuickBoard, not their generator position.
Sorting/filtering changes index; file_index remains fixed. Equal sort keys retain
generator order in either direction. Neither numbering scheme changes the capture.

### QuickBoard Mapping Contract

The only public QuickBoard changes are:

```python
get_rows(text, mapping)
text, accepted, mapping = show_quick_board(...)
```

- `mapping` is an immutable tuple indexed by generator row position. An integer
  is the zero-based visible position; `None` means filtered out. Generated
  `[A, B, C, D]` displayed as `[C, A]` yields `(1, None, 0, None)`.
- Non-None positions are unique and consecutive. Use source positions, not row
  object identity, so equal or repeated row objects are independently mapped.
- Each text revision begins with `get_rows(text, None)`. It returns all source
  rows with neutral derived cells. The host projects them and calls the handler
  again with the map. Bootstrap rows cannot be accepted as a finished preview.
- Mapped responses keep row count, generator order and sortable/filterable source
  cells unchanged. Only non-sortable, non-filterable derived cells may change.
  Reject observable contract violations as preview errors, not reproject loops.
  The caller is responsible for stable identity when source fields are identical.
- Sort/filter changes regenerate the preview when their mapping changes. Text
  edits bootstrap a new snapshot. Hidden rows remain in responses so filters can
  reveal them again; return neutral derived cells for those rows.
- Text, mapping and completed preview belong to one revision. Enter waits for it;
  later text/sort/filter edits clear queued acceptance. Return
  `(text, True, mapping)` only for the settled approved preview. Cancellation is
  `(current_text, False, None)` without waiting for work. Zero rows map to `()`;
  all hidden rows map to a tuple of `None`, distinct from bootstrap/cancellation.
- Preserve the existing bounded worker lanes, queued Qt delivery and stale-result
  rejection. Workers receive immutable plain data; widgets/models stay on Qt.

QuickBoard does not interpret names, validity markers or operation scope. No
public owner, mutable handle, second ordering map or operation/validity callback
is added. Existing callers must accept the second handler argument and unpack
the third result. Update runnable API examples and docs when this is implemented;
until then, clearly distinguish the proposal from the current two-value API.

### User Workflow

Open QuickBoard with title **Batch File Renamer**, text `{name}{ext}`, and a brief
summary such as `12 candidates; visible rows only | {(index + 1):03d} | {file_index}`.
Use the existing elided summary/tooltip, not a new syntax-help control.

| Column        | Type      | Sort/Filter | Value                      |
| ------------- | --------- | ----------- | -------------------------- |
| Index         | numeric   | No          | Current visible rank       |
| File Index    | numeric   | Yes         | Captured folder position   |
| Original Name | file_name | Yes         | Captured source name       |
| File Date     | date      | Yes         | Captured modification time |
| New Name      | file_name | No          | Generated destination name |
| Valid Name    | text      | No          | Unicode marker and reason  |

Set both `sortable=False` and `filterable=False` for Index, New Name and Valid
Name. They update when text/mapping changes, but never determine their own order
or visibility. File Date displays the date; sorting uses the captured timestamp.

`get_rows` is pure computation over capture and mapping: no I/O or mutation on
typing/sorting/filtering. Parse once and generate only active candidates' names.
Use `✓ Ready`, `✓ Unchanged`, `✗ Duplicate target`, `✗ Target exists` or a precise
invalid-name reason. The Unicode markers are ordinary UTF-8 text, accompanied
by words and existing cell tooltips, not new QuickBoard semantics.

Syntax errors raise `ValueError` for the footer. Per-file problems stay visible
in Valid Name; QuickBoard does not block Enter because of a cross. After Enter,
rebuild the active plan from the exact returned text/map and original records.
Validate again without reading displayed markers or shortened names.

If any active candidate is invalid, change nothing, show a concise alert and
reopen with the template. Sort/filter/scroll state resets in v1 and the user
reviews the new preview. Empty or all-unchanged visible sets are no-ops. Otherwise
the preview is approval: start fresh preflight and execution without another
routine confirmation dialog. Escape never mutates files.

### Validation and Bounded Preview

- Check duplicate proposed targets among active rows only and flag every member.
  Excluded rows' hypothetical destinations do not participate.
- Check active destinations against all occupied originals: filtered-out,
  unselected and unchanged files, directories, and other active sources. A hidden
  `B.txt` still blocks visible `A.txt -> B.txt`. V1 rejects occupied-source chains
  and swaps rather than assuming another rename will free a name.
- Reject empty names, `.`/`..`, separators, drive/stream syntax, control characters,
  reserved Windows names, trailing spaces/dots and names over 255 UTF-16 units.
  Validate the resulting full path using the host's supported path rules. Never
  trim or repair names silently; exact original-name equality is a no-op.
- Use conservative `casefold` comparison, not a claim to emulate NTFS. For distinct
  names equal under it, report `Conflicts ignoring case`, including expansions
  such as sharp-s versus `ss`; do not mislabel them all as case-only renames.
- Render incrementally with a bounded builder. Once a candidate exceeds 255
  UTF-16 units, retain only a short prefix and continue counting chunk lengths;
  never join or retain the entire oversized candidate.
- Original Name display is escaped and capped at 768 UTF-8 bytes including any
  shortening marker. A valid New Name stays complete, at most 765 UTF-8 bytes.
  Invalid New Name display is capped at 384 bytes with a visible marker; Valid
  Name is capped at 64 bytes and includes the invalid length/reason. Truncate at
  character boundaries. Tooltips, highlights and row metadata must not restore
  unbounded data. Raw source and valid target names stay in caller-owned records.
- With date-only display, three typed slots and displayed indices, a conservative
  mapped six-column budget is
  `10,000 * (768 + 765 + 64 + 10 + 24 + 5 + 25) = 16,610,000` bytes, below 16 MiB.
  The last two terms cover displayed Index (up to 9,999) and File Index (bounded
  by the host's signed 64-bit numeric type), including grouping separators.
  Validate this with unique worst-case rows in the real schema. It is a payload
  bound, not a total Python/Qt memory guarantee.

Preview hints use captured state. A check mark does not replace fresh preflight
or the native no-overwrite rule.

### Shared Rename API

Use Rename for a basename change in the same parent folder; use Move when the
parent changes, optionally changing the basename too. Existing explicitly
approved Move replacement behavior must remain unchanged.

Proposed public API in `fman.fs`:

```python
rename_no_replace(source_url, destination_url) -> RenameResult
RenameResult(source_url, destination_url, changed, notification_warnings)
```

`RenameResult` is an immutable plain public record. A return confirms the
operation outcome; `changed=False` is permitted only for an existing source
with the identical destination spelling. Otherwise native/provider success
returns `changed=True` with the confirmed destination URL.

- Reject cross-parent/cross-scheme requests with `io.UnsupportedOperation` before
  mutation. Base provider support raises `NotImplementedError`. No fallback to
  replacing Move, merge or copy/delete is allowed inside this API.
- The Windows local provider uses native non-replacing rename (`os.rename`), not
  `Path.replace` or replace-existing flags. An occupied destination fails at the
  operation itself, including one created after preflight. Case-only rename of
  the same entry remains supported by the host; a different hard-link entry is
  not an exemption from collision checks.
- Native failure before commit raises its normal error. Once mutation succeeds,
  notification-listener failures become bounded `notification_warnings`, never
  an ambiguous rename-failed exception. Attempt both removal/addition notification
  paths and isolate listener failures in this new path; do not globally change
  unrelated event behavior. No caller infers commit from path existence or retries
  a mutation because notification failed. Process termination/power loss remains
  outside this in-process outcome guarantee.
- Publish the existing cache/listing notifications through the host. Ordinary
  Rename and the plug-in consume the same result and report refresh warnings
  separately from confirmed mutation. Batch execution stops after a warning to
  avoid accumulating operations against a potentially stale presentation.

Ordinary Rename ultimately calls this one public API, with provider dispatch in
the host, not caller-side platform branches. Do not replace the shared old
`_rename` implementation blindly: existing Move also uses it.

Before switching ordinary Rename, inventory and test every currently supported
bundled provider, including local file/folder/link-object and archive-member
renames. An archive implementation must reject existing member destinations and
serialize/check its archive commit without an unsafe replacing fallback. Keep
current case-only behavior where supported. A provider that cannot satisfy the
contract blocks that migration until resolved; do not silently remove a working
capability. External providers must implement the new method to support the new
Rename contract; document this provider compatibility requirement and migration.
Existing `move`/`prepare_move` callers are unaffected. The batch plug-in retains
its narrower regular-local-file scope.

### Execution and Results

1. Take active rows in returned visible-rank order. Before any mutation, freshly
   recheck the parent and all active sources' identity/type, size and mtime,
   candidate validity, duplicates and target absence. Exclude unchanged no-ops
   from destination-absence checks. Do not refresh/rebase file_index mid-command.
   Abort stale preflight with zero changes and ask for a fresh invocation.
2. In a cancellable `Task`, check cancellation and source identity before each
   operation, then call the public no-overwrite API. Record each returned mapping
   immediately. Stop at the first native error, cancellation or notification
   warning. An OS call already in progress cannot be forcibly interrupted.
3. No batch transaction or automatic rollback: completed renames stay completed;
   unattempted and filtered-out files remain untouched. Show a concise summary
   and a read-only QuickTable report of original name, last confirmed name and
   outcome. Distinguish unchanged, renamed, failed, unattempted and refresh warning.
4. If the invoking pane is still open at the captured folder and has not navigated
   away, request a public same-path reload through `set_path(..., callback=...)`.
   After loading, recheck location/lifetime, select confirmed destination URLs with
   `pane.select` and place the cursor on the first available one. Do not change
   pane filters, steal focus or navigate a pane the user has moved elsewhere.

Normal races are checked where possible; native no-replace protects occupied
destinations. Path-based source/ancestor prechecks do not eliminate every hostile
replacement race. Do not claim transactional or adversarial filesystem safety.

### Delivery and Test Loading

Source home: `plugins/BatchFileRenamer/batch_file_renamer/`, containing the root
command and a pure engine module. A short README covers variables, filtered
scope, ordering, safety, installation and the minimum compatible host version.
Install the outer plug-in folder under `UserSettings/Plugins/Third-party`.
Do not bundle it automatically or copy host code into its package.

Check the documented minimum host version/API requirements before opening the
command. Assign that version when the mapping and rename APIs are delivered;
older hosts receive a clear refusal, not an unsafe fallback. Standard-library
reads may capture local metadata; every mutation uses the public host API.

Keep `build._environment()` unchanged. Pure tests load the engine from its known
source path using a test-only `importlib` fixture with temporary `sys.modules`
registration and cleanup. Integration tests copy the whole package to a temporary
third-party directory and use the real loader/command registry. Host inspection
is confined to test harnesses; the installed package uses no private host API.

No saved templates, numbering state, history or plug-in background service in v1.
QuickBoard workers only compute immutable rows; the command/Task worker captures
and renames files. Qt owns widgets/models. Mutable installed state belongs under
`UserSettings`, never the Registry.

## Alternatives

- General Python expressions, transformations, presets and rollback add scope
  unrelated to this QuickBoard showcase; keep the bounded syntax and simple batch.
- Fixed or pane-only numbering does not satisfy sorting/filtering inside the
  board. Use the visible map plus independent captured file_index instead.
- A second unfiltered map, validity hook or mutable QuickBoard handle is not
  needed. Mapping remains generic; the caller defines WYSIWYG operation scope.
- Direct plug-in `os.rename` bypasses host notifications. Replacing all Move
  behavior would break overwrite workflows. Use a separate shared Rename API.
- Full invalid-name strings in row metadata/tooltips defeat the preview bound;
  preserve validity and length with a visibly shortened display instead.

## Runtime Effects

- Uninvoked: normal registration/import only; no scan, worker, timer or recurring
  subscription. No new dependency, parser process or custom plug-in worker pool.
- Capture: one fresh parent enumeration, classification and selected metadata
  reads; no recursion/content reads. Natural ordering is O(D log D) for D folder
  files; storage is O(D) occupied/index data plus O(N) candidate records.
- Preview: bounded O(N) row/map handling and O(V) generation/collision checks for
  V visible candidates, excluding template length and host sort cost. No I/O.
  The host retains its bounded active/latest-pending work and cancellation checks.
- Execution: O(V) fresh checks and at most one metadata rename per changed file,
  plus notifications. Do not suppress per-entry notifications in the plug-in.
  Reuse host dirty/queued-refresh coalescing; if insufficient, improve that host
  path without exposing private models or adding per-file scans/timers.
- Close/cancel: discard pending preview; reject stale results. Execution stops
  before the next step and reports partial completion. Release captures when the
  command and any retiring preview finish; no state persists afterward.

## Tests

These are implementation gates, not recorded passes. Use disposable files only.

- Parser: six fields, braces, dates/defaults, dotfiles/multiple suffixes, positive
  offsets on both indices, width overflow and rejection of all other expressions.
- Pure planner: natural order (`IMG_2`/`IMG_10`), fixed folder indices, active-only
  duplicates, excluded/unselected/unchanged occupied names, Windows validation,
  conservative case wording, and zero mutation for an invalid active plan.
- Bounds: 10,000 unique maximum-length Unicode/escaped names, long literal and
  repeated-field templates. Every invalid row publishes its bounded reason;
  no full invalid-string allocation or unbounded tooltip/metadata is permitted.
- QuickBoard: None bootstrap, duplicate row objects, stable mapped responses,
  both sort directions, filtering/unfiltering, empty/all-hidden maps, stale worker
  results, exact Enter revision, cancellation and migrated current consumers.
- Public rename/provider tests: destination races, case-only/same-entry versus
  hard-link aliases, files/folders/links, archive-member collisions, unsupported
  providers and unchanged Move overwrite behavior. Force notification exceptions
  after native success: exactly one mutation, a confirmed result with warnings,
  correct ordinary/batch reports and no mutation retry.
- Batch integration: real filtered/sorted QuickBoard, exact accepted targets,
  stale preflight, permission failure, cancellation after a successful prefix,
  reload/selection restoration and a pane navigated away during completion.
- Loader/package: source-path pure tests plus real temporary third-party install,
  command discovery, public-only imports/access, missing-host refusal and no
  privileged/bundled-only runtime behavior.

Focused launcher after those tests are added:

```powershell
@'
import build, os, subprocess, sys
for platform in ('windows', 'offscreen'):
    env = build._environment()
    env['QT_QPA_PLATFORM'] = platform
    env['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
    result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m', 'unittest',
        'fman_unittest.test_batch_file_renamer',
        'fman_unittest.test_ui_elements',
        'core.tests.fs.test_local', 'core.tests.fs.test_zip',
        'core.tests.commands.test___init__',
        'fman_integrationtest.test_qt.QuickBoardIT',
        'fman_integrationtest.test_qt.TableIT',
        'fman_integrationtest.test_qt.BatchFileRenamerIT',
        'fman_integrationtest.impl.plugins.test_plugin.BatchFileRenamerPluginIT',
        '-q'], env=env, timeout=300)
    if result.returncode:
        sys.exit(result.returncode)
'@ | python -B -
```

Record existing symlink-privilege skips explicitly; they do not validate link
behavior or excuse ordinary-file failures. Split slow groups rather than hide
failures if the named gate exceeds its time budget.

Opt-in performance checks belong outside normal discovery. Measure 100/1,000/
10,000 candidates, large unselected parents, mapped preview latency and peak
memory. Assert zero I/O per preview; retain the controlled 150 ms host
publication-to-paint and 50 ms Qt-heartbeat budgets. Separately measure 10,000
actual renames in a disposable folder displayed in a pane: total time, heartbeat,
notification count, scan starts/cancellations and final selection. Granular
notifications need not imply one scan per notification; prove coalescing or fix
it in the host before accepting the execution path.

Manual/release gates: keyboard-only workflow, Unicode markers/tooltips, minimum
and normal layouts at 100%/150%/200%, and separately authorized portable-host
installation/upgrade smoke. No full suite, freeze, package or file mutation runs
are authorized by this design rewrite.

The disposable [PyQt mockup](../target/mockups/batch_file_renamer_qt.py) demonstrates
appearance, date sorting and both indices using synthetic records. Its private
sort bridge and older full-batch filtering are not the production contract or
proof of public API readiness. Replace that bridge when mapping is implemented;
do not ship it. Current reference: [date-order view](../target/mockups/batch-renamer-date-ascending.png).

Next reviewers should concentrate on mapping/bootstrap convergence, exact
accepted scope, committed outcomes, provider migration, six-column payload bounds
and execution-phase refresh cost. No prior approval carries into this rewrite.

## Implementation Steps

1. Obtain a new independent design review and explicit implementation approval.
2. Implement the shared Rename/result contract and provider coverage; validate
   ordinary Rename migration separately from unchanged Move workflows.
3. Implement QuickBoard's mapping argument/result, positional projection and
   revision gating. Migrate callers, API docs, screenshots and compatibility notes.
4. Build the pure template/planner and independent plug-in package with test-only
   source loading and real third-party loader coverage.
5. Add capture, mapped preview, fresh preflight, cancellable execution and honest
   result/selection handling using public APIs only.
6. Run focused correctness, scale/execution and usability gates; update usage and
   changelog for implemented changes, then request implementation review.

## Acceptance Criteria

- One QuickBoard and six bounded variables implement the agreed workflow; no
  arbitrary execution, private plug-in API or unrelated renamer features.
- Only non-None mapped rows are renamed in visible order. Index follows the
  view; file_index and captured dates stay fixed. Filters never free occupied names.
- New Name/Valid Name/Index cannot sort/filter themselves. Returned text and map
  exactly match the completed preview; Escape and an empty active set do nothing.
- Invalid names remain inspectable within the real payload budget; shortened
  display text is never an executable target. Invalid active plans change nothing.
- Native no-replace prevents destination overwrite, and committed mutations are
  distinguishable from notification failures without guessing or retrying.
- Existing supported ordinary Rename capabilities are covered before migration;
  explicit Move replacement remains available. Provider compatibility is documented.
- Failures/cancellation preserve and accurately report completed work, without
  rollback claims. Public reload/selection handling respects pane lifetime/location.
- Third-party installation, focused tests and agreed performance/usability gates
  pass; unrun artifact/platform checks are recorded. Design review alone is not
  implementation or release approval.

## Reviewers

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Replaced accumulated drafts/history at the user's request with this
  consolidated design. Ready for a fresh independent design review; host APIs,
  plug-in implementation and release work remain unapproved.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Revisions required; the WYSIWYG mapping design is sound and the
  earlier ordering, identity, enumeration, date-default and loading concerns
  are resolved. Three P2 items: the reopen-after-invalid path silently widens
  the approved scope (M1), per-keystroke bootstrap doubles work and flickers
  (M2), and the host-side mapping/termination changes are unstated (M3).
  M4-M8 are smaller. No code changed or run.

## Design Review (2026_10_06, Fable)

Checked against the current [quick_board.py](../src/main/python/fman/impl/ui/quick_board.py)
(`get_rows(text)`, two-value result, one `LatestJobs` lane, revision-gated
acceptance), [table.py](../src/main/python/fman/impl/ui/table.py) (`project`
ranks row objects; `visible_positions` is `id(row)`-based; `sort_rows` uses
stable `sorted`/`list.sort`, so equal keys keep generator order in both
directions as the plan requires), [PlugIn.md](../PlugIn.md) (`set_path` callback
is not a loaded guarantee; `on_path_changed` fires on load completion) and the
Unreleased changelog (QuickBoard is not yet in a release).

- **M1 [P2] Reopening after an invalid acceptance widens the approved scope.**
  The user filters 12 candidates to 5, presses Enter, one row is invalid, and
  the board reopens with sort/filter reset: all 12 rows are active again. A
  second Enter after fixing the template renames 12 files although the user
  approved 5. Because QuickBoard cannot block Enter on a cross and has no
  initial sort/filter arguments, prefer: alert and stop (the user re-invokes and
  re-filters), or reopen only for pure syntax failures. If reopening stays,
  the alert must state that the scope was reset to all candidates.
- **M2 [P2] Bootstrap on every text revision is unnecessary for this consumer
  and costly for the host.** Source cells (File Index, Original Name, File
  Date) are text-independent, so the mapping from the previous revision is
  still valid. Requiring `get_rows(text, None)` per keystroke means two worker
  rounds and two 10,000-row projections per edit, and the board visibly shows
  blank derived cells before they fill. Specify: bootstrap only when no settled
  snapshot/mapping exists; otherwise call `get_rows(text, current_mapping)`
  and verify afterwards that row count and sortable/filterable cells (and
  typed `values`) equal the current snapshot; on mismatch, re-bootstrap once,
  then treat a second mismatch as a preview error. State in the contract
  whether source cells may depend on `text` at all; for a generic API they
  should not.
- **M3 [P2] The host changes needed for positional mapping are not listed.**
  `Table.project` carries row objects and `visible_positions` resolves by
  `id(row)`, so a repeated row instance cannot be mapped positionally today.
  The plan should name the host work: rank `(position, row)` through
  `project`/`sort_rows`, expose a positional visible map when `settled`, hook
  `state_changed` so a sort/filter settle with a changed map regenerates
  through the existing latest-only lane, and define loop termination (a mapped
  response whose sortable/filterable cells differ from the bootstrap is a
  preview error, never a reprojection). Also state that acceptance returns the
  map the accepted snapshot was generated from, re-verified after its final
  projection.
- **M4 [P3] API change timing.** QuickBoard exists only in Unreleased, so the
  signature change costs nothing now: amend the Unreleased changelog entry and
  PlugIn.md rather than writing migration notes, and land it before the next
  release. Alternatively an opt-in keyword (for example `mapped=True`) keeps
  the five simple use cases at `get_rows(text)` and skips their bootstrap
  round; record which was chosen and why.
- **M5 [P3] Stage the ordinary Rename migration.** Gating the whole migration
  on archive-member rename design leaves the local `Path.replace` race open
  meanwhile. Allow ordinary Rename to call `rename_no_replace` when the
  provider implements it and keep the documented current path otherwise;
  providers are migrated one at a time with their own tests.
- **M6 [P3] Post-execution selection.** `set_path(url, callback=...)`'s
  callback signals initialization, not a loaded listing. Subscribe
  `pane.on_path_changed` (it fires on same-root load completion), call
  `pane.reload()`, then `select`/`place_cursor_at` inside the callback,
  tolerating `ValueError` and unsubscribing on close or navigation.
- **M7 [P3] Wording.** A candidate that is casefold-equal only to its own
  original is the refused case-only rename; label it as such instead of
  `Conflicts ignoring case`, which should be reserved for two distinct entries.
- **M8 [P3] Test fixture placement.** The `importlib` source-path fixture is
  used by `fman_unittest.test_batch_file_renamer` and by `BatchFileRenamerIT`
  in `test_qt`; name one shared helper location so the two roots do not
  duplicate it. The launcher now includes `core.tests.fs.test_zip`
  (7za-spawning); record its expected duration with the gate result.

Resolved from the previous cycle: natural ordering with digit runs, `os.lstat`
identity, fresh `os.scandir`, explicit `%Y-%m-%d` default, provider-default
exception choices, test loading without `build._environment()` changes and
the 300 s launcher budget.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Revisions required. Agree with M1-M8. The WYSIWYG scope and the
  rename API are sound. P1 proposes a simpler QuickBoard contract that removes
  bootstrap and the contract checks (it supersedes the mechanics of M2/M3).
  P2 closes a preflight gap that can leave a partial batch. P3-P6 are smaller.
  No code changed or run.

## Design Review 2 (2026_10_06, Opus)

Checked against [quick_board.py](../src/main/python/fman/impl/ui/quick_board.py),
`TableSchema.snapshot`/`_display`/`plain_size` in
[table_data.py](../src/main/python/fman/impl/ui/table_data.py),
`LocalFileSystem._rename` and `APP_VERSION` in
[fman/\_\_init\_\_.py](../src/main/python/fman/__init__.py).

- **P1 [P2] Let the host own the source rows.** The plan sends all six cells
  every round and then checks that the caller did not change the sortable or
  filterable cells. That needs a bootstrap round, a mismatch rule and a
  termination rule. Alternative: an opt-in mapped mode in which the caller
  passes the fixed source rows once (`rows=`). `get_rows(text, mapping)` then
  returns only the derived cells for each source row, in source order. Sort and
  filter work on cells the host already has, so the first mapping exists
  before any callback. There is nothing to bootstrap, a caller cannot break
  the contract, and each update carries half the payload. Existing
  `get_rows(text)` callers stay unchanged (M4). Derived columns are exactly the
  `sortable=False, filterable=False` ones. Record this in Alternatives if it is
  rejected.
- **P2 [P2] Check target absence on disk during preflight, not against the
  captured names.** `os.scandir` lists long names only, so a target such as
  `LONGFI~1.TXT` that matches another file's 8.3 short name shows as `✓ Ready`.
  Native no-replace refuses it, but only during execution, after earlier
  renames have already happened. A per-target `os.lstat` (expecting
  `FileNotFoundError`) in the fresh preflight catches it, along with
  entries created after capture, before any mutation. State that preflight
  rejects any existing path, including aliases, while the preview checks only
  the captured long names.
- **P3 [P3] Classify folder entries without a stat per entry.** `file_index` needs
  every entry classified. On Windows, `DirEntry.is_file(follow_symlinks=False)`,
  `is_symlink()`, `is_junction()` and `stat(follow_symlinks=False).st_file_attributes`
  (reparse bit) come from the directory listing without extra calls. Use them for
  the folder, and `os.lstat` only for selected files and the parent. Otherwise
  a 100,000-entry folder costs 100,000 metadata calls before the board opens.
- **P4 [P3] Report filtered-out files.** The report lists unchanged, renamed,
  failed, unattempted and refresh-warning outcomes. Add "Excluded by filter" (count,
  or rows) so the result matches the approved scope. Also define "visible" once:
  rows that pass the filters, not rows currently scrolled into view.
- **P5 [P3] The payload margin is about 1%.** The 16,610,000-byte budget checks
  out against `snapshot`: strings are counted once by object id, typed cells add
  8 bytes, raw integers add nothing. That leaves only 167,216 bytes of headroom
  under 16 MiB, so any added
  `highlights` or `targets` breaks it. Keep the worst-case test and name it as
  the gate for later column changes. Under P1 the per-update payload roughly
  halves.
- **P6 [P3] Minor.**
  - **Host check:** combine `fman.APP_VERSION` with feature detection
    (`hasattr(fman.fs, 'rename_no_replace')`) and state how versions compare.
  - **Sort order:** the plug-in's natural key can differ from the host's
    `natural` sort on the Original Name column (for example, Unicode digits).
    Say that File Index order and the board's Name sort may disagree in such
    cases.

Verified: `QuickTableRow` has no tooltip or metadata field (only `highlights`,
`values`, `targets`). `snapshot` keeps raw cells as `values`, so typed source
cells cost 8 bytes each. `fman.APP_VERSION` is public. No code, mockup or test
was changed or run.