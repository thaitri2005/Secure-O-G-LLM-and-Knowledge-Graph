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

/**
 * Where the API is. Empty by default: the application and `/v1` share one origin (behind the proxy, and through the
 * development server's proxy), so no host is built into the files. `VITE_API_BASE` is for the rare setup where the
 * API is somewhere else.
 */
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

/** An answer waits for the language model, so it may take a while; every other read should be quick. */
export const ASK_TIMEOUT_MS = 180_000;
export const READ_TIMEOUT_MS = 20_000;

async function call<T>(path: string, init?: RequestInit, timeoutMs = READ_TIMEOUT_MS): Promise<T> {
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
  try {
    return (await response.json()) as T;
  } catch {
    // A proxy's own page (a sign-in form, a maintenance notice) is not the API's JSON.
    throw new ApiError("The server sent something the application could not read. Reload this page and try again.");
  }
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

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
};
