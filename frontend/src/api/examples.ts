// The example responses the backend commits (backend/fixtures), served as if they were the API, so the application
// can be opened and tried with no server and no model: npm run dev:examples.
// Their evidence is real. Their model is a stand-in: each example's answer was scripted (backend/contract.py).
import endOfWell from "../../../backend/fixtures/question_end_of_well.json";
import notFound from "../../../backend/fixtures/question_not_found_exact.json";
import overTime from "../../../backend/fixtures/question_over_time.json";
import health from "../../../backend/fixtures/health.json";
import page from "../../../backend/fixtures/page.json";
import wells from "../../../backend/fixtures/wells.json";
import type { Api } from "./client";
import type { AnswerOut, Health, PageOut, WellSummary } from "./types";

/** Which example a question gets: the choice only has to make the three kinds of answer reachable. */
export function exampleFor(question: string, mode: string): AnswerOut {
  if (mode === "exact" && !/\bAK-3\b/i.test(question)) return notFound as AnswerOut;
  if (/\b(hours?|days?|how many|how long)\b/i.test(question)) return overTime as AnswerOut;
  return endOfWell as AnswerOut;
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
  page: async () => page as PageOut,
};
