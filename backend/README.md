# backend: the read-path API

The FastAPI service of the second build ([specification §4.6](../docs/PROJECT_DESIGN.md#46-second-build-one-connected-application), [§7.5](../docs/PROJECT_DESIGN.md#75-http-interface-design)). It answers questions through the coordinator in [`graphrag`](../graphrag/README.md) and serves what the frontend shows: chunks, pages, wells and events. Written by Track B on Hung's behalf on 24 November 2026 (Track B log B-D39, B-C44); the parts still to build are in the [backend design](../docs/tracks/C-storage/backend-design.md).

## Run it

```powershell
.venv\Scripts\python -m pip install -r backend/requirements.txt      # once: FastAPI and uvicorn, on top of the main lock file
.venv\Scripts\python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000/docs for the interactive description. Reading endpoints work at once. `POST /v1/questions` needs the model server of the roles file ([`configs/graphrag/roles.json`](../configs/graphrag/roles.json)), such as llama.cpp on port 8080; without it the answer is a `503` that says so.

## Endpoints

| Endpoint | Returns |
|---|---|
| `POST /v1/questions` | The answer, the lanes that gave its evidence, the question frame, citations with their text and page, the evidence shown (passages, facts, the computed result with its events), the checks and the cost. Body: `question`, `mode` (`allow_fallback` or `exact`), optional `lane` |
| `POST /v1/questions/{id}/feedback` | Stores `right` or `wrong` and a comment against a logged question |
| `GET /v1/chunks/{chunk_id}` | One chunk. Chunk IDs contain `#` or `:`, so percent-encode them in the path |
| `GET /v1/files`, `GET /v1/files/{file_id}/pages/{n}` | The loaded reports; one page as its chunks in reading order. The page image comes later (`image_url` is null) |
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
| `questions.py` | The question log: every question, how it was answered, and feedback. A JSON-lines file under ignored `data/interim/backend/` for now |
| `contract.py` | Writes `openapi.json` and the fixtures |

## What it reads today, and what changes

The service holds an `Engine` ([`graphrag/lanes.py`](../graphrag/lanes.py)) loaded **from this machine's files**, not from the stores: the committed end-of-well bundle, the daily-report corpus if it is there, and the fact runs of the current design. `GET /v1/health` reports `"source": "files"`. When the shared stores are up, the engine's loading changes and this service does not.

## Limits

- No login. The demo holds public data only, and the access gate is a shared password at the proxy (design, B8).
- One question at a time: the model server has one slot.
- Responses over 2 kB are compressed. Reads may be kept by the browser for a minute; answers, feedback and health never.
- The question log holds what users typed. It stays on the machine, in an ignored folder.
- The event graph is one well's (AK-3), so only that well has report days and events.

Tests: `python -m unittest tests.test_backend` (21 tests, no server or model needed).
