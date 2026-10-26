# Architecture prototype (test build)

> **This is experiment E4, a test of the target architecture, not the system.** It runs a small version of the specification ([docs/PROJECT_DESIGN.md](../docs/PROJECT_DESIGN.md) §4–§8) on 15 chunks of **one** report (AK-3), to check that the pieces fit together and to measure where errors come from. It has no authentication, no UI, and throwaway credentials. Its numbers are development-set results. Findings and every run are recorded in the [E4 experiment record](../docs/experiments/E4-ak3-architecture-prototype.md).

## What it contains

| Design element | Prototype |
|---|---|
| Local model server (llama.cpp) | Container, CPU, Qwen2.5-3B-Instruct Q4_K_M, JSON-schema-constrained output |
| Extraction with evidence | `kgproto/extract.py`: text chunks whole, tables one row at a time; each claim carries a verbatim quote (the row, for tables) |
| Deterministic validation | `kgproto/ontology.py`: ontology v0.1 (14 properties), quote, value, unit, qualifier and context checks |
| PostgreSQL as system of record | Runs, candidates, review decisions, generations, publication pointer, question log (`kgproto/db.py`) |
| Review queue | `GET /review-items`, `POST /review-items/{id}/decisions` (a second decision returns 409). The reviewer is a **stand-in**: an oracle built from the gold facts, or accept-all as a no-review baseline (`kgproto/review.py`) |
| Graph generations | Accepted claims projected into Neo4j as a numbered generation, checked (every claim has evidence), then activated through the publication pointer |
| Bounded QA | `POST /questions`: LLM proposes an intent plan; code checks it against the question, derives the qualifier, resolves the well, runs a fixed read-only Cypher template, and returns cited values or an abstention |
| Evaluation | `evaluate_extraction.py` (precision/recall before review), `evaluate_qa.py` (end-to-end, QA layer, citations, safety, latency), `test_ontology.py` |

Out of scope: BSEE (developed as its own track), authentication and roles, UI, multi-user concurrency, backups.

## Run it

Requires Docker Desktop and about 3 GB of disk. From the repository root:

```powershell
# 1. Model (2.1 GB) and services
curl.exe -L -o data/interim/models/qwen2.5-3b-instruct-q4_k_m.gguf https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf
docker compose -f prototype/docker-compose.yml up -d          # wait until http://127.0.0.1:8080/health says ok

# 2. Python environment for the prototype (separate from the locked ingestion one)
py -3.12 -m venv prototype/.venv
prototype/.venv/Scripts/python -m pip install -r prototype/requirements.txt

# 3. Pipeline
prototype/.venv/Scripts/python -m prototype.kgproto.load_graph            # AK-3 document and chunks into Neo4j
prototype/.venv/Scripts/python -m prototype.kgproto.extract               # prints the run ID; about 10 minutes on CPU
prototype/.venv/Scripts/python -m prototype.kgproto.evaluate_extraction 1 # precision/recall before review
Start-Process prototype/.venv/Scripts/python -ArgumentList "-m uvicorn prototype.kgproto.api:app --port 8000"
prototype/.venv/Scripts/python -m prototype.kgproto.review 1 oracle       # work through the review queue
prototype/.venv/Scripts/python -c "from prototype.kgproto.extract import project, activate; activate(project(1, 'reviewed'))"
prototype/.venv/Scripts/python -m prototype.kgproto.evaluate_qa reviewed  # 31 questions, about 3 minutes
prototype/.venv/Scripts/python -m unittest prototype.test_ontology
```

The model's downloaded file should have SHA256 `626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d`. Neo4j Browser is at http://127.0.0.1:7474 (user `neo4j`, password `prototype-only`), and interactive API docs at http://127.0.0.1:8000/docs. `docker compose -f prototype/docker-compose.yml down -v` removes everything.

## Files

| Path | Content |
|---|---|
| `gold/ak3_facts.json` | 41 hand-labelled facts (AI-assisted, single annotator) |
| `gold/questions.json` | 31 questions: answerable, paraphrased, not stated, unsupported, prompt injection |
| `results/` | Scores written by the evaluation scripts for the latest runs; `results/history/` holds earlier runs (`run<N>_…`), mapped to the runs in the [E4 record](../docs/experiments/E4-ak3-architecture-prototype.md) |
