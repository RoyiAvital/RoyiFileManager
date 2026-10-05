# UI Design 001: Application Theme

## Task

Consider the PDF QuickView mockup's visual treatment as a future application
theme: compact dark surfaces, restrained selection color, readable file rows and
small, consistent controls. This is a suggestion, not an approved global redesign.

## Scope

- Review the application frame, location bars, file columns/rows, selection,
  splitters, status bars and QuickView chrome shown in the reference.
- Preserve native Qt widgets, keyboard workflows, public plug-in APIs and
  Windows accessibility/high-DPI behavior.
- Exclude changes to file operations, pane architecture, PDF rendering and the
  document's own colors. PDF support remains [QuickView004](QuickView004.md).
- No browser, web runtime, new font or icon package is proposed for the application.

## Design

### Reproducible Reference

The [Mockup Source](#mockup-source) below contains the complete HTML, CSS, sample
report and initialization code: the selected PDF on the left, continuous pages
on the right, and Fit Width/page/zoom controls below. This Markdown file is the
only source artifact. Its code block preserves the page but does not render it
inside Markdown preview. The page is a visual reference, not an interactive file
manager or PDF renderer. No development server is needed.

Run this PowerShell block from the repository root to generate a uniquely named
temporary HTML preview and open it in the default browser. Edit the embedded
source, not the generated file; rerun the block after changes.

```powershell
$markdown = Get-Content -LiteralPath 'Plan/UIDesign001.md' -Raw
$blocks = [regex]::Matches($markdown, '(?ms)^```html\r?\n(?<html>.*?)^```\r?$')
if ($blocks.Count -ne 1) { throw 'Expected exactly one HTML source block.' }
$preview = Join-Path $env:TEMP ('UIDesign001-' + [guid]::NewGuid().ToString('N') + '.html')
[IO.File]::WriteAllText($preview, $blocks[0].Groups['html'].Value, [Text.UTF8Encoding]::new($false))
Start-Process -FilePath $preview
```

The generated file can be deleted after viewing. No generated HTML needs to be
kept in the repository.

Reference viewport: 1360 x 900 CSS pixels. It starts at a 290-pixel scroll offset
in the PDF area. Icons use pinned Lucide 0.468.0 from unpkg and therefore need
Internet access; text/layout remain available if that request fails. This is a
mockup-only dependency, not a proposed application dependency.

### Suggested Visual Direction

- Neutral surfaces: frame `#292929`, panes `#383838`, location bars `#414141`,
  preview surround `#262626`. Avoid decorative cards and large corner radii.
- Restrained blue-gray selection `#526878`, with a visible boundary `#768997`.
- Main text `#dedede`; secondary metadata stays quieter without obscuring focus
  or selection. Validate contrast rather than copying every swatch blindly.
- Compact 29-pixel reference file rows, aligned sizes/dates and 28-pixel tool
  buttons. Treat these as visual proportions, not hard-coded physical pixels.
- Clear folder/document icons, understated separators and persistent keyboard
  focus indicators. Qt/system window chrome remains platform-owned.
- The mockup uses Segoe UI for chrome and Georgia inside its sample document.
  Evaluate application typography separately from document content and preserve
  font substitution. Do not bundle these fonts.

Any implementation should map reviewed colors/spacing onto the existing theme
and Qt styling abstractions, not embed the HTML. Widgets and painting stay on the
Qt thread. Reuse current settings ownership if theme selection is later approved;
this proposal introduces no settings, migration or Registry access. Invalid theme
values must fall back to the existing usable appearance.

## Alternatives

- Retain the current theme unchanged: lowest regression risk; the reference can
  still guide QuickView control spacing.
- Introduce a selectable theme: preserves user choice but adds persistence and
  maintenance. Decide this explicitly before implementation.
- Replace the interface with web content: rejected; the mockup is a visual
  specification, not a new UI framework or dependency proposal.

## Runtime Effects

The proposal and embedded HTML have no application startup, CPU, memory, I/O,
thread or timer cost. The explicit preview command writes one temporary file and
opens the browser. The browser reference performs one icon-library fetch at load
and has no polling or file-system access. A native theme should change paint/style
data only, with no background work or additional processes. Cancellation is not
applicable to static styling. Keeping the existing theme must be a no-op path.

## Tests

- Reference: run the PowerShell block above, open the generated page at 1360 x
  900, and verify the selected file, page boundary, toolbar and report match the
  supplied mockup; inspect for clipped controls.
- Check 1280 x 800 and a narrowed pane; verify wrapping and text containment.
- Before native implementation, review contrast, focus, selected/inactive states,
  high contrast, font substitution and Windows 100%/150%/200% scaling.
- Native implementation must add focused Qt tests for any changed widget/style
  behavior and run the existing pane/QuickView focus and keyboard regressions.
  Exact module commands are selected when that implementation scope is approved.

## Implementation Steps

1. Preserve the HTML reference and review the suggested visual direction.
2. Decide scope, default versus selectable theme, and accessibility requirements.
3. Map approved tokens onto existing theme abstractions; change one surface at
   a time and validate its Qt regressions.
4. Verify normal/narrow/high-DPI states before documenting an implemented theme.

## Acceptance Criteria

- The reference page recreates the supplied layout without an application build.
- The complete page source and generation command live in this Markdown file;
  no separate HTML source artifact is required.
- No application-wide visual change occurs merely by adding this proposal.
- A future implementation has explicit approval and preserves native behavior,
  readable states, keyboard focus and plug-in compatibility.
- Theming work remains independent of PDF feature delivery.

## Reviewers

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Recorded the user's requested theme suggestion and reproducible HTML
  reference. Global theme adoption remains a separate decision from PDF support.

### 2026_10_05 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: 272K
- Outcome: Consolidated the complete mockup source into this plan with an
  on-demand temporary-preview command, as explicitly approved by the user.
  No application, PDF implementation or visual-design changes are included.

## Validation Results

- Opened the saved HTML directly using Playwright at 1360 x 900. Verified the
  selected report, three document pages, 25 rendered icons, initial scroll offset
  290 and a toolbar within its available width.
- At 1280 x 800 the toolbar remained within bounds and all icons rendered.
  Restored the browser to the reference viewport afterward.
- Required task sections, local links, Pending index entry and editor diagnostics
  passed. This remains a proposal; no application theme has been implemented.
- Consolidation: ran the extraction/generation portion of the PowerShell block
  under Reproducible Reference. The generated HTML matches the original SHA256
  after normalizing line endings and the final newline required by the code
  fence. The standalone source file is removed. Document links and fences pass.
- A new visual check of the temporary output was blocked by the integrated
  browser's trusted-folder restriction. Earlier visual results above remain
  applicable to the unchanged source; no new browser-rendering pass is claimed.

## Mockup Source

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QuickView PDF mockup</title>
<style>
* { box-sizing: border-box; }
html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; }
body { background: #353535; color: #dedede; font: 13px 'Segoe UI', sans-serif; letter-spacing: 0; }
button, input { font: inherit; color: inherit; }
button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; height: 28px; border: 1px solid #595959; border-radius: 2px; background: #424242; padding: 0 8px; }
button svg { width: 16px; height: 16px; stroke-width: 1.7; }
button.icon { width: 28px; padding: 0; }
button.quiet { background: none; border-color: transparent; }
.titlebar { height: 32px; background: #292929; display: flex; align-items: center; padding: 0 12px; gap: 9px; font-size: 12px; }
.app-icon { width: 17px; height: 17px; color: #d4b765; }
.window-actions { margin-left: auto; display: flex; gap: 29px; color: #ddd; }
.window-actions svg { width: 12px; height: 12px; }
.workspace { height: calc(100% - 58px); display: grid; grid-template-columns: 1fr 6px 1fr; }
.divider { background: #282828; border-left: 1px solid #555; border-right: 1px solid #555; }
.pane { min-width: 0; position: relative; overflow: hidden; background: #383838; }
.location { height: 36px; background: #414141; border-bottom: 1px solid #262626; display: flex; align-items: center; padding: 0 11px; gap: 8px; font-weight: 600; }
.location svg { height: 16px; width: 16px; color: #bbb; }
.chevron { color: #999; padding: 0 3px; }
.columns, .row { display: grid; grid-template-columns: minmax(170px, 1fr) 88px 152px; align-items: center; padding: 0 12px; column-gap: 10px; }
.columns { height: 27px; color: #c2c2c2; font-size: 11px; background: #323232; border-bottom: 1px solid #242424; }
.columns .sort { display: inline-flex; align-items: center; gap: 6px; }
.columns svg { width: 10px; height: 10px; }
.row { height: 29px; font-size: 13px; }
.row .filename { display: flex; align-items: center; gap: 8px; min-width: 0; white-space: nowrap; }
.row svg { height: 16px; width: 16px; flex-shrink: 0; stroke-width: 1.5; color: #b5bec6; }
.row.folder svg { color: #d9b966; fill: #c8a65333; }
.row.pdf svg { color: #dd8b80; }
.row.selected { background: #526878; outline: 1px solid #768997; outline-offset: -1px; color: white; }
.size { text-align: right; }
.date { text-align: right; color: #b8b8b8; }
.selected .date { color: #ebebeb; }
.pane-status { position: absolute; bottom: 0; height: 24px; display: flex; align-items: center; background: #484848; border-top: 1px solid #292929; width: 100%; font-size: 11px; padding: 0 10px; }
.pane-status .right, .global-status .right { margin-left: auto; }
.preview { padding: 6px; display: flex; flex-direction: column; gap: 4px; background: #383838; }
.preview-title { height: 28px; flex-shrink: 0; display: flex; align-items: center; padding-left: 2px; gap: 7px; }
.preview-title > svg { width: 16px; height: 16px; color: #de8b82; }
.preview-title .filename { flex: 1; }
.canvas { flex: 1; min-height: 0; overflow: auto; background: #262626; border: 1px solid #1f1f1f; scrollbar-color: #777 #303030; scrollbar-width: auto; }
.canvas::-webkit-scrollbar { width: 14px; }
.canvas::-webkit-scrollbar-track { background: #303030; }
.canvas::-webkit-scrollbar-thumb { background: #737373; border: 3px solid #303030; }
.pages { padding: 18px 28px; display: flex; flex-direction: column; gap: 18px; align-items: center; }
.sheet { width: 100%; aspect-ratio: 210/297; flex-shrink: 0; position: relative; background: #fff; color: #253237; padding: 38px 43px 40px; font-family: Georgia, serif; box-shadow: 0 1px 4px #0008; overflow: hidden; }
.sheet-head { font: 10px 'Segoe UI', sans-serif; display: flex; justify-content: space-between; color: #6c7b7e; letter-spacing: 0; padding-bottom: 13px; border-bottom: 2px solid #226659; }
.sheet h1 { font-size: 30px; line-height: 1.18; font-weight: normal; margin: 28px 0 12px; letter-spacing: 0; }
.sheet .subtitle { font: 11px 'Segoe UI', sans-serif; color: #657575; margin-bottom: 28px; }
.sheet h2 { font: 600 15px 'Segoe UI', sans-serif; color: #235d51; margin: 26px 0 10px; }
.sheet p { font-size: 12px; line-height: 1.65; margin: 0 0 12px; }
.report-table { width: 100%; border-collapse: collapse; font: 11px 'Segoe UI', sans-serif; margin-top: 15px; }
.report-table th { text-align: left; background: #edf3f1; color: #275b50; border-top: 1px solid #afc8bf; padding: 9px 10px; font-weight: 600; }
.report-table td { padding: 10px; border-bottom: 1px solid #e1e7e4; }
.report-table td:not(:first-child), .report-table th:not(:first-child) { text-align: right; }
.chart { font: 10px 'Segoe UI', sans-serif; margin: 20px 0 24px; }
.chart-row { display: grid; grid-template-columns: 65px 1fr 36px; gap: 10px; align-items: center; margin: 11px 0; }
.bar-track { height: 13px; background: #eef1f0; }
.bar { height: 100%; background: #30786a; }
.chart-row:nth-child(2) .bar { background: #67998b; }
.chart-row:nth-child(3) .bar { background: #a4b9ad; }
.footnote { font: 10px 'Segoe UI', sans-serif !important; color: #77817b; }
.sheet-foot { position: absolute; bottom: 25px; left: 43px; right: 43px; border-top: 1px solid #d6ddda; padding-top: 10px; display: flex; justify-content: space-between; color: #7d8884; font: 9px 'Segoe UI', sans-serif; }
.toolbar { min-height: 32px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding-top: 2px; flex-shrink: 0; }
.toolbar .separator { height: 21px; width: 1px; background: #5c5c5c; margin: 0 5px; }
.page-number { width: 38px; height: 26px; text-align: center; background: #252525; border: 1px solid #777; border-radius: 2px; outline: none; }
.page-total { min-width: 26px; margin: 0 4px; color: #c8c8c8; font-size: 12px; }
.toolbar .active { background: #5c6d78; border-color: #9cabb5; color: white; }
.zoom-label { min-width: 39px; text-align: center; font-size: 12px; color: #dedede; }
.format { font-size: 11px; color: #aaa; margin-left: auto; padding-right: 4px; white-space: nowrap; }
.global-status { height: 26px; background: #303030; border-top: 1px solid #222; display: flex; align-items: center; padding: 0 10px; font-size: 11px; color: #aaa; }
</style>
</head>
<body>
<div class="titlebar"><i data-lucide="panels-left-bottom" class="app-icon"></i>RoyiFileManager<div class="window-actions"><i data-lucide="minus"></i><i data-lucide="square"></i><i data-lucide="x"></i></div></div>
<div class="workspace">
<section class="pane">
<div class="location"><i data-lucide="hard-drive"></i><span>C:</span><span class="chevron">&#8250;</span><span>Documents</span><span class="chevron">&#8250;</span><span>Reports</span></div>
<div class="columns"><span class="sort">Name<i data-lucide="chevron-up"></i></span><span class="size">Size</span><span class="date">Modified</span></div>
<div id="files"></div>
<div class="pane-status">10 files, 2 folders<span class="right">Quarterly Report.pdf &middot; 284 KB</span></div>
</section>
<div class="divider"></div>
<section class="pane preview">
<div class="preview-title"><i data-lucide="file-text"></i><span class="filename">Quarterly Report.pdf</span><button class="quiet icon" aria-label="Close QuickView" title="Close QuickView"><i data-lucide="x"></i></button></div>
<div class="canvas" aria-label="PDF pages"><div class="pages">
<article class="sheet">
<div class="sheet-head"><span>FIELDWORK</span><span>RESEARCH &amp; OPERATIONS</span></div>
<h1>Quarterly Report</h1><div class="subtitle">July &ndash; September 2026 &middot; Prepared 5 October 2026</div>
<h2>01 &nbsp; Overview</h2>
<p>This quarter focused on reliable delivery, clearer reporting and the completion of long-running projects. The team closed the period ahead of schedule while keeping operating costs within the agreed budget.</p>
<p>All three workstreams improved against the previous quarter. The strongest gains came from reducing review time and making routine work easier to track.</p>
<h2>02 &nbsp; Results At A Glance</h2>
<table class="report-table"><thead><tr><th>Measure</th><th>Q2</th><th>Q3</th><th>Change</th></tr></thead><tbody><tr><td>Projects delivered</td><td>18</td><td>24</td><td>+33%</td></tr><tr><td>On-time delivery</td><td>89%</td><td>96%</td><td>+7 pts</td></tr><tr><td>Average review time</td><td>4.2 days</td><td>2.8 days</td><td>&minus;33%</td></tr><tr><td>Budget utilization</td><td>94%</td><td>92%</td><td>&minus;2 pts</td></tr></tbody></table>
<h2>03 &nbsp; Workstream Completion</h2>
<div class="chart"><div class="chart-row"><span>Research</span><div class="bar-track"><div class="bar" style="width:96%"></div></div><span>96%</span></div><div class="chart-row"><span>Delivery</span><div class="bar-track"><div class="bar" style="width:88%"></div></div><span>88%</span></div><div class="chart-row"><span>Operations</span><div class="bar-track"><div class="bar" style="width:82%"></div></div><span>82%</span></div></div>
<p class="footnote">Figures reflect completed work as of 30 September 2026.</p>
<div class="sheet-foot"><span>FIELDWORK &middot; QUARTERLY REPORT</span><span>1 / 3</span></div>
</article>
<article class="sheet">
<div class="sheet-head"><span>FIELDWORK</span><span>QUARTERLY REPORT &middot; Q3 2026</span></div>
<h1>Priorities For Q4</h1><div class="subtitle">October &ndash; December 2026</div>
<h2>04 &nbsp; Next Quarter</h2>
<p>The next quarter will concentrate on finishing the remaining delivery milestones and extending the reporting improvements across the wider team.</p>
<table class="report-table"><thead><tr><th>Priority</th><th>Owner</th><th>Target</th></tr></thead><tbody><tr><td>Complete rollout</td><td>Delivery</td><td>October</td></tr><tr><td>Review process updates</td><td>Operations</td><td>November</td></tr><tr><td>Annual planning</td><td>Research</td><td>December</td></tr></tbody></table>
<h2>05 &nbsp; Delivery Notes</h2><p>Keep the weekly review cadence and publish a single summary of decisions, open questions and upcoming milestones.</p>
<div class="sheet-foot"><span>FIELDWORK &middot; QUARTERLY REPORT</span><span>2 / 3</span></div>
</article>
<article class="sheet"><div class="sheet-head"><span>FIELDWORK</span><span>QUARTERLY REPORT &middot; Q3 2026</span></div><h1>Appendix</h1><div class="subtitle">Definitions and reporting notes</div><p>Project counts include work accepted during the reporting period. Percentages are rounded to the nearest whole number.</p><div class="sheet-foot"><span>FIELDWORK &middot; QUARTERLY REPORT</span><span>3 / 3</span></div></article>
</div></div>
<div class="toolbar"><button class="icon" aria-label="Previous page" title="Previous page"><i data-lucide="chevron-up"></i></button><input class="page-number" aria-label="Current page" value="1"><span class="page-total">/ 3</span><button class="icon" aria-label="Next page" title="Next page"><i data-lucide="chevron-down"></i></button><span class="separator"></span><button title="Fit page">Fit Page</button><button class="active" aria-pressed="true" title="Fit width">Fit Width</button><span class="separator"></span><button class="icon" aria-label="Zoom out" title="Zoom out"><i data-lucide="minus"></i></button><span class="zoom-label">73%</span><button class="icon" aria-label="Zoom in" title="Zoom in"><i data-lucide="plus"></i></button><span class="format">PDF</span></div>
</section>
</div>
<div class="global-status">C: &nbsp; 218.6 GB free of 953.1 GB<span class="right">RoyiFileManager</span></div>
<script src="https://unpkg.com/lucide@0.468.0/dist/umd/lucide.min.js"></script>
<script>
const entries = [
  ['folder', '..', '', ''],
  ['folder', 'Archive', '', '04/10/2026 09:14'],
  ['folder', 'Working Files', '', '02/10/2026 16:32'],
  ['file-text', 'Annual Summary.pdf', '416 KB', '01/10/2026 14:28'],
  ['file-text', 'Budget Notes.pdf', '128 KB', '30/09/2026 11:05'],
  ['file-text', 'Delivery Schedule.pdf', '192 KB', '03/10/2026 08:47'],
  ['file-spreadsheet', 'Metrics.csv', '18 KB', '05/10/2026 09:10'],
  ['file-text', 'Meeting Notes.txt', '6 KB', '04/10/2026 15:21'],
  ['file-text', 'Quarterly Report.pdf', '284 KB', '05/10/2026 10:42'],
  ['file-text', 'Research Brief.pdf', '352 KB', '29/09/2026 16:04'],
  ['file-text', 'Review Checklist.md', '4 KB', '02/10/2026 12:38'],
  ['file-text', 'Roadmap.pdf', '236 KB', '01/10/2026 10:16'],
  ['file-text', 'Team Update.pdf', '168 KB', '03/10/2026 17:30']
];
document.querySelector('#files').innerHTML = entries.map(([icon, name, size, date]) =>
  `<div class="row ${icon === 'folder' ? 'folder' : ''} ${name.endsWith('.pdf') ? 'pdf' : ''} ${name === 'Quarterly Report.pdf' ? 'selected' : ''}"><span class="filename"><i data-lucide="${icon}"></i>${name}</span><span class="size">${size}</span><span class="date">${date}</span></div>`
).join('');
if (window.lucide) lucide.createIcons();
document.querySelector('.canvas').scrollTop = 290;
</script>
</body>
</html>
```