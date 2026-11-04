# E24: Plain RAG on the AK-3 daily reports

| | |
|---|---|
| **Date** | 4 November 2026 |
| **Question** | Where does the pipeline break on daily drilling reports (dense forms, one per day), and which failures belong to parsing, retrieval or the model? |
| **Requirement** | B-D22, next-runs E24; the list of parsing failures is for Track A |
| **Input** | The four daily-report attachments of the AK-3 appendices: 145 pages, 898 chunks, 0 pages needing OCR. Corpus pipeline defaults, release `20261104T142124Z-a3acbd713b05` (ignored by git) |
| **Code** | `graphrag/data.py` (loader), `graphrag/baseline.py` (`--pool ak3_daily`), `graphrag/oracle.py` (retrieval bypassed) |
| **Gold data** | [`ak3_daily_v0.json`](../../graphrag/gold/ak3_daily_v0.json): 30 questions, 27 with gold, 3 must not answer. Written from the rendered PDF pages before the attachments were parsed, so gold does not inherit parsing errors. **Simulated: no drilling expert has reviewed it** |
| **Models** | Qwen3-8B (thinking off), `-c 32768 -np 1 -ngl 99`, one request at a time; Qwen3-Embedding-0.6B for fusion |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E24_*.json` |
| **Status** | Done |

## Results

| Setup | Correct of 30 | Correct of the 27 with gold | Wrong values | Wrong abstentions | Gold day retrieved |
|---|---:|---:|---:|---:|---:|
| Plain: BM25 routed by well, top 5, status first | **5** | 2 | 2 | 23 | 13/27 |
| Fusion, top 10, evidence first | **9** | 7 | 13 | 8 | 16/27 |
| Right page given, status first | 11 | 8 | 1 | 18 | n/a |
| **Right page given, evidence first** | **19** | 16 | 4 | 7 | n/a |

The last two rows bypass retrieval and read the gold data, so they are a diagnostic and not a pipeline. They bound what better retrieval alone could reach.

Correct by kind:

| Kind | Questions | Plain | Fusion | Right page, evidence first |
|---|---:|---:|---:|---:|
| Form header field | 12 | 0 | 1 | 4 |
| Form comment | 1 | 0 | 1 | 1 |
| Graphical form | 2 | 0 | 2 | 2 |
| Operations table | 3 | 1 | 0 | 3 |
| Survey table | 1 | 0 | 0 | 1 |
| Mud table | 2 | 1 | 2 | 2 |
| Bit table | 2 | 0 | 1 | 2 |
| Inventory table | 1 | 0 | 0 | 0 |
| Drilling parameters table | 1 | 0 | 0 | 1 |
| Across days | 2 | 0 | 0 | 0 |
| Must not answer | 3 | 3 | 2 | 3 |

Cost per question, with cost in dollars 0 because the runs are local:

| | LLM calls | Prompt tokens, median | Completion tokens, median | Seconds, median |
|---|---:|---:|---:|---:|
| Plain | 1 | 1,158 | 21 | 0.44 |
| Fusion | 1 | 4,012 | 172 | 2.43 |
| Right page, status first | 1 | 1,636 | 21 | 0.43 |
| Right page, evidence first | 1 | 1,694 | 139 | 1.48 |

- These figures leave out the fusion index and query embeddings.
- **Cost per page to parse:** no LLM calls, about 0.93 seconds per page (135 seconds for 145 pages, two workers).

## Which layer fails

**Retrieval and the answer format lose the most.** Given the right page with evidence first, the model answers 19/30 instead of 5/30.

- *Dates:* a question says "28 August 2016", while the forms say `28-Aug-16`. Only 268 of the 898 chunks have a date in their text or section, and filtering by well does not separate days, because all four attachments name AK-3.
- *Answer format:* on the same pages, status first gets 11/30 and evidence first 19/30, confirming B-F22 on forms. Evidence first with real retrieval, though, gives 13 wrong values against 2.

**Parsing sets the ceiling.** With the right page, 11 of the 27 gold questions still fail, and the 9 listed below trace to parsing.

## For Track A (Hung): parsing failures

The PDFs have a good text layer (0 OCR pages), so all of this is about layout and reading order. Examples are from `gdr882-ak3-appx-30` unless noted.

| # | Failure | Evidence | Questions lost even with the right page |
|---|---|---|---|
| 1 | **Key-value form headers are read in the wrong order:** labels and values come apart and the two columns interleave | Report 17 prints `Vertical Depth (ft): 465`. The chunk reads `Spud Date: Major LF90 Drilling Days (act.): Drilling Days (plan): 465 Days On Location: 1700`. Report 13 ends up with `Totals: 18.26` for the leak-off test (LOT) | d01, d08, d09, d10, d14, d21 |
| 2 | **Form regions that are tables on the page come out as text with their columns split** | Inventory: 1 table in 24 chunks. Drilling Parameters: 0 in 22. Report 17 reads `POLY VIS 13 GEL 0 DIESEL 1 Equipment Problems: ... Sky: 9 35 2 CEMENT 0`, mixing inventory and weather | d18 |
| 3 | **Values printed on the page are missing from its chunks** | Report 1 prints `Vis.: 6 Temp: 58` on its last row, and the PDF's text layer has it. No chunk on that page has the 58. The row lies 7.1% from the page bottom, inside the 8% `margin_band` filter. **Suspected cause, not confirmed:** other pages keep parts of the same row | d04, d19 |
| 4 | **Chunks lose which day they belong to** | 630 of 898 chunks have no date in text or section. Section titles are often wrong: report 17's header chunk is under `Rig/Weather Information` | Not lost with the right page, but a main reason retrieval fails |
| 5 | A table header merges two columns | `Operations Description Non-Prod` is one column, and `Used Invent.` is another case | None here |

What works and should be kept:

- Operations, mud and survey tables keep their rows and cells on the pages sampled, and the model reads them: all 6 such questions are right with the right page.
- This is not a cell-by-cell audit.

**Needed in K1 version 1:** key-value pairs from form headers, and a report date on every chunk of a daily report.

The two across-days questions (d26, d27) also fail with the right pages. Both need header fields, so parsing is the likely cause, but this run does not separate it from the model's arithmetic.

## Pipeline problems found while regenerating the chunks

| Problem | Evidence |
|---|---|
| **`process --workers 2` hangs after exactly 40 documents** | It happened in two runs, both at 40 of 44 or 43 documents with no workers left to take the rest. `process.py` sets `max_tasks_per_child=20`, and 2 × 20 = 40. The likely cause is that retired workers are not replaced (Python 3.12.10); that is inferred from the count and not traced in the code. Restarting `process` finishes the remainder |
| **`scripts/run_ak3_appendices.py` prints "done" after every document has failed**, and does not pass `--retry-failed`, so a rerun does not retry them | First run on this machine |
| **`gdr882-ak3-appx-04-12-akutan-3` fails validation and is held back from the export** | `region outside page 4` and later pages. E8 processed all 44 documents on an earlier commit. Not a daily report, so it does not affect E24 |
| **Setup not in the runbook:** VietOCR, its models, and one online Docling run to cache the models | `HF_HUB_OFFLINE=0` for a single document fetches them |

## Limits

- **The mix drives the score.** 12 of 30 questions are form headers, by the author's choice, so 5/30 is not a general figure for daily reports. Read the layers, not the total.
- Four sampled days of 27, one report series, 30 questions, simulated.
- "Gold day retrieved" counts any attachment's copy of that day's pages, even when the value is printed on another copy. It says little about whether the value reached the model.
- **One answer is not repeatable:** in the uncached repeat of Plain, d20 went from a wrong `1955` to an abstention. The other 29 kept their status and values, and the score stayed 5/30. E23's repeats had no such change, so this was not expected under one request at a time.
- `graphrag/oracle.py` reads the gold data, so its scores are not results a system could reach.
