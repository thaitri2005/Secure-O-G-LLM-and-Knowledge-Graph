"""Rebuild ruled Operations Activity Detail continuations from visible PDF cells."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import pairwise
import re

from .casing_tables import RULE_TOLERANCE, assign_cell_words, read_cells, vertical_rules
from .ops_tables import chunk_template, grid_table_record, table_chunks
from .orientation import normalized_rotation, rotate_bbox
from .report_context import pdf_page_texts
from .report_fields import source_report_identity
from .ruled_panels import band_words, independently_readable, key
from .table_recognition import page_lines
from .text_layer import source_page, union
from ..ingestion.scoring import bbox_iou


RULE = "activity_detail"
TITLE = "operations activity detail"
DESCRIPTION = 7
PAGE_NUMBER = re.compile(r"\bpage (\d+) of (\d+)\b", re.I)
CLOCK = re.compile(r"(?:[01]?\d|2[0-3]):[0-5]\d|24:00")
NUMBER = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
DATE = re.compile(r"\d{1,2}-[A-Za-z]{3}-(?:\d{2}|\d{4})")
CODE = re.compile(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*")
HEADERS = (
    {"rpt no", "report no", "report number"}, {"date"}, {"time", "from", "start time"}, {"to", "end time"},
    {"hrs", "hours"}, {"end md", "end md ft", "end md m"}, {"ops code", "activity code"},
    {"activity description", "operations description"}, {"non prod", "non productive"},
)


@dataclass
class PageGrid:
    page: int
    sequence: tuple[int, int]
    header: list[str]
    rows: list[list[str]]
    boxes: list[list[list | None]]
    edges: list[float]
    bbox: list[float]
    identity: dict


def activity_row(row):
    report, date, start, end, elapsed, depth, code, description, mark = row
    return ((not report or report.isdecimal()) and (not date or DATE.fullmatch(date))
            and CLOCK.fullmatch(start) and CLOCK.fullmatch(end) and NUMBER.fullmatch(elapsed)
            and (not depth or NUMBER.fullmatch(depth)) and CODE.fullmatch(code) and bool(description)
            and mark.casefold() in ("", "x", "yes", "no"))


def continuation_row(row, column=DESCRIPTION):
    return bool(row[column]) and all(not text for index, text in enumerate(row) if index != column)


def read_grid(layer, number):
    lines = page_lines(layer)
    counters = [tuple(map(int, match.groups())) for line in lines if line["top"] > layer["height"] * .8
                for match in PAGE_NUMBER.finditer(key(" ".join(w["text"] for w in line["words"])))]
    if len(counters) != 1 or not 1 <= counters[0][0] <= counters[0][1]:
        return None
    bands = sorted(((box[1] + box[3]) / 2, box[0], box[2]) for box in layer["rulings"]
                   if box[3] - box[1] <= RULE_TOLERANCE and box[2] - box[0] >= layer["width"] / 2)
    options = []
    for index, (top, left, right) in enumerate(bands):
        edges = sorted({y for y, x0, x1 in bands[index:] if abs(left - x0) <= RULE_TOLERANCE
                        and abs(right - x1) <= RULE_TOLERANCE})
        if len(edges) < 3:
            continue
        slots = vertical_rules(layer, top, edges[1], left, right)
        if len(slots) != len(HEADERS) + 1:
            continue
        cells = assign_cell_words(band_words(lines, left, right, top, edges[1]), slots)
        header = read_cells(cells) if cells else []
        if not header or any(key(label) not in names for label, names in zip(header, HEADERS)):
            continue
        boxes = [[union(cell) for cell in cells]]
        rows = []
        for upper, lower in pairwise(edges[1:]):
            columns = vertical_rules(layer, upper, lower, left, right)
            if len(columns) != len(slots) or any(abs(a - b) > RULE_TOLERANCE for a, b in zip(columns, slots)):
                break
            cells = assign_cell_words(band_words(lines, left, right, upper, lower), slots)
            row = read_cells(cells) if cells else []
            if not row or not (activity_row(row) or continuation_row(row)):
                break
            rows.append(row)
            boxes.append([union(cell) for cell in cells])
        if rows and len(rows) + 2 == len(edges):
            options.append(PageGrid(number, counters[0], header, rows, boxes, slots, [left, top, right, edges[-1]],
                                    source_report_identity(layer)))
    return options[0] if len(options) == 1 else None


def independent_words(page, angle):
    words = page.get_text("words", sort=angle == 0)
    if not angle:
        return words
    raw = page.rect * page.derotation_matrix
    words = [(*rotate_bbox(list(word[:4]), raw.width, raw.height, angle), *word[4:]) for word in words]
    return sorted(words, key=lambda word: (round(word[1] / 3), word[0]))


def agrees_with_source(panel, words):
    grid = [panel.header, *panel.rows]
    left, top, right, bottom = panel.bbox
    visible = Counter(word[4] for word in words if left <= (word[0] + word[2]) / 2 <= right
                      and top <= (word[1] + word[3]) / 2 <= bottom)
    return (visible == Counter(token for row in grid for cell in row for token in cell.split())
            and independently_readable({"grid": grid, "cell_boxes": panel.boxes}, words))


def compatible(a, b):
    return ([key(label) for label in a.header] == [key(label) for label in b.header]
            and all(abs(x - y) <= RULE_TOLERANCE for x, y in zip(a.edges, b.edges))
            and all(set(a.identity[field]) & set(b.identity[field]) for field in a.identity.keys() & b.identity.keys()))


def assemble(group, doc_id, logical_id, template, max_chars, *, rule=RULE, description_column=DESCRIPTION):
    """Keep one logical row per event, with its cell fragments in the physical parts."""
    header = group[0].header
    grid, parts, ranges = [header], [], []
    suffixes = {}
    for panel in group:
        first = 0 if not parts else len(grid)
        sources = []
        if not parts:
            sources.extend({"r": 0, "c": c, "bbox": box, "text": text}
                           for c, (box, text) in enumerate(zip(panel.boxes[0], header)) if text)
        for row, boxes in zip(panel.rows, panel.boxes[1:]):
            target = len(grid)
            if continuation_row(row, description_column):
                target -= 1
                first = target
                suffixes[len(parts)] = row[description_column]
                grid[target][description_column] += " " + row[description_column]
            else:
                grid.append(row.copy())
            sources.extend({"r": target, "c": c, "bbox": box, "text": text}
                           for c, (box, text) in enumerate(zip(boxes, row)) if text)
        ref = f"textlayer:{rule}:p{panel.page}"
        parts.append({"source_ref": ref, "page": panel.page, "bbox": panel.bbox, "row_start": first, "row_end": len(grid),
                      "header": [panel.header], "cell_sources": sources})
        ranges.append((max(first, 1), len(grid)))
    table = grid_table_record(logical_id, doc_id, parts[0]["source_ref"], parts[0]["page"], parts[0]["bbox"], grid)
    table["regions"] = [{"page": part["page"], "bbox": part["bbox"]} for part in parts]
    table["verified_parts"] = parts
    pieces = []
    for index, (lo, hi) in enumerate(ranges):
        part = parts[index]
        if index + 1 in suffixes:
            hi -= 1
        preceding = lo
        if suffix := suffixes.get(index):
            split = grid_table_record(logical_id, doc_id, part["source_ref"], part["page"], part["bbox"], [header, grid[lo]])
            chunk, = table_chunks(split, template, max_chars)
            previous = parts[index - 1]
            offset = chunk["text"].rfind(suffix)
            if offset <= 0:
                return None
            span = chunk["source_spans"][0]
            chunk.update(row_start=lo, row_end=lo + 1, page=previous["page"], pages=[previous["page"], part["page"]],
                         regions=table["regions"][index - 1:index + 1], source_spans=[
                             dict(span, page=previous["page"], source_ref=previous["source_ref"], end=offset),
                             dict(span, start=offset)])
            pieces.append(chunk)
            preceding += 1
        if preceding < hi:
            page_table = grid_table_record(logical_id, doc_id, part["source_ref"], part["page"], part["bbox"], [header, *grid[preceding:hi]])
            for chunk in table_chunks(page_table, template, max_chars):
                chunk.update(row_start=chunk["row_start"] + preceding - 1, row_end=chunk["row_end"] + preceding - 1)
                pieces.append(chunk)
    return table, pieces


def native_matches(tables, group):
    matches = set()
    for panel in group:
        page_matches = []
        for table in tables:
            for region in table["regions"]:
                if region["page"] != panel.page:
                    continue
                bbox = region["bbox"]
                if not bbox_iou(bbox, panel.bbox):
                    continue
                left, top, right, bottom = panel.bbox
                if (len(table["regions"]) != 1 or not table["source_ref"].startswith("#/tables/")
                        or bbox_iou(bbox, panel.bbox) < .85 or bbox[0] < left - 3 or bbox[1] < top - 3
                        or bbox[2] > right + 3 or bbox[3] > bottom + 3):
                    return None
                page_matches.append(table["table_id"])
        if len(page_matches) > 1:
            return None
        matches.update(page_matches)
    return matches


def replace_chunks(chunks, pieces, removed):
    native_positions = {}
    for index, chunk in enumerate(chunks):
        if chunk["table_id"] in removed:
            native_positions.setdefault(chunk["page"], index)
    insertions = defaultdict(list)
    for piece in pieces:
        page = piece["page"]
        index = native_positions.get(page)
        if index is None:
            index = next((i for i, chunk in enumerate(chunks) if (chunk["page"] or 0) > page), len(chunks))
        insertions[index].append(piece)
    result = []
    for index, chunk in enumerate(chunks):
        result.extend(insertions.get(index, ()))
        if chunk["table_id"] not in removed:
            result.append(chunk)
    result.extend(insertions.get(len(chunks), ()))
    return result


def repair_document(pdf, pages, chunks, tables, doc_id, max_chars, contexts, stacked_pages=()):
    eligible = {page["page"]: page for page in pages if page["mode"] == "text" and page["page"] not in stacked_pages}
    if not eligible:
        return chunks, tables, []
    findings = []
    try:
        titles = [n for n, text in pdf_page_texts(pdf, eligible).items() if TITLE in key(text)]
    except (OSError, RuntimeError, ValueError):
        return chunks, tables, [{"page": min(eligible), "rule": RULE, "reason": "activity_title_scan_unavailable"}]
    handled = set()
    for start in titles:
        if start in handled:
            continue
        try:
            group = verified_group(pdf, eligible, contexts, start)
        except (ImportError, OSError, RuntimeError, ValueError):
            group = None
        remove = native_matches(tables, group) if group else None
        if not group or remove is None or not chunks:
            findings.append({"page": start, "rule": RULE, "reason": "unproven_activity_continuation"})
            continue
        index = next((i for i, row in enumerate(chunks) if row["table_id"] in remove or (row["page"] or 0) >= start), len(chunks))
        table_id = f"{doc_id}#{RULE}-p{start}"
        template = dict(chunk_template(chunks[min(index, len(chunks) - 1)]), section=None, section_path=[], ocr=False, quality="ok")
        rebuilt = assemble(group, doc_id, table_id, template, max_chars)
        if not rebuilt:
            findings.append({"page": start, "rule": RULE, "reason": "unproven_split_row_spans"})
            continue
        table, pieces = rebuilt
        chunks = replace_chunks(chunks, pieces, remove)
        first_table = next((i for i, row in enumerate(tables) if row["table_id"] in remove), len(tables))
        tables = tables[:first_table] + [table] + [row for row in tables[first_table:] if row["table_id"] not in remove]
        handled.update(panel.page for panel in group)
    return chunks, tables, findings


def verified_group(pdf, eligible, contexts, start):
    import pymupdf

    group = []
    with pymupdf.open(pdf) as source:
        for number in range(start, max(eligible, default=0) + 1):
            info = eligible.get(number)
            if info is None or contexts.get(number, {}) != contexts.get(start, {}):
                return None
            transition = normalized_rotation(info)
            angle = transition[1] if transition else source[number - 1].rotation
            layer = source_page(pdf, number, displayed_origin=True, rotation_override=angle)
            panel = read_grid(layer, number)
            if (panel is None or panel.sequence[0] != len(group) + 1 or panel.sequence[1] < 2
                    or (group and (panel.sequence[1] != group[0].sequence[1] or any(not compatible(prior, panel) for prior in group)
                                   or panel.bbox[1] > layer["height"] * .22))
                    or not agrees_with_source(panel, independent_words(source[number - 1], angle))):
                return None
            if panel.sequence[0] < panel.sequence[1] and panel.bbox[3] < layer["height"] * .8:
                return None
            if any(continuation_row(row) for row in panel.rows):
                if not group or panel.sequence[0] != panel.sequence[1] or len(panel.rows) != 1:
                    return None
            group.append(panel)
            if panel.sequence[0] == panel.sequence[1]:
                return group
    return None
