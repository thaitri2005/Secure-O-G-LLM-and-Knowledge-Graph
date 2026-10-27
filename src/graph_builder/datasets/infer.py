"""Draft a mapping from a sample of a CSV or Excel file, for a person to review and complete."""
from __future__ import annotations

import csv
from itertools import islice
from pathlib import Path
import re
from typing import Any

from ..corpus.catalog import slug
from .readers import detect_encoding, iter_rows
from .values import ValueProblem, parse_value

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d", "%d-%m-%Y", "%d.%m.%Y"]
CANDIDATES = [{"type": "integer"}, {"type": "decimal"}, {"type": "decimal", "decimal_mark": ",", "thousands": "."},
              *({"type": "date", "formats": [pattern]} for pattern in DATE_FORMATS),
              {"type": "boolean", "true_values": ["true", "True", "TRUE", "yes", "Yes", "có", "Có"],
               "false_values": ["false", "False", "FALSE", "no", "No", "không", "Không"]}]


def field_name(header: str, index: int, used: set[str]) -> str:
    name = slug(header, 60).replace("-", "_") or f"column_{index + 1}"
    if name[0].isdigit():
        name = f"c_{name}"
    base, counter = name, 2
    while name in used:
        name, counter = f"{base}_{counter}", counter + 1
    used.add(name)
    return name


def infer_type(values: list[Any]) -> dict[str, Any]:
    present = [value for value in values if value not in (None, "")]
    if not present:
        return {"type": "string"}
    for candidate in CANDIDATES:
        try:
            for value in present:
                parse_value(candidate, value.strip() if isinstance(value, str) else value)
        except (ValueProblem, TypeError):
            continue
        if candidate["type"] == "integer" and any(isinstance(v, str) and len(v.strip()) > 1 and v.strip().startswith("0")
                                                  for v in present):
            continue  # zero-padded codes (0827) are identifiers, not numbers
        return dict(candidate)
    return {"type": "string"}


def infer_mapping(path: Path, sample_rows: int = 5000, sheet: str | None = None) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        layout: dict[str, Any] = {"type": "xlsx", "header": True, **({"sheet": sheet} if sheet else {})}
    else:
        encoding = detect_encoding(path, None)
        with path.open(encoding=encoding, newline="") as stream:
            sample = stream.read(64 * 1024)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","
        first = next(csv.reader(sample.splitlines()[:1], delimiter=delimiter), [])
        header = bool(first) and not any(infer_type([cell])["type"] != "string" for cell in first if cell.strip())
        layout = {"type": "csv", "delimiter": delimiter, "header": header, "encoding": encoding}
    rows = [row for _, row in islice(iter_rows(path, None, layout), sample_rows)]
    if not rows:
        raise ValueError("The file has no data rows")
    headers = list(rows[0]) if isinstance(rows[0], dict) else [f"column_{i + 1}" for i in range(len(rows[0]))]
    used: set[str] = set()
    columns, key = [], None
    for index, header in enumerate(headers):
        values = [row[header] if isinstance(row, dict) else row[index] for row in rows]
        column = {"name": field_name(header, index, used), **infer_type(values)}
        if isinstance(rows[0], dict) and column["name"] != header:
            column["source"] = header
        present = [value for value in values if value not in (None, "")]
        if key is None and len(present) == len(values) and len(set(map(str, present))) == len(present):
            key = column["name"]
        columns.append(column)
    table = re.sub(r"[^a-z0-9_]", "_", slug(path.stem, 40).replace("-", "_")) or "records"
    dataset = slug(path.stem, 40)
    return {
        "dataset_id": dataset, "title": path.stem, "publisher": "", "license": {"id": "unspecified", "url": ""},
        "allowed_hosts": [],
        "sources": [{"source_id": table.replace("_", "-"), "table": table, "path": path.resolve().as_posix()}],
        "tables": {table: {"layout": layout, "columns": columns,
                           "id": f"{dataset}:{table}:" + ("{" + key + "}" if key else "{_row}"),
                           **({"key": [key]} if key else {}), "checks": []}},
        "graph": {"nodes": [], "edges": []}, "error_policy": {"max_errors": 0},
        "_note": f"Drafted from {len(rows)} sample rows; review types, key, checks and graph before importing.",
    }
