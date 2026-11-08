"""A repeated data strip near the page bottom is removed as a running line unless keep_line_patterns protects it."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from graph_builder.corpus.chunking import chunk_document
from graph_builder.corpus.config import fingerprint, keep_pattern, validate_config
from graph_builder.ingestion.filters import filter_running_lines
from test_chunking import add_text, make_document

ROOT = Path(__file__).resolve().parents[1]
PAGES = 4
WEATHER = [("Vis.:", 100, "6"), ("Temp:", 200, "581"), ("Pressure:", 300, ""), ("Gusts:", 400, "16")]


def weather_document():
    document = make_document(pages=PAGES)
    for page in range(1, PAGES + 1):
        add_text(document, f"Body text of page {page}.", page=page, top=200, bottom=210)
        for label, left, value in WEATHER:
            add_text(document, label, page=page, top=940, bottom=950, left=left, right=left + 40)
            if value:
                add_text(document, value, page=page, top=940, bottom=950, left=left + 45, right=left + 60)
        add_text(document, f"Page {page} of {PAGES}", page=page, top=965, bottom=975, left=100, right=200)
    return document


def settings(keep: list[str] | None = None) -> dict:
    config = json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8"))
    if keep is not None:
        config["filters"]["keep_line_patterns"] = keep
    return config


def text_of(config: dict) -> str:
    chunks, _, _ = chunk_document(weather_document(), "sample", config, set())
    return "\n".join(chunk["text"] for chunk in chunks)


class KeepLinePatternTests(unittest.TestCase):
    def test_repeated_data_strip_is_removed_without_the_option(self) -> None:
        text = text_of(settings())
        self.assertNotIn("Temp:", text)
        self.assertNotIn("581", text)
        self.assertIn("Body text of page 1.", text)

    def test_data_strip_is_kept_with_the_option_and_page_numbers_are_still_removed(self) -> None:
        text = text_of(settings([r"\b(?:Vis\.|Temp|Pressure|Wind|Gusts):"]))
        for expected in ("Vis.:", "Temp:", "581", "Pressure:", "Gusts:", "16"):
            self.assertIn(expected, text)
        self.assertNotIn("Page 1 of 4", text)

    def test_absent_and_empty_option_match_the_old_output(self) -> None:
        document = weather_document()
        old, old_drops = filter_running_lines(document, .08, .5, 1.0, .5, 3.0)
        none, none_drops = filter_running_lines(document, .08, .5, 1.0, .5, 3.0, None)
        self.assertEqual((old.model_dump_json(), old_drops), (none.model_dump_json(), none_drops))
        self.assertEqual(text_of(settings()), text_of(settings([])))

    def test_pattern_that_matches_nothing_changes_nothing(self) -> None:
        self.assertEqual(text_of(settings()), text_of(settings([r"^never matches$"])))


class KeepLineConfigTests(unittest.TestCase):
    def test_default_configuration_has_no_option_and_the_fingerprint_changes_with_it(self) -> None:
        config = validate_config(settings())
        self.assertNotIn("keep_line_patterns", config["filters"])
        self.assertNotEqual(fingerprint(config, {}), fingerprint(validate_config(settings([r"x"])), {}))

    def test_daily_report_configuration_validates_and_differs_from_default_only_in_the_option(self) -> None:
        daily = json.loads((ROOT / "configs" / "corpus" / "daily_reports.json").read_text(encoding="utf-8"))
        validate_config(copy.deepcopy(daily))
        daily["filters"].pop("keep_line_patterns")
        self.assertEqual(daily, settings())

    def test_invalid_values_are_rejected(self) -> None:
        for bad in ("not a list", [""], [3], ["(unclosed"]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_config(settings(bad))

    def test_unknown_filter_key_is_still_rejected(self) -> None:
        config = settings()
        config["filters"]["unknown"] = 1
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_no_patterns_compile_to_none(self) -> None:
        self.assertIsNone(keep_pattern([]))
        self.assertTrue(keep_pattern(["abc", "d.f"]).search("xx DEF"))


if __name__ == "__main__":
    unittest.main()
