"""K1 export completeness gate: success path, failure report, no partial output, CLI exit codes, CURRENT protection.

The gate (``k1_export.require_complete``) refuses to publish unless every required document is present and ready.
These tests cover the behaviour around it. The gate itself and the older, narrower gate tests live in
``test_corpus_k1.py`` (``CompletenessGateTests``).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

from graph_builder.corpus.k1_build import ReportBoundaryError, build_document
from graph_builder.corpus.k1_export import K1CompletenessError, export_k1
from graph_builder.corpus.k1_validate import GROUPS, summary, validate_k1
from graph_builder.publication import POINTER, PublicationError, current_release
import test_corpus_k1 as base

ROOT = Path(__file__).resolve().parents[1]
FAILURES = ".k1-failures"

REPORT_KEYS = {"gate", "status", "export_name", "corpus_fingerprint", "reason", "required_documents", "ready_documents",
               "blocked_documents", "missing_document_ids", "unexpected_document_ids", "counts", "published",
               "current_updated"}
COUNT_KEYS = {"required_documents", "ready_documents", "blocked_documents", "published_documents",
              "pages_held_known", "pages_held_unknown_documents", "corpus_chunks_held_known",
              "corpus_chunks_held_unknown_documents", "k1_chunks_held_known", "k1_chunks_held_unknown_documents"}
BLOCKED_KEYS = {"doc_id", "sha256", "source", "original_name", "status", "reason", "detail", "pages_held",
                "corpus_chunks_held", "k1_chunks_held", "source_references", "source_reference_error"}
REQUIRED_KEYS = {"doc_id", "sha256", "pages"}
READY_KEYS = {"doc_id", "file_id", "sha256", "document_type", "pages", "chunks", "tables", "forms"}

# The real command line, with only the OCR engine fingerprint replaced (as every export test does).
DRIVER = """
import runpy, sys
from unittest.mock import patch
ocr = {"settings": {"engine": "easyocr"}, "runtime": {"easyocr": "1.0"}, "models": {}}
with patch("graph_builder.corpus.ocr_engines.engine_fingerprint", return_value=ocr):
    runpy.run_module("graph_builder.corpus", run_name="__main__")
"""


def tree(root: Path) -> dict[str, str]:
    """Relative path -> sha256 for every file under ``root`` (empty when ``root`` does not exist)."""
    if not root.exists():
        return {}
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def directories(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()} if root.exists() else set()


class Case(base.PackageCase):
    def blocked(self, name: str = "one", only: list[str] | None = None) -> K1CompletenessError:
        with self.assertRaises(K1CompletenessError) as caught:
            self.export(name, only=only)
        return caught.exception

    def release_files(self, name: str) -> dict[str, str]:
        return tree(current_release(self.corpus.exports / name))


class SuccessTests(Case):
    def test_complete_corpus_gives_a_valid_deterministic_package_and_no_failure_report(self):
        base.add_sample(self.corpus, self.root, "sample-first", self.fingerprint)
        base.add_sample(self.corpus, self.root, "sample-second", self.fingerprint, width=700)
        result = export_k1(self.corpus, "one", Path("models"), base.K1_CONFIG)
        first = Path(result["export"])
        self.assertEqual(result["held_back"], 0)
        self.assertEqual(result["files"], 2)
        self.assertEqual(validate_k1(first), [])
        self.assertEqual(summary(first)["status"], "pass")
        manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["held_back"], [])
        self.assertEqual([d["doc_id"] for d in manifest["documents"]], ["sample-first", "sample-second"])
        second = self.export("two")
        self.assertEqual(tree(first), tree(second))  # every file, byte for byte
        self.assertEqual(current_release(self.corpus.exports / "one"), first)
        self.assertFalse((self.corpus.exports / FAILURES).exists())


class FailureReportTests(Case):
    """Each way a required document can be missing or unready raises, with the documented failure.json."""

    def check_report(self, error: K1CompletenessError, name: str, status: str, reason: str, detail=None) -> dict:
        path = error.report_path
        self.assertEqual(path.name, "failure.json")
        self.assertEqual(path.parent.parent, self.corpus.exports / FAILURES)
        self.assertTrue(path.parent.name.startswith(name + "-"))
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["failure.json"])
        raw = path.read_bytes()
        self.assertNotIn(b"\r", raw)
        report = json.loads(raw.decode("utf-8"))
        self.assertEqual(report, error.report)
        self.assertEqual(set(report), REPORT_KEYS)
        self.assertEqual(set(report["counts"]), COUNT_KEYS)
        self.assertEqual((report["gate"], report["status"], report["reason"]), ("TC-07", "BLOCKED", "required_documents_incomplete"))
        self.assertEqual(report["export_name"], name)
        self.assertEqual(report["corpus_fingerprint"], self.fingerprint)
        self.assertIs(report["published"], False)
        self.assertIs(report["current_updated"], False)
        self.assertEqual(report["counts"]["published_documents"], 0)
        self.assertEqual(report["counts"]["blocked_documents"], len(report["blocked_documents"]))
        self.assertEqual(report["counts"]["ready_documents"], len(report["ready_documents"]))
        self.assertEqual(report["counts"]["required_documents"], len(report["required_documents"]))
        for row in report["required_documents"]:
            self.assertEqual(set(row), REQUIRED_KEYS)
        for row in report["ready_documents"]:
            self.assertEqual(set(row), READY_KEYS)
        for row in report["blocked_documents"]:
            self.assertEqual(set(row), BLOCKED_KEYS)
        held = report["blocked_documents"][0]
        self.assertEqual((held["status"], held["reason"], held["detail"]), (status, reason, detail))
        self.assertEqual(str(error), f"K1 release BLOCKED: required_documents_incomplete; failure report: {path}")
        return report

    def assert_nothing_published(self, name: str, before: dict[str, str]):
        exports = self.corpus.exports
        self.assertFalse((exports / name).exists(), "no publication directory is created by a failed first export")
        self.assertEqual([p.name for p in exports.iterdir() if p.name != FAILURES and p.name.startswith(".")], [],
                         "no staging directory is left behind")
        new = set(tree(exports)) - set(before)
        self.assertEqual({p.split("/")[0] for p in new}, {FAILURES})
        self.assertEqual(len(new), 1)

    def test_unprocessed_failed_and_missing_output_documents(self):
        base.add_sample(self.corpus, self.root, "sample-pending", self.fingerprint, process=False, width=700)
        error = self.blocked("pending")
        report = self.check_report(error, "pending", "NOT_PROCESSED", "processing_not_complete", "not processed")
        self.assertEqual(report["missing_document_ids"], ["sample-pending"])
        self.assertEqual(report["ready_documents"], [])
        doc = base.add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        self.corpus.record_job(doc["doc_id"], self.fingerprint, "failed", "fixture failure", "start", 1, {})
        self.check_report(self.blocked("failed", only=["sample-report"]), "failed", "FAILED", "processing_not_complete",
                          "fixture failure")
        self.corpus.record_job(doc["doc_id"], self.fingerprint, "done", None, "start", 1, {})
        output = self.corpus.work / doc["doc_id"] / self.fingerprint
        (output / "manifest.json").unlink()
        report = self.check_report(self.blocked("nomanifest", only=["sample-report"]), "nomanifest", "NOT_PROCESSED",
                                   "processing_not_complete", "not processed")
        self.assertEqual(report["blocked_documents"][0]["corpus_chunks_held"], 3)

    def test_unreadable_output_is_reported_without_inventing_counts(self):
        doc = base.add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        chunks = self.corpus.work / doc["doc_id"] / self.fingerprint / "chunks.jsonl"
        chunks.write_text("not json\n", encoding="utf-8", newline="\n")
        report = self.check_report(self.blocked(), "one", "NOT_PROCESSED", "processing_not_complete", "not processed")
        held = report["blocked_documents"][0]
        self.assertIsNone(held["source_references"])
        self.assertIsNone(held["corpus_chunks_held"])
        self.assertRegex(held["source_reference_error"], r"^JSONDecodeError")
        self.assertEqual(report["counts"]["corpus_chunks_held_unknown_documents"], 1)
        self.assertEqual(report["counts"]["corpus_chunks_held_known"], 0)

    def test_unsupported_format_and_unknown_required_document(self):
        doc = base.add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        with patch.object(self.corpus, "documents", return_value=[dict(doc, format="text")]):
            error = self.blocked("unsupported")
        self.check_report(error, "unsupported", "UNSUPPORTED", "unsupported_format", "text")
        error = self.blocked("unknown", only=["sample-report", "absent-source"])
        report = self.check_report(error, "unknown", "NOT_FOUND", "unknown_required_document")
        held = report["blocked_documents"][0]
        self.assertEqual((held["doc_id"], held["sha256"], held["pages_held"]), ("absent-source", None, None))
        self.assertEqual(report["missing_document_ids"], ["absent-source"])
        self.assertEqual([row["doc_id"] for row in report["ready_documents"]], ["sample-report"])
        only_unknown = self.blocked("nothing", only=["absent-source"])
        self.assertEqual(only_unknown.report["ready_documents"], [])
        self.assertEqual(only_unknown.report["counts"]["required_documents"], 1)

    def test_builder_errors_and_report_boundaries(self):
        base.add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        with patch("graph_builder.corpus.k1_export.build_document", side_effect=ValueError("bad source")):
            self.check_report(self.blocked("builder"), "builder", "FAILED", "k1_build_failed", "ValueError: bad source")
        with patch("graph_builder.corpus.k1_export.build_document", return_value={}):
            error = self.blocked("empty")
        self.check_report(error, "empty", "FAILED", "k1_build_failed", "KeyError: 'files'")
        with patch("graph_builder.corpus.k1_export.build_document", side_effect=ReportBoundaryError("ambiguous", page=1)):
            error = self.blocked("boundary")
        self.check_report(error, "boundary", "BLOCKED", "report_boundaries", {"reason": "ambiguous", "page": 1})

    def test_every_completeness_problem_blocks_with_its_reason(self):
        doc = base.add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        built = build_document(self.corpus, doc, self.fingerprint, base.K1_CONFIG)
        foreign = "f" + "1" * 16

        def explicit(status):
            return lambda row: row.update(status=status)

        def duplicate_file(row):
            row["files"] = row["files"] * 2

        def change(path, value):
            def apply(row):
                target = row
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
            return apply

        cases = {
            "document_not_ready": explicit("BLOCKED"),
            "document_not_ready_failed": explicit("failed"),
            "document_not_ready_unsupported": explicit("UNSUPPORTED"),
            "missing_or_duplicate_file": duplicate_file,
            "source_identity_mismatch": change(("files", 0, "sha256"), "0" * 64),
            "source_doc_mismatch": change(("files", 0, "doc_id"), "other-source"),
            "missing_or_duplicate_pages": lambda row: row["pages"].pop(),
            "missing_page_content": change(("pages", 0, "status"), "missing"),
            "zero_chunks": change(("chunks",), []),
            "foreign_file_records": change(("chunks", 0, "file_id"), foreign),
            "foreign_document_records": change(("chunks", 0, "doc_id"), "other-source"),
        }
        expected = {"source_doc_mismatch": "source_identity_mismatch",
                    "document_not_ready_failed": "document_not_ready",
                    "document_not_ready_unsupported": "document_not_ready"}
        for label, mutate in cases.items():
            with self.subTest(label=label):
                changed = copy.deepcopy(built)
                mutate(changed)
                name = label.replace("_", "-")
                with patch("graph_builder.corpus.k1_export.build_document", return_value=changed):
                    error = self.blocked(name)
                report = self.check_report(error, name, "BLOCKED", expected.get(label, label),
                                           changed.get("status") if label.startswith("document_not_ready") else None)
                held = report["blocked_documents"][0]
                self.assertEqual(held["k1_chunks_held"], len(changed["chunks"]))
                self.assertEqual(held["corpus_chunks_held"], 3)
                self.assertEqual(held["pages_held"], 2)
                self.assertEqual(held["sha256"], doc["sha256"])
                self.assertEqual(report["ready_documents"], [])
                self.assertEqual(report["counts"]["k1_chunks_held_known"], len(changed["chunks"]))
                self.assertFalse((self.corpus.exports / name).exists())

    def test_ready_documents_are_listed_but_never_published_with_a_blocked_one(self):
        base.add_sample(self.corpus, self.root, "sample-first", self.fingerprint)
        base.add_sample(self.corpus, self.root, "sample-pending", self.fingerprint, process=False, width=700)
        before = tree(self.corpus.exports)
        error = self.blocked()
        report = self.check_report(error, "one", "NOT_PROCESSED", "processing_not_complete", "not processed")
        self.assertEqual([row["doc_id"] for row in report["required_documents"]], ["sample-first", "sample-pending"])
        self.assertEqual([row["doc_id"] for row in report["ready_documents"]], ["sample-first"])
        self.assertEqual(report["missing_document_ids"], ["sample-pending"])
        self.assertEqual(report["unexpected_document_ids"], [])
        self.assertEqual(report["counts"]["ready_documents"], 1)
        self.assertEqual(report["counts"]["blocked_documents"], 1)
        self.assertEqual(report["counts"]["published_documents"], 0)
        self.assert_nothing_published("one", before)

    def test_blocked_documents_do_not_depend_on_the_order_of_documents(self):
        base.add_sample(self.corpus, self.root, "sample-b", self.fingerprint)
        base.add_sample(self.corpus, self.root, "sample-a", self.fingerprint, process=False, width=700)
        report = self.blocked().report
        self.assertEqual([row["doc_id"] for row in report["required_documents"]], ["sample-a", "sample-b"])
        self.assertEqual(self.blocked("two").report["blocked_documents"], report["blocked_documents"])


class NoPartialOutputTests(Case):
    def test_failure_writes_only_the_report_and_no_package_files(self):
        base.add_sample(self.corpus, self.root, "sample-first", self.fingerprint)
        base.add_sample(self.corpus, self.root, "sample-pending", self.fingerprint, process=False, width=700)
        self.assertFalse(self.corpus.exports.exists())
        error = self.blocked()
        files = tree(self.corpus.exports)
        self.assertEqual(list(files), [f"{FAILURES}/{error.report_path.parent.name}/failure.json"])
        self.assertEqual(directories(self.corpus.exports), {FAILURES, f"{FAILURES}/{error.report_path.parent.name}"})
        names = {Path(path).name for path in files}
        self.assertTrue(names.isdisjoint({"manifest.json", "SHA256SUMS", POINTER} | {f"{group}.jsonl" for group in GROUPS}))

    def test_failure_after_the_gate_removes_its_staging_and_keeps_the_previous_release(self):
        base.add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        self.export("one")
        before = tree(self.corpus.exports)
        with patch("graph_builder.corpus.k1_export.validate_k1", return_value=["fixture problem"]):
            with self.assertRaises(PublicationError):
                self.export("one")
            with self.assertRaises(PublicationError):
                self.export("fresh")
        self.assertEqual(tree(self.corpus.exports), before)
        self.assertEqual([p.name for p in self.corpus.exports.iterdir()], ["one"])
        self.assertFalse((self.corpus.exports / "fresh").exists())

    def test_every_failure_leaves_a_new_report_and_changes_nothing_else(self):
        base.add_sample(self.corpus, self.root, "sample-report", self.fingerprint, process=False)
        first = self.blocked("one").report_path
        second = self.blocked("one").report_path
        self.assertNotEqual(first.parent, second.parent)
        self.assertEqual(sorted(tree(self.corpus.exports)),
                         sorted(f"{FAILURES}/{p.parent.name}/failure.json" for p in (first, second)))


class PublicationProtectionTests(Case):
    def test_failed_export_keeps_current_releases_and_other_exports_byte_for_byte(self):
        base.add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        base.add_sample(self.corpus, self.root, "sample-later", self.fingerprint, width=700)
        self.export("one", only=["sample-report"])  # release names hold the UTC second and the content digest
        self.export("one")
        self.export("other")
        pointer = self.corpus.exports / "one" / POINTER
        resolved = current_release(self.corpus.exports / "one")
        before = tree(self.corpus.exports)
        folders = directories(self.corpus.exports)
        base.add_sample(self.corpus, self.root, "sample-pending", self.fingerprint, process=False, width=800)
        for name in ("one", "other", "fresh"):
            self.blocked(name)
        self.assertEqual({path: digest for path, digest in tree(self.corpus.exports).items() if not path.startswith(FAILURES)},
                         before)
        self.assertEqual({d for d in directories(self.corpus.exports) if not d.startswith(FAILURES)}, folders)
        self.assertEqual(current_release(self.corpus.exports / "one"), resolved)
        self.assertEqual(json.loads(pointer.read_text(encoding="utf-8"))["release"], resolved.name)
        self.assertEqual(validate_k1(resolved), [])

    def test_failed_export_does_not_touch_a_frozen_looking_release_and_its_pointer(self):
        base.add_sample(self.corpus, self.root, "sample-report", self.fingerprint, process=False)
        frozen = self.corpus.exports / "frozen"
        release = frozen / "releases" / "20260101T000000Z-aaaaaaaaaaaa"
        release.mkdir(parents=True)
        (release / "manifest.json").write_text('{"format": "K1"}\n', encoding="utf-8", newline="\n")
        (release / "SHA256SUMS").write_text("0" * 64 + "  manifest.json\n", encoding="utf-8", newline="\n")
        (frozen / POINTER).write_text(json.dumps({"release": release.name, "previous": None}) + "\n", encoding="utf-8",
                                      newline="\n")
        before, folders = tree(frozen), directories(frozen)
        self.blocked("frozen")
        self.assertEqual(tree(frozen), before)
        self.assertEqual(directories(frozen), folders)
        self.assertEqual(current_release(frozen), release)
        self.assertEqual(sorted(p.name for p in self.corpus.exports.iterdir()), [FAILURES, "frozen"])

    def test_a_complete_export_after_a_failure_still_publishes_and_chains_to_the_previous_release(self):
        base.add_sample(self.corpus, self.root, "sample-first", self.fingerprint)
        base.add_sample(self.corpus, self.root, "sample-second", self.fingerprint, width=700)
        first = self.export("one", only=["sample-first"])
        base.add_sample(self.corpus, self.root, "sample-pending", self.fingerprint, process=False, width=800)
        self.blocked("one")
        self.assertEqual(current_release(self.corpus.exports / "one"), first)
        second = self.export("one", only=["sample-first", "sample-second"])
        pointer = json.loads((self.corpus.exports / "one" / POINTER).read_text(encoding="utf-8"))
        self.assertEqual((pointer["release"], pointer["previous"]), (second.name, first.name))
        self.assertTrue(first.is_dir())
        self.assertEqual(validate_k1(second), [])


class CommandLineTests(Case):
    """The real ``python -m graph_builder.corpus k1`` entry point, in a subprocess."""

    def run_k1(self, *extra: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", PYTHONIOENCODING="utf-8",
                   PYTHONPATH=os.pathsep.join(filter(None, [str(ROOT / "src"), os.environ.get("PYTHONPATH", "")])))
        return subprocess.run([sys.executable, "-c", DRIVER, "k1", str(self.corpus.root), "--models", "models",
                               "--k1-config", str(ROOT / "configs/corpus/k1.json"), *extra],
                              capture_output=True, text=True, encoding="utf-8", env=env, cwd=self.root, timeout=600)

    def test_exit_codes_messages_and_current_protection(self):
        base.add_sample(self.corpus, self.root, "sample-ready", self.fingerprint)
        done = self.run_k1("--name", "one")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertNotIn("Traceback", done.stderr)
        printed = json.loads(done.stdout[done.stdout.index("{"):done.stdout.rindex("}") + 1])
        self.assertEqual((printed["held_back"], printed["files"]), (0, 1))
        pointer = self.corpus.exports / "one" / POINTER
        previous, releases = pointer.read_bytes(), tree(self.corpus.exports / "one")
        self.assertEqual(validate_k1(current_release(self.corpus.exports / "one")), [])

        base.add_sample(self.corpus, self.root, "sample-pending", self.fingerprint, process=False, width=700)
        failed = self.run_k1("--name", "one")
        output = failed.stdout + failed.stderr
        self.assertEqual(failed.returncode, 1, output)
        self.assertIn("FAIL: K1 release BLOCKED: required_documents_incomplete; failure report: ", output)
        self.assertNotIn("Traceback", output)
        report = Path(re.search(r"failure report: (.+failure\.json)", output).group(1))
        self.assertEqual(report.parent.parent, self.corpus.exports / FAILURES)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["missing_document_ids"], ["sample-pending"])
        self.assertEqual(pointer.read_bytes(), previous)
        self.assertEqual(tree(self.corpus.exports / "one"), releases)

        unknown = self.run_k1("--name", "two", "--only", "sample-ready", "absent-source")
        self.assertEqual(unknown.returncode, 1, unknown.stdout + unknown.stderr)
        self.assertIn("K1 release BLOCKED", unknown.stdout + unknown.stderr)
        self.assertFalse((self.corpus.exports / "two").exists())

        self.assertEqual(self.run_k1().returncode, 1)  # --name is required
        scoped = self.run_k1("--name", "one", "--only", "sample-ready")
        self.assertEqual(scoped.returncode, 0, scoped.stdout + scoped.stderr)
        self.assertNotEqual(pointer.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
