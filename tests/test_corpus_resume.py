"""C-04: worker death, interrupted and not-started documents, resume, retry and cache integrity of ``process``."""
from __future__ import annotations

from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from docling_core.types.doc import DocItemLabel
from pypdf import PdfWriter

from corpus_pool_workers import dies_at_once, fake_task, guarded, write_outputs
from graph_builder.corpus import process
from graph_builder.corpus.__main__ import main
from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import fingerprint as make_fingerprint, load_config
from graph_builder.corpus.process import (completed_summary, document_state, is_complete, marker_path, output_directory,
                                          process_document, read_marker, run, summarize, write_marker)
from graph_builder.corpus.store import file_sha256
from test_chunking import add_table, add_text, make_document

ROOT = Path(__file__).resolve().parents[1]
OCR = {"settings": {"engine": "easyocr"}, "runtime": {}, "models": {}}
MODELS = Path("models")


class ResumeCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.corpus = Corpus.create(self.root / "corpus", load_config(ROOT / "configs/corpus/default.json"))
        self.fingerprint = make_fingerprint(self.corpus.config, {})
        patcher = patch("graph_builder.corpus.ocr_engines.engine_fingerprint", return_value=OCR)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ids = [f"doc{n}" for n in range(6)]
        for n, doc_id in enumerate(self.ids):
            pdf = self.root / f"{doc_id}.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=600 + n, height=1000)  # distinct bytes, so six distinct documents
            writer.write(pdf)
            self.assertEqual(self.corpus.add_file(pdf, doc_id=doc_id)[0], "added")

    def plan(self, **plan):
        (self.corpus.root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    def calls(self) -> list[str]:
        path = self.corpus.root / "calls.log"
        return path.read_text(encoding="utf-8").split() if path.is_file() else []

    def clear_calls(self):
        (self.corpus.root / "calls.log").unlink(missing_ok=True)

    def directory(self, doc_id: str) -> Path:
        return output_directory(self.corpus, doc_id, self.fingerprint)

    def state(self, doc_id: str) -> str:
        return document_state(self.directory(doc_id), self.corpus.jobs(self.fingerprint).get(doc_id))[0]

    def statuses(self) -> dict[str, str]:
        return {doc_id: job["status"] for doc_id, job in self.corpus.jobs(self.fingerprint).items()}

    def do_run(self, workers=1, retry_failed=False, **options):
        with patch.object(process, "_guarded", guarded), patch.object(process, "process_document", fake_task):
            return run(self.corpus, MODELS, workers=workers, retry_failed=retry_failed, report=lambda line: None,
                       heartbeat=0, **options)


class WorkerDeathTests(ResumeCase):
    def test_documents_that_never_ran_are_not_marked_failed(self):
        self.plan(die=["doc2"], sleep=0.4)
        counts = self.do_run(workers=2)
        statuses = self.statuses()
        self.assertEqual(statuses.pop("doc2"), "failed")
        self.assertEqual(set(statuses.values()), {"done"}, statuses)
        self.assertEqual(sorted(statuses), [d for d in self.ids if d != "doc2"])  # every other document is recorded
        self.assertEqual((counts["done"], counts["failed"], counts["not_started"]), (5, 1, 0))
        error = self.corpus.jobs(self.fingerprint)["doc2"]["error"]
        self.assertIn("ran alone", error)
        self.assertEqual([self.state(d) for d in self.ids], ["completed", "completed", "failed", "completed",
                                                            "completed", "completed"])
        self.assertTrue(all(read_marker(self.directory(d)) is None for d in self.ids))

    def test_documents_killed_with_the_pool_are_run_again_alone_and_finish(self):
        self.plan(die=["doc2"], sleep=0.4)
        self.do_run(workers=2)
        # doc2 killed the pool; whatever else was running was re-run alone and completed rather than failed
        self.assertEqual(sorted(d for d, s in self.statuses().items() if s == "failed"), ["doc2"])
        self.assertTrue(all(is_complete(self.directory(d)) for d in self.ids if d != "doc2"))

    def test_completed_outputs_are_untouched_by_a_later_death_and_by_the_retry(self):
        self.plan(sleep=0.1)
        self.do_run(workers=1, only=["doc0", "doc1"])
        before = {d: file_sha256(self.directory(d) / "manifest.json") for d in ("doc0", "doc1")}
        self.plan(die=["doc3"], sleep=0.3)
        self.do_run(workers=2)
        self.assertEqual(before, {d: file_sha256(self.directory(d) / "manifest.json") for d in ("doc0", "doc1")})
        self.assertEqual(sum(call in ("doc0", "doc1") for call in self.calls()), 2)  # each ran once, in the first run
        self.clear_calls()
        self.plan(sleep=0.1)
        self.assertEqual(self.do_run(workers=1)["skipped"], 6)  # without --retry-failed nothing runs: doc3 stays failed
        self.assertEqual(self.calls(), [])
        counts = self.do_run(workers=1, retry_failed=True)
        self.assertEqual(self.calls(), ["doc3"])  # the retry runs the failed document and nothing else
        self.assertEqual((counts["done"], counts["failed"], counts["skipped"]), (1, 0, 5))
        self.assertEqual(set(self.statuses().values()), {"done"})
        self.assertEqual(before, {d: file_sha256(self.directory(d) / "manifest.json") for d in ("doc0", "doc1")})

    def test_a_pool_that_dies_before_anything_started_does_not_fail_or_loop(self):
        with patch.object(process, "_guarded", dies_at_once):
            counts = run(self.corpus, MODELS, workers=2, report=lambda line: None, heartbeat=0)
        self.assertEqual((counts["done"], counts["failed"], counts["not_started"]), (0, 0, 6))
        self.assertEqual(self.statuses(), {})  # nothing is recorded: the documents are simply still pending
        self.assertEqual({self.state(d) for d in self.ids}, {"not_started"})
        self.plan(sleep=0.1)  # the next run processes them normally
        self.assertEqual(self.do_run(workers=2)["done"], 6)

    def test_one_documents_exception_leaves_the_others_untouched(self):
        self.plan(**{"raise": ["doc1"]}, sleep=0.1)
        counts = self.do_run(workers=2)
        self.assertEqual((counts["done"], counts["failed"]), (5, 1))
        self.assertIn("planned failure", self.corpus.jobs(self.fingerprint)["doc1"]["error"])
        self.assertIsNone(read_marker(self.directory("doc1")))  # an exception is a failure, not an interruption


class OutcomeTests(unittest.TestCase):
    def test_a_finished_future_keeps_its_own_result(self):
        future = Future()
        future.set_result(("done", {"pages": 1}, None))
        self.assertEqual(process._outcome(future), ("done", {"pages": 1}, None))

    def test_a_broken_or_pending_future_has_no_result(self):
        broken, pending = Future(), Future()
        broken.set_exception(BrokenProcessPool("died"))
        self.assertIsNone(process._outcome(broken))
        self.assertIsNone(process._outcome(pending))

    def test_another_exception_fails_only_that_document(self):
        future = Future()
        future.set_exception(ValueError("cannot pickle"))
        self.assertEqual(process._outcome(future), ("failed", None, "ValueError: cannot pickle"))


class StateTests(ResumeCase):
    def test_states_from_the_files_and_the_catalog(self):
        done, bare, killed, failed, tampered = (self.directory(d) for d in ("doc0", "doc1", "doc2", "doc3", "doc4"))
        write_outputs(done, "doc0", self.fingerprint)
        self.corpus.record_job("doc0", self.fingerprint, "done", None, "s", 1.0, {})
        write_marker(killed, "doc2", self.fingerprint, "running")
        self.corpus.record_job("doc3", self.fingerprint, "failed", "boom", "s", 1.0, None)
        write_outputs(tampered, "doc4", self.fingerprint)
        self.corpus.record_job("doc4", self.fingerprint, "done", None, "s", 1.0, {})
        (tampered / "chunks.jsonl").write_bytes(b"changed afterwards")
        jobs = self.corpus.jobs(self.fingerprint)
        self.assertEqual(document_state(done, jobs["doc0"]), ("completed", "recorded"))
        self.assertEqual(document_state(bare, None), ("not_started", "pending"))
        self.assertEqual(document_state(killed, None), ("interrupted", "started_without_finishing"))
        self.assertEqual(document_state(failed, jobs["doc3"]), ("failed", "recorded_failure"))
        self.assertEqual(document_state(tampered, jobs["doc4"]), ("not_started", "output_missing_or_changed"))
        # the cheap check used by `status` trusts the manifest and so cannot see the changed file
        self.assertEqual(document_state(tampered, jobs["doc4"], verify=False), ("completed", "recorded"))

    def test_an_intact_output_beats_a_leftover_marker(self):
        directory = self.directory("doc0")
        write_outputs(directory, "doc0", self.fingerprint)
        write_marker(directory, "doc0", self.fingerprint, "running")
        self.assertEqual(document_state(directory, None), ("completed", "unrecorded"))

    def test_status_reports_the_four_states(self):
        write_outputs(self.directory("doc0"), "doc0", self.fingerprint)
        self.corpus.record_job("doc0", self.fingerprint, "done", None, "s", 1.0, {})
        write_marker(self.directory("doc1"), "doc1", self.fingerprint, "running")
        self.corpus.record_job("doc2", self.fingerprint, "failed", "boom", "s", 1.0, None)
        with self.assertLogs("graph_builder.corpus.cli", "INFO") as captured:  # the CLI prints through this logger
            self.assertEqual(main(["status", str(self.corpus.root)]), 0)
        lines = [record.getMessage() for record in captured.records]
        summary = json.loads(next(line for line in lines if line.startswith("{")))
        self.assertEqual(summary["states"], {"completed": 1, "interrupted": 1, "failed": 1, "not_started": 3})
        self.assertEqual(summary["jobs"], {"done": 1, "failed": 1, "pending": 4})  # the existing counts are unchanged
        self.assertIn("interrupted doc1: started_without_finishing", lines)


class ResumeTests(ResumeCase):
    def test_a_run_stopped_by_the_user_leaves_the_document_interrupted_and_resumes_it(self):
        self.plan(interrupt=["doc2"], sleep=0)
        with self.assertRaises(KeyboardInterrupt):
            self.do_run(workers=1)
        self.assertEqual([self.state(d) for d in self.ids[:4]], ["completed", "completed", "interrupted", "not_started"])
        self.assertEqual(sorted(self.statuses()), ["doc0", "doc1"])  # the interrupted document is not a recorded failure
        self.clear_calls()
        self.plan(sleep=0)
        counts = self.do_run(workers=1)
        self.assertEqual(self.calls(), ["doc2", "doc3", "doc4", "doc5"])  # doc0 and doc1 are not processed again
        self.assertEqual((counts["done"], counts["skipped"], counts["failed"]), (4, 2, 0))
        self.assertEqual(set(self.statuses().values()), {"done"})
        self.assertIsNone(read_marker(self.directory("doc2")))

    def test_a_finished_output_without_a_catalog_record_is_recorded_not_reprocessed(self):
        self.plan(sleep=0)
        self.do_run(workers=1, only=["doc0"])
        expected = self.corpus.jobs(self.fingerprint)["doc0"]["summary"]
        with self.corpus.connect() as connection:  # the process died after the manifest and before the catalog update
            connection.execute("DELETE FROM jobs WHERE doc_id = 'doc0'")
        self.assertEqual(self.state("doc0"), "completed")
        self.clear_calls()
        counts = self.do_run(workers=1, only=["doc0"])
        self.assertEqual(self.calls(), [])
        self.assertEqual((counts["done"], counts["skipped"]), (0, 1))
        self.assertEqual(self.corpus.jobs(self.fingerprint)["doc0"]["status"], "done")
        self.assertEqual(self.corpus.jobs(self.fingerprint)["doc0"]["summary"], expected)

    def test_a_changed_output_is_detected_and_only_that_document_is_rebuilt(self):
        self.plan(sleep=0)
        self.do_run(workers=1)
        untouched = file_sha256(self.directory("doc1") / "manifest.json")
        (self.directory("doc4") / "chunks.jsonl").write_bytes(b"damaged")
        self.clear_calls()
        counts = self.do_run(workers=1)
        self.assertEqual(self.calls(), ["doc4"])
        self.assertEqual((counts["done"], counts["skipped"]), (1, 5))
        self.assertTrue(is_complete(self.directory("doc4")))
        self.assertEqual(untouched, file_sha256(self.directory("doc1") / "manifest.json"))

    def test_the_summary_derived_from_the_record_equals_what_processing_returns(self):
        from graph_builder.corpus.process import process_document as real
        pdf = self.root / "real.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=777, height=1000)
        writer.add_blank_page(width=777, height=1000)
        writer.write(pdf)
        self.corpus.add_file(pdf, doc_id="real")
        document = make_document(2)
        add_text(document, "Overview", label=DocItemLabel.SECTION_HEADER)
        add_text(document, "First passage on page one.")
        add_table(document, rows=4)
        add_text(document, "Second passage on page two.", page=2)
        doc = next(d for d in self.corpus.documents() if d["doc_id"] == "real")
        analysis = [SimpleNamespace(to_dict=lambda n=n: {"page": n, "mode": "text", "reasons": ["x"]}) for n in (1, 2)]
        meta = {"mode": "text", "pages": (1, 2), "status": "success", "seconds": 1.0, "confidence": {}, "errors": []}
        with patch("graph_builder.corpus.process.analyze_pdf", return_value=analysis), \
                patch("graph_builder.corpus.process.convert_segment", return_value=(document, meta)):
            returned = real(str(self.corpus.root), doc, self.corpus.config, self.fingerprint, OCR, "models")
        self.assertEqual(returned, completed_summary(self.directory("real")))
        self.assertEqual((returned["pages"], returned["ocr_pages"]), (2, 0))
        self.assertGreater(returned["chunks"], 0)

    def test_summary_counts_ocr_and_hybrid_pages_and_review_pages(self):
        record = {"page_count": 3, "chunk_count": 5, "table_count": 1, "review_pages": [2], "missing_pages": [3],
                  "pages": [{"mode": "text"}, {"mode": "hybrid"}, {"mode": "ocr"}], "processing": {"seconds": 1.5}}
        self.assertEqual(summarize(record), {"pages": 3, "chunks": 5, "tables": 1, "ocr_pages": 2, "review_pages": 1,
                                             "missing_pages": 1, "seconds": 1.5})


class MarkerTests(ResumeCase):
    def test_the_marker_is_outside_the_manifest_and_does_not_change_completeness(self):
        directory = self.directory("doc0")
        write_outputs(directory, "doc0", self.fingerprint)
        before = file_sha256(directory / "manifest.json")
        write_marker(directory, "doc0", self.fingerprint, "running")
        self.assertTrue(marker_path(directory).is_file())
        self.assertTrue(is_complete(directory))
        self.assertEqual(before, file_sha256(directory / "manifest.json"))
        self.assertNotIn(marker_path(directory).name, json.loads((directory / "manifest.json").read_text())["files"])

    def test_an_unreadable_marker_still_means_the_document_had_started(self):
        directory = self.directory("doc0")
        directory.mkdir(parents=True)
        marker_path(directory).write_text("{not json", encoding="utf-8")
        self.assertEqual(document_state(directory, None)[0], "interrupted")


if __name__ == "__main__":
    unittest.main()
