from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import unittest
from unittest import mock

from graph_builder.corpus.qa import ledger as qa_ledger
from graph_builder.corpus.qa.signals import GRANTABLE, Registry
from graph_builder.corpus.qa.builtin_checks import register_builtin

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "data" / "interim" / "overnight" / "a401" / "test-tmp"  # git-ignored, inside the repository
REAL_RELEASE = ROOT / "data/interim/k1-run/corpus/exports/ops-rebuild-r3-e2/releases/20261108T174020Z-e34a87c780d8"
REAL_CORPUS = ROOT / "data/interim/k1-run/corpus"
FORBIDDEN = ("content verified", "validated correct", "verified OK")
PASS = {"status": "pass", "error_count": 0, "errors": [], "page_rebuild_matches": 1, "page_rebuild_total": 1}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")


def page_row(page: int, status: str = "ok", mode: str = "text") -> dict:
    return {"file_id": "fA", "page": page, "page_id": f"fA:p{page}", "conversion_mode": mode, "mode": mode, "status": status,
            "ocr": None, "parser": {"backend": "docling"}}


def work_page(page: int, pdf: int, extracted: int, score: float = 0.9) -> dict:
    return {"page": page, "text_chars": pdf, "extracted_characters": extracted, "reasons": ["text_layer_ok"],
            "confidence": {"mean_score": score}}


def make_corpus(root: Path, segments: list[dict] | None = None) -> tuple[Path, Path, Path]:
    """Synthetic release (one daily_report file, 4 pages, 3 tables) plus work folder and A-107 sidecar."""
    release = root / "exports" / "exp1" / "releases" / "rel1"
    release.mkdir(parents=True)
    (release / "manifest.json").write_text(json.dumps({"identity": "idty", "corpus_fingerprint": "fp1", "schema_version": 1}), encoding="utf-8")
    (release / "SHA256SUMS").write_text("00  manifest.json\n", encoding="utf-8")
    write_jsonl(release / "files.jsonl", [{"file_id": "fA", "doc_id": "docA", "document_type": "daily_report", "page_count": 4,
                                           "sha256": "ab"}])
    write_jsonl(release / "pages.jsonl", [page_row(1), page_row(2), page_row(3, status="review"), page_row(4)])
    parts = lambda ref: [{"source_ref": ref, "page": 1}]  # noqa: E731
    write_jsonl(release / "tables.jsonl", [
        {"file_id": "fA", "table_id": "fA:t1", "pages": [1], "parts": parts("#/tables/0"), "num_rows": 2, "num_cols": 2},
        {"file_id": "fA", "table_id": "fA:t2", "pages": [2], "parts": parts("textlayer:operations_summary:p2:1"), "num_rows": 3, "num_cols": 2},
        {"file_id": "fA", "table_id": "fA:t3", "pages": [4], "parts": [], "num_rows": 1, "num_cols": 1}])
    write_jsonl(release / "parents.jsonl", [{"parent_id": "fA:s1", "type": "section"}, {"parent_id": "fA:t1", "type": "table"}])
    write_jsonl(release / "chunks.jsonl", [
        {"file_id": "fA", "chunk_id": "c1", "page": 1, "parent_id": "fA:s1", "quality": "ok"},
        {"file_id": "fA", "chunk_id": "c2", "page": 2, "parent_id": "fA:t1", "quality": "review"}])
    work = root / "work" / "docA" / "fp1"
    work.mkdir(parents=True)
    document = {"pages": [work_page(1, 1000, 900), work_page(2, 1000, 300), work_page(3, 1000, 950, score=0.2), work_page(4, 1000, 0)],
                "processing": {"segments": segments if segments is not None else [{"mode": "text", "pages": [1, 4], "status": "success", "errors": []}]},
                "statistics": {"dropped": {"page_footer": 4}}, "review_pages": [3], "missing_pages": []}
    (work / "document.json").write_text(json.dumps(document), encoding="utf-8")
    sidecar = root / "exports" / "exp1" / "table_repairs.json"
    sidecar.write_text(json.dumps([
        {"table_id": "fA:t2", "state": "SUPPORTED_AND_VALIDATED", "reason": None, "completeness": "partial_in_source", "evidence": {"margins": {"x": 0.5}}},
        {"table_id": "fA:t3", "state": "PARSING_FAILURE", "reason": "NO_HEADER", "completeness": None},
        {"table_id": "fA:gone", "state": "SUPPORTED_AND_VALIDATED", "reason": None, "completeness": None}]), encoding="utf-8")
    return release, root, sidecar


def codes(entity: dict) -> set[str]:
    return {s["code"] for s in entity["signals"]}


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.root = SCRATCH / self.id().rsplit(".", 1)[-1]
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def build(self, corpus: bool = True, registry: Registry | None = None, validator: dict = PASS, **make_args) -> tuple[dict, dict, Path]:
        release, corpus_dir, _ = make_corpus(self.root / "in", **make_args)
        out = self.root / "out"
        with mock.patch.object(qa_ledger, "run_validator", return_value=validator):
            qa_ledger.build_qa(release, out, corpus_dir=corpus_dir if corpus else None, registry=registry)
        ledger = json.loads((out / "qa-ledger.json").read_text(encoding="utf-8"))
        summary = json.loads((out / "qa-summary.json").read_text(encoding="utf-8"))
        return ledger, summary, out

    def test_signals_from_synthetic_corpus(self) -> None:
        ledger, summary, _ = self.build()
        document = ledger["documents"][0]
        pages = {page["page"]: page for page in document["pages"]}
        tables = {table["table_id"]: table for table in document["tables"]}
        self.assertEqual(codes(pages[1]), set())
        self.assertIn("CHAR_RATIO_LOW", codes(pages[2]))
        self.assertEqual({"PAGE_STATUS_REVIEW", "CONFIDENCE_LOW"}, codes(pages[3]))
        self.assertIn("PAGE_EMPTY_EXTRACTION", codes(pages[4]))
        self.assertEqual("docling", tables["fA:t1"]["origin"])
        self.assertEqual("textlayer_rebuild", tables["fA:t2"]["origin"])
        self.assertEqual("PARTIAL_IN_SOURCE", tables["fA:t2"]["completeness"])
        self.assertIn("A107_PARTIAL_IN_SOURCE", codes(tables["fA:t2"]))
        self.assertEqual({"TABLE_ORIGIN_UNKNOWN", "A107_STATE_NOT_VALIDATED"}, codes(tables["fA:t3"]))
        self.assertEqual({"A107_RECORD_UNMATCHED"}, {s["code"] for s in ledger["release_signals"]})
        self.assertEqual({"DROPPED_ITEMS_RECORDED", "CHUNK_QUALITY_NOT_OK"}, codes(document))
        self.assertEqual(2, document["chunks"]["count"])
        self.assertEqual("daily_report", next(iter(summary["by_family"].keys() - {"(release)"})))
        self.assertGreaterEqual(summary["by_reason_code"]["CHAR_RATIO_LOW"]["count"], 1)

    def test_levels_and_honesty_fields(self) -> None:
        ledger, summary, out = self.build()
        allowed = set(ledger["verification_levels_allowed"])
        text = (out / "qa-ledger.json").read_text(encoding="utf-8") + (out / "qa-summary.json").read_text(encoding="utf-8")
        for item in ledger["documents"][0]["pages"] + ledger["documents"][0]["tables"] + ledger["documents"]:
            self.assertIn(item["verification_level"], allowed)
            self.assertEqual("STRUCTURAL_ONLY", item["verification_level"])  # no check grants more; WARN does not change it
        for container in (ledger, summary):
            self.assertEqual("UNKNOWN", container["completeness"])
            self.assertTrue(container["limitations"])
            self.assertIn("swapped cells or rows inside a table", container["known_blind_spots"])
        self.assertNotIn("COMPLETE", [ledger["completeness"]])
        for phrase in FORBIDDEN:
            self.assertNotIn(phrase.lower(), text.lower())
        self.assertEqual({"UNKNOWN", "PARTIAL_IN_SOURCE"}, set(ledger["completeness_values_allowed"]))

    def test_failed_validator_makes_everything_unverified(self) -> None:
        failing = {"status": "fail", "error_count": 1, "errors": ["x"], "page_rebuild_matches": 0, "page_rebuild_total": 1}
        ledger, _, _ = self.build(validator=failing)
        self.assertEqual("UNVERIFIED", ledger["verification_level"])
        self.assertEqual({"K1_VALIDATOR_FAIL"}, {s["code"] for s in ledger["release_signals"]} - {"A107_RECORD_UNMATCHED"})
        self.assertTrue(all(p["verification_level"] == "UNVERIFIED" for p in ledger["documents"][0]["pages"]))
        self.assertEqual("UNVERIFIED", ledger["documents"][0]["verification_level"])

    def test_degraded_without_work_folder(self) -> None:
        ledger, _, _ = self.build(corpus=False)
        document = ledger["documents"][0]
        self.assertIn("WORK_FOLDER_MISSING", codes(document))
        self.assertTrue(all("CONFIDENCE_MISSING" in codes(page) for page in document["pages"]))
        self.assertTrue(ledger["link"]["corpus_work_folder"].startswith("not available"))

    def test_segment_failure_is_error_and_unverified(self) -> None:
        segments = [{"mode": "text", "pages": [1, 4], "status": "failed", "errors": ["boom"]}]
        ledger, summary, _ = self.build(segments=segments)
        document = ledger["documents"][0]
        self.assertTrue({"SEGMENT_FAILED", "SEGMENT_ERRORS"} <= codes(document))
        self.assertEqual("UNVERIFIED", document["verification_level"])
        self.assertEqual("ERROR", summary["by_reason_code"]["SEGMENT_FAILED"]["severity"])

    def test_deterministic_bytes(self) -> None:
        _, _, out = self.build()
        first = {name: (out / name).read_bytes() for name in ("qa-ledger.json", "qa-summary.json")}
        release, corpus_dir, _ = make_corpus(self.root / "in2")
        out2 = self.root / "out2"
        with mock.patch.object(qa_ledger, "run_validator", return_value=PASS):
            qa_ledger.build_qa(release, out2, corpus_dir=corpus_dir)
        for name, content in first.items():
            self.assertEqual(content, (out2 / name).read_bytes())

    def test_release_is_not_modified(self) -> None:
        release, corpus_dir, _ = make_corpus(self.root / "in")
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in release.iterdir()}
        with mock.patch.object(qa_ledger, "run_validator", return_value=PASS):
            qa_ledger.build_qa(release, self.root / "out", corpus_dir=corpus_dir)
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in release.iterdir()})

    def test_check_exception_is_isolated(self) -> None:
        registry = register_builtin(Registry())

        def broken(context, entity):
            raise RuntimeError("boom")

        registry.register_check("broken", broken, "table", "9")
        ledger, _, _ = self.build(registry=registry)
        tables = ledger["documents"][0]["tables"]
        self.assertTrue(all("QA_ERROR" in codes(table) for table in tables))
        self.assertTrue(all(table["verification_level"] == "UNVERIFIED" for table in tables))
        self.assertEqual("UNVERIFIED", ledger["documents"][0]["verification_level"])
        self.assertEqual(4, len(ledger["documents"][0]["pages"]))  # processing continued

    def test_plugin_registration_and_grants(self) -> None:
        registry = register_builtin(Registry())
        with self.assertRaises(ValueError):
            registry.register_check("bad", lambda c, e: [], "page", "1", grants="CONTENT_VERIFIED")
        with self.assertRaises(ValueError):
            registry.register_check("bad", lambda c, e: [], "nowhere", "1")
        registry.register_reason("X_WARN", "WARN", "test", "plugin")
        with self.assertRaises(ValueError):
            registry.register_reason("X_WARN", "WARN", "dup", "plugin")

        def plugin(context, entity):
            if entity["page"] == 2:
                return [registry.signal("X_WARN", "page", {"page": 2})]
            return []

        registry.register_check("plugin", plugin, "page", "1", grants="TEXT_LAYER_CONSISTENT")
        ledger, _, _ = self.build(registry=registry)
        levels = {p["page"]: p["verification_level"] for p in ledger["documents"][0]["pages"]}
        self.assertEqual("TEXT_LAYER_CONSISTENT", levels[1])
        self.assertEqual("STRUCTURAL_ONLY", levels[2])  # the check emitted a WARN: no grant
        self.assertEqual("STRUCTURAL_ONLY", ledger["documents"][0]["verification_level"])  # document never exceeds its weakest child
        self.assertEqual(set(GRANTABLE), {"TEXT_LAYER_CONSISTENT", "CROSS_REPRESENTATION_CONSISTENT", "NOT_APPLICABLE"})


@unittest.skipUnless((REAL_RELEASE / "manifest.json").is_file() and (REAL_CORPUS / "work").is_dir(), "real K1 release / corpus work folder not available")
class RealReleaseTests(unittest.TestCase):
    def test_real_release_ledger(self) -> None:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        out = SCRATCH / "real"
        shutil.rmtree(out, ignore_errors=True)
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        sums_before = (REAL_RELEASE / "SHA256SUMS").read_bytes()
        qa_ledger.build_qa(REAL_RELEASE, out, corpus_dir=REAL_CORPUS)
        self.assertEqual(sums_before, (REAL_RELEASE / "SHA256SUMS").read_bytes())
        summary = json.loads((out / "qa-summary.json").read_text(encoding="utf-8"))
        self.assertEqual({"chunks": 1042, "documents": 5, "pages": 174, "tables": 195}, summary["totals"])
        self.assertEqual("pass", summary["k1_validator"]["status"])
        self.assertEqual({"STRUCTURAL_ONLY"}, set(summary["verification_levels"]["page"]))
        self.assertEqual(81, summary["by_state"]["table_origin"]["textlayer_rebuild"])
        self.assertEqual("UNKNOWN", summary["completeness"])


if __name__ == "__main__":
    unittest.main()
