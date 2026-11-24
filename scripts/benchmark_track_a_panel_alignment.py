"""Score alignment of ruled BHA and pump cells against independently reviewed PDF rows."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from benchmark_compound_tables import budget_summary, exact_panels, load_view

from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl

REFERENCE = Path(__file__).resolve().parents[1] / "configs/benchmarks/track_a_panel_alignment.json"
CANONICAL_PANELS = ("textlayer:ruled_panels:bha:", "textlayer:ruled_panels:pump:")


def inspect(release, qa, spec):
    files = {row["doc_id"]: row["sha256"] for row in read_jsonl(release / "files.jsonl")}
    if any(files.get(doc_id) != source["sha256"] for doc_id, source in spec["sources"].items()):
        raise ValueError(f"Reviewed source hashes do not match {release}")
    view = load_view(qa / "retrieval_chunks.jsonl", release)
    summary = json.loads((qa / "cell_evidence_summary.json").read_text(encoding="utf-8"))
    if summary["release_checksums_sha256"] != file_sha256(release / "SHA256SUMS"):
        raise ValueError(f"Cell evidence does not belong to {release}")

    tables, by_id = defaultdict(list), {}
    for table in read_jsonl(release / "tables.jsonl"):
        if len(table["pages"]) == 1:
            tables[table["doc_id"], table["pages"][0]].append(table)
            by_id[table["table_id"]] = table
    supported = defaultdict(set)
    evidence_status = Counter()
    for cell in read_jsonl(qa / "cell_evidence.jsonl"):
        evidence_status[cell["status"]] += 1
        if cell["status"] == "source_supported":
            supported[cell["table_id"]].add((cell["r"], cell["c"], cell["text"]))

    scores = exact_panels(spec["panels"], tables, view)
    totals = defaultdict(Counter)
    for source, score in zip(spec["panels"], scores, strict=True):
        table = by_id.get(score["table_id"])
        proofs = supported.get(score["table_id"], set())
        grid = table["grid"] if table else []
        verified_rows = 0
        for expected in source["rows"]:
            if grid.count(expected) == 1:
                index = grid.index(expected)
                verified_rows += all(not value or (index, column, value) in proofs for column, value in enumerate(expected))
        score.update(cohort=source["cohort"], verified_rows=verified_rows)
        totals[source["cohort"]].update(expected=score["expected"], matched=score["matched"], verified=verified_rows)

    panels = Counter()
    source_cells = Counter()
    empty_pumps = []
    for table in by_id.values():
        prefix = table["parts"][0]["source_ref"]
        if prefix.startswith(CANONICAL_PANELS) and table["doc_id"] in spec["sources"]:
            key = prefix.split(":")[2]
            panels[key] += 1
            source_cells[key] += len(supported[table["table_id"]])
            if key == "pump" and table["pages"][0] in spec["empty_pump_pages"]:
                empty_pumps.extend(table["pages"])
    return {"cases": scores, "cohorts": totals, "panels": panels, "source_cells": source_cells,
            "evidence_status": evidence_status, "empty_pumps_emitted": empty_pumps, "retrieval": budget_summary(view, 1500)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "before-qa", "after", "after-qa", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    args = parser.parse_args()
    spec = json.loads(args.reference.read_text(encoding="utf-8"))
    old, new = (inspect(release, qa, spec) for release, qa in [(args.before, args.before_qa), (args.after, args.after_qa)])
    gates = {"all_probes_match_and_have_source_evidence": all(row["verified"] == row["expected"] for row in new["cohorts"].values()),
             "blank_pump_templates_abstain": not new["empty_pumps_emitted"]}
    atomic_write_json(args.out, {"before": old, "after": new, "gates": gates})
    print(json.dumps({"gates": gates, "before": old["cohorts"], "after": new["cohorts"]}, sort_keys=True))
    return int(not all(gates.values()))


if __name__ == "__main__":
    raise SystemExit(main())
