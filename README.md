# Secure LLM and Knowledge Graph Platform

A capstone project for the Vietnam Petroleum Institute (VPI): a secure, on-premise platform, under development, that turns oil-and-gas technical documents and well data into reviewed, domain-specific knowledge graphs over a shared entity registry, and answers questions with source evidence. Ingestion runs locally today. Ontology-guided extraction with a local model, graph storage, review and question answering run as a prototype. Three students is building it on a school machine.

**Start here:** the [project specification](docs/PROJECT_DESIGN.md) is the single source of truth for scope and design. The [documentation index](docs/README.md) lists everything else. Until VPI supplies its own documents, development uses public proxies: [BSEE well data](https://catalog.data.gov/dataset/bsee-data-center-wells-information) and end-of-well reports, starting with [Akutan AK-3](https://gdr.openei.org/files/882/00%20AK-3%20EOW%20Report.pdf) ([data sources](docs/DATA_SOURCES.md)).

## Status

| Component | Purpose | Status |
|---|---|---|
| Document ingestion | PDF, scans, images, DOCX, PPTX, XLSX, HTML and Markdown to passage and table chunks with page, region and section provenance; per-page OCR decision; Vietnamese OCR (VietOCR); quality flags; resumable, parallel, exportable | Implemented ([guide](docs/components/corpus-ingestion.md), [E5](docs/experiments/E5-ocr-engine-benchmark.md), [E7](docs/experiments/E7-corpus-pipeline-smoke.md)) |
| Structured-data import | CSV, Excel and JSON-lines files (also inside ZIPs) to typed records and a linked graph, described by one mapping file; every record and edge cites its file, digest and row | Implemented ([guide](docs/components/dataset-import.md)); BSEE reproduced exactly ([E6](docs/experiments/E6-generic-import-bsee.md)) |
| BSEE well data and linked graph | Wellbores linked to wells, operators, leases, blocks, fields and former records. Seed of the entity registry | Implemented as a mapping ([mapping](configs/datasets/bsee_wells.mapping.json)); earlier [dedicated adapter](docs/components/bsee-ingestion.md) kept |
| Published GDR PDF bundle | Byte-reproducible chunks of three end-of-well reports, used by experiments E1–E4 | Implemented ([details](docs/components/pdf-ingestion.md)) |
| Core ontology and entity registry | Shared entity types and identifiers, language-tagged names, relation categories | Specified ([§5.7, §6](docs/PROJECT_DESIGN.md#6-ontology-layer-and-domain-modules)); not started |
| Domain modules | Wells and drilling; subsurface interpretation (competing interpretations, expert notes) | Wells and drilling: prototype ontology v0.1 (14 properties). Subsurface interpretation: specified ([§5.8](docs/PROJECT_DESIGN.md#58-interpretations-competing-hypotheses-and-expert-knowledge)) |
| Report knowledge (AK-3) | LLM extraction with quotes, validation, review, graph generations, cited QA | Prototype on 15 AK-3 chunks ([experiment E4](docs/experiments/E4-ak3-architecture-prototype.md)); production version planned |
| Review, graph storage, question answering | Review queue; graph in which every fact keeps its evidence; supported questions answered from graph queries with citations | Prototype; production version planned |

## Quick start

Use Python 3.12. The lock file pins the complete Windows CPU environment.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests          # 128 tests, under a minute
```

On Linux or macOS: `python3.12 -m venv .venv && source .venv/bin/activate`, then the same `pip` commands. The lock file includes Windows-only packages (for example `pywin32`); install the rest manually if needed.

**Ingest documents** (any mix of PDFs, scans and Office files; OCR needs the extra and a one-time model download):

```powershell
python -m pip install -e ".[ocr]"; python -m pip install --no-deps vietocr==0.3.13
python -m graph_builder.corpus models
python -m graph_builder.corpus init data/corpora/demo
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
  requirements/         VPI's requirement documents: digest (originals kept out of Git)
  components/           guides to implemented subsystems
  experiments/          one record per experiment (E1–E8) and the register
  diagrams/             SVG exports of the Mermaid diagrams
schemas/          JSON Schemas for every published record type (corpus_* for the document pipeline)
scripts/          experiment utilities (E2 OCR smoke test, E5 OCR benchmark, E8 AK-3 appendix corpus run)
src/graph_builder/corpus/      document pipeline (python -m graph_builder.corpus)
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
