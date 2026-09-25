# Filesystem Link Operation Policy

Status: Proposed design, 2026-09-25. Requested after the implementation review in
[CodeReview003](CodeReview003.md). No policy implementation in this task yet;
review and approve the decisions below before changing operation behavior.

## Task

Make Copy, Move, Delete and Recycle predictable for Windows filesystem links:
**operate on the selected link, not on its target**. A directory link must never
silently turn into a recursive transfer or deletion of another tree. Preserve
ordinary-file performance and existing pane rendering.

## Scope

Included: local file/directory symbolic links, relative and dangling symlinks,
directory junctions, hardlinked regular files, destination collisions, nested
entries, same-volume rename and cross-volume transfer. Classify other reparse
points explicitly rather than assuming they are junctions. Shell `.lnk` and
Internet `.url` shortcuts remain ordinary files for these operations.

Excluded: link-creation commands, automatic relative-target rewriting, copying
target contents through a selected link, hardlink-topology preservation, archive
link round-tripping, volume mounting/unmounting, cloud-provider integration,
search/size traversal policy, and protection against hostile concurrent path
replacement. No global transaction across a directory transfer is promised.

Preserve public `fman` method signatures, current prompts for ordinary files,
portable settings, cancellation and queued Qt notifications. Third-party provider
semantics are not silently changed by local-filesystem helpers. No new setting,
timer, watcher, background scan or pane metadata column.

## Design

### User Policy

| Selected entry | Copy to absent destination | Same-volume Move | Cross-volume Move | Permanent Delete |
| --- | --- | --- | --- | --- |
| File or directory symlink | Recreate same type and stored target text | Rename link | Recreate and verify link, then remove source link | Remove link only |
| Supported directory junction | Recreate directory junction with same absolute target | Rename junction | Recreate and verify junction, then remove source junction | Remove junction only |
| Hardlinked regular file | Independent content copy, not another hardlink | Rename selected name | Existing regular-file copy/delete contract | Remove selected name only |
| `.lnk` / `.url` shortcut file | Ordinary file copy | Ordinary file rename | Ordinary file transfer | Ordinary file deletion |
| Volume mount point, unknown or unsupported reparse type | Refuse | Refuse | Refuse | Refuse |

Cloud placeholders are not symbolic links. In this first version, tagged cloud
entries also refuse these mutations unless a provider-specific path is separately
reviewed and tested. Never guess, implicitly hydrate, copy their reparse payload
as a symlink, or delete a cloud target. This conservative compatibility restriction
needs explicit approval, especially for users whose ordinary folders are cloud
backed. Renaming an ordinary parent folder does not require scanning its contents.

Recycle uses the existing Windows shell adapter only after link-only behavior is
proved for each supported type. If the shell cannot recycle that entry safely,
retain it and report the limitation; never fall back to permanent deletion.
Refuse volume mount points and unsupported reparse entries here too.

### Relative Links and Collisions

- Preserve relative target text verbatim. Moving a tree preserves its internal
  layout; automatically rebasing links could wrongly keep references into the old
  tree. Do not resolve the target, test its existence, or rewrite relative paths.
- A top-level relative symlink relocated to another parent gets one batch-level
  confirmation, default Cancel: its stored target remains unchanged and may refer
  elsewhere. No repeated warning for every nested link. Direct provider callers
  receive the same preservation semantics without a modal UI.
- Relative links escaping a copied tree can change meaning; document this rather
  than claim every link remains valid. Dangling links and cycles are valid link
  objects; recreate/delete them without walking their targets.
- If either source or existing destination is a symlink/junction, do not merge or
  overwrite in this first version. Offer Skip, another name or Cancel through the
  existing workflow. An earlier Yes-to-all for ordinary files does not authorize
  removing links or traversing their targets. Existing known-hardlinked overwrite
  targets retain CodeReview003's refusal.
- Current compatibility tightening: CodeReview003's shared merge guard already
  rejects source directory links for Copy as well as Move, and destination links
  for both. Keep this behavior: even a non-destructive target copy is implicit
  traversal rather than copying the selected link object. Native nested-junction
  and direct guard tests cover both commands. This does not imply that the broader
  absent-destination link-copy policy below is implemented.
- Resolve a selected entry's own name for self-operation checks, not its target.
  A link pointing at the source is not the source entry. Keep case-only rename
  behavior; detect dangling destinations with no-follow metadata, not `exists()`.
- Entering a directory link explicitly still navigates to that location. Later
  operations on selected children apply to those children. That differs from
  selecting the directory link itself or encountering it during an implicit merge.

### Ownership and Data Flow

1. [LocalFileSystem](../src/main/resources/base/Plugins/Core/core/fs/local/__init__.py)
   owns classification and mutation. Currently `_prepare_copy` asks `is_dir`
   before recognizing links; `_prepare_move` and `prepare_delete` have separate
   guards. Replace these decisions with one small private no-follow classifier.
   Do not change the global, target-following `is_dir` API used by navigation.
2. Reuse operation-time metadata where already available. On Windows, inspect
   entry-owned attributes/tag; read reparse payload only for tagged entries.
   Recognize symlink relative/directory flags and junction absolute target data.
   The mount-point tag alone is not sufficient to identify a directory junction:
   volume-root/volume-GUID or ambiguous payloads must be refused.
3. Keep native reparse decoding/creation in a small private Windows helper, using
   existing ctypes/pywin32 and documented no-follow handle APIs. No shelling out to
   `mklink`, package installation, elevation, Registry writes or subprocess per
   entry. Validate payload lengths/tags before use and close handles on every path.
4. [FileTreeOperation](../src/main/resources/base/Plugins/Core/core/fileoperations.py)
   must classify local sources and destinations before directory merge, overwrite
   prompts or followed-path parent checks. Reuse the local classifier, not duplicate
   tag logic. Unknown nonlocal providers continue through their existing contract.
   Provider-level guards remain authoritative for direct plug-in calls.
5. Use an immutable, task-local link descriptor: own type, directory flag, raw
   target/relative flag, and available entry identity. It is not a pane cache or
   proof that a later pathname still names the same entry. Ordinary entries must
   not allocate reparse descriptors or perform target resolution.
6. Planning may classify without target I/O. Execution rechecks selected links
   before mutation; descriptor comparison verifies the entry itself, not content
   or metadata obtained by following it. Keep Qt access through existing Task and
   notification boundaries; workers handle only native paths and plain data.

### Mutation and Failure Rules

Copy creates a supported link at an owned unique sibling name, reads back its
descriptor without following it, then publishes without replacing a competing
destination. Preserve file versus directory symlink type even for dangling links.
Junction creation uses its native mount-point payload, not `os.symlink` as a
substitute. If the destination volume or permissions cannot support that type,
fail with the source and previous destination untouched.

Recreated links inherit destination-parent permissions. Do not copy target ACLs,
streams or attributes; exact cloning of the source link's own security/timestamps
is outside this first version. Rename retains the existing object's metadata.

Same-volume Move uses a non-replacing native rename, preserving the object and
link text. Handle actual cross-device errors rather than trusting zero/equal
device fields as proof that rename will work. Case-only rename must not overwrite
an unrelated entry. Do not enumerate a directory link before deciding to rename.

Cross-volume Move is one compound task: create, verify, publish, check cancellation
and source-entry identity, then unlink/rmdir the source link itself. Do not enqueue
independent create and delete tasks. If source identity cannot be checked reliably,
refuse source deletion rather than treating two zero IDs as equal. If publication
already succeeded, retain both entries and say "Copied; source retained" on
cancellation, source change or deletion failure. Never delete a published output
to disguise a partial move. Clean only unpublished staging owned by this task.

For recursive operations, symlinks/junctions are leaf entries. Do not descend into
them, including inside a real source directory or existing destination tree.
Only remove source parent directories when actually empty. A later failure does
not roll back earlier completed entries; progress and Continue/Skip stay truthful.

No chmod-through-link retry. For read-only hardlinked regular files, do not clear
shared attributes automatically just to delete one name; report the refusal.
Unknown identity cannot establish every hardlink alias; retain the documented
resolved-path fallback limits, not a false guarantee of complete alias detection.

Archive providers and [Pack/Unpack](../src/main/resources/base/Plugins/Core/core/fs/zip.py)
must refuse selected or nested link/reparse entries before calling an external
recursive packer that could follow them. Reuse existing transfer gathering or
archive preflight; this may require an archive-only walk where none exists today.
Do not claim links were preserved in ZIP without explicit round-trip support.
Keep local-to-archive Move disabled and existing archive-out verification intact.

### Persistence

Not applicable: this is a fixed operation policy with no saved preferences or
migration. Update [Core usage](../src/main/resources/base/Plugins/Core/README.md),
[README](../README.md), [archive usage](../docs/archives.md) and the changelog only
when the policy is implemented. Errors identify the operation, link and retained
source/output, without claiming target validity.

## Alternatives

- Follow targets as regular files/directories: rejected for deletion risk, cycles,
  unexpected large transfers, network access and ambiguous recursive semantics.
- Rebase relative links to preserve their old absolute target: rejected as the
  default because it changes the link object and breaks relocatable tree copies.
- Refuse every link operation: simplest but prevents useful rename/delete/copy
  workflows. Refuse unsupported types and collisions instead.
- Implement transactional replacement of every link kind immediately: deferred;
  absent-destination copy plus rename covers the common workflow without unsafe
  unlink-before-create or a new general transaction framework.
- Treat every reparse point as a junction: rejected; mount points and cloud/provider
  data have distinct lifecycle rules. Broader cloud support needs its own evidence.

## Runtime Effects

- Startup, first pane paint and idle: zero policy-specific jobs, I/O, timers,
  recurring signals or scans. No work until an operation requests classification.
- Ordinary copy/move/delete: reuse existing own-entry metadata and replace redundant
  predicates where possible. Do not add hidden-attribute calls, global alias maps,
  target probes or an extra tree walk to ordinary local transfers.
- Link operations: bounded payload reads and native calls per selected link,
  independent of target-tree size; no target content reads or cycle traversal.
  Recursive ordinary-tree enumeration remains necessary for copying/deleting it.
- Memory: constant per link task/descriptor, bounded by existing task gathering;
  no persistent link index. Existing worker threads and cancellation only.
- Archive preflight can add one source-tree traversal; measure and disclose it,
  cancel between entries and never include this work in pane loading.
- There is no optional toggle. The no-op path is browsing/idle and ordinary entries
  that require no link payload. No automatic retries, capability scans or elevation.
- Copy retains source data; cross-volume Move checks cancellation before source
  removal. Native calls are not forcibly interrupted, and hostile races or
  crash/power-loss recovery remain outside this task's guarantee.

## Tests

Extend existing tests, not normal-suite benchmark tooling. Use the existing
interpreter and `build._environment()`; no new environment or packages.

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_local', 'core.tests.test_fileoperations', 'core.tests.fs.test_zip'], env=build._environment(), timeout=180).returncode)"
```

Add a focused `LinkOperationsIT` group to the existing
[Qt harness](../src/integrationtest/python/fman_integrationtest/test_qt.py).
The following gate is for implementation, not runnable until that group exists:

```powershell
python -c "import build, os, subprocess, sys; env=build._environment(); env.update(QT_QPA_PLATFORM='offscreen', QT_QPA_FONTDIR=os.path.join(os.environ['WINDIR'], 'Fonts')); sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'fman_integrationtest.test_qt.LinkOperationsIT', 'fman_integrationtest.test_qt.ArchiveTransferIT'], env=env, timeout=180).returncode)"
```

- Unit: classification from own attributes/tag, malformed/unsupported payloads,
  relative/directory flags, unknown identity and collision/Skip/Yes-to-all rules.
  Instrument filesystem calls: no target traversal, payload reads for regular
  files, extra staging attributes or repeated ordinary-file metadata queries.
- Native integration: file/directory symlinks, absolute/relative/dangling/cyclic
  links, junctions, ordinary files, hardlink pairs and shortcut files. Cover each
  matrix operation directly and through CopyFiles/MoveFiles, selected and nested,
  empty/existing/dangling destinations and case-only rename. Assert target-tree
  fingerprints unchanged; link kind and stored target survive recreation.
- Failure regression: create/readback/publish/delete failure, canceled compound
  move, competing creator, changed source descriptor, unknown IDs and no privilege.
  Assert no source deletion after failure and no success notification before it.
- Qt integration: test the single relative-link confirmation and Skip/Cancel on
  the Qt thread in `LinkOperationsIT`; test navigation into a link separately from
  operating on it. Include the archive gate above when guarding external traversal.
  Record exact methods and results at implementation time.
- Manual release checks: real second-volume link moves; NTFS/ReFS and unsupported
  volumes; UNC targets that are offline; non-elevated versus Developer Mode link
  creation; shell Recycle and restore for both symlinks and junctions. Do not
  create/delete real volume mounts; verify refusal with controlled metadata and
  read-only inspection of an existing mount if available. Cloud refusal must be
  validated before claiming provider support. Record privileged skips as unverified.
- Performance: baseline/current alternating runs of 1,000 ordinary 4 KiB copies
  and overwrites, nine repetitions per side, disposable local fixtures; report
  medians/ranges and metadata-call counts, not raw samples. Run the same procedure
  on an available network fixture before claiming its cost is negligible. No
  additional regular-file round trips or target-size-dependent link costs accepted
  without explicit design revision. This proposed opt-in transfer check is separate
  from the existing catalog; preserve its measurement method and repetitions.
  Run `python build.py measure` only when explicitly
  authorized; no automatic full suite, build, clean or freeze.

## Implementation Steps

1. Review/approve the policy matrix, raw relative-target preservation, collision
   refusal, cloud restriction and required native checks. Add failing tests for
   current directory-link recursion and command-level classification first.
2. Implement the small private classifier/native adapter with unit and native
   descriptor round-trip tests. Prove regular-file call budgets before integration.
3. Route local copy/delete/same-volume rename through the classifier and make
   directory links leaf entries. Keep provider methods independently safe.
4. Integrate command collision handling, one relative-link warning, compound
   cross-volume moves and accurate partial-success errors; verify cancellation.
5. Gate shell Recycle and archive traversal. Preserve source/archive on every
   refused or failed path; complete the manual matrix for supported types.
6. Run focused regression and agreed performance gates, update usage/changelog,
   append implementation/validation records and seek acceptance before completion.

## Acceptance Criteria

- Supported symlink/junction operations never read or alter target contents, even
  for directory links, dangling/cyclic links or implicit directory merges.
- Recreation preserves stored target text/type; relative-link relocation is
  documented and the top-level warning is shown once per applicable batch.
- Cross-volume Move never deletes source after create/verify/publish failure or
  cancellation; retained duplicate output is reported clearly.
- Collisions, volume mounts, unsupported reparse types and unsupported privileges
  refuse explicitly without silently following targets or escalating permissions.
- Hardlinks and shortcut files obey their distinct matrix rows; Recycle does not
  become permanent deletion on failure.
- No new pane-loading/idle work or unnecessary ordinary-transfer metadata calls.
  Focused tests pass; native/manual gaps and measured transfer costs are recorded.
- No public API signature break, new packages, Registry writes or automatic target
  rewriting. Documentation states limits instead of promising all edge cases vanish.

## Reviewers

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context Window: Not exposed by host
- Outcome: Proposed a local link-object policy, preserving relative text and
  refusing collisions/unsupported types. Grounded ownership in local preparation,
  command merge, shell trash and archive boundaries. Requires review before
  implementation, especially cloud compatibility, relative warnings and native
  recreation/Recycle behavior; no link policy implemented or certified here.

### 2026_09_25 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Retained the existing source/destination directory-link merge refusal
  for both Copy and Move, explicitly documenting the compatibility tightening
  raised by the latest CodeReview003 review. Expanded existing direct and native
  nested-junction tests; focused seven-test transfer-error gate passed. The
  broader link policy remains design-only and requires approval.