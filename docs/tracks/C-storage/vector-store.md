# Vector store: which one (proposal for C-D03)

**Proposal: pgvector, inside the PostgreSQL that already holds K1.** To be decided by Hung and Tri; nothing depends on it yet.

## What the vector store must do

From Track B's [note to Track C](../B-graphrag/note-for-track-C-storage.md) and spec §4.2:

1. One vector per child chunk, from Qwen3-Embedding-0.6B (1,024 dimensions), with the chunk's IDs.
2. **Filter by well and report date** in the same query, because retrieval is routed by both (E18, E27).
3. Sit next to BM25, which stays: BM25 alone serves one-well questions; embeddings matter for several wells (E26).
4. Be rebuildable from PostgreSQL and the pinned embedding model (spec §4.2: derived, not a system of record).
5. Scale today: about 1,040 chunks for AK-3 (E30), a few thousand for 5 to 10 reports (M3).

## The three options

| | pgvector (in PostgreSQL) | Qdrant | Neo4j vector index |
|---|---|---|---|
| Extra service | **None**: PostgreSQL is already in the design | One more container | None: Neo4j is already in the design |
| Filter by well and date | **SQL `WHERE` in the same query**; exact search needs no index at our scale | Payload filters, built for this | The index returns the top k first; filters apply afterwards, so a filtered query can return too few results |
| Join with chunks, pages, files | **Same database: one query** | Separate store; IDs in the payload | Same graph as the event and fact graphs |
| Rebuild from PostgreSQL | Simplest: same database | A reload step | A reload step |
| Scale ceiling | Millions of rows with an HNSW index; far above ours | Higher | High |
| What we would learn | SQL, which the rest of Track C uses anyway | A new API | Cypher, which the event graph needs anyway |

## Why pgvector

- It adds no service and keeps vectors next to the records they describe; a chunk, its page and its vector come back in one query.
- Filtering by well and date is exact: with a few thousand chunks, an exact search (no approximate index) takes milliseconds and never drops a filtered match. An HNSW index can be added later if the corpus grows.
- It is the easiest to rebuild and to back up, because it lives in the system of record.

**What it costs:** no built-in hybrid search; BM25 stays in `graphrag/retrieval.py` and fusion stays in code, as today. If Track B later moves retrieval into Neo4j for the fact graph (B-D29), Neo4j's index is the alternative; Qdrant is worth it only at a scale we do not have.

## Draft table

`chunk_vectors` in [`platform/sql/001_k1.sql`](../../../platform/sql/001_k1.sql): one row per chunk and embedding model, with `file_id`, `document_type`, `well` and `report_date` copied from the chunk for filtering.

## To decide with Tri

1. pgvector, or Neo4j's index because of the fact graph?
2. Does `graphrag/retrieval.py` read vectors from the store, or keep computing them in memory for the dry run?
