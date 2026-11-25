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
| Demo release (D1, D3) | Built (`demo-v2`: the end-of-well reports of AK-3, 56-32 and 68-32, appendices 23 and 27 to 30; 8 files, 302 pages, 1,431 chunks, and 1,432 when built on Linux). Validator pass, the legacy map inside, 161 events from the package. Loaded into the stores on a cloud machine. The build script reads `configs/corpus/candidates/k1_demo_v1.json` (the settings of before 24 November), not `k1.json`: the options added to `k1.json` on 24 November never touched `demo-v2`. Rebuilt on 25 November from the cached conversions with the previous settings: 1,431 chunks, 292 tables, 94 forms, the same as `demo-v2` | A-F20 to A-F22, A-F23 |
| End-of-well chunks with a well | Optional K1 key `document_context` (off by default); on in the demo configuration | A-C17 |
| Operations Summary tables | Rebuilt from the PDF text layer when four gates pass (A-107); in `configs/corpus/k1.json` | A-C04 |
| Merged-cell text repeated in table Markdown (D4) | Mode `span_once_keyed` (A-431) clears both `CHAR_RATIO_HIGH` warnings and changes no id, but on two stacked-header tables it drops the group label from the second spanned column (the guard counts Docling's header rows, not the table record's). Decision: the default stays `docling` until the guard is fixed (a code change, not made here). `span_once` also loses one chunk id | A-F24, A-D08 |
| Options of 17 November | Measured on the demo release on 25 November (D2). `section_context` is on in `k1.json`; `table_join` stays as shipped (it joins nothing on the demo); `form_blocks`, `form_recognition`, `page_orientation`, `table_markdown` and `label_value` stay off, each with a number | A-F25 to A-F28, A-D07 |
| Options turned on by default on 24 November | Measured by leaving one group out on the demo release. Kept on: grid recovery (source, complex, borderless, ruled panels). Turned off in `k1.json`: document type from the PDF title, numeric repair, scan grids and fields, hourly/casing/mud/daily-log/well-completion rules, daily header and report fields. The 24 November profile is kept as `configs/corpus/candidates/k1_standard_24nov.json` | A-F29, A-D07 |
| QA sidecar | Warning-only checks; thresholds noisy outside the family they were tuned on (8/20 precision on a sample) | A-C05, A-F06 |
| Tests without PyMuPDF | Skip with a reason (24 November) | — |
| Open | The benchmark manifests that scripts and records point to (plan task D6), the VLM comparison, scanned pages, forms outside the RIMBase template, a fix of the stacked-header guard of `span_once_keyed`, the id numbering of section parents when table rules add tables, and an independent evaluation of every decision here (NOT EVALUATED; the demo release is development data) | A-F23 to A-F29 |

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

The entries below were made later on 24 November by the X4 work package, on Khai's behalf, **for Khai to correct**. X4 added the two other end-of-well reports to the demo package so that the fact graph's passages exist in the stores (Track B log B-F63).

**A-C19 (design choice).** The legacy chunk map covers every document of the bundle that the export holds, not only AK-3's report. `map_legacy_document` in `k1_export.py` maps each bundle document onto its own new chunks only (the same text in two reports never crosses), in doc id order; AK-3's report is still required, as before. `load_legacy_rows` takes `None` for every document. No K1 field, schema or version changed. A test exports two bundle documents with the same text and checks that each maps onto its own (`test_legacy_map_covers_every_bundle_document_in_the_export_and_never_crosses_documents` in `tests/test_corpus_k1.py`).

**A-C20 (design choice).** `scripts/build_k1_demo_release.py` now builds `demo-v2` into `data/interim/k1/demo-v2/`: the eight PDFs of `ak3-demo-v1` plus `gdr1295_56-32_eowr.pdf` and `gdr1153_68-32_eowr.pdf`. Each end-of-well report is added under its bundle doc id (`gdr882_ak3_eowr`, `gdr1295_56-32_eowr`, `gdr1153_68-32_eowr`), so the legacy map finds it. `add` runs every time and skips files already in the corpus, so a corpus built for `ak3-demo-v1` gains the two reports and keeps its conversions. `--legacy-chunks` defaults to the committed bundle. Configurations unchanged: `demo_corpus.json` and `k1_demo_v1.json` (whose cover pattern already found 56-32 and 68-32, A-C17).

**A-F19 (finding).** No conversion of the end-of-well reports could be reused. The corpus of 24 November (`data/interim/k1-demo-corpus`) is no longer on the machine. `data/interim/docling/5ebba303446ca4bb` holds whole-document conversions of the three reports from the earlier pipeline, without OCR; the seeding rule (A-F13) accepts only per-segment text-mode conversions, and the hybrid pages need OCR. So the three reports were converted again, one at a time, with the appendices' segments seeded from a copy of `data/corpora/ak3_appendices`. The run took 2,698 s (45 min) in all, on a 16 GB machine at 93 to 95% memory load, with no crash:

| Report | Pages (hybrid) | Segments | Conversion |
|---|---:|---:|---|
| 68-32 | 40 (10) | 9 | 18.5 min |
| 56-32 | 86 (49) | 24 | 19.2 min |
| AK-3 | 29 (11) | 18 | about 3.5 min |
| Appendices 23, 27 to 30 | 147 (0) | seeded | none |

Single segments took between 3 s and 419 s. The slowest ones came while other jobs held the memory.

**A-F20 (finding).** Demo release `demo-v2`, release `20261124T164744Z-6647c02f0c85` (SHA256SUMS digest `6647c02f0c85…`): 8 files, 302 pages, 1,431 chunks, 292 tables, 94 forms, 1,139 parents, nothing held back. The checks:

| Check | Result |
|---|---|
| Validator | pass, 0 errors, page rebuild 302/302 |
| QA sidecar | validator pass, source validation pass. Signals (warnings): `OCR_PAGE_NO_REFERENCE` 70, `TABLE_ORIGIN_TEXTLAYER_REBUILD` 81, `CHAR_RATIO_HIGH` 16, `TABLE_CHUNK_OVER_BUDGET` 10, `DROPPED_ITEMS_RECORDED` 8, `PAGE_EMPTY_EXPLAINED_BY_EXCLUSION` 5, `CHAR_RATIO_LOW` 3, `CHUNK_QUALITY_NOT_OK` 2, `A107_SIDECAR_MISSING` 1. Not compared with `ak3-demo-v1`'s signals |
| End-of-well chunks with a well | 441 of 441: AK-3 61, 56-32 246, 68-32 134. `document_context` found exactly one candidate on each cover |
| Daily chunks with report date and well | 981 of 981 |
| Same as `ak3-demo-v1` | AK-3's report and the five appendices give the same chunk ids and the same text, chunk for chunk |
| `scripts/check_k1_graphrag_compat.py --expect-events 161` | all six checks pass: 161 events, 28 non-productive, no `#`; BM25 hit@5 0.913 on AK-3's report; gold coverage 15 of 17, as before |

Not checked: whether a second export gives the same `SHA256SUMS`.

**A-F21 (finding).** The legacy map of `demo-v2` covers the bundle's 372 old chunks:

| Report | Old chunks | Exact | Near | Unmapped |
|---|---:|---:|---:|---:|
| AK-3 | 60 | 49 | 2 | 9 |
| 56-32 | 200 | 142 | 2 | 56 |
| 68-32 | 112 | 103 | 1 | 8 |
| All | 372 | 294 | 5 | 73 |

It reaches 36 of the 38 chunks Track B's fact graph cites. The two it does not reach are `gdr1295_56-32_eowr#c0039` and `gdr882_ak3_eowr#c0004`. Why 56-32 leaves 56 old chunks unmapped (the new parser split or merged them, or OCR on its 49 hybrid pages changed the text) was not looked into.

## 2026-11-25: the demo package built from nothing on Linux

Recorded by Track B with Khai's clearance (Track B log B-F71).

**A-F22 (finding).** `demo-v2` was built on a cloud Linux machine with 4 cores and no GPU, from an empty checkout: the three end-of-well reports downloaded from the Geothermal Data Repository and checked against their recorded SHA-256, AK-3's appendix corpus built first (44 PDFs, 463 pages, 1,775 chunks, none failed, 56 minutes, most of it one scanned 91-page appendix), then the package (15 minutes). The commands are in [next-runs.md](../B-graphrag/next-runs.md#building-the-demo-package-from-nothing-on-linux).

| | A-F20 (laptop) | Built here |
|---|---:|---:|
| Release | `20261124T164744Z-6647c02f0c85` | `20261124T185223Z-ccc792161833` |
| Files, pages | 8, 302 | 8, 302 |
| Chunks | 1,431 | **1,432** |
| Parents | 1,139 | **1,140** |
| Tables, forms | 292, 94 | 292, 94 |
| AK-3 report, 56-32, 68-32 chunks | 61, 246, 134 | 61, 246, **135** |
| Daily-report chunks | 981 | 981 |
| Old chunks mapped exactly, nearly, not at all (of 372) | 294, 5, 73 | **287, 9, 76** |

- **The package is not the same to the chunk on another machine.** The one extra chunk is in the 68-32 report, whose hybrid pages go through OCR; AK-3's report and the daily reports are identical. Not tracked down. A record that uses a package names its release ID.
- The package's own validator passes with 0 errors and 302 of 302 pages rebuilt; `scripts/check_k1_graphrag_compat.py` passes, with 161 events.
- **Gaps met on the way:** the three end-of-well PDFs have no download command under the names the build expects; the first Docling run needs `HF_HUB_OFFLINE=0`, which the notes gave only as a remedy; the appendix corpus needs `vietocr`, which is outside the lock file; `platform/validate_k1.py` is the version 0 checker and does not apply to a package. The run notes now state all four.
- `process --workers 1` did not hang; the hang after 40 documents was with two workers.

## 2026-11-25: D2 and D4 measured on the demo release

Plan tasks D2 and D4 for Khai. Method and the rules written before the numbers: [E62](../../experiments/E62-track-a-option-measurements.md). Every option or group was built once more from the cached Docling conversions of the eight demo PDFs (`demo-v2`'s files), with everything else equal. DEV data only: the generalization of every decision below is NOT EVALUATED.

**A-F23 (finding).** Baselines on the demo release, same code (main `efffa0d`), same conversions:

| | Previous settings (before 24 Nov) | Today's `k1.json` | Settings after A-D07 |
|---|---:|---:|---:|
| Chunks, tables, forms, parents | 1,431, 292, 94, 1,139 | 1,474, 298, 131, 1,182 | 1,431, 292, 94, 1,139 |
| Validator | pass | pass | pass |
| Chunks with `quality = review` | 25 | 65 | 25 |
| Daily-report chunks with report date and well | 981 of 981 | 969 of 1,024 | 981 of 981 |
| Old chunk ids mapped (exact, near, none; of 372) | 294, 5, 73 | 280, 15, 77 | 280, 15, 77 |
| QA warnings (`--fidelity --crossrep`) | 57 | 107 | 85 |
| `k1` export time, peak memory | 30 s, 205 MB | 104 s, 264 MB | 88 s, 255 MB |
| 81 Operations Summary tables | 81 | 81 identical | 81 identical |

The first column reproduces `demo-v2`. Today's `k1.json` changes 82 chunk ids of `demo-v2` (section parents are numbered again when new tables appear), moves 126 chunk ids to another page, adds 37 forms and 6 tables, writes a new optional table-part key (`native_trimmed_rows`), and leaves 55 daily-report chunks without report date and well. The compatibility check (`scripts/check_k1_graphrag_compat.py --expect-events 161`) passes on today's settings and on the settings after A-D07: 161 events, no `#`, gold coverage 15 of 17. It was not run on the first column.

**A-F24 (finding, D4).** 45 of 298 tables have merged cells (51 row-span and 159 column-span cells). Against the default, on the demo release:

| | `docling` | `span_once` | `span_once_keyed` |
|---|---:|---:|---:|
| Table chunks whose text changes | | 25 | 23 (14 tables) |
| Table chunk text, characters | 283,071 | 278,244 | 278,524 |
| `CHAR_RATIO_HIGH` warnings | 16 | 14 | 14 (appendix 28 page 32 and appendix 27 page 40 clear) |
| Chunk ids lost | | 1 (a row range moves) | 0; `tables.jsonl` identical |

All 14 changed tables were checked against the PDF text layer: a merged cell's text appears once and never zero times. One table was also read on the page image. Two tables lose information: appendix 27 page 35 and appendix 28 page 36 (survey tables) show "Coordinates" over N-S only; the E-W column loses its group label. The code decides "stacked header" from Docling's count of header rows (1 here) and not from the table record (2). Tri's statement that the mode clears both warnings and changes no id is confirmed; this defect is the cost.

**A-F25 (finding, table joining).** The shipped `table_join` found 104 candidate pairs and joined none: 94 separate, 10 uncertain (nine in the 56-32 report, one in appendix 23). All 10 uncertain pairs were looked at on the page images and all 10 are true continuations (56-32 pages 8-9, 9-10, 10-11, 14-15, 17-18, 41-42, 57-58, 80-81, 81-82; appendix 23 pages 1-2). So 0 wrong joins, 0 of 10 true continuations joined. The earlier candidate (`k1_table_join_candidate.json`, repeated-header rule) joins 3 pairs (56-32 pages 8-9, 10-11, 57-58), all correct, absorbing 3 table ids and adding 3 continuation chunk ids; nothing else changes. The 81 Operations Summary tables are identical in every run.

**A-F26 (finding, section context).** 300 chunk records change `section` or `section_path` (243 text, 57 table); ids, text and every other field stay. Sample of 38 text passages (seed 20261125, 5 per document; appendix 23 has only 3), headings judged on the PDF text layer and on the page image for 68-32: heading right 17 of 38 with the option off and 17 of 38 on (45%, interval 30% to 60%); wrong heading 14 off, 2 on; missing 3 off, 15 on; ambiguous 4 both. 12 passages go from a wrong heading (page banner, report date stamp or e-mail address) to none, 0 get worse. Not handled: the 68-32 report's sideways pages keep their page stamp as a heading (2 of 38). Labels are by one reader.

**A-F27 (finding, forms).** Scored on the 96 geometry-checked pairs of the lower form blocks (A-435 gold; appendix 27 and 28 pages, the pages the option was built on): previous settings 52 of 75 pairs right, 7 of 20 blanks right; today's settings 61 of 75 (one truncated value, "Overcast" for "Overcast / broken") and 7 of 20; with `form_blocks` 75 of 75 and 20 of 20. `form_blocks` also renames 12 form ids (the id of a form now points to another page), so it was not turned on. `form_recognition` (header-only and combined) changes nothing on the demo release. `chunking.label_value` rewrites the text of 262 chunks and marks 163 more as `review`; no pair score was made, so no decision.

**A-F28 (finding, page orientation).** The demo release has 40 pages with `/Rotate` other than 0, all in the 68-32 report (39 at 270, page 34 at 180), not 13; the other seven files have none. `flag` finds all 40 and changes nothing in K1. `normalize` turns tables of pages 17, 21 to 24 into loose text, lowers the share of PDF words found in K1 text from 97.1% to 94.6% and renames 50 chunk ids. `verify` accepts two pages (1 and 35: 27% to 43% and 87% to 91.5% of words, one more table), keeps the rest, and still renames 21 chunk ids of unchanged text. As read, the 40 sideways pages already give 97.1% of the PDF words.

**A-F29 (finding, groups).** Leave-one-out from today's settings, same conversions:

| Group left out | What changes on the demo release | Time of `k1` |
|---|---|---:|
| Document type from the PDF title (`evidence_routing`) | 27 more forms; 55 chunks gain report date and well (1,051 of 1,051 daily chunks have both) | 87 s |
| Numeric repair (4 settings) | nothing | 90 s |
| Grid recovery (source, complex, borderless, ruled panels) | 10 tables of the end-of-well reports change: every word of the 10 tables is in the PDF text, a missing column back on 56-32 page 31, a sideways table of 68-32 page 6 read as a table instead of fragments | 55 s |
| Scan grids and scan fields | nothing (no scanned table in these files) | 99 s |
| Hourly, casing, mud, daily-log and well-completion rules | 6 tables, 82 chunk ids renamed, key `parts.native_trimmed_rows` | 104 s |
| Daily header and report fields | 37 forms; 9 more pairs right, 1 truncated (A-F27) | 94 s |

Today's `k1.json` takes 104 s. Not measured: the scan group needs scanned tables, which the demo files do not have.

**A-D07 (decision, D2).** Applied literally from the rules of E62: on by default only if the validator passes, no id of an unchanged item changes, the sampled changed items include no regression and mostly improve, the 81 Operations Summary tables stay whole, time is at most 2x or the benefit is clear, and no K1 field changes. An option that does not fire has no evidence on this data and goes off unless the repository already holds evidence.

| Option or group | Decision | Reason |
|---|---|---|
| Section context | ON | A-F26 |
| Table joining | ON as shipped; ON-ONLY-FOR-CONFIG `k1_table_join_candidate.json` for the 3 correct joins | A-F25. Shipped profile joins nothing here; evidence elsewhere is E44 (development data) |
| Form blocks | OFF | 12 form ids change page (A-F27) |
| Form recognition | OFF | does not fire here |
| Page orientation (`flag`, `normalize`, `verify`) | OFF | A-F28 |
| Table Markdown modes | OFF (`docling`) | A-F24, A-D08 |
| Label-value repair | OFF | no pair score, 262 chunks rewritten |
| Document type from the PDF title | OFF | 55 daily chunks lose date and well; the 979 of 979 check fails |
| Numeric repair | OFF | does not fire here; when it fires it can write the new optional keys `numeric_repairs` and `scan_repairs`: needs a K1 version decision announced to Tri and Hung |
| Grid recovery | ON | A-F29 |
| Scan grids and scan fields | OFF | does not fire here; can write the new cell key `ocr_unreadable` (same K1 note); needs Tesseract |
| Hourly, casing, mud, daily-log, well-completion rules | OFF | ids renamed and a new K1 table-part key |
| Daily header and report fields | OFF | one truncated value in ten changed pairs; borderline (9 right, 1 truncated) |

`configs/corpus/k1.json` follows this table (commit "set reading-option defaults"). Setting an option off here means "not shared by default": each stays available through `configs/corpus/candidates/k1_standard_24nov.json`. The Current state row "All off by default" (17 November options) is replaced by the rows above.

**A-D08 (decision, D4).** `chunking.table_markdown` stays `docling`. `span_once_keyed` is the right mode once its stacked-header guard uses the table record's header rows; with that fix the two false `CHAR_RATIO_HIGH` alarms and 4,547 characters of repeated text go away without an id change. Switching the mode on is then a one-line corpus setting and a reprocessing from the cache (about 3 minutes for six documents). `span_once` is not recommended: it loses a chunk id.

**A-C21 (design choice).** The profile `main` shipped on 24 November is kept unchanged as `configs/corpus/candidates/k1_standard_24nov.json`. The tests that exercise the whole profile (`test_corpus_k1.py` fixtures, casing, hourly, report fields, form overlap, form recognition) load it; `tests/test_options_default_off.py` now states the defaults of A-D07. No source file, schema or K1 version changed.

**E62.** [Option measurements on the demo release](../../experiments/E62-track-a-option-measurements.md): the rules, the numbers and the limits behind A-F23 to A-D08.
