"""Quality ledger: a deterministic, read-only sidecar describing a K1 release.

Inputs: a K1 release directory (required), the corpus work folder (optional, degraded without it) and an A-107
table repair sidecar (optional). Outputs: qa-ledger.json and qa-summary.json. No timestamps, no absolute paths."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

from .builtin_checks import register_builtin
from .signals import (ALL_LEVELS, COMPLETENESS_VALUES, KNOWN_BLIND_SPOTS, LEVELS, LIMITATIONS, NOT_APPLICABLE, SCHEMA_VERSION,
                      CheckContext, Registry, final_level, initial_level)

DEFAULT_CONFIG = Path("configs/qa/ledger.json")
LEDGER_NAME = "qa-ledger.json"
SUMMARY_NAME = "qa-summary.json"


def default_registry() -> Registry:
    return register_builtin(Registry())


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or DEFAULT_CONFIG).read_text(encoding="utf-8"))


def find_sidecar(config: dict, release_dir: Path, corpus_dir: Path | None, explicit: Path | None) -> tuple[Path | None, list[str]]:
    """Locate an A-107 table repair sidecar. Returns (path or None, list of searched templates)."""
    if explicit is not None:
        return (explicit if explicit.is_file() else None), [str(explicit.name)]
    export_dir = release_dir.parent.parent
    values = {"export_dir": str(export_dir), "export": export_dir.name, "release": str(release_dir),
              "corpus": str(corpus_dir) if corpus_dir else ""}
    searched = []
    for template in config.get("a107_sidecar_search", []):
        if "{corpus}" in template and not corpus_dir:
            continue
        searched.append(template)
        candidate = Path(template.format(**values))
        if candidate.is_file():
            return candidate, searched
    return None, searched


def load_sidecar(path: Path) -> tuple[dict[str, dict], int]:
    """table_id -> compact record; the second value counts duplicated table_ids (first record is kept)."""
    records, duplicates = {}, 0
    for row in json.loads(path.read_text(encoding="utf-8")):
        table_id = row.get("table_id")
        if table_id in records:
            duplicates += 1
            continue
        evidence = row.get("evidence") or {}
        records[table_id] = {"state": row.get("state"), "reason": row.get("reason"), "completeness": row.get("completeness"),
                             "action": row.get("action"), "rule": row.get("rule"), "stage": row.get("stage"),
                             "status": row.get("status"), "decision": evidence.get("decision"),
                             "margins": evidence.get("margins")}
    return records, duplicates


def load_work_document(corpus_dir: Path | None, doc_id: str, fingerprint: str | None) -> tuple[dict | None, str, str | None]:
    """Return (document.json content or None, reason when None, fingerprint of the work data)."""
    if corpus_dir is None or not (corpus_dir / "work").is_dir():
        return None, "corpus work folder not available", None
    folder = corpus_dir / "work" / doc_id
    if not folder.is_dir():
        return None, "no work folder for this document", None
    candidates = [folder / fingerprint] if fingerprint else []
    candidates += sorted(path for path in folder.iterdir() if path.is_dir() and path not in candidates)
    for candidate in candidates:
        if (candidate / "document.json").is_file():
            return json.loads((candidate / "document.json").read_text(encoding="utf-8")), "", candidate.name
    return None, "document.json not found in the work folder", None


def table_origin(table: dict) -> tuple[str, list[str]]:
    refs = sorted({part.get("source_ref") for part in table.get("parts") or [] if part.get("source_ref")})
    kinds = {"textlayer_rebuild" if ref.startswith("textlayer:") else "docling" for ref in refs}
    if not kinds:
        return "unknown", refs
    return (kinds.pop() if len(kinds) == 1 else "mixed"), refs


def ratio(extracted: Any, pdf: Any) -> float | None:
    if isinstance(extracted, (int, float)) and isinstance(pdf, (int, float)) and pdf > 0:
        return round(extracted / pdf, 4)
    return None


def sorted_signals(signals: list[dict]) -> list[dict]:
    return sorted(signals, key=lambda s: (s["code"], dumps(s["scope"]), dumps(s["evidence"])))


def read_release(release_dir: Path) -> dict:
    """Load the small release groups; chunks are streamed into counters (their text is never kept)."""
    pages: dict[str, list[dict]] = {}
    for row in iter_jsonl(release_dir / "pages.jsonl"):
        pages.setdefault(row["file_id"], []).append(row)
    tables: dict[str, list[dict]] = {}
    for row in iter_jsonl(release_dir / "tables.jsonl"):
        tables.setdefault(row["file_id"], []).append(row)
    parent_type = {row["parent_id"]: row.get("type") for row in iter_jsonl(release_dir / "parents.jsonl")}
    chunk_stats: dict[str, dict] = {}
    page_chunks: Counter = Counter()
    for chunk in iter_jsonl(release_dir / "chunks.jsonl"):
        stats = chunk_stats.setdefault(chunk["file_id"], {"count": 0, "by_quality": Counter(), "groups": {}})
        stats["count"] += 1
        stats["by_quality"][str(chunk.get("quality"))] += 1
        group = stats["groups"].setdefault(str(parent_type.get(chunk.get("parent_id"))), {"count": 0, "by_quality": Counter()})
        group["count"] += 1
        group["by_quality"][str(chunk.get("quality"))] += 1
        page_chunks[(chunk["file_id"], chunk.get("page"))] += 1
    return {"files": list(iter_jsonl(release_dir / "files.jsonl")), "pages": pages, "tables": tables,
            "chunk_stats": chunk_stats, "page_chunks": page_chunks}


def counter_dict(counter: Counter) -> dict:
    return {key: counter[key] for key in sorted(counter)}


def run_validator(release_dir: Path, limit: int) -> dict:
    try:
        from ..k1_validate import inspect
        result = inspect(release_dir)
    except Exception as error:  # noqa: BLE001 - reported as a signal, QA continues
        return {"status": "unavailable", "error_count": 1, "errors": [f"{type(error).__name__}: {str(error)[:200]}"],
                "page_rebuild_matches": None, "page_rebuild_total": None}
    errors = list(result["errors"])
    return {"status": result["status"], "error_count": len(errors), "errors": errors[:limit],
            "page_rebuild_matches": result["page_rebuild_matches"], "page_rebuild_total": result["page_rebuild_total"]}


def min_level(levels: list[str]) -> str | None:
    ranked = [level for level in levels if level in LEVELS]
    return min(ranked, key=LEVELS.index) if ranked else None


def base_level(context: CheckContext, signals: list[dict]) -> str:
    if context.validator and context.validator.get("status") != "pass":
        return "UNVERIFIED"  # the release did not even pass the structural validator
    return initial_level(signals)


def build_page(context: CheckContext, file_row: dict, page_row: dict, work_page: dict | None, document_has_work: bool,
               chunk_count: int) -> dict:
    registry = context.registry
    work_page = work_page or {}
    ids = {"file_id": file_row["file_id"], "page": page_row["page"], "page_id": page_row.get("page_id")}
    pdf, extracted = work_page.get("text_chars"), work_page.get("extracted_characters")
    entity = {"ids": ids, "page": page_row["page"], "release_mode": page_row.get("conversion_mode", page_row.get("mode")),
              "status": page_row.get("status"), "ocr": page_row.get("ocr"), "parser": page_row.get("parser"),
              "pdf_text_chars": pdf, "extracted_characters": extracted, "char_ratio": ratio(extracted, pdf),
              "confidence": work_page.get("confidence"), "analysis_reasons": work_page.get("reasons"),
              "chunk_count": chunk_count, "work_present": bool(work_page), "document_has_work": document_has_work}
    signals, ran, granted = registry.run("page", context, entity, ids)
    entity["signals"] = sorted_signals(signals)
    entity["checks"] = ran
    entity["verification_level"] = final_level(base_level(context, signals), granted, signals)
    del entity["ids"], entity["work_present"], entity["document_has_work"]
    entity["page_id"] = ids["page_id"]
    return entity


def build_table(context: CheckContext, file_row: dict, table: dict) -> dict:
    origin, refs = table_origin(table)
    a107 = (context.sidecar or {}).get(table["table_id"])
    completeness = "PARTIAL_IN_SOURCE" if a107 and str(a107.get("completeness") or "").upper() == "PARTIAL_IN_SOURCE" else "UNKNOWN"
    ids = {"file_id": file_row["file_id"], "table_id": table["table_id"]}
    entity = {"ids": ids, "table_id": table["table_id"], "logical_id": table.get("logical_id"), "pages": table.get("pages"),
              "num_rows": table.get("num_rows"), "num_cols": table.get("num_cols"), "header_rows": table.get("header_rows"),
              "origin": origin, "source_refs": refs, "a107": a107, "completeness": completeness}
    signals, ran, granted = context.registry.run("table", context, entity, ids)
    entity["signals"] = sorted_signals(signals)
    entity["checks"] = ran
    entity["verification_level"] = final_level(base_level(context, signals), granted, signals)
    del entity["ids"]
    return entity


def build_document(registry: Registry, config: dict, release_dir: Path, manifest: dict, release: dict, file_row: dict,
                   corpus_dir: Path | None, validator: dict, sidecar: dict | None) -> dict:
    """One ledger record; any exception becomes a QA_ERROR signal and the record stays UNVERIFIED."""
    file_id = file_row["file_id"]
    ids = {"file_id": file_id}
    context = CheckContext(registry, config, release_dir, manifest, validator=validator, sidecar=sidecar)
    record: dict[str, Any] = {"file_id": file_id, "doc_id": file_row.get("doc_id"), "document_type": file_row.get("document_type"),
                              "page_count": file_row.get("page_count"), "sha256": file_row.get("sha256"),
                              "completeness": "UNKNOWN"}
    try:
        work_doc, reason, work_fp = load_work_document(corpus_dir, file_row.get("doc_id", ""), manifest.get("corpus_fingerprint"))
        work_pages = {page["page"]: page for page in (work_doc or {}).get("pages", [])}
        segments = [{"mode": s.get("mode"), "pages": s.get("pages"), "status": s.get("status"), "errors": list(s.get("errors") or [])}
                    for s in ((work_doc or {}).get("processing") or {}).get("segments", [])]
        stats = (work_doc or {}).get("statistics") or {}
        record["work"] = {"present": work_doc is not None, "reason": reason, "fingerprint": work_fp,
                          "fingerprint_matches_release": (work_fp == manifest.get("corpus_fingerprint")) if work_doc else None,
                          "segments": segments, "dropped": stats.get("dropped") or {},
                          "review_pages": (work_doc or {}).get("review_pages"), "missing_pages": (work_doc or {}).get("missing_pages")}
        chunks = release["chunk_stats"].get(file_id, {"count": 0, "by_quality": Counter(), "groups": {}})
        record["chunks"] = {"count": chunks["count"], "by_quality": counter_dict(chunks["by_quality"]),
                            "groups": {name: {"count": group["count"], "by_quality": counter_dict(group["by_quality"])}
                                       for name, group in sorted(chunks["groups"].items())}}
        pages = sorted(release["pages"].get(file_id, []), key=lambda row: row["page"])
        record["pages"] = [build_page(context, file_row, row, work_pages.get(row["page"]), work_doc is not None,
                                      release["page_chunks"].get((file_id, row["page"]), 0)) for row in pages]
        record["tables"] = [build_table(context, file_row, table) for table in release["tables"].get(file_id, [])]
        entity = {"ids": ids, "work": record["work"], "chunks": record["chunks"]}
        signals, ran, granted = registry.run("document", context, entity, ids)
    except Exception as error:  # noqa: BLE001 - failure isolation per document
        record.setdefault("pages", [])
        record.setdefault("tables", [])
        signals, ran, granted = [registry.signal("QA_ERROR", "document", ids, evidence={"error": type(error).__name__,
                                                                                       "detail": str(error)[:300]})], [], None
    record["signals"] = sorted_signals(signals)
    record["checks"] = ran
    children = [item["verification_level"] for item in record["pages"] + record["tables"]]
    own = final_level(initial_level(signals), granted, signals)
    if validator["status"] != "pass":
        own = "UNVERIFIED"
    lowest = min_level(children + ([own] if own in LEVELS else []))
    record["verification_level"] = lowest if lowest else own
    if own == NOT_APPLICABLE and not children:
        record["verification_level"] = NOT_APPLICABLE
    record["tables_partial_in_source"] = sum(table["completeness"] == "PARTIAL_IN_SOURCE" for table in record["tables"])
    return record


class SummaryBuilder:
    """Accumulates counters while records stream by, so the full ledger never has to sit in memory."""

    def __init__(self) -> None:
        self.by_family: dict[str, dict] = {}
        self.codes: dict[str, dict] = {}
        self.levels = {"document": Counter(), "page": Counter(), "table": Counter()}
        self.states = {"a107_state": Counter(), "page_status": Counter(), "conversion_mode": Counter(), "table_origin": Counter(),
                       "table_completeness": Counter(), "segment_status": Counter()}
        self.totals: Counter = Counter()

    def family(self, name: str) -> dict:
        return self.by_family.setdefault(name, {"documents": 0, "pages": 0, "tables": 0, "chunks": 0, "signals": Counter(),
                                                 "severity": Counter(), "levels": Counter()})

    def count_signals(self, family: str, signals: list[dict], severities: dict[str, str]) -> None:
        entry = self.family(family)
        for signal in signals:
            entry["signals"][signal["code"]] += 1
            entry["severity"][signal["severity"]] += 1
            code = self.codes.setdefault(signal["code"], {"severity": signal["severity"], "count": 0, "by_family": Counter()})
            code["count"] += 1
            code["by_family"][family] += 1

    def add_release_signals(self, signals: list[dict]) -> None:
        self.count_signals("(release)", signals, {})

    def add(self, record: dict) -> None:
        family = str(record.get("document_type"))
        entry = self.family(family)
        entry["documents"] += 1
        entry["pages"] += len(record["pages"])
        entry["tables"] += len(record["tables"])
        entry["chunks"] += record.get("chunks", {}).get("count", 0)
        self.totals.update({"documents": 1, "pages": len(record["pages"]), "tables": len(record["tables"]),
                            "chunks": record.get("chunks", {}).get("count", 0)})
        self.levels["document"][record["verification_level"]] += 1
        entry["levels"][record["verification_level"]] += 1
        self.count_signals(family, record["signals"], {})
        for segment in record.get("work", {}).get("segments", []):
            self.states["segment_status"][str(segment["status"])] += 1
        for page in record["pages"]:
            self.levels["page"][page["verification_level"]] += 1
            self.states["page_status"][str(page["status"])] += 1
            self.states["conversion_mode"][str(page["release_mode"])] += 1
            self.count_signals(family, page["signals"], {})
        for table in record["tables"]:
            self.levels["table"][table["verification_level"]] += 1
            self.states["table_origin"][table["origin"]] += 1
            self.states["table_completeness"][table["completeness"]] += 1
            if table["a107"]:
                self.states["a107_state"][f"{table['a107']['state']}/{table['a107']['reason'] or '-'}"] += 1
            self.count_signals(family, table["signals"], {})

    def result(self) -> dict:
        return {
            "by_family": {name: {"documents": e["documents"], "pages": e["pages"], "tables": e["tables"], "chunks": e["chunks"],
                                 "signals_by_code": counter_dict(e["signals"]), "signals_by_severity": counter_dict(e["severity"]),
                                 "verification_levels": counter_dict(e["levels"])} for name, e in sorted(self.by_family.items())},
            "by_reason_code": {code: {"severity": e["severity"], "count": e["count"], "by_family": counter_dict(e["by_family"])}
                               for code, e in sorted(self.codes.items())},
            "by_state": {name: counter_dict(counter) for name, counter in self.states.items()},
            "verification_levels": {scope: counter_dict(counter) for scope, counter in self.levels.items()},
            "totals": counter_dict(self.totals)}


def reason_registry(registry: Registry) -> list[dict]:
    return [{"code": r.code, "severity": r.severity, "meaning": r.meaning, "emitted_by": r.emitted_by}
            for r in sorted(registry.reasons.values(), key=lambda r: r.code)]


def write_ledger(path: Path, header: dict, records: Iterator[dict]) -> None:
    """Write {header..., "documents": [...]} one document per line, byte-stable (LF, UTF-8)."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(dumps(header)[:-1] + ',"documents":[')
        for index, record in enumerate(records):
            handle.write(("," if index else "") + "\n" + dumps(record))
        handle.write("\n]}\n")


def build_qa(release_dir: Path, out_dir: Path, corpus_dir: Path | None = None, config_path: Path | None = None,
             sidecar_path: Path | None = None, registry: Registry | None = None) -> dict:
    """Build qa-ledger.json and qa-summary.json for ``release_dir``; the release and the corpus are only read."""
    registry = registry or default_registry()
    config_file = config_path or DEFAULT_CONFIG
    config = load_config(config_file)
    manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    validator = run_validator(release_dir, config["thresholds"]["max_listed_validator_errors"]["value"])
    found, searched = find_sidecar(config, release_dir, corpus_dir, sidecar_path)
    sidecar, duplicates = load_sidecar(found) if found else (None, 0)
    release = read_release(release_dir)
    known_tables = {table["table_id"] for rows in release["tables"].values() for table in rows}
    unmatched = sorted(set(sidecar) - known_tables) if sidecar is not None else []
    context = CheckContext(registry, config, release_dir, manifest, validator=validator, sidecar=sidecar)
    release_entity = {"ids": {"release": release_dir.name}, "validator": validator,
                      "sidecar": {"found": found is not None, "searched": searched, "unmatched": unmatched}}
    release_signals, release_checks, _ = registry.run("release", context, release_entity, release_entity["ids"])
    release_signals = sorted_signals(release_signals)
    sums = release_dir / "SHA256SUMS"
    link = {"release_dir_name": release_dir.name, "sha256sums_sha256": sha256_file(sums) if sums.is_file() else None,
            "manifest_identity": manifest.get("identity"), "corpus_fingerprint": manifest.get("corpus_fingerprint"),
            "manifest_schema_version": manifest.get("schema_version"), "qa_schema_version": SCHEMA_VERSION,
            "config_sha256": sha256_file(config_file), "a107_sidecar": {"found": found is not None, "name": found.name if found else None,
                                                                     "sha256": sha256_file(found) if found else None,
                                                                     "duplicate_table_ids": duplicates},
            "corpus_work_folder": "used" if corpus_dir is not None and (corpus_dir / "work").is_dir() else "not available (release-only, degraded)"}
    checks = [{"name": c.name, "version": c.version, "scope": c.scope, "grants": c.grants, "limitations": list(c.limitations)}
              for c in sorted(registry.checks, key=lambda c: c.name)]
    header = {"schema_version": SCHEMA_VERSION, "link": link, "completeness": "UNKNOWN", "completeness_values_allowed": list(COMPLETENESS_VALUES),
              "verification_levels_allowed": list(ALL_LEVELS), "limitations": list(LIMITATIONS),
              "known_blind_spots": list(KNOWN_BLIND_SPOTS), "checks": checks, "k1_validator": validator,
              "release_signals": release_signals,
              "verification_level": "UNVERIFIED" if validator["status"] != "pass" else "STRUCTURAL_ONLY"}
    summary = SummaryBuilder()
    summary.add_release_signals(release_signals)

    def records() -> Iterator[dict]:
        for file_row in sorted(release["files"], key=lambda row: row["file_id"]):
            record = build_document(registry, config, release_dir, manifest, release, file_row, corpus_dir, validator, sidecar)
            summary.add(record)
            yield record

    out_dir.mkdir(parents=True, exist_ok=True)
    write_ledger(out_dir / LEDGER_NAME, header, records())
    result = summary.result()
    document = {"schema_version": SCHEMA_VERSION, "link": link, "completeness": "UNKNOWN", "verification_level": header["verification_level"],
                "limitations": header["limitations"], "known_blind_spots": header["known_blind_spots"],
                "k1_validator": {key: validator[key] for key in ("status", "error_count", "page_rebuild_matches", "page_rebuild_total")},
                "reason_codes": reason_registry(registry), **result}
    (out_dir / SUMMARY_NAME).write_text(json.dumps(document, sort_keys=True, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return {"ledger": str(out_dir / LEDGER_NAME), "summary": str(out_dir / SUMMARY_NAME), "totals": result["totals"],
            "validator": validator["status"], "signals": {code: e["count"] for code, e in result["by_reason_code"].items()}}
