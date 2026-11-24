"""Turn a converted document into passage and table chunks with offsets, pages, regions and section paths.

Works for paginated sources (PDF, images, slides), where every chunk keeps page regions, and for flowing
sources (DOCX, HTML, Markdown), where items have no page geometry and chunks carry ``page: null``.
"""
from __future__ import annotations

from collections import Counter
from functools import cache
import hashlib
from pathlib import Path
import re
from typing import Any

from docling_core.types.doc import ContentLayer, DoclingDocument, ListItem, TableItem, TextItem

from ..ingestion.attribution import source_spans
from ..ingestion.chunking import split_table
from ..ingestion.filters import clean_text, dropped_item_reasons, filter_running_lines
from ..ingestion.provenance import item_regions
from ..ingestion.tables import table_markdown, table_views
from .config import keep_pattern
from .label_value import correct_document, label_value_settings
from .quarantine import dropped_items, empty_report as empty_quarantine, quarantine_settings, scan_document, scan_tables
from .vietnamese import is_vietnamese_marked

BOUNDARY = re.compile(r"[.!?…]+[\"'”’)\]]*\s+|\n+")
OPENERS = "\"'“‘([«"


def restore_list_markers(doc: DoclingDocument) -> None:
    """Restore source-backed markers on items with unambiguous provenance before chunking."""
    for item in doc.texts:
        if not isinstance(item, ListItem) or len(item.prov) > 1:
            continue
        marker = item.marker.strip()
        body = item.text.strip()
        original = item.orig.strip()
        tail = original[len(marker):]
        if marker and body and original.startswith(marker) and tail[:1].isspace() and tail.lstrip() == body:
            item.text = original
            if item.prov:
                item.prov[0].charspan = (0, len(original))


def split_sentences(text: str, protected_ends: frozenset[int] = frozenset()) -> list[tuple[int, int]]:
    """Sentence offsets; a boundary needs end punctuation followed by an uppercase letter or digit (any script)."""
    spans, start = [], 0
    for match in BOUNDARY.finditer(text):
        if match.end() in protected_ends:
            continue
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


def pack(text: str, max_chars: int, protected_ends: frozenset[int] = frozenset()) -> list[tuple[int, int]]:
    """Pack whole sentences up to max_chars; split an oversized sentence at whitespace."""
    pieces = []
    for start, end in split_sentences(text, protected_ends):
        while end - start > max_chars:
            limit = start + max_chars
            cut = next((i for i in range(limit, start, -1)
                        if text[i].isspace() and i + 1 not in protected_ends), limit)
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


def table_parts(item: TableItem, doc: DoclingDocument, caption: str, max_chars: int, mode: str,
                *, original: str | None = None) -> list[str]:
    """Table chunk texts. ``span_once_keyed`` renders merged cells once but keeps the row boundaries (hence the
    number of chunks and their ids) of the Docling rendering; if those cannot be reproduced the Docling text is used."""
    if original is None:
        original = item.export_to_markdown(doc=doc)
    markdown = table_markdown(item, doc, mode, original=original)
    if mode != "span_once_keyed":
        return split_table(markdown, caption, max_chars)
    reference = split_table(original, caption, max_chars)
    if markdown == original:
        return reference
    groups = [max(0, sum(line.strip().startswith("|") for line in part.splitlines()) - 2) for part in reference]
    try:
        return split_table(markdown, caption, max_chars, row_groups=groups)
    except ValueError:
        return reference


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
                   ocr_pages: set[int], source: Path | None = None) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """Return (chunks, tables, statistics). Chunk text is cleaned; offsets refer to the joined document text.

    ``source`` (the PDF) is only read when ``chunking.label_value`` is configured (see ``label_value``)."""
    max_chars = config["chunking"]["max_chars"]
    paragraph = config["chunking"]["strategy"] == "paragraph"
    preserve_list_markers = config["chunking"].get("preserve_list_markers", False)
    table_mode = config["chunking"].get("table_markdown", "docling")
    paginated = bool(doc.pages)
    filters = config["filters"]
    running_drops = 0
    unfiltered = doc  # only read for chunking.quarantine.list_dropped_items
    if paginated:
        doc, running_drops = filter_running_lines(doc, filters["margin_band"], filters["frequency"],
                                                  filters["running_block_max_gap_lines"],
                                                  filters["running_block_alignment_lines"],
                                                  filters["running_line_fragment_gap_lines"],
                                                  keep_pattern(filters.get("keep_line_patterns", [])),
                                                  filters.get("running_line_position_tolerance"),
                                                  filters.get("running_line_min_pages"),
                                                  filters.get("running_line_keep_varying_numbers", False))
    @cache
    def serializer():
        from docling_core.transforms.serializer.markdown import MarkdownDocSerializer

        return MarkdownDocSerializer(doc=doc)

    @cache
    def render_table(ref):
        return serializer().serialize(item=table_by_ref[ref]).text

    table_by_ref = {table.self_ref: table for table in doc.tables}
    exclusions = dropped_item_reasons(doc, filters.get("toc_leader_min_dots"),
                                      render_table=lambda item: render_table(item.self_ref))
    label_value = None
    if "label_value" in config["chunking"]:
        # The exclusions (running lines, dotted-leader TOC lines, ...) are decided on the text as converted; the corrected text must not
        # change them, and excluded items are neither corrected nor used as a value source.
        if paginated:
            doc, label_value = correct_document(doc, source, label_value_settings(config["chunking"]["label_value"]), ocr_pages,
                                                frozenset(exclusions))
            table_by_ref = {table.self_ref: table for table in doc.tables}
            serializer.cache_clear()
            render_table.cache_clear()
        else:
            label_value = {"method": "cell_geometry_v1", "skipped": "not_paginated"}
    quarantine = None
    if "quarantine" in config["chunking"]:
        # Optional (P2-WP1): detection and listing only, the text is never changed. Scans the document as it is chunked (after label_value).
        settings = quarantine_settings(config["chunking"]["quarantine"])
        quarantine = empty_quarantine(settings)
        if not paginated:
            quarantine["skipped"] = "not_paginated"
        else:
            if settings["list_dropped_items"]:
                quarantine["dropped_items"] = dropped_items(unfiltered, doc, exclusions, settings)
            if settings["scan_visibility"] or settings["scan_value_before_label"] or settings["list_page_status"]:
                reported = label_value or {}
                claimed = frozenset([change["ref"] for change in reported.get("changes", [])]
                                    + [ref for abstention in reported.get("abstentions", []) for ref in abstention["items"]])
                scan_document(doc, source, settings, ocr_pages, frozenset(exclusions), claimed, quarantine)
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
        protected_ends = set()
        if preserve_list_markers:
            position = 0
            for value, item, _ in buffer:
                marker = clean_text(item.marker) if isinstance(item, ListItem) else ""
                if marker and value.startswith(marker + " "):
                    protected_ends.add(position + len(marker) + 1)
                position += len(value) + 1
        for start, end in pack(text, max_chars, frozenset(protected_ends)):
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
            from docling_core.transforms.serializer.markdown import _count_header_rows
            # Rows are counted as the Markdown serializer renders them; cap at the grid in case it differs.
            next_row = min(_count_header_rows(item), item.data.num_rows)
            items = [(item, None), *[(ref.resolve(doc), None) for ref in item.captions]]
            for part in table_parts(item, doc, caption, max_chars, table_mode, original=render_table(item.self_ref)):
                rows = max(0, sum(line.strip().startswith("|") for line in part.splitlines()) - 2)
                end = min(next_row + rows, item.data.num_rows)
                emit("table", part, items, table_id=table_id, row_start=next_row, row_end=end)
                next_row = end
        elif isinstance(item, TextItem):
            if item.self_ref in caption_refs:
                continue
            if len({p.page_no for p in prov}) > 1:
                for p in prov:
                    add_text(item.text[p.charspan[0]:p.charspan[1]], item, p.page_no)
            else:
                add_text(item.text, item, page)
    flush()
    if quarantine is not None and settings["scan_tables"] and paginated:
        scan_tables(tables, doc, source, ocr_pages, settings, quarantine)  # optional (P2-WP3): table cells against the PDF geometry
    position = 0
    for chunk in chunks:
        chunk["char_start"], chunk["char_end"] = position, position + len(chunk["text"])
        chunk["sha256"] = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
        position += len(chunk["text"]) + 2
    statistics = {"text_chunks": sum(c["type"] == "text" for c in chunks),
                  "table_chunks": sum(c["type"] == "table" for c in chunks), "tables": len(tables),
                  "characters": sum(len(c["text"]) for c in chunks), "dropped": dict(sorted(dropped.items()))}
    if label_value is not None:
        statistics["label_value"] = label_value
    if quarantine is not None:
        statistics["quarantine"] = quarantine
    return chunks, tables, statistics
