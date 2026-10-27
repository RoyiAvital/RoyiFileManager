# File System and Pane Architecture 003: Item Tables

Status: Design draft, 2026-10-26. Open for review; no implementation authorized.
The public `fman` plug-in API may be replaced (user decision, 2026-10-26).
Pipelines and a Rust engine were added in the second pass the same day; the
third pass reframed pipelines as virtual folders driven from the UI.

## Task

Turn the pane into a general **item table**. A pane shows a set of items from
any source: a folder, an archive, a recursive (flat) listing, or the results of
`fd`, ripgrep or Everything. Every column can be sorted, filtered and searched.
File actions (Copy, Move, Delete, Rename, Open, QuickView) apply to any item
that refers to a file, wherever it was listed.

Every result set is a **virtual folder**. Filter the pane, run Search files
(ripgrep) on what remains, select some results and press Delete: each step
works as it does in a real folder. Any tool can take the current pane's items
or selection as its scope and produces a new virtual folder with history,
Back/Forward and refresh. Internally a virtual folder records the chain of
steps that produced it; no pipeline language is required from the user.

Motivation:

- Search results live in separate QuickTable windows today and cannot be used
  like a pane (no Copy/Move/QuickView, no keyboard workflow, no history).
- File operations refresh panes by rescanning whole folders per notification
  ([CodeReview007](../Done/CodeReview007.md)); the cost scales with folder size.
- Navigation commands read the committed location, not the requested one
  ([CodeReview008](CodeReview008.md) F15).
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
  file operations; the rescans and [CodeReview008](CodeReview008.md) F15 are
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

- Column layout, sort and visible columns are saved per source type.
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
