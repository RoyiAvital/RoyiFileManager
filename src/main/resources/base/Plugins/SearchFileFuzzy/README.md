# SearchFileFuzzy

Searches files from the active pane without modifying the pane's file model or
the main window. Local searches build a fresh index with `os.scandir` for every
invocation, so changes made by other programs are reflected in the results.
Other filesystem schemes use the public fman filesystem API.

## Commands

- `Ctrl+F`: Search files in the current folder.
- `Ctrl+Shift+F`: Search files recursively using breadth-first traversal.

Selecting a result opens its containing folder and places the cursor on the
file. Directories are traversed but are not included in the results. Unreadable
directories are skipped. Recursive local searches do not follow directory
symbolic links or junctions.

Searches are case-insensitive. When hidden entries are disabled, hidden
directories are pruned together with all of their descendants.

## Query Syntax

Fuzzy mode supports [fzf extended-search syntax](https://github.com/junegunn/fzf#search-syntax).
Matching terms are highlighted in the displayed relative path.

| Query | Meaning |
| --- | --- |
| `report pdf` | Both fuzzy terms must match |
| `'report` | Exact substring |
| `^src` | Relative path starts with `src` |
| `.py$` | Relative path ends with `.py` |
| `^report.txt$` | Entire relative path matches |
| `!tmp` | Exclude an exact substring |
| `!^src`, `!.py$`, `!^report.txt$` | Negated anchors |
| `!'rpt` | Exclude a fuzzy subsequence |
| `'word'`, `!'word'` | Require or exclude an exact word; underscore is a boundary |
| `^src .py$ \| .rb$` | Require `^src` AND either suffix |
| `'annual\ report` | Exact phrase containing a space |

Only standalone `|` joins adjacent alternatives; there are no parentheses.
Backslash escapes spaces only. Other backslashes are literal, so
`^src\core` searches the displayed Windows-style path. Quote a leading marker
to search for it literally, for example `'!important` or `'^draft`.
Interior markers are literal; `$` alone is also literal. A leading quote
overrides a trailing anchor (`'file$` means exact `file`, as in fzf).
Anchors ignore surrounding whitespace unless explicitly included using `\ `.
Empty operator terms such as `!`, `'` or `^$` are ignored while typing.

Compatibility covers fzf's extended-query operators, not its score or ranking.
Search stays case-insensitive (equivalent to fzf's `--ignore-case` option).
Ordinary fuzzy queries retain the existing separator/camel-case normalization
and ranking. Extended queries preserve punctuation and spaces for matching,
including inside a single fuzzy term with escaped spaces; anchors apply to the
whole relative path, not independently to its basename. Both paths use NFKC
and Unicode case folding, which differ from fzf's Unicode normalization.
Exact/anchor/inverse-only queries retain index order. `regular` mode keeps its
existing normalized substring behavior and does not interpret these operators.
No fzf executable runs in the application.

## Examples And Use Cases

Use `Ctrl+Shift+F` for examples spanning subfolders. All paths below are
relative to the active pane's folder; terms are case-insensitive.

| Goal | Query | Example result or exclusion |
| --- | --- | --- |
| Find a PDF report using initials | `rpt pdf` | Finds `docs\annual report.pdf` with ordinary fuzzy matching |
| Find PDF reports outside temporary paths | `'report .pdf$ !tmp` | Keeps `docs\annual report.pdf`; excludes `tmp\report.pdf` |
| Find Python or Ruby source files, excluding tests | `^src .py$ \| .rb$ !test` | Keeps `src\core.py` and `src\tools\build.rb`; excludes paths containing `test` |
| Match a phrase with an actual space | `'annual\ report .pdf$` | Finds `docs\annual report.pdf`, not `docs\annual-report.pdf` |
| Find one exact relative path | `^src\core.py$` | Finds `src\core.py`, not `docs\core.py` or `src\core.pyc` |
| Match a whole word in text filenames | `'report' .txt$` | Finds `report_notes.txt`, not `annualreport.txt` |
| Exclude a fuzzy subsequence | `.txt$ !'bkp` | Removes `backup.txt` and any other path containing `b`, `k`, `p` in order |
| Search a filename starting with `!` | `'!important` | Finds `!important.txt` without treating `!` as negation |
| Find a README at the search root only | `^README.md$` | Finds `README.md`, not `docs\README.md` |

In the source-file example, `^src` AND (`.py$` OR `.rb$`) AND `!test` must
all succeed. `^src` is a text prefix, so it also includes `src-old\core.py`.
Negation checks the entire relative path, not just the filename. No switch
or second dialog is needed: ordinary queries keep the existing fuzzy behavior;
operators refine a query when needed. This syntax does not provide regex,
wildcards or date/size filters.

## Performance

Ordinary queries keep the previous per-file matcher and ranking; they do not
run the extended-query parser. Highlights add a small amount of work for the
returned results (at most 100 with the default settings). Extended queries
are parsed once per update, then their conditions are evaluated per file.

Measured **additional time per query**, compared with the old matcher, on a
synthetic Windows index with 100 returned results:

| Indexed files | Ordinary queries | Broad queries using operators |
| ---: | ---: | ---: |
| 1,000 | About 1-1.5 ms | About 1.5-2 ms |
| 10,000 | About 1-1.5 ms | About 6-8 ms |
| 50,000 | About 1-2.5 ms | About 30-40 ms |

The operator comparisons used `report !missing`, `rpt !missing` and `^src rpt`
on paths where the added condition rejected nothing. Every comparison returned
the same files in the same order. These are warm paired measurements from
2026-09-18, not guarantees for every machine, path length or query.

These numbers are overhead, not total search time. In the 50,000-file fixture,
ordinary `report py` already took about 162 ms before this feature and about
164 ms including highlights. Broad fuzzy queries can therefore still pause
typing on large indexes. Filters that eliminate candidates can reduce the
total cost instead; literal-only queries such as `'report` or `.py$` returned
the first 100 matches in about 1 ms, while literal no-match scans took 6-10 ms.

Preparing the extra path cache once when opening a 50,000-file search added
about **6 ms and 3.7 MiB**. Filesystem indexing is separate and is not included
in these timings. fzf itself is not launched during a search.

## Focused Tests

From the repository root in the existing development environment:

```powershell
$env:PYTHONPATH="src/main/python;src/unittest/python;src/integrationtest/python;src/main/resources/base/Plugins/Core;src/main/resources/base/Plugins/SearchFileFuzzy"
python -m unittest fman_unittest.test_search_file_fuzzy
```

Offline tests include fixed syntax expectations. To compare match sets with
the installed fzf (no version pin; its version is printed):

```powershell
$env:FZF_REFERENCE_TESTS="1"
try { python -m unittest fman_unittest.test_search_file_fuzzy.FzfReferenceTest }
finally { Remove-Item Env:FZF_REFERENCE_TESTS }
```

The reference check requires `fzf` on `PATH`, ignores user fzf defaults, uses
UTF-8 NUL-separated input/output and fails on a mismatch or missing executable.
It never downloads or installs anything. Timing and memory measurements are
opt-in via `SEARCH_PERFORMANCE_TESTS=1` and the `SearchPerformanceTest` class.

```powershell
$env:SEARCH_PERFORMANCE_TESTS="1"
try { python -m unittest fman_unittest.test_search_file_fuzzy.SearchPerformanceTest }
finally { Remove-Item Env:SEARCH_PERFORMANCE_TESTS }
```

## Settings

The defaults are stored in `SearchFileFuzzy.json`:

```json
{
	"mode": "fuzzy",
	"max_recursive_entries": 50000,
	"max_results": 100,
	"include_hidden": true
}
```

Create
`UserSettings/Plugins/User/Settings/SearchFileFuzzy.json` to override individual
values without changing the bundled plug-in. Set `mode` to `fuzzy` for
subsequence matching or `regular` for normalized, case-insensitive substring
matching. `max_recursive_entries` bounds the number of files and directories
inspected during either search command. `max_results` bounds the quicksearch
results. When `include_hidden` is false, dot-prefixed and Windows-hidden entries
are excluded, including entire hidden directory trees.

The commands also accept an optional `mode` argument from custom key bindings,
which overrides the configured mode for that invocation.