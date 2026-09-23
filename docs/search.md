# Search and Find

Choose the smallest tool that fits the job.

## Filter This Pane

Start typing.

This hides non-matching names in the current pane.

| Query | Meaning |
| --- | --- |
| `report` | Contains `report` |
| `*.pdf` | Matches the glob |
| `^report` | Starts with `report` |
| `.py$` | Ends with `.py` |
| `!tmp` | Does not contain `tmp` |

Press ++esc++ to clear it.

## Find by Name

Press ++ctrl+f++ for the current folder.

Press ++ctrl+shift+f++ to include subfolders.

Results use fuzzy matching. Try `rpt pdf` to find `annual report.pdf`.

| Query | Meaning |
| --- | --- |
| `'report` | Exact text |
| `^src` | Starts with `src` |
| `.py$` | Ends with `.py` |
| `!tmp` | Exclude exact text |
| `report pdf` | Match both terms |

## Find with fd

Press ++shift+f7++.

Filter by name, extension, date, size, or type.

Use this for precise file-system searches.

## Search File Content

Press ++alt+f7++.

Search names and contents with Literal, Glob, or RegEx modes.

Leave the content field empty to search names only.

Search runs in the background. Use **Stop** to keep results collected so far.
