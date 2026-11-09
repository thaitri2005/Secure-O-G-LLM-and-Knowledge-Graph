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
from .k1_build import build_document, canonical, context_coverage
from .k1_config import template_path
from .k1_validate import GROUPS, LEGACY_MAP, MANIFEST, SUMS, validate_k1
from .legacy_ids import LEGACY_DOCUMENT, load_legacy_rows, map_legacy_chunks, summarize_legacy_map
from .process import is_complete, output_directory
from .store import file_sha256
from .validate import SCHEMAS

SCHEMA_VERSION = 1


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
    """Export every processed PDF document of the current fingerprint (or those named in ``only``) in doc_id order.

    Documents that failed, are not processed or are not PDFs are listed in the manifest as held back, never dropped silently.
    """
    from .config import fingerprint as make_fingerprint
    from .ocr_engines import engine_fingerprint
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("Export names use lowercase letters, digits, _ and -")
    config = corpus.config
    documents = [doc for doc in corpus.documents() if not only or doc["doc_id"] in only]
    unknown = sorted(set(only or []) - {doc["doc_id"] for doc in documents})
    if unknown:
        raise ValueError(f"Unknown documents: {', '.join(unknown)}")
    ocr = engine_fingerprint(models, config["ocr"])
    fingerprint = make_fingerprint(config, ocr["models"])
    jobs = corpus.jobs(fingerprint)
    sets: dict[str, list[dict]] = {group: [] for group in GROUPS}
    texts: dict[str, str] = {}
    included, held, conflicts, missing, coverage, repairs = [], [], [], [], {}, []
    for doc in documents:
        job = jobs.get(doc["doc_id"])
        if not job or job["status"] != "done" or not is_complete(output_directory(corpus, doc["doc_id"], fingerprint)):
            held.append({"doc_id": doc["doc_id"], "reason": (job or {}).get("error") or "not processed"})
            continue
        if doc["format"] != "pdf":
            held.append({"doc_id": doc["doc_id"], "reason": "K1 packages hold PDF documents only"})
            continue
        built = build_document(corpus, doc, fingerprint, k1_config)
        for group in GROUPS:
            sets[group].extend(built[group])
        file = built["files"][0]
        texts[file["text"]] = built["text"]
        conflicts += built["form_conflicts"]
        missing += built["pages_without_context"]
        repairs += built["table_repairs"]
        if file["document_type"] in k1_config["report_context"]["document_types"]:
            coverage[doc["doc_id"]] = context_coverage(built["chunks"])
        included.append({"doc_id": doc["doc_id"], "file_id": file["file_id"], "sha256": doc["sha256"],
                         "document_type": file["document_type"], "pages": file["page_count"],
                         "chunks": len(built["chunks"]), "tables": len(built["tables"]), "forms": len(built["forms"])})
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
    if legacy_records is not None:
        result["legacy_map"] = summarize_legacy_map(legacy_records)
    return result
