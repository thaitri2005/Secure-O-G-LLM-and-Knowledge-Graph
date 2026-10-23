"""Render table cells without padding and retain row-oriented evidence."""
from __future__ import annotations

from .filters import clean_text


def table_record(document, table, doc_id, number):
    from .provenance import item_regions
    from docling_core.transforms.serializer.markdown import _count_header_rows
    _, rows, cells, headers = table_views(table)
    return {"table_id": f"{doc_id}#t{number:03d}", "doc_id": doc_id,
            "source_ref": table.self_ref, "regions": item_regions(document, [(table, None)]),
            "num_rows": table.data.num_rows, "num_cols": table.data.num_cols,
            "header_rows": headers, "rendered_header_rows": _count_header_rows(table),
            "cells": cells, "rows_text": rows}


def tables_path(chunks_path):
    stem = chunks_path.stem
    return chunks_path.with_name((stem[:-7] if stem.endswith("_chunks") else stem) + "_tables.jsonl")


def table_views(table) -> tuple[list[list[str]], list[str], list[dict], int]:
    grid = [[clean_text(cell.text) for cell in row] for row in table.data.grid]
    header_rows = 0
    for row in table.data.grid:
        if row and any(cell.column_header for cell in row):
            header_rows += 1
        else:
            break
    headers = []
    for column in range(table.data.num_cols):
        labels = list(dict.fromkeys(grid[row][column] for row in range(header_rows) if grid[row][column]))
        headers.append(" / ".join(labels))
    rows_text = ["; ".join(f"{headers[column]}: {value}" if headers[column] else value
                           for column, value in enumerate(row)) for row in grid[header_rows:]]
    cells = [{"r": cell.start_row_offset_idx, "c": cell.start_col_offset_idx,
              "row_span": cell.row_span, "col_span": cell.col_span, "text": cell.text,
              "is_header": cell.column_header or cell.row_header or cell.row_section}
             for cell in table.data.table_cells]
    return grid, rows_text, cells, header_rows


def compact_markdown(table) -> str:
    grid, _, _, header_rows = table_views(table)
    if not grid:
        return ""
    header = [" / ".join(dict.fromkeys(row[column] for row in grid[:header_rows] if row[column]))
              for column in range(table.data.num_cols)] if header_rows else [""] * table.data.num_cols
    rows = [header, ["---"] * table.data.num_cols, *grid[header_rows:]]
    return "\n".join("| " + " | ".join(value.replace("|", "\\|") for value in row) + " |" for row in rows)


def merge_adjacent_tables(document):
    document = document.model_copy(deep=True)
    merged, previous = [], None
    for table in list(document.tables):
        if previous is not None and previous.prov and table.prov:
            left_grid, _, _, left_headers = table_views(previous)
            right_grid, _, _, right_headers = table_views(table)
            adjacent = max(p.page_no for p in previous.prov) + 1 == min(p.page_no for p in table.prov)
            if (adjacent and previous.data.num_cols == table.data.num_cols and left_headers > 0
                    and left_headers == right_headers and left_grid[:left_headers] == right_grid[:right_headers]):
                offset = previous.data.num_rows - right_headers
                if len(previous.prov) == 1:
                    previous.prov[0].charspan = (0, previous.data.num_rows)
                for cell in table.data.table_cells:
                    if cell.start_row_offset_idx < right_headers:
                        continue
                    cell = cell.model_copy(deep=True)
                    cell.start_row_offset_idx += offset
                    cell.end_row_offset_idx += offset
                    previous.data.table_cells.append(cell)
                previous.data.num_rows += table.data.num_rows - right_headers
                for prov in table.prov:
                    prov = prov.model_copy(deep=True)
                    prov.charspan = (offset + right_headers, previous.data.num_rows)
                    previous.prov.append(prov)
                merged.append({"first": previous.self_ref, "second": table.self_ref})
                document.delete_items(node_items=[table])
                continue
        previous = table
    return document, merged
