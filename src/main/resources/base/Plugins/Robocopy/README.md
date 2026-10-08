# Robocopy

A fast native alternative for copying or moving selected files and folders through
Windows Robocopy. This bundled, public-API plug-in leaves normal **F5/F6** unchanged.
Performance depends on the workload; ordinary F6 can be much faster for same-volume
moves because it can rename instead of copying and deleting.

## Availability

Robocopy is included with the application and loaded automatically, like the other
bundled feature plug-ins. No manual installation is required. It remains a separate
Python package using public pane, Task and UI-owner APIs, not Core internals.
Windows supplies `robocopy.exe`; no package installation, elevation or download is needed.

Builds created before this packaging change need rebuilding. After starting the
updated application, open Command Center with **Ctrl+Shift+P** and search for
**Copy with robocopy** or **Move with robocopy**. There are no default right-click
menu entries or shortcuts.

If you installed an earlier standalone copy, remove its `Robocopy` directory from
`UserSettings/Plugins/Third-party` or `UserSettings/Plugins/User` while the application
is closed to avoid loading two copies. Keep your overrides in `Plugins/User/Settings`
and transfer logs in `Local/Robocopy/Logs`; those locations are unchanged.

## Copy And Move

1. Select files or folders in the active pane. With no selection, the highlighted
   entry is used.
2. Open Command Center with **Ctrl+Shift+P** and choose **Copy with robocopy** or
   **Move with robocopy**.
3. Accept the opposite pane's destination, or type an absolute drive/UNC folder
   path. The first row uses the exact typed path. Enter starts the operation;
   Escape cancels without creating transfer files or launching a process.

For example, selecting `notes.txt`, `budget.csv` and `Photos`, then choosing
`D:\Backup`, produces `D:\Backup\notes.txt`, `D:\Backup\budget.csv` and
`D:\Backup\Photos\...`, including empty subfolders. Unselected source siblings
are not included. New destination directories are created by Robocopy.

Only one Robocopy invocation is allowed at a time, including its wizard and
cleanup. Navigation does not retarget a captured operation. Closing its source
pane or unloading the plug-in cancels it. Relevant live panes reload normally at
the end; continuous intermediate pane updates are not promised.

Command IDs are `copy_with_robocopy` and `move_with_robocopy`. No shortcuts are
assigned by default.

## Native Policies

**These commands use Robocopy's policies, not Core's staged-copy safeguards.**

- Existing destination folders merge. Changed files can replace newer destination
  files without another conflict dialog. Unrelated destination entries are not purged.
- Matching size/time metadata can cause skips without comparing contents. Move can
  leave those skipped sources in place, even when different bytes exist at the target.
- `/MOV` moves loose files; `/MOVE` applies only to each selected folder, never to
  the pane folder merely because some of its files were selected. The plug-in never
  deletes sources based on an aggregate exit code.
- Selected source links/junctions and linked source roots are refused. Nested source
  links are excluded using `/XJD /XJF`. This is **not destination protection**:
  destination junctions/symlinks can redirect writes outside the displayed target,
  and overwriting a hard-linked destination can change its other aliases.
- Cancellation or failure can leave partial destination files and a partially moved
  selection. Completed changes are retained. There is no staging, content verification,
  rollback, undo, or automatic retry of the whole selection.
- Data, attributes and timestamps use `/COPY:DAT`, including native alternate-stream
  behavior. Selected folders use `/E /DCOPY:DAT`; loose files use `/NODCOPY` to avoid
  applying the pane folder's attributes to the destination. ACL/owner/audit copying
  and elevation are not enabled. Do not edit participating files during a Move.

## Settings

Defaults are in [Robocopy.json](Robocopy.json). Put only your overrides in
`UserSettings/Plugins/User/Settings/Robocopy (Windows).json`, then reload plug-ins.
Settings are captured when a command starts; changing them does not alter an active
transfer. Unknown options and invalid types/ranges are rejected.

| Setting | Default | Effect |
| --- | --- | --- |
| `threads` | `8` | Integer 1-32; `/MT`. More threads are not always faster. |
| `retries` | `1` | Integer 0-10; retries per failed native operation. |
| `retry_wait_seconds` | `1` | Integer 0-30; wait between retries. |
| `restartable` | `false` | `/Z`; useful for interrupted network transfers, with overhead. No automatic queue/resume UI. |
| `unbuffered` | `false` | `/J`; generally intended for large-file I/O. |
| `log_enabled` | `false` | Write one Unicode log for the transfer. |
| `open_log_on_finish` | `false` | Open the log externally after cleanup; requires logging. |
| `log_retention_count` | `20` | Integer 1-100; current log plus newest recognized completed logs. |

No arbitrary switches, executable override, mirroring, purge, backup mode, monitoring
or Registry settings are exposed. Jobs run sequentially; `/MT` supplies native
parallelism. Loose filenames are split at a 24,000 UTF-16-unit command limit.
Preparation streams the immediate source folder once to check primary names,
short aliases and ambiguous case matches; it does not scan descendants. Memory
for name validation scales with the selection, not the whole folder. Shared path
ancestry is resolved once; source identities are still checked per selected root.
Each batch can re-enumerate the source/destination folders, so many batches add cost.

## Progress And Results

Preparation and a single job (including an entire folder) use a **busy indicator**,
not actual copy progress or a completion percentage. Multiple jobs are equally weighted
and labelled **approximate**: a large directory and a small file batch each count as
one job. This is not byte progress. The dialog shows Copying/Moving, elapsed time
and the selected file count or folder name. Long folder names are shortened for
display. Raw Robocopy columns are not shown in the progress label.

Cancel stops the owned process and waits for its output reader to finish. Cleanup
runs off the UI thread. After process exit, the reader drains the bytes already
available and stops even if another process retained a pipe writer. Blocked
Windows/network calls can still delay stopping.

Native exits **0-7** mean no reported copy failure, not that every entry transferred:
`0` reports no copied files; bit `1` means files copied, `2` means extra destination
entries, and `4` means mismatches. **8 or higher** is failure and stops later jobs.
Logs retain each job's code. File counts and content verification are unavailable.
Extra entries alone use a status message; mismatches, failures and remaining Move
roots still raise an alert. A late Cancel preserves the finished job's exit code.
The status bar receives one concise line; detailed reports and log paths stay in
alerts and the optional transfer log, rather than expanding the status bar.

Move also reports checked selected roots as absent, remaining or uncheckable, with
at most ten examples. A remaining folder represents a remaining subtree, not a file
count. Cancellation explicitly reports roots left unchecked; disappearance alone does not prove
copy success under concurrent changes. Exit 0 must not be read as "all moved".

## Transfer Logs

Logging and automatic opening are **disabled by default**. With those defaults,
no log file is created or opened. To save and open one, set both options in
`UserSettings/Plugins/User/Settings/Robocopy (Windows).json` and reload plug-ins:

```json
{
  "log_enabled": true,
  "open_log_on_finish": true,
  "log_retention_count": 20
}
```

Logs live in `UserSettings/Local/Robocopy/Logs` (under the configured portable data
directory). One generated UTF-16 text file contains all jobs, arguments, native
output, exit codes and the final outcome. Paths and filenames are intentionally
included: inspect the log before sharing it.

With automatic opening enabled, the `.txt` association opens the log once after
completion, failure or user cancellation, after child/reader cleanup, progress
closure and lease release. It does not open after wizard cancellation, pane closure
or unload. A viewer error leaves the log available and does not retry transfers.

Logging off performs no log-directory work. Creation failure stops before the first
transfer. A later logging failure stops subsequent jobs without undoing completed
work. Cancellation, disk-full or forced exit can leave incomplete output. Footer
and retention errors are reported separately. Generated log paths must not overlap
the selected source or destination trees or use symbolic-link/junction paths.
Non-redirecting cloud-placeholder tags alone do not prevent logging; actual
OneDrive/offline hydration still needs environment-specific validation.

Retention removes only recognized completed regular logs, keeping the current one;
unfinished, reparse and unrelated files are left alone. The count does not bound bytes or
unfinished files. Large transfers can produce large logs. No idle cleanup runs.

## Supported Locations And Limits

Use ordinary filesystem entries and absolute local-drive or UNC destinations.
Virtual/archive/process locations, relative paths, wildcards, device namespaces,
alternate-stream input paths, self-transfers and directory-into-itself transfers
are refused. Source identities are rechecked before each job; this is not a lock
against concurrent filesystem changes.

Loose files in case-sensitive source directories and selected 8.3 aliases are
refused, including aliases without a tilde. When a filesystem does not implement
the per-directory case query, fresh primary/alternate-name validation still rejects
ambiguous selection; unsupported does not mean proven case-insensitive.
Loose filenames beginning with `-` are refused because Robocopy treats them as
switches. Hyphen-named folders are supported through full-path folder jobs.
Spaces, Unicode, extensionless names, brackets and `@` prefixes are covered by tests.

Local Windows tests cover native transfers, loopback UNC Copy/Move, junctions, hard links, streams,
case-sensitive/8.3 refusal, cancellation and process ownership. Symlink traversal
tests require privileges unavailable in the development account. Other UNC servers/reconnect,
second-volume Move, cloud/offline hydration, very deep paths, non-English Windows,
Windows-version coverage and frozen-host installation still need environment-specific
validation. Sparse/cloud reparse attributes alone are not treated as symbolic links;
native access may hydrate placeholders. No universal placeholder or speed guarantee
is implied.