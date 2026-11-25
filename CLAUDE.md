# CLAUDE.md: start here

This file briefs any Claude session on any machine. The repository is the project's memory: if something is not written in it, it did not happen.

## The project

- A VPI capstone: a **GraphRAG application for drilling reports**, covering end-of-well reports and daily drilling reports.
- Design: a **coordinator in front of four lanes** (passages, well facts, events, reasoning about causes) over one graph with two regions (specification §8.1, §8.5). Existing open-source GraphRAG code is used as libraries and references; no base is adopted wholesale (D-50).
- Models: **open-weight, about 8B parameters or smaller, run by the team**. Commercial APIs are never used, not even for development.
- Compute: **the team has no GPU or server of its own**. It is rented, on public data only (D-68): a cloud GPU by the hour for the long measurements, OpenRouter for the demo. Not the school's machines. A machine without a GPU does the short measurements. No budget is approved yet ([resource request](docs/reports/RESOURCE_REQUEST_2026-11-24.md)).
- People: advisors Dr. Le Duy Dung and MSc. Nguyen Anh Tuan ("anh Tuấn", who supervises the work). It is a capstone, not research: prefer what works, start small, keep domain depth thin.

| Person | Role | Track log |
|---|---|---|
| **Tri, the user of these sessions** | Answering engine (`graphrag/`) and the web application (`frontend/`) | [B](docs/tracks/B-graphrag/log.md) |
| Hung | Stores and backend (`platform/`, `backend/`) | [C](docs/tracks/C-storage/log.md) |
| Khai | Reading the reports (`src/graph_builder/`) | [A](docs/tracks/A-ingestion/log.md) |

## Where to read

| For | Read |
|---|---|
| Where the project stands and what is left | [Plan, current status](docs/DEVELOPMENT_PLAN.md#current-status) and [§7](docs/DEVELOPMENT_PLAN.md#7-what-to-do-now) |
| The design | [Specification](docs/PROJECT_DESIGN.md): §4.6 the second build, §7.5 the API, §8.1 coordinator and lanes, §8.5 the graph, §8.6 the reasoning lane, §13.1 decisions (D-01 to D-69) |
| What was found, decided and built, by date | The track logs above. Track B's top table is its current state |
| Every measured result | [Experiment register](docs/experiments/README.md) |
| How the engine's modules fit, and how to run it | [graphrag/README.md](graphrag/README.md) |
| Running the application, the stores, a server | [backend](backend/README.md), [frontend](frontend/README.md), [platform](platform/README.md), [deploy](deploy/README.md) |
| Turning an expert's answers into a test | [docs/EXPERT_PILOT.md](docs/EXPERT_PILOT.md) |
| Every index | [docs/README.md](docs/README.md) |

Each kind of fact has one home (the table in docs/README.md). Link to it; do not copy it.

## Standing rules from the user

- **Log the same day.** Every finding (B-F), decision (B-D), design choice (B-C) and experiment goes into the [Track B log](docs/tracks/B-graphrag/log.md); a measurement also gets a `docs/experiments/E<n>-*.md` record and a row in the register. Project-level decisions also go into specification §13.1.
- **Keep documents readable.** Plain English, short tables and lists. When something changes, rewrite the text that describes it; do not append a note beside the old text. The log is the place for history.
- **Start small; efficiency is a headline metric.** Every run reports LLM calls, tokens, seconds and cost per page and per question, next to quality.
- **Reuse before writing.** Look at ready-made GitHub solutions close to the supervisor's description, then improve them. Any licence is fine with proper credit: keep the copyright notice and add a `NOTICE` file next to copied code.
- **No ontology work for now** (B-D25, D-52). Keep K2 thin.
- **Ignore `explorations/kg-builder/`** and **do not change `prototype/`**: the first is a teammate's exploration, the second is the baseline to beat.
- **Commits are authored as the user, with no `Co-Authored-By: Claude` or other AI attribution.** Push to `main`. Others push too: pull before pushing.
- **Say in the group chat what is being built before building in a teammate's track**, even with clearance (B-F65).
- **Simulated questions are never reported as expert validation.** Every question set so far is written by the team (B-D22). The sets in `graphrag/gold/` are frozen: a change goes into a new version.
- **Run one request at a time for measurements** (B-F19), and record the server settings, or the provider and model ID on a hosted endpoint.
- **Stint reports** say what each person built (the backend is Tri's and Hung's together) and do not comment on when the work happened. After changing one, run `python scripts/stint_figures.py` and `python scripts/render_stint_report.py <report.md>`.
- Vietnamese reports keep technical terms in English.

## What comes next for Track B

Everything code and a machine without a GPU can do for this build is done. The next steps each start with a person or with money ([plan §7](docs/DEVELOPMENT_PLAN.md#7-what-to-do-now)).

1. Send the [resource request](docs/reports/RESOURCE_REQUEST_2026-11-24.md) to anh Trường (capstone funding, as Dr. Dung said), and the [stint report](docs/reports/stints/STINT_REPORT_2026-11-27.md) to anh Tuấn. The stint report is a draft until the stint ends on 27 November.
2. **Measured with the real model**, on a 4-core machine without a GPU (Track B log B-F71 to B-F77): the baseline, answer for answer; the reasoning lane on two probes ([E34](docs/experiments/E34-reasoning-probe.md); it stays a probe, B-D50); one question through the whole application on the stores.
3. **Still to record**, with [these commands](docs/tracks/B-graphrag/next-runs.md):
   - **An expert's question set**, through both paths (hand-routed and coordinator) on one endpoint. [E33](docs/experiments/E33-coordinator.md) measured the coordinator on one team-written set per lane (102/119 against 87/119 hand-routed); long runs on the team's own questions have stopped (B-D51). [How an expert's answers become a test](docs/EXPERT_PILOT.md);
   - **E32:** answers on the demo package `demo-v2`, from files and then from the stores.
4. **Reasoning lane:** an expert's reading of ten answers, and a question set written by someone else, before more code.
5. **Without a GPU:** profile `qwen3-8b.cpu`, with the server started with `--cache-ram 0` ([how](graphrag/README.md#without-a-gpu-on-linux)). Profiles are in [configs/graphrag/models/](configs/graphrag/models/README.md).

## Commands

```powershell
python -m unittest discover -s tests                       # everything; store and PDF tests skip when absent
python -m unittest discover -s tests -p "test_graphrag*.py" # the engine
python -m unittest discover -s tests -p "test_backend*.py"  # the backend
cd frontend; npm test; npm run dev:examples                 # the application on example answers, no server
python platform/run_release.py data/interim/k1/demo-v2      # load a report package into the stores; --skip-vectors with no embedding server
python -m graphrag.bench check <profile>                    # is this model usable here? then: run, compare
docker compose -f platform/docker-compose.yml --profile app --profile demo up -d --build   # the whole application, with a stub model
python deploy/smoke_test.py --url <address> --user team     # check a running application from outside; --quick asks no question
```

- The stores need `platform/.env` with the two passwords (`platform-dev` on a laptop whose stores already exist).
- On a machine short of memory, set `OPENBLAS_NUM_THREADS=1` for the tests.
- `npm run types` in `frontend/` after the API contract changes; `python -m backend.contract` regenerates the contract.

## Setting up a machine with a GPU

Every run up to E31 was made on a borrowed desktop (RTX 4080 SUPER 16 GB, Windows) with llama.cpp. New runs use a rented cloud GPU set up the same way (on Linux, take the matching llama.cpp build), or OpenRouter. A machine without a GPU runs Qwen3-8B at about two minutes a lookup: enough for short measurements, not for the pooled run (B-F71).

1. `git pull`. Create `.venv` with Python 3.12, then `pip install -r requirements.lock.txt` and `pip install -e .`. The engine itself needs only `httpx` and `numpy`.
2. **llama.cpp:** release b12015 (the Windows CUDA 12.4 build plus its `cudart` zip), unpacked into ignored `data/interim/llama.cpp/`. Model files go into ignored `data/interim/models/`:

   | Model | Hugging Face repository and file |
   |---|---|
   | Answer LLM (baseline) | `Qwen/Qwen3-8B-GGUF`, `Qwen3-8B-Q4_K_M.gguf`; serve with thinking off |
   | Smaller LLM | `unsloth/Qwen3-4B-Instruct-2507-GGUF`, `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` |
   | Embeddings | `Qwen/Qwen3-Embedding-0.6B-GGUF`, `Qwen3-Embedding-0.6B-Q8_0.gguf` |

   Server commands are in [graphrag/README.md](graphrag/README.md#running-locally): `-c 32768 -np 1 -ngl 99`.
3. **Check the setup** by reproducing the baseline (E17); BM25 hit@5 should be 1.00 and the answers 28/31, wrong on q07, q25 and q31. Delete the `check*` result files afterwards.

   ```
   python -m graphrag.baseline retrieval --pool ak3 --retrievers bm25 --name check
   python -m graphrag.baseline answer --pool ak3 --retriever bm25 --k 5 --endpoint local-llama --model qwen3-8b --name check_answers
   ```
4. **Hosted instead:** set `OPENROUTER_API_KEY`, then `--endpoint openrouter --model <model id>` for `graphrag.baseline`, or `GRAPHRAG_ROLES=deploy/models/roles.openrouter.json` for the coordinator and the backend. Public data only. A hosted score is compared only with a baseline rerun on the same endpoint.
5. Only for the two library comparisons (E16, E19): separate environments `.venv-graphrag` and `.venv-lightrag` from their lock files, and Neo4j from `configs/graphrag/docker-compose.yml`.

## Useful facts

- **Chunk IDs** follow specification §5.11 as K1 version 1 writes them, for example `f62efbee00767a3e7:s6:c0` (D-54). The engine also reads version 0's `<doc_id>#c0005`.
- **Committed data:** `data/processed/gdr_chunks_full.jsonl` holds three end-of-well reports as K1 version 0 chunks (372 chunks; AK-3 is `gdr882_ak3_eowr`). Gold data for the prototype's 31 questions is in `prototype/gold/`.
- **Report packages are never committed** (B-F56). They live in ignored `data/interim/k1/`; set `GRAPHRAG_K1_CHUNKS` to a package's folder when more than one is there. The demo package `demo-v2` (three end-of-well reports, AK-3's daily reports) is built with `python scripts/build_k1_demo_release.py --raw data/raw --models data/interim/ocr_models`; from nothing it takes about 75 minutes ([all the steps](docs/tracks/B-graphrag/next-runs.md#building-the-demo-package-from-nothing-on-linux)). It has 1,431 chunks built on the laptop and 1,432 built on Linux, so a record names the release ID.
- **The fact graph** the stores load is `graphrag/results/E32_fact_graph.graph.json` (207 facts).
- **Headline results so far**, all on questions written by the team, are in the [experiment register](docs/experiments/README.md) and in the "Best scores" row of the [Track B log](docs/tracks/B-graphrag/log.md#current-state). The baseline to reproduce is E17: 28/31 on the prototype's questions with Qwen3-8B.
- **PyMuPDF is AGPL** and must stay out of anything deployed; use `pypdfium2`.
- **Diagrams:** the specification's are Mermaid in the text, exported with mermaid-cli 11.17.0 ([how](docs/diagrams/README.md)); the stint report's are drawn by `scripts/stint_figures.py`.
- **Standing rule from the reviews:** what code can read from the question or the reports outranks what the model says. Every fault the real model showed was of that kind (B-F72, B-F74, B-F76).
