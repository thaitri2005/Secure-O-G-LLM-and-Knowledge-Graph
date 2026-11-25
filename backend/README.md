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
| `BACKEND_PAGE_IMAGES` | The folder of page images, one sub-folder per report; a page without an image is shown as text |
| `BACKEND_CORS_ORIGINS` | Origins allowed to call the API; the frontend's development server when unset, empty behind the proxy |
| `BACKEND_PUBLIC_RELEASES` | The packages that may be sent to a hosted model, by name, comma-separated. Needed only when the roles file names a hosted endpoint and `BACKEND_SOURCE=stores`; see [the hosted-model boundary](#the-hosted-model-boundary) |
| `BACKEND_MODEL_TIMEOUT` | Seconds one model call may take; 75 when unset |
| `BACKEND_QUEUE_SECONDS`, `BACKEND_MAX_WAITING` | How long a question waits for the model's one slot (60 seconds) and how many may wait (8); see [waiting and failures](#waiting-and-failures) |

A store that is configured but does not answer, a database without the question tables, or a release that is not there stops the service with the error; nothing falls back to files. On the stores the service is built when the server starts, and on files at the first request. Either way the search indexes are built then, so the first question does not wait for them. `GET /v1/health` says `"source": "stores"` or `"files"`.

```powershell
python -m backend.questions init       # once per database: the tables of platform/sql/002_questions.sql (safe to repeat)
python -m backend.questions counts     # questions asked, answered and marked wrong, per kind (backend design §3)
python -m backend.questions stats      # how the application is doing: see "What the log tells the team"
```

All three read `BACKEND_DSN`, or take `--dsn`; `stats` also takes `--file <questions.jsonl>` and `--since <day>`.

**Which models serve.** The roles and endpoints come from `configs/graphrag/roles.json` and `endpoints.json`, or from the files `GRAPHRAG_ROLES` and `GRAPHRAG_ENDPOINTS` name. A hosted endpoint's key comes from the environment (`OPENROUTER_API_KEY`). The compose file mounts a server's own copies of the two files.

## Endpoints

| Endpoint | Returns |
|---|---|
| `POST /v1/questions` | The answer, the lanes that gave its evidence, the question frame, citations with their text and page, the evidence shown (passages, facts, the computed result with its events), the checks and the cost. Body: `question`, `mode` (`allow_fallback` or `exact`), optional `lane` |
| `POST /v1/questions/{id}/feedback` | Stores `right` or `wrong` and a comment against a logged question |
| `GET /v1/chunks/{chunk_id}` | One chunk. Chunk IDs contain `#` or `:`, so percent-encode them in the path |
| `GET /v1/files`, `GET /v1/files/{file_id}/pages/{n}` | The loaded reports; one page as its chunks in reading order. `image_url` is the image route's path when the page has been rendered, else null |
| `GET /v1/files/{file_id}/pages/{n}/image` | The page as a PNG, from `<BACKEND_PAGE_IMAGES>/<file_id>/p<n>.png` (written by `platform/render_pages.py`). `file_id` must be a loaded file and `n` a positive integer, checked before any path is built; 404 when there is no image; cached for a day |
| `GET /v1/wells` | The wells, with how many facts and report days each has |
| `GET /v1/wells/{well_id}` | What a well page shows, computed in code: facts in groups (general; depths and dates; casing strings, largest first; readings at depths), each with its chunk, file and page; the well's reports with type and page count; each report day's hours, non-productive hours, depth and codes; totals with non-productive hours by code |
| `GET /v1/wells/{well_id}/events` | A well's events, optionally between `date_from` and `date_to` |
| `GET /v1/health` | Whether the service is up, what its engine holds and which models serve. It asks nothing of the stores or the model |
| `GET /v1/ready` | Whether a question could be answered now: asks the model endpoint and the question log, at most once every 15 seconds. `200` with `"ready": true`, or `503` naming what did not answer. Also says how many questions are waiting. A monitor watches this one |
| `GET /v1/admin/questions` | The question log, newest first, each question with its feedback. Filters: `kind`, `status`, `mode`, `verdict` (`right`, `wrong`, `none`; the latest mark), `date_from`, `date_to`, `q` (text in the question), `ids`; paged by `limit` (at most 200) and `offset` |
| `GET /v1/admin/questions/{id}` | One logged question with its whole stored record |
| `GET /v1/admin/questions/counts` | Logged questions counted by kind, status and verdict; same filters |
| `GET /v1/admin/questions/export` | The questions the filters or `ids` select, as a question file in the format of [`graphrag/gold/`](../graphrag/gold/): status line "COLLECTED from the application's question log on <date> ...", gold left empty, each question's log ID, asked time, the answer given and the marks kept, oldest first. `expected_lane` is written only when given. `python -m graphrag.coordinator answer --questions <file>` runs it, and `python -m graphrag.expert sheet <file>` makes it a sheet for a person to fill in ([guide](../docs/EXPERT_PILOT.md)) |

The cause answer's evidence carries each event's fields as `activity` beside the text line the model saw, so the frontend need not parse the line.

**The `/v1/admin/` routes have no login yet.** They are read-only, never cached, and protected only by the shared password at the proxy, like the rest of the application: anyone past it can read every question users typed. The log is how the questions domain experts type become the project's real test set (D-65).

## Waiting and failures

The model server answers one question at a time, so questions take turns.

| Limit | Default | When it is passed |
|---|---|---|
| One model call | 75 seconds | The question fails with `model_unavailable` |
| A question's wait for its turn | 60 seconds | It is refused with `busy` and `Retry-After: 30` |
| Questions waiting | 8 | The next one is refused with `busy` at once |
| The browser's own limit | 240 seconds | The frontend stops waiting and says so |

The order matters: a model call ends before the wait for a turn does, and both end before the browser gives up. So nobody waits for an answer the server has already abandoned, and a model that hangs holds the slot for 75 seconds, not for a quarter of an hour. A slow machine raises the first two with the variables above, and `ASK_TIMEOUT_MS` in `frontend/src/api/client.ts` with them.

**Errors have one shape:** `{"detail": "<a sentence>", "code": "<a word>", "question_id": "<when a question was logged>"}`.

| Status | `code` | Means |
|---|---|---|
| 503 | `busy` | Other questions are being answered; try again in half a minute |
| 503 | `model_unavailable` | The model endpoint did not answer, or took too long |
| 503 | `store_unavailable` | PostgreSQL or Neo4j dropped while the question was answered |
| 404 | `not_found` | No such chunk, file, page, well or logged question |
| 422 | `invalid_request` | The request's fields are wrong; `errors` lists them |
| 500 | `internal` | A fault in the service; the server log has it |

**A question that fails is still logged**, with status `error` and the kind of failure, so no question an expert typed is lost and the error rate can be counted. **An answer is never lost to the log:** if the log cannot be written, the answer is returned and the failure goes to the server log.

**Nothing is retried automatically.** A person who asks again gets a new log entry. The model calls of the second try come from the request cache when the first try got that far. A reply that should have been JSON and was not is never kept in that cache, so asking again asks the model again.

## What the log tells the team

Each question writes one JSON line to the server log (`docker compose logs backend`): its ID, status, lanes, model calls, tokens, seconds, the seconds it waited for its turn, and the error if it failed. The same ID is in every error reply, so a report from a user leads to its line.

`python -m backend.questions stats` reads the question log and prints what a run of the application cost and how it went (specification §11.2):

| Field | Meaning |
|---|---|
| `questions`, `by_status`, `by_lane`, `by_error` | How many, how they ended, which lanes answered, which failures |
| `error_rate`, `not_found_rate`, `fallback_rate` | Shares of all questions |
| `seconds_p50`, `seconds_p95` | Seconds per question; failed questions and those answered from the request cache are left out |
| `queue_seconds_p95` | How long questions waited for the model's slot |
| `calls_mean`, `prompt_tokens_mean`, `completion_tokens_mean` | The cost of a question |
| `marked_wrong` | Questions whose latest mark is "wrong" |

## The hosted-model boundary

A hosted model may only see public data (specification §10.1, D-68). The engine's client cannot tell what a package holds, so the service checks once, at start: when the roles file names a hosted endpoint and the data comes from the stores, the loaded package must be named in `BACKEND_PUBLIC_RELEASES`. If it is not, the service refuses to start and says why. Naming a package there is a person's statement that every report in it is public. With `BACKEND_SOURCE=files` the data is the committed bundle, which is public ([data sources](../docs/DATA_SOURCES.md)). With local models nothing is checked.

## The contract with the frontend

- [`openapi.json`](openapi.json) is the description of every request and response.
- [`fixtures/`](fixtures/) holds one real response per endpoint, to build the frontend against before the model server is up.
- Both are generated: `python -m backend.contract`. A test fails when they fall behind the code, so regenerate and commit them with any change to `schemas.py`, then run `npm run types` in [`frontend/`](../frontend/README.md).
- **The fixtures' model is a stand-in.** The evidence in them is real (the three end-of-well reports, E28's recorded events, the validated facts), but the frame and answer of each example question are scripted in `contract.py`. They show the shape of a response, not what a model says.
- **The `admin_*` fixtures read a small fixed log** written by `contract.py`: four made-up entries and three marks, not questions anyone asked.

## Files

| File | Holds |
|---|---|
| `schemas.py` | Request and response shapes: the contract |
| `service.py` | What the API does, without HTTP: questions through the coordinator, reads of chunks, files, wells and events |
| `app.py` | Routes, errors, CORS for the frontend's development server; `create_app(service)` for tests |
| `questions.py` | The question log: every question, how it was answered, and feedback, written and read back (filters, counts, export as a question file). A JSON-lines file under ignored `data/interim/backend/`, or PostgreSQL's tables when `BACKEND_DSN` is set |
| `contract.py` | Writes `openapi.json` and the fixtures |

## What it reads today, and what changes

The service holds an `Engine` ([`graphrag/lanes.py`](../graphrag/lanes.py)), loaded one of two ways; the rest of the service is the same for both.

| Source | End-of-well chunks | Daily chunks | Events | Facts |
|---|---|---|---|---|
| `files` | The committed bundle (three reports, K1 version 0) | The daily-report corpus, if this machine has it | Built from that corpus | The fact runs of the current design, validated on load |
| `stores` | The release's chunks in PostgreSQL that are not daily | Its daily-report files and the non-productive-time report (appendix 23), told apart by name as `Engine.load(k1=True)` does | The event region in Neo4j, for AK-3 | The fact region in Neo4j, validated when the graph was built |

**Questions naming several wells** are searched once per well, chosen at start and kept until the service stops:

| Source | Embedding server answers at start | Retriever |
|---|---|---|
| `files` | yes | BM25 fused with the vector search in memory (`perwell:fusion:bm25+dense:<model>`) |
| `stores` | yes, and the store holds a vector of the embed role's model for every chunk of the release | BM25 fused with the vector search in PostgreSQL (`perwell:fusion:bm25+pgvector:<model>`, `graphrag.retrieval.PgVector`) |
| either | otherwise | BM25 alone (`perwell:bm25`) |

The search in PostgreSQL returns what the search in memory returns on the same vectors, order included (`tests/test_graphrag_vectors.py`); only the question is embedded. A release with vectors for only some of its chunks counts as having none, and the server log names the counts. Once chosen, the retriever does not change: if the embedding server or the database stops answering, questions fail instead of quietly searching another way. `GET /v1/health` shows the choice (`multi_well_retriever`) and the vectors the store holds for the release (`stored_vectors`).

`chunk_vectors` has no vector index, only its primary key, so each search reads every vector of the release: about 17 ms for 1,042 vectors and 80 ms for 10,000 on a laptop (24 November 2026). An approximate index (HNSW) starts to matter at tens of thousands of vectors, some twenty releases the size of AK-3's (1,051 chunks), and would make the search approximate, so it would no longer equal the search in memory.

**On the stores, citations follow the IDs the graph was built on.** Facts and events cite the chunk IDs of the run that built them. A cited chunk the release does not hold is counted in the server log at start and shown without its text. Today's fact region cites the package's chunk IDs for all of its 206 facts.

## Limits

- No login, also for the `/v1/admin/` reads of the question log. The demo holds public data only, and the access gate is a shared password at the proxy (design, B8).
- One question at a time: the model server has one slot, and the engine counts a question's cost per client. A hosted endpoint could answer several at once; the service does not use that yet.
- Loading a new package while the service runs needs a restart of the service afterwards: it reads its data once, at start.
- Questions naming several wells fail, not fall back, if the embedding server stops after start (see above).
- Responses over 2 kB are compressed. Reads may be kept by the browser for a minute; answers, feedback, health and the question log never.
- The question log holds what users typed. It stays on the machine: in an ignored folder, or in the deployment's PostgreSQL.
- The event graph is one well's (AK-3), so only that well has report days, events and non-productive totals.

Tests: `python -m unittest tests.test_backend tests.test_backend_operations` (no server or model needed). `python -m unittest tests.test_backend_postgres tests.test_graphrag_stores` checks the PostgreSQL log, the environment and the stores; tests needing the local PostgreSQL or Neo4j skip when those do not answer.
