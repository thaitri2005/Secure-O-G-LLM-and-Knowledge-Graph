from copy import deepcopy
import json
import unittest

from scripts.benchmark_track_a_scan_cells import GOLD, score_case, score_grid


class ScanCellBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reference = json.loads(GOLD.read_text(encoding="utf-8"))
        cls.forge = next(case for case in reference["cases"] if case["id"] == "forge_temperature_track")
        cls.ozalpha = next(case for case in reference["cases"] if case["id"] == "ozalpha_approval_matrix")

    def test_source_transcription_scores_exactly(self):
        result = score_grid(self.forge, self.forge["rows"], 0)
        self.assertEqual(result["counts"]["correct_cells"], 24)
        self.assertEqual(result["counts"]["exact_rows"], 8)
        self.assertFalse(result["issues"])

    def test_exchanging_in_and_out_flags_wrong_columns(self):
        grid = deepcopy(self.forge["rows"])
        grid[4][1], grid[4][2] = grid[4][2], grid[4][1]
        result = score_grid(self.forge, grid, 0)
        self.assertEqual(result["counts"]["wrong_column"], 2)
        self.assertEqual(result["counts"]["correct_cells"], 22)

    def test_same_number_in_different_unit_is_wrong(self):
        grid = deepcopy(self.forge["rows"])
        grid[0][0] = "200 in"
        grid[0][1] = "68 °C"
        grid[0][2] = "71"
        result = score_grid(self.forge, grid, 0)
        self.assertEqual(result["counts"]["wrong_unit"], 3)
        self.assertEqual(result["counts"]["missing_row"], 0)

    def test_drop_and_duplicate_rows_do_not_shift_other_cells(self):
        grid = deepcopy(self.forge["rows"])
        grid.pop(3)
        grid.append(grid[-1])
        result = score_grid(self.forge, grid, 0)
        self.assertEqual(result["counts"]["missing_row"], 1)
        self.assertEqual(result["counts"]["missing_cell"], 3)
        self.assertEqual(result["counts"]["duplicate_row"], 1)
        self.assertEqual(result["counts"]["unexpected_cells"], 3)
        self.assertEqual(result["counts"]["exact_rows"], 7)

    def test_wrong_row_and_changed_order_are_distinct(self):
        grid = deepcopy(self.forge["rows"])
        grid[4][1], grid[5][1] = grid[5][1], grid[4][1]
        self.assertEqual(score_grid(self.forge, grid, 0)["counts"]["wrong_row"], 2)
        grid = self.forge["rows"][::-1]
        result = score_grid(self.forge, grid, 0)
        self.assertEqual(result["counts"]["correct_cells"], 24)
        self.assertFalse(result["ordered_rows"])
        self.assertEqual(result["counts"]["row_order_changed"], 1)

    def test_known_blank_and_unscored_handwriting_have_distinct_semantics(self):
        grid = [self.ozalpha["header"], *deepcopy(self.ozalpha["rows"])]
        grid[1][1] = "7"
        grid[2][4] = "Signature beyond scope"
        result = score_grid(self.ozalpha, grid, 1)
        self.assertEqual(result["counts"]["unexpected_cells"], 1)
        self.assertEqual(result["counts"]["correct_blank_cells"], 4)
        self.assertEqual(result["counts"]["correct_cells"], 15)

    def test_correct_values_from_another_region_are_not_accepted(self):
        table = {"pages": [1], "table_id": "nearby", "header_rows": 0, "grid": self.forge["rows"],
                 "regions": [{"page": 1, "bbox": [101, 500, 418, 740]}]}
        self.assertEqual(score_case(self.forge, [table], 1)["table_status"], "table_missing")
        table["regions"][0]["bbox"] = self.forge["bbox"]
        self.assertTrue(score_case(self.forge, [table], 1)["exact_pass"])
        duplicate = dict(table, table_id="overlapping")
        self.assertEqual(score_case(self.forge, [table, duplicate], 1)["table_status"], "ambiguous_region")
