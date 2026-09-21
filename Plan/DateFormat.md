# Date Format

Status: Design only; review before implementation. Independent of
[PaneRendering001.md](../Done/PaneRendering001.md).

## Task

Allow pane dates to use either the current locale format or a fixed ISO-date,
24-hour format. Resolve the pattern once instead of discovering and rewriting
it for every Modified cell. Locale remains the default for compatibility.

This supersedes the earlier ISO-only proposal recorded in PaneRendering001;
that task now covers hidden-attribute optimization only.

## Scope

Included: one Core configuration value, the built-in Modified column, focused
tests and usage documentation. Applies wherever panes use `core.Modified`,
including nonlocal filesystem providers.

Excluded: hidden-file optimization, scanning/stat changes, new settings UI,
live switching, global Qt locale changes, custom format strings, timezone
selection, search-result formatting and third-party plug-in strings. Existing
search metadata and date inputs retain their ISO formats.

Compatibility: preserve the public `fman` plug-in API, Modified constructor
signature, datetime values, sort keys, filesystem calls and error behavior.
Only opting into ISO changes the existing pane date presentation.

## Design

### Configuration and Ownership

Add `date_time_format` to
[Core Settings.json](../src/main/resources/base/Plugins/Core/Core%20Settings.json):

```json
{
  "date_time_format": "locale"
}
```

- `locale`: current `QLocale().dateTimeFormat(QLocale.ShortFormat)` with the
  existing `yyyy` to `yy` replacement. Preserve locale order and 12/24-hour
  convention exactly rather than defining a new localized format.
- `iso`: fixed Qt pattern `yyyy-MM-dd HH:mm`, for example `2026-09-21 17:05`.
  Four-digit year, zero-padded fields, local 24-hour time, no AM/PM. Minute display
  precision does not truncate the underlying timestamp or sort value.
- Missing or unsupported setting values select `locale`. Keep malformed-file
  handling with the existing configuration loader; do not add a retry loop or
  silently rewrite the user's file.

Use the existing `load_json` configuration merge. Overrides belong in the user's
Core settings under `UserSettings`, not the bundled default. No automatic save,
configuration migration or Registry writes.

### Data Flow and Lifetime

At [Modified](../src/main/resources/base/Plugins/Core/core/__init__.py) instance
initialization, read the setting once and resolve one immutable format string.
ISO does not query the locale; Locale discovers and rewrites the pattern once.
Each `get_str` reuses that string, retaining the current timestamp conversion,
`QDateTime`, local-time interpretation and empty/error handling.

Settings and OS locale changes take effect after an application restart. A pane
refresh alone does not promise a configuration reload. This avoids new lifecycle
hooks, cache invalidation, mixed formats during a load and per-row configuration
checks. Do not introduce a shared formatting service for other plug-ins.

Threading remains unchanged: row preparation reads immutable state and no Qt
widgets move threads. Persistence uses the existing settings mechanism; there is
no new metadata cache. Cancellation is not applicable to this bounded formatting
operation; existing model cancellation stays unchanged.

## Alternatives

- **ISO only:** superseded by the user's request for a Locale/ISO choice.
- **Resolve the locale on every cell:** current behavior; unnecessary repeated
  configuration/format work once the selected mode is stable.
- **Live switching or reload hooks:** deferred; restart application is sufficient
  for this small configuration feature and avoids model-wide coordination.
- **Direct Python datetime formatting:** deferred to preserve current conversion,
  timezone and invalid-timestamp behavior.
- **Make all bundled views switch modes:** deferred; search/date-input formats
  already use ISO and do not need to change with pane presentation.

## Runtime Effects

- Startup: one settings lookup and pattern resolution per Modified instance.
  Locale may query Qt once; ISO uses a fixed string.
- Steady-state CPU: both modes remove per-row locale discovery and year rewriting.
  Timestamp conversion and string formatting remain; quantify, do not assume,
  the performance benefit.
- Memory: one small immutable pattern per column instance, no per-file cache.
- I/O: only normal settings loading, no extra filesystem metadata reads or writes.
- No workers, processes, timers, subscriptions or new cancellation work.
- Default/no-op path: absent setting preserves Locale output. ISO adds no locale
  lookup, and neither mode performs per-row configuration work.

## Tests

Extend [core.tests.fs.test_columns](../src/main/resources/base/Plugins/Core/core/tests/fs/test_columns.py):

- Default, explicit `locale`, `iso`, missing and invalid setting values.
- Locale output matches the original Qt short-format/year-replacement expression
  under 12-hour and day-first locales. Restore Qt locale after each test.
- ISO output is identical across locales: midnight `00:00`, noon `12:00`,
  afternoon `17:05`, `23:59`, zero padding, year boundaries and leap day.
- Configuration read once per instance; Locale format resolved once, ISO never
  resolves it. Repeated rows reuse the pattern. A newly initialized instance
  observes changed settings; existing instances retain their snapshot.
- Unchanged `None`, `OSError`, invalid-timestamp handling, local-time conversion,
  sort precision and metadata-query counts. Existing Name/Size tests still pass.

Focused command from the application environment:

```powershell
python -c "import build, subprocess, sys; sys.exit(subprocess.run([sys.executable, '-m', 'unittest', 'core.tests.fs.test_columns', '-q'], env=build._environment(), timeout=60).returncode)"
```

Run the new failing Modified test before and immediately after its implementation,
then the full column module. No automatic full suite or clean/freeze/package.

Integration/manual: with disposable settings, launch both panes in each mode,
inspect a local folder and an archive, sort Modified in both directions, refresh
and navigate. Restart after editing the setting and verify both panes adopt it.
Check readable column sizing and 12/24-hour locale cases without automatically
changing OS settings. Search-result and date-input formats must remain unchanged.

Performance: compare the original formatter with both modes using identical
datetime values. Count format/configuration calls and report elapsed time; no
wall-clock speed assertions in unit tests or claim of solving pane stalls.

## Implementation Steps

1. Review the restart-only configuration contract and add focused failing tests.
2. Add the default setting and immutable Modified format snapshot. Run the failing
   case immediately, then the full column module.
3. Run startup/restart and manual checks with isolated settings; measure formatting
   cost without changing scan behavior.
4. Document the setting, modes, default and restart requirement in README/Core
   usage docs and the implemented application change in CHANGELOG.
5. Record implementation/validation results, then move this canonical task to Done
   and its index link to Completed when its independent acceptance gates pass.

## Acceptance Criteria

- Locale is the default and preserves current pane date output.
- ISO produces `YYYY-MM-DD HH:mm`, using local 24-hour time independent of locale.
- Neither mode queries settings or resolves locale patterns per row.
- Restart reliably applies mode changes; invalid values fall back to Locale.
- Datetime precision, sorting, filesystem queries, errors and public API stay intact.
- Focused tests and startup/restart checks pass; documentation describes the actual
  behavior. Hidden optimization and unrelated date surfaces are unchanged.

## Reviewers

### 2026_09_21 - GitHub Copilot

- Role: Reviewer
- Activity: Design
- Agent: GitHub Copilot
- Model: GPT-6 Astra
- Effort: Medium
- Context Window: Not exposed by host
- Outcome: Separated pane date formatting from hidden optimization at the user's
  request. Defined Locale default, optional ISO, startup-resolved pattern and
  focused tests. Supersedes the earlier ISO-only scope without rewriting its
  historical records. Design only; no application changes.