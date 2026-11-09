"""Operations Summary tables rebuilt from the text layer: format detection, self-checks, fallback and K1 integration."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import types
import unittest
from unittest.mock import patch

from graph_builder.corpus import ops_tables as ops
from graph_builder.corpus.k1_build import logical_tables, map_children
from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config
from ops_fixtures import (HEADER, HEADER_LABELS, OPS_RULE, TITLE, annotation_words, continuation, data, good_page, layer, read_page,
                          real_page, rule_copy, title_line, words)

ROOT = Path(__file__).resolve().parents[1]
FID = "f" + "0" * 16


class ReadPageTests(unittest.TestCase):
    def test_rebuilds_header_rows_wrapped_description_and_mark(self):
        [result] = read_page(layer(good_page()))
        self.assertEqual(result["status"], "rebuilt")
        self.assertEqual(result["rows"], [
            ["0:00", "8:00", "8.00", "0", "WOD", "Wait on daylight , morning meeting", "X"],
            ["8:00", "15:00", "7.00", "0", "MOB", "Fly drill loads to site and stage prior to camp, stores tent complete.", ""],
            ["15:00", "0:00", "9.00", "120", "RIGU", "Assemble rig", ""]])
        self.assertEqual(result["bbox"][:2], [48, 263.2])

    def test_free_text_is_never_put_in_the_non_prod_column(self):
        # Description words run into the x range of the Non-Prod header; only a token exactly "X" there is a mark.
        long_text = [("Assemble", 244, 280), ("rig", 282, 291), ("with", 293, 308), ("helicopter,", 310, 346),
                     ("pump", 535, 555), ("and", 557, 570)]
        lines = good_page()
        lines[2] = data(275.1, "0:00", "8:00", "8.00", "0", "WOD", long_text, mark=True)
        [result] = read_page(layer(lines))
        self.assertEqual(result["status"], "rebuilt")
        self.assertEqual(result["rows"][0][5], "Assemble rig with helicopter, pump and")
        self.assertEqual(result["rows"][0][6], "X")

    def test_x_outside_the_non_prod_span_is_description(self):
        lines = good_page()
        lines[3] = data(287.1, "8:00", "15:00", "7.00", "0", "MOB", [("Valve", 244, 270), ("X", 300, 306), ("open", 310, 330)])
        [result] = read_page(layer(lines))
        self.assertEqual(result["rows"][1][5], "Valve X open camp, stores tent complete.")
        self.assertEqual(result["rows"][1][6], "")

    def test_column_anchors_come_from_the_header_of_the_page(self):
        # The same table printed 40 pt further right still rebuilds, because the anchors are read from its header.
        def shift(lines):  # the table moves, the centred "Management Summary" title below it stays
            return [(top, [(text, left + 40, right + 40) for text, left, right in spec]) for top, spec in lines[:-1]] + lines[-1:]
        [result] = read_page(layer(shift(good_page())))
        self.assertEqual(result["status"], "rebuilt")
        self.assertEqual(result["rows"][0][6], "X")

    def test_every_occurrence_is_reported_and_other_pages_give_nothing(self):
        self.assertEqual(read_page(layer([(100.0, [("Daily", 40, 70), ("Report", 72, 110)])])), [])
        second = [(top + 200, spec) for top, spec in good_page()]
        results = read_page(layer(good_page() + second))
        self.assertEqual([(r["index"], r["status"]) for r in results], [(1, "rebuilt"), (2, "rebuilt")])

    def test_no_header_when_the_title_is_not_followed_by_the_header(self):
        lines = good_page()
        lines[1] = (263.2, [("Something", 48, 100), ("else", 102, 130)])
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "no_header"))

    def test_header_in_another_order_falls_back(self):
        lines = good_page()
        lines[1] = (263.2, [("To", 48, 68), ("From", 89, 99)] + HEADER[1][2:])
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "header_order_mismatch"))

    def test_time_tokens_in_the_wrong_columns_fall_back(self):
        lines = good_page()
        lines[2] = (275.1, [("0:00", 91, 107), ("8:00", 120, 135)] + lines[2][1][2:])
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "time_invalid"))

    def test_impossible_clock_time_falls_back(self):
        lines = good_page()
        lines[2] = (275.1, [("0:00", 55, 71), ("25:00", 91, 107)] + lines[2][1][2:])
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "time_invalid"))

    def test_elapsed_must_match_from_and_to(self):
        lines = good_page()
        lines[2] = data(275.1, "0:00", "8:00", "7.00", "0", "WOD", words("Wait"), mark=False)
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "elapsed_mismatch"))

    def test_a_row_that_runs_past_midnight_and_a_full_day_are_consistent(self):
        lines = [TITLE, HEADER,
                 data(275.1, "19:30", "0:00", "4.50", "0", "WOD", words("Crews at lodge"), mark=True),
                 data(287.1, "0:00", "0:00", "24.00", "0", "WOW", words("weather Delay")),
                 (299.1, [("Management", 256, 311), ("Summary", 314, 355)])]
        [result] = read_page(layer(lines))
        self.assertEqual(result["status"], "rebuilt")

    def test_a_row_after_the_table_ends_is_not_dropped_silently(self):
        lines = good_page() + [data(345.0, "19:00", "21:00", "2.00", "0", "OTHER", words("Orphan row"))]
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "row_count_mismatch"))

    def test_two_marks_in_one_row_fall_back(self):
        lines = good_page()
        lines[4] = continuation(296.3, words("camp, stores tent complete."), mark=True)
        lines[3] = data(287.1, "8:00", "15:00", "7.00", "0", "MOB", words("Fly drill loads to site and stage prior to"), mark=True)
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "x_unmapped"))

    def test_a_lowercase_x_under_non_prod_is_not_trusted(self):
        lines = good_page()
        lines[3] = (287.1, lines[3][1] + [("x", 565, 570)])
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "x_unmapped"))

    def test_a_glyph_missing_from_the_rebuilt_rows_falls_back(self):
        page = layer(good_page())
        page["chars"].append({"text": "Q", "bbox": [300, 288, 306, 297], "index": 999})
        [result] = read_page(page)
        self.assertEqual((result["status"], result["reason"]), ("fallback", "word_mismatch"))

    def test_a_line_stuck_to_the_table_end_is_not_dropped_silently(self):
        # A wrapped description line whose indent differs from the first description word is not a table row, but it
        # sits right under the table and is not a section title: the table is not rebuilt without it.
        lines = good_page()
        lines[-1:] = [(320.3, words("pump and circulate", left=300.0)), (332.3, [("Management", 256, 311), ("Summary", 314, 355)])]
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "trailing_line"))

    def test_a_line_far_below_the_table_or_a_centred_title_is_not_trailing(self):
        lines = good_page()
        lines[-1:] = [(340.3, words("Footer text", left=300.0))]
        self.assertEqual(read_page(layer(lines))[0]["status"], "rebuilt")
        self.assertEqual(read_page(layer(good_page()))[0]["status"], "rebuilt")  # "Management Summary" follows closely

    def test_a_symbol_under_non_prod_is_not_folded_into_the_description(self):
        lines = good_page()
        lines[3] = (287.1, lines[3][1] + [("✓", 565, 570)])
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "x_unmapped"))

    def test_punctuation_under_non_prod_is_description(self):
        # "..." and "-" are printed there as part of wrapped descriptions; they are not mark-like symbols.
        lines = good_page()
        lines[3] = (287.1, lines[3][1] + [("...", 550, 557)])
        lines[2] = (275.1, lines[2][1] + [("-", 550, 553)])
        [result] = read_page(layer(lines))
        self.assertEqual(result["status"], "rebuilt")
        self.assertEqual((result["rows"][0][6], result["rows"][1][6]), ("X", ""))

    def test_a_title_with_a_slash_is_a_section_title(self):
        lines = good_page()
        lines[-1] = (320.3, [("Bit/BHA", 256, 295), ("Information", 298, 355)])
        self.assertEqual(read_page(layer(lines))[0]["status"], "rebuilt")

    def test_a_word_under_non_prod_is_description_not_a_symbol(self):
        lines = good_page()
        lines[3] = (287.1, lines[3][1] + [("and", 545, 560)])
        [result] = read_page(layer(lines))
        self.assertEqual(result["status"], "rebuilt")
        self.assertEqual((result["rows"][1][5].endswith("and camp, stores tent complete."), result["rows"][1][6]), (True, ""))

    def test_elapsed_that_is_not_a_number_of_hours_is_a_column_mismatch(self):
        lines = good_page()
        lines[2] = data(275.1, "0:00", "8:00", "eight", "0", "WOD", words("Wait"))
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "column_mismatch"))

    def test_a_row_without_elapsed_and_depth_is_a_column_mismatch(self):
        lines = good_page()
        lines[2] = (275.1, [("0:00", 55, 71), ("8:00", 91, 107)])
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "column_mismatch"))

    def test_a_header_without_rows_has_no_rows(self):
        [result] = read_page(layer([TITLE, HEADER, (275.1, [("Management", 256, 311), ("Summary", 314, 355)])]))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "no_rows"))

    def test_rotated_pages_are_not_read(self):
        [result] = read_page(layer(good_page(), rotation=90))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "rotated_page"))

    def test_result_is_deterministic(self):
        self.assertEqual(read_page(layer(good_page())), read_page(layer(good_page())))

    def test_every_fallback_reason_is_documented(self):
        for reason in ("no_header", "header_order_mismatch", "time_invalid", "row_count_mismatch", "elapsed_mismatch",
                       "x_unmapped", "word_mismatch", "rotated_page", "no_rows", "column_mismatch", "trailing_line",
                       "ambiguous_docling_match", "docling_multipage", "docling_extent_mismatch"):
            self.assertIn(reason, ops.FALLBACK_REASONS)
        self.assertIn("no_title", ops.FALLBACK_REASONS)

    def test_every_fallback_reason_is_in_the_component_documentation(self):
        documentation = (ROOT / "docs/components/corpus-ingestion.md").read_text(encoding="utf-8")
        for reason in ops.FALLBACK_REASONS:
            self.assertIn(f"`{reason}`", documentation)

    def test_known_limit_an_x_word_in_the_description_under_non_prod_is_taken_as_the_mark(self):
        # A description word that is exactly "X" and sits under the Non-Prod header cannot be told from the mark by
        # geometry. The rule only falls back when a row ends up with more than one such token; this documents it.
        lines = good_page()
        lines[3] = (287.1, lines[3][1] + [("X", 545, 551)])  # row without a real mark
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["rows"][1][6]), ("rebuilt", "X"))
        lines[3] = (287.1, lines[3][1] + [("X", 565, 570)])  # row with a real mark and the description word
        [result] = read_page(layer(lines))
        self.assertEqual((result["status"], result["reason"]), ("fallback", "x_unmapped"))


NOTE = ("1 record not printed", 41.5)


def rows_of(page_lines, **kwargs):
    [result] = read_page(layer(page_lines, **kwargs))
    return result


class RecognitionReadPageTests(unittest.TestCase):
    """What ``read_page`` reports for pages that are close to, but not, the supported format."""

    def outcome(self, lines, rule=None):
        [result] = read_page(layer(lines), rule)
        return result["status"], result["reason"], ops.state_of(result["reason"]) if result["reason"] else None

    def test_a_contents_line_is_not_a_table_even_when_the_title_passes_the_word_gate(self):  # N3
        contents = (251.0, [("5.2", 40, 58), ("Operations", 262, 308), ("Summary", 310, 351), ("12", 520, 540)])
        text = (263.2, words("Overview of the drilling programme", left=48.0))
        self.assertEqual(self.outcome([contents, text]), ("fallback", "no_header", "UNSUPPORTED_FORMAT"))

    def test_a_running_header_with_a_page_number_is_not_a_table(self):  # N4
        header = (251.0, TITLE[1] + [("Page", 387, 407), ("3", 409, 415)])  # 4 em_title right of the title
        text = (263.2, words("This report summarises the operations", left=48.0))
        self.assertEqual(self.outcome([header, text]), ("fallback", "no_header", "UNSUPPORTED_FORMAT"))

    def test_a_line_between_the_title_and_the_header_is_not_supported(self):  # N10
        lines = good_page()
        lines.insert(1, (263.2, words("Foo bar", left=48.0)))
        lines[2] = (275.2, HEADER[1])
        self.assertEqual(self.outcome(lines)[:2], ("fallback", "no_header"))

    def test_a_header_too_far_below_the_title_is_not_adjacent(self):  # N11 through the whole page
        lines = good_page()
        lines[1] = (251.0 + 9.0 + 27.0, HEADER[1])
        self.assertEqual(self.outcome(lines)[:2], ("fallback", "header_not_adjacent"))

    def test_the_real_text_heights_rebuild_with_a_title_gap_of_three_quarters_of_a_title_height(self):  # N6c
        page = real_page(left=NOTE)
        page[0] = (page[0][0], [item for item in page[0][1] if item[0] != "Summary"] + [("Summary", 315.5, 356.5, 10.0)])
        result = rows_of(page)
        self.assertEqual((result["status"], result["reason"]), ("rebuilt", None))

    def test_rotated_pages_report_the_precondition_not_a_gate(self):  # N17
        [result] = read_page(layer(good_page(), rotation=90))
        self.assertEqual((result["status"], result["reason"], result["stage"], ops.state_of(result["reason"])),
                         ("fallback", "rotated_page", "precondition", "UNSUPPORTED_FORMAT"))
        self.assertEqual((result["evidence"]["decision"], result["evidence"]["rejected_at"]), ("rejected", "G0"))

    def test_a_code_that_starts_with_a_digit_is_a_column_mismatch_and_not_loosened(self):  # N18
        lines = good_page()
        lines[3] = data(287.1, "8:00", "15:00", "7.00", "0", "3-2-1", words("Fly drill loads to site and stage prior to"))
        result = rows_of(lines)
        self.assertEqual((result["reason"], result["detail"], ops.state_of(result["reason"])),
                         ("column_mismatch", "Code 3-2-1", "RECOGNISED_BUT_FAILED"))

    def test_the_trailing_line_reason_does_not_depend_on_how_long_the_line_is(self):  # N21
        lines = good_page()
        lines[-1:] = [(320.3, words("pump and circulate", left=300.0))]
        short = rows_of(lines)
        lines[-1:] = [(320.3, words("pump and circulate " + "x" * 90, left=300.0))]
        long = rows_of(lines)
        self.assertEqual((short["reason"], long["reason"]), ("trailing_line", "trailing_line"))
        self.assertLessEqual(len(long["detail"]), 60)

    def test_a_table_after_another_one_with_a_noted_title_does_not_spoil_the_first(self):  # V9, audit rows 2 and 3
        second = real_page(left=NOTE, title_top=421.2)
        results = read_page(layer(real_page() + second))
        self.assertEqual([(r["index"], r["status"], r["reason"]) for r in results], [(1, "rebuilt", None), (2, "rebuilt", None)])
        self.assertEqual([r["completeness"] for r in results], [None, "partial_in_source"])

    def test_a_table_directly_followed_by_the_noted_title_of_the_next_one_is_not_a_trailing_line(self):  # audit row 3
        first = real_page()[:-1]  # no section title between the two tables
        bottom = first[-1][0] + 8.9
        results = read_page(layer(first + real_page(left=NOTE, title_top=bottom + 3.0)))
        self.assertEqual([(r["status"], r["reason"]) for r in results], [("rebuilt", None), ("rebuilt", None)])

    def test_the_section_title_settings_come_from_the_rule(self):
        rule = rule_copy()
        rule["tolerances"]["section_title"]["max_words"] = 1  # "Management Summary" has two words
        [result] = read_page(layer(good_page()), rule)
        self.assertEqual((result["status"], result["reason"]), ("fallback", "trailing_line"))

    def test_an_annotation_of_zero_records_is_recorded_and_says_nothing_is_missing(self):  # N27b
        result = rows_of(real_page(left=("0 records not printed", 41.5)))
        self.assertEqual(result["status"], "rebuilt")
        self.assertEqual([(a["kind"], a["count"]) for a in result["annotations"]], [("records_not_printed", 0)])
        self.assertIsNone(result["completeness"])

    def test_two_annotations_and_the_completeness_priority(self):  # N27c, N27d
        for left, right, expected in ((("2 records not printed", 41.5), ("continued", 480.0), "partial_in_source"),
                                      (("continued", 41.5), ("2 records not printed", 480.0), "partial_in_source"),
                                      (("0 records not printed", 41.5), ("continued", 480.0), "unclassified_annotation"),
                                      (None, ("continued", 480.0), "unclassified_annotation")):
            result = rows_of(real_page(left=left, right=right))
            self.assertEqual((result["status"], result["completeness"]), ("rebuilt", expected))
        self.assertEqual(len(rows_of(real_page(left=("2 records not printed", 41.5), right=("continued", 480.0)))["annotations"]), 2)

    def test_a_pattern_with_a_non_numeric_group_is_an_unclassified_annotation_not_an_error(self):  # N27e
        rule = rule_copy()
        rule["schema"]["annotation_kinds"] = [{"kind": "records_not_printed", "pattern": "^(\\w+) records? not printed$",
                                               "sample": "1 record not printed"}]
        [result] = read_page(layer(real_page(left=("many records not printed", 41.5))), rule)
        self.assertEqual((result["status"], [a["kind"] for a in result["annotations"]], result["completeness"]),
                         ("rebuilt", ["unclassified"], "unclassified_annotation"))

    def test_title_words_with_regex_characters_in_a_page(self):  # N29
        rule = rule_copy()
        rule["schema"]["title_words"] = ["Ops.", "Sum+"]
        page = [(251.0, [("Ops.", 261, 290), ("Sum+", 292, 320)])] + good_page()[1:]
        self.assertEqual(read_page(layer(page), rule)[0]["status"], "rebuilt")
        near = [(251.0, [("OpsX", 261, 290), ("Sum", 292, 320)])] + good_page()[1:]
        self.assertEqual(read_page(layer(near), rule), [])

    def test_the_result_has_evidence_and_the_fields_of_the_contract(self):
        result = rows_of(real_page(left=NOTE))
        self.assertEqual(set(result), {"page", "index", "status", "reason", "detail", "stage", "evidence", "annotations",
                                       "completeness", "rows", "bbox", "span"})
        self.assertEqual(set(result["evidence"]), {"decision", "rejected_at", "title", "header", "rows", "margins"})
        self.assertEqual((result["evidence"]["decision"], result["evidence"]["rejected_at"]), ("recognised", None))
        self.assertNotIn("state", result)  # a page read is not yet validated: only the merge assigns the state
        failed = rows_of(good_page()[:1] + [(263.2, words("Page 3", left=48.0))])
        self.assertEqual((failed["evidence"]["decision"], failed["evidence"]["rejected_at"]), ("rejected", "G2"))

    def test_page_rejections_name_the_sentences_that_were_not_titles(self):
        sentence = (400.0, [("See", 240, 260), ("Operations", 262, 308), ("Summary", 310, 351), ("below", 353, 390)])
        [rejection] = ops.page_rejections(layer(good_page() + [sentence]), OPS_RULE)
        self.assertEqual((rejection["passed"], rejection["reason"], rejection["detail"]), (False, "no_title", "embedded_in_text"))
        self.assertEqual(ops.page_rejections(layer(good_page()), OPS_RULE), [])


class SupportedVariationTests(unittest.TestCase):
    """Variations of the supported format that must be rebuilt to the same table (class-level, synthetic)."""

    def setUp(self):
        self.plain = rows_of(real_page())
        self.assertEqual(self.plain["status"], "rebuilt")

    def same_table(self, page_lines, **kwargs):
        result = rows_of(page_lines, **kwargs)
        self.assertEqual((result["status"], result["reason"]), ("rebuilt", None))
        self.assertEqual(result["rows"], self.plain["rows"])
        return result

    def test_annotation_on_the_left_right_or_both(self):  # V1, V2, V3
        self.assertEqual(self.same_table(real_page(left=NOTE))["completeness"], "partial_in_source")
        self.same_table(real_page(right=("3 records not printed", 480.0)))
        both = self.same_table(real_page(left=NOTE, right=("2 records not printed", 480.0)))
        self.assertEqual([(a["side"], a["count"]) for a in both["annotations"]], [("left", 1), ("right", 2)])

    def test_the_count_and_the_singular_or_plural_noun_are_free(self):  # V4
        for text, count in (("1 record not printed", 1), ("3 records not printed", 3), ("12 records not printed", 12),
                            ("7 RECORDS NOT PRINTED", 7)):
            result = self.same_table(real_page(left=(text, 41.5)))
            self.assertEqual(result["annotations"][0]["count"], count)

    def test_the_annotation_font_may_differ_from_the_title_font(self):  # V5
        page = real_page(left=NOTE)
        page[0] = (page[0][0], [(t, l, r, 7.0) if t not in ("Operations", "Summary") else (t, l, r, h)
                                for t, l, r, h in page[0][1]])
        self.same_table(page)

    def test_the_table_may_be_anywhere_on_the_page(self):  # V6
        def shifted(lines, dx=40.0):
            return [(top, [(item[0], item[1] + dx, item[2] + dx, *item[3:]) for item in spec]) for top, spec in lines[:-1]] + lines[-1:]
        self.same_table(shifted(real_page(left=NOTE)))
        self.same_table(shifted(real_page(), dx=-20.0))

    def test_the_whole_page_may_be_smaller_or_larger(self):  # V7
        for scale in (0.75, 1.5):
            with self.subTest(scale=scale):
                result = self.same_table(real_page(left=NOTE), scale=scale)
                self.assertAlmostEqual(result["bbox"][0], self.plain["bbox"][0] * scale, places=6)

    def test_other_ways_to_split_the_header_words(self):  # V8
        for tail in ([("End MD(ft)", 154, 192, 8.9)], [("End", 154, 169, 8.9), ("MD", 171, 182, 8.9), ("(ft)", 183, 192, 8.9)]):
            page = real_page(left=NOTE)
            page[1] = (page[1][0], sorted([w for w in page[1][1] if w[0] not in ("End", "MD(ft")] + tail, key=lambda w: w[1]))
            self.same_table(page)

    def test_two_tables_on_a_page_the_second_with_an_annotation(self):  # V9
        results = read_page(layer(real_page() + real_page(left=NOTE, title_top=421.2)))
        self.assertEqual([r["status"] for r in results], ["rebuilt", "rebuilt"])
        self.assertEqual(results[0]["rows"], results[1]["rows"])

    def test_a_double_space_inside_the_title(self):  # V10
        page = real_page(left=NOTE)
        page[0] = (page[0][0], [(t, l + (2.5 if t == "Summary" else 0), r + (2.5 if t == "Summary" else 0), h)
                                for t, l, r, h in page[0][1]])
        self.same_table(page)

    def test_another_pair_of_title_words_from_the_configuration(self):  # V11
        rule = rule_copy()
        rule["schema"]["title_words"] = ["Daily", "Totals"]
        page = real_page(left=NOTE)
        page[0] = (page[0][0], [("Daily" if t == "Operations" else "Totals" if t == "Summary" else t, l, r, h)
                                for t, l, r, h in page[0][1]])
        [result] = read_page(layer(page), rule)
        self.assertEqual((result["status"], result["rows"]), ("rebuilt", self.plain["rows"]))
        self.assertEqual(read_page(layer(real_page(left=NOTE)), rule), [])  # the old title is not a title any more
        self.assertEqual(read_page(layer(page)), [])  # and the new one is not a title for the shipped rule

    def test_an_unclassified_annotation_is_accepted_and_flagged(self):  # V12
        result = self.same_table(real_page(left=("continued", 41.5)))
        self.assertEqual((result["annotations"][0]["kind"], result["completeness"]), ("unclassified", "unclassified_annotation"))


class TableChunkTests(unittest.TestCase):
    def table(self, rows=None):
        rows = rows or [["0:00", "8:00", "8.00", "0", "WOD", "Wait | on daylight", "X"],
                        ["8:00", "9:00", "1.00", "0", "MOB", "Fly", ""]]
        return ops.table_record("doc#t0004", "doc", "textlayer:operations_summary:p1:1", 1,
                                {"rows": rows, "bbox": [48, 263.2, 573, 330]}, OPS_RULE)

    def test_record_has_one_header_row_seven_columns_and_docling_like_cells(self):
        table = self.table()
        self.assertEqual((table["num_rows"], table["num_cols"], table["header_rows"]), (3, 7, 1))
        self.assertEqual(table["grid"][0], HEADER_LABELS)
        self.assertEqual(table["grid"][2][6], "")
        self.assertNotIn((2, 6), {(c["r"], c["c"]) for c in table["cells"]})  # empty cells are omitted like Docling does
        self.assertTrue(all(c["is_header"] == (c["r"] == 0) for c in table["cells"]))
        self.assertEqual(table["rows_text"][1], "From: 8:00; To: 9:00; Elapsed: 1.00; End MD(ft): 0; Code: MOB; "
                                                "Operations Description: Fly; Non-Prod: ")

    def test_chunks_repeat_the_header_and_cover_every_row_once(self):
        rows = [[f"{h}:00", f"{h + 1}:00", "1.00", "0", "WOD", "Word " * 12 + str(h), "X" if h % 2 else ""] for h in range(10)]
        table = self.table(rows)
        template = {"doc_id": "doc", "section": "S", "section_path": ["S"], "ocr": False, "quality": "ok"}
        chunks = ops.table_chunks(table, template, 400)
        self.assertGreater(len(chunks), 1)
        header = "| From | To | Elapsed | End MD(ft) | Code | Operations Description | Non-Prod |"
        self.assertTrue(all(c["text"].startswith(header + "\n| --- | --- | --- | --- | --- | --- | --- |") for c in chunks))
        self.assertEqual([(c["row_start"], c["row_end"]) for c in chunks][0][0], 1)
        self.assertEqual(sum(c["row_end"] - c["row_start"] for c in chunks), 10)
        self.assertTrue(all(c["table_id"] == "doc#t0004" and c["type"] == "table" and c["pages"] == [1] for c in chunks))
        self.assertTrue(all(c["source_spans"][0]["end"] == len(c["text"]) for c in chunks))

    def test_pipe_in_a_cell_is_escaped(self):
        self.assertIn("Wait \\| on daylight", ops.markdown(self.table()["grid"]))


def docling_table(logical_id, top, bottom, texts):
    return {"table_id": logical_id, "doc_id": "doc", "source_ref": "#/tables/0", "regions": [{"page": 1, "bbox": [36, top, 575, bottom]}],
            "num_rows": 2, "num_cols": 2, "header_rows": 1,
            "cells": [{"r": 0 if i < 9 else 1, "text": t} for i, t in enumerate(texts)], "rows_text": []}


def corpus_chunk(text, section_path, table_id=None, kind="text", page=1):
    return {"chunk_id": "x", "doc_id": "doc", "type": kind, "text": text, "section": (section_path or [None])[-1],
            "section_path": section_path, "page": page, "pages": [page], "regions": [], "source_spans": [],
            "table_id": table_id, "row_start": None, "row_end": None, "language": "en", "ocr": False, "quality": "ok"}


class RepairDocumentTests(unittest.TestCase):
    def repair(self, lines, chunks, tables, text="Operations Summary"):
        with patch.object(ops, "pdf_page_texts", return_value={1: text}), \
                patch.object(ops, "source_page", return_value=layer(lines)):
            return ops.repair_document(Path("x.pdf"), [1], chunks, tables, "doc", FID, 1500, OPS_RULE)

    def setUp(self):
        self.before = corpus_chunk("Before the table", ["S1"])
        self.mention = corpus_chunk("Non-Prod words", ["S1"])
        self.after = corpus_chunk("After the table", ["S2"])
        self.docling_text = ["From", "To", "Elapsed", "End", "MD(ft)", "Code", "Operations", "Description", "Non-Prod",
                             "0:00", "8:00", "Wait", "on", "daylight"]

    def test_replaces_the_docling_table_in_place_and_keeps_its_id(self):
        other = docling_table("doc#t0000", 500, 600, ["a"])
        old = docling_table("doc#t0001", 259, 360, self.docling_text)
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0001", "table"), self.after]
        out = self.repair(good_page(), chunks, [other, old])
        self.assertEqual([t["table_id"] for t in out["tables"]], ["doc#t0000", "doc#t0001"])
        self.assertEqual(out["tables"][1]["grid"][0], HEADER_LABELS)
        self.assertEqual(out["tables"][0], other)
        self.assertEqual([c["text"] for c in out["chunks"] if c["type"] == "text"], ["Before the table", "After the table"])
        self.assertEqual([c["type"] for c in out["chunks"]], ["text", "table", "text"])
        self.assertEqual(out["chunks"][1]["table_id"], "doc#t0001")
        record = out["records"][0]
        self.assertEqual((record["status"], record["action"], record["table_id"]), ("rebuilt", "replaced", f"{FID}:t2"))

    def test_adds_a_table_docling_missed_after_the_existing_ids(self):
        other = docling_table("doc#t0000", 500, 600, ["a"])
        chunks = [self.before, self.mention, self.after]
        out = self.repair(good_page(), chunks, [other])
        self.assertEqual([t["table_id"] for t in out["tables"]], ["doc#t0000", "doc#t0001"])
        self.assertEqual(out["records"][0]["action"], "added")
        self.assertEqual(out["records"][0]["table_id"], f"{FID}:t2")
        self.assertEqual([c["type"] for c in out["chunks"]], ["text", "text", "table", "text"])  # after the chunk that mentions it
        # The new chunk keeps the section path of the chunk it follows, so section numbering of later chunks is unchanged.
        children, _ = map_children(FID, "doc", "daily_report", out["chunks"],
                                   [{"logical_id": "doc#t0001", "table_id": f"{FID}:t2", "pages": [1]}], [], {})
        self.assertEqual([c["parent_id"] for c in children], [f"{FID}:s1", f"{FID}:s1", f"{FID}:t2", f"{FID}:s2"])
        self.assertEqual(children[2]["chunk_id"], f"{FID}:t2:c0")

    def test_fallback_keeps_everything_and_records_the_reason(self):
        old = docling_table("doc#t0000", 259, 360, self.docling_text)
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        lines = good_page()
        lines[1] = (263.2, [("Nothing", 48, 90)])
        out = self.repair(lines, copy.deepcopy(chunks), [old])
        self.assertEqual(out["chunks"], chunks)
        self.assertEqual(out["tables"], [old])
        self.assertEqual((out["records"][0]["status"], out["records"][0]["reason"], out["records"][0]["action"]),
                         ("fallback", "no_header", "kept_docling"))

    def test_docling_table_with_foreign_content_is_kept(self):
        old = docling_table("doc#t0000", 259, 360, self.docling_text + ["Totally", "unrelated", "words"])
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        out = self.repair(good_page(), copy.deepcopy(chunks), [old])
        self.assertEqual((out["tables"], out["chunks"]), ([old], chunks))
        self.assertEqual(out["records"][0]["reason"], "docling_extent_mismatch")

    def test_two_docling_tables_on_the_region_are_ambiguous(self):
        first = docling_table("doc#t0000", 259, 300, self.docling_text[:9])
        second = docling_table("doc#t0001", 300, 330, self.docling_text[9:])
        chunks = [corpus_chunk("| a |", ["S1"], "doc#t0000", "table"), corpus_chunk("| b |", ["S1"], "doc#t0001", "table")]
        out = self.repair(good_page(), copy.deepcopy(chunks), [first, second])
        self.assertEqual((out["tables"], out["chunks"]), ([first, second], chunks))
        self.assertEqual(out["records"][0]["reason"], "ambiguous_docling_match")

    def test_a_docling_table_that_only_partly_overlaps_is_ambiguous_not_duplicated(self):
        # The rebuilt table spans y 251 to 317; this Docling table starts at 300, so it is neither inside nor around it.
        old = docling_table("doc#t0000", 300, 500, self.docling_text)
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        out = self.repair(good_page(), copy.deepcopy(chunks), [old])
        self.assertEqual((out["tables"], out["chunks"]), ([old], chunks))
        self.assertEqual((out["records"][0]["status"], out["records"][0]["reason"], out["records"][0]["action"]),
                         ("fallback", "ambiguous_docling_match", "kept_docling"))

    def test_a_docling_table_on_another_part_of_the_page_does_not_matter(self):
        other = docling_table("doc#t0000", 500, 600, ["a"])
        out = self.repair(good_page(), [self.before, self.mention, self.after], [other])
        self.assertEqual((out["records"][0]["status"], out["records"][0]["action"]), ("rebuilt", "added"))

    def test_a_docling_table_over_two_pages_is_kept(self):
        old = docling_table("doc#t0000", 259, 360, self.docling_text)
        old["regions"].append({"page": 2, "bbox": [36, 50, 575, 200]})
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        out = self.repair(good_page(), copy.deepcopy(chunks), [old])
        self.assertEqual((out["tables"], out["chunks"]), ([old], chunks))
        self.assertEqual(out["records"][0]["reason"], "docling_multipage")

    def test_chunks_of_the_docling_table_that_are_not_adjacent_are_kept(self):
        old = docling_table("doc#t0000", 259, 360, self.docling_text)
        chunks = [corpus_chunk("| a |", ["S1"], "doc#t0000", "table"), self.before, corpus_chunk("| b |", ["S1"], "doc#t0000", "table")]
        out = self.repair(good_page(), copy.deepcopy(chunks), [old])
        self.assertEqual((out["tables"], out["chunks"]), ([old], chunks))
        self.assertEqual((out["records"][0]["reason"], out["records"][0]["detail"]),
                         ("docling_multipage", "chunks of the table are not contiguous"))

    def test_a_page_that_mentions_the_title_without_a_title_line_leaves_a_no_title_record(self):
        old = docling_table("doc#t0000", 259, 360, self.docling_text)
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        lines = good_page()
        lines[0] = (251.0, [("See", 240, 260), ("Operations", 262, 308), ("Summary", 310, 351), ("below", 353, 390)])
        out = self.repair(lines, copy.deepcopy(chunks), [old])
        self.assertEqual((out["tables"], out["chunks"]), ([old], chunks))
        [record] = out["records"]
        self.assertEqual((record["status"], record["reason"], record["action"], record["table_id"], record["page"]),
                         ("fallback", "no_title", "kept_docling", None, 1))
        self.assertIn("1 Docling table(s)", record["detail"])

    def test_a_docling_operations_table_on_a_page_without_the_title_text_leaves_a_no_title_record(self):
        old = docling_table("doc#t0000", 259, 360, self.docling_text)
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        with patch.object(ops, "pdf_page_texts", return_value={1: "Continuation of the table"}), \
                patch.object(ops, "source_page", side_effect=AssertionError("must not read")):
            out = ops.repair_document(Path("x.pdf"), [1], copy.deepcopy(chunks), [old], "doc", FID, 1500, OPS_RULE)
        self.assertEqual((out["tables"], out["chunks"]), ([old], chunks))
        [record] = out["records"]
        self.assertEqual((record["reason"], record["action"]), ("no_title", "kept_docling"))
        self.assertIn("no 'Operations Summary' text", record["detail"])

    def test_a_page_with_a_docling_table_that_is_not_operations_leaves_no_record(self):
        other = docling_table("doc#t0000", 259, 360, ["a", "b"])
        with patch.object(ops, "pdf_page_texts", return_value={1: "Daily report"}), \
                patch.object(ops, "source_page", side_effect=AssertionError("must not read")):
            out = ops.repair_document(Path("x.pdf"), [1], [self.before], [other], "doc", FID, 1500, OPS_RULE)
        self.assertEqual(out["records"], [])

    def test_a_rebuilt_page_does_not_get_a_second_no_title_record(self):
        old = docling_table("doc#t0000", 259, 360, self.docling_text)
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        out = self.repair(good_page(), chunks, [old])
        self.assertEqual([(r["status"], r["reason"]) for r in out["records"]], [("rebuilt", None)])

    def test_pages_without_the_title_are_not_read(self):
        with patch.object(ops, "pdf_page_texts", return_value={1: "Daily report"}), \
                patch.object(ops, "source_page", side_effect=AssertionError("must not read")):
            out = ops.repair_document(Path("x.pdf"), [1], [self.before], [], "doc", FID, 1500, OPS_RULE)
        self.assertEqual((out["records"], out["chunks"], out["tables"]), ([], [self.before], []))


SENTENCE = (400.0, [("See", 240, 260), ("Operations", 262, 308), ("Summary", 310, 351), ("below", 353, 390)])


class RepairStateTests(unittest.TestCase):
    """The sidecar record of ``repair_document``: state, index, rejected mentions, annotations and isolation of errors."""

    def setUp(self):
        self.before = corpus_chunk("Before the table", ["S1"])
        self.mention = corpus_chunk("Non-Prod words", ["S1"])
        self.after = corpus_chunk("After the table", ["S2"])
        self.chunks = [self.before, self.mention, self.after]
        self.docling_text = ["From", "To", "Elapsed", "End", "MD(ft)", "Code", "Operations", "Description", "Non-Prod",
                             "0:00", "8:00", "Wait", "on", "daylight"]

    def repair(self, lines, chunks=None, tables=None, text="Operations Summary", rule=None):
        with patch.object(ops, "pdf_page_texts", return_value={1: text}), \
                patch.object(ops, "source_page", return_value=layer(lines)):
            return ops.repair_document(Path("x.pdf"), [1], list(self.chunks if chunks is None else chunks),
                                       list([] if tables is None else tables), "doc", FID, 1500, OPS_RULE if rule is None else rule)

    def test_a_merged_table_is_supported_and_validated_with_its_evidence(self):
        out = self.repair(real_page(left=NOTE))
        [record] = out["records"]
        self.assertEqual((record["state"], record["stage"], record["status"], record["reason"], record["action"]),
                         ("SUPPORTED_AND_VALIDATED", "merge", "rebuilt", None, "added"))
        self.assertEqual((record["index"], record["rejected_mentions"], record["completeness"]), (1, 0, "partial_in_source"))
        self.assertEqual(record["annotations"][0]["text"], "1 record not printed")
        self.assertEqual(record["evidence"]["decision"], "recognised")

    def test_a_sentence_that_names_the_table_next_to_a_header_is_a_rejected_mention(self):  # N1
        old = docling_table("doc#t0000", 259, 360, self.docling_text)
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        out = self.repair([(251.0, SENTENCE[1]), HEADER], chunks, [old])
        self.assertEqual((out["tables"], out["chunks"]), ([old], chunks))
        [record] = out["records"]
        self.assertEqual((record["state"], record["reason"], record["rejected_mentions"], record["index"]),
                         ("UNSUPPORTED_FORMAT", "no_title", 1, 1))
        self.assertTrue(record["detail"].startswith("embedded_in_text; 1 Docling table(s)"))
        self.assertEqual(record["evidence"]["rejected_at"], "G1")

    def test_a_docling_table_without_any_title_text_has_no_rejected_mention(self):  # N5, N9 (ii)
        old = docling_table("doc#t0000", 259, 360, self.docling_text)
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        for text in ("Continuation of the table", "Operations"):
            with patch.object(ops, "pdf_page_texts", return_value={1: text}), \
                    patch.object(ops, "source_page", side_effect=AssertionError("must not read")):
                out = ops.repair_document(Path("x.pdf"), [1], list(chunks), [old], "doc", FID, 1500, OPS_RULE)
            [record] = out["records"]
            self.assertEqual((record["state"], record["reason"], record["rejected_mentions"]), ("UNSUPPORTED_FORMAT", "no_title", 0))
            self.assertIn("no 'Operations Summary' text on the page; 1 Docling table(s)", record["detail"])

    def test_title_text_in_the_page_text_without_a_mention_line_is_not_found(self):  # N9 (iv)
        out = self.repair([HEADER])
        [record] = out["records"]
        self.assertTrue(record["detail"].startswith("not_found; 0 Docling table(s)"))
        self.assertEqual((record["reason"], record["rejected_mentions"], record["state"]), ("no_title", 0, "UNSUPPORTED_FORMAT"))

    def test_a_non_operations_docling_table_next_to_a_noted_title_is_left_alone(self):  # N22
        other = docling_table("doc#t0000", 500, 600, ["a", "b"])
        out = self.repair(real_page(left=NOTE), tables=[other])
        self.assertEqual(out["tables"][0], other)
        self.assertEqual(len(out["records"]), 1)
        self.assertEqual(out["records"][0]["action"], "added")

    def test_two_runs_give_the_same_records_and_a_different_rule_leaves_no_trace(self):  # N24
        first = self.repair(real_page(left=NOTE))
        other_rule = rule_copy()
        other_rule["schema"]["title_words"] = ["Totals", "Summary"]
        self.assertEqual(self.repair(real_page(left=NOTE), rule=other_rule)["records"], [])
        self.assertEqual(self.repair(real_page(left=NOTE)), first)

    def test_a_note_on_its_own_line_right_above_the_title_is_only_a_hint(self):  # N25, N25b, N25c
        page = real_page()
        plain = self.repair(page)
        above = [(208.0, [(w, x, x + 4.4 * len(w), 8.9) for w, x in annotation_words(("2 records not printed", 41.5))])]
        flagged = self.repair(above + page)
        [record] = flagged["records"]
        self.assertEqual((record["state"], record["completeness"]), ("SUPPORTED_AND_VALIDATED", "partial_in_source"))
        self.assertEqual([(a["side"], a["owner"], a["count"]) for a in record["annotations"]], [("above", "uncertain", 2)])
        self.assertEqual((flagged["tables"], flagged["chunks"]), (plain["tables"], plain["chunks"]))  # the table is the same
        comment = [(208.0, [("Comments:", 41.5, 90.0, 8.9), ("some", 92.0, 115.0, 8.9), ("text", 117.0, 137.0, 8.9)])]
        [record] = self.repair(comment + page)["records"]
        self.assertEqual((record["state"], record["annotations"], record["completeness"]), ("SUPPORTED_AND_VALIDATED", [], None))
        far = [(190.0, above[0][1])]  # farther than the line gap: not detected, and the test says so
        [record] = self.repair(far + page)["records"]
        self.assertEqual((record["state"], record["annotations"], record["completeness"]), ("SUPPORTED_AND_VALIDATED", [], None))

    def test_a_valid_table_and_a_sentence_on_one_page_give_one_record(self):  # N26
        out = self.repair(real_page() + [SENTENCE])
        [record] = out["records"]
        self.assertEqual((record["state"], record["index"], record["rejected_mentions"]), ("SUPPORTED_AND_VALIDATED", 1, 1))
        self.assertEqual(out["tables"][-1]["source_ref"], "textlayer:operations_summary:p1:1")

    def test_a_page_with_only_a_sentence_and_another_tables_header_gives_one_no_title_record(self):  # N26b
        out = self.repair([SENTENCE, (420.0, HEADER[1])])
        [record] = out["records"]
        self.assertEqual((record["state"], record["reason"], record["index"], record["rejected_mentions"]),
                         ("UNSUPPORTED_FORMAT", "no_title", 1, 1))
        self.assertTrue(record["detail"].startswith("embedded_in_text"))

    def test_lines_with_one_title_word_are_never_counted(self):  # N28
        wrong_order = (420.0, [("Summary", 40, 90), ("Operations", 92, 150)])
        out = self.repair(real_page() + [wrong_order])
        [record] = out["records"]
        self.assertEqual((record["state"], record["rejected_mentions"]), ("SUPPORTED_AND_VALIDATED", 0))
        self.assertEqual(ops.page_rejections(layer(real_page() + [wrong_order]), OPS_RULE), [])

    def test_the_index_counts_only_accepted_titles(self):
        out = self.repair(real_page() + real_page(left=NOTE, title_top=421.2) + [(600.0, SENTENCE[1])])
        self.assertEqual([(r["index"], r["rejected_mentions"]) for r in out["records"]], [(1, 1), (2, 0)])
        self.assertEqual([t["source_ref"] for t in out["tables"]],
                         ["textlayer:operations_summary:p1:1", "textlayer:operations_summary:p1:2"])

    def test_failed_merge_checks_carry_the_state_of_their_reason(self):
        old = docling_table("doc#t0000", 259, 360, self.docling_text + ["Totally", "unrelated", "words"])
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        out = self.repair(good_page(), chunks, [old])
        [record] = out["records"]
        self.assertEqual((record["state"], record["stage"], record["reason"], record["status"]),
                         ("RECOGNISED_BUT_FAILED", "merge", "docling_extent_mismatch", "fallback"))

    def test_no_valid_page_produces_a_parsing_failure(self):  # R2-7 at test level
        for lines in (good_page(), real_page(), real_page(left=NOTE), real_page(right=("3 records not printed", 480.0))):
            [record] = self.repair(lines)["records"]
            self.assertNotEqual(record["state"], "PARSING_FAILURE")

    def test_an_unreadable_page_is_recorded_and_the_other_pages_are_processed(self):  # N23
        def reader(path, number):
            if number == 1:
                raise RuntimeError("broken page")
            return layer(real_page())

        with patch.object(ops, "pdf_page_texts", return_value={1: "Operations Summary", 2: "Operations Summary"}), \
                patch.object(ops, "source_page", side_effect=reader), self.assertLogs(ops.LOGGER, "WARNING"):
            out = ops.repair_document(Path("x.pdf"), [1, 2], list(self.chunks), [], "doc", FID, 1500, OPS_RULE)
        first, second = out["records"]
        self.assertEqual((first["page"], first["state"], first["reason"], first["detail"], first["action"]),
                         (1, "PARSING_FAILURE", "text_layer_read_error", "RuntimeError", "kept_docling"))
        self.assertEqual((second["page"], second["state"], second["action"]), (2, "SUPPORTED_AND_VALIDATED", "added"))
        self.assertEqual(len(out["tables"]), 1)
        self.assertNotIn("broken page", json.dumps(out["records"]))  # no message, no path: the sidecar stays deterministic

    def test_an_error_while_recognising_a_page_is_recorded(self):  # N23
        with patch.object(ops.recognition, "mention_lines", side_effect=ValueError("bad")), self.assertLogs(ops.LOGGER, "WARNING"):
            out = self.repair(real_page())
        [record] = out["records"]
        self.assertEqual((record["state"], record["reason"], record["detail"]), ("PARSING_FAILURE", "rule_exception", "ValueError@recognition"))
        self.assertEqual((out["tables"], out["chunks"]), ([], self.chunks))

    def test_an_error_in_one_table_does_not_stop_the_next_table_of_the_page(self):  # N23
        original = ops.read_row
        calls = {"n": 0}

        def failing_once(line, zones, rule):
            calls["n"] += 1
            if calls["n"] == 1:
                raise KeyError("defect")
            return original(line, zones, rule)

        with patch.object(ops, "read_row", side_effect=failing_once), self.assertLogs(ops.LOGGER, "WARNING"):
            out = self.repair(real_page() + real_page(title_top=421.2))
        self.assertEqual([(r["state"], r["reason"], r["detail"]) for r in out["records"]],
                         [("PARSING_FAILURE", "rule_exception", "KeyError@read"), ("SUPPORTED_AND_VALIDATED", None, "")])
        self.assertEqual(len(out["tables"]), 1)

    def test_a_failing_merge_keeps_the_chunks_and_tables_of_the_document(self):  # N23
        old = docling_table("doc#t0000", 215, 300, self.docling_text)
        chunks = [self.before, corpus_chunk("| junk |", ["S1"], "doc#t0000", "table")]
        with patch.object(ops, "table_chunks", side_effect=RuntimeError("no chunks")), self.assertLogs(ops.LOGGER, "WARNING"):
            out = self.repair(real_page(), copy.deepcopy(chunks), [old])
        [record] = out["records"]
        self.assertEqual((record["state"], record["reason"], record["detail"], record["action"], record["table_id"]),
                         ("PARSING_FAILURE", "merge_exception", "RuntimeError@merge", "kept_docling", None))
        self.assertEqual((out["tables"], out["chunks"]), ([old], chunks))

    def test_a_memory_error_is_not_swallowed(self):  # N23
        with patch.object(ops, "source_page", side_effect=MemoryError()), self.assertRaises(MemoryError):
            with patch.object(ops, "pdf_page_texts", return_value={1: "Operations Summary"}):
                ops.repair_document(Path("x.pdf"), [1], list(self.chunks), [], "doc", FID, 1500, OPS_RULE)
        with patch.object(ops, "table_chunks", side_effect=MemoryError()), self.assertRaises(MemoryError):
            self.repair(real_page())


class FamilySummaryTests(unittest.TestCase):
    def record(self, state, reason=None, family="daily_report", above=False):
        return {"document_type": family, "rule": "operations_summary", "state": state, "reason": reason,
                "annotations": [{"side": "above"}] if above else []}

    def test_counts_per_family_state_and_reason(self):  # N30
        records = [self.record("SUPPORTED_AND_VALIDATED") for _ in range(8)] + [
            self.record("UNSUPPORTED_FORMAT", "no_title"), self.record("PARSING_FAILURE", "rule_exception", above=True)]
        summary = ops.family_summary(records)["daily_report/operations_summary"]
        self.assertEqual((summary["records"], summary["parsing_failure_rate"], summary["annotations_above"]), (10, 0.1, 1))
        self.assertEqual(summary["by_state"], {"SUPPORTED_AND_VALIDATED": 8, "UNSUPPORTED_FORMAT": 1, "PARSING_FAILURE": 1})
        self.assertEqual(summary["by_state_reason"]["PARSING_FAILURE/rule_exception"], 1)
        clean = ops.family_summary([self.record("SUPPORTED_AND_VALIDATED") for _ in range(10)])
        self.assertEqual(clean["daily_report/operations_summary"]["parsing_failure_rate"], 0.0)

    def test_families_are_kept_apart(self):
        summary = ops.family_summary([self.record("SUPPORTED_AND_VALIDATED"), self.record("PARSING_FAILURE", "rule_exception", family="eowr")])
        self.assertEqual(sorted(summary), ["daily_report/operations_summary", "eowr/operations_summary"])
        self.assertEqual(summary["daily_report/operations_summary"]["parsing_failure_rate"], 0.0)
        self.assertEqual(summary["eowr/operations_summary"]["parsing_failure_rate"], 1.0)
        self.assertEqual(ops.family_summary([]), {})


class IntegrationTests(unittest.TestCase):
    def test_k1_table_from_a_rebuilt_record_needs_no_docling_item(self):
        record = ops.table_record("doc#t0001", "doc", "textlayer:operations_summary:p1:1", 1,
                                  {"rows": [["0:00", "8:00", "8.00", "0", "WOD", "Wait", "X"]], "bbox": [48, 263.2, 573, 300]}, OPS_RULE)
        [table] = logical_tables([record], None, FID, "doc")
        self.assertEqual(table["table_id"], f"{FID}:t1")
        self.assertEqual(table["logical_id"], "doc#t0001")
        self.assertEqual(table["grid"][1][6], "X")
        self.assertEqual(table["parts"][0]["source_ref"], "textlayer:operations_summary:p1:1")
        self.assertEqual(table["parts"][0]["header"], [HEADER_LABELS])
        self.assertEqual(table["join"], {"status": "single", "reasons": []})
        self.assertEqual(table["regions"], [{"page": 1, "bbox": [48, 263.2, 573, 300]}])

    def test_shipped_configuration_enables_the_rule_for_daily_reports_only(self):
        config = load_k1_config()
        rule = config["table_rules"]["operations_summary"]
        self.assertEqual(rule["document_types"], ["daily_report"])
        self.assertEqual(set(rule), {"document_types", "schema", "recognition", "tolerances"})

    def test_table_rules_are_optional_and_validated(self):
        config = load_k1_config()
        without = {key: value for key, value in config.items() if key != "table_rules"}
        self.assertEqual(validate_k1_config(without), without)
        for bad in ({"unknown": {"document_types": ["daily_report"]}}, {"operations_summary": {}}, {"operations_summary": {"document_types": ["daily_report"]}},
                    {"operations_summary": {"document_types": []}}, {"operations_summary": {"document_types": ["a"], "x": 1}},
                    {"operations_summary": "daily_report"}):
            with self.assertRaises(ValueError):
                validate_k1_config({**config, "table_rules": bad})


def load_harness():
    spec = importlib.util.spec_from_file_location("evaluate_ops_tables", ROOT / "scripts/evaluate_ops_tables.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HarnessTests(unittest.TestCase):
    """The held-out lock and the metrics of scripts/evaluate_ops_tables.py (no PDF is opened)."""

    def setUp(self):
        self.harness = load_harness()
        self.scratch = ROOT / "data/interim/ops-rebuild/_test_lock"
        shutil.rmtree(self.scratch, ignore_errors=True)
        (self.scratch / "release").mkdir(parents=True)
        (self.scratch / "release/SHA256SUMS").write_text("abc  manifest.json\n", encoding="utf-8")
        self.harness.LOCK = self.scratch / "heldout-run.json"
        self.harness.FREEZE = self.scratch / "dev-freeze.json"
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def complete_release(self):
        """A release with the three attachments listed and an empty tables.jsonl, plus a raw dir with their PDFs."""
        release, raw = self.scratch / "release", self.scratch / "raw"
        raw.mkdir(exist_ok=True)
        files = [{"file_id": f"f{n}", "doc_id": f"gdr-appx-{n}-report", "original_name": f"appx_{n}.pdf"} for n in (27, 28, 30)]
        (release / "files.jsonl").write_text("".join(json.dumps(f) + "\n" for f in files), encoding="utf-8")
        (release / "tables.jsonl").write_text("", encoding="utf-8")
        for f in files:
            (raw / f["original_name"]).write_bytes(b"%PDF")
        return release, raw

    def heldout_args(self, release, raw, *extra):
        return ["--release", f"after={release}", "--split", "heldout", "--final", "--raw", str(raw),
                "--out", str(self.scratch / "heldout-results.json"), *extra]

    def test_a_failed_preflight_does_not_take_the_heldout_lock(self):
        release, raw = self.scratch / "release", self.scratch / "raw"
        with patch.dict("sys.modules", {"fitz": None}), self.assertRaisesRegex(SystemExit, "PyMuPDF"):
            self.harness.main(self.heldout_args(release, raw))
        self.assertFalse(self.harness.LOCK.exists())
        fake = types.ModuleType("fitz")
        with patch.dict("sys.modules", {"fitz": fake}):
            with self.assertRaisesRegex(SystemExit, "no files.jsonl"):
                self.harness.main(self.heldout_args(release, raw))
            self.assertFalse(self.harness.LOCK.exists())
            release, raw = self.complete_release()
            shutil.rmtree(raw)
            raw.mkdir()  # PDFs missing
            with self.assertRaisesRegex(SystemExit, "PDF .* not found"):
                self.harness.main(self.heldout_args(release, raw))
        self.assertFalse(self.harness.LOCK.exists())

    def test_an_error_while_reading_the_pdfs_does_not_take_the_heldout_lock(self):
        release, raw = self.complete_release()
        with patch.dict("sys.modules", {"fitz": types.ModuleType("fitz")}), \
                patch.object(self.harness, "scan_pdfs", side_effect=RuntimeError("broken PDF")):
            with self.assertRaisesRegex(RuntimeError, "broken PDF"):
                self.harness.main(self.heldout_args(release, raw))
        self.assertFalse(self.harness.LOCK.exists())

    def test_heldout_run_writes_lock_and_results_together_and_refuses_a_second_run(self):
        release, raw = self.complete_release()
        with patch.dict("sys.modules", {"fitz": types.ModuleType("fitz")}), \
                patch.object(self.harness, "scan_pdfs", return_value=({}, {})):
            self.assertEqual(self.harness.main(self.heldout_args(release, raw)), 0)
            self.assertTrue(self.harness.LOCK.exists() and (self.scratch / "heldout-results.json").exists())
            with self.assertRaisesRegex(SystemExit, "already evaluated"):
                self.harness.main(self.heldout_args(release, raw))
            self.assertEqual(self.harness.main(self.heldout_args(release, raw, "--new-round")), 0)
        self.assertEqual([r["independent"] for r in json.loads(self.harness.LOCK.read_text(encoding="utf-8"))["rounds"]], [True, False])

    def test_the_lock_records_what_changed_since_the_dev_freeze(self):
        release = self.scratch / "release"
        self.harness.take_lock(release, new_round=False)
        first = json.loads(self.harness.LOCK.read_text(encoding="utf-8"))["rounds"][0]
        self.assertIn("no dev-freeze.json", first["changed_since_dev_freeze"])
        self.harness.LOCK.unlink()
        self.harness.write_freeze()
        self.harness.take_lock(release, new_round=False)
        self.assertEqual(json.loads(self.harness.LOCK.read_text(encoding="utf-8"))["rounds"][0]["changed_since_dev_freeze"], [])
        frozen = json.loads(self.harness.FREEZE.read_text(encoding="utf-8"))
        frozen["sources_sha256"]["src/graph_builder/corpus/ops_tables.py"] = "0" * 64
        self.harness.FREEZE.write_text(json.dumps(frozen), encoding="utf-8")
        self.harness.LOCK.unlink()
        self.harness.take_lock(release, new_round=False)
        self.assertEqual(json.loads(self.harness.LOCK.read_text(encoding="utf-8"))["rounds"][0]["changed_since_dev_freeze"],
                         ["src/graph_builder/corpus/ops_tables.py"])

    def test_a_failure_writing_the_results_or_the_lock_leaves_neither_lock_nor_partial_results(self):
        release, raw = self.complete_release()
        results = self.scratch / "heldout-results.json"
        with patch.dict("sys.modules", {"fitz": types.ModuleType("fitz")}), \
                patch.object(self.harness, "scan_pdfs", return_value=({}, {})):
            blocker = self.scratch / "blocker"
            blocker.write_text("a file, not a directory", encoding="utf-8")
            args = self.heldout_args(release, raw)
            args[args.index("--out") + 1] = str(blocker / "results.json")
            with self.assertRaises(OSError):
                self.harness.main(args)
            self.assertFalse(self.harness.LOCK.exists())
            with patch.object(self.harness, "write_lock", side_effect=OSError("disk full")), self.assertRaises(OSError):
                self.harness.main(self.heldout_args(release, raw))
        self.assertFalse(self.harness.LOCK.exists())
        self.assertEqual([p.name for p in self.scratch.glob("heldout-results.json*")], [])
        self.assertFalse(results.exists())

    def test_dates_are_split_without_overlap_and_cover_27_days(self):
        development, heldout = set(self.harness.DEVELOPMENT), set(self.harness.HELDOUT)
        self.assertEqual((len(development), len(heldout), development & heldout), (18, 9, set()))

    def test_heldout_needs_final_and_is_refused_a_second_time(self):
        release = self.scratch / "release"
        with self.assertRaises(SystemExit):
            self.harness.main(["--release", f"after={release}", "--split", "heldout"])
        self.assertFalse(self.harness.LOCK.exists())
        self.harness.take_lock(release, new_round=False)
        first = json.loads(self.harness.LOCK.read_text(encoding="utf-8"))["rounds"]
        self.assertEqual((len(first), first[0]["independent"]), (1, True))
        self.assertIn("src/graph_builder/corpus/ops_tables.py", first[0]["sources_sha256"])
        with self.assertRaisesRegex(SystemExit, "already evaluated"):
            self.harness.take_lock(release, new_round=False)

    def test_new_round_is_recorded_as_not_independent(self):
        release = self.scratch / "release"
        with self.assertRaisesRegex(SystemExit, "earlier held-out run"):
            self.harness.take_lock(release, new_round=True)
        self.harness.take_lock(release, new_round=False)
        self.harness.take_lock(release, new_round=True)
        rounds = json.loads(self.harness.LOCK.read_text(encoding="utf-8"))["rounds"]
        self.assertEqual([r["independent"] for r in rounds], [True, False])
        self.assertEqual(rounds[1]["note"], "new development round: held-out no longer independent")

    def test_table_metrics_count_marks_spill_and_lost_rows(self):
        truth = {"rows": [{"from": "0:00", "to": "8:00", "elapsed": "8.00", "end_md": "0", "code": "WOD", "x": True,
                           "description": "Wait on daylight"},
                          {"from": "8:00", "to": "9:00", "elapsed": "1.00", "end_md": "0", "code": "MOB", "x": False,
                           "description": "Fly loads"}]}
        good = {"table_id": "t", "grid": [list(self.harness.HEADER), ["0:00", "8:00", "8.00", "0", "WOD", "Wait on daylight", "X"],
                                          ["8:00", "9:00", "1.00", "0", "MOB", "Fly loads", ""]], "header_rows": 1, "num_cols": 7}
        result = self.harness.evaluate_table(truth, good)
        self.assertEqual((result["header_ok"], result["lost_rows"], result["x_ok"], result["description_ok"], result["spill_rows"]),
                         (True, 0, 1, 2, 0))
        bad = copy.deepcopy(good)
        bad["grid"][1][6] = "daylight"
        bad["grid"][2][5] = "Fly"
        bad["grid"][2] = bad["grid"][2][:6] + ["loads"]
        result = self.harness.evaluate_table(truth, bad)
        # Description tokens are taken over every column from the sixth on, so spill is counted separately (spill_rows).
        self.assertEqual((result["x_lost"], result["spill_rows"], result["description_ok"]), (1, 2, 1))
        self.assertEqual(self.harness.evaluate_table(truth, None)["status"], "missing")
        merged = {"table_id": "t", "grid": [["From", "To", "Elapsed", "End MD(ft)", "Code", "Operations Description Non-Prod"],
                                           ["0:00", "8:00", "8.00", "0", "WOD", "Wait on daylight", "X"]], "header_rows": 1, "num_cols": 7}
        result = self.harness.evaluate_table(truth, merged)
        self.assertEqual((result["merged_header"], result["header_ok"], result["lost_rows"]), (True, False, 1))


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Round2HarnessTests(unittest.TestCase):
    """What scripts/evaluate_ops_tables.py adds in Round 2 (no PDF is opened)."""

    def setUp(self):
        self.harness = load_harness()
        self.scratch = ROOT / "data/interim/ops-rebuild-r2/_test_harness"
        shutil.rmtree(self.scratch, ignore_errors=True)
        (self.scratch / "release").mkdir(parents=True)
        (self.scratch / "release/SHA256SUMS").write_text("abc  manifest.json\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def test_the_default_lock_and_freeze_stay_in_the_round_one_folder(self):
        self.assertEqual(self.harness.LOCK, ROOT / "data/interim/ops-rebuild/heldout-run.json")
        self.assertEqual(self.harness.FREEZE, ROOT / "data/interim/ops-rebuild/dev-freeze.json")

    def test_the_sources_in_the_freeze_include_the_new_modules_and_tests(self):
        names = set(self.harness.source_digests())
        for name in ("src/graph_builder/corpus/table_recognition.py", "src/graph_builder/corpus/ops_tables.py",
                     "tests/ops_fixtures.py", "tests/test_ops_config.py", "tests/test_table_recognition.py",
                     "tests/test_ops_real_pdfs.py", "docs/components/corpus-ingestion.md", "configs/corpus/k1.json"):
            self.assertIn(name, names)

    def test_a_round_two_lock_is_a_copy_of_the_round_one_lock_and_is_not_independent(self):
        release = self.scratch / "release"
        round_one = self.scratch / "round1-lock.json"
        self.harness.LOCK = round_one
        self.harness.take_lock(release, new_round=False)
        before = round_one.read_bytes()
        lock = self.scratch / "r2" / "lock.json"
        self.harness.LOCK = lock
        lock.parent.mkdir()
        shutil.copyfile(round_one, lock)  # what --seed-lock does
        self.harness.take_lock(release, new_round=True)
        self.assertEqual(round_one.read_bytes(), before)  # the Round 1 lock is untouched
        self.assertEqual([r["independent"] for r in json.loads(lock.read_text(encoding="utf-8"))["rounds"]], [True, False])

    def test_main_seeds_the_round_two_lock_from_a_copy_and_labels_the_data(self):
        release = self.scratch / "release"
        round_one = self.scratch / "round1-lock.json"
        self.harness.LOCK = round_one
        self.harness.take_lock(release, new_round=False)
        before = round_one.read_bytes()
        lock, freeze = self.scratch / "r2/lock.json", self.scratch / "r2/freeze.json"
        out = self.scratch / "r2/results.json"
        files = [{"file_id": f"f{n}", "doc_id": f"gdr-appx-{n}-report", "original_name": f"appx_{n}.pdf"} for n in (27, 28, 30)]
        (release / "files.jsonl").write_text("".join(json.dumps(f) + "\n" for f in files), encoding="utf-8")
        (release / "tables.jsonl").write_text("", encoding="utf-8")
        raw = self.scratch / "raw"
        raw.mkdir()
        for f in files:
            (raw / f["original_name"]).write_bytes(b"%PDF")
        self.harness.LOCK = round_one  # main() must switch to --lock without touching this file
        with patch.dict("sys.modules", {"fitz": types.ModuleType("fitz")}), \
                patch.object(self.harness, "scan_pdfs", return_value=({}, {})):
            self.assertEqual(self.harness.main(["--release", f"after={release}", "--split", "all", "--final", "--new-round",
                                                "--raw", str(raw), "--lock", str(lock), "--freeze", str(freeze),
                                                "--seed-lock", str(round_one), "--out", str(out)]), 0)
        self.assertEqual(round_one.read_bytes(), before)
        rounds = json.loads(lock.read_text(encoding="utf-8"))["rounds"]
        self.assertEqual([r["independent"] for r in rounds], [True, False])
        result = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((result["independent"], result["data_label"]),
                         (False, "regression on data already seen (non-independent)"))

    def test_metrics_state_tp_fp_fn(self):
        truth = {"rows": [{"from": "0:00", "to": "8:00", "elapsed": "8.00", "end_md": "0", "code": "WOD", "x": True,
                           "description": "Wait on daylight"},
                          {"from": "8:00", "to": "9:00", "elapsed": "1.00", "end_md": "0", "code": "MOB", "x": False,
                           "description": "Fly loads"}]}
        header = list(self.harness.HEADER)
        good = {"table_id": "t", "grid": [header, ["0:00", "8:00", "8.00", "0", "WOD", "Wait on daylight", "X"],
                                          ["8:00", "9:00", "1.00", "0", "MOB", "Fly loads", ""]], "header_rows": 1, "num_cols": 7}
        wrong = copy.deepcopy(good)
        wrong["grid"][1][6] = ""
        wrong["grid"][2][6] = "X"  # one mark lost, one mark that is not in the PDF
        tables = [dict(self.harness.evaluate_table(truth, good), appendix="27", page=1, date="d", index=1),
                  dict(self.harness.evaluate_table(truth, wrong), appendix="27", page=2, date="d", index=1),
                  dict(self.harness.evaluate_table(truth, None), appendix="27", page=3, date="d", index=1)]
        summary = self.harness.summarize(tables, extras=1, pages_scanned=10)
        self.assertEqual({k: summary["table_detection"][k] for k in ("tp", "fp", "fn", "pages_scanned")},
                         {"tp": 2, "fp": 1, "fn": 1, "pages_scanned": 10})
        self.assertEqual({k: summary["non_prod_x"][k] for k in ("tp", "fp", "fn", "pdf_x")}, {"tp": 1, "fp": 1, "fn": 2, "pdf_x": 3})
        self.assertEqual({k: summary["rows"][k] for k in ("tp", "fp", "fn", "pdf_rows")}, {"tp": 4, "fp": 0, "fn": 2, "pdf_rows": 6})
        self.assertEqual(summary["description"]["rows_with_exact_text"], 4)

    def test_exact_text_is_stricter_than_the_token_multiset(self):
        truth = {"rows": [{"from": "0:00", "to": "8:00", "elapsed": "8.00", "end_md": "0", "code": "WOD", "x": False,
                           "description": "Wait on daylight"}]}
        table = {"table_id": "t", "grid": [list(self.harness.HEADER), ["0:00", "8:00", "8.00", "0", "WOD", "daylight on Wait", ""]],
                 "header_rows": 1, "num_cols": 7}
        result = self.harness.evaluate_table(truth, table)
        self.assertEqual((result["description_ok"], result["description_exact"]), (1, 0))

    def test_families_are_named_by_file_name_keywords(self):
        for name, family in (("x_dailyreportdetailrpt_1.pdf", "daily_report"), ("a_eowr.pdf", "eowr"),
                             ("b_casinginforpt.pdf", "casing_cement"), ("c_cementjobrpt.pdf", "casing_cement"),
                             ("d_directionalsurveyrpt.pdf", "survey"), ("e_permits.pdf", "permit"),
                             ("f_drillingplan.pdf", "plan"), ("g_unknown.pdf", "other")):
            self.assertEqual(self.harness.family_of(name), family)

    def test_documents_to_scan_leave_out_the_development_files_and_copies(self):
        raw = self.scratch / "raw"
        raw.mkdir()
        (raw / "a_appx_27_report.pdf").write_bytes(b"one")
        (raw / "a_appx_72_copy.pdf").write_bytes(b"one")  # a copy of a development attachment
        (raw / "b_other.pdf").write_bytes(b"two")
        (raw / "c_same_as_b.pdf").write_bytes(b"two")
        keep, left_out = self.harness.documents_to_scan(raw)
        self.assertEqual([p.name for p in keep], ["b_other.pdf"])
        self.assertEqual(sorted(item["file"] for item in left_out), ["a_appx_27_report.pdf", "a_appx_72_copy.pdf", "c_same_as_b.pdf"])

    def test_a_title_that_the_cheap_page_gate_would_miss_is_counted(self):
        page = layer(real_page(left=NOTE))
        seen = self.harness.scan_page(page, "A page whose text stream has the words apart", OPS_RULE)
        self.assertEqual((seen["gate_text"], seen["titles_passed"], seen["gate_miss"]), (False, 1, True))
        self.assertEqual(seen["results"], [("rebuilt", None, True)])  # read_ok: rows read, NOT merged or validated
        found = self.harness.scan_page(page, "Operations Summary", OPS_RULE)
        self.assertEqual((found["gate_text"], found["gate_miss"]), (True, False))
        nothing = self.harness.scan_page(layer([(100.0, [("Daily", 40, 70), ("Report", 72, 110)])]), "Daily Report", OPS_RULE)
        self.assertEqual((nothing["results"], nothing["mentions"], nothing["gate_miss"]), ([], 0, False))

    def test_a_scan_compares_with_round_one_at_the_level_of_status_and_reason(self):
        class RoundOne:  # Round 1 found no title on a page with a noted title
            @staticmethod
            def read_page(page):
                return []

        seen = self.harness.scan_page(layer(real_page(left=NOTE)), "Operations Summary", OPS_RULE, RoundOne)
        self.assertTrue(seen["differs_from_round_one"])
        self.assertEqual((seen["round_one"], seen["annotations"]), ([], 1))

    def test_annotation_coverage_counts_the_note_in_chunks_of_the_same_page(self):
        release = self.scratch / "release"
        (release / "files.jsonl").write_text(json.dumps({"file_id": "f1", "doc_id": "doc"}) + "\n", encoding="utf-8")
        (release / "chunks.jsonl").write_text(
            json.dumps({"file_id": "f1", "pages": [1], "text": "Page one: 1 record not printed"}) + "\n"
            + json.dumps({"file_id": "f1", "pages": [2], "text": "nothing here"}) + "\n", encoding="utf-8")
        records = [{"doc_id": "doc", "page": 1, "annotations": [{"text": "1 record not printed", "side": "left"}]},
                   {"doc_id": "doc", "page": 2, "annotations": [{"text": "1 record not printed", "side": "left"}]},
                   {"doc_id": "doc", "page": 2, "annotations": [{"text": "2 records not printed", "side": "above"}]},
                   {"doc_id": "doc", "page": 2, "annotations": []}]
        self.assertEqual(self.harness.annotation_coverage(release, records), {
            "records_with_a_title_line_annotation": 2, "annotation_text_in_a_k1_chunk_of_the_same_page": 1,
            "records_with_an_annotation_hint_above_the_title": 1, "hint_text_in_a_k1_chunk_of_the_same_page": 0})

    def test_dynamic_truth_takes_its_zones_from_the_page_header(self):
        def word(text, x0, x1, y):
            return (x0, y, x1, y + 9.0, text, 0, 0, 0)

        header = [word(t, l, r, 263.2) for t, l, r in (("From", 48, 68), ("To", 89, 99), ("Elapsed", 115, 146), ("End", 154, 169),
                                                       ("MD(ft", 171, 192), ("Code", 208, 228), ("Operations", 342, 384),
                                                       ("Description", 386, 430), ("Non-Prod", 537, 573))]
        zones = self.harness.header_zones_truth(header)
        self.assertEqual((zones["from_to"], zones["code_limit"], zones["em"]), (78.5, 238.0, 9.0))
        self.assertIsNone(self.harness.header_zones_truth([word("Something", 48, 100, 263.2)]))
        row = [word(t, l, r, 275.1) for t, l, r in (("0:00", 55, 71), ("8:00", 91, 107), ("8.00", 132, 147), ("0", 188, 192),
                                                  ("WOD", 199, 219), ("Wait", 244, 268), ("X", 565, 570))]
        truth = self.harness.truth_row_dynamic(row, zones)
        self.assertEqual((truth["elapsed"], truth["end_md"], truth["code"], truth["x"], truth["description"]),
                         ("8.00", "0", "WOD", True, "Wait"))

        class Page:
            def get_text(self, kind):
                return header + row + [word("Management", 256, 311, 320.3), word("Summary", 314, 355, 320.3)]

        found = self.harness.truth_tables_dynamic(Page())
        self.assertEqual([len(table["rows"]) for table in found], [1])

        class WrappedPage:  # a wrapped line that starts with a time-like word is a continuation, not a new row
            def get_text(self, kind):
                wrapped = [word("12:00", 244, 270, 284.1), word("hrs,", 272, 292, 284.1)]
                return header + row + wrapped + [word("Management", 256, 311, 320.3), word("Summary", 314, 355, 320.3)]

        [table] = self.harness.truth_tables_dynamic(WrappedPage())
        self.assertEqual(len(table["rows"]), 1)
        self.assertEqual(table["rows"][0]["description"], "Wait 12:00 hrs,")


class ExportScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = load_script("export_k1_ops_rebuild")

    def summary(self, failures, total):
        records = [{"document_type": "daily_report", "rule": "operations_summary", "state": "PARSING_FAILURE" if i < failures
                    else "SUPPORTED_AND_VALIDATED", "reason": None, "annotations": []} for i in range(total)]
        return ops.family_summary(records)

    def test_a_family_above_the_threshold_is_warned_about(self):  # N30
        warnings = self.script.warnings_for(self.summary(1, 10), 0.01)
        self.assertEqual(len(warnings), 1)
        self.assertIn("daily_report/operations_summary", warnings[0])
        self.assertEqual(self.script.warnings_for(self.summary(0, 10), 0.01), [])
        self.assertEqual(self.script.warnings_for(self.summary(1, 10), 0.1), [])  # the limit itself is not above it

    def test_the_threshold_must_be_a_share(self):
        for bad in ("-0.1", "1.5", "x"):
            with self.assertRaises((Exception, SystemExit)):
                self.script.rate(bad)
        self.assertEqual(self.script.rate("0.25"), 0.25)

    def test_export_writes_the_summary_next_to_the_sidecar_and_never_stops_for_a_warning(self):
        directory = ROOT / "data/interim/ops-rebuild-r2/_test_export"
        shutil.rmtree(directory, ignore_errors=True)
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        records = [{"doc_id": "d", "page": 1, "index": 1, "document_type": "daily_report", "rule": "operations_summary",
                    "state": "PARSING_FAILURE", "reason": "rule_exception", "annotations": []}]
        result = {"export": "x", "release": "r", "table_repairs": records, **{k: 0 for k in (
            "files", "pages", "tables", "forms", "parents", "chunks", "held_back")}}
        with patch.object(self.script, "export_k1", return_value=result), patch.object(self.script, "Corpus"), \
                patch.object(self.script, "load_k1_config", return_value={}), \
                self.assertLogs("export_k1_ops_rebuild", "WARNING"):
            self.assertEqual(self.script.main(["name", "--sidecar-dir", str(directory)]), 0)
        summary = json.loads((directory / "table_repairs.name.summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["daily_report/operations_summary"]["parsing_failure_rate"], 1.0)
        self.assertEqual(json.loads((directory / "table_repairs.name.json").read_text(encoding="utf-8")), records)


class RegressScriptTests(unittest.TestCase):
    """The comparison rule of scripts/regress_ops_tables.py: identical in every field except the character offsets, and
    the offsets may differ only after a rebuilt or added table of the same document."""

    def setUp(self):
        self.script = load_script("regress_ops_tables")

    @staticmethod
    def chunk(chunk_id, text, start, table_id=None, file_id="f1", kind="text"):
        return {"chunk_id": chunk_id, "file_id": file_id, "type": kind, "table_id": table_id, "text": text,
                "char_start": start, "char_end": start + len(text)}

    @staticmethod
    def table(table_id, rows, source="#/tables/0", file_id="f1"):
        return {"table_id": table_id, "file_id": file_id, "grid": [["Operations Description", "Non-Prod"], *rows],
                "parts": [{"source_ref": source}], "pages": [1], "regions": []}

    def releases(self, after_chunks):
        old_table = self.table("f1:t1", [["a", ""]])
        new_table = self.table("f1:t1", [["a", "X"]], source="textlayer:operations_summary:p1:1")
        base = {"tables": [old_table], "chunks": [self.chunk("f1:s1:c0", "before", 0), self.chunk("f1:t1:c0", "| old |", 8, "f1:t1", kind="table"),
                                                  self.chunk("f1:s2:c0", "after", 17), self.chunk("f2:s1:c0", "other file", 0, file_id="f2")]}
        after = {"tables": [new_table], "chunks": after_chunks}
        return base, after

    def test_offsets_that_follow_a_rebuilt_table_are_expected_and_counted(self):
        base, after = self.releases([self.chunk("f1:s1:c0", "before", 0), self.chunk("f1:t1:c0", "| new table |", 8, "f1:t1", kind="table"),
                                     self.chunk("f1:s2:c0", "after", 23), self.chunk("f2:s1:c0", "other file", 0, file_id="f2")])
        facts = self.script.tables_and_chunks(base, after)
        self.assertEqual(facts["baseline_chunks_by_kind"]["text:identical"], 2)
        self.assertEqual(facts["baseline_chunks_by_kind"]["text:offset_only"], 1)
        self.assertEqual((facts["chunks_offset_only_changed"], facts["offset_changes_not_after_a_rebuilt_table"]), (1, []))

    def test_an_offset_change_before_the_table_or_in_another_document_is_flagged(self):
        base, after = self.releases([self.chunk("f1:s1:c0", "before", 1), self.chunk("f1:t1:c0", "| new table |", 8, "f1:t1", kind="table"),
                                     self.chunk("f1:s2:c0", "after", 23), self.chunk("f2:s1:c0", "other file", 5, file_id="f2")])
        facts = self.script.tables_and_chunks(base, after)
        self.assertEqual(sorted(facts["offset_changes_not_after_a_rebuilt_table"]), ["f1:s1:c0", "f2:s1:c0"])

    def test_a_change_of_the_text_is_changed_not_an_offset_difference(self):
        base, after = self.releases([self.chunk("f1:s1:c0", "before!", 0), self.chunk("f1:t1:c0", "| new table |", 8, "f1:t1", kind="table"),
                                     self.chunk("f1:s2:c0", "after", 23), self.chunk("f2:s1:c0", "other file", 0, file_id="f2")])
        self.assertEqual(self.script.tables_and_chunks(base, after)["baseline_chunks_by_kind"]["text:changed"], 1)

    def test_two_identical_releases_have_no_difference(self):
        base, _ = self.releases([])
        facts = self.script.tables_and_chunks(base, {"tables": base["tables"], "chunks": base["chunks"]})
        self.assertEqual((facts["chunks_offset_only_changed"], facts["offset_changes_not_after_a_rebuilt_table"]), (0, []))
        self.assertEqual(facts["baseline_chunks_by_kind"], {"table_ops:identical": 1, "text:identical": 3})

    def test_records_are_compared_on_the_round_one_fields_only(self):
        old = [{"doc_id": "d", "page": 1, "index": 1, "status": "rebuilt", "reason": None, "action": "replaced", "table_id": "f:t1"},
               {"doc_id": "d", "page": 2, "index": 1, "status": "fallback", "reason": "no_title", "action": "kept_docling", "table_id": None}]
        new = [dict(old[0], state="SUPPORTED_AND_VALIDATED", evidence={}, annotations=[], completeness=None),  # new fields only
               dict(old[1], status="rebuilt", reason=None, action="added", table_id="f:t9")]
        result = self.script.compare_records(old, new)
        self.assertEqual((result["identical_round_one_fields"], result["only_in_baseline"], result["only_in_after"]), (1, 0, 0))
        self.assertEqual(result["different_by_transition"], {"fallback:no_title -> rebuilt:-": 1})


if __name__ == "__main__":
    unittest.main()
