# E45 — Retained-row evidence and ruled mud-property panels

The K1 exporter records the number of leading native rows removed by a compound-table repair in `parts[].native_trimmed_rows`. Cell QA checks the exact retained grid, the shifted native cells, the page and the residual rectangle. Older releases can recover the same mapping from the verified conversion cache and their residual rectangle. The sidecar includes `native_r` for these rows and keeps its normal text and geometry review checks. [Trim producer](../../src/graph_builder/corpus/casing_tables.py) · [Cell QA](../../src/graph_builder/corpus/qa/cell_evidence.py)

The optional `mud_properties` rule recognizes a printed `Mud Properties` panel with its own horizontal bands and stable vertical dividers. It keeps the printed property labels, numeric strings, qualifiers and empty value slots in their original columns. It publishes a standalone table while retaining the adjacent native evidence. A panel with unreadable text can omit the uncertain row. A blank slot remains blank. QA reads the panel from the PDF again. [Rule](../../src/graph_builder/corpus/mud_properties.py) · [Candidate](../../configs/corpus/candidates/k1_table_quality_candidate.json)

For a possible continuation, the optional joiner also checks the printed report number and date. It compares equivalent date formats and allows both day/month interpretations for ambiguous slash dates. On Palm Valley pages 34–35 and 49–50, the source report numbers and dates now give an explicit reason to keep the tables separate. The 229-page run considered 83 candidate pairs and left all 83 separate. The synthetic positive join fixtures still pass. [Join guard](../../src/graph_builder/corpus/table_join.py) · [E44 positive fixtures](E44-track-a-rotated-table-continuations.md)

## Measurements

The native QA baseline is the E44 release. The first ablation reruns only the updated QA on that release. The combined candidate re-exports the 79 PDFs and 229 text pages using the existing Docling cache. The two mud-panel layouts are natural pages from the existing corpus. The reference checks full rows, including left and right value positions and blank slots, and requires a separate cell for each printed value. The rectangle check independently reads the PyMuPDF word centers inside each new cell box. [Pinned rows](../../configs/benchmarks/track_a_mud_properties.json) · [Benchmark script](../../scripts/benchmark_mud_properties.py)

| Measure | E44 | Retained-row QA on the E44 release | E45 combined |
| --- | ---: | ---: | ---: |
| Cells with missing native provenance on the scale corpus | 2,054 | 0 | 0 |
| Exact pinned mud-property rows | 4/32 | 4/32 | 32/32 |
| Pinned casing and time-log cells | 47/47 | 47/47 | 47/47 |
| Palm Valley hourly pairs | 624/624 | 624/624 | 624/624 |

Of the 2,054 newly mapped old cells, 1,569 match the words in their source rectangles and 485 warrant review. Ordinal row verification still depends on independent source rules. The mud-property reader published 56 Palm Valley panels and eight New Crown panels. All 1,886 emitted nonempty cell rectangles passed the independent text check. The earlier hourly test passed all 1,248 clock rectangles. Volve’s 40 control pages produced zero new panels and retained byte-identical QA cell evidence and retrieval text. The scale candidate also produced zero panels from the other three scale-corpus report families.

The scale candidate retained 1,266 of the original 1,271 literal probes. The five original Myrtle Basin labels include a clipped fragment, as documented in E40. The candidate preserves the historic reference. The retrieval projection carries 1,182 more surplus numeric occurrences because the standalone panels and the corresponding native chunks coexist. This is a count of repeated numbers on a page. The combined export took about 57 seconds from the conversion cache, and the full QA pass took about 29 seconds on this machine. Both stages ran locally. The mud reader and multi-page joining stay opt-in. [Scale benchmark](E38-track-a-scale-benchmark.md) · [Visible Myrtle Basin labels](E40-track-a-source-report-fields.md)

## Reproduction

Reuse the hashed scale corpus and set `BASELINE` to the E41 hourly release used in E44. The candidate export reports the path to use as `CANDIDATE`. These runs use the local PDF text layer and the existing conversion cache.

```sh
python -m graph_builder.corpus k1 "$CORPUS" --name table-quality-e45 \
  --k1-config configs/corpus/candidates/k1_table_quality_candidate.json
python -m graph_builder.corpus qa "$CORPUS" --release "$CANDIDATE" --out "$QA_DIR" \
  --fidelity --crossrep --form-overlap --table-overlap --cell-evidence
python scripts/benchmark_mud_properties.py --corpus "$CORPUS" --before "$BASELINE" \
  --after "$CANDIDATE" --evidence "$QA_DIR/cell_evidence.jsonl" --out "$QA_DIR/mud-benchmark.json"
```
