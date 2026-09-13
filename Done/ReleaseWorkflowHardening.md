# Release Workflow Hardening

## Task

Make GitHub release builds reproducible and resistant to accidental or
compromised publication. Verify downloaded 7-Zip tools, enforce the documented
tag policy, prevent replacement of an existing release, and keep manual runs
usable as non-publishing dry runs.

## Scope

Included:

- Pin the official 7-Zip 26.03 GitHub release URLs and SHA-256 digests for
  `7zr.exe`, `7z2603-extra.7z`, and the extracted x64 `7za.exe`.
- Pin GitHub Actions to reviewed commit SHAs and use supported action versions.
- Separate read-only build permissions from release publication permissions.
- Require annotated tags whose names exactly match the SemVer build version.
- Refuse to update or overwrite an existing GitHub release.
- Make `workflow_dispatch` build and upload artifacts without requiring a
  prepared versioned changelog section.
- Reject all substantive content left under `Unreleased` for tagged releases.
- Keep CI builds on the committed conda lock without regenerating it from file
  timestamps.
- Close downloaded files and allow a short Windows settling interval before
  checksum verification.
- Refetch the pushed tag before checking that it is annotated, preserve package
  command failures, and forbid GitHub CLI from creating a missing tag.

Excluded:

- Code signing and GitHub artifact attestations.
- Publishing installers or platforms other than the existing Windows ZIP.
- Changes to application runtime behavior or the public `fman` plug-in API.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5.

## Design

`build.py` owns download integrity. `_download` streams each response through
SHA-256, deletes a mismatched file, and fails before executing it. `_ensure_7za`
also validates an existing destination and the extracted x64 payload, ensuring
the packaged executable is the reviewed 26.03 binary. Versioned GitHub release
URLs avoid the mutable unversioned 7-zip.org bootstrap URL.

The workflow has a read-only build job and a tag-only publication job. The
build job validates SemVer, verifies annotated tag objects, runs tests, freezes,
packages, hashes, and uploads one artifact. Manual dispatch extracts
`Unreleased` notes for audit but never publishes. The publication job downloads
the artifact, fails if the tag already has a release, and creates the release
with GitHub CLI using the job's narrowly scoped `contents: write` token.

The release-notes helper treats `Unreleased` as empty only when its body contains
the required API compatibility statement and whitespace. It has an explicit
dry-run mode that extracts the current `Unreleased` section without applying
the tagged-release empty check.

Failure behavior is fail-closed: checksum mismatch, malformed version,
lightweight tag, stale changelog, missing artifact, or existing release stops
publication.

CI accepts the committed `conda-lock.yml` as the build input and fails when it
is absent; it never regenerates the lock. Local builds retain the timestamp
based convenience behavior. Downloads are closed before a brief settling delay
and checksum verification so buffered writes are complete on Windows.

## Alternatives

- Commit `7za.exe`: rejected because repository policy ignores binaries and a
  verified versioned download keeps source history smaller.
- Keep `softprops/action-gh-release`: rejected because GitHub CLI is already on
  hosted runners and makes the no-overwrite policy explicit.
- Grant write permission to the combined build job: rejected because tests and
  downloaded build tools do not need release privileges.
- Permit release reruns to overwrite assets: rejected because one tag/version
  must identify immutable binaries.

## Runtime Effects

Application startup, steady-state CPU/memory, threading, I/O, cancellation, and
disabled paths are unchanged. Build commands perform SHA-256 while downloading
about 2.4 MB and once over the extracted 1.3 MB executable. Release CI adds one
artifact download and one GitHub release-existence query.

## Tests

Focused commands:

```powershell
python -m unittest fman_unittest.test_release_support
python -m py_compile build.py .github/scripts/release_notes.py
python .github/scripts/release_notes.py --version 0.2.0 --dry-run --output target/release-notes-review.md
git diff --check
```

Tests cover accepted and rejected hashes, cleanup after mismatch, existing
binary validation, versioned URLs, release-section extraction, strict empty
`Unreleased` validation, and dry-run extraction. Static workflow assertions
cover immutable action pins, split permissions, annotated-tag validation,
existing-release refusal, and tag-only publication.

Follow-up tests cover the download settling delay, immutable CI lock handling,
explicit remote tag fetching, package exit-code propagation, and
`gh release create --verify-tag`.

Manual release validation: run `workflow_dispatch` and inspect its ZIP/hash;
then create an annotated matching test tag in a disposable repository and
confirm a second run refuses to replace the release.

## Implementation Steps

1. Add SHA-256 verification and versioned GitHub URLs to `build.py`.
2. Tighten and extend the release-notes helper for strict and dry-run modes.
3. Split and pin the GitHub Actions workflow and enforce release invariants.
4. Add focused tests for build, helper, and workflow behavior.
5. Update the changelog, record validation, and complete this task document.

## Acceptance Criteria

- Clean builds execute only 7-Zip files matching all pinned SHA-256 values.
- Manual dispatch builds artifacts but cannot publish a release.
- Only an annotated tag exactly matching a valid SemVer build version publishes.
- Existing releases and assets are never modified by the workflow.
- Build steps have read-only repository permission; only publication has write.
- `Unreleased` prose, headings, or bullets block a tagged release.
- Focused tests and syntax checks pass.
- CI does not rewrite `conda-lock.yml`, and downloaded files are closed before
  their settling delay and checksum verification.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context window: Not exposed by host
- Outcome: Approved a fail-closed design using pinned downloads and actions,
  split permissions, immutable releases, and focused regression coverage.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Accepted the CI lock, explicit tag fetch, package failure,
  `--verify-tag`, and Windows file-settling findings; kept approvals and
  provenance attestations outside this focused correction.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: High
- Context window: Not exposed by host
- Outcome: Implemented verified 7-Zip retrieval, immutable action pins,
  read-only builds, annotated-tag enforcement, no-overwrite publication,
  strict release-note validation, manual dry runs, and regression tests.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Prevented CI lock regeneration, closed and settled Windows
  downloads before hashing, made annotated-tag verification robust, preserved
  packaging failures, and required publication to use an existing tag.

## Validation Results

- `python -m unittest fman_unittest.test_release_support`: passed 9 tests.
- `python -m py_compile build.py .github/scripts/release_notes.py`: passed.
- `python .github/scripts/release_notes.py --version 0.2.0 --dry-run --output target/release-notes-review.md`:
  passed and generated notes from `Unreleased`.
- The real `_ensure_7za()` path rejected the stale local executable, downloaded
  the pinned 26.03 assets, and installed an x64 `7za.exe` with SHA-256
  `edbee35370e14030e4c785cf88200f42dc651c1eb4217c1e3963c38a12f099b0`.
- `git diff --check`: passed; Git reported only line-ending warnings for
  unrelated pre-existing Core changes.
- VS Code diagnostics reported no errors in the changed build, helper,
  workflow, or test files.
- `actionlint` was unavailable. Hosted `workflow_dispatch` and disposable-tag
  publication checks require GitHub execution and were not run locally.
- The full `python build.py test` suite was not run, in accordance with the
  repository policy requiring explicit user request.

Follow-up validation:

- `python -m unittest fman_unittest.test_release_support`: passed 11 tests.
- The workflow parsed successfully as YAML after the tag, package, and
  publication corrections.