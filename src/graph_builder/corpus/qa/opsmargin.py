"""Mark-column margin check (A-401a): flag Operations Summary tables whose X marks sit unusually close to the Non-Prod column edge.

Problem: the table rebuild accepts an ``X`` token as the Non-Prod mark when its centre lies inside the span of the ``Non-Prod``
header word. In the known template every mark sits 0.597 em (centre) from the right edge, so a mark shifted by that distance
becomes description text and the table is still reported as validated.

What this check does: for every rebuilt table it measures, in em of the header label, how far each ``X`` centre lies inside the
mark column (negative = outside, but within a search window) and records how far description words reach toward the column (information only).
The margins of all tables of the release form the observed distribution (median and robust scale). A table is flagged
``OPS_MARGIN_NEEDS_VERIFICATION`` (WARN) when its smallest margin falls more than ``deviation_k`` scales below the median. The
scale has a floor (``scale_floor_em``), so the fixed offset of the template is never a dead zone: only deviation from it counts.

What it does not do: it does not prove a table correct. A table that is not flagged is only "not unusual relative to the other
tables of the same release". See LIMITATIONS and ``known_blind_spots``.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any

from .fidelity import FidelityState, iter_jsonl
from .signals import CheckContext, Registry

CHECK_NAME = "ops_margin"
CHECK_VERSION = "1"
DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "configs" / "qa" / "ops_margin.json"

REASONS = (
    ("OPS_MARGIN_NEEDS_VERIFICATION", "WARN", "A mark or description margin of this Operations table deviates from the distribution of the release; the column assignment needs verification.", CHECK_NAME),
    ("OPS_MARGIN_NO_REFERENCE", "INFO", "The margin could not be measured (PDF not found, page rotated, header label or table box missing, or too few values in the release).", CHECK_NAME),
)
LIMITATIONS = (
    "Judges a table only against the other tables of the same release: a release in which every table is shifted the same way is not detected.",
    "Reads the same PDF text layer as the table rebuild (same PDFium glyph source); an error in the text layer itself is invisible.",
    "A mark that moved farther than mark_window_em from the column, or an X glyph replaced by another token, is not seen as a mark.",
    "A table passes when its margins are typical; passing is not evidence that the cell content is correct.",
    "Parameters are proposals set on one document family; behaviour on other report templates is NOT EVALUATED.",
)


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or DEFAULT_CONFIG).read_text(encoding="utf-8"))


def _value(config: dict, section: str, name: str) -> Any:
    return config[section][name]["value"]


def _centre(box: list[float]) -> float:
    return (box[0] + box[2]) / 2


def measure_table(words: list[dict], box: list[float], config: dict) -> dict:
    """Margins (em of the header label) of one table; ``words`` are layer words, ``box`` the table box [x0, top, x1, bottom].

    Returns {"status": "ok"|"no_label", "em", "x_margins_em": [...], "desc_gap_em": float|None}. Pure and deterministic."""
    slack = _value(config, "geometry", "band_slack_pt")
    label_text, glyph = _value(config, "geometry", "header_label"), _value(config, "geometry", "mark_glyph")
    ignored = set(_value(config, "geometry", "ignored_tokens"))
    band = [w for w in words if box[1] - slack <= (w["bbox"][1] + w["bbox"][3]) / 2 <= box[3] + slack
            and box[0] - slack <= _centre(w["bbox"]) <= box[2] + slack]
    labels = sorted((w for w in band if w["text"] == label_text), key=lambda w: (w["bbox"][1], w["bbox"][0]))
    if not labels:
        return {"status": "no_label", "em": None, "x_margins_em": [], "desc_gap_em": None}
    label = labels[0]["bbox"]
    em = label[3] - label[1]
    if em <= 0:
        return {"status": "no_label", "em": None, "x_margins_em": [], "desc_gap_em": None}
    left, right, window = label[0], label[2], _value(config, "thresholds", "mark_window_em") * em
    body = [w for w in band if w["bbox"][1] >= label[3] - 0.5 * em]
    margins, gaps = [], []
    for word in body:
        centre = _centre(word["bbox"])
        if word["text"] == glyph and left - window <= centre <= right + window:
            margins.append(round(min(centre - left, right - centre) / em, 4))  # < 0: the centre is outside the column
        elif word["text"] in ignored or word["text"] == label_text:
            continue
        elif centre < right + window:  # description word at or left of the column
            gaps.append(round((left - centre) / em, 4))  # < 0: the word centre lies in the column
    return {"status": "ok", "em": round(em, 3), "x_margins_em": sorted(margins), "desc_gap_em": min(gaps) if gaps else None}


def family_reference(values: list[float], config: dict) -> dict | None:
    """Median and robust scale (1.4826 x MAD, floored) of a family of margins; None when there are too few values."""
    if len(values) < _value(config, "thresholds", "min_family_values"):
        return None
    centre = median(values)
    mad = median(abs(v - centre) for v in values)
    scale = max(1.4826 * mad, _value(config, "thresholds", "scale_floor_em"))
    return {"median_em": round(centre, 4), "scale_em": round(scale, 4), "values": len(values)}


def judge_table(measure: dict, x_reference: dict | None, config: dict) -> list[tuple[str, dict]]:
    """(reason code, evidence) pairs for one table. WARN only; never a gate.

    Only the X-mark margin is judged. The description gap is recorded as information: in the known template description words
    legitimately run under the Non-Prod header (median gap about -1 em), so "close to the column" is normal there and a
    deviation test on it flagged 48/405 unchanged pages at design noise (A-401a iteration 1 measurement)."""
    if measure["status"] != "ok":
        return [("OPS_MARGIN_NO_REFERENCE", {"reason": measure["status"]})]
    k = _value(config, "thresholds", "deviation_k")
    values = measure["x_margins_em"]
    evidence: dict[str, Any] = {"em_pt": measure["em"], "deviation_k": k, "description_gap_em_info": measure["desc_gap_em"]}
    if not values:
        return []  # no mark in this table: nothing to judge (a mark that left the window is a documented blind spot)
    smallest = min(values)
    if x_reference is None:
        return [("OPS_MARGIN_NO_REFERENCE", {"reason": "family_too_small", "x_margin_em": smallest, **evidence})]
    deviation = (x_reference["median_em"] - smallest) / x_reference["scale_em"]
    evidence["x_mark"] = {"margin_em": smallest, "reference": x_reference, "deviation": round(deviation, 2),
                          "margins_em": values[:config["max_listed_values"]["value"]]}
    if deviation > k:
        return [("OPS_MARGIN_NEEDS_VERIFICATION", evidence)]
    return []


def judge_family(measures: dict[str, dict], config: dict) -> dict[str, list[tuple[str, dict]]]:
    """Judge every measured table against the distribution of all of them. ``measures``: table_id -> measure_table result."""
    ok = [m for m in measures.values() if m["status"] == "ok"]
    x_reference = family_reference([v for m in ok for v in m["x_margins_em"]], config)
    return {table_id: judge_table(m, x_reference, config) for table_id, m in sorted(measures.items())}

def operations_parts(release_dir: Path, config: dict) -> list[dict]:
    """Table parts of the release written by the Operations Summary rebuild: {table_id, file_id, page, bbox}. Streams tables.jsonl."""
    prefix = _value(config, "geometry", "source_ref_prefix")
    out = []
    for table in iter_jsonl(release_dir / "tables.jsonl"):
        parts = [p for p in table.get("parts", []) if str(p.get("source_ref", "")).startswith(prefix)]
        if parts:
            out.append({"table_id": table["table_id"], "file_id": table["file_id"],
                        "parts": [{"page": p["page"], "bbox": p["bbox"]} for p in parts]})
    return out


def measure_release(release_dir: Path, corpus_dir: Path | None, config: dict) -> dict[str, dict]:
    """table_id -> measure (status 'ok'/'no_label') or {'status': reason} when no measurement was possible. One PDF page at a time."""
    from graph_builder.corpus.text_layer import source_page
    state = FidelityState(release_dir, corpus_dir, config)
    results: dict[str, dict] = {}
    paths: dict[str, Path | None] = {}
    for table in sorted(operations_parts(release_dir, config), key=lambda t: (t["file_id"], t["table_id"])):
        file_id = table["file_id"]
        if file_id not in paths:
            paths[file_id] = state.locate_pdf(state.files[file_id])[0] if file_id in state.files else None
        if paths[file_id] is None:
            results[table["table_id"]] = {"status": "pdf_not_found"}
            continue
        merged = {"status": "ok", "em": None, "x_margins_em": [], "desc_gap_em": None}
        for part in table["parts"]:
            try:
                layer = source_page(paths[file_id], part["page"])
                if layer["rotation"] != 0:
                    merged = {"status": "rotated_page"}
                    break
                measure = measure_table(layer["words"], part["bbox"], config)
            except Exception as error:  # noqa: BLE001 - per-table isolation: an unreadable page is a missing reference
                merged = {"status": f"read_error_{type(error).__name__}"}
                break
            if measure["status"] != "ok":
                merged = measure
                break
            merged["em"] = measure["em"]
            merged["x_margins_em"] = sorted(merged["x_margins_em"] + measure["x_margins_em"])
            gaps = [g for g in (merged["desc_gap_em"], measure["desc_gap_em"]) if g is not None]
            merged["desc_gap_em"] = min(gaps) if gaps else None
        results[table["table_id"]] = merged
    return results


def register_ops_margin(registry: Registry, corpus_dir: Path | None = None, config_path: Path | None = None) -> Registry:
    """Add the table-scope check. The family distribution is computed lazily on the first table of a release."""
    config = load_config(config_path)
    holder: dict[str, Any] = {}
    for code, severity, meaning, emitter in REASONS:
        registry.register_reason(code, severity, meaning, emitter)

    def check(context: CheckContext, entity: dict) -> list[dict]:
        key = str(context.release_dir)
        if holder.get("key") != key:
            measures = measure_release(Path(context.release_dir), corpus_dir, config)
            holder.update(key=key, measures=measures, verdicts=judge_family(
                {t: m for t, m in measures.items() if m.get("status") in ("ok", "no_label")}, config))
        table_id = entity["ids"].get("table_id")
        if table_id in holder["verdicts"]:
            return [registry.signal(code, "table", entity["ids"], evidence=evidence) for code, evidence in holder["verdicts"][table_id]]
        measure = holder["measures"].get(table_id)
        if measure is None:
            return []  # not an Operations Summary table
        return [registry.signal("OPS_MARGIN_NO_REFERENCE", "table", entity["ids"], evidence={"reason": measure["status"]})]

    registry.register_check(CHECK_NAME, check, "table", CHECK_VERSION, limitations=LIMITATIONS)
    return registry
