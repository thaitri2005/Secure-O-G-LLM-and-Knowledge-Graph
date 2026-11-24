"""Recover geometrically closed scan tables with cell-local OCR agreement."""
from __future__ import annotations

from collections import defaultdict
import csv
import io
import math
import os
import shutil
import subprocess

from ..ingestion.scoring import bbox_iou
from .column_alignment import comparison
from .numeric_cells import compact, read_words
from .ocr_engines import DEFAULT_MODELS
from .ops_tables import grid_table_record, table_chunks
from .orientation import rotate_bbox
from .ruled_geometry import cell_slots, conservative_replacement, materialize_panel
from .scan_fields import rapid_reader, tesseract_line
from .source_grids import NUMERIC, intersects

RULE = "scan_grid"


def snapped_edges(values, tolerance):
    groups = []
    for value in sorted(set(values)):
        if not groups or value - groups[-1][0] > tolerance:
            groups.append([])
        groups[-1].append(value)
    return {value: (group[0] + group[-1]) // 2 for group in groups for value in group}


def ruler_masks(gray):
    import cv2
    import numpy as np

    length = max(24, min(gray.shape) // 36)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    masks = []
    for axis in ((1, length), (length, 1)):
        # Join short breaks along the ruling axis before looking for long strokes.
        gap = (1, 5) if axis[0] == 1 else (5, 1)
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones(gap, np.uint8))
        masks.append(cv2.morphologyEx(closed, cv2.MORPH_OPEN, np.ones(axis, np.uint8)))
    return masks


def enclosed_rectangles(lines):
    import cv2

    contours, tree = cv2.findContours(lines, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    grouped = defaultdict(list)
    if tree is None:
        return grouped.values()
    for index, (_, _, _, parent) in enumerate(tree[0]):
        if parent < 0:
            continue
        x, y, w, h = cv2.boundingRect(contours[index])
        if w >= 14 and h >= 14 and cv2.contourArea(contours[index]) >= .86 * w * h:
            grouped[parent].append((x, y, x + w, y + h))
    return grouped.values()


def scan_rulings(gray):
    """Separate long grid lines from glyphs and enumerate closed rectangular cells."""
    import cv2

    lines = cv2.bitwise_or(*ruler_masks(gray))
    shapes = []
    for rectangles in enclosed_rectangles(lines):
        if len(rectangles) < 4:
            continue
        x = snapped_edges((v for box in rectangles for v in (box[0], box[2])), 6)
        y = snapped_edges((v for box in rectangles for v in (box[1], box[3])), 6)
        shape = cell_slots([(x[l], y[t], x[r], y[b]) for l, t, r, b in rectangles])
        if shape and len(shape[2]) >= 4:
            shapes.append(shape)
    return lines, shapes


def visible_edges(box, horizontal, vertical, slack):
    """A repair can bridge interrupted ink. Every cell edge still needs majority source support."""
    import numpy as np

    left, top, right, bottom = box
    rows, cols = horizontal.shape
    return all(np.any(horizontal[max(0, y - slack):min(rows, y + slack + 1), left:right], axis=0).mean() >= .65
               for y in (top, bottom)) and all(
        np.any(vertical[top:bottom, max(0, x - slack):min(cols, x + slack + 1)], axis=1).mean() >= .65
        for x in (left, right))


def regular_islands(rectangles, slack):
    """Find rectangular islands of enclosed cells inside a fragmented ruling network."""
    if len(rectangles) < 6:
        return
    x = snapped_edges((v for box in rectangles for v in (box[0], box[2])), slack)
    y = snapped_edges((v for box in rectangles for v in (box[1], box[3])), slack)
    rows = defaultdict(dict)
    for left, top, right, bottom in rectangles:
        if x[right] > x[left] and y[bottom] > y[top]:
            rows[y[top]].setdefault(y[bottom], set()).add((x[left], x[right]))
    found = set()
    for top, ends in rows.items():
        for bottom, spans in ends.items():
            pending = [(bottom, spans, (top, bottom))]
            while pending:
                last, common, ordinates = pending.pop()
                if len(ordinates) >= 4:
                    chains = []
                    for left, right in sorted(common):
                        if not chains or chains[-1][-1][1] != left:
                            chains.append([])
                        chains[-1].append((left, right))
                    for chain in chains:
                        if len(chain) >= 2:
                            found.add(tuple((l, t, r, b) for t, b in zip(ordinates, ordinates[1:]) for l, r in chain))
                if len(ordinates) >= 201:
                    continue
                following = [(end, common & spans) for end, spans in rows.get(last, {}).items()
                             if len(common & spans) >= 2]
                if len(following) == 1:
                    end, overlap = following[0]
                    pending.append((end, overlap, (*ordinates, end)))
    # A smaller coincident island adds no rows or columns.
    maximal = []
    for island in sorted(found, key=lambda item: (-len(item), item)):
        cells = set(island)
        if not any(cells <= previous for previous in maximal):
            maximal.append(cells)
            shape = cell_slots(island)
            if shape:
                yield shape


def broken_rulings(gray, *, masks=None):
    import cv2
    import numpy as np

    horizontal, vertical = masks if masks is not None else ruler_masks(gray)
    shorter = min(gray.shape)
    gap = max(7, round(shorter * .025))
    slack = max(4, round(shorter * .005))
    joined = [cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones(axis, np.uint8))
              for mask, axis in ((horizontal, (1, gap)), (vertical, (gap, 1)))]
    repaired = cv2.bitwise_or(*joined)
    shapes = []
    for group in enclosed_rectangles(repaired):
        supported = [box for box in group if visible_edges(box, horizontal, vertical, slack)]
        shapes.extend(regular_islands(supported, slack + 1))
    # Only original ink is masked before recognition. The virtual joins cannot erase characters.
    return cv2.bitwise_or(horizontal, vertical), shapes


def deskew(gray):
    """Use a small correction only when both ruling axes agree on the skew."""
    import cv2
    import numpy as np

    height, width = gray.shape
    length = max(48, min(width, height) // 8)
    contrast = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    lines = cv2.HoughLinesP(cv2.Canny(contrast, 45, 140), 1, np.pi / 720, threshold=length // 2,
                           minLineLength=length, maxLineGap=max(8, length // 12))
    if lines is None:
        return None
    axes = defaultdict(list)
    for x0, y0, x1, y1 in lines.reshape(-1, 4):
        angle = math.degrees(math.atan2(int(y1 - y0), int(x1 - x0)))
        nearest = round(angle / 90)
        delta = angle - nearest * 90
        if abs(delta) <= 5:
            axes[nearest % 2].append(delta)
    if min(len(axes[0]), len(axes[1])) < 3:
        return None
    a, b = (float(np.median(axes[axis])) for axis in (0, 1))
    angle = (a + b) / 2
    if abs(a - b) > .6 or abs(angle) < .4:
        return None
    if any(sum(abs(v - angle) <= .7 for v in angles) < len(angles) * .6 for angles in axes.values()):
        return None
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    corrected = cv2.warpAffine(gray, matrix, (width, height), borderValue=255)
    return corrected, cv2.invertAffineTransform(matrix)


def tess_words(command, image):
    import cv2

    encoded, png = cv2.imencode(".png", image)
    if not encoded:
        return []
    result = subprocess.run([command, "stdin", "stdout", "-l", "eng", "--psm", "11", "tsv"],
                            input=png.tobytes(), capture_output=True, timeout=12,
                            env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    if result.returncode:
        return []
    fields = csv.DictReader(io.StringIO(result.stdout.decode(errors="replace")), delimiter="\t", quoting=csv.QUOTE_NONE)
    words = []
    for item in fields:
        text = (item.get("text") or "").strip()
        if not text or float(item["conf"]) < 45:
            continue
        x, y, width, height = (int(item[key]) for key in ("left", "top", "width", "height"))
        words.append((text, [x, y, x + width, y + height]))
    return words


def upright_view(command, image, boxes, *, upscale=False):
    import cv2
    import numpy as np

    height, width = image.shape
    proposals = []
    for turn in range(4):
        rotated = np.ascontiguousarray(np.rot90(image, turn))
        factor = min(2.0, max(1.0, 2200 / max(rotated.shape))) if upscale else 1.0
        search = cv2.resize(rotated, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC) if factor > 1 else rotated
        words = [(text, [v / factor for v in box]) for text, box in tess_words(command, search)]
        geometry = [rotate_bbox(box, width, height, -90 * turn) for box in boxes]
        # Text inside cells establishes orientation. Digits alone are too ambiguous.
        score = sum(sum(letter.isalpha() for letter in read_words(words, box)) for box in geometry)
        proposals.append((score, turn, rotated, words, geometry))
    proposals.sort(key=lambda item: item[0], reverse=True)
    winner, runner = proposals[:2]
    return winner[1:] if winner[0] >= 10 and winner[0] >= 1.20 * max(1, runner[0]) else None


def exact_value(rapid, command, crop, raw, *, alternate=False):
    import cv2
    import numpy as np

    background = np.percentile(crop, 80)
    active = np.argwhere(crop < min(225, background - 18))
    if len(active) < 8:
        return ""
    top, left = active.min(axis=0)
    bottom, right = active.max(axis=0)
    # Retain all ink. This path does not remove annotations from a cell.
    area = np.s_[max(0, top - 2):bottom + 3, max(0, left - 2):right + 3]
    crop, raw = (cv2.normalize(image[area], None, 0, 255, cv2.NORM_MINMAX) for image in (crop, raw))

    def pad(image):
        return cv2.copyMakeBorder(image, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)

    independent = compact(tesseract_line(command, pad(raw)))
    if not independent and not alternate:
        return None
    _, binary = cv2.threshold(raw, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    variants = (crop, raw, cv2.resize(binary, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
    results = {}
    for image in variants:
        result = rapid(cv2.cvtColor(pad(image), cv2.COLOR_GRAY2BGR))
        if result.txts and len(result.txts) == 1 and result.scores[0] >= .88:
            value = compact(result.txts[0])
            if comparison(value) == comparison(independent):
                return value
            if value:
                results[comparison(value)] = value
    if alternate and results:
        enlarged = cv2.resize(raw, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        other = compact(tesseract_line(command, pad(enlarged), mode=8))
        # Treat conflicting quantitative reads as unresolved. A single glyph can be a digit or a border remnant.
        if other and not (NUMERIC.search(independent) and comparison(independent) != comparison(other)):
            return results.get(comparison(other))
    return None


def read_panel(gray, raw, shape, command, models, *, upscale=False):
    import numpy as np

    _, _, owners = shape
    left = min(box[0] for *_, box in owners)
    top = min(box[1] for *_, box in owners)
    right = max(box[2] for *_, box in owners)
    bottom = max(box[3] for *_, box in owners)
    boxes = [[box[0] - left, box[1] - top, box[2] - left, box[3] - top] for *_, box in owners]
    width, height = right - left, bottom - top
    view = upright_view(command, gray[top:bottom, left:right], boxes, upscale=upscale)
    if view is None:
        return None
    turn, image, _, geometry = view
    original = np.ascontiguousarray(np.rot90(raw[top:bottom, left:right], turn))
    shape = cell_slots(geometry)
    if shape is None:
        return None
    _, cols, owners = shape
    banner = {tuple(box) for r, c, rows, span, box in owners
              if r == 0 and c == 0 and rows == 1 and span >= .8 * cols}
    if banner:
        end = max(box[3] for box in banner)
        retained = [box for *_, box in owners if box[1] >= end]
        if any(box[1] < end < box[3] for *_, box in owners) or (shape := cell_slots(retained)) is None:
            return None
    rapid = rapid_reader(models.resolve(), detect=False)
    missing = set()

    def read_cell(box):
        l, t, r, b = map(round, box)
        crop = image[t + 2:b - 2, l + 2:r - 2]
        if crop.size:
            raw = original[t + 2:b - 2, l + 2:r - 2]
            text = exact_value(rapid, command, crop, raw, alternate=upscale)
            if text is not None:
                return text
        missing.add(tuple(box))
        return ""

    logical = [box for *_, box in shape[2]]
    grid_box = [min(box[0] for box in logical), min(box[1] for box in logical),
                max(box[2] for box in logical), max(box[3] for box in logical)]
    panel = materialize_panel(shape, grid_box, read_cell)
    if panel is None:
        return None
    headers = panel["header_rows"]
    labels = {value.casefold() for row in panel["grid"][:headers] for value in row if any(char.isalpha() for char in value)}
    body = panel["grid"][headers:]
    if (len(labels) < 2
            or sum(any(NUMERIC.search(value) for value in row) for row in body) < 2
            or len(missing) > 2 * sum(bool(value) for row in panel["grid"] for value in row)):
        return None
    for r, c, rows, cols, box in shape[2]:
        if tuple(box) in missing:
            existing = next((cell for cell in panel["cells"] if (cell["r"], cell["c"]) == (r, c)), None)
            if existing is None:
                existing = dict(r=r, c=c, row_span=rows, col_span=cols, text="", is_header=r < headers)
                panel["cells"].append(existing)
            existing["ocr_unreadable"] = True
    dim_x, dim_y = (height, width) if turn % 2 else (width, height)
    def back(box):
        l, t, r, b = rotate_bbox(box, dim_x, dim_y, 90 * turn)
        return [l + left, t + top, r + left, b + top]

    panel["bbox"] = back(panel["bbox"])
    for row in panel["cell_boxes"]:
        for index, box in enumerate(row):
            if box:
                row[index] = back(box)
    panel["cells"].sort(key=lambda cell: (cell["r"], cell["c"]))
    return panel


def read_page(page, models=DEFAULT_MODELS, *, allow_broken=False, allow_sparse=False):
    import cv2
    import numpy as np
    import pymupdf

    command = shutil.which("tesseract")
    if not command:
        return []
    zoom = min(3.5, 2600 / max(page.rect.width, page.rect.height))
    bitmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(bitmap.samples, np.uint8).reshape(bitmap.height, bitmap.width)
    if min(gray.shape) < 64:
        return []
    lines, shapes = scan_rulings(gray)
    restore = None
    if not shapes and (correction := deskew(gray)) is not None:
        gray, restore = correction
        lines, shapes = scan_rulings(gray)
    recovered = allow_broken and not shapes
    if recovered:
        lines, shapes = broken_rulings(gray)
    def physical(box):
        if restore is None:
            return [coordinate / zoom for coordinate in box]
        l, t, r, b = box
        corners = np.array([[l, t, 1], [r, t, 1], [r, b, 1], [l, b, 1]]) @ restore.T
        left, top = corners.min(axis=0) / zoom
        right, bottom = corners.max(axis=0) / zoom
        return [float(left), float(top), float(right), float(bottom)]

    clean = np.where(cv2.dilate(lines, np.ones((3, 3), np.uint8)), 255, gray).astype(np.uint8)
    results = []
    for shape in shapes:
        panel = read_panel(clean, gray, shape, command, models, upscale=recovered)
        if panel:
            panel["bbox"] = physical(panel["bbox"])
            panel["cell_boxes"] = [[(physical(box) if box else None) for box in row]
                                  for row in panel["cell_boxes"]]
            if recovered:
                panel["structure"] = "locally_supported_rulings"
            results.append(panel)
    if recovered:
        results = [panel for panel in results
                   if not any(other is not panel and intersects(panel["bbox"], other["bbox"]) for other in results)]
    if not results and allow_sparse:
        from .scan_bands import read_page as read_sparse

        return read_sparse(page, command, models)
    return results



def repair_document(pdf, pages, chunks, tables, doc_id, max_chars, *, models=DEFAULT_MODELS, stacked_pages=(),
                    allow_broken=False, allow_sparse=False):
    import pymupdf
    from ..ingestion.tables import table_row_texts

    numbers = [p["page"] for p in pages if p["mode"] == "ocr" and p["page"] not in stacked_pages]
    if not numbers:
        return chunks, tables, []
    table_boxes, findings = defaultdict(list), []
    for i, table in enumerate(tables):
        for region in table["regions"]:
            table_boxes[region["page"]].append((i, region["bbox"]))
    with pymupdf.open(pdf) as source:
        for number in numbers:
            try:
                panels = read_page(source[number - 1], models, allow_broken=allow_broken, allow_sparse=allow_sparse)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                findings.append({"page": number, "rule": RULE, "reason": "scan_grid_read_failed"})
                continue
            for index, panel in enumerate(panels, 1):
                logical_id = f"{doc_id}#{RULE}-p{number}-{index}"
                owners = [i for i, box in table_boxes[number] if intersects(box, panel["bbox"])]
                if len(owners) > 1:
                    continue
                caption, previous, positions = "", None, []
                template = dict(doc_id=doc_id, section=None, section_path=[], quality="review", ocr=True)
                if owners:
                    previous, = owners
                    original = tables[previous]
                    logical_id = original["table_id"]
                    positions = [i for i, c in enumerate(chunks) if c["table_id"] == logical_id]
                    if not positions or positions != list(range(positions[0], positions[-1] + 1)):
                        continue
                    comparison_panel = panel
                    if footprint := panel.get("footprint_bbox"):
                        old_box = original["regions"][0]["bbox"]
                        if bbox_iou(footprint, old_box) > bbox_iou(panel["bbox"], old_box):
                            comparison_panel = dict(panel, bbox=footprint)
                    context = conservative_replacement(comparison_panel, original, [chunks[i] for i in positions], number, ocr=True)
                    if context is None:
                        continue
                    template, caption = context
                    template = dict(template, quality="review")
                table = grid_table_record(logical_id, doc_id, f"ocr:{RULE}:p{number}:{index}", number,
                                          panel["bbox"], panel["grid"])
                table.update(cells=panel["cells"], header_rows=panel["header_rows"],
                             rows_text=table_row_texts(panel["grid"], panel["header_rows"], table["num_cols"]))
                rendered = table_chunks(table, template, max_chars, caption)
                if previous is None:
                    offset = next((i for i, chunk in enumerate(chunks) if min(chunk["pages"]) > number), len(chunks))
                    chunks[offset:offset] = rendered
                    tables.append(table)
                else:
                    chunks[positions[0]:positions[-1] + 1] = rendered
                    tables[previous] = table
                findings.append({"page": number, "rule": RULE, "action": "recovered" if previous is None else "repartitioned", "bbox": panel["bbox"],
                                 "unreadable_cells": sum(bool(cell.get("ocr_unreadable")) for cell in panel["cells"])})
                if panel.get("structure"):
                    findings[-1]["structure"] = panel["structure"]
    return chunks, tables, findings
