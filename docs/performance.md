# Performance

!!! danger "Take Performance Seriously"
    Minimize _Time to render a pane_ (TTRP), _Time to apply a filter_ (TTAF) and _Time to apply a fuzzy find_ (TTAFF).

The latest published benchmark suite is tested on version `0.13.0`.

## Current Published Suite

| Test                            |   0.9.0 |   0.9.1 |   0.9.2 |   0.9.3 | 0.10.3 | 0.13.0 |
|---------------------------------|--------:|--------:|--------:|--------:|-------:|-------:|
| Pane Load - Small Folder        |   42.23 |   42.78 |   44.66 |   35.20 |  33.93 |  37.52 |
| Pane Load - Large Folder        | 1001.54 | 1014.82 |  978.07 |  964.31 | 958.23 | 758.64 |
| Filter Bar - Small Folder       |    8.96 |    9.21 |    8.70 |    8.69 |   8.79 |  10.88 |
| Filter Bar - Large Folder       |  332.17 |  331.48 |  333.62 |  331.28 | 338.27 | 364.34 |
| Fuzzy Find - Small Folder       |    4.57 |    4.52 |    4.51 |    4.55 |   7.17 |   5.28 |
| Fuzzy Find - Large Folder       |  408.47 |  379.09 |  389.25 |  407.95 | 441.02 | 357.29 |
| Fuzzy Find (Recursive)          |   91.68 |   91.09 |   91.12 |   91.05 |  91.91 |  92.54 |
| QuickView Images - Small Folder |  122.09 |  120.89 |  120.60 |  122.61 | 122.04 | 121.09 |
| QuickView Images - Large Folder |  123.29 |  128.92 |  125.64 |  121.14 | 135.86 | 119.46 |
| QuickView Text - Small Folder   |       - |       - |       - |       - | 133.03 | 129.55 |
| QuickView Text - Large Folder   |       - |       - |       - |       - | 129.47 | 132.35 |
| Selections - Small Folder       |   15.67 |   15.64 |   15.40 |   15.24 |  15.35 |  16.18 |
| Selections - Large Folder       |   88.18 |   88.37 |   88.94 |   87.85 |  88.36 |  89.65 |
| Selections Readback             | 1994.44 | 1987.26 | 1967.05 | 1974.51 |  73.78 |  69.86 |
| Navigation                      |    7.17 |    7.20 |    7.17 |    7.36 |   7.17 |   7.05 |
| Refresh / Selection             |  581.97 |  581.73 |  582.82 |  592.84 | 585.17 | 355.99 |

Small folders contain 256 files. Large folders contain 200,000 files. Recursive Find uses 50,000 files.

Results use Windows and NTFS with warm caches and three fresh processes per test.

## Version Comparison

[CelebA](https://mmlab.ie.cuhk.edu.hk/projects/CelebA.html) folder with about 200,000 entries. Lower is better.

| Measurement                | ver. 0.8.0  | ver. 0.8.1  | ver. 0.9.0  | ver. 0.9.2  | ver. 0.13.0 |
|----------------------------|-------------|-------------|-------------|-------------|-------------|
| First Populated Pane Paint | 8.949 [s]   | 5.663 [s]   | 0.583 [s]   | 0.506 [s]   | 0.257 [s]   |
| Metadata Loading Complete  | 17.786 [s]  | 11.498 [s]  | 0.571 [s]   | 0.494 [s]   | 0.244 [s]   |
| Post Paint Qt Commit Work  | 2.765 [s]   | 1.282 [s]   | 0 [s]       | 0 [s]       | 0 [s]       |
| Settled Working Memory     | 771.1 [MiB] | 771.3 [MiB] | 165.6 [MiB] | 167.4 [MiB] | 160.3 [MiB] |

All runs used alternating fresh processes, warm OS caches, hidden filtering enabled and QuickView and extended status disabled. Do not chain percentages across the two runs.