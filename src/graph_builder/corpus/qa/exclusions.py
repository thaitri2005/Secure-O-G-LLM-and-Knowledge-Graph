"""Per-page record of text the pipeline removed on purpose as a table of contents (A-412).

The work folder keeps the Docling document next to ``document.json``. ``document.json`` only counts removed items per
document; this module reads the Docling JSON (plain gzip + json, no docling import) and attributes the removed
table-of-contents text to pages, so that an empty K1 page can be reported as an explained exclusion instead of an
unexplained loss. It never reads the PDF and never decides whether the exclusion was right.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

DOCLING_NAME = "docling.json.gz"


def _chars(text: str) -> int:
    return len("".join((text or "").split()))


def _item_pages(item: dict) -> list[int]:
    return sorted({prov["page_no"] for prov in item.get("prov") or [] if "page_no" in prov})


def _table_text(item: dict) -> list[str]:
    return [cell.get("text") or "" for cell in (item.get("data") or {}).get("table_cells") or []]


def page_exclusions(docling: dict, rules: dict) -> dict[int, dict[str, int]]:
    """Return {page: {reason: non-space characters}} for table-of-contents items of a Docling JSON document.

    Reasons: document_index (index table or group children), dotted_leader_toc (text with dotted leaders),
    dotted_leader_toc_table (table whose cells have dotted leaders), document_index_heading (title on a TOC page).
    """
    leader = re.compile(rules["toc_leader_pattern"])
    title = re.compile(rules["toc_title_pattern"], re.IGNORECASE)
    items: dict[str, dict] = {}
    for key in ("texts", "tables", "pictures", "groups"):
        for item in docling.get(key) or []:
            items[item.get("self_ref")] = item
    result: dict[int, dict[str, int]] = {}
    seen: set[str] = set()

    def add(item: dict, reason: str, text_parts: list[str]) -> None:
        ref = item.get("self_ref")
        if ref in seen:
            return
        seen.add(ref)
        pages = _item_pages(item)
        if pages:
            bucket = result.setdefault(pages[0], {})
            bucket[reason] = bucket.get(reason, 0) + sum(_chars(part) for part in text_parts)

    def walk_children(group: dict) -> None:
        for child in group.get("children") or []:
            node = items.get(child.get("$ref"))
            if node is None:
                continue
            if "table_cells" in (node.get("data") or {}):
                add(node, "document_index", _table_text(node))
            elif "text" in node:
                add(node, "document_index", [node.get("text") or ""])
            walk_children(node)

    for table in docling.get("tables") or []:
        if table.get("label") == "document_index":
            add(table, "document_index", _table_text(table))
            walk_children(table)
    for group in docling.get("groups") or []:
        if group.get("label") == "document_index":
            walk_children(group)
    for text in docling.get("texts") or []:
        if leader.search(text.get("text") or ""):
            add(text, "dotted_leader_toc", [text.get("text") or ""])
    for table in docling.get("tables") or []:
        if table.get("label") != "document_index" and any(leader.search(cell) for cell in _table_text(table)):
            add(table, "dotted_leader_toc_table", _table_text(table))
    for text in docling.get("texts") or []:
        pages = _item_pages(text)
        if (text.get("label") in ("section_header", "title") and title.fullmatch(" ".join((text.get("text") or "").split()))
                and any(page in result for page in pages)):
            add(text, "document_index_heading", [text.get("text") or ""])
    return result


def load_page_exclusions(folder: Path | None, rules: dict) -> tuple[dict[int, dict[str, int]], str | None]:
    """Read ``docling.json.gz`` of a work folder. Returns (exclusions, error); any failure gives ({}, reason)."""
    if folder is None or not (folder / DOCLING_NAME).is_file():
        return {}, "docling.json.gz not found in the work folder"
    try:
        with gzip.open(folder / DOCLING_NAME, "rt", encoding="utf-8") as stream:
            return page_exclusions(json.load(stream), rules), None
    except Exception as error:  # noqa: BLE001 - QA must continue; no exclusion is claimed then
        return {}, f"{type(error).__name__}: {str(error)[:200]}"


def explain_page(excluded: dict[str, int] | None, pdf_text_chars: Any, rules: dict) -> dict | None:
    """Return the explanation record of a page, or None when the page has no recorded exclusion.

    ``explained`` is True when the excluded characters cover at least ``min_explained_fraction`` of the PDF text
    characters of the page; a partly covered page keeps its WARN."""
    if not excluded:
        return None
    total = sum(excluded.values())
    fraction = round(total / pdf_text_chars, 4) if isinstance(pdf_text_chars, (int, float)) and pdf_text_chars > 0 else None
    return {"explained": fraction is not None and fraction >= rules["min_explained_fraction"]["value"],
            "excluded_chars": total, "pdf_text_chars": pdf_text_chars, "fraction": fraction,
            "reasons": dict(sorted(excluded.items()))}
