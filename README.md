# Secure LLM and Knowledge Graph Platform

An on-premise platform, under development, that turns oil-and-gas well data and technical well reports into a reviewed knowledge graph, and answers questions with source evidence. Ingestion runs locally today. Ontology-guided extraction with a local model, graph storage, review and question answering are planned. The target is an internal service for a small team, built by three students on a school research machine.

> **Current development focus (25 October 2026).** Following the supervisor's guidance, development targets two sources:
>
> - **[BSEE Data Center – Wells Information](https://catalog.data.gov/dataset/bsee-data-center-wells-information)**: structured records for about 57,000 offshore boreholes. Ingestion is implemented.
> - **End-of-well reports, starting with [Akutan AK-3](https://gdr.openei.org/files/882/00%20AK-3%20EOW%20Report.pdf)**: the document type to extract knowledge from. It is already ingested.
>
> Read **[Development focus and data sources](docs/DATA_SOURCES.md)** before starting new work.

## Status

| Component | Purpose | Status |
|---|---|---|
| PDF ingestion | PDF to passage chunks with page, region and character-offset provenance; optional OCR | Implemented ([details](docs/ingestion.md)) |
| BSEE well-data ingestion | BSEE well files to typed borehole, well and API-change records with row provenance | Implemented ([details](docs/bsee-ingestion.md)) |
| Ontology | Versioned well-domain vocabulary that guides extraction | Planned; first draft from AK-3 and BSEE |
| Graph construction | Extract claims, link them to wells by API number and scoped names, merge duplicates | Planned |
| Review and graph storage | Review queue; graph in which every fact keeps its evidence | Planned |
| Question answering | Supported questions translated into graph queries, with citations | Planned |

## Quick start

Use Python 3.12. The lock file pins the complete Windows CPU environment.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests          # about 100 tests, under a minute
```

On Linux or macOS: `python3.12 -m venv .venv && source .venv/bin/activate`, then the same `pip` commands. The lock file includes Windows-only packages (for example `pywin32`); install the rest manually if needed. The OCR extra is optional: `pip install -e ".[ocr]"` ([OCR guide](docs/ocr-ingestion.md)).

**Ingest the BSEE well data** (downloads about 4 MB; takes about two minutes including validation):

```powershell
python -m graph_builder.ingestion.bsee run
python -m graph_builder.ingestion.bsee show --api 1772140041
```

**Reproduce the published PDF bundle** (downloads three PDFs and the Docling models; about ten minutes on a CPU the first time):

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json
```

An unnamed run succeeds only if it reproduces `data/processed/` byte for byte. Use `--run-name <name>` to experiment; see [PDF ingestion](docs/ingestion.md#usage).

## Repository layout

```text
configs/
  datasets/       structured-data configurations (BSEE)
  ingestion/      PDF pipeline options (default, Vietnamese OCR)
  sources/        PDF source registries with pinned SHA256 digests
data/
  gold/           frozen reference annotations for ingestion evaluation
  processed/      published PDF bundle (committed); local/ holds regenerated bundles (ignored)
  raw/, interim/  downloads, caches and named runs (ignored)
docs/             design, plan, data sources, subsystem guides; start at docs/README.md
schemas/          JSON Schemas for every published record type
scripts/          one-off utilities (OCR smoke test)
src/graph_builder/ingestion/   PDF pipeline (python -m graph_builder.ingestion) and BSEE adapter (…ingestion.bsee)
tests/            unit and regression tests (unittest)
```

Docling caches live in a per-parser-settings subdirectory of `data/interim/docling/`. BSEE snapshots live in `data/raw/bsee_wells/`, and their bundle in `data/processed/local/bsee_wells/`.

## Documentation

The [documentation index](docs/README.md) gives the reading order. The main documents are:

- [Development focus and data sources](docs/DATA_SOURCES.md): what we build on now, and why.
- [Project description and system design](docs/PROJECT_DESIGN.md): architecture, data model, extraction, QA, security, operations, acceptance gates.
- [Development and delivery plan](docs/DEVELOPMENT_PLAN.md): milestones, responsibilities, risks, next backlog.
- [Related work](docs/references.md): papers and resources from the supervisor.

## Development workflow

- Work on a branch and get a review from another student before merging to `main`.
- Run `python -m unittest discover -s tests` before pushing. Tests use small synthetic fixtures; the PDF regression test also runs when the conversion caches are present.
- Text files use UTF-8 and LF line endings (`.gitattributes`, `.editorconfig`). Generated artifacts must stay byte-reproducible.
- Never commit downloads, caches or BSEE files. They are ignored and regenerable, and BSEE's terms are not an open license.
- When behavior changes, update the subsystem document and design §3 in the same change.

## Data attribution

The end-of-well reports were authored by **Geothermal Resource Group, Inc.** and are published in the U.S. DOE [Geothermal Data Repository](https://gdr.openei.org) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The committed chunks are derived text: extracted, filtered and split from these reports, with tables represented as Markdown.

| Report | Source |
|---|---|
| Akutan Geothermal Project, Well AK-3 End of Well Report (2016) | [GDR submission 882](https://gdr.openei.org/submissions/882) |
| Utah FORGE Seismic Monitoring Well 56-32 End of Well Report (2021) | [GDR submission 1295](https://gdr.openei.org/submissions/1295) |
| Utah FORGE Seismic Monitoring Well 68-32 End of Well Report | [GDR submission 1153](https://gdr.openei.org/submissions/1153) |

The [source registry](configs/sources/gdr_end_of_well.json) records the PDF URLs, licenses, byte sizes and SHA256 digests used to verify the inputs.

Well data comes from the [BSEE Data Center](https://www.data.bsee.gov/Main/Well.aspx) (U.S. Department of the Interior), subject to the [BSEE disclaimer](https://www.bsee.gov/bsee.gov/privacy-disclaimer). It is downloaded locally and not redistributed in this repository.
