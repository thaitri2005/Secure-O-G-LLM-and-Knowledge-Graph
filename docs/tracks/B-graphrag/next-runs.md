# Track B: next runs

Status on 5 November 2026: **E23 to E29 are done.** The next runs depend on other people's work; see "Waiting on" below. Runs need the desktop (RTX 4080 SUPER); the laptop has no GPU or models. Decision and limits of the question sets: [log](log.md), B-D22.

## Before you start

```powershell
git pull --rebase
python -m unittest discover -s tests -p "test_graphrag.py"
```

Tests should print `OK` (3 skipped in `.venv`). Then start the servers ([commands](../../../graphrag/README.md#running-locally)):

| Server | Port | Endpoint | Settings |
|---|---|---|---|
| Qwen3-8B, answers | 8080 | `local-llama` | `-c 32768 -np 1 -ngl 99`, thinking off |
| Qwen3-Embedding-0.6B | 8081 | `local-embed` | Needed for the fact sheet ranking and `perwell:fusion` |
| Qwen3-4B, extraction | 8082 | `local-llama-2` | Only if you rebuild the graph |

Send one request at a time, and record the server settings with each run (B-F19).

## E23: does the graph help on the simulated set? (done)

Not on this set: 29/40 for both with top 5, and 31 and 30 with per-well retrieval. See the [record](../../experiments/E23-simulated-set.md).

## E24: AK-3 daily reports (done)

5/30 with plain RAG, 19/30 when the model is given the right page. See the [record](../../experiments/E24-ak3-daily-reports.md), which holds the list for Khai.

To regenerate the chunks on a new machine (`data/corpora/` is ignored by git):

```powershell
python -m pip install --no-deps vietocr==0.3.13
python -m graph_builder.corpus models
python scripts/run_ak3_appendices.py --workers 2
```

- Docling's models must be cached once. If every document fails with `LocalEntryNotFoundError`, run `process` on one document with `HF_HUB_OFFLINE=0`, then `process --retry-failed`.
- `process --workers 2` hangs after 40 documents ([E24](../../experiments/E24-ak3-daily-reports.md)). Stop it and run `process` again, then `export --name v1`.
- Chunks are in the release folder named by `exports/v1/CURRENT.json`; `graphrag/data.py` follows it.

## E25: table mappings on an unseen report (done)

Written from AK-3, the mappings found 3 facts on 78-32, with the wrong size on 2, and missed its 20-row survey. Two small fixes gave 23 correct facts without changing the original three reports. See the [record](../../experiments/E25-table-mappings-unseen-report.md).

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_e25_78-32.json --config configs/ingestion/default.json --run-name e25_78-32
python -m graphrag.tables --run e25_78-32 --name my_tables_78-32
```

## E26 and E27 (done)

[E26](../../experiments/E26-routing-and-strict-facts.md): routing and strict fact checks. [E27](../../experiments/E27-date-filter-and-coverage.md): the date filter and added coverage. The settings adopted from them are in the [README](../../../graphrag/README.md#the-baseline) (B-D23, B-D24).

## E28: the event graph (done)

22/35 and 19/23 against 5/35 and 4/23 for plain RAG, on questions chosen to suit it. See the [record](../../experiments/E28-event-graph.md).

```powershell
python -m graphrag.events build --name my_events
python -m graphrag.events answer --questions ak3_events_heldout --endpoint local-llama --model qwen3-8b --name my_graph_answers
```

Next on our side, when the work resumes: let code report the event graph's result directly, since the model garbles some right results (computed 22/23, not run), and load the graph into Neo4j with Track C.

## E29: table mappings across reports (done)

Held-out casing 4/16 as written, 13/16 with no wrong fact after fixes. See the [record](../../experiments/E29-table-mappings-across-reports.md).

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_e29_unseen.json --config configs/ingestion/default.json --run-name e29_all
python -m graphrag.tables --run e29_all --name my_tables
python -m graphrag.tables --run e25_78-32 --name my_tables_78-32
python -m graphrag.table_eval --facts my_tables my_tables_78-32 --runs e29_all e25_78-32 --name my_score
```

The registry's local PDFs come from each entry's `source_url` (58-32: the attachment `58-32_EOWR_DOE.pdf` of the binder), saved as `data/raw/<doc_id>.pdf`; the SHA256 in the registry checks them.

Worth doing when the work resumes:

- A different author's modern digital report, the real remaining test for the mappings (B-F54).
- The event graph on 58-32's `DailyDrillingReport.pdf`, also in that binder, as its first unseen report.

## Waiting on

| What | From whom | Then |
|---|---|---|
| The expert question set, or a specification for development questions, asked for in the [5 November update](supervisor-update-2026-11-05.md) | Supervisor and the expert group | Write or take the questions, rerun the baseline and both graphs, and decide the graphs for good (B-D24, B-D26) |
| The K1 version 1 package itself: the candidate is merged ([E30](../../experiments/E30-k1-version-1-candidate.md)), but its files are not in the repository (B-F55) | Khai, Track A | Rerun E17's baseline (hit@5 was 0.913 in E30), E24, E27 and E28; replace `page_dates` with the report date field |
| The ID scheme: Track A's `<file_id>:s<n>:c<n>` or another (B-F55) | Hung, Track C | `graphrag` reads either format (B-C28) |
| Vector store and Neo4j loading ([note](note-for-track-C-storage.md)) | Hung, Track C | Choose together; the baseline needs only BM25 for one-well questions and embeddings for several |
| Whether a graph goes in the main pipeline (B-D24, Q3) | Supervisor, through Tri | Confirm or reverse B-D24 |
| Whether users ask questions over time (B-D26, Q3) | Supervisor and the expert group | Confirm or reverse the event graph |

## After each run

1. Add a record `docs/experiments/E<n>-*.md` and a row in the [register](../../experiments/README.md).
2. Add findings and decisions to the [log](log.md), and update its "Current state" table.
3. Update the results table in [CLAUDE.md](../../../CLAUDE.md).
4. Commit as yourself, with no AI attribution, then `git pull --rebase` and push.
5. Mark the run done in this file.
