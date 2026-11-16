"""A-432: scripted taxonomy of the flagged units of a frozen 'before' QA ledger, and what the current QA logic does with them.

For every flagged unit (a page with a WARN/ERROR page signal, or the first page of a table with a WARN/ERROR table signal) of the
BEFORE ledger the script assigns ONE mechanism class by fixed rules (order below) and states whether the AFTER ledger still flags it.
The fidelity classes are decided by re-running the fidelity comparison twice on the same PDF page: once with the A-416 config
(`--old-config`, no block_*/enumerators keys) and once with the current config; the difference between the two says which
mechanism explained the tokens. A class is a mechanism, NOT a verdict: 'cleared' means the logic now explains the missing tokens,
it says nothing about the page being correct. Viewed labels (crops) are joined from `--labels` when given.
Usage (repo root):
  PYTHONPATH=src python scripts/qa_false_alarm_taxonomy.py --old-config OLD.json --out OUT.json \
      --set NAME=RELEASE_DIR,CORPUS_DIR,BEFORE_LEDGER,AFTER_LEDGER [--set ...] [--labels labels.json]
Read-only on releases, corpora, PDFs and ledgers. No randomness.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from graph_builder.corpus.qa import fidelity as fid

BAD = {"WARN", "ERROR"}
INFLATION_WORD_RATIO = 1.2  # K1 word tokens / PDF word tokens at or above this value confirm text inflation on a CHAR_RATIO_HIGH page
PAGE_CODES = ("FIDELITY_NUMERIC_NOVEL", "FIDELITY_NUMERIC_RECALL_LOW", "FIDELITY_WORD_RECALL_LOW", "CHAR_RATIO_HIGH", "CHAR_RATIO_LOW")


def flagged_units(ledger: dict) -> dict[tuple[str, int], dict]:
    units: dict[tuple[str, int], dict] = {}
    for document in ledger["documents"]:
        pages = {page["page"]: page for page in document.get("pages") or []}
        for page in pages.values():
            codes = sorted({s["code"] for s in page.get("signals") or [] if s["severity"] in BAD})
            if codes:
                units[(document["file_id"], page["page"])] = {"doc_id": document["doc_id"], "kind": "page", "codes": codes, "mode": page.get("release_mode"),
                                                              "signals": [s for s in page["signals"] if s["severity"] in BAD]}
        for table in document.get("tables") or []:
            signals = [s for s in table.get("signals") or [] if s["severity"] in BAD]
            if signals and table.get("pages"):
                key = (document["file_id"], min(table["pages"]))
                unit = units.setdefault(key, {"doc_id": document["doc_id"], "kind": "table", "codes": [], "mode": None, "signals": []})
                unit["codes"] = sorted(set(unit["codes"]) | {s["code"] for s in signals})
                unit["signals"] += signals
    return units


def classify_table(unit: dict) -> str:
    text = json.dumps([s.get("evidence") for s in unit["signals"] if s["code"].startswith("XREP")])
    if "&#124;" in text and "|" in text:
        return "markdown_syntax"
    if "Ref." in text or "header" in text:
        return "table_header_repetition_or_span"
    return "table_other"


def fidelity_pass(state, file_id: str, page: int, mode: str, config: dict) -> dict | None:
    raw, _ = state.analyse(file_id, page)
    if raw is None:
        return None
    k1_empty = state.k1_text(file_id, page).strip() == ""
    codes = [code for code, _ in fid.judge(raw, mode, k1_empty, config)]
    flagging = set(PAGE_CODES) | ({fid.MARKER_CODE} if fid.marker_severity(config) == "WARN" else set())  # A-445: lost list numbers flag again
    return {"raw": raw, "codes": codes, "warn": sorted(set(codes) & flagging)}


def numeric_in_scale_runs(pdf_text: str, missing: set[str], min_run: int = 4) -> bool:
    """True when every missing numeric token belongs to a run of at least ``min_run`` consecutive bare numbers on a PDF line
    (axis or scale labels of a plot). A label of the taxonomy only: such labels are NOT excluded from the recall."""
    on_runs: set[str] = set()
    for line in pdf_text.splitlines():
        run: list[str] = []
        for part in line.split() + [""]:  # the empty sentinel closes the last run
            if part and fid.NUMBER.fullmatch(fid.normalise(part)):
                run.append(fid.normalise(part))
            else:
                if len(run) >= min_run:
                    on_runs.update(run)
                run = []
    return bool(missing) and missing <= on_runs


def classify_page(unit: dict, state_old, state_new, key: tuple[str, int], old_config: dict, new_config: dict) -> tuple[str, dict]:
    file_id, page = key
    codes, mode = unit["codes"], unit["mode"] or "text"
    detail: dict = {}
    if "PAGE_STATUS_MISSING" in codes:
        return "page_status_missing_ocr_page", detail
    old = fidelity_pass(state_old, file_id, page, mode, old_config) if mode != "ocr" else None
    new = fidelity_pass(state_new, file_id, page, mode, new_config) if mode != "ocr" else None
    if old is not None and new is not None:
        o, n = old["raw"], new["raw"]
        detail = {"words_k1_over_pdf": round(o["word"]["k1_tokens"] / max(o["word"]["pdf_tokens"], 1), 2),
                  "block_furniture_tokens": n["word"]["missing_furniture_repeated_line"] + n["numeric"]["missing_furniture_repeated_line"]
                  - o["word"]["missing_furniture_repeated_line"] - o["numeric"]["missing_furniture_repeated_line"],
                  "enumerator_marker_tokens": n["numeric"]["missing_enumerator_marker"]}
        fidelity_before = [c for c in codes if c.startswith("FIDELITY_")]
        if fidelity_before and not new["warn"]:
            block, enum = detail["block_furniture_tokens"] > 0, detail["enumerator_marker_tokens"] > 0
            return ("cleared_header_footer_block_and_enumerators" if block and enum else "cleared_header_footer_block" if block
                    else "cleared_enumerator_markers" if enum else "cleared_other"), detail
        if new["warn"] == [fid.MARKER_CODE]:  # A-445 (owner direction D2): the numbers are lost although the item text is kept; this is a real, minor loss and stays WARN
            return "enumerator_markers_lost_still_warn", detail
        if "CHAR_RATIO_HIGH" in codes and not fidelity_before:
            return ("text_inflation_confirmed_by_word_excess" if detail["words_k1_over_pdf"] >= INFLATION_WORD_RATIO else "char_ratio_high_unexplained"), detail
        if "CHAR_RATIO_LOW" in codes or "PAGE_EMPTY_EXTRACTION" in codes:
            return "text_missing_confirmed_by_recall" if (o["word"]["recall_raw"] or 1) < 0.9 else "char_ratio_low_unexplained", detail
        if "CHAR_RATIO_HIGH" in codes:
            return ("text_inflation_confirmed_by_word_excess" if detail["words_k1_over_pdf"] >= INFLATION_WORD_RATIO else "char_ratio_high_unexplained"), detail
        missing_words = new["raw"]["word"]["_content_missing"]
        missing_numbers = new["raw"]["numeric"]["_content_missing"]
        if mode == "hybrid":
            return "hybrid_page_ocr_text_differs_from_text_layer", detail
        if missing_words and not missing_numbers and all(len(w) == 1 for w in missing_words):
            return "split_letter_fragments", detail
        if missing_numbers and not missing_words and numeric_in_scale_runs(state_new.pdf_page(file_id, page)[0], set(missing_numbers)):
            return "numeric_scale_run_labels_missing", detail
        if "FIDELITY_NUMERIC_NOVEL" in codes and not missing_numbers:
            return "numeric_novel_without_numeric_loss", detail
        return "remaining_content_candidate_unclassified", detail
    if "CHAR_RATIO_HIGH" in codes or "CHAR_RATIO_LOW" in codes:
        return "char_ratio_without_pdf_reference", detail
    return "other", detail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", action="append", required=True, metavar="NAME=RELEASE,CORPUS,BEFORE,AFTER")
    parser.add_argument("--old-config", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/qa/source_fidelity.json"))
    parser.add_argument("--labels", type=Path, help="json {NAME: {'DOC:PAGE': 'TP'|'FP'|'UNCLEAR'}} of viewed crops")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    old_config, new_config = fid.load_config(args.old_config), fid.load_config(args.config)
    labels = json.loads(args.labels.read_text(encoding="utf-8")) if args.labels else {}
    report: dict = {"old_config_sha256": fid.sha256_file(args.old_config), "config_sha256": fid.sha256_file(args.config), "sets": {}}
    for item in args.set:
        name, rest = item.split("=", 1)
        release, corpus, before_path, after_path = rest.split(",")
        before = flagged_units(json.loads(Path(before_path).read_text(encoding="utf-8")))
        after = flagged_units(json.loads(Path(after_path).read_text(encoding="utf-8")))
        state_old, state_new = fid.FidelityState(Path(release), Path(corpus), old_config), fid.FidelityState(Path(release), Path(corpus), new_config)
        rows = []
        for key in sorted(before, key=lambda k: (before[k]["doc_id"], k[1])):
            unit = before[key]
            if unit["kind"] == "table" and not any(c.startswith("FIDELITY") or c.startswith("CHAR") or c.startswith("PAGE") for c in unit["codes"]):
                cls, detail = "xrep_" + classify_table(unit), {}
            else:
                try:
                    cls, detail = classify_page(unit, state_old, state_new, key, old_config, new_config)
                except Exception as error:  # noqa: BLE001 - one broken page must not lose the other rows
                    cls, detail = "classification_error", {"error": type(error).__name__}
            label = labels.get(name, {}).get(f"{unit['doc_id'][:40]}:{key[1]}")
            rows.append({"doc_id": unit["doc_id"], "file_id": key[0], "page": key[1], "kind": unit["kind"], "codes_before": unit["codes"],
                         "still_flagged_after": key in after, "codes_after": after[key]["codes"] if key in after else [], "class": cls, "detail": detail,
                         "viewed_label": label})
        state_old.close()
        state_new.close()
        counts = Counter(r["class"] for r in rows)
        still = Counter(r["class"] for r in rows if r["still_flagged_after"])
        report["sets"][name] = {"flagged_before": len(rows), "flagged_after_of_these": sum(r["still_flagged_after"] for r in rows),
                                "flagged_after_total": len(after), "new_flags_not_flagged_before": sorted(f"{after[k]['doc_id'][:30]}:{k[1]}" for k in after if k not in before),
                                "class_counts": dict(sorted(counts.items())), "class_still_flagged": dict(sorted(still.items())), "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for name, entry in report["sets"].items():
        print(name, entry["flagged_before"], "->", entry["flagged_after_total"], json.dumps(entry["class_counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
