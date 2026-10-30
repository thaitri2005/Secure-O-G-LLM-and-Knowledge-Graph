"""Guarded projection into the dedicated domain store, using only parameterized data."""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager

from kgbuilder.core.config import ConfigError, KgbError
from kgbuilder.core.contracts import GraphRecord
from kgbuilder.core.domain import DomainLink, read_object, verify_bundle
from kgbuilder.core.project import require_loopback_url
from kgbuilder.core.text import cj, iter_jsonl, sha256_file


class DomainStore:
    """Open a driver lazily so input hashes are checked before any connection."""
    def __init__(self, settings: dict, password: str, driver_factory=None):
        if not password: raise ConfigError("KGB_NEO4J_PASSWORD is required")
        if hasattr(settings, "model_dump"): settings = settings.model_dump()
        try: require_loopback_url(settings["uri"], "neo4j.uri", ("bolt", "neo4j"))
        except ValueError as exc: raise ConfigError("Neo4j URI must be loopback") from exc
        if settings.get("batch_size", 1000) < 1: raise ConfigError("invalid Neo4j batch size")
        self.settings, self.password, self.driver_factory = settings, password, driver_factory
        self.driver = None

    @contextmanager
    def _session(self):
        if self.driver is None:
            factory = self.driver_factory
            if factory is None:
                from neo4j import GraphDatabase
                factory = GraphDatabase.driver
            try:
                self.driver = factory(self.settings["uri"], auth=(self.settings.get("user", "neo4j"), self.password))
            except Exception as exc: raise KgbError(7, "Neo4j connection failed") from exc
        try:
            with self.driver.session(database=self.settings.get("database", "neo4j")) as session:
                yield session
        except KgbError:
            raise
        except Exception as exc:
            raise KgbError(7, "Neo4j domain operation failed") from exc

    def close(self):
        """Release the optional driver's resources."""
        if self.driver is not None: self.driver.close()

    def verify_snapshot(self, bundle_hash: str) -> None:
        """Refuse a missing, duplicate or foreign domain marker before writing."""
        try:
            with self._session() as session:
                rows = list(session.run("MATCH (m:KgbDomainMeta) RETURN m.bundle_sha256 AS hash"))
            if len(rows) != 1 or rows[0]["hash"] != bundle_hash: raise KgbError(7, "domain snapshot marker mismatch")
        except KgbError: raise
        except Exception as exc: raise KgbError(7, "Neo4j domain marker unavailable") from exc

    def audit(self, bundle: Path, bulk: Path) -> dict:
        """Check source hashes, counts and twenty deterministic provenance samples."""
        verify_bundle(bundle)
        manifest = read_object(bulk / "import_manifest.json")
        if manifest["bundle_sha256"] != sha256_file(bundle / "graph.json"): raise ConfigError("bulk bundle hash mismatch")
        for name, row in manifest["files"].items():
            path = (bulk / name).resolve()
            if not path.is_relative_to(bulk.resolve()) or sha256_file(path) != row["sha256"]: raise ConfigError("bulk CSV hash mismatch")
        self.verify_snapshot(manifest["bundle_sha256"])
        expected_nodes = {r["type"]: r["rows"] for r in manifest["files"].values() if r["kind"] == "nodes"}
        expected_edges = {r["type"]: r["rows"] for r in manifest["files"].values() if r["kind"] == "relationships"}
        with self._session() as session:
            nodes = {r["kind"]: r["count"] for r in session.run("MATCH (n) UNWIND labels(n) AS kind WITH kind, count(*) AS count WHERE kind IN $kinds RETURN kind,count", kinds=list(expected_nodes))}
            edges = {r["kind"]: r["count"] for r in session.run("MATCH ()-[r]->() WITH type(r) AS kind, count(*) AS count WHERE kind IN $kinds RETURN kind,count", kinds=list(expected_edges))}
            samples = []
            for row in iter_jsonl(bundle / "nodes.jsonl"):
                samples.append((row["id"], cj(row["sources"])))
                if len(samples) == 20: break
            found = {r["id"]: r["sources"] for r in session.run("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id,n.sources_json AS sources", ids=[r[0] for r in samples])}
        if nodes != expected_nodes or edges != expected_edges or any(found.get(i) != sources for i, sources in samples):
            raise KgbError(7, "domain audit count/provenance mismatch")
        return {"nodes_by_type": nodes, "edges_by_type": edges, "sampled_ids": [r[0] for r in samples], "provenance_verified": len(samples)}

    def attach(self, text_graph: Path, link_bundle: Path) -> dict:
        """MERGE namespaced text occurrences after validating both sidecar hashes."""
        try:
            link = DomainLink.model_validate(read_object(link_bundle / "graph.json"))
            graph = GraphRecord.model_validate(read_object(text_graph))
        except ValueError as exc: raise ConfigError("invalid attachment inputs") from exc
        if link.text_graph_sha256 != sha256_file(text_graph): raise ConfigError("text graph hash differs from links")
        if set(link.files) != {"links.jsonl", "unresolved.jsonl"}: raise ConfigError("link file inventory mismatch")
        for name, digest in link.files.items():
            path = (link_bundle / name).resolve()
            if not path.is_relative_to(link_bundle.resolve()) or sha256_file(path) != digest: raise ConfigError("link data hash mismatch")
        links = list(iter_jsonl(link_bundle / "links.jsonl"))
        docs = {d.doc_id for d in graph.documents}
        statements = {s.statement_id: s for s in graph.statements if s.status == "accepted"}
        for row in links:
            if row["doc_id"] not in docs or (row["type"] == "ABOUT" and row["source"] != row["doc_id"]) or (
                row["type"] == "EXTRACTED_FROM" and (row["source"] not in statements or row["doc_id"] not in {e.doc_id for e in statements[row["source"]].evidence})):
                raise ConfigError("invalid link occurrence")
            if row["type"] not in {"ABOUT", "EXTRACTED_FROM"}: raise ConfigError("unsupported attachment link")
        self.verify_snapshot(link.bundle_sha256)
        namespace = link.text_graph_sha256 + ":" + graph.ablation
        docs_rows = [{"id": namespace + ":doc:" + d.doc_id, "doc_id": d.doc_id} for d in graph.documents]
        facts = [{"id": namespace + ":fact:" + s.statement_id, "statement_id": s.statement_id,
                  "predicate": s.predicate, "payload": cj(s.model_dump())} for s in statements.values()]
        link_rows = [{"id": namespace + ":" + r["id"], "source": namespace + (":doc:" if r["type"] == "ABOUT" else ":fact:") + r["source"],
                      "target": r["target"], "doc_id": r["doc_id"], "kind": r["type"], "rule": r["rule"]} for r in links]
        with self._session() as session:
            targets = list(session.run("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id", ids=sorted({r["target"] for r in links})))
            if {r["id"] for r in targets} != {r["target"] for r in links}: raise KgbError(7, "attachment target missing")
            for query, rows in [
                ("UNWIND $rows AS row MERGE (n:KgbTextDocument {id:row.id}) SET n.doc_id=row.doc_id", docs_rows),
                ("UNWIND $rows AS row MERGE (n:KgbTextFact {id:row.id}) SET n.statement_id=row.statement_id,n.predicate=row.predicate,n.payload=row.payload", facts),
                ("UNWIND $rows AS row MATCH (s {id:row.source}),(t {id:row.target}) MERGE (s)-[r:KGB_DOMAIN_LINK {id:row.id}]->(t) SET r.doc_id=row.doc_id,r.kind=row.kind,r.rule=row.rule", link_rows),
            ]:
                for start in range(0, len(rows), self.settings.get("batch_size", 1000)):
                    session.run(query, rows=rows[start:start + self.settings.get("batch_size", 1000)]).consume()
        return {"namespace": namespace, "documents": len(docs_rows), "facts": len(facts), "links": len(link_rows)}
