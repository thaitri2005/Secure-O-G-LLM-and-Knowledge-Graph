"""Recover ruled casing tables from the original PDF's word boxes and vector lines."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from pathlib import Path
import re

from .ops_tables import chunk_template, grid_table_record, table_chunks
from .report_context import pdf_page_texts
from .table_recognition import em, page_lines
from .text_layer import source_page, union

RULE = "casing"
SOURCE_PREFIX = "textlayer:casing"
TITLE = re.compile(r"casing(?:\s*/\s*tubular)?\s+(?:data|information|details|record|summary)", re.I)
SIZE_HEADER = re.compile(r"(?:casing )?(?:size|od)(?:\s*\((?:ins?\.?|inches|mm)\))?", re.I)
DEPTH_HEADER = re.compile(r"(?:top |bottom )?(?:md|tvd)(?:\s*\((?:ft|m)\))?"
                          r"|(?:length|set at|setting depth|shoe depth)(?:\s*\((?:ft|m|mgl|mmd)\))?", re.I)
SIZE = re.compile(r"(?:\d+[ -])?\d+/\d+\s*[\"″']*|\d+(?:[.,]\d+)?(?:\s*(?:[\"″']+|mm|in\.?))?", re.I)
DEPTH = re.compile(r"[+-]?\d[\d,.]*(?:\s*(?:ft|m|mgl|mmd))?", re.I)
RULE_TOLERANCE = 2.0  # PDF points. Vector paths can touch the outer stroke at either edge.


def centre(box, axis):
    return (box[axis] + box[axis + 2]) / 2


def horizontal_rules(layer, title, height):
    box = title["words"][0]["bbox"]
    x = centre(box, 0)
    return sorted((centre(b, 1), b[0], b[2]) for b in layer["rulings"]
                  if b[3] - b[1] <= RULE_TOLERANCE and b[2] - b[0] >= 0.4 * layer["width"]
                  and b[0] < x < b[2] and b[1] >= title["top"] - height)


def vertical_rules(layer, top, bottom, left, right):
    xs = sorted(centre(b, 0) for b in layer["rulings"]
                if b[2] - b[0] <= RULE_TOLERANCE and b[3] - b[1] >= (bottom - top) * 0.6
                and b[1] <= top + RULE_TOLERANCE and b[3] >= bottom - RULE_TOLERANCE
                and left + RULE_TOLERANCE < centre(b, 0) < right - RULE_TOLERANCE)
    merged = []
    for x in xs:
        if not merged or x - merged[-1] > RULE_TOLERANCE:
            merged.append(x)
    return [left, *merged, right]


def assign_cell_words(lines, edges):
    """Assign every word once, keeping the PDF's reading order within each cell."""
    cells = [[] for _ in edges[1:]]
    for line in lines:
        for word in line["words"]:
            box = word["bbox"]
            column = bisect_right(edges, centre(box, 0)) - 1
            if (not 0 <= column < len(cells) or box[0] < edges[column] - RULE_TOLERANCE
                    or box[2] > edges[column + 1] + RULE_TOLERANCE or "|" in word["text"]):
                return None
            cells[column].append(word)
    return cells


def read_cells(cells):
    return [" ".join(word["text"] for word in cell) for cell in cells]


def assign_words(lines, edges):
    cells = assign_cell_words(lines, edges)
    return read_cells(cells) if cells is not None else None


def header_columns(header):
    if not header or not all(header) or len(set(map(str.casefold, header))) != len(header):
        return None
    sizes = [i for i, label in enumerate(header) if SIZE_HEADER.fullmatch(label)]
    depths = [i for i, label in enumerate(header) if DEPTH_HEADER.fullmatch(label)]
    if len(sizes) != 1 or sizes[0] > 1 or not depths or not any(re.search(r"\b(?:grade|make)\b", label, re.I) for label in header):
        return None
    return sizes[0], depths


def table_at(layer, lines, title_index):
    title = lines[title_index]
    height = em(title["words"])
    horizontal = horizontal_rules(layer, title, height)
    rows_below = lines[title_index + 1:]
    for index in range(1, min(4, len(rows_below))):
        first = rows_below[index]
        y = (first["top"] + first["bottom"]) / 2
        above = [band for band in horizontal if 0 < y - band[0] <= height * 2]
        if not above or y - title["bottom"] > 7 * height:
            continue
        top, left, right = above[-1]
        levels = []
        for position, x0, x1 in horizontal:
            if (position - top > RULE_TOLERANCE and abs(x0 - left) <= RULE_TOLERANCE
                    and abs(x1 - right) <= RULE_TOLERANCE
                    and (not levels or position - levels[-1] > RULE_TOLERANCE)):
                levels.append(position)
        if not levels or not y < levels[0] <= top + height * 3:
            continue
        edges = vertical_rules(layer, top, levels[0], left, right)
        if not 7 <= len(edges) <= 17:
            continue
        header_words = assign_cell_words(rows_below[:index], edges)
        if header_words is None:
            continue
        header = read_cells(header_words)
        columns = header_columns(header)
        if columns is None:
            continue
        size, depths = columns
        body = []
        cell_boxes = [[union(cell) for cell in header_words]]
        end = top
        offset = index
        for bottom in levels:
            next_edges = vertical_rules(layer, end, bottom, left, right)
            if (bottom - end > height * 3 or len(next_edges) != len(edges)
                    or any(abs(a - b) > RULE_TOLERANCE for a, b in zip(edges, next_edges))):
                break
            start = offset
            while offset < len(rows_below) and (rows_below[offset]["top"] + rows_below[offset]["bottom"]) / 2 < bottom:
                offset += 1
            band_lines = rows_below[start:offset]
            if band_lines:
                words = assign_cell_words(band_lines, edges)
                if words is None:
                    return None
                cells = read_cells(words)
                if (not SIZE.fullmatch(cells[size]) or sum(map(bool, cells)) < 2
                        or any(cells[col] and not DEPTH.fullmatch(cells[col]) for col in depths)):
                    return None
                body.append(cells)
                cell_boxes.append([union(cell) for cell in words])
            end = bottom
        if body:
            # A nearby casing-shaped row without compatible ruling evidence makes the whole grid uncertain.
            if offset < len(rows_below) and rows_below[offset]["top"] - end <= height * 2:
                following = assign_words(rows_below[offset:offset + 1], edges)
                if following and SIZE.fullmatch(following[size]) and sum(map(bool, following)) >= 2:
                    return None
            return {"bbox": [left, title["top"], right, end], "grid": [header, *body], "cell_boxes": cell_boxes}
    return None


def read_page(layer):
    lines = page_lines(layer)
    for number, line in enumerate(lines):
        text = " ".join(word["text"] for word in line["words"])
        if TITLE.fullmatch(text):
            result = None if layer["rotation"] else table_at(layer, lines, number)
            yield line, result


def bounds_overlap(box, other):
    return (min(box[2], other[2]) - max(box[0], other[0]) > RULE_TOLERANCE
            and min(box[3], other[3]) - max(box[1], other[1]) > RULE_TOLERANCE)


def inside(box, region):
    pad = RULE_TOLERANCE
    return (region[0] - pad <= box[0] <= box[2] <= region[2] + pad
            and region[1] - pad <= box[1] <= box[3] <= region[3] + pad)


def printed_tokens(values):
    return Counter(token for value in values for token in value.split())


def chunk_tokens(text, token_reader=printed_tokens):
    return token_reader(line.replace("|", " ") for line in text.splitlines() if not re.fullmatch(r"[\s|:-]+", line))


def trim_compound(table, item, region, expected, page_height, source_chunks, *, token_reader=printed_tokens):
    """Remove a native table prefix only if every discarded cell belongs to the recovered region."""
    from ..ingestion.tables import table_views

    if item is None or item.captions or len(item.prov) != 1 or len(table["regions"]) != 1:
        return None
    original = table["regions"][0]["bbox"]
    if not (region[1] - RULE_TOLERANCE <= original[1] < region[3] < original[3]):
        return None
    grid, _, cells, header_rows = table_views(item)
    rendered = token_reader(value for row in grid for value in row)
    if any(chunk_tokens(c["text"], token_reader) - rendered for c in source_chunks):
        return None
    known = []
    for cell in item.data.table_cells:
        if not cell.text.strip():
            continue
        if cell.bbox is None:
            return None
        bounds = cell.bbox.to_top_left_origin(page_height=page_height)
        known.append((cell, [bounds.l, bounds.t, bounds.r, bounds.b]))
    cut = 0
    for end in range(max(1, header_rows), len(grid)):
        prefix = [(cell, box) for cell, box in known if cell.start_row_offset_idx < end]
        if not prefix or token_reader(cell.text for cell, _ in prefix) - expected:
            break
        if any(not inside([centre(box, 0), centre(box, 1), centre(box, 0), centre(box, 1)], region) for _, box in prefix):
            break
        if all(cell.end_row_offset_idx <= end for cell, _ in prefix):
            cut = end
    if cut == 0 or any(cell["r"] < cut < cell["r"] + cell["row_span"] for cell in cells):
        return None
    remaining = [box for cell, box in known if cell.start_row_offset_idx >= cut]
    if not remaining:
        return None
    new_box = [original[0], max(original[1], min(box[1] for box in remaining)), original[2], original[3]]
    return dict(table, grid=grid[cut:], num_rows=len(grid) - cut, header_rows=0, native_trimmed_rows=cut,
                regions=[dict(table["regions"][0], bbox=new_box)],
                cells=[dict(c, r=c["r"] - cut) for c in cells if c["r"] >= cut],
                rows_text=["; ".join(row) for row in grid[cut:]])


def repair_document(pdf: Path, pages: list[dict], chunks: list[dict], tables: list[dict], doc_id: str,
                    file_id: str, max_chars: int, stacked_pages=(), native_tables=None, *, source_texts=None):
    """Replace a source-contained table, or add the casing grid and keep compound evidence for review."""
    chunks, tables = list(chunks), list(tables)
    findings = []
    numbers = [p["page"] for p in pages if p["mode"] == "text" and p["page"] not in stacked_pages]
    for page, text in pdf_page_texts(pdf, numbers, source_texts=source_texts).items():
        if not TITLE.search(text):
            continue
        try:
            layer = source_page(pdf, page)
            candidates = list(read_page(layer))
        except (OSError, ValueError, RuntimeError) as error:
            findings.append({"page": page, "action": "review", "reason": f"text_layer_{type(error).__name__}"})
            continue
        for title, result in candidates:
            if result is None:
                findings.append({"page": page, "action": "review", "reason": "uncertain_casing_grid",
                                 "y": round(title["top"], 2)})
                continue
            box = result["bbox"]
            overlaps = [(i, table) for i, table in enumerate(tables)
                        if any(r["page"] == page and bounds_overlap(box, r["bbox"]) for r in table["regions"])]
            grid_tokens = printed_tokens(value for row in result["grid"] for value in row)
            replacements = [(i, t) for i, t in overlaps if len(t["regions"]) == 1
                            and inside(t["regions"][0]["bbox"], box)
                            and not printed_tokens(c["text"] for c in t["cells"]) - grid_tokens
                            and all(not chunk_tokens(c["text"]) - grid_tokens
                                    for c in chunks if c["table_id"] == t["table_id"])]
            if not chunks:
                continue  # K1's completeness gate handles a document with no converted evidence.
            if len(overlaps) == len(replacements) == 1:
                index, old = replacements[0]
                logical_id, action = old["table_id"], "replaced"
                positions = [i for i, c in enumerate(chunks) if c["table_id"] == logical_id]
            else:
                index, action, positions = len(tables), "added", []
                logical_id = f"{doc_id}#casing-{index + 1}"
            ref = f"{SOURCE_PREFIX}:p{page}:{len(findings) + 1}"
            table = grid_table_record(logical_id, doc_id, ref, page, box, result["grid"])
            caption = " ".join(word["text"] for word in title["words"])
            split = []
            if native_tables and action == "added":
                expected = grid_tokens + printed_tokens([caption])
                for old_index, old in overlaps:
                    rows = [c for c in chunks if c["table_id"] == old["table_id"]]
                    residual = trim_compound(old, native_tables().get(old["source_ref"]), box, expected, layer["height"], rows)
                    if residual is None or not rows:
                        continue
                    where = next(i for i, c in enumerate(chunks) if c["table_id"] == old["table_id"])
                    chunks = [c for c in chunks if c["table_id"] != old["table_id"]]
                    chunks[where:where] = table_chunks(residual, dict(chunk_template(rows[0]), quality="review"), max_chars)
                    tables[old_index] = residual
                    split.append(f"{file_id}:t{old_index + 1}")
            if positions:
                start = positions[0]
                template = chunk_template(chunks[start])
                for i in reversed(positions):
                    del chunks[i]
            else:
                start = next((i for i, c in enumerate(chunks) if min(c["pages"]) > page), len(chunks))
                anchor = chunks[max(0, start - 1)]
                template = dict(chunk_template(anchor), section=None, section_path=[], ocr=False, quality="ok")
            chunks[start:start] = table_chunks(table, template, max_chars, caption)
            tables[index:index + 1] = [table]
            competing = {t["table_id"]: f"{file_id}:t{i + 1}" for i, t in overlaps if i != index}
            for i, chunk in enumerate(chunks):
                if chunk["table_id"] in competing:
                    chunks[i] = dict(chunk, quality="review")
            findings.append({"page": page, "action": action, "table_id": f"{file_id}:t{index + 1}",
                             "box": box, "split_tables": split, "overlapping_tables_for_review": list(competing.values())})
    return chunks, tables, findings
