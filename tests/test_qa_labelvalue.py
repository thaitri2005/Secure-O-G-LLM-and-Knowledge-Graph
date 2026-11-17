"""A-432: optional label-value geometry check. The LV01 pattern (a text layer whose stream order lists labels first and values later, so a
serialiser pairs 'Days On Location' with another number) must be flagged, and correct pairs must not."""
from __future__ import annotations

from pathlib import Path
import shutil
import unittest

from graph_builder.corpus.qa import labelvalue as lv

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "data" / "interim" / "overnight" / "b3" / "a432" / "test-tmp-lv"
CONFIG = lv.load_config(ROOT / "configs/qa/label_value.json")


def word(text: str, left: float, bottom: float, width: float = 40, height: float = 8) -> dict:
    return {"text": text, "l": left, "b": bottom, "r": left + width, "t": bottom + height}


def pairs(words: list[dict]) -> dict[str, tuple[str, str]]:
    return {p["label"]: (p["value"], p["source"]) for p in lv.pdf_pairs(lv.phrases_of(words, CONFIG), CONFIG)}


class GeometryTests(unittest.TestCase):
    def test_value_to_the_right_inline_and_blank(self) -> None:
        words = [word("Days", 40, 600, 20), word("On", 62, 600, 10), word("Location:", 74, 600, 40), word("1", 180, 600, 5),   # value to the right, far from the label
                 word("Proposed", 40, 580, 40), word("TD:", 82, 580, 15), word("1700", 99, 580, 20),                         # inline
                 word("Last", 40, 560, 20), word("Casing:", 62, 560, 30), word("Rig:", 180, 560, 15), word("Major", 198, 560, 25)]  # blank, next label follows
        found = pairs(words)
        self.assertEqual(found["days on location"], ("1", "right"))
        self.assertEqual(found["proposed td"], ("1700", "inline"))
        self.assertEqual(found["last casing"], ("", "blank"))
        self.assertEqual(found["rig"], ("Major", "inline"))

    def test_value_below_the_label(self) -> None:
        found = pairs([word("Spud", 40, 600, 20), word("Date:", 62, 600, 20), word("18-Aug-16", 40, 589, 45)])
        self.assertEqual(found["spud date"], ("18-Aug-16", "below"))

    def test_times_and_short_text_are_not_labels(self) -> None:
        self.assertEqual(pairs([word("08:30", 40, 600), word("a:", 100, 600, 10)]), {})

    def test_lv01_pairing_is_flagged_and_correct_pairs_are_not(self) -> None:
        words = [word("Days", 40, 600, 20), word("On", 62, 600, 10), word("Location:", 74, 600, 40), word("1", 180, 600, 5),
                 word("Proposed", 40, 580, 40), word("TD:", 82, 580, 15), word("1700", 99, 580, 20),
                 word("Rig:", 40, 560, 15), word("Major", 100, 560, 25)]
        pdf = lv.pdf_pairs(lv.phrases_of(words, CONFIG), CONFIG)
        labels = {p["label"] for p in pdf}
        wrong = lv.k1_pairs("Rig: Major | Proposed TD: 1700 | Days On Location: 1700", labels)  # the K1 chunk pairs the label with the TD number
        result = lv.compare_page(pdf, wrong, CONFIG)
        self.assertEqual([m["label"] for m in result["mismatches"]], ["days on location"])
        self.assertEqual(result["mismatches"][0]["pdf_values"], ["1"])
        self.assertEqual(result["counts"]["agree"], 2)
        right = lv.compare_page(pdf, lv.k1_pairs("Rig: Major\nProposed TD: 1,700\nDays On Location: 1", labels), CONFIG)
        self.assertEqual(right["mismatches"], [])

    def test_label_repeated_on_the_page_accepts_any_pdf_value(self) -> None:
        pdf = [{"label": "operator", "value": "City", "source": "inline", "box": [0, 0, 1, 1]}, {"label": "operator", "value": "2 / 0", "source": "right", "box": [0, 0, 1, 1]}]
        self.assertEqual(lv.compare_page(pdf, [("operator", "2")], CONFIG)["mismatches"], [])
        self.assertEqual(len(lv.compare_page(pdf, [("operator", "7")], CONFIG)["mismatches"]), 1)

    def test_blank_pdf_value_and_empty_k1_value_are_skipped_not_judged(self) -> None:
        pdf = [{"label": "last casing", "value": "", "source": "blank", "box": [0, 0, 1, 1]}, {"label": "rig", "value": "Major", "source": "inline", "box": [0, 0, 1, 1]}]
        result = lv.compare_page(pdf, [("last casing", "9.625"), ("rig", "")], CONFIG)
        self.assertEqual(result["mismatches"], [])
        self.assertEqual(result["counts"], {"pdf_value_blank": 1, "k1_value_empty": 1})

    def test_longer_label_claims_its_text_and_a_following_label_means_no_value(self) -> None:
        labels = {"depth (ft)", "measured depth (ft)", "rig"}
        found = lv.k1_pairs("Measured Depth (ft): 100 Rig: Major", labels)
        self.assertEqual(found, [("measured depth (ft)", "100"), ("rig", "major")])
        self.assertEqual(lv.k1_pairs("Rig: Measured Depth (ft): 100", labels), [("rig", ""), ("measured depth (ft)", "100")])

    def test_a_number_is_compared_without_thousands_commas(self) -> None:
        self.assertEqual(lv.first_token("| 1,700 |"), "1700")


class PdfTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("PyMuPDF not available")
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, SCRATCH, ignore_errors=True)

    def test_real_pdf_text_layer_with_labels_first_and_values_later(self) -> None:
        import fitz
        import pypdfium2 as pdfium
        document = fitz.open()
        page = document.new_page()
        for y, text in ((100, "Days On Location:"), (115, "Proposed TD (ft): 1700")):
            page.insert_text((72, y), text)
        page.insert_text((250, 100), "1")  # drawn last, so the stream order separates label and value
        path = SCRATCH / "form.pdf"
        document.save(str(path))
        pdf = pdfium.PdfDocument(str(path))
        self.addCleanup(pdf.close)
        found = pairs(lv.words_of_page(pdf[0]))
        self.assertEqual(found["days on location"], ("1", "right"))
        self.assertEqual(found["proposed td (ft)"], ("1700", "inline"))


if __name__ == "__main__":
    unittest.main()
