"""A-435: optional lower form blocks (safety / weather labels below the tables) on synthetic text layers; default behaviour unchanged."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from graph_builder.corpus.form_blocks import block_fields, validate_form_blocks
from graph_builder.corpus.forms import extract_auto
from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config
from graph_builder.corpus.k1_export import package_identity
from test_corpus_forms import TEMPLATE_LABELS, form_layer, layer, word

ROOT = Path(__file__).resolve().parents[1]
BLOCKS = json.loads((ROOT / "configs/corpus/form_blocks.json").read_text(encoding="utf-8"))
LEXICON = BLOCKS["labels"]


def title(text: str, row: int, top: float) -> list[dict]:
    """A centred section title (page width 600): one word per 60 points around x = 300."""
    words = text.split()
    start = 300 - 30 * len(words)
    return [word(w, start + 60 * i, start + 60 * i + 50, row, top=top) for i, w in enumerate(words)]


def weather_rows(first_row: int = 1, top: float = 400.0) -> list[dict]:
    """Rows of a weather block: values at different distances from their labels and one blank label."""
    r = first_row
    return [
        word("Sky", 10, 30, r, top), word("Condition:", 32, 90, r, top), word("Clear", 114, 140, r, top),
        word("Visibility:", 309, 360, r, top), word("10", 404, 416, r, top),
        word("Air", 10, 25, r + 1, top + 12), word("Temperature:", 27, 100, r + 1, top + 12), word("55", 114, 124, r + 1, top + 12), word("degF", 127, 150, r + 1, top + 12),
        word("Bar.", 309, 325, r + 1, top + 12), word("Pressure:", 327, 364, r + 1, top + 12),
        word("Wind", 10, 30, r + 2, top + 24), word("Speed/Dir:", 32, 90, r + 2, top + 24), word("4", 114, 120, r + 2, top + 24), word("/", 122, 126, r + 2, top + 24), word("SE", 128, 140, r + 2, top + 24),
        word("Wind", 310, 330, r + 2, top + 24), word("Gusts:", 332, 365, r + 2, top + 24), word("6", 404, 410, r + 2, top + 24),
    ]


def pairs(fields: list[dict]) -> dict[str, str]:
    return {field["key"]: field["value"] for field in fields}


def run(words: list[dict], boundary_row=None, verified=True):
    return block_fields(layer(words), LEXICON, BLOCKS, boundary_row, verified)


class BlockPairingTests(unittest.TestCase):
    def test_values_labels_and_blank_are_paired_on_their_own_row(self) -> None:
        fields, findings = run(title("Weather Information", 0, 380) + weather_rows())
        self.assertEqual(pairs(fields), {"Sky Condition:": "Clear", "Visibility:": "10", "Air Temperature:": "55 degF", "Bar. Pressure:": "",
                                         "Wind Speed/Dir:": "4 / SE", "Wind Gusts:": "6"})
        self.assertEqual(findings["ambiguous"], [])
        blank = next(field for field in fields if field["key"] == "Bar. Pressure:")
        self.assertIsNone(blank["value_bbox"])
        self.assertTrue(all(field["key_bbox"] and field["verified"] and field["source_word_boxes"] for field in fields))

    def test_blank_label_never_takes_the_value_of_the_next_label_or_row(self) -> None:
        fields, _ = run(title("Weather Information", 0, 380) + weather_rows())
        values = pairs(fields)
        self.assertEqual(values["Bar. Pressure:"], "")
        self.assertEqual(values["Wind Gusts:"], "6")

    def test_two_separate_phrases_are_ambiguous_and_not_output(self) -> None:
        words = title("Weather Information", 0, 380) + [word("Visibility:", 309, 360, 1, 400), word("6", 380, 386, 1, 400), word("9", 500, 506, 1, 400)]
        fields, findings = run(words)
        self.assertEqual(fields, [])
        self.assertEqual(findings["ambiguous"], [{"label": "Visibility:", "phrases": ["6", "9"]}])

    def test_labels_in_free_text_sections_are_not_paired(self) -> None:
        words = (title("Management Summary", 0, 100) + [word("Transport:", 10, 60, 1, 120), word("by", 64, 74, 1, 120), word("helicopter", 78, 130, 1, 120)]
                 + title("Weather Information", 2, 200) + [word("Transport:", 10, 60, 3, 220), word("truck", 114, 140, 3, 220)])
        fields, findings = run(words)
        self.assertEqual(pairs(fields), {"Transport:": "truck"})
        self.assertEqual(findings["labels_in_free_text_rows"], 1)

    def test_rows_right_below_the_operations_title_are_free_text_until_a_title(self) -> None:
        words = [word("Transport:", 10, 60, 1, 120), word("x", 114, 120, 1, 120)] + title("Weather Information", 2, 200) + [word("Transport:", 10, 60, 3, 220), word("truck", 114, 140, 3, 220)]
        fields, _ = run(words, boundary_row=0)
        self.assertEqual(pairs(fields), {"Transport:": "truck"})

    def test_label_in_the_middle_of_a_sentence_is_not_a_label(self) -> None:
        words = title("Weather Information", 0, 380) + [word("Crew", 10, 34, 1, 400), word("Transport:", 36, 90, 1, 400), word("late", 93, 112, 1, 400)]
        self.assertEqual(run(words)[0], [])

    def test_unconfigured_labels_are_ignored(self) -> None:
        words = title("Weather Information", 0, 380) + [word("Humidity:", 10, 60, 1, 400), word("40", 114, 126, 1, 400)]
        self.assertEqual(run(words)[0], [])

    def test_comments_take_indented_following_rows_only(self) -> None:
        words = title("Weather Information", 0, 380) + [
            word("Comments:", 10, 60, 1, 400), word("rain", 114, 140, 1, 400), word("all", 142, 160, 1, 400),
            word("day", 114, 134, 2, 412),                                    # continuation (indented at the value)
            word("end", 10, 30, 3, 424),                                       # starts left of the value: not a continuation
        ]
        fields, _ = run(words)
        self.assertEqual(pairs(fields), {"Comments:": "rain all day"})
        words2 = words[:-2] + [word("Visibility:", 10, 60, 2, 412), word("3", 114, 120, 2, 412)]
        self.assertEqual(pairs(run(words2)[0]), {"Comments:": "rain all", "Visibility:": "3"})   # a label row stops the comment
        far = title("Weather Information", 0, 380) + [word("Comments:", 10, 60, 1, 400), word("rain", 114, 140, 1, 400), word("later", 114, 140, 2, 460)]
        self.assertEqual(pairs(run(far)[0]), {"Comments:": "rain"})        # a big vertical gap is not a continuation

    def test_deterministic(self) -> None:
        words = title("Weather Information", 0, 380) + weather_rows()
        self.assertEqual(run(copy.deepcopy(words)), run(copy.deepcopy(words)))


class ExtractAutoTests(unittest.TestCase):
    def extract(self, synthetic, **options):
        with patch("graph_builder.corpus.forms.source_page", return_value=synthetic):
            return extract_auto(Path("synthetic.pdf"), 1, TEMPLATE_LABELS, **options)

    def test_default_is_unchanged_for_template_and_continuation_pages(self) -> None:
        template_page = form_layer()
        lower = title("Weather Information", 2, 330) + weather_rows(3, 350)
        template_page["words"] += lower
        before = self.extract(form_layer(), minimum_share=0.4)
        self.assertEqual(self.extract(template_page, minimum_share=0.4), before)   # lower rows are ignored without the option
        self.assertEqual(self.extract(form_layer(), minimum_share=0.4, blocks=None), before)
        continuation = layer(title("Weather Information", 0, 100) + weather_rows(1, 120), text="Weather Information")
        self.assertIsNone(self.extract(continuation, minimum_share=0.4))

    def test_option_on_appends_block_fields_to_a_template_page_and_keeps_the_header_fields(self) -> None:
        plain = self.extract(form_layer(), minimum_share=0.4)
        page = form_layer()
        page["words"] += title("Weather Information", 2, 330) + weather_rows(3, 350)
        findings: list = []
        form = self.extract(page, minimum_share=0.4, blocks=BLOCKS, findings=findings)
        self.assertEqual(form["fields"][:len(plain["fields"])], plain["fields"])
        self.assertEqual(pairs(form["fields"][len(plain["fields"]):])["Visibility:"], "10")
        self.assertTrue(form["verified"] and form["method"] == "rimbase_template")
        self.assertTrue(all(field["verified"] for field in form["fields"]))
        self.assertEqual(findings, [])

    def test_continuation_page_becomes_an_unverified_block_form_only_with_enough_labels(self) -> None:
        full = layer(title("Weather Information", 0, 100) + weather_rows(1, 120), text="Weather Information")
        form = self.extract(full, minimum_share=0.4, blocks=BLOCKS)
        self.assertEqual((form["method"], form["verified"]), ("generic", False))
        self.assertTrue(all(field["verified"] is False for field in form["fields"]))
        self.assertEqual(len(form["fields"]), 6)
        few = layer(title("Weather Information", 0, 100) + weather_rows(1, 120)[:5], text="Weather Information")   # 2 labels < min_block_labels
        self.assertIsNone(self.extract(few, minimum_share=0.4, blocks=BLOCKS))

    def test_unsupported_page_reports_no_ambiguity(self) -> None:
        page = layer(title("Weather Information", 0, 100) + [word("Transport:", 10, 60, 1, 120), word("a", 114, 120, 1, 120), word("b", 300, 306, 1, 120)],
                     text="Weather Information")
        findings: list = []
        self.assertIsNone(self.extract(page, minimum_share=0.4, blocks=BLOCKS, findings=findings))
        self.assertEqual(findings, [])

    def test_page_without_block_labels_is_untouched_by_the_option(self) -> None:
        plain = layer([word("Some", 10, 40, 0), word("prose", 42, 80, 0)], text="Some prose")
        self.assertIsNone(self.extract(plain, minimum_share=0.4, blocks=BLOCKS))

    def test_block_reader_failure_keeps_header_fields_and_is_reported(self) -> None:
        page = form_layer()
        page["words"] += title("Weather Information", 2, 330) + weather_rows(3, 350)
        findings: list = []
        with patch("graph_builder.corpus.form_blocks.extract_block_fields", side_effect=RuntimeError("boom")):
            form = self.extract(page, minimum_share=0.4, blocks=BLOCKS, findings=findings)
        self.assertEqual(form["fields"], self.extract(form_layer(), minimum_share=0.4)["fields"])
        self.assertEqual(findings, [{"page": 1, "error": "RuntimeError: boom"}])

    def test_ambiguous_labels_are_reported_in_findings(self) -> None:
        page = layer(title("Weather Information", 0, 100) + weather_rows(1, 120) + [word("Transport:", 10, 60, 5, 200), word("a", 114, 120, 5, 200), word("b", 300, 306, 5, 200)],
                     text="Weather Information")
        findings: list = []
        form = self.extract(page, minimum_share=0.4, blocks=BLOCKS, findings=findings)
        self.assertNotIn("Transport:", pairs(form["fields"]))
        self.assertEqual(findings, [{"page": 1, "label": "Transport:", "phrases": ["a", "b"]}, {"page": 1, "block_only": True}])


DAILY = ROOT / "data/raw/gdr882_ak3_appx_27_6_dailyreportdetailrpt_nocost_160920154309.pdf"


@unittest.skipUnless(DAILY.exists(), "daily report PDF not available")
class RealDailyReportTests(unittest.TestCase):
    """Regression on the supported template (DEV family RIMBase daily report; values read from the PDF words by hand, see A-435 gold)."""

    def form(self, page: int, blocks=None, findings=None):
        from graph_builder.corpus.forms import load_template
        return extract_auto(DAILY, page, load_template(), 0.4, False, blocks, findings)

    def test_default_and_option_keep_the_header_fields_and_add_the_lower_block(self) -> None:
        plain, findings = self.form(1), []
        on = self.form(1, BLOCKS, findings)
        self.assertEqual(on["fields"][:len(plain["fields"])], plain["fields"])
        lower = pairs(on["fields"][len(plain["fields"]):])
        self.assertEqual(lower["Visibility:"], "6")
        self.assertEqual(lower["Wind Gusts:"], "16")
        self.assertEqual(lower["Bar. Pressure:"], "")
        self.assertEqual(lower["Days Since LTI:"], "1")
        self.assertEqual(lower["Air Temperature:"], "58 degF")
        self.assertEqual(lower["Wind Speed/Dir:"], "12 / W")
        self.assertEqual(lower["First Aid Treatments:"], "")
        self.assertEqual(findings, [])
        self.assertEqual({k: v for k, v in pairs(plain["fields"]).items() if k in ("Days On Location:", "Proposed TD (ft):")}, {"Days On Location:": "1", "Proposed TD (ft):": "1700"})

    def test_weather_only_continuation_page(self) -> None:
        self.assertIsNone(self.form(8))                                   # default: no form on this page
        form = self.form(8, BLOCKS)
        self.assertEqual((form["method"], form["verified"]), ("generic", False))
        self.assertEqual(pairs(form["fields"]), {"Sky Condition:": "low overcast", "Visibility:": "0.3", "Air Temperature:": "50 degF", "Bar. Pressure:": "",
                                                 "Wind Speed/Dir:": "10 / E", "Wind Gusts:": "15", "Comments:": "Heavy rain through out the day"})

    def test_deterministic_on_the_real_page(self) -> None:
        self.assertEqual(self.form(1, BLOCKS), self.form(1, BLOCKS))


class ConfigTests(unittest.TestCase):
    def test_shipped_block_configuration_is_valid_and_not_part_of_the_default_k1_configuration(self) -> None:
        validate_form_blocks(copy.deepcopy(BLOCKS))
        self.assertNotIn("form_blocks", load_k1_config())

    def test_invalid_configurations_are_refused(self) -> None:
        for mutate in (lambda c: c.pop("geometry"), lambda c: c["labels"].update({"X:": {"multiline": "yes"}}), lambda c: c["labels"].clear(),
                       lambda c: c["geometry"].update({"value_phrase_gap_em": -1}), lambda c: c.update({"min_block_labels": 0}),
                       lambda c: c.update({"free_text_titles": [1]}), lambda c: c.update({"extra": 1})):
            config = copy.deepcopy(BLOCKS)
            mutate(config)
            with self.assertRaises(ValueError):
                validate_form_blocks(config)

    def test_option_enters_the_package_identity_and_k1_config_validation(self) -> None:
        base = load_k1_config()
        on = copy.deepcopy(base)
        on["form_blocks"] = copy.deepcopy(BLOCKS)
        validate_k1_config(on)
        self.assertNotEqual(package_identity("f" * 64, base), package_identity("f" * 64, on))
        on["form_blocks"]["min_block_labels"] = 0
        with self.assertRaises(ValueError):
            validate_k1_config(on)


if __name__ == "__main__":
    unittest.main()
