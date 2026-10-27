"""Command line for mapping-driven structured-data import.

    python -m graph_builder.datasets infer data.csv > configs/datasets/my_data.mapping.json   # draft a mapping
    python -m graph_builder.datasets run --mapping configs/datasets/bsee_wells.mapping.json   # fetch, import, validate
    python -m graph_builder.datasets fetch --mapping ...      # download and verify sources only
    python -m graph_builder.datasets validate --output data/processed/local/datasets/bsee_wells
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m graph_builder.datasets", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("infer", "fetch", "run", "validate"))
    parser.add_argument("file", nargs="?", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--sheet")
    args = parser.parse_args(argv)
    from .importer import fetch, run_import, validate_bundle
    from .mapping import load_mapping
    try:
        if args.command == "infer":
            if not args.file:
                raise ValueError("infer needs a CSV or XLSX file")
            from .infer import infer_mapping
            print(json.dumps(infer_mapping(args.file, sheet=args.sheet), ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate":
            if not args.output:
                raise ValueError("validate needs --output")
            problems = validate_bundle(args.output)
        else:
            if not args.mapping:
                raise ValueError(f"{args.command} needs --mapping")
            mapping = load_mapping(args.mapping)
            if args.command == "fetch":
                for source_id, entry in fetch(mapping, args.root, args.refresh).items():
                    print(f"{source_id}: {entry['bytes']} bytes, sha256={entry['sha256']}")
                return 0
            output = args.output or args.root / "data/processed/local/datasets" / mapping["dataset_id"]
            summary = run_import(mapping, args.root, output, args.refresh)
            print(json.dumps({key: summary[key] for key in ("records", "nodes", "edges", "skipped_links")}, indent=1))
            for kind, finding in summary["warnings"].items():
                print(f"WARNING {kind}: {finding['count']} (e.g. {finding['examples'][0]})")
            for kind, finding in summary["errors"].items():
                print(f"ERROR {kind}: {finding['count']} (e.g. {finding['examples'][0]})")
            problems = validate_bundle(output)
            args.output = output
        for problem in problems[:20]:
            print(f"ERROR {problem}")
        print(f"{'FAIL' if problems else 'PASS'}: {args.output}; {len(problems)} problems")
        return 1 if problems else 0
    except (OSError, ValueError, KeyError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
