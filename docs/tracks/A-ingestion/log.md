# Track A log

> **DRAFT, written on Khai's behalf on 24 November 2026, for Khai to correct.** It was reconstructed by a development agent working for Track B (plan work package W5, with Khai's clearance) from the repository only: the git history of the ingestion code and tests, the documents in this folder, [`docs/components/corpus-ingestion.md`](../../components/corpus-ingestion.md), [`docs/components/dependencies.md`](../../components/dependencies.md), the Track A progress report and the experiment records E5, E7, E8, E30 and E31. Nothing was taken from chat or memory. Where the repository has no number, the entry says "not recorded". Entry numbers, dates and wording are proposals: renumber, merge or delete as you see fit. From the day you accept it, this file is yours and follows the rule of the other two track logs.

Track A is ingestion and tables (owner: Khai, from 5 November 2026): Docling compared with document VLMs, multi-page tables, key-value forms, chunking; it publishes the chunk package K1. Every finding, decision, design choice and experiment of Track A goes here the same day. Entries are never renumbered or deleted. When an entry is replaced, a later entry says so and names it.

| Prefix | Kind | What it records |
|---|---|---|
| **A-F** | Finding | Something learned from reading or from a run, with its source |
| **A-D** | Decision | What we chose, and why |
| **A-C** | Design choice | How a part is built: a schema rule, a setting or an interface |
| **E** | Experiment | A link to the record in [`docs/experiments/`](../../experiments/README.md), plus one line on the outcome |

Task numbers such as A-107 or A-415 are the ones Khai's commits and documents use; they are kept so the code can be searched for them.

## Current state

| Topic | Current answer | Entry |
|---|---|---|
| K1 version 1 | The agreed interface (D-54 ids, D-57 package). Six record types, validator, `k1` command, completeness gate | A-C01, A-C06 |
| Demo release (D1) | Built (`ak3-demo-v1`: end-of-well report, appendices 23 and 27 to 30; 1,051 chunks). Validator pass, 981/981 daily chunks and 61/61 end-of-well chunks with their context, legacy map inside, 161 events from the package. Not yet shared on a store; `graphrag`'s own event command still reads appendix 23 elsewhere | A-F15, A-F16 |
| End-of-well chunks with a well | Optional K1 key `document_context` (off by default); on in the demo configuration | A-C17 |
| Operations Summary tables | Rebuilt from the PDF text layer when four gates pass (A-107); in `configs/corpus/k1.json` | A-C04 |
| Merged-cell text repeated in table Markdown (D4) | Fixed by the optional mode `chunking.table_markdown = span_once_keyed` (A-431), off by default; test added on 24 November. On the demo release it clears both `CHAR_RATIO_HIGH` warnings and changes no id. Not yet switched on for any shared release | A-C08, A-F11 |
| Options of 17 November | All off by default; none measured on the demo release yet (task D2) | A-C08 to A-C15 |
| QA sidecar | Warning-only checks; thresholds noisy outside the family they were tuned on (8/20 precision on a sample) | A-C05, A-F06 |
| Tests without PyMuPDF | Skip with a reason (24 November) | A-F18 |
| Open | D2 (decide each option with a number), D3 (56-32 and 68-32), the VLM comparison, scanned pages, forms outside the RIMBase template | — |

## Before 5 November (background)

The pipeline existed before the tracks were split; these are pointers, not Track A entries.

- 22 and 23 October: PDF ingestion for the GDR end-of-well reports, chunk provenance and table structure (commits `710b782`, `b61ffd2`).
- 25 to 27 October: the generic document pipeline `graph_builder.corpus` with Vietnamese OCR, run logs and the AK-3 appendix corpus (commits `4ac8a7d` to `3f38143`; experiments [E5](../../experiments/E5-ocr-engine-benchmark.md), [E7](../../experiments/E7-corpus-pipeline-smoke.md), [E8](../../experiments/E8-ak3-appendices-corpus-run.md): 44 PDFs, 463 pages, two workers).
- 5 November: Track A moves to Khai (Track B log B-D27).

## 2026-11-07

Dates of this day follow E30 (6 and 7 November); the commits are dated 8 November.

**A-F01 (finding).** A cold conversion and a cached one gave different chunks for the same input: Docling keeps text boxes that overhang the page in the live document and clamps them in the re-read copy. Reproduced on appendix 4 (validation error `region outside page 4` and four more pages). Fixed by reading the document back from the cache on both paths; cold and cached runs then give byte-identical `chunks.jsonl`, `tables.jsonl` and `text.txt` (commit `aa0b604`; [E30](../../experiments/E30-k1-version-1-candidate.md)).

**A-C01 (design choice).** K1 version 1 package: `files`, `pages`, `parents`, `chunks`, `tables`, `forms` as JSON lines, `text/<file_id>.txt`, `manifest.json`, `SHA256SUMS`, and `legacy_chunk_ids.json` when asked. Ids `<file_id>:p<n>`, `:t<n>`, `:s<n>`, `:f<n>`, chunks `<parent>:c<n>`, no `#`. A validator checks schemas, references, offsets, page rebuild, context coverage and checksums before a release becomes current (commit `83afadc`).

**A-C02 (design choice).** Optional corpus filter `filters.keep_line_patterns`: protects lines the running-line filter would drop. `configs/corpus/daily_reports.json` keeps the weather strip (`Vis.:`, `Temp:` ...). On appendix 30 it keeps 106 lines that were dropped before, all weather labels and numbers; the other four documents are unchanged (commit `63b045c`; E30).

**A-C03 (design choice).** Form pairing ported from the ingestion exploration: the RIMBase template (at least 40% of its labels and the text `Operations Summary`) pairs labels and values from the PDF text layer. 141/141 exact pairs on the development forms, 93/93 on the held-out forms of the same template (commit `2f31f57`; E30).

**A-D01 (decision).** Generic colon pairing off (`forms.generic: false`): it reached about 61% exact pairs in the exploration. Pages that do not match the template get no form chunk (E30).

**A-F02 (finding).** The well pattern first specified, `Well (?:ID|Name):\s*(...)`, returns `Geothermal` on every page of appendices 27 and 30, because the text layer has the company name after `Well ID:`. The pattern now requires a digit in the id; a well without a digit would need another pattern (E30).

**A-D02 (decision).** `rapidocr` reads the 11 hybrid pages of the end-of-well report, because it reproduces the prototype's text. With it, 15 of the 17 chunks the prototype's gold cites are mapped to K1 ids; with `easyocr` 17 of 17. Ten of 28 text pages differ between the two engines (E30).

**A-D03 (decision).** Docling with fast TableFormer stays the table parser: 85.1% mean data-cell accuracy on nine annotated tables, against 68.9% for accurate TableFormer and 72.7% for a 1.2B document VLM (the exploration's own result, one annotator; E30).

**E30.** [K1 version 1 candidate](../../experiments/E30-k1-version-1-candidate.md): five documents of AK-3, 174 pages, 1,040 chunks, 191 tables, 81 forms; validator 0 errors, page rebuild 174/174, report date and well on 979/979 daily chunks, two exports with identical `SHA256SUMS`. Track B's readers load it.

## 2026-11-09

**A-C04 (design choice).** Operations Summary tables of RIMBase daily reports rebuilt from the PDF text layer (A-107), configured in `table_rules.operations_summary` of `configs/corpus/k1.json`: four recognition gates, self-checks, and four outcome states with a reason; Docling's table is kept when anything fails (commit `a01977d`). On 81 tables: headers right 51/81 with Docling alone, 81/81 with the rule on the data it was built on, 26/27 on the independent round 1 held-out (Track A progress report §3.2).

**A-C05 (design choice).** QA sidecar beside each release, warning-only: quality ledger, source fidelity against the PDF text layer, cross-representation, Operations margin signal, "N records not printed" annotations, explained page exclusions (A-401, A-402, A-403, A-401a, A-412, A-414; commits `2f97a80`, `0563fc0`, `bdb2f65`).

**A-F03 (finding).** Page 3 of the AK-3 end-of-well report is empty in K1 because it is a table of contents removed on purpose. The three pages with a high character ratio were false alarms caused by Markdown table syntax and by merged-cell text repeated in table Markdown. QA now reports an explained exclusion; the pipeline was not changed (progress report §3.4). Which three pages is not recorded.

**A-F04 (finding).** Source fidelity catches a fabricated sentence with a number in 158/158 cases and one changed digit in 141/157, but swapped or reordered text in 0/155; cross-representation catches a one-sided corruption in 60/60 and a consistent one in 0/60 (progress report §3.4).

**A-F05 (finding).** Parser comparison (A-501): on 10 gold tables Docling fast and accurate detect 10, Camelot stream 9, PyMuPDF 7; on the 81 Operations tables Docling fast 77, the A-107 rule 81 (built on them). The negative labels were unreliable (13 of 20 flagged pages held a table), so no false-positive rate is claimed (progress report §3.3).

**A-F06 (finding).** On four PDFs not used for tuning, 136 of 296 pages carried QA warnings and a viewed sample of 20 flagged pages gave a precision of 8/20: the thresholds are noisy outside the family they were tuned on (progress report §3.4).

**A-F07 (finding).** Multi-page table scan (A-108a): in the five RIMBase documents, 195 tables, 69 pairs of consecutive pages that both hold tables, 0 continuation candidates. Says nothing about other families (commit `270f00c`).

**A-D04 (decision).** The K1 package is shared as a zip and never committed (E30; Track B log B-F56). The branch `track-a-k1-package` was merged into `main` after Track B's review, with 614 tests passing; the id format was adopted as D-54 and the package as the interface, D-57.

**A-F08 (finding).** Known defect at this date: merged-cell text is repeated in table Markdown; listed as the first next priority (progress report §4, §7).

## 2026-11-17

Five commits (`60214e6`, `6ec7041`, `db892e7`, `7829bb8`, `49f0f88`) add options to the pipeline and to K1. **Every option is off by default**: absent from `configs/corpus/default.json` and `configs/corpus/k1.json`, and the default output is byte-identical to before on synthetic corpora (commit messages; `tests/test_options_default_off.py`). What each one does is in the [ingestion guide](../../components/corpus-ingestion.md); what was measured is below. "DEV/SEEN" means the documents the option was built on; for all of them, independent evaluation is recorded as not done.

**A-C06 (design choice).** Completeness gate for `k1` (TC-07): the export publishes only when every required document is ready; otherwise it exits with status 1, writes a failure report under `exports/.k1-failures/`, and leaves `CURRENT.json` and older releases alone. Before, it skipped such documents and published anyway. A behaviour change, not an option.

**A-C07 (design choice).** Resumable runs (C-04): four document states (completed, failed, interrupted, not started), a run marker per document, a pool that survives a dead worker; and a checked working copy of the source (REL-F1). Optional `cache.code_version` adds a hash of the processing code to the fingerprint.

**A-C08 (design choice).** Table Markdown modes `chunking.table_markdown` (corpus option, part of the fingerprint): `span_once` (A-415) writes a merged cell's text once; `span_once_keyed` (A-431) also keeps a row-spanning key cell on every row and keeps the chunk row boundaries, so chunk ids and `row_start`/`row_end` stay those of the default output. Table records do not change. Measured on a release: not recorded.

**A-C09 (design choice).** Section context (A-434), K1 option `section_context`: drops running banners, report-date stamps and e-mail addresses from `section` and `section_path`; optional numbered hierarchy. Ids, text and offsets unchanged. Measured: not recorded.

**A-C10 (design choice).** Lower form blocks (A-435), K1 option `form_blocks`: pairs the safety and weather labels below the tables by row geometry. Motivation measured on the development form pages: about 44% of the same-line `Label: value` pairs in the Docling text disagree with the PDF. Accuracy of the option itself: not recorded.

**A-C11 (design choice).** Form recognition, K1 option `form_recognition` (development candidate): header fields (`P1`) may be used in development; other regions (`P2`) are deferred and not accepted for shared configurations. An earlier internal evaluation run ended with a failed safety check whose cause is not resolved; its results were discarded. Tests use synthetic text layers only.

**A-C12 (design choice).** Tables cut by a page break (FR-25), K1 option `table_join`: joins a table ending page p with one starting page p+1 when the header repeats or the geometry and other evidence agree; otherwise keeps them apart and says why. DEV/SEEN only (50 PDFs, one annotator's gold); numbers not recorded in the guide.

**A-C13 (design choice).** Page filters, corpus options: `filters.running_line_position_tolerance` (numbers in table cells no longer lost as running lines; on DEV/SEEN restores five table-cell values on 78-32 pages 86 and 93, keeps all 1,122 furniture removals), `filters.running_line_min_pages`, `filters.toc_leader_min_dots` (C-03c; text cut with `...` was dropped as a contents line, 62 items in the 50 evaluated PDFs).

**A-C14 (design choice).** Page orientation (C-03), corpus option `analysis.page_orientation` (`flag` or `normalize`): on 9 synthetic sideways copies of three tables, Docling's table dimensions changed in 9 of 9, and in 0 of 9 copies whose `/Rotate` only compensates. The 13 rotated pages counted earlier (progress report §3.2) are the test named in task D2; the option was not measured on them.

**A-C15 (design choice).** Quarantine of uncertain text (`chunking.quarantine`, with `scan_tables`): records findings and can mark chunks `quality = review`, never changes text. Label-value repair (`chunking.label_value`, C-01c) is in the code and the tests; it is not described in the ingestion guide. Measured: DEV/SEEN only.

**A-C16 (design choice).** QA checks added: cross-representation for merged cells, label-value, form-conflict, multi-page structure and orientation, with measurement scripts (commit `db892e7`). Warning-only.

**A-D05 (decision).** PyMuPDF (AGPL-3.0 or commercial) stays out of the production path: no module under `src/graph_builder` imports it; tests and QA scripts use it through the optional extra `qa`. Whether that fits how the repository is distributed is unresolved ([dependencies](../../components/dependencies.md), checked 16 November).

**A-F09 (finding).** Still open after 17 November: which options go on (task D2) has no number on the demo release for any option.

## 2026-11-24

Entries of this day were made by the W5 work package on Khai's behalf.

**A-F10 (finding).** Two tests failed on a machine without PyMuPDF (note of 24 November): `tests/test_corpus_table_join.py` stopped at `import fitz`, and `test_broken_pdf_is_recorded_and_other_documents_survive` errored because `scripts/qa_multipage_scan.py` opens PDFs with PyMuPDF. Now `fitz` is imported optionally and only `RealPdfTests` (the one class that draws a PDF) skips with "PyMuPDF not available"; the multipage test skips the same way. Without PyMuPDF, 71 of the 75 tests of the two files run and 4 skip.

**A-F11 (finding).** Merged-cell text repeated in table Markdown (task D4) was already fixed on 17 November by `chunking.table_markdown = span_once_keyed` (A-C08); no second fix was written. A test now reproduces the repetition at the level of the chunk text with a merged header (`MergedHeaderInChunkTextTests` in `tests/test_table_markdown_keyed.py`). Measured on the demo release (A-F15), the mode against the default:

| | Default | `span_once_keyed` |
|---|---:|---:|
| Table chunks whose text changes | — | 11 (appendices 27, 28, 30), 1,470 characters fewer |
| Chunk ids, table ids, row ranges, `tables.jsonl` | — | identical |
| QA `CHAR_RATIO_HIGH` warnings | 2 (appendix 28 page 32, appendix 27 page 40) | 0 |
| Other QA signals | — | unchanged |

Whether these two pages are among the "three high character-ratio pages" of A-F03 is not recorded (A-F03 does not name them). The mode is a corpus setting, so switching it on means processing again (from the cached conversion: about 3 minutes for the six documents, no conversion).

**A-F12 (finding).** End-of-well reports name their own well only once for sure: on the cover. AK-3's report names `AK-3` on 25 of its 29 pages but also `TG-2` (7 pages) and `TG-4` (4 pages), in its text layer. The three covers in `data/raw` have three layouts: the well on the line before "End of Well Report" (AK-3), on a line of its own after it (68-32), and at the end of a line "... Well 56-32" (56-32).

**A-C17 (design choice).** Optional K1 key `document_context` (`document_types`, `pages`, `well_patterns`; off by default, enters the package identity): sets `context.well` on every chunk of a document type such as `eowr`, from the first `pages` pages of its text layer. The well is set only when exactly one distinct candidate is found; none or several leave the chunks without context and list the pages under `pages_without_context`. The types must differ from `report_context`'s. The validator then requires a well on those chunks, `context_coverage` in the manifest covers them, and the export result lists the well and its candidates per document (outside the package). No K1 field and no schema change: `context.well` already exists. The demo configuration [`configs/corpus/candidates/k1_demo_v1.json`](../../../configs/corpus/candidates/k1_demo_v1.json) is `k1.json` plus one cover pattern, which gives AK-3, 68-32 and 56-32 on the three reports.

**A-F13 (finding).** The Docling conversions of appendices 23 and 27 to 30 in the E8 corpus (`data/corpora/ak3_appendices`) can be reused: all their pages are `text` mode, so the OCR engine plays no part, and the segment files are exactly those the new page plan asks for. The new corpus with the candidate's settings (`configs/corpus/candidates/demo_corpus.json`: rapidocr, weather lines kept) has fingerprint `e99d077b7d5ffcb5`, the same as the candidate's. The end-of-well report was not converted anywhere and was converted again (29 pages, 11 with OCR, 834 s on the last attempt). Its 61 chunks equal the candidate's in id and text, and every non-table chunk of the daily reports equals the candidate's.

**A-F14 (finding).** On a 16 GB machine shared with other jobs, the end-of-well conversion stopped three times (two native crashes, exit codes 0xC0000005 and 139, and one `not enough memory`) at 93 to 98% memory load. Each run resumed from the cached segments, so no work was lost; the fourth run finished.

**A-C18 (design choice).** [`scripts/build_k1_demo_release.py`](../../../scripts/build_k1_demo_release.py) builds the demo release in one command: `init`, `add` (the end-of-well report as `gdr882_ak3_eowr`), optional reuse of text-mode segments from an earlier corpus (A-F13), `process`, `k1 --legacy-chunks`, and a copy of the release to `data/interim/k1/ak3-demo-v1/`. `scripts/check_k1_graphrag_compat.py` gains check (6): Track B's event graph built from the package alone, appendix 23 included, with `--expect-events`.

**A-F15 (finding).** Demo release `ak3-demo-v1` (task D1), release `20261124T102709Z-085c791db13e`: 6 files, 176 pages, 1,051 chunks, 197 tables, 81 forms, 933 parents; K1 schema version 1, field list unchanged. Configuration: today's `k1.json` (with the Operations Summary rule) plus `document_context`; `table_markdown` not set. The five checks of the note's Task 1:

| Check | Result |
|---|---|
| Validator | pass, 0 errors, page rebuild 176/176. A second export gives an identical `SHA256SUMS`. QA sidecar runs; validator pass |
| Daily chunks with report date and well | 981 of 981 (the candidate had 979: the Operations Summary rule rebuilds tables, which adds 2 table chunks) |
| Event graph | 161 events, no event chunk id with `#`, 28 non-productive events from appendix 23 inside the package (check (6) above). Date, times, hours, depth, activity code and non-productive code equal E31's recorded 161 events; 35 descriptions differ, by words the rule recovers ("gasoline to camp", "water pump set"). The note's literal command fails: see A-F16 |
| `legacy_chunk_ids.json` inside | Present and in `SHA256SUMS`; 60 old chunks, 49 exact, 2 near, 9 unmapped. Hung's `platform/load_k1.py`, run against a private schema that was dropped afterwards, reports "legacy map 60", rebuilds 176/176 pages from the database. Gold coverage 15 of 17, as in E30 with rapidocr (`#c0004`, `#c0005` unmapped); 17 of 17 was only reached with easyocr (A-D02) |
| End-of-well chunks with a well | 61 of 61 (`AK-3`); 0 in the database without a well |

Compatibility check: no id-format gaps in `graphrag`; BM25 over the end-of-well chunks gives hit@5 0.913, the same as E30 with rapidocr.

**A-F16 (finding).** `python -m graphrag.events build --k1` still reads appendix 23 from the corpus export `data/corpora/ak3_appendices/exports/v1` (`npt_report_inputs` in `graphrag/events.py`), with version 0 ids, even when the K1 package holds it. So the note's check "no event chunk id contains `#`" can only pass through the command after a change in `graphrag` (Track B's code), which reads appendix 23 from the package. Check (6) of the compatibility script shows that change gives 161 events with no `#`.

**A-D06 (decision, proposed for Khai).** Open for Khai under task D2: whether the demo release switches on `span_once_keyed` (A-F11 is the number for it) and whether 17 of 17 cited chunks (easyocr) matters more than the prototype's text (rapidocr, A-D02).
