from __future__ import annotations

import gzip
import json
from pathlib import Path
import shutil
import unittest
from unittest import mock

from graph_builder.corpus.qa import ledger as qa_ledger
from graph_builder.corpus.qa import fidelity
from graph_builder.corpus.qa.exclusions import explain_page, load_page_exclusions, page_exclusions
from tests.test_qa_ledger import PASS, SCRATCH, codes, make_corpus

RULES = json.loads((Path(__file__).resolve().parents[1] / "configs/qa/ledger.json").read_text(encoding="utf-8"))["exclusion_rules"]


def prov(page: int) -> list[dict]:
    return [{"page_no": page}]


def toc_table(ref: str, page: int, rows: int = 20) -> dict:
    cells = [{"text": f"Section {i} " + "." * 40}  for i in range(rows)] + [{"text": str(i)} for i in range(rows)]
    return {"self_ref": ref, "label": "document_index", "prov": prov(page), "children": [], "data": {"table_cells": cells}}


def text(ref: str, page: int, content: str, label: str = "text") -> dict:
    return {"self_ref": ref, "label": label, "prov": prov(page), "text": content, "children": []}


class PageExclusionTests(unittest.TestCase):
    def test_toc_page_is_attributed_with_its_heading(self) -> None:
        doc = {"texts": [text("#/texts/0", 3, "Table of Contents", "section_header")], "tables": [toc_table("#/tables/0", 3)]}
        found = page_exclusions(doc, RULES)
        self.assertEqual({3}, set(found))
        self.assertEqual({"document_index", "document_index_heading"}, set(found[3]))

    def test_heading_contents_on_prose_page_is_not_an_exclusion(self) -> None:
        prose = "The core was logged in detail and the lithology is described below. " * 5
        doc = {"texts": [text("#/texts/0", 5, "Contents", "section_header"), text("#/texts/1", 5, prose)], "tables": []}
        self.assertEqual({}, page_exclusions(doc, RULES))

    def test_prose_page_without_leaders_is_not_an_exclusion(self) -> None:
        doc = {"texts": [text("#/texts/0", 7, "Drilling proceeded to 1300 ft. The bit was changed.")], "tables": []}
        self.assertEqual({}, page_exclusions(doc, RULES))

    def test_prose_ending_with_ellipsis_covers_too_little_to_explain_a_page(self) -> None:
        prose = "The core was logged in detail and the lithology is described in the sections that follow. " * 12
        doc = {"texts": [text("#/texts/0", 7, "And then the bit was changed..."), text("#/texts/1", 7, prose)], "tables": []}
        pdf_chars = len("".join((prose + "And then the bit was changed...").split()))
        self.assertFalse(explain_page(page_exclusions(doc, RULES)[7], pdf_chars, RULES)["explained"])

    def test_dotted_leader_text_without_index_label_is_found(self) -> None:
        doc = {"texts": [text("#/texts/0", 2, "Introduction ........................ 5")], "tables": []}
        self.assertIn("dotted_leader_toc", page_exclusions(doc, RULES)[2])

    def test_partial_coverage_is_not_explained(self) -> None:
        excluded = {"document_index": 300}
        self.assertFalse(explain_page(excluded, 3000, RULES)["explained"])
        self.assertTrue(explain_page({"document_index": 2900}, 3000, RULES)["explained"])
        self.assertIsNone(explain_page({}, 3000, RULES))
        self.assertFalse(explain_page(excluded, None, RULES)["explained"])

    def test_unreadable_docling_file_gives_no_exclusion(self) -> None:
        folder = SCRATCH / "excl-unreadable"
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        (folder / "docling.json.gz").write_bytes(b"not gzip")
        found, error = load_page_exclusions(folder, RULES)
        self.assertEqual({}, found)
        self.assertIsNotNone(error)
        self.assertEqual(({}, "docling.json.gz not found in the work folder"), load_page_exclusions(None, RULES))


class LedgerExclusionTests(unittest.TestCase):
    """Page 4 of the synthetic corpus has 1000 PDF characters and 0 extracted ones (PAGE_EMPTY_EXTRACTION)."""

    def setUp(self) -> None:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.root = SCRATCH / self.id().rsplit(".", 1)[-1]
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def page4(self, docling: dict | None) -> dict:
        self.calls = getattr(self, "calls", 0) + 1
        release, corpus_dir, _ = make_corpus(self.root / f"in{self.calls}")
        if docling is not None:
            with gzip.open(corpus_dir / "work" / "docA" / "fp1" / "docling.json.gz", "wt", encoding="utf-8") as stream:
                json.dump(docling, stream)
        with mock.patch.object(qa_ledger, "run_validator", return_value=PASS):
            qa_ledger.build_qa(release, self.root / f"out{self.calls}", corpus_dir=corpus_dir)
        ledger = json.loads((self.root / f"out{self.calls}" / "qa-ledger.json").read_text(encoding="utf-8"))
        return {page["page"]: page for page in ledger["documents"][0]["pages"]}[4]

    def test_recorded_toc_exclusion_is_info_not_warn(self) -> None:
        page = self.page4({"tables": [toc_table("#/tables/0", 4, rows=30)], "texts": []})
        self.assertEqual({"PAGE_EMPTY_EXPLAINED_BY_EXCLUSION"}, codes(page))
        signal = page["signals"][0]
        self.assertEqual("INFO", signal["severity"])
        self.assertGreaterEqual(signal["evidence"]["exclusion"]["fraction"], 0.8)
        self.assertEqual("STRUCTURAL_ONLY", page["verification_level"])

    def test_same_page_without_exclusion_record_still_warns(self) -> None:
        self.assertEqual({"PAGE_EMPTY_EXTRACTION"}, codes(self.page4(None)))
        self.assertEqual({"PAGE_EMPTY_EXTRACTION"}, codes(self.page4({"tables": [], "texts": []})))

    def test_small_exclusion_on_empty_page_still_warns(self) -> None:
        page = self.page4({"tables": [toc_table("#/tables/0", 4, rows=2)], "texts": []})
        self.assertEqual({"PAGE_EMPTY_EXTRACTION"}, codes(page))
        self.assertIn("exclusion_partial", page["signals"][0]["evidence"])

    def test_exclusion_on_another_page_does_not_explain(self) -> None:
        self.assertEqual({"PAGE_EMPTY_EXTRACTION"}, codes(self.page4({"tables": [toc_table("#/tables/0", 2, rows=30)], "texts": []})))


class FidelityExclusionTests(unittest.TestCase):
    CONFIG = fidelity.load_config()

    def raw(self) -> dict:
        return fidelity.compare_page("Executive Summary Introduction Permitting Drilling Summary Mobilization Conductor", "", "", "", self.CONFIG)

    def test_explained_empty_page_is_info_without_grant(self) -> None:
        explained = {"explained": True, "excluded_chars": 90, "pdf_text_chars": 100, "fraction": 0.9, "reasons": {"document_index": 90}}
        result = fidelity.judge(self.raw(), "text", True, self.CONFIG, explained)
        self.assertEqual(["FIDELITY_PAGE_EMPTY_EXPLAINED"], [code for code, _ in result])
        self.assertTrue(result[0][1]["grant_withheld"])

    def test_empty_page_without_or_with_partial_exclusion_warns(self) -> None:
        for exclusion in (None, {"explained": False, "excluded_chars": 5, "pdf_text_chars": 100, "fraction": 0.05, "reasons": {}}):
            self.assertEqual(["FIDELITY_PAGE_EMPTY"], [code for code, _ in fidelity.judge(self.raw(), "text", True, self.CONFIG, exclusion)])


if __name__ == "__main__":
    unittest.main()
