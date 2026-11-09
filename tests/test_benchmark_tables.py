"""Small tests of the matching and normalisation functions of scripts/benchmark_tables.py (A-501)."""

import collections
import importlib.util
import sys
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("benchmark_tables", Path(__file__).resolve().parents[1] / "scripts" / "benchmark_tables.py")
bt = importlib.util.module_from_spec(_SPEC)
sys.modules["benchmark_tables"] = bt
_SPEC.loader.exec_module(bt)


class NormalisationTests(unittest.TestCase):
    def test_dashes_case_whitespace(self):
        self.assertEqual(bt.normalize_text("  8.6 \u2013  9.2\nFT "), "8.6 - 9.2 ft")
        self.assertEqual(bt.normalize_text(None), "")

    def test_clean_grid_is_rectangular(self):
        self.assertEqual(bt.clean_grid([["A"], ["b", None, "c"]]), [["a", "", ""], ["b", "", "c"]])

    def test_f1(self):
        a, b = collections.Counter("x y z".split()), collections.Counter("x y w".split())
        score = bt.f1_from_counters(a, b)
        self.assertAlmostEqual(score["f1"], 2 / 3)
        self.assertEqual(bt.f1_from_counters(collections.Counter(), collections.Counter())["f1"], None)


class MatchingTests(unittest.TestCase):
    def test_iou(self):
        self.assertEqual(bt.iou([0, 0, 10, 10], [0, 0, 10, 10]), 1.0)
        self.assertEqual(bt.iou([0, 0, 10, 10], [20, 20, 30, 30]), 0.0)
        self.assertAlmostEqual(bt.iou([0, 0, 10, 10], [5, 0, 15, 10]), 1 / 3)

    def test_greedy_one_to_one(self):
        truths = [{"_score": (lambda box: lambda p: bt.iou(box, p["bbox"]))(b)} for b in ([0, 0, 10, 10], [20, 0, 30, 10])]
        preds = [{"bbox": [0, 0, 10, 10]}, {"bbox": [1, 0, 11, 10]}]
        self.assertEqual([(i, j) for i, j, _ in bt.match_tables(truths, preds, 0.5)], [(0, 0)])  # second truth stays unmatched

    def test_threshold(self):
        truths = [{"_score": lambda p: 0.4}]
        self.assertEqual(bt.match_tables(truths, [{}], 0.5), [])


class GridScoreTests(unittest.TestCase):
    TRUTH = [["Name", "Depth"], ["A", "10"], ["B", "20"]]

    def test_perfect(self):
        s = bt.grid_scores(self.TRUTH, self.TRUTH, 1)
        self.assertTrue(s["row_exact"] and s["col_exact"] and s["header_ok"])
        self.assertEqual((s["positional_cells"], s["truth_cells"], s["token_f1"]), (6, 6, 1.0))

    def test_swapped_cells_keep_set_but_not_position(self):
        pred = [["Name", "Depth"], ["A", "20"], ["B", "10"]]
        s = bt.grid_scores(self.TRUTH, pred, 1)
        self.assertEqual(s["set_hits"], 6)
        self.assertEqual(s["positional_cells"], 4)

    def test_no_header_rows_gives_none(self):
        self.assertIsNone(bt.grid_scores(self.TRUTH, self.TRUTH, 0)["header_ok"])

    def test_leading_row_offset_only_when_allowed(self):
        pred = [["Title", ""]] + self.TRUTH
        self.assertEqual(bt.grid_scores(self.TRUTH, pred, 1)["positional_cells"], 0)
        s = bt.grid_scores(self.TRUTH, pred, 1, offsets=(0, 1))
        self.assertEqual((s["offset"], s["positional_cells"]), (1, 6))

    def test_missing_prediction(self):
        s = bt.grid_scores(self.TRUTH, [], 1)
        self.assertEqual((s["positional_cells"], s["set_hits"]), (0, 0))

    def test_spacing_loss_detected_by_nospace_metric(self):
        s = bt.grid_scores([["Alaska Energy"]], [["AlaskaEnergy"]], 0)
        self.assertEqual((s["set_hits"], s["set_hits_nospace"]), (0, 1))

    def test_row_text_exact_is_order_sensitive(self):
        truth_rows = bt.row_text_sequences([["0:00", "1:00", "x"]])
        self.assertEqual(bt.row_text_exact(truth_rows, [["0:00", "1:00", "", "x"]]), 1)
        self.assertEqual(bt.row_text_exact(truth_rows, [["x", "0:00", "1:00"]]), 0)


class ApplicabilityTests(unittest.TestCase):
    def test_declared_capabilities_only(self):
        lattice, text, custom = bt.CANDIDATES["C4a_camelot_lattice"], bt.CANDIDATES["C4b_camelot_stream"], bt.CANDIDATES["C6_custom_ops"]
        self.assertEqual(bt.applicability(lattice, {"ruled": False})[0], "NOT_APPLICABLE")
        self.assertEqual(bt.applicability(lattice, {"ruled": True})[0], "EVALUATED")
        self.assertEqual(bt.applicability(text, {"ruled": False})[0], "EVALUATED")
        self.assertEqual(bt.applicability(custom, {"kind": "other", "ruled": True})[0], "NOT_APPLICABLE")
        self.assertEqual(bt.applicability(custom, {"kind": "ops"})[0], "EVALUATED")
        self.assertEqual(bt.applicability(text, {"text_chars": 0})[0], "NOT_APPLICABLE")

    def test_percentile_and_hash_are_deterministic(self):
        self.assertEqual(bt.percentile([1, 2, 3, 4, 5], 0.95), 5)
        self.assertIsNone(bt.percentile([], 0.5))
        self.assertEqual(bt.canonical_hash({"b": 1, "a": 2}), bt.canonical_hash({"a": 2, "b": 1}))


if __name__ == "__main__":
    unittest.main()
