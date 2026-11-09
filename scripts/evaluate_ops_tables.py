"""Evaluate the Operations Summary tables of a K1 release against the PDF text layer (PyMuPDF, an independent reader).

Usage (needs PyMuPDF, e.g. the explorations/ingestion/.venvs/docling interpreter):
    python scripts/evaluate_ops_tables.py --release after=PATH [--release before=PATH ...] --split dev
    python scripts/evaluate_ops_tables.py --release after=PATH --split heldout --final      (once, after the freeze)

Ground truth is read from the PDFs with PyMuPDF words (not with the pypdfium2 reader the rebuild rule uses). Report pages
are mapped to report dates, and the 27 dates are split into development and held-out (9 dates). ``--split dev`` never
extracts or reports anything on a held-out page. ``heldout``/``all`` need ``--final``, write a lock file with the SHA256
of the source files, and refuse to run a second time unless ``--new-round`` is given (the held-out dates are then no
longer independent, and the lock says so).

Metrics (per split and per release): table detection, header, row integrity, From/To/Elapsed/End MD/Code columns,
Non-Prod X precision and recall, description words (multiset of alphanumeric tokens, and exact text) and text spill in
Non-Prod. Each group gives its denominator and TP/FP/FN where they apply. The ground truth is the text layer of the same
PDF (PyMuPDF), so a result means agreement with the text layer, not with the printed page.

Round 2 (all 27 report dates are development data now; label every number "regression on data already seen"):
    python scripts/evaluate_ops_tables.py --release after=PATH --split all --final --new-round --truth both \
        --lock data/interim/ops-rebuild-r2/heldout-run.json --seed-lock data/interim/ops-rebuild/heldout-run.json \
        --freeze data/interim/ops-rebuild-r2/freeze.json --out data/interim/ops-rebuild-r2/R3-evaluation.json
The lock of Round 1 is copied to the Round 2 lock file and never modified; ``--new-round`` records the run as not independent.

Document-level scan (forced mode: every page of the PDFs is read by the recogniser and the reader, whatever the document
type; aggregate counts per family; no table is merged, so ``read_ok`` is not "validated"):
    python scripts/evaluate_ops_tables.py --documents [PDF ...] --out data/interim/ops-rebuild-r2/documents-scan.json
It needs pypdfium2 text layers and PYTHONPATH=src; the Round 1 code snapshot is used to compare page by page.
"""

from __future__ import annotations

import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT = ["2016-08-12", "2016-08-13", "2016-08-15", "2016-08-16", "2016-08-18", "2016-08-19", "2016-08-21",
               "2016-08-22", "2016-08-24", "2016-08-25", "2016-08-27", "2016-08-28", "2016-08-30", "2016-08-31",
               "2016-09-02", "2016-09-03", "2016-09-05", "2016-09-06"]
HELDOUT = ["2016-08-14", "2016-08-17", "2016-08-20", "2016-08-23", "2016-08-26", "2016-08-29", "2016-09-01",
           "2016-09-04", "2016-09-07"]
APPENDICES = ("27", "28", "30")
HEADER = ["From", "To", "Elapsed", "End MD(ft)", "Code", "Operations Description", "Non-Prod"]
TIME = re.compile(r"^\d{1,2}:\d\d$")
NON_PROD_LEFT = 536.0  # Ground truth only: the Non-Prod header word starts at x=536.8 on every report page.
LOCK = ROOT / "data/interim/ops-rebuild/heldout-run.json"
FREEZE = ROOT / "data/interim/ops-rebuild/dev-freeze.json"
SOURCE_GLOBS = ("src/**/*.py", "configs/**/*.json", "schemas/*.json", "scripts/evaluate_ops_tables.py",
                "scripts/regress_ops_tables.py", "scripts/export_k1_ops_rebuild.py", "docs/components/corpus-ingestion.md",
                "tests/test_ops_tables.py", "tests/ops_fixtures.py", "tests/test_ops_config.py",
                "tests/test_table_recognition.py", "tests/test_ops_real_pdfs.py")
ROUND_ONE_SNAPSHOT = ROOT / ".track-a-private/evidence/A-107-ops-tables/round1-code-snapshot/src/graph_builder/corpus/ops_tables.py"
SPLIT_LABEL = "regression on data already seen (non-independent)"
# Document families for the document-level scan, by file name keyword (first match wins); the file list is printed
# with the result, so nothing depends on a count written here.
FAMILIES = (("dailyreport", "daily_report"), ("eowr", "eowr"), ("casing", "casing_cement"), ("cement", "casing_cement"),
            ("survey", "survey"), ("permit", "permit"), ("plan", "plan"))
EXCLUDED_APPENDICES = re.compile(r"appx_(27|28|30)_")  # the three attachments the rule was developed on


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ---------------------------------------------------------------- ground truth (PyMuPDF words, census rules)

def page_lines(page, tolerance: float = 3.0) -> list[dict]:
    lines: list[dict] = []
    for word in sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        centre = (word[1] + word[3]) / 2
        if lines and abs(lines[-1]["y"] - centre) <= tolerance:
            lines[-1]["w"].append(word)
        else:
            lines.append({"y": centre, "w": [word]})
    for line in lines:
        line["w"].sort(key=lambda w: w[0])
    return lines


def truth_tables(page) -> list[list[dict]]:
    """Operations tables printed on a page: title line, header line, then rows starting with two time tokens."""
    lines, found, index = page_lines(page), [], 0
    while index < len(lines):
        words = [w[4] for w in lines[index]["w"]]
        title = any(w[4] == "Operations" and 255 < w[0] < 268 for w in lines[index]["w"]) and "Summary" in words
        if not (title and index + 1 < len(lines) and "From" in [w[4] for w in lines[index + 1]["w"]]):
            index += 1
            continue
        rows, cursor = [], index + 2
        while cursor < len(lines):
            line = lines[cursor]["w"]
            if len(line) >= 2 and TIME.match(line[0][4]) and TIME.match(line[1][4]) and line[0][0] < 75:
                rows.append(list(line))
            elif rows and 238 <= line[0][0] <= 252 and not any(w[4] == "Information" for w in line):
                if lines[cursor]["y"] - lines[cursor - 1]["y"] > 14:
                    break
                rows[-1].extend(line)
            else:
                break
            cursor += 1
        found.append({"y": lines[index]["y"], "rows": [truth_row(r) for r in rows]})
        index = cursor
    return found


def tokens(text: str) -> collections.Counter:
    return collections.Counter(re.findall(r"[a-z0-9]+", text.lower()))


def truth_row(words: list) -> dict:
    mark = any(w[4] == "X" and w[0] >= NON_PROD_LEFT - 5 for w in words)
    description = " ".join(w[4] for w in words if w[0] >= 240 and not (w[4] == "X" and w[0] >= NON_PROD_LEFT - 5))
    first = [w for w in words if w[3] - words[0][3] < 3 and abs(w[1] - words[0][1]) < 3]
    elapsed = next((w[4] for w in first if 115 <= w[0] < 150 and re.match(r"^\d+\.\d\d$", w[4])), "")
    end_md = next((w[4] for w in first if 150 <= w[0] < 200 and re.match(r"^-?[\d,.]+$", w[4])), "")
    code = next((w[4] for w in first if 195 <= w[0] < 240 and not re.match(r"^[\d,.:]+$", w[4])), "")
    return {"from": words[0][4], "to": words[1][4], "elapsed": elapsed, "end_md": end_md, "code": code, "x": mark,
            "description": description}


def header_zones_truth(words: list) -> dict | None:
    """Column zones from the printed header words of a line (PyMuPDF boxes), or None when the line is not the header.

    The ground truth must not depend on fixed coordinates, so the zones come from the page itself: the mark column is the
    span of its label (with a margin of a text height), the other columns start halfway between the labels. This is the
    same geometric model as the rule, read independently with another library; it checks the reading of the page and the
    row grouping, not the column model itself.
    """
    box = {}
    for word in words:
        box.setdefault(word[4].rstrip(")"), word)
    needed = ("From", "To", "Elapsed", "End", "MD(ft", "Code", "Non-Prod")
    if not all(name in box for name in needed):
        return None
    middle = lambda a, b: (box[a][2] + box[b][0]) / 2  # noqa: E731
    size = sorted(w[3] - w[1] for w in words)[len(words) // 2]
    return {"from_to": middle("From", "To"), "to_elapsed": middle("To", "Elapsed"), "elapsed_depth": middle("Elapsed", "End"),
            "depth_code": middle("MD(ft", "Code"), "code_limit": box["Code"][2] + (box["Code"][2] - box["Code"][0]) / 2,
            "mark_left": box["Non-Prod"][0] - 0.9 * size, "mark_right": box["Non-Prod"][2] + 0.9 * size, "em": size}


def truth_row_dynamic(words: list, zones: dict) -> dict:
    """One row of the ground truth with the zones of the page header (no fixed coordinate)."""
    in_mark = lambda w: w[4] == "X" and zones["mark_left"] <= (w[0] + w[2]) / 2 <= zones["mark_right"]  # noqa: E731
    first = [w for w in words if abs(w[1] - words[0][1]) < 0.35 * zones["em"]]
    centre = lambda w: (w[0] + w[2]) / 2  # noqa: E731
    elapsed = next((w[4] for w in first if zones["to_elapsed"] <= centre(w) < zones["elapsed_depth"]
                    and re.match(r"^\d+\.\d\d$", w[4])), "")
    end_md = next((w[4] for w in first if zones["elapsed_depth"] <= centre(w) < zones["depth_code"]
                   and re.match(r"^-?[\d,.]+$", w[4])), "")
    code = next((w[4] for w in first if zones["depth_code"] <= centre(w) <= zones["code_limit"]
                 and not re.match(r"^[\d,.:]+$", w[4])), "")
    description = " ".join(w[4] for w in words if centre(w) > zones["code_limit"] and not in_mark(w))
    return {"from": words[0][4], "to": words[1][4], "elapsed": elapsed, "end_md": end_md, "code": code,
            "x": any(in_mark(w) for w in words), "description": description}


def truth_tables_dynamic(page) -> list[dict]:
    """Operations tables of a page found from the header line (PyMuPDF), with relative geometry only.

    A header line holds the printed labels; the rows below start with two time tokens left of the From/To boundary; a
    wrapped description line starts at the description column and lies within 1.6 text heights of the previous line.
    """
    lines, found, index = page_lines(page), [], 0
    while index < len(lines):
        zones = header_zones_truth(lines[index]["w"])
        if zones is None:
            index += 1
            continue
        rows, cursor, left = [], index + 1, None
        while cursor < len(lines):
            line = lines[cursor]["w"]
            near = lines[cursor]["y"] - lines[cursor - 1]["y"] <= 1.6 * zones["em"]
            if len(line) >= 2 and TIME.match(line[0][4]) and TIME.match(line[1][4]) and line[0][2] < zones["from_to"] and near:
                rows.append(list(line))
                described = [w for w in line if (w[0] + w[2]) / 2 > zones["code_limit"] and w[4] != "X"]
                left = left if left is not None else (described[0][0] if described else None)
            elif rows and left is not None and near and abs(line[0][0] - left) <= 0.45 * zones["em"]:
                rows[-1].extend(line)
            else:
                break
            cursor += 1
        if rows:
            found.append({"y": lines[index]["y"], "rows": [truth_row_dynamic(r, zones) for r in rows]})
        index = max(cursor, index + 1)
    return found


def report_date(page) -> str | None:
    text = page.get_text()
    found = re.search(r"Report For\s+(\d{1,2}-[A-Za-z]{3}-\d{2})", text)
    if not found:
        words = [w[4] for w in sorted(page.get_text("words"), key=lambda w: (round(w[1]), w[0]))]
        for index in range(len(words) - 2):
            if words[index] == "Report" and words[index + 1] == "For" and re.match(r"^\d{1,2}-[A-Za-z]{3}-\d{2}$", words[index + 2]):
                found = re.search(r"(\d{1,2}-[A-Za-z]{3}-\d{2})", words[index + 2])
                break
    return datetime.strptime(found.group(1), "%d-%b-%y").strftime("%Y-%m-%d") if found else None


# ---------------------------------------------------------------- K1 side

def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def appendix_of(doc_id: str) -> str | None:
    found = re.search(r"appx-(\d+)", doc_id)
    return found.group(1) if found and found.group(1) in APPENDICES else None


def is_operations(table: dict) -> bool:
    head = " ".join(" ".join(row) for row in table["grid"][:2])
    return "Operations Description" in head or "Non-Prod" in head or (
        bool(table["grid"]) and all(c.strip() in ("Operations Summary", "") for c in table["grid"][0]) and "Operations Summary" in head)


def evaluate_table(truth: dict, table: dict | None) -> dict:
    """Compare one PDF table with one K1 table."""
    record = {"pdf_rows": len(truth["rows"]), "pdf_x": sum(r["x"] for r in truth["rows"])}
    if table is None:
        return dict(record, status="missing", table_id=None)
    grid = table["grid"]
    header_index = next((i for i, row in enumerate(grid) if "From" in row and any("Non-Prod" in c for c in row)), None)
    header = grid[header_index] if header_index is not None else []
    non_prod = header.index("Non-Prod") if "Non-Prod" in header else None
    body = grid[(header_index if header_index is not None else 0) + 1:]
    data = [r for r in body if len(r) >= 2 and TIME.match(r[0].strip()) and TIME.match(r[1].strip())]
    orphans = len(body) - len(data)
    used, matched = set(), []
    for row in truth["rows"]:
        hit = next((j for j, cells in enumerate(data) if j not in used and cells[0].strip() == row["from"] and cells[1].strip() == row["to"]), None)
        if hit is not None:
            used.add(hit)
        matched.append(hit)
    counts = collections.Counter()
    failures = []
    for row, hit in zip(truth["rows"], matched):
        if hit is None:
            continue
        cells = data[hit]
        if len(cells) >= 5 and [c.strip() for c in cells[:5]] == [row["from"], row["to"], row["elapsed"], row["end_md"], row["code"]]:
            counts["key_columns_ok"] += 1
        mark_columns = [c for c, v in enumerate(cells) if v.strip().upper() == "X"]
        if row["x"]:
            counts["x_ok" if non_prod is not None and non_prod in mark_columns else ("x_moved" if mark_columns else "x_lost")] += 1
        elif mark_columns:
            counts["x_false"] += 1
        if non_prod is not None and len(cells) > non_prod and cells[non_prod].strip() not in ("", "X"):
            counts["spill_rows"] += 1
        text = " ".join(dict.fromkeys(v for c, v in enumerate(cells) if c >= 5 and v.strip().upper() != "X" and v.strip()))
        if " ".join(text.split()) == " ".join(row["description"].split()):
            counts["description_exact"] += 1
        if tokens(text) == tokens(row["description"]):
            counts["description_ok"] += 1
        else:
            failures.append({"row": f"{row['from']}-{row['to']}", "pdf": row["description"][:80], "k1": text[:80]})
    lost = [i for i, hit in enumerate(matched) if hit is None]
    extra = [j for j in range(len(data)) if j not in used]
    merged = any("Operations Description" in c and "Non-Prod" in c for c in header)
    return dict(record, status="ok", table_id=table["table_id"], k1_rows=len(data), orphan_rows=orphans,
                lost_rows=len(lost), extra_rows=len(extra), num_cols=table["num_cols"], merged_header=merged,
                header_ok=header == HEADER and table["header_rows"] == 1, **{k: counts[k] for k in (
                    "key_columns_ok", "x_ok", "x_moved", "x_lost", "x_false", "spill_rows", "description_ok", "description_exact")},
                row_order_ok=[h for h in matched if h is not None] == sorted(h for h in matched if h is not None),
                description_failures=failures[:5])


def summarize(tables: list[dict], extras: int, pages_scanned: int | None = None) -> dict:
    """Aggregate per-table records into the evaluation metrics.

    Every group states its denominator and, where it applies, TP/FP/FN: tables (a PDF table with exactly one K1 table, a K1
    Operations table on a page without a PDF table, a PDF table without a K1 table), rows (matched by From/To, extra
    K1 rows, rows of the PDF not found) and marks (a mark in the right cell of the right row, a K1 mark that is not in the
    PDF or sits in a wrong cell, a PDF mark that is not in the right cell). The ground truth is the text layer of the same
    PDF read with PyMuPDF, so the metrics measure agreement with the text layer, not with the printed page.
    """
    present = [t for t in tables if t["status"] == "ok"]
    total = lambda key: sum(t.get(key, 0) for t in present)  # noqa: E731
    rows, marks = sum(t["pdf_rows"] for t in tables), sum(t["pdf_x"] for t in tables)
    lost_rows = total("lost_rows") + sum(t["pdf_rows"] for t in tables if t["status"] != "ok")
    true_marks, wrong_marks = total("x_ok"), total("x_moved") + total("x_false")
    perfect_rows = [t for t in present if t["lost_rows"] == 0 and t["extra_rows"] == 0 and t["orphan_rows"] == 0
                    and t["k1_rows"] == t["pdf_rows"] and t["row_order_ok"]]
    return {
        "pdf_tables": len(tables), "pdf_rows": rows, "pdf_x": marks,
        "table_detection": {"tables_with_k1_table": len(present), "missing": len(tables) - len(present),
                            "extra_k1_ops_tables_on_pages_without_pdf_table": extras,
                            "tp": len(present), "fp": extras, "fn": len(tables) - len(present),
                            "pages_scanned": pages_scanned},
        "header": {"exact_7_columns_1_row": sum(t["header_ok"] for t in present), "merged_header": sum(t["merged_header"] for t in present),
                   "tables": len(tables)},
        "rows": {"tables_with_all_rows_in_order": len(perfect_rows), "rows_matched": rows - lost_rows,
                 "rows_lost": lost_rows, "rows_extra": total("extra_rows"), "orphan_rows": total("orphan_rows"),
                 "pdf_rows": rows, "tp": rows - lost_rows, "fp": total("extra_rows") + total("orphan_rows"), "fn": lost_rows},
        "key_columns": {"rows_equal_on_from_to_elapsed_end_md_code": total("key_columns_ok"), "pdf_rows": rows},
        "non_prod_x": {"correct_in_non_prod_column": true_marks, "moved_to_other_column": total("x_moved"),
                       "lost": total("x_lost") + sum(t["pdf_x"] for t in tables if t["status"] != "ok"),
                       "false_marks": total("x_false"), "pdf_x": marks,
                       "tp": true_marks, "fp": wrong_marks, "fn": marks - true_marks,
                       "precision": round(true_marks / (true_marks + wrong_marks), 4) if true_marks + wrong_marks else None,
                       "recall": round(true_marks / marks, 4) if marks else None},
        "description": {"rows_with_equal_token_multiset": total("description_ok"), "pdf_rows": rows,
                        "rows_with_exact_text": total("description_exact")},
        "text_spill": {"rows_with_text_in_non_prod_column": total("spill_rows")},
    }


def k1_tables_by_page(release: Path) -> dict[tuple[str, int], list[dict]]:
    """K1 operations tables of the three daily-report attachments, keyed by (appendix, page), top to bottom."""
    tables = [t for t in read_jsonl(release / "tables.jsonl") if is_operations(t)]
    files = {f["file_id"]: f for f in read_jsonl(release / "files.jsonl")}
    by_page: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    for table in tables:
        appendix = appendix_of(files[table["file_id"]]["doc_id"])
        if appendix:
            by_page[(appendix, table["pages"][0])].append(table)
    for key in by_page:
        by_page[key].sort(key=lambda t: t["regions"][0]["bbox"][1])
    return by_page


def evaluate_release(release: Path, pages: dict) -> dict:
    """Evaluate every PDF operations table on the selected report dates; returns summary and per-table detail.

    ``pages`` holds only pages on the selected dates, so K1 tables on other pages are never looked at.
    """
    by_page = k1_tables_by_page(release)
    tables, extras = [], 0
    for (appendix, number), info in sorted(pages.items()):
        k1 = by_page.get((appendix, number), [])
        for index, truth in enumerate(info["tables"]):
            result = evaluate_table(truth, k1[index] if index < len(k1) else None)
            tables.append(dict(result, appendix=appendix, page=number, date=info["date"], index=index + 1))
        extras += max(0, len(k1) - len(info["tables"]))
    return {"summary": summarize(tables, extras, len(pages)),
            "by_appendix": {a: summarize([t for t in tables if t["appendix"] == a], 0, sum(1 for key in pages if key[0] == a))
                            for a in APPENDICES},
            "tables": tables}


def scan_pdfs(raw: Path, names: dict[str, str], wanted: set[str], truth=truth_tables) -> tuple[dict, dict]:
    """Report date of every page; ground-truth tables only for pages on a wanted date (never for other dates).

    ``truth`` is ``truth_tables`` (fixed coordinates of the RIMBase layout, the Round 1 ground truth) or
    ``truth_tables_dynamic`` (zones from the header of each page).
    """
    import fitz
    pages, census = {}, collections.Counter()
    for appendix, name in sorted(names.items()):
        with fitz.open(raw / name) as document:
            for number in range(1, len(document) + 1):
                page = document[number - 1]
                date = report_date(page)
                census[("dated" if date else "undated")] += 1
                if date not in wanted:
                    continue
                pages[(appendix, number)] = {"date": date, "tables": truth(page)}
    return pages, dict(census)


# ---------------------------------------------------------------- annotations (R2-10)

def normal_text(text: str) -> str:
    return " ".join(text.lower().split())


def annotation_coverage(release: Path, repairs: list[dict]) -> dict:
    """Does the annotation of a title line (for example "1 record not printed") appear in a K1 chunk of the same page?

    Counts only; the K1 package carries no such field and Round 2 does not change the chunks, so a low number is
    expected and is reported, not hidden. Annotations on the line above a title are hints and are counted apart.
    """
    file_of = {f["doc_id"]: f["file_id"] for f in read_jsonl(release / "files.jsonl")}
    texts: dict[tuple[str, int], list[str]] = collections.defaultdict(list)
    for chunk in read_jsonl(release / "chunks.jsonl"):
        for page in chunk["pages"]:
            texts[(chunk["file_id"], page)].append(normal_text(chunk["text"]))
    with_note = present = hints = hints_present = 0
    for record in repairs:
        page_texts = texts.get((file_of.get(record["doc_id"]), record["page"]), [])
        for side, counted in (("title", True), ("above", False)):
            notes = [a for a in record.get("annotations") or [] if (a["side"] == "above") == (side == "above")]
            if not notes:
                continue
            found = any(normal_text(a["text"]) in text for a in notes for text in page_texts)
            if counted:
                with_note, present = with_note + 1, present + found
            else:
                hints, hints_present = hints + 1, hints_present + found
    return {"records_with_a_title_line_annotation": with_note, "annotation_text_in_a_k1_chunk_of_the_same_page": present,
            "records_with_an_annotation_hint_above_the_title": hints, "hint_text_in_a_k1_chunk_of_the_same_page": hints_present}


# ---------------------------------------------------------------- document-level scan

def family_of(name: str) -> str:
    """Document family from the file name (keyword table ``FAMILIES``); anything else is ``other``."""
    lowered = name.lower()
    return next((family for keyword, family in FAMILIES if keyword in lowered), "other")


def documents_to_scan(raw: Path) -> tuple[list[Path], list[dict]]:
    """PDFs of ``raw`` that are not one of the development attachments or a copy of one, one file per distinct content.

    Returns the files to scan and, for every file left out, the reason, so the choice is visible in the output.
    """
    files = sorted(raw.glob("*.pdf"))
    digest = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    development = {digest[path] for path in files if EXCLUDED_APPENDICES.search(path.name)}
    keep, left_out, seen = [], [], {}
    for path in files:
        if digest[path] in development:
            left_out.append({"file": path.name, "reason": "development attachment or a copy of one"})
        elif digest[path] in seen:
            left_out.append({"file": path.name, "reason": f"same content as {seen[digest[path]]}"})
        else:
            seen[digest[path]] = path.name
            keep.append(path)
    return keep, left_out


def scan_page(layer: dict, text: str, rule: dict, round_one=None) -> dict:
    """What the recogniser and the reader say about one page, without the merge (the *forced* mode of the scan).

    ``gate_text`` is the cheap page gate of the production path (title words next to each other in the page text);
    ``gate_miss`` is true when the geometry finds a title that the gate would not have sent to the reader.
    ``results`` are ``(status, reason, read_ok)`` per accepted title; ``read_ok`` only means the rows were read and
    passed the self-checks, not that the table was merged and validated. ``round_one`` is the Round 1 module.
    """
    from graph_builder.corpus import ops_tables, table_recognition
    gate = bool(re.search(table_recognition.title_phrase_pattern(rule), text))
    mentions = table_recognition.mention_lines(layer, rule) if layer["rotation"] == 0 else []
    passed = [m for m in mentions if m["passed"]]
    candidate = gate or bool(mentions)
    results = ops_tables.read_page(layer, rule) if candidate else []
    old = round_one.read_page(layer) if (round_one and candidate) else []
    outcome = [(r["status"], r["reason"], r["status"] == "rebuilt") for r in results]
    return {"gate_text": gate, "mentions": len(mentions), "titles_passed": len(passed),
            "rejected_details": [m["detail"] for m in mentions if not m["passed"]], "results": outcome,
            "round_one": [(r["status"], r["reason"]) for r in old], "gate_miss": bool(passed) and not gate,
            "differs_from_round_one": round_one is not None and [(s, r) for s, r, _ in outcome] != [(r["status"], r["reason"]) for r in old],
            "annotations": sum(bool(r["annotations"]) for r in results)}


def scan_documents(paths: list[Path], rule: dict, round_one=None, gate_only: bool = False, details: bool = False) -> dict:
    """Scan every page of the given PDFs with the recogniser and the reader (forced mode, ``document_types`` ignored).

    Failure isolation: an unreadable page or document is counted and the scan goes on. Output is aggregate per family
    and per document (counts, no table content); ``details`` also lists the pages where Round 2 differs from Round 1.
    """
    import time
    import pypdfium2
    from graph_builder.corpus.report_context import pdf_page_texts
    from graph_builder.corpus.text_layer import source_page
    families: dict[str, dict] = {}
    documents = []
    for path in paths:
        family = families.setdefault(family_of(path.name), collections.Counter())
        started = time.perf_counter()
        info = {"file": path.name, "family": family_of(path.name), "pages": 0, "titles_passed": 0, "page_read_errors": 0}
        differing = []
        try:
            with pypdfium2.PdfDocument(path) as document:
                numbers = list(range(1, len(document) + 1))
            texts = pdf_page_texts(path, numbers)
            for page in numbers:
                family["pages_scanned"] += 1
                info["pages"] += 1
                gate = bool(re.search(r"\s+".join(map(re.escape, rule["schema"]["title_words"])), texts[page]))
                family["pages_with_gate_text"] += gate
                if gate_only and not gate:
                    continue
                try:
                    layer = source_page(path, page)
                    seen = scan_page(layer, texts[page], rule, round_one)
                except MemoryError:
                    raise
                except Exception as error:
                    family["page_read_errors"] += 1
                    info["page_read_errors"] += 1
                    family[f"page_error:{type(error).__name__}"] += 1
                    continue
                family["pages_with_a_mention_line"] += bool(seen["mentions"])
                family["pages_with_an_accepted_title"] += bool(seen["titles_passed"])
                family["gate_miss_pages"] += seen["gate_miss"]
                family["titles_accepted"] += seen["titles_passed"]
                info["titles_passed"] += seen["titles_passed"]
                for detail in seen["rejected_details"]:
                    family[f"rejected:{detail}"] += 1
                for status, reason, read_ok in seen["results"]:
                    family[f"result:{status}/{reason or '-'}/read_ok={read_ok}"] += 1
                family["pages_with_annotation"] += bool(seen["annotations"])
                if seen["differs_from_round_one"]:
                    family["pages_differing_from_round_one"] += 1
                    differing.append({"page": page, "round_one": seen["round_one"],
                                      "round_two": [(s, r) for s, r, _ in seen["results"]]})
        except MemoryError:
            raise
        except Exception as error:
            family["document_errors"] += 1
            info["document_error"] = type(error).__name__
        info["seconds"] = round(time.perf_counter() - started, 2)
        info["pages_differing_from_round_one"] = len(differing)
        if details:
            info["differences"] = differing
        documents.append(info)
    return {"mode": "forced (document_types ignored, no merge: read_ok is not 'validated')",
            "gate_only": gate_only, "families": {k: dict(sorted(v.items())) for k, v in sorted(families.items())},
            "documents": documents}


def load_round_one_module():
    """The Round 1 ops_tables.py from the read-only code snapshot, to compare page by page; None when it is missing."""
    import importlib.util
    if not ROUND_ONE_SNAPSHOT.is_file():
        return None
    spec = importlib.util.spec_from_file_location("graph_builder.corpus.ops_tables_r1", ROUND_ONE_SNAPSHOT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- lock for held-out

def source_digests() -> dict[str, str]:
    files = sorted({path for pattern in SOURCE_GLOBS for path in ROOT.glob(pattern)
                    if path.is_file() and "__pycache__" not in path.parts and ".venv" not in path.parts})
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in files}


def check_lock(new_round: bool) -> list[dict]:
    """Refuse a second held-out run (or a ``--new-round`` without a first one); returns the earlier rounds."""
    if LOCK.exists():
        if not new_round:
            raise SystemExit(f"{LOCK} exists: held-out was already evaluated. Use --new-round only after a new development "
                             "round; the held-out dates are then no longer independent.")
        return json.loads(LOCK.read_text(encoding="utf-8"))["rounds"]
    if new_round:
        raise SystemExit("--new-round needs an earlier held-out run (no lock file found)")
    return []


def write_lock(release: Path, new_round: bool) -> None:
    rounds = check_lock(new_round)
    digests = source_digests()
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "release": release.name,
             "release_sha256sums": sha256(release / "SHA256SUMS"), "sources_sha256": digests,
             "independent": not new_round}
    if FREEZE.exists():
        frozen = json.loads(FREEZE.read_text(encoding="utf-8"))["sources_sha256"]
        entry["changed_since_dev_freeze"] = sorted(name for name in set(frozen) | set(digests)
                                                   if frozen.get(name) != digests.get(name))
    else:
        entry["changed_since_dev_freeze"] = "no dev-freeze.json: code state at the end of development is not proven"
    if new_round:
        entry["note"] = "new development round: held-out no longer independent"
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(json.dumps({"rounds": rounds + [entry]}, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def take_lock(release: Path, new_round: bool) -> None:
    check_lock(new_round)
    write_lock(release, new_round)


def write_freeze() -> Path:
    """Snapshot of the source hashes at the end of development, to be compared with the held-out lock."""
    FREEZE.parent.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                  "sources_sha256": source_digests()}, indent=1, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")
    return FREEZE


def preflight(releases: dict[str, Path], raw: Path) -> dict[str, str]:
    """Everything the evaluation needs, checked before a held-out lock is taken: PyMuPDF, the release files and the PDFs.

    Returns the attachment name of each appendix. Any problem raises SystemExit and writes nothing.
    """
    try:
        import fitz  # noqa: F401
    except ImportError as failure:
        raise SystemExit(f"pre-flight: PyMuPDF (fitz) is not importable ({failure}); no lock was taken") from failure
    for label, path in releases.items():
        for name in ("files.jsonl", "tables.jsonl", "SHA256SUMS"):
            if not (path / name).is_file():
                raise SystemExit(f"pre-flight: release {label} has no {name} ({path}); no lock was taken")
    first = next(iter(releases.values()))
    names = {appendix_of(f["doc_id"]): f["original_name"] for f in read_jsonl(first / "files.jsonl") if appendix_of(f["doc_id"])}
    if set(names) != set(APPENDICES):
        raise SystemExit(f"pre-flight: attachments {sorted(names)} found, expected {list(APPENDICES)}; no lock was taken")
    for name in sorted(names.values()):
        if not (raw / name).is_file():
            raise SystemExit(f"pre-flight: PDF {name} not found in {raw}; no lock was taken")
    return names


def document_scan_command(args) -> int:
    """`--documents`: scan whole PDFs (forced mode), print aggregate counts per family and write the JSON."""
    from graph_builder.corpus.k1_config import load_k1_config
    rule = load_k1_config()["table_rules"]["operations_summary"]
    if args.documents:
        paths, left_out = list(args.documents), []
    else:
        paths, left_out = documents_to_scan(args.raw)
    scan = scan_documents(paths, rule, load_round_one_module(), args.gate_only, args.details)
    scan.update(files_left_out=left_out, files_scanned=[path.name for path in paths], data_label=SPLIT_LABEL if args.new_round else None)
    out = args.out or ROOT / "data/interim/ops-rebuild-r2/documents-scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(scan, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for family, counts in scan["families"].items():
        print(f"[scan] {family}: pages {counts.get('pages_scanned', 0)}, accepted titles {counts.get('titles_accepted', 0)}, "
              f"gate misses {counts.get('gate_miss_pages', 0)}, differing from Round 1 {counts.get('pages_differing_from_round_one', 0)}")
    print(f"written {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    global LOCK, FREEZE
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", action="append", metavar="LABEL=DIR")
    parser.add_argument("--write-freeze", action="store_true",
                        help="write data/interim/ops-rebuild/dev-freeze.json (source hashes) at the end of development and exit")
    parser.add_argument("--split", choices=("dev", "heldout", "all"), default="dev")
    parser.add_argument("--final", action="store_true", help="required for heldout/all")
    parser.add_argument("--new-round", action="store_true")
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--repairs", type=Path, help="table_repairs sidecar of the export (for the fallback reasons)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--lock", type=Path, help="held-out lock file (default data/interim/ops-rebuild/heldout-run.json, Round 1)")
    parser.add_argument("--freeze", type=Path, help="dev-freeze file (default data/interim/ops-rebuild/dev-freeze.json, Round 1)")
    parser.add_argument("--seed-lock", type=Path, help="with --new-round and a --lock that does not exist yet: start it as a "
                        "COPY of this lock (the original is never changed)")
    parser.add_argument("--truth", choices=("static", "dynamic", "both"), default="static",
                        help="ground truth: fixed RIMBase coordinates (Round 1), zones from each page header, or both")
    parser.add_argument("--documents", nargs="*", type=Path, metavar="PDF",
                        help="document-level scan of every page of these PDFs (default: all PDFs of --raw except the three "
                        "development attachments and copies), in forced mode; no release is evaluated")
    parser.add_argument("--gate-only", action="store_true", help="scan: read only pages whose text has the title (fast; no gate-miss count)")
    parser.add_argument("--details", action="store_true", help="scan: also list the pages that differ from Round 1")
    args = parser.parse_args(argv)
    LOCK, FREEZE = args.lock or LOCK, args.freeze or FREEZE
    if args.write_freeze:
        print(f"written {write_freeze()}")
        return 0
    if args.documents is not None:
        return document_scan_command(args)
    if not args.release:
        parser.error("--release is required")
    releases = {}
    for item in args.release:
        label, _, path = item.partition("=")
        if not label or not path:
            parser.error("--release needs LABEL=DIR")
        releases[label] = Path(path)
    if args.split != "dev":
        if not args.final:
            parser.error("--split heldout/all needs --final")
        if args.seed_lock and args.new_round and not LOCK.exists():
            if not args.seed_lock.is_file():
                raise SystemExit(f"--seed-lock {args.seed_lock} does not exist")
            LOCK.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.seed_lock, LOCK)  # a copy; the Round 1 lock is never modified
        check_lock(args.new_round)  # refuse early, but write nothing yet
    names = preflight(releases, args.raw)  # a held-out lock is only taken once nothing environmental can fail any more
    wanted = set(DEVELOPMENT) if args.split == "dev" else set(HELDOUT) if args.split == "heldout" else set(DEVELOPMENT + HELDOUT)
    truths = {"static": truth_tables, "dynamic": truth_tables_dynamic}
    modes = ("static", "dynamic") if args.truth == "both" else (args.truth,)
    scanned = {mode: scan_pdfs(args.raw, names, wanted, truths[mode]) for mode in modes}
    pages, census = scanned[modes[0]]
    result = {"split": args.split, "dates": sorted(wanted), "page_dates": census, "truth": modes[0], "releases": {}}
    if args.split != "dev":
        result["independent"] = not args.new_round
        if args.new_round:
            result["note"] = "new development round: held-out no longer independent"
    if args.new_round or args.split == "dev":
        result["data_label"] = SPLIT_LABEL if args.new_round else "development data"
    for label, path in releases.items():
        evaluation = evaluate_release(path, pages)
        evaluation["release"] = path.name
        result["releases"][label] = evaluation
    if len(modes) == 2:  # the same releases against the second ground truth, to compare the two readings of the PDFs
        result["releases_dynamic_truth"] = {label: dict(evaluate_release(path, scanned["dynamic"][0]), release=path.name)
                                            for label, path in releases.items()}
    if args.repairs:  # only the records of pages on the selected dates
        records = [r for r in json.loads(args.repairs.read_text(encoding="utf-8"))
                   if (appendix_of(r["doc_id"]), r["page"]) in pages]
        result["annotation_coverage"] = {label: annotation_coverage(path, records) for label, path in releases.items()}
        result["table_repairs"] = {
            "records": records,
            "by_status": dict(collections.Counter(f"{r['status']}:{r['reason'] or '-'}" for r in records)),
            "by_action": dict(collections.Counter(r["action"] for r in records))}
    out = args.out or ROOT / ("data/interim/ops-rebuild/dev-results.json" if args.split == "dev"
                              else "data/interim/ops-rebuild/heldout-results.json")
    # The results go to a temporary file first, then the lock, then the rename: a failure to write the results leaves no
    # lock behind, and a failure to write the lock leaves no results file (the temporary file is removed).
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(out.name + ".tmp")
    try:
        temporary.write_text(json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if args.split != "dev":  # everything is computed and nothing was shown: the lock and the results appear together
            write_lock(next(iter(releases.values())), args.new_round)
        temporary.replace(out)
    finally:
        temporary.unlink(missing_ok=True)
    for label, evaluation in result["releases"].items():
        s = evaluation["summary"]
        print(f"[{args.split}] {label}: tables {s['table_detection']['tables_with_k1_table']}/{s['pdf_tables']}, "
              f"header ok {s['header']['exact_7_columns_1_row']}/{s['pdf_tables']}, rows lost {s['rows']['rows_lost']}/{s['pdf_rows']}, "
              f"X recall {s['non_prod_x']['recall']}, X precision {s['non_prod_x']['precision']}, "
              f"description ok {s['description']['rows_with_equal_token_multiset']}/{s['pdf_rows']}, "
              f"spill rows {s['text_spill']['rows_with_text_in_non_prod_column']}")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
