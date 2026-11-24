# E57 · Source-grid recovery on new drilling reports

| Item | Value |
| --- | --- |
| Date | 24 November 2026 |
| Question | Can a layout-based rule recover or repartition a table on reports that did not inform the implementation? |
| Input | Three newly fetched Volve reports for exploration, seven further Volve PDFs for confirmation, four previously unused pages from two well completion reports and the 79-PDF regression corpus. |
| Reference | Region-anchored samples of printed header and body positions, including units and expected blanks. Original file digests and confirmation annotations were frozen before running the candidate for that cohort. |
| Deployment | Explicit `--recover-source-grids` option. No hosted model calls. |

## Reconciliation

K1 queries vector rulings on upright text-layer pages for a complete rectangular grid. A table has a distinct heading row and populated data. PyMuPDF and PDFium must both agree with every printed cell and its position, including empty cells. The rule uses the headings and literal values in the source. It takes no report aliases, well IDs or fixed source coordinates. [Implementation](../../src/graph_builder/corpus/source_grids.py)

A source-only grid is added alongside the existing page passages. For an overlapping native table to be repartitioned, exactly one native table must claim the region, its perimeter must align, and each existing row must contain the same complete text in the same order as the printed row. K1 also checks the native Markdown against the original grid and keeps its caption and logical table ID. These conditions allow a fused header or cell to be separated into the printed columns. The original native rendering stays in the conversion cache. Unsupported grids keep the previous extraction.

## Transfer and regression

| Scope | K1 and retrieval before | With source-grid recovery | Regressions |
| --- | ---: | ---: | ---: |
| Exploration, three newly fetched Volve reports | 27/68 | **68/68** | 0 |
| Confirmation, seven further Volve reports | 59/108 | **82/108** | 0 |
| Other report layouts, two ONGC pages and two CTSCo pages | 100/100 | **100/100** | 0 |
| Regression, 79 PDFs, phrase probes | 1,271/1,271 | **1,271/1,271** | 0 |
| Regression, 79 PDFs, table positions and ordered hourly rows | 47/47 and 624/624 | **47/47 and 624/624** | 0 |

Confirmation used a seeded selection of reports from distinct wellbores. One previously used PDF was excluded by source digest. The seven confirmation PDFs share the Volve reporting family. The candidate corrected 23 previously wrong or absent positions in two documents. Twenty-six positions across the other five sampled grids remain incorrect or missing. The two improved tables were inspected visually against the source after scoring. The ONGC and CTSCo checks confirm preservation on those layouts, with no newly demonstrated repair in either report family.

The 79-PDF corpus kept the same 947 tables and the same derived text. Cached K1 export took about 143 seconds with the rule, versus 108 seconds in the prior E56 replay on this host. The additional cost and the limited distinct-family evidence motivated keeping the switch explicit. The reader requires a complete ruled text-layer grid. The E56 scan limitation remains separate.

## Reproduction

Convert the source PDFs once with the [English drilling profile](../../configs/corpus/drilling_reports_en.json). Reuse the same source corpus and conversion cache for both K1 exports. Run source QA for each release and compare by physical table region and named position.

```sh
python -m graph_builder.corpus k1 "$CORPUS" --name source-grid-off --no-recover-source-grids
python -m graph_builder.corpus k1 "$CORPUS" --name source-grid-on --recover-source-grids
python -m graph_builder.corpus qa "$CORPUS" --release "$RELEASE" --out "$QA" \
  --fidelity --crossrep --cell-evidence
python -m unittest discover -s tests -p test_source_grids.py
```
