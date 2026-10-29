# Experiment register

**Current direction (28 October 2026):** a GraphRAG application for drilling reports on open-weight models of about 7B or smaller ([specification](../PROJECT_DESIGN.md)). Historical experiments keep their data and results. The next experiments, numbered from E14, are the table evaluation and VLM comparison, the GraphRAG base comparison on one document, and the embedding comparison. E4/E10 are the baseline those must match ([plan](../DEVELOPMENT_PLAN.md#7-next-implementation-backlog)). Every new record also reports model endpoint, calls, tokens and cost.

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
| [E10](E10-profile-driven-prototype.md) | Prototype driven by an ontology file | 27 Oct 2026 | Reports | `prototype/profiles/`, `prototype/kgproto/profile.py` | Ontology loaded from a validated file; a synthetic second ontology runs unchanged. Profile-driven code with the E4 prompt: precision 0.968, recall 0.732; end-to-end 23/31 (E4: 19/31), 0 wrong values. A generic prompt assembly lost precision (0.87) and was dropped |
| [E11](E11-publication-and-import-fixes.md) | E9 defects fixed and rerun as regression tests | 27 Oct 2026 | Integration readiness | `graph_builder/publication.py`, `tests/test_publication.py`, `tests/test_datasets.py` | Interrupted publication keeps the current release; failed validation, duplicate record IDs and duplicate headers block publication; prototype generations checked against the exact accepted set |
| [E12](E12-shared-evidence-contract.md) | Shared evidence, claim and entity contract on real outputs | 27 Oct 2026 | Integration | `graph_builder/contracts.py`, `schemas/{evidence,claim,entity}.schema.json` | All 1,778 AK-3 appendix chunks and 58,040 BSEE records become schema-valid evidence with unique, release-pinned IDs |
| [E13](E13-entity-registry-bsee.md) | Entity registry from BSEE and conservative resolution | 27 Oct 2026 | BSEE | `graph_builder/registry.py`, `configs/registry/bsee_wells.registry.json` | 57,453 wellbores and 39,518 wells registered by config; name + suffix + lease resolves 98.6% of wellbores, the rest go to review, 0 wrong matches |

## Adding an experiment

1. Take the next ID (E14, E15, …) and copy the header table of an existing record.
2. State the question and the requirement or decision it informs before running anything.
3. Use a named run (`--run-name`) or a separate directory so that the experiment cannot overwrite published data or another experiment's outputs. Keep large outputs in ignored `data/interim/`. Commit only small result summaries.
4. Freeze any gold data before tuning, and say whether the result is a development or held-out score. Record the model endpoint (hosted or local), model and version, calls, tokens and cost.
5. Record what changed between runs, the results, and what was learned, then add a row above. If the result changes the design, update the [specification](../PROJECT_DESIGN.md) in the same change.

## Method-evaluation workstream (historical)

The WebNLG/2Wiki/EOR method evaluations and the expanded BSEE graph are reported in the [27 October progress report](../reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md). Their code lives in a team member's separate repository and is **no longer planned for import**: the capstone is not a research project (specification D-41), so method comparisons now run only on drilling documents inside the GraphRAG pipeline. Treat those numbers as background, not as evidence for this repository.
