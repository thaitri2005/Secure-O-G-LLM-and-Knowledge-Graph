"""Build parameterized Cypher and project graph.json into optional Neo4j storage."""
from __future__ import annotations

import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import date

from kgbuilder.core.config import ConfigError, KgbError
from kgbuilder.core.contracts import GraphRecord, Mention, dump
from kgbuilder.core.text import TIME_ISO, match_key, pad


def rel_type(predicate: str) -> str:
    """Sanitize a predicate into the only interpolated Cypher identifier."""
    t = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", predicate)
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").upper()
    return t if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", t) else "RELATED_TO"


def make_run_id(record: GraphRecord, graph_sha256: str) -> str:
    """Identify the exact graph projection, independently of its location."""
    return f"{record.run_name}/{record.ablation}/{graph_sha256[:12]}"


def build_queries(record: GraphRecord, mentions: list[Mention], run_id: str,
                  batch_size: int) -> list[tuple[str, dict]]:
    """Build deterministic upserts with all data carried by parameters."""
    if batch_size < 1:
        raise ConfigError("neo4j.batch_size: must be positive")
    queries = []

    def batches(query, rows):
        for start in range(0, len(rows), batch_size):
            queries.append((query, {"rows": rows[start:start + batch_size]}))

    batches("UNWIND $rows AS row MERGE (d:Document {doc_id: row.doc_id}) SET d += row.props",
            [{"doc_id": d.doc_id, "props": {k: v for k, v in dump(d).items()
                                           if k not in {"doc_id", "text"} and v is not None}}
             for d in sorted(record.documents, key=lambda d: d.doc_id)])
    batches("UNWIND $rows AS row MERGE (c:Chunk {chunk_id: row.chunk_id}) SET c += row.props "
            "WITH c, row MATCH (d:Document {doc_id: row.doc_id}) MERGE (d)-[:HAS_CHUNK]->(c)",
            [{"chunk_id": c.chunk_id, "doc_id": c.doc_id,
              "props": {k: v for k, v in dump(c).items() if k != "chunk_id"}}
             for c in sorted(record.chunks, key=lambda c: c.chunk_id)])
    batches("UNWIND $rows AS row MERGE (e:Entity {entity_id: row.entity_id}) SET e += row.props",
            [{"entity_id": e.entity_id,
              "props": {"name": e.name, "aliases": e.aliases, "kind": e.kind, "resolver": e.resolver,
                        "keys": sorted({match_key(e.name)} | {match_key(a) for a in e.aliases})}}
             for e in sorted(record.entities, key=lambda e: e.entity_id)])
    by_mention = {m.mention_id: m for m in mentions}
    batches("UNWIND $rows AS row MATCH (c:Chunk {chunk_id: row.chunk_id}), "
            "(e:Entity {entity_id: row.entity_id}) MERGE (c)-[m:MENTIONS]->(e) SET m.surface = row.surface",
            [{"chunk_id": by_mention[mid].chunk_id, "entity_id": e.entity_id,
              "surface": by_mention[mid].surface}
             for e in sorted(record.entities, key=lambda e: e.entity_id)
             for mid in sorted(e.mention_ids) if mid in by_mention])
    relations = defaultdict(list)
    for st in sorted(record.statements, key=lambda st: st.statement_id):
        if st.status != "accepted":
            continue
        props = {"statement_id": st.statement_id, "predicate": st.predicate,
                 "predicate_source": st.predicate_source, "source_doc_id": st.source_doc_id,
                 "evidence_span": st.evidence_span.span, "evidence_text": st.evidence_span.text,
                 "evidence_chunk_ids": sorted({e.chunk_id for e in st.evidence}),
                 "support_count": st.support_count, "confidence": st.confidence,
                 "extractor_version": st.extractor_version}
        for field in ("valid_from", "valid_to"):
            value = getattr(st, field)
            if value is not None:
                props[field] = date.fromisoformat(pad(value))
                props[field + "_text"] = value
        relations[rel_type(st.predicate)].append({"subject_id": st.subject_id, "object_id": st.object_id,
                                                "statement_id": st.statement_id, "props": props})
    for kind in sorted(relations):
        batches("UNWIND $rows AS row MATCH (s:Entity {entity_id: row.subject_id}), "
                "(o:Entity {entity_id: row.object_id}) "
                f"MERGE (s)-[r:`{kind}` {{statement_id: row.statement_id}}]->(o) SET r += row.props",
                relations[kind])
    queries.append(("MERGE (m:KgbMeta {key: 'run'}) "
                    "SET m.run_id = $run_id, m.format = $format, m.loaded_at = datetime()",
                    {"run_id": run_id, "format": record.format}))
    return queries


def demo_queries(predicate: str) -> list[tuple[str, str]]:
    """Return alias, half-open temporal, provenance and entity-path Cypher."""
    return [
        ("alias", "MATCH (e:Entity) WHERE $qkey IN e.keys RETURN e.entity_id, e.name, e.aliases"),
        ("temporal", "MATCH (p:Entity) WHERE $skey IN p.keys "
         f"MATCH (p)-[r:`{rel_type(predicate)}`]->(org:Entity) "
         "WHERE (r.valid_from IS NULL OR r.valid_from <= date($at)) "
         "AND (r.valid_to IS NULL OR date($at) < r.valid_to) "
         "RETURN org.name, r.valid_from_text, r.valid_to_text, r.evidence_text"),
        ("provenance", "MATCH (s:Entity)-[r]->(o:Entity) WHERE r.statement_id = $sid "
         "MATCH (d:Document {doc_id: r.source_doc_id}) "
         "OPTIONAL MATCH (c:Chunk) WHERE c.chunk_id IN r.evidence_chunk_ids "
         "RETURN s.name, r.predicate, o.name, r.evidence_span, r.evidence_text, r.support_count, "
         "r.extractor_version, d.title, collect(c.text) AS chunk_texts"),
        ("path", "MATCH (a:Entity) WHERE $from_key IN a.keys "
         "MATCH (b:Entity) WHERE $to_key IN b.keys "
         "MATCH p = shortestPath((a)-[*..3]-(b)) WHERE all(n IN nodes(p) WHERE n:Entity) "
         "RETURN [n IN nodes(p) | n.name] AS hops, [r IN relationships(p) | r.predicate] AS predicates"),
    ]


def demo_params(alias_text: str, subject: str, at: str, statement_id: str | None,
                src: str, dst: str) -> dict:
    """Normalize lookup parameters without embedding values into query text."""
    if not TIME_ISO.fullmatch(at):
        raise ConfigError("at: expected YYYY, YYYY-MM or YYYY-MM-DD")
    try:
        date.fromisoformat(pad(at))
    except ValueError as exc:
        raise ConfigError(f"at: invalid date {at}") from exc
    return {"qkey": match_key(alias_text), "skey": match_key(subject), "at": pad(at),
            "sid": statement_id, "from_key": match_key(src), "to_key": match_key(dst)}


class Neo4jGraphStore:
    """Optional driver wrapper; injected drivers make all store tests offline."""

    def __init__(self, uri: str, user: str, password: str, database: str, batch_size: int, driver=None):
        self.uri, self.database, self.batch_size = uri, database, batch_size
        if driver is None:
            from neo4j import GraphDatabase
            from neo4j.exceptions import DriverError, Neo4jError
            try:
                driver = GraphDatabase.driver(uri, auth=(user, password))
            except (Neo4jError, DriverError, OSError) as exc:
                raise self._unavailable() from exc
        self.driver = driver

    def _unavailable(self) -> KgbError:
        return KgbError(7, f"Neo4j không chạy ở {self.uri}; xem README (Neo4j (tùy chọn))")

    def verify(self) -> None:
        """Fail with the optional-store exit code when connectivity is unavailable."""
        from neo4j.exceptions import DriverError, Neo4jError
        try:
            self.driver.verify_connectivity()
        except (Neo4jError, DriverError, OSError) as exc:
            raise self._unavailable() from exc

    @contextmanager
    def _session(self):
        from neo4j.exceptions import DriverError, Neo4jError
        try:
            with self.driver.session(database=self.database) as session:
                yield session
        except (Neo4jError, DriverError, OSError) as exc:
            raise KgbError(7, f"Neo4j query failed at {self.uri}; xem README (Neo4j (tùy chọn))") from exc

    def load(self, record: GraphRecord, mentions: list[Mention], graph_sha256: str, wipe: bool) -> dict:
        """Guard run identity before any writes, then upsert and return counts."""
        run_id = make_run_id(record, graph_sha256)
        queries = build_queries(record, mentions, run_id, self.batch_size)
        with self._session() as session:
            current = session.run("MATCH (m:KgbMeta {key:'run'}) RETURN m.run_id AS run_id").single()
            if current and current["run_id"] is not None and current["run_id"] != run_id and not wipe:
                raise KgbError(7, "Neo4j contains a different run; use --wipe to replace it")
            if wipe:
                session.run("MATCH (n) WHERE n:Entity OR n:Document OR n:Chunk OR n:KgbMeta "
                            "CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 1000 ROWS").consume()
            for query in [
                "CREATE CONSTRAINT kgb_entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE",
                "CREATE CONSTRAINT kgb_doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
                "CREATE CONSTRAINT kgb_chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
                "CREATE INDEX kgb_entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)",
            ]:
                session.run(query).consume()
            for query, params in queries:
                session.execute_write(lambda tx, q, p: tx.run(q, **p).consume(), query, params)
            nodes = {r["label"]: r["n"] for r in session.run(
                "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n")}
            relationships = {r["type"]: r["n"] for r in session.run(
                "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n")}
            return {"nodes": nodes, "relationships": relationships}

    def demo(self, predicate: str, params: dict) -> dict[str, list[dict]]:
        """Run the four parameterized demonstrations without touching the graph."""
        with self._session() as session:
            return {name: ([] if name == "provenance" and params["sid"] is None else
                           [dict(row) for row in session.run(query, **params)])
                    for name, query in demo_queries(predicate)}

    def close(self) -> None:
        """Release driver resources."""
        from neo4j.exceptions import DriverError, Neo4jError
        try:
            self.driver.close()
        except (Neo4jError, DriverError, OSError) as exc:
            raise self._unavailable() from exc
