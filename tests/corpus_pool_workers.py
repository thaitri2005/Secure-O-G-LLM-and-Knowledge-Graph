"""Worker functions the spawned processes of tests/test_corpus_resume.py import (not a test module).

``<corpus>/plan.json`` tells a task what to do for each document: ``die`` kills the worker after the marker is written
(as an out-of-memory kill would), ``raise`` raises an ordinary exception. Every call is appended to ``<corpus>/calls.log``.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.process import OUTPUTS, guarded_call, output_directory, summarize


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_outputs(directory: Path, doc_id: str, fingerprint: str) -> dict:
    """A minimal intact output directory (manifest digests match) with a valid document.json."""
    directory.mkdir(parents=True, exist_ok=True)
    record = {"page_count": 1, "chunk_count": 2, "table_count": 0, "pages": [{"page": 1, "mode": "text"}],
              "review_pages": [], "missing_pages": [], "processing": {"seconds": 0.5}}
    for name in OUTPUTS:
        (directory / name).write_bytes(f"{doc_id}:{name}".encode())
    (directory / "document.json").write_text(json.dumps(record), encoding="utf-8")
    manifest = {"doc_id": doc_id, "fingerprint": fingerprint, "completed_at": "2026-01-01T00:00:00+00:00",
                "files": {name: sha256(directory / name) for name in OUTPUTS}}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return summarize(record)


def fake_task(root, doc, config, fingerprint, ocr, models):
    plan = json.loads((Path(root) / "plan.json").read_text(encoding="utf-8"))
    with (Path(root) / "calls.log").open("a", encoding="utf-8") as stream:
        stream.write(doc["doc_id"] + "\n")
    time.sleep(plan.get("sleep", 0.3))
    if doc["doc_id"] in plan.get("die", []):
        os._exit(3)
    if doc["doc_id"] in plan.get("raise", []):
        raise ValueError("planned failure")
    if doc["doc_id"] in plan.get("interrupt", []):
        raise KeyboardInterrupt
    return write_outputs(output_directory(Corpus(Path(root)), doc["doc_id"], fingerprint), doc["doc_id"], fingerprint)


def guarded(root, doc, config, fingerprint, ocr, models):
    return guarded_call(fake_task, root, doc, config, fingerprint, ocr, models)


def dies_at_once(root, doc, config, fingerprint, ocr, models):
    """A worker that dies before it can write a marker (for example an import error in the child)."""
    os._exit(5)
