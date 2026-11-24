"""Source-ruled panel extraction and independent position evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pymupdf

from graph_builder.corpus.ruled_panels import read_page
from graph_builder.corpus.text_layer import source_page


class RuledPanelTests(unittest.TestCase):
    def test_numbered_bha_tool_lengths_stop_before_summary_measurements(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "report.pdf"
            with pymupdf.open() as pdf:
                page = pdf.new_page(width=420, height=300)
                page.insert_text((45, 29), "Ran BHA # 73 downhole")
                page.insert_text((76, 65), "BHA # 8")
                rows = [["TOOL", "LENGTH (m)"], ["Motor", "7.76"], ["Float Sub", "0.68"],
                        ["BHA LENGTH", "8.44"], ["HOOK LOAD", "145.00"]]
                for index in range(len(rows) + 1):
                    y = 70 + 20 * index
                    page.draw_line((40, y), (165, y))
                    page.draw_line((165, y), (282, y))
                page.draw_line((40, 70), (282, 70))
                for x in (40, 165, 282):
                    page.draw_line((x, 70), (x, 170))
                for index, (label, value) in enumerate(rows):
                    page.insert_text((46, 84 + 20 * index), label, fontsize=9)
                    page.insert_text((172, 84 + 20 * index), value, fontsize=9)
                pdf.save(path)
            (_, table), = read_page(source_page(path, 1, displayed_origin=True), ["bha"])
            self.assertEqual(table["caption"], "BHA # 8")
            self.assertEqual(table["grid"], rows[:3])

    def test_well_caption_preserves_two_distinct_depths_and_rejects_partial_panels(self):
        from graph_builder.corpus.ruled_panels import independently_readable

        rows = [["Country/Area", "USA / Milford, UT"], ["Well Name", "56-32"],
                ["Planned Depth", "9,000 ft"], ["Actual Depth", "9,105 ft at 2.99 degrees"]]
        for bad_label in (False, True):
            with self.subTest(bad_label=bad_label), TemporaryDirectory() as directory:
                path = Path(directory) / "summary.pdf"
                with pymupdf.open() as pdf:
                    page = pdf.new_page(width=560, height=420)
                    page.insert_text((50, 60), "Table 3: 56-32 Well Information")
                    for index in range(5):
                        page.draw_line((42, 65 + index * 24), (515, 65 + index * 24))
                    for x in (42, 200, 515):
                        page.draw_line((x, 65), (x, 161))
                    for index, (label, value) in enumerate(rows):
                        page.insert_text((49, 80 + index * 24), "Next section" if bad_label and index == 3 else label)
                        page.insert_text((207, 80 + index * 24), value)
                    pdf.save(path)
                (_, panel), = read_page(source_page(path, 1, displayed_origin=True), ["well_summary"])
                if bad_label:
                    self.assertIsNone(panel)
                else:
                    self.assertEqual(panel["grid"][1:], rows)
                    with pymupdf.open(path) as pdf:
                        self.assertTrue(independently_readable(panel, pdf[0].get_text("words", sort=True)))

    def test_typed_panel_layouts_and_position_of_each_numeric_cell(self):
        cases = {
            "survey": ("SURVEY DATA", [["MD", "Inclination", "Azimuth"], ["1200", "1.25", "45"], ["1210", "2.50", "47"]]),
            "bha": ("BHA DATA", [["Item", "Amt", "ID/OD", "Length"], ["Bit", "1", '8"', "0.28"], ["Collar", "1", '6"', "9.2"]]),
            "inventory": ("BULK INVENTORY", [["Item Type", "Used", "On Hand"], ["Diesel", "477", "6,220"]]),
            "pump": ("PUMP DATA", [["Pump No", "1", "2"], ["Model", "NF-500", "NF-500"],
                                    ["Pressure (psi)", "", "1,200"], ["GPM", "165", ""]]),
            "bit": ("BIT DATA", [["Bit No", "2"], ["Size", '8-1/2"'], ["Depth Out", ""]]),
            "formation_depths": ("FORMATION DEPTHS (mKB)", [["NAME", "ESTIMATED", "ACTUAL"],
                                                               ["Upper Sand", "6.67", "7.00"], ["Lower Sand", "", "unknown"]]),
            "well_summary": ("WELL INFORMATION", [["Total Depth (ft)", "3,280"], ["Casing Shoe MD (ft)", "704.47"]]),
        }
        with TemporaryDirectory() as folder:
            for kind, (title, expected) in cases.items():
                with self.subTest(kind=kind):
                    path = Path(folder) / f"{kind}.pdf"
                    with pymupdf.open() as pdf:
                        page = pdf.new_page(width=600, height=400)
                        page.insert_text((47, 65), title)
                        right = 40 + 125 * len(expected[0])
                        for index in range(len(expected) + 1):
                            y = 70 + 20 * index
                            page.draw_line((40, y), (right, y))
                        for index in range(len(expected[0]) + 1):
                            x = 40 + 125 * index
                            page.draw_line((x, 70), (x, 70 + 20 * len(expected)))
                        for row, values in enumerate(expected):
                            for column, text in enumerate(values):
                                page.insert_text((47 + 125 * column, 84 + 20 * row), text, fontsize=9)
                        pdf.save(path)
                    (_, table), = read_page(source_page(path, 1, displayed_origin=True), [kind])
                    field_panel = kind in ("bit", "well_summary")
                    self.assertEqual(table["grid"][int(field_panel):], expected)
                    with pymupdf.open(path) as pdf:
                        for values, boxes in zip(table["grid"], table["cell_boxes"]):
                            for value, box in zip(values, boxes):
                                if box:
                                    text = pdf[0].get_textbox(pymupdf.Rect(box) + (-1, -1, 1, 1)).strip()
                                    self.assertEqual(text, value)
