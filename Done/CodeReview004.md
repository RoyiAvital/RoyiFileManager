# Code Review 004: Low-Risk Responsiveness Improvements

Status: Completed approved scope and final clarity follow-up, 2026-09-25.
The user authorized N01-N04, N09 and N10 only; all six are implemented and
validated. N05-N08 and N11-N13 remain unimplemented, tracked in
[CodeReview099](../Plan/CodeReview099.md) and
[DateFormat](../Plan/DateFormat.md). The proposal and historical review evidence
below are retained; current outcomes are in Validation Results.

## Task

Reduce redundant pane-layout, status, command-palette and icon work, Find
preparation cost and temporary search allocations through small changes.
Preserve the architecture and public plug-in API. The base batch preserves
behavior; optional snapshot-status freshness and date presentation changes need
explicit approval.

### Summary And Recommendation

The three additional reviews agree on N01-N04. Sol's N09/N10 fit the same small,
exact-semantics scope. Opus's N11 offers the largest potential user-visible gain,
but changes freshness semantics; N12 can be reduced to a safer per-suggestion
hint lookup without freezing command visibility. ISO dates are useful as a
preference, not as a material responsiveness improvement.

| Decision | Recommended Scope | Expected Benefit And Limit |
| --- | --- | --- |
| First batch | N01-N04, N09, N10 | Remove proven redundant work with no settings or lifecycle change. N01: 50-67% fewer sizing passes in the probe; N02: half the flat-entry normalization calls; N03: about 1.54 MiB of avoidable score containers at 20,000 matches; N04: half the tested icon-key calls; N09: a reviewer-measured 3.37 ms status pass at 202,603 entries; N10: fewer lowercase calls, timing unmeasured. These are component gains, not additive whole-app percentages. |
| Highest-value conditional follow-up | N11 after N09, if snapshot-consistent totals are accepted | Remove cold size-query I/O for known files. Opus's 40-file ZIP probe spent 303 ms in 40 extra processes after scanning; this work becomes unnecessary for known sizes. No comparable first-pane-paint saving is established, and warm caches/disabled status reduce or remove the benefit. Adds about 1.55 MiB of references per 202,603-entry status snapshot. |
| Optional small palette follow-up | N12 narrowed to one shortcut map per suggestion pass, alongside N10 | In a synthetic 82-command/74-binding fixture, 6,068 binding visits become 74 with exact hint parity. Keep visibility/aliases live; do not cache all candidates per opening. Overall palette latency is unmeasured. |
| Optional display preference | N13 through [DateFormat](../Plan/DateFormat.md) | Locale remains default; ISO gives consistent local 24-hour dates and four-digit years. One-time pattern resolution saves about 0.20-0.25 ms per 512 uncached date cells, roughly 0.02 ms for 40 dates. ISO itself adds little beyond prepared Locale. |
| Do not select for this batch | N05-N08 and the original per-opening N12 cache | Their claimed gains depend on changing signals, scheduling, retained memory, Qt lookup cost or live command semantics. A separate design/benchmark is needed. |

Accepted decision: implement the base six only. N11 still requires approval of
snapshot freshness; N12 requires its separate hint-map tests; N13 remains a
display preference in DateFormat. Sharing an owner with approved work does not
authorize these follow-ups.

Do not expect a dramatic general folder-loading or directory-size-calculation
speedup. No accepted proposal shortens enumeration or the `Ctrl+F4` sort itself.
Benefits occur during layout, uncached painting, Find setup/ranking, debounced
status completion and command-palette typing. Existing reviewer timings are
attributed microprobes, not newly measured application benchmarks.

## Scope

- N01: suppress redundant column sizing during automatic width updates.
- N02: normalize identical search name/path strings once during matcher setup.
- N03: stream ranked matches into the existing bounded top-result selection.
- N04: reuse the icon key within a pane decoration request.
- N09: remove a redundant full pass over complete status entries.
- N10: lowercase each command-palette query and alias once per suggestion pass.
- N11: not implemented; snapshot-size status totals need freshness approval.
- N12: not implemented; conditional per-suggestion shortcut map only; per-opening candidate
  caching is not recommended under the low-risk scope.
- N13: optional Locale/ISO Modified dates, using the independent
  [DateFormat](../Plan/DateFormat.md) configuration design; not implemented.
- N05-N08 are review notes, not accepted implementation scope in their current
  form.
- Preserve result order, marks/cursor/scroll, Qt thread affinity, cancellation,
  stale-result rejection, portable settings and disabled-feature no-op behavior.
- No new workers, timers, dependencies, persistent caches or API changes.
  N13 alone would add the setting defined by DateFormat, using existing settings
  loading and requiring a restart; the other proposals add no settings.
  Directory enumeration, directory-size calculation, sorting policy, search
  syntax and asynchronous matching are outside scope.
- No benchmark protocol, repetition count or saved performance-record changes.

## Design

Keep each selected change in its existing owner and validate it independently.
Layout, status snapshots and icon objects stay on Qt; matcher execution stays
with its existing callers. Cancellation checks, error propagation, fallbacks
and queue limits remain intact. No persistence or data-flow redesign is needed.

The design evidence below predates implementation. The approved six were
implemented in order N01, N02, N03, N04, N09, N10, with focused checks after each
edit. Optional work needs its own scope decision and gates below; this is not
blanket approval of all candidates.

### Review Disposition

- Recommend N01-N04 as scoped, with their existing parity and regression checks.
- Recommend N09 and N10 as smaller exact-semantics additions.
- N11: highest-potential follow-up, conditional on snapshot freshness, per-entry
  memory and fallback/limit decisions. Do not describe it as exact live-result
  parity or promote worker savings to first-paint savings.
- N12: recommend only the per-suggestion shortcut-map variant described below.
  The original per-opening visibility/alias snapshot lacks a stability contract.
- N13: offer as an optional Locale/ISO preference through DateFormat. Pattern
  reuse benefits both modes; its measured saving does not justify a speed claim
  for ISO over prepared Locale.
- Defer N05: suppressing a commit also suppresses documented signals and the
  commit path that resolves pending cursor restoration; equality is additionally
  proposed on the Qt thread for very large listings.
- Defer N06: changing a 4 ms cooperative yield deadline to 16 ms changes the
  responsiveness policy, and `sleep(0)` does not establish equivalent Qt event
  latency. Treat it as a separately benchmarked scheduler experiment.
- Reject N07 in its current form: it retains about 20 MB at the reference size,
  is rebuilt after every commit if invalidated like `_names`, and the 150 ms
  debounce means it is not paid once per Filter Bar keystroke.
- Reject N08 in its current form: repeated `visible.index()` calls move
  potentially quadratic work to Qt, while a thresholded custom mapping and a
  second materialization path add more risk than this low-risk batch allows.

#### N01: Avoid Reentrant Column Sizing During Automatic Layout

- Owner: `ResizeColumnsToContents._resize_cols_to_contents`,
  `_apply_column_widths` and `_on_col_resized` in
  [column sizing](../src/main/python/fman/impl/view/resize_cols_to_contents.py).
- Evidence: applying computed widths emits `sectionResized`, which re-enters
  minimum-width calculation for programmatic changes. A three-column Qt probe
  measured 3, 3 and 2 minimum-width passes at widths 640, 960 and 1280. Temporarily
  suppressing only this internal resize handler reduced each to 1, with identical
  final column widths in those fixtures. Minimum widths ask delegates for cell
  size hints, so the repeated work can include text layout and icon lookup.
- Small change: extend the existing reentrancy guard across a computed width
  batch; restore its prior value in `finally`. Do not block Qt/header signals
  globally, change sizing policy or suppress user-driven column resizing.
- Cost: no new state beyond the existing boolean, background work or I/O. Saves
  redundant visible-cell sizing on affected layout/resize events, not scanning.
- Disconfirm/accept: keep exact widths, minimums, scrollbar allowance and manual
  redistribution for one/many columns, cramped/wide windows, empty-to-populated
  models, font/DPI changes and both panes. Assert one minimum-width pass per
  automatic batch and guard restoration after errors. Reject if native layout
  differs; the offscreen probe alone does not certify it.

#### N02: Normalize Identical Search Name And Path Once

- Owner: `Matcher.__init__` in
  [matcher](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/matcher.py).
  Both `ListingSearch` and `index_listing` in
  [indexer](../src/main/resources/base/Plugins/SearchFileFuzzy/search_file_fuzzy/indexer.py)
  produce entries whose name and relative path are the same label.
- Evidence: constructing a matcher for 20,000 flat entries called `normalize`
  40,000 times. Computing the normalized name once and reusing it only when the
  original strings are equal required 20,000 calls and produced equal normalized
  pairs. This affects first Find preparation, including pane Find projections;
  the matcher already reuses its index across subsequent queries.
- Small change: reuse that result inside the existing constructor. Keep the
  separate literal-path normalization for extended syntax and the unequal-path
  branch unchanged. Do not add an interning cache or alter Unicode rules.
- Cost: one string-equality check per entry, fewer normalization allocations for
  flat entries; existing storage/bounds and cancellation checkpoints remain.
  No startup/idle cost when Find is unused, no extra I/O or worker.
- Disconfirm/accept: exact results, order and UTF-16 highlights for flat and
  nested paths, provider labels, Unicode composition/case expansion, regular and
  fuzzy modes. Confirm one normalization per equal pair, two per unequal pair;
  compare both flat and mostly-nested setup times to expose branch overhead.

#### N03: Feed Ranked Matches Directly To Bounded Top-K Selection

- Owner: `Matcher._fuzzy` and the ranked branch of `Matcher._extended` in the
  same matcher. Both first append every scored candidate to a list, then call
  `heapq.nlargest(max_results, ...)`.
- Evidence: on 20,000 matching entries, both `file` and `file | missing` retained
  20,000 score tuples to return 100 results. The list plus tuple containers alone
  occupied 1,613,016 bytes in the probe; that excludes score/index objects and
  the index itself. Feeding those exact tuples as an iterator to `nlargest`
  returned identical ordering. This probe proves ranking parity for its fixture,
  not the memory or timing of a completed streaming implementation.
- Small change: yield ranked tuples directly into the existing standard-library
  heap operation, preserving `(score, -index, entry)`, traversal order and
  cancellation checks. Keep unranked extended-query early exit and regular mode
  unchanged. No custom ranking algorithm or changed result/entry limit.
- Cost: retained ranking candidates become bounded by requested results rather
  than total matches; scoring still visits the same entries. Generator overhead
  may offset time savings for small inputs, so claim memory savings first. No
  extra persistent state, I/O, threads or disabled-path work.
- Disconfirm/accept: compare exact output/highlights against current behavior
  for ties, duplicate names, empty/no matches, result limits above/below entry
  count, mixed positive/negative OR terms and Unicode. Check cancellation while
  consuming candidates and old/new peak allocation with many matches; reject a
  material input-latency regression or any change in ranking semantics.

#### N04: Reuse The Icon Key Within A Decoration Request

- Owners: `ListingModel.data` in
  [listing model](../src/main/python/fman/impl/model/listing.py) and
  `ListingIcons.icon/key` in
  [listing icons](../src/main/python/fman/impl/model/listing_icons.py).
- Evidence: ten cached ordinary-file decoration requests through the model
  called `key` twenty times, with zero shell jobs. The model computes the key for
  invalidation tracking, then `icon` computes it again. The existing
  `test_icon_suffix_parsed_once_and_shell_arguments_preserved` exercises `icon`
  directly and therefore does not cover this duplication.
- Small change: pass/reuse the already computed key through this private call
  path, leaving direct callers supported. No cross-request cache or public
  `fman` API change; keep provider/reparse/offline fallback behavior.
- Cost: eliminates one path/suffix/identity-key calculation per eligible painted
  cell request. Existing 512-cell tracking, 256-icon cache and 128 queued/inflight
  limits remain; no additional memory, I/O or shell workers. Expected gain is
  modest and local to painting/sizing, not whole-folder enumeration.
- Disconfirm/accept: exercise model decoration calls, cache hits/misses,
  directories, executables/shortcuts, suffix-free/dot names, provider and reparse
  entries. Assert one key computation where required, unchanged shell arguments,
  fallback icons, invalidation notifications, queue bounds and close/start-failure
  handling. Native scroll/resize measurements must show no regression.

#### N05: Skip Reprojection When a Rescan Returns an Identical Listing (Deferred)

- Owner: `ListingModel._receive`, scan branch, in
  [listing model](../src/main/python/fman/impl/model/listing.py).
- Disposition: defer. A no-change scan currently reaches `_commit`, whose
  `transaction_ended`, `files_changed` and `all_rows_loaded` notifications are
  observable. It also gives `FileListView._restore_snapshot_state` an opportunity
  to resolve or retire `_pending_cursor` after a reload. The proposed identity
  short-circuit skips all of those effects, so it is not behavior-preserving as
  written. Moving or retaining the equality check also needs a measured thread
  placement decision rather than an optional note.
- Evidence: every mutation notification, `Ctrl+R` and post-operation refresh
  produces a new `Listing` object; `result is not self._listing` is always true,
  so the pane re-sorts, re-filters, resets the model and restores selection even
  when nothing changed. `Listing` is a frozen dataclass of tuples/bytes;
  `a == b` for two scans of the 202,603-entry reference folder took 10.7 ms
  (probe, warm), against ~300 ms of projection plus a full model reset.
- Small change: `if result == self._listing: result = self._listing`
  before the identity test, so an unchanged rescan publishes nothing. External
  column data (DirectorySize) already arrives through `refresh_files`, so it is
  unaffected. Optional: log/count skipped rescans for the benchmark.
- Cost: one tuple comparison per rescan (sub-ms for ordinary folders, ~11 ms
  at 202k) on the Qt thread; alternatively compare on the scan worker before
  delivering. Saves the whole projection, reset, selection/scroll restore and
  QuickView invalidation on the common no-change refresh.
- Disconfirm/accept: refresh after an external size/mtime/attribute change
  must still update; refresh with no change must keep cursor, marks, scroll and
  QuickView image untouched and emit no `modelReset`; `location_loaded`/
  `files_changed` semantics for the no-change case decided explicitly (today
  they fire on every commit).

#### N06: Yield Less Often in the Cooperative Projection Worker (Deferred)

- Owner: `LatestJobs._run` (`cooperative=True`) in the same module.
- Disposition: defer to a scheduler-specific experiment. A 16 ms deadline is a
  fourfold change to the explicit cooperative latency budget, and `sleep(0)`
  only yields the current Windows timeslice; it does not prove that queued Qt
  Python work runs with the same latency. The current probe establishes sleep
  overhead, not input-to-paint parity.
- Evidence: the check requests a 1 ms sleep after each 4 ms deadline. A separate
  Windows probe measured `sleep(0.001)` at about 1.5 ms; multiplying that result
  by 75 yields estimates 113 ms of sleep for 300 ms of active work. This is an
  arithmetic estimate, not an instrumented projection trace, and a near-zero
  `sleep(0)` duration does not prove when the Qt thread next executes Python.
- Small change: yield once per frame (`deadline = 16 ms`) with `sleep(0)`,
  or keep `sleep(0.001)` at a 16 ms cadence (6% overhead instead of 27-38%).
  No other behaviour changes; cancellation checks stay at the same points.
- Unverified original estimate: about 25% shorter projections. Neither that
  saving nor a 16 ms Qt/GIL latency bound follows from the sleep microprobe;
  treat both as unestablished until an actual scheduler experiment measures them.
- Disconfirm/accept: idle and loaded arrow-to-paint p95 from the existing
  interaction benchmark must not regress; projection completion time for the
  reference folder must drop. Reject if the Qt heartbeat gap grows.

#### N07: Cache Visible Row URLs for Status Snapshots (Rejected)

- Owner: `ListingModel.get_status_entries` (after CodeReview003 item 10) and
  the `_names` cache pattern already in `find()`.
- Disposition: reject this cache design. Retaining roughly 20 MB to save about
  25 ms only when status is enabled is not a low-risk memory trade. Invalidating
  it in `_commit` like `_names` means a Filter Bar projection over the same
  listing rebuilds it before the next debounced snapshot. The 150 ms single-shot
  status timer coalesces rapid transaction notifications, so the cost is not
  incurred on every keystroke as the evidence below claims.
- Evidence: with the extended status bar enabled, `transaction_ended` schedules
  a debounced snapshot on the Qt thread that builds one `join()` URL per visible
  row: 62.8 ms for 202k rows. Rapid Filter Bar transactions restart the 150 ms
  single-shot timer rather than each capturing a snapshot. Reusing a per-listing
  URL tuple and computing only selection membership took 38.3 ms in the probe;
  the remaining cost is the `StatusEntry` tuple build.
- Small change: cache `tuple(join(location, name) for name in names)` next to
  `_names`, invalidated in `_commit` like `_names`; index it by entry. Do not
  change `StatusEntry` or the status service.
- Cost: one extra tuple of URLs per displayed listing (~20 MB at 202k, freed on
  commit); saves ~40% of the Qt-thread snapshot cost when status is enabled;
  zero work when the status bar is disabled.
- Disconfirm/accept: identical entries/selection flags; no work in disabled
  mode; cache dropped on commit and location change.

#### N08: Build the Row-Number Map Only for Entries That Need It (Rejected)

- Owner: `project()` and `Projection.rows` in the listing model; consumer is
  `FileListView._restore_snapshot_state` (`projection.rows.get(...)`) and the
  `preferred` lookup.
- Disposition: reject both proposed shapes from this batch. Lazy
  `visible.index(entry)` is linear per lookup on the Qt thread and can become
  quadratic before an arbitrary threshold materializes the map. Capturing and
  passing the exact cursor/selection set into the worker is a larger snapshot
  protocol change and needs a separate design.
- Evidence: each projection builds `{entry: row for row, entry in
  enumerate(visible)}`: 11.9 ms and ~10 MB at 202k, on every keystroke, sort
  and refresh. Its only readers look up the cursor entry, the preferred entry
  and the marked entries, typically a handful.
- Small change: keep `rows` as a lazily built mapping (`__getitem__`/`get`
  computing `visible.index(entry)` for the first few lookups and materialising
  the dict only when more than, say, 64 lookups occur), or pass the needed
  entries (cursor + marks) into `project()` and build the map for those only.
  Select-all of 202k rows would still materialise the full dict once.
- Cost: the claimed worker-side saving trades against unbounded Qt-thread lookup
  time, custom mapping state and a second full-map construction path. It is not
  cost-free in the common case without selection-size and lookup-position data.
- Disconfirm/accept: selection/cursor/scroll restoration identical for none,
  few and all marked; `preferred` behaviour unchanged.

#### N09: Remove the Redundant Status Completeness Pass (Review Addition)

- Owners: `DirectoryPane.get_status_snapshot` in
  [widgets](../src/main/python/fman/impl/widgets.py) and
  `ListingModel.get_status_entries` in the listing model.
- Evidence: `get_status_snapshot` constructs the complete immutable entry tuple,
  then immediately traverses it again with
  `all(entry.is_loaded for entry in entries)`. The sole production
  `get_status_entries` implementation sets `is_loaded=True` for every entry;
  there is no partial-listing producer. A local 202,603-entry namedtuple probe
  measured the redundant pass at a 3.37 ms median. This excludes tuple creation
  and URL joins, which remain unchanged.
- Small change: set `PaneStatusSnapshot.all_rows_loaded` from the complete
  snapshot-model invariant instead of rediscovering it from every entry. Retain
  `StatusEntry.is_loaded` and the summary logic for isolated tests and any future
  explicit partial snapshot design.
- Cost: removes one linear Qt-thread pass per status calculation with no new
  state, allocation, I/O or disabled-mode work.
- Disconfirm/accept: prove the pane model has no alternate partial producer;
  assert an enabled pane snapshot remains complete for empty, filtered and large
  listings and that summary completeness/limits are unchanged.

#### N10: Normalize Command-Palette Text Once Per Suggestion Pass (Review Addition)

- Owner: `CommandPalette._suggest_commands` in
  [Core commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py).
- Evidence: the nested command/alias/matcher loop calls `query.lower()` for
  every matcher attempt and calls `alias.lower()` again when the first matcher
  fails and the second is tried. An unmatched alias therefore lowercases both
  strings twice even though neither changes during the pass.
- Small change: compute the normalized query once before the loops and each
  normalized alias once before its matcher loop. Preserve the existing
  `str.lower` operation, matcher order, highlights, recency and sorting.
- Cost: one lowercase operation per query and per visited alias replaces up to
  two of each per alias in the current two-matcher configuration. No cache,
  retained state, I/O or command-registration change.
- Disconfirm/accept: exact suggestions, highlights, order and recent-command
  promotion for empty, matched, unmatched and Unicode queries; counted lowercase
  calls must be one per query and visited alias.

#### N11: Use Snapshot Sizes for Status Totals (Review Addition)

- Recommendation: conditional follow-up, not part of the initial six. Prefer it
  when extended status in archives or network folders matters, after approving
  snapshot-consistent rather than freshly queried totals.
- Owners: `ListingModel.get_status_entries` in the
  [listing model](../src/main/python/fman/impl/model/listing.py#L464),
  `StatusEntry` and `calculate_status_summary` in
  [status bar](../src/main/python/fman/impl/status_bar.py#L18), and
  `StatusCalculationService.submit`, which passes `fs.query(url, 'size_bytes')`.
- Evidence: the status worker queries every loaded file's size through the
  provider, although the displayed `Listing` already carries `sizes`. Snapshot
  scans never populate operation caches, and every refresh clears the location
  cache, so each recalculation after a refresh repeats the queries:
  - Archives: `ZipFileSystem.scan` uses `_iter_infos(cache=False)`, so each
    `size_bytes` misses the cache and starts a separate 7-Zip listing. A
    temporary 40-file ZIP probe: 1 process for the scan, then **40 processes and
    303 ms** for the status-style size queries, with sizes equal to the listing.
    With the default `max_entries` of 5,000 this permits up to 5,000 cold size-query
    processes in a large archive. This is an upper bound, not a measured large-
    archive runtime. Later selection-only calculations can reuse provider cache
    entries until invalidation; they do not necessarily launch processes again.
  - Local folders: one `os.stat` per file; 4,757 warm stats in `System32` took
    23-29 ms before provider/query overhead, and far more on network shares.
- Small change: add the displayed size to the private `StatusEntry` and use it
  when it is not `None`; fall back to `query_size` for `None` sizes and for
  reparse entries (`FILE_ATTRIBUTE_REPARSE_POINT`), whose snapshot metadata can
  be the link's own fallback. Keep `max_entries`, selection, completeness and
  unsupported-size rules unchanged.
- Cost: one tuple field per entry, built on Qt beside the existing URL; a local
  namedtuple-size probe measured 8 additional bytes per entry, or 1,620,824 bytes
  (about 1.55 MiB) at 202,603 entries per in-flight snapshot, reusing existing
  size integers. No new worker, cache, I/O or disabled-mode work. Removes cold
  provider queries/processes for eligible files whose sizes the snapshot knows.
- Consistency: status totals then match the Size column of the same snapshot.
  A file that became unreadable after the scan keeps its snapshot size instead
  of turning the total incomplete; CodeReview003 item 9 still applies to
  fallback queries. Known sizes are authoritative until a new listing; zero is
  a known size, not a fallback condition. Keep the cap counting eligible files,
  including known sizes, rather than counting only remaining provider calls.
- Disconfirm/accept: equal totals for local, archive, process and provider
  panes on stable inputs; `None` sizes and reparse entries still query; unsupported
  fallback queries still show `-`; limits, selection and cancellation unchanged.
  Add deliberate file-change/unreadability-after-scan cases to establish the
  approved freshness difference. Zero provider/7-Zip calls for eligible known
  sizes (call counts, not wall-clock thresholds); do not seed operation caches
  from display metadata.

#### N12: Reduce Command-Palette Hint Work (Narrowed Recommendation)

- Owners: `CommandPalette._suggest_commands` and `_get_shortcuts_for_command` in
  [Core commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L1311).
- Original review proposed caching visibility, aliases and hints once per
  opening. Do not adopt that form here: `_get_all_commands` deliberately calls
  visibility/alias APIs on each suggestion pass. Their results are not guaranteed
  immutable while a modal event loop and background tasks run. Freezing them
  changes the freshness contract even without a new worker.
- Evidence: every matched command rescans the same already-loaded bindings for
  its hint. A disposable helper probe with 82 command lookups and 74 bindings
  counted 6,068 binding visits currently versus 74 for one map. A separate fixture
  preserved exact output for malformed command/key values, duplicate shortcuts,
  unknown commands and shadowing. This is not a complete palette timing.
- Small variant: build `{command: shortcuts}` once within each suggestion pass,
  preferably lazily on its first match, then reuse for other matches. Keep
  `_get_all_commands`, visibility and aliases live per pass, and retain the
  settings load, matcher order, recency, Mac symbols and item behavior. Pair
  with N10 only if this extra scope is approved.
- Precedence: a syntactically usable shortcut is occupied by its first binding
  even when the command target is unknown or an unhashable malformed value.
  Preserve that reservation before deciding whether it can be a mapping key;
  do not accidentally expose a later shadowed shortcut or raise on a list key.
- Cost: one small map proportional to bindings, discarded after the pass; no
  cross-query state, workers, registration hooks or added I/O. No saving in
  visibility checks is claimed. Narrow/no-match queries may not benefit, hence
  lazy construction and matched/unmatched measurements.
- Disconfirm/accept: identical suggestions, hints, highlights and order for
  empty/broad/narrow/recent/Unicode queries; current malformed/shadowing behavior;
  dynamic visibility, aliases and bindings reflected on the next query in the
  same opening. Verify at most one binding traversal when hints are needed and
  none added for no matches. Full palette/native tests remain required.

#### N13: Optional Locale/ISO Modified Dates

- Canonical feature design: [DateFormat](../Plan/DateFormat.md). Keep its `locale`
  default and optional `iso` value for `date_time_format`; do not create a second
  setting or silently replace localized dates. ISO displays local time as
  `yyyy-MM-dd HH:mm`, not UTC, and takes effect after an application restart.
- Owner: `core.Modified.__init__`, `text` and `get_str` in
  [Core columns](../src/main/resources/base/Plugins/Core/core/__init__.py).
  Resolve one immutable pattern per column instance. Locale keeps the current
  short pattern with `yyyy` changed to `yy`; ISO uses the fixed pattern without
  locale discovery. Preserve timestamp conversion, errors, sort keys and I/O.
- Evidence: both formatting methods currently discover the locale pattern per
  call. Pane `ListingModel.data` already caches text in 512 cells shared across
  columns; this optimization applies only to uncached Modified text, not every
  file at folder opening. A disposable full-formatter probe measured:

  | Locale | Current Locale | Prepared Locale | Prepared ISO |
  | --- | --- | --- | --- |
  | en_US | 2.119 ms | 1.898 ms | 1.872 ms |
  | en_GB | 2.058 ms | 1.814 ms | 1.812 ms |
  | de_DE | 2.027 ms | 1.826 ms | 1.798 ms |

  Values are median time for 512 uncached cells, using Python 3.14.7 / PyQt5
  5.15.11 / Qt 5.15.15 on Windows: 9 batches, 8 passes over 512 timestamps per
  batch, warmup and rotating variant order. The candidate preserved conversion
  code in memory; no application, settings or benchmark-record changes. Locale
  discovery counts including preparation were 512 / 1 / 0 respectively.
- Estimated gain: prepared Locale saves 0.20-0.24 ms per 512 cells (about 10-12%
  of this formatter only); prepared ISO saves 0.23-0.25 ms versus current Locale.
  ISO versus prepared Locale differs by only 0.002-0.028 ms, too small for a
  robust speed claim from this probe. Scaling the measured saving to 40 uncached
  visible dates gives roughly 0.02 ms, not a noticeable pane speedup. Layout,
  painting, settings lookup and disk work were not timed.
- User benefit: predictable four-digit years and 24-hour dates independent of
  locale when requested. Treat this primarily as a display preference, not a
  performance priority. It does not speed up Modified sorting or `Ctrl+F4`.
- Runtime cost: one normal settings lookup and a small pattern per column;
  no per-row settings I/O, workers, timers or per-file cache. Both modes reuse
  the pattern. Missing/invalid values fall back to Locale. Search-result dates,
  third-party text and timestamp precision remain unchanged.
- Disconfirm/accept: exact Locale output in both methods, locale-independent ISO,
  local-time/DST conversion, missing/invalid timestamps, unchanged sort/query
  counts, one-time resolution, restart persistence and native column widths.
  The probe passed output/count checks in all three locales. An initial fixture
  generated a nonexistent local DST time and was discarded before timing; epoch-
  based fixtures preserve valid timestamps. Settings/restart/native UI checks
  require the feature implementation and have not been run.

#### Checked and Rejected in the Opus Review

- **Go To Windows Search per keystroke** (`SuggestLocations` for queries longer
  than two characters): a reused connection saved under 1 ms per keystroke after
  the first query (5.0-5.5 ms query either way; the first query costs about
  95 ms with or without reuse). Not worth changing in this batch.
- **`Size.keys` directory tuples** when directory sizes are off: the per-name
  `ord` tuples preserve descending directory ordering; replacing them changes
  sort semantics and is not a low-risk trim.

### Estimated Gains And User Benefits

Percentages describe the affected work, not application latency. Existing probes
establish call counts and container sizes; no completed implementation or paired
end-to-end timing supports a whole-app speedup claim yet.

| Candidate | Defensible Estimate | What The User May Notice |
| --- | --- | --- |
| N01: column sizing | 2-3 minimum-width passes become 1: 50-67% fewer passes in the tested automatic layouts. Elapsed sizing savings depend on which cells each pass measures and their cache state. | Less layout work when resizing windows/panes or automatically fitting columns. Best small candidate for smoother layout; no faster disk enumeration. |
| N02: search normalization | 50% fewer name/path normalization calls when all entries are flat, with one reused normalized string per equal pair. For mixed trees, the fraction of equal pairs determines savings; literal-path setup and other construction work remain. | Shorter first Find preparation in large flat folders. Little benefit for mostly nested paths, and no corresponding per-keystroke gain once the matcher is built. |
| N03: bounded scoring | With 20,000 matches and a 100-result limit, almost all of the measured 1.54 MiB list/score-tuple storage becomes avoidable. Linear extrapolation is about 3.85 MiB at 50,000 matches; the bounded heap still needs storage. Score/index objects are excluded, and actual peak-memory savings remain unmeasured. | Lower temporary allocation pressure during broad searches. Query time may improve, remain similar or regress slightly from iterator overhead; it still scores every candidate. No promised typing-latency percentage. |
| N04: icon key reuse | 50% fewer key calculations on the tested eligible decoration path: 20 calls become 10. Icon loading, drawing and shell request counts are unchanged. | A small reduction in paint/sizing overhead, probably difficult to notice alone. Does not accelerate uncached shell icon extraction. |
| N09: status completeness | Removes one 202,603-entry pass measured at 3.37 ms median. Status tuple construction, URL joins and worker calculation remain. | A small reduction in the debounced Qt-thread pause before status calculation for very large folders. No effect while status is disabled. |
| N10: palette normalization | One query lowercase and one per visited alias, instead of up to two of each per alias with the current matchers. Whole-palette timing is unmeasured. | Slightly less synchronous work while opening or typing in the command palette; likely modest by itself. |
| N11: snapshot status sizes, conditional | Remove cold queries for eligible known sizes, up to the 5,000-file cap. Opus reported 303 ms in 40 extra ZIP processes and 23-29 ms for 4,757 warm local stats. These are avoided-worker-work examples, not measured end-to-end savings or CPU-time totals; large archives/network shares are unmeasured. Adds about 1.55 MiB of references at 202,603 entries. | Faster snapshot-consistent status totals when extended status is on and provider sizes would miss cache. No benefit while disabled; changed freshness needs approval. |
| N12: per-suggestion hints, conditional | Synthetic helper fixture: 6,068 binding visits become 74 for 82 lookups, with hint parity. Visibility and aliases still run per query; no per-opening caching. Overall latency unmeasured. | Less synchronous hint work for broad Command Center queries; likely modest with the bundled command set. |
| N13: Locale/ISO dates | Prepared formatting saves about 0.20-0.25 ms per 512 uncached date cells; roughly 0.02 ms for 40 dates, excluding layout/paint. Most saving comes from resolving the pattern once in either mode, not ISO itself. | Consistent local 24-hour dates and four-digit years if selected; little perceptible performance benefit. Locale stays the default. |

For scale, if a removable component accounts for 20% of an interaction's elapsed
time, halving that component saves about 10% overall, ignoring new overhead. Its
actual share has not been measured here. Do not add the table's percentages:
N01 and N04 overlap, and N02 affects setup while N03 affects subsequent queries.

Overall expectation for N01-N04 and N09-N10: incremental reductions in UI work and search allocations,
not a dramatic general folder-opening improvement. None of N01-N04 reduces disk
enumeration or the default folder sort. Prioritize N01/N02 for potential visible
benefit, N03 for bounded temporary memory, then the smaller N04/N09/N10 cleanups.
Validate real interaction timings before deciding that a marginal optimization
is worth maintaining.

N01 applies when a folder finishes loading and columns are fitted, or during
automatic layout/resize. N04 applies during pane painting and sizing. N02 applies
to initial Find preparation (`Ctrl+F` / `Ctrl+Shift+F`); N03 applies to ranked
queries. N09 applies only when status is enabled, after its debounce. N10 applies
to command-palette suggestions; narrowed N12 reduces hint work there. N11 affects
status completion after the snapshot, not folder enumeration. N13 affects only
uncached Modified formatting. None accelerates directory-size calculation or
`Ctrl+F4` sorting itself.

## Alternatives

- N01: blocking all header signals would hide legitimate Qt notifications; guard
  only the existing internal resize handler.
- N02/N04: a persistent cache adds invalidation and memory costs; reuse values
  only within the existing construction/request instead.
- N03: a custom ranking algorithm risks tie/order changes; stream into the
  existing `heapq.nlargest` while retaining the same score tuples.
- N09: caching all visible URLs retains substantial memory and is invalidated by
  projections; remove the proven redundant traversal first.
- N10: caching aliases across registrations requires invalidation; hoist only
  invariant lowercase operations within one suggestion pass.
- N11: retaining fresh queries preserves today's freshness but repeats I/O;
  prefer snapshot consistency only if that explicit behavior change is accepted.
- N12: a whole-opening candidate cache has undocumented lifetime assumptions;
  a per-pass hint map removes redundant scans without freezing command state.
- N13: optional ISO retains user choice. Pattern reuse in default Locale gives
  nearly the same formatter saving; forcing ISO is not a performance strategy.
- N05-N08: keep the current behavior until separate designs resolve their signal,
  latency, memory and Qt-thread tradeoffs.
- Keep current code if parity fails or measured overhead outweighs the savings.

## Runtime Effects

- No added startup/idle jobs, timers, I/O, processes, threads or persistent state.
- N01/N04 reduce Qt-thread work only during layout/decoration requests; they add
  no per-directory scan work and keep existing icon cache/queue limits.
- N02 adds a string-equality branch but avoids duplicate normalization for equal
  pairs. N03 bounds retained ranking candidates by the result limit while scoring
  the same entries; iterator overhead needs measurement on small inputs too.
- N09 removes Qt-thread work only when status snapshots are requested. N10 adds
  no work outside an active command-palette suggestion pass.
- Conditional N11 adds one reference per status entry and avoids eligible worker
  size queries; status disabled still creates no snapshot work. Narrowed N12
  retains only a per-pass hint map, not a per-opening visibility/alias cache.
- Optional N13 adds one existing-settings lookup and immutable format per column,
  never per-row settings work. No automatic save or live-switch subscription;
  restart applies the setting. Formatting and sort timestamps stay local-time.
- Find unused: no matcher work. Status disabled: no status snapshot work.
  Existing cancellation and stale-result checks remain; N01 restores its guard
  after errors, and N04 retains fallback behavior.

## Tests

Before each implementation, add a failing regression/call-count check in the
existing test home. Run it immediately after the edit, then the relevant owner
and Qt tests below. Keep performance tooling outside ordinary test discovery.

Required focused homes for an approved implementation:

| Candidate | Existing Test Homes And Required Additions |
| --- | --- |
| N01 | `fman_unittest.impl.view.test_resize_cols_to_contents`; Qt `UniformRowHeightsIT` and `SnapshotFilterBarIT`. Add the counted batch/guard test and native resizing/empty-model/font/scrollbar regressions. |
| N02, N03 | `fman_unittest.test_search_file_fuzzy` and `fman_unittest.test_listing`; Qt `SnapshotFilterBarIT`, `SearchFileSyntaxIT`, `SearchFileMetadataIT`. Add normalization counts, reference-ranking parity, bounded-allocation and cancellation cases. |
| N04 | `fman_unittest.test_listing`; Qt `SnapshotFilterBarIT`. Extend icon coverage through `ListingModel.data`, retaining direct-call and worker-lifecycle checks. |
| N09 | `fman_unittest.test_listing` and `fman_unittest.impl.test_status_bar`. Add a pane-snapshot completeness regression covering empty and filtered listings without a second entry traversal. |
| N10 | `core.tests.commands.test___init__` and Qt `CommandPaletteRecentIT`. Add counted normalization and exact suggestion/highlight/order cases. |
| N11 | `fman_unittest.impl.test_status_bar`, `fman_unittest.test_listing` and `core.tests.fs.test_zip`. Add known/zero/unknown/reparse sizes, preserved file cap and cancellation, disabled behavior, per-entry memory, deliberate after-scan changes and zero cold provider/7-Zip calls for known sizes. |
| N12 | `core.tests.commands.test___init__` and Qt `CommandPaletteRecentIT`. Add per-pass hint traversal counts, unmatched-query behavior, duplicate/malformed shadowing and dynamic visibility/alias/binding changes within one opening. |
| N13 | `core.tests.fs.test_columns` and `fman_unittest.test_listing`; configuration, restart and native pane checks in [DateFormat](../Plan/DateFormat.md). Exercise snapshot `text` and compatibility `get_str`, locale parity, ISO output, DST, invalid values, resolution counts and unchanged sorting. |

Exact focused commands for the completed six-item batch are recorded in
Validation Results. Use the existing project interpreter; no new environment.

Additional commands only if the corresponding option is selected:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.impl.test_status_bar', 'fman_unittest.test_listing', 'core.tests.fs.test_zip'], env=build._environment(), timeout=120).returncode)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_columns', 'fman_unittest.test_listing'], env=build._environment(), timeout=120).returncode)"
```

The first optional command covers N11; the second covers N13, whose independent
DateFormat restart/native checks are also required. Narrowed N12 uses the N10
command/Qt homes in the base commands. Add status snapshot Qt coverage using the
existing integration harness rather than relying on summary unit tests alone.

Start with just the changed candidate's regression, then its listed homes. Run
native Qt checks without the offscreen override before accepting N01/N04. For
future timing comparisons use the existing pane/filter/fuzzy/navigation fixtures,
unchanged counts/repetitions, same environment and compatible harness; report
query setup, first populated paint and loaded-input latency separately. Do not
turn an isolated call-count probe into a catalog statistic. No automatic full
suite, build or performance-catalog run is required.

Design-pass evidence collected before implementation: normalization call counts and equal output;
current ranked-list size and iterator/list top-K parity; cached decoration key
call counts; offscreen three-width layout/guard parity; sole-producer searches
for status completeness; and a 3.37 ms median status-pass microprobe. All probe
assertions passed. N10's repeated lowercase calls were established by direct
control-flow inspection; no timing claim is made. Native UI behavior, complete
candidate implementations and end-to-end speedups remain unverified. Memory
conversions and estimates were checked; no application tests were run for this
documentation-only design. Document validation checks required sections,
accepted N01-N04/N09-N10, local links and whitespace, including
`git diff --check -- Plan/CodeReview004.md Plan.md` and untracked-file checks.

Consolidation evidence: current formatter versus prepared Locale/ISO output and
counts passed under en_US/en_GB/de_DE with the timing protocol in N13. The narrowed
N12 helper matched current hints on ordinary and malformed/shadowing fixtures;
the N11 extra tuple reference measured 8 bytes. These probes did not implement
settings, status payloads or palette changes in production. The original three
reviewers' records and measurements remain below; their proposed estimates are
not all endorsed by the current dispositions. Validate this update with required
sections, unique N01-N13 definitions, preserved reviewer history, links, arithmetic
and `git diff --check -- Plan/CodeReview004.md Plan/DateFormat.md`. No application
tests, full suite, portable build or performance catalog were run in this pass.

## Implementation Steps

1. N01: test automatic sizing counts and geometry, apply the local guard, then
   validate native resizing, manual column dragging and exception restoration.
2. N02: test equal/unequal name-path normalization, reuse the equal result, then
   verify Unicode, cancellation, result/highlight parity and matcher setup cost.
3. N03: test ranking parity and cancellation, stream ranked tuples, then measure
   peak allocation and query time for small and many-match inputs.
4. N04: test decoration through the model, pass the computed key to icon lookup,
   then verify fallback, invalidation, queue bounds and native paint/scroll behavior.
5. N09: test pane snapshot completeness without a second traversal, use the
   complete-listing invariant, then verify status summary and disabled behavior.
6. N10: add counted normalization tests, hoist query/alias lowercase operations,
   then verify command suggestions, highlights, ordering and recency.
7. Only if selected, add N11 after N09 with approved freshness/fallback semantics,
   and narrowed N12 alongside N10 without per-opening visibility caching.
8. Only if selected, implement N13 through the canonical DateFormat steps,
   including both formatting methods, default Locale, restart and native checks.
9. Do not implement N05-N08 or original per-opening N12 without another design.
10. Run the selected focused commands, record measured benefits and limitations,
   and update the changelog for the actual implemented changes.

## Acceptance Criteria

- N01 performs one minimum-width pass per tested automatic batch with unchanged
  geometry and manual resize behavior; the guard is restored after errors.
- N02 normalizes once per equal pair and twice per unequal pair, preserving
  search results, Unicode highlights and cancellation.
- N03 retains bounded ranking candidates with unchanged ordering/highlights,
  lower peak allocation on many-match queries and no material latency regression.
- N04 computes at most one required key per model decoration request, with
  unchanged shell arguments, fallbacks, notifications and queue bounds.
- N09 performs no second completeness traversal and preserves complete/limited
  status results for the snapshot listing model.
- N10 lowercases the query once and each visited alias once, with exact suggestion,
  highlight, order and recent-command parity.
- If selected, N11 makes no provider query for eligible known snapshot sizes,
  preserves the file cap and fallback/cancellation behavior, and passes explicit
  tests for the approved snapshot-freshness difference and extra payload memory.
- If selected, narrowed N12 scans bindings at most once per suggestion pass for
  hints, retains malformed/shadowing behavior and keeps visibility/aliases live.
- If selected, N13 preserves default Locale output and sorting, resolves the
  pattern once in both formatting paths, and applies optional local-time ISO
  formatting after restart. Follow DateFormat's independent acceptance checks.
- N05-N08 remain unimplemented unless separately redesigned and reviewed.
- Focused unit/Qt/native checks for selected work pass; record unavailable checks
  explicitly. No public API, lifecycle or benchmark-method change; N13's existing-
  mechanism setting is the sole optional persistence addition. No hidden shift
  of work into the post-render interaction period.

## Reviewers

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Reviewed N01-N04 as four independent, low-risk optimizations with
  local probe evidence, explicit runtime costs and testable acceptance criteria.
  Component savings are distinguished from unmeasured end-to-end gains. No
  implementation or benchmark-method change is authorized by this proposal.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: N01-N04 approved as written; each is owner-local, order-preserving
  and testable by call counts. Notes: N01 must also cover the `resizeEvent`
  path, which calls `_resize_cols_to_contents` with the previous widths and is
  the batch most often re-entered; N02's equality test should compare the raw
  strings before normalization (`entry.name == entry.relative_path`), which is
  exactly the flat-listing case `ListingSearch`/`index_listing` produce; N03
  is memory-only as stated (`nlargest` over a generator scores the same
  entries) and should keep the `-index` tiebreak; N04 is a two-line change.
  Added N05-N08 from the listing model's hot paths, measured on the
  202,603-entry reference folder: skip reprojection when a rescan returns an
  equal `Listing` (10.7 ms compare vs ~300 ms projection + reset — the largest
  win here, on every refresh/notification without a change); reduce the
  cooperative worker's `sleep(0.001)` cadence (75 yields cost 113 ms of a
  300 ms projection on Windows); cache visible-row URLs for status snapshots
  (62.8 → ~38 ms per snapshot on Qt when the extended status bar is on);
  build the projection row map lazily (11.9 ms / ~10 MB per keystroke).
  Checked and dropped: `Modified.text` locale/format lookups (0.9 ms per 512
  cells — not worth a cache). No code changed.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context Window: 272K
- Outcome: Approved N01-N04 and added N09-N10: remove a redundant complete-status
  traversal and hoist invariant command-palette lowercase operations. Deferred
  N05-N06 because their current forms alter refresh/scheduler semantics; rejected
  N07-N08 because they add substantial retained memory or potentially unbounded
  Qt-thread work. No application code changed or implementation authorized.
### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Agree with the dispositions of N01-N10; N09/N11 and N10/N12 share
  owners and should be sequenced together. Added N11: status totals query every
  file through the provider although the snapshot has sizes; inside archives
  each query starts a 7-Zip process (40-file probe: 40 processes, 303 ms, equal
  sizes), so large archives with the extended status bar pay up to 5,000
  processes per recalculation. Added N12: the command palette recomputes
  visibility for about 82 pane commands and rescans 74 key bindings per matched
  command on every keystroke; build both once per opening, with an equivalent
  single-pass shortcut map. Checked and rejected Go To search-connection reuse
  (under 1 ms per keystroke) and `Size.keys` directory tuples (sort semantics).
  No application code changed.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Consolidated the three additional reviews into a six-item base
  recommendation, conditional N11 snapshot-status semantics, narrowed per-pass
  N12 hints and optional N13 Locale/ISO dates. Preserved prior records. Verified
  date output/counts in three locales, measured full uncached formatter cost,
  checked narrow hint-map parity and status reference overhead. Distinguished
  component/worker savings from unmeasured first-paint and input latency; no
  implementation authorized or application/benchmark protocol changed.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Implementation review of N01-N04, N09, N10; **approved**. Diffs are
  exactly the owner-local changes described: `_apply_column_widths` saves and
  restores `_handle_col_resize` around the batch (nested use from
  `_on_col_resized` restores correctly because the outer handler's `finally`
  runs last); `Matcher.__init__` reuses the normalized name when
  `entry.name == entry.relative_path`; `_fuzzy` and the ranked `_extended`
  branch feed `(score, -index, entry)` generators to `heapq.nlargest` with the
  unranked early exit preserved; `ListingModel.data` passes the computed key
  to `ListingIcons.icon(key=...)` with direct callers unchanged;
  `get_status_snapshot` reports `all_rows_loaded=True` from the snapshot
  invariant; the palette lowercases query and alias once. Re-ran both gates:
  unit 242 OK (2 expected skips), native Qt 36 OK. Probe on the 202,603-entry
  reference folder: matcher setup 217 ms; ranked queries `1`, `19`,
  `199 | 05` return 100 results with a `tracemalloc` peak below 0.1 MiB (the
  old path retained ~2.7 MB of score tuples per 20k matches, i.e. ~27 MB
  here). Notes, none blocking: (1) with the guard, a column that Qt clamps to
  its `minimumSectionSize` during a programmatic batch no longer triggers the
  redistribution `_on_col_resized` used to perform; fixtures showed identical
  widths, so the ideal-width math already respects minimums, but a cramped
  three-column native case at 100%/150% scaling is worth one manual glance.
  (2) `get_status_snapshot` now hard-codes completeness; if a partial-listing
  producer is ever added, `StatusEntry.is_loaded` must be wired back. (3) The
  deferred N05 remains the largest available win in this area; its
  disposition correctly identifies the observable notifications that a
  no-change short-circuit would suppress, and a variant that still emits
  `transaction_ended`/`files_changed` while skipping projection and reset is
  the shape to design next. Dispositions of N05-N08, N11-N13 accepted.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Addressed all three nonblocking implementation remarks. Cramped
  native column geometry matches the old handler-driven path at verified 1.0
  and 1.5 device-pixel ratios. Added complete-status producer coverage without
  reintroducing the traversal. N05 remains worth a separate design, but two
  retained notifications alone do not preserve commit/cursor/callback behavior.
  No production correction or expansion to deferred scope is justified.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Independent implementation review of N01-N04, N09 and N10.
  Production diffs match their designs: the N01 guard restores the prior flag in
  `finally`; N02 reuses the normalized name only for equal raw strings; N03 keeps
  `(score, -index, entry)` with unique tie keys, the unranked early exit and
  cancellation inside the generators; N04 keeps direct `icon` callers working;
  N09 and N10 are exact. Unit gate re-run: 243 tests, OK, 2 skips.
  **Blocking finding (reproduced):** the offscreen Qt gate now fails.
  `UniformRowHeightsIT.test_cramped_column_batches_preserve_clamped_geometry`
  fails deterministically under `QT_QPA_PLATFORM=offscreen` (two runs, 2
  failures each: `minimum=-1` and `64` at `width=960`) and passes natively.
  An in-memory probe with the test's fixture gave old `[735, 120, 111]` versus
  guarded `[715, 120, 111]` offscreen, both wider than the 919 px viewport,
  and identical `[748, 100, 95]` natively. The follow-up gate ran this class
  only with `QT_QPA_PLATFORM=windows`, but `build.py test` and the release
  workflow run offscreen, so the next CI run would fail. Before release,
  determine which width is intended (the old re-entrant pass adds 20 px to
  the first column) and either correct the guard or make the parity assertion
  platform-independent without weakening native coverage; then re-run the
  offscreen gate. Until then this task should not be treated as complete.
  Non-blocking: the changelog's performance note and component figures are
  consistent with the recorded probes. No application code changed by this
  review.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Reproduced the Opus offscreen blocker and traced the old handler's
  intermediate 20-pixel redistribution. The intended guarded result is the
  sizing algorithm's output with Qt section minimums, not that extra width.
  Corrected the regression oracle on every platform while retaining native
  old/new parity. All focused offscreen/native gates now pass. The nonblocking
  performance-note remark requires no change; figures and scope remain valid.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revalidated the supplied offscreen-oracle correction against the
  latest implementation review. Exact ideal/clamped widths and one sizing pass
  remain asserted on every platform; native legacy parity is retained. Both
  recorded focused commands passed again: 243 unit tests with two expected
  skips, and 37 Qt tests each offscreen/native 100%/native 150%. The nonblocking
  performance-note remark needs no edit. No remaining blocker or new code
  change; N05 remains a separately approved design recommendation.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Final production-diff audit and focused correctness/performance
  verification found no additional defect. Exact baseline parity passed 1,250
  matcher, 40 cancellation and 150 palette cases. Repeated probes confirm about
  45% less flat matcher setup time and 99% lower many-match ranking allocation;
  small-input overhead remains explicit. Unit and all three Qt gates passed.
  No code correction, broader feature approval or whole-application speedup claim.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Code-quality review found no blocking structural or simplicity
  concern in the six approved changes. Existing ownership is preserved without
  new caches, services or concurrency. Recommend a short producer contract
  docstring for `ListingModel.get_status_entries`: completeness describes loaded
  displayed rows, not pending scans or known metadata. The local `_extended`
  generator's ranked/unranked yield shapes add some reading cost, but do not
  justify extra abstractions now. Regression-test detail is proportionate to
  the Qt/reentrancy and ordering risks. Assessment only; no source changes or
  repeated runtime gates. Prior final verification remains applicable.

## Implementer

### 2026_09_25 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented only N01-N04, N09 and N10. Focused unit and offscreen/native
  Qt gates passed; old-method replay confirms regression sensitivity. Ranked
  query peak allocation fell substantially with unchanged results; native
  geometry and warm paint cost were preserved. Unselected proposals stay open
  in CodeReview099/DateFormat. No settings, public API or benchmark-record change.

### 2026_09_25 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Added cramped-column parity and complete-status producer contract
  tests. Preserved the supplied implementation review verbatim in this canonical
  file and removed its identical Plan duplicate. Focused unit gate: 73 passed;
  native sizing/snapshot gate: 33 passed at each of 100% and 150% scale. Test
  and documentation changes only; application and changelog remain unchanged.

### 2026_09_25 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Fixed the cramped-column test's cross-platform oracle and added an
  exact one-pass assertion. Unit gate: 243 tests, two expected skips; Qt gate:
  37 passed offscreen and 37 at each native scale, 100% and 150%. Test-only
  correction; production sizing, changelog and saved measurements unchanged.

### 2026_09_25 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Completed the approved clarity follow-up by documenting the complete
  displayed-row contract on `ListingModel.get_status_entries`. Pending scans
  and unknown metadata do not invalidate that guarantee. Existing contract
  regression passed. No behavior, matcher structure or changelog changes;
  canonical task and index remain completed.

## Validation Results

Environment: existing Python 3.14.7, PyQt 5.15.11, Qt 5.15.15 on Windows.
`python` below denotes that existing project interpreter; the session invoked
it by its absolute path. No dependencies or environments were added.

### Status Contract Follow-Up

Final clarity follow-up completed on 2026-09-25. Immediately after the docstring
edit, ran the existing contract regression:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_listing.ListingTest.test_status_entries_are_complete_displayed_rows_during_pending_scan'], env=build._environment(), timeout=60).returncode)"
```

One test passed (0.007 s), covering displayed rows during pending scans and
unknown metadata. Editor diagnostics, scoped whitespace and completion-index
checks passed. No new behavior or tests; broader runtime gates were not repeated
for this documentation-only change. The canonical file remains under `Done/`
and its `Plan.md` link remains under Completed.

### Focused Gates

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.impl.view.test_resize_cols_to_contents', 'fman_unittest.test_search_file_fuzzy', 'fman_unittest.test_listing', 'fman_unittest.impl.test_status_bar', 'core.tests.commands.test___init__'], env=build._environment(), timeout=120).returncode)"
python -c "import build, os, subprocess, sys; environment=build._environment(); environment.update(QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts')); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.UniformRowHeightsIT', 'fman_integrationtest.test_qt.SnapshotFilterBarIT', 'fman_integrationtest.test_qt.SearchFileSyntaxIT', 'fman_integrationtest.test_qt.SearchFileMetadataIT', 'fman_integrationtest.test_qt.CommandPaletteRecentIT'], env=environment, timeout=180).returncode)"
```

- Unit gate: 242 tests, 240 passed, two expected skips (opt-in fzf reference and
  unavailable directory-symlink creation), 0.956 s.
- Qt gate: 36 passed offscreen (1.125 s). Repeated the same command with
  `QT_QPA_PLATFORM='windows'`: 36 passed (2.063 s). Offscreen
  `propagateSizeHints` warnings were non-failing platform messages.
- After adding mouse-driven header dragging, reran `UniformRowHeightsIT` alone
  with the same Qt command/environment and `timeout=60`: three passed native
  (0.199 s), three passed offscreen (0.046 s).
- Immediate checks also passed: sizing module 14; matcher module 75 with two
  expected skips; matcher plus listing 119 with those same skips; five icon
  lifecycle/model cases; status module plus snapshot Qt regression 15; palette
  recent-command class 17. The first sizing guard run intentionally failed two
  regressions before the production fix.

Coverage includes one minimum-width pass per automatic batch, prior-flag and
exception restoration, real header signals/dragging, empty/repopulated models,
font/row geometry, Unicode matching/highlights, cancellation and stable ties,
unranked early exit, model icon misses/hits/notifications, direct callers,
provider/reparse/offline fallbacks, queue bounds/start-failure recovery, complete
empty/filtered/20,000-entry status snapshots, partial summary compatibility,
palette lowercase counts, recency and live visibility/aliases/bindings.

### Baseline And Cost Probes

Disposable in-memory probes used `build._environment()` and the existing
interpreter, leaving benchmark tooling and saved records unchanged:

- Loaded old methods from `git show HEAD:<owner path>` as UTF-8 with `ast` and
  patched one method at a time. New regressions rejected old N02 preparation,
  both old N03 ranked paths, old N04 model decoration, N09 snapshot traversal
  and N10 palette lowering. N01 was already demonstrated red before editing.
  Initial probe-launch quoting/encoding errors were corrected by sending source
  through stdin and explicitly decoding Git output as UTF-8.
- Matcher fixture: 100 or 20,000 flat `SearchEntry` records named
  `report_%05d.txt`, distinct numeric URLs, default top-100 limit. Warm each
  operation, then nine batches of three calls, alternating old/new order;
  report median milliseconds per call. Measure one separate `tracemalloc` peak
  after `gc.collect()` per operation. Compare all query outputs exactly.

| Entries | Operation | Old / New Median ms | Old / New Peak Bytes |
| --- | --- | --- | --- |
| 100 | Preparation | 0.2160 / 0.1198 | 26,716 / 21,016 |
| 100 | `rpt` | 0.1727 / 0.1931 | 15,940 / 25,644 |
| 100 | `rpt !tmp` | 0.2289 / 0.2523 | 17,820 / 27,620 |
| 100 | `missing` | 0.0708 / 0.0706 | 1,334 / 2,440 |
| 20,000 | Preparation | 44.5317 / 24.9113 | 5,206,672 / 4,066,672 |
| 20,000 | `rpt` | 36.9808 / 36.7025 | 2,744,724 / 25,996 |
| 20,000 | `rpt !tmp` | 47.7925 / 47.7138 | 2,746,612 / 27,996 |
| 20,000 | `missing` | 15.1315 / 15.3584 | 1,334 / 2,504 |

Ranked peak allocation drops about 99% on the many-match fixture. At 100 entries,
iterator/heap overhead adds about 0.02 ms and 10 KB versus the old sized-list
path. Large-query times are similar; this does not promise faster typing.

- Native Qt: used the existing `FilterBarIT` fixture with cached icon fallbacks.
  Compared old/new width application plus model decoration in memory. Each
  cycle resized to 960x600, 1280x800 and 1440x900, requested scrolling/sizing,
  processed events and grabbed non-null frames. Rotated order over ten batches,
  discarded the first, with one warmup cycle and three measured cycles per
  implementation per batch. Median cycle: 33.3398 ms old / 33.4224 ms new;
  identical column widths at all sizes. No material warm-paint regression or
  measured whole-application speedup is claimed.

### Completion Checks And Limits

- Editor diagnostics, changed-file Python syntax/duplicate-test checks,
  Markdown links, required task sections, append-only reviewer history and
  whitespace checks passed. Changelog records the six delivered changes.
- README unchanged: no commands, shortcuts, settings or workflows changed.
- No full correctness suite, performance catalog, clean/freeze/package or new
  startup/cold-first-paint benchmark was run. Physical human UX checks and wider
  release gates remain outside this batch in CodeReview099; native automated
  checks do not close its unrelated SearchFiles label-width issue.
- N05-N08, N11-N13, public API, status-size freshness, shortcut lookup strategy,
  enumeration, directory-size calculation and `Ctrl+F4` sorting are unchanged.

### Implementation Review Follow-Up

All three Claude Fable 5.1 remarks were addressed, including the nonblocking
suggestions:

1. **Cramped sizing:** added
   `UniformRowHeightsIT.test_cramped_column_batches_preserve_clamped_geometry`.
   It compares the guarded batch with the previous signal-driven implementation
   using three populated columns, logical widths 180/240/480/960 and default,
   64 and 160 pixel section minimums. All 12 cases have identical final widths
   and respect Qt section minimums at both tested scales. A viewport narrower
   than the section minimum total can still overflow, just as before; the test
   does not assume all content minima fit. No sizing algorithm change is needed.
2. **Status completeness:** added
   `ListingTest.test_status_entries_are_complete_displayed_rows_during_pending_scan`.
   It pins the producer contract for local, archive and process locations,
   empty/filtered/reordered rows, missing size/mtime metadata and a pending
   replacement listing. Completeness describes displayed rows, not available
   size metadata or completion of an in-flight scan. Existing no-traversal and
   partial/limited-summary tests still pass. A future partial-listing producer
   must carry its completeness to `get_status_snapshot` (or restore an
   `is_loaded` reduction) and update these contract tests; do not add that
   unused machinery or recurring traversal now.
3. **N05:** recommend a separate design, not an implementation in this batch.
   `_commit` also drives `all_rows_loaded`, `committed`, pending cursor
   resolution/retirement, column/navigation callbacks, sort notification and
   cache invalidation. Captured filter/search/column state can change while a
   scan runs. Merely emitting `transaction_ended` and `files_changed` does not
   preserve those behaviors. The constrained next-design requirements are
   retained in [CodeReview099](../Plan/CodeReview099.md#n05-next-design-requirements).

Exact focused commands, with `python` denoting the existing project interpreter:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.impl.view.test_resize_cols_to_contents', 'fman_unittest.test_listing', 'fman_unittest.impl.test_status_bar'], env=build._environment(), timeout=120).returncode)"
python -c "import build, os, subprocess, sys; environment=build._environment(); environment.update(QT_QPA_PLATFORM='windows', QT_AUTO_SCREEN_SCALE_FACTOR='0', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts')); outcomes=[subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.UniformRowHeightsIT', 'fman_integrationtest.test_qt.SnapshotFilterBarIT'], env=dict(environment, QT_SCALE_FACTOR=scale), timeout=120).returncode for scale in ('1', '1.5')]; sys.exit(max(outcomes))"
```

- Unit gate: 73 passed, no skips (0.665 s). Native gate: 33 passed at 100%
  (2.591 s) and 33 at 150% (2.806 s), no skips.
- Immediate checks: new cramped case passed at 100%; sizing class four passed
  at 150%; new status contract plus snapshot capture/summary tests seven passed.
- A disposable probe wrapped the native view's `grab` during the four sizing
  tests, asserted view and pixmap device-pixel ratios of 1.0/1.5, and generated
  temporary native contact sheets at cramped widths 180/480 for each minimum.
  Four tests passed per scale with all captures non-null. This is automated
  native scale/rendering coverage, not a human or mixed-monitor DPI UX check.
- Canonical review transfer was checked with
  `git diff --no-index -- Done/CodeReview004.md Plan/CodeReview004.md` before
  deleting the identical Plan copy. Prior reviewer records are preserved.
- No production code, changelog, public API, optional feature behavior or
  benchmark records changed. No full suite, catalog, clean/freeze/package or
  new dependencies. Editor diagnostics and focused document/whitespace checks
  passed; physical mixed-monitor scaling remains untested.

### Offscreen Review Resolution

The Claude Opus 5.5 blocker was valid: the newly added cramped-column test
failed twice offscreen at width 960 with default/64-pixel section minimums.
The prior follow-up tested native scales but missed the required offscreen
rerun. That gap is closed by the focused gates below; no test is skipped.

- **Intended widths:** from current widths `[300, 100, 160]`, content minima
  `[332, 120, 111]` and the existing 946-pixel budget, the sizing algorithm
  returns `[715, 120, 111]`. The old first-column resize callback instead
  redistributes to `[735, 100, 111]` using the intermediate widths. The rest of
  the batch then raises the second column to 120, producing the extra 20 pixels.
  Preserving that re-entrant artifact would contradict N01's single-batch design.
- **Viewport distinction:** `_get_width_excl_scrollbar` uses view width minus
  scrollbar width, not `viewport().width()`. The generic fixture has a visible
  vertical row header and frame, explaining its narrower 919-pixel viewport;
  the actual file pane hides the row header. This pre-existing width-budget
  policy is unchanged, and this test does not claim exact viewport filling.
- **Correction:** the cramped regression now checks the exact ideal widths
  clamped to Qt's `minimumSectionSize`, one minimum-width calculation and guard
  restoration on every platform. The additional old/new equality check remains
  on native Windows. All 12 width/minimum combinations still run offscreen;
  native coverage, including header dragging at both scales, is not reduced.
- **Sensitivity:** an in-memory replay of the old unguarded batch makes the
  corrected regression fail all 12 cases on the one-pass assertion. A separate
  trace reproduced the intermediate values above. No production change is needed.
- **Nonblocking remark:** the changelog's component figures and limitations
  agree with the recorded probes. Kept the performance table, fixed-width
  formatting and caveats unchanged; no new benchmark or speedup claim.

Exact focused commands, using the existing project interpreter as `python`:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.impl.view.test_resize_cols_to_contents', 'fman_unittest.test_search_file_fuzzy', 'fman_unittest.test_listing', 'fman_unittest.impl.test_status_bar', 'core.tests.commands.test___init__'], env=build._environment(), timeout=120).returncode)"
python -c "import build, os, subprocess, sys; environment=build._environment(); environment.update(QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts')); targets=['fman_integrationtest.test_qt.UniformRowHeightsIT', 'fman_integrationtest.test_qt.SnapshotFilterBarIT', 'fman_integrationtest.test_qt.SearchFileSyntaxIT', 'fman_integrationtest.test_qt.SearchFileMetadataIT', 'fman_integrationtest.test_qt.CommandPaletteRecentIT']; outcomes=[subprocess.run([sys.executable, '-m', 'unittest', *targets], env=dict(environment, **settings), timeout=180).returncode for settings in ({'QT_QPA_PLATFORM':'offscreen'}, {'QT_QPA_PLATFORM':'windows','QT_SCALE_FACTOR':'1','QT_AUTO_SCREEN_SCALE_FACTOR':'0'}, {'QT_QPA_PLATFORM':'windows','QT_SCALE_FACTOR':'1.5','QT_AUTO_SCREEN_SCALE_FACTOR':'0'})]; sys.exit(max(outcomes))"
```

- Unit gate: 243 tests, 241 passed and two expected skips (opt-in fzf reference
  and unavailable directory-symlink creation), 1.049 s.
- Qt gate: 37 passed offscreen (1.106 s), 37 native at 100% (2.164 s), and
  37 native at 150% (2.179 s), no skips. Offscreen `propagateSizeHints` messages
  are non-failing Qt platform warnings.
- Immediate validation reran only
  `fman_integrationtest.test_qt.UniformRowHeightsIT.test_cramped_column_batches_preserve_clamped_geometry`
  offscreen through `build._environment()` with Windows Fonts and `timeout=60`:
  two expected failures before the correction, one passing test afterward.
- Editor diagnostics, Python syntax/test-name uniqueness, required task sections,
  local links, append-only history and `git diff --check` passed. Full suite,
  performance catalog and build/package steps were not run. Earlier physical
  mixed-monitor limitations and deferred proposal dispositions are unchanged.

Revalidation on 2026-09-25 used the same two exact commands above against the
already supplied correction: unit gate 243 tests, 241 passed/two expected skips
(1.058 s); Qt 37 passed offscreen (1.133 s), native 100% (3.086 s), and native
150% (3.249 s). Editor diagnostics were clear. No additional test, production,
changelog, benchmark or deferred-feature changes were needed.

### Final Code And Gain Verification

Final check on 2026-09-25 used the unchanged six production diffs against
`bf4d495`. Reviewed guard restoration, raw-string normalization reuse, ranking
ties/limits/cancellation, private icon-call compatibility/fallbacks, complete
displayed-snapshot ownership and live palette metadata. No further defect found.

- Re-ran the two exact focused commands in Offscreen Review Resolution:
  243 unit tests, 241 passed/two expected skips (0.950 s); 37 Qt tests passed
  each offscreen (1.135 s), native 100% (3.065 s), native 150% (3.154 s).
- Disposable differential probe loaded baseline source with `git show` as
  UTF-8. Seed 20260925; 0/1/17/257/1024 entries, regular/fuzzy modes,
  limits 0/1/7/100/2000, 25 ordinary/extended/empty/Unicode queries and mixed
  flat/recursive paths. All 1,250 cases preserved exact entries, order and
  UTF-16 highlights. Forty canceled/noncanceled cases preserved checkpoint
  counts and results. Palette comparison preserved identities, titles,
  highlights, hints and order in 150 cases across Windows/Mac shortcut labels,
  three recency states, alias alternatives and malformed/shadowed bindings.
- Repeated the original matcher protocol: warmup, nine alternating-order
  batches of three calls; separate `tracemalloc` peaks after collection.
  Added unequal recursive-path preparation under the same protocol. Outputs
  and prepared strings matched baseline in every measured case.

| Entries | Operation | Old / New Median ms | Old / New Peak Bytes |
| --- | --- | --- | --- |
| 100 | Preparation | 0.2196 / 0.1210 | 26,716 / 21,016 |
| 100 | `rpt` | 0.1710 / 0.1918 | 15,940 / 25,644 |
| 100 | `rpt !tmp` | 0.2306 / 0.2498 | 17,820 / 27,620 |
| 100 | `missing` | 0.0702 / 0.0710 | 1,334 / 2,440 |
| 20,000 | Preparation | 45.8255 / 25.3024 | 5,206,672 / 4,066,672 |
| 20,000 | `rpt` | 34.8369 / 34.4534 | 2,744,724 / 25,996 |
| 20,000 | `rpt !tmp` | 45.3222 / 45.0047 | 2,746,612 / 27,996 |
| 20,000 | `missing` | 14.1980 / 14.3316 | 1,334 / 2,504 |
| 20,000 | Recursive preparation | 57.3492 / 57.5320 | 5,566,738 / 5,566,738 |

Flat setup used 44.79% less time; ordinary/extended ranked allocation fell
99.05%/98.98%. Small ranked queries still add about 0.02 ms and 10 KB; large
no-match and recursive setup medians increased by 0.134 ms and 0.183 ms.
These small differences are reported, not described as zero overhead.

Repeated the original native warm three-window-size paint protocol at verified
DPR 1.0: ten alternating batches, discard first, one warmup and three measured
cycles each. Exact geometry and non-null frames passed. Median old/new:
31.1702/28.0822 ms; interquartile ranges 30.6527-32.9482/27.6412-30.7894 ms.
Earlier runs were essentially equal; this supports no observed warm-paint
regression, not a stable 10% UI speedup claim.

Conclusion: gains are confirmed with no functional regression in tested paths;
the bounded-allocation tradeoff remains worthwhile. No code change needed.
Editor diagnostics, syntax/test uniqueness, task history/links and whitespace
checks passed. Historical changelog figures and benchmark records are untouched.
No full suite, performance catalog, packaging, cold-start/first-paint benchmark
or physical mixed-monitor check was run; these results do not certify all
providers, external tools or release configurations.