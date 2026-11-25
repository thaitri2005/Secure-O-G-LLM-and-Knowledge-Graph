"""Regression checks for source-backed daily-report fields."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pymupdf

from graph_builder.corpus.k1_config import load_k1_config
STANDARD_24NOV = __import__('pathlib').Path(__file__).resolve().parents[1] / "configs/corpus/candidates/k1_standard_24nov.json"  # the profile main shipped on 24 November (D2/D4 decisions made the default smaller)
from graph_builder.corpus.report_fields import recover_fields, source_fields
from graph_builder.corpus.text_layer import source_page


class SourceReportFieldsTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "dailyreport.pdf"

    def write_page(self, lines, crop=False):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            for x, y, text in lines:
                page.insert_text((x, y), text, fontsize=9)
            if crop:
                page.set_cropbox(pymupdf.Rect(24, 18, 570, 800))
            pdf.save(self.path)

    def test_recovers_typed_fields_and_boxes_on_a_cropped_page(self):
        self.write_page([(53, 48, "Wellbore: 32/5-C 9"), (53, 62, "Report number: 26"),
                         (53, 76, "Spud: 2024-11-01"), (53, 90, "Operations Summary"),
                         (53, 104, "DAILY COST $5,124")], crop=True)
        _, fields = source_fields(source_page(self.path, 1, displayed_origin=True))
        self.assertEqual([(f["key"], f["value"]) for f in fields],
                         [("Wellbore:", "32/5-C 9"), ("Report number:", "26"), ("Spud:", "2024-11-01")])
        with pymupdf.open(self.path) as pdf:
            for field in fields:
                for part in ("key", "value"):
                    box = pymupdf.Rect(field[f"{part}_bbox"]) + (-1, -1, 1, 1)
                    self.assertEqual(pdf[0].get_textbox(box).strip(), field[part])

    def test_abstains_on_single_anchor_and_conflicting_report_aliases(self):
        for lines in (
            [(53, 48, "Well ID: Drywater 5"), (53, 62, "DAILY COST $5,124")],
            [(53, 48, "Well ID: Drywater 5"), (53, 62, "Report No: 35"),
             (53, 76, "Report number: 36")],
        ):
            with self.subTest(lines=lines):
                self.write_page(lines)
                self.assertEqual(source_fields(source_page(self.path, 1))[1], [])

    def test_unclassified_pdf_needs_an_explicit_title_or_dated_report_identity(self):
        identifiers = [(53, 48, "Well ID: Drywater 5"), (53, 62, "Report No: 35")]
        self.write_page(identifiers)
        self.assertEqual(source_fields(source_page(self.path, 1), require_signature=True)[1], [])
        for extra in ((53, 32, "Daily Drilling Report"), (53, 76, "Report Date: 2024-11-01")):
            with self.subTest(extra=extra):
                self.write_page(identifiers + [extra])
                _, fields = source_fields(source_page(self.path, 1), require_signature=True)
                self.assertEqual([f["value"] for f in fields[:2]], ["Drywater 5", "35"])

    def test_adds_missing_complete_values_and_preserves_existing_form_fields(self):
        self.write_page([(53, 48, "Well ID: Drywater 5"), (53, 62, "Report No: 35"),
                         (53, 76, "Spud: 2024-11-01"), (53, 90, "DAILY COST $124")])
        prior = {"page": 1, "fields": [{"key": "Report No:", "value": "35"}], "header_boundary": 100}
        pages = [{"page": 1, "mode": "text"}]
        chunks = {1: "Well ID: Drywater 5\nDAILY COST $124.50"}
        merged = recover_fields(self.path, pages, [prior], chunks, 0.4)
        self.assertEqual([(f["key"], f["value"]) for f in merged[0]["fields"]],
                         [("Report No:", "35"), ("Spud:", "2024-11-01"), ("DAILY COST", "$124")])
        self.assertEqual(len(prior["fields"]), 1)
        self.assertEqual(recover_fields(self.path, pages, [prior], chunks, 0.4, stacked_pages={1}), [prior])
        for entry in ({"page": 1, "mode": "ocr"}, {"page": 1}):
            self.assertEqual(recover_fields(self.path, [entry], [prior], chunks, 0.4), [prior])

    def test_standard_config_enables_source_report_fields(self):
        self.assertTrue(load_k1_config(STANDARD_24NOV)["forms"]["missing_report_fields"])


if __name__ == "__main__":
    unittest.main()
