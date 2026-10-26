# Secure LLM and Knowledge Graph Platform

A capstone project for the Vietnam Petroleum Institute (VPI): a secure, on-premise platform, under development, that turns oil-and-gas technical documents and well data into reviewed, domain-specific knowledge graphs over a shared entity registry, and answers questions with source evidence. Ingestion runs locally today. Ontology-guided extraction with a local model, graph storage, review and question answering run as a prototype. Three students build it on a school research machine.

**Start here:** the [project specification](docs/PROJECT_DESIGN.md) is the single source of truth for scope and design. The [documentation index](docs/README.md) lists everything else. Until VPI supplies its own documents, development uses public proxies: [BSEE well data](https://catalog.data.gov/dataset/bsee-data-center-wells-information) and end-of-well reports, starting with [Akutan AK-3](https://gdr.openei.org/files/882/00%20AK-3%20EOW%20Report.pdf) ([data sources](docs/DATA_SOURCES.md)).

## Status

| Component | Purpose | Status |
|---|---|---|
| PDF ingestion | PDF to passage chunks with page, region and character-offset provenance; optional OCR | Implemented ([details](docs/components/pdf-ingestion.md)) |
| BSEE well-data ingestion | BSEE well files to typed borehole, well and API-change records with row provenance | Implemented ([details](docs/components/bsee-ingestion.md)) |
| BSEE linked graph | Wellbores linked to wells, operators, leases, blocks, fields and former records; every edge cites its BSEE row. Seed of the entity registry | Implemented ([details](docs/components/bsee-ingestion.md#linked-graph)) |
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
python -m unittest discover -s tests          # 108 tests, under a minute
```

On Linux or macOS: `python3.12 -m venv .venv && source .venv/bin/activate`, then the same `pip` commands. The lock file includes Windows-only packages (for example `pywin32`); install the rest manually if needed. The OCR extra is optional: `pip install -e ".[ocr]"` ([OCR guide](docs/components/ocr-ingestion.md)).

**Ingest the BSEE well data** (downloads about 4 MB; takes about two minutes including validation):

```powershell
python -m graph_builder.ingestion.bsee run
python -m graph_builder.ingestion.bsee show --api 1772140041
```

**Reproduce the published PDF bundle** (downloads three PDFs and the Docling models; about ten minutes on a CPU the first time):

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json
```

An unnamed run succeeds only if it reproduces `data/processed/` byte for byte. Use `--run-name <name>` to experiment; see [PDF ingestion](docs/components/pdf-ingestion.md#usage).

## Repository layout

```text
configs/
  datasets/       structured-data configurations (BSEE)
  ingestion/      PDF pipeline options (default, Vietnamese OCR)
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
  experiments/          one record per experiment (E1–E4) and the register
  diagrams/             SVG exports of the Mermaid diagrams
schemas/          JSON Schemas for every published record type
scripts/          experiment utilities (E2 OCR smoke test)
src/graph_builder/ingestion/   PDF pipeline (python -m graph_builder.ingestion) and BSEE adapter (…ingestion.bsee)
src/graph_builder/graph/       BSEE linked graph (python -m graph_builder.graph.bsee)
prototype/        experiment E4: test build of the target stack on AK-3 (Neo4j, PostgreSQL, llama.cpp, FastAPI); not the system
tests/            unit and regression tests (unittest)
```

Docling caches live in a per-parser-settings subdirectory of `data/interim/docling/`. BSEE snapshots live in `data/raw/bsee_wells/`, and their bundle in `data/processed/local/bsee_wells/`.

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
