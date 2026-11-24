"""The API's request and response shapes (specification §7.5). They are the contract with the frontend: the OpenAPI
file in this folder is generated from them, so change them here and regenerate (`python -m backend.contract`)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["allow_fallback", "exact"]
Lane = Literal["passages", "well_facts", "events", "reasoning"]
Status = Literal["answered", "not_stated", "not_found_in_graph", "withheld", "invalid", "ask_which"]
# In the question log only: a question that failed (the model or a store did not answer, or the system was busy).
LoggedStatus = Literal["answered", "not_stated", "not_found_in_graph", "withheld", "invalid", "ask_which", "error"]
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


class Problem(BaseModel):
    """A drilling problem found in the event graph: a run of non-productive events with one code."""
    date_from: str
    date_to: str
    start: str
    end: str
    npt_code: str | None
    hours: float
    events: int
    depth_ft: list[int] = Field(description="Lowest and highest end depth of its events, ft")
    codes: list[str] = Field(description="Activity codes of its events")
    description: str
    chunks: list[str]


class Activity(EventOut):
    """An event among the reasoning evidence, as fields: the same event as its text line, which is what the model saw."""
    description: str = Field(description="Whole, also where the text line cuts a neighbouring event's description")
    problem: bool = Field(description="Whether it is part of the problem itself")


class ReasoningEvidence(BaseModel):
    id: str = Field(description="The label the answer cites: E1, E2, ... for events, P1, P2, ... for passages")
    kind: Literal["event", "daily", "end_of_well"]
    chunk: str
    text: str = Field(description="The line or passage exactly as the model saw it")
    date: str | None = None
    page: int | None = None
    problem: bool | None = Field(None, description="For an event: whether it is part of the problem itself")
    activity: Activity | None = Field(None, description="For an event: its fields; null for a passage")


class CauseCitation(BaseModel):
    evidence: str = Field(description="The label of the evidence item")
    chunk: str
    how: Literal["model", "by_quote"]
    quote: str


class Cause(BaseModel):
    cause: str
    citations: list[CauseCitation]


class Missing(BaseModel):
    text: str
    source: Literal["corpus", "model"] = Field(description="corpus: a fixed list of what these reports lack; model: added by the model")


class Reasoning(BaseModel):
    """The answer to a question about causes (specification §8.6)."""
    problem: Problem | None = Field(description="The problem the answer is about; null when several match and the user is asked which")
    candidates: list[Problem] = Field(description="Every problem that matched the question")
    evidence: list[ReasoningEvidence] = Field(description="What code gathered around the problem and showed the model")
    stated: list[Cause] = Field(description="Causes a report states, each with a citation that code checked")
    possible: list[Cause] = Field(description="Factors visible in the evidence that no report states as the cause; empty in exact mode")
    possible_hidden: int = Field(description="Possible causes left out because the mode is exact")
    removed: dict[str, int] = Field(description="Causes code removed because no citation supported them, by list")
    missing: list[Missing] = Field(description="Kinds of evidence a real judgement needs that the reports do not hold")


class Evidence(BaseModel):
    passages: list[ChunkOut] = Field(description="The passages shown to the model, or the closest ones when nothing was found")
    facts: list[FactOut] = Field(description="The validated facts shown to the model")
    computed: Computed | None
    reasoning: Reasoning | None = Field(None, description="Set for a question about causes")
    model_note: str | None = Field(description="The model's own note on the evidence, when the answer format asks for one")


class Frame(BaseModel):
    kind: Literal["lookup", "lookup_by_date", "across_wells", "over_time", "cause", "other"]
    report_type: Literal["end_of_well", "daily", "both", "unknown"]
    plan: dict
    problem: dict | None = Field(None, description="For a question about causes: the date, depth, code and keywords it names")


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
    image_url: str | None = Field(None, description="Path of the page image when it has been rendered (platform/render_pages.py), else null")


class WellSummary(BaseModel):
    well_id: str
    facts: int
    report_days: int


class WellFact(FactOut):
    file_id: str = Field(description="The report the fact's chunk belongs to")
    page: int | None = Field(description="The chunk's page; null when this machine does not hold the chunk")


class CasingString(BaseModel):
    size_in: str = Field(description="Casing size as the report writes it, for example 9-5/8")
    facts: list[WellFact] = Field(description="Its depth, weight and grade, planned and actual")


class Readings(BaseModel):
    property: str = Field(description="For example inclination or max_measured_temperature")
    facts: list[WellFact] = Field(description="One per depth, shallowest first; context.depth_ft is the depth")


class WellFacts(BaseModel):
    general: list[WellFact] = Field(description="Rig, contractor, API number, elevation and other well-level facts")
    depths_and_dates: list[WellFact] = Field(description="Total depth, spud and rig release dates, days and hours")
    casing_strings: list[CasingString] = Field(description="Largest casing first")
    readings: list[Readings] = Field(description="Values measured or projected at depths")


class WellDocument(BaseModel):
    file_id: str
    report_type: ReportType | None = Field(description="Null when a fact cites a report this machine does not hold")
    pages: int = Field(description="0 when this machine does not hold the report")
    chunks: int


class ReportDay(BaseModel):
    date: str
    hours: float = Field(description="Hours logged in the day's operations table")
    npt_hours: float = Field(description="Hours of those the report marks non-productive")
    events: int
    end_md: int = Field(description="Deepest end measured depth of the day's events, ft")
    codes: list[str] = Field(description="Activity codes of the day, in the order logged")
    npt_codes: list[str] = Field(description="Non-productive codes of the day, in the order logged")


class WellTotals(BaseModel):
    days: int
    events: int
    hours: float
    npt_hours: float
    npt_hours_by_code: dict[str, float] = Field(description="Non-productive hours per non-productive code, most first")


class WellOut(BaseModel):
    """What a page about one well shows, computed in code from the engine; no model call."""
    well_id: str
    facts: WellFacts
    documents: list[WellDocument] = Field(description="End-of-well reports first, then daily reports, by file ID")
    report_days: list[ReportDay] = Field(description="From the event graph, oldest first; empty for a well without one")
    totals: WellTotals


# ---- the question log, read side (D-65): no login yet, the shared password at the proxy is the only gate ---------

Verdict = Literal["right", "wrong"]


class FeedbackRecord(BaseModel):
    verdict: Verdict
    comment: str
    at: str


class LoggedQuestion(BaseModel):
    id: str
    asked_at: str | None
    question: str
    mode: str | None
    kind: str | None = Field(description="The frame's kind")
    report_type: str | None = Field(description="The frame's report type")
    status: str | None
    lanes: list[str]
    fallback: bool | None
    answered_from: str | None
    answer_text: str | None
    verdict: Verdict | None = Field(description="The latest mark; null when nobody marked the answer")
    feedback: list[FeedbackRecord] = Field(description="Every mark, oldest first")


class QuestionPage(BaseModel):
    total: int = Field(description="Questions matching the filters, over all pages")
    limit: int
    offset: int
    questions: list[LoggedQuestion] = Field(description="Newest first")


class LoggedQuestionDetail(LoggedQuestion):
    record: dict = Field(description="The whole stored entry: frame, answers, cited chunk IDs, cost, models, forced lane")


class QuestionCounts(BaseModel):
    questions: int
    by_kind: dict[str, int]
    by_status: dict[str, int]
    by_verdict: dict[str, int] = Field(description="right, wrong and none (not marked), by the latest mark")


class CollectedQuestion(BaseModel):
    id: str = Field(description="The question's ID in the log")
    kind: str = Field(description="The frame's kind when it was asked")
    question: str
    gold: list[str] = Field(description="Empty: gold answers are not written yet")
    asked_at: str | None
    feedback: list[FeedbackRecord] = Field(description="The marks and comments the users left")


class QuestionSetFile(BaseModel):
    """A question file in the format of graphrag/gold/, which `python -m graphrag.coordinator answer --questions
    <file>` runs; a person adds the gold facts later."""
    status: str
    version: str
    expected_lane: str | None = Field(None, description="Absent unless chosen at export: the coordinator then takes "
                                                        "it as reasoning, so routing scores of the file mean nothing")
    collected: dict = Field(description="On which date, how many questions and with which filters")
    known_limits: list[str]
    questions: list[CollectedQuestion]
    facts: list[dict] = Field(description="Empty: the gold facts a person writes")


class Health(BaseModel):
    data: dict[str, str | int] = Field(description="Where the engine reads from and how much it holds")
    models: dict[str, str] = Field(description="role -> endpoint:model")


class ProblemOut(BaseModel):
    """Every error response."""
    detail: str = Field(description="A sentence for a person")
    code: str = Field(description="A word for a program: busy, model_unavailable, store_unavailable, not_found, "
                                  "invalid_request, internal")
    question_id: str | None = Field(None, description="The log ID of the question, when one was logged")


class Ready(BaseModel):
    ready: bool
    checks: dict[str, str] = Field(description="`model` and `question_log`: `ok`, or what went wrong")
    waiting: int = Field(description="Questions waiting for the model now")
