# Experiment register

**Current delivery scope:** a knowledge-graph builder with a user-supplied ontology, applied to one English oil-well use case (specification D-28/D-29). Historical experiments retain their original data, languages and results. Existing Vietnamese OCR remains completed work; second-domain and multilingual rollout are later scope.

Every measurement the project relies on comes from one experiment, recorded in one file here. Experiments are numbered in the order they were run and never renumbered. Each record starts with the same header: date, question, requirement, input, gold data, outputs and status. Other documents link to an experiment instead of copying its numbers.

| ID | Experiment | Date | Track | Code and data | Headline result |
|---|---|---|---|---|---|
| [E1](E1-pdf-ingestion-configuration.md) | PDF ingestion configuration and quality | before 23 Oct 2026 | Reports | `src/graph_builder/ingestion/`, `configs/ingestion/default.json`, `data/gold/ingestion/` | Paragraph chunking, 1,500 characters, fast TableFormer selected; quantity recall 334/335 |
| [E2](E2-vietnamese-ocr-smoke.md) | Vietnamese OCR smoke test | 24–25 Oct 2026 | Reports (languages) | `scripts/ocr_smoke.py`, `configs/ingestion/vietnamese.json` | Integration works on one synthetic page (CER 10.5%); no real-corpus benchmark yet |
| [E3](E3-reproduction-run-2026-10-25.md) | Reproduction run of both ingestion paths | 25 Oct 2026 | Reports and BSEE | Both ingestion CLIs, `graph_builder.graph.bsee` | PDF bundle byte-identical; BSEE 57,453 boreholes with 0 errors; linked graph of 113,384 nodes |
| [E4](E4-ak3-architecture-prototype.md) | Architecture prototype on AK-3 | 25 Oct 2026 | Reports | `prototype/` (separate environment) | Stack works end to end; extraction precision 0.97, recall 0.68 before review; prose recall is the bottleneck |
| [E5](E5-ocr-engine-benchmark.md) | OCR engine benchmark, Vietnamese and English scans | 27 Oct 2026 | Reports (languages) | `scripts/ocr_benchmark.py`, `graph_builder.corpus.ocr_engines` | VietOCR: Vietnamese CER 5.2% and word recall 96% on moderate scans, against 24% CER for EasyOCR; PP-OCR drops Vietnamese marks |
| [E6](E6-generic-import-bsee.md) | BSEE through the generic structured-data importer | 27 Oct 2026 | BSEE | `graph_builder.datasets`, `configs/datasets/bsee_wells.mapping.json` | All 58,040 records identical to the dedicated adapter; same node and edge counts |
| [E7](E7-corpus-pipeline-smoke.md) | Corpus pipeline smoke test | 27 Oct 2026 | Reports | `graph_builder.corpus` | Scan, PDF and Markdown processed, resumed and exported (one worker) |
| [E8](E8-ak3-appendices-corpus-run.md) | AK-3 appendix portfolio through the document pipeline | 27 Oct 2026 | Reports | `scripts/run_ak3_appendices.py`, `graph_builder.corpus` | 44 PDFs, 463 pages (104 OCR'd), 1,778 chunks exported with two workers; validation caught two defects, since fixed; 5 pages flagged, hand-checked |
| [E9](E9-repository-review.md) | Repository review and local verification | 27 Oct 2026 | Integration readiness | Main/prototype tests; temporary fault/input probes | 128 + 4 tests passed; export interruption, duplicate header/ID and calendar-date defects reproduced; fixes open |
| [E10](E10-profile-driven-prototype.md) | Prototype driven by an ontology file | 27 Oct 2026 | Reports | `prototype/profiles/`, `prototype/kgproto/profile.py` | Ontology loaded from a validated file; a synthetic second ontology runs unchanged; date defects fixed; 10 prototype tests pass. Model rerun in progress |
| [E11](E11-publication-and-import-fixes.md) | E9 defects fixed and rerun as regression tests | 27 Oct 2026 | Integration readiness | `graph_builder/publication.py`, `tests/test_publication.py`, `tests/test_datasets.py` | Interrupted publication keeps the current release; failed validation, duplicate record IDs and duplicate headers block publication; prototype generations checked against the exact accepted set |

## Adding an experiment

1. Take the next ID (E10, E11, …) and copy the header table of an existing record.
2. State the question and the requirement or decision it informs before running anything.
3. Use a named run (`--run-name`) or a separate directory so that the experiment cannot overwrite published data or another experiment's outputs. Keep large outputs in ignored `data/interim/`. Commit only small result summaries.
4. Freeze any gold data before tuning, and say whether the result is a development or held-out score.
5. Record what changed between runs, the results, and what was learned, then add a row above. If the result changes the design, update the [specification](../PROJECT_DESIGN.md) in the same change.

## Method-evaluation and graph-construction workstreams

The unified [project progress report](../reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md) covers WebNLG/2Wiki/EOR evaluation, the expanded BSEE graph and replay alongside E1–E10. Preserve the dataset, model/configuration, scorer version and manifest for each run. The method suite has 354 tests; the ingestion/application checks have 136 main and 11 prototype tests. Assign experiment IDs when consolidating these run records into the register. **The code for these method evaluations (and the 354-test suite) is not yet in this repository**: it is in a team member's separate repository. It is to be added under `experiments/` with configs, data scripts, scorers and per-run results ([plan backlog](../DEVELOPMENT_PLAN.md#7-next-implementation-backlog) item 2). Until then, those numbers cannot be rerun from this repository.
