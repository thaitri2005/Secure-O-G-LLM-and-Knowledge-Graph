import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE, ApiError, liveApi } from "./client";

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

describe("the example responses", () => {
  it("show one page with an image, and the image file is committed", async () => {
    const { exampleApi } = await import("./examples");
    const shown = await exampleApi.page("gdr882_ak3_eowr", 2);
    expect(shown.image_url).toBe("/example-pages/gdr882_ak3_eowr/p7.png");
    const files = import.meta.glob("../../public/example-pages/**/*.png", { query: "?url", import: "default" });
    expect(Object.keys(files)).toEqual(["../../public/example-pages/gdr882_ak3_eowr/p7.png"]);
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
