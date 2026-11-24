"""Ensure reconstructed daily logs keep row and page ownership."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pymupdf

from graph_builder.corpus.daily_log import DESCRIPTION, RULE, assemble, joins, read_page


class DailyLogTests(unittest.TestCase):
    @staticmethod
    def draw(pdf, name, page_number, top, rows):
        page = pdf.new_page(width=600, height=760)
        page.insert_text((55, 30), f"{name} Well Completion Report")
        page.insert_text((55, 731), f"Final Page {page_number} of 3", fontsize=9)
        edges = [40, 144, 217, 342, 560]
        bottom = top + 45 * len(rows)
        for x in edges:
            page.draw_line((x, top), (x, bottom), width=.7)
        for r in range(len(rows) + 1):
            y = top + 45 * r
            page.draw_line((edges[0], y), (edges[-1], y), width=.7)
        for r, row in enumerate(rows):
            for x, value in zip(edges, row):
                page.insert_text((x + 5, top + 15 + r * 45), value, fontsize=9)

    def test_verified_split_with_another_body_row_and_same_header_on_a_different_well(self):
        header = ["Report Date", "Report #", "Midnight Depth (m)", "24-hour Summary"]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.pdf"
            with pymupdf.open() as pdf:
                self.draw(pdf, "Tailwell 8", 1, 540, [header, ["2 Jul 2024", "41", "1220.0", "Circulated at 45 psi."]])
                self.draw(pdf, "Tailwell 8", 2, 80, [header, ["", "", "", "Returns stayed clear."],
                                                   ["3 Jul 2024", "42", "1230.0", "Continued coring."]])
                self.draw(pdf, "Otherwell 5", 3, 80, [header, ["4 Jul 2024", "43", "1230.0", "Set casing."]])
                pdf.save(path)
            with pymupdf.open(path) as pdf:
                first, second, unrelated = [read_page(path, page, n) for n, page in enumerate(pdf, 1)]
        self.assertTrue(joins(first, second, {}))
        moved = deepcopy(second)
        moved.page = 2
        moved.identity = unrelated.identity
        self.assertFalse(joins(first, moved, {}))
        self.assertFalse(joins(first, second, {1: {"well": "A"}, 2: {"well": "B"}}))
        template = {"doc_id": "test", "section": None, "section_path": [], "ocr": False, "quality": "ok"}
        table, pieces = assemble([first, second], "test", "log", template, 1500, rule=RULE, description_column=DESCRIPTION)
        self.assertEqual(table["grid"][1][3], "Circulated at 45 psi. Returns stayed clear.")
        self.assertEqual([part["row_start"] for part in table["verified_parts"]], [0, 1])
        self.assertEqual([(piece["pages"], piece["row_start"], piece["row_end"]) for piece in pieces], [([1, 2], 1, 2), ([2], 2, 3)])
        self.assertEqual(pieces[0]["source_spans"][1]["page"], 2)
        self.assertIn("Returns stayed clear.", pieces[0]["text"][pieces[0]["source_spans"][1]["start"]:])
