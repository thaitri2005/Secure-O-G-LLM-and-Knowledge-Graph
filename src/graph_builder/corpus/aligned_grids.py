"""Detect borderless measurement tables from repeated, separated word positions."""
from __future__ import annotations

from collections import Counter
from itertools import pairwise
import re
from statistics import median

from .column_alignment import comparison
from .numeric_cells import read_words
from .ruled_geometry import cell_slots, materialize_panel

QUANTITY = re.compile(r"[+−-]?(?:\d+(?:[.,:/]\d+)*|\.\d+)(?:\s*(?:%|[a-zµ°][a-zµ°0-9/%³².-]{0,11}))?", re.I)


def lines(words, height):
    rows = []
    for word in sorted(words, key=lambda w: (middle(w[1]), w[1][0])):
        y = middle(word[1])
        if not rows or y - rows[-1][0] > .45 * height:
            rows.append((y, []))
        rows[-1][1].append(word)
    return [(y, sorted(row, key=lambda w: w[1][0])) for y, row in rows]


def middle(box):
    return (box[1] + box[3]) / 2


def quantity_groups(row, height):
    groups = []
    for text, box in row:
        if groups and box[0] - groups[-1][-1][1][2] <= .55 * height:
            groups[-1].append((text, box))
        else:
            groups.append([(text, box)])
    if 2 <= len(groups) <= 20 and all(QUANTITY.fullmatch(" ".join(w[0] for w in group)) for group in groups):
        return groups
    return None


def runs(bands, height):
    current = []
    for index, (y, row) in enumerate(bands):
        groups = quantity_groups(row, height)
        if current and (groups is None or len(groups) != len(current[-1][2]) or y - current[-1][1] > 2.4 * height):
            yield current
            current = []
        if groups:
            current.append((index, y, groups))
    if current:
        yield current


def enclosing(row):
    return [min(box[0] for _, box in row), min(box[1] for _, box in row),
            max(box[2] for _, box in row), max(box[3] for _, box in row)]


def proposals(words):
    """Find a complete table block. Every body lane needs stable anchors and a white gutter."""
    if len(words) < 10:
        return
    height = median(max(1, box[3] - box[1]) for _, box in words)
    bands = lines(words, height)
    for run in runs(bands, height):
        index, first_y, _ = run[0]
        if len(run) < 4 or index == 0 or first_y - bands[index - 1][0] > 2.5 * height:
            continue
        columns = list(zip(*(groups for _, _, groups in run), strict=True))
        bounds = [[enclosing(group) for group in column] for column in columns]
        if any(min(max(edge) - min(edge) for edge in ([b[0] for b in lane], [b[2] for b in lane])) > .6 * height
               for lane in bounds):
            continue
        gaps = [(max(box[2] for box in left), min(box[0] for box in right)) for left, right in pairwise(bounds)]
        if any(right - left < .75 * height for left, right in gaps):
            continue
        cuts = [(left + right) / 2 for left, right in gaps]
        heading = bands[index - 1][1]
        labels = [[] for _ in columns]
        for word, box in heading:
            if any(box[0] + .15 * height < cut < box[2] - .15 * height for cut in cuts):
                break
            labels[sum(cut <= (box[0] + box[2]) / 2 for cut in cuts)].append((word, box))
        else:
            values = [" ".join(word for word, _ in label) for label in labels]
            if (len({comparison(value).casefold() for value in values}) != len(columns)
                    or any(not 1 <= len(label) <= 8 or not any(ch.isalpha() for ch in value)
                           for label, value in zip(labels, values, strict=True))):
                continue
            # Exclude a heading with an unrelated phrase far outside the data lanes.
            if any(enclosing(label)[2] < min(b[0] for b in lane) - height
                   or enclosing(label)[0] > max(b[2] for b in lane) + height
                   for label, lane in zip(labels, bounds, strict=True)):
                continue
            physical_rows = [heading, *(bands[i][1] for i, _, _ in run)]
            rectangle = enclosing([word for row in physical_rows for word in row])
            vertical = [enclosing(row) for row in physical_rows]
            if any(a[3] > b[1] + .4 * height for a, b in pairwise(vertical)):
                continue
            xs = [rectangle[0] - .25 * height, *cuts, rectangle[2] + .25 * height]
            ys = [rectangle[1] - .2 * height, *((a[3] + b[1]) / 2 for a, b in pairwise(vertical)),
                  rectangle[3] + .2 * height]
            yield xs, ys, physical_rows


def read_panels(words, independent):
    for xs, ys, rows in proposals(words):
        bbox = [xs[0], ys[0], xs[-1], ys[-1]]
        shape = cell_slots([(l, t, r, b) for t, b in pairwise(ys) for l, r in pairwise(xs)])
        if shape is None:
            continue

        def read_cell(box):
            text = read_words(words, box)
            return text if comparison(text) == comparison(read_words(independent, box)) else None

        panel = materialize_panel(shape, bbox, read_cell)
        if panel and all(all(row) for row in panel["grid"]) and (
                Counter(word for row in rows for word, _ in row) ==
                Counter(word for row in panel["grid"] for value in row for word in value.split())):
            yield panel
