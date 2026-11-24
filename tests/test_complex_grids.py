from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pymupdf

from graph_builder.corpus.ruled_geometry import cell_slots, conservative_replacement
from graph_builder.corpus.source_grids import table_panels


class ComplexGridTests(unittest.TestCase):
    def test_a_span_grid_requires_every_slot_to_have_one_owner(self):
        self.assertIsNone(cell_slots([(0, 0, 10, 10), (10, 0, 20, 10), (0, 10, 10, 20)]))
        self.assertIsNone(cell_slots([(0, 0, 20, 10), (10, 0, 20, 20), (0, 10, 10, 20)]))
        _, _, owners = cell_slots([(0, 0, 20, 10), (0, 10, 10, 20), (10, 10, 20, 20)])
        self.assertEqual(owners[0][:4], (0, 0, 1, 2))

    def test_boxed_prose_with_numbers_is_not_a_data_grid(self):
        panel = {"grid": [["Activity", "", "Observations"], ["Circulation", "", "Kept circulating for 2 hours."]],
                 "header_rows": 1}
        with patch("graph_builder.corpus.complex_grids.panels", return_value=[(None, panel)]):
            self.assertEqual(list(table_panels(None, None, True)), [])

    def test_repeated_markdown_heading_is_allowed_only_for_a_recorded_span(self):
        from graph_builder.corpus.ops_tables import grid_table_record, table_chunks

        box = [20, 40, 240, 160]
        old = grid_table_record("old", "sample", "#/tables/0", 1, box,
                                [["Location Pressure"] * 3, ["First", "50", "17 psi"]])
        head, *body = old["cells"][:1] + old["cells"][3:]
        old["cells"] = [dict(head, col_span=3), *body]
        panel = grid_table_record("new", "sample", "ocr:scan_grid:p1:1", 1, box,
                                  [["Location", "", "Pressure"], ["First", "50", "17 psi"]])
        panel["bbox"] = box
        chunks = table_chunks(old, dict(doc_id="sample", section=None, section_path=[], quality="ok", ocr=True), 1500)
        self.assertIsNotNone(conservative_replacement(panel, old, chunks, 1, ocr=True))
        old["cells"][0]["col_span"] = 1
        self.assertIsNone(conservative_replacement(panel, old, chunks, 1, ocr=True))

    def test_rotated_table_reads_its_printed_spans_and_keeps_the_displayed_bbox(self):
        with TemporaryDirectory() as folder, pymupdf.open() as original:
            page = original.new_page(width=400, height=300)
            for x, start in ((25, 35), (125, 65), (225, 35), (325, 35)):
                page.draw_line((x, start), (x, 145))
            for y in (35, 65, 105, 145):
                page.draw_line((25, y), (325, y))
            for y, row in ((55, ["Interval", "", "Pressure"]), (90, ["First", "50", "10 psi"]),
                           (130, ["Next", "123", "17 psi"])):
                for x, value in zip((35, 135, 235), row, strict=True):
                    if value:
                        page.insert_text((x, y), value)
            for angle in (0, 90, 180, 270):
                with self.subTest(angle=angle), pymupdf.open() as rotated:
                    target = Path(folder) / f"input-{angle}.pdf"
                    width, height = (300, 400) if angle % 180 else (400, 300)
                    view = rotated.new_page(width=width, height=height)
                    view.show_pdf_page(view.rect, original, 0, rotate=angle)
                    rotated.save(target)
                    panel, = table_panels(target, view, True)
                    self.assertEqual(panel["grid"], [["Interval", "", "Pressure"], ["First", "50", "10 psi"],
                                                     ["Next", "123", "17 psi"]])
                    self.assertEqual(panel["cells"][0]["col_span"], 2)
                    self.assertIsNone(panel["cell_boxes"][0][1])
                    self.assertTrue(view.rect.contains(pymupdf.Rect(panel["bbox"])))

    def test_raster_rulings_prove_a_span_from_enclosed_cell_borders(self):
        import cv2
        import numpy as np
        from graph_builder.corpus.scan_grids import scan_rulings

        raster = np.full((320, 440), 232, dtype=np.uint8)
        for x, top in ((30, 30), (170, 90), (310, 30), (410, 30)):
            cv2.line(raster, (x, top), (x, 270), 180, 2)
        for y in (30, 90, 150, 210, 270):
            cv2.line(raster, (30, y), (410, y), 180, 2)
        _, shapes = scan_rulings(raster)
        (rows, columns, owners), = shapes
        self.assertEqual((rows, columns), (4, 3))
        self.assertEqual(owners[0][3], 2)

    def test_scan_deskew_uses_both_ruling_axes(self):
        import cv2
        import numpy as np
        from graph_builder.corpus.scan_grids import deskew, scan_rulings

        original = np.full((420, 600), 255, dtype=np.uint8)
        for x in (40, 200, 360, 540):
            cv2.line(original, (x, 40), (x, 355), 70, 2)
        for y in (40, 115, 195, 275, 355):
            cv2.line(original, (40, y), (540, y), 70, 2)
        rotation = cv2.getRotationMatrix2D((300, 210), 1.8, 1)
        skewed = cv2.warpAffine(original, rotation, (600, 420), borderValue=255)
        corrected, _ = deskew(skewed)
        self.assertTrue(any((rows, cols) == (4, 3) for rows, cols, _ in scan_rulings(corrected)[1]))
