# Batch File Renamer

Status: Proposed design for review. No application or plug-in implementation is
authorized by this document. Defaults below resolve unspecified details for a
small first version and may be revised during review.

## Task

Rename a captured group of files using one readable template and a live
QuickBoard preview. Make this a public-API-only third-party plug-in and a simple
showcase of QuickBoard, not a comprehensive renaming toolbox.

The essential addition beyond template variables is collision protection:
invalid or conflicting targets must never cause an overwrite. Implement this
as an application-wide public rename capability, shared by ordinary Rename and
third-party plug-ins, not a Batch File Renamer bypass.

## Scope

- One Command Center command, **Batch File Renamer**, ID `batch_file_renamer`.
  No default shortcut. Existing single-file Rename keeps its UI and workflow but
  adopts the shared no-overwrite rename operation described below.
- Use selected files, falling back to the cursor file via
  `DirectoryPaneCommand.get_chosen_files()`. Capture the set once; do not infer
  operation targets from filtered QuickBoard rows or later pane selection.
- Windows local-drive `file://` regular files in one parent folder, at most
  10,000. Refuse an empty set, mixed parents, directories, archive/virtual URLs,
  UNC locations, source reparse points and unavailable metadata. No recursion.
  Never silently drop unsupported selected entries.
- Rename basenames only, with an owner-free, modal QuickBoard. No Panel, extra
  operation buttons, new QuickBoard options, Qt imports or host-private imports.
- Five variables, date formatting, zero-based indices, index padding and an
  optional positive integer offset. No arbitrary Python, general expression
  evaluation, subtraction, regex replacement, case transformations, presets,
  separate counter controls, configurable step, undo or background service.
- No overwrites, swaps, chains through occupied names, case-only renames or
  temporary-name staging in v1. Exact unchanged names are skipped.
- Installable independently under `UserSettings/Plugins/Third-party`; not
  automatically bundled. Its minimum host version must include the current
  QuickBoard API and the proposed shared public rename API below. Host changes
  belong to the application; the plug-in must work without privileged access.

## Design

### Template Language

Enter the template directly, without an `f` prefix or surrounding quotes.
Python-like replacement fields and format specifications are supported, but
this is deliberately not Python execution.

| Variable         | Meaning                                  | Default Format |
| ---------------- | ---------------------------------------- | -------------- |
| `{current_date}` | Local date/time captured at invocation   | `YYYY-MM-DD`   |
| `{file_date}`    | File last-modified date/time, local time | `YYYY-MM-DD`   |
| `{index}`        | Stable file number, starting at 0        | Decimal        |
| `{name}`         | Original name without its final suffix   | Unchanged text |
| `{ext}`          | Final suffix including its leading dot   | Unchanged text |

Decisions:

- **Current Date** is captured once, not on every keystroke or file. Crossing
  midnight while the board is open cannot change the accepted preview.
- **File Date** means last modification time, not creation time, EXIF date or
  a date inferred from the name. This is an explicit default to confirm in review.
  Capture date values and the invocation's system time-zone interpretation once.
- **File Index** starts at 0 and uses a fixed sort by
  `(original_name.casefold(), original_name)`.
  This is case-insensitive lexical name order, not current pane size/date order
  or natural-number ordering. Sorting/filtering the preview never renumbers files.
  The preview's Index column always shows this base index, even when a template
  adds an offset to its rendered value.
- Split names with `os.path.splitext`: `archive.tar.gz` becomes `archive.tar`
  plus `.gz`; `.gitignore` and extensionless files have an empty extension.
  Including the dot makes `{name}{ext}` an identity template for every file.
  Extension preservation is explicit: omitting `{ext}` removes the extension.
- Date fields accept `%Y`, `%y`, `%m`, `%d`, `%H`, `%M`, `%S` and `%%`, with
  bounded literal separators. Default to `%Y-%m-%d`. Reject unsupported directives
  rather than relying on platform-dependent `strftime` behavior.
- Index accepts no specification, `d`, a decimal width with `d`, or zero-padded
  width such as `03d`; width must be 1-32. Prefer `{index:03d}` in examples.
  Name/extension accept no formatting or conversion in v1.
- The only arithmetic form is `index + positive_integer`, optionally enclosed
  in one pair of parentheses. Both `{index + 5:03d}` and `{(index + 5):03d}`
  produce `005` for the first file; `{(index + 1):03d}` starts at `001`.
  Permit spaces around the tokens, but no line breaks. The offset is an unsigned
  ASCII decimal literal with a value greater than zero; bound its digit count
  by the existing template/name limits before conversion. No signed literal,
  `index + 0`, subtraction, other operator, repeated addition, reversed operands,
  nested parentheses, variables in the offset or arbitrary expression is allowed.
- `{{` and `}}` produce literal braces. Unknown/empty fields, positional fields,
  attribute/index access, nested replacement fields, conversions such as `!r`,
  expressions other than the single positive index offset, calls and unmatched
  braces are syntax errors. No aliases or implicit filename sanitization.

Use the standard-library `string.Formatter.parse()` to parse once per preview,
then validate an exact field/specification allowlist. Recognize the small index
offset grammar directly and normalize it to a base-index field plus one constant;
add that constant before formatting. Do not enable an expression evaluator.
Render only captured strings, integers and date values. Never use `eval`, `exec`,
generated f-string source, or unrestricted field lookup. Bound specification
expansion before formatting; do not allow huge widths to allocate huge strings.

| Template                                | Example Result             |
| --------------------------------------- | -------------------------- |
| `{name}{ext}`                           | `report.txt`               |
| `{index:03d}_{name}{ext}`               | `000_report.txt`           |
| `{(index + 1):03d}_{name}{ext}`         | `001_report.txt`           |
| `{(index + 5):03d}_{name}{ext}`         | `005_report.txt`           |
| `{current_date}_{name}{ext}`            | `2026-10-06_report.txt`    |
| `{file_date:%Y%m%d}_{index:03d}{ext}`   | `20260930_000.txt`         |
| `Trip_{index:03d}{ext}`                 | `Trip_000.txt`             |

Examples assume `report.txt`, index 0, current date 2026-10-06 and file date
2026-09-30. No additional variable is essential for v1; parent-folder names,
creation/EXIF dates and text transformations can be considered separately later.

### QuickBoard Workflow

1. Capture chosen URLs on the command worker, then prepare immutable file
   records in a cancellable `Task`: original URL/name, split name/extension,
   index, file identity, size and modification timestamp. Enumerate occupied
   names in the parent once for the preview, including hidden files/directories.
2. Open `show_quick_board` with `text='{name}{ext}'`, title **Batch File Renamer**
   and a short summary containing the captured count and variable examples.
  Example summary: `12 files | {name}{ext} | {(index + 1):03d} | {file_date:%Y%m%d} | {current_date}`.
   QuickBoard's existing elision/tooltip handles the summary; no syntax-help API.
3. Show four columns: **Index** (numeric), **Original Name** (file_name),
  **New Name** (file_name), **Valid Name** (text). Prefix advisory results with
  `V` or `X` and a reason: `V - Ready`, `V - Unchanged`, `X - Duplicate target`,
  `X - Target exists`, or `X - Invalid name: reserved name`. Typed sorting and
  filtering do not change the captured operation set, indices or validation.
4. `get_rows(text)` is pure, bounded text-to-rows work over those records and the
   captured occupied-name set. No filesystem access, setting writes or mutation
   on keystrokes. Use full rows, not a sample, within QuickBoard's 16 MiB budget.
5. Syntax/specification errors raise `ValueError` for QuickBoard's error footer.
  Per-file target problems remain visible in the Valid Name column. QuickBoard
  displays supplied text; it does not compute filename validity or disable
  Enter because a row contains `X`.
6. Escape/window close returns without changes. Enter returns the exact template;
   the command rebuilds the full rename plan from the same captured records and
   checks every row. If any row is invalid, perform no mutation, show a concise
   alert and reopen QuickBoard with that template. Do not apply only visible rows.
7. If all rows are unchanged, report `No files need renaming` and stop. Otherwise
   start a cancellable Task for fresh preflight and execution. The preview is
   the approval step; do not add another routine confirmation dialog.

The board remains modal, frameless and buttonless. It needs no public owner or
controller subclass. Plug-in unload alone does not cancel an already active
blocking command; it may finish its normal dialog/task lifecycle. No new unload
service or recurring lifetime monitor is introduced by this plug-in.

### Advisory Preview Validation

The plug-in's pure rename planner supplies Valid Name hints through ordinary
public `QuickTableRow` cells. QuickBoard remains generic; no new host UI API is
needed to display these results.

- Recheck all proposed names on each template edit, including duplicate targets
  across the entire batch and collisions with the captured parent entries.
  Mark every member of a duplicate-target group `X`, not just the later row.
- Show concrete reasons for invalid Windows names, occupied targets and v1
  restrictions such as case-only changes. Exact unchanged names are
  `V - Unchanged` unless another candidate collides with them; they remain no-ops.
- Symbols always have explanatory text, with existing cell tooltips for elided
  reasons. Filtering out an `X` row cannot make the full batch valid.
- `V` means only that the candidate passes checks against captured state, not
  that a future rename must succeed. No filesystem scans or monitoring run on
  keystrokes; external changes can make the displayed hints stale.
- After Enter, rebuild and validate the full plan, not the displayed V/X strings.
  Fresh preflight and native no-overwrite enforcement remain mandatory. Preview
  hints improve usability; they do not replace either safety layer.

### Validation and Rename Safety

- Reject empty names, `.`/`..`, separators, absolute paths, drive/stream syntax,
  NUL/control characters, Windows reserved names, trailing spaces/dots and names
  exceeding 255 UTF-16 units. Preserve other characters and case exactly; never
  trim or repair names silently. Validate the resulting full destination path.
- Use conservative case-insensitive target comparison even in case-sensitive
  directories. Reject duplicate target names, occupied destinations belonging
  to any other entry (including selected entries and directories), and case-only
  changes. Only exact original-name equality is an unchanged no-op. Do not use
  `samefile` alone to treat a different hard-link name as an unchanged entry.
- Before the first mutation, recheck every source's identity/type, size and
  modification time against capture, the parent identity, and destination
  absence. Read live metadata, not cached `fs.query` results. If anything changed,
  abort the batch without changes and ask the user to restart with fresh inputs.
- Immediately before each rename, check cancellation and source identity again.
  The mutation itself must refuse an occupied destination atomically; a prior
  existence check is not sufficient. Stop at the first execution error.
- No whole-batch atomicity or automatic rollback is promised. On failure or
  cancellation, already-renamed files remain renamed and unattempted files stay
  unchanged. Show a concise summary and a read-only QuickTable report with
  original name, last confirmed name and result; never infer success from a
  progress counter or retry a mutation after an ambiguous failure.
- Ordinary concurrent changes are detected where checked, and destinations
  cannot be overwritten. Path-based identity prechecks do not eliminate every
  source/ancestor time-of-check/time-of-use race; hostile directory replacement
  is outside v1's guarantee. Do not claim transactional or adversarial safety.

### Shared Application Rename API

The existing public [fman.fs.move](../src/main/python/fman/fs.py) is unsuitable
for the no-overwrite contract: the Windows local provider's file rename uses
`Path.replace`, which can overwrite a destination created after preflight. See
[LocalFileSystem](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py).
Ordinary [Rename](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)
checks destination existence but then uses `prepare_move`, exposing it to the
same race. Correct that path in the host as well; do not hide the fix in this
plug-in or let the plug-in call Core's private `_Rename` task.

Propose one additive, application-wide public function,
`fman.fs.rename_no_replace(src_url, dst_url)`, documented for all third-party
consumers in [PlugIn.md](../PlugIn.md) before use:

- Same-parent rename only; never fall back to copy/delete, replacement or merge.
  The first provider implementation is Windows local storage. The common API
  dispatches to capable providers; unsupported providers raise
  `UnsupportedOperation`, with no private or replacing fallback.
- Destination existence is rejected by the native operation, not just a Python
  check. On Windows use the non-replacing rename operation (`os.rename`), not
  `Path.replace`, `os.replace` or replace-existing flags.
- Migrate ordinary Rename for supported providers to this public operation.
  Keep progress, error reporting and cursor placement in its existing command;
  preflight can give a friendly error but cannot substitute for native refusal.
  Review provider compatibility before migration and report unsupported rename
  explicitly instead of claiming an unverified no-overwrite guarantee.
- The host API is not restricted to the plug-in's file-only subset: preserve
  ordinary file/folder rename and existing supported link-object behavior.
  Keep ordinary case-only rename when the native operation targets the same
  directory entry; never use `samefile` alone to permit replacement of another
  hard-link entry. Test this independently from the batch plug-in, which still
  refuses case-only changes, directories and source reparse points in v1.
- Keep rename-without-replacement distinct from an explicitly approved replacing
  Move. Do not silently change `move` or `prepare_move` semantics application-wide
  or remove users' overwrite choices. Those broader transfer policies need their
  own review; this shared operation closes the ordinary Rename race first.
- Successful renames publish the existing removed/added notifications so pane
  refresh and caches remain coherent. Separate a committed rename from a later
  notification failure; report the committed mapping without retrying the rename.
- Add native regression coverage for an already occupied destination and one
  created between validation and mutation, through both the public API and the
  ordinary Rename command; destination contents must survive.

This host work is an independently verifiable application prerequisite, not an
implemented API or plug-in special case. The Batch File Renamer consumes the
same documented operation as any separately installed third-party plug-in and
must refuse an older host missing it rather than fall back to `move`.

### Ownership and Persistence

- Proposed source home: `plugins/BatchFileRenamer/batch_file_renamer/`, with a
  root command module and one pure template/planning module; a short README
  documents installation, variables, ordering, extension handling and limits.
- The plug-in imports only public `fman`, `fman.fs`, `fman.url`, `fman.ui` and
  standard-library APIs. Host internals own mutation dispatch and notifications.
  No `fman.impl`, Core imports, private attributes, private `fs.query` method
  names, monkeypatches or bundled-only exceptions. Standard-library reads may
  capture local metadata; all file mutations go through the public host API,
  not direct `os.rename`/Win32 calls from the plug-in. Test installation outside
  the host resource tree so accidental private coupling cannot pass as support.
- Command/Task workers capture and operate on files; QuickBoard workers render
  immutable preview data; Qt owns widgets/models. No custom threads, timers,
  parser processes or direct Qt objects are needed in the plug-in.
- No saved templates, history, counter state or settings in v1. Every invocation
  starts with the identity template. Installation lives under `UserSettings`;
  no Registry writes or new dependencies.

## Alternatives

- Full Python f-strings: rejected because general expressions and arbitrary code
  are unnecessary. Allow only the user's requested positive constant added to
  the zero-based index, without an evaluator or configurable counter controls.
- Extension without its dot: familiar in `{name}.{ext}`, but adds a trailing dot
  for extensionless files. Use `{name}{ext}` consistently instead.
- Creation/EXIF date as File Date: less portable/available and adds metadata I/O;
  last-modified time is the explicit v1 interpretation.
- Index tied to live preview order: rejected because filtering/sorting would
  silently change operation results. Capture deterministic indices once.
- Two-stage rename graphs and rollback: support swaps/case-only changes, but add
  temporary-name recovery and partial-failure complexity. Refuse these in v1.
- Direct `os.rename` from the plug-in: avoids overwrites on Windows but bypasses
  host filesystem notifications/caches. Use the shared public host primitive,
  also adopted by ordinary Rename; a plug-in-specific bypass is rejected.
- Change all Move operations to refuse replacement: not selected here because
  explicit overwrite is a separate, existing workflow. Add a clearly named
  no-replacement operation and migrate callers that require that guarantee.
- Expand QuickBoard with validity callbacks, operation buttons or variable
  selectors: rejected. Show per-file problems in rows and validate after return.

## Runtime Effects

- Disabled/uninvoked: no scans, metadata reads, jobs, timers, settings writes or
  recurring subscriptions; only normal command registration/import overhead.
- Opening: one parent-name enumeration plus metadata for the captured files;
  no recursion/content reads. Work is cancellable between entries. Sorting costs
  O(N log N) once; retain O(N) file records and O(D) occupied names for D entries
  in the parent, which can be larger than the selected set.
- Editing: parse once, render/validate N names and detect duplicates in O(N),
  with no I/O. Respect the host's 4,096-unit input, 10,000-row and 16 MiB limits;
  bound generated names before building large row snapshots. The optional
  offset is one bounded integer addition per rendered index field.
- Acceptance: O(N) fresh preflight and at most one same-folder rename per changed
  file, plus host notifications. No content copies and no extra worker pool.
- Cancellation: Escape prevents mutation; Task cancellation stops before the
  next filesystem step. A single in-progress OS call cannot be forcibly stopped.
  Partial completion is reported, not rolled back. Snapshot memory is released
  when the command and any retiring QuickBoard preview finish.

## Tests

Planned tests below do not exist or pass merely because they are listed here.
Reuse the existing Qt and plug-in-loader test modules; add one focused pure
plug-in test module, `fman_unittest.test_batch_file_renamer`.

- Template units: all five fields/defaults, the examples above, zero padding,
  fixed current date, stable zero-based indices, local modified-date formatting, braces,
  extensionless files, dotfiles and multi-dot names. At base index 0 assert
  `{index:03d}` -> `000`, `{(index + 1):03d}` -> `001`,
  `{(index + 5):03d}` -> `005`, and the equivalent unparenthesized forms.
  Cover allowed spacing and reject `index + 0`, signed/negative literals,
  subtraction, multiplication, repeated addition, reversed operands, nested
  parentheses and excessive offset digits. Reject all other expressions, field
  traversal, unknown variables, conversions, nested/oversized specs and bad braces.
- Plan units: invalid Windows names, Unicode/UTF-16 length, duplicate outputs,
  occupied targets, unchanged names, case-only changes, chains/swaps, hard-link
  aliases, deterministic order and preview filtering not reducing operation scope.
  Assert V/X plus reasons, all duplicate-group members flagged, and collisions
  against unchanged/unselected entries. Preview and acceptance share validation
  logic without inspecting the rendered status strings.
- Native host tests in `core.tests.fs.test_local`: no-overwrite races, ordinary
  rename and notification success, unsupported provider/cross-parent rejection,
  long paths and a committed rename followed by notification failure. Cover
  files, folders, supported link objects, case-only same-entry rename and hard-link
  destination aliases without extending the batch plug-in's supported inputs.
- Ordinary Rename tests in `core.tests.commands.test___init__`: use the shared
  public operation, preserve cursor/progress behavior, and reject a destination
  created after the friendly precheck. Existing explicit-overwrite Move tests
  must still pass; unsupported providers must not fall back to replacement.
- `BatchFileRenamerIT` in `fman_integrationtest.test_qt`: real QuickBoard updates,
  syntax errors, Valid Name hints, Escape/no-op, invalid acceptance/reopen,
  filtered acceptance still covering all captured files, and slow preview/close.
  Invalid-to-valid edits update the hints. Hiding an X row still prevents batch
  execution, and V rows are still subject to fresh checks after external changes.
- `BatchFileRenamerPluginIT` in the existing loader tests: install from a
  disposable third-party directory, public-only imports, command discovery,
  unavailable-host refusal and source-app invocation without a UI controller.
  Audit source imports/attribute access for host-private dependencies, exercise
  mutations through only the documented public operation, and ensure the package
  includes no host code or direct native mutation workaround.
- Disposable filesystem integration: source modified/replaced/removed while
  composing, target introduced after preflight, permission denial and cancellation
  after a completed prefix. Assert exact original/destination bytes and every
  report mapping; never test mutations against user files.

Focused correctness launcher after implementation adds those tests:

```powershell
@'
import build, os, subprocess, sys
for platform in ('windows', 'offscreen'):
    env = build._environment()
    env['QT_QPA_PLATFORM'] = platform
    env['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
    result = subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m', 'unittest',
        'fman_unittest.test_batch_file_renamer',
        'core.tests.fs.test_local',
        'core.tests.commands.test___init__',
        'fman_integrationtest.test_qt.BatchFileRenamerIT',
        'fman_integrationtest.impl.plugins.test_plugin.BatchFileRenamerPluginIT',
        '-q'], env=env, timeout=120)
    if result.returncode:
        sys.exit(result.returncode)
'@ | python -B -
```

Performance: use an opt-in case in the existing performance test area, outside
normal discovery. Measure 100/1,000/10,000 selected records and a large unselected
parent separately: capture time/memory, callback time, input-to-paint and Qt
heartbeat. Assert zero filesystem calls per preview; retain QuickBoard's 150 ms
publication-to-paint and 50 ms controlled-heartbeat gates. Report callback cost
separately rather than promising a filesystem-independent opening time.

Manual/release checks: keyboard-only workflow, full long-name tooltips, normal
and minimum QuickBoard sizes at 100%/150%/200%, docs screenshot using real sample
rows, and separately authorized portable-host installation/upgrade smoke.
Do not run a full suite, freeze, package or mutate files during this design task.

### PyQt Design Preview

A disposable local mockup is available in
[batch_file_renamer_qt.py](../target/mockups/batch_file_renamer_qt.py). It uses the
real frameless QuickBoard and application theme with eight synthetic file records
and one simulated occupied target, `Trip_007.JPG`. It does not install a plug-in,
inspect user files or execute any rename operation.

```powershell
python -B -X faulthandler target/mockups/batch_file_renamer_qt.py --capture
python -B target/mockups/batch_file_renamer_qt.py --template 'Trip_{(index + 5):03d}{ext}'
```

The capture command passed on 2026-10-06: five variables, zero-based offsets,
rejected expressions/specifications, identity/dotfile/extensionless examples,
duplicate and occupied targets, and actual Qt rows/error feedback. Six nonblank
images cover normal and minimum geometry; Escape closes without mutations.
`os.rename` and `os.replace` are forbidden during the mockup dialog. Screenshots
include [positive offset](../target/mockups/batch-renamer-offset.png) and
[duplicate targets](../target/mockups/batch-renamer-collisions.png).

These ignored `target` artifacts are design aids, not delivered application
code or evidence for live filesystem safety. The sample producer uses public
`fman.ui` records and `show_quick_board`; theme setup, column resizing and capture
inspection are host-test-harness work only. Initial screenshot column widths
are adjusted as a user could resize them; no new public sizing option is assumed.
The shared application rename prerequisite and installable plug-in remain
unimplemented and require separate approval after design review.

## Implementation Steps

1. Review/confirm variable names, modified-time meaning, dot-inclusive extension,
  fixed lexical ordering and v1 exclusions. Index zero and positive-addition-only
  offsets are user decisions; approve implementation separately.
2. Design/review and independently validate the application-wide public rename
  operation and ordinary Rename migration first, including provider/case-only
  compatibility. Publish the contract; preserve explicit Move overwrite semantics.
3. Implement the pure bounded parser and rename-plan validation with unit tests.
4. Add command capture and QuickBoard composition using immutable data, plus
   public-only loader and Qt tests. No filesystem mutations in the preview.
5. Add fresh preflight, cancellable no-overwrite execution and honest partial
   outcome reporting; test races and failure paths with disposable files.
6. Measure scale, capture the QuickBoard showcase, document usage/installation
   and host prerequisite, and update the changelog only after implementation.

## Acceptance Criteria

- One QuickBoard and five documented variables cover the requested workflow;
  no additional controls or Python-code execution are introduced.
- The first file has index 0. Only a positive decimal integer may be added to
  `index`, with optional parentheses; formatting follows that addition. Sorting
  or filtering the board changes neither base indices nor offset results.
- Default `{name}{ext}` preserves all supported filenames; indices and date
  values remain stable across typing, sorting, filtering and midnight changes.
- Every captured file has a preview row; hidden preview rows remain in scope.
  Escape changes nothing, and invalid plans perform no partial subset operation.
- Valid Name shows V/X and a reason from the captured full-batch validation.
  The display is advisory; live preflight and OS no-overwrite checks remain
  independent and mandatory even when every visible row says V.
- Valid same-folder batches use the public no-overwrite primitive. Existing or
  newly appearing destinations are never replaced, including on error paths.
- Ordinary Rename and third-party callers share the application-level public
  primitive for supported providers; no safety workaround is private to the
  plug-in. Explicit-overwrite Move behavior is not silently redefined.
- Stale preflight aborts before mutations; later failures/cancellation preserve
  completed work and accurately report completed, unchanged and unattempted files.
- The plug-in is independently installable and uses no Qt/Core/host-private
  imports. It refuses missing host support without an unsafe fallback.
- Focused tests and agreed performance/usability checks pass; any unrun portable
  or platform checks are explicitly recorded. Design completion is not release
  approval or evidence that this feature has been implemented.

## Reviewers

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Proposed a small QuickBoard-based third-party renamer with five
  allowlisted variables, stable capture/indexing and explicit no-overwrite safety.
  Identified the current replacing move path and a minimal additive host API
  prerequisite. Ready for design review; no implementation authorized.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Applied the user's zero-based index and positive-integer-addition-only
  syntax decisions. Expanded no-overwrite renaming into a shared application API
  and ordinary Rename migration, distinct from explicit replacing Move behavior.
  Reinforced independent third-party packaging and strictly public host API use.
  Preserved the initial design record; no implementation performed or authorized.

### 2026_10_06 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Specified advisory Valid Name hints with V/X and reasons through
  QuickBoard's existing public row API, independent of live/native safety checks.
  User requested a disposable PyQt design mockup; application and plug-in
  implementation remain unapproved, with no file renames in the mockup.