# Track B: next runs

Status on 24 November 2026: **E23 to E31 are done.** Next, in order: E32 (answers on K1 version 1, [commands below](#answers-on-k1-version-1)), E33 (the coordinator on the 221 pooled questions) and E34 (the reasoning probe); see the [plan's task list](../../DEVELOPMENT_PLAN.md#7-what-to-do-now) and log entries B-D36 to B-D38. **The team has no GPU of its own now** (B-D42, B-D43): the desktop these runs were written for was borrowed. Run them on a hosted open-weight model on public data ([below](#on-a-hosted-model)) or on a school GPU with the local commands as written.

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
| The expert question set, or a specification for development questions, asked for in the [5 November update](../../reports/stints/STINT_UPDATE_2026-11-05.md) | Supervisor and the expert group | Write or take the questions, rerun the baseline and both graphs, and decide the graphs for good (B-D24, B-D26) |
| **High priority:** shared hosting of the stores on a free cloud tier, owned by Track C, with Tri and Khai added as users (B-D35) | Hung, Track C | Read K1 packages and chunks from the shared store instead of zips |
| Appendix 23 (the non-productive-time report) inside the K1 package, so the event graph reads only K1 (E31) | Khai, Track A | Drop the old-corpus fallback in `events.npt_report_inputs` |
| Reading chunks from Track C's PostgreSQL, and both graphs in Neo4j ([note](note-for-track-C-storage.md)); vector store is pgvector (D-56) | Hung, Track C | Point the baseline at the store; BM25 stays for one-well questions, pgvector embeddings for several |
| Whether users ask questions over time (B-D26, Q3). The fact graph is in the design (B-D29), and the supervisor accepted the lanes as a concept on 9 November | Supervisor and the expert group; the application's question log (B-D37) | Confirm or reverse the event graph |
| The purpose of use: document types and kinds of question (Q13) | Supervisor | Split, merge or add lanes (B-D32, B-D36) |

## After each run

1. Add a record `docs/experiments/E<n>-*.md` and a row in the [register](../../experiments/README.md).
2. Add findings and decisions to the [log](log.md), and update its "Current state" table.
3. Update the results table in [CLAUDE.md](../../../CLAUDE.md).
4. Commit as yourself, with no AI attribution, then `git pull --rebase` and push.
5. Mark the run done in this file.

## On a hosted model

All data in these runs is public (AK-3 and the Utah FORGE reports), so a hosted open-weight model is allowed (D-38, D-68). Set `OPENROUTER_API_KEY` first.

| Local command part | Hosted |
|---|---|
| `--endpoint local-llama --model qwen3-8b` (`graphrag.baseline`, `graphrag.events answer`) | `--endpoint openrouter --model qwen/qwen3-8b` |
| The coordinator and the backend, which read the roles file | `$env:GRAPHRAG_ROLES = "deploy/models/roles.openrouter.json"` before the command |
| Questions naming several wells (they need the embedding server) | `--no-embeddings` on the coordinator, or `--multi-well-retriever perwell:bm25` on the baseline; say so in the record |

Rules for a hosted run (D-68):

1. **Rerun the baseline on the same endpoint first.** A hosted score is compared only with another hosted score, never with the recorded local ones.
2. Record the provider OpenRouter routed to, the model ID and the date with the run. Report tokens and cost; seconds say little there.
3. Check on the first run that thinking is off (answers arrive without a reasoning block and at the usual token counts); if it is not, stop and record what the provider needs.
4. None of this has been run: the model ID and the provider's behaviour are unverified until the first call.

Cost: the 221 pooled questions are about 0.7 million prompt tokens, so E33 with its baselines, E32 and E34 together come to a few million tokens, under US$1 at the listed prices ([resource request](../../reports/RESOURCE_REQUEST_2026-11-24.md)).

## Answers on K1 version 1

Use the demo release `ak3-demo-v1` (`python scripts/build_k1_demo_release.py`, Track B log B-C55), in ignored `data/interim/k1/`; set `GRAPHRAG_K1_CHUNKS` to its `chunks.jsonl` if another package is there too. The compatibility check and the event graph need no model. These need a model, shown here with the local endpoint:

```powershell
python -m graphrag.baseline answer --pool k1_ak3 --retriever bm25 --k 5 --endpoint local-llama --model qwen3-8b --name E32_k1_prototype
python -m graphrag.events answer --k1 --questions ak3_events --name E32_k1_events
python -m graphrag.events answer --k1 --questions ak3_events_heldout --name E32_k1_events_heldout
python -m graphrag.baseline answer --pool k1_daily --retriever dates:wells:bm25 --k 5 --questions ak3_daily_heldout --endpoint local-llama --model qwen3-8b --name E32_k1_daily_heldout
```

Compare with E17 (28/31), E28 (22/35, 19/23) and E27 (14/26). On `k1_ak3` the retrieval hit flags use old gold chunk IDs and are not meaningful; scores are by value. `DateRouter` still guesses dates from text; swapping in K1's report date field is the next small change.
