# E55 · Numeric cells that cross printed borders

| Item | Value |
| --- | --- |
| Date | 23 November 2026 |
| Question | Can Track A resolve the 70 compound numeric cells flagged by E54 without dropping source values? |
| Input | 79 drilling PDFs and 229 pages from the pinned scale benchmark, plus four Volve reports and eight pages from the ZeroGen-5 completion report |
| Reference | Printed cell boundaries and values from the source PDFs, existing regression probes and 17 more ZeroGen source checks |
| Status | Enabled in the default K1 profile. Runs with local PDF readers and makes zero hosted model calls. |

## Changes

K1 can recover a single printed number from a native cell that spans a border. The visible word must lie within one uniquely owned printed cell, whose neighboring native cells confirm the row and column in the same ruled grid. PyMuPDF and PDFium must agree on the full printed cell. K1 removes an extra literal only when the other emitted occurrences cover its count on that PDF page. K1 records the previous value, corrected value, printed rectangle and word rectangle. Cell QA checks the stored correction against the source again. [Reconciliation](../../src/graph_builder/corpus/numeric_cells.py) · [Cell evidence](../../src/graph_builder/corpus/qa/cell_evidence.py)

For a duplicate whose native assignment remains ambiguous, QA omits the compound from retrieval only when one group of contiguous, independently supported cells retains all of its values. Other unresolved values carry `[unverified: …]` in retrieval text, with the row, column and reason in structured metadata. K1 retains the original text at these positions. Hourly deduplication continues to process unchanged cells after a focused edit elsewhere in the native grid. [Ruled overlap](../../src/graph_builder/corpus/qa/ruled_overlap.py) · [Hourly overlap](../../src/graph_builder/corpus/qa/table_overlap.py)

## Results

| Disposition of the 70 E54 candidates | Palm Valley | New Crown | FORGE | Total |
| --- | ---: | ---: | ---: | ---: |
| Corrected in K1 and corroborated against the printed cell | 6 | 5 | 0 | **11** |
| Removed from retrieval because all individual values are kept in verified cells | 9 | 5 | 0 | **14** |
| Retained in retrieval with an explicit cell-level warning | 31 | 13 | 1 | **45** |

Palm Valley PDF page 18 now serves `5.3` at a position that previously held `4.5 5.3`. On page 1, `9.5` and `10.0` stay available in two distinct verified cells and the merged copy is omitted from retrieval. Of the 45 displayed warnings, 40 lack a sufficiently clear row or column assignment and five lack evidence that another copy accounts for the extra value.

| Regression check | E54 | E55 |
| --- | ---: | ---: |
| Exact page phrase probes | 1,271/1,271 | 1,271/1,271 |
| Exact table-cell probes | 47/47 | 47/47 |
| Palm Valley hourly intervals in order | 624/624 | 624/624 |
| Palm Valley time cells corroborated against PDF rectangles | 1,248/1,248 | 1,248/1,248 |
| Myrtle Basin source cell probes in K1 and retrieval | 40/40 | 40/40 |
| Page-scoped retrieval hits in the top five | 9/10 | 9/10 |
| Matched numeric occurrences on scale benchmark pages | 47,627 | 47,627 |
| Excess occurrences of numbers already present in the source | 11,177 | 11,138 |

The K1 validator passed on all 79 PDFs. The grid diff contains 11 cells and all previously matched distinct words and numbers remain on their pages. Cell QA counted 11,760 `source_supported` cells before and 11,771 after. It separately counted 29,726 cells whose text matched their native rectangle and 4,741 cells with source review findings after the change. These statuses measure a cell's evidence and do not represent a corpus accuracy score.

## Transfer and limits

The default and the ablation produced identical K1 pages, tables, chunks and forms, and identical retrieval records on four Volve PDFs (40 pages, 157/157 exact phrase probes) and the eight sampled ZeroGen pages. ZeroGen scored 46/46 on the earlier source checks and 17/17 on additional checks from original pages 7–9. These samples exercised preservation of existing values. They contained no natural examples that activated the new repair.

The new repair covers upright text-layer PDFs with readable ruled cells. A check on original ZeroGen page 16 found a separate column-header alignment problem in both releases. The printed `Casing Seat` for `Surface` is `197.9m`, while K1 associates `Cemented` with that header. OCR tables and layouts without usable boundaries require separate source checks.

## Reproduction

Export the default profile and a copy with `numeric_cell_focus: false` from the same Docling cache. QA both releases with `--fidelity --crossrep --cell-evidence` and separate output directories. The unchanged E54 probes and Palm Valley time-cell checks use the commands and source manifests in the [E54 record](E54-track-a-native-numeric-cell-reconciliation.md). Compare `parts[].numeric_repairs` for K1 fixes, `RULED_TABLE_OVERLAP_PROJECTED` entries for duplicate suppression and `numeric_review` entries in the QA retrieval file for unresolved cells.
