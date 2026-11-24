"""Recover ruled three-column operation logs from printed headers and clock rows."""
from __future__ import annotations

from collections import Counter
import re

from .casing_tables import (RULE_TOLERANCE, assign_cell_words, bounds_overlap, centre, chunk_tokens, inside,
                            read_cells, trim_compound, vertical_rules)
from .ops_tables import chunk_template, grid_table_record, table_chunks
from .report_context import pdf_page_texts
from .table_recognition import em, page_lines
from .text_layer import source_page, union

RULE = "hourly_operations"
CLOCK = re.compile(r"(?:(?:[01]?\d|2[0-3]):[0-5]\d|24:00)")
TITLE_PERIOD = r"(?:\s+\d{4}\s+to\s+\d{4}(?:\s+on\s+\d{1,2}/\d{1,2}/\d{2,4})?)?"


def normalize(text):
    return " ".join(text.casefold().split())


def title_pattern(template):
    return re.compile(r"\s+".join(map(re.escape, template["title"].split())) + TITLE_PERIOD, re.I)


def compile_templates(templates):
    return [dict(template, pattern=title_pattern(template),
                 columns=[{normalize(alias) for alias in names} for names in template["columns"]])
            for template in templates]


def row_text(line):
    return " ".join(word["text"] for word in line["words"])


def similar_position(left, right):
    return len(left) == len(right) and all(abs(a - b) <= RULE_TOLERANCE for a, b in zip(left, right))


def title_top(layer, rules, title, left, right, height):
    start, end = title["top"] - height, title["top"] + RULE_TOLERANCE
    frames = [y for y, x0, x1 in rules if start <= y <= end and similar_position([left, right], [x0, x1])]
    frames.extend(b[1] for b in layer["rulings"]
                  if start <= b[1] <= end and title["bottom"] - RULE_TOLERANCE <= b[3] <= title["bottom"] + height
                  and similar_position([left, right], b[::2]))
    return max(frames, default=None)


def body_levels(rules, edges, top):
    left, *_, details, right = edges
    levels = []
    for y, x0, x1 in rules:
        if y - top <= RULE_TOLERANCE or abs(x1 - right) > RULE_TOLERANCE:
            continue
        full_width = abs(x0 - left) <= RULE_TOLERANCE
        if not full_width and abs(x0 - details) > RULE_TOLERANCE:
            continue
        if levels and y - levels[-1][0] <= RULE_TOLERANCE:
            if full_width:
                levels[-1] = (levels[-1][0], True)
        else:
            levels.append((y, full_width))
    return levels


def body_grid(layer, lines, rules, edges, top):
    left, right = edges[0], edges[-1]
    rows = []
    cell_boxes = []
    end = top
    closed = False
    offset = 0
    for bottom, full_width in body_levels(rules, edges, top):
        if not similar_position(vertical_rules(layer, end, bottom, left, right), edges):
            break
        band = []
        while offset < len(lines) and (lines[offset]["top"] + lines[offset]["bottom"]) / 2 < bottom:
            line = lines[offset]
            offset += 1
            words = [word for word in line["words"] if left < centre(word["bbox"], 0) < right]
            if words:
                band.append({"words": words})
        if band:
            words = assign_cell_words(band, edges)
            if words is None:
                return None
            cells = read_cells(words)
            if not all(CLOCK.fullmatch(value) for value in cells[:2]):
                return None
            rows.append(cells)
            cell_boxes.append([union(cell) for cell in words])
        end, closed = bottom, full_width
    return (rows, cell_boxes, end) if closed and rows else None


def table_at(layer, title, header, body, template):
    height = em(header["words"])
    if header["top"] - title["bottom"] > 2 * height or body[0]["top"] - header["bottom"] > 2 * height:
        return None
    rules = sorted((centre(box, 1), box[0], box[2]) for box in layer["rulings"]
                   if box[3] - box[1] <= RULE_TOLERANCE and box[2] - box[0] > height)
    first_y = (body[0]["top"] + body[0]["bottom"]) / 2
    for top, left, right in reversed(rules):
        if not header["bottom"] - RULE_TOLERANCE <= top < first_y:
            continue
        if left > header["words"][0]["bbox"][0] or right < header["words"][-1]["bbox"][2]:
            continue
        above = title_top(layer, rules, title, left, right, height)
        if above is None:
            continue
        edges = vertical_rules(layer, top, first_y + height / 2, left, right)
        if len(edges) != 4:
            continue
        header_words = assign_cell_words([header], edges)
        if header_words is None:
            continue
        labels = read_cells(header_words)
        if any(normalize(label) not in aliases for label, aliases in zip(labels, template["columns"])):
            continue
        result = body_grid(layer, body, rules, edges, top)
        if result:
            rows, cell_boxes, bottom = result
            return {"bbox": [left, above, right, bottom], "grid": [labels, *rows],
                    "cell_boxes": [[union(cell) for cell in header_words], *cell_boxes], "text_height": height}
    return None


def read_page(layer, templates):
    if layer["rotation"]:
        return
    lines = page_lines(layer)
    for i, title in enumerate(lines[:-2]):
        caption = row_text(title)
        matches = [template for template in templates if template["pattern"].fullmatch(caption)]
        # A second heading of the same name can describe a headerless after-midnight log.
        # Only enter this rule when the next line gives evidence of the configured columns.
        if len(matches) == 1 and any(normalize(row_text(lines[i + 1])).startswith(alias + " ")
                                     for alias in matches[0]["columns"][0]):
            yield caption, matches[0]["id"], table_at(layer, title, lines[i + 1], lines[i + 2:], matches[0])


def tokens(values):
    return Counter(token for value in values for token in re.findall(r"\w+|[^\w\s|]", value))


def replaceable(table, region, text_height, printed, chunks):
    left, top, right, bottom = region
    # Docling's estimated vertical extent can extend past a printed ruling by a glyph height.
    if len(table["regions"]) != 1 or not inside(table["regions"][0]["bbox"], [left, top - text_height, right, bottom + text_height]):
        return False
    old_cells = tokens(cell["text"] for cell in table["cells"])
    return not old_cells - printed and all(not chunk_tokens(chunk["text"], tokens) - printed for chunk in chunks)


def repair_document(pdf, pages, chunks, tables, doc_id, file_id, max_chars, rule, stacked_pages=(), native_tables=None, *, source_texts=None):
    """Repair a matching native table or add an independent grid beside ambiguous native data."""
    chunks, tables = list(chunks), list(tables)
    findings = []
    templates = compile_templates(rule["templates"])
    numbers = [p["page"] for p in pages if p.get("mode") == "text" and p["page"] not in stacked_pages]
    if not numbers:
        return chunks, tables, findings
    for page, text in pdf_page_texts(pdf, numbers, source_texts=source_texts).items():
        if not any(normalize(template["title"]) in normalize(text) for template in templates):
            continue
        try:
            layer = source_page(pdf, page, displayed_origin=True)
            candidates = list(read_page(layer, templates))
        except (OSError, RuntimeError, ValueError) as error:
            findings.append({"page": page, "action": "review", "reason": f"text_layer_{type(error).__name__}"})
            continue
        for caption, template_id, result in candidates:
            if not result:
                findings.append({"page": page, "template": template_id, "action": "review", "reason": "unproven_grid"})
                continue
            box, grid = result["bbox"], result["grid"]
            overlaps = [(i, table) for i, table in enumerate(tables)
                        if any(r["page"] == page and bounds_overlap(box, r["bbox"]) for r in table["regions"])]
            by_table = {t["table_id"]: [i for i, c in enumerate(chunks) if c["table_id"] == t["table_id"]]
                        for _, t in overlaps}
            printed = tokens([caption, *(value for row in grid for value in row)])
            safe = [(i, t) for i, t in overlaps if by_table[t["table_id"]]
                    and replaceable(t, box, result["text_height"], printed, [chunks[j] for j in by_table[t["table_id"]]])]
            if not chunks:
                continue
            split = []
            if len(safe) == len(overlaps) == 1:
                index, old = safe[0]
                logical_id, action = old["table_id"], "replaced"
                positions = by_table[logical_id]
                start = positions[0]
                template = chunk_template(chunks[start])
                for i in reversed(positions):
                    del chunks[i]
            else:
                index, action = len(tables), "added"
                logical_id = f"{doc_id}#hourly-operations-{index + 1}"
                if native_tables:
                    for old_index, old in overlaps:
                        positions = [i for i, chunk in enumerate(chunks) if chunk["table_id"] == old["table_id"]]
                        if not positions:
                            continue
                        original_chunks = [chunks[i] for i in positions]
                        native = native_tables().get(old["source_ref"])
                        residual = trim_compound(old, native, box, printed, layer["height"], original_chunks,
                                                 token_reader=tokens)
                        if residual:
                            tables[old_index] = residual
                            residual_chunks = table_chunks(residual, chunk_template(original_chunks[0]), max_chars)
                            for i in reversed(positions):
                                del chunks[i]
                            chunks[positions[0]:positions[0]] = residual_chunks
                            split.append(f"{file_id}:t{old_index + 1}")
                start = next((i for i, c in enumerate(chunks) if min(c["pages"]) > page), len(chunks))
                template = dict(chunk_template(chunks[max(0, start - 1)]), section=None, section_path=[], ocr=False, quality="ok")
            source_ref = f"textlayer:{RULE}:p{page}:{len(findings) + 1}"
            table = grid_table_record(logical_id, doc_id, source_ref, page, box, grid)
            chunks[start:start] = table_chunks(table, template, max_chars, caption)
            tables[index:index + 1] = [table]
            competing = {t["table_id"]: f"{file_id}:t{i + 1}" for i, t in overlaps if i != index}
            chunks = [dict(chunk, quality="review") if chunk["table_id"] in competing else chunk for chunk in chunks]
            findings.append({"page": page, "template": template_id, "action": action, "table_id": f"{file_id}:t{index + 1}",
                             "box": box, "rows": len(grid) - 1, "split_tables": split,
                             "overlapping_tables_for_review": list(competing.values())})
    return chunks, tables, findings
