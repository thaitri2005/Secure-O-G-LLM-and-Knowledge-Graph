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


def show_validation(root: Path, registry: list[dict[str, Any]], options: dict[str, Any]) -> int:
    path = root / "data" / "processed" / "gdr_chunks.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    errors, warnings, summary = validate_records(records, [doc["doc_id"] for doc in registry], load_sources(registry, root), options)
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
    parser.add_argument("command", choices=("fetch", "convert", "chunk", "validate", "run"))
    parser.add_argument("--sources", type=Path, default=Path("configs/sources/gdr_end_of_well.json"))
    parser.add_argument("--config", type=Path, default=Path("configs/ingestion/default.json"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        registry = load_registry(args.sources)
        options = load_options(args.config)
        root = project_root(args.config)
        if args.command in {"fetch", "run"}:
            for source in fetch_sources(registry, root):
                print(f"{source['doc_id']}: {'verified cached' if source['cached'] else 'downloaded and verified'}; bytes={source['bytes']}; sha256={source['sha256']}", flush=True)
        if args.command in {"convert", "run"}:
            from .convert import convert_sources
            convert_sources(registry, root, options)
        if args.command in {"chunk", "run"}:
            chunks, statistics = chunk_documents(registry, root, options)
            log = root / "data" / "interim" / "run_log.json"
            history = json.loads(log.read_text(encoding="utf-8")) if log.exists() else {}
            history["chunking"] = statistics
            write_json(log, history)
            for stats in statistics:
                print(json.dumps(stats, ensure_ascii=False), flush=True)
            print(f"MERGED: {len(chunks)} chunks; SHA256={sha256(root / 'data' / 'processed' / 'gdr_chunks.json')}", flush=True)
        if args.command in {"validate", "run"}:
            return show_validation(root, registry, options)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"FAIL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
