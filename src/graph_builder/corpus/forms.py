"""Pair visible source glyphs using vector rulings and a label template."""
from __future__ import annotations

import json
from pathlib import Path

from .text_layer import source_page, union, physical_box

TEMPLATE = Path(__file__).resolve().parents[3] / "configs/corpus/rimbase_form_template.json"


def load_template(path: Path = TEMPLATE) -> dict:
    """Read the label template that describes where each known form label keeps its value."""
    return json.loads(path.read_text(encoding="utf-8"))


def extract_auto(path: Path, number: int, template: dict, minimum_share: float = 0.4, generic: bool = False, blocks: dict | None = None,
                 findings: list | None = None, recognition: dict | None = None,
                 recognition_findings: list | None = None, excluded_boxes: list | None = None,
                 *, daily_header: bool = False) -> dict | None:
    """Pair a page with the template when enough distinct labels occur visibly.

    Pages that do not match return None unless ``generic`` is true, which pairs any colon-terminated
    label and marks the result as not verified.

    ``blocks`` (the optional ``form_blocks`` configuration, default None = off) adds the label-value pairs of the lower blocks of the page
    (see ``form_blocks``); ambiguous labels are appended to ``findings`` as {page, label, phrases} and never become fields.
    """
    if recognition is not None:
        from .form_recognition import validate_form_recognition
        validate_form_recognition(recognition)
        if blocks is not None:
            raise ValueError("form_recognition and form_blocks cannot be combined")
    layer = source_page(path, number, upright=True)
    present = {label["key"] for row in sorted({w["row"] for w in layer["words"]}) for label in find_labels([w for w in layer["words"] if w["row"] == row], template["labels"])}
    share = len(present) / len(template["labels"])
    matching = share >= minimum_share and "Operations Summary" in layer["text"]

    def finish(form):
        if daily_header:
            from .daily_header import add_header_fields
            return add_header_fields(layer, form, share, minimum_share)
        return form

    if not matching and (not generic or sum((w["text"].endswith(":") for w in layer["words"])) < 3):
        if recognition is not None:
            from .form_recognition import append_candidate
            return finish(append_candidate(layer, recognition, None, share, minimum_share, number, recognition_findings, excluded_boxes))
        return finish(_block_page(layer, share, minimum_share, blocks, number, findings) if blocks else None)
    result = extract(path, number, "template" if matching else "generic", template)
    result.update(method="rimbase_template" if matching else "generic", verified=matching, template_label_share=share, template_minimum_share=minimum_share)
    if blocks and matching:
        from .form_blocks import extract_block_fields
        boundary = next((row for row in sorted({w["row"] for w in layer["words"]})
                         if " ".join(w["text"] for w in layer["words"] if w["row"] == row) == "Operations Summary"), None)
        try:
            added, found = extract_block_fields(layer, blocks, boundary, True)
        except Exception as error:  # a page the block reader cannot handle keeps its header fields
            added, found = [], {"ambiguous": [], "error": f"{type(error).__name__}: {error}"}
        result["fields"] = result["fields"] + added
        _record(findings, number, found)
    result = result if result["fields"] else None
    if recognition is not None:
        from .form_recognition import append_candidate
        result = append_candidate(layer, recognition, result, share, minimum_share, number, recognition_findings, excluded_boxes)
    return finish(result)


def _block_page(layer: dict, share: float, minimum_share: float, blocks: dict, number: int, findings: list | None) -> dict | None:
    """A page that is not a template page but carries enough configured block labels: an unverified form of those labels only."""
    from .form_blocks import extract_block_fields
    try:
        fields, found = extract_block_fields(layer, blocks, None, False, blocks["min_block_labels"])
    except Exception as error:
        fields, found = [], {"ambiguous": [], "error": f"{type(error).__name__}: {error}"}
    _record(findings, number, found)
    if not fields:
        return None
    if findings is not None:
        findings.append({"page": number, "block_only": True})  # lets the K1 builder number these forms after the template forms
    return {"status": "success", "fields": fields, "reference_text": layer["text"], "header_boundary": layer["height"],
            "bbox_frame": "displayed physical page, top-left PDF points", "rotation": layer["rotation"], "text_layer_only": True,
            "visible_glyph_clipping": True, "method": "generic", "verified": False, "template_label_share": share,
            "template_minimum_share": minimum_share}


def _record(findings: list | None, number: int, found: dict) -> None:
    if findings is not None:
        findings.extend({"page": number, **item} for item in found["ambiguous"])
        if found.get("error"):
            findings.append({"page": number, "error": found["error"]})


def horizontal(layer: dict, x: float, y: float) -> tuple[float, float]:
    """Find the surrounding horizontal vector rulings."""
    found = []
    for l, t, r, b in layer["rulings"]:
        if b - t <= 1.6 and r - l > 15 and (l - 1 <= x <= r + 1):
            found.append((t + b) / 2)
        elif r - l > 15 and b - t > 1.6:
            if l - 1 <= x <= r + 1:
                found.extend([t, b])
    return (max((v for v in found if v < y - 1), default=0), min((v for v in found if v > y + 1), default=layer["height"]))

def vertical(layer: dict, y: float) -> list[float]:
    """Find vertical cell edges crossing the specified height."""
    found = [0, layer["width"]]
    for l, t, r, b in layer["rulings"]:
        if t - 1 <= y <= b + 1:
            if r - l <= 1.6 and b - t > 3:
                found.append((l + r) / 2)
            elif r - l > 1.6 and b - t > 3:
                found.extend([l, r])
    return sorted(set(found))

def find_labels(words: list[dict], lexicon: dict | None) -> list[dict]:
    """Locate known labels or generic colon-terminated labels in a source row."""
    result = []
    if lexicon is not None:
        for start in range(len(words)):
            if any((start in r["indices"] for r in result)):
                continue
            for key in sorted(lexicon, key=len, reverse=True):
                target = key.split()
                subset = words[start:start + len(target)]
                if [w["text"] for w in subset] == target:
                    result.append({"key": key, "indices": list(range(start, start + len(target))), "words": subset})
                    break
    else:
        last_end = 0
        for end, word in enumerate(words):
            if not word["text"].endswith(":"):
                continue
            start = end
            while start > last_end:
                prior = words[start - 1]
                gap = words[start]["bbox"][0] - prior["bbox"][2]
                if gap > 8 or any((c.isdigit() for c in prior["text"])):
                    break
                start -= 1
            result.append({"key": " ".join((w["text"] for w in words[start:end + 1])), "indices": list(range(start, end + 1)), "words": words[start:end + 1]})
            last_end = end + 1
    for item in result:
        item["bbox"] = union(item["words"])
    return result

def extract(path: Path, number: int, variant: str, template: dict | None=None) -> dict:
    """Pair source words using their row, cell boundaries and label direction."""
    layer = source_page(path, number, upright=True)
    words = layer["words"]
    rows = [[w for w in words if w["row"] == row] for row in sorted({w["row"] for w in words})]
    boundary = next((min((w["bbox"][1] for w in row)) for row in rows if " ".join((w["text"] for w in row)) == "Operations Summary"), None)
    if boundary is None:
        boundary = layer["height"]
    rows = [row for row in rows if row and max((w["bbox"][3] for w in row)) < boundary]
    labels = []
    for row in rows:
        for item in find_labels(row, template["labels"] if variant == "template" else None):
            item["row_words"] = row
            labels.append(item)
    fields = []

    def emit(label, value_words):
        fields.append({"key": label["key"], "value": " ".join((w["text"] for w in value_words)), "key_bbox": physical_box(label["bbox"], layer), "value_bbox": physical_box(union(value_words), layer), "canonical_key": None, "verified": variant == "template", "source_word_boxes": True})
    totals_y = next(((p["bbox"][1] + p["bbox"][3]) / 2 for p in labels if p["key"] == "Totals:"), None)
    for label in labels:
        bb = label["bbox"]
        cy = (bb[1] + bb[3]) / 2
        edges = vertical(layer, cy)
        left = max((v for v in edges if v < bb[0] - 0.5), default=0)
        right = min((v for v in edges if v > bb[2] + 0.5), default=layer["width"])
        top, bottom = horizontal(layer, bb[0], cy)
        same = [p for p in labels if p is not label and abs((p["bbox"][1] + p["bbox"][3]) / 2 - cy) < 2.5 and (p["bbox"][0] > bb[2])]
        if same:
            right = min(right, min((p["bbox"][0] for p in same)))
        direction = template["labels"][label["key"]]["direction"] if variant == "template" else "right_then_below"
        if direction.startswith("below_column"):
            edges = vertical(layer, cy + 12)
            left = max((v for v in edges if v < bb[0] - 0.5), default=0)
            right = min((v for v in edges if v > bb[2] + 0.5), default=layer["width"])
            limit = (totals_y + 4 if direction.endswith("including_totals") else totals_y - 4) if totals_y else boundary
            for row in rows:
                value = [w for w in row if left - 0.1 <= (w["bbox"][0] + w["bbox"][2]) / 2 < right - 0.1 and w["bbox"][1] > bb[3] + 1 and ((w["bbox"][1] + w["bbox"][3]) / 2 <= limit)]
                if value and (not any((w["text"].endswith(":") for w in value))):
                    emit(label, value)
            continue
        if direction == "right_next_cell":
            right = next((v for v in edges if v > right + 1), right)
        value = [w for w in words if w["bbox"][0] >= bb[2] + 0.3 and w["bbox"][2] <= right + 0.5 and (abs((w["bbox"][1] + w["bbox"][3]) / 2 - cy) < 2.5)]
        value_start = min((w["bbox"][0] for w in value), default=bb[2] + 1)
        for row in rows:
            row_y = (row[0]["bbox"][1] + row[0]["bbox"][3]) / 2
            if cy + 3 < row_y < min(bottom, boundary) - 1:
                if any((p["bbox"][1] <= row_y <= p["bbox"][3] and left <= p["bbox"][0] < right for p in labels)):
                    continue
                value.extend((w for w in row if w["bbox"][0] >= value_start - 0.5 and w["bbox"][2] <= right + 0.5))
        emit(label, value)
    return {"status": "success", "fields": fields, "reference_text": layer["text"], "header_boundary": boundary, "bbox_frame": "displayed physical page, top-left PDF points", "rotation": layer["rotation"], "text_layer_only": True, "visible_glyph_clipping": True}
