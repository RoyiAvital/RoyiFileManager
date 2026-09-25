# QuickView 003: Text-Based Files

## Task

Add plain text, Markdown and programming-language previews to the
viewport from [stage 001: initial design and images](../Done/QuickView001.md). Deliver
after [videos](QuickView002.md); all formats use the same inactive pane, toggle
and lifecycle.

Status: proposed design only; review and dependency approval precede implementation.

## Scope

- Read-only text/log/configuration files, Markdown rendered/source modes, and syntax
  highlighting for known programming languages. Selection, copy, scrolling, line
  numbers, wrap toggle and literal in-preview Find are included.
- Initial language map: Python, JavaScript/TypeScript/JSX/TSX, C/C++, C#, Java, Go,
  Rust, Ruby, PHP, Swift, Kotlin, shell/PowerShell/batch, SQL, HTML/CSS, JSON, YAML,
  TOML, XML/SVG, INI, diff, Makefile, CMake and Dockerfile. Unknown readable text uses
  plain text; support is not a promise of language-server semantics.
- Same shared local/UNC/symlink policy. Do not run programs, import the viewed Python
  module, load language servers, render HTML/SVG as web content, or write source files.
- Exclude editing, hex view, live log tail, whole-file indexing of huge files,
  Markdown scripts/HTML execution, Mermaid/math extensions and external resources.
- Preserve external Text Viewer/Editor commands and the public `fman` plug-in API.

## Design

### Dependencies

Hard prerequisite: the shared foundation in [stage 001](../Done/QuickView001.md).
Earlier stages are delivery and regression prerequisites; text does not import
the image decoder or libmpv, and must work when video dependencies are absent.

Use existing PyQt5 5.15 `QPlainTextEdit`, `QSyntaxHighlighter`, `QTextBrowser` and
`QTextDocument`. Native Markdown parsing exists since Qt 5.14. Add **Pygments**
(distribution/import `pygments`) for lexing; pin a Python 3.14-compatible release
in the [environment](../environment.yml)/lock only after user approval/installation.
Retain its BSD license notice and collect the explicit lexer modules for the
[portable build](../application.spec). No Markdown Python package, WebEngine,
Node, browser service, chardet or language server is required.

[Qt Markdown/resource documentation](https://doc.qt.io/archives/qt-5.15/qtextdocument.html)
and [Pygments API](https://pygments.org/docs/api/) are the reference APIs. Recheck Qt
bindings if the separate PyQt6 migration lands first. Missing Pygments degrades to
plain code with an inline highlighting-unavailable state; text/Markdown still work.
Do not probe/import Pygments until highlighting an eligible code file.

### Read, Decode and Limits

- The shared worker resolves/opens/stats the cursor file, never a directory scan.
  Read at most 2 MiB plus up to four bytes to finish an encoding boundary; do not
  mmap/read the entire file. Cap retained preview at 20,000 logical lines and 16,384
  Unicode code points per line. Mark byte/line truncation in chrome, and shortened
  lines in a non-copyable annotation; do not silently claim to show the full file.
- Detect BOMs in longest-first order: UTF-32, UTF-16, UTF-8. Otherwise use strict
  UTF-8. At a bounded prefix use incremental decoding so an incomplete terminal
  sequence is not misreported as corruption. Do not use Pygments' decoding guesses.
- On invalid UTF-8 show replacement characters with an explicit encoding warning,
  plus an encoding menu: UTF-8, UTF-16 LE/BE, UTF-32 LE/BE and Windows ANSI code page.
  Show the actual code-page name. An explicit choice rereads the bounded prefix;
  keep it per-file only, never change application locale or source bytes.
- Detect binary data after BOM-aware decoding: NUL characters or more than 1% C0
  controls other than tab/CR/LF/form-feed in the first 8 KiB-equivalent text sample
  reject automatic text preview. Signature checks reject known executables/archives
  even with text suffixes. UTF-16 BOMs must not be rejected for zero bytes alone.
- Plain-text fallback is considered only after media routing declines the file;
  a corrupt claimed image/video is not automatically dumped as text. Unknown suffixes
  can use this bounded text probe, including extensionless README/LICENSE files.
- Normalize line endings for display and record encoding/truncation metadata.
  Selection/copy copies displayed text only; it does not promise byte-perfect
  original line endings or omitted content. No hidden whole-file load on Select All.
- Worker results contain immutable strings/metadata and shared generation/fingerprint.
  All widgets, document layout and formatting objects stay on the Qt thread. Cancel
  between read chunks and reject stale/changed-file results; blocked OS reads retain
  the single shared slot under the common retirement policy.

### Plain Text and Code

Use read-only `QPlainTextEdit`, undo disabled, existing monospace font conventions,
line-number gutter for code, optional line numbers for plain text, and a wrap toggle
(default off). Preserve tabs, using a four-space visual tab width. No automatic
link activation or ANSI escape execution. Initial scroll is top-left on new files.

| Control | Preview-local behavior |
| --- | --- |
| Wheel/arrows/Page Up/Page Down | Scroll or normal read-only caret/selection movement; no source navigation. |
| Ctrl+Home / Ctrl+End | Start/end of the loaded prefix. |
| Ctrl+A / Ctrl+C | Select/copy displayed content, never mark/copy directory entries. |
| Ctrl+F / F3 / Shift+F3 | Literal find in loaded content, next/previous; case-sensitive toggle and wrap indicator. |
| Wrap / line-number controls | Explicit toggles; retain source position as far as layout permits. |
| Escape | Close a local find bar first, then shared return-to-source behavior. |
| Tab / QuickView toggle | Shared focus traversal and close behavior. |

Persist deliberate wrap/line-number/Markdown-mode preferences through shared config;
search query, encoding override, selection and scroll positions are transient.
Global external viewer/editor bindings keep their behavior in the source list, not
inside text selection. Local Find never invokes the file filter/search commands.

Choose lexers from an explicit built-in filename/extension map, with a bounded
shebang hint for extensionless scripts. Unknown/ambiguous cases use plain text or
a language menu from that same map. Do not import entry-point plugins, arbitrary
lexer files, or invoke content guessing over every known language.

Pygments lexing runs in one on-demand helper process, never a GUI-thread regex or
a Python thread that can hold the host GIL indefinitely. Reuse the reviewed private
worker dispatch/Job Object cleanup from stage 002, without importing its media
libraries. Input is already decoded plain text plus a trusted language ID. The
helper cannot load source-defined modules or execute the viewed file.

Highlight at most the first 256 KiB of UTF-8 display text / 5,000 lines. If any
eligible line exceeds 4,096 characters, show it unhighlighted and skip lexing the
file. Use `get_tokens_unprocessed()` to avoid stripping newlines/expanding tabs;
return coalesced per-block spans with token kinds, not HTML. Cap output at 50,000
spans and 2 MiB. Convert code-point offsets to Qt UTF-16 units, including astral
characters, before applying formats. Multiline lexing must precede per-block spans.

Plain text appears first. A two-second highlight deadline or output/lexer failure
leaves it readable without coloring; kill/reap the helper using the shared bounded
process policy. One helper plus one latest pending request at most, including
retirement. Switching cursor/renderer or closing cancels it; no retry loop. On Qt,
`QSyntaxHighlighter` applies cached spans, never lexes, and formats visible blocks
in bounded event-loop batches. Stale spans cannot color a replacement document.

### Markdown

Rendered/Source are modes of the same viewport, not separate panes. Default is
Rendered. Use Qt's GitHub Markdown dialect with `MarkdownNoHTML`; support Qt's
headings, emphasis, lists, blockquotes, tables and fenced code blocks. Fences are
monospaced in rendered mode; source highlighting follows the normal code path.
Do not promise browser/GitHub pixel parity or unsupported extensions.

Only render complete Markdown up to 128 KiB / 2,000 lines, with the same long-line
cap; larger or truncated documents fall back to Source with a size state. Parse/
layout on Qt only within these bounds; measure adversarial tables/nesting and
reduce the cap if responsiveness gates fail. A size limit is not a hard parser
timeout. No synchronous whole-document highlighting during Markdown layout.

Resource loading must be denied, not merely external-link opening. Override both
document/browser resource paths so all images, stylesheets and local/remote URLs
(including `file:`, UNC, `data:` and relative paths) return a safe placeholder or
empty resource without calling the base loader. No base URL to the source folder.
Disable automatic link navigation/external opening and drag/drop; permit copying
link addresses and same-document anchors only. Raw HTML is not rendered and HTML
files use escaped source text. Tests must spy on resource access, because returning
an invalid resource must not accidentally trigger a Qt fallback file read.

Switching Source/Rendered never rereads an unchanged file; retain an approximate
scroll fraction per mode for that cursor file. Clear documents/resource caches on
replacement, close and error. No local image loading dependency on stage 001.

## Alternatives

- Handwritten language regexes: fragile and costly to maintain; use Pygments' proven
  built-in lexers with explicit bounds and process isolation.
- Pygments in a worker thread: simpler but pathological regexes can retain the GIL
  and cannot be force-canceled safely. Pay helper cost only for code highlighting.
- WebEngine/Monaco: substantially larger distribution and script/network surface.
  Native Qt fits read-only previews and the existing theme.
- Python Markdown plus HTML sanitization: unnecessary extra parser when Qt already
  renders the required subset. Disable HTML and resource retrieval explicitly.
- Automatic legacy-encoding guessing/whole-file loading: ambiguous and costly.
  Bounded Unicode-first decoding with explicit overrides makes limitations visible.

## Runtime Effects

- Off/other renderer: no text reads, highlighter imports/helper, documents, timers
  or file watchers. Video DLL availability has no effect on this renderer.
- On: one bounded shared read and, for eligible code only, one bounded helper.
  Plain/Markdown requires no helper. Documents and token spans cost more than raw
  bytes; target host incremental working set below 64 MiB for the maximum text
  fixture and helper below 128 MiB, measuring before fixing release limits.
- Initial document insertion/Markdown parsing are bounded Qt work; target heartbeat
  gaps below 100 ms on recorded hardware. Formatting yields between visible-block
  batches; no recurring work after load except interaction/repaint.
- No background full-file reads, language servers, refresh polling or persistent
  content cache. Read-only input plus deliberate preference writes only. Teardown
  follows shared blocked-read retirement and bounded helper termination.

## Tests

Planned tests, not implemented or run during design:

- Unit: empty files, BOM order, UTF-8 boundaries, UTF-16/32, explicit ANSI override,
  malformed text, binary detection, unknown suffixes, huge files/lines, exact limits,
  line endings/tabs, safe filename language map, stale/changed/canceled requests.
- Highlight: representative fixture per shipped language, multiline strings/comments,
  astral-character UTF-16 positions, unknown lexer/dependency absent, span/output
  overflow, timeout/crash and no source execution or third-party lexer discovery.
- Native Qt: read-only/selection/copy/wrap/line numbers, Find focus and Escape/Tab,
  Source/Rendered switching, both source sides, source cursor unchanged, accurate
  truncation metadata, stale spans, close during read/lex and no hidden file actions.
- Markdown: headings/tables/fences, malformed/deep nesting, threshold fallback,
  raw HTML, scripts, `file:`/UNC/relative/HTTP/data resources and links. Assert zero
  external resource access or process launch; no automatic navigation from a link.
- Performance: 2 MiB text, 20,000 lines, huge single-line input, 128 KiB Markdown,
  pathological lexer fixture and 200 mixed-format switches. Record memory/latency;
  assert one helper maximum, forced cleanup and zero off-path work after retirement.

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_view', 'fman_unittest.test_quick_view_text', '-q'], env=build._environment(), timeout=120).returncode)"
$env:QT_QPA_PLATFORM = 'windows'
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.QuickViewIT', 'fman_integrationtest.test_qt.QuickViewImagesIT', 'fman_integrationtest.test_qt.QuickViewVideosIT', 'fman_integrationtest.test_qt.QuickViewTextIT', '-q'], env=build._environment(), timeout=180).returncode)"
```

Manual: `python build.py run` with disposable `ROYIFILEMANAGER_USER_SETTINGS`;
view text/code/Markdown, select/copy/find, change modes, browse mixed types, close
and restart. Inspect native Qt at 100%/150%/200% scaling and a narrow pane. Authorized
artifact smoke verifies every shipped lexer and helper dispatch without development
PYTHONPATH; no automatic freeze. Pygments absence is a fallback test, not a passing
release gate for promised syntax highlighting. Record any video-dependency skips.

## Implementation Steps

1. Review shared routing and this stage; approve/install/pin Pygments.
2. Implement bounded read/decode/binary/limit tests and immediately run the focused
   unit module before adding document rendering.
3. Add read-only plain text controls and native focus/copy/find tests.
4. Add isolated lexer spans and bounded highlighting; test timeout/Unicode cleanup.
5. Add safe Markdown rendering/mode switch; prove zero resource loading and measure
   layout budgets. Run shared and prior-renderer regressions.
6. Verify packaging collection when authorized; update README/CHANGELOG for delivered
   formats, limits and dependencies, recording validation before task completion.

## Acceptance Criteria

- Text, Markdown and listed language fixtures use the same inactive-pane viewport;
  image/video support and pane state restoration continue unchanged.
- Text is read-only/selectable; find/copy controls never act on directory entries.
- Decoding/truncation are explicit; large/binary/corrupt inputs stay responsive.
- Syntax uses bounded trusted lexers with correct Unicode spans, safe fallback and
  cleanup; a missing video runtime cannot prevent text preview.
- Markdown has no executable content or implicit file/network resource loads.
- No feature-specific work while off; shared stale-result/API gates and focused
  tests pass, and portable lexer/dependency checks are recorded before release.

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