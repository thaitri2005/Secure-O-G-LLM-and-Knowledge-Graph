"""Compare orientation and table joining against a reviewed table on a SHA-pinned PDF."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from time import perf_counter

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.config import load_config, validate_config
from graph_builder.corpus.k1_config import load_k1_config
from graph_builder.corpus.k1_export import export_k1
from graph_builder.corpus.orientation import rotate_bbox
from graph_builder.corpus.process import run as process
from graph_builder.corpus.qa.cli import run as run_qa
from graph_builder.corpus.store import atomic_write_json, file_sha256, read_jsonl
from graph_builder.ingestion.scoring import bbox_iou, cell_grid, whitespace


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/corpus/default.json"
ANNOTATIONS = ROOT / "explorations/ingestion/annotations/held-out/continued-tables/continued_tables.json"
JOIN = ROOT / "configs/corpus/table_join.json"
SUPPORTED_CELL = {"source_supported", "text_matches_region"}


def displayed_box(box, page):
    attempts = page["rotation_attempts"]
    if not attempts:
        return box
    rotation = attempts[-1]
    angle = (rotation["source_rotation"] - rotation["working_rotation"]) % 360
    return rotate_bbox(box, page["width"], page["height"], angle)


def split_final_row(case, target_rows, body, evidence):
    last_row = target_rows[-1]
    last_keys = {key for key, row in body.items() if row == last_row}
    owner = len(target_rows)
    expected_pages = sorted(part["page"] for part in case["parts"] if part["first_row"] <= owner <= part["last_row"])
    columns = defaultdict(list)
    if len(last_keys) == 1:
        for row in evidence:
            if (row["table_id"], row["r"]) in last_keys and row["col_span"] == 1 and row.get("observed_text"):
                columns[row["c"]].append((row["page"], row["observed_text"]))
    proven = []
    for column, fragments in columns.items():
        fragments.sort()
        if ([page for page, _ in fragments] == expected_pages
                and whitespace(" ".join(text for _, text in fragments)) == last_row[column]):
            proven.append(column)
    return {"exact_occurrences": len(last_keys), "expected_source_pages": expected_pages,
            "supported_pages_by_column": {c: sorted({p for p, _ in items}) for c, items in columns.items()},
            "proven_split_columns": sorted(proven), "pass": len(expected_pages) > 1 and bool(proven)}


def score(release, evidence, case, expected):
    pages = {page["page"]: page for page in read_jsonl(release / "pages.jsonl")}
    tables_by_page = {page: [] for page in case["pages"]}
    for table in read_jsonl(release / "tables.jsonl"):
        for part in table["parts"]:
            if part["page"] in tables_by_page:
                tables_by_page[part["page"]].append((table, part))

    target_headers = expected[:case["header_rows"]]
    target_rows = expected[case["header_rows"]:]
    expected_counts = Counter(target_rows)
    matches, rows, grids, matching_headers = [], {}, {}, 0
    for target in case["parts"]:
        number = target["page"]
        options = [(bbox_iou(target["bbox"], displayed_box(part["bbox"], pages[number])), table, part)
                   for table, part in tables_by_page[number] if part.get("bbox")]
        overlap, table, part = max(options, key=lambda option: option[0], default=(0, None, None))
        if not overlap:
            matches.append({"page": number, "bbox_iou": 0, "table_id": None})
            continue
        table_id = table["table_id"]
        matches.append({"page": number, "bbox_iou": round(overlap, 4), "table_id": table_id,
                        "row_start": part["row_start"], "row_end": part["row_end"]})
        if table_id not in grids:
            grids[table_id] = cell_grid(table)
        for index in range(part["row_start"], part["row_end"]):
            key = table_id, index
            if key in rows:
                continue
            row = tuple(map(whitespace, grids[table_id][index]))
            rows[key] = row
            matching_headers += row in target_headers

    body = {key: row for key, row in rows.items() if row not in target_headers}
    seen = Counter(body.values())
    evidence_rows = [row for row in read_jsonl(evidence) if row["status"] in SUPPORTED_CELL
                     and row["bbox"] and row["page"] in tables_by_page]
    final_row = (split_final_row(case, target_rows, body, evidence_rows)
                 if any(part.get("continues_row_from_previous_page") for part in case["parts"]) else None)
    owners = {part["table_id"] for part in matches}
    return {"expected_body_rows": len(target_rows), "output_body_rows": len(body),
            "exact_body_rows": sum((seen & expected_counts).values()),
            "exact_order": list(body.values()) == target_rows,
            "output_matching_header_rows": matching_headers,
            "one_logical_table": len(owners) == 1 and None not in owners,
            "parts": matches, "rotation_attempts": {p: pages[p]["rotation_attempts"] for p in case["pages"]},
            "source_supported_cells": sum(row["table_id"] in owners for row in evidence_rows), "split_final_row": final_row}


def evaluate(args, case, expected):
    if file_sha256(args.pdf) != case["source_sha256"]:
        raise ValueError(f"PDF SHA-256 does not match the reviewed source for {case['id']}")
    args.out.mkdir(parents=True, exist_ok=True)
    settings = load_config(args.config or DEFAULT_CONFIG)
    if args.config is None:
        settings["ocr"].update(engine="rapidocr", languages=["en"])
    settings["analysis"].pop("page_orientation", None)
    join = json.loads(JOIN.read_text(encoding="utf-8"))
    if args.activity_detail:
        join["continuity"]["split_activity_rows"] = True
    report = {"case": case["id"], "source_sha256": case["source_sha256"], "ocr": settings["ocr"],
              "orientation_mode": args.orientation_mode, "activity_detail": args.activity_detail, "variants": {}}
    for rotated in (False, True):
        mode = "normalize" if rotated else "original"
        if rotated:
            settings["analysis"]["page_orientation"] = {"mode": args.orientation_mode}
        config = validate_config(settings)
        corpus = Corpus.create(args.out / mode, config)
        state, reason = corpus.add_file(args.pdf, doc_id=case["doc_id"])
        if state != "added":
            raise ValueError(f"Cannot register reviewed source: {reason}")

        start = perf_counter()
        counts = process(corpus, args.models)
        processing = perf_counter() - start
        if counts["failed"] or counts["not_started"]:
            raise RuntimeError(f"{mode}: PDF processing failed: {counts}")
        for joined in (False, True):
            name = mode + ("-join" if joined else "-separate")
            k1 = load_k1_config()
            if joined:
                k1["table_join"] = join
            start = perf_counter()
            exported = export_k1(corpus, name, args.models, k1)
            release = Path(exported["export"])
            extraction = perf_counter() - start
            start = perf_counter()
            qa = run_qa(corpus.root, release, args.out / ("qa-" + name), None, None,
                        crossrep=True, cell_evidence=True, orientation=rotated)
            validation = perf_counter() - start
            variant = {"release": str(release), "validator": qa["validator"],
                       "seconds": {"shared_process": round(processing, 3), "k1": round(extraction, 3), "qa": round(validation, 3)}}
            if qa["validator"] == "pass":
                variant.update(score(release, Path(qa["cell_evidence"]["path"]), case, expected))
            if joined:
                decisions = exported["table_join"].get(case["doc_id"], {}).get("decisions", [])
                variant["join_decisions"] = [decision for decision in decisions
                                             if set(decision["evidence"]["pages"]) <= set(case["pages"])]
            report["variants"][name] = variant
            atomic_write_json(args.out / "results.json", report)
            print(name, json.dumps({key: variant[key] for key in ("validator", "exact_body_rows", "one_logical_table", "split_final_row", "seconds")
                                    if key in variant}), flush=True)
    return 0 if all(variant["validator"] == "pass" for variant in report["variants"].values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="fresh output directory for the two work corpora")
    parser.add_argument("--case", default="forge68_activity_detail")
    parser.add_argument("--annotations", type=Path, default=ANNOTATIONS)
    parser.add_argument("--config", type=Path, help="corpus configuration (defaults to standard extraction with English RapidOCR)")
    parser.add_argument("--models", type=Path, default=ROOT / "data/interim/ocr_models")
    parser.add_argument("--orientation-mode", choices=("normalize", "verify"), default="normalize")
    parser.add_argument("--activity-detail", action="store_true", help="rebuild verified ruled activity tables when joining is enabled")
    args = parser.parse_args()
    cases = json.loads(args.annotations.read_text(encoding="utf-8"))
    case = next((entry for entry in cases if entry["id"] == args.case and entry["status"] == "corrected"), None)
    if case is None:
        parser.error(f"no corrected case named {args.case}")
    with (args.annotations.parent / Path(case["csv"]).name).open(encoding="utf-8-sig", newline="") as stream:
        expected = [tuple(map(whitespace, row)) for row in csv.reader(stream)]
    if not expected or not expected[0] or any(len(row) != len(expected[0]) for row in expected):
        parser.error("the annotated grid must be rectangular and nonempty")
    if len(expected) <= case["header_rows"]:
        parser.error("the annotated grid must contain body rows")
    return evaluate(args, case, expected)


if __name__ == "__main__":
    raise SystemExit(main())
