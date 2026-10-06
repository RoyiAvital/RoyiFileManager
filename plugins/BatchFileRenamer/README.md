# Batch File Renamer

Copy this folder to `UserSettings/Plugins/Third-party/BatchFileRenamer`, then
reload plug-ins or restart. This is an independent plug-in, not bundled host code.
It requires a host with the mapped QuickBoard API and `fman.fs.rename_no_replace`.
Version numbers are compared numerically (minimum source API version 0.14.0);
older released 0.14.0 hosts lacking these features are rejected.

Select regular files in one local-drive folder and run **Batch File Renamer**
from Command Center. There is no default shortcut. With no selection, the cursor
file is used. The initial `{name}{ext}` leaves names unchanged.
Links, junctions and files with multiple hard links are rejected during loading,
before the preview opens: select actual files instead. Sparse files and cloud
placeholders, including files in OneDrive/Dropbox folders, are allowed.
Up to 25,000 candidates are accepted, subject to QuickBoard's 16 MiB preview
budget. If the complete preview cannot fit, reduce the template or candidate set;
the command does not silently truncate the preview or apply a partial set.

Variables: `{current_date}`, `{file_date}` (modified time), `{index}` (visible
zero-based order), `{file_index}` (captured natural position among all regular
folder files, including hidden/unselected ones), `{name}` and `{ext}` (with dot).
Folder numbering ignores link counts, so unselected hard-linked names still
consume an index. Selected files are checked separately and hard links refused.

Examples:

```text
{name}{ext}
Trip_{(index + 1):03d}{ext}
{file_date:%Y%m%d}_{(index + 5):03d}{ext}
{(file_index + 1):03d}_{name}{ext}
```

Only addition of a positive integer is allowed. No Python expressions, calls,
subtraction, conversions or nested fields. Date directives: `%Y`, `%y`, `%m`,
`%d`, `%H`, `%M`, `%S`, `%%`; the default is `%Y-%m-%d`. Index widths are 1-32;
padding is a minimum, so `02d` does not truncate 149. Use `{{`/`}}` for braces.

Sorting/filtering source columns changes the visible index and operation scope.
Only rows passing filters are renamed, including rows scrolled out of view.
Filtered-out and unselected files stay untouched and still occupy their names.
Generated Index, New Name and Valid Name cannot filter/sort themselves.
Check/cross hints are advisory; fresh preflight and native no-overwrite checks
remain mandatory. Invalid acceptance stops, without reopening a broader batch.
The right-hand footer reports ready files or `Rename blocked` with the problem
count. Text edits regenerate after 100 ms of keyboard inactivity; Enter flushes
that delay. This message is caller feedback, not a replacement for validation.

Escape makes no changes. Execution is cancellable between files, not atomic:
successful renames remain completed after cancellation/error. The results show
excluded, unchanged, renamed, failed and unattempted files; notification failures
are reported separately from committed renames. No automatic rollback or undo.
Renaming uses the normal progress dialog and cancellation. Large result reports
are split into pages of at most 10,000 rows: Enter advances, Escape closes reporting.

V1 excludes folders, UNC/archive sources, links/junctions, case-only changes,
swaps and occupied-target chains. The preview's conservative case comparison
and plug-in natural filename key need not exactly match NTFS or the host's Name
sort for unusual Unicode names. Invalid candidate names remain complete within
the preview budget; exceeding the budget blocks approval. No settings or templates
are saved and no work runs until the command is invoked.