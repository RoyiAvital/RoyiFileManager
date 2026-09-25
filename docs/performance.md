# Performance

!!! danger "Take Performance Seriously"
    Minimize _Time to render a pane_ (TTRP), _Time to apply a filter_ (TTAF) and _Time to apply a fuzzy find_ (TTAFF).

The current application version and latest published benchmark suite are `0.9.2`.

## Current Published Suite

| Test                      	| Version 0.9.2 (ms) 	|
|---------------------------	|--------------------	|
| Pane Load - Small Folder  	| 42.37              	|
| Pane Load - Large Folder  	| 983.77             	|
| Filter Bar - Small Folder 	| 10.08              	|
| Filter Bar - Large Folder 	| 328.40             	|
| Fuzzy Find - Small Folder 	| 4.82               	|
| Fuzzy Find - Large Folder 	| 349.39             	|
| Fuzzy Find - Recursive    	| 89.72              	|
| QuickView - Small Folder  	| 111.81             	|
| QuickView - Large Folder  	| 115.70             	|
| Navigation                	| 6.80               	|
| Refresh / Selection       	| 471.10             	|

Small folders contain 256 files. Large folders contain 200,000 files. Recursive Find uses 50,000 files.

Results use Windows and NTFS with warm caches and three fresh processes per test.

## Version Comparison

[CelebA](https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html) folder with about 200,000 entries. Lower is better.

| Measurement                | Version 0.8.0 | Version 0.8.1 | Version 0.9.0 | Version 0.9.2 |
|----------------------------|---------------|---------------|---------------|---------------|
| First Populated Pane Paint | 8.949 [s]     | 5.663 [s]     | 0.583 [s]     | 0.506 [s]     |
| Metadata Loading Complete  | 17.786 [s]    | 11.498 [s]    | 0.571 [s]     | 0.494 [s]     |
| Post Paint Qt Commit Work  | 2.765 [s]     | 1.282 [s]     | 0 [s]         | 0 [s]         |
| Settled Working Memory     | Not recorded  | 771.3 [MiB]   | 165.6 [MiB]   | 167.4 [MiB]   |

The `0.8.1` timing column shows its lowest result from the two comparison runs. Memory was recorded only in the `0.8.1` to `0.9.0` run.

Both runs used alternating fresh processes, warm OS caches, hidden filtering enabled and QuickView and extended status disabled. Do not chain percentages across the two runs.