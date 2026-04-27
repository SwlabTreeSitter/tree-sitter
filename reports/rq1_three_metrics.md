# RQ1 — Three Metrics (Coverage / Ranking / Top-10)

Evidence categories follow prior work (SmallBasic/C):
- **Coverage**: fraction of cursors where a candidate set is retrievable.
- **Rank-1 / Avg↓keys**: ranking usefulness (0 keystrokes when rank=1).
- **Top-5 / Top-10**: answer found within visible page.

| Language    | Cat | Cursors | Coverage | Rank-1    | Avg↓keys | Med↓keys | Top-5  | Top-10 |
|-------------|-----|---------|----------|-----------|----------|----------|--------|--------|
| smallbasic  | LR  |    1119 | 100.00% |   457 (40.8%) |    1.81 |     1.0 | 89.45% | 95.44% |
| c           | LR  |   46970 |  99.79% | 24152 (51.5%) |    2.02 |     0.0 | 87.03% | 95.53% |
| php         | GLR |   63228 |  99.23% | 30768 (49.0%) |    2.20 |     1.0 | 85.62% | 95.63% |
| haskell     | GLR |   62169 |  99.91% | 19705 (31.7%) |    2.77 |     1.0 | 81.07% | 93.73% |
| java        | GLR |   51365 |  99.60% | 20383 (39.8%) |    2.70 |     1.0 | 84.34% | 93.40% |
| javascript  | GLR |   52168 |  99.96% | 21512 (41.3%) |    3.01 |     1.0 | 81.96% | 92.57% |
| python      | GLR |   49287 |  99.91% | 18123 (36.8%) |    3.19 |     1.0 | 86.11% | 92.30% |
| cpp         | GLR |   53795 |  99.30% | 23165 (43.4%) |    3.19 |     1.0 | 79.54% | 91.04% |
| ruby        | GLR |   35299 |  99.46% | 13059 (37.2%) |    3.62 |     1.0 | 78.80% | 89.47% |

Metric definitions: computed over FOUND cursors in `debug_coverage_<lang>/*.csv`.
`Cat` = LR (prior work) or GLR (this work extension via tree-sitter).
