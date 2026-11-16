"""A-446: source-structure evidence for multi-page tables (scripts/qa_multipage_structure.py). Evidence only, never joins anything.
Positive: a continuing numbered log with repeated header and equal column rules is SUPPORTED. Negative: the same report title on two different days
(repeated header, no continuity) is never SUPPORTED; different column rules or a numbering restart are CONFLICT; a running page footer is no counter."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("qa_multipage_structure", ROOT / "scripts" / "qa_multipage_structure.py")
st = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(st)
CFG = st.load_config()
H = 800.0
BBOX = (50.0, 100.0, 550.0, 700.0)


def w(x0, y0, text, width=40.0, height=10.0):
    return (x0, y0, x0 + width, y0 + height, text)


def log_page(first_start, count=4, header=True, x_desc=200.0, y_top=110.0):
    """Words of a depth log page: header line, then one 'a-b- description' line per 10 units."""
    words = []
    y = y_top
    if header:
        words += [w(60, y, "DEPTH"), w(120, y, "LITHOLOGY"), w(x_desc, y, "DESCRIPTION")]
        y += 20
    for i in range(count):
        a = first_start + 10 * i
        words += [w(x_desc, y, f"{a}-{a + 10}-"), w(x_desc + 60, y, "granite")]
        y += 20
    return words


def rules(xs=(50.0, 110.0, 190.0, 550.0), top=100.0, bottom=700.0):
    return [(x, top, x, bottom) for x in xs]


def side(words, segments, bbox=BBOX, pages=30):
    return {"bbox": list(bbox), "words": words, "segments": segments, "page_height": H, "pdf_pages": pages}


class Numbering(unittest.TestCase):
    def test_range_continuity_across_the_break(self):
        a = st.text_lines(log_page(900), BBOX, CFG)
        b = st.text_lines(log_page(940), BBOX, CFG)
        result = st.numbering_continuity(a, b, BBOX, BBOX, CFG)
        self.assertEqual(result["kind"], "range")
        self.assertTrue(result["continuous"])

    def test_gap_in_ranges_is_not_continuous(self):
        a = st.text_lines(log_page(900), BBOX, CFG)
        b = st.text_lines(log_page(960), BBOX, CFG)
        self.assertFalse(st.numbering_continuity(a, b, BBOX, BBOX, CFG)["continuous"])

    def test_restart_is_reported(self):
        a = st.text_lines(log_page(900), BBOX, CFG)
        b = st.text_lines(log_page(0), BBOX, CFG)
        result = st.numbering_continuity(a, b, BBOX, BBOX, CFG)
        self.assertFalse(result["continuous"])
        self.assertTrue(result["restart"])

    def test_no_numbering_series_is_unknown_not_false(self):
        words = [w(60, 110 + 20 * i, "text") for i in range(5)]
        lines = st.text_lines(words, BBOX, CFG)
        result = st.numbering_continuity(lines, lines, BBOX, BBOX, CFG)
        self.assertIsNone(result["continuous"])

    def test_first_column_counter(self):
        a = st.text_lines([w(55, 110 + 20 * i, str(i + 1)) for i in range(4)] + [w(120, 110 + 20 * i, "item") for i in range(4)], BBOX, CFG)
        b = st.text_lines([w(55, 110 + 20 * i, str(i + 5)) for i in range(4)] + [w(120, 110 + 20 * i, "item") for i in range(4)], BBOX, CFG)
        result = st.numbering_continuity(a, b, BBOX, BBOX, CFG)
        self.assertEqual(result["kind"], "counter")
        self.assertTrue(result["continuous"])


class HeaderColumnsBorders(unittest.TestCase):
    def test_header_repeated_same_position(self):
        a = st.text_lines(log_page(0), BBOX, CFG)
        b = st.text_lines(log_page(40), BBOX, CFG)
        self.assertTrue(st.header_repeated(a, b, 500.0, CFG)["repeated"])

    def test_different_first_line_is_not_a_repeated_header(self):
        a = st.text_lines(log_page(0), BBOX, CFG)
        b = st.text_lines(log_page(40, header=False), BBOX, CFG)
        self.assertFalse(st.header_repeated(a, b, 500.0, CFG)["repeated"])

    def test_single_word_first_line_is_too_short(self):
        a = st.text_lines([w(60, 110, "Total")], BBOX, CFG)
        b = st.text_lines([w(60, 110, "Total")], BBOX, CFG)
        self.assertFalse(st.header_repeated(a, b, 500.0, CFG)["repeated"])

    def test_column_rules_match_and_differ(self):
        ra = st.vertical_rules(rules(), BBOX, CFG)
        self.assertEqual(len(ra), 4)
        self.assertTrue(st.column_rules_match(ra, st.vertical_rules(rules(), BBOX, CFG), 500.0, CFG)["match"])
        shifted = st.vertical_rules(rules((50.0, 140.0, 190.0, 550.0)), BBOX, CFG)
        self.assertFalse(st.column_rules_match(ra, shifted, 500.0, CFG)["match"])
        fewer = st.vertical_rules(rules((50.0, 550.0)), BBOX, CFG)
        self.assertFalse(st.column_rules_match(ra, fewer, 500.0, CFG)["match"])

    def test_short_vertical_segments_are_not_column_rules(self):
        short = [(110.0, 100.0, 110.0, 130.0)]
        self.assertEqual(st.vertical_rules(short, BBOX, CFG), [])
        self.assertIsNone(st.column_rules_match([], [], 500.0, CFG)["match"])

    def test_horizontal_border_on_edge(self):
        bottom = [(50.0, 700.0, 550.0, 700.0)]
        self.assertTrue(st.horizontal_border(bottom, BBOX, "bottom", CFG))
        self.assertFalse(st.horizontal_border(bottom, BBOX, "top", CFG))
        self.assertFalse(st.horizontal_border([(50.0, 700.0, 300.0, 700.0)], BBOX, "bottom", CFG))


class MarkersAndCounters(unittest.TestCase):
    def test_continued_marker_found_below_table(self):
        self.assertTrue(st.continued_marker([w(60, 705, "(continued)")], BBOX, H, CFG)["found"])
        self.assertTrue(st.continued_marker([w(60, 705, "continued")], BBOX, H, CFG)["found"])

    def test_cont_inside_ordinary_word_or_far_away_is_ignored(self):
        self.assertFalse(st.continued_marker([w(60, 705, "Contractor")], BBOX, H, CFG)["found"])
        self.assertFalse(st.continued_marker([w(60, 705, "Cont")], BBOX, H, CFG)["found"])
        self.assertFalse(st.continued_marker([w(60, 780, "continued")], BBOX, H, CFG)["found"])

    def test_form_counter_ignores_running_page_footer(self):
        footer = [w(50, 20, "Page 12 of 28")]
        self.assertIsNone(st.form_page_counter(footer, 28, CFG))
        form = [w(50, 20, "Page"), w(90, 20, "_2_"), w(120, 20, "of"), w(140, 20, "_17_")]
        self.assertEqual(st.form_page_counter(form, 28, CFG), {"n": 2, "of": 17})


class Decision(unittest.TestCase):
    def evaluate(self, words_a, words_b, rules_a=None, rules_b=None, segs_extra_a=(), segs_extra_b=()):
        a = side(words_a, rules(**({} if rules_a is None else {"xs": rules_a})) + list(segs_extra_a))
        b = side(words_b, rules(**({} if rules_b is None else {"xs": rules_b})) + list(segs_extra_b))
        return st.evaluate_structure(a, b, CFG)

    def test_continuing_log_is_supported(self):
        ev = self.evaluate(log_page(0), log_page(40))
        self.assertEqual(ev["decision"], "STRUCTURE_SUPPORTS_CONTINUATION")
        self.assertIn("numbering_continuous_range", ev["reasons"])

    def test_closed_frames_are_a_caveat_not_a_veto(self):
        edges = [(50.0, 700.0, 550.0, 700.0)], [(50.0, 100.0, 550.0, 100.0)]
        ev = self.evaluate(log_page(0), log_page(40), segs_extra_a=edges[0], segs_extra_b=edges[1])
        self.assertEqual(ev["decision"], "STRUCTURE_SUPPORTS_CONTINUATION")
        self.assertTrue(ev["border"]["closed_per_page"])

    def test_same_title_on_different_days_is_not_supported(self):
        title = [w(60, 110, "Daily"), w(110, 110, "Drilling"), w(170, 110, "Report")]
        rows = [w(60, 130 + 20 * i, "x") for i in range(3)]
        a = self.evaluate(title + rows, title + rows, segs_extra_a=[(50.0, 700.0, 550.0, 700.0)], segs_extra_b=[(50.0, 100.0, 550.0, 100.0)])
        self.assertNotEqual(a["decision"], "STRUCTURE_SUPPORTS_CONTINUATION")
        self.assertTrue(a["header"]["repeated"])

    def test_different_column_rules_conflict(self):
        ev = self.evaluate(log_page(0), log_page(40), rules_b=(50.0, 150.0, 300.0, 550.0))
        self.assertEqual(ev["decision"], "STRUCTURE_CONFLICT")
        self.assertIn("columns_differ", ev["reasons"])

    def test_numbering_restart_conflicts(self):
        ev = self.evaluate(log_page(900), log_page(0))
        self.assertEqual(ev["decision"], "STRUCTURE_CONFLICT")

    def test_no_evidence_is_undetermined(self):
        ev = self.evaluate([w(60, 110, "alpha"), w(100, 110, "beta")], [w(60, 110, "gamma"), w(100, 110, "delta")],
                           segs_extra_a=[(50.0, 700.0, 550.0, 700.0)], segs_extra_b=[(50.0, 100.0, 550.0, 100.0)])
        self.assertEqual(ev["decision"], "UNDETERMINED")


class Config(unittest.TestCase):
    def test_config_values_have_units_and_load(self):
        self.assertGreater(CFG["columns"]["rule_x_tol_rel"], 0)
        self.assertEqual(CFG["numbering"]["counter_step"], 1)


if __name__ == "__main__":
    unittest.main()
