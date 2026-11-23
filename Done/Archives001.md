# Archives 001: One Policy for Archive Operations

Status: Implemented 2026-11-23; see [Implementation](#implementation) and
[Final Implementation](#final-implementation). The design below was rewritten
2026-11-23 around one policy for every archive operation (user decision). It
replaces the earlier revisions of this document: archives are read-only, and
there is no temporary tar, no reading task and no visibility check. The earlier
reviewer records below describe those revisions.

## Task

Make archive operations fast in the normal cases, with few special cases and no
silent loss of data. One policy covers every archive type and every operation.
Delicate work is done by entering the archive and choosing items, and that must
be fast too.

Four problems led here.

### Compressed tar archives

Compressed tars (`.tar.gz`, `.tgz`, `.tar.bz2`, `.tbz2`, `.tbz`, `.tar.xz`,
`.txz`, `.tar.zst`, `.tzst`) have no `archive_handlers` entry, so:

- Enter does not open them as archives.
- Explorer items inside them are refused with "*name*: this archive type has no
  entry in archive_handlers (AppSettings.yaml)". Windows 11 Explorer opens these
  types natively, so users meet this through drag and drop or paste.

Adding `.tar.gz: tar://` alone does not work. The bundled 7-Zip (`7za` 26.03)
reads `x.tar.gz` as one compressed stream that holds `x.tar`, so it lists `x.tar`,
not the members. It has no one-call type chain for this (`-tgzip.tar` fails with
"Is not archive"); piping the stream into a second 7-Zip does list the members.

### Many items from one archive

Reported in `TODO.md`: extracting `CelebAAligned.zip` is too slow. The archive
holds 202,600 files in its root (1.31 GiB). A copy out of an archive (F5, Paste,
drop) handles every chosen item on its own. Measured with the application's
code (SATA SSD, real-time antivirus on):

| Step | Time |
|---|---|
| One chosen file: nine 7-Zip listings while "Gathering files" | 1.20 s |
| One chosen file: its own 7-Zip extraction | 0.27 s |
| All 202,600 files, extrapolated from runs of 10 and 40 files | about 83 hours |
| 7-Zip alone, whole archive | 53 s |
| Unpack archive (works today) | 54 s |

About 68 of the 83 hours pass in "Gathering files", before the first file is
written. Every 7-Zip start reads the archive's index again (0.13 s). A tar has
no index, so there each start reads the whole archive.

### Unpack to a folder

From `TODO.md`, as the user phrased it:

- Add "Unpack to..." as an option to unpack the archive content to a path (the
  other pane as the default) without entering it.
- Add "Unpack to..." and "Unpack here" to the context menu on archives.

Today there is one command, **Unpack archive**. It works like "Extract Here":
`Reports.zip` in `C:\Work` creates `C:\Work\Reports`, and it stops when that
folder exists. It is only in the Command Center. In this document, "Unpack
here" is that command.

### Changing an archive in place

Copy into an archive, Move out of or between archives, Rename, Delete and New
folder inside an archive run 7-Zip once per chosen item. Every run writes the
whole archive again as a new file. Measured on 48 files of 192 MiB together
(145 MiB as a `.zip`):

| Type | Add one small file | Delete one member |
|---|---|---|
| `.zip` | 0.08 s, the data is copied as it is | 0.07 s, copied as it is |
| `.7z` (solid, 7-Zip's default) | 0.07 s | 18.6 s: compressed again (creating it took 15.9 s) |
| `.tar` | 0.11 s | 0.09 s |
| `.tar.gz` | not possible with 7-Zip | not possible with 7-Zip |

Moves add verification passes (see
[Archive Transfers](../Done/ArchiveTransfers.md)). This is the most delicate
archive code, and none of it runs once per operation. The user decided
(2026-11-23) to start with archives that are read-only, for every type.

## Scope

Archive types: `.zip`, `.zipx`, `.jar`, `.xpi`, `.7z` and `.tar` as today, and
the nine compressed tar suffixes as new types.

Included, for every archive type:

- Browse with Enter: list and navigate folders, Name/Size/Modified columns.
- **Unpack here**: a new folder beside the archive, named after it.
- **Unpack to...**: the archive's content goes into a chosen folder, by default
  the other pane's folder, without entering the archive.
- Copy of chosen items out of an archive (F5, Paste, drop), also for items
  copied or dragged from Windows Explorer's archive view.
- **Pack** and **Pack here**: a new `.zip`, `.7z` or `.tar` from the chosen
  items.
- "Unpack to..." and "Unpack here" in the file context menu.

Refused with one message, for every archive type; the archive file is never
changed:

- Copy or Move into an archive, and Pack into an archive that exists.
- Move out of an archive, within it or between archives.
- Rename, Delete (to the Recycle Bin or permanently) and New folder inside an
  archive.

Excluded:

- Changing an archive in place. It can return later as a task of its own.
- Packing compressed tars, and conversion between formats.
- Formats `7za` cannot read: `.rar`, `.iso` and others Windows Explorer opens
  natively. Their Explorer items keep the current message.
- Single compressed files that are not tars (`.gz`, `.xz`, `.bz2`, `.zst`).
- Windows' own copy engine for Explorer items. Earlier archive work routed all
  extraction through the application's copy pipeline; this task keeps that.
- Encrypted archives, a password prompt, opening or previewing a file inside an
  archive, and archives inside archives. All stay as they are.

Compatibility. Removed for `.zip`, `.7z` and `.tar` (user decision,
2026-11-23): copy into an archive, Pack into an existing archive, move out of,
within or between archives, and Rename, Delete permanently and New folder
inside an archive. To change an archive, unpack it, change the files and pack
them again.

Changed:

- A copy of several items extracts them in one 7-Zip run. If that run fails,
  none of its items is copied. Today the other items could still be copied.
- Pack refuses an archive name that exists; today it asks to add or update.
  It also refuses two chosen items with the same name, and items that are
  inside an archive.
- Symbolic links inside an archive are skipped and reported. Today a link is
  created where Windows allows it and fails the whole copy elsewhere.
- Archives whose entries start with `./` open. Today they fail.
- New folder is no longer offered inside an archive.

Unchanged: **Unpack archive** keeps its behavior, its command ID and its first
name, and gains the name "Unpack here". Browsing, the Copy prompt, the overwrite
questions and the Pack prompt stay as they are.

The plug-in API gains one optional attribute, `FileSystem.read_only_message`;
existing plug-ins need no change. The compressed tar entries are bundled
`archive_handlers` defaults, so user settings need no change; a user can still
remove a type by overriding its entry.

## Design

**Policy.** Five rules, for every archive type:

1. One listing per archive version. It is kept in memory and answers every
   question about the archive's members.
2. One 7-Zip run per operation and archive, whatever the number of items. A
   compressed tar runs as one pipe of two 7-Zip processes.
3. Stage, then publish. Output is written to a temporary folder or file on the
   destination's volume and moved into place by rename. Nothing that exists is
   replaced without the user's yes. A run that fails or is cancelled publishes
   nothing.
4. An archive file is never changed. Archives are created by Pack and read.
5. No work before the user asks: no visibility checks when a menu opens. A
   wrong choice gets a message.

| Operation | Result | Asks | 7-Zip runs |
|---|---|---|---|
| Browse | Folders from the member list | Nothing | One listing per archive version |
| Unpack here | New folder beside the archive | Nothing | One |
| Unpack to... | Content in the chosen folder | The folder | One |
| Copy chosen items | As any copy: merge, overwrite | Copy's questions | One |
| Pack, Pack here | New archive from the chosen items | The archive name | One |
| Any change to an archive | Refused with one message | Nothing | None |

**Member list.** `_7ZipFileSystem`
([zip.py](../src/main/resources/base/Plugins/Core/core/fs/zip.py)) keeps the
members of an archive in memory and answers `scan`, `iterdir`, `is_dir`,
`exists`, `resolve`, sizes and dates from that list, without starting 7-Zip:

- One 7-Zip listing (`7za l -slt`) builds the list. It replaces the per-member
  metadata cache (`_put_in_cache`).
- The list is indexed by folder. A folder opens in time proportional to its own
  entries, and a copy can tell whether every entry of a folder was chosen.
- Lists are kept by the archive's identity (normalized path, `st_dev`, `st_ino`,
  `st_size`, `st_mtime_ns`), checked with `os.stat` before every use. A changed
  archive is listed again.
- Memory: about 250 bytes per member. The least recently used lists are dropped
  while the kept lists hold more than 1,000,000 members together; the newest
  list always stays. No archive is refused for its size.
- Names: a leading `./` is removed and the `.` entry is skipped. The list keeps
  7-Zip's stored name for extraction (`./docs/a.txt`). An archive with absolute
  or `..` paths is refused with one clear message; today its listing fails.
- Links: a member is marked as a symbolic link when 7-Zip's `Symbolic Link`
  field is not empty (tar) or its Unix mode starts with `l` (zip).
- A pane scan and tasks build a missing list with their cancellation. Other
  calls of `resolve`, `is_dir`, `exists`, sizes and dates build it too, without
  cancellation: at startup for a pane saved inside an archive, or before Copy's
  prompt for an item dropped from Explorer. The callers found in review run off
  the Qt thread. For `.zip`, `.7z` and `.tar` the listing reads an index or the
  headers only (1.2 s for 202,600 members).
- A per-archive lock stops two builds of one list. A waiter stays cancellable
  and takes over when the owner is cancelled.

**Extraction.** `Extract` is the one task behind Unpack here, Unpack to... and
the copy of chosen items:

1. Input: the archive, what to extract (everything, or stored member names) and
   pairs of member and destination path.
2. Stage: a temporary folder on the destination's volume, as today: inside the
   destination folder, or beside it when it does not exist yet.
3. Run: 7-Zip once, with `-snl-`. Names go into a list file (`-i@`, UTF-8) in
   the stage, one name per line in double quotes. Without quotes 7-Zip drops a
   leading space of a name.
4. Publish: after exit code 0, each pair moves into place with one rename. A
   rename does not replace. A file replaces an existing file only where the
   user agreed to overwrite, which only a copy can ask. Each destination folder
   is announced once (`notify_file_changed`).
5. Failure: a failed or cancelled run publishes nothing and removes the stage.
   If a rename fails in a copy of chosen items, the other items are still
   moved, and one message at the end gives the count and names the items that
   were not copied. In Unpack a failed rename stops publishing and the message
   names the item. The items already moved stay, each complete.

Identity checks keep using the real archive: the before and after `stat` of the
archive, and the refusal to write over the source.

**Unpack here and Unpack to.** Both unpack the whole archive under one rule:
Unpack only creates, and what it would create must not exist yet. It asks about
no single file, merges nothing and overwrites nothing. For that, the user enters
the archive and copies.

| | Unpack here | Unpack to... |
|---|---|---|
| Command | `UnpackArchive` (`unpack_archive`), as today | New: `UnpackArchiveTo` (`unpack_archive_to`) |
| Names | "Unpack archive", "Extract archive", new: "Unpack here" | "Unpack to...", "Unpack archive to...", "Extract to..." |
| Destination | Folder beside the archive, named after it | Folder typed in a prompt; default: the other pane's folder |
| Creates | That folder | The archive's top-level entries in the folder, and the folder if it is missing |
| Publish | One rename | One rename for a new folder; otherwise one per top-level entry |

Both follow the same steps:

1. Source: exactly one chosen item, a local file whose name has an
   `archive_handlers` entry. Anything else gets the existing messages, for
   example "This archive format is not supported."
2. The member list is built if it is missing. The existing name rules
   (`_unpack_manifest`) run on it and refuse an archive with names that Windows
   would change or that collide, as today. Today Unpack lists the archive a
   second time for them (3.7 s of 54 s for the CelebA zip).
3. Nothing may exist yet: the folder for Unpack here, each top-level name in the
   folder for Unpack to... The first name found stops the operation with
   "Destination already exists: *name*", before 7-Zip starts.
4. `Extract` extracts everything and publishes.
5. The status bar shows "Unpacked *name*". Unpack here places the cursor on the
   new folder, as today.

The prompt of Unpack to... reads "Unpack x.zip to". The typed path is the
destination folder; a relative path starts at the current folder, as in Copy.
It must be a local folder path. Typing a name at the end gives a new folder.
Neither command has a default shortcut.

**Copy of chosen items.** F5, Paste and drop keep the Copy prompt, the merge
into existing folders and the overwrite questions. `CopyFiles`
([fileoperations.py](../src/main/resources/base/Plugins/Core/core/fileoperations.py))
answers them from the member list, so gathering starts no 7-Zip process. All
chosen items of one archive then share one `Extract`: when `CopyFiles` queues a
task, the open `Extract` of the same archive takes its pair.

- Names: the chosen members. When every entry of an archive folder was chosen,
  the folder's name stands for them; for the root, no names are passed.
- Cost of a name list: 7-Zip compares each chosen name with the entries of its
  own folder, about 9 ns per pair. Other folders cost nothing: in a zip of 200
  folders with 1,000 files each, 10,000 names from 20 folders matched in 0.2 s.
  The worst case is one very large folder. From the 202,600-file folder of the
  CelebA zip, 7-Zip extracts 1,000 chosen files in 1.8 s, 5,000 in 9.6 s and
  20,000 in 43 s. All 202,600 names would add 6 minutes, which the rule above
  avoids.
- Progress: 7-Zip's percentage, then the count of items moved.

**Copy-into-itself test.** For every item, `CopyFiles` checks that the
destination is not the source or inside it. Outside `file://` this resolves the
source and every folder above the destination again for each item: ten
`resolve` calls per item, 59 s for 202,600 members even with the member list.
The test now resolves the source once per item and each folder above the
destination once per operation, and compares only URLs that resolve to the same
scheme, which `samefile` requires anyway. Its results do not change.

**Pack.** Pack and Pack here keep their prompt and create one new archive in one
7-Zip run:

- Sources: local files and folders. Other items are refused with a message.
- Type: from the name's `archive_handlers` entry: `zip://`, `7z://` or `tar://`
  (`-tzip`, `-t7z`, `-ttar`). Any other name, also a compressed tar, gets the
  existing "this archive format is not supported" message.
- An archive name that exists is refused: "Destination already exists: *name*".
- 7-Zip writes a temporary file beside the destination
  (`7za a -t... temp @list`, the chosen paths in a quoted UTF-8 list file), with
  progress and Cancel. After exit code 0 the file is renamed to the archive
  name. A failure or Cancel removes it.
- Each item is stored under its own name. Two chosen items with the same name
  (possible in search results) make 7-Zip refuse the run ("Duplicate
  filename"); nothing is written and the message is shown.

**Read-only.** The archive file systems implement reading only. Deleted from
`zip.py`: `mkdir`, `delete`, `prepare_delete`, `move`, `prepare_move`, the copy
into and between archives, the tasks `AddToArchive`, `UpdateArchive`,
`MoveOutOfArchive`, `CopyBetweenArchives`, `MoveBetweenArchives` and `Rename`,
and their helpers (empty-parent restore, archive state, tree digest, output
verification). `ArchiveUpdateError` and the `zip://` rule in `MoveFiles` go
with them.

Every write gets one message. A file system declares it with one optional
attribute, `read_only_message`, empty by default in `FileSystem`
([fs.py](../src/main/python/fman/fs.py)). `MotherFileSystem`
([mother_fs.py](../src/main/python/fman/impl/plugins/mother_fs.py)), which every
command passes through, checks it first in each write entry point and raises
`UnsupportedOperation` with that message:

- `touch`, `mkdir`, `makedirs`, `delete`, `prepare_delete`, `move_to_trash` and
  `prepare_trash`, for their target.
- `move`, `prepare_move` and `rename_no_replace`, for the source and the
  destination.
- `copy` and `prepare_copy`, for the destination.

The check runs before the existing fall-back to the other file system. Without
it, moving a file out of an archive shows that file system's error:
"LocalFileSystem only supports transferring to and from file://."

The archive file systems set "Archives are read-only. Unpack the archive,
change the files and pack them again." Copy, Move and Rename already show an
error's text. `_Delete` changes to show it when the error carries one. New
folder is hidden inside archives, as New file is today, because the file system
no longer implements `mkdir`. Commands still ask first and are refused
afterwards, as today.

**Compressed tars.** A new `CompressedTarFileSystem(_7ZipFileSystem)` with
scheme `ctar://` ("compressed tar"), exported with the other archive file
systems. The bundled
[AppSettings.yaml](../src/main/resources/base/Plugins/Core/AppSettings.yaml) maps
the nine suffixes to `ctar://`. Every existing lookup already picks the longest
matching suffix, so `x.tar.gz` gets `ctar://` while `x.tar` keeps `tar://`.
7-Zip detects the compression from the file content, so one scheme serves all
nine suffixes. It differs from the other types in one point: 7-Zip reads the
inner tar through a pipe.

- Listing: `7za x -so x.tar.gz | 7za l -si -ttar -slt`.
- Extraction: `7za x -so x.tar.gz | 7za x -si -ttar`, with the same name list.
  Checked for gzip, bzip2, xz and zstd with `./` names, a folder, a leading
  space and non-ASCII letters.
- Nothing is written besides the stage. There is no temporary tar.
- A tar has no index, so each listing and each extraction decompresses the
  whole archive once. Unpack decompresses once after browsing and twice
  otherwise; so does a copy.
- Accepted only when 7-Zip reports the archive's type as gzip, bzip2, xz or
  zstd and both processes exit with 0. A listing without entries is an empty
  tar only when the first 512 decompressed bytes, read in a second short run,
  are zero. Otherwise: "Not a compressed tar archive". Through a pipe 7-Zip
  lists a zip, a plain tar or text as zero entries with exit code 0, so the
  exit codes alone are not enough.
- Progress: the decompressing 7-Zip reports its percentage on standard error
  (`-bsp2`). Inside a task it drives the progress window. Outside a task the
  status bar shows "Reading x.tar.gz: 45%" through the public
  `show_status_message`, updated only when the percentage changes and at most
  every 250 ms, and cleared in a `finally`.
- A read outside a scan or a task cannot be cancelled. It does not block the
  application.

**Symbolic links.** Every extraction runs with `-snl-`, for every archive type,
so links are never created. Today one link fails the whole run on an account
that may not create links; checked for a tar and a zip, where the failed run
also left an empty file. When the task ends it reports "N symbolic links were
skipped" once, counted from the marked members among those it extracted. A
chosen item that is a link is skipped the same way. Hard links extract as
ordinary files.

**Context menu.** `File Context Menu.yaml` of Core gains two entries in its
`archive` group, after the Pack entries: "Unpack to..." (`unpack_archive_to`)
and "Unpack here" (`unpack_archive`). They are always shown (user decision,
2026-11-23: a visibility check would add latency to every menu). On a file that
is not an archive the command shows its message. The Everything plug-in refuses
`unpack_archive` in its folder list; `unpack_archive_to` joins that list.

**Threads.** A list is built on the thread that needs it: the scan worker or a
command thread. 7-Zip runs for extraction and packing happen inside tasks.
Nothing touches Qt except the status message and the task window, through their
public functions.

**Explorer items.** No change in
[shell_items.py](../src/main/python/fman/impl/shell_items.py) or the drop and paste
code: once the bundled handlers list the suffix, `x.tar.gz\dir\a.txt` maps to
`ctar://C:/…/x.tar.gz/dir/a.txt` and copies through `Copy`. Explorer shows the
members of a `./` archive without the prefix; the member list maps them to the
stored names. Many items dropped from Explorer's view of one archive are one
7-Zip run.

## Alternatives

- **Keep changes in place as they are** (today): nothing is removed, but these
  operations stay at one 7-Zip run per item and keep the most delicate code.
  Rejected for now (user decision, 2026-11-23).
- **Changes in place in one run** (one `a`, `d` or `rn` run for all items): fast,
  but new code with its own failure cases, and a solid `.7z` is still
  compressed again. Not now; it can be the later task.
- **One 7-Zip run per chosen item** (today): 1.47 s per file of the CelebA zip,
  about 83 hours for all of them. Replaced by one run per archive.
- **"Unpack to..." through the copy pipeline** (the previous revision): merges
  and asks about overwrites, but gathers every item first: about 86 s for the
  CelebA zip. Replaced by the whole-archive run; merging stays with Copy.
- **Extract straight into the destination folder**: saves the renames, about
  20 s for 202,600 top-level entries. But a failed or cancelled run leaves
  partial files in the user's folder. Rejected.
- **A visibility check for the menu entries**: hides them on other files, but
  runs every time a menu opens. Rejected (user decision).
- **A temporary inner tar for compressed tars** (the previous revisions, with a
  cache, a reading task, free-space rules and cleanup at quit and after a
  crash): it saved decompressions when every chosen item had its own 7-Zip run.
  With one run per operation it only helps a second copy from the same archive.
  Removed. Cost: an item dropped from Explorer out of an archive that was not
  browsed decompresses twice, once for the list and once for the copy.
- **Cancel for every read**: `resolve`, `is_dir` and `exists` carry no
  cancellation, so this needs a new way to pass one. Not adopted: these reads
  do not block the application.
- **Single-pass Unpack for compressed tars** (copy each decompressed block to
  the lister and the extractor): halves Unpack for xz and bzip2 archives that
  were not browsed, but needs a third process and a copy loop. Not adopted.
- **Extract the whole folder and publish only the chosen items**: needs no name
  list, but choosing 100 files would extract 1.3 GiB. Rejected as the rule. As
  an exception for a large partial choice from one very large folder it would
  cap the time near the whole folder's: about 53 s for the CelebA zip, against
  an estimated 4 minutes for half of its files. Not adopted now: it is not a
  normal case and adds a rule.
- **Exclude list for a nearly complete choice** (`-x@`): halves the worst case
  of the name list. Not adopted now; it can follow if large partial choices
  matter.
- **Skip the copy-into-itself test for archive sources**: gathering takes 5 s
  instead of 12 s, but a URL with an archive scheme can address a real folder
  that is named like an archive. The test stays and becomes cheaper.
- **Refuse archives above a member limit**: bounds memory, but a large `.zip`
  that opens today would be refused. Old lists are dropped instead.
- **Refuse or report names that Windows changes on copy-out** (`aux.c` becomes
  `_aux.c`; of `Makefile` and `makefile` one remains): kept as it is and
  documented (user decision, 2026-11-23). Unpack refuses such an archive.
- **A read-only check in each command, before its prompt**: refuses earlier, but
  needs a call in every command and cannot cover a destination the user types.
  Rejected.
- **Python `zipfile` and `tarfile`**: a second archive code path beside 7-Zip,
  with its own extraction safety checks. Rejected.
- **Map the compressed tar suffixes to `tar://`**: 7-Zip lists only the inner
  `x.tar`. Rejected.
- **Windows' copy engine** (`IFileOperation`) for unsupported Explorer items:
  tested working, but it bypasses the application's prompts, progress and safe
  copy, and reverses an earlier decision. Rejected.
- **Full 7-Zip** (`7z.exe` and `7z.dll`) for `.rar` and `.iso`: a packaging
  change and wider scope. Deferred.

## Runtime Effects

- Startup and unused path: nothing. No process, thread or temporary file exists
  until an archive is used. The read-only check adds one attribute lookup to
  each write call. The menu entries add no check.
- The CelebA zip (202,600 files, SATA SSD, real-time antivirus on). The new
  times are sums of stages measured separately, not one run:

| Operation | Today | With the policy |
|---|---|---|
| Enter the archive | 1.2 s | 1.2 s |
| Open one of its folders again | 1.2 s, a new listing | 0.1 s, from memory |
| Unpack here | 54 s | About 52 s |
| Unpack to..., new folder | Not available | About 52 s |
| Unpack to..., existing folder | Not available | About 73 s |
| Enter, Select all, F5 | About 83 hours | About 85 s |

- 7-Zip alone needs 53 s for this archive. Unpack adds the listing (1.2 s) and
  the name rules (0.5 s). An existing folder adds the existence check (1.1 s)
  and one rename per top-level entry (20 s for 202,600; an archive with one
  top-level folder needs one). The copy adds the gathering (12 s) and one rename
  per chosen item.
- A copy of part of the CelebA zip's one folder, 7-Zip's run: 0.2 s for 10
  files, 0.3 s for 100, 1.8 s for 1,000, 9.6 s for 5,000 and 43 s for 20,000.
  Today each file takes 1.47 s. The time grows with the chosen names times the
  entries of their folder, so an archive organized in folders stays fast: 500
  of the 1,000 files of one folder among 200 took 0.2 s.
- Cancel during a large extraction removes the stage: about 10 s for 200,000
  files.
- Pack: one run. 2,002 chosen small files took 0.2 s as `.7z` in one run; today
  each chosen item is its own run.
- Compressed tars write nothing besides their output. First open of a 2 GiB tar
  of 16,384 files (0.5 GiB compressed, NVMe SSD, warm): the files are shown
  after 1.84 s (gzip), 0.55 s (zstd) and 8.21 s (xz). Unpack of a 257 MiB tar
  that was not browsed, both passes: 1.66 s (gzip), 1.40 s (zstd), 4.74 s (xz)
  and 4.57 s (bzip2).
- A pane saved inside an archive builds its list when the application starts.
  `_init_pane` sets the saved location when that read returns, so a pane the
  user moved meanwhile returns to it, as for any slow location today.
- Memory: about 250 bytes per member: 47 MiB for the 202,600 members of the
  CelebA zip. Kept lists hold at most 1,000,000 members together, plus the
  newest list when it is larger.
- Status bar updates are throttled to 4 per second.
- Cancellation: pane navigation or task Cancel stops 7-Zip. A read started by
  `resolve`, `is_dir` or `exists` outside these cannot be cancelled; it ends
  with the archive.

## Tests

Unit (Core), with fixtures written by Python `zipfile` and `tarfile` (plain,
`w:gz`, `w:bz2`, `w:xz`, `w:zst`), the tars also with `./` names as
`shutil.make_archive` writes them:

- Member list: listing, nested folders, `is_dir`, size and modified time for
  every type. One 7-Zip listing per archive version (count 7-Zip starts):
  folders, `is_dir`, `exists` and `resolve` start no process; a changed archive
  lists again; lists above the kept total are dropped, least recently used
  first. Absolute and `..` names are refused with the message.
- Extraction, for `.zip`, `.7z`, `.tar` and a compressed tar: several chosen
  members, a chosen folder and names with a leading space, non-ASCII letters,
  `@` and `!` come out exactly, in one run. Every entry of a folder chosen
  passes no names for them.
- Extraction failures: a failed or cancelled run publishes nothing and leaves
  no stage; a failed rename stops, names the item and keeps the items already
  moved; a file is replaced only where the copy agreed; one notification per
  destination folder.
- Unpack here: the existing tests pass (new folder, existing destination
  refused, name rules, Cancel). No second listing when the list exists.
- Unpack to...: the prompt names the archive and defaults to the other pane's
  folder; a missing folder two levels deep is created and published with one
  rename; an existing folder receives the top-level entries; one existing
  top-level name refuses before 7-Zip starts and changes nothing; a relative
  path; a path that is a file or not local is refused; the source refusals of
  Unpack here.
- Copy: gathering 1,000 members starts no 7-Zip process and resolves each
  source and each folder above the destination once; a merge into existing
  folders with yes and no answers is one run; the copy-into-itself results are
  unchanged, including a `zip://` URL of a real folder named like an archive.
- Pack: several chosen items are one run for `.zip`, `.7z` and `.tar`, stored
  under their names; an existing archive name and two items with the same name
  are refused and write nothing; Cancel and a failure leave no temporary file;
  a compressed tar name and a source that is not local are refused.
- Read-only, for every type: Copy into, Move into, out of and within, Rename,
  Delete, Delete permanently and New folder each show the one message, and the
  archive's bytes are unchanged.
- Compressed tars: listing and extraction for each suffix. A zip, a plain tar
  and a text file named `x.tar.gz`, a gzip of text (small and large) and a
  truncated archive are refused and keep no list. An empty tar opens as an
  empty folder. No file is written besides the stage. Cancel ends both
  processes.
- Progress: a read outside a task shows "Reading ...: N%" messages (fake 7-Zip
  progress records), at most one per 250 ms, and clears the message on
  success, failure and Cancel.
- Links: a tar and a zip with a symbolic link extract with exit code 0, create
  no link and report the count once; a chosen link is skipped.

Unit (host):

- `MotherFileSystem` refuses every write entry point for a file system with
  `read_only_message`, before the fall-back and without calling the file
  system; a file system without the attribute behaves as before.
- `shell_items` maps `x.tar.gz\dir\a.txt` and `x.tgz\a.txt` to `ctar://` with the
  bundled handlers; `x.tar` still maps to `tar://`.
- `File Context Menu.yaml` holds the two entries with their captions. The
  Everything folder list refuses `unpack_archive_to`.

Integration (native Windows):

- Build Explorer's real drag data for an item inside a `.tar.gz` (the archive
  folder's own data object), drop it on a pane and check the extracted bytes.
  Skip with a message where Explorer cannot open `.tar.gz` (older Windows).
- The existing Explorer item tests for `.zip`, `.7z` and `.tar` pass.

The tests of the deleted operations are deleted with them.

Manual:

- `CelebAAligned.zip`: Unpack here; Unpack to... a new folder and an existing
  empty folder; Enter, Select all, F5. Compare with the table above, check
  202,600 files each time, and Cancel in every stage.
- A large `.tar.gz` (about 1 GB): first open with the status bar progress, no
  temporary file, Unpack with and without browsing first, Cancel.
- Right-click an archive: "Unpack to..." and "Unpack here" work. On another
  file each shows its message.
- Drag and paste from Explorer for `.zip`, `.tar.gz` and `.tar.zst` on
  Windows 11.
- A pane left inside a compressed tar: restart opens that folder.

## Implementation Steps

Steps 1 to 5 need no compressed tar code. Step 2 fixes the reported copy, and
step 3 makes both Unpack commands fast.

1. Add the member list to `_7ZipFileSystem` (direct listing, folder index,
   identity check, `./` names, link marks, kept total) and answer `_iter_infos`
   from it; remove `_put_in_cache`. The existing read tests pass.
2. Make `Extract` the one extraction task (names in a list file, pairs,
   publishing, `-snl-`, the report of skipped links), let
   `FileTreeOperation._enqueue` add pairs to it, and make the copy-into-itself
   test resolve each URL once.
3. Run Unpack here on the member list and the new `Extract`; add
   `UnpackArchiveTo`, the name "Unpack here" and the two context menu entries;
   refuse the new command in the Everything folder list.
4. Pack in one run, with the temporary file and the two refusals.
5. Read-only: add `read_only_message` and the check in `MotherFileSystem`, show
   the message in `_Delete`, and delete the write methods, tasks, helpers and
   their tests.
6. Add `CompressedTarFileSystem` (piped listing and extraction, the acceptance
   checks, progress), export it, and add the nine `ctar://` entries to the
   bundled `AppSettings.yaml`.
7. Add the `shell_items` tests and the native Explorer drop test.
8. Update [docs/archives.md](../docs/archives.md),
   [docs/advanced.md](../docs/advanced.md) and
   [docs/file-system-operations.md](../docs/file-system-operations.md) (the
   policy, the removed operations and how to change an archive, both Unpack
   commands, supported types, skipped links, names that Windows changes on
   copy-out), [PlugIn.md](../PlugIn.md) (`read_only_message` and its place
   before the provider fall-back), [README.md](../README.md) (feature list),
   the [Core README](../src/main/resources/base/Plugins/Core/README.md) and
   `CHANGELOG.md`.

## Acceptance Criteria

- Unpack here, Unpack to..., a copy of chosen items and Pack each start one
  7-Zip run per archive, whatever the number of items (one pipe for a
  compressed tar).
- Once an archive's list exists, opening its folders, gathering a copy and the
  checks before an operation start no 7-Zip process.
- For `CelebAAligned.zip` on the machine of the measurements: Unpack here and
  Unpack to... a new folder finish within 70 s, Unpack to... an existing folder
  within 100 s, and Enter, Select all, F5 within 2 minutes. Every file arrives,
  and Cancel works in every stage.
- Unpack only creates. An existing folder (Unpack here) or one existing
  top-level name (Unpack to...) refuses the operation before 7-Zip starts.
  Nothing is merged or overwritten.
- A copy of chosen items keeps its prompt, its merge and its overwrite
  questions. A file is replaced only after a yes.
- A failed or cancelled run publishes none of its items and leaves no temporary
  folder or file.
- Pack creates a new archive in one run and refuses a name that exists.
- Every operation that would change an archive is refused with the same
  message, for every archive type. No archive file changes through the
  application.
- Enter on each of the nine compressed tar suffixes opens the members and
  writes no file. Unpack and copy from them write nothing besides their output.
  A file that is not a compressed tar is refused with one message, whatever its
  name.
- Archives whose entries start with `./` open, copy out and unpack.
- Symbolic links in an archive do not fail an extraction. They are skipped,
  never created, and the task reports how many.
- The file context menu shows "Unpack to..." and "Unpack here". On a file that
  is not an archive the command shows a message.
- Copy and paste, and drag and drop, from Explorer's archive view of a `.tar.gz`
  extract with the usual prompt, progress and Cancel.
- While a compressed tar is read outside a task, the status bar shows the
  percentage, and clears it afterwards.

## Reviewers

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Designed with the user: read-only compressed tars in the application
  plus Explorer copy/paste and drag and drop, without Windows' copy engine.
  Verified on the current source: plain `.tar` already works end to end, including
  Explorer's real drag data; `x.tar.gz` reproduces the `archive_handlers` message;
  `7za` 26.03 reads gzip, bzip2, xz and zstd but lists only the inner tar, and the
  piped inner stream lists the members. Ready for review.

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Added, at the user's request, status bar progress for a pane's first
  open, a free-space check and piped Unpack without a temporary tar. Measured the
  first-open cost (256 MiB tar: gzip 0.51 s, zstd 0.14 s, xz 1.83 s; later
  listings 0.01 s). Verified that 7-Zip reports the inner size for gzip (modulo
  4 GiB) and xz but not for bzip2 or streamed zstd, and that piped extraction
  works. Review point: piped Unpack decompresses twice (entry check, then
  extraction), trading time for disk space. Ready for review.

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: Needs revision before implementation. The approach is sound and the
  plan's 7-Zip claims reproduce. Three findings make the acceptance criteria
  fail on common archives or in the main Explorer scenario: F01 (`./` names),
  F02 (symbolic links) and F03 (archive reads outside the scan and the task).
  F04 proposes browsing without the temporary tar. F10 answers the designer's
  review point. Added the status line; the design text is unchanged. No
  application code changed.

Priorities are High, Medium and Low.

#### Real Archives

**F01 - High: archives with `./` names cannot be opened.** `tar -czf x.tgz .`
and Python's `shutil.make_archive` write entries named `./docs/a.txt`, plus a
`.` entry. 7-Zip lists them as `.\docs\a.txt`. Probe on the existing tar code,
which the new file system inherits: the pane listing fails with "Invalid
directory entry name" and Unpack refuses with "Archive entry name may be
changed by extraction: .". Explorer's namespace resolves the same members
without the prefix (`x.tgz\docs\a.txt`), so its items map to `.../docs/a.txt`.
7-Zip does not match that: `-i!docs/a.txt` extracts nothing, `-i!./docs/a.txt`
works. Required: show names without the leading `./`, skip the `.` entry, pass
7-Zip the stored name, and do the same in Unpack's name check. Add `./`
fixtures to each test group. Plain `.tar` has this defect today. Entries with
absolute or `..` paths also fail the listing; give them one clear message.

**F02 - High: one symbolic link stops a copy or an Unpack.** Tar archives
from Linux often contain symbolic links. Without the Windows symlink privilege
(the default, and this development account) 7-Zip reports "Cannot create
symbolic link", exits with 2, and the task fails: copying a folder that holds
one link delivers nothing. Links that point outside the output fail the same
way with the privilege. With `-snl-`, 7-Zip skips link entries and exits 0;
the listing names them (`Symbolic Link = ...`). Decision for the user:

- Recommended: extract with `-snl-`, never create links, and report
  "N symbolic links were skipped" when the task ends.
- Or keep failing, with a short message instead of 7-Zip's output.

Hard links extract as ordinary files and need no change.

**F11 - Medium: copy-out changes names silently.** Existing behavior that
Linux archives make common. Copying a folder out renames `aux.c` to `_aux.c`
and `a:b.txt` to `a_b.txt`, and keeps one of `Makefile` and `makefile`. Unpack
refuses the same archive. Decision for the user: document it, or run Unpack's
name check on the copied folder's entries first and refuse (cheap with F04).

#### When the Archive Is Read

**F03 - High: the archive is read before the scan and before `Extract`.** The
plan confines decompression to the pane scan and to `Extract.__call__`. Other
calls read the archive first, through `_iter_infos`, which has no cancellation
argument:

- One item dropped or pasted from Explorer: `Copy` calls `is_dir` on it before
  it shows its prompt. Probe on the existing tar code: one archive read, the
  Copy prompt, 16 more reads while gathering, then `Extract`. (`is_parent`
  resolves the source for each destination path component, two reads each.)
- Several items: the reads start in the "Gathering files" step.
- A pane saved inside an archive: startup calls `is_dir` before navigating.
  History, Favorites and Go To reach a subfolder through `resolve`.

With the plan, the first of these reads decompresses the whole archive to
disk without progress or Cancel. In the plan's main scenario that happens
before the user confirms the copy. Required: state which calls may start a
read of an archive that is not cached, and how each shows progress and
cancels. Recommended with F04: every such read shows the status bar progress;
scans and tasks can cancel it; `resolve` of a member checks only the archive
file and lets the scan report a missing folder. Correct "Startup and unused
path: nothing" in Runtime Effects.

**F04 - Medium: browse from a member list in memory.** A piped listing
(`7za x -so x | 7za l -si -ttar -slt`) takes the same time as writing the
inner tar and returns the same records (table below). Keep the parsed list in
memory per archive identity and answer `scan`, `is_dir`, `exists`, sizes and
dates from it:

- Enter writes nothing to disk. The free-space question moves to copy-out,
  inside a task with a dialog and Cancel.
- Folders inside the archive open without starting 7-Zip. Today every folder
  runs 7-Zip over the whole tar (0.21 s to list 50,000 members), and copy-out
  repeats that for the reads in F03.
- Cost: browsing and then copying out decompresses twice. Memory is one small
  record per member.

The inner tar stays for copy-out, where several `Extract` tasks share one
decompression. The plan rejected piping because every listing would
decompress; the list in memory removes that reason for browsing. Decision for
the user.

#### Refusals and Temporary Data

**F05 - Medium: three refusals do not show the read-only message.** Probe
with the plan's overrides on a stub file system:

- F6 out of the archive shows "LocalFileSystem only supports transferring to
  and from file://.". The host asks the destination file system after the
  source refuses and shows the second error.
- Delete permanently and F8 show `_Delete`'s own texts. The F8 text tells the
  user to use Delete permanently.
- Copy to another archive shows an empty alert (existing for `7z://` to
  `zip://`).

Copy in, Move in and Rename show the message. New folder stays in the menus
inside the archive because `mkdir` is overridden. Required: name the host or
command change for each case, and test the alert text through the commands,
not only the exception of the file system.

**F06 - Medium: the inner tar's file name must not come from the archive.**
`7za e` takes the output name from the archive: `sample.tgz` gives
`sample.tgz`, and a gzip header can name it `report.exe`, `_NUL` or `a_b.tar`.
7-Zip strips folders, so nothing escapes. Use `7za x -so` with standard output
opened on a file the application creates: same speed, and progress arrives on
standard error with `-bsp2`. This removes the "exactly one regular file" rule
and name clashes between archives. The `-ttar` check stays.

**F07 - Medium: guard the disk when the size is unknown.** bzip2 and streamed
zstd give no size (Python's `w:zst` fixtures are streamed), and gzip's is a
lower bound (a two-member gzip reported half). A small archive can fill the
temporary drive to zero before 7-Zip fails, which disturbs other programs.
Required: refuse when free space is below the compressed size, and stop 7-Zip
when free space falls under a stated reserve, checked at each progress update.

**F08 - Medium: lifetime of the temporary tar.**

- `_reading_path` returns a path, so eviction can delete the file before
  7-Zip opens it. Two panes and one drop make three archives against a limit
  of two. Return a lease that pins the entry while a listing or `Extract`
  uses it.
- 7-Zip processes are not in a job object and outlive the application. End
  running decompressions on `aboutToQuit`, as QuickView's CSV helper does,
  before removing the session folder.
- After a crash, gigabytes stay behind. On first use, remove session folders
  whose lock file is no longer held.
- Compare the archive's identity again after decompression. Do not cache a
  copy of a file that changed meanwhile.
- A scan that waits for another decompression stays cancellable and takes
  over when the owner is cancelled.

**F09 - Medium: the cache location needs the user's decision.**
[AGENTS.md](../AGENTS.md) keeps mutable state under `UserSettings`, and
QuickView's CSV cache (up to 8 GiB) is in `UserSettings\Cache`. The plan uses
the system temp folder. That is faster for a portable copy on removable media,
but leaves decompressed archive contents on the host computer after a crash.
Recommended: `UserSettings\Cache`. If temp is kept, record it as an approved
exception.

#### Unpack

**F10 - Medium: Unpack in one pass.** Copy each decompressed block to both the
lister and the extractor. Probe on xz: 2.30 s, against 4.74 s for the plan's
two passes and 2.95 s through an inner tar. gzip and zstd differ by 0.2 s at
most. Safety is unchanged: output goes to the temporary sibling folder and is
renamed only after the name check and the extraction both succeed. Cost: a
third process and the copy loop. Recommended; two passes remain acceptable if
simpler code is preferred.

#### Smaller Points

**F12 - Low.**

- Decompression inside `Extract` must not advance the task's progress.
  `run_7zip_with_progress` only moves forward, so extraction would show
  nothing after decompression reaches 99.
- Clear the status message in a `finally`. It shares the status bar with the
  filter count and other messages.
- Tests to add: `./` names, a link member, a gzip with a header name, three
  archives against the limit of two, cancel while waiting, startup inside an
  archive, and the Explorer mapping of a `./` archive.
- [TODO.md](../TODO.md) still reports plain `.tar` as not registered. The
  bundled settings map `.tar` now and in v0.20.4. If a plain `.tar` failed,
  that is a separate defect this plan does not cover.

#### Review Validation

Disposable probes with the bundled `7za` 26.03 and Python 3.14.7 in temporary
folders, removed afterwards, on Windows 10.0.26300. No application tests,
suite or build were run.

Reproduced from the plan: the outer listing shows only the inner tar; `-ttar`
on the archive fails; the piped listing equals the plain tar's for all nine
suffixes; sizes are reported for gzip and xz only; a non-tar passes `e` and
fails `-ttar`; Explorer's namespace maps `x.tar.gz\docs\a.txt` to the archive
and its members.

Timings: a 257 MiB tar of 2,048 files, about 129 MiB compressed, warm, medians
of three. Half of the data is random, so absolute times differ from the plan's.

| Seconds                         | gzip | zstd |   xz | bzip2 |
| ------------------------------- | ---: | ---: | ---: | ----: |
| First open: `e` to a file       | 0.25 | 0.10 | 1.82 |  1.75 |
| First open: `-so` to own file   | 0.27 | 0.11 | 1.75 |  1.70 |
| First open: piped listing       | 0.23 | 0.09 | 1.74 |  1.68 |
| Unpack: two passes (plan)       | 1.66 | 1.40 | 4.74 |  4.57 |
| Unpack: one pass                | 1.47 | 1.50 | 2.30 |  2.25 |
| Unpack: through an inner tar    | 1.84 | 1.30 | 2.95 |  3.02 |

Listing an inner tar took 0.017 s at 2,048 members and 0.21 s at 50,000.

Not verified: a real Explorer drag or paste, archives over 4 GiB,
cancellation, the free-space paths, extraction with the symlink privilege, and
any prototype of the cache or the member list.

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: Recorded two user decisions. F02: symbolic links are skipped with
  `-snl-`, never created, and reported; added to Scope, Design, Tests and
  Acceptance Criteria. F09: the cache stays in the system temp folder, as an
  approved exception; noted under Alternatives. With temp chosen, the crash
  cleanup in F08 matters more. F04, F10 and F11 await the user's decision; the
  other findings are open for the next design revision.

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: Revised the design after the user's decisions. F04 was approved for
  every tar type on two conditions, both met. It works for all nine suffixes
  and plain `.tar`. The files are shown in the same time or less: on a 2 GiB
  tar, gzip 1.84 s against 2.30 s, zstd 0.55 s against 0.93 s, xz 8.21 s
  against 8.42 s. F10 is not adopted: the user's condition was faster with
  fewer edge cases, and a single pass is faster for xz and bzip2 only and adds
  failure paths. With the member list, Unpack after browsing is one pass
  anyway. F11: kept as it is and documented. Folded F01, F03, F06, F07, F08 and
  F12 into the design; they needed no decision. New in this pass: through a
  pipe 7-Zip lists a zip, a plain tar or text as zero entries with exit code 0,
  so the member list has three acceptance checks. Plain `.tar` skips symbolic
  links too: asked, the user chose the simpler option with fewer edge cases,
  and one rule for every tar type removes a per-type branch and the copy that
  fails on accounts that may not create links. Open: F05. Probes as before,
  plus a 2 GiB tar and twelve piped inputs, eight of them empty, truncated,
  wrong or misnamed. Nothing was run in the application.

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: Closed the two open points; the user approved both as the simplest
  robust options. F05: one read-only check in `MotherFileSystem`, before the
  provider fall-back that replaced the message; `CompressedTarFileSystem` no
  longer overrides write methods. Reads without Cancel: `Copy` starts with a
  reading task for an archive without a list; navigation reads stay as they
  are. Corrected in this pass: the previous revision made a copy from Explorer
  decompress twice (the list through the pipe, then the inner tar); the
  reading task writes the inner tar once and lists from it. Read in the code:
  commands run on their own threads, `submit_task` runs its task before
  returning (as `UnpackArchive` uses it), `_set_location` drops a navigation
  that was superseded, `_init_pane` does not. Probes: a listing of the inner
  tar gives the same records as the pipe (gzip and xz, with `./` names and a
  link); 7-Zip lists an empty tar with exit code 0 in a file named `.tar` and
  with exit code 2 in a file named `.bin`. Clarified: a plain `.tar` is listed
  as today, whatever 7-Zip's exit code. The user renamed this file to
  `Archives001.md`; it keeps its earlier layout. Nothing was run in the
  application.

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: Added the second goal at the user's request: the `TODO.md` report
  that extracting the CelebA zip is too slow. Cause, measured with the
  application's code on the reported archive (202,600 files in its root): a
  copy handles each chosen item alone, with nine 7-Zip listings and one
  extraction, 1.47 s per file (14.7 s for 10 files, 58.8 s for 40). Unpack
  works: 53.8 s, against 52.6 s for 7-Zip alone. Design added: the member list
  for every archive type, one `Extract` per archive and destination folder, a
  cheaper copy-into-itself test, and Unpack's name rules on the list. Changed
  with it: the member limit no longer refuses an archive, because that would
  refuse a large `.zip` that opens today. Probes behind the numbers: gathering
  202,600 members answered from memory took 59 s as the code is, 12 s with each
  URL resolved once and 5 s without the test; a 7-Zip name list cost 1.6 s,
  8.6 s and 37.7 s for 1,000, 5,000 and 20,000 names; 182,600 renames took
  17.5 s; a member list of this archive held 47 MiB; a quoted list file
  extracted exactly 21 awkward names, and an unquoted one lost a name with a
  leading space. Limits: the 85 s is a sum of stages, not one run. Nothing ran
  in a window, so pane refreshes during the copy are not measured, nor is a
  drop of 202,600 items from Explorer. Move out of an archive, Delete inside
  one and Pack still run 7-Zip once per chosen item; they are excluded here.
  The probes wrote only to work folders beside the archive and in the system
  temp folder; all were removed. Nothing was implemented.

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: Added the third goal at the user's request, from two `TODO.md`
  items as the user rephrased them. Reading of the first item: the archive's
  content goes straight into the chosen path, with the other pane's folder as
  the default, and no folder named after the archive is added. Design:
  `UnpackArchiveTo` hands the archive's root entries to the copy pipeline, so
  it adds no extraction code and follows the copy's rules. "Unpack here" is the
  existing Unpack archive command, added to the menu. Both commands are shown
  only while one local archive is chosen. Probe on today's code (small zip, the
  pipeline as it is): a destination two levels deep was created, an existing
  folder was merged after one overwrite question, a file at the destination
  path was refused, and the archive stayed unchanged. Read in the code: the
  menu and the Command Center both use `is_visible`; a right-click on a file
  outside the selection selects that file alone; `load_settings` answers from
  a cache; a test pins "Unpack archive" as the first name. Costs recorded:
  "Unpack to..." changes names as a copy does, where Unpack refuses the
  archive; for a compressed tar it writes the temporary inner tar; for the
  CelebA zip it needs about 86 s against 54 s for Unpack here. The 86 s is a
  sum of stages. Nothing was run in the application and nothing was
  implemented.

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: Rewrote the document above the records around one policy, at the
  user's request for a simple, fast and coherent rule set for all archive
  operations. User decisions: archives are read-only for every type, for now;
  Unpack here and Unpack to... are the simplest whole-archive operations and
  delicate work is done by entering the archive; no visibility check for the
  menu entries. Consequences in the design: one `Extract` task for both Unpack
  commands and the copy; "Unpack to..." only creates and no longer goes through
  the copy pipeline; Pack is one run; the write code of `zip.py` is deleted.
  Removed from the earlier revisions: the temporary inner tar with its cache,
  free-space rules and cleanup, the reading task, the `is_visible` checks and
  the archive-type message. Review findings F06 to F09 no longer apply, since
  no temporary tar exists; F01 to F05 and F12 remain answered. Probes for this
  revision: chosen names extract through the pipe from gzip, bzip2, xz and zstd
  tars (exact output, both exit codes 0; a truncated archive gives 2 and 2);
  Unpack's name rules took 0.48 s for 202,600 names from memory, and the
  existence check 1.12 s; `os.rename` refuses an existing file and folder; one
  Pack run stored 2,002 chosen items from two folders under their names and
  refused two items with the same name; changing a 145 MiB zip or a tar copies
  it at file-copy speed, deleting from a solid 7z took 18.6 s against 15.9 s
  to create it, and 7-Zip cannot change a `.tar.gz`; a link in a zip fails a
  default extraction with exit code 2 and is skipped with `-snl-`. Limits: the
  CelebA times are sums of stages measured separately; nothing ran in a
  window; the piped extraction was not timed above 65 MiB; Pack and the
  extraction with pairs were probed with 7-Zip directly, not as application
  code. Nothing was implemented.

### 2026_11_23 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M
- Outcome: Corrected the cost of a name list after the user asked whether a
  copy of part of a large archive is fast. 7-Zip compares a chosen name with
  the entries of its own folder, not with the whole archive. Probes: from the
  202,600-file folder of the CelebA zip, one 7-Zip run extracted 10 files in
  0.17 s, 100 in 0.28 s, 1,000 in 1.82 s and 5,000 in 9.61 s (20,000 took 43 s
  earlier); in a zip of 200 folders with 1,000 files each, 500 names of one
  folder matched in 0.13 s and 10,000 names from 20 folders in 0.21 s, against
  0.18 s for a listing without names. One slow case remains and is recorded
  under Alternatives: a large partial choice from one very large folder. Not
  measured: these copies through the application, and browsing in a window.

## Implementation

### Implementer - Claude Opus 5.5

- Date: 2026_11_23
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 1M

- **Changes**: An earlier session on this task stopped before finishing and
  left its work uncommitted; the user supplied its transcript. It implemented
  steps 1 to 6 and most tests. This session verified that work against the
  design, completed steps 7 and 8, fixed the review findings below and ran the
  acceptance measurements. Files:
  - [zip.py](../src/main/resources/base/Plugins/Core/core/fs/zip.py): member list
    (`_MemberLists`, `_Members`, `_read_members`, `_DirectReader`, `_PipedReader`);
    `Extract` with member/destination pairs, `batch_key`/`absorb`, name list file,
    `-snl-`, staging and publishing, and the `new`/`into` modes for Unpack;
    `PackArchive`; `CompressedTarFileSystem` with `_Decompressor` and
    `_StatusProgress`; `READ_ONLY_MESSAGE`. The write methods, tasks and helpers
    are deleted. This session also deleted `_unpack_manifest`: Unpack's name rules
    run as `_read_members(...).check_names()`, and the tests moved to that path.
  - [fileoperations.py](../src/main/resources/base/Plugins/Core/core/fileoperations.py):
    `_enqueue` joins tasks with the same `batch_key`; `_is_parent` resolves each
    URL once per operation and compares only URLs of the same scheme.
    `ArchiveUpdateError` and the `zip://` move rule are deleted.
  - Core commands: `UnpackArchiveTo` (`unpack_archive_to`), `_chosen_archive`
    shared with `UnpackArchive`, the alias "Unpack here", Pack through
    `PackArchive`, and `_Delete` showing an `UnsupportedOperation` text. `_Pack`
    is deleted.
  - Host: `FileSystem.read_only_message` ([fs.py](../src/main/python/fman/fs.py))
    and `MotherFileSystem._writable`
    ([mother_fs.py](../src/main/python/fman/impl/plugins/mother_fs.py)) in every
    write entry point listed in the design.
  - Settings and menus: the nine `ctar://` entries in
    [AppSettings.yaml](../src/main/resources/base/Plugins/Core/AppSettings.yaml),
    "Unpack to..." and "Unpack here" in Core's `File Context Menu.yaml`, and
    `unpack_archive_to` in the Everything folder list's refusals.
  - Performance suite: the archive-move workloads of the legacy suite are removed
    (`legacy.py`, `run.py`, its README), since archive moves no longer exist.
  - Tests: `test_zip.py` (member list, chosen items, compressed tars, status
    progress, Pack, read-only refusals), `test_unpack_archive.py`
    (`UnpackArchiveToTest`), `test___init__.py` (context menu entries, Pack,
    `_Delete` message), `test_fileoperations.py` (gathering without 7-Zip,
    resolving once, one run for a merge, read-only destination),
    `test_mother_fs.py`, `test_shell_items.py` (bundled `ctar://` mapping and a
    copy of Explorer's real items from a `.tar.gz`), `test_everything.py` and
    the alias check in `test_qt.py`.
  - Step 7: [explorer_archive_smoke](../src/integrationtest/python/fman_integrationtest/explorer_archive_smoke.py)
    also drops a folder from Explorer's view of a `.tar.gz` with `./` names onto
    a pane of the real application, and checks the bytes, the prompts and that
    both archives are unchanged. It skips that part where Explorer cannot open
    the type.
  - Step 8: [archives.md](../docs/archives.md), [advanced.md](../docs/advanced.md),
    [file-system-operations.md](../docs/file-system-operations.md),
    `docs/features.md`, [PlugIn.md](../PlugIn.md), [README.md](../README.md),
    the [Core README](../src/main/resources/base/Plugins/Core/README.md),
    `DEVELOPMENT.md` (the smoke), `CHANGELOG.md` and three `TODO.md` items.
- **Deviations**:
  - Cancel while items are moved into place stops between items, for a copy and
    for Unpack to... an existing folder. The design required Cancel in every
    stage but left this step implicit; without it, Cancel waited about 20 s for
    202,600 renames. The items already moved stay, each complete, as after a
    failed rename. In both cases the folders that received items are now
    announced; before, a failure skipped the announcement and left panes stale.
  - A copy replaces only an ordinary file: a file member over a regular file with
    one hard link and no reparse tag, after the user's yes. A folder or a link
    never replaces (review finding R01). The design said "a file replaces an
    existing file only where the user agreed".
  - Unpack's name rules no longer reject malformed listing records, as the
    deleted `_unpack_manifest` did; lines without ` = ` are ignored, as when
    browsing. Every listed name is still checked, and output is still staged and
    published by rename.
  - The native drop test is in `explorer_archive_smoke` (real window), not in
    `test_qt.py`, which runs offscreen. The unit suite maps and copies Explorer's
    real items from a `.tar.gz`.
  - Pack excludes its staging folder by its unique name (`-xr!`), so a destination
    inside a chosen folder works (review finding R03).
- **Validation Results**: see [Final Implementation](#final-implementation).

### Implementation Review - Code Review Agent

- Date: 2026_11_23
- Agent: GitHub Copilot (code-review agent)
- Model: Not exposed by host
- Effort: Not exposed by host
- Context Window: Not exposed by host

- **Verdict**: Changes requested.
- **Findings**: Three defects, each reproduced with disposable scripts.
  - R01 - Critical: `Extract` replaced with `os.replace` wherever the
    destination existed when the copy was prepared. A merge reaches a folder pair
    whose destination is a file without any question; on Windows a folder
    replaces a file this way, and the file was lost.
  - R02 - High: the readers did not close the listing generator. When
    `_read_members` raised (Cancel, or an entry outside the root), 7-Zip blocked
    on a full pipe, the thread never returned and the archive's build lock was
    never released.
  - R03 - Medium: Pack's staging folder, with the list of absolute source paths,
    was added to an archive whose destination lies inside a chosen folder.
- **Required Changes**: Replace only files the copy asked about; close the
  listing in both readers; keep the stage out of Pack's archive.

### Implementation Review - Gemini 4 Neon

- Date: 2026_11_23
- Agent: GitHub Copilot
- Model: Gemini 4 Neon
- Effort: High
- Context Window: 1M

- **Verdict**: Changes requested.
- **Findings**: Six defects reproduced with disposable probes against the bundled
  `7za` 26.03, plus three small refinements (large-ZIP timings assumed accurate):
  - R04 - High: `_7zip.__exit__` joins `self._stdout_lines` with `''` instead of
    `'\n'` after `progress_records` strips line breaks. `_cannot_read` drops the
    error reason whenever any prior line contains `' = '` and otherwise mashes
    lines together; `_cannot_pack` dumps the entire 7-Zip banner, scan output and
    temp staging path as one glued line.
  - R05 - High: `_PipedReader.read` rejects valid compressed tars of an empty
    folder (containing only `.` or `./`) with `"Not a compressed tar archive"`:
    `_Members.add` skips `.`/`./`, leaving `len(members) == 0`, and
    `_starts_with_zero_block` returns `False` on the `.` tar header.
  - R06 - Medium: `_Members.links` is an append-only list. When a tar updates a
    symlink path with a later regular file (or promotes it to an implicit folder),
    the path stays in `links`, causing `Extract._extract_chosen` to skip copying
    the real file. Duplicate link entries are also double-counted.
  - R07 - Medium: `_Members.prefix` is archive-wide. In an archive mixing `./`
    and bare paths, `self.stored` prepends `'./'` to unrelated implicit folders,
    failing extraction (`Not extracted`) on folder copy or all-children merge.
  - R08 - Medium: `_ordinary_file` checks `not getattr(info, 'st_reparse_tag', 0)`
    instead of masking `_REPARSE_NAME_SURROGATE` (`0x20000000`), blocking
    confirmed overwrites of OneDrive/Dropbox cloud placeholders.
  - R09 - Medium: In `Extract._unpack` (`into=False`), `_existing_ancestor` climbs
    past an existing non-directory file (running a full extraction before
    `os.makedirs` fails); multi-level new folders notify only the leaf instead of
    the existing parent folder so visible panes stay stale; and `_unpack` calls
    global `fman.fs.notify_file_*` instead of `self._fman_fs`.
  - Refinements (Low): validate the parent folder in `Pack`/`PackArchive` before
    creating the temp directory so missing parents do not leak the `.tmp` path;
    break on `----------` (and close the generator) in `_PipedReader.read`'s outer
    type check so misnamed large archives fail immediately; guard `process.kill()`
    in `_starts_with_zero_block` against `OSError`; add `.tar.bz2` and
    `.tar.zst` to `_find_extension_start`.
- **Required Changes**: Fix R04-R09 (and optionally the low-priority refinements)
  with focused regression tests covering each case.

### Implementation Review - Claude Fable 5.2

- Date: 2026_11_23
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M

- **Verdict**: Changes requested.
- **Findings**: Written after Final Implementation. Its focused test command
  passes here (485 OK, 3 skipped). The findings come from disposable probes: the
  file systems with the bundled `7za`, and the real application off-screen with
  isolated settings. The large-ZIP numbers were not re-checked, by request.
  - Open from the Gemini 4 Neon review: the code has no fix for R04-R09; Final
    Implementation covers R01-R03 only. Reproduced here: R04 (for example
    "Cannot read truncated.zip." without a reason, and Pack's duplicate-name
    message with the whole 7-Zip banner), R05, R06, R07 and R09. R08 was not
    reproduced: a OneDrive file on this machine reports no reparse tag and
    passes `_ordinary_file`; a file that is not downloaded was not tried.
  - R10 - High: Enter on an archive that cannot be listed does nothing and
    shows nothing. Seen in the application for random bytes named `.zip`, a
    truncated `.zip`, gzipped text named `.tar.gz` and a tar with
    `../escape.txt`: the pane stays, no dialog opens, and the reason is only
    printed to standard error. The acceptance criterion "refused with one
    message" is not met in the window. The cause is in host code this task did
    not change: the folder is read after `pane.set_path` returns, so the
    `except PermissionError` in `OpenDirectory` can never run, and with
    `onerror=None` the error goes to `sys.excepthook`, which only prints errors
    of Core. Enter on a local folder without list permission is silent the
    same way. New with this task: a damaged archive used to open with the
    entries 7-Zip could list, possibly none; now nothing happens.
  - R11 - Medium: a chosen item gets another item's content when two names
    differ only by case. An archive holds `Makefile` ("UPPER") and `makefile`
    ("lower"). Copying only `Makefile` gives a file `Makefile` that contains
    "lower", with no message: 7-Zip matches the name list without regard to
    case, extracts both, and the second replaces the first in the stage. With
    `-ssc` in the same run only the chosen entry is extracted; checked for a
    zip, a tar and a piped `.tar.gz`, and a folder name still brings its
    content. The behaviour is older than this task. `docs/archives.md` says
    such an item "is reported as not extracted"; that holds for `aux.c`, not
    here.
  - R12 - Medium, design: one item that cannot be moved into place drops every
    item after it. Five files are chosen and the user agrees to overwrite
    `f3.txt`, which is read-only (the same with a hard-linked file): `f1` and
    `f2` are copied, `f4` and `f5` are not, and the message is "Error
    extracting 5 items from five.zip (f3.txt: Access is denied)." The code
    follows the design text, which I wrote ("publishing stops"). In a large
    copy one such file loses everything after it although all of it is already
    extracted, and the count in the message is wrong. Before this task each
    item failed on its own. `CHANGELOG.md` and `docs/archives.md` say "none of
    its items is copied" for a failed run; this case copies some.
  - R13 - Low: message text. `_describe_error` lower-cases the first letter of
    the reason, which now can start with a file name (`Thing` is shown as
    "thing: ..."). Unpack alerts start with "[Errno 5]" (`str(error)`).
  - R14 - Low: `output.joinpath(*member.split('/'))` forgets the stage when a
    name part looks like a drive (`dir/c:victim.txt` gives `c:victim.txt`), so
    the comment "the source stays inside the stage" does not hold by
    construction. No harm found in the probes: the move fails. The drive check
    in `_Members.add` looks at the start of the name only, so `a:b.txt` at the
    top refuses the whole archive while `dir/a:b.txt` is listed.
  - R15 - Low: Unpack to... `fresh\mid\leaf` keeps the created `fresh\mid\`
    when the final rename fails.
  - Works as designed: the status bar shows "Reading big.tar.gz: N%" and then
    "Ready." in the application (listed as not run by the implementer); Delete
    and New folder inside an archive show the read-only message; F5 out of a
    compressed tar copies; a choice of links only copies nothing and reports
    the count; the R01 fix keeps the user's file.
  - Not checked: anything on a network share, a right-click on the context
    menu, and a visible window (the application ran off-screen).
- **Required Changes**:
  1. R10: give `OpenDirectory` an `onerror` that shows "Could not read from
     <path> (<reason>)" and returns nothing, in place of the `try` that cannot
     run. One place then covers archives and local folders on Enter. It needs
     R04 for a readable reason. Test: Enter on random bytes named `.zip` shows
     one alert and the pane stays.
  2. R04-R07 and R09, each with a regression test, as the Gemini 4 Neon review
     asks. R08 only once it is reproduced on a file that is not downloaded.
  3. R11: add `-ssc` where `Extract._extract_chosen` passes the name list.
     Test: `Makefile` chosen alone arrives with its own content.
  4. R12: the user decides. Recommended: keep moving the remaining items,
     collect the failed ones and raise one error after the loop that gives the
     count and names the first few ("1 of 5 items was not copied: f3.txt
     (Access is denied)"). No question per item. Unpack keeps stopping: its
     check before the run makes a failed rename there exceptional. Correct the
     sentence in `CHANGELOG.md` and `docs/archives.md` either way.
  5. R13-R15, optional: do not lower-case a reason that starts with a name;
     show `error.strerror` in Unpack alerts; build the staged path by joining
     strings; remove the folders Unpack created when it fails.
  6. Append the fixes and their validation to Final Implementation. Its
     sentence "Every acceptance criterion is met" does not hold for R10.

### Implementation Review - Claude Fable 5.2

- Date: 2026_11_23
- Agent: GitHub Copilot
- Model: Claude Fable 5.2
- Effort: Extra High
- Context Window: 1M

- **Verdict**: Changes requested.
- **Findings**: A follow-up to my review above. The user decided its two open
  points; the verdict is unchanged. Nothing was probed for this record.
  - R12: accepted as recommended. A copy of chosen items moves every item it
    can and reports the rest once. Unpack keeps stopping at the first failed
    rename. Step 5 of "Extraction" in the design now says so.
  - Damaged archives stay refused, as the code does now: an archive that
    7-Zip lists with an error does not open; one listed with a warning does.
    With R10 the refusal shows a message.
- **Required Changes**: Item 1 replaces item 4 of my review above; item 2 adds
  to it.
  1. R12, in `Extract._extract_chosen`: when moving an item fails, also when
     it was not extracted, keep its name and reason and go on with the next
     item. Cancel still stops between items. After the loop, announce the
     folders as today, then raise one `OSError` that gives the count and the
     first three names. The operation shows it like any failed task, so there
     is no new dialog and no question per item: "Error extracting 5 items from
     five.zip (1 of 5 items was not copied: f3.txt: Access is denied)."
     Test: five files, the third cannot be replaced; four arrive and the one
     message names `f3.txt`.
  2. Documentation. `docs/archives.md`: under "Copy Items Out", an item that
     cannot be moved is skipped and named in one message at the end; and an
     archive that cannot be read is refused with a message. `CHANGELOG.md`,
     under Changed: a damaged archive is refused with a message; before, it
     opened with the entries 7-Zip could list.

### Implementation Review - Code Review Agent

- Date: 2026_11_23
- Agent: GitHub Copilot (code-review agent)
- Model: Not exposed by host
- Effort: Not exposed by host
- Context Window: Not exposed by host

- **Verdict**: Changes requested.
- **Findings**: A review of the R04-R15 fixes, before they were recorded below.
  - R16 - High: `-ssc` covers a copy that chooses one of `Makefile` and
    `makefile`, not one that chooses both. On Windows 7-Zip writes both to one
    staged file. `Makefile` then arrives with the content of `makefile`, and
    only `makefile` is reported as not extracted.
  - Also reported: a copied folder that holds such a pair keeps one of them
    without a message. This behavior predates the task and is documented
    ("of `Makefile` and `makefile` one remains"); Unpack refuses such archives.
- **Required Changes**: Never publish chosen items whose names differ only by
  case. Optionally refuse a folder copy that holds such a pair.

## Final Implementation

- Date: 2026_11_23
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 1M

- **Final Summary**: Delivered as designed, with the deviations recorded above.
  Archives of every type are read-only: one message, from `read_only_message`,
  refuses every change before any provider runs. One member list per archive
  version, kept in memory, answers browsing and the checks before an operation.
  Unpack here, Unpack to..., a copy of chosen items and Pack each start one
  7-Zip run per archive, staged on the destination's volume and published by
  rename. A compressed tar runs as one pipe of two 7-Zip processes. The nine
  compressed tar suffixes open as `ctar://`, and archives with `./` names
  open. Symbolic links are skipped and reported. "Unpack to..." and "Unpack
  here" are in the file context menu. Cancel works in every stage, including
  while items are moved into place.
  Review fixes applied: R01, publishing uses `os.replace` only for a file member
  over an ordinary file (`_ordinary_file`), otherwise `os.rename`, which refuses.
  R02, `_members_of` closes the listing in a `finally`, ending 7-Zip and its
  reader thread. R03, `PackArchive` passes `-xr!<stage name>`. Each has a
  regression test: `test_a_folder_or_a_linked_file_is_never_replaced`,
  `test_a_listing_stopped_early_ends_7zip` (it hangs without the fix) and
  `test_an_archive_inside_a_chosen_folder_holds_no_staging_files`. Cancel during
  publishing is tested for a copy and for Unpack to... an existing folder.
  Every acceptance criterion is met; see the measurements below. The manual
  checks listed under "Not run" remain open.
- **Validation Results**:
  - Focused tests, with `build._environment()` and `QT_QPA_PLATFORM=offscreen`:
    `python -m unittest core.tests.fs.test_zip core.tests.commands.test_unpack_archive core.tests.commands.test___init__ core.tests.test_fileoperations fman_unittest.impl.test_shell_items fman_unittest.impl.plugins.test_mother_fs fman_unittest.test_everything fman_integrationtest.test_qt.UnpackArchiveIT fman_integrationtest.test_qt.ArchiveTransferIT fman_integrationtest.test_qt.WindowsCleanupIT.test_explorer_archive_items_paste_and_drop_as_copies fman_unittest.impl.plugins.test_context_menu`:
    485 tests OK; 3 skipped because creating symbolic links needs a Windows
    privilege.
  - Also run on the final code: `fman_unittest.test_listing`,
    `fman_integrationtest.impl.model.test___init__` and
    `fman_integrationtest.impl.plugins.test_plugin`, 72 tests. All pass except four
    `BatchFileRenamerPluginIT` tests that assert QuickBoard column widths
    (`109 not less than 61`). The same assertion fails on the last commit
    (`HEAD`) in an exported copy, so it is unrelated to this task.
  - `python -m fman_integrationtest.explorer_archive_smoke` with
    `QT_QPA_PLATFORM=windows`: all four checks pass (ZIP paste, ZIP drop,
    `.tar.gz` drop, archives unchanged and only the usual prompts).
  - `python build.py doc`: strict mode stops on five missing screenshots in
    `docs/basics.md`, which this task did not change. The images are generated
    by the Pages workflow and are not in the repository. The changed pages give
    no warnings.
  - CelebA acceptance, `CelebAAligned.zip` (202,600 files, 1.31 GiB), through
    the real application in a window: a fresh process per run, prompts answered
    automatically, commands dispatched from the Qt thread as a key press is, the
    task timed around `submit_task`. Run outside the VS Code workspace on the
    SATA SSD of the design's measurements. Inside the workspace (`target\`), VS
    Code's file watcher made 202,600 renames take 99 s instead of 19 s, and
    7-Zip alone took 65 s instead of 52 s.

| Operation (CelebA zip)          | Measured | Target | Files   |
| ------------------------------- | -------: | -----: | ------: |
| Unpack here                     |   55.8 s |   70 s | 202,600 |
| Unpack to..., new folder        |   56.5 s |   70 s | 202,600 |
| Unpack to..., existing folder   |   76.8 s |  100 s | 202,600 |
| Enter, Select all, F5           |   94.3 s |  120 s | 202,600 |

  - Phases of Unpack to... an existing folder: 7-Zip 52.1 s, renames 18.7 s,
    existence check 0.7 s. Enter took 2.2 s and Select all 0.08 s. The Unpack
    rows were measured before the review fixes, which change nothing those runs
    execute; the copy row and every Cancel run used the final code (the copy took
    94.7 s before the fixes).
  - Cancel in each stage. In every run no temporary folder remained and the
    archive was unchanged:

| Operation                       | Cancel during | Ends after | Result                       |
| ------------------------------- | ------------- | ---------: | ---------------------------- |
| Unpack here                     | Extraction    |      1.1 s | Nothing published            |
| Unpack to..., new folder        | Extraction    |      0.9 s | Nothing published            |
| Unpack to..., existing folder   | Publishing    |      9.4 s | 48 entries kept, complete    |
| Enter, Select all, F5           | Gathering     |     0.00 s | Nothing copied               |
| Enter, Select all, F5           | Extraction    |      0.9 s | Nothing copied               |
| Enter, Select all, F5           | Publishing    |      9.0 s | 18 files kept, complete      |

  - The same 202,600 files as a `.tar.gz` (gzip level 1, 1.21 GiB), same
    method: Unpack here without browsing 64.6 s (two decompressions), Unpack
    to... an existing folder 87.2 s, Enter 13.1 s and the copy 104.0 s
    (117.4 s in total). Cancel during the copy's extraction ended both 7-Zip
    processes in 1.2 s and copied nothing. All runs delivered 202,600 files.
  - Names that Windows changes, probed on a small zip: copying a folder gives
    `_aux.c` and one of `Makefile`/`makefile`; copying `aux.c` alone fails with
    "Not extracted: aux.c" and leaves nothing. Documented.
  - Not run: the full `python build.py test` suite, freeze and package; a
    manual right-click on an archive (the menu entries are tested through the
    YAML file and the commands); paste from Explorer for `.tar.zst`; restarting
    with a pane inside a compressed tar; and the status bar progress in a
    window (unit-tested through `_StatusProgress` and a fake 7-Zip).

### Review Fixes R04-R16 - Claude Opus 5.5

- Date: 2026_11_23
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 1M

- **Final Summary**: Fixes for the Gemini 4 Neon, Claude Fable 5.2 and code
  review findings, as the user approved. This record corrects the sentence
  "Every acceptance criterion is met" above. It did not hold for R10, which is
  now fixed. Code: [zip.py](../src/main/resources/base/Plugins/Core/core/fs/zip.py)
  and [commands/\_\_init\_\_.py](../src/main/resources/base/Plugins/Core/core/commands/__init__.py).
  - R04: `_7zip.__exit__` joins output lines with `'\n'`. The direct listing
    runs without `-ba`, because only its header holds the reason for a damaged
    archive. `_reason_in` takes 7-Zip's first reason, without the archive's
    path. Messages: "Cannot read truncated.zip: Unexpected end of archive",
    "Cannot read random.zip: Cannot open the file as [zip] archive", and
    "Two chosen items have the same name: f.txt".
  - R05: `_Members.records` counts every listed record, also `.`. A compressed
    tar of an empty folder opens empty.
  - R06: `_Members.links` is a set. A later entry of the same path, or an
    implied folder, removes the link, and a link stored twice counts once.
  - R07: in an archive that stores names both with and without `./`, a copy
    passes only file names. A chosen folder is refused with a message, and
    choosing every top-level item passes no list.
  - R08: `_ordinary_file` refuses only name surrogates (`0x20000000`: symbolic
    links, junctions) and files with several hard links. A cloud placeholder
    can be replaced.
  - R09: Unpack finds the existing folder above the destination before it
    reads the archive. An existing file on the way is refused ("Not a folder:
    ..."). The top folder it creates is announced, so the pane showing its
    parent updates.
  - R10: `OpenDirectory` passes `_report_unreadable_folder` as `onerror`. It
    shows "Could not read from <path> (<reason>)" from a short-lived thread, so
    the Qt thread that reports a failed scan is not held by a dialog. It then
    returns the same URL, so the pane stays. A synchronous failure is caught
    after the alert. Navigation requests (`current_request`) behave as before.
    This covers archives and local folders.
  - R11: `-ssc` with the name list. R16: chosen items whose names differ only by
    case are skipped as "another chosen item differs only by case".
  - R12: as decided, a copy moves every item it can. One `OSError` then gives
    the count and the first three names, for example "1 of 5 items was not
    copied: f3.txt: Access is denied". Unpack still stops at the first failure.
  - R13: Unpack, Pack and Enter alerts show `strerror` (`_reason`), without
    "[Errno N]".
  - R14: the staged source path is joined as text. Only a name that starts with
    `X:/` or is `X:` counts as outside the root, so `a:b.txt` lists at any
    depth. Copying it reports "not extracted".
  - R15: if Unpack to... fails, the folders it created are removed again, from
    the deepest up.
  - Refinements: `PackArchive` refuses a missing destination folder before it
    creates a stage. The type check of a compressed tar stops at the entry list
    and closes it. `_find_extension_start` knows `.tar.bz2` and `.tar.zst`.
  - Added: an encrypted archive or item reports "The archive needs a password".
    Without a password prompt, 7-Zip reads empty input, and without a reason
    the message said only "Cannot read x.7z.".
- **Deviations**:
  - R07: the review suggested inheriting each folder's prefix. That could
    silently leave out entries stored in the other form, so a chosen folder is
    refused instead.
  - R09: `_unpack` still calls `fman.fs.notify_file_*` rather than
    `self._fman_fs`. In production both are the same object, and the Unpack
    tests patch `fman.fs`. The difference is consistency only.
  - R13: `_describe_error` still lowercases the first letter. The new copy
    message starts with a count, so no name is changed.
  - The `process.kill()` guard in `_starts_with_zero_block` is not added. On
    Windows, `Popen.kill` already ignores a process that has exited.
  - R16's second point is left as documented: a copied folder keeps one of two
    names that differ only by case. The user decides whether a copy should
    refuse it, as Unpack does.
- **Tests**:
  - `test_zip.py`: a damaged archive's reason (truncated, random bytes,
    encrypted headers); a later entry replaces a link; a colon in a name at any
    depth; a `./`-only tar opens empty; the type check reads only the header;
    Pack's duplicate and missing-folder messages; `Makefile`/`makefile` alone
    and together; a mixed-prefix archive; a skipped item named once (one and
    four of five); a drive-like name part; `_ordinary_file`'s reparse tags.
  - `test_unpack_archive.py`: a file on the way refuses before reading; created
    folders are removed; the top created folder is announced; `_unpack_error_text`
    without "[Errno]".
  - `test___init__.py`: `OpenDirectoryTest` (asynchronous and synchronous
    failure, one alert) and the two extensions.
  - `test_qt.py`: `OpenDamagedArchiveIT`, Enter through a real pane.
- **Validation Results**:
  - Focused tests, with `build._environment()` and `QT_QPA_PLATFORM=offscreen`:
    `python -m unittest core.tests.fs.test_zip core.tests.commands.test_unpack_archive core.tests.commands.test___init__ core.tests.test_fileoperations fman_unittest.impl.test_shell_items fman_unittest.impl.plugins.test_mother_fs fman_unittest.test_everything fman_integrationtest.test_qt.UnpackArchiveIT fman_integrationtest.test_qt.OpenDamagedArchiveIT fman_integrationtest.test_qt.ArchiveTransferIT fman_integrationtest.test_qt.WindowsCleanupIT.test_explorer_archive_items_paste_and_drop_as_copies fman_unittest.impl.plugins.test_context_menu`:
    499 tests OK; 3 skipped (symbolic links need a Windows privilege).
  - `python -m fman_integrationtest.explorer_archive_smoke` with
    `QT_QPA_PLATFORM=windows`: all four checks pass.
  - The real application, off-screen, with isolated settings (a scratch
    script outside the repository): Enter on Fable's four cases (random bytes
    named `.zip`, a truncated `.zip`, a `.tar.gz` with `../escape.txt`, and
    gzipped text named `.tar.gz`). Each showed one alert with the reason, and
    the pane stayed in its folder.
  - `python build.py doc`: only the five missing `docs/basics.md` screenshots,
    as before. The changed pages give no warnings.
  - The CelebA measurements were not repeated. Per item, the hot path gained
    one set lookup, and the stage path is now joined as text. The listing gained
    about 20 header lines.
