"""Exercise reading order, page and section boundaries, table row splitting, and source immutability with small documents."""
from __future__ import annotations

import unittest

from docling_core.types.doc import BoundingBox, CoordOrigin, DocItemLabel, DoclingDocument, ProvenanceItem, Size, TableCell, TableData

from graph_builder.ingestion.chunking import chunks_from_document, split_table


def make_document(pages: int = 2) -> DoclingDocument:
    document = DoclingDocument(name="Example report")
    for page in range(1, pages + 1):
        document.add_page(page_no=page, size=Size(width=600, height=1000))
    return document


def provenance(page: int, text: str = "", top: float = 300, bottom: float = 310,
               left: float = 100, right: float = 300, origin: CoordOrigin = CoordOrigin.TOPLEFT) -> ProvenanceItem:
    box = BoundingBox(l=left, t=top, r=right, b=bottom)
    if origin == CoordOrigin.BOTTOMLEFT:
        box = box.to_bottom_left_origin(page_height=1000)
    return ProvenanceItem(page_no=page, bbox=box, charspan=(0, len(text)))


def add_text(document: DoclingDocument, text: str, page: int = 1, top: float = 300, bottom: float = 310,
             label: DocItemLabel = DocItemLabel.TEXT, **kwargs: float) -> object:
    if label == DocItemLabel.DOCUMENT_INDEX:
        cell = TableCell(text=text, start_row_offset_idx=0, end_row_offset_idx=1,
                         start_col_offset_idx=0, end_col_offset_idx=1)
        return document.add_table(data=TableData(num_rows=1, num_cols=1, table_cells=[cell]),
                                  prov=provenance(page, text, top, bottom, **kwargs), label=label)
    return document.add_text(label=label, text=text, prov=provenance(page, text, top, bottom, **kwargs))


def add_table(document: DoclingDocument, page: int = 1, rows: int = 3, caption: object = None) -> object:
    cells = [TableCell(text="Column" if row == 0 else f"Row {row}", start_row_offset_idx=row, end_row_offset_idx=row + 1,
                       start_col_offset_idx=0, end_col_offset_idx=1, column_header=row == 0)
             for row in range(rows)]
    return document.add_table(data=TableData(num_rows=rows, num_cols=1, table_cells=cells),
                              prov=provenance(page), caption=caption)


def chunks(document: DoclingDocument, limit: int = 1500) -> tuple[list[dict], dict]:
    return chunks_from_document(document, "sample", limit, .08, .5, 1, .5, 3)


class ChunkingTests(unittest.TestCase):
    def test_page_section_and_table_boundaries(self) -> None:
        document = make_document()
        add_text(document, "Overview", label=DocItemLabel.SECTION_HEADER)
        add_text(document, "First paragraph.")
        caption = add_text(document, "Measurements", label=DocItemLabel.CAPTION)
        add_table(document, caption=caption)
        add_text(document, "Second page.", page=2)
        add_text(document, "Details", page=2, label=DocItemLabel.SECTION_HEADER)
        add_text(document, "Details paragraph.", page=2)
        before = document.export_to_dict()
        records, stats = chunks(document)
        self.assertEqual([c["type"] for c in records], ["text", "table", "text", "text"])
        self.assertEqual([c["page"] for c in records], [1, 1, 2, 2])
        self.assertEqual([c["section"] for c in records], ["Overview", "Overview", "Overview", "Details"])
        self.assertEqual([c["chunk_id"] for c in records], [f"sample#c{i:04d}" for i in range(4)])
        self.assertEqual(records[1]["text"].count("Measurements"), 1)
        self.assertEqual(before, document.export_to_dict())
        self.assertEqual(stats["table_chunks"], 1)

    def test_multipage_text_charspans_and_table_first_page(self) -> None:
        document = make_document()
        item = add_text(document, "Alpha.Beta.")
        item.prov[0].charspan = (0, 6)
        item.prov.append(provenance(2))
        item.prov[1].charspan = (6, 11)
        table = add_table(document)
        table.prov.append(provenance(2))
        records, stats = chunks(document)
        self.assertEqual([(c["page"], c["text"]) for c in records[:2]], [(1, "Alpha."), (2, "Beta.")])
        self.assertEqual(records[-1]["page"], 1)
        self.assertEqual(stats["multi_page_tables"], [table.self_ref])

    def test_empty_tables_missing_provenance_and_picture_text(self) -> None:
        document = make_document()
        empty = document.add_table(data=TableData(), prov=provenance(1))
        orphan = document.add_text(label=DocItemLabel.TEXT, text="No page")
        picture = document.add_picture(prov=provenance(1))
        document.add_text(label=DocItemLabel.CAPTION, text="Chart caption", parent=picture, prov=provenance(1))
        records, stats = chunks(document)
        self.assertEqual(stats["empty_tables"], [empty.self_ref])
        self.assertEqual(stats["no_provenance"], [orphan.self_ref])
        self.assertEqual(records[0]["text"], "Chart caption")

    def test_row_splitting_repeats_header_and_preserves_rows(self) -> None:
        markdown = "Caption\n| Name | Value |\n| ------ | ----- |\n| A | " + "x" * 30 + " |\n| B | " + "y" * 30 + " |"
        parts = split_table(markdown, "Caption", 80)
        self.assertEqual(len(parts), 2)
        self.assertTrue(all(p.startswith("Caption\n| Name | Value |\n| --- | --- |") for p in parts))
        self.assertTrue(all(len(p) <= 80 for p in parts))
        self.assertEqual(sum(p.count("x" * 30) for p in parts), 1)
        self.assertEqual(sum(p.count("y" * 30) for p in parts), 1)

    def test_oversized_row_is_not_truncated(self) -> None:
        text = "| H |\n| --- |\n| " + "z" * 100 + " |"
        self.assertIn("z" * 100, split_table(text, "", 20)[0])

    def test_invalid_budget(self) -> None:
        with self.assertRaises(ValueError):
            chunks(make_document(), 0)
