"""WP-2 (REL-F1): the working copy ``input.*`` of a source is reused only if it matches the store; stale copies are rebuilt.

Covers: normal path, retry after the store was repaired (the REL-F1 case), resume of a completed document, fingerprint
and cache unaffected, failure isolation (also with a worker killed), and the store-still-corrupt error path.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import pickle
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from docling_core.types.doc import DocItemLabel
from pypdf import PdfWriter

from corpus_source_workers import guarded_source
from graph_builder.corpus import process
from graph_builder.corpus.__main__ import main
from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import fingerprint as make_fingerprint, load_config
from graph_builder.corpus.process import (SourceChecksumError, ensure_source, is_complete, output_directory,
                                          process_document, run)
from graph_builder.corpus.store import file_sha256
from test_chunking import add_table, add_text, make_document

ROOT = Path(__file__).resolve().parents[1]
OCR = {"settings": {"engine": "easyocr"}, "runtime": {}, "models": {}}
MODELS = Path("models")
STORE_REASON = "source_checksum_mismatch_store"


def hard_links_work(directory: Path) -> bool:
    first, second = directory / "probe-a", directory / "probe-b"
    first.write_bytes(b"x")
    try:
        os.link(first, second)
        return True
    except OSError:
        return False


class SourceCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.corpus = Corpus.create(self.root / "corpus", load_config(ROOT / "configs/corpus/default.json"))
        self.fingerprint = make_fingerprint(self.corpus.config, {})
        patcher = patch("graph_builder.corpus.ocr_engines.engine_fingerprint", return_value=OCR)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ids = ["doc0", "doc1", "doc2"]
        for n, doc_id in enumerate(self.ids):
            self.corpus.add_file(self.make_pdf(self.root / f"{doc_id}.pdf", 600 + n), doc_id=doc_id)
        self.convert_calls: list[str] = []

    @staticmethod
    def make_pdf(path: Path, width: int) -> Path:
        writer = PdfWriter()
        writer.add_blank_page(width=width, height=1000)  # distinct bytes per document
        writer.write(path)
        return path

    def doc(self, doc_id: str, corpus: Corpus | None = None) -> dict:
        return next(d for d in (corpus or self.corpus).documents() if d["doc_id"] == doc_id)

    def blob(self, doc_id: str) -> Path:
        return self.corpus.blob(self.doc(doc_id)["sha256"])

    def directory(self, doc_id: str, corpus: Corpus | None = None) -> Path:
        return output_directory(corpus or self.corpus, doc_id, self.fingerprint)

    def source(self, doc_id: str) -> Path:
        return self.directory(doc_id) / "input.pdf"

    @staticmethod
    def replace_blob(blob: Path, data: bytes) -> None:
        """Publish new bytes as a NEW file (new inode), as put_blob / a restore from backup does."""
        staged = blob.with_name(blob.name + ".new")
        staged.write_bytes(data)
        os.replace(staged, blob)

    @staticmethod
    def damaged(data: bytes) -> bytes:
        return data[: len(data) // 2] + b"CORRUPTED" + data[len(data) // 2 + 9:]

    def listing(self, doc_id: str) -> list[str]:
        directory = self.directory(doc_id)
        return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []

    # -- real process_document / run with Docling replaced by a small fixed document -----------------------------------
    def fake_convert(self, source, kind, mode, pages, cache, config, models):
        doc_id = source.parent.parent.name
        self.convert_calls.append(doc_id)
        self.assertEqual(file_sha256(source), self.doc(doc_id)["sha256"])  # what reaches conversion matches the catalog
        document = make_document(1)
        add_text(document, "Overview", label=DocItemLabel.SECTION_HEADER)
        add_text(document, f"First passage of {doc_id}.")
        add_table(document, rows=4)
        meta = {"mode": "text", "pages": (1, 1), "status": "success", "seconds": 1.0, "confidence": {}, "errors": []}
        return document, meta

    @staticmethod
    def fake_analysis(source, settings):
        return [SimpleNamespace(to_dict=lambda: {"page": 1, "mode": "text", "reasons": ["x"]})]

    def do_run(self, retry_failed=False, corpus: Corpus | None = None, **options):
        with patch.object(process, "analyze_pdf", self.fake_analysis), \
                patch.object(process, "convert_segment", self.fake_convert):
            return run(corpus or self.corpus, MODELS, workers=1, retry_failed=retry_failed, report=lambda line: None,
                       heartbeat=0, **options)

    def jobs(self) -> dict:
        return self.corpus.jobs(self.fingerprint)

    def manifests(self, doc_ids) -> dict:
        return {d: file_sha256(self.directory(d) / "manifest.json") for d in doc_ids}


class EnsureSourceTests(SourceCase):
    def test_a_missing_copy_is_created_from_the_store_with_one_hash(self):
        doc, source = self.doc("doc0"), self.source("doc0")
        source.parent.mkdir(parents=True)
        with patch.object(process, "file_sha256", wraps=process.file_sha256) as hashed:
            ensure_source(self.corpus, doc, source)
        self.assertEqual(hashed.call_count, 1)  # same read cost as before the fix
        self.assertEqual(file_sha256(source), doc["sha256"])
        self.assertEqual(self.listing("doc0"), ["input.pdf"])  # no .partial left behind

    def test_a_matching_copy_is_reused_and_not_rewritten_with_one_hash(self):
        doc, source = self.doc("doc0"), self.source("doc0")
        source.parent.mkdir(parents=True)
        shutil.copyfile(self.blob("doc0"), source)
        before = source.stat()
        with patch.object(process, "file_sha256", wraps=process.file_sha256) as hashed, \
                patch.object(process.os, "replace") as replaced, patch.object(process.os, "link") as linked:
            ensure_source(self.corpus, doc, source)
        self.assertEqual(hashed.call_count, 1)
        replaced.assert_not_called()
        linked.assert_not_called()
        self.assertEqual((source.stat().st_ino, source.stat().st_mtime_ns), (before.st_ino, before.st_mtime_ns))

    def test_a_stale_full_copy_after_the_store_was_repaired_is_rebuilt(self):  # REL-F1, copy branch
        doc, source = self.doc("doc0"), self.source("doc0")
        source.parent.mkdir(parents=True)
        good = self.blob("doc0").read_bytes()
        source.write_bytes(self.damaged(good))
        ensure_source(self.corpus, doc, source)
        self.assertEqual(source.read_bytes(), good)
        self.assertEqual(self.listing("doc0"), ["input.pdf"])

    def test_a_truncated_copy_left_by_a_killed_copy_is_rebuilt(self):
        doc, source = self.doc("doc0"), self.source("doc0")
        source.parent.mkdir(parents=True)
        good = self.blob("doc0").read_bytes()
        source.write_bytes(good[: len(good) // 3])
        ensure_source(self.corpus, doc, source)
        self.assertEqual(source.read_bytes(), good)

    def test_a_stale_hard_link_to_a_replaced_blob_is_rebuilt(self):  # REL-F1 exactly as reproduced on the CLI
        if not hard_links_work(self.root):
            self.skipTest("hard links unavailable")
        doc, source, blob = self.doc("doc0"), self.source("doc0"), self.blob("doc0")
        source.parent.mkdir(parents=True)
        good = blob.read_bytes()
        self.replace_blob(blob, self.damaged(good))  # store damaged by replacement
        os.link(blob, source)  # what an earlier failed attempt left: input.pdf linked to the damaged blob
        self.replace_blob(blob, good)  # store repaired by replacement: the old link keeps the damaged inode
        self.assertNotEqual(file_sha256(source), doc["sha256"])
        ensure_source(self.corpus, doc, source)
        self.assertEqual(file_sha256(source), doc["sha256"])
        self.assertEqual(blob.read_bytes(), good)  # the store was not touched

    def test_the_copy_branch_is_used_when_hard_links_fail_and_stale_copies_are_still_rebuilt(self):
        doc, source = self.doc("doc0"), self.source("doc0")
        source.parent.mkdir(parents=True)
        good = self.blob("doc0").read_bytes()
        source.write_bytes(self.damaged(good))
        with patch.object(process.os, "link", side_effect=OSError("no hard links")):
            ensure_source(self.corpus, doc, source)
        self.assertEqual(source.read_bytes(), good)
        self.assertEqual(self.listing("doc0"), ["input.pdf"])

    def test_a_leftover_partial_file_is_replaced(self):
        doc, source = self.doc("doc0"), self.source("doc0")
        source.parent.mkdir(parents=True)
        source.with_name("input.pdf.partial").write_bytes(b"left by a killed run")
        ensure_source(self.corpus, doc, source)
        self.assertEqual(file_sha256(source), doc["sha256"])
        self.assertEqual(self.listing("doc0"), ["input.pdf"])

    def test_in_place_repair_of_the_store_still_works(self):  # regression: scenario C of the reproduction
        if not hard_links_work(self.root):
            self.skipTest("hard links unavailable")
        doc, source, blob = self.doc("doc0"), self.source("doc0"), self.blob("doc0")
        source.parent.mkdir(parents=True)
        good = blob.read_bytes()
        with blob.open("r+b") as stream:
            stream.seek(len(good) // 2)
            stream.write(b"CORRUPTED")
        with self.assertRaises(SourceChecksumError):
            ensure_source(self.corpus, doc, source)
        with blob.open("r+b") as stream:
            stream.write(good)
        ensure_source(self.corpus, doc, source)
        self.assertEqual(file_sha256(source), doc["sha256"])

    def test_a_corrupt_store_gives_a_coded_error_and_leaves_no_wrong_file(self):
        doc, source, blob = self.doc("doc0"), self.source("doc0"), self.blob("doc0")
        source.parent.mkdir(parents=True)
        good = blob.read_bytes()
        bad = self.damaged(good)
        self.replace_blob(blob, bad)
        source.write_bytes(good[:10])  # a stale copy is present too
        with self.assertRaises(SourceChecksumError) as caught:
            ensure_source(self.corpus, doc, source)
        error = caught.exception
        self.assertIsInstance(error, ValueError)  # the CLI and callers that catch ValueError still see it
        self.assertEqual(error.reason, STORE_REASON)
        self.assertTrue(str(error).startswith(STORE_REASON + ": "))
        self.assertIn(doc["sha256"], str(error))
        self.assertEqual(self.listing("doc0"), [])  # neither input.pdf nor input.pdf.partial remains
        self.assertEqual(blob.read_bytes(), bad)  # the blob is reported, not modified or removed
        if hard_links_work(self.root):
            self.assertEqual(blob.stat().st_nlink, 1)

    def test_a_failure_to_replace_the_copy_is_reported_with_its_own_code_and_not_swallowed(self):
        doc, source = self.doc("doc0"), self.source("doc0")
        source.parent.mkdir(parents=True)
        stale = self.damaged(self.blob("doc0").read_bytes())
        source.write_bytes(stale)
        with patch.object(process.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(SourceChecksumError) as caught:
                ensure_source(self.corpus, doc, source)
        self.assertEqual(caught.exception.reason, "source_work_copy_replace_failed")
        self.assertIn("PermissionError", str(caught.exception))
        self.assertEqual(source.read_bytes(), stale)  # an unchecked file is never published under the name

    def test_a_missing_blob_keeps_the_original_os_error(self):
        doc, source = self.doc("doc0"), self.source("doc0")
        source.parent.mkdir(parents=True)
        self.blob("doc0").unlink()
        with self.assertRaises(FileNotFoundError):
            ensure_source(self.corpus, doc, source)

    def test_the_error_survives_a_trip_between_processes(self):
        error = pickle.loads(pickle.dumps(SourceChecksumError(STORE_REASON, "detail")))
        self.assertEqual((type(error), error.reason, str(error)), (SourceChecksumError, STORE_REASON, f"{STORE_REASON}: detail"))


class ProcessDocumentTests(SourceCase):
    OUTPUT_FILES = ("chunks.jsonl", "tables.jsonl", "text.txt")

    def process_one(self, corpus: Corpus, doc_id: str) -> Path:
        with patch.object(process, "analyze_pdf", self.fake_analysis), \
                patch.object(process, "convert_segment", self.fake_convert):
            process_document(str(corpus.root), self.doc(doc_id, corpus), corpus.config, self.fingerprint, OCR, "models")
        return self.directory(doc_id, corpus)

    @classmethod
    def content(cls, directory: Path) -> dict:
        record = json.loads((directory / "document.json").read_text(encoding="utf-8"))
        record["processing"].pop("seconds", None)
        for segment in record["processing"]["segments"]:
            segment.pop("seconds", None)
        out = {name: (directory / name).read_bytes() for name in cls.OUTPUT_FILES}
        out["document.json"] = json.dumps(record, sort_keys=True)
        out["docling.json"] = gzip.decompress((directory / "docling.json.gz").read_bytes())
        out["files"] = sorted(p.name for p in directory.iterdir())
        return out

    def test_the_output_does_not_depend_on_a_stale_copy_and_the_copy_is_removed(self):
        other = Corpus.create(self.root / "other", load_config(ROOT / "configs/corpus/default.json"))
        other.add_file(self.root / "doc0.pdf", doc_id="doc0")  # same bytes and doc id => same work path and fingerprint
        self.assertEqual(make_fingerprint(other.config, {}), self.fingerprint)  # fingerprint (cache key) unchanged
        clean = self.content(self.process_one(self.corpus, "doc0"))
        stale_dir = self.directory("doc0", other)
        stale_dir.mkdir(parents=True)
        (stale_dir / "input.pdf").write_bytes(self.blob("doc0").read_bytes()[:50])
        stale = self.content(self.process_one(other, "doc0"))
        self.assertEqual(clean, stale)
        self.assertNotIn("input.pdf", clean["files"])
        self.assertFalse(any(name.endswith(".partial") for name in clean["files"]))
        self.assertTrue(is_complete(self.directory("doc0")))

    def test_cached_segments_are_not_touched_by_rebuilding_the_copy(self):
        segment = self.directory("doc0") / "segments" / "00001-00001-text.json.gz"
        segment.parent.mkdir(parents=True)
        segment.write_bytes(b"cache")
        self.source("doc0").write_bytes(b"stale")
        ensure_source(self.corpus, self.doc("doc0"), self.source("doc0"))
        self.assertEqual(segment.read_bytes(), b"cache")


class RetryTests(SourceCase):
    def test_retry_after_the_store_is_repaired_completes_without_manual_cleanup(self):  # the REL-F1 case through run()
        blob = self.blob("doc1")
        good = blob.read_bytes()
        self.replace_blob(blob, self.damaged(good))
        counts = self.do_run()
        self.assertEqual((counts["done"], counts["failed"]), (2, 1))
        job = self.jobs()["doc1"]
        self.assertEqual(job["status"], "failed")
        self.assertTrue(job["error"].startswith(f"SourceChecksumError: {STORE_REASON}: "), job["error"])
        self.assertEqual(self.listing("doc1"), [])  # no wrong input.pdf is left to block a retry
        kept = self.manifests(["doc0", "doc2"])
        # the store is still damaged: the retry fails again with the same code, nothing is marked done
        counts = self.do_run(retry_failed=True)
        self.assertEqual((counts["done"], counts["failed"], counts["skipped"]), (0, 1, 2))
        self.assertEqual(self.jobs()["doc1"]["attempts"], 2)
        self.assertEqual(self.listing("doc1"), [])
        # the store is repaired by replacement; the same --retry-failed now completes
        self.replace_blob(blob, good)
        self.convert_calls.clear()
        counts = self.do_run(retry_failed=True)
        self.assertEqual((counts["done"], counts["failed"], counts["skipped"]), (1, 0, 2))
        self.assertEqual(self.convert_calls, ["doc1"])
        self.assertEqual(self.jobs()["doc1"]["status"], "done")
        self.assertTrue(is_complete(self.directory("doc1")))
        self.assertNotIn("input.pdf", self.listing("doc1"))
        self.assertEqual(kept, self.manifests(["doc0", "doc2"]))  # failure isolation: the others never changed
        self.assertEqual(blob.read_bytes(), good)

    def test_a_stale_copy_left_by_an_older_run_no_longer_blocks_the_retry(self):
        directory = self.directory("doc1")
        directory.mkdir(parents=True)
        good = self.blob("doc1").read_bytes()
        (directory / "input.pdf").write_bytes(self.damaged(good))  # exactly what REL-F1 left on disk
        self.corpus.record_job("doc1", self.fingerprint, "failed", "ValueError: Stored source does not match its "
                               "catalogued SHA256", "s", 1.0, None)
        counts = self.do_run(retry_failed=True)
        self.assertEqual((counts["done"], counts["failed"]), (3, 0))
        self.assertEqual(self.jobs()["doc1"]["status"], "done")
        self.assertEqual(self.jobs()["doc1"]["attempts"], 2)

    def test_resume_of_completed_documents_does_not_touch_them_or_their_copies(self):
        self.do_run()
        before = self.manifests(self.ids)
        listings = {d: self.listing(d) for d in self.ids}
        self.convert_calls.clear()
        with patch.object(process, "ensure_source") as ensured:
            counts = self.do_run(retry_failed=True)
        self.assertEqual((counts["done"], counts["failed"], counts["skipped"]), (0, 0, 3))
        ensured.assert_not_called()
        self.assertEqual(self.convert_calls, [])
        self.assertEqual(before, self.manifests(self.ids))
        self.assertEqual(listings, {d: self.listing(d) for d in self.ids})

    def test_a_document_interrupted_in_the_middle_of_its_copy_is_resumed(self):
        directory = self.directory("doc1")
        directory.mkdir(parents=True)
        good = self.blob("doc1").read_bytes()
        (directory / "input.pdf").write_bytes(good[: len(good) // 2])  # death inside copyfile
        process.write_marker(directory, "doc1", self.fingerprint, "running")
        counts = self.do_run()
        self.assertEqual((counts["done"], counts["failed"]), (3, 0))
        self.assertIsNone(process.read_marker(directory))
        self.assertTrue(is_complete(directory))

    def test_failure_isolation_one_bad_store_does_not_stop_or_change_the_other_documents(self):
        for doc_id in ("doc0", "doc2"):
            self.replace_blob(self.blob(doc_id), self.damaged(self.blob(doc_id).read_bytes()))
        counts = self.do_run()
        self.assertEqual((counts["done"], counts["failed"]), (1, 2))
        self.assertEqual({d: j["status"] for d, j in self.jobs().items()}, {"doc0": "failed", "doc1": "done", "doc2": "failed"})
        self.assertTrue(is_complete(self.directory("doc1")))

    def test_status_shows_the_reason_code(self):
        self.replace_blob(self.blob("doc1"), self.damaged(self.blob("doc1").read_bytes()))
        self.do_run()
        with self.assertLogs("graph_builder.corpus.cli", "INFO") as captured:
            self.assertEqual(main(["status", str(self.corpus.root)]), 0)
        lines = [record.getMessage() for record in captured.records]
        self.assertTrue(any(line.startswith(f"failed doc1: SourceChecksumError: {STORE_REASON}: ") for line in lines), lines)


class WorkerKillTests(SourceCase):
    def plan(self, **plan):
        (self.corpus.root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    def do_pool(self, retry_failed=False):
        with patch.object(process, "_guarded", guarded_source):
            return run(self.corpus, MODELS, workers=2, retry_failed=retry_failed, report=lambda line: None, heartbeat=0)

    def test_a_worker_killed_after_the_copy_leaves_a_copy_that_the_retry_checks_and_replaces(self):
        self.plan(die=["doc1"])
        counts = self.do_pool()
        self.assertEqual(self.jobs()["doc1"]["status"], "failed")
        self.assertEqual((counts["done"], counts["failed"]), (2, 1))
        done = self.manifests(["doc0", "doc2"])
        copy = self.source("doc1")
        self.assertTrue(copy.is_file())  # the killed worker left its copy (valid here)
        cut = copy.read_bytes()[:40]
        copy.unlink()  # not written in place: the copy may be a hard link to the blob, and that must stay intact
        copy.write_bytes(cut)  # and, in the other case, a copy cut short
        self.plan()
        counts = self.do_pool(retry_failed=True)
        self.assertEqual((counts["done"], counts["failed"], counts["skipped"]), (1, 0, 2))
        self.assertTrue(is_complete(self.directory("doc1")))
        self.assertNotIn("input.pdf", self.listing("doc1"))
        self.assertEqual(done, self.manifests(["doc0", "doc2"]))


if __name__ == "__main__":
    unittest.main()
