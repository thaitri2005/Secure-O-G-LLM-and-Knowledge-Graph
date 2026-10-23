"""Expose fetching, conversion, cached chunking, validation, and the complete ingestion pipeline as CLI commands."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from .chunking import chunk_documents
from .sources import fetch_sources, load_options, load_registry, project_root, sha256, write_json
from .validate import load_sources, validate_records
from .runs import bundle_directory, compare_runs, conversion_cache, prepare_run, publish_run


def show_validation(root: Path, registry: list[dict[str, Any]], options: dict[str, Any], path: Path | None = None) -> int:
    path = path or root / "data" / "processed" / "gdr_chunks.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    sidecar = path.with_name(path.stem + "_full.jsonl")
    provenance = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()] if sidecar.exists() else None
    errors, warnings, summary = validate_records(records, [doc["doc_id"] for doc in registry], load_sources(registry, root, conversion_cache(root, options)), options, provenance)
    if provenance is not None:
        from .schema_validation import validate_artifacts
        errors.extend(validate_artifacts(path))
    for item in summary:
        print(f"{item['doc_id']}: pages={item['pages']} text={item['text']} table={item['table']} total={item['total']} exempt_pages={item['exempt_pages']} missing_pages={item['missing_pages']}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"{'FAIL' if errors else 'PASS'}: {len(records) if isinstance(records, list) else 0} chunks; {len(errors)} errors; {len(warnings)} warnings")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "convert", "chunk", "validate", "run", "evaluate", "compare", "publish", "ocr"))
    parser.add_argument("--sources", type=Path, default=Path("configs/sources/gdr_end_of_well.json"))
    parser.add_argument("--config", type=Path, default=Path("configs/ingestion/default.json"))
    parser.add_argument("--run-name")
    parser.add_argument("--run")
    parser.add_argument("--old")
    parser.add_argument("--new")
    parser.add_argument("--set", action="append", default=[])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.set and args.command in {"compare", "evaluate", "publish", "ocr"}:
            raise ValueError(f"{args.command} does not accept --set")
        registry = load_registry(args.sources)
        options = load_options(args.config, args.set)
        root = project_root(args.config)
        if args.command == "compare":
            if not args.old or not args.new:
                raise ValueError("compare requires --old and --new")
            print(json.dumps(compare_runs(root, args.old, args.new)))
            return 0
        if args.command in {"publish", "evaluate", "ocr"}:
            if not args.run:
                raise ValueError(f"{args.command} requires --run")
            if args.command == "publish":
                publish_run(root, args.run, args.sources)
            elif args.command == "ocr":
                from .ocr import evaluate_ocr
                print(json.dumps(evaluate_ocr(root, args.run)))
            else:
                from .evaluation import evaluate_run
                print(json.dumps(evaluate_run(root, args.run), ensure_ascii=False))
            return 0
        if args.set and not args.run_name:
            raise ValueError("Overrides require --run-name")
        if args.command in {"fetch", "run"}:
            for source in fetch_sources(registry, root):
                print(f"{source['doc_id']}: {'verified cached' if source['cached'] else 'downloaded and verified'}; bytes={source['bytes']}; sha256={source['sha256']}", flush=True)
        if any(source.get("portfolio") for source in registry):
            from .portfolio import expand_portfolios
            registry = expand_portfolios(registry, root)
        directory = prepare_run(root, args.run_name, options, registry) if args.run_name else None
        output = directory / "gdr_chunks.json" if directory else None
        if not directory and args.sources.stem != "gdr_end_of_well":
            output = bundle_directory(root, args.sources.stem) / "gdr_chunks.json"
        cache = conversion_cache(root, options)
        if args.command in {"convert", "run"}:
            from .convert import convert_sources
            timings = convert_sources(registry, root, options, cache=cache, reuse_cache=bool(directory))
            if directory and timings:
                write_json(directory / "timings.json", timings)
        if args.command in {"chunk", "run"}:
            chunks, statistics = chunk_documents(registry, root, options, output=output, cache=cache)
            log = root / "data" / "interim" / "run_log.json"
            history = json.loads(log.read_text(encoding="utf-8")) if log.exists() else {}
            history["chunking"] = statistics
            write_json(log, history)
            for stats in statistics:
                print(json.dumps(stats, ensure_ascii=False), flush=True)
            print(f"MERGED: {len(chunks)} chunks; SHA256={sha256(output or root / 'data' / 'processed' / 'gdr_chunks.json')}", flush=True)
        if args.command in {"validate", "run"}:
            return show_validation(root, registry, options, output)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
