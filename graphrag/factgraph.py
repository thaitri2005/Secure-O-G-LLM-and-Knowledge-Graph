"""The per-well fact graph as nodes and relationships, for Track C to load into Neo4j (specification §8.5, D-67).

    python -m graphrag.factgraph --facts E20_graph_three_qwen3-4b E27_tables_three --name my_fact_graph
    python -m graphrag.factgraph --map-to data/interim/k1/demo-v2 --name E27_fact_graph_demo-v2

Reads the facts of one or more fact runs (graphrag.tables, graphrag.neo4j_kg), keeps those that pass the strict
checks of graphrag.validate, and writes `graphrag/results/<name>.graph.json`. No model call.

`--map-to` instead moves a recorded fact graph (`--graph`, E27's by default) onto the chunk IDs of a K1 release,
through the release's `legacy_chunk_ids.json` (B-F63). The map pairs chunks by text, so each moved fact is checked
again on its new chunk's text, strictly. A fact whose chunk has no mapping, or fails a check on the new text, keeps
its old ID; the file counts both, by reason.

A fact is a node, not a property on its well: one well can have several values for one property (planned and
actual, two reports that disagree), and each needs its own source. `Chunk` nodes hold only an ID; their text and
page stay in PostgreSQL. Which casing was set in which hole section is not written: no fact states it today.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .baseline import POOLS, RESULTS, pool
from .data import ROOT, document_key, load_chunks
from .retrieval import well_names
from .validate import validate

CASING = {"casing_depth": "depth", "casing_weight": "weight", "casing_grade": "grade"}
RECORDED = RESULTS / "E27_fact_graph.graph.json"
LEGACY_MAP = "legacy_chunk_ids.json"   # written into a K1 release by Track A (graph_builder.corpus.k1_export)


def to_graph(facts: list[dict]) -> dict[str, list[dict]]:
    """Nodes `{label, key, properties}` and relationships `{type, from, to, properties}`, where `from` and `to`
    are `[label, key]`. Both lists are sorted and hold no duplicate, so the same facts always give the same graph.
    A fact that does not name exactly one well is left out."""
    nodes: dict[tuple[str, str], dict] = {}
    links: set[tuple[str, tuple[str, str], tuple[str, str]]] = set()

    def node(label: str, key: str, **properties) -> tuple[str, str]:
        nodes.setdefault((label, key), {}).update(properties)
        return label, key

    for fact in facts:
        wells = sorted(well_names(str(fact.get("well") or "")))
        if len(wells) != 1:
            continue
        name = wells[0]
        well = node("Well", name, name=name)
        document = node("Document", document_key(fact["chunk"]), doc_id=document_key(fact["chunk"]))
        chunk = node("Chunk", fact["chunk"])
        context = json.dumps(fact.get("context") or {}, sort_keys=True)
        value = str(fact["value"])
        item = node("Fact", "|".join([name, fact["property"], fact["qualifier"], context, value]),
                    property=fact["property"], value=value, qualifier=fact["qualifier"], context=context,
                    source="table_mapping" if fact.get("source") else "llm",
                    **({"unit": fact["unit"]} if fact.get("unit") else {}))
        links.update({("HAS_FACT", well, item), ("FROM", item, chunk), ("DESCRIBED_BY", well, document),
                      ("HAS_CHUNK", document, chunk)})
        size = (fact.get("context") or {}).get("casing_size_in")
        if fact["property"] in CASING and size and fact["qualifier"] == "actual":
            casing = node("CasingString", f"{name}|{size}", casing_size_in=str(size), **{CASING[fact["property"]]: value})
            links.add(("HAS_CASING", well, casing))
        if fact["property"] == "hole_size" and fact["qualifier"] == "actual":
            links.add(("HAS_SECTION", well, node("HoleSection", f"{name}|{value}", hole_size_in=value)))
    return {"nodes": [{"label": label, "key": key, "properties": nodes[(label, key)]} for label, key in sorted(nodes)],
            "relationships": [{"type": kind, "from": list(start), "to": list(end), "properties": {}}
                              for kind, start, end in sorted(links)]}


def graph_facts(graph: dict) -> list[dict]:
    """The facts of a fact graph, with the fields `to_graph` took in, so `to_graph(graph_facts(g))` gives `g` back.
    As in graphrag.stores.read_facts, `source` is "table_mapping" or None: the graph keeps no more than that."""
    well = {tuple(r["to"]): r["from"][1] for r in graph["relationships"] if r["type"] == "HAS_FACT"}
    chunk = {tuple(r["from"]): r["to"][1] for r in graph["relationships"] if r["type"] == "FROM"}
    facts = []
    for node in graph["nodes"]:
        if node["label"] != "Fact":
            continue
        p, key = node["properties"], ("Fact", node["key"])
        facts.append({"well": well[key], "property": p["property"], "value": p["value"], "qualifier": p["qualifier"],
                      "context": json.loads(p.get("context") or "{}") or None, "chunk": chunk[key],
                      "source": "table_mapping" if p.get("source") == "table_mapping" else None,
                      **({"unit": p["unit"]} if p.get("unit") else {})})
    return facts


def fact_key(fact: dict) -> tuple:
    return fact["well"], fact["property"], fact["qualifier"], json.dumps(fact.get("context") or {}, sort_keys=True), str(fact["value"])


def map_chunks(facts: list[dict], legacy: dict[str, str], texts: dict[str, str]) -> tuple[list[dict], dict]:
    """Move each fact onto the new chunk ID `legacy` gives its chunk, and check it again, strictly, on `texts` (the
    release's chunk texts by ID). A fact with no mapping, or that fails a check on the new text, keeps its old ID.
    Returns the facts in their order and the counts."""
    moved = [dict(fact, chunk=legacy[fact["chunk"]]) for fact in facts if legacy.get(fact["chunk"])]
    kept, rejected = validate(moved, texts, strict=True)
    passed = {fact_key(fact) for fact in kept}
    out, on_old = [], Counter()
    for fact in facts:
        new = legacy.get(fact["chunk"])
        if new and fact_key(fact) in passed:
            out.append(dict(fact, chunk=new))
        else:
            out.append(fact)
            on_old["no mapping" if not new else "failed a check on the new text"] += 1
    cited = sorted({fact["chunk"] for fact in facts})
    counts = {"llm_calls": 0, "facts": len(facts), "facts_on_new_ids": len(facts) - sum(on_old.values()),
              "facts_on_old_ids": dict(on_old), "checks_failed_on_new_text": rejected,
              "chunks_cited": len(cited), "chunks_mapped": sum(bool(legacy.get(c)) for c in cited),
              "chunks_unmapped": [c for c in cited if not legacy.get(c)]}
    return out, counts


def map_to_release(release: Path, graph_path: Path = RECORDED) -> tuple[dict, dict]:
    """A recorded fact graph moved onto a K1 release's chunk IDs (`map_chunks`), with its counts; no model call."""
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    records = json.loads((release / LEGACY_MAP).read_text(encoding="utf-8"))
    legacy = {r["old_chunk_id"]: r["new_chunk_id"] for r in records if r.get("new_chunk_id")}
    texts = {c.id: c.text for c in load_chunks(path=release / "chunks.jsonl")}
    facts, counts = map_chunks(graph_facts(graph), legacy, texts)
    sums = release / "SHA256SUMS"
    source = {"source_graph": graph_path.name, "release": release.resolve().name,
              "sha256sums_sha256": hashlib.sha256(sums.read_bytes()).hexdigest() if sums.is_file() else None}
    return to_graph(facts), {**source, **counts}


def summarize(graph: dict) -> dict:
    keys = {(n["label"], n["key"]) for n in graph["nodes"]}
    return {"nodes": dict(Counter(n["label"] for n in graph["nodes"])),
            "relationships": dict(Counter(r["type"] for r in graph["relationships"])),
            "dangling": sum(tuple(r["from"]) not in keys or tuple(r["to"]) not in keys for r in graph["relationships"])}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--facts", nargs="+", help="fact run names under graphrag/results/")
    source.add_argument("--map-to", type=Path, metavar="RELEASE", help="a K1 release folder holding legacy_chunk_ids.json")
    parser.add_argument("--graph", type=Path, default=RECORDED, help="with --map-to: the recorded fact graph to move")
    parser.add_argument("--pool", choices=POOLS, default="three", help="the chunks the facts are checked against")
    parser.add_argument("--name", required=True, help="writes graphrag/results/<name>.graph.json")
    args = parser.parse_args(argv)
    if args.map_to:
        graph, counts = map_to_release(args.map_to, args.graph)
        summary = {**counts, **summarize(graph)}
    else:
        raw = [f for name in args.facts for f in json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))["facts"]]
        kept, rejected = validate(raw, {c.id: c.text for c in pool(args.pool)}, strict=True)
        graph = to_graph(kept)
        summary = {"fact_runs": args.facts, "pool": args.pool, "llm_calls": 0, "facts_read": len(raw),
                   "facts_kept": len(kept), "facts_rejected": rejected, **summarize(graph)}
    path = RESULTS / f"{args.name}.graph.json"
    path.write_text(json.dumps({**summary, **graph}, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
