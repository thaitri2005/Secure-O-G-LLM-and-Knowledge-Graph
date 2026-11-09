"""A-401a: mark-margin signal for Operations tables (synthetic words; no PDF needed)."""
from __future__ import annotations

import unittest

from graph_builder.corpus.qa import opsmargin as om

CONFIG = om.load_config()
EM = 9.0
LABEL = [500.0, 100.0, 536.0, 100.0 + EM]  # "Non-Prod": x0 500, x1 536


def word(text, x0, x1, top):
    return {"text": text, "bbox": [x0, top, x1, top + EM]}


def table_words(mark_centres, description_right=520.0):
    words = [word("Non-Prod", LABEL[0], LABEL[2], 100.0)]
    for index, centre in enumerate(mark_centres):
        top = 112.0 + index * 12
        words.append(word("meeting", description_right - 40, description_right, top))
        words.append(word("X", centre - 2.5, centre + 2.5, top))
    return words


BOX = [40.0, 100.0, 570.0, 200.0]


class MeasureTests(unittest.TestCase):
    def test_margin_is_distance_inside_the_column_in_em(self):
        m = om.measure_table(table_words([LABEL[2] - 5.4]), BOX, CONFIG)
        self.assertEqual(m["status"], "ok")
        self.assertEqual(m["x_margins_em"], [0.6])

    def test_mark_outside_column_has_negative_margin(self):
        m = om.measure_table(table_words([LABEL[2] + 3.0]), BOX, CONFIG)
        self.assertLess(m["x_margins_em"][0], 0)

    def test_mark_beyond_window_is_not_a_mark(self):
        m = om.measure_table(table_words([LABEL[2] + 6 * EM]), BOX, CONFIG)
        self.assertEqual(m["x_margins_em"], [])

    def test_missing_label(self):
        words = [w for w in table_words([530.0]) if w["text"] != "Non-Prod"]
        self.assertEqual(om.measure_table(words, BOX, CONFIG)["status"], "no_label")

    def test_dots_marker_is_ignored(self):
        words = table_words([530.0]) + [word("...", 505.0, 520.0, 112.0)]
        self.assertEqual(len(om.measure_table(words, BOX, CONFIG)["x_margins_em"]), 1)


def family(margins_per_table):
    return {f"t{i}": {"status": "ok", "em": EM, "x_margins_em": sorted(m), "desc_gap_em": None} for i, m in enumerate(margins_per_table)}


class JudgeTests(unittest.TestCase):
    def codes(self, verdicts, table_id):
        return [code for code, _ in verdicts[table_id]]

    def test_uniform_template_offset_is_not_flagged(self):
        """All marks at the same offset (MAD = 0): the fixed offset must not become a dead zone."""
        measures = family([[0.5975]] * 30)
        verdicts = om.judge_family(measures, CONFIG)
        self.assertFalse(any(verdicts.values()))

    def test_noise_inside_the_floor_is_not_flagged(self):
        measures = family([[0.5975]] * 29 + [[0.5975 - 0.2]])  # 0.2 em relative scatter = 2 floors < k
        self.assertEqual(om.judge_family(measures, CONFIG)["t29"], [])

    def test_mark_close_to_the_edge_is_flagged(self):
        measures = family([[0.5975]] * 29 + [[0.1]])
        verdicts = om.judge_family(measures, CONFIG)
        self.assertEqual(self.codes(verdicts, "t29"), ["OPS_MARGIN_NEEDS_VERIFICATION"])
        self.assertEqual(self.codes(verdicts, "t0"), [])

    def test_mark_outside_the_column_is_flagged(self):
        measures = family([[0.5975]] * 29 + [[-0.4]])
        self.assertEqual(self.codes(om.judge_family(measures, CONFIG), "t29"), ["OPS_MARGIN_NEEDS_VERIFICATION"])

    def test_mark_deeper_inside_is_not_flagged(self):
        measures = family([[0.5975]] * 29 + [[2.5]])
        self.assertEqual(om.judge_family(measures, CONFIG)["t29"], [])

    def test_family_that_varies_widely_is_judged_by_its_own_spread(self):
        spread = [[0.3 + 0.05 * (i % 12)] for i in range(40)]
        measures = family(spread + [[0.35]])  # inside the observed range
        self.assertEqual(om.judge_family(measures, CONFIG)["t40"], [])

    def test_too_few_values_gives_info_not_a_judgement(self):
        verdicts = om.judge_family(family([[0.5975]] * 5), CONFIG)
        self.assertEqual(self.codes(verdicts, "t0"), ["OPS_MARGIN_NO_REFERENCE"])

    def test_table_without_mark_is_not_flagged(self):
        measures = family([[0.5975]] * 30)
        measures["blank"] = {"status": "ok", "em": EM, "x_margins_em": [], "desc_gap_em": 1.0}
        self.assertEqual(om.judge_family(measures, CONFIG)["blank"], [])

    def test_unmeasured_table_reports_why(self):
        verdicts = om.judge_table({"status": "no_label"}, None, CONFIG)
        self.assertEqual(verdicts, [("OPS_MARGIN_NO_REFERENCE", {"reason": "no_label"})])

    def test_deterministic_and_warn_only(self):
        measures = family([[0.5975]] * 29 + [[0.1]])
        self.assertEqual(om.judge_family(measures, CONFIG), om.judge_family(measures, CONFIG))
        severities = {code: severity for code, severity, _, _ in om.REASONS}
        self.assertEqual(severities["OPS_MARGIN_NEEDS_VERIFICATION"], "WARN")


if __name__ == "__main__":
    unittest.main()
