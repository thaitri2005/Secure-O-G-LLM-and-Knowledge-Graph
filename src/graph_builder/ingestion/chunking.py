"""Build page-level text and Markdown table chunks in document reading order with stable identifiers."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from docling_core.types.doc import ContentLayer, DoclingDocument, TableItem, TextItem

from .filters import clean_text, dropped_item_reasons, filter_running_lines
from .sources import write_json
from .text_packing import chunk_spans

def split_table(markdown: str, caption: str, max_chars: int) -> list[str]:
    """Repeat the caption and Markdown header when splitting on row boundaries."""
    # In docling-core 2.103.1 export_to_markdown(doc=doc) includes captions.
    # Keep only the Markdown grid here; add the caption exactly once below.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in markdown.splitlines()
             if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    # Tabulate pads separator cells to the widest content cell. Those dashes
    # carry no source content and can exceed the entire chunk budget.
    separator_cells = lines[1].strip("|").split("|")
    if all(re.fullmatch(r"\s*:?-+:?\s*", cell) for cell in separator_cells):
        lines[1] = "| " + " | ".join(
            (":" if cell.strip().startswith(":") else "") + "---"
            + (":" if cell.strip().endswith(":") else "") for cell in separator_cells
        ) + " |"
    header = ([caption] if caption else []) + lines[:2]
    rows = lines[2:]
    parts, current = [], []
    for row in rows:
        candidate = "\n".join(header + current + [row])
        if current and len(candidate) > max_chars:
            parts.append("\n".join(header + current))
            current = []
        current.append(row)
    if current:
        parts.append("\n".join(header + current))
    return parts or ["\n".join(header)]


def chunks_from_document(doc: DoclingDocument, doc_id: str, max_chars: int, margin_band: float, frequency: float,
                         block_max_gap_lines: float, block_alignment_lines: float,
                         fragment_gap_lines: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    doc, running_line_drops = filter_running_lines(doc, margin_band, frequency, block_max_gap_lines, block_alignment_lines, fragment_gap_lines)
    chunks: list[dict] = []
    dropped = Counter(running_line=running_line_drops)
    section = None
    buffer: list[str] = []
    buffer_page = None
    buffer_section = None
    multi_page_tables = []
    empty_tables = []
    no_prov = []
    table_caption_refs = {ref.cref for table in doc.tables for ref in table.captions}
    exclusions = dropped_item_reasons(doc)

    def emit(page: int, kind: str, text: str, heading: str | None) -> None:
        if text.strip():
            chunks.append({"doc_id": doc_id, "page": page,
                           "chunk_id": f"{doc_id}#c{len(chunks):04d}",
                           "type": kind, "text": text, "section": heading})

    def flush() -> None:
        if buffer:
            text = "\n".join(buffer)
            for start, end in chunk_spans(text, max_chars):
                emit(buffer_page, "text", text[start:end], buffer_section)
            buffer.clear()

    def add_text(page: int, text: str) -> None:
        nonlocal buffer_page, buffer_section
        if page != buffer_page or section != buffer_section:
            flush()
            buffer_page, buffer_section = page, section
        cleaned = clean_text(text)
        if cleaned:
            buffer.append(cleaned)

    # Keep existing TextItems inside figures as well as their captions. The
    # bitmap itself is excluded; no OCR is used to obtain this text.
    for item, _ in doc.iterate_items(included_content_layers=set(ContentLayer), traverse_pictures=True):
        label = getattr(getattr(item, "label", None), "value", "unknown")
        if item.self_ref in exclusions:
            dropped[exclusions[item.self_ref]] += 1
            continue
        raw_text = getattr(item, "text", "")
        if isinstance(item, TextItem) and not raw_text.strip():
            continue
        if not getattr(item, "prov", None):
            dropped["no_provenance"] += 1
            no_prov.append(item.self_ref)
            continue
        page = item.prov[0].page_no
        if label in {"section_header", "title"}:
            flush()
            section = clean_text(raw_text) or None
        elif isinstance(item, TableItem):
            flush()
            if not item.data.table_cells:
                dropped["empty_table"] += 1
                empty_tables.append(item.self_ref)
                continue
            if len({prov.page_no for prov in item.prov}) > 1:
                multi_page_tables.append(item.self_ref)
            caption = clean_text(item.caption_text(doc))
            markdown = item.export_to_markdown(doc=doc)
            for part in split_table(markdown, caption, max_chars):
                emit(page, "table", part, section)
        elif isinstance(item, TextItem):
            if item.self_ref in table_caption_refs:
                continue  # Already included as the first line of the table chunk.
            pages = {prov.page_no for prov in item.prov}
            if len(pages) > 1:
                for prov in item.prov:
                    start, end = prov.charspan
                    add_text(prov.page_no, raw_text[start:end])
            else:
                add_text(page, raw_text)
    flush()
    stats = {"doc_id": doc_id, "pages": len(doc.pages),
             "text_chunks": sum(c["type"] == "text" for c in chunks),
             "table_chunks": sum(c["type"] == "table" for c in chunks),
             "characters": sum(len(c["text"]) for c in chunks),
             "dropped": dict(sorted(dropped.items())), "multi_page_tables": multi_page_tables,
             "empty_tables": empty_tables, "no_provenance": no_prov}
    return chunks, stats


def chunk_documents(registry: list[dict[str, Any]], root: Path, options: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Re-chunk cached documents and write the merged deliverable in registry order."""
    cache = root / "data" / "interim" / "docling"
    merged, statistics = [], []
    for source in registry:
        doc_id = source["doc_id"]
        document = DoclingDocument.model_validate_json((cache / f"{doc_id}.json").read_text(encoding="utf-8"))
        chunks, stats = chunks_from_document(document, doc_id, options["max_chars"], options["margin_band"], options["frequency"],
                                            options["running_block_max_gap_lines"], options["running_block_alignment_lines"],
                                            options["running_line_fragment_gap_lines"])
        write_json(cache / f"{doc_id}.chunks.json", chunks)
        merged.extend(chunks)
        statistics.append(stats)
    write_json(root / "data" / "processed" / "gdr_chunks.json", merged)
    return merged, statistics
