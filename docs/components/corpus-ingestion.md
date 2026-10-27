# Document ingestion (`graph_builder.corpus`)

This guide describes the **implemented generic document pipeline**. It takes documents in many formats, reads every page in the most reliable way available (text layer, OCR of images, or full-page OCR), and produces passage and table chunks with page, region and section provenance. It is the pipeline for new and VPI documents. The older [PDF ingestion](pdf-ingestion.md) pipeline stays in place to reproduce the published GDR bundle and experiments E1–E4.

Measurements: [E5](../experiments/E5-ocr-engine-benchmark.md) (OCR engines), [E7](../experiments/E7-corpus-pipeline-smoke.md) (end-to-end smoke test).

## Setup

Use the README environment, then add the OCR stack:

```powershell
.\.venv\Scripts\python -m pip install -e ".[ocr]"
.\.venv\Scripts\python -m pip install --no-deps vietocr==0.3.13   # its metadata pins old packages; only the model code is used
.\.venv\Scripts\python -m graph_builder.corpus models            # once, online: PP-OCRv6 detector and VietOCR weights, digest-checked
```

Models are stored in `data/interim/ocr_models/`. Conversion never downloads anything: the pipeline sets `HF_HUB_OFFLINE=1` and loads only pinned local files. Docling's layout and table models must have been fetched once, as for the PDF pipeline.

## Workflow

```powershell
python -m graph_builder.corpus init data/corpora/vpi                  # creates config.json, catalog.sqlite, store/, work/, exports/
python -m graph_builder.corpus add data/corpora/vpi D:\docs --recursive --license-id vpi-internal
python -m graph_builder.corpus analyze data/corpora/vpi               # page plan only: how many pages need OCR
python -m graph_builder.corpus process data/corpora/vpi               # convert, chunk, check, validate
python -m graph_builder.corpus status data/corpora/vpi                # done / failed / pending, rejected files
python -m graph_builder.corpus export data/corpora/vpi --name v1      # one bundle of everything done
```

- **`add`** registers files or folders, and also accepts `--url` for HTTPS hosts listed in `allowed_hosts`. Each file is checked from its bytes, not its extension. A copy is stored once under its SHA256 in `store/`, so identical files are registered once and reported as `duplicate`. Rejected files (legacy `.doc`/`.xls`, ZIP archives, encrypted PDFs, files over the limits) are recorded with a reason that says what to do.
- **`process`** handles each document independently and records the result in the catalog. A failure stays with its document and is retried with `--retry-failed`.
  - Re-running skips complete documents (manifest digests verified) and resumes partly converted ones from their cached segments.
  - `--workers N` runs N worker processes. Each loads its own models (about 2–3 GB of RAM), so use 1–2 on a 16 GB machine. A worker that crashes fails only the documents it held.
- **`export`** writes `exports/<name>/` atomically: either the old export or the complete new one is visible. Documents that failed or were never processed are listed under `held_back` in the manifest. `--hold-review` also holds back documents with pages that need review.
- **`retire --only DOC_ID`** removes a document from future exports.

## Supported inputs

| Format | How it is read | Chunk location |
|---|---|---|
| PDF | Per-page plan (below); Docling layout and TableFormer | Page, regions (PDF points, top-left origin), character spans |
| Images (PNG, JPEG, TIFF, BMP, WebP) | Full-page OCR | Page 1 (or frame), regions |
| DOCX, XLSX, HTML, Markdown, plain text | Docling structure, no OCR | `page: null`, section path |
| PPTX | Docling slides | Slide number |

Limits are set in the configuration: 200 MB and 3,000 pages per file by default.

## How each PDF page is read

`analyze` inspects every page with pdfium, without rendering, and assigns a mode ([`analysis.py`](../../src/graph_builder/corpus/analysis.py)):

| Mode | When | Conversion |
|---|---|---|
| `text` | The text layer is complete and well formed | Text layer only |
| `hybrid` | Good text layer, and images cover at least 15% of the page | Text layer, plus OCR of image regions it does not cover |
| `ocr` | Almost no text and a page-sized image (scan) or many vector paths (outlined text); or a garbled text layer | Full-page OCR, text layer ignored |

A text layer counts as garbled if any of these holds:
- replacement, private-use or control characters;
- many words with letters that neither basic Latin nor Vietnamese uses (typical of TCVN3/VNI legacy fonts: "ViÖt" for "Việt");
- many Vietnamese-marked words that are not well-formed syllables.

Invisible text left by a scanner's own OCR is kept when it passes these checks and replaced otherwise.

Pages are converted in segments: consecutive `text` and `hybrid` pages in batches of `segment_pages` (default 40), each `ocr` page on its own. Each segment is cached as gzipped Docling JSON, and the segments are joined with their original page numbers.

## OCR engine

The default engine is PP-OCRv6 text-line detection (ONNX) with VietOCR transformer recognition ([`vietocr_engine.py`](../../src/graph_builder/corpus/vietocr_engine.py)), registered as a Docling OCR plugin. It reads Vietnamese with all its marks as well as English. Set `"ocr": {"engine": "rapidocr"}` for faster English-only corpora; `easyocr` remains for comparison. [E5](../experiments/E5-ocr-engine-benchmark.md) has the measurements. On a laptop CPU, expect roughly 25–50 s per scanned page; text pages take well under a second each after model loading.

## Quality flags

After conversion, the text attributed to each page is profiled with the Vietnamese syllable checker. A page read by OCR gets a status:

| Status | Meaning |
|---|---|
| `ok` | No problems found |
| `review` | More than 8% of its Vietnamese-marked words are malformed, or more than 5% of words use foreign letters |
| `missing` | It yielded fewer than 40 characters |

Chunks on flagged pages carry `"quality": "review"`. The flags are spelling heuristics, not accuracy measurements: a correctly spelled wrong word, such as a wrong tone that forms another real syllable, is not caught. Docling's per-page confidence scores are stored next to them.

## Outputs

Per document, in `work/<doc_id>/<fingerprint>/`:
- `document.json`: source identity, page analysis and quality, processing record;
- `chunks.jsonl`, `tables.jsonl`, `text.txt`;
- `docling.json.gz`: the full converted document;
- `segments/`: the conversion cache;
- `manifest.json`: output digests, written last.

The fingerprint hashes the configuration, the Docling versions and the OCR model digests. Changing any of them creates a new output directory instead of overwriting the old one.

Record schemas: [`corpus_document`](../../schemas/corpus_document.schema.json), [`corpus_chunk`](../../schemas/corpus_chunk.schema.json), [`corpus_table`](../../schemas/corpus_table.schema.json). Chunk offsets index `text.txt`, which is the chunks joined by two newlines. Every document is validated before its manifest is written: schemas, offsets, digests, regions inside the page, and table references.

## Limitations

- Handwriting, stamps, heavy skew and multi-column reading order on scans are not evaluated; [E5](../experiments/E5-ocr-engine-benchmark.md) used rendered pages.
- VietOCR lacks some symbols ("°").
- Multi-worker processing and very large files have not been exercised yet ([E7](../experiments/E7-corpus-pipeline-smoke.md)).
- Legacy-encoded PDFs are re-read by OCR rather than decoded from their font encoding.
