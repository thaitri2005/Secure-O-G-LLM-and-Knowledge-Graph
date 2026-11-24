import type { AnswerOut, Health, Mode, PageOut, Verdict, WellSummary } from "./types";

/** What the application asks of the server. Two versions exist: the real API, and the example responses. */
export interface Api {
  ask(question: string, mode: Mode): Promise<AnswerOut>;
  feedback(questionId: string, verdict: Verdict, comment: string): Promise<void>;
  wells(): Promise<WellSummary[]>;
  health(): Promise<Health>;
  page(fileId: string, page: number): Promise<PageOut>;
}

/** A failure the person can act on: the message says what happened and what to do. */
export class ApiError extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Cannot reach the application server. Check that it is running, then ask again.");
  }
  if (response.status === 503) {
    throw new ApiError("The language model is not running. Start the model server, then ask again.");
  }
  if (response.status === 422) {
    throw new ApiError("The server did not accept that question. Keep it under 500 characters.");
  }
  if (!response.ok) {
    throw new ApiError(`The server answered with an error (${response.status}). Try again.`);
  }
  return (await response.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const liveApi: Api = {
  ask: (question, mode) => call<AnswerOut>("/v1/questions", json({ question, mode })),
  feedback: async (questionId, verdict, comment) => {
    await call(`/v1/questions/${encodeURIComponent(questionId)}/feedback`, json({ verdict, comment }));
  },
  wells: () => call<WellSummary[]>("/v1/wells"),
  health: () => call<Health>("/v1/health"),
  // File IDs can contain ":" or "#", so they are encoded in the path.
  page: (fileId, page) => call<PageOut>(`/v1/files/${encodeURIComponent(fileId)}/pages/${page}`),
};
