"""Read ruled daily-report logs and join independently verified page parts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from pathlib import Path
import re
import unicodedata

from .activity_detail import PageGrid, assemble, compatible, continuation_row, native_matches, replace_chunks
from .casing_tables import RULE_TOLERANCE, assign_cell_words, read_cells, vertical_rules
from .ops_tables import chunk_template
from .report_context import pdf_page_texts
from .ruled_panels import band_words, horizontal_bands, key
from .table_recognition import page_lines
from .text_layer import source_page, union

RULE = "daily_log"
DESCRIPTION = 3
HEADERS = (
    {"report date", "date"},
    {"report", "report no", "report number"},
    {"midnight depth m", "midnight depth ft"},
    {"24 hour summary", "daily drilling summary", "daily operations summary"},
)
HEADER_HINTS = (
    re.compile(r"\bmidnight\s+depth\b", re.I),
    re.compile(r"\b(?:24[-\s]+hour|daily\s+(?:drilling|operations))\s+summary\b", re.I),
)
DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%Y-%m-%d")
NUMBER = re.compile(r"[0-9]+")
DEPTH = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
PAGE_COUNTER = re.compile(r"\bpage (\d+) of (\d+)\b", re.I)
REPORT_TITLE = re.compile(r"\b(?:well completion|end of well|drilling) report\b")


@dataclass
class LogPage(PageGrid):
    height: float


def date_of(text):
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def ordered_records(rows):
    records = [(date_of(date), int(report)) for date, report, _, _ in rows if NUMBER.fullmatch(report)]
    return (bool(rows) and len(records) == len(rows) and all(date and report >= 1 for date, report in records)
            and all(next_number == number + 1 and next_date > date
                    for (date, number), (next_date, next_number) in pairwise(records)))


def matched_text(col, from_words, from_table):
    def compact(value):
        return "".join(unicodedata.normalize("NFC", value).split())

    words, cell = compact(from_words), compact(from_table)
    if words == cell:
        return True
    # PDFium can expose an unmapped hyphen in a prose cell. Every other character, including digits, must match.
    return (col == DESCRIPTION and len(words) == len(cell)
            and all(a == b or (a == "\ufffe" and b in "-‑–") for a, b in zip(words, cell)))


def page_identity(layer, lines, table_top):
    title, footers = [], []
    for line in lines:
        text = key(" ".join(word["text"] for word in line["words"]))
        if line["bottom"] < min(table_top, .08 * layer["height"]) and text:
            title.append(text)
        if line["top"] > .85 * layer["height"] and (counter := PAGE_COUNTER.search(text)):
            footers.append((counter.groups(), text[:counter.start()].strip()))
    heading = " ".join(title)
    if not REPORT_TITLE.search(heading) or not REPORT_TITLE.sub("", heading).strip() or len(footers) != 1:
        return (0, 0), {}
    (number, total), edition = footers[0]
    number, total = int(number), int(total)
    if not 1 <= number <= total:
        return (0, 0), {}
    return (number, total), {"heading": [heading], "edition": [edition]}


def header_size(rows):
    for stop in range(1, min(4, len(rows) - 1) + 1):
        header = [" ".join(col for col in parts if col) for parts in zip(*rows[:stop])]
        if all(key(value) in allowed for value, allowed in zip(header, HEADERS, strict=True)):
            return stop, header
    return None


def read_table(candidate, layer, lines, page):
    values = [[" ".join((cell or "").split()) for cell in row] for row in candidate.extract()]
    header = header_size(values)
    if header is None:
        return None
    start, names = header
    body = values[start:]
    suffix = int(continuation_row(body[0], DESCRIPTION))
    if (not ordered_records(body[suffix:])
            or any(not DEPTH.fullmatch(row[2]) or not row[DESCRIPTION] for row in body[suffix:])
            or any(any(cell is None for cell in row.cells) for row in candidate.rows[start:])):
        return None

    left, top, right, bottom = candidate.bbox
    recorded = [top, *(row.bbox[1] for row in candidate.rows[start:]), bottom]
    levels = [y for y in horizontal_bands(layer, left, right, top) if y <= bottom + RULE_TOLERANCE]
    if len(levels) != len(recorded) or any(abs(a - b) > RULE_TOLERANCE for a, b in zip(levels, recorded)):
        return None
    edges, boxes = [], []
    for (upper, lower), row in zip(pairwise(levels), [names, *body], strict=True):
        slots = vertical_rules(layer, upper, lower, left, right)
        if len(slots) != 5 or (edges and any(abs(a - b) > RULE_TOLERANCE for a, b in zip(edges, slots))):
            return None
        cells = assign_cell_words(band_words(lines, left, right, upper, lower), slots)
        if cells is None or not all(matched_text(col, word_text, table_text)
                                    for col, (word_text, table_text) in enumerate(zip(read_cells(cells), row))):
            return None
        edges = slots
        boxes.append([union(cell) for cell in cells])
    sequence, identity = page_identity(layer, lines, top)
    return LogPage(page, sequence, names, body, boxes, edges, list(candidate.bbox), identity, layer["height"])


def read_page(path, source, number):
    if source.rotation:
        return None
    layer = source_page(path, number, displayed_origin=True)
    lines = page_lines(layer)
    found = [panel for table in source.find_tables().tables if table.col_count == 4
             and (panel := read_table(table, layer, lines, number)) is not None]
    return found[0] if len(found) == 1 else None


def joins(previous, current, contexts):
    return (current.page == previous.page + 1
            and previous.sequence[0] > 0 and current.sequence == (previous.sequence[0] + 1, previous.sequence[1])
            and previous.identity == current.identity
            and contexts.get(previous.page, {}) == contexts.get(current.page, {})
            and previous.bbox[3] >= .80 * previous.height and current.bbox[1] <= .20 * current.height
            and compatible(previous, current)
            and ordered_records([previous.rows[-1], current.rows[int(continuation_row(current.rows[0], DESCRIPTION))]]))


def repair_document(pdf: Path, pages, chunks, tables, doc_id, max_chars, contexts, *, stacked_pages=(), source_texts=None):
    if not chunks:
        return chunks, tables, []
    numbers = [page["page"] for page in pages if page["mode"] == "text" and page["page"] not in stacked_pages]
    findings, groups = [], []
    try:
        hits = [number for number, text in pdf_page_texts(pdf, numbers, source_texts=source_texts).items()
                if all(hint.search(text) for hint in HEADER_HINTS)]
        if not hits:
            return chunks, tables, findings
        import pymupdf

        with pymupdf.open(pdf) as doc:
            for number in hits:
                try:
                    panel = read_page(pdf, doc[number - 1], number)
                except (OSError, RuntimeError, ValueError):
                    panel = None
                if panel is None:
                    findings.append({"page": number, "rule": RULE, "reason": "unproven_ruled_daily_log"})
                elif groups and joins(groups[-1][-1], panel, contexts):
                    groups[-1].append(panel)
                elif continuation_row(panel.rows[0], DESCRIPTION):
                    findings.append({"page": number, "rule": RULE, "reason": "unproven_description_continuation"})
                else:
                    groups.append([panel])
    except (ImportError, OSError, RuntimeError, ValueError):
        return chunks, tables, [{"page": min(numbers), "rule": RULE, "reason": "daily_log_source_unavailable"}] if numbers else []
    for group in groups:
        start = group[0].page
        remove = native_matches(tables, group)
        if remove is None:
            findings.append({"page": start, "rule": RULE, "reason": "ambiguous_native_daily_log"})
            continue
        index = next((i for i, row in enumerate(chunks) if row["table_id"] in remove or (row["page"] or 0) >= start), len(chunks))
        template = dict(chunk_template(chunks[min(index, len(chunks) - 1)]), section=None, section_path=[], ocr=False, quality="ok")
        built = assemble(group, doc_id, f"{doc_id}#{RULE}-p{start}", template, max_chars,
                         rule=RULE, description_column=DESCRIPTION)
        if built is None:
            findings.append({"page": start, "rule": RULE, "reason": "unproven_daily_log_chunk_spans"})
            continue
        table, pieces = built
        chunks = replace_chunks(chunks, pieces, remove)
        first = next((i for i, row in enumerate(tables) if row["table_id"] in remove), len(tables))
        tables = tables[:first] + [table] + [row for row in tables[first:] if row["table_id"] not in remove]
    return chunks, tables, findings
