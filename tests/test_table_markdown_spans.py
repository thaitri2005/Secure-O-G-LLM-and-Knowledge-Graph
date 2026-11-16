"""Merged-cell text appears once in table Markdown when chunking.table_markdown is span_once (A-415)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from docling_core.types.doc import BoundingBox, ProvenanceItem, TableCell, TableData
from docling_core.types.doc.base import CoordOrigin

from graph_builder.corpus.chunking import chunk_document
from graph_builder.corpus.config import fingerprint, validate_config
from graph_builder.ingestion.tables import table_markdown, table_views
from test_chunking import make_document

ROOT = Path(__file__).resolve().parents[1]


def cell(r, c, text, rows=1, cols=1, header=False):
    return TableCell(text=text, start_row_offset_idx=r, end_row_offset_idx=r + rows, start_col_offset_idx=c,
                     end_col_offset_idx=c + cols, row_span=rows, col_span=cols, column_header=header)


def make_table(cells, num_rows, num_cols):
    document = make_document(pages=1)
    box = BoundingBox(l=50, t=100, r=500, b=300, coord_origin=CoordOrigin.TOPLEFT)
    table = document.add_table(data=TableData(table_cells=cells, num_rows=num_rows, num_cols=num_cols),
                               prov=ProvenanceItem(page_no=1, bbox=box, charspan=(0, 0)))
    return document, table


def lines(markdown):
    return [line for line in markdown.splitlines() if line.startswith("|")]


def config(mode=None):
    value = json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8"))
    if mode:
        value["chunking"]["table_markdown"] = mode
    return value


class SpanOnceTests(unittest.TestCase):
    def test_column_span_in_single_header_row_is_written_once(self) -> None:
        document, table = make_table([cell(0, 0, "Name", header=True), cell(0, 1, "Ref. GRG-10230", cols=2, header=True),
                                      cell(1, 0, "a"), cell(1, 1, "b"), cell(1, 2, "c")], 2, 3)
        old = table_markdown(table, document, "docling")
        new = table_markdown(table, document, "span_once")
        self.assertEqual(old.count("Ref. GRG-10230"), 2)
        self.assertEqual(new.count("Ref. GRG-10230"), 1)
        self.assertEqual(len(lines(old)), len(lines(new)))
        self.assertIn("| a ", new)

    def test_row_span_in_body_keeps_text_in_first_row_only(self) -> None:
        document, table = make_table([cell(0, 0, "K", header=True), cell(0, 1, "V", header=True),
                                      cell(1, 0, "Totals", rows=2), cell(1, 1, "1"), cell(2, 1, "2")], 3, 2)
        new = table_markdown(table, document, "span_once")
        self.assertEqual(table_markdown(table, document, "docling").count("Totals"), 2)
        self.assertEqual(new.count("Totals"), 1)
        self.assertTrue(lines(new)[2].startswith("| Totals"))
        self.assertTrue(lines(new)[3].replace(" ", "").startswith("||2"))

    def test_row_and_column_span_together(self) -> None:
        document, table = make_table([cell(0, 0, "H1", header=True), cell(0, 1, "H2", header=True),
                                      cell(0, 2, "H3", header=True), cell(1, 0, "Block", rows=2, cols=2),
                                      cell(1, 2, "x"), cell(2, 2, "y")], 3, 3)
        new = table_markdown(table, document, "span_once")
        self.assertEqual(new.count("Block"), 1)
        self.assertEqual(len(lines(new)), len(lines(table_markdown(table, document, "docling"))))

    def test_stacked_header_keeps_the_group_label_per_column(self) -> None:
        document, table = make_table([cell(0, 0, "ROP", cols=2, header=True), cell(0, 2, "WOB", header=True),
                                      cell(1, 0, "Avg", header=True), cell(1, 1, "Max", header=True),
                                      cell(1, 2, "Avg", header=True), cell(2, 0, "1"), cell(2, 1, "2"), cell(2, 2, "3")],
                                     3, 3)
        new = table_markdown(table, document, "span_once")
        self.assertEqual(new, table_markdown(table, document, "docling"))
        self.assertIn("ROP - Max", new)

    def test_stacked_header_with_row_span_label_is_unchanged(self) -> None:
        document, table = make_table([cell(0, 0, "Depth", rows=2, header=True), cell(0, 1, "ROP", cols=2, header=True),
                                      cell(1, 1, "Avg", header=True), cell(1, 2, "Max", header=True),
                                      cell(2, 0, "1"), cell(2, 1, "2"), cell(2, 2, "3")], 3, 3)
        self.assertEqual(table_markdown(table, document, "span_once"), table_markdown(table, document, "docling"))

    def test_table_without_spans_is_byte_identical(self) -> None:
        document, table = make_table([cell(0, 0, "A", header=True), cell(0, 1, "B", header=True),
                                      cell(1, 0, "1"), cell(1, 1, "2")], 2, 2)
        self.assertEqual(table_markdown(table, document, "span_once"), table_markdown(table, document, "docling"))
        self.assertEqual(table_markdown(table, document, "docling"), table.export_to_markdown(doc=document))

    def test_repeated_equal_texts_that_are_not_spans_are_kept(self) -> None:
        document, table = make_table([cell(0, 0, "A", header=True), cell(0, 1, "A", header=True),
                                      cell(1, 0, "same"), cell(1, 1, "same"), cell(2, 0, "span", cols=2)], 3, 2)
        new = table_markdown(table, document, "span_once")
        self.assertEqual(new.count("same"), 2)
        self.assertEqual(new.count("span"), 1)

    def test_idempotent_and_deterministic(self) -> None:
        document, table = make_table([cell(0, 0, "T", cols=3, header=True), cell(1, 0, "a"), cell(1, 1, "b"),
                                      cell(1, 2, "c")], 2, 3)
        first = table_markdown(table, document, "span_once")
        self.assertEqual(first, table_markdown(table, document, "span_once"))

    def test_overlapping_cells_fall_back_to_docling_output(self) -> None:
        document, table = make_table([cell(0, 0, "H", cols=2, header=True), cell(0, 1, "overlap", header=True),
                                      cell(1, 0, "a"), cell(1, 1, "b")], 2, 2)
        self.assertEqual(table_markdown(table, document, "span_once"), table_markdown(table, document, "docling"))

    def test_unknown_mode_is_rejected(self) -> None:
        document, table = make_table([cell(0, 0, "A", header=True), cell(1, 0, "1")], 2, 1)
        with self.assertRaises(ValueError):
            table_markdown(table, document, "other")

    def test_structured_table_data_does_not_change(self) -> None:
        cells = [cell(0, 0, "Name", header=True), cell(0, 1, "Ref", cols=2, header=True), cell(1, 0, "a"),
                 cell(1, 1, "b"), cell(1, 2, "c")]
        document, table = make_table(cells, 2, 3)
        before = copy.deepcopy(table_views(table))
        table_markdown(table, document, "span_once")
        self.assertEqual(table_views(table), before)


class ChunkingModeTests(unittest.TestCase):
    def chunks(self, mode):
        cells = [cell(0, 0, "Name", header=True), cell(0, 1, "Ref. GRG-10230", cols=2, header=True),
                 cell(1, 0, "a"), cell(1, 1, "b"), cell(1, 2, "c")]
        document, _ = make_table(cells, 2, 3)
        return chunk_document(document, "doc", config(mode), set())

    def test_tables_and_row_ranges_are_identical_and_only_chunk_text_differs(self) -> None:
        old_chunks, old_tables, _ = self.chunks(None)
        new_chunks, new_tables, _ = self.chunks("span_once")
        self.assertEqual(old_tables, new_tables)
        self.assertEqual(len(old_chunks), len(new_chunks))
        key = lambda c: {k: v for k, v in c.items() if k not in ("text", "sha256", "char_start", "char_end", "source_spans")}
        self.assertEqual([key(c) for c in old_chunks], [key(c) for c in new_chunks])
        self.assertEqual(old_chunks[0]["text"].count("Ref. GRG-10230"), 2)
        self.assertEqual(new_chunks[0]["text"].count("Ref. GRG-10230"), 1)

    def test_default_behaviour_is_unchanged_without_the_key(self) -> None:
        self.assertNotIn("table_markdown", config()["chunking"])
        explicit = self.chunks("docling")
        self.assertEqual(explicit[0], self.chunks(None)[0])


class ConfigAndFingerprintTests(unittest.TestCase):
    def test_key_is_optional_validated_and_changes_the_fingerprint(self) -> None:
        base = validate_config(config())
        spanned = validate_config(config("span_once"))
        self.assertNotEqual(fingerprint(base, {}), fingerprint(spanned, {}))
        self.assertEqual(fingerprint(base, {}), fingerprint(validate_config(config()), {}))
        with self.assertRaises(ValueError):
            validate_config(config("nonsense"))
        extra = config()
        extra["chunking"]["other"] = 1
        with self.assertRaises(ValueError):
            validate_config(extra)

    def test_default_configuration_does_not_enable_the_option(self) -> None:
        self.assertNotIn("table_markdown", json.loads((ROOT / "configs/corpus/default.json").read_text(encoding="utf-8"))["chunking"])


if __name__ == "__main__":
    unittest.main()
