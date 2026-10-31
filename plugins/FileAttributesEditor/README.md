# File Attributes Editor

Included automatically in newly frozen application builds. It is an independent
public-API plug-in, not part of Core's internal implementation.

For source runs, copy this folder to
`UserSettings/Plugins/Third-party/FileAttributesEditor`, then reload plug-ins or
restart. It requires a host with `fman.ui.show_quick_check_list`.

Select files or folders in a local-drive pane (including mapped network drives)
and choose **Edit attributes...** from the file context menu, or run
**Edit attributes** from Command Center. There is no default shortcut.
With no selection, the item under the cursor is used.

The list shows Read-only, Hidden, System, Archive, Not content indexed and
Temporary. A mixed box means the chosen items differ. Press Space to cycle a
state; mixed is reachable only where it started.

- Enter applies the changed attributes to the chosen items.
- Shift+Enter, offered when a folder is chosen, applies them recursively to the
  folders' contents too. Links and junctions inside are skipped, never followed.
- Esc cancels. If nothing changed, nothing is written, whichever key was used.

Only the attributes you changed are written; all other bits stay as they were.
To push an attribute that the chosen folders already have to items inside that
lack it, set it off and then on in two runs, or choose those items directly.

Attributes are read once when the command starts and treated as static. Changes
made by other programs during the run are overwritten with the values read plus
your changes. Temporary applies to files only. Windows stores Read-only on
folders but does not enforce it. Compressed, Encrypted and UNC paths are not
supported. Failures do not stop the run; they are listed at the end.
