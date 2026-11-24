"""Compact only repeated display positions of the same source cell."""
import unittest

from graph_builder.corpus.qa.compound_spans import compact_chunk
from graph_builder.corpus.qa.crossrep import parse_table_chunk


class CompoundSpanTests(unittest.TestCase):
    def test_keeps_signed_value_units_and_an_identical_independent_cell(self):
        value = "Measured pressure -120.5 psi"
        text = f"| A | B | C | D |\n| --- | --- | --- | --- |\n| {value} | {value} | {value} | {value} |"
        table = {"num_cols": 4, "header_rows": 1, "grid": [["A", "B", "C", "D"], [value] * 4], "cells": [
            {"r": 1, "c": 0, "row_span": 1, "col_span": 3, "is_header": False, "text": value},
            {"r": 1, "c": 3, "row_span": 1, "col_span": 1, "is_header": False, "text": value},
        ]}
        chunk = {"row_start": 1, "row_end": 2, "text": text}
        result, positions = compact_chunk(table, chunk)
        self.assertEqual(positions, [[1, 1], [1, 2]])
        self.assertEqual(parse_table_chunk(result)["rows"], [[value, "", "", value]])

        conflicting = text.replace(f"| {value}", "| 98.1 bar", 1)
        self.assertEqual(compact_chunk(table, dict(chunk, text=conflicting)), (conflicting, []))
        table["cells"].append({"r": 1, "c": 1, "row_span": 1, "col_span": 1, "is_header": False, "text": value})
        self.assertEqual(compact_chunk(table, chunk), (text, []))
