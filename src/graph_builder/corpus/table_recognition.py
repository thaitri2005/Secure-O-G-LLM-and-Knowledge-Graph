"""Recognise a table format in the text layer of one page: which lines are a title, a header and a first row, and why not.

This is the recognition layer (gates G1 to G3) in front of the specialised table readers such as ``ops_tables``. It looks
at word boxes only, never at a PDF, and returns plain data instead of raising: a gate that fails gives a machine-readable
``reason`` and a ``detail``, so a page of another format is reported as unsupported and not guessed at. Nothing here
knows a document, a page number, a date or a well. The words of the title, the column labels, the patterns and every
tolerance come from the rule in ``configs/corpus/k1.json`` (``table_rules``); every distance is measured in units of the
text height of the page itself (``em_title``, ``em_header``) or of the page width, so a scaled page gives the same result.

Gates, each on a different kind of evidence:

* G0 precondition (the page is upright) is checked by the caller;
* G1 words: the title words sit next to each other on a *mention line*, and all other words of that line are far away
  horizontally (an annotation in its own column), not glued to the title (a sentence);
* G2 geometry and structure: the line right under the title has the labels of the schema, in order, left to right;
* G3 meaning: the next line starts with two time tokens.

There is no numeric confidence. A result carries an ``evidence`` record with the measured values and the margin to each
threshold, which is only for the reader and takes no part in a decision.
"""
from __future__ import annotations

import re
from statistics import median

STATES = ("SUPPORTED_AND_VALIDATED", "RECOGNISED_BUT_FAILED", "UNSUPPORTED_FORMAT", "PARSING_FAILURE")
# reason code -> (state, stage). ``SUPPORTED_AND_VALIDATED`` has no reason: the caller assigns it after a successful merge.
REASON_STATE = {
    "no_title": ("UNSUPPORTED_FORMAT", "recognition"),
    "no_header": ("UNSUPPORTED_FORMAT", "recognition"),
    "header_order_mismatch": ("UNSUPPORTED_FORMAT", "recognition"),
    "rotated_page": ("UNSUPPORTED_FORMAT", "precondition"),
    "no_rows": ("UNSUPPORTED_FORMAT", "recognition"),
    "time_invalid": ("RECOGNISED_BUT_FAILED", "read"),
    "column_mismatch": ("RECOGNISED_BUT_FAILED", "read"),
    "row_count_mismatch": ("RECOGNISED_BUT_FAILED", "validate"),
    "trailing_line": ("RECOGNISED_BUT_FAILED", "read"),
    "elapsed_mismatch": ("RECOGNISED_BUT_FAILED", "validate"),
    "x_unmapped": ("RECOGNISED_BUT_FAILED", "validate"),
    "word_mismatch": ("RECOGNISED_BUT_FAILED", "validate"),
    "docling_extent_mismatch": ("RECOGNISED_BUT_FAILED", "merge"),
    "ambiguous_docling_match": ("RECOGNISED_BUT_FAILED", "merge"),
    "docling_multipage": ("RECOGNISED_BUT_FAILED", "merge"),
    "header_not_adjacent": ("UNSUPPORTED_FORMAT", "recognition"),
    "header_labels_missing": ("UNSUPPORTED_FORMAT", "recognition"),
    "header_extra_labels": ("UNSUPPORTED_FORMAT", "recognition"),
    "text_layer_read_error": ("PARSING_FAILURE", "runtime"),
    "rule_exception": ("PARSING_FAILURE", "runtime"),
    "merge_exception": ("PARSING_FAILURE", "runtime"),
}
# Annotation kinds that say the printout is missing records (the number in group 1 is the count of missing records).
PARTIAL_KINDS = frozenset({"records_not_printed"})


def state_of_reason(reason: str) -> str:
    """The state a reason code stands for; an unknown code is a programming error, not a state."""
    try:
        return REASON_STATE[reason][0]
    except (KeyError, TypeError):
        raise ValueError(f"unknown reason code {reason!r}") from None


def page_lines(layer: dict) -> list[dict]:
    """Text-layer words grouped by visual row (the ``row`` ids of ``source_page``), each row left to right."""
    rows: dict[int, list[dict]] = {}
    for word in layer["words"]:
        rows.setdefault(word["row"], []).append(word)
    return [{"words": sorted(words, key=lambda w: (w["bbox"][0], w["bbox"][1])),
             "top": min(w["bbox"][1] for w in words), "bottom": max(w["bbox"][3] for w in words)}
            for _, words in sorted(rows.items())]


def height(word: dict) -> float:
    return word["bbox"][3] - word["bbox"][1]


def em(words: list[dict]) -> float:
    """The text height of a set of words: the median of their box heights."""
    return median(height(word) for word in words)


def gap(first: dict, second: dict) -> float:
    """Horizontal distance between two word boxes; zero when they touch or overlap."""
    return max(0.0, second["bbox"][0] - first["bbox"][2], first["bbox"][0] - second["bbox"][2])


def normalise(text: str) -> str:
    """Lower case without anything but letters and digits: how a printed header word is compared with a label."""
    return re.sub(r"[^0-9a-z]", "", text.lower())


def title_phrase_pattern(rule: dict) -> str:
    """A regular expression for the title words next to each other in plain page text (each word escaped)."""
    return r"\s+".join(re.escape(word) for word in rule["schema"]["title_words"])


def classify_annotation(text: str, side: str, rule: dict) -> dict:
    """Name an annotation by the first configured kind that matches; any other text stays ``unclassified``.

    The kinds only label the text, they never decide whether a title is accepted. The count is read with ``int`` only
    when group 1 is made of digits, so a pattern that matches something else can not raise at run time.
    """
    for kind in rule["schema"]["annotation_kinds"]:
        found = re.search(kind["pattern"], text, re.IGNORECASE)
        if not found:
            continue
        digits = found.group(1) if found.re.groups >= 1 else None
        if digits is not None and re.fullmatch(r"\d+", digits):
            return {"text": text, "side": side, "kind": kind["kind"], "count": int(digits)}
        break
    return {"text": text, "side": side, "kind": "unclassified", "count": None}


def completeness(annotations: list[dict]) -> str | None:
    """``partial_in_source`` > ``unclassified_annotation`` > ``None`` (a count of zero says nothing is missing)."""
    if any(a["kind"] in PARTIAL_KINDS and a["count"] and a["count"] > 0 for a in annotations):
        return "partial_in_source"
    if any(a["kind"] == "unclassified" for a in annotations):
        return "unclassified_annotation"
    return None


def title_candidates(words: list[dict], rule: dict) -> tuple[list[int], float]:
    """(start indexes of title phrases, em_title). A phrase is the two title words next to each other, no word between
    them, at most ``phrase_gap_em_title`` apart. ``em_title`` is the median height of the (first) pair of title words."""
    first, second = rule["schema"]["title_words"]
    limit = rule["recognition"]["phrase_gap_em_title"]
    starts, em_title = [], None
    for i in range(len(words) - 1):
        if words[i]["text"] == first and words[i + 1]["text"] == second:
            size = em([words[i], words[i + 1]])
            if gap(words[i], words[i + 1]) <= limit * size:
                starts.append(i)
            if em_title is None:
                em_title = size
    if em_title is None:  # a mention line without adjacent title words: take the first pair in order
        a = next(i for i, w in enumerate(words) if w["text"] == first)
        b = next(i for i in range(a + 1, len(words)) if words[i]["text"] == second)
        em_title = em([words[a], words[b]])
    return starts, em_title


def rejected(at: int, detail: str, evidence: dict) -> dict:
    return {"line": at, "passed": False, "reason": "no_title", "detail": detail,
            "evidence": dict(evidence, decision="rejected", rejected_at="G1"), "annotations": []}


def mention_lines(layer: dict, rule: dict, lines: list[dict] | None = None) -> list[dict]:
    """One result per *mention line* of the page, top to bottom: ``line`` (index in ``page_lines``), ``passed`` (gate G1),
    ``reason`` (``no_title`` when not passed), ``detail``, ``evidence`` and ``annotations``.

    A mention line has the first title word and, somewhere after it on the same line, the second one. A line with only one
    of them (a header that contains "Operations", a "Management Summary" title) is not a mention. G1 checks, in this
    order, and the first violation is the reason: ``not_found`` (no title phrase), ``multiple_title_phrases``,
    ``embedded_in_text`` (a word within ``phrase_gap_em_title`` of the phrase), ``ambiguous_gap`` (nearest other word
    closer than ``annotation_min_gap_em_title``) and ``annotation_too_long`` (more than ``annotation_max_tokens`` other
    words). Title words are compared case-sensitively; the distances are in ``em_title``.
    """
    lines = page_lines(layer) if lines is None else lines
    first, second = rule["schema"]["title_words"]
    recognition = rule["recognition"]
    results = []
    for at, line in enumerate(lines):
        words = line["words"]
        texts = [word["text"] for word in words]
        if first not in texts or second not in texts[texts.index(first) + 1:]:
            continue
        starts, em_title = title_candidates(words, rule)
        evidence = {"title": {"em_pt": round(em_title, 3), "phrase_gap_em": None,
                              "nearest_gap_em": {"left": None, "right": None}, "annotation_tokens": 0}}
        if not starts:
            results.append(rejected(at, "not_found", evidence))
            continue
        if len(starts) > 1:
            results.append(rejected(at, "multiple_title_phrases", evidence))
            continue
        i = starts[0]
        phrase = (words[i], words[i + 1])
        em_title = em(list(phrase))
        left, right = words[:i], words[i + 2:]
        phrase_box = {"bbox": [phrase[0]["bbox"][0], 0, phrase[1]["bbox"][2], 0]}
        nearest = {side: (min(gap(word, phrase_box) for word in group) / em_title if group else None)
                   for side, group in (("left", left), ("right", right))}
        title = {"em_pt": round(em_title, 3), "phrase_gap_em": round(gap(*phrase) / em_title, 3),
                 "nearest_gap_em": {side: None if value is None else round(value, 3) for side, value in nearest.items()},
                 "annotation_tokens": len(left) + len(right)}
        evidence = {"title": title}
        closest = min((value for value in nearest.values() if value is not None), default=None)
        if closest is not None and closest <= recognition["phrase_gap_em_title"]:
            results.append(rejected(at, "embedded_in_text", evidence))
        elif closest is not None and closest < recognition["annotation_min_gap_em_title"]:
            results.append(rejected(at, "ambiguous_gap", evidence))
        elif len(left) + len(right) > recognition["annotation_max_tokens"]:
            results.append(rejected(at, "annotation_too_long", evidence))
        else:
            annotations = [classify_annotation(" ".join(word["text"] for word in group), side, rule)
                           for side, group in (("left", left), ("right", right)) if group]
            results.append({"line": at, "passed": True, "reason": None, "detail": "", "evidence": evidence,
                            "annotations": annotations})
    return results


def above_flag(lines: list[dict], at: int, rule: dict, em_header: float) -> list[dict]:
    """A hint, never a decision: the line right above the title is on its own line (so G1 did not see it) and is entirely
    an annotation of a configured kind. It may belong to the table above, so the owner is marked ``uncertain``."""
    if at == 0:
        return []
    above = lines[at - 1]
    if lines[at]["top"] - above["bottom"] > rule["tolerances"]["line_gap_em_header"] * em_header:
        return []
    found = classify_annotation(" ".join(word["text"] for word in above["words"]), "above", rule)
    if found["kind"] == "unclassified":
        return []
    return [dict(found, owner="uncertain")]


def label_matches(words: list[dict], label: str) -> list[tuple[int, int]]:
    """(first, last) word indexes of every run of consecutive words whose normalised text joins up to the label."""
    target, found = normalise(label), []
    for start in range(len(words)):
        joined = ""
        for end in range(start, len(words)):
            joined += normalise(words[end]["text"])
            if joined == target:
                found.append((start, end))
                break
            if not target.startswith(joined):
                break
    return found


def union_box(words: list[dict]) -> list[float]:
    return [min(w["bbox"][0] for w in words), min(w["bbox"][1] for w in words),
            max(w["bbox"][2] for w in words), max(w["bbox"][3] for w in words)]


def recognise_header(lines: list[dict], at: int, rule: dict) -> dict:
    """Gate G2: the line right under the title ``lines[at]`` holds the schema labels, in order and left to right.

    ``ok`` is true with ``boxes`` (one box per column label), ``em`` (``em_header``, the median word height of the header
    line) and ``line`` (its index), or false with ``reason`` and ``detail``. The step order is fixed: no line under the
    title (``no_header``); a line farther than ``title_header_gap_em_header`` (``header_not_adjacent``); no label at all
    (``no_header``); missing labels (``header_labels_missing``); labels in another order or overlapping in x
    (``header_order_mismatch``); extra words or repeated labels (``header_extra_labels``). ``em_header`` of the distance
    test is the median word height of the line right under the title, whether or not it turns out to be a header.
    """
    labels = [column["label"] for column in rule["schema"]["columns"]]
    if at + 1 >= len(lines):
        return {"ok": False, "reason": "no_header", "detail": "title_is_last_line", "evidence": {"gap_em": None}}
    line = lines[at + 1]
    words = line["words"]
    size = em(words)
    distance = (line["top"] - lines[at]["bottom"]) / size
    header = {"labels_matched": [], "x_monotone": None, "gap_em": round(distance, 3)}
    if distance > rule["recognition"]["title_header_gap_em_header"]:
        return {"ok": False, "reason": "header_not_adjacent", "detail": f"{distance:.2f} em_header", "evidence": header}
    runs = [label_matches(words, label) for label in labels]
    present = [index for index, found in enumerate(runs) if found]
    header["labels_matched"] = [labels[index] for index in present]
    if not present:
        return {"ok": False, "reason": "no_header", "detail": "next_row_is_not_header", "evidence": header}
    if len(present) < len(labels):
        missing = [label for index, label in enumerate(labels) if index not in present]
        return {"ok": False, "reason": "header_labels_missing", "detail": "missing " + ", ".join(missing), "evidence": header}
    starts = [found[0][0] for found in runs]
    if starts != sorted(starts):
        return {"ok": False, "reason": "header_order_mismatch", "detail": "labels in another order", "evidence": header}
    boxes = [union_box(words[found[0][0]:found[0][1] + 1]) for found in runs]
    header["x_monotone"] = all(boxes[k][0] >= boxes[k - 1][2] for k in range(1, len(boxes)))
    if not header["x_monotone"]:
        return {"ok": False, "reason": "header_order_mismatch", "detail": "x_not_monotone", "evidence": header}
    covered = {index for found in runs for first, last in found[:1] for index in range(first, last + 1)}
    if any(len(found) > 1 for found in runs) or len(covered) != len(words):
        extra = [words[index]["text"] for index in range(len(words)) if index not in covered]
        return {"ok": False, "reason": "header_extra_labels", "detail": "extra " + (" ".join(extra) or "repeated label"),
                "evidence": header}
    return {"ok": True, "boxes": boxes, "em": size, "line": at + 1, "evidence": header}


def zones_from_header(boxes: list[list[float]], rule: dict) -> dict[str, float]:
    """Column anchors from the printed header boxes of this page (the row grammar is time, time, hours, depth, code,
    text, mark): boundaries halfway between the labels of neighbouring columns, the end of the Code zone a fraction of
    the Code label width past it, and the span of the mark column label."""
    middle = lambda a, b: (boxes[a][2] + boxes[b][0]) / 2  # noqa: E731 - halfway across the gap between two labels
    extension = rule["tolerances"]["code_zone_extension"]
    return {"left": boxes[0][0], "from_to": middle(0, 1), "to_elapsed": middle(1, 2), "elapsed_depth": middle(2, 3),
            "depth_code": middle(3, 4), "code_limit": boxes[4][2] + extension * (boxes[4][2] - boxes[4][0]),
            "non_prod_left": boxes[6][0], "non_prod_right": boxes[6][2]}


def first_row_gate(lines: list[dict], header_at: int, rule: dict, em_header: float) -> dict:
    """Gate G3: the line right under the header is close to it and starts with two time tokens."""
    if header_at + 1 >= len(lines):
        return {"ok": False, "reason": "no_rows", "detail": "", "evidence": {"first_row_gap_em": None, "time_tokens": 0}}
    line = lines[header_at + 1]
    distance = (line["top"] - lines[header_at]["bottom"]) / em_header
    pattern = re.compile(rule["schema"]["patterns"]["time"])
    tokens = line["words"]
    times = len(tokens) >= 2 and all(pattern.match(word["text"]) for word in tokens[:2])
    evidence = {"first_row_gap_em": round(distance, 3), "time_tokens": 2 if times else 0}
    if not times or distance > rule["tolerances"]["line_gap_em_header"]:
        return {"ok": False, "reason": "no_rows", "detail": "", "evidence": evidence}
    return {"ok": True, "evidence": evidence}


def build_evidence(title: dict, header: dict | None, rows: dict | None, decision: str, rejected_at: str | None,
                   rule: dict) -> dict:
    """The evidence record for the sidecar: the gates' measurements and the margin to each threshold (in em). The margins
    are for reading only. Keys are in a fixed order so the sidecar is deterministic."""
    recognition, tolerances = rule["recognition"], rule["tolerances"]
    title = title or {}
    nearest = [value for value in title.get("nearest_gap_em", {}).values() if value is not None]
    phrase = title.get("phrase_gap_em")
    margins = {
        "phrase_gap_em": None if phrase is None else round(recognition["phrase_gap_em_title"] - phrase, 3),
        "annotation_gap_em": round(min(nearest) - recognition["annotation_min_gap_em_title"], 3) if nearest else None,
        "title_header_gap_em": None if not header or header.get("gap_em") is None
        else round(recognition["title_header_gap_em_header"] - header["gap_em"], 3),
        "first_row_gap_em": None if not rows or rows.get("first_row_gap_em") is None
        else round(tolerances["line_gap_em_header"] - rows["first_row_gap_em"], 3)}
    return {"decision": decision, "rejected_at": rejected_at, "title": title, "header": header, "rows": rows,
            "margins": margins}
