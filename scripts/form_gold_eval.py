"""Score form label-value extraction against a geometry-verified gold (A-435).

The gold lists (pdf, page, label bbox, expected value, value bbox, status) built from the SOURCE PDF words by a reader that is independent of
forms.py (see the gold builder in the evidence folder). Each gold pair is matched to the extracted field whose KEY box sits at the same place
and receives one outcome:

  PAIR gold:   CORRECT | UNIT_DROPPED | WRONG_LABEL (value of ANOTHER gold pair) | WRONG_VALUE | ABSENT (no field for this label)
  BLANK gold:  BLANK_OK | BLANK_FILLED (a value was invented or taken from a neighbour; WRONG_LABEL if it is the neighbour's value) | ABSENT
  AMBIGUOUS:   NOT_FORCED (absent or empty) | FORCED (a value was output)

    python scripts/form_gold_eval.py GOLD.json [--out result.json] [--form-blocks CONFIG]
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def norm(text: str) -> str:
    return re.sub(r"\s+([,.;:])", r"\1", " ".join((text or "").split()))


def overlap(a, b) -> float:
    """Intersection over the smaller box."""
    if not a or not b:
        return 0.0
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / max(1e-9, min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])))


def match_field(gold: dict, fields: list[dict]) -> dict | None:
    """The extracted field whose key box coincides with the gold label box (same row, boxes overlap)."""
    best, score = None, 0.0
    for field in fields:
        box = field.get("key_bbox")
        if not box:
            continue
        value = overlap(gold["label_bbox"], box)
        if value > score and value >= 0.5:
            best, score = field, value
    return best


def classify(gold: dict, field: dict | None, page_gold: list[dict]) -> str:
    if gold["status"] == "AMBIGUOUS":
        return "FORCED" if field is not None and norm(field["value"]) else "NOT_FORCED"
    if field is None:
        return "ABSENT"
    predicted, expected = norm(field["value"]), norm(gold["expected_value"])
    others = [g for g in page_gold if g is not gold and g["status"] == "PAIR" and norm(g["expected_value"]) == predicted
              and overlap(g["value_bbox"], field.get("value_bbox")) >= 0.5]
    if gold["status"] == "BLANK":
        if not predicted:
            return "BLANK_OK"
        return "WRONG_LABEL" if others else "BLANK_FILLED"
    if predicted == expected:
        return "CORRECT"
    if others:
        return "WRONG_LABEL"
    if predicted and expected.startswith(predicted + " "):
        return "UNIT_DROPPED" if gold["category"].startswith("number_unit") else "WRONG_VALUE"
    return "WRONG_VALUE"


def evaluate(gold_pairs: list[dict], extract) -> dict:
    """``extract(pdf_path, page) -> list of fields`` (empty when the page is not supported)."""
    by_page = defaultdict(list)
    for pair in gold_pairs:
        by_page[(pair["pdf"], pair["page"])].append(pair)
    rows, supported = [], {}
    for (pdf, page), pairs in sorted(by_page.items()):
        record = extract(ROOT / "data/raw" / pdf, page)
        supported[(pdf, page)] = record is not None
        fields = record["fields"] if record else []
        for pair in pairs:
            outcome = classify(pair, match_field(pair, fields), pairs)
            rows.append({"id": pair["id"], "label": pair["label"], "page": page, "category": pair["category"], "status": pair["status"], "outcome": outcome,
                         "page_supported": supported[(pdf, page)], "pdf": pdf})
    return {"rows": rows, "summary": summarize(rows)}


def summarize(rows: list[dict]) -> dict:
    def count(selected):
        c = Counter(r["outcome"] for r in selected)
        return {"n": len(selected), **dict(sorted(c.items()))}
    pair = [r for r in rows if r["status"] == "PAIR"]
    blank = [r for r in rows if r["status"] == "BLANK"]
    ambiguous = [r for r in rows if r["status"] == "AMBIGUOUS"]
    sup = [r for r in rows if r["page_supported"]]
    return {"all": count(rows), "pair": count(pair), "blank": count(blank), "ambiguous": count(ambiguous),
            "on_supported_pages": count(sup), "on_unsupported_pages": count([r for r in rows if not r["page_supported"]]),
            "pair_correct": f"{sum(r['outcome'] == 'CORRECT' for r in pair)}/{len(pair)}",
            "wrong_label": sum(r["outcome"] == "WRONG_LABEL" for r in rows),
            "blank_ok": f"{sum(r['outcome'] == 'BLANK_OK' for r in blank)}/{len(blank)}",
            "number_unit_kept": f"{sum(r['outcome'] == 'CORRECT' for r in pair if r['category'].startswith('number_unit'))}/{sum(1 for r in pair if r['category'].startswith('number_unit'))}",
            "ambiguous_forced": f"{sum(r['outcome'] == 'FORCED' for r in ambiguous)}/{len(ambiguous)}",
            "by_category": {cat: count([r for r in rows if r["category"] == cat]) for cat in sorted({r["category"] for r in rows})}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gold", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--form-blocks", type=Path, help="optional extra-block configuration (A-435), default OFF")
    args = parser.parse_args()
    from graph_builder.corpus.forms import extract_auto, load_template
    from graph_builder.corpus.k1_config import load_k1_config
    forms = load_k1_config()["forms"]
    template = load_template()
    blocks = json.loads(args.form_blocks.read_text(encoding="utf-8")) if args.form_blocks else None
    gold = json.loads(args.gold.read_text(encoding="utf-8"))["pairs"]
    extra = {"blocks": blocks} if blocks else {}
    result = evaluate(gold, lambda pdf, page: extract_auto(pdf, page, template, forms["minimum_label_share"], False, **extra))
    text = json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
