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


TABLE_MARKDOWN_MODES = ("docling", "span_once", "span_once_keyed")


def table_markdown(table, doc, mode: str = "docling") -> str:
    """Markdown of a table as ``export_to_markdown`` renders it, or with each merged cell's text written once.

    ``docling`` returns Docling's own output. ``span_once`` keeps the text of a cell that spans several rows or
    columns at its top-left grid position and leaves the other covered positions empty. A header cell that spans
    columns of a table with a stacked header (more than one header row) keeps its text in each spanned column,
    because the flattened column label ("Group - Sub") is then the column's meaning, not a duplicate. Row and
    column counts, header rows and the Markdown line count never change. The text is returned unchanged when the
    table has no merged cell, holds a nested (rich) cell, has overlapping cells or Docling's table text cannot be
    reproduced exactly from the grid (a guard against a different serializer version).

    ``span_once_keyed`` renders like ``span_once`` but keeps the text of a row-spanning *key* cell on every row it
    covers: a body cell that starts in the first column or is flagged as a row header. The decision uses only the
    span structure and the cell's position, never text equality. A row-spanning value cell elsewhere is still
    written once. ``corpus.chunking`` also keeps the chunk row boundaries of the ``docling`` rendering in this mode.
    """
    if mode not in TABLE_MARKDOWN_MODES:
        raise ValueError(f"table_markdown mode must be one of {TABLE_MARKDOWN_MODES}")
    original = table.export_to_markdown(doc=doc)
    if mode == "docling":
        return original
    from docling_core.transforms.serializer.markdown import _count_header_rows, _flatten_header_rows
    from docling_core.types.doc.document import RichTableCell
    from tabulate import _column_type, tabulate
    grid = table.data.grid
    cells = table.data.table_cells
    if (not grid or not any(c.end_row_offset_idx - c.start_row_offset_idx > 1
                            or c.end_col_offset_idx - c.start_col_offset_idx > 1 for c in cells)
            or any(isinstance(cell, RichTableCell) for row in grid for cell in row)):
        return original
    inside = [c for c in cells if c.start_row_offset_idx < table.data.num_rows
              and c.start_col_offset_idx < table.data.num_cols]
    if any(grid[c.start_row_offset_idx][c.start_col_offset_idx] is not c for c in inside):
        return original  # overlapping cells: a covered position holds another cell
    headers = _count_header_rows(table)
    keyed = mode == "span_once_keyed"

    def text_of(row: int, column: int, once: bool) -> str:
        cell = grid[row][column]
        origin = (cell.start_row_offset_idx, cell.start_col_offset_idx) == (row, column)
        keep = origin or not once or (row < headers and headers > 1 and cell.start_row_offset_idx == row)
        if keyed and not keep and row >= headers and column == cell.start_col_offset_idx and cell.row_span > 1:
            keep = cell.start_col_offset_idx == 0 or bool(cell.row_header)  # row key of a row-spanning cell
        return (cell.text or "").replace("\n", " ").replace("|", "&#124;") if keep else ""

    def rows_of(once: bool) -> list[list[str]]:
        return [[text_of(r, c, once) for c in range(len(grid[r]))] for r in range(len(grid))]

    def render(once: bool, alignment_rows: list[list[str]]) -> str:
        rows = rows_of(once)
        header = _flatten_header_rows(rows[:headers], len(rows[0]))
        body = alignment_rows[headers:]
        # Column alignment is decided on the unmodified body so that only cell texts change, not the separator row.
        colalign = tuple("right" if _column_type([row[c] if c < len(row) else "" for row in body]) in (int, float)
                         else "left" for c in range(len(rows[0]))) if body else None
        return tabulate(rows[headers:], headers=header, tablefmt="github", disable_numparse=True, colalign=colalign)

    plain_rows = rows_of(False)
    reference = render(False, plain_rows)
    if original.count(reference) != 1:
        return original
    return original.replace(reference, render(True, plain_rows))


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
