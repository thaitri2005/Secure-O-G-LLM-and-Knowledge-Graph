# E43 — Source evidence for individual K1 table cells

`qa --cell-evidence` writes `cell_evidence.jsonl` and a summary bound to the K1 release identity and checksum inventory. Each record identifies the K1 table and its zero-based row and column, the cell text, the source page and reference, and the rectangle in displayed original PDF points when the location can be established. The sidecar is separate from the K1 package and the retrieval view. [Cell evidence implementation](../../src/graph_builder/corpus/qa/cell_evidence.py)

| Status | What the check established |
| --- | --- |
| `source_supported` | The original PDF's ruled grid matches the released grid and the cell has its own visible word box. This path covers reconstructed hourly and casing tables. |
| `text_matches_region` | The original PDF text matches the text of an intact native Docling cell in its recorded rectangle. This status verifies the text at the location. |
| `review` | The text differs in the region or the box crosses cells or rows in a reconstructed source table. The record carries a reason and, where applicable, the source cell IDs. |
| `unavailable` | The geometry is unsupported, missing, ambiguous or cannot be linked to the released grid. |

The sidecar retains literal values. A source-supported clock cell can also carry a normalized `HH:MM` value. A numeric casing value can carry the explicit depth or length unit from its verified column. The measurements below used single-part upright text pages. E44 added native cell evidence on normalized text pages and on joined table parts with verifiable row mappings. [E44](E44-track-a-rotated-table-continuations.md)

## Measurements

| Scope | Records | Source-supported grid cells | Native text matches | Review | Unavailable |
| --- | ---: | ---: | ---: | ---: | ---: |
| E41 drilling corpus, 229 pages | 37,540 | 2,633 | 28,934 | 3,919 | 2,054 |
| Volve controls, 40 pages | 2,399 | 0 | 2,111 | 185 | 103 |

On the 59 Palm Valley pages, an independent PyMuPDF reader confirmed **1,248/1,248 clock cell rectangles** from the pinned 624 pairs. The check verifies the literal text inside both rectangles, their left-to-right column separation and the physical row order. The retrieval view is byte-identical to the E42 view across both corpora. A fresh K1 export of Palm Valley reproduces all six JSONL groups from the prior release. The unit suite ran 1,224 tests with 16 skipped and zero failures. [Pinned clock rows](../../configs/benchmarks/track_a_hourly_palm.json)

On Palm Valley page 13, table `t24` row 1 column 1 maps `2:30` to its original `To` cell. Page 30's compound table `t54` row 31 column 1 contains `6:00 11:00 [ 2 ] Drilled`. Its native rectangle overlaps two rows of the source-backed `t120`, so the sidecar flags it as `native_box_spans_source_rows`. The two correct times each have a separate original rectangle. The neighboring native cell `DIESEL (L) 4900` has `text_matches_region` and remains in the retrieval view.

## Reproduction

Set `RELEASE` to the validated E41 hourly K1 release. Reuse the original corpus and its Docling cache.

```sh
python -m graph_builder.corpus qa data/interim/track-a-scale/corpus \
  --release "$RELEASE" --out data/interim/track-a-cell-evidence/final-regression \
  --fidelity --crossrep --form-overlap --table-overlap --cell-evidence

python scripts/benchmark_cell_evidence.py \
  --pdf data/raw/track-a-scale/PR2019W019_Appendix_F_Daily_Drilling_Reports.pdf \
  --release "$RELEASE" --reference configs/benchmarks/track_a_hourly_palm.json \
  --evidence data/interim/track-a-cell-evidence/final-regression/cell_evidence.jsonl \
  --out data/interim/track-a-cell-evidence/final-regression/hourly_geometry_check.json
```
