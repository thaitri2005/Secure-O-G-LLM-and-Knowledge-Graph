import unittest
from unittest.mock import patch

import numpy as np

from graph_builder.corpus.scan_bands import agree_in_shared_cells, periodic_bands, refine_lanes
from graph_builder.corpus.scan_grids import tess_words


class SparseScanTests(unittest.TestCase):
    def test_repeated_segments_propose_lanes_but_continuous_rules_do_not(self):
        mask = np.zeros((300, 500), dtype=np.uint8)
        for y in (70, 90, 110, 130, 150):
            for start in (26, 144, 219, 290, 372, 429):
                mask[y:y + 2, start:start + 38] = 255
        bands, = periodic_bands(mask)
        self.assertEqual(bands.edges, (71, 91, 111, 131, 151))
        self.assertEqual(len(bands.lanes), 6)
        mask[mask.any(axis=1), 26:467] = 255
        self.assertEqual(list(periodic_bands(mask)), [])

    def test_hard_ruling_cannot_split_located_print(self):
        lanes = ((10, 50), (50, 100), (100, 150), (150, 200))
        words = [("Pressure", [36, 18, 74, 41]), ("7", [93, 51, 108, 65]), ("Loss", [145, 20, 152, 39])]
        self.assertEqual(refine_lanes(lanes, words), ((10, 100), (100, 150), (150, 200)))

    def test_rotating_a_crop_cannot_confirm_conflicting_values_in_the_same_cell(self):
        def panel(value, box):
            return {"grid": [[], ["Test:", value]], "cell_boxes": [[], [[0, 0, 40, 10], box]]}

        first = panel("-15.0", [40, 0, 80, 10])
        self.assertTrue(agree_in_shared_cells(first, panel("−15.0", [42, 0, 82, 10])))
        self.assertFalse(agree_in_shared_cells(first, panel("15.0", [42, 0, 82, 10])))
        self.assertTrue(agree_in_shared_cells(first, panel("15.0", [80, 0, 120, 10])))

    def test_tesseract_tsv_preserves_literal_quote_and_following_cells(self):
        raw = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
               '5\t1\t1\t1\t1\t1\t1\t2\t3\t4\t96\t"\n'
               '5\t1\t1\t1\t1\t2\t6\t2\t4\t4\t92\t27.5\n')
        with patch("graph_builder.corpus.scan_grids.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = raw.encode()
            self.assertEqual(tess_words("tesseract", np.zeros((40, 40), dtype=np.uint8)),
                             [('"', [1, 2, 4, 6]), ("27.5", [6, 2, 10, 6])])
