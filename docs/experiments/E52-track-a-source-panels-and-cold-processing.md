# E52 · Well completion panels, scanned fields and cold processing

## Original source PDFs

The experiment covers three original well completion reports and one original mud log. It uses selected pages from ONGC, Statoil and CTSCo, plus the metadata region of the Utah FORGE mud log on page 1. The mud log region is an original PDF CropBox over the source image. Both K1 profiles use the same native conversion for each PDF. The baseline disables `well_completion` and `scan_fields`. The current profile enables both by default. All four original files are pinned by SHA-256. The probes target the specified pages and fields. [Source manifest](../../configs/benchmarks/track_a_source_panels_e52.json)

| Original source | What the probe checks | Baseline | Current | Source evidence after |
| --- | --- | ---: | ---: | ---: |
| ONGC AD#66, pages 2–3 | Well details, depth and deviation | 2/20 | **20/20** | 20/20 pairs |
| Statoil OzAlpha-1, page 10 | Well summary on the text layer | 10/10 | **10/10** | 10/10 pairs |
| CTSCo West Moonie, pages 47, 144 and 147 | Well cards, coordinates and hole data | 14/14 | **14/14** | 14/14 pairs |
| Statoil OzAlpha-1, scanned page 3 | Expiry date, distribution date and status | 0/3 | **3/3** | 3/3 pairs |
| Utah FORGE mud log, scanned page 1 region | Elevations, dates and logging depth | 0/4 | **4/4** | 4/4 pairs |
| Statoil OzAlpha-1, scanned page 5 | Ordered section/chapter column of the existing five-column table | 5/5 | **5/5** | Native regression control |

The completion rule checks adjacent ruled boxes against two PDF readers and requires a physical well-summary title and identifiable fields. It preserves the source table and gives each extracted label and value its own source box. The five emitted panels contain 172 corroborated physical cells. AD#66 gained 18 source-verified pairs. Its target and drilled depth each map to the correct label and keep `3011m/2715m`. A replay under an ordinary document ID categorized as `other` recovered both panels and passed QA. [Completion reader](../../src/graph_builder/corpus/well_completion.py)

The scan rule adds a two-column `Field`–`Value` table on eligible raster pages. RapidOCR locates labels and nearby typed values. Tesseract independently reads the labelled areas of the source pixels. When only unit punctuation differs, it rereads the same crop with enlargement or contrast adjustment and still requires the exact unit character. The FORGE rows retain `GL:5414' RF: 5444'` and `130'-10987'`. QA reproduced all 14 printed label and value cells from both readers with source rectangles. It marks the generated headers as such. Scan tables carry review quality. These checks cover the specified metadata tables. The remaining columns of the OzAlpha approval matrix and the FORGE chart body were outside the cell scoring scope. [Scan reader](../../src/graph_builder/corpus/scan_fields.py)

When full-page OCR leaves a very tall scan marked `missing`, K1 now retries OCR in overlapping strips at readable scale. Line centres assign each detection to a single strip, and fallback requires enough text across at least two strips. Recovered passages keep the original PDF page and strip rectangle and carry `review` quality. The structured metadata table still requires corroboration from both OCR readers.

On the complete, unmodified three-page FORGE PDF, Docling initially marked the two 7,200-point pages `missing` and K1 blocked the release. The strip fallback recovered both pages at `review` quality. K1 and full QA then validated the three-page release. All four metadata rows on page 1 matched the window experiment, including both printed foot units, and QA reproduced all eight printed cells. The fallback export and QA replay took about four minutes on the four-CPU quota after native conversion. The chart-body passages are OCR text with original strip coordinates. The metadata benchmark scores the two-column table.

## Rotation and continuation

The optional rotation verifier compares both conversions against the source. On top of the source word and exact numeric occurrence checks, it compares table count and numeric rows. When row grouping changes, it requires a distinct stronger match for each existing table using original PDF word positions in the converted cells. Acceptance still requires preservation of the source numeric occurrences at page level. [Verification](../../src/graph_builder/corpus/orientation.py)

On original ZeroGen-5 page 18, the verifier accepted the correction. Numeric occurrences corroborated in physical table cells rose from **73 to 180**. It declined pages 17, 19 and 20 because the proposed conversion lost some source coverage. On page 21, source word and number totals were unchanged but the proposed conversion discarded the native table and five multi-cell numeric rows. The verifier rejected that correction. The four-page window retained both tables, up from one with the earlier verifier. The rotation comparison reused the same Docling probe outputs and reran conversion for the accepted-only copy where needed. The general rotation option and unconstrained cross-page joins are experimental. The supported West Moonie daily log continues to join under the default K1 profile. [Rotation source](../../configs/benchmarks/track_a_natural_layouts.json) · [Daily log benchmark](E51-track-a-verified-daily-logs.md)

## Regression

The 79-PDF corpus contains 229 text-layer pages. The current and E51 default releases each matched **1,271/1,271** page-scoped phrase probes, **47/47** exact-cell probes and **624/624** ordered hourly rows. BM25 retrieved the correct source row in its top five for **9/10** queries in both releases. Every previously retrievable distinct source word and number type remained available on its source page. The current release passed K1 validation and full QA.

## Cold processing

The corpus process now reuses a Markdown serializer for each converted document and renders each table once per document version. The filtering and chunking steps share that rendering. On the same cached 59-page Palm Valley conversion, the chunking profile fell from **72.1 s to 12.3 s** with `cProfile`. The older profile spent **60.7 s** in per-table Markdown exports. A same-input staged replay reduced registration, merge and chunking from **38.1 s to 16.1 s** including their disk work. These two measurements isolate different portions of the pipeline. [Chunking](../../src/graph_builder/corpus/chunking.py)

The default path was then measured again on the original 59-page PDF with a fresh document cache, one sequential worker and local model weights. Both cold releases passed validation and matched across all 296 logical grids, 744 K1 chunks, 59 forms and 731 retrieval chunks by content.

| Stage | E51 | E52 |
| --- | ---: | ---: |
| Docling model passes | 570.3 s | 565.8 s |
| Entire corpus process | 609.1 s | 582.2 s |
| K1 export | 39.4 s | 42.2 s |
| Full QA | 17.7 s | 18.4 s |
| End to end, including registration | 666.2 s | **642.8 s** |

End-to-end time fell by **23.4 s (3.5%)** in these individual runs. The same-input replay isolates the serialization improvement from variation in Docling inference and export time. Two parallel cold conversion segments took **570.45 s** wall time on the four-CPU quota. The default remains sequential. All runs used local weights and incurred zero paid model API calls.

## Reproduction

Place the four SHA-pinned original PDFs in `ORIGINAL_PDF_DIR` and add the separately pinned ZeroGen-5 original for rotation. Use the local Docling artifacts, local small RapidOCR weights and Tesseract with English language data. Each scan requires both readers for corroboration. [ZeroGen-5 source](../../configs/benchmarks/track_a_natural_layouts.json)

```sh
export HF_HUB_OFFLINE=1
export DOCLING_ARTIFACTS_PATH="$LOCAL_DOCLING_MODELS"
python scripts/benchmark_track_a_source_panels.py \
  --pdf-dir "$ORIGINAL_PDF_DIR" --runs "$SOURCE_RUNS" \
  --models data/interim/ocr_models --out "$SOURCE_RESULTS"
python scripts/benchmark_track_a_cold.py \
  --pdf-dir data/raw/track-a-scale --models data/interim/ocr_models --out "$COLD_RUNS" \
  --only eastern-palm-valley-dailyreport
python scripts/benchmark_track_a_natural_layouts.py \
  --pdf-dir "$ORIGINAL_PDF_DIR" --models data/interim/ocr_models --out "$ROTATION_RUNS" \
  --case zerogen --pages 19 22
```

For the complete FORGE replay, initialize a separate corpus with `SOURCE_RUNS/forge-mudlog_eowr/corpus/config.json`. Add `HadiSlvt-drilling report.pdf` directly and run `process`, `k1` and `qa --fidelity --crossrep --cell-evidence` with the same local models.
