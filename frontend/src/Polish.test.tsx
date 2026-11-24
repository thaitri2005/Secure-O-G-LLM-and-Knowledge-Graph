import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import cause from "../../backend/fixtures/question_cause.json";
import endOfWell from "../../backend/fixtures/question_end_of_well.json";
import overTime from "../../backend/fixtures/question_over_time.json";
import App from "./App";
import { ApiError, Stopped, type Api } from "./api/client";
import { exampleApi, exampleDelay } from "./api/examples";
import type { AnswerOut } from "./api/types";
import { bubbleLeft } from "./components/Tip";
import { firstDays, firstRows, stickyTop } from "./lib/fold";
import { elapsed, pageTitle, WAITING_STEPS, waitingNote, waitingStep } from "./lib/wording";

// How the application behaves in use: waiting, the keyboard, long lists, narrow screens, the edges.

const OVER_TIME = "How many hours of non-productive time did AK-3 have?";
const DEPTH = "What total depth did well AK-3 reach?";
const CAUSE = "What caused the stuck pipe on AK-3 on 20 August 2016?";

function fakeApi(over: Partial<Api> = {}): Api & { ask: ReturnType<typeof vi.fn> } {
  let asked = 0;
  const { stop: _stop, ready: _ready, ...examples } = exampleApi;
  return {
    ...examples,
    ask: vi.fn(async (question: string, mode: string) => {
      asked += 1;
      const example = /caus/.test(question) ? cause : /hours/.test(question) ? overTime : endOfWell;
      return { ...(example as AnswerOut), id: `a-${asked}`, question, mode } as AnswerOut;
    }),
    ...over,
  } as Api & { ask: ReturnType<typeof vi.fn> };
}

async function ask(text: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Ask about the reports"), text);
  await user.click(screen.getByRole("button", { name: "Ask" }));
  return user;
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  window.localStorage.setItem("drilling-reports.guide-seen", "1");
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("waiting for an answer", () => {
  it("says what is happening in steps as the seconds pass, and counts them", async () => {
    vi.useFakeTimers();
    let release: (answer: AnswerOut) => void = () => {};
    const api = fakeApi({ ask: vi.fn(() => new Promise<AnswerOut>((resolve) => { release = resolve; })) });
    render(<App api={api} />);
    fireEvent.change(screen.getByLabelText("Ask about the reports"), { target: { value: OVER_TIME } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    const steps = screen.getByRole("list", { name: "What is happening" });
    const current = () => within(steps).getAllByRole("listitem").find((step) => step.getAttribute("aria-current") === "step");
    expect(current()).toHaveTextContent("Reading your question");
    expect(screen.getByText("0 seconds")).toBeInTheDocument();
    expect(document.title).toBe(`${OVER_TIME} · Drilling Reports Assistant`);
    await act(async () => { vi.advanceTimersByTime(6000); });
    expect(current()).toHaveTextContent("Looking through the reports");
    expect(screen.getByText("6 seconds")).toBeInTheDocument();
    expect(screen.getByText("This usually takes less than a minute.")).toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(60_000); });
    expect(current()).toHaveTextContent("Writing the answer and checking it");
    expect(screen.getByText("1 minute 6 seconds")).toBeInTheDocument();
    expect(screen.getByText(/Still working/)).toBeInTheDocument();
    // Only the step is announced; the seconds are outside the announced part, so they are not read out every second.
    expect(screen.getByRole("status")).not.toHaveTextContent("seconds");
    await act(async () => { release({ ...(overTime as AnswerOut), question: OVER_TIME }); });
    expect(screen.getByRole("heading", { name: "115 hours" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "What is happening" })).not.toBeInTheDocument();
  });

  it("names no part of the system, whatever the wait", () => {
    const said = [...WAITING_STEPS.flatMap((step) => [step.title, step.detail]), ...[0, 50, 100, 200].map(waitingNote)].join(" ");
    expect(said).not.toMatch(/\b(lane|frame|graph|chunk|retriev|token|model|fallback|coordinator|reasoning|queue|server)\b/i);
    expect([0, 3, 4, 14, 15, 500].map(waitingStep)).toEqual([0, 0, 1, 1, 2, 2]);
    expect([1, 59, 60, 125].map(elapsed)).toEqual(["1 second", "59 seconds", "1 minute 0 seconds", "2 minutes 5 seconds"]);
    expect(waitingNote(200)).toMatch(/four minutes/);
  });

  it("can be stopped: the question goes back into the box, and a late answer is not shown", async () => {
    let release: (answer: AnswerOut) => void = () => {};
    const stop = vi.fn();
    const api = fakeApi({ ask: vi.fn(() => new Promise<AnswerOut>((resolve) => { release = resolve; })), stop });
    render(<App api={api} />);
    const user = await ask(OVER_TIME);
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(stop).toHaveBeenCalled();
    expect(screen.getByLabelText("Ask about the reports")).toHaveValue(OVER_TIME);
    expect(screen.getByLabelText("Ask about the reports")).toHaveFocus();
    expect(screen.getByText(/Stopped\. Your question is still in the box/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
    await act(async () => { release({ ...(overTime as AnswerOut), question: OVER_TIME }); });
    expect(screen.queryByRole("heading", { name: "115 hours" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("can be tried on the examples with a delay in the address, and stopped there too", async () => {
    expect(exampleDelay("?slow=30")).toBe(30);
    expect(exampleDelay("?slow=abc")).toBe(0);
    expect(exampleDelay("")).toBe(0);
    window.history.replaceState(null, "", "/?slow=60");
    const waiting = exampleApi.ask(DEPTH, "allow_fallback");
    exampleApi.stop!();
    await expect(waiting).rejects.toBeInstanceOf(Stopped);
  });
});

describe("the keyboard", () => {
  it("moves between tabs with the arrow keys, and Tab reaches only the open one", async () => {
    render(<App api={fakeApi()} />);
    const user = await ask(DEPTH);
    const text = await screen.findByRole("tab", { name: "Report text 5" });
    const facts = screen.getByRole("tab", { name: "Key facts 12" });
    expect(text).toHaveAttribute("tabindex", "0");
    expect(facts).toHaveAttribute("tabindex", "-1");
    text.focus();
    await user.keyboard("{ArrowRight}");
    expect(facts).toHaveFocus();
    expect(facts).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Key facts 12" })).toHaveAttribute("tabindex", "0");
    await user.keyboard("{ArrowRight}");
    expect(text).toHaveFocus();
    await user.keyboard("{End}");
    expect(facts).toHaveAttribute("aria-selected", "true");
  });

  it("reaches the timeline in one step and moves along its bars with the arrow keys", async () => {
    render(<App api={fakeApi()} />);
    const user = await ask(OVER_TIME);
    const bars = within(await screen.findByRole("list", { name: "Days" })).getAllByRole("button");
    expect(bars.filter((bar) => bar.getAttribute("tabindex") === "0")).toEqual([bars[0]]);
    bars[0].focus();
    await user.keyboard("{ArrowRight}");
    expect(bars[1]).toHaveFocus();
    expect(screen.getByRole("note", { name: "Selected activity" })).toHaveTextContent("16 Aug");
    await user.keyboard("{End}");
    expect(bars[bars.length - 1]).toHaveFocus();
    await user.keyboard("{Home}{ArrowLeft}");
    expect(bars[0]).toHaveFocus();
  });

  it("keeps Tab inside the guide, and gives the keyboard back to what opened it", async () => {
    render(<App api={fakeApi()} />);
    const user = userEvent.setup();
    const opener = screen.getByRole("button", { name: "How it works" });
    await user.click(opener);
    const guide = screen.getByRole("dialog", { name: "How it works" });
    const close = within(guide).getByRole("button", { name: "Close the guide" });
    expect(close).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(within(guide).getByRole("button", { name: "Got it" })).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(close).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("moves to a page when it opens, and back to its source when it closes", async () => {
    render(<App api={fakeApi()} />);
    const user = await ask(DEPTH);
    const source = await screen.findByRole("button", { name: "Source 1: AK-3 end-of-well report, page 7" });
    expect(source).toHaveAccessibleDescription("Found by matching the answer’s value");
    await user.click(source);
    expect(await screen.findByRole("heading", { name: "AK-3 end-of-well report, page 7" })).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(source).toHaveFocus());
  });

  it("closes an explanation with Escape even when it was only focused", async () => {
    render(<App api={fakeApi()} />);
    const user = userEvent.setup();
    act(() => screen.getByRole("button", { name: "What is verified data only?" }).focus());
    expect(await screen.findByRole("tooltip")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("offers a way past the top of the page, and one main part", () => {
    render(<App api={fakeApi()} />);
    expect(screen.getByRole("link", { name: "Skip to the content" })).toHaveAttribute("href", "#main");
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.getByRole("region", { name: "Ask a question" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});

describe("each screen", () => {
  it("has its own name on the browser tab", async () => {
    render(<App api={fakeApi()} />);
    expect(document.title).toBe("Drilling Reports Assistant");
    const user = await ask(DEPTH);
    await screen.findByRole("heading", { name: "1955 ft" });
    expect(document.title).toBe(`${DEPTH} 1955 ft · Drilling Reports Assistant`);
    await user.click(screen.getByRole("link", { name: "Questions people asked" }));
    const title = await screen.findByRole("heading", { name: "Questions people asked" });
    expect(document.title).toBe("Questions people asked · Drilling Reports Assistant");
    expect(title).toHaveFocus();
    expect(pageTitle("Well AK-3")).toBe("Well AK-3 · Drilling Reports Assistant");
  });

  it("has one top heading on a well's page", async () => {
    window.history.replaceState(null, "", "/?well=AK-3");
    render(<App api={fakeApi()} />);
    await screen.findByRole("heading", { name: "Well AK-3" });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(document.title).toBe("Well AK-3 · Drilling Reports Assistant");
  });
});

describe("a narrow screen", () => {
  it("puts the evidence before the earlier questions", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: /max-width/.test(query), addEventListener() {}, removeEventListener() {} }));
    render(<App api={fakeApi()} />);
    const user = await ask(DEPTH);
    await screen.findByRole("heading", { name: "1955 ft" });
    await user.type(screen.getByLabelText("Ask about the reports"), `${OVER_TIME}{Enter}`);
    const answer = await screen.findByRole("heading", { name: "115 hours" });
    const evidence = screen.getByRole("heading", { name: "The evidence" });
    const earlier = screen.getByRole("heading", { name: "Your earlier questions" });
    expect(answer.compareDocumentPosition(evidence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(evidence.compareDocumentPosition(earlier) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps them beside the evidence, under the answer, on a wide one", async () => {
    render(<App api={fakeApi()} />);
    const user = await ask(DEPTH);
    await screen.findByRole("heading", { name: "1955 ft" });
    await user.type(screen.getByLabelText("Ask about the reports"), `${OVER_TIME}{Enter}`);
    await screen.findByRole("heading", { name: "115 hours" });
    const evidence = screen.getByRole("heading", { name: "The evidence" });
    const earlier = screen.getByRole("heading", { name: "Your earlier questions" });
    expect(earlier.compareDocumentPosition(evidence) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: `${DEPTH} 1955 ft` })).toHaveAttribute("title", DEPTH);
  });
});

describe("long lists and columns", () => {
  it("fold to whole days, and not at all when little would be hidden", () => {
    const days = (counts: number[]) => counts.flatMap((count, day) => Array.from({ length: count }, () => `2016-08-${10 + day}`));
    expect(firstDays(days([1, 2, 1, 1, 2, 4, 6, 9, 1, 1]))).toBe(7);
    expect(firstDays(days([4, 4, 6, 11]))).toBe(8);
    expect(firstDays(days([3, 3, 3]))).toBe(9);
    expect(firstDays(days([20]))).toBe(20);
    expect(firstDays(days([6, 3]))).toBe(9);
    expect([5, 9, 10, 18].map((total) => firstRows(total))).toEqual([5, 9, 6, 6]);
  });

  it("stick under the question box when short, and by the bottom edge when taller than the window", () => {
    expect(stickyTop(500, 900, 180)).toBe(180);
    expect(stickyTop(1400, 900, 180)).toBe(-516);
  });

  it("keep an explanation on the screen", () => {
    expect(bubbleLeft(195, 200, 390)).toBe(95);
    expect(bubbleLeft(30, 200, 390)).toBe(8);
    expect(bubbleLeft(370, 200, 390)).toBe(182);
  });
});

describe("the edges", () => {
  it("confirms that a link was copied, and says so when it could not be", async () => {
    render(<App api={fakeApi()} />);
    const user = await ask(DEPTH);
    await screen.findByRole("heading", { name: "1955 ft" });
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("?q=What+total+depth"));
    expect(await screen.findByRole("button", { name: "Link copied" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("A link to this answer was copied.");
    writeText.mockRejectedValueOnce(new Error("blocked"));
    await user.click(screen.getByRole("button", { name: "Link copied" }));
    expect(await screen.findByText(/Copy it from the address bar instead/)).toBeInTheDocument();
  });

  it("says so when an answer names no page", async () => {
    const bare = { ...(endOfWell as AnswerOut), citations: [] };
    render(<App api={fakeApi({ ask: vi.fn(async () => bare) })} />);
    await ask(DEPTH);
    expect(await screen.findByText(/No page of a report was recorded for this answer/)).toBeInTheDocument();
  });

  it("offers to reload, not to try again, when the sign-in has run out", async () => {
    const expired = new ApiError("The access password was not accepted, or it has expired. Reload this page and sign in again.", true);
    render(<App api={fakeApi({ ask: vi.fn(async () => { throw expired; }) })} />);
    await ask(DEPTH);
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("button", { name: "Reload the page" })).toBeInTheDocument();
    expect(within(alert).queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask about the reports")).toHaveValue(DEPTH);
  });

  it("says before the first question when questions cannot be answered, and checks again on request", async () => {
    const ready = vi.fn(async () => ({ ready: false, checks: { model: "ReadTimeout" }, waiting: 0 }));
    render(<App api={fakeApi({ ready })} />);
    const notice = await screen.findByText(/Questions cannot be answered right now/);
    expect(notice).not.toHaveTextContent(/ReadTimeout|model/);
    ready.mockResolvedValueOnce({ ready: true, checks: { model: "ok" }, waiting: 0 });
    await userEvent.setup().click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(screen.queryByText(/Questions cannot be answered right now/)).not.toBeInTheDocument());
    expect(ready).toHaveBeenCalledTimes(2);
  });

  it("looks again once a minute while it is not ready, and no more often", async () => {
    vi.useFakeTimers();
    const ready = vi.fn(async () => ({ ready: false, checks: {}, waiting: 0 }));
    render(<App api={fakeApi({ ready })} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    await act(async () => { await vi.advanceTimersByTimeAsync(59_000); });
    expect(ready).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
    expect(ready).toHaveBeenCalledTimes(2);
  });

  it("says nothing when the server cannot tell whether it is ready", async () => {
    render(<App api={fakeApi({ ready: vi.fn(async () => { throw new Error("404"); }) })} />);
    await screen.findByRole("table", { name: "Wells loaded" });
    expect(screen.queryByText(/Questions cannot be answered right now/)).not.toBeInTheDocument();
  });
});

// jsdom cannot work out colours or sizes, so contrast and target size are checked in a browser; structure, names,
// roles and labels are checked here on every main screen.
describe("accessibility of each screen (structure, names and roles)", () => {
  async function violations(): Promise<string[]> {
    const found = await axe.run(document.body, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] },
      rules: { "color-contrast": { enabled: false }, "target-size": { enabled: false } },
    });
    return found.violations.flatMap((rule) => rule.nodes.map((node) => `${rule.id}: ${node.target.join(" ")}`));
  }

  it("the start page, with the guide open and closed", async () => {
    window.localStorage.clear();
    render(<App api={fakeApi()} />);
    await screen.findByRole("table", { name: "Wells loaded" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(await violations()).toEqual([]);
    await userEvent.setup().keyboard("{Escape}");
    expect(await violations()).toEqual([]);
  });

  it("a calculated answer, an AI-written answer with its page open, and an answer about a cause", async () => {
    render(<App api={fakeApi()} />);
    const user = await ask(OVER_TIME);
    await screen.findByRole("heading", { name: "115 hours" });
    expect(await violations()).toEqual([]);
    await user.type(screen.getByLabelText("Ask about the reports"), `${DEPTH}{Enter}`);
    await user.click(await screen.findByRole("tab", { name: "Key facts 12" }));
    expect(await violations()).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Source 1: AK-3 end-of-well report, page 7" }));
    await screen.findByRole("heading", { name: "AK-3 end-of-well report, page 7" });
    expect(await violations()).toEqual([]);
    await user.type(screen.getByLabelText("Ask about the reports"), `${CAUSE}{Enter}`);
    await screen.findByRole("heading", { name: "1 cause stated in the reports" });
    expect(await violations()).toEqual([]);
  });

  it("waiting, a well's page and the questions people asked", async () => {
    const api = fakeApi();
    api.ask.mockImplementationOnce(() => new Promise<AnswerOut>(() => {}));
    const { unmount } = render(<App api={api} />);
    await ask(DEPTH);
    expect(screen.getByRole("list", { name: "What is happening" })).toBeInTheDocument();
    expect(await violations()).toEqual([]);
    unmount();
    window.history.replaceState(null, "", "/?well=AK-3");
    const well = render(<App api={fakeApi()} />);
    await screen.findByRole("heading", { name: "Well AK-3" });
    expect(await violations()).toEqual([]);
    well.unmount();
    window.history.replaceState(null, "", "/?view=questions");
    render(<App api={fakeApi()} />);
    await screen.findByRole("list", { name: "Questions" });
    expect(await violations()).toEqual([]);
  });
});
