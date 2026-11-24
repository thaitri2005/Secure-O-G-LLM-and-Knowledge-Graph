"""Project source-proven overlaps out of retrieval text while retaining the K1 evidence."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import gzip
import json
from pathlib import Path
import re
import unicodedata

from ..numeric_cells import compact
from ..process import is_complete
from ..store import read_jsonl
from ...ingestion.tables import table_views
from .crossrep import UNESCAPED_PIPE, analyse_table, load_config, parse_table_chunk
from .form_overlap import valid_box, covers
from .signals import Registry

CHECK = "table_source_overlap"
REASON = "TABLE_SOURCE_DUPLICATE"
SOURCE = "textlayer:hourly_operations:"


def tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\w+|[^\w\s]", unicodedata.normalize("NFC", text)))


@dataclass(frozen=True)
class SourceTable:
    table_id: str
    box: list
    context: dict
    lines: tuple[tuple[str, ...], ...]

    def matches(self, box, text):
        if not valid_box(box) or not covers(self.box, box):
            return False
        sequence = tokens(text)
        size = len(sequence)
        return bool(size and any(line[i:i + size] == sequence for line in self.lines
                                 for i in range(len(line) - size + 1)))


def positioned_box(bbox, height):
    if bbox is None:
        return None
    box = bbox.to_top_left_origin(page_height=height)
    return [box.l, box.t, box.r, box.b]


def load_native_document(corpus: Path, fingerprint: str, file: dict):
    from docling_core.types.doc import DoclingDocument

    doc_id = file["doc_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", doc_id) or not re.fullmatch(r"[0-9a-f]{16}", fingerprint):
        return None, {}
    directory = corpus / "work" / doc_id / fingerprint
    try:
        files = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["files"]
        if not isinstance(files, dict) or not {"document.json", "docling.json.gz"} <= files.keys() or not is_complete(directory):
            return None, {}
        record = json.loads((directory / "document.json").read_text(encoding="utf-8"))
        if (record["doc_id"], record["sha256"]) != (doc_id, file["sha256"]):
            return None, {}
        pages = {row["page"]: row for row in record["pages"]}
        with gzip.open(directory / "docling.json.gz", "rt", encoding="utf-8") as stream:
            return DoclingDocument.model_validate_json(stream.read()), pages
    except (OSError, ValueError, KeyError, EOFError):
        return None, {}


def load_native(corpus: Path, fingerprint: str, file: dict):
    native, pages = load_native_document(corpus, fingerprint, file)
    return native, {number for number, row in pages.items() if row["mode"] == "text" and row["rotation"] == 0
                    and not (row.get("orientation") or {}).get("normalized")}


def source_tables(tables, chunks, config):
    by_page = defaultdict(list)
    for table in tables:
        parts = table["parts"]
        if len(parts) != 1 or not parts[0]["source_ref"].startswith(SOURCE):
            continue
        part = parts[0]
        children = sorted(chunks[table["table_id"]], key=lambda row: row["child_index"])
        if (not children or not valid_box(part["bbox"]) or children[0]["row_start"] != table["header_rows"]
                or any(child["pages"] != [part["page"]] or child["ocr"] or child["quality"] != "ok"
                       or child["context"] != children[0]["context"] for child in children)
                or analyse_table(table, children, config)):
            continue
        caption = parse_table_chunk(children[0]["text"])["caption"]
        lines = tuple(tokens(text) for text in [*caption, *(" ".join(row) for row in table["grid"])])
        by_page[table["file_id"], part["page"]].append(SourceTable(table["table_id"], part["bbox"],
                                                                  children[0]["context"], lines))
    return {key: entries[0] for key, entries in by_page.items() if len(entries) == 1}


def text_edits(chunk, items, height, table):
    edits = []
    for span in chunk["source_spans"]:
        item = items.get(span["source_ref"])
        if item is None or len(item.prov) != 1 or span["page"] != chunk["page"]:
            continue
        source = item.prov[0]
        start, end = span["start"], span["end"]
        source_start, source_end = span["source_start"], span["source_end"]
        text = chunk["text"][start:end]
        if (source.page_no == chunk["page"] and 0 <= start < end <= len(chunk["text"])
                and 0 <= source_start < source_end <= len(item.text)
                and source.charspan[0] <= source_start < source_end <= source.charspan[1]
                and tokens(item.text[source_start:source_end]) == tokens(text)
                and table.matches(positioned_box(source.bbox, height), text)):
            edits.append({"source_ref": span["source_ref"], "start": start, "end": end})
    edits.sort(key=lambda edit: edit["start"])
    if any(left["end"] > right["start"] for left, right in zip(edits, edits[1:])):
        return []
    return edits


def covered_cells(record, item, height, source):
    """Match the untrimmed native grid, accounting for documented focused edits elsewhere in it."""
    grid, _, _, headers = table_views(item)
    repairs = {(row["r"], row["c"]): row for row in record["parts"][0].get("numeric_repairs", ()) if "focus" in row}
    if headers != record["header_rows"]:
        return set()
    expected = [row.copy() for row in grid] if repairs else grid
    for (r, c), patch in repairs.items():
        if not headers <= r < len(grid) or not 0 <= c < len(grid[r]) or compact(grid[r][c]) != patch["previous"]:
            return set()
        expected[r][c] = patch["value"]
    if expected != record["grid"]:
        return set()
    native_grid = item.data.grid
    cells = set()
    for cell in item.data.table_cells:
        if (not headers <= cell.start_row_offset_idx < cell.end_row_offset_idx <= len(grid)
                or not 0 <= cell.start_col_offset_idx < cell.end_col_offset_idx <= record["num_cols"]
                or not source.matches(positioned_box(cell.bbox, height), cell.text)):
            continue
        for row in range(cell.start_row_offset_idx, cell.end_row_offset_idx):
            for col in range(cell.start_col_offset_idx, cell.end_col_offset_idx):
                # The native table's grid must assign this position to this very cell.
                if (row, col) not in repairs and native_grid[row][col] is cell:
                    cells.add((row, col))
    return cells


def mask_cells(chunk, cells):
    """Clear proved duplicates from Markdown body cells without reserializing adjacent cells."""
    lines = chunk["text"].splitlines(keepends=True)
    row_lines = [i for i, line in enumerate(lines) if line.lstrip().startswith("|")][2:]
    touched = []
    for row, index in enumerate(row_lines, chunk["row_start"]):
        pieces = UNESCAPED_PIPE.split(lines[index])
        if pieces[0].strip() or pieces[-1].strip():
            continue
        for col in range(len(pieces) - 2):
            if (row, col) in cells and pieces[col + 1].strip():
                touched.append([row, col])
                pieces[col + 1] = " "
        lines[index] = "|".join(pieces)
    return "".join(lines), touched


class TableOverlap:
    """Retrieve canonical hourly tables and omit only corroborated overlapping parts of old chunks."""

    def __init__(self, release: Path, corpus: Path | None):
        self.findings = defaultdict(list)
        self.replacements = {}
        if corpus is None:
            return
        tables = list(read_jsonl(release / "tables.jsonl"))
        file_ids = {table["file_id"] for table in tables for part in table["parts"] if part["source_ref"].startswith(SOURCE)}
        if not file_ids:
            return
        related = defaultdict(list)
        table_chunks = defaultdict(list)
        for chunk in read_jsonl(release / "chunks.jsonl"):
            if chunk["file_id"] in file_ids:
                related[chunk["file_id"]].append(chunk)
                if chunk["type"] == "table":
                    table_chunks[chunk["table_id"]].append(chunk)
        config = load_config()
        sources = source_tables(tables, table_chunks, config)
        fingerprint = json.loads((release / "manifest.json").read_text(encoding="utf-8"))["corpus_fingerprint"]
        records = {table["table_id"]: table for table in tables}
        for file in read_jsonl(release / "files.jsonl"):
            file_id = file["file_id"]
            if file_id not in file_ids:
                continue
            native, upright = load_native(corpus, fingerprint, file)
            if native is None:
                continue
            items = {item.self_ref: item for item in native.texts}
            native_tables = {item.self_ref: item for item in native.tables}
            overlaps = {}
            for chunk in related[file_id]:
                page = chunk["page"]
                source = sources.get((file_id, page))
                if (source is None or page not in upright or chunk["pages"] != [page] or chunk["ocr"]
                        or chunk["context"] != source.context or page not in native.pages):
                    continue
                height = native.pages[page].size.height
                evidence = {"chunk_id": chunk["chunk_id"], "retained_table_id": source.table_id}
                if chunk["type"] == "text":
                    edits = text_edits(chunk, items, height, source)
                    if not edits:
                        continue
                    text = chunk["text"]
                    for edit in reversed(edits):
                        text = text[:edit["start"]] + "\n" + text[edit["end"]:]
                    evidence["removed_spans"] = edits
                    text = text.strip()
                elif chunk["type"] == "table" and chunk["quality"] == "review" and chunk["table_id"] != source.table_id:
                    table_id = chunk["table_id"]
                    if table_id not in overlaps:
                        record = records[table_id]
                        parts = record["parts"]
                        item = native_tables.get(parts[0]["source_ref"]) if len(parts) == 1 and parts[0]["page"] == page else None
                        cells = set()
                        if (item is not None and len(item.prov) == 1 and item.prov[0].page_no == page
                                and not analyse_table(record, table_chunks[table_id], config)):
                            cells = covered_cells(record, item, height, source)
                        overlaps[table_id] = cells
                    text, touched = mask_cells(chunk, overlaps[table_id])
                    if not touched:
                        continue
                    evidence["removed_cells"] = touched
                else:
                    continue
                self.replacements[chunk["chunk_id"]] = text
                self.findings[file_id, page].append(evidence)

    def project(self, rows):
        for row in rows:
            chunk_id = row["chunk_id"]
            if chunk_id not in self.replacements:
                yield row
            elif self.replacements[chunk_id]:
                yield dict(row, text=self.replacements[chunk_id])

    def summary(self):
        parts = [part for findings in self.findings.values() for part in findings]
        return {"duplicate_table_spans_removed": sum(len(part.get("removed_spans", ())) for part in parts),
                "duplicate_table_cells_removed": sum(len(part.get("removed_cells", ())) for part in parts)}


def register_table_overlap(registry: Registry, load_overlap) -> Registry:
    registry.register_reason(REASON, "INFO", "An overlapping passage or native cell is covered by a source-backed hourly table.", CHECK)

    def check(context, entity):
        if context.validator and context.validator["status"] != "pass":
            return []
        ids = entity["ids"]
        parts = load_overlap().findings.get((ids["file_id"], ids["page"]))
        return [registry.signal(REASON, "page", ids, evidence={"parts": parts})] if parts else []

    registry.register_check(CHECK, check, "page", "1", limitations=(
        "Requires a uniquely attributed, source-backed hourly table and matching upright text pages in the conversion cache.",
        "Checks only whole native spans and body cells with matching content inside the same source region and context.",
    ))
    return registry
