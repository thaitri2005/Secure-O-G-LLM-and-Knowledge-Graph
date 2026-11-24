import type { components } from "./schema";
import type {
  AnswerOut, EventOut, Health, LoggedQuestionDetail, Mode, PageOut, QuestionCounts, QuestionPage, Verdict, WellOut, WellSummary,
} from "./types";

/** Which logged questions to read back. Every field is optional; an empty one does not filter. */
export interface QuestionFilters {
  kind?: string;
  /** How the question ended: "answered", or "error" for one that could not be answered. */
  status?: "answered" | "error";
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
  /** Whether a question could be answered now, where the server can say. */
  ready?(): Promise<Ready>;
  /** Gives up the question being answered, so the server is not left working on an answer nobody waits for. */
  stop?(): void;
}

/**
 * A failure the person can act on: the message says what happened and what to do. `reload` marks the failures that
 * asking again cannot fix (the sign-in ran out, or a page that is not the API's came back): the way out is to reload.
 */
export class ApiError extends Error {
  constructor(message: string, readonly reload = false) {
    super(message);
  }
}

/** The person stopped the question themselves: nothing went wrong, so nothing is reported. */
export class Stopped extends ApiError {
  constructor() {
    super("Stopped.");
  }
}

/**
 * Where the API is. Empty by default: the application and `/v1` share one origin (behind the proxy, and through the
 * development server's proxy), so no host is built into the files. `VITE_API_BASE` is for the rare setup where the
 * API is somewhere else.
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

export type Ready = components["schemas"]["Ready"];

/**
 * An answer waits for its turn and then for the language model, so it may take a while: the server gives up after
 * about 210 seconds at worst, and the browser must not give up before it does. Every other read should be quick.
 */
export const ASK_TIMEOUT_MS = 240_000;
export const READ_TIMEOUT_MS = 20_000;

/** Why the server could not answer just now, by the word it gives the reason (`code` in its error body). */
const UNAVAILABLE: Record<string, string> = {
  busy: "Several people are asking at once, so your question was not answered. Try again in half a minute.",
  model_unavailable:
    "The answering service is not responding, so your question was not answered. Try again in a minute; if it stays like this, tell the person who runs the application.",
  store_unavailable:
    "The report database is not responding, so your question was not answered. Try again in a minute; if it stays like this, tell the person who runs the application.",
};

/** The word an error body gives its reason, or null: a proxy's own error page has no such body. */
async function problemCode(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { code?: unknown } | null;
    return typeof body?.code === "string" ? body.code : null;
  } catch {
    return null;
  }
}

async function send(path: string, init?: RequestInit, timeoutMs = READ_TIMEOUT_MS, stop?: AbortSignal): Promise<Response> {
  let response: Response;
  const timeout = AbortSignal.timeout(timeoutMs);
  // Whichever comes first ends the request: the time limit, or the person stopping it.
  const ended = new AbortController();
  const end = (signal: AbortSignal) => () => ended.abort(signal.reason);
  timeout.addEventListener("abort", end(timeout), { once: true });
  stop?.addEventListener("abort", end(stop), { once: true });
  try {
    response = await fetch(API_BASE + path, { ...init, signal: stop ? ended.signal : timeout });
  } catch (failure) {
    if (stop?.aborted) throw new Stopped();
    if (failure instanceof DOMException && failure.name === "TimeoutError") {
      throw new ApiError("The server is taking too long to answer. Please try again in a moment.");
    }
    throw new ApiError("Cannot reach the application server. Check your connection, then try again.");
  }
  if (response.status === 401 || response.status === 403) {
    throw new ApiError("The access password was not accepted, or it has expired. Reload this page and sign in again.", true);
  }
  if (response.status === 404) {
    throw new ApiError("We couldn’t find that. The link may be wrong, or it is no longer here.");
  }
  if (response.status === 502 || response.status === 504) {
    throw new ApiError("The application server is not responding. It may be restarting; please try again in a minute.");
  }
  if (response.status === 503) {
    throw new ApiError(UNAVAILABLE[(await problemCode(response)) ?? ""] ?? "The system is not responding right now. Try again in a minute; if it keeps happening, tell the project team.");
  }
  if (response.status === 500) {
    throw new ApiError("The server ran into a problem and could not finish. Try again; if it happens again, tell the person who runs the application.");
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

async function call<T>(path: string, init?: RequestInit, timeoutMs = READ_TIMEOUT_MS, stop?: AbortSignal): Promise<T> {
  const response = await send(path, init, timeoutMs, stop);
  try {
    return (await response.json()) as T;
  } catch {
    if (stop?.aborted) throw new Stopped();
    throw new ApiError(UNREADABLE, true);
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

// One question is answered at a time, so one handle is enough to stop it.
let asking: AbortController | null = null;

export const liveApi: Api = {
  ask: (question, mode) => {
    asking = new AbortController();
    return call<AnswerOut>("/v1/questions", json({ question, mode }), ASK_TIMEOUT_MS, asking.signal);
  },
  stop: () => asking?.abort(),
  // "Not ready" arrives as a 503 with the same body, so the status is not treated as a failure here.
  ready: async () => {
    const response = await fetch(`${API_BASE}/v1/ready`, { signal: AbortSignal.timeout(READ_TIMEOUT_MS) });
    const body = (await response.json()) as Ready;
    if (typeof body?.ready !== "boolean") throw new ApiError(UNREADABLE, true);
    return body;
  },
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
      throw new ApiError(UNREADABLE, true);
    }
    return { filename: filename(response, "collected_questions.json"), text };
  },
};
