"""Identify structural exclusions and remove repeated margin lines from a copy of a document."""
from __future__ import annotations

from collections import Counter
import re
from typing import Any

from docling_core.types.doc import ContentLayer, DoclingDocument, PictureItem, TableItem, TextItem

TOC_LEADER = re.compile(r"\.{3,}\s*\d*\s*(?:$|\n)")
TOC_TITLE = re.compile(r"(?:table\s+of\s+contents|contents)\s*[:.]?", re.IGNORECASE)
NUMBERED_FURNITURE = re.compile(
    r"(?:\d+|(?:page|pg\.?|p\.)\s*\d+(?:\s*(?:of|/)\s*\d+)?|"
    r"(?:printed|generated)(?:\s+(?:at|on))?\s*:\s*.+)", re.IGNORECASE,
)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\r\n", "\n")).strip()


def varying_number_keys(occurrences: list[dict[str, Any]]) -> set[str]:
    """Find masked keys that recur with different printed values outside explicit furniture."""
    first: dict[str, str] = {}
    varying: set[str] = set()
    for occurrence in occurrences:
        key, literal = occurrence["key"], occurrence["text"].casefold()
        if not re.search(r"\d", literal) or NUMBERED_FURNITURE.fullmatch(literal):
            continue
        if first.setdefault(key, literal) != literal:
            varying.add(key)
    return varying


def positional_repeats(occurrences: list[dict[str, Any]], pages: Any, tolerance: float,
                       minimum_pages: float) -> set[tuple[int, int]]:
    """``(occurrence index, page)`` pairs whose key also occurs at about the same vertical position on enough pages.

    The vertical position is the centre of the line box as a fraction of the page height, so the test does not depend
    on the page size. Two occurrences are at the same position when their centres differ by at most ``tolerance``.
    Distinct pages are counted, so several equal cells in one row count once.
    """
    by_key: dict[str, list[tuple[float, int, int]]] = {}
    for index, occurrence in enumerate(occurrences):
        if not occurrence["key"]:
            continue
        for page_no, boxes in occurrence["boxes"].items():
            centre = (min(b.t for b in boxes) + max(b.b for b in boxes)) / 2 / pages[page_no].size.height
            by_key.setdefault(occurrence["key"], []).append((centre, page_no, index))
    repeated: set[tuple[int, int]] = set()
    for entries in by_key.values():
        entries.sort()
        window: Counter[int] = Counter()
        low = high = 0
        for centre, page_no, index in entries:
            while high < len(entries) and entries[high][0] <= centre + tolerance:
                window[entries[high][1]] += 1
                high += 1
            while entries[low][0] < centre - tolerance:
                window[entries[low][1]] -= 1
                if not window[entries[low][1]]:
                    del window[entries[low][1]]
                low += 1
            if len(window) >= minimum_pages:
                repeated.add((index, page_no))
    return repeated


def filter_running_lines(doc: DoclingDocument, margin_band: float, frequency: float,
                         block_max_gap_lines: float, block_alignment_lines: float,
                         fragment_gap_lines: float, keep: re.Pattern[str] | None = None,
                         position_tolerance: float | None = None,
                         min_pages: int | None = None,
                         keep_varying_numbers: bool = False) -> tuple[DoclingDocument, int]:
    """Remove repeated margin lines and adjacent repeated lines in an anchored block.

    Frequency keys normalize whitespace, case, and digit runs. Block members
    must align at the left edge and be separated by at most the configured
    number of line heights. A block needs an entire line inside a margin band.
    The full document exports remain intact because filtering uses a copy.

    A line, or a restored logical line made of horizontal fragments, whose
    cleaned text matches ``keep`` is data that happens to repeat; it and its
    fragments are never removed on that page.

    Digit runs are normalized, so every bare number (a table cell ``150``) shares the key of a page counter
    (``42``) and counts as frequent. With ``position_tolerance`` (a fraction of the page height) a table-cell line is
    removed only when its key also repeats at the same vertical position on enough distinct pages. Text items keep
    the legacy decisions: rescuing converter text can introduce chart artefacts absent from the PDF. Apply the cell
    guard after block selection so a rescued cell cannot also rescue a neighbouring text item. Only all-cell logical
    lines can provide positional evidence for their fragments. ``None`` keeps the old behavior.
    Chart-label text (DR-10) is not restored by this option. Real table data repeated at the same position can still
    be removed; position alone cannot distinguish it from running furniture.

    The share rule ``frequency`` is trivially true for a document of one or two pages (one page is 100 % of the pages),
    so every line in the margin band of a short document counts as repeated, including titles and identifiers.
    With ``min_pages`` a key must also occur on at least that many distinct pages to count as repeated; a document with
    fewer pages than ``min_pages`` has no repetition evidence and nothing is removed. ``None`` keeps the old behavior.

    ``keep_varying_numbers`` protects lines whose printed digits actually change under the same masked key, including
    geometric line fragments. Number-only counters, explicit page counters and print/generation stamps are excluded.
    """
    needed_pages = len(doc.pages) * frequency if min_pages is None else max(len(doc.pages) * frequency, min_pages)
    doc = doc.model_copy(deep=True)
    records = []

    for item, _ in doc.iterate_items(included_content_layers=set(ContentLayer), traverse_pictures=True):
        if isinstance(item, TextItem):
            spans = [(prov.page_no, prov.bbox, *prov.charspan) for prov in item.prov]
            if len(spans) == 1:
                # Single-page item geometry applies to all of its text lines.
                spans = [(spans[0][0], spans[0][1], 0, len(item.text))]
            records.append((item, spans))
        elif isinstance(item, TableItem) and len(item.prov) == 1:
            page_no = item.prov[0].page_no
            for cell in item.data.table_cells:
                if isinstance(getattr(cell, "text", None), str):
                    records.append((cell, [(page_no, cell.bbox, 0, len(cell.text))]))
    pages_by_line: dict[str, set[int]] = {}
    occurrences: list[dict[str, Any]] = []
    for record_index, (source, spans) in enumerate(records):
        offset = 0
        for line in source.text.splitlines(keepends=True):
            end = offset + len(line)
            key = re.sub(r"\d+", "#", clean_text(line).casefold())
            boxes: dict[int, list[Any]] = {}
            located_pages = set()
            for page_no, bbox, start, stop in spans:
                if start < end and offset < stop:
                    located_pages.add(page_no)
                    page = doc.pages.get(page_no)
                    if bbox is not None and page is not None and page.size.height > 0:
                        box = bbox.to_top_left_origin(page_height=page.size.height)
                        if 0 <= box.t <= box.b <= page.size.height:
                            boxes.setdefault(page_no, []).append(box)
            if key:
                pages_by_line.setdefault(key, set()).update(located_pages)
            occurrences.append({"record": record_index, "start": offset, "end": end, "key": key, "members": [],
                                "pages": located_pages, "boxes": boxes, "text": clean_text(line)})
            offset = end
    # Restore a logical line when layout extraction puts its horizontal
    # fragments in separate cells. Keep the original cells for serialization.
    by_page: dict[int, list[tuple[int, Any]]] = {}
    for index, occurrence in enumerate(occurrences):
        if len(occurrence["pages"]) != 1 or not occurrence["key"]:
            continue
        for page_no, boxes in occurrence["boxes"].items():
            box = boxes[0].model_copy(update={"l": min(b.l for b in boxes), "r": max(b.r for b in boxes),
                                              "t": min(b.t for b in boxes), "b": max(b.b for b in boxes)})
            by_page.setdefault(page_no, []).append((index, box))
    for page_no, segments in by_page.items():
        for index, box in segments:
            members, right = [index], box.r
            for other, next_box in sorted(segments, key=lambda pair: pair[1].l):
                line_height = min(box.b - box.t, next_box.b - next_box.t)
                if (other != index and line_height > 0 and next_box.l >= right
                        and next_box.l - right <= line_height * fragment_gap_lines
                        and max(abs(box.t - next_box.t), abs(box.b - next_box.b)) <= line_height * block_alignment_lines):
                    members.append(other)
                    right = next_box.r
            if len(members) > 1:
                key = " ".join(occurrences[member]["key"] for member in members)
                pages_by_line.setdefault(key, set()).add(page_no)
                occurrences.append({"record": None, "key": key, "pages": {page_no}, "members": members,
                                    "boxes": {page_no: [box.model_copy(update={"r": right})]},
                                    "text": " ".join(occurrences[member]["text"] for member in members)})
    positional = (positional_repeats(occurrences, doc.pages, position_tolerance, needed_pages)
                  if position_tolerance is not None else None)
    protected: set[tuple[int, int]] = set()
    varying = varying_number_keys(occurrences) if keep_varying_numbers else set()
    if keep is not None or varying:
        for index, occurrence in enumerate(occurrences):
            if occurrence["key"] in varying or (keep is not None and keep.search(occurrence["text"])):
                for page_no in occurrence["pages"]:
                    protected.update((member, page_no) for member in (index, *occurrence["members"]))
    frequent = {key for key, pages in pages_by_line.items() if len(pages) >= needed_pages}
    candidates: dict[int, list[tuple[int, float, float, float]]] = {}
    selected: set[tuple[int, int]] = set()
    for index, occurrence in enumerate(occurrences):
        if occurrence["key"] not in frequent:
            continue
        for page_no, boxes in occurrence["boxes"].items():
            if (index, page_no) in protected:
                continue
            top, bottom, left = min(b.t for b in boxes), max(b.b for b in boxes), min(b.l for b in boxes)
            candidates.setdefault(page_no, []).append((index, top, bottom, left))
            height = doc.pages[page_no].size.height
            if bottom <= height * margin_band or top >= height * (1 - margin_band):
                selected.add((index, page_no))
    for page_no, lines in candidates.items():
        pending = [line for line in lines if (line[0], page_no) in selected]
        while pending:
            _, top, bottom, left = pending.pop()
            for candidate in lines:
                index, next_top, next_bottom, next_left = candidate
                if (index, page_no) in selected:
                    continue
                height, next_height = bottom - top, next_bottom - next_top
                if min(height, next_height) <= 0:
                    continue
                gap = max(0, next_top - bottom, top - next_bottom)
                if (gap <= max(height, next_height) * block_max_gap_lines
                        and abs(left - next_left) <= min(height, next_height) * block_alignment_lines):
                    selected.add((index, page_no))
                    pending.append(candidate)
    for index, occurrence in enumerate(occurrences):
        for page_no in occurrence["pages"]:
            if (index, page_no) in selected:
                selected.update((member, page_no) for member in occurrence["members"])
    selected -= protected
    if positional is not None:
        table_occurrences = {index for index, occurrence in enumerate(occurrences)
                             if occurrence["record"] is not None
                             and not isinstance(records[occurrence["record"]][0], TextItem)}
        table_evidence = {(index, page_no) for index, page_no in positional if index in table_occurrences}
        for index, occurrence in enumerate(occurrences):
            if occurrence["members"] and all(member in table_occurrences for member in occurrence["members"]):
                for page_no in occurrence["pages"]:
                    if (index, page_no) in positional and (index, page_no) in selected:
                        table_evidence.update((member, page_no) for member in occurrence["members"])
        selected = {(index, page_no) for index, page_no in selected
                    if index not in table_occurrences or (index, page_no) in table_evidence}
    removed_by_record: dict[int, list[tuple[int, int]]] = {}
    for index, occurrence in enumerate(occurrences):
        if occurrence["record"] is not None and occurrence["pages"] and all((index, page_no) in selected for page_no in occurrence["pages"]):
            removed_by_record.setdefault(occurrence["record"], []).append((occurrence["start"], occurrence["end"]))
    drops = 0
    for record_index, (source, spans) in enumerate(records):
        removed = removed_by_record.get(record_index, [])
        if removed:
            drops += len(removed)
            kept, offset = [], 0
            for start, end in removed:
                kept.append(source.text[offset:start])
                offset = end
            kept.append(source.text[offset:])
            source.text = "".join(kept)
            if isinstance(source, TextItem):
                # Preserve page-specific offsets when earlier lines disappear.
                def remap(position: int) -> int:
                    return position - sum(max(0, min(position, end) - start) for start, end in removed)
                for prov in source.prov:
                    prov.charspan = tuple(remap(position) for position in prov.charspan)
    return doc, drops


LEADER_RUN = re.compile(r"\.+")


def has_toc_leader(text: str, min_dots: int | None = None) -> bool:
    """True if ``text`` has a dotted leader (``TOC_LEADER``) at a line end.

    With ``min_dots`` a leader of fewer dots counts only when a page number follows it. A trailing ellipsis (``...``, text
    cut off with no number after it) is then not a leader, so the sentence in front of it is data and not a TOC line.
    Text with no letter or digit at all (a bare ``...``) carries no data and keeps counting as a leader fragment.
    ``None`` keeps the old behavior: any run of three or more dots counts.
    """
    if min_dots is None:
        return bool(TOC_LEADER.search(text))
    bare = not any(character.isalnum() for character in text)
    for match in TOC_LEADER.finditer(text):
        found = match.group(0)
        if bare or len(LEADER_RUN.match(found).group(0)) >= min_dots or any(character.isdigit() for character in found):
            return True
    return False


def dropped_item_reasons(doc: DoclingDocument, toc_leader_min_dots: int | None = None, *, render_table=None) -> dict[str, str]:
    """Identify structural exclusions, including the explicit title of a detected TOC.

    Shared with the validator so exemptions describe actual extraction rules.
    Ordinary headings, captions and empty tables are never coverage exclusions.
    ``toc_leader_min_dots`` (C-03c) is passed to ``has_toc_leader``; ``None`` keeps the old behavior.
    """
    items = list(doc.iterate_items(included_content_layers=set(ContentLayer), traverse_pictures=True))
    reasons: dict[str, str] = {}
    toc_pages: set[int] = set()
    toc_level = None
    for item, level in items:
        label = getattr(getattr(item, "label", None), "value", "unknown")
        if toc_level is not None and level <= toc_level:
            toc_level = None
        reason = None
        if toc_level is not None:
            reason = "document_index_child"
        elif label in {"page_header", "page_footer", "document_index"}:
            reason = label
            if label == "document_index":
                toc_level = level
        elif isinstance(item, PictureItem):
            reason = "picture"
        elif has_toc_leader(getattr(item, "text", ""), toc_leader_min_dots):
            reason = "dotted_leader_toc"
        elif isinstance(item, TableItem):
            markdown = render_table(item) if render_table is not None else item.export_to_markdown(doc=doc)
            if has_toc_leader(markdown, toc_leader_min_dots):
                reason = "dotted_leader_toc_table"
        if reason is not None:
            reasons[item.self_ref] = reason
            if reason.startswith("document_index") or reason.startswith("dotted_leader_toc"):
                toc_pages.update(prov.page_no for prov in getattr(item, "prov", []))
    for item, _ in items:
        label = getattr(getattr(item, "label", None), "value", "unknown")
        if (label in {"section_header", "title"}
                and TOC_TITLE.fullmatch(clean_text(getattr(item, "text", "")))
                and any(prov.page_no in toc_pages for prov in getattr(item, "prov", []))):
            reasons[item.self_ref] = "document_index_heading"
    return reasons


