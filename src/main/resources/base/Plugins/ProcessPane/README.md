# Process Pane

Open the Command Center with **Ctrl+Shift+P** and run **Show OS' processes**.
The active pane displays a flat **Name / PID** list. Type to filter by name,
click a column to sort, and press **Ctrl+R** to refresh.

To end a process:

1. Select exactly one row, or leave selection empty and use the cursor row.
2. Press **F8**, or run **End process** from the Command Center.
3. Confirm the prompt, which defaults to **No**.

This is forced termination, not a request to save files and close gracefully.
Unsaved data can be lost. Child processes are not ended automatically.
The status says **Termination requested** for five seconds; it does not wait for
exit. The active process pane refreshes once afterward. Other panes refresh
manually.

## Restrictions

- Uses current Windows permissions only. No elevation prompts or security bypass.
- Denied names appear as `Unavailable`; entries without a verified identity cannot
  be ended. System, critical processes, and the file manager itself are refused.
- Access denied can mean insufficient permissions or a process already exiting;
  refresh the list before retrying.
- Old rows cannot target a different process that has reused the same PID.
- F8 keeps its ordinary delete behavior in file panes. Shift+Delete and the
  palette's Delete entry use the same process confirmation in a process pane.
- No child navigation, live monitoring, extra columns, batch termination, or
  file copy/move/create/rename operations. Enter does not launch or end a process.
- Filtering uses a name-bearing URL; `/`, `\`, `~` and control characters in
  names are sanitized. The displayed Name retains the original text.

## Find Blocking Processes

Right-click one file or folder in a local pane and choose
**Find blocking processes**, or run **Find blocking processes** from the
Command Center. It lists processes that keep the item open.
These are possible users, not proven blockers: sharing permissions may still
allow deleting, moving or renaming the item.

- A table shows Process, PID, Item and Program. Ctrl+Enter or a double-click
  on Item or Program goes to that path. Escape closes it.
- Detects open files and folders, running programs, loaded DLLs and folders
  used as a working folder.
- For a folder, the folder and everything inside it are checked, up to 100,000
  items. Links and junctions are not followed. Cancel is checked during scanning,
  name lookup and result preparation; an ongoing Windows call must return first.
- Results retain at most 10,000 process/item pairs with bounded text. Long-path
  or larger results are marked truncated; paths in retained rows stay navigable.
- Runs with regular user rights; it never asks for administrator rights.
  Windows reports the process IDs for each item, so no process has to be
  opened to find them. Names of protected processes show as `Unavailable`.
- Items that cannot be opened (for example, no list permission) are counted
  as not checked. Network paths depend on the server and may fail.
- It only reports. Close the item in that program, or end the process from the
  process pane.

## Plug-In Installation

ProcessPane uses public `fman` plug-in APIs and owns all process-specific code.
It is bundled with RoyiFileManager but has an ordinary plug-in folder layout.
Do not install it alongside upstream ProcessFS: both register `process://`.

It requires Windows 8.1 or newer and the host's compatible **pywin32** package.
RoyiFileManager already declares pywin32; no psutil dependency is required.
For another compatible host, place this folder under its user plug-in directory
and ensure that host supplies `win32process` for its Python version/architecture.
Copying a plug-in cannot add an incompatible native extension to a frozen host.

The native enumerator loads only when the process pane is used, and the lock
finder only when its command runs. The unused or
disabled plug-in performs no process scans, polling, background jobs or Registry
writes. It stores no process metadata on disk.