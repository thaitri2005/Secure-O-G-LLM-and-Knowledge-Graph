"""A-445: effect of the label-value false-alarm filters (qa/labelvalue.py, config labels.not_a_label_patterns).

Runs the geometry check twice over the same pages and PDF readings: with the shipped config ('new') and with the same config minus the
A-445 key ('old' = A-432 behaviour). Lists every mismatch pair that only the old config reports ('removed') and every one only the new config
reports ('added', must be empty), and, with --gold, whether each source-verified TRUE_ERROR pair of the A-441 gold that the geometry checker
flagged is still flagged. Counts only; it does not decide which flag is right (the removed pairs are viewed by a human).
Usage (repo root, PYTHONPATH=src):
  python scripts/qa_label_value_fp_eval.py --set NAME=RELEASE_DIR,CORPUS_DIR [--set ...] [--gold label-value-gold.json] --out OUT.json
Read-only on releases, corpora and PDFs. Deterministic.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

from graph_builder.corpus.qa import fidelity as fid
from graph_builder.corpus.qa import labelvalue as lv


def old_config(config: dict) -> dict:
    old = copy.deepcopy(config)
    old["labels"].pop("not_a_label_patterns", None)
    return old


def mismatch_keys(result: dict) -> set[tuple[str, str]]:
    return {(m["label"], m["k1_value"]) for m in result["mismatches"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", action="append", required=True, metavar="NAME=RELEASE,CORPUS")
    parser.add_argument("--config", type=Path, default=Path("configs/qa/label_value.json"))
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    new_cfg = lv.load_config(args.config)
    old_cfg = old_config(new_cfg)
    fid_cfg = fid.load_config()
    report: dict = {"config_sha256": fid.sha256_file(args.config), "sets": {}}
    flagged: dict[tuple[str, str, int], dict] = {}  # (set, file_id, page) -> {'old': keys, 'new': keys}
    for item in args.set:
        name, rest = item.split("=", 1)
        release, corpus = rest.split(",")
        release = Path(release)
        pages = [(row["file_id"], row["page"], row.get("mode") or row.get("conversion_mode")) for row in fid.iter_jsonl(release / "pages.jsonl")]
        state_new = lv.LabelValueState(release, Path(corpus), fid_cfg, new_cfg)
        state_old = lv.LabelValueState(release, Path(corpus), fid_cfg, old_cfg)
        entry = {"pages_compared": 0, "pages_flagged_old": 0, "pages_flagged_new": 0, "pairs_old": 0, "pairs_new": 0, "removed": [], "added": [], "errors": 0}
        for file_id, page, mode in sorted(pages, key=lambda p: (p[0], p[1])):
            if mode == "ocr":
                continue
            try:
                new, _ = state_new.analyse(file_id, page)
                old, _ = state_old.analyse(file_id, page)
            except Exception:  # noqa: BLE001 - one broken page must not lose the others
                entry["errors"] += 1
                continue
            if new is None or old is None:
                continue
            entry["pages_compared"] += 1
            kn, ko = mismatch_keys(new), mismatch_keys(old)
            entry["pairs_new"] += len(new["mismatches"])
            entry["pairs_old"] += len(old["mismatches"])
            entry["pages_flagged_new"] += bool(new["mismatches"])
            entry["pages_flagged_old"] += bool(old["mismatches"])
            doc = state_new.base.files[file_id]["doc_id"]
            entry["removed"] += [{"doc_id": doc, "file_id": file_id, "page": page, "label": a, "k1_value": b} for a, b in sorted(ko - kn)]
            entry["added"] += [{"doc_id": doc, "file_id": file_id, "page": page, "label": a, "k1_value": b} for a, b in sorted(kn - ko)]
            flagged[(name, file_id, page)] = {"old": ko, "new": kn}
        state_new.close()
        state_old.close()
        report["sets"][name] = entry
        print(name, {k: v for k, v in entry.items() if not isinstance(v, list)}, "removed", len(entry["removed"]), "added", len(entry["added"]))
    if args.gold:
        gold = json.loads(args.gold.read_text(encoding="utf-8"))["pairs"]
        rows = []
        for pair in gold:
            if pair.get("geometry_checker") != "CONFLICT":
                continue
            seen = flagged.get((pair["release"], pair["file_id"], pair["page"]))
            if seen is None:
                continue
            was = any(label == pair["label"] for label, _ in seen["old"])
            now = any(label == pair["label"] for label, _ in seen["new"])
            rows.append({"sample_id": pair["sample_id"], "verdict": pair["verdict"], "flagged_old": was, "flagged_new": now})
        report["gold_geometry_flagged"] = {
            "pairs": len(rows),
            "true_error": sum(r["verdict"] == "TRUE_ERROR" for r in rows),
            "true_error_still_flagged": sum(r["verdict"] == "TRUE_ERROR" and r["flagged_new"] for r in rows),
            "true_error_flagged_before": sum(r["verdict"] == "TRUE_ERROR" and r["flagged_old"] for r in rows),
            "not_true_error_flagged_before": sum(r["verdict"] != "TRUE_ERROR" and r["flagged_old"] for r in rows),
            "not_true_error_flagged_now": sum(r["verdict"] != "TRUE_ERROR" and r["flagged_new"] for r in rows),
            "rows": rows}
        print("gold", {k: v for k, v in report["gold_geometry_flagged"].items() if k != "rows"})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
