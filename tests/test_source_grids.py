from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pymupdf

from graph_builder.corpus.source_grids import lossless_repair, repair_document


class SourceGridTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.pdf = Path(directory.name) / "arbitrary.pdf"
        self.grid = [["Stage", "Pressure (psi)", "Observation"],
                     ["Baseline", "-3.75", ""], ["Final", "15.2", "Stable"]]
        with pymupdf.open() as document:
            page = document.new_page(width=360, height=240)
            for x in (24, 100, 214, 333):
                page.draw_line((x, 35), (x, 137))
            for y in (35, 69, 103, 137):
                page.draw_line((24, y), (333, y))
            for y, row in zip((53, 87, 121), self.grid, strict=True):
                for x, value in zip((31, 109, 223), row, strict=True):
                    page.insert_text((x, y), value)
            document.save(self.pdf)

    def recover(self, tables=()):
        chunks = [{"pages": [1], "table_id": None, "type": "text", "text": "Original evidence"}]
        return repair_document(self.pdf, [{"page": 1, "mode": "text"}], chunks, list(tables), "arbitrary",
                               1500, lambda: self.fail("Expected no native table lookup"))

    def test_recovers_unclaimed_grid_and_keeps_source_passage(self):
        chunks, (table,), (finding,) = self.recover()
        self.assertEqual(table["grid"], self.grid)
        self.assertEqual(finding["action"], "recovered")
        self.assertEqual(chunks[0]["text"], "Original evidence")
        self.assertIn("| Baseline | -3.75 | |", chunks[1]["text"])

    def test_keeps_existing_verified_grid_and_refuses_reader_disagreement(self):
        existing = {"source_ref": "textlayer:other:p1:1", "table_id": "existing", "regions": [
            {"page": 1, "bbox": [24, 35, 333, 137]}]}
        _, tables, findings = self.recover([existing])
        self.assertEqual(tables, [existing])
        self.assertFalse(findings)
        with patch("graph_builder.corpus.source_grids.source_page", return_value={"words": []}):
            chunks, tables, findings = self.recover()
        self.assertEqual(len(chunks), 1)
        self.assertFalse(tables)
        self.assertEqual(findings[0]["reason"], "source_grid_readers_disagree")

    def test_repartition_requires_same_order_and_all_original_content(self):
        printed = self.grid
        native = [["Stage", "Pressure (psi) Observation"], ["Baseline", "-3.75"], ["Final", "15.2 Stable"]]
        self.assertTrue(lossless_repair(native, printed))
        split_glyphs = [["Sta ge", "Pressure (psi) Observation"], ["Baseline", "- 3.75"], ["Final", "15.2 Sta ble"]]
        self.assertTrue(lossless_repair(split_glyphs, printed))
        self.assertFalse(lossless_repair(printed, printed))
        self.assertFalse(lossless_repair([native[0], native[2], native[1]], printed))
        self.assertFalse(lossless_repair([*native[:2], ["Final", "15.2 Extra Stable"]], printed))
        self.assertFalse(lossless_repair([*native[:2], ["Final", "15.3 Stable"]], printed))
