"""A-501 comparative table-extraction benchmark (one command reproduces everything).

    python scripts/benchmark_tables.py all            # manifest -> run -> determinism -> score  (default interpreter: docling venv)
    python scripts/benchmark_tables.py manifest       # build the dataset manifest only
    python scripts/benchmark_tables.py run [--only C3a_pdfplumber_lines ...] [--datasets D1 D2]
    python scripts/benchmark_tables.py determinism    # repeat D1 for every candidate, compare hashes
    python scripts/benchmark_tables.py score          # metrics from the stored extraction files

Interpreter: ``explorations/ingestion/.venvs/docling/Scripts/python.exe`` (orchestrator, manifest, scoring). Each candidate runs
in its own venv through a subprocess (``worker`` sub-command, stdlib at module level, libraries imported lazily).

Datasets are reported separately and never averaged:
  D1  K5 gold tables (cell-level truth, data/gold/ingestion)
  D2  Operations Summary tables of appendices 27/28/30 (truth = PDF text layer read with PyMuPDF; seen data, development)
  D3  negative pages (no table by a candidate-independent heuristic; proxy, see ``negative_pages`` in the config)
  D4  other document families (no cell truth; detection agreement only; NOT independent truth)

Per candidate x item exactly one status: EVALUATED, NOT_APPLICABLE, UNSUPPORTED, FAILED (plus NOT_RUN_LIMIT when a page limit
was applied to a slow candidate). Metrics are computed only over EVALUATED items; the other denominators are reported.
Pure functions (matching, normalisation, grid scores) are at the top and are unit tested; thresholds live in
configs/benchmark_tables.json.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/benchmark_tables.json"
OUT_DIR = ROOT / "data/interim/overnight/a501"
RAW = ROOT / "data/raw"
GOLD = ROOT / "data/gold/ingestion"
WORK = ROOT / "data/interim/k1-run/corpus/work"
RELEASE_R2 = ROOT / "data/interim/k1-run/corpus/exports/ops-rebuild-r3-e2/releases/20261108T174020Z-e34a87c780d8"
VENVS = {name: ROOT / f"explorations/ingestion/.venvs/{name}/Scripts/python.exe" for name in ("docling", "pdfplumber", "camelot")}

# Declared capabilities (fairness): what each candidate is designed to do. ``needs_ruling``: only finds tables with drawn
# ruling lines; ``text_layer_only``: cannot read scanned pages; ``domain``: restricted to one table family.
CANDIDATES = {
    "C1_docling_fast": {"venv": "docling", "family": "layout model + TableFormer (fast)", "needs_ruling": False,
                        "text_layer_only": False, "domain": None, "cell_extraction": True, "scanned": "yes (OCR, not exercised here)"},
    "C2_docling_accurate": {"venv": "docling", "family": "layout model + TableFormer (accurate)", "needs_ruling": False,
                            "text_layer_only": False, "domain": None, "cell_extraction": True, "scanned": "yes (OCR, not exercised here)"},
    "C3a_pdfplumber_lines": {"venv": "pdfplumber", "family": "text layer + ruling lines", "needs_ruling": True,
                             "text_layer_only": True, "domain": None, "cell_extraction": True, "scanned": "no"},
    "C3b_pdfplumber_text": {"venv": "pdfplumber", "family": "text layer + word alignment", "needs_ruling": False,
                            "text_layer_only": True, "domain": None, "cell_extraction": True, "scanned": "no"},
    "C4a_camelot_lattice": {"venv": "camelot", "family": "text layer + ruling lines (lattice)", "needs_ruling": True,
                            "text_layer_only": True, "domain": None, "cell_extraction": True, "scanned": "no"},
    "C4b_camelot_stream": {"venv": "camelot", "family": "text layer + word alignment (stream)", "needs_ruling": False,
                           "text_layer_only": True, "domain": None, "cell_extraction": True, "scanned": "no"},
    "C5a_pymupdf_lines": {"venv": "docling", "family": "text layer + ruling lines", "needs_ruling": True,
                          "text_layer_only": True, "domain": None, "cell_extraction": True, "scanned": "no"},
    "C5b_pymupdf_text": {"venv": "docling", "family": "text layer + word alignment", "needs_ruling": False,
                         "text_layer_only": True, "domain": None, "cell_extraction": True, "scanned": "no"},
    "C6_custom_ops": {"venv": None, "family": "A-107 text-layer reconstruction (Operations Summary only)", "needs_ruling": False,
                      "text_layer_only": True, "domain": "ops", "cell_extraction": True, "scanned": "no"},
}
DATASET_LABELS = {
    "D1": "K5 gold tables (cell-level truth, AI-assisted single annotator)",
    "D2": "Operations Summary tables, truth = PDF text layer (seen data, development)",
    "D3": "negative pages (heuristic 'no table', proxy)",
    "D4": "other document families (not independent truth, agreement only)",
}
ALL_DATASETS = ("D1", "D2", "D3", "D4")
TIME = re.compile(r"^\d{1,2}:\d\d$")


# ------------------------------------------------------------------------------------------------ pure functions

def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def normalize_text(value) -> str:
    """NFKC, dashes unified, case-folded, whitespace collapsed. None -> ''."""
    text = unicodedata.normalize("NFKC", "" if value is None else str(value))
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    return " ".join(text.casefold().split())


def token_counter(text: str) -> collections.Counter:
    return collections.Counter(normalize_text(text).split())


def f1_from_counters(truth: collections.Counter, pred: collections.Counter) -> dict:
    common = sum((truth & pred).values())
    recall = common / sum(truth.values()) if truth else None
    precision = common / sum(pred.values()) if pred else None
    if not common:
        return {"precision": precision, "recall": recall, "f1": 0.0 if (truth or pred) else None}
    return {"precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall)}


def iou(a, b) -> float:
    """Intersection over union of two [x0, top, x1, bottom] boxes (same origin)."""
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def clean_grid(grid) -> list[list[str]]:
    """Rectangular grid of normalised cell strings (None -> '')."""
    rows = [[normalize_text(c) for c in (row or [])] for row in (grid or [])]
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


def grid_tokens(grid) -> collections.Counter:
    counter: collections.Counter = collections.Counter()
    for row in clean_grid(grid):
        for cell in row:
            counter.update(cell.split())
    return counter


def match_tables(truths: list[dict], preds: list[dict], threshold: float) -> list[tuple[int, int, float]]:
    """Greedy one-to-one matching. Each element carries a precomputed ``score_to`` callable via ``pair_score``.

    ``truths``/``preds`` are dicts; the caller supplies the score function through ``truths[i]['_score'](pred)``.
    Returns (truth_index, pred_index, score) sorted by truth index, only pairs with score >= threshold.
    """
    pairs = sorted(((t["_score"](p), i, j) for i, t in enumerate(truths) for j, p in enumerate(preds)), key=lambda x: (-x[0], x[1], x[2]))
    used_t, used_p, out = set(), set(), []
    for score, i, j in pairs:
        if score < threshold:
            break
        if i in used_t or j in used_p:
            continue
        used_t.add(i)
        used_p.add(j)
        out.append((i, j, score))
    return sorted(out)


def _multiset(grid, rows=None) -> collections.Counter:
    counter: collections.Counter = collections.Counter()
    for r, row in enumerate(grid):
        if rows is not None and r not in rows:
            continue
        counter.update(c for c in row if c)
    return counter


def grid_scores_at(truth: list[list[str]], pred: list[list[str]], header_rows: int) -> dict:
    """Structure and content scores of a normalised predicted grid against a normalised truth grid (no offset)."""
    t_rows, p_rows = len(truth), len(pred)
    t_cols = max((len(r) for r in truth), default=0)
    p_cols = max((len(r) for r in pred), default=0)
    nonempty = pos = 0
    for r, row in enumerate(truth):
        for c, cell in enumerate(row):
            if not cell:
                continue
            nonempty += 1
            if r < p_rows and c < len(pred[r]) and pred[r][c] == cell:
                pos += 1
    t_set, p_set = _multiset(truth), _multiset(pred)
    common = sum((t_set & p_set).values())
    squash = lambda c: collections.Counter({k.replace(" ", ""): v for k, v in c.items()})  # noqa: E731
    common_nospace = sum((squash(t_set) & squash(p_set)).values())
    header_ok = None
    if header_rows > 0:
        header_ok = _multiset(truth, set(range(header_rows))) == _multiset(pred, set(range(header_rows))) and p_rows >= header_rows
    return {"truth_rows": t_rows, "pred_rows": p_rows, "truth_cols": t_cols, "pred_cols": p_cols,
            "row_exact": t_rows == p_rows, "col_exact": t_cols == p_cols, "row_within_1": abs(t_rows - p_rows) <= 1,
            "truth_cells": nonempty, "positional_cells": pos, "set_hits": common, "set_hits_nospace": common_nospace,
            "pred_cells": sum(p_set.values()),
            "header_ok": header_ok}


def grid_scores(truth_grid, pred_grid, header_rows: int, offsets=(0,)) -> dict:
    """Best score over the allowed leading-row offsets of the prediction (offset 0 only unless the caller allows more)."""
    truth, pred = clean_grid(truth_grid), clean_grid(pred_grid)
    best = None
    for k in offsets:
        if k > len(pred):
            continue
        scores = grid_scores_at(truth, pred[k:], header_rows)
        key = (scores["positional_cells"], scores["set_hits"], -k)
        if best is None or key > best[0]:
            best = (key, dict(scores, offset=k))
    if best is None:
        best = (None, dict(grid_scores_at(truth, [], header_rows), offset=0))
    scores = best[1]
    f1 = f1_from_counters(grid_tokens(truth_grid), grid_tokens(pred_grid))
    scores.update(token_precision=f1["precision"], token_recall=f1["recall"], token_f1=f1["f1"])
    return scores


def row_text_sequences(grid) -> list[tuple[str, ...]]:
    """Order-sensitive token sequence of each row (all non-empty cells joined in column order)."""
    return [tuple(" ".join(c for c in row if c).split()) for row in clean_grid(grid)]


def row_text_exact(truth_rows: list[tuple], pred_grid) -> int:
    """How many truth rows have an identical token sequence in some (unused) predicted row."""
    available = collections.Counter(s for s in row_text_sequences(pred_grid) if s)
    hits = 0
    for seq in truth_rows:
        if seq and available[seq] > 0:
            available[seq] -= 1
            hits += 1
    return hits


def percentile(values: list[float], q: float):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def canonical_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def applicability(caps: dict, item: dict) -> tuple[str, str]:
    """('EVALUATED'|'NOT_APPLICABLE', reason) of a candidate for one truth item, from declared capabilities only."""
    if caps["domain"] == "ops" and item.get("kind") != "ops":
        return "NOT_APPLICABLE", "A-107 rule only handles Operations Summary tables"
    if caps["text_layer_only"] and item.get("text_chars", 1) <= 0:
        return "NOT_APPLICABLE", "no text layer (scanned page)"
    if caps["needs_ruling"] and not item.get("ruled", False):
        return "NOT_APPLICABLE", "no ruling lines around the table (method needs drawn lines)"
    return "EVALUATED", ""


# ------------------------------------------------------------------------------------------------ manifest (PyMuPDF)

def rule_counts(page, bbox, cfg) -> dict:
    """Axis-aligned rule segments inside ``bbox`` (displayed coordinates) from PyMuPDF drawings."""
    import fitz
    r = cfg["ruling"]
    rect = fitz.Rect(bbox) + (-r["margin_pt"], -r["margin_pt"], r["margin_pt"], r["margin_pt"])
    rect = rect * page.derotation_matrix if page.rotation else rect
    h = v = 0
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                box = fitz.Rect(min(p1.x, p2.x), min(p1.y, p2.y), max(p1.x, p2.x), max(p1.y, p2.y))
                if not rect.intersects(box):
                    continue
                if abs(p1.y - p2.y) <= r["max_rule_thickness_pt"] and abs(p1.x - p2.x) >= r["min_rule_length_pt"]:
                    h += 1
                elif abs(p1.x - p2.x) <= r["max_rule_thickness_pt"] and abs(p1.y - p2.y) >= r["min_rule_length_pt"]:
                    v += 1
            elif item[0] == "re":
                box = item[1]
                if not rect.intersects(box):
                    continue
                if box.width >= r["min_rule_length_pt"]:
                    h += 2 if box.height > r["max_rule_thickness_pt"] else 1
                if box.height >= r["min_rule_length_pt"]:
                    v += 2 if box.width > r["max_rule_thickness_pt"] else 1
    return {"h": h, "v": v, "ruled": h >= r["min_h_rules"] and v >= r["min_v_rules"]}


def page_profile(page, cfg) -> dict:
    """Candidate-independent page facts used to build D3/D4: text chars, rule items, columnar lines."""
    n = cfg["negative_pages"]
    text_chars = len(page.get_text().strip())
    rules = sum(len(d["items"]) for d in page.get_drawings())
    lines: list[list[tuple[float, float]]] = []
    centres: list[float] = []
    for w in sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        centre = (w[1] + w[3]) / 2
        if lines and abs(centres[-1] - centre) <= 3.0:
            lines[-1].append((w[0], w[2]))
        else:
            lines.append([(w[0], w[2])])
            centres.append(centre)
    columnar = 0
    for words in lines:
        words.sort()
        segments = 1 + sum(1 for a, b in zip(words, words[1:]) if b[0] - a[1] >= n["columnar_gap_pt"])
        columnar += segments >= n["columnar_min_segments"]
    return {"text_chars": text_chars, "rule_items": rules, "columnar_lines": columnar, "rotation": page.rotation}


def cache_for(pdf_name: str) -> str | None:
    """Relative path of the cached Docling document of the corpus work folder for this PDF, if any (INSPECTED mapping)."""
    stem = pdf_name[:-4]
    if stem == "gdr882_ak3_eowr":
        found = sorted((WORK / "gdr882_ak3_eowr").glob("*/docling.json.gz"))
    else:
        match = re.match(r"gdr882_ak3_appx_(27|28|29|30)_", stem)
        found = sorted(WORK.glob(f"gdr882-ak3-appx-{match.group(1)}-*/*/docling.json.gz")) if match else []
    return found[0].relative_to(ROOT).as_posix() if found else None


def stable_key(*parts) -> str:
    return hashlib.sha1(":".join(map(str, parts)).encode()).hexdigest()


def read_gold_grid(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.reader(handle)]


def build_manifest(cfg: dict) -> dict:
    import fitz
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate_ops_tables as ops

    manifest = {"version": 1, "config": cfg, "labels": DATASET_LABELS, "datasets": {}, "notes": []}
    page_info: dict[tuple[str, int], dict] = {}

    def info(doc, pdf_name, number) -> dict:
        key = (pdf_name, number)
        if key not in page_info:
            page = doc[number - 1]
            page_info[key] = dict(page_profile(page, cfg), pdf=pdf_name, page=number, cache=cache_for(pdf_name))
        return page_info[key]

    # ---- D1 gold
    items, pages = [], {}
    for entry in json.loads((GOLD / "tables.json").read_text(encoding="utf-8")):
        pdf_name = entry["doc_id"] + ".pdf"
        grid = read_gold_grid(ROOT / entry["csv"])
        with fitz.open(RAW / pdf_name) as doc:
            page = doc[entry["page"] - 1]
            profile = info(doc, pdf_name, entry["page"])
            rules = rule_counts(page, entry["bbox"], cfg)
        head = " ".join(" ".join(r) for r in grid[:2])
        items.append({"id": entry["id"], "pdf": pdf_name, "page": entry["page"], "bbox": entry["bbox"], "format": entry["format"],
                      "header_rows": entry["header_rows"], "grid": grid, "rotation": profile["rotation"],
                      "text_chars": profile["text_chars"], "ruled": rules["ruled"], "rule_counts": rules,
                      "kind": "ops" if "Operations Description" in head and "Non-Prod" in head else "other"})
        pages[(pdf_name, entry["page"])] = profile
    manifest["datasets"]["D1"] = {"items": items, "pages": [pages[k] for k in sorted(pages)]}

    # ---- D2 operations tables (truth: PyMuPDF text layer, dynamic zones; same functions as scripts/evaluate_ops_tables.py)
    files = ops.read_jsonl(RELEASE_R2 / "files.jsonl")
    names = {ops.appendix_of(f["doc_id"]): f["original_name"] for f in files if ops.appendix_of(f["doc_id"])}
    wanted = set(ops.DEVELOPMENT + ops.HELDOUT)
    truth_pages, census = ops.scan_pdfs(RAW, names, wanted, ops.truth_tables_dynamic)
    items, pages = [], {}
    for (appendix, number), data in sorted(truth_pages.items()):
        pdf_name = names[appendix]
        if not data["tables"]:
            continue
        with fitz.open(RAW / pdf_name) as doc:
            profile = info(doc, pdf_name, number)
            page = doc[number - 1]
            for index, table in enumerate(data["tables"]):
                grid = [list(ops.HEADER)] + [[r["from"], r["to"], r["elapsed"], r["end_md"], r["code"], r["description"],
                                              "X" if r["x"] else ""] for r in table["rows"]]
                items.append({"id": f"D2:{appendix}:{number}:{index + 1}", "appendix": appendix, "pdf": pdf_name, "page": number,
                              "index": index + 1, "date": data["date"], "grid": grid, "header_rows": 1, "format": "grid",
                              "rotation": profile["rotation"], "text_chars": profile["text_chars"], "kind": "ops", "ruled": None})
        pages[(pdf_name, number)] = profile
    # ruled flag for D2: rule segments over the whole page (table bbox is not part of this truth); recorded per page
    for item in items:
        with fitz.open(RAW / item["pdf"]) as doc:
            page = doc[item["page"] - 1]
            item["rule_counts"] = rule_counts(page, list(page.rect), cfg)
            item["ruled"] = item["rule_counts"]["ruled"]
    manifest["datasets"]["D2"] = {"items": items, "pages": [pages[k] for k in sorted(pages)], "page_dates": census,
                                  "release_for_C6": RELEASE_R2.relative_to(ROOT).as_posix()}
    manifest["notes"].append("D2 'ruled' = rule segments anywhere on the page (the text-layer truth has no table bbox)")

    # ---- pool of all unique PDFs for D3/D4
    seen: dict[str, str] = {}
    unique = []
    for path in sorted(RAW.glob("*.pdf")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in seen:
            seen[digest] = path.name
            unique.append(path.name)
    manifest["unique_pdfs"] = unique
    manifest["duplicate_pdfs_skipped"] = len(list(RAW.glob("*.pdf"))) - len(unique)
    used = {(i["pdf"], i["page"]) for d in ("D1", "D2") for i in manifest["datasets"][d]["items"]}
    d2_docs = {names[a] for a in names}

    pool: dict[str, list[dict]] = {}
    skipped_no_text = 0
    for pdf_name in unique:
        with fitz.open(RAW / pdf_name) as doc:
            for number in range(1, len(doc) + 1):
                if (pdf_name, number) in used or pdf_name in d2_docs:
                    continue
                profile = info(doc, pdf_name, number)
                if profile["text_chars"] < cfg["min_text_layer_chars"]:
                    skipped_no_text += 1
                    continue
                pool.setdefault(pdf_name, []).append(profile)
    manifest["pages_without_text_layer_excluded"] = skipped_no_text

    def round_robin(candidates: dict[str, list[dict]], limit: int, per_round: int) -> list[dict]:
        order = sorted(candidates, key=lambda n: stable_key("doc", n))
        queues = {n: sorted(candidates[n], key=lambda p: stable_key(n, p["page"])) for n in order}
        chosen: list[dict] = []
        while len(chosen) < limit and any(queues.values()):
            for n in order:
                for _ in range(per_round):
                    if queues[n] and len(chosen) < limit:
                        chosen.append(queues[n].pop(0))
        return sorted(chosen, key=lambda p: (p["pdf"], p["page"]))

    neg = cfg["negative_pages"]
    eligible = {n: [p for p in pages_ if p["text_chars"] >= neg["min_text_chars"] and p["rule_items"] <= neg["max_rule_items"]
                    and p["columnar_lines"] <= neg["max_columnar_lines"]] for n, pages_ in pool.items()}
    eligible = {n: p for n, p in eligible.items() if p}
    d3 = round_robin(eligible, neg["max_pages"], neg["per_document_first_round"])
    d3_keys = {(p["pdf"], p["page"]) for p in d3}
    rest = {n: [p for p in pages_ if (p["pdf"], p["page"]) not in d3_keys and p["text_chars"] >= cfg["other_family_pages"]["min_text_chars"]]
            for n, pages_ in pool.items()}
    rest = {n: p for n, p in rest.items() if p}
    d4 = round_robin(rest, cfg["other_family_pages"]["max_pages"], 1)
    manifest["datasets"]["D3"] = {"pages": d3, "eligible_pages_total": sum(len(v) for v in eligible.values()),
                                  "documents_with_eligible_pages": len(eligible),
                                  "definition": "text >= %d chars, <= %d drawing items, <= %d columnar lines (>=%d segments split by gaps >= %.0f pt); "
                                                "pages of D1/D2 and appendices 27/28/30 excluded; a proxy, not a proof of 'no table'"
                                                % (neg["min_text_chars"], neg["max_rule_items"], neg["max_columnar_lines"],
                                                   neg["columnar_min_segments"], neg["columnar_gap_pt"])}
    manifest["datasets"]["D4"] = {"pages": d4, "pool_pages_total": sum(len(v) for v in rest.values()),
                                  "definition": "stratified round-robin over unique documents, pages with text, disjoint from D1-D3; no truth"}
    return manifest


# ------------------------------------------------------------------------------------------------ workers (one per candidate)

def clean_cells(grid) -> list[list[str]]:
    return [["" if c is None else str(c) for c in row] for row in (grid or [])]


def docling_tables_from_document(doc, wanted_pages: set[int]) -> dict[int, list[dict]]:
    found: dict[int, list[dict]] = {}
    for table in doc.tables:
        if not table.prov:
            continue
        number = table.prov[0].page_no
        if number not in wanted_pages:
            continue
        height = doc.pages[number].size.height
        box = table.prov[0].bbox.to_top_left_origin(height)
        data = table.data
        grid = [[""] * data.num_cols for _ in range(data.num_rows)]
        for cell in data.table_cells:
            grid[cell.start_row_offset_idx][cell.start_col_offset_idx] = cell.text
        found.setdefault(number, []).append({"bbox": [box.l, box.t, box.r, box.b], "grid": grid})
    return found


def _emit(handle, record) -> None:
    handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
    handle.flush()


def worker_docling(entries: list[dict], mode: str, out_path: Path) -> None:
    import gzip
    from docling_core.types.doc import DoclingDocument
    converter = None
    cached: dict[str, object] = {}
    with out_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            record = {"pdf": entry["pdf"], "page": entry["page"], "status": "ok", "source": "fresh", "seconds": None, "tables": []}
            try:
                if entry.get("cache") and mode == "fast":
                    path = ROOT / entry["cache"]
                    if entry["cache"] not in cached:
                        cached[entry["cache"]] = DoclingDocument.model_validate_json(gzip.open(path, "rt", encoding="utf-8").read())
                    record["source"] = "cache"
                    record["tables"] = docling_tables_from_document(cached[entry["cache"]], {entry["page"]}).get(entry["page"], [])
                else:
                    if converter is None:
                        from docling.datamodel.base_models import InputFormat
                        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
                        from docling.document_converter import DocumentConverter, PdfFormatOption
                        options = PdfPipelineOptions()
                        options.do_ocr = False
                        options.do_table_structure = True
                        options.table_structure_options.mode = TableFormerMode.FAST if mode == "fast" else TableFormerMode.ACCURATE
                        converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
                        # warm-up is not done: the first page includes model loading; it is flagged in the record
                        record["first_call"] = True
                    start = time.perf_counter()
                    result = converter.convert(str(RAW / entry["pdf"]), page_range=(entry["page"], entry["page"]))
                    record["seconds"] = time.perf_counter() - start
                    record["tables"] = docling_tables_from_document(result.document, {entry["page"]}).get(entry["page"], [])
            except Exception as failure:  # noqa: BLE001 - recorded per page, never stops the run
                record.update(status="failed", error=f"{type(failure).__name__}: {str(failure)[:300]}", tables=[])
            _emit(handle, record)


def worker_pdfplumber(entries: list[dict], strategy: str, out_path: Path) -> None:
    import pdfplumber
    settings = {"vertical_strategy": strategy, "horizontal_strategy": strategy}
    docs: dict[str, object] = {}
    with out_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            record = {"pdf": entry["pdf"], "page": entry["page"], "status": "ok", "seconds": None, "tables": []}
            try:
                if entry["pdf"] not in docs:
                    docs[entry["pdf"]] = pdfplumber.open(str(RAW / entry["pdf"]))
                start = time.perf_counter()
                page = docs[entry["pdf"]].pages[entry["page"] - 1]
                tables = [{"bbox": [float(x) for x in t.bbox], "grid": clean_cells(t.extract())} for t in page.find_tables(table_settings=settings)]
                record["seconds"] = time.perf_counter() - start
                record["tables"] = tables
            except Exception as failure:  # noqa: BLE001
                record.update(status="failed", error=f"{type(failure).__name__}: {str(failure)[:300]}")
            _emit(handle, record)


def worker_camelot(entries: list[dict], flavor: str, out_path: Path) -> None:
    import camelot
    import pypdfium2
    heights: dict[str, object] = {}
    with out_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            record = {"pdf": entry["pdf"], "page": entry["page"], "status": "ok", "seconds": None, "tables": []}
            try:
                if entry["pdf"] not in heights:
                    heights[entry["pdf"]] = pypdfium2.PdfDocument(str(RAW / entry["pdf"]))
                height = heights[entry["pdf"]][entry["page"] - 1].get_height()
                start = time.perf_counter()
                result = camelot.read_pdf(str(RAW / entry["pdf"]), pages=str(entry["page"]), flavor=flavor)
                tables = []
                for table in result:
                    x1, y1, x2, y2 = table._bbox  # PDF coordinates, origin bottom-left
                    tables.append({"bbox": [x1, height - y2, x2, height - y1], "grid": clean_cells(table.df.values.tolist())})
                record["seconds"] = time.perf_counter() - start
                record["tables"] = tables
            except Exception as failure:  # noqa: BLE001
                record.update(status="failed", error=f"{type(failure).__name__}: {str(failure)[:300]}")
            _emit(handle, record)


def worker_pymupdf(entries: list[dict], strategy: str, out_path: Path) -> None:
    import fitz
    docs: dict[str, object] = {}
    with out_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            record = {"pdf": entry["pdf"], "page": entry["page"], "status": "ok", "seconds": None, "tables": []}
            try:
                if entry["pdf"] not in docs:
                    docs[entry["pdf"]] = fitz.open(str(RAW / entry["pdf"]))
                start = time.perf_counter()
                page = docs[entry["pdf"]][entry["page"] - 1]
                tables = []
                for table in page.find_tables(strategy=strategy).tables:
                    box = fitz.Rect(table.bbox) * page.rotation_matrix if page.rotation else fitz.Rect(table.bbox)
                    tables.append({"bbox": [box.x0, box.y0, box.x1, box.y1], "grid": clean_cells(table.extract())})
                record["seconds"] = time.perf_counter() - start
                record["tables"] = tables
            except Exception as failure:  # noqa: BLE001
                record.update(status="failed", error=f"{type(failure).__name__}: {str(failure)[:300]}")
            _emit(handle, record)


def worker_main(args) -> int:
    entries = json.loads(Path(args.pages_file).read_text(encoding="utf-8"))
    out_path = Path(args.out)
    name = args.candidate
    if name.startswith("C1"):
        worker_docling(entries, "fast", out_path)
    elif name.startswith("C2"):
        worker_docling(entries, "accurate", out_path)
    elif name == "C3a_pdfplumber_lines":
        worker_pdfplumber(entries, "lines", out_path)
    elif name == "C3b_pdfplumber_text":
        worker_pdfplumber(entries, "text", out_path)
    elif name == "C4a_camelot_lattice":
        worker_camelot(entries, "lattice", out_path)
    elif name == "C4b_camelot_stream":
        worker_camelot(entries, "stream", out_path)
    elif name == "C5a_pymupdf_lines":
        worker_pymupdf(entries, "lines", out_path)
    elif name == "C5b_pymupdf_text":
        worker_pymupdf(entries, "text", out_path)
    else:
        raise SystemExit(f"unknown candidate {name}")
    return 0


# ------------------------------------------------------------------------------------------------ orchestration

def sample_every(entries: list[dict], limit: int) -> list[dict]:
    """Deterministic evenly spaced sample of at most ``limit`` entries (sorted input)."""
    if len(entries) <= limit:
        return list(entries)
    step = len(entries) / limit
    return [entries[int(i * step)] for i in range(limit)]


def dataset_pages(manifest: dict, dataset: str) -> list[dict]:
    return sorted(manifest["datasets"][dataset]["pages"], key=lambda p: (p["pdf"], p["page"]))


def run_pages_for(manifest: dict, candidate: str, dataset: str) -> tuple[list[dict], dict | None]:
    pages = dataset_pages(manifest, dataset)
    limit = None
    cfg = load_config()
    if candidate == "C2_docling_accurate" and dataset in cfg["accurate_sample_pages"]:
        cap = cfg["accurate_sample_pages"][dataset]
        if len(pages) > cap:
            limit = {"pages_run": cap, "pages_total": len(pages), "rule": "evenly spaced deterministic sample"}
            pages = sample_every(pages, cap)
    return pages, limit


def sample_memory(process, interval: float, box: dict, stop: threading.Event) -> None:
    import psutil
    peak = 0
    while not stop.is_set():
        try:
            total = process.memory_info().rss + sum(c.memory_info().rss for c in process.children(recursive=True))
            peak = max(peak, total)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        stop.wait(interval)
    box["peak_rss_mb"] = round(peak / 2**20, 1)


def run_worker(candidate: str, dataset: str, pages: list[dict], cfg: dict, suffix: str = "") -> dict:
    import psutil
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{candidate}__{dataset}{suffix}"
    pages_file, out_file = OUT_DIR / "work" / f"{stem}.pages.json", OUT_DIR / "work" / f"{stem}.jsonl"
    pages_file.parent.mkdir(parents=True, exist_ok=True)
    pages_file.write_text(json.dumps([{"pdf": p["pdf"], "page": p["page"], "cache": p.get("cache")} for p in pages]), encoding="utf-8")
    python = VENVS[CANDIDATES[candidate]["venv"]]
    command = [str(python), str(Path(__file__).resolve()), "worker", "--candidate", candidate, "--pages-file", str(pages_file), "--out", str(out_file)]
    env = {**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ROOT / "src")}
    log_path = OUT_DIR / "work" / f"{stem}.log"
    box: dict = {}
    stop = threading.Event()
    start = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        process = psutil.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT), env=env)
        sampler = threading.Thread(target=sample_memory, args=(process, cfg["memory_sample_interval_seconds"], box, stop), daemon=True)
        sampler.start()
        timed_out = False
        try:
            process.wait(timeout=cfg["timeout_seconds_per_run"])
        except psutil.TimeoutExpired:
            timed_out = True
            for child in process.children(recursive=True):
                child.kill()
            process.kill()
        stop.set()
        sampler.join()
    wall = time.perf_counter() - start
    records = [json.loads(line) for line in out_file.read_text(encoding="utf-8").splitlines() if line.strip()] if out_file.exists() else []
    done = {(r["pdf"], r["page"]) for r in records}
    for p in pages:  # pages never reached (timeout / crash) become FAILED with the reason
        if (p["pdf"], p["page"]) not in done:
            reason = "timeout" if timed_out else f"worker exit code {process.returncode}"
            records.append({"pdf": p["pdf"], "page": p["page"], "status": "failed", "error": reason, "seconds": None, "tables": []})
    return {"candidate": candidate, "dataset": dataset, "wall_seconds": round(wall, 1), "peak_rss_mb": box.get("peak_rss_mb"),
            "timed_out": timed_out, "exit_code": process.returncode, "log": log_path.relative_to(ROOT).as_posix(), "records": records}


def c6_records(manifest: dict, dataset: str) -> dict:
    """A-107 output (Round 2 release): operations tables as extraction records. No Docling or PDF is read."""
    tables = [json.loads(l) for l in (RELEASE_R2 / "tables.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    files = {f["file_id"]: f["original_name"] for f in (json.loads(l) for l in (RELEASE_R2 / "files.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
    by_page: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    for table in tables:
        head = " ".join(" ".join(row) for row in table["grid"][:2])
        if "Operations Description" in head or "Non-Prod" in head or "Operations Summary" in head:  # same notion as is_operations
            by_page[(files[table["file_id"]], table["pages"][0])].append(
                {"bbox": table["regions"][0]["bbox"], "grid": table["grid"], "table_id": table["table_id"]})
    records = [{"pdf": p["pdf"], "page": p["page"], "status": "ok", "seconds": None, "tables": by_page.get((p["pdf"], p["page"]), [])}
               for p in dataset_pages(manifest, dataset)]
    return {"candidate": "C6_custom_ops", "dataset": dataset, "wall_seconds": None, "peak_rss_mb": None, "timed_out": False,
            "exit_code": 0, "log": None, "records": records, "source": "A-107 Round 2 release tables.jsonl (read-only)"}


def save_result(result: dict, limit: dict | None) -> Path:
    result = dict(result, limit=limit)
    path = OUT_DIR / f"{result['candidate']}__{result['dataset']}.json"
    path.write_text(json.dumps(result, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_manifest() -> dict:
    return json.loads((OUT_DIR / "manifest.json").read_text(encoding="utf-8"))


def command_manifest(_args) -> int:
    cfg = load_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(cfg)
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, data in manifest["datasets"].items():
        print(name, "items", len(data.get("items", [])), "pages", len(data["pages"]))
    return 0


def command_run(args) -> int:
    cfg = load_config()
    manifest = load_manifest()
    names = args.only or list(CANDIDATES)
    for dataset in args.datasets or ALL_DATASETS:
        for candidate in names:
            if candidate == "C6_custom_ops":
                if dataset in ("D1", "D2"):
                    save_result(c6_records(manifest, dataset), None)
                    print(f"{candidate} {dataset}: from release")
                continue
            pages, limit = run_pages_for(manifest, candidate, dataset)
            result = run_worker(candidate, dataset, pages, cfg)
            save_result(result, limit)
            failed = sum(1 for r in result["records"] if r["status"] != "ok")
            print(f"{candidate} {dataset}: pages {len(pages)} failed {failed} wall {result['wall_seconds']}s peak {result['peak_rss_mb']} MB", flush=True)
    return 0


def tables_hash(records: list[dict]) -> str:
    return canonical_hash([[r["pdf"], r["page"], r["status"], [[[round(v, 2) for v in t["bbox"]], t["grid"]] for t in r["tables"]]]
                           for r in sorted(records, key=lambda r: (r["pdf"], r["page"]))])


def command_determinism(args) -> int:
    cfg = load_config()
    manifest = load_manifest()
    dataset = cfg["determinism_dataset"]
    report = {}
    for candidate in args.only or [c for c in CANDIDATES if c != "C6_custom_ops"]:
        first = json.loads((OUT_DIR / f"{candidate}__{dataset}.json").read_text(encoding="utf-8"))
        pages, _ = run_pages_for(manifest, candidate, dataset)
        if candidate.startswith("C1"):  # the first run used the cache for cached documents; repeat with fresh conversion would change the question
            pages = [dict(p, cache=p.get("cache")) for p in pages]
        second = run_worker(candidate, dataset, pages, cfg, suffix=".repeat")
        a, b = tables_hash(first["records"]), tables_hash(second["records"])
        report[candidate] = {"dataset": dataset, "pages": len(pages), "hash_run1": a, "hash_run2": b, "identical": a == b}
        print(candidate, "identical" if a == b else "DIFFERENT", flush=True)
    (OUT_DIR / "determinism.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


# ------------------------------------------------------------------------------------------------ scoring

def load_results(candidate: str, dataset: str) -> dict | None:
    path = OUT_DIR / f"{candidate}__{dataset}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def index_records(result: dict) -> dict[tuple[str, int], dict]:
    return {(r["pdf"], r["page"]): r for r in result["records"]}


def pair_score_fn(item: dict, rule: str):
    """Score function of a truth item against a predicted table: bbox IoU, or token F1 when no usable bbox."""
    truth_tokens = grid_tokens(item["grid"])

    def score(pred: dict) -> float:
        if rule == "iou":
            return iou(item["bbox"], pred["bbox"])
        return f1_from_counters(truth_tokens, grid_tokens(pred["grid"]))["f1"] or 0.0
    return score


def score_items(candidate: str, dataset: str, manifest: dict, result: dict, cfg: dict) -> dict:
    caps = CANDIDATES[candidate]
    items = manifest["datasets"][dataset]["items"]
    records = index_records(result)
    by_page: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    for item in items:
        by_page[(item["pdf"], item["page"])].append(item)
    status_count: collections.Counter = collections.Counter()
    reasons: collections.Counter = collections.Counter()
    rows, extras, extras_pages = [], 0, 0
    offsets = tuple(cfg["leading_row_offsets_d2"]) if dataset == "D2" else (0,)
    limited = {(p["pdf"], p["page"]) for p in run_pages_for(manifest, candidate, dataset)[0]} if candidate != "C6_custom_ops" else None
    for key, page_items in sorted(by_page.items()):
        record = records.get(key)
        page_items = sorted(page_items, key=lambda i: i["id"])
        verdicts = [applicability(caps, i) for i in page_items]
        if limited is not None and key not in limited:
            for item in page_items:
                status_count["NOT_RUN_LIMIT"] += 1
            continue
        if record is None or record["status"] != "ok":
            for item, (state, why) in zip(page_items, verdicts):
                if state == "NOT_APPLICABLE":
                    status_count["NOT_APPLICABLE"] += 1
                    reasons[why] += 1
                else:
                    status_count["FAILED"] += 1
                    reasons["FAILED: " + (record or {}).get("error", "no record")[:80]] += 1
            continue
        evaluated = [(i, item) for i, (item, (state, _)) in enumerate(zip(page_items, verdicts)) if state == "EVALUATED"]
        for item, (state, why) in zip(page_items, verdicts):
            if state == "NOT_APPLICABLE":
                status_count["NOT_APPLICABLE"] += 1
                reasons[why] += 1
        preds = record["tables"]
        truths = []
        for _, item in evaluated:
            rule = "iou" if (item.get("bbox") and not item.get("rotation")) else "tokens"
            threshold = cfg["iou_match"] if rule == "iou" else cfg["token_f1_match"]
            truths.append({"_score": pair_score_fn(item, rule), "item": item, "threshold": threshold, "rule": rule})
        # matching is done per rule group so that each truth uses its own threshold
        matched: dict[int, tuple[int, float]] = {}
        taken: set[int] = set()
        for rule in ("iou", "tokens"):
            group = [(n, t) for n, t in enumerate(truths) if t["rule"] == rule]
            if not group:
                continue
            avail = [(j, p) for j, p in enumerate(preds) if j not in taken]
            pairs = match_tables([t for _, t in group], [p for _, p in avail], group[0][1]["threshold"])
            for gi, pj, score in pairs:
                matched[group[gi][0]] = (avail[pj][0], score)
                taken.add(avail[pj][0])
        for n, truth in enumerate(truths):
            item = truth["item"]
            status_count["EVALUATED"] += 1
            row = {"id": item["id"], "format": item["format"], "match_rule": truth["rule"], "detected": n in matched,
                   "truth_rows": len([s for s in row_text_sequences(item["grid"])[1:] if s]) if dataset == "D2" else 0}
            if n in matched:
                pred = preds[matched[n][0]]
                row["match_score"] = round(matched[n][1], 4)
                if item["format"] == "form_fields":
                    values = Counter_values(item["grid"])
                    row["value_recall"] = f1_from_counters(values, grid_tokens(pred["grid"]))["recall"]
                    row["structure"] = "NOT_APPLICABLE (gold is block/field/value, not a grid)"
                else:
                    row["scores"] = grid_scores(item["grid"], pred["grid"], item["header_rows"], offsets)
                    if dataset == "D2":
                        truth_rows = [s for s in row_text_sequences(item["grid"])[1:] if s]
                        row["row_text"] = {"truth_rows": len(truth_rows), "exact": row_text_exact(truth_rows, pred["grid"])}
            if n not in matched and truth["rule"] == "tokens" and dataset == "D2":
                row["contained_in_larger_table"] = contained_in_some_table(item["grid"], preds, cfg["containment_char_recall"])
            rows.append(row)
        extras += sum(1 for j in range(len(preds)) if j not in taken)
        extras_pages += 1 if any(j not in taken for j in range(len(preds))) else 0
    return {"status_counts": dict(status_count), "not_applicable_reasons": dict(reasons), "rows": rows,
            "unlabelled_extra_tables": extras, "pages_with_unlabelled_extra": extras_pages, "summary": summarize_rows(rows, dataset)}


def char_counter(grid) -> collections.Counter:
    """Multiset of non-space characters of all cells (insensitive to spacing and tokenisation)."""
    counter: collections.Counter = collections.Counter()
    for row in clean_grid(grid):
        for cell in row:
            counter.update(cell.replace(" ", ""))
    return counter


def contained_in_some_table(truth_grid, preds: list[dict], threshold: float) -> bool:
    """True when one predicted table holds >= threshold of the truth characters (found, but not isolated as its own table)."""
    truth = char_counter(truth_grid)
    total = sum(truth.values())
    return bool(total) and any(sum((truth & char_counter(p["grid"])).values()) / total >= threshold for p in preds)


def Counter_values(grid) -> collections.Counter:
    """Value tokens of a block/field/value gold CSV (third column, header row skipped)."""
    counter: collections.Counter = collections.Counter()
    for row in grid[1:]:
        if len(row) >= 3:
            counter.update(normalize_text(row[2]).split())
    return counter


def ratio(num, den):
    return round(num / den, 4) if den else None


def summarize_rows(rows: list[dict], dataset: str) -> dict:
    n = len(rows)
    detected = [r for r in rows if r["detected"]]
    grids = [r for r in detected if "scores" in r]
    s = [r["scores"] for r in grids]
    total = lambda key: sum(x[key] for x in s)  # noqa: E731
    headers = [x["header_ok"] for x in s if x["header_ok"] is not None]
    out = {"items_evaluated": n, "tp": len(detected), "fn": n - len(detected), "recall": ratio(len(detected), n),
           "missed_but_contained_in_larger_table": sum(1 for r in rows if r.get("contained_in_larger_table")),
           "grid_items_matched": len(grids),
           "row_count_exact": [sum(x["row_exact"] for x in s), len(s)], "col_count_exact": [sum(x["col_exact"] for x in s), len(s)],
           "row_count_within_1": [sum(x["row_within_1"] for x in s), len(s)],
           "header_ok": [sum(headers), len(headers)],
           "cell_positional_exact": [total("positional_cells"), total("truth_cells")] if s else [0, 0],
           "cell_set_recall": [total("set_hits"), total("truth_cells")] if s else [0, 0],
           "cell_set_precision": [total("set_hits"), total("pred_cells")] if s else [0, 0],
           "cell_set_recall_ignoring_spaces": [total("set_hits_nospace"), total("truth_cells")] if s else [0, 0],
           "token_f1_mean_over_matched": round(statistics.fmean(x["token_f1"] or 0.0 for x in s), 4) if s else None}
    all_grid_items = [r for r in rows if r["format"] != "form_fields"]
    out["token_f1_mean_missed_as_zero"] = round(statistics.fmean((r["scores"]["token_f1"] or 0.0) if "scores" in r else 0.0 for r in all_grid_items), 4) if all_grid_items else None
    forms = [r for r in rows if r["format"] == "form_fields"]
    if forms:
        out["form_items"] = {"evaluated": len(forms), "detected": sum(r["detected"] for r in forms),
                             "value_recall_mean": round(statistics.fmean(r.get("value_recall") or 0.0 for r in forms), 4)}
    if dataset == "D2":
        out["rows_text_exact"] = [sum(r["row_text"]["exact"] for r in rows if "row_text" in r), sum(r["truth_rows"] for r in rows)]
    return out


def timing_summary(results: list[dict]) -> dict:
    seconds = [r["seconds"] for res in results for r in res["records"] if r.get("seconds") is not None and not r.get("first_call")]
    first = [r["seconds"] for res in results for r in res["records"] if r.get("first_call") and r.get("seconds") is not None]
    peaks = [res["peak_rss_mb"] for res in results if res.get("peak_rss_mb") is not None]
    return {"pages_timed": len(seconds), "median_s_per_page": round(statistics.median(seconds), 4) if seconds else None,
            "p95_s_per_page": round(percentile(seconds, 0.95), 4) if seconds else None,
            "first_call_s_includes_model_load": first[0] if first else None, "peak_rss_mb_max": max(peaks) if peaks else None}


def score_negative(candidate: str, dataset: str, manifest: dict, result: dict, review: dict | None) -> dict:
    caps = CANDIDATES[candidate]
    pages = manifest["datasets"][dataset]["pages"]
    records = index_records(result)
    limited = {(p["pdf"], p["page"]) for p in run_pages_for(manifest, candidate, dataset)[0]}
    counts: collections.Counter = collections.Counter()
    flagged = []
    tables_total = 0
    for p in pages:
        key = (p["pdf"], p["page"])
        if key not in limited:
            counts["NOT_RUN_LIMIT"] += 1
            continue
        if caps["domain"] == "ops" or (caps["text_layer_only"] and p["text_chars"] <= 0):
            counts["NOT_APPLICABLE"] += 1
            continue
        r = records.get(key)
        if r is None or r["status"] != "ok":
            counts["FAILED"] += 1
            continue
        counts["EVALUATED"] += 1
        if r["tables"]:
            tables_total += len(r["tables"])
            flagged.append({"pdf": p["pdf"], "page": p["page"], "tables": len(r["tables"])})
    n = counts["EVALUATED"]
    out = {"status_counts": dict(counts), "pages_with_tables": len(flagged), "tables_predicted": tables_total,
           "tables_per_100_pages_raw": round(100 * tables_total / n, 2) if n else None,
           "pages_flagged_per_100_pages_raw": round(100 * len(flagged) / n, 2) if n else None, "flagged_pages": flagged}
    if review:
        real = {(x["pdf"], x["page"]): x["real_table"] for x in review["pages"]}
        reviewed = [f for f in flagged if (f["pdf"], f["page"]) in real]
        real_n = sum(real[(f["pdf"], f["page"])] for f in reviewed)
        fp_n = len(reviewed) - real_n
        unreviewed = len(flagged) - len(reviewed)
        out["after_review_of_flagged_pages"] = {
            "flagged_pages": len(flagged), "reviewed": len(reviewed), "reviewed_real_table": real_n, "reviewed_false_positive": fp_n,
            "flagged_not_reviewed": unreviewed,
            "false_positive_pages_per_100_lower_bound": round(100 * fp_n / n, 2) if n else None,
            "false_positive_pages_per_100_upper_bound": round(100 * (fp_n + unreviewed) / n, 2) if n else None}
    return out


def score_agreement(manifest: dict, dataset: str) -> dict:
    """D4: detection agreement between candidates (page level) and with Docling fast (table level, IoU). Not truth."""
    pages = manifest["datasets"][dataset]["pages"]
    detect: dict[str, dict] = {}
    for candidate in CANDIDATES:
        res = load_results(candidate, dataset)
        if not res:
            continue
        limited = {(p["pdf"], p["page"]) for p in run_pages_for(manifest, candidate, dataset)[0]}
        rec = index_records(res)
        detect[candidate] = {k: bool(rec[k]["tables"]) for k in limited if k in rec and rec[k]["status"] == "ok"}
    out = {"pages": len(pages), "per_candidate": {}, "pairwise_page_agreement": {}}
    for c, d in detect.items():
        out["per_candidate"][c] = {"pages_evaluated": len(d), "pages_with_table": sum(d.values()),
                                   "tables_total": sum(len(index_records(load_results(c, dataset))[k]["tables"]) for k in d)}
    names = sorted(detect)
    for a in names:
        for b in names:
            if a < b:
                shared = sorted(set(detect[a]) & set(detect[b]))
                if shared:
                    agree = sum(detect[a][k] == detect[b][k] for k in shared)
                    out["pairwise_page_agreement"][f"{a} vs {b}"] = [agree, len(shared)]
    ref = load_results("C1_docling_fast", dataset)
    if ref:
        ref_rec = index_records(ref)
        out["table_iou_vs_docling_fast"] = {}
        for c in names:
            if c == "C1_docling_fast":
                continue
            rec = index_records(load_results(c, dataset))
            hit = total_ref = 0
            for k in detect[c]:
                if k not in ref_rec or ref_rec[k]["status"] != "ok":
                    continue
                refs = ref_rec[k]["tables"]
                total_ref += len(refs)
                items = [{"_score": (lambda t: lambda p: iou(t["bbox"], p["bbox"]))(t)} for t in refs]
                hit += len(match_tables(items, rec[k]["tables"], 0.5))
            out["table_iou_vs_docling_fast"][c] = [hit, total_ref]
    return out


def command_score(_args) -> int:
    cfg = load_config()
    manifest = load_manifest()
    review_path = OUT_DIR / "d3_review.json"
    review = json.loads(review_path.read_text(encoding="utf-8")) if review_path.exists() else None
    scores: dict = {"datasets": {}, "capabilities": CANDIDATES, "labels": DATASET_LABELS}
    for dataset in ("D1", "D2"):
        scores["datasets"][dataset] = {}
        for candidate in CANDIDATES:
            result = load_results(candidate, dataset)
            if result is None:
                scores["datasets"][dataset][candidate] = {"status": "NOT_RUN"}
                continue
            entry = score_items(candidate, dataset, manifest, result, cfg)
            entry["limit"] = result.get("limit")
            entry["timing"] = timing_summary([result])
            scores["datasets"][dataset][candidate] = entry
    scores["datasets"]["D3"] = {}
    for candidate in CANDIDATES:
        result = load_results(candidate, "D3")
        if result is None:
            scores["datasets"]["D3"][candidate] = {"status": "NOT_APPLICABLE" if candidate == "C6_custom_ops" else "NOT_RUN"}
            continue
        entry = score_negative(candidate, "D3", manifest, result, review)
        entry["timing"] = timing_summary([result])
        entry["limit"] = result.get("limit")
        scores["datasets"]["D3"][candidate] = entry
    scores["datasets"]["D4"] = score_agreement(manifest, "D4")
    scores["datasets"]["D4"]["timing"] = {c: timing_summary([r]) for c in CANDIDATES if (r := load_results(c, "D4"))}
    # overall timing per candidate across datasets (fresh runs only; cached Docling pages carry no timing)
    scores["timing_all_datasets"] = {c: timing_summary([r for d in ALL_DATASETS if (r := load_results(c, d))]) for c in CANDIDATES}
    scores["determinism"] = json.loads((OUT_DIR / "determinism.json").read_text(encoding="utf-8")) if (OUT_DIR / "determinism.json").exists() else None
    scores["manifest_summary"] = {d: {"items": len(v.get("items", [])), "pages": len(v["pages"])} for d, v in manifest["datasets"].items()}
    (OUT_DIR / "scores.json").write_text(json.dumps(scores, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"written {OUT_DIR / 'scores.json'}")
    return 0


def flagged_pages(manifest: dict, dataset: str, only=None) -> dict[tuple[str, int], list[str]]:
    """Pages where at least one candidate predicted a table -> candidates that flagged it (sorted)."""
    flagged: dict[tuple[str, int], list[str]] = collections.defaultdict(list)
    for candidate in only or CANDIDATES:
        result = load_results(candidate, dataset)
        if not result:
            continue
        for record in result["records"]:
            if record["status"] == "ok" and record["tables"]:
                flagged[(record["pdf"], record["page"])].append(candidate)
    return {k: sorted(v) for k, v in flagged.items()}


def command_crops(args) -> int:
    """Contact sheets for manual review: page thumbnail + predicted boxes (one colour per candidate). Review aid only."""
    import cv2
    import fitz
    import numpy as np
    manifest = load_manifest()
    flagged = flagged_pages(manifest, args.dataset, args.candidates)
    keys = sorted(flagged, key=lambda k: stable_key("review", *k))[:args.limit]
    names = sorted(CANDIDATES)
    palette = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180), (70, 240, 240), (240, 50, 230), (128, 128, 0), (0, 0, 0)]
    results = {c: index_records(r) for c in CANDIDATES if (r := load_results(c, args.dataset))}
    tiles, legend = [], []
    for key in keys:
        with fitz.open(RAW / key[0]) as doc:
            page = doc[key[1] - 1]
            zoom = 520 / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
        for index, candidate in enumerate(names):
            record = results.get(candidate, {}).get(key)
            for table in (record or {}).get("tables", []):
                x0, y0, x1, y1 = (int(v * zoom) for v in table["bbox"])
                cv2.rectangle(image, (x0, y0), (x1, y1), palette[index], 2)
        label = f"{len(tiles) + 1}: {key[0][:28]} p{key[1]}"
        cv2.putText(image, label, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
        tiles.append(image)
        legend.append({"n": len(tiles), "pdf": key[0], "page": key[1], "flagged_by": flagged[key]})
    per_sheet = args.per_sheet
    OUT_DIR.joinpath("review").mkdir(exist_ok=True)
    for sheet, start in enumerate(range(0, len(tiles), per_sheet)):
        chunk = tiles[start:start + per_sheet]
        height = max(t.shape[0] for t in chunk)
        row = [np.pad(t, ((0, height - t.shape[0]), (0, 4), (0, 0)), constant_values=255) for t in chunk]
        cv2.imwrite(str(OUT_DIR / "review" / f"{args.dataset}_sheet{sheet + 1}.png"), cv2.cvtColor(np.hstack(row), cv2.COLOR_RGB2BGR))
    (OUT_DIR / "review" / f"{args.dataset}_legend.json").write_text(json.dumps(
        {"colors": dict(zip(names, palette)), "pages": legend, "flagged_pages_total": len(flagged)}, indent=1, sort_keys=True), encoding="utf-8")
    print(f"{len(keys)} of {len(flagged)} flagged pages rendered")
    return 0


def command_all(args) -> int:
    for step, call in (("manifest", lambda: command_manifest(args)), ("run", lambda: command_run(args)),
                       ("determinism", lambda: command_determinism(args)), ("score", lambda: command_score(args))):
        print(f"== {step}", flush=True)
        if call():
            return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("manifest", "run", "determinism", "score", "all"):
        p = sub.add_parser(name)
        p.set_defaults(only=None, datasets=None)
        if name in ("run", "determinism", "all"):
            p.add_argument("--only", nargs="*")
        if name in ("run", "all"):
            p.add_argument("--datasets", nargs="*")
    c = sub.add_parser("crops")
    c.add_argument("--dataset", required=True)
    c.add_argument("--limit", type=int, default=8)
    c.add_argument("--candidates", nargs="*", help="restrict the flagged-page union to these candidates (review sample)")
    c.add_argument("--per-sheet", type=int, default=4)
    w = sub.add_parser("worker")
    w.add_argument("--candidate", required=True)
    w.add_argument("--pages-file", required=True)
    w.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    return {"manifest": command_manifest, "run": command_run, "determinism": command_determinism, "score": command_score,
            "all": command_all, "worker": worker_main, "crops": command_crops}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
