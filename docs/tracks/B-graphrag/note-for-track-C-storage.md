# Note for Hung (Track C): what Track B needs from storage and the runner

From Tri, Track B, 5 November 2026. Full status: [specification §8.4](../../PROJECT_DESIGN.md#84-what-the-first-build-runs-today) and the [track log](log.md).

Track B's experiments changed some assumptions in the Track C plan. No third-party GraphRAG base was adopted, so there is no base to fit the stores around (B-D21). What runs today is our own code in [`graphrag/`](../../../graphrag/README.md).

## What runs today

| Question type | Path | Stored where today |
|---|---|---|
| One well | BM25, filtered by well and, on daily reports, by date | In memory, rebuilt from the chunk files |
| Several wells | BM25 and embeddings (Qwen3-Embedding-0.6B) fused per well | In memory |
| Totals over time on daily reports | Event graph ([E28](../../experiments/E28-event-graph.md)): well → report date → event → activity code and non-productive code | In memory, not in Neo4j |
| Optional: per-well fact sheet | Facts from K2 table mappings and extraction | Optional (B-D24), so it does not need a store now |

The questions behind these results are simulated and not expert-reviewed. The supervisor has yet to confirm the event graph or say whether users ask questions over time (B-D26), so keep it easy to leave out of the run.

## What we need

| Priority | Need | Why |
|---|---|---|
| 1 | **Choose the vector store together** | BM25 alone serves one-well questions, and embeddings are needed only for several wells. BM25 has to stay either way, in the store or in our code |
| 2 | **Well and report date in the vector payload** | Retrieval is filtered by both. Each document's well names stand in for registry IDs (`WellRouter`), and `page_dates` guesses each page's date until K1 version 1 has the field. Registry linking is not in the first build, so plain well names are enough for now |
| 3 | **Load the event graph into Neo4j**, keeping each event's source chunks | Answers cite those chunks. Rerun E28 afterwards and expect the same results: 22/35 and 19/23 |
| 4 | **A runner with both paths** | It runs the parser, builds the indexes and the event graph, answers, and writes K4 |
| 5 | **A viewer that shows computed answers** | A total is written in no passage, so the citation check cannot confirm it (E28). Show the source events (`how: event_graph` in K4) beside the answer |

E28's win is for structured events, and it says nothing about graph databases: the graph has no traversal beyond its links. Loading it into Neo4j fits the direction and the viewer, but do not report it as a gain until it is measured.

## What you can start from

- **K4 version 0.1 already exists:** [`schemas/k4_answer_record.schema.json`](../../../schemas/k4_answer_record.schema.json), written by `python -m graphrag.k4 <run>` (B-C18). Please load it rather than write another; ask us for a new version if a field is missing.
- **Run costs:** K4 has each answer's calls, tokens, seconds and cost. Index-time cost is in the run's result file and the experiment record, so the run log needs both.
- **Neo4j:** `configs/graphrag/docker-compose.yml` runs Neo4j 5.26 with APOC. It shares ports with the prototype's compose file, so run one at a time. APOC was added for neo4j-graphrag's writer, which we did not adopt, so the event graph may not need it.
- **Model endpoints:** `configs/graphrag/endpoints.json`. Go through `graphrag/client.py`, which has the cache, the cost ledger and the check that refuses private data on hosted endpoints.

## What will break when IDs change

These depend on today's IDs, so please tell us before the §5.11 IDs land. Track B will update its side.

| Depends on | Where | What it does |
|---|---|---|
| `<doc_id>#c<nnnn>` chunk IDs | `prototype/gold/ak3_facts.json` through `graphrag/data.py`, K4 citations | Gold facts name chunks, so rechunking needs a mapping from old IDs to new ones |
| Text inside `doc_id` | `graphrag/data.py`, `graphrag/events.py` | Finds daily reports by `dailyreport`, the non-productive-time report by `-appx-23-`, and appendix numbers by `-appx-` |
| Chunk fields `chunk_id`, `doc_id`, `page`, `pages`, `type`, `section`, `text`, `table_id`, `row_start`, `row_end` | `graphrag/data.py` | The loader for every run |
| One well in code | `WELL = "AK-3"` in `graphrag/events.py` | The event graph covers AK-3 only, so the runner cannot yet build it for another well |

The daily-report gold names PDF pages instead of chunks, so it survives rechunking (B-C19). That may be a useful pattern for your page-rebuild check.

## How to run and measure

- Commands: [next-runs.md](next-runs.md) and [`graphrag/README.md`](../../../graphrag/README.md).
- **Run one request at a time for measurements.** Parallel requests to llama.cpp make results non-repeatable (B-F19). Record the server settings with each run.
- Answers need a GPU: the old laptop proved too slow (B-F16), and Tri's desktop runs them. Your loader and stores do not need one. OpenRouter is an option for public data.
- The first check of a load is a known score: BM25 hit@5 of 1.00 and about 28/31 on the prototype's questions, as in `CLAUDE.md`.

Tell us when the stores can take K1 version 0, and Track B will run on them.
