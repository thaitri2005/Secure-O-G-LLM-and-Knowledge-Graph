"""A-416: QA false-positive reductions. Every change has a negative test (the false alarm disappears) and a positive test
(the real error is still flagged)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import unittest

from graph_builder.corpus.qa import crossrep as xr
from graph_builder.corpus.qa import fidelity as fid
from graph_builder.corpus.qa import ledger as qa_ledger
from graph_builder.corpus.qa.builtin_checks import check_char_ratio, register_builtin
from graph_builder.corpus.qa.markdown_syntax import normalise_cell, syntax_chars
from graph_builder.corpus.qa.signals import CheckContext, Registry

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "data" / "interim" / "overnight" / "b2" / "a416" / "test-tmp"  # git-ignored, inside the repository
FID_CONFIG = fid.load_config(ROOT / "configs/qa/source_fidelity.json")
LEDGER_CONFIG = qa_ledger.load_config(ROOT / "configs/qa/ledger.json")
XR_CONFIG = xr.load_config(ROOT / "configs/qa/cross_representation.json")
RULES = LEDGER_CONFIG["markdown_syntax"]
BODY = "Mud weight 9.2 ppg, viscosity 45 sec per quart, sandstone interval."
UNIQUE = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima")  # line differs by a word, not only by digits


class MarkdownSyntaxTests(unittest.TestCase):
    def test_table_syntax_is_counted_and_cell_text_is_not(self) -> None:
        table = "| Depth | Type |\n| --- | :---: |\n| 100 | A &#124; B |\n| 200 | <!-- image --> |"
        # header pipes 3 + separator row "|---|:---:|" 11 + row pipes 3 + entity surplus 5 + row pipes 3 + placeholder "<!--image-->" 12
        self.assertEqual(syntax_chars(table, RULES), 3 + 11 + 3 + 5 + 3 + 12)
        self.assertEqual(syntax_chars("| Depth | Type |\n| --- | --- |\n| 100 | A |", RULES), 3 + len("|---|---|") + 3)

    def test_running_text_with_a_pipe_is_not_syntax(self) -> None:
        self.assertEqual(syntax_chars("Footer text 9 | P a g e and a | b", RULES), 0)

    def test_escaped_pipe_inside_a_cell_is_content(self) -> None:
        self.assertEqual(syntax_chars("| a\\|b |", RULES), 2)

    def test_normalise_cell(self) -> None:
        self.assertEqual(normalise_cell("a &#124; b <!-- image -->", RULES), "a | b")
        self.assertEqual(normalise_cell("a   b", None), "a b")


class CharRatioTests(unittest.TestCase):
    def codes(self, pdf: int, extracted: int, syntax: int) -> list[str]:
        registry = register_builtin(Registry())
        context = CheckContext(registry, LEDGER_CONFIG, Path("."), {})
        ratio = lambda value: round(value / pdf, 4)  # noqa: E731
        entity = {"ids": {"file_id": "f", "page": 1}, "release_mode": "text", "pdf_text_chars": pdf, "extracted_characters": extracted,
                  "char_ratio": ratio(extracted), "markdown_syntax_chars": syntax, "char_ratio_content": ratio(max(extracted - syntax, 0)),
                  "page_exclusion": None}
        return [signal["code"] for signal in check_char_ratio(context, entity)]

    def test_markdown_overhead_alone_no_longer_raises_char_ratio_high(self) -> None:
        self.assertEqual(self.codes(1000, 1300, 0), ["CHAR_RATIO_HIGH"])  # before: the overhead looked like extra text
        self.assertEqual(self.codes(1000, 1300, 250), [])  # 1050 content characters

    def test_real_excess_text_is_still_flagged_and_reports_both_ratios(self) -> None:
        registry = register_builtin(Registry())
        context = CheckContext(registry, LEDGER_CONFIG, Path("."), {})
        entity = {"ids": {"file_id": "f", "page": 1}, "release_mode": "text", "pdf_text_chars": 1000, "extracted_characters": 1600,
                  "char_ratio": 1.6, "markdown_syntax_chars": 250, "char_ratio_content": 1.35, "page_exclusion": None}
        found = check_char_ratio(context, entity)
        self.assertEqual([s["code"] for s in found], ["CHAR_RATIO_HIGH"])
        self.assertEqual((found[0]["evidence"]["ratio"], found[0]["evidence"]["ratio_content"]), (1.6, 1.35))

    def test_low_ratio_is_judged_on_content_characters(self) -> None:
        self.assertEqual(self.codes(1000, 520, 0), [])
        self.assertEqual(self.codes(1000, 520, 100), ["CHAR_RATIO_LOW"])  # pipes were hiding a loss

    def test_page_without_syntax_is_unchanged(self) -> None:
        self.assertEqual(self.codes(1000, 400, 0), ["CHAR_RATIO_LOW"])
        self.assertEqual(self.codes(1000, 800, 0), [])
        self.assertEqual(self.codes(1000, 1200, 0), ["CHAR_RATIO_HIGH"])


class ReleaseSyntaxCountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = SCRATCH / self.id().rsplit(".", 1)[-1]
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_read_release_counts_syntax_per_page_through_source_spans(self) -> None:
        table = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        rows = {"files.jsonl": [], "pages.jsonl": [], "tables.jsonl": [], "parents.jsonl": [],
                "chunks.jsonl": [{"file_id": "f", "chunk_id": "c1", "page": 2, "parent_id": "p", "quality": "ok", "text": table,
                                  "source_spans": [{"page": 2, "start": 0, "end": len(table)}]},
                                 {"file_id": "f", "chunk_id": "c2", "page": 3, "parent_id": "p", "quality": "ok", "text": "plain | text"}]}
        for name, content in rows.items():
            (self.root / name).write_text("".join(json.dumps(row) + "\n" for row in content), encoding="utf-8")
        with_rules = qa_ledger.read_release(self.root, RULES)
        self.assertEqual(with_rules["page_syntax"][("f", 2)], 3 + len("|---|---|") + 3)
        self.assertEqual(with_rules["page_syntax"][("f", 3)], 0)
        self.assertEqual(sum(qa_ledger.read_release(self.root)["page_syntax"].values()), 0)  # off without rules


def md_table(rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows]
    return "\n".join([lines[0], "| " + " | ".join("---" for _ in rows[0]) + " |"] + lines[1:])


class CrossRepNormalisationTests(unittest.TestCase):
    GRID = [["Depth", "Note"], ["100", "a|b"], ["200", "c"]]

    def record(self) -> dict:
        return {"table_id": "f:t", "file_id": "f", "grid": copy.deepcopy(self.GRID), "header_rows": 1, "num_rows": 3, "num_cols": 2, "pages": [1]}

    def chunk(self, rows: list[list[str]]) -> dict:
        return {"chunk_id": "f:t:c0", "child_index": 0, "row_start": 1, "row_end": 3, "text": md_table(rows), "table_id": "f:t", "type": "table",
                "file_id": "f", "parent_id": "f:t", "page": 1, "pages": [1]}

    def found(self, rows: list[list[str]], grid: list[list[str]] | None = None) -> list[str]:
        record = self.record()
        if grid is not None:
            record["grid"] = grid
        return [code for code, _ in xr.analyse_table(record, [self.chunk(rows)], XR_CONFIG)]

    def test_html_entity_for_a_pipe_is_not_a_mismatch(self) -> None:
        self.assertEqual(self.found([["Depth", "Note"], ["100", "a&#124;b"], ["200", "c"]]), [])

    def test_image_placeholder_in_a_cell_is_not_a_mismatch(self) -> None:
        self.assertEqual(self.found([["Depth", "Note"], ["100", "a|b"], ["200", "c <!-- image -->"]]), [])
        self.assertEqual(self.found([["Depth", "Note"], ["100", "a|b"], ["200", "<!-- image -->"]], [["Depth", "Note"], ["100", "a|b"], ["200", ""]]), [])

    def test_changed_value_next_to_an_entity_or_placeholder_is_still_flagged(self) -> None:
        self.assertEqual(self.found([["Depth", "Note"], ["100", "a&#124;x"], ["200", "c"]]), ["XREP_TABLE_CHUNK_MISMATCH"])
        self.assertEqual(self.found([["Depth", "Note"], ["100", "a|b"], ["200", "d <!-- image -->"]]), ["XREP_TABLE_CHUNK_MISMATCH"])
        self.assertEqual(self.found([["Depth", "Note"], ["150", "a&#124;b"], ["200", "c"]]), ["XREP_TABLE_CHUNK_MISMATCH"])

    def test_missing_rules_keep_the_old_strict_behaviour(self) -> None:
        strict = {key: value for key, value in XR_CONFIG.items() if key != "markdown_syntax"}
        record = self.record()
        found = xr.analyse_table(record, [self.chunk([["Depth", "Note"], ["100", "a&#124;b"], ["200", "c"]])], strict)
        self.assertEqual([code for code, _ in found], ["XREP_TABLE_CHUNK_MISMATCH"])


class FurnitureKeyTests(unittest.TestCase):
    def test_digit_runs_share_one_key(self) -> None:
        self.assertEqual(fid.line_key("Page 8 of 74"), fid.line_key("Page 12 of 74"))
        self.assertEqual(fid.line_key("9 | P a g e"), fid.line_key("19 | P a g e"))

    def test_different_words_keep_different_keys(self) -> None:
        self.assertNotEqual(fid.line_key("Page 8 of 74"), fid.line_key("Section 8 of 74"))

    def test_furniture_keys_count_pages_with_digit_run_variants(self) -> None:
        pages = [[f"Page {n} of 74"] for n in (1, 2, 8, 9, 10, 11, 12, 13)] + [["Other"]]
        self.assertEqual(fid.furniture_keys(pages, 0.5, 3), {"page # of #"})  # 9 of 9 single and double digit pages share it


class PdfFurnitureTests(unittest.TestCase):
    """Synthetic PDFs (PyMuPDF, test-only): footer of a sub-report, rotated pages."""

    def setUp(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("PyMuPDF not available")
        self.root = SCRATCH / self.id().rsplit(".", 1)[-1]
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def reader(self, footer_pages: set[int], pages: int = 12, rotation: int = 0, header: bool = False, footer: str = "{} | P a g e") -> fid.PdfReference:
        import fitz
        document = fitz.open()
        for number in range(1, pages + 1):
            page = document.new_page()
            if header:
                page.insert_text((72, 150), "Daily drilling report header")  # repeated in the BODY area, not in a margin
            page.insert_text((72, 300), f"{BODY} {UNIQUE[number - 1]}.")
            if number in footer_pages:
                page.insert_text((72, 815), footer.format(number))
            if rotation:
                page.set_rotation(rotation)
        path = self.root / "doc.pdf"
        document.save(str(path))
        reader = fid.PdfReference(path, FID_CONFIG)
        self.addCleanup(reader.close)
        return reader

    def test_footer_on_part_of_the_pages_is_furniture(self) -> None:
        reader = self.reader(footer_pages={1, 2, 3, 4, 5}, footer="Draft copy {} confidential")  # 5 of 12 pages = 42%: below the document-wide 50%
        _, margin, repeated = reader.page_text(3)
        self.assertIn("Draft copy", margin)
        self.assertNotIn("sandstone", margin + repeated)

    def test_footer_on_too_few_pages_is_not_furniture(self) -> None:
        reader = self.reader(footer_pages={1, 2}, footer="Draft copy {} confidential")  # 2 pages < margin_min_pages; not a page counter
        _, margin, repeated = reader.page_text(1)
        self.assertEqual((margin, repeated), ("", ""))

    def test_missing_body_text_is_still_a_content_candidate_next_to_furniture(self) -> None:
        reader = self.reader(footer_pages={1, 2, 3, 4, 5})
        pdf_text, margin, repeated = reader.page_text(2)
        k1 = pdf_text.replace("sandstone interval", "").replace("2 | P a g e", "")
        raw = fid.compare_page(pdf_text, k1, margin, repeated, FID_CONFIG)
        self.assertEqual(raw["word"]["missing_content"], 2)  # "sandstone", "interval" are not explained by the footer
        self.assertEqual(raw["word"]["missing_furniture_margin"], 4)  # p a g e

    def test_rotated_page_margin_band_follows_the_text_not_the_rotated_page_size(self) -> None:
        reader = self.reader(footer_pages={1, 2, 3, 4, 5}, rotation=270, header=True)
        _, margin, repeated = reader.page_text(3)
        self.assertIn("P a g e", margin)
        self.assertIn("Daily drilling report header", repeated)  # body line, repeated on all pages: not a margin line
        self.assertNotIn("Daily drilling report header", margin)

    def single_page(self, lines: list[tuple[int, str]]) -> fid.PdfReference:
        import fitz
        document = fitz.open()
        page = document.new_page()
        for y, text in lines:
            page.insert_text((72, y), text)
        path = self.root / "one.pdf"
        document.save(str(path))
        reader = fid.PdfReference(path, FID_CONFIG)
        self.addCleanup(reader.close)
        return reader

    def test_page_counter_stamp_is_furniture_even_in_a_one_page_document(self) -> None:
        reader = self.single_page([(100, "Cement job report"), (300, "Top of cement 1200 ft"), (700, "Printed: 17:53 13-Sep-16 RIMBase 7.2.44.1 Page: 1 of 1")])
        _, margin, _ = reader.page_text(1)
        self.assertIn("Page: 1 of 1", margin)
        self.assertNotIn("1200", margin)

    def test_page_counter_in_the_middle_of_the_body_is_not_furniture(self) -> None:
        reader = self.single_page([(80, "Cement job report"), (100, "Daily summary"), (200, "Details are on Page 3 of 12 of the plan"), (300, "Top of cement 1200 ft"),
                                   (400, "Casing shoe 2100 ft"), (500, "Mud weight 9.2 ppg"), (600, "Hole size 12.25 in"), (700, "Prepared by the field crew")])
        self.assertNotIn("Page 3 of 12", reader.page_text(1)[1])

    def test_lost_value_next_to_a_stamp_is_still_flagged(self) -> None:
        pdf = "Cement job report\nTop of cement 1200 ft\nCasing shoe 2100 ft\nMud weight 9.2 ppg and more words follow here today\nPrinted: 17:53 13-Sep-16 Page: 1 of 1\n"
        k1 = pdf.replace("Casing shoe 2100 ft\n", "").replace("Printed: 17:53 13-Sep-16 Page: 1 of 1\n", "")
        raw = fid.compare_page(pdf, k1, "Printed: 17:53 13-Sep-16 Page: 1 of 1", "", FID_CONFIG)
        self.assertIn("2100", raw["numeric"]["_content_missing"])
        self.assertEqual(raw["numeric"]["missing_furniture_margin"], 6)  # 17, 53, 13, 16, 1, 1

    def test_bare_page_number_limit_is_configurable(self) -> None:
        wide = copy.deepcopy(FID_CONFIG)
        wide["furniture"]["page_number_max_digits"]["value"] = 1
        import fitz
        document = fitz.open()
        for number in range(1, 6):
            page = document.new_page()
            page.insert_text((72, 300), f"{BODY} {UNIQUE[number - 1]}.")
            if number == 2:
                page.insert_text((300, 815), "222")  # a bare number on one page only: not repeated, so it is judged as a page number by its length
        path = self.root / "numbers.pdf"
        document.save(str(path))
        for config, expected in ((FID_CONFIG, True), (wide, False)):
            reader = fid.PdfReference(path, config)
            self.addCleanup(reader.close)
            self.assertEqual("222" in reader.page_text(2)[1], expected)


class SampleRuleTests(unittest.TestCase):
    def units(self) -> list[dict]:
        units = [{"doc_id": f"d{index % 3}", "file_id": f"f{index % 3}", "page": index, "codes": ["FIDELITY_WORD_RECALL_LOW"]} for index in range(60)]
        units += [{"doc_id": "d1", "file_id": "f1", "page": 100 + index, "codes": ["CHAR_RATIO_HIGH"]} for index in range(20)]
        units += [{"doc_id": "d2", "file_id": "f2", "page": 200, "codes": ["FIDELITY_NUMERIC_NOVEL"]}]
        return units

    def test_sample_is_deterministic_bounded_and_covers_every_stratum(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("qa_flagged_sample", ROOT / "scripts/qa_flagged_sample.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        first, second = module.select_sample(self.units(), 30), module.select_sample(self.units(), 30)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 30)
        self.assertEqual({unit["stratum"] for unit in first}, {"FIDELITY_NUMERIC_NOVEL", "FIDELITY_WORD_RECALL_LOW", "CHAR_RATIO_HIGH"})
        self.assertEqual(len({(unit["file_id"], unit["page"]) for unit in first}), 30)  # no page twice
        self.assertEqual(len(module.select_sample(self.units()[:5], 30)), 5)  # fewer units than slots: all of them


if __name__ == "__main__":
    unittest.main()
