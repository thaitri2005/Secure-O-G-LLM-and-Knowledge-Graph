"""Check the exported hourly cell rectangles against the pinned PDF with PyMuPDF."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf

from graph_builder.corpus.qa.cell_evidence import FRAME
from graph_builder.corpus.qa.form_overlap import valid_box
from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl


def chars(page):
    tree = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)
    boxes = []
    for block in tree["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for char in span["chars"]:
                    left, top, right, bottom = char["bbox"]
                    boxes.append(((left + right) / 2, (top + bottom) / 2, char["c"]))
    return sorted(boxes)


def check(pdf, tables, evidence, reference):
    failures, proven = [], 0
    for key, rows in reference["rows"].items():
        number = int(key)
        candidates = [t for t in tables if t["pages"] == [number] and t["header_rows"] == 1
                      and t["grid"][0] == reference["header"] and [row[:2] for row in t["grid"][1:]] == rows]
        if len(candidates) != 1:
            failures.append({"page": number, "reason": "no_unique_exact_hourly_table"})
            continue
        table = candidates[0]
        pdf_chars = chars(pdf[number - 1])
        previous_y = [0, 0]
        for r, pair in enumerate(rows, 1):
            pair_boxes = []
            for c, value in enumerate(pair):
                where = {"page": number, "table_id": table["table_id"], "r": r, "c": c}
                cell = evidence.get((table["table_id"], r, c))
                if (cell is None or cell["status"] != "source_supported" or cell["bbox_frame"] != FRAME
                        or cell["page"] != number or not valid_box(cell["bbox"])):
                    failures.append(dict(where, reason="cell_geometry_missing"))
                    continue
                left, top, right, bottom = cell["bbox"]
                observed = "".join(char for x, y, char in pdf_chars if left - 0.2 <= x <= right + 0.2 and top <= y <= bottom).strip()
                if observed != value or cell["text"] != value or top <= previous_y[c]:
                    failures.append(dict(where, reason="wrong_text_or_row_geometry", expected=value, observed=observed))
                    continue
                previous_y[c] = top
                pair_boxes.append(cell["bbox"])
            if len(pair_boxes) == 2:
                first, second = pair_boxes
                if first[2] >= second[0] or min(first[3], second[3]) <= max(first[1], second[1]):
                    failures.append({"page": number, "table_id": table["table_id"], "r": r,
                                     "reason": "time_columns_or_baselines_not_separate"})
                    continue
            proven += len(pair_boxes)
    return {"pages": len(reference["rows"]), "cells_expected": sum(len(rows) * 2 for rows in reference["rows"].values()),
            "cells_proven": proven, "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("pdf", "release", "evidence", "reference", "out"):
        parser.add_argument(f"--{argument}", type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    files = [row for row in read_jsonl(args.release / "files.jsonl") if row["doc_id"] == reference["doc_id"]]
    if len(files) != 1 or files[0]["sha256"] != reference["sha256"] or file_sha256(args.pdf) != reference["sha256"]:
        raise ValueError("PDF, release and reference do not share the same source digest")
    tables = [table for table in read_jsonl(args.release / "tables.jsonl") if table["doc_id"] == reference["doc_id"]]
    evidence = {(row["table_id"], row["r"], row["c"]): row for row in read_jsonl(args.evidence)
                if row["doc_id"] == reference["doc_id"] and row["status"] == "source_supported"}
    with pymupdf.open(args.pdf) as pdf:
        result = check(pdf, tables, evidence, reference)
    atomic_write_json(args.out, result)
    print(f"{result['cells_proven']}/{result['cells_expected']} time-cell rectangles checked on {result['pages']} pages")
    return int(bool(result["failures"]))


if __name__ == "__main__":
    raise SystemExit(main())
