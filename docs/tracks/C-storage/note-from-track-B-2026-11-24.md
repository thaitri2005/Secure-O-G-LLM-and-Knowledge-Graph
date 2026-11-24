# Note for Hung: where the backend stands and what is yours next

**From:** Tri (Track B), 24 November 2026 · **Goes with:** the [backend design](backend-design.md), which has the detail · **Plan tasks:** B1 to B8 in the [plan](../../DEVELOPMENT_PLAN.md#7-what-to-do-now)

Thank you for agreeing to the design and the backend role. You asked me to do part of it for now. This says what I did, what I left for you, and what to do first.

## What I did on your behalf

| Task | State | Where |
|---|---|---|
| B4. The API contract | Done | [`backend/openapi.json`](../../../backend/openapi.json), examples in `backend/fixtures/` |
| B5. The API service | Done, **reading files, not your stores** | [`backend/`](../../../backend/README.md), 21 tests |
| B6. The question log | Done as a file | `backend/questions.py` |

I changed nothing in `platform/`. Please read `backend/` when you can: it is your area and I wrote it without you. Change what you would have done differently.

To try it:

```powershell
.venv\Scripts\python -m pip install -r backend/requirements.txt
.venv\Scripts\python -m uvicorn backend.app:app --port 8000      # then http://127.0.0.1:8000/docs
cd frontend; npm install; npm run dev:examples                    # the application, no model needed
```

## What is yours, in order

| Order | Task | Why now | Design |
|---|---|---|---|
| 1 | **B1. Shared hosting** of the stores | Blocks everyone: the engine cannot read the stores, and data still moves through chat | [§1](backend-design.md#1-shared-hosting-b1) |
| 2 | **B3. The well facts in Neo4j** | The file is ready: [`E27_fact_graph.graph.json`](../../../graphrag/results/E27_fact_graph.graph.json), 216 facts of 5 wells | [§4](backend-design.md#4-the-graph-in-neo4j-b3) |
| 3 | **The engine reads the stores**, with me | Turns the application from files to your stores | [§5](backend-design.md#5-the-engine-reads-the-stores-plan-task-e2-with-tri) |
| 4 | **B2. The runner** | One command from Khai's release to a loaded store | [§6](backend-design.md#6-the-runner-b2) |
| 5 | **B8. Compose file and password** | So domain experts can open it | [§8](backend-design.md#8-the-compose-file-and-the-access-gate-b8) |
| 6 | **B6 in PostgreSQL, B7 page images** | Can wait: the log works as a file, and pages show as text | [§3](backend-design.md#3-the-question-log-in-postgresql-b6), [§7](backend-design.md#7-page-images-b7) |

## Four decisions that are yours

1. **Which provider** for the server, and whether teammates reach the databases by SSH tunnel or Tailscale. The [resource request](../../reports/RESOURCE_REQUEST_2026-11-24.md) assumes 4 vCPU and 8 GB from student credits; **please confirm that size** before we send the request to anh Tuấn.
2. **Whether store-reading code moves into a module `graphrag` can import.** `platform/` is not a package on purpose (C-C02), so the engine cannot import from it by name.
3. **Whether the question-log tables suit you.** They are in the design, not in `platform/sql/`, because files there run on the database's first start and I could not run them against PostgreSQL.
4. **Property names in Neo4j.** I kept yours (`Well.name`, `Chunk.chunk_id`) and proposed names for the new labels.

## Things to know before loading the well facts

- **Their chunk IDs are the old format** (`gdr882_ak3_eowr#c0013`), as your event graph's are. They will not match your `chunks` table until they go through the legacy map, or I rerun the facts on a K1 version 1 package.
- **Three doubts in the data,** not for the loader to fix (Track B log B-F60, B-F62): 13 facts are about TG-2 and TG-4, wells the AK-3 report only describes; one 68-32 casing size may be a hole size; and AK-3's "spud to release days" is 3 where the report says 19.
- **`run_plan`'s result text is unchanged.** I split it into `plan_value` and a wrapper; all 154 recorded plans give the same text and events, so your 58-plan replay still passes.

## What I need from you first

When the shared store is up: the address, how to connect, and the release name. Then I point the engine at it and we do step 3 together.
