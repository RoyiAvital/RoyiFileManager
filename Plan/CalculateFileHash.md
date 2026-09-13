# Calculate File Hash

## Task

Add a bundled `CalculateFileHash` plug-in with two Command Center commands:

- `Calculate File Hash` — computes the hash of the file under the cursor with
  the algorithm configured as default (`sha256` out of the box) and shows the
  result in a dialog whose primary action copies the hash to the clipboard.
  Default shortcut `Ctrl+H`.
- `Calculate File Hash By` — first lets the user pick the algorithm from a
  Quicksearch list, then computes and shows the result the same way.

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
- Result dialog with: copy hash, copy `<algorithm>: <hash>`, copy in
  `sha256sum` format (`<hash> *<filename>`), compare against the clipboard,
  recompute with another algorithm.
- Progress dialog with cancellation for large files (through the existing
  `Task`/`submit_task` mechanism).
- Detection of files whose size or modification timestamp changes while they
  are being hashed; no potentially stale digest is presented.
- Optional automatic copy to the clipboard on completion (`auto_copy`).

Excluded:

- Multiple files, directories, checksum-file creation (`.sha256`) and
  verification of checksum files; non-`file://` schemes (`zip://`,
  `network://`) — the commands are hidden there. These can be later tasks.
- Changes to the public `fman` plug-in API. Only public API is used
  (`fman`, `fman.fs`, `fman.url`, `fman.clipboard`).

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5. The
plug-in can be removed without affecting Core.

## Design

Plug-in layout `Plugins/CalculateFileHash/`:

- `calculate_file_hash/__init__.py` — the two commands and the result dialog
  flow.
- `calculate_file_hash/hashing.py` — pure Python: algorithm registry,
  chunked hashing with progress/cancel callbacks and clipboard-comparison
  helper. No Qt or `fman` imports; the hashing function receives
  `report(bytes_done)` and `check_canceled()` callables so it is unit-testable
  without fman.
- `CalculateFileHash.json` — settings defaults.
- `Key Bindings (Windows).json` — `Ctrl+H` → `calculate_file_hash`.
- `README.md`.

### Algorithm Registry

```python
ALGORITHMS = (
    ('sha256', 'SHA-256'), ('sha1', 'SHA-1'), ('md5', 'MD5'),
    ('sha384', 'SHA-384'), ('sha512', 'SHA-512'),
    ('sha3_256', 'SHA3-256'), ('sha3_512', 'SHA3-512'),
    ('blake2b', 'BLAKE2b'), ('blake2s', 'BLAKE2s'), ('crc32', 'CRC32'),
)
```

Identifiers are `hashlib` names except `crc32`, implemented with
`zlib.crc32` accumulated over chunks. Availability is checked once by trying
`hashlib.new(identifier)` for each configured hashlib algorithm; unavailable
names are dropped from the picker without relying on platform-specific alias
spelling in `hashlib.algorithms_available`. Output is lower-case hex, except
`crc32` which is `%08X`. The picker labels MD5 and SHA-1 as legacy algorithms
that are unsuitable for collision-resistant security decisions.

### Hashing

`compute_hash(path, algorithm, report, check_canceled, chunk_size=4 MiB)`:
open in binary mode, capture `os.fstat(file.fileno())`, loop
`read(chunk_size)` -> `update`, call `report(bytes_done)` after each chunk and
`check_canceled()` before the next read and once after EOF. Compare size,
`st_mtime_ns`, `st_dev` and `st_ino` with a second `fstat`, close the handle,
and compare the same fields with `os.stat(path)` to detect path replacement.
Return a `HashResult(digest, bytes_read, changed)`. `OSError` propagates
unchanged. A changed or replaced file produces an alert asking the user to
retry and no digest dialog. This detects ordinary concurrent writes; it does
not claim to provide an atomic filesystem snapshot.

`_HashFileTask(Task)` owns `result` and `completed` fields. Its `__call__`
invokes `compute_hash` with `self.set_progress` (clamped to the initial task
size) and `self.check_canceled`, stores the result, then sets `completed`.
The command obtains the initial size from `os.stat`, calls `submit_task(task)`,
and opens the result UI only when `task.completed` is true. This explicit flag
is required because `submit_task` catches `Task.Canceled` and returns no task
result. The existing progress dialog appears after one second for large files
and offers Cancel. Hashing runs on the existing command thread, already off
the Qt thread; no extra threads or processes are created.

The command catches `OSError` around initial stat and task submission and
shows `show_alert('Could not read <path> (<strerror>).')`, using
`error.strerror or str(error)`. The URL is converted to a native Windows path
with public `as_human_readable(file_url)` before `stat` or `open`.

### Commands

Both are `DirectoryPaneCommand`s and share `_hash_and_show(url, algorithm)`.

- `CalculateFileHash` (`calculate_file_hash`, aliases `Calculate file hash`,
  `File hash`, `Checksum`): `__call__(self, algorithm=None)`. Uses
  `algorithm` if given and valid. An explicitly supplied unknown algorithm
  shows a status error and returns rather than silently hashing with a
  different algorithm. An invalid configured default falls back to `sha256`
  with a warning once per process.
  Target is `self.pane.get_file_under_cursor()`; if it is `None` or a
  directory, `show_status_message('Place the cursor on a file to hash it.')`.
  `is_visible()` checks only that the pane and cursor URLs use `file://` and a
  cursor item exists. It deliberately does not call `fman.fs.is_dir` on the
  Qt thread; directory validation runs on the command worker after invocation.
- `CalculateFileHashBy` (`calculate_file_hash_by`, aliases
  `Calculate file hash by...`, `File hash by algorithm`): opens
  `show_quicksearch` over the registry (item title = display name, hint =
  identifier, description `default` on the configured one, initial cursor on
  the default). Its local case-insensitive subsequence matcher returns
  filtered `QuicksearchItem`s without importing Core internals. Check for a
  `None` result before unpacking the public `(query, value)` tuple; a false
  chosen value also means cancel. Then
  `_hash_and_show(url, chosen)`. If `remember_last_algorithm` is `true`, the
  choice becomes the new default via `save_json`.

### Result Dialog

Use `show_quicksearch` as an action menu (public API, keyboard first, `Enter`
= primary action, `Esc` = close). The `get_items(query)` callback filters
case-insensitively over action titles, and the returned `(query, value)` is
unpacked before dispatch. Items, in order:

1. Title `<hash>`, hint `<ALGO>  <filename>`, description = clipboard
   comparison result (see below). Value `copy`. **Enter copies the hash.**
2. `Copy "<ALGO>: <hash>"` — value `copy_labeled`.
3. `Copy "<hash> *<filename>"` (GNU checksum-file style) — value
   `copy_checksum_line`.
4. `Compare with clipboard...` — value `compare`. If the clipboard already
  contains a digest of the expected length, show `Match` / `No match`
  directly. Otherwise call `show_prompt` prefilled with the clipboard text,
  unpack `(text, accepted)`, and return without a comparison when
  `accepted` is false.
5. `Calculate with another algorithm...` — value `other`; runs the picker and
  recomputes, then builds a fresh action menu and clipboard description for
  the new digest.

After a copy action, `show_status_message('<ALGO> copied to clipboard.',
timeout_secs=3)`. Query filtering is over titles so typing `copy` narrows the
list; empty query lists all.

Clipboard comparison: `clipboard.get_text().strip()`; if it matches
`^[0-9a-fA-F]+$` and its length equals the digest length, description is
`Matches clipboard` or `Does not match clipboard`; otherwise empty. Comparison
is case-insensitive. This makes the common "paste published checksum, hash the
download" verification a zero-keystroke read.

With `auto_copy: true`, the hash is copied before the dialog opens and the
first item's hint says `copied`.

`show_alert` was considered for the result: `QMessageBox` text is selectable
but there is no way to add a *Copy* button through the public API and
selection with the mouse is not "easy copy". Quicksearch is the only public
dialog with custom, keyboard-selectable actions until the Extended
Quicksearch UI task lands; the plug-in can adopt controls then without
changing its commands.

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

`default_algorithm` must be an available registry identifier, otherwise
`sha256` with a one-time status message. If SHA-256 is unexpectedly
unavailable, use the first available registry entry; CRC32 guarantees one
entry remains; registry tuple order defines this fallback order.
`chunk_size_mib` integers are clamped with `max(1, min(value, 64))`; booleans
and non-integers fall back to 4. Settings are loaded lazily on command
invocation and persisted with `save_json` only when
`remember_last_algorithm` changes the default.

## Alternatives

- **`hashlib.file_digest`** (Python 3.11+) — one call, but no progress or
  cancellation hooks; a 20 GB ISO would block the command thread with no
  feedback. Rejected in favour of the chunked loop using the existing
  progress dialog. Chunking at 4 MiB measured within a few percent of
  `file_digest` on local NVMe.
- **`certutil -hashfile` / `Get-FileHash` subprocess** — external process,
  Windows-only output parsing, no CRC32; rejected. `hashlib` is already in the
  frozen build.
- **Adding a `Hash` column** — hashing every visible file is prohibitively
  expensive; on-demand is the only sensible default. Out of scope.
- **`show_alert` with the hash in the text** — see Result Dialog; no copy
  action available.
- **Hashing the whole selection** — useful, but the result UI becomes a list
  of pairs and the copy semantics get ambiguous; deferred to a follow-up
  "checksum file" task that has a natural multi-file output.
- **`Ctrl+Shift+H` / `Alt+H`** — `Ctrl+H` is free in every bundled binding
  file and matches the mnemonic; kept.

## Runtime Effects

- Startup: registers two commands and one key binding; the algorithm
  availability check constructs one empty hash object per configured hashlib
  identifier at import. No timers, threads, I/O or settings reads.
- Steady state: zero background cost.
- Invocation: reads settings, stats the file, then reads it once sequentially
  in `chunk_size_mib` chunks;
  memory is one chunk plus the hash state. Progress updates go through the
  existing throttled progress dialog (100 ms). Cancel raises `Task.Canceled`
  between chunks, closing the file via the `with` block; the task completion
  flag remains false and no partial result is shown. One final `fstat` detects
  ordinary changes during the read.
- Disabled/no-op path: not applicable — nothing runs unless a command is
  invoked; removing the plug-in directory removes both commands.

## Implementation Steps

1. `hashing.py`: registry with availability filtering, `compute_hash` with
  `report`/`check_canceled` callbacks, concurrent-change detection and
  `crc32` support,
   `compare_with_clipboard_text(digest, text)`; unit tests with temp files
   against known vectors.
2. `__init__.py`: lazy settings loading/validation, `CalculateFileHash` with
  the `algorithm` argument and `is_visible`, native path conversion, and
  `_HashFileTask`/`submit_task` result and cancellation handling.
3. Result Quicksearch with the five actions, clipboard comparison
   description, `auto_copy`.
4. `CalculateFileHashBy` with the algorithm picker and
   `remember_last_algorithm`.
5. `CalculateFileHash.json`, `Key Bindings (Windows).json`, add the plug-in
   directory to `build.py`'s test `PYTHONPATH` (the base resources tree is
   already bundled).
6. Plug-in README, one concise entry in the main README Features section, and
  a changelog entry under `Unreleased / Added`.

## Tests

Focused validation commands from the repository root (repository test
`PYTHONPATH`, `QT_QPA_PLATFORM=offscreen`):

```powershell
python -m unittest fman_unittest.test_calculate_file_hash
python -m unittest fman_integrationtest.impl.plugins.test_calculate_file_hash_plugin
```

Unit tests (`src/unittest/python/fman_unittest/test_calculate_file_hash.py`,
no Qt):

- `compute_hash` against known vectors for every registry algorithm on an
  empty file, a 1-byte file, and a file larger than two chunks (`chunk_size`
  set small); `crc32` formatting is upper-case 8 digits.
- `report` is called with monotonically increasing byte counts ending at the
  file size; `check_canceled` raising stops reading and closes the file.
- A file whose size or `st_mtime_ns` changes during hashing returns
  `changed=True`; the command shows an alert and no result menu.
- `OSError` from `open` propagates unchanged.
- Registry filtering when a `hashlib` name is missing (patched
  `hashlib.new`).
- `compare_with_clipboard_text`: exact match, case-insensitive match, wrong
  length, non-hex text, surrounding whitespace.
- Settings validation: unknown `default_algorithm`, `chunk_size_mib` out of
  range (`0 -> 1`, `65 -> 64`), non-integer values and booleans; partial user
  settings retain bundled defaults through the existing shallow dict merge.
- `CalculateFileHash` with a `Mock` pane: no file under cursor → status
  message, no hashing; directory under cursor → same; `algorithm` argument
  overrides the default; an invalid explicit argument reports the error and
  does not hash; an invalid configured default warns once and falls back.
- `_HashFileTask`: successful completion stores the result; cancellation
  leaves `completed=False`; a read error is translated into the documented
  alert without opening the result menu.
- Result actions with patched `show_quicksearch` returning each value:
  `clipboard.set_text` receives the hash / labeled / checksum-line text;
  `compare` covers valid clipboard text, accepted prompt text, and canceled
  `(text, False)` prompt results; `other` runs the picker, re-hashes and
  rebuilds comparison state; `None` (Escape) copies nothing.
- `CalculateFileHashBy`: cancel in the picker hashes nothing;
  `remember_last_algorithm` triggers `save_json` with the new default;
  `false` leaves settings untouched.
- `is_visible()` false for `zip://` and a missing cursor, without calling
  filesystem methods; invoking it on a directory reports the documented
  status message from the command worker.

Integration (`test_calculate_file_hash_plugin.py`, existing plug-in loading
pattern): plug-in loads, both commands appear, `Ctrl+H` maps to
`calculate_file_hash`, bundled JSON merges with an empty user file.

Manual: hash a multi-GB file and cancel mid-way (dialog closes, no result),
then immediately rename or delete it to verify the handle closed; put a
published SHA-256 on the clipboard, hash the download, read
`Matches clipboard`; `Enter` copies and the status bar confirms.

## Acceptance Criteria

- `Ctrl+H` / `Calculate File Hash` hashes the file under the cursor with the
  configured default algorithm and `Enter` in the result copies the hash.
- `Calculate File Hash By` lets the user choose any available algorithm
  before hashing; the choice optionally becomes the new default.
- The result dialog offers plain, labeled and checksum-line copies, shows
  whether the clipboard already holds the same digest, and can rehash with
  another algorithm.
- Large files show the standard progress dialog and can be cancelled without
  leaving a result behind.
- A file changed during hashing is rejected with an alert instead of showing
  a potentially inconsistent digest.
- Commands are hidden on non-`file://` locations and when no item is under
  the cursor; directories receive a status message after invocation, and read
  errors produce an alert rather than a traceback.
- No background work exists when the commands are not used; the public
  `fman` API is unchanged.

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
