"""Cross-representation checks (A-403): do the representations inside one K1 release agree with each other?

K1 stores the same content several times: ``tables.jsonl`` (grid) and the table chunks of ``chunks.jsonl`` (Markdown rows),
``forms.jsonl`` (fields) and the form chunks (``key: value`` lines), ``files.jsonl`` page counts and ``pages.jsonl``,
chunk pages and parent / table / form records. The K1 validator checks schemas, references and the page rebuild, but not
that these copies carry the same content. This module compares them and emits QA signals; none is a publish gate.

What a pass means: the compared representations agree with each other (CROSS_REPRESENTATION_CONSISTENT at most). It does not
mean the content matches the PDF: a value that is wrong in every representation, swapped cells that were swapped before the
release was written, a wrong table structure with the same words and errors of the text layer stay invisible. The chunks
are derived from the same Docling / rule output as the records, so the check mainly detects later divergence and
export bugs. See KNOWN_BLIND_SPOTS in signals.py.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Iterator

from .signals import CheckContext, Registry

DEFAULT_CONFIG = Path("configs/qa/cross_representation.json")
CHECK_NAME = "cross_representation"
CHECK_VERSION = "1"
SEPARATOR_CELL = re.compile(r":?-{3,}:?")
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")

CROSSREP_LIMITATIONS = (
    "Compares representations written by the same pipeline from the same intermediate data: a value that is wrong in every representation, or a wrong table structure that keeps the same words, is not detected.",
    "Table chunks are compared row by row with the grid after whitespace collapse and pipe unescaping; the table caption that the chunker repeats before the Markdown header is NOT part of tables.jsonl and is only checked for consistency between the chunks of one table.",
    "Form chunks are compared with the fields of forms.jsonl in field order; the form bounding boxes and the reference text of forms.jsonl are not compared.",
    "tables.jsonl has three views of a table (grid, cells, rows_text); only the grid is compared with the chunks.",
    "Page coverage uses the pages named by chunks; a page whose chunks hold only part of its content is not detected.",
    "The check cannot say which representation is right when they differ: the signal names both sides.",
    "Memory is proportional to the text of the table and form chunks of one release; the release is read in two passes, not per document.",
)

# (code, severity, meaning, emitted_by). ERROR only where the rule is structural/referential and had no finding on both real releases.
REASONS = (
    ("XREP_TABLE_NO_CHUNK", "ERROR", "A table record in tables.jsonl has no table chunk in chunks.jsonl; its content cannot be retrieved.", CHECK_NAME),
    ("XREP_TABLE_CHUNK_ORPHAN", "ERROR", "A table chunk has no table_id or its table_id is not a table record of the release.", CHECK_NAME),
    ("XREP_ROW_RANGE_INVALID", "ERROR", "row_start/row_end of a table chunk is missing, reversed, before the header rows or beyond the table row count.", CHECK_NAME),
    ("XREP_ROW_RANGE_COVERAGE", "ERROR", "The row ranges of the chunks of one table leave a gap, overlap or do not end at the last row.", CHECK_NAME),
    ("XREP_FORM_NO_CHUNK", "ERROR", "A form record in forms.jsonl has no form chunk in chunks.jsonl.", CHECK_NAME),
    ("XREP_FORM_CHUNK_ORPHAN", "ERROR", "A form chunk has no form_id or its form_id is not a form record of the release.", CHECK_NAME),
    ("XREP_PAGE_COUNT_MISMATCH", "ERROR", "files.jsonl page_count differs from the number of pages in pages.jsonl, or the page numbers are not 1..page_count.", CHECK_NAME),
    ("XREP_TABLE_SHAPE", "WARN", "The grid of a table record does not match its own num_rows / num_cols.", CHECK_NAME),
    ("XREP_TABLE_CHUNK_MISMATCH", "WARN", "The header or the rows of a table chunk differ from the grid of its table record.", CHECK_NAME),
    ("XREP_FORM_CHUNK_MISMATCH", "WARN", "The text of the form chunk differs from the key: value lines built from its form record.", CHECK_NAME),
    ("XREP_PAGE_WITHOUT_CHUNKS", "WARN", "A page of pages.jsonl is named by no chunk and is not declared in the manifest exceptions (pages_without_context).", CHECK_NAME),
    ("XREP_CHUNK_PAGE_INCONSISTENT", "WARN", "The page, pages or regions of a chunk disagree with its parent, table or form record.", CHECK_NAME),
    ("XREP_PARENT_WITHOUT_CHUNKS", "WARN", "A parent record in parents.jsonl has no chunk.", CHECK_NAME),
    ("XREP_PAGE_EMPTY_BY_DIGEST", "INFO", "A page has no chunk and pages.jsonl records the digest of an empty filtered text; whether the PDF page really has no text is not checked here (see A-402).", CHECK_NAME),
)
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # sha256 of the empty string


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or DEFAULT_CONFIG).read_text(encoding="utf-8"))


def _limit(config: dict, name: str) -> int:
    return config["limits"][name]["value"]


def collapse(text: Any) -> str:
    """The chunker collapses blanks of table lines; tabs, newlines and repeated spaces carry no content."""
    return " ".join(str(text if text is not None else "").split())


def clip(text: str, config: dict) -> str:
    size = _limit(config, "max_evidence_chars")
    return text if len(text) <= size else text[:size] + "..."


def split_cells(line: str) -> list[str]:
    """Cells of one Markdown table line; ``\\|`` is a literal pipe, other blanks are collapsed."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [collapse(cell.replace("\\|", "|")) for cell in UNESCAPED_PIPE.split(body)]


def parse_table_chunk(text: str) -> dict:
    """Split a table chunk into caption lines, header cells, body rows and lines that could not be parsed."""
    caption, table_lines, stray = [], [], []
    for line in text.split("\n"):
        if line.strip().startswith("|"):
            table_lines.append(line)
        elif not line.strip():
            continue
        elif table_lines:
            stray.append(collapse(line))
        else:
            caption.append(collapse(line))
    header = split_cells(table_lines[0]) if table_lines else None
    separator_ok = len(table_lines) > 1 and all(SEPARATOR_CELL.fullmatch(cell) for cell in split_cells(table_lines[1]))
    rows = [split_cells(line) for line in table_lines[2:]] if separator_ok else [split_cells(line) for line in table_lines[1:]]
    return {"caption": caption, "header": header, "separator_ok": separator_ok, "rows": rows, "stray": stray}


WORD = re.compile(r"\w+")


def header_words(cells: list[str]) -> set[str]:
    """Word set of header cells; the separator Docling puts between merged header rows (" - ", " / ") carries no content."""
    return {word for cell in cells for word in WORD.findall(cell)}

def token_diff(left: list[str], right: list[str], config: dict) -> dict:
    """Whitespace tokens of ``left`` missing from ``right`` and vice versa (multiset difference)."""
    a, b = Counter(token for cell in left for token in cell.split()), Counter(token for cell in right for token in cell.split())
    size = _limit(config, "max_listed_tokens")
    return {"in_record_not_in_chunk": [clip(token, config) for token in sorted((a - b).elements())[:size]],
            "in_chunk_not_in_record": [clip(token, config) for token in sorted((b - a).elements())[:size]]}


def compare_table_chunk(table: dict, chunk: dict, parsed: dict, config: dict, range_ok: bool, rendered_header_rows: int) -> list[dict]:
    """Mismatches between one table chunk and the grid of its table record (empty list = consistent).

    ``rendered_header_rows`` is the number of grid rows the chunker rendered as the Markdown header: row_start of the
    first chunk (K1 does not store Docling's rendered header count, and it can differ from header_rows)."""
    grid = [[collapse(cell) for cell in row] for row in table.get("grid") or []]
    num_cols = table.get("num_cols") or 0
    out: list[dict] = []
    if parsed["header"] is None:
        return [{"chunk_id": chunk["chunk_id"], "kind": "no_markdown_table"}]
    if not parsed["separator_ok"]:
        out.append({"chunk_id": chunk["chunk_id"], "kind": "separator_row_missing"})
    if parsed["stray"]:
        out.append({"chunk_id": chunk["chunk_id"], "kind": "text_after_table", "lines": [clip(line, config) for line in parsed["stray"][:_limit(config, "max_listed_items")]]})
    header_source = [cell for row in grid[:rendered_header_rows] for cell in row]
    if len(parsed["header"]) != num_cols or header_words(parsed["header"]) != header_words(header_source):
        out.append({"chunk_id": chunk["chunk_id"], "kind": "header", "rendered_header_rows": rendered_header_rows,
                    "header_cells": len(parsed["header"]), "num_cols": num_cols, **token_diff(header_source, parsed["header"], config)})
    if not range_ok:
        return out  # rows cannot be aligned without a valid range; the table-level token comparison covers them
    expected = grid[chunk["row_start"]:chunk["row_end"]]
    actual = parsed["rows"]
    if len(expected) != len(actual):
        out.append({"chunk_id": chunk["chunk_id"], "kind": "row_count", "expected_rows": len(expected), "actual_rows": len(actual)})
        return out
    bad = []
    for offset, (want, got) in enumerate(zip(expected, actual)):
        if want != got:
            same = Counter(token for cell in want for token in cell.split()) == Counter(token for cell in got for token in cell.split())
            bad.append({"row": chunk["row_start"] + offset, "kind": "same_tokens_different_cells" if same else "cell_text",
                        **({} if same else token_diff(want, got, config))})
    if bad:
        out.append({"chunk_id": chunk["chunk_id"], "kind": "rows", "mismatching_rows": len(bad), "first": bad[:_limit(config, "max_listed_items")]})
    return out


def check_row_ranges(table: dict, chunks: list[dict]) -> tuple[bool, list[dict], list[dict]]:
    """(all chunk ranges individually valid, invalid-range findings, coverage findings) for the chunks of one table."""
    num_rows = table.get("num_rows")
    invalid, coverage = [], []
    for chunk in chunks:
        start, end = chunk.get("row_start"), chunk.get("row_end")
        if not isinstance(start, int) or not isinstance(end, int) or isinstance(start, bool) or isinstance(end, bool):
            invalid.append({"chunk_id": chunk["chunk_id"], "row_start": start, "row_end": end, "problem": "missing or not an integer"})
        elif start > end or start < 0 or (isinstance(num_rows, int) and end > num_rows):
            invalid.append({"chunk_id": chunk["chunk_id"], "row_start": start, "row_end": end, "num_rows": num_rows,
                            "problem": "reversed, negative or beyond num_rows"})
    if invalid:
        return False, invalid, coverage
    # The first chunk starts after the rows the chunker rendered as header (not stored in K1, so it is read from row_start).
    expected_start = chunks[0]["row_start"]
    for chunk in chunks:
        if chunk["row_start"] != expected_start:
            coverage.append({"chunk_id": chunk["chunk_id"], "row_start": chunk["row_start"], "expected_row_start": expected_start})
        expected_start = chunk["row_end"]
    if isinstance(num_rows, int) and expected_start != num_rows:
        coverage.append({"chunk_id": chunks[-1]["chunk_id"], "row_end": expected_start, "expected_row_end": num_rows})
    return True, invalid, coverage


def analyse_table(table: dict, chunks: list[dict], config: dict) -> list[tuple[str, dict]]:
    """Findings (code, evidence) of one table record against its table chunks (ordered by child_index)."""
    if not chunks:
        return [("XREP_TABLE_NO_CHUNK", {"table_id": table["table_id"], "num_rows": table.get("num_rows")})]
    found: list[tuple[str, dict]] = []
    grid = table.get("grid") or []
    wrong_rows = len(grid) != table.get("num_rows")
    wrong_cols = [index for index, row in enumerate(grid) if len(row) != table.get("num_cols")]
    if wrong_rows or wrong_cols:
        found.append(("XREP_TABLE_SHAPE", {"grid_rows": len(grid), "num_rows": table.get("num_rows"), "num_cols": table.get("num_cols"),
                                           "rows_with_other_width": wrong_cols[:_limit(config, "max_listed_items")]}))
    range_ok, invalid, coverage = check_row_ranges(table, chunks)
    if invalid:
        found.append(("XREP_ROW_RANGE_INVALID", {"chunks": invalid[:_limit(config, "max_listed_items")]}))
    if coverage:
        found.append(("XREP_ROW_RANGE_COVERAGE", {"problems": coverage[:_limit(config, "max_listed_items")], "num_rows": table.get("num_rows")}))
    parsed = [parse_table_chunk(chunk.get("text") or "") for chunk in chunks]
    mismatches: list[dict] = []
    rendered = chunks[0]["row_start"] if range_ok else 0
    for chunk, parts in zip(chunks, parsed):
        mismatches += compare_table_chunk(table, chunk, parts, config, range_ok, rendered)
    captions = {tuple(parts["caption"]) for parts in parsed}
    if len(captions) > 1:
        mismatches.append({"kind": "caption_differs_between_chunks", "captions": [clip(" / ".join(c), config) for c in sorted(captions)][:_limit(config, "max_listed_items")]})
    if not range_ok:  # compare all cells (header included) as one multiset; header lines repeat, so expect extra tokens only from them
        record_cells = [collapse(cell) for row in grid for cell in row]
        chunk_cells = [cell for cell in (parsed[0]["header"] or [])] + [cell for parts in parsed for row in parts["rows"] for cell in row]
        diff = token_diff(record_cells, chunk_cells, config)
        if diff["in_record_not_in_chunk"] or diff["in_chunk_not_in_record"]:
            mismatches.append({"kind": "table_tokens", **diff})
    if mismatches:
        found.append(("XREP_TABLE_CHUNK_MISMATCH", {"mismatches": mismatches[:_limit(config, "max_listed_items")], "mismatch_count": len(mismatches)}))
    return found


def expected_form_lines(form: dict) -> list[str]:
    """The lines K1 writes for a form chunk (k1_build.form_text): printed colon kept once, then the value."""
    return [collapse(field["key"].rstrip(":") + ": " + field["value"]) for field in form.get("fields") or []]


def analyse_form(form: dict, chunks: list[dict], config: dict) -> list[tuple[str, dict]]:
    if not chunks:
        return [("XREP_FORM_NO_CHUNK", {"form_id": form["form_id"], "fields": len(form.get("fields") or [])})]
    expected = expected_form_lines(form)
    actual = [collapse(line) for chunk in chunks for line in (chunk.get("text") or "").split("\n")]
    if expected == actual:
        return []
    bad = [{"line": index, "expected": clip(want, config), "actual": clip(got, config)}
           for index, (want, got) in enumerate(zip(expected, actual)) if want != got]
    return [("XREP_FORM_CHUNK_MISMATCH", {"form_id": form["form_id"], "expected_lines": len(expected), "actual_lines": len(actual),
                                          "mismatching_lines": len(bad), "first": bad[:_limit(config, "max_listed_items")]})]


def page_numbers_ok(file_row: dict, page_rows: list[dict]) -> tuple[bool, dict]:
    numbers = sorted(row["page"] for row in page_rows)
    count = file_row.get("page_count")
    ok = count == len(numbers) and numbers == list(range(1, len(numbers) + 1))
    return ok, {"page_count": count, "pages_rows": len(numbers), "missing": sorted(set(range(1, (count or 0) + 1)) - set(numbers))[:20],
                "extra": sorted(set(numbers) - set(range(1, (count or 0) + 1)))[:20]}


def _read(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


class Findings:
    """Result of one release analysis: findings grouped by the ledger entity that carries the signal."""

    def __init__(self, release_dir: Path) -> None:
        self.release_dir = release_dir
        self.tables: dict[str, list[tuple[str, dict, dict]]] = {}
        self.documents: dict[str, list[tuple[str, dict, dict]]] = {}
        self.release: list[tuple[str, dict, dict]] = []
        self.stats: Counter = Counter()

    def add(self, store: dict, key: str, code: str, ids: dict, evidence: dict) -> None:
        store.setdefault(key, []).append((code, ids, evidence))

    def all_codes(self) -> Counter:
        counter: Counter = Counter()
        for group in (self.tables, self.documents):
            for rows in group.values():
                counter.update(code for code, _, _ in rows)
        counter.update(code for code, _, _ in self.release)
        return counter


def chunk_page_problems(chunk: dict, parent: dict | None, record: dict | None, kind: str) -> list[str]:
    """Why the page fields of a chunk disagree with its parent / table / form (check 6); empty list = consistent."""
    problems = []
    pages = chunk.get("pages") or []
    if chunk.get("page") is None or chunk["page"] not in pages:
        problems.append("page not in pages")
    if pages != sorted(set(pages)):
        problems.append("pages not sorted unique")
    region_pages = {region["page"] for region in chunk.get("regions") or []}
    if not region_pages <= set(pages):
        problems.append("region page not in pages")
    if parent is not None and parent.get("pages") is not None and not set(pages) <= set(parent["pages"]):
        problems.append("pages not inside parent pages")
    if kind == "table" and record is not None and not set(pages) <= set(record.get("pages") or []):
        problems.append("pages not inside table pages")
    if kind == "form" and record is not None and chunk.get("page") != record.get("page"):
        problems.append("page differs from form page")
    return problems


def analyse_release(release_dir: Path, config: dict) -> Findings:
    """Run all cross-representation checks over one release (read-only, two passes over chunks.jsonl)."""
    findings = Findings(release_dir)
    size = _limit(config, "max_listed_items")
    files = {row["file_id"]: row for row in _read(release_dir / "files.jsonl")}
    pages: dict[str, list[dict]] = {}
    for row in _read(release_dir / "pages.jsonl"):
        pages.setdefault(row["file_id"], []).append(row)
    tables = {row["table_id"]: row for row in _read(release_dir / "tables.jsonl")}
    forms = {row["form_id"]: row for row in _read(release_dir / "forms.jsonl")}
    parents = {row["parent_id"]: row for row in _read(release_dir / "parents.jsonl")}
    manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    declared = {(item["doc_id"], item["page"]) for item in manifest.get("pages_without_context") or []}

    table_chunks: dict[str, list[dict]] = {}
    form_chunks: dict[str, list[dict]] = {}
    covered: dict[str, set[int]] = {}
    parents_with_chunks: set[str] = set()
    for chunk in _read(release_dir / "chunks.jsonl"):
        file_id = chunk.get("file_id")
        findings.stats["chunks"] += 1
        parents_with_chunks.add(chunk.get("parent_id"))
        covered.setdefault(file_id, set()).update(chunk.get("pages") or [])
        ids = {"file_id": file_id, "chunk_id": chunk.get("chunk_id")}
        if chunk.get("type") == "table" or chunk.get("table_id"):
            if chunk.get("table_id") in tables:
                table_chunks.setdefault(chunk["table_id"], []).append(chunk)
            else:
                findings.add(findings.documents, file_id, "XREP_TABLE_CHUNK_ORPHAN", ids, {"table_id": chunk.get("table_id"), "type": chunk.get("type")})
        if chunk.get("type") == "form" or chunk.get("form_id"):
            if chunk.get("form_id") in forms:
                form_chunks.setdefault(chunk["form_id"], []).append(chunk)
            else:
                findings.add(findings.documents, file_id, "XREP_FORM_CHUNK_ORPHAN", ids, {"form_id": chunk.get("form_id"), "type": chunk.get("type")})
        kind = "table" if chunk.get("table_id") in tables else "form" if chunk.get("form_id") in forms else "text"
        record = tables.get(chunk.get("table_id")) if kind == "table" else forms.get(chunk.get("form_id")) if kind == "form" else None
        problems = chunk_page_problems(chunk, parents.get(chunk.get("parent_id")), record, kind)
        findings.stats["chunks_page_checked"] += 1
        if problems:
            findings.add(findings.documents, file_id, "XREP_CHUNK_PAGE_INCONSISTENT", ids,
                         {"problems": problems, "page": chunk.get("page"), "pages": chunk.get("pages"),
                          "region_pages": sorted({region["page"] for region in chunk.get("regions") or []})})

    for table_id in sorted(tables):
        table = tables[table_id]
        findings.stats["tables"] += 1
        chunks = sorted(table_chunks.get(table_id, []), key=lambda c: (c.get("child_index") is None, c.get("child_index"), c.get("chunk_id")))
        findings.stats["table_chunks"] += len(chunks)
        ids = {"file_id": table.get("file_id"), "table_id": table_id}
        try:
            for code, evidence in analyse_table(table, chunks, config):
                findings.add(findings.tables, table_id, code, ids, evidence)
        except Exception as error:  # noqa: BLE001 - failure isolation per table
            findings.add(findings.tables, table_id, "QA_ERROR", ids, {"check": CHECK_NAME, "error": type(error).__name__, "detail": str(error)[:300]})
    for form_id in sorted(forms):
        form = forms[form_id]
        findings.stats["forms"] += 1
        chunks = sorted(form_chunks.get(form_id, []), key=lambda c: (c.get("child_index") is None, c.get("child_index"), c.get("chunk_id")))
        findings.stats["form_chunks"] += len(chunks)
        ids = {"file_id": form.get("file_id"), "form_id": form_id}
        try:
            for code, evidence in analyse_form(form, chunks, config):
                findings.add(findings.documents, form.get("file_id"), code, ids, evidence)
        except Exception as error:  # noqa: BLE001
            findings.add(findings.documents, form.get("file_id"), "QA_ERROR", ids, {"check": CHECK_NAME, "error": type(error).__name__, "detail": str(error)[:300]})

    for file_id in sorted(files):
        file_row = files[file_id]
        findings.stats["documents"] += 1
        page_rows = pages.get(file_id, [])
        findings.stats["pages"] += len(page_rows)
        ids = {"file_id": file_id}
        ok, evidence = page_numbers_ok(file_row, page_rows)
        if not ok:
            findings.add(findings.documents, file_id, "XREP_PAGE_COUNT_MISMATCH", ids, evidence)
        no_chunk = [row for row in page_rows if row["page"] not in covered.get(file_id, set())
                    and (file_row.get("doc_id"), row["page"]) not in declared]
        empty_declared = sorted(row["page"] for row in no_chunk if row.get("filtered_text_sha256") == EMPTY_SHA256)
        if empty_declared:  # pages.jsonl itself records an empty filtered text (the K1 validator rebuilds it from the chunks)
            findings.add(findings.documents, file_id, "XREP_PAGE_EMPTY_BY_DIGEST", ids, {"pages": empty_declared[:size]})
        empty = sorted(row["page"] for row in no_chunk if row.get("filtered_text_sha256") != EMPTY_SHA256)
        if empty:
            statuses = {row["page"]: row.get("status") for row in page_rows if row["page"] in empty}
            findings.add(findings.documents, file_id, "XREP_PAGE_WITHOUT_CHUNKS", ids,
                         {"pages": empty[:size], "page_count_without_chunks": len(empty), "page_status": {str(k): statuses[k] for k in sorted(statuses)[:size]}})
    for parent_id in sorted(set(parents) - parents_with_chunks):
        findings.stats["parents_without_chunks"] += 1
        findings.add(findings.documents, parents[parent_id].get("file_id"), "XREP_PARENT_WITHOUT_CHUNKS",
                     {"file_id": parents[parent_id].get("file_id"), "parent_id": parent_id}, {"type": parents[parent_id].get("type")})
    findings.stats["parents"] = len(parents)
    return findings


def to_signals(registry: Registry, rows: list[tuple[str, dict, dict]], scope: str) -> list[dict]:
    return [registry.signal(code, scope, ids, evidence=evidence) for code, ids, evidence in rows]


def register_crossrep(registry: Registry, config_path: Path | None = None) -> Registry:
    """Add the reason codes and three checks (table, document, release scope) to a quality-ledger registry.

    The release is analysed once, lazily, by the first entity the checks see. Only the table check grants a level
    (CROSS_REPRESENTATION_CONSISTENT, for a table whose chunks agree with its record)."""
    config = load_config(config_path)
    holder: dict[str, Findings] = {}
    for code, severity, meaning, emitter in REASONS:
        registry.register_reason(code, severity, meaning, emitter)

    def findings_for(context: CheckContext) -> Findings:
        current = holder.get("findings")
        if current is None or current.release_dir != Path(context.release_dir):
            current = holder["findings"] = analyse_release(Path(context.release_dir), config)
        return current

    def table_check(context: CheckContext, entity: dict) -> list[dict]:
        return to_signals(registry, findings_for(context).tables.get(entity["ids"]["table_id"], []), "table")

    def document_check(context: CheckContext, entity: dict) -> list[dict]:
        return to_signals(registry, findings_for(context).documents.get(entity["ids"]["file_id"], []), "document")

    def release_check(context: CheckContext, entity: dict) -> list[dict]:
        return to_signals(registry, findings_for(context).release, "release")

    registry.register_check(CHECK_NAME + "_table", table_check, "table", CHECK_VERSION, grants="CROSS_REPRESENTATION_CONSISTENT",
                            limitations=CROSSREP_LIMITATIONS)
    registry.register_check(CHECK_NAME + "_document", document_check, "document", CHECK_VERSION, limitations=CROSSREP_LIMITATIONS)
    registry.register_check(CHECK_NAME + "_release", release_check, "release", CHECK_VERSION, limitations=CROSSREP_LIMITATIONS)
    registry.crossrep_holder = holder  # type: ignore[attr-defined]
    return registry


def run_standalone(release_dir: Path, out_dir: Path | None = None, config_path: Path | None = None) -> dict:
    """Degraded mode without the quality ledger: the same signal objects in ``qa-crossrep.json`` (read-only on the release)."""
    config = load_config(config_path)
    registry = Registry()
    for code, severity, meaning, emitter in REASONS:
        registry.register_reason(code, severity, meaning, emitter)
    registry.reasons.setdefault("QA_ERROR", Registry().reasons["QA_ERROR"])
    findings = analyse_release(release_dir, config)
    signals = (to_signals(registry, [row for rows in findings.tables.values() for row in rows], "table")
               + to_signals(registry, [row for rows in findings.documents.values() for row in rows], "document")
               + to_signals(registry, findings.release, "release"))
    signals.sort(key=lambda s: (s["code"], json.dumps(s["scope"], sort_keys=True), json.dumps(s["evidence"], sort_keys=True)))
    result = {"schema_version": "1", "check": f"{CHECK_NAME}@{CHECK_VERSION}", "release": release_dir.name,
              "verification_level_granted": "CROSS_REPRESENTATION_CONSISTENT (per table, only without WARN/ERROR; never content-verified)",
              "stats": {key: findings.stats[key] for key in sorted(findings.stats)},
              "signals_by_code": {code: n for code, n in sorted(findings.all_codes().items())},
              "signals": signals, "limitations": list(CROSSREP_LIMITATIONS), "completeness": "UNKNOWN"}
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "qa-crossrep.json").write_text(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return result
