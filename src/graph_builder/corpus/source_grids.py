"""Recover unclaimed ruled text tables using their printed geometry and two PDF readers."""
from __future__ import annotations

from collections import defaultdict
import re

from ..ingestion.tables import table_views
from ..ingestion.tables import table_row_texts
from ..ingestion.scoring import bbox_iou
from . import complex_grids, rendered_grids
from .column_alignment import comparison, independently_readable
from .numeric_cells import compact
from .ops_tables import chunk_template, grid_table_record, table_chunks
from .ruled_geometry import conservative_replacement
from .text_layer import source_page

RULE = "source_grids"
PREFIX = f"textlayer:{RULE}:"
NUMERIC = re.compile(r"(?<!\w)[+−-]?\d+(?:[.,:]\d+)*(?!\w)")
MEASUREMENT = re.compile(r"[+−-]?\d+(?:[.,:/]\d+)*(?:\s*[°%\w./'-]{1,12})?", re.I)


def plausible_grid(grid):
    """Only rectangular data tables with a printed heading row and body values are eligible."""
    if len(grid) < 2 or len(grid[0]) < 2:
        return False
    width = len(grid[0])
    labels = [comparison(value).casefold() for value in grid[0] if value]
    return (len(labels) >= 2 and len(labels) * 2 >= width and len(set(labels)) == len(labels)
            and sum(any(letter.isalpha() for letter in label) for label in labels) >= 2
            and all(len(row) == width and sum(bool(value) for value in row) >= 2 for row in grid[1:])
            and any(NUMERIC.search(value) for row in grid[1:] for value in row))


def intersects(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1


def ruled_grids(page):
    drawings = page.get_drawings()
    if not drawings:
        return
    yield from physical_grids(page.find_tables(strategy="lines", paths=drawings).tables)


def physical_grids(tables):
    for table in tables:
        boxes = [row.cells for row in table.rows]
        # A missing physical box indicates a merged or unproven grid position.
        if not boxes or not all(boxes[0]) or any(len(row) != len(boxes[0]) or not all(row) for row in boxes):
            continue
        grid = [[compact(value) for value in row] for row in table.extract()]
        if plausible_grid(grid) and all("|" not in value for row in grid for value in row):
            yield {"bbox": list(table.bbox), "grid": grid, "cell_boxes": boxes}


def table_panels(pdf, page, allow_complex, geometry_gate=None, *, allow_borderless=False):
    occupied = []
    for table, panel in complex_grids.panels(pdf, page, allow_complex, geometry_gate, allow_borderless=allow_borderless):
        if panel is None:
            for ruled in physical_grids([table]):
                occupied.append(ruled["bbox"])
                yield ruled
            continue
        headers = panel["header_rows"]
        grid = panel["grid"]
        labels = [" ".join(row[c] for row in grid[:headers] if row[c]) for c in range(len(grid[0]))]
        if headers > 1 and any(NUMERIC.fullmatch(value) for row in grid[:headers] for value in row):
            continue
        # A boxed report can have rows and columns without having column headings or data cells.
        if any(len(label.split()) > 12 for label in labels) or not any(
                MEASUREMENT.fullmatch(value) for row in grid[headers:] for value in row):
            continue
        if plausible_grid([labels, *grid[headers:]]):
            occupied.append(panel["bbox"])
            yield panel

    def unclaimed(box):
        return (not any(intersects(box, other) for other in occupied)
                and (geometry_gate is None or geometry_gate(box, aligned=True)))

    if allow_complex and page is not None:
        for panel in rendered_grids.panels(pdf, page, unclaimed):
            if plausible_grid(panel["grid"]):
                yield dict(panel, rule=complex_grids.RULE)


def independently_proven(page, panel, pdfium_words):
    """Both readers must read the same whole cell. This also checks that empty cells stay empty."""
    words = [(w[4], w[:4]) for w in page.get_text("words", clip=panel["bbox"], sort=True)]
    return independently_readable(panel, words) and independently_readable(panel, pdfium_words)


def row_content(row):
    # A converter can introduce a word break inside a printed glyph run.
    # The result still needs the full character sequence in every row.
    return "".join(comparison(" ".join(row)).split())


def lossless_repair(native, printed):
    """Repartition a row only when its non-whitespace characters match the printed row in order."""
    return (len(native) == len(printed) and [list(map(comparison, row)) for row in native]
            != [list(map(comparison, row)) for row in printed]
            and all(row_content(a) == row_content(b) for a, b in zip(native, printed, strict=True)))


def template_for_repair(chunks, grid, page):
    from .qa.crossrep import parse_table_chunk

    if not chunks:
        return None
    next_row, caption = 1, None
    header = [comparison(value) for value in grid[0]]
    for chunk in chunks:
        if chunk["pages"] != [page] or chunk["ocr"] or chunk["row_start"] != next_row:
            return None
        parsed = parse_table_chunk(chunk["text"])
        if not parsed["separator_ok"] or parsed["stray"] or list(map(comparison, parsed["header"])) != header:
            return None
        next_row = chunk["row_end"]
        if [[comparison(value) for value in row] for row in parsed["rows"]] != [
                [comparison(value) for value in row] for row in grid[chunk["row_start"]:next_row]]:
            return None
        if parsed["caption"]:
            if caption is not None and caption != parsed["caption"]:
                return None
            caption = parsed["caption"]
    if next_row == len(grid):
        return chunk_template(chunks[0]), "\n".join(caption or ())
    return None


def replacement_for(region, candidate, table, get_native, children, page):
    if candidate.get("rule") == complex_grids.RULE:
        return conservative_replacement(candidate, table, children, page, ocr=False)
    if not table["source_ref"].startswith("#/tables/") or table["header_rows"] != 1 or len(table["regions"]) != 1:
        return None
    if any(abs(a - b) > 2 for a, b in zip(region, candidate["bbox"], strict=True)):
        return None
    item = get_native().get(table["source_ref"])
    if item is None or len(item.prov) != 1 or item.prov[0].page_no != page:
        return None
    native, _, _, _ = table_views(item)
    if not lossless_repair(native, candidate["grid"]):
        return None
    return template_for_repair(children, native, page)


def repair_document(pdf, pages, chunks, tables, doc_id, max_chars, get_native, *, stacked_pages=(), allow_complex=False,
                    allow_borderless=False):
    import pymupdf

    numbers = [p["page"] for p in pages if p.get("mode") == "text" and (allow_complex or not p.get("rotation"))
               and not (p.get("orientation") or {}).get("normalized") and p["page"] not in stacked_pages]
    if not numbers:
        return chunks, tables, []
    claimed = defaultdict(list)
    for index, table in enumerate(tables):
        for region in table["regions"]:
            claimed[region["page"]].append((index, region["bbox"]))
    children = defaultdict(list)
    for chunk in chunks:
        if chunk["type"] == "table":
            children[chunk["table_id"]].append(chunk)
    additions, replacements, findings = defaultdict(list), {}, []
    with pymupdf.open(pdf) as document:
        for number in numbers:
            page = document[number - 1]

            def could_use(box, *, aligned=False):
                owners = [(i, region) for i, region in claimed[number] if intersects(box, region)]
                if not owners:
                    return True
                if len(owners) != 1:
                    return False
                (index, region), = owners
                if not tables[index]["source_ref"].startswith("#/tables/"):
                    return False
                return bbox_iou(box, region) >= .85 if aligned else all(
                    abs(a - b) <= 5 for a, b in zip(box, region, strict=True))

            try:
                candidates = list(table_panels(pdf, page, True, could_use, allow_borderless=allow_borderless)) if allow_complex else (
                    list(ruled_grids(page)) if not page.rotation else [])
                pdfium_words = None
                for index, panel in enumerate(candidates, 1):
                    owners = [(previous, box) for previous, box in claimed[number] if intersects(panel["bbox"], box)]
                    if len(owners) > 1:
                        continue
                    previous = None
                    logical_id = f"{doc_id}#{RULE}-p{number}-{index}"
                    template, caption = {"doc_id": doc_id, "section": None, "section_path": [], "ocr": False, "quality": "ok"}, ""
                    if owners:
                        (previous, box), = owners
                        original = tables[previous]
                        logical_id = original["table_id"]
                        context = replacement_for(box, panel, original, get_native, children[logical_id], number)
                        if context is None:
                            continue
                        template, caption = context
                    if any(other is not panel and intersects(other["bbox"], panel["bbox"]) for other in candidates):
                        findings.append({"page": number, "rule": RULE, "reason": "competing_source_grids", "bbox": panel["bbox"]})
                        continue
                    rule = panel.get("rule", RULE)
                    if rule == RULE:
                        if pdfium_words is None:
                            layer = source_page(pdf, number, displayed_origin=True)
                            pdfium_words = [(word["text"], word["bbox"]) for word in layer["words"]]
                        if not independently_proven(page, panel, pdfium_words):
                            findings.append({"page": number, "rule": RULE, "reason": "source_grid_readers_disagree", "bbox": panel["bbox"]})
                            continue
                    ref = f"textlayer:{rule}:p{number}:{index}"
                    table = grid_table_record(logical_id, doc_id, ref, number, panel["bbox"], panel["grid"])
                    if rule == complex_grids.RULE:
                        table.update(cells=panel["cells"], header_rows=panel["header_rows"],
                                     rows_text=table_row_texts(panel["grid"], panel["header_rows"], table["num_cols"]))
                    rendered = table_chunks(table, template, max_chars, caption)
                    finding = {"page": number, "rule": rule, "action": "recovered", "bbox": panel["bbox"]}
                    if rule == complex_grids.RULE:
                        finding["rotation"] = list(panel["rotation"])
                        if panel.get("structure"):
                            finding["structure"] = panel["structure"]
                    if previous is None:
                        additions[number].extend(rendered)
                        tables.append(table)
                    else:
                        finding.update(action="repartitioned", original_source_ref=tables[previous]["source_ref"])
                        replacements[logical_id] = rendered
                        tables[previous] = table
                    findings.append(finding)
            except (OSError, RuntimeError, ValueError):
                findings.append({"page": number, "rule": RULE, "reason": "source_grid_unreadable"})
    if not additions and not replacements:
        return chunks, tables, findings
    ordered, pending = [], iter(sorted(additions))
    current = next(pending, None)
    for chunk in chunks:
        while current is not None and current < min(chunk["pages"]):
            ordered.extend(additions[current])
            current = next(pending, None)
        if chunk["table_id"] in replacements:
            if children[chunk["table_id"]][0] is chunk:
                ordered.extend(replacements[chunk["table_id"]])
        else:
            ordered.append(chunk)
    if current is not None:
        ordered.extend(additions[current])
        for number in pending:
            ordered.extend(additions[number])
    return ordered, tables, findings
