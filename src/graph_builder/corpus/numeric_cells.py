"""Reconcile a native compound number with an independently readable ruled PDF cell."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cache
import re

from ..ingestion.tables import table_row_texts
from .text_layer import source_page, union

SCALAR = re.compile(r"[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
COMPOUND = re.compile(fr"{SCALAR.pattern}(?:\s+{SCALAR.pattern})+")
# Count exact signed spellings as units, including numbers followed by a printed unit.
NUMBERS = re.compile(fr"(?<![\d.,+−-])(?:{SCALAR.pattern})(?![\d.,])")
PIPE = re.compile(r"(?<!\\)\|")
RULE = "native_numeric_cell"
TOLERANCE = 1.0


@dataclass(frozen=True)
class PrintedCell:
    box: tuple
    text: str
    grids: frozenset[int] = frozenset()


def compact(text):
    return " ".join((text or "").split())


def contains(outer, inner):
    return (outer[0] - TOLERANCE <= inner[0] < inner[2] <= outer[2] + TOLERANCE
            and outer[1] - TOLERANCE <= inner[1] < inner[3] <= outer[3] + TOLERANCE)


def words_inside(words, box):
    left, top, right, bottom = box
    return [(text, (l, t, r, b)) for text, (l, t, r, b) in words
            if left <= (l + r) / 2 <= right and top <= (t + b) / 2 <= bottom]


def read_words(words, box):
    """Read words whose centres lie inside the rectangle in the given coordinate frame."""
    return compact(" ".join(text for text, _ in words_inside(words, box)))


def printed_cells(page):
    cells = defaultdict(lambda: defaultdict(set))
    for grid, table in enumerate(page.find_tables(strategy="lines", paths=page.get_drawings()).tables):
        for row, texts in zip(table.rows, table.extract(), strict=True):
            for box, text in zip(row.cells, texts, strict=True):
                if box and compact(text):
                    cells[tuple(box)][compact(text)].add(grid)
    return [PrintedCell(box, text, frozenset(grids)) for box, texts in cells.items() if len(texts) == 1
            for text, grids in texts.items()]


def unique_cell(cells, box):
    hits = [cell for cell in cells if contains(cell.box, box)]
    return hits[0] if len(hits) == 1 else None


def same_band(a, b, dim):
    return all(abs(a[i] - b[i]) <= TOLERANCE for i in (dim, dim + 2))


def native_positions(item, height):
    positions = {}
    for cell in item.data.table_cells:
        if cell.bbox is None or cell.row_span != 1 or cell.col_span != 1 or not compact(cell.text):
            continue
        key = (cell.start_row_offset_idx, cell.start_col_offset_idx)
        if key in positions:
            return {}
        box = cell.bbox.to_top_left_origin(page_height=height)
        positions[key] = (compact(cell.text), (box.l, box.t, box.r, box.b))
    return positions


def matching_anchors(cell, key, anchors, dim):
    """Find in-grid anchors immediately adjacent in the corresponding native dimension."""
    fixed = 0 if dim == 1 else 1
    moving = 1 - fixed
    result = set()
    for slot, anchor in anchors.items():
        drift = slot[moving] - key[moving]
        if (slot[fixed] == key[fixed] and abs(drift) == 1 and same_band(cell.box, anchor.box, dim)
                and (anchor.box[fixed] - cell.box[fixed]) * drift > 0):
            result.update(anchor.grids)
    return result


def focused_positions(printout, positions, words):
    focuses = {}
    for key, (_, box) in positions.items():
        items = words_inside(words, box)
        if items:
            focus = union([bounds for _, bounds in items])
            cell = unique_cell(printout, focus)
            if cell is not None:
                focuses[key] = (cell, focus, compact(" ".join(text for text, _ in items)))
    return focuses


def corrections(table, positions, words, get_printed, get_independent, *, allow_focus=True):
    """Require one ruled cell, matching row and column anchors, and two agreeing readers."""
    occupied = [(r, c) for r, c in positions if 0 <= r < table["num_rows"] and 0 <= c < table["num_cols"]]
    candidates = {}
    for r, c in occupied:
        text, box = positions[r, c]
        if r < table["header_rows"] or text != compact(table["grid"][r][c]) or not COMPOUND.fullmatch(text):
            continue
        proposed = read_words(words, box)
        if SCALAR.fullmatch(proposed) and text.split().count(proposed) == 1:
            candidates[r, c] = proposed
    if not candidates:
        return {}, []
    printed = get_printed()
    mapped = {key: unique_cell(printed, positions[key][1]) for key in occupied}
    anchors = {key: cell for key, cell in mapped.items() if cell is not None and cell.text == positions[key][0]}
    owners = defaultdict(list)
    for key, cell in mapped.items():
        if cell is not None:
            owners[cell.box].append(key)
    accepted, unresolved = {}, []
    focused = None
    for key, value in candidates.items():
        r, c = key
        cell = mapped[key]
        reason = "numeric_cell_geometry_ambiguous"
        if (cell is not None and cell.text == value and owners[cell.box] == [key]
                and any(ar == r and ac != c and same_band(cell.box, anchor.box, 1) for (ar, ac), anchor in anchors.items())
                and any(ac == c and ar != r and same_band(cell.box, anchor.box, 0) for (ar, ac), anchor in anchors.items())):
            independent = get_independent()
            if independent is not None and read_words(independent, cell.box) == value and read_words(words, cell.box) == value:
                accepted[key] = {"r": r, "c": c, "previous": positions[key][0], "value": value, "bbox": list(cell.box)}
                continue
            reason = "numeric_cell_readers_disagree"
        if allow_focus and reason == "numeric_cell_geometry_ambiguous":
            if focused is None:
                focused = focused_positions(printed, positions, words)
                focus_anchors = {slot: p for slot, (p, _, text) in focused.items() if p.text == text == positions[slot][0]}
                focus_owners = Counter(p.box for p, _, _ in focused.values())
            if key in focused:
                target, focus, _ = focused[key]
                grids = (target.grids & matching_anchors(target, key, focus_anchors, 1)
                         & matching_anchors(target, key, focus_anchors, 0))
                if target.text == value and focus_owners[target.box] == 1 and grids:
                    independent = get_independent()
                    if (independent is not None and read_words(independent, target.box) == value
                            and read_words(words, target.box) == value):
                        accepted[key] = {"r": r, "c": c, "previous": positions[key][0], "value": value,
                                         "bbox": list(target.box), "focus": focus}
                        continue
                    reason = "numeric_cell_readers_disagree"
        unresolved.append({"r": r, "c": c, "reason": reason})
    return accepted, unresolved


def chunk_edits(chunk, changes, width):
    """Map body grid positions to exact rendered cells, preserving the original Markdown layout."""
    edits = {}
    row_lines = []
    offset = 0
    for line in chunk["text"].splitlines(keepends=True):
        if line.lstrip().startswith("|"):
            row_lines.append((offset, line))
        offset += len(line)
    body = row_lines[2:]
    if len(body) != chunk["row_end"] - chunk["row_start"]:
        return {}
    for (r, c), change in changes.items():
        if not chunk["row_start"] <= r < chunk["row_end"]:
            continue
        offset, line = body[r - chunk["row_start"]]
        pipes = list(PIPE.finditer(line))
        if len(pipes) != width + 1 or line[:pipes[0].start()].strip() or line[pipes[-1].end():].strip():
            continue
        start, end = pipes[c].end(), pipes[c + 1].start()
        cell = line[start:end]
        if compact(cell) != change["previous"]:
            continue
        first = offset + start + len(cell) - len(cell.lstrip())
        last = offset + start + len(cell.rstrip())
        if any(first < span[endpoint] < last for span in chunk.get("source_spans", []) for endpoint in ("start", "end")):
            continue
        edits[r, c] = (first, last, change["value"])
    return edits


def patch_chunk(chunk, edits):
    if not edits:
        return
    text = chunk["text"]
    for first, last, value in reversed(sorted(edits)):
        text = text[:first] + value + text[last:]

    def offset(pos):
        return pos + sum(len(value) - (last - first) for first, last, value in edits if last <= pos)

    chunk["text"] = text
    chunk["source_spans"] = [dict(span, start=offset(span["start"]), end=offset(span["end"]))
                             for span in chunk["source_spans"]]


def apply_corrections(table, chunks, plan, surplus=None):
    edits = [chunk_edits(chunk, plan, table["num_cols"]) for chunk in chunks]
    owners = defaultdict(list)
    for index, positions in enumerate(edits):
        for key in positions:
            owners[key].append(index)
    cells = defaultdict(list)
    for cell in table["cells"]:
        cells[cell["r"], cell["c"]].append(cell)
    accepted = {}
    withheld = {}
    for key, patch in plan.items():
        slots = cells[key]
        r, c = key
        if (len(owners[key]) == len(slots) == 1 and slots[0]["row_span"] == slots[0]["col_span"] == 1
                and compact(slots[0]["text"]) == patch["previous"] and not slots[0]["is_header"]):
            removed = Counter(patch["previous"].split()) - Counter([patch["value"]])
            if "focus" in patch and (surplus is None or any(surplus[value] < count for value, count in removed.items())):
                withheld[key] = "numeric_cell_source_coverage_unproven"
                continue
            if surplus is not None:
                surplus.subtract(removed)
            accepted[key] = patch
            slots[0]["text"] = table["grid"][r][c] = patch["value"]
    if accepted:
        table["rows_text"] = table_row_texts(table["grid"], table["header_rows"], table["num_cols"])
        table["parts"][0]["numeric_repairs"] = list(accepted.values())
        for chunk, changes in zip(chunks, edits, strict=True):
            patch_chunk(chunk, [edit for key, edit in changes.items() if key in accepted])
    return [{"r": r, "c": c, "reason": withheld.get((r, c), "numeric_cell_chunk_mapping_unproven")}
            for r, c in sorted(plan.keys() - accepted.keys())]


def repair_document(path, pages, tables, chunks, native_tables, *, stacked_pages=(), allow_focus=True):
    """Update eligible native K1 grids and rendered chunks before ids and digests are assigned."""
    eligible = {row["page"] for row in pages if row.get("mode") == "text" and row.get("rotation") == 0
                and not row.get("orientation", {}).get("normalized") and row["page"] not in stacked_pages}
    by_page, children = defaultdict(list), defaultdict(list)
    for table in tables:
        if len(table["parts"]) == 1 and table["parts"][0]["page"] in eligible:
            part = table["parts"][0]
            if part["source_ref"].startswith("#/tables/") and "native_trimmed_rows" not in part:
                if any(COMPOUND.fullmatch(value) for row in table["grid"][table["header_rows"]:] for value in row):
                    by_page[part["page"]].append(table)
    if not by_page:
        return []
    for chunk in chunks:
        if chunk["type"] == "table" and not chunk["ocr"]:
            children[chunk["table_id"]].append(chunk)
    try:
        import pymupdf

        pdf = pymupdf.open(path)
    except (ImportError, OSError, RuntimeError, ValueError):
        return []
    items = native_tables()
    texts_by_page = defaultdict(list)
    for chunk in chunks:
        if len(chunk["pages"]) == 1 and not chunk["ocr"]:
            texts_by_page[chunk["pages"][0]].append(chunk["text"])
    findings = []
    with pdf:
        for n, page_tables in by_page.items():
            page = pdf[n - 1]
            if page.rotation:
                continue
            words = [(w[4], w[:4]) for w in page.get_text("words", sort=True)]
            counts = Counter(NUMBERS.findall("\n".join(texts_by_page[n])))
            source_counts = Counter(number for text, _ in words for number in NUMBERS.findall(text))
            surplus = counts - source_counts

            @cache
            def read_printed():
                try:
                    return printed_cells(page)
                except (OSError, RuntimeError, ValueError):
                    return []

            @cache
            def read_independent():
                try:
                    layer = source_page(path, n, displayed_origin=True)
                    return [(word["text"], word["bbox"]) for word in layer["words"]]
                except (OSError, RuntimeError, ValueError):
                    return None

            for table in page_tables:
                item = items.get(table["parts"][0]["source_ref"])
                if item is None or len(item.prov) != 1 or item.prov[0].page_no != n:
                    continue
                source_chunks = children[table["logical_id"]]
                if not source_chunks or any(chunk["pages"] != [n] for chunk in source_chunks):
                    continue
                positions = native_positions(item, page.rect.height)
                plan, unresolved = corrections(table, positions, words, read_printed, read_independent,
                                                 allow_focus=allow_focus)
                unresolved += apply_corrections(table, source_chunks, plan, surplus)
                for item in unresolved:
                    findings.append(dict(item, page=n, table_id=table["table_id"], rule=RULE))
                for chunk in source_chunks:
                    if any(chunk["row_start"] <= item["r"] < chunk["row_end"] for item in unresolved):
                        chunk["quality"] = "review"
    return findings
