import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE, ApiError, filterQuery, liveApi } from "./client";

function reply(status: number, body: unknown = {}, raw = false): Response {
  return new Response(raw ? (body as string) : JSON.stringify(body), { status });
}

afterEach(() => vi.unstubAllGlobals());

describe("the real API client", () => {
  it("calls the API on its own origin unless VITE_API_BASE is set", async () => {
    const fetcher = vi.fn(async () => reply(200, []));
    vi.stubGlobal("fetch", fetcher);
    await liveApi.wells();
    expect(API_BASE).toBe("");
    expect((fetcher.mock.calls as unknown[][])[0][0]).toBe("/v1/wells");
  });

  it("says what to do when the proxy’s password is wrong or has expired, for any status that means so", async () => {
    for (const status of [401, 403]) {
      vi.stubGlobal("fetch", vi.fn(async () => reply(status)));
      await expect(liveApi.health()).rejects.toThrow(/password .* sign in again/);
    }
  });

  it("gives friendly messages when the server is down, restarting, slow or answers with a page that is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(liveApi.health()).rejects.toThrow(/Cannot reach the application server/);

    for (const status of [502, 504]) {
      vi.stubGlobal("fetch", vi.fn(async () => reply(status)));
      await expect(liveApi.health()).rejects.toThrow(/not responding/);
    }

    vi.stubGlobal("fetch", vi.fn(async () => { throw new DOMException("timed out", "TimeoutError"); }));
    await expect(liveApi.health()).rejects.toThrow(/taking too long/);

    vi.stubGlobal("fetch", vi.fn(async () => reply(200, "<html>Sign in</html>", true)));
    const failure = await liveApi.health().catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as Error).message).toMatch(/could not read/);
  });

  it("gives every request a time limit, and an answer a longer one than a read", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    vi.stubGlobal("fetch", vi.fn(async () => reply(200, {})));
    await liveApi.health();
    await liveApi.ask("What total depth did well AK-3 reach?", "allow_fallback");
    const [read, ask] = timeout.mock.calls.map((call) => Number(call[0]));
    expect(read).toBeGreaterThan(0);
    expect(ask).toBeGreaterThan(read);
    timeout.mockRestore();
  });

  it("keeps a page’s image link as the server wrote it", async () => {
    const url = "/v1/files/gdr882_ak3_eowr/pages/7/image";
    vi.stubGlobal("fetch", vi.fn(async () => reply(200, { file_id: "gdr882_ak3_eowr", page: 2, chunks: [], image_url: url })));
    expect((await liveApi.page("gdr882_ak3_eowr", 2)).image_url).toBe(url);
  });
});

describe("the real API client, for the newer screens", () => {
  it("asks for a well's page and its activities, the name encoded", async () => {
    const fetcher = vi.fn(async () => reply(200, {}));
    vi.stubGlobal("fetch", fetcher);
    await liveApi.well("AK-3");
    await liveApi.wellEvents("56/32");
    const paths = (fetcher.mock.calls as unknown[][]).map((call) => call[0]);
    expect(paths).toEqual(["/v1/wells/AK-3", "/v1/wells/56%2F32/events"]);
  });

  it("reads the questions people asked with only the filters that are set", async () => {
    const fetcher = vi.fn(async () => reply(200, {}));
    vi.stubGlobal("fetch", fetcher);
    await liveApi.questions({ kind: "cause", verdict: "wrong", q: "  stuck pipe ", date_from: "", date_to: undefined }, 20, 40);
    await liveApi.questionCounts({});
    await liveApi.question("log 1");
    const paths = (fetcher.mock.calls as unknown[][]).map((call) => call[0]);
    expect(paths).toEqual([
      "/v1/admin/questions?kind=cause&verdict=wrong&q=stuck+pipe&limit=20&offset=40",
      "/v1/admin/questions/counts",
      "/v1/admin/questions/log%201",
    ]);
    expect(filterQuery({})).toBe("");
  });

  it("only reads: every request about the questions is a GET", async () => {
    const fetcher = vi.fn(async (_path: string, _init?: RequestInit) => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    await liveApi.questions({}, 20, 0);
    await liveApi.questionCounts({});
    await liveApi.question("x");
    await liveApi.exportQuestions({});
    expect(fetcher.mock.calls.every(([, init]) => (init?.method ?? "GET") === "GET")).toBe(true);
  });

  it("keeps the question file exactly as the server wrote it, under the server's name", async () => {
    const text = '{\n  "status": "COLLECTED",\n  "questions": []\n}\n';
    vi.stubGlobal("fetch", vi.fn(async () => new Response(text, {
      status: 200, headers: { "Content-Disposition": 'attachment; filename="collected_2026-11-24.json"' },
    })));
    expect(await liveApi.exportQuestions({ verdict: "none" })).toEqual({ filename: "collected_2026-11-24.json", text });
    vi.stubGlobal("fetch", vi.fn(async () => reply(200, "<html>Sign in</html>", true)));
    await expect(liveApi.exportQuestions({})).rejects.toThrow(/could not read/);
  });

  it("says plainly when something asked for is not there", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(404)));
    await expect(liveApi.well("ZZ-9")).rejects.toThrow(/couldn’t find that/);
  });
});

describe("the example responses", () => {
  it("show the page the example answer cites with its image, and the image file is committed", async () => {
    const { exampleApi } = await import("./examples");
    const shown = await exampleApi.page("gdr882_ak3_eowr", 7);
    expect(shown.image_url).toBe("/example-pages/gdr882_ak3_eowr/p7.png");
    const files = import.meta.glob("../../public/example-pages/**/*.png", { query: "?url", import: "default" });
    expect(Object.keys(files)).toEqual(["../../public/example-pages/gdr882_ak3_eowr/p7.png"]);
  });

  it("show another page as the text the examples hold of it, and say so when they hold none", async () => {
    const { exampleApi } = await import("./examples");
    const other = await exampleApi.page("gdr882_ak3_eowr", 19);
    expect(other).toMatchObject({ page: 19, image_url: null });
    expect(other.chunks.map((chunk) => chunk.chunk_id)).toEqual(["gdr882_ak3_eowr#c0034"]);
    await expect(exampleApi.page("gdr882_ak3_eowr", 28)).rejects.toThrow(/not among the examples/);
  });
});

describe("the production files", () => {
  const sources = import.meta.glob(["../**/*.ts", "../**/*.tsx", "!../**/*.test.*", "!../api/schema.d.ts", "!../api/examples.ts"], {
    query: "?raw", import: "default", eager: true,
  }) as Record<string, string>;

  it("name no development address", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(5);
    for (const [file, text] of Object.entries(sources)) {
      expect(text, file).not.toMatch(/localhost|127\.0\.0\.1|:5173|:8000/);
    }
  });
});
