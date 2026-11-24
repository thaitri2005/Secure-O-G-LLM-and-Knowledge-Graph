"""What the API does, without HTTP: questions through the coordinator, and reads of chunks, files, wells and events.

The service holds an `Engine` (graphrag.lanes). Today that engine is loaded from files; when the shared stores are
up, only the engine's loading changes (plan task E2) and this module stays as it is.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from collections import Counter
from datetime import date
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote

from graphrag import coordinator
from graphrag.data import document_key
from graphrag.factgraph import CASING
from graphrag.lanes import Engine
from graphrag.retrieval import well_names

from .questions import Filters, QuestionLog, now, question_set, verdict_of

# A well page's facts without a context: these are its depths, dates and times; the rest are general.
DEPTHS_AND_DATES = ("total_depth", "spud_date", "rig_release_date", "drilling_days", "spud_to_release_days",
                    "total_rig_time", "productive_time", "non_productive_time")


class NotFound(LookupError):
    """An ID the engine does not hold."""


def inches(size: str) -> Fraction:
    """A casing size as reports write it ("9-5/8", "20", "13 3/8") as a number, to order casings; 0 if unreadable."""
    found = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(?:[- ](\d+)/(\d+))?\s*(?:in|\")?\s*", size)
    if not found:
        return Fraction(0)
    whole, top, bottom = found.groups()
    return Fraction(whole) + (Fraction(int(top), int(bottom)) if top and int(bottom) else 0)


def depth(value) -> float:
    """A depth in a fact's context as a number, to order readings; one that is not a number goes last."""
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return float("inf")


def reasoning_view(found: dict | None) -> dict | None:
    """The reasoning lane's result as the contract gives it: the engine's own bookkeeping fields are left out."""
    if not found:
        return None
    keep = ("id", "kind", "chunk", "text", "date", "page", "problem", "activity")
    return {"problem": found["problem"], "candidates": found["candidates"],
            "evidence": [{k: item.get(k) for k in keep} for item in found["evidence"]],
            "stated": found["stated"], "possible": found["possible"], "possible_hidden": found["possible_hidden"],
            "removed": found["removed"],
            "missing": [{"text": m["text"], "source": m["from"]} for m in found["missing"]]}


class Service:
    def __init__(self, engine: Engine, frame_client, answer_client, log: QuestionLog, roles: dict[str, dict[str, str]],
                 page_images: Path | None = None):
        self.engine, self.frame_client, self.answer_client, self.log = engine, frame_client, answer_client, log
        # <page_images>/<file_id>/p<n>.png, written by platform/render_pages.py; None: no images.
        self.page_images = page_images
        self.models = {role: f"{chosen['endpoint']}:{chosen['model']}" for role, chosen in roles.items()}
        self.by_id = engine.by_id()
        # One question at a time: the model server has one slot, and the engine's retrievers are built on first use.
        self.lock = threading.Lock()
        self.new_id = lambda: uuid.uuid4().hex
        self.today = lambda: date.today().isoformat()

    # ---- questions ---------------------------------------------------------------------------------------------

    def ask(self, question: str, mode: str = "allow_fallback", lane: str | None = None) -> dict:
        question_id = self.new_id()
        q = {"id": question_id, "kind": "live", "question": question, "gold": []}
        with self.lock:
            row = coordinator.answer(q, self.engine, self.frame_client, self.answer_client, mode=mode, lane=lane)
        computed = row["computed"]
        units = row["units"] or [None] * len(row["values"])
        answers = [{"value": str(v), "unit": u or None} for v, u in zip(row["values"], units)]
        out = {
            "id": question_id, "question": question, "mode": row["mode"], "status": row["status"],
            "answer_text": row.get("answer_text") or ("; ".join(f"{a['value']} {a['unit'] or ''}".strip() for a in answers)
                                                       or None),
            "answers": answers, "lanes": row["lanes"], "fallback": row["fallback"], "answered_from": row["answered_from"],
            "frame": row["frame"],
            "citations": [dict(self.chunk_view(c["chunk"]), how=c["how"]) for c in row["citations"] if c.get("chunk")],
            "evidence": {"passages": [self.chunk_view(c) for c in row["shown_passages"]],
                         "facts": [self.fact_view(f) for f in row["shown_facts"]],
                         "computed": computed, "reasoning": reasoning_view(row.get("reasoning")),
                         "model_note": row.get("evidence") if isinstance(row.get("evidence"), str) else None},
            "checks": {"citations_supported": bool(row["citations_supported"]),
                       "quotes_verbatim": bool(row["quotes_verbatim"])},
            "cost": {"calls": row["calls"], "prompt_tokens": row["prompt_tokens"] + row["frame_prompt_tokens"],
                     "completion_tokens": row["completion_tokens"] + row["frame_completion_tokens"],
                     "seconds": round(row["seconds"] + row["frame_seconds"], 3)}}
        self.log.add_question({
            "id": question_id, "asked_at": now(), "question": question, "mode": out["mode"], "forced_lane": lane,
            "frame": out["frame"], "lanes": out["lanes"], "fallback": out["fallback"],
            "answered_from": out["answered_from"], "status": out["status"], "answers": answers,
            "answer_text": out["answer_text"], "citations": [c["chunk_id"] for c in out["citations"]],
            "cost": out["cost"], "models": self.models})
        return out

    def feedback(self, question_id: str, verdict: str, comment: str) -> dict:
        if not self.log.has_question(question_id):
            raise NotFound(question_id)
        self.log.add_feedback(question_id, verdict, comment)
        return {"question_id": question_id, "verdict": verdict}

    # ---- the question log, read side (D-65): read-only; no login yet ------------------------------------------

    @staticmethod
    def logged_view(entry: dict) -> dict:
        frame = entry.get("frame") or {}
        return {"id": entry["id"], "asked_at": entry.get("asked_at"), "question": entry.get("question", ""),
                "mode": entry.get("mode"), "kind": frame.get("kind"), "report_type": frame.get("report_type"),
                "status": entry.get("status"), "lanes": entry.get("lanes") or [], "fallback": entry.get("fallback"),
                "answered_from": entry.get("answered_from"), "answer_text": entry.get("answer_text"),
                "verdict": verdict_of(entry), "feedback": entry.get("feedback", [])}

    def logged_questions(self, filters: Filters, limit: int, offset: int) -> dict:
        total, entries = self.log.questions(filters, limit, offset)
        return {"total": total, "limit": limit, "offset": offset, "questions": [self.logged_view(e) for e in entries]}

    def logged_question(self, question_id: str) -> dict:
        entry = self.log.question(question_id)
        if entry is None:
            raise NotFound(question_id)
        return dict(self.logged_view(entry), record={k: v for k, v in entry.items() if k != "feedback"})

    def question_counts(self, filters: Filters) -> dict:
        return self.log.counts(filters)

    def export_questions(self, filters: Filters, expected_lane: str | None = None) -> dict:
        _, entries = self.log.questions(filters)
        return question_set(entries, self.today(), filters, expected_lane)

    # ---- sources -----------------------------------------------------------------------------------------------

    def chunk_view(self, chunk_id: str) -> dict:
        """A chunk for display. A citation can name a chunk this machine does not hold; it is still shown, empty."""
        chunk = self.by_id.get(chunk_id)
        if chunk is None:
            return {"chunk_id": chunk_id, "file_id": document_key(chunk_id), "page": None, "section": None,
                    "type": None, "text": None}
        return {"chunk_id": chunk.id, "file_id": chunk.doc_id, "page": chunk.page, "section": chunk.section,
                "type": chunk.kind, "text": chunk.text}

    def chunk(self, chunk_id: str) -> dict:
        if chunk_id not in self.by_id:
            raise NotFound(chunk_id)
        return self.chunk_view(chunk_id)

    def files(self) -> list[dict]:
        out = []
        for report_type, chunks in (("end_of_well", self.engine.eow_chunks), ("daily", self.engine.daily_chunks)):
            counts = Counter(c.doc_id for c in chunks)
            pages = {doc: len({c.page for c in chunks if c.doc_id == doc}) for doc in counts}
            out += [{"file_id": doc, "report_type": report_type, "pages": pages[doc], "chunks": counts[doc]}
                    for doc in sorted(counts)]
        return out

    def page(self, file_id: str, page: int) -> dict:
        chunks = [c for c in self.engine.eow_chunks + self.engine.daily_chunks if c.doc_id == file_id and c.page == page]
        if not chunks:
            raise NotFound(f"{file_id} page {page}")
        image = f"/v1/files/{quote(file_id, safe='')}/pages/{page}/image" if self._image_path(file_id, page) else None
        return {"file_id": file_id, "page": page, "chunks": [self.chunk_view(c.id) for c in chunks], "image_url": image}

    def _image_path(self, file_id: str, page: int) -> Path | None:
        """The PNG of a page, or None. The path is built from a file ID the engine holds and a positive integer, never
        from the request's text, and must stay inside the image folder."""
        if self.page_images is None or page < 1 or file_id not in {c.doc_id for c in self.engine.eow_chunks + self.engine.daily_chunks}:
            return None
        root = self.page_images.resolve()
        path = (root / file_id / f"p{page}.png").resolve()
        return path if path.is_relative_to(root) and path.is_file() else None

    def page_image(self, file_id: str, page: int) -> Path:
        path = self._image_path(file_id, page)
        if path is None:
            raise NotFound(f"{file_id} page {page} image")
        return path

    # ---- wells and events --------------------------------------------------------------------------------------

    @staticmethod
    def fact_view(fact: dict) -> dict:
        return {"well": sorted(well_names(str(fact.get("well") or "")) or {str(fact.get("well") or "")})[0],
                "property": fact["property"], "value": str(fact["value"]), "unit": fact.get("unit"),
                "qualifier": fact["qualifier"], "context": fact.get("context") or None,
                "source": "table_mapping" if fact.get("source") else "llm", "chunk_id": fact["chunk"]}

    def _facts_of(self, well: str) -> list[dict]:
        facts = [f for f in self.engine.facts if well in well_names(str(f.get("well") or ""))]
        # Well-level facts before per-depth readings, then by name: the order of the fact sheet.
        return sorted(facts, key=lambda f: (bool(f.get("context")), f["property"], json.dumps(f.get("context"), sort_keys=True)))

    def _days_of(self, well: str) -> list[str]:
        return sorted({e.date for e in self._events_of(well)})

    def _events_of(self, well: str) -> list:
        # The event graph is one well's today (graphrag.events.WELL); `Engine.wells` includes it when events exist.
        from graphrag.events import WELL
        return self.engine.events if well == WELL else []

    def wells(self) -> list[dict]:
        return [{"well_id": w, "facts": len(self._facts_of(w)), "report_days": len(self._days_of(w))}
                for w in sorted(self.engine.wells)]

    def well_fact(self, fact: dict) -> dict:
        chunk = self.by_id.get(fact["chunk"])
        return dict(self.fact_view(fact), file_id=document_key(fact["chunk"]), page=chunk.page if chunk else None)

    def well(self, well_id: str) -> dict:
        """What a page about one well shows: its facts in groups, its documents, its report days and totals. Computed
        in code from the engine; no model call."""
        if well_id not in self.engine.wells:
            raise NotFound(well_id)
        facts = self._facts_of(well_id)
        events = self._events_of(well_id)
        # The well's reports: those its facts cite, those named after it, and the daily reports its events cite.
        documents = {document_key(f["chunk"]): None for f in facts}
        documents |= {c.doc_id: None for c in self.engine.eow_chunks + self.engine.daily_chunks
                      if well_id in well_names(c.doc_id.replace("_", " "))}
        documents |= {(c.doc_id if (c := self.by_id.get(cid)) else document_key(cid)): "daily"
                      for e in events for cid in e.chunks}
        return {"well_id": well_id, "facts": self._grouped([self.well_fact(f) for f in facts]),
                "documents": self._documents(documents), **self._days(events)}

    @staticmethod
    def _grouped(facts: list[dict]) -> dict:
        """Facts in the groups a well page shows: casing facts by casing size, largest first; values at depths by
        property, shallowest first; then depths, dates and times; the rest are general."""
        general, timeline, casings, readings = [], [], {}, {}
        for fact in facts:
            context = fact["context"] or {}
            if "casing_size_in" in context:
                casings.setdefault(str(context["casing_size_in"]), []).append(fact)
            elif "depth_ft" in context:
                readings.setdefault(fact["property"], []).append(fact)
            elif fact["property"] in DEPTHS_AND_DATES:
                timeline.append(fact)
            else:
                general.append(fact)
        order = list(CASING)
        return {"general": general,
                "depths_and_dates": sorted(timeline, key=lambda f: DEPTHS_AND_DATES.index(f["property"])),
                "casing_strings": [{"size_in": size, "facts": sorted(casings[size], key=lambda f: (
                                        order.index(f["property"]) if f["property"] in order else len(order), f["property"]))}
                                   for size in sorted(casings, key=inches, reverse=True)],
                "readings": [{"property": name, "facts": sorted(found, key=lambda f: depth(f["context"]["depth_ft"]))}
                             for name, found in sorted(readings.items())]}

    def _documents(self, file_ids: dict[str, str | None]) -> list[dict]:
        """File ID -> report type when known from where it was cited; a report this machine does not hold is listed
        with no pages."""
        held = {f["file_id"]: f for f in self.files()}
        out = [held.get(file_id) or {"file_id": file_id, "report_type": report_type, "pages": 0, "chunks": 0}
               for file_id, report_type in file_ids.items()]
        rank = {"end_of_well": 0, "daily": 1, None: 2}
        return sorted(out, key=lambda d: (rank[d["report_type"]], d["file_id"]))

    @staticmethod
    def _days(events: list) -> dict:
        """The report days of the event graph, with the hours logged and the non-productive hours, and totals."""
        days: dict[str, list] = {}
        for e in events:
            days.setdefault(e.date, []).append(e)
        report_days = [{"date": day, "hours": round(sum(e.hours for e in found), 2),
                        "npt_hours": round(sum(e.hours for e in found if e.npt_code), 2), "events": len(found),
                        "end_md": max(e.end_md for e in found), "codes": list(dict.fromkeys(e.code for e in found)),
                        "npt_codes": list(dict.fromkeys(e.npt_code for e in found if e.npt_code))}
                       for day, found in sorted(days.items())]
        by_code = Counter()
        for e in events:
            if e.npt_code:
                by_code[e.npt_code] += e.hours
        return {"report_days": report_days,
                "totals": {"days": len(days), "events": len(events), "hours": round(sum(e.hours for e in events), 2),
                           "npt_hours": round(sum(by_code.values()), 2),
                           "npt_hours_by_code": {code: round(hours, 2) for code, hours in by_code.most_common()}}}

    def events(self, well_id: str, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
        if well_id not in self.engine.wells:
            raise NotFound(well_id)
        from dataclasses import asdict
        return [asdict(e) for e in self._events_of(well_id)
                if (not date_from or e.date >= date_from) and (not date_to or e.date <= date_to)]

    # ---- health ------------------------------------------------------------------------------------------------

    def health(self) -> dict:
        return {"data": {"source": getattr(self.engine, "source", "files"), "end_of_well_chunks": len(self.engine.eow_chunks),
                         "daily_chunks": len(self.engine.daily_chunks), "events": len(self.engine.events),
                         "facts": len(self.engine.facts), "wells": len(self.engine.wells)},
                "models": self.models}
