# Vietnamese and multilingual PDF ingestion

The normal ingestion pipeline now supports opt-in OCR, including Vietnamese and mixed Vietnamese–English PDFs. Text, tables, chunk offsets, and PDF regions continue through the existing provenance and validation stages. The original English GDR configuration and published data remain unchanged.

## Setup and model acquisition

Use the pinned environment from the README. The OCR extra is required. Download model assets explicitly while connected, before offline processing:

```powershell
.\.venv\Scripts\python -m graph_builder.ingestion.ocr_models --languages vi en
.\.venv\Scripts\docling-tools models download layout tableformer
```

The first command prepares EasyOCR's compatible recognition/detection models in `data/interim/ocr_models/` and records their SHA256 hashes. OCR runtime downloads are disabled. Vietnamese requires the Latin recognition model; the English-only model from the old appendix trial is insufficient. EasyOCR supports Vietnamese (`vi`) and English (`en`) together; other language combinations must be supported by EasyOCR and evaluated independently. [Official language support](https://www.jaided.ai/easyocr/).

## Register a local document

```powershell
.\.venv\Scripts\python -m graph_builder.ingestion.register "D:\Documents\bao_cao.pdf" --registry data/interim/local_sources.json --doc-id bao_cao --title "Báo cáo kỹ thuật"
```

Registration records source size and SHA256, rejects encrypted/non-PDF inputs, enforces 50 MiB and 300-page limits, and prevents duplicate document IDs. It does not upload or modify the original. The `private` license marker means no public license was asserted; it does not establish permission to process the document. Supply `--license-id` and `--license-url` when appropriate. Keep private source registries under ignored `data/interim/`.

## Run, inspect, and evaluate

```powershell
$env:DOCLING_ARTIFACTS_PATH = Join-Path $env:USERPROFILE ".cache/docling/models"
$env:HF_HUB_OFFLINE = "1"
.\.venv\Scripts\python -m graph_builder.ingestion run --sources data/interim/local_sources.json --config configs/ingestion/vietnamese.json --run-name vietnamese_v1
.\.venv\Scripts\python -m graph_builder.ingestion evaluate --sources data/interim/local_sources.json --run vietnamese_v1
```

For offline runs, `DOCLING_ARTIFACTS_PATH` must point to the directory printed by `docling-tools models download`. Prefetching alone did not make the default Hugging Face snapshot lookup work on the development machine. The example above uses the default Windows download location.

Outputs are under `data/interim/runs/vietnamese_v1/`. Inspect chunks, shared tables, canonical documents, and the `ocr` section in each document JSON. This section records effective OCR settings and page-level attributed-character counts. Scanned pages with no attributed content fail artifact validation; scanned pages with fewer than 40 attributed characters are marked `review`. These are coverage heuristics, not recognition-accuracy or confidence measurements. A genuinely blank scanned page may require manual investigation. `needs_ocr` describes the original PDF's scan characteristics, not whether the completed OCR run failed.

OCR requires a named run, including when enabled directly in a configuration file. Publishing remains an explicit action after evaluation; do not replace the main GDR publication with an unrelated source registry.

## Modes and languages

`configs/ingestion/vietnamese.json` enables OCR with `languages: ["vi", "en"]`, `mode: "auto"`, and `confidence_threshold: 0.5`. Auto mode retains useful PDF text and allows Docling to OCR image regions. Full-page mode is available for scans or PDFs with an unreliable text layer:

```powershell
.\.venv\Scripts\python -m graph_builder.ingestion run --sources data/interim/local_sources.json --config configs/ingestion/vietnamese.json --run-name vietnamese_full_page --set ocr.mode=full_page
```

Mode, language list, and confidence threshold participate in the conversion-cache key. The confidence threshold filters OCR detections; increasing it can lose legitimate Vietnamese text. Benchmark changes instead of assuming a higher threshold improves the document. GPU execution is not enabled in this CPU baseline.

Conversion cache manifests bind source bytes, parser versions/settings, OCR model hashes, and JSON/Markdown output hashes. Corrupt or mismatched caches are rebuilt during conversion. Older caches without a manifest are converted again. Chunking-only commands still require a correctly prepared conversion cache.

## Evaluation and limitations

Use human-transcribed reference text to compute character error rate (CER) and word error rate (WER) with `graph_builder.ingestion.ocr_metrics.score_ocr`. Metrics normalize Unicode to NFC and whitespace, while preserving case, digits, and Vietnamese diacritics. Empty references return undefined rates (`None`), alongside edit counts. Rates can exceed 1 when the OCR inserts substantial extra text.

Evaluate clean scans, degraded scans, mixed text/image pages, tables, and numerical units separately. Synthetic examples establish integration behavior only; a real Vietnamese corpus is required before claiming production accuracy. Handwriting, severe skew, poor resolution, complex reading order, and merged table cells remain limitations. The pipeline does not use an LLM to silently repair recognized text, because that could alter evidence.

After prefetching models, `scripts/ocr_smoke.py --run` creates an image-only Vietnamese PDF, ingests it through the normal pipeline, and writes the CER/WER report to ignored `data/interim/ocr_smoke/`. Its method and results are recorded as [experiment E2](../experiments/E2-vietnamese-ocr-smoke.md).

The historical `ocr --run ...` command remains an appendix-only comparison experiment. Normal OCR ingestion uses `run` with the OCR profile above.

Headings intentionally become section metadata in the current chunker, so an end-to-end CER/WER against a full-page reference includes that representation difference. It must not be described as a pure OCR recognition score; inspect section metadata alongside canonical text. The general evaluator compares against the PDF text layer, so scans without reference text report undefined precision and recall rather than a misleading zero. Use human references and `score_ocr` to measure scan accuracy.

OCR rejects the `pypdf` chunking strategy because it reads only the original text layer. Invalid registry values fail with validation errors, and malformed cache manifests are rebuilt. This CLI is not a concurrent upload service; authentication, process isolation, transactional publication and a representative Vietnamese quality benchmark remain future work.

Measurements: [experiment E2](../experiments/E2-vietnamese-ocr-smoke.md).
