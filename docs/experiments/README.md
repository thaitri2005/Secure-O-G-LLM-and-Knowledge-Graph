# Experiment register

Every measurement the project relies on comes from one experiment, recorded in one file here. Experiments are numbered in the order they were run and never renumbered. Each record starts with the same header: date, question, requirement, input, gold data, outputs and status. Other documents link to an experiment instead of copying its numbers.

| ID | Experiment | Date | Track | Code and data | Headline result |
|---|---|---|---|---|---|
| [E1](E1-pdf-ingestion-configuration.md) | PDF ingestion configuration and quality | before 23 Oct 2026 | Reports | `src/graph_builder/ingestion/`, `configs/ingestion/default.json`, `data/gold/ingestion/` | Paragraph chunking, 1,500 characters, fast TableFormer selected; quantity recall 334/335 |
| [E2](E2-vietnamese-ocr-smoke.md) | Vietnamese OCR smoke test | 24–25 Oct 2026 | Reports (languages) | `scripts/ocr_smoke.py`, `configs/ingestion/vietnamese.json` | Integration works on one synthetic page (CER 10.5%); no real-corpus benchmark yet |
| [E3](E3-reproduction-run-2026-10-25.md) | Reproduction run of both ingestion paths | 25 Oct 2026 | Reports and BSEE | Both ingestion CLIs, `graph_builder.graph.bsee` | PDF bundle byte-identical; BSEE 57,453 boreholes with 0 errors; linked graph of 113,384 nodes |
| [E4](E4-ak3-architecture-prototype.md) | Architecture prototype on AK-3 | 25 Oct 2026 | Reports | `prototype/` (separate environment) | Stack works end to end; extraction precision 0.97, recall 0.68 before review; prose recall is the bottleneck |
| [E5](E5-ocr-engine-benchmark.md) | OCR engine benchmark, Vietnamese and English scans | 27 Oct 2026 | Reports (languages) | `scripts/ocr_benchmark.py`, `graph_builder.corpus.ocr_engines` | VietOCR: Vietnamese CER 5.2% and word recall 96% on moderate scans, against 24% CER for EasyOCR; PP-OCR drops Vietnamese marks |
| [E6](E6-generic-import-bsee.md) | BSEE through the generic structured-data importer | 27 Oct 2026 | BSEE | `graph_builder.datasets`, `configs/datasets/bsee_wells.mapping.json` | All 58,040 records identical to the dedicated adapter; same node and edge counts |
| [E7](E7-corpus-pipeline-smoke.md) | Corpus pipeline smoke test | 27 Oct 2026 | Reports | `graph_builder.corpus` | Scan, PDF and Markdown processed, resumed and exported; multi-worker run not yet exercised |

## Adding an experiment

1. Take the next ID (E8, E9, …) and copy the header table of an existing record.
2. State the question and the requirement or decision it informs before running anything.
3. Use a named run (`--run-name`) or a separate directory so that the experiment cannot overwrite published data or another experiment's outputs. Keep large outputs in ignored `data/interim/`. Commit only small result summaries.
4. Freeze any gold data before tuning, and say whether the result is a development or held-out score.
5. Record what changed between runs, the results, and what was learned, then add a row above. If the result changes the design, update the [specification](../PROJECT_DESIGN.md) in the same change.
