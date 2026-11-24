"""Use rendered ruling ink to locate cells on a PDF that already has searchable text."""
from collections import Counter
from itertools import pairwise
from statistics import median

from .aligned_grids import QUANTITY, lines
from .column_alignment import comparison
from .numeric_cells import contains, words_inside
from .ruled_geometry import cell_slots, materialize_panel


def has_raster_rules_hint(page):
    """Identify repeated image paint operations or a page graphic with room for a grid."""
    tiles = Counter()
    for kind, box in page.get_bboxlog():
        if kind != "fill-image":
            continue
        width, height = box[2] - box[0], box[3] - box[1]
        if width >= .30 * page.rect.width and height >= .06 * page.rect.height:
            return True
        if max(width, height) <= .025 * min(page.rect.width, page.rect.height):
            tiles[tuple(round(value, 1) for value in box)] += 1
    return any(count >= 8 for count in tiles.values())


def covers_table_width(horizontal, first, last, ordinate, slack):
    """Reject islands of cells whose top ruling visibly continues into neighbouring columns."""
    import numpy as np

    from .scan_bands import ink_runs

    ink = np.any(horizontal[max(0, ordinate - slack):ordinate + slack + 1], axis=0)
    runs = ink_runs(ink, max_gap=slack)
    covers = [(left, right) for left, right in runs
              if min(right, last) - max(left, first) >= .9 * (last - first)]
    return any(abs(left - first) <= slack and abs(right - last) <= slack for left, right in covers)


def good_header(panel, words, line_height):
    labels = [label for label in panel["grid"][0] if label]
    if (len(labels) < max(2, (len(panel["grid"][0]) + 1) // 2)
            or len(set(map(str.casefold, labels))) != len(labels)
            or any(not any(ch.isalpha() for ch in label) or len(label.split()) > 8 for label in labels)):
        return False
    for box in panel["cell_boxes"][0]:
        for _, row in lines(words_inside(words, box), line_height):
            if any(right[0] - left[2] > 3 * line_height for (_, left), (_, right) in pairwise(row)):
                return False
    return True


def panels(pdf, page, could_use):
    from .complex_grids import independent_words, word_data

    if page.rotation or not has_raster_rules_hint(page):
        return
    try:
        import numpy as np
        from .scan_grids import broken_rulings, ruler_masks
    except ImportError:
        return
    import pymupdf

    from .scan_bands import ink_runs

    zoom = min(3.0, 2800 / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, np.uint8).reshape((pix.height, pix.width))
    try:
        masks = ruler_masks(gray)
        _, shapes = broken_rulings(gray, masks=masks)
    except ImportError:
        return
    if not shapes:
        return
    words = word_data(page)
    if not words:
        return
    independent = independent_words(pdf, page.number + 1)
    line_height = median(box[3] - box[1] for _, box in words)
    slack = max(2, round(3 * zoom))

    def read_cell(box):
        def value(reader):
            hits = words_inside(reader, box)
            if any(not contains(box, word_box) for _, word_box in hits):
                return None
            return " ".join(text for text, _ in hits)

        first, second = value(words), value(independent)
        if first is not None and second is not None and comparison(first) == comparison(second):
            return first
        return None

    for rows, cols, owners in shapes:
        if len(owners) != rows * cols:
            continue
        left = round(min(box[0] for *_, box in owners))
        right = round(max(box[2] for *_, box in owners))
        top = round(min(box[1] for *_, box in owners))
        bottom = round(max(box[3] for *_, box in owners))
        horizontal = masks[0]
        if not covers_table_width(horizontal, left, right, top, slack):
            continue

        body_boxes = [[coordinate / zoom for coordinate in box] for *_, box in owners]
        search_top = max(0, top - round(2.5 * line_height * zoom))
        # Some exports print the column headings above the first ruled body row.
        ink = horizontal[search_top:max(search_top, top - slack // 2), left:right]
        edges = ink_runs(np.count_nonzero(ink, axis=1) >= .85 * (right - left))
        header_boxes = []
        if edges:
            header_top = (search_top + edges[-1][1]) / zoom
            header_boxes = [[x0, header_top, x1, y0] for x0, y0, x1, _ in body_boxes if abs(y0 - top / zoom) < .01]

        for boxes in (body_boxes, header_boxes + body_boxes) if header_boxes else (body_boxes,):
            bbox = [left / zoom, min(box[1] for box in boxes), right / zoom, bottom / zoom]
            if not could_use(bbox):
                continue
            shape = cell_slots(boxes)
            panel = materialize_panel(shape, bbox, read_cell) if shape else None
            if (not panel or not good_header(panel, words, line_height)
                    or not any(QUANTITY.fullmatch(value) for row in panel["grid"][1:] for value in row)):
                continue
            used_rows = [i for i, row in enumerate(panel["grid"]) if any(row)]
            limit = used_rows[-1] + 1
            if limit < 3 or len(used_rows) != limit:
                continue
            panel["grid"] = panel["grid"][:limit]
            panel["cells"] = [cell for cell in panel["cells"] if cell["r"] < limit]
            panel["cell_boxes"] = panel["cell_boxes"][:limit]
            panel["bbox"][3] = max(box[3] for box in panel["cell_boxes"][-1])
            yield dict(panel, structure="rendered_rulings", rotation=(0, 0))
            break
