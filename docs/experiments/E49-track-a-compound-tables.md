# E49 — Drilling table panels and operation codes

K1 reads the Bit Number block in a compound daily report using printed horizontal and vertical rulings. The bit IDs travel with the headers and the printed measurement units stay in the relevant row labels. Separately ruled Formation Depths panels preserve the unit printed in the caption, distinct Estimated and Actual columns, and the source's blanks and `unknown` values. Both panels require the visible cell text and caption to match a second PDF reader. [Panel extraction](../../src/graph_builder/corpus/ruled_panels.py)

The Operations Summary code column accepts groups of digits separated by hyphens, including leading zeroes. Printed column boundaries, clock values, elapsed time, depth and the complete source token check still govern each row. Cell QA independently checks the emitted boxes for Operations Summary against the original PDF. [Operations reader](../../src/graph_builder/corpus/ops_tables.py) · [Cell QA](../../src/graph_builder/corpus/qa/cell_evidence.py)

QA compacts horizontal span copies in oversized retrieval chunks when the parsed positions have a single owner in K1 and agree with the retained anchor. It keeps headers, row-spanning cells, separate cells with the same text and the original K1 package. Its sidecar records the changed positions, original length and projected length for each chunk. [Span projection](../../src/graph_builder/corpus/qa/compound_spans.py)

## Results on the 79-PDF drilling corpus

The reference pins the three original source PDFs. Operations Summary checks the order and printed values of the From, To, Elapsed, End MD in feet, Code and Non-Prod columns. The two panel checks require exact row labels, column keys, adjacent values and the printed measurement unit. These are reviewed cases selected for this change. [Reference](../../configs/benchmarks/track_a_compound_tables.json)

| Check | Before | After |
| --- | ---: | ---: |
| Exact Operations Summary rows, five FORGE 78B pages | 53/62 | 62/62 in source order |
| Exact selected Bit Number and Formation Depths rows | 0/26 | 26/26 |
| Retrieval table chunks above 1,500 characters | 33 | 9 |
| Palm Valley page 49, targeted compound chunk | 3,535 characters | 655 characters |

K1 produced 55 verified Bit Number panels on Palm Valley and 20 Formation Depths panels on New Crown. Cell QA verified 1,566 and 370 nonempty cells in those panels, and 410 cells in the five rebuilt Operations Summary tables. Span compaction by itself changed 24 chunks and preserved their IDs and all distinct tokens in each chunk.

Both profiles matched the 1,271 phrases, 47 exact-cell probes and 624 hourly intervals. The revised phrase reference contains the five report numbers visibly printed as 13 through 17 in Myrtle Basin. The full comparison preserved the distinct PDF word and number tokens previously retrieved on each page. Four Volve PDFs and 40 pages produced a byte-identical retrieval view. K1 export took about 75 seconds on cached Docling output. QA with source fidelity, cross-representation and cell evidence took about 42 seconds on the same batch.

The default drilling profile enables the new panels and numeric codes. QA compacts oversized spans automatically for that profile. The remaining over-budget chunks stay available and recorded for review. The measurements cover original PDFs with text layers.

## Reproduction

Export the current default K1 profile and run QA with `--crossrep --fidelity --cell-evidence`. Run QA again on the same release with `--no-compact-table-spans` and a separate output directory. Supply the baseline, final and span-off views to the benchmark runner. [Benchmark runner](../../scripts/benchmark_compound_tables.py)

```sh
python scripts/benchmark_compound_tables.py \
  --before "$BEFORE_RELEASE" --before-view "$BEFORE_VIEW" \
  --after "$AFTER_RELEASE" --after-view "$AFTER_VIEW" \
  --span-off-view "$SPAN_OFF_VIEW" --out "$RESULTS"
```
