# Calculate File Hash

- `Ctrl+H` / `Calculate File Hash`: hash the cursor file with the configured
  default (SHA-256 initially), without an algorithm prompt.
- `Calculate File Hash By`: select an algorithm in QuickSearch, then view the
  result. Escape in the picker cancels without hashing or opening a result.
  The target file is captured before opening the picker.
- Both commands reuse the centered result window, with the full file path as
  its title and visible heading. Long paths elide with a full-path tooltip.
- The title beside the copy icon is `Hash Algorithm: <Algorithm>` and identifies
  the displayed digest. The output tooltip includes the full path and algorithm.
- There is no hash panel. Run either command again to calculate another hash;
  neither command changes unrelated docked tools.
- The top-left copy icon and Return/keypad Enter in the output copy the entire
  digest. Successful calculation focuses the output for immediate keyboard
  copying. Ctrl+C copies selected text. Copy leaves the window open.
- Escape or closing the result ends its session and cancels pending work.

Only regular local files are supported. Large hashes use the standard progress
dialog with Cancel. Files changed during hashing are rejected; cancellation of
a recomputation retains the previous result with an explicit status. This is
ordinary concurrent-change detection, not an atomic filesystem snapshot.

Available algorithms are SHA-256, SHA-384, SHA-512, SHA3-256, SHA3-512, BLAKE2b,
BLAKE2s, MD5, SHA-1, and CRC32, subject to runtime availability. MD5/SHA-1 are
legacy algorithms, and CRC32 is non-cryptographic. Use them only when needed to
match a published checksum, not for collision-resistant security decisions.

## Settings

Override bundled defaults in
`UserSettings/Plugins/User/Settings/CalculateFileHash (Windows).json`:

```json
{
  "default_algorithm": "sha256",
  "remember_last_algorithm": false,
  "auto_copy": false,
  "chunk_size_mib": 4
}
```

An invalid default falls back through SHA-256, SHA-512, SHA-384, SHA3-256,
SHA3-512, BLAKE2b, and BLAKE2s, with a warning. No available strong fallback
means an error; weak algorithms are never selected silently. An explicitly
configured available algorithm is honored. Chunk size is clamped to 1-64 MiB;
invalid types use 4 MiB.

`remember_last_algorithm` saves an accepted picker choice or explicit algorithm
argument, and leaves other stored settings unchanged. `auto_copy`
copies only a successfully published current
result. Nothing monitors the clipboard or hashes in the background while idle.
Comparison and alternate copy formats are not included.

Custom bindings can pass `algorithm`, for example:

```json
{ "keys": ["Ctrl+Alt+H"], "command": "calculate_file_hash", "args": {"algorithm": "sha512"} }
```

The command also accepts a local fman `url` for explicit-target recomputation.
The generic OutputTextBox remains available through `fman.ui` if this plug-in
is removed.