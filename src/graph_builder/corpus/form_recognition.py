"""Opt-in, additive FORM recognition. Ambiguous source regions abstain."""
from __future__ import annotations

import math
from statistics import median

from .text_layer import physical_box, union

KEYS = {"version", "labels", "geometry", "eligibility", "excluded_titles", "table_headers"}
# Optional boolean. Absent or true: fields are also recognised in eligible regions outside the template header (P2).
# False: only the header of pages the legacy extractor read with the RIMBase template is extended (P1).
OPTIONAL_KEYS = {"non_header_regions"}
GEOMETRY = {"label_start_gap_em", "value_phrase_gap_em", "row_gap_lines"}
ELIGIBILITY = {"min_labels", "min_rows", "min_nonempty"}


def compact(text: str) -> str:
    return " ".join(text.split())


def validate_form_recognition(options: dict) -> None:
    if not isinstance(options, dict) or not KEYS <= set(options) <= KEYS | OPTIONAL_KEYS or options["version"] != "v1":
        raise ValueError("form_recognition requires exactly the v1 registry and settings")
    if "non_header_regions" in options and type(options["non_header_regions"]) is not bool:
        raise ValueError("form_recognition non_header_regions must be true or false")
    labels = options["labels"]
    if not isinstance(labels, dict) or not labels:
        raise ValueError("form_recognition labels must be a nonempty registry")
    spellings = {}
    for identity, aliases in labels.items():
        if not isinstance(identity, str) or not identity.strip() or not isinstance(aliases, list) or not aliases:
            raise ValueError("Each registered label needs a name and explicit spellings")
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError("Label spellings must be nonempty strings")
            key = compact(alias)
            if key in spellings:
                raise ValueError("Duplicate or colliding label alias: " + key)
            spellings[key] = identity
    for name in ("excluded_titles", "table_headers"):
        values = options[name]
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(name + " must be a nonempty string list")
        if len({compact(v) for v in values}) != len(values):
            raise ValueError("Duplicate " + name)
    geometry = options["geometry"]
    if not isinstance(geometry, dict) or set(geometry) != GEOMETRY:
        raise ValueError("Unknown or missing recognition geometry setting")
    for name, value in geometry.items():
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 4:
            raise ValueError("Recognition geometry must be finite, positive and at most 4 em/lines")
    eligibility = options["eligibility"]
    if not isinstance(eligibility, dict) or set(eligibility) != ELIGIBILITY:
        raise ValueError("Unknown or missing eligibility setting")
    for name, floor in (("min_labels", 4), ("min_rows", 2), ("min_nonempty", 2)):
        if type(eligibility[name]) is not int or not floor <= eligibility[name] <= 100:
            raise ValueError("Unsafe eligibility threshold: " + name)


def box_ok(box) -> bool:
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in box)
            and box[0] < box[2] and box[1] < box[3])


def overlaps(a, b) -> bool:
    return bool(a and b and a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])


def labels_in_row(row: list[dict], options: dict) -> tuple[list[dict], bool]:
    """Longest explicit spelling wins at a start; crossing interpretations abstain."""
    matches = []
    height = median(w["bbox"][3] - w["bbox"][1] for w in row)
    for start in range(len(row)):
        if start and row[start]["bbox"][0] - row[start - 1]["bbox"][2] < options["geometry"]["label_start_gap_em"] * height:
            continue
        possible = []
        for end in range(start + 1, len(row) + 1):
            text = compact(" ".join(w["text"] for w in row[start:end]))
            for identity, aliases in options["labels"].items():
                if text in {compact(a) for a in aliases}:
                    possible.append(dict(identity=identity, start=start, end=end, words=row[start:end], bbox=union(row[start:end])))
        if possible:
            longest = max(p["end"] for p in possible)
            winners = [p for p in possible if p["end"] == longest]
            if len(winners) != 1:
                return [], True
            matches.append(winners[0])
    for i, a in enumerate(matches):
        if any(a["start"] < b["end"] and b["start"] < a["end"] for b in matches[i + 1:]):
            return [], True
    return matches, False


def separated(previous: list[dict], following: list[dict], layer: dict, options: dict) -> bool:
    """Use the same local gap/ruling boundary for pairing, masks and eligibility."""
    before, after = union(previous), union(following)
    height = median(w["bbox"][3] - w["bbox"][1] for w in following)
    return (after[1] - before[3] > options["geometry"]["row_gap_lines"] * height or
            any(b[2] - b[0] >= .8 * layer["width"] and b[3] - b[1] <= 1.6
                and before[3] < b[1] < after[1] for b in layer["rulings"]))


def local_followers(rows, index, layer, options, masks, excluded_boxes, left, right):
    """Stop continuation inspection at region boundaries, before table content."""
    previous = rows[index]
    for row in rows[index + 1:]:
        if separated(previous, row, layer, options):
            break
        bb = union(row)
        labels, ambiguous = labels_in_row(row, options)
        title = (not labels and not ambiguous and not any(w["text"].endswith(":") for w in row)
                 and bb[2] - bb[0] < .35 * layer["width"]
                 and abs((bb[0] + bb[2]) / 2 - layer["width"] / 2) < .03 * layer["width"])
        lane = [left, bb[1], right, bb[3]]
        if (compact(" ".join(w["text"] for w in row)) in options["excluded_titles"] or title
                or any(overlaps(lane, mask) for mask in masks)
                or any(overlaps(physical_box(lane, layer), mask) for mask in excluded_boxes)):
            break
        yield from row
        previous = row


def source_table_masks(rows: list[list[dict]], layer: dict, options: dict) -> list[list[float]]:
    """Veto header/body columns, including unruled grids and AFE side columns."""
    masks = []
    for index, row in enumerate(rows):
        height = median(w["bbox"][3] - w["bbox"][1] for w in row)
        header_start = None
        for start in range(len(row)):
            tail = compact(" ".join(w["text"] for w in row[start:]))
            if any(tail == h or tail.startswith(h + " ") for h in options["table_headers"]):
                header_start = start
                break
        labels, ambiguous = labels_in_row(row, options)
        # A row of known labels without interleaved values is a column header,
        # never positive evidence for a FORM with empty fields.
        if header_start is None and len(labels) >= 2 and not ambiguous:
            occupied = {i for label in labels for i in range(label["start"], label["end"])}
            if len(occupied) == len(row):
                header_start = 0
        if header_start is None and not labels and index + 1 < len(rows):
            phrases = []
            for word in row:
                if not phrases or word["bbox"][0] - phrases[-1][-1]["bbox"][2] >= height:
                    phrases.append([])
                phrases[-1].append(word)
            follower = rows[index + 1]
            if (len(phrases) >= 2 and all(any(c.isalpha() for w in phrase for c in w["text"]) for phrase in phrases)
                    and min(w["bbox"][1] for w in follower) - max(w["bbox"][3] for w in row) <= options["geometry"]["row_gap_lines"] * height
                    and all(any(abs(w["bbox"][0] - phrase[0]["bbox"][0]) <= .5 * height for w in follower) for phrase in phrases)):
                header_start = 0
        if header_start is None:
            continue
        left = row[header_start]["bbox"][0]
        cy = (row[0]["bbox"][1] + row[0]["bbox"][3]) / 2
        edges = [b[0] for b in layer["rulings"] if b[2] - b[0] <= 1.6 and b[1] <= cy <= b[3] and b[0] <= left]
        left = max(edges, default=left)
        bottom = max(w["bbox"][3] for w in row)
        previous = row
        for following in rows[index + 1:]:
            if separated(previous, following, layer, options):
                break
            if any(w["bbox"][0] < left < w["bbox"][2] for w in following):
                break
            bottom = max(w["bbox"][3] for w in following)
            previous = following
        masks.append([left, min(w["bbox"][1] for w in row), layer["width"], bottom])
    return masks


def recognize(layer: dict, options: dict, legacy: dict | None = None, excluded_boxes: list | None = None) -> tuple[list[dict], list[dict]]:
    """Return additions and diagnostics only; never mutate the layer or legacy fields."""
    validate_form_recognition(options)
    findings = []
    words = layer["words"]
    if not words:
        return [], [{"reason": "no_source_words"}]
    if any(not isinstance(w.get("text"), str) or not box_ok(w.get("bbox")) for w in words):
        return [], [{"reason": "invalid_source_geometry"}]
    excluded_boxes = excluded_boxes or []  # External boxes use physical page coordinates.
    if any(not box_ok(b) for b in excluded_boxes):
        return [], [{"reason": "invalid_table_geometry"}]
    rows = [sorted((w for w in words if w["row"] == r), key=lambda w: w["bbox"][0]) for r in sorted({w["row"] for w in words})]
    labelled_rows = {row[0]["row"] for row in rows if labels_in_row(row, options)[0]}
    masks = source_table_masks(rows, layer, options)
    from .forms import horizontal, vertical

    candidates = []
    regions = []
    region = []
    previous = None
    blocked_text = False
    for row_index, row in enumerate(rows):
        height = median(w["bbox"][3] - w["bbox"][1] for w in row)
        bb = union(row)
        text = compact(" ".join(w["text"] for w in row))
        labels, ambiguous = labels_in_row(row, options)
        if text in options["excluded_titles"]:
            blocked_text = True
        # Only a standalone non-field title ends a free-text section. The title
        # itself supplies no eligibility evidence.
        elif not labels and not any(w["text"].endswith(":") for w in row) and bb[2] - bb[0] < .35 * layer["width"] and abs((bb[0] + bb[2]) / 2 - layer["width"] / 2) < .03 * layer["width"]:
            blocked_text = False
        split = previous is not None and separated(previous, row, layer, options)
        if split or not labels or blocked_text or ambiguous:
            if region:
                regions.append(region)
                region = []
        previous = row
        if blocked_text or ambiguous or not labels:
            if labels or ambiguous:
                findings.append({"row": row[0]["row"], "reason": "ambiguous_labels" if ambiguous else "excluded_narrative_region"})
            continue
        row_candidates = []
        row_rejected = False
        for position, label in enumerate(labels):
            key_box = label["bbox"]
            cy = (key_box[1] + key_box[3]) / 2
            right_edges = [v for v in vertical(layer, cy) if v > key_box[2] + .5]
            right = min(right_edges, default=layer["width"])
            if position + 1 < len(labels):
                right = min(right, labels[position + 1]["bbox"][0])
            value = [w for w in row[label["end"]:] if w["bbox"][0] >= key_box[2] and w["bbox"][2] <= right]
            reason = None
            if any(w["text"].endswith(":") for w in value):
                reason = "unregistered_label_in_value"
            elif any(b["bbox"][0] - a["bbox"][2] > options["geometry"]["value_phrase_gap_em"] * height for a, b in zip(value, value[1:])):
                reason = "multiple_value_phrases"
            elif value and value[0]["bbox"][0] - key_box[2] < .3 * height:
                reason = "no_label_value_separation"
            top, bottom = horizontal(layer, key_box[0], cy)
            if value and any(w["row"] not in labelled_rows and key_box[2] < w["bbox"][0] < right and key_box[3] < w["bbox"][1] < bottom
                             for w in local_followers(rows, row_index, layer, options, masks, excluded_boxes, key_box[0], right)):
                reason = "unsupported_multiline_value"
            if not value and (right >= layer["width"] or top == 0 or bottom == layer["height"] or
                              any(key_box[2] < w["bbox"][0] < right and top < w["bbox"][1] < bottom for w in words)):
                reason = "empty_value_not_proven"
            field = dict(key=" ".join(w["text"] for w in label["words"]), value=" ".join(w["text"] for w in value),
                         key_bbox=physical_box(key_box, layer), value_bbox=physical_box(union(value), layer),
                         canonical_key=None, verified=False, source_word_boxes=True)
            if any(overlaps(box, mask) for box in (key_box, union(value)) for mask in masks) or any(
                    overlaps(box, mask) for box in (field["key_bbox"], field["value_bbox"]) for mask in excluded_boxes):
                reason = "table_region"
            if reason:
                row_rejected = True
                findings.append({"row": row[0]["row"], "label": field["key"], "reason": reason})
                continue
            row_candidates.append({"field": field, "identity": label["identity"], "row": row[0]["row"], "upright_box": key_box})
        # A mixed or ambiguous row cannot establish independent region eligibility.
        if row_rejected:
            if region:
                regions.append(region)
                region = []
        else:
            region.extend(row_candidates)
        candidates.extend(row_candidates)
    if region:
        regions.append(region)
    eligible = set()
    # Without non-header regions nothing is evaluated for eligibility, so no region finding is recorded either.
    for group in regions if options.get("non_header_regions", True) else ():
        nonempty = [c for c in group if c["field"]["value"]]
        settings = options["eligibility"]
        aligned = any(a["row"] != b["row"] and abs(a["upright_box"][0] - b["upright_box"][0]) <= .25 * (a["upright_box"][3] - a["upright_box"][1])
                      and abs(a["field"]["value_bbox"][0] - b["field"]["value_bbox"][0]) <= .25 * (a["upright_box"][3] - a["upright_box"][1])
                      for i, a in enumerate(nonempty) for b in nonempty[i + 1:])
        if (len({c["identity"] for c in group}) >= settings["min_labels"] and len({c["row"] for c in group}) >= settings["min_rows"]
                and len(nonempty) >= settings["min_nonempty"] and aligned):
            eligible.update(id(c) for c in group)
        else:
            findings.append({"rows": sorted({c["row"] for c in group}), "reason": "insufficient_region_evidence"})
    added = []
    existing = legacy["fields"] if legacy else []
    for candidate in candidates:
        field = candidate["field"]
        if any(overlaps(field["key_bbox"], f["key_bbox"]) for f in existing):
            continue
        if any(overlaps(b, other) for b in (field["key_bbox"], field["value_bbox"]) for f in existing
               for other in (f["key_bbox"], f["value_bbox"])):
            findings.append({"label": field["key"], "reason": "overlaps_legacy_field"})
            continue
        header = legacy is not None and legacy["method"] == "rimbase_template" and candidate["upright_box"][3] < legacy["header_boundary"]
        if not header and id(candidate) not in eligible:
            continue
        attribution = "P1" if header else "P2"
        added.append(field)
        findings.append({"label": field["key"], "key_bbox": field["key_bbox"], "reason": "accepted", "attribution": attribution,
                         "field_index": len(existing) + len(added) - 1})
    return added, findings


def append_candidate(layer, options, legacy, share, minimum_share, number, findings, excluded_boxes=None):
    additions, decisions = recognize(layer, options, legacy, excluded_boxes)
    if findings is not None:
        findings.extend(dict(page=number, **item) for item in decisions)
        findings.append({"page": number, "legacy_field_count": len(legacy["fields"]) if legacy else 0,
                         "recognition_only": legacy is None and bool(additions)})
    if not additions:
        return legacy
    if legacy:
        return dict(legacy, fields=legacy["fields"] + additions)
    return dict(status="success", fields=additions, reference_text=layer["text"], header_boundary=layer["height"],
                bbox_frame="displayed physical page, top-left PDF points", rotation=layer["rotation"], text_layer_only=True,
                visible_glyph_clipping=True, method="generic", verified=False, template_label_share=share,
                template_minimum_share=minimum_share)


def legacy_first(forms, findings):
    new_pages = {item["page"] for item in findings if item.get("recognition_only")}
    return [f for f in forms if f["page"] not in new_pages] + [f for f in forms if f["page"] in new_pages]
