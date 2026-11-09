"""Key-value form pairing on synthetic text layers and on the real daily report PDF."""
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from graph_builder.corpus.form_scoring import annotated_box_coverage, pair_score
from graph_builder.corpus.forms import TEMPLATE, extract, extract_auto, find_labels, load_template

ROOT = Path(__file__).resolve().parents[1]
DAILY_SUMMARY = ROOT / "data/raw/gdr882_ak3_appx_30_6_dailyreportsummaryrpt_160920155352.pdf"
TEMPLATE_LABELS = {"labels": {"Vertical Depth (ft):": {"direction": "right_then_below"},
                              "Days On Location:": {"direction": "right_then_below"},
                              "Report For": {"direction": "right_then_below"}}}


def word(text, left, right, row, top=100.0):
    return {"text": text, "bbox": [left, top, right, top + 10], "row": row}


def layer(words, rulings=(), text="Operations Summary"):
    return {"page": 1, "width": 600.0, "height": 800.0, "rotation": 0, "upright_for_pairing": False, "chars": [],
            "words": list(words), "rulings": list(rulings), "text": text, "provenance": "synthetic"}


def vertical_ruling(x):
    return [x - 0.4, 90.0, x + 0.4, 115.0]


def form_layer():
    """One table row: depth and day count in separate cells, with a neighbouring cell holding 1700."""
    words = [word("Vertical", 10, 50, 0), word("Depth", 52, 80, 0), word("(ft):", 82, 110, 0), word("465", 115, 140, 0),
             word("Days", 210, 240, 0), word("On", 242, 256, 0), word("Location:", 258, 310, 0), word("17", 315, 330, 0),
             word("1700", 410, 440, 0), word("Operations", 10, 80, 1, top=300), word("Summary", 82, 140, 1, top=300)]
    return layer(words, [vertical_ruling(200), vertical_ruling(400)])


def extract_from(synthetic, **options):
    with patch("graph_builder.corpus.forms.source_page", return_value=synthetic):
        return extract_auto(Path("synthetic.pdf"), 1, TEMPLATE_LABELS, **options)


class LabelTests(unittest.TestCase):
    def test_template_labels_cover_several_words_and_prefer_the_longest(self):
        words = [word("Days", 10, 30, 0), word("On", 32, 40, 0), word("Location:", 42, 90, 0), word("17", 95, 105, 0)]
        labels = find_labels(words, TEMPLATE_LABELS["labels"])
        self.assertEqual([label["key"] for label in labels], ["Days On Location:"])
        self.assertEqual(labels[0]["bbox"], [10, 100, 90, 110])

    def test_generic_labels_end_with_a_colon(self):
        words = [word("Depth", 10, 40, 0), word("(ft):", 42, 70, 0), word("465", 75, 95, 0)]
        self.assertEqual([label["key"] for label in find_labels(words, None)], ["Depth (ft):"])


class PairingTests(unittest.TestCase):
    def test_values_stay_in_their_own_cell(self):
        form = extract_from(form_layer(), minimum_share=0.4)
        values = {field["key"]: field["value"] for field in form["fields"]}
        self.assertEqual(values["Vertical Depth (ft):"], "465")
        self.assertEqual(values["Days On Location:"], "17")
        self.assertNotIn("1700", values.values())
        self.assertEqual((form["method"], form["verified"]), ("rimbase_template", True))
        self.assertTrue(all(field["verified"] and field["key_bbox"] and field["value_bbox"] for field in form["fields"]))

    def test_result_reports_label_share_and_minimum(self):
        form = extract_from(form_layer(), minimum_share=0.4)
        self.assertAlmostEqual(form["template_label_share"], 2 / 3)
        self.assertEqual(form["template_minimum_share"], 0.4)

    def test_template_mismatch_returns_none_when_generic_is_off(self):
        self.assertIsNone(extract_from(form_layer(), minimum_share=0.9))
        self.assertIsNone(extract_from(form_layer(), minimum_share=0.9, generic=False))

    def test_generic_pairing_is_marked_unverified(self):
        words = [word("Alpha:", 10, 50, 0), word("1", 55, 60, 0), word("Beta:", 110, 150, 0), word("2", 155, 160, 0),
                 word("Gamma:", 210, 250, 0), word("3", 255, 260, 0)]
        unknown = layer(words, [vertical_ruling(100), vertical_ruling(200)], text="Alpha: 1 Beta: 2 Gamma: 3")
        self.assertIsNone(extract_from(unknown, minimum_share=0.4))
        form = extract_from(unknown, minimum_share=0.4, generic=True)
        self.assertEqual((form["method"], form["verified"]), ("generic", False))
        self.assertEqual([(field["key"], field["value"]) for field in form["fields"]], [("Alpha:", "1"), ("Beta:", "2"), ("Gamma:", "3")])
        self.assertFalse(any(field["verified"] for field in form["fields"]))

    def test_generic_default_is_off_in_the_k1_configuration(self):
        from graph_builder.corpus.k1_config import load_k1_config
        self.assertIs(load_k1_config()["forms"]["generic"], False)

    def test_page_without_colon_labels_returns_none_even_when_generic_is_on(self):
        plain = layer([word("Plain", 10, 40, 0), word("text", 42, 70, 0)], text="Plain text")
        self.assertIsNone(extract_from(plain, minimum_share=0.4, generic=True))

    def test_extract_uses_the_template_directions(self):
        with patch("graph_builder.corpus.forms.source_page", return_value=form_layer()):
            form = extract(Path("synthetic.pdf"), 1, "template", TEMPLATE_LABELS)
        self.assertEqual([field["key"] for field in form["fields"]], ["Vertical Depth (ft):", "Days On Location:"])

    def test_template_file_is_valid(self):
        template = load_template()
        self.assertEqual(TEMPLATE, ROOT / "configs/corpus/rimbase_form_template.json")
        self.assertIn("Days On Location:", template["labels"])
        self.assertEqual(json.loads(TEMPLATE.read_text(encoding="utf-8")), template)


class ScoringTests(unittest.TestCase):
    def test_pair_accuracy_penalizes_extra_predictions(self):
        actual = [dict(key="A", value="one", key_bbox=[1] * 4, value_bbox=[2] * 4),
                  dict(key="B", value="invented", key_bbox=None, value_bbox=None)]
        result = pair_score([("A", "one")], actual, "A one")
        self.assertEqual(result["pair_accuracy"], .5)
        self.assertEqual(result["literal_source_absent_count"], 1)
        self.assertEqual(result["bbox_share"], .5)

    def test_box_coverage_matches_duplicates_by_overlap(self):
        expected = [dict(key="A", value="1", key_bbox=[0, 0, 10, 10], value_bbox=[10, 0, 20, 10]),
                    dict(key="A", value="1", key_bbox=[0, 20, 10, 30], value_bbox=[10, 20, 20, 30])]
        actual = [dict(key="A", value="1", key_bbox=[0, 20, 10, 30], value_bbox=[10, 20, 20, 30]),
                  dict(key="A", value="1", key_bbox=[0, 0, 10, 10], value_bbox=[10, 0, 20, 10])]
        result = annotated_box_coverage(expected, actual)
        self.assertEqual((result["annotated_boxes"], result["annotated_bbox_coverage"], result["mean_matched_bbox_iou"]), (4, 1.0, 1.0))


@unittest.skipUnless(DAILY_SUMMARY.exists(), "daily report summary PDF is not in data/raw")
class RealDailyReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = load_template()
        cls.forms = {number: extract_auto(DAILY_SUMMARY, number, template, 0.4) for number in (1, 17)}

    @staticmethod
    def values(form):
        return {field["key"]: field["value"] for field in form["fields"]}

    def test_report_17_depth_and_day_count(self):
        values = self.values(self.forms[17])
        self.assertEqual(values["Vertical Depth (ft):"], "465")
        self.assertEqual(values["Days On Location:"], "17")
        self.assertNotEqual(values["Days On Location:"], "1700")

    def test_report_1_day_count(self):
        self.assertEqual(self.values(self.forms[1])["Days On Location:"], "1")

    def test_pages_are_verified_template_forms(self):
        for form in self.forms.values():
            self.assertEqual((form["method"], form["verified"]), ("rimbase_template", True))


if __name__ == "__main__":
    unittest.main()
