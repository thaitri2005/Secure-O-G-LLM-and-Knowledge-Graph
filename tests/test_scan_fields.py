from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pymupdf

from graph_builder.corpus import scan_fields


class ScanFieldTests(unittest.TestCase):
    def test_ambiguous_value_alignment_keeps_both_as_candidates(self):
        label = scan_fields.Line("Expiry date", [10, 0, 90, 12])
        other_column = scan_fields.Line("2025-12-01", [90, 14, 160, 26])
        dates = [scan_fields.Line("2025-12-02", [10, 13, 85, 25]),
                 scan_fields.Line("2025-12-03", [11, 18, 86, 30])]
        self.assertEqual(scan_fields.value_candidates(label, [other_column, *dates], "below", scan_fields.DATE, 200), dates)

    def test_exact_unit_must_survive_a_second_ocr_read(self):
        line = scan_fields.Line("200'-300′", [10, 0, 90, 12])
        with patch.object(scan_fields, "local_ocr", side_effect=['200"-300"', "200'-300'"]) as ocr:
            self.assertTrue(scan_fields.corroborates("ocr", None, line, 2))
            self.assertEqual(ocr.call_args.kwargs, {"prefilter": "enlarge"})
        with patch.object(scan_fields, "local_ocr", side_effect=['200"-300"', '200300"', "200'-300'"]) as ocr:
            self.assertTrue(scan_fields.corroborates("ocr", None, line, 2))
            self.assertEqual(ocr.call_args.kwargs, {"prefilter": "adaptive"})
        with patch.object(scan_fields, "local_ocr", return_value='200"-300"'):
            self.assertFalse(scan_fields.corroborates("ocr", None, line, 2))
        with patch.object(scan_fields, "local_ocr", return_value="200'-800'") as ocr:
            self.assertFalse(scan_fields.corroborates("ocr", None, line, 2))
            ocr.assert_called_once()

    def test_ocr_strips_own_seam_text_once_and_require_multiple_regions(self):
        page = SimpleNamespace(rect=pymupdf.Rect(0, 0, 100, 500))
        seam = scan_fields.Line("seam text", [6, 196, 80, 204])
        deep = scan_fields.Line("later interval", [8, 495, 95, 505])
        with patch.object(scan_fields, "rapid_reader"), patch.object(scan_fields, "detected_lines") as detect:
            detect.side_effect = [[seam], [seam], [deep], [], []]
            recovered = scan_fields.tall_scan_chunks(page, Path("models"), "mud-log", 2, 200, 10)
            self.assertEqual([chunk["text"] for chunk in recovered], ["seam text", "later interval"])
            self.assertEqual([chunk["regions"][0]["bbox"] for chunk in recovered],
                             [[0, 100, 100, 200], [0, 200, 100, 300]])
            self.assertTrue(all(chunk["ocr"] and chunk["quality"] == "review" for chunk in recovered))

            detect.side_effect = [[seam], [seam], [], [], []]
            self.assertEqual(scan_fields.tall_scan_chunks(page, Path("models"), "mud-log", 2, 200, 1), [])
