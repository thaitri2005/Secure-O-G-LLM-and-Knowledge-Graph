"""Load Track B's per-well fact graph into Neo4j and check it (plan task B3; design: docs/tracks/C-storage/backend-design.md §4.1).

    python platform/load_facts_neo4j.py                       # graphrag/results/E27_fact_graph.graph.json

The file, written by `python -m graphrag.factgraph`, holds `nodes` ({label, key, properties}) and `relationships`
({type, from: [label, key], to: [label, key]}). This is the fact region of the graph. It meets the event region
(platform/load_events_neo4j.py) on the same `Well` and `Chunk` nodes:

    (:Well {name})-[:HAS_FACT]->(:Fact {fact_id, property, value, qualifier, context, source})-[:FROM]->(:Chunk)
    (:Well)-[:DESCRIBED_BY]->(:Document {file_id, doc_id})-[:HAS_CHUNK]->(:Chunk {chunk_id, id_format})
    (:Well)-[:HAS_CASING]->(:CasingString {casing_id, ...})
    (:Well)-[:HAS_SECTION]->(:HoleSection {section_id, ...})        none in the E27 file

All in one write transaction, which rolls back if any check fails:
1. clear the fact region only (Fact, CasingString, HoleSection, Document, then Chunks left with no relationship);
   Well, ReportDay and Event are never deleted;
2. MERGE every node by its key and every relationship, so a second load changes nothing;
3. check: node and relationship counts equal the file's; every Fact has exactly one HAS_FACT in and one FROM out;
   facts read back equal the file's, field by field; the event region's counts are unchanged.
Needs `neo4j==6.4.1` (Track B's lock file).
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
URI, USER = "bolt://127.0.0.1:7687", "neo4j"                               # platform/docker-compose.yml
PASSWORD = os.environ.get("NEO4J_PASSWORD", "platform-dev")
FACTS = ROOT / "graphrag/results/E27_fact_graph.graph.json"

KEY = {"Well": "name", "Chunk": "chunk_id", "Document": "file_id", "Fact": "fact_id",
       "CasingString": "casing_id", "HoleSection": "section_id"}           # design §4.1; Well and Chunk as the event loader
FACT_REGION = ["Fact", "CasingString", "HoleSection", "Document"]          # labels only this loader owns
REL_TYPES = ["HAS_FACT", "FROM", "DESCRIBED_BY", "HAS_CHUNK", "HAS_CASING", "HAS_SECTION"]

CLEAR = """
MATCH (n) WHERE n:Fact OR n:CasingString OR n:HoleSection OR n:Document
DETACH DELETE n
WITH count(*) AS removed
MATCH (c:Chunk) WHERE NOT (c)--()
DELETE c
"""

EVENT_REGION = """
OPTIONAL MATCH (d:ReportDay) WITH count(d) AS days
OPTIONAL MATCH (e:Event) RETURN days, count(e) AS events
"""

# How many nodes of each label belong to the fact region. Well and Chunk are shared with the event region, so only
# those with a fact-region relationship count.
REGION_COUNTS = {
    "Well": "MATCH (w:Well) WHERE (w)-[:HAS_FACT|DESCRIBED_BY|HAS_CASING|HAS_SECTION]->() RETURN count(w) AS n",
    "Chunk": "MATCH (c:Chunk) WHERE ()-[:HAS_CHUNK]->(c) OR (:Fact)-[:FROM]->(c) RETURN count(c) AS n",
    **{label: f"MATCH (x:{label}) RETURN count(x) AS n" for label in FACT_REGION},
}

FACT_LINKS = """
MATCH (f:Fact)
RETURN count { (:Well)-[:HAS_FACT]->(f) } AS has_fact_in, count { (f)-[:FROM]->(:Chunk) } AS from_out, f.fact_id AS id
"""


class CheckFailed(Exception):
    """Raised inside the transaction so that a failed check rolls the load back."""


def node_statement(label: str) -> str:
    key = KEY[label]
    extra = ""
    if label == "Chunk":                                   # as load_events_neo4j.py sets it
        extra = ("ON CREATE SET x.id_format = CASE WHEN n.key CONTAINS '#' THEN 'corpus export (K1 version 0 style)' "
                 "ELSE 'K1 version 1' END ")
    return f"UNWIND $rows AS n MERGE (x:{label} {{{key}: n.key}}) {extra}SET x += n.properties"


def rel_statement(rel_type: str, from_label: str, to_label: str) -> str:
    return (f"UNWIND $rows AS r MATCH (a:{from_label} {{{KEY[from_label]}: r.from}}), "
            f"(b:{to_label} {{{KEY[to_label]}: r.to}}) MERGE (a)-[:{rel_type}]->(b)")


def load_and_check(tx, graph: dict) -> dict:
    problems: list[str] = []
    events_before = tx.run(EVENT_REGION).single().data()
    tx.run(CLEAR).consume()

    by_label: dict[str, list[dict]] = {}
    for n in graph["nodes"]:
        by_label.setdefault(n["label"], []).append({"key": n["key"], "properties": n["properties"]})
    for label in by_label:
        if label not in KEY:
            raise CheckFailed(f"unknown label {label!r} in the file; add its key property to KEY")
    for label in ["Well", "Chunk", "Document", "Fact", "CasingString", "HoleSection"]:
        if label in by_label:
            tx.run(node_statement(label), rows=by_label[label]).consume()

    by_shape: dict[tuple[str, str, str], list[dict]] = {}
    for r in graph["relationships"]:
        if r["type"] not in REL_TYPES:
            raise CheckFailed(f"unknown relationship type {r['type']!r} in the file")
        shape = (r["type"], r["from"][0], r["to"][0])
        by_shape.setdefault(shape, []).append({"from": r["from"][1], "to": r["to"][1]})
    for (rel_type, from_label, to_label), rows in by_shape.items():
        tx.run(rel_statement(rel_type, from_label, to_label), rows=rows).consume()

    # 1. counts per label and per type
    want_nodes = Counter(n["label"] for n in graph["nodes"])
    got_nodes = {label: tx.run(REGION_COUNTS[label]).single()["n"] for label in KEY}
    for label in KEY:
        if got_nodes[label] != want_nodes.get(label, 0):
            problems.append(f"{label}: {got_nodes[label]} in Neo4j, {want_nodes.get(label, 0)} in the file")
    want_rels = Counter(r["type"] for r in graph["relationships"])
    got_rels = {t: tx.run(f"MATCH ()-[r:{t}]->() WHERE NOT startNode(r):Event RETURN count(r) AS n").single()["n"]
                for t in REL_TYPES}
    for t in REL_TYPES:
        if got_rels[t] != want_rels.get(t, 0):
            problems.append(f"{t}: {got_rels[t]} in Neo4j, {want_rels.get(t, 0)} in the file")

    # 2. every Fact has exactly one HAS_FACT in and one FROM out
    bad = [r["id"] for r in tx.run(FACT_LINKS) if (r["has_fact_in"], r["from_out"]) != (1, 1)]
    if bad:
        problems.append(f"{len(bad)} facts without exactly one HAS_FACT and one FROM, e.g. {bad[0]!r}")

    # 3. facts read back equal the file's, field by field
    stored = {r["id"]: r["props"] for r in tx.run("MATCH (f:Fact) RETURN f.fact_id AS id, properties(f) AS props")}
    same = 0
    for n in by_label.get("Fact", []):
        want = {"fact_id": n["key"], **n["properties"]}
        if stored.get(n["key"]) == want:
            same += 1
        elif len(problems) < 20:
            problems.append(f"fact {n['key']!r}: {stored.get(n['key'])} in Neo4j, {want} in the file")

    # 4. the event region is untouched
    events_after = tx.run(EVENT_REGION).single().data()
    if events_after != events_before:
        problems.append(f"event region changed: {events_before} before, {events_after} after")

    formats = {r["format"]: r["n"] for r in tx.run(
        "MATCH (c:Chunk) WHERE ()-[:HAS_CHUNK]->(c) OR (:Fact)-[:FROM]->(c) "
        "RETURN c.id_format AS format, count(c) AS n")}
    if problems:
        raise CheckFailed("\n  ".join([f"{len(problems)} problems, load rolled back:"] + problems[:20]))
    return {"nodes": got_nodes, "rels": got_rels, "facts_same": same, "facts": len(by_label.get("Fact", [])),
            "events": events_after, "formats": formats}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--facts", type=Path, default=FACTS, help=f"fact graph file (default: {FACTS.name})")
    parser.add_argument("--uri", default=URI)
    parser.add_argument("--user", default=USER)
    parser.add_argument("--password", default=PASSWORD, help="default: $NEO4J_PASSWORD, else the local dev password")
    args = parser.parse_args(argv)

    graph = json.loads(args.facts.read_text(encoding="utf-8"))
    if graph.get("dangling"):
        print(f"refused: the file has {graph['dangling']} relationships pointing to missing nodes")
        return 1
    # Warnings off: HAS_SECTION and HoleSection are checked even when the file has none, and Neo4j warns about them.
    with GraphDatabase.driver(args.uri, auth=(args.user, args.password), notifications_min_severity="OFF") as driver:
        driver.verify_connectivity()
        for label, key in KEY.items():
            driver.execute_query(f"CREATE CONSTRAINT {label.lower()}_{key} IF NOT EXISTS "
                                 f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")
        with driver.session() as session:
            try:
                s = session.execute_write(load_and_check, graph)
            except CheckFailed as failure:
                print(failure)
                return 1
    print(f"loaded {args.facts.name}: " + ", ".join(f"{n} {label}" for label, n in s["nodes"].items() if n))
    print("relationships: " + ", ".join(f"{n} {t}" for t, n in s["rels"].items() if n))
    print(f"read back: {s['facts_same']} / {s['facts']} facts identical to the file")
    print(f"event region unchanged: {s['events']['days']} report days, {s['events']['events']} events")
    print("fact chunks by ID format: " + ", ".join(f"{n} {f}" for f, n in s["formats"].items())
          + " (K1 version 0 IDs do not match PostgreSQL's chunks table yet; design §4.2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
