# File System and Pane Architecture 003: Item Tables

Status: Design draft, 2026-10-26. Open for review; no implementation authorized.
The public `fman` plug-in API may be replaced (user decision, 2026-10-26).
Pipelines and a Rust engine were added in the second pass the same day; the
third pass reframed pipelines as virtual folders driven from the UI.
Reviewed 2026-11-15: needs revision before P0; see the last reviewer record.

## Task

Turn the pane into a general **item table** and generate that table as fast as
possible. Every item is a row with an ID and typed columns. Two motivations:

- **Performance**: the table is the single input of display, refresh, sort,
  filter, Find and every tool. Generating it fast, in a compact form those
  operations read directly, lowers the latency of all of them.
- **Composability and modularity**: sources, columns, tools and actions meet
  only at the table. The rows one tool produces are the input of the next, as
  objects flow through a PowerShell pipeline, and a new source or column needs
  no change to the pane.

A pane shows a set of items from any source: a folder, an archive, a recursive
(flat) listing, or the results of `fd`, ripgrep or Everything. Every column can
be sorted, filtered and searched. File actions (Copy, Move, Delete, Rename,
Open, QuickView) apply to any item that refers to a file, wherever it was
listed.

Every result set is a **virtual folder**. Filter the pane, run Search files
(ripgrep) on what remains, select some results and press Delete: each step
works as it does in a real folder. Any tool can take the current pane's items
or selection as its scope and produces a new virtual folder with history,
Back/Forward and refresh. Internally a virtual folder records the chain of
steps that produced it; no pipeline language is required from the user.

Background:

- Search results live in separate QuickTable windows today and cannot be used
  like a pane (no Copy/Move/QuickView, no keyboard workflow, no history).
- File operations refresh panes by rescanning whole folders per notification
  ([CodeReview007](../Done/CodeReview007.md)); the cost scales with folder size.
- Navigation commands read the committed location, not the requested one
  ([CodeReview008](../Done/CodeReview008.md) F15).
- Item identity is a string URL; aliases and case rules are handled per feature
  (F04, CodeReview099 C08).
- Latency must improve on [FSPaneArch002](../Done/FSPaneArch002.md): the
  remaining large-folder cost is GIL-held key building, sorting and a full Qt
  model reset.
- Working with virtual folders and virtual files in a pipeline like operations.
  It is easy to search with one tool, filter teh results with another, sort 
  the current view and delete some of the files and copy others.
  Think of virtual folder for favorites, results of file operation, renaming
  view (One column is the original files other is the renamed file), etc...

## Scope

Included:

- Item, column and source model; sources for local folders, archives, drives,
  network roots, processes, flat view, `fd`, ripgrep and Everything.
- Per-column sort, filter and Find in the pane, reusing the QuickTable and CSV
  Table View filter UI (header funnel, Fuzzy/Contains, numeric/date operators).
- Versioned snapshots updated by change sets (deltas) instead of rescans.
- Locations that describe a query (`fd://...`, `rg://...`), so results have
  history, Back/Forward and favorites, and can be rerun.
- File actions on any file-backed item; actions declared by sources.
- A new plug-in API replacing the fman 1.7.5 API; bundled plug-ins migrated.
- Virtual folders: every tool (Filter Bar, column filters, Find files, Search
  files, Everything) can run on the current pane's items or selection and opens
  its result as a virtual folder; a pane API exposes the same chain to plug-ins.
- A Rust engine (PyO3 extension) with the `fd` walker and ripgrep searcher
  embedded as in-process stages.

Excluded:

- CSV/TSV rows as pane items. The QuickView Table View engine stays separate;
  sharing its query/paging design is a later decision.
- Non-Windows platforms, cloud providers and remote protocols beyond the
  existing network roots.
- Visual redesign beyond what column filtering needs
  ([UIDesign001](UIDesign001.md) owns theming).

Compatibility:

- Third-party plug-ins break by design; document migration.
- User settings, sessions and key bindings migrate or reset explicitly; no
  silent loss of favorites or history.
- Subsumes [Flat View](FlatView.md) and the metadata parts of
  [Find Files 003](FindFiles003.md); both are re-scoped onto this model.
  [CodeReview007](../Done/CodeReview007.md) is the interim setting for rescans during
  file operations; the rescans and [CodeReview008](../Done/CodeReview008.md) F15 are
  resolved here.

## Design

### Concepts

- **Item**: one row. It has a stable key within its source, a kind (`file`,
  `folder`, `link`, `match`, `process`, `drive`, ...) and typed field values.
  An item may have a **target**: the file or folder it refers to. File
  actions work on targets; items without targets (a process) only offer
  their source's actions.
- **Schema**: the source's columns. Each column has a value type (`text`,
  `name`, `path`, `integer`, `size`, `datetime`, `enum`, `boolean`), sort
  semantics (natural, numeric, chronological), filter operators and a
  display formatter. Columns can be hidden, reordered and resized.
- **Column contract** (built-in and plug-in columns alike):
  - A column supplies **values of a native type**, not a comparator. The
    engine sorts, filters and finds on those values natively, so a plug-in
    column sorts as fast as a built-in one once its values exist.
  - Optional **sort key** separate from the displayed text, also of a native
    type (for example a version `1.10.2` as a tuple of integers, or a
    composite key). Arbitrary Python comparison functions are not supported:
    calling Python per comparison would undo the native sort.
  - Optional display formatter, called only for visible cells.
  - Values are produced in **batches** on a worker (Python plug-ins receive
    the item batch as columns and return a value array), never per item on Qt.
  - **Cost class**: `inline` values come with the source (name, size, dates);
    `computed` values (hash, image size, folder size, plug-in metadata) arrive
    later as field change sets. Missing values sort last and filters treat them
    as unknown; the view re-sorts when they arrive, as Size does today with
    folder totals.
  - The 150 ms load target covers built-in inline columns. A pane sorted by a
    computed column is complete only when its values are; the column reports
    progress instead of blocking navigation.
- **Source**: produces items for a **location**. A location is a URL-like
  descriptor: `file://C:/src`, `zip://...`, `flat://C:/src`,
  `fd://C:/src?pattern=*.py`, `rg://C:/src?text=TODO&glob=*.py`,
  `everything://?query=...`, `processes://`. A source declares its
  capabilities: navigable children, file-backed items, live updates
  (change sets), refreshable, rerunnable, streaming.
- **Snapshot**: an immutable, columnar item set with a version number.
  Sources publish batches (streaming) and change sets (live). The engine owns
  snapshots; nothing else mutates them.

### Virtual Folders and Chained Tools

User view:

- Each tool has a **scope**: the current folder (today), the pane's current
  items (after a filter or a search) or the selection. Running a tool opens
  its result as a virtual folder in the pane, or in the other pane.
- Virtual folders behave like folders: sort, column filters, Find, QuickView,
  Copy/Move/Delete/Rename on file items, Enter on folders, Backspace to the
  previous step, refresh to rerun the chain.
- The path bar shows the chain as breadcrumbs, for example
  `C:\src > Filter *.py > Search "TODO"`; clicking a step returns to it.

Mechanism (internal):

- A **step** maps input items to output items and declares its output columns
  from its input columns:
  - **Source** (no input): folder, archive, drives, processes, Everything.
  - **Expand** (one item to many): flat view/`fd` walk (folders to entries),
    ripgrep in match mode (files to match items with line and snippet).
  - **Filter**: Filter Bar and column filters, ripgrep files-with-matches,
    `fd`-style name/type/size/date filters on any input.
  - **Shape**: sort, unique, computed columns (for example hash or folder size).
- A pane's location is the chain of steps. Plain folders are one-step chains,
  so history, favorites and Back/Forward store chains.
- Header sorting, column filters and Find run on the materialized result, so
  they never rerun `fd` or ripgrep.
- Execution streams in batches with backpressure and runs in parallel where a
  step allows it. One cancellation token covers the chain. The first batch
  reaches the pane early.
- Live updates flow through steps that can apply change sets incrementally
  (filters, ripgrep per changed file). Other steps mark the result stale and
  rerun on refresh or verification. Deleting files from a virtual folder
  removes their rows directly.
- A text form of the chain exists for serialization. Exposing it as a typed
  command language is optional (decision 6).
- Pane API for plug-ins: read the chain, items and selection as typed batches,
  add a step, open a chain in a pane. Python steps receive columnar batches
  on workers, never one call per item.
- **View query**: column filters, a global filter, multi-column sort and Find,
  per pane. The result is a position vector into the snapshot.

### Layers and Ownership

1. **Sources** (worker threads or helper processes) enumerate, stream and
   watch. They never touch Qt. External tools (`fd`, `rg`, Everything) run in
   their existing process/IPC boundaries and stream parsed rows in batches.
2. **Item store** (one per open location, shared by panes showing it): holds
   the current snapshot and applies change sets. Cache invalidation for
   provider metadata stays synchronous and separate from change delivery.
3. **Query engine** (one worker per pane, latest-wins like `LatestJobs`):
   evaluates view queries against a snapshot and returns position vectors.
   Heavy kernels run in native code with the GIL released.
4. **Table view** (Qt thread only): a model over the position vector. It
   formats only visible cells, keeps cursor and selection by item key, and
   applies small changes with row insert/remove signals instead of a reset.
5. **Actions**: commands receive a selection of items. File actions map items
   to distinct targets (several ripgrep matches in one file are one target).

### Change Sets Instead of Rescans

- A change set lists added, removed, changed and renamed items for one
  location, with the field values the producer already knows (an operation
  knows the size and times of a file it just wrote).
- Producers: file operations (exact deltas), a provider's "name changed"
  (the store re-reads that entry) and "location changed" (full rescan).
- The store queues change sets per location; its worker drains everything
  pending in one pass and publishes one new version. Coalescing needs no timers.
- Panes pull by version. A small delta updates the position vector by binary
  insertion/removal using the current sort keys; a large one re-queries.
- Verification: snapshots built from deltas can drift (no OS watching on
  Windows). Rescan to verify on explicit refresh, after a batch operation
  and when a pane regains focus, reusing the unchanged-listing fast path.

### Latency Design

Current baselines (0.13.1, large folder 200k): first paint 262 ms; Filter Bar
slowest query 290 ms; unchanged refresh 68 ms (mean); every change triggers a
full rescan, re-sort and model reset.

#### Preliminary Measurements (2026-10-26)

Same development PC, warm cache, `flat-large-v1` (200,000 empty files with
long names) and `flat-small-v1` (256). Suite rows: three fresh processes,
median (range). Stage rows: one process, five repetitions, median.

| Suite measurement (in app)            | Small (256) | Large (200,000)       |
| ------------------------------------- | ----------: | --------------------: |
| Folder load to first paint            | 33.8 ms     | 253.8 ms (252-256)    |
| Unchanged refresh to paint            |             | 122-181 ms by pattern |
| Navigation key/wheel to paint         | 6.4-7.8 ms  | 6.3-7.6 ms            |
| Filter Bar query to paint             |             | 56-258 ms by query    |
| Worst Qt heartbeat gap while filtering |            | 15-35 ms              |
| Peak working set (refresh workload)   |             | 220 MiB               |

| Stage at 200,000 entries (current code)           | Time     |
| ------------------------------------------------- | -------: |
| Scan: kernel enumeration + native parser + Listing | 121.8 ms |
| Name keys (C natural keys) + sort                 | 72.0 + 33.6 ms |
| Size / Modified keys + sort                       | 14.2 + 6.5 / 48.2 + 7.5 ms |
| Projection, Name sort, no filter                  | 109.7 ms |
| Filter, Python predicate: `report` / `strasse`    | 81.5 / 105.4 ms |
| Filter: `.txt$` / `?*?*?*?*?*?*?*?Z`              | 46.2 / 229.8 ms |
| Plain `QTableView` model reset + repaint          | 6.9 ms   |
| Plain `QTableView` insert + remove one row, two repaints | 11.9 ms |

Std-only Rust probe on the same names (single thread, no crates):

| Rust stage                                  | Time     |
| ------------------------------------------- | -------: |
| Lowercase keys (Unicode)                    | 19.5 ms  |
| Natural sort, comparator parses each compare | 107.5 ms |
| Substring filter `report` / `strasse`       | 2.8 / 2.5 ms |

Std-only Rust load probe (single thread, `read_dir` with find-data metadata,
one allocation per name and per key):

| Rust load stage                                | Time     |
| ---------------------------------------------- | -------: |
| First 2,000 entries available                  | 1.0 ms   |
| Enumerate 200,000 entries with size            | 106 ms   |
| Compact natural keys (allocating)              | 59 ms    |
| Sort on precomputed keys (`sort_unstable`)      | 20 ms    |
| Total                                          | 185 ms   |

Findings:

- Load is scan (~120 ms) + projection (~110 ms) + Qt (~20 ms). An unchanged
  refresh costs about one scan. Change sets avoid both scan and projection.
- Qt is not the bottleneck: a 200k-row reset and repaint takes ~7 ms, and a
  single insert/remove costs about as much as a reset. Row insert/remove
  signals are for keeping cursor, selection and scroll, not for speed.
- Native filtering is 30-40x faster than the Python predicate (2.5 ms versus
  81-105 ms for substring).
- Sorting is not faster in naive Rust. Gains need precomputed compact keys
  (as the C natural keys already do), unstable sort and parallelism; unmeasured.
- A naive native load (185 ms) is not below 150 ms. Enumeration is the floor:
  FSPaneArch002 estimated ~55 ms kernel time for this fixture, and the current
  C parser adds ~22 ms. Reaching < 150 ms needs NT enumeration with large
  buffers, allocation-free keys built in parallel while batches arrive, and a
  parallel sort: estimated 110-140 ms with ~20 ms of Qt, not yet demonstrated.
- First rows are available in ~1 ms, but a sorted view is only correct after
  the whole folder is read. Folders render once, complete and sorted (user
  decision, 2026-10-26); there is no progressive rendering.
- Not measured yet: the share of rescans in copy time
  ([CodeReview007](../Done/CodeReview007.md) now measures it), glob/fuzzy in
  Rust, a PyO3 round trip, and memory of a native columnar store.

Design levers:

- **Native columnar core**: a Rust engine (see below) holds columns as native
  arrays and packed strings; natural keys, sort, substring/glob/fuzzy filters
  and Find run natively with the GIL released. Python objects are created only
  for visible cells.
- **Incremental sort maintenance**: keep sort keys per snapshot; insert and
  remove by binary search for deltas.
- **Row insert/remove for small deltas**: keeps cursor, selection and scroll;
  reset only for a new location or a re-query (measured cost is similar).
- **Keys during enumeration**: build sort keys per batch while later batches
  are still being read, then sort once the folder is complete.
- **No snapshot cache**: a folder is enumerated every time it is entered; there
  is no history cache and no provisional rendering (user decision, 2026-10-26).
- **Bounded Qt work**: every Qt-thread step is bounded per frame (16 ms);
  formatting and icons stay lazy and cached.

### Native Engine: Rust

Rust is chosen because it makes this engine easier to develop, not for its own
sake (user condition, 2026-10-26):

- The walker and searcher already exist as libraries: `ignore` (fd's parallel,
  gitignore-aware walker), `grep-searcher`/`grep-regex` (ripgrep), `globset`,
  `regex` and a fuzzy matcher such as `nucleo-matcher`. In C each would be
  written or wrapped by hand.
- Embedding them makes `fd` and `rg` first-class stages: no process spawn, no
  JSON parsing, typed items, direct cancellation and shared batches.
- A multi-threaded streaming engine is safer to write in Rust (ownership,
  `Send`/`Sync`, `rayon`); native crashes have already cost time in this project.
- PyO3 builds an abi3 `.pyd`, maps errors to Python exceptions and releases the
  GIL around native work.

Costs: a Rust toolchain in development and CI (installed by the user; the
GitHub Windows runner has one), compile time, a few MB of binary, crate license
notices (MIT/Unlicense/Apache-2.0) in the package, and parity work with Python's
`casefold` and `natural_key`. The existing C `_fsparser` stays until a port is
measured and justified. External `fd.exe`/`rg.exe` remain an optional stage for
flags the libraries do not expose.

### Navigation

- Each pane has a **target location** (requested) and a **shown location**
  (committed). Relative navigation (Backspace, Enter on a child, Back/Forward)
  starts from the target. Superseded requests are canceled as today.
- Query locations enter history like folders. Backspace from a result set
  returns to the location it was started from.
- Cursor restoration uses item keys, including across renames and case-only
  changes.

### Identity

- Local items carry volume serial and file ID; other sources supply their own
  stable keys. Same-file checks, favorites deduplication, comparison and
  rename tracking compare identities, not normalized strings.
- Items without a native identity fall back to the source key and are marked
  as such, so features that need identity can refuse explicitly.

### Plug-in API (replacement)

- `Source` (enumerate, stream, watch, capabilities), `Schema`/`Column`,
  `ItemBatch`, `ChangeSet`, `Action(selection)`, and the location registry.
- Commands receive item selections and targets, not raw URL lists.
- Bundled plug-ins (Core, Everything, FindFiles, SearchFiles, ProcessPane,
  Favorites, Robocopy, checksum and hash tools) are migrated in the same
  release; the old API is removed, not shimmed.

### Persistence

- The sort order stays remembered per folder, as today (`Sort Settings.json`).
- Column layout and visible columns are saved per source type.
- History and favorites store locations, including query locations.
- Snapshots are never persisted.

### Failure Behavior

- A failing source keeps the last snapshot and shows the error inline; partial
  streams are marked incomplete.
- Cancellation stops sources, engine work and helper processes; stale versions
  and stale query results are rejected by version and query revision.
- Deltas that cannot be applied (unknown key, schema mismatch) trigger a
  verification rescan instead of an error.

### Open Decisions

1. Port `_fsparser` into the Rust engine, or keep it in C.
2. Multi-column sort and global filter defaults per source.
3. Whether QuickTable windows remain for plug-ins or are replaced entirely.
4. Whether CSV Table View later shares the item engine or stays DuckDB-backed.
5. Settings migration strategy for column layouts and key bindings.
6. Whether to expose the chain as a typed command language, and its syntax.
7. Fuzzy matcher: port the current scoring or adopt `nucleo-matcher` ranking.

## Alternatives

- **Incremental fixes on the current model** (CodeReview007 deferred refresh,
  CodeReview008 F15 target location): low risk, but keeps rescans, string
  identity and separate search windows. Kept as a fallback if P0 fails.
- **DuckDB in-process for all item sets**: queries release the GIL, but
  ingesting a folder from Python without Arrow/NumPy costs more than today's
  whole load. Rejected for folders; remains the CSV engine.
- **SQLite in memory**: same ingestion cost; weaker natural sort support.
- **A separate engine process for panes**: isolation, but IPC and duplicated
  memory add latency to every navigation and keystroke. Rejected for folders.
- **`QSortFilterProxyModel`**: sorting and filtering on the Qt thread; the
  stalls FSPaneArch001/002 removed would return. Rejected.
- **NumPy/Arrow columnar core in Python**: excluded from the build today, and
  natural sort and fuzzy matching still need custom kernels.
- **C for the new engine**: no new toolchain, but the walker, regex search,
  glob, fuzzy matching and thread-safe streaming would be hand-written or
  wrapped. More code and more crash risk than Rust with existing crates.
- **`fd`/`rg` as external processes only**: works today, but every stage pays
  process start, text parsing and coarse cancellation, and stages cannot share
  batches. Kept as an optional fallback stage.
- **Embedding Nushell or PowerShell**: large runtimes with their own type
  systems; the pane needs a small, typed, file-focused stage set.
- **Rust application with a Python plug-in API (dropping PyQt)**: smaller
  memory, faster start, no GIL in the UI and a single executable. But the data
  path is already native or moves to the Rust engine here, and the rewrite
  would replace Qt widgets, shell integration (icons, context menus, drag and
  drop), QuickView, all plug-ins and the Python test suite. Reconsider only if
  profiles after P3 show Python/Qt as the remaining bottleneck.

## Runtime Effects

- Startup: one Rust extension module loads with the existing C module. No
  helper process for local folders, `fd` or `rg`.
- Build: Rust toolchain and PyO3 build step in `build.py` and CI; freeze
  collects the `.pyd` like `_fsparser`.
- Memory: native columns and packed strings replace per-entry Python tuples; the
  expected footprint per item is lower. Measure at 200k and 1M items.
- CPU: deltas replace rescans; batch operations no longer rescan large
  folders. Native kernels release the GIL, so the Qt thread stays responsive.
- I/O: verification rescans only at defined points; no new polling.
- Threads/processes: one query worker per pane, one store worker per open
  location, existing tool processes for `fd`, `rg` and Everything.
- Cancellation and disabled paths: closed locations release their store;
  sources without live updates add no watchers.

## Tests

- Engine unit tests: sort parity with `natural_key`, filter parity with the
  QuickTable predicates, Find, multi-column sort, Unicode and case rules.
- Plug-in columns: batch value production, separate sort keys, computed values
  arriving late (missing sorts last, re-sort on arrival), and rejection of
  values outside the declared type.
- Chain tests: column propagation, chained tools (filter, then Search files,
  then Delete), Backspace between steps, cancellation from any step,
  first-batch latency, and parity of the embedded
  walker and searcher with `fd`/`rg` CLI output on fixtures.
- Delta oracle tests: random change sets applied to a snapshot equal a rescan
  of the same folder; position vectors equal a fresh query.
- Qt integration: insert/remove rows keep cursor, selection and scroll; no
  reset for small deltas; deleting a pane's location navigates away.
- Sources: streaming, cancellation and error handling for folder, flat, `fd`,
  `rg`, Everything, archive and process sources.
- Actions: Copy/Move/Delete/Open/QuickView on search results; target
  deduplication; refusal for items without targets.
- Performance suite gates: `pane.load.*`, `filter.*`, `refresh.*`,
  `selection.*`, `copy.*`, plus new delta and search-result workloads.
- Manual: keyboard workflow on search results, history and Back/Forward,
  network folders, DPI and theme.

## Implementation Steps

1. **P0 spike and gates**: build a PyO3 module through `build.py` and freeze;
   prototype native sort/filter with the GIL released, an embedded
   walk-and-search chain, and a delta-applied Qt model on the 200k fixture.
   Stop if the targets below are not reachable.
2. **P1 item model**: Item, Schema, Source and Snapshot types; adapt the local
   folder source and current columns behind them with no behavior change.
3. **P2 item store and change sets**: per-location store, change journal,
   cache-invalidation split, file operations emitting deltas; panes pull by
   version (replaces the CodeReview007 deferred refresh).
4. **P3 native core and incremental view**: Rust kernels, binary-insertion
   updates, row insert/remove signals.
5. **P4 navigation**: target/shown locations, query locations in history
   (resolves CodeReview008 F15).
6. **P5 pane column filters and Find**: header funnel, operators per type.
7. **P6 virtual folders and search steps**: step model and chains, tool
   scopes (folder, current items, selection), embedded `fd`/`rg` steps,
   Everything and flat view as sources, breadcrumbs and "open in other pane";
   retire the separate result windows.
8. **P7 plug-in API**: publish the new API, migrate bundled plug-ins, remove
   the old API, document migration.
9. **P8 identity**: identity-based comparisons (F04, C08) and rename tracking.

## Acceptance Criteria

- `pane.load.large` first paint ≤ 150 ms (today 254 ms), sorted and complete,
  with built-in columns. No caching or provisional rendering.
- Filter Bar slowest large-folder query ≤ 100 ms (today 290 ms).
- A single added/removed file in a 200k-item folder repaints within 10 ms of
  its change set, without a model reset or rescan.
- Copying 10,000 files into a 200k-item folder performs no full rescan until
  the batch's verification rescan.
- Worst Qt heartbeat gap ≤ 16 ms during load, filter, sort and deltas.
- `fd`, ripgrep and Everything results open in a pane with sort, filter,
  Find, QuickView and file actions; first rows paint before the tool finishes.
- Filter a folder, run Search files on the remaining items, select results and
  Delete: the files are deleted, their rows disappear without a rescan, and
  Backspace returns to the filtered folder. Column filters on the results do
  not rerun ripgrep.
- Repeated Backspace and Enter navigate relative to the requested location.
- All bundled plug-ins work on the new API; the old API is removed and its
  migration documented.

## Reviewers

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Initial design from the user's direction to rethink the pane as an
  item table over pluggable sources, with change sets, native kernels and a new
  plug-in API. Latency targets and the P0 gate are proposals, not measurements.
  Awaiting review and decisions 1-5.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Added pipelines (typed stages, pipeline locations, pane API) and
  chose Rust for the engine because the `ignore`/ripgrep crates and safe
  concurrency make it easier to develop than C; the P0 gate now includes the
  Rust build. Open decisions extended to 1-7.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Reframed pipelines per the user's clarification: result sets are
  virtual folders, tools take the pane's items or selection as scope, and the
  chain is shown as breadcrumbs. A command language is optional (decision 6).
  A Rust UI rewrite was discussed and not adopted.

### 2026_10_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Added preliminary measurements (suite, stage breakdown, std-only Rust
  probes). Per user decisions: no snapshot cache, no progressive rendering,
  target 150 ms for a complete sorted 200k folder. Specified the column
  contract: typed values and optional sort keys from plug-ins, batch
  production, computed columns arriving as change sets; no Python comparators.

### 2026_11_15 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: Needs revision before P0. The direction holds: enumeration is the
  measured floor and change sets are the largest win. Four findings block
  approval: F01 and F02 (operations on multi-folder and stale rows), F06 (one
  update path) and F15 (split into independent tasks). F12 corrects one speed
  lever. Fixed two dead CodeReview008 links and added the status line; the
  design text is otherwise unchanged. No application code changed.

Requested focus: speed, fewer edge cases, data safety. Priorities are High,
Medium and Low, to avoid the P0-P8 phase names.

#### Data Safety

**F01 - High: batches from several folders can overwrite themselves.**
Virtual folders make multi-folder selections the normal input, but
[FileTreeOperation](../src/main/resources/base/Plugins/Core/core/fileoperations.py)
assumes one parent: the layout comes from `dirname(files[0])` and destinations
are checked only against the disk, before anything runs. Probe: moving
`a\x.txt` and `b\x.txt` into an empty folder left one `x.txt` (from `b`), with
no prompt and both sources gone. Copy silently kept the second. With three
items, one order flattened them and another failed on a missing subfolder.
Paste and drop pass external multi-folder lists to the same class today.
Required: map every source to its destination during preparation and refuse
the batch before any mutation when two map to one name, ignoring case. Define
one layout for multi-folder batches. Drop a selected item that lies inside a
selected folder. Commands that assume one folder (Pack, Batch File Renamer,
Checksum, Robocopy, Compare) refuse multi-folder selections unless they opt in
with tests. Fix the existing overwrite in its own task first.

**F02 - High: result rows describe the past; destructive commands must check
them.** A folder pane rescans on activation. A result set can be minutes old,
spans many folders, and Delete acts on the path. Required: each file-backed row
keeps what was listed (volume and file ID, else type, size and modification
time). Delete, Move and Rename from a virtual folder re-read each target
without following links during preparation and put mismatches in the existing
skipped-errors summary. Rows from `fd`, ripgrep and Everything get the ID from
one stat per returned row (10 µs measured). Decision for the user: whether
ordinary folders adopt this check or keep name-based behavior.

**F03 - Medium: define what a command acts on.** Marks are a subset of the
visible rows today: [the view](../src/main/python/fman/impl/view/__init__.py)
drops marks whose rows a filter hides. Selection "by item key", column filters
and streaming can break that silently. Required: targets are the marked and
visible rows at command capture, else the cursor row. Rows arriving later never
join a running command. Several match rows of one file are one target, and the
confirmation counts targets.

**F04 - Medium: the engine is read-only and the operation layer stays.** State
in Scope that the Rust engine has no filesystem mutation entry points and that
item selection is an adapter in front of the existing `fman.fs` operations.
Snapshot values and change-set fields never parameterize a mutation, as
[PlugIn.md](../PlugIn.md) already requires for listing identities.

**F05 - Medium: contain the walker and searcher.** In-process, a native fault
or a failed allocation (Rust aborts) ends the application during a running
transfer, and a blocked network read cannot be canceled. PDF and CSV previews
use helper processes for this reason. FO01, an undiagnosed native crash during
pane refresh, and CS05 are still open in [CodeReview099](CodeReview099.md).
Required: P0 compares one persistent helper process for walking and searching
(ending it is a hard cancel) with in-process hosting, against a stated
throughput budget. Memory-only kernels (keys, sort, filter, find) stay
in-process. In both cases: row and byte caps per result set with the
"incomplete" marker, unwinding panics and no memory maps.

#### Fewer Edge Cases

**F06 - High: one update path: a hint, then an authoritative re-read.** Drop
"exact deltas" with producer-supplied values. The local filesystem and the
host already emit `notify_file_added/changed/removed(url)` after each mutation.
The store turns each into a re-read of that one entry and derives the change
itself. Probe: `NtQueryDirectoryFile` with the entry name returns the record
the scanner parses. 10,000 of 10,000 single-entry reads equaled the scan
through the same `_fsparser`, at 12 µs each. A missing name returns no record;
the filesystem resolves case and returns the on-disk name. This removes wrong
producer values, name matching, link-metadata rules and identity capture as
separate concerns. It needs no new producer API and is the input a directory
watcher ([Roadmap002](Roadmap002.md) priority 3) would use. 10,000 copied
files cost about 0.12 s of re-reads, against 34-61 s of rescans today
([CodeReview007](../Done/CodeReview007.md)). Keep a coalesced rescan outside
the native scanner's scope (UNC, FAT), when the hint names the location
itself, when the returned name is not the requested one ignoring case
(wildcard or short-name match), and at task end.

**F07 - Medium: a total order, then one merge.** Sorting is stable over
enumeration order, so ties follow scan order. Appended and streamed rows arrive
in another order, so "position vectors equal a fresh query" cannot hold.
Required: every sort ends with a tie-break on the row key. Then replace "binary
insertion for small deltas, re-query for large" with one path: sort the changed
rows and merge them into the retained order. Probe at 200k in Python, an upper
bound for native code: insertion 2.2 ms, re-sorting the previous order 12.8 ms,
same result. Retained keys live along one store lineage and are dropped when a
rescan differs; state this against the R08 refusal in
[FSPaneArch002](../Done/FSPaneArch002.md).

**F08 - Medium: row key, target and identity are three things.** A file ID
cannot be the row key: hard links share it, a match row is a file plus a line,
and one file can appear twice. Define the row key (unique per snapshot), the
target (the URL acted on) and the identity (the check token for F02, marks and
rename tracking). Favorites and history stay lexical: identity needs I/O, fails
offline, and two paths to one folder are different favorites.

**F09 - Medium: result sets are static in the first version.** Remove "live
updates flow through steps" and reruns on verification: regaining focus would
rerun a search. Rows change through the application's own operations on their
targets (the F06 re-read, per target) or an explicit refresh. While a tool
streams, rows append in arrival order and are sorted once on completion, so
rows do not move under the cursor. Back to a result set shows retained rows
under a count and byte cap, or "expired, press Ctrl+R". History and session
restore never start a search.

**F10 - Medium: locations are structured values, not parsed strings.**
`rg://C:/src?text=TODO&glob=*.py` cannot be parsed reliably: application URLs
are not percent-encoded, and `&`, `=`, `#` and `%` are legal in names and
patterns. The archive path parser had this class of bug (fixed in 0.20.4).
Keep chains as typed steps with one serializer for persistence; `fman.url`
functions apply to real locations only. Steps scoped to a selection hold
explicit target lists and are session-only. Decision 6: no command language.

**F11 - Medium: `pane.get_path()` in a virtual folder is undefined.** Copy and
Move default to the opposite pane's path; New folder, Paste, Pack here and the
terminal use the active pane's. These are the [FlatView](FlatView.md) blockers
this plan inherits. Proposal, consistent with the 2026_09_17 approval there: a
chain with one real root returns it and prompts show it; rootless sources
(Everything, processes) have no path and those commands refuse. Carry
FlatView's parity matrix into Tests.

#### Speed

**F12 - Medium: where the 150 ms goes.** Measured at 200k entries (see Review
Validation): kernel enumeration 77-100 ms, C parse 52 ms, Name keys 81 ms, sort
30 ms. Enumeration is the floor and takes half to two-thirds of the budget.

- Large buffers are not a lever. NTFS returned about 64 KiB per call (733
  calls) for 64 KiB, 1 MiB and larger buffers, through both
  `GetFileInformationByHandleEx` and `NtQueryDirectoryFile`; larger buffers
  were slower. The current information class is the cheap one
  (`FileIdBothDirectoryInfo` took twice as long). Remove this lever from
  Findings.
- Overlap is the lever, and it needs enumeration off the GIL: a second Python
  thread recovered 22 ms (195 to 173 ms). The target holds only if parsing and
  key building finish inside the enumeration time on native threads, and
  nothing serial but the sort follows. Gate P0 on that pipeline. Decision 1:
  keep `_fsparser` until the pipeline beats it; F06 reuses it unchanged.

**F13 - Medium: marks on the Qt thread break the 16 ms criterion.** Marks live
in `QItemSelectionModel` and are remapped on Qt at every commit: about 30 ms at
200k marked rows, before Qt's own selection update. Moving a large selection
gives the source pane continuous removals with everything marked. Required:
marks are an engine-side set remapped on the worker and painted from the model,
as the pattern-selection preview already is. Commits are coalesced to one per
frame, and wait while an inline editor or a drag is active (a model reset
closes the editor; probed).

**F14 - Low: two specifications to add.**

- Snapshot representation. Copying immutable columns per delta is O(n): 8 ms
  for the tuple columns at 200k, which cannot meet 10 ms at 1M items. Specify
  append-only columns with per-row validity by version (or chunked columns),
  the compaction rule and the memory while two versions are alive.
- Case folding and natural keys with parity by construction: ASCII in native
  code, other names through Python's own `str.lower` and `casefold`, as
  `natural_keys` does today. Build the folded column at the first filter, not
  at load. Decision 7: port the current fuzzy scoring with the Python matcher
  as the oracle.

#### Scope and Sequence

**F15 - High: this is nine tasks.** [AGENTS.md](../AGENTS.md) asks for
independently planned and completed tasks, and the Rust gate in P0 blocks work
that needs no Rust. Suggested order, each with its own document and gate:

1. The existing overwrite in F01.
2. Target and shown location (CodeReview008 F15).
3. Store, hints and re-read on the current `Listing` model, replacing the
   CodeReview007 setting. Gate: `copy.flat.large` within 15 % of
   `copy.flat.large.deferred`.
4. Row key, total order and model-owned marks (F07, F08, F13).
5. Native kernels behind the same interface; the Rust P0 belongs here, with the
   toolchain target, locked crates, license notices and a frozen-build load as
   exit criteria. Gates: `pane.load.large` and `filter.large`.
6. Results in panes from the existing `fd.exe`, `rg.exe` and Everything, with
   F01-F03 and F11.
7. Column filters and Find.
8. A hosted walker and searcher where a measurement asks for it (F05).
9. The plug-in API last and once ([Roadmap002](Roadmap002.md) wants it stable
   through 1.x): add `Source` beside `FileSystem.scan`, whose result is already
   an item batch, and remove the old API in a later release.

Acceptance criteria to add: no mutation when two sources share a destination;
a replaced target is refused; hidden rows are never acted on; ending the search
helper during a Copy leaves the Copy unaffected; the heartbeat criterion names
its mark counts (none, 1,000, all).

#### Review Validation

Disposable probes through `build._environment()` in temporary folders, removed
afterwards. No application tests, suite, build or performance catalog were run.
The suite fixtures are not on this machine: timings come from a generated
folder of 200,000 empty files with 73-character names, warm, medians of five.

| Measurement                                                     | Result              |
| --------------------------------------------------------------- | ------------------: |
| `scan()`, current code                                          | 173.5 ms            |
| Kernel enumeration only, two folder instances                   | 77-100 ms           |
| `_fsparser` parse and `finish`                                  | 52.4 ms             |
| Name keys / sort                                                | 81.4 / 30.4 ms      |
| Enumerate, parse and keys per batch: one thread / reader thread | 195.0 / 173.3 ms    |
| One added entry: insertion / re-sort / copy of tuple columns    | 2.2 / 12.8 / 8.0 ms |
| Single-entry `NtQueryDirectoryFile`: reused / new handle        | 12.4 / 60.4 µs      |
| Mark capture / restore, 200,000 marked rows                     | 3.3 / 26.0 ms       |

Not verified: anything in Rust, the suite fixtures, network and non-NTFS
volumes, end-to-end timings for F06, and F01 through the Paste and drop
commands themselves (reproduced on `MoveFiles` and `CopyFiles` directly).

### 2026_11_15 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: At the user's request, restated the Task with its two motivations:
  fast generation of the item table, for performance and for composability
  and modularity. Renamed the former Motivation list to Background. User
  clarifications: the native engine is a tool, not the goal, and file
  operations stay outside it, so F04 stands. The load target is judged
  feasible as Windows enumeration time plus 30-40 ms; this is an estimate
  from measured parts, not a demonstration. The F12 note on decision 1 and the
  F15 order are under discussion and not yet revised. No other design text or
  application code changed.

### 2026_11_15 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: User decision: the existing per-folder sort memory stays as is.
  Persistence now says so; the draft had moved the sort to per source type.
  The order proposed in F15 is withdrawn: the plan's own sequence stands.
  Three changes remain proposed and undecided: the spike generates the table
  from a folder, P1 and P3 merge so the table is native before the store is
  built, and decision 1 is settled with enumeration inside the engine.

### 2026_11_15 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Independent design review; needs revision. Added F16-F18 on scan/
  change-set ordering, shared-source cancellation ownership and exact chained-
  tool scope. Earlier F01-F14 concerns are not independently reproduced here;
  the later withdrawal of F15's proposed order is respected. The plan's phase
  sequence, per-folder sort memory and approved API-replacement scope are not
  changed. No application edits, tests, probes or benchmarks were performed.

#### F16 - High: Publication Versions Do Not Define Scan/Delta Ordering

- Evidence: Change Sets queues updates on a store worker and Failure Behavior
  rejects stale versions, but neither defines a full scan's relationship to
  changes accepted while it runs. A version assigned when work finishes is not
  evidence that its input is newer.
- Failure sequence: a verification scan reads a folder before a new file is
  added; the add hint is applied and published; the scan then finishes and
  replaces that snapshot without the new file. A late field-computation result
  can similarly overwrite values after its source item changed. Rejecting old
  pane query revisions does not protect the shared store from these cases.
- Required: define the store's location epoch, scan base/event boundary and
  publication order. Serialize publication and reconcile hints received during
  enumeration before exposing the verified snapshot, or use another explicit
  rule that prevents accepted changes being lost. Field updates must identify
  the input row revision they computed, not merely receive a new version on
  completion. Late callbacks from a closed/reopened location must be rejected.
  This complements F06's authoritative re-read; it does not require trusting
  producer-supplied metadata or rescanning for every hint.
- Checks: deterministically interleave scan, add/remove/rename hints, a late
  computed-column result and location close/reopen. Once a change is accepted,
  an older scan/job must not roll it back. The final store must equal an
  authoritative rescan after all inputs settle.

#### F17 - Medium: Shared Stores Need a Separate Cancellation Lifetime

- Evidence: Layers and Ownership shares one store per open location between
  panes, while Virtual Folders gives a chain one cancellation token and Failure
  Behavior says cancellation stops sources. The owner of a shared source and
  the meaning of its last consumer disappearing are not specified.
- Failure sequence: panes A and B share a folder source; A navigates away or
  cancels its chain. Cancelling that source with A stops B's input. Conversely,
  retaining every source to protect B can leave jobs or watchers running after
  both panes close. Per-pane latest-wins query jobs alone do not decide this.
- Required: distinguish per-pane query/chain cancellation from shared-store
  source ownership. Specify acquisition/release, the final-consumer stop path,
  cancellation of unshared downstream stages and stale-callback rejection on
  reopening. One pane must not cancel work still required by another; no
  consumer must mean no source-specific recurring work.
- Checks: two panes sharing a source while one filters, cancels, navigates or
  closes; close the final pane during enumeration; reopen before an old callback
  arrives. Assert the surviving pane still completes and final release stops
  workers/watchers without blocking Qt.

#### F18 - High: Tool Adapters Must Preserve the Captured Input Scope

- Evidence: tools can take a folder, current pane items or selection, but the
  chain contract does not define an immutable scope capture or how library/CLI
  stages distinguish these inputs. F03 defines action selection and F10 defines
  serialized locations; neither specifies this tool-adapter boundary.
- Failure sequence: Filter `*.py` then Search files is implemented by passing
  the folder root to the searcher, which also searches excluded files. Treating
  an explicitly empty item/selection scope as an omitted scope can expand it to
  the whole folder. The resulting rows then become apparently valid input to
  Copy/Delete even though the user never included those files.
- Required: distinguish folder scope, a captured view result and an explicit
  selection, including empty scope versus no scope. Bind item/selection scope
  to its snapshot/query revision so later arrivals or UI edits cannot enlarge a
  running tool. Specify when folder rows expand into descendants rather than
  leaving that to each adapter. Embedded and external stages must honor the
  same contract; unsupported provider targets must fail explicitly instead of
  falling back to a real root or URL interpreted as a native path.
- Checks: filtered and empty panes, an empty explicit selection, new rows while
  the tool runs, folder rows, and unsupported archive/provider targets. Record
  exactly which files the searcher opens; excluded/outside-scope sentinels must
  never be searched or become targets of the downstream operation.

#### Review Validation

- Read the complete current plan, including the latest reviewer clarifications.
  F16-F18 are contract/counterexample findings, not new runtime reproductions or
  independent confirmation of the older native timings and mutation probes.
- Validation is document-only: required sections, unique finding IDs, existing
  relative link targets, Pending index placement, whitespace and preservation
  of the complete pre-review document as an unchanged prefix.
- No application source changes, tests, native probes, performance catalog,
  toolchain changes or build/freeze were run. Implementation remains unauthorized.
