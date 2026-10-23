"""Validate chunk records against source page coverage, schema, identifiers, size limits, and configured content checks."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import re

from docling_core.types.doc import DoclingDocument
from pypdf import PdfReader

from .filters import clean_text, dropped_item_reasons, filter_running_lines
from typing import Any

from .sources import DOC_ID

REQUIRED = {"doc_id", "page", "chunk_id", "type", "text", "section"}
ALLOWED = REQUIRED


@dataclass
class Source:
    document: DoclingDocument
    page_chars: list[int]


def load_sources(config: list[dict[str, Any]], root: Path, cache: Path | None = None) -> dict[str, Source]:
    sources = {}
    cache = cache or root / "data" / "interim" / "docling"
    for entry in config:
        doc_id = entry["doc_id"]
        document = DoclingDocument.model_validate_json(
            (cache / f"{doc_id}.json").read_text(encoding="utf-8")
        )
        reader = PdfReader(root / "data" / "raw" / f"{doc_id}.pdf")
        sources[doc_id] = Source(document, [len((page.extract_text() or "").strip()) for page in reader.pages])
    return sources


def exempt_pages(document: DoclingDocument, options: dict[str, Any]) -> list[int]:
    """Derive exclusions from source items, with running metadata allowed on index pages.

    Inspect all layers and figure contents, including captions and headings.
    Empty tables and ordinary headings prevent exemptions. Explicit index
    headings and geometrically matching header templates are index metadata.
    """
    exclusions = dropped_item_reasons(document)
    filtered, _ = filter_running_lines(document, options["margin_band"], options["frequency"],
                                       options["running_block_max_gap_lines"], options["running_block_alignment_lines"],
                                       options["running_line_fragment_gap_lines"])
    index_pages = {prov.page_no for item in [*document.texts, *document.tables]
                   if exclusions.get(item.self_ref, "").startswith(("document_index", "dotted_leader_toc"))
                   for prov in item.prov}
    header_templates = [item for item in document.texts if item.label.value == "page_header"]

    def index_metadata(item: Any) -> bool:
        if getattr(getattr(item, "label", None), "value", "") not in {"title", "section_header"}:
            return False
        text = clean_text(item.text).casefold()
        if re.fullmatch(r"(?:(?:table|list)\s+of\s+)?(?:contents|figures|tables)\s*[:.]?", text):
            return True
        for header in header_templates:
            if not text or text not in clean_text(header.text).casefold():
                continue
            for prov in item.prov:
                box = prov.bbox.to_top_left_origin(page_height=document.pages[prov.page_no].size.height)
                height = document.pages[prov.page_no].size.height
                for reference in header.prov:
                    reference_height = document.pages[reference.page_no].size.height
                    template = reference.bbox.to_top_left_origin(page_height=reference_height)
                    if template.t / reference_height <= box.t / height and box.b / height <= template.b / reference_height:
                        return True
        return False
    seen: set[int] = set()
    retained: set[int] = set()
    # Include orphaned items too: a retained source item must never disappear
    # from the coverage decision merely because it is outside the body tree.
    items = [*document.texts, *document.tables, *document.pictures,
             *document.key_value_items, *document.form_items]
    for item in items:
        removed_running_text = (bool(getattr(item, "text", "").strip())
                                and not getattr(item.get_ref().resolve(filtered), "text", "").strip())
        for prov in getattr(item, "prov", []):
            seen.add(prov.page_no)
            if (item.self_ref not in exclusions
                    and not (prov.page_no in index_pages and (removed_running_text or index_metadata(item)))):
                retained.add(prov.page_no)
    return sorted(seen - retained)


def single_oversized_row(text: str, max_chars: int) -> bool:
    """Allow exactly one body row, including its full repeated header."""
    grid = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(grid) == 1:
        return bool(re.fullmatch(r"\|.*\|", grid[0]))
    # A lone rendered row above a separator is a headerless one-row table.
    return (len(grid) in {2, 3} and len(grid[1]) <= max_chars
            and bool(re.fullmatch(r"\|[\s:|\-]+\|", grid[1]))
            and all(row.endswith("|") for row in grid))


def validate_records(chunks: Any, doc_ids: list[str], sources: dict[str, Source], options: dict[str, Any],
                     provenance: list[dict] | None = None) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    warnings: list[str] = []
    summary: list[dict] = []
    max_chars, spot_checks = options["max_chars"], options["spot_checks"]
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if not isinstance(chunks, list):
        return ["Top-level JSON must be an array"], warnings, summary
    if not chunks:
        errors.append("Chunk array is empty")
    by_doc = defaultdict(list)
    seen_ids: set[str] = set()
    next_index = Counter()
    previous_doc_rank = -1
    ranks = {doc_id: rank for rank, doc_id in enumerate(doc_ids)}
    for index, chunk in enumerate(chunks):
        prefix = f"chunk[{index}]"
        if not isinstance(chunk, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        if missing := REQUIRED - chunk.keys():
            errors.append(f"{prefix}: missing fields {sorted(missing)}")
        if extra := chunk.keys() - ALLOWED:
            errors.append(f"{prefix}: extra fields {sorted(extra)}")
        doc_id = chunk.get("doc_id")
        if not isinstance(doc_id, str) or not DOC_ID.fullmatch(doc_id):
            errors.append(f"{prefix}: invalid doc_id")
            continue
        if doc_id not in ranks:
            errors.append(f"{prefix}: unconfigured doc_id {doc_id}")
            continue
        by_doc[doc_id].append(chunk)
        rank = ranks[doc_id]
        if rank < previous_doc_rank:
            errors.append(f"{prefix}: documents are not in config order")
        previous_doc_rank = rank
        chunk_id = chunk.get("chunk_id")
        expected_id = f"{doc_id}#c{next_index[doc_id]:04d}"
        next_index[doc_id] += 1
        if not isinstance(chunk_id, str) or not re.fullmatch(re.escape(doc_id) + r"#c\d{4}", chunk_id):
            errors.append(f"{prefix}: invalid chunk_id")
        else:
            if chunk_id in seen_ids:
                errors.append(f"{prefix}: duplicate chunk_id {chunk_id}")
            seen_ids.add(chunk_id)
        if chunk_id != expected_id:
            errors.append(f"{prefix}: expected contiguous ID {expected_id}, got {chunk_id!r}")
        page = chunk.get("page")
        if type(page) is not int or not 1 <= page <= len(sources[doc_id].page_chars):
            errors.append(f"{prefix}: page must be an integer in the physical PDF page range")
        kind = chunk.get("type")
        if not isinstance(kind, str) or kind not in {"text", "table"}:
            errors.append(f"{prefix}: type must be text or table")
        if "section" in chunk and chunk["section"] is not None and not isinstance(chunk["section"], str):
            errors.append(f"{prefix}: section must be a string or null")
        text = chunk.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{prefix}: text must be a nonempty string")
        elif len(text) > max_chars:
            if kind == "table" and single_oversized_row(text, max_chars):
                warnings.append(f"{chunk_id}: {len(text)} characters; indivisible single body row with full header exceeds {max_chars}")
            else:
                errors.append(f"{prefix} ({chunk_id}): {len(text)} characters exceeds {max_chars}")
    for doc_id in doc_ids:
        rows = by_doc[doc_id]
        source = sources[doc_id]
        exempt = exempt_pages(source.document, options)
        covered = {c["page"] for c in rows if type(c.get("page")) is int}
        covered.update(region["page"] for c in provenance or [] if c["doc_id"] == doc_id for region in c["regions"])
        missing_pages = [page for page, chars in enumerate(source.page_chars, 1)
                         if chars > 200 and page not in covered and page not in exempt]
        if not rows:
            errors.append(f"{doc_id}: no chunks")
        if missing_pages:
            errors.append(f"{doc_id}: missing coverage pages {missing_pages}")
        counts = Counter(c.get("type") for c in rows if isinstance(c.get("type"), str))
        if counts["table"] == 0:
            warnings.append(f"{doc_id}: no table chunks")
        summary.append({"doc_id": doc_id, "pages": len(source.page_chars),
                        "text": counts["text"], "table": counts["table"], "total": len(rows),
                        "exempt_pages": exempt, "missing_pages": missing_pages})
    for check in spot_checks:
        if check["doc_id"] in doc_ids and not any(
            c.get("type") == "text" and c.get("page") == check["page"] and c.get("section") == check["section"]
            and isinstance(c.get("text"), str) and all(term in c["text"] for term in check["contains"])
            for c in by_doc[check["doc_id"]]
        ):
            errors.append(f"{check['doc_id']}: content spot check failed")
    return errors, warnings, summary
