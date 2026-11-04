"""Scores table facts on reports the mappings were not written from, against independent gold (E29).

    python -m graphrag.table_eval --facts E29_tables_as_is E25_tables_78-32_fixed --runs e29_all e25_78-32 --name E29_score_as_is

Casing: a string is right when a fact has its size and bottom depth, in the report's unit. A casing fact matching no
gold string is wrong. Surveys: a row is right when a fact has its measured depth and inclination. With --runs, facts are
also scored after strict validation, which is what reaches the answer model.
"""
from __future__ import annotations

import argparse
import json
import re

from .baseline import RESULTS
from .data import ROOT, load_chunks
from .validate import casing_size, validate

GOLD = ROOT / "graphrag/gold/e29_table_gold.json"


def _number(text) -> float | None:
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def _well_named(fact: dict) -> bool:
    return bool(fact.get("well")) and bool(re.search(r"\d", fact["well"]))


def score_casing(facts: list[dict], gold: dict) -> dict:
    wanted = {(float(size), float(depth)) for size, depth in gold["strings"]}
    found, wrong = set(), []
    for fact in facts:
        if fact["property"] != "casing_depth" or fact["qualifier"] != "actual":
            continue
        size, depth = casing_size(str((fact["context"] or {}).get("casing_size_in", ""))), _number(fact["value"])
        unit_ok = fact.get("unit", "ft") == gold["unit"]
        match = next((w for w in wanted if size == w[0] and depth is not None and abs(depth - w[1]) <= max(0.5, 0.005 * w[1])), None)
        if match and unit_ok:
            found.add(match)
        else:
            wrong.append(f"{fact['context']} = {fact['value']} {fact.get('unit', 'ft')}")
    return {"strings": len(wanted), "right": len(found), "wrong_facts": wrong}


def score_survey(facts: list[dict], rows: list[list[float]]) -> dict:
    wanted = {(round(md, 2), round(inc, 2)) for md, inc in rows}
    got = set()
    for fact in facts:
        if fact["property"] != "inclination":
            continue
        context = fact["context"] or {}
        md, inc = _number(context.get("depth_ft", context.get("depth_m"))), _number(fact["value"])
        if md is not None and inc is not None:
            got.add((round(md, 2), round(inc, 2)))
    return {"rows": len(wanted), "right": len(got & wanted), "wrong_facts": len(got - wanted)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--facts", nargs="+", required=True, help="graphrag.tables result names")
    parser.add_argument("--runs", nargs="*", default=[], help="named ingestion runs, to validate the facts against their chunks")
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    facts = [f for name in args.facts for f in json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))["facts"]]
    kept = None
    if args.runs:
        texts = {c.id: c.text for run in args.runs
                 for c in load_chunks(path=ROOT / "data/interim/runs" / run / "gdr_chunks_full.jsonl")}
        kept, _ = validate(facts, texts, strict=True)
    out = {}
    for doc, entry in gold["casing"].items():
        mine = [f for f in facts if f["chunk"].startswith(doc + "#")]
        row = {"role": entry["role"], "casing": score_casing(mine, entry), "wells": sorted({f["well"] for f in mine}),
               "facts": len(mine)}
        if doc in gold["surveys"]:
            row["survey"] = score_survey(mine, gold["surveys"][doc])
        checked = None
        if kept is not None:
            valid = [f for f in kept if f["chunk"].startswith(doc + "#")]
            checked = score_casing(valid, entry)
            row["validated"] = {"casing": checked, "facts": len(valid)}
            if doc in gold["surveys"]:
                row["validated"]["survey"] = score_survey(valid, gold["surveys"][doc])
        out[doc] = row
        survey = row.get("survey")
        print(f"{doc:<28} {entry['role'][:30]:<31} casing {row['casing']['right']}/{row['casing']['strings']} "
              f"wrong {len(row['casing']['wrong_facts'])}"
              + (f" | survey {survey['right']}/{survey['rows']} wrong {survey['wrong_facts']}" if survey else "")
              + f" | facts {row['facts']} wells {row['wells'][:3]}"
              + (f" | VALIDATED casing {checked['right']}/{checked['strings']} wrong {len(checked['wrong_facts'])}" if checked else "")
              + (f" survey {row['validated']['survey']['right']} wrong {row['validated']['survey']['wrong_facts']}" if checked and survey else ""))
    (RESULTS / f"{args.name}.json").write_text(json.dumps({"facts": args.facts, "reports": out}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
