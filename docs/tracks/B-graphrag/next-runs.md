# Track B: next runs

**Next: E33 and E32** ([plan task list](../../DEVELOPMENT_PLAN.md#7-what-to-do-now)). E34 is recorded ([two probes](../../experiments/E34-reasoning-probe.md)). The team has no GPU of its own (B-D42, B-D47). The long run goes on a rented cloud GPU, running our own copy of the model so scores stay comparable with the recorded ones, or on a hosted open-weight model on public data (D-68). Neither is paid for yet ([resource request](../../reports/RESOURCE_REQUEST_2026-11-24.md)). A machine without a GPU does the short runs ([how](../../../graphrag/README.md#without-a-gpu-on-linux)).

Every run goes through the model bench (`python -m graphrag.bench`, [how it works](../../../graphrag/README.md#trying-a-model-profiles-and-the-bench-d-62-d-68)): one command checks a model, one runs the whole suite, one compares runs.

| Measurement | What | Inside `bench run --suite full` |
|---|---|---|
| E32 | Answers on the K1 package `demo-v2` | Every step with `--k1`, and the prototype questions on the package's AK-3 report |
| E33 | The coordinator on the 221 pooled questions, against the hand-routed scores from the same model | The hand-routed baselines of the seven sets, then the coordinator |
| E34 | The reasoning lane on its first probe (`graphrag/gold/ak3_reasoning_probe_v0.json`); recorded on a CPU, and repeated here on the GPU | The last step |

## On a rented GPU

1. Rent a 16 GB card or larger, with an Ubuntu CUDA "devel" image and a disk that is kept when the machine stops.
2. On the machine, clone the repository and run the setup. It is untested: read it first. It installs Python 3.12 and the packages, builds llama.cpp b12015, downloads the three models, and starts the answer model (port 8080) and the embedding model (8081) with the settings of [graphrag/README.md](../../../graphrag/README.md#running-locally):

   ```bash
   git clone <repository> kg && cd kg
   bash scripts/setup_gpu_box.sh /workspace/kg
   ```

3. Copy the K1 package (public data) to `data/interim/k1/demo-v2/`. Build it with `scripts/build_k1_demo_release.py` ([the steps, below](#building-the-demo-package-from-nothing-on-linux)).
4. Check the model, then reproduce the baseline: the quick suite should give about 28/31, as the recorded run did.

   ```bash
   .venv/bin/python -m graphrag.bench check qwen3-8b.local
   .venv/bin/python -m graphrag.bench run qwen3-8b.local --suite quick
   .venv/bin/python -m graphrag.bench compare bench_qwen3-8b.local_quick E17_answers_bm25_k5_qwen3-8b
   ```

5. Run the suite. If the machine stops or a call fails, run the same command again: finished steps are skipped and answered questions come from the request cache, at no new cost.

   ```bash
   .venv/bin/python -m graphrag.bench run qwen3-8b.local --suite full --k1 data/interim/k1/demo-v2
   ```

6. Copy `graphrag/results/bench_qwen3-8b.local_*` and `data/models.sha256` back, then stop the machine.

`check` and `run` refuse a server that runs another model file than the profile names. Another model is another profile: copy `configs/graphrag/models/qwen3-8b.local.json` and change `model`, `file` and the server command.

## On a hosted endpoint

All data in these runs is public (AK-3 and the Utah FORGE reports), so a hosted open-weight model is allowed (D-38, D-68). Set `OPENROUTER_API_KEY` first.

```powershell
python -m graphrag.bench check qwen3-8b.openrouter
python -m graphrag.bench run qwen3-8b.openrouter --suite quick
python -m graphrag.bench run qwen3-8b.openrouter --suite full --k1 data/interim/k1/demo-v2 --no-embeddings
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

## Building the demo package from nothing, on Linux

Run on 25 November 2026 on a cloud machine with 4 cores (Track B log B-F71). It needs no GPU and about 75 minutes of processing: 56 for the AK-3 appendix corpus, most of it one scanned 91-page appendix, and 15 for the package.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.lock.txt
uv pip install --python .venv/bin/python -e .
uv pip install --python .venv/bin/python -r backend/requirements.txt
uv pip install --python .venv/bin/python --no-deps vietocr==0.3.13      # only the appendix corpus needs it

# The three end-of-well reports, under the names the package expects; check them against configs/sources/gdr_end_of_well.json
mkdir -p data/raw && cd data/raw
curl -fsS -o gdr882_ak3_eowr.pdf    "https://gdr.openei.org/files/882/00%20AK-3%20EOW%20Report.pdf"
curl -fsS -o gdr1295_56-32_eowr.pdf "https://gdr.openei.org/files/1295/56-32%20EOWR%20-%20Final%2022%20July%202021.pdf"
curl -fsS -o gdr1153_68-32_eowr.pdf "https://gdr.openei.org/files/1153/Monitoring%20Well%2068-32%20-%20EOWR.pdf"
sha256sum *.pdf; cd ../..

.venv/bin/python -m graph_builder.corpus models --engine rapidocr       # OCR models into data/interim/ocr_models
.venv/bin/python -m graph_builder.corpus models
# Downloads AK-3's appendix portfolio, splits its 44 PDFs into data/raw, processes and exports them.
# HF_HUB_OFFLINE=0 on the first run only: Docling's layout and table models are fetched once.
HF_HUB_OFFLINE=0 .venv/bin/python scripts/run_ak3_appendices.py --workers 1
.venv/bin/python scripts/build_k1_demo_release.py --raw data/raw --models data/interim/ocr_models --reuse-corpus data/corpora/ak3_appendices

# Checks
(cd data/interim/k1/demo-v2 && sha256sum -c SHA256SUMS)
.venv/bin/python scripts/check_k1_graphrag_compat.py --k1 data/interim/k1/demo-v2 --expect-events 161
```

- **The package is not identical from machine to machine.** Built here it has 1,432 chunks, where the laptop's has 1,431: one more in the 68-32 report, whose pages are read by OCR. AK-3's report and the daily reports are the same chunk for chunk. A record names the package's release ID, not only its name.
- `platform/validate_k1.py` checks K1 version 0 files and does not apply to a package; the package's own check runs inside the build and in the runner's first step.

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
