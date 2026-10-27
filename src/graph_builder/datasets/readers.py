"""Stream rows from delimited text, Excel and JSON-lines files, optionally inside a ZIP archive."""
from __future__ import annotations

from contextlib import contextmanager
import csv
import io
import json
from pathlib import Path
from typing import Any, BinaryIO, Iterator
import zipfile

MAX_MEMBER_BYTES = 2 * 1024 ** 3
ENCODINGS = ("utf-8", "utf-8-sig", "cp1258", "cp1252", "latin-1")


@contextmanager
def open_binary(path: Path, member: str | None) -> Iterator[BinaryIO]:
    if member is None:
        with path.open("rb") as stream:
            yield stream
        return
    with zipfile.ZipFile(path) as archive:
        try:
            info = archive.getinfo(member)
        except KeyError:
            raise ValueError(f"{path.name} has no member {member!r}") from None
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f"{member} is larger than {MAX_MEMBER_BYTES} bytes")
        with archive.open(info) as stream:
            yield stream


def detect_encoding(path: Path, member: str | None) -> str:
    """Pick the first encoding that decodes a 4 MiB sample; utf-8-sig wins when a BOM is present."""
    with open_binary(path, member) as stream:
        sample = stream.read(4 * 1024 * 1024)
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    for encoding in ENCODINGS:
        try:
            # A multibyte character may be cut at the sample end; ignore only that tail.
            sample.decode(encoding) if len(sample) < 4 * 1024 * 1024 else sample[:-4].decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin-1"


def iter_rows(path: Path, member: str | None, layout: dict[str, Any]) -> Iterator[tuple[int, dict[str, Any] | list[Any]]]:
    """Yield (row number in the file, row). Rows are dicts when the file has a header, otherwise lists.

    Row numbers count data rows from 1, after skipped lines and the header.
    """
    kind = layout["type"]
    if kind == "csv":
        encoding = layout.get("encoding", "auto")
        if encoding == "auto":
            encoding = detect_encoding(path, member)
        with open_binary(path, member) as stream:
            text = io.TextIOWrapper(stream, encoding=encoding, newline="")
            for _ in range(layout.get("skip_rows", 0)):
                text.readline()
            reader = csv.reader(text, delimiter=layout.get("delimiter", ","), quotechar=layout.get("quote", '"'),
                                strict=True)
            header = [name.strip() for name in next(reader, [])] if layout.get("header", True) else None
            for number, row in enumerate(reader, 1):
                if not any(cell.strip() for cell in row) and layout.get("skip_blank", True):
                    continue
                if header is None:
                    yield number, row
                else:
                    if len(row) != len(header):
                        raise ValueError(f"row {number}: {len(row)} cells but the header has {len(header)}")
                    yield number, dict(zip(header, row))
    elif kind == "xlsx":
        from openpyxl import load_workbook
        with open_binary(path, member) as stream:
            data = io.BytesIO(stream.read()) if member else None
        workbook = load_workbook(data or path, read_only=True, data_only=True)
        try:
            sheet = workbook[layout["sheet"]] if layout.get("sheet") else workbook.worksheets[0]
            rows = sheet.iter_rows(values_only=True)
            for _ in range(layout.get("skip_rows", 0)):
                next(rows, None)
            header = None
            if layout.get("header", True):
                header = [str(cell).strip() if cell is not None else "" for cell in next(rows, ())]
            for number, row in enumerate(rows, 1):
                cells = [cell.strip() if isinstance(cell, str) else cell for cell in row]
                if all(cell is None or cell == "" for cell in cells):
                    continue
                if header is None:
                    yield number, cells
                else:
                    cells = (cells + [None] * len(header))[:len(header)]
                    yield number, dict(zip(header, cells))
        finally:
            workbook.close()
    elif kind == "jsonl":
        with open_binary(path, member) as stream:
            for number, line in enumerate(io.TextIOWrapper(stream, encoding="utf-8"), 1):
                if line.strip():
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError(f"line {number}: expected a JSON object")
                    yield number, value
    else:
        raise ValueError(f"unknown file type {kind!r}")
