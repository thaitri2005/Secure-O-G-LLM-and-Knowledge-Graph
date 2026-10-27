"""Assemble a corpus export: one directory of JSONL files plus manifest and checksums, swapped in atomically."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from .catalog import Corpus, copy_tree_atomic, now
from .process import is_complete, output_directory
from .store import atomic_write_json, atomic_write_text, file_sha256

FILES = ("documents.jsonl", "chunks.jsonl", "tables.jsonl")


def export(corpus: Corpus, name: str, models: Path, allow_review: bool = True) -> dict[str, Any]:
    """Export every complete, non-retired document of the current fingerprint, in doc_id order.

    Documents that failed or are not processed are listed in the manifest, never silently dropped.
    With ``allow_review=False`` documents with review or missing pages are held back as well.
    """
    from .config import fingerprint as make_fingerprint
    from .ocr_engines import engine_fingerprint
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("Export names use lowercase letters, digits, _ and -")
    config = corpus.config
    ocr = engine_fingerprint(models, config["ocr"])
    fingerprint = make_fingerprint(config, ocr["models"])
    jobs = corpus.jobs(fingerprint)
    corpus.exports.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=corpus.exports))
    included, held, counts = [], [], {"documents": 0, "chunks": 0, "tables": 0, "pages": 0, "review_pages": 0}
    try:
        streams = {file: (staging / file).open("w", encoding="utf-8", newline="\n") for file in FILES}
        try:
            for doc in corpus.documents():
                directory = output_directory(corpus, doc["doc_id"], fingerprint)
                job = jobs.get(doc["doc_id"])
                if not job or job["status"] != "done" or not is_complete(directory):
                    held.append({"doc_id": doc["doc_id"], "reason": (job or {}).get("error") or "not processed"})
                    continue
                document = json.loads((directory / "document.json").read_text(encoding="utf-8"))
                if not allow_review and (document["review_pages"] or document["missing_pages"]):
                    held.append({"doc_id": doc["doc_id"], "reason": "pages need review"})
                    continue
                streams["documents.jsonl"].write(json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n")
                for file, source in (("chunks.jsonl", "chunks.jsonl"), ("tables.jsonl", "tables.jsonl")):
                    with (directory / source).open(encoding="utf-8") as stream:
                        for line in stream:
                            streams[file].write(line)
                            counts["chunks" if file == "chunks.jsonl" else "tables"] += 1
                counts["documents"] += 1
                counts["pages"] += document["page_count"] or 0
                counts["review_pages"] += len(document["review_pages"]) + len(document["missing_pages"])
                included.append({"doc_id": doc["doc_id"], "sha256": doc["sha256"],
                                 "chunks": document["chunk_count"], "review_pages": document["review_pages"],
                                 "missing_pages": document["missing_pages"]})
        finally:
            for stream in streams.values():
                stream.close()
        manifest = {"export": name, "created_at": now(), "fingerprint": fingerprint, "config": config,
                    "ocr": {"engine": ocr["settings"]["engine"], "runtime": ocr["runtime"], "models": ocr["models"]},
                    "counts": counts, "documents": included, "held_back": held}
        atomic_write_json(staging / "manifest.json", manifest)
        atomic_write_text(staging / "SHA256SUMS", "".join(f"{file_sha256(staging / file)}  {file}\n"
                                                          for file in (*FILES, "manifest.json")))
        copy_tree_atomic(staging, corpus.exports / name)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"export": str(corpus.exports / name), **counts, "held_back": len(held)}
