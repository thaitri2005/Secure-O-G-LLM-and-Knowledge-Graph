"""The lanes a question can be answered from (specification §8.1, B-D36): passages, well facts and events.

Each lane is a function with one shape: it takes the question, its frame and the engine, and returns `Evidence`.
That shape is what lets the coordinator choose among them in code, and what would let a later agent or an MCP
server call one as a tool. No lane calls a model. The settings are the baseline's (B-D23, B-D26), not new ones.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .baseline import RESULTS, asks_about_plan, build, fact_lines, names_several_wells, pool, render
from .data import Chunk
from .events import WELL, Event, build_events, inputs, plan_value
from .retrieval import well_names
from .validate import validate

SHEET_LINES = 12  # facts shown per well in an answer prompt, as the local UI has shown since B-C32
DEFAULT_FACT_RUN = "E27_design_prototype"  # its `fact_sheet` names the fact runs the current design uses


@dataclass
class Evidence:
    """What a lane found. `exact` is true for facts and computed results, false for passages (D-59)."""
    lane: str
    exact: bool
    passages: list[str] = field(default_factory=list)  # chunk IDs, best first
    facts: list[dict] = field(default_factory=list)  # validated fact records, with the fields tables.py writes
    computed: dict | None = None  # plan, text, values, unit, events, source_chunks
    answer_format: str = "status_first"
    report_type: str = "end_of_well"

    @property
    def empty(self) -> bool:
        return not self.passages and not self.facts and not (self.computed and self.computed["values"])


@dataclass
class Engine:
    """Everything the lanes read. Today it is loaded from files; the stores replace that (plan task E2)."""
    eow_chunks: list[Chunk]
    daily_chunks: list[Chunk]
    events: list[Event]
    facts: list[dict]  # already validated
    multi_well_retriever: str | None = "perwell:fusion:bm25+dense:qwen3-embedding-0.6b"
    _retrievers: dict[tuple[str, str], Any] = field(default_factory=dict, init=False, repr=False, compare=False)
    _by_id: dict[str, Chunk] | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def load(cls, fact_runs: list[str] | None = None, k1: bool = False, **settings: Any) -> "Engine":
        """The three end-of-well reports of the bundle, AK-3's daily reports with their event graph, and the
        validated facts of `fact_runs`. A machine without the daily-report corpus gets no daily chunks or events."""
        eow = pool("three")
        try:
            daily, tables, dates = inputs(k1)
            events, _ = build_events(daily, tables, dates)
        except (FileNotFoundError, OSError, KeyError):
            daily, events = [], []
        if fact_runs is None:
            design = RESULTS / f"{DEFAULT_FACT_RUN}.json"
            fact_runs = (json.loads(design.read_text(encoding="utf-8")).get("fact_sheet") or []) if design.is_file() else []
        raw = [f for name in fact_runs if (RESULTS / f"{name}.json").is_file()
               for f in json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))["facts"]]
        facts, _ = validate(raw, {c.id: c.text for c in eow}, strict=True) if raw else ([], {})
        return cls(eow, daily, events, facts, **settings)

    @property
    def has_daily(self) -> bool:
        """False on a machine without the daily-report corpus: the daily and event lanes then find nothing."""
        return bool(self.daily_chunks)

    @property
    def wells(self) -> set[str]:
        """The wells this engine holds: those its facts are about, those its reports are named after, and the
        event graph's well. A name in a question counts as a well only if it is one of these: the pattern for
        well names also matches a date range (20-22 August) or a tool (BHA-2)."""
        named = {w for f in self.facts for w in well_names(str(f.get("well") or ""))}
        named |= {w for c in self.eow_chunks for w in well_names(c.doc_id.replace("_", " "))}
        return named | ({WELL} if self.events else set())

    def chunks(self, report_type: str) -> list[Chunk]:
        return self.daily_chunks if report_type == "daily" else self.eow_chunks

    def by_id(self) -> dict[str, Chunk]:
        """Every chunk by its ID, built once: each answer looks its passages up here."""
        if self._by_id is None:
            self._by_id = {c.id: c for c in self.eow_chunks + self.daily_chunks}
        return self._by_id

    def retriever(self, spec: str, report_type: str) -> Any:
        """Built once per engine: BM25 statistics and embeddings are index-time work."""
        key = (spec, report_type)
        if key not in self._retrievers:
            self._retrievers[key] = build(spec, self.chunks(report_type))
        return self._retrievers[key]


def passages(question: str, frame: dict, engine: Engine) -> Evidence:
    """Retrieval routed by well, and by date on daily reports. Several wells get passages per well (E26)."""
    if frame.get("report_type") == "daily":
        if not engine.daily_chunks:
            return Evidence("passages", False, report_type="daily")
        hits = engine.retriever("dates:wells:bm25", "daily").search(question, 5)
        return Evidence("passages", False, [cid for cid, _ in hits], report_type="daily")
    if engine.multi_well_retriever and names_several_wells(question):
        hits = engine.retriever(engine.multi_well_retriever, "end_of_well").search(question, 10)
        return Evidence("passages", False, [cid for cid, _ in hits], answer_format="evidence_first")
    hits = engine.retriever("wells:bm25", "end_of_well").search(question, 5)
    return Evidence("passages", False, [cid for cid, _ in hits])


def shown_facts(facts: list[dict]) -> list[dict]:
    """The facts an answer prompt shows: SHEET_LINES per well, in the fact sheet's order, one per distinct line
    (baseline.fact_lines)."""
    seen: dict[str, list[str]] = {}
    out = []
    for fact in sorted(facts, key=lambda f: (bool(f.get("context")), f["property"])):
        for well in sorted(well_names(str(fact.get("well") or ""))):
            line = render(fact)
            if line not in seen.setdefault(well, []) and len(seen[well]) < SHEET_LINES:
                seen[well].append(line)
                out.append(fact)
    return out


def well_facts(question: str, frame: dict, engine: Engine) -> Evidence:
    """The validated facts of the wells the question names. Planned values are left out unless the question asks
    about a plan (B-C21). Its passages are the chunks of the facts an answer prompt would show."""
    wells = well_names(question)
    with_plans = asks_about_plan(question)
    facts = [f for f in engine.facts if well_names(str(f.get("well") or "")) & wells
             and (with_plans or f["qualifier"] != "planned")]
    # Well-level facts before per-depth readings, as the fact sheet orders them (baseline.fact_lines).
    facts.sort(key=lambda f: (bool(f.get("context")), f["property"]))
    # The chunks of the lines a fact sheet shows: SHEET_LINES per well, as baseline.fact_sheet cuts them.
    lines = fact_lines(facts)
    shown = list(dict.fromkeys(line.rsplit("[", 1)[1].rstrip("]") for well in sorted(lines)
                               for _, line in lines[well][:SHEET_LINES]))
    return Evidence("well_facts", True, shown, facts, answer_format="evidence_first")


def events(question: str, frame: dict, engine: Engine) -> Evidence:
    """Runs the frame's query plan on the event graph, in code. The result rests on its source events."""
    values, unit, text, rows = plan_value(frame["plan"], engine.events)
    if not values:
        return Evidence("events", True, report_type="daily")
    sources = list(dict.fromkeys(c for e in rows for c in e.chunks))
    computed = {"plan": frame["plan"], "text": text, "values": values, "unit": unit,
                "events": [asdict(e) for e in rows[:60]], "source_chunks": sources}
    return Evidence("events", True, sources[:5], computed=computed, report_type="daily")


LANES = {"passages": passages, "well_facts": well_facts, "events": events}
