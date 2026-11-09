"""Measure multi-page table candidates in a K1 release (A-108a). Measurement only: no pipeline change, no LLM, no network.

    python scripts/qa_multipage_scan.py --release <K1 release dir> --raw data/raw --out <dir> \
        [--config configs/qa/multipage.json] [--pymupdf-cross] [--crops-for 1,2,...]

A candidate is a table that ends the body of page p (no text but the running footer below it) followed by a table that
starts the body of page p+1 (no text but the running header above it) in the same document. Evidence per pair: column
count, x extent, repeated header row, first-row shape, column start positions from the text layer, a weighted score.
A pair with the structural boundary but a different structure is a LOOKALIKE. Output (scan.json, summary.json) is
deterministic: sorted keys, no timestamps. Scores are evidence for a human reviewer; they never prove a continuation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "qa" / "multipage.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return {
        "header_band": cfg["page_bands"]["header_band_frac"]["value"],
        "footer_band": cfg["page_bands"]["footer_band_frac"]["value"],
        "bottom_gap": cfg["boundary"]["bottom_gap_max_frac"]["value"],
        "top_gap": cfg["boundary"]["top_gap_max_frac"]["value"],
        "slack": cfg["boundary"]["word_slack_pt"]["value"],
        "x_tol": cfg["compatibility"]["x_tolerance_rel"]["value"],
        "edge_tol": cfg["compatibility"]["column_edge_tolerance_rel"]["value"],
        "segment_gap_em": cfg["compatibility"]["segment_gap_em"]["value"],
        "min_support": cfg["compatibility"]["column_start_min_support_frac"]["value"],
        "min_alnum": cfg["compatibility"]["numeric_cell_min_alnum"]["value"],
        "running_cell_pt": cfg["running_text"]["cell_pt"]["value"],
        "running_min_pages_frac": cfg["running_text"]["min_pages_frac"]["value"],
        "running_top_zone": cfg["running_text"]["top_zone_frac"]["value"],
        "running_bottom_zone": cfg["running_text"]["bottom_zone_frac"]["value"],
        "weights": cfg["score"]["weights"],
        "high_min": cfg["score"]["high_min"]["value"],
        "medium_min": cfg["score"]["medium_min"]["value"],
    }


# ---------------------------------------------------------------- pure helpers (unit tested)

def norm_cell(text) -> str:
    return " ".join(str(text or "").lower().split())


def norm_row(row) -> tuple:
    return tuple(norm_cell(cell) for cell in row)


def ends_page_body(bbox, words, page_height: float, cfg: dict, limit: float | None = None) -> dict:
    """Does the table end the page body? words are (x0, y0, x1, y1, text) in top-left page coordinates."""
    limit = page_height * (1.0 - cfg["footer_band"])
    below = [w for w in words if w[1] >= bbox[3] - cfg["slack"] and w[3] <= limit]
    gap = max(0.0, (limit - bbox[3]) / page_height)
    return {"words_below": len(below), "gap_frac": round(gap, 4),
            "ends": not below and gap <= cfg["bottom_gap"]}


def starts_page_body(bbox, words, page_height: float, cfg: dict, limit: float | None = None) -> dict:
    limit = page_height * cfg["header_band"] if limit is None else limit
    above = [w for w in words if w[3] <= bbox[1] + cfg["slack"] and w[1] >= limit]
    gap = max(0.0, (bbox[1] - limit) / page_height)
    return {"words_above": len(above), "gap_frac": round(gap, 4),
            "starts": not above and gap <= cfg["top_gap"]}


def x_extent_match(a, b, cfg: dict) -> dict:
    width = max(a[2] - a[0], b[2] - b[0], 1e-6)
    left = abs(a[0] - b[0]) / width
    right = abs(a[2] - b[2]) / width
    return {"left_delta_rel": round(left, 4), "right_delta_rel": round(right, 4),
            "match": left <= cfg["x_tol"] and right <= cfg["x_tol"]}


def column_starts(words, bbox, cfg: dict) -> list:
    """Cell-start x positions inside bbox from the text layer: positions supported by enough text lines."""
    inside = [w for w in words if w[0] >= bbox[0] - cfg["slack"] and w[2] <= bbox[2] + cfg["slack"]
              and w[1] >= bbox[1] - cfg["slack"] and w[3] <= bbox[3] + cfg["slack"]]
    if not inside:
        return []
    heights = sorted(w[3] - w[1] for w in inside)
    median_h = heights[len(heights) // 2] or 1.0
    lines: list[list] = []
    for word in sorted(inside, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        centre = (word[1] + word[3]) / 2
        if lines and abs(centre - lines[-1][0]) <= 0.5 * median_h:
            lines[-1][1].append(word)
        else:
            lines.append([centre, [word]])
    starts: list[float] = []
    for _, line_words in lines:
        previous_end = None
        for word in sorted(line_words, key=lambda w: w[0]):
            if previous_end is None or word[0] - previous_end > cfg["segment_gap_em"] * median_h:
                starts.append(word[0])
            previous_end = max(previous_end or word[2], word[2])
    tolerance = cfg["edge_tol"] * max(bbox[2] - bbox[0], 1e-6)
    clusters: list[list[float]] = []
    for value in sorted(starts):
        if clusters and value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    need = max(2, int(cfg["min_support"] * len(lines) + 0.999))
    return [round(sum(c) / len(c), 2) for c in clusters if len(c) >= need]


def column_starts_match(a: list, b: list, width: float, cfg: dict) -> dict:
    if not a or not b:
        return {"match": None, "reason": "no_text_layer_columns", "count_a": len(a), "count_b": len(b)}
    if len(a) != len(b):
        return {"match": False, "reason": "count_differs", "count_a": len(a), "count_b": len(b)}
    delta = max(abs(x - y) for x, y in zip(a, b)) / max(width, 1e-6)
    return {"match": delta <= cfg["edge_tol"], "reason": "compared", "count_a": len(a), "count_b": len(b),
            "max_delta_rel": round(delta, 4)}


def first_row_shape(row, cfg: dict) -> dict:
    cells = [str(c or "") for c in row]
    filled = [c for c in cells if sum(ch.isalnum() for ch in c) >= cfg["min_alnum"]]
    numeric = [c for c in filled if re.fullmatch(r"[\s\d.,:/()+\-%$]+", c)]
    return {"cells": len(cells), "filled": len(filled),
            "numeric_frac": round(len(numeric) / len(filled), 3) if filled else None}


def score_pair(evidence: dict, cfg: dict) -> float:
    weights = cfg["weights"]
    total = sum(weights.values())
    got = sum(weight for key, weight in weights.items() if evidence.get(key))
    return round(got / total, 4)


def grade(score: float, cfg: dict) -> str:
    return "HIGH" if score >= cfg["high_min"] else "MEDIUM" if score >= cfg["medium_min"] else "LOW"


def evaluate_pair(a: dict, b: dict, words_a, words_b, height_a: float, height_b: float, cfg: dict,
                  limit_a: float | None = None, limit_b: float | None = None) -> dict:
    """a ends page p, b starts page p+1. a and b: {id, page, bbox, grid, num_cols}. Returns the evidence record."""
    end = ends_page_body(a["bbox"], words_a, height_a, cfg, limit_a)
    start = starts_page_body(b["bbox"], words_b, height_b, cfg, limit_b)
    extent = x_extent_match(a["bbox"], b["bbox"], cfg)
    header_a = a["grid"][0] if a["grid"] else []
    row_b = b["grid"][0] if b["grid"] else []
    repeated = bool(header_a) and norm_row(header_a) == norm_row(row_b)
    width = max(a["bbox"][2] - a["bbox"][0], b["bbox"][2] - b["bbox"][0])
    starts_a = column_starts(words_a, a["bbox"], cfg)
    starts_b = column_starts(words_b, b["bbox"], cfg)
    evidence = {
        "ends_page_body": end["ends"], "starts_page_body": start["starts"],
        "columns_equal": a["num_cols"] == b["num_cols"], "x_extent_match": extent["match"],
        "header_repeated": repeated,
    }
    boundary = end["ends"] and start["starts"]
    structure = evidence["columns_equal"] and evidence["x_extent_match"]
    score = score_pair(evidence, cfg)
    return {
        "a": a["id"], "b": b["id"], "page_a": a["page"], "page_b": b["page"],
        "kind": ("CANDIDATE" if structure else "LOOKALIKE") if boundary else "NO_BOUNDARY",
        "grade": grade(score, cfg) if boundary else None, "score": score, "evidence": evidence,
        "detail": {
            "end": end, "start": start, "x_extent": extent,
            "num_cols": [a["num_cols"], b["num_cols"]],
            "column_starts": column_starts_match(starts_a, starts_b, width, cfg),
            "b_first_row": first_row_shape(row_b, cfg),
            "a_header": list(header_a), "b_first_row_text": list(row_b),
        },
    }


def running_limits(pages: dict, cfg: dict) -> dict:
    """Per page (top_limit, bottom_limit) in points: words whose grid cell (x, y) is occupied on at least
    running_min_pages_frac of the document pages, inside the top / bottom search zone, are template text (report
    title block, footer) and are skipped. pages: {page: (words, height)}. Position only, text is ignored, so a
    different date or report number does not hide the template."""
    cell = cfg["running_cell_pt"]
    counts: Counter = Counter()
    for words, height in pages.values():
        keys = {(round(w[0] / cell), round(w[1] / cell)) for w in words
                if w[3] <= height * cfg["running_top_zone"] or w[1] >= height * (1 - cfg["running_bottom_zone"])}
        counts.update(keys)
    need = max(2, cfg["running_min_pages_frac"] * len(pages))
    limits = {}
    for page, (words, height) in pages.items():
        top = height * cfg["header_band"]
        bottom = height * (1.0 - cfg["footer_band"])
        for w in words:
            if counts[(round(w[0] / cell), round(w[1] / cell))] < need:
                continue
            if w[3] <= height * cfg["running_top_zone"]:
                top = max(top, w[3])
            elif w[1] >= height * (1 - cfg["running_bottom_zone"]):
                bottom = min(bottom, w[1])
        limits[page] = (top, bottom)
    return limits


def pair_boundaries(tables: list) -> list:
    """(last table of page p, first table of page p+1) for every consecutive page pair of one document."""
    by_page: dict = {}
    for table in tables:
        by_page.setdefault(table["page"], []).append(table)
    pairs = []
    for page in sorted(by_page):
        if page + 1 in by_page:
            last = max(by_page[page], key=lambda t: (t["bbox"][3], t["id"]))
            first = min(by_page[page + 1], key=lambda t: (t["bbox"][1], t["id"]))
            pairs.append((last, first))
    return pairs


# ---------------------------------------------------------------- release / PDF access

def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_release(release: Path) -> dict:
    files = {row["file_id"]: row for row in iter_jsonl(release / "files.jsonl")}
    pages = {(row["file_id"], row["page"]): row for row in iter_jsonl(release / "pages.jsonl")}
    chunks = Counter()
    chunk_rows = {}
    for row in iter_jsonl(release / "chunks.jsonl"):
        if row.get("type") == "table" and row.get("table_id"):
            chunks[row["table_id"]] += 1
            chunk_rows.setdefault(row["table_id"], []).append((row.get("row_start"), row.get("row_end")))
    tables: dict = {}
    for row in iter_jsonl(release / "tables.jsonl"):
        parts = row["parts"]
        regions = row["regions"]
        for index, region in enumerate(regions):
            tables.setdefault(row["file_id"], []).append({
                "id": row["table_id"] if len(regions) == 1 else f"{row['table_id']}#{index}",
                "page": region["page"], "bbox": region["bbox"], "grid": row["grid"],
                "num_cols": row["num_cols"], "num_rows": row["num_rows"], "header_rows": row["header_rows"],
                "source": ("textlayer" if parts[min(index, len(parts) - 1)]["source_ref"].startswith("textlayer") else "docling") if parts else "",
                "join_status": row["join"]["status"], "n_regions": len(regions),
            })
    return {"files": files, "pages": pages, "tables": tables, "chunks": chunks, "chunk_rows": chunk_rows}


def find_pdfs(files: dict, raw: Path) -> dict:
    wanted = {row["sha256"]: file_id for file_id, row in files.items()}
    found = {}
    for path in sorted(raw.glob("*.pdf")):
        digest = sha256(path)
        if digest in wanted:
            found[wanted[digest]] = path
    return found


def page_words(doc, index: int) -> tuple:
    page = doc[index]
    words = [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]
    return words, page.rect.height, page.rotation


def pymupdf_tables(doc, index: int) -> list:
    out = []
    finder = doc[index].find_tables()
    for number, table in enumerate(finder.tables):
        rows = table.extract()
        out.append({"id": f"p{index + 1}:m{number}", "page": index + 1, "bbox": [round(v, 2) for v in table.bbox],
                    "grid": rows, "num_cols": table.col_count, "num_rows": table.row_count})
    return out


def scan(release: Path, raw: Path, cfg: dict, pymupdf_cross: bool) -> dict:
    import pymupdf as fitz
    data = load_release(release)
    pdfs = find_pdfs(data["files"], raw)
    result = {"documents": {}, "pairs": [], "pymupdf_pairs": []}
    for file_id in sorted(data["files"]):
        tables = data["tables"].get(file_id, [])
        pdf = pdfs.get(file_id)
        doc_record = {"pdf": pdf.name if pdf else None, "pages": data["files"][file_id]["page_count"],
                      "tables": len(tables), "rotated_pages": 0, "errors": []}
        result["documents"][file_id] = doc_record
        if pdf is None:
            doc_record["errors"].append("PDF_NOT_FOUND_BY_SHA256")
            continue
        with fitz.open(pdf) as doc:
            cache: dict = {}

            def words_of(page_number: int):
                if page_number not in cache:
                    cache[page_number] = page_words(doc, page_number - 1)
                return cache[page_number]

            for page_number in range(1, len(doc) + 1):
                words_of(page_number)
            limits = running_limits({n: (v[0], v[1]) for n, v in cache.items()}, cfg)
            for a, b in pair_boundaries(tables):
                try:
                    words_a, height_a, rotation_a = words_of(a["page"])
                    words_b, height_b, rotation_b = words_of(b["page"])
                    if rotation_a or rotation_b:
                        doc_record["rotated_pages"] += 1
                    record = evaluate_pair(a, b, words_a, words_b, height_a, height_b, cfg,
                                           limits[a["page"]][1], limits[b["page"]][0])
                    record["file_id"] = file_id
                    record["rotation"] = [rotation_a, rotation_b]
                    record["rows"] = [a["num_rows"], b["num_rows"]]
                    record["table_chunks"] = [data["chunks"].get(a["id"], 0), data["chunks"].get(b["id"], 0)]
                    record["join_status"] = [a["join_status"], b["join_status"]]
                    record["sources"] = [a["source"], b["source"]]
                    result["pairs"].append(record)
                except Exception as exc:  # per-pair isolation
                    doc_record["errors"].append(f"{a['id']}->{b['id']}: {type(exc).__name__}: {exc}")
            if pymupdf_cross:
                try:
                    found = []
                    for index in range(len(doc)):
                        found.extend(pymupdf_tables(doc, index))
                    doc_record["pymupdf_tables"] = len(found)
                    for a, b in pair_boundaries(found):
                        words_a, height_a, _ = words_of(a["page"])
                        words_b, height_b, _ = words_of(b["page"])
                        record = evaluate_pair(a, b, words_a, words_b, height_a, height_b, cfg,
                                               limits[a["page"]][1], limits[b["page"]][0])
                        record["file_id"] = file_id
                        result["pymupdf_pairs"].append(record)
                except Exception as exc:
                    doc_record["errors"].append(f"pymupdf_cross: {type(exc).__name__}: {exc}")
    result["_data"] = data
    return result


def summarize(result: dict) -> dict:
    data = result.pop("_data")
    pairs = result["pairs"]
    consecutive = len(pairs)
    kinds = Counter(p["kind"] for p in pairs)
    candidates = [p for p in pairs if p["kind"] == "CANDIDATE"]
    all_tables = [t for tables in data["tables"].values() for t in tables]
    summary = {
        "documents": len(result["documents"]),
        "pages": sum(d["pages"] for d in result["documents"].values()),
        "tables": len(all_tables),
        "tables_by_source": dict(sorted(Counter(t["source"] for t in all_tables).items())),
        "join_status": dict(sorted(Counter(t["join_status"] for t in all_tables).items())),
        "table_chunks_per_table": dict(sorted(Counter(data["chunks"].get(t["id"], 0) for t in all_tables).items())),
        "consecutive_page_pairs_with_tables": consecutive,
        "pair_kinds": dict(sorted(kinds.items())),
        "candidate_grades": dict(sorted(Counter(p["grade"] for p in candidates).items())),
        "candidates_header_repeated": sum(1 for p in candidates if p["evidence"]["header_repeated"]),
        "candidates_by_document": dict(sorted(Counter(p["file_id"] for p in candidates).items())),
        "candidates_by_source": dict(sorted(Counter("+".join(p["sources"]) for p in candidates).items())),
        "rotated_pairs": sum(1 for p in pairs if any(p["rotation"])),
        "pair_errors": sum(len(d["errors"]) for d in result["documents"].values()),
        "pymupdf_pairs": dict(sorted(Counter(p["kind"] for p in result["pymupdf_pairs"]).items())),
        "label_note": "NOT classified: every candidate and lookalike is unreviewed until a person views the crop",
    }
    return summary


def render_crops(result: dict, release: Path, raw: Path, out: Path, ids: list, scale: float = 1.5) -> list:
    import pymupdf as fitz
    data_files = {row["file_id"]: row for row in iter_jsonl(release / "files.jsonl")}
    pdfs = find_pdfs(data_files, raw)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for number in ids:
        pair = result["pairs"][number]
        pdf = pdfs.get(pair["file_id"])
        if pdf is None:
            continue
        with fitz.open(pdf) as doc:
            images = []
            for page_number in (pair["page_a"], pair["page_b"]):
                pix = doc[page_number - 1].get_pixmap(matrix=fitz.Matrix(scale, scale))
                images.append(pix)
            path = out / f"pair_{number:03d}.png"
            width = images[0].width + images[1].width + 10
            height = max(images[0].height, images[1].height)
            canvas = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
            canvas.set_rect(canvas.irect, (255, 255, 255))
            for pix, x in ((images[0], 0), (images[1], images[0].width + 10)):
                pix = fitz.Pixmap(fitz.csRGB, pix) if pix.colorspace.n != 3 else pix
                pix.set_origin(x, 0)
                canvas.copy(pix, pix.irect)
            canvas.save(path)
            written.append(str(path))
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--pymupdf-cross", action="store_true")
    parser.add_argument("--crops-for", default="", help="comma separated indices into scan.json pairs")
    args = parser.parse_args()
    cfg = load_config(args.config)
    result = scan(args.release, args.raw, cfg, args.pymupdf_cross)
    summary = summarize(result)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scan.json").write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
    if args.crops_for:
        ids = [int(x) for x in args.crops_for.split(",") if x.strip()]
        render_crops(result, args.release, args.raw, args.out / "crops", ids)
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
