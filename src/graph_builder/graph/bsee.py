"""Link BSEE boreholes to their wells, operators, leases, blocks, fields and former records as a property graph."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any, Iterator

from ..ingestion.sources import sha256, write_json, write_text

# Values that name no real entity: "NOLEASE" is a lease placeholder and "WILD" marks a wildcat
# (exploratory) borehole outside a named field. Linking them would create meaningless hubs.
PLACEHOLDERS = {"lease": {"NOLEASE"}, "field": {"WILD"}}
WELLBORE_PROPERTIES = ("api_well_number", "well_name", "well_name_suffix", "region", "status_code", "status_date",
                       "type_code", "well_class_code", "spud_date", "total_depth_date", "bh_total_md_ft", "tvd_ft",
                       "rkb_elevation_ft", "water_depth_ft", "surface_latitude", "surface_longitude",
                       "coordinate_datum", "withheld")


def block_key(area: str | None, block: str | None) -> str | None:
    """Compare blocks without zero padding: the borehole file writes 0827, the API-change file 827."""
    if not area or not block:
        return None
    return f"{area}-{re.sub(r'^0+(?=.)', '', block)}"


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def build_graph(bundle: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    """Return nodes by ID, edges in input order, and counts of links skipped as placeholders."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()

    def node(node_id: str, label: str, **properties: Any) -> str:
        nodes.setdefault(node_id, {"id": node_id, "label": label, **properties})
        return node_id

    def edge(source: str, relation: str, target: str, record: dict[str, Any]) -> None:
        edges.append({"source": source, "relation": relation, "target": target, "evidence": {
            "record_id": record["record_id"], "file_id": record["source"]["file_id"],
            "sha256": record["source"]["sha256"], "row": record["source"]["row"]}})

    boreholes = list(read_jsonl(bundle / "boreholes.jsonl"))
    for record in boreholes:
        wellbore = node(f"wellbore:{record['api_well_number']}", "Wellbore",
                        **{key: record[key] for key in WELLBORE_PROPERTIES})
        well = node(f"well:{record['well_api10']}", "Well", api10=record["well_api10"])
        edge(well, "HAS_WELLBORE", wellbore, record)
        edge(wellbore, "OPERATED_BY", node(f"operator:{record['operator_number']}", "Operator",
                                           operator_number=record["operator_number"]), record)
        for side in ("surface", "bottom"):
            lease = record[f"{side}_lease_number"]
            if lease in PLACEHOLDERS["lease"]:
                skipped[f"{side}_lease placeholder"] += 1
            elif lease:
                edge(wellbore, f"{side.upper()}_ON_LEASE", node(f"lease:{lease}", "Lease", lease_number=lease), record)
            key = block_key(record[f"{side}_area_code"], record[f"{side}_block_number"])
            if key:
                area, number = key.split("-", 1)
                edge(wellbore, f"{side.upper()}_IN_BLOCK", node(f"block:{key}", "Block", area_code=area,
                                                                block_number=number), record)
        field = record["bottom_field_name_code"]
        if field in PLACEHOLDERS["field"]:
            skipped["field placeholder"] += 1
        elif field:
            edge(wellbore, "BOTTOM_IN_FIELD", node(f"field:{field}", "Field", field_code=field), record)
    for change in read_jsonl(bundle / "api_changes.jsonl"):
        current = f"wellbore:{change['api_well_number']}"
        digits = re.sub(r"\D", "", change["previous_api_number"] or "")
        if current not in nodes:
            skipped["api change to unknown wellbore"] += 1
        elif f"wellbore:{digits}" in nodes and f"wellbore:{digits}" != current:
            edge(current, "RENUMBERED_FROM", f"wellbore:{digits}", change)
        else:
            nodes[current].setdefault("former_api_numbers", [])
            if change["previous_api_number"] not in nodes[current]["former_api_numbers"]:
                nodes[current]["former_api_numbers"].append(change["previous_api_number"])
    return nodes, edges, skipped


def write_graph(output: Path, bundle: Path, nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]],
                skipped: Counter[str]) -> dict[str, Any]:
    write_text(output / "nodes.jsonl", "".join(json.dumps(n, ensure_ascii=False) + "\n" for n in nodes.values()))
    write_text(output / "edges.jsonl", "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in edges))
    summary = {
        "input": {name: sha256(bundle / name) for name in ("boreholes.jsonl", "api_changes.jsonl")},
        "nodes": dict(sorted(Counter(n["label"] for n in nodes.values()).items())),
        "edges": dict(sorted(Counter(e["relation"] for e in edges).items())),
        "skipped_links": dict(sorted(skipped.items())),
        "outputs": {name: sha256(output / name) for name in ("nodes.jsonl", "edges.jsonl")},
    }
    write_json(output / "summary.json", summary)
    return summary


def check_graph(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    errors = [f"edge {e['source']} {e['relation']} {e['target']}: missing endpoint"
              for e in edges if e["source"] not in nodes or e["target"] not in nodes]
    wells = Counter(e["target"] for e in edges if e["relation"] == "HAS_WELLBORE")
    errors += [f"{n['id']}: expected exactly one well" for n in nodes.values()
               if n["label"] == "Wellbore" and wells[n["id"]] != 1]
    return errors


def load_graph(output: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    nodes = {n["id"]: n for n in read_jsonl(output / "nodes.jsonl")}
    return nodes, list(read_jsonl(output / "edges.jsonl"))


def neighbors(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    """Describe one node and its direct links in both directions, grouped by relation."""
    if node_id not in nodes:
        raise ValueError(f"Unknown node {node_id!r}; IDs look like well:1772140041, wellbore:177214004100, "
                         "lease:G01608, block:SP-60, operator:00276, field:SP060")
    linked: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e["source"] == node_id:
            linked[f"{e['relation']} ->"].append(e["target"])
        elif e["target"] == node_id:
            linked[f"<- {e['relation']}"].append(e["source"])
    return {"node": nodes[node_id], "links": {relation: {"count": len(ids), "ids": sorted(set(ids))[:20]}
                                               for relation, ids in sorted(linked.items())}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "show"))
    parser.add_argument("node", nargs="?", help="show: node ID such as well:1772140041 or lease:G01608")
    parser.add_argument("--bundle", type=Path, default=Path("data/processed/local/bsee_wells"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/local/bsee_graph"))
    args = parser.parse_args()
    try:
        if args.command == "show":
            print(json.dumps(neighbors(*load_graph(args.output), args.node or ""), ensure_ascii=False, indent=2))
            return 0
        nodes, edges, skipped = build_graph(args.bundle)
        errors = check_graph(nodes, edges)
        for error in errors[:20]:
            print(f"ERROR {error}")
        if errors:
            print(f"FAIL: {len(errors)} graph errors; no output written")
            return 1
        summary = write_graph(args.output, args.bundle, nodes, edges, skipped)
        print(f"nodes: {summary['nodes']}\nedges: {summary['edges']}\nskipped: {summary['skipped_links']}")
        print(f"PASS: {args.output}")
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
