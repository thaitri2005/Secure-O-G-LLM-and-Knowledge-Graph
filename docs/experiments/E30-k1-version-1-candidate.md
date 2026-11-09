# E30: K1 version 1 candidate for the AK-3 reports

| | |
|---|---|
| **Date** | 6 and 7 November 2026 |
| **Question** | Can Track A deliver a K1 chunk package (parent and child ids, forms, report dates, tables) for the AK-3 end-of-well report and its four daily-report attachments, from the current corpus pipeline, and does Track B's code read it? |
| **Requirement** | Track A item 4 (chunks, K1 version 1) in the [development plan](../DEVELOPMENT_PLAN.md), Track B's [note to Track A](../tracks/B-graphrag/note-for-track-A-daily-reports.md), specification §5.11 |
| **Input** | The AK-3 end-of-well report (`gdr882_ak3_eowr`, 29 pages) and appendices 27 to 30 (daily reports, 145 pages), from `data/raw/` (ignored by git). Scratch corpus `data/interim/k1-run/` (ignored). The main bundle in `data/processed/` is unchanged |
| **Code** | `src/graph_builder/corpus/{k1_build,k1_export,k1_validate,k1_config,forms,text_layer,form_scoring,report_context,legacy_ids}.py`, `configs/corpus/{k1,daily_reports}.json`, `schemas/k1_*.schema.json`, `scripts/evaluate_form_pairing.py`, `scripts/check_k1_graphrag_compat.py` |
| **Gold data** | Form annotations of the [ingestion exploration](../../explorations/ingestion/README.md) (single annotator, AI-assisted, five forms); the prototype's fact gold [`ak3_facts.json`](../../prototype/gold/ak3_facts.json) for the id map and retrieval check. Neither was edited |
| **Models** | Docling layout and fast TableFormer; `rapidocr` 3.10.0 for the 11 hybrid pages of the end-of-well report (`easyocr` 1.7.2 for the comparison). No language model, no GPU |
| **Outputs** | The five-document package, shared with the team as a zip on 9 November and **not committed**: data pushed to git is hard to remove. Track B reads it from ignored `data/interim/k1/` (Track B log B-F56). The sample this row first named was never committed |
| **Status** | Done for the version 1 candidate. Open items are listed at the end |

## Parser choice

The exploration compared parsers on nine annotated grid tables (mean data-cell accuracy). Docling with fast TableFormer scored 85.1%, accurate TableFormer 68.9%, and a local 1.2B document VLM 72.7%. Fast stays the parser. This is the exploration's own result: one annotator, AI-assisted, a small English sample. Details: [`explorations/ingestion/docs/evaluation.md`](../../explorations/ingestion/docs/evaluation.md#parser-comparison). K1 uses the corpus pipeline with `table_mode: fast` and does not re-measure the parser.

## Form pairing

The exploration's form code and RIMBase template were ported to `graph_builder.corpus.forms` and scored again on its annotations with `scripts/evaluate_form_pairing.py` (template on, generic off):

| Set | Exact pairs | Boxes |
|---|---:|---|
| Development (appendix 27 p1 and p2, 68-32 p17) | 141/141 | key and value boxes on every pair |
| Held out (appendix 27 p28, 78-32 p30) | 93/93 | key and value boxes on every pair |

This equals the exploration's 234/234. Appendix 30 page 17 gives `Vertical Depth (ft):` = 465 and `Days On Location:` = 17, never 1700. One early summary of the prototype quoted 1 for this field on report 17. The text layer of the PDF, the prototype output and the ported code all give 17; the value 1 belongs to report 1 on page 1, which the tests assert separately.

Template forms are found on 27 of 45 pages (appendix 27), 27 of 46 (appendix 28), 0 of 27 (appendix 29) and 27 of 27 (appendix 30). The other pages of appendices 27 and 28 are continuation pages that do not match the template (label share 0.19 to 0.21 on appendix 27 pages 8 and 14, against a 0.4 minimum); appendix 29 is a graphical report with no such form. With generic pairing off they get no form chunk, so K1 has 81 forms and fewer chunks than the prototype (below).

## Report date and well

| Attachment | Prototype chunks with date and well | K1 chunks with date and well |
|---|---:|---:|
| Appendix 27 | 198/307 | 289/289 |
| Appendix 28 | 231/347 | 328/328 |
| Appendix 29 | 0/82 | 55/55 |
| Appendix 30 | 307/307 | 307/307 |

The prototype took the context from form fields only. K1 takes the verified form first and falls back to regular expressions on the page text (`Report For <date>`, `Graphical Summary <date>`, and `Well ID:` or `Well Name:`). All 145 pages resolve, with no page without context and no disagreement between form and text. The well is `AK-3` everywhere. The prototype and K1 chunk counts differ because the prototype had generic forms on; the denominators here are each side's own chunks.

One regular expression had to change. The pattern first specified for the well, `Well (?:ID|Name):\s*([A-Z0-9][A-Za-z0-9-]*)`, returns `Geothermal` on every page of appendices 27 and 30, because the text layer reads `Well ID:` followed by the company name. K1 requires a digit in the id (`AK-3`, `68-32`, `78-32`). A well whose id has no digit would need another pattern.

## Cold and cached conversion

`convert_segment` returned the live Docling document on a fresh conversion and a re-read copy from the cache. Docling keeps text boxes that overhang the page in the live document and clamps them in the re-read copy, so the same input gave different chunks.

- Reproduced on appendix 4 (25 text pages): a cold run failed validation with `region outside page 4` and the same error on four more pages. The cause is the overhanging boxes, not rotated scanned pages as first suspected.
- Fix: both paths now read the document from the cache file. The pipeline version is unchanged, so existing caches stay valid.
- After the fix, cold and cached runs give byte-identical `chunks.jsonl`, `tables.jsonl` and `text.txt` (36 chunks). Three unit tests fail on the old logic and pass on the new.

## Weather footer on appendix 30

Track B reported that the weather line on page 1 of appendix 30 (`Vis.: 6 Temp: 58 ...`) was missing from the chunks. The corpus filter removes lines that repeat on many pages. The labels and bare numbers of the weather strip repeat on at least half of the pages and sit in the bottom margin band, so they were dropped as page furniture although the numbers are data.

| Page 1 of appendix 30 | Margin band 0.08 (default) | Margin band 0 |
|---|---|---|
| Bottom fraction of `Vis.:`, `Temp:`, `58` | 0.069 | 0.069 |
| Removed | `Vis.:`, `Temp:`, `58`, `6`, `Pressure:`, `Gusts:`, `16` | none |

| Document | Lines removed by default | With `keep_line_patterns` | Newly kept |
|---|---:|---:|---:|
| End-of-well report | 28 | 28 | 0 |
| Appendix 27 | 180 | 180 | 0 |
| Appendix 28 | 184 | 184 | 0 |
| Appendix 29 | 169 | 169 | 0 |
| Appendix 30 | 302 | 196 | 106 |

Decision: an optional setting `filters.keep_line_patterns` (list of regular expressions, absent means the old behavior) protects matching lines; [`configs/corpus/daily_reports.json`](../../configs/corpus/daily_reports.json) uses `\b(?:Vis\.|Temp|Pressure|Wind|Gusts):`. The 106 newly kept lines are all weather labels and numbers at bottom fraction 0.069 to 0.070. Job id, company name, well name, print date, `RIMBase` and `Page n of m` are still removed. A pattern anchored at the line start missed pages such as 26, where the strip begins with `Clear Vis.:`. On the fresh corpus, `58` is in the page-1 chunk `f62efbee00767a3e7:s6:c0` (`Vis.:` / `6` / `Temp:` / `58`). Compared with the prototype, 15 of the 27 pages of appendix 30 differ, and every difference is an added weather line; the other four documents are identical. The change touches `ingestion/filters.py` by one optional parameter with default `None`, and the main bundle test is unchanged.

## Old-to-new chunk ids

`export --legacy-chunks data/processed/gdr_chunks_full.jsonl` maps the 60 chunks of `gdr882_ak3_eowr` in the main bundle to K1 chunk ids (exact text with whitespace collapsed, then token Jaccard of at least 0.9). The prototype gold cites 17 of those chunks.

| OCR engine for the 11 hybrid pages | K1 chunks | Exact | Near | Unmapped | Cited chunks mapped |
|---|---:|---:|---:|---:|---:|
| `rapidocr` (primary; reproduces the prototype text) | 61 | 49 | 2 | 9 | 15 of 17 |
| `easyocr` | 60 | 51 | 4 | 5 | 17 of 17 |

With `rapidocr` this is the number measured on the prototype bundle: 49 exact, 2 near, 9 unmapped, and `#c0004` (page 5) and `#c0005` (page 6) are the two cited chunks without a match. The 9 unmapped chunks, with the best Jaccard score among the unused new chunks:

| Old chunk | Page | What changed | Best score |
|---|---:|---|---:|
| c0000, c0015, c0032, c0036, c0056 | 1, 9, 18, 20, 27 | A 36 to 132 character caption or address, now followed by text OCR read from the figure; the new chunk is 135 to 1,495 characters | 0.08 to 0.72 |
| c0004, c0005, c0006 | 5, 6 | Introduction paragraphs cut at different points | 0.59 to 0.64 |
| c0047 | 23 | Permeability paragraph, 1,051 instead of 964 characters | 0.885 (below 0.9) |

The two near matches are c0018 (0.9333) and c0048 (0.9592). The map is a migration aid: a chunk the new parser changed stays unmapped, and the gold was not edited. Ten of 28 text pages differ between the two OCR engines, so the id map and the retrieval numbers below depend on the engine. The gold cites unmapped chunks only under `rapidocr`.

## K1 package

Five documents, `rapidocr` for the end-of-well report, 174 pages, validator status pass with 0 errors, page rebuild 174 of 174, nothing held back.

| Document | Pages | Chunks | Tables | Forms | Prototype chunks |
|---|---:|---:|---:|---:|---:|
| End-of-well report | 29 | 61 | 6 | 0 | 62 |
| Appendix 27 | 45 | 289 | 58 | 27 | 307 |
| Appendix 28 | 46 | 328 | 81 | 27 | 347 |
| Appendix 29 | 27 | 55 | 0 | 0 | 82 |
| Appendix 30 | 27 | 307 | 46 | 27 | 307 |
| **Total** | **174** | **1,040** | **191** | **81** | |

Also 926 parents. The prototype counts include its generic-form chunks, which K1 leaves out. The 61 non-form chunks of the end-of-well report equal the prototype's 61, and its text is identical page by page on 28 of 28 text pages. Non-form text of appendices 27, 28 and 29 is identical on every page.

**Determinism and size.** Two independent exports (`k1a`, `k1b`) have byte-identical `SHA256SUMS`, and a second export of `k1b` after the last code change matches too. The package is 5.5 MB, of which `chunks.jsonl` is 2.8 MB, `forms.jsonl` 1.0 MB and `tables.jsonl` 1.0 MB. The committed sample (end-of-well report and appendices 30 and 29) is 2.2 MB; appendices 27 and 28 would take it past 3 MB. Converting the 174 pages took 12.9 minutes on CPU, and an export takes about 50 seconds.

## Check against Track B's code

`scripts/check_k1_graphrag_compat.py` imports `graphrag` without changing it and runs on the CPU. No llama.cpp, GPU, embedding endpoint or language model step was run.

| Check | Result |
|---|---|
| `graphrag.data.load_chunks(path=chunks.jsonl)` | 1,040 of 1,040 rows load, ids equal |
| `"dailyreport" in doc_id` and `doc_id.split("-appx-")[1][:2]` | 4 attachments, numbers 27 to 30; 16 chunks on appendix 30 page 17 through `chunks_on_pages` |
| `tables.jsonl` and `graphrag.ontology.table_rows` | 191 tables with `table_id`, `doc_id`, `cells`; every table gives rows; every table chunk finds its table |
| BM25 over the end-of-well report (23 of the 31 prototype questions have gold), gold ids remapped | `rapidocr`: hit@1 0.652, hit@3 0.826, hit@5 0.913, hit@10 0.957. `easyocr`: 0.696, 0.957, 1.000, 1.000. Old bundle with old ids: 0.696, 0.957, 1.000, 1.000 |
| Same, page level for unmapped gold chunks (secondary) | `rapidocr` hit@5 0.957, hit@10 1.000 |

With `rapidocr` two questions miss at hit@5, so the expected 1.00 is not reached:

- q03 ("How deep was well TG-2 drilled?"): its gold chunk c0004 is unmapped; the other gold chunk c0039 ranks 12. Two page-5 chunks, which carry the re-cut text of c0004, rank first and second, so the page-level check counts the question as found.
- q11 ("At what depth was the 4-1/2 inch casing set in AK-3?"): both gold chunks map exactly and rank 6 and later. A new figure chunk (page 18, `4.500ins Casing set at 800.08ft`, from OCR of Figure 10) scores higher. Here the change is in the chunk set, not in the id map.

**Id-format gaps in `graphrag`** (not changed here; K1 ids have no `#`):

| File and line | Effect with a K1 id |
|---|---|
| `graphrag/citations.py:25` | A cited id without `#` gets `<doc_id>#` prefixed, so it never matches a retrieved chunk |
| `graphrag/baseline.py:252` | The passage label is the part after `#`; with K1 it is the whole id |
| `graphrag/validate.py:95` and `:103` | Well names and a fact's document are taken from the part before `#`; with K1 every chunk is its own group |

**Table ids.** `configs/ontology/k2_eowr_v1.json` names tables of the old bundle (`gdr882_ak3_eowr#t002`, `#t004`, ...). K1 table ids are `<file_id>:t<n>`, and the corpus id is kept as `logical_id`. The old ids do not resolve in a K1 package, and the corpus ids of a new run need not equal the old bundle's, so K2 needs a table-id map from Track B.

## Not done

- Tables that continue over several pages are single-part tables in K1. The exploration's joining code (3 of 4 annotated tables joined, 0 of 3 held-out boundaries with the frozen rule) is not ported, and it is not merged with `ingestion/rotation.py`.
- No VLM comparison on the K1 pages.
- No route for scanned pages through OCRmyPDF.
- Forms outside the RIMBase template (the 68-32 and 78-32 layouts beyond the pages annotated) and continuation pages with a low label share get no form.
- Thick survey tables, and the metric survey rows Track B found unreliable in [E29](E29-table-mappings-across-reports.md), are not addressed.
- The environment: `rapidocr` needs `onnxruntime`, which the main virtual environment lacks, so the primary run used the exploration environment with `PYTHONPATH=src`.
- Track B follow-ups: the K1 id format in the three files above, and the old table ids in K2. Track C: review the six schemas.
