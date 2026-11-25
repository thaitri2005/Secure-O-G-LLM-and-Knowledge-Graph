# platform: the stores and the scripts that fill them

Track C's stores (PostgreSQL with pgvector, Neo4j) and the scripts that load a K1 release into them. The scripts are run by path (`python platform/<script>.py`); the folder has no `__init__.py` on purpose, because a package named `platform` would hide Python's own module (Track C log C-C02). Design: [backend design §4 and §6](../docs/tracks/C-storage/backend-design.md).

## Start the stores

```
docker compose -f platform/docker-compose.yml up -d
```

PostgreSQL runs the files in `sql/` on its first start (empty volume only). Every SQL file after `001_k1.sql` is idempotent, so the scripts that need a table apply its file themselves.

## One command: the runner

```
python platform/run_release.py data/interim/k1/demo-v2
python platform/run_release.py <release folder> --skip-vectors        # no embedding server
python platform/run_release.py <release folder> --skip-graphs         # PostgreSQL only
python platform/run_release.py data/interim/k1/demo-v2 --replaces ak3-demo-v1   # first remove the older release of the same files
```

The demo package `demo-v2` (three end-of-well reports, AK-3's daily reports and its non-productive-time report) is built by `python scripts/build_k1_demo_release.py --raw data/raw --models data/interim/ocr_models` ([all the steps](../docs/tracks/B-graphrag/next-runs.md#building-the-demo-package-from-nothing-on-linux)) into the ignored `data/interim/k1/`.

It runs the eight steps below in order, stops at the first failed check with exit code 1 and the step's name, and writes one row to the `runs` table either way. Run twice on the same release, the second run prints whether its counts equal the first's.

| Step | Script it uses | What it does |
|---|---|---|
| 1. Validate | Track A's `graph_builder.corpus.k1_validate` | Refuses a release with any validator error |
| 2. Load chunks | `load_k1.py` | Loads the release into PostgreSQL in one transaction (or keeps it when unchanged); row counts against the manifest, every page rebuilt |
| 3. Embed | `embed_k1.py` | One vector per chunk into `chunk_vectors`; SQL search must equal in-memory search. Needs the embedding server (`local-embed`) |
| 4. Build the event graph | `graphrag.events` | Events from the release's operations tables, no model call. Appendix 23 comes from the release, or else from `--appendices` (a corpus export) |
| 5. Load the event region | `load_events_neo4j.py` | See below |
| 6. Build the fact graph | `graphrag.factgraph` | Starts from the committed `graphrag/results/E32_fact_graph_v2.graph.json` (206 facts of three end-of-well reports: E27's facts, read with a model call, checked again with the rules of Track B log B-F68 and B-F85). `--facts mapped`, the default when the release holds `legacy_chunk_ids.json`: those facts moved onto the release's chunk IDs and checked again on the new text, no model call; a fact whose passage has no pair moves to the one passage on the same page that holds it; one that still cannot move keeps its old ID and is counted (none on `demo-v2`). `--facts recorded`, the default otherwise: the file as it is, on K1 version 0 IDs. `--facts tables`: K2 table mappings on the release, no model call |
| 7. Load the fact region | `load_facts_neo4j.py` | See below |
| 8. Record the run | `sql/003_runs.sql` | Release, its `SHA256SUMS` digest, git commit, embedding model, counts and seconds per step |

Step 2 keeps a release the store already holds with the same `SHA256SUMS` digest and only checks it, so a second run changes nothing and its vectors stay. `--reload` replaces the release anyway; that deletes its vectors (`chunk_vectors` cascades from `chunks`), so after `--reload --skip-vectors` the release has no vectors.

The backend on the stores searches these vectors in SQL for questions naming several wells (`graphrag.retrieval.PgVector`, [backend README](../backend/README.md#what-it-reads-today-and-what-changes)), but only when every chunk of the release has a vector of the embed role's model (`qwen3-embedding-0.6b` in `configs/graphrag/roles.json`); otherwise it uses BM25 alone and logs the counts. After a reload, run step 3 again before starting the backend. What a step decided (kept or loaded, which fact graph) is printed and kept in the run record's `notes`.

## The scripts

| Script | What it does |
|---|---|
| `load_k1.py <release>` | Validates and loads one K1 version 1 release into PostgreSQL, all or nothing (C-C08) |
| `k1_store.py compare <release>` / `export --out <file>` | Reads a release's chunks back from PostgreSQL: equal to the package, or written as a `chunks.jsonl` (C-C09) |
| `embed_k1.py embed` / `check` | Fills `chunk_vectors` from the embedding server, and checks SQL search against search in memory (C-C10) |
| `load_events_neo4j.py [--events F] [--runs F ...] [--well W]` | Loads an event graph under one well in one transaction: read back, recorded plans replayed, Cypher totals against Python; rolls back on a difference (C-C11). Default: `graphrag/results/E28_events.json` with E28's plans; a bare `--runs` replays none |
| `load_facts_neo4j.py [--graph F]` | Loads the fact region in one transaction: counts, every relationship and property read back, one `HAS_FACT` in and one `FROM` out per fact, the event region of its wells unchanged; rolls back on a difference. Loading twice changes nothing |
| `run_release.py <release>` | The runner above |
| `validate_k1.py [chunks.jsonl]` | Checks a K1 version 0 chunk file (C-C02); not part of the runner |
| `checks/k1_constraints.sql` | Checks the K1 tables' constraints in a transaction that is rolled back (C-C06) |

Both Neo4j loaders also look up the chunks whose IDs follow K1 version 1 in PostgreSQL's `chunks`, and report how many are missing without failing (backend design §4.2); they skip that quietly when PostgreSQL cannot be reached.

## Settings

| Variable | Used by | Default (the local compose file) |
|---|---|---|
| `BACKEND_DSN` | `run_release.py`, both Neo4j loaders (chunk check) | `postgresql://kg:platform-dev@127.0.0.1:5434/kg` |
| `NEO4J_URI` | `run_release.py`, both Neo4j loaders | `bolt://127.0.0.1:7687` |
| `NEO4J_USER` | same | `neo4j` |
| `NEO4J_PASSWORD` | same | `platform-dev` |

`load_k1.py`, `k1_store.py` and `embed_k1.py` take `--dsn` instead; the runner passes `BACKEND_DSN` to them.

## Tests

```
python -m unittest discover -s tests -p "test_platform_*.py"
```

Unit tests need no service. Integration tests skip when PostgreSQL or Neo4j cannot be reached; they load a test-only well and a test-only embedding model, and remove only what they created, so the real AK-3 data stays. Tests that rebuild from the K1 release need it under `data/interim/k1/` (or `PLATFORM_K1_RELEASE`) and appendix 23's corpus export (or `PLATFORM_APPENDICES`); otherwise they skip.
