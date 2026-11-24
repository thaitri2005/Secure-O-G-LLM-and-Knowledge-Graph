# Track A operating guide

Track A converts drilling reports into a versioned package of passages, forms, tables and source locations. Quality assurance validates that package against the original PDFs and the associated conversion cache before publishing the retrieval view.

## Prepare the environment

Use Python 3.12 and install Tesseract with English language data. On Debian or Ubuntu, the system packages are `tesseract-ocr` and `tesseract-ocr-eng`. PyMuPDF is supplied by the `qa` extra. Review the dependency and licence details for the intended deployment. [Dependencies](dependencies.md)

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock.txt
python -m pip install --no-deps -e .
tesseract --list-langs
```

The following commands obtain the layout, table and OCR assets. The layout and table files belong under `DOCLING_ARTIFACTS_PATH`, and the OCR files belong under `--models`. Keep the same directories for conversion, export and QA. [Asset provenance and hashes](model-provenance.md)

```sh
export DOCLING_ARTIFACTS_PATH="$PWD/data/interim/docling_assets"
export TRACK_A_OCR_DIR="$PWD/data/interim/ocr_models"

docling-tools models download layout tableformer --output-dir "$DOCLING_ARTIFACTS_PATH"
python -m graph_builder.corpus models --engine rapidocr --models "$TRACK_A_OCR_DIR"
export HF_HUB_OFFLINE=1
```

## Process and validate a corpus

Run the following from the repository root. Replace `/path/to/reports` with a directory of source PDFs.

```sh
TRACK_A_CORPUS=data/corpora/drilling-reports
python -m graph_builder.corpus init "$TRACK_A_CORPUS" \
  --config configs/corpus/drilling_reports_en.json
python -m graph_builder.corpus add "$TRACK_A_CORPUS" /path/to/reports --recursive
python -m graph_builder.corpus process "$TRACK_A_CORPUS" --workers 2 --models "$TRACK_A_OCR_DIR"
python -m graph_builder.corpus status "$TRACK_A_CORPUS"
python -m graph_builder.corpus k1 "$TRACK_A_CORPUS" \
  --name drilling-reports --models "$TRACK_A_OCR_DIR"
```

Set `TRACK_A_RELEASE` to the release directory printed by the `k1` command. Export requires a completed conversion for each included document. A repeated `process` run resumes incomplete work. Add `--retry-failed` to retry failed documents.

The export command reports `document_type_findings` by document ID. With evidence routing enabled, `pdf_title` identifies a recognized source heading, `doc_id` identifies a configured `document_context` type used when the PDF has no recognized heading, and `default` identifies the configured default. Conflicting types within a PDF header keep the default. The finding appears in the command output outside the release package.

```sh
python -m graph_builder.corpus qa "$TRACK_A_CORPUS" \
  --release "$TRACK_A_RELEASE" --models "$TRACK_A_OCR_DIR" \
  --out "$TRACK_A_CORPUS/qa" --crossrep --fidelity --cell-evidence
```

| Output | Use |
| --- | --- |
| `tables.jsonl` | Table cells, spans, headers, physical parts and page coordinates |
| `chunks.jsonl` | K1 passages and their source locations |
| `qa-summary.json` | Release validation and quality signals |
| `cell_evidence.jsonl` | Cell-level source support, review or unavailable evidence |
| `retrieval_chunks.jsonl` and `retrieval-manifest.json` | Validated retrieval view and its checksum binding |

Pass the retrieval view and its companion manifest together to consumers. The K1 release remains the source of table structure and provenance. An `unavailable` cell evidence status means QA lacked sufficient source evidence for that cell. Treat `review` and `ocr_unreadable` as requiring inspection before operational use. [Extraction and QA rules](corpus-ingestion.md)

## Reproduce the validation benchmark

The runner downloads checksum-pinned public sources, verifies the selected inputs, converts the corpus, exports K1, publishes the QA view and scores both against the frozen reference. Select a new output directory for each run. Reuse `--input-dir` to share the source cache across runs. A cache entry is named with its source ID and extension from the manifest.

```sh
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
python scripts/benchmark_track_a_validation.py \
  --output-dir data/interim/track_a_validation/default \
  --input-dir data/interim/track_a_validation/sources \
  --models "$TRACK_A_OCR_DIR" --workers 2
```

Add `--only forge-003` for the single-page completion report, or `--compare-scan-fallbacks` to add the optional scan profile. The latter reuses the same conversion cache. Output contains per-document conversion times, K1 and QA timings, and cell-level discrepancies. [Source manifest](../../configs/benchmarks/track_a_validation_sources.json) · [Frozen reference](../../configs/benchmarks/track_a_validation_reference.json) · [Validation report](../reports/track-a-validation.md)

Run the repository test suite with `python -m unittest discover -s tests`. The suite reports skips when optional packages, PDF fixtures or previous releases are absent. Generated benchmark directories belong under `data/interim/`.
