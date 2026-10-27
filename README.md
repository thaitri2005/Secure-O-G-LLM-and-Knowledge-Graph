# Secure LLM and Knowledge Graph Platform

A capstone project for the Vietnam Petroleum Institute (VPI): a secure, on-premise **knowledge-graph builder**. It is a domain-agnostic pipeline and admin application that turns documents and datasets into a reviewed knowledge graph, guided by an ontology its users supply. The use case is **oil wells** (drilling and production), initially using **English** documents and questions; well terminology, identifiers, units and query rules belong in a versioned domain profile. The builder comes first, question answering second ([supervisor direction, 7 October](docs/requirements/supervisor-meeting-2026-10-07.md)). Ingestion runs locally; extraction, review, graph storage and cited QA run as a well-specific prototype. Three students are building it on school hardware.

**Start here:** the [project specification](docs/PROJECT_DESIGN.md) is the single source of truth for scope and design. The [documentation index](docs/README.md) lists everything else. Until VPI supplies its own documents, development uses public proxies: [BSEE well data](https://catalog.data.gov/dataset/bsee-data-center-wells-information) and end-of-well reports, starting with [Akutan AK-3](https://gdr.openei.org/files/882/00%20AK-3%20EOW%20Report.pdf) ([data sources](docs/DATA_SOURCES.md)).

## Status

**27 October review:** document ingestion, structured-data import and the AK-3 prototype exist as separate paths; their integration remains open. The next milestone is the builder slice: an ontology loaded from a file rather than code, extraction with reference resolution, duplicate search, and a real reviewer publishing into a validated graph generation. Cited QA follows, then access control. The publication, dataset-identity, header and generation-check defects from the [repository assessment](docs/REPOSITORY_REVIEW_2026-10-27.md) are fixed and covered by tests ([E11](docs/experiments/E11-publication-and-import-fixes.md)); cache-identity and redirect-check findings remain open. See the updated [development plan](docs/DEVELOPMENT_PLAN.md#7-next-implementation-backlog) and [progress report](docs/reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md).

| Component | Purpose | Status |
|---|---|---|
| Document ingestion | PDF, scans, images, DOCX, PPTX, XLSX, HTML and Markdown to passage and table chunks with page, region and section provenance; per-page OCR decision; Vietnamese OCR (VietOCR); quality flags; resumable, parallel, exportable | Implemented ([guide](docs/components/corpus-ingestion.md), [E5](docs/experiments/E5-ocr-engine-benchmark.md), [E7](docs/experiments/E7-corpus-pipeline-smoke.md)) |
| Structured-data import | CSV, Excel and JSON-lines files (also inside ZIPs) to typed records and a linked graph, described by one mapping file; every record and edge cites its file, digest and row | Implemented ([guide](docs/components/dataset-import.md)); BSEE reproduced exactly ([E6](docs/experiments/E6-generic-import-bsee.md)) |
| BSEE well data and linked graph | Wellbores linked to wells, operators, leases, blocks, fields and former records. Seed of the entity registry | Implemented as a mapping ([mapping](configs/datasets/bsee_wells.mapping.json)); earlier [dedicated adapter](docs/components/bsee-ingestion.md) kept |
| Published GDR PDF bundle | Byte-reproducible chunks of three end-of-well reports, used by experiments E1–E4 | Implemented ([details](docs/components/pdf-ingestion.md)) |
| Core schema and entity registry | Generic entities, opaque IDs and evidence/claim contracts; profile-declared types and scoped English aliases | Contracts and schemas ([E12](docs/experiments/E12-shared-evidence-contract.md)); registry built from BSEE by config with conservative resolution ([guide](docs/components/entity-registry.md), [E13](docs/experiments/E13-entity-registry-bsee.md)); PostgreSQL storage and report linking planned |
| Domain profiles | One `oil_wells` application; reusable core/profile contracts | Prototype ontology v0.1 (14 properties); well-specific extraction/QA still to externalize. Other domains, interpretation/expert-note workflows and multilingual rollout later |
| Ontology management and graph curation | Load, edit, version and AI-draft the ontology in an admin application; reference resolution; duplicate-node search and merge; confidence-routed review | Specified ([§5.9, §6.5](docs/PROJECT_DESIGN.md#59-builder-controls-nodes-connections-and-curation)); not started |
| Report knowledge (AK-3) | LLM extraction with quotes, validation, review, graph generations, cited QA | Prototype on 15 AK-3 chunks ([experiment E4](docs/experiments/E4-ak3-architecture-prototype.md)); production version planned |
| Review, graph storage, question answering | Review queue; graph in which every fact keeps its evidence; supported questions answered from graph queries with citations | Prototype; production version planned |

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

**Ingest documents** (any mix of PDFs, scans and Office files; OCR needs the extra and a one-time model download):

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
  requirements/         VPI's requirement documents (digest; originals kept out of Git) and supervisor meeting digests
  components/           guides to implemented subsystems
  experiments/          one record per experiment (E1–E13) and the register
  reports/              updated Vietnamese progress report (editable Markdown)
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
prototype/        experiment E4: test build of the target stack on AK-3 (Neo4j, PostgreSQL, llama.cpp, FastAPI); not the system
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
