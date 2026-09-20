# QuickView 002: Videos

## Task

Extend the viewport from [stage 001: initial design and images](../Done/QuickView001.md)
with local video preview and explicit playback. Images continue to work unchanged.
No additional pane, viewer window or video-specific toggle.

Status: proposed design; backend/packaging feasibility must pass before implementation
is accepted. No dependencies are installed by this task document.

## Scope

- Windows local/UNC regular video files under the shared location policy.
- Initial containers: MP4/MOV, MKV/WebM, AVI, MPEG/TS and WMV/ASF. A container suffix
  does not guarantee codec support. The tested runtime defines the supported matrix.
- Required codec fixtures: H.264/AAC in MP4 and VP9/Opus in WebM; test silent video
  too. HEVC, AV1 and other combinations are conditional, never assumed from suffix.
- First frame paused/muted, embedded Play/Pause, seeking, elapsed/duration, mute
  and volume. Fit with preserved aspect ratio/rotation; no crop by default.
- Exclude autoplay, playlists, streaming URLs, discs, audio-only viewing, external
  subtitles, downloading, recording, thumbnails-on-disk, fullscreen and editing.
- Shared focus/restoration and public `fman` plug-in API remain unchanged.

## Design

### Dependencies and Delivery

| Dependency | Decision |
| --- | --- |
| Stage 001 shared foundation | Hard dependency for requests, focus, presentation and teardown. |
| Stage 001 images | Delivery/regression prerequisite; video does not call the image decoder. |
| Qt widgets/process support | Existing PyQt5; native container and nonblocking `QProcess`. |
| python-mpv | New binding; upstream PyPI distribution is `mpv`, imported as `mpv`. |
| libmpv | New matching Windows native DLL plus its transitive runtime libraries. |
| FFmpeg libraries | Transitive through the selected libmpv build; no separate `ffmpeg.exe`/`ffprobe.exe` requirement. |
| Windows process cleanup | Existing pywin32 for a kill-on-close Job Object; no registry writes. |

[python-mpv](https://github.com/jaseg/python-mpv) documents ctypes/libmpv loading,
callbacks from an event thread, Qt embedding and an `LC_NUMERIC=C` requirement.
[mpv's embedding API](https://mpv.io/manual/stable/#embedding-into-other-programs-libmpv)
and [window embedding](https://mpv.io/manual/stable/#options-wid) support native
window parenting. Yazi's FFmpeg thumbnails are an experience reference, not this
playback backend.

The [environment](../environment.yml) does not yet declare this binding/runtime.
Before coding against it, obtain user approval/installation, select a maintained
Windows build, pin the Python package and native artifact/checksum, and verify
Python 3.14, process architecture and client-API compatibility. Availability from
the configured conda channel is not assumed. Document any approved alternate
artifact source; never download codecs automatically at runtime.

The binding follows the underlying libmpv license (GPL by default, LGPL for an
appropriate build). Audit actual mpv/FFmpeg build flags and every bundled dependency;
do not infer LGPL status from the DLL name. Distribution notices/source obligations
and the codec matrix are release gates. Prefer a verified LGPL-compatible runtime
where feasible; an incompatible license or unavailable supported binary blocks
this stage, not image/text viewing.

Extend [packaging](../RoyiFileManager.spec) only during implementation. Bundle the
pinned runtime in an application-owned directory and make the helper resolve it
explicitly, never from the viewed directory, current working directory or arbitrary
PATH entries. Test the binding's loader against that policy; do not assume
`os.add_dll_directory` alone overrides its ctypes lookup. Missing/wrong-architecture
libraries produce an inline unavailable-backend state, not startup failure.

### Playback and Controls

- On a stable cursor request, open only that file and decode its first frame while
  paused and muted. Play is explicit. New files always reset position, pause and
  mute; preference volume can persist through shared settings, never playback history.
- Play/Pause icon and Space work only within preview focus. Left/Right seek 5 seconds;
  Shift+Left/Right seek 30 seconds, clamped to available duration. Home seeks to zero.
- A time slider shows elapsed/duration; coalesce drag updates and send the final
  requested position on release. Unknown duration/nonseekable media disables seeking.
  Keep paused seeks silent and show the resulting frame without resuming playback.
- Mute icon/`M` and 0%-100% volume slider control this player, never system volume.
  No audio device means video can continue with an explicit audio-unavailable state.
- EOF pauses on the last frame; Play at EOF restarts from zero. No repeat or auto-next.
- Changing cursor invalidates, hides and stops the old video immediately, before
  the shared debounce. Minimize/hide pauses; restoring does not resume automatically.
  Escape/Tab/toggle follow shared rules. Merely returning focus to the source need
  not stop explicitly started playback while that same video remains visible.

### Ownership, Process and Cancellation

The Qt-thread adapter owns toolbar, native video container and process lifecycle.
One on-demand helper owns libmpv; it draws a native child window parented to the
container HWND captured on the Qt thread. The helper receives only plain request
data and the numeric handle, never Qt widgets/models. Controls remain Qt siblings
of the video surface, not overlays on a foreign native window.

Use the current interpreter plus a fixed internal worker module in source mode;
the frozen executable needs an early, private worker dispatch before normal app,
plugin and session startup. It must not create another file-manager window or read
normal application settings. The helper alone sets `LC_NUMERIC=C`; the host locale
is unchanged. Reuse this small lifecycle boundary for later bounded helpers, not
a general external-preview plugin framework.

- At most one helper/player per window, including a retiring one. Each new video
  uses a fresh process; do not start it until the previous helper exits. Latest-only
  pending requests prevent a process storm during browsing.
- Parent/helper communicate with bounded, versioned JSON lines over private stdin/
  stdout, using a real JSON parser. Include session/generation/request IDs; limit
  messages to 64 KiB and diagnostic retention to 64 KiB. No shell or public IPC server.
- Allow only fixed load/play/pause/seek/volume/stop operations. Load uses an absolute
  validated filename as a separate libmpv argument, not a command string. Callback
  threads publish plain events to one serialized writer; the host applies events
  only on Qt after generation/ownership checks.
- Attach the process to a kill-on-close Windows Job Object before authorizing media
  load. The helper exits on control-pipe EOF; job ownership prevents orphan playback
  if the host crashes. Do not start a player if cleanup ownership cannot be established.
- Stop/dispose sends an asynchronous stop/quit request. After 500 ms without exit,
  terminate the helper; escalate to job termination within 2 seconds. Keep the native
  parent alive until exit, including when closing a window. Never join or wait for
  player termination on Qt or from the libmpv callback thread.
- Initial load has a 10-second deadline, stopped on success; timeout disposes the
  helper and offers inline Retry. No automatic crash/retry loop. All deadline timers
  are one-shot and exist only while a request/teardown is outstanding.
- Disable mpv keyboard/mouse bindings and prevent its child from stealing focus.
  Native Windows tests must prove mouse, Tab, toggle and Command Center routing.
  If native embedding cannot meet the shared contract, revisit rendering through
  libmpv's render API before accepting this stage; no detached-player fallback.

### Input and Failure Policy

Configure the pinned backend before initialization: no ambient/user configuration,
scripts/auto-profiles/youtube-dl, external subtitles/audio/cover art, playlist creation,
resume history, disk/shader caches, screenshots or global media-key capture. Disable
reference following (`access-references=no`, `autoload-files=no`) and restrict
FFmpeg protocols to local file input; reject playlist/manifest/script demuxers even
when renamed to a video suffix. Verify required safety options on the pinned runtime;
an unsupported option fails closed instead of silently weakening the policy.

UNC access to the explicitly selected file is allowed; HTTP or linked media fetches
are not. Instrument malicious reference/playlist fixtures for secondary file/network
access. These controls and process isolation are not a security sandbox against
native codec vulnerabilities; untrusted media still requires maintained binaries.

Missing/changed files, unsupported codec, corrupt data, timeout and crashed backend
clear the surface and show distinct shared inline states. Release file locks on
switch/close; do not claim a pause releases them. Cap forwarded diagnostics and
escape metadata as plain text. Image viewing remains available after video failure.

## Alternatives

- Qt 5 Multimedia: no extra Python binding but Windows codec/backend availability
  is machine-dependent; choose a pinned media runtime for a reproducible codec matrix.
- Direct in-process libmpv: simplest embedding, but codec crashes, blocking teardown
  and numeric-locale requirements affect the file manager. Pay helper startup cost
  only for an actively requested video.
- mpv executable/JSON IPC: avoids the Python binding, but adds executable/IPC-server
  handling. The private helper provides isolated locale and controlled lifetime
  without exposing mpv's unrestricted IPC command surface.
- FFmpeg thumbnails only: closer to Yazi and lighter, but cannot provide the proposed
  playback interaction. No independent thumbnail subsystem in this stage.

## Runtime Effects

- Off or non-video: no library import/probe, helper, audio device, video timers or
  media reads. A bounded retiring helper is the sole teardown exception.
- Active: one helper, libmpv event thread and native decoder/render threads. Start
  with at most four software decode threads, 32 MiB forward/8 MiB back demux buffers,
  no disk cache and no whole-file buffering. Driver/decoder memory is additional.
- Hardware decoding may use a verified automatic backend with software fallback;
  do not scan devices before first use. Target 1080p/30 playback first; record 4K
  behavior rather than promising all resolutions/codecs are real-time.
- Coalesce progress updates to at most 4 Hz; no host recurring poll when paused.
  Native library idle behavior must be measured, not assumed zero CPU.
- Prototype budgets: first frame within 2 seconds for the local baseline fixture;
  parent heartbeat gaps below 100 ms; incremental helper working set below 512 MiB
  for 1080p. Record cold/warm, CPU, GPU and peak memory on the test machine. Budgets
  are acceptance targets, not guarantees for corrupt or slow-network media.

## Tests

Planned modules/classes, not implemented or run during design:

- `fman_unittest.test_quick_view_videos`: dependency/loader failures, fixed options,
  structured paths with spaces/Unicode, IPC limits, generation filtering, paused
  startup, slider coalescing, timeouts, bounded replacement and forced cleanup.
- `fman_integrationtest.test_qt.QuickViewVideosIT`: fake event-gated helpers for
  focus/ownership/error paths plus real pinned-backend fixtures for frame pixels,
  playback, paused seeking, EOF, resize, minimized pause, audio mute and file unlock.
- Crash/stall a test helper; close/reopen rapidly and verify one helper maximum,
  zero orphan processes and bounded close latency. Prove the host locale is unchanged.
- Reject disguised playlists and reference media; assert no secondary media reads,
  network requests, user mpv configuration/scripts, registry writes or disk caches.
- Repeat image/video switches 200 times; measure CPU/memory/process counts and
  shared responsiveness. Real-backend tests may skip only when the dependency is
  absent, with an explicit reason; such skips do not satisfy the video release gate.

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_quick_view', 'fman_unittest.test_quick_view_videos', '-q'], env=build._environment(), timeout=120).returncode)"
$env:QT_QPA_PLATFORM = 'windows'
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.QuickViewIT', 'fman_integrationtest.test_qt.QuickViewImagesIT', 'fman_integrationtest.test_qt.QuickViewVideosIT', '-q'], env=build._environment(), timeout=180).returncode)"
```

Manual source procedure: `python build.py run` with disposable
`ROYIFILEMANAGER_USER_SETTINGS`; both source sides, muted first frame, Play/Pause,
seek/end/restart, another file, toggle/close and 100%/150%/200% display scaling.
Release smoke uses an authorized portable artifact with development PATH/Qt removed:
verify DLLs/codecs, private helper dispatch, no console flash, no second app instance,
Job Object cleanup and missing-DLL failure. Do not invoke freeze automatically.

## Implementation Steps

1. Review stage 001 integration; approve/install/pin dependencies and licenses.
2. Prototype the native child, focus, locale and helper cleanup using baseline
   fixtures; stop and revise this design if any hard gate fails.
3. Add backend policy/lifecycle unit tests; run the focused module immediately.
4. Wire the video adapter/controls and source/frozen worker dispatch; run native Qt
   and image/shared regressions, including crash and stale-event cases.
5. Measure budgets and verify dependency collection; run artifact smoke only when
   authorized. Update README/CHANGELOG and record exact results/remaining release gates.

## Acceptance Criteria

- Same viewport/toggle; image support and both directory pane identities are unchanged.
- Baseline codecs display an actual paused/muted frame, play only explicitly, seek
  correctly, and release locks/processes on replacement/close.
- Focus, native-window lifecycle, host locale, stale rejection and bounded helper
  cleanup pass tests; no off-path player work or automatic external access.
- Approved dependency pins, provenance/checksums, licenses and tested codec matrix
  are recorded before delivering video support; portable smoke is a release gate.
- Missing video dependencies degrade inline without disabling other renderers or
  changing the public `fman` plug-in API.

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