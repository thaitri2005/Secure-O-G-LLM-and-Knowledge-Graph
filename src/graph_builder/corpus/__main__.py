"""Command line for generic document ingestion.

    python -m graph_builder.corpus init data/corpora/demo [--config configs/corpus/default.json]
    python -m graph_builder.corpus add data/corpora/demo FILES_OR_FOLDERS... [--recursive] [--license-id ID]
    python -m graph_builder.corpus add data/corpora/demo --url https://host/file.pdf [--sha256 HEX]
    python -m graph_builder.corpus analyze data/corpora/demo          # page plan only, no conversion
    python -m graph_builder.corpus process data/corpora/demo [--workers 2] [--retry-failed]
    python -m graph_builder.corpus status data/corpora/demo
    python -m graph_builder.corpus export data/corpora/demo --name v1 [--hold-review]
    python -m graph_builder.corpus k1 data/corpora/demo --name v1 [--only DOC_ID...] [--k1-config configs/corpus/k1.json]
                                                        [--legacy-chunks data/processed/gdr_chunks_full.jsonl]
    python -m graph_builder.corpus qa data/corpora/demo --release RELEASE_DIR [--out DIR]   # QA sidecar, read-only
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

from .ocr_engines import DEFAULT_MODELS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m graph_builder.corpus", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("init", "add", "analyze", "process", "status", "export", "k1", "retire", "models", "qa"))
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
    parser.add_argument("--k1-config", type=Path, default=Path("configs/corpus/k1.json"))
    parser.add_argument("--no-mud-properties", action="store_true", help="k1: disable Mud Properties reconstruction for ablation")
    parser.add_argument("--no-ruled-panels", action="store_true", help="k1: disable ruled report panel reconstruction for ablation")
    parser.add_argument("--recover-source-grids", action=argparse.BooleanOptionalAction,
                        help="k1: recover independently verified tables from their printed source columns")
    parser.add_argument("--recover-sparse-scan-rows", action=argparse.BooleanOptionalAction,
                        help="k1: recover corroborated measurement rows from open scan rulings")
    parser.add_argument("--legacy-chunks", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--a107-sidecar", type=Path)
    parser.add_argument("--qa-config", type=Path)
    parser.add_argument("--release-only", action="store_true", help="qa: write diagnostics without publishing a retrieval view")
    parser.add_argument("--fidelity", action="store_true", help="qa: add the A-402 source fidelity check (reads the source PDFs)")
    parser.add_argument("--crossrep", action="store_true", help="qa: add the A-403 cross-representation checks (reads only the release)")
    parser.add_argument("--ops-margin", action="store_true", help="qa: add the A-401a Operations table mark-margin check (reads the source PDFs)")
    parser.add_argument("--annotations", action="store_true", help="qa: add the A-414 'N records not printed' annotation check (reads the source PDFs)")
    parser.add_argument("--label-value", action="store_true", help="qa: add the optional A-432 label-value geometry check (reads the source PDFs; WARN signal only)")
    parser.add_argument("--form-conflict", action="store_true", help="qa: add the optional A-435 form-versus-text-chunk pairing conflict check (reads only the release; WARN signal only)")
    parser.add_argument("--form-overlap", action=argparse.BooleanOptionalAction,
                        help="qa: project source-backed form/text overlaps (default follows the K1 form rules)")
    parser.add_argument("--table-overlap", action=argparse.BooleanOptionalAction,
                        help="qa: project source-proven hourly table overlaps (default follows the K1 hourly rule)")
    parser.add_argument("--ruled-table-overlap", action=argparse.BooleanOptionalAction,
                        help="qa: prefer corroborated mud, casing and ruled panel cells (default follows the K1 table rules)")
    parser.add_argument("--no-ruled-native-margin", action="store_false", dest="ruled_native_margin",
                        help="qa: use strict panel bounds for the native-cell overlap ablation")
    parser.add_argument("--compact-table-spans", action=argparse.BooleanOptionalAction,
                        help="qa: compact repeated horizontal spans in oversized table chunks")
    parser.add_argument("--cell-evidence", action="store_true",
                        help="qa: write original-PDF locations and source review reasons for table cells")
    parser.add_argument("--table-tokenizer", type=Path, help="qa: local tokenizer.json for exact table chunk token counts")
    parser.add_argument("--table-max-tokens", type=int, help="qa: token budget for table chunks, including special tokens")
    parser.add_argument("--orientation", action="store_true", help="qa: add the optional C-03 page-orientation check (reads the orientation records of the work folder, not the PDFs; needs analysis.page_orientation)")
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
        if args.command == "init":
            if args.corpus is None:
                raise ValueError("A corpus directory is required")
            from .config import load_config
            Corpus.create(args.corpus, load_config(args.config))
            print(f"Created corpus {args.corpus}")
            return 0
        if args.command == "qa":  # read-only sidecar; never opens the catalog or writes into the corpus
            from .qa.cli import run as run_qa
            result = run_qa(args.corpus, args.release, args.out, args.qa_config, args.a107_sidecar,
                                    fidelity=args.fidelity, crossrep=args.crossrep, ops_margin=args.ops_margin,
                                    annotations=args.annotations, label_value=args.label_value,
                                    form_conflict=args.form_conflict, orientation=args.orientation,
                                    form_overlap=args.form_overlap, table_overlap=args.table_overlap,
                                    cell_evidence=args.cell_evidence, table_tokenizer_path=args.table_tokenizer,
                                    max_table_tokens=args.table_max_tokens, ruled_table_overlap=args.ruled_table_overlap,
                                    compact_table_spans=args.compact_table_spans, ruled_native_margin=args.ruled_native_margin,
                                    models=args.models, release_only=args.release_only)
            print(json.dumps(result, sort_keys=True))
            return int(result["validator"] != "pass" or result.get("source_validation", {}).get("status") == "fail")
        if args.corpus is None:
            raise ValueError("A corpus directory is required")
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
            return 1 if counts["failed"] or counts["not_started"] else 0
        if args.command == "status":
            from .config import fingerprint
            from .ocr_engines import engine_fingerprint
            from .process import document_state, output_directory
            ocr = engine_fingerprint(args.models, corpus.config["ocr"])
            current = fingerprint(corpus.config, ocr["models"])
            jobs = corpus.jobs(current)
            documents = corpus.documents()
            states = Counter(jobs[doc["doc_id"]]["status"] if doc["doc_id"] in jobs else "pending" for doc in documents)
            # manifest presence only (no digest check): `status` stays cheap; `process` verifies the digests
            derived = {doc["doc_id"]: document_state(output_directory(corpus, doc["doc_id"], current),
                                                     jobs.get(doc["doc_id"]), verify=False) for doc in documents}
            with corpus.connect() as connection:
                rejected = connection.execute("SELECT path, reason FROM rejected").fetchall()
            print(json.dumps({"fingerprint": current, "documents": len(documents), "jobs": states,
                              "states": Counter(state for state, _ in derived.values()),
                              "rejected": len(rejected)}))
            for doc_id, job in sorted(jobs.items()):
                if job["status"] == "failed":
                    print(f"failed {doc_id}: {job['error']}")
            for doc_id, (state, reason) in sorted(derived.items()):
                if state == "interrupted":
                    print(f"interrupted {doc_id}: {reason}")
            for row in rejected:
                print(f"rejected {row['path']}: {row['reason']}")
            return 0
        if args.command == "export":
            if not args.name:
                raise ValueError("export requires --name")
            from .export import export
            print(json.dumps(export(corpus, args.name, args.models, allow_review=not args.hold_review)))
            return 0
        if args.command == "k1":
            if not args.name:
                raise ValueError("k1 requires --name")
            from .k1_config import load_k1_config
            from .k1_export import export_k1
            config = load_k1_config(args.k1_config)
            if args.recover_source_grids is not None:
                config["recover_source_grids"] = args.recover_source_grids
            if args.recover_sparse_scan_rows is not None:
                config["recover_sparse_scan_rows"] = args.recover_sparse_scan_rows
            rules = config.get("table_rules", {})
            if args.no_mud_properties:
                rules.pop("mud_properties", None)
            if args.no_ruled_panels:
                rules.pop("ruled_panels", None)
            print(json.dumps(export_k1(corpus, args.name, args.models, config, only=args.only,
                                       legacy_chunks=args.legacy_chunks)))
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
    if args.corpus is None or args.command in ("init", "models", "status", "qa"):
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
