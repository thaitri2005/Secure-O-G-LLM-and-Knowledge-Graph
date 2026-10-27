# E7: Corpus pipeline smoke test

| | |
|---|---|
| **Date** | 27 October 2026 |
| **Question** | Does the generic document pipeline register, plan, convert, OCR, chunk, validate, resume and export a mixed set of documents end to end? |
| **Requirement** | SR-02, SR-12, SR-13, SR-14; FR-01, FR-02, FR-13 |
| **Input** | Three small files: a one-page image-only Vietnamese scan (the [E2](E2-vietnamese-ocr-smoke.md) fixture), a two-page excerpt of the Petroleum Law PDF (text layer), and a Vietnamese Markdown note with a table |
| **Code** | [`graph_builder.corpus`](../../src/graph_builder/corpus/), configuration [`configs/corpus/default.json`](../../configs/corpus/default.json) |
| **Outputs** | Ignored, local: `data/interim/corpus_smoke/` |
| **Status** | Passed with one worker. Two workers and a real scanned corpus were exercised afterwards in [E8](E8-ak3-appendices-corpus-run.md) |

## Steps and results

| Step | Result |
|---|---|
| `init`, `add` on the folder | 3 documents added; adding the scan a second time reported `duplicate` |
| `analyze` | Law excerpt: 2 `text` pages. Scan: 1 `ocr` page (`no_text_layer_image`). Markdown: no pages |
| `process` (1 worker, CPU) | All 3 done: Markdown 2 chunks and 1 table (22.9 s, including model loading); law excerpt 5 chunks (16.5 s); scan 1 chunk, OCR with VietOCR (17.5 s) |
| Chunk metadata | Language `vi` on all chunks; section paths from headings (for example "Điều 1. Phạm vi điều chỉnh"); `page: null` for Markdown; `ocr: true` only on the scan |
| Scan text | Every body line correct except "35,5 °C", read as "35,5 ?C". CER 9% against the reference, mostly because the title became section metadata |
| Page quality | All pages `ok`; no `review` or `missing` pages |
| `process` again | 0 processed, 3 skipped (manifests verified) |
| `export --name v1` | `documents.jsonl`, `chunks.jsonl`, `tables.jsonl`, `manifest.json` and `SHA256SUMS`; 3 documents, 8 chunks, 1 table, nothing held back |

## Not covered

- Recovery from a crashed worker. (Parallel workers: see [E8](E8-ak3-appendices-corpus-run.md).)
- Large documents, DOCX, PPTX, XLSX, HTML and images other than PDF scans.
- Real scanned corpora: done for the AK-3 appendix portfolio in [E8](E8-ak3-appendices-corpus-run.md).
