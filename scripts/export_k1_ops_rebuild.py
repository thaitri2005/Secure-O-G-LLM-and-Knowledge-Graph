"""Export the K1 package of the local corpus under a NEW export name and write the table-repair sidecar.
Usage (repository root; needs the interpreter with onnxruntime, e.g. explorations/ingestion/.venvs/docling/Scripts/python.exe):
    set PYTHONPATH=src
    python scripts/export_k1_ops_rebuild.py NAME [--sidecar-dir DIR] [--warn-parsing-failure-rate 0.01]
The sidecar ``DIR/table_repairs.NAME.json`` (default DIR ``data/interim/ops-rebuild``, Round 1; for Round 2 pass
``--sidecar-dir data/interim/ops-rebuild-r2``) lists every Operations Summary occurrence with its state, the status
(rebuilt/fallback), the machine-readable reason and what happened to the table. ``table_repairs.NAME.summary.json`` next
to it counts the records per document family, state and reason, with the share of ``PARSING_FAILURE`` records. A family
whose share is above ``--warn-parsing-failure-rate`` is reported as a warning (log and stdout); the export is never stopped
by it. Neither file is part of the K1 package.
Use a NEW export name: each run writes a new release directory (timestamp + content hash) under that name, and the
sidecar of an earlier run with the same name is overwritten.
"""
from __future__ import annotations
import argparse
import json
import logging
import os
from pathlib import Path
os.environ.setdefault("HF_HUB_OFFLINE", "1")
from graph_builder.corpus.catalog import Corpus  # noqa: E402
from graph_builder.corpus.k1_config import load_k1_config  # noqa: E402
from graph_builder.corpus.k1_export import export_k1  # noqa: E402
from graph_builder.corpus.ops_tables import family_summary  # noqa: E402

LOGGER = logging.getLogger("export_k1_ops_rebuild")

def warnings_for(summary: dict, threshold: float) -> list[str]:
    """One warning per family whose share of PARSING_FAILURE records is above ``threshold``."""
    return [f"family {name}: {family['by_state'].get('PARSING_FAILURE', 0)} of {family['records']} records are PARSING_FAILURE "
            f"(rate {family['parsing_failure_rate']:.3f} > {threshold})"
            for name, family in sorted(summary.items()) if family["parsing_failure_rate"] > threshold]

def rate(text: str) -> float:
    value = float(text)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("the rate must be between 0 and 1")
    return value

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name")
    parser.add_argument("--corpus", type=Path, default=Path("data/interim/k1-run/corpus"))
    parser.add_argument("--models", type=Path, default=Path("explorations/ingestion/models/corpus-ocr"))
    parser.add_argument("--config", type=Path, default=Path("configs/corpus/k1.json"))
    parser.add_argument("--sidecar-dir", type=Path, default=Path("data/interim/ops-rebuild"))
    parser.add_argument("--warn-parsing-failure-rate", type=rate, default=0.01,
                        help="warn (never stop) when a family has a larger share of PARSING_FAILURE records; "
                        "a value chosen in advance, not calibrated")
    args = parser.parse_args(argv)
    result = export_k1(Corpus(args.corpus), args.name, args.models, load_k1_config(args.config))
    repairs = result.pop("table_repairs")
    args.sidecar_dir.mkdir(parents=True, exist_ok=True)
    out = args.sidecar_dir / f"table_repairs.{args.name}.json"
    out.write_text(json.dumps(repairs, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    summary = family_summary(repairs)
    summary_out = args.sidecar_dir / f"table_repairs.{args.name}.summary.json"
    summary_out.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    for warning in warnings_for(summary, args.warn_parsing_failure_rate):
        LOGGER.warning(warning)
        print(f"WARNING: {warning}")
    print(json.dumps({"export": result["export"], "release": result["release"], "counts": {k: result[k] for k in (
        "files", "pages", "tables", "forms", "parents", "chunks", "held_back")}, "sidecar": out.as_posix(),
        "summary": summary_out.as_posix()}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())