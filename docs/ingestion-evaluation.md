# Ingestion evaluation

## Method and default selection

Evaluation uses spatially filtered pypdf text as an imperfect reference. Emitted character spans are attributed to source items and physical pages, including Docling provenance character spans. Serializer tokens are aligned to their source items; unmatched serializer tokens remain in the precision denominator. Merged table rows retain their physical source pages, while repeated headers retain the original header page. Substantive pages contain more than 200 retained reference characters. Word scores use distinct alphanumeric tokens; quantity recall uses normalized drilling numbers and units.

Select among validated ingestion configurations in this order: quantity recall; minimum then median substantive-page word recall; gold grid-cell accuracy; short text chunks; mid-sentence endings. The unfiltered pypdf control lacks table structure and sections and fails validation. Hybrid uses a 512-token budget, which does not satisfy the character limit, and is not publishable.

The selected configuration is paragraph chunking, 1,500 characters, fast TableFormer, cell matching enabled, CPU, OCR off, and optional compact tables, page merging and rotation retry disabled. Fast improves quantity recall (334/335 versus 331/335), substantive minimum/median recall (0.4423/0.9538 versus 0.1340/0.9528), and nine-grid gold cell accuracy (0.7037 versus 0.4344). It therefore meets the requirement of being no worse on the first three criteria. It also reduces short/mid-sentence text chunks to 116/116. This choice does not meet every aspirational fidelity target and regresses form-value recall from 59/60 to 51/60; that separate form metric is reported explicitly.

## Automatic and gold comparison

Gold cell accuracy is micro-averaged over data cells of all nine grids. The tenth annotation is a form and has a separate value-recall score. Extended and appendix rows use the shared default configuration. Gold columns are configuration-level scores over cached gold documents, not registry-specific scores; runs whose registry contains no gold documents display `-`, while automatic metrics use only the registry's own pages. Short chunks are text chunks below 200 characters; mid-sentence means not ending in `. ! ? :`. Seconds/page was measured once on the reference machine and is not reproducible; a dash means no measured conversion time. Timing columns are excluded from all reproducibility claims.

| Run | Quantity recall | Substantive min | Substantive median | Gold cells | Form values | Short | Mid-sentence | Chunks | Seconds/page (measured once on the reference machine; not reproducible) | Valid |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| page_1500_accurate | 0.9881 | 0.1340 | 0.9528 | 0.4344 | 0.9833 | 124 | 134 | 360 | 2.3561 | True |
| pypdf_naive | 1.0000 | 0.9863 | 1.0000 | 0.0000 | 0.9833 | 37 | 175 | 232 | - | False |
| paragraph_1500_accurate | 0.9881 | 0.1340 | 0.9528 | 0.4344 | 0.9833 | 121 | 123 | 355 | - | True |
| paragraph_1000_accurate | 0.9881 | 0.1340 | 0.9528 | 0.4344 | 0.9833 | 125 | 126 | 390 | - | True |
| paragraph_2000_accurate | 0.9881 | 0.1340 | 0.9528 | 0.4344 | 0.9833 | 118 | 123 | 337 | - | True |
| paragraph_1500_fast | 0.9970 | 0.4423 | 0.9538 | 0.7037 | 0.8500 | 116 | 116 | 372 | 1.5557 | True |
| hybrid_512tokens_accurate | 0.9851 | 0.0773 | 0.9539 | 0.4344 | 0.9833 | 20 | 64 | 263 | - | False |
| paragraph_1500_accurate_structured | 0.9881 | 0.0825 | 0.9524 | 0.4262 | 0.9833 | 119 | 122 | 321 | - | True |
| extended_paragraph_1500_fast | 0.9624 | 0.4907 | 0.9091 | - | - | 194 | 191 | 458 | 2.5601 | True |
| appendices_paragraph_1500_fast | 0.9754 | 0.0902 | 0.9346 | 0.7037 | 0.8500 | 669 | 792 | 1633 | 1.4812 | True |

## Table and page annotations

Table matching uses document, physical page and maximum bounding-box IoU, independently of parser item references. Grid comparison normalizes whitespace only; en dash and hyphen remain different. Leading annotated header rows are excluded from data-cell accuracy and scored separately. Merged cells occupy the top-left location only. Forms are scored by whether each nonempty value appears in page-attributed chunk text, without positional comparison.

| Gold table | Accurate data cells | Fast data cells | Accurate headers | Fast headers | Fast row count | Fast column count |
|---|---:|---:|---:|---:|---|---|
| akutan_abbreviations | 1.0000 | 0.9800 | - | - | False | True |
| forge_directional_survey | 0.0474 | 1.0000 | 0.3000 | 0.2000 | True | True |
| forge_fluid_parameters | 0.9000 | 0.9000 | - | - | True | True |
| akutan_directional_survey | 0.9706 | 0.9882 | 0.2000 | 0.1000 | True | True |
| akutan_daily_operations | 1.0000 | 1.0000 | 1.0000 | 1.0000 | True | True |
| akutan_bit_summary | 0.0556 | 0.0427 | 0.3077 | 0.1154 | False | False |
| akutan_casing | 1.0000 | 1.0000 | 1.0000 | 1.0000 | True | True |
| akutan_cement | 1.0000 | 1.0000 | 1.0000 | 1.0000 | True | True |
| akutan_mud | 0.2292 | 0.7500 | - | - | False | True |

Reading order uses Kendall tau on common item IDs only; absent items and additional predicted items are counted separately. An item with multiple boxes appears once at its first occurrence. Section accuracy compares the nearest preceding retained heading per common item. With fewer than two common items tau is undefined. ID-based page scores become less comparable when a different parser configuration changes item IDs.

| Run | Mean defined tau | Section matches/items | Missing items | Extra items |
|---|---:|---:|---:|---:|
| page_1500_accurate | 0.0738 | 75/106 | 0 | 0 |
| pypdf_naive | - | 0/0 | 106 | 0 |
| paragraph_1500_accurate | 0.0738 | 75/106 | 0 | 0 |
| paragraph_1000_accurate | 0.0738 | 75/106 | 0 | 0 |
| paragraph_2000_accurate | 0.0738 | 75/106 | 0 | 0 |
| paragraph_1500_fast | 0.3423 | 74/105 | 1 | 1 |
| hybrid_512tokens_accurate | 0.0738 | 75/106 | 0 | 0 |
| paragraph_1500_accurate_structured | 0.7897 | 72/103 | 3 | 2 |
| extended_paragraph_1500_fast | - | - | - | - |
| appendices_paragraph_1500_fast | 0.3423 | 74/105 | 1 | 1 |

## Validation and remaining errors

Offsets and source-region validity are 100% for the Docling runs. Named-run determinism checks repeat chunking from cached conversions; full fresh-conversion checks are reported separately. The indivisible table unit is the complete header plus exactly one body row. Oversized single-row parts warn; oversized parts with multiple body rows fail, and text keeps the hard limit. A lone row rendered above a Markdown separator is a headerless single-row table. Separator padding is not an exception.

| Run | Oversized single-row warnings |
|---|---:|
| page_1500_accurate | 17 |
| pypdf_naive | 0 |
| paragraph_1500_accurate | 17 |
| paragraph_1000_accurate | 18 |
| paragraph_2000_accurate | 17 |
| paragraph_1500_fast | 20 |
| hybrid_512tokens_accurate | 0 |
| paragraph_1500_accurate_structured | 9 |
| extended_paragraph_1500_fast | 0 |
| appendices_paragraph_1500_fast | 5 |

Five remaining error examples:

1. The 56-32 directional survey has nine predicted columns in accurate mode versus ten in gold; fast recovers the data grid but still scores only 0.20 on its two header rows.
2. AK-3 abbreviations gain an extra row in fast mode (26 versus 25), with one data-cell mismatch.
3. The 56-32 fluid-parameter table scores 18/20; printed dash distinctions are preserved in gold and are not normalized away.
4. The rotated 68-32 daily form on physical page 17 retains only 51/60 annotated values under the selected configuration, despite fast mode improving the aggregate grid score.
5. The appendix bit-summary table has clipped labels and a wide grid that the parser does not reconstruct exactly; the daily-operations page also has reading-order tau 0.3692 and section accuracy 56/87.

## Corpus and OCR

The main registry has three reports and 155 pages; the extended registry adds two reports and 170 pages. The appendix portfolio has 88 attachment aliases that deduplicate to 44 PDFs and **463 pages**, rather than the preliminary 226-page estimate. There are **67 scanned pages** in the drilling-plan and permit documents. The optional OCR trial increased extracted words from 49 to **12,112** across those pages. This supports evaluating OCR for those documents in the Spring work; OCR remains disabled in every published deliverable. All three published registries use the same default configuration: paragraph chunking, 1,500 characters and fast TableFormer. No registry-specific overrides are required.

Rotation retry accepted 68-32 pages 18, 19, 30 and 31 only when both populated-cell count and word recall improved; page 17 was rejected. Optional compact/merged/rotated processing remains available for experiments.

## Limitations

Visual review of the selected run's three lowest-recall substantive pages (56-32 physical pages 23, 24 and 25) shows dense ten-column directional-survey grids with stacked coordinate headers and decimal values. They are text-layer pages, not scans. Automatic token comparisons on these numeric tables are sensitive to PDF extraction and digit-spacing normalization. The rotated daily form on 68-32 page 17 visibly consists of several labelled blocks rather than one rectangular data grid; its separate form-value score is therefore essential.

Gold was produced by a **single annotator with AI-assisted transcription** from rendered pages, cross-checked against the PDF text layer. There is **no inter-annotator agreement** measurement. The ten tables and five pages are a small indicative sample. Corrected gold is immutable and no thresholds were tuned against its scores. The pypdf reference has kerning, rotation and text-order artifacts; low automatic recall is not proof of source-content loss. Set-based metrics do not detect all duplicates or semantic rearrangements. Table serialization flattens stacked headers; shared cell records preserve their original spans. Hybrid's conservative table references identify source tables, not exact row-level fragments, and its character-limit failures exclude it from publication. Exact byte reproducibility is referenced to the locked Windows CPU environment.

## Additional validation measures

Repeated-line leakage is a candidate count, not a confirmed footer-error count. The selected run has 34 repeated 56-32 report-title lines; visual review found no standalone footer page numbers. The remaining quantity miss is `9105ft` on 56-32 physical page 43; the PDF reference has digit-kerning ambiguity. These candidates remain reported and are not removed from the metric.

| Run | Median word precision | Repeated-line candidates | Offset match | Valid regions | Cached determinism |
|---|---:|---:|---:|---:|---|
| appendices_paragraph_1500_fast | 0.9615 | 6598 | 1.0000 | 1.0000 | True |
| page_1500_accurate | 1.0000 | 34 | 1.0000 | 1.0000 | True |
| hybrid_512tokens_accurate | 1.0000 | 35 | 1.0000 | 1.0000 | True |
| extended_paragraph_1500_fast | 1.0000 | 56 | 1.0000 | 1.0000 | True |
| paragraph_1000_accurate | 1.0000 | 34 | 1.0000 | 1.0000 | True |
| paragraph_1500_accurate | 1.0000 | 34 | 1.0000 | 1.0000 | True |
| paragraph_1500_fast | 1.0000 | 34 | 1.0000 | 1.0000 | True |
| paragraph_2000_accurate | 1.0000 | 34 | 1.0000 | 1.0000 | True |
| pypdf_naive | 0.9200 | 368 | 1.0000 | 1.0000 | True |
| paragraph_1500_accurate_structured | 1.0000 | 34 | 1.0000 | 1.0000 | True |

## Published bundle checks

Every registry reproduces with `run --sources <registry> --config configs/ingestion/default.json`, without overrides. Shared structures, row-range reconstruction, canonical offsets and source regions pass validation in all three bundles.

| Registry | Documents | Pages | Chunks | Text | Table | Validation errors | Warnings |
|---|---:|---:|---:|---:|---:|---:|---:|
| Main | 3 | 155 | 372 | 237 | 135 | 0 | 20 |
| Extended | 2 | 170 | 458 | 373 | 85 | 0 | 0 |
| Appendices | 44 | 463 | 1633 | 1276 | 357 | 0 | 20 |

Main warnings are the documented indivisible single-body-row table parts. The appendix warnings comprise five such parts and 15 documents without tables; the extended bundle has no warnings.

Geometry is rounded to two decimals (0.01 PDF point) at artifact serialization, including regions, cell bboxes when present, page sizes and floating character spans. Chunk text and integer offsets are not rounded. Two complete fresh CPU conversions of every registry produced byte-identical chunks, provenance, shared tables and canonical documents; both passes validated with exit 0. The main bundle is at `data/processed/`; secondary bundles are regenerable, ignored artifacts under `data/processed/local/<registry_name>/`. Each LF manifest lists only its registry's chunk JSON, two sidecars and document pairs, sorted by relative POSIX path. Expected chunk and manifest SHA256 values:

| Registry | Chunk SHA256 | SHA256SUMS SHA256 |
|---|---|---|
| Main | `b3256ef6d83c709ddc4ba3f3262ad0b56e6273551b49694a3b72f0b880037b9b` | `60051a67db944c1f53c0d689641f17eab4e2717eeda27e73f6cb7dec7a419085` |
| Extended | `130b357054723d0d542fdd0ac36877741d0c7e35a9e5b655413ab93ede96313a` | `df4c135d926a11e948a7a8f78102018ab05a34d801691c3e92de1156e4563ed5` |
| Appendices | `cfe9e785181eeeaa62c02390ce3e5ffd47508d1b63c0fd0522af83b68707e0e2` | `e168381c683806e2bbab84814c2a0295e157c7093eb4552779c26b680c5cdb32` |

The main manifest covers nine tracked artifacts. The extended and appendix manifests cover seven and 91 artifacts, respectively; each excludes itself.

All generated and published text artifacts, schemas and the default configuration contain no CRLF. The test suite checks this for the full run and publication path.

The main content-ID comparison against the `page_1500_accurate` run gives 241 kept, 42 changed, 89 added and 77 removed chunks. A clean-room reproduction (fresh virtual environment from the lock file, editable install, fresh verified PDF downloads) reproduces every SHA256 above.

## Reproducing these numbers
Run after the README setup and one normal `run` of each registry, so that PDFs and Docling models are cached. The OCR extra installs from packages already pinned in the lock file.

```powershell
$env:HF_HUB_OFFLINE = "1"
python -m pip install --no-index --no-deps --no-build-isolation -e ".[ocr]"
python -m graph_builder.ingestion run --sources configs/sources/gdr_ak3_appendices.json --config configs/ingestion/default.json --run-name appendices_paragraph_1500_fast
python -m graph_builder.ingestion run --sources configs/sources/gdr_ak3_appendices.json --config configs/ingestion/default.json --run-name appendices_page_1500_accurate --set table_mode=accurate --set chunking.strategy=page
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well_extended.json --config configs/ingestion/default.json --run-name extended_paragraph_1500_fast
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well_extended.json --config configs/ingestion/default.json --run-name extended_page_1500_accurate --set table_mode=accurate --set chunking.strategy=page
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json --run-name page_1500_accurate --set table_mode=accurate --set chunking.strategy=page
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json --run-name pypdf_naive --set table_mode=accurate --set chunking.strategy=pypdf
if ($LASTEXITCODE -ne 1) { throw "Expected the control to fail validation" }
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json --run-name paragraph_1500_accurate --set table_mode=accurate
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json --run-name paragraph_1000_accurate --set table_mode=accurate --set max_chars=1000
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json --run-name paragraph_2000_accurate --set table_mode=accurate --set max_chars=2000
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json --run-name paragraph_1500_fast
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json --run-name hybrid_512tokens_accurate --set table_mode=accurate --set chunking.strategy=hybrid
if ($LASTEXITCODE -ne 1) { throw "Expected the control to fail validation" }
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json --run-name paragraph_1500_accurate_structured --set table_mode=accurate --set tables.compact=true --set tables.merge_pages=true --set tables.rotation_retry=true
python -m graph_builder.ingestion evaluate --run appendices_paragraph_1500_fast
python -m graph_builder.ingestion evaluate --run appendices_page_1500_accurate
python -m graph_builder.ingestion evaluate --run extended_paragraph_1500_fast
python -m graph_builder.ingestion evaluate --run extended_page_1500_accurate
python -m graph_builder.ingestion evaluate --run page_1500_accurate
python -m graph_builder.ingestion evaluate --run pypdf_naive
python -m graph_builder.ingestion evaluate --run paragraph_1500_accurate
python -m graph_builder.ingestion evaluate --run paragraph_1000_accurate
python -m graph_builder.ingestion evaluate --run paragraph_2000_accurate
python -m graph_builder.ingestion evaluate --run paragraph_1500_fast
python -m graph_builder.ingestion evaluate --run hybrid_512tokens_accurate
python -m graph_builder.ingestion evaluate --run paragraph_1500_accurate_structured
python -m graph_builder.ingestion publish --run paragraph_1500_fast
python -m graph_builder.ingestion publish --run extended_paragraph_1500_fast --sources configs/sources/gdr_end_of_well_extended.json
python -m graph_builder.ingestion publish --run appendices_paragraph_1500_fast --sources configs/sources/gdr_ak3_appendices.json
python -m graph_builder.ingestion compare --old page_1500_accurate --new paragraph_1500_fast
python -c "from pathlib import Path; from docling.models.stages.ocr.easyocr_model import EasyOcrModel; EasyOcrModel.download_models(recognition_models=['english_g2'], local_dir=Path('data/interim/ocr_models'))"
python -m graph_builder.ingestion ocr --run appendices_paragraph_1500_fast
```
