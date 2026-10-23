"""Check table structure, compact rendering and cross-page merges."""
import unittest
from docling_core.types.doc import TableCell, TableData
from graph_builder.ingestion.tables import compact_markdown, merge_adjacent_tables, table_views
from graph_builder.ingestion.chunking import chunks_from_document
from test_chunking import add_table, make_document


class TableTests(unittest.TestCase):
    def test_table_parts_reference_one_structure_and_reconstruct_rows(self):
        doc = make_document()
        table = add_table(doc, rows=7)
        metadata, structures = [], []
        chunks, _ = chunks_from_document(doc, "sample", 35, .08, .5, 1, .5, 3,
                                         metadata, table_records=structures)
        self.assertEqual(len(structures), 1)
        self.assertGreater(len(chunks), 1)
        rows = []
        for record in metadata:
            self.assertNotIn("cells", record)
            self.assertNotIn("rows_text", record)
            self.assertEqual(record["table_id"], f"sample#t{0:03d}")
            rows.extend(range(record["row_start"], record["row_end"]))
        self.assertEqual(rows, list(range(1, table.data.num_rows)))

    def test_merged_table_rows_keep_their_physical_pages(self):
        from graph_builder.ingestion.attribution import page_texts
        doc = make_document()
        first = add_table(doc, page=1)
        second = add_table(doc, page=2)
        first.data.table_cells[1].text = "10 psi"
        second.data.table_cells[1].text = "20 psi"
        metadata = []
        chunks, _ = chunks_from_document(doc, "sample", 1500, .08, .5, 1, .5, 3, metadata,
                                         table_options={"merge_pages": True})
        pages = page_texts({**chunks[0], **metadata[0]})
        self.assertIn("10 psi", pages[1])
        self.assertNotIn("20 psi", pages[1])
        self.assertIn("20 psi", pages[2])
        self.assertNotIn("10 psi", pages[2])
    def test_multilevel_headers_and_spans(self):
        document = make_document()
        cells = [TableCell(text="Pressure", start_row_offset_idx=0, end_row_offset_idx=1,
                           start_col_offset_idx=0, end_col_offset_idx=2, col_span=2, column_header=True)]
        for row, values in ((1, ("Start", "End")), (2, ("10", "20"))):
            for column, value in enumerate(values):
                cells.append(TableCell(text=value, start_row_offset_idx=row, end_row_offset_idx=row + 1,
                                       start_col_offset_idx=column, end_col_offset_idx=column + 1,
                                       column_header=row == 1))
        table = document.add_table(data=TableData(num_rows=3, num_cols=2, table_cells=cells))
        _, rows, records, headers = table_views(table)
        self.assertEqual(headers, 2)
        self.assertEqual(rows, ["Pressure / Start: 10; Pressure / End: 20"])
        self.assertEqual(records[0]["col_span"], 2)

    def test_compact_rows_cells(self):
        table = add_table(make_document())
        grid, rows, cells, header_rows = table_views(table)
        self.assertEqual(header_rows, 1)
        self.assertEqual(rows, ["Column: Row 1", "Column: Row 2"])
        self.assertTrue(cells[0]["is_header"])
        self.assertEqual(compact_markdown(table), "| Column |\n| --- |\n| Row 1 |\n| Row 2 |")

    def test_merge_requires_adjacent_pages_and_matching_headers(self):
        doc = make_document(3)
        add_table(doc, page=1)
        add_table(doc, page=2)
        different = add_table(doc, page=3)
        different.data.table_cells[0].text = "Different"
        merged, log = merge_adjacent_tables(doc)
        self.assertEqual(len(log), 1)
        self.assertEqual(len(merged.tables), 2)
        self.assertEqual(merged.tables[0].data.num_rows, 5)
        self.assertEqual(len(doc.tables), 3)

    def test_degenerate_table_as_text_is_opt_in(self):
        doc = make_document()
        add_table(doc, rows=1)
        chunks, stats = chunks_from_document(doc, "sample", 1500, .08, .5, 1, .5, 3, table_options={"compact": True})
        self.assertEqual(chunks[0]["type"], "text")
        self.assertEqual(stats["dropped"]["degenerate_table_to_text"], 1)
