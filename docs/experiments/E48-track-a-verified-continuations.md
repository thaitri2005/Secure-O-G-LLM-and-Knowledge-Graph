# E48 — Verified rotation and split activity rows

The `verify` orientation mode compares the displayed and upright conversions against the original PDF text layer. It accepts an upright page only if word matches hold and each previously matched numeric occurrence survives. It reuses a conversion when the entire segment can use the same version. A segment with mixed decisions is converted using the accepted page rotations. OCR, hybrid and ambiguous pages retain their original orientation in this mode. QA records the comparison and the result for each tested page. [Orientation](../../src/graph_builder/corpus/orientation.py) · [Segment processing](../../src/graph_builder/corpus/process.py)

The full table candidate rebuilds ruled Operations Activity Detail tables from their printed columns, matching headers and complete page counters. It verifies the full visible word inventory and the individual cells with an independent PDF reader. The final page can supply only the description suffix for the preceding event. The logical grid contains that event once and `parts[].cell_sources` records each fragment on its physical page. Publication checks that the fragments reproduce the grid. Cell QA reads the original PDF again and reports the rectangles in its displayed frame. [Activity rule](../../src/graph_builder/corpus/activity_detail.py) · [K1 validation](../../src/graph_builder/corpus/k1_validate.py)

The end-of-well rule accepts numbered Well Information captions and separate labels for planned and actual depth, elevation, location and drilling contractor. It abstains when a populated row in the ruled panel falls outside its supported field layout. The test included two explicitly titled table parts and a panel with an unsupported label. It matched all 15 reference fields, verified 32 nonempty source cells and kept the unsupported panel under native extraction.

## Results

The replay uses the 54 reviewed FORGE 68-32 activity rows in a rebuilt, rotated and ruled three-page PDF. The last description is printed in two fragments. The original FORGE PDF was unavailable from the cloud network during this run.

| Configuration | Exact activity rows | Complete logical table | Final row verified on both source pages |
| --- | ---: | --- | --- |
| Original orientation, separate tables | 0/54 | No | No |
| Original orientation, joining | 0/54 | No | No |
| Verified orientation, separate tables | 45/54 | No | No |
| Verified orientation, joining and activity reconstruction | 54/54 | Yes | Yes |

The final variant verified 361 source cells and fragments, kept all rows in order and published one header row. The three-page cold conversion took about 33 seconds including orientation comparison. Export and QA added about half a second. All processing used local models.

On 79 existing drilling PDFs and 229 pages, the full candidate passed QA. Its exported tables, forms, chunks, pages, files, parents and retrieval view matched the core baseline byte for byte. This run is a regression check on those report layouts. The FORGE replay and end-of-well fixture measure extraction on reconstructed layouts. The orientation verification mode and extended K1 profile remain opt-in pending evaluation on original reports with those layouts.

## Reproduction

Supply the original SHA-256-pinned PDF to benchmark the annotated FORGE table. The output reports all four variants, timing, exact row counts and whether the final description's fragments match both original pages. [Benchmark runner](../../scripts/benchmark_table_continuation.py)

```sh
python scripts/benchmark_table_continuation.py \
  --pdf 'Monitoring Well 68-32 - EOWR.pdf' --out path/to/benchmark \
  --orientation-mode verify --activity-detail
```
