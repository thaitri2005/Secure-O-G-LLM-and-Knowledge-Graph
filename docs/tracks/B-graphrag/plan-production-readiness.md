# Plan: everything that can be built before keys and servers arrive

**Written:** 24 November 2026, Track B (Tri, with Claude), with clearance from Khai and Hung to work in all three tracks (Track B log B-D41). **Goal:** at the end of the stint the only work left is to rent the server, set passwords and keys, and run the measurements that need the desktop GPU.

The designs this plan carries out are already written: [backend design](../C-storage/backend-design.md) (B1 to B8), [specification §4.6, §7.5, §8.5, §8.6](../../PROJECT_DESIGN.md), the [note for Khai](../A-ingestion/note-from-track-B-2026-11-24.md) (D1 to D5). This file only splits the work so several development agents can build at once without touching the same files.

## Rules for every work package

- Work only in the files your package owns. If another file must change, say so in your report instead of changing it.
- Open-weight models only inside the project; no commercial API is called by any code. Tests use stand-in models and need no network.
- Tests are `unittest` (`python -m unittest discover -s tests -p "<pattern>"`). Tests that need PostgreSQL, Neo4j or Docker skip with a reason when the service is not reachable.
- LF line endings. Plain English in comments and documents, short tables and lists.
- No credentials in the repository: passwords and keys come from the environment; `platform-dev` remains only as the local default.
- PyMuPDF (AGPL) stays out of anything deployed; use `pypdfium2`.
- Do not touch `prototype/`, `explorations/`, frozen question sets in `graphrag/gold/`, or recorded results in `graphrag/results/`.
- Do not commit, push, or edit the track logs, the plan or the specification. The overseeing session reviews, logs and commits.
- Report at the end: files changed, how each "done when" was checked (with the command and its result), what is not done, and anything doubtful.

## Local services for testing

| Service | Address | Credentials |
|---|---|---|
| PostgreSQL 16 with pgvector | `postgresql://kg:platform-dev@127.0.0.1:5434/kg` | local default |
| Neo4j 5.26 with APOC | `bolt://127.0.0.1:7687` | `neo4j` / `platform-dev` |

Both are shared by all agents. PostgreSQL holds the K1 tables of `platform/sql/001_k1.sql`; new SQL files must be idempotent (`CREATE TABLE IF NOT EXISTS`) because the init folder runs only on an empty volume. Integration tests use their own schema or their own well name and clean up after themselves, so they cannot disturb another agent.

## Fixed interfaces

These names are fixed so packages fit together without talking.

| Interface | Definition |
|---|---|
| Environment variables | `BACKEND_DSN` (PostgreSQL), `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `BACKEND_SOURCE` (`files` or `stores`), `BACKEND_PAGE_IMAGES` (folder of page images), `BACKEND_CORS_ORIGINS`, `POSTGRES_PASSWORD` (compose) |
| Question log tables | `questions`, `question_feedback`, exactly as in backend design §3, in `platform/sql/002_questions.sql` |
| Run record table | `runs (run_id text primary key, release text, started_at timestamptz, finished_at timestamptz, status text, record jsonb)` in `platform/sql/003_runs.sql` |
| Fact region in Neo4j | Labels and key properties of backend design §4.1: `Well.name`, `Chunk.chunk_id`, `Document.file_id`, `Fact.fact_id`, `CasingString.casing_id`, `HoleSection.section_id`; `Fact` properties `property`, `value`, `unit`, `qualifier`, `context` (JSON text), `source`; relationships `HAS_FACT`, `FROM`, `DESCRIBED_BY`, `HAS_CHUNK`, `HAS_CASING`, `HAS_SECTION` |
| Event region in Neo4j | As `platform/load_events_neo4j.py` writes it today |
| Store readers | `graphrag/stores.py`: `read_chunks(dsn, release=None) -> list[dict]`, `read_events(driver, well) -> list[Event]`, `read_facts(driver) -> list[dict]`, `engine_from_stores(dsn, neo4j_uri, neo4j_user, neo4j_password, **settings) -> Engine` |
| Page images | `<BACKEND_PAGE_IMAGES>/<file_id>/p<n>.png`, 150 dpi, page numbers from 1; route `GET /v1/files/{file_id}/pages/{n}/image` |
| Reasoning lane | `graphrag/reasoning.py`: `reasoning(question, frame, engine, client) -> Evidence`-compatible result; registered in `graphrag.lanes.LANES` as `reasoning`; the frame's `kind` gains `cause` |

## Work packages

| # | Package | Owns | Done when |
|---|---|---|---|
| W1 | **Stores: loaders and the runner** (B2, B3) | `platform/load_facts_neo4j.py` (new), `platform/load_events_neo4j.py`, `platform/run_release.py` (new), `platform/sql/003_runs.sql` (new), `platform/README.md` (new), `tests/test_platform_*.py` (new) | The fact region loads from `graphrag/results/E27_fact_graph.graph.json` with the four checks of backend design §4.1 and rolls back on a difference; the event loader takes `--events`, `--runs`, `--well`, and reads the address and password from the environment; `run_release.py` runs the eight steps of §6 on `data/interim/k1/ak3-k1-v1-candidate`, twice, with the same counts, and writes a `runs` row |
| W2 | **Engine and backend on the stores** (B6, E2) | `graphrag/stores.py` (new), `backend/questions.py`, `backend/app.py` (`default_service` only), `backend/README.md`, `backend/requirements.txt`, `platform/sql/002_questions.sql` (new), `tests/test_graphrag_stores.py` (new), `tests/test_backend_postgres.py` (new) | `PostgresQuestionLog` passes the same tests as the file log against the local PostgreSQL, and the counting query of §3 runs; `engine_from_stores` builds an `Engine` whose chunks, events and facts equal the file-loaded ones on the same data; with `BACKEND_SOURCE=stores` the health endpoint says `"source": "stores"`; with nothing set the service behaves exactly as today |
| W3 | **Deployment** (B1, B8) | `platform/docker-compose.yml`, `platform/.env.example` (new), `backend/Dockerfile` (new), `frontend/Dockerfile` (new), `deploy/` (new: `Caddyfile`, `backup.sh`, `README.md` runbook, `smoke_test.py`), `.dockerignore` (new), `.github/workflows/ci.yml` (new), `scripts/stub_model_server.py` (new), `tests/test_stub_model_server.py` (new) | `docker compose -f platform/docker-compose.yml --profile app up -d --build` gives the application at one local address behind one shared password, with the stub model server standing in for llama.cpp, and `deploy/smoke_test.py` asks a question through the proxy and gets an answer; the stores still start alone with the local defaults; the runbook takes a new Ubuntu server to a running application step by step; CI runs the Python and frontend tests on push without blocking anyone |
| W4 | **The reasoning lane** (E7, code only) | `graphrag/reasoning.py` (new), `graphrag/lanes.py`, `graphrag/coordinator.py`, `graphrag/k4.py`, `schemas/k4_answer_record.schema.json`, `graphrag/README.md`, `tests/test_graphrag_reasoning.py` (new), `tests/test_graphrag_lanes.py` | The lane of specification §8.6 runs on the recorded AK-3 events with a stand-in model: finds the problem, gathers the surrounding evidence in code, asks for a two-part answer under a JSON schema, drops any cause without a valid citation in code, and lists what is missing; the coordinator routes `kind: cause` to it; every existing test still passes with byte-identical requests for the other lanes. The probe's questions are written by the overseeing session, not by this package |
| W5 | **Data: the demo K1 release** (D1, D4, D5 and the test fixes) | `src/graph_builder/` (ingestion), `scripts/` files of Track A, `tests/test_corpus_*.py`, `tests/test_qa_*.py`, `tests/test_table_*.py`, `docs/tracks/A-ingestion/log.md` (new, a draft for Khai) | The two tests that fail without PyMuPDF skip with a reason; a K1 version 1 release is built from AK-3's end-of-well report, appendices 27 to 30 and appendix 23, with `legacy_chunk_ids.json` inside and `context.well` on every end-of-well chunk, and passes the five checks of the note's Task 1; merged-cell text appears once in table Markdown (D4) with a test; nothing in K1's field list changes |
| W6 | **Page images and the source viewer** (B7, F2) | `platform/render_pages.py` (new), `backend/service.py`, `backend/schemas.py`, `backend/app.py` (the new route only), `backend/contract.py`, `backend/openapi.json`, `backend/fixtures/`, `frontend/` (all), `tests/test_backend.py`, `tests/test_platform_render_pages.py` (new) | `render_pages.py` writes one PNG per page with `pypdfium2`; the image route validates `file_id` and `n` before touching the disk and returns the PNG, and `PageOut.image_url` is set when the image exists and stays `null` otherwise; the frontend shows the page image beside the passage, with the credit line, and falls back to text when there is no image; frontend and backend tests pass; the frontend's production build has no development-only address in it |

`backend/app.py` is shared by W2 (`default_service`) and W6 (one new route): each keeps its change inside that part of the file.

## After the packages

The overseeing session merges the six branches, runs the whole test suite, runs the application end to end against the local stores with the stub model server, reviews each diff, writes the reasoning probe's questions, and records everything in the track logs, the plan and the stint report.

## What stays for people

| What | Who | Needs |
|---|---|---|
| Rent the server, set the passwords, run the runbook | Hung | The provider account |
| E32, E33, E34 on the desktop | Tri | The GPU |
| A hosted open-weight model for the demo | Tri | An OpenRouter key and about US$10 |
| Review the K1 release and the Track A log draft | Khai | — |
| Message anh Tuấn | Tri | — |
