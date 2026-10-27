"""Run the document pipeline on the AK-3 appendix portfolio (44 PDFs, 463 pages, 67 scanned).

Downloads and verifies the portfolio (about 25 MB), splits its attachments into separate PDFs, then
initializes, fills, processes and exports the corpus data/corpora/ak3_appendices. Safe to re-run:
finished documents are skipped and an interrupted run resumes.

    python scripts/run_ak3_appendices.py                 # one worker
    python scripts/run_ak3_appendices.py --workers 2     # faster, about 5-6 GB RAM
    python scripts/run_ak3_appendices.py --scanned-only  # only the PDFs that contain scanned pages
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/corpora/ak3_appendices"
INPUTS = ROOT / "data/interim/ak3_appendices_inputs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--scanned-only", action="store_true")
    args = parser.parse_args()
    from graph_builder.ingestion.portfolio import expand_portfolios
    from graph_builder.ingestion.sources import fetch_sources, load_registry
    from graph_builder.corpus.__main__ import main as corpus

    registry = load_registry(ROOT / "configs/sources/gdr_ak3_appendices.json")
    for source in fetch_sources(registry, ROOT):
        print(f"portfolio {source['doc_id']}: {'cached' if source['cached'] else 'downloaded'}, sha256 verified")
    children = expand_portfolios(registry, ROOT)
    INPUTS.mkdir(parents=True, exist_ok=True)
    selected = 0
    for child in children:
        pdf = ROOT / "data/raw" / f"{child['doc_id']}.pdf"
        if args.scanned_only:
            from graph_builder.corpus.analysis import analysis_config, analyze_pdf
            if not any(page.mode == "ocr" for page in analyze_pdf(pdf, analysis_config(None))):
                continue
        target = INPUTS / f"{child['doc_id']}.pdf"
        if not target.exists():
            shutil.copyfile(pdf, target)
        selected += 1
    print(f"{selected} of {len(children)} attachment PDFs selected in {INPUTS}")
    if not (CORPUS / "catalog.sqlite").exists():
        corpus(["init", str(CORPUS)])
    steps = [["add", str(CORPUS), str(INPUTS), "--license-id", "CC-BY-4.0",
              "--license-url", "https://creativecommons.org/licenses/by/4.0/"],
             ["process", str(CORPUS), "--workers", str(args.workers)],
             ["export", str(CORPUS), "--name", "v1"],
             ["status", str(CORPUS)]]
    code = 0
    for step in steps:
        code = corpus(step) or code
    print(f"done; logs in {CORPUS / 'logs'}, export in {CORPUS / 'exports' / 'v1'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
