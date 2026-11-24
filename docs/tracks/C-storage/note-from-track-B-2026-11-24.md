# Note for Hung: what to build next, in detail

**From:** Tri (Track B), 24 November 2026 · **Goes with:** the [backend design](backend-design.md), which holds the SQL, the Cypher and the reasons · **Plan tasks:** B1 to B8 in the [plan](../../DEVELOPMENT_PLAN.md#7-what-to-do-now)

This is your work list for the backend and the stores, in the order that unblocks the most. Each task says what to build, the steps, and how to know it is done. Change anything you disagree with and say so in your log.

## Update, later on 24 November: most of this list is built

With your clearance the tasks below were built the same day (Track B log B-D41; Track C log C-C14 to C-C18), beside your own fact loader and server scripts. **What is asked of you now is review, a host, and the real server run**, not the building. The task sections further down are kept as the description of what each part must do; read them as the checklist to review against.

| Task | State | What is left for you |
|---|---|---|
| 1. Shared server (B1) | Your scripts and [runbook](server-runbook.md) are ready; no server | Agree a host. Tri's desktop is borrowed and cannot host (C-D07): your machine over Tailscale, or wait for a server |
| 2. Well facts in Neo4j (B3) | Loaded. One loader is kept from the two written that afternoon (C-C14) | Check that choice; reverse it if you disagree |
| 3. The engine reads the stores | Built: `graphrag/stores.py`, `BACKEND_SOURCE=stores` | Try it against your stores, which hold vectors (Tri's do not) |
| 4. The runner (B2) | Built: `python platform/run_release.py <release>` ([platform/README.md](../../../platform/README.md)) | Run it with the embedding server; confirm the softer rule for the graphical report (C-C16) |
| 5. The application on the host (B8) | Built: `--profile app`, [deploy/README.md](../../../deploy/README.md); run on a laptop with a stub model | Run it on a real server with a domain |
| 6. Page images (B7) | Built: `platform/render_pages.py` and the image route | Render the demo release's pages on the host |
| The question log in PostgreSQL (B6) | Built: `platform/sql/002_questions.sql` | Check the tables suit you |

To see it all run on your machine, with no model and no GPU:

```sh
docker compose -f platform/docker-compose.yml --profile app --profile demo up -d --build   # needs APP_PASSWORD_HASH in platform/.env
python deploy/smoke_test.py --url http://127.0.0.1 --user team --password '<the password>' --expect-stub
```

The demo release to load is `ak3-demo-v1`: build it with `python scripts/build_k1_demo_release.py` (it needs the source PDFs and the E8 corpus), or ask Tri for the folder. It holds the same files as the candidate you loaded, so load it with `--replaces <the old release name>`.

## Where things stood when the list was written

| Piece | State on the morning of 24 November |
|---|---|
| PostgreSQL with pgvector, Neo4j, the K1 loader, 1,042 vectors, the daily activities in Neo4j | Built and checked by you, on your laptop |
| The backend service, [`backend/`](../../../backend/README.md) | Built, reading files |
| The contract with the application: [`backend/openapi.json`](../../../backend/openapi.json) and example responses in `backend/fixtures/` | Built |
| The question log | Built as a file |
| The well facts as a graph file: [`E27_fact_graph.graph.json`](../../../graphrag/results/E27_fact_graph.graph.json) | Built, ready to load |
| The application, [`frontend/`](../../../frontend/README.md) | Built, on the example responses |

```powershell
.venv\Scripts\python -m pip install -r backend/requirements.txt
.venv\Scripts\python -m uvicorn backend.app:app --port 8000      # then http://127.0.0.1:8000/docs
cd frontend; npm install; npm run dev:examples                    # the application, no model needed
python -m unittest discover -s tests -p "test_backend*.py"
```

## Task 1 (B1): put the stores on a shared server

**Why first:** it blocks everything else. The engine cannot read the stores, and data still travels through chat.

**Build**

1. A server from GitHub Student Developer Pack credits (DigitalOcean or Azure): about 4 vCPU, 8 GB memory, 80 GB disk, Ubuntu LTS, Docker with the compose plugin. **Tell me if that size is wrong**: the [resource request](../../reports/RESOURCE_REQUEST_2026-11-24.md) to anh Tuấn assumes it.
2. Change `platform/docker-compose.yml` so the two passwords come from the environment: `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}` and `NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:?}`. Add a `.env.example` with the variable names and no values.
3. On the server: a `.env` with new passwords (not `platform-dev`), then `docker compose -f platform/docker-compose.yml up -d`.
4. Firewall: only ports 22 and 443 open. Leave PostgreSQL (5434) and Neo4j (7474, 7687) bound to `127.0.0.1`, as the compose file already does.
5. Give Khai and me access: add our SSH public keys. We reach the databases through a tunnel: `ssh -L 5434:127.0.0.1:5434 -L 7687:127.0.0.1:7687 <user>@<server>`.
6. A folder for K1 releases on the server, `/srv/k1/<release>/`, filled with `scp` or `rsync`.
7. Load the AK-3 release there with `platform/load_k1.py`, then `embed_k1.py embed` and `load_events_neo4j.py`, as you did on your laptop.
8. A nightly `pg_dump` kept for 7 days (a cron line is enough).
9. Write in your log: the provider, the address, how to connect, the release loaded. No password in the repository.

**Done when:** from my machine, through the tunnel, `python platform/k1_store.py compare <package>` reports every chunk identical; Khai can connect too.

**Yours to decide:** the provider; SSH tunnel or Tailscale.

## Task 2 (B3): load the well facts into Neo4j

**Build:** `platform/load_facts_neo4j.py`, written like your `load_events_neo4j.py`.

1. **Read** [`graphrag/results/E27_fact_graph.graph.json`](../../../graphrag/results/E27_fact_graph.graph.json). It has `nodes` (`{label, key, properties}`) and `relationships` (`{type, from: [label, key], to: [label, key]}`), plus counts at the top.
2. **Constraints:** a uniqueness constraint per new key: `Document.file_id`, `Fact.fact_id`, `CasingString.casing_id`, `HoleSection.section_id`. Keep your existing `Well.name` and `Chunk.chunk_id`.
3. **In one write transaction:**
   - Clear the fact region only: delete `Fact`, `CasingString`, `HoleSection` and `Document` nodes, then any `Chunk` left with no relationship. Do not touch `Well`, `ReportDay` or `Event`.
   - Nodes: one `UNWIND ... MERGE` per label, setting the key property from `key` and the rest from `properties`. `MERGE` for `Well` and `Chunk` too, so they join the nodes your event graph already made.
   - Relationships: one `UNWIND ... MATCH ... MERGE` per type. Six types: `HAS_FACT`, `FROM`, `DESCRIBED_BY`, `HAS_CHUNK`, `HAS_CASING`, `HAS_SECTION`.
4. **Check, and roll back on any difference:**
   - counts per label and per type equal the file's: 5 wells, 3 documents, 38 chunks, 216 facts, 11 casing strings; 216 `HAS_FACT`, 216 `FROM`, 38 `HAS_CHUNK`, 5 `DESCRIBED_BY`, 11 `HAS_CASING`;
   - every `Fact` has exactly one `HAS_FACT` coming in and one `FROM` going out;
   - the facts read back equal the file's, field by field;
   - the event region is untouched: still 27 days and 161 activities for AK-3.
5. **Also:** add an `--events <file>` argument to `load_events_neo4j.py` (the path is a constant today), so the activities built from K1 version 1 can be loaded: `python -m graphrag.events build --k1 --name E31_events_k1`.

The Cypher for steps 3 and 4 is in the [design, §4](backend-design.md#4-the-graph-in-neo4j-b3).

**Done when:** `MATCH (w:Well {name:'AK-3'})-[:HAS_FACT|HAS_DAY]->() RETURN count(*)` covers both regions, a second load changes nothing, and your 58 recorded plans still replay.

**Know before you start**

- The facts' chunk IDs are the old format (`gdr882_ak3_eowr#c0013`), like your event graph's. They will not match your `chunks` table until Khai's release carries the legacy map, or I rerun the facts on K1 version 1. Report the count of unmatched chunks; do not fail on it yet.
- Three doubtful facts are in the file, and they are mine to fix, not the loader's (Track B log B-F60, B-F62): 13 facts about TG-2 and TG-4, a 68-32 casing size that may be a hole size, and AK-3's "spud to release days" of 3 where the report says 19.

## Task 3: the engine reads the stores (together with me)

**Build:** a way to load `graphrag.lanes.Engine` from the stores instead of files. The backend does not change.

| The engine needs | You provide |
|---|---|
| Passages as `graphrag.data.Chunk` objects, end-of-well and daily kept apart | `read_chunks(release)` from `platform/k1_store.py`. Daily passages are those of daily-report files |
| Activities as `graphrag.events.Event` objects | Your `READ_BACK` query, which already returns those fields in order |
| Facts as records with `well`, `property`, `value`, `unit`, `qualifier`, `context`, `chunk`, `source` | A read-back query on the fact region from Task 2 |
| Search vectors, for questions that name several wells | `chunk_vectors`, filtered by well in SQL |

1. Decide with me where this code lives. `platform/` is not a package (your C-C02), so `graphrag` cannot import it by name. My proposal: a small module `graphrag/stores.py` with the reading functions, which your scripts then use too.
2. I add `Engine.from_stores(...)`; you review the queries.
3. `backend/app.py` picks the stores when `BACKEND_DSN` and the Neo4j address are set, and files otherwise.

**Done when:** `GET /v1/health` says `"source": "stores"` and the same questions give the same answers from the stores as from files.

## Task 4 (B2): one command to load a new release

**Build:** `platform/run_release.py <release folder> [--skip-vectors] [--skip-graphs]`.

| Step | Calls | Stops the run if |
|---|---|---|
| 1. Validate | Khai's validator, as `load_k1.py` does | any validator error |
| 2. Load passages | `load_k1.py` | counts differ from the manifest, or a page does not rebuild |
| 3. Search vectors | `embed_k1.py embed`, then `check` | vectors do not equal passages, or SQL and memory searches disagree |
| 4. Build activities | `python -m graphrag.events build --k1` | a daily-report file gives no activity |
| 5. Load activities | `load_events_neo4j.py --events <file>` | its own read-back or plan replay fails |
| 6. Build facts | `python -m graphrag.tables`, then `python -m graphrag.factgraph` | a relationship points to a missing node |
| 7. Load facts | `load_facts_neo4j.py` from Task 2 | its own counts or read-back fail |
| 8. Record the run | one row in a new `runs` table | never |

- Each step is a function; a failed check exits non-zero and names the step.
- The run record: release name and the digest of its `SHA256SUMS`, the git commit, the embedding model, counts and seconds per step, start and end time. Proposed table: `runs (run_id, release, started_at, finished_at, status, record jsonb)`.
- No AI model is needed for any step. The AI extraction of facts is optional and stays off.

**Done when:** the demo release loads on the server with one command, twice, with the same counts.

## Task 5 (B8): the application on the server, behind a password

**Build:** three services in `platform/docker-compose.yml`, under a profile (`--profile app`) so the stores still start alone.

| Service | Built from | Notes |
|---|---|---|
| `backend` | A new `backend/Dockerfile`: Python 3.12, the lock file without the OCR extras, `backend/requirements.txt` | Runs `uvicorn backend.app:app --host 0.0.0.0 --port 8000`. Reads the database addresses and the model endpoint from the environment |
| `frontend` | `npm run build` in `frontend/`; the `dist/` folder is served by the proxy | No Node at run time |
| `proxy` | Caddy | HTTPS; serves the frontend; forwards `/v1/` to `backend`; asks for one shared user name and password |

- Set `BACKEND_CORS_ORIGINS` to empty on the server: the application and the API share one address there.
- The model is outside the compose file: my desktop over a private network, or a hosted open-weight endpoint, which is allowed because the demo data is public.
- Use `GET /v1/health` for the health check.

**Done when:** one HTTPS address shows the application after the password, and a question asked there appears in the question log.

## Task 6 (B6, B7): can wait

**The question log in PostgreSQL.** Two tables, `questions` and `question_feedback`; the SQL is in the [design, §3](backend-design.md#3-the-question-log-in-postgresql-b6). Then a class with the three methods of `QuestionLog` in `backend/questions.py` (`add_question`, `add_feedback`, `has_question`). Put the SQL in `platform/sql/002_questions.sql` once you have run it; I kept it out because files there run on the database's first start.

**Page images.** At load time, render each PDF page to a PNG at 150 dpi with `pypdfium2` (already in the lock file; not PyMuPDF, which is AGPL). Store as `pages/<file_id>/p<n>.png`. Add a route `GET /v1/files/{file_id}/pages/{n}/image` and fill `image_url` in the page response. Check `file_id` against the loaded files before touching the disk.

## What I need from you

1. The server size confirmed, so the resource request can go to anh Tuấn.
2. When the shared store is up: the address, how to connect, and the release name.
3. Your view on `graphrag/stores.py` (Task 3, step 1).
