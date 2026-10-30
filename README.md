# Secure LLM and Knowledge Graph Platform

A capstone project for the Vietnam Petroleum Institute (VPI): a secure, on-premise **GraphRAG application for drilling reports**.

- It ingests end-of-well and daily drilling reports and parses pages and tables with vision-language models.
- It extracts entities and relations under an ontology the user supplies, and links every well to one ID across documents.
- It answers questions with citations to the source page.

Administrators manage documents, the ontology and the glossary, and correct low-confidence items; end users ask questions. Models are **open-weight and about 7B parameters or smaller**; commercial models and APIs are never used. The direction comes from the [28 October supervisor meeting](docs/requirements/supervisor-meeting-2026-10-28.md). The work is a capstone application, not a research project.

**Start here.**

- The [project specification](docs/PROJECT_DESIGN.md) is the single source of truth.
- The [development plan](docs/DEVELOPMENT_PLAN.md) has the milestones and this week's tasks.
- The [documentation index](docs/README.md) lists everything else.

Development uses public data ([data sources](docs/DATA_SOURCES.md)): [BSEE well data](https://catalog.data.gov/dataset/bsee-data-center-wells-information) for well identity, and drilling reports starting with the [Akutan AK-3 end-of-well report](https://gdr.openei.org/files/882/00%20AK-3%20EOW%20Report.pdf) and its daily reports.

## Status

**29 October:** the design was rewritten for the GraphRAG direction (specification 3.0).

- **Carries over:** ingestion, structured-data import, the entity registry and an extraction/QA prototype.
- **Not built yet:** the GraphRAG pipeline, VLM parsing, object and vector storage, the ID scheme across stores, and the frontend.
- **Next:** ingestion and data organization on one end-of-well and one daily report, then a one-document GraphRAG slice ([plan](docs/DEVELOPMENT_PLAN.md#current-status)).

| Component | Purpose | Status |
|---|---|---|
| Document ingestion | Files to page-provenanced passage and table chunks (Docling, Markdown tables, rows never split) | Implemented ([guide](docs/components/corpus-ingestion.md)); baseline for the VLM comparison |
| VLM page parsing and multi-page tables | Pages and tables to Markdown/HTML with a document VLM; continued tables joined with headers carried | Planned (M1, Track A) |
| Storage and ID scheme | MinIO for files, PostgreSQL for metadata and chunks, a vector store, Neo4j; file → page → parent → child chunk → vector → graph | Planned (IDs in M1 Track A; stores in M2) |
| Structured-data import | CSV/Excel/JSON-lines to typed records with row provenance; BSEE as a mapping | Implemented ([guide](docs/components/dataset-import.md), [E6](docs/experiments/E6-generic-import-bsee.md)) |
| Entity registry | One ID per well; 57,453 wellbores and 39,518 wells from BSEE; identifier or scoped-name resolution | Implemented ([guide](docs/components/entity-registry.md), [E13](docs/experiments/E13-entity-registry-bsee.md)); report linking planned |
| GraphRAG pipeline | Existing open-source base, ontology injection, extraction, embeddings, graph and vector retrieval, cited answers | Planned (M1, Track B); base chosen by comparison |
| Extraction/QA prototype | Ontology file, local LLM extraction, Neo4j, template QA on 15 AK-3 chunks | Implemented as the baseline ([prototype](prototype/README.md), [E10](docs/experiments/E10-profile-driven-prototype.md)) |
| Application | Chat with citations; admin for documents, ontology, glossary, flagged items | Planned (M4) |

## Quick start

Use Python 3.12. The lock file pins the complete Windows CPU environment.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests          # 136 tests, a few minutes with the cached PDF regression
python -m unittest prototype.test_ontology    # 14 prototype tests (profiles, validator, duplicate search, generation check)
```

The lock file is the verified Windows CPU environment. A tested Linux/GPU deployment lock remains to be produced after the host is confirmed; manually omitting Windows-only packages does not establish an equivalent deployment environment.

**Ingest documents** with the current Docling-based pipeline (any mix of PDFs, scans and Office files; OCR needs the extra and a one-time model download). VLM parsing replaces OCR for new work once M1 selects a model:

```powershell
python -m pip install -e ".[ocr]"; python -m pip install --no-deps vietocr==0.3.13
python -m graph_builder.corpus models
python -m graph_builder.corpus init data/corpora/demo
# English workload: set ocr.engine to "rapidocr" in the generated config.json before processing.
python -m graph_builder.corpus add data/corpora/demo D:\docs --recursive
python -m graph_builder.corpus process data/corpora/demo
python -m graph_builder.corpus export data/corpora/demo --name v1
```

**Import structured data** (the BSEE well files: downloads about 4 MB):

```powershell
python -m graph_builder.datasets run --mapping configs/datasets/bsee_wells.mapping.json
python -m graph_builder.datasets infer my_table.xlsx      # draft a mapping for your own data
```

**Reproduce the published PDF bundle** (downloads three PDFs and the Docling models; about ten minutes on a CPU the first time):

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json
```

An unnamed run succeeds only if it reproduces `data/processed/` byte for byte. Use `--run-name <name>` to experiment; see [PDF ingestion](docs/components/pdf-ingestion.md#usage).

## Repository layout

```text
configs/
  corpus/         document pipeline settings (OCR engine, page analysis, chunking, limits)
  registry/       entity-registry configs (bsee_wells.registry.json)
  datasets/       structured-data mappings (bsee_wells.mapping.json) and the earlier BSEE adapter config
  ingestion/      earlier PDF pipeline options (default, Vietnamese OCR)
  sources/        PDF source registries with pinned SHA256 digests
data/
  gold/ingestion/ frozen reference annotations for experiment E1
  processed/      published PDF bundle (committed); local/ holds regenerated bundles (ignored)
  raw/, interim/  downloads, caches, models and named experiment runs (ignored)
docs/
  PROJECT_DESIGN.md     project specification: the single source of truth
  DEVELOPMENT_PLAN.md   status, milestones, risks, backlog (derived from the specification)
  DATA_SOURCES.md       the public proxy data
  requirements/         VPI's requirement documents (digest; originals kept out of Git) and supervisor meeting digests (7 and 28 October)
  components/           guides to implemented subsystems
  experiments/          one record per experiment (E1–E13) and the register
  reports/              Vietnamese progress report of 27 October (historical snapshot)
  diagrams/             SVG exports of the Mermaid diagrams
schemas/          JSON Schemas for every published record type (corpus_* for the document pipeline; evidence, claim, entity for application records)
scripts/          experiment utilities (E2 OCR smoke test, E5 OCR benchmark, E8 AK-3 appendix corpus run)
src/graph_builder/corpus/      document pipeline (python -m graph_builder.corpus)
src/graph_builder/publication.py  immutable releases behind an atomic pointer (exports and dataset bundles)
src/graph_builder/contracts.py    shared evidence, claim-revision and entity records
src/graph_builder/registry.py     entity registry from a dataset bundle, conservative resolver (python -m graph_builder.registry)
src/graph_builder/datasets/    structured-data importer (python -m graph_builder.datasets)
src/graph_builder/ingestion/   earlier PDF pipeline (python -m graph_builder.ingestion) and BSEE adapter (…ingestion.bsee)
src/graph_builder/graph/       earlier BSEE linked graph (python -m graph_builder.graph.bsee)
prototype/        experiments E4/E10: extraction and template-QA prototype on AK-3; the baseline for the GraphRAG pipeline
tests/            unit and regression tests (unittest)
```

For the earlier PDF pipeline, Docling caches live in a per-parser-settings subdirectory of `data/interim/docling/`. A document corpus keeps everything in its own directory (catalog, stored originals, per-document outputs, exports); OCR models live in `data/interim/ocr_models/`. BSEE snapshots live in `data/raw/bsee_wells/`, and the imported bundle in `data/processed/local/datasets/bsee_wells/`.

## Development workflow

- Work on a branch and get a review from another student before merging to `main`.
- Run `python -m unittest discover -s tests` before pushing. Tests use small synthetic fixtures; the PDF regression test also runs when the conversion caches are present.
- Also run `python -m unittest prototype.test_ontology` until the prototype validation is promoted. On 27 October, 136 main tests and 14 prototype tests passed; these checks do not validate live services, GPU performance or private-data readiness ([E9](docs/experiments/E9-repository-review.md)). CI remains planned.
- Text files use UTF-8 and LF line endings (`.gitattributes`, `.editorconfig`). Generated artifacts must stay byte-reproducible.
- Never commit downloads, caches or BSEE files. They are ignored and regenerable, and BSEE's terms are not an open license.
- When behavior changes, update the component guide and specification §3 in the same change. Scope changes go into the specification first ([conventions](docs/README.md#conventions)).
- Record each new measurement as an experiment ([register](docs/experiments/README.md)), in a named run that cannot overwrite published data.

## Data attribution

The end-of-well reports were authored by **Geothermal Resource Group, Inc.** and are published in the U.S. DOE [Geothermal Data Repository](https://gdr.openei.org) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The committed chunks are derived text: extracted, filtered and split from these reports, with tables represented as Markdown.

| Report | Source |
|---|---|
| Akutan Geothermal Project, Well AK-3 End of Well Report (2016) | [GDR submission 882](https://gdr.openei.org/submissions/882) |
| Utah FORGE Seismic Monitoring Well 56-32 End of Well Report (2021) | [GDR submission 1295](https://gdr.openei.org/submissions/1295) |
| Utah FORGE Seismic Monitoring Well 68-32 End of Well Report | [GDR submission 1153](https://gdr.openei.org/submissions/1153) |

The [source registry](configs/sources/gdr_end_of_well.json) records the PDF URLs, licenses, byte sizes and SHA256 digests used to verify the inputs.

Well data comes from the [BSEE Data Center](https://www.data.bsee.gov/Main/Well.aspx) (U.S. Department of the Interior), subject to the [BSEE disclaimer](https://www.bsee.gov/bsee.gov/privacy-disclaimer). It is downloaded locally and not redistributed in this repository.
