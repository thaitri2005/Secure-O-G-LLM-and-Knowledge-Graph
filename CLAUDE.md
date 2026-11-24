# CLAUDE.md: start here

This file briefs any Claude session on any machine. The repository is the project's memory: if something is not written in it, it did not happen.

## The project

- A VPI capstone: a **GraphRAG application for drilling reports**, covering end-of-well reports and daily drilling reports.
- Design: a **coordinator in front of four lanes** (passages, well facts, events, reasoning about causes) over one graph with two regions (specification §8.1, §8.5). Existing open-source GraphRAG code is used as libraries and references; no base is adopted wholesale (D-50).
- Models: **open-weight, about 8B parameters or smaller, run by the team**. Commercial APIs are never used, not even for development.
- Compute: **the team has no GPU or server of its own**. It is rented, on public data only (D-68): a cloud GPU by the hour for measurements, OpenRouter for the demo. Not the school's machines. No budget is approved yet ([resource request](docs/reports/RESOURCE_REQUEST_2026-11-24.md)).
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
| The design | [Specification](docs/PROJECT_DESIGN.md): §4.6 the second build, §7.5 the API, §8.1 coordinator and lanes, §8.5 the graph, §8.6 the reasoning lane, §13.1 decisions (D-01 to D-68) |
| What was found, decided and built, by date | The track logs above. Track B's top table is its current state |
| Every measured result | [Experiment register](docs/experiments/README.md) |
| How the engine's modules fit, and how to run it | [graphrag/README.md](graphrag/README.md) |
| Running the application, the stores, a server | [backend](backend/README.md), [frontend](frontend/README.md), [platform](platform/README.md), [deploy](deploy/README.md) |
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

1. Send the [resource request](docs/reports/RESOURCE_REQUEST_2026-11-24.md) to anh Trường (capstone funding, as Dr. Dung said), and the [stint report](docs/reports/stints/STINT_REPORT_2026-11-27.md) to anh Tuấn. The stint report is a draft until the stint ends on 27 November.
2. Once there is compute, run the three measurements, with [these commands](docs/tracks/B-graphrag/next-runs.md):
   - **E32:** answers on the demo package `ak3-demo-v1`, from files and then from the stores;
   - **E33:** the coordinator on the 221 pooled questions; adopt it only if it matches the hand-routed scores from the same endpoint;
   - **E34:** the reasoning lane on its ten frozen questions.
3. Rebuild the facts on the new chunk IDs once the package holds three reports (B-F63).

## Commands

```powershell
python -m unittest discover -s tests                       # everything; store and PDF tests skip when absent
python -m unittest discover -s tests -p "test_graphrag*.py" # the engine
python -m unittest discover -s tests -p "test_backend*.py"  # the backend
cd frontend; npm test; npm run dev:examples                 # the application on example answers, no server
python platform/run_release.py <release> --skip-vectors     # load a report package into the stores
docker compose -f platform/docker-compose.yml --profile app --profile demo up -d --build   # the whole application, with a stub model
```

- The stores need `platform/.env` with the two passwords (`platform-dev` on a laptop whose stores already exist).
- On a machine short of memory, set `OPENBLAS_NUM_THREADS=1` for the tests.
- `npm run types` in `frontend/` after the API contract changes; `python -m backend.contract` regenerates the contract.

## Setting up a machine with a GPU

Every run up to E31 was made on a borrowed desktop (RTX 4080 SUPER 16 GB, Windows) with llama.cpp. New runs use a rented cloud GPU set up the same way (on Linux, take the matching llama.cpp build), or OpenRouter. The laptop is too slow for the LLM.

1. `git pull`. Create `.venv` with Python 3.12, then `pip install -r requirements.lock.txt` and `pip install -e .`. The engine itself needs only `httpx` and `numpy`.
2. **llama.cpp:** release b12015 (the Windows CUDA 12.4 build plus its `cudart` zip), unpacked into ignored `data/interim/llama.cpp/`. Model files go into ignored `data/interim/models/`:

   | Model | Hugging Face repository and file |
   |---|---|
   | Answer LLM (baseline) | `Qwen/Qwen3-8B-GGUF`, `Qwen3-8B-Q4_K_M.gguf`; serve with thinking off |
   | Smaller LLM | `unsloth/Qwen3-4B-Instruct-2507-GGUF`, `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` |
   | Embeddings | `Qwen/Qwen3-Embedding-0.6B-GGUF`, `Qwen3-Embedding-0.6B-Q8_0.gguf` |

   Server commands are in [graphrag/README.md](graphrag/README.md#running-locally): `-c 32768 -np 1 -ngl 99`.
3. **Check the setup** by reproducing the baseline; BM25 hit@5 should be 1.00 and the answers about 28/31. Delete the `check*` result files afterwards.

   ```
   python -m graphrag.baseline retrieval --pool ak3 --retrievers bm25 --name check
   python -m graphrag.baseline answer --pool ak3 --retriever bm25 --k 5 --endpoint local-llama --model qwen3-8b --name check_answers
   ```
4. **Hosted instead:** set `OPENROUTER_API_KEY`, then `--endpoint openrouter --model <model id>` for `graphrag.baseline`, or `GRAPHRAG_ROLES=deploy/models/roles.openrouter.json` for the coordinator and the backend. Public data only. A hosted score is compared only with a baseline rerun on the same endpoint.
5. Only for the two library comparisons (E16, E19): separate environments `.venv-graphrag` and `.venv-lightrag` from their lock files, and Neo4j from `configs/graphrag/docker-compose.yml`.

## Useful facts

- **Chunk IDs** follow specification §5.11 as K1 version 1 writes them, for example `f62efbee00767a3e7:s6:c0` (D-54). The engine also reads version 0's `<doc_id>#c0005`.
- **Committed data:** `data/processed/gdr_chunks_full.jsonl` holds three end-of-well reports as K1 version 0 chunks (372 chunks; AK-3 is `gdr882_ak3_eowr`). Gold data for the prototype's 31 questions is in `prototype/gold/`.
- **Report packages are never committed** (B-F56). They live in ignored `data/interim/k1/`; set `GRAPHRAG_K1_CHUNKS` when more than one is there. Build the demo package with `python scripts/build_k1_demo_release.py`.
- **Headline results so far**, all on questions written by the team: 28/31 on the prototype's questions with Qwen3-8B (E18, the baseline); 30/31 with checked facts added (E22); 22/35 and 19/23 on totals over time with the event graph, against 5/35 and 4/23 for plain retrieval (E28).
- **PyMuPDF is AGPL** and must stay out of anything deployed; use `pypdfium2`.
- **Diagrams:** the specification's are Mermaid in the text, exported with mermaid-cli 11.17.0 ([how](docs/diagrams/README.md)); the stint report's are drawn by `scripts/stint_figures.py`.
