# Graph Builder

A domain-agnostic Knowledge Graph Builder. The current ingestion stage turns PDF reports into page-level chunks with source provenance.

## Setup

Use Python 3.12. The lock file captures the Windows CPU environment.

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

Expected SHA256 of `data/processed/gdr_chunks.json`: `70a27d3a4109d00a2c46ba4bca7ee22315b6adb6a71b99b71396d23b19dfbe18`.

The `fetch`, `convert`, `chunk`, and `validate` commands expose the individual stages with the same `--sources` and `--config` arguments. `convert` reads local verified PDFs; `chunk` uses the complete document cache. Downloads live in ignored `data/raw/`; complete Docling JSON/Markdown and per-document chunks live in ignored `data/interim/docling/`; timings and filter statistics live in ignored `data/interim/run_log.json`.

## Chunk format

The deliverable is a UTF-8 JSON array in source registry and document reading order, with LF line endings and a final newline.

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
