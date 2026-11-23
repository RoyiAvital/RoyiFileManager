# Advanced Notes

These notes cover behavior that matters during unusual or failed operations.

## File Transfers

Local Copy (`F5`) and Move (`F6`) prepare the whole transfer and ask about known
filename conflicts before changing files. Large selections can take time to
prepare; you can cancel while waiting.

After preparation, items are processed in order. Cancelling before transfers
start leaves files unchanged. Cancelling later does not undo completed copies
or moves.
Missing destination folders are created only after preparation succeeds.

If an item fails, choose **Yes** to skip it, **Yes to all** to skip later
errors without asking, or **Abort**. After **Yes to all**, one summary lists the
skipped errors at the end.

### Local Copies

- A copy is completed in temporary space beside the destination before it is
  published. Keep enough free space for the new file.
- Overwriting links and merging folders through directory links are refused.
- If a Windows replacement error reports a recovery file, keep it until you
  have checked the destination.

### Local Moves

- Within the same drive, Move normally changes the item's location without
  copying its contents.
- Between drives, each file is copied successfully before its original is
  deleted. If copying fails, that original stays in place.

### Archives

- Archives are read-only. To change one, unpack it, change the files and pack
  them into a new archive.
- A copy out of an archive extracts all chosen items in one 7-Zip run into
  temporary space beside the destination, then moves them into place. Keep
  enough free space for the extracted items. A failed or canceled run copies
  nothing; Cancel while items are moved into place keeps those already moved.
  An item that cannot be moved into place is skipped and named at the end.
- Unpack and Pack only create. An existing destination is refused.

See the [archive guide](archives.md), [file-system link behavior](file-system-operations.md)
and the Core plug-in's detailed
[local transfer](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/Core/README.md#local-transfers)
and [archive transfer](https://github.com/RoyiAvital/RoyiFileManager/blob/main/src/main/resources/base/Plugins/Core/README.md#archive-transfers)
documentation.
