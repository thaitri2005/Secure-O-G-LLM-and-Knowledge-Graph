"""Source preflight and the checksum contract for a published K1 retrieval view."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from ..process import OUTPUTS, is_complete
from ..store import atomic_write_json, blob_path, file_sha256, read_jsonl

VIEW = "retrieval_chunks.jsonl"
MANIFEST = "retrieval-manifest.json"


def source_problems(release: Path, corpus: Path | None, fingerprint: str) -> list[str]:
    if corpus is None or not (corpus / "work").is_dir():
        return ["QA needs the original corpus and conversion cache. Use --release-only for diagnostics."]
    if not re.fullmatch(r"[a-f0-9]{16}", fingerprint or ""):
        return ["K1 does not have a valid conversion cache fingerprint."]
    problems = []
    for document in read_jsonl(release / "files.jsonl"):
        digest, doc_id = document["sha256"], document["doc_id"]
        source = blob_path(corpus / "store", digest)
        if not source.is_file() or file_sha256(source) != digest:
            problems.append(f"{doc_id}: original PDF missing or checksum differs")
        work = corpus / "work" / doc_id / fingerprint
        if not matches_work(work, doc_id, digest):
            problems.append(f"{doc_id}: conversion cache missing or invalid")
    return problems


def matches_work(work: Path, doc_id: str, digest: str) -> bool:
    try:
        files = json.loads((work / "manifest.json").read_text(encoding="utf-8"))["files"]
        document = json.loads((work / "document.json").read_text(encoding="utf-8"))
        return (set(OUTPUTS) <= files.keys() and (document["doc_id"], document["sha256"]) == (doc_id, digest)
                and is_complete(work))
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return False


def seal_view(release: Path, view: Path, count: int) -> Path:
    manifest = view.parent / MANIFEST
    atomic_write_json(manifest, {"version": 1, "source_validation": "pass", "file": view.name, "chunks": count,
                                "release_checksum": file_sha256(release / "SHA256SUMS"),
                                "view_checksum": file_sha256(view)})
    return manifest


def read_verified_view(chunks: Path, view: Path) -> str:
    """Read the same bytes that are checked, for a single snapshot of the consumer input."""
    manifest = view.parent / MANIFEST
    if not manifest.is_file():
        raise FileNotFoundError(f"No verified retrieval manifest for {view}. Run corpus qa with the original corpus.")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    checksums = (chunks.parent / "SHA256SUMS").read_bytes()
    if (record.get("version") != 1 or record.get("source_validation") != "pass"
            or record.get("file") != view.name
            or hashlib.sha256(checksums).hexdigest() != record.get("release_checksum")):
        raise ValueError(f"Retrieval view {view} belongs to a different K1 release or has an invalid manifest")
    pairs = (line.split("  ", 1) for line in checksums.decode("utf-8").splitlines())
    matches = [pair[0] for pair in pairs if len(pair) == 2 and pair[1] == chunks.name]
    if matches != [file_sha256(chunks)]:
        raise ValueError(f"K1 chunks checksum differs for {chunks}")
    payload = view.read_bytes()
    if hashlib.sha256(payload).hexdigest() != record.get("view_checksum"):
        raise ValueError(f"Retrieval view checksum differs for {view}")
    # A concurrent QA run may have withdrawn or replaced the manifest while this view was being loaded.
    if json.loads(manifest.read_text(encoding="utf-8")) != record:
        raise ValueError(f"Retrieval view changed while opening {view}")
    return payload.decode("utf-8")
