"""Compare exact mud-property rows and verify panel cell rectangles against the original PDFs."""
from __future__ import annotations

import argparse
from collections import defaultdict
from operator import itemgetter
from itertools import groupby
import json
from pathlib import Path
import re
import unicodedata

import pymupdf

from graph_builder.corpus.qa.fidelity import FidelityState, load_config
from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl


REFERENCE = Path(__file__).resolve().parents[1] / "configs/benchmarks/track_a_mud_properties.json"
PREFIX = "textlayer:mud_properties:"


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text).casefold())


def exact_rows(release, reference):
    files = {row["doc_id"]: row["sha256"] for row in read_jsonl(release / "files.jsonl")}
    panels = defaultdict(list)
    for table in read_jsonl(release / "tables.jsonl"):
        if len(table["pages"]) == 1 and any("mudproperties" in normalize(cell) for row in table["grid"] for cell in row):
            panels[table["doc_id"], table["pages"][0]].append(table)
    results = {}
    for doc in reference:
        doc_id = doc["doc_id"]
        if files.get(doc_id) != doc["sha256"]:
            raise ValueError(f"Unexpected source PDF for {doc_id}")
        expected, failures = 0, []
        for page in doc["pages"]:
            number = page["page"]
            rows = set()
            for table in panels[doc_id, number]:
                unit = {(cell["r"], cell["c"]) for cell in table["cells"] if cell["row_span"] == cell["col_span"] == 1}
                for r, row in enumerate(table["grid"]):
                    values = tuple(map(normalize, row))
                    for length in (2, 3):
                        for c in range(len(row) - length + 1):
                            if all(not row[j] or (r, j) in unit for j in range(c, c + length)):
                                rows.add(values[c:c + length])
            expected += len(page["rows"])
            failures.extend({"page": number, "row": row} for row in page["rows"] if tuple(map(normalize, row)) not in rows)
        results[doc_id] = {"expected": expected, "matched": expected - len(failures), "missing": failures}
    return results


def verify_rectangles(corpus, release, evidence):
    summary = json.loads(evidence.with_name("cell_evidence_summary.json").read_text(encoding="utf-8"))
    if file_sha256(release / "SHA256SUMS") != summary["release_checksums_sha256"]:
        raise ValueError("Cell evidence is from another release")
    source = FidelityState(release, corpus, load_config())
    panels = {table["table_id"]: table for table in read_jsonl(release / "tables.jsonl")
              if any(part["source_ref"].startswith(PREFIX) for part in table["parts"])}
    cells = {(tid, cell["r"], cell["c"]): cell["text"] for tid, table in panels.items() for cell in table["cells"]}
    grouped = defaultdict(list)
    for row in read_jsonl(evidence):
        if row["table_id"] in panels:
            grouped[row["file_id"]].append(row)
    failures = []
    seen = set()
    for file_id, rows in grouped.items():
        pdf_path, _ = source.locate_pdf(source.files[file_id])
        if pdf_path is None:
            raise ValueError(f"Missing source PDF for {file_id}")
        with pymupdf.open(pdf_path) as pdf:
            page_number = itemgetter("page")
            for number, page_rows in groupby(sorted(rows, key=page_number), key=page_number):
                page = pdf[number - 1]
                words = [((x0 + x1) / 2, (y0 + y1) / 2, text) for x0, y0, x1, y1, text, *_ in page.get_text("words", sort=True)]
                for row in page_rows:
                    key = row["table_id"], row["r"], row["c"]
                    if key in seen or cells.get(key) != row["text"] or panels[key[0]]["pages"] != [number]:
                        raise ValueError(f"Cell evidence disagrees with the release: {key}")
                    seen.add(key)
                    actual = ""
                    if row["status"] == "source_supported" and row["bbox"]:
                        rect = pymupdf.Rect(row["bbox"]) * page.derotation_matrix
                        actual = " ".join(text for x, y, text in words
                                          if rect.x0 - 0.5 <= x <= rect.x1 + 0.5 and rect.y0 <= y <= rect.y1)
                    if normalize(actual) != normalize(row["text"]):
                        failures.append({"cell": key, "expected": row["text"], "observed": actual, "status": row["status"]})
    failures.extend({"cell": key, "status": "missing"} for key in sorted(cells.keys() - seen))
    return {"panels": len(panels), "cells": len(cells), "verified": len(cells) - len(failures), "failures": failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("corpus", "before", "after", "evidence", "out"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text(encoding="utf-8"))["documents"]
    result = {"before": exact_rows(args.before, reference), "after": exact_rows(args.after, reference),
              "rectangles": verify_rectangles(args.corpus, args.after, args.evidence)}
    atomic_write_json(args.out, result)
    print({key: (sum(row["matched"] for row in result[key].values()), sum(row["expected"] for row in result[key].values()))
           for key in ("before", "after")})
    print({key: result["rectangles"][key] for key in ("panels", "cells", "verified")})
    return 0 if all(not row["missing"] for row in result["after"].values()) and not result["rectangles"]["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
