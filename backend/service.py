"""What the API does, without HTTP: questions through the coordinator, and reads of chunks, files, wells and events.

The service holds an `Engine` (graphrag.lanes). Today that engine is loaded from files; when the shared stores are
up, only the engine's loading changes (plan task E2) and this module stays as it is.
"""
from __future__ import annotations

import json
import threading
import uuid
from collections import Counter

from graphrag import coordinator
from graphrag.data import document_key
from graphrag.lanes import Engine
from graphrag.retrieval import well_names

from .questions import QuestionLog, now


class NotFound(LookupError):
    """An ID the engine does not hold."""


class Service:
    def __init__(self, engine: Engine, frame_client, answer_client, log: QuestionLog, roles: dict[str, dict[str, str]]):
        self.engine, self.frame_client, self.answer_client, self.log = engine, frame_client, answer_client, log
        self.models = {role: f"{chosen['endpoint']}:{chosen['model']}" for role, chosen in roles.items()}
        self.by_id = engine.by_id()
        # One question at a time: the model server has one slot, and the engine's retrievers are built on first use.
        self.lock = threading.Lock()
        self.new_id = lambda: uuid.uuid4().hex

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
                         "computed": computed, "model_note": row.get("evidence")},
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
        return {"file_id": file_id, "page": page, "chunks": [self.chunk_view(c.id) for c in chunks], "image_url": None}

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

    def well(self, well_id: str) -> dict:
        if well_id not in self.engine.wells:
            raise NotFound(well_id)
        facts = self._facts_of(well_id)
        documents = {document_key(f["chunk"]) for f in facts}
        documents |= {c.doc_id for c in self.engine.eow_chunks if well_id in well_names(c.doc_id.replace("_", " "))}
        documents |= {c.doc_id for e in self._events_of(well_id) for cid in e.chunks if (c := self.by_id.get(cid))}
        return {"well_id": well_id, "facts": [self.fact_view(f) for f in facts], "documents": sorted(documents),
                "report_days": self._days_of(well_id)}

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
