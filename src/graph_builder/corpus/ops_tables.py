"""Rebuild RIMBase "Operations Summary" tables from the PDF text layer, with Docling as the fallback.

The conversion stage (Docling) misreads this table in several ways: it merges the "Operations Description" and
"Non-Prod" headers, puts the X mark in a wrong column, spills description words into other cells, and on a few pages
finds no table at all. Every daily report prints the same table, so a page that matches the format can be read from the
word boxes of its own text layer: the column anchors come from the header words of that page, a data row starts with
two time tokens, and an ``X`` token whose centre lies under the ``Non-Prod`` header is the mark.

Two layers cooperate. ``table_recognition`` decides, from evidence on the page itself (title, header, first row), whether
the page has this table format at all and says why not when it has not. This module reads the rows of a recognised table,
runs the self-checks and merges the result into the K1 chunks and tables. The schema (title words, column labels,
patterns) and every tolerance are the ``table_rules.operations_summary`` settings of ``configs/corpus/k1.json``; the
tolerances are fractions of the text height of the page (``em_header``) or of the page width, never points.

Nothing here changes how other pages or tables are read. A rebuilt table replaces the Docling table (same K1 table
id) or, when Docling found none, is added with a new id after the existing ones. If the page does not match the
format or any self-check fails, the Docling table is kept and the reason is recorded (``FALLBACK_REASONS``) together
with one of four states: ``SUPPORTED_AND_VALIDATED`` (only after a successful merge), ``RECOGNISED_BUT_FAILED``,
``UNSUPPORTED_FORMAT`` and ``PARSING_FAILURE``. "Validated" means consistent with the text layer of the page itself,
not compared with the page image. An error on one page or table is recorded and does not stop the document.
The result depends only on the PDF and the settings, so it is deterministic.
"""
from __future__ import annotations

from collections import Counter
import logging
from pathlib import Path
import re
from typing import Any

from . import table_recognition as recognition
from .report_context import pdf_page_texts
from .table_recognition import REASON_STATE, page_lines
from .text_layer import source_page

LOGGER = logging.getLogger(__name__)
RULE = "operations_summary"
SOURCE_PREFIX = "textlayer:operations_summary"
FALLBACK_REASONS = tuple(REASON_STATE)
SUPPORTED = "SUPPORTED_AND_VALIDATED"


class Fallback(Exception):
    """The page does not match the format or fails a self-check; ``reason`` is one of FALLBACK_REASONS."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


def state_of(reason: str) -> str:
    """State of a reason code (``UNSUPPORTED_FORMAT``, ``RECOGNISED_BUT_FAILED`` or ``PARSING_FAILURE``).

    ``SUPPORTED_AND_VALIDATED`` has no reason code: ``repair_document`` assigns it after a successful merge.
    """
    return recognition.state_of_reason(reason)


def labels(rule: dict) -> list[str]:
    return [column["label"] for column in rule["schema"]["columns"]]


def column_label(rule: dict, kind: str) -> str:
    return next(column["label"] for column in rule["schema"]["columns"] if column["kind"] == kind)


def pattern(rule: dict, name: str) -> re.Pattern:
    return re.compile(rule["schema"]["patterns"][name])


def centre(word: dict) -> float:
    return (word["bbox"][0] + word["bbox"][2]) / 2


def is_time_line(line: dict, rule: dict) -> bool:
    words, time = line["words"], pattern(rule, "time")
    return len(words) >= 2 and bool(time.match(words[0]["text"])) and bool(time.match(words[1]["text"]))


def is_section_title(line: dict, page_width: float, rule: dict) -> bool:
    """A short, title-case line centred on the page, like the "Management Summary" title that follows the table."""
    section = rule["tolerances"]["section_title"]
    words, word = line["words"], re.compile(section["word_pattern"])
    middle = (words[0]["bbox"][0] + words[-1]["bbox"][2]) / 2
    return (1 <= len(words) <= section["max_words"] and all(word.match(w["text"]) for w in words)
            and abs(middle - page_width / 2) <= section["centre_tolerance_page_width"] * page_width)


def clock_minutes(token: str) -> int:
    """Minutes since midnight; ``24:00`` is the end of the day."""
    hours, minutes = map(int, token.split(":"))
    if hours > 24 or (hours == 24 and minutes):
        raise Fallback("time_invalid", token)
    return hours * 60 + minutes


def read_row(line: dict, zones: dict[str, float], rule: dict) -> dict:
    """Split the first line of a row into From, To, Elapsed, End MD, Code and the start of the description."""
    words = line["words"]
    from_word, to_word = words[0], words[1]
    if not (centre(from_word) < zones["from_to"] <= centre(to_word) < zones["to_elapsed"]):
        raise Fallback("time_invalid", f"{from_word['text']} {to_word['text']} outside the From/To columns")
    clock_minutes(from_word["text"]), clock_minutes(to_word["text"])
    rest = words[2:]
    if len(rest) < 2:
        raise Fallback("column_mismatch", f"row {from_word['text']}-{to_word['text']} has no Elapsed and End MD")
    elapsed, depth = rest[0], rest[1]
    if not (pattern(rule, "hours").match(elapsed["text"]) and zones["to_elapsed"] <= centre(elapsed) < zones["elapsed_depth"]):
        raise Fallback("column_mismatch", f"Elapsed {elapsed['text']}")
    if not (pattern(rule, "depth").match(depth["text"]) and zones["elapsed_depth"] <= centre(depth) < zones["depth_code"]):
        raise Fallback("column_mismatch", f"End MD {depth['text']}")
    rest = rest[2:]
    code = ""
    if rest and zones["depth_code"] <= centre(rest[0]) <= zones["code_limit"]:
        code = rest[0]["text"]
        if not pattern(rule, "code").match(code):
            raise Fallback("column_mismatch", f"Code {code}")
        rest = rest[1:]
    return {"from": from_word["text"], "to": to_word["text"], "elapsed": elapsed["text"], "end_md": depth["text"],
            "code": code, "lines": [line], "first_description": rest}


def split_marks(words: list[dict], zones: dict[str, float], rule: dict) -> tuple[list[dict], list[dict]]:
    """(description words, marks): only a token that is exactly the mark glyph under the mark column header is a mark."""
    glyph = rule["schema"]["mark"]["glyph"]
    marks = [w for w in words if w["text"] == glyph and zones["non_prod_left"] <= centre(w) <= zones["non_prod_right"]]
    return [w for w in words if not any(w is mark for mark in marks)], marks


def check_elapsed(row: dict, rule: dict) -> None:
    tolerance = rule["tolerances"]["elapsed_tolerance_minutes"]
    start, end = clock_minutes(row["from"]), clock_minutes(row["to"])
    span = (end - start) % 1440
    if abs(float(row["elapsed"]) * 60 - span) > tolerance and not (
            span == 0 and abs(float(row["elapsed"]) * 60 - 1440) <= tolerance):
        raise Fallback("elapsed_mismatch", f"{row['from']}-{row['to']} elapsed {row['elapsed']}")


def read_table(layer: dict, lines: list[dict], at: int, rule: dict, titles: frozenset = frozenset(),
               trace: dict | None = None) -> tuple[dict, int]:
    """Read the table whose title is ``lines[at]``; returns the table and the index of the first line after it.

    ``titles`` holds the indexes of the lines that passed the title gate (so a following table's title is not taken for a
    stray line). ``trace`` receives what the gates measured and the stage reached, for the evidence record.
    """
    trace = {} if trace is None else trace
    trace.update(stage="recognition", rejected_at=None, header=None, rows=None, above=[])
    header = recognition.recognise_header(lines, at, rule)
    trace["header"] = header["evidence"]
    if not header["ok"]:
        trace["rejected_at"] = "G2"
        raise Fallback(header["reason"], header["detail"])
    size, header_line = header["em"], lines[header["line"]]
    gate = recognition.first_row_gate(lines, header["line"], rule, size)
    trace["rows"] = gate["evidence"]
    if not gate["ok"]:
        trace["rejected_at"] = "G3"
        raise Fallback(gate["reason"], gate["detail"])
    trace["above"] = recognition.above_flag(lines, at, rule, size)
    trace["stage"] = "read"
    zones = recognition.zones_from_header(header["boxes"], rule)
    line_gap = rule["tolerances"]["line_gap_em_header"] * size
    indent = rule["tolerances"]["continuation_indent_em_header"] * size
    rows: list[dict] = []
    anchor = None
    position, previous = header["line"] + 1, header_line
    while position < len(lines):
        line = lines[position]
        near = line["top"] - previous["bottom"] <= line_gap
        if is_time_line(line, rule) and near:
            rows.append(read_row(line, zones, rule))
            words = split_marks(rows[-1]["first_description"], zones, rule)[0]
            if anchor is None and words:
                anchor = words[0]["bbox"][0]
        elif (rows and anchor is not None and near and not is_time_line(line, rule)
              and abs(line["words"][0]["bbox"][0] - anchor) <= indent):
            rows[-1]["lines"].append(line)
        else:
            break
        previous = line
        position += 1
    if not rows:
        raise Fallback("no_rows")
    if position < len(lines):  # a line stuck to the table that is neither a row nor a title (this table's kind or a section)
        following = lines[position]
        if following["top"] - previous["bottom"] <= line_gap and position not in titles \
                and not is_section_title(following, layer["width"], rule):
            raise Fallback("trailing_line", " ".join(w["text"] for w in following["words"])[:60])
    trace["stage"] = "validate"
    for index in range(position, len(lines)):
        if index in titles:
            break
        if is_time_line(lines[index], rule):
            orphan = lines[index]["words"]
            raise Fallback("row_count_mismatch", f"time line {orphan[0]['text']} {orphan[1]['text']} "
                                                 "after the end of the table")
    table_words = list(header_line["words"])
    cells = []
    for row in rows:
        check_elapsed(row, rule)
        description, marks = split_marks(row["first_description"] + [w for extra in row["lines"][1:]
                                                                      for w in extra["words"]], zones, rule)
        if len(marks) > 1:
            raise Fallback("x_unmapped", f"{len(marks)} X marks in row {row['from']}-{row['to']}")
        row.update(description=description, marks=marks)
        cells.append([row["from"], row["to"], row["elapsed"], row["end_md"], row["code"],
                      " ".join(w["text"] for w in description), rule["schema"]["mark"]["glyph"] if marks else ""])
        table_words.extend(w for line in row["lines"] for w in line["words"])
    check_text_layer(layer, zones, rows, lines[header["line"] + 1:position], rule, size)
    box = [min(w["bbox"][0] for w in table_words), min(w["bbox"][1] for w in table_words),
           max(w["bbox"][2] for w in table_words), max(w["bbox"][3] for w in table_words)]
    return {"zones": zones, "rows": cells, "bbox": box, "top": lines[at]["top"], "bottom": lines[position - 1]["bottom"],
            "title_top": lines[at]["top"]}, position


def check_text_layer(layer: dict, zones: dict[str, float], rows: list[dict], consumed: list[dict], rule: dict,
                     em_header: float) -> None:
    """Compare the rebuilt rows with the page's words and glyphs in the table's vertical band (independent selection)."""
    top, bottom = min(line["top"] for line in consumed), max(line["bottom"] for line in consumed)
    left = zones["left"] - rule["tolerances"]["band_margin_em_header"] * em_header
    words = [w for w in layer["words"] if top <= (w["bbox"][1] + w["bbox"][3]) / 2 <= bottom and centre(w) >= left]
    used = [w for row in rows for line in row["lines"] for w in line["words"]]
    if Counter(w["text"] for w in words) != Counter(w["text"] for w in used):
        raise Fallback("word_mismatch", "words in the table band differ from the rebuilt rows")
    glyphs = [c["text"] for c in layer["chars"]
              if top <= (c["bbox"][1] + c["bbox"][3]) / 2 <= bottom and centre(c) >= left]
    if Counter(glyphs) != Counter("".join(w["text"] for w in used)):
        raise Fallback("word_mismatch", "glyphs in the table band differ from the rebuilt rows")
    # Under the mark column header only an exact mark glyph is a mark. A lookalike ("x", "×") or a tick-like symbol ("✓")
    # there could be a mark in another notation, so it is not folded into the description. Plain punctuation ("-", "...")
    # is not a lookalike: the report prints such tokens as part of wrapped descriptions in that x range.
    mark = rule["schema"]["mark"]
    stray = [w for w in words if w["text"] != mark["glyph"] and zones["non_prod_left"] <= centre(w) <= zones["non_prod_right"]
             and (w["text"].lower() == mark["glyph"].lower() or w["text"] in mark["lookalikes"])]
    if stray:
        raise Fallback("x_unmapped", f"unexpected mark {stray[0]['text']!r} under {column_label(rule, 'mark')}")


def page_result(layer: dict, index: int, status: str, reason: str | None, detail: str, trace: dict, mention: dict | None,
                rule: dict, **extra: Any) -> dict:
    """One occurrence of the title on a page, as ``read_page`` reports it (before any merge: no state, only ``status``)."""
    rejected_at = trace.get("rejected_at")
    evidence = recognition.build_evidence(mention["evidence"]["title"] if mention else None, trace.get("header"),
                                          trace.get("rows"), "rejected" if rejected_at else "recognised", rejected_at, rule)
    annotations = (mention["annotations"] if mention else []) + trace.get("above", [])
    stage = REASON_STATE[reason][1] if reason else "validate"
    return {"page": layer["page"], "index": index, "status": status, "reason": reason, "detail": detail, "stage": stage,
            "evidence": evidence, "annotations": annotations, "completeness": recognition.completeness(annotations), **extra}


def page_rejections(layer: dict, rule: dict) -> list[dict]:
    """The mention lines of the page that failed the title gate (the sentence or contents line that names the table)."""
    return [mention for mention in recognition.mention_lines(layer, rule) if not mention["passed"]]


def read_page(layer: dict, rule: dict) -> list[dict]:
    """Every title that passed the title gate on a page: ``rebuilt`` with rows and box (read, not yet merged), or
    ``fallback`` with a reason. A page without such a title gives ``[]``; a rotated page one ``rotated_page`` result."""
    if layer["rotation"] != 0:
        trace = {"rejected_at": "G0"}
        return [page_result(layer, 1, "fallback", "rotated_page", f"rotation {layer['rotation']}", trace, None, rule)]
    lines = page_lines(layer)
    mentions = [mention for mention in recognition.mention_lines(layer, rule, lines) if mention["passed"]]
    titles = frozenset(mention["line"] for mention in mentions)
    results, resume, index = [], 0, 0
    for mention in mentions:
        if mention["line"] < resume:  # inside a table that was just read
            continue
        index += 1
        trace: dict = {}
        try:
            table, after = read_table(layer, lines, mention["line"], rule, titles, trace)
        except Fallback as failure:
            results.append(page_result(layer, index, "fallback", failure.reason, failure.detail, trace, mention, rule))
            resume = mention["line"] + 1
            continue
        except MemoryError:
            raise
        except Exception as error:  # a defect in the rule must not stop the document
            LOGGER.warning("operations_summary: %s while reading page %s", type(error).__name__, layer["page"], exc_info=True)
            results.append(page_result(layer, index, "fallback", "rule_exception",
                                       f"{type(error).__name__}@{trace.get('stage', 'recognition')}", trace, mention, rule))
            resume = mention["line"] + 1
            continue
        results.append(page_result(layer, index, "rebuilt", None, "", trace, mention, rule, rows=table["rows"],
                                   bbox=table["bbox"], span=[table["title_top"], table["bottom"]]))
        resume = after
    return results


def tokens(text: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def markdown(grid: list[list[str]]) -> str:
    lines = ["| " + " | ".join(value.replace("|", "\\|") for value in row) + " |" for row in grid]
    return "\n".join([lines[0], "| " + " | ".join("---" for _ in grid[0]) + " |", *lines[1:]])


def table_record(logical_id: str, doc_id: str, source_ref: str, page: int, result: dict, rule: dict) -> dict:
    """A corpus-format table (plus ``grid``) for a rebuilt table: one header row, one column per schema label."""
    header = labels(rule)
    grid = [header, *result["rows"]]
    cells = [{"r": r, "c": c, "row_span": 1, "col_span": 1, "text": value, "is_header": r == 0}
             for r, row in enumerate(grid) for c, value in enumerate(row) if value]
    rows_text = ["; ".join(f"{header[c]}: {value}" for c, value in enumerate(row)) for row in grid[1:]]
    return {"table_id": logical_id, "doc_id": doc_id, "source_ref": source_ref,
            "regions": [{"page": page, "bbox": result["bbox"]}], "num_rows": len(grid), "num_cols": len(header),
            "header_rows": 1, "cells": cells, "rows_text": rows_text, "grid": grid}


def table_chunks(table: dict, template: dict, max_chars: int) -> list[dict]:
    """Table chunks like the ones Docling tables get: header repeated, whole rows, row range per chunk."""
    from ..ingestion.chunking import split_table
    from .chunking import language
    page = table["regions"][0]["page"]
    chunks, next_row = [], table["header_rows"]
    for number, part in enumerate(split_table(markdown(table["grid"]), "", max_chars)):
        rows = max(0, sum(line.strip().startswith("|") for line in part.splitlines()) - 2)
        end = min(next_row + rows, table["num_rows"])
        chunks.append(dict(template, chunk_id=f"{table['table_id']}:ops{number}", type="table", text=part, page=page,
                           pages=[page], regions=table["regions"],
                           source_spans=[{"source_ref": table["source_ref"], "page": page, "start": 0,
                                          "end": len(part), "source_start": 0, "source_end": 0}],
                           table_id=table["table_id"], row_start=next_row, row_end=end, language=language(part)))
        next_row = end
    return chunks


def docling_counterparts(page: int, span: list[float], tables: list[dict], taken: set[int],
                         overlap: float) -> tuple[list[int], list[int]]:
    """(counterparts, partial) among the Docling tables on ``page`` not yet taken: a counterpart lies at least ``overlap``
    inside ``span`` (the text-layer table's vertical extent) or covers at least ``overlap`` of it; a partial table
    touches ``span`` without either, so it is neither a clear match nor clear of the rebuilt table."""
    found, partial = [], []
    for index, table in enumerate(tables):
        if index in taken or page not in {region["page"] for region in table["regions"]}:
            continue
        top = min(r["bbox"][1] for r in table["regions"] if r["page"] == page)
        bottom = max(r["bbox"][3] for r in table["regions"] if r["page"] == page)
        shared = min(bottom, span[1]) - max(top, span[0])
        if shared <= 0:
            continue
        if shared / (bottom - top) >= overlap or shared / (span[1] - span[0]) >= overlap:
            found.append(index)
        else:
            partial.append(index)
    return found, partial


def anchor_position(chunks: list[dict], page: int, rule: dict) -> int:
    """Index of the chunk after which a new table chunk goes: the page's chunk that mentions the table, else the
    last chunk that starts on or before the page."""
    mark = re.escape(column_label(rule, "mark"))
    anchor = re.compile(f"{recognition.title_phrase_pattern(rule)}|{mark}")
    mention = [i for i, c in enumerate(chunks) if c["type"] == "text" and page in c["pages"] and anchor.search(c["text"])]
    if mention:
        return mention[-1]
    before = [i for i, c in enumerate(chunks) if c["pages"] and min(c["pages"]) <= page]
    return before[-1] if before else len(chunks) - 1


def new_record(doc_id: str, page: int, index: int, status: str, reason: str | None, detail: str, evidence: dict | None,
               annotations: list[dict], completeness: str | None, rejected: int) -> dict:
    """A sidecar record: what happened to one occurrence of the table on a page. ``state`` stays ``None`` for a table that
    was read but not merged yet; ``repair_document`` sets it (``SUPPORTED_AND_VALIDATED`` only after the merge)."""
    return {"doc_id": doc_id, "page": page, "index": index, "status": status, "reason": reason, "detail": detail,
            "action": "kept_docling", "table_id": None, "state": state_of(reason) if reason else None,
            "stage": REASON_STATE[reason][1] if reason else None, "evidence": evidence, "annotations": annotations,
            "completeness": completeness, "rejected_mentions": rejected}


def fail(record: dict, reason: str, detail: str) -> None:
    """Keep the Docling table: the record says why, with the state that belongs to the reason."""
    record.update(status="fallback", reason=reason, detail=detail, action="kept_docling", table_id=None,
                  state=state_of(reason), stage=REASON_STATE[reason][1])
    record.pop("docling_table", None)


def repair_document(pdf: Path, numbers: list[int], chunks: list[dict], tables: list[dict], doc_id: str, file_id: str,
                    max_chars: int, rule: dict) -> dict[str, Any]:
    """Apply the rule to one document: returns the new ``chunks`` and ``tables`` and one record per occurrence.

    Existing tables keep their position (so their K1 ids); tables Docling did not find are appended in page order.
    Chunks of other tables and all text chunks are not touched. An exception while reading a page, reading a table or
    merging one is recorded (``PARSING_FAILURE``) and the other pages and tables are still processed.
    """
    chunks, tables = list(chunks), list(tables)
    texts = pdf_page_texts(pdf, numbers)
    gate = re.compile(recognition.title_phrase_pattern(rule))
    overlap = rule["tolerances"]["docling_overlap"]
    title = " ".join(rule["schema"]["title_words"])
    records, taken = [], set()
    docling_pages = Counter(page for table in tables if looks_like_operations(table, rule)
                            for page in {region["page"] for region in table["regions"]})

    def merge(result: dict, record: dict, layer: dict, page: int) -> None:
        matches, partial = docling_counterparts(page, result["span"], tables, taken, overlap)
        if len(matches) > 1 or partial:
            return fail(record, "ambiguous_docling_match",
                        f"{len(matches)} matching and {len(partial)} partly overlapping Docling tables")
        region_tokens = Counter()
        for word in layer["words"]:
            if result["span"][0] <= (word["bbox"][1] + word["bbox"][3]) / 2 <= result["span"][1]:
                region_tokens += tokens(word["text"])
        source_ref = f"{SOURCE_PREFIX}:p{page}:{result['index']}"
        if matches:
            old = tables[matches[0]]
            if len({region["page"] for region in old["regions"]}) > 1:
                return fail(record, "docling_multipage", old["table_id"])
            docling_tokens = sum((tokens(cell["text"]) for cell in old["cells"]), Counter())
            if docling_tokens - region_tokens:
                return fail(record, "docling_extent_mismatch", old["table_id"])
            old_chunks = [i for i, c in enumerate(chunks) if c["table_id"] == old["table_id"]]
            if old_chunks and old_chunks != list(range(old_chunks[0], old_chunks[-1] + 1)):
                return fail(record, "docling_multipage", "chunks of the table are not contiguous")
            table = table_record(old["table_id"], doc_id, source_ref, page, result, rule)
            if old_chunks:
                start, stop = old_chunks[0], old_chunks[-1] + 1
                chunks[start:stop] = table_chunks(table, chunk_template(chunks[start]), max_chars)
            else:
                position = anchor_position(chunks, page, rule)
                chunks[position + 1:position + 1] = table_chunks(table, chunk_template(chunks[position]), max_chars)
            tables[matches[0]] = table
            taken.add(matches[0])
            record.update(action="replaced", table_id=f"{file_id}:t{matches[0] + 1}", docling_table=old["table_id"])
        else:
            table = table_record(f"{doc_id}#t{len(tables):04d}", doc_id, source_ref, page, result, rule)
            position = anchor_position(chunks, page, rule)
            chunks[position + 1:position + 1] = table_chunks(table, chunk_template(chunks[position]), max_chars)
            tables.append(table)
            taken.add(len(tables) - 1)
            record.update(action="added", table_id=f"{file_id}:t{len(tables)}")
        record.update(status="rebuilt", reason=None, detail="", state=SUPPORTED, stage="merge")

    for page in numbers:
        mentioned = bool(gate.search(texts[page]))
        if not mentioned and not docling_pages[page]:
            continue
        layer, results, rejections, failure = None, [], [], None
        if mentioned:
            try:
                layer = source_page(pdf, page)
            except MemoryError:
                raise
            except Exception as error:
                LOGGER.warning("operations_summary: %s while reading the text layer of page %s", type(error).__name__, page,
                               exc_info=True)
                failure = ("text_layer_read_error", type(error).__name__)
            else:
                try:
                    results = read_page(layer, rule)
                    rejections = page_rejections(layer, rule) if layer["rotation"] == 0 else []
                except MemoryError:
                    raise
                except Exception as error:
                    LOGGER.warning("operations_summary: %s while recognising page %s", type(error).__name__, page,
                                   exc_info=True)
                    results, rejections, failure = [], [], ("rule_exception", f"{type(error).__name__}@recognition")
        if failure:
            records.append(new_record(doc_id, page, 1, "fallback", failure[0], failure[1], None, [], None, 0))
            continue
        if not results:  # a page that mentions the title, or holds a Docling Operations table, must leave a record
            first = rejections[0] if rejections else None
            where = first["detail"] if first else "not_found" if mentioned else f"no '{title}' text on the page"
            evidence = recognition.build_evidence(first["evidence"]["title"] if first else None, None, None,
                                                  "rejected", "G1", rule)
            records.append(new_record(doc_id, page, 1, "fallback", "no_title",
                                      f"{where}; {docling_pages[page]} Docling table(s) with an Operations header",
                                      evidence, [], None, len(rejections)))
            continue
        for number, result in enumerate(results):
            record = new_record(doc_id, page, result["index"], result["status"], result["reason"], result["detail"],
                                result["evidence"], result["annotations"], result["completeness"],
                                len(rejections) if number == 0 else 0)
            records.append(record)
            if result["status"] != "rebuilt":
                continue
            try:
                merge(result, record, layer, page)
            except MemoryError:
                raise
            except Exception as error:
                LOGGER.warning("operations_summary: %s while merging a table of page %s", type(error).__name__, page,
                               exc_info=True)
                fail(record, "merge_exception", f"{type(error).__name__}@merge")
    return {"chunks": chunks, "tables": tables, "records": records}


def family_summary(records: list[dict]) -> dict[str, dict]:
    """Counters per document family (``document_type`` and ``rule`` of each record): records, records per state and per
    (state, reason), ``annotations_above`` (records with an annotation hint above the title) and ``parsing_failure_rate``
    (``PARSING_FAILURE`` records over all records of the family). Counts, not a measure of scalability."""
    families: dict[str, dict] = {}
    for record in records:
        key = f"{record.get('document_type')}/{record.get('rule')}"
        family = families.setdefault(key, {"document_type": record.get("document_type"), "rule": record.get("rule"),
                                           "records": 0, "by_state": {}, "by_state_reason": {}, "annotations_above": 0})
        family["records"] += 1
        state = record.get("state") or "UNKNOWN"
        family["by_state"][state] = family["by_state"].get(state, 0) + 1
        pair = f"{state}/{record.get('reason') or '-'}"
        family["by_state_reason"][pair] = family["by_state_reason"].get(pair, 0) + 1
        family["annotations_above"] += any(a.get("side") == "above" for a in record.get("annotations") or [])
    for family in families.values():
        family["parsing_failure_rate"] = family["by_state"].get("PARSING_FAILURE", 0) / family["records"]
    return dict(sorted(families.items()))


def looks_like_operations(table: dict, rule: dict) -> bool:
    """A Docling table whose first two rows mention the Operations header or title (same test as the regression)."""
    head = " ".join(cell["text"] for cell in table["cells"] if cell["r"] < 2)
    markers = (column_label(rule, "text"), column_label(rule, "mark"), " ".join(rule["schema"]["title_words"]))
    return any(marker in head for marker in markers)


def chunk_template(chunk: dict) -> dict:
    """Fields a table chunk inherits from the chunk it replaces or follows, so section numbering does not shift."""
    return {key: chunk[key] for key in ("doc_id", "section", "section_path", "ocr", "quality")}
