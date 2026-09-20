# QuickView 001: Initial Design and Images

## Task

Use the existing inactive pane as a QuickView viewport for the file under the
active pane's cursor. This initial stage owns the shared design and delivers image
support: inspect at Fit or true 100%, and pan larger images without another window.
There is one QuickView feature and one viewport, extended in three delivery stages:

1. Stage 001: the shared foundation and images, specified in this document.
2. [Stage 002: Videos](QuickView002.md): add video support to that same viewport.
3. [Stage 003: Text-Based Files](QuickView003.md): add text, Markdown, and programming languages.

Status: revised design only, incorporating the user's overlay, Tab-focus and
minimal-workflow-impact decisions through 2026-09-21. This supersedes the earlier
NoFocus/stacked-page design and its approval. The latest review approved the overlay
design with three simplifications, incorporated below; implementation and its
validation gates remain pending.
Stages 002 and 003 remain independently pending and must align with this overlay
and focus contract before implementation.

## Scope

- Windows, exactly two existing directory panes. The invoking pane is the source;
  the other pane temporarily presents QuickView instead of its directory content.
- **Toggle QuickView** / `toggle_quick_view`, proposed default `Ctrl+Q` on Windows.
  Preserve Linux's existing `Ctrl+Q` quit binding and macOS Quick Look.
- Follow the source cursor, not marked selection, including when several files
  are marked. Source browsing/filtering/navigation remains available.
- One opaque QuickView overlay covers the target pane, including its address bar,
  without changing that pane's layout or widgets. Tab switches keyboard focus
  between the source file list and QuickView, never the covered target list.
  No extra splitter pane, bottom dock, detached window, or per-type toggle.
- Local regular files and accessible UNC files after URL resolution, including
  resolved local symlinks. No archive extraction, remote downloads, directory
  thumbnails, PDF/office documents, editing, executing scripts, persistent content
  cache, or background prefetch in these stages.
- Required baseline: JPEG, PNG, BMP. WebP, TIFF, GIF and ICO are conditional on
  verified Qt handlers in the portable distribution; missing codecs are explicit.
  Decode only the first frame/page; no animation timers.
- EXIF orientation, transparency, Fit, 100%, incremental zoom, mouse/keyboard pan.
- Up to 128 million source pixels and 65,536 pixels per edge, doubling each axis
  of the previous limits. The normalized 32-bit image buffer is at most 512 MB
  (about 488 MiB), matching the user's approximate 500 MB per-image allowance.
  The separate encoded-file limit remains 64 MiB; peak process RAM is not capped
  by the decoded-buffer allowance.
- Exclude SVG rasterization, RAW, HEIC/AVIF, multipage navigation, slideshows,
  editing, export and persistent thumbnails. SVG may appear as source in stage 003.
- Preserve the public `fman` plug-in API and the identity/state of both real panes.

## Design

### Isolation Contract

Prioritize a small integration surface over making QuickView impersonate a pane.
Off must preserve existing behavior, not merely approximate it. On intentionally
changes only the covered area's input/display and the source-to-preview focus switch.
Other commands retain their normal semantics. Near-zero workflow impact is an
acceptance goal, not a claim of zero native-code, memory or regression risk.

Allowed existing-code changes: thin Core command/lifecycle wiring, Windows binding
registration, and one active-session branch in `SwitchPanes`. Put the overlay,
event adapters, image loader and controls in internal QuickView modules. No changes
to pane layout/focus proxies, global active-pane lookup, MainWindow focus/status
handling, Controller dispatch, filesystem/model behavior or session persistence.
If implementation cannot satisfy this boundary, stop and review the reason rather
than widening the changes implicitly.

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

- Off -> On: retain the source/target pane identities and show the initial cursor
  preview over the target. Initially leave focus in the source file list. The
  preview canvas is one keyboard-focus target, including while loading or showing
  an error; its toolbar buttons and scrollbars use `Qt.NoFocus` to avoid extra stops.
- On -> On: cursor change immediately invalidates the old result, clears its
  content, and schedules the latest candidate after a 100 ms single-shot debounce.
  Marking alone does not retarget. Source location changes invalidate immediately;
  request the new cursor only after its listing is ready.
- Tab in the source follows the existing `switch_panes` binding, redirected to the
  QuickView canvas while enabled. Tab or Shift+Tab in QuickView returns to source;
  neither closes it. Clicking the canvas also focuses it. Image actions do not
  change the captured source/target identities or the source cursor.
- Escape in QuickView returns to source without closing. Source Escape, filtering,
  rename and dialog behavior are unchanged. No separate **Focus QuickView** command.
  The canvas explicitly returns `False` from `focusNextPrevChild`, so Tab/Backtab
  reach its `keyPressEvent` without traversing covered controls or relying on the
  MainWindow parent chain. No toolbar tab cycle or custom `ShortcutOverride` handler.
- QuickView is an auxiliary widget, not a substitute active file pane. Local image
  actions use its captured session. For every other non-modifier keypress, first
  focus the real source list, then call unchanged command dispatch once. This also
  handles toggle and Command Center; QuickView does not inspect bindings. Consume
  the event even if dispatch returns `False`, without synthesizing a list/filter
  keypress or invoking nonexistent-shortcut handling. An unbound key returns focus
  to source but does not act on the list. Leave focus where dispatch puts it; no
  automatic return to preview. Modifier-only presses retain canvas focus for local
  Shift+arrow and Ctrl+wheel interaction. Tab remains available to resume QuickView.
- On -> Off: Ctrl+Q/the configured toggle or the mouse close control invalidates
  work, releases the image and removes the overlay. Return focus to the surviving
  source when closing from QuickView; preserve focus in unrelated dialogs/panels.
  Toggle lookup is per window, so invocation from the preview closes the existing
  session rather than reversing source and target.
- Do not intercept target navigation, model changes or explicitly invoked file
  operations. They continue normally underneath; removal reveals the latest state.
  No operation blacklist, rollback or blanket disabling of the underlying pane.
  The supported pane-switch route focuses the overlay instead of the covered list;
  arbitrary direct widget manipulation by a plug-in is outside this focus guarantee.
- Source file operations keep their normal semantics; opposite-pane copy/move
  destinations remain the real target location, not the previewed file. Existing
  destination prompts must display that path. No preview drag/drop filesystem actions.
- Cover, do not rebuild or restore: existing target widgets/model stay in place
  and retain state. Do not hide/reparent them, replace their layout, or change the
  splitter. No recreation, reload or snapshot rollback on toggle.
- Closing either pane/window or unloading the Core command owner disposes the
  session. Invalid pane counts fail before any presentation change.

### Shared Ownership and Integration

- A small Core command bridge invokes an internal `fman.impl.quick_view` controller.
  Renderer modules are internal adapters, not new `FileSystem` providers or pane
  objects. Do not add an external plug-in API in this task.
- [DirectoryPaneWidget and MainWindow](../src/main/python/fman/impl/widgets.py)
  retain their identities and existing layout. Parent the lazy opaque overlay to
  `MainWindow.centralWidget()`, as a non-layout sibling above the splitter, not a
  descendant of either pane and not a separate window. Never parent it to the
  splitter, which adopts child widgets as panes. Map the target's rectangle into
  the central widget's coordinates; cover its address bar/list/filter/local status,
  never the splitter handle, source, bottom panels or global status bar.
- Keep the pane's focus proxy, filter positioning, status insertion and size hints
  unchanged. A sibling above the splitter also covers newly raised pane children
  without monitoring every filter/status child or changing their z-order.
- While enabled, filter target-pane `Resize`, `Move`, `Show`, `Hide` and splitter
  `Resize`, `Move`; also connect `splitterMoved`. On enable and these geometry/show
  notifications, recompute the rectangle from
  `target.mapTo(central, QPoint(0, 0))` and `target.size()`, then reposition/raise
  only the overlay. Mirror target show/hide; normal ancestor visibility applies.
  Disconnect/remove these adapters on disposal. No central/application-wide event
  filter, polling, layout insertion or off-path listener.
- Splitter movement within the central layout need not move the target relative to
  its own parent, so target-only filtering is insufficient. Panel open/close and
  ancestor-only movement are mandatory geometry regressions. The overlay receives
  pointer input, rejects filesystem drops and never forwards mouse events to
  covered controls.
- The Qt-thread controller owns source/target, generation, debounce and renderer
  disposal. It owns overlay geometry and focus switching; each renderer owns only
  content/controls. No normal-pane page container or state-restoration machinery.
- [SwitchPanes](../src/main/resources/base/Plugins/Core/core/commands/__init__.py)
  delegates to a small private QuickView focus handler when that window has a
  session: no explicit pane index toggles source/canvas; an explicit source/target
  index focuses that surface. With no session, the command follows its old path.
  The off path checks a private window-local reference without importing a renderer
  or reading settings. No change to `DirectoryPaneWidget.focus()` or navigation.
- Before entering the canvas, focus source if needed, then canvas. Existing
  MainWindow tracking retains the source because the overlay is outside both pane
  subtrees. Do not modify [active-pane lookup](../src/main/python/fman/impl/plugins/__init__.py)
  or status routing. While the auxiliary canvas has focus, a direct active-pane
  query can return none; this is explicit, not patched with a false focus owner.
- Canvas `keyPressEvent` handles only the local controls below and consumes
  modifier-only presses without changing focus. For every other key, focus source
  and call existing `Controller.handle_shortcut(source_widget, event)` once via
  [controller dispatch](../src/main/python/fman/impl/controller.py). Consume the
  event whether that returns `True` or `False`; if source cannot gain focus, consume
  without dispatch. Do not forward a raw keypress or call a file-list key handler.
- Zero binding recognition, settings lookup, toggle-command identification or
  shortcut cache lives in QuickView. Controller alone applies existing binding
  order, user overrides and pane/application command dispatch. Toggle is an ordinary
  source-pane command that closes the window's session; Command Center sees real
  source focus. Local canvas keys take precedence only inside QuickView. Source
  Tab follows its existing binding; the documented cycle assumes `switch_panes`.
  No command blacklist, custom `ShortcutOverride` handling or automatic focus
  restoration. Dialogs, panels and source-list dispatch remain outside this adapter.
- Connect source `selectionModel().currentChanged`, model-reset/location-load and
  close signals only while enabled, through one private pane adapter. No permanent
  cursor listener and no use of selection changes as cursor changes. GUI/model
  access remains on Qt; layout/DPR events are renderer-local.
- Independent windows have independent sessions. Existing search/favorites panels
  retain their own lifecycle and normal focus behavior.

### Renderer Boundary

Keep only three internal operations: `load(request) -> result` on the worker,
`show(result)` and `dispose()` on Qt. Requests contain immutable plain data;
`load` receives no widget, model or bound GUI adapter. Result disposal and generation
checks belong to the controller; image ownership is specified below. This is an
image-stage interface, not a generic streaming or process framework. Playback,
helper-process lifetime and text selection/find behavior belong to stages 002/003;
they reuse the source/preview focus switch and may extend local interaction after
review without adding another viewport/toggle.

### Shared Data, Bounds, and Failure

- Qt captures generation, source URL and load options as immutable plain data.
  Viewport size/DPR are display state, not decode inputs; resize never queues a read.
  Resolve/stat/read off Qt, accepting resolved local regular files only. Extension
  hints are not proof of format. Missing/broken/inaccessible inputs show inline states.
- Common states: empty cursor, folder, loading, ready, unsupported format,
  unavailable dependency, too large, and read/decode failure. Escape filenames as
  plain text. Clear stale content immediately; do not leave a previous file visible
  under a new name or show modal errors for each cursor movement.
- One lazy daemon loader thread per window, with one active job and one overwriteable
  pending request protected by a lock/condition. A new request replaces pending data;
  it does not submit another future. Use generation/cancellation checks before I/O,
  after decode and on Qt delivery. No module-global executor or general job scheduler.
- An active job includes any decoded result awaiting Qt delivery: do not start the
  next decode until that result is accepted/discarded. Thus queued completions cannot
  retain a succession of large images. Return through an explicit queued Qt signal,
  not the synchronous `run_in_main_thread` bridge. Disconnect on receiver disposal;
  discard a result whose session/generation is no longer current.
- Disable drops the pending request and invalidates the active one. The loader
  remains owned by the window across disable/re-enable until a blocked job returns;
  re-enable replaces pending data on that same loader. Threads exit when idle.
  On close/unload, drop requests, disconnect delivery and let an active daemon retire.
  Neither Qt teardown nor process exit joins it; check shutdown in a subprocess.
- Results include size/mtime fingerprints checked around the read; reject observed
  changes. This is not an atomic filesystem snapshot. No watcher, recurring stat,
  directory scan or prefetch. Clear the displayed image before a replacement decode.

### Shared Persistence and Dependencies

QuickView starts off on every application launch. No automatic session restoration
or cursor-history persistence. Optional preferences use `QuickView.json` through
existing differential config under `UserSettings`, loaded lazily on first use.
Default to image Fit. Save only deliberate Fit/100% preference changes, never pan
positions or every cursor event; preserve unknown keys. A failed save does not
prevent viewing. Stage 001 adds no package or helper process. Video/text dependencies,
preferences and helper cleanup remain in [002](QuickView002.md) and
[003](QuickView003.md), not prerequisites or implementation work for this stage.

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

Use `QAbstractScrollArea` with a custom-painted `viewport()`, scrollbars and a
compact toolbar. Use one strong-focus canvas, with toolbar buttons/scrollbars
`Qt.NoFocus`; canvas clicks focus it and toolbar clicks retain the current focus.
Normal scrollbar input is reused; drag, anchored Ctrl+wheel zoom and painting
need small explicit handlers. Keep pan in one scrollbar-based model.

| Control | Behavior |
| --- | --- |
| Source Tab / `switch_panes` | Focus QuickView; do not close or reveal the covered list. |
| Canvas Tab / Shift+Tab / Escape | Focus source; leave QuickView open. |
| Configured toggle / close icon | Close QuickView; return to source if preview had focus. |
| Fit / canvas F | Complete oriented image, preserved aspect ratio, no enlargement beyond 100%. |
| 100% / canvas 1 | One source image pixel per physical screen pixel; never an enlarged thumbnail. |
| Zoom icons / Ctrl+wheel / canvas + or - | Multiply/divide scale by 1.25, within 5%-800%; Fit can go below 5%. |
| Canvas arrows / Shift+arrows | Pan 32 / 128 logical pixels; never change the file cursor. |
| Left-button drag | Hand cursor; image follows pointer, clamped to its edges. |
| Wheel / Shift+wheel | Vertical/horizontal pan; never change the source file. |
| Other non-modifier key in canvas | Focus source, invoke unchanged dispatch once; consume unbound keys without sending them to the list/filter. |

Also expose ordinary Core pane commands, without default bindings:
`quick_view_fit`, `quick_view_actual_size`, `quick_view_zoom_in`,
`quick_view_zoom_out`, and `quick_view_pan(direction, large=False)`, where direction
is left/right/up/down. All controls use the same renderer methods, are visible
only for a ready image in the invoking source session, and safely no-op otherwise.
Canvas-local controls do not move focus to execute pane commands. Source navigation
keys and Command Center behavior stay unchanged.

Use existing icons/tooltips/accessible names; Fit/100% are mode controls, with a
percentage for custom zoom. Show dimensions/format, center small images and paint
alpha over a restrained checkerboard. No fullscreen or double-click file opening.

Define scale in physical output pixels per oriented source pixel. For viewport DPR
`ratio`, logical paint transform is `scale / ratio`. Fit is the minimum of `1`,
physical viewport width/image width and physical viewport height/image height.
Normalize decoded image DPR to `1` so `@2x` names cannot silently halve the size.
Metadata DPI does not change 100%. At 100%, disable smoothing and round the paint
origin to physical pixels (`round(origin * ratio) / ratio` in logical coordinates).
This is a paint-only adjustment, not another pan state or an image-sized buffer.

Ctrl+wheel anchors zoom under the pointer; toolbar/keyboard zoom anchors the center.
Preserve that image coordinate until clamping is necessary. Fit recomputes on resize;
100%/custom zoom preserve scale and the center image point. Recompute transforms on
screen/DPR changes. Center an axis when smaller than the viewport; otherwise clamp
pan so the image cannot be moved entirely offscreen.

New files start centered in the preferred Fit or 100% mode. Deliberate mode changes
update shared preferences; custom zoom/pan is transient, not saved per file. Failed
settings writes do not prevent viewing.

### Image Decode and Ownership

- Create the read-only `QFile` and `QImageReader(device)` in the loader; close both
  there. Never pass a filename to an API that can try alternative suffixes.
- Reject files above 64 MiB before codec probing. Use
  `setDecideFormatFromContent(True)` and `reader.format()` to detect the format.
  Accept JPEG/PNG/BMP plus verified conditional GIF/ICO/TIFF/WebP handlers only.
  Pin the approved format with `setFormat`, `setDecideFormatFromContent(False)`
  and `setAutoDetectImageFormat(False)`, then inspect dimensions/read. Other formats
  are rejected, even when installed. Content detection can probe installed codecs;
  the allowlist controls accepted decodes, not a security boundary around probing.
- Before full decode reject unknown/nonpositive dimensions, an edge above 65,536
  pixels or more than 128 million source pixels. Both limits apply independently;
  65,536 by 65,536 is not allowed. Recheck decoded dimension limits and normalized
  `sizeInBytes()` against 512,000,000 bytes. These limits double each previous axis
  and quadruple the pixel/buffer allowance, as requested on 2026-09-21. Further
  increases require review; the 64 MiB encoded-file limit is unchanged.
- Decode full resolution once with `setAutoTransform(True)`; reject null results
  and normalize DPR to `1`. Normalize once in the loader to
  `Format_ARGB32_Premultiplied` for alpha or `Format_RGB32` otherwise, avoiding
  repeated source-format conversion during painting. Release the original after
  conversion and measure this transient overlap. No scaled decode, frame/page
  enumeration or embedded thumbnails.
- Return the owned `QImage` plus plain metadata, generation and fingerprint. A
  `QImage` is a reentrant value type, not a widget: after handoff the worker must
  neither mutate it nor keep an image cache. Qt paints it read-only. Do not wrap
  external byte storage, call `bits()` for transport, or construct a `QPixmap`.
  There is no raw-stride contract, retained-bytes owner or full-size transport copy.
- Paint using `QPainter` transform and `drawImage`. No zoom-sized buffers, re-decode
  on pan/resize, or second full-sized image cache. Clear the old image before loading.
- Reject stale/changed output. Cancellation checks bracket native reads/decodes;
  they cannot interrupt a blocked call. Keep the one loader occupied until return.
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
  and state preservation. Cover the real pane without modifying it.
- Stacked pages or reparenting existing widgets: unnecessary layout/focus/size-hint
  changes. A non-layout sibling overlay leaves the existing pane tree untouched.
- Overlay parented inside target plus global focus-owner overrides: changes shared
  command/status semantics. A sibling outside both panes plus explicit source-focus
  handoff uses existing semantics. Direct plug-in queries while the canvas is focused
  may see no active pane; this limitation is preferable to a global override.
- NoFocus canvas or Tab-to-close: simpler, but superseded by the user's requirement
  that Tab focus QuickView. Keep one focusable canvas, not a toolbar traversal chain.
- Snapshot/restore or target-navigation interception: unnecessary and can undo
  legitimate changes. Leave the actual directory widgets/model alive and covered.
- `ThreadPoolExecutor(max_workers=1)`: caps running threads, not queued requests;
  Python still joins its workers at exit, even after `shutdown(wait=False)`.
  A tiny per-window daemon loader/mailbox retains bounded work without that exit
  wait or cross-window blocking. No generic scheduler or weak-session registry.
- Raw RGBA bytes: extra copy and lifetime/stride bookkeeping with no process
  boundary to justify them. Transfer an exclusively handed-off `QImage` instead.
- Dimmed previous image under a Loading overlay: smoother browsing, but requires
  separate old/new file identity and retains the old pixel buffer during decode.
  Keep immediate blanking; it is simpler and never labels old content as new.
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

- Startup/off: thin command registrations and a null session check when
  `switch_panes` runs. No replacement layout, renderer import, overlay creation,
  settings read, new models, scans, codecs, workers, listeners or active timers.
  Disabling may leave one previously blocked read retiring, never new work.
- On: one sibling overlay over the existing target, enabled-only subscriptions and
  a single-shot debounce. No extra filesystem model or directory enumeration.
- CPU/memory/I/O here are image-only. Settings writes occur on explicit mode changes.
- Cancellation invalidates immediately. One blocked job may delay the next image
  in that window, never UI closure or another window's loader. Once disabled work
  retires, its thread exits; no polling, idle executor or queued future backlog.

### Images

- Off/other renderer: no image probes, reads, timers, submissions or pixel buffers.
  Enumerate capabilities lazily on first image use, not application startup.
- On: one loader per window, cursor file only. A 128 MP, 32-bit image uses
  512,000,000 bytes (512 MB, about 488 MiB) of normalized pixel storage: for example,
  16,000 by 8,000 pixels, twice each axis of an 8,000 by 4,000 image. This is the
  user's approximate 500 MB per-image allowance, not a strict 500,000,000-byte cap.
- Higher-depth input, orientation, format conversion and codec workspace can push
  peak RAM substantially above the retained buffer; one extra full-sized 32-bit
  buffer alone brings pixel storage to about 977 MiB. QImage handoff adds no
  deliberate full-size copy. The former below-512-MiB incremental peak target is
  superseded, not silently claimed for the larger images. Measure retained bytes
  and incremental peak working set separately; the measured peak needs explicit
  acceptance before release, rather than assuming an unrestricted higher budget.
  No hard allocator cap or codec sandbox is introduced.
- The maximum pixel workload/buffer is four times the previous allowance, not
  twice. Independent windows each have this allowance; aggregate RAM can grow
  accordingly. Loading can take longer, but off-path work, concurrency, immediate
  old-image release and the ban on prefetch/scaled-image caches remain unchanged.
- Loaded: CPU only on repaint/interaction; no polling/animation. Zoom/pan does not
  allocate image-sized scaled copies. Read-only I/O plus explicit preference writes;
  no temporary or cache files. One blocked native call can retire after close.

### Residual Risks

- Off-path integration should be low risk once regressions pass; it is not yet
  implemented or measured. While enabled, overlay geometry/input and queued result
  disposal remain the principal application-integration risks.
- Decoder faults can still terminate the process; header limits are not isolation.
  UNC/native reads may block the single loader indefinitely, although GUI close
  remains nonblocking. Do not describe either as guaranteed safe or cancellable.
- The larger image allowance increases enabled-state memory pressure and decode
  cost. The approximately 500 MB buffer budget does not establish safe total RAM
  use; largest-image peak measurements and their acceptance remain a release gate.
- Ordinary commands still operate on both real panes where their existing semantics
  require it. The covered target may change. QuickView is not a protection layer;
  disabling it exposes current state, with no rollback or new confirmation policy.
- A plug-in that assumes a file pane is always focused can observe none while the
  canvas owns focus, as with other auxiliary widgets. Test command handoff rather
  than expanding the public API to conceal this. Revisit only on demonstrated need.

## Tests

Planned application tests, not implemented or run in this design task:

### Shared Foundation

- `fman_unittest.test_quick_view`: state transitions, latest-only requests, cursor
  versus marks, generation checks, lazy settings and cleanup. Event-gated reads
  must prove one active job (including undelivered output) and one replaceable
  request, including disable/re-enable; no off-path work after retirement.
- `fman_integrationtest.test_qt.QuickViewIT`: real command registry and Windows
  binding from both sides. Capture layout identity/count, widget parents, focus
  proxies, pane/model identity, splitter sizes and minimum size before/while/after
  toggling. Preserve path/cursor/marks/sort/width/filter/scroll without reload. A
  separate covered-navigation case must reveal new state, not restore the old.
- Test off at startup and after disable: normal Tab, source filter/rename/selection,
  Command Center, file operations, panels/dialogs and status ownership. Instrument
  QuickView imports, settings, signal adapters, timers and I/O to prove off does
  no feature work except command registration/session checks, once a blocked job
  retires. Compare operation counts, not noisy millisecond startup thresholds.
- Source Tab focuses canvas; canvas Tab/Shift+Tab/Escape returns source without
  closing. Canvas clicks focus it; toolbar/scrollbars do not steal focus. Image
  keys do not reach either list. Exercise canvas Tab/Backtab under a plain QWidget
  parent to prove independence from MainWindow; use no custom ShortcutOverride.
  Modifier-only presses keep canvas focus; Shift+arrows and Ctrl+wheel stay local.
- Every other key calls unchanged Controller exactly once after source focus,
  including unbound keys, toggle, Command Center cancel/execute, both command kinds
  and custom overrides. Assert unbound keys reach neither list/filter nor the
  nonexistent-shortcut handler, and cause no binding scan outside Controller.
  Assert no automatic focus theft after dialogs/panels open. Verify unchanged
  MainWindow tracking and explicit no-active-pane lookup while canvas is focused.
  Programmatic target focus/navigation is not intercepted.
- Test overlay bounds after splitter/window/central-layout changes, panel open/close
  and minimize/restore, plus target show/hide. Include a splitter-only move with
  unchanged target-relative geometry and no target `Move` event; assert the overlay
  follows `target.mapTo(central, QPoint(0, 0))`. Verify the exact target/splitter
  event filters and `splitterMoved` connection are removed on disable. A new/raised
  target filter/status widget stays covered;
  source, splitter handle, panels/dialogs and global status remain reachable.
  Test source loading/reset, two independent windows, owner unload/window close,
  removed adapters and stale delivery to a deleted receiver.
- In a subprocess, close the app with a blocked fake read and prove it exits without
  joining a loader. In-process event gates prove another window remains responsive
  and can load independently. No sleep-based races or real hanging network calls.
- Run the touched pane/filter/status/command regressions listed below. No full suite
  or package build automatically.

### Images

- Unit: Fit/100% at DPR 1/1.25/1.5/2; EXIF dimension swap; anchored zoom; pan clamping;
  small images; preferences; all size thresholds; malformed headers/null results;
  stale, changed-file and canceled results. Resize/pan must never request decoding.
- Size boundaries: accept 16,000 by 8,000 and reject 16,001 by 8,000; independently
  accept 65,536 by 1 and its transpose, reject 65,537 by 1 and its transpose, and
  reject 65,536 by 65,536 on area. Check exact/one-above 64 MiB encoded-file and
  512,000,000-byte normalized-buffer limits. Unit tests use metadata/stubs, not
  hundreds of MiB of real allocations.
- Qt/codec: generated JPEG/PNG/BMP; small licensed fixtures for EXIF and conditional
  formats. Assert pixels/alpha, `@2x`, first-frame-only, corruption, wrong suffix,
  removed files, codec absence and rejection of installed SVG. Verify worker-created
  QImage lifetime through queued handoff, format normalization and disposal;
  mandatory codecs cannot skip.
- Native Qt: canvas and command-based controls, resize/splitter and monitor changes;
  preserve source cursor/marks and specified focus transitions. Check physical 1:1
  extent and snapped edges, not just nonblank output. Large images/labels must not
  change window minimum size or overflow the overlay at narrow widths.
- Performance: 1/12/32/128 MP cold/warm loads, 200 cursor changes, repeated toggles and
  event-gated slow reads/delivery. Assert bounded requests and no accumulated QImage
  results or retained-buffer growth. Use a compressed 16,000 by 8,000 fixture within
  the encoded-file limit, plus supported thin images at the maximum edge; verify
  Fit/100% and every corner remain paintable. Record normalized `sizeInBytes()`
  (at most 512,000,000), incremental peak RAM including orientation/conversion, load
  time and release after close. Obtain explicit acceptance of the measured peak;
  do not report the buffer size as peak RAM. Retain the target GUI heartbeat gaps
  below 100 ms on the recorded machine while decoding. Large-image performance
  checks are separate from lightweight unit tests; do not allocate them in this
  design-only update.

### Commands and Manual Gates

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_view', 'fman_unittest.test_quick_view_images', 'fman_unittest.impl.test_status_bar', '-q'], env=build._environment(), timeout=120).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.QuickViewIT', 'fman_integrationtest.test_qt.QuickViewImagesIT', 'fman_integrationtest.test_qt.FilterBarIT', 'fman_integrationtest.test_qt.MainWindowIT', 'core.tests.commands.test___init__', '-q'], env=env, timeout=120).returncode)"
```

Manual: `python build.py run` with disposable `ROYIFILEMANAGER_USER_SETTINGS`;
toggle from each side, browse images, Tab between source/canvas, use Command Center,
open/cancel dialogs and panels, close and restart. Check transparency, small/large
images, 100% and all corners via mouse, local keys and commands. Inspect native
screenshots at 100%/150%/200% Windows scaling and a narrow window. Verify directory
state, covered-target navigation, splitter interaction and off-on-start. Repeat the
normal workflow with QuickView never enabled and after disabling it.
Portable codec smoke remains a release gate when an artifact/build
is authorized; DLL presence alone is not a decode pass. No automatic freeze.
Name conditional-codec skips; advertise those formats only after artifact validation.

## Implementation Steps

1. Review the isolation contract, source-focus handoff and bounded loader shutdown.
   Recheck Windows `Ctrl+Q` and retain user binding precedence.
2. Implement state tests and the sibling overlay with placeholder content;
   immediately run focused tests. No image loading yet. Prove layout identity,
   target/splitter geometry listeners, panel open/close, ancestor-only movement,
   canvas-owned Tab traversal and off-path behavior before connecting file I/O.
3. Wire toggle, the SwitchPanes session branch, local command handoff and enabled-only
   cursor/load adapters. Delegate all non-local keys to unchanged Controller after
   source focus; no binding recognition in QuickView. Prove bound/unbound input and
   Command Center behavior with native Qt and existing regressions. Stop for review
   if shared routing needs edits.
4. Add the daemon mailbox loader, QImage handoff and pure geometry; run their focused
   tests, including blocked-read process exit, before connecting the actual renderer.
5. Add the QAbstractScrollArea renderer, local controls and bindable image commands;
   run image/native tests and the listed shared regressions.
6. Measure limits, run source smoke and inspect codec delivery. Record unavailable
   artifact gates explicitly; do not build packages without authorization.
7. Update README/Core usage and CHANGELOG only after implementation, then complete
   this task with validation results. Leave [videos](QuickView002.md) and
   [text](QuickView003.md) pending their own revised focus/process designs. Update
   relative links when moving this canonical file to Done; never keep a Plan copy.

## Acceptance Criteria

- One existing inactive pane displays the cursor image; there are always two real
  panes, no third pane/window, and no per-type activation modes or public API change.
- Tab focuses QuickView; Tab/Shift+Tab/Escape there returns source without closing.
  Canvas traversal explicitly returns `False`; no custom ShortcutOverride handling.
  Source browsing is unchanged. All non-local, non-modifier keys focus source before
  unchanged dispatch; unbound keys are consumed. QuickView contains no binding
  recognition. Command Center, dialogs and panels retain normal behavior.
- Existing pane layouts, parents, focus proxies, models, status/active-pane tracking
  and Controller dispatch are unmodified. No always-on filter or listener. Only
  thin registration/lifecycle wiring and the SwitchPanes branch touch existing code.
- The overlay changes no underlying state and intercepts no deliberate navigation
  or file operation. Covered changes remain visible on close; no restore/reload.
  Bounds cover only the target, including address bar and pane-local status/filter.
  Target/splitter listeners keep these bounds through panel layout changes and
  ancestor-only movement, and are absent after disposal.
- Cursor-following, loading, generation rejection, close/unload and the disabled
  no-op path pass focused tests. No unbounded request or decoded-result queue.
- Fit and physical-pixel 100% work; mouse/keyboard panning reaches every image edge
  at tested DPI scales via local controls/bindable commands. Resize preserves 100%.
- Baseline codecs, orientation, alpha, limits and inline errors pass focused tests.
- Both the 128-million-pixel area and 65,536-pixel edge limits pass boundary tests;
  encoded files remain limited to 64 MiB. The largest supported compressed fixture
  renders correctly with a normalized buffer no larger than 512,000,000 bytes.
  Actual peak RAM, including decoder/conversion overhead, is recorded and explicitly
  accepted before release; the approximately 500 MB buffer is not a peak-RAM claim.
- Workers access no widgets/models and never mutate a QImage after handoff. Stale
  images never reappear; one active/one pending bound holds across toggle cycles.
- Blocked loading does not hold up Qt shutdown/process exit or other windows.
  After retirement, off has no image thread, queued work or recurring activity.
- Artifact codec verification is recorded before release; development codecs and
  existing plug-in DLLs alone do not establish delivered format support.
- Design only until reviewed/implemented/tested. Record exact results and explicit
  deferrals for any unrun gates; stages 002/003 remain separate future work.

## Review Resolution

| Review item | Decision |
| --- | --- |
| 1. No preview focus | Superseded by user's Tab-focus requirement. One canvas takes focus; ordinary commands explicitly focus source before dispatch. No global focus-owner override. |
| 2. Hide instead of restore | Preserve the no-restoration goal, but supersede stacked pages with a sibling overlay. No layout/parent/focus-proxy changes. |
| 3. Allow hidden navigation | Adopt covered navigation. Neither navigation nor programmatic focus is intercepted; Tab is handled by the session-aware SwitchPanes command/local canvas. |
| 4. One ThreadPoolExecutor | Reject the literal proposal: pending work is unbounded and interpreter exit joins workers. Use one small daemon mailbox loader per window, no generic scheduler/weak-session registry. |
| 5. Return QImage | Adopt exclusive handoff; remove RGBA transport copies, stride validation and retained backing bytes. |
| 6. QAbstractScrollArea | Adopt; retain the one-line physical-origin rounding at 100%. Disabling smoothing and positioning pixels are separate concerns. |
| 7. Defer later-stage machinery | Adopt. Only the small renderer boundary remains here; existing 002/003 focus assumptions must be revised before those stages proceed. |
| 8. Dim old content while loading | Keep blank-on-change: simpler identity and lifetime rules, no old buffer alongside the new decode. |
| Approval follow-up notes | Normalize image format once in loader and name automatic-fallback disabling; consolidate pan commands. Retain delivery acknowledgement: a one-slot request mailbox alone does not bound already-emitted Qt results. |
| Minimum workflow impact | Existing host behavior is a constraint, not an invitation to add global protection/routing. Validate the placeholder overlay and ordinary command handoff before implementing image I/O. |
| 2026-09-21: no canvas binding recognition | Adopt. Local keys stay local; every other non-modifier key focuses source and calls Controller once, consuming even unbound input. Toggle uses that ordinary dispatch path. |
| 2026-09-21: exact geometry adapters | Adopt. Target Resize/Move/Show/Hide, splitter Resize/Move and splitterMoved; mapTo central on sync. Include panel layout and ancestor-only movement regressions. Never parent to Splitter. |
| 2026-09-21: explicit canvas traversal | Adopt. Canvas focusNextPrevChild returns False; keyPressEvent handles Tab/Backtab, with no custom ShortcutOverride or parent-chain dependency. |
| 2026-09-21: user-approved image capacity | Double each axis: 65,536-pixel edge and 128 MP area, with a 512 MB (about 488 MiB) normalized buffer. Keep the 64 MiB encoded-file limit and bounded loading. Supersede the old peak target; measure and obtain acceptance of actual peak RAM separately. |

Design checks on 2026-09-20: native Qt mouse clicking a NoFocus button preserved
source focus; a worker-created QImage remained valid after handoff; a device-backed
PNG decoded after content detection and explicit format pinning. An event-blocked
executor accepted 200 pending jobs with `max_workers=1`; a separate child remained
alive after `shutdown(wait=False)` and was killed/reaped by the probe. These are
API/design probes, not implementation tests or portable-codec certification.

Follow-up native Qt probes: a non-layout overlay accepted Tab/backtab/click/Escape,
resized and retained covered widget state. On 2026-09-21, a central-widget sibling
overlay using the existing `MainWindow._on_focus_changed` retained source status
ownership. Unchanged `PluginSupport.get_active_pane()` returned none on the canvas
and the source after explicit source-focus handoff. Run as an in-memory Qt probe
via `python -` and a child interpreter using `build._environment()`; no application
files changed. This validates the focus primitive, not real application shortcuts,
Command Center, overlay geometry across docks, or all lifecycle paths. Those remain
the placeholder-stage gates above. The earlier NoFocus approval does not cover
this revision.

2026-09-21 simplification check: an in-memory probe piped to `python -` launched
a child with `build._environment()` and `QT_QPA_PLATFORM=windows`. A canvas under
a plain QWidget passed Tab/Backtab/Escape and modifier/local-key focus checks with
`focusNextPrevChild` returning `False` and `keyPressEvent`, without custom
ShortcutOverride. Actual `Controller.handle_shortcut` with recording command stubs
passed first-binding precedence, pane/application/toggle dispatch and unbound-key
consumption without delivering keys to either list. Exact target/splitter adapters
passed panel show/hide, splitter-only movement with no target Move event,
splitterMoved and target show/hide. Both real pane children remained in place.
These are design probes, not real Command Center/file-operation tests or production
overlay lifecycle validation; the planned application gates remain required.

2026-09-21 capacity validation: a no-allocation PowerShell check verified doubled
axes produce 128 million pixels and 512,000,000 bytes (488.28125 MiB). Eight
dimension cases passed: the exact/over-area pair, both orientations of exact/over
edge, an over-area maximum-edge square and a zero dimension. The independent
64 MiB encoded-file conversion is 67,108,864 bytes. Document limit consistency,
relative links and append-only reviewer history passed. No 128 MP image was
allocated or decoded; actual peak RAM and large-image rendering remain unverified.

Documentation validation: `git diff --check -- Plan/QuickView001.md`, required
section checks, relative-link targets and append-only comparison against the full
pre-edit reviewer history, including the restored record. No application,
dependency, changelog, README or other stage-plan edits in this review response.

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

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Not approved as written; a simplification pass is requested. Review
  brief from the user: prefer the simplest robust design over runtime efficiency.
  Checked against the code: `Ctrl+Q` is free on Windows (only the Linux bindings
  use it); `DirectoryPaneWidget` sets `setFocusProxy(self._file_view)` and
  `PluginSupport.get_active_pane()` is `widget.hasFocus()`, so any focusable
  viewport child makes the active pane `None` for every pane command;
  `MainWindow._on_focus_changed` promotes whichever pane `isAncestorOf` the
  focused widget; the packaged artifact already ships `qjpeg`, `qgif`, `qico`,
  `qtiff`, `qwebp`, `qsvg`, `qtga`, `qwbmp`, `qicns` (no BMP/PNG plug-in needed,
  they are built in). Findings, in priority order:
  1. **Viewport never takes keyboard focus.** Give every viewport widget
     `Qt.NoFocus`. Keyboard focus stays in the source file list for the whole
     session; interaction is mouse (drag, wheel, Ctrl+wheel, toolbar buttons) plus
     ordinary pane commands (`quick_view_fit`, `quick_view_actual_size`,
     `quick_view_zoom_in/out`) that users may bind. This deletes **Focus
     QuickView**, the Escape/Tab traversal rules, the "scoped preview-owner rule"
     in controller/active-pane lookup, "shortcuts never fall through to the hidden
     target", and "toggle while preview controls have focus". Nothing in
     `get_active_pane()` or `MainWindow` changes.
  2. **Hide, do not restore.** State the invariant once: the target pane's model,
     view, filter bar and location bar are only hidden (a `QStackedLayout` page
     over the existing `Layout`), never modified, so there is nothing to capture
     or restore. Drop the restoration list and its tests in favour of one check:
     hide then show, `get_path`/cursor/marks/sort/column widths identical.
  3. **Do not intercept target navigation.** Remove "programmatic target
     focus/navigation closes QuickView before performing the action". Let the
     hidden pane navigate; the user sees the result on close. The only close
     triggers: the toggle, `DirectoryPaneWidget.focus()` on the hidden target
     (so `Tab`/`switch_panes` closes then focuses, one hook), source or window
     close.
  4. **One executor, generation check, no slot bookkeeping.** Replace the
     "one running/one pending job, retiring slot, weak-session late-result
     service" contract with a module-level `ThreadPoolExecutor(max_workers=1)`;
     each job first compares its generation with the session's current one and
     returns early if stale; results arrive via `run_in_main_thread` and are
     checked again. Cancellation is "ignore the result". Qt never joins the
     executor; no shutdown wait.
  5. **Pass a `QImage`, not bytes.** `QImage` is explicitly usable off the GUI
     thread (only `QPixmap` is not) and is neither a widget nor a model. Decode in
     the worker with `QImageReader(device)`, `setDecideFormatFromContent(True)`,
     allowlist check on `imageFormat()`, `setAutoTransform(True)`, `read()`,
     `setDevicePixelRatio(1)`; return the `QImage`. This removes stride/length
     validation, the retained-bytes lifetime rule and one full-size copy.
  6. **Use `QAbstractScrollArea`.** Scrollbars, pan range and wheel handling come
     for free; paint in `viewport()` with `QPainter.setTransform` + `drawImage`,
     so no zoom-sized buffers exist. Keep physical-pixel 100% and Fit formulas;
     drop the "align origin to physical pixel boundaries" clause, disabling
     smoothing at 100% is enough.
  7. **Move stage 002/003 contracts out.** Helper-process-per-window,
     video-to-text transitions, private worker dispatch and libmpv/Pygments
     dependency rows belong in QuickView002/003. Stage 001 should only define the
     renderer interface: `load(request) -> result` off-thread, `show(result)` and
     `dispose()` on the Qt thread.
  8. **Loading state without blanking.** Keep the 100 ms single-shot timer, but
     update the name/metadata label immediately and dim the previous image with a
     "Loading…" overlay instead of clearing it; blank only on error, folder,
     unsupported or empty cursor. Same "never a stale image under a new name"
     guarantee with far less flicker; if the user prefers the blank rule, keep it,
     but it is not required for correctness.
  Keep as is: file 64 MiB / edge 32,768 / 32 MP limits, allowlisted handlers with
  content sniffing, off-on-start, lazy `QuickView.json`, `Ctrl+Q`, source-cursor
  following with `location_loaded` gating, the `cursor_changed` signal added to
  `DirectoryPaneWidget` beside its existing `selectionChanged` hookup.
  Editorial: the `### Commands and Manual Gates` heading and the Implementation
  Steps / Acceptance Criteria lists are indented inconsistently; the PowerShell
  block has a stray leading indent on its third line. With items 1-7 applied, the
  Tests section should shrink accordingly before implementation starts.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Approved for implementation. The revision adopts items 1-3 and 5-7
  (NoFocus viewport, `QStackedLayout` hide/show with no restoration, no navigation
  interception, `QImage` handoff, `QAbstractScrollArea`, later-stage machinery
  moved out) and the code paths it leaves untouched (`get_active_pane`,
  `MainWindow._on_focus_changed`, controller dispatch) match the source. The
  rejection of item 4 is correct: `concurrent.futures` registers an interpreter
  exit hook that joins pool workers regardless of `shutdown(wait=False)`, so a
  blocked native read would hang exit; a per-window daemon thread with a
  one-slot mailbox is the simpler robust choice. Keeping blank-on-change
  (item 8) is accepted. Referenced regressions (`MainWindowIT`, `FilterBarIT`,
  `fman_unittest.impl.test_status_bar`) exist. Non-blocking notes for the
  implementer:
  1. "Keep the decoded format, without an unconditional RGBA conversion" trades
     one conversion for a hidden per-paint one: the raster engine converts
     `Indexed8`, `Grayscale8`, `RGB888` and similar sources on every
     `drawImage`, i.e. an image-sized temporary per repaint while panning.
     Convert once in the loader to `Format_ARGB32_Premultiplied` when
     `hasAlphaChannel()` else `Format_RGB32`; simpler rule, no paint-time
     buffers, and the 32 MP budget already assumes 32-bit pixels.
  2. The delivery handshake ("do not start the next decode until the result is
     accepted/discarded") is optional. With a one-slot mailbox the worst case
     without it is displayed + one undelivered + one decoding; if that bound is
     acceptable the condition round-trip can be dropped.
  3. Eight image commands is fine; folding the four pan commands into one
     `quick_view_pan` with `direction`/`large` arguments is an option if Command
     Center noise matters.
  4. When the format is pinned after detection, also call
     `setAutoDetectImageFormat(False)` so a pinned handler that fails cannot fall
     back; the text says this in prose, the step list should name the call.

### 2026_09_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Applied the simpler image-stage design: NoFocus mouse controls and
  bindable pane commands, hide/show pages, one target-focus hook, QImage handoff
  and QAbstractScrollArea. Removed global focus routing, restoration and future
  process/dependency machinery; aligned tests and fixed list/command formatting.
  Runtime probes disconfirmed the proposed executor's queue/shutdown assumptions,
  so retained bounded latest-only daemon loading with queued delivery. Kept
  blank-on-change and physical-origin rounding as small correctness safeguards.
  Earlier review history is unchanged. Stages 002/003 need their own focus review;
  this revision is ready for re-review, not application implementation approval.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Refined the user's overlay/Tab request around a strict integration
  boundary: non-layout central-widget sibling, enabled-only adapters, one
  SwitchPanes session branch and real source-focus handoff for ordinary shortcuts.
  Removed proposed global active-pane/status overrides and aligned controls,
  alternatives, runtime effects and test gates. A native probe exercised unchanged
  host focus/lookup methods successfully. Preserved all earlier records; approval
  of the previous NoFocus design is superseded. Design only, pending review and
  application tests; codec, memory, blocked I/O and plug-in focus risks remain.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: Medium
- Context Window: 1M
- Outcome: Restored record. This review of the NoFocus/stacked-page revision was
  appended on 2026_09_21 and dropped when the file was rewritten from an older
  copy; reviewer history is append-only, so it is re-recorded here in short form.
  It approved that revision against the low-risk goal, inventoried the touched
  code (`DirectoryPaneWidget` layout and `focus()`, Core registrations, one
  binding) and recommended an overlay child plus event filters over a
  `QStackedLayout` to avoid adapting `set_status_widget`, `FilterBar.reposition`
  and `resizeEvent`. That approval is superseded by the overlay/Tab revision
  reviewed below.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Approved with simplifications. The overlay/Tab revision keeps the
  low-risk goal: existing code changes are Core registrations, one binding and
  one session branch in `SwitchPanes`; `widgets.py`, `controller.py` and
  `plugins/__init__.py` stay untouched. Verified against the source:
  `MainWindow` uses a plain `QWidget` central container with a `QVBoxLayout`
  holding the `Splitter` and the optional `PanelDock`, so a non-layout child of
  `centralWidget()` is feasible (it must never be parented to the `Splitter`,
  which adopts child widgets as panes); `MainWindow._on_focus_changed` only
  promotes a pane that `isAncestorOf` the focused widget, so a sibling canvas
  leaves the source active; `MainWindow.focusNextPrevChild` already returns
  `False`, so Tab/Backtab reach the canvas `keyPressEvent` with no extra
  traversal or `ShortcutOverride` handling; `Controller.handle_shortcut(
  pane_widget, event)` is the complete binding-to-command dispatch used by the
  file list. Simplifications requested before implementation:
  1. **No binding recognition in the canvas.** Drop "the overlay adapter
     recognizes bindings using existing sanitized settings and key-matching
     utilities" and "recognize toggle by command identity". The canvas handles
     its local keys (Tab, Shift+Tab, Escape, F, 1, +, -, arrows); for any other
     key it focuses the source list and calls
     `Controller.handle_shortcut(source_widget, event)`, consuming the event if
     that returns `False`. The toggle then runs as an ordinary command on the
     source pane and closes the session; Command Center sees a focused pane.
     Zero binding logic lives in QuickView.
  2. **Geometry sync is the one real integration risk.** A pane receives no
     `Move` event when the splitter shifts inside the central widget (panel dock
     opened/closed), so filtering the target alone is insufficient. State the
     exact set: event filter on the target pane (`Resize`, `Move`, `Show`,
     `Hide`), on the splitter (`Resize`, `Move`) and `splitterMoved`; recompute
     with `target.mapTo(central, QPoint(0, 0))`. Keep the "panel open/close"
     test as the regression for this.
  3. `focusNextPrevChild` on the canvas should return `False` explicitly rather
     than rely on inheritance from `MainWindow`, so the behaviour does not
     depend on the parent chain.
  Accepted as designed: sibling overlay instead of a pane child (status-bar
  ownership and active-pane lookup unchanged), canvas focus via `switch_panes`,
  covered navigation without interception, per-window daemon mailbox with
  delivery acknowledgement, one-time `RGB32`/`ARGB32_Premultiplied`
  normalization, consolidated `quick_view_pan`, `setAutoDetectImageFormat(False)`.
  Residual note: a focused canvas makes `get_active_pane()` return `None`, the
  same situation as a focused bottom panel today; documented, not patched.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Incorporated all three requested simplifications: no QuickView binding
  recognition, exact target/splitter geometry adapters and explicit canvas focus
  traversal. Unbound non-local input now hands focus to source before Controller
  dispatch; the canvas consumes unbound events. Modifier-only presses retain focus
  for local chord/mouse controls. Native input/Controller and geometry probes passed.
  Aligned input, implementation and acceptance gates; preserved the restored and
  subsequent reviewer records. Design only; application implementation, native
  workflow regressions and release gates remain pending.

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Applied the user's approximate 500 MB per-image allowance by doubling
  each dimension limit: 65,536 pixels per edge and 128 million pixels total,
  yielding at most 512,000,000 bytes of normalized 32-bit pixel storage. Kept the
  independent 64 MiB file limit and existing isolation/concurrency design. Updated
  boundary/performance tests and required measured peak-RAM acceptance rather than
  promising a 500 MB process cap. Prior reviewer history is unchanged; design only,
  with actual large-image decode, memory and rendering checks still pending.