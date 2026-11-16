"""Label-value pairs of the lower blocks of a RIMBase daily-report page (A-435, OPTIONAL, default OFF).

``forms.py`` pairs the header block above "Operations Summary". The safety and weather blocks below the tables ("Sky Condition: ... Visibility:
... Bar. Pressure: ... Wind Gusts: ...") are left to the text chunks, where Docling lists the labels first and the values later, so a
reader cannot tell which number belongs to which label (a blank "Bar. Pressure:" shifts every following value).

Rule (all numbers in the configuration, relative to the em of the label): a configured label that starts a phrase on a row gets the words
of the SAME row between the end of the label and the next label of that row. No words: the field is blank (value ""). One phrase: that
is the value. Two or more phrases separated by a wide gap: the pairing is AMBIGUOUS, no field is output and the label is reported in the
findings. Only labels that are listed in the configuration are paired; rows inside free-text sections (operations table, management
summary, comments) are skipped; labels listed as ``multiline`` take the following indented rows that carry no label.
A page that did not match the header template is paired only when at least ``min_block_labels`` different configured labels were found
and then its form is marked unverified (method ``generic``): the page is a continuation of the same report family, not a recognised
template page.
"""
from __future__ import annotations

from typing import Any

from .text_layer import physical_box, union

LABEL_KEYS = {"multiline"}
GEOMETRY_KEYS = {"label_start_gap_em", "value_phrase_gap_em", "continuation_max_gap_lines", "continuation_indent_tolerance_em"}
TITLE_KEYS = {"centre_tolerance_page_width", "max_width_page_width"}
OPTION_KEYS = {"labels", "free_text_titles", "title", "geometry", "min_block_labels"}


def validate_form_blocks(options: Any) -> dict[str, Any]:
    """Check the ``form_blocks`` option of the K1 configuration."""
    if not isinstance(options, dict) or set(options) != OPTION_KEYS:
        raise ValueError(f"form_blocks must contain exactly {sorted(OPTION_KEYS)}")
    labels = options["labels"]
    if not isinstance(labels, dict) or not labels or any(not isinstance(key, str) or not key.strip() or not isinstance(value, dict) or set(value) != LABEL_KEYS
                                                         or type(value["multiline"]) is not bool for key, value in labels.items()):
        raise ValueError("form_blocks labels must map label text to {multiline: true|false}")
    titles = options["free_text_titles"]
    if not isinstance(titles, list) or any(not isinstance(item, str) or not item.strip() for item in titles):
        raise ValueError("form_blocks free_text_titles must be a list of title texts")
    for name, keys in (("title", TITLE_KEYS), ("geometry", GEOMETRY_KEYS)):
        section = options[name]
        if not isinstance(section, dict) or set(section) != keys or any(type(value) not in (int, float) or value <= 0 for value in section.values()):
            raise ValueError(f"form_blocks {name} must contain exactly {sorted(keys)} (positive numbers)")
    if type(options["min_block_labels"]) is not int or options["min_block_labels"] < 1:
        raise ValueError("form_blocks min_block_labels must be a positive integer")
    return options


def compact(text: str) -> str:
    return " ".join(text.casefold().split())


def row_height(row: list[dict]) -> float:
    return max(w["bbox"][3] - w["bbox"][1] for w in row)


def phrases(row: list[dict], gap_em: float) -> list[list[dict]]:
    """Words of one row grouped into phrases; a gap wider than ``gap_em`` x the word height starts a new phrase."""
    out: list[list[dict]] = []
    for word in sorted(row, key=lambda w: w["bbox"][0]):
        height = word["bbox"][3] - word["bbox"][1]
        if out and word["bbox"][0] - out[-1][-1]["bbox"][2] <= gap_em * height:
            out[-1].append(word)
        else:
            out.append([word])
    return out


def is_title(row: list[dict], layer: dict, options: dict, has_label: bool) -> bool:
    """A short centred row without a label (a section title such as "Weather Information", also when titles overlap)."""
    if has_label:
        return False
    box = union(row)
    width = layer["width"]
    return (box[2] - box[0] <= options["title"]["max_width_page_width"] * width
            and abs((box[0] + box[2]) / 2 - width / 2) <= options["title"]["centre_tolerance_page_width"] * width
            and not any(w["text"].endswith(":") for w in row))


def lower_rows(layer: dict, boundary_row: int | None) -> list[list[dict]]:
    words = layer["words"]
    ids = sorted({w["row"] for w in words})
    return [[w for w in words if w["row"] == row] for row in ids if boundary_row is None or row > boundary_row]


def block_fields(layer: dict, lexicon: dict, options: dict, boundary_row: int | None, verified: bool) -> tuple[list[dict], dict]:
    """Pair the configured labels of the rows below ``boundary_row`` (all rows when None). Returns (fields, findings)."""
    from .forms import find_labels
    geometry = options["geometry"]
    titles = {compact(title) for title in options["free_text_titles"]}
    rows = lower_rows(layer, boundary_row)
    found = []
    for index, row in enumerate(rows):
        found.append([item for item in find_labels(row, lexicon)
                      if item["indices"][0] == 0 or item["words"][0]["bbox"][0] - row[item["indices"][0] - 1]["bbox"][2] >= geometry["label_start_gap_em"] * row_height(row)])
    fields, ambiguous, skipped = [], [], 0
    free_text = boundary_row is not None  # the rows right below "Operations Summary" are the operations table
    for index, row in enumerate(rows):
        labels = found[index]
        if is_title(row, layer, options, bool(labels)):
            free_text = compact(" ".join(w["text"] for w in row)) in titles
            continue
        if free_text or not labels:
            skipped += bool(labels)
            continue
        labels = sorted(labels, key=lambda item: item["bbox"][0])
        for position, label in enumerate(labels):
            right = labels[position + 1]["bbox"][0] if position + 1 < len(labels) else layer["width"]
            span = [w for w in row if w["bbox"][0] >= label["bbox"][2] - 0.5 and (w["bbox"][0] + w["bbox"][2]) / 2 < right]
            groups = phrases(span, geometry["value_phrase_gap_em"])
            if len(groups) > 1:
                ambiguous.append({"label": label["key"], "phrases": [" ".join(w["text"] for w in group) for group in groups]})
                continue
            value = list(groups[0]) if groups else []
            if value and lexicon[label["key"]]["multiline"] and len(labels) == 1:
                value += continuation(rows, found, index, value, layer, options, geometry)
            fields.append({"key": label["key"], "value": " ".join(w["text"] for w in value), "key_bbox": physical_box(label["bbox"], layer),
                           "value_bbox": physical_box(union(value), layer) if value else None, "canonical_key": None, "verified": verified,
                           "source_word_boxes": True})
    return fields, {"ambiguous": ambiguous, "labels_in_free_text_rows": skipped}


def continuation(rows: list[list[dict]], found: list[list[dict]], index: int, value: list[dict], layer: dict, options: dict, geometry: dict) -> list[dict]:
    """Indented rows below a multi-line value that carry no label and are not titles."""
    extra, last = [], rows[index]
    left = min(w["bbox"][0] for w in value)
    for follower in range(index + 1, len(rows)):
        row = rows[follower]
        height = row_height(row)
        gap = (row[0]["bbox"][1] + row[0]["bbox"][3]) / 2 - (last[0]["bbox"][1] + last[0]["bbox"][3]) / 2
        if found[follower] or is_title(row, layer, options, False) or gap > geometry["continuation_max_gap_lines"] * height \
                or min(w["bbox"][0] for w in row) < left - geometry["continuation_indent_tolerance_em"] * height:
            break
        extra += sorted(row, key=lambda w: w["bbox"][0])
        last = row
    return extra


def extract_block_fields(layer: dict, options: dict, boundary_row: int | None, verified: bool, minimum_labels: int | None = None) -> tuple[list[dict], dict]:
    lexicon = options["labels"]
    fields, findings = block_fields(layer, lexicon, options, boundary_row, verified)
    findings["distinct_labels"] = len({field["key"] for field in fields}) + len({item["label"] for item in findings["ambiguous"]})
    if minimum_labels is not None and findings["distinct_labels"] < minimum_labels:
        return [], {**findings, "ambiguous": []}  # not a supported page: nothing is output and nothing is reported as ambiguous
    return fields, findings
