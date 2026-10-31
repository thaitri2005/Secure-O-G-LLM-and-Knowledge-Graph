# CLAUDE.md: start here

This file briefs any Claude session on any machine. Read it first, then the files it points to. The repository is the project's memory: if something is not written in it, it did not happen.

## The project in five lines

- A VPI capstone: a **GraphRAG application for drilling reports**, covering end-of-well reports (EOWR) and daily drilling reports (DDR).
- It is built on an **existing open-source GraphRAG pipeline**, which we take over and improve.
- It uses **open-weight models of about 7B or smaller**. 8B models are allowed (Track B log B-D06). Commercial APIs are never used, not even for development.
- Development runs on **OpenRouter, on public data only**. Large runs use the school GPUs.
- Supervisor: MSc. Nguyen Anh Tuan ("anh Tuấn"). His 28 October 2026 direction is in [docs/requirements/supervisor-meeting-2026-10-28.md](docs/requirements/supervisor-meeting-2026-10-28.md). It is a capstone, not research: prefer what works, start small, keep domain depth thin.

## Sources of truth, in order

1. [docs/PROJECT_DESIGN.md](docs/PROJECT_DESIGN.md), the specification. §4.5 covers the first build in three tracks; §13.1 is the decision register (D-01 to D-49).
2. [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md), the plan. M1 is the first build, and each track's section lives there.
3. Track logs in `docs/tracks/`, with dated findings and decisions.
4. Experiment records in [docs/experiments/](docs/experiments/README.md), one record per measurement.

## The team split (first stint, from 30 October 2026; redone every one to two weeks)

| Track | Owner | Does |
|---|---|---|
| A. Ingestion and tables | Hung | Docling compared with document VLMs, multi-page tables, key-value forms, chunking; publishes K1 |
| **B. GraphRAG engine and models** | **Tri, the user of these sessions** | Base pipeline, LLM, embeddings, thin ontology, cited answers, cost per page; publishes K2, K4 |
| C. Storage, IDs and the end-to-end run | Khai | ID scheme and schemas, MinIO, PostgreSQL, vector store and Neo4j, loader, runner, viewer |

The tracks meet only through versioned files K1 to K5 (specification §4.5). The team writes no question set of its own: the expert group will supply one, and until then the prototype's 31 questions are the development check.

## Standing rules from the user

- **Log everything the same day.** Every finding (B-F), decision (B-D), design choice (B-C) and experiment (E14 onward) goes into [docs/tracks/B-graphrag/log.md](docs/tracks/B-graphrag/log.md) and, for measurements, into a `docs/experiments/E<n>-*.md` record with a row in the register. Update the log's "Current state" table. Project-level decisions also go into specification §13.1.
- **Start small; efficiency is a headline metric.** Every run reports LLM calls, tokens, seconds and cost per page and per question, next to quality.
- **Reuse before writing.** Look only at ready-made GitHub solutions close to the supervisor's description, then improve them. Any licence is fine with proper credit: keep the copyright notice and add a `NOTICE` file next to copied code.
- **Ignore `explorations/kg-builder/`.** It is a teammate's separate exploration; do not build on it or recommend it.
- **Commits are authored as the user, with no `Co-Authored-By: Claude` or other AI attribution.** Push to `main`. Others push too, so run `git pull --rebase` before pushing.
- When the direction changes, remove superseded text instead of keeping both, and record what was removed.
- Write documentation in plain English, with short tables and lists. Vietnamese reports keep technical terms in English.

## Track B: where things stand (1 November 2026)

Read [docs/tracks/B-graphrag/log.md](docs/tracks/B-graphrag/log.md) first; its top table is the current state.

- **Survey:** [docs/tracks/B-graphrag/survey.md](docs/tracks/B-graphrag/survey.md). neo4j-graphrag-python (E16, E20) and LightRAG (E19) have been run and not adopted; **LightRAG with the K2 ontology** (E21) is next. Learn from neo4j-labs/llm-graph-builder (a finished application, Apache-2.0), RAGFlow, fast-graphrag, Youtu-GraphRAG and MiniRAG.
- **Code:** [graphrag/](graphrag/README.md).

  | Module | Contents |
  |---|---|
  | `client.py` | One OpenAI-compatible client with JSON-schema output, embeddings, a request cache, a cost ledger and the private-data guard |
  | `retrieval.py` | BM25, dense and fusion retrieval; `WellRouter` keeps only documents that name the asked-about well |
  | `scoring.py` | The prototype's answer rules, plus date and number normalization |
  | `citations.py` | Citations checked against the retrieved chunks in code |
  | `baseline.py` | Command line for retrieval and answer runs (`--facts`, `--withhold-unsupported`) |
  | `neo4j_kg.py` | neo4j-graphrag-python with the ontology file as its schema (runs in `.venv-graphrag`) |
  | `lightrag_run.py` | LightRAG 1.5.7 on our chunks, client and answer harness (runs in `.venv-lightrag`) |
  | `ontology.py` | K2: glossary generated from the reports' tables; rendering as extractor guidance |
  | `validate.py` | Checks extracted facts before they reach an answer (value in chunk, one well, no zeros, no contradictions) |
  | `tables.py` | Facts from table rows by K2's `table_mappings`, with no model call |

  Endpoints are in `configs/graphrag/endpoints.json`; Neo4j with APOC in `configs/graphrag/docker-compose.yml`. Tests: `python -m unittest discover -s tests -p "test_graphrag.py"`.
- **Results so far** (AK-3 EOWR, 60 chunks, the prototype's 31 questions; E10 prototype: 23/31):

  | Run | Setup | Correct |
  |---|---|---:|
  | [E14](docs/experiments/E14-plain-rag-baseline.md) | BM25, top 5, Qwen3-4B, laptop CPU | 21/31 |
  | [E15](docs/experiments/E15-baseline-checks-in-code.md) | Same, citations and values checked in code, desktop GPU | 22/31 |
  | [E16](docs/experiments/E16-neo4j-graphrag-python.md) | neo4j-graphrag facts added under the passages (Qwen3-4B / Qwen3-8B) | 21/31 / 28/31 |
  | [E17](docs/experiments/E17-model-sweep.md) | BM25, top 5, **Qwen3-8B** (thinking off) | **28/31** |
  | E17 | Three reports, fusion retrieval, Qwen3-8B | 26/31 |
| [E18](docs/experiments/E18-well-routing.md) | Three reports, **BM25 routed by well**, Qwen3-8B (the baseline, D-50) | **28/31** |
  | [E19](docs/experiments/E19-lightrag.md) | LightRAG `mix` with Qwen3-8B, one report or three | 25/31 |
  | [E20](docs/experiments/E20-well-fact-sheet.md) | Baseline plus extracted per-well facts (neo4j-graphrag, Qwen3-4B), raw / **validated in code** | 21/31 / 28/31 |
  | [E22](docs/experiments/E22-table-facts.md) | Baseline plus validated facts from **K2 table mappings and LLM extraction** (the working design) | **30/31** |

  On the 9-question cross-report probe (`graphrag/gold/cross_report_probe.json`, not an evaluation set), plain RAG and LightRAG each reach 3/9, on different questions; the baseline plus **validated** per-well facts reaches **5/9** (B-D19, the working design). Use `--answer-format evidence_first` there: a status-first schema makes the model abstain (B-F22).

  - neo4j-graphrag with Qwen3-4B extracts 0.85 of the 41 gold facts, but 28% of its keyed facts are wrong, and its facts do not improve answers. One prompt sentence can move recall between 0.37 and 0.85 (B-F20).
  - Qwen2.5-7B and Llama-3.1-8B abstain on nearly everything under our prompt (8/31, 10/31) and are dropped.
  - **Run one request at a time for measurements:** parallel requests to llama.cpp make results non-repeatable (B-F19). Record the server settings with each run.
  - A supported citation does not prove a right answer (B-F18, which corrects B-F17).

### Next steps (B-D15)

1. Ask the supervisor for questions where a graph should help (across wells and reports, counts, comparisons), or for the expert question set. The 31 development questions are mostly single-fact lookups that plain RAG with Qwen3-8B already answers.
2. ~~Filter retrieval by well~~: done in E18 (B-D16). ~~LightRAG~~: E19, not adopted. ~~K2 version 1~~: `configs/ontology/k2_eowr_v1.json` (B-D17).
3. LightRAG with K2 injected as its entity-type guidance (E21).
4. ~~Validate extracted facts~~: `graphrag/validate.py` (B-C15). ~~Table rows mapped in code~~: `graphrag/tables.py`, E22 (B-D20). Next: check the mappings on reports they were not written from, and add people, projects and document counts to the fact graph.
5. Choose the vector store with Khai (Track C) once the base is chosen.

## Setting up a machine for Track B runs

Runs happen on Tri's desktop (RTX 4080 SUPER 16 GB, Ryzen 9 9900X, 32 GB, Windows), fully local on the GPU with llama.cpp (B-F16). The old laptop proved too slow. OpenRouter remains an option for public data.

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
4. **Hosted, optional:** set `OPENROUTER_API_KEY` and use `--endpoint openrouter --model <openrouter model id>`. Public data only; the client refuses private data on hosted endpoints.
5. Check the setup by reproducing E17's baseline:

   ```
   python -m graphrag.baseline retrieval --pool ak3 --retrievers bm25 --name check
   python -m graphrag.baseline answer --pool ak3 --retriever bm25 --k 5 --endpoint local-llama --model qwen3-8b --name check_answers
   ```

   BM25 hit@5 should be 1.00 and the answers about 28/31. Delete the `check*` result files afterwards.
## Useful facts

- Data: `data/processed/gdr_chunks_full.jsonl` holds the K1 version 0 chunks: AK-3 EOWR (`gdr882_ak3_eowr`, 60 chunks) plus two other EOWRs (372 chunks in total). Gold data: `prototype/gold/questions.json` (31 questions) and `ak3_facts.json` (41 facts, chunk IDs like `c0002`).
- The prototype (`prototype/`) is the baseline to beat (E10). Do not change it.
- Diagrams: Mermaid source sits in the documents. SVGs are regenerated with mermaid-cli 11.17.0 (see `docs/diagrams/README.md`).
- Tests: `python -m unittest discover -s tests`. The line-ending test needs LF files.
