# Document ingestion (`graph_builder.corpus`)

**Direction (28 October 2026):** a GraphRAG application for drilling reports on open-weight models of about 7B or smaller ([specification](../PROJECT_DESIGN.md), [meeting](../requirements/supervisor-meeting-2026-10-28.md)). This guide records implemented behavior only. This pipeline is the current parser and chunker and the **baseline** for the VLM comparison (specification D-39, §5.10). Its row-safe Markdown table chunks carry over; OCR-engine tuning (VietOCR, RapidOCR, EasyOCR) is no longer planned work, and the engines remain for reproduction. Planned additions are VLM page parsing, multi-page table joining, parent/child chunk IDs and object storage (§5.11).

This guide describes the **implemented generic document pipeline**. It takes documents in many formats, reads every page in the most reliable way available (text layer, OCR of images, or full-page OCR), and produces passage and table chunks with page, region and section provenance. It is the pipeline for new and VPI documents. The older [PDF ingestion](pdf-ingestion.md) pipeline stays in place to reproduce the published GDR bundle and experiments E1–E4.

Measurements: [E5](../experiments/E5-ocr-engine-benchmark.md) (OCR engines), [E7](../experiments/E7-corpus-pipeline-smoke.md) (end-to-end smoke test), [E8](../experiments/E8-ak3-appendices-corpus-run.md) (AK-3 appendix portfolio: 44 PDFs, 463 pages, two workers).

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
# For the English workload, set ocr.engine to "rapidocr" in config.json before processing.
python -m graph_builder.corpus add data/corpora/vpi D:\docs --recursive --license-id vpi-internal
python -m graph_builder.corpus analyze data/corpora/vpi               # page plan only: how many pages need OCR
python -m graph_builder.corpus process data/corpora/vpi               # convert, chunk, check, validate
python -m graph_builder.corpus status data/corpora/vpi                # done / failed / pending, rejected files
python -m graph_builder.corpus export data/corpora/vpi --name v1      # one bundle of everything done
python -m graph_builder.corpus k1 data/corpora/vpi --name k1 --models data/interim/ocr_models   # K1 chunk package of the PDFs done
```

- **`add`** registers files or folders, and also accepts `--url` for HTTPS hosts listed in `allowed_hosts`. Each file is checked from its bytes, not its extension. A copy is stored once under its SHA256 in `store/`, so identical files are registered once and reported as `duplicate`. Rejected files (legacy `.doc`/`.xls`, ZIP archives, encrypted PDFs, files over the limits) are recorded with a reason that says what to do.
- **`process`** handles each document independently and records the result in the catalog. A failure stays with its document and is retried with `--retry-failed`.
  - Re-running skips complete documents (manifest digests verified) and resumes partly converted ones from their cached segments.
  - `--workers N` runs N worker processes. Each loads its own models (about 2–3 GB of RAM), so use 1–2 on a 16 GB machine. A worker that crashes fails only the documents it held.
- **`export`** stages a complete bundle, checks it against its `SHA256SUMS`, and only then publishes it as an immutable release, `exports/<name>/releases/<UTC time>-<digest>/`. `exports/<name>/CURRENT.json` names the current release and is switched with one atomic file replacement. An interruption at any step leaves the previous release current and complete, and the previous release is kept so a reader that resolved it can finish ([`publication.py`](../../src/graph_builder/publication.py)). Readers resolve the current release once with `graph_builder.publication.current_release(exports/<name>)`; an export written before this change (flat files in `exports/<name>/`) is still read until the next export of that name. Documents that failed or were never processed are listed under `held_back`. `--hold-review` also holds back documents with pages that need review.
- **`k1`** writes the PDF documents that are done as a K1 chunk package in the same release layout as `export` (see [K1 chunk package](#k1-chunk-package)). `--only DOC_ID...` selects documents, `--k1-config` names the settings file, and `--legacy-chunks data/processed/gdr_chunks_full.jsonl` adds the old-to-new chunk id map. Use the same `--models` as for `process`, so that the processed documents are found.
- **`retire --only DOC_ID`** removes a document from future exports.
- **Run logs.** Every command also writes a timestamped log to `<corpus>/logs/`. `process` logs one line per finished document (pages, OCR pages, chunks, tables, review and missing pages, time), elapsed time, pages done and an ETA, plus a heartbeat every minute naming the documents still in progress.
- **AK-3 appendix example.** [`scripts/run_ak3_appendices.py`](../../scripts/run_ak3_appendices.py) downloads and verifies the AK-3 appendix portfolio, splits it into 44 PDFs, and runs `init`, `add`, `process`, `export` and `status` on `data/corpora/ak3_appendices`. Use `--workers 2` to run faster, and `--scanned-only` to process only the PDFs with scanned pages. Results: [E8](../experiments/E8-ak3-appendices-corpus-run.md).

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

The default engine is PP-OCRv6 text-line detection (ONNX) with VietOCR transformer recognition ([`vietocr_engine.py`](../../src/graph_builder/corpus/vietocr_engine.py)), registered as a Docling OCR plugin. It reads Vietnamese with all its marks as well as English. For English pages, `"ocr": {"engine": "rapidocr"}` measured better on the E5 English sample. Further OCR-engine tuning is not planned: VLM page parsing replaces it (specification D-39). The code default remains VietOCR until configuration is explicitly selected; `easyocr` remains for comparison. [E5](../experiments/E5-ocr-engine-benchmark.md) has the measurements. On a laptop CPU, expect roughly 25–50 s per scanned page; text pages take well under a second each after model loading.

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

It does not yet include the collected OCR runtime versions or complete pipeline/layout/table-model identity. Process-local converter reuse also keys only on format/mode. Changed runtimes or repeated library calls with different configurations can therefore reuse stale work; complete fingerprinting and configuration-aware reuse are open fixes ([E9](../experiments/E9-repository-review.md)).

Record schemas: [`corpus_document`](../../schemas/corpus_document.schema.json), [`corpus_chunk`](../../schemas/corpus_chunk.schema.json), [`corpus_table`](../../schemas/corpus_table.schema.json). Chunk offsets index `text.txt`, which is the chunks joined by two newlines. Every document is validated before its manifest is written: schemas, offsets, digests, regions inside the page, and table references.

## K1 chunk package

`k1` turns finished corpus output into the package that Track B reads (specification §5.11). It runs after `process` and changes nothing in the corpus chunk format, the fingerprint or the existing exports. Only PDFs are exported; other formats, and documents that failed or were not processed, are listed under `held_back` in the manifest with a reason. This is a Track A proposal; Track C reviews the schemas. Results and measurements: [E30](../experiments/E30-k1-version-1-candidate.md).

| Module | Job |
|---|---|
| [`k1_build.py`](../../src/graph_builder/corpus/k1_build.py) | Builds the records of one document: ids, parents, forms, report context, page rebuild text |
| [`forms.py`](../../src/graph_builder/corpus/forms.py), [`text_layer.py`](../../src/graph_builder/corpus/text_layer.py) | Pairs form labels with values from the PDF text layer, using a template |
| [`report_context.py`](../../src/graph_builder/corpus/report_context.py) | Finds the report date and well of each daily-report page |
| [`table_recognition.py`](../../src/graph_builder/corpus/table_recognition.py), [`ops_tables.py`](../../src/graph_builder/corpus/ops_tables.py) | Recognise and rebuild the RIMBase "Operations Summary" table of a daily-report page from the PDF text layer (rule `table_rules.operations_summary`): recognition gates and reason registry, then rows, self-checks and merge |
| [`k1_export.py`](../../src/graph_builder/corpus/k1_export.py) | Writes and publishes the package, with `SHA256SUMS` |
| [`k1_validate.py`](../../src/graph_builder/corpus/k1_validate.py) | Checks schemas, references, offsets, checksums, page rebuild and context coverage before the release becomes current |
| [`legacy_ids.py`](../../src/graph_builder/corpus/legacy_ids.py) | Maps old chunk ids to K1 ids by text |
| [`k1_config.py`](../../src/graph_builder/corpus/k1_config.py) | Loads `configs/corpus/k1.json` |

**Files in a package.** `files.jsonl`, `pages.jsonl`, `tables.jsonl`, `forms.jsonl`, `parents.jsonl` and `chunks.jsonl` (one JSON record per line), `text/<file_id>.txt` (the text that chunk offsets index), `manifest.json`, `SHA256SUMS`, and `legacy_chunk_ids.json` when `--legacy-chunks` is given. The package has no timestamps or absolute paths, so the same inputs give byte-identical `SHA256SUMS`.

**Ids.**

| Id | Form | Example |
|---|---|---|
| File | `f` + first 16 hex digits of the PDF SHA256 | `f673c77409ffeafb7` |
| Page, table, section parent, form parent | `<file_id>:p<n>`, `:t<n>`, `:s<n>`, `:f<n>` | `f673c77409ffeafb7:t3` |
| Chunk | `<parent id>:c<n>` | `f673c77409ffeafb7:s5:c0` |

K1 ids contain no `#`. Tables are one logical table per corpus table (`parts` has one element); joining tables across pages is not done yet. Table chunks keep the `row_start` and `row_end` the corpus wrote.

**`doc_id` policy.** The end-of-well report keeps its registry id (`add --doc-id gdr882_ak3_eowr`). The daily-report attachments keep the catalog default, a slug of the file name plus 8 hex digits of the SHA256. These ids are hyphenated and keep `dailyreport` and `-appx-NN-`, which Track B uses to find the daily reports and their appendix number.

**Forms.** A form is paired only when a page matches the RIMBase template (`configs/corpus/rimbase_form_template.json`: at least 40% of its labels and the text `Operations Summary`). Generic colon pairing is off (`forms.generic` in `configs/corpus/k1.json`) because it reached about 61% exact pairs in the exploration; pages that do not match the template get no form chunk. Each form is a parent of type `form` with one chunk of `Key: value` lines.

**Report context.** Chunks of daily reports (`report_context.document_types` in `configs/corpus/k1.json`) carry `context.report_date` and `context.well`. The verified template form supplies them first. Pages without a form use the regular expressions in `report_context.date_patterns` and `well_patterns` on the PDF text layer. When both exist and disagree, the form wins and the manifest lists the page under `form_conflicts`. A passage that crosses a change of report date is split. A daily-report page with no context must be listed under `pages_without_context`, or validation fails.

**Operations Summary tables.** Docling merges the `Operations Description` and `Non-Prod` headers of this table, can move the `X` mark to another column, spills words into other cells and on some pages finds no table. For document types listed in `table_rules.operations_summary.document_types` (`configs/corpus/k1.json`; absent means no rule), the PDF text layer of the page is read instead, in two layers. [`table_recognition.py`](../../src/graph_builder/corpus/table_recognition.py) decides from evidence on the page itself whether it holds this table format, and says why not when it does not. [`ops_tables.py`](../../src/graph_builder/corpus/ops_tables.py) reads the rows of a recognised table, runs the self-checks and merges the result into the K1 chunks and tables. The rule is configuration, not code: the title words, the column labels and kinds, the value patterns, the annotation kinds, the recognition thresholds and the tolerances are the `schema`, `recognition` and `tolerances` blocks of `table_rules.operations_summary`, validated by `k1_config.py` when the file is loaded. Every distance is a fraction of the text height of the page itself (`em_title`, `em_header`) or of the page width, never a point value, so a scaled page gives the same result.

*Supported format* (checked by four gates, each with a different kind of evidence):

| Gate | Evidence | Requirement |
|---|---|---|
| G0 | precondition | the page is upright (rotation 0) |
| G1 | words | the title words sit next to each other on a line; every other word of that line is an annotation in a column of its own (far from the title in `em_title`), not a sentence glued to it |
| G2 | geometry and structure | the line right under the title holds all column labels of the schema, once each, in order and left to right (other splits of the same words are accepted) |
| G3 | meaning | the next line starts with two time tokens |

A line with only one of the title words (the header `... Operations Description ...`, a `Management Summary` title) is not a mention of the table. Annotations on the title line, such as `1 record not printed`, are accepted on either side, in any font, and recorded in the sidecar. After the gates the rows are read (two times, hours, depth, an optional code, a description that may wrap, a mark column that holds only the exact mark glyph), and the page is rebuilt only if every self-check passes: valid times, row count, Elapsed against From and To, at most one mark per row, the words and glyphs of the table band equal the rebuilt cells, no stray time line after the table, and no line that is neither a row, a following title nor a centred section title directly under the table. The table then replaces Docling's table under the same `table_id`, or, when Docling found none, is added with the next free number of its file. It has one header row and one column per schema label, its `source_ref` starts with `textlayer:operations_summary:`, and its chunks are split like any table chunk.

*Not supported* (the Docling table is kept and the reason is recorded; nothing is guessed): rotated pages and pages without a text layer; a header with extra, missing, repeated or reordered labels, or one that is not directly under the title; a title inside a sentence or a contents line; words near the title that are neither the same phrase nor a column of their own; a line between the title and the header; a code that starts with a digit (`3-2-1`); marks printed as anything but the exact glyph; tables over several pages and continuation pages without a title; a following section title that is not centred; other report families and other page sizes or fonts than the ones evaluated (`NOT EVALUATED`). An annotation that sits on a line of its own away from the title or the table is not detected.

*Four states.* Every occurrence of the title (and every page that mentions the title or holds a Docling table with an Operations header) leaves one sidecar record with one of these states and a machine-readable `reason`:

| State | Meaning | Reasons |
|---|---|---|
| `SUPPORTED_AND_VALIDATED` | gates and self-checks passed and the table was merged. "Validated" means consistent with the text layer of that page, not compared with the page image | none |
| `UNSUPPORTED_FORMAT` | a recognition gate or the precondition failed; Docling is untouched | `no_title`, `no_header`, `header_not_adjacent`, `header_labels_missing`, `header_extra_labels`, `header_order_mismatch`, `no_rows`, `rotated_page` |
| `RECOGNISED_BUT_FAILED` | the gates passed but reading, a self-check or the merge failed; Docling is kept | `time_invalid`, `column_mismatch`, `trailing_line` (also used for a stray line below the table and for a lone line stuck to it), `row_count_mismatch`, `elapsed_mismatch`, `x_unmapped`, `word_mismatch`, `docling_extent_mismatch`, `ambiguous_docling_match` (also when a Docling table only partly overlaps the rebuilt one), `docling_multipage` |
| `PARSING_FAILURE` | an unexpected exception on one page or table, recorded with the class name; the other pages and tables are still processed, `MemoryError` is not caught | `text_layer_read_error`, `rule_exception`, `merge_exception` |

A fallback result is never presented as validated, and no confidence number is computed. `no_title` details name the first rejected mention: `not_found`, `multiple_title_phrases`, `embedded_in_text`, `ambiguous_gap` or `annotation_too_long`.

*Reading the sidecar.* `export_k1` returns the records as `table_repairs`, outside the package (the K1 manifest and schemas are unchanged; moving the reasons into the contract is task A-104). `scripts/export_k1_ops_rebuild.py` writes them to `table_repairs.NAME.json` and a per-family summary to `table_repairs.NAME.summary.json`. A record has `doc_id`, `page`, `index` (the nth accepted title of the page, so a rebuilt table keeps its `source_ref`), `document_type`, `rule`, `state`, `stage` (`precondition`, `recognition`, `read`, `validate`, `merge` or `runtime`), `status` (`rebuilt` or `fallback`, for older readers), `reason`, `detail`, `action` (`replaced`, `added` or `kept_docling`), `table_id`, and:

| Field | Meaning |
|---|---|
| `evidence` | what each gate measured and the margin to each threshold in `em` (reading aid only, never part of a decision); `decision` and `rejected_at` (`G0` to `G3`) |
| `annotations` | words on the title line (`side` left or right, `kind`, `count`; `unclassified` when no configured kind matches) and, as a hint only, a line right above the title (`side: above`, `owner: uncertain`: it may belong to the table above) |
| `completeness` | `partial_in_source` when an annotation says records were not printed (the rebuilt table holds only the printed rows, and the K1 chunks do not carry the annotation: consumers of K1 cannot see it, the decision is deferred to A-104); `unclassified_annotation` for an unknown annotation; `null` otherwise, which is not proof that nothing is missing |
| `rejected_mentions` | lines that name the table but are not its title (sentences, contents lines) |

The summary file counts records per family (`document_type` and `rule`), per state and per state and reason, with `parsing_failure_rate` and `annotations_above`; the script prints a warning (without stopping) when `parsing_failure_rate` of a family is above `--warn-parsing-failure-rate`. These are counts, not a measure of scalability.

*Conventions and limits.* A description that the report truncates with `...` (printed in the x range of the `Non-Prod` column) keeps the dots at the end of the description cell; the mark cell holds only the mark. A description word that is exactly the mark glyph and sits under the mark header cannot be told from the mark by geometry; it is read as the mark unless the row has two such tokens (then `x_unmapped`). Text chunks are never edited, so the words of a rebuilt table also remain in the loose text chunks of the page, which can duplicate hits for a consumer that reads both. A `trailing_line` reason hides three situations (a wrapped line with another indent, a footer and a following title that is not centred); read `detail`. To label a new annotation, add an entry to `annotation_kinds` (a `kind`, a pattern with one numeric group, and a sample the pattern must match); an annotation never needs a kind to be accepted. [`scripts/evaluate_ops_tables.py`](../../scripts/evaluate_ops_tables.py) measures the result against the PDFs (known documents and a document-level scan), [`scripts/regress_ops_tables.py`](../../scripts/regress_ops_tables.py) compares a release with a baseline (ids, non-operations tables and chunks, Track B events), and [`scripts/export_k1_ops_rebuild.py`](../../scripts/export_k1_ops_rebuild.py) writes an export together with the sidecar.

**Footer lines.** The corpus filter removes lines that repeat on many pages, which also removed the weather line `Vis.: 6 Temp: 58 ...` of the daily reports. `filters.keep_line_patterns` (optional list of regular expressions; absent means the old behavior) protects matching lines. [`configs/corpus/daily_reports.json`](../../configs/corpus/daily_reports.json) sets it for the weather labels. It is a corpus setting, so `process` must run with it; `k1` only reads the result.

**Old-to-new chunk ids.** `--legacy-chunks` maps the 60 chunks of `gdr882_ak3_eowr` in the main bundle to K1 chunk ids. Chunks match first on exact text with whitespace collapsed, then on token Jaccard similarity of at least 0.9; each new chunk is used once, and the rest are `unmapped`. `legacy_chunk_ids.json` holds one record per old chunk (`old_chunk_id`, `new_chunk_id`, `method`, `jaccard`, `old_page`, `new_page`) and is covered by `SHA256SUMS`. It is a migration aid, not a drop-in: a chunk the new parser split or merged stays unmapped.

**Committed sample.** [`data/processed/k1/ak3-k1-candidate/`](../../data/processed/k1/ak3-k1-candidate/README.md) holds the end-of-well report and two daily-report attachments (about 2.2 MB) with a README that says how to regenerate it. The full five-document package stays in the ignored corpus folder.

**Schemas.** [`k1_file`](../../schemas/k1_file.schema.json), [`k1_page`](../../schemas/k1_page.schema.json), [`k1_table`](../../schemas/k1_table.schema.json), [`k1_form`](../../schemas/k1_form.schema.json), [`k1_parent`](../../schemas/k1_parent.schema.json), [`k1_chunk`](../../schemas/k1_chunk.schema.json).

**Check against Track B's readers.** `python scripts/check_k1_graphrag_compat.py --k1 <release dir>` loads a package through `graphrag` (read-only), checks the daily-report and table rules, and runs BM25 over the end-of-well report through the id map. It needs no GPU and no model server.

## Limitations

- This is a local processing tool, not an authenticated application boundary. Parsing isolation, enforced network denial and expanded-archive/image resource limits remain required before shared/private-data use.
- Remote URL redirects are checked after `urlopen` follows them; the allow-list is not a complete SSRF defense. Keep acquisition operator-controlled.
- `retire` excludes future exports; it does not revoke older exports or answers. Immediate application withdrawal and restore tombstones remain planned.
- Standalone wheel/schema packaging and a reproducible Linux/GPU environment have not been verified. Run from the documented Windows checkout environment.

- Handwriting, stamps, heavy skew and multi-column reading order on scans are not evaluated; [E5](../experiments/E5-ocr-engine-benchmark.md) used rendered pages.
- VietOCR lacks some symbols ("°").
- Two workers on a 463-page corpus work ([E8](../experiments/E8-ak3-appendices-corpus-run.md)); very large single files and recovery from a crashed worker have not been exercised.
- Scanned forms with small print come out fragmentary, and VietOCR can turn English form labels into invented Vietnamese. The language and spelling checks flag such pages for review ([E8](../experiments/E8-ak3-appendices-corpus-run.md)); for English-only corpora, compare `rapidocr`.
- A scanned contents page is reported as `missing`: OCR reads it, then the contents filter removes the text ([E8](../experiments/E8-ak3-appendices-corpus-run.md)).
- Legacy-encoded PDFs are re-read by OCR rather than decoded from their font encoding.
