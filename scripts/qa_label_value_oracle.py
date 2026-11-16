"""A-432: compare the LABEL_VALUE_GEOMETRY_MISMATCH pairs with the verified form records (forms.jsonl) of the same release.

forms.jsonl values come from the pipeline's own geometry-based pairing (forms.py, value_bbox). It is a DIFFERENT code path from the QA check
but not an independent human ground truth: agreement says the two geometry readers agree, nothing more. For each mismatching pair whose
label has a form record on the same page the script reports: PDF value == form value (the QA reading is supported), K1 value == form value
(the QA signal is probably a false positive), or neither. Pairs without a form record are 'no_oracle'.
Usage:  python scripts/qa_label_value_oracle.py --ledger L.json --release R_DIR [--ledger ... --release ...] --out out.json
Read-only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from graph_builder.corpus.qa.labelvalue import first_token, fold_label


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", action="append", required=True, type=Path)
    parser.add_argument("--release", action="append", required=True, type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report, rows = Counter(), []
    form_pages = Counter()
    for ledger_path, release in zip(args.ledger, args.release):
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        oracle: dict[tuple[str, int], dict[str, str]] = {}
        forms_path = release / "forms.jsonl"
        for line in forms_path.read_text(encoding="utf-8").splitlines() if forms_path.is_file() else []:
            form = json.loads(line)
            page = form.get("page") or (form.get("pages") or [None])[0]
            fields = oracle.setdefault((form["doc_id"], page), {})
            for field in form.get("fields", []):
                if field.get("verified"):
                    fields.setdefault(fold_label(field["key"]), first_token(field.get("value") or ""))
        form_pages["pages_with_form_record"] += len(oracle)
        for document in ledger["documents"]:
            for page in document.get("pages") or []:
                for signal in page.get("signals") or []:
                    if signal["code"] != "LABEL_VALUE_GEOMETRY_MISMATCH":
                        continue
                    on_form_page = (document["doc_id"], page["page"]) in oracle
                    form_pages["flagged_pages"] += 1
                    form_pages["flagged_pages_with_form_record"] += on_form_page
                    for item in signal["evidence"]["mismatches"]:
                        truth = oracle.get((document["doc_id"], page["page"]), {}).get(item["label"])
                        if truth is None:
                            verdict = "no_oracle"
                        elif truth in item["pdf_values"] and item["k1_value"] != truth:
                            verdict = "pdf_reading_supported_k1_differs"
                        elif item["k1_value"] == truth:
                            verdict = "k1_equals_form_value_probable_false_positive"
                        else:
                            verdict = "neither_equals_form_value"
                        report[verdict] += 1
                        rows.append({"doc_id": document["doc_id"], "page": page["page"], "label": item["label"], "k1": item["k1_value"], "pdf": item["pdf_values"], "form": truth, "verdict": verdict})
    args.out.write_text(json.dumps({"counts": dict(report), "pages": dict(form_pages), "rows": rows}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(dict(report), dict(form_pages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
