"""Score key-value form pairing against the reviewed annotations, using only the source PDFs.

Reads the form annotation manifests of the ingestion exploration (read-only), pairs each annotated page
with the corpus form code and prints exact-pair and box results. Needs the PDFs in data/raw/.

    python scripts/evaluate_form_pairing.py                           # writes data/interim/k1-form-eval/forms.json
    python scripts/evaluate_form_pairing.py --out data/interim/other
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPLORATION = ROOT / "explorations/ingestion"
SPLITS = ("development", "held-out")


def annotation_path(old: str) -> Path:
    """Resolve a path stored in an annotation manifest through the exploration's relocation table."""
    if old.startswith("data/"):
        return ROOT / old
    relocation = EXPLORATION / "configs/annotation-paths.json"
    mapped = json.loads(relocation.read_text(encoding="utf-8"))["paths"].get(old, old) if relocation.exists() else old
    return EXPLORATION / mapped


def expected_pairs(gold: dict) -> list[tuple[str, str]]:
    import csv
    with annotation_path(gold["csv"]).open(encoding="utf-8", newline="") as stream:
        return [(row[1], row[2]) for row in list(csv.reader(stream))[1:]]


def evaluate(forms_config: dict, template: dict) -> list[dict]:
    from graph_builder.corpus.form_scoring import annotated_box_coverage, pair_score
    from graph_builder.corpus.forms import extract_auto
    results = []
    for split in SPLITS:
        manifest = EXPLORATION / "annotations" / split / "forms/forms.json"
        for gold in json.loads(manifest.read_text(encoding="utf-8")):
            pdf = ROOT / "data/raw" / f"{gold['doc_id']}.pdf"
            form = extract_auto(pdf, gold["page"], template, forms_config["minimum_label_share"], generic=False)
            fields = form["fields"] if form else []
            results.append(dict(id=gold["id"], split=split, doc_id=gold["doc_id"], page=gold["page"],
                                method=form["method"] if form else None,
                                **pair_score(expected_pairs(gold), fields, form["reference_text"] if form else ""),
                                **annotated_box_coverage(gold["pairs"], fields)))
    return results


def table(results: list[dict]) -> str:
    lines = [f"{'split':<12}{'form':<28}{'method':<18}{'exact pairs':<14}{'bbox share':<12}{'annotated box coverage':<24}"]
    for row in results:
        lines.append(f"{row['split']:<12}{row['id']:<28}{str(row['method']):<18}{row['matched']}/{row['gold_pairs']:<10}"
                     f"{row['bbox_share']:<12.4f}{row['annotated_bbox_coverage']:<24.4f}")
    for split in SPLITS:
        rows = [row for row in results if row["split"] == split]
        lines.append(f"{split}: {sum(row['matched'] for row in rows)}/{sum(row['gold_pairs'] for row in rows)} exact pairs")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "data/interim/k1-form-eval")
    args = parser.parse_args()
    out = args.out.resolve()
    if EXPLORATION in (out, *out.parents):
        parser.error("--out must not be inside explorations/")
    from graph_builder.corpus.forms import load_template
    from graph_builder.corpus.k1_config import load_k1_config, template_path
    config = load_k1_config()
    results = evaluate(config["forms"], load_template(template_path(config)))
    print(table(results))
    out.mkdir(parents=True, exist_ok=True)
    (out / "forms.json").write_text(json.dumps({"format": "form-pairing-evaluation", "forms": results}, ensure_ascii=False,
                                               sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if all(row["matched"] == row["gold_pairs"] == row["predicted_pairs"] for row in results) else 1


if __name__ == "__main__":
    sys.exit(main())
