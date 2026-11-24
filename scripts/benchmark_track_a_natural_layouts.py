"""Replay opt-in Track A layout rules on SHA-pinned original drilling report pages."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from time import perf_counter
import unicodedata

from benchmark_compound_tables import load_view

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import load_config
from graph_builder.corpus.k1_config import load_k1_config
from graph_builder.corpus.k1_export import export_k1
from graph_builder.corpus.orientation import source_coverage
from graph_builder.corpus.process import run as process
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "configs/benchmarks/track_a_natural_layouts.json"
CANDIDATE = ROOT / "configs/corpus/candidates/k1_full_table_candidate.json"


def normalize(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def page_window(original, derived, spec):
    import pymupdf

    if file_sha256(original) != spec["sha256"]:
        raise ValueError(f"Original PDF does not match the reviewed source: {original}")
    first, last = spec["source_pages"]
    with pymupdf.open(original) as source, pymupdf.open() as output:
        output.insert_pdf(source, from_page=first - 1, to_page=last - 1)
        output.save(derived)
    with pymupdf.open(original) as source, pymupdf.open(derived) as output:
        for page, original_page in zip(output, (source[k - 1] for k in range(first, last + 1)), strict=True):
            if (page.rect != original_page.rect or page.rotation != original_page.rotation
                    or page.get_text("words") != original_page.get_text("words")):
                raise ValueError(f"Source page geometry changed in {derived}")


def score_daily_log(spec, tables, first):
    expected = {int(page): [tuple(row) for row in rows] for page, rows in spec["pages"].items()}
    actual, owners, exact_units = defaultdict(list), [], []
    for table in tables:
        if not table["header_rows"] or table["num_cols"] != 4:
            continue
        header = list(map(normalize, table["grid"][0]))
        prefix = spec["header_prefix"]
        if header[:2] != prefix[:2] or not header[2].startswith(prefix[2]):
            continue
        owners.append([page + first - 1 for page in table["pages"]])
        if f"({spec['depth_unit']})" in header[2]:
            exact_units.append(table["table_id"])
        for part in table["parts"]:
            original_page = part["page"] + first - 1
            for row in table["grid"][max(part["row_start"], table["header_rows"]):part["row_end"]]:
                date, number, depth, desc = map(normalize, row)
                actual[original_page].append((date, number, depth, hashlib.sha256(desc.encode()).hexdigest()))
    report = []
    for page, gold in expected.items():
        seen = actual[page]
        triples = Counter(row[:3] for row in gold) & Counter(row[:3] for row in seen)
        report.append({"source_page": page, "expected_rows": len(gold), "observed_rows": len(seen),
                       "exact_date_number_depth": sum(triples.values()), "exact_rows_including_description": sum((Counter(gold) & Counter(seen)).values()),
                       "ordered_exact": gold == seen,
                       "missed_report_numbers": [row[1] for row in gold if not triples[row[:3]]]})
    return {"pages": report, "logical_owners": owners, "joins_made": sum(len(pages) - 1 for pages in owners),
            "unit_in_header_tables": len(exact_units), "complete_table": owners == [list(expected)] and all(page["ordered_exact"] for page in report)}


def score_ozalpha(spec, tables):
    candidates = [table for table in tables if any("WELL SUMMARY" in row for row in table["grid"][:1])]
    grid = candidates[0]["grid"] if len(candidates) == 1 else []
    pairs = Counter((normalize(left), normalize(right)) for row in grid for left, right in zip(row, row[1:]))
    expected = spec["ozalpha"]["fields"]
    missing = [pair for pair in expected if pairs[tuple(pair)] != 1]
    return {"expected_field_pairs": len(expected), "exact_field_pairs": len(expected) - len(missing), "missing_field_pairs": missing,
            "source_rule_emitted": bool(candidates and candidates[0]["parts"][0]["source_ref"].startswith("textlayer:ruled_panels:well_summary:"))}


def score_zerogen(input_pdf, release, view, qa, first):
    import pymupdf

    evidence = Counter((row["page"], row["status"]) for row in read_jsonl(qa / "cell_evidence.jsonl"))
    table_counts = Counter(page for table in read_jsonl(release / "tables.jsonl") for page in table["pages"])
    ledger = json.loads((qa / "qa-ledger.json").read_text(encoding="utf-8"))
    decisions = {page["page"]: signal["evidence"] for page in ledger["documents"][0]["pages"] for signal in page["signals"]
                 if signal["code"] in ("ROTATED_PAGE_NORMALIZED", "ROTATED_PAGE_UNNORMALIZED")}
    results = []
    with pymupdf.open(input_pdf) as pdf:
        for row in read_jsonl(release / "pages.jsonl"):
            page = row["page"]
            raw = pdf[page - 1].get_text()
            rendered = "\n".join(chunk["text"] for chunk in view.values() if page in chunk["pages"])
            counts, _ = source_coverage(raw, rendered)
            results.append({"source_page": page + first - 1, "rotation_attempts": row["rotation_attempts"],
                            "orientation_decision": decisions.get(page), "coverage": counts,
                            "tables": table_counts[page],
                            "cells_text_matches_region": evidence[page, "text_matches_region"], "cells_review": evidence[page, "review"]})
    return {"pages": results}


def run_case(case, manifest, original, out, settings, models):
    source = manifest["sources"][case]
    out.mkdir(parents=True, exist_ok=False)
    derived = out / f"{source['doc_id']}.pdf"
    page_window(original, derived, source)
    results = {}
    for mode in (("original", "verify") if case == "zerogen" else ("original",)):
        options = deepcopy(settings)
        if mode == "verify":
            options["analysis"]["page_orientation"] = {"mode": "verify"}
        folder = out / mode
        corpus = Corpus.create(folder, options)
        added, reason = corpus.add_file(derived, doc_id=source["doc_id"])
        if added != "added":
            raise RuntimeError(f"{derived}: {added} {reason}")
        start = perf_counter()
        counts = process(corpus, models, workers=1, heartbeat=25, report=lambda line: print(line, flush=True))
        process_seconds = perf_counter() - start
        if counts["done"] != 1 or counts["failed"]:
            raise RuntimeError(f"Conversion did not finish: {counts}")
        profiles = ("core", "full") if case != "zerogen" else ("core",)
        for profile in profiles:
            config = load_k1_config(CANDIDATE) if profile == "full" else load_k1_config()
            for rule in ("daily_log", "well_completion", "scan_fields"):
                config["table_rules"].pop(rule, None)  # Preserve the E50 comparison.
            release = Path(export_k1(corpus, profile, models, config)["export"])
            qa_dir = folder / f"qa-{profile}"
            run_qa(corpus.root, release, qa_dir, None, None, fidelity=True, crossrep=True,
                   cell_evidence=True, orientation=(mode == "verify"))
            results[f"{mode}_{profile}"] = score_case(case, manifest, derived, release, qa_dir, process_seconds)
    return results


def score_case(case, manifest, derived, release, qa_dir, process_seconds):
    view = load_view(qa_dir / "retrieval_chunks.jsonl", release)
    tables = list(read_jsonl(release / "tables.jsonl"))
    if case == "west_moonie":
        score = score_daily_log(manifest[case], tables, manifest["sources"][case]["source_pages"][0])
    elif case == "ozalpha":
        score = score_ozalpha(manifest, tables)
    else:
        score = score_zerogen(derived, release, view, qa_dir, manifest["sources"][case]["source_pages"][0])
    return dict(score, conversion_seconds=process_seconds, release=str(release), qa=str(qa_dir))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--corpus-config", type=Path)
    parser.add_argument("--case", choices=("west_moonie", "ozalpha", "zerogen"), help="run only the selected case in a clean output")
    parser.add_argument("--pages", type=int, nargs=2, metavar=("FIRST", "LAST"), help="original page window for --case zerogen")
    args = parser.parse_args()
    manifest = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if args.pages:
        if args.case != "zerogen" or not 1 <= args.pages[0] <= args.pages[1]:
            parser.error("--pages requires --case zerogen and a positive inclusive page range")
        manifest["sources"]["zerogen"]["source_pages"] = args.pages
    settings = load_config(args.corpus_config or ROOT / "configs/corpus/default.json")
    if args.corpus_config is None:
        settings["ocr"].update(engine="rapidocr", languages=["en"])
        settings["filters"]["running_line_min_pages"] = 3
    settings["analysis"].pop("page_orientation", None)
    args.out.mkdir(parents=True, exist_ok=True)
    results = {}
    for case, spec in manifest["sources"].items():
        if args.case and case != args.case:
            continue
        results[case] = run_case(case, manifest, args.pdf_dir / spec["file"], args.out / case, settings, args.models.resolve())
        atomic_write_json(args.out / "results.json", results)


if __name__ == "__main__":
    main()
