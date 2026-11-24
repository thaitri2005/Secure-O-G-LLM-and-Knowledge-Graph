"""Read explicitly titled, ruled report panels from the visible PDF text layer."""
from __future__ import annotations

from functools import cache
from itertools import pairwise
import re
import unicodedata

from .casing_tables import RULE_TOLERANCE, assign_cell_words, read_cells, vertical_rules
from .ops_tables import chunk_template, grid_table_record, table_chunks
from .report_context import pdf_page_texts
from .table_recognition import em, page_lines
from .text_layer import source_page, union

RULE = "ruled_panels"
TITLES = {
    "survey": ("survey data", "directional survey", "deviation survey"),
    "bit": ("bit data", "bit information"),
    "bha": ("bha data", "bottom hole assembly", "bottomhole assembly"),
    "pump": ("pump data",),
    "inventory": ("bulk inventory", "materials inventory", "fluid inventory"),
    "formation_depths": ("formation depths",),
    "well_summary": ("well information", "well data", "well summary", "general information"),
}
NUMBER = re.compile(r"[<>~*]?[+-]?(?:\d{1,3}(?:,\d{3})+|\d+|(?=\.\d))(?:\.\d+)?\s*(?:m(?:d|kb)?|ft|feet|°|deg|bbls?|gal|lb|kg|t|l|hr|h|%)?", re.I)
BIT_LABELS = re.compile(r"(?:bit (?:no|number|size|type|make)|size|mfg|make|type|model|jets?|depth (?:in|out)|daily mtrg|cum mtrg|hours|cum hours|mph|wob|rpm|gpm air rate|pump psi|grade out|serial(?: no| number)?|footage)(?: .*)?", re.I)
WELL_LABELS = re.compile(
    r"(?:well(?: name| number| id| type| location|head location)?|(?:total|final|planned|actual|measured|true vertical) depth"
    r"|casing shoe(?: md| tvd)?|(?:spud|completion) date|(?:drilling )?rig(?: name)?|operator|field|permit(?: number)?"
    r"|country(?: area)?|area|coordinate reference system|ground level(?: gl)?|rotary table (?:height|elevation)"
    r"|drilling (?:project manager|contractor)(?: pm)?|(?:surface |wellhead )?(?:easting|northing|elevation)|utm zone)"
    r"(?: (?:ft|m|md|tvd|asl))*", re.I,
)
WELL_TITLE = re.compile(
    r"(?:table \d+[a-z]? )?(?:(?:[a-z0-9]+ )*\d[a-z0-9]*(?: \d[a-z0-9]*)* )?"
    r"(?:well information|well data|well summary|general information)(?: continued)?"
)
DEPTH = re.compile(r"(?:md|depth|measured depth)(?: (?:ft|feet|m|md))*")
DEVIATION = re.compile(r"(?:dev|deviation|inc|incl|inclination)(?: (?:deg|degrees))*")
BIT_IDENTIFIER = re.compile(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*")
NUMBERED_BHA = re.compile(r"\bbha\s*#\s*[0-9]+\b", re.I)
BHA_SUMMARY_ROWS = {"bha length", "bha weight", "string wt", "hook load", "wt below jars"}
PUMP_HEADER = {"pump no", "pump number"}
PUMP_TEXT_ROWS = {"make", "model", "liner size"}
PUMP_RATE = re.compile(r"(?:output(?: gps)?|spm|gpm|pressure)(?: (?:spm|gpm|psi|kpa|mpa|bar))?")
PUMP_VALUE = re.compile(r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:\s*(?:spm|gpm|psi|kpa|mpa|bar))?", re.I)
BIT_FIELDS = {"size inches", "size in", "size", "make", "mfg", "type", "iadc code", "serial number", "serial no",
              "t f a in", "tfa in", "depth in m", "depth out m", "depth in ft", "depth out ft", "total meters", "total feet"}
DEPTH_UNIT = re.compile(r"\((?:m|ft)(?:\s*kb)?\)", re.I)


def key(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def is_number(text):
    return bool(NUMBER.fullmatch(text))


def header_matches(kind, values):
    cols = [key(value) for value in values]
    if kind == "survey":
        return (2 <= len(cols) <= 12 and DEPTH.fullmatch(cols[0]) and DEVIATION.fullmatch(cols[1])
                and (len(cols) == 2 or cols[2].split()[:1] in (["az"], ["azi"], ["azimuth"])))
    if kind == "bha":
        return (len(cols) == 2 and cols[0] in ("item", "tool", "description") and cols[1].startswith("length")
                or len(cols) == 4 and cols[0] in ("item", "tool", "description")
                and cols[1] in ("amt", "qty", "quantity") and cols[2] in ("id od", "od", "size") and cols[3].startswith("length"))
    if kind == "pump":
        return (2 <= len(cols) <= 4 and cols[0] in PUMP_HEADER
                and all(re.fullmatch(r"[0-9]+", value) for value in values[1:])
                and len(set(values[1:])) == len(values) - 1)
    if kind == "inventory":
        measures = {"beginning", "used", "received", "on hand", "net", "opening", "closing", "quantity", "remaining"}
        return 3 <= len(cols) <= 10 and cols[0] in ("item", "item type", "material", "description", "product") and len(set(cols) & measures) >= 2
    if kind == "formation_depths":
        return cols == ["name", "estimated", "actual"]
    return False


def valid_body(kind, values):
    label, *rest = values
    if kind in ("bit", "well_summary"):
        grammar = BIT_LABELS if kind == "bit" else WELL_LABELS
        counts = (1, 2) if kind == "bit" else (1,)
        return len(rest) in counts and grammar.fullmatch(key(label))
    if kind == "survey":
        return is_number(label) and bool(rest[0]) and all(not value or is_number(value) or key(value) == "miss run" for value in rest)
    if kind == "bha":
        return bool(label and rest[-1] and is_number(rest[-1])) and (len(rest) == 1 or is_number(rest[0]))
    if kind == "pump":
        field = key(label)
        return field in PUMP_TEXT_ROWS or (PUMP_RATE.fullmatch(field) and all(
            value.casefold() in ("", "-", "–", "—", "n/a") or PUMP_VALUE.fullmatch(value) for value in rest))
    if kind == "formation_depths":
        return (len(rest) == 2 and any(letter.isalpha() for letter in label)
                and all(is_number(value) or value.casefold() in ("", "-", "–", "—", "unknown", "n/a") for value in rest))
    return bool(label) and any(is_number(value) for value in rest)


def band_words(lines, left, right, top, bottom):
    return [{"words": [word for word in line["words"] if left <= (word["bbox"][0] + word["bbox"][2]) / 2 <= right]}
            for line in lines if top <= (line["top"] + line["bottom"]) / 2 < bottom]


def assign_header(kind, words, slots):
    cells = assign_cell_words(words, slots)
    if cells is not None or kind != "survey":
        return cells, ""
    labels = {key(word["text"]) for row in words for word in row["words"]}
    shared = [word for row in words for word in row["words"] if key(word["text"]) == "coordinates"
              and any(word["bbox"][0] + RULE_TOLERANCE < x < word["bbox"][2] - RULE_TOLERANCE for x in slots[1:-1])]
    if len(shared) != 1 or not {"n s", "e w"} <= labels:
        return None, ""
    return assign_cell_words([{"words": [word for word in row["words"] if word is not shared[0]]} for row in words], slots), shared[0]["text"]


def horizontal_bands(layer, left, right, top):
    """Combine rules drawn separately in each cell, within one panel's printed borders."""
    segments = sorted(((box[1] + box[3]) / 2, box[0], box[2]) for box in layer["rulings"]
                      if box[3] - box[1] <= RULE_TOLERANCE and box[2] - box[0] > 2 * RULE_TOLERANCE
                      and left - RULE_TOLERANCE <= box[0] < box[2] <= right + RULE_TOLERANCE
                      and (box[1] + box[3]) / 2 >= top - RULE_TOLERANCE)
    lines = []
    for y, x0, x1 in segments:
        if not lines or y - lines[-1][0] > RULE_TOLERANCE:
            lines.append((y, []))
        lines[-1][1].append((x0, x1))
    levels = []
    for y, intervals in lines:
        covered = left
        for start, end in sorted(intervals):
            if start > covered + RULE_TOLERANCE:
                break
            covered = max(covered, end)
        if covered >= right - RULE_TOLERANCE:
            levels.append(y)
    return levels


def anchored_bits(layer, lines, title):
    """Read a Bit Number grid below a title and preserve its printed bit IDs as column keys."""
    l, t, r, b = union(title)
    height = em(title)
    boundaries = {(box[0], box[2], (box[1] + box[3]) / 2) for box in layer["rulings"]
                  if box[3] - box[1] <= RULE_TOLERANCE and box[0] <= l < r <= box[2]
                  and b - height / 3 <= (box[1] + box[3]) / 2 <= b + height}
    for left, right, top in sorted(boundaries, key=lambda band: (band[1] - band[0], band[2], band[0])):
        levels = horizontal_bands(layer, left, right, top)
        grid, boxes, labels = [], [], set()
        schema = None
        bottom = top
        for upper, lower in pairwise(levels):
            if lower - upper > 4 * height:
                break
            slots = vertical_rules(layer, upper, lower, left, right)
            cells = assign_cell_words(band_words(lines, left, right, upper, lower), slots)
            values = read_cells(cells) if cells else []
            if not grid:
                if upper - top > 4 * height:
                    break
                if (len(values) not in (2, 3) or key(values[0]) not in ("bit no", "bit number")
                        or not all(BIT_IDENTIFIER.fullmatch(value) for value in values[1:]) or len(set(values[1:])) < len(values) - 1):
                    continue
                schema = slots
                header_top = upper
            elif (len(slots) != len(schema) or any(abs(a - b) > RULE_TOLERANCE for a, b in zip(slots, schema))
                  or not values or key(values[0]) not in BIT_FIELDS or key(values[0]) in labels):
                break
            grid.append(values)
            labels.add(key(values[0]))
            boxes.append([union(cell) for cell in cells])
            bottom = lower
        if len(grid) >= 5 and any(label.startswith("size") for label in labels) and "type" in labels:
            return {"bbox": [left, header_top, right, bottom], "grid": grid, "cell_boxes": boxes,
                    "caption": " ".join(word["text"] for word in title), "caption_bbox": [l, t, r, b]}
    return None


def read_at(layer, lines, kind, title):
    title_box = union(title)
    l, t, r, b = title_box
    height = em(title)
    caption = " ".join(word["text"] for word in title)
    numbered_bha = kind == "bha" and NUMBERED_BHA.fullmatch(caption)
    bands = sorted(((box[1] + box[3]) / 2, box[0], box[2]) for box in layer["rulings"]
                   if box[3] - box[1] <= RULE_TOLERANCE and box[0] <= l < r <= box[2])
    for top, left, right in bands:
        if not b - height / 3 <= top <= b + height:
            continue
        if numbered_bha:
            edges = horizontal_bands(layer, left, right, top)
        else:
            edges = [top]
            for y, x0, x1 in bands:
                if y - edges[-1] > RULE_TOLERANCE and abs(x0 - left) <= RULE_TOLERANCE and abs(x1 - right) <= RULE_TOLERANCE:
                    edges.append(y)
        rows, boxes, labels = [], [], set()
        columns = None
        bottom = top
        is_field_panel = kind in ("bit", "well_summary")
        group_label = ""
        for index, (y0, y1) in enumerate(zip(edges, edges[1:])):
            if y1 - y0 > (8 if kind == "well_summary" else 4) * height:
                break
            slots = vertical_rules(layer, y0, y1, left, right)
            is_header = index == 0 and not is_field_panel
            if is_header and len(slots) == 2 and len(edges) > 2:
                slots = vertical_rules(layer, y1, edges[2], left, right)
            if columns is not None and (len(columns) != len(slots) or any(abs(a - b) > RULE_TOLERANCE for a, b in zip(columns, slots))):
                break
            if len(slots) < 3:
                break
            words = band_words(lines, left, right, y0, y1)
            if is_header:
                cells, group_label = assign_header(kind, words, slots)
            else:
                cells = assign_cell_words(words, slots)
            if not cells:
                if (kind in ("well_summary", "pump") or numbered_bha) and any(line["words"] for line in words):
                    return None
                break
            values = read_cells(cells)
            label = key(values[0])
            if numbered_bha and rows and label in BHA_SUMMARY_ROWS:
                # These measurements are not tool lengths despite sharing the same ruling.
                break
            okay = valid_body(kind, values) if rows or is_field_panel else header_matches(kind, values)
            if kind == "pump" and rows and label in labels:
                return None
            if not okay:
                if (kind in ("well_summary", "pump") or numbered_bha) and any(values):
                    return None
                break
            rows.append(values)
            labels.add(label)
            boxes.append([union(cell) for cell in cells])
            bottom, columns = y1, slots
        if is_field_panel:
            if columns is None or sum(any(row[1:]) for row in rows) < 2:
                continue
            if kind == "well_summary":
                labels = [key(row[0]) for row in rows]
                if len(set(labels)) != len(labels):
                    continue
            rows.insert(0, [caption] + [""] * (len(columns) - 2))
            boxes.insert(0, [title_box] + [None] * (len(columns) - 2))
            caption = ""
        elif (len(rows) < (2 if kind == "inventory" else 3)
              or (kind == "pump" and not any(any(row[1:]) for row in rows[1:]))
              or (kind == "formation_depths" and not any(is_number(value) for row in rows[1:] for value in row[1:]))):
            continue
        panel = {"bbox": [left, t, right, bottom], "grid": rows, "cell_boxes": boxes,
                 "caption": " ".join(part for part in (caption, group_label) if part)}
        if kind in ("formation_depths", "pump") or numbered_bha:
            panel["caption_bbox"] = title_box
        return panel
    return None


def numbered_bha_titles(layer, words):
    """Require the printed title's own ruled band so narrative references do not become candidates."""
    for start in range(len(words)):
        for size in (1, 2, 3):
            group = words[start:start + size]
            if len(group) != size or not NUMBERED_BHA.fullmatch(" ".join(word["text"] for word in group)):
                continue
            height = em(group)
            if any(b["bbox"][0] - a["bbox"][2] > height for a, b in pairwise(group)):
                continue
            left, _, right, bottom = union(group)
            starts = [box for box in layer["rulings"] if box[3] - box[1] <= RULE_TOLERANCE
                      and box[0] <= left < right <= box[2] and bottom - height / 3 <= (box[1] + box[3]) / 2 <= bottom + height]
            neighbors = words[:start] + words[start + size:]
            if any(not any(box[0] <= (word["bbox"][0] + word["bbox"][2]) / 2 <= box[2] for word in neighbors)
                   for box in starts):
                yield group


def read_page(layer, kinds):
    lines = page_lines(layer)
    for kind in kinds:
        matches = []
        for line in lines:
            words = line["words"]
            if kind == "well_summary":
                if WELL_TITLE.fullmatch(key(" ".join(word["text"] for word in words))):
                    matches.append(words)
                continue
            if kind == "bha":
                matches.extend(numbered_bha_titles(layer, words))
            for title in TITLES[kind]:
                expected = title.split()
                for i in range(len(words) - len(expected) + 1):
                    group = words[i:i + len(expected)]
                    if [key(word["text"]) for word in group] == expected and all(
                        b["bbox"][0] - a["bbox"][2] <= em(group) for a, b in zip(group, group[1:])
                    ):
                        if kind == "formation_depths":
                            unit = words[i + len(expected):i + len(expected) + 1]
                            if not unit or not DEPTH_UNIT.fullmatch(unit[0]["text"]) or unit[0]["bbox"][0] - group[-1]["bbox"][2] > em(group):
                                continue
                            group = group + unit
                        matches.append(group)
        for title in matches:
            panel = None if layer["rotation"] else read_at(layer, lines, kind, title)
            if not panel and kind == "bit" and not layer["rotation"]:
                panel = anchored_bits(layer, lines, title)
            yield kind, panel


def independently_readable(panel, words):
    def normalize(text):
        return re.sub(r"\s+", "", unicodedata.normalize("NFC", text)).casefold()

    centers = [((word[0] + word[2]) / 2, (word[1] + word[3]) / 2, word[4]) for word in words]
    cells = [pair for row, boxes in zip(panel["grid"], panel["cell_boxes"]) for pair in zip(row, boxes)]
    if panel.get("caption_bbox"):
        cells.append((panel["caption"], panel["caption_bbox"]))
    for cell, bbox in cells:
        if not cell:
            continue
        if not bbox:
            return False
        l, t, r, b = bbox
        observed = " ".join(text for x, y, text in centers if l - 0.5 <= x <= r + 0.5 and t <= y <= b)
        if normalize(observed) != normalize(cell):
            return False
    return True


def repair_document(pdf, pages, chunks, tables, doc_id, max_chars, kinds, *, stacked_pages=(), source_texts=None):
    chunks, tables = list(chunks), list(tables)
    findings = []
    numbers = [page["page"] for page in pages if page["mode"] == "text" and page["page"] not in stacked_pages]

    @cache
    def independent_words(number):
        try:
            import pymupdf
            with pymupdf.open(pdf) as source:
                return source[number - 1].get_text("words", sort=True)
        except (ImportError, OSError, ValueError, RuntimeError):
            return None

    for number, text in pdf_page_texts(pdf, numbers, source_texts=source_texts).items():
        normalized = key(text)
        active = [kind for kind in kinds if any(title in normalized for title in TITLES[kind])
                  or (kind == "bha" and NUMBERED_BHA.search(text))]
        if not active or not chunks:
            continue
        try:
            candidates = list(read_page(source_page(pdf, number, displayed_origin=True), active))
        except (OSError, ValueError, RuntimeError) as error:
            findings.extend({"page": number, "rule": kind, "reason": f"text_layer_{type(error).__name__}"} for kind in active)
            continue
        for index, (kind, panel) in enumerate(candidates):
            if panel is None:
                findings.append({"page": number, "rule": kind, "reason": "unproven_ruled_panel"})
                continue
            words = independent_words(number)
            if words is None or not independently_readable(panel, words):
                reason = "independent_reader_unavailable" if words is None else "independent_cell_text_differs"
                findings.append({"page": number, "rule": kind, "reason": reason})
                continue
            ref = f"textlayer:{RULE}:{kind}:p{number}:{index}"
            logical_id = f"{doc_id}#{kind}-p{number}-{index}"
            table = grid_table_record(logical_id, doc_id, ref, number, panel["bbox"], panel["grid"])
            where = next((i for i, chunk in enumerate(chunks) if min(chunk["pages"]) > number), len(chunks))
            template = dict(chunk_template(chunks[max(0, where - 1)]), section=None, section_path=[], ocr=False, quality="ok")
            chunks[where:where] = table_chunks(table, template, max_chars, panel["caption"])
            tables.append(table)
    return chunks, tables, findings
