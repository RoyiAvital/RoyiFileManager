# Code Review 001: Dead Code Removal

Status: Completed on 2026-09-24; focused acceptance gates passed.

## Task

Review application source and tests for code that is unreachable, unreferenced,
obsolete, duplicated without a remaining consumer, or otherwise no longer
relevant. Remove only candidates supported by repository-wide evidence, remove
tests that exclusively specify deleted behavior, and validate that the
application's supported functionality remains unchanged.

The review starts with the verified candidates below but is not limited to
them. Finding a candidate is not approval to delete it; every removal must pass
the ownership and dynamic-use checks in Design. This initial inventory records
the starting evidence; Final Inventory below records the completed disposition.

| Initial candidate | Current evidence | Expected action |
| --- | --- | --- |
| `fman.impl.util.os_` (removed) | No source, test, resource or build consumer; fresh host/Core/Favorites imports did not load it. | Removed the orphan internal module; historical references are retained here. |
| [`fman.impl.onboarding.tutorial._is_macos_catalina_or_later`](../src/main/python/fman/impl/onboarding/tutorial.py) | The definition is its only occurrence. | Delete it and its exclusive `platform.mac_ver` import. |
| [`core.os_._is_gnome_based`](../src/main/resources/base/Plugins/Core/core/os_.py) | The definition is its only source occurrence; active Gnome detection is owned by `fbs_runtime.platform`. | Delete it and the resulting unused `os` import. |
| Unused imports in [Tutorial](../src/main/python/fman/impl/onboarding/tutorial.py), [Shortcuts](../src/main/python/fman/impl/shortcuts.py), [Core commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py) and [Favorites](../src/main/resources/base/Plugins/Favorites/favorites/__init__.py) | Lexical and repository-wide searches found no consumers for `show_alert`, `Qt`, `strformat_dict_values`, `QUrl`, `QDesktopServices`, and `exists` in those modules. | Remove individually after confirming they are not intentional exports or import-time dependencies. |
| [`FilterBar._select_row_with_prefix`](../src/main/python/fman/impl/widgets.py) | Its first check returns whenever the source model has `_displayed`; the current snapshot model always defines that attribute. | Remove the unreachable helper and its call; verify filter/find cursor behavior. |
| [`SortedFileSystemModel._num_rows_to_preload`](../src/main/python/fman/impl/model/__init__.py) | Initialized and assigned by `set_num_rows_to_preload`, but never read. The view still invokes the setter on resize. | Remove the write-only state, setter and resize-time call; retain active header precision settings. |
| Lazy-row loading in [FileListView](../src/main/python/fman/impl/view/__init__.py) and [ResizeColumnsToContents](../src/main/python/fman/impl/view/resize_cols_to_contents.py) | The snapshot model's `row_is_loaded` always returns `True`, so no missing rows enter the paint-time load path. Unit tests still exercise the generic helper with a fake model. | Confirm no supported alternate model uses the path; then remove only obsolete row-loading branches, forwarding and tests, preserving active column sizing and repaint behavior. |
| [`FilterBar._accepts`](../src/main/python/fman/impl/widgets.py) | The bound method is registered as a filter, but the snapshot model obtains `snapshot_filter()` from its owner and never calls its URL-matching body. | Preserve a valid snapshot-filter registration while removing the unused URL matcher; verify filtering and counts. |

## Scope

Included:

- Production code under `src/main/python` and bundled plug-ins under
  `src/main/resources/base/Plugins`.
- Unit and integration tests that target removed behavior, obsolete fixtures,
  unused test helpers, and tests that can no longer fail for a supported reason.
- Unused imports, private functions/classes/constants, orphan internal modules,
  obsolete compatibility branches, duplicate implementations, unreachable
  branches, and stale plug-in resources when their lack of use is proven.
- Focused neighboring tests, import/startup checks, native Windows application
  smoke testing, and a clean-source/package-content check.

Excluded:

- Removal based only on naming, age, a single static analyzer, or low textual
  reference count.
- Public `fman` API symbols, intentional package re-exports, supported platform
  code, optional features, error handling, or compatibility behavior unless
  separate evidence proves the contract obsolete.
- Feature changes, broad refactoring, dependency upgrades, formatting churn,
  generated files under `target/`, and speculative performance work.
- The complete `python build.py test` suite unless the user explicitly requests
  it. No clean, freeze, or package build is required by default.

Compatibility: preserve the repository's current public plug-in API and all
documented commands, settings, key bindings, filesystem providers, platform
behavior, and user-visible workflows. Internal removal must not change command
identifiers, import paths exposed to plug-ins, persisted data, or failure
behavior. If a candidate is externally importable or compatibility is unclear,
retain it or move it to a separately reviewed compatibility task.

## Design

### Evidence and Classification

Build a candidate inventory from complementary checks:

1. Search definitions, imports, string references, JSON resources, command
   identifiers, callbacks, tests, documentation, build scripts and packaging.
2. Inspect import-time registration, inheritance, Qt signals/slots, overridden
   methods, reflection, dynamic plug-in loading and platform-conditional paths.
3. Classify each candidate as remove, retain, or investigate. Record the symbol
   or file, evidence, ownership, compatibility risk, affected tests and focused
   validation. Do not leave ambiguous candidates in the removal set.
4. Use static diagnostics and AST/reference scans as candidate generators only.
   A definition-only count is insufficient in this architecture.

Known false-positive categories include dynamically registered
`ApplicationCommand` and `DirectoryPaneCommand` classes, listener methods, Qt
callbacks, imports used as package exports, test discovery hooks, platform-only
implementations and symbols addressed by command strings. The existing
`get_core_services`, `is_modifier_only`, `MAX_COMMAND_UNITS`, quicksearch matcher
exports and imported Core command classes are specifically retained unless new
runtime evidence changes their classification.

Do not group all pre-snapshot `get_str`/`get_sort_value` implementations into the
removal set: drive scanning still calls `DriveName.get_str`, and unit tests
explicitly exercise other per-URL column methods. Evaluate individual methods
against external plug-in contracts before changing them. Windows-only startup
does not by itself authorize removal of non-Windows code.

Before deleting an entire module or resource, verify that no dynamic loader
constructs its name or scans its package. Search outside `src/main` as well as
inside it, including tests, documentation, build configuration and plug-in JSON.
Generated copies under `target/` are evidence about packaging, not source to
edit; subsequent builds must derive only from the source tree.

### Removal Units

Apply removals in small, independently testable groups:

1. Delete isolated imports and private helpers, including imports made unused by
   those helper deletions.
2. Delete an orphan module only after a fresh interpreter proves supported
   startup/import paths do not load it.
3. Remove a duplicate implementation only when one active owner remains and all
   callers use that owner.
4. Remove obsolete tests in the same group as their production behavior. Keep
   neighboring regression tests that protect still-supported behavior.

Do not add tests merely to prove that a deleted private symbol is absent. Add or
strengthen a regression test only when deletion exposes an inadequately covered
supported contract. Test-only candidates require the same evidence standard as
production code: classify the protected contract first. Delete tests only when
that contract is proven obsolete or equivalent coverage is demonstrated elsewhere.
Repair or replace ineffective setup for supported behavior; a failing test or a
test that has not failed recently is not evidence of dead code.

After the first substantive deletion, immediately run the narrowest neighboring
test or import check. A failure blocks further removals in that group. If a
removal changes behavior, restore or redesign it rather than weakening tests to
accept the regression.

### Validation and Failure Handling

Run all checks through [`build._environment()`](../build.py) so application and
bundled plug-in imports resolve exactly as repository tests expect. Use a fresh child process for
import and startup checks to avoid `sys.modules` hiding missing dependencies.
Treat tracebacks from workers or delayed Qt callbacks as failures even if the
test runner otherwise reports success.

If a platform branch cannot be executed on the Windows development host, retain
it unless reference/ownership evidence is conclusive and its supported-platform
validation is available. Do not infer macOS or Linux obsolescence from the
current host alone. Any required cross-platform deletion must be split out or
validated on the affected platform before completion.

The implementation must update `CHANGELOG.md` under Unreleased because source
code is removed. README or developer documentation changes are required only if
the audit removes a documented API, command, setting, setup step or workflow; in
that case compatibility must first be explicitly approved.

## Alternatives

- **Delete everything reported by an unused-code tool:** rejected because Qt,
  plug-in registration, string dispatch and intentional exports produce false
  positives.
- **Limit the task to the initial findings:** lower risk but leaves the requested
  code-and-test review incomplete. The initial table is a reviewed starting set;
  additional candidates still require the same evidence gate.
- **Large cleanup followed by one broad test run:** rejected because regressions
  cannot be attributed reliably. Small removal groups and immediate focused
  checks provide a clear rollback boundary.
- **Keep dead tests as historical documentation:** rejected when the tested
  behavior is removed. Relevant design history belongs in task documents or
  version control; executable tests must protect current contracts.
- **Run the full suite automatically:** deferred under repository policy. Focused
  coverage plus application smoke validation is required; the user may request
  the full suite separately.

## Runtime Effects

- Startup: expected unchanged or marginally reduced import work. Measure import
  or startup only if removal touches an imported module or registration path.
- Steady-state CPU: unchanged; no supported execution path is intentionally
  removed. A measurable behavioral difference invalidates the dead-code claim.
- Memory: unchanged or marginally reduced module/class state; no new caches.
- I/O: no new application I/O, persistence, Registry access or background scans.
- Threads/processes: no new workers, timers, processes or cancellation paths.
- Disabled/no-op behavior: unchanged. Optional disabled features must remain free
  of feature-specific jobs and I/O.
- Build/package: generated output may become smaller, but `target/` is not edited
  directly and size reduction is not an acceptance requirement.

## Tests

### Static and Structural Checks

- Repeat repository-wide exact-name and import searches for every removal after
  editing. Remaining references must be intentional and documented.
- Parse all changed Python files and import affected packages in fresh child
  interpreters using `build._environment()`.
- Check changed files with VS Code/Pylance diagnostics. If an existing dead-code
  analyzer is available, record its version and output; do not install a package
  solely for this task.
- Confirm no deleted source path is referenced by build scripts, plug-in
  resources, documentation or tests. Ignore stale generated `target/` copies as
  inputs and do not modify them.

### Focused Automated Tests

Run the narrowest test after each corresponding removal group, then run this
focused aggregate from the repository root:

```powershell
python -c "import build, subprocess, sys; modules=['fman_unittest.impl.onboarding.test_tutorial','fman_unittest.impl.test_shortcuts','fman_unittest.impl.view.test_resize_cols_to_contents','fman_unittest.impl.test_filter_pattern','fman_unittest.test_listing','fman_unittest.test_application_context','fman_unittest.test_portable','fman_unittest.test_favorites','fman_unittest.test_ui_elements','fman_unittest.test_filter_find_benchmark','core.tests.commands.test___init__','core.tests.fs.test_columns']; sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest',*modules,'-q'],env=build._environment(),timeout=180).returncode)"
```

Run affected bundled plug-in/UI behavior on native Windows:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); modules=['fman_integrationtest.test_qt.MainWindowIT','fman_integrationtest.test_qt.FavoritesManagerIT','fman_integrationtest.test_qt.SortedFileSystemModelIT','fman_integrationtest.test_qt.SnapshotFilterBarIT','fman_integrationtest.test_qt.DirectorySizeIT','fman_integrationtest.test_qt.PanelIT','fman_integrationtest.test_qt.UniformRowHeightsIT']; sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest',*modules,'-q'],env=env,timeout=180).returncode)"
```

Expand the aggregate with the nearest existing test module for every additional
production or test file removed. A deleted test must be shown to cover only a
deleted contract; run its neighboring module before and after removal. Do not
reduce assertions or skip supported behavior to make cleanup pass.

### Application and Manual Checks

- Launch from a fresh process with disposable `UserSettings`; verify startup has
  no import, plug-in registration, command-discovery or worker traceback.
- Verify both panes load a local directory, navigation and sorting work, command
  palette opens and runs a Core command, keyboard shortcuts are listed, Favorites
  opens, and quit completes cleanly.
- Exercise any additional feature whose implementation, resource or test was
  removed. Use its existing integration or smoke runner when one exists.
- Restart once to detect hidden import-order or persisted-settings dependencies.

No performance benchmark is required for behavior-preserving deletions. If an
imported module or startup registration is removed, compare bounded startup/import
timings only to detect regression; do not require a speedup.

## Implementation Steps

1. Review this design and the initial inventory; confirm public API and supported
   platform boundaries before implementation.
2. Generate the full candidate inventory and classify every candidate as remove,
   retain or investigate with concrete reference and ownership evidence.
3. Remove the first isolated helper/import group and immediately run its narrow
   focused test or fresh-process import check.
4. Continue in independently validated groups. Remove obsolete tests only with
   the production contract they exclusively cover; add focused regression
   coverage only for supported behavior exposed as under-tested.
5. Run structural checks, the focused aggregate, affected plug-in/UI integration
   tests, and native Windows startup/workflow smoke checks.
6. Add a concise Unreleased changelog entry describing internal dead-code and
   obsolete-test removal without claiming a user-visible feature.
7. Record the final removal/retention inventory, exact validation results and any
   unavailable platform checks. Add implementation provenance, then move this
   canonical file to `Done/CodeReview001.md` and its index link to Completed.

## Acceptance Criteria

- Every deleted production symbol, module, resource, fixture and test has
  repository-wide evidence that it is obsolete and is recorded in the final
  removal inventory.
- Dynamic plug-in registration, Qt callbacks, string commands, intentional
  exports, public API and supported platform branches are preserved.
- Tests removed by the task exclusively covered deleted behavior; coverage of
  supported contracts is not weakened.
- No remaining source, test, resource, build or documentation reference points
  to deleted code, except preserved historical task records.
- Changed files have no new diagnostics, fresh-process imports succeed, focused
  unit/integration tests pass, and native Windows startup plus listed workflows
  complete without tracebacks.
- The application has no intended functional, persistence, threading or public
  API change. Any discovered behavior change is restored or separately approved.
- `CHANGELOG.md`, implementation provenance and validation results are complete;
  no generated `target/` file is manually edited.

## Final Inventory

### Removed Production Code

| Owner | Removal and evidence | Focused protection |
| --- | --- | --- |
| `fman.impl.util.os_` | Deleted the orphan module and its `name`, `version`, `distribution` helpers. Source/resources/build searches found no consumer; fresh host/Core/Favorites imports did not load it. | Fresh imports, source-only packaging-input check, native startup/restart smokes. |
| [Tutorial](../src/main/python/fman/impl/onboarding/tutorial.py), [Core OS helpers](../src/main/resources/base/Plugins/Core/core/os_.py) | Deleted definition-only `_is_macos_catalina_or_later` and `_is_gnome_based`; active platform detection remains in `fbs_runtime.platform`. | Tutorial/Core tests and native startup; no supported platform branch removed. |
| [Core commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py) | Deleted uncalled `_remove_app`; the live `Configure` to `RemoveApp.on_selected` path owns association removal. | Core command tests and command-discovery smoke. |
| [Shortcut suggestions](../src/main/python/fman/impl/nonexistent_shortcut_handler.py) | Deleted uncalled `_open_url`, two empty-options guards after unconditional appends, and responses for never-offered `Move cursor up/down` choices. Dialog choices come only from offered radio options; free-form text is separate. The reachable F2 empty-options guard remains. | Added supported Left/Right Home/End offer-and-dispatch coverage in the existing shortcut test module. |
| [FilterBar](../src/main/python/fman/impl/widgets.py) | Removed unreachable `_select_row_with_prefix` and uncalled `_accepts` matcher. Registered bound `self.snapshot_filter`, retaining the owner used to capture `snapshot_prefix`. | Snapshot filter/find cursor, selection, count and metadata repaint tests. |
| [Model facade](../src/main/python/fman/impl/model/__init__.py), [ListingModel](../src/main/python/fman/impl/model/listing.py) | Removed write-only `_num_rows_to_preload`, its setter, no-op `row_is_loaded`/`load_rows`, facade forwarding and exclusive `_map_row_to_source`. Every supported facade uses the snapshot source. | Listing/model, public API, filter and native pane tests. |
| [FileListView](../src/main/python/fman/impl/view/__init__.py) | Removed `_urls_being_loaded`, obsolete `paintEvent`, `_get_rows_to_load`, `_on_rows_loaded`. Snapshot rows need no paint-time loading. Kept reset generation, drag cancellation, cursor, selection, scroll and editor handling. | MainWindow, model, filter and uniform-row-height integration tests. |
| [Column resizing](../src/main/python/fman/impl/view/resize_cols_to_contents.py) | Removed preload setter call, obsolete preload comment, `_has_rows_visible_but_not_loaded` guard/helper and `_get_rows_visible_but_not_loaded`. Retained visible-row precision and all active sizing logic. | Twelve neighboring geometry unit tests and native pane resizing tests. |

Removed exclusive or unused imports: Tutorial `mac_ver`/`show_alert`; Core OS
`os`; [Shortcuts](../src/main/python/fman/impl/shortcuts.py) `Qt`; Core commands
`strformat_dict_values`/`QUrl`/`QDesktopServices`; [Favorites](../src/main/resources/base/Plugins/Favorites/favorites/__init__.py)
`exists`; FilterBar `DisplayRole`/`basename`; shortcut suggestions
`QUrl`/`QDesktopServices`. Reference and import-side-effect checks preceded removal.

### Tests and Fixtures

- Removed four `RowsVisibleButNotLoadedTest` cases, their exclusive `_View` and
  `_Model` fakes, and the unused `ResizeColumnsToContents` import from
  [the existing resize test module](../src/unittest/python/fman_unittest/impl/view/test_resize_cols_to_contents.py).
  They specified only the deleted lazy-row contract; all twelve active geometry
  tests remain and pass.
- Removed unused `Task`/`basename` imports from [Core test helpers](../src/main/resources/base/Plugins/Core/core/tests/__init__.py)
  and `os` imports from the [filter/find harness](../src/performancetest/python/fman_performancetest/filter_find.py)
  and [legacy comparison harness](../src/performancetest/python/fman_performancetest/legacy.py).
- Removed obsolete source-model `_worker` teardown from the six source smokes
  named below. They now use existing application exit, which closes services and
  shuts down each current facade. Feature-specific cancellation/child cleanup
  remains. Directory Size fixtures in [test_qt.py](../src/integrationtest/python/fman_integrationtest/test_qt.py)
  likewise use current facade ownership; removed the ineffective comparison to
  nonexistent model-worker IDs while retaining the real worker-versus-Qt-thread,
  queued delivery, cancellation and stale-result assertions.
- With explicit user approval, repaired the two pre-existing Favorites Escape
  test failures by waiting for native prompt exposure before input. All original
  assertions remain; no application dialog code changed.
- Repaired the Favorites smoke's assumption that already-capped buttons must
  grow between 960 and 1440 pixels. It now checks nondecreasing widths, the 160px
  cap and unclipped labels. The independent Panel test still checks actual growth
  below the cap, its limit and a custom cap.
- Repaired the comparator smoke's empty-file race by publishing child argument
  JSON with an atomic temporary-file replacement. Actual argv, nonblocking
  execution, persistence, restart and clear checks remain unchanged.

### Retained and Out of Scope

- Retained intentional exports/registrations flagged by the final AST scan:
  `fbs_runtime.application_context.cached_property`,
  `fman.impl.plugins.sanitize_key_bindings`, Core Directory Size and QuickView
  commands/services, `DirSize`, `ShowExplorerProperties`, local filesystem
  providers/`DriveName`, the five quicksearch matcher exports,
  `MAX_COMMAND_UNITS`, and the platform-selected `move_to_trash`. Import consumers,
  dynamic discovery, platform dispatch or compatibility boundaries justify keeping
  them; local non-use alone does not justify an API removal.
- Retained `get_core_services`, `is_modifier_only`, per-URL column methods,
  supported platform code, Qt overrides and disabled-feature paths.
- Retained conditional old-worker support in both historical
  [integration](../src/integrationtest/python/fman_integrationtest/pane_rendering_benchmark.py)
  and [performance](../src/performancetest/python/fman_performancetest/pane_rendering_benchmark.py)
  pane comparison runners. Their `--baseline-ref` runs isolated older revisions;
  those branches are not current-application leftovers.
- Developer prototypes under `src/misc` are outside this application's/test
  cleanup scope; import flags there were not used to broaden the task.
- No documented API, command, setting or workflow changed, so no README change
  was needed. No speed, memory or mathematical whole-repository liveness claim is
  made. All verified in-scope removal candidates were resolved.

## Validation Results

### Automated Gates

- Before implementation: 119 unit tests passed; native baseline ran 76 tests with
  two reproducible Favorites failures. Both also failed through the Qt runner.
  After the exposure-wait repair, both passed and the original native gate passed
  all 76 tests. These were retained tests, not deletions or skips.
- Immediate removal gates passed: isolated helpers/imports 132 tests; snapshot
  loading/view cleanup 63; Core helpers/columns/context 110; final shortcut and
  lightweight benchmark-harness cleanup 47. The standalone native button-growth
  regression also passed.
- Final unit/API gate: **277 passed** in 4.518 seconds, using the exact expanded
  unit command in Tests above.
- Final native gate: **95 passed** in 8.495 seconds, using the exact expanded
  Windows command in Tests above. Includes Directory Size full Core startup,
  blocked-scan navigation, cancellation and restored enablement.
- Parsed all **229 Python files** under application, unit, integration and
  performance-test roots with stdlib AST; the earlier wider candidate scan parsed
  237 files including developer scripts. No remaining definition-only private
  candidates in the final scoped scan. Remaining import flags are classified above.
- Exact retired-symbol scans found no remaining application/test/resource
  references. Build script/spec parsing and input inspection found no orphan
  module reference or generated application source input. Fresh imports of
  application context, Tutorial, Core commands and Favorites passed.
- VS Code diagnostics reported no errors in changed Python files. No unused-code
  analyzer was installed. Git was unavailable on PATH, so no Git-based diff/status
  check was available; checks used the working source tree.

### Native Source Smokes

Favorites command, using disposable settings:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','fman_integrationtest.favorites_smoke'],env=env,timeout=75).returncode)"
```

Passed startup, dock/button geometry, close icon, pane restoration/reopening,
session reuse, query, rename persistence, Go To, deletion, empty state and focus
recovery. The 200-row filter/sort check reported 5.98ms p95; this is smoke evidence,
not a claimed cleanup speedup. A second monitor was unavailable.

Command palette and restart command:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','fman_integrationtest.recent_commands_smoke'],env=build._environment(),timeout=180).returncode)"
```

All nine native processes passed: scales 1, 1.5 and 2, each with record, reload
and restore. Checked Core commands, sorting picker, filtering, bundled hint widths,
actual plug-in reload, no interim history writes and persisted restart.

Four additional source smokes, run sequentially:

```powershell
& {
$check = @'
import build
import os
import subprocess
import sys
environment = build._environment()
environment['QT_QPA_PLATFORM'] = 'windows'
environment['QT_QPA_FONTDIR'] = os.path.join(os.environ['WINDIR'], 'Fonts')
for name in ('comparator_smoke', 'find_files_smoke', 'hash_smoke', 'search_files_smoke'):
    result = subprocess.run(
        [sys.executable, '-X', 'faulthandler', '-m', 'fman_integrationtest.' + name],
        env=environment, timeout=100)
    if result.returncode:
        sys.exit(result.returncode)
'@
python -c $check
}
```

All passed: comparator setup/argv/nonblocking execution/restart/clear; Find Files
startup/Shift+F7/layout/persistence/counts/navigation with real `fd`; hash algorithms,
copy, Enter, centering, icon pixels, QuickSearch cancellation and close; Search
Files startup/modes/persistence/globs/layout/modal and file navigation.

Additional native Help procedure: launched a fresh source application with
disposable settings through the existing recent-command smoke harness; invoked
the actual `Help` command, inspected `ShortcutsDialog` on the Qt thread, checked
F3/F4/Shift+F4 among **68 built-in shortcuts**, filtered for F3, cleared the query
and checked row restoration, then closed it and ran the normal record-phase
palette smoke. All passed, including 83 bundled hint-width checks and clean exit.

### Limits

No complete `python build.py test`, clean/freeze/package build, frozen executable,
macOS/Linux runtime, large performance workload or optional 2GiB hash benchmark
was run. Packaging validation was source/input inspection, not a rebuilt artifact.
The second-monitor check was unavailable. No packages or environments were added,
and no generated file was manually edited. The focused required gates passed;
these checks do not prove every possible third-party plug-in or platform workflow.

## Reviewers

### 2026_09_24 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context Window: 272K
- Outcome: Defined an evidence-gated dead-code and obsolete-test review with an
  initial verified inventory, protection for dynamic/public contracts, staged
  deletion, focused tests and native Windows application validation. Design only;
  implementation requires review.

### 2026_09_24 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Sol
- Effort: High
- Context Window: 272K
- Outcome: Added snapshot-era pane/view candidates and focused checks. Retained
  bound filter registration, active column sizing and per-URL column consumers as
  explicit review boundaries; implementation remains pending.

### 2026_09_24 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Changes requested before implementation approval. The proposed unit
  gate passes, but two native Qt baseline failures reproduce before any cleanup.
  Tighten the dead-test classification so an ineffective test setup cannot by
  itself justify removing coverage of a supported contract. No application or
  test code changed during this review.

#### Findings

1. **P1 - Establish a usable native validation baseline.** The exact native
   aggregate in Tests runs 76 tests with two failures in `FavoritesManagerIT`:
   `test_rename_targets_current_and_escape_keeps_manager` finds the manager
   closed after Escape, and
   `test_shared_confirmation_defaults_to_no_and_escape_keeps_manager` finds the
   prompt still open. See the assertions in
   [the rename test](../src/integrationtest/python/fman_integrationtest/test_qt.py#L5864)
   and [the confirmation test](../src/integrationtest/python/fman_integrationtest/test_qt.py#L5671).
   Both failures repeat together in a fresh focused process. They predate this
   cleanup; the cause has not been established as application, test-harness or
   environment behavior. Record and triage them before deletion, establish a
   passing supported baseline, and do not remove or weaken these tests merely
   to make the dead-code task pass. Any unrelated fix needs separate scope.
2. **P2 - Separate ineffective tests from obsolete contracts.** Removal Units
   currently calls a test dead when its setup cannot exercise the asserted path.
   That condition can describe a broken test of still-supported behavior, not
   deleted functionality. It conflicts with Implementation Steps and Acceptance
   Criteria, which require removed tests to exclusively cover deleted contracts.
   Require classification of the protected behavior first: repair or replace
   ineffective coverage of supported behavior; delete only tests and fixtures
   whose contract is proven obsolete or whose equivalent coverage is explicitly
   demonstrated elsewhere. A failing baseline test is not dead-code evidence.

#### Confirmed Boundaries

- The snapshot model owns prefix selection and always reports rows loaded. The
  lazy-load and preload candidates are credible, subject to the planned complete
  reference and compatibility audit; keep model-reset drag/editor invalidation
  and active column sizing intact.
- Preserve **bound-method ownership**, not merely a valid `snapshot_filter`
  provider, when replacing `FilterBar._accepts`: filter capture accepts either
  shape, but [prefix capture](../src/main/python/fman/impl/model/listing.py#L305)
  obtains `snapshot_prefix` only from the registered method's `__self__`.
  The selected `SnapshotFilterBarIT` includes prefix-cursor, find-mode restoration,
  selection and metadata repaint coverage.

#### Review Validation

- Ran the exact focused unit aggregate in Tests: **119 passed**.
- Ran the exact native Windows Qt aggregate in Tests: **76 run, 74 passed,
  2 failed**, with the assertions recorded above. No production edits preceded
  these checks.
- Reran only the two failing tests in a fresh child process using this command:

  ```powershell
  python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); tests=['fman_integrationtest.test_qt.FavoritesManagerIT.test_rename_targets_current_and_escape_keeps_manager','fman_integrationtest.test_qt.FavoritesManagerIT.test_shared_confirmation_defaults_to_no_and_escape_keeps_manager']; sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest',*tests,'-v'],env=env,timeout=45).returncode)"
  ```

  Result: **2 run, 2 failed**, at the same assertions.
- Full application/restart smoke, package-content validation, cross-platform
  execution and the full suite were not run. This is a design review, not a
  completed removal audit or implementation acceptance.

### 2026_09_24 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User authorized implementation and prerequisite baseline repair.
  Resolved the dead-test classification ambiguity. Both existing Favorites tests
  pass after waiting for native prompt exposure before sending Escape, with all
  original assertions retained and no application dialog changes. The complete
  focused native baseline now passes all 76 tests. Proceed with staged removals;
  final acceptance still requires the remaining audit and validation gates.

## Implementer

### 2026_09_24 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Removed verified dead helpers/imports, the orphan OS module, obsolete
  snapshot loading paths and unreachable shortcut choices. Retained dynamic and
  compatibility contracts, repaired supported test/smoke fixtures, and added
  shortcut suggestion coverage. Final gates: 277 unit/API tests, 95 native Qt
  tests, six source smoke runners, native Help inspection and structural checks
  passed. Limits are recorded above; no functional change is intended.