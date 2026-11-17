"""A-432: precision of flagged units on a labelled stratified sample, before and after, with Wilson 95% intervals.

Inputs: the sample made by qa_flagged_sample.py from the BEFORE ledgers, a labels file {"<n>": {"label": "TP|MARKER|FP|UNCLEAR", "source": "..."}} (1-based
position in the sample) and the AFTER ledgers. A unit is still flagged after when its page (or table first page) has a WARN/ERROR signal in the AFTER ledgers.
precision = TP / (TP + FP); UNCLEAR is excluded from that ratio and also reported in the 'all labelled' lower bound TP / (TP + FP + UNCLEAR).
MARKER (list/outline numbers lost, text kept) counts as TP-minor: it is shown separately and included in TP so that downgrading it cannot raise the precision.
The sample is stratified and NOT weighted: the numbers describe the sample, not the whole pool. Read-only.
"""
from __future__ import annotations

import argparse
import json
from math import sqrt
from pathlib import Path

from qa_flagged_sample import flagged_units


def wilson(k: int, n: int, z: float = 1.96) -> list[float | None]:
    if n == 0:
        return [None, None]
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 3), round(centre + half, 3)]


def measure(rows: list[dict], names: list[str]) -> dict:
    tp = sum(r["label"] in ("TP", "MARKER") for r in rows)
    fp = sum(r["label"] == "FP" for r in rows)
    unclear = sum(r["label"] == "UNCLEAR" for r in rows)
    return {"units": len(rows), "TP": tp, "of_which_MARKER": sum(r["label"] == "MARKER" for r in rows), "FP": fp, "UNCLEAR": unclear,
            "precision_excluding_unclear": round(tp / (tp + fp), 3) if tp + fp else None, "wilson95": wilson(tp, tp + fp),
            "precision_lower_bound_all_labelled": round(tp / (tp + fp + unclear), 3) if rows else None, "wilson95_all": wilson(tp, tp + fp + unclear),
            "false_positive_rate_of_flags": round(fp / (tp + fp), 3) if tp + fp else None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--after", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))["sample"]
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    after = {(u["doc_id"], u["page"]) for path in args.after for u in flagged_units(json.loads(path.read_text(encoding="utf-8")))}
    rows = [{"n": i, "doc_id": u["doc_id"], "page": u["page"], "stratum": u["stratum"], "label": labels[str(i)]["label"], "source": labels[str(i)]["source"],
             "flagged_after": (u["doc_id"], u["page"]) in after} for i, u in enumerate(sample, 1)]
    still = [r for r in rows if r["flagged_after"]]
    cleared = [r for r in rows if not r["flagged_after"]]
    report = {"before": measure(rows, []), "after_same_units_still_flagged": measure(still, []),
              "cleared": {"units": len(cleared), "by_label": {k: sum(r["label"] == k for r in cleared) for k in ("TP", "MARKER", "FP", "UNCLEAR")},
                          "cleared_TP_not_marker": [r for r in cleared if r["label"] == "TP"]},
              "rows": rows}
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, sort_keys=True, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
