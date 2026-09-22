# QuickView 002: Videos

## Task

Add video playback to the existing QuickView viewport using Qt Multimedia only.
Keep the same toggle, pane ownership and focus behavior as
[stage 001: images](../Done/QuickView001.md); images continue to work unchanged.

Status: revised Qt-only design (2026_09_22); application implementation has not
started. This revision supersedes the libmpv/helper-process proposal preserved
in the reviewer history. No packages or codecs are installed by this task.

## Scope

- Windows local/UNC regular files under the existing local-file policy.
- Candidate suffixes: MP4/MOV, MKV/WebM, AVI, MPEG/TS and WMV/ASF. Actual codec
  support comes from the installed Qt/Windows backend, not the suffix.
- Embedded Play/Pause, seek slider, elapsed/duration, mute and volume. Preserve
  aspect ratio with letterboxing; no crop, custom rotation or video zoom controls.
- No autoplay, playlists, streaming URLs, discs, audio-only viewing, external
  subtitle support, recording, fullscreen, external-player fallback or editing.
- No mpv binding, libmpv, separate FFmpeg runtime, helper process, IPC or Qt upgrade.
  Public `fman` plug-in APIs and image preferences remain unchanged.

## Design

### Qt Components and Integration

Use the existing PyQt5 modules:

- `PyQt5.QtMultimedia.QMediaPlayer` owns loading, playback, seeking and audio.
- `PyQt5.QtMultimedia.QMediaContent` wraps `QUrl.fromLocalFile(path)`.
- `PyQt5.QtMultimediaWidgets.QVideoWidget` displays the video through
  `player.setVideoOutput(widget)` and `Qt.KeepAspectRatio`.
- `QToolButton`, `QSlider` and `QLabel` supply the controls. Use existing Qt style
  media icons, tooltips and accessible names; QVideoWidget is the display, not a
  ready-made playback toolbar.

Extend [QuickViewSession and QuickViewOverlay](../src/main/python/fman/impl/quick_view.py)
with one lazy video widget/controller in `fman.impl.quick_view_videos`. A stacked
content area selects the existing image canvas or video view; image controls
are hidden for video. Do not introduce a general plug-in renderer framework.

Retain the session's 100 ms debounce, cursor/content token and generation checks.
Extend the existing bounded loader in
[quick_view_images.py](../src/main/python/fman/impl/quick_view_images.py) to prepare
plain video-path results: resolve the selected URL and check a regular local file
off Qt, then return its path, generation and fingerprint. Video bypasses image
decoding and the image-only 64 MiB limit. Workers never create multimedia objects
or receive widgets. Recheck session ownership before accepting a prepared result.

Import Qt Multimedia only when the first valid video result is accepted. Parent
the player, video widget and controls to Qt-owned objects on the Qt thread. Qt
handles decoding, buffering and backend threads; application code does not read
frames, create decoding threads or manage native window handles.

### Playback and Controls

- Start at zero, muted, with no call to `play()` until the user asks. Request pause
  once loaded. If the backend provides a paused first frame, show it; otherwise
  show a ready state until Play. Do not briefly autoplay to manufacture a poster.
- Space toggles Play/Pause while the preview surface has focus. Left/Right seek
  5 seconds, Shift+Left/Right 30 seconds, Home to zero, clamped to duration.
  Seeking preserves paused/playing intent; never resume just to refresh a frame.
- Update elapsed/duration from Qt signals. Set the slider's tracking off and seek
  once on drag release; prevent position updates from fighting an active drag.
  Disable seeking for unknown duration or `isSeekable() == False`.
- Mute/`M` and a 0%-100% volume slider affect only this player. Retain volume only
  within the QuickView session; each new file resets to muted. No new persistence
  or playback history in this stage.
- End-of-media stops; explicit Play seeks to zero and restarts. Retaining the last
  frame and automatic orientation are backend-dependent, not new renderer features.
- Pause on hide/minimize; restoring never resumes automatically. Escape/Tab return
  focus to the source pane under the shared rules. Controls keep normal Qt keyboard
  behavior; video shortcuts must not hijack slider keys or source-pane commands.

### Lifecycle and Failure

`setMedia` loads asynchronously. Connect `mediaStatusChanged`, `stateChanged`,
`positionChanged`, `durationChanged`, `seekableChanged`, video availability and
`error` signals to the view. Use `setNotifyInterval(250)` for progress rather than
an application polling timer. Check media service availability and catch multimedia
import failures; neither may disable images or application startup.

- One player per accepted file, at most one active player per window. Bind every
  signal handler to that player and request generation, since Qt's signals do not
  carry the application's request ID. Ignore callbacks from retired requests.
- On cursor/content change, invalidate first, mute and hide the old video, stop,
  disconnect, clear with `setMedia(QMediaContent())`, detach its output and dispose
  on Qt. Do this before the shared debounce, not when the next video finishes
  loading. Serialize replacement through Qt destruction; retain only the latest
  pending request, including across toggle/close/reopen. No nested event loop.
- Session close, owner unload and window destruction use the same cleanup path.
  An unchanged selected file must not restart because of an unrelated model reset.
  Pause alone is not cleanup; verify file unlock after clearing/replacement.
- A single-shot 10-second loading deadline clears a stalled request and shows an
  inline timeout. It stops on load, error, invalidation or close; retry is explicit.
- Show inline unavailable-backend, unsupported/no-video, read/decode-error and
  timeout states using bounded plain-text errors. Silent video remains valid.
  Missing audio content is not proof of a missing audio device; do not infer it
  from `audioAvailableChanged`. Recover by selecting another file.

This is in-process playback. Qt/codec crashes or blocking native teardown can
affect the application; a Qt timer cannot interrupt a blocked backend. Do not claim
process isolation or hard cancellation deadlines. Test those costs before delivery
rather than restoring the rejected helper-process architecture automatically.

### Input and Failure Policy

Accept only resolved `file://` regular files, including the selected UNC path;
construct Qt URLs with `QUrl.fromLocalFile`, never parse user text as a media URL.
Reject directory, non-file provider and playlist/manifest selections. Never create
a `QMediaPlaylist`, download codecs or search for external sidecars in application
code. No environment/locale changes, global media-key registration or intentional
Registry writes.

Qt 5 does not expose libmpv-style protocol/demuxer restrictions. A local URL or
extension allowlist is not a sandbox against a disguised reference file or native
codec behavior. The old guaranteed no-secondary-access policy is not promised by
this simpler design. Include reference-file behavior in manual validation and
document backend limitations; do not silently add a custom demuxer or security layer.

### Delivery

No new Python dependency is expected: the installed Qt 5.15 environment already
provides both multimedia modules. Codec/backend availability still varies across
Windows machines. Target H.264/AAC MP4 and silent H.264 MP4 as release smoke cases;
WebM/VP9/Opus, HEVC, AV1 and other combinations are conditional. Record actual
source and portable results; `hasSupport()` and filename suffixes are not proof.

Verify PyInstaller collects QtMultimedia, QtMultimediaWidgets and the required Qt
media-service/plugin DLLs from the pinned environment. Adjust
[RoyiFileManager.spec](../RoyiFileManager.spec) only if necessary. Keep Qt/PyQt
distribution notices; no codec-pack installation, runtime downloads or system
configuration changes. Missing plugins/codecs degrade inline. A source-only
construction probe does not establish portable playback support.

## Alternatives

- **QMediaPlayer + QVideoWidget:** selected for direct Qt ownership and the existing
  runtime; accept backend-dependent codecs, poster behavior and in-process risk.
- **libmpv/helper or external player:** rejected by the user's Qt-only direction;
  extra dependencies, native embedding, IPC and process cleanup are unnecessary.
- **Custom Qt frame surface/Qt Quick scene:** more control but adds rendering and
  synchronization work without a current need. Use the dedicated widget instead.
- **Qt 6 migration:** separate task, not a prerequisite for Qt 5 video support.

## Runtime Effects

- Disabled/image-only startup: no multimedia import, service probe, player, audio
  device or video timer. After video use, imports may stay cached but the player
  is released; existing image workers remain unchanged.
- Active: one Qt player and widget, backend-owned decoder/render/audio threads
  and buffers. Qt chooses acceleration and buffering; no arbitrary thread/memory
  caps or zero-idle-CPU guarantees unsupported by the public API.
- Only the selected file loads after debounce. No recursive scan, preload cache,
  whole-file Python buffering, helper process or new persisted state.
- Diagnostic targets: 1080p/30 playback, first visible frame within 2 seconds of
  explicit Play, UI heartbeat gaps below 100 ms and incremental process peak below
  512 MiB on the reference machine. Measure cold/warm behavior, 4K and repeated
  switching separately. Backend cancellation cannot be forcibly bounded in-process.

## Tests

The new video test module/class below is planned, not implemented. Application
behavior tests belong in normal correctness verification; timing and long stress
runs remain separate developer diagnostics.

- Unit with a fake player: lazy creation, local-path preparation, stale player
  signals after replacement (including same-path reload), no automatic play,
  mute reset, state/position mapping, single seek on slider release, timeout,
  disposal ordering and failure recovery. Test disabled/non-video no-op behavior.
- Qt integration: both source sides, stacked image/video controls, Qt thread
  ownership, focus/shortcuts/slider keys, hide/minimize pause, rapid toggle and
  owner/window close. Preserve existing image rendering and selection behavior.
- Real Windows backend: small licensed/generated MP4 fixtures with known moving
  colors, sound and a silent variant. Verify visible changing frames, Play/Pause,
  paused seeks, EOF/restart, aspect ratio, audio mute and unlock by rename/delete
  after close. Loading signals alone do not prove visible video. Use a desktop
  capture if native video does not appear in QWidget grabs.
- Unsupported/corrupt/missing/disappearing files and unavailable media services
  must show inline errors and leave image preview usable. Record optional codec
  and environment skips explicitly; they do not satisfy portable smoke coverage.

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_view', 'fman_unittest.test_quick_view_images', 'fman_unittest.test_quick_view_videos'], env=build._environment(), timeout=120).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.QuickViewIT', 'fman_integrationtest.test_qt.QuickViewImagesIT', 'fman_integrationtest.test_qt.QuickViewVideosIT'], env=env, timeout=180).returncode)"
```

Manual source: run `python build.py run` with disposable
`ROYIFILEMANAGER_USER_SETTINGS`; exercise both panes, controls, fallback before
Play, 100%/150%/200% scaling, long/Unicode/UNC paths and permission/network errors.
Inspect rotated media and disguised references to document backend limitations.
Diagnostic stress: switch images/videos 200 times and record player count, file
locks, UI latency, paused CPU and memory growth; do not add this loop to CI.
Portable smoke: use an authorized artifact on Windows without development PATH/Qt
or extra codec packs; repeat MP4/silent playback, missing-backend behavior and
image recovery. Do not run freeze/package automatically.

## Implementation Steps

1. Review this Qt-only revision; prove visible MP4 playback with the installed
   backend, including stopped/paused first-frame behavior and file release.
2. Add focused player lifecycle/path/control tests, then implement the small
   Qt video view. Run each narrow test immediately after the corresponding edit.
3. Wire local-file preparation, media selection and stacked controls into the
   existing session; run video, image and shared focus regressions.
4. Verify Qt plugin collection and authorized portable playback; record codec
   limitations and run separate latency/memory/switching diagnostics.
5. Update usage docs and changelog for delivered behavior, record exact validation
   results and complete this task only after application and artifact checks pass.

## Acceptance Criteria

- Video uses only Qt Multimedia/QVideoWidget and existing application facilities;
  no separate player runtime, IPC, external window or new Python dependency.
- MP4 baseline visibly plays in source and portable builds. Play is explicit,
  initial audio is muted, seeking/EOF/focus behave as specified, and file locks
  release on replacement/close. A pre-Play frame is optional, not faked by autoplay.
- Image support, disabled-path cost, directory pane state and public APIs are
  unchanged; stale callbacks cannot revive a replaced video or closed overlay.
- Missing services and unsupported codecs fail inline. Tested formats, backend
  limits and measured runtime costs are recorded; no universal codec, sandbox
  or hard native-cancellation claim.

## Design Validation

- 2026_09_22: consulted Qt 5.15 documentation for
  [QMediaPlayer](https://doc.qt.io/archives/qt-5.15/qmediaplayer.html) and
  [QVideoWidget](https://doc.qt.io/archives/qt-5.15/qvideowidget.html).
- Existing-environment probe constructed QApplication, QMediaPlayer and
  QVideoWidget, attached video output, muted and cleared media. Qt 5.15.15 /
  PyQt 5.15.11 reported availability 0 (Available) and error 0 (NoError).
  No media was loaded or played; codec, frame, audio and packaged behavior remain
  unverified. No dependencies, application code or environment settings changed.

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