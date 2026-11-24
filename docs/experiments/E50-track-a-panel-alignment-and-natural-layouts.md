# E50 · Panel alignment and original report layouts

The default Track A profile reads numbered BHA tool grids and numbered pump columns from the printed ruling. The BHA rule requires a standalone numbered caption above a verified header and keeps summary measurements such as hook load out of the tool-length grid. Pump headers keep the printed pump identifiers, dimensions and blanks. A blank template with no identifiers emits no new panel. PyMuPDF independently reads the visible words in the estimated cell and caption rectangles before publication. Native source records remain available. [Panel reader](../../src/graph_builder/corpus/ruled_panels.py)

## Default extraction

Before and after use the same cached Docling conversions for 79 original PDFs and 229 text-layer pages. The new reference measures exact captions, column keys and rows. It checks the contents of populated cells against the original PDF coordinates. The evaluation pages are other pages of the same two reports. [Reference](../../configs/benchmarks/track_a_panel_alignment.json)

| Check | E49 | E50 |
| --- | ---: | ---: |
| Exact BHA and pump rows on the five development pages | 0/20 | 20/20 |
| Exact rows on seven additional pages | 0/24 | 24/24 |
| Verified numbered BHA panels on Palm Valley | 0 | 44 |
| Verified pump panels on New Crown | 0 | 10 |
| Populated cells independently verified in those panels | 0 | 1,348 |
| Pinned phrases, exact cells and hourly rows | 1,271/1,271 · 47/47 · 624/624 | 1,271/1,271 · 47/47 · 624/624 |
| Source-backed chunk in the top five when the page is known | 9/10 | 9/10 |
| Retrieval table chunks over 1,500 characters | 9 | 9 |

The zero in the first two rows refers to a standalone structured panel with the expected caption and columns. Raw values could already appear in native content. On Palm Valley page 34, for example, the new grid puts `7.76` beside `Down Hole Motor` under the printed `LENGTH` header in `BHA # 15`. The source omits a length unit in that header. On New Crown page 7, `GPM = 310` belongs to pump `1`, and the corresponding pump `2` cell stays blank.

The release retained every previously matched distinct source token type per page. Four Volve PDFs and 40 pages produced a byte-identical retrieval view. The added structured panels raised page-level surplus numeric occurrences from 10,696 to 11,271. Cell review entries rose from 4,739 to 4,770 as additional source regions exposed overlaps in some native cells. The pump rule abstained on the 10 blank New Crown templates and the different pump layout on 59 Palm Valley pages. The three pinned empty templates emitted no new panel. [E49 benchmark](E49-track-a-compound-tables.md)

## Original report pages for experimental features

The originals are pinned by SHA-256. The runner passes selected windows of original pages to Docling. It checks that the extracted page windows keep the original text boxes, orientation and page geometry. The experiment covers two well completion reports and a petrophysics appendix. [Sources and references](../../configs/benchmarks/track_a_natural_layouts.json)

| Source | Core | Candidate | Finding |
| --- | --- | --- | --- |
| West Moonie-1, source pages 25–29 | 5 parts kept separate | 3/4 boundaries joined, 2 logical tables remain | In both configurations, 25/35 rows match printed date, report number and depth. 10/35 also match the normalized full description. On source page 27 a native row combines reports 14 and 15. |
| ZeroGen-5, source pages 17–18 | Both pages processed as displayed | Page 18 rotates by 90°. Page 17 keeps its original orientation. | The page-18 retrieval view retains 193 numeric occurrences, up from 186. Native cells with matching text in the source rectangle rise from 124 to 265, while cells marked for review fall from 31 to 0. The orientation guard declined the page-17 rewrite because it lost one numeric occurrence. |
| OzAlpha-1, source page 10 | 10/10 annotated label–value pairs | 10/10 annotated label–value pairs | The four-column summary falls back to the native table and keeps the sampled pairs. |

Rotation verification, joining and the extended well-summary rule stay opt-in. West Moonie exposes a separate reconstruction problem upstream of joining. On the 79-PDF regression corpus, the full K1 candidate made zero joins and emitted identical tables, chunks, pages and forms. Original GDR FORGE downloads returned HTTP 403, so the E48 split-description replay still needs its own original-PDF confirmation. [E48](E48-track-a-verified-continuations.md)

## Cold PDF latency

Eight of the original regression PDFs cover five families, 158 pages and a range of 1–60 pages per file. Each conversion starts with a fresh document corpus and uses the already installed local model weights. The first file includes model initialization. One worker converts the PDFs sequentially. The reported file total sums registration, uncached conversion, K1 and full QA. All eight exports passed QA validation. This sample estimates local latency for the selected files.

| Measure | Wall time |
| --- | ---: |
| Sum across the eight files | 20 min 47 s |
| Median per PDF | 37.5 s |
| 95th percentile per PDF, linearly interpolated | 9 min 27 s |
| Slowest PDF, Palm Valley, 59 pages | 12 min 8 s |
| Mean per page across the batch | 7.89 s |

The Palm Valley run took 672.2 seconds in native conversion, 38.1 seconds in K1 export and 17.3 seconds in QA. Inference ran locally. The measurement includes no model downloads or paid model API calls.

## Reproduction

Use the two validated K1 releases and their QA directories to compare the default extraction. Run QA with `--fidelity --crossrep --cell-evidence` on both releases.

```sh
python scripts/benchmark_track_a_panel_alignment.py \
  --before "$E49_RELEASE" --before-qa "$E49_QA" \
  --after "$E50_RELEASE" --after-qa "$E50_QA" --out "$PANEL_RESULTS"
python scripts/benchmark_track_a_natural_layouts.py \
  --pdf-dir "$ORIGINAL_PDF_DIR" --out "$NATURAL_RESULTS" --models data/interim/ocr_models
python scripts/benchmark_track_a_cold.py \
  --pdf-dir data/raw/track-a-scale --out "$COLD_RESULTS" --models data/interim/ocr_models
```
