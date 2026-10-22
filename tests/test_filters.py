"""Test structural exclusions and geometry-aware repeated-line filtering across coordinate origins and layout fragments."""
from __future__ import annotations

import unittest

from docling_core.types.doc import CoordOrigin, DocItemLabel, TableCell, TableData

from graph_builder.ingestion.filters import dropped_item_reasons, filter_running_lines
from test_chunking import add_text, make_document, provenance


def filtered(document: object) -> tuple[object, int]:
    return filter_running_lines(document, .08, .5, 1, .5, 3)


class FilterTests(unittest.TestCase):
    def test_varying_page_numbers_and_both_origins(self) -> None:
        for origin in (CoordOrigin.TOPLEFT, CoordOrigin.BOTTOMLEFT):
            document = make_document(4)
            for page in range(1, 5):
                document.add_text(label=DocItemLabel.TEXT, text=f"Release Page {page} of 4",
                                  prov=provenance(page, f"Release Page {page} of 4", 950, 960, origin=origin))
            before = document.export_to_dict()
            result, count = filtered(document)
            self.assertEqual(count, 4)
            self.assertTrue(all(not t.text for t in result.texts))
            self.assertEqual(before, document.export_to_dict())

    def test_frequency_uses_distinct_pages_and_exact_half(self) -> None:
        document = make_document(4)
        add_text(document, "Frequent", 1, 20, 30)
        add_text(document, "Frequent", 2, 20, 30)
        for _ in range(3):
            add_text(document, "Duplicates", 1, 20, 30)
        result, count = filtered(document)
        self.assertEqual(count, 2)
        self.assertEqual([t.text for t in result.texts[2:]], ["Duplicates"] * 3)

    def test_exact_band_and_interior_preservation(self) -> None:
        document = make_document(2)
        for page in (1, 2):
            add_text(document, "Top", page, 70, 80)
            add_text(document, "Bottom", page, 920, 930)
            add_text(document, "Outside", page, 81, 91, left=400, right=500)
            add_text(document, "Top", page, 500, 510)
        result, count = filtered(document)
        self.assertEqual(count, 4)
        self.assertEqual(sum(t.text == "Top" for t in result.texts), 2)
        self.assertEqual(sum(t.text == "Outside" for t in result.texts), 2)

    def test_anchored_aligned_block_requires_anchor_frequency_and_spacing(self) -> None:
        document = make_document(4)
        for page in range(1, 5):
            add_text(document, "Reference 42", page, 50, 60)
            add_text(document, f"Version Page {page} of 4", page, 68, 78)
            add_text(document, "Published 12 May", page, 86, 96)
            add_text(document, "Body starts", page, 160, 170)
            add_text(document, "Unaligned", page, 86, 96, left=400, right=500)
        add_text(document, "Unique note", 1, 104, 114)
        result, count = filtered(document)
        self.assertEqual(count, 12)
        self.assertEqual(sum(bool(t.text) for t in result.texts), 9)

    def test_repeated_block_without_margin_anchor_stays(self) -> None:
        document = make_document()
        for page in (1, 2):
            add_text(document, "Interior heading", page, 100, 110)
            add_text(document, "Interior subheading", page, 118, 128)
        self.assertEqual(filtered(document)[1], 0)

    def test_table_fragments_recover_full_line_frequency(self) -> None:
        document = make_document(4)
        for page in range(1, 5):
            add_text(document, "Reference 99", page, 50, 60)
            if page < 4:
                add_text(document, f"Version Page {page} of 4", page, 68, 78, right=260)
            else:
                cells = [TableCell(text=text, bbox=provenance(page, top=68, bottom=78, left=left, right=right).bbox,
                                   start_row_offset_idx=0, end_row_offset_idx=1, start_col_offset_idx=column,
                                   end_col_offset_idx=column + 1)
                         for column, (text, left, right) in enumerate([("Version", 100, 150), ("Page 4 of 4", 170, 260)])]
                document.add_table(data=TableData(num_rows=1, num_cols=2, table_cells=cells), prov=provenance(page))
            add_text(document, "Published May", page, 86, 96)
        result, count = filtered(document)
        self.assertEqual(count, 13)
        self.assertTrue(all(not cell.text for cell in result.tables[0].data.table_cells))

    def test_whitespace_case_normalization_and_charspan_remapping(self) -> None:
        document = make_document()
        first = add_text(document, "  Shared   LINE\n", 1, 20, 30)
        first.prov[0].charspan = (0, len(first.text))
        add_text(document, "shared line", 2, 20, 30)
        result, count = filtered(document)
        self.assertEqual(count, 2)
        self.assertEqual(result.texts[0].prov[0].charspan, (0, 0))

    def test_structural_drops_and_substantive_heading(self) -> None:
        document = make_document()
        toc_heading = add_text(document, "Table of Contents", label=DocItemLabel.SECTION_HEADER)
        toc = add_text(document, "Overview .... 2", label=DocItemLabel.DOCUMENT_INDEX)
        header = add_text(document, "Running header", label=DocItemLabel.PAGE_HEADER)
        footer = add_text(document, "Running footer", label=DocItemLabel.PAGE_FOOTER)
        picture = document.add_picture(prov=provenance(1))
        ordinary = add_text(document, "Measurements", label=DocItemLabel.SECTION_HEADER)
        reasons = dropped_item_reasons(document)
        for item in (toc_heading, toc, header, footer, picture):
            self.assertIn(item.self_ref, reasons)
        self.assertNotIn(ordinary.self_ref, reasons)
