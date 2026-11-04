# Track B: next runs

Status on 4 November 2026: **E23 to E27 are done, and no run is waiting.** The next runs depend on other people's work; see "Waiting on" below. Runs need the desktop (RTX 4080 SUPER); the laptop has no GPU or models. Decision and limits of the question sets: [log](log.md), B-D22.

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

5/30 with plain RAG, 19/30 when the model is given the right page. See the [record](../../experiments/E24-ak3-daily-reports.md), which holds the list for Hung.

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

## Waiting on

| What | From whom | Then |
|---|---|---|
| The expert question set | Supervisor and the expert group | Rerun the baseline and the fact sheet on it; decide the fact graph for good (B-D24) |
| K1 version 1: form key-value pairs, report dates, form tables ([note](note-for-track-A-daily-reports.md)) | Hung, Track A | Rerun E24 and E27; replace `page_dates` with the real field |
| Vector store | Khai, Track C | Choose together; the baseline needs only BM25 for one-well questions and embeddings for several |

## After each run

1. Add a record `docs/experiments/E<n>-*.md` and a row in the [register](../../experiments/README.md).
2. Add findings and decisions to the [log](log.md), and update its "Current state" table.
3. Update the results table in [CLAUDE.md](../../../CLAUDE.md).
4. Commit as yourself, with no AI attribution, then `git pull --rebase` and push.
5. Mark the run done in this file.
