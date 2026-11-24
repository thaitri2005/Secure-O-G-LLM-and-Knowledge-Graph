import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import cause from "../../backend/fixtures/question_cause.json";
import causeWhich from "../../backend/fixtures/question_cause_which.json";
import health from "../../backend/fixtures/health.json";
import page from "../../backend/fixtures/page.json";
import endOfWell from "../../backend/fixtures/question_end_of_well.json";
import wells from "../../backend/fixtures/wells.json";
import App from "./App";
import type { Api } from "./api/client";
import { exampleApi } from "./api/examples";
import type { AnswerOut, Health, PageOut, Reasoning, WellSummary } from "./api/types";

// The screens of a question about a cause (specification §8.6): the answer in parts, and the choices when several
// problems match.

type Fake = Api & { ask: ReturnType<typeof vi.fn>; page: ReturnType<typeof vi.fn> };

function fakeApi(...answers: AnswerOut[]): Fake {
  let asked = 0;
  return {
    ...exampleApi,
    ask: vi.fn(async (question: string, mode: string) => {
      const answer = answers[Math.min(asked, answers.length - 1)];
      asked += 1;
      return { ...answer, id: `${answer.id}-${asked}`, question, mode } as AnswerOut;
    }),
    feedback: vi.fn(async () => {}),
    wells: async () => wells as WellSummary[],
    health: async () => health as Health,
    page: vi.fn(async () => page as PageOut),
  };
}

const CAUSE = "What caused the stuck pipe on AK-3 on 20 August 2016?";
const WHICH = "What caused the non-productive time on AK-3?";
const DEPTH = "What total depth did well AK-3 reach?";
const caused = cause as AnswerOut;

/** The cause example with its reasoning changed. */
function causeWith(change: Partial<Reasoning>, over: Partial<AnswerOut> = {}): AnswerOut {
  return { ...caused, ...over, evidence: { ...caused.evidence, reasoning: { ...caused.evidence.reasoning!, ...change } } };
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

describe("an answer about a cause", () => {
  it("shows the problem found, in parts, and never the AI's sentence", async () => {
    render(<App api={fakeApi(caused)} />);
    await ask(CAUSE);
    expect(await screen.findByRole("heading", { name: "1 cause stated in the reports" })).toBeInTheDocument();
    expect(screen.getByText("Written by AI, each cause checked against the reports")).toBeInTheDocument();
    expect(screen.queryByText(/Problem: non-productive time coded KICK/)).not.toBeInTheDocument();
    expect(screen.getByText("Based on 25 logged activities and 3 passages of report text around the problem.")).toBeInTheDocument();
    expect(screen.getByText("20 Aug 2016, 17:00 to 23 Aug 2016, 11:00")).toBeInTheDocument();
    expect(screen.getByText("66 hours over 21 logged activities")).toBeInTheDocument();
    expect(screen.getByText("176 ft")).toBeInTheDocument();
    expect(screen.getByText("KICK")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What is this code?" })).toBeInTheDocument();
    expect(screen.getByText(/^Work to free stuck pipe, free hot water flowing from annulus.*…$/)).toBeInTheDocument();
    // The general list of sources is not shown: each cause carries its own.
    expect(screen.queryByRole("list", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("gives each stated cause with the report's words and where they are written", async () => {
    render(<App api={fakeApi(caused)} />);
    await ask(CAUSE);
    const stated = await screen.findByRole("list", { name: "Stated causes" });
    const items = within(stated).getAllByRole("listitem").filter((li) => li.parentElement === stated);
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("The inner barrel was plugged, which stuck the pipe");
    expect(within(items[0]).getByText("“due to plugged inner barrel”")).toBeInTheDocument();
    expect(items[0]).toHaveTextContent("AK-3 daily drilling report, 20 Aug 2016");
    expect(items[0]).toHaveTextContent("The AI pointed to this passage");
    expect(within(items[0]).queryByText("Possibility, not a finding")).not.toBeInTheDocument();
  });

  it("keeps other possible factors apart and labels them as possibilities", async () => {
    render(<App api={fakeApi(caused)} />);
    await ask(CAUSE);
    expect(await screen.findByRole("heading", { name: /Other possible factors \(not stated in any report\)/ })).toBeInTheDocument();
    const possible = screen.getByRole("list", { name: "Possible factors" });
    expect(possible).toHaveTextContent("Possibility, not a finding");
    expect(possible).toHaveTextContent("Hot water entering the hole at shallow depth");
    expect(possible).toHaveTextContent("“temp. building to 186 degrees”");
    expect(within(screen.getByRole("list", { name: "Stated causes" })).queryByText(/Hot water entering/)).not.toBeInTheDocument();
  });

  it("hides the possible factors with verified data only, and says how many", async () => {
    const api = fakeApi(causeWith({ possible: [], possible_hidden: 1 }));
    render(<App api={api} />);
    await userEvent.setup().click(screen.getByRole("checkbox", { name: "Verified data only" }));
    await ask(CAUSE);
    expect(api.ask).toHaveBeenCalledWith(CAUSE, "exact");
    expect(await screen.findByText("1 possible factor is not shown because “Verified data only” is on.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Possible factors" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Hot water entering/)).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Stated causes" })).toBeInTheDocument();
  });

  it("says in one quiet line when causes were left out for want of support", async () => {
    render(<App api={fakeApi(causeWith({ removed: { stated: 1, possible: 1 } }))} />);
    await ask(CAUSE);
    expect(await screen.findByText("2 more causes were left out because no report text supported them.")).toBeInTheDocument();
  });

  it("says nothing about left-out causes when there were none", async () => {
    render(<App api={fakeApi(caused)} />);
    await ask(CAUSE);
    await screen.findByRole("list", { name: "Stated causes" });
    expect(screen.queryByText(/left out because/)).not.toBeInTheDocument();
  });

  it("says so plainly when no report states a cause", async () => {
    render(<App api={fakeApi(causeWith({ stated: [] }))} />);
    await ask(CAUSE);
    expect(await screen.findByRole("heading", { name: "No report states the cause" })).toBeInTheDocument();
    expect(screen.getByText("No stated cause found")).toBeInTheDocument();
    expect(screen.getByText("None of the reports says what caused this problem.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Possible factors" })).toHaveTextContent("Possibility, not a finding");
  });

  it("lists what a real judgement would still need", async () => {
    render(<App api={fakeApi(caused)} />);
    await ask(CAUSE);
    expect(await screen.findByRole("heading", { name: /What a real judgement would still need/ })).toBeInTheDocument();
    const needed = within(screen.getByRole("list", { name: "Still needed" })).getAllByRole("listitem");
    expect(needed).toHaveLength(5);
    expect(needed[0]).toHaveTextContent("Offset wells: what happened in nearby wells drilled through the same formations");
    expect(needed[4]).toHaveTextContent("A temperature log of the hole (suggested by the AI)");
  });

  it("shows the activities around the problem, those of the problem marked", async () => {
    render(<App api={fakeApi(caused)} />);
    await ask(CAUSE);
    expect(await screen.findByRole("tab", { name: "Around the problem 25" })).toHaveAttribute("aria-selected", "true");
    const rows = within(screen.getByRole("table", { name: "Activities around the problem" })).getAllByRole("row");
    expect(rows).toHaveLength(26);
    expect(rows.filter((row) => within(row).queryByText("The problem"))).toHaveLength(21);
    expect(within(rows[1]).queryByText("The problem")).not.toBeInTheDocument();
    expect(within(rows[3]).getByText("The problem")).toBeInTheDocument();
    expect(within(rows[3]).getByText("Cited for a cause")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Days" })).getAllByRole("listitem")).toHaveLength(4);
  });

  it("shows the report text gathered around the problem on its own tab", async () => {
    render(<App api={fakeApi(caused)} />);
    const user = await ask(CAUSE);
    await user.click(await screen.findByRole("tab", { name: "Report text 3" }));
    const passages = screen.getAllByRole("article");
    expect(passages).toHaveLength(3);
    expect(within(passages[0]).getByText(/AK-3 end-of-well report, page 20/)).toBeInTheDocument();
    expect(within(passages[0]).getByText(/flowed uncontrolled from a permeable zone/)).toBeInTheDocument();
  });

  it("points to a cited activity in the evidence when its page cannot be opened here", async () => {
    render(<App api={fakeApi(caused)} />);
    const user = await ask(CAUSE);
    await user.click(await screen.findByRole("tab", { name: "Report text 3" }));
    await user.click(screen.getByRole("button", { name: "Show in the evidence: AK-3 daily drilling report, 20 Aug 2016" }));
    expect(screen.getByRole("tab", { name: "Around the problem 25" })).toHaveAttribute("aria-selected", "true");
    const rows = within(screen.getByRole("table", { name: "Activities around the problem" })).getAllByRole("row");
    expect(rows[3]).toHaveAttribute("aria-selected", "true");
    expect(rows[3]).toHaveTextContent("due to plugged inner barrel");
  });

  it("opens the page of a cited passage the way every source opens", async () => {
    const p1 = caused.evidence.reasoning!.evidence.find((item) => item.id === "P1")!;
    const onPage = causeWith({
      stated: [{
        cause: "The well flowed from a permeable zone",
        citations: [{ evidence: "P1", chunk: p1.chunk, how: "by_quote", quote: "permeable zone at about 176 feet" }],
      }],
    });
    const api = fakeApi(onPage);
    render(<App api={api} />);
    const user = await ask(CAUSE);
    const stated = await screen.findByRole("list", { name: "Stated causes" });
    expect(stated).toHaveTextContent("Found by the sentence the AI quoted");
    await user.click(within(stated).getByRole("button", { name: "Open the page: AK-3 end-of-well report, page 20" }));
    expect(api.page).toHaveBeenCalledWith("gdr882_ak3_eowr", 20);
    expect(await screen.findByRole("heading", { name: "AK-3 end-of-well report, page 7" })).toBeInTheDocument();
  });

  it("can be found again among the earlier questions", async () => {
    render(<App api={fakeApi(caused, endOfWell as AnswerOut)} />);
    const user = await ask(CAUSE);
    await screen.findByRole("heading", { name: "1 cause stated in the reports" });
    await user.type(screen.getByLabelText("Ask about the reports"), DEPTH);
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByRole("heading", { name: "1955 ft" });
    expect(screen.getByRole("button", { name: `${CAUSE} 1 cause stated in the reports` })).toBeInTheDocument();
  });
});

describe("when several problems match", () => {
  it("lists them as choices, and shows nothing as if it were an answer", async () => {
    render(<App api={fakeApi(causeWhich as AnswerOut)} />);
    await ask(WHICH);
    expect(await screen.findByRole("heading", { name: "Which problem do you mean?" })).toBeInTheDocument();
    expect(screen.getByText("Your choice is needed")).toBeInTheDocument();
    expect(screen.getByText("6 problems in the daily reports fit your question.")).toBeInTheDocument();
    expect(screen.queryByText(/Several problems match/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Yes" })).not.toBeInTheDocument();
    const choices = within(screen.getByRole("list", { name: "Problems that fit" })).getAllByRole("button");
    expect(choices).toHaveLength(6);
    expect(choices[0]).toHaveTextContent("13 Aug 2016 · 24 hours · 0 ft");
    expect(choices[0]).toHaveTextContent("Weather Delay");
    expect(choices[3]).toHaveTextContent("20–23 Aug 2016 · 66 hours · 176 ft");
    expect(choices[3]).toHaveTextContent("Coded KICK");
    expect(screen.getByText(/Choose one of the problems first/)).toBeInTheDocument();
  });

  it("asks again about the problem chosen, naming its date", async () => {
    const api = fakeApi(causeWhich as AnswerOut, caused);
    render(<App api={api} />);
    const user = await ask(WHICH);
    const choices = within(await screen.findByRole("list", { name: "Problems that fit" })).getAllByRole("button");
    await user.click(choices[3]);
    expect(api.ask).toHaveBeenLastCalledWith("What caused the non-productive time on AK-3 on 20 August 2016?", "allow_fallback");
    expect(await screen.findByRole("heading", { name: "1 cause stated in the reports" })).toBeInTheDocument();
  });

  it("keeps verified data only when it asks again", async () => {
    const api = fakeApi(causeWhich as AnswerOut, caused);
    render(<App api={api} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Verified data only" }));
    await ask(WHICH);
    const choices = within(await screen.findByRole("list", { name: "Problems that fit" })).getAllByRole("button");
    await user.click(choices[0]);
    expect(api.ask).toHaveBeenLastCalledWith("What caused the non-productive time on AK-3 on 13 August 2016?", "exact");
  });
});

describe("questions about causes on the first screen and in the guide", () => {
  it("offers a cause question to try", async () => {
    const api = fakeApi(caused);
    render(<App api={api} />);
    await userEvent.setup().click(screen.getByRole("button", { name: CAUSE }));
    expect(api.ask).toHaveBeenCalledWith(CAUSE, "allow_fallback");
  });

  it("explains in the guide that possible factors are not findings", async () => {
    const api = fakeApi(caused);
    render(<App api={api} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "How it works" }));
    const guide = screen.getByRole("dialog", { name: "How it works" });
    expect(within(guide).getByText(/they are ideas to check, not findings/)).toBeInTheDocument();
    await user.click(within(guide).getByRole("button", { name: `Try: “${CAUSE}”` }));
    expect(api.ask).toHaveBeenCalledWith(CAUSE, "allow_fallback");
  });
});
