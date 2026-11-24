"""The per-well fact graph as nodes and relationships, for Track C to load into Neo4j (specification §8.5, D-67).

    python -m graphrag.factgraph --facts E20_graph_three_qwen3-4b E27_tables_three --name my_fact_graph

Reads the facts of one or more fact runs (graphrag.tables, graphrag.neo4j_kg), keeps those that pass the strict
checks of graphrag.validate, and writes `graphrag/results/<name>.graph.json`. No model call.

A fact is a node, not a property on its well: one well can have several values for one property (planned and
actual, two reports that disagree), and each needs its own source. `Chunk` nodes hold only an ID; their text and
page stay in PostgreSQL. Which casing was set in which hole section is not written: no fact states it today.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from .baseline import POOLS, RESULTS, pool
from .data import ROOT, document_key
from .retrieval import well_names
from .validate import validate

CASING = {"casing_depth": "depth", "casing_weight": "weight", "casing_grade": "grade"}


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--facts", nargs="+", required=True, help="fact run names under graphrag/results/")
    parser.add_argument("--pool", choices=POOLS, default="three", help="the chunks the facts are checked against")
    parser.add_argument("--name", required=True, help="writes graphrag/results/<name>.graph.json")
    args = parser.parse_args(argv)
    raw = [f for name in args.facts for f in json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))["facts"]]
    kept, rejected = validate(raw, {c.id: c.text for c in pool(args.pool)}, strict=True)
    graph = to_graph(kept)
    keys = {(n["label"], n["key"]) for n in graph["nodes"]}
    dangling = sum(tuple(r["from"]) not in keys or tuple(r["to"]) not in keys for r in graph["relationships"])
    summary = {"fact_runs": args.facts, "pool": args.pool, "llm_calls": 0, "facts_read": len(raw), "facts_kept": len(kept),
               "facts_rejected": rejected, "nodes": dict(Counter(n["label"] for n in graph["nodes"])),
               "relationships": dict(Counter(r["type"] for r in graph["relationships"])), "dangling": dangling}
    path = RESULTS / f"{args.name}.graph.json"
    path.write_text(json.dumps({**summary, **graph}, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
