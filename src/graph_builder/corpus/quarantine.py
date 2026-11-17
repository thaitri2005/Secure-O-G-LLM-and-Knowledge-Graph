"""Producer-side detection and quarantine of text whose correctness the converter output alone cannot guarantee.

Optional step of chunking (``chunking.quarantine``, default off; absent = the output is byte for byte what it was). It never rewrites,
drops or reorders text. It reads the source PDF (visible glyphs with their clip paths, word boxes, vector rulings; never a language
model) and records, per document, machine-readable findings in ``statistics["quarantine"]``:

* ``list_dropped_items``: every content-bearing item the filters leave out of the chunks (dotted-leader TOC lines/tables, index items, the
  parts of running lines), with page, reason and text, instead of the bare count in ``statistics["dropped"]``;
* ``list_page_status``: for every page the support status of the label-value reading (``grid_supported``, ``few_label_cells``,
  ``ocr_page``, ``rotated_page``, ``page_size_mismatch``, ``page_error``, ``no_text_items``), so an unexamined page is visible;
* ``scan_visibility``: a text item whose words are not (or only partly) visible in the PDF at the item's box, because the glyphs are
  outside the clip path of the cell that draws them. ``text_not_visible``: whole words clipped away (the item says something the page does
  not show, e.g. a label the form hides); informational (recorded, no chunk is marked unless ``review_reasons`` lists them):
  ``text_not_in_layer`` (words absent from the PDFium text layer, which can miss text another reader shows, e.g. form-field values),
  ``text_displaced`` (a word missing at the item's box but visible elsewhere on the page) and ``text_tail_clipped`` (the end of a
  visible word is clipped, ``Va`` shown for ``Valley``; the text is probably real);
* ``scan_value_before_label``: an item that starts with the value of the label to its left and ends with the label of the next cell
  (``Chris Hoffman Title:`` for the row ``Name: Chris Hoffman | Title: Owner``), found from word geometry only: a column gap inside the
  words in front of the first label, and a colon-terminated word, outside the item, directly to the left of those words.

Findings are warnings. With ``mark_review`` the chunks that hold a finding get ``quality`` "review" (an existing K1 v1 value): this is a
signal for whoever reads the field, not an isolation, because the consumers of a K1 package may ignore it. Nothing is added to the text.
"""
from __future__ import annotations

from collections import Counter
import re
from statistics import median
from typing import Any

from ..ingestion.filters import LEADER_RUN, TOC_LEADER
from .label_value import read_cells
from .text_layer import source_page

DEFAULTS: dict[str, Any] = {
    "list_dropped_items": False,      # statistics.quarantine.dropped_items: the content-bearing items the filters leave out, with text
    "list_page_status": False,        # statistics.quarantine.pages: support status of every page
    "scan_visibility": False,         # items with clipped / non-visible words
    "scan_value_before_label": False, # value glued in front of the next label
    "mark_review": False,             # chunks that hold a (non-informational) finding get quality "review"
    "review_reasons": None,           # None = every reason except the informational ones; else only the listed reasons
    "item_labels": ["text", "list_item", "checkbox_selected", "checkbox_unselected", "paragraph"],
    "box_grow_pt": 3.0,               # growth of an item box when collecting the visible words that belong to it
    "column_gap_factor": 1.5,         # a gap wider than this many text heights between two words of a row separates two cells
    "min_label_cells": 4,             # same meaning as label_value.min_label_cells (page status grid_supported / few_label_cells)
    "page_size_tolerance_pt": 1.0,
    "max_findings": 2000,             # per document and list; counts stay exact
    "max_text_chars": 300,            # text kept per dropped item / finding
    # P2-WP3, only read when scan_tables is true (and then echoed in the report); absent / false = the report is what it was
    "scan_tables": False,             # tables whose cells do not match the PDF geometry: table_cell_spans_blocks, table_geometry_inconsistent
    "table_region_grow_pt": 6.0,      # PDF words whose centre is within the table box grown by this many points belong to the table
    "table_min_found_share": 0.4,     # share of the table's tokens that must be found in that region, else the table is not examined
    "table_gap_factor": 3.0,          # a gap wider than this many text heights between two consecutive tokens of a cell on one line
    "table_cell_min_jumps": 2,        # reading-path jumps (up / back on the line / wide gap) that make a cell span separate blocks
    "table_min_testable": 8,          # cells with a unique PDF anchor and a neighbour in their column/row needed to judge the grid
    "table_max_geometry_ratio": 0.4,  # share of those cells that overlap no neighbour of their own column/row
}
TABLE_KEYS = ("scan_tables", "table_region_grow_pt", "table_min_found_share", "table_gap_factor", "table_cell_min_jumps", "table_min_testable",
              "table_max_geometry_ratio")
# Recorded, never mark chunks unless listed in review_reasons. text_not_in_layer is informational because the PDFium text layer used
# here can miss text that another reader shows (DEV: 48 of 55 findings were visible to MuPDF, the other 7 are a lone glyph).
INFORMATIONAL = frozenset({"text_tail_clipped", "text_displaced", "text_not_in_layer"})
MARKING_DEFAULT = ("text_not_visible", "value_before_label", "table_cell_spans_blocks", "table_geometry_inconsistent")
TABLE_REASONS = frozenset({"table_cell_spans_blocks", "table_geometry_inconsistent"})
CONTENT_DROP_REASONS = frozenset({"dotted_leader_toc", "dotted_leader_toc_table", "document_index", "document_index_child",
                                  "document_index_heading"})
BOOLEANS = ("list_dropped_items", "list_page_status", "scan_visibility", "scan_value_before_label", "mark_review", "scan_tables")


def quarantine_settings(value: Any) -> dict[str, Any]:
    """Validate the optional ``chunking.quarantine`` object and fill in the defaults."""
    if not isinstance(value, dict) or not set(value) <= set(DEFAULTS):
        raise ValueError(f"chunking.quarantine must be an object with keys from {sorted(DEFAULTS)}")
    settings = {**DEFAULTS, **value}
    for name in BOOLEANS:
        if type(settings[name]) is not bool:
            raise ValueError(f"quarantine.{name} must be true or false")
    for name in ("box_grow_pt", "column_gap_factor", "page_size_tolerance_pt"):
        if type(settings[name]) not in (int, float) or not 0 <= settings[name] <= 50:
            raise ValueError(f"quarantine.{name} must be a number between 0 and 50")
    for name in ("min_label_cells", "max_findings", "max_text_chars", "table_cell_min_jumps", "table_min_testable"):
        if type(settings[name]) is not int or settings[name] < 1:
            raise ValueError(f"quarantine.{name} must be a positive integer")
    for name in ("table_region_grow_pt", "table_gap_factor"):
        if type(settings[name]) not in (int, float) or not 0 <= settings[name] <= 50:
            raise ValueError(f"quarantine.{name} must be a number between 0 and 50")
    for name in ("table_min_found_share", "table_max_geometry_ratio"):
        if type(settings[name]) not in (int, float) or not 0 <= settings[name] <= 1:
            raise ValueError(f"quarantine.{name} must be a number between 0 and 1")
    reasons = settings["review_reasons"]
    if reasons is not None and (not isinstance(reasons, list) or not reasons or any(not isinstance(v, str) or not v for v in reasons)):
        raise ValueError("quarantine.review_reasons must be null or a non-empty list of finding reasons")
    labels = settings["item_labels"]
    if not isinstance(labels, list) or not labels or any(not isinstance(v, str) or not v for v in labels):
        raise ValueError("quarantine.item_labels must be a non-empty list of Docling labels")
    return settings


def empty_report(settings: dict[str, Any]) -> dict[str, Any]:
    if not settings["scan_tables"]:
        settings = {key: value for key, value in settings.items() if key not in TABLE_KEYS}  # report of a run without the table scan is unchanged
    return {"method": "pdf_geometry_quarantine_v1", "settings": settings, "pages_scanned": 0, "items_scanned": 0,
            "findings_total": 0, "findings_by_reason": {}, "findings": [], "pages": [], "pages_by_status": {}}


def _clip(text: str, settings: dict[str, Any]) -> str:
    return text if len(text) <= settings["max_text_chars"] else text[:settings["max_text_chars"]]


def _norm(token: str) -> str:
    return "".join(character for character in token if character.isalnum())


def _center(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def leader_info(text: str) -> dict[str, Any]:
    """Why a dotted-leader item was dropped: the longest dot run of its line-end leaders and whether a page number follows. An item with
    ``leader_dots`` below N and no page number is kept by ``filters.toc_leader_min_dots`` = N (a trailing ellipsis, not a table of contents)."""
    runs = [(len(LEADER_RUN.match(match.group(0)).group(0)), any(character.isdigit() for character in match.group(0)))
            for match in TOC_LEADER.finditer(text)]
    if not runs:
        return {"leader_dots": 0, "page_number_follows": False}
    return {"leader_dots": max(run for run, _ in runs), "page_number_follows": any(number for _, number in runs),
            "has_letters_or_digits": any(character.isalnum() for character in text)}


def dropped_items(original: Any, filtered: Any, exclusions: dict[str, str], settings: dict[str, Any]) -> dict[str, Any]:
    """Content-bearing items the filters leave out of the chunks: excluded items (``exclusions``) and text removed from items by the
    running-line filter (``original`` is the document before it, ``filtered`` after). Order: document order."""
    from docling_core.types.doc import TableItem
    listed: list[dict[str, Any]] = []
    counts: Counter = Counter()
    after = {item.self_ref: item.text for item in filtered.texts}
    for item in original.texts:
        reason = exclusions.get(item.self_ref)
        page = item.prov[0].page_no if getattr(item, "prov", None) else None
        if reason is None:
            kept = after.get(item.self_ref)
            if kept is not None and kept.strip() == item.text.strip():
                continue
            if not item.text.strip():
                continue
            counts["running_line"] += 1
            listed.append({"page": page, "ref": item.self_ref, "reason": "running_line", "text": _clip(item.text, settings),
                           "kept": _clip(kept or "", settings), "chars": len(item.text)})
        elif reason in CONTENT_DROP_REASONS and item.text.strip():
            counts[reason] += 1
            row = {"page": page, "ref": item.self_ref, "reason": reason, "text": _clip(item.text, settings), "chars": len(item.text)}
            if reason.startswith("dotted_leader"):
                row.update(leader_info(item.text))
            listed.append(row)
        elif item.text.strip():
            counts[reason] += 1
    for table in original.tables:
        reason = exclusions.get(table.self_ref)
        if reason in CONTENT_DROP_REASONS and isinstance(table, TableItem):
            text = " | ".join(cell.text for cell in table.data.table_cells if cell.text.strip())
            counts[reason] += 1
            listed.append({"page": table.prov[0].page_no if table.prov else None, "ref": table.self_ref, "reason": reason,
                           "text": _clip(text, settings), "chars": len(text)})
    listed.sort(key=lambda row: (row["page"] or 0, row["ref"]))
    return {"total": sum(counts.values()), "by_reason": dict(sorted(counts.items())),
            "listed": listed[:settings["max_findings"]], "truncated": len(listed) > settings["max_findings"]}


def visibility(text: str, visible: list[str], raw_tokens: frozenset[str], page_visible: frozenset[str] = frozenset()) -> dict[str, list[str]]:
    """Compare the words of a text item with the visible PDF words of its box (all compared on letters and digits only).

    ``whole``: words with no visible counterpart anywhere on the page that the PDF text layer has (clipped away, shown nowhere);
    ``elsewhere``: words with no counterpart in the box but visible somewhere else on the page (the converter's box does not sit on its
    words, or the word repeats); ``absent``: words with no counterpart that the text layer does not have either; ``tail``: words whose
    visible counterpart is a proper prefix of them (end clipped). Words the item and the page spell with another segmentation (the
    missing letters are among the unmatched visible letters) count as visible."""
    need = Counter(token for token in map(_norm, text.split()) if token)
    have = Counter(token for token in map(_norm, visible) if token)
    missing = need - have
    pool = list((have - need).elements())
    tail, rest = [], []
    for token in sorted(missing.elements()):
        remaining, used = token, []
        while remaining:  # the token read as consecutive visible words (another segmentation), the last piece possibly cut short
            match = next((word for word in pool if word not in used or pool.count(word) > used.count(word)
                          if remaining.startswith(word)), None)
            if match is None:
                break
            used.append(match)
            remaining = remaining[len(match):]
        for word in used:
            pool.remove(word)
        if used and not remaining:
            continue  # same letters, spelled with another segmentation
        if used and remaining:
            tail.append(token)  # visible start, clipped end
        else:
            rest.append(token)
    if rest and not Counter("".join(rest)) - Counter("".join(pool)):
        rest = []
    clipped = [t for t in rest if t in raw_tokens]
    return {"tail": tail, "whole": [t for t in clipped if t not in page_visible], "elsewhere": [t for t in clipped if t in page_visible],
            "absent": [t for t in rest if t not in raw_tokens]}


def _value_before_label(layer: dict, inside: list[int], factor: float) -> dict[str, Any] | None:
    """Geometry test (see module docstring): the first row of the item's words has a colon-terminated word after a column gap, and a
    colon-terminated word outside the item sits directly to the left of the words in front of that gap."""
    words = layer["words"]
    if not inside:
        return None
    # the first line of the item: the words that overlap vertically with its top-most, left-most word (the extractor's row ids
    # follow the glyph centres and can differ between a label and its value on the same printed line)
    top = min(inside, key=lambda i: (round(words[i]["bbox"][1]), words[i]["bbox"][0]))

    def same_line(i: int) -> bool:
        a, b = words[i]["bbox"], words[top]["bbox"]
        return min(a[3], b[3]) - max(a[1], b[1]) >= 0.5 * min(a[3] - a[1], b[3] - b[1])
    line = sorted((i for i in inside if same_line(i)), key=lambda i: words[i]["bbox"][0])
    label_at = next((n for n, i in enumerate(line) if words[i]["text"].endswith(":")), None)
    if label_at is None or label_at == 0:
        return None
    height = max(words[i]["bbox"][3] - words[i]["bbox"][1] for i in line)
    head = line[:label_at + 1]
    gaps = [(n, words[head[n]]["bbox"][0] - words[head[n - 1]]["bbox"][2]) for n in range(1, len(head))]
    wide = [n for n, gap in gaps if gap > factor * height]
    if not wide:
        return None
    cut = wide[-1]  # the label phrase starts after the last column gap in front of the first colon
    prefix = head[:cut]
    first = words[prefix[0]]["bbox"]
    members = set(inside)
    neighbours = [j for j, word in enumerate(words) if j not in members and same_line(j) and word["bbox"][2] <= first[0] + 1.0]
    if not neighbours:
        return None
    previous = max(neighbours, key=lambda j: words[j]["bbox"][2])
    if not words[previous]["text"].endswith(":") or first[0] - words[previous]["bbox"][2] > factor * height:
        return None
    return {"value_words": [words[i]["text"] for i in prefix], "label": " ".join(words[i]["text"] for i in head[cut:]),
            "previous_label": words[previous]["text"], "column_gap_pt": round(dict(gaps)[cut], 1),
            "box": [round(v, 2) for v in first]}


def scan_document(doc: Any, source: Any, settings: dict[str, Any], ocr_pages: set[int], excluded: frozenset[str],
                  claimed: frozenset[str], report: dict[str, Any]) -> None:
    """Scan the text items of a paginated document. ``claimed``: refs that label_value already changed or reported (not reported twice)."""
    from docling_core.types.doc import TextItem
    import pypdfium2 as pdfium
    wanted = set(settings["item_labels"])
    by_page: dict[int, list[dict]] = {}
    for item in doc.texts:
        label = getattr(item.label, "value", str(item.label))
        if not isinstance(item, TextItem) or label not in wanted or not item.text.strip() or item.self_ref in excluded:
            continue
        if not item.prov or any(prov.bbox is None for prov in item.prov) or len({prov.page_no for prov in item.prov}) > 1:
            continue
        page_no = item.prov[0].page_no
        page = doc.pages.get(page_no)
        if page is None:
            continue
        boxes = []
        for prov in item.prov:
            box = prov.bbox.to_top_left_origin(page_height=page.size.height)
            boxes.append([box.l, box.t, box.r, box.b])
        by_page.setdefault(page_no, []).append({"ref": item.self_ref, "text": item.text, "boxes": boxes})
    want_layer = settings["scan_visibility"] or settings["scan_value_before_label"] or settings["list_page_status"]
    pdf = None
    if want_layer and source is not None:
        try:
            pdf = pdfium.PdfDocument(source)
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"[:300]
    try:
        for page_no in sorted(doc.pages):
            items = by_page.get(page_no, [])
            colon_items = sum(":" in item["text"] for item in items)
            status, layer = None, None
            if not items:
                status = "no_text_items"
            elif pdf is None:
                status = "no_source"
            elif page_no in ocr_pages:
                status = "ocr_page"
            else:
                try:
                    if pdf[page_no - 1].get_rotation() != 0:
                        status = "rotated_page"
                    else:
                        layer = source_page(source, page_no)
                        size = doc.pages[page_no].size
                        tolerance = settings["page_size_tolerance_pt"]
                        if abs(layer["width"] - size.width) > tolerance or abs(layer["height"] - size.height) > tolerance:
                            status, layer = "page_size_mismatch", None
                except Exception as error:
                    status, layer = "page_error", None
                    report.setdefault("errors", []).append({"page": page_no, "error": f"{type(error).__name__}: {error}"[:200]})
            if layer is not None:
                _scan_page(layer, items, settings, claimed, report)
                cells = read_cells(layer)[1]
                status = ("grid_supported" if sum(cell["state"] == "label" for cell in cells.values()) >= settings["min_label_cells"]
                          else "few_label_cells")
                report["pages_scanned"] += 1
            report["pages_by_status"][status] = report["pages_by_status"].get(status, 0) + 1
            if settings["list_page_status"]:
                report["pages"].append({"page": page_no, "status": status, "colon_items": colon_items})
    finally:
        if pdf is not None:
            pdf.close()


def _scan_page(layer: dict, items: list[dict], settings: dict[str, Any], claimed: frozenset[str], report: dict[str, Any]) -> None:
    words = layer["words"]
    raw = frozenset(token for token in map(_norm, layer["text"].split()) if token)  # every glyph of the text layer, clipped ones included
    page_visible = frozenset(token for token in map(_norm, (word["text"] for word in words)) if token)
    grow = settings["box_grow_pt"]
    for item in items:
        report["items_scanned"] += 1
        inside = [i for i, word in enumerate(words)
                  if any(l - grow <= _center(word["bbox"])[0] <= r + grow and t - grow <= _center(word["bbox"])[1] <= b + grow
                         for l, t, r, b in item["boxes"])]
        found: list[tuple[str, dict]] = []
        if settings["scan_visibility"]:
            result = visibility(item["text"], [words[i]["text"] for i in inside], raw, page_visible)
            for reason, key in (("text_not_visible", "whole"), ("text_not_in_layer", "absent"), ("text_displaced", "elsewhere"),
                                ("text_tail_clipped", "tail")):
                if result[key]:
                    found.append((reason, {"words": result[key][:8], "visible_words": len(inside)}))
        if settings["scan_value_before_label"] and item["ref"] not in claimed:
            vbl = _value_before_label(layer, inside, settings["column_gap_factor"])
            if vbl is not None:
                found.append(("value_before_label", vbl))
        for reason, details in found:
            report["findings_total"] += 1
            report["findings_by_reason"][reason] = report["findings_by_reason"].get(reason, 0) + 1
            if len(report["findings"]) < settings["max_findings"]:
                report["findings"].append({"page": layer["page"], "reason": reason, "item": item["ref"],
                                           "text": _clip(item["text"], settings), "details": details})


_TOKEN = re.compile(r"[^\W\d_]+|\d+(?:[.,:/\-]\d+)*")


def _tokens(text: str | None) -> list[str]:
    """Alphabetic runs and numeric runs, lower case: independent of how a reader cuts words."""
    return [match.group().lower() for match in _TOKEN.finditer(text or "")]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


def table_geometry(cells: list[dict], words: list[tuple[list[str], list[float]]], settings: dict[str, Any]) -> dict[str, Any]:
    """Compare the cells of one table with the PDF words of its region (pure function; ``words``: [(tokens, box)]).

    A token that occurs once among the cells and once among the words has a known place on the page (an anchor). Two tests use anchors only:

    * ``spans_blocks``: the anchors of one cell, in the order of the cell text, must follow the reading path of the page: a later token
      is not a line above, not left of the previous one on the same line, and not across a wide gap on the same line when the two tokens
      are neighbours in the cell. ``table_cell_min_jumps`` such jumps = the cell joins text of separate blocks (labels and values of
      different cells, header words of several columns, two tables).
    * ``inconsistent``: a cell with an anchor must overlap in x at least one other anchored cell of its own column (in y: of its own row);
      if more than ``table_max_geometry_ratio`` of the testable cells overlap none, the grid does not follow the page.
    """
    owners: dict[str, list[tuple[int, int]]] = {}
    for index, cell in enumerate(cells):
        for position, token in enumerate(_tokens(cell.get("text"))):
            owners.setdefault(token, []).append((index, position))
    where: dict[str, list[list[float]]] = {}
    for tokens, box in words:
        for token in tokens:
            where.setdefault(token, []).append(box)
    anchors: dict[int, list[tuple[int, list[float]]]] = {}
    for token, own in owners.items():
        if len(own) == 1 and len(where.get(token, [])) == 1:
            anchors.setdefault(own[0][0], []).append((own[0][1], where[token][0]))
    jumpy = []
    for index, found in anchors.items():
        found.sort(key=lambda pair: pair[0])
        path: list[tuple[int, list[float]]] = []
        for position, box in found:
            if not path or box != path[-1][1]:
                path.append((position, box))
        if len(path) < 3:
            continue
        height = median(box[3] - box[1] for _, box in path) or 1.0
        jumps = 0
        for (before, a), (after, b) in zip(path, path[1:]):
            dy = (b[1] + b[3]) / 2 - (a[1] + a[3]) / 2
            gap = b[0] - a[2]
            if dy < -height:
                jumps += 1
            elif abs(dy) <= 0.6 * height and gap < -2.0 * height:
                jumps += 1
            elif after - before == 1 and abs(dy) <= 0.6 * height and gap > settings["table_gap_factor"] * height:
                jumps += 1
        if jumps >= settings["table_cell_min_jumps"]:
            jumpy.append({"r": cells[index]["r"], "c": cells[index]["c"], "jumps": jumps, "anchors": len(path), "text": cells[index].get("text") or ""})
        if jumps:
            anchors[index] = []  # a cell that mixes blocks has no single place: not used for the grid test
    boxes = {index: [min(b[0] for _, b in found), min(b[1] for _, b in found), max(b[2] for _, b in found), max(b[3] for _, b in found)]
             for index, found in anchors.items() if found}
    columns: dict[int, list[tuple[int, list[float]]]] = {}
    rows: dict[int, list[tuple[int, list[float]]]] = {}
    for index, box in boxes.items():
        cell = cells[index]
        if (cell.get("col_span") or 1) == 1:
            columns.setdefault(cell["c"], []).append((index, box))
        if (cell.get("row_span") or 1) == 1:
            rows.setdefault(cell["r"], []).append((index, box))
    testable = flagged = 0
    for groups, low, high in ((columns, 0, 2), (rows, 1, 3)):
        for members in groups.values():
            for index, box in members:
                others = [other for j, other in members if j != index]
                if not others:
                    continue
                testable += 1
                if not any(_overlap(box[low], box[high], other[low], other[high]) > 0.5 for other in others):
                    flagged += 1
    return {"anchored_cells": len(boxes), "jumpy_cells": jumpy, "testable": testable, "unmatched": flagged,
            "ratio": round(flagged / testable, 3) if testable else 0.0}


def scan_tables(tables: list[dict], doc: Any, source: Any, ocr_pages: set[int], settings: dict[str, Any], report: dict[str, Any]) -> None:
    """``scan_tables``: examine every table record of the document against the PDF text layer (see ``table_geometry``) and add the
    findings ``table_cell_spans_blocks`` / ``table_geometry_inconsistent`` (with ``table_id``, ``source_ref`` and the region) to the
    report. Tables that cannot be judged are counted with the reason in ``report["tables"]["not_examined"]``; none is silently skipped.
    Pages with /Rotate 270 are read in the upright frame; other rotations, OCR pages and tables with little text layer are not examined."""
    import pypdfium2 as pdfium
    summary = report["tables"] = {"method": "table_geometry_v1", "tables": len(tables), "examined": 0, "flagged": 0, "not_examined": {}}

    def skip(reason: str) -> None:
        summary["not_examined"][reason] = summary["not_examined"].get(reason, 0) + 1

    if source is None:
        summary["skipped"] = "no_source"
        return
    try:
        pdf = pdfium.PdfDocument(source)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"[:300]
        summary["skipped"] = "source_unreadable"
        return
    layers: dict[tuple[int, bool], dict] = {}
    grow, tolerance = settings["table_region_grow_pt"], settings["page_size_tolerance_pt"]
    try:
        for table in tables:
            regions = table.get("regions") or []
            if not regions:
                skip("no_region")
                continue
            if {region["page"] for region in regions} & ocr_pages:
                skip("ocr_page")
                continue
            words: list[tuple[list[str], list[float]]] = []
            reason = None
            for region in regions:
                page_no = region["page"]
                try:
                    rotation = pdf[page_no - 1].get_rotation()
                    if rotation not in (0, 270):
                        reason = "rotated_page"
                        break
                    key = (page_no, rotation == 270)
                    if key not in layers:
                        layers[key] = source_page(source, page_no, upright=rotation == 270)
                    layer = layers[key]
                    size = doc.pages[page_no].size
                    box = list(region["bbox"])
                    if rotation == 0:
                        if abs(layer["width"] - size.width) > tolerance or abs(layer["height"] - size.height) > tolerance:
                            reason = "page_size_mismatch"
                            break
                    elif abs(size.width - layer["height"]) <= tolerance and abs(size.height - layer["width"]) <= tolerance:
                        box = [layer["width"] - box[3], box[0], layer["width"] - box[1], box[2]]  # displayed frame -> upright frame
                    elif abs(size.width - layer["width"]) > tolerance or abs(size.height - layer["height"]) > tolerance:
                        reason = "page_size_mismatch"
                        break
                except Exception as error:
                    report.setdefault("errors", []).append({"table": table["table_id"], "error": f"{type(error).__name__}: {error}"[:200]})
                    reason = "page_error"
                    break
                for word in layer["words"]:
                    cx, cy = _center(word["bbox"])
                    tokens = _tokens(word["text"])
                    if tokens and box[0] - grow <= cx <= box[2] + grow and box[1] - grow <= cy <= box[3] + grow:
                        words.append((tokens, word["bbox"]))
            if reason is None:
                cells = table["cells"]
                k1 = Counter(token for cell in cells for token in _tokens(cell.get("text")))
                present = Counter(token for tokens, _ in words for token in tokens)
                total = sum(k1.values())
                if not words or (total and sum(min(count, present.get(token, 0)) for token, count in k1.items()) / total < settings["table_min_found_share"]):
                    reason = "little_text_layer_in_region"
            if reason is not None:
                skip(reason)
                continue
            summary["examined"] += 1
            result = table_geometry(table["cells"], words, settings)
            found = []
            if result["jumpy_cells"]:
                found.append(("table_cell_spans_blocks", {"cells": [{key: _clip(str(cell[key]), settings) if key == "text" else cell[key] for key in
                                                                       ("r", "c", "jumps", "anchors", "text")} for cell in result["jumpy_cells"][:10]],
                                                          "cells_total": len(result["jumpy_cells"])}))
            if result["testable"] >= settings["table_min_testable"] and result["ratio"] >= settings["table_max_geometry_ratio"]:
                found.append(("table_geometry_inconsistent", {"testable": result["testable"], "unmatched": result["unmatched"], "ratio": result["ratio"]}))
            if found:
                summary["flagged"] += 1
            first = next((cell["text"] for cell in table["cells"] if (cell.get("text") or "").strip()), "")
            for finding_reason, details in found:
                report["findings_total"] += 1
                report["findings_by_reason"][finding_reason] = report["findings_by_reason"].get(finding_reason, 0) + 1
                if len(report["findings"]) < settings["max_findings"]:
                    report["findings"].append({"page": regions[0]["page"], "reason": finding_reason, "item": table["source_ref"], "table_id": table["table_id"],
                                               "source_ref": table["source_ref"], "region": regions[0]["bbox"], "text": _clip(first, settings), "details": details})
    finally:
        pdf.close()


def chunk_reasons(chunks: list[dict], report: dict[str, Any], reasons: set[str] | None = None) -> tuple[dict[int, list[str]], dict[str, Any]]:
    """Map findings (and unexamined pages) to chunk indices: {index: sorted reason codes}, plus statistics.

    A finding belongs to the chunks of its page whose text contains the item text; if none does, to every chunk of the page (counted).
    Unexamined pages (status not ``grid_supported`` / ``no_text_items`` and with colon items) add ``page_unexamined:<status>`` to the
    chunks of that page. ``reasons`` restricts the finding reasons (default: all)."""
    flat = [" ".join(chunk["text"].split()) for chunk in chunks]
    mapping: dict[int, set[str]] = {}
    stats = {"findings": 0, "mapped_by_text": 0, "mapped_by_page": 0, "unmapped": 0, "list_truncated": report.get("findings_total", 0) > len(report.get("findings", []))}
    for finding in report.get("findings", []):
        if reasons is not None and finding["reason"] not in reasons:
            continue
        stats["findings"] += 1
        if finding.get("table_id"):
            # a table finding belongs to the chunks of that table (exact), never to the text chunks of its page
            found = {i for i, chunk in enumerate(chunks) if chunk.get("table_id") == finding["table_id"]}
            stats["mapped_by_table" if found else "unmapped"] = stats.get("mapped_by_table" if found else "unmapped", 0) + 1
            for i in found:
                mapping.setdefault(i, set()).add(finding["reason"])
            continue
        text = " ".join(finding["text"].split())
        found = {i for i, chunk in enumerate(chunks) if finding["page"] in chunk["pages"] and text in flat[i]}
        if found:
            stats["mapped_by_text"] += 1
        else:
            found = {i for i, chunk in enumerate(chunks) if finding["page"] in chunk["pages"]}
            stats["mapped_by_page" if found else "unmapped"] += 1
        for i in found:
            mapping.setdefault(i, set()).add(finding["reason"])
    for page in report.get("pages", []):
        if page["status"] not in ("grid_supported", "no_text_items") and page["colon_items"]:
            for i, chunk in enumerate(chunks):
                if page["page"] in chunk["pages"]:
                    mapping.setdefault(i, set()).add(f"page_unexamined:{page['status']}")
    return {i: sorted(v) for i, v in mapping.items()}, stats


REASON_CLASS = {"text_not_visible": "hidden_text", "text_not_in_layer": "hidden_text", "text_tail_clipped": "hidden_text", "text_displaced": "hidden_text",
                "value_before_label": "value_before_label", "table_cell_spans_blocks": "table_association",
                "table_geometry_inconsistent": "table_association"}


def chunk_sidecar(statistics: dict[str, Any], chunks: list[dict], table_owners: dict[str, tuple[str, str]] | None = None) -> dict[str, Any]:
    """The join of a K1 package for a consumer: {chunk_id: [{"reason", "class", "source"}]} over the text chunks, built from the
    quarantine findings, the unexamined pages and (when label_value ran) every label-value abstention. Nothing here changes a chunk;
    it lives outside the package (like the label_value sidecar)."""
    from .label_value import unverified_chunks
    texts = [(i, chunk) for i, chunk in enumerate(chunks) if chunk["type"] == "text"]
    view = [chunk for _, chunk in texts]
    entries: dict[str, list[dict[str, str]]] = {}
    summary: dict[str, Any] = {}

    def add(index: int, reason: str, kind: str, source: str) -> None:
        row = {"reason": reason, "class": kind, "source": source}
        bucket = entries.setdefault(chunks[texts[index][0]]["chunk_id"], [])
        if row not in bucket:
            bucket.append(row)

    report = statistics.get("quarantine")
    if isinstance(report, dict) and "findings" in report:
        text_report = report
        table_findings = [f for f in report["findings"] if f.get("table_id")]
        if table_findings:
            text_report = {**report, "findings": [f for f in report["findings"] if not f.get("table_id")]}
        mapping, stats = chunk_reasons(view, text_report, None)
        summary["quarantine"] = stats
        if table_findings:
            # table findings join the table chunks of the K1 table that still has the scanned source (a table rebuilt later is not the one scanned)
            joined = replaced = 0
            for finding in table_findings:
                owner = (table_owners or {}).get(finding["table_id"])
                if owner is None or owner[1] != finding["source_ref"]:
                    replaced += 1
                    continue
                hits = [chunk for chunk in chunks if chunk["type"] == "table" and chunk.get("table_id") == owner[0]
                        and (len(owner) < 3 or chunk["chunk_id"] in owner[2])]  # a joined table: only the chunks of the scanned part
                for chunk in hits:
                    row = {"reason": finding["reason"], "class": REASON_CLASS.get(finding["reason"], "quarantine"), "source": "quarantine"}
                    bucket = entries.setdefault(chunk["chunk_id"], [])
                    if row not in bucket:
                        bucket.append(row)
                joined += bool(hits)
            summary["quarantine_tables"] = {"findings": len(table_findings), "joined": joined, "not_joined": len(table_findings) - joined,
                                            "table_replaced_or_unknown": replaced}
        for index, codes in mapping.items():
            for code in codes:
                if code.startswith("page_unexamined:"):
                    add(index, code, "unexamined_page", "quarantine")
                else:
                    add(index, code, REASON_CLASS.get(code, "quarantine"), "quarantine")
    lv = statistics.get("label_value")
    if isinstance(lv, dict) and lv.get("abstentions"):
        reasons = sorted({a["reason"] for a in lv["abstentions"]})
        summary["label_value"] = {}
        for reason in reasons:
            marked, stats = unverified_chunks(view, lv, [reason])
            summary["label_value"][reason] = {"chunks": len(marked), "by_page": stats["groups_marked_by_page"], "list_truncated": stats["list_truncated"]}
            for index in marked:
                add(index, reason, "label_value_abstention", "label_value")
    elif isinstance(lv, dict):
        summary["label_value"] = {}
    for rows in entries.values():
        rows.sort(key=lambda r: (r["source"], r["reason"]))
    return {"chunks": dict(sorted(entries.items())), "summary": summary}


def mark_quarantine(chunks: list[dict], statistics: dict[str, Any], settings: dict[str, Any]) -> None:
    """``mark_review``: set ``quality`` to "review" on the chunks that hold a finding (not the informational ones, not page status) and
    record the numbers in ``statistics["quarantine"]["review"]``. Without the option or without a report nothing changes."""
    report = statistics.get("quarantine")
    if not settings.get("mark_review") or not isinstance(report, dict) or "findings" not in report:
        return
    allowed = settings["review_reasons"]
    reasons = set(allowed) if allowed is not None else set(MARKING_DEFAULT)
    mapping, stats = chunk_reasons(chunks, report, reasons)
    marked = {i for i, codes in mapping.items() if any(not code.startswith("page_unexamined:") for code in codes)}
    for index in marked:
        chunks[index]["quality"] = "review"
    stats["chunks"] = len(marked)
    report["review"] = stats
