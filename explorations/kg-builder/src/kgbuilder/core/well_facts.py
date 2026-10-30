"""Strict span-backed annotations and shared deterministic well-fact scoring."""
from __future__ import annotations

import copy
import json
import math
import random
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from kgbuilder.core.config import ConfigError
from kgbuilder.core.text import cj, match_key, predicate_words
from kgbuilder.core.well_values import Quantity, RELATIONS, compare, hash_is_pressure, parse_quantity, parse_us_date


RELATION_SPEC = {
    'spudded_on': (frozenset(['Borehole']), frozenset(['date']), frozenset([])),
    'reached_td': (frozenset(['Borehole']), frozenset(['depth']), frozenset(['bound', 'correction'])),
    'drilled_to': (frozenset(['Borehole']), frozenset(['depth']), frozenset(['hole_size', 'bound'])),
    'set_casing_at': (frozenset(['Tubular']), frozenset(['depth']), frozenset(['correction', 'bound'])),
    'casing_size': (frozenset(['Tubular']), frozenset(['size']), frozenset([])),
    'casing_spec': (frozenset(['Tubular']), frozenset(['text']), frozenset([])),
    'cemented_interval': (frozenset(['Tubular', 'Annulus', 'Borehole']), frozenset(['depth', 'interval']), frozenset(['volume', 'toc'])),
    'set_plug_at': (frozenset(['Plug']), frozenset(['depth', 'interval']), frozenset(['action'])),
    'set_equipment_at': (frozenset(['Equipment']), frozenset(['depth']), frozenset(['action'])),
    'tagged_at': (frozenset(['Plug', 'Equipment', 'Fluid']), frozenset(['depth']), frozenset([])),
    'cut_at': (frozenset(['Tubular', 'Equipment']), frozenset(['depth']), frozenset(['bound'])),
    'tested_to_pressure': (frozenset(['Equipment', 'Tubular', 'Plug', 'Annulus', 'Borehole']), frozenset(['pressure']), frozenset(['test_kind', 'duration', 'result', 'stage'])),
    'fit_lot_emw': (frozenset(['Borehole']), frozenset(['density']), frozenset(['test_kind', 'at_depth'])),
    'perforated_interval': (frozenset(['Borehole', 'Tubular', 'Zone']), frozenset(['interval', 'depth']), frozenset(['zone', 'spf', 'gun_size'])),
    'has_mud_weight': (frozenset(['Borehole']), frozenset(['density']), frozenset([])),
    'completed_in': (frozenset(['Borehole']), frozenset(['entity']), frozenset([])),
    'encountered_marker': (frozenset(['Borehole']), frozenset(['entity']), frozenset(['at_depth'])),
    'has_well_status': (frozenset(['Borehole']), frozenset(['status']), frozenset([])),
    'used_rig': (frozenset(['Borehole']), frozenset(['entity']), frozenset([])),
    'operated_by': (frozenset(['Borehole']), frozenset(['entity']), frozenset([])),
    'pumped': (frozenset(['Fluid']), frozenset(['volume']), frozenset(['density', 'purpose'])),
}

ENTITY_TYPES = frozenset({"Borehole", "Tubular", "Plug", "Equipment", "Annulus", "Zone", "Rig", "Company", "Fluid"})
UNITS = {"depth": {"ft", "m", "unknown"}, "interval": {"ft", "m", "unknown"}, "pressure": {"psi", "unknown"},
         "density": {"ppg", "unknown"}, "size": {"in", "unknown"}, "volume": {"bbl", "sx", "cuft", "gal", "unknown"}}
REFERENCES = {"MD", "TVD", "BML", "AML", "unknown"}
DATUMS = {"KB", "SLM", "CTM", "WLM", "DPM", "ML", "unknown"}
NUMERIC = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
OBJECT_FIELDS = {"depth": {"value", "unit", "reference", "datum"}, "interval": {"lower", "upper", "unit", "reference", "datum"},
                 "date": {"iso", "precision"}, "status": {"value"}, "entity": {"type"}, "text": {"value"},
                 **{k: {"value", "unit"} for k in ("pressure", "density", "size", "volume")}}
ENUM_QUALIFIERS = {"bound": {"eq", "ge", "le", "approx"}, "result": {"good", "failed", "unknown"},
                   "stage": {"low", "high"}, "test_kind": {"bop_ram", "bop_annular", "bop", "casing", "tubing", "plug",
                   "annulus", "lubricator", "tree", "line", "fit", "lot", "other", "unknown"}}
SPAN_QUALIFIERS = {"at_depth": {"value", "unit", "reference", "datum"}, "duration": {"minutes"}, "spf": {"value"},
                   "density": {"value", "unit"}, "volume": {"value", "unit"}, "gun_size": {"value", "unit"},
                   "hole_size": set(), "zone": set(), "purpose": set()}


class AnnotationError(ValueError):
    """A fixed validation reason with its field path and optional date details."""
    def __init__(self, path: str, reason: str, detail: dict | None = None, extra: tuple = ()):
        super().__init__(reason)
        self.path, self.reason, self.detail, self.extra = path, reason, detail, extra


def _at(path, function, *args):
    try:
        return function(*args)
    except AnnotationError:
        raise
    except ValueError as exc:
        raise AnnotationError(path, str(exc)) from exc


def annotation_message(issue, locations_only=False):
    """Format diagnostics without disclosing arbitrary span or annotation text."""
    message = f"{issue['file']}:{issue['line']}: {issue['path']}"
    if locations_only:
        return message
    message += ": " + issue["reason"]
    detail = issue.get("detail")
    if detail:
        text = detail["text"]
        month_form = (r"(?:(?:early|mid|late)\s+)?(?:(?:january|february|march|april|may|june|july|august|"
                      r"september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
                      r"\.?\s+)?(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?\d{4}")
        safe = len(text) <= 40 and (re.fullmatch(r"[0-9/\-]+", text) or re.fullmatch(month_form, text, re.I))
        span = json.dumps(text) if safe else f"<span length {len(text)}>"
        def shown(value):
            # Malformed values are never allowed to disclose free annotation text.
            if value is None: return "null"
            if isinstance(value, str) and (value in {"day", "month", "year", "partial"} or re.fullmatch(r"[0-9-]+", value)):
                return value
            return "<invalid>"
        message += (f": span {span}; annotator iso={shown(detail['annotator']['iso'])} precision={shown(detail['annotator']['precision'])}"
                    f"; parser iso={shown(detail['parser']['iso'])} precision={shown(detail['parser']['precision'])}")
    return message


def _shape(row, required, optional=()):
    if not isinstance(row, dict) or not set(required) <= row.keys() or not row.keys() <= set(required) | set(optional):
        raise ValueError("invalid field shape")


def _number(value):
    if not isinstance(value, str) or not NUMERIC.fullmatch(value): raise ValueError("expected decimal string")


def _span(row, extras=(), optional=()):
    _shape(row, {"text", "occ", *extras}, {"start", "end", *optional})
    if not isinstance(row["text"], str) or not row["text"] or type(row["occ"]) is not int or row["occ"] < 0:
        raise ValueError("invalid span")
    for key in ("start", "end"):
        if key in row and (type(row[key]) is not int or row[key] < 0): raise ValueError("invalid span offset")


def _literal(row, kind, object_record=True):
    _span(row, OBJECT_FIELDS[kind] | ({"kind"} if object_record else set()))
    if kind in UNITS:
        if row["unit"] not in UNITS[kind]: raise ValueError("invalid unit")
        for key in (("lower", "upper") if kind == "interval" else ("value",)): _number(row[key])
        if kind == "interval" and Decimal(row["lower"]) > Decimal(row["upper"]): raise ValueError("reversed interval")
    if kind in {"depth", "interval"}:
        if row["reference"] not in REFERENCES or row["datum"] not in DATUMS: raise ValueError("invalid depth semantics")
    if kind == "date":
        iso, precision = parse_us_date(row["text"])
        if (row["iso"], row["precision"]) != (iso, precision):
            return {"text": row["text"], "annotator": {"iso": row["iso"], "precision": row["precision"]},
                    "parser": {"iso": iso, "precision": precision}}
    if kind == "entity" and row["type"] not in ENTITY_TYPES: raise ValueError("invalid entity type")
    if kind == "status" and row["value"] not in {"TA", "PA", "COM", "ST", "BP", "SI", "other"}: raise ValueError("invalid status")
    if kind == "text" and not isinstance(row["value"], str): raise ValueError("invalid text literal")


class WellFact(BaseModel):
    """One exact, closed-schema annotation fact with optional resolved offsets."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    record: Literal["fact"] = "fact"
    format: Literal["kgb.well_annotation/1"] = "kgb.well_annotation/1"
    annotator: str
    chunk_id: str
    fact_no: int = Field(ge=1)
    relation: str
    other_label: str | None = None
    subject: dict
    object: dict
    qualifiers: dict
    polarity: Literal["positive", "negative"]
    modality: Literal["done", "attempted", "planned", "approved"]
    time: dict | None
    uncertainty: Literal["certain", "uncertain"]
    evidence: dict
    note: str = Field(max_length=300)
    origin: str | None = None
    decision_id: str | None = None

    @model_validator(mode="after")
    def _validate(self):
        if self.relation not in RELATIONS and self.relation != "other": raise AnnotationError("relation", "unknown relation")
        if self.relation == "other":
            if not self.other_label or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.other_label): raise AnnotationError("relation", "other_label required")
        elif self.other_label is not None: raise AnnotationError("relation", "other_label only for other")
        if self.origin is not None or self.decision_id is not None:
            if self.annotator != "adjudicated": raise AnnotationError("relation", "adjudicated metadata on unadjudicated fact")
        if "implicit" in self.subject:
            if self.subject != {"implicit": "report_well", "type": "Borehole"}: raise AnnotationError("subject", "invalid implicit subject")
        else:
            _at("subject", _span, self.subject, {"type"}, {"role"})
            if "role" in self.subject and (self.subject["role"] != "report_well" or self.subject["type"] != "Borehole"):
                raise AnnotationError("subject", "invalid subject role")
        if self.subject["type"] not in ENTITY_TYPES: raise AnnotationError("subject", "invalid subject type")
        kind = self.object.get("kind")
        if kind not in OBJECT_FIELDS: raise AnnotationError("object", "invalid object kind")
        object_mismatch = _at("object", _literal, self.object, kind)
        if self.relation != "other":
            subjects, kinds, allowed = RELATION_SPEC[self.relation]
            if self.subject["type"] not in subjects or kind not in kinds or not self.qualifiers.keys() <= allowed:
                raise AnnotationError("relation", "relation type/qualifier mismatch")
            expected_type = {"completed_in": "Zone", "encountered_marker": "Zone", "used_rig": "Rig", "operated_by": "Company"}.get(self.relation)
            if expected_type and self.object.get("type") != expected_type: raise AnnotationError("relation", "relation object type mismatch")
        elif self.qualifiers: raise AnnotationError("qualifiers", "other does not allow qualifiers")
        for key, value in self.qualifiers.items():
            if key in {"toc", "correction"}:
                if type(value) is not bool: raise AnnotationError("qualifiers." + key, "boolean qualifier required")
            elif key in ENUM_QUALIFIERS:
                if not isinstance(value, str) or value not in ENUM_QUALIFIERS[key]: raise AnnotationError("qualifiers." + key, "invalid enum qualifier")
                if self.relation == "fit_lot_emw" and key == "test_kind" and value not in {"fit", "lot"}: raise AnnotationError("qualifiers." + key, "FIT/LOT kind")
            elif key == "action":
                allowed = {"set", "placed", "replaced"} if self.relation == "set_plug_at" else {"set", "located"}
                if not isinstance(value, str) or value not in allowed: raise AnnotationError("qualifiers." + key, "invalid action")
            elif key in SPAN_QUALIFIERS:
                _at("qualifiers." + key, _span, value, SPAN_QUALIFIERS[key])
                # Qualifier schemas are exact, including no optional offsets.
                _at("qualifiers." + key, _shape, value, {"text", "occ"} | SPAN_QUALIFIERS[key])
                qkind = {"at_depth": "depth", "density": "density", "volume": "volume", "gun_size": "size"}.get(key)
                if qkind: _at("qualifiers." + key, _literal, value, qkind, False)
                if key == "spf": _at("qualifiers." + key, _number, value["value"])
                if key == "duration" and value["minutes"] is not None and (
                    type(value["minutes"]) not in {int, float} or not math.isfinite(value["minutes"]) or value["minutes"] < 0):
                    raise AnnotationError("qualifiers." + key, "invalid duration")
            else: raise AnnotationError("qualifiers." + key, "unknown qualifier")
        time_mismatch = _at("time", _literal, self.time, "date", False) if self.time is not None else None
        _at("evidence", _span, self.evidence)
        mismatches = [AnnotationError(path, "date normalization mismatch", detail)
                      for path, detail in (("object", object_mismatch), ("time", time_mismatch)) if detail]
        if mismatches:
            mismatches[0].extra = tuple(mismatches[1:])
            raise mismatches[0]
        return self


def resolve_span(span: dict, text: str) -> dict:
    """Resolve overlapping substring occurrences with code-point offsets."""
    start = -1
    for _ in range(span["occ"] + 1):
        start = text.find(span["text"], start + 1)
        if start < 0: raise ValueError("span not found")
    end = start + len(span["text"])
    if span.get("start", start) != start or span.get("end", end) != end: raise ValueError("span offset mismatch")
    return {**span, "start": start, "end": end}


def resolve_fact(fact: WellFact, text: str) -> WellFact:
    """Resolve all spans and require explicit subject/object inside evidence."""
    row = copy.deepcopy(fact.model_dump(exclude_none=True))
    row["time"] = fact.time
    for key in ("subject", "object", "evidence", "time"):
        if isinstance(row.get(key), dict) and "text" in row[key]: row[key] = _at(key, resolve_span, row[key], text)
    for key, value in row["qualifiers"].items():
        if isinstance(value, dict): _at("qualifiers." + key, resolve_span, value, text)
    for key in ("subject", "object"):
        if "start" in row[key] and not row["evidence"]["start"] <= row[key]["start"] < row[key]["end"] <= row["evidence"]["end"]:
            raise AnnotationError("evidence", "evidence does not contain fact span")
    return WellFact.model_validate(row)


class AnnotationFacts(list):
    """Facts plus chunk statuses so unreadable chunks remain excluded from scoring."""
    def __init__(self, values=(), statuses=None):
        super().__init__(values)
        self.statuses = statuses or {}


def load_annotations(path: Path, chunks: dict[str, str], issues: list | None = None,
                     label: str | None = None) -> AnnotationFacts:
    """Collect field-specific line errors without cascading numbering failures."""
    facts, statuses, numbers = AnnotationFacts(), {}, Counter()
    current = annotator = None
    label = label or path.name
    had_error = False
    try:
        with path.open(encoding="utf-8-sig") as source:
            for line_no, line in enumerate(source, 1):
                try:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise AnnotationError("record", "invalid json") from exc
                    if not isinstance(row, dict): raise TypeError()
                    chunk_id = row.get("chunk_id")
                    known = isinstance(chunk_id, str) and chunk_id in chunks
                    # Open known chunks and count fact lines even when validation fails.
                    if row.get("record") == "chunk" and known: current = chunk_id
                    if row.get("record") == "fact" and known: numbers[chunk_id] += 1
                    if row.get("format") != "kgb.well_annotation/1": raise AnnotationError("record", "invalid format")
                    if not known: raise AnnotationError("record", "unknown chunk")
                    if annotator is None: annotator = row.get("annotator")
                    if not isinstance(annotator, str) or row.get("annotator") != annotator:
                        raise AnnotationError("record", "annotator mismatch")
                    if row.get("record") == "chunk":
                        _at("chunk", _shape, row, {"record", "format", "annotator", "chunk_id", "status", "n_facts", "note"})
                        if chunk_id in statuses: raise AnnotationError("chunk", "duplicate chunk record")
                        if type(row["n_facts"]) is not int or row["n_facts"] < 0: raise AnnotationError("chunk", "invalid fact count")
                        if row["status"] not in {"annotated", "no_facts", "unreadable"}: raise AnnotationError("chunk", "invalid chunk status")
                        if not isinstance(row["note"], str) or len(row["note"]) > 300: raise AnnotationError("chunk", "invalid note")
                        if row["status"] == "unreadable" and not row["note"]: raise AnnotationError("chunk", "unreadable reason required")
                        if row["status"] == "annotated" and row["n_facts"] == 0: raise AnnotationError("chunk", "annotated requires facts")
                        if row["status"] != "annotated" and row["n_facts"] and annotator != "adjudicated":
                            raise AnnotationError("chunk", "non-annotated facts")
                        statuses[chunk_id] = row
                    else:
                        if row.get("record") != "fact" or current != chunk_id: raise AnnotationError("record", "fact must follow its chunk")
                        fact = resolve_fact(WellFact.model_validate(row), chunks[chunk_id])
                        if fact.fact_no != numbers[chunk_id]: raise AnnotationError("record", "fact numbering gap")
                        facts.append(fact)
                except (ValueError, KeyError, TypeError) as exc:
                    had_error = True
                    if isinstance(exc, ValidationError):
                        errors = []
                        for error in exc.errors():
                            nested = error.get("ctx", {}).get("error")
                            if isinstance(nested, AnnotationError): errors.extend((nested, *nested.extra))
                            else: errors.append(AnnotationError(".".join(str(k) for k in error["loc"]), error["type"]))
                    elif isinstance(exc, AnnotationError): errors = [exc, *exc.extra]
                    else: errors = [AnnotationError("record", type(exc).__name__)]
                    messages = [{"file": label, "line": line_no, "path": error.path,
                                 "reason": error.reason, "detail": error.detail} for error in errors]
                    if issues is None:
                        raise ConfigError("\n".join(annotation_message(issue) for issue in messages)) from exc
                    limit = getattr(issues, "limit", None)
                    issues.extend(messages if limit is None else messages[:limit - len(issues)])
                    if limit is not None and len(issues) >= limit:
                        break
    except (OSError, UnicodeError) as exc: raise ConfigError(f"{label}: cannot read annotations") from exc
    if not had_error:
        if set(statuses) != set(chunks): raise ConfigError(f"{label}: missing chunk records")
        if any(row["n_facts"] != numbers[key] for key, row in statuses.items()): raise ConfigError(f"{label}: fact count mismatch")
    facts.statuses = statuses
    return facts


def _quantity(obj):
    return Quantity(obj["kind"], obj.get("value"), obj.get("lower"), obj.get("upper"), obj.get("unit", "unknown"),
                    obj.get("reference", "unknown"), obj.get("datum", "unknown"), obj.get("text", ""), "ok")


def value_equal(a, b, policy, symmetric: bool = False):
    """L1 values, with entity/text compatibility and no depth/interval collapsing."""
    ka, kb = a["kind"], b["kind"]
    if {ka, kb} <= {"entity", "text"}:
        heads = set(policy.get("generic_heads", ["sand", "zone", "reservoir", "formation", "rig", "well"]))
        x, y = match_key(a.get("value", a["text"])), match_key(b.get("value", b["text"]))
        return x == y or bool(" ".join(t for t in x.split() if t not in heads)) and (
            [t for t in x.split() if t not in heads] == [t for t in y.split() if t not in heads])
    if ka != kb: return False
    if ka in UNITS: return compare(_quantity(a), _quantity(b), policy, symmetric=symmetric)
    if ka == "date":
        return a["precision"] == b["precision"] and (match_key(a["text"]) == match_key(b["text"]) if a["precision"] == "partial" else a["iso"] == b["iso"])
    return a.get("value") == b.get("value")


def _subject(a, b, policy, symmetric=False):
    def report(s): return s.get("implicit") == "report_well" or s.get("role") == "report_well"
    def alias(s):
        return report(s) or match_key(s.get("text", "")) in policy.get("well_aliases", ["well", "the well", "wellbore", "borehole", "this well"]) or bool(re.fullmatch(policy.get("well_name_pattern", r"[A-Z]{0,3}\d{2,4}[A-Z]?"), s.get("text", "")))
    if report(a): return alias(b)
    if report(b): return alias(a)
    x, y = match_key(a.get("text", "")).split(), match_key(b.get("text", "")).split()
    return bool(x and y) and (len(set(x) & set(y)) / len(set(x) | set(y)) >= 0.5 or x[-1] in y or (symmetric and y[-1] in x))


def _level(g, p, policy, symmetric=False):
    if g.chunk_id != p.chunk_id or not value_equal(g.object, p.object, policy, symmetric=symmetric): return 0
    if g.relation != p.relation: return 1
    if not _subject(g.subject, p.subject, policy, symmetric=symmetric): return 2
    for key in ("test_kind", "stage"):
        a, b = g.qualifiers.get(key), p.qualifiers.get(key)
        if a not in (None, "unknown") and b not in (None, "unknown") and a != b: return 2
    a, b = g.qualifiers.get("at_depth"), p.qualifiers.get("at_depth")
    if isinstance(a, dict) and isinstance(b, dict):
        x, y = a.get("reference"), b.get("reference")
        if x not in (None, "unknown") and y not in (None, "unknown") and x != y: return 2
    return 3


def match(gold: list[WellFact], pred: list[WellFact], policy: dict, level: str, symmetric: bool = False) -> list[tuple[int, int]]:
    """Greedy one-to-one matching by highest level, evidence distance, stable order."""
    minimum = {"L1": 1, "L2": 2, "L3": 3}[level]
    candidates = []
    def key(fact):
        return (fact.evidence.get("start", 0), fact.evidence.get("end", 0),
                cj(fact.model_dump(exclude={"annotator", "origin", "decision_id"})))
    keys_g, keys_p = ([key(f) for f in source] if symmetric else [] for source in (gold, pred))
    for i, g in enumerate(gold):
        for j, p in enumerate(pred):
            rank = _level(g, p, policy, symmetric=symmetric)
            if rank >= minimum:
                tie = tuple(sorted((keys_g[i], keys_p[j]))) if symmetric else ()
                candidates.append((-rank, abs(g.evidence.get("start", 0) - p.evidence.get("start", 0)), *tie, i, j))
    used_g, used_p, pairs = set(), set(), []
    for *_, i, j in sorted(candidates):
        if i not in used_g and j not in used_p:
            pairs.append((i, j)); used_g.add(i); used_p.add(j)
    return pairs


def partition(fact):
    """Uncertainty precedes ontology coverage and nonasserted polarity/modality."""
    if fact.uncertainty == "uncertain": return "G?"
    if fact.relation == "other": return "Gother"
    return "G+" if fact.polarity == "positive" and fact.modality == "done" else "G-"


def metrics(tp, fp, fn):
    """Counts remain available when a metric has no denominator."""
    p, r = tp / (tp + fp) if tp + fp else None, tp / (tp + fn) if tp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def score(gold, pred, policy, symmetric: bool = False) -> dict:
    """Score each level separately, excluding unreadable and neutral matches."""
    unreadable = {k for k, v in getattr(gold, "statuses", {}).items() if v["status"] == "unreadable"}
    gold, pred = [g for g in gold if g.chunk_id not in unreadable], [p for p in pred if p.chunk_id not in unreadable]
    partitions = Counter(partition(g) for g in gold)
    result = {"partitions": {k: partitions[k] for k in ("G+", "G?", "Gother", "G-")}, "n_unreadable": len(unreadable)}
    for level in ("L1", "L2", "L3"):
        pairs = match(gold, pred, policy, level, symmetric=symmetric)
        counts = Counter(partition(gold[i]) for i, _ in pairs)
        row = metrics(counts["G+"], len(pred) - len(pairs) + counts["G-"], partitions["G+"] - counts["G+"])
        row.update(matched_other=counts["Gother"], asserted_nonasserted=counts["G-"], matched_uncertain=counts["G?"])
        if level != "L1":
            row["per_relation"] = {}
            for relation in sorted({f.relation for f in [*gold, *pred]} - {"other"}):
                positive = sum(g.relation == relation and partition(g) == "G+" for g in gold)
                matched = [(i, j) for i, j in pairs if pred[j].relation == relation]
                tp = sum(partition(gold[i]) == "G+" for i, _ in matched)
                fp = sum(p.relation == relation for p in pred) - len(matched) + sum(partition(gold[i]) == "G-" for i, _ in matched)
                row["per_relation"][relation] = metrics(tp, fp, positive - tp)
        result[level] = row
    return result


def iaa_score(k: list[WellFact], c: list[WellFact], policy: dict) -> dict:
    """Score asserted facts symmetrically; callers supply the same readable scope."""
    return score([f for f in k if partition(f) == "G+"], [f for f in c if partition(f) == "G+"], policy, symmetric=True)


def bootstrap_ci(per_chunk: list, stat, n: int = 1000, seed: int = 0) -> tuple[float, float]:
    """Percentile interval from resampling whole chunks, with a fixed RNG."""
    if not per_chunk: return (None, None)
    rng = random.Random(seed)
    values = [stat([per_chunk[rng.randrange(len(per_chunk))] for _ in per_chunk]) for _ in range(n)]
    values = sorted(v for v in values if v is not None)
    if not values: return (None, None)
    return values[int((len(values) - 1) * .025)], values[int((len(values) - 1) * .975)]


def paired_bootstrap(a_chunks, b_chunks, stat, n=1000, seed=0) -> dict:
    """Resample aligned chunk pairs and report B minus A."""
    if len(a_chunks) != len(b_chunks): raise ValueError("paired scopes differ")
    def difference(rows):
        a, b = stat([r[0] for r in rows]), stat([r[1] for r in rows])
        return None if a is None or b is None else b - a
    pairs = list(zip(a_chunks, b_chunks))
    return {"difference": difference(pairs), "ci95": bootstrap_ci(pairs, difference, n, seed), "n": len(pairs)}


def sign_test(wins: int, losses: int) -> float:
    """Exact two-sided binomial sign test, omitting ties."""
    if min(wins, losses) < 0: raise ValueError("negative sign counts")
    total = wins + losses
    return min(1., 2 * sum(math.comb(total, k) for k in range(min(wins, losses) + 1)) / 2 ** total)


def facts_from_graph(graph: dict, doc_ids: set[str]) -> list[WellFact]:
    """Convert accepted statement occurrences without mapping open predicates."""
    entities = {e["entity_id"]: e["name"] for e in graph["entities"]}
    chunks = {c["chunk_id"]: c for c in graph["chunks"]}
    output = []
    for statement in graph["statements"]:
        if statement["status"] != "accepted": continue
        relation = statement["predicate"]
        surface = entities[statement["object_id"]]
        candidates = [k for k in ("interval", "depth", "pressure", "density", "size", "volume", "date", "status")
                      if relation not in RELATION_SPEC or k in RELATION_SPEC[relation][1]]
        obj = {"kind": "entity", "text": surface, "occ": 0, "type": "Zone"}
        for kind in candidates:
            if kind == "date":
                iso, precision = parse_us_date(surface)
                partial = r"\d{1,2}[/-]\d{1,2}" if relation in RELATION_SPEC else r"\d{1,2}/\d{1,2}"
                if iso is not None or re.fullmatch(partial, surface):
                    obj = {"kind": kind, "text": surface, "occ": 0, "iso": iso, "precision": precision}; break
            elif kind == "status":
                if surface.upper() in {"TA", "PA", "COM", "ST", "BP", "SI"}:
                    obj = {"kind": kind, "text": surface, "occ": 0, "value": surface.upper()}; break
            else:
                q = parse_quantity(surface, kind)
                if q.status == "ok" or relation in RELATION_SPEC and q.value is not None:
                    obj = {"kind": kind, "text": surface, "occ": 0, **{k: getattr(q, k) for k in OBJECT_FIELDS[kind]}}
                    if (relation not in RELATION_SPEC and kind == "pressure" and "#" in surface
                            and not re.search(r"\bpsig?\b", surface, re.I)
                            and not hash_is_pressure(predicate_words(relation) + " " + surface)):
                        obj["unit"] = "unknown"
                    break
        if relation == "casing_spec": obj = {"kind": "text", "text": surface, "occ": 0, "value": surface}
        for ev in statement["evidence"]:
            if ev["doc_id"] not in doc_ids: continue
            chunk = chunks[ev["chunk_id"]]
            evidence = {"text": ev["text"], "occ": 0, "start": ev["char_start"] - chunk["char_start"], "end": ev["char_end"] - chunk["char_start"]}
            output.append(WellFact.model_construct(record="fact", format="kgb.well_annotation/1", annotator="system",
                chunk_id=ev["chunk_id"], fact_no=len(output) + 1, relation=relation,
                subject={"text": entities[statement["subject_id"]], "occ": 0, "type": "Borehole"}, object=obj,
                qualifiers={}, polarity="positive", modality="done", uncertainty="certain", time=None, evidence=evidence, note=""))
    return output
