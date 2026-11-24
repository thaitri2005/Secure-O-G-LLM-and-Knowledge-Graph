"""Recover colonless daily-report cost and depth fields from explicit printed labels."""
from __future__ import annotations

import re

from .table_recognition import page_lines
from .text_layer import union

TITLE = re.compile(r"\bdaily drilling report\b", re.I)
CURRENCY = r"\$\d+(?:,\d{3})*(?:\.\d{2})?"
COSTS = re.compile(fr"(?P<daily>DAILY COST) (?P<daily_value>{CURRENCY}) ?"
                   fr"(?P<cumulative>CUM\. COST) (?P<cumulative_value>{CURRENCY})(?= |$)", re.I)
MEASURE = r"\d[\d,]*(?:\.\d+)?\s*(?:ft|m)?"
DEPTH = re.compile(fr"(?P<depth>DEPTH AT (?:0600|06:00)) (?P<depth_value>{MEASURE}(?: \(TD\))?)"
                   fr"(?= EST TD {MEASURE}(?: |$))", re.I)


def glyph_line(layer, words):
    """Build a searchable line with one source box per character, including joined PDF words."""
    y0 = min(w["bbox"][1] for w in words)
    y1 = max(w["bbox"][3] for w in words)
    line = [g for g in layer["chars"] if y0 <= (g["bbox"][1] + g["bbox"][3]) / 2 <= y1]
    boxes = []
    for word in words:
        left, top, right, bottom = word["bbox"]
        glyphs = sorted((g for g in line
                         if left <= (g["bbox"][0] + g["bbox"][2]) / 2 <= right
                         and top <= (g["bbox"][1] + g["bbox"][3]) / 2 <= bottom),
                        key=lambda g: g["bbox"][0])
        if "".join(g["text"] for g in glyphs) != word["text"]:
            return []
        if boxes:
            boxes.append(None)
        boxes.extend(g["bbox"] for g in glyphs)
    return boxes


def header_fields(layer):
    if layer["rotation"]:
        return []
    lines = [(line, " ".join(w["text"] for w in line["words"]))
             for line in page_lines(layer) if line["bottom"] <= layer["height"] / 4]
    heading = next((i for i, (_, text) in enumerate(lines) if TITLE.search(text)), None)
    if heading is None:
        return []
    found = {}
    for line, text in lines[heading + 1:]:
        for rule, names in ((COSTS, ("daily", "cumulative")), (DEPTH, ("depth",))):
            matches = list(rule.finditer(text))
            if len(matches) != 1:
                continue
            match = matches[0]
            boxes = glyph_line(layer, line["words"])
            if not boxes:
                continue
            for name in names:
                key = match.group(name)
                val = name + "_value"
                value = match.group(val).strip()
                key_box = union([box for box in boxes[slice(*match.span(name))] if box])
                value_box = union([box for box in boxes[slice(*match.span(val))] if box])
                if key_box[2] > value_box[0]:
                    continue
                if name in found:  # A repeated candidate in the report header is ambiguous.
                    found[name] = None
                else:
                    found[name] = {"key": key, "value": value, "key_bbox": key_box, "value_bbox": value_box,
                                   "canonical_key": None, "verified": False, "source_word_boxes": True}
    return [field for field in found.values() if field]


def add_header_fields(layer, form, share, minimum_share):
    """Extend an unverified form with source-backed fields the colon-based reader missed."""
    if form and form["verified"]:
        return form
    fields = header_fields(layer)
    if not fields:
        return form
    if form:
        keys = {field["key"].rstrip(":").casefold() for field in form["fields"]}
        return dict(form, fields=form["fields"] + [f for f in fields if f["key"].casefold() not in keys])
    return {"status": "success", "fields": fields, "reference_text": layer["text"], "header_boundary": layer["height"] / 4,
            "bbox_frame": "displayed physical page, top-left PDF points", "rotation": layer["rotation"],
            "text_layer_only": True, "visible_glyph_clipping": True, "method": "generic", "verified": False,
            "template_label_share": share, "template_minimum_share": minimum_share}
