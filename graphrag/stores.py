"""The engine read from the shared stores instead of files (backend design §5, plan task E2).

PostgreSQL holds the K1 chunks (platform/sql/001_k1.sql); Neo4j holds the event region (platform/load_events_neo4j.py)
and the fact region (backend design §4.1). `engine_from_stores` reads all three into the same `Engine` that
`Engine.load` builds from files, so the lanes, the coordinator and the backend do not change.

`platform/` is a folder of scripts, not a package (C-C02), so the readers live here and the scripts can use them.
psycopg and neo4j are imported inside the functions: `import graphrag` still needs only httpx and numpy.

Questions naming several wells are searched per well with BM25 fused with the vector search in PostgreSQL
(`pgvector:<model>`, graphrag.retrieval.PgVector, over `chunk_vectors`, C-C10), when an embedding endpoint answers and
the store holds that model's vector for every chunk of the release; otherwise per well with BM25 alone. The choice is
made once, here, and kept for the engine's life; `Engine.retrieval` gives it, with the vector count, for GET /v1/health.

A limit of the data, not of this module: the stores hold what was loaded. Facts and events cite the chunk IDs their
graph was built on; a citation of a chunk the release does not hold is logged here by count (backend design §4.2),
and shown without its text.
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from .data import Chunk, load_chunks
from .events import WELL, Event
from .lanes import Engine

log = logging.getLogger(__name__)

CHUNKS = "SELECT c.record FROM chunks c JOIN files f USING (file_id) WHERE f.release = %s ORDER BY c.seq"
VECTOR_COUNTS = """
SELECT (SELECT count(*) FROM chunks c JOIN files f USING (file_id) WHERE f.release = %(release)s),
       (SELECT count(*) FROM chunk_vectors v JOIN files f USING (file_id)
        WHERE f.release = %(release)s AND v.embedding_model = %(model)s)
"""

# platform/load_events_neo4j.py's READ_BACK: the fields of `Event`, in the recorded order.
EVENTS = """
MATCH (:Well {name: $well})-[:HAS_DAY]->(d:ReportDay)-[:HAS_EVENT]->(e:Event)-[:HAS_CODE]->(c:ActivityCode)
OPTIONAL MATCH (e)-[:NPT]->(n:NptCode)
OPTIONAL MATCH (e)-[f:FROM]->(ch:Chunk)
WITH d, e, c, n, f, ch ORDER BY e.seq, f.rank
WITH d, e, c, n, collect(ch.chunk_id) AS chunks
RETURN d.date AS date, e.start_time AS start_time, e.end_time AS end_time, e.hours AS hours, e.end_md AS end_md,
       c.code AS code, e.description AS description, chunks, n.code AS npt_code
ORDER BY e.seq
"""

# One row per fact and source chunk: graphrag.factgraph.to_graph gives a fact one FROM per chunk it came from.
# `properties(f)`, not `f.unit`: a graph where no fact has a unit would make Neo4j warn on every read.
FACTS = """
MATCH (w:Well)-[:HAS_FACT]->(f:Fact)-[:FROM]->(c:Chunk)
WHERE $well IS NULL OR w.name = $well
RETURN w.name AS well, properties(f) AS fact, c.chunk_id AS chunk
ORDER BY f.fact_id, c.chunk_id
"""


def releases(cur) -> list[str]:
    cur.execute("SELECT release FROM k1_releases ORDER BY release")
    return [row[0] for row in cur.fetchall()]


def release_of(conn, cur, release: str | None) -> str:
    """The release named, or the store's only one; a release the store does not hold raises."""
    held = releases(cur)
    if release is None and len(held) != 1:
        raise LookupError(f"name a K1 release; the store at {conn.info.host}:{conn.info.port} holds {held or 'none'}")
    if release is not None and release not in held:
        raise LookupError(f"K1 release {release!r} is not in the store; it holds {held or 'none'}")
    return release or held[0]


def read_chunks(dsn: str, release: str | None = None) -> list[dict]:
    """The chunk records of a release, as the package wrote them, in reading order (chunks.seq), as
    platform/k1_store.py reads them. With no release named, the store must hold exactly one."""
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(CHUNKS, (release_of(conn, cur, release),))
        return [row[0] for row in cur.fetchall()]


def vector_counts(dsn: str, model: str, release: str | None = None) -> tuple[int, int]:
    """(chunks of the release, vectors of `model` the store holds for them)."""
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(VECTOR_COUNTS, {"release": release_of(conn, cur, release), "model": model})
        chunks, vectors = cur.fetchone()
        return chunks, vectors


def choose_multi_well_retriever(dsn: str, release: str | None, embed_model: str, embedding_answers: bool) -> tuple[str, int]:
    """The retriever for questions naming several wells, and the vectors the store holds for the release.
    Per-well fusion of BM25 with the SQL vector search when the embedding endpoint answers and every chunk of the
    release has a vector of `embed_model`; per-well BM25 otherwise. Vectors for only part of the release count as
    none, with a warning: a search over part of the release would miss passages and say nothing."""
    chunks, vectors = vector_counts(dsn, embed_model, release)
    if 0 < vectors < chunks:
        log.warning("the store holds %s vectors for %d of the %d chunks of the release; they count as none until "
                    "the release is embedded again (platform/embed_k1.py embed)", embed_model, vectors, chunks)
    if vectors == chunks > 0 and embedding_answers:
        spec = f"perwell:fusion:bm25+pgvector:{embed_model}"
    else:
        spec = "perwell:bm25"
    log.info("questions naming several wells: %s (%d of %d chunks have %s vectors; the embedding endpoint %s)", spec,
             vectors, chunks, embed_model, "answers" if embedding_answers else "does not answer")
    return spec, vectors


def to_chunks(records: list[dict]) -> list[Chunk]:
    """K1 records as `Chunk`s, through `graphrag.data.load_chunks`, so the store and the file give the same chunks
    (the export-and-read of C-C09, in a temporary file)."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder, "chunks.jsonl")
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        return load_chunks(path=path)


def is_daily(doc_id: str) -> bool:
    """A daily-report file, or the non-productive-time report the event graph joins (appx-23), as
    `Engine.load(k1=True)` takes them (graphrag.events.load_k1_inputs, npt_report_inputs)."""
    return "dailyreport" in doc_id or "-appx-23-" in doc_id


def read_events(driver, well: str) -> list[Event]:
    """The well's events from the event region, field by field as the file holds them."""
    records = driver.execute_query(EVENTS, well=well).records
    return [Event(date=r["date"], start=r["start_time"], end=r["end_time"], hours=r["hours"], end_md=r["end_md"],
                  code=r["code"], description=r["description"], chunks=list(r["chunks"]), npt_code=r["npt_code"])
            for r in records]


def read_facts(driver, well: str | None = None) -> list[dict]:
    """The facts of the fact region with the fields graphrag.factgraph took in, so `to_graph(read_facts(driver))`
    gives the loaded graph back. `context` is parsed from its JSON text (`None` when empty). The graph keeps only
    whether a fact came from a table mapping, so `source` is "table_mapping" for those and `None` for extracted ones:
    truthy and falsy, as `to_graph` and the backend read it."""
    records = driver.execute_query(FACTS, well=well).records
    out = []
    for r in records:
        node = r["fact"]
        fact = {"well": r["well"], "property": node["property"], "value": node["value"], "qualifier": node["qualifier"],
                "context": json.loads(node.get("context") or "{}") or None, "chunk": r["chunk"],
                "source": "table_mapping" if node.get("source") == "table_mapping" else None}
        if node.get("unit") is not None:
            fact["unit"] = node["unit"]
        out.append(fact)
    return out


def engine_from_stores(dsn: str, neo4j_uri: str, neo4j_user: str, neo4j_password: str, release: str | None = None,
                       well: str = WELL, embed_model: str | None = None, embedding_answers: bool = False,
                       **settings: Any) -> Engine:
    """An `Engine` on a K1 release in PostgreSQL and the graph in Neo4j. `settings` go to `Engine` as in
    `Engine.load`. A store that does not answer raises: there is no fallback to files. Facts are not validated again:
    the fact graph holds only facts that passed `validate(strict=True)` when it was built (graphrag.factgraph).

    Without a `multi_well_retriever` setting, `choose_multi_well_retriever` picks it from `embed_model` (the embed
    role's model) and `embedding_answers` (whether its endpoint answered at start). A vector retriever is built now,
    so a store or model it cannot use stops the start instead of the first question."""
    from neo4j import GraphDatabase
    chunks = to_chunks(read_chunks(dsn, release))
    stored = 0
    if embed_model and "multi_well_retriever" not in settings:
        settings["multi_well_retriever"], stored = choose_multi_well_retriever(dsn, release, embed_model, embedding_answers)
    elif embed_model:
        stored = vector_counts(dsn, embed_model, release)[1]
    with GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password)) as driver:
        driver.verify_connectivity()
        events = read_events(driver, well)
        facts = read_facts(driver)
    held = {c.id for c in chunks}
    for name, cited in (("facts", {f["chunk"] for f in facts}), ("events", {c for e in events for c in e.chunks})):
        if cited - held:
            log.warning("%d of %d chunks cited by %s are not in the K1 release; they are shown without text",
                        len(cited - held), len(cited), name)
    engine = Engine([c for c in chunks if not is_daily(c.doc_id)], [c for c in chunks if is_daily(c.doc_id)],
                    events, facts, **settings)
    engine.source, engine.vector_store, engine.stored_vectors = "stores", dsn, stored
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        engine.release = release_of(conn, cur, release)
    if "pgvector:" in (engine.multi_well_retriever or ""):
        engine.retriever(engine.multi_well_retriever, "end_of_well")
    return engine
