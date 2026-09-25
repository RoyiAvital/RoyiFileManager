# File System Links

NTFS and ReFS support hard links, directory junctions and symbolic links. A
Windows `.lnk` shortcut is an ordinary file, not a file system link.

## Link Types

| Property | Hard link | Junction | Symbolic link |
| --- | --- | --- | --- |
| Essence | Another name for one file | Directory redirection | Stored path to a target |
| Can represent | File | Directory | File or directory |
| Target scope | Same volume | Local volumes | Local volumes or UNC paths |
| Relative target | Not applicable | No | Yes |
| Can become broken | No, while a name remains | Yes | Yes |
| Delete the selected link | Removes one name | Removes junction only | Removes symbolic link only |
| NTFS support | Yes | Yes | Yes |
| ReFS support | Yes | Yes | Yes |
| Creation privilege | Normal directory permissions | Normal directory permissions | **Create symbolic links** right, or Developer Mode with supported applications |

Hard-linked names are peers, not a link and an original. Changes through one name
are visible through every name. Windows reclaims the data after the last name and
open handle are gone.

### Creation

| Type | Command Prompt |
| --- | --- |
| Hard link | `mklink /H LinkName TargetFile` |
| Junction | `mklink /J LinkName TargetDirectory` |
| File symbolic link | `mklink LinkName TargetFile` |
| Directory symbolic link | `mklink /D LinkName TargetDirectory` |

All operations require normal directory permissions. Symbolic-link creation also
normally requires the **Create symbolic links** right; Developer Mode allows
supported applications to request unprivileged creation.

Reparse points can represent other features too, including volume mount points
and cloud placeholders. A reparse point is not automatically a junction or
symbolic link.

## Windows File Explorer Behavior

These are File Explorer defaults. Permissions, unavailable targets, cloud
providers and other reparse types can change or refuse an operation.

| Operation in File Explorer | Hard link | Junction | Symbolic link |
| --- | --- | --- | --- |
| Open or edit | Opens the shared file | Opens the target directory | Opens the target file or directory |
| Copy and paste | Creates an independent file copy | Copies the target tree as a normal directory | Copies target data as a normal file or directory |
| Delete or Shift+Delete | Removes the selected name | Removes the junction, not its target | Removes the symbolic link, not its target |
| Move on the same volume | Renames or relocates the selected name | Moves the junction object | Moves the symbolic link object |
| Move to another volume | Copies an independent file, then removes the source name | Copies the target tree, then removes the source junction | Copies target data, then removes the source symbolic link |

Copying a directory link can copy much more data than the link itself occupies.

### Relative Symbolic Links

| Operation | Result |
| --- | --- |
| Copy and paste | Explorer follows the link and creates an ordinary copy of the target data. |
| Same-volume move | Explorer moves the link object and preserves its target text. The new location can change what the relative path resolves to or leave it broken. |
| Cross-volume move | Explorer performs copy followed by delete, so the destination is normally an ordinary copy of the target data. |

`robocopy` has options to preserve links instead of following them; its behavior
is not the File Explorer default.

### Chained Links

Windows resolves each junction or symbolic link in sequence. Each relative
symbolic link is resolved from its own containing directory.

| Operation | File Explorer behavior |
| --- | --- |
| Open or edit | Follows the chain to the final target. |
| Copy and paste | Follows the chain and copies the final target data as an ordinary file or directory. |
| Chain mixing absolute and relative links | Resolves each relative target from the directory containing that link; an absolute target starts the next hop from its absolute path. |
| Delete the outer link | Removes only that link; inner links and the final target remain. |
| Same-volume move of a relative link | Moves only that link and does not rewrite its target text, so that hop can resolve elsewhere or break. |
| Broken chain, loop or excessive depth | Fails instead of repairing or rewriting the chain. |

For example, `C:\Links\Outer` -> `..\Shared\Inner` resolves first to
`C:\Shared\Inner`. If `Inner` -> `..\Data\File.txt`, the final target is
`C:\Data\File.txt`, because the second relative path starts from `C:\Shared`.

Hard links do not form chains; their names identify the same file directly.
Windows permits at most 63 reparse points on one path, reduced in some cases such
as fully qualified targets.

## Microsoft References

- [Hard Links and Junctions](https://learn.microsoft.com/en-us/windows/win32/fileio/hard-links-and-junctions).
- [Symbolic Links](https://learn.microsoft.com/en-us/windows/win32/fileio/symbolic-links).
- [Symbolic Link Effects on File System Functions](https://learn.microsoft.com/en-us/windows/win32/fileio/symbolic-link-effects-on-file-systems-functions).
- [Reparse Points](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points)
- [ReFS Feature Comparison](https://learn.microsoft.com/en-us/windows-server/storage/refs/refs-overview#feature-comparison).

## Royi File Manager Behavior

Yes, {{ app_name }} handles several cases differently from File Explorer. It
refuses ambiguous operations rather than risk changing a link target or alias.

### Differences from File Explorer

| Case | File Explorer | {{ app_name }} |
| --- | --- | --- |
| Copy a file symbolic link to an unused name | Copies target data into a regular file | Recreates the symbolic link with the same stored target |
| Copy over a symbolic link | May write through the link to its target | Refuses; link and target are retained |
| Copy over a known hard-linked file | Overwrites the shared file; aliases see the new data | Refuses; other aliases are protected |
| Merge through a source or destination directory link | Follows and merges the target tree | Refuses before traversing the link |
| Move a symbolic link or junction to another volume | Copies target data, then removes the source link | Refuses and retains the source link |

### What a Refusal Does

| Refusal point | Cases | Result for the batch |
| --- | --- | --- |
| While gathering | Directory-link merge or cross-volume link move | Stops the whole selected batch before any queued copy or move runs. |
| While executing an item | Symbolic-link or known hard-link overwrite | The item fails. If later items remain, choose whether to continue or abort. |

Completed items are retained; a later refusal does not roll them back.

### Other Operations

| Operation | {{ app_name }} behavior |
| --- | --- |
| Open a directory link | Navigates into its target |
| Copy a directory link to an unused name | Follows the target and creates a normal directory tree, like Explorer |
| Copy a hard link to an unused name | Creates an independent regular file, like Explorer |
| Same-volume move | Moves the selected name or link object without rewriting a relative target |
| Permanent Delete | Removes the selected name, symbolic link or junction, not another target path |
| Move to Recycle Bin | Delegates to Windows Recycle Bin handling |
| Create symbolic link | ++shift+f5++ creates an absolute link in the other local pane; existing destinations are retained |

Symbolic-link creation uses the current Windows permissions. {{ app_name }} does
not elevate or change system policy.

Archive operations do not promise to preserve file system links. Moving local
entries into an archive is disabled; use Copy, verify the archive, and remove the
source explicitly. Directory Size does not follow links, and Find Files leaves
**Follow links** off by default.