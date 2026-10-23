# Secure LLM and Knowledge Graph Platform

An on-premise platform under development that will turn technical documents into a reviewed knowledge graph and answer questions with source evidence. Parsing runs locally today; ontology-guided extraction, local model inference, graph storage, review, and question answering are planned. The target is an internal production service for a small team, built by three students using a school research machine.

The intended design supports user-supplied ontologies and evidence-linked facts. The current implementation uses public end-of-well reports from the U.S. DOE [Geothermal Data Repository (GDR)](https://gdr.openei.org). Its downloader and metadata contracts still require GDR inputs; general local uploads and domain-neutral metadata need the adapters described in the project design. Package/model/source acquisition may use the network; enforcing and verifying the production network boundary remains planned work.

## Project documentation

Start with the **[Project description and system design](docs/PROJECT_DESIGN.md)** for the complete product and architecture reference. It covers scope, users, requirements, six architecture/workflow/data diagrams, technology choices, evidence contracts, extraction and review, question answering, security, deployment, hardware estimates, and acceptance criteria. Existing behavior and proposed components are explicitly distinguished.

The **[Development and delivery plan](docs/DEVELOPMENT_PLAN.md)** maps that design to milestones, dependencies, responsibilities for three students, effort estimates, hardware/cloud cost controls, risks, release gates, and the first implementation backlog. Its 20-week example depends on an assumed 12 hours per student per week; it is not an agreed deadline.

For the current subsystem, use [Ingestion details](docs/ingestion.md) and [Ingestion evaluation](docs/ingestion-evaluation.md). The [documentation audit](docs/DOCUMENTATION_AUDIT.md) records what was missing, what these documents now cover, and which checks were performed.

## Components

| Component | Purpose | Status |
|---|---|---|
| Ingestion | PDF to passage chunks with document, page, region and character-offset provenance | Implemented (`graph_builder.ingestion`) |
| Ontology | User-supplied ontology (YAML/JSON) that guides extraction | Planned |
| Graph construction | Extract entities and relations by the ontology, link names to reference lists, merge duplicates | Planned |
| Graph control | Confidence threshold, basic checks, review queue | Planned |
| Graph storage | Graph database in which every fact keeps its source | Planned |
| Admin application | Uploads, review queue, node merging and deletion, re-runs | Planned |
| Question answering | Natural-language questions translated into graph queries | Planned |

The `graph_builder` package holds the stages that build the graph. Ingestion is the first one.

## Setup

Use Python 3.12. The lock file captures the complete Windows CPU environment, including the optional OCR trial dependencies. The base installation needs only pinned Docling and pypdf; EasyOCR and its pins are available through `pip install -e ".[ocr]"`. OCR is disabled in published outputs.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
.\.venv\Scripts\Activate.ps1
```

Bash equivalent: `python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.lock.txt && .venv/bin/python -m pip install -e . --no-deps && source .venv/bin/activate` (the supplied lock includes Windows-specific packages).

## Reproduce the ingestion output

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json
```

This command downloads and verifies the three source PDFs, downloads the Docling models, converts and chunks the reports, and validates the result. Allow about ten minutes on a CPU for the first run. Because the main bundle is published, an unnamed run only succeeds if it reproduces the committed files byte for byte. If anything differs, it fails without changing them. Use a named run (below) to experiment.

Optional model prefetch: `docling-tools models download layout tableformer`. Once the models and PDFs are cached, set `$env:HF_HUB_OFFLINE = "1"` (bash: `export HF_HUB_OFFLINE=1`) to run offline.

Expected SHA256 of `data/processed/gdr_chunks.json`: `b3256ef6d83c709ddc4ba3f3262ad0b56e6273551b49694a3b72f0b880037b9b`. `data/processed/SHA256SUMS` lists the digest of every published main artifact.

The `fetch`, `convert`, `chunk` and `validate` commands run the individual stages with the same `--sources` and `--config` arguments. Other locations:
- downloaded PDFs: ignored `data/raw/`;
- Docling JSON/Markdown caches (ignored): a per-parser-settings subdirectory of `data/interim/docling/`;
- timings and filter statistics: ignored `data/interim/run_log.json`.

## Output

The main bundle in `data/processed/` is the input for graph construction:

| File | Content |
|---|---|
| `gdr_chunks.json` | Array of chunks: `doc_id`, `page`, `chunk_id`, `type`, `text`, `section` |
| `gdr_chunks_full.jsonl` | One record per chunk, in the same order: `content_id`, canonical character offsets, source item/page character spans, regions (PDF points, top-left origin), section path, table reference |
| `gdr_tables.jsonl` | Each table once: cells with spans and header flags, and row-oriented text |
| `documents/<doc_id>.json`, `.txt` | Source metadata and physical-page geometry; canonical text (chunks joined by two newlines) that the offsets index |
| `SHA256SUMS` | Digests of the files above |

Chunk fields:

| Field | Value |
|---|---|
| `doc_id` | Stable identifier from the source registry |
| `page` | Physical PDF page, numbered from 1 |
| `chunk_id` | Unique `{doc_id}#c0000` identifier, numbered continuously per document |
| `type` | `text` or `table` |
| `text` | Nonempty extracted text or Markdown table |
| `section` | Nearest preceding section heading, or `null` |

`content_id` stays stable when document ID, type and whitespace-normalized text are unchanged, even if chunks are renumbered. Identical repeated passages can share it, and changed content produces a new ID; it is a comparison aid, not a unique evidence key. The planned evidence contract also pins the document version, immutable run/bundle and span. The four JSON schemas in `schemas/` describe the current records. All text artifacts are UTF-8 with LF line endings, and geometry is rounded to 0.01 PDF point.

## Experiments

The default configuration (`configs/ingestion/default.json`) uses paragraph chunking, a 1,500-character budget and fast TableFormer. It was selected by measurement. [Evaluation results](docs/ingestion-evaluation.md) report fidelity, gold scores, remaining errors and the commands that reproduce every number.

```powershell
python -m graph_builder.ingestion run --run-name paragraph_1500_fast
python -m graph_builder.ingestion evaluate --run paragraph_1500_fast
python -m graph_builder.ingestion compare --old page_1500_accurate --new paragraph_1500_fast
python -m graph_builder.ingestion publish --run paragraph_1500_fast
```

How named runs work:
- Named runs reuse the verified conversion caches and write to ignored `data/interim/runs/<name>/`.
- Overrides such as `--set max_chars=2000` are only allowed on a named run. `page_1500_accurate` is created with `--set table_mode=accurate --set chunking.strategy=page`.
- Commands that read a saved run (`evaluate`, `compare`, `publish`, `ocr`) reject `--set`.
- `publish` revalidates the run and copies it to the bundle of the `--sources` registry. The default is the main registry.

Two more registries use the same configuration: `configs/sources/gdr_end_of_well_extended.json` (two further reports) and `configs/sources/gdr_ak3_appendices.json` (the AK-3 appendix portfolio, split into 44 PDFs). Their bundles are regenerated locally into ignored `data/processed/local/<registry_name>/`:

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well_extended.json --config configs/ingestion/default.json
python -m graph_builder.ingestion run --sources configs/sources/gdr_ak3_appendices.json --config configs/ingestion/default.json
```

[Published bundle checks](docs/ingestion-evaluation.md#published-bundle-checks) list their expected digests. [Ingestion details](docs/ingestion.md) describe filtering, chunking, validation and known limitations.

## Tests

```powershell
python -m unittest discover -s tests
```

Tests use small synthetic documents. The regression test also re-chunks the cached reports and checks the published SHA256 when all document caches are present.

## Data attribution

The reports were authored by **Geothermal Resource Group, Inc.** and are published in the DOE Geothermal Data Repository under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The chunks are derived text: extracted, filtered and split from these reports, with tables represented as Markdown.

| Report | Source |
|---|---|
| Akutan Geothermal Project, Well AK-3 End of Well Report (2016) | [GDR submission 882](https://gdr.openei.org/submissions/882) |
| Utah FORGE Seismic Monitoring Well 56-32 End of Well Report (2021) | [GDR submission 1295](https://gdr.openei.org/submissions/1295) |
| Utah FORGE Seismic Monitoring Well 68-32 End of Well Report | [GDR submission 1153](https://gdr.openei.org/submissions/1153) |

The [source registry](configs/sources/gdr_end_of_well.json) records the PDF URLs, license URLs, byte sizes and SHA256 digests used to verify the inputs.
