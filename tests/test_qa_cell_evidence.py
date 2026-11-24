"""Verify cell locations, raw-value preservation and review of a mixed native cell."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from docling_core.types.doc import BoundingBox, CoordOrigin, DoclingDocument, Size, TableCell, TableData
from docling_core.types.doc.document import ProvenanceItem
import pymupdf

from graph_builder.corpus.hourly_operations import compile_templates, read_page
from graph_builder.corpus.ops_tables import grid_table_record
from graph_builder.corpus.qa.cell_evidence import CellEvidence, normalized_value
from graph_builder.corpus.text_layer import source_page
from graph_builder.ingestion.tables import table_views


def box(left, top, right, bottom):
    return BoundingBox(l=left, t=top, r=right, b=bottom, coord_origin=CoordOrigin.TOPLEFT)


class CellEvidenceTests(unittest.TestCase):
    def test_hourly_cells_use_distinct_original_boxes_on_a_cropped_page(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "report.pdf"
            with pymupdf.open() as pdf:
                page = pdf.new_page(width=500, height=500)
                page.draw_rect((100, 180, 400, 198), fill=(.9, .9, .9))
                page.insert_text((150, 193), "Hourly Operations Summary 0000 to 2400", fontsize=9)
                for x in (100, 155, 207, 400):
                    page.draw_line((x, 198), (x, 246))
                for y in (213, 230, 246):
                    page.draw_line((100, y), (400, y))
                rows = [["From", "To", "Description"], ["0:00", "6:00", "Drilling"], ["6:00", "11:00", "Inspect"]]
                for y, row in zip((209, 226, 241), rows):
                    for x, value in zip((113, 166, 223), row):
                        page.insert_text((x, y), value, fontsize=9)
                page.set_cropbox(pymupdf.Rect(24, 18, 470, 460))
                pdf.save(path)
            templates = compile_templates([{"id": "test-v1", "title": "Hourly Operations Summary",
                                            "columns": [["From"], ["To"], ["Description"]]}])
            (_, _, result), = read_page(source_page(path, 1, displayed_origin=True), templates)
            table = grid_table_record("hourly", "report", "textlayer:hourly_operations:p1:1", 1, result["bbox"], result["grid"])
            table.update(file_id="file", parts=[{"page": 1, "source_ref": table["source_ref"]}])
            cells = {(row["r"], row["c"]): row for row in CellEvidence.rule_rows(table, "hourly_operations", result["cell_boxes"])}
            with pymupdf.open(path) as pdf:
                for key, expected in [((1, 1), "6:00"), ((2, 1), "11:00")]:
                    row = cells[key]
                    self.assertEqual(row["status"], "source_supported")
                    self.assertEqual(pdf[0].get_textbox(pymupdf.Rect(row["bbox"]) + (-1, -1, 1, 1)).strip(), expected)
            self.assertEqual(cells[(1, 1)]["normalized"], {"type": "time", "value": "06:00"})
            self.assertLess(cells[(1, 1)]["bbox"][3], cells[(2, 1)]["bbox"][1])
            next(cell for cell in table["cells"] if (cell["r"], cell["c"]) == (1, 1))["text"] = "9:00"
            changed = next(row for row in CellEvidence.rule_rows(table, "hourly_operations", result["cell_boxes"])
                           if (row["r"], row["c"]) == (1, 1))
            self.assertEqual((changed["status"], changed["observed_text"], changed["normalized"]), ("review", "6:00", None))

    def test_visible_text_across_two_source_rows_requires_review(self):
        doc = DoclingDocument(name="compound")
        doc.add_page(page_no=1, size=Size(width=400, height=400))
        rows = ["6:00 11:00", "DIESEL (L) 4900"]
        cells = [TableCell(text=value, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                           start_col_offset_idx=0, end_col_offset_idx=1, bbox=coords)
                 for r, (value, coords) in enumerate(zip(rows, [box(87, 99, 120, 124), box(200, 50, 298, 64)]))]
        item = doc.add_table(data=TableData(num_rows=2, num_cols=1, table_cells=cells),
                             prov=ProvenanceItem(page_no=1, bbox=box(80, 40, 300, 145), charspan=(0, 0)))
        grid, _, record_cells, headers = table_views(item)
        part = {"page": 1, "source_ref": item.self_ref, "row_start": 0, "row_end": 2}
        table = {"table_id": "old", "doc_id": "report", "file_id": "file", "grid": grid, "header_rows": headers,
                 "cells": record_cells, "parts": [part]}
        words = [(90, 100, 110, 108, "6:00"), (90, 114, 113, 121, "11:00"),
                 (210, 52, 280, 61, rows[1])]
        refs = [("hourly", i, 1, list(word[:4])) for i, word in enumerate(words[:2], 1)]
        mixed, diesel = CellEvidence.native_rows(table, item, 400, words, refs, 400)
        self.assertEqual((mixed["text"], mixed["observed_text"]), (rows[0], rows[0]))
        self.assertEqual((mixed["status"], mixed["reason"]), ("review", "native_box_spans_source_rows"))
        self.assertEqual(diesel["status"], "text_matches_region")
        changed = deepcopy(table)
        changed["grid"][1][0] = "DIESEL (L) 4090"
        self.assertEqual({row["status"] for row in CellEvidence.native_rows(changed, item, 400, words, refs, 400)},
                         {"unavailable"})

    def test_only_trusted_column_units_are_normalized(self):
        self.assertEqual(normalized_value("1,250.0", "Set at (mGL)", "casing", 2),
                         {"type": "number", "value": "1250.0", "unit": "mGL"})
        self.assertIsNone(normalized_value("1,250 ft", "Set at (mGL)", "casing", 2))
        self.assertIsNone(normalized_value("1250", "Set at", "casing", 2))
        self.assertIsNone(normalized_value("1250", "Set at (mGL)", "docling_region", 2))

    def test_trimmed_native_cells_need_exact_shift_and_residual_bbox(self):
        doc = DoclingDocument(name="residual")
        doc.add_page(page_no=1, size=Size(width=400, height=400))
        values = ("Casing", "ID", "Independent measurements", "75.6")
        native = [TableCell(text=value, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                            start_col_offset_idx=0, end_col_offset_idx=1, column_header=r == 0,
                            bbox=box(30, 30 + r * 20, 230, 44 + r * 20)) for r, value in enumerate(values)]
        item = doc.add_table(data=TableData(num_rows=4, num_cols=1, table_cells=native),
                             prov=ProvenanceItem(page_no=1, bbox=box(20, 20, 300, 110), charspan=(0, 0)))
        grid, _, cells, _ = table_views(item)
        part = {"page": 1, "source_ref": item.self_ref, "row_start": 0, "row_end": 2, "header": [], "bbox": [20, 70, 300, 110]}
        table = {"table_id": "old", "file_id": "f", "doc_id": "doc", "parts": [part], "grid": grid[2:], "header_rows": 0,
                 "cells": [dict(cell, r=cell["r"] - 2) for cell in cells[2:]]}
        words = [(33, 71, 210, 82, values[2]), (45, 94, 62, 101, values[3])]
        for marker in ({}, {"native_trimmed_rows": 2}):
            row_a, row_b = CellEvidence.native_rows(table, item, 400, words, [], 400, part={**part, **marker})
            self.assertEqual([(row["native_r"], row["status"]) for row in (row_a, row_b)],
                             [(2, "text_matches_region"), (3, "text_matches_region")])
        for override in ({"bbox": [20, 20, 300, 110]}, {"native_trimmed_rows": 1}):
            result = CellEvidence.native_rows(table, item, 400, words, [], 400, part={**part, **override})
            self.assertEqual({row["status"] for row in result}, {"unavailable"})

    def test_joined_rows_keep_original_boxes_after_dropping_rotated_headers(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "joined.pdf"
            doc = DoclingDocument(name="joined")
            parts, grids, cells = [], [], []
            work_pages = {}
            with pymupdf.open() as pdf:
                rotations = ((0, 0), (90, 0), (180, 0), (270, 0), (0, 90))
                for page_num, (rotation, working) in enumerate(rotations, 1):
                    page = (pdf.new_page(width=430, height=300) if working
                            else pdf.new_page(width=340, height=470))
                    doc.add_page(page_no=page_num, size=Size(width=300, height=430))
                    values = ["Pressure PSI", f"Reading {1500 + page_num}"]
                    native_cells = []
                    for row, value in enumerate(values):
                        top = 30 + row * 23
                        if working:
                            page.insert_text((top + 13, 274), value, fontsize=10, rotate=90)
                        else:
                            page.insert_text((46, top + 33), value, fontsize=10)
                        native_cells.append(TableCell(text=value, start_row_offset_idx=row, end_row_offset_idx=row + 1,
                                                      start_col_offset_idx=0, end_col_offset_idx=1, column_header=row == 0,
                                                      bbox=box(20, top, 200, top + 16)))
                    if not working:
                        page.set_cropbox(pymupdf.Rect(20, 20, 320, 450))
                    page.set_rotation(rotation)
                    item = doc.add_table(data=TableData(num_rows=2, num_cols=1, table_cells=native_cells),
                                         prov=ProvenanceItem(page_no=page_num, bbox=box(20, 30, 200, 70), charspan=(0, 0)))
                    grid, _, record_cells, _ = table_views(item)
                    drop = int(page_num != 1)
                    offset = len(grids)
                    parts.append(dict(page=page_num, source_ref=item.self_ref, row_start=offset, row_end=offset + 2 - drop,
                                      header=grid[:1], bbox=[20, 30, 200, 70]))
                    grids.extend(grid[drop:])
                    cells.extend(dict(cell, r=offset + cell["r"] - drop) for cell in record_cells[drop:])
                    work_pages[page_num] = {"mode": "text", "rotation": rotation}
                    if rotation != working:
                        work_pages[page_num]["orientation"] = {"rotation": rotation, "normalized": True, "applied_rotate": working}
                pdf.save(path)
            table = {"table_id": "t", "file_id": "f", "doc_id": "doc", "pages": list(work_pages), "parts": parts,
                     "cells": cells, "grid": grids, "header_rows": 1}
            evidence = CellEvidence.__new__(CellEvidence)
            evidence.corpus = path.parent
            evidence.manifest = {"corpus_fingerprint": "test"}
            with pymupdf.open(path) as pdf, patch("graph_builder.corpus.qa.cell_evidence.load_native_document", return_value=(doc, work_pages)):
                modes = {("f", page): "text" for page in work_pages}
                rows = list(evidence.read_tables(path, pdf, {"file_id": "f"}, [table], modes))
                self.assertEqual([(row["r"], row["page"]) for row in rows], [(0, 1), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5)])
                for row in rows:
                    page = pdf[row["page"] - 1]
                    self.assertEqual(row["status"], "text_matches_region", row)
                    actual = page.get_textbox(pymupdf.Rect(row["bbox"]) * page.derotation_matrix)
                    self.assertEqual(actual, row["text"])
                parts[2]["header"] = [["different header"]]
                rows = list(evidence.read_tables(path, pdf, {"file_id": "f"}, [table], modes))
                self.assertEqual([(row["page"], row["reason"]) for row in rows if row["status"] == "unavailable"],
                                 [(3, "native_grid_or_page_mapping_changed")])


if __name__ == "__main__":
    unittest.main()
