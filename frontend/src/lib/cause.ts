// Answers to questions about causes (specification §8.6): which answers get the cause view, the activities around
// the problem (their fields, or read back from the lines the system showed the AI when an answer lacks them), where
// each cited cause is written, and the question asked again when the reader picks one of several problems.
import type { AnswerOut, CauseCitation, ChunkOut, Citation, EventOut, Problem, Reasoning, ReasoningEvidence } from "../api/types";

/** The answer's reasoning when it is shown as a cause answer: one problem found, or several to choose from. */
export function reasoningOf(answer: AnswerOut): Reasoning | null {
  const reasoning = answer.evidence.reasoning ?? null;
  if (!reasoning) return null;
  if (reasoning.problem) return reasoning;
  return answer.status === "ask_which" && reasoning.candidates.length > 0 ? reasoning : null;
}

/** An activity around the problem, and whether it is part of the problem itself. */
export interface AroundEvent {
  item: ReasoningEvidence;
  /** Null when the activity came without its fields and its line could not be read; the line is then shown as it is. */
  event: EventOut | null;
  problem: boolean;
}

// The line graphrag/reasoning.py writes for an event: "* 2016-08-20 17:00-18:00, 1 h, end depth 176 ft, activity
// STUCK, non-productive KICK: description". The star marks the problem's own events. Read only for an answer whose
// activities came without their fields.
const EVENT_LINE =
  /^(\* )?(\d{4}-\d{2}-\d{2}) (\d{1,2}:\d{2})-(\d{1,2}:\d{2}), ([\d.]+) h, end depth (-?\d+) ft, activity (\S+?)(?:, non-productive (\S+?))?: ([\s\S]*)$/;

export function aroundEvent(item: ReasoningEvidence): AroundEvent {
  if (item.activity) {
    const { problem, ...event } = item.activity;
    return { item, event, problem: item.problem ?? problem };
  }
  const found = EVENT_LINE.exec(item.text);
  const event: EventOut | null = found
    ? {
        date: found[2], start: found[3], end: found[4], hours: Number(found[5]), end_md: Number(found[6]),
        code: found[7], npt_code: found[8] ?? null, description: found[9], chunks: [item.chunk],
      }
    : null;
  return { item, event, problem: item.problem ?? Boolean(found?.[1]) };
}

/** The evidence gathered around the problem, split into logged activities and passages of report text. */
export function gathered(reasoning: Reasoning): { events: AroundEvent[]; passages: ReasoningEvidence[] } {
  return {
    events: reasoning.evidence.filter((item) => item.kind === "event").map(aroundEvent),
    passages: reasoning.evidence.filter((item) => item.kind !== "event"),
  };
}

/** The evidence labels the kept causes cite. */
export function citedLabels(reasoning: Reasoning): Set<string> {
  return new Set([...reasoning.stated, ...reasoning.possible].flatMap((cause) => cause.citations.map((c) => c.evidence)));
}

function chunkOf(answer: AnswerOut, chunkId: string) {
  return answer.evidence.passages.find((p) => p.chunk_id === chunkId) ?? answer.citations.find((c) => c.chunk_id === chunkId) ?? null;
}

/** A passage gathered around the problem as report text to show; the full text when this machine holds it. */
export function passageChunk(answer: AnswerOut, item: ReasoningEvidence): ChunkOut {
  const chunk = chunkOf(answer, item.chunk);
  return {
    chunk_id: item.chunk,
    file_id: chunk?.file_id ?? item.chunk.split(/[#:]/)[0],
    page: chunk?.page ?? item.page ?? null,
    section: chunk?.section ?? null,
    type: chunk?.type ?? null,
    text: chunk?.text ?? item.text,
  };
}

/** A cited cause's source as a citation, so it opens the same way as every other source. */
export function causeSource(answer: AnswerOut, reasoning: Reasoning, citation: CauseCitation): Citation & { item: ReasoningEvidence | null } {
  const item = reasoning.evidence.find((e) => e.id === citation.evidence) ?? null;
  const chunk = chunkOf(answer, citation.chunk);
  return {
    chunk_id: citation.chunk,
    // Chunk IDs start with their report's ID: "<file>#c0038" (K1 version 0) or "<file>:s6:c0" (version 1).
    file_id: chunk?.file_id ?? citation.chunk.split(/[#:]/)[0],
    page: chunk?.page ?? item?.page ?? null,
    section: chunk?.section ?? null,
    type: chunk?.type ?? null,
    text: chunk?.text ?? (item && item.kind !== "event" ? item.text : null),
    how: citation.how,
    item,
  };
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** A date as the system reads it in a question: "20 August 2016". */
export function questionDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

const DATE_IN_QUESTION = new RegExp(`\\b\\d{1,2} (?:${MONTHS.join("|")}) \\d{4}\\b`, "g");

/**
 * The question asked again about one of several problems. The system reads a date written in the question, and
 * that date wins, so the problem's first day is written into it: in place of a date it already had, or at its end.
 */
export function reask(question: string, problem: Problem): string {
  const date = questionDate(problem.date_from);
  if (question.match(DATE_IN_QUESTION)) return question.replace(DATE_IN_QUESTION, date);
  return `${question.trim().replace(/[\s?.!]+$/, "")} on ${date}?`;
}
