# PDF ingestion

This document describes the **implemented ingestion subsystem**. For the full intended product, technology choices, graph and QA architecture, and production requirements, see the [project design](PROJECT_DESIGN.md) and [development plan](DEVELOPMENT_PLAN.md).

The baseline details and historical results below describe OCR-disabled GDR processing. The new [multilingual OCR and local-PDF workflow](ocr-ingestion.md) adds a separate Vietnamese–English profile, named-run protection, model-aware cache checks, and page coverage diagnostics.

## Stages and configuration

`fetch` downloads source PDFs or verifies existing files against the registry's SHA256 and byte size. A mismatch fails the command. `convert` runs Docling locally and stores complete, unfiltered JSON and Markdown documents in a per-parser-settings subdirectory of `data/interim/docling/`. Accurate TableFormer settings use the base directory; other settings, including the default, use a hashed subdirectory. `chunk` filters a copy of each cached document and writes the merged chunks in registry and reading order. `validate` checks those chunks against the original PDFs and cached documents. `run` performs all four stages and fails if validation fails.

[Pipeline options](../configs/ingestion/default.json) explicitly set a 1,500-character budget, CPU execution, OCR off, table structure on, fast TableFormer, and cell matching on. Remote services and Hugging Face telemetry are disabled. Dependencies are Python 3.12.10, docling 2.141.0, docling-core 2.103.1, torch 2.14.1+cpu, and pypdf 6.1.1. The full Windows CPU dependency set is frozen in `requirements.lock.txt`.

## Filters

Page headers, page footers, pictures, document indexes and dotted-leader TOC entries are dropped. The explicit contents heading is dropped with its detected index. Captions and existing PDF text within figures are retained without OCR. Empty tables and items without provenance are skipped and counted.

Running-line frequency keys collapse whitespace, case-fold text, and replace each digit run with `#`. Frequencies count distinct pages, with a threshold of 50% of document pages. A line entirely within the top or bottom 8% of a page anchors a running metadata block. Bboxes are converted to top-left coordinates using the source page height. Adjacent repeated lines may join an anchored block if their left edges differ by at most half the smaller line height and their vertical gap is at most one line height. The band stays at 8%; an isolated repeated line outside it is retained.

Docling sometimes splits a line across table cells. Fragments with aligned vertical bounds and a horizontal gap of at most three line heights are considered together for frequency matching. All block and fragment thresholds are in the configuration. No document-specific string or page number is used by the filter. This removes version, page-number and issue-date metadata even when digits vary or table cells divide the line. Interior text is retained. The source JSON and Markdown cache remain complete.

| Dropped occurrences/items | AK-3 | 56-32 | 68-32 |
|---|---:|---:|---:|
| Document index | 1 | 5 | 0 |
| Explicit contents heading | 1 | 1 | 1 |
| Dotted-leader entries | 0 | 0 | 13 |
| Page header | 1 | 33 | 5 |
| Page footer | 28 | 86 | 12 |
| Picture | 46 | 226 | 54 |
| Empty table | 0 | 1 | 1 |
| Running-line occurrence | 28 | 276 | 0 |

Running-line counts include matches already labelled as headers or footers, so categories overlap. Counts reflect the selected fast parser configuration. The source cache remains complete.

## Chunking and validation

Text is grouped by the nearest preceding section and packed by sentence. Paragraph continuation may join the final unfinished paragraph of a page to a lowercase- or digit-starting paragraph on the next page; headings prevent continuation. The `page` strategy remains available. Long sentences split at whitespace, or at the character budget when no whitespace exists. Headings end the current text buffer and set the section; they do not create standalone chunks. A text item spanning pages is divided using its provenance character spans. Existing text within figures remains available.

Tables become Markdown. Long tables split only at row boundaries and repeat their caption and header. Markdown separator padding is compacted. The full header plus exactly one body row remains intact when over budget and produces a validation warning. A multi-page table uses its first provenance page and is counted; none occurred in these inputs. Identifiers use `{doc_id}#c{index:04d}` with continuous indexes from zero per document.

Validation checks the JSON array and fields, identifiers and continuity, registry order, physical page range, nonempty text, allowed types, section type, character limits and table-row exceptions. Configured content checks verify selected phrases and page/section provenance. A document without table chunks warns. Each PDF page with more than 200 pypdf characters must have a chunk unless it is a computed index-only page.

Exemptions come from every item in the complete Docling cache, including figure children and orphaned items. A page is exempt when all items are structural exclusions, or when a detected index page contains only those exclusions, filtered running metadata, and index headings. Index headings are explicit contents/figures/tables headings or headings matching labelled running-header text within the same normalized vertical region. Substantive paragraphs, captions, ordinary headings and empty tables prevent exemption. No page numbers are hard-coded and no TOC chunks are created. Current exempt pages: AK-3 `[3]`, 56-32 `[3, 4, 5, 7]`, 68-32 `[]`; missing substantive pages: none.

## Validation rules

The indivisible table unit is the complete repeated header plus exactly one body row. A table part may exceed `max_chars` only when it contains exactly one body row, with or without a header; validation emits a warning. A lone row rendered above a Markdown separator represents a headerless single-row table. Oversized parts with two or more body rows fail. Text chunks retain the hard character limit. Separator padding does not qualify for an exception. The splitter fills each part until adding the next body row would exceed the budget and repeats the complete header.

Validation also checks the JSON schemas, canonical offsets, stable IDs, geometry and table references. The shared table file stores `cells` and `rows_text` once per `table_id`. Each table part references a zero-based half-open `[row_start, row_end)` range in the original grid; leading rendered header rows are stored in the table record and repeated in chunk text. Combining the header with contiguous part ranges reconstructs the original table. `regions` use PDF points with a top-left origin. Source spans index the emitted chunk and identify its physical source pages; table row provenance survives page merging.

## Results

| Document | Pages | Text chunks | Table chunks | Characters |
|---|---:|---:|---:|---:|
| gdr882_ak3_eowr | 29 | 54 | 6 | 43073 |
| gdr1295_56-32_eowr | 86 | 131 | 69 | 68028 |
| gdr1153_68-32_eowr | 40 | 52 | 60 | 111158 |

SHA256: `b3256ef6d83c709ddc4ba3f3262ad0b56e6273551b49694a3b72f0b880037b9b`

The main deliverable has 372 chunks and 20 indivisible-table warnings, with no validation errors. Text, IDs and JSON formatting are deterministic under the locked Windows CPU environment. Comparison against `page_1500_accurate`: 241 kept, 42 changed, 89 added and 77 removed. `content_id` is the first 16 hexadecimal characters of SHA1 over `doc_id|type|text`, with text whitespace collapsed. Comparison first matches these IDs one-to-one, then matches remaining chunks within a document/type by token Jaccard similarity at least 0.9.

[Evaluation](ingestion-evaluation.md) includes the tested configurations, source-page attribution, gold accuracy, timings measured once on the reference machine, and error examples. Timings are not reproducible.

## Known limitations

Rotated forms remain difficult: the selected parser retains 51/60 annotated values on 68-32 page 17. Wide appendix tables and stacked headers still contain cell errors. Twenty table parts exceed the character limit under the documented single-body-row rule. OCR is disabled; 67 appendix pages need it. The optional trial and its dependency extra do not change published chunks. Gold is single-annotator and AI-assisted; see the evaluation report for scoring conventions and limitations.

## Commands and artifacts

`run --run-name <name>` isolates chunks, table structures, documents, resolved configuration and metrics under the ignored runs directory. Parser settings select separate conversion caches; chunking settings reuse them. `evaluate --run <name>` checks automatic metrics and corrected gold available in matching parser caches. Appendix annotations are reported when those source caches are present; score counts expose partial gold coverage. `compare --old <name> --new <name>` reports one-to-one kept/changed/added/removed counts. `publish --run <name> --sources <registry>` revalidates artifacts, requires the saved sources to match that registry, and copies the bundle to its destination. The main registry is the default target. `compare`, `evaluate`, `publish` and `ocr` reject `--set`; overrides belong on run creation.

Unnamed main chunking stages the complete bundle and compares every artifact before changing published files. A changed bundle requires a named run followed by publication. Source and schema document IDs share `^[a-z0-9][a-z0-9_-]{0,63}$`, allowing at most 64 characters.

The main bundle is `gdr_chunks.json`, `gdr_chunks_full.jsonl`, `gdr_tables.jsonl` and `documents/`. Extended and portfolio bundles use the same filenames inside ignored `data/processed/local/<registry_name>/` directories. Every registry uses the same default configuration without overrides. `chunk.schema.json`, `chunk_full.schema.json`, `table.schema.json` and `document.schema.json` are under `schemas/`. Canonical `.txt` files join chunk text in reading order using two newlines. Offset ranges are half-open Python Unicode character indexes, not UTF-8 byte indexes. All generated text uses UTF-8 with LF line endings, and publication normalizes CRLF inputs to LF.

Geometry is rounded to two decimals at artifact serialization, including region and cell coordinates when present, page sizes and floating character spans. Integer offsets and chunk text are not rounded. Raw conversion caches keep full precision. Direct processed output and publication refresh `SHA256SUMS`, listing only that registry's chunk JSON, two sidecars and document pairs in relative POSIX path order with LF line endings. The main manifest has nine entries and excludes all local bundles.

Source titles, submission links and licenses are listed in the README and document records.

## Design debt

Core modules import shared helpers from `evaluation.py`; these helpers should eventually live in a shared module.

The private APIs `_count_header_rows` and `pypdf._text_extraction.mult` depend on the versions pinned by the lock file.
