"""Score K1 scan grids against visual source annotations without invoking extraction or OCR."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import re
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "configs/benchmarks/track_a_scan_cells_e53.json"
PRINTED_MARKS = str.maketrans("‘’′“”″−–—", "'''\"\"\"---")
MEASUREMENT = re.compile(r"([+-]?\d+(?:[.,]\d+)?)\s*(ft/min|ft|in|m|mm|cm|psi|kpa|ppg|°[fc]|['\"])")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_rows(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def normalize(text):
    if text is None:
        return ""
    value = " ".join(unicodedata.normalize("NFC", text).translate(PRINTED_MARKS).casefold().split())
    if measurement := MEASUREMENT.fullmatch(value):
        return " ".join(measurement.groups())
    return value


def row_key(row, columns):
    key = []
    for column in columns:
        value = normalize(row[column]) if column < len(row) else ""
        measurement = MEASUREMENT.fullmatch(value)
        key.append(measurement[1] if measurement else value)
    return tuple(key) if all(key) else ()


def wrong_cell(expected, actual, grid, row_index, column):
    exact = MEASUREMENT.fullmatch(expected)
    found = MEASUREMENT.fullmatch(actual)
    if exact and (actual == exact[1] or (found and exact[1] == found[1] and exact[2] != found[2])):
        return "wrong_unit"
    other_columns = {c for c, value in enumerate(grid[row_index]) if c != column and value == actual}
    other_rows = {r for r, row in enumerate(grid) if r != row_index and row[column] == actual}
    if other_columns and not other_rows:
        return "wrong_column"
    if other_rows and not other_columns:
        return "wrong_row"
    return "wrong_value"


def score_grid(case, grid, header_rows):
    """Align unique printed keys, then score the original column indices and physical row order."""
    rows = case["rows"]
    columns = case["key_columns"]
    width = len(case["column_names"])
    annotated = [[None if cell is None else normalize(cell) for cell in row] for row in rows]
    if any(len(row) != width for row in rows) or not rows:
        raise ValueError(f"Invalid gold grid for {case['id']}")
    keys = [row_key(row, columns) for row in annotated]
    if () in keys or len(keys) != len(set(keys)):
        raise ValueError(f"Gold row keys must be nonempty and unique for {case['id']}")
    body = [row for row in grid[header_rows:] if any(map(normalize, row))]
    expected_by_key = dict(zip(keys, range(len(rows)), strict=True))
    observed = {}
    known_order = []
    counts = Counter()
    issues = []

    def issue(kind, **details):
        counts[kind] += 1
        issues.append({"kind": kind, **details})

    body_scope = {c for c in range(width) if any(row[c] is not None for row in rows)}
    for number, row in enumerate(body, 1):
        key = row_key(row, columns)
        if key in expected_by_key and key not in observed:
            observed[key] = row
            known_order.append(key)
        else:
            issue("duplicate_row" if key in observed else "unexpected_row", output_row=number, actual=row)
            counts["unexpected_cells"] += sum(bool(normalize(value)) for c, value in enumerate(row)
                                              if c in body_scope or c >= width)

    for r, (key, expected) in enumerate(zip(keys, annotated, strict=True), 1):
        row = observed.get(key)
        if row is None:
            issue("missing_row", gold_row=r, row_key=key)
        row_exact = row is not None
        for c, (value, raw) in enumerate(zip_longest(expected, row or [], fillvalue=None), 1):
            actual = normalize(raw)
            if c <= width and value is None:
                continue  # Explicitly unscored source cell.
            details = dict(gold_row=r, column=c, expected=rows[r - 1][c - 1] if c <= width else None, actual=raw)
            if value:
                counts["gold_cells"] += 1
                if value == actual:
                    counts["correct_cells"] += 1
                else:
                    row_exact = False
                    issue(wrong_cell(value, actual, annotated, r - 1, c - 1) if actual else "missing_cell", **details)
            elif actual:
                issue("unexpected_cells", **details)
                row_exact = False
            elif c <= width and row is not None:
                counts["correct_blank_cells"] += 1
        counts["exact_rows"] += row_exact

    expected_header = case["header"]
    if expected_header is not None:
        actual_header = grid[0] if header_rows and grid else []
        for c, (expected, actual) in enumerate(zip_longest(expected_header, actual_header), 1):
            if normalize(expected) == normalize(actual):
                counts["correct_header_cells"] += bool(expected)
            else:
                issue("header_mismatch", column=c, expected=expected, actual=actual)
        if grid and header_rows != 1:
            issue("header_shape_mismatch", expected=1, actual=header_rows)
    order_ok = known_order == [key for key in keys if key in observed]
    if not order_ok:
        issue("row_order_changed", expected=keys, actual=known_order)
    return {"counts": counts, "expected_rows": len(rows), "expected_header_cells": len(expected_header or []),
            "ordered_rows": order_ok, "issues": issues}


def intersects_region(region, gold):
    width = min(region[2], gold[2]) - max(region[0], gold[0])
    height = min(region[3], gold[3]) - max(region[1], gold[1])
    area = max(0, width) * max(0, height)
    region_area = (region[2] - region[0]) * (region[3] - region[1])
    gold_area = (gold[2] - gold[0]) * (gold[3] - gold[1])
    return area >= 0.20 * gold_area and area >= 0.50 * region_area


def score_case(case, tables, page):
    """Choose a grid by physical location before inspecting its text."""
    candidates = [table for table in tables if table["pages"] == [page]
                  and any(intersects_region(region["bbox"], case["bbox"]) for region in table["regions"]
                          if region["page"] == page)]
    grid = candidates[0]["grid"] if len(candidates) == 1 else []
    header_rows = candidates[0]["header_rows"] if grid else 0
    result = score_grid(case, grid, header_rows)
    counts = result["counts"]
    result.update(candidate_ids=[table["table_id"] for table in candidates],
                  table_status="matched_region" if grid else "ambiguous_region" if candidates else "table_missing",
                  actual_grid=grid,
                  exact_pass=bool(grid) and counts["exact_rows"] == result["expected_rows"]
                  and not result["issues"])
    return result


def verify_input(original, input_pdf, source, pages):
    """Check the original page pixels or the recorded lossless raster window against the evaluated PDF."""
    import pymupdf

    if digest(original) != source["sha256"]:
        raise ValueError(f"Source hash differs for {original}")
    if original == input_pdf:
        with pymupdf.open(original) as pdf:
            if pages != list(range(1, len(pdf) + 1)):
                raise ValueError(f"Incorrect page mapping for full source {original}")
        return
    with pymupdf.open(input_pdf) as supplied:
        if len(supplied) != len(pages):
            raise ValueError(f"Input page mapping differs for {input_pdf}")
        if spec := source.get("raster_window"):
            import io
            from PIL import Image

            if pages != [1] or supplied[0].rotation:
                raise ValueError("Raster snapshot must use the original orientation")
            page = supplied[0]
            images = page.get_images()
            if len(images) != 1 or page.get_text().strip() or page.get_image_rects(images[0][0]) != [page.rect]:
                raise ValueError("Raster wrapper must contain one full-page image")
            with Image.open(original) as image, Image.open(io.BytesIO(supplied.extract_image(images[0][0])["image"])) as actual:
                expected = image.crop(tuple(spec["pixels"]))
                if expected.size != actual.size or expected.convert("L").tobytes() != actual.convert("L").tobytes():
                    raise ValueError(f"Raster pixels differ for {input_pdf}")
                width, height = (pixels * 72 / spec["dpi"] for pixels in expected.size)
                if abs(page.rect.width - width) > .02 or abs(page.rect.height - height) > .02:
                    raise ValueError(f"Raster page scale differs for {input_pdf}")
        else:
            with pymupdf.open(original) as pdf:
                for target, number in zip(supplied, pages, strict=True):
                    reference = pdf[number - 1]
                    if (reference.rect != target.rect or reference.rotation != target.rotation
                            or reference.get_pixmap(dpi=96).samples != target.get_pixmap(dpi=96).samples):
                        raise ValueError(f"Source PDF page {number} differs in {input_pdf}")


def read_release(release, input_pdf, pages):
    checksums = {filename: checksum for checksum, filename in
                 (line.split("  ", 1) for line in (release / "SHA256SUMS").read_text().splitlines())}
    for name in ("files.jsonl", "tables.jsonl", "pages.jsonl"):
        if checksums.get(name) != digest(release / name):
            raise ValueError(f"Release checksum differs for {release / name}")
    input_sha = digest(input_pdf)
    matching = [row for row in json_rows(release / "files.jsonl") if row["sha256"] == input_sha]
    if len(matching) != 1 or matching[0]["page_count"] != len(pages):
        raise ValueError(f"Release does not identify the evaluated input {input_pdf}")
    file_id = matching[0]["file_id"]
    tables = [row for row in json_rows(release / "tables.jsonl") if row["file_id"] == file_id]
    modes = {row["page"]: row["mode"] for row in json_rows(release / "pages.jsonl") if row["file_id"] == file_id}
    return tables, modes


def summaries(results):
    groups = defaultdict(Counter)
    for row in results:
        aggregate = groups[row["split"]]
        aggregate.update(row["counts"])
        aggregate["tables"] += 1
        aggregate["tables_missing"] += row["table_status"] == "table_missing"
        aggregate["tables_ambiguous"] += row["table_status"] == "ambiguous_region"
        aggregate["gold_rows"] += row["expected_rows"]
        aggregate["gold_header_cells"] += row["expected_header_cells"]
    for aggregate in groups.values():
        errors = sum(aggregate[name] for name in ("wrong_unit", "wrong_column", "wrong_row", "wrong_value"))
        predictions = aggregate["correct_cells"] + errors + aggregate["unexpected_cells"]
        aggregate["precision"] = aggregate["correct_cells"] / predictions if predictions else None
        aggregate["recall"] = aggregate["correct_cells"] / aggregate["gold_cells"]
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=GOLD)
    parser.add_argument("--pdf-dir", type=Path, required=True, help="Directory containing pinned original PDFs and raster")
    parser.add_argument("--runs", type=Path, required=True, help="JSON mapping source IDs to release, input PDF and source page order")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--split", choices=("development", "holdout"), help="Read only this split")
    parser.add_argument("--require-exact", action="store_true", help="Exit with status 1 if any annotated grid fails")
    args = parser.parse_args()
    spec = json.loads(args.gold.read_text(encoding="utf-8"))
    runs = json.loads(args.runs.read_text(encoding="utf-8"))
    results = []
    inputs = {}
    for source_id, source in spec["sources"].items():
        if args.split and source["split"] != args.split:
            continue
        run = runs[source_id]
        original = (args.pdf_dir / source["file"]).resolve()
        input_pdf = Path(run["pdf"]).resolve()
        release = Path(run["release"])
        verify_input(original, input_pdf, source, run["pages"])
        tables, modes = read_release(release, input_pdf, run["pages"])
        inputs[source_id] = {"release": str(release), "timings": run.get("timings")}
        for case in (row for row in spec["cases"] if row["source"] == source_id):
            page = run["pages"].index(case["source_page"]) + 1
            if modes[page] != "ocr":
                raise ValueError(f"Gold scan was not processed as a raster page: {case['id']}")
            result = score_case(case, tables, page)
            results.append(dict(result, id=case["id"], source=source_id, source_page=case["source_page"],
                                bbox=case["bbox"], split=source["split"], operator=source["operator"]))
    if not results:
        parser.error("The selected split has no annotated cases")
    output = {"gold_sha256": digest(args.gold), "summary": summaries(results), "cases": results, "inputs": inputs}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], indent=2))
    return int(args.require_exact and not all(case["exact_pass"] for case in results))


if __name__ == "__main__":
    raise SystemExit(main())
