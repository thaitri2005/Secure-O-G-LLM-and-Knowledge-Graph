"""Separate a corroborated line of printed table text from blue ink below it."""
from __future__ import annotations

from collections import defaultdict
import re
import shutil
import subprocess

from ..ingestion.tables import table_row_texts
from .numeric_cells import chunk_edits, compact, patch_chunk
from .scan_fields import literal, rapid_reader, tesseract_line

RULE = "scan_table_ink"


def replaces_suffix(original, printed):
    words = printed.split()
    previous = original.split()
    return (len(words) >= 2 and len(words) < len(previous) and any(word.isalpha() for word in words)
            and literal(" ".join(previous[:len(words)])) == literal(printed))


def read_printed(page, box, models, original):
    import cv2
    import numpy as np
    import pymupdf

    command = shutil.which("tesseract")
    if command is None or not 8 <= box[2] - box[0] <= 420 or not 8 <= box[3] - box[1] <= 75:
        return None
    clip = pymupdf.Rect(box) + (-1, -1, 1, 1)
    px = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(4, 4), colorspace=pymupdf.csRGB, alpha=False)
    rgb = np.frombuffer(px.samples, np.uint8).reshape(px.height, px.width, 3)
    red, green, blue = np.moveaxis(rgb.astype(np.int16), 2, 0)
    colored = (blue - red >= 19) & (blue - green >= 10)
    if not colored.any():
        return None
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    ink = np.where(colored, 255, grey).astype(np.uint8)
    # Vector rulings may be included at the edge of a native OCR cell.
    ink[(ink < 145).sum(axis=1) > .78 * px.width] = 255
    counts = (ink < 145).sum(axis=1)
    active = np.flatnonzero(counts >= max(4, .14 * counts.max(initial=0)))
    bands = [rows for rows in np.split(active, np.flatnonzero(np.diff(active) > 3) + 1)
             if len(rows) >= 10]
    if len(bands) != 1:
        return None
    start, stop = int(bands[0][0]), int(bands[0][-1]) + 1
    if (stop - start > .55 * px.height or colored[stop + 3:].sum() < px.width
            or (counts[stop + 3:] >= max(4, .14 * counts.max())).sum() > 5):
        return None
    reader = rapid_reader(models.resolve(), detect=False)
    for first, last, inset in ((start - 2, stop + 2, 0), (start + 1, stop + 5, round((stop - start) / 2))):
        crop = ink[max(0, first):min(px.height, last), inset:]
        if crop.size == 0:
            continue
        padded = cv2.copyMakeBorder(crop, 22, 22, 22, 22, cv2.BORDER_CONSTANT, value=255)
        found = reader(cv2.cvtColor(padded, cv2.COLOR_GRAY2BGR))
        if not found.txts or len(found.txts) != 1 or found.scores[0] < .9:
            continue
        text = compact(found.txts[0])
        other = compact(tesseract_line(command, padded))
        # Tesseract sometimes emits a vertical bar for a printed capital I followed by a period.
        other = re.sub(r"(?<!\S)\|\.", "I.", other)
        if literal(other) == literal(text) and replaces_suffix(original, text):
            return text
    return None


def native_box(cell, height):
    box = cell.bbox.to_top_left_origin(page_height=height)
    return [box.l, box.t, box.r, box.b]


def repair_document(pdf, pages, tables, chunks, get_native, models, *, stacked_pages=()):
    eligible = {row["page"] for row in pages if row.get("mode") == "ocr" and not row.get("rotation")
                and not (row.get("orientation") or {}).get("normalized") and row["page"] not in stacked_pages}
    candidates = [(table, table["parts"][0]) for table in tables if len(table["parts"]) == 1
                  and table["pages"][0] in eligible and table["parts"][0]["source_ref"].startswith("#/tables/")]
    if not candidates:
        return
    import pymupdf

    children = defaultdict(list)
    for chunk in chunks:
        if chunk["type"] == "table" and chunk["ocr"]:
            children[chunk["table_id"]].append(chunk)
    native = get_native()
    with pymupdf.open(pdf) as source:
        for table, part in candidates:
            page = source[part["page"] - 1]
            item = native.get(part["source_ref"])
            if page.rotation or item is None or len(item.prov) != 1 or item.prov[0].page_no != part["page"]:
                continue
            for_scan = {}
            for cell in item.data.table_cells:
                r, c = cell.start_row_offset_idx, cell.start_col_offset_idx
                original = compact(cell.text)
                if (not table["header_rows"] <= r < table["num_rows"] or cell.bbox is None
                        or cell.row_span != 1 or cell.col_span != 1 or len(original.split()) < 3
                        or not 0 <= c < table["num_cols"] or compact(table["grid"][r][c]) != original):
                    continue
                records = [record for record in table["cells"] if (record["r"], record["c"]) == (r, c)]
                if len(records) != 1 or records[0]["is_header"]:
                    continue
                box = [round(v, 2) for v in native_box(cell, page.rect.height)]
                if not (0 <= box[0] < box[2] <= page.rect.width and 0 <= box[1] < box[3] <= page.rect.height):
                    continue
                try:
                    value = read_printed(page, box, models, original)
                except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                    continue
                if value:
                    for_scan[r, c] = (records[0], {"r": r, "c": c, "value": value, "previous": original, "bbox": box})
            if not for_scan:
                continue
            plan = {key: change for key, (_, change) in for_scan.items()}
            loc = children[table["logical_id"]]
            edits = [chunk_edits(chunk, plan, table["num_cols"]) for chunk in loc]
            owners = defaultdict(list)
            for index, group in enumerate(edits):
                for key in group:
                    owners[key].append(index)
            accepted, patches = [], defaultdict(list)
            for (r, c), (record, change) in for_scan.items():
                if len(owners[r, c]) != 1:
                    continue
                index, = owners[r, c]
                patches[index].append(edits[index][r, c])
                record["text"] = table["grid"][r][c] = change["value"]
                accepted.append(change)
            if accepted:
                part["scan_repairs"] = accepted
                table["rows_text"] = table_row_texts(table["grid"], table["header_rows"], table["num_cols"])
                for index, changes in patches.items():
                    patch_chunk(loc[index], changes)
                    loc[index]["quality"] = "review"
