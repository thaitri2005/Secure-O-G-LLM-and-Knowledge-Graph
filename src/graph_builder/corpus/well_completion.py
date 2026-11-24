"""Recover physically verified label–value pairs from well completion panels."""
from __future__ import annotations

from collections import Counter
import re

from .casing_tables import centre
from .daily_log import matched_text
from .ops_tables import chunk_template, grid_table_record, table_chunks
from .report_context import pdf_page_texts
from .ruled_panels import key, WELL_LABELS, WELL_TITLE
from .table_recognition import page_lines
from .text_layer import source_page, union

RULE = "well_completion"
HINT = re.compile(r"\b(?:(?:general\s+)?well\s+(?:summary|information|data|card|completion\s+report))\b", re.I)
CAPTION = re.compile(r"(?:table [0-9]+ [0-9]+ )?(?:general well data|well summary|well (?:information|data|card))"
                     r"|well completion report of [a-z0-9 ]+")
SECONDARY_FIELDS = re.compile(
    r"(?:well (?:class|no well name|profile|type category)|offset wells|licen[cs]e|location|zone|"
    r"lat(?:itude)?|long(?:itude)?|grid|geodetic datum|ellipsoid|basin|"
    r"(?:gl |rig )?elevations?|driller td(?: .+)?|"
    r"depth ref(?: elev)?|seismic (?:survey|ref)|primary objective|structure|rig release|"
    r"td date(?: .+)?|operation days|country|state district|village mandal tehsil|area structure|"
    r"wbs element|expendable non expendable|hole size|mud (?:type|weight)|offset from released location|"
    r"(?:target|revised target|drilled|logger s) depth(?: if any)?(?: mdkb tvdss)?|formation member at td|"
    r"(?:planned|actual) (?:drift|deviation inc azim))(?:\s+(?:m|ft|ppg))?"
)


def is_caption(text):
    return bool(CAPTION.fullmatch(key(text)) or WELL_TITLE.fullmatch(key(text)))


def is_field(text):
    label = key(text)
    return bool(WELL_LABELS.fullmatch(label) or SECONDARY_FIELDS.fullmatch(label))


def verified_box(text, box, words):
    if not box:
        return None
    left, top, right, bottom = box
    in_box = [word for word in words if left - .5 <= centre(word["bbox"], 0) <= right + .5
              and top - .5 <= centre(word["bbox"], 1) <= bottom + .5]
    if matched_text(3, " ".join(word["text"] for word in in_box), text):
        return union(in_box)
    return None


def panel_at(table, lines, words):
    left, top, right, bottom = table.bbox
    rows = list(zip(table.rows, table.extract(), strict=True))
    if not rows:
        return None
    first = [(" ".join(value.split()), cell) for value, cell in zip(rows[0][1], rows[0][0].cells)
             if value and value.strip()]
    caption, caption_box = "", None
    if first and is_caption(first[0][0]):
        caption = first[0][0]
        caption_box = verified_box(caption, first[0][1], words)
        # A different heading to the right starts an adjacent panel.
        if len(first) > 1 and first[1][1]:
            right = first[1][1][0]
        rows = rows[1:]
    else:
        for line in reversed(lines):
            if not 0 <= top - line["bottom"] <= 6 * max(1, line["bottom"] - line["top"]):
                continue
            segment = [word for word in line["words"] if left <= centre(word["bbox"], 0) <= right]
            title = " ".join(word["text"] for word in segment)
            if is_caption(title):
                caption, caption_box = title, union(segment)
                break
    if not caption_box:
        return None

    pairs = []
    for row, values in rows:
        populated = [(" ".join(value.split()), box) for value, box in zip(values, row.cells)
                     if value and value.strip() and box and left - .6 <= box[0] < right - .6 and box[2] <= right + .6]
        for (label, a), (value, b) in zip(populated, populated[1:]):
            gap = max(4, .75 * min(a[3] - a[1], b[3] - b[1]))
            if not is_field(label) or is_field(value) or not -.6 <= b[0] - a[2] <= gap or abs(a[1] - b[1]) > 2:
                continue
            field, content = verified_box(label, a, words), verified_box(value, b, words)
            if field and content:
                pairs.append(([label, value], [field, content]))
    occurrences = Counter(key(row[0]) for row, _ in pairs)
    pairs = [(row, boxes) for row, boxes in pairs if occurrences[key(row[0])] == 1]
    labels = {key(row[0]) for row, _ in pairs}
    identity = bool(labels & {"well name", "well no well name", "well number"})
    depth_summary = {"target depth mdkb tvdss", "drilled depth mdkb tvdss"} <= labels
    if len(pairs) < 4 or not (identity or (CAPTION.fullmatch(key(caption)) and depth_summary)):
        return None
    return caption, caption_box, pairs


def read_page(path, page, number):
    if page.rotation:
        return []
    layer = source_page(path, number, displayed_origin=True)
    lines = page_lines(layer)
    words = [word for line in lines for word in line["words"]]
    return [panel for table in page.find_tables().tables if table.col_count >= 2
            and (panel := panel_at(table, lines, words)) is not None]


def repair_document(pdf, pages, chunks, tables, doc_id, max_chars, *, stacked_pages=(), source_texts=None):
    findings = []
    if not chunks:
        return chunks, tables, findings
    numbers = [page["page"] for page in pages if page["mode"] == "text" and page["page"] not in stacked_pages]
    try:
        hits = [number for number, text in pdf_page_texts(pdf, numbers, source_texts=source_texts).items() if HINT.search(text)]
        if not hits:
            return chunks, tables, findings
        import pymupdf

        with pymupdf.open(pdf) as source:
            for number in hits:
                try:
                    panels = read_page(pdf, source[number - 1], number)
                except (OSError, RuntimeError, ValueError):
                    panels = []
                if not panels:
                    findings.append({"page": number, "rule": RULE, "reason": "unproven_completion_pairs"})
                for i, (caption, title_box, pairs) in enumerate(panels):
                    grid = [[caption, ""], *(row for row, _ in pairs)]
                    sources = [{"r": 0, "c": 0, "bbox": title_box, "text": caption}]
                    sources.extend({"r": row_index, "c": column, "bbox": box, "text": cell}
                                   for row_index, (row, boxes) in enumerate(pairs, 1)
                                   for column, (cell, box) in enumerate(zip(row, boxes)))
                    bbox = union([item["bbox"] for item in sources])
                    ref = f"textlayer:{RULE}:p{number}:{i}"
                    table = grid_table_record(f"{doc_id}#{RULE}-{number}-{i}", doc_id, ref, number, bbox, grid)
                    table["verified_parts"] = [dict(source_ref=ref, page=number, bbox=bbox, row_start=0,
                                                    row_end=len(grid), header=grid[:1], cell_sources=sources)]
                    offset = next((j for j, chunk in enumerate(chunks) if min(chunk["pages"]) > number), len(chunks))
                    template = dict(chunk_template(chunks[max(0, offset - 1)]), section=None, section_path=[], ocr=False, quality="ok")
                    chunks[offset:offset] = table_chunks(table, template, max_chars)
                    tables.append(table)
    except (ImportError, OSError, RuntimeError, ValueError):
        if numbers:
            findings.append({"page": min(numbers), "rule": RULE, "reason": "completion_source_unavailable"})
    return chunks, tables, findings
