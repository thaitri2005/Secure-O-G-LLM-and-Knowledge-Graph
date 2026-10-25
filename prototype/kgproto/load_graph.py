"""Load the BSEE graph and the AK-3 report chunks into Neo4j."""
from __future__ import annotations

from collections import defaultdict
import json
import time

from neo4j import GraphDatabase

from .config import BSEE_GRAPH, NEO4J_AUTH, NEO4J_URI, PDF_BUNDLE, REPORT_DOC

LABELS = {"well": "Well", "wellbore": "Wellbore", "lease": "Lease", "block": "Block", "operator": "Operator",
          "field": "Field"}
BATCH = 5000


def label_of(node_id: str) -> str:
    return LABELS[node_id.split(":", 1)[0]]


def batches(rows: list, size: int = BATCH):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def reset(session) -> None:
    while session.run("MATCH (n) WITH n LIMIT 20000 DETACH DELETE n RETURN count(n) AS c").single()["c"]:
        pass


def load_bsee(session) -> dict:
    for label in [*LABELS.values(), "Document", "Chunk", "ReportWell", "Claim"]:
        session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
    nodes = defaultdict(list)
    with (BSEE_GRAPH / "nodes.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            node = json.loads(line)
            label = node.pop("label")
            nodes[label].append({k: v for k, v in node.items() if v is not None and v != []})
    for label, rows in nodes.items():
        for batch in batches(rows):
            session.run(f"UNWIND $rows AS r CREATE (n:{label}) SET n = r", rows=batch)
    groups = defaultdict(list)
    with (BSEE_GRAPH / "edges.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            edge = json.loads(line)
            key = (edge["relation"], label_of(edge["source"]), label_of(edge["target"]))
            groups[key].append({"s": edge["source"], "t": edge["target"], **edge["evidence"]})
    for (relation, source, target), rows in groups.items():
        for batch in batches(rows):
            session.run(f"UNWIND $rows AS r MATCH (a:{source} {{id: r.s}}) MATCH (b:{target} {{id: r.t}}) "
                        f"CREATE (a)-[:{relation} {{record_id: r.record_id, file_id: r.file_id, "
                        "sha256: r.sha256, row: r.row}]->(b)", rows=batch)
    # Each wellbore node also carries its own source row, for direct citations.
    session.run("MATCH (:Well)-[r:HAS_WELLBORE]->(w:Wellbore) "
                "CALL (r, w) { SET w.source_file = r.file_id, w.source_row = r.row, w.source_sha256 = r.sha256 } "
                "IN TRANSACTIONS OF 10000 ROWS")
    return {"nodes": {k: len(v) for k, v in nodes.items()}, "edges": {k[0]: len(v) for k, v in groups.items()}}


def load_report(session) -> int:
    meta = json.loads((PDF_BUNDLE / "documents" / f"{REPORT_DOC}.json").read_text(encoding="utf-8"))
    chunks = [c for c in json.loads((PDF_BUNDLE / "gdr_chunks.json").read_text(encoding="utf-8"))
              if c["doc_id"] == REPORT_DOC]
    session.run("CREATE (d:Document {id: $id, title: $title, sha256: $sha, source_url: $url})",
                id=REPORT_DOC, title=meta["title"], sha=meta["sha256"], url=meta.get("source_url", ""))
    session.run("UNWIND $rows AS r MATCH (d:Document {id: $doc}) "
                "CREATE (d)-[:HAS_CHUNK]->(:Chunk {id: r.chunk_id, page: r.page, type: r.type, "
                "section: coalesce(r.section, ''), text: r.text})", rows=chunks, doc=REPORT_DOC)
    return len(chunks)


def main() -> None:
    """Load only the AK-3 report; the prototype focuses on one source. load_bsee is kept for later use."""
    started = time.perf_counter()
    with GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH) as driver, driver.session() as session:
        reset(session)
        for label in ("Document", "Chunk", "ReportWell", "Claim"):
            session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
        counts = {"report_chunks": load_report(session)}
    counts["seconds"] = round(time.perf_counter() - started, 1)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
