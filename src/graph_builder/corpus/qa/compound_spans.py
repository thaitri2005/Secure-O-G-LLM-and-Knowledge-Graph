"""Compact repeated horizontal body spans in oversized retrieval chunks."""
from collections import Counter

from ..store import read_jsonl
from .crossrep import parse_table_chunk
from .markdown_syntax import normalise_cell
from .ruled_overlap import positions
from .table_overlap import mask_cells


def compact_chunk(table, chunk):
    start, end = chunk["row_start"], chunk["row_end"]
    if not table or not 0 <= start < end <= len(table["grid"]):
        return chunk["text"], []
    parsed = parse_table_chunk(chunk["text"])
    rows = parsed["rows"]
    width = table["num_cols"]
    if (not parsed["separator_ok"] or parsed["stray"] or len(parsed["header"]) != width
            or len(rows) != end - start or any(len(row) != width for row in rows)):
        return chunk["text"], []
    owners = Counter(slot for cell in table["cells"] for slot in positions(cell))
    removable = set()
    for cell in table["cells"]:
        r, c, span = cell["r"], cell["c"], cell["col_span"]
        if (cell["is_header"] or cell["row_span"] != 1 or span < 2 or not max(start, table["header_rows"]) <= r < end
                or c + span > width or len(table["grid"][r]) != width):
            continue
        value = normalise_cell(cell["text"], None)
        rendered = rows[r - start][c:c + span]
        if (value and rendered[0] == value and all(text in ("", value) for text in rendered)
                and all(owners[r, column] == 1 and normalise_cell(table["grid"][r][column], None) == value
                        for column in range(c, c + span))):
            removable.update((r, column) for column in range(c + 1, c + span))
    return mask_cells(chunk, removable) if removable else (chunk["text"], [])


def project(rows, release, budget, edits):
    tables = None
    for row in rows:
        if row["type"] == "table" and len(row["text"]) > budget:
            if tables is None:
                tables = {table["table_id"]: table for table in read_jsonl(release / "tables.jsonl")}
            text, positions_removed = compact_chunk(tables.get(row["table_id"]), row)
            if positions_removed:
                edits.append({"chunk_id": row["chunk_id"], "table_id": row["table_id"], "page": row["page"],
                              "before_characters": len(row["text"]), "after_characters": len(text),
                              "removed_positions": positions_removed})
                row = dict(row, text=text)
        yield row
