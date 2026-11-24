import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import health from "../../backend/fixtures/health.json";
import page from "../../backend/fixtures/page.json";
import endOfWell from "../../backend/fixtures/question_end_of_well.json";
import notFound from "../../backend/fixtures/question_not_found_exact.json";
import overTime from "../../backend/fixtures/question_over_time.json";
import wells from "../../backend/fixtures/wells.json";
import App from "./App";
import { ApiError, type Api } from "./api/client";
import type { AnswerOut, Health, PageOut, WellSummary } from "./api/types";

function fakeApi(answer: AnswerOut | Error): Api & { ask: ReturnType<typeof vi.fn>; feedback: ReturnType<typeof vi.fn>; page: ReturnType<typeof vi.fn> } {
  return {
    ask: vi.fn(async (question: string, mode: string) => {
      if (answer instanceof Error) throw answer;
      return { ...answer, question, mode } as AnswerOut;
    }),
    feedback: vi.fn(async () => {}),
    wells: async () => wells as WellSummary[],
    health: async () => health as Health,
    page: vi.fn(async () => page as PageOut),
  };
}

async function ask(text: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Ask about the reports"), text);
  await user.click(screen.getByRole("button", { name: "Ask" }));
  return user;
}

describe("the application", () => {
  it("starts with questions to try and says what is loaded", async () => {
    const api = fakeApi(overTime as AnswerOut);
    render(<App api={api} />);
    expect(await screen.findByText(/5 wells/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "How many hours of non-productive time did AK-3 have?" }));
    expect(api.ask).toHaveBeenCalledWith("How many hours of non-productive time did AK-3 have?", "allow_fallback");
    expect(await screen.findByRole("heading", { name: "115 hours" })).toBeInTheDocument();
  });

  it("shows a computed answer with the operations behind it, day by day", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    await ask("How many hours of non-productive time did AK-3 have?");
    expect(await screen.findByRole("heading", { name: "115 hours" })).toBeInTheDocument();
    expect(screen.getByText("Computed from 28 operations on 10 report days. No model wrote this number.")).toBeInTheDocument();
    const days = screen.getByRole("list", { name: "Report days" });
    expect(within(days).getAllByRole("listitem")).toHaveLength(10);
    expect(screen.getByRole("table", { name: "Operations" })).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Operations" })).getAllByRole("row")).toHaveLength(29);
  });

  it("shows a model's answer with the facts and passages it was given", async () => {
    render(<App api={fakeApi(endOfWell as AnswerOut)} />);
    await ask("What total depth did well AK-3 reach?");
    expect(await screen.findByRole("heading", { name: "1955 ft" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Checked facts" })).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(5);
  });

  it("opens the page a source is on", async () => {
    const api = fakeApi(endOfWell as AnswerOut);
    render(<App api={api} />);
    const user = await ask("What total depth did well AK-3 reach?");
    await user.click(await screen.findByRole("button", { name: /Source 1/ }));
    const cited = (endOfWell as AnswerOut).citations[0];
    expect(api.page).toHaveBeenCalledWith(cited.file_id, cited.page);
    expect(await screen.findByRole("heading", { name: /page 2/i })).toBeInTheDocument();
  });

  it("asks for graph answers only when the switch is on, and says what to do when there is none", async () => {
    const api = fakeApi(notFound as AnswerOut);
    render(<App api={api} />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText(/Graph answers only/));
    await ask("What total depth did well ZZ-9 reach?");
    expect(api.ask).toHaveBeenCalledWith("What total depth did well ZZ-9 reach?", "exact");
    expect(await screen.findByRole("heading", { name: "Not in the knowledge graph" })).toBeInTheDocument();
    expect(screen.getByText(/Turn off “Graph answers only”/)).toBeInTheDocument();
  });

  it("says what went wrong and keeps the question when the model is not running", async () => {
    render(<App api={fakeApi(new ApiError("The language model is not running. Start the model server, then ask again."))} />);
    await ask("What total depth did well AK-3 reach?");
    expect(await screen.findByRole("alert")).toHaveTextContent("The language model is not running");
    expect(screen.getByLabelText("Ask about the reports")).toHaveValue("What total depth did well AK-3 reach?");
  });

  it("shows the first sources of a long list and the rest on request", async () => {
    render(<App api={fakeApi(overTime as AnswerOut)} />);
    const user = await ask("How many hours of non-productive time did AK-3 have?");
    const total = (overTime as AnswerOut).citations.length;
    const sources = await screen.findByRole("list", { name: "Sources" });
    expect(within(sources).getAllByRole("listitem")).toHaveLength(4);
    await user.click(screen.getByRole("button", { name: `Show all ${total} sources` }));
    expect(within(sources).getAllByRole("listitem")).toHaveLength(total);
  });

  it("saves a wrong answer with the reader's comment", async () => {
    const api = fakeApi(overTime as AnswerOut);
    render(<App api={api} />);
    const user = await ask("How many hours of non-productive time did AK-3 have?");
    await user.click(await screen.findByRole("button", { name: "Wrong" }));
    await user.type(screen.getByLabelText("What should it say?"), "116 hours");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(api.feedback).toHaveBeenCalledWith((overTime as AnswerOut).id, "wrong", "116 hours");
    expect(await screen.findByText("Saved as wrong.")).toBeInTheDocument();
  });

  it("saves a right answer in one click", async () => {
    const api = fakeApi(overTime as AnswerOut);
    render(<App api={api} />);
    const user = await ask("How many hours of non-productive time did AK-3 have?");
    await user.click(await screen.findByRole("button", { name: "Right" }));
    expect(api.feedback).toHaveBeenCalledWith((overTime as AnswerOut).id, "right", "");
    expect(await screen.findByText("Saved as right.")).toBeInTheDocument();
  });

  it("does not send an empty question", async () => {
    const api = fakeApi(overTime as AnswerOut);
    render(<App api={api} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Ask" }));
    expect(api.ask).not.toHaveBeenCalled();
  });
});
