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

**24 November:** the second build is coded in all three tracks and runs end to end on a laptop, with a stand-in in place of the model (specification 3.5, [plan](docs/DEVELOPMENT_PLAN.md#current-status)).

- **Connected:** chunk packages with stable IDs (K1 version 1) are loaded into the stores (PostgreSQL with pgvector, Neo4j) by one command; the GraphRAG engine reads the stores; a backend and a React frontend sit on top, behind one shared password, as containers.
- **Built, not yet measured:** the coordinator that picks a lane per question, with four lanes behind one interface (passages, well facts, events, reasoning about causes).
- **Not done:** any run of the new parts with a real model; a server. The team has no GPU of its own now, so measurements need a hosted open-weight model on public data or the school GPUs.
- **Next:** measure, then put it on a server ([task list](docs/DEVELOPMENT_PLAN.md#7-what-to-do-now)).

All question sets so far are simulated; none is expert-reviewed.

| Component | Purpose | Status |
|---|---|---|
| Document ingestion and K1 packages | Files to pages, tables, forms and chunks with stable IDs, a validator and a QA sidecar (Docling, plus rules for known table formats) | Implemented in `src/graph_builder/corpus/` ([guide](docs/components/corpus-ingestion.md), [Track A](docs/tracks/A-ingestion/README.md)); tuned on one report family |
| VLM page parsing | Pages and tables with a document VLM | Not run; rule-based methods come first (D-63) |
| Stores and ID scheme | PostgreSQL with pgvector for chunks and vectors, Neo4j for the graph; file → page → parent → child chunk → vector → graph | Implemented in `platform/` ([guide](platform/README.md), [Track C](docs/tracks/C-storage/log.md)): one command loads a release, each step checked. On laptops; no server yet |
| GraphRAG engine | Retrieval by well and date, a per-well fact graph, an event graph, a reasoning lane for causes, a coordinator over them, answers with citations checked in code | Implemented in `graphrag/` ([README](graphrag/README.md), [Track B](docs/tracks/B-graphrag/log.md)), reading files or the stores; the coordinator and the reasoning lane are tested with stand-in models and not yet measured |
| Application | A FastAPI backend and a React frontend for people who read drilling reports; a question log; Docker deployment behind one password | Implemented in `backend/`, `frontend/` and `deploy/` ([backend](backend/README.md), [frontend](frontend/README.md), [runbook](deploy/README.md)); run on a laptop with a stub model, not on a server |
| Structured-data import | CSV/Excel/JSON-lines to typed records with row provenance; BSEE as a mapping | Implemented ([guide](docs/components/dataset-import.md), [E6](docs/experiments/E6-generic-import-bsee.md)) |
| Entity registry | One ID per well; 57,453 wellbores and 39,518 wells from BSEE; identifier or scoped-name resolution | Implemented ([guide](docs/components/entity-registry.md), [E13](docs/experiments/E13-entity-registry-bsee.md)); report linking planned (M3) |
| Extraction/QA prototype | Ontology file, local LLM extraction, Neo4j, template QA on 15 AK-3 chunks | Kept as the measured baseline ([prototype](prototype/README.md), [E10](docs/experiments/E10-profile-driven-prototype.md)) |
| Application | Chat with citations, source page and evidence; later, admin for documents, ontology, glossary and flagged items | Second build (M2). The backend's read path ([backend/](backend/README.md)) and the React frontend ([frontend/](frontend/README.md)) exist; neither has run against a real model or the stores. A local developer UI exists (`python -m graphrag.ui`) |

## Quick start

Use Python 3.12. The lock file pins the complete Windows CPU environment. It includes the OCR packages and PyMuPDF, which the test suite and the QA scripts need (the `qa` extra in `pyproject.toml`).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests          # about 1,190 tests, a few minutes with the cached PDF regression
python -m unittest prototype.test_ontology    # 14 prototype tests (profiles, validator, duplicate search, generation check)
```

The lock file is the verified Windows CPU environment (`pywin32` is marked Windows-only). A tested Linux/GPU deployment lock remains to be produced after the host is confirmed; manually omitting Windows-only packages does not establish an equivalent deployment environment. Without the lock, `pip install -e ".[ocr,qa]"` installs the same pinned packages.

**PyMuPDF licence.** PyMuPDF is licensed under AGPL-3.0 or a commercial Artifex licence. Only tests and QA scripts import it; nothing under `src/graph_builder` does. Build any environment you deploy or distribute without it (`pip install ".[ocr]"`), and see [dependencies](docs/components/dependencies.md) before shipping anything that includes it. Model files and their digests are in [model provenance](docs/components/model-provenance.md).

Three tests in `tests/test_graphrag.py` skip because they need the separate `requirements-graphrag.lock.txt` environment (Track B). Tests that need the public PDFs in `data/raw`, cached Docling conversions or earlier K1 releases skip when those files are absent.

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
  requirements/         VPI's requirement documents (digest; originals kept out of Git) and supervisor meeting digests (7 and 28 October, 9 November)
  components/           guides to implemented subsystems
  tracks/               each track's dated record of findings and decisions (A ingestion, B GraphRAG engine, C storage)
  experiments/          one record per experiment (E1–E31) and the register
  reports/              stint reports in stints/ (one per stint, with a PDF); slides in slides/; the project report; the resource request
  diagrams/             SVG exports of the Mermaid diagrams
graphrag/         the GraphRAG engine: model client, retrieval, both graphs, cited answers, a local developer UI (python -m graphrag.ui)
platform/         the stores: Docker Compose (PostgreSQL with pgvector, Neo4j), SQL, loaders and checks; scripts run by path
schemas/          JSON Schemas for every published record type (k1_* for chunk packages, k4 for answer records, corpus_* for the document pipeline; evidence, claim, entity for application records)
scripts/          experiment, evaluation and QA utilities; stint_figures.py and render_stint_report.py make a stint report's diagrams and PDF
src/graph_builder/corpus/      document pipeline (python -m graph_builder.corpus)
src/graph_builder/publication.py  immutable releases behind an atomic pointer (exports and dataset bundles)
src/graph_builder/contracts.py    shared evidence, claim-revision and entity records
src/graph_builder/registry.py     entity registry from a dataset bundle, conservative resolver (python -m graph_builder.registry)
src/graph_builder/datasets/    structured-data importer (python -m graph_builder.datasets)
src/graph_builder/ingestion/   earlier PDF pipeline (python -m graph_builder.ingestion) and BSEE adapter (…ingestion.bsee)
src/graph_builder/graph/       earlier BSEE linked graph (python -m graph_builder.graph.bsee)
prototype/        experiments E4/E10: extraction and template-QA prototype on AK-3; the baseline for the GraphRAG pipeline
explorations/     side explorations, not part of the system
tests/            unit and regression tests (unittest)
backend/          the read-path API (FastAPI), its OpenAPI description and example responses; python -m uvicorn backend.app:app
frontend/         the React application; npm run dev:examples needs no server or model
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
