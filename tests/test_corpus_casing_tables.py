"""Check source-based casing recovery, preserved native evidence and colonless report headers."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from docling_core.types.doc import BoundingBox, CoordOrigin, DoclingDocument, TableCell, TableData
from docling_core.types.doc.document import ProvenanceItem
import pymupdf

from graph_builder.corpus.casing_tables import printed_tokens, read_page, repair_document, trim_compound
from graph_builder.corpus.daily_header import header_fields
from graph_builder.corpus.k1_config import load_k1_config
STANDARD_24NOV = __import__('pathlib').Path(__file__).resolve().parents[1] / "configs/corpus/candidates/k1_standard_24nov.json"  # the profile main shipped on 24 November (D2/D4 decisions made the default smaller)
from graph_builder.corpus.text_layer import source_page

HEADERS = ["Size", "Grade", "N. Joints", "Make", "Length (m)", "Set at (mGL)", "Comment"]
ROWS = [
    ['9-5/8"', "J55", "12", "Example", "110", "106", ""],
    ['7"', "K55", "42", "", "530", "527", "Cemented"],
]


def write_casing(path, crossing=False, title="Casing Details"):
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((200, 100), title)
        edges = [31, 100, 165, 232, 313, 396, 487, 560]
        for y in (105, 122, 139, 156):
            page.draw_line((edges[0], y), (edges[-1], y))
        for x in edges:
            page.draw_line((x, 105), (x, 156))
        for y, row in zip((118, 135, 152), [HEADERS, *ROWS]):
            for x, value in zip(edges, row):
                if value:
                    page.insert_text((x + 4, y), value, fontsize=9)
        if crossing:
            page.insert_text((380, 135), "ambiguous", fontsize=9)
        page.insert_text((41, 177), 'Last Casing 7" at 527m')
        pdf.save(path)


class SourceTableTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.pdf = Path(folder.name) / "report.pdf"

    def test_reads_reordered_columns_and_leaves_blank_source_cells(self):
        write_casing(self.pdf)
        (_, result), = read_page(source_page(self.pdf, 1))
        self.assertEqual(result["grid"], [HEADERS, *ROWS])

    def test_crossing_word_and_narrative_title_abstain(self):
        write_casing(self.pdf, crossing=True)
        (_, result), = read_page(source_page(self.pdf, 1))
        self.assertIsNone(result)
        write_casing(self.pdf, title="Review casing data after the cement job")
        self.assertEqual(list(read_page(source_page(self.pdf, 1))), [])

    def test_keeps_a_compound_native_table_and_flags_it_for_review(self):
        write_casing(self.pdf)
        region = {"page": 1, "bbox": [28, 94, 565, 201]}
        native = {"table_id": "native", "regions": [region], "cells": [{"text": "Other section 40"}]}
        chunk = {"table_id": "native", "type": "table", "pages": [1], "page": 1, "quality": "ok", "ocr": False,
                 "doc_id": "test-dailyreport", "section": None, "section_path": [], "text": "Other section 40"}
        args = (self.pdf, [{"mode": "text", "page": 1}], [chunk], [native], "test-dailyreport", "f1", 1500)
        chunks, tables, findings = repair_document(*args)
        self.assertEqual(tables[0], native)
        self.assertEqual((chunks[0]["text"], chunks[0]["quality"], chunk["quality"]), ("Other section 40", "review", "ok"))
        self.assertEqual(findings[0]["overlapping_tables_for_review"], ["f1:t1"])
        self.assertEqual(tables[1]["grid"], [HEADERS, *ROWS])
        self.assertEqual(chunks[1]["source_spans"][0]["source_ref"], tables[1]["source_ref"])
        self.assertEqual(repair_document(*args, stacked_pages={1}), ([chunk], [native], []))

    def test_compound_prefix_is_split_with_no_changes_to_remaining_cells(self):
        source = [["Size", "Grade"], ['7"', "J55"], ["Pump", "24"]]
        cells = [TableCell(text=text, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                           start_col_offset_idx=c, end_col_offset_idx=c + 1, column_header=r == 0,
                           bbox=BoundingBox(l=30 + 60*c, t=103 + 16*r, r=70 + 60*c, b=115 + 16*r,
                                            coord_origin=CoordOrigin.TOPLEFT))
                 for r, row in enumerate(source) for c, text in enumerate(row)]
        document = DoclingDocument(name="report")
        box = BoundingBox(l=20, t=99, r=240, b=152, coord_origin=CoordOrigin.TOPLEFT)
        item = document.add_table(data=TableData(num_rows=3, num_cols=2, table_cells=cells),
                                  prov=ProvenanceItem(page_no=1, bbox=box, charspan=(0, 0)))
        native = {"regions": [{"page": 1, "bbox": [20, 99, 240, 152]}]}
        region = [20, 100, 240, 131]
        tokens = printed_tokens(value for row in source[:2] for value in row)
        residual = trim_compound(native, item, region, tokens, 800, [])
        self.assertEqual((residual["grid"], residual["header_rows"]), ([["Pump", "24"]], 0))
        self.assertEqual([(cell["r"], cell["c"], cell["text"]) for cell in residual["cells"]],
                         [(0, 0, "Pump"), (0, 1, "24")])
        self.assertIsNone(trim_compound(native, item, region, tokens, 800, [{"text": "Outside evidence"}]))

    def test_daily_header_reads_literal_values_and_their_source_boxes(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((70, 63), "Daily Drilling Report")
            page.insert_text((70, 92), "DAILY COST $6,873CUM. COST $2,389,251")
            page.insert_text((70, 112), "DEPTH AT 0600 960m (TD) EST TD 1000m")
            page.insert_text((70, 300), "DAILY COST $1 CUM. COST $2")
            pdf.save(self.pdf)
        fields = header_fields(source_page(self.pdf, 1))
        self.assertEqual([(f["key"], f["value"]) for f in fields],
                         [("DAILY COST", "$6,873"), ("CUM. COST", "$2,389,251"), ("DEPTH AT 0600", "960m (TD)")])
        self.assertLessEqual(fields[0]["value_bbox"][2], fields[1]["key_bbox"][0])

    def test_shipped_rules_apply_to_daily_reports(self):
        config = load_k1_config(STANDARD_24NOV)
        self.assertIn("daily_report", config["table_rules"]["casing"]["document_types"])
        self.assertTrue(config["forms"]["daily_header"])


if __name__ == "__main__":
    unittest.main()
