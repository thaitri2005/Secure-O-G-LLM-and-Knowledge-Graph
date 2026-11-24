"""Load Track B's per-well fact graph into Neo4j beside the event region, and check it (backend design §4.1, B3).

    python platform/load_facts_neo4j.py                       # graphrag/results/E32_fact_graph.graph.json
    python platform/load_facts_neo4j.py --graph <file.graph.json>

The file is what `python -m graphrag.factgraph` writes: nodes `{label, key, properties}` and relationships
`{type, from: [label, key], to: [label, key]}`. They become (specification §8.5):

    (:Well {name})-[:HAS_FACT]->(:Fact {fact_id, property, value, unit, qualifier, context, source})
    (:Fact)-[:FROM]->(:Chunk {chunk_id, id_format})           the passage the fact was read from
    (:Well)-[:DESCRIBED_BY]->(:Document {file_id, doc_id})-[:HAS_CHUNK]->(:Chunk)
    (:Well)-[:HAS_CASING]->(:CasingString {casing_id, ...})   (:Well)-[:HAS_SECTION]->(:HoleSection {section_id, ...})

`Well` and `Chunk` are the nodes the event region uses too (platform/load_events_neo4j.py), so the two regions meet
on them. `Fact.context` stays JSON text, as in the file.

All in one write transaction, which rolls back if any check fails:
1. clear the fact region (facts, casing strings, hole sections, documents, then chunks left unlinked), leaving
   wells, report days and events alone;
2. merge the nodes, one statement per label, and the relationships, one per type, so a second load changes nothing;
3. read the region back: node counts per label and relationship counts per type equal the file's, every
   relationship and every node's properties equal the file's (so every fact, field by field), and every fact has
   exactly one HAS_FACT in and one FROM out;
4. the event region of the file's wells (days, events and their links) counts the same as before the load.
After the load, chunks with K1 version 1 IDs are looked up in PostgreSQL, as the event loader does (design §4.2).
Connection settings come from NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD and BACKEND_DSN.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from neo4j import GraphDatabase  # noqa: E402

from load_events_neo4j import (DSN, PASSWORD, URI, USER, CheckFailed, create_constraints, k1_chunk_ids,  # noqa: E402
                               missing_in_postgres)

GRAPH = ROOT / "graphrag/results/E32_fact_graph.graph.json"
KEYS = {"Well": "name", "Chunk": "chunk_id", "Document": "file_id", "Fact": "fact_id", "CasingString": "casing_id",
        "HoleSection": "section_id"}
ENDS = {"HAS_FACT": ("Well", "Fact"), "FROM": ("Fact", "Chunk"), "DESCRIBED_BY": ("Well", "Document"),
        "HAS_CHUNK": ("Document", "Chunk"), "HAS_CASING": ("Well", "CasingString"),
        "HAS_SECTION": ("Well", "HoleSection")}
OWN = ("Fact", "CasingString", "HoleSection", "Document")   # labels only this region uses

# `$wells` is null to clear the whole region (a load), or a list to clear only those wells' part (tests).
CLEAR = [
    """MATCH (n) WHERE (n:Fact OR n:CasingString OR n:HoleSection)
         AND ($wells IS NULL OR EXISTS { MATCH (w:Well)-->(n) WHERE w.name IN $wells })
       DETACH DELETE n""",
    "MATCH (w:Well)-[r:DESCRIBED_BY]->(:Document) WHERE $wells IS NULL OR w.name IN $wells DELETE r",
    "MATCH (d:Document) WHERE NOT ()-[:DESCRIBED_BY]->(d) DETACH DELETE d",
    "MATCH (c:Chunk) WHERE NOT (c)--() DELETE c",
]

CHUNK_FORMAT = """CASE WHEN n.key CONTAINS '#' THEN 'corpus export (K1 version 0 style)' ELSE 'K1 version 1' END"""

# The region as it stands: every relationship that starts at one of the file's wells, or at a fact or document
# such a well reaches, with the label and key of both ends.
READ_RELATIONSHIPS = """
MATCH (w:Well)-[r:HAS_FACT|DESCRIBED_BY|HAS_CASING|HAS_SECTION]->(b) WHERE w.name IN $wells
RETURN type(r) AS type, 'Well' AS a_label, w.name AS a_key, head(labels(b)) AS b_label, b[$keys[head(labels(b))]] AS b_key
UNION
MATCH (w:Well)-[:HAS_FACT|DESCRIBED_BY]->(a)-[r:FROM|HAS_CHUNK]->(b:Chunk) WHERE w.name IN $wells
RETURN type(r) AS type, head(labels(a)) AS a_label, a[$keys[head(labels(a))]] AS a_key, 'Chunk' AS b_label,
       b.chunk_id AS b_key
"""

ONE_IN_ONE_OUT = """
MATCH (w:Well)-[:HAS_FACT]->(f:Fact) WHERE w.name IN $wells
WITH DISTINCT f
RETURN f.fact_id AS fact, COUNT { ()-[:HAS_FACT]->(f) } AS ins, COUNT { (f)-[:FROM]->() } AS outs
"""

# The event region of the file's wells (design §4.1: "27 days and 161 events for AK-3"). Other wells are not
# counted, so another loader committing its own well meanwhile cannot fail this load.
EVENT_REGION = """
MATCH (w:Well)-[:HAS_DAY]->(d:ReportDay)-[:HAS_EVENT]->(e:Event) WHERE w.name IN $wells
RETURN count(DISTINCT d) AS days, count(e) AS events, sum(COUNT { (e)-[:FROM]->(:Chunk) }) AS event_sources,
       sum(COUNT { (e)-[:HAS_CODE]->() }) AS has_code, sum(COUNT { (e)-[:NPT]->() }) AS npt
"""


def check_file(graph: dict) -> list[str]:
    """Problems in the file itself, found before anything is written: unknown labels or types, wrong ends,
    duplicates and relationships whose ends are not nodes of the file."""
    problems, keys = [], Counter((n["label"], n["key"]) for n in graph["nodes"])
    problems += [f"unknown label {label}" for label in sorted({n["label"] for n in graph["nodes"]} - set(KEYS))]
    problems += [f"node {node} appears {count} times" for node, count in keys.items() if count > 1]
    links = Counter((r["type"], tuple(r["from"]), tuple(r["to"])) for r in graph["relationships"])
    problems += [f"relationship {link} appears {count} times" for link, count in links.items() if count > 1]
    for kind, start, end in links:
        if ENDS.get(kind) != (start[0], end[0]):
            problems.append(f"relationship {kind} from {start[0]} to {end[0]} is not in the fact region's design")
        elif start not in keys or end not in keys:
            problems.append(f"relationship {kind} {start} -> {end} is dangling")
    return problems


def file_wells(graph: dict) -> list[str]:
    return sorted(n["key"] for n in graph["nodes"] if n["label"] == "Well")


def load_and_check(tx, graph: dict, clear_wells: list[str] | None = None) -> dict:
    """Replace the fact region with the file's graph and check it. `clear_wells` limits the clearing to those
    wells' part of the region, so a test can load its own well beside the real data."""
    wells = file_wells(graph)
    events_before = tx.run(EVENT_REGION, wells=wells).single().data()
    for statement in CLEAR:
        tx.run(statement, wells=clear_wells).consume()

    for label, key in KEYS.items():
        nodes = [{"key": n["key"], "properties": n["properties"]} for n in graph["nodes"] if n["label"] == label]
        on_create = f" ON CREATE SET x.id_format = {CHUNK_FORMAT}" if label == "Chunk" else ""
        tx.run(f"UNWIND $nodes AS n MERGE (x:{label} {{{key}: n.key}}){on_create} SET x += n.properties",
               nodes=nodes).consume()
    for kind, (start, end) in ENDS.items():
        rels = [{"a": r["from"][1], "b": r["to"][1]} for r in graph["relationships"] if r["type"] == kind]
        tx.run(f"UNWIND $rels AS r MATCH (a:{start} {{{KEYS[start]}: r.a}}), (b:{end} {{{KEYS[end]}: r.b}}) "
               f"MERGE (a)-[:{kind}]->(b)", rels=rels).consume()

    problems = []
    stored_links = {(r["type"], (r["a_label"], r["a_key"]), (r["b_label"], r["b_key"]))
                    for r in tx.run(READ_RELATIONSHIPS, wells=wells, keys=KEYS)}
    file_links = {(r["type"], tuple(r["from"]), tuple(r["to"])) for r in graph["relationships"]}
    problems += [f"relationship in Neo4j, not in the file: {link}" for link in sorted(stored_links - file_links)]
    problems += [f"relationship in the file, not in Neo4j: {link}" for link in sorted(file_links - stored_links)]

    stored_nodes = {}
    for label, key in KEYS.items():
        wanted = [n["key"] for n in graph["nodes"] if n["label"] == label]
        for r in tx.run(f"MATCH (x:{label}) WHERE x.{key} IN $keys RETURN x.{key} AS key, properties(x) AS p",
                        keys=wanted):
            stored_nodes[(label, r["key"])] = {k: v for k, v in r["p"].items() if k != key or label not in OWN}
    same_facts = 0
    for n in graph["nodes"]:
        stored = stored_nodes.get((n["label"], n["key"]))
        if stored is None:
            problems.append(f"node {n['label']} {n['key']!r} not in Neo4j")
            continue
        # Region-only nodes must match exactly; Well and Chunk may carry the event region's properties too.
        shown = stored if n["label"] in OWN else {k: stored.get(k) for k in n["properties"]}
        if shown != n["properties"]:
            problems.append(f"node {n['label']} {n['key']!r}: {shown} in Neo4j, {n['properties']} in the file")
        elif n["label"] == "Fact":
            same_facts += 1

    for r in tx.run(ONE_IN_ONE_OUT, wells=wells):
        if (r["ins"], r["outs"]) != (1, 1):
            problems.append(f"fact {r['fact']!r} has {r['ins']} HAS_FACT in and {r['outs']} FROM out")
    events_after = tx.run(EVENT_REGION, wells=wells).single().data()
    if events_after != events_before:
        problems.append(f"event region changed: {events_before} before, {events_after} after")

    region_nodes = {end for _, start, stop in stored_links for end in (start, stop)}
    summary = {"nodes": dict(sorted(Counter(label for label, _ in region_nodes).items())),
               "relationships": dict(sorted(Counter(kind for kind, _, _ in stored_links).items())),
               "facts_same": same_facts, "facts": sum(n["label"] == "Fact" for n in graph["nodes"]),
               "event_region": events_after}
    file_nodes = dict(sorted(Counter(n["label"] for n in graph["nodes"]).items()))
    file_rels = dict(sorted(Counter(r["type"] for r in graph["relationships"]).items()))
    if (summary["nodes"], summary["relationships"]) != (file_nodes, file_rels):
        problems.append(f"counts: Neo4j {summary['nodes']} {summary['relationships']}, file {file_nodes} {file_rels}")
    if problems:
        raise CheckFailed("\n  ".join([f"{len(problems)} problems, load rolled back:"] + problems[:10]))
    return summary


def load(graph_path: Path = GRAPH, uri: str = URI, user: str = USER, password: str = PASSWORD, dsn: str = DSN,
         clear_wells: list[str] | None = None) -> dict:
    """Load one fact graph file and check it; raises CheckFailed on a bad file or, after rolling back, on any
    difference."""
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    problems = check_file(graph)
    if problems:
        raise CheckFailed("\n  ".join([f"{len(problems)} problems in {graph_path.name}, nothing loaded:"] + problems[:10]))
    with GraphDatabase.driver(uri, auth=(user, password), notifications_min_severity="OFF") as driver:
        driver.verify_connectivity()
        create_constraints(driver, list(KEYS.items()))
        with driver.session() as session:
            summary = session.execute_write(load_and_check, graph, clear_wells)
    k1 = k1_chunk_ids(n["key"] for n in graph["nodes"] if n["label"] == "Chunk")
    return {"wells": file_wells(graph), **summary, "k1_chunks": len(k1),
            "k1_chunks_missing_in_postgres": missing_in_postgres(k1, dsn)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--graph", "--facts", dest="graph", type=Path, default=GRAPH,
                        help="a .graph.json written by graphrag.factgraph")
    parser.add_argument("--uri", default=URI)
    parser.add_argument("--user", default=USER)
    parser.add_argument("--password", default=PASSWORD)
    parser.add_argument("--dsn", default=DSN, help="PostgreSQL holding the K1 chunks, for the chunk ID check")
    args = parser.parse_args(argv)

    try:
        s = load(args.graph, args.uri, args.user, args.password, args.dsn)
    except CheckFailed as failure:
        print(failure)
        return 1
    print(f"loaded the fact region of {len(s['wells'])} wells ({', '.join(s['wells'])}) from {args.graph.name}")
    print("nodes: " + ", ".join(f"{label} {count}" for label, count in s["nodes"].items()))
    print("relationships: " + ", ".join(f"{kind} {count}" for kind, count in s["relationships"].items()))
    print(f"read back: {s['facts_same']} / {s['facts']} facts identical to the file, each with one HAS_FACT and one FROM")
    print(f"event region unchanged: {s['event_region']['days']} report days, {s['event_region']['events']} events")
    if s["k1_chunks"]:
        missing = s["k1_chunks_missing_in_postgres"]
        print(f"chunks with K1 version 1 IDs: {s['k1_chunks']}, " + ("PostgreSQL not reachable, not looked up"
              if missing is None else f"{missing} of them missing from PostgreSQL's chunks"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
