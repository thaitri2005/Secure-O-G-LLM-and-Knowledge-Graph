"""Retry collapsed tables on isolated rotated pages and retain measured improvements."""
from __future__ import annotations

from pathlib import Path
from docling_core.types.doc import BoundingBox, DoclingDocument
from pypdf import PdfReader, PdfWriter

from .evaluation import fidelity
from .sources import write_json


def restore_box(box, original_height: float, rotated_height: float):
    box = box.to_top_left_origin(page_height=rotated_height)
    return BoundingBox(l=box.t, t=original_height - box.r, r=box.b,
                       b=original_height - box.l, coord_origin="TOPLEFT")


def table_score(tables: list, reference: str) -> dict:
    text = " ".join(cell.text for table in tables for cell in table.data.table_cells)
    return {"cells": sum(bool(cell.text.strip()) for table in tables for cell in table.data.table_cells),
            "word_recall": fidelity(reference, text)["word_recall"] or 0.0}


def improves(before: dict, after: dict) -> bool:
    return after["cells"] > before["cells"] and after["word_recall"] > before["word_recall"]


def retry_rotated_tables(document, pdf: Path, directory: Path, options: dict):
    document = document.model_copy(deep=True)
    reader = PdfReader(pdf)
    candidates = sorted({t.prov[0].page_no for t in document.tables if t.prov and t.data.table_cells
                         and (t.data.num_rows <= 1 or any(len(c.text) > 1000 for c in t.data.table_cells)
                              or document.pages[t.prov[0].page_no].size.width > document.pages[t.prov[0].page_no].size.height
                              or reader.pages[t.prov[0].page_no - 1].rotation)})
    directory.mkdir(parents=True, exist_ok=True)
    converter, report = None, []
    for number in candidates:
        original = [t for t in document.tables if t.prov and t.prov[0].page_no == number]
        reference = reader.pages[number - 1].extract_text() or ""
        before = table_score(original, reference)
        cached = directory / f"page_{number}.json"
        if not cached.exists():
            isolated = directory / f"page_{number}.pdf"
            writer = PdfWriter()
            writer.add_page(reader.pages[number - 1])
            writer.pages[0].rotate(90)
            writer.write(isolated)
            if converter is None:
                from .convert import make_converter
                converter = make_converter(options)
            result = converter.convert(isolated)
            if result.status.value != "success":
                raise RuntimeError(f"Rotated page conversion failed: {number}")
            write_json(cached, result.document.export_to_dict())
        rotated = DoclingDocument.model_validate_json(cached.read_text(encoding="utf-8"))
        after = table_score(rotated.tables, reference)
        accepted = improves(before, after)
        report.append({"page": number, "degrees": 90, "before": before, "after": after, "accepted": accepted})
        if accepted:
            anchor = original[-1]
            for table in rotated.tables:
                table = table.model_copy(deep=True)
                table.captions = []
                table.children = []
                for prov in table.prov:
                    prov.bbox = restore_box(prov.bbox, document.pages[number].size.height, rotated.pages[1].size.height)
                    prov.page_no = number
                for cell in table.data.table_cells:
                    if cell.bbox:
                        cell.bbox = restore_box(cell.bbox, document.pages[number].size.height, rotated.pages[1].size.height)
                document.insert_item_after_sibling(new_item=table, sibling=anchor)
                anchor = table
            document.delete_items(node_items=original)
        write_json(directory / "rotation_metrics.json", report)
    return document, report
