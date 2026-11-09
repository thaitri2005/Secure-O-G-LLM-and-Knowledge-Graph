# Quality Ledger (QA sidecar)

The quality ledger describes a K1 release without changing it. K1 v1 stays frozen (decision D-012): all quality metadata lives in a sidecar linked to the release by stable ids. The ledger is not a publish gate and `k1_validate.py` is not changed.

## Run

```
python -m graph_builder.corpus qa <corpus_dir> --release <release_dir> [--out <dir>] [--a107-sidecar <file>] [--qa-config <file>]
```

- Default output: `data/interim/qa/<release-dir-name>/` (git-ignored) with `qa-ledger.json` and `qa-summary.json`.
- Read-only on the corpus and on the release. If `<corpus_dir>/work` does not exist the ledger is built from the release only (signal `WORK_FOLDER_MISSING`).
- The A-107 table repair sidecar (`table_repairs*.json`) is searched with the templates in `configs/qa/ledger.json` (`a107_sidecar_search`), or given with `--a107-sidecar`.
- Output is byte-identical on repeated runs (sorted keys, LF, no timestamps, no absolute paths). Thresholds live in `configs/qa/ledger.json` with units; they are proposals.

## Contents

`qa-ledger.json`: header (`link`, `completeness`, `limitations`, `known_blind_spots`, `checks`, `k1_validator`, `release_signals`) and `documents[]`. Each document record has `work` (segments, Docling errors, dropped-item counts), `chunks` (counts by quality and parent type), `pages[]` (mode, status, OCR flag, PDF text chars, extracted chars, ratio, Docling confidence), `tables[]` (origin `docling` / `textlayer_rebuild` / `mixed` / `unknown`, A-107 state, reason, completeness, margins), `signals[]`, `checks[]` and `verification_level`.

`qa-summary.json`: counters per document family (K1 `document_type`), per reason code (total, severity, per family), per state (A-107 state, page status, conversion mode, table origin, segment status) and per verification level, plus the reason-code registry.

Linking block: release directory name, SHA256 of `SHA256SUMS`, manifest `identity`, corpus fingerprint, manifest schema version, QA `schema_version` (`1`), SHA256 of the QA config, A-107 sidecar name and SHA256.

A signal is `{code, severity, scope{kind, ids}, evidence, message}` with severity `INFO`, `WARN` or `ERROR`.

## Verification levels

| Level | Meaning |
|---|---|
| `UNVERIFIED` | An ERROR signal exists for the entity, or the K1 validator failed for the release. |
| `STRUCTURAL_ONLY` | The release passed the K1 validator and no ERROR signal exists. Says nothing about whether text, numbers or cells match the source. |
| `TEXT_LAYER_CONSISTENT` | Reserved for A-402: its checks passed for the tokens checked. Not content-verified. |
| `CROSS_REPRESENTATION_CONSISTENT` | Reserved for A-403: its checks passed. Not content-verified. |
| `NOT_APPLICABLE` | No independent reference exists (for example OCR pages). Only replaces `STRUCTURAL_ONLY`. |

No level means the content is correct. A WARN signal does not lower the level; read the signals. A document is never above its weakest page or table. `quality: ok` on a chunk and the A-107 state `SUPPORTED_AND_VALIDATED` are recorded as data and are never treated as evidence of correct content. `completeness` is `UNKNOWN` by default and `PARTIAL_IN_SOURCE` for tables whose PDF says records were not printed; there is no "complete" value.

## Check-registration API

```python
from graph_builder.corpus.qa.signals import Registry
from graph_builder.corpus.qa.builtin_checks import register_builtin
from graph_builder.corpus.qa.ledger import build_qa

registry = register_builtin(Registry())
registry.register_reason("MY_CODE", "WARN", "meaning", "my_check")
registry.register_check("my_check", function, scope="page", version="1", grants="TEXT_LAYER_CONSISTENT")
build_qa(release_dir, out_dir, corpus_dir=corpus_dir, registry=registry)
```

`function(context, entity)` returns a list of signals built with `registry.signal(code, scope, ids, evidence=...)`. Scopes: `release`, `document`, `page`, `table`. `grants` may only be `TEXT_LAYER_CONSISTENT`, `CROSS_REPRESENTATION_CONSISTENT` or `NOT_APPLICABLE`; the level is granted only when the check produced no WARN/ERROR for that entity. An exception in a check becomes a `QA_ERROR` signal and QA continues.

## Reason codes

| Code | Severity | Meaning | Emitted by |
|---|---|---|---|
| `A107_PARTIAL_IN_SOURCE` | INFO | The PDF itself indicates that records were not printed (A-107 completeness partial_in_source). | a107_sidecar |
| `A107_RECORD_UNMATCHED` | WARN | An A-107 sidecar record refers to a table_id that is not in the release. | a107_sidecar |
| `A107_SIDECAR_MISSING` | INFO | No A-107 table repair sidecar was found for this release; table repair states are unknown. | a107_sidecar |
| `A107_STATE_NOT_VALIDATED` | WARN | A-107 sidecar state of the table is not SUPPORTED_AND_VALIDATED. | a107_sidecar |
| `CHAR_RATIO_HIGH` | WARN | Extracted/pdf text-char ratio of a text-mode page is above the proposed threshold. | char_ratio |
| `CHAR_RATIO_LOW` | WARN | Extracted/pdf text-char ratio of a text-mode page is below the proposed threshold. | char_ratio |
| `CHUNK_QUALITY_NOT_OK` | WARN | Chunks of this document carry a quality value other than 'ok'. | chunk_quality |
| `CONFIDENCE_LOW` | WARN | Docling mean_score of the page is below the proposed threshold. | docling_confidence |
| `CONFIDENCE_MISSING` | INFO | No Docling confidence value is available for a page. | docling_confidence |
| `DROPPED_ITEMS_RECORDED` | INFO | The pipeline removed items (running lines, footers, pictures, index) and recorded their counts. | work_folder |
| `K1_VALIDATOR_FAIL` | ERROR | k1_validate.inspect reported errors for the release. | k1_validator |
| `OCR_PAGE_NO_REFERENCE` | INFO | Page text came from OCR or hybrid conversion; no independent reference in this ledger. | ocr_flags |
| `PAGE_EMPTY_EXTRACTION` | WARN | A text-mode page has PDF text characters but zero extracted characters. | char_ratio |
| `PAGE_NOT_IN_WORK_DATA` | WARN | The page exists in the release but not in the corpus work document. | work_folder |
| `PAGE_STATUS_MISSING` | ERROR | Page status is 'missing' in the release. | page_status |
| `PAGE_STATUS_OTHER` | WARN | Page status is not ok, review or missing. | page_status |
| `PAGE_STATUS_REVIEW` | WARN | Page status is 'review' in the release. | page_status |
| `QA_ERROR` | ERROR | A check or the processing of one entity raised an exception; the entity is UNVERIFIED and QA continues. | ledger, registry |
| `SEGMENT_ERRORS` | WARN | A Docling segment finished but recorded error strings. | work_folder |
| `SEGMENT_FAILED` | ERROR | A Docling segment did not finish with status success. | work_folder |
| `TABLE_ORIGIN_TEXTLAYER_REBUILD` | INFO | Table (or part) was rebuilt from the PDF text layer by a rule, not produced by Docling. | table_origin |
| `TABLE_ORIGIN_UNKNOWN` | WARN | The release table has no source_ref in its parts. | table_origin |
| `WORK_FINGERPRINT_MISMATCH` | WARN | Work data fingerprint differs from the release manifest corpus fingerprint. | work_folder |
| `WORK_FOLDER_MISSING` | WARN | No corpus work data for this document; ledger built from the release only (degraded). | work_folder |

## Limitations and known blind spots

Limitations: absence of a signal is not evidence of correct content; Docling confidence, character ratios and A-107 states are heuristics of the pipeline itself; the ratio check compares the pipeline's own counts and furniture removal lowers it legitimately; OCR and hybrid pages have no independent reference; thresholds were looked at on five documents of one family (`daily_report` and one `eowr`) and generalisation is NOT EVALUATED.

Known blind spots (error classes the enabled checks cannot detect): swapped cells or rows; reordered text; wrong label-value pairing; OCR substitution without a reference; errors already in the PDF text layer; wrong table structure that keeps the same words; numbers changed consistently in every representation; content dropped without being counted in the dropped-item statistics.

K1 limitation: chunks, pages and tables carry no field for per-entity quality evidence beyond `quality` and `status`; the ledger therefore references entities by `file_id`, `page`, `table_id` and does not extend K1.

## Source fidelity check (A-402, opt-in)

Run: `python -m graph_builder.corpus qa <corpus> --release <release_dir> --fidelity` (reads the source PDFs, found by SHA-256 in `<corpus>/store` or `data/raw`).
Module `qa/fidelity.py`, thresholds (proposals, with units) in `configs/qa/source_fidelity.json`, evaluation `scripts/qa_fidelity_eval.py`.

What it does: a second reader (pypdfium2) reads the PDF text layer; word and numeric tokens of each page are compared as multisets with the text rebuilt from the K1 chunks. Missing tokens explained by furniture (repeated margin lines, lines repeated on at least half of the pages, bare page numbers) are reported separately from `content candidate` tokens; recall is given raw and after exclusion. Only WARN/INFO signals are emitted.

| Code | Severity | Meaning |
| --- | --- | --- |
| FIDELITY_NUMERIC_NOVEL | WARN | K1 text has a numeric token absent from the PDF page |
| FIDELITY_NUMERIC_RECALL_LOW | WARN | numeric recall after exclusion below threshold |
| FIDELITY_WORD_RECALL_LOW | WARN | word recall after exclusion below threshold |
| FIDELITY_PAGE_EMPTY | WARN | K1 page empty while the PDF page has words |
| FIDELITY_NOT_APPLICABLE | INFO | OCR page, no independent reference |
| FIDELITY_PARTIAL_REFERENCE | INFO | hybrid page, recall only, no level |
| FIDELITY_NO_REFERENCE | INFO | PDF not found or SHA-256 differs |
| FIDELITY_INSUFFICIENT_TOKENS | INFO | too few words to judge recall |

A text page without WARN and with enough tokens may reach `TEXT_LAYER_CONSISTENT`. This is not content verification. Blind spots: swapped cells or values, reordered text, wrong label-value pairing, OCR errors, errors in the text layer itself, wrong table structure with the same words, a digit change that produces a token present elsewhere on the page.

## Cross-representation check (A-403, opt-in)
Run: `python -m graph_builder.corpus qa <corpus> --release <release_dir> --crossrep` (reads only the release). Without the ledger: `graph_builder.corpus.qa.crossrep.run_standalone(release_dir, out_dir)` writes `qa-crossrep.json`.
Module `qa/crossrep.py`, settings in `configs/qa/cross_representation.json`, evaluation `scripts/qa_crossrep_eval.py`. It is not part of `k1_validate` and not a publish gate.
What it does: compares copies of the same content inside one release. Table chunks are compared row by row with the grid of `tables.jsonl` (header repeated per chunk and the caption line before the Markdown header are accounted for; the header rows the chunker rendered are read from `row_start` of the first chunk, because K1 does not store them and `header_rows` can differ). Form chunks are compared with the fields of `forms.jsonl`. Also: row ranges against `num_rows`, table and form records without chunks, chunks pointing to missing tables or forms, pages without chunks (not declared in the manifest `pages_without_context`), chunk page against parent / table / form, `page_count` against `pages.jsonl`, parents without chunks.
| Code | Severity | Meaning |
| --- | --- | --- |
| XREP_TABLE_NO_CHUNK | ERROR | table record without any table chunk |
| XREP_TABLE_CHUNK_ORPHAN | ERROR | table chunk without a known table record |
| XREP_ROW_RANGE_INVALID | ERROR | row_start/row_end missing, reversed, negative or beyond num_rows |
| XREP_ROW_RANGE_COVERAGE | ERROR | gap, overlap or missing end in the row ranges of one table |
| XREP_FORM_NO_CHUNK | ERROR | form record without a form chunk |
| XREP_FORM_CHUNK_ORPHAN | ERROR | form chunk without a known form record |
| XREP_PAGE_COUNT_MISMATCH | ERROR | files page_count differs from pages.jsonl |
| XREP_TABLE_SHAPE | WARN | grid does not match its num_rows / num_cols |
| XREP_TABLE_CHUNK_MISMATCH | WARN | header or rows of a table chunk differ from the grid |
| XREP_FORM_CHUNK_MISMATCH | WARN | form chunk text differs from the form fields |
| XREP_PAGE_WITHOUT_CHUNKS | WARN | page named by no chunk, not declared |
| XREP_CHUNK_PAGE_INCONSISTENT | WARN | chunk page fields disagree with parent / table / form |
| XREP_PARENT_WITHOUT_CHUNKS | WARN | parent record without chunk |
| XREP_PAGE_EMPTY_BY_DIGEST | INFO | page without chunks whose digest in pages.jsonl is the digest of the empty text |
ERROR only for structural/referential rules with no finding on both real releases (one document family, the two releases share most data, so this is not independent evidence). Content comparisons stay WARN. A table without WARN/ERROR may reach `CROSS_REPRESENTATION_CONSISTENT`; documents and pages are not raised. This is not content verification: values wrong in every representation, swapped cells made before the release was written, wrong table structure with the same words and text-layer errors stay invisible.
## Operations table mark margin (A-401a, optional, `--ops-margin`)

`python -m graph_builder.corpus qa <corpus> --release <release> --ops-margin` adds a table-scope check that reads the source PDFs.
For each table rebuilt from the text layer (`source_ref` `textlayer:operations_summary:`) it measures how far each `X` centre lies inside the
`Non-Prod` header span, in em of the header label (negative = outside). The margins of all tables of the release give a median and a robust
scale (1.4826 x MAD, floored by `scale_floor_em`). A table whose smallest margin is more than `deviation_k` scales below the median gets
`OPS_MARGIN_NEEDS_VERIFICATION` (WARN). A table with typical margins gets nothing; that is not evidence of correct content.
Parameters: `configs/qa/ops_margin.json` (proposals, one document family). Too few values or an unreadable page give `OPS_MARGIN_NO_REFERENCE` (INFO).

Blind spots: swapped adjacent description words (the other half of the earlier "validated but different" cases), a release in which every
table is shifted equally, a mark that moved farther than `mark_window_em`, errors in the text layer itself.
Evaluation: `scripts/qa_ops_margin_eval.py` (development data, not independent).