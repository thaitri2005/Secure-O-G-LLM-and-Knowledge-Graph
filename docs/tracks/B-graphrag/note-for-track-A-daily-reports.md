# Note for Hung (Track A): what Track B needs for daily reports

From Tri, Track B, 4 November 2026. Full evidence: [E24](../../experiments/E24-ak3-daily-reports.md).

We ran the current K1 version 0 pipeline on the four AK-3 daily-report attachments. These PDFs have a good text layer (0 OCR pages), so the problems below come from layout and reading order, not OCR.

Plain RAG scored 5/30. Given the right page, the model scored 19/30. The 30 questions are simulated and not expert-reviewed, and 12 of them ask about form headers, so use the failure types below, not the totals.

## What we need in K1 version 1

| Priority | Need | Why | Example |
|---|---|---|---|
| 1 | **Key-value pairs from form headers**, with each label joined to its value | Labels and values come apart and the columns interleave. 6 questions fail even with the right page | The form prints `Vertical Depth (ft): 465`; the chunk reads `Drilling Days (plan): 465 Days On Location: 1700` |
| 2 | **A report date on every chunk of a daily report**, as a field | 630 of 898 chunks have no date in their text or section, so retrieval cannot tell the days apart. Attachment 29 loses the date altogether: the PDF prints `Daily Well Graphical Summary 20-Aug-16`, and no chunk of that page has it | Only the header says `Report For 28-Aug-16` |
| 3 | **Form regions kept as tables:** inventory, drilling parameters, bit and BHA, safety | They come out as text with split columns, and regions get mixed | `POLY VIS 13 GEL 0 DIESEL 1 Equipment Problems: ... Sky: 9 35 2 CEMENT 0` |
| 4 | **Values kept on the last row of the form** | Printed values are missing from the chunks | Report 1's `Vis.: 6 Temp: 58` is in the PDF's text layer, but 58 is in no chunk of that page |
| 5 | Correct section titles | Report 17's header chunk is filed under `Rig/Weather Information`, and the first chunk of report 7 in attachment 30 carries the previous day's `Report For 17-Aug-16` | Section titles cannot be used to filter |
| 6 | Merged table headers split | Two columns become one | `Operations Description Non-Prod`, `Used Invent.` |
| 7 | **Keep the operations tables' rows and their last column** | Track B's event graph is built from them ([E28](../../experiments/E28-event-graph.md)). The `X` in `Non-Prod` is lost on some rows, and the one-row table on 13 August comes out as text | Report 9 prints `X` on 17:00-18:00; the parsed row has none |

On item 4, our suspicion is the footer filter: the row lies 7.1% from the page bottom, inside `margin_band` 0.08. This is not confirmed, because other pages keep parts of the same row.

## What already works

Operations, mud and survey tables keep their rows, and the model answers all 6 questions on them when given the right page. Please keep this behaviour. We sampled four days and did not audit every cell.

## Corpus pipeline problems you may want to fix

Tell us if another track owns these.

- `process --workers 2` hung after exactly 40 documents in two runs. `process.py` sets `max_tasks_per_child=20`, and 2 × 20 = 40. The cause is inferred from the count, not traced. Restarting finishes the rest.
- `scripts/run_ak3_appendices.py` prints "done" after every document has failed, and does not pass `--retry-failed`.
- `gdr882-ak3-appx-04-12-akutan-3` now fails validation (`region outside page 4`) and is held back. E8 processed it on an earlier commit.

## How to check your output

The questions are in [`graphrag/gold/ak3_daily_v0.json`](../../../graphrag/gold/ak3_daily_v0.json). Their gold values name PDF pages, not chunks, so they work with any parser. Once your chunks are in the corpus format:

```powershell
python -m graphrag.oracle --answer-format evidence_first --max-tokens 700 --name my_check
```

19/30 is the number to beat with that command.

Track B now works around priority 2 with a date filter ([E27](../../experiments/E27-date-filter-and-coverage.md)): it guesses each page's date from `Report For` and `Report No`, and gets all 145 pages right. That doubled the score on unseen questions, so a real report-date field is worth having: it would replace the guess and work on other report series. Priorities 1 and 3 have no workaround on our side. Operations tables are now the most valuable thing you parse for us: the event graph, our best result on daily reports, rests on them (all 161 rows recovered, by merging attachments).

Table mappings on an unseen report ([E25](../../experiments/E25-table-mappings-unseen-report.md)) had a similar lesson: 78-32's forms come out as mixed grids too.

Dense survey tables on other reports ([E29](../../experiments/E29-table-mappings-across-reports.md)): the parser merges neighbouring rows into one (`114.20 125.50` over `0.20 0.10`) and shifts columns, on TNT-GT-01 and TNT-GT-02. We get half the rows at best, and 8% of those are wrong. Scanned reports such as Raft River RRGE-3 come out column by column, with no rows to read. Both matter if the corpus grows.

Tell us when K1 version 1 is ready, and Track B will rerun E24, E27 and E29.
