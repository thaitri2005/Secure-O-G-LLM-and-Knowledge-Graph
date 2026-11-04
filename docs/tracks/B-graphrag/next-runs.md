# Track B: next runs

Status on 4 November 2026: **E23 is done ([record](../../experiments/E23-simulated-set.md)); E24 and E25 have not been run.** Do them on the desktop (RTX 4080 SUPER); the laptop has no GPU or models. Decision and limits of the question set: [log](log.md), B-D22.

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

## E24: AK-3 daily reports

**Code is needed first:** no `--pool` covers these reports yet, and they use the corpus chunk format.

1. Regenerate the chunks, because `data/corpora/` is ignored by git:

   ```powershell
   python scripts/run_ak3_appendices.py --workers 2
   ```

2. Add a loader for `data/corpora/ak3_appendices/exports/v1/chunks.jsonl`, keeping the four daily-report documents (`doc_id` containing `dailyreport`), and a new pool in `graphrag/baseline.py`.
3. Write new questions in a new file, from those reports' pages, before any run. Do not change `simulated_expert_v0.json`.
4. Run plain RAG, then list every failure that comes from parsing: wrong cells, lost headers, split tables. Send that list to Hung. Also count failures from picking the wrong day among near-identical forms (E23, s27), which come from retrieval and not from parsing.

## E25: table mappings on an unseen report

**A new report is needed:** one public end-of-well report outside the three, not yet chosen ([Data sources](../../DATA_SOURCES.md)).

1. Parse it with the current pipeline.
2. Add it to the chunk input without changing the existing three reports.
3. Run `python -m graphrag.tables` on it and hand-check a sample of the facts. Do not edit the mappings first.

Report how many facts it found, how many are right, and what was missed. Then record any mapping fixes as a separate run.

## After each run

1. Add a record `docs/experiments/E<n>-*.md` and a row in the [register](../../experiments/README.md).
2. Add findings and decisions to the [log](log.md), and update its "Current state" table.
3. Update the results table in [CLAUDE.md](../../../CLAUDE.md).
4. Commit as yourself, with no AI attribution, then `git pull --rebase` and push.
5. Mark the run done in this file.
