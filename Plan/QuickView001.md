# QuickView 001: Initial Design and Images

## Task

Use the existing inactive pane as a QuickView viewport for the file under the
active pane's cursor. This initial stage owns the shared design and delivers image
support: inspect at Fit or true 100%, and pan larger images without another window.
There is one QuickView feature and one viewport, extended in three delivery stages:

1. Stage 001: the shared foundation and images, specified in this document.
2. [Stage 002: Videos](QuickView002.md): add video support to that same viewport.
3. [Stage 003: Text-Based Files](QuickView003.md): add text, Markdown, and programming languages.

Status: proposed design only; review required before implementation. Each stage
owns its implementation, tests and completion record. Completing this initial
stage leaves stages 002 and 003 independently pending.

## Scope

- Windows, exactly two existing directory panes. The invoking pane is the source;
  the other pane temporarily presents QuickView instead of its directory content.
- **Toggle QuickView** / `toggle_quick_view`, proposed default `Ctrl+Q` on Windows.
  Preserve Linux's existing `Ctrl+Q` quit binding and macOS Quick Look.
- Follow the source cursor, not marked selection, including when several files
  are marked. Source browsing/filtering/navigation remains available.
- Same viewport, toggle, focus rules, and lifecycle across all three stages.
  Type-specific controls appear within it; no extra splitter pane, bottom dock,
  detached preview window, or independent image/video/text toggle.
- Local regular files and accessible UNC files after URL resolution, including
  resolved local symlinks. No archive extraction, remote downloads, directory
  thumbnails, PDF/office documents, editing, executing scripts, persistent content
  cache, or background prefetch in these stages.
- Required baseline: JPEG, PNG, BMP. WebP, TIFF, GIF and ICO are conditional on
  verified Qt handlers in the portable distribution; missing codecs are explicit.
  Decode only the first frame/page; no animation timers.
- EXIF orientation, transparency, Fit, 100%, incremental zoom, mouse/keyboard pan.
- Exclude SVG rasterization, RAW, HEIC/AVIF, multipage navigation, slideshows,
  editing, export and persistent thumbnails. SVG may appear as source in stage 003.
- Preserve the public `fman` plug-in API and the identity/state of both real panes.

## Design

### Experience and Reference

[Yazi](https://github.com/sxyazi/yazi) is an interaction reference, not a runtime
dependency or a source-code transplant. Its
[preview configuration](https://yazi-rs.github.io/docs/configuration/yazi/#preview)
and [previewer descriptions](https://yazi-rs.github.io/docs/configuration/yazi/#plugin)
support cursor-oriented previews, bounded image work, asynchronous rendering, and
format-specific previewers. Its
[seek command](https://yazi-rs.github.io/docs/configuration/keymap/#mgr.seek)
illustrates interacting with preview content while browsing.

Adapt those ideas to the existing two-pane Qt GUI. Do not copy Yazi's three-column
layout, terminal image protocols, directory preloading, or thumbnail-only video
behavior. Here images support native-resolution inspection, videos support explicit
playback, and text is selectable. Keep the app's current typography/theme and a
compact toolbar; use existing icon conventions, tooltips, and accessible names.

### Shared State and Focus

- Off -> On: capture the source/target pane identities and show the initial cursor
  preview in the target. Leave keyboard focus in the source file list.
- On -> On: cursor change immediately invalidates the old result, clears its
  content, and schedules the latest candidate after a 100 ms single-shot debounce.
  Marking alone does not retarget. Source location changes invalidate immediately;
  request the new cursor only after its listing is ready.
- On -> Off: the toggle or viewport close control cancels work, releases media,
  restores the target's directory presentation, and returns focus to the source.
  Toggling while preview controls have focus closes the same session, never reverses
  the source and target.
- Add **Focus QuickView** / `focus_quick_view`, without a default shortcut, for
  keyboard-only access through Command Center or a user binding. Clicking the
  viewport also focuses its controls. Focus does not change the source owner.
- In the preview, local keys pan/seek/scroll/copy as specified by the renderer.
  `Escape` returns focus to the source; it does not consume Escape in source rename,
  filter, or other dialogs. `Tab` traverses preview controls with an exit back to
  the source. File-operation shortcuts never fall through to the hidden target.
- Normal pane switching from the source, including its existing Tab command,
  closes QuickView and then focuses the restored target file list. Programmatic
  target focus/navigation also closes it before performing the requested action.
  Merely focusing preview controls does neither.
- Source file operations keep their normal semantics; opposite-pane copy/move
  destinations remain the real target location, not the previewed file. Existing
  destination prompts must display that path. No preview drag/drop filesystem actions.
- Restore location, cursor, marks, sorting, column widths, filters, scrolling,
  status-bar mode, and splitter sizes without recreating/reloading a pane just to
  close QuickView. Real concurrent filesystem/model changes still take effect;
  restoration must not resurrect removed files or undo deliberate navigation.

### Shared Ownership and Integration

- A small Core command bridge invokes an internal `fman.impl.quick_view` controller.
  Renderer modules are internal adapters, not new `FileSystem` providers or pane
  objects. Do not add an external plug-in API in this task.
- [DirectoryPaneWidget and MainWindow](../src/main/python/fman/impl/widgets.py)
  retain their identities and splitter positions. Add a private presentation mode
  inside the existing target widget: hide its normal location/list/filter/status
  presentation and show the viewport in the same bounds. Do not reparent the pane
  or change the assumptions of its `window` property and public handle.
- The shared controller owns source/target, generation token, debounce, bounded
  work, renderer disposal, and restoration. The pane owns Qt layout/focus hooks;
  each renderer owns only content and its controls.
- [Controller dispatch](../src/main/python/fman/impl/controller.py),
  [active-pane lookup](../src/main/python/fman/impl/plugins/__init__.py), and
  MainWindow focus/status handling require a scoped preview-owner rule. During
  viewport interaction, Command Center/toggle/focus actions resolve to the source,
  not the hidden target. Non-preview operation remains unchanged.
- Subscribe to source current-row, model-reset/location-load, pane-close, and
  relevant layout changes only while enabled. GUI/model access stays on the Qt
  thread. The private current-row subscription is necessary because the public
  API does not expose a cursor-change subscription; isolate it in the pane adapter.
- Independent windows have independent sessions. Closing either pane/window or
  unloading its command owner disposes the session. Unsupported pane counts fail
  before hiding anything. Existing search/favorites panels keep their own lifecycle.

### Shared Data, Bounds, and Failure

- GUI captures a plain immutable request: generation, source URL, viewport size,
  device-pixel ratio, and renderer options. No widget/model is passed to workers.
- Resolve/stat/read off the GUI thread. Provider reads use the resolved local
  file, never arbitrary shell commands. Extension hints only choose a candidate;
  format validation determines whether it is supported. Symlinks follow their
  local targets; missing/broken/inaccessible inputs show an inline state.
- Common states: empty cursor, folder, loading, ready, unsupported format,
  unavailable dependency, too large, and read/decode failure. Escape filenames as
  plain text. Clear stale content immediately; do not leave a previous file visible
  under a new name or show modal errors for each cursor movement.
- At most one shared decode/read job and one replaceable pending request per
  window. Results carry their generation and file size/mtime fingerprint; reject
  stale results and files changed during a read. No file watcher or recurring stat;
  reload/cursor changes request fresh data.
- Native blocking reads/decodes may not be interruptible: cancel cooperatively,
  retain the occupied slot until return, and never spawn a replacement pool on
  disable/re-enable. Qt must not join/wait on those calls during teardown. Late
  results go to a service that checks weak session ownership before GUI dispatch.
- Across renderers, at most one helper process per window, including a retiring
  one. Stop/dispose it on replacement before starting another; this applies to
  video-to-text transitions too. Stage 002 introduces private worker dispatch and
  process cleanup reused by stage 003 without a dependency on video libraries.
  Format-specific message/resource limits belong to the stage plans.
- Release the previous renderer before allocating the next large result. Return
  plain bytes/text/metadata from workers; create GUI resources on the Qt thread.

### Shared Persistence and Dependencies

QuickView starts off on every application launch. No automatic session restoration
or cursor-history persistence. Optional preferences use `QuickView.json` through
existing differential config under `UserSettings`, loaded lazily on first use.
Initial defaults: image Fit, video no autoplay and muted, text no wrap, Markdown
rendered. Save only deliberate preference changes, never pan positions or every
cursor event; preserve unknown keys. A failed save does not prevent viewing.

| Stage | Dependency decision | New requirement |
| --- | --- | --- |
| 001: initial design and images | Existing PyQt5 5.15 widgets, QtGui image codecs | No new Python package; verify delivered codec plugins. |
| 002: videos | Proposed `python-mpv` binding (PyPI `mpv`) and Windows `libmpv` in an on-demand helper | New Python package plus native DLL/dependencies and license review. |
| 003: text-based | Qt plain text/Markdown rendering; proposed Pygments for language lexing | Pygments is new; no WebEngine, Node, or browser service. |

The [environment](../environment.yml) currently declares PyQt5, not `python-mpv`
or Pygments. These are design choices, not claims that packages are installed or
approved. User installation/approval is required before adding new packages; no
environment or dependency changes in this planning task. Details, alternatives,
fallbacks, and packaging gates belong to each stage. Yazi is not required.

### Image Dependencies

The shared infrastructure above is delivered with images in this stage.
No video or text dependency. Use existing PyQt5 5.15: `QImageReader` and a
Qt scrollable paint surface. No Pillow, ImageMagick, Yazi or new Python package.
The [environment](../environment.yml) already declares PyQt5. Verify codec plugin
collection in the [packaging specification](../RoyiFileManager.spec) and artifact;
development-machine support alone is insufficient.

[QImageReader documentation](https://doc.qt.io/archives/qt-5.15/qimagereader.html)
describes handler-dependent formats, `size()`, `setAutoTransform()`, scaled decode
limitations and `@2x` filename behavior. Do not assume Qt 6 allocation APIs exist
in Qt 5.15. Recheck these APIs if the separately planned Qt migration lands first.

### Image Display and Interaction

| Control | Behavior while preview has focus |
| --- | --- |
| Fit / `F` | Complete oriented image, preserved aspect ratio, no enlargement beyond 100%. |
| 100% / `1` | One source image pixel per physical screen pixel; never an enlarged thumbnail. |
| Zoom icons / `+`, `-` / Ctrl+wheel | Multiply/divide scale by 1.25, within 5%-800%; Fit can go below 5%. |
| Left-button drag | Hand cursor; image follows pointer, clamped to its edges. |
| Wheel / Shift+wheel | Vertical/horizontal pan; never change the source file. |
| Arrows / Shift+arrows | Pan by 32/128 logical pixels. |
| Escape / Tab / toggle | Shared focus/close rules; no fallthrough to hidden directory commands. |

Compact toolbar with existing icons, tooltips and accessible names; Fit/100% are
mode controls, with a percentage for custom zoom. Show dimensions/format as concise
metadata. Center small images and paint alpha over a restrained checkerboard.
Scrollbars expose both axes; no automatic fullscreen or file opening on double-click.

Define scale in physical output pixels per oriented source pixel. For viewport DPR
`ratio`, logical paint transform is `scale / ratio`. Fit is the minimum of `1`,
physical viewport width/image width and physical viewport height/image height.
Normalize decoded image DPR to `1` so `@2x` names cannot silently halve the size.
Metadata DPI does not change 100%. At 100%, align the origin to physical pixel
boundaries and disable smoothing.

Ctrl+wheel anchors zoom under the pointer; toolbar/keyboard zoom anchors the center.
Preserve that image coordinate until clamping is necessary. Fit recomputes on resize;
100%/custom zoom preserve scale and the center image point. Recompute transforms on
screen/DPR changes. Center an axis when smaller than the viewport; otherwise clamp
pan so the image cannot be moved entirely offscreen.

New files start centered in the preferred Fit or 100% mode. Deliberate mode changes
update shared preferences; custom zoom/pan is transient, not saved per file. Failed
settings writes do not prevent viewing.

### Image Decode and Ownership

- The shared bounded worker receives immutable request data. Resolve, stat, inspect
  headers and decode off the GUI thread; create/destroy reader and file handle there.
- Open the exact file through a read-only device, avoiding suffix fallback. Select
  only approved handlers and validate content; a decode error must not fall through
  to SVG or another installed handler.
- Before full decode reject input above 64 MiB, unknown/nonpositive dimensions,
  an edge above 32,768 pixels, or more than 32 million source pixels. These initial
  limits require measurements/review before raising; no unbounded override.
- Decode full resolution once with `setAutoTransform(True)` and convert to RGBA8888.
  Scaled decoding may still allocate the full source, so is not a safety mechanism.
  Do not enumerate frames/pages or load embedded thumbnails.
- Return immutable bytes, dimensions/stride, format, generation and fingerprint.
  No widgets, models or `QPixmap` cross threads. On Qt, validate byte length/stride
  before creating the display `QImage`, retaining backing bytes for its lifetime.
- Paint the original with a transform. No zoom-sized buffers, re-decode on pan or
  resize, or second full-sized `QPixmap` cache. Release old image/bytes before replacement.
- Reject stale output and files changed during reads. Cancellation is cooperative
  before/after native decode; `read()` itself may not be interruptible. Keep its
  shared slot occupied across disable/re-enable until it returns. Qt never waits.
- Corrupt, unavailable or oversized images show the shared inline state and disable
  image controls. A new cursor never retains the previous image under its name.

Color is best-effort Qt decoding, not a calibrated monitor-profile/HDR workflow.
Native codecs are not a sandbox: file/dimension limits reduce ordinary resource
abuse but do not prove a hard process-memory bound or prevent codec defects.

## Alternatives

- New third pane or detached window: contradicts the requested existing inactive
  pane viewport. Preserve the current two-pane geometry.
- Independent viewers per stage: creates competing state/bindings. Extend one
  controller with renderer adapters; stages add formats only.
- Replacing a real pane/model with a preview filesystem: breaks directory handles
  and restoration. Change presentation while retaining the real pane.
- Polling/preloading every file: adds idle work and network I/O. Subscribe on enable
  and load only the cursor file, with debounce and bounded latest-request handling.
- Always-active previews: not requested and can hold media/files open unexpectedly.
  An explicit toggle and off-on-start behavior make resource use predictable.
- Pillow: adds another dependency/decoder without removing native-memory risks.
  Existing Qt is sufficient for initial raster formats.
- Fit thumbnails only: cannot satisfy genuine 100%. One bounded full-resolution
  decode makes subsequent zoom/pan immediate.
- Tiled/region decode: useful for huge images, but handler support varies. Defer
  rather than promise arbitrary-resolution support.
- One pixel per logical pixel: enlarges at high DPI. Physical-pixel 100% provides
  predictable detail inspection.

## Runtime Effects

### Shared Foundation

- Off: command registrations and a cheap null presentation check only; no new
  models, scans, file reads, codecs, player, worker, listeners, or active timers.
  Disabling may leave one previously blocked read retiring, never new work.
- On: one viewport inside the existing pane, invocation-scoped subscriptions and
  a single-shot debounce. No extra filesystem model or directory enumeration.
- CPU/memory/I/O budgets are renderer-specific. Only the active renderer may own
  heavy resources. Settings writes occur only on explicit preference changes.
- Cancellation invalidates immediately; media/process cleanup is bounded by the
  relevant adapter. Blocking OS reads are a documented latency limit, not a reason
  to block Qt or accumulate workers.

### Images

- Off/other renderer: no image probes, reads, timers, submissions or pixel buffers.
  Enumerate capabilities lazily on first image use, not application startup.
- On: one shared worker, cursor file only, no directory scan/prefetch. A 32 MP RGBA
  image is about 122 MiB; conversion/transport may temporarily retain several buffers.
  Target incremental peak working set below 512 MiB on the largest accepted fixture;
  measure codec overhead and reduce limits if needed. This is not an allocator cap.
- Loaded: CPU only on repaint/interaction; no polling/animation. Zoom/pan does not
  allocate image-sized scaled copies. Read-only I/O plus explicit preference writes;
  no temporary or cache files. One blocked native call can retire after close.

## Tests

Planned tests, not implemented or run in this design task:

### Shared Foundation

- `fman_unittest.test_quick_view`: state transitions, latest-only requests, cursor
  versus marks, format routing, bounds, errors, generation checks, lazy settings,
  and cleanup. Assert no preview-specific work off, including re-enable while a
  canceled read is still retiring.
- `fman_integrationtest.test_qt.QuickViewIT`: real command registry and Windows
  binding; both source sides; still exactly two identical pane/model instances;
  restoration of marks/filter/cursor/scroll/splitter; current-row/loading races;
  programmatic focus/navigation; source Tab and viewport focus traversal;
  Command Center ownership; destructive keys do not reach hidden targets;
  existing panels/status bars; close/unload; stale delivery after deletion.
- Use event-gated workers to prove GUI responsiveness and bounded concurrency,
  not sleeps. Assert zero idle I/O/timers/jobs, and no directory scans when enabled.
- Run existing pane/filter/status/command regressions for touched integration paths.
  Add renderer gates from each stage. No full suite or package build automatically.

### Images

- Unit: Fit/100% at DPR 1/1.25/1.5/2; EXIF dimension swap; anchored zoom; pan clamping;
  small images; preferences; all size thresholds; malformed headers/buffers;
  stale, changed-file and canceled results.
- Qt/codec: generated JPEG/PNG/BMP; small licensed fixtures for EXIF and conditional
  formats. Assert pixels/alpha, `@2x`, first-frame-only, corruption, wrong suffix,
  removed files and codec absence. Mandatory baseline codecs must not be skipped.
- Native Qt: drag/wheel/arrows, resize/splitter, monitor changes and focus routing;
  preserve source cursor/marks. Check 1:1 pixel extent/edges, not just nonblank output.
- Performance: 1/12/32 MP cold/warm loads, 200 cursor changes, repeated toggles and
  event-gated slow reads. Assert one running/one pending job, no retained-buffer
  growth, zero off-path work after retirement. Record load time/peak memory and
  target GUI heartbeat gaps below 100 ms on the recorded machine while decoding.

  ### Commands and Manual Gates

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_view', 'fman_unittest.test_quick_view_images', '-q'], env=build._environment(), timeout=120).returncode)"
$env:QT_QPA_PLATFORM = 'windows'
  python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.QuickViewIT', 'fman_integrationtest.test_qt.QuickViewImagesIT', 'fman_integrationtest.test_qt.FilterBarIT', 'core.tests.commands.test___init__', '-q'], env=build._environment(), timeout=120).returncode)"
```

Manual: `python build.py run` with disposable `ROYIFILEMANAGER_USER_SETTINGS`;
  toggle from each side, browse delivered types, interact, close, restart, and verify
  directory state and off-on-start behavior. Check transparency, large/small images,
  100% and all four corners via panning. Inspect native Qt screenshots at
  100%/150%/200% Windows scaling and a narrow window. Portable dependency/codec smoke
  is a release gate when an artifact/build is authorized; no automatic freeze.
  Record it as unverified until run. Name conditional-codec skips and advertise
  those formats only after the delivered artifact passes.

## Implementation Steps

  1. Review the shared contract and image renderer together. Verify proposed Windows
    `Ctrl+Q` against all bundled bindings; retain user binding precedence.
  2. Implement shared state/request tests and the private pane-presentation adapter.
    Immediately run the focused state test after its first substantive edit.
  3. Wire toggle/focus/current-row events and restoration; run native QuickView tests
    and touched pane/command regressions before adding media behavior.
  4. Add bounded image loader/geometry tests; immediately run the focused unit module.
  5. Add Qt image display, mode/zoom/pan and stale-safe delivery; run native tests.
  6. Measure limits, verify codec collection and shared source smoke; record any
    unavailable artifact gate explicitly.
  7. Update README/Core usage and CHANGELOG for implemented behavior; complete this
    task with exact validation results, dependencies and limitations. Leave
    [videos](QuickView002.md) and [text-based files](QuickView003.md) pending, extending
    the same viewport. Update relative links when moving the canonical document to
    Done; do not duplicate its body in the index.

## Acceptance Criteria

  - One existing inactive pane displays the cursor image; there are always two real
    panes, no third pane/window, and no per-type QuickView activation modes.
  - Proposed binding and commands work from either source side and viewport focus;
    original pane state restores without changing existing public APIs.
  - Cursor-following behavior, focus ownership, stale-result rejection, no-op path,
    bounded jobs, and failure states pass unit/native Qt tests.
- Fit and physical-pixel 100% work; mouse/keyboard panning reaches every image edge
  at tested DPI scales. Resize does not silently reset 100%.
- Baseline codecs, orientation, alpha, limits and inline errors pass focused tests.
- Workers never access widgets/models; stale images never reappear; concurrency
  and resource bounds hold across rapid navigation/toggle cycles.
- No image-specific recurring work when off; resources release after retirement.
- Shared focus/restoration/API gates pass; artifact codec verification is recorded
  before release, not inferred from development tests.
- This stage provides a usable shared foundation; later stages extend it without
  replacement layouts or separate sessions. Dependencies are explicit.
- No application implementation is claimed by these design documents. Completion
  requires implementation review, exact validation results, and any unrun release
  gate to be completed or explicitly accepted for deferral.

## Reviewers

The original shared-design records and image-stage design record are retained
unchanged below. Subsequent reviews apply to this combined initial stage.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed one existing-pane QuickView session, delivered through three
  incremental format stages. Grounded in current Qt pane/focus/dispatch code and
  Yazi preview documentation; awaiting review, implementation and runtime checks.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Adopted requested QuickView001/002/003 filenames and completed the linked
  renderer designs. Clarified Qt-only images, isolated libmpv playback, Pygments
  highlighting and one helper across renderer transitions. Still proposed; native
  embedding, dependency approval and implementation gates remain unverified.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed Qt-only raster support, physical-pixel 100% and bounded pan/zoom
  in the shared viewport. Numbered stages follow the requested naming convention;
  codec, memory and DPI gates await review and implementation.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Consolidated the initial shared design and images into stage 001 at the
  user's request. Retained both contracts and their history, removed the separate
  shared task, and redirected the later stages and index. Design only; runtime
  and dependency gates remain pending.