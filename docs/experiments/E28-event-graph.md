# E28: An event graph from daily-report operations tables

| | |
|---|---|
| **Date** | 4 and 5 November 2026 |
| **Question** | The per-well fact graph did not beat plain RAG, on questions that were mostly lookups (B-D24). Does a graph of events beat it on questions over time, which retrieval cannot assemble? |
| **Requirement** | B-F45, B-D25 (no new ontology), specification D-36 |
| **Input** | The four AK-3 daily-report attachments and the non-productive-time report (appx-23), K1 version 0 chunks and tables |
| **Code** | `graphrag/events.py`; `graphrag/retrieval.py` (`page_dates` fix) |
| **Gold data** | [`ak3_events_v0.json`](../../graphrag/gold/ak3_events_v0.json) (35 questions, frozen before the graph was built) and [`ak3_events_heldout_v0.json`](../../graphrag/gold/ak3_events_heldout_v0.json) (23, frozen before the planner fix was run). Gold is computed by code from the PDFs' text layer, independent of the parsed chunks. **Simulated: no drilling expert has reviewed them** |
| **Models** | Qwen3-8B (thinking off), `-c 32768 -np 1 -ngl 99`, one request at a time; Qwen3-Embedding-0.6B for fusion runs |
| **Outputs** | [`graphrag/results/`](../../graphrag/results/): `E28_*.json`; K4 records in `E28_heldout_graph.k4.jsonl` |
| **Status** | Done |

## How it works

1. **Build, with no model call.** Well → report date → event → activity code and non-productive code. Each event keeps the chunks it came from. Rows from the operations tables of the attachments are merged by date and time, then joined with appx-23.
2. **Plan.** Qwen3-8B turns the question into a JSON plan: an operation (total hours, count, dates, first or last date, top group, depth) and filters. The list of activity codes, each with an example from the reports, is generated from the data, so there is no glossary to write and no new ontology.
3. **Run the plan in code.** Totals and comparisons do not depend on the model. An unknown well, code or period gives "no events match".
4. **Answer.** Qwen3-8B writes the answer from the result and the source passages. A question the plan calls `not_answerable` falls back to the daily-report baseline.

The graph is kept in memory as indexed records, with no traversal beyond those links. **A win here is a win for structured events; it says nothing about graph databases.** It has not been loaded into Neo4j.

## Build quality

Checked against the gold rows from the PDFs' text layer, before any model saw a question:

| | Result |
|---|---:|
| Events, gold rows | 161 of 161 |
| Differences in hours, depth or code | 0 |
| Total hours | 647.5, same as gold |
| Non-productive hours | 115.0, same as the report's printed Well Total |
| LLM calls | 0 |

No single source was complete. The summary attachment omits rows ("1 record not printed"), each attachment loses some rows, and the parser turned one 24-hour row into text. Merging recovers them. Every day sums to 24 hours except 26 August (23.5), where the report itself has no row for 18:15 to 18:45.

## Results

| Questions | Setup | Correct | Wrong values | Wrong abstentions |
|---|---|---:|---:|---:|
| **Frozen 35, the official result** | **Event graph** | **22** | 3 | 10 |
| | Event graph, evidence first | 23 | 7 | 5 |
| | Plain, daily reports: date filter, BM25, top 5 | 4 | 7 | 24 |
| | Plain, daily reports: fusion, top 10, evidence first | 4 | 18 | 13 |
| | Plain, all AK-3 documents: BM25, top 5 | 5 | 3 | 27 |
| | Plain, all AK-3 documents: fusion, top 10, evidence first | 4 | 15 | 16 |
| Same 35 after the planner fix (**already seen**) | Event graph | 27 | 2 | 6 |
| **New 23, with the fix** | **Event graph** | **19** | 3 | 1 |
| | Plain, daily reports | 4 | 2 | 17 |
| | Plain, all AK-3 documents | 4 | 2 | 17 |
| **26 daily-report lookups (regression, E27's unseen set)** | Plain, date filter (E27) | 14 | 2 | 10 |
| | **Event graph, falling back to plain** | **17** | 1 | 8 |

Plain RAG over all AK-3 documents had the non-productive report and the end-of-well report in its pool, and these state some totals outright. That is why it gets a few of them.

Correct by kind, frozen 35 (before the fix) and new 23:

| Kind | Frozen 35 | Event graph | Best plain | New 23 | Event graph | Plain |
|---|---:|---:|---:|---:|---:|---:|
| Total hours by code | 6 | 5 | 0 | 3 | 3 | 0 |
| Total hours in a date range | 3 | 3 | 0 | 2 | 2 | 0 |
| Non-productive hours | 5 | 0 | 2 | 4 | 3 | 0 |
| Days with non-productive time | 2 | 0 | 0 | 1 | 1 | 0 |
| Counts | 3 | 2 | 0 | 2 | 1 | 0 |
| List of dates | 3 | 3 | 0 | 2 | 1 | 0 |
| First or last date | 3 | 1 | 1 | 2 | 2 | 0 |
| Depth over time | 4 | 4 | 1 | 3 | 3 | 1 |
| Largest group | 3 | 1 | 0 | 1 | 0 | 0 |
| Must not answer | 3 | 3 | 3 | 3 | 3 | 3 |

"Best plain" takes the highest of the four plain setups for each kind, so it can add up to more than any one setup.

Cost per question:

| Setup | LLM calls | Prompt tokens, mean | Completion tokens, mean | Seconds, mean |
|---|---:|---:|---:|---:|
| Event graph (new 23) | 2 | 3,111 | 206 | 2.5 |
| Plain, daily reports (new 23) | 1 | 1,884 | 43 | 0.8 |

The graph doubles the calls and adds about 900 prompt tokens per question, for the planner. All local, $0.

**Cost per page to build:** no LLM calls and no embeddings, on top of parsing (about 1 second per page, [E24](E24-ak3-daily-reports.md)). The fact graph costs 2.48 LLM calls per page.

## Where it still fails

1. **The final model step garbles right results.** On the new 23, the graph's result held the gold value on 19 of the 20 questions with gold, and 16 of those were answered correctly. For example, g07: the graph said 6.5, the model said 4. t23: the graph gave the date, and the model abstained. If code reported the result directly, these would be right; **computed from the rows, that gives 22/23, and it was not run.**
2. **The planner sometimes errs.** g20 and t32 filter the "which code has the most hours" question by a code. t18 counts events when asked for days.
3. **The planner fix came from the frozen run's failures:** it fills the code field with `non_productive`, or with the non-productive code. Code now drops such a value. That is why the frozen 22 stays the official figure; 27 is on questions the fix was made from.
4. **Citations:** a total is not written in any passage, so the citation check marks it unsupported (19 of 31 citations in the frozen run). The source events' chunks are now recorded with each answer, and K4 cites them with `how: event_graph`. No citation check confirms that a passage supports a computed total; the reader has the source rows instead.

## What was learned

1. **On questions over time, this graph beats plain RAG by a wide margin:** 22/35 against at best 5/35, and 19/23 against 4/23. Plain RAG sees five to ten passages, so it cannot add up 27 days.
2. **It does not hurt lookups:** 17/26 against 14/26, with fewer wrong values. The planner sent 22 of the 26 to retrieval. The gain is too small to claim beyond "no harm".
3. **This answers why the earlier graphs did not help:** the shape of the graph has to match the questions. Static per-well facts duplicate what retrieval finds; events add what it cannot do.
4. **The operations tables are reliable enough to build on,** even from K1 version 0. Merging repeated attachments makes up for what each one loses.

## Limits

- **The questions were chosen to suit this graph, by the author who built it.** The result shows a graph can help on totals over time, not that users ask such questions. Only the expert set or the supervisor can say that.
- One well and one report system (RIMBase forms); 27 days. Other report series have not been tried, and `page_dates` and the table detection depend on these forms' labels. 68-32's and 78-32's daily forms are known to parse as mixed grids (E22, E25), so **this will not carry over to them until K1 version 1.**
- The plain setups use an unchanged retriever. A plain pipeline with a larger budget might do better on a few, but it would not add up 27 days reliably, and we did not test that.
- The non-productive answers rely on the separate appx-23 report, because the parser loses `X` marks in the daily forms' last column. Reports without such a summary would have to use those marks.
- The event-graph runs were each run once.

## Corrections to earlier records

`page_dates` now takes the last section title on a page and prefers a date in the text. It dates 145 of 145 pages correctly, up from E27's 143. No E27 question uses those days, so E27's scores stand.
