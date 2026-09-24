# Code Review 002: Application Name Single Source

Status: Completed on 2026-09-24. Focused tests, generated documentation and the
user-approved isolated source/frozen rename checks passed.

## Task

Make [`app_name`](../src/build/settings/base.json) the only definition of the
application's product name. Changing this value must propagate to runtime UI,
Qt identity, build and package names, the frozen executable and directory,
release artifacts, generated documentation, screenshot tooling and their tests
without another product-name edit.

`build.py` may expose one module-level `APP_NAME` constant, but it must load that
value from `base.json`; it must not repeat the product-name literal. Consumers at
other process boundaries may read the same JSON independently. Generated output
may contain the resolved name, but no generated copy becomes authoritative.

This is an application rename mechanism, not an automatic GitHub repository
rename. Stable external and compatibility identifiers are classified explicitly
below so a product rename neither breaks them nor mistakes them for a second
product-name definition.

## Scope

Included:

- Development and frozen runtime names: window/dialog titles, Qt application
  identity, Windows AppUserModelID, profile filename and user-facing product
  prose in Python and bundled plug-ins.
- Build, freeze and package outputs: distribution folder, executable, archive,
  error/help text and PyInstaller `EXE`/`COLLECT` names.
- Release workflow artifact names and release titles.
- MkDocs site name, copyright and current product prose rendered from docs.
- Packaged screenshot executable discovery and window-title expectations.
- Product headings in the generated local performance report, without changing
  benchmark suite IDs, fixture formats or stored result schemas.
- Unit, integration, structural and rename-probe coverage.
- Rename the product-named PyInstaller source file to a neutral
  `application.spec` and update all live and historical links to that real path.
- Remove or start honoring stale name-related settings such as `freeze_dir`; do
  not leave a second, misleading output-path contract.

Excluded or preserved as independent identities:

- README files, DEVELOPMENT and similar repository prose, per the user's
  implementation-time clarification. Product substitutions apply to generated
  documentation under `docs/`, not these files. Earlier proposed edits to them
  are superseded; only the implementation's own edits were restored.
- GitHub owner/repository slug `RoyiAvital/RoyiFileManager`, Pages URL path,
  release-download URLs and badges. These identify an external repository and
  do not change merely because the product display name changes.
- Existing environment variables such as `ROYIFILEMANAGER_USER_SETTINGS` and
  `ROYIFILEMANAGER_BUILD_CONSOLE`. They are compatibility APIs. New neutral
  aliases may be considered separately, but this task must not silently break
  existing scripts.
- Stable serialized/protocol identifiers, benchmark suite IDs and fixture format
  headers. They remain unchanged unless a migration is separately designed.
- Lowercase screenshot asset filenames. They are stable asset IDs; captions and
  rendered prose use the configured product name.
- Historical wording in `CHANGELOG.md`, `Done/`, reviewer records and released
  documentation. Links to renamed live files must still be repaired.
- Automatically renaming a conda environment already installed on a developer's
  machine, repository folder, GitHub project, Python package or public `fman`
  namespace.
- The existing `RoyiFileManager` conda environment label, which is a stable
  development identifier rather than product display text.

Compatibility: preserve the public `fman` plug-in API, settings location,
environment-variable overrides, repository links, persisted data and command
identifiers. Changing `app_name` intentionally changes visible product text,
Windows taskbar identity, executable/distribution/archive names and release
title. It must not move `UserSettings` or write to the Registry.
With the current `app_name` unchanged, the identity mechanism change itself is
user-invisible and does not migrate taskbar pins or settings.

## Design

### Settings Ownership and Validation

[`base.json`](../src/build/settings/base.json) owns the sole product-name value:

```json
{
  "app_name": "RoyiFileManager"
}
```

Load and validate the full settings document at each natural process boundary
through one shared standard-library helper under `fbs_runtime`. A name must match
`[A-Za-z][A-Za-z0-9_-]{0,63}` and must not be a case-insensitive Windows device
name (`CON`, `PRN`, `AUX`, `NUL`, `COM1` through `COM9`, `LPT1` through `LPT9`).
This explicitly excludes spaces, dots, control characters, separators and long
names. All consumers use the same validator and test vectors, including CI and
docs. Report the settings path and invalid field without a fallback literal.

Do not search-and-replace arbitrary files at runtime. Do not use an environment
variable as a higher-priority name source. Tests may inject a settings path or
document into pure loaders, but production always resolves `base.json`.

The current `freeze_dir: "target/${app_name}"` is not interpreted. Prefer
removing it and deriving `TARGET_DIR / APP_NAME` in `build.py`. If review keeps
it, implement strict `string.Template.substitute` against validated settings and
reject absolute or escaping paths. Do not retain its present inert state.

### Build and Packaging Boundary

In [`build.py`](../build.py), load settings once after `ROOT` and
`SETTINGS_PATH` are known:

```python
BUILD_SETTINGS = _load_build_settings(SETTINGS_PATH)
APP_NAME = BUILD_SETTINGS['app_name']
```

The shared helper uses `json` and `pathlib`, validates the name, and returns an
immutable-enough process snapshot; consumers do not reread the file. Derive
`DIST_DIR`, archive filename, user-facing messages and argument-parser text from
`APP_NAME`. Reuse `BUILD_SETTINGS['version']` in packaging instead of reopening
the JSON. The constant is a convenience, not another definition.

Use the neutral [application.spec](../application.spec), renamed from the former
product-named source file.
The spec runs in a separate PyInstaller execution context, so it loads the shared
standard-library helper and reads `src/build/settings/base.json` independently.
It must not import `build.py`, which would couple PyInstaller evaluation to build
command initialization and side effects. Use the loaded name for both `EXE` and
`COLLECT`, continue bundling `base.json` at
`resources/build-settings/base.json`, and keep the console compatibility
environment variable unchanged.

`build.py freeze` invokes the neutral spec path. Existing tests that inspect the
spec use the neutral path and assert that `EXE` and `COLLECT` consume the loaded
name rather than a literal. All planning and completion documents linking to the
old source filename are updated so no link becomes stale.
Move PyInstaller work output to `target/.pyinstaller`, disjoint from every valid
product directory. Test `app_name=build` as well as the ordinary sentinel.

### Runtime Boundary

Keep [`ApplicationContext.build_settings`](../src/main/python/fbs_runtime/application_context/PyQt5.py)
as the development/frozen resource loader. Extract its path resolution and JSON
read into a small process-cached helper callable before Qt application
construction, while retaining the cached property. Both the property and runtime
product module call this same helper, so runtime performs one JSON read and owns
one settings snapshot. Tests clear or replace the helper's cache explicitly.
Development reads the repository settings; frozen execution reads the bundled
settings under `sys._MEIPASS`.

Add one internal runtime product-settings module, for example
`fman.impl.product`, that validates the loaded document and exposes `APP_NAME`
for runtime Python modules. It is private, standard-library-only apart from the
existing fbs path resolver, performs no I/O after first import, and avoids
constructor changes across every tutorial/helper solely for branding text.
`build.py` and the PyInstaller spec do not import this module.

Use the runtime value for:

- `_set_windows_app_id`, Qt organization/application identity and main-window
  title in `fman.impl.application_context`.
- Platform errors and frozen profile filename in `fman.main`.
- Prompt/dialog titles and current product prose in onboarding, usage and
  nonexistent-shortcut guidance.
- Current product text and command aliases in bundled Core where the old literal
  refers to the running application.

Prompt titles may use the already configured Qt application name or main-window
title rather than import settings again. Repository hyperlinks in About remain
the stable external URLs, while the visible product heading uses `APP_NAME`.
This private configuration path does not add a public `fman` API constant.

Qt organization/application name changes are expected when `app_name` changes.
The portable settings directory does not use Qt's default settings location and
remains `UserSettings`, so the rename must not migrate user data. Deriving the
Windows AppUserModelID intentionally creates a new taskbar identity for a new
product name; document this effect.

### CI, Release and Documentation Boundaries

GitHub Actions cannot import runtime state. Resolve settings in the checked-out
release build job through the shared standard-library helper before environment
setup, then export the validated name through step/job outputs. The publish job
has no checkout: it must consume the build job's resolved name, not read another
settings file. Use it for artifact names, release title and product-named paths.
Leave conda labels, setup commands and cache keys unchanged as independent
development identifiers; no environment recreation or renaming is required.

Use a standard MkDocs local hook, loaded by `mkdocs.yml`, to read `base.json` and:

- Set `config.site_name` and product-name copyright text.
- Expose `app_name` to templates.
- Replace one documented token such as `{{ app_name }}` in page Markdown before
  rendering.

Convert current product-name prose under `docs/` to that token, including explicit
tokens in executable/archive examples and fenced commands. Substitute only this
opt-in token; do not search-and-replace ordinary text, URLs or asset paths.
Existing repository links and asset filenames contain no token and remain
unchanged. Implement substitution through the MkDocs page hook. `python build.py doc`
must fail clearly when settings are invalid. Generated `site/` remains an output
and is never hand-edited.

README, DEVELOPMENT and similar directly rendered repository prose are excluded
by the user's clarified scope. Do not rewrite their text or installation examples
in this task. Record their literals as explicit out-of-scope documentation.

Screenshot source mode obtains the runtime window name from settings. Packaged
mode derives the default executable path from `app_name`; generated screenshot
asset names remain stable. Tests compare against the loaded name rather than the
current literal.

### Rename Audit and Exemptions

Use focused sentinel tests for the known consumers and a recorded repository
literal/path search at completion. Do not build a general semantic scanner.
Classify remaining matches rather than blindly requiring zero text matches:

| Classification | Policy |
| --- | --- |
| Product definition | Exactly one: `base.json` `app_name`. |
| Derived executable/runtime/build/docs value | Literal forbidden; consumer must load or receive `app_name`. |
| Stable repository URL/slug | Allowed by exact path/context allowlist. |
| Compatibility identifier | Allowed and documented; includes legacy uppercase environment variables. |
| Stable asset/protocol identifier | Allowed only when rename-independent and tested as such. |
| Historical record | Allowed under `Done/`, released changelog entries and reviewer history. |
| Generated output | Excluded as input; regenerate to verify the new value. |

Keep the recorded exceptions narrow and reviewable. Do not exempt entire active
source trees. Also search product-named source paths such as the old spec filename.

The decisive rename probe uses a temporary repository/settings fixture with a
sentinel such as `RfmRenameProbe`, never edits the developer's canonical
`base.json`, and verifies all pure loaders and generated names. Integration
validation may use a temporary copy/worktree where a real source/frozen launch
is required. It must verify absence of the old product name from rename-sensitive
outputs while preserving allowlisted external identifiers.

## Alternatives

- **One literal Python constant imported everywhere:** rejected because JSON,
  PyInstaller, GitHub Actions and MkDocs run in different contexts, and
  `base.json` is the requested authority.
- **Import `build.py` from runtime or the PyInstaller spec:** rejected because it
  couples application startup/spec evaluation to build initialization and paths.
- **Generate a Python source module from JSON:** workable but adds a generated
  source synchronization problem. The existing bundled settings loader and one
  small private runtime module are simpler.
- **Pass `app_name` through every constructor:** explicit but creates broad API
  churn for tutorials, helpers and dialogs whose only need is immutable product
  metadata.
- **Global repository search-and-replace whenever renamed:** rejected because it
  cannot distinguish product identity from repository URLs, compatibility IDs,
  protocols or history and does not enforce future consistency.
- **Template every Markdown file:** rejected for GitHub-rendered historical and
  repository documents. Template active MkDocs pages and use neutral placeholders
  where direct GitHub rendering cannot load settings.
- **Rename legacy environment variables with the product:** rejected as an
  unnecessary compatibility break. They are identifiers, not product display.
- **Keep the product-named spec filename:** functional but leaves source tooling
  visibly tied to the old default after a rename. A neutral filename is clearer.
- **Permissive display names or dot-containing identifiers:** rejected for this
  task; one conservative artifact-safe name avoids escaping and trailing-dot
  ambiguities. Windows device-name rejection remains required.
- **Rename the conda label or build a semantic literal scanner:** rejected as
  unnecessary expansion; stable environment identity and focused probes suffice.
- **Only rename MkDocs site metadata:** rejected because the requested one-field
  rename must also update current page prose and executable instructions.

## Runtime Effects

- Startup: one small cached JSON read already exists. The private runtime module
  may move that read earlier but must not add repeated I/O.
- Steady-state CPU: no recurring work; name interpolation occurs during object or
  message construction only.
- Memory: one settings dictionary and short immutable name per process.
- Build/docs/CI: one bounded settings snapshot per consuming process. CI's
  existing version-validation step separately reads version metadata. No network access,
  worker, timer or recurring scan is added.
- Persistence: `UserSettings` location and contents are unchanged. Qt metadata
  and Windows taskbar identity use the configured name but do not write the
  Registry intentionally.
- Disabled/no-op path: not applicable; every application needs a valid name.
  Invalid settings fail before partial build, packaging or UI initialization.
- Packaging: folder, executable, archive and release display names intentionally
  change when `app_name` changes. Repository URLs and compatibility IDs do not.

## Tests

### Unit and Structural Tests

The implemented `fman_unittest.test_app_name` module covers:

- Valid current and sentinel names; missing, wrong-type, blank, path-like,
  Windows-invalid, reserved, trailing-dot/space, control-character and overlong
  values.
- `build.py` loads once and derives distribution/archive/help names from injected
  settings without embedding the default literal.
- Development and frozen settings lookup return the configured name and keep a
  cached snapshot after the file is removed.
- Runtime `APP_NAME`, Qt application metadata, window/dialog titles, product
  messages and profile filename derive from sentinel settings.
- `application.spec` reads JSON and passes the value to both `EXE` and `COLLECT`;
  bundled data still contains `base.json` at the expected frozen path.
- Screenshot default executable/window discovery derives the name while asset
  filenames remain stable.
- MkDocs hook substitutes prose tokens, sets site metadata, preserves code
  fences/URLs/assets without tokens, resolves explicit command/example tokens,
  and reports invalid or missing settings.
- Release workflow uses the parsed name for artifact/title output and does not
  contain a second product-name scalar.
- Sentinel tests exercise the known consumers; completion search classifies all
  remaining repository/compatibility/history/generated occurrences.
- The valid name `build` does not overlap PyInstaller work output.

Update existing application-context, portable, screenshot, packaging-inspection,
Core command/About and release-support tests. All modules below now exist.

After each runtime edit, run its focused sentinel test immediately.
Then run the focused aggregate from the application environment:

```powershell
python -c "import build, subprocess, sys; modules=['fman_unittest.test_app_name','fman_unittest.test_application_context','fman_unittest.test_portable','fman_unittest.test_generate_docs_screenshots','fman_unittest.test_find_files','fman_unittest.test_quick_view','fman_unittest.test_release_support','fman_unittest.test_filter_find_benchmark','fman_unittest.impl.onboarding.test_tutorial','fman_unittest.impl.test_shortcuts','core.tests.commands.test___init__']; sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest',*modules,'-q'],env=build._environment(),timeout=180).returncode)"
```

Run documentation validation:

```powershell
python build.py doc
```

The current checkout is missing a screenshot referenced by configuration docs.
Generate source screenshots first, as the existing Pages workflow already does,
or use an isolated docs fixture containing the generated assets. Do not remove
the reference or weaken strict mode to hide that prerequisite.

Run native Windows integration for actual Qt metadata, title-dependent window
discovery and startup:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); modules=['fman_integrationtest.test_qt.MainWindowIT']; sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest',*modules,'-q'],env=env,timeout=120).returncode)"
```

### Rename and Packaging Checks

In a temporary copy or isolated fixture, set `app_name` to `RfmRenameProbe` and
verify:

- Source startup shows the sentinel in Qt metadata, main/prompt titles and
  current product prose without the old display name.
- Build dry-run/pure helpers resolve
  `target/RfmRenameProbe/RfmRenameProbe.exe` and
  `RfmRenameProbe-<version>-windows-x86_64.zip`.
- PyInstaller spec evaluation uses the sentinel for `EXE` and `COLLECT`.
- MkDocs strict output uses the sentinel for site metadata and rendered product
  prose while stable repository links and asset URLs remain unchanged.
- Release workflow contract derives sentinel artifact and title values.
- CI and documented setup retain the existing conda label independently of the
  sentinel product name.
- Legacy settings/console environment variables continue to work.

Because repository policy avoids automatic freeze/package work, do not run
`build.py clean`, `freeze` or `package` merely while writing this plan. Before
implementation completion, obtain explicit approval for one isolated real
freeze/package rename smoke, or record that packaging remains unverified and do
not mark the packaging acceptance criteria complete. The smoke must inspect the
executable, directory, bundled `base.json`, archive root/name and launch title;
it must leave canonical settings untouched and must not reuse generated output as
source.

Do not run the complete `python build.py test` suite unless explicitly requested.

## Implementation Steps

1. Review the identity classifications, name validation policy, compatibility
   exemptions and packaging-smoke requirement.
2. Add pure settings/name validation and failing sentinel tests. Establish the
  known-consumer inventory before replacing literals.
3. Make `build.py` load one settings snapshot and derive paths, artifacts and
   messages. Rename the spec to `application.spec`, read JSON in its execution
   boundary and repair all source/document links. Run focused build/spec tests.
4. Add the private cached runtime product settings and replace runtime/UI/Core
   product literals. Validate development and frozen-path unit cases immediately,
   then run native Qt integration.
5. Derive screenshot and release workflow outputs. Preserve documented external
  URLs, asset IDs, conda labels and legacy environment-variable names.
6. Add the MkDocs hook and convert active generated docs prose to its token.
  Leave README and similar repository prose unchanged. Run strict docs build.
7. Run the sentinel rename probe, focused aggregate and manual source startup.
   With explicit approval, run the isolated freeze/package/launch smoke.
8. Update `CHANGELOG.md` under Unreleased. Record validation, implementation provenance
   and remaining exemptions, then move this task to `Done/CodeReview002.md` and
   its index entry to Completed.

## Acceptance Criteria

- `src/build/settings/base.json` contains the sole application product-name
  definition; `build.py` `APP_NAME` and every process-boundary consumer load it.
- Changing only `app_name` to a valid sentinel updates source runtime UI/Qt
  identity, build paths, executable/distribution/archive names, release
  artifact/title, screenshot discovery and generated MkDocs product prose.
- Development and frozen runtime use the same bundled setting, with clear
  failure for missing or invalid values and no fallback literal.
- The neutral PyInstaller spec has no product-name literal and supplies the
  configured value to both `EXE` and `COLLECT`; all references to its old source
  filename are repaired.
- Stable repository URLs, Pages path, asset IDs, protocol markers, historical
  records and legacy environment variables remain unchanged and are documented
  in the completion inventory.
- User settings location, public `fman` API, command IDs, persisted data and
  Registry behavior are unchanged.
- Focused tests, strict docs build, native Windows startup/integration and the
  sentinel rename probe pass without worker/callback tracebacks.
- A real isolated freeze/package smoke either verifies the renamed executable,
  directory, archive, bundled settings and launch title, or completion remains
  blocked pending explicit approval to run it.
- README, DEVELOPMENT and similar prose remain unchanged, per user direction;
  the Unreleased changelog describes the implemented behavior;
  generated `target/` and `site/` files are not hand-edited.

## Reviewers

### 2026_09_24 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-5.6 Sol
- Effort: High
- Context Window: 272K
- Outcome: Designed `base.json` as the sole product-name definition across
  runtime, build, PyInstaller, CI release, screenshots and generated docs. Added
  validation, compatibility classifications, a strict literal audit, sentinel
  rename probe and explicit packaging verification gate. Design only; review is
  required before implementation.

### 2026_09_24 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved in principle; three scope reductions and three design gaps
  before implementation. Verified the literal inventory: `build.py` (six
  uses), `RoyiFileManager.spec` (`EXE`/`COLLECT`), `mkdocs.yml`
  (`site_name`, `copyright`), `release.yml`/`pages.yml` (`RELEASE_ENV`,
  `DOCS_ENV`, artifact and title), `environment.yml` (`name`),
  `application_context.py` (AppUserModelID, three Qt names, window title),
  `main.py` (platform error, profile filename), `widgets.py` (prompt title)
  and about 25 prose strings in tutorial/cleanup guide/usage helper/shortcut
  handler. The identity classification table and the "spec must not import
  `build.py`" rule are correct. The runtime path already exists:
  `ApplicationContext.build_settings` reads `base.json` in both modes, so
  `fman.impl.product` is a thin cache over it, as the plan says.

#### Follow Up Tasks

- [ ] **Drop the strict rename audit from this task.** A classifying scanner
      with a semantic allowlist is the largest single piece of work in the
      plan and its value is defensive against a rename that will happen
      rarely, if ever. Replace it with one focused test that asserts the
      known rename-sensitive consumers (`build.py` paths, spec `EXE`/`COLLECT`,
      Qt identity, window title, profile filename, release outputs) derive
      from a sentinel. Grep remains the tool for prose; a hard-fail audit is
      out of proportion to the risk.
- [ ] **Drop the `rfm-dev` conda rename.** `environment.yml` `name` is a
      developer-machine label, not product branding, and the plan itself
      says it is independent of `app_name`. Renaming it forces every
      contributor to recreate or rename an environment and touches README,
      DEVELOPMENT, both workflows and cache keys for zero user-visible gain.
      Leave `RoyiFileManager` as the environment name and record it in the
      Compatibility identifier row.
- [ ] **Make the MkDocs prose token optional.** The hook is right for
      `site_name`/`copyright`, but converting all `docs/` prose to
      `{{ app_name }}`, with rules for skipping fences, URLs and asset paths,
      is a documentation rewrite whose rendered output is identical today.
      Set site metadata from the hook; leave prose as ordinary text unless a
      rename actually occurs. Keep the runtime prose interpolation (tutorial,
      usage helper) since that is cheap and tested by existing suites.
- [ ] **State that the Qt/AppUserModelID mechanism change is user-invisible
      today.** Switching `setApplicationName` and the AppUserModelID from the
      literal to the loaded value is a no-op while `app_name` stays
      `RoyiFileManager`; only a future value change affects taskbar pins.
      Say so under Compatibility so the change is not read as a migration.
- [ ] **Bound the name-validation contract.** Design offers either a
      permissive Windows-filename rule or a conservative identifier form.
      Pick the identifier form (`^[A-Za-z][A-Za-z0-9._-]{0,63}$`): it is a
      subset of valid filenames, AppUserModelIDs and archive names, needs no
      reserved-device or trailing-dot table, and matches what a product name
      is in practice. Record the rejected permissive rule in Alternatives.
- [ ] **Add the frozen bundling assertion to Tests.** The spec already ships
      `base.json` at `resources/build-settings/base.json`; frozen runtime
      reads it there, but no listed test asserts that `datas` entry survives
      the spec rename. One assertion in the spec-inspection test.

### 2026_09_24 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Changes requested before implementation. The earlier validation
  recommendation does not meet the stated Windows filename contract. Keep the
  single-source goal and compatibility boundaries; resolve the findings below
  without treating optional scope reductions as approved requirements changes.

#### Findings

1. **P2 - Do not use the proposed identifier regex as the complete validator.**
   `^[A-Za-z][A-Za-z0-9._-]{0,63}$` admits `CON`, `NUL.txt`, `COM1`, `LPT1`
   and names ending in a dot. Those do not satisfy the required Windows artifact
   naming contract. The previous recommendation to drop device-name and
   trailing-dot checks is therefore unsafe. Select one concrete policy, retain
   those checks even with a restricted alphabet, and run the same valid/invalid
   vectors at build, spec, runtime, docs and CI boundaries; a nonempty-only CI
   check is not equivalent validation.
2. **P2 - Keep the product output separate from PyInstaller work output.**
   The valid name `build` makes `DIST_DIR` equal the current `target/build`
   work-directory ancestor. PyInstaller's overlap guard rejects that output.
   A direct guard probe reproduced the failure without freezing anything.
   Use a disjoint work directory and cover this valid-name case.
3. **P2 - Preserve rename-sensitive executable examples in docs.**
   [Basics](../docs/basics.md#L72) invokes the literal executable inside a code
   fence. A hook that skips every fence leaves the command broken after a rename;
   making prose conversion optional also contradicts the task's one-field goal.
   Substitute explicit opt-in tokens in commands as well as prose, leaving
   ordinary examples, external URLs and asset IDs untouched.
4. **P2 - Carry the resolved product name across release jobs.**
   The [publish job](../.github/workflows/release.yml#L146) has no checkout and
   cannot read `base.json`. Export the validated build-time name as a job output
   alongside version/artifact identity and consume it when publishing the title.
5. **P2 - Make documentation validation prerequisites explicit.**
   `python build.py doc` currently fails strict validation because the screenshot
   referenced by [configuration docs](../docs/configuration.md#L155) is absent.
   The Pages workflow generates screenshots before building docs. Establish that
   prerequisite for the local gate instead of attributing the failure to a rename.

#### Reconciled Decisions

- User authorized implementation after this review and reaffirmed `app_name` as
  the sole product-name definition. Updated the live design above accordingly.
- Accepted the earlier review's focused-test approach, stable conda identity and
  explicit current-name no-op clarification. Kept device-name rejection and
  automatic current-docs prose renaming where its suggested reductions conflict
  with Windows behavior or the user's goal.
- Use one standard-library settings validator at every process boundary,
  preserve one cached runtime snapshot, and avoid importing the build command
  module from runtime or PyInstaller.
- Frozen settings-data assertions were already in the original Tests section;
  retain them and the explicit approval gate for a real isolated package smoke.
- User approved the isolated temporary-copy freeze/package/launch check with the
  existing Python environment. No environment changes or canonical settings
  edits are authorized or needed.
- User later excluded README files and similar repository prose; restored only
  this implementation's README/DEVELOPMENT changes and retained generated-docs
  substitutions. This explicit scope clarification supersedes earlier prose edits.

#### Review Validation

- Existing focused modules: **142 passed**. The screenshot argument-parser error
  text was an expected negative-test diagnostic; the test process exited zero.
  Exact command:

  ```powershell
  python -c "import build, subprocess, sys; modules=['fman_unittest.test_application_context','fman_unittest.test_portable','fman_unittest.test_generate_docs_screenshots','fman_unittest.test_find_files','fman_unittest.test_quick_view','fman_unittest.test_release_support','core.tests.commands.test___init__']; sys.exit(subprocess.run([sys.executable,'-X','faulthandler','-m','unittest',*modules,'-q'],env=build._environment(),timeout=180).returncode)"
  ```

- Proposed-regex probe: all five invalid examples in finding 1 were accepted;
  confirmed with `re.fullmatch` and Windows path/device checks.
- Called only PyInstaller's `_check_path_overlap` with temporary path strings and
  a patched configuration. Confirmed the `build` collision; no freeze or package
  command ran and canonical settings were not edited.
- `python build.py doc`: failed on the missing generated screenshot above.
- Native MainWindow baseline invocation was cancelled before a result; it is not
  counted as passed. No full suite, frozen rename or release publication ran.

## Implementer

### 2026_09_24 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented one validated product-name source in `base.json`, cached
  runtime settings, settings-derived build/spec/release/UI/screenshot/docs/report
  consumers, and sentinel regression coverage. Reconciled all review findings,
  preserved compatibility identifiers and the user's README exclusion. The real
  isolated renamed executable and ZIP were built, inspected and launched with
  the existing Python environment; canonical settings/output were not changed.

## Implementation Results

- [Shared settings](../src/main/python/fbs_runtime/build_settings.py) validates
  the full document's `app_name` using the selected 1-64 character ASCII policy
  and rejects Windows device names. Runtime uses its cached dictionary through
  both the existing context property and [private product module](../src/main/python/fman/impl/product.py).
  Build, spec, docs and CI reuse the same validator without importing build
  commands into runtime or spec evaluation.
- [build.py](../build.py) takes one snapshot for name/version, derives output
  paths and archive names, and uses `target/.pyinstaller` for collision-free
  work output. Removed the inert `freeze_dir` field. The neutral
  [application.spec](../application.spec) derives both `EXE` and `COLLECT` names
  and retains the bundled settings destination and console override.
- Runtime identity, main/prompt/message-box titles, profile filename, onboarding,
  usage guidance, shortcut guidance and Core product text/aliases now derive
  from the runtime name. The native probe exposed an empty Qt message-box title;
  an explicit product title and focused real-widget regression now cover it.
- [Release workflow](../.github/workflows/release.yml) obtains a validated name
  before environment setup and passes it as a build-job output to the publish
  job. Environment labels, version checks, artifact integrity and release
  publication protections are unchanged.
- [Screenshot tooling](../src/misc/generate_docs_screenshots.py) derives default
  executable and window discovery from settings. [MkDocs hook](../src/misc/docs_hooks.py)
  sets metadata and replaces only explicit `{{ app_name }}` tokens, including
  executable examples. [Local report](../src/misc/performance_report.py) derives
  visible headings without changing benchmark data or measurements.
- README, DEVELOPMENT and plug-in README files have no retained changes from
  this task, per user direction. Existing task documents received only necessary
  live-spec link repairs; their historical wording and signatures are preserved.

### Remaining Name Matches

The final source/tooling/docs search found only these classified occurrences:

- The authoritative `app_name` value in `src/build/settings/base.json`.
- External repository/Pages URLs and repository labels in About, its tests,
  MkDocs configuration and docs links.
- Legacy `ROYIFILEMANAGER_USER_SETTINGS` and `ROYIFILEMANAGER_BUILD_CONSOLE`
  APIs; existing conda environment labels; stable lowercase screenshot asset IDs.
- Stable benchmark suite/fixture identifiers; the independent Everything probe's
  instance label; static public-API docstrings and excluded repository prose.
  These do not provide runtime product naming or generated site metadata.
- Historical task text and release notes. Links to the renamed live spec were
  repaired; no active source/test consumer still uses the old spec path.

## Validation Results

### Focused Tests

- Final expanded aggregate in Tests above: **216 passed** in 4.837 seconds.
  This includes settings, build/spec/archive, Qt identity, real message-box
  title, onboarding/guidance, Core, portable API, docs hook, screenshot, release
  and lightweight performance-report tests. The screenshot parser's printed
  invalid-width message is an expected negative-test diagnostic, not a failure.
- After strengthening the console override assertion, **3 build-name tests
  passed** using:

  ```powershell
  python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.test_app_name.BuildNamingTest','-v'],env=build._environment(),timeout=60).returncode)"
  ```

- Native MainWindow command in Tests: **1 passed**. The initial review attempt
  was cancelled; this later implementation run completed successfully.
- Immediate gates after implementation groups passed: loader/context 10;
  build/spec 33; runtime identity/context 17; text consumers 117; screenshot,
  release and naming 32; docs and screenshot 23; report/guidance 58; explicit
  message-box title 1. No failed application gate remains outstanding.
- VS Code diagnostics: no errors in all changed Python, spec, workflow and
  MkDocs files. Required spec links resolve and the old spec is absent.

### Documentation and Native Source

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'src/misc/generate_docs_screenshots.py','--mode','source'],env=build._environment(),timeout=240).returncode)"
python build.py doc
```

Both passed. Source capture generated all 11 public-location images, including
the missing context-menu prerequisite. Strict docs also passed in the isolated
sentinel copy; parsed HTML confirmed the renamed homepage, executable example
and archive instructions, resolved tokens and unchanged repository URLs.

In the isolated copy, changing only `app_name` to `RfmRenameProbe` passed **129
focused tests** and a fresh native source smoke. The smoke asserted Qt
application/organization/domain values, main/prompt/About titles, the Core Zen
alias and stable About URLs, then reused the record-phase recent-command smoke
to check Core command execution, both panes, palette filtering, 83 hint widths,
portable history and clean shutdown.

During validation, a raw HTML substring check did not account for syntax-
highlighting spans, and a one-off smoke used an incorrect command class name.
Corrected the checks using parsed HTML and the verified `ZenOfFman` class. The
separate real message-box title finding was fixed in application code and
regression-tested before the native smoke passed.

### Approved Isolated Package

With explicit user approval, copied working source into a disposable directory,
excluding Git data, `UserSettings`, existing `target`/`site` and Python caches.
Only the copied `app_name` was changed. Used the existing interpreter and
committed conda lock; verified the existing bundled 7-Zip hash before running,
so the probe required no dependency download or environment change.

From that isolated root, executed:

```powershell
python -c "import build, os, subprocess, sys; assert build.APP_NAME == 'RfmRenameProbe'; assert build._sha256(build.SEVEN_ZIP_PATH) == build.SEVEN_ZIP_BINARY_SHA256, 'Existing bundled 7-Zip is required; do not download during this probe'; env=dict(os.environ, CI='true'); subprocess.run([sys.executable,'build.py','freeze'],env=env,check=True,timeout=900); subprocess.run([sys.executable,'build.py','package'],env=env,check=True,timeout=180)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'src/misc/generate_docs_screenshots.py','--mode','packaged','--output-dir','target/name-smoke','--timeout','45'],env=build._environment(),timeout=75).returncode)"
```

Passed actual `EXE`/`COLLECT` creation, ZIP generation and frozen launch/capture.
Inspected `RfmRenameProbe.exe`, its distribution directory,
`RfmRenameProbe-0.9.1-windows-x86_64.zip`, every archive member's root, the empty
portable `UserSettings` entry and exact bundled settings equality. Packaged
window discovery found the sentinel title and produced a nonblank 1280x800
capture. The renamed process exited; canonical `app_name` remains unchanged.

### Limits

No full test suite, live GitHub release publication, macOS/Linux run or heavy
performance workload was executed. Workflow behavior was validated structurally
and through the shared settings contract; no remote CI run is claimed. No new
Python environment/package, Registry operation, git staging or commit occurred.
Git was unavailable on PATH, so validation used source, diagnostics, tests and
real artifacts instead of Git diff/status. Generated screenshots/site/build
artifacts were produced by their tools, never hand-edited. The approved frozen
check used only the disposable copy, not the canonical build output.
