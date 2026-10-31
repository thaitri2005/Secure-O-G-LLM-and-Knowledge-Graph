"""K2, the thin ontology slice (D-49): glossary generation from the reports' tables, and rendering for extractors.

    python -m graphrag.ontology glossary   # fills K2's glossary from the abbreviation and unit tables
    python -m graphrag.ontology guidance --out data/interim/k2_guidance.txt   # LightRAG entity-type guidance
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .data import ROOT

K2 = ROOT / "configs/ontology/k2_eowr_v1.json"
TABLES = ROOT / "data/processed/gdr_tables.jsonl"


def load(path: Path = K2) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def table_rows(table: dict) -> list[list[str]]:
    rows: dict[int, dict[int, str]] = {}
    for cell in table["cells"]:
        rows.setdefault(cell["r"], {})[cell["c"]] = cell["text"].strip()
    return [[row[c] for c in sorted(row)] for _, row in sorted(rows.items())]


def glossary(k2: dict, tables: Path = TABLES) -> list[dict]:
    """One entry per abbreviation, with every expansion the reports give and the tables it came from.

    Abbreviations containing a space are kept but flagged: they come from merged cells (`JSA jt`) and need a
    person to split them."""
    wanted = set(k2["sources"]["glossary_tables"]) | set(k2["sources"]["unit_tables"])
    entries: dict[str, dict] = {}
    for line in tables.read_text(encoding="utf-8").splitlines():
        table = json.loads(line)
        if table["table_id"] not in wanted:
            continue
        units = table["table_id"] in k2["sources"]["unit_tables"]
        for row in table_rows(table):
            if units and len(row) >= 3 and row[0] != "Unit Category":
                term, expansion, kind = row[2], f"{row[1]} ({row[0]})", "unit"
            elif not units and len(row) >= 2 and row[0] and row[1] and not row[0].lower().startswith("abbreviation"):
                term, expansion, kind = row[0], row[1], "abbreviation"
            else:
                continue
            entry = entries.setdefault(term, {"term": term, "kind": kind, "expansions": [], "tables": []})
            if expansion.lower() not in (e.lower() for e in entry["expansions"]):
                entry["expansions"].append(expansion)
            if table["table_id"] not in entry["tables"]:
                entry["tables"].append(table["table_id"])
            if " " in term and kind == "abbreviation":
                entry["check"] = "possibly two merged cells"
    return sorted(entries.values(), key=lambda e: e["term"].lower())


def guidance(k2: dict) -> str:
    """The slice as LightRAG's `entity_types_guidance`: types with definitions, then the relations to look for."""
    lines = ["Classify each entity using one of the following types. If no type fits, use `Other`.", ""]
    lines += [f"- {name}: {t['definition']} (e.g. {', '.join(t['examples'])})" for name, t in k2["entity_types"].items()]
    lines += ["", "Relationships worth extracting between these types:"]
    lines += [f"- {r['from']} {name} {r['to']}: {r['definition']}" for name, r in k2["relation_types"].items()]
    lines += ["", "Keep numbers with their units and say whether a value is planned or actual, for example "
              "\"total depth 9,145 ft (actual), planned 9,000 ft\"."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("glossary")
    g = sub.add_parser("guidance")
    g.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    k2 = load()
    if args.command == "glossary":
        k2["glossary"] = glossary(k2)
        K2.write_text(json.dumps(k2, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"{len(k2['glossary'])} glossary entries written to {K2.relative_to(ROOT)}")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(guidance(k2) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
