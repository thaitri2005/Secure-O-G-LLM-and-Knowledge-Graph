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
  window.localStorage.clear();
  window.localStorage.setItem("drilling-reports.guide-seen", "1"); // most tests are a returning visitor
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

  it("says so when it is running on prepared examples", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} examples />);
    expect(await screen.findByText(/Demo mode: no AI is connected/)).toBeInTheDocument();
  });
});

describe("the guide", () => {
  it("opens by itself on a first visit, and stays closed after that", async () => {
    window.localStorage.clear();
    const first = render(<App api={fakeApi(overTime as AnswerOut)} />);
    const guide = await screen.findByRole("dialog", { name: "How it works" });
    expect(within(guide).getByText(/Tell us when it is wrong/)).toBeInTheDocument();
    await userEvent.setup().click(within(guide).getByRole("button", { name: "Got it" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask about the reports")).toHaveFocus();
    first.unmount();
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    await screen.findByRole("table", { name: "Wells loaded" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("can be opened again at any time, and closes with Escape", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "How it works" }));
    expect(screen.getByRole("dialog", { name: "How it works" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks one of its example questions for you", async () => {
    const api = fakeApi(endOfWell as AnswerOut);
    render(<App api={api} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "How it works" }));
    await user.click(screen.getByRole("button", { name: /Try: “What total depth did well AK-3 reach\?”/ }));
    expect(api.ask).toHaveBeenCalledWith(DEPTH, "allow_fallback");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("explanations on hover", () => {
  it("explains a term when its i is hovered, focused or clicked", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    const user = userEvent.setup();
    const info = screen.getByRole("button", { name: "What is verified data only?" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.hover(info);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/already checked in the reports/);
    await user.unhover(info);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.click(info);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("explains how far an answer can be trusted", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    const user = await ask(OVER_TIME);
    expect(await screen.findByText("Calculated from the reports")).toBeInTheDocument();
    await user.hover(screen.getByRole("button", { name: "What is calculated from the reports?" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent(/No AI wrote it/);
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
    expect(status).toHaveTextContent("Reading the reports for you");
    expect(status).toHaveTextContent(OVER_TIME);
    expect(screen.getByRole("button", { name: "Asking" })).toBeDisabled();
    release({ ...(overTime as AnswerOut), question: OVER_TIME });
    expect(await screen.findByRole("heading", { name: "115 hours" })).toBeInTheDocument();
    expect(screen.queryByText(/Reading the reports for you/)).not.toBeInTheDocument();
  });
});

describe("a computed answer", () => {
  it("shows the number, how far to trust it, and how it was produced", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    await ask(OVER_TIME);
    const heading = await screen.findByRole("heading", { name: "115 hours" });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(screen.getByText("Added up from 28 activities across 10 days of daily reports.")).toBeInTheDocument();
    expect(screen.getByText("Calculated from the reports")).toBeInTheDocument();
    const steps = within(screen.getByRole("list", { name: "How we got this answer", hidden: true })).getAllByRole("listitem", { hidden: true });
    expect(steps.map((s) => s.textContent)).toEqual([
      "We understood your question asA total over a period of time",
      "We looked at28 activities logged over 10 days in the daily reports",
      "How the answer was producedThe system added up the numbers itself",
    ]);
  });

  it("draws the operations day by day and lists them", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    await ask(OVER_TIME);
    const days = await screen.findByRole("list", { name: "Days" });
    expect(within(days).getAllByRole("listitem")).toHaveLength(10);
    expect(within(screen.getByRole("table", { name: "Activities" })).getAllByRole("row")).toHaveLength(29);
  });

  it("explains a bar when it is hovered, and marks its row when it is clicked", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    const user = await ask(OVER_TIME);
    const days = await screen.findByRole("list", { name: "Days" });
    const first = within(days).getAllByRole("button")[0];
    const readout = screen.getByRole("note", { name: "Selected activity" });
    expect(readout).toHaveTextContent("Hover over a bar to see what happened");
    await user.hover(first);
    expect(readout).toHaveTextContent("13 Aug, 0:00 to 0:00, 24 hours, non-productive time");
    expect(readout).toHaveTextContent("Weather Delay");
    await user.unhover(first);
    expect(readout).toHaveTextContent("Hover over a bar");
    await user.click(first);
    const rows = within(screen.getByRole("table", { name: "Activities" })).getAllByRole("row");
    expect(rows[1]).toHaveAttribute("aria-selected", "true");
    await user.unhover(first);
    expect(readout).toHaveTextContent("Weather Delay");
    await user.click(rows[3]);
    expect(rows[3]).toHaveAttribute("aria-selected", "true");
    expect(rows[1]).toHaveAttribute("aria-selected", "false");
  });

  it("lists each report once, however many passages of it were used", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    await ask(OVER_TIME);
    const sources = await screen.findByRole("list", { name: "Sources" });
    expect((overTime as AnswerOut).citations.length).toBe(33);
    expect(within(sources).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "AK-3 non-productive time reportContains activities used in the calculation",
      "AK-3 daily drilling reportContains activities used in the calculation",
      "AK-3 daily drilling report (summary)Contains activities used in the calculation",
    ]);
    expect(screen.queryByRole("button", { name: /Show all/ })).not.toBeInTheDocument();
  });

  it("shows the first sources of a long list and the rest on request", async () => {
    const many = {
      ...(endOfWell as AnswerOut),
      citations: [3, 5, 7, 9, 11].map((page) => ({ ...(endOfWell as AnswerOut).citations[0], page, chunk_id: `c${page}` })),
    } as AnswerOut;
    render(<App api={fakeApi(many)} />);
    const user = await ask(DEPTH);
    const sources = await screen.findByRole("list", { name: "Sources" });
    expect(within(sources).getAllByRole("listitem")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "Show all 5 sources" }));
    expect(within(sources).getAllByRole("listitem")).toHaveLength(5);
  });
});

describe("a model's answer", () => {
  it("opens on the report text, the cited passage first, with the value highlighted", async () => {
    render(<App api={fakeApi(endOfWell as AnswerOut)} />);
    await ask(DEPTH);
    expect(await screen.findByRole("heading", { name: "1955 ft" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Report text 5" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Written by AI, checked against the reports")).toBeInTheDocument();
    const passages = screen.getAllByRole("article");
    expect(passages).toHaveLength(5);
    expect(within(passages[0]).getByText("The answer is here")).toBeInTheDocument();
    expect(within(passages[0]).getByText(/AK-3 end-of-well report, page 7/)).toBeInTheDocument();
    expect(within(passages[0]).getAllByText("1,955").some((node) => node.tagName === "MARK")).toBe(true);
  });

  it("shows the key facts on their own tab", async () => {
    render(<App api={fakeApi(endOfWell as AnswerOut)} />);
    const user = await ask(DEPTH);
    await user.click(await screen.findByRole("tab", { name: "Key facts 12" }));
    expect(within(screen.getByRole("table", { name: "Key facts" })).getAllByRole("row")).toHaveLength(13);
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("opens the page a source is on, and Escape goes back", async () => {
    const api = fakeApi(endOfWell as AnswerOut);
    render(<App api={api} />);
    const user = await ask(DEPTH);
    await user.click(await screen.findByRole("button", { name: "Source 1: AK-3 end-of-well report, page 7" }));
    const cited = (endOfWell as AnswerOut).citations[0];
    expect(api.page).toHaveBeenCalledWith(cited.file_id, cited.page);
    expect(await screen.findByRole("heading", { name: "AK-3 end-of-well report, page 2" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("heading", { name: "AK-3 end-of-well report, page 2" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(5);
  });
});

describe("when there is no answer", () => {
  it("asks for verified data only when the switch is on, and says what to do next", async () => {
    const api = fakeApi(notFound as AnswerOut);
    render(<App api={api} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Verified data only" }));
    await ask("What total depth did well ZZ-9 reach?");
    expect(api.ask).toHaveBeenCalledWith("What total depth did well ZZ-9 reach?", "exact");
    expect(await screen.findByRole("heading", { name: "Not in the verified data" })).toBeInTheDocument();
    expect(screen.getByText(/Switch off “Verified data only”/)).toBeInTheDocument();
    expect(screen.getByText("No answer found")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Closest report text 5" })).toBeInTheDocument();
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
    await user.click(await screen.findByRole("button", { name: "No, it’s wrong" }));
    await user.type(screen.getByLabelText("What should the answer be? (optional)"), "116 hours");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(api.feedback).toHaveBeenCalledWith(`${(overTime as AnswerOut).id}-1`, "wrong", "116 hours");
    expect(await screen.findByText("Thank you. Saved as wrong.")).toBeInTheDocument();
  });

  it("saves a right answer in one click", async () => {
    const api = fakeApi(overTime as AnswerOut);
    render(<App api={api} />);
    const user = await ask(OVER_TIME);
    await user.click(await screen.findByRole("button", { name: "Yes" }));
    expect(api.feedback).toHaveBeenCalledWith(`${(overTime as AnswerOut).id}-1`, "right", "");
    expect(await screen.findByText("Thank you. Saved as helpful.")).toBeInTheDocument();
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
    expect(screen.getByRole("list", { name: "Days" })).toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "Start over" }));
    expect(screen.queryByRole("heading", { name: "115 hours" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Not sure what to ask? Try one of these" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("drilling-reports.answers")).toBe("[]");
  });
});

describe("a link that carries a question", () => {
  it("asks it when the page opens", async () => {
    window.history.replaceState(null, "", `/?q=${encodeURIComponent(DEPTH)}&graph=1`);
    const api = fakeApi(endOfWell as AnswerOut);
    render(<App api={api} />);
    await waitFor(() => expect(api.ask).toHaveBeenCalledWith(DEPTH, "exact"));
    expect(screen.getByRole("checkbox", { name: "Verified data only" })).toBeChecked();
  });
});
