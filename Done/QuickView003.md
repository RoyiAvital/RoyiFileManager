# QuickView 003: Text-Based Files

## Task

Add read-only text, Markdown and source-code previews using one HTML pipeline
and one Qt widget in the existing QuickView viewport. Favor straightforward
implementation for ordinary files over editor features or strict latency targets.

Status: design and source implementation marked complete at the user's request
on 2026-09-26. Reviews are addressed and focused source validation has passed.
Portable smoke and locked-environment validation remain recorded release
follow-ups, not claims of completed verification or blockers to this closure.
The user selected this simpler direction and confirmed that the
Python packages are available. This replaces the separate text editor,
Qt-native Markdown and isolated lexer proposal retained in reviewer history.

## Scope

- Plain text/log files, rendered Markdown, and highlighted source/configuration
  files share selection, copy, scrolling and literal in-preview Find.
- Markdown has Rendered/Source modes. Source uses `setPlainText` in the same
  browser, not another editor widget. Plain text/code preserve line breaks and indentation.
- Support common built-in Pygments languages selected by filename/extension:
  Python, Julia, MATLAB, JavaScript/TypeScript, C/C++, C#, Java, Go, Rust,
  shell/PowerShell/batch, SQL, HTML/CSS, JSON, YAML, TOML, XML/SVG, INI and diff,
  plus Makefile, CMake and Dockerfile. The ambiguous `.m` suffix selects MATLAB.
  Unknown readable files remain plain text; no language guessing UI.
- Reuse the existing local/UNC/symlink policy, pane ownership and toggle. Keep
  image previews, external Text Viewer/Editor commands and public APIs unchanged.
- Exclude editing, line-number gutters, wrap controls, legacy-encoding menus,
  live logs, huge-file indexing, browser/GitHub fidelity, Mermaid/math, scripts,
  external resources and new persisted preferences. No performance-tuning project
  or exhaustive malformed-input/codec matrix is part of this stage.

## Design

### Shared Ownership

The only prerequisite is [QuickView001](../Done/QuickView001.md). This stage can
be delivered independently of [video playback](../Plan/QuickView002.md); it neither
imports multimedia nor expects helper-process infrastructure from that task.

Keep [QuickViewSession](../src/main/python/fman/impl/quick_view.py) responsible for
pane ownership, focus, the 100 ms debounce and generation/content-token checks.
Add one lazily created text view beside the existing image canvas in a stacked
content area. Switch controls with the content; do not build a renderer framework.

One new private module, `fman.impl.quick_view_text`, owns bounded text loading,
HTML conversion and the small QTextBrowser-based view. Extend the existing
[bounded loader](../src/main/python/fman/impl/quick_view_images.py) with minimal
request/result-kind dispatch while retaining one active job and one latest
pending request per window. Text does not create another worker lane.

Known text/code filenames route to the text reader. Unknown extensions can use
a bounded text probe after media identification declines the file; a recognized
but broken image/video remains a media error. Keep image size/codec checks
separate and unchanged. Videos need not exist for this dispatch to work.

Dispatch uses explicit image/text/unsupported/error result kinds, never message
matching. Known image suffixes and recognized image content retain image errors;
only unsupported content may reach text probing. Probe unknown files with at most
8 KiB before the 2 MiB read, rejecting decoded NUL or more than 1% C0 controls
other than tab, CR, LF and form-feed. Skip known binary suffixes including `.exe`,
`.dll`, `.zip`, `.7z`, `.iso`, `.msi`, `.pdf` and known video/audio containers.

### Packages And Conversion

The [environment](../environment.yml) already declares `markdown`, `pygments`
and `pymdown-extensions`. Use Python-Markdown and Pygments for the initial pipeline;
PyMdown is available but no extra extension is needed for basic previews.
Do not install packages or edit environment/lock files as part of this design.

| Input | HTML conversion |
| --- | --- |
| Plain text or Markdown Source | `setPlainText` in the same QTextBrowser; do not interpret Markdown punctuation. |
| Markdown Rendered | Python-Markdown with `fenced_code`, `tables` and `codehilite`. |
| Source/configuration code | Wrap in a fenced block with a trusted language identifier, then use that same Markdown converter. |

Create a fresh Markdown converter for each conversion; documents must not share
references or parser state. Configure `codehilite` with `noclasses=True`,
`guess_lang=False`, `linenums=False`, `pygments_style='monokai'` and
`nobackground=True`. Emit a single
in-memory HTML document with simple body/pre styling and matching foreground and
background. Use inline syntax colors, font weight and italics, not external CSS,
JavaScript or browser-dependent layout. No temporary HTML files are written.

Capture immutable foreground/background color strings from the themed preview
widget on Qt before submitting conversion. Workers never inspect palettes or
widgets. Match generated body and code backgrounds to those colors, using Monokai
token colors rather than the earlier light style. Plain fallbacks use the widget's
palette. Formatting is limited to complete inputs of at most 512 KiB; larger
inputs use `setPlainText` with a formatting-limit indicator before parser work.

Use a small explicit filename/extension-to-built-in-lexer map. Never infer a lexer
by importing or executing the viewed file. Unknown code-fence languages remain
uncolored; do not add application-specific lexer loaders. For generated source fences,
choose a backtick delimiter longer than any run in the source, with a minimum of
three, and surround the contents with newlines. This prevents source backticks
from terminating the block. Qt and Markdown may normalize tabs or final newlines;
copy is of displayed text, not a byte-preserving file operation.

Disable Python-Markdown's raw-HTML handlers (`html_block` and inline `html`) so
raw markup is displayed as text. Source HTML/XML/SVG always uses the code path,
never the document's markup path. Only enable the three named built-in extensions;
browser-oriented PyMdown features are outside the initial scope. If nested fences
later prove important, evaluate `pymdownx.superfences` separately rather than
combining overlapping fence/highlight extensions by default.

### Bounded Read And Lifecycle

- Resolve and stat only the selected regular file through the existing policy.
  Read at most a 2 MiB prefix. BOM-aware UTF-8/16/32 decoding uses the standard
  library; otherwise assume UTF-8. On invalid UTF-8, preserve it with a warning
  when valid non-ASCII text remains and replacement count is at most
  `max(3, decoded_character_count // 100)`. Count only decoding errors, not literal
  replacement characters already in the file. Otherwise retry once with the
  Windows ANSI code page and display its name; if that fails, use replacements
  and an encoding warning. This bounded heuristic preserves short ANSI files
  without valid UTF-8 Unicode; it is not definitive encoding detection. No menu.
- Use incremental decoding at the prefix boundary; normalize line endings.
  Reject NUL/control-heavy decoded samples as binary. This is a usability check,
  not a general file-type detector or hostile-file sandbox.
- Truncated input is shown with `setPlainText` and a truncation indicator;
  do not render partial Markdown or syntax-highlight an incomplete prefix. If
  generated HTML exceeds 8 MiB, use `setPlainText` with a formatting-limit indicator.
  The HTML check happens after conversion and is not a peak-memory guarantee.
- Read, decode and convert in the existing worker. Results contain only immutable
  source text, HTML and metadata, with generation and file fingerprint. Check
  cancellation between stages and reject changed-file or stale results. Qt widget
  creation, `setHtml`, document layout and clipboard actions stay on Qt.
- Markdown defaults to Rendered on selection. Source/Rendered conversion reuses
  the current bounded source through the same worker and advances the generation;
  switching modes does not reread the file or start a parallel conversion.
- On replacement/close, invalidate immediately, clear document/source references
  and retain the existing loader-retirement policy. A running Python parser or
  blocked OS read cannot be forcibly canceled; its stale output is discarded.
- Read errors show an inline error. Conversion/import failures fall back to
  plain text with a short warning. No retries, polling, preloading or content
  caches across files. Missing packages are a fallback, not a passing release gate.

### One HTML View

Use one read-only `QTextBrowser`/`QTextDocument`, undo disabled, for all text modes.
Use `WidgetWidth` wrapping for Rendered Markdown and `NoWrap` for plain/code/Source,
with preformatted monospace text and horizontal scrolling when necessary.
Set tab stops from four current-font spaces, matching Markdown's tab expansion.
Keep one consistent font/color scheme and
Qt-supported HTML; this is a document preview, not a browser or code editor.
Changing files or modes starts at the top; elaborate scroll restoration is deferred.

Selection, Ctrl+A, Ctrl+C and scrolling use the widget's normal behavior. Add a
small local Find bar using `QTextDocument.find`: Ctrl+F opens it, F3/Shift+F3 moves
through literal matches, with a case checkbox and wrap indication. These keys act
on the preview only while it has focus. Escape closes Find first, then returns to
the source pane; Tab and the shared QuickView toggle retain existing behavior.
Markdown alone shows Rendered/Source controls. Disable Rendered when the source
is truncated or exceeds 512 KiB, and re-enable it for eligible content. No
preferences are persisted.

While the browser or its Find controls have focus, local scrolling/selection,
Ctrl+Home/End, Ctrl+A/C, Ctrl+F, F3/Shift+F3, Escape and Tab take precedence over
user bindings. They never invoke pane Find, external View or Select All. Other
keys follow QuickView001's source-pane forwarding exactly once; no duplicate
dispatch or recursion. A user binding remains active in the source pane.

Override document/browser resource loading to return an empty resource without
calling base loaders. Block local, relative, UNC, HTTP and data resources; do not
set a source-directory base URL. Disable automatic link/external navigation and
drag/drop; text and link addresses remain copyable. No images, scripts, stylesheets
or external processes are fetched/launched by preview content. A focused resource
test must verify the override does not fall back to Qt file loading. This modest
boundary remains necessary even with relaxed performance/edge-case requirements.

## Alternatives

- Separate QPlainTextEdit, QSyntaxHighlighter and Qt-native Markdown: superseded
  by the user's unified HTML direction; duplicates presentation and formatting work.
- Isolated lexer helper, span protocol and incremental highlighting: removed.
  Strict cancellation/latency isolation is not required for this ordinary-use stage.
- Send plain text through Markdown directly: rejected because punctuation and
  whitespace would be interpreted rather than displayed literally.
- Escaped `<pre>` for every input: superseded by review; `setPlainText` keeps one
  widget while avoiding HTML parsing for plain/large/Source content.
- Send source directly to Pygments: viable, but fenced Markdown uses the same
  conversion/configuration as Markdown code blocks and matches the chosen pipeline.
- Enable PyMdown/SuperFences immediately: not needed for basic top-level fences
  and tables; retain as an available option, not a feature dependency.
- WebEngine or JavaScript highlighting: unnecessary runtime and browser complexity;
  QTextBrowser plus server-side HTML generation is sufficient.

## Runtime Effects

- Disabled/image-only: no text reads, parser imports, text document creation,
  extra worker, timer, helper process or recurring signal work. Imports may remain
  cached after first use; content and documents are released with the view.
- Active: one shared worker reads/converts the selected prefix. Plain text needs
  decoding and `setPlainText`; Markdown/Pygments imports occur only for formatting.
  Invalid unmarked UTF-8 uses additional bounded decoding passes to assess damage;
  valid input retains its single-decode path. No extra I/O or worker is added.
  Source, generated HTML and Qt's parsed document overlap in memory for one file;
  native document/layout memory can substantially exceed source size.
- Python parsing/highlighting can contend for the GIL; document layout can pause
  Qt. Input caps reduce ordinary workload, not worst-case execution time. Accept
  these limits instead of promising hard deadlines or process isolation.
- No numeric speed/memory acceptance gate or stress benchmark catalog is required.
  Check ordinary-file usability and one capped large file; preserve cancellation
  between stages, stale-result rejection and no new work while disabled.
- No settings, Registry writes, source writes or external-resource I/O. Existing
  PyInstaller hooks collect the enabled Markdown extensions and built-in lexers;
  the spec additionally collects Pygments distribution metadata, including notices.
  An authorized portable smoke must still verify the resulting artifact.

## Tests

Required checks; executed results and remaining gates are recorded below:

- Unit: literal text with Markdown/HTML punctuation, empty and Unicode files,
  BOM/ANSI decoding, binary suffixes and probe threshold, 8 KiB probe, 512 KiB
  formatting cap and 2 MiB read cap; plain fallback/warnings and typed dispatch.
- Conversion: heading/list/table/fenced Markdown, a short sample per enabled
  language, unknown fence language, embedded backtick runs and inline highlighting
  styles. Raw HTML remains literal; consecutive documents do not share state.
- Lifecycle/regression: one worker, stale result after cursor/mode change or close,
  unchanged-file reuse, no text work while off, and preserved image/error routing.
- Qt: all three inputs use the same widget; visible syntax colors, preformatted
  indentation, copy/Find/focus, Markdown mode switching, both panes and existing
  image controls. Spy on blocked resource loading and automatic link actions.
- Manual/smoke: ordinary text, Markdown and source plus a capped large file;
  check scrolling, narrow pane, Unicode and 100%/150% scaling. No fixed timing gate,
  exhaustive adversarial suite or long stress run. Portable smoke, when an artifact
  is authorized, verifies Markdown extensions and each promised lexer without the
  development environment. Do not build/freeze automatically.

Focused commands (`python` denotes the existing project interpreter):

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_view', 'fman_unittest.test_quick_view_text', '-q'], env=build._environment(), timeout=120).returncode)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_view_images', '-q'], env=build._environment(), timeout=120).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.QuickViewIT', 'fman_integrationtest.test_qt.QuickViewImagesIT', 'fman_integrationtest.test_qt.QuickViewTextIT', '-q'], env=env, timeout=180).returncode)"
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts')); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.QuickViewIT', 'fman_integrationtest.test_qt.QuickViewImagesIT', 'fman_integrationtest.test_qt.QuickViewTextIT', '-q'], env=env, timeout=180).returncode)"
```

Use the existing interpreter; no new environment or packages. If videos land
first, also run their implemented focused regressions; their absence is not a
blocker. For manual application smoke use `python build.py run` with disposable
`ROYIFILEMANAGER_USER_SETTINGS`. Verify [application.spec](../application.spec)
and [conda-lock.yml](../conda-lock.yml) through the existing release workflow at
implementation time; available imports do not establish portable collection.

## Implementation Steps

1. Review this simplified design and check sample generated HTML in the installed
   Qt widget. Confirm enabled extensions/lexer aliases without adding dependencies.
2. Add focused conversion/read tests and the small text module. Validate literal
   escaping, Markdown, highlighted source and fallback before integrating the view.
3. Extend the existing loader/session with text dispatch and the single browser;
   immediately run shared loading, stale-result and image regressions.
4. Add local Find, Markdown modes and blocked resource loading; validate native
   focus/copy/rendering and ordinary-file usability without performance machinery.
5. Document supported previews/limits in README and CHANGELOG and record source
  results. Retain authorized portable collection as a release follow-up under
  the user's completion decision below.

## Acceptance Criteria

- Plain text, Markdown and code render through one QTextBrowser; plain text stays
  literal and known code languages show syntax colors without JavaScript.
- Standard Markdown headings/lists/tables/fences work in Qt's supported HTML subset;
  source mode, selection/copy/Find and focus work without changing pane selections.
- Read/conversion limits and fallbacks are visible; ordinary samples are usable.
  No hard latency, parser cancellation, byte-perfect copy or browser-fidelity claim.
- No content-triggered external resources, source execution or file writes.
- Existing images, session ownership, shared bounded loading, stale-result rejection
  and the disabled no-work path remain intact. No video dependency or helper process.
- Focused source tests pass and unrun checks are recorded. The user accepted
  design completion on 2026-09-26 with portable and locked-environment checks
  retained as release follow-ups.

## Design Validation

On 2026-09-25, a disposable probe in the existing Python 3.14.7 environment
verified Markdown 3.10.3, Pygments 2.21.0 and PyMdown Extensions 12.0.1 imports,
with Qt 5.15.15 / PyQt 5.15.11. PyMdown was not needed for conversion.

Offscreen QTextBrowser checks passed: literal punctuation/indentation/Unicode,
Markdown headings/lists/tables, colored Python keywords in both Markdown and
generated source blocks, embedded backticks, unknown-language fallback, escaped
raw HTML and fresh-parser reference isolation. Widget grabs were non-null and
the keyword format was Pygments' expected green (`#008000`). Empty-resource
document/browser overrides intercepted local, relative and HTTPS image requests
without invoking base loaders. This is not a native visual or network-trace audit.

Reproducible core smoke command (`python` denotes the existing project interpreter):

```powershell
python -c "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; import html, markdown; from PyQt5.QtWidgets import QApplication, QTextBrowser; app=QApplication([]); browser=QTextBrowser(); parser=markdown.Markdown(extensions=['fenced_code','tables','codehilite'], extension_configs={'codehilite':{'noclasses':True,'guess_lang':False,'linenums':False,'pygments_style':'default'}}); fence=chr(96)*3; source='def example():\n    return 42'; browser.setHtml(parser.convert(fence+'python\n'+source+'\n'+fence)); assert source in browser.toPlainText(); assert browser.document().find('def').charFormat().foreground().color().name()=='#008000'; browser.setHtml('<pre>'+html.escape('# Literal <tag>')+'</pre>'); assert browser.toPlainText()=='# Literal <tag>'; print('Unified HTML smoke passed')"
```

The core smoke and design section/link/history checks passed, as did editor
diagnostics and `git diff --check -- Plan/QuickView003.md`. No application files,
dependencies, environment/lock files, changelog or benchmark records were changed.
Application lifecycle tests, native styling/focus, input-limit behavior and portable
package collection remain implementation checks, not completed design-probe results.

## Reviewers

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed bounded read-only text, safe native Markdown and isolated
  Pygments highlighting in the existing shared viewport. Dependency, Unicode,
  resource-access and responsiveness gates await review and implementation.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Feasibility review: bounded plain-text preview is the simplest useful
  candidate stage; the full plan is substantially larger because of isolated
  lexing, Unicode spans, Markdown resource denial and packaging. The helper-process
  reuse assumption is stale: QuickView002 now uses in-process Qt and no longer
  supplies that infrastructure. A later design revision must assign lexer-helper
  ownership independently. Plain text need not technically wait for video, but
  changing scope or delivery order requires approval. No dependency installation,
  production edits, scope changes or runtime tests performed.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revised per user direction to one Python-Markdown/Pygments HTML
  pipeline and QTextBrowser, with literal escaped plain text and fenced source.
  Packages are user-confirmed available; PyMdown remains optional. Removed the
  helper process, per-block highlighting, separate editor, strict performance
  gates and video prerequisite. Retained modest input/resource limits and shared
  lifecycle. Design only; historical reviewer records preserved.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: **Approve the unified HTML direction with changes.** Confirmed
  `markdown`, `pygments` and `pymdown-extensions` are declared in
  [environment.yml](../environment.yml). An in-memory probe confirmed that
  deregistering `html_block` and inline `html` escapes raw `<b>`, `<script>`
  and `<div>` as text. Probe timings (offscreen, no font directory, repeated
  `markdown/core.py` source) for 64 KiB / 512 KiB / 2 MiB: Markdown+codehilite
  60 / 204 / 811 ms (HTML 0.2 / 1.4 / 5.6 MiB), direct Pygments 24 / 190 /
  762 ms, `setHtml` of highlighted HTML 16 / 126 / 522 ms, `setHtml` of escaped
  `<pre>` 3 / 26 / 120 ms, `setPlainText` 1 / 10 / 51 ms. Requested changes:
  1. **Cap formatting below the read cap.** A 2 MiB source stays under the
     8 MiB HTML limit, so it pays about 0.8 s of worker time and about 0.5 s of
     Qt-thread `setHtml` per selection. Highlight/render only up to a smaller
     formatting cap (for example 512 KiB) and show larger files as plain text
     with an indicator. Use `setPlainText` in the same `QTextBrowser` for plain
     text, Markdown Source and truncated files; it keeps one widget and is 2-3x
     cheaper than parsing escaped `<pre>` HTML.
  2. **Match the dark theme.** The application theme is dark; Pygments'
     `default` style emits light inline backgrounds with `noclasses=True`.
     Choose a dark style (for example `monokai`, Sublime Text's default) and
     body colors from the theme.
  3. **Bound the unknown-file probe.** Specify a small probe (a few KiB) before
     any full read, and skip known binary extensions (`.exe`, `.dll`, `.zip`,
     `.7z`, `.iso`, `.msi`, `.pdf`), so cursor moves over large binaries or
     network files do not read 2 MiB prefixes.
  4. **List local keys and precedence.** Ctrl+F, F3 and Ctrl+A normally mean
     Find files, View file and Select all. State which keys the focused text
     view handles (scrolling, selection, Ctrl+A/C, Ctrl+F, F3/Shift+F3, Escape,
     Tab), that all other keys follow the QuickView001 routing, and how user
     bindings on those keys behave.
  5. **Run the Qt tests offscreen too.** `build.py test` and the release
     workflow use `QT_QPA_PLATFORM=offscreen`; CodeReview004 showed that a test
     validated only natively can fail there. Add the offscreen run to Tests.
  6. **Packaging.** Codehilite and `get_lexer_by_name` import lexers by name.
     Verify PyInstaller collects the mapped lexers, the chosen style and the
     three Markdown extensions (existing hooks may cover them), or add explicit
     hidden imports. Direct Pygments with statically imported lexer classes for
     source files is an equivalent alternative; the probe shows Markdown adds
     only about 6% over it.
  Optional: when UTF-8 decoding fails, retry once with the ANSI code page, as
  CodeReview003 item 22 does for JSON, so ordinary Windows text files do not
  show replacement characters. No application code changed.

### 2026_09_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Changes requested before implementation. The unified widget and
  conversion direction is viable, and the resource-denial contract is adequate
  when a `QTextBrowser.loadResource` override is tested without calling the base
  loader. Revise the active design to: cap Markdown/code formatting below the
  2 MiB read limit and use `setPlainText` for plain, Source, truncated and
  formatting-limited content; define typed dispatch outcomes so unsupported
  media can fall through to a bounded text probe while recognized broken media
  cannot; specify the probe byte limit, binary-extension exclusions and binary
  threshold; define local text-view keys and their precedence over user bindings,
  with every other key following QuickView001 routing exactly once; replace the
  light `default` Pygments style and state how immutable colors are captured on
  Qt before worker conversion; and add the required offscreen Qt gate beside
  native runs. Installed PyInstaller hooks currently collect Markdown extensions
  and Pygments lexers/styles, so explicit hidden imports are not presumed; the
  planned portable smoke remains the release gate. No application code changed.

### 2026_09_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Addressed both reviews before implementation: 512 KiB formatting cap,
  same-widget plain-text fallback, 8 KiB unknown-file probe and binary exclusions,
  typed routing, immutable theme colors with Monokai, explicit local-key precedence,
  and native plus offscreen gates. Accepted the optional ANSI retry with a visible
  encoding label. Existing PyInstaller hooks will be verified before adding any
  hidden imports; portable smoke remains an artifact-dependent release gate.

### 2026_09_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implementation review of `quick_view_text.py`, the loader dispatch,
  the QuickView session/overlay changes and the spec. **Approved for continued
  work**; release still waits on the recorded locked-environment and portable
  gates. All review requests are implemented: 512 KiB formatting cap,
  `setPlainText` for plain/Source/limited text, 8 KiB probe with binary-suffix
  exclusions, content-detected images still routed to the image loader, fresh
  parser per conversion with raw HTML deregistered, Monokai without background
  and theme colors captured on Qt, blocked resource loading, local keys with
  QuickView001 forwarding. Re-ran gates: unit 40 OK (offscreen), Qt 18 OK
  offscreen and 18 OK native. Probes: every mapped lexer alias resolves in the
  installed Pygments; the installed Markdown hook copies Markdown metadata (so
  short extension names resolve when frozen) and the Pygments hook collects
  lexers/styles. Findings, all small:
  1. **ANSI retry garbles mostly-UTF-8 text (reproduced).** `decode_text` switches
     the whole file to the ANSI code page after any strict UTF-8 error. A UTF-8
     `café résumé` text with one stray `0xFF` byte decoded as `cafÃ© rÃ©sumÃ©`
     labeled `Windows ANSI: cp1252`, instead of one replacement character.
     Retry ANSI only when UTF-8 decoding with `replace` yields more than a small
     number of replacements; otherwise keep UTF-8 with the existing warning.
  2. **Ineffective Rendered button.** For truncated or formatting-limited
     Markdown, Rendered stays enabled but always returns Source. Disable it in
     that case; the limit reason is already shown.
  3. **Tab width.** The document keeps Qt's default 80 px tab stop; set
     `tabStopDistance` to four or eight fixed-font spaces for code and plain text.
  4. Note: `.m` maps to MATLAB (Objective-C also uses it) and `.ts` to
     TypeScript; MPEG-TS video files reach the probe and show "Binary file".
     Acceptable; worth one line in the Core README.
  No application code changed.

### 2026_09_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Addressed all four Opus implementation-review points, including the
  extension-ambiguity remark. Accepted UTF-8 preservation with a refinement:
  require valid non-ASCII UTF-8 evidence so short legacy ANSI text still decodes.
  Input-limited Markdown disables Rendered, plain/source/code tabs use four spaces,
  and Core usage documents `.m`/`.ts`. Focused source gates pass; the existing
  locked-environment and portable release gates remain open.

### 2026_09_26 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Closed the design at the user's explicit request. Retained the passing
  source gates and all prior attribution records; unrun locked-environment and
  portable checks remain release follow-ups rather than closure blockers. The
  canonical task moves to Done and its index entry to Completed. No new QuickView
  application changes or runtime tests were needed for this documentation closure.

## Implementer

### 2026_09_26 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented bounded text loading/conversion and the single lazy
  QTextBrowser in the existing worker/session, with local Find, Markdown modes,
  immutable theme colors, resource denial and typed image/text/error dispatch.
  Added focused unit/Qt regressions, Pygments notices collection and usage/changelog
  updates. Source gates pass; portable and locked-environment gates remain open.

### 2026_09_26 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Added the missing `.jl` to `julia` lexer mapping after the user's
  report. A real-file regression failed for `.jl`/`.JL` before the change and
  passed afterward, verifying colored Julia keywords. The 16-test text/Qt gate
  passes; the installed packaging hook already collects the Julia lexer.
  Existing limits and outstanding portable gates are unchanged.

### 2026_09_26 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Routed `.m`/`.M` to MATLAB as requested. A real-file regression
  verifies the explicit lexer choice and colored keywords. All 17 focused
  text/Qt tests pass; the existing packaging hook includes the MATLAB lexer.
  No dependency or packaging changes; portable verification remains pending.

### 2026_09_26 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented the encoding, Rendered-button and tab-stop fixes, added
  focused decoding/Qt/dispatch regressions and documented the ambiguous suffixes.
  Final unit gate: 27 passed. QuickView Qt gate: 20 passed each offscreen and native
  at 100%/150%. No dependency, settings, packaging or public API changes.

## Validation Results

### Source Gates

On 2026-09-26 the existing Python 3.14.7 interpreter used Markdown 3.10.3,
Pygments 2.21.0 and PyMdown Extensions 12.0.1, with Qt 5.15.15 / PyQt 5.15.11.
The edited lockfile instead specifies Markdown 3.11 and PyMdown Extensions 12.1;
those versions were not installed or tested in this run. PyMdown is not used by
the application preview pipeline. Environment/lock changes were pre-existing.

Commands below use `python` for that existing interpreter; no new environment:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_view.QuickViewPackagingTest'], env=build._environment(), timeout=60).returncode)"
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.test_quick_view','fman_unittest.test_quick_view_images','fman_unittest.test_quick_view_text'],env=env,timeout=120).returncode)"
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); targets=['fman_integrationtest.test_qt.QuickViewIT','fman_integrationtest.test_qt.QuickViewImagesIT','fman_integrationtest.test_qt.QuickViewTextIT']; settings=({'QT_QPA_PLATFORM':'offscreen'},{'QT_QPA_PLATFORM':'windows','QT_SCALE_FACTOR':'1','QT_AUTO_SCREEN_SCALE_FACTOR':'0'},{'QT_QPA_PLATFORM':'windows','QT_SCALE_FACTOR':'1.5','QT_AUTO_SCREEN_SCALE_FACTOR':'0'}); sys.exit(max(subprocess.run([sys.executable,'-m','unittest',*targets],env=dict(env,**setting),timeout=180).returncode for setting in settings))"
python -c "import subprocess, sys, tempfile; output=tempfile.mkdtemp(prefix='quickview003-docs-'); print('Temporary documentation output:', output, flush=True); sys.exit(subprocess.run([sys.executable,'-m','mkdocs','build','--strict','--site-dir',output],timeout=120).returncode)"
```

- Packaging regression: 2 passed immediately after the spec edit.
- Final unit gate: 23 passed, no skips. The deliberately broken PNG fixture emits
  `libpng error: Read Error`; the test confirms a media error, not text fallback.
- Final Qt gate: 18 passed offscreen, 18 native at 100%, 18 native at 150%; no skips.
  Includes image regressions, Qt-thread delivery, both pane directions, same-widget
  mode changes without rereads, local keys/forwarding, blocked actual file resources,
  immediate clearing and stale conversion rejection after cursor changes.
- Native appearance probe: reused QuickViewTextIT/QtIT on the Qt thread with
  DevelopmentApplicationContext's real palettes and the base stylesheet. Rendered
  Markdown/table/fence, Python, literal text and a near-2-MiB plain fallback at
  DPR 1.0/1.5; checked non-null grabs, dark background pixels and visible keyword
  colors. Captures were temporary, not application assets. The first probe used
  the imported base context instead of the palette owner and failed before preview;
  the corrected probe passed at both scales.
- Native narrow-pane probe: exact Unicode/emoji plain-text roundtrip and Find
  with no-match status at target widths 477/358/279 logical pixels, DPR 1.0/1.5.
  Overlay size matched its target and visible text/Find/mode widgets remained
  contained. This used disposable QtIT windows, not saved user geometry.
- Executed installed PyInstaller Markdown/Pygments hooks: 20/326 hidden imports;
  verified all mapped lexer implementation modules, Monokai and the three enabled
  Markdown extensions. `copy_metadata('Pygments')` includes AUTHORS and LICENSE.
  This validates hook coverage and notices, not a built artifact.
- Editor diagnostics were clear for all changed Python modules/tests and the spec.
- Strict MkDocs build passed into a disposable output directory. Task sections,
  real task links, Pending index, Python syntax, unique test names and scoped
  tracked/new-file whitespace checks passed.

### Julia Highlighting Follow-Up

The missing filename mapping caused `.jl` files to bypass formatting. Added
`.jl` to the existing built-in lexer map; no lexer guessing, new dependency or
change to the 512 KiB formatting limit. Unknown files still use plain text.

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.test_quick_view_text.TextLoadingTest.test_julia_files_are_syntax_highlighted'],env=build._environment(),timeout=60).returncode)"
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.test_quick_view_text','fman_integrationtest.test_qt.QuickViewTextIT'],env=env,timeout=120).returncode)"
```

- New regression: reproduced plain `source` mode for both suffix cases before
  the mapping; passed afterward with `code` mode and a colored `function` keyword.
- Focused text/Qt gate: 16 passed, no skips. The corrupt-PNG fixture's libpng
  diagnostic remains expected.
- Executed the installed Pygments hook and checked that the module returned by
  `type(get_lexer_by_name('julia')).__module__`, `pygments.lexers.julia`, is in its
  `hiddenimports`. No frozen artifact was built or tested.

### MATLAB Highlighting Follow-Up

Added `.m` to `matlab`, including uppercase `.M`, without content guessing.
The new regression verifies the lexer selection, unchanged source and a colored
`function` keyword through the real file loader:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.test_quick_view_text.TextLoadingTest.test_matlab_files_are_syntax_highlighted'],env=build._environment(),timeout=60).returncode)"
```

The regression passed. Reran the exact text/Qt command in the Julia follow-up:
17 passed, no skips, with the same expected corrupt-PNG diagnostic. The installed
Pygments hook includes `pygments.lexers.matlab`, verified against the module of
`get_lexer_by_name('matlab')`. Editor diagnostics were clear. No frozen artifact
was built or tested; existing formatting limits and release gates are unchanged.

### Opus Implementation Review Follow-Up

All four points were addressed on 2026-09-26:

1. **ANSI retry:** preserve valid UTF-8 Unicode when newly introduced replacements
  are at most `max(3, decoded_character_count // 100)`. Unlike a count-only rule,
  requiring valid non-ASCII UTF-8 preserves the existing short-ANSI fallback.
  Regressions cover the reported accented text plus a stray byte, sparse/dense
  damage, literal replacement characters, a split trailing sequence and cp1252.
  This remains an explicitly bounded heuristic, not guaranteed encoding detection.
2. **Rendered button:** disable it for truncated or over-512-KiB Markdown using
  immutable content metadata, not warning-text matching. Tests verify disabled
  clicks emit no request, Source remains usable, and an eligible replacement
  file re-enables Rendered, including the exact formatting boundary.
3. **Tab width:** compute four-space stops from the current font after setting
  document content. Qt tests compare the property and actual cursor positions
  for plain text, Markdown Source, code Source and highlighted code at all gates.
4. **Extension remark:** Core README now states `.m` selects MATLAB rather than
  Objective-C and `.ts` selects TypeScript; binary MPEG-TS is rejected by the
  content probe. Existing dispatch tests now include both text and binary `.ts`.

Immediate focused checks passed: `TextConversionTest` (7 tests), the two new Qt
tests offscreen, and the extended dispatch test. Final commands (`python` is the
existing project interpreter):

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.test_quick_view','fman_unittest.test_quick_view_images','fman_unittest.test_quick_view_text'],env=env,timeout=120).returncode)"
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); targets=['fman_integrationtest.test_qt.QuickViewIT','fman_integrationtest.test_qt.QuickViewImagesIT','fman_integrationtest.test_qt.QuickViewTextIT']; settings=({'QT_QPA_PLATFORM':'offscreen'},{'QT_QPA_PLATFORM':'windows','QT_SCALE_FACTOR':'1','QT_AUTO_SCREEN_SCALE_FACTOR':'0'},{'QT_QPA_PLATFORM':'windows','QT_SCALE_FACTOR':'1.5','QT_AUTO_SCREEN_SCALE_FACTOR':'0'}); sys.exit(max(subprocess.run([sys.executable,'-m','unittest',*targets],env=dict(env,**setting),timeout=180).returncode for setting in settings))"
```

- Unit: 27 passed, no skips. The corrupt-PNG fixture's libpng diagnostic is expected.
- Qt: 20 passed offscreen, 20 native at 100%, and 20 native at 150%; no skips.
- Editor diagnostics were clear for changed code, tests and Core usage.
- No full suite, package/freeze, dependency installation or environment/lock edit.
  These are fixes to the existing Unreleased feature, so no separate changelog
  entry was added. The original review and implementation history are retained.

### Design Closure

On 2026-09-26 the user explicitly requested that this design be marked done.
The existing implementation, reviewer dispositions and validation results are
retained. Closure checks cover the canonical move, Completed index, relative
links and preservation of all prior reviewer/implementer records. Earlier
Pending statements in dated records describe the status at those times.

Closure validation passed: SHA-256 matched across the move, the Plan copy is
absent, the index has exactly one Completed entry, all 11 required sections and
task links resolve, and all 12 prior attribution records remain unchanged beside
the new closure record. The three incoming Stage 001 links were updated and
checked. Editor diagnostics reported no errors. Scoped tracked whitespace checks
and `git diff --no-index --check -- NUL Done/QuickView003.md` reported no
diagnostics. No runtime tests were rerun for this documentation-only closure.

### Remaining Release Checks

- Run the focused gates in the locked environment and perform the authorized
  portable smoke for Markdown extensions, promised lexers, styling and notices,
  without development Python paths. No new artifact was built in this task.
- No full suite, clean/freeze/package, dependency installation or benchmark catalog
  was run. Human physical-monitor/IME checks are not established by synthetic Qt
  events or screenshots. Existing image-specific release limitations are unchanged.
- These checks remain open for release verification. The user explicitly accepted
  design closure with them retained; no artifact build or dependency installation
  was performed as part of closing this task.