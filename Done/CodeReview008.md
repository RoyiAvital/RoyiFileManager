# Code Review 008: Edge Cases, Safety and Responsiveness

Status: Completed 2026-10-27. Findings F01-F12, F14 and F15 recorded 2026-10-26;
follow-up comments R05-R06 recorded 2026-10-27. The user approved implementation
of F01-F12 and F14 on 2026-10-27 (see Decisions); F15 is not implemented.

Split from [CodeReview007](../Done/CodeReview007.md) on 2026-10-27 by user request.
F13 (pane rescans during Copy/Move/Delete) and its review comments R01-R04 and
Q01 moved there for implementation. Finding IDs are kept for traceability.

## Task

Review the whole application for edge-case bugs, unnecessarily protective
guards and redundant work. Identify ways to make operations smoother and faster
without weakening correctness. Record findings and wait for other contributors
before selecting implementation work.

## Scope

- Include lifecycle, filesystem and archive operations, persistence, pane models,
  search, previews and bundled plug-ins. Broad review, not an exhaustive audit
  of every file or release certification.
- Do not run tests: no existing unit, integration or regression targets, test
  discovery, full suite, build, freeze or performance-catalog commands.
- Only run small generated probes for new, specific speculations. Use temporary
  fixtures and mocked boundaries, never user data or private settings.
- No fixes, guard removals, package installations or environment creation.
  Preserve public APIs, Windows portability, Qt ownership, cancellation,
  stale-result rejection and optional features' disabled/no-op behavior.

## Design

This is the canonical review record. Contributors append independently supported
findings with the next unused ID and their own reviewer metadata. Confirmations,
challenges and later dispositions reference existing IDs; preserve earlier
evidence and provenance rather than rewriting history.

Each finding distinguishes the observed failure/cost, reproduction, limitations
and proposed next decision. A repeated guard is not automatically redundant;
establish which contract it protects before recommending removal.

Existing backlog ownership remains in [CodeReview099](../Plan/CodeReview099.md): F02
reconfirms C06, F03 refines C11, and F06 adds evidence for FO02. These are not
three newly discovered issues or new implementation approvals. Retain that
backlog's dispositions and release gates.

Future fixes must use the existing task/provider and persistence boundaries.
Qt objects stay on Qt; workers receive immutable plain data and reject stale
results. No new cache, worker, timer or persistence mechanism is selected here.

## Alternatives

- Run the existing tests: excluded by the user; existing passes do not address
  these additional speculations.
- Apply obvious fixes immediately: rejected; await independent contributions
  and user selection before implementation.
- Remove all repeated checks or add caches/workers preemptively: rejected;
  require correctness evidence and measured costs, including invalidation,
  retained memory, cancellation and disabled behavior.
- Duplicate old backlog work as new findings: instead record reconfirmations
  and new evidence with links to canonical ownership.

## Runtime Effects

Documentation and index changes have no application startup, steady-state CPU,
memory, I/O, thread/process, cancellation or disabled-feature effects. Earlier
generated probes used disposable fixtures, synthetic listings and mocked UI
boundaries. Their local timings are not end-to-end performance measurements.
Runtime effects of proposed remedies remain unapproved and unmeasured.

## Tests

Tests were prohibited during the review phase. The user's implementation approval
on 2026-10-27 replaced that rule with focused regression tests per finding
(see Validation Results); the full suite was not run.

Document validation is limited to required sections, real relative links, unique
IDs, Pending index placement and whitespace. Full UI interactions, real
second-volume transfers, packaging and release gates remain unverified. These
checks are not waived or represented as passed.

## Findings

### F01 - P1: Copy-Based Move Deletes a Source Changed During Copy

- Owner: [MoveByCopying](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L500).
- Failure: copying is followed by source deletion without revalidating the
  source. Destination-publication checks do not establish source consistency.
- Probe: pass a real temporary 2 MiB file through the existing composite. After
  its first 1 MiB read, a reader wrapper rewrites the source from all `A` to all
  `B`. The destination contains 1 MiB of `A` followed by 1 MiB of `B`, and the
  source is deleted. A separate edit after publication was also deleted without
  reaching the destination.
- Limit: invoked the composite directly on one volume; not a real second-volume
  or network transfer, but demonstrates the fallback's failure sequencing.
- Next decision: retain a changed source and report partial completion. Review
  consistency across reading, publication and deletion; metadata checks alone
  must not be claimed to fully protect against concurrent writers.

### F02 - P2: Copy-Based Move Loses Cancellation and Progress

- Owner: [MoveByCopying.__call__](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L507).
- Failure: direct provider copy execution creates subtasks without the parent
  task's dialog. They do not observe its cancellation or report its progress;
  source deletion follows without checking parent cancellation.
- Probe: set parent cancellation during copying. The copy subtask sees `False`,
  copies all 140,000 bytes and deletes the source. Parent cancellation remains
  `True` and parent progress remains zero.
- Limit: direct composite invocation, not physical second-volume coverage or
  cancellation during blocked OS I/O.
- Next decision: preserve context through existing task composition and define
  cancellation after publication. Reconfirms C06 in
  [CodeReview099](../Plan/CodeReview099.md), without changing its approval status.

### F03 - P2: Malformed Persisted Geometry Aborts Session Restoration

- Owner: [SessionManager._restore_window_geometry](../src/main/python/fman/impl/session.py#L57).
- Failure: malformed base64 in otherwise valid settings JSON raises before the
  normal startup path; JSON-root validation does not validate session fields.
- Probe: write `window_geometry` as `abcde` using `Settings.flush`, reload the
  temporary file and call `show_main_window` with a mocked window. Decoding
  raises `Error: Invalid base64-encoded string` before restoration.
- Limit: malformed geometry only, not every session field or a full launch.
- Next decision: recover to defaults for specifically invalid restoration fields,
  not arbitrary startup exceptions. Refines C11 in
  [CodeReview099](../Plan/CodeReview099.md).

### F04 - P2: Favorites Merge Distinct Unicode Windows Paths

- Owner: [FavoritesStore.key](../src/main/resources/base/Plugins/Favorites/favorites/store.py#L179).
- Failure: Unicode `casefold` is broader than Windows filename equivalence.
  Adding a distinct folder can reuse the first favorite and return its URL.
- Probe: create folders named by `'stra' + chr(223) + 'e'` and `strasse`.
  Windows reports distinct objects. Adding both leaves one favorite; looking
  up the second returns the first folder's URL.
- Limit: one local Windows pair, not a complete Unicode, UNC, provider or
  case-sensitive-directory identity policy.
- Next decision: choose filesystem-appropriate identity/comparison semantics;
  do not substitute another blanket normalization without reviewing those cases.

### F05 - P2: Normal Quit Falls Through to Error Reporting

- Owner: [ReportExceptions.__exit__](../src/main/python/fman/impl/plugins/plugin.py#L326).
- Failure: after handling `SystemExit`, the wrapper continues into error
  reporting. Alt+F4 does not take this command-exception path.
- Probe: use the real `PluginErrorHandler` with mocked application/window
  boundaries and raise `SystemExit(0)` inside the wrapper. It calls
  `application.exit(0)` and attempts one alert containing
  `Command Quit raised error` and `SystemExit: 0`.
- Limit: alert attempt confirmed, not its visibility or real Qt shutdown timing.
- Next decision: stop error-report fallthrough after handling shutdown while
  retaining exit codes and ordinary exception reporting.

### F06 - P2: Status Snapshot Construction Blocks Qt Before Submission

- Owner: [ListingModel.get_status_entries](../src/main/python/fman/impl/model/listing.py#L591),
  called by [DirectoryPaneWidget.get_status_snapshot](../src/main/python/fman/impl/widgets.py#L229).
- Cost: enabled status refresh constructs a URL and entry object for every
  visible row on Qt before worker submission. The cap bounds size queries,
  not capture allocation or the required complete file/directory counts.
- Probe: synthetic 200,000-row listing, three snapshot expansions: 115.7,
  118.9 and 121.8 ms; median 118.9 ms on the review machine.
- Limit: expansion only; not action-to-next-input, Qt heartbeat, total refresh
  time or memory measurement. No disabled-status overhead was established.
- Next decision: separately review compact immutable listing/selection capture
  and expansion on the existing worker. Preserve counts, freshness, limits,
  cancellation and the disabled no-op path. FO02 in
  [CodeReview099](../Plan/CodeReview099.md) retains canonical proposal ownership.

### F07 - P3: FindFiles Revalidates Rows Already Destined for Discard

- Owner: [Collector.accept](../src/main/resources/base/Plugins/FindFiles/find_files/engine.py#L265).
- Cost: after the table fills, discarded results still undergo path decoding,
  normalization, containment checks, relative-path construction and encoding.
- Probe: three repetitions count 50,000 additional valid records after a one-row
  table fills. Current median: 231.9 ms; count-only prototype: approximately
  3 ms, or 78 times faster for that slice. Both retain one row and count 50,002.
- Limit: valid synthetic records only; no fd process, transport parsing, disk
  enumeration or end-to-end speedup measurement. Malformed discarded-record
  behavior differs in the prototype and has not been approved.
- Next decision: consider early count-only handling after saturation. Preserve
  framing/record limits and retained-row validation; explicitly decide whether
  malformed discarded records must still fail the search. Conditional
  guard-removal candidate, not an approved optimization.

### F08 - P2: Quitting With a Table View Open Leaves Its Cache on Disk

- Owner: [CsvController.shutdown](../src/main/python/fman/impl/quick_view_csv.py#L249),
  connected to `aboutToQuit` at [line 169](../src/main/python/fman/impl/quick_view_csv.py#L169).
- Failure: on quit, `retire` sends `close` to an idle helper and returns. The
  event loop ends before the helper exits, Qt destroys the running `QProcess`
  (`QProcess: Destroyed while process ... is still running`) and the helper never
  runs its cache release. `_finished`, which deletes owned folders after a kill,
  is not reached either. The owned cache is limited to twice the file size, up to
  8 GiB per window. [recover_abandoned](../src/main/python/_quick_view_csv_worker.py#L80)
  removes it only when a later helper starts, and only after 60 s.
- Probe: isolated settings, real `CsvController` with the source helper, a
  200,000-record CSV. After `imported`, call `app.quit()`. Qt printed the warning
  and, 3 s after the process ended, one `s-<pid>-<id>` folder of 1,586,302 bytes
  remained under `Cache/QuickViewCsv`.
- Limit: controller-level quit, not the full application window-close sequence;
  the leftover size scales with the file and was not measured for large files.
- Next decision: on quit, bound a wait for the helper's `close` (or kill it) and
  delete owned folders synchronously before Qt teardown. Keep the 60 s age rule
  for other processes' folders.

### F09 - P3: Copy Within the 8 MiB Limit Can Exceed the Helper Frame Limit

- Owner: [Engine.copy](../src/main/python/_quick_view_csv_worker.py#L682) and
  the JSON reply in [main](../src/main/python/_quick_view_csv_worker.py#L786).
- Failure: copy measures UTF-8 TSV bytes against 8 MiB, but the reply is JSON.
  Control characters (U+0001-U+001F other than tab/CR/LF) expand to six bytes
  (`\u0001`), so allowed text can exceed the 32 MiB `MAX_PAYLOAD`. The error is
  then the reused PDF message `PDF page exceeds memory allowance`.
- Probe: seven records of 1,000,000 `U+0001` characters. Copy text 7,000,012
  bytes (limit 8,388,608); JSON payload 42,000,035 bytes; `encode_frame` raised
  `PDF page exceeds memory allowance`.
- Limit: worker-level; the UI path shows it as a copy failure (status line), not
  a helper crash. Ordinary text is unaffected.
- Next decision: send copy and cell text as a raw UTF-8 payload, or measure the
  encoded size; use a Table View message.

### F10 - P3: TSV Fields Starting With a Quote Are Refused

- Owner: [Engine._dialect](../src/main/python/_quick_view_csv_worker.py#L449) and
  the import options, which always use `quote='"'` and strict mode.
- Failure: plain TSV has no quoting convention, so `1<TAB>"Dune" by Herbert` is
  valid. Auto detection fails, and explicit Tab/First record fails at import.
  No option loads the file. Auto also reports kind `encoding` for a dialect error.
- Probe: a three-line `.tsv` with that record. Auto: `Cannot detect the table
  format` (kind `encoding`); explicit Tab + header: `CSV Error on Line: 2` (kind
  `parse`). A quote inside a field (`27" monitor`) loads.
- Limit: files up to 2 MiB still open in Text View; larger ones are Table-only.
- Next decision: decide whether `.tsv` (or a Quote option) disables quoting,
  and classify sniffer failures as `parse`.
- Dialect policy (R05): literal and quoted TSV are different dialects; neither
  is assumed. Literal TSV loads `"Dune" by Herbert` but cannot hold tabs or
  line breaks inside a field; quoted TSV (current) holds them but refuses a
  field that starts with an unbalanced quote. Options for the user: (a) keep
  quoted TSV and report the failure as `parse` with a hint; (b) a Quote option
  (`"` or None) in Options, default unchanged; (c) literal for `.tsv` only,
  a compatibility change for quoted `.tsv` files. Proposed: (a) plus (b).

### F11 - P3: New Folder Reports Invalid Names as a Plug-In Error

- Owner: [CreateDirectory.__call__](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L907).
- Failure: only `FileExistsError` is handled. Invalid names (`a<b`, `a:b`, a
  component over 255 characters), read-only folders or a disconnected share raise
  `OSError` into the command error report. **New file** handles the same cases
  with an alert in `_touch_file_if_missing`.
- Probe: real `LocalFileSystem.makedirs` in a temporary folder. `bad<name` and a
  300-character name raise `OSError` (`WinError 123`), not `FileExistsError`.
- Limit: the error-report dialog itself was not shown; the command path was
  traced in code, as the isolated harness cannot register the local provider.
- Next decision: alert with the OS reason, as New file does.

### F12 - P3: Filter Typing Restarts an Interrupted Fold From Scratch

- Owner: [CsvController.query](../src/main/python/fman/impl/quick_view_csv.py#L191)
  and [Engine.prepare_folds](../src/main/python/_quick_view_csv_worker.py#L518).
- Cost: each debounced filter change (200 ms) cancels the active query. If a
  fold column is still being prepared, it is dropped (IR1 rollback) and the next
  query starts that column again. Completed columns are kept, so a global filter
  progresses, but a column filter on one large non-ASCII column can restart on
  every pause in typing and finish only once the user stops for its whole duration.
- Evidence: code trace only; not measured. Engine measurements show a first
  global fold of 2.6 s for 100 MB, so large files can take far longer per column.
- Next decision: keep preparation running when the new query needs the same
  folds and cancel only the projection, or start folding on filter-menu open.
  Preserve cancellation on file change and helper retirement.

### F13 - Moved

Implemented through [CodeReview007](../Done/CodeReview007.md).

### F14 - P3: Small-File Copy Has Candidate Per-File Overheads

- Owner: [CopyFile._copy_bytes](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L454)
  and the `finally` block of `CopyFile.__call__`.
- Cost: `fsrc.read(1 MiB)` allocates a new 1 MiB buffer per call, and every file
  needs two calls (data, then EOF). After a successful `rename`, the staging path
  is unlinked unconditionally and fails.
- Probe: `cProfile` over provider copies of 2,000 x 4 KiB files (2.18 s
  profiled): 4,000 `read` calls took 0.50 s, 2,000 failing `unlink` calls 0.08 s.
  The same files took 0.73-0.76 s with `shutil.copy2` versus 2.72-2.97 s through
  the provider. Staging, `rename`, `copystat` and the extra checks account for the
  rest and are intentional.
- Limit: one local NVMe volume, warm cache, no antivirus attribution. The
  profile measures time inside `read`, not allocation alone (R06); the heading
  previously claimed a quarter of copy time was avoidable, which is unproven.
  Any saving needs a comparable prototype with staging and identity checks.
- Next decision: `readinto` a reused buffer sized to the file (up to 1 MiB) and
  skip the unlink once published. Keep staging and identity checks. A native
  `CopyFile2` path for large files is a separate, unmeasured design question.

### F15 - P3: Fast Repeated Navigation Uses the Old Location

- Owner: [go_up](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L197)
  and [SortedFileSystemModel](../src/main/python/fman/impl/model/__init__.py#L126).
- Failure: commands run on their own threads and read `pane.get_path()`, which
  changes only after the new folder's scan commits. Two Backspace presses during
  one pending navigation both target the same parent, so the user goes up one
  level. Enter on a folder followed by Backspace before it loads goes to the old
  folder's parent. Noticeable on slow (network) folders; fast local scans hide it.
- Evidence: code trace only; the second navigation supersedes the first by
  generation, so no stale listing is shown.
- Next decision: decide whether relative navigation should start from the
  pending target. Preserve cancellation and cursor restoration.

### Follow-up Review (2026-10-27)

Document/design review of F10, F13 and F14, not new runtime findings. The runtime
claims and external prototype were not independently revalidated; no tests,
probes or application changes were made for this review. Earlier findings and
evidence remain unchanged. R01-R04 and Q01 concerned F13 and were resolved in
[CodeReview007](../Done/CodeReview007.md).

#### R05 - P3: F10 Needs an Explicit TSV Dialect Policy

- Concern: saying plain TSV has no quoting convention does not establish the
  intended supported dialect. Disabling quoting automatically for `.tsv` could
  break quoted tabs and multiline fields.
- Required clarification: treat literal versus quoted TSV as a dialect-support
  decision; specify the selected behavior rather than assuming an
  extension-wide quoting change is a compatibility-preserving fix.

#### R06 - P3: F14 Overstates the Demonstrated Avoidable Cost

- Concern: the profile measures time inside `read`, not allocation overhead
  separately. It does not show that `readinto` removes a quarter of copy time.
- Required clarification: retain the optimization candidate, but qualify the
  heading and any savings claim until a comparable prototype measures the
  effect while preserving staging and identity checks.

#### Response (2026-10-27)

- R05: F10 "Dialect policy" lists the options; a user choice is needed.
- R06: the F14 heading and claim are qualified.

### Investigated, Not Promoted (2026-10-26)

- Filter Bar per-keystroke cost: projections already run off the Qt thread.
- Everything `terminate()` escalation: on Windows it is `TerminateProcess`.
- `CsvController.retire` races: all controller state is Qt-thread only.
- `ROW_MAP_LIMIT` off-by-one: the threshold is intentional, not a defect.
- Path segments such as `..` in New file/folder names: user-typed relative
  paths; not a safety boundary.
- `is_dir`/`resolve` during Open and Go Up: commands run on their own threads,
  not the Qt thread.
- Per-chunk progress updates: `ProgressDialog` stores values and repaints on a
  100 ms timer.

## Decisions (2026-10-27)

User selection after the review:

- Implement F01-F06, F08, F11, F12 and F14 as proposed below; not F15.
- F01/F02: run the copy as a subtask of the move (parent progress and Cancel).
  Before deleting, compare the source's `st_ino`, `st_dev`, `st_size` and
  `st_mtime_ns` with the copy-time `fstat`; on a difference keep the source and
  raise `OSError` (reported as a per-file move error). Cancel after the copy keeps
  the source. A change between this check and deletion remains possible.
- F03: ignore undecodable or Qt-rejected `window_geometry`/`window_state` and use
  defaults; other startup errors are unchanged.
- F04: compare `file://` favorites with `ntpath.normcase` (simple per-character
  lowercase), close to but not guaranteed identical to NTFS name comparison.
- F05: return after `handle_system_exit`.
- F06: capture listing tuples and the selection; build entries on the worker.
- F07: option B, count-only after the table fills. Framing and record limits are
  unchanged; malformed discarded records are counted, not reported.
- F08: on `aboutToQuit`, wait up to 2 s for the helper, kill it otherwise, and
  delete owned cache folders synchronously.
- F09: option (a), copy text as a raw UTF-8 frame payload.
- F10: keep DuckDB's strict quoted rules for CSV and TSV, without fallback.
  Classify sniffer failures as `parse`, add a strict-rules hint, keep the
  in-panel message (no modal alert), and document the policy in
  [tools.md](../docs/tools.md).
- F11: alert with the OS reason, as New file does.
- F12: keep an active query that is still preparing folds the next query needs;
  the helper reports prepared folds with each projection.
- F14: `readinto` one buffer of the source size, between 64 KiB and 1 MiB, and
  skip the staging unlink after publication.

## Implementation Steps

1. Record initial findings and add this task to Pending in [Plan.md](../Plan.md).
   Do not implement application changes.
2. Wait for others to append independent findings, evidence and reviewer records;
   do not launch additional agents automatically.
3. Reconcile duplicates, challenged claims and canonical backlog ownership while
   retaining historical evidence and dispositions.
4. Ask the user to select follow-up scope. Any eventual implementation needs
   explicit compatibility and validation decisions; this review authorizes none.
5. Implement the selected findings (see Decisions) with focused regression tests.

## Acceptance Criteria

- Cover bugs, edge cases, unnecessary guards and smoother/faster operations.
- Distinguish confirmed evidence, proposed remedies and unverified limits.
- Keep stable finding IDs, real source references and append-only provenance;
  cross-reference overlapping backlog items rather than silently superseding them.
- Run no tests and change no application code during this review phase. Only
  check specific new speculations with bounded disposable probes.
- Remain Pending while awaiting other contributors and the user's next decision.
  Document creation is not implementation completion or release approval.

## Implementation Review (2026-10-27)

The selected F01-F12 and F14 changes were reviewed against Decisions and nearby
regression coverage. F15 remains explicitly excluded. IR01 and IR02 are open
implementation follow-ups, not changes to the earlier findings or approvals.
No application code was changed by this review.

### IR01 - P2: F08 Quit Cleanup Misses a Cache Created Before Preview

- Owner: [CsvController._quit](../src/main/python/fman/impl/quick_view_csv.py#L278),
  [preview ownership registration](../src/main/python/fman/impl/quick_view_csv.py#L422)
  and [Engine._open](../src/main/python/_quick_view_csv_worker.py#L390).
- Failure: the helper creates its cache before dialect detection and preview
  parsing. The controller adds that directory to `_owned` only on receipt of
  the later `preview` frame. Quitting with an active open kills the helper;
  when no preview has arrived, `_finished` has no directory to remove.
- Probe: generated a two-record CSV and isolated settings/cache directories;
  ran the real helper and controller on the native Windows Qt platform. An
  inline helper patch paused `_dialect` with a bounded event wait after cache
  creation, before preview. A stderr marker triggered `app.quit()`, exercising
  the real `aboutToQuit` connection. The helper stopped, but `_owned` had been
  empty and one 12,288-byte cache folder remained after the event loop exited.
  The disposable probe directory was removed afterward.
- Coverage gap: the existing
  [quit regression](../src/integrationtest/python/fman_integrationtest/test_qt.py#L960)
  waits for a ready table and a populated `_owned` set, so it cannot cover this
  startup boundary.
- Follow-up: establish recoverable ownership before killable open work starts,
  then clean this helper's cache after confirming termination. Do not remove
  another process's cache or bypass its age rule. Add a pre-preview quit
  regression alongside the existing imported-table case.
- Limit: controlled pause at a real helper boundary, not a naturally slow disk
  reproduction, packaged host or full application window-close test.

### IR02 - P3: F07 Still Validates the First Record Beyond the Row Cap

- Owner: [Collector.accept](../src/main/resources/base/Plugins/FindFiles/find_files/engine.py#L265).
- Failure: `limited` is set only after decoding and validating an extra record.
  With exactly `max_rows` retained rows it is still false, so a malformed next
  record fails the search even though that record cannot be retained. Decisions
  explicitly select count-only handling for malformed discarded records.
- Probe: compiled the actual `Collector` class from source with minimal options
  and a plain replacement for the `Hit` record, using a temporary root. With
  `max_rows=1`, accepting `kept.txt` produced one stored row, total 1 and
  `limited=False`; accepting `b'\xff'` next raised `UnicodeDecodeError`, leaving
  total at 1 instead of counting the discarded record.
- Coverage gap: the existing
  [capacity test](../src/unittest/python/fman_unittest/test_find_files.py#L211)
  feeds malformed records only after a valid record has already set `limited`.
- Follow-up: check row-count exhaustion before decoding the next record; mark
  `limited` when discarding that record, not merely when storing the last
  allowed row. Preserve framing/record-size limits and retained-row validation.
  Add malformed-record cases immediately after the row cap is reached.
- Limit: collector-level check, not an actual fd transport or end-to-end search.

### Review Validation

- Both bounded inline probes ran under the selected Python 3.14.7 interpreter
  as `python -X faulthandler -u -`, launched through `build._environment()` with
  a 25-second parent timeout. No existing unit, integration, smoke, performance,
  build or freeze target was run for this review.
- Editor diagnostics reported no errors in the local copy/move provider,
  session restoration, status model/service, CSV controller/worker or Find Files
  engine. This is not a replacement for runtime regression coverage.
- Other inspected changes did not produce additional confirmed findings. The
  implementer's earlier test counts and measurements remain historical and
  were not independently rerun. No release certification is implied.

### Resolution (2026-10-27)

- IR01 accepted and fixed. The controller now names the session cache folder
  (`s-<helper pid>-<random>` under the cache root) and adds it to `_owned` before
  sending `open`; the helper creates exactly that folder and rejects one outside
  the root, without the `s-` prefix, or already present. Ownership no longer
  depends on the `preview` frame, so a kill at any point leaves a known folder
  for the synchronous quit cleanup. Other processes' folders and the 60 s age
  rule are unchanged. Regressions: a real helper paused after creating its
  cache, then `_quit`; and engine validation of requested folders.
- IR02 accepted and fixed. `Collector.accept` checks the row cap before decoding,
  so the first record past the cap is counted without validation. The byte cap
  still validates the record that exceeds it. Regression: each malformed record
  immediately after `max_rows` is reached.

## Reviewers

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Established review-only scope and the no-tests rule; recorded F01-F07
  with disposable-probe evidence, limitations and existing-backlog links.
  Awaiting independent contributions; no application implementation authorized.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Independent review; added F08-F12 (QuickView Table View quit cleanup,
  copy framing, TSV quoting, New folder errors, fold restarts) with disposable
  probes outside the repository, and recorded rejected speculations. No tests
  run and no application code changed. F01-F07 not re-verified.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Core-focused pass on navigation, filtering and Copy/Move; added
  F13-F15 (rescans during batches, small-file copy overhead, repeated
  navigation). Provider-level copy probes ran outside the repository. No tests
  run and no application code changed.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: F13: recorded the side-implementation A/B, user-visible losses, the
  user's setting decision (default live refresh) and a concrete design for the
  `live_refresh_during_file_operations` setting, toggle command, tests and
  `copy.flat.deferred` benchmark. Awaiting review; no application code changed.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Recorded document/design review comments R01-R06 on F13 concurrency,
  refresh completion, per-thread freshness and cache invalidation, F10 TSV
  dialect policy and F14 performance attribution; added open benchmark question
  Q01. Resolve R01-R04 before implementation. Runtime claims and the external
  prototype were not independently revalidated. Historical findings and reviewer
  records preserved; no tests, probes or application changes for this review.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Accepted R01-R06 and Q01, and revised F13 to cover settings-write
  locking, endpoints, scope semantics, per-case cache invalidation and the
  four-test benchmark matrix. Proposed an F10 dialect policy and qualified F14.
  Code facts were checked by reading the source (`config.py`, `mother_fs.py`,
  `_request_scan`, `settings_resource`, copy child). No tests run and no
  application code changed; F13 implementation awaits approval.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Split from CodeReview007 by user request. F13 and R01-R04/Q01 moved
  to CodeReview007 for implementation; the remaining findings, R05-R06 and all
  earlier reviewer records are kept here unchanged. No application code changed.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the selected implementation and nearby regression coverage.
  Recorded IR01 (F08 pre-preview cache cleanup) and IR02 (F07 first discarded
  record validation) with bounded disposable-probe evidence. Both remain open
  follow-ups. No application code changed or existing test targets rerun;
  historical findings, decisions and implementation/validation records preserved.

## Implementer

### 2026_10_27 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented F01-F12 and F14 per Decisions; F15 not implemented.
  Changes in `core/fs/local`, `session.py`, `favorites/store.py`, `plugin.py`,
  `status_bar.py`, `model/listing.py`, `find_files/engine.py`,
  `quick_view_csv.py`, `_quick_view_csv_worker.py` and `core/commands`.
  Focused regression tests added per finding; all focused runs pass.

### 2026_10_27 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Fixed IR01 (controller-owned cache folder before `open`) and IR02
  (row cap checked before decoding) with the regressions listed in Resolution;
  focused runs pass.

## Validation Results

Commands (conda environment, `build._environment()`):

- `python -m unittest core.tests.test_fileoperations core.tests.fs.test_local
  core.tests.commands.test___init__ fman_unittest.impl.test_session
  fman_unittest.impl.plugins.test_plugin fman_unittest.test_favorites
  fman_unittest.test_find_files fman_unittest.test_listing
  fman_unittest.impl.test_status_bar fman_unittest.impl.test_quick_view_csv
  fman_integrationtest.test_find_files_engine
  fman_integrationtest.impl.plugins.test_favorites_plugin`
  (offscreen): 508 tests OK, 7 skipped (symbolic-link privilege and similar).
- `python -m unittest fman_integrationtest.test_qt.SnapshotFilterBarIT
  fman_integrationtest.test_qt.RoadmapCommandsIT
  fman_integrationtest.test_qt.QuickViewCsvIT
  fman_integrationtest.test_qt.FavoritesManagerIT` (windows platform): 76 OK,
  1 skipped. Includes the new quit test against the real Table View helper.
- `python -B src/performancetest/run.py copy-buffer`: 10 OK.

New regression tests: move-by-copying progress, changed source (during and after
publication), parent cancellation, buffer reuse, no staging unlink; invalid
session geometry/state; Favorites `Straße`/`strasse`; `SystemExit` without
report; New folder `OSError`; count-only Find Files collector; raw copy payload;
strict TSV errors; fold-keeping query decisions; lazy status entries.

Measurements (local, not certified):

- F14: 2,000 x 4 KiB provider copies, five runs each: median 8.70 s with the
  old `read` loop, 8.35 s with the reused buffer (about 4%; run-to-run spread is
  similar). The staging-unlink saving is not separately measured.
- F06: 200,000-row status capture on the Qt thread: about 113 ms before
  (expansion now on the worker), about 1 µs after.

Not run: the full suite, real second-volume moves, packaged-application smoke and
real application quit with an open table (the controller quit path is tested).

IR01/IR02 follow-up (2026-10-27):

- `python -m unittest fman_unittest.test_find_files
  fman_unittest.impl.test_quick_view_csv fman_integrationtest.test_find_files_engine`
  (offscreen): 49 OK, 1 skipped.
- `python -m unittest fman_integrationtest.test_qt.QuickViewCsvIT` (windows
  platform): 7 OK, including the new pre-preview quit regression with a real
  helper.