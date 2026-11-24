# E41 — Recovering ruled hourly operations logs

K1 uses a versioned three-column template for the `Hourly Operations Summary` layout. The template gives the printed title and the label aliases for the start time, end time and description. The reader checks adjacency, column rulings, the closing rule and the clock values in each body row before publishing a grid. It derives the coordinates from the visible PDF and accepts the layout under an ordinary filename. [Template](../../configs/corpus/k1.json) · [Reader](../../src/graph_builder/corpus/hourly_operations.py)

On Palm Valley page 13, K1 promotes `From`, `To` and `[IADC Code] Description` to the header of the existing table. On page 30, it creates a standalone time log with eight rows and marks the overlapping native compound table for review. The compound table contains adjacent sections and stays available as source evidence. A native table prefix is split only when its geometry and tokens establish that the discarded rows are covered by the rebuilt log.

## Results

Both profiles reuse the same native Docling output. The before profile uses E40 and disables only the hourly operations rule. The source reference for the daily time ranges was read independently with PyMuPDF and fixed before scoring K1. A full page match requires one table with the printed header and every start/end pair in order. The source reference covers the daily 00:00–24:00 table on each Palm Valley page. [Pinned time rows](../../configs/benchmarks/track_a_hourly_palm.json)

| Measure | Before | After |
| --- | ---: | ---: |
| Pinned table cells across the 229-page benchmark | 43/47 | 47/47 |
| Pinned header and body phrases across the 229-page benchmark | 1,266/1,271 | 1,266/1,271 |
| Exact daily time pairs in document order on Palm Valley | 203/624 | 624/624 |
| Palm Valley pages with one correct daily log | 13/59 | 59/59 |
| Exact daily time pairs on the 57 pages outside pages 13 and 30 | 203/609 | 609/609 |
| Surplus occurrences of source numbers on the 229-page corpus | 11,338 | 14,374 |
| K1 export on the 229-page conversion cache | 37.3 s | 42.6 s |
| QA and retrieval export on the same cache | 8.9 s | 8.6 s |

The additional Palm Valley pages all use the same report family. The wider benchmark includes 170 pages from other report families plus 40 Volve pages. Their table, chunk, and form records are identical across profiles. The time-pair audit measures the two printed clock columns. A synthetic PDF with distinct labels and geometry also exercises the same reader through a second template.

Both releases passed structural validation. The 229-page release had one existing table/chunk consistency finding before and zero after. The rule published 59 source-backed logs and identified 12 native overlaps for review. Five overlaps had a proven native prefix removed. The remaining overlapping evidence and the separate text chunks contribute to the surplus count, which measures page-level numeric occurrences. Recovery is local and uses zero billed model APIs.

## Reproduction

Use the native corpora described in [E38](E38-track-a-scale-benchmark.md) and [E40](E40-track-a-source-report-fields.md).

```sh
python scripts/benchmark_track_a_scale.py --hourly-ablation \
  --hourly-reference configs/benchmarks/track_a_hourly_palm.json \
  --pdf-dir data/raw/track-a-scale --reuse-corpus data/interim/track-a-scale/corpus \
  --out data/interim/track-a-hourly/final-regression
python scripts/benchmark_track_a_scale.py --hourly-ablation \
  --manifest configs/benchmarks/track_a_volve_fresh.json --pdf-dir data/raw/track-a-volve-fresh \
  --reuse-corpus data/interim/track-a-volve-fresh-natural/corpus --out data/interim/track-a-hourly/final-volve
```

Each run writes the per-document coverage, K1 and QA timings, and the repair decisions to `results.json`.
