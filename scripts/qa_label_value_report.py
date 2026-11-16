"""A-432: aggregate the LABEL_VALUE_GEOMETRY_MISMATCH signals of one or more QA ledgers (made with `qa ... --label-value`).
Prints, per document, the pages compared / flagged / skipped and the most frequent (label, K1 value, PDF value) mismatches, so that a
human can decide per pattern whether it is a real wrong pairing or a limitation of the check. Counting is NOT a precision measurement.
Usage (repo root):  python scripts/qa_label_value_report.py --ledger A/qa-ledger.json [--ledger B/qa-ledger.json] [--out report.json]
Read-only. Never opens a PDF.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def summarise(ledger: dict) -> dict:
    documents, patterns = {}, Counter()
    for document in ledger["documents"]:
        pages = document.get("pages") or []
        flagged = [p for p in pages if any(s["code"] == "LABEL_VALUE_GEOMETRY_MISMATCH" for s in p.get("signals") or [])]
        skipped = [p for p in pages if any(s["code"] == "LABEL_VALUE_NOT_APPLICABLE" for s in p.get("signals") or [])]
        pairs_compared = pairs_mismatch = 0
        for page in flagged:
            for signal in page["signals"]:
                if signal["code"] == "LABEL_VALUE_GEOMETRY_MISMATCH":
                    evidence = signal["evidence"]
                    pairs_compared += evidence["counts"].get("compared", 0)
                    pairs_mismatch += evidence["mismatch_pairs"]
                    for item in evidence["mismatches"]:
                        patterns[(document["doc_id"][:36], item["label"], item["k1_value"], "|".join(item["pdf_values"]))] += 1
        documents[document["doc_id"]] = {"pages": len(pages), "flagged": len(flagged), "skipped": len(skipped), "flagged_pages": [p["page"] for p in flagged],
                                         "pairs_compared_on_flagged_pages": pairs_compared, "pairs_mismatch": pairs_mismatch}
    top = [{"doc": doc, "label": label, "k1": k1, "pdf": pdf, "pages": count} for (doc, label, k1, pdf), count in sorted(patterns.items(), key=lambda item: (-item[1], item[0]))]
    return {"documents": documents, "patterns": top}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", action="append", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()
    report = {str(path): summarise(json.loads(path.read_text(encoding="utf-8"))) for path in args.ledger}
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for path, entry in report.items():
        print(path)
        for doc, row in entry["documents"].items():
            if row["flagged"] or row["skipped"]:
                print(f"  {doc[:50]:50} pages {row['pages']:4} flagged {row['flagged']:3} skipped {row['skipped']:3} mismatching pairs {row['pairs_mismatch']}")
        for item in entry["patterns"][:args.top]:
            print("  ", item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
