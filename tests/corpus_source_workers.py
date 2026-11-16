"""Worker functions the spawned processes of tests/test_corpus_source_copy.py import (not a test module).

``source_task`` does what ``process_document`` does with the working copy of the source (``ensure_source``), then dies
when ``<corpus>/plan.json`` says so (as an out-of-memory kill would, leaving the copy behind) or finishes like a real
document: writes outputs and removes the copy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from corpus_pool_workers import write_outputs
from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.process import ensure_source, guarded_call, output_directory


def source_task(root, doc, config, fingerprint, ocr, models):
    corpus = Corpus(Path(root))
    plan = json.loads((Path(root) / "plan.json").read_text(encoding="utf-8"))
    directory = output_directory(corpus, doc["doc_id"], fingerprint)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "input.pdf"
    ensure_source(corpus, doc, source)
    with (Path(root) / "calls.log").open("a", encoding="utf-8") as stream:
        stream.write(doc["doc_id"] + "\n")
    if doc["doc_id"] in plan.get("die", []):
        os._exit(3)
    summary = write_outputs(directory, doc["doc_id"], fingerprint)
    source.unlink(missing_ok=True)
    return summary


def guarded_source(root, doc, config, fingerprint, ocr, models):
    return guarded_call(source_task, root, doc, config, fingerprint, ocr, models)
