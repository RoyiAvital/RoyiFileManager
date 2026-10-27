# QuickView 006: Videos

## Task

Play local video files in the QuickView viewport, with minimal controls. Split
from [QuickView002](QuickView002.md) on 2026_10_27, which now covers animated
images only.

Status: Waiting for [PyQt6 Migration](PyQt6Migration.md). Not started.
Qt 5 plays video on Windows through DirectShow or Media Foundation, whose codec
support depends on the machine; Qt 6 Multimedia uses FFmpeg. Video written for
the Qt 5 API would also need a rewrite during the migration. Start this task
only after the migration is delivered, as its first QuickView feature.

## Scope

- Local and UNC regular files under the existing QuickView local-file policy.
- Candidate suffixes: MP4/MOV, MKV/WebM, AVI, MPEG/TS, WMV/ASF. What plays depends
  on the Qt 6 FFmpeg backend, not the suffix.
- Controls: Play/Pause, seek slider with elapsed/total time, Mute. Aspect ratio is
  kept with letterboxing.
- Excluded: autoplay, volume slider, extra seek shortcuts, playlists, streaming
  URLs, subtitles, fullscreen, audio-only files, external players, persistence.
- Public `fman` plug-in APIs and image preferences stay unchanged.

## Design

- Qt 6 `QMediaPlayer` with `QAudioOutput` and `QVideoWidget`, created lazily on
  the Qt thread in a new `fman.impl.quick_view_videos` module and shown in the
  overlay's existing stacked content area. Image controls are hidden for video.
- The existing debounced loader resolves the selection off Qt and returns a plain
  `kind='video'` result (path, fingerprint). Workers never create multimedia objects.
- Each file starts paused at zero and muted; Play is explicit. Space toggles
  Play/Pause, `M` toggles Mute. The slider seeks once on release and is disabled
  when the media is not seekable. End of media stops; Play restarts from zero.
- One player per accepted file. On selection change, close or window teardown:
  stop, disconnect, clear the source and delete the player, so the file is
  released. Signal handlers check the request generation and ignore retired players.
- Errors (missing backend, unsupported codec, read error) show inline; selecting
  another file recovers. Image preview keeps working.
- In-process playback: a backend crash or blocking teardown can affect the
  application. No sandbox or hard cancellation is claimed.

## Alternatives

- **Qt 5 QMediaPlayer now:** rejected; machine-dependent codecs and an API that
  changes in Qt 6.
- **libmpv, helper process or external player:** rejected; extra runtime, IPC and
  native window handling.
- **Full control set (volume, 30 s jumps, timeout state):** deferred; not needed for
  a preview.

## Runtime Effects

- No multimedia import, player or audio device until the first video is selected.
- While a video is shown: one player, Qt-owned decoding/audio threads and buffers.
- Nothing is preloaded or persisted; switching files releases the player and file.

## Tests

- Unit (fake player): lazy creation, no autoplay, muted start, stale-signal
  rejection after replacement, single seek on slider release, disposal order.
- Qt integration with generated MP4 fixtures (moving colors, with and without
  sound): frames change after Play, Pause/seek/EOF, Mute, file unlock after
  switch and close, inline error for a corrupt file, image preview unaffected.
- Portable smoke: MP4 and silent MP4 playback in a frozen build without extra codecs.

## Implementation Steps

1. Wait for the PyQt6 migration; confirm FFmpeg-backed playback of a generated MP4.
2. Add the video result kind and player view with unit tests.
3. Wire the view into the session; add Qt integration tests.
4. Verify PyInstaller collects the multimedia plug-ins; run the portable smoke.
5. Update docs and CHANGELOG.

## Acceptance Criteria

- MP4 plays visibly in source and portable builds; Play is explicit and audio
  starts muted.
- Switching files or closing QuickView releases the player and the file lock.
- Unsupported media fails inline; images, text, PDF and tables are unaffected.

## Reviewers

### 2026_10_27 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Split video from QuickView002 by user request with a reduced control
  set (Play/Pause, seek, Mute). Blocked on the PyQt6 migration because Qt 5
  Windows video depends on machine codecs and a different API. Earlier Qt 5
  and libmpv designs remain in QuickView002's reviewer history.
