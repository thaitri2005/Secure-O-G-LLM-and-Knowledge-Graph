from __future__ import annotations

import unittest

from graph_builder.corpus.aligned_grids import read_panels
from graph_builder.corpus.scan_grids import broken_rulings, scan_rulings
from graph_builder.corpus.split_rows import fragment_column


class EvidenceTableRecoveryTests(unittest.TestCase):
    def test_alignment_keeps_prose_outside_a_measurement_grid(self):
        grid = [["Elapsed", "Pressure", "Volume"], ["1:00", "-12.65", "310"], ["2:00", "-12.50", "315"],
                ["3:00", "-10.00", "328"], ["4:00", "-9.05", "341"]]
        words = [("Notes outside the table", [20, 10, 140, 20])]
        for r, row in enumerate(grid):
            for c, text in enumerate(row):
                x, y = 20 + c * 110, 42 + r * 16
                words.append((text, [x, y, x + len(text) * 5, y + 10]))
        panel, = read_panels(words, words)
        self.assertEqual(panel["grid"], grid)
        self.assertEqual(list(read_panels(words, [*words[:-1], ("342", words[-1][1])])), [])
        self.assertEqual(list(read_panels(words[4:], words[4:])), [])

    def test_fragment_needs_quantitative_anchors_and_continuing_prose(self):
        left = [["1", "Inspection began", "120"], ["2", "Seal calibrated", "140"],
                ["3", "The operators measured", "150"]]
        right = [["", "the remaining travel", ""], ["4", "Condition normal", "155"], ["5", "Core confirmed", "165"]]
        self.assertEqual(fragment_column(left, right), 1)
        self.assertEqual(fragment_column([row[::-1] for row in left], [row[::-1] for row in right]), 1)
        self.assertEqual(fragment_column([row[1:] + row[:1] for row in left], [row[1:] + row[:1] for row in right]), 0)
        self.assertIsNone(fragment_column([*left[:-1], ["3", "The operators measured.", "150"]], right))
        self.assertIsNone(fragment_column(left, [["6", "the remaining travel", ""], *right[1:]]))

    def test_repair_requires_original_ruling_ink_in_both_directions(self):
        import cv2
        import numpy as np

        image = np.full((500, 620), 241, dtype=np.uint8)
        for y in (100, 165, 230, 295, 360):
            cv2.line(image, (40, y), (560, y), 95, 2)
        for x in (40, 220, 390, 560):
            cv2.line(image, (x, 100), (x, 360), 95, 2)
            for y in (131, 196, 261, 326):
                image[y:y + 8, x - 3:x + 4] = 241
        self.assertEqual(scan_rulings(image)[1], [])
        self.assertTrue(any((rows, cols) == (4, 3) for rows, cols, _ in broken_rulings(image)[1]))
        image[:, 385:396] = 241
        self.assertFalse(any(cols == 3 for _, cols, _ in broken_rulings(image)[1]))
