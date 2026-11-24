"""Produce K1 releases for the scan-cell benchmark from pinned originals."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from time import perf_counter

import pymupdf
from PIL import Image

if __package__:
    from .benchmark_track_a_scan_cells import GOLD, ROOT, digest, verify_input
else:
    from benchmark_track_a_scan_cells import GOLD, ROOT, digest, verify_input

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import load_config, validate_config
from graph_builder.corpus.k1_config import load_k1_config
from graph_builder.corpus.k1_export import export_k1
from graph_builder.corpus.process import run
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.store import atomic_write_json


def make_input(original, target, source, selected_pages, full):
    if spec := source.get("raster_window"):
        with Image.open(original) as raster, io.BytesIO() as buffer, pymupdf.open() as doc:
            window = raster.crop(tuple(spec["pixels"]))
            window.save(buffer, format="PNG")
            page = doc.new_page(width=window.width * 72 / spec["dpi"], height=window.height * 72 / spec["dpi"])
            page.insert_image(page.rect, stream=buffer.getvalue())
            doc.save(target)
        return target, [1]
    with pymupdf.open(original) as pdf:
        if full:
            return original, list(range(1, len(pdf) + 1))
        with pymupdf.open() as selected:
            for page in selected_pages:
                selected.insert_pdf(pdf, from_page=page - 1, to_page=page - 1)
            selected.save(target)
    return target, selected_pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=GOLD)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--corpus-config", type=Path)
    parser.add_argument("--only", nargs="+", help="Run only these source IDs")
    parser.add_argument("--full-pdf", nargs="+", default=[], help="Process the complete original PDF for these source IDs")
    args = parser.parse_args()
    spec = json.loads(args.gold.read_text(encoding="utf-8"))
    ids = set(spec["sources"])
    if (set(args.only or ()) | set(args.full_pdf)) - ids:
        parser.error("Use source IDs from the gold file")
    settings = load_config(args.corpus_config or ROOT / "configs/corpus/default.json")
    if args.corpus_config is None:
        settings["ocr"].update(engine="rapidocr", languages=["en"])
        settings["filters"]["running_line_min_pages"] = 3
        settings = validate_config(settings)
    models = args.models.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    results = out / "runs.json"
    runs = json.loads(results.read_text(encoding="utf-8")) if results.is_file() else {}
    for name, source in spec["sources"].items():
        if args.only and name not in args.only:
            continue
        original = (args.pdf_dir / source["file"]).resolve()
        if digest(original) != source["sha256"]:
            raise ValueError(f"Source hash differs for {original}")
        folder = out / name
        folder.mkdir(exist_ok=False)
        selected = sorted({case["source_page"] for case in spec["cases"] if case["source"] == name})
        pdf, pages = make_input(original, folder / "source.pdf", source, selected, name in args.full_pdf)
        verify_input(original, pdf, source, pages)
        corpus = Corpus.create(folder / "corpus", settings)
        status, reason = corpus.add_file(pdf, doc_id=name)
        if status != "added":
            raise RuntimeError(f"Could not register {pdf}: {reason}")
        start = perf_counter()
        result = run(corpus, models, workers=1, heartbeat=25, report=lambda line: print(line, flush=True))
        converted = perf_counter()
        if result["done"] != 1 or result["failed"]:
            raise RuntimeError(f"Conversion failed for {name}: {result}")
        release = Path(export_k1(corpus, "scan-cells", models, load_k1_config())["export"])
        exported = perf_counter()
        qa_dir = folder / "qa"
        qa = run_qa(corpus.root, release, qa_dir, None, None, crossrep=True, fidelity=True, cell_evidence=True, models=models)
        if "retrieval_view" not in qa:
            raise RuntimeError(f"QA could not publish the scan retrieval view for {release}: {qa['ledger']}")
        timings = dict(process_seconds=converted - start, k1_seconds=exported - converted, qa_seconds=perf_counter() - exported)
        runs[name] = dict(release=str(release), pdf=str(pdf), pages=pages, qa=str(qa_dir), timings=timings)
        atomic_write_json(results, runs)


if __name__ == "__main__":
    main()
