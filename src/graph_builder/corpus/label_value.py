"""Re-attach the value of a label to its own label when the converter glued it to a neighbouring cell's label.

Optional step of chunking (``chunking.label_value``, default off). Docling sometimes builds one text item from the text
runs of two neighbouring cells of a ruled form: the right-aligned value of cell N ends up in the item of the label of
cell N+1 (``Days On Location: 1700`` where the page prints ``Proposed TD (ft): 1700`` and ``Days On Location: 1``).

The source PDF decides, never the converter output and never a language model:

* a cell is the rectangle between the vertical and horizontal vector rulings around a word (``forms.vertical`` and
  ``forms.horizontal``); a cell with exactly one colon-terminated label owns the words after the label;
* a text item is only examined when the PDF words inside its box (or, if the box is smaller than its text, the words of the
  text lines it touches, each token occurring exactly as often as in the item) spell exactly the item's tokens;
* a word that sits in the cell of another label is moved to the item of that label, and an item without any label whose
  words all lie in that cell is attached to the label (its own text becomes empty); nothing is added or dropped (the multiset
  of words of the affected items is the same before and after) and the text of a changed item is rebuilt from the PDF words:
  label words followed by the words of the cell, per label in reading order;
* whenever the evidence is not unambiguous (several labels in a cell, a label split over items, a token in a cell without a
  label, an unmapped target item) the original text of the whole group is kept and a finding with a reason is recorded.
  Pairs of items that are already consistent with the cells are never touched.

Only pages without rotation and with a text layer are examined. The result is a copy of the document plus a report
(counts, changes with PDF word boxes, abstentions with reasons).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .forms import find_labels, horizontal, vertical
from .text_layer import source_page

DEFAULTS: dict[str, Any] = {
    "min_label_cells": 4,                  # a page is only examined when it has this many cells with exactly one label
    "box_expansions_pt": [0.5, 1.5, 3.0],  # item box growth tried in order when mapping PDF words to a text item
    "page_size_tolerance_pt": 1.0,
    "max_findings": 2000,                  # per document and list; counts stay exact
    "item_labels": ["text", "list_item", "checkbox_selected", "checkbox_unselected", "paragraph"],
    # C-01c, all three off by default (the output of ``{}`` is the one of C-01R, byte for byte except the report's settings):
    "split_label_cells": False,            # a single-row cell with several labels is read as one sub-cell per label (value = words up to the next label)
    "rebuild_item_order": False,           # an item whose words are those of its label cells in another order is rebuilt in cell order
    "review_unverified": False,            # report items with a value of another label in an ambiguous cell and mark the chunks of every abstention quality "review"
    "review_reasons": None,                # None = every abstention reason marks its chunks; else only the listed reasons
}


def label_value_settings(value: Any) -> dict[str, Any]:
    """Validate the optional ``chunking.label_value`` object and fill in the defaults."""
    if not isinstance(value, dict) or not set(value) <= set(DEFAULTS):
        raise ValueError(f"chunking.label_value must be an object with keys from {sorted(DEFAULTS)}")
    settings = {**DEFAULTS, **value}
    if type(settings["min_label_cells"]) is not int or settings["min_label_cells"] < 1:
        raise ValueError("label_value.min_label_cells must be a positive integer")
    ladder = settings["box_expansions_pt"]
    if (not isinstance(ladder, list) or not ladder or any(type(v) not in (int, float) or not 0 <= v <= 10 for v in ladder)):
        raise ValueError("label_value.box_expansions_pt must be a non-empty list of numbers between 0 and 10")
    if type(settings["page_size_tolerance_pt"]) not in (int, float) or settings["page_size_tolerance_pt"] < 0:
        raise ValueError("label_value.page_size_tolerance_pt must be nonnegative")
    if type(settings["max_findings"]) is not int or settings["max_findings"] < 1:
        raise ValueError("label_value.max_findings must be a positive integer")
    for name in ("split_label_cells", "rebuild_item_order", "review_unverified"):
        if type(settings[name]) is not bool:
            raise ValueError(f"label_value.{name} must be true or false")
    reasons = settings["review_reasons"]
    if reasons is not None and (not isinstance(reasons, list) or not reasons or any(not isinstance(v, str) or not v for v in reasons)):
        raise ValueError("label_value.review_reasons must be null or a non-empty list of abstention reasons")
    labels = settings["item_labels"]
    if not isinstance(labels, list) or not labels or any(not isinstance(v, str) or not v for v in labels):
        raise ValueError("label_value.item_labels must be a non-empty list of Docling labels")
    return settings


def empty_report(settings: dict[str, Any]) -> dict[str, Any]:
    return {"method": "cell_geometry_v1", "settings": settings, "pages_examined": 0, "pages_supported": 0,
            "pages_skipped": {}, "items_not_examined": {}, "items_with_label_examined": 0, "items_with_colon_unmapped": 0, "items_changed": 0, "groups_changed": 0, "groups_abstained": 0, "words_moved": 0,
            "changes": [], "abstentions": []}


def _round(box: list[float]) -> list[float]:
    return [round(v, 2) for v in box]


def _center(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _cell_of(layer: dict, word: dict) -> tuple[float, float, float, float]:
    cx, cy = _center(word["bbox"])
    edges = vertical(layer, cy)
    left = max((v for v in edges if v <= cx), default=0.0)
    right = min((v for v in edges if v > cx), default=layer["width"])
    top, bottom = horizontal(layer, cx, cy)
    return (round(left, 1), round(top, 1), round(right, 1), round(bottom, 1))


def _split_cell(words: list[dict], indices: list[int], found: list[tuple[int, list[int]]]) -> list[dict] | None:
    """Sub-cells of a cell with several labels, or None when the cell is not a single row that starts with a label.

    Sub-cell n holds label n and the words after it up to the next label (the last one up to the end of the cell): the order
    "label, then its value" of a form row. A cell with words before its first label, on several rows or with labels that are
    not in reading order is left ambiguous."""
    if len({words[i]["row"] for i in indices}) != 1:
        return None
    starts = [indices.index(label[0]) if label[0] in indices else -1 for _, label in found]
    if -1 in starts or starts[0] != 0 or starts != sorted(set(starts)):
        return None
    parts = []
    for n, (_, label) in enumerate(found):
        members = indices[starts[n]:starts[n + 1] if n + 1 < len(starts) else len(indices)]
        if members[:len(label)] != label:
            return None
        parts.append({"words": members, "state": "label", "label": label, "values": members[len(label):], "reason": None, "split": True})
    return parts


def read_cells(layer: dict, split: bool = False) -> tuple[list[tuple], dict[tuple, dict[str, Any]]]:
    """Cell of every word and, per cell, its words in reading order and its label state.

    State ``label``: exactly one colon-terminated label that starts the cell; its words are ``label`` and the rest
    ``values``. State ``none``: no label. State ``ambiguous``: several labels, words before the label, or a label
    that continues on another row; ``reason`` says which. With ``split`` a single-row cell that starts with several
    labels becomes one ``label`` sub-cell per label (key = cell key + (n,), ``split`` true).
    """
    words = layer["words"]
    keys = [_cell_of(layer, word) for word in words]
    members: dict[tuple, list[int]] = {}
    for index, key in enumerate(keys):
        members.setdefault(key, []).append(index)
    cells: dict[tuple, dict[str, Any]] = {}
    for key, indices in members.items():
        indices.sort(key=lambda i: (words[i]["row"], words[i]["bbox"][0]))
        info: dict[str, Any] = {"words": indices, "state": "none", "label": [], "values": indices, "reason": None}
        found = []
        for row in dict.fromkeys(words[i]["row"] for i in indices):
            in_row = [i for i in indices if words[i]["row"] == row]
            for label in find_labels([words[i] for i in in_row], None):
                found.append((row, [in_row[n] for n in label["indices"]]))
        info["labels"] = [label for _, label in found]
        if len(found) > 1:
            info.update(state="ambiguous", reason="cell_multiple_labels")
            parts = _split_cell(words, indices, found) if split else None
            if parts:
                for n, part in enumerate(parts):
                    cells[key + (n,)] = part
                    for i in part["words"]:
                        keys[i] = key + (n,)
                continue
        elif found:
            row, label = found[0]
            if label[0] != indices[0]:
                info.update(state="ambiguous", reason="words_before_label")
            else:
                info.update(state="label", label=label, values=[i for i in indices if i not in label])
        cells[key] = info
    return keys, cells


def _tokens(text: str) -> list[str]:
    return text.split()


def _map_items(layer: dict, items: list[dict], ladder: list[float]) -> None:
    """Attach to every item the PDF words inside its box when they spell the item's characters; else ``unmapped``."""
    words = layer["words"]
    for item in items:
        item["words"], item["status"] = [], "unmapped"
        wanted = Counter("".join(_tokens(item["text"])))
        for grow in ladder:
            inside = [i for i, word in enumerate(words)
                      if any(left - grow <= _center(word["bbox"])[0] <= right + grow and top - grow <= _center(word["bbox"])[1] <= bottom + grow
                             for left, top, right, bottom in item.get("boxes", [item["box"]]))]
            if inside and Counter("".join(words[i]["text"] for i in inside)) == wanted:
                item["words"], item["status"] = inside, "mapped"
                break
        if item["status"] == "mapped":
            continue
        # The converter's box can be smaller than the text it holds (a cell of the next column in the same line). Fall back to the
        # text lines the box touches: accepted only when every word of the item occurs in them exactly as often as in the item.
        top, bottom = item["box"][1], item["box"][3]
        band = [i for i, word in enumerate(words) if top - ladder[-1] <= _center(word["bbox"])[1] <= bottom + ladder[-1]]
        need, have = Counter(_tokens(item["text"])), Counter(words[i]["text"] for i in band)
        if need and all(have[token] == count for token, count in need.items()):
            item["words"], item["status"] = [i for i in band if words[i]["text"] in need], "mapped"
    claims = Counter(i for item in items if item["status"] == "mapped" for i in item["words"])
    for item in items:
        if item["status"] == "mapped" and any(claims[i] > 1 for i in item["words"]):
            item["status"] = "overlap"


def _first_order_difference(item: dict, cells: dict, words: list[dict]) -> str | None:
    """First token where the item's word order is not "label, then the item's words of that cell" per label cell in reading order
    (None when it is, or when the words of the item are not exactly those of its label cells)."""
    tokens = _tokens(item["text"])
    inside = set(item["words"])
    canonical: list[str] = []
    for key in sorted(item["own"], key=lambda k: (words[cells[k]["label"][0]]["row"], words[cells[k]["label"][0]]["bbox"][0])):
        cell = cells[key]
        values = sorted((i for i in cell["words"] if i in inside and i not in cell["label"]), key=lambda i: (words[i]["row"], words[i]["bbox"][0]))
        canonical += [words[i]["text"] for i in cell["label"] + values]
    if canonical == tokens or sorted(canonical) != sorted(tokens):
        return None
    return next(token for token, expected in zip(tokens, canonical) if token != expected)


def _abstain(report: dict, page: int, reason: str, items: list[dict], **extra: Any) -> None:
    report["groups_abstained"] += 1
    if len(report["abstentions"]) < report["settings"]["max_findings"]:
        report["abstentions"].append({"page": page, "reason": reason, "items": [item["ref"] for item in items],
                                      "texts": [item["text"] for item in items], **extra})


def analyse_page(layer: dict, items: list[dict], settings: dict[str, Any], report: dict[str, Any]) -> list[dict]:
    """Decide the corrections of one page. ``items``: dicts with ref, text, box (top-left PDF points). Returns the
    accepted rewrites ``{ref, text, box, ...}``; abstentions and statistics go to ``report``."""
    page = layer["page"]
    words = layer["words"]
    keys, cells = read_cells(layer, bool(settings.get("split_label_cells")))
    # sub-cells made by split_label_cells do not count: the set of examined pages stays the one of the unsplit reading
    if sum(cell["state"] == "label" and not cell.get("split") for cell in cells.values()) < settings["min_label_cells"]:
        report["pages_skipped"]["few_label_cells"] = report["pages_skipped"].get("few_label_cells", 0) + 1
        return []
    report["pages_supported"] += 1
    _map_items(layer, items, settings["box_expansions_pt"])
    mapped = [item for item in items if item["status"] == "mapped"]
    label_cell_of_words: dict[int, tuple] = {}
    for key, cell in cells.items():
        if cell["state"] == "label":
            for index in cell["label"]:
                label_cell_of_words[index] = key
    # which item holds the complete label of a cell
    holder: dict[tuple, list[dict]] = {}
    for item in mapped:
        inside = set(item["words"])
        for key, cell in cells.items():
            if cell["state"] == "label" and set(cell["label"]) <= inside:
                holder.setdefault(key, []).append(item)
    for item in mapped:
        inside = set(item["words"])
        item["own"] = [key for key, cell in cells.items() if cell["state"] == "label" and set(cell["label"]) <= inside]
        item["partial"] = [key for key, cell in cells.items() if cell["state"] == "label" and set(cell["label"]) & inside
                           and not set(cell["label"]) <= inside]
        # cells whose labels cannot be told apart but whose label-like words (ending in a colon) are inside this item
        item["amb"] = [key for key, cell in cells.items() if cell["state"] == "ambiguous"
                       and any(words[i]["text"].endswith(":") for i in cell["words"] if i in inside)]
    report["items_with_colon_unmapped"] += sum(item["status"] != "mapped" and ":" in item["text"] for item in items)
    report["items_with_label_examined"] += sum(bool(item["own"] or item["partial"] or item["amb"]) for item in mapped)
    # An item with a label-like word (ending in a colon) that cannot be tied to the PDF words is left alone, and says so.
    for item in items:
        if item["status"] != "mapped" and any(token.endswith(":") for token in _tokens(item["text"])):
            _abstain(report, page, f"label_item_{item['status']}", [item])
    orphans = [item for item in mapped if not (item["own"] or item["partial"] or item["amb"]) and item["words"]]
    moves: list[tuple[int, dict, dict]] = []  # (word index, from item, to item)
    problems: dict[int, list[dict]] = {}      # id(item) -> unresolved findings
    for item in mapped:
        if not item["own"] and not item["partial"] and not item["amb"]:
            continue  # value-only or label-less item: nothing to attach
        for index in item["words"]:
            key = keys[index]
            if key in item["own"] or key in item["amb"]:
                continue
            cell = cells[key]
            if cell["state"] == "label" and index in cell["label"] and key in item["partial"]:
                problems.setdefault(id(item), []).append({"reason": "label_split_over_items", "word": words[index]["text"]})
            elif cell["state"] == "label":
                targets = holder.get(key, [])
                if len(targets) == 1 and targets[0] is not item:
                    moves.append((index, item, targets[0]))
                else:
                    problems.setdefault(id(item), []).append({"reason": "target_item_unmapped" if not targets else "target_item_ambiguous",
                                                              "word": words[index]["text"]})
            elif cell["state"] == "ambiguous":
                problems.setdefault(id(item), []).append({"reason": cell["reason"], "word": words[index]["text"]})
            else:
                problems.setdefault(id(item), []).append({"reason": "token_in_unlabelled_cell", "word": words[index]["text"]})
    # An item that no move touches keeps its text, but its words may still be in another order than the cells (labels first, then
    # the values: ``Wear: Brgs: Gge: A`` for the cells ``Wear: A | Brgs: 0 | Gge: 0``). Not rebuilt, flagged.
    touched = {id(source) for _, source, _ in moves} | {id(target) for _, _, target in moves}
    reorder: set[int] = set()  # rebuild_item_order: items whose only defect is the word order (their group is rebuilt, values attached)
    for item in mapped:
        if item["own"] and not item["partial"] and not item["amb"] and id(item) not in touched and id(item) not in problems:
            differs = _first_order_difference(item, cells, words)
            if differs is not None:
                if settings.get("rebuild_item_order"):
                    reorder.add(id(item))
                else:
                    problems[id(item)] = [{"reason": "item_order_differs_from_cells", "word": differs}]

    def value_of_another_label(item: dict) -> str | None:
        """First word of the item that, in an ambiguous cell, follows a label (reading order) which is not in the item: the item then
        shows that word next to other words than its own label. An item that holds every label its words follow is not reported."""
        inside = set(item["words"])
        for key in item["amb"]:
            cell = cells[key]
            groups = {label[0]: set(label) for label in cell.get("labels", [])}
            marked = {i for label in groups.values() for i in label}
            governing = None
            for index in cell["words"]:
                if index in groups:
                    governing = groups[index]
                elif index not in marked and index in inside and governing is not None and not governing & inside:
                    return words[index]["text"]
        return None

    def flag_unresolved(covered: set[int]) -> None:
        """review_unverified: an item in an ambiguous cell that no finding covers and that carries the value of another label would be silent."""
        if settings.get("review_unverified"):
            for item in mapped:
                if item["amb"] and id(item) not in covered:
                    word = value_of_another_label(item)
                    if word is not None:
                        _abstain(report, page, "ambiguous_cell_unresolved", [item], details=[{"reason": "value_of_another_label", "word": word}])

    if not moves and not problems and not reorder:
        flag_unresolved(set())
        return []
    # groups = connected items of the moves; an item with a problem and no move forms its own group
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_id = {id(item): item for item in mapped}
    for _, source, target in moves:
        parent[find(id(source))] = find(id(target))
    for item_id in list(problems) + sorted(reorder):
        find(item_id)
    groups: dict[int, list[dict]] = {}
    for item_id in sorted(parent, key=lambda i: by_id[i]["order"]):
        groups.setdefault(find(item_id), []).append(by_id[item_id])
    accepted: list[dict] = []
    cell_group = {cell_key: group_id for group_id, members in groups.items() for member in members for cell_key in member["own"]}
    for group_id, members in groups.items():
        ids = {id(m) for m in members}
        group_moves = [m for m in moves if id(m[1]) in ids or id(m[2]) in ids]
        # Words of an item without any label that lie in the cell of a label of this group are that label's value (a value the
        # converter kept in a separate item, possibly together with the text of a neighbouring cell): attach them, so the right value
        # ends up next to its label. An item that reaches into the cells of several groups is left alone.
        held = {cell_key: member for member in members for cell_key in member["own"]}
        attached = set()
        for orphan in orphans:
            if id(orphan) in parent:
                continue
            in_cells = [i for i in orphan["words"] if keys[i] in held]
            touched = {cell_group[keys[i]] for i in orphan["words"] if keys[i] in cell_group}
            if in_cells and touched == {group_id}:
                attached.add(id(orphan))
                members.append(orphan)
                group_moves += [(i, orphan, held[keys[i]]) for i in in_cells]
        reasons = [dict(p, item=m["ref"]) for m in members for p in problems.get(id(m), [])]
        if reasons:
            _abstain(report, page, reasons[0]["reason"], members, details=reasons[:6])
            continue
        outcome = _rewrite_group(layer, members, group_moves, cells, keys, attached)
        if isinstance(outcome, str):
            _abstain(report, page, outcome, members)
            continue
        accepted.extend(outcome)
        report["groups_changed"] += 1
        report["items_changed"] += len(outcome)
        report["words_moved"] += len(group_moves)
    flag_unresolved(set(parent))
    return accepted


def _rewrite_group(layer: dict, members: list[dict], moves: list[tuple[int, dict, dict]], cells: dict, keys: list,
                   attached: set[int]) -> list[dict] | str:
    """New text and box of the items of one group, or the reason why the group is left alone.

    The text of an item is rebuilt from the PDF words: for each label cell it holds (in reading order) the label words followed by
    the words of that cell. An attached value-only item ends up empty. Every word is accounted for before and after."""
    words = layer["words"]
    out: dict[int, set[int]] = {id(m): set() for m in members}
    into: dict[int, set[int]] = {id(m): set() for m in members}
    for index, source, target in moves:
        out[id(source)].add(index)
        into[id(target)].add(index)
    before = Counter()
    after = Counter()
    result = []
    for item in members:
        tokens = _tokens(item["text"])
        if sorted(tokens) != sorted(words[i]["text"] for i in item["words"]):
            return "tokenization_mismatch"
        before.update(tokens)
        if id(item) in attached:
            rest = [i for i in item["words"] if i not in out[id(item)]]
            reading = sorted(item["words"], key=lambda i: (words[i]["row"], words[i]["bbox"][0]))
            if rest and [words[i]["text"] for i in reading] != tokens:
                return "value_item_order"  # the remaining words would be re-ordered: not certain enough
            rest = sorted(rest, key=lambda i: (words[i]["row"], words[i]["bbox"][0]))
            after.update(words[i]["text"] for i in rest)
            result.append({"ref": item["ref"], "old": item["text"], "text": " ".join(words[i]["text"] for i in rest),
                           "box": _union([words[i]["bbox"] for i in rest]) if rest else item["box"], "label": "", "label_box": None,
                           "moved_out": [{"text": words[i]["text"], "box": _round(words[i]["bbox"])} for i in sorted(out[id(item)])],
                           "moved_in": [], "page": layer["page"]})
            continue
        if item["amb"]:
            return cells[item["amb"][0]]["reason"]
        if not item["own"] or item["partial"]:
            return "label_split_over_items"
        kept = {i for i in item["words"] if i not in out[id(item)]} | into[id(item)]
        new_tokens: list[str] = []
        used: list[int] = []
        label_words: list[int] = []
        for key in sorted(item["own"], key=lambda k: (words[cells[k]["label"][0]]["row"], words[cells[k]["label"][0]]["bbox"][0])):
            cell = cells[key]
            values = sorted((i for i in kept if keys[i] == key and i not in cell["label"]), key=lambda i: (words[i]["row"], words[i]["bbox"][0]))
            new_tokens += [words[i]["text"] for i in cell["label"] + values]
            used += cell["label"] + values
            label_words += cell["label"]
        if set(used) != kept:
            return "word_outside_label_cells"
        after.update(new_tokens)
        left, top = min(words[i]["bbox"][0] for i in used), min(words[i]["bbox"][1] for i in used)
        right, bottom = max(words[i]["bbox"][2] for i in used), max(words[i]["bbox"][3] for i in used)
        result.append({"ref": item["ref"], "old": item["text"], "text": " ".join(new_tokens), "box": [left, top, right, bottom],
                       "label": " ".join(words[i]["text"] for i in label_words), "label_box": _round(_union([words[i]["bbox"] for i in label_words])),
                       "moved_out": [{"text": words[i]["text"], "box": _round(words[i]["bbox"])} for i in sorted(out[id(item)])],
                       "moved_in": [{"text": words[i]["text"], "box": _round(words[i]["bbox"])} for i in sorted(into[id(item)])],
                       "page": layer["page"]})
    if before != after:
        return "words_not_conserved"
    return [r for r in result if r["text"] != " ".join(_tokens(r["old"]))] or "no_net_change"

def _union(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def correct_document(doc: Any, source: Path | None, settings: dict[str, Any], ocr_pages: set[int],
                     excluded: frozenset[str] = frozenset()) -> tuple[Any, dict[str, Any]]:
    """Return (document, report). The document is a copy only when something changed; nothing is written to ``source``."""
    from docling_core.types.doc import BoundingBox, CoordOrigin, TextItem
    import pypdfium2 as pdfium
    report = empty_report(settings)
    if source is None:
        report["error"] = "no_source_pdf"
        return doc, report
    wanted = set(settings["item_labels"])
    by_page: dict[int, list[dict]] = {}
    skipped = report["items_not_examined"]
    for order, item in enumerate(doc.texts):
        label = getattr(item.label, "value", str(item.label))
        if not isinstance(item, TextItem) or label not in wanted or not item.text.strip() or item.self_ref in excluded:
            continue
        if not item.prov or any(prov.bbox is None for prov in item.prov):
            skipped["no_box"] = skipped.get("no_box", 0) + 1
            continue
        page_no = item.prov[0].page_no
        if any(prov.page_no != page_no for prov in item.prov):
            skipped["spans_pages"] = skipped.get("spans_pages", 0) + 1
            continue
        page = doc.pages.get(page_no)
        if page is None:
            continue
        boxes = []
        for prov in item.prov:  # one box per text run the converter merged into this item
            box = prov.bbox.to_top_left_origin(page_height=page.size.height)
            boxes.append([box.l, box.t, box.r, box.b])
        by_page.setdefault(page_no, []).append({"ref": item.self_ref, "text": item.text, "order": order, "boxes": boxes,
                                               "box": _union(boxes)})
    by_page = {page_no: page_items for page_no, page_items in by_page.items() if any(":" in item["text"] for item in page_items)}
    rewrites: dict[str, dict] = {}
    try:
        pdf = pdfium.PdfDocument(source)
    except Exception as error:  # unreadable source: keep every text, say why
        report["error"] = f"{type(error).__name__}: {error}"[:300]
        return doc, report
    try:
        for page_no in sorted(by_page):
            skip = None
            try:
                if page_no in ocr_pages:
                    skip = "ocr_page"
                elif pdf[page_no - 1].get_rotation() != 0:
                    skip = "rotated_page"
                if skip is None:
                    layer = source_page(source, page_no)
                    size = doc.pages[page_no].size
                    tolerance = settings["page_size_tolerance_pt"]
                    if abs(layer["width"] - size.width) > tolerance or abs(layer["height"] - size.height) > tolerance:
                        skip = "page_size_mismatch"
            except Exception as error:
                skip = "page_error"
                report.setdefault("errors", []).append({"page": page_no, "error": f"{type(error).__name__}: {error}"[:200]})
            report["pages_examined"] += 1
            if skip:
                report["pages_skipped"][skip] = report["pages_skipped"].get(skip, 0) + 1
                continue
            try:
                for rewrite in analyse_page(layer, by_page[page_no], settings, report):
                    rewrites[rewrite["ref"]] = rewrite
            except Exception as error:  # one page never loses the others
                report["pages_skipped"]["page_error"] = report["pages_skipped"].get("page_error", 0) + 1
                report.setdefault("errors", []).append({"page": page_no, "error": f"{type(error).__name__}: {error}"[:200]})
    finally:
        pdf.close()
    if not rewrites:
        return doc, report
    doc = doc.model_copy(deep=True)
    for item in doc.texts:
        rewrite = rewrites.get(item.self_ref)
        if rewrite is None:
            continue
        height = doc.pages[item.prov[0].page_no].size.height
        left, top, right, bottom = rewrite["box"]
        box = BoundingBox(l=left, t=top, r=right, b=bottom, coord_origin=CoordOrigin.TOPLEFT)
        if item.prov[0].bbox.coord_origin == CoordOrigin.BOTTOMLEFT:
            box = box.to_bottom_left_origin(page_height=height)
        item.text = rewrite["text"]
        item.prov = item.prov[:1]  # the text was rebuilt from the PDF words: one run, one box
        item.prov[0].bbox = box
        item.prov[0].charspan = (0, len(rewrite["text"]))
        if len(report["changes"]) < settings["max_findings"]:
            report["changes"].append({key: rewrite[key] for key in ("page", "ref", "old", "text", "label", "label_box", "moved_out", "moved_in")}
                                     | {"box": _round(rewrite["box"])})
    return doc, report


def unverified_chunks(chunks: list[dict], report: dict[str, Any], reasons: list[str] | None = None) -> tuple[set[int], dict[str, Any]]:
    """Indices of the chunks that hold an item the label-value step looked at and left unverified (``review_unverified``), and statistics.

    The consumer of a K1 package sees only the chunks, so every abstention of the report (reason, page, item texts) is mapped to the chunks of
    its page whose text contains the item text (items with a colon-terminated word; value-only items of the group are not searched: their
    label item is). An abstention whose item cannot be found in any chunk of its page marks every chunk of that page; a report whose list
    was cut at ``max_findings`` marks every chunk of the document. Nothing is added to the text."""
    abstentions = report.get("abstentions") or []
    total = report.get("groups_abstained", 0)
    if reasons is not None:  # only these reasons mark chunks; a cut list is still detected against the exact count
        stats_skipped = sum(a["reason"] not in reasons for a in abstentions)
        abstentions, total = [a for a in abstentions if a["reason"] in reasons], total - stats_skipped
    stats = {"abstained_groups": total, "listed": len(abstentions), "chunks": 0, "groups_marked_by_page": 0, "list_truncated": total > len(abstentions)}
    if stats["list_truncated"]:
        stats["chunks"] = len(chunks)
        return set(range(len(chunks))), stats
    flat = [" ".join(chunk["text"].split()) for chunk in chunks]
    marked: set[int] = set()
    for abstention in abstentions:
        texts = [" ".join(text.split()) for text in abstention["texts"]]
        texts = [t for t in texts if any(token.endswith(":") for token in t.split())] or [t for t in texts if t]
        found = {i for i, chunk in enumerate(chunks) if abstention["page"] in chunk["pages"] and any(t in flat[i] for t in texts)}
        if not found:
            found = {i for i, chunk in enumerate(chunks) if abstention["page"] in chunk["pages"]}
            stats["groups_marked_by_page"] += 1
        marked |= found
    stats["chunks"] = len(marked)
    return marked, stats


def mark_unverified(chunks: list[dict], statistics: dict[str, Any], settings: dict[str, Any]) -> None:
    """``review_unverified``: set ``quality`` to "review" on the chunks that ``unverified_chunks`` returns and record the numbers in
    ``statistics["label_value"]["review"]``. Without the option, or without a report (not paginated, no source PDF), nothing changes."""
    report = statistics.get("label_value")
    if not settings.get("review_unverified") or not isinstance(report, dict) or "abstentions" not in report:
        return
    marked, report["review"] = unverified_chunks(chunks, report, settings.get("review_reasons"))
    for index in marked:
        chunks[index]["quality"] = "review"
