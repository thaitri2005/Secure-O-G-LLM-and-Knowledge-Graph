"""Compare Track A's K1 profiles on a pinned drilling-report corpus."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import resource
from time import perf_counter

from benchmark_form_overlap import coverage, released_pages, stage_pdfs, table_cells
from benchmark_track_a_ablation import (Corpus, MODELS, ROOT, configs, export_k1, load_k1_config,
                                        native_samples, options, process, read_json, references, register_corpus)
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.store import atomic_write_json, read_jsonl


def cpu_seconds() -> float:
    usage = [resource.getrusage(who) for who in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)]
    return sum(item.ru_utime + item.ru_stime for item in usage)


def profiles(hourly_ablation=False):
    default = load_k1_config()
    # Keep the recorded E38 and E41 comparisons focused on their original rules.
    for rule in ("mud_properties", "ruled_panels", "daily_log", "well_completion", "scan_fields"):
        default["table_rules"].pop(rule, None)
    default["table_rules"]["operations_summary"]["schema"]["patterns"]["code"] = r"^[A-Za-z][A-Za-z0-9/&_-]*$"
    if hourly_ablation:
        baseline = deepcopy(default)
        baseline["table_rules"].pop("hourly_operations")
        yield "before", baseline
        yield "hourly_operations", default
        return
    default["forms"].pop("missing_report_fields", None)  # Preserve the E38 profiles.
    default["table_rules"].pop("hourly_operations", None)
    baseline = deepcopy(default)
    baseline["forms"].pop("daily_header")
    baseline["table_rules"].pop("casing")
    yield "before", baseline
    yield "default", default
    generic = deepcopy(default)
    generic["forms"]["generic"] = True
    yield "generic_forms", generic


def unseen_pages(source: dict) -> set[int]:
    if source["cohort"] == "regression":
        return set()
    return set(range(1, source["pages"] + 1)) - set(source.get("prior_review_pages", ()))


def score_hourly(reference: dict, release: Path) -> dict:
    """Count ordered source intervals and require a unique daily log on each tested page."""
    by_page = defaultdict(list)
    for table in read_jsonl(release / "tables.jsonl"):
        if table["doc_id"] != reference["doc_id"]:
            continue
        for part in table["parts"]:
            if part["header"] == [reference["header"]]:
                rows = table["grid"][part["row_start"] + 1:part["row_end"]]
                by_page[part["page"]].append([row[:2] for row in rows])
    development = set(reference["development_pages"])
    totals = defaultdict(Counter)
    incomplete = []
    for number, expected in reference["rows"].items():
        page = int(number)
        found = by_page[page]
        observed = found[0] if len(found) == 1 else []
        counts = dict(pages=1, exact_pages=int(observed == expected), expected_rows=len(expected),
                      ordered_row_matches=sum(a == b for a, b in zip(expected, observed)),
                      ambiguous_pages=int(len(found) > 1))
        totals["all"].update(counts)
        totals["development" if page in development else "other_pages"].update(counts)
        if observed != expected:
            incomplete.append({"page": page, "matching_tables": len(found), "expected": expected, "observed": observed})
    return {**{key: dict(value) for key, value in totals.items()}, "incomplete_pages": incomplete}


def score(samples, source, original, release: Path, qa: dict, *, allow_table_overlap=False) -> dict:
    tables = defaultdict(list)
    for table in read_jsonl(release / "tables.jsonl"):
        tables[table["doc_id"]].append(table)
    chunks = list(read_jsonl(release / "chunks.jsonl"))
    view = {row["chunk_id"]: row for row in read_jsonl(Path(qa["retrieval_view"]["path"]))}
    canonical = released_pages(chunks)
    retrieval = released_pages(chunks, view, allow_table_overlap=allow_table_overlap)
    documents = {}
    for sample in samples:
        spec = source[sample.name]
        raw = original[sample.name]
        full, canonical_hits = coverage(sample, raw, canonical)
        projected, hits = coverage(sample, raw, retrieval)
        expected = {(page, probe) for page, probes in sample.critical.items() for probe in probes}
        new_pages = unseen_pages(spec)
        new_probes = {page: probes for page, probes in sample.critical.items() if page in new_pages}
        new_expected = {(page, probe) for page, probe in expected if page in new_pages}
        new_raw = [pair if i in new_pages else (Counter(), Counter()) for i, pair in enumerate(raw, 1)]
        new_metrics, _ = coverage(replace(sample, critical=new_probes), new_raw, retrieval)
        cells = table_cells(spec, tables[sample.name])
        documents[sample.name] = {
            "family": spec["family"], "pages": sample.pages, "unseen_pages": len(new_pages),
            "phrase_expected": len(expected), "phrase_matches": sorted(hits),
            "missing_phrases": sorted(expected - hits), "phrases_lost_in_retrieval": sorted(canonical_hits - hits),
            "unseen_phrase_expected": len(new_expected), "table_cells": cells,
            "unseen_cells_expected": sum(p["page"] in new_pages for p in spec.get("table_cells", ())),
            "unseen_cells_missing": sum(p["page"] in new_pages for p in cells["missing"]),
            "k1": full, "retrieval": projected, "unseen_retrieval": new_metrics,
        }
    return documents


def summarize(documents: dict, unseen: bool = False) -> dict:
    totals = defaultdict(Counter)
    for row in documents.values():
        scope = "unseen_" if unseen else ""
        pages = row[scope + "pages"]
        if not pages:
            continue
        metrics = row[scope + "retrieval"]
        if unseen:
            cell_total, cell_missed = row["unseen_cells_expected"], row["unseen_cells_missing"]
        else:
            cell_total, cell_missed = row["table_cells"]["expected"], len(row["table_cells"]["missing"])
        counts = {
            "documents": 1, "pages": pages, "phrases": row[scope + "phrase_expected"],
            "phrases_matched": metrics["critical"], "cells": cell_total, "cells_matched": cell_total - cell_missed,
            "words": metrics["words"]["expected"], "words_matched": metrics["words"]["matched"],
            "numbers": metrics["numbers"]["expected"], "numbers_matched": metrics["numbers"]["matched"],
            "numeric_surplus": metrics["numbers"]["surplus"],
        }
        for key in ("all", row["family"]):
            totals[key].update(counts)
    return {key: dict(value) for key, value in totals.items()}


def changes(before: dict, after: dict) -> dict:
    totals = defaultdict(Counter)
    for document, row in after.items():
        previous = before[document]
        old_hits = set(previous["phrase_matches"])
        new_hits = set(row["phrase_matches"])
        cell_keys = ("page", "row", "column", "value")
        old_misses = {tuple(cell[key] for key in cell_keys) for cell in previous["table_cells"]["missing"]}
        new_misses = {tuple(cell[key] for key in cell_keys) for cell in row["table_cells"]["missing"]}
        for key in ("all", row["family"]):
            totals[key].update(phrases_gained=len(new_hits - old_hits), phrases_lost=len(old_hits - new_hits),
                               cells_gained=len(old_misses - new_misses), cells_lost=len(new_misses - old_misses))
    return {key: dict(value) for key, value in totals.items()}


def convert_corpus(corpus, workers: int) -> dict:
    """Keep parallel submissions within one worker lifetime on Python 3.12."""
    if workers <= 1:
        return process.run(corpus, MODELS, workers=1, retry_failed=True)
    ids = [doc["doc_id"] for doc in corpus.documents()]
    counts = Counter()
    # The executor retires a worker after 20 jobs. A larger queued batch can stall when workers retire.
    for start in range(0, len(ids), 20):
        counts.update(process.run(corpus, MODELS, workers=workers, retry_failed=True, only=ids[start:start + 20]))
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "configs/benchmarks/track_a_scale_holdout.json")
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--reuse-corpus", type=Path, help="processed corpus matching all manifest files")
    parser.add_argument("--processing-stats", type=Path, help="timings of a separately measured conversion run")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--hourly-ablation", action="store_true", help="compare the current K1 default with the hourly rule disabled")
    parser.add_argument("--hourly-reference", type=Path, help="pinned source time intervals to score in K1")
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    if args.fetch:
        stage_pdfs(manifest, args.pdf_dir)
    samples = list(native_samples(args.manifest, args.pdf_dir))
    original = references(samples)
    source = {entry["doc_id"]: entry for entry in manifest["documents"]}
    hourly_reference = read_json(args.hourly_reference) if args.hourly_reference else None
    if hourly_reference and source[hourly_reference["doc_id"]]["sha256"] != hourly_reference["sha256"]:
        raise ValueError("The hourly reference must use the source PDF from the main manifest")
    processing = read_json(args.processing_stats) if args.processing_stats else None
    config, _, _ = configs(["running_line_min_pages"], options())
    if args.reuse_corpus:
        corpus = Corpus(args.reuse_corpus)
    else:
        corpus_path = args.out / "corpus"
        corpus = Corpus(corpus_path) if (corpus_path / "catalog.sqlite").is_file() else register_corpus(corpus_path, config, samples)
    registered = {doc["doc_id"]: doc["sha256"] for doc in corpus.documents()}
    if registered != {key: value["sha256"] for key, value in source.items()} or corpus.config != config:
        raise ValueError("Corpus configuration and registered PDFs must match the benchmark")
    if not args.reuse_corpus:
        wall, cpu = perf_counter(), cpu_seconds()
        counts = convert_corpus(corpus, args.workers)
        processing = {"wall_seconds": perf_counter() - wall, "cpu_seconds": cpu_seconds() - cpu,
                      "counts": counts, "workers": args.workers}
        atomic_write_json(args.out / "processing.json", processing)
        if counts["failed"] or counts["not_started"]:
            raise RuntimeError(f"Native conversion did not complete: {counts}")

    results = {"processing": processing, "profiles": {}}
    for name, k1 in profiles(args.hourly_ablation):
        start = perf_counter()
        exported = export_k1(corpus, f"scale-{name}", MODELS, k1)
        export_seconds = perf_counter() - start
        release = Path(exported["export"])
        start = perf_counter()
        qa = run_qa(corpus.root, release, args.out / name / "qa", None, None, fidelity=True, crossrep=True,
                    form_overlap=True, table_overlap=False, ruled_table_overlap=False, compact_table_spans=False)
        qa_seconds = perf_counter() - start
        if qa["validator"] != "pass":
            raise ValueError(f"Structural QA failed for {name}: {qa['ledger']}")
        docs = score(samples, source, original, release, qa)
        repairs = exported.get("casing_tables", {})
        summary = summarize(docs)
        earlier = results["profiles"].get("before", {}).get("documents", docs)
        results["profiles"][name] = {
            "export_seconds": export_seconds, "qa_seconds": qa_seconds, "qa": qa, "release": str(release),
            "casing_decisions": repairs, "summary": summary, "unseen": summarize(docs, unseen=True),
            "changes_from_before": changes(earlier, docs), "documents": docs,
        }
        if args.hourly_ablation:
            results["profiles"][name]["hourly_decisions"] = exported.get("hourly_operations", {})
        if hourly_reference:
            results["profiles"][name]["hourly_reference"] = score_hourly(hourly_reference, release)
        atomic_write_json(args.out / "results.json", results)
        print(f"{name}: K1 {export_seconds:.1f}s, QA {qa_seconds:.1f}s, {summary['all']}", flush=True)


if __name__ == "__main__":
    main()
