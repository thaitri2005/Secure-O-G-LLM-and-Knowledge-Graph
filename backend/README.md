# backend: the read-path API

The FastAPI service of the second build ([specification §4.6](../docs/PROJECT_DESIGN.md#46-second-build-one-connected-application), [§7.5](../docs/PROJECT_DESIGN.md#75-http-interface-design)). It answers questions through the coordinator in [`graphrag`](../graphrag/README.md) and serves what the frontend shows: chunks, pages, wells and events. Written by Track B on Hung's behalf on 24 November 2026 (Track B log B-D39, B-C44); the parts still to build are in the [backend design](../docs/tracks/C-storage/backend-design.md).

## Run it

```powershell
.venv\Scripts\python -m pip install -r backend/requirements.txt      # once: FastAPI and uvicorn, on top of the main lock file
.venv\Scripts\python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000/docs for the interactive description. Reading endpoints work at once. `POST /v1/questions` needs the model server of the roles file ([`configs/graphrag/roles.json`](../configs/graphrag/roles.json)), such as llama.cpp on port 8080; without it the answer is a `503` that says so.

### Where it reads from: the environment

With nothing set, the service reads this machine's files and writes the question log to a file, as it always has.

| Variable | Effect |
|---|---|
| `BACKEND_SOURCE` | `files` (the default) or `stores`: the engine reads the K1 release in PostgreSQL and the graph in Neo4j ([`graphrag/stores.py`](../graphrag/stores.py)) |
| `BACKEND_DSN` | PostgreSQL address, e.g. `postgresql://kg:<password>@127.0.0.1:5434/kg`. When set, the question log goes into its `questions` and `question_feedback` tables. Needed by `BACKEND_SOURCE=stores` |
| `BACKEND_RELEASE` | The K1 release to read, when the store holds more than one |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Neo4j address and login for `BACKEND_SOURCE=stores`; the local stores' defaults (`bolt://127.0.0.1:7687`, `neo4j`, `platform-dev`) when unset |
| `BACKEND_CORS_ORIGINS` | Origins allowed to call the API; the frontend's development server when unset, empty behind the proxy |

A store that is configured but does not answer, a database without the question tables, or a release that is not there stops the service with the error; nothing falls back to files. The service is built on the first request, so the error shows there and in the server log. `GET /v1/health` says `"source": "stores"` or `"files"`.

```powershell
python -m backend.questions init       # once per database: the tables of platform/sql/002_questions.sql (safe to repeat)
python -m backend.questions counts     # questions asked, answered and marked wrong, per kind (backend design §3)
```

Both read `BACKEND_DSN`, or take `--dsn`.

**The model endpoints are not set by the environment yet.** The roles and endpoints come from `configs/graphrag/roles.json` and `endpoints.json`; only a hosted endpoint's key comes from the environment (`OPENROUTER_API_KEY`). A server points the frame and answer roles elsewhere by its own copy of those two files.

## Endpoints

| Endpoint | Returns |
|---|---|
| `POST /v1/questions` | The answer, the lanes that gave its evidence, the question frame, citations with their text and page, the evidence shown (passages, facts, the computed result with its events), the checks and the cost. Body: `question`, `mode` (`allow_fallback` or `exact`), optional `lane` |
| `POST /v1/questions/{id}/feedback` | Stores `right` or `wrong` and a comment against a logged question |
| `GET /v1/chunks/{chunk_id}` | One chunk. Chunk IDs contain `#` or `:`, so percent-encode them in the path |
| `GET /v1/files`, `GET /v1/files/{file_id}/pages/{n}` | The loaded reports; one page as its chunks in reading order. `image_url` is the image route's path when the page has been rendered, else null |
| `GET /v1/files/{file_id}/pages/{n}/image` | The page as a PNG, from `<BACKEND_PAGE_IMAGES>/<file_id>/p<n>.png` (written by `platform/render_pages.py`). `file_id` must be a loaded file and `n` a positive integer, checked before any path is built; 404 when there is no image; cached for a day |
| `GET /v1/wells`, `GET /v1/wells/{well_id}` | The wells; one well's facts, documents and report days |
| `GET /v1/wells/{well_id}/events` | A well's events, optionally between `date_from` and `date_to` |
| `GET /v1/health` | What the engine holds and which models serve |

## The contract with the frontend

- [`openapi.json`](openapi.json) is the description of every request and response.
- [`fixtures/`](fixtures/) holds one real response per endpoint, to build the frontend against before the model server is up.
- Both are generated: `python -m backend.contract`. A test fails when they fall behind the code, so regenerate and commit them with any change to `schemas.py`, then run `npm run types` in [`frontend/`](../frontend/README.md).
- **The fixtures' model is a stand-in.** The evidence in them is real (the three end-of-well reports, E28's recorded events, the validated facts), but the frame and answer of each example question are scripted in `contract.py`. They show the shape of a response, not what a model says.

## Files

| File | Holds |
|---|---|
| `schemas.py` | Request and response shapes: the contract |
| `service.py` | What the API does, without HTTP: questions through the coordinator, reads of chunks, files, wells and events |
| `app.py` | Routes, errors, CORS for the frontend's development server; `create_app(service)` for tests |
| `questions.py` | The question log: every question, how it was answered, and feedback. A JSON-lines file under ignored `data/interim/backend/`, or PostgreSQL's tables when `BACKEND_DSN` is set |
| `contract.py` | Writes `openapi.json` and the fixtures |

## What it reads today, and what changes

The service holds an `Engine` ([`graphrag/lanes.py`](../graphrag/lanes.py)), loaded one of two ways; the rest of the service is the same for both.

| Source | End-of-well chunks | Daily chunks | Events | Facts |
|---|---|---|---|---|
| `files` | The committed bundle (three reports, K1 version 0) | The daily-report corpus, if this machine has it | Built from that corpus | The fact runs of the current design, validated on load |
| `stores` | The release's chunks in PostgreSQL that are not daily | Its daily-report files and the non-productive-time report (appendix 23), told apart by name as `Engine.load(k1=True)` does | The event region in Neo4j, for AK-3 | The fact region in Neo4j, validated when the graph was built |

**On the stores, citations follow the IDs the graph was built on.** Facts and events cite the chunk IDs of the run that built them. A cited chunk the release does not hold is counted in the server log at start and shown without its text. Today's fact region (E27) cites K1 version 0 IDs, so every fact citation is of that kind until the facts are rebuilt on a K1 version 1 release (backend design §4.2).

## Limits

- No login. The demo holds public data only, and the access gate is a shared password at the proxy (design, B8).
- One question at a time: the model server has one slot.
- Responses over 2 kB are compressed. Reads may be kept by the browser for a minute; answers, feedback and health never.
- The question log holds what users typed. It stays on the machine: in an ignored folder, or in the deployment's PostgreSQL.
- The event graph is one well's (AK-3), so only that well has report days and events.
- On the stores, questions naming several wells search per well in memory, as on files. The SQL vector search over `chunk_vectors` with the well filter (C-C10) is not built.

Tests: `python -m unittest tests.test_backend` (no server or model needed). `python -m unittest tests.test_backend_postgres tests.test_graphrag_stores` checks the PostgreSQL log, the environment and the stores; tests needing the local PostgreSQL or Neo4j skip when those do not answer.
