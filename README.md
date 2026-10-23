# Graph Builder

A domain-agnostic Knowledge Graph Builder. The current ingestion stage turns PDF reports into passage chunks with source provenance.

## Setup

Use Python 3.12. The lock file captures the complete Windows CPU environment, including the optional OCR trial dependencies. Base installation requires only pinned Docling and pypdf; EasyOCR and its explicit pins are available through `pip install -e ".[ocr]"`. OCR remains disabled in published outputs.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
.\.venv\Scripts\Activate.ps1
```

Bash equivalent: `python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements.lock.txt && .venv/bin/python -m pip install -e . --no-deps && source .venv/bin/activate` (the supplied lock includes Windows-specific packages).

## Reproduce

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well.json --config configs/ingestion/default.json
```

The first run downloads and verifies the three source PDFs and downloads Docling models. Allow about seven minutes on a CPU, including the initial model download; hardware and network speed affect this estimate. Optional model prefetch: `docling-tools models download layout tableformer` (supported by the pinned version's CLI). Once models are cached, use `$env:HF_HUB_OFFLINE = "1"` for offline model reuse; in bash, `export HF_HUB_OFFLINE=1`. Source PDFs must also be present for a fully offline run.

Expected SHA256 of `data/processed/gdr_chunks.json`: `b3256ef6d83c709ddc4ba3f3262ad0b56e6273551b49694a3b72f0b880037b9b`.

The `fetch`, `convert`, `chunk`, and `validate` commands expose the individual stages with the same `--sources` and `--config` arguments. `convert` reads local verified PDFs; `chunk` uses the complete document cache. Downloads live in ignored `data/raw/`; complete Docling JSON/Markdown and per-document chunks live in a per-parser-settings subdirectory of `data/interim/docling/`; timings and filter statistics live in ignored `data/interim/run_log.json`.

## Experiments and provenance

The measured default uses paragraph continuation, a 1,500-character budget and fast TableFormer. [Evaluation results](docs/ingestion-evaluation.md) report fidelity, gold scores, remaining errors and the selection criteria.

```powershell
python -m graph_builder.ingestion run --run-name paragraph_1500_fast
python -m graph_builder.ingestion evaluate --run paragraph_1500_fast
python -m graph_builder.ingestion compare --old page_1500_accurate --new paragraph_1500_fast
python -m graph_builder.ingestion publish --run paragraph_1500_fast
```

Named runs use verified conversion caches and isolate results in `data/interim/runs/`; `run` without a name performs a fresh conversion. Overrides such as `--set max_chars=2000` require a named run. Evaluate the run before publication. Comparison requires two locally generated named runs; `page_1500_accurate` is generated with `--set table_mode=accurate --set chunking.strategy=page`. Publication validates the current artifacts and selects the destination from the explicit `--sources` registry (the main registry by default). Commands that consume saved runs reject `--set`; configure overrides when creating the run.

The six-field array remains the compatibility output. `gdr_chunks_full.jsonl` adds stable content IDs, canonical character offsets, source item/page character spans, regions, section paths and table references. `gdr_tables.jsonl` stores each table's cells and row-oriented text once. `documents/<doc_id>.json` records source metadata and physical-page geometry; the matching `.txt` is canonical chunk text joined by two newlines. Four JSON schemas describe these records.

All three registries use the same `configs/ingestion/default.json`: paragraph chunking, 1,500 characters and fast TableFormer. Reproduce the additional bundles with the same command, changing only the source registry:

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_end_of_well_extended.json --config configs/ingestion/default.json
python -m graph_builder.ingestion run --sources configs/sources/gdr_ak3_appendices.json --config configs/ingestion/default.json
```

These write `gdr_chunks.json`, matching provenance/table sidecars and `documents/` under the ignored directories `data/processed/local/gdr_end_of_well_extended/` and `data/processed/local/gdr_ak3_appendices/`, respectively. No overrides are needed. Portfolio children are deduplicated by SHA and retain their parent document ID. [Published bundle checks](docs/ingestion-evaluation.md#published-bundle-checks) list the expected digests for all three registries.

## Chunk format

The deliverable is a UTF-8 JSON array in source registry and document reading order, with LF line endings and a final newline. All generated text artifacts use LF; publication normalizes CRLF inputs to LF. Artifact geometry is rounded to two decimals without changing chunk text. `data/processed/SHA256SUMS` records only the nine tracked main artifacts, sorted by relative path. Each secondary directory has its own manifest. Direct output and publication refresh only the destination bundle's manifest.

| Field | Value |
|---|---|
| `doc_id` | Stable identifier from the source registry. |
| `page` | Physical PDF page, numbered from 1. |
| `chunk_id` | Unique `{doc_id}#c0000` identifier, numbered continuously per document. |
| `type` | `text` or `table`. |
| `text` | Nonempty extracted text or Markdown table. |
| `section` | Nearest preceding section heading, or `null`. |

## Tests

```powershell
python -m unittest discover -s tests
```

Tests use small synthetic documents. The cache regression test also runs when all document caches are available. See [ingestion details](docs/ingestion.md) for filtering, validation, results, and extraction limitations.

## Data attribution

All reports were authored by **Geothermal Resource Group** and are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The chunks are derived text: extracted, filtered, and split from these reports, with tables represented as Markdown.

| Report | Source |
|---|---|
| Akutan AK-3 End of Well Report (2016) | [GDR submission 882](https://gdr.openei.org/submissions/882) |
| Utah FORGE well 56-32 End of Well Report (2021) | [GDR submission 1295](https://gdr.openei.org/submissions/1295) |
| Utah FORGE seismic monitoring well 68-32 End of Well Report | [GDR submission 1153](https://gdr.openei.org/submissions/1153) |

The [source registry](configs/sources/gdr_end_of_well.json) records the PDF URLs, license URLs, byte sizes, and SHA256 digests used to verify the inputs.
