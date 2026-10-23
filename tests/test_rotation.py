"""Check the strict rotation acceptance gate and inverse coordinates."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from docling_core.types.doc import BoundingBox
from graph_builder.ingestion.rotation import improves, restore_box, table_score, retry_rotated_tables
from graph_builder.ingestion.sources import write_json
from test_chunking import make_document, add_table


class RotationTests(unittest.TestCase):
    def test_cached_retry_inserts_replacement_with_original_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            pdf = directory / "source.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=600, height=1000)
            writer.write(pdf)
            original = make_document(1)
            add_table(original, rows=1)
            rotated = make_document(1)
            add_table(rotated)
            write_json(directory / "page_1.json", rotated.export_to_dict())
            with patch("graph_builder.ingestion.rotation.table_score", side_effect=[{"cells": 1, "word_recall": .2}, {"cells": 3, "word_recall": .8}]):
                result, report = retry_rotated_tables(original, pdf, directory, {})
            self.assertTrue(report[0]["accepted"])
            self.assertEqual(len(result.tables), 1)
            self.assertEqual(result.tables[0].data.num_rows, 3)
            self.assertEqual(original.tables[0].data.num_rows, 1)
    def test_both_metrics_must_improve(self):
        before = {"cells": 2, "word_recall": .5}
        self.assertTrue(improves(before, {"cells": 3, "word_recall": .6}))
        self.assertFalse(improves(before, {"cells": 2, "word_recall": .6}))
        self.assertFalse(improves(before, {"cells": 3, "word_recall": .5}))

    def test_inverse_clockwise_coordinates(self):
        box = restore_box(BoundingBox(l=700, t=100, r=800, b=200), 1000, 600)
        self.assertEqual([box.l, box.t, box.r, box.b], [100, 200, 200, 300])

    def test_table_score_counts_populated_cells(self):
        table = add_table(make_document())
        self.assertEqual(table_score([table], "Column Row 1 Row 2"), {"cells": 3, "word_recall": 1.0})
