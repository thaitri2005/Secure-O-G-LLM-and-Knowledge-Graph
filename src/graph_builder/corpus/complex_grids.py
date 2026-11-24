"""Read ruled text tables with physical spans or a table-local quarter turn."""
from __future__ import annotations

from collections import Counter
import math

from .column_alignment import comparison
from .numeric_cells import read_words
from .orientation import quarter, rotate_bbox
from .ruled_geometry import cell_slots, materialize_panel
from .text_layer import source_page

RULE = "complex_grid"


def line_directions(page):
    import pymupdf

    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    return [(line["bbox"], quarter(math.degrees(math.atan2(line["dir"][1], line["dir"][0])), 3),
             sum(len(span["text"].strip()) for span in line["spans"]))
            for block in page.get_text("dict", flags=flags)["blocks"] for line in block.get("lines", ())]


def table_angle(box, lines):
    counts = Counter()
    for (left, top, right, bottom), angle, weight in lines:
        x, y = (left + right) / 2, (top + bottom) / 2
        if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
            counts[angle] += weight
    if counts:
        angle, weight = counts.most_common(1)[0]
        if angle is not None and weight >= .95 * counts.total():
            return angle
    return None


def word_data(page):
    return [(word[4], word[:4]) for word in page.get_text("words", sort=True)]


def independent_words(pdf, number):
    return [(word["text"], word["bbox"])
            for word in source_page(pdf, number, displayed_origin=True, rotation_override=0)["words"]]


def read_rectangles(table, words, independent):
    shape = cell_slots(table.cells)
    if shape is None:
        return None

    def read_cell(box):
        value = read_words(words, box)
        other = read_words(independent, box)
        return value if comparison(value) == comparison(other) else None

    return materialize_panel(shape, table.bbox, read_cell)


def transform_panel(panel, box_in_source):
    panel["bbox"] = box_in_source(panel["bbox"])
    panel["cell_boxes"] = [[box_in_source(box) if box else None for box in row] for row in panel["cell_boxes"]]
    return panel


def local_panel(page, table, angle):
    import pymupdf

    clip = (pymupdf.Rect(table.bbox) + (-1, -1, 1, 1)) & page.rect
    # The vector copy preserves the printed glyphs and rulings for both PDF readers.
    width, height = (clip.height, clip.width) if angle % 180 else (clip.width, clip.height)
    with pymupdf.open() as upright:
        view = upright.new_page(width=width, height=height)
        view.show_pdf_page(view.rect, page.parent, page.number, clip=clip, rotate=angle)
        candidates = view.find_tables(strategy="lines_strict", paths=view.get_drawings()).tables
        if len(candidates) != 1:
            return None
        panel = read_rectangles(candidates[0], word_data(view), independent_words(upright.tobytes(), 1))
    if panel is None:
        return None

    def back(box):
        l, t, r, b = rotate_bbox(box, width, height, angle)
        return [l + clip.x0, t + clip.y0, r + clip.x0, b + clip.y0]

    result = transform_panel(panel, back)
    return result if all(abs(a - b) <= 2 for a, b in zip(result["bbox"], table.bbox, strict=True)) else None


def matching_boundary(a, b):
    return all(abs(x - y) <= 2 for x, y in zip(a, b, strict=True))


def borderless_panels(page, directions, rotation, geometry_gate):
    from .aligned_grids import read_panels
    import pymupdf

    angle = table_angle(page.rect, directions)
    if angle is None or not (angle or rotation):
        return
    raw_width, raw_height = page.rect.width, page.rect.height
    width, height = (raw_height, raw_width) if angle % 180 else (raw_width, raw_height)

    def displayed(box):
        raw = rotate_bbox(box, width, height, angle)
        return rotate_bbox(raw, raw_width, raw_height, rotation)

    with pymupdf.open() as upright:
        view = upright.new_page(width=width, height=height)
        view.show_pdf_page(view.rect, page.parent, page.number, rotate=angle)
        words = word_data(view)
        for panel in read_panels(words, independent_words(upright.tobytes(), 1)):
            panel = transform_panel(panel, displayed)
            if (pymupdf.Rect(0, 0, raw_height if rotation % 180 else raw_width,
                             raw_width if rotation % 180 else raw_height).contains(pymupdf.Rect(panel["bbox"]))
                    and (geometry_gate is None or geometry_gate(panel["bbox"], aligned=True))):
                yield None, dict(panel, rule=RULE, rotation=(angle, rotation), structure="aligned_numeric_columns")


def panels(pdf, page, allow_complex, geometry_gate=None, *, allow_borderless=False):
    """Yield ordinary Table objects and independently read complex tables in the displayed source frame."""
    rotation = page.rotation
    if rotation and not allow_complex:
        return
    if rotation:
        page.set_rotation(0)
    try:
        drawings = page.get_drawings()
        tables = page.find_tables(strategy="lines_strict" if rotation else "lines", paths=drawings).tables if drawings else ()
        directions = line_directions(page) if allow_complex and (tables or allow_borderless) else ()
        angled = any(angle != 0 for _, angle, _ in directions)
        strict_tables = tables if rotation else None
        words = independent = None
        for table in tables:
            angle = table_angle(table.bbox, directions) if angled else 0
            if angle is None:
                continue
            merged = allow_complex and any(None in row.cells for row in table.rows)
            if not (rotation or angle or merged):
                yield table, None
                continue
            if geometry_gate and not geometry_gate(rotate_bbox(list(table.bbox), page.rect.width, page.rect.height, rotation)):
                continue
            if not rotation:
                if strict_tables is None:
                    strict_tables = page.find_tables(strategy="lines_strict", paths=drawings).tables
                matches = [candidate for candidate in strict_tables if matching_boundary(candidate.bbox, table.bbox)]
                if len(matches) != 1:
                    continue
                table, = matches
            if angle:
                panel = local_panel(page, table, angle)
            else:
                if words is None:
                    words, independent = word_data(page), independent_words(pdf, page.number + 1)
                panel = read_rectangles(table, words, independent)
            if panel:
                if rotation:
                    raw_width, raw_height = page.rect.width, page.rect.height
                    panel = transform_panel(panel, lambda box: rotate_bbox(box, raw_width, raw_height, rotation))
                yield table, dict(panel, rule=RULE, rotation=(angle, rotation))
        if allow_borderless and not tables:
            yield from borderless_panels(page, directions, rotation, geometry_gate)
    finally:
        if rotation:
            page.set_rotation(rotation)
