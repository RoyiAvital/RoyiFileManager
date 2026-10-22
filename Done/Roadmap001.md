# Tweaks and Tricks

Status: Implemented the approved scope on 2026-10-22. Only rows marked
**Implement** were included. Pass/Deferred decisions and historical review records
remain unchanged. Pattern selection has its own canonical task below.

Opus's implementation findings R1-R4 and input/performance recommendations are
addressed in [Implementation Review Resolutions](#implementation-review-resolutions).
Review 2 findings N1/N2 are addressed in
[Implementation Review 2 Resolutions](#implementation-review-2-resolutions).

| #   | Feature                         | Why it fits                                                                  | Size          | Decision by Royi |
| --- | ------------------------------- | ---------------------------------------------------------------------------- | ------------- | ---------------- |
| 1   | Swap pane locations             | Exchange the two folder locations without moving files or pane objects.      | Very small    | Implement        |
| 2   | Select / deselect by pattern    | Preview selection live in the Filter Bar UI without hiding entries.          | Small, medium | Implement        |
| 3   | Bind Invert selection           | Bind the existing command to keypad `*` using Qt's `Num+*` notation.         | Very small    | Implement        |
| 4   | Show in Explorer with selection | `F10` opens the folder but does not highlight the file.                      | Very small    | Pass             |
| 5   | Copy names of several files     | `Shift+F11` handles one item; `F11` already copies many paths.               | Very small    | Implement        |
| 6   | Free space in the status bar    | Reuse the listing scope; show free space for local NTFS/ReFS. Implemented.   | Small         | Implement        |
| 7   | Go to link target               | Command Center action; inspect and resolve the highlighted link on demand.   | Small         | Implement        |
| 8   | Sort by extension               | Only Name, Size and Modified exist.                                          | Medium        | Deferred         |
| 9   | Select the same extension       | Mark visible files like the cursor file without typing a pattern.            | Very small    | Implement        |
| 10  | New folder and enter            | Create a folder and immediately navigate into it.                            | Small         | Pass             |
| 11  | Command Center synonyms         | Find Favorites with "Bookmarks" or Unpack archive with "Extract".            | Very small    | Implement        |
| 12  | Optional ISO date display       | Show consistent, unambiguous local dates and 24-hour time in pane columns.   | Small         | Deferred         |
| 13  | Go to clipboard path            | Open a copied folder path or reveal a copied file using existing navigation. | Very small    | Implement        |
| 14  | Duplicate a file                | Suggest an available numbered copy name for one file or folder.              | Very small    | Implement        |
| 15  | Link indicators in file rows    | Visual hints for symlinks/junctions; independent of target navigation.       | Medium        | Deferred         |
| 16  | Public location metadata API    | Thin public access hint from the current URL and existing listing scope.     | Small         | Implement        |

Suggested order among items marked **Implement**: 11, 13, 14, 7, 1 and 3,
then 5, 9, 16 and 2. Item 6 is already implemented.
Items 2, 3 and 9 share selection behavior, but their approval is independent;
implementing item 3 does not require adding items 2 or 9. Pass and Deferred
decisions remain unchanged.

## Task

Deliver the approved navigation, selection, clipboard, discovery and location-hint
improvements without changing unrelated file-operation policies.

## Scope

Implemented items 1, 2, 3, 5, 6, 7, 9, 11, 13, 14 and 16. Items 4 and 10 remain
Pass; items 8, 12 and 15 remain Deferred. Item 6's historical record said completed,
but its runtime code was absent from this checkout; the approved simple design
was supplied and tested with the shared item 16 predicate.

## Design

The numbered sections are the canonical designs, except item 2, which links to
its dedicated task. Core reuses existing navigation, Copy prompts and selection
APIs. The host owns preview painting/input and the thin public location getter.
Filesystem checks occur only on command/status workers; widgets remain on Qt.

## Alternatives

Preserve existing aliases, command IDs, transfer/conflict paths and snapshot
contracts instead of adding new command registries, transfer engines or storage
discovery. Unapproved alternatives remain Pass/Deferred. Per-item deselection
was measured before the existing selection range builder was reused to batch it.

## Runtime Effects

No new pane-load scans, metadata queries, persistent queues or idle services.
Clipboard/link/duplicate work is invocation-only. Location classification is pure
and on demand. Free space uses one eligible query on the existing status worker;
disabled extended status performs none. Pattern matching is bounded and cancellable;
its dedicated task records memory, input routing and idle behavior.

## Tests

Exact focused commands and outcomes are in Validation Results. Tests cover new
commands plus existing Copy/Move/Pack, aliases/history, clipboard, filters, native
snapshot selection, status workers and public API compatibility. Native symlink
privilege and a disposable mounted-volume fixture are unavailable; those checks
are explicitly unverified rather than inferred from mocks.

## Implementation Steps

1. Add synonyms and clipboard-path navigation; validate existing dispatch/history.
2. Add numbered duplicate suggestions, link-target navigation and pane swapping.
3. Implement immediate visible-selection commands and multi-name copying.
4. Add the shared scope predicate, public location hint and approved status behavior.
5. Extract and implement pattern selection, then measure preview/commit behavior.
6. Run focused native/offscreen gates and update usage/API documentation.

## Acceptance Criteria

- All Implement rows are represented in code and focused regression coverage.
- Pass/Deferred rows, F10 and ordinary Copy/Move conflict policies are unchanged.
- Preview marks never leak into committed selection or file-operation dispatch.
- Keypad bindings distinguish ordinary keys; no new filesystem work occurs on Qt.
- Public location hints remain advisory, location-bound and provisional.
- Validation records include actual counts, measured costs, skips and unrun checks.

## 1. Swap Pane Locations

1. Add `SwapPanes(DirectoryPaneCommand)` beside `SyncPaneLocation` in
   [commands](../src/main/resources/base/Plugins/Core/core/commands/__init__.py).
2. Get `left, right = self.pane.window.get_panes()[:2]`, then capture both
   `left_url` and `right_url` before changing either location.
3. Mirror `SyncPaneLocation`: hidden with fewer than two panes, refuse `null://`,
   no-op when both URLs are equal.
4. Call `left.set_path(right_url)` and `right.set_path(left_url)`. Focus stays on
   the same side. Use normal navigation; do not exchange pane objects, selections,
   filters or histories between sides.
5. Bind `Ctrl+U` in `Key Bindings (Windows).json` (currently unused).
6. Unit test with mock panes: both `set_path` calls, the no-op and the refusal.

## 2. Select / Deselect by Pattern

Canonical design and validation: [Select And Deselect By Pattern](PatternSelection.md).
Extracted before implementation as required. This roadmap does not duplicate the
session design; item 2 remains approved independently of items 3 and 9.

## 3. Bind Invert Selection

1. Bind `invert_selection` to keypad `*` using `Num+*`. The current Qt matcher
   accepts this spelling, not `Num*`; test keypad versus ordinary `*`.
   With the Filter Bar open, non-empty printable keypad input edits the bar before shortcut
   dispatch. With it closed, keypad `*` inverts, while keypad `+` / `-` open the
   selection modes. Ordinary punctuation can still start a filter. Space retains
   its normal toggle-selection behavior outside pattern-selection mode.
   Empty-text NumLock-off navigation and Insert still dispatch their normal actions.
2. Replace enumeration with existing selection behavior: capture the selected
   URLs, call `pane.select_all()`, then `pane.deselect(previously_selected)`.
   Keep the read/modify sequence on Qt so a model change cannot interleave it.
   This operates on visible entries without listing scans or new metadata helpers.
   Measure deselection cost before adding any optimization; item 2 is not a prerequisite.
3. Test a filtered pane, empty listing and repeated inversion, including a Qt
   check that hidden or filtered rows are not newly marked and no scan is added.
   Include no/all/partial selection and selection-notification counts; one API
   call is not proof of a single Qt selection update.

## 4. Show in Explorer with the File Selected

1. Add a `ShowInExplorer` command. Keep `F10` unchanged.
2. Accept only a `file://` item under the cursor.
3. Launch `['explorer.exe', '/select,' + native_path]` with `shell=False`.
   Ignore Explorer's nonzero exit code; it is normal.
4. Fall back to opening the folder when nothing is under the cursor.
5. Add it to `File Context Menu (Windows).json`.
6. Unit test the argument list with a patched `subprocess`.
7. Run a native Explorer smoke check with spaces and Unicode in the path;
   verify that the file is selected, not merely that Explorer was launched.

## 5. Copy Names of Several Files

1. Let `CopyFileName` accept all chosen files; join their basenames with newlines.
   Return without clearing the clipboard when no items are chosen.
2. Report with `_report_clipboard_action`, as `F11` does.
3. Replace the single-item `is_visible` check with `bool(self.get_chosen_files())`.
   Keep *Copy file path* single-item; `F11` covers many paths.
4. Update the single-item notes in [shortcuts](../docs/shortcuts.md) and the Core README.
5. Unit test zero, one and several names, visibility, cursor fallback and
   preservation of existing clipboard contents when there is nothing to copy.

## 6. Free Space in the Status Bar

Status: Implemented with the simple design below; Royi approved it after the
latency check. The independent thin public path hint is item 16.

1. Eligibility reuses the pane's committed `Listing.scope`. Only Core's native
   scanner sets it, and only for local NTFS/ReFS directories. UNC paths, mapped
   network drives (resolved to `\\?\UNC\`), other filesystems, archives and
   virtual locations keep the unknown scope and are skipped. Removable NTFS/ReFS
   drives are eligible.
2. `free_space_path(location, listing)` in
   [status_bar.py](../src/main/python/fman/impl/status_bar.py) applies the gate on
   Qt with no I/O. `PaneStatusSnapshot` carries the resulting native path.
3. The existing status worker calls `shutil.disk_usage` once per status refresh,
   after the counts, on the pane's folder (so mounted folders report their own
   volume). Errors leave the field empty.
4. The widget shows `Free: <free> of <total>`, right-aligned, using `size_divisor`.
   It clears on ineligible locations, `null://` and errors.
5. Disabled extended status does no free-space work. Navigation and first paint
   add no work: the scope already exists.
6. Measured: `shutil.disk_usage` on local NTFS takes about 20 us (p99 under 50 us),
   off the Qt thread.
7. Tests in `fman_unittest.impl.test_status_bar`: gate cases, a real native scan,
   UNC skip, query/skip/error paths and label rendering.
8. Coupling: `scope` exists for mark reconciliation. If native scanning extends
   to network or other volumes, revisit `free_space_path`.

Public pane path classification is tracked independently in item 16; it is not
a prerequisite for this completed feature.

Deferred, separate tasks if needed:

- Free space for network shares and exFAT/FAT drives. Network queries need a
  time-bounded call on a separate thread, since an offline server can block.

## 7. Go to Link Target

Decision: Implement the simple command. Visual link indicators remain separate,
deferred work under item 15.

1. Add `GoToLinkTarget`, alias *Reveal link target*, in Command Center only.
   Use the highlighted item, not the marked selection. Add no right-click menu
   entry or default shortcut. Leave Enter's normal open behavior unchanged.
2. Visibility requires only a highlighted `file://` item, including ordinary
   files and folders. Do not detect links or resolve targets while building or
   searching the palette; visibility performs no filesystem I/O.
3. Only when invoked, capture the highlighted URL and convert it to a native
   path. Check `os.path.islink` / `os.path.isjunction` on the existing command
   worker. A non-link gets a short status message without navigation. Resolve
   link chains with `os.path.realpath` only then. If the resolved path still starts
   with `\\?\` (for example `\\?\Volume{GUID}\...`), report an unsupported target
   without navigation, before further target checks or URL conversion. Do not
   strip the namespace prefix to guess a usable path. Explicitly check a supported
   resolved target before dispatch: `realpath()` alone does not prove it exists.
   If initial `lstat` fails because the highlighted item vanished, report that it
   no longer exists. Reserve *Broken link* for a missing target after the source
   was inspected. Neither case navigates. Catch other `OSError`
   failures across inspection, resolution and target checks, and show their reason
   without navigation; do not label access errors or cycles as broken links. Windows `.lnk` shortcuts,
   hardlinks and other reparse types are outside this feature's scope.
   Junctions and volume mount points follow the same supported-target rule; this
   is not a blanket refusal of mounts. Add no special mount-opening fallback,
   mount discovery or Copy/Delete restrictions to this read-only command.
4. Convert the resolved path with `fman.url.as_url`, then dispatch
   `pane.run_command('open_directory', {'url': target_url})`, as in item 13.
   A folder target opens at its resolved location, not the link's path. A file
   target opens its parent and highlights the file without launching it. Reuse
   existing navigation and cursor placement; never pass native paths to `set_path`.
5. No listing fields, retained tags, scanner changes, metadata API changes or
   dependency on items 6 or 15. Add no per-entry loading work, idle jobs, timers
   or background services. Link detection and target resolution are invocation-only.
6. Test palette discovery and visibility without filesystem I/O, the highlighted
   item when other files are marked, ordinary items, file/folder links, broken
   links, missing resolved targets, access failures and chains. Use existing
   link-test helpers and platform skips. Mock retained `\\?\Volume{GUID}\...`,
   extended drive and extended UNC results; assert refusal without URL conversion
   or navigation. Add a native mounted-folder check when a suitable fixture is
   available; otherwise record the skip. Add Qt
   checks for target navigation, file highlighting and unchanged Enter behavior;
   verify there is no context-menu entry. Retain the no-measurable-regression gate
   for first populated pane paint and navigation, using focused baseline/candidate
   checks. Document the command only when implemented.

## 8. Sort by Extension

1. Add a `core.Extension` column in [Core](../src/main/resources/base/Plugins/Core/core/__init__.py).
2. `text`: the extension; `keys(listing, ascending)`:
   `(is_dir ^ ascending, extension.casefold(), natural_name_key)` per entry.
   The host reverses descending order, so grouping must account for direction,
   as the existing columns do. Folders stay first in both directions. No I/O.
3. Set `keys_depend_on_external_data = False`.
4. Make it optional: off by default, enabled by a setting, so default layouts and
   saved widths are unchanged.
5. Bind a sort key (e.g. `Ctrl+F5`) through `sort_by_column` when the column is
   enabled. Resolve its current column index rather than assuming a fixed slot.
6. Unit test the keys for files, folders, no extension and descending order.
   Include optional-column settings and saved-width integration in the medium scope.

## 9. Select the Same Extension

1. Add `SelectSameExtension`. Alias: *Select files with the same extension*.
   This remains an immediate, no-dialog command; it does not open a live preview.
2. Capture the cursor file and committed listing. Use its final filename suffix:
   `archive.tar.gz` means `.gz`. Compare case-insensitively and exclude folders.
3. Compare suffixes directly; the pattern parser is unnecessary. Use the committed
   listing and existing selection APIs without depending on item 2's preview UI
   or a new visible-row helper. Do not enumerate or stat files.
4. Apply one batched `pane.select(urls)` call. Keep the current filter and
   unrelated marks; do not newly mark hidden or filtered rows.
   The shared view builder sorts/deduplicates resolved row indices before grouping
   adjacent ranges. Input/listing order must not create one range per file when
   the view is sorted differently. Preserve successful-prefix effects on lookup
   or iterator failure and the existing missing-row behavior.
5. With no cursor file, a folder or no extension, show a short status message
   without changing selection. Add no default shortcut.
6. Unit test mixed case, compound names, extensionless files, folders,
   visible-row restrictions and preservation of unrelated marks.

## 10. New Folder and Enter

1. Add `CreateDirectoryAndEnter`. Alias: *New folder and enter*.
2. Reuse or extract the prompt and creation logic from `CreateDirectory`.
   Capture the invoking pane's URL and requested destination before creation.
3. After successful creation, navigate to the normalized destination, including
   nested folders. Cancellation, an existing destination or a creation error
   must not navigate.
4. Do not retarget a pane that closed or changed location while creation ran.
   A navigation failure reports the error and leaves the created folder intact.
5. Keep ordinary New Folder and `F7` unchanged. Add no default shortcut.
6. Unit test ordinary and nested creation, cancellation, existing destinations,
   creation failure and stale navigation. Add a Qt check for successful entry
   and pane focus.

## 11. Command Center Synonyms

1. Extend existing command `aliases`; do not add a keyword registry or new API.
2. Add useful vocabulary, such as *Bookmarks* for Favorites, *Extract archive*
   for Unpack Archive and *Preview* for Toggle QuickView.
3. Preserve command IDs, the first alias, shortcuts, visibility checks and
   existing ranking/recent-command rules. Keep the current matched-alias display
   behavior and one result per command.
4. Unit test synonym matching, original aliases, duplicate suppression, correct
   dispatch and recent-command identity.
5. Add concise discovery examples to the
   [Command Center guide](../docs/basics.md#command-center).

## 12. Optional ISO Date Display

1. Continue [DateFormat](../Plan/DateFormat.md), the canonical design; do not create a
   second task or duplicate its implementation plan here.
2. Offer locale formatting (default) or `yyyy-MM-dd HH:mm` for the built-in
   Modified column. Keep timestamps, sorting and other date surfaces unchanged.
3. Before implementation, update that design's legacy column references to the
   current snapshot `text(listing, index)` / `keys(listing, ascending)` contract.
4. Resolve the display pattern once; add no scans, timers or background work.
   Treat clearer presentation as the benefit, not an unmeasured speed claim.
5. Test locale/ISO output, local-time conversion, missing dates and unchanged
   sort keys. Document the setting and its restart requirement.

## 13. Go to Clipboard Path

1. Add `GoToClipboardPath(DirectoryPaneCommand)`. Alias: *Open clipboard location*.
2. Read `clipboard.get_text()` once when invoked. Trim surrounding whitespace
   and one enclosing pair of double quotes, as produced by Explorer's Copy as path.
   Accept absolute native drive/UNC paths and existing unescaped application URLs;
   convert native paths with `fman.url.as_url`. Reject relative or multi-line input
   with a short explanation and no navigation. Do not interpret the clipboard as
   multiple destinations.
   Standard file URIs such as `file:///C:/Work/a%20b.txt` are not supported in this
   first version: report that an absolute path or application URL is required.
   Preserve literal percent sequences in application URLs; do not globally decode
   `%20` or confuse application UNC URLs (`file:////server/share`) with standard URIs.
   For `file://` application URLs, validate the path after the scheme: require a
   drive-absolute or UNC path, preserving the existing drive-root shorthand
   `file://C:`. Reject `file://server/share/x` and drive-relative `file://C:Work`;
   a scheme delimiter alone does not make the path absolute. Leave non-file URL
   rules to existing provider/navigation validation: valid virtual URLs such as
   `network://` must not be rejected by Windows drive/UNC checks.
   After validation, normalize native paths and `file://` path portions with
   `ntpath.normpath`, then convert with `as_url`. This collapses dot components
   and canonicalizes backslash file URLs without filesystem work or percent
   decoding. Non-file provider URLs pass through unchanged.
3. Dispatch `pane.run_command('open_directory', {'url': url})`. Reuse its folder
   navigation, file-parent navigation with cursor placement, and error handling;
   do not add a separate filesystem-check or navigation path.
4. An empty clipboard shows a short status message without navigating. Leave
   Paste and `Ctrl+V` unchanged; add no default shortcut.
5. No clipboard monitoring, persistence, timers or new background service.
6. Unit test plain and quoted paths, UNC paths, application URLs, literal percent
   sequences, empty text, relative/multi-line rejection, standard-URI rejection,
   non-absolute `file://` rejection, drive-root shorthand and valid virtual URL
   dispatch. Verify folder navigation and file highlighting through the existing
   `OpenDirectory` tests; keep Paste behavior unchanged.

## 14. Duplicate a File

1. Keep `DuplicateFile`, its *Create a duplicate file* / *Copy file here* aliases,
   the active-folder destination and the existing Copy dialog and operation.
   Change only the suggested destination for one chosen file or folder.
2. For a file, insert ` Copy N` before its extension: `report.txt` becomes
   `report Copy 1.txt`. Preserve the existing recognized compound extensions,
   such as `backup.tar.gz` becoming `backup Copy 1.tar.gz`. Extensionless files
   and dotfiles without another extension use the whole name: `README Copy 1`
   and `.gitignore Copy 1`.
3. For one folder, append to its whole name: `Folder Copy 1`. Do not treat dots
   in folder names as extension separators. Multiple selections retain today's
   Copy destination-folder prompt and original names; no per-item auto-naming.
4. Start at 1 and increment until the first free candidate; gaps are reusable.
   If the source stem already ends in ` Copy N` with a positive integer, reuse
   that stem's series and continue from N + 1. Thus `report Copy 1.txt` suggests
   `report Copy 2.txt`, skipping occupied names, not `report Copy 1 Copy 1.txt`.
   Apply the same series rule to folder names.
5. Check candidate availability in the destination filesystem, not the pane's
   visible rows or display snapshot. Existing files, folders and dangling links
   occupy names. Use a non-following entry check for local paths and the existing
   provider existence API elsewhere; do not add a directory-wide scan.
6. Add a small private suggestion hook to the shared Copy prompt preparation.
   Its default preserves current behavior; only Duplicate supplies numbered
   candidates. Capture the source and destination before generating the suggestion.
   Keep the normal editable path, filename selection, validation and task submission.
7. Availability is checked when preparing the prompt, not reserved. Enter uses
   the suggested name unless edited; Cancel creates nothing. If another process
   claims the name later, use normal Copy conflict handling. Do not silently
   renumber after confirmation or introduce a separate publication policy.
8. Generate candidates only on invocation, on the existing command worker.
   Cost is one existence check per candidate, with no persistent counter,
   placeholder files, new workers, timers or idle work. Surface lookup errors
   through existing error handling rather than assuming a name is free.
9. Extend `DuplicateFileTest` and `SameFolderOperationsTest`: numbering and gaps,
   existing numbered sources, extensions/dotfiles, folder names with dots,
   hidden entries, directory/link collisions, edited destinations, cancellation
   and normal conflict handling. Verify Enter creates the suggested copy when
   still available, and ordinary Copy/Move/Pack and multiple selections are unchanged.

## 15. Link Indicators in File Rows

Decision: Deferred. The canonical concept is
[UI Design 001: Deferred Link Indicators](../Plan/UIDesign001.md#deferred-link-indicators).

1. Explore visual hints identifying symlinks and junctions in file rows, with
   accessible appearance and metadata acquisition to be designed before implementation.
2. Keep this independent of item 7's invocation-only command and global theme
   adoption. Do not add scanner work or retained metadata as a prerequisite for item 7.
3. Require the linked design's no-pane-loading/navigation-regression gate before
   adoption. Record the detailed visual and metadata decisions there, not in a
   second copy here. This roadmap entry does not authorize implementation.

## 16. Public Location Metadata API

Decision: Implement the thin hint only. Replaces the earlier broader discovery
proposal; no storage discovery service or new provider contract is included.
The purpose is to let third-party plug-ins identify potentially expensive paths
using whatever information the pane already has, not measure storage speed.

1. Export an immutable `LocationInfo(location, access_hint)` record from
   `fman.listing` and add `DirectoryPane.get_location_info() -> LocationInfo | None`.
   Also export `NATIVE_LOCAL = 'native_local'`, `NETWORK = 'network'` and
   `UNKNOWN = 'unknown'` from `fman.listing`; consumers compare these constants
   rather than repeating raw strings. The record ties the hint to its captured
   application URL without a separate pane-path read. Consumers need only public
   `fman` / `fman.listing` imports, not `fman.impl`, Qt or Win32 APIs. No enum or
   additional record fields are needed.
2. Compute the small record only when the getter is called, from the current
   committed location and matching listing captured together on Qt. Return `None`
   if there is no committed listing or its location does not match the pane;
   consumers treat `None` conservatively as `UNKNOWN`. During an initial navigation
   scan the old model may still provide a valid record for the old location. After
   the model switches, return `None` until the new displayed listing commits.
   Add no separate pending-navigation tracking. Reuse existing Qt dispatch for
   calls from command workers. No per-entry work, filesystem I/O or discovery waits.
3. Define `access_hint` from existing facts, with this precedence:
   - `NETWORK`: an explicit `network://` location or application UNC URL
     (`file:////server/share/...`). Identify these syntactically, without probing.
   - `NATIVE_LOCAL`: a `file://` location with the known matching `Listing.scope`
     used by item 6's eligibility check. Currently this identifies Core's native
     local NTFS/ReFS listing path; it is the fast-path candidate, not a speed promise.
   - `UNKNOWN`: everything else, including fallback local listings, drive-letter
     paths without a known scope, archives and other virtual providers. Treat this
     as potentially slow; do not infer local storage merely from `file://`.
4. Do not add a guessed `medium` or `usb` category. USB NTFS/ReFS can qualify as
   `native_local`; other USB devices remain unknown unless later work supplies
   real information. Mapped network drives whose network nature is not retained
   remain `unknown`. No drive-type, bus, volume-root, mount-point or network queries
   are added to make classification more complete.
5. Factor item 6's pure URL/scope eligibility predicate into a shared internal
   helper independent of status-bar code, used by both `free_space_path` and the
   new getter. The getter must not call or import `free_space_path`. Keep item 6's
   free-space behavior unchanged. Preserve `Listing` fields, its identity/equality
   rules and the `scan -> Listing` provider contract.
   Unsupported providers need no changes. If native scanner scope eligibility
   changes, review both consumers rather than promoting unknown paths by inference.
6. The hint is a snapshot for optional-work policy, not an access, identity or
   performance guarantee. Keep existing operation-time checks and worker rules;
   `native_local` does not authorize blocking I/O on Qt. No caching, persistence,
   new signals, subscriptions, requests, workers, timers or work on pane load.
7. Test explicit UNC/network locations, native scopes, unknown/fallback/mapped
   paths, virtual providers, no listing, and location/listing mismatch. Verify
   immutable records, the exported constants and zero filesystem calls. Extend
   existing Qt integration tests with a third-party-style consumer that imports
   only the public API, reads the getter on Qt and a command worker, and observes
   old-location / `None` / new-location results across a controlled navigation.
   Retain item 6 tests and confirm no pane-loading or selection changes. Do not
   add Directory Size skipping, fuzzy-find warnings or another application
   behavior solely to provide a consumer.
8. When implemented, document the constants, `None` contract and advisory,
   provisional classification semantics in [PlugIn.md](../PlugIn.md), and include
   the classification caveat with the API's changelog entry. Explain the native
   scanner dependency and USB/unknown limitations; provisional classification is
   not measured speed or permission to break the public API silently.

Deferred beyond this thin API: accurate USB/device classification, filesystem
name retention, volume-root discovery, provider metadata hooks, explicit discovery
requests, update subscriptions and network acquisition. Add only for a concrete
consumer under a separate design and performance review.

Historical review notes (Claude Opus 5.5, 2026-10-21; broader proposal):

- No current consumer needs it: item 6 gates free space on the existing
  `Listing.scope`. Implement only when a concrete consumer exists, and size the
  API to that consumer.
- The Windows scanner already reads the filesystem name in `scope()` but
  discards it; drive type is never queried. "Reuse collected facts" is partial.
- Prefer a smaller first version: `get_location_info()` plus the provider hook.
  Add `request_location_info` and connection types only when a consumer needs them.
- Network acquisition must be time-bounded on its own thread; an offline server
  can block volume queries.

## Review Follow-Up

### 2026_10_21 - GitHub Copilot / GPT-6 Astra

Response to Claude Opus 5.5's feedback. These notes preserve Royi's decisions and
the approved behavior; they do not authorize application changes in this edit.

| Item | Disposition |
| --- | --- |
| 2 | Adopted mode-local input before pane shortcuts. The live-preview feature needs its own implementation task, not a prompt-only change. |
| 3 | Adopted remembered selection, Select All, then Deselect. Verify the operation as one Qt-thread sequence and measure per-item deselection before optimizing. |
| 6 / 16 | Agree with keeping free space independent of the metadata API. The implemented scope gate includes removable NTFS/ReFS, unlike the earlier fixed-only proposal. Keep that difference explicit and item 16 Deferred. |
| 7 | Added explicit missing-target handling. Volume-mount behavior remains a scope decision for read-only navigation, not an automatic transfer-safety restriction. Link checks remain invocation-only. |
| 13 | Defined the first version's accepted path formats and rejection of relative, multi-line and standard file-URI input. Never decode literal percent sequences in application URLs. |
| 14 | Keep the approved `filename Copy N.ext` format and series continuation; do not substitute Explorer-style naming. Any search-attempt budget needs a separately defined fallback, never a silently occupied suggestion or a numeric ceiling that breaks existing series. |
| 8 | Appending the optional column and adding a sorting-performance gate are reasonable refinements for the deferred design; existing default columns and shortcuts must not shift. |
| 15 | A reparse flag alone cannot identify symlinks/junctions, even after excluding cloud placeholders. Retain precise classification and the pane-loading performance gate in the canonical deferred UI design. |
| 16 | A timeout on a waiting thread does not terminate its blocked Windows call. Future network discovery needs bounded outstanding work, stale-result rejection and explicit timeout/shutdown behavior; do not claim a hard I/O deadline without a cancellable API or suitable isolation. No new discovery service is approved now. |

Verified with the current code and read-only probes: `Num++`, `Num+-` and
`Num+*` match keypad events and not ordinary keys; `Num*` does not match keypad
star. `as_url` preserves a relative path as relative, and `as_human_readable`
does not decode a standard percent-encoded file URI. `realpath()` can return a
nonexistent target. The status implementation was inspected, but Opus's reported
test results and timing measurements were not independently rerun in this review.

### 2026_10_21 - GitHub Copilot / Claude Opus 5.5

Response to GPT-6 Astra's follow-up. Feedback only; item designs and Royi's
decisions are unchanged.

| Item | Response |
| --- | --- |
| 3 | Agree: run remember / Select All / Deselect as one Qt-thread sequence. Separate worker-dispatched calls could interleave with a refresh. |
| 7 | Mount points are also a correctness issue, not only scope. `ntpath.realpath` strips `\\?\` only when the plain path resolves identically, so a volume mounted on a folder without a drive letter can resolve to `\\?\Volume{GUID}\...`, which `as_url` cannot turn into a navigable URL. Simplest consistent policy: treat a mount point as its own target and open the mount folder as-is. Regardless of policy, refuse resolved paths that still start with `\\?\`. Add a native mount-point check to the item 7 tests; exact output was not confirmed without a mounted volume. |
| 13 | Also reject application URLs whose path is not absolute (neither a drive letter nor a leading `//`), e.g. the standard UNC URI form `file://server/share/x`. |
| 14 | Agree: keep `name Copy N.ext`. Withdrawn: a bare numeric cap. Any search budget needs an explicit fallback, never a silently occupied suggestion. |
| 15 | Agree: the reparse attribute alone cannot identify symlinks/junctions. Precise and cheap alternative for the deferred design: `_fsparser.Columns.add()` already reports entries with link tags during the scan; retaining that per-entry flag avoids new metadata I/O. |
| 16 | Agree: a timeout does not stop a blocked Windows call. Use bounded outstanding work and stale-result rejection; my earlier "time-bounded" wording was imprecise. |

Minor, non-blocking: item 2 step 12 uses 3-space continuation lines; item 6 is
implemented but still listed in the suggested order; item 6's Implementer record
has no separate Validation Results section (required on moving to `Done`).

Validation note: Opus ran `fman_unittest.impl.test_status_bar` (18 tests) and
`SnapshotFilterBarIT.test_status_snapshots_are_complete_for_visible_entries`;
both passed. The `shutil.disk_usage` timing was a standalone microbenchmark,
not an in-application measurement.

### 2026_10_21 - GitHub Copilot / Claude Opus 5.5 (second response)

Response to GPT-6 Astra's revision of item 16 and the remaining open points.
Feedback only; item designs and Royi's decisions are unchanged.

Item 16 (thin access hint): the direction is right. Verified against the code:
`network://` is Core's `NetworkFileSystem` scheme, and `as_url` renders UNC
paths as `file:////server/share/...`, so both network markers are syntactically
correct. Treating mapped drives, exFAT/FAT, archives and fallback listings as
`unknown` is the safe default.

| Item | Response |
| --- | --- |
| 16 | Name and wire at least one concrete consumer in the same change, e.g. automatic Directory Size skipping `network` or recursive fuzzy find warning on `unknown`, so the API is exercised beyond unit tests. |
| 16 | Consider `DirectoryPane.get_access_hint() -> str \| None` instead of a one-field `LocationInfo`; a record is a fair choice only if more fields are expected. If the record stays, note that `fman.listing` describes snapshots, not locations. |
| 16 | Export the three values as constants (e.g. `fman.listing.NATIVE_LOCAL`) so consumers do not compare raw strings. |
| 16 | Document that `None` occurs during navigation, when the committed listing may still belong to the previous location; consumers should treat `None` as `unknown`. |
| 16 | Mark the hint provisional in `PlugIn.md` and the changelog; `native_local` depends on scanner scope semantics that may change. |
| 16 | Factor the scope predicate into a shared helper used by both item 6 and item 16. Do not call `free_space_path` and test it for `None`; that couples the public API to status-bar code. |
| 7 | Still open: regardless of mount-point policy, refuse a resolved path that still starts with `\\?\` (e.g. `\\?\Volume{GUID}\`), since it cannot become a navigable URL. Add a native mount-point check to the tests. |
| 13 | Still open: reject application URLs whose path is not absolute (neither a drive letter nor a leading `//`), e.g. the standard UNC URI form `file://server/share/x`. |
| 2 | Cosmetic, still open: step 12 continuation lines use 3-space indentation. |

Adopted since the previous response: item 6 removed from the suggested order;
item 13 rejects standard percent-encoded `file:///` URIs.

### 2026_10_21 - GitHub Copilot / GPT-6 Astra (thin-hint follow-up)

Response to Opus's second response. Item 16 remains Small / Implement with no
discovery work. These are review recommendations; the item designs and application
code are unchanged by this review.

| Item | Disposition |
| --- | --- |
| 16 | Do not require new Directory Size skip rules or fuzzy-find warnings. That expands the approved API-only scope. Exercise the public getter in a third-party-style Qt integration fixture; item 6 continues to exercise the shared classification without changing its behavior. |
| 16 | Retain `LocationInfo(location, access_hint)`: it has two useful fields, not one. Capturing the location with its hint avoids a separate pane-path read that could observe another navigation state. This is a location-bound snapshot, so `fman.listing` is a reasonable home without anticipating more fields. |
| 16 | Adopt public named constants alongside the record for the three documented string values. No new enum framework or provider contract is needed. |
| 16 | Clarify `None` as no matching committed listing; consumers treat it conservatively as `unknown`. During initial navigation scanning, the old model can still supply a valid record for the old location. After the model switches, its displayed listing starts as `None` until projection commits. Do not add navigation tracking just to return `None` throughout every pending navigation. |
| 16 | Adopt an explicit shared pure URL/scope predicate outside status-bar code. The getter must not call `free_space_path`; status rendering is not the public API's owner. |
| 16 | Document advisory/provisional classification semantics and the native scanner dependency when implemented. This is not measured speed, permission for Qt-thread I/O or permission to break the public API silently. No changelog entry is needed for this planning review. |
| 7 | Agree that v1 should explicitly refuse still-extended `\\?\` target paths before URL conversion, with a native mount-point check in its tests. This avoids adding extended-namespace navigation support; the mount-point policy remains a separate decision. |
| 13 | Agree that a scheme delimiter alone does not make a file URL absolute. Explicitly reject relative path portions such as `file://server/share/x`. Apply Windows drive/UNC rules to `file://` URLs, not indiscriminately to valid virtual schemes such as `network://`. |
| 2 | Continuation indentation is a cosmetic correction, not an implementation blocker. |

Navigation evidence: [model replacement](../src/main/python/fman/impl/model/__init__.py)
keeps the old source model during the initial scan, then installs a new
[listing model](../src/main/python/fman/impl/model/listing.py) whose `_displayed`
starts as `None` and is populated on commit. Source inspection only; the proposed
public getter is not implemented and its Qt lifecycle tests have not been run.

## Reviewers

### 2026_10_20 - Copilot

- Role: Reviewer
- Activity: Review
- Agent: Copilot SDK in VS Code
- Model: GPT-6.1 Sol
- Effort: High
- Context Window: 1M
- Outcome: Added three small feature candidates; retained the existing pattern-selection
  and Explorer-selection entries without duplication. No implementation authorized.

### 2026_10_20 - Copilot

- Role: Reviewer
- Activity: Review
- Agent: Copilot SDK in VS Code
- Model: Claude Fable 5.1
- Effort: High
- Context Window: 1M
- Outcome: Added optional ISO date display by reference to its canonical design.
  Pattern selection, same-extension selection, multi-name copying and command
  synonyms were already covered and were not duplicated. No implementation authorized.

### 2026_10_20 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Added Go to clipboard path using existing navigation. Swap panes,
   multi-name copying, same-extension selection and command synonyms were already
   covered by items 1, 5, 9 and 11 and were not duplicated. No implementation authorized.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Applied the review corrections for selection patterns/APIs, empty
   clipboard actions, status-worker data flow, link navigation, descending sort
   and implementation scope. Added the agreed numbered-copy design for item 14,
   including folders, continued series, unchanged multiple-selection behavior
   and normal late-conflict handling. Royi's decisions and prior records are
   preserved; this edit updates the design only, not application code.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Replaced item 2's modal prompt with the agreed inline Filter Bar-style
   Select/Deselect modes and live, uncommitted selection preview. Defined baseline
   matching, Enter/Esc, existing-filter preservation and bounded worker lifecycle.
   Item 9 remains a separate no-dialog action. Decision cells and earlier reviewer
   records are unchanged; design update only, no application implementation.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Expanded item 6 with shared, immutable pane location metadata and
   separate dynamic free-space measurements. Limited free-space queries and display
   to known fixed NTFS/ReFS volumes, including USB disks reported as fixed; other
   locations are skipped. Preserved decision cells and prior records. Design only;
   no application implementation or zero-latency claim.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Made item 6's metadata explicitly public for third-party consumers
   and providers: immutable LocationInfo, a no-I/O pane getter, coalesced requests,
   update subscriptions and an optional provider hook. Added compatibility,
   threading, lifecycle, documentation and public-only plug-in tests. The fixed
   NTFS/ReFS free-space policy and user decisions remain unchanged. Design only.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Revised item 7 for Command Center and context-menu navigation using
   retained public per-entry link metadata. Defined zero-copy native tag retention,
   invocation-only target resolution and a no-regression pane-paint/navigation gate.
   Marked item 7 Deferred at Royi's request; other decisions and reviewer history
   remain unchanged. Documentation only, no application implementation.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Marked the simple, invocation-only Command Center action in item 7
   Implement at Royi's request. Removed context-menu and retained-metadata
   requirements from that command. Added Deferred item 15 linking to the canonical
   visual-indicator concept in UIDesign001. Other decisions and earlier records
   are preserved; documentation only, no application implementation.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Feedback only; no design text or decisions changed. Item 6: show
   free space simply (status worker, `shutil.disk_usage` gated on the known
   NTFS/ReFS `Listing.scope`); the public LocationInfo API is split into item 16,
   which needs its own task and a concrete consumer. Item 2 needs its own
   task and mode-local key routing, since pane shortcuts (Space, keypad `-`) run
   before Filter Bar input. Item 3 can invert via remembered marks, `select_all`
   and `deselect`; measure deselection cost. Item 7 needs an explicit missing-target
   check and refusal of volume mount points. Item 13 should handle or refuse
   `file:///` percent-encoded URIs, relative paths and multi-line text. Item 14:
   consider Explorer-style names and cap candidate numbering. Deferred: item 8
   column last with a sort-performance gate; item 15 can start from the reparse
   attribute bit, excluding cloud placeholders. Verify keypad key names in tests.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Recorded the response to Opus 5.5 and applied concrete input-routing,
  keypad, inversion, missing-target and clipboard-format corrections. Preserved
  approved Copy N naming, Deferred boundaries, existing reviewer records and the
  item 6 implementation record. Runtime keypad/path probes support the findings;
  no application code or user decisions changed.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Responded to GPT-6 Astra's follow-up. Accepted the corrections on
   items 3, 14, 15 and 16. Item 7: mount points can resolve to `\\?\Volume`
   paths that cannot be navigated; refuse such paths and decide the mount-point
   policy explicitly. Item 13: reject non-absolute application URLs. Feedback
   only; no design text or decisions changed.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Narrowed item 16 to the user-approved thin public access hint and
   marked it Implement. Reuse only the current URL and item 6's existing scope
   predicate; no added discovery, scanner work, guessed USB/speed tier or provider
   migration. The broader metadata API remains future work. Earlier reviews and
   the item 6 implementation record are preserved; documentation only.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Reviewed Astra's thin item 16 design: approve the direction; asked
   for a concrete consumer, value constants, documented `None`, provisional status
   and a shared scope predicate instead of reusing `free_space_path`. Items 7
   (`\\?\` refusal) and 13 (non-absolute application URLs) remain open.
   Feedback only; no design text or decisions changed.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Reviewed Opus's second response. Recommend constants, explicit
   no-listing semantics and a shared pure predicate; retain the location-bound
   record and test its public API without unrelated consumer behavior changes.
   Qualified navigation timing against the model's commit path and file-URL
   validation against virtual schemes. Recorded remaining item 7/13 boundaries;
   no item designs, decisions or application code changed.

### 2026_10_21 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Applied the accepted review recommendations to the designs at Royi's
   request. Item 16 retains the thin location-bound record and gains constants,
   precise `None` semantics, a shared predicate, public-only Qt integration coverage
   and advisory/provisional documentation. Item 7 explicitly refuses retained
   extended-namespace targets; item 13 validates file-URL paths without rejecting
   valid virtual schemes. Corrected item 2 indentation. All decisions and earlier
   records are preserved; design changes only, no application implementation.

### 2026_10_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Verified approved item boundaries against current code and prior reviews.
   Item 2 was extracted before implementation. Item 6's documented code was absent
   in this checkout, so the approved simple implementation was included. Native
   and offscreen gates pass; this is implementer verification, not an independent review.

### 2026_10_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 872K
- Outcome: Request changes for two P2 regressions, both reproduced. Keypad `*`,
   `-` and `+` run commands instead of typing into an open Filter Bar (R1).
   Select same extension took 2.3 s on Qt for 20,000 matches sorted by date (R2).
   Other approved items match their designs; both focused gates pass. See
   Implementation Review.

### 2026_10_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Addressed all four Opus findings and recommendations. Preserved closed-bar
   keypad shortcuts while restoring open-bar editing; reproduced and fixed fragmented
   selection ranges; added native link-cycle/deleted-entry and normalized-navigation
   checks. Reproduced the reported combined-process clipboard teardown warning and
   validated test-owned clipboard cleanup. Original reviews and excluded decisions
   remain unchanged; this is implementer verification, not independent re-review.

### 2026_10_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: Extra High
- Context Window: 872K
- Outcome: R1-R4 and the teardown warning are resolved and verified. Request one
   change: the R1 fix swallows NumLock-off keypad navigation while the Filter Bar
   is open, because empty key text counts as printable (N1, reproduced). Gates
   pass with fatal-output detection. See Implementation Review 2.

### 2026_10_22 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Addressed both Review 2 findings and the recommended regression extension.
   The real-Controller test reproduced seven swallowed empty-text keypad actions;
   requiring non-empty printable text restored navigation and Insert while retaining
   R1 punctuation behavior. Missing-source reporting is now distinct from broken
   target reporting. Original Opus records and previous results remain historical.

## Implementer

### 2026_10_21 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Claude Opus 5.5
- Effort: High
- Context Window: 872K
- Outcome: Implemented item 6 with the simple `Listing.scope` gate and one
   `shutil.disk_usage` call on the existing status worker (measured about 20 us).
   Split the public LocationInfo design into Deferred item 16. Validation:
   `fman_unittest.impl.test_status_bar` (18 tests) and
   `SnapshotFilterBarIT.test_status_snapshots_are_complete_for_visible_entries` pass.

### 2026_10_22 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Implemented only approved rows, including the dedicated PatternSelection
   task. Reused Core navigation/Copy behavior, immutable snapshots, existing status
   worker and public APIs. Added no storage-discovery service or deferred feature.
   Final gates: 317 unit tests passed; 89 native Qt tests with one expected symlink
   skip; 18 offscreen tests with the same skip. Usage, shortcuts, API reference,
   README and application changelog updated. No full suite or freeze.

### 2026_10_22 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Fixed R1-R4 in the owning input-routing, shared selection and Core command
   paths. Added regressions and concise documentation. The 20k Modified-order case
   now produces one range instead of 20,000; native cycle/stale-highlight errors are
   reported without navigation. Unit gate: 318 passed; native aggregate: 95 tests,
   one expected symlink skip, no post-test fatal output after test-only clipboard
   ownership cleanup. No application clipboard policy or unapproved feature changed.

### 2026_10_22 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Extra High
- Context Window: 1M
- Outcome: Fixed N1 with an explicit non-empty keypad-text guard and extended tests
   to generic/Windows Core bindings, cursor movement and Insert mark toggling. Fixed
   N2 by distinguishing failed source inspection from missing target resolution.
   Unit gate: 318 passed. Native Qt: 106 tests, one expected symlink skip. Sequential
   offscreen replay: 33 tests, one expected skip; an earlier concurrent run timed out
   and remains an unattributed transient. Documentation updated; no full suite/freeze.

## Validation Results

### Commands

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.commands.test_unpack_archive','fman_unittest.test_favorites','fman_unittest.test_quick_view','fman_unittest.test_listing','fman_unittest.impl.test_filter_pattern','fman_unittest.impl.test_status_bar','fman_unittest.test_portable.PluginApiCompatibilityTest','fman_unittest.impl.plugins.test_plugin','fman_unittest.impl.plugins.test_key_bindings','fman_unittest.impl.plugins.test_context_menu','-q'],env=env,timeout=240).returncode)"
python -B -c "import build, os, subprocess, sys; env=build._environment(); env['QT_QPA_PLATFORM']='windows'; sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.RoadmapCommandsIT','fman_integrationtest.test_qt.PatternSelectionIT','fman_integrationtest.test_qt.SnapshotFilterBarIT','fman_integrationtest.test_qt.SortedFileSystemModelIT','fman_integrationtest.test_qt.ClipboardCommandsIT','fman_integrationtest.test_qt.CommandPaletteRecentIT','fman_integrationtest.impl.plugins.test_plugin.PluginTest','-q'],env=env,timeout=240).returncode)"
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); sys.exit(subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.RoadmapCommandsIT','fman_integrationtest.test_qt.PatternSelectionIT','fman_integrationtest.test_qt.ClipboardCommandsIT','-q'],env=env,timeout=180).returncode)"
```

- Unit/command gate: **317 passed**, 20.079 s.
- Native Qt gate: **89 tests, 88 passed, one expected skip**, 9.777 s.
- Offscreen gate: **18 tests, 17 passed, one expected skip**, 2.968 s. An initial
   run without `QT_QPA_FONTDIR` failed geometry with missing-font warnings; the
   configured rerun passed. No test failure was ignored.
- Expected skip: Windows symlink creation privilege unavailable. Real junction
   navigation, clipboard file highlighting and native local scope/free-space checks
   ran. Still-extended drive/UNC/Volume targets and access failures use unit tests.
- Item 7: no disposable mounted-volume fixture was available; native mount behavior
   remains unverified. No privileged mount creation or user-data mutation was attempted.
- Actual inversion notifications: one for none-to-all, one for all-to-none, two
   for partial inversion. The exact Qt test passed after the final count assertions.
- Public location getter: immutable exported record/constants, no filesystem calls,
   worker/Qt reads, and controlled old-location / None / new-location transitions pass.
- Syntax/render/link checks cover edited usage and API docs. Editor diagnostics
   are clear. No packages, environments, full test suite, clean, freeze or release build.

### Measured Scope

- Synthetic committed listing: 10,000 rows; 5,000 matches. Native final run:
   next-input processing 14.7 ms; query-to-preview 15.0 ms; Select commit 108.2 ms;
   Deselect commit 327.5 ms. Both commits emit one selection notification.
- Before batching, the same Deselect test measured 2936.0 ms and 5,000 notifications.
   These are local UI timings, not filesystem-transfer or general performance claims.
- Three alternating link-command registration pairs on small native fixture panes:
   first populated paint median 7.3 -> 7.4 ms; navigation paint 7.0 -> 8.9 ms.
   The command's visibility and invocation were forbidden during loading. This
   bounded sample passed the regression guard; it is not a complete startup benchmark.
- Focused tests found and fixed deleted-view preview cleanup. No late worker
   traceback remained. Existing clipboard and alias tests were updated only for
   the explicitly approved multi-name and synonym behavior.

## Implementation Review (2026_10_22, Opus)

Request changes for R1 and R2. Items 1, 3, 5, 6, 11, 14 and 16 match their
designs. Item 2 is reviewed only where it meets keypad routing; its canonical
review belongs to [PatternSelection](PatternSelection.md).

### Findings

- **R1 [P2] Keypad `*`, `-` and `+` no longer type into the Filter Bar.**
  `_on_key_pressed` checks shortcuts before the Filter Bar, except in pattern mode.
  Probe through the real `Controller` and Core bindings, with the filter holding
  `re`: keypad `*`, `-` and `+` ran `invert_selection`, `deselect_by_pattern` and
  `select_by_pattern`; the filter text stayed `re`. Before these bindings,
  keypad `*` typed `*.pdf`-style patterns.
  - Risk: inversion silently marks every visible row, and the next command acts
    on those marks.
  - Fix: while the Filter Bar is open, let keypad text keys edit it, as pattern
    mode does. Add a regression beside the Space test in `FilterBarIT`.
  - Decide whether keypad `*` should still start a filter when the bar is closed.
- **R2 [P2] Select same extension can freeze the UI in large folders.** The URL
  list follows listing order, and `_change_selections` merges only rows that are
  consecutive in input order. Probe, 20,000 matches on Qt: sorted by Name,
  117 ms and 1 range; sorted by a shuffled Modified time, 2,330 ms and 19,999
  ranges. Sort the collected rows before building ranges in
  `_change_selections`. Every `select`/`deselect` caller benefits.
- **R3 [P3] Go to link target can end in an unhandled error.** A two-junction
  cycle makes `os.stat(target)` raise WinError 1921. A highlighted item deleted
  since display makes `os.lstat` raise. Catch `OSError` and report the reason;
  keep *Broken link* for `FileNotFoundError`.
- **R4 [P3] Clipboard paths are not normalized.** `C:\Users\..\Windows` becomes
  `file://C:/Users/../Windows`, and `file://C:\Windows` keeps its backslashes.
  Open Directory passes the URL unchanged, so it becomes the pane location,
  history entry and sort-settings key. Normalize native paths with
  `ntpath.normpath` before `as_url`, and convert or refuse backslashes in
  `file://` input.

### Verified

- Swap captures both URLs before navigating, refuses `null://` and ignores
  equal locations. `Ctrl+U` has no other Core binding.
- Invert runs as one Qt sequence; its Deselect input is in row order, so ranges
  merge.
- Duplicate: series continuation, dotfiles, compound extensions and dotted
  folder names follow the design. Local candidates use `lstat`; multiple
  selections keep the Copy prompt.
- `native_local_scope` is shared. The public getter does not call
  `free_space_path`. `disk_usage` runs only on the status worker.
- The location hint is captured on Qt with its listing. A mismatch returns
  `None`; UNC and `network://` are syntactic.
- Broken junctions, including a missing target parent, report *Broken link*.
  A junction loop resolves to a real folder.
- PlugIn.md, Core README, user docs, README and changelog match the code.

### Validation Results

- Unit/command gate (command above): 317 tests, OK, 20.1 s.
- Native Qt gate (command above): 89 tests, OK, one expected skip, 14.8 s. In
  that run, after `OK`, faulthandler printed `Windows fatal exception: code
  0x80010108` (RPC_E_DISCONNECTED) from a thread without a Python frame. It did
  not recur in `ClipboardCommandsIT`, `RoadmapCommandsIT` or
  `PatternSelectionIT` alone. Exit code 0; not attributed.
- Ad-hoc probes outside the repository: keypad routing with an open filter,
  same-extension cost at 20,000 rows, link cycles and broken junctions, and
  clipboard parser inputs.
- No source change, full suite, benchmark, freeze or package.

## Implementation Review Resolutions

| Finding / Recommendation | Resolution |
| --- | --- |
| R1: keypad shortcuts interrupt filtering | An open Filter Bar receives printable keypad text before Core shortcuts. Real Controller/Core-binding tests cover `*`, `-`, `+`, ordinary punctuation and retained marks. Existing Space and pattern-mode tests pass. |
| R1: decide closed-bar keypad `*` | Retain the approved Invert selection binding. It does not start a filter when the bar is closed; ordinary `*` can. Use Command Center to invoke selection commands while an existing filter is open. Documented in Basics, Shortcuts and Core README. |
| R2: selection ranges depend on input order | The shared Select/Deselect builder sorts unique resolved view rows and coalesces adjacent ranges. Lookup/iterator failure still commits only the resolved prefix; empty input and ignored missing rows retain their behavior. No filesystem scans or selection API changes. |
| R2: large sorted-folder regression | Added one bounded 20k-row fixture, Name and shuffled Modified order, Select and Deselect. Assert one Qt submission and one range, plus the exact selected set. Timings below are local observations, not a new benchmark suite or general speed claim. |
| R3: uncaught link failures | Catch missing paths and other `OSError` failures from initial inspection, chain resolution and target verification. Missing paths keep Broken link; other errors show their reason. Native two-junction cycle (WinError 1921) and deleted highlighted entry tests pass without navigation. |
| R4: unnormalized clipboard locations | Validate then normalize native drive/UNC paths and file-URL path portions with `ntpath.normpath`/`as_url`. Backslashes become canonical application separators; dot components collapse. Literal percent sequences and non-file provider URLs remain intact. Real file-parent navigation/highlighting tests pass. |
| Native teardown warning | The combined gate reproduced `0x80010108` after unittest OK and was counted as failed. Individual Qt groups were clean. A test-only ownership-checked clipboard clear before fixture teardown removed the reproduced warning; the final aggregate is clean. No MIME cloning, OLE proxy restoration, production clipboard changes or exception suppression. This does not certify every external clipboard/COM environment. |

### Review Fix Validation

The launchers capture child output and reject native fatal diagnostics or Python
tracebacks even if unittest itself reports OK and returns zero:

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); result=subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.commands.test_unpack_archive','fman_unittest.test_favorites','fman_unittest.test_quick_view','fman_unittest.test_listing','fman_unittest.impl.test_filter_pattern','fman_unittest.impl.test_status_bar','fman_unittest.test_portable.PluginApiCompatibilityTest','fman_unittest.impl.plugins.test_plugin','fman_unittest.impl.plugins.test_key_bindings','fman_unittest.impl.plugins.test_context_menu','-q'],env=env,timeout=240,capture_output=True,text=True); output=result.stdout+result.stderr; print(output); sys.exit(result.returncode or int(any(marker in output for marker in ('Windows fatal exception','Fatal Python error','Traceback (most recent call last):'))))"
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); result=subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.RoadmapCommandsIT','fman_integrationtest.test_qt.PatternSelectionIT','fman_integrationtest.test_qt.SnapshotFilterBarIT','fman_integrationtest.test_qt.SortedFileSystemModelIT','fman_integrationtest.test_qt.ClipboardCommandsIT','fman_integrationtest.test_qt.CommandPaletteRecentIT','fman_integrationtest.impl.plugins.test_plugin.PluginTest','-q'],env=env,timeout=240,capture_output=True,text=True); output=result.stdout+result.stderr; print(output); sys.exit(result.returncode or int(any(marker in output for marker in ('Windows fatal exception','Fatal Python error','Traceback (most recent call last):'))))"
```

Final offscreen replay:

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); result=subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.RoadmapCommandsIT','fman_integrationtest.test_qt.PatternSelectionIT','fman_integrationtest.test_qt.FilterBarIT.test_open_filter_owns_keypad_text_before_core_shortcuts','fman_integrationtest.test_qt.ClipboardCommandsIT','-q'],env=env,timeout=180,capture_output=True,text=True); output=result.stdout+result.stderr; print(output); sys.exit(result.returncode or int(any(marker in output for marker in ('Windows fatal exception','Fatal Python error','Traceback (most recent call last):'))))"
```

- Unit/command gate: **318 passed**, 20.790 s.
- Final native aggregate: **95 tests, 94 passed, one expected symlink-privilege
   skip**, 15.753 s. No fatal/traceback diagnostics after test-owned clipboard cleanup.
- Final configured offscreen replay: **23 tests, 22 passed, the same expected
   symlink-privilege skip**, 5.389 s. No fatal/traceback diagnostics. Edited Markdown
   renders and local links resolve; editor diagnostics are clear.
- Before that cleanup, all 94 assertions finished but teardown emitted WinError
   `0x80010108`; that run was rejected, not treated as a pass. Fresh-process groups
   (changed workflows, clipboard, snapshot/model, palette) passed independently.
- R2 baseline: Name order 113.1 ms Select / 105.8 ms Deselect, one range each;
   Modified order 2242.0 ms / 8254.5 ms, 20,000 ranges each. After the fix, the same
   focused check measured 118.3 / 104.6 ms for Name and 119.2 / 108.8 ms for Modified,
   one range each. Setup, file verification and clipboard work are not included.
- The final combined native run also measured Name 119.2 / 109.7 ms and Modified
   117.7 / 109.1 ms. Structural range assertions are the stable regression gate;
   these single-run local timings are not filesystem throughput claims.
- Native junction-cycle and deleted-highlight checks ran on disposable files.
   Symlink privilege and disposable mounted-volume limitations remain as previously
   recorded. No elevation, user-data fixtures, new packages/environments, full suite,
   clean, freeze or release build. Original implementation validation remains historical.

## Implementation Review 2 (2026_10_22, Opus)

R1-R4 are fixed. Request one change: N1 is a regression introduced by the R1 fix.

### Findings

- **N1 [P2] Keypad navigation stops working while filtering.** With NumLock off,
  keypad arrows, Page Up/Down, Home, End and Insert send an empty `event.text()`.
  `''.isprintable()` is `True`, so `keypad_text` routes them to the Filter Bar,
  which ignores them, and `_on_key_pressed` still returns `True`.
  - Probe through the real `Controller` and the Core `Num+` bindings: with the
    filter closed, the six keys ran `move_cursor_*`; with the filter holding
    `re`, they ran nothing. Num+Insert also stopped toggling marks.
  - Fix: require non-empty text (`event.text() and event.text().isprintable()`).
  - Extend `test_open_filter_owns_keypad_text_before_core_shortcuts` with
    Num+Down and Num+Insert while the filter is open.
- **N2 [P3] A deleted highlighted file is reported as a broken link.** The
  `FileNotFoundError` from `os.lstat` shares the *Broken link* message. Report that
  the highlighted item no longer exists; keep *Broken link* for a missing target.

### Verified

- R1: keypad `*`, `-` and `+` extend an open filter and run no command. With the
  bar closed they still invoke their commands, and ordinary keys still type. The
  docs record that behavior.
- R2: rows are de-duplicated, sorted and coalesced, and a lookup failure still
  commits the resolved prefix. 20,000 matches: Name 120.1 / 107.5 ms and Modified
  122.7 / 110.1 ms for Select / Deselect, one range each.
- R3: a two-junction cycle reports WinError 1921 without navigating.
- R4: `..`, `.`, backslashes in `file://` input and UNC `..` normalize; literal
  `%20`, provider URLs and `file://C:` pass through unchanged.
- The clipboard teardown clears only a clipboard the test owns.

### Validation Results

- Unit/command gate with fatal-output rejection: 318 tests, OK, 20.1 s.
- Native Qt aggregate plus all of `FilterBarIT`, with fatal-output rejection: 106
  tests, OK, one expected symlink skip, 19.1 s. No fatal or traceback lines.
- Probes outside the repository: NumLock-off keypad keys with and without a
  filter; `_clipboard_location` on eight inputs.
- No source change, full suite, benchmark, freeze or package.

## Implementation Review 2 Resolutions

- **N1:** Require non-empty printable keypad text before routing it into the normal
   Filter Bar. Expanded the existing real-Controller regression to load generic and
   Windows Core bindings. Keypad Down, Up, Page Down, Page Up, Home, End and Insert
   now dispatch with empty text in both open and closed filter states. Tests verify
   actual Down movement and Insert marks as well as unchanged filter text. Printable
   `*`, `-`, `+`, ordinary punctuation, Space and pattern-mode editing still pass.
- **N2:** Initial `lstat` disappearance reports **The highlighted item no longer
   exists**. Missing paths during subsequent resolution/target checks retain
   **Broken link**. Unit tests distinguish all stages; the native deleted-highlight
   test verifies no navigation and no misleading broken-link message. Access errors,
   WinError 1921 cycles and normal junction-target navigation are unchanged.
- Updated Basics, Shortcuts and Core README. No new bindings, filesystem probes,
   preview-policy changes or separate fixes entry for these unreleased features.

### Validation

N1's extended test first failed on all seven empty-text keypad cases with an open
filter, then passed after the guard. N2's focused unit/native check passed five
tests. Final gates retained fatal/traceback-output rejection.

```powershell
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); result=subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','core.tests.commands.test___init__','core.tests.commands.test_unpack_archive','fman_unittest.test_favorites','fman_unittest.test_quick_view','fman_unittest.test_listing','fman_unittest.impl.test_filter_pattern','fman_unittest.impl.test_status_bar','fman_unittest.test_portable.PluginApiCompatibilityTest','fman_unittest.impl.plugins.test_plugin','fman_unittest.impl.plugins.test_key_bindings','fman_unittest.impl.plugins.test_context_menu','-q'],env=env,timeout=240,capture_output=True,text=True); output=result.stdout+result.stderr; print(output); sys.exit(result.returncode or int(any(marker in output for marker in ('Windows fatal exception','Fatal Python error','Traceback (most recent call last):'))))"
python -B -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='windows',QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'],'Fonts')); result=subprocess.run([sys.executable,'-B','-X','faulthandler','-m','unittest','fman_integrationtest.test_qt.RoadmapCommandsIT','fman_integrationtest.test_qt.PatternSelectionIT','fman_integrationtest.test_qt.FilterBarIT','fman_integrationtest.test_qt.SnapshotFilterBarIT','fman_integrationtest.test_qt.SortedFileSystemModelIT','fman_integrationtest.test_qt.ClipboardCommandsIT','fman_integrationtest.test_qt.CommandPaletteRecentIT','fman_integrationtest.impl.plugins.test_plugin.PluginTest','-q'],env=env,timeout=240,capture_output=True,text=True); output=result.stdout+result.stderr; print(output); sys.exit(result.returncode or int(any(marker in output for marker in ('Windows fatal exception','Fatal Python error','Traceback (most recent call last):'))))"
```

- Unit/command gate: **318 passed**, 20.968 s.
- Native gate including all FilterBarIT: **106 tests, 105 passed, one expected
   symlink-privilege skip**, 17.950 s; no fatal or traceback output.
- The first offscreen aggregate, launched alongside the other gates, timed out at
   180 seconds; its child was terminated. No cause was established. Isolated verbose
   FilterBarIT then passed **11 tests** in 0.575 s. A sequential verbose aggregate
   of RoadmapCommandsIT, PatternSelectionIT, FilterBarIT and ClipboardCommandsIT
   passed **33 tests, 32 passed and one expected skip**, in 6.320 s.
- The diagnostic replay used the same `build._environment()`, offscreen platform
   and Windows font directory. Child command:

```text
python -B -X faulthandler -c "import faulthandler, unittest; faulthandler.dump_traceback_later(30); unittest.main(module=None)" fman_integrationtest.test_qt.RoadmapCommandsIT fman_integrationtest.test_qt.PatternSelectionIT fman_integrationtest.test_qt.FilterBarIT fman_integrationtest.test_qt.ClipboardCommandsIT -v
```

The replay was bounded to 75 seconds, captured stdout/stderr, and rejected fatal,
traceback and 30-second timeout-dump markers. None occurred. This is not a claim
that the initial timeout's root cause was fixed. Expected Qt offscreen capability
notices only. Docs render and editor diagnostics pass. No full suite, freeze,
package installation or change to previous unverified native-mount limitations.
