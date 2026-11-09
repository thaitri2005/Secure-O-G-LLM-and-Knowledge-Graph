"""A-401a evaluation: margin signal on the real Operations tables and under the A-107 style position noise.

Run (docling venv, repo root):  PYTHONPATH=src:tests python scripts/qa_ops_margin_eval.py [--out DIR]
Reads: the A-107 Round 2 release (read-only), data/raw PDFs. Writes: <out>/ops-margin-eval.json (default data/interim/overnight/a401a).
Labels: the 81 real tables are DEVELOPMENT data (the rule and this check were designed on them): NOT independent.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "tests")
from graph_builder.corpus import ops_tables as ops, table_recognition as rec  # noqa: E402
from graph_builder.corpus.k1_config import load_k1_config  # noqa: E402
from graph_builder.corpus.qa import opsmargin as om  # noqa: E402
from graph_builder.corpus.qa.fidelity import FidelityState, iter_jsonl  # noqa: E402
from graph_builder.corpus.text_layer import source_page  # noqa: E402
from test_ops_real_pdfs import transform  # noqa: E402  (unit-test helper: seeded jitter of word positions)

RELEASE = Path("data/interim/k1-run/corpus/exports/ops-rebuild-r3-e2/releases/20261108T174020Z-e34a87c780d8")
RULE = load_k1_config()["table_rules"]["operations_summary"]
SEEDS = (1, 2, 3, 4, 5)
LEVELS = ((1.0, "design level (x 0.1 em)"), (3.0, "3x design (x 0.3 em)"), (6.0, "6x design (x 0.6 em)"))


def stats(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"n": len(ordered), "min": ordered[0], "median": ordered[len(ordered) // 2], "max": ordered[-1]} if ordered else {"n": 0}


def cell_difference(base: list, new: list) -> str:
    """Coarse cause of a rebuilt-but-different page: mark moved into the description, or other change."""
    kinds = set()
    for b_result, n_result in zip(base, new):
        if b_result.get("rows") == n_result.get("rows"):
            continue
        for b_row, n_row in zip(b_result.get("rows") or [], n_result.get("rows") or []):
            if b_row == n_row:
                continue
            if b_row[6] == "X" and n_row[6] != "X":
                kinds.add("mark_left_column")
            elif b_row[6] != n_row[6]:
                kinds.add("mark_changed")
            else:
                kinds.add("description_or_other")
        if len(b_result.get("rows") or []) != len(n_result.get("rows") or []):
            kinds.add("row_count")
    return "+".join(sorted(kinds)) or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/interim/overnight/a401a")
    out_dir = Path(parser.parse_args().out)
    out_dir.mkdir(parents=True, exist_ok=True)
    config = om.load_config()

    # 1. real release: all Operations tables
    measures = om.measure_release(RELEASE, None, config)
    ok = {t: m for t, m in measures.items() if m["status"] == "ok"}
    x_values = [v for m in ok.values() for v in m["x_margins_em"]]
    gap_values = [m["desc_gap_em"] for m in ok.values() if m["desc_gap_em"] is not None]
    x_ref = om.family_reference(x_values, config)
    verdicts = om.judge_family({t: m for t, m in measures.items() if m["status"] in ("ok", "no_label")}, config)
    flagged = sorted(t for t, v in verdicts.items() if any(code == "OPS_MARGIN_NEEDS_VERIFICATION" for code, _ in v))
    real = {"tables": len(measures), "measured_ok": len(ok), "not_measured": dict(collections.Counter(m["status"] for m in measures.values() if m["status"] != "ok")),
            "tables_with_x": sum(1 for m in ok.values() if m["x_margins_em"]), "x_marks": len(x_values),
            "x_margin_em": stats(x_values), "desc_gap_em": stats(gap_values), "x_reference": x_ref,
            "flagged_tables": flagged, "flagged": len(flagged),
            "no_reference_signals": sum(1 for v in verdicts.values() if any(c == "OPS_MARGIN_NO_REFERENCE" for c, _ in v))}

    # 2. perturbation on the pages of those tables (page level, like the A-107 experiment)
    state = FidelityState(RELEASE, None, config)
    pages = sorted({(t["file_id"], p["page"]) for t in om.operations_parts(RELEASE, config) for p in t["parts"]})
    cache = {}
    results = {label: collections.Counter() for _, label in LEVELS}
    details = {label: [] for _, label in LEVELS}
    for file_id, page in pages:
        path = cache.get(file_id) or cache.setdefault(file_id, state.locate_pdf(state.files[file_id])[0])
        layer = source_page(path, page)
        em = rec.em(next(l for l in rec.page_lines(layer) if len(l["words"]) > 5)["words"])
        base = ops.read_page(layer, RULE)
        base_key = [(r["status"], r["reason"], json.dumps(r.get("rows"))) for r in base]
        for multiplier, label in LEVELS:
            for seed in SEEDS:
                noisy = transform(layer, jitter=random.Random(seed), em=em * multiplier)
                new = ops.read_page(noisy, RULE)
                key = [(r["status"], r["reason"], json.dumps(r.get("rows"))) for r in new]
                rebuilt = [r for r in new if r["status"] == "rebuilt"]
                signals = []
                for r in rebuilt:
                    m = om.measure_table(noisy["words"], [r["bbox"][0], r["span"][0], r["bbox"][2], r["span"][1]], config)
                    signals.append(any(code == "OPS_MARGIN_NEEDS_VERIFICATION" for code, _ in om.judge_table(m, x_ref, config)))
                any_flag = any(signals)
                counter = results[label]
                counter["pages"] += 1
                if key == base_key:
                    counter["identical"] += 1
                    counter["identical_flagged"] += any_flag
                elif new and len(rebuilt) == len(new):
                    cause = cell_difference(base, new)
                    counter["validated_but_different"] += 1
                    counter["validated_but_different_flagged"] += any_flag
                    counter[f"vbd[{cause}]"] += 1
                    counter[f"vbd[{cause}]_flagged"] += any_flag
                    if not any_flag:
                        details[label].append({"file_id": file_id, "page": page, "seed": seed, "cause": cause})
                else:
                    counter["left_unvalidated"] += 1
                    counter["left_unvalidated_flagged_on_rebuilt_part"] += any_flag
    evaluation = {"release": RELEASE.name, "label": "DEVELOPMENT data (81 real tables, seen); NOT independent",
                  "real_tables": real, "pages_perturbed": len(pages), "seeds": list(SEEDS),
                  "perturbation": {label: dict(sorted(c.items())) for label, c in results.items()},
                  "unflagged_residue": details, "config_thresholds": {k: v["value"] for k, v in config["thresholds"].items()}}
    (out_dir / "ops-margin-eval.json").write_text(json.dumps(evaluation, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"real_tables": real, "perturbation": evaluation["perturbation"]}, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
