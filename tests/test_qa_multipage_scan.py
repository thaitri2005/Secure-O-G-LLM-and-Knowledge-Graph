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


class A433FalseNegativeClassTests(unittest.TestCase):
    def test_explicit_footer_limit_is_used(self):
        # footer text sits at 12% of the page height, above the default footer band: the explicit running limit must win
        footer = [word(50, 700, "Printed"), word(300, 700, "Page")]
        self.assertFalse(scan.ends_page_body([50, 600, 500, 695], footer, H, CFG)["ends"])
        self.assertTrue(scan.ends_page_body([50, 600, 500, 695], footer, H, CFG, limit=699.0)["ends"])

    def test_real_text_below_table_still_blocks_with_explicit_limit(self):
        text = [word(50, 700, "Notes"), word(50, 740, "more")]
        self.assertFalse(scan.ends_page_body([50, 600, 500, 695], text, H, CFG, limit=739.0)["ends"])

    def test_frame_tables_are_dropped_and_body_tables_kept(self):
        frame_top = {"id": "f", "page": 2, "bbox": [50, 20, 500, 60]}
        body = {"id": "b", "page": 2, "bbox": [50, 100, 500, 300]}
        frame_bottom = {"id": "g", "page": 2, "bbox": [50, 770, 500, 790]}
        kept, frames = scan.drop_frame_tables([frame_top, body, frame_bottom], {2: (65.0, 760.0)}, CFG)
        self.assertEqual([t["id"] for t in kept], ["b"])
        self.assertEqual({t["id"]: t["frame"] for t in frames}, {"f": "header", "g": "footer"})

    def test_table_overlapping_running_limit_is_not_a_frame(self):
        straddling = {"id": "s", "page": 1, "bbox": [50, 40, 500, 300]}
        kept, frames = scan.drop_frame_tables([straddling], {1: (65.0, 760.0)}, CFG)
        self.assertEqual(len(kept), 1)
        self.assertFalse(frames)

    def test_pair_ignores_header_frame_table(self):
        frame = {"id": "f", "page": 2, "bbox": [50, 20, 500, 60]}
        real = table(2, [50, 90, 550, 300], ["From", "To", "Code"])
        real["id"] = "r"
        kept, _ = scan.drop_frame_tables([frame, real], {2: (70.0, 740.0)}, CFG)
        pairs = scan.pair_boundaries([table(1, [50, 600, 550, 745], ["From", "To", "Code"])] + kept)
        self.assertEqual(pairs[0][1]["id"], "r")

    def test_rotation_matrix_maps_words_to_display_orientation(self):
        # 90 degree rotation of a 612x792 page: (x, y) -> (792 - y, x)
        matrix = (0.0, 1.0, -1.0, 0.0, 792.0, 0.0)
        x0, y0, x1, y1 = scan.to_display_rect((100.0, 50.0, 140.0, 60.0), matrix)
        self.assertEqual((x0, y0, x1, y1), (732.0, 100.0, 742.0, 140.0))

    def test_identity_rotation_keeps_rect(self):
        self.assertEqual(scan.to_display_rect((1.0, 2.0, 3.0, 4.0), (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)), (1.0, 2.0, 3.0, 4.0))

    def test_config_has_frame_and_wider_footer_zone(self):
        self.assertGreater(CFG["frame_slack_pt"], 0.0)
        self.assertGreaterEqual(CFG["running_bottom_zone"], 0.12)


GOLD_SPEC = importlib.util.spec_from_file_location("qa_multipage_gold", ROOT / "scripts" / "qa_multipage_gold.py")
gold = importlib.util.module_from_spec(GOLD_SPEC)
GOLD_SPEC.loader.exec_module(gold)


def upair(key, kind, data_set="DEV", **extra):
    base = {"key": key, "file_id": key.split(":")[0], "kind": kind, "data_set": data_set, "score": 0.85,
            "words_below": 0, "words_above": 0, "gap_sum": 0.05}
    base.update(extra)
    return base


class GoldMetricsTests(unittest.TestCase):
    def test_precision_recall_with_denominators_and_unclear_excluded(self):
        universe = {"pairs": [upair("a:1-2", "CANDIDATE"), upair("b:1-2", "CANDIDATE"), upair("c:1-2", "LOOKALIKE"),
                              upair("d:1-2", "NO_BOUNDARY"), upair("e:1-2", "CANDIDATE")]}
        cases = [{"key": "a:1-2", "label": "TRUE_CONTINUATION"}, {"key": "b:1-2", "label": "FALSE_CANDIDATE"},
                 {"key": "c:1-2", "label": "TRUE_CONTINUATION"}, {"key": "d:1-2", "label": "FALSE_CANDIDATE"},
                 {"key": "e:1-2", "label": "UNCLEAR"}]
        result = gold.score_scanner(universe, cases)
        total = result["by_set"]["ALL"]
        self.assertEqual((total["TP"], total["FP"], total["FN"], total["TN"]), (1, 1, 1, 1))
        self.assertEqual(result["excluded_unclear"], 1)
        self.assertEqual(total["precision"], 0.5)
        self.assertEqual(total["recall_on_gold"], 0.5)

    def test_sets_are_reported_separately(self):
        universe = {"pairs": [upair("a:1-2", "CANDIDATE", "X"), upair("b:1-2", "NO_BOUNDARY", "Y")]}
        cases = [{"key": "a:1-2", "label": "TRUE_CONTINUATION"}, {"key": "b:1-2", "label": "TRUE_CONTINUATION"}]
        result = gold.score_scanner(universe, cases)
        self.assertEqual(result["by_set"]["X"]["TP"], 1)
        self.assertEqual(result["by_set"]["Y"]["FN"], 1)

    def test_wilson_interval_bounds(self):
        low, high = gold.wilson(15, 15)
        self.assertGreater(low, 0.75)
        self.assertEqual(high, 1.0)
        self.assertIsNone(gold.wilson(0, 0))

    def test_sample_rule_is_deterministic_and_skips_labelled(self):
        pairs = [upair(f"d{i}:1-2", "NO_BOUNDARY", gap_sum=0.1 * i) for i in range(6)]
        pairs += [upair("c:1-2", "CANDIDATE"), upair("l:1-2", "LOOKALIKE")]
        universe = {"pairs": pairs}
        first = gold.select_sample(universe, {"c:1-2"}, 4)
        self.assertEqual(first, gold.select_sample(universe, {"c:1-2"}, 4))
        self.assertNotIn("c:1-2", first["keys"])
        self.assertIn("l:1-2", first["keys"])
        self.assertLessEqual(len(first["keys"]), 4)

    def test_universe_counts_shared_document_once(self):
        doc = {"pdf": "x.pdf", "pages": 3, "tables": 1, "errors": []}
        pair = {"file_id": "f1", "page_a": 1, "page_b": 2, "a": "t1", "b": "t2", "kind": "NO_BOUNDARY", "grade": None,
                "score": 0.1, "rotation": [0, 0], "evidence": {"header_repeated": False},
                "detail": {"end": {"gap_frac": 0.1, "words_below": 1}, "start": {"gap_frac": 0.1, "words_above": 0},
                           "num_cols": [2, 2]}}
        scan_a = {"documents": {"f1": doc}, "pairs": [pair]}
        scan_b = {"documents": {"f1": doc}, "pairs": [dict(pair, kind="CANDIDATE")]}
        result = gold.build_universe([("a", "S1", scan_a), ("b", "S2", scan_b)])
        self.assertEqual(len(result["pairs"]), 1)
        self.assertEqual(result["pairs"][0]["data_set"], "S1")


class DocumentIsolationTests(unittest.TestCase):
    def test_broken_pdf_is_recorded_and_other_documents_survive(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
            tmp = Path(tmp)
            rel = tmp / "rel"
            rel.mkdir()
            raw = tmp / "raw"
            raw.mkdir()
            bad = raw / "bad.pdf"
            bad.write_bytes(b"not a pdf at all")
            digest = scan.sha256(bad)
            (rel / "files.jsonl").write_text(json.dumps({"file_id": "f1", "sha256": digest, "page_count": 2}) + "\n", encoding="utf-8")
            (rel / "pages.jsonl").write_text("", encoding="utf-8")
            (rel / "chunks.jsonl").write_text("", encoding="utf-8")
            (rel / "tables.jsonl").write_text("", encoding="utf-8")
            result = scan.scan(rel, raw, CFG, False)
            self.assertEqual(result["pairs"], [])
            self.assertTrue(any(e.startswith("PDF_OPEN_FAILED") for e in result["documents"]["f1"]["errors"]))


if __name__ == "__main__":
    unittest.main()
