"""Immutable data contracts carrying graph provenance and temporal validity."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator
from kgbuilder.core.text import TIME_ISO, pad

Grounding = Literal["exact", "partial", "none"]
PredSource = Literal["schema", "inverse", "trigger", "open", "self_canon"]
_Surface = Annotated[str, Field(min_length=1, max_length=300)]
_Time = Annotated[str, Field(pattern=TIME_ISO.pattern)]
_DocId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.\-]{1,64}$")]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Document(_Contract):
    doc_id: _DocId
    text: Annotated[str, Field(min_length=1, max_length=200_000)]
    title: Annotated[str, Field(max_length=300)] | None = None
    source_uri: Annotated[str, Field(max_length=2000)] | None = None
    published_at: _Time | None = None

    @field_validator("text", mode="before")
    @classmethod
    def _newlines(cls, value):
        return value.replace("\r\n", "\n") if isinstance(value, str) else value


class Chunk(_Contract):
    chunk_id: str
    doc_id: _DocId
    idx: Annotated[int, Field(ge=0)]
    char_start: Annotated[int, Field(ge=0)]
    char_end: Annotated[int, Field(gt=0)]
    text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def _offsets(self):
        if self.char_end <= self.char_start or self.char_end - self.char_start != len(self.text):
            raise ValueError("chunk offsets must match text length")
        return self


class Evidence(_Contract):
    doc_id: _DocId
    chunk_id: str
    char_start: Annotated[int, Field(ge=0)]
    char_end: Annotated[int, Field(gt=0)]
    text: Annotated[str, Field(min_length=1)]
    grounding: Grounding

    @model_validator(mode="before")
    @classmethod
    def _drop_span(cls, data):
        if isinstance(data, dict) and "span" in data:
            data = dict(data)
            span = data.pop("span")
            exp = f"{data.get('doc_id')}:{data.get('char_start')}-{data.get('char_end')}"
            if span != exp:
                raise ValueError(f"span {span!r} != {exp!r}")
        return data

    @computed_field
    @property
    def span(self) -> str:
        return f"{self.doc_id}:{self.char_start}-{self.char_end}"

    @model_validator(mode="after")
    def _offsets(self):
        if self.char_start >= self.char_end:
            raise ValueError("evidence requires 0 <= char_start < char_end")
        return self


class Mention(_Contract):
    mention_id: str
    chunk_id: str
    surface: _Surface
    char_start: Annotated[int, Field(ge=0)] | None
    char_end: Annotated[int, Field(gt=0)] | None
    extractor_version: str


class CandidateTriple(_Contract):
    candidate_id: str
    chunk_id: str
    source_doc_id: _DocId
    subject: _Surface
    predicate: _Surface
    object: _Surface
    extractor: Literal["kggen", "edc", "guided", "derived"]
    extractor_version: str
    evidence: Evidence
    temporal_marker: Literal["start", "end"] | None = None
    trigger_relation: str | None = None
    time_iso: _Time | None = None


class Entity(_Contract):
    entity_id: str
    name: _Surface
    aliases: list[str]
    kind: Literal["entity", "literal"]
    mention_ids: list[str]
    resolver: str


class CanonicalTriple(_Contract):
    candidate_id: str
    subject_id: str
    predicate: str
    object_id: str
    predicate_source: PredSource
    open_predicate: str
    edc_definition: str | None = None
    temporal_marker: Literal["start", "end"] | None = None
    time_iso: _Time | None = None
    evidence: Evidence
    extractor_version: str


class ValidatedStatement(_Contract):
    statement_id: str
    subject_id: str
    predicate: str
    object_id: str
    predicate_source: PredSource
    source_doc_id: _DocId
    evidence_span: Evidence
    evidence: list[Evidence]
    support_count: Annotated[int, Field(ge=1)]
    valid_from: _Time | None
    valid_to: _Time | None
    extractor_version: str
    confidence: Annotated[float, Field(ge=0, le=1)]
    status: Literal["accepted", "rejected"]
    reasons: list[str]
    candidate_ids: list[str]

    @model_validator(mode="after")
    def _invariants(self):
        if self.source_doc_id != self.evidence_span.doc_id:
            raise ValueError("source_doc_id must match evidence_span.doc_id")
        if self.support_count != len(self.candidate_ids):
            raise ValueError("support_count must match candidate_ids")
        if not self.evidence or self.evidence[0] != self.evidence_span:
            raise ValueError("evidence_span must be the first evidence")
        if self.valid_from is not None and self.valid_to is not None:
            if pad(self.valid_from) >= pad(self.valid_to) and "empty_interval" not in self.reasons:
                raise ValueError("invalid interval requires empty_interval reason")
        return self


FLAG_REASONS = frozenset({"weak_evidence", "judge_no"})


def flagged(stmt: ValidatedStatement) -> bool:
    """Identify accepted facts carrying a validation or judge flag."""
    return stmt.status == "accepted" and bool(set(stmt.reasons) & FLAG_REASONS)


class Rejection(_Contract):
    kind: Literal["candidate", "statement"]
    id: str
    stage: str
    reasons: list[str]
    record: dict


class GraphRecord(_Contract):
    format: Literal["kgb.graph/1"]
    run_name: str
    ablation: str
    flags: dict[str, bool]
    documents: list[Document]
    chunks: list[Chunk]
    entities: list[Entity]
    statements: list[ValidatedStatement]


def dump(model) -> dict:
    """Serialize a contract while retaining null-valued fields."""
    return model.model_dump(mode="json")
