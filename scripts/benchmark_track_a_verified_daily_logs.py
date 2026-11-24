"""Check reconstructed logs against original report rows, page boundaries and cell evidence."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from benchmark_compound_tables import load_view
from benchmark_track_a_natural_layouts import ROOT, page_window, score_daily_log

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import load_config
from graph_builder.corpus.k1_config import load_k1_config
from graph_builder.corpus.k1_export import export_k1
from graph_builder.corpus.process import run as process
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl

REFERENCE = ROOT / "configs/benchmarks/track_a_verified_daily_logs.json"


def score_variant(release, qa_dir, case, source):
    view = load_view(qa_dir / "retrieval_chunks.jsonl", release)
    evidence_summary = json.loads((qa_dir / "cell_evidence_summary.json").read_text(encoding="utf-8"))
    if evidence_summary["release_checksums_sha256"] != file_sha256(release / "SHA256SUMS"):
        raise ValueError(f"Cell evidence does not belong to {release}")
    tables = list(read_jsonl(release / "tables.jsonl"))
    first, last = source["source_pages"]
    score = score_daily_log(case, tables, first)
    expected_pages = {int(page) for page in case["pages"]}
    guard_pages = set(range(first, last + 1)) - expected_pages
    guard_chunks = Counter((page + first - 1, chunk["type"], chunk["text"])
                           for chunk in view.values() for page in chunk["pages"] if page + first - 1 in guard_pages)
    verified_ids = {t["table_id"] for t in tables if t["parts"][0]["source_ref"].startswith("textlayer:daily_log:")}
    verified = Counter(cell["status"] for cell in read_jsonl(qa_dir / "cell_evidence.jsonl") if cell["table_id"] in verified_ids)
    score.update(verified_cells=verified, release=str(release), qa=str(qa_dir))
    return score, guard_chunks


def benchmark(corpus, models, out, case, source):
    results, guards = {}, {}
    for stage in ("before", "after"):
        profile = load_k1_config()
        if stage == "before":
            profile["table_rules"].pop("daily_log")
        release = Path(export_k1(corpus, f"verified-daily-log-{stage}", models, profile)["export"])
        qa_dir = out / f"qa-{stage}"
        run_qa(corpus.root, release, qa_dir, None, None, fidelity=True, crossrep=True, cell_evidence=True)
        results[stage], guards[stage] = score_variant(release, qa_dir, case, source)

    after = results["after"]
    expected = sum(len(rows) for rows in case["pages"].values())
    gates = {"all_rows_and_page_ownership_exact": after["complete_table"],
             "one_header_with_printed_unit": after["unit_in_header_tables"] == 1,
             "all_cells_confirmed": after["verified_cells"] == {"source_supported": 4 * (expected + 1)},
             "outside_table_pages_retained": guards["before"] == guards["after"]}
    return dict(results, gates=gates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--corpus-config", type=Path)
    args = parser.parse_args()
    settings = load_config(args.corpus_config or ROOT / "configs/corpus/default.json")
    if args.corpus_config is None:
        settings["ocr"].update(engine="rapidocr", languages=["en"])
        settings["filters"]["running_line_min_pages"] = 3

    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    results = {}
    models = args.models.resolve()
    for name, source in reference["sources"].items():
        folder = args.out / name
        folder.mkdir(exist_ok=False)
        derived = folder / f"{name}.pdf"
        page_window(args.pdf_dir / source["file"], derived, source)
        corpus = Corpus.create(folder / "corpus", settings)
        status, reason = corpus.add_file(derived, doc_id=source["doc_id"])
        if status != "added":
            raise RuntimeError(f"Could not register {derived}: {reason}")
        counts = process(corpus, models, workers=1, heartbeat=25, report=lambda line: print(line, flush=True))
        if counts["done"] != 1 or counts["failed"]:
            raise RuntimeError(f"Conversion did not complete: {counts}")
        results[name] = benchmark(corpus, models, folder, reference["cases"][name], source)
        atomic_write_json(args.out / "results.json", results)
    print({name: report["gates"] for name, report in results.items()})
    return int(not all(all(result["gates"].values()) for result in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
