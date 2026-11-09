"""Recognition layer of the Operations Summary rule (gates G1 to G3, annotations, zones, reason registry): pure functions
on synthetic text layers, no PDF."""
from __future__ import annotations

import unittest

from graph_builder.corpus import ops_tables as ops
from graph_builder.corpus import table_recognition as recognition
from ops_fixtures import (HEADER, HEADER_REAL, OPS_RULE, TITLE, TITLE_REAL, annotation_words, data, good_page, layer, rule_copy,
                          title_line, words)

RULE = OPS_RULE


def mentions(lines, rule=RULE):
    return recognition.mention_lines(layer(lines), rule)


def reasons(lines, rule=RULE):
    return [(m["passed"], m["reason"], m["detail"]) for m in mentions(lines, rule)]


class FixtureTests(unittest.TestCase):
    def test_default_layer_has_height_nine_and_one_glyph_per_character(self):
        page = layer([(10.0, [("ab", 1, 3)])])
        self.assertEqual(page["words"], [{"text": "ab", "bbox": [1, 10.0, 3, 19.0], "row": 0}])
        self.assertEqual([(c["text"], c["bbox"]) for c in page["chars"]], [("a", [1.0, 10.0, 2.0, 19.0]), ("b", [2.0, 10.0, 3.0, 19.0])])
        self.assertEqual((page["width"], page["height"], page["rotation"]), (612, 792, 0))

    def test_scale_shrinks_the_page_the_coordinates_the_glyphs_and_the_text_height(self):
        page = layer([(10.0, [("ab", 1, 3, 4.0)])], scale=0.5)
        self.assertEqual(page["words"][0]["bbox"], [0.5, 5.0, 1.5, 7.0])
        self.assertEqual(page["chars"][1]["bbox"], [1.0, 5.0, 1.5, 7.0])
        self.assertEqual((page["width"], page["height"]), (306.0, 396.0))

    def test_word_height_is_used_for_the_word_and_its_glyphs(self):
        page = layer([TITLE_REAL])
        self.assertEqual({round(w["bbox"][3] - w["bbox"][1], 6) for w in page["words"]}, {10.0})
        self.assertEqual({round(c["bbox"][3] - c["bbox"][1], 6) for c in page["chars"]}, {10.0})

    def test_a_triple_without_height_still_works(self):
        self.assertEqual(len(layer(good_page())["words"]), len([w for _, spec in good_page() for w in spec]))


class MentionLineTests(unittest.TestCase):
    def test_a_bare_title_passes(self):
        self.assertEqual(reasons([TITLE_REAL]), [(True, None, "")])

    def test_lines_with_only_one_title_word_are_not_mentions(self):
        # The header holds "Operations" and the section title holds "Summary"; neither names the table, and
        # "Summary Operations" is the wrong order. None of them may be counted as a rejected mention (N28).
        wrong_order = (300.0, [("Summary", 40, 90), ("Operations", 92, 150)])
        self.assertEqual(reasons(good_page() + [wrong_order]), [(True, None, "")])
        self.assertEqual(reasons([HEADER]), [])
        self.assertEqual(reasons([(10.0, [("Management", 256, 311), ("Summary", 314, 355)])]), [])

    def test_a_sentence_that_names_the_table_is_embedded_in_text(self):  # N1, N2
        sentence = (251.0, [("See", 240, 260), ("Operations", 262, 308), ("Summary", 310, 351), ("below", 353, 390)])
        self.assertEqual(reasons([sentence]), [(False, "no_title", "embedded_in_text")])
        contents = (251.0, [("5.2", 40, 58), ("Operations", 60, 106), ("Summary", 108, 150), ("........", 152, 190), ("12", 192, 204)])
        self.assertEqual(reasons([contents]), [(False, "no_title", "embedded_in_text")])

    def test_a_word_between_the_title_words_or_far_apart_is_not_found(self):  # N9 (i), (iii)
        far = (251.0, [("Operations", 261, 308), ("Summary", 335, 376)])  # 27 pt = 3 em_title apart
        between = (251.0, [("Operations", 261, 308), ("of", 310, 320), ("Summary", 322, 363)])
        for line in (far, between):
            self.assertEqual(reasons([line]), [(False, "no_title", "not_found")])

    def test_two_title_phrases_on_a_line(self):  # N7
        two = (251.0, [("Operations", 40, 86), ("Summary", 88, 130), ("Operations", 300, 346), ("Summary", 348, 390)])
        self.assertEqual(reasons([two]), [(False, "no_title", "multiple_title_phrases")])

    def test_a_word_in_the_dead_zone_is_ambiguous(self):  # N6
        # 1.5 em_title (13.5 pt) from the title: not the same phrase and not far enough to be a column of its own.
        line = (251.0, TITLE[1] + [("Page", 351 + 13.5, 380)])
        self.assertEqual(reasons([line]), [(False, "no_title", "ambiguous_gap")])

    def test_the_gap_is_measured_in_em_title_not_em_header(self):  # N6b
        # 29 pt from the title is 2.9 em_title (10.0 pt): ambiguous. Measured with the 8.9 pt header it would be 3.26.
        top, spec = title_line()
        line = (top, spec + [("Page", 351.5 + 29.0, 375.0, 8.9)])
        self.assertEqual(reasons([line, HEADER_REAL]), [(False, "no_title", "ambiguous_gap")])
        top, spec = title_line()
        line = (top, spec + [("Page", 351.5 + 31.0, 375.0, 8.9)])  # 3.1 em_title: a column of its own
        self.assertEqual(reasons([line, HEADER_REAL]), [(True, None, "")])

    def test_the_space_inside_the_title_is_measured_in_em_title(self):  # N6c
        # 7.5 pt between the title words is 0.75 em_title (<= 0.8). Measured with 8.9 it would be 0.84 and split the phrase.
        title = (221.2, [("Operations", 260.5, 308.0, 10.0), ("Summary", 315.5, 356.5, 10.0)])
        self.assertEqual(reasons([title, HEADER_REAL]), [(True, None, "")])
        title = (221.2, [("Operations", 260.5, 308.0, 10.0), ("Summary", 317.0, 358.0, 10.0)])  # 9.0 pt = 0.9 em_title
        self.assertEqual(reasons([title, HEADER_REAL]), [(False, "no_title", "not_found")])

    def test_a_long_annotation_is_refused(self):  # N8
        spec = [(f"w{i}", 20.0 + 8 * i, 26.0 + 8 * i, 8.9) for i in range(13)] + TITLE_REAL[1]
        self.assertEqual(reasons([(221.2, spec)]), [(False, "no_title", "annotation_too_long")])
        self.assertEqual(reasons([(221.2, spec[1:])]), [(True, None, "")])  # 12 words are the limit

    def test_the_first_violation_wins(self):  # N11c: a word glued to the title AND 13 words in all
        glued = [("a", 351.5 + 2.7, 358.0, 8.9)] + [(f"w{i}", 400.0 + 8 * i, 406.0 + 8 * i, 8.9) for i in range(12)]
        self.assertEqual(reasons([(221.2, TITLE_REAL[1] + glued)]), [(False, "no_title", "embedded_in_text")])

    def test_title_words_are_case_sensitive(self):
        line = (251.0, [("operations", 261, 308), ("summary", 310, 351)])
        self.assertEqual(reasons([line]), [])

    def test_title_words_with_regex_characters_are_plain_text(self):  # N29
        rule = rule_copy()
        rule["schema"]["title_words"] = ["Ops.", "Sum+"]
        good = (251.0, [("Ops.", 261, 290), ("Sum+", 292, 320)])
        near_miss = (251.0, [("OpsX", 261, 290), ("Sum", 292, 320)])
        self.assertEqual(reasons([good], rule), [(True, None, "")])
        self.assertEqual(reasons([near_miss], rule), [])
        self.assertEqual(recognition.title_phrase_pattern(rule), r"Ops\.\s+Sum\+")

    def test_evidence_holds_the_measurements(self):
        [mention] = mentions([title_line(left=("1 record not printed", 41.5))])
        title = mention["evidence"]["title"]
        self.assertEqual(title["em_pt"], 10.0)
        self.assertEqual(title["annotation_tokens"], 4)
        self.assertGreater(title["nearest_gap_em"]["left"], 13.0)
        self.assertIsNone(title["nearest_gap_em"]["right"])
        evidence = recognition.build_evidence(title, None, None, "recognised", None, RULE)
        self.assertGreater(evidence["margins"]["annotation_gap_em"], 10.0)  # about 13.8 em against the 3.0 limit

    def test_results_are_in_page_order_and_deterministic(self):
        lines = good_page() + [(top + 300, spec) for top, spec in good_page()]
        first, second = mentions(lines), mentions(lines)
        self.assertEqual(first, second)
        self.assertEqual([m["line"] for m in first], [0, 7])


class AnnotationTests(unittest.TestCase):
    def kinds(self, **sides):
        [mention] = mentions([title_line(**sides)])
        self.assertTrue(mention["passed"])
        return [(a["side"], a["kind"], a["count"]) for a in mention["annotations"]]

    def test_left_right_and_both_sides(self):
        self.assertEqual(self.kinds(left=("1 record not printed", 41.5)), [("left", "records_not_printed", 1)])
        self.assertEqual(self.kinds(right=("3 records not printed", 480.0)), [("right", "records_not_printed", 3)])
        self.assertEqual(self.kinds(left=("2 records not printed", 41.5), right=("12 record not printed", 480.0)),
                         [("left", "records_not_printed", 2), ("right", "records_not_printed", 12)])

    def test_an_annotation_in_a_smaller_font_is_found(self):
        [mention] = mentions([title_line(left=("1 record not printed", 41.5))])
        self.assertTrue(mention["passed"])

    def test_an_unclassified_annotation_is_accepted_and_flagged(self):
        [mention] = mentions([title_line(left=("continued", 41.5))])
        self.assertTrue(mention["passed"])
        self.assertEqual([(a["kind"], a["count"]) for a in mention["annotations"]], [("unclassified", None)])
        self.assertEqual(recognition.completeness(mention["annotations"]), "unclassified_annotation")

    def test_zero_records_not_printed_says_nothing_is_missing(self):  # N27b
        [mention] = mentions([title_line(left=("0 records not printed", 41.5))])
        self.assertEqual([(a["kind"], a["count"]) for a in mention["annotations"]], [("records_not_printed", 0)])
        self.assertIsNone(recognition.completeness(mention["annotations"]))

    def test_a_classified_count_wins_over_an_unclassified_annotation_on_either_side(self):  # N27c
        for left, right in ((("2 records not printed", 41.5), ("continued", 480.0)),
                            (("continued", 41.5), ("2 records not printed", 480.0))):
            [mention] = mentions([title_line(left=left, right=right)])
            self.assertEqual(len(mention["annotations"]), 2)
            self.assertEqual(recognition.completeness(mention["annotations"]), "partial_in_source")

    def test_only_unclassified_text_gives_unclassified_annotation(self):  # N27d
        [mention] = mentions([title_line(left=("0 records not printed", 41.5), right=("continued", 480.0))])
        self.assertEqual(recognition.completeness(mention["annotations"]), "unclassified_annotation")
        self.assertIsNone(recognition.completeness([]))

    def test_a_pattern_whose_group_is_not_a_number_never_raises(self):  # N27e
        rule = rule_copy()
        rule["schema"]["annotation_kinds"] = [{"kind": "records_not_printed", "pattern": "^(\\w+) records? not printed$",
                                               "sample": "x"}]
        found = recognition.classify_annotation("many records not printed", "left", rule)
        self.assertEqual((found["kind"], found["count"]), ("unclassified", None))
        optional = rule_copy()
        optional["schema"]["annotation_kinds"] = [{"kind": "records_not_printed", "pattern": "^(\\d+)?not printed$", "sample": "1not printed"}]
        self.assertEqual(recognition.classify_annotation("not printed", "left", optional)["kind"], "unclassified")

    def test_a_line_above_the_title_is_flagged_as_a_hint(self):  # N25 at the level of the function
        above = (208.0, [(w, x, x + 4.4 * len(w), 8.9) for w, x in annotation_words(("2 records not printed", 41.5))])
        lines = recognition.page_lines(layer([above, title_line(), HEADER_REAL]))
        flag = recognition.above_flag(lines, 1, RULE, 8.9)
        self.assertEqual([(a["side"], a["kind"], a["count"], a["owner"]) for a in flag],
                         [("above", "records_not_printed", 2, "uncertain")])
        self.assertEqual(recognition.completeness(flag), "partial_in_source")

    def test_text_above_the_title_is_not_flagged(self):  # N25b
        above = (208.0, [("Comments:", 41.5, 90.0, 8.9), ("some", 92.0, 115.0, 8.9), ("text", 117.0, 137.0, 8.9)])
        lines = recognition.page_lines(layer([above, title_line(), HEADER_REAL]))
        self.assertEqual(recognition.above_flag(lines, 1, RULE, 8.9), [])
        self.assertEqual(recognition.above_flag(lines, 0, RULE, 8.9), [])

    def test_a_line_farther_than_the_line_gap_is_not_flagged(self):  # N25c
        above = (190.0, [(w, x, x + 4.4 * len(w), 8.9) for w, x in annotation_words(("2 records not printed", 41.5))])
        lines = recognition.page_lines(layer([above, title_line(), HEADER_REAL]))
        self.assertEqual(recognition.above_flag(lines, 1, RULE, 8.9), [])


class HeaderGateTests(unittest.TestCase):
    def header(self, lines, at=0, rule=RULE):
        return recognition.recognise_header(recognition.page_lines(layer(lines)), at, rule)

    def test_a_correct_header_gives_boxes_and_em(self):
        found = self.header([TITLE, HEADER])
        self.assertTrue(found["ok"])
        self.assertEqual((found["line"], found["em"], len(found["boxes"])), (1, 9.0, 7))
        self.assertEqual(found["boxes"][3][0::2], [154, 192])  # "End MD(ft" is one label box
        self.assertEqual(found["evidence"]["labels_matched"], [c["label"] for c in RULE["schema"]["columns"]])
        self.assertTrue(found["evidence"]["x_monotone"])

    def test_the_title_is_the_last_line(self):  # N11b
        found = self.header([TITLE])
        self.assertEqual((found["ok"], found["reason"], found["detail"]), (False, "no_header", "title_is_last_line"))

    def test_a_line_that_is_not_a_header_has_no_header(self):  # N3, N4, N10
        for text in ("Some sentence of the report", "Page 3"):
            found = self.header([TITLE, (263.2, words(text, left=48.0))])
            self.assertEqual((found["reason"], found["detail"]), ("no_header", "next_row_is_not_header"))

    def test_a_header_too_far_below_the_title_is_not_adjacent(self):  # N11
        found = self.header([TITLE, (251.0 + 9.0 + 27.0, HEADER[1])])  # 3 em_header below the title
        self.assertEqual(found["reason"], "header_not_adjacent")
        self.assertIn("3.00 em_header", found["detail"])

    def test_the_distance_is_measured_in_the_text_height_of_the_line_under_the_title(self):  # N11d
        small = (266.0, [("Some", 48.0, 70.0, 5.0), ("sentence", 72.0, 110.0, 5.0)])  # 6 pt below a 9 pt title: 1.2 em of 5.0
        found = self.header([TITLE, small])
        self.assertEqual(found["reason"], "header_not_adjacent")
        # The same 6 pt under 9 pt text (0.67 em) would still be adjacent: the gap is not measured with the title's text.
        self.assertTrue(self.header([TITLE, (266.0, HEADER[1])])["ok"])

    def test_missing_extra_and_reordered_labels(self):  # N12, N13, N14, N15
        without = [w for w in HEADER[1] if w[0] != "Elapsed"]
        found = self.header([TITLE, (263.2, without)])
        self.assertEqual((found["reason"], found["detail"]), ("header_labels_missing", "missing Elapsed"))
        found = self.header([TITLE, (263.2, HEADER[1] + [("Extra", 450, 480)])])
        self.assertEqual((found["reason"], found["detail"]), ("header_extra_labels", "extra Extra"))
        found = self.header([TITLE, (263.2, [("To", 48, 68), ("From", 89, 99)] + HEADER[1][2:])])
        self.assertEqual(found["reason"], "header_order_mismatch")
        overlapping = [("From", 48, 68), ("To", 60, 99)] + HEADER[1][2:]
        found = self.header([TITLE, (263.2, overlapping)])
        self.assertEqual((found["reason"], found["detail"]), ("header_order_mismatch", "x_not_monotone"))

    def test_a_repeated_label_is_extra(self):
        found = self.header([TITLE, (263.2, HEADER[1] + [("Code", 600, 620)])])
        self.assertEqual(found["reason"], "header_extra_labels")

    def test_other_ways_to_split_the_header_words_are_the_same_header(self):
        variants = {
            "two words": HEADER[1],
            "one word": [w for w in HEADER[1] if w[0] not in ("End", "MD(ft")] + [("End MD(ft)", 154, 192)],
            "three words": [w for w in HEADER[1] if w[0] not in ("End", "MD(ft")] + [("End", 154, 169), ("MD", 171, 182), ("(ft)", 183, 192)]}
        zones = {}
        for name, spec in variants.items():
            found = self.header([TITLE, (263.2, sorted(spec, key=lambda w: w[1]))])
            self.assertTrue(found["ok"], name)
            zones[name] = recognition.zones_from_header(found["boxes"], RULE)
        self.assertEqual(zones["two words"], zones["one word"])
        self.assertEqual(zones["two words"], zones["three words"])

    def test_zones_are_halfway_between_the_labels(self):
        found = self.header([TITLE, HEADER])
        self.assertEqual(recognition.zones_from_header(found["boxes"], RULE), {
            "left": 48, "from_to": 78.5, "to_elapsed": 107.0, "elapsed_depth": 150.0, "depth_code": 200.0,
            "code_limit": 238.0, "non_prod_left": 537, "non_prod_right": 573})

    def test_first_row_gate(self):  # N16
        lines = recognition.page_lines(layer(good_page()))
        self.assertTrue(recognition.first_row_gate(lines, 1, RULE, 9.0)["ok"])
        lines = recognition.page_lines(layer([TITLE, HEADER, (275.1, [("Management", 256, 311), ("Summary", 314, 355)])]))
        found = recognition.first_row_gate(lines, 1, RULE, 9.0)
        self.assertEqual((found["ok"], found["reason"]), (False, "no_rows"))
        found = recognition.first_row_gate(recognition.page_lines(layer([TITLE, HEADER])), 1, RULE, 9.0)
        self.assertEqual((found["ok"], found["reason"]), (False, "no_rows"))
        far = data(300.0, "0:00", "8:00", "8.00", "0", "WOD", words("Wait"))  # more than one line gap below the header
        found = recognition.first_row_gate(recognition.page_lines(layer([TITLE, HEADER, far])), 1, RULE, 9.0)
        self.assertEqual(found["reason"], "no_rows")

    def test_the_header_labels_come_from_the_rule(self):
        rule = rule_copy()
        rule["schema"]["columns"][2]["label"] = "Hours"
        renamed = [("Hours" if w[0] == "Elapsed" else w[0], w[1], w[2]) for w in HEADER[1]]
        self.assertTrue(self.header([TITLE, (263.2, renamed)], rule=rule)["ok"])
        self.assertEqual(self.header([TITLE, HEADER], rule=rule)["reason"], "header_labels_missing")


class ReasonRegistryTests(unittest.TestCase):
    ROUND_ONE = ("no_title", "no_header", "header_order_mismatch", "rotated_page", "no_rows", "time_invalid", "column_mismatch",
                 "row_count_mismatch", "trailing_line", "elapsed_mismatch", "x_unmapped", "word_mismatch",
                 "docling_extent_mismatch", "ambiguous_docling_match", "docling_multipage")
    NEW = ("header_not_adjacent", "header_labels_missing", "header_extra_labels", "text_layer_read_error", "rule_exception",
           "merge_exception")

    def test_every_code_has_exactly_one_state_and_stage(self):
        self.assertEqual(set(recognition.REASON_STATE), set(self.ROUND_ONE + self.NEW))
        self.assertEqual(set(ops.FALLBACK_REASONS), set(recognition.REASON_STATE))
        self.assertEqual(len(ops.FALLBACK_REASONS), 21)
        for reason in ops.FALLBACK_REASONS:
            state, stage = recognition.REASON_STATE[reason]
            self.assertIn(state, ("RECOGNISED_BUT_FAILED", "UNSUPPORTED_FORMAT", "PARSING_FAILURE"))
            self.assertIn(stage, ("precondition", "recognition", "read", "validate", "merge", "runtime"))
            self.assertEqual(ops.state_of(reason), state)

    def test_the_mapping_follows_the_design(self):
        for reason in ("no_title", "no_header", "header_order_mismatch", "rotated_page", "no_rows", "header_not_adjacent",
                       "header_labels_missing", "header_extra_labels"):
            self.assertEqual(ops.state_of(reason), "UNSUPPORTED_FORMAT", reason)
        for reason in ("time_invalid", "column_mismatch", "row_count_mismatch", "trailing_line", "elapsed_mismatch",
                       "x_unmapped", "word_mismatch", "docling_extent_mismatch", "ambiguous_docling_match", "docling_multipage"):
            self.assertEqual(ops.state_of(reason), "RECOGNISED_BUT_FAILED", reason)
        for reason in ("text_layer_read_error", "rule_exception", "merge_exception"):
            self.assertEqual(ops.state_of(reason), "PARSING_FAILURE", reason)
        self.assertEqual(recognition.REASON_STATE["rotated_page"][1], "precondition")

    def test_an_unknown_code_or_none_is_an_error_and_success_is_never_returned(self):
        for bad in ("surprise", None, ""):
            with self.assertRaises(ValueError):
                ops.state_of(bad)
        self.assertNotIn("SUPPORTED_AND_VALIDATED", {state for state, _ in recognition.REASON_STATE.values()})

    def test_retired_codes_are_gone(self):
        for retired in ("low_confidence", "row_malformed", "no_text_layer", "not_daily_report_type"):
            self.assertNotIn(retired, ops.FALLBACK_REASONS)


if __name__ == "__main__":
    unittest.main()
