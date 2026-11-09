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
| Vector store | Open: Neo4j's index, pgvector or Qdrant, chosen with Tri. BM25 stays either way | C-F01 |
| Stores, loader, runner, viewer | Not started | — |
| Next | Review Track A's six `k1_*` schemas; vector store choice; stores for the week-3 dry run | — |

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
