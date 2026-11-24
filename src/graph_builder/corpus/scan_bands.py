"""Recover sparse scan tables from recurring horizontal rules and visible column gaps."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median

from ..ingestion.scoring import bbox_iou
from .aligned_grids import QUANTITY
from .column_alignment import comparison
from .numeric_cells import compact


@dataclass(frozen=True)
class Bands:
    edges: tuple[int, ...]
    lanes: tuple[tuple[int, int], ...]


def ink_runs(mask, max_gap=0):
    """Return inclusive-exclusive intervals of true pixels, optionally bridging tiny gaps."""
    import numpy as np

    hits = np.flatnonzero(mask)
    if not hits.size:
        return []
    groups = np.split(hits, np.flatnonzero(np.diff(hits) > max_gap + 1) + 1)
    return [(int(group[0]), int(group[-1]) + 1) for group in groups]


def periodic_bands(horizontal):
    """Propose row bands only when several adjacent printed rules repeat the same geometry."""
    import numpy as np

    height, width = horizontal.shape
    # Short segments inside each printed cell can collectively form a row ruling.
    rows = ink_runs(np.count_nonzero(horizontal, axis=1) >= .16 * width, max_gap=3)
    centres = [(start + stop) // 2 for start, stop in rows if 1 <= stop - start <= max(8, .012 * width)]
    for index in range(len(centres) - 3):
        edges = centres[index:index + 4]
        spacing = median(b - a for a, b in zip(edges, edges[1:]))
        if not .009 * width <= spacing <= .07 * width:
            continue
        if any(not .70 * spacing <= b - a <= 1.30 * spacing for a, b in zip(edges, edges[1:])):
            continue
        end = index + 4
        while end < len(centres) and .70 * spacing <= centres[end] - edges[-1] <= 1.30 * spacing:
            edges.append(centres[end])
            end += 1
        if index and .70 * spacing <= edges[0] - centres[index - 1] <= 1.30 * spacing:
            continue
        slack = max(2, round(spacing * .16))
        readings = [np.any(horizontal[max(0, y - slack):min(height, y + slack + 1)], axis=0) for y in edges]
        coverage = np.count_nonzero(readings, axis=0)
        lanes = [(l, r) for l, r in ink_runs(coverage >= .65 * len(edges), max_gap=round(.15 * spacing))
                 if r - l >= 1.1 * spacing]
        if not 5 <= len(lanes) <= 20 or lanes[-1][1] - lanes[0][0] < .40 * width:
            continue
        cuts = [(left[1] + right[0]) // 2 for left, right in zip(lanes, lanes[1:])]
        boundaries = [lanes[0][0], *cuts, lanes[-1][1]]
        if min(b - a for a, b in zip(boundaries, boundaries[1:])) < spacing:
            continue
        yield Bands(tuple(edges), tuple(zip(boundaries, boundaries[1:])))


def glyph_image(image, *, threshold, edge_rulings):
    """Isolate the principal print line. Retain attached decimal points and minus signs."""
    import cv2
    import numpy as np

    height, width = image.shape
    if min(height, width) < 10:
        return None
    if threshold == "otsu":
        _, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    else:
        binary = cv2.adaptiveThreshold(image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 15, 10)
    if edge_rulings:
        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((1, max(10, width // 3)), np.uint8))
        vertical_ink = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((max(3, height // 4), 1), np.uint8))
        binary = cv2.bitwise_or(cv2.subtract(binary, horizontal), vertical_ink)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    large = [i for i, (_, _, w, h, area) in enumerate(stats[1:], 1)
             if .24 * height <= h <= height and w <= .45 * width and area >= .13 * h * h]
    if not large:
        return None
    boxes = stats[large]
    if boxes[:, 1].max() - boxes[:, 1].min() > .35 * height:
        return None
    left = int(boxes[:, 0].min())
    right = int((boxes[:, 0] + boxes[:, 2]).max())
    top = int(boxes[:, 1].min())
    bottom = int((boxes[:, 1] + boxes[:, 3]).max())
    size = float(median(boxes[:, 3]))
    kept = set(large)
    for i, (x, y, w, h, area) in enumerate(stats[1:], 1):
        # Small punctuation belongs to the line when it is in or immediately beside its ink bounds.
        if (area >= 2 and left - .55 * size <= x <= right + .2 * size
                and top - .2 * size <= y < bottom + .15 * size and w <= .7 * size and h <= .55 * size):
            kept.add(i)
    active = np.isin(labels, list(kept))
    rows, cols = np.where(active)
    text = np.where(active, 0, 255).astype(np.uint8)
    return text[rows.min():rows.max() + 1, cols.min():cols.max() + 1]


def text_canvas(image):
    import cv2

    image = cv2.resize(image, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(image, 14, 14, 14, 14, cv2.BORDER_CONSTANT, value=255)


def read_text(rapid, command, cleaned, source):
    import cv2

    from .scan_fields import tesseract_line
    from .scan_grids import exact_value

    def textual(value):
        return (value and "|" not in value and any(ch.isalpha() for ch in value)
                and all(value.count(left) == value.count(right) for left, right in ("()", "[]")))

    direct = exact_value(rapid, command, cleaned, source, alternate=True)
    if textual(direct):
        return direct
    # Eliminate background and bring the dominant print line to a common size.
    ink = glyph_image(source, threshold="adaptive", edge_rulings=True)
    if ink is None:
        return None
    canvas = text_canvas(ink)
    output = rapid(cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR))
    if len(output.txts or ()) != 1 or output.scores[0] < .88:
        return None
    value = compact(output.txts[0])
    if textual(value) and any(comparison(value) == comparison(tesseract_line(command, canvas, mode=mode))
                              for mode in (7, 8)):
        return value
    return None


def quantity_proposals(rapid, cleaned, source):
    """A cheap first pass rules out prose, blank bands, and conflicting candidate values."""
    import cv2

    readings = {}
    for ink in (glyph_image(source, threshold="otsu", edge_rulings=True),
                glyph_image(source, threshold="adaptive", edge_rulings=True),
                glyph_image(cleaned, threshold="otsu", edge_rulings=False)):
        if ink is None:
            continue
        result = rapid(cv2.cvtColor(text_canvas(ink), cv2.COLOR_GRAY2BGR))
        if result.txts and len(result.txts) == 1 and result.scores[0] >= .88:
            value = compact(result.txts[0])
            if QUANTITY.fullmatch(value):
                readings[comparison(value)] = value
    # Whole-slot recognition can support a decimal whose ink touches a rule or breaks into fragments.
    if not readings:
        result = rapid(cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR))
        if result.txts and len(result.txts) == 1 and result.scores[0] >= .88:
            value = compact(result.txts[0])
            if QUANTITY.fullmatch(value):
                readings[comparison(value)] = value
    return next(iter(readings.values())) if len(readings) == 1 else None


def corroborated_quantity(rapid, command, proposal, cleaned, source, located=()):
    """Require a compatible token from two readers using independently prepared crops."""
    from .scan_fields import tesseract_line
    from .scan_grids import exact_value

    if not proposal:
        return None
    direct = exact_value(rapid, command, cleaned, source, alternate=True)
    if direct and QUANTITY.fullmatch(direct):
        return direct if comparison(proposal) == comparison(direct) else None
    expected = comparison(proposal)
    word_values = {comparison(word) for word in located if QUANTITY.fullmatch(word)}
    if word_values == {expected}:
        return proposal
    observed = Counter()
    for ink in (glyph_image(source, threshold="adaptive", edge_rulings=True),
                glyph_image(source, threshold="otsu", edge_rulings=True),
                glyph_image(cleaned, threshold="otsu", edge_rulings=False)):
        if ink is not None:
            canvas = text_canvas(ink)
            first = compact(tesseract_line(command, canvas))
            if comparison(first) == expected:
                return proposal
            alternate = compact(tesseract_line(command, canvas, mode=8))
            if QUANTITY.fullmatch(alternate):
                observed[comparison(alternate)] += 1
    return proposal if observed[expected] >= 2 and len(observed) == 1 else None


def visible_slots(clean, lanes, top, bottom):
    """Skip blank ruling bands before invoking either recognizer."""
    import numpy as np

    height = bottom - top
    allowed = []
    for left, right in lanes:
        area = clean[top + 2:bottom - 2, left + 2:right - 2]
        groups = ink_runs(np.count_nonzero(area < 150, axis=1) >= 2, max_gap=1)
        allowed.append(any(end - start >= max(4, .22 * height) for start, end in groups))
    return allowed


def located_words(command, source, box):
    from .scan_grids import tess_words

    left, top, right, bottom = box
    words = tess_words(command, text_canvas(source[top:bottom, left:right]))
    return [(word, [offset + (value - 14) / 3 for offset, value in zip((left, top, left, top), region, strict=True)])
            for word, region in words]


def refine_lanes(lanes, words):
    """A proposed gutter cannot run through an independently located printed word."""
    left, right = lanes[0][0], lanes[-1][1]
    crossing = [(box[0], box[2])
                for word, box in words if sum(ch.isalpha() for ch in word) >= 3]
    cuts = [a for a, _ in lanes[1:] if not any(lo + 4 <= a <= hi - 4 for lo, hi in crossing)]
    return tuple(zip((left, *cuts), (*cuts, right)))


def read_band(rapid, command, gray, clean, bands, row, restore):
    top, bottom = bands.edges[row:row + 2]
    spacing = round(median(b - a for a, b in zip(bands.edges, bands.edges[1:])))
    start = max(0, top - 2 * spacing)
    upper = max(start + 1, top - spacing)

    def crops(left, right, start, end, inset=2):
        return clean[start:end, left + inset:right - inset], gray[start:end, left + inset:right - inset]

    def quantity_slots(lanes):
        available = visible_slots(clean, lanes, top, bottom)
        required = max(4, round(.50 * (len(available) - 1)))
        areas = [crops(left, right, top, bottom) for left, right in lanes[1:]]
        if sum(available[1:]) < required:
            return available, required, areas, []
        return available, required, areas, [quantity_proposals(rapid, *area) if ink else None
                                            for area, ink in zip(areas, available[1:], strict=True)]

    available, required, areas, tentative = quantity_slots(bands.lanes)
    if sum(value is not None for value in tentative) < max(4, required - 1):
        return None
    words = located_words(command, gray, [bands.lanes[0][0], start, bands.lanes[-1][1], bottom])
    lanes = refine_lanes(bands.lanes, words)
    if lanes != bands.lanes:
        available, required, areas, tentative = quantity_slots(lanes)
    if sum(value is not None for value in tentative) < required:
        return None

    measurements = []
    for value, area, (left, right) in zip(tentative, areas, lanes[1:], strict=True):
        located = [word for word, (x0, y0, x1, y1) in words
                   if left + 2 <= x0 < x1 <= right - 2 and top + 1 <= y0 < y1 <= bottom - 1]
        measurements.append(corroborated_quantity(rapid, command, value, *area, located=located))
    if sum(value is not None for value in measurements) < required:
        return None
    # Headers may wrap over two printed bands. Read the physical lines individually.
    body_left, body_right = lanes[0]

    def heading(left, right, lo, hi):
        return (read_text(rapid, command, *crops(left, right, lo, hi))
                or read_text(rapid, command, *crops(left, right, lo, hi, inset=0)))

    header_bands = [(lo, hi, visible_slots(clean, lanes, lo, hi)) for lo, hi in ((start, upper), (upper, top)) if hi - lo >= 8]
    header_lines = [[heading(left, right, lo, hi) if has_ink else ""
                     for (left, right), has_ink in zip(lanes, visible, strict=True)]
                    for lo, hi, visible in header_bands]
    label = read_text(rapid, command, *crops(body_left, body_right, top, bottom))
    label_box = [body_left, top, body_right, bottom]
    if not label:
        markers = [(i, lines[0]) for i, lines in enumerate(header_lines)
                   if lines[0] and lines[0].endswith(":") and len(lines[0].split()) <= 4]
        if len(markers) == 1:
            index, label = markers[0]
            lo, hi, _ = header_bands[index]
            label_box = [body_left, lo, body_right, hi]
            header_lines[index][0] = ""
    header_columns = list(zip(*header_lines, strict=True))
    # A partly legible heading can establish table structure without certifying an incomplete cell.
    if sum(any(pieces) for pieces in header_columns) < (1 if label else 2):
        return None
    # Exclude a verified empty row above the headings from the source extent.
    header_top = next((lo for lo, _, visible in header_bands if any(visible)), start)
    header_review = [any(piece is None for piece in pieces) for pieces in header_columns]
    headers = ["" if unreadable else " ".join(filter(None, pieces))
               for pieces, unreadable in zip(header_columns, header_review, strict=True)]

    first, last = lanes[0][0], lanes[-1][1]
    footprint_bottom = bottom
    for edge in bands.edges[row + 2:]:
        if any(visible_slots(clean, lanes, footprint_bottom, edge)):
            break
        footprint_bottom = edge
    header_boxes = [[left, header_top, right, top] for left, right in lanes]
    body_boxes = [label_box, *[[left, top, right, bottom] for left, right in lanes[1:]]]
    grid = [headers, [label or "", *(value or "" for value in measurements)]]
    cells = []
    for r, values in enumerate(grid):
        for c, value in enumerate(values):
            record = {"r": r, "c": c, "row_span": 1, "col_span": 1, "text": value, "is_header": r == 0}
            if not value and (header_review[c] if r == 0 else available[c]):
                record["ocr_unreadable"] = True
            cells.append(record)
    return {"bbox": restore([first, header_top, last, bottom]), "body_bbox": restore([first, top, last, bottom]),
            "footprint_bbox": restore([first, header_top, last, footprint_bottom]),
            "grid": grid, "cells": cells, "header_rows": 1,
            "cell_boxes": [[restore(box) for box in row] for row in (header_boxes, body_boxes)],
            "structure": "horizontal_ruling_bands"}


def panel_rank(panel):
    return (bool(panel["grid"][1][0]), sum(bool(value) for value in panel["grid"][1][1:]),
            sum(bool(value) for value in panel["grid"][0]), panel["ruling_concentration"])


def agree_in_shared_cells(left, right):
    for a, a_box in zip(left["grid"][1][1:], left["cell_boxes"][1][1:]):
        for b, b_box in zip(right["grid"][1][1:], right["cell_boxes"][1][1:]):
            if a and b and bbox_iou(a_box, b_box) >= .52 and comparison(a) != comparison(b):
                return False
    return True


def read_page(page, command, models):
    """Use a bounded small-angle search when the enclosing grid detector found nothing."""
    import cv2
    import numpy as np
    import pymupdf

    from .scan_fields import rapid_reader
    from .scan_grids import ruler_masks

    zoom = min(300 / 72, 2600 / max(page.rect.width, page.rect.height))
    bitmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    if min(bitmap.width, bitmap.height) < 160:
        return []
    image = np.frombuffer(bitmap.samples, np.uint8).reshape(bitmap.height, bitmap.width)
    proposals = []
    for angle in (0, -.25, .25, -.5, .5, -.75, .75):
        matrix = cv2.getRotationMatrix2D((bitmap.width / 2, bitmap.height / 2), angle, 1)
        inverse = cv2.invertAffineTransform(matrix)
        gray = cv2.warpAffine(image, matrix, (bitmap.width, bitmap.height), borderValue=255) if angle else image
        horizontal, _ = ruler_masks(gray)

        def restore(box):
            l, t, r, b = box
            points = np.array([[l, t, 1], [l, b, 1], [r, t, 1], [r, b, 1]]) @ inverse.T / zoom
            low, high = points.min(axis=0), points.max(axis=0)
            return [float(low[0]), float(low[1]), float(high[0]), float(high[1])]

        geometry = list(periodic_bands(horizontal))
        if not geometry:
            continue
        rapid = rapid_reader(models.resolve(), detect=False)
        clean = np.where(horizontal > 0, 255, gray).astype(np.uint8)
        for bands in geometry:
            # A sharper run of printed rules gives a better deskew transform when OCR coverage ties.
            l, r = bands.lanes[0][0], bands.lanes[-1][1]
            projection = np.count_nonzero(horizontal[:, l:r], axis=1)
            spread = max(3, round(median(np.diff(bands.edges)) / 5))
            sharp = sum(projection[max(0, y - 1):y + 2].sum() for y in bands.edges)
            broad = sum(projection[max(0, y - spread):y + spread + 1].sum() for y in bands.edges)
            for row in range(len(bands.edges) - 1):
                panel = read_band(rapid, command, gray, clean, bands, row, restore)
                if panel and pymupdf.Rect(page.rect).contains(pymupdf.Rect(panel["bbox"])):
                    panel["ruling_concentration"] = sharp / max(1, broad)
                    proposals.append(panel)
    pending = sorted(proposals, key=panel_rank, reverse=True)
    retained = []
    while pending:
        winner = pending.pop(0)
        peers = [panel for panel in pending if bbox_iou(winner["body_bbox"], panel["body_bbox"]) >= .45]
        pending = [panel for panel in pending if panel not in peers]
        if all(agree_in_shared_cells(winner, alternate) for alternate in peers):
            retained.append(winner)
    return sorted(retained, key=lambda panel: (panel["bbox"][1], panel["bbox"][0]))
