"""Turn a converted document into passage and table chunks with offsets, pages, regions and section paths.

Works for paginated sources (PDF, images, slides), where every chunk keeps page regions, and for flowing
sources (DOCX, HTML, Markdown), where items have no page geometry and chunks carry ``page: null``.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import re
from typing import Any

from docling_core.types.doc import ContentLayer, DoclingDocument, TableItem, TextItem

from ..ingestion.attribution import source_spans
from ..ingestion.chunking import split_table
from ..ingestion.filters import clean_text, dropped_item_reasons, filter_running_lines
from ..ingestion.provenance import item_regions
from ..ingestion.tables import table_views
from .vietnamese import is_vietnamese_marked

BOUNDARY = re.compile(r"[.!?…]+[\"'”’)\]]*\s+|\n+")
OPENERS = "\"'“‘([«"


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Sentence offsets; a boundary needs end punctuation followed by an uppercase letter or digit (any script)."""
    spans, start = [], 0
    for match in BOUNDARY.finditer(text):
        following = text[match.end():match.end() + 2].lstrip(OPENERS)[:1]
        if "\n" in match.group() or following.isupper() or following.isdigit():
            end = match.end()
            piece = text[start:end]
            left = start + len(piece) - len(piece.lstrip())
            right = start + len(piece.rstrip())
            if left < right:
                spans.append((left, right))
            start = end
    piece = text[start:]
    left, right = start + len(piece) - len(piece.lstrip()), start + len(piece.rstrip())
    if left < right:
        spans.append((left, right))
    return spans


def pack(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Pack whole sentences up to max_chars; split an oversized sentence at whitespace."""
    pieces = []
    for start, end in split_sentences(text):
        while end - start > max_chars:
            limit = start + max_chars
            cut = next((i for i in range(limit, start, -1) if text[i].isspace()), limit)
            pieces.append((start, cut))
            start = cut
            while start < end and text[start].isspace():
                start += 1
        if start < end:
            pieces.append((start, end))
    packed: list[tuple[int, int]] = []
    for start, end in pieces:
        if packed and end - packed[-1][0] <= max_chars:
            packed[-1] = (packed[-1][0], end)
        else:
            packed.append((start, end))
    return packed


def language(text: str) -> str:
    """Rough tag: vi if many words carry Vietnamese marks, en if all words are plain ASCII, else und."""
    words = re.findall(r"[^\W\d_]{2,}", text)
    if not words:
        return "und"
    share = sum(is_vietnamese_marked(word) for word in words) / len(words)
    if share >= 0.15:
        return "vi"
    return "en" if all(word.isascii() for word in words) else "und"


def chunk_document(doc: DoclingDocument, doc_id: str, config: dict[str, Any],
                   ocr_pages: set[int]) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """Return (chunks, tables, statistics). Chunk text is cleaned; offsets refer to the joined document text."""
    max_chars = config["chunking"]["max_chars"]
    paragraph = config["chunking"]["strategy"] == "paragraph"
    paginated = bool(doc.pages)
    filters = config["filters"]
    running_drops = 0
    if paginated:
        doc, running_drops = filter_running_lines(doc, filters["margin_band"], filters["frequency"],
                                                  filters["running_block_max_gap_lines"],
                                                  filters["running_block_alignment_lines"],
                                                  filters["running_line_fragment_gap_lines"])
    exclusions = dropped_item_reasons(doc)
    dropped = Counter(running_line=running_drops)
    chunks: list[dict] = []
    tables: list[dict] = []
    table_ids: dict[str, str] = {}
    caption_refs = {ref.cref for table in doc.tables for ref in table.captions}
    section_stack: list[tuple[int, str]] = []
    buffer: list[tuple[str, Any, int | None]] = []

    def emit(kind: str, text: str, items: list[tuple[Any, int | None]], **extra: Any) -> None:
        if not text.strip():
            return
        regions = item_regions(doc, items) if paginated else []
        spans = source_spans(doc, text, items) if paginated else []
        pages = sorted({region["page"] for region in regions} | {span["page"] for span in spans})
        chunks.append({"chunk_id": f"{doc_id}#c{len(chunks):05d}", "doc_id": doc_id, "type": kind, "text": text,
                       "section": section_stack[-1][1] if section_stack else None,
                       "section_path": [value for _, value in section_stack],
                       "page": pages[0] if pages else None, "pages": pages, "regions": regions,
                       "source_spans": spans, "table_id": None, "row_start": None, "row_end": None,
                       "language": language(text), "ocr": bool(set(pages) & ocr_pages), **extra})

    def flush() -> None:
        if not buffer:
            return
        text = "\n".join(value for value, _, _ in buffer)
        for start, end in pack(text, max_chars):
            selected, position = [], 0
            for value, item, page in buffer:
                if position < end and start < position + len(value):
                    selected.append((item, page))
                position += len(value) + 1
            emit("text", text[start:end], selected)
        buffer.clear()

    def add_text(value: str, item: Any, page: int | None) -> None:
        cleaned = clean_text(value)
        if not cleaned:
            return
        if buffer and paginated and page != buffer[-1][2]:
            continuation = (paragraph and page == (buffer[-1][2] or 0) + 1 and buffer[-1][0][-1] not in ".!?:…"
                            and (cleaned[0].islower() or cleaned[0].isdigit()))
            if not continuation:
                flush()
        buffer.append((cleaned, item, page))

    for item, _ in doc.iterate_items(included_content_layers=set(ContentLayer), traverse_pictures=True):
        label = getattr(getattr(item, "label", None), "value", "unknown")
        if item.self_ref in exclusions:
            dropped[exclusions[item.self_ref]] += 1
            continue
        prov = getattr(item, "prov", None) or []
        if paginated and not prov:
            dropped["no_provenance"] += 1
            continue
        page = prov[0].page_no if prov else None
        if label in {"section_header", "title"} and isinstance(item, TextItem):
            heading = clean_text(item.text)
            if heading:
                flush()
                level = getattr(item, "level", 1) if label == "section_header" else 0
                section_stack[:] = [(depth, value) for depth, value in section_stack if depth < level]
                section_stack.append((level, heading))
        elif isinstance(item, TableItem):
            flush()
            if not item.data.table_cells or not any(cell.text.strip() for cell in item.data.table_cells):
                dropped["empty_table"] += 1
                continue
            table_id = f"{doc_id}#t{len(tables):04d}"
            grid, rows_text, cells, header_rows = table_views(item)
            tables.append({"table_id": table_id, "doc_id": doc_id, "source_ref": item.self_ref,
                           "regions": item_regions(doc, [(item, None)]) if paginated else [],
                           "num_rows": item.data.num_rows, "num_cols": item.data.num_cols,
                           "header_rows": header_rows, "cells": cells, "rows_text": rows_text})
            table_ids[item.self_ref] = table_id
            caption = clean_text(item.caption_text(doc))
            next_row = header_rows
            items = [(item, None), *[(ref.resolve(doc), None) for ref in item.captions]]
            for part in split_table(item.export_to_markdown(doc=doc), caption, max_chars):
                rows = max(0, sum(line.strip().startswith("|") for line in part.splitlines()) - 2)
                emit("table", part, items, table_id=table_id, row_start=next_row, row_end=next_row + rows)
                next_row += rows
        elif isinstance(item, TextItem):
            if item.self_ref in caption_refs:
                continue
            if len({p.page_no for p in prov}) > 1:
                for p in prov:
                    add_text(item.text[p.charspan[0]:p.charspan[1]], item, p.page_no)
            else:
                add_text(item.text, item, page)
    flush()
    position = 0
    for chunk in chunks:
        chunk["char_start"], chunk["char_end"] = position, position + len(chunk["text"])
        chunk["sha256"] = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
        position += len(chunk["text"]) + 2
    statistics = {"text_chunks": sum(c["type"] == "text" for c in chunks),
                  "table_chunks": sum(c["type"] == "table" for c in chunks), "tables": len(tables),
                  "characters": sum(len(c["text"]) for c in chunks), "dropped": dict(sorted(dropped.items()))}
    return chunks, tables, statistics
