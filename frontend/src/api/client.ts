import type {
  AnswerOut, EventOut, Health, LoggedQuestionDetail, Mode, PageOut, QuestionCounts, QuestionPage, Verdict, WellOut, WellSummary,
} from "./types";

/** Which logged questions to read back. Every field is optional; an empty one does not filter. */
export interface QuestionFilters {
  kind?: string;
  verdict?: "right" | "wrong" | "none";
  q?: string;
  date_from?: string;
  date_to?: string;
}

/** A file to save: its name and its text. */
export interface Download {
  filename: string;
  text: string;
}

/** What the application asks of the server. Two versions exist: the real API, and the example responses. */
export interface Api {
  ask(question: string, mode: Mode): Promise<AnswerOut>;
  feedback(questionId: string, verdict: Verdict, comment: string): Promise<void>;
  wells(): Promise<WellSummary[]>;
  health(): Promise<Health>;
  page(fileId: string, page: number): Promise<PageOut>;
  well(wellId: string): Promise<WellOut>;
  wellEvents(wellId: string): Promise<EventOut[]>;
  questions(filters: QuestionFilters, limit: number, offset: number): Promise<QuestionPage>;
  question(questionId: string): Promise<LoggedQuestionDetail>;
  questionCounts(filters: QuestionFilters): Promise<QuestionCounts>;
  exportQuestions(filters: QuestionFilters): Promise<Download>;
}

/** A failure the person can act on: the message says what happened and what to do. */
export class ApiError extends Error {}

/**
 * Where the API is. Empty by default: the application and `/v1` share one origin (behind the proxy, and through the
 * development server's proxy), so no host is built into the files. `VITE_API_BASE` is for the rare setup where the
 * API is somewhere else.
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

/** An answer waits for the language model, so it may take a while; every other read should be quick. */
export const ASK_TIMEOUT_MS = 180_000;
export const READ_TIMEOUT_MS = 20_000;

async function send(path: string, init?: RequestInit, timeoutMs = READ_TIMEOUT_MS): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(API_BASE + path, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  } catch (failure) {
    if (failure instanceof DOMException && failure.name === "TimeoutError") {
      throw new ApiError("The server is taking too long to answer. Please try again in a moment.");
    }
    throw new ApiError("Cannot reach the application server. Check your connection, then try again.");
  }
  if (response.status === 401 || response.status === 403) {
    throw new ApiError("The access password was not accepted, or it has expired. Reload this page and sign in again.");
  }
  if (response.status === 404) {
    throw new ApiError("We couldn’t find that. The link may be wrong, or it is no longer here.");
  }
  if (response.status === 502 || response.status === 504) {
    throw new ApiError("The application server is not responding. It may be restarting; please try again in a minute.");
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
  return response;
}

// A proxy's own page (a sign-in form, a maintenance notice) is not the API's JSON.
const UNREADABLE = "The server sent something the application could not read. Reload this page and try again.";

async function call<T>(path: string, init?: RequestInit, timeoutMs = READ_TIMEOUT_MS): Promise<T> {
  const response = await send(path, init, timeoutMs);
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(UNREADABLE);
  }
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** The filters as a query string, leaving out the empty ones: "?kind=cause&verdict=wrong". */
export function filterQuery(filters: QuestionFilters, extra: Record<string, string | number> = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...filters, ...extra })) {
    const text = String(value ?? "").trim();
    if (text) params.set(key, text);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** The file name the server gives a download, or a plain one. */
function filename(response: Response, fallback: string): string {
  const named = /filename="?([^";]+)"?/.exec(response.headers.get("Content-Disposition") ?? "");
  return named ? named[1] : fallback;
}

export const liveApi: Api = {
  ask: (question, mode) => call<AnswerOut>("/v1/questions", json({ question, mode }), ASK_TIMEOUT_MS),
  feedback: async (questionId, verdict, comment) => {
    await call(`/v1/questions/${encodeURIComponent(questionId)}/feedback`, json({ verdict, comment }));
  },
  wells: () => call<WellSummary[]>("/v1/wells"),
  health: () => call<Health>("/v1/health"),
  // File IDs can contain ":" or "#", so they are encoded in the path.
  page: async (fileId, page) => {
    const found = await call<PageOut>(`/v1/files/${encodeURIComponent(fileId)}/pages/${page}`);
    return found.image_url ? { ...found, image_url: API_BASE + found.image_url } : found;
  },
  well: (wellId) => call<WellOut>(`/v1/wells/${encodeURIComponent(wellId)}`),
  wellEvents: (wellId) => call<EventOut[]>(`/v1/wells/${encodeURIComponent(wellId)}/events`),
  questions: (filters, limit, offset) => call<QuestionPage>(`/v1/admin/questions${filterQuery(filters, { limit, offset })}`),
  question: (questionId) => call<LoggedQuestionDetail>(`/v1/admin/questions/${encodeURIComponent(questionId)}`),
  questionCounts: (filters) => call<QuestionCounts>(`/v1/admin/questions/counts${filterQuery(filters)}`),
  // Saved as the server wrote it: the file is read by the project's tools, which expect its exact shape.
  exportQuestions: async (filters) => {
    const response = await send(`/v1/admin/questions/export${filterQuery(filters)}`);
    const text = await response.text();
    try {
      JSON.parse(text);
    } catch {
      throw new ApiError(UNREADABLE);
    }
    return { filename: filename(response, "collected_questions.json"), text };
  },
};
