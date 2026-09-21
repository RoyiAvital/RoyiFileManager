# Migrate to tinycss2

Replace the unmaintained `tinycss 0.4` CSS parser behind theme loading with
`tinycss2`, preserving application styling. Status: Completed. Source and
appearance checks passed; the user confirmed successful packaging and
application operation on 2026_09_21. Source of the request: the `tinycss` item
in [TODO.md](../TODO.md).

## Task

`tinycss 0.4` (2013) emits `SyntaxWarning: "\`" is an invalid escape sequence`
from `tinycss/token_data.py:291` whenever Python 3.14 compiles it (first import
after install, cleared `__pycache__`, or any `-W` run), and CPython documents
that such sequences become errors in a later release. The project uses it for one
purpose: parsing plug-in `Theme.css` files into `(selectors, declarations)` rules
in [src/main/python/fman/impl/util/css.py](../src/main/python/fman/impl/util/css.py),
consumed by [src/main/python/fman/impl/theme.py](../src/main/python/fman/impl/theme.py).
`tinycss2` is the maintained successor by the same organisation (CourtBouillon),
pure Python, on conda-forge, and implements the CSS Syntax Level 3 tokenizer.

Goal: no legacy `tinycss` runtime import, no new warnings and identical theme
output for every shipped and test theme. The user approved parser-specific
diagnostic reasons while preserving error formatting and source locations.

## Scope

Included:

- Rewrite `parse_css(bytes_)` in `fman/impl/util/css.py` on `tinycss2`; keep
  its signature and its `Rule` / `Declaration` return shape unchanged.
- Introduce `fman.impl.util.css.CSSParseError(ValueError)` carrying `line`,
  `column`, `reason`, and make `theme.py` catch it instead of
  `tinycss.parsing.ParseError`. The `ThemeError` format is unchanged; parser
  reason text may differ.
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
authors retain valid-theme behaviour and styling. Diagnostic reasons and clean
errors for unsupported at-rules follow the approved policy above. `tinycss` and
`tinycss2` were never part of the plug-in API surface.

## Design

### Current behaviour to preserve

`parse_css` today, via `tinycss.make_parser()` (CSS 2.1 parser):

| Aspect | tinycss 0.4 behaviour |
| --- | --- |
| Input | `bytes`; `@charset`, BOM and UTF-8 fallback decoding |
| Rules | Qualified rules only; each yields `Rule(selectors, declarations)` |
| Selectors | `rule.selector.as_css().split(', ')` – text split on comma-space |
| Declarations | `(name, value.as_css())`; leading/trailing whitespace stripped, inner whitespace kept, `!important` dropped from the value |
| Comments | Dropped |
| Errors | Any tokenizer/parser error (bad declaration, unknown at-rule, unbalanced block) collected in `stylesheet.errors`; `parse_css` raises the first as `ParseError(line, column, reason)` |
| Empty file | `[]` |

`theme.py` formats errors as `'CSS Parse error in file %s at line %d, column %d: %s'`
using `e.line`, `e.column`, `e.reason`.

### Implemented Design

- tinycss2 parses tokens, rules and declarations; source positions preserve
  original quoting, escapes and whitespace while removing CSS comments.
- The existing literal `split(', ')` selector behaviour remains unchanged.
- BOM/charset decoding and UTF-8 then Latin-1 fallback preserve legacy input.
- Nested token errors become `CSSParseError`; ordinary EOF recovery is retained.
- Theme handling changes only its parser-error import and handler.

### Original Proposal (Superseded)

The sketch below was revised during implementation: canonical serialization and
comma-token splitting changed observable theme behaviour. The implemented design
above governs the completed migration; this proposal is retained as history.

```python
import tinycss2
from tinycss2.ast import AtRule, Comment, ParseError, QualifiedRule, WhitespaceToken

class CSSParseError(ValueError):
	def __init__(self, line, column, reason):
		super().__init__('line %d, column %d: %s' % (line, column, reason))
		self.line, self.column, self.reason = line, column, reason

def parse_css(bytes_):
	rules, _encoding = tinycss2.parse_stylesheet_bytes(
		bytes_, skip_comments=True, skip_whitespace=True
	)
	result = []
	for node in rules:
		if isinstance(node, ParseError):
			raise CSSParseError(node.source_line, node.source_column, node.message)
		if isinstance(node, AtRule):
			raise CSSParseError(node.source_line, node.source_column,
				'unknown at-rule: @' + node.at_keyword)
		selectors = _split_selectors(node.prelude)
		declarations = []
		for item in tinycss2.parse_declaration_list(
			node.content, skip_comments=True, skip_whitespace=True
		):
			if isinstance(item, ParseError):
				raise CSSParseError(item.source_line, item.source_column, item.message)
			if isinstance(item, AtRule):
				raise CSSParseError(item.source_line, item.source_column,
					'unknown at-rule: @' + item.at_keyword)
			declarations.append(
				Declaration(item.lower_name, tinycss2.serialize(item.value).strip())
			)
		result.append(Rule(selectors, declarations))
	return result

def _split_selectors(prelude):
	groups, current = [], []
	for token in prelude:
		if token.type == 'literal' and token.value == ',':
			groups.append(current); current = []
		else:
			current.append(token)
	groups.append(current)
	return [tinycss2.serialize(group).strip() for group in groups]
```

Decisions inside the design:

- **Selector split on comma tokens, not on the text `', '`.** For every shipped
  and test theme (`.a, .b`) the result is identical. For `.a,.b` the old code
  produced one unmatched selector `'.a,.b'`; the new code produces two. This is
  the single intentional deviation, in the direction of the CSS specification,
  and it cannot break a theme that worked before. Strings containing commas
  (`font-family: "a, b"`) are values, not preludes, so they are unaffected.
- **Declaration name**: `item.lower_name` matches tinycss, which lower-cases
  property names. Value serialization via `tinycss2.serialize` round-trips
  tokens exactly (`1px solid #262626`, `0.25ex`, `"quoted, string"`).
- **Errors**: tinycss2 does not raise; it inserts `ParseError` nodes. Converting
  the first one to `CSSParseError` preserves fail-fast semantics and the
  line/column/reason triple (`source_line`/`source_column` are 1-based, as in
  tinycss). Rejecting at-rules mirrors the CSS 2.1 parser's "unknown at-rule"
  error for the at-rules the shipped themes never use.
- **Decoding**: `parse_stylesheet_bytes` honours BOM and `@charset` and falls
  back to UTF-8, the same contract as tinycss's `decoding.py`.
- **`theme.py`**: change one import and one `except` clause; nothing else.
- **No warnings filter, no vendoring, no fork of tinycss**: the root cause is
  removed rather than silenced.

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
mention `tinycss` and needed no change. The user updated the environment and
lock; the Windows lock lists tinycss2 1.5.1 and webencodings 0.5.1. Successful
packaged operation was confirmed by the user.

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
- **Serialize prelude and keep `split(', ')`**: byte-for-byte identical to
  today, including the `.a,.b` quirk. Considered; token splitting is simpler
  and correct, and the deviation is documented and tested.

## Runtime Effects

- Startup: `import tinycss` currently costs ~15 ms (`-X importtime`, warm) and,
  after a fresh install, one SyntaxWarning on stderr. `tinycss2` + `webencodings`
  are of similar size; measure both in Step 5 and record the numbers. Parsing the
  four shipped `Theme*.css` files is well under a millisecond either way.
- Steady state: none; themes are parsed once per plug-in load.
- Memory, I/O, threads, timers, cancellation: unchanged (none beyond the file
  read that exists today).
- Disabled/no-op path: not applicable; theme parsing is not optional.

## Tests

Extend `fman_integrationtest.impl.util.test_css` (pure Python, no Qt):

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
- Errors: missing colon, unbalanced `{`, unknown at-rule `@media`: each raises
  `CSSParseError` with the expected 1-based line and column and a non-empty
  `reason`; `isinstance(error, ValueError)` holds.
- Shipped themes: parse `Theme.css`, `Theme (Windows).css`, `Theme (Mac).css`,
  `Theme (Linux).css` and the test resource `Simple Plugin/Theme.css`; compare
  against a fixture generated once with the current tinycss implementation
  before it is removed (Step 1), so the migration is proven output-identical.
- Theme integration: `Theme(...).load(<Core Theme.css>)` produces the same QSS
  string and the same `get_quicksearch_item_css()` dict as the frozen fixture;
  a broken theme raises `ThemeError` with the existing message format.
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

Packaged validation: build and launch the artifact to confirm dependency
collection and theme loading. Completed by the user, who confirmed successful
packaging and application operation on 2026_09_21.

## Implementation Steps

1. **Freeze the baseline.** With tinycss still installed, add the shipped-theme
   and Theme-QSS fixture tests to `test_css.py` and generate their expected
   values from the current implementation. Run the module; it must pass.
2. **Dependency.** Edit `environment.yml` (`tinycss` → `tinycss2`); ask the user
   to install `tinycss2` into the environment and regenerate `conda-lock.yml`
   with `conda-lock lock -f environment.yml -p win-64`.
3. **Rewrite `parse_css`** and add `CSSParseError` in `css.py`; switch the import
   and `except` in `theme.py`. Run `test_css` immediately.
4. **Add the remaining tests** (selectors, declarations, encoding, errors,
   warning-free import) and run the three focused commands.
5. **Measure** import time of `tinycss2` vs the recorded `tinycss` baseline and
   record it under Validation Results.
6. **Docs.** CHANGELOG `Changed` entry; README dependency mention if it lists
   `tinycss` (it does not today); complete the task document and move it to
   `Done/`.

## Acceptance Criteria

- Production source no longer imports the legacy `tinycss` package.
- `python -W error::SyntaxWarning` can import `fman.impl.theme`.
- All four shipped themes and the test plug-in theme parse to output identical
  to the frozen tinycss fixture; the Core theme yields the identical QSS string
  and quicksearch item dict.
- Invalid themes raise `ThemeError` with the existing
  `'CSS Parse error in file %s at line %d, column %d: %s'` text and correct
  1-based positions.
- `environment.yml` declares tinycss2; the lock includes tinycss2 and its
  webencodings dependency, not tinycss.
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
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Marked complete based on the recorded implementation checks and the
  user's confirmation of successful packaging and application operation. The
  implemented design supersedes the original proposal; no gates remain open.

### 2026_09_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Confirmed the existing completion record, 36 passing focused tests
  and user-confirmed packaged operation. Verified the Plan and Done copies were
  byte-identical before removing the stale Plan copy. Retained this canonical
  completed record and its existing Completed index entry; no code changed.

## Implementer

### 2026_09_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented source-preserving tinycss2 parsing and Theme error
  handling, expanded regression tests, and updated dependencies and usage docs.
  Frozen appearance outputs and 36 focused tests passed. Dependency installation,
  lock update and successful packaging were performed by the user.

## Validation Results

- Six baseline CSS tests passed with tinycss before replacement, freezing parsed
  rules and generated styling for all shipped themes and the test plug-in.
- After migration, 17 CSS tests passed, including encoding, source spelling,
  nested errors, EOF recovery, ThemeError handling and warning-free fresh imports.
- The following focused command passed 36 tests with zero skips in the
  application environment:

```powershell
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-W', 'error::SyntaxWarning', '-m', 'unittest', 'fman_integrationtest.impl.util.test_css', 'fman_unittest.impl.test_theme', 'fman_integrationtest.impl.plugins.test_plugin', 'fman_integrationtest.test_qt.TextEditorIT', 'fman_integrationtest.test_qt.ComparatorIT', 'fman_integrationtest.test_qt.UniformRowHeightsIT', '-q'], env=env, timeout=120).returncode)"
```

- Native startup at 100/150/200 percent scaling matched the frozen Windows
  generated-style fingerprint and produced nonblank captures. Direct old/new
  pixel comparison was unavailable after removal of the legacy parser; identical
  parsed rules, QSS and quicksearch styling were verified instead.
- Import timing: median 9.195 ms across five fresh processes. Parsing all four
  shipped themes: median 0.459 ms per batch; no comparative speedup is claimed.
- On 2026_09_21 the user confirmed successful packaging and that the application
  works correctly. Packaged validation is complete, not deferred.
- Completion bookkeeping: move the canonical file to `Done/MigrateToTinycss2.md`
  and its index entry to Completed; validate with `git diff --check` and check
  that the old path is absent and the completed link resolves.

### Completion Bookkeeping Review (2026_09_22)

- Compared both copies with `Get-FileHash -Algorithm SHA256` before deletion;
  hashes matched. Removed only the duplicate under `Plan`.
- Checked the canonical `Done/MigrateToTinycss2.md` file, its sole Completed
  index link, and absence of the old path. Ran the scoped `git diff --check`.
- Documentation only: relied on the recorded runtime tests and the user's
  packaged validation above; no application tests, builds or benchmarks rerun.
