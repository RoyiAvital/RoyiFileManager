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

## Find with `fd`

Press ++shift+f7++.

Filter by name, extension, date, size, or type.

Use this for precise file-system searches.

<figure class="product-shot" markdown>
  ![Find Files panel configured to locate Notepad executables](assets/royifilemanager-find-files-fd-panel.png)
  <figcaption>Find Notepad executables under C:\Windows.</figcaption>
</figure>

!!! example "Find Notepad Executables"
    Set **Name Pattern** to `notepad*` and keep **Pattern Mode** set to Glob.

    Set **Extensions** to `exe`, enable **Recursive** and set **Max Results** to `25`.

    Press **Search**.

## Search File Content

Press ++alt+f7++.

Search names and contents with Literal, Glob, or RegEx modes.

Leave the content field empty to search names only.

Search runs in the background. Use **Stop** to keep results collected so far.

<figure class="product-shot" markdown>
  ![Search Files panel configured to find font settings](assets/royifilemanager-search-files-panel.png)
  <figcaption>Search INI files containing “fonts” under C:\Windows.</figcaption>
</figure>

!!! example "Find INI Files That Mention Fonts"
    Set **File Name Pattern** to `*.ini` and keep its mode set to Glob.

    Set **Content Pattern** to `fonts` and keep its mode set to Literal.

    Enable **Recursive** then press **Search**.
