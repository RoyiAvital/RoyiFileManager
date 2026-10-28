# Code Review 009: Dead Code, fman Luggage and Test Cost

Status: F01-F19 implemented 2026-10-28 following user selection. Independent
implementation review below records one diagnostic defect (IR01) and further
cleanup candidates F20-F22. Original design/review evidence remains historical.

## Task

Review the whole codebase for these five objectives:

1. Find dead code.
2. Find unused luggage inherited from fman.
3. Find non-Windows code that can be removed.
4. Find excessive protective code that can be removed to increase speed.
5. Find redundant or no-longer-relevant tests that can be removed to shorten
   test time.

Reduce maintenance noise and unnecessary work without weakening data safety,
supported plug-ins or regression coverage. Findings are proposals, not approval
to implement every removal.

## Scope

- Application host, bundled and independent plug-ins, native parser, resource
  registration, build/packaging, CI, developer tools and all test groups.
- Review baseline: version `0.19.2` in [AppMeta.json](../src/AppMeta.json).
  Runtime probes used CPython 3.14.10 on Windows.
- Exclude generated `target`, `site`, bytecode, user settings and third-party
  implementation/license text as cleanup targets.
- Preserve the current fork API, not obsolete upstream listing contracts.
  Internal `fman.impl` classes are not public plug-in contracts.
- No production/test edits, dependency changes, commits, full test suite,
  freeze, clean or performance-catalog runs in this review.
- Previous decisions remain relevant: [005](../Done/CodeReview005.md),
  [006](../Done/CodeReview006.md), [007](../Done/CodeReview007.md),
  [008](../Done/CodeReview008.md) and [099](../Plan/CodeReview099.md).
  Do not reopen resolved findings as new defects.

### Coverage

This was a whole-repository screening pass, followed by direct source reading
and bounded verification of candidates. It is not a claim that every line has
been proven correct or every dynamic reference is discoverable statically.

| Surface | Review performed |
| --- | --- |
| Host: 94 Python files | AST/reference screening; startup, session, loader, model/view, threading, UI services, status and preview paths |
| Bundled plug-ins: 52 Python files outside tests | Registration/import screening; Core operations/archive transports, searches, Favorites, Everything, hashing/checksums, processes and Robocopy |
| Independent plug-in: 2 Python files | Batch Renamer public-API use, capture/preview/preflight/execution boundaries |
| Native parser and 3 Python support scripts | Parser entry points, trusted construction, source/binary pairing and retained reference implementations |
| Unit/integration/Core tests: 116 Python files | AST/test-identity screening; fixture inheritance, dead-contract coverage and subprocess/native-test cost |
| Performance: 22 Python files; miscellaneous tools: 12 | Entry points, historical-source compatibility, duplicated harness code and discovery boundaries |
| Build/spec/workflows | Source/resource inputs, Windows execution, test discovery and Pages screenshot generation |

All 303 Python files in the selected source/build/script corpus parsed with
BOM-aware decoding. Reference searches included configuration and string
dispatch. A source scan alone is not proof that a public API is unused.

## Design

Use this file as the canonical shared review record. Later reviewers:

- Append their own evidence and reviewer metadata.
- Refer to existing finding IDs when confirming or challenging them.
- Give new findings the next unused ID; do not renumber historical records.
- Separate confirmed dead paths, simplification candidates and retained guards.
- State the caller/contract, actual cost, proposed removal and decisive checks.
- Do not equate repeated checks with unnecessary checks, or similar test names
  with identical coverage.

Ownership stays with existing modules. Widgets/models remain on Qt. Workers use
captured plain data; cancellation, stale-result rejection, resource bounds and
failure reporting remain intact. No cache, scheduler, persistence format or
public API replacement is selected here.

## Findings

Cleanup priorities below are not vulnerability severities. P2 means useful
measured/runtime cleanup; P3 means smaller maintenance or test cleanup.

| ID | Priority | Objectives | Finding | Disposition |
| --- | --- | --- | --- | --- |
| F01 | P3 | 1, 2 | Unreferenced utility mixins/version parser and Qt event helper | Removal candidate; high confidence |
| F02 | P3 | 1, 2, 3, 5 | Unreachable Unix 7-Zip transports and their test fragment | Removal candidate; high confidence |
| F03 | P2 | 1, 2, 4 | Old icon provider still performs startup work without a pane consumer | Removal candidate; high confidence |
| F04 | P3 | 1, 2, 5 | Licensing state and duplicate startup-message helper | Removal candidate; high confidence |
| F05 | P3 | 1, 2 | Unused immediate-transfer hooks and write-only flag | Removal candidate; high confidence |
| F06 | P2 | 2, 4 | Column wrapper forwards every lookup but provides no error protection | Simplification candidate; measured dispatch cost |
| F07 | P3 | 2, 4 | Capability guards for a retired pane model | Narrow simplification candidate; no measured speed claim |
| F08 | P3 | 5 | Eleven filter integration tests run twice against the snapshot backend | Consolidation candidate; measured |
| F09 | P3 | 1, 2, 5 | Reverse command-name helper is exercised only by its own test | Removal candidate; high confidence |
| F10 | P2 | 5 | Documentation gallery tests launch full applications in release verification | Test-tier candidate; approval needed |
| F11 | P1 | 2, 3, 4, 5 | Archive writes through winpty wait about 5 s per 7-Zip run | Replacement candidate; measured, high confidence |
| F12 | P2 | 1, 2 | fbs exception-handler chain is dead; Qt-slot exceptions now abort the process | Decision needed: restore a minimal hook or delete the chain |
| F13 | P2 | 4 | Full `Listing` validation is about 23% of a warm fallback local scan | Simplification candidate; measured |
| F14 | P3 | 1, 5 | Production-unused UI/helper code kept alive only by tests | Removal candidate; high confidence |
| F15 | P3 | 1, 2, 3 | Small dead methods, Unix-only defaults and unused Qt aliases | Removal candidate; high confidence |
| F16 | P3 | 1, 2 | Public APIs with no bundled consumer | API decision required; retain by default |
| F17 | P3 | 2, 3 | Unused Open Sans font and Mac/Linux notices/docs | Removal candidate; license review |
| F18 | P3 | 2, 4 | Per-name error context and cache in `iterdir` cost about 1.6 µs/name | Simplification candidate; measured, low priority |
| F19 | P3 | 5 | PDF leak-cycle test is the largest single test (15-19 s in CI) | Test-cost candidate |

### F01 - Unreferenced Utility Families

- Owners: [util](../src/main/python/fman/impl/util/__init__.py#L17) and
  [Qt helpers](../src/main/python/fman/impl/util/qt/__init__.py#L12).
- `parse_version`, `EqMixin`, `ReprMixin`, `ConstructorMixin` and
  `FilterEventOnce` have no caller/import outside their definitions.
  `MixinBase` is referenced only by the three unused subclasses.
- Their names are absent from registration/configuration consumers. They are
  internal helpers, not documented exports from `fman` or `fman.ui`.
- Remove these definitions and imports that then become unused. Keep `Event`,
  `is_below_dir`, URL conversions and `connect_once`: they have live consumers.
- Effect: fewer imported definitions; no significant speedup established.
- Gate: fresh host/Core imports, utility/Qt URL tests and native startup smoke.

### F02 - Unix Archive Backends Cannot Be Selected

- Owner: [archive transports](../src/main/resources/base/Plugins/Core/core/fs/zip.py#L875).
- `_7zip.__enter__` selects only `Popen7ZipWindows` or `Run7ZipViaWinpty`.
  `Popen7ZipUnix`, `_get_7zip_env_encoding_unix` and `Run7ZipViaPty` form an
  unreachable Unix-only branch. They retain `pty.fork`, `os.waitpid`,
  `os.execlp`, Unix locale setup and signal handling.
- Mocked dispatch confirmed calls `[Windows=1, Winpty=0, Unix=0, Pty=0]`
  with `pty=False`, and `[0, 1, 0, 0]` with `pty=True`.
- Remove that branch and its exclusive imports. Keep the Windows pseudo-terminal
  path and `pywinpty`; Pack and other archive operations still use it.
- [test_existing_pty_readers](../src/main/resources/base/Plugins/Core/core/tests/fs/test_zip.py#L393)
  directly constructs the unreachable Unix reader. Remove only that fragment
  and its unused imports; keep the Windows ANSI-stripping assertions.
- Gate: archive transport/process tests, Unicode archive paths, progress,
  cancellation and Pack/Unpack smoke checks. No file-operation safety change.

### F03 - Retired Icon Service Still Initializes at Startup

- Owners: [application context](../src/main/python/fman/impl/application_context.py#L175),
  former `model/icon_provider.py` (removed by F03) and
  [MotherFileSystem.icon](../src/main/python/fman/impl/plugins/mother_fs.py#L85).
- Constructing `mother_fs` creates `Local/Cache/Icons`, constructs
  `QFileIconProvider`, scans `file*` surrogate cache entries and requests icons.
- Pane decoration instead calls the bounded
  [ListingIcons](../src/main/python/fman/impl/model/listing_icons.py) service.
  No production caller of the old `MotherFileSystem.icon` path was found;
  it is not exposed by `fman.fs`.
- A temporary cache containing three file types caused four mocked Qt icon
  requests during old-provider construction, before any `get_icon` call.
  This verifies unnecessary work, not a measured real-shell startup delay.
- Remove the old provider/cache setup and dead facade method together. Simplify
  internal constructor fixtures and remove the test requiring obsolete cache
  creation. Do not delete existing users' cache directories automatically.
- Gate: current pane icon tests, generic/provider fallbacks, cold startup,
  executable/folder icons and absence of old icon-cache writes.

### F04 - fman Licensing State and Test-Only Message Code

- Owner: [SessionManager](../src/main/python/fman/impl/session.py#L23).
- The application context supplies `is_licensed=True` unconditionally.
  `_is_licensed` is only persisted; `was_licensed_on_last_run` has no consumer.
  Screenshot setup also seeds the obsolete field and a test checks that seed.
- `_get_startup_message` duplicates `_show_startup_messages` but has no
  production caller. Its only caller is
  [the session test](../src/unittest/python/fman_unittest/impl/test_session.py#L114),
  which already checks the actual status message.
- Remove the internal licensing parameter/property/write and screenshot seed
  assertion. Remove the duplicate helper and its assertion, not the meaningful
  startup-version/persistence test.
- Existing `is_licensed` keys may remain ignored in old files. Keep
  `fman_version` migration unless separately approved; that is compatibility
  behavior, not proof of dead licensing.
- Effect: simpler session state; trivial write/import savings, not a latency fix.
- Gate: session restore/save, startup version messages, first-run tours and
  isolated screenshot settings.

### F05 - File-Operation Hooks No Longer Reach Execution

- Owner: [FileTreeOperation](../src/main/resources/base/Plugins/Core/core/fileoperations.py#L27).
- The base, CopyFiles and MoveFiles define `_transfer`; no attribute call to
  `_transfer` exists anywhere in application or tests.
  Execution uses `_prepare_transfer`, queues tasks, then calls `Task.run`.
- `_cannot_move_to_self_shown` is assigned once and never read.
- Remove the three dead method definitions and flag. Keep `_prepare_transfer`,
  ancestry/alias checks, preparation cancellation and postprocessing hooks.
- Effect: code/one attribute allocation removed; no throughput claim.
- Gate: existing CopyFiles/MoveFiles tests, conflicts, preparation refusal,
  deferred refresh and cancellation.

### F06 - ColumnWrapper Has Cost but No Protective Behavior

- Owner: [column construction and wrapper](../src/main/python/fman/impl/plugins/plugin.py#L103);
  caller: [ListingModel.data](../src/main/python/fman/impl/model/listing.py#L520).
- The loader registers a `ColumnWrapper`. Its only dispatch behavior is
  `__getattr__ -> getattr(_wrapped, name)`; it does not use `ReportExceptions`.
  Cell-text cache misses therefore pay forwarding cost for `column.text`.
- Probe: the wrapped/raw columns returned identical text, keys and headings.
  A `ValueError` from wrapped text propagated and never called the error handler.
- Seven alternating warm samples of 100,000 calls:
  raw median **5.266 ms** (5.219-5.318); wrapped **17.492 ms** (17.426-17.604).
  This is isolated attribute dispatch, not pane-paint latency or a file-count
  speedup. Cells are virtualized and cached, so real benefit needs measurement.
- Register the raw instance and retain constructor-error reporting and public
  column validation. Do not remove listener/filesystem wrappers as a consequence:
  those wrappers have live attribution/validation behavior.
- The [loader test](../src/integrationtest/python/fman_integrationtest/impl/plugins/test_plugin.py#L137)
  currently asserts `.unwrap()`; update it to assert the registered raw column
  and behavior, not delete the loader test.
- Gate: column loading/unloading, custom columns, formatting/keys errors, sorting,
  external-data invalidation and a real pane-paint comparison.

### F07 - Retired-Model Compatibility Guards

- Owners: [proxy signal wiring](../src/main/python/fman/impl/model/__init__.py#L342)
  and [QuickView reset handling](../src/main/python/fman/impl/quick_view.py#L576).
- Normal source-model construction now always creates `ListingModel`, including
  the initial null provider. It declares `about_to_commit`, `committed`,
  `state_provider` and `_displayed`.
- The proxy still conditionally wires snapshot signals with `hasattr`.
  QuickView still has a non-snapshot reset path selected by absence of
  `_displayed`. That alternate model is no longer constructed by the host.
- Simplify those internal branches only after checking test doubles and all
  `setSourceModel` callers. Keep the reset-in-progress flag itself: it prevents
  preview work before selection restoration commits.
- Do not remove `listing is None`, generation/closed checks or the public
  provider-result validation. Those conditions remain reachable.
- Effect: clearer ownership, tiny transition overhead at most. No material
  speed improvement measured; do not prioritize this as a performance fix.

### F08 - Same Filter Cases Inherited Into a Second Concrete Suite

- Owner: [FilterBarIT and SnapshotFilterBarIT](../src/integrationtest/python/fman_integrationtest/test_qt.py#L1913).
- The loader finds 12 methods on FilterBarIT and 41 on SnapshotFilterBarIT.
  Eleven inherited test methods are the exact same function objects.
  Both use the same `setUp` and current snapshot backend.
- The subclass changes drain/cleanup helpers, not the backend. Its query/key/
  status overrides repeat settling after the base helpers. These differences
  do not justify another legacy-versus-snapshot pass.
- All 22 executions of those shared cases passed: base **0.927 s**, subclass
  **0.788 s** locally. This is one local observation, not guaranteed CI savings.
- Consolidate into one concrete suite with shared fixture helpers; execute each
  shared scenario once. Retain the subclass's additional tests.
  The two `test_loading_navigation_and_retired_source` implementations are
  different: give them distinct names and retain both scenarios.
- Keep plain `SortedFileSystemModelAT`/`RunInThreadAT` mixins: they are not
  TestCase subclasses and are not independently discovered duplicates.
- Gate: compare discovered test identities before/after, run every retained
  case and verify the removal is exactly the duplicate executions.

### F09 - Reverse Command-Name Conversion Is Test-Only

- Owner: [get_command_class_name](../src/main/python/fman/impl/plugins/plugin.py#L295).
- Only `GetCommandClassNameTest.test_is_inverse_of_get_command_name` calls it.
  Runtime registration uses `_get_command_name`, never the reverse conversion.
- Remove the unused helper, test class and import together.
  Keep `GetCommandNameTest`: the forward conversion remains essential to
  configuration and command dispatch.
- The existing inverse test passed in about **0.0002 s**. This is housekeeping,
  not a worthwhile test-runtime improvement by itself.

### F10 - Separate Gallery Validation From Release Verification

- Owner: [screenshot tests](../src/unittest/python/fman_unittest/test_generate_docs_screenshots.py#L416);
  discovery: [build.test](../build.py#L370).
- Normal release verification discovers documentation gallery tests that start
  real applications and capture widgets. Two sampled cases cost **1.698 s**
  (QuickBoard) and **1.951 s** (Batch Renamer), **3.649 s** combined.
- Their assertions protect actual capture output, public/sample-only paths,
  no desktop grabs, no file mutation and normal cleanup. They are not redundant
  with all ordinary UI tests and must not simply disappear.
- Candidate: move gallery-only checks to an explicit documentation-tool test
  target and run it in [Pages](../.github/workflows/pages.yml#L49) before capture.
  Keep the shared restricted-process/token/job/timeout/desktop tests in release
  validation: `smoke-everything` uses that launcher too.
- This changes validation ownership, so obtain user approval first. Pages
  generation alone does not currently replace every assertion in these tests.
- Gate: new docs target executes the moved cases; ordinary release discovery
  excludes only gallery cases; release-critical launcher coverage remains.

## Independent Review: Claude Opus 5.5 (2026-10-28)

Method: own AST/token reference scan over 302 Python files plus JSON/QSS/CSS/
spec/workflow text (Qt overrides and loader-registered classes triaged by hand),
targeted microbenchmarks, and per-test timings parsed from the two latest
release CI logs (v0.19.2 run 40546132971, v0.19.1 run 40529853065). P1 below
means a measured, user-visible latency removal.

### Confirmation of F01-F10

| ID | Verdict | Evidence |
| --- | --- | --- |
| F01 | Confirmed | Scan found no reference outside the definitions. |
| F02 | Confirmed; superseded by F11 | With F11 the Windows pseudo-terminal backend goes too. |
| F03 | Confirmed (not re-measured) | No production `MotherFileSystem.icon` caller. |
| F04 | Confirmed | `was_licensed_on_last_run` 0 refs; `_get_startup_message` test-only. |
| F05 | Confirmed | `_transfer` never called. |
| F06 | Confirmed by reading | `ColumnWrapper` has only `__getattr__`; `unwrap` is test-only. |
| F07 | Not independently verified | No objection. |
| F08 | Confirmed; low value | CI: SnapshotFilterBarIT 41 tests = 4.9 s / 3.0 s in total. |
| F09 | Confirmed | Single test caller. |
| F10 | Confirmed with CI cost | GenerateDocsScreenshotsTest: 34 tests = 20.0 s (v0.19.2), about 9% of test time. |

### CI Test-Time Evidence

GitHub prints each verbose test line when the test *ends*; durations below are
the gap from the previous end-stamp, excluding the first test of each discovery
group. Totals: 1,932 tests, **216.6 s** (v0.19.2) and **178.6 s** (v0.19.1).

| Cost (v0.19.2 / v0.19.1) | Tests | Cause |
| --- | --- | --- |
| 66.0 s / 65.7 s | 11 archive-write tests (13 7-Zip runs) | F11: fixed winpty delay |
| 19.3 s / 14.8 s | `PdfControllerTest.test_repeated_use_and_large_pixel_delivery` | F19: 100 helper cycles |
| 20.0 s / 15.9 s | `GenerateDocsScreenshotsTest` (34) | F10 |
| 5.1 s / 4.1 s | `NativeWindowsCleanupTest.test_source_workflows_with_isolated_settings` | Native app launch; retain |
| 3.0 s / 3.0 s | `TestRunnerDiagnosticsTest.test_hang_dumps_stack_and_times_out` | Intended 3 s timeout (F19) |

### F11 - Archive Writes Pay a Fixed ~5 s Through winpty

- Owners: [_7zipTaskWithProgress](../src/main/resources/base/Plugins/Core/core/fs/zip.py#L306)
  (`pty=True` default), [Run7ZipViaWinpty](../src/main/resources/base/Plugins/Core/core/fs/zip.py#L964);
  consumers: `AddToArchive` (Pack, copy into archive), `Rename`, and other default calls.
- Probe, pywinpty 3.1.1: `7za i` through `PtyProcess` produced its last output at
  about 0.55 s, but EOF arrived at **5.08 s** (process already exited). Same command
  through a pipe: **11 ms**. Seven samples each; range 5.080-5.088 s.
- Real path, one small file copied into a ZIP via `ZipFileSystem.copy`:
  **5,064 ms** with winpty, **126 ms** with pipes; identical archive contents.
- Locally, three archive tests took 10.2 s. In CI, 11 tests cost about 66 s per run
  (table above). Pack runs one 7-Zip process per selected item, so Pack of N items
  waits about N x 5 s.
- The pipe path with `-bsp1 -bse1 -spd` and `progress_records` already serves
  extraction and moving into an archive. The pseudo-terminal was fman's way to get
  7-Zip progress before `-bsp`; it is luggage now.
- Proposal: route every 7-Zip call through pipes with `-bsp1 -bse1`; remove
  `Run7ZipViaWinpty`, its ANSI stripping, F02's Unix backends, `pywinpty` in
  [environment.yml](../environment.yml) and `collect_all('winpty')` in the
  [spec](../application.spec) (about 4.2 MB in the frozen build:
  `winpty.dll`, `OpenConsole.exe`, `conpty.dll`, `_winpty.pyd`).
- Cancellation differs: winpty sends Ctrl+C; the pipe path calls
  `TerminateProcess`, which can leave a 7-Zip `.tmp` update file. Follow the move
  path: `cancellable=False` during the write ("Canceling after archive update
  finishes..."), then honour cancellation. Do not hard-kill an archive update.
- Gate: Pack/copy/rename/mkdir/delete inside ZIP/7z/TAR, Unicode names, progress,
  cancellation (archive unchanged, no `.tmp` left), CI test time before/after,
  frozen-build smoke without winpty files.

### F12 - Dead Exception-Handler Chain; Qt-Slot Exceptions Abort

- Owners: [exception_handlers](../src/main/python/fman/impl/application_context.py#L116),
  former `fbs_runtime/excepthook` (removed by F12),
  [PluginErrorHandler.handle](../src/main/python/fman/impl/plugins/error.py#L22).
- The local fbs replacement never installs `sys.excepthook`, so nothing reads
  `exception_handlers`; `StderrExceptionHandler`, the `ExceptionHandler` base,
  `handle` and `_get_plugin_causing_error` are unreachable.
- Consequence probe: an exception raised from a Qt timer slot under PyQt 5.15
  ended the process with `0xC0000409` (fail-fast abort), not a printed traceback.
- Panel callbacks are wrapped, but `DirectoryPane.on_path_changed` and
  `on_closed` callbacks ([fman/__init__.py](../src/main/python/fman/__init__.py))
  run unguarded on Qt. A raising plug-in callback can terminate the application
  and lose unsaved session state.
- Options: (a) install a minimal hook in `run()` that tries `plugin_error_handler`
  then prints, restoring plug-in attribution (recommended); (b) delete the dead
  chain and wrap the remaining public Qt callbacks. Either way the current state
  is dead code plus a lost safeguard. Not a pure removal; user decision.
- Gate: a raising `on_path_changed` callback shows an alert and the app survives;
  Core exceptions still print; tests patching `sys.excepthook` unaffected.

### F13 - Validation Dominates Part of the Fallback Scan

- Owner: [LocalFileSystem._scan_entries](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L43)
  builds `Listing.create(...)`, which runs full `__post_init__` validation.
  This path serves exFAT/FAT drives, UNC/mapped shares and other non-native folders.
- Microbenchmark, 200,000 entries: validated create **96.7 ms** median; trusted
  construction **5.1 ms**. Real warm fallback scan of a 20,000-file local folder:
  **46.3 ms** with validation, **35.8 ms** without (about 23%).
- Names come from `os.scandir` (no `.`/`..`, separators or NUL on Windows) and the
  columns are built by Core with fixed types. Proposal: a Core-private trusted
  constructor for this producer, keeping only checks the OS cannot guarantee
  (consider an exact-duplicate check for SMB servers). Third-party providers keep
  full validation.
- Network shares gain proportionally less; their cost is mostly I/O.
- Gate: fallback parity with `Listing.create` on fixtures; SMB/exFAT smoke;
  reconcile/marks unchanged.

### F14 - Production-Unused Code Kept Alive by Tests

| Symbol | Production refs | Tests | Note |
| --- | --- | --- | --- |
| [JsonSettings](../src/main/python/fman/impl/ui/panel.py#L414) (~130 lines) | 0 | 4 `test_qt` tests | Export removed in UIElements002 |
| `Panel.add_stretch` | 0 | 1 | |
| `QuickList.selected_items`, `current_item` | 0 | 3 | |
| `DirectoryPaneWidget.set_column_widths` | 0 | 2 | Production uses `restore_column_widths` |
| `DirectoryPaneWidget.hidden_files_shown` | 0 | 0 | |
| `ResultRow.payload_bytes` (ChecksumFiles) | 0 | 1 | |
| Everything `instance.add_folder` | 0 | 4 | |
| `PluginSupport.get_active_pane` | 0 | 1 smoke assertion | |

Remove each symbol with the assertions that exist only for it; keep tests that
also cover live behavior by rewriting them against the live API.

### F15 - Small Dead Code and Unix Leftovers

- Dead: `ListingModel.notify_file_renamed`, `CsvController.cancel_action`,
  `GoTo._traverse_by_mtime` (~30 lines).
- Unix leftovers: `GoTo._get_default_paths(exclude={'/proc', '/run', '/sys'})`
  and its "or / on Unix" comment; `# macOS` `IsADirectoryError` branch in
  `LocalFileSystem.mkdir`; `os.name != 'nt'` branches in ChecksumFiles
  `native_path`/`_existing_destination_path`, Robocopy `api()` and
  `rename_no_replace` (`main.py` already refuses non-Windows).
- 7 unused Qt aliases in [util/qt](../src/main/python/fman/impl/util/qt/__init__.py):
  `TextAlignmentRole`, `KeyboardModifier`, `GroupSwitchModifier`, `Key_Help`,
  `Key_F2`, `Key_F7`, `SizeHintRole`.
- Keep `os.name` checks in tests that skip native-only cases.

### F16 - Public APIs Without a Bundled Consumer

Retain by default; listed for an explicit API decision because each carries
host code and tests.

- `DirectoryPane.find_in_listing`: Ctrl+F moved back to QuickSearch
  (`index_listing`). The in-pane Find session in `FilterBar`, the search branch of
  projection and `ListingSearch` now serve only this public API, Qt tests and the
  pane benchmark.
- `PaneToolWindow.set_panel` / `bottom_panel` focus bridging: no caller since the
  panel widget export was removed; `show_panel` uses `MainWindow` directly.
- `ToolWindow.rename_prompt`: documented, no bundled caller.

### F17 - fman Font, License and Icon Luggage

- `Core/Open Sans.ttf` (221 KB) is registered at every start but referenced by no
  CSS/QSS; `Roboto Bold.ttf` is used by `Theme.css`. Registration costs only
  ~0.35 ms; the gain is package size.
- [LICENSE](../src/main/resources/base/LICENSE) still lists osxtrash ("Mac
  version of fman only"), p7zip ("Linux and Mac versions") and Open Sans ("Linux
  version only"). Remove after license review; keep notices for shipped
  components.
- [icons/README](../src/main/icons/README) describes Mac/Linux icon sets that no
  longer exist.

### F18 - iterdir Error Context and Cache Cost

- `FileSystemWrapper.iterdir` (non-navigation path) creates a `ReportExceptions`
  context per name; `MotherFileSystem.iterdir` wraps the result in
  `CachedIterator` (lock per name). 200,000 names: raw 6.6 ms, wrapped 156 ms,
  wrapped + cache 334 ms.
- Consumers are now directory merges, Compare Directories and non-local fuzzy
  indexing; panes use snapshots. The cached names can also be stale between
  pane scans.
- Proposal: one error context around the loop (same attribution, keep the
  per-item `str` check); consider removing iterdir caching and its
  `_add_to_parent`/`_remove` maintenance. Low priority: not a hot path today.

### F19 - Test Cost Without Coverage Loss

- `test_repeated_use_and_large_pixel_delivery` runs 100 real open/render/release
  cycles (15-19 s in CI). The leak assertions compare cycles 10..N; 30 cycles
  keep the warm-up and growth checks at about a third of the cost. Alternatively
  move the 100-cycle variant to the performance tier.
- `test_hang_dumps_stack_and_times_out` waits its full 3 s timeout; 1.5 s keeps a
  margin over child start-up. Saves ~1.5 s.
- F08/F09 savings are below 1 s; F10 and F11 dominate test-time reduction
  (about 85 s of ~217 s together).

## Retained or Deferred Candidates

- **Tutorial, Cleanup Guide, usage helper and shortcut hints:** reachable
  Windows UX retained explicitly in CodeReview005. Not dead fman luggage.
- **`requests`:** no direct application import found, but 005 Q10 explicitly
  deferred dependency removal. Reopen separately; inspect build-tool transitive
  requirements before changing the environment/lock.
- **`adodbapi`:** live Windows Search consumer in Core Go To. Keep.
- **POSIX-style application URLs and Unix checksum output:** supported data
  formats on Windows, not non-Windows execution paths.
- **Non-NTFS/UNC scanning:** supported Windows fallback, not an obsolete
  non-Windows path. Keep authoritative metadata separate from display snapshots.
- **Native parser bounds, validation and source/binary hashes:** required by the
  trusted Listing path. Reference parsers/gauge entry points support parity and
  rebuild checks; being absent from normal runtime is not enough to delete them.
- **Link/alias/identity checks, staged copy publication and source rechecks:**
  protect different races and data-safety guarantees. No blanket removal.
- **Image dimension checks before/after decoding, file-size checks before/after
  opening, helper framing limits:** different boundaries; no redundant-cost
  proof found.
- **CSV quota/disk monitors, cancellation, process jobs and stale-result guards:**
  retain. Their failure behavior is observable and not replaced by a single
  initial validation.
- **Detached/blocked-worker and hostile-input regression tests:** retain. A wait
  timeout is usually an upper failure bound, not time spent on a passing run.
- **Historical benchmarks:** old source paths and original model access are
  intentional. The two pane benchmark copies are a maintenance candidate, but
  neither runs through normal `test*.py` discovery; deduplicating them cannot
  be claimed as release-test savings.

## Alternatives

- Delete all static single-reference symbols: rejected; registration, Qt
  callbacks, native entry points and public APIs require ownership evidence.
- Remove guards for speed without measurement: rejected. Prefer removing a
  dead service or forwarding layer over weakening operation-time validation.
- Delete similar tests: rejected; preserve unique fixtures, race conditions,
  failure paths and native integration boundaries.
- Run/profile the full suite now: not requested. Selected test timings establish
  local costs only; whole-suite savings remain unmeasured.
- Implement during this pass: rejected; independent reviews and user selection
  come first.

## Runtime Effects

- Review/document changes: no startup or steady-state work, I/O, persistence,
  timers, workers or processes added to the application.
- Proposed removals: mostly smaller source/import state. F03 can eliminate
  unnecessary startup directory/icon work; F06 removes forwarding on text-cache
  misses. End-to-end gains have not been established.
- F08 removes duplicate test setup/execution. F10 relocates cost to docs
  validation rather than eliminating unique coverage.
- Cancellation, stale-result rejection, error reporting, portable settings and
  disabled-feature no-op behavior must remain unchanged after implementation.

## Tests

### Review Validation Performed

Use the existing environment with offscreen Qt and no bytecode:

```powershell
@'
import build, os, subprocess, sys
env = build._environment()
env.update(QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1')
code = """
import unittest
from fman_integrationtest.test_qt import FilterBarIT, SnapshotFilterBarIT
from fman_unittest.test_generate_docs_screenshots import GenerateDocsScreenshotsTest
from fman_unittest.impl.plugins.test_plugin import GetCommandClassNameTest
from core.tests.fs.test_zip import ArchiveProcessTest
from fman_integrationtest.impl.plugins.test_plugin import ExternalPluginTest
loader = unittest.TestLoader()
shared = [n for n in loader.getTestCaseNames(FilterBarIT)
    if getattr(FilterBarIT, n) is getattr(SnapshotFilterBarIT, n)]
tests = [cls(n) for cls in (FilterBarIT, SnapshotFilterBarIT) for n in shared]
tests += [
    GenerateDocsScreenshotsTest('test_quick_board_capture_shows_arguments_without_desktop_grab'),
    GenerateDocsScreenshotsTest('test_batch_renamer_capture_previews_samples_without_renaming'),
    GetCommandClassNameTest('test_is_inverse_of_get_command_name'),
    ArchiveProcessTest('test_existing_pty_readers'),
    ExternalPluginTest('test_load'),
]
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(tests))
raise SystemExit(not result.wasSuccessful())
"""
sys.exit(subprocess.run([sys.executable, '-B', '-c', code],
    env=env, timeout=150).returncode)
'@ | python -B -
```

The measured run used the same selection with a `TextTestResult` subclass
timing `startTest` through `stopTest`. All **27 passed in 5.381 s**.
Four representative duplicate cases were also run separately: **4 passed in
0.289 s**. These are review checks, not post-removal validation.

Other probes: BOM-aware AST/reference scans; mocked 7-Zip transport selection;
raw/wrapped column parity and exception propagation; seven alternating
100,000-call dispatch timings; old icon-provider construction with three
temporary cache entries and a mocked Qt provider. No real shell extraction,
user settings or files were used in those microprobes.

### Required Before Any Implementation Is Accepted

- Repeat reference/config/export searches for each selected deletion.
- Run the nearest existing tests immediately after each removal group.
- F01/F04/F09: utility, Qt URL, session, startup and plug-in naming tests.
- F02/F05: archive/process and file-operation suites, including Windows
  progress/cancellation and real disposable Copy/Move/Pack/Unpack checks.
- F03/F06/F07: loader, columns, snapshot/filter, icon, QuickView and native
  startup/focus checks. Verify custom providers and columns remain usable.
- F08: record discovered identities before/after; preserve unique navigation
  scenarios and all subclass-only cases.
- F10: run both documentation and release-critical launcher selections, with
  an explicit CI gate for moved tests.
- Measure actual startup/paint/test savings before making performance claims.
  Use the same environment, fixtures, repetitions and workload boundaries.
- Full suite and freeze/package remain separately requested gates, not
  automatic consequences of this review.

## Implementation Steps

1. Collect independent reviews; challenge findings by ID and record decisions.
2. Obtain user selection, especially for F06/F07 and the F10 test-tier change.
3. Remove confirmed dead definitions and their exclusively obsolete assertions
   in small groups; run focused validation after each group.
4. Remove the retired icon service and column forwarding only with current
   startup/loader/icon/column behavior protected.
5. Consolidate duplicate test execution without deleting unique assertions.
   Wire any moved documentation checks before excluding them from release tests.
6. Update affected developer/API documentation and the application changelog
   only when code/build behavior is actually changed.
7. Record before/after coverage, timings, failures/skips and remaining gates;
   complete the task lifecycle only after approved changes pass their checks.

## Acceptance Criteria

- All five objectives have evidence-backed findings or explicit retention
  decisions; no unused-code tool output is accepted without caller analysis.
- Later reviewers can append confirmations/challenges without rewriting history.
- No application/test removal occurs before selection and independent review.
- Approved removals leave no active references, registrations or packaging inputs.
- No supported API, Windows location, cancellation, error or safety contract is
  silently lost.
- Removed tests cover only removed behavior or verified duplicate execution.
  Moved tests have an enforced owner/CI target.
- Performance claims state the measured workload and do not extrapolate isolated
  dispatch or single-machine test timings into application-wide guarantees.

## Implementation Summary

User decisions: implement all findings; F12 restores a minimal hook; F16 removes
all three APIs; F10 moves gallery tests to a docs target; F11 cancels an archive
write only after the current 7-Zip write finishes.

| ID | Change |
| --- | --- |
| F01 | Removed `parse_version`, the `*Mixin` helpers and `FilterEventOnce`. |
| F02, F11 | 7-Zip always uses pipes with `-bsp1 -bse1` progress. Removed the pty runners, `pywinpty` (environment, lock, spec) and their tests. Archive writes are non-cancellable mid-write. |
| F03 | Deleted `model/icon_provider.py`; `MotherFileSystem()` takes no icon provider. |
| F04 | Removed `is_licensed` session state and `_get_startup_message`. |
| F05 | Removed the three `_transfer` methods and `_cannot_move_to_self_shown`. |
| F06, F09 | Columns register the raw instance; removed `ColumnWrapper` and `get_command_class_name`. |
| F07 | Proxy wires snapshot signals unconditionally; QuickView drops its non-snapshot reset path. The view keeps its `hasattr`: a Qt test drives it with a `QStandardItemModel`. |
| F08 | The 12 `FilterBarIT` tests moved into `SnapshotFilterBarIT`; `FilterBarIT` is a shared fixture. The two loading-navigation tests have distinct names. |
| F10 | Six gallery-capture tests moved to [test_docs_gallery.py](../src/docstest/python/test_docs_gallery.py), run by `python build.py test-docs` in the Pages workflow. Launcher tests stay in release. |
| F12 | `ApplicationContext.run` installs `sys.excepthook` that reports through `PluginErrorHandler`; deleted `fbs_runtime/excepthook`. |
| F13 | The local fallback scan builds `Listing._trusted`; exact duplicates fall back to `Listing.create`. |
| F14 | Removed `JsonSettings`, `Panel.add_stretch`, `QuickList.selected_items`/`current_item`, `set_column_widths`, `hidden_files_shown`, `payload_bytes`, Everything `add_folder` and `get_active_pane`. |
| F15 | Removed 7 Qt aliases, `notify_file_renamed`, `CsvController.cancel_action`, `_traverse_by_mtime` and the Unix/macOS branches. |
| F16 | Removed `find_in_listing` (FilterBar Find session, projection search, highlight role and paint hook, `ListingSearch`), `PaneToolWindow.set_panel`/`bottom_panel` and `ToolWindow.rename_prompt`. |
| F17 | Deleted `Core/Open Sans.ttf`; removed osxtrash, Open Sans and p7zip from `LICENSE`; rewrote `icons/README`. |
| F18 | `FileSystemWrapper.iterdir` uses one error context (excluding `GeneratorExit`). `MotherFileSystem.iterdir` is uncached; removed `CachedIterator` and its maintenance. |
| F19 | PDF resource test: 30 cycles. Hang test: 1.5 s timeout. |

The `conda-lock.yml` `content_hash` was already stale before this task (it did
not match the original `environment.yml`); only the two package blocks were
removed. CI uses the committed lock.

## Reviewers

### 2026_10_28 - Copilot

- Role: Reviewer
- Activity: Design
- Agent: Copilot SDK in VS Code
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 1M
- Outcome: Defined the five-objective, review-only task and evidence/acceptance
  gates; independent contributions and user selection required before removal.

### 2026_10_28 - Copilot

- Role: Reviewer
- Activity: Review
- Agent: Copilot SDK in VS Code
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 1M
- Outcome: Recorded F01-F10 after repository-wide screening and focused probes;
  27 targeted tests passed, plus 4 earlier representative executions. No code,
  tests, dependencies or runtime safeguards changed.

### 2026_10_28 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Independent review. Confirmed F01-F06 and F08-F10 (F07 not verified).
  Added F11-F19. Highest value: F11, a fixed ~5 s winpty delay on every archive
  write (copy into ZIP 5,064 ms vs 126 ms via pipes; ~66 s of ~217 s CI test
  time), and F12, a dead exception-hook chain whose loss lets Qt-slot exceptions
  abort the app. Evidence: reference scan, microbenchmarks and per-test timings
  from two release CI logs. No code, tests or dependencies changed.

### 2026_10_28 - Copilot

- Role: Reviewer
- Activity: Review
- Agent: Copilot SDK in VS Code
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 1M
- Outcome: Reviewed the F01-F19 implementation and affected contracts. Recorded
  reproduced diagnostic defect IR01 and additional candidates F20-F22.
  Focused validation ran 475 tests, with 4 skips and no failures. No application
  or test code changed; IR01 remains open.

## Implementer

### 2026_10_28 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented F01-F19 per the user's decisions. Decisive checks:
  archive modules 378 tests in 22.9 s (about 66 s of winpty waits removed),
  a 48 MiB archive copy in 1.5 s with live progress, a subprocess check that
  a raising Qt slot no longer aborts, full `test_qt` (311 tests) and the new
  `test-docs` target.

### 2026_10_28 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Fixed IR01 (plug-in errors from Qt callbacks now include the
  exception and traceback) with a real-handler regression test, and
  implemented F20-F22. Also fixed the Quicksearch focus loss found by
  `quick_view_smoke`. Gates in the response section: 425 + 312 tests OK.

## Validation Results

Environment: `build._environment()`, `QT_QPA_PLATFORM=offscreen`,
`QT_QPA_FONTDIR=%WINDIR%\Fonts`.

| Command / procedure | Result |
| --- | --- |
| `python -m unittest core.tests.fs.test_zip core.tests.commands.test_unpack_archive core.tests.commands.test___init__ core.tests.test_fileoperations` (after F11) | 378 OK, 22.9 s |
| Final focused run: the modules above plus `core.tests.commands.test_goto core.tests.fs.test_local fman_unittest.test_listing fman_unittest.impl.plugins.test_plugin fman_unittest.impl.plugins.test_mother_fs fman_integrationtest.impl.plugins.test_plugin fman_unittest.test_application_context fman_unittest.impl.test_session fman_unittest.test_checksum_files fman_unittest.test_everything fman_unittest.test_robocopy fman_unittest.test_search_file_fuzzy fman_unittest.test_portable fman_unittest.impl.test_quick_view_csv fman_integrationtest.impl.model.test___init__ fman_unittest.test_quick_view_pdf fman_unittest.test_generate_docs_screenshots` | 898 run, 10 skipped, 5 environmental errors (below) |
| `python -m unittest fman_unittest.test_quick_view_pdf fman_unittest.test_portable` | 32 OK, 13 s |
| `python -m unittest fman_unittest.test_generate_docs_screenshots` | 28 OK, 11 s |
| `python build.py test-docs` | 6 OK, 11.6 s |
| `python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt` | 311 run, 2 skipped, 1 failure (below) |
| Real archive copy, 48 MiB into ZIP | 1.5 s, progress 15-100 % |
| Reference scan after removal | No new orphan; `DirectoryPane._has_focus` became test-only and was inlined into `quick_view_smoke.py` |

Follow-up run (2026-10-28, long paths enabled, Everything provisioned by
`build._ensure_everything()` from the pinned portable ZIP):

| Command / procedure | Result |
| --- | --- |
| Final focused run (modules above) | 898 OK, 10 skipped |
| `python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt` | 311 OK, 2 skipped |
| `CommandPaletteRecentIT` with `QT_QPA_PLATFORM=windows` | 2 OK |
| `test_move_by_copying_keeps_source_changed_during_or_after_copy`, 30 repeats | 0 failures |

Earlier local failures and their causes:

- Long-path tests and `test_production_verifier_reads_all_tc_digests`: long
  paths were disabled (`LongPathsEnabled=0`). Pass once enabled.
- ChecksumFiles and Robocopy spec tests: `Everything.exe` was not provisioned.
  Pass after `_ensure_everything()`.
- `test_move_by_copying_keeps_source_changed_during_or_after_copy`: flaky test.
  A same-size rewrite within one NTFS timestamp tick keeps `st_mtime_ns`
  (81 of 200 local rewrites). The test now ages the source first, as a real
  pre-existing file is.
- `test_long_hint_is_elided_instead_of_overlapping_the_title`: offscreen Qt
  requests Helvetica and falls back to an installed font. With Office's narrow
  Agency FB the hint (196 px) fit the fixed 400 px row (249 px available).
  The test now sizes the row from measured widths. The application uses
  `MS Shell Dlg 2` and is unaffected.
- `quick_view_smoke` ("Command Center did not return source focus"): a real
  defect, fixed separately (see CHANGELOG, Unreleased, Fixed). Each Quicksearch
  dialog is kept alive by its own reference cycle (`LineEdit.keyPressEventFilter`
  bound to the dialog) until garbage collection. When the process does not own
  the OS foreground, closing that hidden dialog left no active window.
  `MainWindow.exec_dialog` now calls `deleteLater()`; regression test
  `WindowsCleanupIT.test_closed_dialogs_are_destroyed`. The smoke script
  passed 5 of 5 runs afterwards.

Not run: the complete `python build.py test` suite, `freeze` and `package`
(separate gates per AGENTS.md).

## Implementation Review: GPT-6.1 Sol (2026-10-28)

Reviewed the current worktree against Git baseline `61e3d98`, the F01-F19
decisions and the implementation summary. The diff also contains the earlier
metadata relocation; that is not counted as a new cleanup finding.

The selected removals are present, including raw column registration, uncached
directory enumeration, pipe-only archives, API removal, test consolidation and
the enforced Pages gallery target. No incorrect dead-code removal was confirmed
in the inspected paths. The review does not certify every platform/storage
combination or a frozen release.

**Disposition:** retain the cleanup, but address IR01 before considering the
restored plug-in exception-reporting path complete. F20-F22 are optional
follow-ups, not implementation authorization.

### IR01 - P2: The Restored Exception Hook Drops Plug-in Error Details

- Owners: [application hook](../src/main/python/fman/impl/application_context.py#L71)
  and [PluginErrorHandler.handle](../src/main/python/fman/impl/plugins/error.py#L21).
- `_excepthook` correctly receives `(type, exception, traceback)` from Qt and
  delegates to `handle`. For an attributed non-Core plug-in, `handle` calls
  `report(message)` without supplying `exc_value` and returns `True`.
- `report` falls back to `sys.exc_info()[1]`. At a real Qt excepthook entry this
  is `None`, so it neither includes the exception/traceback nor prints them.
  Returning `True` also suppresses the outer hook's stderr fallback.
- Reproduction: compile a temporary plug-in callback raising
  `ValueError('review009 diagnostic detail')`, register its directory with the
  real handler, and invoke it through `QTimer.singleShot`. Use a recording
  `show_alert` boundary instead of opening a modal alert.
  The application survives, but the only alert is
  `Plugin 'DiagnosticPlugin' raised an error.`; stderr is empty.
  The hook received the ValueError while `sys.exc_info()[1]` was `None`.
  Direct hook invocation outside an `except` block reproduces the same result.
- This is a defect in the newly activated F12 path, not a request to restore
  the old handler hierarchy. Pass the supplied exception explicitly to
  `report`, retaining attribution and fallback if reporting itself fails.
- Regression needed: use the real `PluginErrorHandler` and an actual Qt
  callback; assert the alert includes the exception type/message and plug-in
  traceback and the process remains alive. Keep the existing Core-error and
  reporting-failure fallback tests.

### F20 - P3: A Small Group of Import-Only Dependencies Remains

Objectives: 1 and 2. Source/AST and repository reference checks found no use of
these imports beyond their import statements:

| File | Candidate import |
| --- | --- |
| [CSV worker](../src/main/python/_quick_view_csv_worker.py#L14) | `FrameDecoder` |
| [CSV controller](../src/main/python/fman/impl/quick_view_csv.py#L7) | `QKeySequence` |
| [plug-in loader](../src/main/python/fman/impl/plugins/plugin.py#L14) | `json` |
| [plug-in support](../src/main/python/fman/impl/plugins/__init__.py#L2) | `sanitize_key_bindings` |
| [Everything instance](../src/main/resources/base/Plugins/Everything/everything_search/instance.py#L5) | `os` |

Remove only these imports after another reference check. No material speedup is
claimed: several modules are already imported by other active dependencies.
Keep deliberate re-exports in `fman.ui`, Core's extension namespace and
`fbs_runtime.application_context`. Also keep `DirSize` and `MAX_COMMAND_UNITS`
re-exports unless their existing test consumers are deliberately migrated;
an unused local AST name is not sufficient evidence to delete an export.

Gate: fresh worker/loader imports and focused CSV, plug-in and Everything tests.

### F21 - P3: Non-Windows Native-Sort Fallback Is Unreachable in the Product

Objectives: 1, 2 and 3.

- [Windows scanner](../src/main/resources/base/Plugins/Core/core/fs/local/windows/listing.py#L54)
  sets `_fsparser=None` only when `os.name != 'nt'`.
- On supported Windows startup the module must load the native extension or
  raise; missing binaries do not produce `None`.
  [Name.keys](../src/main/resources/base/Plugins/Core/core/__init__.py#L28)
  nevertheless retains a Python-sort-key branch for that `None` value.
- Candidate: remove the non-Windows conditional initialization and dead
  `Name.keys` branch, preserving mandatory-load errors and bounded native slices.
  No product caller or test deliberately setting the parser to `None` was found.
- Keep `fman.impl.util.natural.natural_key`: shared UI sorting and native parity
  tests still use it. Keep the scanner's ordinary `os.scandir` path for
  unsupported volumes and UNC shares; that is a different, live Windows fallback.
- Effect: less platform-luggage code, not a demonstrated pane speedup.
  Recheck standalone tooling assumptions before implementation.
- Gate: native parser/column parity, missing/LFS-pointer import failures,
  large sliced keys and forced non-native-volume scan tests.

### F22 - P3: Obsolete Source-Model Recreation Parameters and Flag

Objectives: 1, 2 and 4.

- Owner: [SortedFileSystemModel._set_location_main](../src/main/python/fman/impl/model/__init__.py#L194).
  Both repository call sites pass seven positional arguments, followed only by
  `listing`, `scanner` and optional `observation` keywords.
  Neither supplies `recreating` or `sort_column`.
- `recreating` is therefore always `False`, and `sort_column` always empty.
  `_columns_recreated` is initialized to False, overwritten with that False,
  and read solely to decide whether to emit `location_loaded`.
- Optional columns now use `ListingModel.set_columns` on the existing model,
  rather than recreating the source. The old suppression/reselection route is
  not used by that implementation.
- Candidate: remove the two unused parameters, their dead branches and the
  `_columns_recreated` state; forward the normal location notifications directly.
  Preserve the live optional-column methods and their completion callbacks.
- Effect: simpler lifecycle reasoning; no measurable performance gain claimed.
- Gate: navigation/null-provider setup, loaded-callback ordering, optional-column
  changes, directory-size toggles and QuickView continuity.

### Review Validation and Limits

CPython 3.14.10; existing repository environment; no packages installed. All
302 current Python files in the source/build/script corpus parsed with BOM-aware
decoding. Pages/release YAML parsed, and both environment manifests contain no
`pywinpty`/`winpty` package requirement.

The following launcher ran the three focused groups below in separate child
processes, with no dependency stubs:

```powershell
@'
import build, subprocess, sys
env = build._test_environment()
env['PYTHONDONTWRITEBYTECODE'] = '1'
groups = [
    [
        'core.tests.fs.test_zip', 'core.tests.fs.test_columns',
        'fman_unittest.test_listing',
        'fman_unittest.impl.plugins.test_plugin',
        'fman_unittest.impl.plugins.test_mother_fs',
        'fman_unittest.impl.test_session',
        'fman_unittest.test_application_context.ApplicationContextTest',
        'fman_integrationtest.impl.plugins.test_plugin.ExternalPluginTest',
        'fman_integrationtest.test_qt.SnapshotFilterBarIT',
        'fman_integrationtest.test_qt.QuickViewIT',
        'fman_integrationtest.test_qt.WindowsCleanupIT',
        'fman_integrationtest.test_qt.PublicUiIT',
    ],
    [
        'fman_unittest.test_quick_view_pdf.PdfControllerTest.test_repeated_use_and_large_pixel_delivery',
        'fman_unittest.test_portable', 'fman_unittest.test_app_name',
        'fman_unittest.test_release_support',
        'fman_integrationtest.impl.plugins.test_error',
    ],
    [
        'fman_integrationtest.test_qt.DirectorySizeIT',
        'fman_integrationtest.test_qt.CommandPaletteRecentIT',
        'fman_unittest.test_search_file_fuzzy',
        'fman_unittest.test_ui_elements',
    ],
]
for modules in groups:
    subprocess.run([sys.executable, '-B', '-m', 'unittest', '-q', *modules],
        env=env, check=True, timeout=180)
'@ | python -B -
```

| Selection | Outcome |
| --- | --- |
| Archive/columns/listing/loader/session/selected Qt group | 287 run, 2 skipped, no failures; 22.795 s |
| PDF resource/portable/metadata/release/traceback group | 48 run, no skips/failures; 9.946 s |
| Directory-size/palette/fuzzy/UI group | 134 run, 2 skipped, no failures; 3.542 s |
| `python -B build.py test-docs` | 6 passed; 10.868 s |
| Real Qt plug-in exception probe | IR01 reproduced; process survived, error details missing |
| Early `FileSystemWrapper.iterdir` close probe | First name delivered; no spurious error report |
| AST caller inspection for F22 | Two call sites; neither can select the recreation branch |

Total: **475 tests run, 4 skipped, no failures**. This does not invalidate IR01:
the existing hook test mocks `handle` and does not check the real plug-in
diagnostic path. The 30-cycle PDF check reported stable handles (207 to 207)
and commit (30.8 MiB to 30.8 MiB), with a 20.5 ms maximum heartbeat gap.
No new test-time or application-speed comparison was performed.

The two skipped cases in the first group were symbolic-link creation checks.
The third group's skips were the opt-in fzf reference check and directory-symlink
creation without the required privilege, not hidden failures.
Not run: full suite, native foreground/focus smoke, frozen packaging,
real SMB/exFAT validation or the performance catalog. Those remain separate
release/storage gates; isolated fallback parity tests do not certify every
remote filename or filesystem response.

This pass changed only this review record. Application/test fixes and new
cleanup implementations require a subsequent request.

## Response to Implementation Review: Claude Opus 5.5 (2026-10-28)

- **IR01 - fixed.** Confirmed: `PluginErrorHandler.handle` called
  `report(message)` without the exception, and `sys.exc_info()` is empty inside
  `sys.excepthook`. `handle` now passes `exc_value`. New regression test
  `ApplicationContextTest.test_excepthook_reports_plugin_qt_callback_error_details`
  uses the real handler, a real plug-in package and a `QTimer` callback. It
  asserts the alert holds the plug-in name, the plug-in source line and
  `ValueError: plug-in detail`, that stderr has the exception, and that the
  process exits normally. It fails without the fix with exactly Sol's alert.
  `fman_unittest.test_application_context`,
  `fman_integrationtest.impl.plugins.test_error` and
  `fman_unittest.impl.plugins.test_plugin`: 27 OK.
- **F20 - agree.** AST check: the five names have no use and no test patches
  them through the module.
- **F21 - agree.** No test or tool sets `_fsparser` to `None`;
  `test_fsparser` asserts the native module loaded.
- **F22 - agree.** Both `_set_location_main` callers omit `recreating` and
  `sort_column`, so the `sort_column` lookup, the `_columns_recreated` flag and
  the `location_loaded` suppression cannot run.
- **F20-F22 - implemented** at the user's request:
  - F20: removed the five unused imports.
  - F21: `_fsparser = _load_native_parser()` unconditionally; removed the
    `Name.keys` Python fallback and its `natural_key` import. The comment now
    names `fman.impl.util.natural.natural_key` as the reference the native
    keys equal.
  - F22: removed `recreating`, `sort_column` and `_columns_recreated`;
    `location_changed` and `location_loaded` are emitted directly.

| Gate | Result |
| --- | --- |
| Fresh imports: `_quick_view_csv_worker`, `fman.impl.quick_view_csv`, `fman.impl.plugins`, `fman.impl.plugins.plugin`, `everything_search.instance`, `core` | OK |
| `fman_unittest.impl.test_quick_view_csv fman_unittest.impl.plugins.test_plugin fman_integrationtest.impl.plugins.test_plugin fman_integrationtest.impl.plugins.test_error fman_unittest.test_everything fman_unittest.test_application_context core.tests.fs.test_fsparser core.tests.fs.test_columns core.tests.fs.test_local fman_unittest.test_listing fman_integrationtest.impl.model.test___init__ fman_unittest.test_search_file_fuzzy fman_unittest.test_ui_elements` | 425 OK, 6 skipped |
| `python -m fman_integrationtest.qt_runner fman_integrationtest.test_qt` | 312 OK, 2 skipped |
| `quick_view_smoke`, `recent_commands_smoke` (`QT_QPA_PLATFORM=windows`) | PASS |

### Pages Failure After F10 (2026-10-29)

- Pages `test-docs` failed: the selection, duplicate-file and batch-renamer
  captures timed out ("did not settle").
- Cause: unlike the release job, Pages keeps the runner's default `TEMP`, an
  8.3 alias (`C:\Users\RUNNER~1\...`). The tests built expected pane paths
  from that alias; panes show the resolved long path, so they never matched.
  Reproduced locally with an 8.3 `TEMP` (same three failures, 96 s).
- Fix: both screenshot test modules use `resolved_temporary_directory()`,
  following the `RUNNER~1` rule in DEVELOPMENT.md. `build.py test-docs` (6) and
  `fman_unittest.test_generate_docs_screenshots` (28) pass with an 8.3 and a
  normal `TEMP`.

