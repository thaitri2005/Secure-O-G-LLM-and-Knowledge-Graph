"""Build the demo K1 release: the three end-of-well reports of the committed bundle (AK-3, 56-32 and 68-32), AK-3's
four daily-report attachments (appendices 27 to 30) and its non-productive-time report (appendix 23).

    python scripts/build_k1_demo_release.py --raw <folder with the PDFs> --models <ocr_models folder> \
        [--reuse-corpus data/corpora/ak3_appendices] \
        [--corpus data/interim/k1-demo-corpus] [--out data/interim/k1/demo-v2]

Steps: ``init`` a corpus with the candidate's corpus settings (configs/corpus/candidates/demo_corpus.json: rapidocr
for the end-of-well reports' hybrid pages, weather lines kept), ``add`` the eight PDFs (each end-of-well report under
its bundle id, such as ``gdr882_ak3_eowr``, so the legacy chunk map can find it), optionally seed Docling segments
from an earlier corpus, ``process``, ``k1`` with the legacy chunk map, and copy the published release to ``--out``.
``add`` runs every time and skips files already in the corpus, so a corpus built for an earlier version (``ak3-demo-v1``
had only AK-3's report) gains the missing reports and keeps its conversions.

Seeding reuses a cached Docling conversion only when it cannot differ from a fresh one: same document id and SHA-256,
every page of the new page plan in ``text`` mode (no OCR, so the OCR engine plays no part), and exactly the segment
files the new plan asks for. Anything else is converted. The corpus commands are run as subprocesses, so the
outputs are what the documented command line gives. If ``process`` stops (for example out of memory on a busy
machine), run the script again: finished documents and converted segments are kept and reused.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EOWRS = ("gdr882_ak3_eowr", "gdr1295_56-32_eowr", "gdr1153_68-32_eowr")  # bundle doc id = PDF name
APPENDICES = ("gdr882_ak3_appx_23_5_nonproductivetimerpt_160927143525.pdf",
              "gdr882_ak3_appx_27_6_dailyreportdetailrpt_nocost_160920154309.pdf",
              "gdr882_ak3_appx_28_6_dailyreportdetailrpt_160920153612.pdf",
              "gdr882_ak3_appx_29_6_dailyreportgraphicalrpt_160920155318.pdf",
              "gdr882_ak3_appx_30_6_dailyreportsummaryrpt_160920155352.pdf")
LICENSE = ["--license-id", "CC-BY-4.0", "--license-url", "https://creativecommons.org/licenses/by/4.0/"]


def corpus_command(*arguments: str) -> None:
    print("$ python -m graph_builder.corpus " + " ".join(arguments), flush=True)
    subprocess.run([sys.executable, "-m", "graph_builder.corpus", *arguments], cwd=ROOT, check=True)


def seed_segments(corpus_path: Path, previous_path: Path, models: Path) -> list[dict]:
    """Copy cached text-mode segments of documents the earlier corpus already converted; return what was decided."""
    from graph_builder.corpus.analysis import analyze_pdf, segments
    from graph_builder.corpus.catalog import Corpus
    from graph_builder.corpus.config import fingerprint
    from graph_builder.corpus.ocr_engines import engine_fingerprint
    from graph_builder.corpus.process import output_directory
    corpus, previous = Corpus(corpus_path), Corpus(previous_path)
    current = fingerprint(corpus.config, engine_fingerprint(models, corpus.config["ocr"])["models"])
    earlier = {doc["doc_id"]: doc for doc in previous.documents()}
    decisions = []
    for doc in corpus.documents():
        old = earlier.get(doc["doc_id"])
        modes = [page.mode for page in analyze_pdf(corpus.blob(doc["sha256"]), corpus.config["analysis"])]
        wanted = {f"{first:05d}-{last:05d}-{mode}.json.gz" for mode, first, last in segments(modes, corpus.config["segment_pages"])}
        decision = {"doc_id": doc["doc_id"], "pages": len(modes), "modes": sorted(set(modes)), "seeded": False}
        if old is None or old["sha256"] != doc["sha256"]:
            decision["reason"] = "not in the earlier corpus"
        elif set(modes) != {"text"}:
            decision["reason"] = "has OCR or hybrid pages"
        else:
            sources = [folder / "segments" for folder in (previous_path / "work" / doc["doc_id"]).glob("*")
                       if {name for name in wanted} <= {p.name for p in (folder / "segments").glob("*.json.gz")}]
            if not sources:
                decision["reason"] = "no earlier folder holds exactly the planned segments"
            else:
                target = output_directory(corpus, doc["doc_id"], current) / "segments"
                target.mkdir(parents=True, exist_ok=True)
                for name in sorted(wanted):
                    meta = name.replace(".json.gz", ".json.meta.json")
                    shutil.copyfile(sources[0] / name, target / name)
                    shutil.copyfile(sources[0] / meta, target / meta)
                decision.update(seeded=True, source=sources[0].parent.name, segments=sorted(wanted))
        decisions.append(decision)
        print(json.dumps(decision), flush=True)
    return decisions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, required=True, help="folder holding the eight source PDFs")
    parser.add_argument("--models", type=Path, required=True, help="OCR model folder (RapidOcr/ inside)")
    parser.add_argument("--corpus", type=Path, default=ROOT / "data/interim/k1-demo-corpus")
    parser.add_argument("--reuse-corpus", type=Path, help="earlier corpus whose text-mode Docling segments may be reused")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/corpus/candidates/demo_corpus.json")
    parser.add_argument("--k1-config", type=Path, default=ROOT / "configs/corpus/candidates/k1_demo_v1.json")
    parser.add_argument("--legacy-chunks", type=Path, default=ROOT / "data/processed/gdr_chunks_full.jsonl",
                        help="version 0 chunks of the three end-of-well reports, for legacy_chunk_ids.json")
    parser.add_argument("--name", default="demo-v2")
    parser.add_argument("--out", type=Path, default=ROOT / "data/interim/k1/demo-v2")
    args = parser.parse_args(argv)
    corpus = str(args.corpus)
    if not (args.corpus / "catalog.sqlite").is_file():
        corpus_command("init", corpus, "--config", str(args.config))
    for doc_id in EOWRS:
        corpus_command("add", corpus, str(args.raw / f"{doc_id}.pdf"), "--doc-id", doc_id, *LICENSE)
    corpus_command("add", corpus, *(str(args.raw / name) for name in APPENDICES), *LICENSE)
    if args.reuse_corpus:
        seed_segments(args.corpus, args.reuse_corpus, args.models)
    corpus_command("process", corpus, "--models", str(args.models))
    corpus_command("k1", corpus, "--name", args.name, "--models", str(args.models), "--k1-config", str(args.k1_config),
                   "--legacy-chunks", str(args.legacy_chunks))
    from graph_builder.publication import current_release
    release = current_release(args.corpus / "exports" / args.name)
    if args.out.exists():
        shutil.rmtree(args.out)
    shutil.copytree(release, args.out)
    print(f"release {release} copied to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
