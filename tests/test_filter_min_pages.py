"""C-02: the share rule of ``filter_running_lines`` is always true for a document of one or two pages, so titles and
identifiers in the margin band are removed as "running lines". The optional ``filters.running_line_min_pages`` demands
repetition on a minimum number of distinct pages. Default behavior stays byte-identical."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from graph_builder.corpus.chunking import chunk_document
from graph_builder.corpus.config import fingerprint, load_config, validate_config
from graph_builder.ingestion.filters import filter_running_lines
from test_chunking import add_text, make_document
from test_filter_position import add_numeric_table, report_document

ROOT = Path(__file__).resolve().parents[1]


def run(document, min_pages=None, tolerance=None):
    return filter_running_lines(document, .08, .5, 1.0, .5, 3.0, None, tolerance, min_pages)


def short_document(pages: int, titles_on_every_page: bool):
    """A title and a well identifier in the top band and a print stamp in the bottom band, plus body text."""
    document = make_document(pages)
    for page in range(1, pages + 1):
        if titles_on_every_page or page == 1:
            add_text(document, "Wellbore Schematic Report", page, 30, 42)
            add_text(document, "Well ID: AK-3", page, 52, 62, left=120)
        add_text(document, f"Printed: 15:33 {page}0-Sep-16", page, 960, 970)
        add_text(document, "Body text of the page.", page, 400, 410)
    return document


def kept(result) -> list[str]:
    return [t.text for t in result.texts if t.text]


class MinPagesTests(unittest.TestCase):
    def test_varying_report_values_survive_while_page_counters_and_print_stamps_are_removed(self) -> None:
        document = make_document(4)
        for page in range(1, 5):
            add_text(document, "Summary report", page, 16, 26, left=120)
            add_text(document, f"Inspection date: {page + 10}/12/2024", page, 52, 62, left=120)
            add_text(document, f"Page {page} of 4", page, 954, 964)
            add_text(document, f"Printed: 15:33 {page}/12/2024", page, 971, 981)
            add_text(document, "Body text.", page, 400, 410)
        legacy, _ = run(document, 3)
        protected, _ = filter_running_lines(document, .08, .5, 1.0, .5, 3.0, min_pages=3,
                                            keep_varying_numbers=True)
        self.assertEqual(kept(legacy), ["Body text."] * 4)
        self.assertEqual(kept(protected), [value for page in range(1, 5)
                                          for value in (f"Inspection date: {page + 10}/12/2024", "Body text.")])

    def test_varying_values_protect_horizontal_fragments(self) -> None:
        document = make_document(4)
        for page in range(1, 5):
            add_text(document, "Report #", page, 48, 58, left=100, right=150)
            add_text(document, str(100 + page), page, 48, 58, left=156, right=180)
            add_text(document, f"Page {page}", page, 960, 970)
        legacy, _ = run(document, 3)
        protected, _ = filter_running_lines(document, .08, .5, 1.0, .5, 3.0, min_pages=3,
                                            keep_varying_numbers=True)
        self.assertEqual(kept(legacy), [])
        self.assertEqual(kept(protected), [x for page in range(1, 5) for x in ("Report #", str(100 + page))])

    def test_defect_one_page_document_loses_its_title_without_the_option(self) -> None:
        off, drops = run(short_document(1, True))
        self.assertEqual(kept(off), ["Body text of the page."])
        self.assertEqual(drops, 3)

    def test_one_page_document_keeps_everything_with_the_option(self) -> None:
        document = short_document(1, True)
        on, drops = run(document, 2)
        self.assertEqual(drops, 0)
        self.assertEqual(on.model_dump_json(), document.model_dump_json())

    def test_header_repeated_on_both_pages_of_a_two_page_document_is_still_removed(self) -> None:
        off, off_drops = run(short_document(2, True))
        on, on_drops = run(short_document(2, True), 2)
        self.assertEqual(kept(on), ["Body text of the page."] * 2)
        self.assertEqual((off.model_dump_json(), off_drops), (on.model_dump_json(), on_drops))

    def test_line_on_one_page_of_a_two_page_document_is_kept(self) -> None:
        off, _ = run(short_document(2, False))
        on, _ = run(short_document(2, False), 2)
        # OFF: the title on page 1 is 1 of 2 pages = 50 %, so it counts as repeated and is removed.
        self.assertNotIn("Wellbore Schematic Report", kept(off))
        self.assertIn("Wellbore Schematic Report", kept(on))
        self.assertIn("Well ID: AK-3", kept(on))
        # the print stamp occurs on both pages (same key, digit runs normalised) and is still a running line
        self.assertFalse([text for text in kept(on) if text.startswith("Printed:")])

    def test_longer_documents_are_byte_identical_when_the_share_rule_dominates(self) -> None:
        for pages in (3, 4, 6):
            document = report_document() if pages == 6 else short_document(pages, True)
            off, off_drops = run(document)
            on, on_drops = run(document, 2)
            self.assertEqual((off.model_dump_json(), off_drops), (on.model_dump_json(), on_drops), pages)
            self.assertGreater(off_drops, 0)

    def test_minimum_above_the_page_count_removes_nothing(self) -> None:
        document = short_document(3, True)
        on, drops = run(document, 5)
        self.assertEqual((drops, on.model_dump_json()), (0, document.model_dump_json()))

    def test_minimum_can_raise_the_requirement_above_the_share(self) -> None:
        document = make_document(6)
        for page in range(1, 7):
            add_text(document, "Body", page, 400, 410)
            if page <= 3:
                add_text(document, "Reference 42", page, 20, 30)
        self.assertEqual(run(document)[1], 3)           # 3 of 6 pages = 50 %
        self.assertEqual(run(document, 3)[1], 3)
        self.assertEqual(run(document, 4)[1], 0)

    def test_combination_with_the_position_test(self) -> None:
        document = report_document()
        both, both_drops = run(document, 2, 0.005)
        position_only, position_drops = run(document, None, 0.005)
        self.assertEqual((both.model_dump_json(), both_drops), (position_only.model_dump_json(), position_drops))
        one = make_document(1)
        add_text(one, "Reference 42", 1, 20, 30)
        add_numeric_table(one, 1, ["150", "0"], top=920)
        for tolerance in (None, 0.005):
            self.assertEqual(run(one, 2, tolerance)[1], 0, tolerance)

    def test_option_off_is_identical_to_not_passing_it(self) -> None:
        document = short_document(2, True)
        old, old_drops = filter_running_lines(document, .08, .5, 1.0, .5, 3.0)
        none, none_drops = filter_running_lines(document, .08, .5, 1.0, .5, 3.0, None, None, None)
        self.assertEqual((old.model_dump_json(), old_drops), (none.model_dump_json(), none_drops))


class MinPagesConfigTests(unittest.TestCase):
    @staticmethod
    def settings(minimum=None) -> dict:
        config = json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8"))
        if minimum is not None:
            config["filters"]["running_line_min_pages"] = minimum
        return config

    def test_default_has_no_option_and_the_fingerprint_changes_with_it(self) -> None:
        config = validate_config(self.settings())
        self.assertNotIn("running_line_min_pages", config["filters"])
        self.assertNotEqual(fingerprint(config, {}), fingerprint(validate_config(self.settings(2)), {}))
        self.assertNotEqual(fingerprint(validate_config(self.settings(2)), {}), fingerprint(validate_config(self.settings(3)), {}))

    def test_invalid_values_are_rejected_and_valid_ones_accepted(self) -> None:
        for bad in (0, 1, -2, 1001, 2.5, "2", True, None, [2]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                config = self.settings()
                config["filters"]["running_line_min_pages"] = bad
                validate_config(config)
        for good in (2, 3, 1000):
            validate_config(self.settings(good))

    def test_chunks_of_a_one_page_document_keep_the_title_only_with_the_option(self) -> None:
        def text(config) -> str:
            chunks, _, _ = chunk_document(short_document(1, True), "sample", config, set())
            return "\n".join(chunk["text"] for chunk in chunks)
        off, on = text(self.settings()), text(self.settings(2))
        self.assertNotIn("Wellbore Schematic Report", off)
        self.assertIn("Wellbore Schematic Report", on)
        self.assertIn("Well ID: AK-3", on)
        self.assertEqual(text(self.settings()), text(self.settings()))

    def test_shared_default_configuration_file_is_not_changed_by_the_option(self) -> None:
        default = json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8"))
        self.assertNotIn("running_line_min_pages", default["filters"])

    def test_daily_report_profile_keeps_short_report_headers_and_filters_repeated_furniture(self) -> None:
        config = load_config(ROOT / "configs" / "corpus" / "daily_reports.json")
        report_number = "RPT NUM.: 22"
        report_date = "RPT DATE: 11/10/2020"
        for pages in (1, 2, 4):
            with self.subTest(pages=pages):
                document = make_document(pages)
                add_text(document, report_number, top=40, bottom=50)
                add_text(document, report_date, top=60, bottom=70)
                for page in range(1, pages + 1):
                    add_text(document, "Daily Drilling Report", page, 20, 30)
                    add_text(document, f"Page {page} of {pages}", page, 965, 975)
                    add_text(document, "Temp: 58", page, 940, 950)
                    add_text(document, "Operations continued.", page, 400, 410)

                chunks, _, stats = chunk_document(document, "sample", config, set())
                text = "\n".join(chunk["text"] for chunk in chunks)
                self.assertIn(report_number, text)
                self.assertIn(report_date, text)
                self.assertEqual(text.count("Temp: 58"), pages)
                self.assertEqual(text.count("Daily Drilling Report"), pages if pages < 3 else 0)
                for page in range(1, pages + 1):
                    self.assertEqual(f"Page {page} of {pages}" in text, pages < 3)
                self.assertEqual(stats["dropped"]["running_line"], 0 if pages < 3 else 2 * pages)


if __name__ == "__main__":
    unittest.main()
