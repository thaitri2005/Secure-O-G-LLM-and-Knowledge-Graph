# E54 · Source verification for compound numeric cells

The default K1 configuration now repairs a narrow class of errors in upright, text-layer PDFs. The native grid has multiple plain numeric literals in one body cell and the printed cell contains exactly one of them. The rule identifies the source cell from vector borders and requires independent agreeing anchors in the same printed row and column. PyMuPDF and PDFium must both read the same complete printed value. Heading text, units and punctuation remain outside the edit unless the complete native cell matches the supported numeric grammar. [Reconciliation](../../src/graph_builder/corpus/numeric_cells.py)

A correction updates the grid, cell record, row-oriented text and Markdown chunk. The K1 table part retains the original value, revised value, native grid indices and printed PDF rectangle. QA rereads the printed box. Unresolved candidates keep their extracted value and carry a page finding and chunk-level review status. The setting `repair_numeric_cells: false` measures the same profile without the correction. [K1 profile](../../configs/corpus/k1.json)

## Regression and transfer

| Check | Baseline | Revised |
| --- | ---: | ---: |
| Myrtle Basin, `PRE TOUR MEETING` in K1 and retrieval | 2/20 | **20/20** |
| Myrtle Basin, adjacent `PERMITS ISSUED` control | 20/20 | **20/20** |
| Whole 79-PDF regression, exact page phrases | 1,271/1,271 | **1,271/1,271** |
| Whole 79-PDF regression, exact table-cell probes | 47/47 | **47/47** |
| Palm Valley, time cells checked against source rectangles | 1,248/1,248 | **1,248/1,248** |
| ZeroGen-5 main report, four external source pages, printed cell probes | 46/46 | **46/46** |
| Volve, four reports and 40 pages, exact phrase probes | 157/157 | **157/157** |

E54 preserved every previously matched distinct source word and number type on its page, all 624 ordered Palm Valley hourly rows and 9/10 page-scoped BM25 top-five hits. K1 changed exactly 18 grid cells and 18 chunk texts. QA's source-supported count moved from 11,742 to 11,760 across the 79 PDFs. All 18 revised cells were reread and corroborated. The narrow pass recorded 70 other candidate conflicts with ambiguous geometry and raised 16 chunks to review. Those conflicts remain present in the canonical source-aligned export at review quality. [Source expectations](../../configs/benchmarks/track_a_numeric_cells_e54.json)

The natural ZeroGen-5 window preserves pages, tables, chunks, forms and the retrieval view byte for byte or record for record. Its sampled values include signed subsea depths, decimals, mud-weight strings and printed `N/A`. The Volve transfer releases also match across those representations. The two transfer sets produced zero natural target repairs. On two deliberately corrupted copies of native cells from the ZeroGen tables, the rule recovered `892` from `5555 892` and `-251.32` from `111 -251.32`. The PDF bytes were identical to the unmodified input in the controlled comparison. This establishes transfer for the injected error class. Tests also preserve a cell with two visible printed numbers and abstain when the second reader or chunk mapping disagrees. [Tests](../../tests/test_native_numeric_cells.py)

## Reproduction

Export both profiles from the same native conversion cache and run `qa --fidelity --crossrep --cell-evidence` against each release. Use the original source PDF with the same filename and SHA-256 listed in the reference.

```sh
python scripts/benchmark_native_numeric_cells.py --case myrtle \
  --pdf data/raw/track-a-scale/PR20140005_Daily_Drilling_Report.pdf \
  --baseline "$OLD_RELEASE" --baseline-qa "$OLD_QA" \
  --candidate "$NEW_RELEASE" --candidate-qa "$NEW_QA" --out "$MYRTLE_SCORES"
python scripts/benchmark_cell_evidence.py \
  --pdf data/raw/track-a-scale/PR2019W019_Appendix_F_Daily_Drilling_Reports.pdf \
  --release "$NEW_RELEASE" --reference configs/benchmarks/track_a_hourly_palm.json \
  --evidence "$NEW_QA/cell_evidence.jsonl" --out "$TIME_CELL_SCORES"
```

For ZeroGen, process the original PDF pages 23, 24, 34 and 35 in order as a lossless PDF page window. Use `--case zerogen --pdf "$ORIGINAL_ZEROGEN" --input-pdf "$ZEROGEN_WINDOW"` with the two releases and QA directories. The scorer checks the original digest and rendered page identity. Both benchmarks compare K1 and retrieval by source row anchor and column position.
