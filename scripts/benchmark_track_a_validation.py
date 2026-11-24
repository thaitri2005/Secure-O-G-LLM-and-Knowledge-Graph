"""Run the pinned Track A source validation and record conversion, export and QA timings."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import NamedTemporaryFile
from time import perf_counter

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import fingerprint, load_config
from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config
from graph_builder.corpus.k1_export import export_k1
from graph_builder.corpus.ocr_engines import DEFAULT_MODELS, engine_fingerprint
from graph_builder.corpus.process import run
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.store import atomic_write_json, file_sha256

if __package__:
    from .score_track_a_validation import REFERENCE, ROOT, SOURCES, score_release
else:
    from score_track_a_validation import REFERENCE, ROOT, SOURCES, score_release


def pinned_input(entry: dict, directory: Path) -> Path:
    from urllib.request import urlopen

    kind = entry["format"]
    if kind not in ("pdf", "jpeg") or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", entry["id"]):
        raise ValueError(f"Invalid source entry: {entry['id']}")
    target = directory / (entry["id"] + (".pdf" if kind == "pdf" else ".jpg"))
    if target.exists():
        if file_sha256(target) != entry["sha256"]:
            raise ValueError(f"Input checksum differs: {target}")
        return target

    if not entry["source"].startswith("https://"):
        raise ValueError(f"Expected a pinned HTTPS source for {entry['id']}")
    with NamedTemporaryFile(dir=directory, prefix=".download-", delete=False) as temporary:
        partial = Path(temporary.name)
    try:
        with urlopen(entry["source"], timeout=60) as response, partial.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        if file_sha256(partial) != entry["sha256"]:
            raise ValueError(f"Downloaded checksum differs for {entry['id']}")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def wrap_chart(image: Path, target: Path) -> Path:
    """Preserve the original raster with a fixed 144 DPI placement and no text layer."""
    import pymupdf
    from PIL import Image

    with Image.open(image) as source, pymupdf.open() as pdf:
        page = pdf.new_page(width=source.width / 2, height=source.height / 2)
        page.insert_image(page.rect, filename=str(image))
        pdf.save(target, no_new_id=True)
    return target


def run_profile(corpus: Corpus, models: Path, output: Path, profile_name: str,
                entries: list[dict], input_hashes: dict[str, str], reference: dict) -> dict:
    profile = load_k1_config()
    if profile_name == "scan-fallbacks":
        profile.update(recover_broken_scan_grids=True, recover_sparse_scan_rows=True)
    start = perf_counter()
    result = export_k1(corpus, f"track-a-validation-{profile_name}", models, validate_k1_config(profile))
    release = Path(result["export"])
    exported = perf_counter()
    qa_dir = output / f"qa-{profile_name}"
    qa = run_qa(corpus.root, release, qa_dir, None, None, crossrep=True, fidelity=True,
                cell_evidence=True, models=models)
    finished = perf_counter()
    if not qa.get("retrieval_view"):
        raise RuntimeError(f"QA did not publish a retrieval view for {release}")
    report = score_release(release, qa_dir, entries, input_hashes, reference)
    atomic_write_json(output / f"score-{profile_name}.json", report)
    totals = report["summary"].values()
    return {"release": str(release), "qa": str(qa_dir), "k1_seconds": exported - start,
            "qa_seconds": finished - exported, "score": f"score-{profile_name}.json",
            "correct_cells": sum(group.get("correct_cells", 0) for group in totals),
            "reference_cells": sum(group.get("expected_cells", 0) for group in totals),
            "counts": report["release_counts"], "validator": report["qa_validator"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for the corpus and results")
    parser.add_argument("--input-dir", type=Path, help="Reuse or populate a checksum-verified source cache")
    parser.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--only", nargs="+", metavar="DOCUMENT", help="Run selected source IDs")
    parser.add_argument("--compare-scan-fallbacks", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    manifest = json.loads(SOURCES.read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    ids = {entry["id"] for entry in manifest["entries"]}
    unknown = set(args.only or ()) - ids
    if unknown:
        parser.error(f"Unknown source IDs: {', '.join(sorted(unknown))}")
    entries = [entry for entry in manifest["entries"] if not args.only or entry["id"] in args.only]

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = args.input_dir.resolve() if args.input_dir else output / "sources"
    inputs.mkdir(parents=True, exist_ok=True)
    models = args.models.resolve()
    config = load_config(ROOT / "configs/corpus/drilling_reports_en.json")
    corpus = Corpus.create(output / "corpus", config)
    input_hashes = {}
    for entry in entries:
        source = pinned_input(entry, inputs)
        pdf = wrap_chart(source, output / f"{entry['id']}.pdf") if entry["format"] == "jpeg" else source
        status, reason = corpus.add_file(pdf, doc_id=entry["id"], title=entry["id"], source=entry["source"])
        if status != "added":
            raise RuntimeError(f"Could not register {entry['id']}: {reason}")
        input_hashes[entry["id"]] = file_sha256(pdf)

    start = perf_counter()
    converted = run(corpus, models, workers=args.workers, heartbeat=25, report=lambda line: print(line, flush=True))
    conversion_seconds = perf_counter() - start
    settings = engine_fingerprint(models, config["ocr"])
    jobs = corpus.jobs(fingerprint(config, settings["models"]))
    report = {"source_manifest_sha256": file_sha256(SOURCES), "reference_sha256": file_sha256(REFERENCE),
              "workers": args.workers, "conversion_seconds": conversion_seconds, "conversion": converted,
              "input_hashes": input_hashes,
              "documents": {doc_id: {"status": job["status"], "seconds": job["seconds"],
                                     "summary": json.loads(job["summary"]) if job["summary"] else None}
                            for doc_id, job in jobs.items()}, "profiles": {}}
    atomic_write_json(output / "benchmark.json", report)
    if converted["done"] != len(entries) or converted["failed"]:
        raise RuntimeError(f"Conversion did not complete for all documents: {converted}")
    profiles = ("default", "scan-fallbacks") if args.compare_scan_fallbacks else ("default",)
    for profile in profiles:
        result = run_profile(corpus, models, output, profile, entries, input_hashes, reference)
        report["profiles"][profile] = result
        atomic_write_json(output / "benchmark.json", report)
    print(json.dumps(report["profiles"], indent=2), flush=True)


if __name__ == "__main__":
    main()
