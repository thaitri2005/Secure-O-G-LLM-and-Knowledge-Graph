"""The API's request and response shapes (specification §7.5). They are the contract with the frontend: the OpenAPI
file in this folder is generated from them, so change them here and regenerate (`python -m backend.contract`)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["allow_fallback", "exact"]
Lane = Literal["passages", "well_facts", "events"]
Status = Literal["answered", "not_stated", "not_found_in_graph", "withheld", "invalid"]
ReportType = Literal["end_of_well", "daily"]


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    mode: Mode = Field("allow_fallback", description="exact: answer from the graphs only, no fallback to passages (D-59)")
    lane: Lane | None = Field(None, description="Force one lane instead of the coordinator's route")


class FeedbackIn(BaseModel):
    verdict: Literal["right", "wrong"]
    comment: str = Field("", max_length=2000)


class Answer(BaseModel):
    value: str = Field(description="Normalized in code: dates YYYY-MM-DD, numbers without separators")
    unit: str | None = None


class ChunkOut(BaseModel):
    chunk_id: str
    file_id: str = Field(description="The report the chunk belongs to")
    page: int | None
    section: str | None
    type: str | None = Field(description="text, table or form")
    text: str | None = Field(description="None when this machine does not hold the chunk's report")


class Citation(ChunkOut):
    how: Literal["model", "by_quote", "by_value", "unsupported", "event_graph"] = Field(
        description="How code checked the citation; event_graph: a chunk holding a source event of a computed result")


class FactOut(BaseModel):
    well: str
    property: str
    value: str
    unit: str | None = None
    qualifier: str = Field(description="actual, planned, projected, ...")
    context: dict[str, str | int | float] | None = Field(None, description="For example the casing size a depth belongs to")
    source: Literal["table_mapping", "llm"]
    chunk_id: str


class EventOut(BaseModel):
    date: str
    start: str
    end: str
    hours: float
    end_md: int = Field(description="End measured depth, ft")
    code: str = Field(description="Activity code")
    description: str
    npt_code: str | None = Field(description="Non-productive code, when the report marks one")
    chunks: list[str]


class Computed(BaseModel):
    plan: dict = Field(description="The query plan the framing call wrote; code ran it")
    text: str
    values: list[str]
    unit: str
    events: list[EventOut] = Field(description="The events the result was computed from (at most 60)")
    source_chunks: list[str]


class Evidence(BaseModel):
    passages: list[ChunkOut] = Field(description="The passages shown to the model, or the closest ones when nothing was found")
    facts: list[FactOut] = Field(description="The validated facts shown to the model")
    computed: Computed | None
    model_note: str | None = Field(description="The model's own note on the evidence, when the answer format asks for one")


class Frame(BaseModel):
    kind: Literal["lookup", "lookup_by_date", "across_wells", "over_time", "reasoning", "other"]
    report_type: Literal["end_of_well", "daily", "both", "unknown"]
    plan: dict


class Checks(BaseModel):
    citations_supported: bool = Field(description="Every answer has a passage that supports it")
    quotes_verbatim: bool


class Cost(BaseModel):
    calls: int
    prompt_tokens: int
    completion_tokens: int
    seconds: float


class AnswerOut(BaseModel):
    id: str = Field(description="The question's ID in the question log; use it for feedback")
    question: str
    mode: Mode
    status: Status
    answer_text: str | None = Field(description="A sentence to show: the computed result, or the values with their units")
    answers: list[Answer]
    lanes: list[Lane] = Field(description="The lanes that gave the evidence, in order; empty when nothing was found")
    fallback: bool = Field(description="True when the routed lanes found nothing and passages were used instead")
    answered_from: ReportType | None = Field(description="The reports the evidence came from")
    frame: Frame
    citations: list[Citation]
    evidence: Evidence
    checks: Checks
    cost: Cost


class FeedbackOut(BaseModel):
    question_id: str
    verdict: Literal["right", "wrong"]


class FileOut(BaseModel):
    file_id: str
    report_type: ReportType
    pages: int
    chunks: int


class PageOut(BaseModel):
    file_id: str
    page: int
    chunks: list[ChunkOut] = Field(description="The page's chunks in reading order")
    image_url: str | None = Field(None, description="The page as an image, once the file store serves pages (plan task B7)")


class WellSummary(BaseModel):
    well_id: str
    facts: int
    report_days: int


class WellOut(BaseModel):
    well_id: str
    facts: list[FactOut]
    documents: list[str]
    report_days: list[str]


class Health(BaseModel):
    data: dict[str, str | int] = Field(description="Where the engine reads from and how much it holds")
    models: dict[str, str] = Field(description="role -> endpoint:model")
