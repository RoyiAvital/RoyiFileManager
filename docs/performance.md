# Performance

!!! danger "Take Performance Seriously"
    Minimize _Time to render a pane_ (TTRP), _Time to apply a filter_ (TTAF) and _Time to apply a fuzzy find_ (TTAFF).

The latest published benchmark suite is tested on version `0.13.1`.

## Current Published Suite

| Test                            |   0.9.0 |   0.9.3 | 0.10.3 | 0.13.0 | 0.13.1 |
|---------------------------------|--------:|--------:|-------:|-------:|-------:|
| Pane Load - Small Folder        |   42.23 |   35.20 |  33.93 |  37.52 |  37.02 |
| Pane Load - Large Folder        | 1001.54 |  964.31 | 958.23 | 758.64 | 266.27 |
| Filter Bar - Small Folder       |    8.96 |    8.69 |   8.79 |  10.88 |   9.77 |
| Filter Bar - Large Folder       |  332.17 |  331.28 | 338.27 | 364.34 | 289.53 |
| Fuzzy Find - Small Folder       |    4.57 |    4.55 |   7.17 |   5.28 |   4.86 |
| Fuzzy Find - Large Folder       |  408.47 |  407.95 | 441.02 | 357.29 | 354.73 |
| Fuzzy Find (Recursive)          |   91.68 |   91.05 |  91.91 |  92.54 |  91.28 |
| QuickView Images - Small Folder |  122.09 |  122.61 | 122.04 | 121.09 | 116.37 |
| QuickView Images - Large Folder |  123.29 |  121.14 | 135.86 | 119.46 | 120.62 |
| QuickView Text - Small Folder   |       - |       - | 133.03 | 129.55 | 132.58 |
| QuickView Text - Large Folder   |       - |       - | 129.47 | 132.35 | 131.50 |
| Selections - Small Folder       |   15.67 |   15.24 |  15.35 |  16.18 |  15.79 |
| Selections - Large Folder       |   88.18 |   87.85 |  88.36 |  89.65 |  87.64 |
| Selections Readback             | 1994.44 | 1974.51 |  73.78 |  69.86 |  65.65 |
| Navigation                      |    7.17 |    7.36 |   7.17 |   7.05 |   6.97 |
| Refresh / Selection             |  581.97 |  592.84 | 585.17 | 355.99 |  67.59 |

Small folders contain 256 files. Large folders contain 200,000 files. Recursive Find uses 50,000 files.

Results use Windows and NTFS with warm caches and three fresh processes per test.

## Version Comparison

[CelebA](https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html) folder with about 200,000 entries. Lower is better.

| Measurement                | Ver. 0.8.0  | Ver. 0.8.1  | Ver. 0.9.2  | Ver. 0.13.0 | Ver. 0.13.1 |
|----------------------------|-------------|-------------|-------------|-------------|-------------|
| First Populated Pane Paint | 8.949 [s]   | 5.663 [s]   | 0.506 [s]   | 0.257 [s]   | 0.112 [s]   |
| Metadata Loading Complete  | 17.786 [s]  | 11.498 [s]  | 0.494 [s]   | 0.244 [s]   | 0.100 [s]   |
| Post Paint Qt Commit Work  | 2.765 [s]   | 1.282 [s]   | 0 [s]       | 0 [s]       | 0 [s]       |
| Settled Working Memory     | 771.1 [MiB] | 771.3 [MiB] | 167.4 [MiB] | 160.3 [MiB] | 145.5 [MiB] |

All runs used alternating fresh processes, warm OS caches, hidden filtering enabled and QuickView and extended status disabled. Do not chain percentages across the two runs.