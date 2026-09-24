# Calculate File Hash

Status: Implemented and validated. Both commands show centered, panel-free
results; Calculate File Hash By first selects an algorithm in QuickSearch. See Implementation
Notes and Validation Results for the delivered behavior and checks.

## Task

Add a bundled `CalculateFileHash` plug-in with two Command Center commands:

- `Calculate File Hash` — computes the hash of the file under the cursor with
  the algorithm configured as default (`sha256` out of the box) and shows the
  result in a tool window using the new public `OutputTextBox` UI element.
  A small copy icon at the top left copies the complete hash.
  Default shortcut `Ctrl+H`.
- `Calculate File Hash By` — first lets the user pick the algorithm from a
  Quicksearch list, then computes and shows the result the same way.

Both commands share the hashing engine and centered result controller. `Ctrl+H`
uses the configured default; By selects the algorithm before hashing the captured
file. The window title/heading is the full path, and OutputTextBox's title is
`Hash Algorithm: <Algorithm>`. Neither command creates a Panel.

Expose `OutputTextBox` through `fman.ui` for other plug-ins: a read-only,
selectable plain-text output block with a built-in copy action, visually similar
to a web code block. Keep hash-specific actions out of this generic component.

Motivation: verifying downloads against a published checksum and producing a
checksum to share are common file-manager tasks; today they require a terminal
(`certutil -hashfile`, `Get-FileHash`). Total Commander offers *Create
checksum file* (`Files` menu) and *Verify checksums*; this plug-in covers the
interactive single-file case with a copy-first workflow.

## Scope

Included:

- Hashing the single file under the cursor on `file://` locations.
- Algorithms: `md5`, `sha1`, `sha256`, `sha384`, `sha512`, `sha3_256`,
  `sha3_512`, `blake2b`, `blake2s` via `hashlib`, plus `crc32` via `zlib`
  (upper-case 8-digit hex) because archive tools publish it.
- Configurable default algorithm; the `Calculate File Hash` command also
  accepts an `algorithm` argument from a custom key binding.
- Reusable `OutputTextBox` with a top-left copy button; both commands show the
  plain digest in the same centered result window beneath the file-path heading.
  Algorithm selection belongs to the By command's QuickSearch wizard.
- Progress dialog with cancellation for large files (through the existing
  `Task`/`submit_task` mechanism).
- Detection of files whose size or modification timestamp changes while they
  are being hashed; no potentially stale digest is presented.
- Optional automatic copy to the clipboard on completion (`auto_copy`).

Excluded:

- Multiple files, directories, checksum-file creation (`.sha256`) and
  verification of checksum files; non-`file://` schemes (`zip://`,
  `network://`) — the commands are hidden there. These can be later tasks.
- Clipboard/expected-digest comparison and labeled/checksum-line copy formats
  are deferred. The initial result UI has no comparison field or Copy As menu.
- Changes to the legacy fman 1.7.5 API, general Window/DirectoryPane widget
  exposure, and a new windowing or docking framework.
- Rich text/HTML/Markdown rendering, syntax highlighting, editing, live log
  streaming, file loading/saving, and settings persistence in `OutputTextBox`.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
new export is the additive, provisional `fman.ui.OutputTextBox`. The existing
`set_panel` API also accepts `None` to detach a panel without closing its tool.
The plug-in uses public APIs, including `fman.ui`, without importing host
internals. Removing the plug-in removes its commands, not the shared control.

## Design

Plug-in layout `Plugins/CalculateFileHash/`:

- `calculate_file_hash/__init__.py` — the two commands and the result window
  orchestration.
- `calculate_file_hash/hashing.py` — pure Python: algorithm registry,
  safe default selection, and chunked hashing with progress/cancel callbacks.
  No Qt or `fman` imports; the hashing function receives
  `report(bytes_done)` and `check_canceled()` callables so it is unit-testable
  without fman.
- `calculate_file_hash/ui.py` — `UiController` composition and a plain result
  session; no hashing loop in Qt callbacks.
- `CalculateFileHash.json` — settings defaults.
- `Key Bindings (Windows).json` — `Ctrl+H` → `calculate_file_hash`.
- `README.md`.

### OutputTextBox

Add the generic implementation under `fman.impl.ui.output` and re-export it
from [fman.ui](../src/main/python/fman/ui.py), including `__all__`. Follow the
[shared UI design](../Plan/UIElements.md) and existing
[component conventions](../src/main/python/fman/impl/ui/panel.py). This replaces
the older QuickList-based hash-result sketch for this consumer.

Public contract:

| API | Behavior |
| --- | --- |
| `OutputTextBox(text='', parent=None, *, title='')` | Construct a Qt-owned output widget with an optional plain-text title beside Copy. Existing positional arguments are unchanged. |
| `set_title(title)` / `title()` | Set/get the complete string title on Qt. Elide long display text with a full-title tooltip; never include it in copying. |
| `set_text(text)` | Replace the complete output; require `str`, reset selection/scroll, and update copy availability. |
| `text()` | Return the original string supplied by the caller. |
| `copy_text()` | Copy the entire current string, regardless of selection; empty text leaves the clipboard unchanged. |
| `copied` | No-argument Qt signal after a nonempty copy action, for caller-owned feedback. |

Keyboard contract: unmodified Return or keypad Enter with focus in the text
invokes `copy_text()` exactly once and consumes the event. This behavior belongs
to OutputTextBox itself, including when reused outside the hash plug-in; callers
must not access the private editor or install a duplicate Enter shortcut.

The widget is a styled QFrame containing a small header and a read-only
QPlainTextEdit, not an editor service or a QScintilla dependency. Construction
and all widget operations require the Qt thread, using the existing guard.
Expose the methods above, not the internal editor/button as additional API.
Ordinary QWidget sizing, parenting, and accessibility methods remain available.

- Put one non-checkable IconButton at the **top left**, in a reserved header
  row above the text. Use a 16-logical-pixel copy icon in a fixed 24-pixel
  button, with tooltip/accessibility name `Copy text`. Do not float it over
  characters, move it on hover, or require hover to discover it.
- Use a thin theme-colored frame, at most a 4-pixel radius, modest padding, and
  a platform fixed-width font. The control is the framed output surface; the
  surrounding window is not another decorative card. Inherit theme colors,
  including readable selection and focus states.
- Text is selectable by keyboard and mouse but cannot be changed by typing,
  paste, cut, drag/drop, undo, or context-menu editing actions. Ctrl+A selects
  all; Ctrl+C copies the selection using normal Qt behavior. The top-left
  button always copies all output. Space/Return/keypad Enter activate the
  focused button once; Enter in text uses the same public copy-all contract.
- Focus on the composite forwards to the text. Tab/Shift+Tab traverse out of
  the text and through the copy button normally; do not trap focus or register
  application-global shortcuts. Empty output disables the copy button.
- Soft-wrap long unbroken hashes at the viewport width; preserve logical lines,
  tabs, Unicode, and trailing newlines. Use scrolling for tall output, without
  growing the window to fit arbitrary text. Resizing never changes copy payload.
- Keep the supplied string as the authoritative copy-all value: Qt display or
  selection newline normalization must not silently change `text()` or the
  string passed to the clipboard by `copy_text()`. Never interpret HTML, links,
  ANSI escapes, or Markdown as executable or formatted content.
- No background work, timers, file I/O, clipboard monitoring, or persistence.
  The caller explicitly supplies text and decides what `copied` feedback means.
  This is bounded-result UI, not an unbounded log viewer; arbitrary huge-text
  performance is outside this task, and no silent truncation is permitted.

Retain an established [Lucide Copy SVG](https://lucide.dev/icons/copy), rather
than a hand-painted glyph. No suitable copy SVG was found in the workspace.
During implementation:

- Add `src/main/resources/base/icons/copy.svg` and the upstream license/notice
  in that shared resource directory, outside the hash plug-in. The base
  resources tree is already collected into the portable application.
- Add a path-specific rule after the broad SVG rule in
  [.gitattributes](../.gitattributes):
  `src/main/resources/base/icons/copy.svg -filter -diff -merge text`.
  Keep this small asset as ordinary text, without changing other LFS assets.
- Add `fman.impl.ui.output` and `PyQt5.QtSvg` to the explicit hidden imports in
  [application.spec](../application.spec). Verify the Qt SVG module,
  native dependencies, and `iconengines/qsvgicon.dll` are collected by the
  PyInstaller Qt hooks; explicitly collect a missing plugin if needed.
- Load `icons/copy.svg` via the host resource resolver only on construction,
  tint for the active palette, and refresh on palette/style changes. Test the
  actual SVG bytes and a nonblank rendered icon in source and frozen builds;
  existence of an LFS pointer or a non-null QIcon is not sufficient.

No runtime downloads or new icon-library dependency. Asset acquisition and
packaging changes are implementation steps, not completed work in this revision.

### Algorithm Registry

```python
ALGORITHMS = (
    ('sha256', 'SHA-256'), ('sha1', 'SHA-1'), ('md5', 'MD5'),
    ('sha384', 'SHA-384'), ('sha512', 'SHA-512'),
    ('sha3_256', 'SHA3-256'), ('sha3_512', 'SHA3-512'),
    ('blake2b', 'BLAKE2b'), ('blake2s', 'BLAKE2s'), ('crc32', 'CRC32'),
)

  DEFAULT_FALLBACK_ORDER = (
    'sha256', 'sha512', 'sha384', 'sha3_256', 'sha3_512',
    'blake2b', 'blake2s',
  )
```

Identifiers are `hashlib` names except `crc32`, implemented with
`zlib.crc32` accumulated over chunks. Availability is checked once by trying
`hashlib.new(identifier)` for each configured hashlib algorithm; unavailable
names are dropped from the picker without relying on platform-specific alias
spelling in `hashlib.algorithms_available`. Output is lower-case hex, except
`crc32` which is `%08X`. The picker labels MD5 and SHA-1 as legacy algorithms
that are unsuitable for collision-resistant security decisions, and CRC32 as
non-cryptographic. The output title uses the same labels. Availability filtering does
not change the explicit strong-algorithm fallback order above.

### Hashing

`compute_hash(path, algorithm, report, check_canceled, chunk_size=4 MiB)`:
open in binary mode, capture `os.fstat(file.fileno())`, loop
`read(chunk_size)` -> `update`, call `report(bytes_done)` after each chunk and
`check_canceled()` before the next read and once after EOF. Compare size,
`st_mtime_ns`, `st_dev` and `st_ino` with a second `fstat`, close the handle,
and compare the same fields with `os.stat(path)` to detect path replacement.
Return a `HashResult(digest, bytes_read, changed)`. `OSError` propagates
unchanged. A changed or replaced file produces an alert asking the user to
retry and publishes no new digest. This detects ordinary concurrent writes; it does
not claim to provide an atomic filesystem snapshot.

`_HashFileTask(Task)` owns `result` and `completed` fields. Its `__call__`
invokes `compute_hash` with `self.set_progress` (clamped to the initial task
size) and cancellation checks, stores the result, then sets `completed`.
The command opens/reuses the result session, marks its request busy, obtains
the initial size from `os.stat` on the worker, and calls `submit_task(task)`.
It publishes a digest
only when `task.completed` is true and the file did not change. This explicit flag
is required because `submit_task` catches `Task.Canceled` and returns no task
result. The existing progress dialog appears after one second for large files
and offers Cancel. Hashing runs on the existing command thread, already off
the Qt thread; no extra threads or processes are created by this plug-in.
Check both `Task` cancellation and the captured session/request cancellation
token between reads and after EOF. Closing the result session or unloading the
plug-in cancels publication and requests cancellation of the read loop.

The command catches `OSError` around initial stat and task submission and
shows `show_alert('Could not read <path> (<strerror>).')`, using
`error.strerror or str(error)`. The URL is converted to a native Windows path
with public `as_human_readable(file_url)` before `stat` or `open`.

### Commands

Both are `DirectoryPaneCommand`s and share `_hash_and_show(url, algorithm)`.

- `CalculateFileHash` (`calculate_file_hash`, aliases `Calculate file hash`,
  `File hash`, `Checksum`): `__call__(self, algorithm=None, url=None)`. Uses
  `algorithm` if given and valid. An explicitly supplied unknown algorithm
  shows a status error and returns rather than silently hashing with a
  different algorithm. An invalid configured default falls back to `sha256`
  or the next available strong algorithm as specified in Settings, with a
  warning once per process.
  Target is the explicitly supplied `url` for recomputation, otherwise
  `self.pane.get_file_under_cursor()`; if it is `None` or a
  directory, `show_status_message('Place the cursor on a file to hash it.')`.
  `is_visible()` checks only that the pane and cursor URLs use `file://` and a
  cursor item exists. It deliberately does not call `fman.fs.is_dir` on the
  Qt thread; directory validation runs on the command worker after invocation.
  Validate explicit URLs by the same local-file rules; never follow the current
  cursor when recomputing an already displayed file.
- `CalculateFileHashBy` (`calculate_file_hash_by`, aliases
  `Calculate file hash by...`, `File hash by algorithm`): opens
  `show_quicksearch` over the registry (item title = display name, hint =
  identifier, description `default` on the configured one, initial cursor on
  the default). Its local case-insensitive subsequence matcher returns
  filtered `QuicksearchItem`s without importing Core internals. Check for a
  `None` result before unpacking the public `(query, value)` tuple; a false
  chosen value also means cancel. Then
  `_hash_and_show(url, chosen)`. If `remember_last_algorithm` is `true`, the
  accepted choice becomes the new default via `save_json`, using a copied
  settings dict. Capture the target URL before opening the picker; cancel
  hashes nothing and opens no result window. This command takes no arguments;
  explicit algorithm/URL bindings use `calculate_file_hash` instead.

### Result Window

Compose a modeless, pane-owned result view with `UiController.build(window,
pane)` and [the existing tool lifecycle](../src/main/python/fman/impl/ui/session.py).
Both commands show the full file path as the window title and a visible heading
above OutputTextBox. The heading elides with the full path in its tooltip.
OutputTextBox contains only the digest, with `Hash Algorithm: <Algorithm>` as
its header title and the full path/algorithm in its tooltip. Titles identify the
successful result; canceled recomputation retains the previous digest and titles.
There is no duplicate algorithm label or feedback label. Copy/cancellation
feedback uses the status bar; no metadata is included in copy-all.
Set `window.focus_widget` to the output. No custom host-window subclass or new
public `UiController` signature is required.

In `build`, override only this consumer's inherited window size: call
`setMinimumSize(480, 160)` before `resize(560, 180)`, in logical pixels, rather
than retaining PaneToolWindow's 480x260 minimum and 680x430 initial size.
Let the actual layout/font minimum win if larger, clamp to the available screen,
and test wrapped 128-character digests and long paths at supported DPI. Do not
change the shared host defaults for Favorites or other consumers.
On show and request start, center the result's frame on the main window's frame.
Use the parent's screen for bounds; only clamp away from exact centering if
needed to keep the result visible. No tracking timer or host-wide position
change is introduced.

Neither command constructs a Panel, DropDown, or Calculate button. To calculate
again, invoke a hash command; By always opens the algorithm picker. Both leave
unrelated docked tools untouched, including when closing the result. Escape or
window close ends the session. No presentation-mode flag or dock lifecycle is
needed in the hash plug-in; the shared Panel API remains available to other tools.

The top-left icon and Enter with focus in the output call the same
generic `copy_text()` action. Enter in other controls keeps that control's behavior;
Ctrl+C in output copies only the selection. Copy leaves the window open and
reports `<ALGO> copied to clipboard.` through the existing status API. The
generic control itself does not own a status bar or timer.
After a successful calculation, re-enable and focus the output so Return can
copy immediately. Perform this only while the session and owner remain active.

The optional `auto_copy` setting remains false by default. When enabled, call
`copy_text()` only after successful, current-result publication and report the
same copied feedback. Do not read, subscribe to, or poll the clipboard; comparison
and alternate copy formats are outside this initial workflow.

### Result Delivery And Lifetime

`UiController.show(pane)` creates/reuses the Qt window and returns its public
handle; `window.post(callback, snapshot)` is the queued result-delivery boundary.
Only Qt callbacks call `set_text`, write the clipboard, or mutate widgets.
The worker receives a native path, algorithm/settings snapshots, and plain
cancellation/request state, never a widget/model to operate on.

Keep one in-flight hash per pane, guarded by plain session request state. A
second invocation while hashing reports busy without starting another read or
queue. Hashing runs on the command worker, never directly on Qt or in the
shared two-slot UI worker pool. Disable output copying while busy.

Each request has an ID and captures the owner/session lifetime. Queued busy,
completion, error, and automatic-copy callbacks verify that ID and
the live owner before acting. Closing the pane/window or
unloading the plug-in invalidates the request. Late work cannot reopen a closed
window or copy to the clipboard. The existing host supplies Qt dispatch and
owner invalidation; the plug-in owns domain request state, not a new executor.

Initial output is empty and busy, with copy disabled. Initial cancellation or
failure closes the empty result view; errors still use the documented alert.
Recomputation retains the last successful snapshot until a new digest is
validated. Cancellation/failure re-enables the prior output and preserves its
path/algorithm titles, indicating that no new result was produced. No partial or
changed-file digest is displayed or automatically copied. No results or paths
are persisted after closing the session.

### Settings

`CalculateFileHash.json`:

```json
{
  "default_algorithm": "sha256",
  "remember_last_algorithm": false,
  "auto_copy": false,
  "chunk_size_mib": 4
}
```

`default_algorithm` must be an available registry identifier. An invalid or
unavailable configured default selects the first available identifier in
`DEFAULT_FALLBACK_ORDER`, with a one-time status warning naming the replacement.
If none is available, the quick command reports an error and does not hash;
it never silently chooses SHA-1, MD5, or CRC32. Those remain available when
explicitly chosen in the picker, passed as an argument, or configured as
a valid default. The By picker remains usable without a valid default; give
it an initial cursor but require explicit confirmation of any choice.
`chunk_size_mib` integers are clamped with `max(1, min(value, 64))`; booleans
and non-integers fall back to 4. Settings are loaded lazily on command
invocation and persisted with `save_json` only when
`remember_last_algorithm` changes the default after an accepted choice.
Make a fresh dict from the raw loaded settings before assigning `default_algorithm`
and saving; never mutate the shared cached dict. Normalization is for runtime
use only; preserve unrelated keys and their original values when saving. If
save fails, report the error, retain the old default, and still allow the
explicit hash request without claiming the preference was saved.

## Alternatives

- **`hashlib.file_digest`** (Python 3.11+) — one call, but no progress or
  cancellation hooks; a 20 GB ISO would block the command thread with no
  feedback. Rejected in favour of the chunked loop using the existing
  progress dialog. Compare throughput during implementation; no measurement
  from this design pass is claimed.
- **`certutil -hashfile` / `Get-FileHash` subprocess** — external process,
  Windows-only output parsing, no CRC32; rejected. `hashlib` is already in the
  frozen build.
- **Adding a `Hash` column** — hashing every visible file is prohibitively
  expensive; on-demand is the only sensible default. Out of scope.
- **Quicksearch result menu** — keeps actions keyboard-accessible but does not
  provide the requested selectable output block and persistent top-left copy
  button. Keep Quicksearch for algorithm selection only.
- **`show_alert` or a bare read-only text editor** — no reusable built-in
  copy-all affordance. Use the composed OutputTextBox and existing tool host.
- **QScintilla or HTML/WebEngine output** — unnecessary editor/browser
  dependencies for plain hashes; a read-only Qt text widget is sufficient.
- **Docked or embedded algorithm Panel** — superseded by the user's simpler
  picker-then-result workflow. Removing it avoids duplicate selection controls
  and hash-specific docking/recompute state; unrelated tools keep their docks.
- **QPainter copy glyph** — avoids an asset dependency but duplicates an
  established icon. Retain the SVG with a narrow LFS exception, upstream notice,
  and explicit frozen rendering checks.
- **Comparison and copy-format controls** — useful later, but unnecessary for
  the agreed picker-and-output workflow. Defer rather than expand this UI.
- **Hashing the whole selection** — useful, but the result UI becomes a list
  of pairs and the copy semantics get ambiguous; deferred to a follow-up
  "checksum file" task that has a natural multi-file output.
- **`Ctrl+Shift+H` / `Alt+H`** — `Ctrl+H` is free in every bundled binding
  file and matches the mnemonic; kept.

## Runtime Effects

- Startup: registers two commands, the UI controller, and one key binding; the algorithm
  availability check constructs one empty hash object per configured hashlib
  identifier at import. No timers, threads, I/O or settings reads.
- Steady state: zero feature work without an invocation. Importing the shared
  control creates no widgets, clipboard connections, workers, timers, or asset
  reads. Construct/load its icon only when a result view is needed.
- Invocation: reads settings, stats the file, then reads it once sequentially
  in `chunk_size_mib` chunks;
  memory is one chunk plus the hash state and bounded result text. Progress updates go through the
  existing throttled progress dialog (100 ms). Cancel raises `Task.Canceled`
  between chunks, closing the file via the `with` block; the task completion
  flag remains false and no partial result is shown. Final `fstat` and path
  `stat` detect ordinary concurrent changes/replacement. Blocked filesystem
  reads are not preemptible; cancellation takes effect when control returns.
- Open UI: event-driven text painting and explicit clipboard actions only.
  A full copy is linear in supplied text, at most 128 digest characters here.
  Closing disposes widget/signal ownership and invalidates result publication.
  Neither command creates a Panel, dropdown, or Calculate button. There is no
  presentation-mode state; centering and title updates remain event-driven on Qt.
- Disabled/no-op path: nothing runs unless invoked; removing the plug-in
  directory removes commands and UI registration. The exported OutputTextBox
  remains available to other consumers without feature-specific work.

## Tests

Focused commands from the repository root in the existing environment.
Check each exit code;
do not run the complete `python build.py test` suite without an explicit request.

```powershell
$roots = @('src/main/python', 'src/unittest/python', 'src/integrationtest/python', 'src/main/resources/base/Plugins/Core', 'src/main/resources/base/Plugins/Favorites', 'src/main/resources/base/Plugins/SearchFileFuzzy', 'src/main/resources/base/Plugins/CalculateFileHash')
$env:PYTHONPATH = ($roots | ForEach-Object { (Resolve-Path $_).Path }) -join [IO.Path]::PathSeparator
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_calculate_file_hash
python -m unittest fman_integrationtest.impl.plugins.test_calculate_file_hash_plugin
python -m unittest fman_unittest.test_ui_elements
python -m unittest fman_integrationtest.test_qt
```

The shared Qt harness contains `OutputTextBoxIT` and `HashResultIT`; run the
narrowest affected case immediately after widget edits. Do not create another
QApplication or a new virtual environment. No package installation is required.

Unit tests (`src/unittest/python/fman_unittest/test_calculate_file_hash.py`,
pure helpers/command tests with mocked UI):

- `compute_hash` against known vectors for every registry algorithm on an
  empty file, a 1-byte file, and a file larger than two chunks (`chunk_size`
  set small); `crc32` formatting is upper-case 8 digits.
- `report` is called with monotonically increasing byte counts ending at the
  file size; `check_canceled` raising stops reading and closes the file.
- Changes in size, `st_mtime_ns`, identity, or path replacement return
  `changed=True`; the command shows an alert and publishes no new digest.
- `OSError` from `open` propagates unchanged.
- Registry filtering when a `hashlib` name is missing (patched
  `hashlib.new`); exact strong fallback order when SHA-256 or successive
  alternatives are unavailable. If only SHA-1/MD5/CRC32 remain, implicit fallback
  hashes nothing; explicit selection or a valid configured default still works.
- Settings validation: unknown `default_algorithm`, `chunk_size_mib` out of
  range (`0 -> 1`, `65 -> 64`), non-integer values and booleans; partial user
  settings retain bundled defaults through the existing shallow dict merge.
- `CalculateFileHash` with a `Mock` pane: no file under cursor → status
  message, no hashing; directory under cursor → same; `algorithm` argument
  overrides the default; an invalid explicit argument reports the error and
  does not hash; an invalid configured default warns once and falls back.
- `_HashFileTask`: successful completion stores the result; cancellation
  leaves `completed=False`; a read error is translated into the documented
  alert without publishing output. Session cancellation also closes the handle.
- Pure result actions: only the plain digest is copied; automatic copy happens
  only for a successful current result, and canceled/stale results copy nothing.
  The algorithm wizard captures the target URL before the cursor can move.
- `CalculateFileHashBy`: cancel in the picker hashes nothing;
  `remember_last_algorithm` triggers `save_json` with the new default;
  `false` leaves settings untouched. Verify the loaded dict is unchanged,
  unrelated keys survive, and save failure leaves the cached default intact.
  Filtering or canceling the picker writes no preferences.
- `is_visible()` false for `zip://` and a missing cursor, without calling
  filesystem methods; invoking it on a directory reports the documented
  status message from the command worker.

Qt integration (existing shared harness):

- Import OutputTextBox from `fman.ui` and `__all__`; construct/use on Qt and
  reject off-thread calls. Render HTML-like strings literally; test Unicode,
  mixed line endings, tabs, trailing newlines, empty text, and invalid types.
- Mouse/select-all/Ctrl+C copy selected text; top-left click and keyboard
  activation copy the complete supplied string despite a partial selection.
  Unmodified Return and keypad Enter in the text work in the standalone
  OutputTextBox with no hash-specific shortcut or private-widget access.
  Empty output preserves clipboard contents and emits nothing; each nonempty
  copy-all action emits `copied` once.
- Typing/paste/cut/drop/undo cannot mutate output. `set_text` replaces the
  authoritative value; no old selection or digest is copied after replacement.
- Copy button remains top-left, visible, non-checkable, and non-overlapping at
  narrow/wide sizes and DPI variants. Verify wrap/scroll, tab traversal,
  accessibility labels, focus indication, SVG rendering, and palette changes.
- Both commands use the same centered result controller and two-widget layout:
  file-path heading plus OutputTextBox. Verify windowTitle/full-path tooltip and
  `Hash Algorithm: <Algorithm>` beside Copy. By cancel creates no result, and
  accepted selection hashes the file captured before the picker opened.
- Switch quick -> By -> quick, verifying reuse without any dock creation.
  Both commands and result close must leave an unrelated dock untouched.
  Verify center alignment on initial show and reuse after moving
  the main window, plus native popup pixels at the reported location.
- Hash UI relies on the generic copy behavior; other controls retain normal
  bindings, and no shortcut reaches the underlying file pane. Copy leaves the
  result open. Verify consumer-specific size/minimum overrides without changing
  the host defaults used by Favorites.
- Busy/cancel/error/recompute states; one read per pane; no Qt-thread hashing;
  stale completion/auto-copy rejection on close, pane close,
  and plug-in unload. Existing Favorites docking and controls still pass.

Plug-in integration (`test_calculate_file_hash_plugin.py`, existing loading
pattern): controller and both commands load; `Ctrl+H` maps to the command;
JSON defaults merge correctly; unload removes registrations and pending UI
callbacks while the host-owned OutputTextBox export remains usable.

Manual/performance: use empty, short, and multi-GB files; record hashing
throughput and cancellation latency against the chunk size without claiming
preemption of a blocked read. Verify Qt stays responsive and rename/delete
immediately after cancellation confirms the file handle closed. Compute and
copy via the top-left icon, Return, and keypad Enter; move the file cursor while
the algorithm picker is open and verify the captured file is still hashed.
Exercise long paths and 128-character hashes at 100/150/200% DPI with no clipping.
Verify no file/clipboard polling while idle or after close.

Native smoke: remove the offscreen override and run
`python -m fman_integrationtest.hash_smoke` with isolated settings. Delivery
smoke is run only when explicitly requested: freeze/package, then repeat checks from the
extracted ZIP with isolated UserSettings, including a path containing spaces
and non-ASCII characters. Run
`git check-attr filter diff merge text -- src/main/resources/base/icons/copy.svg`
to confirm filter/diff/merge are unset and text is set. Parse the tracked asset
as XML to reject an LFS pointer, and verify the upstream notice, QtSvg native
dependencies, qsvgicon plugin, and `fman.impl.ui.output` import in the frozen
application. Render the copy icon in a clean extracted ZIP without relying on
source-tree Qt paths; record commands/artifact paths and any approved skips.

## Implementation Steps

1. Review the revised public OutputTextBox contract, picker/result layout, and
  cancellation/clipboard acceptance criteria before implementation.
2. Add OutputTextBox and its `fman.ui` export, acquire the shared copy SVG and
  required notice/LFS exception, and add focused Qt tests in the existing
  harness, including its own Enter-to-copy behavior. Validate the standalone
  control before wiring the hash consumer.
3. Implement the pure registry, strong default fallback, chunked hashing,
  and change detection with unit tests against known vectors.
4. Add commands, lazy settings validation, Task/cancellation handling, and
  captured-URL recomputation; verify no visibility-time I/O or Qt-thread hash.
5. Compose the centered compact result window with path and algorithm titles
  and queued, lifetime-checked snapshots; test copy, busy states, explicit
  recomputation, safe settings updates, and stale completion.
6. Add defaults/bindings and plug-in loading tests; include the plug-in in
  [build.py](../build.py)'s test paths. Add `fman.impl.ui.output` and
  `PyQt5.QtSvg` hidden imports and verify qsvgicon/resources in
  [application.spec](../application.spec).
7. Document OutputTextBox in [PlugIn.md](../PlugIn.md), update the shared UI
  implementation status and the plug-in/main README, and add the implemented
  application/API change to [CHANGELOG.md](../CHANGELOG.md).
8. Record focused and native/frozen validation plus implementation metadata;
  move this canonical task to Done and update the index only after completion.

## Acceptance Criteria

- `Ctrl+H` / `Calculate File Hash` hashes the file under the cursor with the
  configured default algorithm without a picker or Panel. The centered result
  contains the file-path heading and output/copy control. The top-left copy icon and
  generic Return/keypad Enter behavior copy the complete hash without closing
  the window or exposing OutputTextBox internals.
- Plug-ins can import and reuse `fman.ui.OutputTextBox` independently of the
  hash plug-in. Its public text/copy contract, read-only behavior, selection,
  empty state, accessibility, and Qt-thread constraints pass focused tests.
- Output resembles a compact web code block; its top-left SVG button never
  overlaps text, and long hashes remain readable/copyable at supported DPI.
- `Calculate File Hash By` lets the user choose any available algorithm
  before hashing; the choice optionally becomes the new default.
- Both commands share one result UI and create no docked controls. By selects
  an algorithm in QuickSearch, then hashes the captured file. The window title
  is the full path; OutputTextBox's title is `Hash Algorithm: <Algorithm>` and
  follows the published digest. No comparison or copy-format controls are included.
- The result window uses a compact consumer-specific size and minimum, without
  modifying shared host defaults or clipping text/buttons at supported DPI.
  Its frame center matches the main window's frame center whenever screen bounds
  permit. Both commands preserve unrelated docks.
- Invalid defaults use the documented strong fallback order or fail clearly;
  weaker algorithms require an explicit choice or valid configured default.
  Persisting a choice never mutates the loaded settings dict in place.
- Large files show the standard progress dialog and can be cancelled without
  publishing a partial/new digest. A canceled recomputation retains only the
  clearly identified prior result. Close/unload rejects all late UI and copy work.
- A file changed during hashing is rejected with an alert instead of showing
  a potentially inconsistent digest.
- Commands are hidden on non-`file://` locations and when no item is under
  the cursor; directories receive a status message after invocation, and read
  errors produce an alert rather than a traceback.
- No background work exists when the commands are not used; the public
  fman 1.7.5 API is preserved with only the documented additive `fman.ui` export.
- The asset and widget work in source and portable ZIP builds; focused tests,
  native UI checks, and required documentation pass before implementation is
  marked complete. Packaging verification is not rerun without an explicit request.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Initial design created: chunked `hashlib`/`zlib` hashing through
  the existing `Task` progress dialog, Quicksearch used as a keyboard-first
  result/action menu with copy as the `Enter` action and clipboard comparison
  shown inline; `Ctrl+H` chosen as it is free in all bundled bindings.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context window: Not exposed by host
- Outcome: Revised before implementation. Aligned task result and
  cancellation handling with `submit_task`, made Quicksearch and prompt
  return handling explicit, removed visibility-time filesystem I/O, added
  concurrent file-change detection, and tightened settings and error tests.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Revised for the requested public OutputTextBox with a top-left
  copy-all SVG button. Replaced the Quicksearch result menu with the shared
  tool/Panel composition; specified Qt ownership, request cancellation,
  pre-auto-copy comparison, asset delivery, and focused acceptance tests.
  Design only, awaiting review; no runtime behavior or packaging verified.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Not yet approved; hashing, cancellation, settings and test design are
  sound and verified against the host (`Ctrl+H` free in all bundled bindings;
  `submit_task` swallows `Task.Canceled`, so the `completed` flag is required;
  `ProgressDialog` scales progress above `INT_MAX`; Panel `Calculate` via
  `pane.run_command` correctly leaves Qt). Revise before implementation:
  (1) Enter-in-output copy must be part of the generic `OutputTextBox`
  contract (Return/Enter in the text invokes `copy_text()`, or an `activated`
  signal), since the hash UI may not reach the internal editor; (2) the SVG
  asset is costly here: `.gitattributes` routes `*.svg` through Git LFS (the
  release workflow needed special handling for `Icon.svg`), a `QIcon` from SVG
  needs `PyQt5.QtSvg` plus the `qsvgicon` icon-engine plugin bundled, and the
  Lucide notice must ship. Prefer a `QPainter`-drawn copy glyph using palette
  colors; if SVG stays, list the LFS exception, `PyQt5.QtSvg` hidden import and
  resource location under `src/main/resources/base/` explicitly; (3) decide
  whether the action Panel is docked (`set_panel`, which evicts an open
  Favorites session) or embedded in the tool window (Panel is embeddable
  without the dock); embedding is recommended for this small consumer;
  (4) `PaneToolWindow` hard-codes a frameless 680x430 window with a 480x260
  minimum — state that `build` resizes it for a single digest; (5) define the
  fallback order when `sha256` is unavailable so it does not select SHA-1/MD5;
  (6) add `fman.impl.ui.output` to `RoyiFileManager.spec` hidden imports and
  copy the loaded settings dict before `save_json`.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Aligned the initial workflow with two commands sharing OutputTextBox
  and the public docked Panel, containing only algorithm selection and Calculate.
  Deferred comparison/copy-format controls. Incorporated generic Enter-to-copy,
  compact consumer sizing, strong fallback, copied settings, and explicit SVG,
  LFS, notice, and frozen-import requirements. Retained SVG and dock placement
  with rationale. Design revision only; implementation and runtime checks remain
  pending.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Confirmed both open defects with failing regressions: publication
  lacked keyboard focus and remembering an algorithm normalized unrelated
  settings. Retained the noted initial-error modal alert: it waits for dismissal
  before closing the empty result; the shared nonblocking alert has no public
  dismissal callback. No shared alert API change is included in this follow-up.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Adopted the user's correction to the earlier shared-Panel design:
  Ctrl+H shows centered output only; By owns the optional docked controls.
  Chose Qt-parent frame centering and a captured request-mode flag, with lazy
  panel creation and public set_panel(None) detachment. No new host positioning
  policy, worker, timer, or legacy API break is needed.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Selected an optional keyword-only title and Qt-thread set_title/title
  methods, preserving positional arguments and digest-only copying. Long titles
  elide in the existing header; hash titles identify only the published result.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Adopted the requested picker-then-result workflow. Keep the full path
  in the window title/heading and the algorithm beside Copy. Remove all hash
  panel state and duplicate labels while preserving cancellation, captured-file
  selection, focus, generic OutputTextBox API, and unrelated docks.

## Implementation Notes

- [OutputTextBox](../src/main/python/fman/impl/ui/output.py) is exported through
  `fman.ui`. Return/keypad Enter, exact copy-all, read-only selection, empty
  state, thread guards, and explicit high-DPI SVG bounds are implemented.
- The [hash plug-in](../src/main/resources/base/Plugins/CalculateFileHash/README.md)
  uses the shared host window without a Panel, with one request per pane.
  Long paths elide with a full tooltip. Closing/unloading rejects late results;
  canceled recomputation retains the identified previous digest.
- SVG and its ISC notice are bundled; the copy SVG alone opts out of LFS.
  `fman.impl.ui.output`, QtSvg, and the qsvgicon plugin are present in the build.
- Hash choices are remembered only when explicitly submitted, including an
  algorithm argument from a binding. Settings are copied before persistence.
- The existing packaged application's UserSettings were not replaced. Build
  validation used the normal build functions with isolated target directories
  and the existing lockfile, rather than deleting the user's original build.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Implemented the exported OutputTextBox, licensed copy SVG, both hash
  commands, safe settings/defaults, cancellable chunked hashing, and compact
  docked result workflow. All 120 affected regressions and source/frozen hash
  smoke checks passed; portable SVG/DPI and cancellation behavior verified.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Implementation matches the approved design. Re-ran the focused gate
  offscreen: `fman_unittest.test_calculate_file_hash`,
  `fman_integrationtest.impl.plugins.test_calculate_file_hash_plugin`,
  `fman_unittest.test_ui_elements`, `fman_unittest.test_portable`,
  `fman_unittest.test_release_support` (43 tests OK) and
  `fman_integrationtest.test_qt` (77 tests OK). Verified spec hidden imports,
  `build.py` test path, `.gitattributes` exception (`git check-attr` reports
  filter/diff/merge unset, text set), real SVG XML plus ISC notice, `completed`
  flag, per-pane busy guard, request cancellation, strong fallback order,
  copied settings, generic Return/Enter copy-all, and the dropdown-plus-Calculate
  Panel. Process: `Plan/CalculateFileHash.md` had been copied rather than moved;
  the duplicate was deleted during this review. Open items for the implementer,
  not fixed here: (1) UX: `OutputTextBox` is disabled while busy, so
  `UiController.show` cannot focus it and `_finished` never moves focus to the
  published digest; Return therefore does not copy until the user focuses the
  output. Recommend `output.setFocus()` after a successful result. (2) Minor:
  `_remember` saves the normalized `settings_snapshot`, so an out-of-range user
  `chunk_size_mib` or non-boolean flag is rewritten on save; copy the raw loaded
  dict and change only `default_algorithm`. (3) Note: the first-run error path
  calls blocking `show_alert` inside a Qt-posted callback (nested modal loop)
  before closing the empty window; it works but blocks that callback.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Addressed review items 1 and 2. Successful publication restores output
  focus after the busy/lifetime checks; remembering an algorithm saves a raw
  settings copy with only that algorithm changed. Both reproductions now pass,
  along with 25 focused regressions and the native Windows focus check. Item 3
  remains the documented modal-error behavior. The canonical Done file and the
  reviewer's removal of the duplicate Plan file were preserved.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: High
- Context Window: Not exposed by host
- Outcome: Corrected center-on-center placement and split quick/By presentation.
  Added safe panel detachment, preserved By mode for captured-file Calculate,
  and tested repeated mode switching, cancellation, focus, and unrelated docks.
  All 105 affected regressions and the native source layout/pixel smoke passed.
  No build commands, portable archive, or installation were run.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Low
- Context Window: Not exposed by host
- Outcome: Added the optional title beside Copy and File Hash filename/algorithm
  headers. Preserved tooltips, copy payload, positional compatibility, and titles
  after canceled recalculation. Completed the code before running focused tests;
  all 13 passed. No build or packaging commands were run.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Removed hash panels, presentation flags, duplicate labels, and panel
  recompute dispatch. Both commands share a path-titled window and algorithm-titled
  OutputTextBox; By uses QuickSearch. All 28 focused tests and the native source
  wizard smoke passed, including picker cancellation, copying, captured targets,
  centering, result retention, and unrelated docks. No builds or ZIPs were produced.

## Validation Results

Commands ran from the repository root using the existing Python environment,
the test/plugin PYTHONPATH roots listed above, and `PYTHONUTF8=1`. No environment
or packages were installed; no full `python build.py test` run was performed.

Focused first checks and final regression gate:

```powershell
python -m unittest fman_integrationtest.test_qt.OutputTextBoxIT
python -m unittest fman_unittest.test_calculate_file_hash.HashingTest
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_calculate_file_hash fman_unittest.test_ui_elements fman_unittest.test_portable fman_unittest.test_release_support fman_integrationtest.impl.plugins.test_calculate_file_hash_plugin fman_integrationtest.test_qt
Remove-Item Env:QT_QPA_PLATFORM
```

- The first OutputTextBox test failed for the missing export, then passed after
  implementation. Subsequent checks caught and fixed command indentation,
  export expectations, high-DPI SVG cropping, and a test-only QtTest dependency
  in the frozen smoke helper.
- Final affected regression gate: **120 tests passed**. This includes command
  vectors/settings/cancellation, plug-in loading/unload, public API, shared Qt,
  and portable/release-support checks. Diagnostics reported no new code errors.
- An exploratory native-backend run of the shared Qt harness had three failures
  in existing dock geometry/Favorites Escape tests. The required offscreen run
  passed unchanged in those areas. Offscreen font/raise/size-hint warnings are
  environmental; no unrelated shared UI fixes were made.

Native workflow and portable build:

```powershell
$env:HASH_SMOKE_LARGE = '1'
python -m fman_integrationtest.hash_smoke
python -c "import os; import build; os.environ['CI'] = 'true'; build.TARGET_DIR = build.ROOT / 'target' / 'hash-validation'; build.DIST_DIR = build.TARGET_DIR / 'RoyiFileManager'; build.freeze(); build.package()"
Expand-Archive -LiteralPath 'target/hash-validation/RoyiFileManager-0.3.0-windows-x86_64.zip' -DestinationPath 'target/hash-validation/extracted-final'
python -m fman_integrationtest.hash_smoke --frozen target/hash-validation/extracted-final/RoyiFileManager/RoyiFileManager.exe
git check-attr filter diff merge text -- src/main/resources/base/icons/copy.svg
```

- Source smoke passed at `QT_SCALE_FACTOR=1`, `1.5`, and `2`; final extracted
  ZIP smoke passed at all three scales with isolated UserSettings. Checks cover
  real startup and command dispatch, SHA-256/SHA-512, dropdown/Calculate, copy,
  Return/keypad Enter, nonblank SVG pixels, compact layout, close, and paths with
  spaces/Unicode. Screenshots under `target/hash-source-*` and
  `target/hash-frozen-final-*` were captured; the corrected 200% source icon was
  visually inspected, as was the final 200% frozen result.
- A further extracted-ZIP smoke passed with Python/Qt search-path overrides
  removed and child PATH restricted to Windows system directories. The smoke
  helper now enforces this isolation for every frozen run.
- A 2 GiB fixture was canceled and deleted after worker release in source and
  frozen checks; one source run took 168.2 ms from close to handle release.
  This is a cancellation observation, not a filesystem throughput guarantee.
- Freeze/package succeeded. Archive:
  `target/hash-validation/RoyiFileManager-0.3.0-windows-x86_64.zip`.
  QtSvg, qsvgicon, the SVG XML, and the upstream license were verified present.
  Asset attributes report filter/diff/merge unset and text set.
- PyInstaller reported optional Windows UIA dependency warnings for the existing
  winpty/OpenConsole component; the hash workflow passed in the extracted build.
- Throughput procedure (`python -`): create a temporary 256 MiB file from 64
  zero-filled 4 MiB blocks; time SHA-256 `compute_hash` with no-op progress and
  cancellation callbacks at 1, 4, and 64 MiB chunks, then `hashlib.file_digest`;
  assert byte count, unchanged identity, and matching digest; remove the fixture.
  Observed 1,634.9 / 1,785.8 / 1,623.9 MiB/s respectively, versus 2,141.0 MiB/s
  for `file_digest`. This single cached-file run supports keeping the 4 MiB
  default and cancellation hooks; it is not a storage-device benchmark.
- No exhaustive storage-device throughput benchmark or Process Monitor Registry
  trace was performed. Existing portability source checks passed. Blocked native
  filesystem calls remain non-preemptible as documented.

### Review Follow-Up

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_calculate_file_hash fman_integrationtest.test_qt.OutputTextBoxIT fman_integrationtest.test_qt.HashResultIT fman_integrationtest.impl.plugins.test_calculate_file_hash_plugin
Remove-Item Env:QT_QPA_PLATFORM
python -m unittest fman_integrationtest.test_qt.HashResultIT.test_published_result_focuses_output_for_enter_copy
```

- **25 focused tests passed**, plus **1 native Windows focus test**. The new
  focus case covers initial calculation and recomputation without manually
  focusing output after completion. The strengthened persistence case checks
  raw invalid values, unrelated keys, cached-dict preservation, and save failure.
  Both regression cases failed before their respective fixes and passed after.
- No edited-code diagnostics. Existing offscreen font/raise warnings remain.
  No new background work, public API change, package install, or environment.
- No full suite, clean, freeze, or package run for this follow-up. The previously
  validated ZIP predates these source fixes. No extra changelog entry is needed
  for corrections to this unreleased feature.

### Command Layout Correction

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_calculate_file_hash fman_unittest.test_ui_elements fman_integrationtest.impl.plugins.test_calculate_file_hash_plugin fman_integrationtest.test_qt
Remove-Item Env:QT_QPA_PLATFORM
$env:HASH_SMOKE_LARGE = '0'
$env:HASH_SMOKE_IMAGE = (Join-Path $PWD 'target/hash-layout-quick.png')
python -m fman_integrationtest.hash_smoke
```

- **105 tests passed**, including shared Qt/Favorites behavior. New cases first
  reproduced incorrect centering and unconditional docking, then passed after
  correction. Coverage includes panel detach/remount without closing the tool,
  initial/reused centering, By Calculate with the original file, both-mode
  cancellation, quick output keyboard focus, and preserving unrelated docks.
- Native source smoke passed with temporary isolated UserSettings. It verifies
  matching main/result frame centers, quick output without metadata or dock,
  By-only controls, recalculation, copy/Enter, SVG pixels, and switch-back.
  A bounded paint check precedes the native screen capture; screenshots
  `target/hash-layout-quick-layout.png` and `target/hash-layout-quick-panel.png`
  were inspected and show the centered quick result and the By-only dock.
- Existing offscreen font/raise warnings remain non-failing. No full suite,
  clean, freeze, packaging, ZIP extraction, or installation was performed.
  No new multi-monitor or DPI-matrix run was performed for this correction.

### Output Title

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_integrationtest.test_qt.OutputTextBoxIT fman_integrationtest.test_qt.HashResultIT
Remove-Item Env:QT_QPA_PLATFORM
```

All **13 tests passed**: title placement, long-title elision, invalid types,
Qt-thread guards, old positional parenting, digest-only copy, algorithm changes,
and canceled-result title retention. The initial fixed-width test assumption
was corrected to use actual font metrics. Edited code has no diagnostics.
No full suite, build, packaging, or new native smoke was run for this addition.

### Panel-Free Algorithm Wizard

Use the PYTHONPATH setup in Tests, then:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest fman_unittest.test_calculate_file_hash fman_integrationtest.test_qt.OutputTextBoxIT fman_integrationtest.test_qt.HashResultIT fman_integrationtest.impl.plugins.test_calculate_file_hash_plugin
Remove-Item Env:QT_QPA_PLATFORM
$env:HASH_SMOKE_LARGE = '0'
$env:HASH_SMOKE_IMAGE = (Join-Path $PWD 'target/hash-wizard.png')
python -m fman_integrationtest.hash_smoke
Remove-Item Env:HASH_SMOKE_LARGE, Env:HASH_SMOKE_IMAGE
```

- The immediate post-edit gate passed **22 tests**; the final gate passed
  **28 tests**, including the shared OutputTextBox and plug-in loader.
- Native source smoke passed with temporary isolated settings and real
  QuickSearch selection/cancellation. Verified SHA-256/SHA-512, both title
  locations, centered panel-free results, copy/Enter, SVG pixels, and closing.
  Inspected the main-window and SHA-512 result screenshots under `target/hash-wizard*`.
- Existing offscreen font/raise warnings are non-failing. No code diagnostics.
- No full suite, build, freeze, clean, packaging, ZIP, new large-file benchmark,
  or DPI-matrix run. Existing executables were not rebuilt. Earlier validation
  sections above describe historical layouts, not the current wizard design.
