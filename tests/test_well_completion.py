from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pymupdf

from graph_builder.corpus import well_completion


class WellCompletionTests(unittest.TestCase):
    def test_reads_adjacent_cells_across_two_field_columns(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "well.pdf"
            with pymupdf.open() as pdf:
                page = pdf.new_page()
                page.insert_text((42, 82), "Well Summary", fontsize=11)
                for y in (90, 114, 138, 162):
                    page.draw_line((40, y), (470, y))
                for x in (40, 145, 235, 370, 470):
                    page.draw_line((x, 90), (x, 162))
                for row, cells in enumerate((("Well Name", "QA-17", "Well Profile", "Vertical"),
                                             ("GL Elevation", "18.5 m", "Hole Size", "8.5 in"),
                                             ("Latitude", "", "Mud Weight", "9.3 ppg"))):
                    for x, text in zip((46, 151, 241, 376), cells, strict=True):
                        page.insert_text((x, 106 + 24 * row), text, fontsize=10)
                pdf.save(source)
            with pymupdf.open(source) as pdf:
                panels = well_completion.read_page(source, pdf[0], 1)
            self.assertEqual(len(panels), 1)
            title, _, pairs = panels[0]
            self.assertEqual(title, "Well Summary")
            self.assertEqual([row for row, _ in pairs], [["Well Name", "QA-17"], ["Well Profile", "Vertical"],
                                                        ["GL Elevation", "18.5 m"], ["Hole Size", "8.5 in"],
                                                        ["Mud Weight", "9.3 ppg"]])
            for _, (label, value) in pairs:
                self.assertLess(label[2], value[0])
