"""Source-structure evidence for a table that may continue on the next page (A-446, evidence only: no pipeline change,
no joining, no LLM, no network).

    python scripts/qa_multipage_structure.py pairs --universe universe.json --release name=release_dir ... \
        [--keys keys.json] [--raw data/raw] [--out evidence.json]

For a pair of K1 table boxes (last table of page p, first table of page p+1) the PDF itself is read (PyMuPDF words and
drawn lines, display orientation) and these signals are reported: repeated header line, column rules at the same x
positions, numbering continuity (ranges such as 900-910 / 910-920, or an integer counter in the first column),
an explicit 'continued' marker, a page counter that is not the running footer, and whether the frame is open or closed
at the break. The decision STRUCTURE_SUPPORTS_CONTINUATION needs a layout match plus a continuity signal; a repeated
header alone never suffices (the same report title repeats on different days). The result is evidence for a human
reviewer and for the gold file, not a proof and never a trigger to join anything."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import qa_multipage_scan as scan  # noqa: E402  (same directory)

DEFAULT_CONFIG = ROOT / "configs" / "qa" / "multipage_structure.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for section, body in raw.items():
        if isinstance(body, dict):
            out[section] = {k: (v["value"] if isinstance(v, dict) and "value" in v else v) for k, v in body.items()}
    return out


# ---------------------------------------------------------------- pure helpers (unit tested)

def norm(text) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").split())


def inside(word, bbox, slack: float) -> bool:
    return (word[0] >= bbox[0] - slack and word[2] <= bbox[2] + slack
            and word[1] >= bbox[1] - slack and word[3] <= bbox[3] + slack)


def text_lines(words, bbox, cfg: dict) -> list:
    """Text lines inside bbox, top to bottom: [{y, x0, text, words}]. words are (x0, y0, x1, y1, text)."""
    cl = cfg["lines"]
    chosen = [w for w in words if inside(w, bbox, cl["bbox_slack_pt"]) and str(w[4]).strip()]
    if not chosen:
        return []
    heights = sorted(w[3] - w[1] for w in chosen)
    median_h = heights[len(heights) // 2] or 1.0
    lines: list = []
    for w in sorted(chosen, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        centre = (w[1] + w[3]) / 2
        if lines and abs(centre - lines[-1]["y"]) <= cl["line_tol_rel_height"] * median_h:
            lines[-1]["words"].append(w)
        else:
            lines.append({"y": centre, "words": [w]})
    for line in lines:
        line["words"].sort(key=lambda w: w[0])
        line["x0"] = line["words"][0][0]
        line["text"] = norm(" ".join(str(w[4]) for w in line["words"]))
    return lines


def header_repeated(lines_a: list, lines_b: list, width: float, cfg: dict) -> dict:
    """First body line of the later table found, at the same x, among the lines of the earlier table."""
    hr = cfg["header_repeat"]
    if not lines_b:
        return {"repeated": False, "reason": "no_text_in_b"}
    first = lines_b[0]
    if len(first["words"]) < hr["min_words"]:
        return {"repeated": False, "reason": "first_line_too_short", "line": first["text"]}
    tol = hr["x_tol_rel"] * max(width, 1e-6)
    for line in lines_a:
        if line["text"] == first["text"] and abs(line["x0"] - first["x0"]) <= tol:
            return {"repeated": True, "line": first["text"]}
    return {"repeated": False, "reason": "not_found_in_a", "line": first["text"]}


_RANGE = re.compile(r"^(\d+(?:\.\d+)?)\s*[-\u2013]\s*(\d+(?:\.\d+)?)(?=\D|$)")
_INT = re.compile(r"^\d+$")


def range_series(lines: list) -> list:
    """(start, end) of every line that starts with a numeric range 'a-b' with b > a."""
    out = []
    for line in lines:
        # a range may be split into words ('900-910-' or '900 - 910'): test the words of the line from left to right;
        # the first match counts (the depth ticks or notes of other columns can precede it on the same text line)
        texts = [str(w[4]) for w in line["words"]]
        for i in range(len(texts)):
            m = _RANGE.match(" ".join(texts[i:i + 3]).strip())
            if m and float(m.group(2)) > float(m.group(1)):
                out.append((float(m.group(1)), float(m.group(2))))
                break
    return out


def counter_series(lines: list, bbox, cfg: dict) -> list:
    limit = bbox[0] + cfg["numbering"]["counter_column_frac"] * max(bbox[2] - bbox[0], 1e-6)
    out = []
    for line in lines:
        first = line["words"][0]
        if _INT.match(str(first[4]).strip()) and first[0] <= limit:
            out.append(int(first[4]))
    return out


def numbering_continuity(lines_a: list, lines_b: list, bbox_a, bbox_b, cfg: dict) -> dict:
    n = cfg["numbering"]
    ra, rb = range_series(lines_a), range_series(lines_b)
    if len(ra) >= n["min_series_lines"] and len(rb) >= 1:
        ok = abs(rb[0][0] - ra[-1][1]) <= n["range_tolerance"]
        return {"kind": "range", "continuous": ok, "last_a": ra[-1][1], "first_b": rb[0][0],
                "restart": rb[0][0] <= ra[0][0] and not ok}
    ca, cb = counter_series(lines_a, bbox_a, cfg), counter_series(lines_b, bbox_b, cfg)
    if len(ca) >= n["min_series_lines"] and len(cb) >= 1:
        ok = cb[0] - ca[-1] == n["counter_step"]
        return {"kind": "counter", "continuous": ok, "last_a": ca[-1], "first_b": cb[0], "restart": cb[0] <= ca[0] and not ok}
    return {"kind": None, "continuous": None, "restart": False, "reason": "no_numbering_series"}


def vertical_rules(segments, bbox, cfg: dict) -> list:
    """x positions of vertical drawn segments inside bbox that are long enough. segments: (x0, y0, x1, y1)."""
    c = cfg["columns"]
    height = max(bbox[3] - bbox[1], 1e-6)
    slack = cfg["lines"]["bbox_slack_pt"]
    xs = []
    for s in segments:
        if abs(s[2] - s[0]) > 1.0:
            continue
        top, bottom = max(s[1], bbox[1]), min(s[3], bbox[3])
        x = (s[0] + s[2]) / 2
        if bottom - top >= c["min_rule_len_frac"] * height and bbox[0] - slack <= x <= bbox[2] + slack:
            xs.append(x)
    clusters: list = []
    for x in sorted(xs):
        if clusters and x - clusters[-1][-1] <= c["cluster_tol_pt"]:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [round(sum(g) / len(g), 2) for g in clusters]


def column_rules_match(rules_a: list, rules_b: list, width: float, cfg: dict) -> dict:
    if len(rules_a) < 2 or len(rules_b) < 2:
        return {"match": None, "reason": "no_column_rules", "count_a": len(rules_a), "count_b": len(rules_b)}
    if len(rules_a) != len(rules_b):
        return {"match": False, "reason": "count_differs", "count_a": len(rules_a), "count_b": len(rules_b)}
    delta = max(abs(x - y) for x, y in zip(rules_a, rules_b)) / max(width, 1e-6)
    return {"match": delta <= cfg["columns"]["rule_x_tol_rel"], "reason": "compared",
            "count_a": len(rules_a), "count_b": len(rules_b), "max_delta_rel": round(delta, 4)}


def horizontal_border(segments, bbox, edge: str, cfg: dict) -> bool:
    """Is there a horizontal drawn segment on the 'top' or 'bottom' edge of bbox spanning most of the width?"""
    need = cfg["borders"]["min_rule_width_frac"] * max(bbox[2] - bbox[0], 1e-6)
    slack = cfg["lines"]["bbox_slack_pt"]
    y_edge = bbox[1] if edge == "top" else bbox[3]
    for s in segments:
        if abs(s[3] - s[1]) > 1.0 or abs(((s[1] + s[3]) / 2) - y_edge) > slack:
            continue
        if min(s[2], bbox[2] + slack) - max(s[0], bbox[0] - slack) >= need:
            return True
    return False


def continued_marker(words, bbox, page_height: float, cfg: dict) -> dict:
    m = cfg["markers"]
    pattern = re.compile(m["continued_pattern"], re.I)
    strip = m["strip_frac"] * page_height
    zone = (bbox[0] - 5, bbox[1] - strip, bbox[2] + 5, bbox[3] + strip)
    for w in words:
        if inside(w, zone, 0.0) and pattern.search(str(w[4])):
            return {"found": True, "text": str(w[4])}
    return {"found": False}


def form_page_counter(words, pdf_pages: int, cfg: dict) -> dict | None:
    """'Page n of N' counters in the page text whose N differs from the PDF page count (the running footer is ignored)."""
    pattern = re.compile(cfg["page_counter"]["pattern"], re.I)
    lines = text_lines(words, (-1e9, -1e9, 1e9, 1e9), cfg)
    for line in lines:
        for m in pattern.finditer(line["text"]):
            if int(m.group(2)) != pdf_pages:
                return {"n": int(m.group(1)), "of": int(m.group(2))}
    return None


def decide(ev: dict) -> dict:
    """Decision from the evidence dict (see evaluate_structure). Returns {decision, reasons}."""
    reasons = []
    cols = ev["columns"]["match"]
    num = ev["numbering"]
    marker = ev["continued_marker"]["found"]
    open_break = ev["border"]["open_across_break"]
    continuity = bool(num.get("continuous")) or marker or open_break
    if cols is False or num.get("restart"):
        return {"decision": "STRUCTURE_CONFLICT",
                "reasons": (["columns_differ"] if cols is False else []) + (["numbering_restarts"] if num.get("restart") else [])}
    if cols and continuity and (ev["header"]["repeated"] or marker):
        if num.get("continuous"):
            reasons.append("numbering_continuous_" + str(num["kind"]))
        if marker:
            reasons.append("continued_marker")
        if open_break:
            reasons.append("frame_open_across_break")
        if ev["header"]["repeated"]:
            reasons.append("header_repeated")
        reasons.append("column_rules_match")
        return {"decision": "STRUCTURE_SUPPORTS_CONTINUATION", "reasons": reasons}
    if cols is None:
        reasons.append("no_column_rules")
    if not continuity:
        reasons.append("no_continuity_signal")
    if not ev["header"]["repeated"]:
        reasons.append("header_not_repeated")
    return {"decision": "UNDETERMINED", "reasons": reasons}


def evaluate_structure(a: dict, b: dict, cfg: dict) -> dict:
    """a, b: {bbox, words (display orientation), segments, page_height, pdf_pages}. Returns the evidence record."""
    lines_a = text_lines(a["words"], a["bbox"], cfg)
    lines_b = text_lines(b["words"], b["bbox"], cfg)
    width = max(a["bbox"][2] - a["bbox"][0], b["bbox"][2] - b["bbox"][0])
    rules_a = vertical_rules(a["segments"], a["bbox"], cfg)
    rules_b = vertical_rules(b["segments"], b["bbox"], cfg)
    closed_bottom = horizontal_border(a["segments"], a["bbox"], "bottom", cfg)
    closed_top = horizontal_border(b["segments"], b["bbox"], "top", cfg)
    counter_a = form_page_counter(a["words"], a["pdf_pages"], cfg)
    counter_b = form_page_counter(b["words"], b["pdf_pages"], cfg)
    columns = column_rules_match(rules_a, rules_b, width, cfg)
    columns["source"] = "drawn_rules"
    if columns["match"] is None:  # no drawn rules (borderless table or raster page): text-layer cell starts, if any
        scan_cfg = scan.load_config()
        starts = scan.column_starts_match(scan.column_starts(a["words"], a["bbox"], scan_cfg),
                                          scan.column_starts(b["words"], b["bbox"], scan_cfg), width, scan_cfg)
        columns = {"match": starts["match"], "reason": starts["reason"], "source": "text_layer_cell_starts",
                   "count_a": starts["count_a"], "count_b": starts["count_b"]}
    ev = {
        "header": header_repeated(lines_a, lines_b, width, cfg),
        "columns": columns,
        "numbering": numbering_continuity(lines_a, lines_b, a["bbox"], b["bbox"], cfg),
        "continued_marker": {"a": continued_marker(a["words"], a["bbox"], a["page_height"], cfg),
                             "b": continued_marker(b["words"], b["bbox"], b["page_height"], cfg)},
        "border": {"a_bottom_closed": closed_bottom, "b_top_closed": closed_top,
                   "open_across_break": (not closed_bottom) and (not closed_top),
                   "closed_per_page": closed_bottom and closed_top},
        "form_page_counter": {"a": counter_a, "b": counter_b,
                              "sequential": bool(counter_a and counter_b and counter_b["n"] == counter_a["n"] + 1
                                                 and counter_a["of"] == counter_b["of"])},
        "rules": [rules_a, rules_b],
    }
    ev["continued_marker"]["found"] = ev["continued_marker"]["a"]["found"] or ev["continued_marker"]["b"]["found"]
    ev.update(decide(ev))
    return ev


# ---------------------------------------------------------------- PDF access

def page_segments(page) -> list:
    """Axis-aligned drawn segments (x0, y0, x1, y1) in the displayed orientation: lines and the edges of rectangles."""
    matrix = tuple(page.rotation_matrix) if page.rotation else None
    out = []

    def add(x0, y0, x1, y1):
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        out.append(scan.to_display_rect(rect, matrix) if matrix else rect)

    for path in page.get_drawings():
        for item in path["items"]:
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) <= 1.0 or abs(p1.y - p2.y) <= 1.0:
                    add(p1.x, p1.y, p2.x, p2.y)
            elif kind == "re":
                r = item[1]
                if r.width <= 1.0 or r.height <= 1.0:
                    add(r.x0, r.y0, r.x1, r.y1)
                else:
                    add(r.x0, r.y0, r.x0, r.y1)
                    add(r.x1, r.y0, r.x1, r.y1)
                    add(r.x0, r.y0, r.x1, r.y0)
                    add(r.x0, r.y1, r.x1, r.y1)
    return out


def load_tables(releases: dict) -> dict:
    """table id -> {bbox, release}. Multi-region tables use '<id>#<n>' like qa_multipage_scan."""
    tables = {}
    for name, path in releases.items():
        data = scan.load_release(Path(path))
        for items in data["tables"].values():
            for t in items:
                tables[t["id"]] = {"bbox": t["bbox"], "release": name}
    return tables


def pairs_evidence(universe: dict, releases: dict, raw: Path, keys: list | None, cfg: dict) -> list:
    import pymupdf as fitz
    tables = load_tables(releases)
    pdf_for = {}
    for name, path in releases.items():
        files = {r["file_id"]: r for r in scan.iter_jsonl(Path(path) / "files.jsonl")}
        pdf_for.update({fid: p for fid, p in scan.find_pdfs(files, raw).items()})
    wanted = [p for p in universe["pairs"] if keys is None or p["key"] in keys]
    out = []
    cache: dict = {}
    for pair in wanted:
        record = {"key": pair["key"], "pdf": pair["pdf"], "pages": [pair["page_a"], pair["page_b"]],
                  "scanner_kind": pair["kind"], "rotation": pair["rotation"]}
        try:
            pdf = pdf_for[pair["file_id"]]
            with fitz.open(pdf) as doc:
                sides = []
                for table_id, page_number in ((pair["table_a"], pair["page_a"]), (pair["table_b"], pair["page_b"])):
                    ck = (str(pdf), page_number)
                    if ck not in cache:
                        words, height, _ = scan.page_words(doc, page_number - 1)
                        cache[ck] = (words, height, page_segments(doc[page_number - 1]))
                    words, height, segments = cache[ck]
                    sides.append({"bbox": tables[table_id]["bbox"], "words": words, "segments": segments,
                                  "page_height": height, "pdf_pages": len(doc)})
            record["evidence"] = evaluate_structure(sides[0], sides[1], cfg)
        except Exception as exc:  # per-pair isolation
            record["error"] = f"{type(exc).__name__}: {exc}"
        out.append(record)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pairs")
    p.add_argument("--universe", type=Path, required=True)
    p.add_argument("--release", action="append", required=True, help="name=release_dir")
    p.add_argument("--keys", type=Path, help="JSON list of pair keys (default: all pairs of the universe)")
    p.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    releases = dict(spec.split("=", 1) for spec in args.release)
    universe = json.loads(args.universe.read_text(encoding="utf-8"))
    keys = set(json.loads(args.keys.read_text(encoding="utf-8"))) if args.keys else None
    result = pairs_evidence(universe, releases, args.raw, keys, load_config(args.config))
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    from collections import Counter
    print(json.dumps(Counter(r.get("evidence", {}).get("decision", "ERROR") for r in result), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
