"""Lock gold scoring conventions independently of parser output."""
import unittest
from graph_builder.ingestion.scoring import bbox_iou, match_table, score_grid, score_order, cell_grid, score_values


class ScoringTests(unittest.TestCase):
    def test_form_values_ignore_positions_but_preserve_characters(self):
        result = score_values(["10 psi", "8.6 \u2013 9.2", ""], "Other field: 10\npsi; 8.6 - 9.2")
        self.assertEqual(result, {"value_matches": 1, "value_count": 2, "value_recall": .5})

    def test_header_separation_whitespace_and_dash_distinction(self):
        result = score_grid([[" H "], ["8.6 \u2013 9.2"], ["A  B"]], [["H"], ["8.6 - 9.2"], ["A B"]], 1)
        self.assertEqual(result["cell_accuracy"], .5)
        self.assertEqual(result["header_accuracy"], 1)
        self.assertTrue(result["row_count_correct"])
        self.assertTrue(result["column_count_correct"])
        self.assertFalse(score_grid([["A", "B"]], [["A"]], 0)["column_count_correct"])

    def test_merged_cell_only_occupies_top_left(self):
        self.assertEqual(cell_grid({"num_rows": 2, "num_cols": 2, "cells": [
            {"r": 0, "c": 0, "row_span": 2, "col_span": 2, "text": "Merged"}]}), [["Merged", ""], ["", ""]])

    def test_iou_ignores_ref_and_requires_document_and_page(self):
        annotation = {"doc_id": "sample", "page": 2, "bbox": [0, 0, 10, 10], "source_ref": "old"}
        table = {"doc_id": "sample", "source_ref": "new", "regions": [{"page": 2, "bbox": [0, 0, 10, 10]}]}
        wrong = {**table, "doc_id": "other"}
        self.assertEqual(match_table(annotation, [wrong, table]), (table, 1))
        self.assertEqual(bbox_iou([0, 0, 10, 10], [10, 10, 20, 20]), 0)

    def test_tau_common_ids_extras_and_first_occurrence(self):
        gold = {"reading_order": ["a", "b", "c"], "items": [{"id": x, "section": "S"} for x in "abc"]}
        predicted = [{"id": "b", "section": "S"}, {"id": "a", "section": None},
                     {"id": "b", "section": "wrong"}, {"id": "extra", "section": "S"}]
        result = score_order(gold, predicted)
        self.assertEqual(result["kendall_tau"], -1)
        self.assertEqual(result["section_accuracy"], .5)
        self.assertEqual(result["extra_items"], 1)
        self.assertEqual(result["missing_items"], 1)
