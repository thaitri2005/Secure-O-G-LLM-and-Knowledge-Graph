from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import unittest

from graph_builder.corpus.qa import fidelity as fid
from graph_builder.corpus.qa import ledger as qa_ledger
from graph_builder.corpus.qa.signals import Registry

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "data" / "interim" / "overnight" / "a402" / "test-tmp"  # git-ignored, inside the repository
REAL_RELEASE = ROOT / "data/interim/k1-run/corpus/exports/ops-rebuild-r3-e2/releases/20261108T174020Z-e34a87c780d8"
REAL_CORPUS = ROOT / "data/interim/k1-run/corpus"
CONFIG = fid.load_config(ROOT / "configs/qa/source_fidelity.json")
PAGE = ("Drilling report\nMeasured depth 1700 ft\nHole size 12.25 in\nCasing 9.625 at 220\n"
        "The crew circulated mud and tripped the bit out of the hole after a short delay in the morning shift.\n")


def codes(pdf: str, k1: str, margin: str = "", repeated: str = "", mode: str = "text", credit: str = "") -> set[str]:
    raw = fid.compare_page(pdf, k1, margin, repeated, CONFIG, credit)
    return {code for code, _ in fid.judge(raw, mode, not k1.strip(), CONFIG)}


class CompareTests(unittest.TestCase):
    def test_identical_text_has_no_warning(self) -> None:
        self.assertEqual(codes(PAGE, PAGE), set())

    def test_changed_digit_and_fabricated_number_are_flagged(self) -> None:
        self.assertIn("FIDELITY_NUMERIC_NOVEL", codes(PAGE, PAGE.replace("1700", "1701")))
        self.assertIn("FIDELITY_NUMERIC_NOVEL", codes(PAGE, PAGE + "The pressure reached 4817 psi.\n"))

    def test_deleted_numbers_lower_numeric_recall(self) -> None:
        self.assertIn("FIDELITY_NUMERIC_RECALL_LOW", codes(PAGE, PAGE.replace("Hole size 12.25 in\n", "")))

    def test_empty_k1_page_is_flagged(self) -> None:
        self.assertEqual(codes(PAGE, ""), {"FIDELITY_PAGE_EMPTY"})

    def test_furniture_explains_only_missing_tokens(self) -> None:
        pdf, footer = PAGE + "Printed 15:35 RIMBase Page 2\n", "Printed 15:35 RIMBase Page 2"
        k1 = PAGE
        self.assertIn("FIDELITY_NUMERIC_RECALL_LOW", codes(pdf, k1))  # numbers 15, 35, 2 missing without exclusion
        self.assertEqual(codes(pdf, k1, margin=footer), set())

    def test_section_title_credit_never_creates_a_novel_token(self) -> None:
        self.assertEqual(codes(PAGE, PAGE, credit="Report For 17-Aug-16"), set())
        self.assertIn("FIDELITY_NUMERIC_NOVEL", codes(PAGE, PAGE + "extra 99\n"))

    def test_documented_blind_spots_are_not_detected(self) -> None:
        lines = PAGE.splitlines()
        self.assertEqual(codes(PAGE, "\n".join(reversed(lines))), set())  # reordered text
        swapped = PAGE.replace("1700", "@@").replace("220", "1700").replace("@@", "220")
        self.assertEqual(codes(PAGE, swapped), set())  # swapped values

    def test_hybrid_checks_recall_only_and_withholds_grant(self) -> None:
        raw = fid.compare_page(PAGE, PAGE + "ocr text 9876\n", "", "", CONFIG)
        judged = dict(fid.judge(raw, "hybrid", False, CONFIG))
        self.assertIn("FIDELITY_PARTIAL_REFERENCE", judged)
        self.assertNotIn("FIDELITY_NUMERIC_NOVEL", judged)

    def test_tiny_page_is_insufficient_not_granted(self) -> None:
        judged = dict(fid.judge(fid.compare_page("Page one", "Page one", "", "", CONFIG), "text", False, CONFIG))
        self.assertTrue(judged["FIDELITY_INSUFFICIENT_TOKENS"]["grant_withheld"])

    def test_repeated_margin_lines_need_frequency(self) -> None:
        pages = [["Daily Report 1"], ["Daily Report 2"], ["Daily Report 3"], ["Other"]]
        self.assertEqual(fid.furniture_keys(pages, 0.5, 3), {"daily report #"})
        self.assertEqual(fid.furniture_keys(pages[:2], 0.5, 3), set())  # too few pages


class RegistryTests(unittest.TestCase):
    def test_grant_is_withheld_by_marked_signal_and_never_content_verified(self) -> None:
        registry = fid.register_fidelity(Registry())
        check = next(c for c in registry.checks if c.name == "source_fidelity")
        self.assertEqual(check.grants, "TEXT_LAYER_CONSISTENT")
        ids = {"file_id": "f", "page": 1}
        signal = registry.signal("FIDELITY_NOT_APPLICABLE", "page", ids, evidence={"grant_withheld": True})
        registry.checks[:] = [type(check)("x", lambda c, e: [signal], "page", "1", "TEXT_LAYER_CONSISTENT", ())]
        self.assertIsNone(registry.run("page", None, {}, ids)[2])
        registry.checks[:] = [type(check)("x", lambda c, e: [], "page", "1", "TEXT_LAYER_CONSISTENT", ())]
        self.assertEqual(registry.run("page", None, {}, ids)[2], "TEXT_LAYER_CONSISTENT")


class SyntheticPdfTests(unittest.TestCase):
    """Build a tiny PDF with PyMuPDF (test-only) and a matching release; check OCR, missing PDF and a real signal."""

    def setUp(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("PyMuPDF not available")
        self.root = SCRATCH / self.id().rsplit(".", 1)[-1]
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def release(self, k1_text: str, mode: str = "text", with_pdf: bool = True) -> Path:
        import fitz
        pdf_path = self.root / "doc.pdf"
        document = fitz.open()
        document.new_page().insert_text((72, 100), "x")
        page = document[0]
        for index, line in enumerate(PAGE.splitlines()):
            page.insert_text((72, 120 + 14 * index), line)
        document.save(str(pdf_path))
        sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        if not with_pdf:
            pdf_path.unlink()
        release = self.root / "rel"
        release.mkdir()
        row = {"file_id": "fA", "doc_id": "docA", "original_name": "doc.pdf", "sha256": sha, "page_count": 1}
        chunk = {"file_id": "fA", "chunk_id": "c", "page": 1, "pages": [1], "text": k1_text, "section_path": [],
                 "source_spans": [{"page": 1, "start": 0, "end": len(k1_text)}]}
        (release / "files.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        (release / "chunks.jsonl").write_text(json.dumps(chunk) + "\n", encoding="utf-8")
        return release

    def signals(self, release: Path, mode: str = "text") -> list[dict]:
        config = dict(CONFIG, pdf_search=[str(self.root / "{original_name}")])
        state = fid.FidelityState(release, None, config)
        self.addCleanup(state.close)
        registry = fid.register_fidelity(Registry())
        ids = {"file_id": "fA", "page": 1, "page_id": "fA:p1"}
        return fid.evaluate_page(state, registry, ids, {"release_mode": mode})

    def test_consistent_page_has_no_signal(self) -> None:
        self.assertEqual(self.signals(self.release("x\n" + PAGE)), [])

    def test_changed_digit_is_flagged(self) -> None:
        found = self.signals(self.release("x\n" + PAGE.replace("1700", "1707")))
        self.assertIn("FIDELITY_NUMERIC_NOVEL", [s["code"] for s in found])
        self.assertTrue(all(s["severity"] != "ERROR" for s in found))

    def test_ocr_page_not_applicable(self) -> None:
        found = self.signals(self.release(PAGE), mode="ocr")
        self.assertEqual([s["code"] for s in found], ["FIDELITY_NOT_APPLICABLE"])

    def test_missing_pdf_gives_no_reference(self) -> None:
        found = self.signals(self.release(PAGE, with_pdf=False))
        self.assertEqual([s["code"] for s in found], ["FIDELITY_NO_REFERENCE"])


@unittest.skipUnless(REAL_RELEASE.is_dir() and REAL_CORPUS.is_dir(), "real release not available")
class RealReleaseTests(unittest.TestCase):
    def test_ledger_with_fidelity_is_deterministic_and_has_no_content_verified_level(self) -> None:
        digests = []
        for name in ("a", "b"):
            out = SCRATCH / f"real-{name}"
            shutil.rmtree(out, ignore_errors=True)
            registry = fid.register_fidelity(qa_ledger.default_registry(), corpus_dir=REAL_CORPUS)
            try:
                qa_ledger.build_qa(REAL_RELEASE, out, corpus_dir=REAL_CORPUS, registry=registry)
            finally:
                fid.close_fidelity(registry)
            digests.append(hashlib.sha256((out / "qa-ledger.json").read_bytes()).hexdigest())
            summary = json.loads((out / "qa-summary.json").read_text(encoding="utf-8"))
            self.assertNotIn("CROSS_REPRESENTATION_CONSISTENT", summary["verification_levels"]["page"])
            self.assertEqual(summary["verification_levels"]["document"], {"STRUCTURAL_ONLY": 5})
            shutil.rmtree(out, ignore_errors=True)
        self.assertEqual(digests[0], digests[1])


if __name__ == "__main__":
    unittest.main()
