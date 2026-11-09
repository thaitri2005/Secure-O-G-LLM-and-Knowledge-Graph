"""A-402 evaluation: source fidelity check on real releases, synthetic corruptions, runtime and memory.

Run (repo root):  PYTHONPATH=src explorations/ingestion/.venvs/docling/Scripts/python.exe -B scripts/qa_fidelity_eval.py
Writes data/interim/overnight/a402/eval.json (counts with denominators). Read-only on releases, corpus and PDFs.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import sys
import time

import psutil

from graph_builder.corpus.qa import fidelity as fid

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/interim/k1-run/corpus"
RELEASES = {
    "a107_round2": CORPUS / "exports/ops-rebuild-r3-e2/releases/20261108T174020Z-e34a87c780d8",
    "k1_legacy": CORPUS / "exports/k1-legacy/releases/20261106T181142Z-67e8a9a1c73b",
}
OUT = ROOT / "data/interim/overnight/a402"
WARN_CODES = {"FIDELITY_NUMERIC_NOVEL", "FIDELITY_NUMERIC_RECALL_LOW", "FIDELITY_WORD_RECALL_LOW", "FIDELITY_PAGE_EMPTY"}


def release_pages(release: Path) -> list[dict]:
    return sorted(fid.iter_jsonl(release / "pages.jsonl"), key=lambda row: (row["file_id"], row["page"]))


def rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1e6


def evaluate_release(name: str, release: Path, config: dict) -> tuple[dict, list[dict], list[dict]]:
    """Per-page results for one release. Returns (summary, page rows, clean text-mode rows for the synthetic tests)."""
    state = fid.FidelityState(release, CORPUS, config)
    rows, per_page_ms, peak = [], [], rss_mb()
    start = time.perf_counter()
    for page in release_pages(release):
        mode = page.get("conversion_mode", page.get("mode"))
        row = {"release": name, "file_id": page["file_id"], "doc": state.files[page["file_id"]]["doc_id"][:30], "page": page["page"], "mode": mode}
        t0 = time.perf_counter()
        if mode == "ocr":
            row["codes"] = ["FIDELITY_NOT_APPLICABLE"]
        else:
            raw, error = state.analyse(page["file_id"], page["page"])
            if raw is None:
                row["codes"] = ["FIDELITY_NO_REFERENCE"]
                row["error"] = error
            else:
                k1_empty = state.k1_text(page["file_id"], page["page"]).strip() == ""
                judged = fid.judge(raw, str(mode), k1_empty, config)
                row["codes"] = [code for code, _ in judged]
                metrics = fid.public_metrics(raw, config["max_listed_tokens"]["value"])
                row["word"], row["numeric"] = metrics["word"], metrics["numeric"]
                row["novel_numeric"] = metrics["novel_numeric"]
                row["missing_content_candidate"] = metrics["missing_content_candidate"]
        per_page_ms.append((time.perf_counter() - t0) * 1000)
        peak = max(peak, rss_mb())
        rows.append(row)
    total_s = time.perf_counter() - start
    state.close()
    ordered = sorted(per_page_ms)
    codes = Counter(code for row in rows for code in row["codes"])
    checked = [r for r in rows if r["mode"] == "text" and "word" in r]
    flagged = [r for r in rows if WARN_CODES & set(r["codes"])]
    granted = [r for r in checked if not (WARN_CODES & set(r["codes"])) and not (set(r["codes"]) & {"FIDELITY_INSUFFICIENT_TOKENS", "FIDELITY_NO_REFERENCE"})]
    summary = {
        "pages_total": len(rows), "pages_by_mode": dict(sorted(Counter(r["mode"] for r in rows).items())),
        "text_pages_compared": len(checked), "hybrid_pages_recall_only": sum(r["mode"] == "hybrid" for r in rows),
        "ocr_pages_not_applicable": codes["FIDELITY_NOT_APPLICABLE"], "no_reference": codes["FIDELITY_NO_REFERENCE"],
        "insufficient_tokens": codes["FIDELITY_INSUFFICIENT_TOKENS"],
        "pages_flagged_warn": len(flagged), "flag_codes": {c: codes[c] for c in sorted(WARN_CODES) if codes[c]},
        "flagged_by_mode": dict(sorted(Counter(r["mode"] for r in flagged).items())),
        "text_pages_eligible_for_TEXT_LAYER_CONSISTENT": len(granted),
        "unmodified_release_flag_rate_text_pages": f"{sum(r['mode'] == 'text' for r in flagged)}/{len(checked)}",
        "runtime": {"total_s": round(total_s, 2), "ms_per_page_median": round(ordered[len(ordered) // 2], 1),
                    "ms_per_page_p95": round(ordered[int(len(ordered) * 0.95)], 1), "ms_per_page_mean_incl_open": round(total_s * 1000 / len(rows), 1)},
        "rss_mb_peak": round(peak, 1)}
    return summary, rows, granted


def make_texts(state: fid.FidelityState, row: dict) -> tuple[str, str, str, str]:
    pdf, margin, repeated = state.pdf_page(row["file_id"], row["page"])
    sections = state._sections.get(row["page"], "")  # noqa: SLF001 - evaluation script reads the same sections the check uses
    return pdf, margin, repeated, sections


def flagged(config: dict, pdf: str, margin: str, repeated: str, k1: str, credit: str, k1_empty: bool = False) -> bool:
    raw = fid.compare_page(pdf, k1, margin, repeated, config, credit)
    return any(code in WARN_CODES for code, _ in fid.judge(raw, "text", k1_empty, config))


def numeric_in(text: str) -> list[str]:
    return [m for m in fid.NUMBER.findall(text) if len(m) >= 2 and m.isdigit()]


def corruptions(config: dict, state: fid.FidelityState, rows: list[dict]) -> dict:
    """Deterministic corruptions of the K1 text of pages that the unmodified check does not flag."""
    results = {name: Counter() for name in ("digit_change_all_occurrences", "digit_change_one_occurrence", "sentence_deleted", "sentence_deleted_big",
                                            "fabricated_sentence_with_number", "swap_two_lines", "reverse_line_order", "swap_two_numbers_between_lines")}
    deleted_detail = []
    for row in rows:
        pdf, margin, repeated, credit = make_texts(state, row)
        main = state.k1_text(row["file_id"], row["page"])
        blocks = [b for b in re.split(r"\n\s*\n|\n", main) if b.strip()]
        numbers = numeric_in(main)
        pdf_numbers = set(fid.NUMBER.findall(fid.normalise(pdf)))
        if numbers:
            token = sorted(numbers, key=lambda t: (-main.count(t), t))[0]
            changed = token[:-1] + str((int(token[-1]) + 1) % 10)
            pattern = re.compile(rf"(?<![\d.,]){re.escape(token)}(?![\d.,]*\d)")
            results["digit_change_all_occurrences"]["pages"] += 1
            results["digit_change_all_occurrences"]["flagged"] += flagged(config, pdf, margin, repeated, pattern.sub(changed, main), credit)
            results["digit_change_all_occurrences"]["new_token_present_in_pdf_page"] += changed in pdf_numbers
            results["digit_change_one_occurrence"]["pages"] += 1
            results["digit_change_one_occurrence"]["flagged"] += flagged(config, pdf, margin, repeated, pattern.sub(changed, main, count=1), credit)
        if len(blocks) >= 4:
            middle = blocks[len(blocks) // 2]
            without = main.replace(middle, "", 1)
            share = len(middle.split()) / max(len(main.split()), 1)
            bucket = "sentence_deleted_big" if share >= 0.12 else "sentence_deleted"
            results[bucket]["pages"] += 1
            hit = flagged(config, pdf, margin, repeated, without, credit)
            results[bucket]["flagged"] += hit
            deleted_detail.append({"bucket": bucket, "share_of_page_words": round(share, 3), "flagged": hit})
            swapped = blocks[:]
            swapped[0], swapped[-1] = swapped[-1], swapped[0]
            results["swap_two_lines"]["pages"] += 1
            results["swap_two_lines"]["flagged"] += flagged(config, pdf, margin, repeated, "\n".join(swapped), credit)
            results["reverse_line_order"]["pages"] += 1
            results["reverse_line_order"]["flagged"] += flagged(config, pdf, margin, repeated, "\n".join(reversed(blocks)), credit)
            number_blocks = [i for i, b in enumerate(blocks) if numeric_in(b)]
            if len(number_blocks) >= 2:
                a, b = number_blocks[0], number_blocks[-1]
                na, nb = numeric_in(blocks[a])[0], numeric_in(blocks[b])[0]
                if na != nb:
                    mutated = blocks[:]
                    mutated[a], mutated[b] = blocks[a].replace(na, nb, 1), blocks[b].replace(nb, na, 1)
                    results["swap_two_numbers_between_lines"]["pages"] += 1
                    results["swap_two_numbers_between_lines"]["flagged"] += flagged(config, pdf, margin, repeated, "\n".join(mutated), credit)
        value = 4817
        while str(value) in pdf_numbers or str(value) in main:
            value += 7
        results["fabricated_sentence_with_number"]["pages"] += 1
        results["fabricated_sentence_with_number"]["flagged"] += flagged(
            config, pdf, margin, repeated, main + f"\nThe pressure reached {value} psi at the shoe.\n", credit)
    out = {name: dict(counter) for name, counter in results.items()}
    for name, entry in out.items():
        if entry.get("pages"):
            entry["flag_rate"] = f"{entry.get('flagged', 0)}/{entry['pages']}"
    out["_deleted_detail_buckets"] = {"note": "sentence_deleted = removed block under 12% of the page words, sentence_deleted_big = 12% or more"}
    return out


def main() -> int:
    config = fid.load_config(ROOT / "configs/qa/source_fidelity.json")
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"config_sha256": fid.sha256_file(ROOT / "configs/qa/source_fidelity.json"), "releases": {}, "synthetic": {}}
    all_rows = []
    for name, release in RELEASES.items():
        summary, rows, clean = evaluate_release(name, release, config)
        report["releases"][name] = summary
        all_rows += rows
        state = fid.FidelityState(release, CORPUS, config)
        report["synthetic"][name] = {"clean_text_pages_used": len(clean), **corruptions(config, state, clean)}
        state.close()
    (OUT / "pages.json").write_text(json.dumps(all_rows, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    (OUT / "eval.json").write_text(json.dumps(report, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
