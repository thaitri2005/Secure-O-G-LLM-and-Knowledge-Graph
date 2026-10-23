"""Build passage chunks with source provenance in document reading order."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from docling_core.types.doc import ContentLayer, DoclingDocument, TableItem, TextItem

from .filters import clean_text, dropped_item_reasons, filter_running_lines
from .sources import write_checksums, write_json, write_text
from .provenance import rounded_geometry
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
                         fragment_gap_lines: float, provenance: list[dict] | None = None,
                         strategy: str = "page", table_options: dict | None = None,
                         table_records: list[dict] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    doc, running_line_drops = filter_running_lines(doc, margin_band, frequency, block_max_gap_lines, block_alignment_lines, fragment_gap_lines)
    table_options = table_options or {}
    merged_tables = []
    if table_options.get("merge_pages"):
        from .tables import merge_adjacent_tables
        doc, merged_tables = merge_adjacent_tables(doc)
    chunks: list[dict] = []
    dropped = Counter(running_line=running_line_drops)
    section = None
    section_stack: list[tuple[int, str]] = []
    buffer: list[str] = []
    buffer_items: list[tuple[Any, int]] = []
    buffer_page = None
    buffer_section = None
    multi_page_tables = []
    empty_tables = []
    no_prov = []
    table_caption_refs = {ref.cref for table in doc.tables for ref in table.captions}
    exclusions = dropped_item_reasons(doc)
    from .tables import table_record
    catalog = {item.self_ref: table_record(doc, item, doc_id, index)
               for index, item in enumerate(doc.tables) if item.self_ref not in exclusions and item.prov and item.data.table_cells}
    if table_options.get("compact"):
        for record in catalog.values():
            record["rendered_header_rows"] = record["header_rows"]
    if table_records is not None:
        table_records.extend(catalog.values())

    def emit(page: int, kind: str, text: str, heading: str | None, items: list | None = None) -> None:
        if text.strip():
            chunks.append({"doc_id": doc_id, "page": page,
                           "chunk_id": f"{doc_id}#c{len(chunks):04d}",
                           "type": kind, "text": text, "section": heading})
            if provenance is not None:
                from .provenance import item_regions
                from .attribution import source_spans
                provenance.append({"regions": item_regions(doc, items or []),
                                   "source_spans": source_spans(doc, text, items or []),
                                   "section_path": [value for _, value in section_stack],
                                   "table_id": None, "row_start": None, "row_end": None})

    def flush() -> None:
        if buffer:
            text = "\n".join(buffer)
            for start, end in chunk_spans(text, max_chars):
                position, selected = 0, []
                for value, (item, page) in zip(buffer, buffer_items):
                    if position < end and start < position + len(value):
                        selected.append((item, page))
                    position += len(value) + 1
                emit(selected[0][1] if selected else buffer_page, "text", text[start:end], buffer_section, selected)
            buffer.clear()
            buffer_items.clear()

    def add_text(page: int, text: str, item: Any) -> None:
        nonlocal buffer_page, buffer_section
        cleaned = clean_text(text)
        continuation = (strategy == "paragraph" and buffer and page == buffer_items[-1][1] + 1
                        and buffer[-1][-1] not in ".!?:" and cleaned
                        and (cleaned[0].islower() or cleaned[0].isdigit()))
        if section != buffer_section or (page != buffer_page and not continuation):
            flush()
            buffer_page, buffer_section = page, section
        elif continuation:
            buffer_page = page
        if cleaned:
            buffer.append(cleaned)
            buffer_items.append((item, page))

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
            heading_level = getattr(item, "level", 1)
            section_stack[:] = [(depth, value) for depth, value in section_stack if depth < heading_level]
            if section:
                section_stack.append((heading_level, section))
        elif isinstance(item, TableItem):
            flush()
            if table_options.get("compact") and (item.data.num_rows * item.data.num_cols <= 1
                                                    or not any(cell.text.strip() for cell in item.data.table_cells)):
                text = clean_text(" ".join(cell.text for cell in item.data.table_cells))
                if text:
                    for start, end in chunk_spans(text, max_chars):
                        emit(page, "text", text[start:end], section, [(item, None)])
                    dropped["degenerate_table_to_text"] += 1
                else:
                    dropped["empty_table"] += 1
                    empty_tables.append(item.self_ref)
                continue
            if not item.data.table_cells:
                dropped["empty_table"] += 1
                empty_tables.append(item.self_ref)
                continue
            if len({prov.page_no for prov in item.prov}) > 1:
                multi_page_tables.append(item.self_ref)
            caption = clean_text(item.caption_text(doc))
            if table_options.get("compact"):
                from .tables import compact_markdown
                markdown = compact_markdown(item)
            else:
                markdown = item.export_to_markdown(doc=doc)
            from .tables import table_views
            header_rows = table_views(item)[3] if table_options.get("compact") else catalog[item.self_ref]["rendered_header_rows"]
            next_row = header_rows
            for part in split_table(markdown, caption, max_chars):
                emit(page, "table", part, section, [(item, None), *[(ref.resolve(doc), None) for ref in item.captions]])
                end_row = next_row + max(0, sum(line.strip().startswith("|") for line in part.splitlines()) - 2)
                if provenance is not None:
                    provenance[-1].update(table_id=catalog[item.self_ref]["table_id"], row_start=next_row, row_end=end_row)
                    # Row boundaries survive table merging; repeated headers keep
                    # the original header page rather than leaking into every page.
                    spans, position, body_row, grid_line = [], 0, next_row, 0
                    for line in part.splitlines(keepends=True):
                        source_page = page
                        if line.strip().startswith("|"):
                            if grid_line >= 2:
                                for prov in item.prov:
                                    if prov.charspan[0] <= body_row < prov.charspan[1] and len(item.prov) > 1:
                                        source_page = prov.page_no
                                        break
                                body_row += 1
                            grid_line += 1
                        spans.append({"source_ref": item.self_ref, "page": source_page,
                                      "start": position, "end": position + len(line),
                                      "source_start": 0, "source_end": 0})
                        position += len(line)
                    provenance[-1]["source_spans"] = spans
                next_row = end_row
        elif isinstance(item, TextItem):
            if item.self_ref in table_caption_refs:
                continue  # Already included as the first line of the table chunk.
            pages = {prov.page_no for prov in item.prov}
            if len(pages) > 1:
                for prov in item.prov:
                    start, end = prov.charspan
                    add_text(prov.page_no, raw_text[start:end], item)
            else:
                add_text(page, raw_text, item)
    flush()
    stats = {"doc_id": doc_id, "pages": len(doc.pages),
             "text_chunks": sum(c["type"] == "text" for c in chunks),
             "table_chunks": sum(c["type"] == "table" for c in chunks),
             "characters": sum(len(c["text"]) for c in chunks),
             "dropped": dict(sorted(dropped.items())), "multi_page_tables": multi_page_tables,
             "empty_tables": empty_tables, "no_provenance": no_prov}
    stats["merged_tables"] = merged_tables
    return chunks, stats


def chunk_documents(registry: list[dict[str, Any]], root: Path, options: dict[str, Any],
                    output: Path | None = None, cache: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Re-chunk cached documents and write the merged deliverable in registry order."""
    cache = cache or root / "data" / "interim" / "docling"
    if output is None:
        if options.get("chunking", {}).get("strategy") == "pypdf":
            raise ValueError("Alternative chunking requires a named run")
        destination = root / "data/processed"
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            result = chunk_documents(registry, root, options, output=staging / "gdr_chunks.json", cache=cache)
            write_checksums(staging, [source["doc_id"] for source in registry])
            artifacts = sorted(path for path in staging.rglob("*") if path.is_file())
            published_paths = {path.relative_to(destination) for path in (destination / "documents").rglob("*") if path.is_file()}
            published_paths.update(Path(name) for name in ("gdr_chunks.json", "gdr_chunks_full.jsonl", "gdr_tables.jsonl", "SHA256SUMS")
                                   if (destination / name).exists())
            if published_paths:
                if published_paths != {path.relative_to(staging) for path in artifacts}:
                    raise ValueError("Changed output requires a named run followed by publish")
                for path in artifacts:
                    published = destination / path.relative_to(staging)
                    if not published.is_file() or published.read_bytes() != path.read_bytes():
                        raise ValueError("Changed output requires a named run followed by publish")
            for path in artifacts:
                published = destination / path.relative_to(staging)
                published.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, published)
            return result
    if options.get("chunking", {}).get("strategy") == "pypdf":
        from .evaluation import naive_chunks
        merged = naive_chunks(registry, root, options["max_chars"])
        write_json(output, merged)
        from .provenance import write_document
        full = []
        for source in registry:
            chunks = [c for c in merged if c["doc_id"] == source["doc_id"]]
            import pypdfium2
            with pypdfium2.PdfDocument(root / "data/raw" / f"{source['doc_id']}.pdf") as pdf:
                sizes = {}
                for index in range(len(pdf)):
                    page = pdf[index]
                    sizes[index + 1] = page.get_size()
                    page.close()
            metadata = [{"regions": [{"page": c["page"], "bbox": [0, 0, *sizes[c["page"]]]}],
                         "section_path": [], "table_id": None, "row_start": None, "row_end": None} for c in chunks]
            full.extend(write_document(root, output.parent, source, chunks, metadata, options))
        write_text(output.with_name(output.stem + "_full.jsonl"), "".join(json.dumps(rounded_geometry(record), ensure_ascii=False) + "\n" for record in full))
        from .tables import tables_path
        write_text(tables_path(output), "")
        if output.is_relative_to(root / "data/processed"):
            write_checksums(output.parent, [source["doc_id"] for source in registry])
        return merged, []
    merged, statistics, full, table_records = [], [], [], []
    for source in registry:
        doc_id = source["doc_id"]
        document = DoclingDocument.model_validate_json((cache / f"{doc_id}.json").read_text(encoding="utf-8"))
        rotation_report = []
        if options["tables"]["rotation_retry"]:
            from .rotation import retry_rotated_tables
            document, rotation_report = retry_rotated_tables(document, root / "data/raw" / f"{doc_id}.pdf",
                                                              cache / "rotated" / doc_id, options)
        provenance = []
        chunks, stats = chunks_from_document(document, doc_id, options["max_chars"], options["margin_band"], options["frequency"],
                                            options["running_block_max_gap_lines"], options["running_block_alignment_lines"],
                                            options["running_line_fragment_gap_lines"], provenance=provenance,
                                            strategy=options["chunking"]["strategy"], table_options=options["tables"], table_records=table_records)
        if options["chunking"]["strategy"] == "hybrid":
            from .strategies import hybrid_chunks
            chunks, provenance = hybrid_chunks(document, doc_id, options)
            stats.update(text_chunks=sum(c["type"] == "text" for c in chunks),
                         table_chunks=sum(c["type"] == "table" for c in chunks),
                         characters=sum(len(c["text"]) for c in chunks))
        from .provenance import write_document
        full.extend(write_document(root, output.parent, source, chunks, provenance, options))
        if rotation_report:
            write_json(output.parent / f"{doc_id}_rotation.json", rotation_report)
        write_json(cache / f"{doc_id}.chunks.json", chunks)
        merged.extend(chunks)
        statistics.append(stats)
    destination = output
    write_json(destination, merged)
    write_text(output.with_name(output.stem + "_full.jsonl"), "".join(json.dumps(rounded_geometry(record), ensure_ascii=False) + "\n" for record in full))
    from .tables import tables_path
    write_text(tables_path(output), "".join(json.dumps(rounded_geometry(record), ensure_ascii=False) + "\n" for record in table_records))
    if destination.is_relative_to(root / "data/processed"):
        write_checksums(destination.parent, [source["doc_id"] for source in registry])
    return merged, statistics
