"""Multi-page table gold set for A-433: build the pair universe from qa_multipage_scan.py outputs, select a stratified
crop sample by a recorded rule, and score the scanner against viewed labels. No pipeline change, no LLM, no network.

    python scripts/qa_multipage_gold.py universe --scan name=scan_dir[:data_set] ... --out universe.json
    python scripts/qa_multipage_gold.py sample --universe universe.json --labels labels.json --out sample.json
    python scripts/qa_multipage_gold.py score --universe universe.json --gold gold.json --out metrics.json

Labels are human judgements from viewed page crops (TRUE_CONTINUATION / FALSE_CANDIDATE / UNCLEAR); they are not content
verification. UNCLEAR pairs are excluded from every metric. Every metric states its denominators and data set."""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

LABELS = ("TRUE_CONTINUATION", "FALSE_CANDIDATE", "UNCLEAR")
FEW_WORDS_IN_THE_WAY = 10  # words; more text than this between table and page edge is not a near-boundary case


def pair_key(file_id: str, page_a: int, page_b: int) -> str:
    return f"{file_id}:{page_a}-{page_b}"


def wilson(successes: int, total: int, z: float = 1.96) -> list | None:
    if total <= 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def build_universe(scans: list) -> dict:
    """scans: [(name, data_set, scan_json_dict)] in priority order. A document (file_id) is taken from the first scan
    that contains it, so documents shared by several releases are counted once."""
    owner: dict = {}
    pairs: dict = {}
    documents: dict = {}
    for name, data_set, scan in scans:
        for file_id, doc in scan["documents"].items():
            if file_id in owner:
                continue
            owner[file_id] = name
            documents[file_id] = {"pdf": doc["pdf"], "pages": doc["pages"], "tables": doc["tables"],
                                  "release_scan": name, "data_set": data_set, "errors": doc["errors"],
                                  "frame_tables_skipped": len(doc.get("frame_tables_skipped", []))}
        for pair in scan["pairs"]:
            if owner.get(pair["file_id"]) != name:
                continue
            key = pair_key(pair["file_id"], pair["page_a"], pair["page_b"])
            end, start = pair["detail"]["end"], pair["detail"]["start"]
            pairs[key] = {
                "key": key, "file_id": pair["file_id"], "pdf": documents[pair["file_id"]]["pdf"],
                "data_set": data_set, "scan": name, "page_a": pair["page_a"], "page_b": pair["page_b"],
                "table_a": pair["a"], "table_b": pair["b"], "kind": pair["kind"], "grade": pair["grade"],
                "score": pair["score"], "rotation": pair["rotation"], "num_cols": pair["detail"]["num_cols"],
                "gap_sum": round(end["gap_frac"] + start["gap_frac"], 4),
                "words_below": end["words_below"], "words_above": start["words_above"],
                "header_repeated": pair["evidence"]["header_repeated"],
            }
    return {"documents": documents, "pairs": [pairs[k] for k in sorted(pairs)]}


def near_boundary_rank(pair: dict) -> tuple:
    """Smaller = closer to a page boundary: few words in the way, small total gap."""
    in_the_way = pair["words_below"] + pair["words_above"]
    return (in_the_way > FEW_WORDS_IN_THE_WAY, pair["gap_sum"], in_the_way, pair["key"])


def select_sample(universe: dict, labelled: set, budget: int, per_document_cap: int = 3,
                  near_boundary_fraction: float = 0.3) -> dict:
    """Recorded stratified rule. Strata, in order: (1) every CANDIDATE not yet labelled; (2) LOOKALIKE by score
    descending, at most per_document_cap per document; (3) NO_BOUNDARY with the smallest (words in the way, gap) for
    false-negative estimation, at most per_document_cap per document, at most near_boundary_fraction of the budget.
    Deterministic. The NO_BOUNDARY stratum is not random, so it gives no population false-negative rate."""
    pairs = [p for p in universe["pairs"] if p["key"] not in labelled]
    chosen: list = []

    def take(candidates, limit, by_doc):
        for pair in candidates:
            if len(chosen) >= budget or limit <= 0:
                return
            if by_doc is not None and by_doc[pair["file_id"]] >= per_document_cap:
                continue
            chosen.append(pair["key"])
            limit -= 1
            if by_doc is not None:
                by_doc[pair["file_id"]] += 1

    take(sorted((p for p in pairs if p["kind"] == "CANDIDATE"), key=lambda p: (-p["score"], p["key"])), budget, None)
    nb_budget = int(budget * near_boundary_fraction)
    take(sorted((p for p in pairs if p["kind"] == "LOOKALIKE"), key=lambda p: (-p["score"], p["key"])),
         budget - len(chosen) - nb_budget, defaultdict(int))
    take(sorted((p for p in pairs if p["kind"] == "NO_BOUNDARY"), key=near_boundary_rank), budget - len(chosen),
         defaultdict(int))
    return {"rule": "all unlabelled CANDIDATE; LOOKALIKE by score desc (cap per document); NO_BOUNDARY by smallest "
                    "(words in the way, gap) (cap per document, <= near_boundary_fraction of budget)",
            "budget": budget, "per_document_cap": per_document_cap, "keys": chosen}


def score_scanner(universe: dict, gold: list) -> dict:
    """gold: [{key, label, ...}]. Scanner positive = kind CANDIDATE. UNCLEAR excluded. Reports per data set."""
    by_key = {p["key"]: p for p in universe["pairs"]}
    out: dict = {"gold_total": len(gold), "excluded_unclear": 0, "missing_in_universe": [], "by_set": {}}
    sets: dict = defaultdict(lambda: {"TP": 0, "FP": 0, "FN": 0, "TN": 0, "lookalike_true": 0, "lookalike_false": 0,
                                      "true_pairs": 0, "false_pairs": 0})
    for item in gold:
        if item["label"] == "UNCLEAR":
            out["excluded_unclear"] += 1
            continue
        pair = by_key.get(item["key"])
        if pair is None:
            out["missing_in_universe"].append(item["key"])
            continue
        positive = pair["kind"] == "CANDIDATE"
        true = item["label"] == "TRUE_CONTINUATION"
        for bucket in (sets[pair["data_set"]], sets["ALL"]):
            bucket["true_pairs" if true else "false_pairs"] += 1
            bucket["TP" if positive and true else "FP" if positive else "FN" if true else "TN"] += 1
            if pair["kind"] == "LOOKALIKE":
                bucket["lookalike_true" if true else "lookalike_false"] += 1
    for name, bucket in sorted(sets.items()):
        tp, fp, fn = bucket["TP"], bucket["FP"], bucket["FN"]
        bucket["precision"] = round(tp / (tp + fp), 4) if tp + fp else None
        bucket["precision_wilson95"] = wilson(tp, tp + fp)
        bucket["recall_on_gold"] = round(tp / (tp + fn), 4) if tp + fn else None
        bucket["recall_wilson95"] = wilson(tp, tp + fn)
        out["by_set"][name] = bucket
    return out


def load_scan(spec: str) -> tuple:
    name, _, rest = spec.partition("=")
    path, _, data_set = rest.partition(":")
    scan = json.loads((Path(path) / "scan.json").read_text(encoding="utf-8"))
    return name, data_set or "DEV", scan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("universe")
    u.add_argument("--scan", action="append", required=True)
    u.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("sample")
    s.add_argument("--universe", type=Path, required=True)
    s.add_argument("--labels", type=Path)
    s.add_argument("--budget", type=int, default=40)
    s.add_argument("--out", type=Path, required=True)
    m = sub.add_parser("score")
    m.add_argument("--universe", type=Path, required=True)
    m.add_argument("--gold", type=Path, required=True)
    m.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == "universe":
        result = build_universe([load_scan(spec) for spec in args.scan])
    elif args.cmd == "sample":
        universe = json.loads(args.universe.read_text(encoding="utf-8"))
        labelled = set()
        if args.labels:
            labelled = {item["key"] for item in json.loads(args.labels.read_text(encoding="utf-8"))["cases"]}
        result = select_sample(universe, labelled, args.budget)
    else:
        universe = json.loads(args.universe.read_text(encoding="utf-8"))
        gold = json.loads(args.gold.read_text(encoding="utf-8"))["cases"]
        result = score_scanner(universe, gold)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, (list, dict)) else len(v)) for k, v in result.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
