"""A-416: deterministic stratified sample of the pages a QA run flagged (for visual classification).

Rule (recorded in the output): a flagged unit is a page with at least one WARN/ERROR page signal, or the first page of a
table with a WARN/ERROR table signal. Units are grouped by their primary signal (the first code of PRIORITY present on
the unit). Slots are shared out in proportion to the group sizes, at least ``MIN_PER_GROUP`` per group while slots last
(largest groups first, so the total never exceeds ``--n``); inside a group the units are sorted by (doc_id, page) and
taken at evenly spaced positions ``floor((k + 0.5) * size / slots)``. No randomness: the same ledgers give the same sample.

Usage (repo root):  PYTHONPATH=src python scripts/qa_flagged_sample.py --ledger A/qa-ledger.json [--ledger B/qa-ledger.json] --n 30 --out sample.json
Read-only on the ledgers. It never opens a PDF.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PRIORITY = ("FIDELITY_PAGE_EMPTY", "PAGE_EMPTY_EXTRACTION", "FIDELITY_NUMERIC_NOVEL", "FIDELITY_NUMERIC_RECALL_LOW",
            "FIDELITY_WORD_RECALL_LOW", "CHAR_RATIO_HIGH", "CHAR_RATIO_LOW", "XREP_TABLE_CHUNK_MISMATCH")
MIN_PER_GROUP = 2
BAD = {"WARN", "ERROR"}


def flagged_units(ledger: dict) -> list[dict]:
    """[{doc_id, file_id, page, codes}] for the flagged pages / tables of one qa-ledger.json."""
    units: dict[tuple[str, int], set[str]] = {}
    names: dict[str, str] = {}
    for document in ledger["documents"]:
        file_id, doc_id = document["file_id"], document.get("doc_id") or document["file_id"]
        names[file_id] = doc_id
        for page in document.get("pages") or []:
            codes = {s["code"] for s in page.get("signals") or [] if s.get("severity") in BAD}
            if codes:
                units.setdefault((file_id, page["page"]), set()).update(codes)
        for table in document.get("tables") or []:
            codes = {s["code"] for s in table.get("signals") or [] if s.get("severity") in BAD}
            if codes and table.get("pages"):
                units.setdefault((file_id, min(table["pages"])), set()).update(codes)
    return [{"doc_id": names[file_id], "file_id": file_id, "page": page, "codes": sorted(codes)}
            for (file_id, page), codes in sorted(units.items(), key=lambda item: (names[item[0][0]], item[0][1]))]


def primary(codes: list[str]) -> str:
    return next((code for code in PRIORITY if code in codes), "OTHER:" + codes[0])


def select_sample(units: list[dict], n: int) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for unit in units:
        groups.setdefault(primary(unit["codes"]), []).append(unit)
    total = len(units)
    if total <= n:
        return [{**unit, "stratum": primary(unit["codes"])} for unit in units]
    slots = {name: 0 for name in groups}
    for name in sorted(groups, key=lambda key: (-len(groups[key]), key)):  # minimum first, largest groups first
        slots[name] = min(MIN_PER_GROUP, len(groups[name]), n - sum(slots.values()))
    spare = n - sum(slots.values())
    shares = sorted(groups, key=lambda key: (-(len(groups[key]) / total * n - slots[key]), key))
    while spare > 0 and any(slots[name] < len(groups[name]) for name in groups):
        for name in shares:
            if spare > 0 and slots[name] < len(groups[name]):
                slots[name] += 1
                spare -= 1
    picked = []
    for name in sorted(groups):
        members = groups[name]
        for k in range(slots[name]):
            picked.append({**members[int((k + 0.5) * len(members) / slots[name])], "stratum": name})
    return sorted(picked, key=lambda unit: (unit["stratum"], unit["doc_id"], unit["page"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", action="append", required=True, type=Path)
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    units = []
    for path in args.ledger:
        units += flagged_units(json.loads(path.read_text(encoding="utf-8")))
    units.sort(key=lambda unit: (unit["doc_id"], unit["page"]))
    sample = select_sample(units, args.n)
    strata: dict[str, int] = {}
    for unit in units:
        strata[primary(unit["codes"])] = strata.get(primary(unit["codes"]), 0) + 1
    result = {"rule": __doc__.split("\n\n")[1].replace("\n", " "), "flagged_units": len(units), "strata_sizes": dict(sorted(strata.items())),
              "n_requested": args.n, "sample": sample}
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"flagged_units": len(units), "sampled": len(sample), "strata": dict(sorted(strata.items()))}))


if __name__ == "__main__":
    main()
