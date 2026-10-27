"""Command line for generic document ingestion.

    python -m graph_builder.corpus init data/corpora/demo [--config configs/corpus/default.json]
    python -m graph_builder.corpus add data/corpora/demo FILES_OR_FOLDERS... [--recursive] [--license-id ID]
    python -m graph_builder.corpus add data/corpora/demo --url https://host/file.pdf [--sha256 HEX]
    python -m graph_builder.corpus analyze data/corpora/demo          # page plan only, no conversion
    python -m graph_builder.corpus process data/corpora/demo [--workers 2] [--retry-failed]
    python -m graph_builder.corpus status data/corpora/demo
    python -m graph_builder.corpus export data/corpora/demo --name v1 [--hold-review]
    python -m graph_builder.corpus models [--engine vietocr]          # download OCR models while online
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import logging
import os
from pathlib import Path
import sys

DEFAULT_MODELS = Path("data/interim/ocr_models")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m graph_builder.corpus", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("init", "add", "analyze", "process", "status", "export", "retire", "models"))
    parser.add_argument("corpus", nargs="?", type=Path)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/corpus/default.json"))
    parser.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--sha256")
    parser.add_argument("--title")
    parser.add_argument("--doc-id")
    parser.add_argument("--license-id", default="unspecified")
    parser.add_argument("--license-url", default="")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--name")
    parser.add_argument("--hold-review", action="store_true")
    parser.add_argument("--engine", default="vietocr")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    log_file = setup_logging(args)
    from .catalog import Corpus, iter_files
    log = logging.getLogger("graph_builder.corpus.cli")

    def print(message: str = "", **_: object) -> None:  # noqa: A001 - every user-facing line also goes to the log
        log.info(message)

    if log_file:
        print(f"log: {log_file}")
    try:
        if args.command == "models":
            os.environ["HF_HUB_OFFLINE"] = "0"
            from .ocr_engines import download_models, ocr_config
            digests = download_models(args.models, ocr_config({"engine": args.engine}))
            print(json.dumps(digests, indent=1))
            return 0
        if args.corpus is None:
            raise ValueError("A corpus directory is required")
        if args.command == "init":
            from .config import load_config
            Corpus.create(args.corpus, load_config(args.config))
            print(f"Created corpus {args.corpus}")
            return 0
        corpus = Corpus(args.corpus)
        if args.command == "add":
            fields = {"license_id": args.license_id, "license_url": args.license_url}
            if args.url:
                outcomes = [(args.url, *corpus.add_url(args.url, args.sha256, title=args.title, doc_id=args.doc_id, **fields))]
            else:
                files = list(iter_files(args.paths, args.recursive))
                if (args.title or args.doc_id) and len(files) != 1:
                    raise ValueError("--title and --doc-id apply to a single file")
                outcomes = [(str(path), *corpus.add_file(path, title=args.title, doc_id=args.doc_id, **fields))
                            for path in files]
            for path, status, detail in outcomes:
                print(f"{status}: {path} -> {detail}")
            totals = Counter(status for _, status, _ in outcomes)
            print(json.dumps(totals))
            return 1 if totals.get("rejected") and not totals.get("added") else 0
        if args.command == "analyze":
            from .analysis import analyze_pdf
            modes, reasons = Counter(), Counter()
            config = corpus.config
            for doc in corpus.documents():
                if doc["format"] != "pdf":
                    modes[doc["format"]] += 1
                    continue
                pages = analyze_pdf(corpus.blob(doc["sha256"]), config["analysis"])
                modes.update(page.mode for page in pages)
                reasons.update(reason for page in pages for reason in page.reasons)
                ocr = sum(page.mode == "ocr" for page in pages)
                print(f"{doc['doc_id']}: {len(pages)} pages, {ocr} OCR, {sum(p.mode == 'hybrid' for p in pages)} hybrid")
            print(json.dumps({"modes": modes, "reasons": reasons}))
            return 0
        if args.command == "process":
            from .process import run
            counts = run(corpus, args.models, workers=args.workers, retry_failed=args.retry_failed, only=args.only,
                         report=print)
            print(json.dumps(counts))
            return 1 if counts["failed"] else 0
        if args.command == "status":
            from .config import fingerprint
            from .ocr_engines import engine_fingerprint
            ocr = engine_fingerprint(args.models, corpus.config["ocr"])
            current = fingerprint(corpus.config, ocr["models"])
            jobs = corpus.jobs(current)
            documents = corpus.documents()
            states = Counter(jobs[doc["doc_id"]]["status"] if doc["doc_id"] in jobs else "pending" for doc in documents)
            with corpus.connect() as connection:
                rejected = connection.execute("SELECT path, reason FROM rejected").fetchall()
            print(json.dumps({"fingerprint": current, "documents": len(documents), "jobs": states,
                              "rejected": len(rejected)}))
            for doc_id, job in sorted(jobs.items()):
                if job["status"] == "failed":
                    print(f"failed {doc_id}: {job['error']}")
            for row in rejected:
                print(f"rejected {row['path']}: {row['reason']}")
            return 0
        if args.command == "export":
            if not args.name:
                raise ValueError("export requires --name")
            from .export import export
            print(json.dumps(export(corpus, args.name, args.models, allow_review=not args.hold_review)))
            return 0
        if args.command == "retire":
            for doc_id in args.only or []:
                corpus.retire(doc_id)
                print(f"retired {doc_id}")
            return 0
    except (OSError, ValueError, RuntimeError) as error:
        log.error(f"FAIL: {error}")
        return 1
    except KeyboardInterrupt:
        log.warning("Interrupted. Finished documents and converted segments are kept; run the same command to resume.")
        return 130
    return 0


def setup_logging(args: argparse.Namespace) -> Path | None:
    """Console and a timestamped file in <corpus>/logs/; third-party chatter only at warning level."""
    from datetime import datetime
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, "corpus_cli", False)]:
        root.removeHandler(handler)  # main() may run several times in one process
        handler.close()
    root.setLevel(logging.WARNING)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    console.corpus_cli = True
    root.addHandler(console)
    logging.getLogger("graph_builder").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    if args.corpus is None or args.command in ("init", "models", "status"):
        return None
    directory = args.corpus / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{args.command}-{datetime.now():%Y%m%d-%H%M%S}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(formatter)
    handler.corpus_cli = True
    root.addHandler(handler)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
