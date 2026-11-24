"""Read the ruled mud-properties panel independently of adjacent drilling-report panels."""
from __future__ import annotations

import re

from .casing_tables import RULE_TOLERANCE, assign_cell_words, read_cells, vertical_rules
from .ops_tables import chunk_template, grid_table_record, table_chunks
from .report_context import pdf_page_texts
from .table_recognition import em, page_lines
from .text_layer import source_page, union

RULE = "mud_properties"
TITLE = re.compile(r"\bmud\s+properties\b", re.I)
LABEL = re.compile(
    r"(?:depth|density|mud weight|ecd|temp(?:erature)?|visc(?:osity)?|pv\s*/\s*yp|gels|api filt\.?|"
    r"sand|kcl|ph|lgs|chlorides?|lcm|%\s*solids|%\s*water|hardness|pf\s*/\s*mf|cl\s*-|ca\s*\+\+|fluid loss)"
    r"(?:\s*\([^()]+\)|\s*%\s*/?\s*vol)?", re.I,
)
NUMBER = r"[<>*~]?[+-]?(?:\d+(?:[,.]\d+)*|\.\d+)"
VALUE = re.compile(fr"{NUMBER}(?:\s*[/–-]\s*{NUMBER})?(?:\s*(?:ppg|sg|psi|sec|s|cc|ml|ppm|m|°\s*[cf]|%))?", re.I)
QUALITATIVE = {"", "-", "–", "—", "n/a", "tr", "trace", "traces"}


def panel_at(layer, lines, title):
    """Use the panel's own horizontal bands and stable column rulings to assign visible words."""
    height = em(title)
    l, t, r, b = union(title)
    horizontals = sorted(((line[1] + line[3]) / 2, line[0], line[2]) for line in layer["rulings"]
                         if line[3] - line[1] <= RULE_TOLERANCE and line[0] <= l < r <= line[2])
    start = next((line for line in horizontals if b - height / 4 <= line[0] <= b + height), None)
    if start is None:
        return None
    top, left, right = start
    levels = [top]
    for y, x0, x1 in horizontals:
        if y - levels[-1] > RULE_TOLERANCE and abs(x0 - left) <= RULE_TOLERANCE and abs(x1 - right) <= RULE_TOLERANCE:
            levels.append(y)

    edges, body, boxes, labels = None, [], [], set()
    bottom = top
    populated, unreadable_labels = 0, 0
    for y0, y1 in zip(levels, levels[1:]):
        if y1 - y0 > 3 * height:
            break
        band = [{"words": [word for word in line["words"] if left <= centre_x(word) <= right]}
                for line in lines if y0 <= (line["top"] + line["bottom"]) / 2 < y1]
        band_edges = vertical_rules(layer, y0, y1, left, right)
        if body and (len(band_edges) != len(edges) or any(abs(x - other) > RULE_TOLERANCE for x, other in zip(edges, band_edges))):
            break
        if len(band_edges) not in (3, 4):
            break
        cells = assign_cell_words(band, band_edges)
        if cells is None:
            return None
        label, *values = read_cells(cells)
        key = " ".join(label.casefold().split())
        if y0 == top and key == "mud type":
            continue
        if body and any(char in key for char in "\ufffd\ufffe\uffff"):
            unreadable_labels += 1
            if unreadable_labels > 1:
                return None
            continue
        if not LABEL.fullmatch(key):
            break
        if key in labels or any(value.casefold() not in QUALITATIVE and not VALUE.fullmatch(value) for value in values):
            return None
        edges = band_edges
        labels.add(key)
        populated += any(VALUE.fullmatch(value) for value in values)
        body.append([label, *values])
        boxes.append([union(cell) for cell in cells])
        bottom = y1

    if len(body) < 4 or populated < 3:
        return None
    header = [" ".join(word["text"] for word in title)] + [""] * (len(edges) - 2)
    header_boxes = [union(title)] + [None] * (len(edges) - 2)
    return {"bbox": [left, t, right, bottom], "grid": [header, *body], "cell_boxes": [header_boxes, *boxes]}


def centre_x(word):
    box = word["bbox"]
    return (box[0] + box[2]) / 2


def read_page(layer):
    """A page needs one title with an independently readable panel underneath it."""
    if layer["rotation"]:
        return None
    lines = page_lines(layer)
    titles = [[a, b] for line in lines for a, b in zip(line["words"], line["words"][1:])
              if (a["text"].casefold(), b["text"].casefold()) == ("mud", "properties")
              and b["bbox"][0] - a["bbox"][2] <= em([a, b])]
    return panel_at(layer, lines, titles[0]) if len(titles) == 1 else None


def repair_document(pdf, pages, chunks, tables, doc_id, max_chars, *, stacked_pages=(), findings=None, source_texts=None):
    """Publish a standalone ruled panel and keep neighboring native evidence available."""
    chunks, tables = list(chunks), list(tables)
    findings = findings if findings is not None else []
    if not chunks:
        return chunks, tables
    numbers = [page["page"] for page in pages if page["mode"] == "text" and page["page"] not in stacked_pages]
    for number, text in pdf_page_texts(pdf, numbers, source_texts=source_texts).items():
        if not TITLE.search(text):
            continue
        try:
            panel = read_page(source_page(pdf, number, displayed_origin=True))
        except (OSError, RuntimeError, ValueError) as error:
            findings.append({"page": number, "reason": f"text_layer_{type(error).__name__}"})
            continue
        if panel is None:
            findings.append({"page": number, "reason": "unproven_mud_grid"})
            continue
        logical_id = f"{doc_id}#mud-properties-p{number}"
        table = grid_table_record(logical_id, doc_id, f"textlayer:{RULE}:p{number}", number, panel["bbox"], panel["grid"])
        index = next((i for i, chunk in enumerate(chunks) if min(chunk["pages"]) > number), len(chunks))
        template = dict(chunk_template(chunks[max(0, index - 1)]), section=None, section_path=[], ocr=False, quality="ok")
        chunks[index:index] = table_chunks(table, template, max_chars)
        tables.append(table)
    return chunks, tables
