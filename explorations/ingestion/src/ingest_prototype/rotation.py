"""Retry upright pages and retain tables only when both measured scores improve."""
from __future__ import annotations

from pathlib import Path

from .convert import segment


def score(tables: list, reference: str) -> dict:
    from graph_builder.ingestion.evaluation import fidelity
    text = ' '.join(cell.text for table in tables for cell in table.data.table_cells)
    return {'cells': sum(bool(cell.text.strip()) for table in tables for cell in table.data.table_cells),
            'word_recall': fidelity(reference, text)['word_recall'] or 0.0}


def improves(before: dict, after: dict) -> bool:
    return after['cells'] > before['cells'] and after['word_recall'] > before['word_recall']


def restore_box(box, width: float, height: float, rotated_height: float, degrees: int):
    from docling_core.types.doc import BoundingBox
    box = box.to_top_left_origin(page_height=rotated_height)
    if degrees == 90:
        values = (box.t, height - box.r, box.b, height - box.l)
    elif degrees == 270:
        values = (width - box.b, box.l, width - box.t, box.r)
    else:
        values = (width - box.r, height - box.b, width - box.l, height - box.t)
    return BoundingBox(l=values[0], t=values[1], r=values[2], b=values[3], coord_origin='TOPLEFT')


def retry(document, source: Path, directory: Path, config: dict) -> tuple:
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(source)
    document = document.model_copy(deep=True)
    attempts = []
    for number, page in sorted(document.pages.items()):
        original = [t for t in document.tables if t.prov and t.prov[0].page_no == number]
        rotation = reader.pages[number - 1].rotation % 360
        if not rotation and not (page.size.width > page.size.height and original):
            continue
        degrees = (360 - rotation) % 360 if rotation else 90
        folder = directory / str(number)
        folder.mkdir(parents=True, exist_ok=True)
        isolated = folder / 'upright.pdf'
        if not isolated.exists():
            writer = PdfWriter()
            writer.add_page(reader.pages[number - 1])
            writer.pages[0].rotate(degrees)
            writer.write(isolated)
        upright, _ = segment(isolated, 'text', None, folder / 'document.json.gz', config)
        reference = reader.pages[number - 1].extract_text() or ''
        before, after = score(original, reference), score(upright.tables, reference)
        accepted = bool(original) and improves(before, after)
        attempts.append({'page': number, 'source_rotation': rotation, 'degrees': degrees,
                         'before': before, 'after': after, 'accepted': accepted})
        if not accepted:
            continue
        anchor = original[-1]
        for table in upright.tables:
            table = table.model_copy(deep=True)
            table.captions, table.children = [], []
            for provenance in table.prov:
                provenance.bbox = restore_box(provenance.bbox, page.size.width, page.size.height,
                                              upright.pages[1].size.height, degrees)
                provenance.page_no = number
            for cell in table.data.table_cells:
                if cell.bbox:
                    cell.bbox = restore_box(cell.bbox, page.size.width, page.size.height,
                                            upright.pages[1].size.height, degrees)
            document.insert_item_after_sibling(new_item=table, sibling=anchor)
            anchor = table
        document.delete_items(node_items=original)
    return document, attempts
