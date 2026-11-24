"""Export finished corpus documents as a K1 package, published as an immutable release.

``exports/<name>/CURRENT.json`` names the current release in ``exports/<name>/releases/``; see publication.py.
The package holds files, pages, tables, forms, parents and chunks as JSONL, one text file per source file,
``manifest.json`` and ``SHA256SUMS``. It contains no timestamps and no absolute paths, so the same inputs give
byte-identical files.
"""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from ..publication import publish
from .catalog import Corpus
from .k1_build import ReportBoundaryError, build_document, canonical, context_coverage
from .k1_config import template_path
from .k1_validate import GROUPS, LEGACY_MAP, MANIFEST, SUMS, context_types, validate_k1
from .legacy_ids import LEGACY_DOCUMENT, load_legacy_rows, map_legacy_chunks, summarize_legacy_map
from .process import is_complete, output_directory
from .store import file_sha256
from .validate import SCHEMAS

SCHEMA_VERSION = 1


class K1CompletenessError(ValueError):
    """A failed export attempt, never a published partial release.

    ValueError is handled by the existing CLI with a nonzero exit status.
    """

    def __init__(self, report: dict, report_path: Path):
        self.report = report
        self.report_path = report_path
        super().__init__(f"K1 release BLOCKED: {report['reason']}; failure report: {report_path}")


def blocked_document(corpus: Corpus, doc: dict, fingerprint: str, status: str, reason: str,
                     detail: Any = None, built: dict | None = None) -> dict:
    """Account for withheld sources; unknown counts remain null, never invented as zero."""
    source_references, source_error = None, None
    path = output_directory(corpus, doc["doc_id"], fingerprint) / "chunks.jsonl"
    if path.is_file():
        try:
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError("Invalid corpus chunk record")
            source_references = [{key: row.get(key) for key in ("chunk_id", "pages", "source_spans", "regions")} for row in rows]
        except (OSError, ValueError) as error:
            source_error = f"{type(error).__name__}: {error}"
    return {"doc_id": doc["doc_id"], "sha256": doc.get("sha256"), "source": doc.get("source"),
            "original_name": doc.get("original_name"), "status": status, "reason": reason, "detail": detail,
            "pages_held": doc.get("pages"), "corpus_chunks_held": len(source_references) if source_references is not None else None,
            "k1_chunks_held": len(built["chunks"]) if built is not None else None,
            "source_references": source_references, "source_reference_error": source_error}


def completeness_problem(doc: dict, built: dict) -> str | None:
    """Check required identity and coverage independently of K1 structural validation."""
    if str(built.get("status", "")).upper() in {"BLOCKED", "FAILED", "UNSUPPORTED"}:
        return "document_not_ready"
    files = built["files"]
    if len(files) != 1:
        return "missing_or_duplicate_file"
    file = files[0]
    if file["doc_id"] != doc["doc_id"] or file["sha256"] != doc["sha256"]:
        return "source_identity_mismatch"
    pages = built["pages"]
    expected = doc["pages"]
    if expected is None or file["page_count"] != expected or len(pages) != expected \
            or sorted(page["page"] for page in pages) != list(range(1, expected + 1)):
        return "missing_or_duplicate_pages"
    if any(page["status"] == "missing" for page in pages):
        return "missing_page_content"
    if not built["chunks"]:
        return "zero_chunks"
    if any(row["file_id"] != file["file_id"] for group in GROUPS for row in built[group]):
        return "foreign_file_records"
    if any(row["doc_id"] != doc["doc_id"] for group in ("chunks", "tables", "forms") for row in built[group]):
        return "foreign_document_records"
    return None


def require_complete(corpus: Corpus, name: str, fingerprint: str, documents: list[dict],
                     included: list[dict], held: list[dict], sets: dict) -> None:
    """Runtime barrier before staging/publication; successful package bytes stay unchanged."""
    required = {doc["doc_id"] for doc in documents}
    actual = [file["doc_id"] for file in sets["files"]]
    if not held and len(actual) == len(required) and set(actual) == required:
        return
    failure_root = corpus.exports / ".k1-failures"
    failure_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=name + "-", dir=failure_root))
    report = {"gate": "TC-07", "status": "BLOCKED", "export_name": name, "corpus_fingerprint": fingerprint,
              "reason": "required_documents_incomplete", "required_documents": [
                  {"doc_id": doc["doc_id"], "sha256": doc.get("sha256"), "pages": doc.get("pages")} for doc in documents],
              "ready_documents": included, "blocked_documents": held,
              "missing_document_ids": sorted(required - set(actual)),
              "unexpected_document_ids": sorted(set(actual) - required),
              "counts": {"required_documents": len(required), "ready_documents": len(included),
                         "blocked_documents": len(held), "published_documents": 0},
              "published": False, "current_updated": False}
    for field in ("pages_held", "corpus_chunks_held", "k1_chunks_held"):
        report["counts"][field + "_known"] = sum(row[field] for row in held if row[field] is not None)
        report["counts"][field + "_unknown_documents"] = sum(row[field] is None for row in held)
    report_path = directory / "failure.json"
    write_text(report_path, dumps(report, indent=2))
    raise K1CompletenessError(report, report_path)


def dumps(value: Any, indent: int | None = None) -> str:
    separators = None if indent else (",", ":")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=separators, indent=indent) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def text_digest(path: Path) -> str:
    """SHA256 of a text file with LF line endings, so checkouts with other line endings give the same value."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def package_identity(corpus_fingerprint: str, k1_config: dict) -> str:
    """Hash of everything besides the documents that decides the package content."""
    material = {"corpus_fingerprint": corpus_fingerprint, "k1_config": k1_config,
                "form_template": text_digest(template_path(k1_config)),
                "schemas": {path.name: text_digest(path) for path in sorted(SCHEMAS.glob("k1_*.schema.json"))},
                "versions": {name: version(name) for name in ("docling", "docling-core")}}
    return hashlib.sha256(dumps(material).encode("utf-8")).hexdigest()


def map_legacy_document(legacy_chunks: Path, chunks: list[dict]) -> list[dict]:
    """Old-to-new chunk id records for the legacy document; form chunks have no old counterpart."""
    new_rows = [row for row in chunks if row["doc_id"] == LEGACY_DOCUMENT and row["type"] != "form"]
    if not new_rows:
        raise ValueError(f"--legacy-chunks needs the document {LEGACY_DOCUMENT} in the export")
    old_rows = load_legacy_rows(legacy_chunks)
    if not old_rows:
        raise ValueError(f"{legacy_chunks} has no chunks of {LEGACY_DOCUMENT}")
    return map_legacy_chunks(old_rows, new_rows)


def export_k1(corpus: Corpus, name: str, models: Path, k1_config: dict, only: list[str] | None = None,
              legacy_chunks: Path | None = None) -> dict[str, Any]:
    """Export all required active documents (or the explicit ``only`` scope) in doc_id order.

    Any failed, blocked, unsupported or missing required document blocks publication.
    A structured failure report is kept outside releases; CURRENT is left untouched.
    """
    from .config import fingerprint as make_fingerprint
    from .ocr_engines import engine_fingerprint
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("Export names use lowercase letters, digits, _ and -")
    config = corpus.config
    documents = [doc for doc in corpus.documents() if not only or doc["doc_id"] in only]
    unknown = sorted(set(only or []) - {doc["doc_id"] for doc in documents})
    ocr = engine_fingerprint(models, config["ocr"])
    fingerprint = make_fingerprint(config, ocr["models"])
    jobs = corpus.jobs(fingerprint)
    sets: dict[str, list[dict]] = {group: [] for group in GROUPS}
    texts: dict[str, str] = {}
    included, held, conflicts, missing, coverage, repairs = [], [], [], [], {}, []
    unknown_documents = [{"doc_id": doc_id, "sha256": None, "pages": None} for doc_id in unknown]
    held.extend(blocked_document(corpus, doc, fingerprint, "NOT_FOUND", "unknown_required_document")
                for doc in unknown_documents)
    section_findings: dict[str, dict] = {}
    single_findings: dict[str, dict] = {}
    block_findings: dict[str, dict] = {}
    label_findings: dict[str, dict] = {}
    quarantine_findings: dict[str, dict] = {}
    join_findings: dict[str, dict] = {}
    boundary_findings: dict[str, dict] = {}
    for doc in documents:
        job = jobs.get(doc["doc_id"])
        if doc["format"] != "pdf":
            held.append(blocked_document(corpus, doc, fingerprint, "UNSUPPORTED", "unsupported_format", doc["format"]))
            continue
        if not job or job["status"] != "done" or not is_complete(output_directory(corpus, doc["doc_id"], fingerprint)):
            status = "FAILED" if job and job["status"] == "failed" else "NOT_PROCESSED"
            held.append(blocked_document(corpus, doc, fingerprint, status, "processing_not_complete",
                                         (job or {}).get("error") or "not processed"))
            continue
        try:
            built = build_document(corpus, doc, fingerprint, k1_config)
            problem = completeness_problem(doc, built)
        except ReportBoundaryError as error:
            held.append(blocked_document(corpus, doc, fingerprint, "BLOCKED", "report_boundaries", error.evidence))
            continue
        except Exception as error:
            held.append(blocked_document(corpus, doc, fingerprint, "FAILED", "k1_build_failed",
                                         f"{type(error).__name__}: {error}"))
            continue
        if problem:
            held.append(blocked_document(corpus, doc, fingerprint, "BLOCKED", problem, built.get("status"), built))
            continue
        for group in GROUPS:
            sets[group].extend(built[group])
        file = built["files"][0]
        texts[file["text"]] = built["text"]
        conflicts += built["form_conflicts"]
        missing += built["pages_without_context"]
        repairs += built["table_repairs"]
        if "label_value" in built:
            label_findings[doc["doc_id"]] = built["label_value"]
        if "quarantine" in built:
            quarantine_findings[doc["doc_id"]] = built["quarantine"]
        if "table_join" in built:
            join_findings[doc["doc_id"]] = built["table_join"]
        if "report_boundaries" in built:
            boundary_findings[doc["doc_id"]] = built["report_boundaries"]
        if "section_context" in built:
            section_findings[doc["doc_id"]] = built["section_context"]
        if "form_blocks" in built:
            block_findings[doc["doc_id"]] = built["form_blocks"]
        if "document_context" in built:
            single_findings[doc["doc_id"]] = built["document_context"]
        if file["document_type"] in context_types(k1_config):
            coverage[doc["doc_id"]] = context_coverage(built["chunks"])
        included.append({"doc_id": doc["doc_id"], "file_id": file["file_id"], "sha256": doc["sha256"],
                         "document_type": file["document_type"], "pages": file["page_count"],
                         "chunks": len(built["chunks"]), "tables": len(built["tables"]), "forms": len(built["forms"])})
    require_complete(corpus, name, fingerprint, documents + unknown_documents, included, held, sets)
    legacy_records = map_legacy_document(legacy_chunks, sets["chunks"]) if legacy_chunks is not None else None
    corpus.exports.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=corpus.exports))
    try:
        for group in GROUPS:
            write_text(staging / f"{group}.jsonl", "".join(dumps(canonical(row)) for row in sets[group]))
        for path, text in texts.items():
            write_text(staging / path, text)
        if legacy_records is not None:
            write_text(staging / LEGACY_MAP, dumps(legacy_records, indent=2))
        manifest = {"format": "K1", "schema_version": SCHEMA_VERSION,
                    "identity": package_identity(fingerprint, k1_config), "corpus_fingerprint": fingerprint,
                    "config": {"corpus": config, "k1": k1_config},
                    "ocr": {"engine": ocr["settings"]["engine"], "runtime": ocr["runtime"], "models": ocr["models"]},
                    "geometry_pdf_points": 0.01, "counts": {group: len(sets[group]) for group in GROUPS},
                    "documents": included, "context_coverage": coverage, "pages_without_context": missing,
                    "form_conflicts": conflicts, "held_back": held}
        write_text(staging / MANIFEST, dumps(manifest, indent=2))
        names = sorted(path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file())
        write_text(staging / SUMS, "".join(f"{file_sha256(staging / name)}  {name}\n" for name in names))
        release = publish(staging, corpus.exports / name, marker=MANIFEST, digest=file_sha256(staging / SUMS),
                          validate=validate_k1)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    result = {"export": str(release), "release": release.name, **manifest["counts"], "held_back": len(held)}
    if k1_config.get("table_rules"):
        # Outside the package on purpose: which tables were rebuilt and why Docling's table was kept (ops_tables).
        result["table_repairs"] = repairs
    if k1_config.get("section_context"):
        # Outside the package on purpose: which headings were removed from section values, and why (section_context).
        result["section_context"] = section_findings
    if "label_value" in config["chunking"]:
        # Outside the package on purpose: values moved back to their own label and the label cells left alone, with reasons (label_value).
        result["label_value"] = label_findings
    if "quarantine" in config["chunking"]:
        # Outside the package on purpose: findings, page status, dropped items and the chunk_id join (quarantine).
        result["quarantine"] = quarantine_findings
    if k1_config.get("table_join"):
        # Outside the package on purpose: every pair examined with its decision, reasons and evidence, the tables absorbed into others and the old-to-new chunk ids (table_join).
        result["table_join"] = join_findings
    if k1_config.get("form_blocks"):
        # Outside the package on purpose: labels left out because their value was ambiguous, and pages the block reader failed on (form_blocks).
        result["form_blocks"] = block_findings
    if "report_boundaries" in k1_config:
        result["report_boundaries"] = boundary_findings
    if k1_config.get("document_context"):
        # Outside the package on purpose: the well found for each document and the candidates it came from (document_context).
        result["document_context"] = single_findings
    if legacy_records is not None:
        result["legacy_map"] = summarize_legacy_map(legacy_records)
    return result
