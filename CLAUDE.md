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

## Track B: where things stand (31 October 2026)

Read [docs/tracks/B-graphrag/log.md](docs/tracks/B-graphrag/log.md) first; its top table is the current state.

- **Survey:** [docs/tracks/B-graphrag/survey.md](docs/tracks/B-graphrag/survey.md). Run **neo4j-graphrag-python** first: its schema is the ontology injection, it can prune types the schema does not define, and it links chunks to their documents. Then run **LightRAG**, whose own docs want a ~30B extraction model, so a ~7B run is the real test. Learn from neo4j-labs/llm-graph-builder (a finished application, Apache-2.0), RAGFlow, fast-graphrag, Youtu-GraphRAG and MiniRAG.
- **Code:** [graphrag/](graphrag/README.md).

  | Module | Contents |
  |---|---|
  | `client.py` | One OpenAI-compatible client with JSON-schema output, embeddings, a request cache, a cost ledger and the private-data guard |
  | `retrieval.py` | BM25, dense and fusion retrieval |
  | `scoring.py` | The prototype's answer rules |
  | `baseline.py` | Command line |

  Endpoints are in `configs/graphrag/endpoints.json`. Tests: `python -m unittest discover -s tests -p "test_graphrag.py"`.
- **E14** ([record](docs/experiments/E14-plain-rag-baseline.md)), plain RAG on the AK-3 EOWR (60 chunks):
  - BM25 retrieval found every gold fact in the top 5, beating Qwen3-Embedding-0.6B (hit@5 0.78).
  - BM25, top 5 and Qwen3-4B-Instruct-2507 answered **21/31**. The prototype, E10, answered 23/31.
  - All 9 questions that should get no answer were refused, and there were 0 invalid JSON outputs.
  - The misses come from the 4B model reading tables and abstaining. Model-written citations are unreliable, so citations are checked in code (B-C07).

### Next steps (B-D10)

1. Strengthen the baseline:
   - check citations in code (each cited chunk must be among the retrieved ones, and the quote must appear in it);
   - normalize dates and numbers in code;
   - try *k* = 3 to cut prompt tokens.

   Rerun as E15.
2. Run **neo4j-graphrag-python**:
   - same 60 chunks, same 31 questions, same model;
   - `oil_wells.json` turned into its schema, with undefined types pruned;
   - one extraction pass per chunk, JSON-schema output, cached.

   Compare with E14 on correctness, citations, tokens per page and time. Record as E16.
3. Then LightRAG under the same conditions.
4. Thin ontology slice K2 version 1, from the report's headings, table columns and abbreviation table (D-49).
5. Choose the vector store with Khai (Track C) once the base is chosen.

## Setting up a machine for Track B runs

The old laptop (i5-1340P, CPU only, shared with other work) proved too slow, and its model files were deleted. Run on a bigger machine or on OpenRouter.

1. `git pull`. Create `.venv` with Python 3.12, then `pip install -r requirements.lock.txt` and `pip install -e .`. `graphrag/` needs only `httpx` and `numpy`, which the lock file includes.
2. **Hosted, preferred for comparisons:** set `OPENROUTER_API_KEY` and use `--endpoint openrouter --model <openrouter model id>`. Check which candidate models OpenRouter serves:

   | Purpose | Candidates |
   |---|---|
   | LLM | Qwen3-4B-Instruct-2507, Qwen2.5-7B-Instruct, Qwen3-8B, Llama-3.1-8B-Instruct |
   | Embeddings | Qwen3-Embedding-0.6B, bge-m3 |

   Public data only. The client refuses private data on hosted endpoints.
3. **Local, with llama.cpp (`llama-server`):** download the GGUFs into ignored `data/interim/models/`:

   | Model | Hugging Face repository and file |
   |---|---|
   | LLM | `unsloth/Qwen3-4B-Instruct-2507-GGUF`, file `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` |
   | Embeddings | `Qwen/Qwen3-Embedding-0.6B-GGUF`, file `Qwen3-Embedding-0.6B-Q8_0.gguf` |
   | Embeddings, optional | `ggml-org/bge-m3-Q8_0-GGUF` |

   Server commands are in [graphrag/README.md](graphrag/README.md). On a machine with an Nvidia GPU, drop `--device none -ngl 0`; on an integrated GPU, keep them. PyTorch embeddings were unusably slow on the old laptop, which is why all models go through endpoints (B-C06).
4. Reproduce E14 to check the setup:

   ```
   python -m graphrag.baseline retrieval --pool ak3 --retrievers bm25 --name check
   python -m graphrag.baseline answer --pool ak3 --retriever bm25 --k 5 --endpoint <endpoint> --model <model> --name check_answers
   ```

   BM25 hit@5 should be 1.00. Delete the `check*` result files afterwards.

## Useful facts

- Data: `data/processed/gdr_chunks_full.jsonl` holds the K1 version 0 chunks: AK-3 EOWR (`gdr882_ak3_eowr`, 60 chunks) plus two other EOWRs (372 chunks in total). Gold data: `prototype/gold/questions.json` (31 questions) and `ak3_facts.json` (41 facts, chunk IDs like `c0002`).
- The prototype (`prototype/`) is the baseline to beat (E10). Do not change it.
- Diagrams: Mermaid source sits in the documents. SVGs are regenerated with mermaid-cli 11.17.0 (see `docs/diagrams/README.md`).
- Tests: `python -m unittest discover -s tests`. The line-ending test needs LF files.
