# Self-Contained ZIP Tests

## Task

Fix release CI failures caused by the ignored and untracked
`ZipFileSystemTest.zip` fixture by making the ZIP filesystem tests create their
own deterministic archive.

## Scope

Included: replace the external fixture dependency with a temporary ZIP having
the same directory layout, Unicode filename, text files, and 2017-11-08
timestamps expected by the tests. Accept the optional fractional seconds that
7-Zip 26.03 emits in archive metadata, and use deterministic UTF-8 output for
Unicode archive paths on Windows runners.

Excluded: changes to archive formats, `.gitignore`, or the public `fman`
plug-in API.

Compatibility: preserves the public `fman` plug-in API from fman 1.7.5.

## Design

`ZipFileSystemTest.setUp` creates the fixture inside its existing temporary
directory using Python's standard `zipfile` API. Each test continues to receive
a private mutable copy, while clean Git checkouts no longer depend on an
ignored binary file. The archive is small, synchronous, and removed by the
existing teardown.

The Windows 7-Zip wrapper requests UTF-8 console output and decodes it as UTF-8.
This avoids dependence on Python's process-wide locale or UTF-8 mode while
preserving Unicode archive names.

## Alternatives

- Unignore and commit the ZIP: rejected because a generated fixture is easier
  to review and cannot be omitted accidentally from a source checkout.
- Generate the fixture in CI: rejected because local and CI tests should use
  the same self-contained setup.

## Runtime Effects

Application runtime is unchanged. ZIP tests perform a few small in-memory/file
writes during setup; there are no background jobs, persistent I/O, or disabled
paths.

## Tests

```powershell
python -m unittest core.tests.fs.test_zip
python -m py_compile src/main/resources/base/Plugins/Core/core/tests/fs/test_zip.py
git diff --check
```

The focused module covers archive traversal, metadata, extraction, mutation,
copy, and move operations using the generated fixture.

## Implementation Steps

1. Generate the deterministic archive in `ZipFileSystemTest.setUp`.
2. Parse whole-second and fractional-second 7-Zip timestamps.
3. Make Windows 7-Zip output encoding deterministic.
4. Run the focused ZIP filesystem tests.
5. Update the changelog and completion records.

## Acceptance Criteria

- A clean checkout contains everything needed to run the ZIP tests.
- The focused ZIP filesystem test module passes without
  `ZipFileSystemTest.zip` in the source tree.
- ZIP metadata timestamps with fractional seconds are accepted.
- Unicode archive names are decoded consistently on Windows and CI.
- Application and plug-in APIs are unchanged.

## Reviewers

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Low
- Context window: Not exposed by host
- Outcome: Approved self-contained deterministic fixture generation as the
  smallest fix for clean-checkout CI failures.

### 2026_09_13 - GitHub Copilot

- Role: Reviewer
- Activity: Review
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Confirmed that `-sccWIN` output conflicted with the runner's UTF-8
  Python mode and approved explicit UTF-8 output and decoding.

## Implementer

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Replaced the ignored ZIP fixture with deterministic per-test
  generation and updated metadata parsing for 7-Zip 26.03 fractional seconds.

### 2026_09_13 - GitHub Copilot

- Role: Implementer
- Activity: Implementation
- Agent: GitHub Copilot
- Model: Not exposed by host
- Effort: Medium
- Context window: Not exposed by host
- Outcome: Made Windows 7-Zip request and decode UTF-8 output consistently,
  preventing locale-dependent failures for Unicode archive names.

## Validation Results

- `python -m unittest core.tests.fs.test_zip.ZipFileSystemTest`: passed 46
  tests.
- `python -m unittest core.tests.fs.test_zip`: passed all 47 tests, including
  the real `7za.exe` smoke test.
- VS Code diagnostics reported no errors in the changed source, tests, or task
  files.
- The full `python build.py test` suite was not run, in accordance with the
  repository policy requiring explicit user request.
- `PYTHONUTF8=1 python -m unittest core.tests.fs.test_zip`: passed all 48 tests,
  including Unicode archive operations and the real `7za.exe` smoke test.