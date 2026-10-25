"""Isolate experiment artifacts and explicitly publish reviewed outputs."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
from typing import Any

from .sources import write_checksums, write_json, write_text


def conversion_cache(root: Path, options: dict[str, Any]) -> Path:
    keys = ("do_ocr", "do_table_structure", "table_mode", "do_cell_matching", "device")
    settings = {key: options[key] for key in keys}
    if options["do_ocr"]:
        from .ocr_settings import ocr_settings
        settings["ocr"] = ocr_settings(options)
    base_settings = dict(zip(keys, (False, True, "accurate", True, "cpu")))
    base = root / "data" / "interim" / "docling"
    if settings == base_settings:
        return base
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]
    return base / digest


def run_directory(root: Path, name: str) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
        raise ValueError("Run names must start with a lowercase letter and contain letters, digits, _ or -")
    return root / "data" / "interim" / "runs" / name


def bundle_directory(root: Path, registry_name: str) -> Path:
    """Keep the main deliverable stable and secondary publications local."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", registry_name):
        raise ValueError("Invalid registry name")
    directory = root / "data" / "processed"
    return directory if registry_name == "gdr_end_of_well" else directory / "local" / registry_name


def prepare_run(root: Path, name: str, options: dict[str, Any], registry: list[dict[str, Any]]) -> Path:
    directory = run_directory(root, name)
    directory.mkdir(parents=True, exist_ok=True)
    for filename, value in (("config.json", options), ("sources.json", registry)):
        path = directory / filename
        if path.exists() and json.loads(path.read_text(encoding="utf-8")) != value:
            raise ValueError("Existing run uses different inputs; choose a new run name")
        write_json(path, value)
    return directory


def compare_runs(root: Path, old: str, new: str) -> dict[str, int]:
    records = [json.loads((run_directory(root, name) / "gdr_chunks.json").read_text(encoding="utf-8"))
               for name in (old, new)]
    from .provenance import content_id
    from .evaluation import tokens
    unmatched = set(range(len(records[1])))
    pending, kept = [], 0
    for left in records[0]:
        match = next((index for index in sorted(unmatched) if content_id(left) == content_id(records[1][index])), None)
        if match is None:
            pending.append(left)
        else:
            unmatched.remove(match)
            kept += 1
    changed = 0
    for left in pending:
        a = tokens(left["text"])
        candidates = []
        for index in sorted(unmatched):
            right = records[1][index]
            if (left["doc_id"], left["type"]) != (right["doc_id"], right["type"]):
                continue
            b = tokens(right["text"])
            score = len(a & b) / len(a | b) if a | b else 0
            if score >= .9:
                candidates.append((score, -index))
        if candidates:
            unmatched.remove(-max(candidates)[1])
            changed += 1
    return {"kept": kept, "changed": changed, "added": len(unmatched), "removed": len(pending) - changed}


def publish_run(root: Path, name: str, sources: Path) -> None:
    from .sources import load_registry
    configured = load_registry(sources)
    if any(source.get("portfolio") for source in configured):
        from .portfolio import expand_portfolios
        configured = expand_portfolios(configured, root)
    directory = run_directory(root, name)
    required = ("gdr_chunks.json", "gdr_chunks_full.jsonl", "documents", "metrics.json", "gdr_tables.jsonl")
    if any(not (directory / filename).exists() for filename in required):
        raise ValueError("Publication requires complete chunks, provenance, documents and evaluated metrics")
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    if metrics.get("validated") is not True:
        raise ValueError("Publication requires successful validation")
    from .sources import sha256
    if metrics.get("sha256") != sha256(directory / "gdr_chunks.json"):
        raise ValueError("Publication metrics do not match chunk bytes")
    from .schema_validation import validate_artifacts
    if errors := validate_artifacts(directory / "gdr_chunks.json"):
        raise ValueError("Publication validation failed: " + "; ".join(errors[:5]))
    options = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    registry = json.loads((directory / "sources.json").read_text(encoding="utf-8"))
    if registry != configured:
        raise ValueError("Publication run does not match the target --sources registry")
    from .validate import load_sources, validate_records
    chunks = json.loads((directory / "gdr_chunks.json").read_text(encoding="utf-8"))
    full = [json.loads(line) for line in (directory / "gdr_chunks_full.jsonl").read_text(encoding="utf-8").splitlines()]
    errors, _, _ = validate_records(chunks, [s["doc_id"] for s in registry],
                                    load_sources(registry, root, conversion_cache(root, options)), options, full)
    if errors:
        raise ValueError("Publication validation failed: " + "; ".join(errors[:5]))
    ids = {s["doc_id"] for s in registry}
    destination = bundle_directory(root, sources.stem)
    destination.mkdir(parents=True, exist_ok=True)
    from .provenance import rounded_geometry
    for filename in (*required[:3], "gdr_tables.jsonl"):
        source = directory / filename
        if source.is_dir():
            for document in source.rglob("*"):
                if document.is_file():
                    target = destination / filename / document.relative_to(source)
                    if document.suffix == ".json":
                        write_json(target, rounded_geometry(json.loads(document.read_text(encoding="utf-8"))))
                    else:
                        write_text(target, document.read_text(encoding="utf-8"))
        else:
            target = destination / filename
            text = source.read_text(encoding="utf-8")
            if source.suffix == ".jsonl":
                text = "".join(json.dumps(rounded_geometry(json.loads(line)), ensure_ascii=False) + "\n"
                               for line in text.splitlines())
            write_text(target, text)
    write_checksums(destination, sorted(ids))
