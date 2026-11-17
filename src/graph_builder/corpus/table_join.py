"""Join a table that is cut by a page break into one logical K1 table (FR-25). Optional K1 option ``table_join``; absent = no joining.

Class of problems: a ruled or borderless table that ends the body of page p and goes on at the top of page p+1. Corpus processing keeps one
physical table per page (``join.status = single``); this module decides, per pair (last table of page p, first table of page p+1), from
geometry and content whether the second is the continuation of the first, and assembles one K1 table when the evidence is strong.

Decision, from page geometry of the source PDF (PDFium text layer, display orientation) and the table grids:

* ``separate``: a hard condition fails (unsupported source or rotation, no text layer, a table does not end / start the page body, other column
  count, other x extent, a numeric column that restarts, an already multi-page table). The tables stay as they are.
* ``uncertain``: the geometry matches but nothing shows that the second table continues the first. The tables stay separate and both carry
  ``join.status = uncertain`` with the reason; a join is never forced.
* ``joined``: the geometry matches and at least one continuation signal holds: the header rows of the first table repeat at the top of the
  second table (also found on the PDF text layer), or the first table holds nothing but header-like rows (an orphaned header).

Nothing here knows a document id, a page number or a text string; thresholds and the marker pattern come from the configuration. Failures
never lose data: a pair that cannot be examined is reported with a machine-readable reason and stays separate. The text of table chunks is
never changed (a repeated header stays in the chunk text of the part that prints it), so chunk offsets and digests do not move; only the
table record, the parent of the later part's chunks and its ``row_start`` / ``row_end`` change (see ``apply_groups`` and ``k1_build``).
"""
from __future__ import annotations

from collections import Counter
import copy
import re
from pathlib import Path
from typing import Any, Callable

OPTION_KEYS = {"sources", "rotations", "page", "running_text", "boundary", "structure", "continuity"}
SECTION_KEYS = {
    "page": {"header_band_frac", "footer_band_frac", "frame_slack_pt", "page_size_tolerance_pt"},
    "running_text": {"cell_pt", "min_pages_frac", "top_zone_frac", "bottom_zone_frac", "max_pages"},
    "boundary": {"bottom_gap_max_frac", "top_gap_max_frac", "word_slack_pt"},
    "structure": {"x_tolerance_rel", "min_region_words"},
    "continuity": {"header_x_tolerance_rel", "header_min_words", "series_min_rows"},
}
REASONS_SEPARATE = ("already_multipage", "empty_table", "source_not_supported", "rotation_unsupported", "rotation_differs", "page_size_differs",
                    "no_text_layer", "a_not_at_page_end", "b_not_at_page_start", "column_count_differs", "x_extent_differs",
                    "series_restarts", "header_cell_spans_body", "invariant_failed", "pdf_unreadable")


def validate_table_join(options: Any) -> dict[str, Any]:
    """Check the ``table_join`` option of the K1 configuration. No defaults: every key is required."""
    if not isinstance(options, dict) or set(options) != OPTION_KEYS:
        raise ValueError(f"table_join must contain exactly {sorted(OPTION_KEYS)}")
    sources = options["sources"]
    if not isinstance(sources, list) or not sources or any(item not in ("docling", "textlayer") for item in sources) or len(set(sources)) != len(sources):
        raise ValueError("table_join sources must be a non-empty list of distinct names from: docling, textlayer")
    rotations = options["rotations"]
    if not isinstance(rotations, list) or not rotations or any(type(item) is not int or item not in (0, 90, 180, 270) for item in rotations):
        raise ValueError("table_join rotations must be a non-empty list of page rotations (0, 90, 180, 270)")
    for name, keys in SECTION_KEYS.items():
        section = options[name]
        if not isinstance(section, dict) or set(section) != keys:
            raise ValueError(f"table_join {name} must contain exactly {sorted(keys)}")
    numeric = {"page": ("header_band_frac", "footer_band_frac", "frame_slack_pt", "page_size_tolerance_pt"),
               "running_text": ("cell_pt", "min_pages_frac", "top_zone_frac", "bottom_zone_frac"),
               "boundary": ("bottom_gap_max_frac", "top_gap_max_frac", "word_slack_pt"), "structure": ("x_tolerance_rel",),
               "continuity": ("header_x_tolerance_rel",)}
    for name, keys in numeric.items():
        for key in keys:
            value = options[name][key]
            if type(value) not in (int, float) or value < 0:
                raise ValueError(f"table_join {name} {key} must be a non-negative number")
    for name, key in (("running_text", "max_pages"), ("structure", "min_region_words"), ("continuity", "header_min_words"),
                      ("continuity", "series_min_rows")):
        if type(options[name][key]) is not int or options[name][key] < 1:
            raise ValueError(f"table_join {name} {key} must be a positive integer")
    for key in ("min_pages_frac", "top_zone_frac", "bottom_zone_frac"):
        if not 0 < options["running_text"][key] <= 1:
            raise ValueError(f"table_join running_text {key} must be above 0 and at most 1")
    return options


# ---------------------------------------------------------------- geometry helpers (pure; words are {"text", "bbox": [l, t, r, b], "row"})

def norm_text(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").split())


def norm_row(row: list[Any]) -> tuple[str, ...]:
    return tuple(norm_text(cell) for cell in row)


def words_inside(box: list[float], words: list[dict], slack: float) -> list[dict]:
    return [w for w in words if w["bbox"][0] >= box[0] - slack and w["bbox"][2] <= box[2] + slack
            and w["bbox"][1] >= box[1] - slack and w["bbox"][3] <= box[3] + slack]


def running_limits(layers: dict[int, dict], options: dict) -> dict[int, tuple[float, float]]:
    """Per page (top_limit, bottom_limit): words whose grid cell (x, y) holds a word on enough of the given pages, inside the top / bottom
    search zone, are template text (title block, footer) and are skipped. Position only; the text is ignored."""
    page, running = options["page"], options["running_text"]
    cell = running["cell_pt"]
    counts: Counter = Counter()
    for layer in layers.values():
        height = layer["height"]
        counts.update({(round(w["bbox"][0] / cell), round(w["bbox"][1] / cell)) for w in layer["words"]
                       if w["bbox"][3] <= height * running["top_zone_frac"] or w["bbox"][1] >= height * (1 - running["bottom_zone_frac"])})
    need = max(2, running["min_pages_frac"] * len(layers))
    limits = {}
    for number, layer in layers.items():
        height = layer["height"]
        top, bottom = height * page["header_band_frac"], height * (1.0 - page["footer_band_frac"])
        for w in layer["words"]:
            if counts[(round(w["bbox"][0] / cell), round(w["bbox"][1] / cell))] < need:
                continue
            if w["bbox"][3] <= height * running["top_zone_frac"]:
                top = max(top, w["bbox"][3])
            elif w["bbox"][1] >= height * (1 - running["bottom_zone_frac"]):
                bottom = min(bottom, w["bbox"][1])
        limits[number] = (top, bottom)
    return limits


def frame_zone(box: list[float], top: float, bottom: float, slack: float) -> str | None:
    """'header' / 'footer' for a "table" lying completely inside the running header / footer zone (page furniture), else None."""
    if box[3] <= top + slack:
        return "header"
    if box[1] >= bottom - slack:
        return "footer"
    return None


def ends_page_body(box: list[float], words: list[dict], height: float, limit: float, options: dict) -> dict:
    below = [w for w in words if w["bbox"][1] >= box[3] - options["boundary"]["word_slack_pt"] and w["bbox"][3] <= limit]
    gap = max(0.0, (limit - box[3]) / height)
    return {"words_below": len(below), "gap_frac": round(gap, 4), "ends": not below and gap <= options["boundary"]["bottom_gap_max_frac"]}


def starts_page_body(box: list[float], words: list[dict], height: float, limit: float, options: dict) -> dict:
    above = [w for w in words if w["bbox"][3] <= box[1] + options["boundary"]["word_slack_pt"] and w["bbox"][1] >= limit]
    gap = max(0.0, (box[1] - limit) / height)
    return {"words_above": len(above), "gap_frac": round(gap, 4), "starts": not above and gap <= options["boundary"]["top_gap_max_frac"]}


def x_extent_match(a: list[float], b: list[float], options: dict) -> dict:
    width = max(a[2] - a[0], b[2] - b[0], 1e-6)
    left, right = abs(a[0] - b[0]) / width, abs(a[2] - b[2]) / width
    tolerance = options["structure"]["x_tolerance_rel"]
    return {"left_delta_rel": round(left, 4), "right_delta_rel": round(right, 4), "match": left <= tolerance and right <= tolerance}


def text_lines(words: list[dict]) -> list[dict]:
    """Text lines (top to bottom) of words that carry a ``row`` id: [{"x0", "text", "n"}]."""
    rows: dict[Any, list[dict]] = {}
    for w in words:
        if str(w["text"]).strip():
            rows.setdefault(w.get("row"), []).append(w)
    lines = []
    for row in rows.values():
        row.sort(key=lambda w: w["bbox"][0])
        lines.append({"y": sum((w["bbox"][1] + w["bbox"][3]) / 2 for w in row) / len(row), "x0": row[0]["bbox"][0],
                      "text": norm_text(" ".join(str(w["text"]) for w in row)), "n": len(row)})
    return sorted(lines, key=lambda line: line["y"])


def header_prefix(words_a: list[dict], words_b: list[dict], width: float, options: dict) -> dict:
    """Source-based header repetition: how many text rows at the top of the later table's region reproduce, in text and x position, the top
    rows of the earlier table's region on the PDF text layer (independent of how the converter split the header cells)."""
    lines_a, lines_b = text_lines(words_a), text_lines(words_b)
    tolerance = options["continuity"]["header_x_tolerance_rel"] * max(width, 1e-6)
    rows = 0
    while rows < min(len(lines_a), len(lines_b)) and lines_a[rows]["text"] == lines_b[rows]["text"] \
            and abs(lines_a[rows]["x0"] - lines_b[rows]["x0"]) <= tolerance:
        rows += 1
    tokens = {token for line in lines_a[:rows] for token in line["text"].split()}
    words = sum(line["n"] for line in lines_a[:rows])
    return {"rows": rows, "words": words, "tokens": tokens, "repeated": rows >= 1 and words >= options["continuity"]["header_min_words"]}


# ---------------------------------------------------------------- grid helpers (pure; a table is a K1 table record)

def number_of(text: Any) -> float | None:
    cleaned = str(text or "").strip().replace(",", "")
    return float(cleaned) if re.fullmatch(r"-?\d+(\.\d+)?", cleaned) else None


def leading_header_rows(b: dict, prefix_tokens: set[str]) -> int:
    """How many leading grid rows of ``b`` hold nothing but the words of the header printed at the top of both pages (always fewer than all
    rows of b). The dropped rows add no information: every word of them is part of the header that the earlier table prints as well."""
    count = 0
    for row in b["grid"][:len(b["grid"]) - 1]:
        tokens = {token for cell in row for token in norm_text(cell).split()}
        if not tokens or not tokens <= prefix_tokens:
            break
        count += 1
    return count


def series_check(a: dict, b: dict, dropped: int, options: dict) -> dict:
    """Numeric columns of ``a`` that run monotonically over at least ``series_min_rows`` rows and whether ``b`` continues or restarts them."""
    need = options["continuity"]["series_min_rows"]
    continues, restarts = [], []
    for column in range(a["num_cols"]):
        values = [v for v in (number_of(row[column]) for row in a["grid"][a["header_rows"]:] if column < len(row)) if v is not None]
        if len(values) < need or len(set(values)) < 2:
            continue
        increasing = all(x <= y for x, y in zip(values, values[1:]))
        decreasing = all(x >= y for x, y in zip(values, values[1:]))
        if not (increasing or decreasing):
            continue
        first = next((v for v in (number_of(row[column]) for row in b["grid"][dropped:dropped + 2] if column < len(row)) if v is not None), None)
        if first is None or first == values[-1]:
            continue
        (continues if (first > values[-1]) == increasing else restarts).append(column)
    return {"continues": continues, "restarts": restarts}


def header_like(row: list[str]) -> bool:
    """A row that can be a header: some text and no number in any cell."""
    return any(str(cell).strip() for cell in row) and all(number_of(cell) is None for cell in row)


def source_of(table: dict) -> str:
    return "textlayer" if str(table["parts"][0]["source_ref"]).startswith("textlayer") else "docling"


# ---------------------------------------------------------------- decision for one pair

def assess_pair(a: dict, b: dict, layer_a: dict | None, layer_b: dict | None, limits: dict[int, tuple[float, float]], options: dict) -> dict:
    """Decide for table ``a`` (last of page p) and table ``b`` (first of page p+1). Returns {decision, reasons, evidence, dropped_header_rows}."""
    evidence: dict[str, Any] = {"pages": [a["regions"][-1]["page"], b["regions"][0]["page"]], "num_cols": [a["num_cols"], b["num_cols"]],
                                "rows": [a["num_rows"], b["num_rows"]], "header_rows": [a["header_rows"], b["header_rows"]]}
    blocking: list[str] = []
    inside_a: list[dict] = []
    inside_b: list[dict] = []
    if len(a["regions"]) > 1 or len(b["regions"]) > 1:
        blocking.append("already_multipage")
    if a["num_rows"] == 0 or b["num_rows"] == 0 or not a["grid"] or not b["grid"]:
        blocking.append("empty_table")
    if source_of(a) not in options["sources"] or source_of(b) not in options["sources"]:
        blocking.append("source_not_supported")
    if a["num_cols"] != b["num_cols"]:
        blocking.append("column_count_differs")
    if layer_a is None or layer_b is None:
        blocking.append("pdf_unreadable")
    else:
        evidence["rotation"] = [layer_a["rotation"], layer_b["rotation"]]
        if layer_a["rotation"] not in options["rotations"] or layer_b["rotation"] not in options["rotations"]:
            blocking.append("rotation_unsupported")
        elif layer_a["rotation"] != layer_b["rotation"]:
            blocking.append("rotation_differs")
        tolerance = options["page"]["page_size_tolerance_pt"]
        if abs(layer_a["width"] - layer_b["width"]) > tolerance or abs(layer_a["height"] - layer_b["height"]) > tolerance:
            blocking.append("page_size_differs")
        box_a, box_b = a["regions"][-1]["bbox"], b["regions"][0]["bbox"]
        minimum = options["structure"]["min_region_words"]
        inside_a = words_inside(box_a, layer_a["words"], options["boundary"]["word_slack_pt"])
        inside_b = words_inside(box_b, layer_b["words"], options["boundary"]["word_slack_pt"])
        evidence["words_in_region"] = [len(inside_a), len(inside_b)]
        if len(inside_a) < minimum or len(inside_b) < minimum:
            blocking.append("no_text_layer")
        end = ends_page_body(box_a, layer_a["words"], layer_a["height"], limits[a["regions"][-1]["page"]][1], options)
        start = starts_page_body(box_b, layer_b["words"], layer_b["height"], limits[b["regions"][0]["page"]][0], options)
        extent = x_extent_match(box_a, box_b, options)
        evidence.update(ends_page_body=end, starts_page_body=start, x_extent=extent)
        if not end["ends"]:
            blocking.append("a_not_at_page_end")
        if not start["starts"]:
            blocking.append("b_not_at_page_start")
        if not extent["match"]:
            blocking.append("x_extent_differs")
    dropped = 0
    prefix = None
    if not any(reason in blocking for reason in ("already_multipage", "empty_table", "column_count_differs", "pdf_unreadable")):
        prefix = header_prefix(inside_a, inside_b, max(a["regions"][-1]["bbox"][2] - a["regions"][-1]["bbox"][0], 1e-6), options)
        dropped = leading_header_rows(b, prefix["tokens"]) if prefix["repeated"] else 0
        evidence["header_text_layer"] = {"rows": prefix["rows"], "words": prefix["words"], "repeated": prefix["repeated"], "grid_rows_dropped": dropped}
        series = series_check(a, b, dropped, options)
        evidence["series"] = series
        if series["restarts"]:
            blocking.append("series_restarts")
        if dropped and any(cell["r"] < dropped < cell["r"] + cell["row_span"] for cell in b["cells"]):
            blocking.append("header_cell_spans_body")
    if blocking:
        return {"decision": "separate", "reasons": sorted(set(blocking), key=REASONS_SEPARATE.index), "evidence": evidence, "dropped_header_rows": 0}
    signals, conflicts = [], []
    if prefix and prefix["repeated"]:
        covered = {token for row in b["grid"][:dropped] for cell in row for token in norm_text(cell).split()}
        if dropped and prefix["tokens"] <= covered:
            signals.append("header_repeated")
        else:
            conflicts.append("header_repeated_on_pdf_not_in_grid")  # the PDF repeats a header the grid cannot drop cleanly: do not guess
    if a["num_rows"] == a["header_rows"] >= 1 and not dropped and all(header_like(row) for row in a["grid"]):
        signals.append("orphan_header")
    evidence["signals"] = signals
    if conflicts:
        return {"decision": "uncertain", "reasons": conflicts + ["structure_matches"], "evidence": evidence, "dropped_header_rows": 0}
    if not signals:
        return {"decision": "uncertain", "reasons": ["no_continuation_signal", "structure_matches"], "evidence": evidence, "dropped_header_rows": 0}
    reasons = ["ends_page_body", "starts_page_body", "columns_equal", "x_extent_match"] + signals
    if evidence["series"]["continues"]:
        reasons.append("series_continues")
    return {"decision": "joined", "reasons": reasons, "evidence": evidence, "dropped_header_rows": dropped}


# ---------------------------------------------------------------- planning over one document

def candidate_pairs(tables: list[dict], frames: set[str]) -> list[tuple[dict, dict]]:
    """(last table ending page p, first table starting page p+1) for every consecutive page pair; frame tables are left out."""
    ending: dict[int, list[dict]] = {}
    starting: dict[int, list[dict]] = {}
    for table in tables:
        if table["table_id"] in frames or not table["regions"]:
            continue
        ending.setdefault(table["regions"][-1]["page"], []).append(table)
        starting.setdefault(table["regions"][0]["page"], []).append(table)
    pairs = []
    for page in sorted(ending):
        if page + 1 in starting:
            last = max(ending[page], key=lambda t: (t["regions"][-1]["bbox"][3], t["table_id"]))
            first = min(starting[page + 1], key=lambda t: (t["regions"][0]["bbox"][1], t["table_id"]))
            if last["table_id"] != first["table_id"]:
                pairs.append((last, first))
    return pairs


def sample_pages(count: int, needed: set[int], maximum: int) -> list[int]:
    """Deterministic page set for the running-text statistics: every page of a short document, else the needed pages plus evenly spaced others."""
    every = list(range(1, count + 1))
    if len(every) <= maximum:
        return every
    others = [page for page in every if page not in needed]
    room = max(0, maximum - len(needed))
    return sorted(needed | {others[int(i * len(others) / room)] for i in range(room)}) if room else sorted(needed)


def plan_joins(tables: list[dict], read_page: Callable[[int], dict], page_count: int, options: dict) -> dict[str, Any]:
    """Decide every candidate pair of one document. ``read_page(n)`` returns the source page layer (words, height, width, rotation).

    Returns {"decisions": [...], "groups": [[table, ...], ...], "error": str | None}. A group of two or more tables is to be joined."""
    pairs = candidate_pairs(tables, set())
    if not pairs:
        return {"decisions": [], "groups": [], "error": None}
    needed = {page for a, b in pairs for page in (a["regions"][-1]["page"], b["regions"][0]["page"])}
    try:
        layers = {n: read_page(n) for n in sample_pages(page_count, needed, options["running_text"]["max_pages"])}
    except Exception as error:  # an unreadable PDF never stops the export: nothing is joined and the reason is recorded
        decisions = [{"a": a["table_id"], "b": b["table_id"], "pages": [a["regions"][-1]["page"], b["regions"][0]["page"]], "decision": "separate",
                      "reasons": ["pdf_unreadable"], "evidence": {}, "dropped_header_rows": 0} for a, b in pairs]
        return {"decisions": decisions, "groups": [], "error": f"{type(error).__name__}: {error}"}
    limits = running_limits(layers, options)
    frames = {t["table_id"] for t in tables if t["regions"] and len({r["page"] for r in t["regions"]}) == 1
              and t["regions"][0]["page"] in limits
              and frame_zone(t["regions"][0]["bbox"], *limits[t["regions"][0]["page"]], options["page"]["frame_slack_pt"])}
    decisions = []
    for a, b in candidate_pairs(tables, frames):
        result = assess_pair(a, b, layers.get(a["regions"][-1]["page"]), layers.get(b["regions"][0]["page"]), limits, options)
        decisions.append({"a": a["table_id"], "b": b["table_id"], "pages": result["evidence"]["pages"], **result})
    by_id = {t["table_id"]: t for t in tables}
    groups: list[list[dict]] = []
    for decision in decisions:
        if decision["decision"] != "joined":
            continue
        a, b = by_id[decision["a"]], by_id[decision["b"]]
        if groups and groups[-1][-1]["table_id"] == a["table_id"]:
            groups[-1].append(b)
        else:
            groups.append([a, b])
    return {"decisions": decisions, "groups": groups, "error": None, "frames": sorted(frames)}


# ---------------------------------------------------------------- assembling the K1 tables

def token_bag(grid: list[list[str]]) -> Counter:
    return Counter(token for row in grid for cell in row for token in norm_text(cell).split())


def labels_of(table: dict) -> list[str]:
    return [" / ".join(dict.fromkeys(row[c] for row in table["grid"][:table["header_rows"]] if c < len(row) and row[c]))
            for c in range(table["num_cols"])]


def row_text(labels: list[str], row: list[str]) -> str:
    return "; ".join(f"{labels[c]}: {value}" if labels[c] else value for c, value in enumerate(row))


def apply_groups(tables: list[dict], plan: dict[str, Any], options: dict) -> tuple[list[dict], dict[str, dict], list[dict]]:
    """Assemble the planned groups. Returns (tables, absorbed, failures): ``tables`` keeps the order and ids of the tables that are not absorbed,
    ``absorbed[logical_id]`` = {table_id, owner, offset, dropped, rows} for every table that joined an earlier one.

    A group is assembled only when the token multiset of the joined grid plus the dropped header rows equals that of its parts; otherwise it is
    left separate and reported as ``invariant_failed`` (no data is ever dropped silently)."""
    decisions = {(d["a"], d["b"]): d for d in plan["decisions"]}
    replaced: dict[str, dict] = {}
    absorbed: dict[str, dict] = {}
    failures: list[dict] = []
    for group in plan["groups"]:
        first = group[0]
        grid = [list(row) for row in first["grid"]]
        cells = copy.deepcopy(first["cells"])
        rows_text = list(first["rows_text"])
        parts = copy.deepcopy(first["parts"])
        regions = list(first["regions"])
        labels = labels_of(first)
        reasons = set(decisions[(group[0]["table_id"], group[1]["table_id"])]["reasons"])
        dropped_bag: Counter = Counter()
        moved: dict[str, dict] = {}
        for previous, table in zip(group, group[1:]):
            decision = decisions[(previous["table_id"], table["table_id"])]
            dropped = decision["dropped_header_rows"]
            reasons.update(decision["reasons"])
            offset = len(grid)
            if len(table["grid"]) != table["num_rows"]:
                failures.append({"table_id": first["table_id"], "reason": "invariant_failed", "detail": "grid rows differ from num_rows"})
                moved = {}
                break
            grid.extend(list(row) for row in table["grid"][dropped:])
            dropped_bag.update(token_bag(table["grid"][:dropped]))
            cells.extend(dict(cell, r=cell["r"] - dropped + offset) for cell in copy.deepcopy(table["cells"]) if cell["r"] >= dropped)
            rows_text.extend(row_text(labels, row) for row in table["grid"][dropped:])
            parts.append(dict(table["parts"][0], row_start=offset, row_end=offset + len(table["grid"]) - dropped,
                              header=[list(row) for row in table["grid"][:dropped]]))
            regions.extend(table["regions"])
            moved[table["logical_id"]] = {"table_id": table["table_id"], "owner": first["table_id"], "offset": offset, "dropped": dropped,
                                          "rows": len(table["grid"]) - dropped}
        if moved:
            before = Counter()
            for part in group:
                before.update(token_bag(part["grid"]))
            if token_bag(grid) + dropped_bag != before:
                failures.append({"table_id": first["table_id"], "reason": "invariant_failed", "detail": "token multiset differs"})
                moved = {}
        if not moved:
            for previous, table in zip(group, group[1:]):
                decisions[(previous["table_id"], table["table_id"])].update(decision="separate", reasons=["invariant_failed"], dropped_header_rows=0)
            continue
        joined = dict(first, pages=sorted({r["page"] for r in regions}), grid=grid, num_rows=len(grid), cells=cells, parts=parts, regions=regions,
                      rows_text=rows_text, join={"status": "joined", "reasons": sorted(reasons)})
        replaced[first["table_id"]] = joined
        absorbed.update(moved)
    owner_of = {entry["table_id"]: entry["owner"] for entry in absorbed.values()}
    marks = uncertain_marks(plan["decisions"], owner_of)
    result = []
    for table in tables:
        if table["table_id"] in owner_of:
            continue
        table = replaced.get(table["table_id"], table)
        if table["table_id"] in marks:
            status = "uncertain" if table["join"]["status"] == "single" else table["join"]["status"]
            table = dict(table, join={"status": status, "reasons": sorted(set(table["join"]["reasons"]) | set(marks[table["table_id"]]))})
        result.append(table)
    return result, absorbed, failures


def uncertain_marks(decisions: list[dict], owner_of: dict[str, str]) -> dict[str, list[str]]:
    """Entries for the K1 ``join.reasons`` of the tables at the two ends of an ``uncertain`` pair (``uncertain_next:<id>:<reason>``); an absorbed
    table is replaced by the table it joined."""
    marks: dict[str, list[str]] = {}
    for d in decisions:
        if d["decision"] != "uncertain":
            continue
        a, b = owner_of.get(d["a"], d["a"]), owner_of.get(d["b"], d["b"])
        if a != b:
            marks.setdefault(a, []).append(f"uncertain_next:{b}:{d['reasons'][0]}")
            marks.setdefault(b, []).append(f"uncertain_previous:{a}:{d['reasons'][0]}")
    return {key: sorted(set(value)) for key, value in marks.items()}


def summarize(plan: dict[str, Any], absorbed: dict[str, dict], failures: list[dict]) -> dict[str, Any]:
    decisions = plan["decisions"]
    return {"pairs": len(decisions), "by_decision": dict(sorted(Counter(d["decision"] for d in decisions).items())),
            "by_reason": dict(sorted(Counter(r for d in decisions for r in d["reasons"] if d["decision"] != "joined").items())),
            "joined_groups": len(plan["groups"]) - len(failures), "absorbed_tables": len(absorbed),
            "failures": failures, "error": plan.get("error")}


def join_tables(tables: list[dict], pdf: Path, page_count: int, options: dict) -> tuple[list[dict], dict[str, dict], dict[str, Any]]:
    """Plan and apply the joins of one document. Returns (tables, absorbed, report); the report is a sidecar and never part of the package."""
    from .text_layer import source_page
    cache: dict[int, dict] = {}

    def read_page(number: int) -> dict:
        if number not in cache:
            cache[number] = source_page(pdf, number)
        return cache[number]

    try:
        plan = plan_joins(tables, read_page, page_count, options)
        result, absorbed, failures = apply_groups(tables, plan, options)
    except Exception as error:  # failure isolation: one document that cannot be judged never stops the export and never gets half a join
        report = {"decisions": [], "frames": [], "absorbed": {}, "summary": {"pairs": 0, "by_decision": {}, "by_reason": {}, "joined_groups": 0,
                                                                         "absorbed_tables": 0, "failures": [], "error": f"{type(error).__name__}: {error}"}}
        return tables, {}, report
    report = {"decisions": plan["decisions"], "frames": plan.get("frames", []), "summary": summarize(plan, absorbed, failures),
              "absorbed": {logical: dict(entry) for logical, entry in sorted(absorbed.items())}}
    return result, absorbed, report
