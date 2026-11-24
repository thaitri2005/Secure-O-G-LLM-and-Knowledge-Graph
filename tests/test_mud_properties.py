"""Two ruled panel layouts, including a blank reading, and hard geometry negatives."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pymupdf

from graph_builder.corpus.mud_properties import read_page
from graph_builder.corpus.text_layer import source_page


class MudPropertiesTests(unittest.TestCase):
    def read(self, readings, *, broken=False, duplicate_title=False):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "panel.pdf"
            with pymupdf.open() as pdf:
                page = pdf.new_page(width=500, height=400)
                page.insert_text((210, 77), "MUD PROPERTIES", fontsize=9)
                if duplicate_title:
                    page.insert_text((210, 220), "MUD PROPERTIES", fontsize=9)
                page.insert_text((72, 77), "BIT DATA", fontsize=9)
                boundaries = [200, 302, 368, 430] if len(readings[0]) == 3 else [200, 321, 430]
                for x in boundaries:
                    if not broken or x in (200, 430):
                        page.draw_line((x, 80), (x, 80 + 15 * len(readings)))
                for index in range(len(readings) + 1):
                    y = 80 + index * 15
                    page.draw_line((200, y), (430, y))
                for index, row in enumerate(readings):
                    for x, value in zip(boundaries, row):
                        page.insert_text((x + 6, 91 + index * 15), value, fontsize=9)
                    page.insert_text((165, 91 + index * 15), "777", fontsize=9)
                page.insert_text((207, 94 + 15 * len(readings)), "SURVEY DATA", fontsize=9)
                pdf.save(path)
            return read_page(source_page(path, 1, displayed_origin=True))

    def test_parent_heading_and_neighbors_do_not_enter_value_columns(self):
        one = [["Mud Weight", "8.9ppg"], ["Visc", "46sec"], ["Gels", "*6 / 8"], ["Hardness", "120"]]
        two = [["Density (ppg)", "8.45", "9.05"], ["Viscosity (sec)", "106", "74"],
               ["Gels (10s/m)", "", "21 / 31"], ["Sand (% Vol)", "tr", "2.0"]]
        for rows in (one, two):
            with self.subTest(columns=len(rows[0])):
                result = self.read(rows)
                self.assertEqual(result["grid"][1:], rows)
                for row, boxes in zip(rows, result["cell_boxes"][1:]):
                    self.assertEqual([bool(box) for box in boxes], [bool(value) for value in row])
                    self.assertEqual([box[0] for box in boxes if box], sorted(box[0] for box in boxes if box))

    def test_abstains_on_missing_dividers_multiple_panels_or_invalid_values(self):
        rows = [["Mud Weight", "8.9ppg"], ["Visc", "46sec"], ["Gels", "*6 / 8"], ["Hardness", "120"]]
        self.assertIsNone(self.read(rows, broken=True))
        self.assertIsNone(self.read(rows, duplicate_title=True))
        self.assertIsNone(self.read([*rows[:3], ["Hardness", "Survey 120"]]))
