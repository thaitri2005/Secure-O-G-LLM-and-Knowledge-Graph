"""A-416: count flagged pages / tables per signal code in one or two qa-ledger.json files and list what changed.

Usage (repo root):  python scripts/qa_compare_ledgers.py --before A/qa-ledger.json --after B/qa-ledger.json [--out cmp.json]
                    python scripts/qa_compare_ledgers.py --after B/qa-ledger.json        (counts only)
Read-only. A flagged page has at least one WARN/ERROR page signal; a flagged table has a WARN/ERROR table signal.
Denominators (pages by mode, tables) are part of the output. Counting flags is NOT a precision or recall measurement.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

BAD = {"WARN", "ERROR"}


def load(path: Path) -> dict:
    ledger = json.loads(path.read_text(encoding="utf-8"))
    pages, tables = {}, {}
    modes: Counter = Counter()
    for document in ledger["documents"]:
        for page in document.get("pages") or []:
            key = (document["doc_id"], page["page"])
            pages[key] = {"codes": sorted({s["code"] for s in page.get("signals") or [] if s.get("severity") in BAD}), "mode": page.get("release_mode"),
                          "level": page.get("verification_level")}
            modes[str(page.get("release_mode"))] += 1
        for table in document.get("tables") or []:
            tables[(document["doc_id"], table["table_id"])] = sorted({s["code"] for s in table.get("signals") or [] if s.get("severity") in BAD})
    return {"pages": pages, "tables": tables, "modes": dict(modes)}


def summarise(data: dict) -> dict:
    flagged = {key: row for key, row in data["pages"].items() if row["codes"]}
    by_code: Counter = Counter(code for row in flagged.values() for code in row["codes"])
    by_mode: Counter = Counter(row["mode"] for row in flagged.values())
    levels: Counter = Counter(str(row["level"]) for row in data["pages"].values())
    table_codes: Counter = Counter(code for codes in data["tables"].values() for code in codes)
    return {"pages": len(data["pages"]), "pages_by_mode": data["modes"], "pages_flagged": len(flagged), "flagged_by_mode": dict(sorted(by_mode.items())),
            "page_codes": dict(sorted(by_code.items())), "page_levels": dict(sorted(levels.items())), "tables": len(data["tables"]),
            "tables_flagged": sum(1 for codes in data["tables"].values() if codes), "table_codes": dict(sorted(table_codes.items()))}


def compare(before: dict, after: dict) -> dict:
    only_before = sorted(key for key, row in before["pages"].items() if row["codes"] and not after["pages"].get(key, {}).get("codes"))
    only_after = sorted(key for key, row in after["pages"].items() if row["codes"] and not before["pages"].get(key, {}).get("codes"))
    table_before = {key for key, codes in before["tables"].items() if codes}
    table_after = {key for key, codes in after["tables"].items() if codes}
    return {"pages_unflagged_by_change": len(only_before), "pages_newly_flagged": len(only_after),
            "newly_flagged_pages": [f"{doc}:{page}:{','.join(after['pages'][(doc, page)]['codes'])}" for doc, page in only_after],
            "tables_unflagged_by_change": len(table_before - table_after), "tables_newly_flagged": len(table_after - table_before),
            "newly_flagged_tables": sorted(f"{doc}:{table}" for doc, table in table_after - table_before)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    after = load(args.after)
    result = {"after": summarise(after)}
    if args.before:
        before = load(args.before)
        result.update({"before": summarise(before), "change": compare(before, after)})
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
