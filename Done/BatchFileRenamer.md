# Batch File Renamer

Status: Implemented and source-validated on 2026-10-06. The latest user decisions
add optional caller status, 100 ms text debounce and a measured 25,000-row /
16-column QuickBoard limit. Portable-artifact, CI and physical mixed-DPI checks
remain unverified. Performance observations and limitations are recorded below.

## Review Integration

- M1: invalid active plans alert and stop; no automatic reopen or scope reset.
- M2/M3: bootstrap once per dialog. Reuse the current positional mapping on text
  changes, keep old rows while computing, and reject changes to source cells or
  row count as preview errors. Rank source positions through Table projections;
  accept only the map used to generate the final re-verified snapshot.
- M4/P1: retain the user's two approved public changes (callback map and returned
  map), without `rows=` or an opt-in mode. Source fields stay fixed for the dialog;
  derived fields disable sorting/filtering. Amend the Unreleased feature docs.
- M5: stage provider adoption in the host. Ordinary Rename uses the new operation
  where supported; unimplemented providers retain the documented legacy route.
  The strict public API itself never falls back to replacement.
- M6: source testing showed ordinary reload does not emit `on_path_changed`.
  Added public `pane.reload(on_done=...)`, tied to a fresh settled scan and cancelled
  by navigation/closure; the plug-in uses it without private model access.
- M7: distinguish an ASCII case-only spelling of the same entry from conservative
  casefold conflicts; never equate separate hard-link names with an unchanged entry.
- M8: share one test-only import helper in `fman_unittest`; keep the 300-second
  focused gate and record the archive-module duration and privilege skips.
- P2/P3: live target `os.lstat` preflight catches aliases and races before any
  mutation; folder classification uses enumeration metadata, full identity reads
  only for the parent and selected files.
- P4/P5: report excluded counts; visible means passes filters, not viewport rows.
  No highlights/targets in renamer rows. The user's later simplification supersedes
  shortened invalid cells: publish the complete preview or block approval on the
  16 MiB budget. Keep the capacity boundary and oversized-refusal regressions.
- P6: numeric version comparison plus public feature detection; document that
  plug-in folder order and host Name ordering can differ on unusual Unicode names.
- Final user changes: optional caller status on the footer's right (`None` means
  hidden), 100 ms trailing debounce with Enter flush, 25,000 rows and 16 columns.
  A 50,000-row comparison was correct but approximately doubled preview latency;
  retain 25,000. No further giant rename benchmark is required.

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
- V1 accepts 1-25,000 regular files in one Windows local-drive folder,
  subject to the complete 16 MiB preview budget.
  Reject directories, mixed parents, UNC/archive/virtual sources and unreadable
  required metadata. Never silently drop an unsupported selected item.
- Reject selected symbolic links, junctions and files with multiple hard links
  during capture, before opening QuickBoard, with "Select actual files, not links
  or junctions." Sparse files and cloud placeholders remain allowed, including
  cloud-backed parent folders. Windows name-surrogate tags identify redirects;
  the reparse attribute alone does not make a file a link.
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
non-redirecting file entry for file_index; classification failures abort capture.

`file_index` starts at zero and includes hidden/unselected regular files, ignoring
pane filters. Directories and name-surrogate links do not consume an index,
but still occupy names; cloud placeholders do consume an index. Sort decimal digit runs numerically and text
case-insensitively, with exact name as the final tie-breaker: `IMG_2` precedes
`IMG_10`. Define the pure key in the plug-in, without a private host import.

Folder classification ignores link counts: Windows enumeration does not provide
them. Unselected hard-linked names therefore consume file_index positions;
selected files still receive a full identity/link check before QuickBoard opens.

Candidate generator rows retain this captured natural order. `{index}` is their
current visible rank supplied by QuickBoard, not their generator position.
Sorting/filtering changes index; file_index remains fixed. Equal sort keys retain
generator order in either direction. Neither numbering scheme changes the capture.

### QuickBoard Mapping Contract

The implemented public QuickBoard contract is:

```python
get_rows(text, mapping) -> (rows, caller_status)
text, accepted, mapping = show_quick_board(...)
```

- `mapping` is an immutable tuple indexed by generator row position. An integer
  is the zero-based visible position; `None` means filtered out. Generated
  `[A, B, C, D]` displayed as `[C, A]` yields `(1, None, 0, None)`.
- Non-None positions are unique and consecutive. Use source positions, not row
  object identity, so equal or repeated row objects are independently mapped.
- The dialog bootstraps with `get_rows(text, None)`. It returns all source
  rows with neutral derived cells. The host projects them and calls the handler
  again with the map. Bootstrap rows cannot be accepted as a finished preview.
- Mapped responses keep row count, generator order and sortable/filterable source
  cells unchanged. Only non-sortable, non-filterable derived cells may change.
  Reject observable contract violations as preview errors, not reproject loops.
  The caller is responsible for stable identity when source fields are identical.
- Sort/filter changes regenerate the mapped preview. Text edits reuse the settled
  mapping after 100 ms of inactivity; each edit restarts the single-shot timer.
  Enter flushes the delay. Hidden rows remain in responses so filters can
  reveal them again; return neutral derived cells for those rows.
- Text, mapping and completed preview belong to one revision. Enter waits for it;
  later text/sort/filter edits clear queued acceptance. Return
  `(text, True, mapping)` only for the settled approved preview. Cancellation is
  `(current_text, False, None)` without waiting for work. Zero rows map to `()`;
  all hidden rows map to a tuple of `None`, distinct from bootstrap/cancellation.
- Preserve the existing bounded worker lanes, queued Qt delivery and stale-result
  rejection. Workers receive immutable plain data; widgets/models stay on Qt.
- Every callback returns a two-item tuple `(rows, caller_status)`, including
  bootstrap. Reject rows-only results and status values other than strings or
  `None` as preview errors. Use `(rows, None)` for no right-hand message. A plain
  status
  string (up to 512 characters) publishes with its exact rows/revision, is hidden
  during newer work, and is elided with a tooltip. The host's counts/errors stay
  on the left. QuickBoard does not interpret a status as permission or validity.
- QuickBoard permits 25,000 rows and 16 columns within 16 MiB; QuickTable retains
  10,000 rows and 64 columns. An oversized preview is an error, not truncated data.

QuickBoard does not interpret names, validity markers or operation scope. No
public owner, mutable handle, second ordering map or operation/validity callback
is added. Existing callers must accept the second handler argument, return
`(rows, status)` and unpack the third result. Public examples and API documentation
describe this implemented Unreleased contract, not the earlier two-value API.

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
Validate again without reading displayed markers. The caller reports
`Rename blocked: N invalid or conflicting names.` or `N files ready to rename.`
on the right; this feedback does not bypass fresh validation.

If any active candidate is invalid, change nothing, show a concise alert and
stop. Reinvocation is a new task; no automatic reopen can widen the scope.
Empty or all-unchanged visible sets are no-ops. Otherwise
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
- Keep complete candidate text, escaping unsupported control/surrogate characters
  for display only. A name over 255 UTF-16 units is invalid, but may be displayed
  with its reason if the entire preview fits. Do not substitute shortened names.
- Bound template/specification inputs and stop generation when its conservative
  accumulated payload estimate exceeds 16 MiB. The shared schema also validates
  the actual payload. Tell the user to reduce the template/candidate set and block
  approval; never apply only the portion that fitted. This cap is not total
  Python/Qt process memory.

Preview hints use captured state. A check mark does not replace fresh preflight
or the native no-overwrite rule.

### Shared Rename API

Use Rename for a basename change in the same parent folder; use Move when the
parent changes, optionally changing the basename too. Existing explicitly
approved Move replacement behavior must remain unchanged.

Implemented public API in `fman.fs`:

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
- Reject backslashes in local source/destination URLs before metadata access or
  native rename. Canonical forward-slash URLs keep native parent interpretation
  consistent with notification/cache URLs.
- The Windows local provider uses native non-replacing rename (`os.rename`), not
  `Path.replace` or replace-existing flags. An occupied destination fails at the
  operation itself, including one created after preflight. Case-only rename of
  the same ordinary entry remains supported by the host. The later user decision
  rejects link/junction and multi-hard-link sources instead of supporting their
  rename edge cases. Sparse/cloud files remain supported.
- Reject an existing destination whose spelling is not a case-only variant of
  the source, including the source's own 8.3 alias. Do not publish a successful
  rename when Windows left the long directory-entry name unchanged.
- Native failure before commit raises its normal error. Once mutation succeeds,
  notification-listener failures become bounded `notification_warnings`, never
  an ambiguous rename-failed exception. Guard warning formatting itself and use
  a fixed bounded message if it raises. Attempt both removal/addition notification
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

Windows local Rename uses the new API. On `NotImplementedError` only, the ordinary
command retains its old `prepare_move` path for providers such as archives.
The strict API itself has no replacing fallback. Collision/permission failures
never trigger legacy fallback. Archive/other providers have not acquired a new
no-overwrite guarantee; they can adopt the public provider contract separately.
Existing `move`/`prepare_move` callers remain unchanged. The batch plug-in requires
the new operation and retains its narrower regular-local-file scope.

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
  outcome. Distinguish excluded, unchanged, renamed, failed, unattempted and
  refresh warning. Static results are paged at 10,000 rows; Enter advances and
  Escape closes reporting. Renaming has its normal cancellable progress dialog.
4. If the invoking pane is still open at the captured folder and has not navigated
  away, request `pane.reload(on_done=...)`, which completes after a fresh settled
  successful scan. Failed scans leave the callback pending until a later success;
  projecting old rows cannot complete it. Navigation/closure cancels it.
  Recheck location, select confirmed URLs with
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

Check the documented minimum source API version 0.14.0 numerically together with
public feature availability before opening the command. Released 0.14.0 builds
lacking the new APIs are unsupported; the next packaged host must include them.
Older hosts receive a clear refusal, not an unsafe fallback. Standard-library
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
- Shortening oversized invalid candidates was superseded by the user's simpler
  rule: complete preview or clear error/no application. Keep the payload cap.

## Runtime Effects

- Uninvoked: normal registration/import only; no scan, worker, timer or recurring
  subscription. No new dependency, parser process or custom plug-in worker pool.
- Capture: one fresh parent enumeration, classification and selected metadata
  reads; no recursion/content reads. Natural ordering is O(D log D) for D folder
  files; storage is O(D) occupied/index data plus O(N) candidate records.
- Preview: bounded O(N) row/map handling and O(V) generation/collision checks for
  V visible candidates, excluding template length and host sort cost. No I/O.
  The host retains bounded active/latest-pending work and cancellation checks,
  with one 100 ms debounce timer while typing. None status has no visible label.
- Execution: O(V) fresh checks and at most one metadata rename per changed file,
  plus notifications. Do not suppress per-entry notifications in the plug-in.
  Reuse host dirty/queued-refresh coalescing; if insufficient, improve that host
  path without exposing private models or adding per-file scans/timers.
- Close/cancel: discard pending preview; reject stale results. Execution stops
  before the next step and reports partial completion. Release captures when the
  command and any retiring preview finish; no state persists afterward.
- Reload: ordinary calls keep the original signal-only path. Only an explicit
  completion callback adds temporary Qt signal connections, removed after a fresh
  successful scan, navigation or closure. Each model tracks one success revision,
  updated once per successful scan; no additional scans, row loops or timers.

## Tests

Coverage targets are listed below; Validation Results distinguishes executed
checks from remaining gaps. Filesystem tests use disposable files only.

- Parser: six fields, braces, dates/defaults, dotfiles/multiple suffixes, positive
  offsets on both indices, width overflow and rejection of all other expressions.
- Pure planner: natural order (`IMG_2`/`IMG_10`), fixed folder indices, active-only
  duplicates, excluded/unselected/unchanged occupied names, Windows validation,
  conservative case wording, and zero mutation for an invalid active plan.
- Bounds: 25,000 rows/16 columns accepted, 25,001 rows/17 columns refused, and
  unchanged QuickTable limits. Complete valid long-name previews fit where
  possible; over-budget literal/repeated-field previews refuse approval.
- QuickBoard: None bootstrap, duplicate row objects, stable mapped responses,
  both sort directions, filtering/unfiltering, empty/all-hidden maps, stale worker
  results, exact Enter revision, cancellation and migrated current consumers.
- Public rename/provider tests: destination races, case-only/same-entry versus
  refused hard links/junctions, files/folders, unsupported
  providers and unchanged Move overwrite behavior. Force notification exceptions
  after native success: exactly one mutation, a confirmed result with warnings,
  correct ordinary/batch reports and no mutation retry.
- Batch integration: real filtered/sorted QuickBoard, exact accepted targets,
  stale preflight, cancellation after a successful prefix and reload/selection
  restoration. Unit tests inject permission/reporting failures, verify rejection
  before QuickBoard and allowed cloud/sparse metadata, and check navigation guards.
  Qt tests exercise reload completion and cancellation.
- Remaining coverage gaps: native symbolic-link refusal where creation privilege
  is unavailable, live cloud-provider behavior and archive-member collisions
  through ordinary Rename's legacy path. Link-renaming support is out of scope.
- Loader/package: source-path pure tests plus real temporary third-party install,
  command discovery, public-only imports/access, missing-host refusal and no
  privileged/bundled-only runtime behavior.

Focused correctness launcher:

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
        'fman_unittest.impl.plugins.test_mother_fs',
        'fman_unittest.test_portable.PluginApiCompatibilityTest',
        'core.tests.fs.test_local', 'core.tests.fs.test_zip',
        'core.tests.commands.test___init__',
        'fman_integrationtest.test_qt.QuickBoardIT',
        'fman_integrationtest.test_qt.QuickBoardMappingIT',
        'fman_integrationtest.test_qt.TableIT',
        'fman_integrationtest.test_qt.BatchFileRenamerIT',
        'fman_integrationtest.test_qt.SnapshotFilterBarIT',
        'fman_integrationtest.impl.plugins.test_plugin',
        'fman_unittest.test_generate_docs_screenshots.GenerateDocsScreenshotsTest.test_quick_board_capture_shows_arguments_without_desktop_grab',
        'fman_unittest.test_generate_docs_screenshots.GenerateDocsScreenshotsTest.test_source_outputs_include_documented_features',
        '-q'], env=env, timeout=300)
    if result.returncode:
        sys.exit(result.returncode)
'@ | python -B -
```

Record existing symlink-privilege skips explicitly; they do not validate link
behavior or excuse ordinary-file failures. Split slow groups rather than hide
failures if the named gate exceeds its time budget.

Opt-in capacity measurement compares 25,000 and 50,000 rows at 16 columns, with
typing, sorting, filtering, mapping parity, completed publication-to-paint,
heartbeat and memory. Retain the 150 ms publication target; report actual
heartbeat excursions rather than claim a universal 50 ms guarantee. The user
declined further giant rename measurements; a modest source progress/cancellation
smoke is the ongoing execution gate. Earlier measurements remain evidence below.

Manual/release gates: keyboard-only workflow, Unicode markers/tooltips, minimum
and normal layouts at 100%/150%/200%, and separately authorized portable-host
installation/upgrade smoke. No full suite, freeze or package was run.

The [PyQt mockup](../target/mockups/batch_file_renamer_qt.py) is a historical design
aid with a private bridge; it is not shipped or used to validate the public API.
Implemented reference: [source-app capture](../target/batch-file-renamer-source.png).

## Implementation Steps

1. Integrated M1-M8/P1-P6 and the user's implementation approval.
2. Implemented the shared Rename/result contract and local provider coverage,
  keeping explicit-overwrite Move unchanged.
3. Implemented QuickBoard mapping and revision gating; migrated callers, docs
  and screenshot examples.
4. Built the independent plug-in, test import fixture and third-party loader tests.
5. Added capture, preview, preflight, cancellable execution and selection restoration.
6. Ran focused correctness, performance and source checks; recorded review fixes
  and outstanding delivery/test gaps below.

## Acceptance Criteria

- One QuickBoard and six bounded variables implement the agreed workflow; no
  arbitrary execution, private plug-in API or unrelated renamer features.
- Only non-None mapped rows are renamed in visible order. Index follows the
  view; file_index and captured dates stay fixed. Filters never free occupied names.
- New Name/Valid Name/Index cannot sort/filter themselves. Returned text and map
  exactly match the completed preview; Escape and an empty active set do nothing.
- Complete previews fit the real payload budget or approval fails clearly, with
  no silent truncation or partial operation. Invalid active plans change nothing.
- Native no-replace prevents destination overwrite, and committed mutations are
  distinguishable from notification failures without guessing or retrying.
- Windows local Rename uses the new contract; unimplemented providers retain
  their existing command behavior. Explicit Move replacement remains available.
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

## Implementer

### 2026_10_06 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Implemented the independent public-only renamer, shared safe Rename
  result API, mapped QuickBoard, optional caller status and 100 ms debounce.
  Integrated M1-M8/P1-P6 with the recorded decisions and later user simplifications.
  Added public reload completion and batched selection after real source testing
  exposed those host gaps. Retained 25,000 rows / 16 columns after measuring 50,000.

## Validation Results

- The focused correctness launcher in Tests passed 431 tests per platform before
  the final typed-capacity guard adjustment: 425 passed and six expected skips
  on Windows (113.355 s) and offscreen (109.617 s). These timings include the
  archive module and its 7-Zip subprocesses; the whole repository suite was not run.
- Expected privilege skips: `test_visible_hidden_and_broken_symlinks_keep_qt`,
  `test_copy_refuses_dangling_destination_link`, `test_stat_nonexistent_symlink`,
  `test_delete_symlink_to_directory`, `test_tar_symlink_uses_7zip_behavior`, and
  `test_dangling_destination_symlink_is_retained`. Native ordinary-file collision,
  8.3-alias preflight, partial-cancellation and committed-warning tests passed.
- The full 25,000-by-16 distinct numeric-cell snapshot initially exposed the old
  object-count guard. The board-specific allowance now scales with its dimensions;
  QuickTable defaults and the 16 MiB byte cap remain unchanged. Afterward all
  40 data checks and the final 102-test data/UI/plug-in gate passed:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_unittest.test_ui_elements','fman_unittest.test_batch_file_renamer','fman_integrationtest.test_qt.QuickBoardIT','fman_integrationtest.test_qt.QuickBoardMappingIT','fman_integrationtest.test_qt.TableIT','fman_integrationtest.test_qt.BatchFileRenamerIT','fman_integrationtest.impl.plugins.test_plugin','-q'],env=env,timeout=120).returncode)"
  ```

- Final native capacity comparison, 16 columns, typing/sort/filter/clear:
  25,000 rows took 462-530 ms to completed preview (typing includes 100 ms debounce),
  8.7-33.1 ms publication-to-paint, 52.4 ms maximum heartbeat gap and 155.1 MiB
  process peak working set. At 50,000: 1,037-1,104 ms, 24.5-85.2 ms, 75.7 ms and
  226.7 MiB. Both were correct, but the slower/larger case was not adopted.
  The 150 ms publication target passed; the old universal 50 ms heartbeat target
  is not claimed. These are controlled local measurements, not arbitrary-callback
  guarantees. Run only the explicit opt-in case to reproduce:

  ```powershell
  python -B -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; code='import sys, unittest; sys.path.insert(0, \'src/performancetest/python\'); unittest.main(module=None, argv=[\'capacity\', \'fman_performancetest.legacy.QuickBoardPerformance.test_capacity_25000_and_50000\', \'-v\'])'; sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-c',code],env=env,timeout=120).returncode)"
  ```

- The two migrated existing QuickBoard performance cases also passed: 10,000 rows
  near the 16 MiB budget had 174.6 ms maximum input-to-paint including debounce,
  13.9 ms publication-to-paint and 20.9 ms heartbeat. Two hundred rapid edits
  coalesced to the final preview; close returned in 2.29 ms and ten reopen cycles
  left no additional workers or admission leases.
- A real source-app smoke installs the plug-in in disposable settings and uses
  its command, progress, native renames, results and restored selection/cursor.
  Eight files passed at DPR 1.0/1.5/2.0: execution-to-restoration 56/53/75 ms and
  heartbeat maxima 21.0/13.8/31.2 ms. All contents were verified; each run emitted
  eight added and eight removed notifications. Exact source/DPI launcher:

  ```powershell
  @'
  import build, subprocess, sys
  for scale in ('1', '1.5', '2'):
      env = build._environment()
      env.update(QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=scale, QT_AUTO_SCREEN_SCALE_FACTOR='0')
      result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m',
          'fman_integrationtest.batch_file_renamer_smoke'], env=env, timeout=120)
      if result.returncode:
          sys.exit(result.returncode)
  '@ | python -B -
  ```

- Earlier, before the user declined further giant tests, the 10,000-file source
  measurement exposed per-file selection updates: 27.695 s, 9,031 ms heartbeat.
  Batching the public selection reduced the repeat to 18.591 s and 71.35 ms;
  all 10,000 contents and restored URLs were verified. The panes made 879 scans
  for 20,000 notifications, demonstrating existing coalescing. No further large
  rename measurement was run after the user's simplification.
- The public reload callback was necessary because source inspection and a real
  smoke disproved the review's assumption that ordinary reload emits
  `on_path_changed`. The callback waits for a newer settled scan and disconnects
  on navigation/destruction. The final source workflow passed with this API.
- Documentation image regeneration and strict docs passed:

  ```powershell
  python -B -c "import sys; sys.path.insert(0, 'src/misc'); import generate_docs_screenshots as screenshots; screenshots.SOURCE_CAPTURES = ('quick-board',); sys.exit(screenshots.main(['--mode', 'source']))"
  python -B -m mkdocs build --strict --site-dir target/quickboard-docs
  ```

- Changed-file editor diagnostics are clear. The original updated review records
  are preserved. The independent package is under `plugins/BatchFileRenamer`;
  it was tested through temporary third-party installations, not installed into
  the user's normal settings. No dependency install, full suite, freeze/package,
  Git staging or commit was performed.
- Unverified: frozen portable installation/upgrade, hosted Windows CI, physical
  mixed-monitor transitions and privileged link cases. Unimplemented providers
  retain legacy Rename behavior and do not gain a no-overwrite guarantee.

### 2026_10_06 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Applied the user's stricter contract: every QuickBoard callback returns
  `(rows, status)`, with `None` for no status. Removed rows-only detection, migrated
  test/source/screenshot consumers, and updated both developer guides and the
  existing changelog entry. A malformed result is a preview error, never an
  alternate row representation. Existing historical records are preserved.

Validation:

- Six data tests passed immediately after the first edit, including empty and
  two-row results, iterator consumption/closure, malformed tuple shapes and
  invalid status types/text. The combined gate passed 30 tests without skips on
  offscreen (2.898 s) and native Windows (3.536 s). An initial run exposed a
  misindented return in the embedded plug-in fixture and omitted Qt font setup;
  both were corrected before the passing reruns. Native command below; use
  `offscreen` instead of `windows` for the other recorded run:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_unittest.test_ui_elements.QuickBoardDataTest','fman_integrationtest.test_qt.QuickBoardIT','fman_integrationtest.test_qt.QuickBoardMappingIT','fman_integrationtest.test_qt.BatchFileRenamerIT','fman_integrationtest.impl.plugins.test_plugin.QuickBoardPluginIT','fman_integrationtest.impl.plugins.test_plugin.BatchFileRenamerPluginIT','-q'],env=env,timeout=120).returncode)"
  ```

- The real source-app QuickBoard/QuickTable smoke passed at DPR 1, covering normal
  and narrow geometry, menus, preview errors and cancellation. The dedicated
  screenshot regression passed. Exact launchers:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','fman_integrationtest.quick_board_smoke'],env=env,timeout=90).returncode)"
  python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','fman_unittest.test_generate_docs_screenshots.GenerateDocsScreenshotsTest.test_quick_board_capture_shows_arguments_without_desktop_grab','-q'],env=build._environment(),timeout=90).returncode)"
  ```

- Both existing QuickBoard performance cases passed (1.441 s): maximum
  publication-to-paint 14.1 ms and heartbeat 17.6 ms; 200 edits coalesced and ten
  reopen cycles retained no workers/leases. This exercises the migrated fixture,
  not another large filesystem rename. Command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); code='import sys, unittest; sys.path.insert(0, \'src/performancetest/python\'); unittest.main(module=None, argv=[\'quickboard\', \'fman_performancetest.legacy.QuickBoardPerformance.test_large_preview_budgets\', \'fman_performancetest.legacy.QuickBoardPerformance.test_rapid_input_and_close_reopen_drain\', \'-q\'])'; sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-c',code],env=env,timeout=120).returncode)"
  ```

- `python -B -m mkdocs build --strict --site-dir target/quickboard-docs` passed;
  changed-code editor diagnostics are clear. Capacity limits and previously
  unverified delivery checks are unchanged. No full suite, freeze or package run.

## Implementation Review (2026_10_06, Opus)

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Approved with follow-ups. The renamer, the no-overwrite API and the
  mapped QuickBoard match the design. M1-M8 and P1-P6 are resolved or recorded
  as user decisions. Two P2 items: the fixed-row QuickBoard contract traps
  generic callers (K1), and the new public `pane.reload(on_done=...)` has no
  regression test (K2). K3-K6 are smaller. No code changed.

Read the plug-in ([\_\_init\_\_.py](../plugins/BatchFileRenamer/batch_file_renamer/__init__.py),
[engine.py](../plugins/BatchFileRenamer/batch_file_renamer/engine.py), README),
the diffs of [quick_board.py](../src/main/python/fman/impl/ui/quick_board.py),
`table.py`, `table_data.py`, `fman/fs.py`, `mother_fs.py`, the local provider,
ordinary `_Rename`, `widgets.py`/`view` (reload, batched select), PlugIn.md,
`docs/plugins/ui-elements.md`, CHANGELOG, and the new tests.

Confirmed:

- **Preview state:** QuickBoard bootstraps once and reuses the settled map on
  text edits. It regenerates on sort/filter changes, rejects changed source
  cells, and accepts only when the text revision, map and settled projection
  match. The debounce is flushed by Enter.
- **Mappings:** positional mappings fix duplicate row objects.
- **Rename API:** the local provider uses `os.rename`. The mother filesystem
  isolates listener failures after the commit. Ordinary Rename falls back only
  on `NotImplementedError`.
- **Plug-in:**
  - It imports only public APIs.
  - Its capture uses `DirEntry` attributes for folder entries, and `os.lstat`
    for the selected files and the parent.
  - Preflight checks every target with `os.lstat`, which catches 8.3 aliases.
  - Execution stops on cancellation, errors and refresh warnings, and reports
    excluded files.

Findings:

- **K1 [P2] Every QuickBoard caller now has a fixed row set.**
  - **What changed:** the mapping contract is not opt-in. Every caller must keep
    the row count and all sortable/filterable cells fixed for the dialog.
  - **Lost use case:** a preview whose rows depend on the text (UIElements003's
    "Saved search query" case) can no longer be built.
  - **Trap:** a text-dependent column left at the default `sortable=True` fails
    on the first keystroke with a generic "source cells must stay fixed" error.
  - **Test gap:** the six-use-case fixture in `QuickBoardPluginIT` has exactly
    such a sortable `Preview` column, but it never edits the text, so it passes.
  - **Fix:**
    - Name the column in the error and suggest
      `sortable=False, filterable=False`.
    - In the `get_rows` bullet of
      [ui-elements.md](../docs/plugins/ui-elements.md), say that the rows are
      fixed per dialog.
    - Make the fixture edit the text once.
- **K2 [P2] The new public `pane.reload(on_done=...)` has no regression test.**
  Only the source smoke covers its happy path. Add a focused `QtIT` case:
  - the callback runs once after a scan newer than the call;
  - navigation and pane closure disconnect it without calling it;
  - a scan already in flight does not satisfy it.

  Related: `DirectoryPaneWidget.reload` is now `@run_in_main_thread` for every
  caller, so a plain `pane.reload()` from a worker now blocks until Qt handles
  it. Apply the hop only when `on_done` is given, or record why blocking is safe.
- **K3 [P3] An unexpected exception can lose the report of completed renames.**
  `engine.execute` catches only `OSError`, `ValueError` and `RuntimeError`. Any
  other exception propagates, so `_Rename.report` stays `None` and earlier
  renames are not reported. For example, `mother_fs.rename_no_replace` raises
  `TypeError` after the provider has already renamed, if a third-party provider
  returns a wrong type. Catch `Exception` per entry, and keep `committed`
  accurate.
- **K4 [P3] The preview goes stale when sorting during a preview error.**
  `view_changed` returns early while `preview_error` is set. The old rows are
  re-sorted, but Index and New Name keep their previous ranks. Approval is
  blocked, so nothing wrong executes, but the Index shown is misleading. Consider
  blanking the derived cells, or noting it in the status.
- **K5 [P3] The Tests section overstates coverage.**
  - **Missing tests:** no test covers:
    - a hard-link alias destination through `rename_no_replace`;
    - link objects;
    - an archive-member collision through ordinary Rename (the legacy path);
    - a permission failure during batch execution;
    - a pane that navigates away before selection is restored.
  - **Fix:** add these tests, or mark them as not implemented under Validation
    Results.
- **K6 [P3] Document hygiene.**
  - The second Implementer heading uses `Strict Callback Result` instead of the
    contributor name.
  - A sentence in Delivery begins with lowercase "older hosts".
  - Leftover planning text should be trimmed from this completed record: "Next
    reviewers should...", "Replace that bridge when mapping is implemented", and
    Implementation Step 1.

Validation by this review (through `build._environment()`, `QT_QPA_FONTDIR` set):

- `fman_unittest.test_batch_file_renamer`, `fman_unittest.test_ui_elements`,
  `core.tests.fs.test_local`, `core.tests.commands.test___init__`,
  `fman_integrationtest.test_qt.QuickBoardIT`, `QuickBoardMappingIT`, `TableIT`,
  `BatchFileRenamerIT` and `fman_integrationtest.impl.plugins.test_plugin`:
  264 passed with 4 expected skips, both offscreen (5.6 s) and native (6.7 s).
- Not run: the source smokes, performance cases, `test_zip`, the full suite and
  freeze/package.

## Implementation Follow-Up

### 2026_10_06 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Addressed K1-K6 and the user's subsequent link policy. Links and
  junctions are rejected during Batch Renamer capture, before QuickBoard opens;
  sparse files and cloud placeholders remain allowed. Review history is unchanged
  apart from K6's requested correction to this contributor's earlier heading.

### Review Resolution

- K1: source-cell errors name the column and suggest disabling sorting/filtering.
  All six public-consumer examples now edit their text in the loader regression.
  The API guide states that source rows/order are fixed per dialog; no new mode.
- K2: plain `reload()` retains the original worker-safe signal path. Only the
  callback path dispatches to Qt and connects temporary listeners. Native tests
  cover one completion after a newer settled scan, rejection of an in-flight
  scan, navigation/closure disconnection and calls after window closure. First
  folder entry has no added work. No new Panel API or folder-entry benchmark.
- K3: per-entry `Exception` handling preserves earlier confirmed renames and
  reports post-commit progress failures without losing the committed result.
  Cancellation remains separate; unconfirmed mutations are not guessed.
- K4: retained rows after a failed preview are marked `Stale preview`, including
  after sorting. Acceptance stays blocked; a successful edit clears the warning.
- K5: added native hard-link/junction refusal, injected permission/reporting
  failures, the plug-in navigation guard and Qt reload lifecycle tests. The
  remaining archive-member collision case is explicitly untested. Link-renaming
  support was superseded by the user's refusal policy.
- K6: corrected the contributor heading and capitalization, removed obsolete
  planning directions, and kept the implementation steps factual.
- Link policy: capture rejects symbolic links, junctions and regular files with
  multiple hard links before returning any rows. The alert asks the user to select
  actual files. Shared local Rename applies the same guard and ordinary Rename
  displays it without Move fallback. Existing Move behavior is unchanged.
- Cloud policy: use the Windows name-surrogate tag bit, not the reparse attribute
  alone. Metadata-only tests cover sparse files, cloud placeholder tags and cloud
  parent folders through capture/preflight. See [Windows reparse tags](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-tags).

### Validation Results

- The first reload regression passed immediately after the threading change.
  Its lifecycle extension caught a shadowed `window` attribute; explicit
  `QWidget.window(self)` fixed it, and all four reload cases passed. The initial
  hard-link regression exposed Windows same-file alias behavior; the later user
  decision replaced link support with rejection, removing the temporary alias
  workaround. Final focused rename/load gate: 24 passed.
- Combined gate: 311 tests per platform, 307 passed and four expected symlink
  privilege skips; Windows 10.756 s, offscreen 7.314 s. Skips were
  `test_visible_hidden_and_broken_symlinks_keep_qt`,
  `test_copy_refuses_dangling_destination_link`, `test_stat_nonexistent_symlink`,
  and `test_delete_symlink_to_directory`. Exact command:

  ```powershell
  @'
  import build, os, subprocess, sys
  modules = [
      'fman_unittest.test_batch_file_renamer',
      'fman_unittest.test_ui_elements',
      'core.tests.fs.test_local',
      'core.tests.commands.test___init__',
      'fman_integrationtest.test_qt.QuickBoardIT',
      'fman_integrationtest.test_qt.QuickBoardMappingIT',
      'fman_integrationtest.test_qt.TableIT',
      'fman_integrationtest.test_qt.BatchFileRenamerIT',
      'fman_integrationtest.test_qt.SnapshotFilterBarIT',
      'fman_integrationtest.impl.plugins.test_plugin',
  ]
  for platform in ('windows', 'offscreen'):
      env = build._environment()
      env.update(QT_QPA_PLATFORM=platform, QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))
      print('Review gate:', platform, flush=True)
      result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m', 'unittest', *modules, '-q'], env=env, timeout=180)
      if result.returncode:
          sys.exit(result.returncode)
  '@ | python -B -
  ```

- Eight-file source-app smoke passed: 56 ms execution-to-restoration, 14.5 ms
  maximum heartbeat gap, eight added/eight removed notifications, five scans,
  all eight targets selected and contents verified. This is not a folder-entry
  benchmark or another giant rename test. Command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','fman_integrationtest.batch_file_renamer_smoke'],env=env,timeout=120).returncode)"
  ```

- `python -B -m mkdocs build --strict --site-dir target/quickboard-docs` passed;
  changed-source editor diagnostics are clear.
- Unverified: live OneDrive/Dropbox provider behavior, native symbolic-link
  creation/refusal without the required privilege, the legacy archive-member
  collision case, frozen packaging, hosted CI and physical mixed-monitor changes.
  Metadata-tag tests do not substitute for live cloud-provider validation.
- No full suite, new packages/environments, freeze/package, staging or commit.

## Implementation Review 2 (2026_10_06, Sol)

Revisions required for L1-L2. Reviewed against the current six-variable,
visible-row mapping contract and the later link/cloud decisions, not the
superseded fixed-index design. Existing K1-K6 resolutions are preserved.
The focused gate passes, but two additional disposable-file probes reproduce
violations of the public rename contract.

### Findings

- **L1 [P2] Native path separators bypass the same-parent restriction.** Both
  [MotherFileSystem.rename_no_replace](../src/main/python/fman/impl/plugins/mother_fs.py#L132)
  and the [local provider](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L130)
  compare parents with `fman.url.dirname`, which treats only `/` as a separator.
  The local provider subsequently interprets `\` as a Windows path separator.
  In a disposable folder, public
  `rename_no_replace(as_url(source), as_url(root) + '/nested\\moved.txt')`
  succeeded and moved `source.txt` into `root/nested/moved.txt`, rather than
  refusing a cross-parent request. This also publishes a noncanonical URL whose
  URL parent is the old folder, so destination cache/pane notifications cannot
  be relied on. Ordinary Rename's UI rejects separators, but that does not
  protect third-party callers of this public primitive. Reject noncanonical
  local paths before mutation, or normalize native separators and compare the
  resulting native parents while retaining canonical outcome/notification URLs.
  Add public-API and direct-provider regressions for backslash-containing
  destinations and assert zero mutations plus `UnsupportedOperation`; keep
  genuine same-parent file/folder renames passing.
- **L2 [P2] Warning formatting can escape after a committed rename.** The
  [notification handler](../src/main/python/fman/impl/plugins/mother_fs.py#L145)
  catches listener failures, but its subsequent `str(error)` is unguarded.
  A listener raising an exception whose `__str__` raises `RuntimeError` makes
  the public API raise after `os.rename` has already succeeded. A disposable
  probe through the actual public API and
  [engine.execute](../plugins/BatchFileRenamer/batch_file_renamer/engine.py#L275)
  made exactly one native mutation and preserved the destination bytes, but
  returned no confirmed URLs and reported `source.txt` as the current name with
  `Failed: notification error formatting failed`. This violates the promised
  confirmed mapping and accurate partial report; it is not a pre-commit failure.
  Guard warning construction itself and use a safe bounded fallback when an
  exception cannot be formatted. Add a malformed-notification-error regression
  through the public API and batch execution: return the committed destination,
  preserve later notification attempts, report a refresh warning, stop before
  the next rename and never retry the successful mutation.

### Validation Results

- Reran the complete focused correctness launcher in this document's Tests
  section, using `build._environment()`, `QT_QPA_FONTDIR`, `-B` and
  `-X faulthandler`: 447 tests per platform, 441 passed and six skips each.
  Native Windows took 113.612 s; offscreen took 111.306 s. The skips cover
  Windows/7-Zip symbolic-link creation privileges; no test failed. This is the
  named task gate, not the complete `python build.py test` suite.
- Ran `python -B -` to launch two disposable-file probes under
  `build._environment()` with `python -B -X faulthandler -c`: L1 moved a source
  into a nested parent through the public API; L2 committed once, then returned
  an inaccurate batch report after notification-error formatting failed.
  All probe files were confined to `TemporaryDirectory` and cleaned up.
- No application, plug-in, test or mockup source was changed by this review.
  No performance rerun, giant rename benchmark, source smoke, freeze/package or
  full suite was run. Existing portable/CI/live-cloud/mixed-monitor gaps remain.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Revisions required. L1-L2 reproduce a same-parent restriction bypass
  and a committed rename misreported after warning-formatting failure. The
  focused gate passes on both platforms; implementation/history are unchanged.

## Implementation Review 2 Follow-Up

### 2026_10_06 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Addressed L1-L2 with focused public/direct-provider and real batch
  regressions. Existing reviewer records are preserved.

- L1: the local provider rejects backslashes in either source or destination URL
  with `UnsupportedOperation`, before metadata access or native mutation. Public
  and direct-provider tests cover source/destination bypasses and folders; they
  assert zero native calls, notifications or filesystem changes. Genuine
  same-parent file/folder and case-only renames still pass. Move is unchanged.
- L2: warning construction is inside its own `BaseException` guard. An exception
  whose `__str__` fails produces a fixed bounded warning. Native tests verify
  confirmed source/destination URLs, exactly one mutation, retained bytes and
  later host/provider notifications. A real public-API batch test confirms the
  refresh-warning report, committed destination and unattempted next file.
- Updated the public API documentation and existing Unreleased changelog entry.

### Validation Results

- Immediately after L1: all seven no-replace tests passed. After L2: all 27
  focused rename/batch tests passed. The broader touched-module gate ran 212
  tests in 2.217 s: 208 passed, four expected Windows symlink-privilege skips
  (`test_visible_hidden_and_broken_symlinks_keep_qt`,
  `test_copy_refuses_dangling_destination_link`, `test_stat_nonexistent_symlink`,
  `test_delete_symlink_to_directory`). Commands:

  ```powershell
  python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','core.tests.fs.test_local.NoReplaceRenameTest','fman_unittest.test_batch_file_renamer','-q'],env=build._environment(),timeout=90).returncode)"
  python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.fs.test_local','core.tests.commands.test___init__','fman_unittest.impl.plugins.test_mother_fs','fman_unittest.test_batch_file_renamer','-q'],env=build._environment(),timeout=120).returncode)"
  ```

- Eight-file source smoke passed: all targets/content/selection verified,
  57 ms execution-to-restoration, 21.52 ms maximum heartbeat, eight added/eight
  removed notifications and five scans. Exact command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','fman_integrationtest.batch_file_renamer_smoke'],env=env,timeout=120).returncode)"
  ```

- `python -B -m mkdocs build --strict --site-dir target/quickboard-docs` passed;
  changed-source editor diagnostics are clear.
- No full suite, giant rename/performance rerun, freeze/package, package install,
  staging or commit. Previously recorded live-cloud, archive-collision,
  privileged-link, packaged/CI and physical mixed-monitor gaps remain unverified.

## Implementation Review 3 (2026_10_06, Fable)

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved except for N1, which needs a user decision or a
  documentation fix: ordinary Rename now refuses links, junctions and
  hard-linked files that the previous path renamed, contradicting the Core
  README. The focused gate was reproduced (450 passed, 6 skips per platform).
  N2-N6 are non-blocking. No application code changed by this review.

Read the current [engine.py](../plugins/BatchFileRenamer/batch_file_renamer/engine.py),
[\_\_init\_\_.py](../plugins/BatchFileRenamer/batch_file_renamer/__init__.py),
[quick_board.py](../src/main/python/fman/impl/ui/quick_board.py) and the
`origin/main` diffs of `table.py`, `table_data.py`, `fs.py`, `mother_fs.py`,
the local provider, Core `_Rename`, `widgets.py` (`_reload_with_callback`),
`view/__init__.py` (batched `select`), `fman/__init__.py`, CHANGELOG, README
and docs.

Confirmed:

- Preview state machine: one bootstrap per dialog; text edits reuse the settled
  mapping after the debounce and Enter flushes it; sort/filter changes bump the
  revision, cancel the lane and regenerate once the projection settles;
  acceptance needs `accept_revision == revision == preview_revision`, a settled
  table, equal generated/current mapping and no error. Source-cell violations
  name the column. Positional ranking in `Table.project`/`sort_rows` is stable
  in both directions, so the mapped round reproduces the bootstrap mapping and
  cannot loop.
- Plug-in: public-only imports; `os.lstat` identity for parent/selected files,
  `DirEntry` classification for the folder; active-only duplicates, hidden
  occupied names, chain/swap refusal, conservative casefold wording; preflight
  `os.lstat` per target; execution stops on cancel/error/warning, keeps
  committed results, reports excluded/unchanged/unattempted; restoration is
  guarded by `on_path_changed`/`on_closed` and uses `reload(on_done=...)`.
- Host: `_reload_with_callback` completes on a scan newer than the call
  (unchanged refreshes also emit `all_rows_loaded`); plain `reload()` is
  untouched. `rename_no_replace` dispatch rejects cross-filesystem/parent and
  backslash URLs before mutation; listener failures after commit become
  warnings; ordinary Rename falls back only on `NotImplementedError`.

Findings:

- **N1 [P2] Ordinary Rename regressed for link objects and hard-linked files.**
  The local `rename_no_replace` refuses symlinks, name-surrogate reparse points
  and regular files with `st_nlink > 1`, and Core `_Rename` surfaces that as
  an alert. Reproduced in a disposable folder: the new API refused `a.txt`
  (hard-linked) and a junction with "Select actual files, not links or
  junctions.", while the previous `_rename` renamed both. This contradicts
  [Core README](../src/main/resources/base/Plugins/Core/README.md#L253)
  ("standalone same-volume link renames remain supported"), the acceptance
  criterion that existing supported Rename capabilities are covered before
  migration, and the Scope statement that the link policy applies to Batch
  Renamer capture. The guard is not needed for the API's safety: `os.rename`
  renames the link object itself and still refuses an occupied destination.
  Decide one of: (a) keep the guard in the plug-in only (`capture` and
  `verify_source` already enforce it) and let the host API rename link
  objects, adding a provider test for symlink/junction/hard-link sources; or
  (b) keep the host refusal, reword the alert for ordinary Rename, update the
  Core README and [file-system-links](../docs/file-system-operations.md), and add a
  `RenameListener` regression asserting the refusal.
- **N2 [P3] Notification replication in `MotherFileSystem.rename_no_replace`.**
  The method re-implements `_on_file_removed`/`_on_file_added` by iterating the
  private `_callbacks` of four `Event`s and skipping the forwarding handlers.
  A later change to the ordinary handlers would not reach this path. Prefer an
  `Event` helper that invokes callbacks with per-callback isolation and reuse
  the existing handlers.
- **N3 [P3] Folder classification cannot see hard links.** Windows
  `DirEntry.stat()` reports `st_nlink == 0`, so hard-linked unselected files
  count as regular for `file_index` while selected ones are rejected. The
  outcome is consistent, but the README should say that `file_index` ignores
  link counts.
- **N4 [P3] QuickTable `visible_positions` semantics changed.** It is now
  positional; a caller passing the same row instance twice gets two positions
  instead of one shared visibility. This is Unreleased, so note it in the
  QuickTable line of PlugIn.md/changelog rather than as a migration.
- **N5 [P3] `supported_host()` message.** "0.14.0 or newer source API" will
  read as satisfied on the released 0.14.0 build, which lacks the APIs; say
  "a host newer than 0.14.0" or name the feature check in the alert.
- **N6 [P3] Record freshness.** Validation Results cite 447 tests; the gate
  now runs 450 (three tests added by later follow-ups).

Validation by this review, through `build._environment()` with
`QT_QPA_FONTDIR` set:

- The Tests section launcher, unchanged apart from a 400 s child timeout:
  450 tests, 444 passed, 6 expected symlink-privilege skips on both
  `QT_QPA_PLATFORM=windows` (115.2 s) and `offscreen` (112.7 s).
- One disposable-file probe (`TemporaryDirectory`, hard link via `os.link`,
  junction via `_winapi.CreateJunction`) through `LocalFileSystem` directly:
  `rename_no_replace` raised `UnsupportedOperation` for both sources; the
  previous `_rename` renamed both. Files were cleaned up.
- Not run: source smokes, performance cases, strict docs, full suite,
  freeze/package.

## Implementation Review 4 (2026_10_06, Astra)

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Revisions required for O1-O2. Both were reproduced independently of
  the passing regression gate. L1-L2 remain resolved. Ordinary Rename's link
  refusal follows the user's later instruction; N1 still needs documentation
  clarification, not an automatic restoration of link-renaming support.

### Findings

- **O1 [P2] Renaming to the source's own 8.3 alias reports a change that did not
  happen.** [LocalFileSystem.rename_no_replace](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L128)
  derives `changed` from the input strings and assumes a successful `os.rename`
  changed the directory entry. In a disposable directory on this volume,
  renaming `Long source file for rename review.txt` to its existing `LONGSO~1.TXT`
  alias returned `changed=True`, but enumeration still returned only the original
  long filename. The source was an ordinary file with one hard link, so the
  link-refusal policy does not address this case.
  - The real [RenameListener](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L796)
    path also reproduced it: no alert, a removed notification for the long name,
    an added notification for the alias and a cursor request for the alias, even
    though no directory-entry rename occurred. Bytes remained intact.
  - Reject this occupied-alias request before mutation, or implement an actual
    canonical basename change; retain genuine case-only renames. Add public API
    and ordinary-command regressions that inspect the enumerated filename and
    notifications, not only whether the destination path resolves.
  - Batch Renamer's existing target preflight rejects this alias, so the direct
    public API and ordinary Rename are the affected paths.
- **O2 [P2] A failed reload can later invoke its success callback with stale
  data.** [_reload_with_callback](../src/main/python/fman/impl/widgets.py#L144)
  accepts any later `all_rows_loaded` signal when `_scan_revision` increased and
  scanning is idle. That revision counts scan attempts, not successful scans.
  - A native Qt probe injected a scan failure after `pane.reload(on_done=...)`.
    No callback ran immediately. Changing the pane filter then projected the old
    listing and invoked `on_done` once, although no successful rescan occurred:
    scan revision `1 -> 2`, completion count `0 -> 1` after the filter change.
  - Bind completion to a successfully published scan newer than the request,
    rather than any projection after a scan attempt. Define failure cleanup or
    retry behavior and test failed scan followed by filter/sort and then a real
    successful refresh. Plain `reload()` must keep its current signal-only path.
- **N1 clarification [P3]: user documentation still implies link Rename works.**
  The [Core README](../src/main/resources/base/Plugins/Core/README.md#L252) says
  standalone same-volume link renames remain supported. Clarify that Move retains
  its existing link-object behavior while ordinary Rename now refuses links and
  junctions. The refusal itself matches the user's explicit instruction.

### Validation Results

- Reviewed the plug-in capture/parser/planner/executor, QuickBoard state machine,
  table mapping/limits, selection batching, reload completion, shared Rename and
  provider dispatch against the current task and later user decisions. No
  application, plug-in or test source was edited; only this record was appended.
- Focused gate: 341 tests per platform, 337 passed and four expected privilege
  skips. Native Windows: 11.195 s; offscreen: 7.744 s. This gate includes the
  current L1-L2 regressions but not the two new probes. Exact launcher:

  ```powershell
  @'
  import build, os, subprocess, sys
  modules = [
      'fman_unittest.test_batch_file_renamer',
      'fman_unittest.test_ui_elements',
      'fman_unittest.impl.plugins.test_mother_fs',
      'core.tests.fs.test_local',
      'core.tests.commands.test___init__',
      'fman_integrationtest.test_qt.QuickBoardIT',
      'fman_integrationtest.test_qt.QuickBoardMappingIT',
      'fman_integrationtest.test_qt.TableIT',
      'fman_integrationtest.test_qt.BatchFileRenamerIT',
      'fman_integrationtest.test_qt.SnapshotFilterBarIT',
      'fman_integrationtest.impl.plugins.test_plugin',
  ]
  for platform in ('windows', 'offscreen'):
      env = build._environment()
      env.update(QT_QPA_PLATFORM=platform, QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))
      print('Implementation review:', platform, flush=True)
      result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m', 'unittest', *modules, '-q'], env=env, timeout=180)
      if result.returncode:
          sys.exit(result.returncode)
  '@ | python -B -
  ```

- Expected skips: `test_visible_hidden_and_broken_symlinks_keep_qt`,
  `test_copy_refuses_dangling_destination_link`, `test_stat_nonexistent_symlink`
  and `test_delete_symlink_to_directory` require Windows symlink privileges.
- Disposable O1 probes ran via `python -B -` and a `build._environment()` child
  using `python -B -X faulthandler -c`: create a regular long-name file, obtain
  `GetShortPathName`, call the public API, then compare directory enumeration,
  `RenameResult` and bytes. Repeat through `RenameListener.on_name_edited` with
  only task/dialog adapters mocked, observing actual native mutation and
  notifications. Both probes reproduced O1 and cleaned their temporary files.
- Native O2 probe used a `FilterBarIT` subclass in the same child launcher, with
  the existing Qt module setup/teardown. After the settled initial listing,
  patch only `source._scanner` to raise `RuntimeError`, capture `sys.excepthook`,
  call public `DirectoryPane.reload(on_done=Mock())`, await the error, assert zero
  completions, then call `set_query('report')`. Completion incorrectly became one
  with no additional scan. The corrected probe ran cleanly; an initial probe's
  final exit statement lacked a `sys` import, not an application failure.
- Editor diagnostics for the reviewed implementation files are clear. No full
  suite, archive module, performance/large-folder benchmark, source smoke,
  live-cloud test or freeze/package was run in this review. Previously recorded
  cloud/provider, archive-collision, packaged/CI and mixed-monitor gaps remain.

## Reviews 3-4 Follow-Up

### 2026_10_06 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Addressed O1-O2 and N1/N3-N6. N2 is retained as a non-blocking
  maintainability follow-up. The user's link-refusal policy is unchanged.

### Resolution

- O1: existing destinations with a different non-case-only spelling are refused
  before native rename, including the source's own 8.3 alias. The native check
  still protects against later collisions. Public/direct-provider and real
  `RenameListener` regressions verify an alert, unchanged directory-entry names,
  preserved bytes and no native calls, notifications or cursor changes. Existing
  identical-name, case-only, folder and late-collision tests remain passing.
- O2: each listing model tracks its latest successful scan revision. Completion
  requires that it match the current scan, be newer than the request, and have
  settled into the displayed listing/projection. Failed scans leave callbacks
  pending for a successful retry; navigation/closure still cancels them. A native
  regression covers thrown errors and missing scan results, filter/sort changes
  on old rows, successful retry and exactly-once disconnection.
- Runtime: the scan-success counter adds one integer per model and one assignment
  per successful scan. It does not add directory scans, per-row work, polling,
  timers or workers. Plain `reload()` retains the signal-only path. No new
  large-folder rendering performance claim or benchmark is made.
- N1: retained host link refusal as requested by the user. Updated the Core README
  and link guide to distinguish Rename refusal from existing same-volume Move
  behavior. The native junction test now goes through `RenameListener` and checks
  the selection alert, unchanged target and absence of native rename.
- N2: deferred the optional shared `Event` dispatch refactor. Current isolation
  remains specific to committed Rename and is covered by listener-continuation
  and malformed-exception tests. Avoid changing general event failure behavior
  as part of these correctness fixes; handler duplication remains a maintenance
  concern, not claimed resolved.
- N3: documented that folder indices ignore link counts because Windows directory
  enumeration does not provide them. Added a native hard-link fixture proving
  unselected hard-linked names consume indices; selected links remain refused.
- N4: documented source-position visibility for repeated QuickTable row objects
  in the API reference and existing Unreleased changelog section.
- N5: the unsupported-host alert now explicitly says the released 0.14.0 host
  lacks the required features. A missing-API regression confirms refusal before
  capture or preview.
- N6: current results are recorded below. Earlier 447/450-test records describe
  their historical runs and are preserved, not relabeled as new validation.

### Validation Results

- Immediate focused checks passed: nine no-replace tests, five native reload
  tests, then 30 combined no-replace/batch tests. Commands:

  ```powershell
  python -B -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-B','-m','unittest','core.tests.fs.test_local.NoReplaceRenameTest','fman_unittest.test_batch_file_renamer','-q'],env=build._environment(),timeout=90).returncode)"
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); tests=['test_failed_reload_does_not_complete_on_filter_or_sort','test_plain_public_reload_keeps_worker_signal_path','test_reload_completion_waits_for_fresh_scan_once','test_reload_completion_disconnects_on_navigation','test_reload_completion_disconnects_on_window_close']; sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest',*['fman_integrationtest.test_qt.SnapshotFilterBarIT.'+name for name in tests],'-q'],env=env,timeout=90).returncode)"
  ```

- Broader gate: 399 tests per platform, 395 passed and four expected symlink
  privilege skips. Windows 11.524 s, offscreen 7.885 s. This is a task-scoped
  gate including the listing unit tests, not the full repository suite or the
  earlier archive-inclusive launcher. Exact command:

  ```powershell
  @'
  import build, os, subprocess, sys
  modules = [
      'fman_unittest.test_batch_file_renamer',
      'fman_unittest.test_ui_elements',
      'fman_unittest.test_listing',
      'fman_unittest.impl.plugins.test_mother_fs',
      'core.tests.fs.test_local',
      'core.tests.commands.test___init__',
      'fman_integrationtest.test_qt.QuickBoardIT',
      'fman_integrationtest.test_qt.QuickBoardMappingIT',
      'fman_integrationtest.test_qt.TableIT',
      'fman_integrationtest.test_qt.BatchFileRenamerIT',
      'fman_integrationtest.test_qt.SnapshotFilterBarIT',
      'fman_integrationtest.impl.plugins.test_plugin',
  ]
  for platform in ('windows', 'offscreen'):
      env = build._environment()
      env.update(QT_QPA_PLATFORM=platform, QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts'))
      print('Additional review gate:', platform, flush=True)
      result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m', 'unittest', *modules, '-q'], env=env, timeout=180)
      if result.returncode:
          sys.exit(result.returncode)
  '@ | python -B -
  ```

- Expected skips: `test_visible_hidden_and_broken_symlinks_keep_qt`,
  `test_copy_refuses_dangling_destination_link`, `test_stat_nonexistent_symlink`,
  `test_delete_symlink_to_directory`. The 8.3 alias and native junction tests ran.
- Eight-file source smoke passed: 54 ms execution-to-restoration, 19.45 ms maximum
  heartbeat, eight added/eight removed notifications, five scans, all eight files
  selected and contents verified. Command:

  ```powershell
  python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','fman_integrationtest.batch_file_renamer_smoke'],env=env,timeout=120).returncode)"
  ```

- `python -B -m mkdocs build --strict --site-dir target/quickboard-docs` passed;
  changed-source diagnostics are clear. No full suite, giant benchmark,
  freeze/package, new dependencies/environments, staging or commit. Unrelated
  user edits were retained. Live-cloud, legacy archive collision, privileged
  symbolic-link, packaged/CI and physical mixed-monitor gaps remain unverified.