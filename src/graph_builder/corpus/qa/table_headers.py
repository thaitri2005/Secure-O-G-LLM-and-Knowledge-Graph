"""Supply a printed header as retrieval context on a continuation with no physical header."""
from __future__ import annotations

from ..ops_tables import markdown
from ..store import read_jsonl
from ..table_join import labels_of
from .crossrep import parse_table_chunk


def continuation_headers(release):
    headers = {}
    for table in read_jsonl(release / "tables.jsonl"):
        if table["join"]["status"] != "joined" or not table["header_rows"]:
            continue
        labels = labels_of(table)
        origin = table["parts"][0]["page"]
        for part in table["parts"][1:]:
            if not part["header"]:
                headers[table["table_id"], part["page"]] = (origin, labels, part["row_start"], part.get("rendered_body_header_rows", 0))
    return headers


def add_continuation_headers(rows, headers):
    for row in rows:
        header = headers.get((row.get("table_id"), row.get("page")))
        if header and row["type"] == "table" and row["pages"] == [row["page"]]:
            origin, labels, row_start, body_header = header
            text = row["text"]
            parsed = parse_table_chunk(text)
            if parsed["separator_ok"] and (body_header or not any(parsed["header"])):
                lines = text.split("\n")
                first_line = next(i for i, line in enumerate(lines) if line.strip().startswith("|"))
                after_separator = next(i for i in range(first_line + 1, len(lines)) if lines[i].strip().startswith("|")) + 1
                if body_header and row["row_start"] == row_start:
                    lines.insert(after_separator, lines[first_line])
                lines[first_line] = markdown([labels]).split("\n", 1)[0]
                text = "\n".join(lines)
            else:
                text = "Table columns (page " + str(origin) + "): " + " | ".join(labels) + "\n" + text
            yield dict(row, text=text, table_header_page=origin)
        else:
            yield row
