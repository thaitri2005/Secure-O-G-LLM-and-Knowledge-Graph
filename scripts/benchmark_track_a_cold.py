"""Measure cold-document Track A latency with local Docling models and full QA."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import load_config
from graph_builder.corpus.k1_config import load_k1_config
from graph_builder.corpus.k1_export import export_k1
from graph_builder.corpus.process import run as process
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.store import atomic_write_json, file_sha256

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "configs/benchmarks/track_a_scale_holdout.json"
COHORT = (
    "forge-16a-dailyreport-003", "forge-16a-dailyreport-017", "forge-16a-dailyreport-038", "forge-16a-dailyreport-070",
    "forge-78b-dailyreport", "new-crown-1-dailyreport", "armour-myrtle-basin-dailyreport", "eastern-palm-valley-dailyreport",
)


def conversion(folder, source, settings, pdf, models, *, reuse):
    path = folder / "conversion.json"
    if reuse:
        record = json.loads(path.read_text(encoding="utf-8"))
        corpus = Corpus(folder / "corpus")
        if (record["sha256"] != source["sha256"] or corpus.config != settings
                or {row["doc_id"]: row["sha256"] for row in corpus.documents()} != {source["doc_id"]: source["sha256"]}):
            raise ValueError(f"Cached timing or source config differs in {folder}")
        return corpus, record

    folder.mkdir(parents=True, exist_ok=False)
    start = perf_counter()
    corpus = Corpus.create(folder / "corpus", settings)
    added, reason = corpus.add_file(pdf, doc_id=source["doc_id"])
    if added != "added":
        raise RuntimeError(f"{pdf}: {added} {reason}")
    registered = perf_counter()
    counts = process(corpus, models, workers=1, heartbeat=25, report=lambda line: print(line, flush=True))
    processed = perf_counter()
    if counts["done"] != 1 or counts["failed"]:
        raise RuntimeError(f"Cold conversion did not complete: {counts}")
    record = {"doc_id": source["doc_id"], "pages": source["pages"], "sha256": source["sha256"],
              "register_seconds": registered - start, "process_seconds": processed - registered}
    atomic_write_json(path, record)
    return corpus, record


def benchmark(pdf_dir, out, settings, models, specs, *, reuse):
    records = []
    profile = load_k1_config()
    for source in specs:
        pdf = pdf_dir / source["file"]
        if file_sha256(pdf) != source["sha256"]:
            raise ValueError(f"PDF does not match the timing manifest: {pdf}")
        folder = out / source["doc_id"]
        corpus, record = conversion(folder, source, settings, pdf, models, reuse=reuse)
        started = perf_counter()
        export = export_k1(corpus, "cold-k1", models, profile)
        exported = perf_counter()
        result = run_qa(corpus.root, Path(export["export"]), folder / "qa", None, None, fidelity=True, crossrep=True, cell_evidence=True)
        finished = perf_counter()
        if result["validator"] != "pass" or export["pages"] != source["pages"]:
            raise RuntimeError(f"Cold export did not validate for {source['doc_id']}")
        total = record["register_seconds"] + record["process_seconds"] + finished - started
        row = dict(record, source_file=pdf.name, k1_seconds=exported - started, qa_seconds=finished - exported,
                   total_seconds=total, release=export["export"])
        records.append(row)
        atomic_write_json(folder / "timing.json", row)
        print(json.dumps(row), flush=True)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--corpus-config", type=Path)
    parser.add_argument("--only", nargs="+", choices=COHORT, help="measure one or more PDFs from the timing cohort")
    parser.add_argument("--reuse-conversion", action="store_true", help="measure K1 and QA using previously timed cold conversions")
    args = parser.parse_args()

    settings = load_config(args.corpus_config or ROOT / "configs/corpus/default.json")
    if args.corpus_config is None:
        settings["ocr"].update(engine="rapidocr", languages=["en"])
        settings["filters"]["running_line_min_pages"] = 3
    manifest = json.loads(REFERENCE.read_text(encoding="utf-8"))
    specs = [source for source in manifest["documents"] if source["doc_id"] in (args.only or COHORT)]
    records = benchmark(args.pdf_dir, args.out, settings, args.models.resolve(), specs, reuse=args.reuse_conversion)
    durations = [row["total_seconds"] for row in records]
    pages = sum(row["pages"] for row in records)
    report = {"measure": "uncached PDF conversion with local model weights, K1 and full QA",
              "workers": 1, "files": len(records), "pages": pages, "total_seconds": sum(durations),
              "p50_seconds_per_pdf": median(durations),
              "p95_seconds_per_pdf": quantiles(durations, n=100, method="inclusive")[94] if len(durations) > 1 else durations[0],
              "batch_seconds_per_page": sum(durations) / pages, "documents": records}
    atomic_write_json(args.out / "results.json", report)


if __name__ == "__main__":
    main()
