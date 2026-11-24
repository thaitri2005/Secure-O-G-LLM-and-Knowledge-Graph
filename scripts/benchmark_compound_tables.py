"""Score reviewed drilling table rows, source units and retrieval span compaction."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from graph_builder.corpus.qa.ruled_overlap import value_tokens
from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl


REFERENCE = Path(__file__).resolve().parents[1] / "configs/benchmarks/track_a_compound_tables.json"


def load_view(path, release):
    ledger = json.loads(path.with_name("qa-ledger.json").read_text(encoding="utf-8"))
    if (ledger["k1_validator"]["status"] != "pass"
            or ledger["link"]["sha256sums_sha256"] != file_sha256(release / "SHA256SUMS")):
        raise ValueError(f"Retrieval view is from a different or invalid release: {path}")
    return {row["chunk_id"]: row for row in read_jsonl(path)}


def exact_operations(spec, tables):
    results = []
    for number, expected in spec["pages"].items():
        page = int(number)
        candidates = []
        for table in tables[spec["doc_id"], page]:
            for header in table["grid"][:table["header_rows"]]:
                if not all(header.count(label) == 1 for label in spec["headers"]):
                    continue
                columns = [header.index(label) for label in spec["headers"]]
                values = [tuple(row[column] for column in columns) for row in table["grid"][table["header_rows"]:]]
                candidates.append((table["table_id"], values))
        wanted = [tuple(row) for row in expected]
        table_id, observed = candidates[0] if len(candidates) == 1 else (None, [])
        results.append({"page": page, "table_id": table_id, "expected": len(wanted), "observed": len(observed),
                        "matched": sum((Counter(wanted) & Counter(observed)).values()), "same_order": wanted == observed,
                        "missing": list((Counter(wanted) - Counter(observed)).elements())})
    return results


def exact_panels(specs, tables, view):
    chunks = defaultdict(list)
    for row in view.values():
        if row["type"] == "table":
            chunks[row["table_id"]].append(row["text"])
    results = []
    for spec in specs:
        candidates = [table for table in tables[spec["doc_id"], spec["page"]]
                      if table["grid"] and table["grid"][0] == spec["header"]
                      and any(spec["caption"] in text.splitlines() for text in chunks[table["table_id"]])]
        table = candidates[0] if len(candidates) == 1 else None
        grid = table["grid"][table["header_rows"]:] if table else []
        matched = sum(grid.count(row) == 1 for row in spec["rows"])
        results.append({"doc_id": spec["doc_id"], "page": spec["page"], "caption": spec["caption"],
                        "table_id": table["table_id"] if table else None, "matched": matched, "expected": len(spec["rows"])})
    return results


def budget_summary(view, budget):
    widths = {row["chunk_id"]: len(row["text"]) for row in view.values() if row["type"] == "table"}
    longest = max(widths, key=widths.get, default=None)
    return {"over_budget": sum(size > budget for size in widths.values()), "longest": longest,
            "max_characters": widths[longest] if longest else 0}


def inspect(release, view, spec):
    files = {row["doc_id"]: row["sha256"] for row in read_jsonl(release / "files.jsonl")}
    if any(files.get(doc) != record["sha256"] for doc, record in spec["sources"].items()):
        raise ValueError(f"Review source PDF digests differ from {release}")
    tables = defaultdict(list)
    for row in read_jsonl(release / "tables.jsonl"):
        if len(row["pages"]) == 1:
            tables[row["doc_id"], row["pages"][0]].append(row)
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    budget = manifest["config"]["corpus"]["chunking"]["max_chars"]
    operations = exact_operations(spec["operations"], tables)
    panels = exact_panels(spec["panels"], tables, view)
    return {"budget": budget, "retrieval": budget_summary(view, budget), "operations": operations, "panels": panels,
            "operations_matched": sum(row["matched"] for row in operations), "panel_rows_matched": sum(row["matched"] for row in panels)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    for key in ("before", "before-view", "after", "after-view", "span-off-view", "out"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.reference.read_text(encoding="utf-8"))
    before = load_view(args.before_view, args.before)
    after = load_view(args.after_view, args.after)
    uncompact = load_view(args.span_off_view, args.after)
    outputs = {"before": inspect(args.before, before, spec), "after": inspect(args.after, after, spec)}
    current = outputs["after"]
    compacted = current["retrieval"]
    compaction_baseline = budget_summary(uncompact, current["budget"])
    changed = [chunk for chunk in uncompact if chunk in after and uncompact[chunk]["text"] != after[chunk]["text"]]
    same_ids = set(uncompact) == set(after)
    same_types = same_ids and all(set(value_tokens(uncompact[chunk]["text"])) == set(value_tokens(after[chunk]["text"]))
                                  for chunk in changed)
    outputs.update(compaction={"before": compaction_baseline, "after": compacted, "changed_chunks": len(changed),
                               "chunk_ids_preserved": same_ids, "distinct_tokens_preserved": same_types},
                   gates={"all_operations_in_order": all(row["same_order"] for row in current["operations"]),
                          "all_panel_rows_with_units": all(row["matched"] == row["expected"] for row in current["panels"]),
                          "reduced_over_budget_chunks": compacted["over_budget"] < compaction_baseline["over_budget"],
                          "compaction_preserves_chunk_ids_and_distinct_tokens": same_types})
    atomic_write_json(args.out, outputs)
    print(json.dumps(outputs["gates"], sort_keys=True))
    return int(not all(outputs["gates"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
