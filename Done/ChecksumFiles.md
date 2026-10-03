# Checksum Files

Status: Moved to Done at the user's request on 2026-10-03. Implemented as a bundled
plug-in, including highlighted-manifest selection and normal build delivery.
Compatibility gates remain open; earlier Pending statements below are historical.
Source and supplied portable host 0.10.2 pass focused checks.
The five supplied TC Unicode profiles are verified through the production engine;
remaining TC/DC, network-storage and native removal-UI checks stay open.
S1 and I1-I8 are addressed in the reviewer-feedback follow-up below; unrun and
unresolved release checks now have a Pending home in CodeReview099.
The summary-free result menus and screenshots are implemented in the follow-up
below. They require the updated host Table API; earlier portable-host passes do
not validate this revision, and a fresh portable build remains unverified.

## Task

Implement a fast, bundled RoyiFileManager plug-in
for recursive checksum files interoperable with Total Commander (TC) and
Double Commander (DC). Expose exactly two commands:

- **Generate checksum file** (`generate_checksum_file`).
- **Verify checksum file** (`verify_checksum`).

**SHA256 is the generation default**, stored in the plug-in preference file.
BLAKE3 remains available as an accelerated alternative.

## Scope

- Generate one manifest in the active pane's current directory. Explicitly
  selected files are inputs; selected folders contribute their regular files
  recursively. With no explicit selection, use the entire current directory
  recursively. The focused item alone is not a selection.
- Within those input roots, pane filters, ignore lists and hidden/system
  visibility do not restrict traversal. Never expand a nonempty selection to
  the whole directory because selected inputs are empty, excluded or invalid.
- Discover supported manifests directly in that directory. Use the highlighted
  file when it is among those manifests; otherwise use the first in case-insensitive
  filename order, breaking case-only ties by exact spelling. No manifest picker.
  Verify all its relative subdirectory entries and default results to problems.
  Marked selection does not choose the manifest or restrict verification.
- Support the 11 algorithms common to the visible choices in the supplied
  TC 11.58 and DC screenshots, plus MD5 as an explicit user-requested exception:
  12 algorithms total. XXH3_128 and BLAKE2S remain excluded. Unshown dropdown
  entries are not assumed; this does not claim that DC cannot implement MD5.
- Target Windows `file://` directories, including mounted/UNC storage. Reject
  archive, search-result and other virtual locations without extracting files.
- Defer per-file/per-directory output, legacy encodings, arbitrary renamed/generic
  manifests, exotic escaping, variable-length BLAKE3, signatures, repair,
  monitoring and detection of files absent from a manifest.
- Trust the navigated root, including a junction or mounted location. Below it,
  do not follow symbolic links, junctions or other reparse points, including cloud
  placeholders; report exclusions. Hash ordinary `.lnk` files as bytes and regular
  hard-linked paths individually. Empty directories have no checksum record.
- Preserve public `fman` APIs, existing Calculate File Hash commands and shortcuts.
  No Core changes, Registry writes or automatic dependency installation/downloads.
- No docked panel or `show_panel` integration. Use existing prompts/pickers,
  the Task progress dialog and a standalone results Table. No new host toolbar,
  inline-toggle API or additional registered command is part of this task.

## Design

### Independent Ownership

Use the bundled plug-in layout alongside CalculateFileHash and Favorites. The
plug-in owns its commands, preferences, engine, manifest parser/writer and UI
state. Keep these in a `checksum_files` package with packaged defaults, README,
focused tests/reference fixtures and a private native-dependency directory.
Normal source startup and `clean` / `freeze` builds must include it without user
installation. This supersedes the earlier third-party-only delivery decision.

Source lives in [ChecksumFiles](../src/main/resources/base/Plugins/ChecksumFiles/README.md).
[engine.py](../src/main/resources/base/Plugins/ChecksumFiles/checksum_files/engine.py) owns formats,
paths, hashing and bounded results; [commands.py](../src/main/resources/base/Plugins/ChecksumFiles/checksum_files/commands.py)
owns public command/Task/Table integration. The repository's existing unit and Qt
harnesses own the focused tests. [package.py](../src/main/resources/base/Plugins/ChecksumFiles/package.py)
copies pinned installed native bytes and their license into a standalone directory,
recording file hashes and host runtime prerequisites. It performs no installation
or download. Python/CRT/Windows DLLs remain prerequisites supplied by the host,
not duplicate private Python runtimes.

[application.spec](../application.spec) includes the canonical plug-in source
through the existing base resources tree and calls `native_files()` for pinned
BLAKE3 inputs. Native extensions are binary inputs; wrappers and license are
data inputs under `resources/Plugins/ChecksumFiles/checksum_files/_vendor/blake3`.
Validation fails on missing/mismatched native artifacts before freezing; there is
no generated source copy, dependency download or UserSettings installation.
Source runs use installed BLAKE3 only when no private vendor package exists;
frozen hosts never fall back to the global package, nor does a broken private
package fall back in source mode. Independent packaging remains available for
compatible hosts that do not bundle this plug-in. Remove any old third-party copy
with the application closed before using bundled delivery.

Use `DirectoryPaneCommand`, `Task`, `submit_task`, public alerts/settings and
`fman.url`. UI uses a root-exported `UiController` owner carrier with
`require_owner()`, standalone `show_table`, `TableRow` and `TableAction` from
[fman.ui](../PlugIn.md#ui-extension). No production imports from `core`,
`fman.impl` or another plug-in's private modules. Follow the streaming and
file-change detection pattern in
[hashing.py](../src/main/resources/base/Plugins/CalculateFileHash/calculate_file_hash/hashing.py)
without depending on that plug-in.

This is a RoyiFileManager plug-in, not a TC/DC binary plug-in. Its public UI
extension is provisional and fork-specific; unmodified upstream fman is not a
supported host. Declare tested host release/API and native ABI requirements.

Both the source host and supplied frozen executable report 0.10.2, CPython 3.14.7,
PyQt 5.15.11 and Qt 5.15.15. The native package is pinned to BLAKE3 1.0.10,
`cp314-win_amd64`. These are tested configurations, not inferred minimum versions
or certification of other builds. See Validation Results for actual procedures.

### Supported Algorithms

| TC label | DC label | Preference ID | Hex characters | Output extension |
| --- | --- | --- | ---: | --- |
| CRC32 (SFV) | SFV | `crc32` | 8 | `.sfv` |
| MD5 | Not shown; explicit exception | `md5` | 32 | `.md5` |
| BLAKE3 | BLAKE3 | `blake3` | 64 | `.blake3` |
| SHA1 | SHA1_160 | `sha1` | 40 | `.sha` |
| SHA224 | SHA2_224 | `sha224` | 56 | `.sha224` |
| SHA256 | SHA2_256 | `sha256` | 64 | `.sha256` |
| SHA384 | SHA2_384 | `sha384` | 96 | `.sha384` |
| SHA512 | SHA2_512 | `sha512` | 128 | `.sha512` |
| SHA3_224 | SHA3_224 | `sha3_224` | 56 | `.sha3_224` |
| SHA3_256 | SHA3_256 | `sha3_256` | 64 | `.sha3_256` |
| SHA3_384 | SHA3_384 | `sha3_384` | 96 | `.sha3_384` |
| SHA3_512 | SHA3_512 | `sha3_512` | 128 | `.sha3_512` |

Case-insensitive input aliases include `.sha1`, `.bk3`, `.sha3-<bits>` and
`.sha3` for the verified SHA3_256 profile (64 hex characters only). Reject other
digest widths for `.sha3`; do not infer other variants without reference fixtures.
Finalize extensions against fixtures from both applications. CRC32 means IEEE/SFV,
not CRC32C; SHA3 means standardized SHA3, not Keccak. BLAKE3 uses an ordinary
unkeyed 32-byte digest, not BLAKE2. CRC32/MD5/SHA1 remain interoperability choices,
not authentication mechanisms. An untrusted manifest is not proof of authenticity.

Use native `zlib.crc32` and `hashlib` backends plus the maintained
[blake3 binding](https://github.com/oconnor663/blake3-py) to the official Rust
implementation. SHA-2/SHA-3 already execute native code; do not add replacement
libraries without measured end-to-end gains and independent correctness checks.
MD5 also uses native `hashlib`, adding no dependency. Report unavailable MD5
constructors in restricted runtimes rather than substituting another algorithm.

Pin a tested BLAKE3 release/artifact hash and bundle its runtime dependencies
and licenses privately. [Upstream wheels](https://pypi.org/project/blake3) exist,
but Windows architecture/CPU, Python ABI and frozen-host imports must be proved.
No system Python, runtime pip, compiler or host-environment changes are required
of users. Missing/incompatible backends give actionable errors, never silent
algorithm substitution. Packaging BLAKE3 is a release gate, not optional support.

#### Native Dependency Lifecycle

Bundled delivery follows the other shipped plug-ins: Reload Plugins and Remove
Plugin enumerate user-installed plug-ins only. The bundled owner remains active
across that command; hashing must still succeed afterward. Replace bundled files
only while the application is closed. The explicit unload/reload and removal
checks below continue to apply to the optional standalone distribution, not a
promise that the built-in Remove Plugin command can remove application resources.

Keep native dependencies below `checksum_files`, not in another immediate
package that the external loader imports on startup. Lazy-load BLAKE3 only for
that algorithm; prove package-local imports without global-name collisions.
Unloading removes `checksum_files.*` from `sys.modules` but does not guarantee
that Windows releases the `.pyd`. Do not assume releasing hashers unloads it or
that a PyO3 extension can be initialized again after Reload plugins.

Before certifying a bundle, hash with BLAKE3, invoke the real Reload plugins
command, then hash again with the same known result in source and portable
hosts. Include reload during work: cancellation/stale-result rejection must
finish without a crash or old callbacks accessing the new owner. Failed
re-import or reinitialization blocks that bundle's release; no host-global
module retention or private loader changes are an assumed workaround.

After BLAKE3 use, supported removal/update requires a full application exit,
then deletion/replacement of the plug-in directory while the process is stopped.
Reload alone is not an unload guarantee. The built-in Remove plugin command
deletes after unloading and may fail partway on a locked `.pyd`; do not promise
atomic removal or an intercepting plug-in hook. On a disposable installation,
test real removal both before and after BLAKE3 use, recording the error and any
partial deletion. Verify that full exit followed by complete directory removal
or reinstallation recovers cleanly. Document the measured reload/removal behavior
and restart/recovery procedure in the plug-in README before release.

Source-host evidence now exists for user-installed BLAKE3 1.0.10 on Python
3.14.7, PyQt 5.15.11 and Qt 5.15.15, Windows AMD64, source metadata 0.10.2.
A disposable copy of the existing CalculateFileHash fixture privately loaded the
native package and passed the real ReloadPlugins command with actual
ExternalPlugin unload/load, followed by the same digest. The global installed
package remained independent. Filesystem removal after native use failed on
the `.pyd` with Windows error 5; this probe deleted no files before failing.
After child-process exit, removal, reinstallation and another hash/reload passed.
The probe used stub registries/context and bypassed pane-path restoration; it
does not certify the frozen host, reload during active work, or the complete
Remove plugin UI/Core filesystem route. Those remain required gates.

### Preferences

Proposed packaged `ChecksumFiles.json` defaults, merged through host settings
APIs with user overrides under `UserSettings`:

```json
{
  "default_algorithm": "sha256",
  "filename_encoding": "utf-8-sig",
  "unix_format": false,
  "chunk_size_mib": 4,
  "blake3_threads": 0
}
```

The checksum algorithm is separate from filename text encoding. File contents
are always hashed as unchanged binary bytes. Generation offers a one-run
algorithm override without replacing the saved default. Snapshot settings once
per invocation; missing keys use defaults, invalid values alert rather than
silently changing the algorithm. Validate integer chunks in 1-64 MiB and thread
counts in 0-16.

Windows output uses CRLF and backslash relative paths. Default to `utf-8-sig`,
which always writes a UTF-8 BOM, matching all five supplied corpus-v2 Unicode
manifests byte-for-byte. Keep `utf-8` as an explicit no-BOM option for the earlier
ASCII-only profile. This chooses a confirmed output profile; it does not infer
TC's automatic encoding-selection policy or claim that its dialog options were
recorded. SHA256 remains the checksum algorithm default.
Unix format uses LF, forward slashes and no BOM, overriding
BOM emission. Readers accept strict UTF-8 with/without BOM and either newline
style. Unsupported encodings give explicit errors, not guessed filenames.

### Manifest Profiles

- SFV: filename followed by eight-digit CRC, parsed from the right. Try a complete
  valid record before treating a semicolon-prefixed line as a comment: TC emits
  `;semicolon.txt` as an ordinary file entry. Otherwise allow blank lines and
  semicolon comments. Preserve leading filename spaces; do not strip records.
- MD5/SHA-family: digest, space, binary `*` marker and filename; also accept two-space
  records. BLAKE3 output uses two spaces, not ` *`. Markers do not enable text
  transformations of file contents.
- Preserve filename whitespace/Unicode and digest leading zeroes. Compare hex
  case-insensitively; remove only known record framing.
- Verification selects its algorithm from the extension/profile, not the
  generation default or digest length. SHA256/SHA3_256/BLAKE3 are distinct.
- Malformed records, invalid hex/length, empty filenames and duplicate normalized
  paths are explicit problems. Do not merge distinct case-sensitive paths.
  Bound a record to 256 KiB. Unrepresentable output filenames fail generation.
- Discover and verify `.md5` files through the same workflow as the shared
  algorithms. Recognize known excluded algorithm extensions as unsupported,
  rather than misverifying them. No arbitrary format inference.

The [TC release history](https://www.ghisler.com/history.txt) documents BLAKE3
two-space output (2022-04-11), `.bk3` (2022-08-01), filename-space preservation
(2022-08-26), SHA3 hyphen aliases (2024-12-01) and Unix/BOM handling (2020-02-09).
[Python documentation](https://docs.python.org/3/library/hashlib.html) establishes
the standard backends. All proposed profiles, including DC filename/extension
conventions, must pass real two-way checks with both applications before release.

### TC Fixture Observations

The first user-supplied TC manifests, inspected on 2026-10-02, each
contains the same 162 unique paths with CRLF endings, ASCII-only bytes and no BOM. The
SFV header identifies compatibility with TC 11.58. These observations do not
establish Unicode encoding, Unix output or reverse interoperability.

| Supplied manifest | Digest hex characters | Record framing |
| --- | ---: | --- |
| `CheckSum.sfv` | 8, uppercase | Filename, space, CRC; two semicolon header lines |
| `CheckSum.md5` | 32, lowercase | Digest, space, `*`, filename |
| `CheckSum.sha256` | 64, lowercase | Digest, space, `*`, filename |
| `CheckSum.blake3` | 64, lowercase | Digest, two spaces, filename |
| `CheckSum.sha3` | 64, lowercase | Digest, space, `*`, filename |

Independent native-backend checks passed for CRC32, MD5, SHA256 and SHA3_256
on three source files: a script, a nested PNG and an executable with spaces in
its name. The 12 comparisons read 175,454 source bytes and confirm `.sha3` as a
SHA3_256 input profile for this sample. Do not infer an algorithm from a generic
64-character digest or treat a supplied name as TC's default output name.

BLAKE3 record formatting was checked, but digest verification was not run at
that inspection: the native binding was not installed. No dependency was installed, corpus copied
into the repository or large archive/model file hashed. Reproduce the spot check
with the existing interpreter's `zlib.crc32`, `hashlib.md5(usedforsecurity=False)`,
`hashlib.sha256` and `hashlib.sha3_256`, comparing unchanged binary bytes with the
corresponding manifest entries. These were historical spot checks, not a
retained or reproducible reference set; corpus-v2 coverage below supersedes them.

After the user installed BLAKE3 1.0.10, all three corresponding BLAKE3 digests
also matched the supplied TC manifest. Empty/`abc` known vectors passed, as did
17 MiB in-memory streaming at 4 MiB chunks with 1/2/4 threads and reset/reuse.
No large corpus files were hashed and these checks are not performance measurements.

### Reproducible Reference Corpus

[generate_checksum_fixtures.py](../src/misc/generate_checksum_fixtures.py) owns
corpus v2: 83 files, 29,375,536 bytes, with fixed bytes, relative paths and file
timestamps. Its canonical inventory SHA256 is
`65ee48bccd569a243e63259bc93a367d4febfda983d08190274dba1e2e3f15dd`.
Changes to these inputs require a new corpus version and regenerated references.

Run `python src/misc/generate_checksum_fixtures.py <empty-directory>`; verify
with the same command plus `--verify`. No fixed machine path is embedded in the
generator or tests. It refuses nonempty destinations and never deletes inputs.
Payloads live directly in the chosen directory: 26 root files plus nested
folders, without a `data` wrapper. Root samples include Unicode, leading spaces,
semicolon/hash punctuation, binary formats and repeated basenames also found in
subfolders. Verification allows additional root files with supported checksum
extensions and leaves them untouched; unexpected ordinary files and nested
manifests are rejected.

Coverage includes empty files/directories, repeated basenames in different
folders, spaces/punctuation, NFC/NFD names, multiple scripts and non-BMP Unicode,
UTF-8/BOM/UTF-16/UTF-32 contents, mixed line endings, all byte values, valid
PNG/WAV/stored-ZIP files, paths over 260 characters, block/chunk boundaries and
a file over the BLAKE3 parallel threshold. No private data, links, privileged
attributes or executable fixture programs are used. Invalid manifest paths,
malformed encodings/records, link/permission failures and oversized result sets
will be synthesized by focused tests rather than mixed into valid TC inputs.

TC handoff: stay at the generated root, explicitly select the fixture files and
folders, and generate one recursive manifest per supported algorithm in the root.
Exclude every previously generated reference manifest from the selection.
Capture normal Windows output and Unix-format
variants where available; record exact TC version, algorithm and encoding/BOM/
Unix options, including warnings. SHA256 Unicode output is the first priority.
Do not rename inputs or edit/normalize the resulting manifest bytes.

The five supplied corpus-v2 references are retained in
[references.json](../src/unittest/resources/ChecksumFiles/v2/references.json),
with per-file SHA256/lengths and base64-encoded original bytes. This avoids Git
newline conversion and adding a Git LFS fixture dependency without changing
attributes. The SFV compatibility header says 11.58; exact application build
and dialog options were not separately supplied and remain null in metadata.

[test_checksum_fixtures.py](../src/unittest/python/fman_unittest/test_checksum_fixtures.py)
regenerates corpus v2 in a TemporaryDirectory, decodes/copies the references to
that root and verifies every entry independently of the original folder, TC
installation or network. All 415 digests (83 files for CRC32, MD5, SHA256,
BLAKE3 and SHA3_256) pass. All five have a UTF-8 BOM, CRLF and relative backslash
paths; native digests re-encoded in reference order reproduce their exact bytes.
Coverage includes 26 root files, the 289-character relative path, NFC/NFD and
non-BMP names, leading spaces and root/nested semicolon-prefixed filenames.

The reader/re-encoder is a deliberately narrow test helper for these observed
profiles, not the production checksum engine. Keep golden bytes unchanged;
derive corruption/deletion/unsafe-record cases from disposable copies. Do not
commit the 28 MiB payload tree or use self-generated manifests as the oracle.
The remaining seven algorithms, Unix/DC variants, reverse checks in TC and the
production parser/writer still require their planned validation.

### Windows Path Handling

Keep validated, absolute logical paths separate from native I/O paths. A small
plug-in-owned helper follows Core's
[staging path convention](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py#L410)
without importing it: convert drive paths to `\\?\C:\...` and UNC paths to
`\\?\UNC\server\share\...`; an already validated extended-length path is
idempotent. Normalize and validate logical paths before adding the prefix;
reject device namespaces, alternate streams and traversal rather than passing
untrusted manifest text to this helper. No Registry or system long-path setting
changes are required.

Use the extended-length form consistently for root/manifest discovery,
`os.scandir`, file and manifest open, stat/lstat, staging creation, cleanup and
both operands of `os.replace`. Continue checking redirected components. Keep
manifest entries relative and prefix-free; preserve selected-folder prefixes.
Display and public Table navigation use validated logical paths, not the I/O
prefix or escaped display cells. Unsupported filesystem/component length limits
are explicit errors; do not truncate names or silently retry a shorter path.

The captured root and ancestors are the user's chosen location; do not reject
them solely for redirection. Check components below that boundary and reject
reserved Windows aliases with `ntpath.isreserved`, including spaces before an
extension. Verification caches up to 256 successfully validated directories per
run, never file checks or errors. Beyond that cap, uncached directories are checked
again. The cache is discarded after the run. This uses the documented non-hostile
concurrency model: retargeting an already checked directory is not detected by
every later record. Generation's destination-parent check before publication is
uncached. Directory traversal reuses non-following `DirEntry.stat` metadata.

### Generate checksum file

1. Capture the invoking pane's current directory and explicit selection through
  `pane.get_selected_files()` before opening generation prompts. Both public
  getters marshal to Qt; guard the pair with temporary `pane.on_path_changed()`
  cancellation and reject navigation during capture. Always unsubscribe that
  guard afterward, including exceptions/cancellation. An unstable snapshot is
  rejected, never converted to empty-selection whole-directory fallback. Do not
  use `get_chosen_files()` or `get_file_under_cursor()`: a focused item alone
  must not replace the whole-directory fallback. Snapshot preferences and pass
  the root, selected URL tuple and settings as immutable data to the worker.
  An empty selection tuple means the current directory is the single input
  root. Later selection changes or navigation never retarget this request.
2. Use `show_quicksearch` for a one-run algorithm choice, initially selecting the
  saved default without saving the choice. Use `show_prompt` for the output
  filename; its label includes the captured root, input scope and algorithm.
  Suggest `<directory-name>.<extension>`, using `checksums` at a filesystem root.
  Require a single filename in that root with the proper extension; confirm
  replacement of an existing regular manifest through `show_alert`. Canceling
  any prompt starts no traversal or output. Check owner/pane lifetime after
  each prompt. No persistent generation form or panel is created.
3. Validate and classify inputs on the command worker, rejecting unsupported or
  outside-root URLs. Process selected regular files directly; traverse each
  selected ordinary directory iteratively with `os.scandir`. Collapse duplicate
  or overlapping input roots without merging distinct case-sensitive paths or
  regular hard-linked paths. Do not enumerate unselected sibling subtrees.
  Missing/unreadable selected inputs are errors, never a reason to broaden scope.
  Keep every entry relative to the captured current directory, retaining a
  selected folder's prefix. Apply the existing reparse-point exclusions and
  exclude only the destination pathname and this operation's temporary output.
  Other hard-link names for the old destination remain ordinary inputs:
  replacement rebinds the destination name without modifying their old bytes.
  Other existing checksum files remain ordinary inputs.
4. Hash sequentially in chunks, checking cancellation between entries/chunks.
   Compare identity, size and modification time using handle stats before/after
   reading and a final path stat. Detected changes are errors, not valid digests.
   Enumeration is a live traversal, not an atomic tree snapshot.
5. Stream records to a uniquely created temporary sibling. Any traversal, read,
   encoding or change error prevents publication and reports the affected path.
   Do not publish partial output as a successful manifest.
6. Flush/close, recheck cancellation and destination identity, then atomically
   replace in the same directory where supported. Refuse redirected targets or
   destinations changed since confirmation. Before-commit cancellation removes
   staging; after commit report completion. Preserve prior output on failure;
   report cleanup errors. Empty input alerts without creating a manifest.

Report file/byte totals and exclusions. Only the requested manifest and staging
sibling are written in the source tree. No power-loss durability or concurrent
namespace transaction guarantee.

### Verify checksum file

1. Capture the highlighted file with the root/settings under the existing
  path-change guard. Discover manifests in the current directory on the command
  worker, independent of pane filters, excluding unsupported algorithms and
  redirected/non-file entries. None: alert **No checksum file found in the current folder.**
  Prefer the captured highlighted path when it is among the supported manifests;
  otherwise choose the minimum `(filename.casefold(), filename)`. Exact path
  membership preserves distinct case-sensitive filenames. No picker or marked
  selection lookup. Later cursor changes do not retarget the operation. A read,
  parsing or mutation problem in the chosen manifest is reported without trying
  another manifest. Its filename remains in the Task and results titles.
2. Parse the manifest and resolve entries against its parent, not process CWD or
   a later pane location. Reject absolute, drive-relative, UNC/device, `..`,
   alternate-stream and Windows-aliased paths. Allow harmless `./` or `.\`.
   Never expand variables, URL-decode or execute manifest text.
3. Reject redirected components and outside-root targets before reading. These
   checks protect against static unsafe manifests, not an attacker concurrently
  replacing directories. Files reached through a symlink, junction or other
  reparse point, including cloud placeholders, receive **Skipped: link**.
  Do not open the redirected target; this status is a problem and prevents
  All matched. Unsafe path syntax remains a separate error. Apply generation's
  file-change checks to ordinary targets.
4. Continue past individual mismatches, missing/unreadable/changed files and
   malformed/unsafe records, retaining each problem. A manifest read failure or
   detected change makes the entire run Incomplete. Verification writes neither
   the manifest nor targets; files absent from the manifest are not scanned.
5. Show **Relative Path**, **Status**, **Expected**, **Actual**, **Details**;
   parser errors include line numbers, failed reads have no invented digest.
  Default to the problems-only view, including every non-Matched failure.
  Offer all results only when the complete set fits the display budgets below;
  menu changes never reread or rehash. Count all processed results even when
  their rows cannot be retained, and show explicit omitted-row totals.
  Escape NUL/control characters and invalid Unicode surrogates before creating
  any display cell. Bound each escaped cell to 4,096 characters with an explicit
  truncation marker; display shortening never changes paths used for I/O.
  Keep raw diagnostics separately within the retention budget and use short
  line-based record IDs. Invalid/link records have no navigation target.
6. **All matched** requires complete processing, at least one valid record and
   zero problems. Empty/comment-only input is not success. Cancellation retains
   completed rows with **Canceled / Incomplete**, never an all-matched claim.
  Display truncation alone does not make completed verification Incomplete;
  it is always reported separately. Exhausted parsing/safety budgets do stop
  processing as Incomplete, with counts labeled as processed-so-far.

### Speed And Lifetime

One active operation uses the existing command worker and sequential file I/O;
native BLAKE3 may parallelize within large files. No per-file processes/threads.
Reuse bounded buffers and the documented BLAKE3 `reset()`/hasher pool where
appropriate; test alternating large, empty and small files for state leakage.

`blake3_threads=0` uses a bounded automatic policy: serial below 16 MiB,
up to four native threads for larger files, leaving a logical CPU available
where possible. One forces serial; 2-16 caps the large-file path. One operation
reuses its buffer and serial/parallel hashers, resetting between files. The local
measurements support retaining the 4 MiB default and bounded large-file path;
mixed-file measurements also show the parallel-startup tradeoff. No unlimited
`AUTO` pool or universal speed claim is made.

Benchmark 1/4/8/16 MiB chunks and 1/2/4 threads on real large/mixed/small-file
workloads. Disk/network I/O may dominate; BLAKE3 is not universally fastest.
Use chunked reads, not whole-file buffers or memory mapping, for cancellation and
changing/sparse-file handling. Additional acceleration packages require clear
measured gains, maintained implementations and simple portable packaging.

Use the normal `submit_task` progress dialog for running work and standalone
`show_table(modal=False)` without a `panel` argument for completed or canceled
results. No panel, inline checkbox or custom toolbar is part of this design.
Coalesce Task progress to ten updates/second maximum, not one callback per file.
Widgets/models remain host-owned on Qt; workers exchange immutable plain data.

The table API limits each snapshot to 10,000 rows/16 MiB. There is no paging.
Prepare a bounded problems snapshot on the worker, with at most 9,999 file/problem
rows and no synthetic summary row. Count IDs, cells and row values in
UTF-8 bytes, preserving the existing 64 KiB headroom below the 16 MiB limit. Do not put
raw diagnostics into Table payloads. Stop retaining problem rows at the first
row/byte/retention limit, but keep verifying and counting subsequent records.

Keep an all-results candidate only while the entire processed set fits the same
limits. On overflow, discard that candidate and disable **Show all results** for
this run; never offer a partial all-results view. Share immutable records between
the candidates and bound their combined retained display/raw payload to 32 MiB,
plus object overhead. Prioritize problems when the combined budget is reached;
if problems alone exceed it, retain only the bounded prefix and count omissions.
This replaces the 200,000-record retention and multi-page browser.

After processing ends or is canceled, freeze the available snapshots. Supply
`get_menu` and the optional `get_background_menu` with `TableAction` records for **Show all results** and **Show only
mismatches** only when the full processed set fits; otherwise show the problems
snapshot alone. The mismatches label retains the existing non-matched results,
including missing/unreadable files and invalid records. These fast Qt callbacks select a prepared snapshot and call
`TableHandle.refresh()`, with no I/O or plug-in-side whole-set filtering.
Switching retains the Table's text query. The host still validates the bounded
snapshot on refresh; measure maximum-size refresh latency in the Qt checks.

No Summary row is inserted, including All matched, empty or canceled verification.
Use `summary` for terminal status/global totals above the table and `get_count_text`
for the active view's retained result count. The empty-background menu remains
available even when the selected view or text filter has no visible rows.
Its provider takes no arguments; actions receive `(None, -1)`, without invoking
row-menu or path-resolution callbacks. Existing callers opt in explicitly and
otherwise keep their prior behavior. Stale actions and owner/window closure are
guarded as for row menus, and cleanup releases the additional callback.
Totals remain visible with zero matches. If rows are omitted, `summary` states the
omitted problem count and **Results truncated**; unavailable all-results also
states the limiting row/byte budget. Do not imply that filtering searches omitted
records. Menu usage is documented with generated screenshots, not repeated in
the summary text.

Keep Copy Path/Go To disabled for invalid and Skipped: link records by returning `None`
from `resolve_path`. Pass the captured manifest parent as `base_path` explicitly.
Valid targets use captured authoritative paths, never escaped display cells or
the pane's later location. Text filtering applies only to the retained view.

Bound duplicate-path bookkeeping separately to 16 MiB of normalized UTF-8 keys,
plus object overhead. Exhaustion stops parsing as Incomplete rather than silently
losing duplicate detection. This processing limit is distinct from display
truncation, which never stops hashing. No disk-backed result store or paging.

Prompts capture one-run choices; Table callbacks select prepared views.
A busy guard prevents overlapping operations. Cancellation uses the Task dialog,
pane closure or owner invalidation, not a panel token. Register plain cancellation
and cleanup with the owner and `pane.on_closed`; Table `on_closed` releases
retained results. Navigation/selection changes after capture never retarget a run.
Owner/handle/request identity rejects stale updates. Keep explicit completion because
`submit_task` can consume `Task.Canceled`. Release native pools after operations
and retained results on session close. No persistent hash cache/history.

## Alternatives

- Third-party-only delivery or post-build installation into UserSettings: rejected
  by the user. Keep one canonical source beside the other shipped plug-ins and
  collect private native files through the existing PyInstaller spec.
- Always hash the whole directory or fall back to the focused item: rejected.
  Explicit selection controls generation; only no selection means the whole
  directory. Verification entry coverage remains manifest-driven rather than
  limited by marks; the captured cursor only chooses which manifest is verified.
- BLAKE3 default: fast alternative, but SHA256 is the user's chosen default;
  preserve it even when BLAKE3 is available.
- Entire TC/DC algorithm union: rejected in favor of the screenshot intersection
  plus the explicitly requested MD5 exception.
  SHA-3 costs no additional dependency and no hashing work unless used.
- External executable/handwritten hashing: adds protocol or correctness burden
  compared with maintained native libraries. Never use shell-interpreted paths.
- Replace every native standard backend: only justified by measured gains that
  outweigh deployment complexity.
- Core/private API implementation or unlimited tables: unnecessary for a bounded,
  independent plug-in; defer extras instead of altering host ownership.
- Docked panel: excluded by the user. Table context menus supply bounded view actions;
  an optional background-menu callback keeps them accessible without result rows.
  A synthetic Summary row was rejected as redundant with the summary above the
  table. Inline toggles and toolbars remain outside this task.
- Large retained result sets with context-menu paging: rejected. Bounded problem
  rows, complete counts and conditional Show all are simpler; oversized full sets
  are not browsable in this version, and that limitation is explicit.

## Runtime Effects

- Bundling adds ordinary plug-in registration and packaged native files, without
  startup staging, copying or dependency probes. Native file hashing/pin checks
  happen at build time; source BLAKE3 import is lazy and only used for that algorithm.
- Startup/idle: registration only when loaded; lazy settings/backend loading.
  Disabled/unused plug-in has no feature jobs, scans, probes, timers or I/O.
- CPU/I/O: linear in entries and bytes hashed, one content read per included
  file. Selection capture runs once per invocation, not on recurring signals.
  Verification adds one cursor getter within the capture guard and one linear
  supported-manifest choice after discovery; no additional scans, sort or timers.
  No unselected-subtree scans or preliminary pass solely for progress totals.
  Hashing itself costs four metadata calls: pre/post-read handle stats and
  initial/final non-following path stats. Verification adds a fresh file-path
  check and shares ancestor checks through its bounded per-run directory cache.
  A ten-file regression uses 33 `lstat` calls at root depth and 43 at depth ten,
  plus 22 `fstat` calls in either case (including manifest checks). Uncached
  directories after the 256-entry cap add repeated checks; live UNC latency is
  still unmeasured. Generation classifies walk entries using `DirEntry.stat`
  rather than an extra path-based `lstat` for each directory entry.
  Existing-output filename spelling is resolved through a non-following Windows
  handle to exclude capitalization aliases without excluding other hard-link names.
- Memory: reusable default 4 MiB buffer, bounded native/traversal state;
  generation also retains a snapshot proportional to selected input count.
  Verification retains at most 32 MiB of result/display/raw payload and 16 MiB
  of duplicate-path keys, plus up to 256 checked directory paths and Python
  object overhead; no per-page snapshots. Row accounting escapes cells once and
  stops for discarded rows while verification and result counts continue.
- Threads: one host worker, a bounded native BLAKE3 pool only for applicable
  operations, no extra process or recurring work after completion.
- Cancellation: between entries, records/chunks and before output commit.
  A blocked OS/network read can delay worker exit but must never block Qt;
  no promise of interruptible filesystem calls.
- UI: pickers/prompts and Task progress only during an invocation; results use
  a standalone Table with no panel dock, panel timer or panel token. Menu view
  changes reuse prepared data and start no scan, hash job or worker.
- Persistence: overrides under `UserSettings`; no Registry/network activity.
  Normal failure/cancel removes staging. A crash can leave a temporary sibling,
  not a published partial manifest. No automatic startup cleanup scan.

## Tests

- Command Palette: command aliases are class-level tuples, as required by
  PaneCommandRegistry. Test the real registry lookup and actual palette
  suggestions for empty and checksum-filtered queries in source/frozen hosts.
- Bundled delivery: assert normal discovery, source hashing, frozen no-fallback,
  spec-expanded source/default/native/license inputs, and rejection of wrong
  native versions, altered bytes and missing licenses. Run actual source startup
  and a disposable portable host with spec-selected bundled files and no
  third-party ChecksumFiles copy. Check commands, twelve algorithms, standalone
  Table behavior and retained ownership after Reload Plugins. A new freeze is
  a separate manual packaging gate, not implied by the existing-host smoke.
This is the required verification matrix; completed checks and open gates are
distinguished in Validation Results. Use the existing interpreter and repository
environment. No new environment or package installation is required.

1. `python -m unittest src.unittest.python.fman_unittest.test_checksum_files`: independent vectors for all 12
   algorithms; binary/empty/chunk-boundary data; serial/parallel equality and
   BLAKE3 reset. Test encoding/profiles, spaces/Unicode, malformed/unsafe input,
   duplicates, self-exclusion, recursion, mutations, cancellation/output failures.
  Check that destination/staging names are excluded but other hard-link names
  for the old destination are hashed and still verify after replacement.
  Test drive/UNC prefix conversion, already-prefixed native paths, rejection of
  device/traversal/stream input and deep-tree paths beyond 260 characters through
  discovery, generation, verification, overwrite, cancellation and staging cleanup.
  Assert relative prefix-free manifest entries. Link/junction/cloud exclusions
  must produce Skipped: link, keep All matched false and never read the target.
  Cover individual file roots, recursive folder roots, mixed/overlapping inputs,
  preserved folder prefixes and no enumeration of unselected sibling subtrees.
2. `python -m unittest src.unittest.python.fman_unittest.test_checksum_files.ChecksumCommandTest`: exact command IDs, SHA256 default,
   preference override validation, filter-independent roots, zero/one/multiple
   manifests, excluded algorithms, missing backends/no fallback, busy guard and
   canceled completion. Assert no private imports or disabled/unused feature work.
  Test focused-only/no-selection -> whole directory, explicit selection with
  focus elsewhere -> selected inputs only, selected folders recursively, and
  empty/excluded/missing selections without whole-directory fallback. Changing
  selection after capture must not retarget inputs. Test navigation between
  root/selection reads and removal of the capture guard. Test cancellation of
  algorithm/filename/replacement prompts without traversal/output. Verification
  prefers the captured supported manifest, otherwise uses case-insensitive filename
  order with an exact-spelling tie-breaker. Cover zero/one/many candidates, ordinary
  or unsupported highlighted files, directory/foreign paths, marked-selection
  independence, cursor movement after capture, capture instability, no picker,
  and no retry after problems in the chosen manifest. Assert no `show_panel` use
  or extra registered command.
3. `python -m unittest fman_integrationtest.test_qt.ChecksumFilesIT`: reuse the shared Qt harness;
   thread affinity, default filter/failure visibility, empty all-matched view,
  context-menu view changes, retained/global counts, Task cancel, Table/pane close,
   unload and stale results. Run offscreen then native at 100%/150% with long
  paths/narrow Table windows. Assert no Summary row with zero problems or empty
  input, correct file counts, and background menus with a no-match query.
   Test NUL-bearing malformed rows alongside valid rows, no navigation targets
  for invalid/link rows, and menu switching without I/O/rereads/rehashing.
  Assert summary text above the table, truncated/omitted totals and unavailable
  Show all explanation. Cover 9,998/9,999/10,000 records, byte-budget overflow
  below the row limit, many matches with few problems, oversized problem sets,
  and cancellation after display overflow. Verify full-set availability is based
  on every processed record, no page actions exist, and no problem is silently
  counted as matched. Exercise cell escaping/shortening and combined raw/display
  budgets; a malformed record must not prevent other rows/counts from rendering.
  Distinguish complete-but-display-truncated from parsing-limit Incomplete and
  measure the largest permitted Table refresh on Qt.
  Confirm explicit marks versus cursor-only state, Qt-thread selection capture,
  displayed input scope and stable inputs while prompts are open. Existing docks
  remain unchanged; the plug-in opens/replaces no panel.
4. `python -m unittest src.unittest.python.fman_unittest.test_checksum_fixtures`: TC fixtures for all 12 algorithms and
  DC fixtures for the 11 shared algorithms, covering supported profiles and
  recording versions/options/provenance. Include MD5 generation, discovery,
  verification and corruption regressions; add DC MD5 fixtures where available.
  Cover the five supplied record profiles, including `.sha3` discovery as
  SHA3_256 and rejection of other widths or mixed-width records for that alias.
   Preserve exact fixture bytes without repository attribute changes. Include
   corruption/deletion; a plug-in writer/reader round trip alone is insufficient.
  Reuse the imported TC Unicode-name fixtures for production parser/writer
   byte-for-byte checks, including BOM, non-Latin/non-BMP names, leading spaces
   and semicolon-prefixed SFV filenames. The current test helper passes the five
   observed Windows profiles; add genuine Unix/DC and remaining-algorithm inputs.
5. Manual interoperability gate: TC -> plug-in, plug-in -> TC, DC -> plug-in,
   plug-in -> DC for all 11 algorithms and both output profiles on the same
  disposable nested corpus, including Unicode/spaces and empty files. Add
  mandatory two-way TC checks for MD5; check DC MD5 where available and record
  its outcome separately rather than inferring support from the screenshot.
6. Offline packaging smoke: install only the independent artifact into a supplied
   portable host without system Python/BLAKE3. Exercise algorithms, preference
   persistence, disable/uninstall and missing/wrong-ABI native dependency errors.
  Test BLAKE3 -> Reload plugins -> BLAKE3 against the same vectors, including
  reload during work. On a disposable copy, test Remove plugin before/after
  native use, report locked-file/partial-removal behavior and prove full-exit
  removal/reinstallation recovery. Record actual host/Python/Qt versions and ABI.
   Request a suitable artifact if unavailable; do not rebuild the host automatically.
7. Focused performance: compare SHA256 with serial/bounded-parallel BLAKE3 on a
   large file, a 10,001-file tree and mixed files. Record wall time, bytes read,
   throughput, CPU/threads, peak memory and cancellation latency across three
   repetitions, reporting cache conditions. Test chunk/thread candidates and
   available SSD/HDD/UNC storage; document unavailable checks. Assert digest
  equality, snapshot/retention limits using synthetic rows, and update-rate bounds.
  For the 10,001-file UNC case, record metadata call counts and elapsed time
  separately from content reads so metadata costs remain visible.
   No full suite or unrelated benchmark is required.

## Implementation Steps

1. Review design, capture TC/DC fixtures and prove private native-dependency
  imports, reload and full-exit removal/recovery in the supported interpreter
  and supplied portable host. Reuse the confirmed TC Unicode/BOM references.
  Report any
   missing public loader/UI capability before proposing separate host changes.
2. Add registry, preferences and pure parser/writer; immediately run vectors and
   reference-fixture checks.
3. Add selection-scoped streaming generation, safe publication and bounded native
  acceleration; validate input roots, mutations, cancellation, write failures
  and serial/parallel equality.
4. Add discovery/verification, problem states and bounded retained results;
  validate long-path I/O, link status, safety, empty input, display truncation
  and distinct parsing-limit outcomes. Prepare only bounded problem/full views.
5. Register the two commands, public prompts and standalone Table/menu UI;
  run focused command/Qt checks,
   benchmark and finalize chunk/thread policy from measurements.
6. Complete four-direction interoperability and offline packaging checks.
   Document installation, host/ABI requirements, commands, defaults and limits
   in the plug-in README. Update application README/changelog for qualifying
  delivered changes. Document restart-required
  native removal/update, measured reload support and limited result browsing.

## Acceptance Criteria

- ChecksumFiles resides alongside the other bundled plug-ins and normal freeze
  collects both commands, defaults and pinned native BLAKE3 with its license.
  No separate installation, source duplication or runtime download is required.
- Independent installation exposes the two commands via public APIs without
  Core changes, runtime package installation or a mandatory host rebuild.
- All 12 supported algorithms pass independent vectors and TC manifest tests;
  the 11 shared algorithms also pass DC checks. MD5 generation/discovery and
  verification are included. Excluded algorithms and missing backends fail
  clearly without fallback.
- SHA256 is the preference-file default; BLAKE3 remains selectable. Filename
  encoding is separate and verification derives the algorithm from its manifest.
- The filename-encoding default is confirmed against TC Unicode-name output,
  including exact BOM/filename bytes. Native reload and full-exit removal/recovery
  pass on declared source/portable hosts with actual tested versions recorded.
- Deep drive and UNC paths use extended-length I/O for the full lifecycle while
  manifests stay relative. Link targets are not read and appear as Skipped: link,
  never as matched files or navigable result targets.
- Generation hashes explicitly selected files and folders recursively; with no
  selection it hashes the captured current directory recursively. Cursor focus
  alone never narrows scope, and later selection changes never retarget work.
- Selected folders retain their relative prefixes in the single manifest stored
  in the captured current directory. Traversal ignores pane filters within the
  chosen roots, never broadens an empty/invalid selected input to the whole tree,
  reports exclusions and never publishes incomplete output.
- No supported manifest alerts. The highlighted supported manifest wins; otherwise
  the first by case-insensitive filename/exact-spelling order wins. There is no
  picker or silent retry of another file, and the chosen filename is shown.
  Marked selection and later cursor movement do not affect entry coverage.
  Results default to problems, can
  reveal all processed results only when the full set fits, and always show
  accurate processed/matched/problem totals with explicit omitted-row counts.
- No panel is created or replaced. Standalone Table menus switch prepared
  views without rehashing or paging. Background menus are available even with no
  visible problem records, and no synthetic Summary row is present. Global totals
  remain above the table, including unavailability and truncation notices.
  No host toolbar/toggle API or additional command is required.
- Errors, cancellation, zero entries and processing limits never produce All matched.
  Display-only limits do not stop verification or conceal problems in the totals.
  Qt remains responsive; stale work is rejected; idle does no feature work.
- Acceleration is bounded, digest-equivalent and measured end to end; slower
  parallel policies are not enabled on microbenchmark claims alone.
- Focused tests, TC/DC interoperability and portable packaging gates pass.
  Missing tools/artifacts remain documented validation gaps, not successes.

## Reviewers

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Proposed the 11-algorithm screenshot intersection with SHA256 as the
  explicit default, native BLAKE3 acceleration and independent plug-in ownership.
  Uncommon formats defer; TC/DC fixtures, design review and portable native
  packaging remain implementation gates.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Added MD5 as the user's explicit exception to the screenshot
  intersection, bringing support to 12 algorithms without an extra dependency.
  Updated profiles and validation gates; SHA256 remains the default and BLAKE3
  remains available with native acceleration. No implementation performed.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Inspected five user-supplied TC manifests with the same 162 paths;
  confirmed record framing and 12 digest comparisons over three small files.
  Added the verified `.sha3`/SHA3_256 input alias and regression requirements.
  BLAKE3 digests, full-corpus and two-way interoperability remain unverified;
  the SHA256 default and design-only status are unchanged.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revised generation to use explicit selection with recursive folders,
  falling back to the whole current directory only when no items are selected.
  Confirmed the public selection getter differs from the focused-item fallback;
  added snapshot, scope, relative-path and regression requirements. The design
  is ready for review, not approved for implementation; SHA256 and all 12
  algorithms remain unchanged.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: The host-facing design is feasible as an independently installed
  third-party plug-in without Core changes or private production imports.
  Source-host contracts and an isolated Third-party installation probe pass.
  Request safe malformed-record display and clarification of consistent input
  capture before implementation. Private BLAKE3/frozen-host imports remain
  unverified. No checksum implementation, host change or dependency installation.

#### Third-Party Feasibility

- The external loader discovers immediate Python packages beneath
  `UserSettings/Plugins/Third-party/ChecksumFiles`. Export `GenerateChecksumFile`,
  `VerifyChecksum` and a `UiController` owner carrier from
  `checksum_files/__init__.py`. Class names produce the requested command IDs;
  display aliases may retain `CheckSum`.
- Public pane getters, `pane.run_command`, `Task`, `submit_task`, settings/URL
  helpers, `pane.on_closed`, `show_panel` and modeless `show_table` cover the
  proposed integration. Dispatch hashing through commands, not Qt callbacks.
  Panel cancellation and owner/handle identity cover disposal and stale results;
  explicit completion is necessary because `submit_task` consumes cancellation.
- Keep native dependencies below `checksum_files`, not in a second immediate
  Python package that the loader would import on startup. Load BLAKE3 only when
  selected. Prove package-local loading without global dependency-name collisions,
  required runtime dependencies, and frozen-host ABI compatibility before release.
  A wheel tag is not an import test; no host rebuild appears necessary, but this
  packaging route is not yet certified.

#### Review Requests

1. **P2 - Safe malformed-record display.** The host table rejects NUL-containing
  cells. A real snapshot probe with `bad\x00.txt` raises `ValueError: Cell contains
  NUL or exceeds its length limit.` Thus a retained unsafe record can prevent the
  entire results view from opening/refreshing. Keep raw diagnostics separate from
  escaped, bounded display cells; account for both in retention limits and use
  short line-based row IDs. If path roles are enabled, invalid records must have
  no navigation target. Add a Qt regression proving other rows/counts still render
  and the rejected target is never read.
2. **Capture clarification.** Root/selection getters marshal to Qt separately,
  not as an atomic pair. Specify a public-only consistency guard, for example
  temporary `pane.on_path_changed()` cancellation around the getter sequence,
  rejecting navigation during capture and unsubscribing afterward. Never turn an
  unstable snapshot into empty-selection whole-directory fallback. Test navigation
  between reads separately from navigation after a completed snapshot.

#### Feasibility Validation

The current source host reports 0.10.2, using existing Python 3.14.7 on
`win-amd64`. These checks validate host contracts, not the checksum implementation:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.impl.plugins.test_plugin','fman_unittest.test_ui_elements','fman_integrationtest.impl.plugins.test_calculate_file_hash_plugin','-q'],env=env,timeout=120).returncode)"
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); targets=['fman_integrationtest.test_qt.TableIT','fman_integrationtest.test_qt.PublicUiIT']; settings=({'QT_QPA_PLATFORM':'offscreen'},{'QT_QPA_PLATFORM':'windows','QT_SCALE_FACTOR':'1','QT_AUTO_SCREEN_SCALE_FACTOR':'0'}); sys.exit(max(subprocess.run([sys.executable,'-m','unittest',*targets,'-q'],env=dict(env,**setting),timeout=120).returncode for setting in settings))"
```

- Loader/descriptor/lifetime gate: 36 passed, no skips. Qt gate: 17 passed
  offscreen and 17 native at 100%, no skips.
- Isolated Third-party installation: copied the existing public-API
  CalculateFileHash plug-in into a disposable Third-party directory and reused
  its real loader test. Discovery, two commands, defaults, active owner, unload
  and import-path cleanup passed (one test). The first wrapper omitted a child
  `sys` import and failed its final assertion; the corrected probe passed.
- CRC32 and all ten proposed `hashlib` constructors are available with the
  specified digest widths. This does not replace independent algorithm vectors.
- BLAKE3 is not installed. Official PyPI 1.0.10 metadata lists
  `blake3-1.0.10-cp314-cp314-win_amd64.whl`, distinct from the free-threaded
  `cp314t` artifact. Metadata was queried without downloading/installing a wheel.
  No BLAKE3 digest, private import or frozen-host test ran.
- No application code, installed plug-in/settings, environment, host artifact,
  full suite or benchmark changed. TC/DC interoperability and native/portable
  packaging remain required future gates. The existing draft is preserved;
  this task remains design-only.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Revised the results direction to exclude panels at the user's request.
  Standalone Table context menus select views/pages through public `TableAction`
  callbacks and `TableHandle.refresh()`. A non-file summary/action row keeps menus
  reachable with no problem records; ordinary filtering/sorting still applies.
  No inline toggle, host change or third command is assumed. Validate the public
  menu route and align the remaining workflows/tests; implementation is unstarted.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Completed the panel-free design revision and verified the existing
  public Table menu route. The standalone menu/refresh/stale-action regression
  passed; a disposable real-Table probe passed offscreen and native Windows,
  including zero problems, view changes, paging, filter recovery, safe summary
  targets and close cleanup. Active generation, lifetime, tests and acceptance
  sections now use prompts, Task progress and standalone Table menus. Historical
  panel-based statements above are superseded, not rewritten. No plug-in or host
  implementation was created; native packaging/interoperability gates remain open.

#### Panel-Free Table Validation

Immediate host contract check:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_integrationtest.test_qt.TableIT.test_custom_menu_stale_action_and_atomic_refresh','-q'],env=env,timeout=60).returncode)"
```

One test passed. A disposable prototype then used public `show_table`,
`TableRow`, `TableAction` and handle methods against the real Table host, with a
synthetic pane fixture and canned immutable pages for three matched files:

- Created a modeless Table with no panel, five columns, captured `base_path`,
  custom menus, global summary/count text and a summary row for zero problems.
- Sent a keyboard context-menu event to that row and invoked actual menu actions:
  Show all results, Next page, Previous page, Show only problems, then Show all
  again after clearing a no-match Table filter. Asserted exact row/page contents.
- Confirmed the summary resolves to no file and offers neither Copy Path nor
  Go To; global terminal totals remain visible when every row is filtered out.
- Guarded Python `open` during all menu/page changes; the prepared-data route
  passed without file reads. No hashing engine or checksum implementation ran.
- Confirmed callbacks run on Qt and Table closure invokes cleanup once.
- Passed offscreen and native Windows at 100%. The first fixture omitted
  `base_path` and failed before menus because its pane stub lacked `get_path`;
  the corrected fixture supplied the captured base explicitly and passed both.
- This proves the host integration route, not production plug-in correctness or
  a new inline-toggle API. No panels, application code, packages, environments,
  builds, full suite or benchmarks were added/run by this revision.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Revisions required before implementation approval (D1-D4). Host
  contracts match the source: `show_table` arguments, `TableAction`, the
  10,000-row/16 MiB snapshot limit, NUL rejection and pane `on_path_changed`/
  `on_closed`. Open risks: native-module reload/removal, the BOM default versus
  the TC fixtures, long paths and oversized result paging. D5-D10 are
  simplifications or clarifications. Read-only review; no tests or probes ran.

#### Design Review Findings

| ID | Priority | Finding | Required change |
| --- | --- | --- | --- |
| D1 | P2 | **Native module lifecycle.** Unload deletes every `checksum_files.*` entry from `sys.modules` ([plugin.py](../src/main/python/fman/impl/plugins/plugin.py#L279-L282)), so **Reload plugins** re-imports the vendored BLAKE3 `.pyd` while Windows keeps its DLL loaded. PyO3 re-initialization is unverified. **Remove plugin** calls `delete` on the folder ([commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py#L1407)); a loaded `.pyd` cannot be deleted, so removal can fail partway and leave a broken plug-in. | Gate: use BLAKE3, run Reload plugins, then hash again. Define and test Remove plugin after BLAKE3 use (expected error or restart requirement). Document the result in the plug-in README. |
| D2 | P2 | **BOM default.** `filename_encoding: utf-8-sig` always writes a BOM, but all five supplied TC manifests have none. | Choose the default from a TC Unicode-name fixture (for example, BOM only for non-ASCII names, or `utf-8`). Add a byte-level comparison with TC output to `test_interop`. |
| D3 | P2 | **Long paths.** Recursive trees often exceed 260 characters. Traversal, open/stat, staging and atomic replace have no extended-length path requirement. | Specify `\\?\` and `\\?\UNC\` handling for I/O, as the Core copy staging does, while keeping manifest paths relative. Add deep-tree generation and verification tests. |
| D4 | P2 | **Result paging is overbuilt.** Retaining 200,000 records (128 MiB) in 1,000-row pages means up to 200 pages, each reached through a context menu on a summary row. Matched rows rarely need browsing. | Simplify: show problems up to the Table limit; offer **Show all** only when the full set fits; otherwise report counts and an explicit truncation note in `summary`. If paging stays, use pages near the host maximum (9,999 rows + summary), not 1,000. |
| D5 | P3 | **Hard-link alias exclusion is unnecessary.** `os.replace` rebinds only the destination name; aliases keep the old bytes, so their digests stay valid. | Exclude only the destination name and the staging file. Drop the alias identity bookkeeping. |
| D6 | P3 | **Metadata cost is not stated.** Before/after handle stats plus a final path stat mean about three metadata calls per file. This is significant on UNC shares with many small files. | State it in Runtime Effects. Measure it in the 10,001-file benchmark on UNC storage. |
| D7 | P3 | **Links in third-party manifests.** TC/DC manifests may list files reached through junctions. These currently become generic problems. | Use a distinct status (for example, **Skipped: link**) and keep it out of **All matched**. |
| D8 | P3 | **Scope wording.** Scope says "verify one selected manifest", but the Design discovers manifests and ignores the selection and cursor. | Clarify. Optionally use a manifest under the cursor or the single selected manifest directly (Total Commander-style). |
| D9 | P3 | **Discoverability.** View switching exists only in the summary row's context menu. | Include a short hint in `summary` and assert it in `ChecksumFilesIT`. |
| D10 | P3 | **Host version.** An earlier record states the source host reports 0.10.2, but [base.json](../src/build/settings/base.json) is 0.10.1. | Do not rely on that record. Record the actual tested host version when declaring requirements. |

The remaining design is sound: independent ownership through public APIs,
manifest-driven verification, safe publication and the panel-free Table route.
The Table route was verified by the previous record's probe.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revised the active design and regression requirements for D1-D10.
  Preserved all prior reviewer records and the selection-aware, panel-free,
  12-algorithm scope with SHA256 as default. Native lifecycle and Unicode-default
  validation remain open; no implementation approval or runtime compatibility
  is claimed. No application, environment or dependency changes were made.

#### Review Response

| Finding | Design response | Remaining evidence |
| --- | --- | --- |
| D1 | Private lazy native loading; real reload/hash gate; full-exit removal/update policy and partial-removal recovery. | Source/portable native reload and disposable removal tests; record observed behavior in the plug-in README. |
| D2 | Propose BOM-free `utf-8`, matching supplied ASCII files; retain explicit `utf-8-sig` and require byte-level Unicode comparison before finalizing. | Genuine TC Unicode-name fixture with version/options. The default remains provisional until checked. |
| D3 | Separate logical and extended-length drive/UNC I/O paths across discovery, hashing, staging, replacement and cleanup. | Deep-tree generation/verification and lifecycle tests, including UNC. |
| D4 | Remove paging; retain bounded problems, offer Show all only for a complete fitting set, report omitted counts and distinguish display from processing limits. | Row/byte/raw-budget boundaries, no rehash on switching, maximum Table refresh latency and accurate totals. |
| D5 | Exclude destination and staging names only; retain other hard-link names. | Their digests still verify after replacing the destination name. |
| D6 | State the three metadata calls per hashed file plus traversal checks. | Separate metadata/content timing on the 10,001-file UNC benchmark. |
| D7 | Skipped: link is a distinct problem, never read/navigated or counted as matched. | Link/junction/cloud-placeholder rejection and result-display tests. |
| D8 | Verification ignores pane marks/cursor; auto-choose one discovered manifest or use a picker for several. | Selected/focused manifests must not bypass that discovery policy. |
| D9 | Summary gives a result-view menu hint when available, otherwise explains Show all unavailability; truncation is explicit. | Qt assertions for the hint, filter recovery, limits and summary counts. |
| D10 | Source metadata currently reads 0.10.2; it does not certify a minimum/frozen version or alter historical observations. | Record actual source/artifact versions and ABI in each compatibility run. |

#### Revision Validation

- Focused PowerShell assertions passed for name-only exclusion, lifecycle/encoding/
  long-path policies, current source metadata and bounded result-view requirements.
  The paging check found one stale alternative; it passed after removal.
- Preserve the original 15,077-character reviewer history unchanged; append this
  response only. Check required sections, algorithm/default settings, local links,
  Markdown diagnostics and whitespace in the final document validation.
- Whitespace command: `git diff --no-index --check -- NUL Plan/ChecksumFiles.md`.
- This revision ran no checksum implementation, native lifecycle, interoperability,
  packaging, full-suite or performance tests. Those future checks are not passes.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Used the user's newly installed BLAKE3 1.0.10 for bounded correctness
  and isolated source-host lifecycle probes. TC samples, vectors, streaming/reset
  and native reload passed. Loaded-file deletion failed as expected; full-exit
  cleanup/reinstallation passed. Frozen-host, in-flight reload, real removal UI
  and Unicode-default checks remain open. No dependency installation or checksum
  implementation was performed.

#### BLAKE3 Validation

- Existing environment: Python 3.14.7, BLAKE3 1.0.10, PyQt 5.15.11, Qt 5.15.15,
  Windows AMD64; source version read from build settings as 0.10.2. No environment
  files or installed plug-ins were changed by these probes.
- Correctness procedure: parse the TC `.blake3` records, read the same three small
  source files used earlier (175,454 bytes total), and compare native digests.
  All three passed. Verify independent empty/`abc` vectors, then hash 17 MiB of
  generated bytes in 4 MiB chunks with `max_threads=1`, `2`, `4`; compare with the
  serial digest, reset each hasher, and recheck empty/`abc`. All cases passed.
- Lifecycle procedure: copy the existing CalculateFileHash fixture and installed
  native package into a disposable Third-party directory, nesting the native
  package under `calculate_file_hash`. Reuse the integration-test registries and
  actual ExternalPlugin loader. Initial load was lazy; private import/hash and a
  simultaneous global-package hash passed without module-name collision.
- Invoke the real ReloadPlugins command with the disposable plugin list and real
  unload/load callbacks. Stub status reporting and pane-path restoration only.
  Reimport and hash again: passed in the used and reinstalled cases. This tests
  the source loader path, not a running application window or frozen artifact.
- Filesystem removal via `shutil.rmtree` passed before native use. After native
  use and unload, it failed on the `.pyd` with Windows error 5 (10 files before,
  10 remaining). No partial deletion was observed in this ordering; the real
  Remove plugin command may differ. Parent-process cleanup after child exit,
  reinstallation, hash/reload and final temporary-directory cleanup all passed.
- Review-history validation initially caught the prior reviewer's final sentence
  after the new response. Restoring it made the original 15,077 characters match
  the pre-edit SHA256 fingerprint exactly; no historical content was rewritten.
- Full-corpus/TC Unicode/DC interoperability, performance, reload during work,
  actual removal UI/Core deletion and portable-host certification were not run.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Added deterministic corpus v1, its non-overwriting generator and
  focused regeneration/integrity/format tests for the user's TC reference pass.
  Documented byte-exact reference import and independent temporary-root tests.
  This prepares validation data, not a checksum plug-in implementation; reference
  manifests and Unicode-default confirmation remain pending the user's TC run.

#### Fixture Preparation Validation

- `python -m unittest src.unittest.python.fman_unittest.test_checksum_fixtures -v`:
  seven focused tests passed before corpus publication, including identical
  regeneration in two roots, fixed archive metadata, refusal to overwrite,
  corruption/extra-file detection and PNG/WAV decoding. Corpus v1's inventory,
  count and byte total are pinned by the regression test.
- An initial discovery command imported an unrelated package without `fman` on
  its path; the direct module command above avoids that discovery dependency.
  A format probe caught an invalid PNG constant; corrected fixed bytes and a
  decode regression passed. Neither failed draft was published to the corpus.
- Generate in the user's emptied directory and run the generator's `--verify`
  check there before handing it over. Do not regenerate once reference files
  are present; existing-directory verification remains read-only.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Revised the requested reference layout to corpus v2: 83 files with
  26 directly in the destination root and no data wrapper. Pinned the new
  inventory and added a regression distinguishing allowed root reference files
  from unexpected nested manifests. Existing reviewer records remain unchanged.
- Validation: `python -m unittest src.unittest.python.fman_unittest.test_checksum_fixtures -v`
  passed all eight focused tests. Verify the old corpus before replacement and
  the published v2 tree with the generator's `--verify` command before handoff.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Imported the five user-produced corpus-v2 TC references as byte-exact
  base64/JSON fixtures. Independent regeneration passes all 415 digests and
  exact observed-profile reconstruction. Confirmed UTF-8 BOM as the Windows
  default and SFV record-before-comment handling. Previous records are unchanged;
  production implementation and unprovided interoperability cases remain pending.

#### Independent Reference Validation

- `python -m unittest src.unittest.python.fman_unittest.test_checksum_fixtures.TotalCommanderReferencesTest -v`:
  seven focused tests passed, including reference fingerprints, 415 digests,
  exact framing/BOM/CRLF, Unicode/whitespace/long paths, corruption, missing files
  and JSON checkout line-ending independence. Inputs are regenerated in a fresh
  temporary directory; no original reference folder is read by these tests.
- Store only the JSON fixture; its five decoded byte lengths and SHA256 values
  matched the user files before and after encoding. Loose import copies are
  redundant, not additional test inputs. Original user files remain untouched.
- Test helpers use native digest backends; this is not a production plug-in test
  or a TC reverse-verification run. No packages, environment files, host APIs,
  Git attributes or installed plug-ins changed during this reference import.

### 2026_10_02 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented the reviewed independent-package design without Core or
  public-API changes. Retained-count-only footer avoids guessing filtered summary
  visibility. Resolved Windows destination spelling without hard-link alias
  exclusion. Source/frozen workflows pass; remaining interoperability and
  lifecycle checks remain explicit rather than being treated as release approval.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Applied the user's revised manifest-choice policy: captured highlighted
  supported file first, deterministic case-insensitive filename fallback, no
  picker or retry after a chosen-file failure. Generation and owner/capture guards
  remain unchanged. Supersedes the older discovery-only picker policy; historical
  reviewer records remain unchanged.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Applied the user's bundled-delivery requirement: canonical source
  alongside existing plug-ins, ordinary resource discovery, pinned private native
  inputs collected by the spec, no UserSettings installation. Source fallback is
  development-only. Bundled reload retains ownership by existing host policy;
  standalone unload/removal requirements remain distinct. Prior history preserved.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Traced the reported Ctrl+P TypeError to checksum aliases declared as
  properties while PaneCommandRegistry reads them from the class. Correct the
  plug-in declarations, not Core or the registry. Prior command-invocation smokes
  missed palette enumeration; require that path in both application probes.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Use the requested labels Show all results and Show only mismatches,
  correcting the spelling without changing which verification problems are shown.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Independent implementation review. Approved with fixes: I1 (any
  reparse-point ancestor rejects the whole operation, including mounted folders)
  and I2 (verification metadata calls scale with path depth) should be fixed
  before release; I3-I8 are minor. Focused gate rerun: 73 tests, 72 passed, one
  expected portable skip. See Implementation Review.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 272K
- Outcome: Found S1, a Windows device-name alias validation gap; confirmed the
  existing I1 junction-root failure and I2 depth-dependent metadata overhead.
  Source, Qt and supplied portable-copy checks passed. Changes required before
  release; production code unchanged. See Independent Implementation Review.

### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Accepted S1 and I1-I7 as actionable; trusted-root handling and bounded
  directory reuse retain below-root refusals under the documented non-hostile
  concurrency model. I8 uses the existing Pending release backlog and adds site
  usage documentation. Prior findings are preserved; the intermittent native
  exit failure and external compatibility checks are not declared resolved.

## Implementer

### 2026_10_02 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Added the independent plug-in, twelve backends, validated preferences,
  strict manifest formats, cancellable streamed generation/verification, staged
  publication, bounded standalone results and an offline native packager. Native
  focused gate: 58 passed; offscreen gate: 56 passed. The supplied frozen 0.10.2
  host passed real command, overwrite, Table and BLAKE3 reload smoke checks.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented cursor-first manifest selection, seven focused regression
  methods and real-pane portable coverage. Fifteen command checks, the 52-test
  native gate and the 50-test offscreen gate passed. The portable host selected
  the alphabetical fallback for a text file and reported the highlighted malformed
  manifest without switching; its Table title named the chosen file.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Moved ChecksumFiles into bundled resources, updated development/test
  imports and reused native pin/license validation in the PyInstaller spec.
  Sixty focused checks pass, including real source startup and an isolated copy
  of a portable host using spec-selected resources with no third-party checksum
  installation. No clean/freeze or installed-application modification performed.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Replaced both alias properties with tuples; added a registry regression
  and source/frozen palette checks for empty and checksum queries. The exact
  reported error reproduced before the fix; the final 56-test gate passes.
  An earlier source-process exit violation is recorded below, not treated as
  resolved. Existing Calculate File Hash aliases and installed files are unchanged.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Updated the menu label and regression coverage for both labels and
  no-I/O view switches. All 18 focused command and Qt tests pass.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Renamed palette entries to Generate checksum file and Verify checksum
  file; command IDs and behavior are unchanged. Updated test expectations and
  usage documentation. Only the focused alias-registry regression ran and passed.

### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Implemented reserved-alias rejection, trusted-root path checks,
  bounded directory reuse, cheaper row accounting, accurate limit messages,
  consistent names/default filenames and pinned native inputs. Added regressions,
  site documentation and a Pending gate handoff. Final focused gate: 88 passed;
  strict documentation build and conda-lock input-hash validation passed.

## Validation Results

### Reviewer Feedback Follow-Up - 2026-10-03

| Finding | Response And Evidence |
| --- | --- |
| S1 | `ntpath.isreserved` rejects reserved aliases in every component. Parser/writer tests cover spaces before extensions; verification creates no hash call or target for invalid entries; unsafe output filenames fail before staging or hashing. |
| I1 | The captured root and ancestors are trusted. A real junction at the root or above it supports generation, discovery, verification and overwrite. Redirected descendants, selected paths through them and redirected output parents remain refused. |
| I2 | Per-run cache retains at most 256 positively checked directory paths, never file/error checks. Ten-file verification performs 33/43 `lstat` calls at depths 0/10, and 22 `fstat` calls in both cases. Directory traversal reuses non-following `DirEntry.stat`; uncached directories beyond the cap are rechecked. Runtime Effects records the limits and concurrency tradeoff. |
| I3 | "Results truncated" appears only when problem rows are omitted. Exceeding the all-results capacity without omitting problems reports only Show all unavailable. |
| I4 | Palette names, error prefixes and the verification window title consistently use Generate checksum file / Verify checksum file. |
| I5 | Generation suggests the captured folder name plus extension, or `checksums` at drive/UNC-share roots; tested without real network access. |
| I6 | Each retained row's cells are escaped once for accounting. Once no view can retain a row, only totals are updated; byte/payload budgets and problem-prefix retention remain enforced. |
| I7 | `environment.yml` pins BLAKE3 1.0.10. The lock already selected that version; only its input hash changed. The package origin now says installed distribution rather than asserting a wheel. Version, byte-pin, license and manifest tests pass. |
| I8 | [Pending checks CS01-CS06](../Plan/CodeReview099.md#checksumfiles-release-checks) retain external interoperability, storage, performance, restart/release, shutdown and standalone-only lifecycle checks. Site Features and Tools document the feature. No new task document or duplicate implementation was created. |

Final command, using the existing interpreter and `CHECKSUM_FILES_PORTABLE_EXE`
set to an available supplied portable host:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_unittest.test_checksum_files', 'fman_unittest.test_checksum_fixtures', 'fman_unittest.test_app_name.BuildNamingTest', 'fman_integrationtest.impl.plugins.test_checksum_files_plugin', 'fman_integrationtest.test_qt.ChecksumFilesIT'], env=build._environment()).returncode)"
python -m mkdocs build --strict --site-dir target/checksum-review-docs
```

88 tests passed, no skips. Source and disposable portable-copy probes each
verified 83 files, twelve algorithms, palette names, chosen-manifest behavior and
continued hashing after user-plugin reload. The 10,000-row Qt refresh took 40 ms;
this does not measure the worst-case 16 MiB text snapshot. Documentation built
successfully in strict mode. Editor diagnostics were clear in changed Python and
environment files. The original installed host and settings were untouched.

Immediate earlier gates passed: format/safety (7), engine (34), engine/commands/Qt
(56) and packaging (5). The new root-filename test initially used a malformed UNC
URL and blocked on an unstubbed alert; its fixture was corrected and alerts mocked,
then the same gate passed. The first final gate had 87 passes and one unavailable
portable check because the workspace artifact was absent. Using the supplied
installed host's disposable copy, the next run completed functional checks but
exited with `0xC0000005`. Fault diagnostics and child stderr are now retained by
the smoke. Its diagnostic rerun and the final 88-test gate passed; the native exit
failure remains intermittent and unresolved under CS05, not silently waived.

The lock input hash was recomputed offline through the installed conda-lock API.
The previous unpinned-input hash was reproduced first; no package was re-solved
or installed. Validation command:

```powershell
@'
from pathlib import Path
import yaml
from conda_lock.conda_lock import make_lock_spec
from conda_lock.content_hash import compute_content_hashes
from conda_lock.virtual_package import default_virtual_package_repodata
spec = make_lock_spec(src_files=[Path('environment.yml')], platform_overrides=['win-64'], mapping_url='')
lock = yaml.safe_load(Path('conda-lock.yml').read_text(encoding='utf-8'))
virtual = default_virtual_package_repodata(cuda_version='default')
with virtual:
    assert compute_content_hashes(spec, virtual) == lock['metadata']['content_hash']
print('PASS: conda-lock input hash matches environment.yml.')
'@ | python -I -
```

No full application suite, clean/freeze, new environment, dependency installation,
privileged filesystem setup or live UNC test ran. The portable copy uses current
spec-collected plug-in files in an existing host, not a newly frozen release.

### Palette Names - 2026-10-03

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files.ChecksumCommandTest.test_command_aliases_are_iterable_from_pane_registry', '-v'], env=build._environment()).returncode)"
```

One test passed, covering both exact palette names. The application smoke's
expected labels were updated but the smoke and broader suites were not rerun,
as requested for this naming-only change. No build or installed-app edit ran.

### Results Menu Wording - 2026-10-03

The focused `ChecksumCommandTest.test_table_prepares_views_and_blocks_stale_actions`
test passed immediately after editing. Final command and Qt validation:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files.ChecksumCommandTest', 'fman_integrationtest.test_qt.ChecksumFilesIT'], env=build._environment()).returncode)"
```

18 passed; editor diagnostics are clear. Labels are Show all results and Show
only mismatches. Filtering behavior is unchanged. No clean/freeze or full suite
ran; existing broader compatibility gates remain open. This unreleased wording
change does not need a separate changelog fix entry.

### Earlier Implementation Validation

Following the implementation checkpoint above, two additional regressions cover
an SFV first filename beginning with U+FEFF and byte counts after partial read
failures. The final totals below include both fixes; prior provenance is unchanged.

### Focused Commands

Run from the repository root with the existing supported interpreter:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_SCALE_FACTOR']='1.5'; env['QT_AUTO_SCREEN_SCALE_FACTOR']='0'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); env['CHECKSUM_FILES_PORTABLE_EXE']=os.path.abspath('target/RoyiFileManager/RoyiFileManager.exe'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files', 'src.unittest.python.fman_unittest.test_checksum_fixtures', 'fman_integrationtest.impl.plugins.test_checksum_files_plugin', 'fman_integrationtest.test_qt.ChecksumFilesIT'], env=env).returncode)"
```

60 tests passed, no skips. This includes 415 genuine TC digests through the
production verifier, byte-exact record formatting, all twelve Windows/Unix
writer-reader roundtrips, real junctions, changed files/manifests, cancellation,
destination races/case aliases, hard-link names, resource reuse and display limits.
Source-loader unload/load during active native hashing canceled the old task.
Qt snapshots rendered nonblank at native 100%/150%; observed 10,000-row refreshes
were 37-67 ms for the tested short-cell data, not a worst-case 16 MiB text snapshot.

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_SCALE_FACTOR']='1'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files', 'src.unittest.python.fman_unittest.test_checksum_fixtures', 'fman_integrationtest.test_qt.ChecksumFilesIT'], env=env).returncode)"
```

58 tests passed, no skips. The native-only packaged smoke is intentionally not
repeated in this command. Normally the portable test skips unless
`CHECKSUM_FILES_PORTABLE_EXE` is explicitly supplied.

The frozen smoke uses a disposable Third-party installation and isolated settings,
removes development Python/Qt paths and runs from an unrelated temporary directory.
It generates and case-aliased-overwrites a manifest for the 83-file corpus through
the real commands, verifies it, switches/closes the standalone table, hashes with
all twelve backends, then invokes real Reload plugins and repeats BLAKE3. It reports
host 0.10.2 / Python 3.14.7 / PyQt 5.15.11 / Qt 5.15.15 and confirms private native
loading. The child exits before cleanup; the supplied host and its settings are
not modified. No application rebuild, dependency installation or full suite ran.

### Local Measurements

Executed inline Python procedures through `build._environment()`, using temporary
files, production `hash_file`/`generate`/`verify`, `perf_counter`, `process_time`
and the installed pinned BLAKE3 binding. Three repetitions per timed candidate;
freshly written, OS-cache-warm local files, no cache flush. All candidate digests
agreed and every generated workload manifest verified completely.

| Workload | SHA256 | BLAKE3 Serial | BLAKE3 2 Threads | BLAKE3 4 Threads |
|---|---:|---:|---:|---:|
| 64 MiB file, 4 MiB chunks | 31.299 ms | 12.714 ms | 10.658 ms | 8.147 ms |
| 10,001 one-byte files | 1021.424 ms | 1014.700 ms | 1015.783 ms | 1017.511 ms |
| v2 mixed corpus, 29,375,536 bytes | 30.037 ms | 17.340 ms | 19.302 ms | 19.521 ms |

The full chunk comparison used 1/4/8/16 MiB and native caps 1/2/4. Large-file
BLAKE3 four-thread medians were 9.468/8.147/8.994/11.426 ms respectively;
SHA256 medians were 29.915/31.299/31.251/32.720 ms. Four-MiB throughput was about
2,045 MiB/s for SHA256 and 7,856 MiB/s for four-thread BLAKE3, under these warm
conditions only. CPU medians were quantized to 15.625 ms on this host: large-file
SHA256 31.25 ms, BLAKE3 15.625 ms; small-tree candidates about 1016-1031 ms.

An independently instrumented small-tree generation counted 30,035 `lstat` and
20,002 `fstat` calls. Its mock-retained allocation peak is not an engine memory
measurement. A separate unmocked `tracemalloc` pass measured 4,485,644 bytes for
generation and 10,245,608 bytes for verification; these exclude native allocations
and process RSS. All 10,001 entries still matched after the full display candidate
was discarded. A cancellation requested after a completed chunk returned in
0.065 ms; this is not worst-case blocked-I/O cancellation latency.

### Remaining Gates

Current Pending home: [ChecksumFiles release checks](../Plan/CodeReview099.md#checksumfiles-release-checks).
The historical list below is retained as evidence, not a claim that the task must
return to Plan. Standalone unload/removal gates do not apply to bundled reload.

- Seven remaining TC algorithms, genuine Unix/DC references, and four-direction
  TC/DC verification of the production writer. Self-roundtrips are not substitutes.
- Live UNC/HDD/cold-storage behavior and metadata latency, process/native memory
  peaks and actual thread counts, and worst-case 16 MiB Table refresh latency.
- Frozen-host reload during active hashing, actual Remove plugin UI behavior
  before/after native use, and preference override persistence across a full restart.
- Case-sensitive NTFS directory and live cloud-placeholder coverage beyond the
  lexical and reparse regressions. No privileged filesystem or Registry setup ran.

Keep this canonical task under Plan until those required gates are completed or
explicitly revised by the user. Source implementation and the offline package are
ready for use on the tested configuration; this is not blanket release certification.

### Manifest Selection Follow-Up - 2026-10-03

Exact executed commands, using the existing interpreter from the repository root:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files.ChecksumCommandTest', '-v'], env=build._environment()).returncode)"
```

15 passed. Covers cursor preference, ordinary/unsupported/absent cursor fallback,
case ties, marked-selection independence, stable captured cursor, path-change
rejection, no supported manifests and no retry after incomplete chosen-manifest
results. Generation does not read the cursor and retains its selection semantics.

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); env['CHECKSUM_FILES_PORTABLE_EXE']=os.path.abspath('target/RoyiFileManager/RoyiFileManager.exe'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files', 'fman_integrationtest.impl.plugins.test_checksum_files_plugin', 'fman_integrationtest.test_qt.ChecksumFilesIT'], env=env).returncode)"
```

52 passed, no skips. The disposable portable smoke uses the actual pane cursor:
highlighting `ascii-lf.txt` chooses `a-first.sha256`; highlighting malformed
`B-highlighted.sha256` chooses that manifest and displays its problem. It asserts
no picker and the chosen filename in the real Table title. The initial probe could
not place its cursor; publishing file-added notifications and choosing a known
visible fixture corrected the test setup. Existing loader, native hashing,
generation/overwrite, cancellation and reload checks also pass. The supplied
executable and its normal settings are unchanged.

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files', 'fman_integrationtest.test_qt.ChecksumFilesIT'], env=env).returncode)"
```

50 passed, no skips. No full suite, host rebuild, new environment or dependency
installation ran. The broader Remaining Gates are unchanged; this revision is
ready for code review, not blanket interoperability certification.

### Bundled Delivery Follow-Up - 2026-10-03

Using the existing interpreter from the repository root, with
`CHECKSUM_FILES_PORTABLE_EXE` set to the supplied portable executable:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files', 'fman_unittest.test_app_name.BuildNamingTest', 'fman_integrationtest.impl.plugins.test_checksum_files_plugin', 'fman_integrationtest.test_qt.ChecksumFilesIT'], env=build._environment()).returncode)"
```

60 passed, no skips. The original discovery regression failed before the move.
Spec-expanded inputs contain commands, engine, defaults, wrapper, native binary
and license. Invalid version, changed bytes and missing license are rejected.
Source and frozen-copy startup each run both commands and twelve algorithms,
verify 83 corpus files, exercise cursor selection and keep hashing after user
plug-in reload. Frozen hashing uses the private backend with development paths
removed; source hashing uses the installed dependency. Standalone load/unload,
in-flight cancellation and Qt Table tests also pass (10,000-row refresh: 38 ms).

The first startup smoke incorrectly expected bundled-owner invalidation on
Reload Plugins; Core intentionally reloads user-installed plug-ins only. The
assertion now requires preserved ownership. A workspace portable artifact was
unavailable, so the frozen test copied the supplied installed host into a temporary
directory and injected only spec-selected ChecksumFiles resources into that copy.
The original executable and settings were not changed. This is not a newly frozen
artifact: `clean`, `freeze`, the full suite and dependency installation were not run.
Broader compatibility gates remain open; the canonical task stays Pending.

### Command Palette Follow-Up - 2026-10-03

The registry regression reproduced `TypeError: 'property' object is not iterable`
for both checksum commands before their declarations were corrected. The earlier
smokes verified registration and direct invocation, not palette enumeration.

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files.ChecksumCommandTest.test_command_aliases_are_iterable_from_pane_registry', '-v'], env=build._environment()).returncode)"
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files.ChecksumCommandTest', '-v'], env=build._environment()).returncode)"
```

The first command failed as expected before the fix. The second passed all 16
command tests afterward. With `CHECKSUM_FILES_PORTABLE_EXE` set to the supplied
portable executable, the final focused gate was:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files', 'fman_integrationtest.impl.plugins.test_checksum_files_plugin'], env=build._environment()).returncode)"
```

56 passed, no skips. Both real applications invoke `command_palette`; its actual
suggestion callback finds Generate CheckSum File and Verify Checksum for empty
and `checksum` queries. Only the Quicksearch dialog is replaced in the probe.
The portable probe uses a disposable host copy with current collected resources;
the supplied installation is untouched. Editor diagnostics report no errors.

An earlier run passed the functional source checks but exited with Windows access
violation `0xC0000005`. Its isolated rerun with fault diagnostics passed:

```powershell
python -c "import build, subprocess, sys; env=build._environment(); env['PYTHONFAULTHANDLER']='1'; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.impl.plugins.test_checksum_files_plugin.ChecksumFilesPluginTest.test_source_commands_are_bundled_without_installation', '-v'], env=env).returncode)"
```

The subsequent full focused gate also passed. This one-off exit failure remains
unexplained; it is not evidence of a fixed shutdown issue. No clean/freeze, full
suite, environment installation or installed-application edit ran. The feature is
still Unreleased, so no separate changelog fix entry was added. Broader gates remain open.

## Implementation Review (2026-10-03)

Verdict: **approved with fixes.** Fix I1 and I2 before release.

The code follows the design: public APIs only, capture guarded by
`on_path_changed`, staged publication with identity checks, extended-length I/O,
bounded Table snapshots whose byte accounting matches the host's `plain_size`,
and native BLAKE3 pinned by hash.

| ID | Priority | Finding | Where |
| --- | --- | --- | --- |
| I1 | P2 | **Any reparse-point ancestor rejects the whole operation.** `_check_chain` inspects every ancestor up to the drive root. In a probe, a folder reached through a junction made generation fail with `LinkedPath`, and verification returned Incomplete with zero records. Volume mount points are also reparse points, which contradicts the Scope's "mounted/UNC storage". | [engine.py](../src/main/resources/base/Plugins/ChecksumFiles/checksum_files/engine.py) `_check_chain`, used by `_walk_files`, `discover`, `generate` and `verify` |
| I2 | P2 | **Verification metadata calls scale with path depth.** Every record re-checks all ancestors. 100 files at depth 10 took 1,410 `lstat` calls (about 14 per file); Runtime Effects says four. 10,000 local files: verify took 1.59 s, or 1.17 s with an in-process per-run directory cache. On UNC each call is a network round trip. | `verify` -> `_check_chain(path)` |
| I3 | P3 | Any result set over 9,999 rows reports "Results truncated; 0 problem rows omitted", even when all files matched. | `Results.summary` |
| I4 | P3 | Names are inconsistent after the palette rename: the alert prefixes are "Generate CheckSum File:" and "Verify Checksum:", and the Table title is "Verify Checksum:". | [commands.py](../src/main/resources/base/Plugins/ChecksumFiles/checksum_files/commands.py) |
| I5 | P3 | The suggested filename is `CheckSum<ext>`, but Design step 2 says `<directory-name>.<extension>` (or `checksums` at a root). | `GenerateChecksumFile` / Design |
| I6 | P3 | Row accounting escapes each row's cells twice and continues after both views stop retaining rows (about 15 µs per record). | `ResultRow.payload_bytes`, `Results.add` |
| I7 | P3 | `environment.yml` leaves `blake3` unpinned while `package.py` hard-pins the 1.0.10 bytes, so an environment update breaks `freeze`. The manifest's `origin` says "Installed wheel", but the installed package comes from conda-forge. | [environment.yml](../environment.yml), [package.py](../src/main/resources/base/Plugins/ChecksumFiles/package.py) |
| I8 | P3 | Open gates (seven TC algorithms, DC, UNC, the Remove plugin UI, the unexplained `0xC0000005` exit) have no Pending home. The documentation site does not mention the feature. | [Plan.md](../Plan.md), `docs/` |

Recommended fixes:

- **I1:** check redirection from the captured root downward. The navigated root
  and its ancestors are the user's chosen location. Keep link refusal for every
  component below the root.
- **I2:** cache directories already checked during the run. Classify walk
  entries with `DirEntry.stat(follow_symlinks=False)`. Update Runtime Effects
  with the measured calls per file.
- **I3:** say "truncated" only when problem rows were omitted. Otherwise report
  that Show all is unavailable above 9,999 results.
- **I7:** pin `blake3 =1.0.10`.
- **I8:** record the open gates in a pending plan.

### Review Validation

Offscreen focused gate, using the existing interpreter:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_SCALE_FACTOR']='1'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'], 'Fonts'); sys.exit(subprocess.run([sys.executable, '-B', '-X', 'faulthandler', '-m', 'unittest', 'src.unittest.python.fman_unittest.test_checksum_files', 'src.unittest.python.fman_unittest.test_checksum_fixtures', 'fman_integrationtest.impl.plugins.test_checksum_files_plugin', 'fman_integrationtest.test_qt.ChecksumFilesIT'], env=env, timeout=600).returncode)"
```

Result: 73 tests, 72 passed, one skip (the portable smoke, because
`CHECKSUM_FILES_PORTABLE_EXE` was not set). The source bundled smoke passed:
12 algorithms, 83 matched, both palette queries. The 10,000-row refresh took
0.039 s.

The I1-I3 and I6 probes used temporary directories, a non-administrator
junction and in-process monkeypatching only. The build-time `native_files()` pin
check passed against the installed conda-forge BLAKE3 1.0.10. No source, test,
build, freeze or installed-application change was made. Only this document was
edited.

## Independent Implementation Review (2026-10-03, Sol)

Verdict: **changes required before release.** The implementation follows the
current bundled, panel-free design with bounded, conditional all-results views.
S1 is new; I1 and I2 below confirm the earlier review, not additional discoveries.
Historical findings and records above remain unchanged.

| ID | Priority | Finding | Evidence / Required Change |
| --- | --- | --- | --- |
| S1 | P2 | **Space-before-extension device aliases bypass path validation.** [relative_path](../src/main/resources/base/Plugins/ChecksumFiles/checksum_files/engine.py#L97) tests `part.split('.')[0].upper()` without Windows device-name normalization. `NUL .txt`, `CON .txt`, `COM1 .log` and `AUX .sha256` are accepted although `ntpath.isreserved` rejects them. | A temporary `NUL .txt` created through the extended-path helper was hashed once by production verification, reported as Matched, and assigned an ordinary navigable target. This violates the required Windows-alias rejection; ordinary Win32 consumers need not resolve that target like extended-path I/O. Reject every reserved component before I/O and target creation, using a Windows-aware predicate such as `ntpath.isreserved` while preserving the existing case-sensitive/Unicode path rules. Add parser, verification no-read/no-target, and generation filename regressions. |
| I1 | P2 | **Captured roots reached through junctions remain unusable.** [_check_chain](../src/main/resources/base/Plugins/ChecksumFiles/checksum_files/engine.py#L183) inspects ancestors above the operation boundary. | A real temporary junction used as the captured root raised LinkedPath during generation; verification was Incomplete with zero records. Define the trusted navigated-root boundary, permit supported mounted locations there, and retain rejection of redirected components below it. Add a captured-root junction/mount regression separately from the existing below-root exclusion test. |
| I2 | P2 | **Every record repeats ancestor metadata checks.** [verify](../src/main/resources/base/Plugins/ChecksumFiles/checksum_files/engine.py#L591) checks the full chain before hashing. | Ten files required 121 `lstat` calls at depth zero and 221 at depth ten: 100 extra calls solely from nesting, in addition to handle stats. This contradicts the four-call Runtime Effects estimate and risks disproportionate UNC latency. Reuse validated directory information within the documented non-hostile-concurrency model, preserve below-root link rejection, and test metadata-call scaling. No live UNC latency was measured. |

### Focused Validation

All commands used the existing interpreter and `build._environment()`; no
dependency installation, full suite, clean or freeze was performed.

Source engine, format, TC fixture, command, packaging and plug-in lifecycle gate:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.test_checksum_files','fman_unittest.test_checksum_fixtures','fman_integrationtest.impl.plugins.test_checksum_files_plugin','-q'],env=env,timeout=180).returncode)"
```

Result: 71 tests, 70 passed, one expected skip because
`CHECKSUM_FILES_PORTABLE_EXE` was not set for this invocation. The real bundled
source startup smoke passed both commands, palette enumeration, 12 algorithms,
83 matched records and continued hashing after user-plugin reload.

Real Table integration at offscreen, Windows 100% and Windows 150%:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); settings=({'QT_QPA_PLATFORM':'offscreen'},{'QT_QPA_PLATFORM':'windows','QT_SCALE_FACTOR':'1','QT_AUTO_SCREEN_SCALE_FACTOR':'0'},{'QT_QPA_PLATFORM':'windows','QT_SCALE_FACTOR':'1.5','QT_AUTO_SCREEN_SCALE_FACTOR':'0'}); sys.exit(max(subprocess.run([sys.executable,'-m','unittest','fman_integrationtest.test_qt.ChecksumFilesIT','-q'],env=dict(env,**setting),timeout=180).returncode for setting in settings))"
```

Result: two tests passed in each configuration, no skips. Maximum 10,000-row
refresh took 0.037-0.038 seconds; view switching, empty/truncated results,
navigation roles, close cleanup and nonblank widget grabs passed.

Build-input checks and explicitly supplied existing portable-host smoke:

```powershell
python -c "import build, os, subprocess, sys; path=build.ROOT/'target/RoyiFileManager/RoyiFileManager.exe'; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); env['CHECKSUM_FILES_PORTABLE_EXE']=str(path); print('Existing portable executable present:',path.is_file(),flush=True); sys.exit(subprocess.run([sys.executable,'-m','unittest','fman_unittest.test_app_name.BuildNamingTest','fman_integrationtest.impl.plugins.test_checksum_files_plugin.ChecksumFilesPluginTest.test_supplied_portable_commands_and_private_backend','-v'],env=env,timeout=120).returncode if path.is_file() else 2)"
```

Result: four tests passed, no skips. The portable smoke copies the existing
0.10.2 host to a temporary directory and injects current spec-selected checksum
inputs. Its private native backend, 12 algorithms, 83 matches, case-aliased
overwrite, highlighted/fallback selection, palette and bundled reload passed.
This is **not** a fresh freeze or validation of the untouched delivered artifact.

Focused reproduction procedures, all in disposable temporary directories:

- S1: compare `relative_path` and `ntpath.isreserved` on the four names above.
  Create `NUL .txt` using `open(engine.native_path(path), 'wb')`, write a SHA256
  record for its bytes, and call production `verify` with `hash_file` wrapped by
  a mock. Observed complete=True, status=Matched, one hash call, target equal to
  the ordinary logical path. No console or serial device was opened.
- I1: create an ordinary corpus and manifest, then `cmd /c mklink /J` a temporary
  root to it. Invoke `generate` and `verify` through that root. Observed LinkedPath
  and an Incomplete zero-record report; remove the junction before cleanup.
- I2: verify ten ordinary files at depths zero and ten while wrapping
  `engine.os.lstat`; assert ten matches each. Observed counts 121/221. Filesystem
  depth above the temporary corpus affects absolute counts, not the 100-call delta.
- Editor diagnostics: no errors in engine, commands or the offline packager.

Remaining gates are unchanged: seven other TC algorithms, genuine Unix/DC
profiles and reverse interoperability, live UNC storage, standalone Remove
Plugin UI, and a fresh packaged release. Prior unexplained shutdown failure
remains historical; this review did not reproduce or establish its cause.
No source, test, build configuration, changelog or installed application was
changed. Only this task document was amended.

## Summary-Free Results Follow-Up

The user approved removing the redundant Summary row while retaining problems-first
results and both view-menu labels. The shared Table adds opt-in background actions;
row callbacks and path navigation are unchanged. No hashing, scanning, persistence,
thread count, timer or idle work was added. Existing row/byte limits are unchanged.
The documentation generator verifies three real sample files with production
SHA256 logic, captures both actual Qt menus and exercises both view choices.

### Reviewers

#### 2026_10_03 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: User approved summary-free results with opt-in empty-background menus
  and requested screenshots. Keep existing row callbacks compatible; validate
  empty/filtered views, stale actions, cleanup and native Qt interaction.

### Implementer

#### 2026_10_03 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 272K
- Outcome: Removed the synthetic row and its count adjustment; added background
  menus, focused regressions and two reproducible documentation screenshots.
  Source validation passed; the supplied older portable host needs rebuilding.

### Validation Results

The existing project interpreter ran the following commands from the repository
root. No new environment, packages, full application suite or freeze was used.

```powershell
python -c "import build, subprocess, sys, os; env=build._environment(); env['QT_QPA_PLATFORM']='offscreen'; env['QT_QPA_FONTDIR']=os.path.join(os.environ['WINDIR'],'Fonts'); sys.exit(subprocess.run([sys.executable, '-u', '-X', 'faulthandler', '-m', 'unittest', 'fman_unittest.test_checksum_files', 'fman_unittest.test_ui_elements', 'fman_unittest.test_generate_docs_screenshots', 'fman_integrationtest.test_qt.ChecksumFilesIT', 'fman_integrationtest.test_qt.TableIT', 'fman_integrationtest.impl.plugins.test_checksum_files_plugin.ChecksumFilesPluginTest.test_packaged_loader_native_reload_and_inflight_cancellation', 'fman_integrationtest.impl.plugins.test_checksum_files_plugin.ChecksumFilesPluginTest.test_source_commands_are_bundled_without_installation'], env=env).returncode)"
python -c "import build, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable, '-u', '-X', 'faulthandler', '-m', 'unittest', 'fman_integrationtest.test_qt.ChecksumFilesIT', 'fman_integrationtest.test_qt.TableIT'], env=env).returncode)"
python -c "import sys; sys.path.insert(0, 'src/misc'); import generate_docs_screenshots as shots; shots.SOURCE_CAPTURES=('checksum-files',); args=shots._parse_args(['--mode', 'source']); outputs=shots._run_source(args); [shots._validate_image(path) for path in outputs]; print('\n'.join(str(path) for path in outputs))"
python -c "import build, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1.5', QT_AUTO_SCREEN_SCALE_FACTOR='0'); sys.exit(subprocess.run([sys.executable, '-u', '-X', 'faulthandler', '-m', 'unittest', 'fman_integrationtest.test_qt.ChecksumFilesIT', 'fman_integrationtest.test_qt.TableIT'], env=env).returncode)"
python -m mkdocs build --strict --site-dir target/checksum-menu-docs
```

- Final source gate: 116 tests passed, no skips. Native Windows Table gate:
  14 tests passed at normal scale and 14 at 150%. The 9,999-result refresh took
  about 38-39 ms in these fixtures. Strict MkDocs build, editor diagnostics and
  scoped tracked-file whitespace checks passed.
- Both 820x520 PNGs were generated, passed image validation and were visually
  inspected. Empty-background and row menus show the two requested labels;
  no Summary row or private absolute path appears. Pages regenerates these
  ignored assets using the existing source-capture command.
- Early Qt tests exposed an asynchronous filter assertion and an unsafe test-only
  direct action trigger on an open popup. The regression now waits for bounded
  filter completion and selects menu actions with actual Enter-key events.
  Owner-cleanup assertions run after queued Qt dispatch. Final gates pass; this
  does not resolve the separately recorded historical native shutdown issue.
- The earlier 19-test generator/plug-in gate had 18 passes and one failure:
  `test_supplied_portable_commands_and_private_backend` rejected the new
  `get_background_menu` keyword in the supplied older frozen host. Plug-in-only
  resource replacement cannot update that host API. A fresh rebuilt portable
  validation remains open; neither the installed app nor normal settings changed.
- Root README feature wording and all earlier reviewer records were preserved.