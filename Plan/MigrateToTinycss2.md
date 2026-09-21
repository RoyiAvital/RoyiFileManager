# Migrate to tinycss2

Replace the unmaintained `tinycss 0.4` CSS parser behind theme loading with
`tinycss2`, keeping the application's appearance exactly unchanged. Status:
Source migration implemented and validated; external lock verification and
packaged release validation remain open. Source of the request: the `tinycss`
item in [TODO.md](../TODO.md).

## Task

`tinycss 0.4` (2013) emits `SyntaxWarning: "\`" is an invalid escape sequence`
from `tinycss/token_data.py:291` whenever Python 3.14 compiles it (first import
after install or cleared `__pycache__`), and CPython documents
that such sequences become errors in a later release. The project uses it for one
purpose: parsing plug-in `Theme.css` files into `(selectors, declarations)` rules
in [src/main/python/fman/impl/util/css.py](../src/main/python/fman/impl/util/css.py),
consumed by [src/main/python/fman/impl/theme.py](../src/main/python/fman/impl/theme.py).
`tinycss2` is the maintained successor by the same organisation (CourtBouillon),
pure Python, on conda-forge, and implements the CSS Syntax Level 3 tokenizer.

Goal: no `tinycss` runtime import, no new warnings, and identical parsed theme
output, generated QSS and quicksearch styling for every shipped and test theme.
On 2026_09_21 the user approved parser-specific diagnostic reason text and clean
`ThemeError` reporting for unsupported at-rules. Keep the error formatting and
1-based source locations; exact application appearance is the acceptance gate.

## Scope

Included:

- Rewrite `parse_css(bytes_)` in `fman/impl/util/css.py` on `tinycss2`; keep
  its signature and its `Rule` / `Declaration` return shape unchanged.
- Introduce `fman.impl.util.css.CSSParseError(ValueError)` carrying `line`,
  `column`, `reason`, and make `theme.py` catch it instead of
  `tinycss.parsing.ParseError`. The `ThemeError` format is unchanged; reason text
  may differ under the approved diagnostic policy.
- Dependency swap in [environment.yml](../environment.yml): remove `tinycss`,
  add `tinycss2` (which pulls `webencodings`); regenerate `conda-lock.yml`.
- Regression tests in
  [src/integrationtest/python/fman_integrationtest/impl/util/test_css.py](../src/integrationtest/python/fman_integrationtest/impl/util/test_css.py)
  and a theme-level snapshot test; a warning-free import check.
- CHANGELOG entry (dependency change in the delivered product).

Excluded:

- Any change to `CSSEngine`, the CSS-to-QSS selector map, `Theme` public
  behaviour, the shipped `Theme*.css` files or the plug-in API for themes.
- Supporting new CSS features (at-rules, nesting, `!important` semantics,
  property validation). The current parser ignores or rejects them; keep that.
- Removing `tinycss` from any other place: there is none (`grep tinycss src/`
  finds only the two files above).

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. Plug-in
authors retain existing selector/value text and decoding behaviour. Diagnostic
wording and unsupported-at-rule errors may change; rendering must not.
`tinycss` and `tinycss2` were never part of the plug-in API surface.

## Design

### Current behaviour to preserve

`parse_css` today, via `tinycss.make_parser()` (CSS 2.1 parser):

| Aspect | tinycss 0.4 behaviour |
| --- | --- |
| Input | `bytes`; `@charset`, BOM, UTF-8 then ISO-8859-1 fallback decoding |
| Rules | Qualified rules only; each yields `Rule(selectors, declarations)` |
| Selectors | `rule.selector.as_css().split(', ')` – text split on comma-space |
| Declarations | `(name, value.as_css())`; leading/trailing whitespace stripped, inner whitespace kept, `!important` dropped from the value |
| Comments | Dropped |
| Errors | Collected parse errors raise through `ThemeError`; incomplete blocks can recover at EOF. Legacy accepted at-rule objects could cause `AttributeError` in the adapter. |
| Empty file | `[]` |

`theme.py` formats errors as `'CSS Parse error in file %s at line %d, column %d: %s'`
using `e.line`, `e.column`, `e.reason`.

### New implementation (`css.py`)

The original direct-serialization sketch is superseded by this reviewed design:

- Use tinycss2 for tokenization, rules and declarations, not a handwritten CSS
  grammar. Convert errors anywhere in selector/value/function/block token trees
  to `CSSParseError(line, column, reason)` before emitting theme output.
- Preserve original token text using token source positions, with CSS comments
  removed and only boundary whitespace tokens trimmed. This retains quote and
  escape spelling, inner whitespace and legacy comment concatenation; canonical
  `tinycss2.serialize` does not promise these properties.
- Keep the literal `split(', ')` selector behaviour. Exact matching in `Theme`
  and `CSSEngine` makes trimming or normalizing selectors a rendering change.
  Do not activate previously unmatched comma/spacing/quote variants.
- Preserve BOM/declared encodings and UTF-8 then Latin-1 fallback using Python
  codecs before passing text to tinycss2. Accept a valid leading `@charset`;
  tinycss2 decoding alone does not remove its at-rule node.
- Preserve property lowercasing, ignored `!important` and ordinary EOF block
  recovery. Reject unsupported at-rules through the approved diagnostic path.
- `theme.py` changes only its parser-error import and handler. No engine,
  selector map, theme asset, application layout or public API change.
- No warnings filter, vendored parser or new background work.

### Data flow, threading, persistence, failure

Unchanged. `Theme.load` runs on the Qt thread during plug-in loading, reads the
file bytes, calls `parse_css`, and either stores rules or raises `ThemeError`.
No persistence. A parse failure of one plug-in's theme is reported for that file
and does not affect other plug-ins, exactly as today.

### Dependencies

| Package | Before | After |
| --- | --- | --- |
| `tinycss` 0.4 (conda-forge noarch) | required | removed |
| `tinycss2` (conda-forge noarch, >=1.5,<2) | – | required |
| `webencodings` (dependency of tinycss2, noarch) | – | pulled automatically |

Both new packages are pure Python; PyInstaller collects them without hidden
imports or data hooks. [RoyiFileManager.spec](../RoyiFileManager.spec) does not
mention `tinycss` today and needs no source change; artifact collection remains
a release check. The application environment was updated by the user: tinycss2
1.5.1 and webencodings
0.5.1 are available under Python 3.14.7. The assistant installs no packages.

## Alternatives

- **Keep tinycss and silence the warning** (`warnings.filterwarnings` or a
  pre-compiled `__pycache__`): hides a deprecation that CPython will turn into a
  `SyntaxError`; unmaintained since 2016. Rejected.
- **Vendor a patched tinycss** (fix the escape in `token_data.py`): adds ~2k
  lines of third-party code to maintain for a 30-line use case. Rejected.
- **Hand-written mini parser** (regex on `selector { name: value; }`): no
  dependency at all, but string/comment/escape handling is exactly what CSS
  tokenizers get wrong; theme files are user-authored. Rejected in favour of a
  maintained tokenizer.
- **`cssutils`**: heavier, validation-oriented, DOM-style API; overkill.
- **Canonical serialization/token-based selector splitting**: rejected for this
  migration because normalizing quotes/whitespace can activate previously
  unmatched selectors. Preserve source token text and legacy splitting instead.

## Runtime Effects

- Startup: `import tinycss` currently costs ~15 ms (`-X importtime`, warm) and,
  after a fresh install, one SyntaxWarning on stderr. `tinycss2` + `webencodings`
  are of similar size; measure both in Step 5 and record the numbers. Parsing the
  shipped themes and any compatibility overhead must also be measured.
- Steady state: none; themes are parsed once per plug-in load.
- Memory: transient token/source-text maps proportional to stylesheet size,
  released after parsing. Returned rule data retains the existing shape.
- I/O, threads, timers, cancellation: no additional file reads, workers or timers.
- Disabled/no-op path: not applicable; theme parsing is not optional.

## Tests

Extend `fman_integrationtest.impl.util.test_css` (no QApplication required;
Theme colour checks use the existing QColor dependency):

- Existing `test_parse_css` fixture unchanged and passing.
- Selectors: `.a, .b`, `.a,.b`, `.a ,  .b`, attribute selector
  `.statusbar-pane[active="true"]`, `*`, descendant selector `th td`.
- Declarations: multiple per rule, missing trailing semicolon, extra inner
  whitespace preserved (`1px  solid`), `!important` stripped from the value,
  upper-case property name lower-cased, values with quoted strings containing
  `,` and `;`, `0.25ex`, hex colours, `white`.
- Comments between rules and inside blocks are dropped.
- Encoding: UTF-8 BOM, `@charset "utf-8";` prefix, non-ASCII characters inside
  a quoted value and a comment.
- Empty input and whitespace-only input → `[]`.
- Errors: missing colon, nested invalid tokens, bad strings/URLs and unsupported
  at-rules such as `@media`: each raises
  `CSSParseError` with the expected 1-based line and column and a non-empty
  `reason`; `isinstance(error, ValueError)` holds.
- Preserve ordinary missing-final-brace EOF recovery, original selector/value
  spelling, UTF-8/BOM/charset handling and undeclared Latin-1 input.
- Shipped themes: parse `Theme.css`, `Theme (Windows).css`, `Theme (Mac).css`,
  `Theme (Linux).css` and the test resource `Simple Plugin/Theme.css`; compare
  against a fixture generated once with the current tinycss implementation
  before it is removed (Step 1), so the migration is proven output-identical.
- Theme integration: `Theme(...).load(<Core Theme.css>)` produces the same QSS
  string and the same `get_quicksearch_item_css()` dict as the frozen fixture;
  a broken theme raises `ThemeError` with the existing message format.
- Exact fingerprints of parsed rules, generated QSS and quicksearch colours,
  fonts and metrics are captured from tinycss before replacement. Native Qt
  startup must match the frozen generated-style fingerprint and render at
  100/150/200 percent scaling. Direct old/new pixel comparison is an additional
  check only when a legacy runtime is still available; it was unavailable here.
- Warning check: `python -W error::SyntaxWarning -c "import fman.impl.util.css, fman.impl.theme"`
  exits 0.
- Existing Qt regressions that construct `Theme`: `fman_integrationtest.test_qt`
  cases at lines using `Theme(Mock(), [])` (TextEditorIT, ComparatorIT, etc.) and
  `fman_integrationtest.impl.plugins.test_plugin`.

Focused commands:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-W', 'error::SyntaxWarning', '-m', 'unittest', 'fman_integrationtest.impl.util.test_css', 'fman_integrationtest.impl.plugins.test_plugin', '-q'], env=build._environment(), timeout=120).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.TextEditorIT', 'fman_integrationtest.test_qt.ComparatorIT', '-q'], env=env, timeout=120).returncode)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-W', 'error::SyntaxWarning', '-c', 'import fman.impl.util.css, fman.impl.theme'], env=build._environment(), timeout=60).returncode)"
```

Release gate (not run automatically): `python build.py freeze` and launching the
artifact to confirm `tinycss2`/`webencodings` are collected and the theme loads.

## Implementation Steps

1. **Freeze the baseline.** With tinycss still installed, add the shipped-theme
   and Theme-QSS fixture tests to `test_css.py` and generate their expected
   values from the current implementation. Run the module; it must pass.
2. **Dependency.** Edit `environment.yml` (`tinycss` → `tinycss2`); the user
  installs dependencies and regenerates `conda-lock.yml` with
  `conda-lock lock -f environment.yml -p win-64`. Verify the regenerated lock
  matches the manifest before closing the task.
3. **Rewrite `parse_css`** and add `CSSParseError` in `css.py`; switch the import
   and `except` in `theme.py`. Run `test_css` immediately.
4. **Add the remaining tests** (selectors, declarations, encoding, errors,
   warning-free import) and run the three focused commands.
5. **Measure** import and parse time; record unavailable comparisons rather than
  infer a speedup from measurements made under different conditions.
6. **Docs.** CHANGELOG `Changed` entry; README dependency mention if it lists
   `tinycss` (it does not today); complete the task document and move it to
   `Done/`.

## Acceptance Criteria

- Production source contains no `tinycss` import. The fresh-process import test
  confirms it is absent from `sys.modules`.
- `python -W error::SyntaxWarning` can import `fman.impl.theme`.
- All four shipped themes and the test plug-in theme parse to output identical
  to the frozen tinycss fixture; the Core theme yields the identical QSS string
  and quicksearch item dict.
- Invalid themes raise `ThemeError` with the existing
  `'CSS Parse error in file %s at line %d, column %d: %s'` text and correct
  1-based positions.
- `environment.yml` declares `tinycss2>=1.5,<2`; the verified lock contains
  tinycss2 and its webencodings dependency, not tinycss.
- Focused commands pass; no other module changes.

## Reviewers

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Initial design. Verified the motivation on this machine (Python
  3.14.7 emits the SyntaxWarning from `tinycss/token_data.py:291` on compile)
  and the footprint (two files, one call site, one existing test). Chose a
  direct `tinycss2` rewrite of `parse_css` with a local `CSSParseError`
  preserving the `line`/`column`/`reason` contract used by `theme.py`; the
  only intentional behaviour change is splitting selectors on comma tokens.
  Baseline fixture generation before removing tinycss makes the migration
  provably output-identical for all shipped themes. `tinycss2` is not yet
  installed; installation and lock regeneration are user steps.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Original sketch required changes for charset handling, nested token
  errors, canonical serialization and byte decoding. User approved changed
  diagnostic reasons and clean unsupported-at-rule errors, but requires exact
  application appearance. Revised design preserves source text and legacy
  selector splitting. Six baseline tests pass before migration, including all
  five shipped/test rule fingerprints and five generated-theme combinations.
  Implementation may proceed against these appearance and compatibility gates.

## Implementer

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented the source-preserving tinycss2 adapter, local parse-error
  type and Theme handler, expanded the existing CSS tests, and updated the
  dependency declaration, README and changelog. All frozen appearance outputs
  and 36 focused tests pass; native startup matches the pre-migration styling
  at three DPI scales. Dependency installation/removal and the subsequent lock
  update were external to this implementation. Task remains pending lock/release
  validation; no full suite, package installation or build was performed.

## Validation Results

### Source and Appearance

- Before replacement: six CSS tests passed against tinycss 0.4, freezing five
  parsed-rule fingerprints and five QSS/quicksearch combinations (Core base,
  Windows, Mac, Linux and the test plug-in). The test plug-in CSS is empty;
  that combination intentionally equals the base theme.
- After replacement: 17 CSS tests pass, including charset/BOM/wide encodings,
  Latin-1 fallback, source quoting/escapes/CRLF/comments, EOF recovery, nested
  errors, ThemeError state preservation and an uncached warning-free import.
  Every frozen parsed-rule and generated-style fingerprint is unchanged.
- Final native Windows gate: **36 tests passed**, 1.573 s, zero skips. From the
  repository root with the application environment activated:

```powershell
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-W', 'error::SyntaxWarning', '-m', 'unittest', 'fman_integrationtest.impl.util.test_css', 'fman_unittest.impl.test_theme', 'fman_integrationtest.impl.plugins.test_plugin', 'fman_integrationtest.test_qt.TextEditorIT', 'fman_integrationtest.test_qt.ComparatorIT', 'fman_integrationtest.test_qt.UniformRowHeightsIT', '-q'], env=env, timeout=120).returncode)"
```

- Native source smoke: three fresh processes with disposable UserSettings,
  a fixed four-entry temporary folder and `QT_SCALE_FACTOR=1`, `1.5`, `2`.
  Waited for both panes to load all rows, reloaded their two Core themes,
  checked the actual application's generated CSS/quicksearch fingerprint
  against the frozen Windows baseline, and captured the complete window.
  All three passed; nonblank captures were 1280x800, 1920x1200 and 2560x1600.
  Inspected the 100/200 percent captures. Windows emitted a screen-geometry
  constraint warning at 200 percent; the complete widget capture succeeded.
- Captures are ignored diagnostics under
  `target/diagnostics/theme-migration/tinycss2-{1,1.5,2}.png`, not shipped assets.
  The legacy parser had been removed before pixel A/B could run; no legacy
  package was reinstalled. Exact style-data equality was verified, but direct
  old/new pixel equality is **not claimed**.
- Editor diagnostics passed for the edited source, tests and manifest/docs.
  Documentation sections/links and scoped `git diff --check` passed.

### Timing

Application Python 3.14.7, tinycss2 1.5.1, OS caches not flushed:

- Five fresh-process imports: median **9.195 ms**, range 8.938-10.202 ms.
- Five batches of 100 parses of all four shipped Core themes: median
  **0.459 ms per four-theme batch**, range 0.458-0.479 ms.
- Files were read before parse timing. The removed legacy parser could not be
  remeasured; these results do not establish a comparative speedup.

### Remaining Gates

- Lock generation via `python -m conda_lock` failed because repository
  `build.py` shadowed conda-lock's external `build` dependency. The installed
  `conda-lock` console-entry-point retry was skipped by the user. A subsequent
  external lock update now lists tinycss2 1.5.1; the requested detailed diff
  inspection was also skipped. Do not overwrite that update. Lock/manifest
  consistency and dependency collection still need verification before closing
  the task; no regeneration success is attributed to this agent.
- Frozen artifact collection/theme startup remain an explicit release gate.
  No `build.py clean`, full test suite, freeze or package command was run.
- The canonical task remains under `Plan/`; its Pending index entry is retained.
