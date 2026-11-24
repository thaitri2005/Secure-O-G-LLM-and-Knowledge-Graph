"""Restore a displaced native column when the complete printed grid proves the mapping."""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import cache

from ..ingestion.tables import table_views
from .numeric_cells import compact, read_words
from .ops_tables import chunk_template, grid_table_record, table_chunks
from .text_layer import source_page

RULE = "column_alignment"
PREFIX = f"textlayer:{RULE}:"
EQUIVALENT = str.maketrans("“”″‘’−–", '"""\'\'--')


def comparison(text):
    return compact(text).translate(EQUIVALENT)


def column_inversion(item):
    rows = defaultdict(list)
    for cell in item.data.table_cells:
        if cell.start_row_offset_idx > 0 and cell.text.strip() and cell.bbox is not None:
            rows[cell.start_row_offset_idx].append((cell.start_col_offset_idx, cell.bbox.l))
    return sum(any(x > y + 2 for (_, x), (_, y) in zip(row, row[1:]))
               for cells in rows.values() if (row := sorted(cells))) >= 2


def printed_tables(page):
    for result in page.find_tables(strategy="lines", paths=page.get_drawings()).tables:
        boxes = [row.cells for row in result.rows]
        grid = [[compact(value) for value in row] for row in result.extract()]
        if (len(grid) >= 3 and len(grid[0]) >= 3 and sum(bool(value) for value in grid[0]) >= 2
                and all(len(row) == len(grid[0]) and all(row) for row in boxes)
                and all("|" not in value for row in grid for value in row)):
            yield {"bbox": list(result.bbox), "grid": grid, "cell_boxes": boxes}


def proves_mapping(native, printed):
    before, after = ([[comparison(value) for value in row] for row in grid] for grid in (native, printed))
    if (len(before) != len(after) or len(before[0]) != len(after[0])
            or Counter(before[0]) != Counter(after[0])):
        return False
    original, physical = (list(zip(*grid[1:], strict=True)) for grid in (before, after))
    # Whole columns must make a unique permutation. Empty or repeated columns cannot decide an ownership change.
    return original != physical and len(set(physical)) == len(physical) and set(original) == set(physical)


def independently_readable(table, words):
    words = list(words)
    return all(comparison(read_words(words, box)) == comparison(value)
               for row, boxes in zip(table["grid"], table["cell_boxes"], strict=True)
               for value, box in zip(row, boxes, strict=True))


def repair_document(pdf, pages, chunks, tables, get_native, max_chars, *, stacked_pages=()):
    from .qa.crossrep import parse_table_chunk

    upright = {p["page"] for p in pages if p.get("mode") == "text" and p.get("rotation", 0) == 0
               and not (p.get("orientation") or {}).get("normalized") and p["page"] not in stacked_pages}
    candidates = [(i, t) for i, t in enumerate(tables) if t["source_ref"].startswith("#/tables/")
                  and "native_trimmed_rows" not in t and len(t["regions"]) == 1
                  and t["regions"][0]["page"] in upright and t["header_rows"] == 1
                  and t["num_rows"] >= 3 and t["num_cols"] >= 3]
    if not candidates:
        return chunks, tables, []
    native = get_native()
    eligible = []
    for i, table in candidates:
        item = native.get(table["source_ref"])
        if item is None or len(item.prov) != 1 or any(c.row_span != 1 or c.col_span != 1 for c in item.data.table_cells):
            continue
        grid, _, _, _ = table_views(item)
        if column_inversion(item):
            eligible.append((i, table, grid))
    if not eligible:
        return chunks, tables, []
    import pymupdf

    replacements, findings = {}, []
    with pymupdf.open(pdf) as source:
        @cache
        def printed(number):
            return [] if source[number - 1].rotation else list(printed_tables(source[number - 1]))

        @cache
        def second_reader(number):
            return [(word["text"], word["bbox"]) for word in source_page(pdf, number, displayed_origin=True)["words"]]

        for index, table, native_grid in eligible:
            region, = table["regions"]
            page = region["page"]
            children = [c for c in chunks if c["table_id"] == table["table_id"]]
            parsed = [parse_table_chunk(c["text"]) for c in children]
            if (not children or any(c["pages"] != [page] or c["ocr"] for c in children)
                    or any(not p["separator_ok"] or p["stray"] for p in parsed)
                    or any([comparison(value) for value in p["header"]] != [comparison(value) for value in native_grid[0]]
                           or [[comparison(v) for v in row] for row in p["rows"]]
                           != [[comparison(v) for v in row] for row in native_grid[child["row_start"]:child["row_end"]]]
                           for child, p in zip(children, parsed, strict=True))
                    or any(p["caption"] not in ([], parsed[0]["caption"]) for p in parsed[1:])):
                continue
            try:
                matches = [p for p in printed(page)
                           if all(abs(x - y) <= 2 for x, y in zip(p["bbox"], region["bbox"], strict=True))
                           and proves_mapping(native_grid, p["grid"])]
                if len(matches) != 1 or not independently_readable(matches[0], second_reader(page)):
                    continue
            except (OSError, RuntimeError, ValueError):
                continue
            panel, = matches
            ref = f"{PREFIX}p{page}:{index + 1}"
            corrected = grid_table_record(table["table_id"], table["doc_id"], ref, page, panel["bbox"], panel["grid"])
            replacement = table_chunks(corrected, chunk_template(children[0]), max_chars, "\n".join(parsed[0]["caption"]))
            replacements[table["table_id"]] = children[0], replacement
            tables[index] = corrected
            findings.append({"page": page, "rule": RULE, "action": "realigned", "source_ref": ref,
                             "original_source_ref": table["source_ref"], "bbox": panel["bbox"]})
    revised = []
    for chunk in chunks:
        if chunk["table_id"] not in replacements:
            revised.append(chunk)
        else:
            first, replacement = replacements[chunk["table_id"]]
            if chunk is first:
                revised.extend(replacement)
    return revised, tables, findings
