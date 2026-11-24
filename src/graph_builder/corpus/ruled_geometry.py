"""Map physical cell rectangles to a logical grid with explicit span owners."""
from __future__ import annotations

from collections import Counter
import re

from .column_alignment import comparison
from .numeric_cells import compact
from ..ingestion.scoring import bbox_iou


def cell_slots(rectangles):
    """Return the dimensions and owners of a complete rectangular tiling."""
    boxes = sorted({tuple(round(value, 2) for value in box) for box in rectangles},
                   key=lambda box: (box[1], box[0], box[3], box[2]))
    if not boxes:
        return None
    x = sorted({edge for box in boxes for edge in (box[0], box[2])})
    y = sorted({edge for box in boxes for edge in (box[1], box[3])})
    rows, cols = len(y) - 1, len(x) - 1
    if not (2 <= rows <= 200 and 2 <= cols <= 40):
        return None
    taken, owners = set(), []
    for left, top, right, bottom in boxes:
        r, end_r, c, end_c = y.index(top), y.index(bottom), x.index(left), x.index(right)
        covered = {(i, j) for i in range(r, end_r) for j in range(c, end_c)}
        if not covered or taken.intersection(covered):
            return None
        taken.update(covered)
        owners.append((r, c, end_r - r, end_c - c, [left, top, right, bottom]))
    return (rows, cols, owners) if len(taken) == rows * cols else None


def materialize_panel(shape, bbox, read_cell):
    """Represent each printed cell once, at the origin of its span."""
    rows, cols, owners = shape
    grid = [[""] * cols for _ in range(rows)]
    boxes = [[None] * cols for _ in range(rows)]
    cells = []
    for r, c, row_span, col_span, box in owners:
        value = read_cell(box)
        if value is None or "|" in value:
            return None
        grid[r][c], boxes[r][c] = value, box
        if value or row_span > 1 or col_span > 1:
            cells.append(dict(r=r, c=c, row_span=row_span, col_span=col_span, text=value, is_header=r == 0))
    headers = max((cell["row_span"] for cell in cells if cell["r"] == 0), default=1)
    if headers >= rows or any(0 < cell["r"] < headers < cell["r"] + cell["row_span"] for cell in cells):
        return None
    for cell in cells:
        cell["is_header"] = cell["r"] < headers
    return {"bbox": list(bbox), "grid": grid, "cell_boxes": boxes, "cells": cells, "header_rows": headers}


def conservative_replacement(panel, original, chunks, page, *, ocr):
    """Preserve the complete native token inventory and any caption when changing table structure."""
    from .ops_tables import chunk_template
    from .qa.crossrep import parse_table_chunk

    def positions(cells):
        return sorted((cell["r"], cell["c"], cell["row_span"], cell["col_span"], compact(cell["text"]))
                      for cell in cells if cell["text"].strip())

    def tokens(values):
        return Counter(re.findall(r"\w+|[^\w\s]", comparison(" ".join(values))))

    if (not original["source_ref"].startswith("#/tables/") or len(original["regions"]) != 1 or not chunks
            or any(c["pages"] != [page] or c["ocr"] != ocr for c in chunks)
            or any(cell.get("ocr_unreadable") for cell in panel["cells"])):
        return None
    old_box = original["regions"][0]["bbox"]
    if panel.get("structure"):
        overlaps = bbox_iou(old_box, panel["bbox"]) >= .85
    else:
        overlaps = all(abs(a - b) <= 3 for a, b in zip(panel["bbox"], old_box, strict=True))
    if not overlaps:
        return None
    before, after = positions(original["cells"]), positions(panel["cells"])
    printed = tokens(cell[-1] for cell in after)
    if before == after or tokens(cell[-1] for cell in before) != printed:
        return None
    parsed = [parse_table_chunk(chunk["text"]) for chunk in chunks]
    if (any(not part["separator_ok"] or part["stray"] or part["header"] != parsed[0]["header"] for part in parsed)
            or any(part["caption"] not in ([], parsed[0]["caption"]) for part in parsed)):
        return None
    # Native Markdown can flatten stacked headings using a generated separator.
    header = [re.sub(r"\s[-/]\s", " ", title) for title in parsed[0]["header"]]
    header_rows = original.get("rendered_header_rows", original["header_rows"])
    for cell in original["cells"]:
        column, width = cell["c"], cell["col_span"]
        if cell["r"] >= header_rows or not cell["is_header"] or width == 1 or column + width > len(header):
            continue
        value = compact(cell["text"])
        if value and compact(header[column]) == value:
            for covered in range(column + 1, column + width):
                if compact(header[covered]) == value:
                    header[covered] = ""
    body = [value for part in parsed for row in part["rows"] for value in row]
    if tokens(header + body) - printed:
        return None
    return chunk_template(chunks[0]), "\n".join(parsed[0]["caption"])
