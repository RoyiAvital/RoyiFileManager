# ChecksumFiles

Bundled plug-in using RoyiFileManager's public `fman` and
`fman.ui` APIs. Current source is smoke-tested with
CPython 3.14.7, PyQt 5.15.11 and Qt 5.15.15 on Windows x64. Remaining Total
Commander / Double Commander interoperability checks are pending.

## Delivery

ChecksumFiles lives beside the other application plug-ins and is included by
`python build.py freeze`. No separate installation is needed. Source runs use
the development environment's BLAKE3 dependency; frozen builds validate and ship
the pinned private native package and its license. A missing or mismatched native
artifact fails the build instead of silently dropping BLAKE3 support.

Fully exit the application before upgrading. If an earlier standalone copy was
installed under `UserSettings/Plugins/Third-party/ChecksumFiles`, remove that
copy before starting a build that bundles it. Do not keep duplicate installations.
`Reload Plugins` and `Remove Plugin` manage user-installed plug-ins, not this
bundled copy; application updates replace it.

The results require a host with the `show_quick_table(columns=..., rows=...)` API.
Existing portable binaries need a rebuilt application, not just replacement
plug-in resources; the older supplied 0.10.2 and 0.11.0 hosts lack this API.
Current portable-build validation remains pending.

## Standalone Packaging

For a compatible host that does not already bundle ChecksumFiles:

With the existing CPython 3.14 Windows x64 environment and BLAKE3 1.0.10 installed:

```powershell
python src/main/resources/base/Plugins/ChecksumFiles/package.py --output target/ChecksumFiles
```

The command refuses an existing output directory. It copies the pinned native
artifact, its license, defaults and source into an offline installable directory.
No package installation, network access or application rebuild is performed.
`package-manifest.json` records each shipped file's SHA256 and runtime requirements.

Exit RoyiFileManager, place the resulting `ChecksumFiles` directory under
`UserSettings/Plugins/Third-party/`, and restart. Do not install the source
directory alone: it deliberately does not contain the native dependency.
The package requires the host's matching `python314.dll`, Visual C++ runtime and
Windows Universal CRT. These host components are not redistributed by this plug-in.

After BLAKE3 has been used, fully exit the application before updating or removing
the plug-in. Reloading Python modules does not release the Windows native DLL lock.
Standalone native reload passed in the source loader, including cancellation
during hashing. In bundled source and portable hosts, Reload Plugins preserves
the existing checksum owner and hashing still works afterward.

## Commands

- **Generate checksum file**: marked files and folders are included; folders recurse.
  With no marked selection, the entire current folder is included, regardless of
  the cursor. Choose an algorithm and output filename; the suggestion uses the
  current folder's name, or `checksums` at a drive/share root. Replacing a file
  requires confirmation. Cancellation or a read/change error prevents publication.
- **Verify checksum file**: uses the highlighted file when it is a discovered, supported
  checksum manifest in the current folder. Otherwise it uses the first supported
  manifest in case-insensitive filename order, independent of pane sorting; exact
  spelling breaks case-only ties. Marked selections do not affect verification.
  No supported manifest shows an alert. An unreadable or malformed chosen manifest
  reports its problems without silently switching to another file. The results
  title identifies the chosen manifest. Cursor movement after capture cannot
  change the choice, and no manifest picker opens.
  The results open in a non-modal table with the summary above it, so files can
  be inspected while it stays open. It lists every result when the complete
  view fits the display limit; otherwise it lists only problems and the summary
  says so. Problems include mismatches, missing files, unreadable files and
  invalid records. Use the column filters (for example on Status) to narrow the view.
  Ctrl+Enter or double-click on a path goes to the file; Enter or Escape closes
  the results.

Supported algorithms: CRC32/SFV, MD5, BLAKE3, SHA1, SHA224, SHA256, SHA384, SHA512,
SHA3_224, SHA3_256, SHA3_384 and SHA3_512. SHA256 is the default. CRC32, MD5 and SHA1
are compatibility checks, not protection against deliberate tampering. Manifests
are not signed or authenticated.

## Preferences

Override `ChecksumFiles.json` through the host's user settings:

```json
{
  "default_algorithm": "sha256",
  "filename_encoding": "utf-8-sig",
  "unix_format": false,
  "chunk_size_mib": 4,
  "blake3_threads": 0
}
```

Windows output defaults to UTF-8 BOM, CRLF and backslashes. `filename_encoding`
also accepts `utf-8`. Unix format uses BOM-free UTF-8, LF and forward slashes.
Readers accept strict UTF-8 with or without BOM. Hashes always use raw file bytes.
SFV output includes a standard comment header to disambiguate BOM-like filenames.
Algorithm choices do not overwrite the saved default. Chunk size is 1-64 MiB;
BLAKE3 threads are 0-16, where 0 uses at most four on files of at least 16 MiB.

## Safety And Limits

Local/UNC folders are supported, including a navigated root reached through a
junction or mount point. The chosen root is trusted; links, junctions, reparse
points and offline placeholders below it are not followed. Verification reports linked entries as
problems. Unsafe manifest paths, duplicate normalized paths and malformed records
are rejected; file changes are checked around streaming reads.
Verification reuses up to 256 validated directory paths per run; each file still
gets fresh checks. Concurrent redirection of an already checked directory is
outside the non-hostile-concurrency guarantee.

Results retain at most 9,999 entries within a 16 MiB display budget.
Verification continues counting after display truncation, prioritizing problems.
Show all is unavailable when the entire result set cannot fit; "truncated" is
reported only if problem rows were omitted. Duplicate-path
bookkeeping exhaustion, cancellation or manifest read/change failures are Incomplete.
An empty manifest is never All matched. Filtering searches only retained rows;
the background menu remains available when the filter hides every row.

Generation uses a temporary sibling and replacement after final checks. It is
not a directory snapshot, a power-loss guarantee or protection against hostile
concurrent namespace changes. Other names hard-linked to an old manifest remain
eligible inputs. The destination pathname and current temporary file are excluded.

The production verifier passes 415 checksums from five supplied Windows TC
profiles. All twelve algorithms pass Windows/Unix writer-reader roundtrips;
those roundtrips do not establish TC/DC interoperability. The portable smoke
exercises bundled discovery, both commands, case-aliased overwrite, all backends
and continued hashing after user-plugin reload.
The other seven TC algorithms, genuine Unix/DC profiles, reverse verification in
TC/DC and live UNC storage remain unverified. The actual Remove plugin UI remains
unverified for standalone installations; it does not list bundled plug-ins.