"""``python -m graph_builder.corpus qa <corpus_dir> --release <release_dir> [--out <dir>]``."""
from __future__ import annotations

import json
from pathlib import Path

from .ledger import build_qa

DEFAULT_OUT_ROOT = Path("data/interim/qa")


def run(corpus_dir: Path | None, release: Path | None, out: Path | None, config: Path | None, sidecar: Path | None, fidelity: bool = False, crossrep: bool = False, ops_margin: bool = False, annotations: bool = False) -> dict:
    if release is None:
        raise ValueError("qa requires --release <release_dir>")
    if not (release / "manifest.json").is_file():
        raise ValueError(f"not a K1 release directory (manifest.json missing): {release}")
    if corpus_dir is not None and not corpus_dir.is_dir():
        corpus_dir = None  # degraded: ledger from the release only
    out_dir = out or DEFAULT_OUT_ROOT / release.resolve().name
    registry = None
    if crossrep:  # opt-in: compares the representations inside the release (A-403); reads only the release
        from .crossrep import register_crossrep
        from .ledger import default_registry
        registry = register_crossrep(default_registry())
    if fidelity:  # opt-in: reads the source PDFs, so the default ledger stays independent of them
        from .fidelity import register_fidelity
        from .ledger import default_registry
        registry = register_fidelity(registry or default_registry(), corpus_dir=corpus_dir)
    if ops_margin:  # opt-in: reads the source PDFs (A-401a); WARN signals only
        from .ledger import default_registry
        from .opsmargin import register_ops_margin
        registry = register_ops_margin(registry or default_registry(), corpus_dir=corpus_dir)
    if annotations:  # opt-in: reads the source PDFs (A-414); INFO signals and completeness PARTIAL_IN_SOURCE only
        from .annotations import register_annotations
        from .ledger import default_registry
        registry = register_annotations(registry or default_registry(), corpus_dir=corpus_dir)
    try:
        return build_qa(release, out_dir, corpus_dir=corpus_dir, config_path=config, sidecar_path=sidecar, registry=registry)
    finally:
        if registry is not None:
            from .fidelity import close_fidelity
            close_fidelity(registry)


def main_text(result: dict) -> str:
    return json.dumps(result, sort_keys=True)
