"""Synthetic text layers for the Operations Summary tests (shared by several test modules; contains no test).

A layer is built from lines: ``(top, [(text, left, right[, height]), ...])``. The optional fourth value is the height of
the word box (default 9.0 pt). ``layer(lines, scale=...)`` multiplies the page size, every coordinate, the glyph widths
and the text height, so a scaled page is the same page printed smaller or larger.
"""
from __future__ import annotations

import copy

from graph_builder.corpus import ops_tables as ops
from graph_builder.corpus.k1_config import load_k1_config

OPS_RULE = load_k1_config()["table_rules"]["operations_summary"]
HEADER_LABELS = [column["label"] for column in OPS_RULE["schema"]["columns"]]
TITLE = (251.0, [("Operations", 261, 308), ("Summary", 310, 351)])
HEADER = (263.2, [("From", 48, 68), ("To", 89, 99), ("Elapsed", 115, 146), ("End", 154, 169), ("MD(ft", 171, 192),
                  ("Code", 208, 228), ("Operations", 342, 384), ("Description", 386, 430), ("Non-Prod", 537, 573)])
# Title and header with the text heights of the real daily reports (title 10.0 pt, header 8.9 pt), where em_title
# differs from em_header, so a gate that measures with the wrong one gives a different answer.
TITLE_REAL = (221.2, [("Operations", 260.5, 308.0, 10.0), ("Summary", 310.5, 351.5, 10.0)])
HEADER_REAL = (221.2 + 12.2, [(text, left, right, 8.9) for text, left, right in HEADER[1]])


def rule_copy() -> dict:
    """A private copy of the shipped rule, for tests that change a setting."""
    return copy.deepcopy(OPS_RULE)


def read_page(page: dict, rule: dict | None = None) -> list[dict]:
    return ops.read_page(page, OPS_RULE if rule is None else rule)


def words(text, left=244.0, width=6.0):
    """Description words laid out from ``left`` with a fixed width per character."""
    result, x = [], left
    for word in text.split():
        result.append((word, x, x + width * len(word)))
        x += width * len(word) + 4
    return result


def data(top, start, end, elapsed, depth, code, description, mark=False):
    spec = [(start, 55, 71), (end, 91, 107), (elapsed, 132, 147), (depth, 188, 192)]
    spec += [(code, 199, 219)] if code else []
    spec += description
    spec += [("X", 565, 570)] if mark else []
    return (top, spec)


def continuation(top, description, mark=False):
    return (top, description + ([("X", 565, 570)] if mark else []))


def layer(lines, rotation=0, scale=1.0):
    """A text layer like ``source_page``: one word row per line and one glyph per character."""
    result_words, chars = [], []
    for row, (top, spec) in enumerate(lines):
        for item in spec:
            text, left, right = item[:3]
            size = item[3] if len(item) > 3 else 9.0
            box = [left * scale, top * scale, right * scale, (top + size) * scale]
            result_words.append({"text": text, "bbox": box, "row": row})
            step = (right - left) * scale / len(text)
            for i, char in enumerate(text):
                chars.append({"text": char, "bbox": [box[0] + i * step, box[1], box[0] + (i + 1) * step, box[3]],
                              "index": len(chars)})
    return {"page": 1, "width": 612 * scale, "height": 792 * scale, "rotation": rotation, "words": result_words,
            "chars": chars}


def good_page():
    """Title, header, three rows (one wrapped, two with a mark or code) and the "Management Summary" title below."""
    return [TITLE, HEADER,
            data(275.1, "0:00", "8:00", "8.00", "0", "WOD", words("Wait on daylight , morning meeting"), mark=True),
            data(287.1, "8:00", "15:00", "7.00", "0", "MOB", words("Fly drill loads to site and stage prior to")),
            continuation(296.3, words("camp, stores tent complete.")),
            data(308.3, "15:00", "0:00", "9.00", "120", "RIGU", words("Assemble rig")),
            (320.3, [("Management", 256, 311), ("Summary", 314, 355)])]


def title_line(left=None, right=None, top=221.2, title=TITLE_REAL):
    """The title row of a daily report, with an annotation ``(text, x)`` to the left and/or the right of the title, in
    the same row and in a smaller font (8.9 pt), as the reports print it."""
    spec = [(w, x, x + 4.4 * len(w), 8.9) for w, x in annotation_words(left)] if left else []
    spec += title[1]
    spec += [(w, x, x + 4.4 * len(w), 8.9) for w, x in annotation_words(right)] if right else []
    return (top, spec)


def real_page(left=None, right=None, title_top=221.2):
    """A page with the heights of the real reports (title 10.0, header 8.9, rows 8.9). The title row may carry an
    annotation to its left and/or right (see ``title_line``)."""
    shift = title_top - TITLE_REAL[0]
    title = title_line(left, right, title_top)
    header = (HEADER_REAL[0] + shift, HEADER_REAL[1])

    def row(top, *args, **kwargs):
        top_, spec = data(top + shift, *args, **kwargs)
        return top_, [(item[0], item[1], item[2], 8.9) for item in spec]

    return [title, header,
            row(246.0, "0:00", "8:00", "8.00", "0", "WOD", words("Wait on daylight"), mark=True),
            row(257.7, "8:00", "15:00", "7.00", "0", "MOB", words("Fly drill loads")),
            row(269.4, "15:00", "0:00", "9.00", "120", "RIGU", words("Assemble rig")),
            (281.4 + shift, [("Management", 256, 311, 10.0), ("Summary", 314, 355, 10.0)])]


def annotation_words(note):
    """``note = (text, left)`` as ``[(word, left), ...]`` with 4.4 pt per character and a 2.2 pt space."""
    text, left = note
    result = []
    for word in text.split():
        result.append((word, left))
        left += 4.4 * len(word) + 2.2
    return result
