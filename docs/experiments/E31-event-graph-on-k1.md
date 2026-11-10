# E31: The event graph rebuilt from Track A's K1 version 1 package

| | |
|---|---|
| **Date** | 10 November 2026 |
| **Question** | Does the event graph (E28) come out the same when built from Track A's K1 version 1 package instead of the K1 version 0 corpus, and do its links now point to the new chunk IDs? Step one of joining the tracks before the answers are rerun |
| **Requirement** | D-53 (event graph), D-54 (IDs), D-57 (K1 version 1 as the interface), Track C's request to link the event graph to K1 chunks (C-F06) |
| **Input** | Track A's package `ak3-k1-v1-candidate` (E30: 5 files, 174 pages, 1,040 chunks, 191 tables, rapidocr, with `legacy_chunk_ids.json`), in ignored `data/interim/k1/`. The non-productive-time report (appx-23) is not in the package, so it comes from the older corpus export `data/corpora/ak3_appendices/exports/v1` (E8) |
| **Code** | `graphrag/events.py` (`--k1`, `load_k1_inputs`, `build_events(..., dates)`), `graphrag/data.py` (`k1_chunks_path` finds a package in its own folder) |
| **Gold data** | E28's recorded event graph (`E28_events.json`) and its recorded query plans and results; nothing new |
| **Models** | None. Building the graph and running recorded plans make no model call |
| **Outputs** | [`graphrag/results/E31_events_k1.json`](../../graphrag/results/E31_events_k1.json) |
| **Status** | Done for the graph. The answer runs on K1 need the desktop's GPU and are not run yet |

## What changed in the build

- **Report dates come from K1.** Each daily-report chunk carries `context.report_date` (E30: 979 of 979), so each page's date is read from that field. E28 guessed it from the page text (`page_dates`, B-C22).
- **Tables come from K1** (`tables.jsonl`), read with the same `table_rows`.
- **NPT codes still come from appx-23**, joined by date and time as before. Its chunks keep version 0 IDs.

Command:

```powershell
python -m graphrag.events build --k1 --name E31_events_k1
```

## Results

| Check | Result |
|---|---|
| Events | 161 from K1, 161 in E28; the same 161 date and time keys |
| Fields | Hours, end depth, activity code and NPT code identical on all 161 |
| Totals | 647.5 hours; 115 non-productive hours in 28 events; 27 report days; all equal to E28 |
| Build | 160 events from the operations tables, 1 added from the non-productive report, as in E28 |
| Links | 160 of 161 events cite K1 version 1 chunks (`<file_id>:t<n>:c<n>`); the one added from appx-23 cites only that report, with a version 0 ID |
| Recorded plans | E28's final runs replay identically on the new graph: 35 / 35 (`E28_graph_fixed_seen`) and 23 / 23 (`E28_heldout_graph`) |
| Compatibility check (`scripts/check_k1_graphrag_compat.py`) | All checks pass; the ID map covers 15 of the 17 gold chunks the prototype cites; BM25 hit@5 0.913 against 1.00 on the old chunks, as in E30 |

`E28_graph`, the first run before the planner fix, replays 28 / 35: its 7 recorded results were empty because of the code bug fixed after it, not because of K1.

**Cost:** no LLM calls; building takes a few seconds on the laptop.

## What was learned

1. **Track A's package carries the event graph unchanged.** The graph side of every event-graph answer holds on K1 version 1, so the E28 scores should hold too. Only the final answer step reads passage text, which changed, so the answers still need one rerun.
2. **The report date field replaces a guess.** `page_dates` needed three rules and a fix to reach 145 of 145 pages; K1 gives the date directly.
3. **The event graph now links to the agreed chunk IDs,** which is what Track C needs to link Neo4j's events to the store (C-F06).

## Limits

- **This is the earlier package (1,040 chunks, E30).** Track C loaded a later one (1,042 chunks) without the legacy map. The later one likely includes Track A's Operations-table rebuild (A-107); this graph does not depend on it, since all rows were already recovered by merging attachments.
- **appx-23 is still read from the old corpus,** with version 0 IDs, until Track A adds it to the package.
- **No answers were rerun.** Retrieval and the final answer step need Qwen3-8B on the desktop.
