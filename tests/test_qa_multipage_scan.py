"""Helper functions of scripts/qa_multipage_scan.py (A-108a): boundary tests, compatibility evidence, lookalikes."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("qa_multipage_scan", ROOT / "scripts" / "qa_multipage_scan.py")
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)
CFG = scan.load_config()
H = 800.0


def word(x0, y0, text="w", width=30.0, height=10.0):
    return (x0, y0, x0 + width, y0 + height, text)


def table(page, bbox, header, cols=None):
    return {"id": f"t{page}", "page": page, "bbox": bbox, "grid": [header, ["1"] * len(header)],
            "num_cols": cols or len(header), "num_rows": 2, "header_rows": 1}


class BoundaryTests(unittest.TestCase):
    def test_table_ending_page_body_with_only_footer_below(self):
        footer = [word(50, 780, "Page 1 of 2")]
        self.assertTrue(scan.ends_page_body([50, 600, 500, 740], footer, H, CFG)["ends"])

    def test_text_below_table_is_not_page_end(self):
        words = [word(50, 710, "Another section")]
        self.assertFalse(scan.ends_page_body([50, 600, 500, 700], words, H, CFG)["ends"])

    def test_large_gap_below_is_not_page_end(self):
        self.assertFalse(scan.ends_page_body([50, 100, 500, 300], [], H, CFG)["ends"])

    def test_table_starting_page_body(self):
        self.assertTrue(scan.starts_page_body([50, 70, 500, 200], [word(50, 20, "Header")], H, CFG)["starts"])

    def test_heading_above_table_blocks_start(self):
        self.assertFalse(scan.starts_page_body([50, 120, 500, 200], [word(50, 90, "Heading")], H, CFG)["starts"])

    def test_explicit_running_limit_skips_template_block(self):
        words = [word(50, 90, "Title block")]
        self.assertFalse(scan.starts_page_body([50, 120, 500, 200], words, H, CFG)["starts"])
        self.assertTrue(scan.starts_page_body([50, 120, 500, 200], [], H, CFG, limit=110.0)["starts"])


class CompatibilityTests(unittest.TestCase):
    def test_x_extent_relative_tolerance(self):
        self.assertTrue(scan.x_extent_match([50, 0, 550, 10], [51, 0, 549, 10], CFG)["match"])
        self.assertFalse(scan.x_extent_match([50, 0, 550, 10], [50, 0, 400, 10], CFG)["match"])

    def test_column_starts_and_match(self):
        words = []
        for row in range(5):
            for x in (50, 150, 300):
                words.append(word(x, 100 + row * 14, "c", width=20))
        bbox = [45, 95, 330, 175]
        starts = scan.column_starts(words, bbox, CFG)
        self.assertEqual([round(s) for s in starts], [50, 150, 300])
        self.assertTrue(scan.column_starts_match(starts, starts, 285.0, CFG)["match"])
        self.assertFalse(scan.column_starts_match(starts, starts[:2], 285.0, CFG)["match"])
        self.assertIsNone(scan.column_starts_match([], starts, 285.0, CFG)["match"])

    def test_first_row_shape(self):
        shape = scan.first_row_shape(["12:00", "1.5", "text"], CFG)
        self.assertAlmostEqual(shape["numeric_frac"], 2 / 3, places=2)

    def test_pair_boundaries_picks_last_and_first(self):
        a1, a2 = table(1, [0, 100, 10, 200], ["a"]), table(1, [0, 300, 10, 700], ["b"])
        b1, b2 = table(2, [0, 400, 10, 500], ["c"]), table(2, [0, 60, 10, 90], ["d"])
        a2["id"], b2["id"] = "a2", "b2"
        pairs = scan.pair_boundaries([a1, a2, b1, b2])
        self.assertEqual([(p[0]["id"], p[1]["id"]) for p in pairs], [("a2", "b2")])


class EvaluatePairTests(unittest.TestCase):
    def setUp(self):
        self.header = ["From", "To", "Code"]
        self.a = table(1, [50, 600, 550, 745], self.header)
        self.words_a = [word(50, 780, "footer")]

    def run_pair(self, b, words_b=()):
        return scan.evaluate_pair(self.a, b, self.words_a, list(words_b), H, H, CFG)

    def test_repeated_header_continuation_is_high_candidate(self):
        b = table(2, [50, 70, 550, 300], self.header)
        record = self.run_pair(b)
        self.assertEqual(record["kind"], "CANDIDATE")
        self.assertEqual(record["grade"], "HIGH")
        self.assertTrue(record["evidence"]["header_repeated"])

    def test_headerless_continuation_scores_lower(self):
        b = table(2, [50, 70, 550, 300], ["1", "2", "3"])
        record = self.run_pair(b)
        self.assertEqual(record["kind"], "CANDIDATE")
        self.assertFalse(record["evidence"]["header_repeated"])
        self.assertLess(record["score"], 1.0)

    def test_different_columns_is_lookalike_not_candidate(self):
        b = table(2, [50, 70, 550, 300], ["x", "y", "z", "w"])
        self.assertEqual(self.run_pair(b)["kind"], "LOOKALIKE")

    def test_heading_between_means_no_boundary(self):
        b = table(2, [50, 150, 550, 300], self.header)
        self.assertEqual(self.run_pair(b, [word(50, 100, "New section")])["kind"], "NO_BOUNDARY")

    def test_deterministic(self):
        b = table(2, [50, 70, 550, 300], self.header)
        self.assertEqual(self.run_pair(b), self.run_pair(b))

    def test_running_limits_ignore_template_block(self):
        pages = {n: ([word(50, 30, "Title"), word(50, 400, f"body{n}"[:4] if n == 1 else "x")], H) for n in (1, 2, 3, 4)}
        limits = scan.running_limits(pages, CFG)
        self.assertGreaterEqual(limits[2][0], 40.0)
        self.assertLess(limits[2][0], 100.0)


if __name__ == "__main__":
    unittest.main()
