# CLAUDE.md: start here

This file briefs any Claude session on any machine. Read it first, then the files it points to. The repository is the project's memory: if something is not written in it, it did not happen.

## The project in five lines

- A VPI capstone: a **GraphRAG application for drilling reports**, covering end-of-well reports (EOWR) and daily drilling reports (DDR).
- It uses **existing open-source GraphRAG code** as libraries and references; no base is adopted wholesale (D-50). The design is a **coordinator in front of four lanes** (passages, well facts, events, reasoning about causes) over one graph with two regions (specification §8.1, §8.5).
- It uses **open-weight models of about 7B or smaller**. 8B models are allowed (Track B log B-D06). Commercial APIs are never used, not even for development.
- **The team has no GPU of its own** (the desktop used up to E31 was borrowed, B-D42, B-D43). Compute is **rented, on public data only** (D-68, B-D44): a cloud GPU by the hour with our own model copy for measurements, OpenRouter for the demo and quick checks. Not the school's machines: anh Tuấn advised they are slow and awkward. No budget is approved yet ([resource plan](docs/reports/RESOURCE_REQUEST_2026-11-24.md)).
- Advisors: Dr. Le Duy Dung, and MSc. Nguyen Anh Tuan ("anh Tuấn"), who supervises the work. His 28 October 2026 direction is in [docs/requirements/supervisor-meeting-2026-10-28.md](docs/requirements/supervisor-meeting-2026-10-28.md); the [9 November meeting](docs/requirements/supervisor-meeting-2026-11-09.md) added a coordinator for routing, a simple UI early, a reasoning question type and short reporting (D-58 to D-63). Tri's design choices of 24 November turn that into the second build (D-64 to D-67). It is a capstone, not research: prefer what works, start small, keep domain depth thin.

## Sources of truth, in order

1. [docs/PROJECT_DESIGN.md](docs/PROJECT_DESIGN.md), the specification (version 3.5). §4.5 covers the first build in three tracks (closed); **§4.6 the second build, §8.1 the coordinator and lanes, §8.5 the graph's nodes and relationships, §8.6 the reasoning lane**; §13.1 is the decision register (D-01 to D-67). Chunk and table IDs follow §5.11 as Track A's K1 version 1 writes them, for example `f62efbee00767a3e7:s6:c0` (D-54); `graphrag` also reads version 0's `<doc_id>#c0005`.
2. [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md), the plan (version 3.2). M1 is closed; **M2 is the second build, and §7 is the task list by role**.
3. Track records in [docs/tracks/](docs/tracks/README.md), with dated findings and decisions.
4. Experiment records in [docs/experiments/](docs/experiments/README.md), one record per measurement.

## The team split (from 5 November 2026; redone every one to two weeks)

| Track | Owner | Does |
|---|---|---|
| A. Ingestion and tables | Khai | Docling compared with document VLMs, multi-page tables, key-value forms, chunking; publishes K1 |
| **B. GraphRAG engine and models** | **Tri, the user of these sessions** | Base pipeline, LLM, embeddings, thin K2, cited answers, cost per page; publishes K2, K4 |
| C. Storage, IDs and the end-to-end run | Hung | ID scheme and schemas, MinIO, PostgreSQL, vector store and Neo4j, loader, runner, viewer |

The first build's tracks are closed (24 November). For the second build the roles are agreed (24 November, Q14): Khai data, Hung backend and stores (Tri does part of it for now, B-D39), Tri the engine and the frontend (the React UI). K1 to K5 stay the interfaces (specification §4.5). The expert group will supply the evaluation question set. Until then the development checks are the prototype's 31 questions and the simulated sets in `graphrag/gold/` (B-D22), which no expert has reviewed and which must never be reported as expert validation.

## Standing rules from the user

- **Log everything the same day.** Every finding (B-F), decision (B-D), design choice (B-C) and experiment (E14 onward) goes into [docs/tracks/B-graphrag/log.md](docs/tracks/B-graphrag/log.md) and, for measurements, into a `docs/experiments/E<n>-*.md` record with a row in the register. Update the log's "Current state" table. Project-level decisions also go into specification §13.1.
- **Start small; efficiency is a headline metric.** Every run reports LLM calls, tokens, seconds and cost per page and per question, next to quality.
- **Reuse before writing.** Look only at ready-made GitHub solutions close to the supervisor's description, then improve them. Any licence is fine with proper credit: keep the copyright notice and add a `NOTICE` file next to copied code.
- **No ontology work for now:** anh Tuấn's direction is GraphRAG (B-D25, D-52). Keep K2 thin. The two ontology papers he sent came before this direction and are background only.
- **Ignore `explorations/kg-builder/`.** It is a teammate's separate exploration; do not build on it or recommend it.
- **Commits are authored as the user, with no `Co-Authored-By: Claude` or other AI attribution.** Push to `main`. Others push too, so run `git pull --rebase` before pushing.
- When the direction changes, remove superseded text instead of keeping both, and record what was removed.
- Write documentation in plain English, with short tables and lists. Vietnamese reports keep technical terms in English.

## Track B: where things stand (24 November 2026)

Read [docs/tracks/B-graphrag/log.md](docs/tracks/B-graphrag/log.md) first; its top table is the current state.

- **Now: the second build is coded in all three tracks and runs end to end on a laptop with a stand-in model (24 November, log B-D41, B-C50 to B-C57): the coordinator and four lanes, the engine and backend on the stores, the runner, the Docker deployment with a password gate, the frontend. Nothing is measured with a real model yet.** One connected application: a FastAPI backend and a React frontend on the shared stores, with `graphrag` as the engine library (D-65). Before changing it, read specification §4.6, §7.5, §8.1, §8.5 and §8.6, then the plan's §7. Reserved experiment numbers: E32 answers on K1 version 1, E33 the coordinator on the 221 pooled questions, E34 the reasoning probe.

- **Survey:** [docs/tracks/B-graphrag/survey.md](docs/tracks/B-graphrag/survey.md). neo4j-graphrag-python (E16, E20) and LightRAG (E19, with K2 in E21) have been run; no base is adopted wholesale (B-D21). **What runs today ([specification §8.4](docs/PROJECT_DESIGN.md#84-what-the-first-build-runs-today)): an event graph answers questions over time on daily reports (B-D26), and retrieval routed by well and date answers the rest (B-D23). The per-well fact graph is part of the design and of the end-of-well answer path (B-D29, which reverses B-D24). Plain RAG is the baseline the graphs are measured against, not the system. On 9 November the supervisor accepted the lanes as a concept and asked for a coordinator; he has not said whether users ask questions over time.** Learn from neo4j-labs/llm-graph-builder (a finished application, Apache-2.0), RAGFlow, fast-graphrag, Youtu-GraphRAG and MiniRAG.
- **Code:** [graphrag/](graphrag/README.md).

  | Module | Contents |
  |---|---|
  | `client.py` | One OpenAI-compatible client with JSON-schema output, embeddings, a request cache, a cost ledger and the private-data guard |
  | `retrieval.py` | BM25, dense and fusion retrieval; `WellRouter` keeps only documents that name the asked-about well; `DateRouter` keeps only the pages of the date asked about |
  | `scoring.py` | The prototype's answer rules, plus date and number normalization |
  | `citations.py` | Citations checked against the retrieved chunks in code |
  | `baseline.py` | Command line for retrieval and answer runs (`--multi-well-retriever`, `--fact-sheet`, `--strict-facts`, `--withhold-unsupported`) |
  | `neo4j_kg.py` | neo4j-graphrag-python with the ontology file as its schema (runs in `.venv-graphrag`) |
  | `lightrag_run.py` | LightRAG 1.5.7 on our chunks, client and answer harness (runs in `.venv-lightrag`) |
  | `ontology.py` | K2: glossary generated from the reports' tables; rendering as extractor guidance |
  | `validate.py` | Checks extracted facts before they reach an answer (value in chunk, one well, no zeros, no contradictions; `strict` also checks their context) |
  | `tables.py` | Facts from table rows by K2's `table_mappings`, with no model call |
  | `table_eval.py` | Scores table facts on unseen reports against independent gold, raw and after validation (E29) |
  | `k4.py` | K4 answer records (`schemas/k4_answer_record.schema.json`) from any answer run |
  | `events.py` | Event graph from operations tables, with no model call: the model plans, code runs the plan (E28) |
  | `lanes.py` | The four lanes behind one shape: `passages`, `well_facts`, `events`, `reasoning`, each returning `Evidence` (B-C37, B-C51). `Engine.source` says files or stores |
  | `coordinator.py` | One framing call, lanes chosen in code, fallback, exact mode, pooled runs over sets or question files (B-C38; built, not yet measured: E33) |
  | `reasoning.py` | The reasoning lane for questions about causes (spec §8.6): finds the problem in the event graph, gathers around it in code, a two-part cited answer, scoring of the probe (B-C51; not yet measured: E34) |
  | `stores.py` | The engine built from PostgreSQL and Neo4j instead of files: `engine_from_stores` (B-C50) |
  | `factgraph.py` | The fact graph as nodes and relationships for Track C's Neo4j loader (B-C40) |
  | `oracle.py` | Answers with retrieval bypassed, to separate parsing, retrieval and model failures (E24; a diagnostic, it reads the gold data) |
  | `ui.py`, `ui.html` | Local UI (D-60): replays recorded runs with citations, events and side-by-side comparison, and answers new questions when llama.cpp runs. `python -m graphrag.ui`, then http://127.0.0.1:8765 |

  Endpoints are in `configs/graphrag/endpoints.json`; Neo4j with APOC in `configs/graphrag/docker-compose.yml`. Tests: `python -m unittest discover -s tests -p "test_graphrag*.py"`.
- **Results so far** (up to E22: AK-3 EOWR and the prototype's 31 questions, E10 prototype 23/31; later rows name their questions):

  | Run | Setup | Correct |
  |---|---|---:|
  | [E14](docs/experiments/E14-plain-rag-baseline.md) | BM25, top 5, Qwen3-4B, laptop CPU | 21/31 |
  | [E15](docs/experiments/E15-baseline-checks-in-code.md) | Same, citations and values checked in code, desktop GPU | 22/31 |
  | [E16](docs/experiments/E16-neo4j-graphrag-python.md) | neo4j-graphrag facts added under the passages (Qwen3-4B / Qwen3-8B) | 21/31 / 28/31 |
  | [E17](docs/experiments/E17-model-sweep.md) | BM25, top 5, **Qwen3-8B** (thinking off) | **28/31** |
  | E17 | Three reports, fusion retrieval, Qwen3-8B | 26/31 |
  | [E18](docs/experiments/E18-well-routing.md) | Three reports, **BM25 routed by well**, Qwen3-8B (the baseline, D-50) | **28/31** |
  | [E19](docs/experiments/E19-lightrag.md) | LightRAG `mix` with Qwen3-8B, one report or three | 25/31 |
  | [E21](docs/experiments/E21-lightrag-k2.md) | LightRAG with K2 injected, `mix` | 26/31 |
  | [E20](docs/experiments/E20-well-fact-sheet.md) | Baseline plus extracted per-well facts (neo4j-graphrag, Qwen3-4B), raw / **validated in code** | 21/31 / 28/31 |
  | [E22](docs/experiments/E22-table-facts.md) | Baseline plus validated facts from **K2 table mappings and LLM extraction** (the fact graph's sheet; `--sheet-properties 3` keeps it at 1,793 prompt tokens per question) | **30/31** |

  | [E23](docs/experiments/E23-simulated-set.md) | **Simulated 40 questions, not expert-reviewed**: plain RAG / fact sheet, top 5; then per-well fusion, evidence first | 29/40 / 29/40; 31/40 / 30/40 (5 wrong values each) |

  | [E24](docs/experiments/E24-ak3-daily-reports.md) | **AK-3 daily reports, 30 simulated questions, not expert-reviewed**: plain RAG / fusion, evidence first / right page given, evidence first (diagnostic) | 5/30 / 9/30 / 19/30 |

  | [E25](docs/experiments/E25-table-mappings-unseen-report.md) | K2 table mappings on unseen 78-32, as written / after two fixes | 3 facts, 2 with the wrong size, survey missed / 23 correct |
  | [E26](docs/experiments/E26-routing-and-strict-facts.md) | **36 new simulated questions**: top 5 / routed by number of wells (**baseline**) / fact sheet, routed, strict | 20/36 / **23/36** / 23/36 |
  | [E27](docs/experiments/E27-date-filter-and-coverage.md) | **26 new daily-report questions**: no filter / **date filter** / top 10, evidence first | 7/26 / **14/26** (2 wrong) / 17/26 (6 wrong) |

  | [E28](docs/experiments/E28-event-graph.md) | **Daily reports, totals over time, chosen to suit the graph**: **event graph** / best plain RAG. Frozen 35; then new 23 | **22/35** / 5/35; **19/23** / 4/23 |
  | [E29](docs/experiments/E29-table-mappings-across-reports.md) | K2 table mappings on held-out reports from other authors: casing as written / after fixes and validation | 4/16 / **13/16**, no wrong fact; surveys unreliable |
  | [E31](docs/experiments/E31-event-graph-on-k1.md) | Event graph rebuilt from **Track A's K1 version 1** (report dates from K1), no model call | 161 / 161 events identical to E28; plans replay 35/35 and 23/23 |

  The shape of the graph has to match the questions (B-F47). On new lookup questions the per-well fact graph ties plain RAG so far (B-F30), and it stays in the design (B-D29); a graph of events wins on totals over time (B-D26). Scrambled form headers remain for Track A (B-F36).

  On the 9-question cross-report probe (`graphrag/gold/cross_report_probe.json`, not an evaluation set), plain RAG and LightRAG each reach 3/9, on different questions; with validated per-well facts it scores 2 to 5 of 9 depending on the sheet, which 9 questions cannot tell from noise (B-F29). Use `--answer-format evidence_first` there: a status-first schema makes the model abstain (B-F22).

  - neo4j-graphrag with Qwen3-4B extracts 0.85 of the 41 gold facts, but 28% of its keyed facts are wrong, and its facts do not improve answers. One prompt sentence can move recall between 0.37 and 0.85 (B-F20).
  - Qwen2.5-7B and Llama-3.1-8B abstain on nearly everything under our prompt (8/31, 10/31) and are dropped.
  - **Run one request at a time for measurements:** parallel requests to llama.cpp make results non-repeatable (B-F19). Record the server settings with each run; on a hosted endpoint record the provider and model ID, and expect seconds per question to say little.
  - A supported citation does not prove a right answer (B-F18, which corrects B-F17).

### Next steps

The task list is [plan §7](docs/DEVELOPMENT_PLAN.md#7-what-to-do-now). Track B's part, in order (B-D36 to B-D38):

1. Message anh Tuấn: no contact is recorded since 9 November (plan task A1). The desktop is borrowed: it hosts nothing for the team, neither the stores nor the demo's model (B-D42, Track C log C-D07); Hung to say whether his machine hosts the stores for now.
2. **Get compute to measure with** (B-D43, B-D44, D-68): send the [resource plan](docs/reports/RESOURCE_REQUEST_2026-11-24.md) (5 million VND for the next three months of rented GPU hours, a small server and hosted calls; the email goes to anh Trường, who handles the capstone funding, as Dr. Le Duy Dung, the team's advisor, said). With a rented GPU, set the machine up as below and run as before; with only an OpenRouter key, rerun the baselines there first. Then E32: answers on K1 version 1 ([commands](docs/tracks/B-graphrag/next-runs.md)) on the demo release `ak3-demo-v1` (`python scripts/build_k1_demo_release.py`, B-C55); then the same from the stores (`BACKEND_SOURCE=stores`, B-C50).
3. ~~The lane interface and model roles~~: done (B-C37, B-C41).
4. ~~The fact graph as nodes and relationships~~: exported (B-C40) and loaded in Neo4j. Open: its facts cite K1 version 0 chunk IDs, which the stores do not hold (B-F63), and B-F60's two doubts.
5. The coordinator is built (B-C38, B-C39). **Run E33** (`python -m graphrag.coordinator answer --questions prototype simulated heldout ak3_daily ak3_daily_heldout ak3_events ak3_events_heldout --name E33_coordinator_pool`; on a hosted model set `GRAPHRAG_ROLES=deploy/models/roles.openrouter.json` and add `--no-embeddings`) and adopt it only if it matches the hand-routed scores from the same endpoint.
6. The reasoning lane and its ten frozen questions are built (B-C51, B-C52). **Run E34:** `python -m graphrag.coordinator answer --questions graphrag/gold/ak3_reasoning_probe_v0.json --name E34_reasoning_probe`.
7. ~~The React frontend~~: built in [frontend/](frontend/README.md), for non-developers: always light, plain words, a guide, explanations on hover, answers about causes in parts (B-C45, B-C47, B-C57; `npm run dev:examples` needs no server; `npm test`; `npm run types` after a contract change). **First run against the API with a real model is still to do.**

**Backend, stores and deployment (B-D39, B-D41):** built with Hung's clearance, beside his own work of the same day; the Track C log says who built what. The API is in [backend/](backend/README.md) (`python -m uvicorn backend.app:app`; `BACKEND_SOURCE=stores` with `BACKEND_DSN` and `NEO4J_*` reads the stores; tests `tests/test_backend*.py`). Scripts in [platform/](platform/README.md): `run_release.py <release>` loads a K1 release into PostgreSQL and Neo4j, each step checked. The stores need `platform/.env` with the two passwords (`platform-dev` on a laptop whose stores already exist). The whole application: `docker compose -f platform/docker-compose.yml --profile app --profile demo up -d --build`, where `demo` adds a stub model that is not a model; the runbooks are [deploy/README.md](deploy/README.md) (application) and [docs/tracks/C-storage/server-runbook.md](docs/tracks/C-storage/server-runbook.md) (server and stores). Say in the group chat what is being built before building in a teammate's track (B-F65).

**What was asked of teammates (24 November):** [note for Khai](docs/tracks/A-ingestion/note-from-track-B-2026-11-24.md) (the demo K1 release first) and [note for Hung](docs/tracks/C-storage/note-from-track-B-2026-11-24.md) (shared hosting first). **What the stint accomplished:** [stint report](docs/reports/stints/STINT_REPORT_2026-11-27.md), a **draft updated until the stint ends on 27 November**. Stint reports live in `docs/reports/stints/`, one per stint; after changing one, run `python scripts/stint_figures.py` and `python scripts/render_stint_report.py <report.md>` to redraw its diagrams and PDF. In a stint report, say what each person built (the backend service is Tri's and Hung's together) and do not comment on when in the stint the work happened.

Still waiting on others: the expert questions and the purpose of use (Q2, Q13); a budget for rented compute and a server (D-68, C-D06); Khai's review of the demo release and of the Track A log draft; Hung's review of the loaders, the runner and the deployment files.

History of this list (B-D15):

1. The supervisor asked us to wait for the expert questions, so simulated sets stand in (B-D22). E23 to E31 are done; the stint's status is in Tri's [update](docs/reports/stints/STINT_UPDATE_2026-11-05.md) and the [project report](docs/reports/PROJECT_REPORT_2026-11-09.md) of 9 November.
2. ~~Filter retrieval by well~~: done in E18 (B-D16). ~~LightRAG~~: E19, not adopted. ~~K2 version 1~~: `configs/ontology/k2_eowr_v1.json` (B-D17).
3. ~~LightRAG with K2~~: E21, 26/31; adds document and project structure (B-D21).
4. ~~Validate extracted facts~~: `graphrag/validate.py` (B-C15). ~~Table rows mapped in code~~: `graphrag/tables.py`, E22 (B-D20). Mappings checked on unseen reports (E25, E29): casing holds up, surveys do not, and a different author's modern report is untested (B-F54). Fact-graph work resumes (B-D29 reverses B-D24's stop).
5. ~~Choose the vector store~~: pgvector inside PostgreSQL, Hung's proposal (D-56). K1 version 1 is the agreed chunk-package interface, Khai's proposal (D-57).

## Setting up a machine for Track B runs

Every run up to E31 was made on a borrowed desktop (RTX 4080 SUPER 16 GB, Ryzen 9 9900X, 32 GB, Windows), fully local on the GPU with llama.cpp (B-F16). **That machine is no longer the team's to plan on** (B-D42, B-D43): new runs use a rented cloud GPU, set up by the steps below (on Linux, take the matching llama.cpp build), or OpenRouter on public data (step 4). The laptop is too slow for the LLM.

1. `git pull`. Create `.venv` with Python 3.12, then `pip install -r requirements.lock.txt` and `pip install -e .`. `graphrag/` needs only `httpx` and `numpy`, which the lock file includes.
2. For neo4j-graphrag runs only: a second environment `.venv-graphrag` from `requirements-graphrag.lock.txt` (it needs a newer `pypdf` than the main lock allows, B-C09), and Docker Desktop for Neo4j: `docker compose -f configs/graphrag/docker-compose.yml up -d`. Stop the prototype's Neo4j first; they share ports. On Windows the `docker` CLI may not be on PATH; it is under `%LOCALAPPDATA%/Programs/DockerDesktop/resources/bin`.
   For LightRAG runs: a third environment `.venv-lightrag` from `requirements-lightrag.lock.txt`.
3. **llama.cpp:** the Windows CUDA 12.4 build of release b12015 plus its `cudart` zip, unpacked into ignored `data/interim/llama.cpp/`. GGUFs go into ignored `data/interim/models/`:

   | Model | Hugging Face repository and file |
   |---|---|
   | Answer LLM (baseline) | `Qwen/Qwen3-8B-GGUF`, file `Qwen3-8B-Q4_K_M.gguf`; serve with thinking off |
   | Smaller LLM | `unsloth/Qwen3-4B-Instruct-2507-GGUF`, file `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` |
   | Embeddings | `Qwen/Qwen3-Embedding-0.6B-GGUF`, file `Qwen3-Embedding-0.6B-Q8_0.gguf` |
   | Dropped (E17) | `bartowski/Qwen2.5-7B-Instruct-GGUF`, `bartowski/Meta-Llama-3.1-8B-Instruct-GGUF` (Q4_K_M) |

   Server commands are in [graphrag/README.md](graphrag/README.md): `-c 32768 -np 4 -ngl 99` up to E18; **`-np 1` from E19 on** (LightRAG needs a 32k slot; the baseline gives the same 28/31 either way). Qwen3-4B for extraction can run on port 8082 (endpoint `local-llama-2`). On a laptop with an integrated GPU, use `--device none -ngl 0` instead.
   Tools used in this stint, installed with `winget --source winget`: Poppler (`oschwartz10612.Poppler`, reading PDF pages) and Node.js (`OpenJS.NodeJS.LTS`, rendering Mermaid).
4. **Hosted, for the demo and for checks when no rented GPU is running:** set `OPENROUTER_API_KEY` and use `--endpoint openrouter --model <openrouter model id>` for `graphrag.baseline`, or `GRAPHRAG_ROLES=deploy/models/roles.openrouter.json` for the coordinator and the backend. Public data only; the client refuses private data on hosted endpoints. A hosted score is not comparable with the recorded local ones (full precision against a 4-bit copy): rerun the baseline on the same endpoint first, and record the provider with the run.
5. Check the setup by reproducing E17's baseline:

   ```
   python -m graphrag.baseline retrieval --pool ak3 --retrievers bm25 --name check
   python -m graphrag.baseline answer --pool ak3 --retriever bm25 --k 5 --endpoint local-llama --model qwen3-8b --name check_answers
   ```

   BM25 hit@5 should be 1.00 and the answers about 28/31. Delete the `check*` result files afterwards.
## Useful facts

- Data: `data/processed/gdr_chunks_full.jsonl` holds the K1 version 0 chunks: AK-3 EOWR (`gdr882_ak3_eowr`, 60 chunks) plus two other EOWRs (372 chunks in total). Gold data: `prototype/gold/questions.json` (31 questions) and `ak3_facts.json` (41 facts, chunk IDs like `c0002`).
- Track A's K1 version 1 package is shared as a zip, never committed (B-F56): unzip it into ignored `data/interim/k1/` or a folder inside it (or set `GRAPHRAG_K1_CHUNKS`); `python -m graphrag.events build --k1` builds the event graph from it (E31) and use `--pool k1_ak3` or `--pool k1_daily`.
- AK-3 daily reports: `--pool ak3_daily`, 898 chunks in ignored `data/corpora/ak3_appendices/`; [next-runs](docs/tracks/B-graphrag/next-runs.md) has the regeneration steps. Simulated question sets in `graphrag/gold/`: `simulated_expert_v0`, `simulated_heldout_v0`, `ak3_daily_v0`, `ak3_daily_heldout_v0`, `ak3_events_v0`, `ak3_events_heldout_v0`. They are frozen: changes go into a new version.
- The prototype (`prototype/`) is the baseline to beat (E10). Do not change it.
- Diagrams: Mermaid source sits in the documents. SVGs are regenerated with mermaid-cli 11.17.0 (see `docs/diagrams/README.md`).
- Tests: `python -m unittest discover -s tests`. The line-ending test needs LF files. Tests that need PostgreSQL or Neo4j skip when the stores are not running. On a machine short of memory set `OPENBLAS_NUM_THREADS=1`.
