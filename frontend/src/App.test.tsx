import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import health from "../../backend/fixtures/health.json";
import page from "../../backend/fixtures/page.json";
import endOfWell from "../../backend/fixtures/question_end_of_well.json";
import notFound from "../../backend/fixtures/question_not_found_exact.json";
import overTime from "../../backend/fixtures/question_over_time.json";
import wells from "../../backend/fixtures/wells.json";
import App from "./App";
import { ApiError, type Api } from "./api/client";
import type { AnswerOut, Health, PageOut, WellSummary } from "./api/types";

type Fake = Api & { ask: ReturnType<typeof vi.fn>; feedback: ReturnType<typeof vi.fn>; page: ReturnType<typeof vi.fn> };

function fakeApi(...answers: (AnswerOut | Error)[]): Fake {
  let asked = 0;
  return {
    ask: vi.fn(async (question: string, mode: string) => {
      const answer = answers[Math.min(asked, answers.length - 1)];
      asked += 1;
      if (answer instanceof Error) throw answer;
      return { ...answer, id: `${answer.id}-${asked}`, question, mode } as AnswerOut;
    }),
    feedback: vi.fn(async () => {}),
    wells: async () => wells as WellSummary[],
    health: async () => health as Health,
    page: vi.fn(async () => page as PageOut),
  };
}

const OVER_TIME = "How many hours of non-productive time did AK-3 have?";
const DEPTH = "What total depth did well AK-3 reach?";

async function ask(text: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Ask about the reports"), text);
  await user.click(screen.getByRole("button", { name: "Ask" }));
  return user;
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/");
});

describe("before a question", () => {
  it("offers questions to try and shows what is loaded", async () => {
    const api = fakeApi(overTime as AnswerOut);
    render(<App api={api} />);
    const loaded = await screen.findByRole("table", { name: "Wells loaded" });
    expect(within(loaded).getAllByRole("row")).toHaveLength(6);
    expect(within(loaded).getByRole("row", { name: /AK-3 66 27/ })).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: OVER_TIME }));
    expect(api.ask).toHaveBeenCalledWith(OVER_TIME, "allow_fallback");
    expect(await screen.findByRole("heading", { name: "115 hours" })).toBeInTheDocument();
  });

  it("does not send an empty question", async () => {
    const api = fakeApi(overTime as AnswerOut);
    render(<App api={api} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Ask" }));
    expect(api.ask).not.toHaveBeenCalled();
  });

  it("puts the cursor in the question box when / is pressed", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    const box = screen.getByLabelText("Ask about the reports");
    box.blur();
    await userEvent.setup().keyboard("/");
    expect(box).toHaveFocus();
    expect(box).toHaveValue("");
  });

  it("says which model answers, or that the answers are examples", async () => {
    const { unmount } = render(<App api={fakeApi(overTime as AnswerOut)} />);
    expect(await screen.findByText(/scripted/)).toBeInTheDocument();
    unmount();
    render(<App api={fakeApi(overTime as AnswerOut)} examples />);
    expect(await screen.findByText(/Example answers/)).toBeInTheDocument();
  });
});

describe("while a question is being answered", () => {
  it("shows the question and that the reports are being read", async () => {
    let release: (answer: AnswerOut) => void = () => {};
    const api = fakeApi(overTime as AnswerOut);
    api.ask.mockImplementation(() => new Promise<AnswerOut>((resolve) => { release = resolve; }));
    render(<App api={api} />);
    await ask(OVER_TIME);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Reading the reports");
    expect(status).toHaveTextContent(OVER_TIME);
    expect(screen.getByRole("button", { name: "Asking" })).toBeDisabled();
    release({ ...(overTime as AnswerOut), question: OVER_TIME });
    expect(await screen.findByRole("heading", { name: "115 hours" })).toBeInTheDocument();
    expect(screen.queryByText(/Reading the reports/)).not.toBeInTheDocument();
  });
});

describe("a computed answer", () => {
  it("shows the number, that no model wrote it, and how it was answered", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    await ask(OVER_TIME);
    const heading = await screen.findByRole("heading", { name: "115 hours" });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.getByText("Computed from 28 operations on 10 report days. No model wrote this number.")).toBeInTheDocument();
    const steps = within(screen.getByRole("list", { name: "How this was answered" })).getAllByRole("listitem");
    expect(steps.map((s) => s.textContent)).toEqual([
      "Understood asA total over the daily operations",
      "Read28 daily operations on 10 report days",
      "AnsweredCalculated in code. No model wrote the number",
    ]);
  });

  it("draws the operations day by day and lists them", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    await ask(OVER_TIME);
    const days = await screen.findByRole("list", { name: "Report days" });
    expect(within(days).getAllByRole("listitem")).toHaveLength(10);
    expect(within(screen.getByRole("table", { name: "Operations" })).getAllByRole("row")).toHaveLength(29);
  });

  it("points out an operation's row when it is picked on its strip", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    const user = await ask(OVER_TIME);
    const days = await screen.findByRole("list", { name: "Report days" });
    const first = within(days).getAllByRole("button")[0];
    await user.click(first);
    const rows = within(screen.getByRole("table", { name: "Operations" })).getAllByRole("row");
    expect(rows[1]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("note", { name: "Selected operation" })).toHaveTextContent("Weather Delay");
    await user.click(rows[3]);
    expect(rows[3]).toHaveAttribute("aria-selected", "true");
    expect(rows[1]).toHaveAttribute("aria-selected", "false");
  });

  it("shows the first sources of a long list and the rest on request", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    const user = await ask(OVER_TIME);
    const total = (overTime as AnswerOut).citations.length;
    const sources = await screen.findByRole("list", { name: "Sources" });
    expect(within(sources).getAllByRole("listitem")).toHaveLength(4);
    await user.click(screen.getByRole("button", { name: `Show all ${total} sources` }));
    expect(within(sources).getAllByRole("listitem")).toHaveLength(total);
  });
});

describe("a model's answer", () => {
  it("opens on the passages, cited first, with the value marked where it is written", async () => {
    render(<App api={fakeApi(endOfWell as AnswerOut)} />);
    await ask(DEPTH);
    expect(await screen.findByRole("heading", { name: "1955 ft" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Passages 5" })).toHaveAttribute("aria-selected", "true");
    const passages = screen.getAllByRole("article");
    expect(passages).toHaveLength(5);
    expect(within(passages[0]).getByText("Cited in the answer")).toBeInTheDocument();
    expect(within(passages[0]).getAllByText("1,955").some((node) => node.tagName === "MARK")).toBe(true);
  });

  it("shows the checked facts on their own tab", async () => {
    render(<App api={fakeApi(endOfWell as AnswerOut)} />);
    const user = await ask(DEPTH);
    await user.click(await screen.findByRole("tab", { name: "Checked facts 12" }));
    expect(within(screen.getByRole("table", { name: "Checked facts" })).getAllByRole("row")).toHaveLength(13);
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("opens the page a source is on, and Escape goes back", async () => {
    const api = fakeApi(endOfWell as AnswerOut);
    render(<App api={api} />);
    const user = await ask(DEPTH);
    await user.click(await screen.findByRole("button", { name: /Source 1/ }));
    const cited = (endOfWell as AnswerOut).citations[0];
    expect(api.page).toHaveBeenCalledWith(cited.file_id, cited.page);
    expect(await screen.findByRole("heading", { name: /page 2/i })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("heading", { name: /page 2/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(5);
  });
});

describe("when there is no answer", () => {
  it("asks for graph answers only when the switch is on, and says what to do next", async () => {
    const api = fakeApi(notFound as AnswerOut);
    render(<App api={api} />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText(/Graph answers only/));
    await ask("What total depth did well ZZ-9 reach?");
    expect(api.ask).toHaveBeenCalledWith("What total depth did well ZZ-9 reach?", "exact");
    expect(await screen.findByRole("heading", { name: "Not in the knowledge graph" })).toBeInTheDocument();
    expect(screen.getByText(/Turn off “Graph answers only”/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Closest passages 5" })).toBeInTheDocument();
  });

  it("says what went wrong and keeps the question when the model is not running", async () => {
    render(<App api={fakeApi(new ApiError("The language model is not running. Start the model server, then ask again."))} />);
    await ask(DEPTH);
    expect(await screen.findByRole("alert")).toHaveTextContent("The language model is not running");
    expect(screen.getByLabelText("Ask about the reports")).toHaveValue(DEPTH);
  });
});

describe("marking an answer", () => {
  it("saves a wrong answer with the reader's comment", async () => {
    const api = fakeApi(overTime as AnswerOut);
    render(<App api={api} />);
    const user = await ask(OVER_TIME);
    await user.click(await screen.findByRole("button", { name: "Wrong" }));
    await user.type(screen.getByLabelText("What should it say?"), "116 hours");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.feedback).toHaveBeenCalledWith(`${(overTime as AnswerOut).id}-1`, "wrong", "116 hours");
    expect(await screen.findByText("Saved as wrong.")).toBeInTheDocument();
  });

  it("saves a right answer in one click", async () => {
    const api = fakeApi(overTime as AnswerOut);
    render(<App api={api} />);
    const user = await ask(OVER_TIME);
    await user.click(await screen.findByRole("button", { name: "Right" }));
    expect(api.feedback).toHaveBeenCalledWith(`${(overTime as AnswerOut).id}-1`, "right", "");
    expect(await screen.findByText("Saved as right.")).toBeInTheDocument();
  });
});

describe("earlier questions", () => {
  it("fold to one line each, and open again with their evidence", async () => {
    render(<App api={fakeApi(overTime as AnswerOut, endOfWell as AnswerOut)} />);
    const user = await ask(OVER_TIME);
    await screen.findByRole("heading", { name: "115 hours" });
    await user.type(screen.getByLabelText("Ask about the reports"), DEPTH);
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("heading", { name: "1955 ft" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "115 hours" })).not.toBeInTheDocument();
    const earlier = screen.getByRole("button", { name: `${OVER_TIME} 115 hours` });
    await user.click(earlier);
    expect(await screen.findByRole("heading", { name: "115 hours" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Report days" })).toBeInTheDocument();
  });

  it("are still there after the page is opened again", async () => {
    const first = render(<App api={fakeApi(overTime as AnswerOut)} />);
    await ask(OVER_TIME);
    await screen.findByRole("heading", { name: "115 hours" });
    first.unmount();
    render(<App api={fakeApi(endOfWell as AnswerOut)} />);
    expect(await screen.findByRole("heading", { name: "115 hours" })).toBeInTheDocument();
  });

  it("can all be cleared", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    const user = await ask(OVER_TIME);
    await screen.findByRole("heading", { name: "115 hours" });
    await user.click(screen.getByRole("button", { name: "Clear all questions" }));
    expect(screen.queryByRole("heading", { name: "115 hours" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Questions to try" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("drilling-reports.answers")).toBe("[]");
  });
});

describe("a link that carries a question", () => {
  it("asks it when the page opens", async () => {
    window.history.replaceState(null, "", `/?q=${encodeURIComponent(DEPTH)}&graph=1`);
    const api = fakeApi(endOfWell as AnswerOut);
    render(<App api={api} />);
    await waitFor(() => expect(api.ask).toHaveBeenCalledWith(DEPTH, "exact"));
    expect(screen.getByLabelText(/Graph answers only/)).toBeChecked();
  });
});
