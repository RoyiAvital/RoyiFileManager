# QuickView 002: Animated Images

## Task

Play animated GIF, WebP and APNG files in the QuickView image viewport. Today they
show only their first frame. Videos moved to [QuickView006](../Plan/QuickView006.md) on
2026_10_27 and wait for the PyQt6 migration.

Status: Implemented 2026_10_27; implementation review recorded below, with
IR01-IR02 open.

## Scope

- GIF and WebP files that the installed Qt image plug-ins (`qgif`, `qwebp`) decode
  as animations, and APNG files (see below). Detection uses the file content, not
  the suffix.
- Animations start playing when shown and follow the file's loop count (most
  loop forever).
- A Play/Pause toggle button and the Space key, shown and active only for
  animations. Fit, 100%, zoom, pan and Copy Image keep working; Copy Image
  copies the current frame.
- Excluded: frame stepping, speed control, seeking, a frame cache, new settings.
- Still images, text, PDF and table previews are unchanged. Public `fman` plug-in
  APIs are unchanged.

## Design

### Detection (loader thread)

`load_image` in [quick_view_images.py](../src/main/python/fman/impl/quick_view_images.py)
already decodes the first frame off Qt. After that, for `gif` and `webp`, mark the
result animated when `reader.supportsAnimation()` and `reader.imageCount() > 1`.
Return the first frame as today plus the frame count (`frames`) and the local `path` in
`ImageResult`. Animations larger than 16 MP per frame stay still images, because
QMovie decodes each frame on the Qt thread. The 64 MiB file limit is unchanged.

For `png`, a short chunk scan looks for `acTL` before the image data. Only then
is the file read and indexed by `parse_apng` (frame rectangles, delays, dispose
and blend operations, data offsets; invalid frames keep the still image).

### APNG Playback

Qt 5 has no APNG animation handler and PyQt5 cannot register an image plug-in,
so [quick_view_animation.py](../src/main/python/fman/impl/quick_view_animation.py)
adds `ApngMovie`, which has the QMovie subset QuickView uses (`frameChanged`,
`finished`, `error`, `start`, `setPaused`, `stop`, `state`, `currentImage`). A
`QTimer` drives it with each frame's delay (at least 20 ms). Each frame is
wrapped as a standalone PNG (signature, IHDR with the frame size, shared PLTE/tRNS
and color chunks, its IDAT/fdAT data, IEND) and decoded by Qt's PNG reader, then
painted onto the full-size canvas with the frame's dispose and blend operations.
It keeps the encoded bytes (at most 64 MiB), the canvas and, for "previous"
disposal, one saved canvas; no file handle stays open.

### Playback (Qt thread)

- `QuickViewSession.show_result` shows the first frame as today. For an animated
  result it creates one `QMovie(path, format)` owned by the session, with
  `CacheNone` so decoded frames are not retained, and starts it.
- `frameChanged` calls a new `PreviewCanvas.set_frame(image)`, which replaces the
  image without resetting the fit/zoom mode, scale or scroll position.
- The Play/Pause button is a checkable `QToolButton` in the existing image control
  row, using the style's media play/pause icons and a tooltip. It is hidden unless
  the current preview is animated. Space on the canvas toggles it; for still
  images Space keeps its current behavior.
- When the file's loop count ends, the button shows Play; Play restarts from the
  first frame.
- QuickView hidden (pane hidden or window minimized): pause; resume on show unless
  the user paused it.
- The metadata label adds the frame count, for example `GIF 480 x 270 | 100% | 24 frames`.

### Cleanup and Errors

- Selection change, switching to another preview kind, closing QuickView and
  overlay disposal all go through one `_stop_animation()`: stop the movie,
  disconnect it, delete it and hide the button. Deleting the movie releases the file.
- Frame signals from a stopped movie are ignored (the session holds only the
  current movie).
- A QMovie error stops playback, keeps the last shown frame and notes
  `Animation stopped` in the metadata label. Selecting another file recovers.

## Alternatives

- **Start paused with Play/Pause and Restart buttons** (previous design): rejected
  as more controls than an image preview needs; image viewers autoplay animations.
- **Decode all frames on the loader thread:** rejected; unbounded memory for small
  files with many large frames.
- **QMediaPlayer for animations:** rejected; it does not use Qt's image plug-ins.
- **APNG through a native Qt plug-in or Pillow:** rejected; a native binary to
  build and maintain, or a new dependency. Wrapping frames for Qt's PNG reader
  needs neither.

## Runtime Effects

- Still images, other previews and a closed QuickView: no QMovie and no timer.
- While an animation is shown: one QMovie, its frame timer and one decoded frame
  at a time, decoded on the Qt thread; the file stays open until playback stops.
- Paused or hidden animations do no decoding work.

## Tests

- Unit (`test_quick_view_animation`): `load_image` marks generated two-frame GIF
  and APNG files animated, and one-frame GIF/APNG, plain PNG and an APNG with an
  out-of-bounds frame still; frames over 16 MP stay still. APNG parsing (delays,
  loop count, truncation), dispose background/previous, blend source/over, loop
  end with restart, pause/resume and an undecodable frame.
- Qt integration (`QuickViewImagesIT`): generated two-frame GIF and APNG files
  show the Play/Pause button and change frames; Space and the button pause and
  resume; zoom survives frame changes; hiding QuickView pauses and showing resumes;
  a still image hides the button and stops the movie; after closing QuickView the
  file can be renamed. Animated WebP is not covered: Qt cannot write it and no
  fixture is stored.

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_view_animation', 'fman_unittest.test_quick_view_images', 'fman_unittest.test_quick_view'], env=build._environment()).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.QuickViewIT', 'fman_integrationtest.test_qt.QuickViewImagesIT'], env=env).returncode)"
```

## Implementation Steps

1. Loader: animation detection and the `frames` result field, with unit tests.
2. Canvas `set_frame`, session-owned QMovie, `_stop_animation()` and the
   Play/Pause button and Space key, with Qt integration tests.
3. Hide/show pause and the metadata frame count.
4. APNG: `parse_apng`, `ApngMovie` and dispose/blend/loop tests.
5. Update [docs/tools.md](../docs/tools.md), the Core README and CHANGELOG.

## Acceptance Criteria

- Animated GIF, WebP and APNG play in QuickView; still images look and behave as before.
- The Play/Pause button appears only for animations and toggles with a click or Space.
- Zoom, fit and pan are kept across frames; Copy Image copies the current frame.
- Changing the selection or closing QuickView stops playback and releases the file.

## Implementation Review (2026-10-27)

Two implementation follow-ups remain open. No application changes were made by
this review; the original implementation and validation records are preserved.

### IR01 - P2: Short APNG Control Chunks Discard a Valid Still Frame

- Owner: `parse_apng` in
  [quick_view_animation.py](../src/main/python/fman/impl/quick_view_animation.py)
  and `_animation` in
  [quick_view_images.py](../src/main/python/fman/impl/quick_view_images.py).
- Failure: fixed-size `struct.unpack` calls can raise `struct.error`, but the
  animation fallback catches only `ValueError`. A malformed animation control
  therefore escapes `load_image` instead of retaining the decoded first frame.
  `ImageLoader` catches it as an unexpected exception and delivers
  `Unable to preview file` with no image.
- Probe: generated a 1 x 1 RGBA PNG with valid chunk CRCs, two declared APNG
  frames, valid first-frame data, and an empty second `fcTL` followed by `IEND`.
  Qt decoded its still frame successfully. `load_image` raised `struct.error`
  (`unpack requires a buffer of 26 bytes`); the real `ImageLoader` delivered an
  error result without an image.
- Required follow-up: validate control chunk lengths and normalize malformed
  animation metadata to the parser's fallback error contract. Add a regression
  asserting that short control chunks retain the image with animation disabled,
  both through `load_image` and its normal loader boundary.
- Coverage gap: existing corrupt-APNG coverage checks an out-of-bounds frame,
  which raises `ValueError`; the truncation check does not exercise this loader
  fallback with a decodable PNG still frame.

### IR02 - P3: Animation Error Metadata Persists on the Next Still Image

- Owner: `QuickViewSession._stop_animation` and `_animation_error` in
  [quick_view.py](../src/main/python/fman/impl/quick_view.py).
- Failure: `_animation_error` stops and clears the movie, then sets the
  overlay's `animation_note`. Later `_clear` and `show_result` call
  `_stop_animation`, which returns immediately when there is no movie and does
  not reset that note. A successfully loaded still image consequently displays
  `Animation stopped`, despite having no animation.
- Probe: used a real Qt overlay and the session's actual playback/error/clear
  methods, with unrelated preview dependencies stubbed. After starting a
  generated APNG, invoked the animation error callback, cleared for a selection
  change, and showed a valid 2 x 2 PNG. Its metadata was
  `PNG  2 x 2  |  100%  |  Animation stopped`, with no active movie.
- Required follow-up: reset animation presentation state when replacing or
  clearing a preview even if its movie was already removed. Preserve the error
  note on the failed preview until that transition. Add error-to-still and
  error-to-other-preview recovery coverage.
- Limit: exercised the actual error callback directly; not a full application
  selection workflow or a naturally occurring decoder failure.

### Review Validation

- Bounded generated-file probes ran as `python -X faulthandler -u -`, through
  `build._environment()` with `QT_QPA_PLATFORM=windows` and a 15-second parent
  timeout. All files and settings were isolated in a temporary directory.
- Controls passed: a generated `.apng` file routed by content to a two-frame
  image result; minimizing a native Qt window paused its animation, and restoring
  it resumed playback. Selection-change cleanup was also checked in source.
- Editor diagnostics reported no errors in the animation player, image loader
  or QuickView integration. No existing unit, integration, smoke, performance,
  build or freeze target was run; earlier results below were not independently
  rerun. Animated WebP and frozen delivery remain unverified.

### Resolution (2026-10-27)

- IR01 fixed: `parse_apng` checks the minimum length of `IHDR`, `acTL`, `fcTL`
  and `fdAT` and reports short chunks as `ValueError`, which the loader turns into
  a still image. Regression: an empty second `fcTL` and a short `acTL` keep the
  first frame through `load_image` and through `ImageLoader`.
- IR02 fixed: `_stop_animation` also clears a leftover `Animation stopped` note
  when no movie is active. Regression: error followed by a still image, and error
  followed by an error preview and then a still image.
- By user request, `.apng` files are routed to the image loader as well;
  APNG content in `.png` files already played. Regression: `.apng`, `.png` and
  `.APNG` all load as two-frame animations.

## Reviewers

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed incremental embedded video support through an isolated libmpv
  helper, with explicit dependency, codec/license, focus and teardown feasibility
  gates. Awaiting review, dependency approval and implementation.

### 2026_09_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Revised per user direction to in-process QMediaPlayer/QVideoWidget
  using installed Qt modules and existing QuickView ownership. Removed helper,
  IPC, native embedding and libmpv deployment. Construction/availability probe
  passed; real playback and portable checks remain pending. Explicitly documented
  backend-dependent first frame/codecs, lack of sandboxing and native teardown
  limits instead of retaining unsupported guarantees from the previous design.

### 2026_09_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Sol
- Effort: High
- Context Window: 272K
- Outcome: Extended the Qt-only plan to route animated GIF/WebP through QMovie
  with movie-like controls and a still-frame fallback. APNG requires a verified
  Qt animation handler; actual frame playback and portable codecs remain unverified.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Feasibility review: the full video/animation scope is moderate work,
  with backend-dependent delivery risk. Existing debounce, bounded loading and
  generation handling are reusable, but routing and controls remain image-only.
  GIF animation alone is a smaller candidate stage, subject to explicit scope
  approval. Real playback, replacement/teardown, file unlock and portable codec
  checks are the main uncertainties, not constructing the Qt widgets. Scope and
  delivery order unchanged; no implementation or new playback tests performed.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Rewritten by user request for animated images only: autoplay with the
  file's loop count, a Play/Pause toggle and Space shown only for animations,
  one session-owned QMovie with CacheNone and a 16 MP per-frame limit. Video moved
  to QuickView006, blocked on the PyQt6 migration. Earlier records kept above.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Added APNG by user request: frames wrapped as standalone PNGs for Qt's
  decoder and composited by `ApngMovie`, a QMovie-compatible player. No new
  dependency or native plug-in.

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Reviewed the loader, APNG parser/player, session lifecycle, controls
  and nearby regression coverage. Recorded IR01 (short-control still fallback)
  and IR02 (stale animation-error metadata) with bounded disposable-probe
  evidence. Content routing for `.apng` and native minimize/resume controls
  passed. No application changes or existing test targets run; historical
  implementation, validation and reviewer records preserved. Follow-up needed
  before acceptance.

## Implementer

### 2026_10_27 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented GIF/WebP playback through QMovie and APNG through
  `ApngMovie` in `quick_view_animation.py`; loader detection in
  `quick_view_images.py`; canvas `set_frame`, Play/Pause button, Space, pause
  while hidden and frame count in `quick_view.py`; frozen hidden import. Focused
  unit, Qt integration and smoke checks pass.

### 2026_10_27 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Fixed IR01 (short APNG control chunks keep the still image) and IR02
  (stale `Animation stopped` note), and routed `.apng` files to the image loader.
  Regressions added; focused runs pass.

## Validation Results

- `python -m unittest fman_unittest.test_quick_view_animation
  fman_unittest.test_quick_view_images fman_unittest.test_quick_view
  fman_unittest.test_quick_view_text fman_unittest.test_quick_view_pdf`
  (offscreen): 56 OK. Qt prints `libpng error` for the deliberately broken frame.
- `python -m unittest fman_integrationtest.test_qt.QuickViewIT
  fman_integrationtest.test_qt.QuickViewImagesIT
  fman_integrationtest.test_qt.QuickViewCsvIT
  fman_integrationtest.test_qt.QuickViewTextIT` (windows platform): 30 OK,
  including the new GIF/APNG playback test.
- `python -m fman_integrationtest.quick_view_smoke`: both passes OK.
- Not run: animated WebP (no fixture), window minimize (hide/show is tested on
  the overlay), frozen build, CPU and memory measurements.

IR01/IR02 follow-up (2026-10-27):

- `python -m unittest fman_unittest.test_quick_view_animation
  fman_unittest.test_quick_view_images fman_unittest.test_quick_view`
  (offscreen): 21 OK.
- `python -m unittest fman_integrationtest.test_qt.QuickViewIT
  fman_integrationtest.test_qt.QuickViewImagesIT` (windows platform): 15 OK.
- Window minimize pause/resume was confirmed by the review probe.
