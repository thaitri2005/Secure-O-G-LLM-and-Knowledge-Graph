# E8: AK-3 appendix portfolio through the document pipeline

| | |
|---|---|
| **Date** | 27 October 2026 |
| **Question** | Does the document pipeline hold up on a real mixed corpus at size: 44 PDFs and 463 pages, including scanned permits and plans, with two workers? What does it do with the scanned pages, and which pages need a person? |
| **Requirement** | SR-02, SR-12, SR-13, SR-14; FR-01, FR-02, FR-13; plan backlog item 4a |
| **Input** | [AK-3 EOW Appendices.pdf](https://gdr.openei.org/files/882/AK-3EOWAppendices.pdf) (GDR 882, CC BY 4.0), SHA256-verified and split into 44 unique attachment PDFs by [`scripts/run_ak3_appendices.py`](../../scripts/run_ak3_appendices.py) |
| **Code** | [`graph_builder.corpus`](../../src/graph_builder/corpus/), default configuration (VietOCR engine, `vi` + `en`, paragraph chunking at 1,500 characters, fast TableFormer); commits up to `3f38143` |
| **Gold data** | None for OCR text. Flagged pages were checked by eye against the rendered page |
| **Outputs** | Ignored, local: `data/corpora/ak3_appendices/`, with run logs in `logs/` and export `exports/v1/` |
| **Status** | Passed after two fixes. All 44 documents exported; 5 pages flagged, hand-checked |

## Runs

| Run | Setup | Result |
|---|---|---|
| 1 | All 44 documents, 2 workers, 10:27–11:22 | 35 done, 5 failed validation, 4 not started: stopped deliberately with Ctrl+C at 40/44 to improve speed and logging before resuming |
| Fixes | `9083594` | Page sizes are now taken from the converted document, so rotated pages match their chunk regions. Table row ranges start at the serializer's header count and are capped at the table size |
| 2 | Same command, 2 workers, 12:17–12:23 | The 35 finished documents were skipped after manifest checks. The remaining 9 (198 pages) took 6.0 minutes: 9 done, 0 failed |
| Export | `export --name v1` | 44 documents, 463 pages, 1,778 chunks, 336 tables, 0 held back |

The five failures in run 1 were real validator catches, not crashes:

- **Rotated pages:** one document's chunk regions fell outside its page because of the rotation.
- **Table row ranges:** in four documents (two daily reports and two cement job reports), a chunk's row range pointed outside its table.

Per-document failure isolation worked as designed: the other documents finished, and resume after the deliberate stop re-ran only the unfinished ones. Between the runs, the logging was improved (`afef0c2`, `3f38143`): per-document times, elapsed time, ETA and a heartbeat every minute.

## Results (export v1)

| Measure | Value |
|---|---:|
| Pages: text layer / full-page OCR / hybrid (text plus OCR of images) | 359 / 71 / 33 |
| Page decision reasons | `text_layer_ok` 358, `no_text_layer_image` 70, `images_with_text` 33, `no_text_layer_vector_paths` 1, `blank_or_sparse` 1 |
| Chunks: text / table | 1,398 / 380 (1,778 in total) |
| Chunks produced by OCR | 218 |
| Chunk language: English / undetermined / Vietnamese | 1,738 / 39 / 1 |
| Chunks with quality `review` | 8, all in the permit transmittal memo: 6 on p. 62, 1 each on pp. 28 and 60 |
| Pages `ok` / `missing` / `review` | 458 / 4 / 1 |
| Median characters extracted per OCR or hybrid page | 880 |

Compared with the earlier PDF pipeline on the same portfolio ([E1](E1-pdf-ingestion-configuration.md): 1,633 chunks, with the 67 scanned pages left without text), the new pipeline OCRs 104 pages and keeps them in the export with page-level flags.

## Hand check of flagged pages

| Document, page | Flag | What the page is | Verdict |
|---|---|---|---|
| Non-compliance letter, pp. 4 and 5 | missing | Site photographs with short callouts ("Mud mixing and storage tanks") | Correct: no substantive text. The callouts were not captured |
| Permit transmittal memo, p. 28 | missing | Scanned table of contents of the drilling plan | Not an OCR failure: the text was read, then removed by the contents-page filter. The flag is a false alarm for this kind of page |
| Permit transmittal memo, p. 61 | missing | Blank graph-paper test sheet with a few field labels | Correct |
| Permit transmittal memo, p. 62 | review | AOGCC Permit to Drill form: small print, dense boxes | Correct flag, real loss. The OCR text is fragmentary, and English field labels came out as invented Vietnamese ("Từ Type có Wood", "ĐỢP SANH"). The form holds the AK-3 API number and casing program |

A sample of other OCR chunks: continuous prose (letters, permit text, targeting report) is readable, with occasional garbling ("geologreby geops ysical"). Tables and forms in scans break into short fragments, and the inch mark is often read as "?" ("8-5/8?").

## What was learned

1. The pipeline runs a real 463-page corpus to completion on a laptop with two workers. Failures stay with their document, and resume costs only the unfinished work.
2. Output validation caught two real defects (rotated-page regions, table row ranges) before anything was exported.
3. The page flags are useful but not precise. Three of five flagged pages were correct, one was a filter interaction (a scanned contents page), and one was a genuine loss on a dense form.
4. VietOCR on English forms can invent Vietnamese diacritics. The Vietnamese spelling and language checks caught it here. For English-only corpora, the faster `rapidocr` engine ([E5](E5-ocr-engine-benchmark.md)) is worth comparing on the same pages.
5. Scanned forms remain the weak point, matching [E1](E1-pdf-ingestion-configuration.md) and [E5](E5-ocr-engine-benchmark.md).

## Not covered

- OCR accuracy against a transcription: there is no gold text for these scans.
- Wall-clock throughput for the whole portfolio in a single run (it was done in two runs with a code change in between).
- One worker against two workers on the same input.
- A VPI or other Vietnamese sample: backlog item 4a, second half.
