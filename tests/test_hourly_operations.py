"""Check hourly log evidence, preserved neighboring content and template configuration."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pymupdf

from graph_builder.corpus.hourly_operations import repair_document
from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config


HEAD = ["From", "To", "[IADC Code] Description"]
BODY = [["22:00", "23:00", "[ 7 ] A pressure check"], ["23:00", "24:00", "[ 2 ] Finished drilling"]]


class HourlyOperationsTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "source.pdf"
        self.rule = load_k1_config()["table_rules"]["hourly_operations"]

    def write_source(self, rows=BODY, columns=HEAD, closed=True, title="Hourly Operations Summary 0000 to 2400"):
        with pymupdf.open() as doc:
            page = doc.new_page(width=600, height=600)
            page.draw_rect((100, 180, 540, 198), fill=(0.9, 0.9, 0.9))
            page.insert_text((210, 193), title, fontsize=9)
            for x in (100, 162, 220, 540):
                page.draw_line((x, 198), (x, 246))
            for y in (213, 230):
                page.draw_line((100, y), (540, y))
            page.draw_line((100 if closed else 220, 246), (540, 246))
            for y, row in zip((209, 226, 241), [columns, *rows]):
                for x, value in zip((113, 176, 225), row):
                    page.insert_text((x, y), value, fontsize=9)
            page.insert_text((115, 270), "Pumps 43", fontsize=9)
            doc.save(self.path)

    def export(self, box=None, old=None, stacked_pages=()):
        old = old if old is not None else ("From To [IADC Code] Description\n"
                                           "22:00 23:00 [ 7 ] A pressure check\n"
                                           "23:00 24:00 [ 2 ] Finished drilling")
        tables = [] if box is None else [{"table_id": "native", "regions": [{"page": 1, "bbox": box}],
                                         "cells": [{"text": old}]}]
        chunks = [{"table_id": "native" if tables else None, "page": 1, "pages": [1], "doc_id": "ordinary-name",
                   "section": None, "section_path": [], "ocr": False, "quality": "ok", "text": old}]
        return repair_document(self.path, [{"page": 1, "mode": "text"}], chunks, tables, "ordinary-name", "f1", 1500,
                               self.rule, stacked_pages=stacked_pages)

    def test_replaces_contained_native_grid_and_assigns_header_and_row_ranges(self):
        self.write_source()
        (chunk,), (table,), (finding,) = self.export([101, 199, 539, 245])
        self.assertEqual((table["table_id"], table["header_rows"], table["grid"]), ("native", 1, [HEAD, *BODY]))
        self.assertEqual((chunk["row_start"], chunk["row_end"]), (1, 3))
        self.assertEqual(chunk["source_spans"][0]["source_ref"], table["source_ref"])
        self.assertEqual(finding["action"], "replaced")

    def test_recovers_separate_grid_beside_compound_data_and_marks_overlap(self):
        self.write_source()
        (old_chunk, new_chunk), (compound, table), (finding,) = self.export([100, 160, 540, 285], "Pumps 43")
        self.assertEqual(compound["cells"][0]["text"], "Pumps 43")
        self.assertEqual((old_chunk["text"], old_chunk["quality"], new_chunk["quality"]), ("Pumps 43", "review", "ok"))
        self.assertEqual(table["grid"], [HEAD, *BODY])
        self.assertEqual(finding["overlapping_tables_for_review"], ["f1:t1"])

    def test_missing_boundaries_bad_clock_and_unrelated_heading_abstain(self):
        for variation in ({"closed": False}, {"rows": [["22:00", "23:90", "[ 7 ] A pressure check"], BODY[1]]},
                          {"title": "Please see Hourly Operations Summary in the appendix"}):
            with self.subTest(variation=variation):
                self.write_source(**variation)
                self.assertEqual(self.export()[1], [])
        self.write_source()
        self.assertEqual(self.export(stacked_pages={1})[1], [])

    def test_aliases_match_a_new_layout_without_changing_the_reader(self):
        names = ["Start", "End", "Activity"]
        template = {"id": "example-v1", "title": "Shift log", "columns": [[name] for name in names]}
        self.rule = dict(self.rule, templates=[template])
        self.write_source(columns=names, title="Shift log")
        _, (table,), (finding,) = self.export(old="Report summary")
        self.assertEqual(table["grid"], [names, *BODY])
        self.assertEqual(finding["template"], "example-v1")

    def test_config_rejects_duplicate_template_ids(self):
        config = load_k1_config()
        templates = config["table_rules"]["hourly_operations"]["templates"]
        templates.append(deepcopy(templates[0]))
        with self.assertRaisesRegex(ValueError, "distinct template ids"):
            validate_k1_config(config)


if __name__ == "__main__":
    unittest.main()
