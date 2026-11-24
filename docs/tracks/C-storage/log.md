# Track C log

Track C is storage, IDs and the end-to-end run (owner: Hung, from 5 November 2026). Every finding, decision, design choice and experiment of Track C goes here the same day. Entries are never renumbered or deleted. When an entry is replaced, a later entry says so and names it.

| Prefix | Kind | What it records |
|---|---|---|
| **C-F** | Finding | Something learned from reading or from a run, with its source |
| **C-D** | Decision | What we chose, and why |
| **C-C** | Design choice | How a part is built: a schema rule, a setting or an interface |
| **E** | Experiment | A link to the record in [`docs/experiments/`](../../experiments/README.md), plus one line on the outcome |

## Current state

| Topic | Current answer | Entry |
|---|---|---|
| What Track C must build | ID scheme and K1 schema with validators; MinIO, PostgreSQL, the vector store and Neo4j in Docker Compose; loader and run log; runner; viewer ([plan](../../DEVELOPMENT_PLAN.md), [Tri's note](../B-graphrag/note-for-track-C-storage.md)) | C-F01 |
| K1 version 0 | Schema [`k1_chunk.v0.schema.json`](../../../schemas/k1_chunk.v0.schema.json) and checker `platform/validate_k1.py`: 372 of 372 corpus chunks pass | C-C01, C-C02 |
| ID scheme (spec §5.11) | Chosen: §5.11 in the format of Track A's K1 version 1 (`<file_id>:s<n>:c<n>`, D-54). Build the stores on it | C-D02 |
| Vector store | **Decided: pgvector inside PostgreSQL** ([comparison](vector-store.md)); BM25 stays alongside it | C-D03, C-D04 |
| Stores | Drafted: [`platform/docker-compose.yml`](../../../platform/docker-compose.yml) (PostgreSQL with pgvector, Neo4j, optional MinIO) and the K1 tables [`platform/sql/001_k1.sql`](../../../platform/sql/001_k1.sql). Running under Docker on Hung's Mac: the check [`platform/checks/k1_constraints.sql`](../../../platform/checks/k1_constraints.sql) passes 9 of 9 against the Docker PostgreSQL; both images pinned by digest | C-C04 to C-C07 |
| K1 version 1 package | Received from Track A as a zip, kept out of the repository in ignored `data/interim/k1/`: AK-3 EOWR and 4 daily reports, 1,042 chunks; checksums and Track A's validator pass on Hung's Mac. The agreed interface (D-57); no legacy ID map yet | C-F04, C-D04 |
| Loader | [`platform/load_k1.py`](../../../platform/load_k1.py): validates, loads one release in one transaction, reads it back and rebuilds every page from the database. Track A's AK-3 package loaded on Hung's Mac: 1,042 chunks, 174 / 174 pages rebuilt from the database | C-C08, C-F05 |
| Reading the store | [`platform/k1_store.py`](../../../platform/k1_store.py): `read_chunks()` returns a release's chunks as the package wrote them, in order; `export` writes a `chunks.jsonl` that `graphrag` reads. The store equals the package, 1,042 / 1,042 | C-C09, C-F06 |
| Vectors | [`platform/embed_k1.py`](../../../platform/embed_k1.py): 1,042 Qwen3-Embedding-0.6B vectors in pgvector, each with its well and report date; 67 / 67 searches give the same top 5 from SQL as in memory. About 1,170 tokens and 0.5 s per page on Hung's Mac | C-C10, C-F06 |
| Neo4j | [`platform/load_events_neo4j.py`](../../../platform/load_events_neo4j.py): E28's event graph (161 events of AK-3) in Neo4j; read back identical, and 58 / 58 recorded query plans give their recorded results. [`platform/load_facts_neo4j.py`](../../../platform/load_facts_neo4j.py): the fact region (E27 fact graph: 216 facts, 5 wells, 11 casing strings) beside it, read back identical, the event region untouched. Both regions still cite the corpus export's chunk IDs, not K1 version 1's | C-C11, C-F06, C-C12, C-F07 |
| Runner, viewer | Not started. Track B's local UI (B-C32, D-60) is the viewer for now | — |
| Shared hosting | **Interim, not set up yet:** one team machine (proposed: Tri's desktop, Tri to agree) hosts the stores over Tailscale, because there is no budget for a server yet. Passwords come from `platform/.env` (never committed); server scripts and the [runbook](server-runbook.md) are ready for a cloud server when one is found | C-D06, C-C13 |
| Backend API | Read path built by Track B on Hung's behalf: `backend/`, with the contract and example responses for the frontend. It reads files, not the stores. The rest is designed in [backend-design.md](backend-design.md): hosting, the graph in Neo4j, the question log in PostgreSQL, the runner, page images, the compose file | C-D05 |
| Next | Tri's answer on hosting the stores; then the interim setup ([runbook §0](server-runbook.md#0-for-now-a-team-machine-over-tailscale-no-budget-yet)); free server options in parallel (C-D06). Then, in the order of [the note of 24 November](note-from-track-B-2026-11-24.md): the engine reading the stores (with Tri), the runner (B2). ~~The fact region in Neo4j (B3)~~: done on Hung's Mac (C-C12, C-F07); load it again on the shared host | — |

## 2026-11-05

**C-D01 (decision).** Hung takes over Track C from Khai; Khai takes Track A (Track B log B-D27).

## 2026-11-06

**C-F01 (finding).** What Track B needs from Track C, in its order of priority ([note](../B-graphrag/note-for-track-C-storage.md)):

1. Choose the vector store together. BM25 alone serves one-well questions; embeddings are needed only for several wells.
2. Well and report date in the vector payload, because retrieval filters by both.
3. Load the event graph into Neo4j, keeping each event's source chunks; E28 must still give 22/35 and 19/23.
4. A runner that covers both of Track B's paths and writes K4.
5. A viewer that shows the source events of a computed total.

No third-party GraphRAG base was adopted (B-D21), so the stores serve Track B's own code in `graphrag/`.

**C-F02 (finding).** What breaks when chunk IDs change (same note): the gold facts name `<doc_id>#c<nnnn>` chunk IDs (`prototype/gold/ak3_facts.json`, read through `graphrag/data.py`), K4 citations use them, and `graphrag/data.py` and `graphrag/events.py` look for text inside `doc_id` (`dailyreport`, `-appx-`). The daily-report gold names PDF pages instead, so it survives rechunking (B-C19). Any new ID scheme therefore needs a mapping from old IDs to new ones.

**C-F03 (finding).** What the K1 version 0 file holds: `data/processed/gdr_chunks_full.jsonl` has 372 chunks (237 text, 135 table) from three end-of-well reports (AK-3 60, 56-32 200, 68-32 112). Table chunks carry `table_id`, `row_start` and `row_end`; text chunks have them null. Only daily-report chunks (in ignored `data/corpora/`) carry `pages`.

**C-C01 (design choice).** K1 version 0 is today's chunk rows, written down as a schema: [`schemas/k1_chunk.v0.schema.json`](../../../schemas/k1_chunk.v0.schema.json).

- Required: the fields Track B reads (`chunk_id`, `doc_id`, `page`, `type`, `text`, `section`, `table_id`, `row_start`, `row_end`). `pages` is optional.
- Table chunks must have a table ID and row range; text chunks must not.
- Extra fields are allowed, so the corpus output passes unchanged. Version 1 adds the §5.11 IDs, file and page records, and report dates.

**C-C02 (design choice).** `platform/validate_k1.py` checks a chunk file against the schema, then the rules a schema cannot express: unique chunk IDs, chunk and table IDs that start with their `doc_id`, `row_end` not before `row_start`, and `page` equal to the first of `pages`. On the corpus file: 372 checked, 372 passed. Tests: `python -m unittest tests/test_k1_validator.py` (10 tests).

- `platform/` has no `__init__.py` on purpose. A package named `platform` would hide Python's own `platform` module, so the folder holds scripts run by path.
- Daily-report chunks are not checked yet: they sit in ignored `data/corpora/` and need a local regeneration first ([next-runs](../B-graphrag/next-runs.md)).

**C-C03 (design choice; fix by Tri, 8 November).** `doc_id` in the K1 schema now also states `maxLength: 64`, as `tests/test_contracts.py` requires of every non-corpus schema. The pattern already enforced the limit, so no chunk changes: 372 of 372 still pass.

## 2026-11-09

**C-D02 (decision, by Tri, recorded here by Track B).** The ID scheme is §5.11 in the format Track A's K1 version 1 candidate writes ([E30](../../experiments/E30-k1-version-1-candidate.md)): file `f<16 hex of the PDF's SHA-256>`, then `:p<n>`, `:t<n>`, `:s<n>`, `:f<n>` and `<parent>:c<n>`. This replaces drafting a scheme (C-F02's open item). Specification D-54, Track B log B-D28. [`k1_chunk.v0.schema.json`](../../../schemas/k1_chunk.v0.schema.json) still describes version 0, which stays readable; Track A's `k1_*` schemas describe version 1 and are Track C's to review.

**C-D03 (proposed, to decide with Tri).** Vector store: pgvector, inside the PostgreSQL that holds K1. It adds no service, filters by well and report date in the same SQL query, and is rebuilt from the system of record. At a few thousand chunks an exact search needs no approximate index, so a filtered query never drops matches. Neo4j's index is the alternative if retrieval moves next to the fact graph (B-D29). Comparison: [vector-store.md](vector-store.md).

**C-C04 (design choice).** [`platform/docker-compose.yml`](../../../platform/docker-compose.yml) runs PostgreSQL 16 with pgvector (port 5434, because the prototype uses 5433) and Neo4j 5.26 with APOC (the image Track B pins). MinIO is optional (`--profile objectstore`): spec §4.2 allows a plain directory in development, and MinIO's licence and community images are still to be checked. PostgreSQL creates the K1 tables from `platform/sql/` on its first start. The pgvector image is not yet pinned by digest.

**C-C05 (design choice).** [`platform/sql/001_k1.sql`](../../../platform/sql/001_k1.sql) holds K1 version 1 in PostgreSQL:

- One table per K1 record type: `files`, `pages`, `parents`, `k1_tables` (`tables` would shadow the SQL word), `forms`, `chunks`, plus `k1_releases`. Each keeps IDs, links and filter fields as columns and the whole K1 row in `record` (JSONB), so a release loads without loss and the schemas can grow without a migration.
- The database enforces D-54: the file ID equals `f` plus the first 16 hex of the PDF's SHA-256; a page ID is `<file>:p<page>`; a chunk ID is `<parent>:c<child_index>`; every child points to an existing parent and file.
- `chunk_id_map` holds E30's map from version 0 IDs (`<doc_id>#c<nnnn>`), so gold data and old runs still resolve.
- `chunk_vectors` holds 1,024-dimension embeddings per chunk and model, with well and report date copied for filtering (used if C-D03 is accepted).
- Checked on a local PostgreSQL 16 with pgvector 0.6.0: valid rows load, and a wrong file ID, a chunk ID that does not match its child index, and a page ID that does not match its page number are each refused. Deleting a release removes all its rows.

**C-C06 (design choice).** [`platform/checks/k1_constraints.sql`](../../../platform/checks/k1_constraints.sql) checks the K1 tables in one transaction that is rolled back, so it changes nothing. It loads one valid file, page, section and chunk (`f62efbee00767a3e7:s6:c0`), then expects six bad rows to be refused: a file ID that does not match the SHA-256, a page ID that does not match its page, a chunk ID that does not match its child index, a chunk with no parent, a version 0 chunk ID, and a vector that is not 1,024 long. It also traces the chunk back to its file and page, and checks that deleting the release removes its rows. On a local PostgreSQL 16 with pgvector 0.6.0, all nine checks pass. Run it against the Docker database with the command at the top of the file.

**C-C07 (design choice).** The stores run under Docker Compose on Hung's laptop (macOS, Docker Desktop). Against the Docker PostgreSQL, `platform/checks/k1_constraints.sql` passes all nine checks. The PostgreSQL image is now pinned by digest (`pgvector/pgvector:pg16@sha256:0dd3149a…`), as the Neo4j image already was, so every machine runs the same build. MinIO stays unpinned and optional (C-C04).

**C-F04 (finding).** Track A sent a K1 version 1 package as a zip (`ak3-k1-v1-proposed.zip`, dated 8 November, Track A base commit `54d3e23`, which is on `main`). It is kept out of the repository, in ignored `data/interim/k1/ak3-k1v1-proposed/`, because pushed data is hard to remove. On Hung's Mac:

- Contents: 5 files (AK-3 end-of-well report, daily-report appendices 27 to 30), 174 pages, 930 parents, 195 tables, 81 forms, 1,042 chunks (755 text, 206 table, 81 form, per Track A's note). E30 counted 1,040 chunks; the difference is to confirm with Khai.
- All 12 files match `SHA256SUMS`, and Track A's validator passes with page rebuild 174 / 174.
- The release folder must hold only the files `SHA256SUMS` lists: the validator reports any other file, so Track A's `README-share.md` is kept beside the folder, not inside it.
- Status: proposed, not an agreed interface. No `legacy_chunk_ids.json`, so old gold chunk IDs cannot be mapped from this package; asked of Khai. Chunks carry no QA status (a separate sidecar), and end-of-well chunks have no well or date context yet.
- Running Track A's validator needs only four packages, not the full lock file: `docling-core==2.103.1`, `jsonschema==4.26.0`, `pypdf==6.1.1`, `pypdfium2==5.14.0`, with `PYTHONPATH=src`.

**C-C08 (design choice).** [`platform/load_k1.py`](../../../platform/load_k1.py) loads one K1 package into the Track C PostgreSQL, all or nothing:

1. It refuses a package that fails Track A's validator.
2. In one transaction it deletes the release if loaded before, then inserts every record type and the legacy ID map when present.
3. It reads the release back and checks that row counts equal the manifest's and that every page rebuilds from the stored chunks to the package's digest. Any difference rolls the load back.

Two changes to the tables of C-C05 came with it. `chunks.seq` keeps each chunk's line in `chunks.jsonl`, because page rebuild joins chunks in reading order and IDs alone do not give that order. `chunk_id_map` now follows Track A's legacy map: methods `exact`, `near` and `unmapped`, the `jaccard` score, and the release it came with. A database created before these changes must be recreated (`docker compose down -v`, then `up -d`).

Tested on a sample package built with Track A's own test helpers (2 files, 4 pages, 6 chunks, 3 legacy IDs): it loads, loads again in place, rebuilds 4 / 4 pages from the database and maps 2 old IDs exactly and 1 as unmapped. A package with one changed chunk is refused with five named problems. Known limit: two releases that contain the same PDF cannot be loaded side by side (`files.sha256` is unique). The loader needs `psycopg[binary]==3.3.8`.

**C-F05 (finding).** Track A's AK-3 package (C-F04) loads into the Docker PostgreSQL on Hung's Mac with `platform/load_k1.py`, after the database was recreated for C-C08's table changes. Every count matches the manifest (5 files, 174 pages, 930 parents, 195 tables, 81 forms, 1,042 chunks, no legacy map), and all 174 pages rebuild from the stored chunks to the package's digests. The release is recorded with the SHA-256 of its `SHA256SUMS` (starts `e34a87c780d866cd`). This is the week-3 dry run's first link: Track A's package into Track C's store. Next on that path: Track B reads chunks from the store.

**C-D04 (decision, by Tri, recorded here by Track B on 9 November).** C-D03 is accepted: the vector store is pgvector inside the PostgreSQL that holds K1 (specification D-56, Track B log B-D30). Track A's K1 version 1 is also accepted as the team's interface (D-57), so the package in C-F04 is no longer only a proposal.

## 2026-11-10

Before the professor's review on 11 November, Track C stored vectors and loaded Neo4j, as Hung said at the 9 November meeting ([digest](../../requirements/supervisor-meeting-2026-11-09.md)).

**C-C09 (design choice).** [`platform/k1_store.py`](../../../platform/k1_store.py) is how Track B reads the store. `read_chunks(release)` returns the chunk records of one release from `chunks.record`, ordered by `chunks.seq`, so they equal the package's `chunks.jsonl` line for line. `compare <package>` checks that; `export --out <file>` writes the records as a `chunks.jsonl`, which `graphrag` already reads through `GRAPHRAG_K1_CHUNKS` with no code change. JSONB does not keep key order, so the export equals the package as JSON, not byte for byte.

**C-C10 (design choice).** [`platform/embed_k1.py`](../../../platform/embed_k1.py) fills `chunk_vectors` (D-56):

- Qwen3-Embedding-0.6B served by llama.cpp (`--embedding --pooling last`, alias `qwen3-embedding-0.6b`, endpoint `local-embed`), called through `graphrag/client.py`, on the passage text `graphrag.retrieval.Dense` embeds (section heading, then text), normalised to unit length as `Dense` does.
- Each vector keeps its chunk's well and report date. End-of-well chunks carry no well (B-F57), so they take their file's well: the one the file's report context names, or else the well name its text mentions most.
- `embed` replaces one model's vectors for a release in one transaction. `check` compares an exact cosine search in SQL (`<=>`) with numpy on the same stored vectors, for the prototype's 31 questions unfiltered and filtered by well, and for five report dates. It shows that SQL search and filtering agree with search in memory; it does not compare the vectors with ones Track B computes.

**C-C11 (design choice).** [`platform/load_events_neo4j.py`](../../../platform/load_events_neo4j.py) loads Track B's recorded event graph (`graphrag/results/E28_events.json`) into Neo4j, the graph E28 measured. Nodes and relationships:

- `(:Well)-[:HAS_DAY]->(:ReportDay)-[:HAS_EVENT]->(:Event)`, with `(:Event)-[:HAS_CODE]->(:ActivityCode)`, `(:Event)-[:NPT]->(:NptCode)` for non-productive events, and `(:Event)-[:FROM {rank}]->(:Chunk)` for the passages each event was read from.
- A `Chunk` node holds only its ID; text and page stay in PostgreSQL, so Neo4j stays derived (D-06). `Event.seq` keeps the recorded order, which the plan runner relies on for first and last dates.
- One write transaction replaces the well's days and events, reads them back, replays every recorded query plan of the two E28 runs (`E28_graph_fixed_seen`, `E28_heldout_graph`; 58 plans) with `graphrag.events.run_plan`, and computes hours per activity code and the non-productive totals in Cypher. Any difference rolls the load back.
- Limit: the recorded events cite the chunk IDs of the corpus export E28 read (`<doc_id>#c<nnnnn>`), not K1 version 1 IDs, so their `Chunk` nodes do not yet match chunks in PostgreSQL. `Chunk.id_format` names the scheme. Linking needs Track A's legacy map for the daily reports, or the event graph built from K1 version 1 by Track B.

**C-F06 (finding).** On Hung's Mac (Docker PostgreSQL and Neo4j, llama.cpp from Homebrew with Metal), with Track A's AK-3 package (C-F05):

| Check | Result |
|---|---|
| Store against package (`k1_store.py compare`) | 1,042 / 1,042 chunks identical |
| Vectors stored (`embed_k1.py embed`) | 1,042, all with a well (AK-3 for all five files) and 981 with a report date; the 61 without are end-of-well chunks |
| Embedding cost | 66 calls, 203,630 tokens, 91 s: about 1,170 tokens and 0.52 s per page over 174 pages; no hosted call, no money |
| Search from the store (`embed_k1.py check`) | 67 / 67 searches give the same top 5 from pgvector as in memory (31 unfiltered, 31 filtered by well, 5 by report date) |
| Event graph in Neo4j (`load_events_neo4j.py`) | 27 report days, 161 events, 88 source chunks; 161 / 161 events read back identical; 58 / 58 recorded query plans give their recorded results; hours of 30 / 30 activity codes match in Cypher; non-productive time 115 hours in 28 events on 10 days |

Before this run the three scripts were tested in the cloud: `k1_store.py` and `embed_k1.py` on a sample package with a stand-in embedding server, `load_events_neo4j.py` with a stand-in Neo4j transaction, as no Neo4j server could be installed there. Neo4j Browser draws relationships between returned nodes only when its "connect result nodes" setting is on; returning a path (`MATCH p = ... RETURN p`) always draws them.

## 2026-11-24

**C-D05 (decision, by Hung, told to Tri; recorded here by Track B, as C-D02 was).** Hung agrees with the design of the second build ([specification §4.6](../../PROJECT_DESIGN.md#46-second-build-one-connected-application), the graph model of §8.5, D-67) and takes backend and stores. He asked Track B to do part of the backend for now. Track B log B-D39 has the detail.

- **Built by Track B on Hung's behalf:** the read-path API in `backend/` (Track B log B-C44), its contract (`backend/openapi.json`, `backend/fixtures/`) and the question log as a file.
- **Designed for Hung, not built:** [backend-design.md](backend-design.md), covering shared hosting, the question log in PostgreSQL, loading the fact region into Neo4j, the engine reading the stores, the runner, page images, and the compose file with the access gate.
- **Nothing in `platform/` was changed.** The proposed SQL for the question log is in the design, not in `platform/sql/`, because files there run on the database's first start and it has not been run against PostgreSQL.
- Hung has not reviewed this entry or the design; both are his to correct.
- What to do first, in order, is in the [note of 24 November](note-from-track-B-2026-11-24.md): shared hosting, then the well facts in Neo4j, then the engine reading the stores.

**C-C12 (design choice).** [`platform/load_facts_neo4j.py`](../../../platform/load_facts_neo4j.py) loads Track B's fact graph (`graphrag/results/E27_fact_graph.graph.json`, from `python -m graphrag.factgraph`) into Neo4j as the fact region, following [backend-design.md §4.1](backend-design.md#41-the-fact-region). Written with Claude; Hung ran and checked it.

1. Key properties: `Well.name` and `Chunk.chunk_id` as the event loader has them, so the two regions meet on the same nodes; `Document.file_id`, `Fact.fact_id`, `CasingString.casing_id`, `HoleSection.section_id`, each with a uniqueness constraint.
2. One write transaction: delete only `Fact`, `CasingString`, `HoleSection`, `Document` and chunks left with no relationship; then `MERGE` every node and relationship, so a second load changes nothing.
3. Checks, any failure rolls back: counts per label and type equal the file's; every `Fact` has exactly one `HAS_FACT` in and one `FROM` out; facts read back equal the file's field by field; `ReportDay` and `Event` counts are the same before and after.
4. The file has no `HoleSection` nodes or `HAS_SECTION` relationships (no fact states a hole section today), so five relationship types, not the six the note lists. Facts carry no `unit`. The loader handles both if they appear.
5. The Neo4j password comes from `NEO4J_PASSWORD` when set (for the shared server, Task 1), else the local development one.

`load_events_neo4j.py` already had the `--events` argument the note asked for; nothing changed there.

**C-F07 (finding).** On Hung's Mac (Docker Neo4j 5.26, the event graph of C-F06 already loaded):

| Check | Result |
|---|---|
| First load | 5 wells, 3 documents, 38 chunks, 216 facts, 11 casing strings; 216 `HAS_FACT`, 216 `FROM`, 5 `DESCRIBED_BY`, 38 `HAS_CHUNK`, 11 `HAS_CASING`: all equal the file |
| Facts read back | 216 / 216 identical to the file |
| Event region | 27 report days and 161 events before and after |
| Second load | Same counts; nothing changed |
| `MATCH (w:Well {name:'AK-3'})-[:HAS_FACT\|HAS_DAY]->()` | 27 `HAS_DAY` and 66 `HAS_FACT`: both regions |
| Event loader run again afterwards | 161 / 161 events identical, 58 / 58 plans replay; still 216 facts |
| A copy of the file with one `FROM` removed | Refused and rolled back; 216 facts with `FROM` remain |

All 38 fact chunks use the corpus export's IDs (`gdr882_ak3_eowr#c0013`), so none match the `chunks` table in PostgreSQL yet (design §4.2). The data doubts Track B named (B-F60, B-F62: facts about TG-2 and TG-4, a 68-32 casing size that may be a hole size, AK-3's spud-to-release days) are loaded as the file gives them; they are Track B's to fix.

**C-C13 (design choice).** Shared hosting prepared in the repository (plan task B1), written with Claude and checked by Hung:

1. [`platform/docker-compose.yml`](../../../platform/docker-compose.yml) reads `POSTGRES_PASSWORD` and `NEO4J_PASSWORD` from `platform/.env` and refuses to start without them; [`platform/.env.example`](../../../platform/.env.example) lists the names. `.env` is now in `.gitignore`: the repository is public. A laptop whose stores already exist keeps `platform-dev` in its `.env`, because both databases read the password only on their first start.
2. [`platform/server/setup.sh`](../../../platform/server/setup.sh): one-time setup of an Ubuntu 24.04 server (Docker from Docker's apt repository, user `kg` with SSH keys only, no root or password login, firewall open on 22 and 443 only, `/srv` folders). Not yet run on a server.
3. [`platform/server/backup.sh`](../../../platform/server/backup.sh): `pg_dump` in custom format, keeps 7 days. On Hung's Mac it wrote a 5.2 MB dump holding all nine K1 tables, including `chunks` and `chunk_vectors`, and deleted an older file. Neo4j is not backed up: it is derived (D-06) and its loaders rebuild it.
4. [server-runbook.md](server-runbook.md): the steps. The server runs Docker only; loading scripts run on our machines through an SSH tunnel on ports 15434, 17474 and 17687 (local Docker uses the usual ones), so the server needs no Python and no model. This differs from the note of 24 November, which loaded on the server.

**C-D06 (decision, by Hung; Tri still to agree).** There is no budget for a server yet. Until a free one is found, one team machine hosts the stores and the others reach it over Tailscale, a free private network; nothing is opened to the internet ([runbook §0](server-runbook.md#0-for-now-a-team-machine-over-tailscale-no-budget-yet)). Proposed host: Tri's desktop, which is on most often and runs the engine. In parallel: each of us tries the student credits (a card may be asked for), the school is asked for a small virtual machine, and the resource request goes to anh Tuấn with the server size confirmed (4 vCPU, 8 GB). The interim host cannot serve the demo application at any hour; a cloud server is still needed for Task 5.

## 2026-11-24 (later): the loaders, the runner and the deployment files

Built by Track B with Hung's clearance (Track B log B-D41), from the [backend design](backend-design.md), the same afternoon as C-C12, C-C13 and C-D06 above; where the two overlapped, the better version was kept, judged on what it does: the fact loader written here (C-C14, a superset the runner can call); Hung's required passwords (a server cannot start on the public defaults), his backup script (it writes to a temporary file and renames, and was run) and his tunnel ports (they leave local stores running). Hung has not reviewed these entries or the code; both are his to correct. Everything ran on Tri's laptop against the Docker stores of `platform/docker-compose.yml`, not on a server.

**C-C14 (design choice; one fact loader, from two written the same afternoon).** Hung wrote and checked `platform/load_facts_neo4j.py` on his Mac (C-C12, C-F07) while a second one was being written here from the same design. They do the same thing and give the same counts (216 facts, 38 chunks, 3 documents, 11 casing strings, 5 wells). The file now in the repository is the second one, because the runner calls it as a function. **This replaces Hung's file and is his to reverse.**

- **What it adds to C-C12:** `load()` and `check_file()` for the runner; `NEO4J_URI` and `NEO4J_USER` from the environment beside `NEO4J_PASSWORD`; the count of chunks with K1 version 1 IDs missing from PostgreSQL; the event-region check counts the file's wells only, so loading another well at the same time cannot fail it.
- **Kept from C-C12:** `--facts` still names the file (`--graph` is the same option), so the commands in the [server runbook](server-runbook.md) work unchanged.
- **Run here:** loaded twice with the same result; the event region still 27 days and 161 events.

**C-C15 (design choice; the event loader takes its input and its connection from outside).** `platform/load_events_neo4j.py` gains `--events`, `--runs` and `--well`, and reads `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` and `BACKEND_DSN` from the environment; with nothing given it behaves as before. It now reports chunks with K1 version 1 IDs that are missing from PostgreSQL (backend design §4.2), without failing on them.

- **The event region is now loaded from the graph built on K1** (`E31_events_k1.json`): 161 of 161 events read back identical, 58 of 58 recorded plans replay, 83 chunks carry version 1 IDs and none is missing from PostgreSQL. The non-productive report's events still cite old IDs, until the release holds appendix 23 (plan task D1).

**C-C16 (design choice; the runner).** `platform/run_release.py <release>`: the eight steps of backend design §6 as functions, each with its check, and one row in a new `runs` table (`platform/sql/003_runs.sql`). [platform/README.md](../../../platform/README.md) lists the scripts, their order and the environment variables.

| Run on Khai's K1 candidate | Result |
|---|---|
| First run, `--skip-vectors --reload` | 1,040 chunks, 174 of 174 pages rebuilt, 161 events on 27 days, 58 of 58 plans, 216 of 216 facts; a row in `runs` |
| Second run | "counts equal those of the previous run"; the release was kept, nothing changed |
| Without the appendix 23 export | Stops at step 4 and names it; the row says `failed`; neither graph region touched |

- **A release already loaded is kept, not reloaded,** when its `SHA256SUMS` digest matches; `--reload` forces a load. Reloading deleted the release's vectors, so a rerun with `--skip-vectors` would have wiped real vectors on the server.
- **Step 3, embedding, has only run against a stand-in:** this laptop has no embedding server.
- **Step 6 loads the committed fact graph by default** and says so in the output and the run record. A full fact graph needs model extraction on three end-of-well reports. `--facts tables` builds one from the release's tables with no model call; it is unit-tested, not loaded.
- **A softer rule than the design's:** appendix 29, the graphical report, has no operations table and gives no events. The runner fails a daily-report file that has an operations table but no event, and only lists the others. For Hung to confirm.
- **Not changed:** `load_k1.py`, `embed_k1.py`, `k1_store.py`, `validate_k1.py`. Run alone they still default to the local connection string; they take `--dsn`.

**C-C17 (design choice; the question log tables and the run record).** `platform/sql/002_questions.sql` holds the tables of backend design §3, safe to run twice, with `reasoning` among the lanes that can be forced. The class that writes them is in `backend/questions.py` (Track B log B-C50). Both files run by themselves when PostgreSQL first starts on an empty volume; on an existing database, `python -m backend.questions init` and the runner create them.

**C-C18 (design choice; the compose file serves a laptop and a server).** Backend design §1 and §8.

- **The store passwords stay as C-C13 set them:** required, from `platform/.env`. A first version here gave them local defaults; that was dropped for Hung's rule. [`platform/.env.example`](../../../platform/.env.example) lists his variables first, then the application's. The stores still start alone, with the same images and volumes.
- **`--profile app`** adds the backend (built from `backend/Dockerfile`: Python 3.12, a non-root user, only what runs) and the proxy (Caddy with the built frontend, `/v1/` forwarded to the backend, one shared user name and password, automatic HTTPS when a domain is set). Without a password hash the proxy refuses to start.
- **`--profile demo`** adds a stub model server, `scripts/stub_model_server.py`, for trying the stack without a GPU. It is not a model: every answer starts with "[stub model]".
- **The model endpoint is a mounted file,** a server-side copy of `endpoints.json` and `roles.json`; templates for Tri's desktop over a private network and for an open-weight model at OpenRouter are in `deploy/models/`.
- **[deploy/README.md](../../../deploy/README.md) is the runbook:** from a new Ubuntu server to the running application, the model endpoint, starting and checking the application, updating, and troubleshooting. It covers the application only: for the server, the stores, the tunnel and the backup it points to the [server runbook](server-runbook.md) and says that one is right where they differ. A second backup script written here was removed in favour of `platform/server/backup.sh`. `deploy/smoke_test.py` checks a running deployment from outside.
- **Run on Tri's laptop only** (Track B log B-C54). The steps on a real server with a real domain have not been run.
- **CI:** `.github/workflows/ci.yml` runs the engine, backend and stub tests and the frontend's tests and build on each push. It informs; it is not a required check and blocks no one.

**C-F08 (finding; what is still open in the stores).**

- **No vectors on this laptop's store:** `chunk_vectors` is empty, and vector search in SQL is not wired into the engine (Track B log B-C50).
- **Facts and chunks are on two ID schemes** (Track B log B-F63): the fact region cites K1 version 0 chunk IDs, which are not in `chunks`.
- **MinIO is still unpinned and unused;** page images and K1 releases are folders on the server.
