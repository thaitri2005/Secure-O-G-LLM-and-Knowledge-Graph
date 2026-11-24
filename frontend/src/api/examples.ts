// The example responses the backend commits (backend/fixtures), served as if they were the API, so the application
// can be opened and tried with no server and no model: npm run dev:examples.
// Their evidence is real. Their model is a stand-in: each example's answer was scripted (backend/contract.py), and
// the questions people asked are a small made-up log.
import exportFile from "../../../backend/fixtures/admin_export.json";
import loggedDetail from "../../../backend/fixtures/admin_question.json";
import logged from "../../../backend/fixtures/admin_questions.json";
import events from "../../../backend/fixtures/events.json";
import cause from "../../../backend/fixtures/question_cause.json";
import causeWhich from "../../../backend/fixtures/question_cause_which.json";
import endOfWell from "../../../backend/fixtures/question_end_of_well.json";
import notFound from "../../../backend/fixtures/question_not_found_exact.json";
import overTime from "../../../backend/fixtures/question_over_time.json";
import health from "../../../backend/fixtures/health.json";
import page from "../../../backend/fixtures/page.json";
import well from "../../../backend/fixtures/well.json";
import wells from "../../../backend/fixtures/wells.json";
import { ApiError, type Api, type QuestionFilters } from "./client";
import type {
  AnswerOut, EventOut, Health, LoggedQuestion, LoggedQuestionDetail, PageOut, QuestionCounts, WellOut, WellSummary,
} from "./types";

const A_DATE = /\b\d{1,2} (January|February|March|April|May|June|July|August|September|October|November|December) \d{4}\b/;

/** The cause example as exact mode gives it: the possible factors are hidden and counted (graphrag/reasoning.py). */
function causeExact(answer: AnswerOut): AnswerOut {
  const reasoning = answer.evidence.reasoning!;
  return {
    ...answer,
    evidence: { ...answer.evidence, reasoning: { ...reasoning, possible: [], possible_hidden: reasoning.possible.length } },
  };
}

/** Which example a question gets: the choice only has to make each kind of answer reachable. */
export function exampleFor(question: string, mode: string): AnswerOut {
  // A question about a cause: with a date it finds one problem; without one, several match and it asks which.
  if (/\b(caus\w*|why)\b/i.test(question)) {
    if (!A_DATE.test(question)) return causeWhich as AnswerOut;
    return mode === "exact" ? causeExact(cause as AnswerOut) : (cause as AnswerOut);
  }
  if (mode === "exact" && !/\bAK-3\b/i.test(question)) return notFound as AnswerOut;
  if (/\b(hours?|days?|how many|how long)\b/i.test(question)) return overTime as AnswerOut;
  return endOfWell as AnswerOut;
}

const ANSWERS = [cause, causeWhich, endOfWell, notFound, overTime] as AnswerOut[];

/**
 * The example page, or one put together from the passages the examples hold. The examples have one page image (the
 * page the example answer cites); any other page shows as its text, or not at all when no example holds it.
 */
export function examplePage(fileId: string, number: number): PageOut {
  const shown = page as PageOut;
  if (shown.file_id === fileId && shown.page === number) {
    return shown.image_url ? { ...shown, image_url: `/example-pages/${shown.file_id}/p${shown.page}.png` } : shown;
  }
  const seen = new Set<string>();
  const chunks = ANSWERS.flatMap((answer) => [...answer.evidence.passages, ...answer.citations])
    .filter((chunk) => chunk.file_id === fileId && chunk.page === number && chunk.text !== null)
    .filter((chunk) => !seen.has(chunk.chunk_id) && Boolean(seen.add(chunk.chunk_id)))
    .map(({ chunk_id, file_id, page: at, section, type, text }) => ({ chunk_id, file_id, page: at, section, type, text }));
  if (chunks.length === 0) throw new ApiError("This page is not among the examples. Pages that are, open as usual.");
  return { file_id: fileId, page: number, chunks, image_url: null };
}

/** Every activity of AK-3 the examples hold, each once. The well page draws the days they cover completely. */
export function exampleEvents(): EventOut[] {
  const found = new Map<string, EventOut>();
  const add = (event: EventOut) => found.set(`${event.date} ${event.start} ${event.end} ${event.code}`, event);
  (events as EventOut[]).forEach(add);
  (overTime as AnswerOut).evidence.computed!.events.forEach(add);
  for (const item of (cause as AnswerOut).evidence.reasoning!.evidence) {
    if (item.activity) {
      const { problem: _problem, ...event } = item.activity;
      add(event);
    }
  }
  return [...found.values()];
}

/** The example log read back with the filters, newest first, as the API does it. */
export function exampleQuestions(filters: QuestionFilters): LoggedQuestion[] {
  const text = filters.q?.trim().toLowerCase();
  return (logged.questions as LoggedQuestion[]).filter((question) => {
    const day = question.asked_at?.slice(0, 10) ?? "";
    return (!filters.kind || question.kind === filters.kind)
      && (!filters.verdict || (question.verdict ?? "none") === filters.verdict)
      && (!text || question.question.toLowerCase().includes(text))
      && (!filters.date_from || day >= filters.date_from)
      && (!filters.date_to || (day !== "" && day <= filters.date_to));
  });
}

function counted(questions: LoggedQuestion[], key: (question: LoggedQuestion) => string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const question of questions) counts[key(question)] = (counts[key(question)] ?? 0) + 1;
  return counts;
}

let asked = 0;

export const exampleApi: Api = {
  ask: async (question, mode) => {
    const example = exampleFor(question, mode);
    asked += 1;
    return { ...example, id: `${example.id}-${asked}`, question, mode };
  },
  feedback: async () => {},
  wells: async () => wells as WellSummary[],
  health: async () => health as Health,
  // The committed example image stands in for the API's image route (frontend/public/example-pages).
  page: async (fileId, number) => examplePage(fileId, number),
  well: async (wellId) => {
    if (wellId !== (well as WellOut).well_id) throw new ApiError(`The examples hold a page for ${(well as WellOut).well_id} only.`);
    return well as WellOut;
  },
  wellEvents: async (wellId) => (wellId === (well as WellOut).well_id ? exampleEvents() : []),
  questions: async (filters, limit, offset) => {
    const matching = exampleQuestions(filters);
    return { total: matching.length, limit, offset, questions: matching.slice(offset, offset + limit) };
  },
  question: async (questionId) => {
    if (questionId === loggedDetail.id) return loggedDetail as LoggedQuestionDetail;
    const found = (logged.questions as LoggedQuestion[]).find((question) => question.id === questionId);
    if (!found) throw new ApiError("We couldn’t find that. The link may be wrong, or it is no longer here.");
    return { ...found, record: {} };
  },
  questionCounts: async (filters): Promise<QuestionCounts> => {
    const matching = exampleQuestions(filters);
    return {
      questions: matching.length,
      by_kind: counted(matching, (question) => question.kind ?? "none"),
      by_status: counted(matching, (question) => question.status ?? "none"),
      by_verdict: { right: 0, wrong: 0, none: 0, ...counted(matching, (question) => question.verdict ?? "none") },
    };
  },
  // The example file with the questions shown, oldest first, as the API writes it (backend/questions.py).
  exportQuestions: async (filters) => {
    const chosen = exampleQuestions(filters).reverse();
    const { expected_lane: _lane, ...file } = exportFile as Record<string, unknown>;
    const collected: Record<string, unknown> = { ...(file.collected as Record<string, unknown>), questions: chosen.length, filters };
    const questions = chosen.map(({ id, kind, question, asked_at, feedback }) => ({ id, kind: kind ?? "", question, gold: [], asked_at, feedback }));
    return {
      filename: `collected_${String(collected.on)}.json`,
      text: `${JSON.stringify({ ...file, collected, questions }, null, 2)}\n`,
    };
  },
};
