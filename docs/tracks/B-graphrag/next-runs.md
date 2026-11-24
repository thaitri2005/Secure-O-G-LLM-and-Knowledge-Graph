# Track B: next runs

**Next: E32, E33 and E34**, once there is compute ([plan task list](../../DEVELOPMENT_PLAN.md#7-what-to-do-now)). The team has no GPU of its own (B-D42, B-D43). The runs go on a rented cloud GPU, running our own copy of the model so scores stay comparable with the recorded ones, or on a hosted open-weight model on public data (D-68, B-D44). Neither is paid for yet ([resource request](../../reports/RESOURCE_REQUEST_2026-11-24.md)).

Every run goes through the model bench (`python -m graphrag.bench`, [how it works](../../../graphrag/README.md#trying-a-model-profiles-and-the-bench-d-62-d-68)): one command checks a model, one runs the whole suite, one compares runs.

| Measurement | What | Inside `bench run --suite full` |
|---|---|---|
| E32 | Answers on the K1 package `ak3-demo-v1` | Every step with `--k1`, and the prototype questions on the package's AK-3 report |
| E33 | The coordinator on the 221 pooled questions, against the hand-routed scores from the same model | The hand-routed baselines of the seven sets, then the coordinator |
| E34 | The reasoning lane on its ten frozen questions (`graphrag/gold/ak3_reasoning_probe_v0.json`) | The last step |

## On a rented GPU

1. Rent a 16 GB card or larger, with an Ubuntu CUDA "devel" image and a disk that is kept when the machine stops.
2. On the machine, clone the repository and run the setup. It is untested: read it first. It installs Python 3.12 and the packages, builds llama.cpp b12015, downloads the three models, and starts the answer model (port 8080) and the embedding model (8081) with the settings of [graphrag/README.md](../../../graphrag/README.md#running-locally):

   ```bash
   git clone <repository> kg && cd kg
   bash scripts/setup_gpu_box.sh /workspace/kg
   ```

3. Copy the K1 package (public data) to `data/interim/k1/ak3-demo-v1/`. Build it on a laptop with `python scripts/build_k1_demo_release.py`.
4. Check the model, then reproduce the baseline: the quick suite should give about 28/31, as the recorded run did.

   ```bash
   .venv/bin/python -m graphrag.bench check qwen3-8b.local
   .venv/bin/python -m graphrag.bench run qwen3-8b.local --suite quick
   .venv/bin/python -m graphrag.bench compare bench_qwen3-8b.local_quick E17_answers_bm25_k5_qwen3-8b
   ```

5. Run the suite. If the machine stops or a call fails, run the same command again: finished steps are skipped and answered questions come from the request cache, at no new cost.

   ```bash
   .venv/bin/python -m graphrag.bench run qwen3-8b.local --suite full --k1 data/interim/k1/ak3-demo-v1
   ```

6. Copy `graphrag/results/bench_qwen3-8b.local_*` and `data/models.sha256` back, then stop the machine.

`check` and `run` refuse a server that runs another model file than the profile names. Another model is another profile: copy `configs/graphrag/models/qwen3-8b.local.json` and change `model`, `file` and the server command.

## On a hosted endpoint

All data in these runs is public (AK-3 and the Utah FORGE reports), so a hosted open-weight model is allowed (D-38, D-68). Set `OPENROUTER_API_KEY` first.

```powershell
python -m graphrag.bench check qwen3-8b.openrouter
python -m graphrag.bench run qwen3-8b.openrouter --suite quick
python -m graphrag.bench run qwen3-8b.openrouter --suite full --k1 data/interim/k1/ak3-demo-v1 --no-embeddings
python -m graphrag.bench compare bench_qwen3-8b.openrouter_full
```

Rules for a hosted run (D-68):

1. **Rerun the baseline on the same endpoint first.** The full suite does this: its hand-routed steps are that endpoint's baseline. A hosted score is compared only with another hosted score, never with the recorded local ones; `compare` puts them in separate tables and says so.
2. **Record the provider.** OpenRouter routes each call to one of several providers. The run records the providers that answered, and `compare` warns when there was more than one. To hold one provider, add `"order": ["<provider>"], "allow_fallbacks": false` to the profile's `request.provider`.
3. **Check that thinking is off.** `bench check` fails if a reply carries a reasoning block or far more completion tokens than its text. The profile turns thinking off with OpenRouter's `reasoning` field; this is unverified until the first check.
4. Without the embedding server, `--no-embeddings` answers questions naming several wells with per-well BM25. Say so in the record.

Cost: the 221 pooled questions are about 0.7 million prompt tokens, so the full suite comes to a few million tokens, under US$1 at the listed prices.

## After a run

1. Write a draft record. It fills in the header, the commands and the tables, and leaves the prose blank for a person: `python scripts/experiment_record.py E33 bench_qwen3-8b.local_full --title "The coordinator on the pooled questions"`.
2. Write the parts marked **TO WRITE**, then add the row to the [register](../../experiments/README.md) by hand. The script never adds it.
3. Add findings and decisions to the [log](log.md), and update its "Current state" table and the results in [CLAUDE.md](../../../CLAUDE.md).
4. Commit as yourself, with no AI attribution, then `git pull --rebase` and push.

## Rebuilding inputs and reproducing earlier runs

The daily-report corpus (ignored `data/corpora/`), needed for daily-report runs without `--k1` ([E24](../../experiments/E24-ak3-daily-reports.md)):

```powershell
python -m pip install --no-deps vietocr==0.3.13
python -m graph_builder.corpus models
python scripts/run_ak3_appendices.py --workers 2
```

- Docling's models must be cached once. If every document fails with `LocalEntryNotFoundError`, run `process` on one document with `HF_HUB_OFFLINE=0`, then `process --retry-failed`.
- `process --workers 2` hangs after 40 documents. Stop it, run `process` again, then `export --name v1`.
- Chunks are in the release folder that `exports/v1/CURRENT.json` names; `graphrag/data.py` follows it.

Table mappings on unseen reports ([E25](../../experiments/E25-table-mappings-unseen-report.md), [E29](../../experiments/E29-table-mappings-across-reports.md)). The registry's PDFs come from each entry's `source_url` (for 58-32, the attachment `58-32_EOWR_DOE.pdf` of its binder), saved as `data/raw/<doc_id>.pdf` and checked by their SHA256:

```powershell
python -m graph_builder.ingestion run --sources configs/sources/gdr_e25_78-32.json --config configs/ingestion/default.json --run-name e25_78-32
python -m graph_builder.ingestion run --sources configs/sources/gdr_e29_unseen.json --config configs/ingestion/default.json --run-name e29_all
python -m graphrag.tables --run e29_all --name my_tables
python -m graphrag.tables --run e25_78-32 --name my_tables_78-32
python -m graphrag.table_eval --facts my_tables my_tables_78-32 --runs e29_all e25_78-32 --name my_score
```

The event graph ([E28](../../experiments/E28-event-graph.md)): `python -m graphrag.events build --name my_events`.
