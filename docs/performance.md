# Performance

The current application version is 0.9.1. The latest published benchmark suite is the 0.9.0 snapshot-architecture baseline.

## Current Published Suite

| Test | Run Time (ms) |
| --- | ---: |
| Pane Load - Small Folder | 44.14 |
| Pane Load - Large Folder | 1,030.26 |
| Filter Bar - Small Folder | 9.72 |
| Filter Bar - Large Folder | 332.28 |
| Fuzzy Find - Small Folder | 4.67 |
| Fuzzy Find - Large Folder | 350.86 |
| Fuzzy Find - Recursive | 89.82 |
| QuickView - Small Folder | 109.73 |
| QuickView - Large Folder | 118.74 |
| Navigation | 6.79 |
| Refresh / Selection | 482.95 |

Small folders contain 256 files. Large folders contain 200,000 files. Recursive Find uses 50,000 files.

Results use Windows and NTFS with warm caches and three fresh processes per test. The Fuzzy Find rows predate restoration of the Quicksearch dialog and do not measure its current rendering cost.

## Version Comparison

CelebA folder with about 200,000 entries. Lower is better.

| Measurement | Version 0.8.0 | Version 0.8.1 | Version 0.9.0 |
| --- | ---: | ---: | ---: |
| First Populated Pane Paint | 8.949 s | 5.663 s | 0.583 s |
| Metadata Loading Complete | 17.786 s | 11.498 s | 0.571 s |
| Post-Paint Qt Commit Work | 2.765 s | 1.282 s | 0 s |
| Settled Working Memory | Not recorded | 771.3 MiB | 165.6 MiB |

The `0.8.1` timing column shows its lowest result from the two comparison runs. Memory was recorded only in the `0.8.1` to `0.9.0` run.

Both runs used alternating fresh processes, warm OS caches, hidden filtering enabled and QuickView and extended status disabled. Do not chain percentages across the two runs.