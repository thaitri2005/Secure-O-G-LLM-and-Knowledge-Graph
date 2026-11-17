"""A-432: QA generalisation. Two classes of fidelity false alarms are explained (and recorded) instead of warned about:
(1) a header/footer block of a sub-report that stands at the page edge outside the margin band, (2) list/outline numbers
(a numbered series) that the converter dropped while it kept the item text. Every change has a negative test (the false
alarm is gone), a positive test (a real error next to it is still flagged), and a test that an old config behaves as before."""
from __future__ import annotations

import copy
from pathlib import Path
import shutil
import unittest

from graph_builder.corpus.qa import fidelity as fid

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "data" / "interim" / "overnight" / "b3" / "a432" / "test-tmp"  # git-ignored, inside the repository
CONFIG = fid.load_config(ROOT / "configs/qa/source_fidelity.json")
OLD_CONFIG = copy.deepcopy(CONFIG)  # the A-416 behaviour: no block_* and no enumerators keys
for _key in ("block_edge_lines", "block_min_pages", "block_frequency"):
    OLD_CONFIG["furniture"].pop(_key)
OLD_CONFIG.pop("enumerators")
WORDS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima")
OUTLINE = "16.3 Casing design\n16.4 Cement program\n16.5 Mud program\n"


def judged(pdf: str, k1: str, config: dict, margin: str = "", repeated: str = "") -> tuple[dict, list[tuple[str, dict]]]:
    raw = fid.compare_page(pdf, k1, margin, repeated, config, "", fid.enumerator_items(pdf, config))
    return raw, fid.judge(raw, "text", False, config)


def warn_codes(result: list[tuple[str, dict]]) -> set[str]:
    return {code for code, _ in result if code in {"FIDELITY_NUMERIC_RECALL_LOW", "FIDELITY_NUMERIC_NOVEL", "FIDELITY_WORD_RECALL_LOW"}}


class EnumeratorTests(unittest.TestCase):
    PDF = OUTLINE + "Top of cement 1200 ft and the shoe at 2100 ft are planned for the surface casing string today\n"

    def test_outline_numbers_with_kept_text_are_reported_under_their_own_code(self) -> None:
        # A-445: the code is separate from the numeric recall (so the lost markers are named), but its severity is WARN (see test_qa_marker_severity_and_label_value_filters)
        k1 = "Casing design\nCement program\nMud program\nTop of cement 1200 ft and the shoe at 2100 ft are planned for the surface casing string today\n"
        raw, result = judged(self.PDF, k1, CONFIG)
        self.assertEqual(raw["numeric"]["missing_enumerator_marker"], 3)
        self.assertEqual(warn_codes(result), set())
        info = dict(result)["FIDELITY_ENUMERATOR_MARKERS_NOT_KEPT"]
        self.assertTrue(info["grant_withheld"])  # the page does not become TEXT_LAYER_CONSISTENT
        self.assertEqual(info["missing_enumerator_marker"]["numeric"], ["16.3", "16.4", "16.5"])

    def test_old_config_without_the_section_warns_as_before(self) -> None:
        k1 = "Casing design\nCement program\nMud program\nTop of cement 1200 ft and the shoe at 2100 ft are planned for the surface casing string today\n"
        raw, result = judged(self.PDF, k1, OLD_CONFIG)
        self.assertEqual(fid.enumerator_items(self.PDF, OLD_CONFIG), [])
        self.assertEqual(raw["numeric"]["missing_enumerator_marker"], 0)
        self.assertEqual(warn_codes(result), {"FIDELITY_NUMERIC_RECALL_LOW"})

    def test_a_lost_real_number_next_to_the_markers_is_still_flagged(self) -> None:
        k1 = "Casing design\nCement program\nMud program\nTop of cement ft and the shoe at ft are planned for the surface casing string today\n"
        raw, result = judged(self.PDF, k1, CONFIG)
        self.assertEqual(set(raw["numeric"]["_content_missing"]), {"1200", "2100"})
        self.assertEqual(warn_codes(result), {"FIDELITY_NUMERIC_RECALL_LOW"})

    def test_markers_whose_item_text_is_also_missing_are_not_explained(self) -> None:
        k1 = "Mud program\nTop of cement 1200 ft and the shoe at 2100 ft are planned for the surface casing string today\n"
        raw, result = judged(self.PDF, k1, CONFIG)
        self.assertEqual(raw["numeric"]["missing_enumerator_marker"], 1)  # only 16.5, whose words survived
        self.assertEqual(set(raw["numeric"]["_content_missing"]), {"16.3", "16.4"})
        self.assertIn("FIDELITY_NUMERIC_RECALL_LOW", warn_codes(result))

    def test_a_single_leading_measurement_is_never_a_marker(self) -> None:
        pdf = "8.5 in hole section drilled to the planned depth without any problem reported by the crew\n"
        self.assertEqual(fid.enumerator_items(pdf, CONFIG), [])
        raw, result = judged(pdf, "in hole section drilled to the planned depth without any problem reported by the crew\n", CONFIG)
        self.assertEqual(set(raw["numeric"]["_content_missing"]), {"8.5"})
        self.assertEqual(warn_codes(result), {"FIDELITY_NUMERIC_RECALL_LOW"})

    def test_measurements_with_three_decimals_or_without_a_following_word_are_not_markers(self) -> None:
        pdf = "9.625 casing weight\n9.700 liner weight\n1200 2100 3400\n12 18 30\n"
        self.assertEqual(fid.enumerator_items(pdf, CONFIG), [])

    def test_flat_list_numbers_need_a_closing_dot_or_parenthesis_and_a_sibling(self) -> None:
        pdf = "1. Daily Drilling Reports\n2) Final Mud Log\n3 Casing Run Reports\n"
        self.assertEqual(fid.enumerator_items(pdf, CONFIG), [("1", ["daily", "drilling"]), ("2", ["final", "mud"])])  # '3 Casing' has no closing mark

    def test_two_markers_of_the_same_value_explain_only_what_is_missing(self) -> None:
        pdf = "1. Alpha item\n2. Bravo item\nThe tool 2 was run twice\n"
        k1 = "Alpha item\nBravo item\nThe tool 2 was run twice\n"
        raw, _ = judged(pdf, k1, CONFIG)
        self.assertEqual(raw["numeric"]["missing_raw"], 2)  # '1' and one '2' (the PDF has the digit 2 twice, K1 once)
        self.assertEqual(raw["numeric"]["missing_enumerator_marker"], 2)
        self.assertEqual(sum(raw["numeric"]["_content_missing"].values()), 0)
        lost_body = judged(pdf, "Alpha item\nThe tool 2 was run twice\n", CONFIG)[0]  # 'Bravo item' lost with its marker: nothing may explain the lost '2' of that item
        self.assertEqual(lost_body["numeric"]["missing_enumerator_marker"], 1)
        self.assertEqual(dict(lost_body["numeric"]["_content_missing"]), {"2": 1})

    def test_item_words_must_stand_together_not_just_occur_somewhere(self) -> None:
        pdf = "16.4 Cement program\n16.5 Mud program\nTop of cement is planned and the mud is heavy\n"
        k1 = "Mud program\nTop of cement is planned and the mud is heavy program\n"  # 'cement' and 'program' both occur, but not as the item 'cement program'
        raw, _ = judged(pdf, k1, CONFIG)
        self.assertEqual(raw["numeric"]["missing_enumerator_marker"], 1)
        self.assertEqual(dict(raw["numeric"]["_content_missing"]), {"16.4": 1})

    def test_result_is_deterministic(self) -> None:
        k1 = "Casing design\nCement program\nMud program\n"
        first = judged(self.PDF, k1, CONFIG)[1]
        self.assertEqual(first, judged(self.PDF, k1, CONFIG)[1])


class BlockFurnitureTests(unittest.TestCase):
    """Synthetic PDFs (PyMuPDF, test-only): the title block of a sub-report stands in the first lines of some pages, below the margin band."""

    def setUp(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("PyMuPDF not available")
        self.root = SCRATCH / self.id().rsplit(".", 1)[-1]
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def reader(self, block_pages: set[int], pages: int = 40, middle: bool = False, config: dict | None = None) -> fid.PdfReference:
        import fitz
        document = fitz.open()
        for number in range(1, pages + 1):
            page = document.new_page()
            y = 100 if not middle else 400  # 100 pt is below the 8% margin band of an A4 page (67 pt); 400 pt is the middle
            if number in block_pages:
                if middle:  # stream order = reading order: twelve body lines come first, so the block is far from both page edges
                    for step in range(12):
                        page.insert_text((72, 80 + 14 * step), f"Opening line {step} {WORDS[(number + step) % 12]} text")
                for step, text in enumerate(("Prepared by: GRG", "Seismic Monitoring Well", "Well 68-32", f"Verified by: Final rev {number}")):
                    page.insert_text((72, y + 14 * step), text)
            page.insert_text((72, 300 if not middle else 600), f"Body {WORDS[number % 12]} {number * 7 + 3} units measured here.")
            if middle:
                for step in range(12):
                    page.insert_text((72, 620 + 14 * step), f"Closing line {step} {WORDS[(number + step) % 12]} text")
        path = self.root / "doc.pdf"
        document.save(str(path))
        reader = fid.PdfReference(path, config or CONFIG)
        self.addCleanup(reader.close)
        return reader

    def test_block_on_a_quarter_of_the_pages_is_furniture(self) -> None:
        reader = self.reader(block_pages=set(range(5, 15)))  # 10 of 40 pages = 25%: below the document-wide 50%
        pdf_text, margin, repeated = reader.page_text(7)
        self.assertEqual(margin, "")
        self.assertIn("Seismic Monitoring Well", repeated)
        self.assertIn("68-32", repeated)
        self.assertNotIn("Body", repeated)

    def test_old_config_does_not_know_the_block(self) -> None:
        reader = self.reader(block_pages=set(range(5, 15)), config=OLD_CONFIG)
        self.assertNotIn("Seismic", "".join(reader.page_text(7)[1:]))

    def test_block_on_too_few_pages_is_not_furniture(self) -> None:
        reader = self.reader(block_pages={5, 6, 7})  # 3 pages < block_min_pages
        self.assertEqual(reader.page_text(6)[1:], ("", ""))

    def test_repeated_line_in_the_middle_of_the_page_is_not_block_furniture(self) -> None:
        reader = self.reader(block_pages=set(range(5, 15)), middle=True)  # the block now stands in the middle: more than 8 lines from both edges
        self.assertNotIn("Seismic", "".join(reader.page_text(7)[1:]))

    def test_false_alarm_gone_and_the_lost_body_number_still_flagged(self) -> None:
        reader = self.reader(block_pages=set(range(5, 15)))
        pdf_text, margin, repeated = reader.page_text(7)
        k1_no_block = "Body {} 52 units measured here.".format(WORDS[7 % 12])
        raw = fid.compare_page(pdf_text, k1_no_block, margin, repeated, CONFIG)
        self.assertEqual(sum(raw["numeric"]["_content_missing"].values()), 0)  # 68, 32 and 7 (the revision number) are the block
        self.assertEqual(raw["numeric"]["missing_furniture_repeated_line"], 3)
        self.assertEqual(warn_codes(fid.judge(raw, "text", False, CONFIG)), set())
        lost = fid.compare_page(pdf_text, "Body {} units measured here.".format(WORDS[7 % 12]), margin, repeated, CONFIG)
        self.assertEqual(set(lost["numeric"]["_content_missing"]), {"52"})  # a body number is not hidden by the block
        self.assertEqual(warn_codes(fid.judge(lost, "text", False, CONFIG)), {"FIDELITY_NUMERIC_RECALL_LOW"})

    def test_block_furniture_never_explains_more_tokens_than_the_block_holds(self) -> None:
        reader = self.reader(block_pages=set(range(5, 15)))
        pdf_text, margin, repeated = reader.page_text(7)
        raw = fid.compare_page(pdf_text + "\nWell 68-32 was cased\n", "", margin, repeated, CONFIG)
        self.assertEqual(raw["numeric"]["missing_furniture_repeated_line"], 3)  # the second '68-32' in the body is content
        self.assertIn("68", raw["numeric"]["_content_missing"])


if __name__ == "__main__":
    unittest.main()
