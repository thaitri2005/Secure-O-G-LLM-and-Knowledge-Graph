"""Render controlled drilling PDFs and native snapshots from frozen annotations."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pymupdf
from docling_core.types.doc import BoundingBox, DoclingDocument, ProvenanceItem, Size, TableCell, TableData


FONT_NAME = "DrillingBenchmark"
FONT_SIZE = 9
ROW_HEIGHT = 17
MARGIN = 40


def read_manifest(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_grid(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = [[" ".join(value.split()) for value in row] for row in csv.reader(stream)]
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError(f"nonrectangular gold grid: {path}")
    return rows


def page_pair(pdf, native, width, height, font_path):
    page = pdf.new_page(width=width, height=height)
    page.insert_font(fontname=FONT_NAME, fontfile=str(font_path))
    native.add_page(page_no=len(pdf), size=Size(width=width, height=height))
    return page


def provenance(page, left, top, right, bottom, length):
    return ProvenanceItem(page_no=page.number + 1, bbox=BoundingBox(l=left, t=top, r=right, b=bottom),
                          charspan=(0, length))


def grid_parts(rows, entry):
    header = entry["header_rows"]
    parts = entry.get("parts")
    if not parts:
        return [(rows, header)]
    body = rows[header:]
    rendered = []
    for pos, part in enumerate(parts):
        first, last = part["first_row"], part["last_row"]
        if not 1 <= first <= last + 1 <= len(body) + 1:
            raise ValueError(f'{entry["id"]}: invalid annotated body range {first}–{last}')
        keep_header = header if not pos or entry["header_repeated_on_continuation"] else 0
        rendered.append((rows[:keep_header] + body[first - 1:last], keep_header))
    return rendered


def render_grid(target, entry, rows, font_path, font):
    parts = grid_parts(rows, entry)
    width_by_column = [
        max(42, max(font.text_length(row[index], fontsize=FONT_SIZE) for row in rows) + 22)
        for index in range(len(rows[0]))
    ]
    width = max(600, round(sum(width_by_column) + 2 * MARGIN + 1))
    height = max(800, max(len(part) for part, _ in parts) * ROW_HEIGHT + 120)
    native = DoclingDocument(name=entry["id"])
    with pymupdf.open() as pdf:
        for index, (part, header_rows) in enumerate(parts):
            page = page_pair(pdf, native, width, height, font_path)
            top = height - len(part) * ROW_HEIGHT - 70 if index + 1 < len(parts) else 85
            cells = []
            for row_index, row in enumerate(part):
                left = MARGIN
                y = top + row_index * ROW_HEIGHT + 12
                for col_index, value in enumerate(row):
                    if value:
                        page.insert_text((left + 5, y), value, fontname=FONT_NAME, fontsize=FONT_SIZE)
                    cells.append(TableCell(text=value, start_row_offset_idx=row_index, end_row_offset_idx=row_index + 1,
                                           start_col_offset_idx=col_index, end_col_offset_idx=col_index + 1,
                                           column_header=row_index < header_rows))
                    left += width_by_column[col_index]
            bounds = provenance(page, MARGIN, top, MARGIN + sum(width_by_column), top + len(part) * ROW_HEIGHT, len(part))
            native.add_table(data=TableData(num_rows=len(part), num_cols=len(rows[0]), table_cells=cells), prov=bounds)
        pdf.save(target, no_new_id=True)
    return native, len(parts)


def render_form(target, entry, font_path, font):
    native = DoclingDocument(name=entry["id"])
    fields = [(" ".join(p["key"].split()), " ".join(p["value"].split())) for p in entry["pairs"]]
    lines = ["Daily Drilling Report", *(f"{key} {value}".strip() for key, value in fields), "Operations Summary"]
    width = max(600, round(2 * MARGIN + max(font.text_length(line, fontsize=FONT_SIZE) for line in lines) + 1))
    height = max(800, len(lines) * ROW_HEIGHT + 120)
    with pymupdf.open() as pdf:
        page = page_pair(pdf, native, width, height, font_path)
        for index, line in enumerate(lines):
            y = 66 + index * ROW_HEIGHT
            page.insert_text((MARGIN, y), line, fontname=FONT_NAME, fontsize=FONT_SIZE)
            right = MARGIN + font.text_length(line, fontsize=FONT_SIZE)
            native.add_text(label="text", text=line, prov=provenance(page, MARGIN, y - 9, right, y + 2, len(line)))
        pdf.save(target, no_new_id=True)
    return native, fields


def build_drilling_samples(repo, root, font_path):
    gold = repo / "data/gold/ingestion"
    annotations = repo / "explorations/ingestion/annotations"
    font = pymupdf.Font(fontfile=str(font_path))
    jobs = [(gold / "tables.json", gold / "tables", "repository", "grid")]
    for group in ("development", "held-out"):
        subset = annotations / group
        jobs.extend([(subset / "continued-tables/continued_tables.json", subset / "continued-tables", group, "grid"),
                     (subset / "forms/forms.json", subset / "forms", group, "form")])
    for manifest, directory, group, kind in jobs:
        for entry in read_manifest(manifest):
            if entry["status"] != "corrected" or (kind == "grid" and entry["format"] != "grid"):
                continue
            name = entry["id"].replace("_daily_", "_dailyreport_") if kind == "form" else entry["id"]
            target = root / f"{name}.pdf"
            annotation = directory / Path(entry["csv"]).name
            metadata = {"source_document": entry["doc_id"], "source_pages": entry.get("pages", [entry.get("page")]),
                        "annotation_group": group, "annotation_path": annotation.relative_to(repo).as_posix(),
                        "annotation_sha256": digest(annotation), "annotation_manifest_sha256": digest(manifest),
                        "source_pdf_sha256": entry.get("source_sha256"), "font_sha256": digest(font_path),
                        "kind": kind, "input": "rendered_from_drilling_annotations"}
            if kind == "grid":
                native, pages = render_grid(target, entry, read_grid(annotation), font_path, font)
                pairs = []
            else:
                native, pairs = render_form(target, entry, font_path, font)
                pages = 1
            yield name, target, native.model_dump_json(), pages, pairs, metadata
