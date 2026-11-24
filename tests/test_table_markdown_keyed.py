"""Row keys of row-spanning cells and stable chunk row boundaries for chunking.table_markdown=span_once_keyed (A-431)."""
from __future__ import annotations

import unittest

from docling_core.types.doc import TableCell

from graph_builder.corpus.chunking import chunk_document
from graph_builder.corpus.config import fingerprint, validate_config
from graph_builder.ingestion.chunking import split_table
from graph_builder.ingestion.tables import table_markdown
from test_table_markdown_spans import cell, config, lines, make_table


def small(max_chars):
    value = config("span_once_keyed")
    value["chunking"]["max_chars"] = max_chars
    return value


def chunk_rows(table_cells, num_rows, num_cols, mode, max_chars=200):
    document, _ = make_table(table_cells, num_rows, num_cols)
    value = config(mode)
    value["chunking"]["max_chars"] = max_chars
    chunks, tables, _ = chunk_document(document, "doc", value, set())
    return [c for c in chunks if c["type"] == "table"], tables


class KeyedRenderingTests(unittest.TestCase):
    def test_first_column_row_span_keeps_its_key_on_every_covered_row(self) -> None:
        document, table = make_table([cell(0, 0, "K", header=True), cell(0, 1, "V", header=True),
                                      cell(1, 0, "Totals", rows=2), cell(1, 1, "1"), cell(2, 1, "2")], 3, 2)
        once, keyed = (table_markdown(table, document, m) for m in ("span_once", "span_once_keyed"))
        self.assertEqual(once.count("Totals"), 1)
        self.assertEqual(keyed.count("Totals"), 2)
        self.assertEqual([len(x) for x in map(lines, (once, keyed))], [4, 4])
        self.assertTrue(lines(keyed)[2].startswith("| Totals") and lines(keyed)[3].startswith("| Totals"))

    def test_row_header_cell_outside_the_first_column_is_a_key(self) -> None:
        key = TableCell(text="Reviewed By:", start_row_offset_idx=1, end_row_offset_idx=3, start_col_offset_idx=1,
                        end_col_offset_idx=2, row_span=2, col_span=1, row_header=True)
        document, table = make_table([cell(0, 0, "A", header=True), cell(0, 1, "B", header=True), cell(1, 0, "x"),
                                      key, cell(2, 0, "y")], 3, 2)
        self.assertEqual(table_markdown(table, document, "span_once_keyed").count("Reviewed By:"), 2)
        self.assertEqual(table_markdown(table, document, "span_once").count("Reviewed By:"), 1)

    def test_row_spanning_value_cell_in_a_later_column_is_still_written_once(self) -> None:
        document, table = make_table([cell(0, 0, "K", header=True), cell(0, 1, "V", header=True),
                                      cell(1, 0, "a"), cell(1, 1, "Long remark", rows=2), cell(2, 0, "b")], 3, 2)
        self.assertEqual(table_markdown(table, document, "span_once_keyed").count("Long remark"), 1)

    def test_column_span_header_follows_span_once(self) -> None:
        document, table = make_table([cell(0, 0, "Name", header=True), cell(0, 1, "Ref. X", cols=2, header=True),
                                      cell(1, 0, "a"), cell(1, 1, "b"), cell(1, 2, "c")], 2, 3)
        self.assertEqual(table_markdown(table, document, "span_once_keyed"), table_markdown(table, document, "span_once"))
        self.assertEqual(table_markdown(table, document, "span_once_keyed").count("Ref. X"), 1)

    def test_key_that_also_spans_columns_is_kept_only_in_its_first_column(self) -> None:
        document, table = make_table([cell(0, 0, "H1", header=True), cell(0, 1, "H2", header=True),
                                      cell(0, 2, "H3", header=True), cell(1, 0, "Block", rows=2, cols=2),
                                      cell(1, 2, "x"), cell(2, 2, "y")], 3, 3)
        keyed = table_markdown(table, document, "span_once_keyed")
        self.assertEqual(keyed.count("Block"), 2)

    def test_equal_neighbours_that_are_not_spans_stay_and_unspanned_tables_are_identical(self) -> None:
        document, table = make_table([cell(0, 0, "A", header=True), cell(0, 1, "B", header=True), cell(1, 0, "0"),
                                      cell(1, 1, "0"), cell(2, 0, "0"), cell(2, 1, "0")], 3, 2)
        self.assertEqual(table_markdown(table, document, "span_once_keyed"), table_markdown(table, document, "docling"))

    def test_equal_text_is_not_used_as_the_signal(self) -> None:
        # The row-spanning cell "Totals" is a key; the equal text "Totals" in a separate, unspanned cell is untouched.
        document, table = make_table([cell(0, 0, "K", header=True), cell(0, 1, "V", header=True),
                                      cell(1, 0, "Totals", rows=2), cell(1, 1, "1"), cell(2, 1, "2"),
                                      cell(3, 0, "Totals"), cell(3, 1, "3")], 4, 2)
        self.assertEqual(table_markdown(table, document, "span_once_keyed").count("Totals"), 3)

    def test_idempotent_and_never_changes_table_shape(self) -> None:
        document, table = make_table([cell(0, 0, "K", header=True), cell(0, 1, "V", header=True),
                                      cell(1, 0, "Totals", rows=2), cell(1, 1, "1"), cell(2, 1, "2")], 3, 2)
        first = table_markdown(table, document, "span_once_keyed")
        self.assertEqual(first, table_markdown(table, document, "span_once_keyed"))
        self.assertEqual(len(lines(first)), len(lines(table_markdown(table, document, "docling"))))

    def test_overlapping_cells_fall_back_to_docling(self) -> None:
        document, table = make_table([cell(0, 0, "H", cols=2, header=True), cell(0, 1, "overlap", header=True),
                                      cell(1, 0, "a"), cell(1, 1, "b")], 2, 2)
        self.assertEqual(table_markdown(table, document, "span_once_keyed"), table_markdown(table, document, "docling"))


class StableBoundaryTests(unittest.TestCase):
    CELLS = []

    @classmethod
    def build(cls, pairs=20):
        cells = [cell(0, 0, "Run", header=True), cell(0, 1, "Remark", header=True), cell(0, 2, "Value", header=True)]
        for index in range(pairs):
            row = 1 + 2 * index
            cells += [cell(row, 0, f"R{index:02d}", rows=2), cell(row, 1, f"A rather long remark number {index:02d} with words",
                                                              rows=2), cell(row, 2, "1"), cell(row + 1, 2, "2")]
        return cells, 1 + 2 * pairs

    def test_chunk_ids_and_row_ranges_equal_the_docling_rendering(self) -> None:
        cells, rows = self.build()
        old, old_tables = chunk_rows(cells, rows, 3, None)
        keyed, keyed_tables = chunk_rows(cells, rows, 3, "span_once_keyed")
        once, _ = chunk_rows(cells, rows, 3, "span_once")
        self.assertGreater(len(old), 2)
        self.assertEqual(old_tables, keyed_tables)
        self.assertEqual([(c["chunk_id"], c["row_start"], c["row_end"]) for c in old],
                         [(c["chunk_id"], c["row_start"], c["row_end"]) for c in keyed])
        self.assertLess(sum(len(c["text"]) for c in keyed), sum(len(c["text"]) for c in old))
        self.assertNotEqual([(c["row_start"], c["row_end"]) for c in old], [(c["row_start"], c["row_end"]) for c in once],
                            "the span_once rendering re-packs rows; the keyed mode must not")
        self.assertTrue(all(c["text"].count("Run") == 1 for c in keyed))

    def test_every_row_key_is_visible_in_its_chunk(self) -> None:
        cells, rows = self.build()
        keyed, _ = chunk_rows(cells, rows, 3, "span_once_keyed")
        for chunk in keyed:
            body = [l for l in chunk["text"].splitlines() if l.startswith("|")][2:]
            self.assertEqual(len(body), chunk["row_end"] - chunk["row_start"])
            self.assertTrue(all(l.split("|")[1].strip().startswith("R") for l in body), chunk["text"])

    def test_default_and_docling_modes_are_byte_identical(self) -> None:
        cells, rows = self.build()
        self.assertEqual(chunk_rows(cells, rows, 3, None)[0], chunk_rows(cells, rows, 3, "docling")[0])

    def test_chunking_is_deterministic(self) -> None:
        cells, rows = self.build()
        self.assertEqual(chunk_rows(cells, rows, 3, "span_once_keyed")[0], chunk_rows(cells, rows, 3, "span_once_keyed")[0])

    def test_header_only_table_does_not_crash(self) -> None:
        cells = [cell(0, 0, "A", header=True), cell(0, 1, "B", cols=1, header=True)]
        chunks, _ = chunk_rows(cells, 1, 2, "span_once_keyed")
        self.assertEqual(len(chunks), len(chunk_rows(cells, 1, 2, None)[0]))


class MergedHeaderInChunkTextTests(unittest.TestCase):
    """D4 (note of 24 November): a merged header cell is repeated in the default chunk text and written once with
    ``span_once_keyed``, while table records, chunk ids and row ranges stay as they are (no K1 field changes)."""
    CELLS = [cell(0, 0, "Casing", header=True), cell(0, 1, "Setting depth (m MD)", cols=2, header=True),
             cell(1, 0, '13 3/8"'), cell(1, 1, "1,005"), cell(1, 2, "1,010"),
             cell(2, 0, '9 5/8"'), cell(2, 1, "2,950"), cell(2, 2, "2,955")]

    def test_default_repeats_the_merged_header_and_keyed_writes_it_once(self) -> None:
        old, old_tables = chunk_rows(self.CELLS, 3, 3, None)
        keyed, keyed_tables = chunk_rows(self.CELLS, 3, 3, "span_once_keyed")
        self.assertEqual(sum(c["text"].count("Setting depth (m MD)") for c in old), 2)
        self.assertEqual(sum(c["text"].count("Setting depth (m MD)") for c in keyed), 1)
        self.assertEqual(old_tables, keyed_tables)
        ids = lambda chunks: [(c["chunk_id"], c["table_id"], c["row_start"], c["row_end"]) for c in chunks]
        self.assertEqual(ids(old), ids(keyed))
        self.assertEqual(set(old[0]), set(keyed[0]))
        self.assertIn("2,955", keyed[0]["text"])


class SplitTableRowGroupTests(unittest.TestCase):
    MD = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |"

    def test_row_groups_set_the_boundaries(self) -> None:
        parts = split_table(self.MD, "", 10000, row_groups=[1, 2])
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[1].splitlines()[2:], ["| 3 | 4 |", "| 5 | 6 |"])
        self.assertEqual(split_table(self.MD, "", 10000), [self.MD.replace("|---|---|", "| --- | --- |")])

    def test_inconsistent_row_groups_are_rejected(self) -> None:
        for groups in ([1, 1], [0, 3], [2, 2]):
            with self.assertRaises(ValueError):
                split_table(self.MD, "", 10000, row_groups=groups)


class ConfigAndFingerprintTests(unittest.TestCase):
    def test_mode_is_valid_and_has_its_own_fingerprint(self) -> None:
        base, once, keyed = (fingerprint(validate_config(config(mode)), {}) for mode in (None, "span_once", "span_once_keyed"))
        self.assertEqual(len({base, once, keyed}), 3)
        self.assertEqual(base, fingerprint(validate_config(config()), {}))


if __name__ == "__main__":
    unittest.main()
