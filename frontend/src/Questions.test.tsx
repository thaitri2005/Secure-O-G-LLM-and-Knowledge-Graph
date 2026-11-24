import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Api } from "./api/client";
import { exampleApi } from "./api/examples";
import type { LoggedQuestion, QuestionPage } from "./api/types";
import { PAGE_SIZE } from "./components/Questions";

// The page for the team and the advisors: the questions people asked, read back, and saved as a question set.

type Fake = Api & {
  questions: ReturnType<typeof vi.fn>;
  questionCounts: ReturnType<typeof vi.fn>;
  question: ReturnType<typeof vi.fn>;
  exportQuestions: ReturnType<typeof vi.fn>;
  ask: ReturnType<typeof vi.fn>;
  feedback: ReturnType<typeof vi.fn>;
};

function fakeApi(): Fake {
  return {
    ...exampleApi,
    ask: vi.fn(exampleApi.ask),
    feedback: vi.fn(exampleApi.feedback),
    questions: vi.fn(exampleApi.questions),
    questionCounts: vi.fn(exampleApi.questionCounts),
    question: vi.fn(exampleApi.question),
    exportQuestions: vi.fn(exampleApi.exportQuestions),
  };
}

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  window.localStorage.setItem("drilling-reports.guide-seen", "1");
  window.history.replaceState(null, "", "/");
});

afterEach(() => vi.restoreAllMocks());

async function openPage(api: Api) {
  render(<App api={api} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("link", { name: "Questions people asked" }));
  await screen.findByRole("list", { name: "Questions" });
  return user;
}

describe("the questions people asked", () => {
  it("is linked from the top bar, and shows the counts and the list, newest first", async () => {
    const api = fakeApi();
    await openPage(api);
    expect(window.location.search).toBe("?view=questions");
    expect(screen.getByRole("heading", { name: "Questions people asked" })).toBeInTheDocument();
    const counts = screen.getByLabelText("Counts");
    expect(within(counts).getAllByRole("term").map((t) => `${t.textContent} ${t.nextElementSibling?.textContent}`)).toEqual([
      "Asked 3", "Answered 2", "Marked right 1", "Marked wrong 0", "Not marked 2",
    ]);
    const items = within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button");
    expect(items.map((item) => item.querySelector(".logq__question")?.textContent)).toEqual([
      "What mud weight was used on well ZZ-9?",
      "What caused the stuck pipe on AK-3 on 20 August 2016?",
      "How many hours of non-productive time did AK-3 have?",
    ]);
    expect(items[2]).toHaveTextContent("21 Nov 2026, 09:30 UTC · A total over a period of time");
    expect(items[2]).toHaveTextContent("115 hours");
    expect(items[2]).toHaveTextContent("Marked right");
    expect(items[2]).toHaveTextContent("2 comments");
    expect(items[0]).toHaveTextContent("Not in the verified data");
    expect(items[0]).toHaveTextContent("Not marked");
    expect(screen.getByText("Showing 1–3 of 3 questions")).toBeInTheDocument();
    // The question box of the main screen is not shown here: this page has its own search.
    expect(screen.queryByLabelText("Ask about the reports")).not.toBeVisible();
  });

  it("filters in plain words, and the counts follow the filters", async () => {
    const api = fakeApi();
    const user = await openPage(api);
    await user.selectOptions(screen.getByLabelText("How it was marked"), "Not marked");
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button")).toHaveLength(2));
    expect(api.questions).toHaveBeenLastCalledWith({ verdict: "none" }, PAGE_SIZE, 0);
    expect(api.questionCounts).toHaveBeenLastCalledWith({ verdict: "none" });
    await user.selectOptions(screen.getByLabelText("Kind of question"), "A question about what caused a problem");
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button")).toHaveLength(1));
    expect(api.questions).toHaveBeenLastCalledWith({ verdict: "none", kind: "cause" }, PAGE_SIZE, 0);
    await user.click(screen.getByRole("button", { name: "Clear the filters" }));
    await user.type(screen.getByLabelText("Words in the question"), "mud");
    await waitFor(() => expect(api.questions).toHaveBeenLastCalledWith({ q: "mud" }, PAGE_SIZE, 0));
    expect(within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button")).toHaveLength(1);
    await user.clear(screen.getByLabelText("Words in the question"));
    await user.type(screen.getByLabelText("Words in the question"), "nothing like this");
    expect(await screen.findByText(/No question matches these filters\./)).toBeInTheDocument();
  });

  it("filters by the days asked", async () => {
    const api = fakeApi();
    const user = await openPage(api);
    await user.type(screen.getByLabelText("Asked from"), "2026-11-22");
    await waitFor(() => expect(api.questions).toHaveBeenLastCalledWith({ date_from: "2026-11-22" }, PAGE_SIZE, 0));
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button")).toHaveLength(2));
  });

  it("pages through a long list", async () => {
    const api = fakeApi();
    const many = Array.from({ length: 45 }, (_, index) => ({
      id: `q${index}`, asked_at: "2026-11-21T09:30:00+00:00", question: `Question ${index}`,
      mode: "allow_fallback", kind: "lookup", report_type: "end_of_well", status: "answered", lanes: ["passages"], fallback: false,
      answered_from: "end_of_well", answer_text: "1955 ft", verdict: null, feedback: [],
    })) as LoggedQuestion[];
    api.questions.mockImplementation(async (_filters: unknown, limit: number, offset: number): Promise<QuestionPage> => (
      { total: many.length, limit, offset, questions: many.slice(offset, offset + limit) }
    ));
    const user = await openPage(api);
    expect(screen.getByText("Showing 1–20 of 45 questions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Newer" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Older" }));
    expect(await screen.findByText("Showing 21–40 of 45 questions")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Older" }));
    expect(await screen.findByText("Showing 41–45 of 45 questions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Older" })).toBeDisabled();
    expect(api.questions).toHaveBeenLastCalledWith({}, PAGE_SIZE, 40);
  });

  it("opens a question: what was asked, the answer with its label, and the marks and comments", async () => {
    const api = fakeApi();
    const user = await openPage(api);
    await user.click(within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button")[2]);
    const asked = await screen.findByRole("heading", { name: "How many hours of non-productive time did AK-3 have?" });
    expect(api.question).toHaveBeenCalledWith("fixture-log-2");
    expect(window.location.search).toBe("?view=questions&question=fixture-log-2");
    await waitFor(() => expect(asked).toHaveFocus());
    expect(screen.getByText("Calculated from the reports")).toBeInTheDocument();
    expect(screen.getByText("115 hours")).toBeInTheDocument();
    const marks = within(screen.getByRole("list", { name: "Marks" })).getAllByRole("listitem");
    expect(marks).toHaveLength(2);
    expect(marks[0]).toHaveTextContent("Marked wrong");
    expect(marks[0]).toHaveTextContent("Expected the well total of appendix 23");
    expect(marks[1]).toHaveTextContent("Marked right21 Nov 2026, 10:05 UTCMatches appendix 23 after checking");
    expect(screen.getByText("Technical details: 2 AI calls, 0.0 seconds.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to the list" }));
    expect(await screen.findByRole("list", { name: "Questions" })).toBeInTheDocument();
  });

  it("says plainly when nobody has marked an answer, and claims no check the log did not keep", async () => {
    const api = fakeApi();
    api.question.mockResolvedValueOnce({
      id: "q1", asked_at: "2026-11-20T08:15:00+00:00", question: "What total depth did well AK-3 reach?", mode: "exact",
      kind: "lookup", report_type: "end_of_well", status: "answered", lanes: ["well_facts", "passages"], fallback: false,
      answered_from: "end_of_well", answer_text: "1955 ft", verdict: null, feedback: [],
      record: { citations: ["gdr882_ak3_eowr#c0010"] },
    });
    window.history.replaceState(null, "", "/?view=questions&question=q1");
    render(<App api={api} />);
    expect(await screen.findByRole("heading", { name: "What total depth did well AK-3 reach?" })).toBeInTheDocument();
    expect(screen.getByText("Nobody has marked this answer yet.")).toBeInTheDocument();
    expect(screen.getByText("Written by AI")).toBeInTheDocument();
    expect(screen.getByText("Asked with “Verified data only” on")).toBeInTheDocument();
    expect(screen.getByText("From: AK-3 end-of-well report.")).toBeInTheDocument();
  });

  it("downloads the questions the filters select as a question set, and says what the file is for", async () => {
    const api = fakeApi();
    const made: Blob[] = [];
    const create = vi.fn((blob: Blob) => {
      made.push(blob);
      return "blob:questions";
    });
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() });
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const user = await openPage(api);
    expect(screen.getByText(/Once someone writes the right answers into it, it becomes a test the system can be run against\./)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("How it was marked"), "Not marked");
    await waitFor(() => expect(api.questions).toHaveBeenLastCalledWith({ verdict: "none" }, PAGE_SIZE, 0));
    await user.click(screen.getByRole("button", { name: "Download these as a question set" }));
    expect(api.exportQuestions).toHaveBeenCalledWith({ verdict: "none" });
    expect(await screen.findByText("Saved as collected_2026-11-24.json.")).toBeInTheDocument();
    expect(clicked).toHaveBeenCalledTimes(1);
    const file = JSON.parse(await made[0].text());
    expect(file.questions.map((q: { id: string }) => q.id)).toEqual(["fixture-log-3", "fixture-log-4"]);
  });

  it("only reads: nothing on it saves, changes or deletes", async () => {
    const api = fakeApi();
    const user = await openPage(api);
    await user.click(within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button")[2]);
    await screen.findByRole("heading", { name: "How many hours of non-productive time did AK-3 have?" });
    expect(screen.queryByRole("button", { name: /delete|remove|edit|save|mark/i })).not.toBeInTheDocument();
    expect(api.feedback).not.toHaveBeenCalled();
    expect(api.ask).not.toHaveBeenCalled();
  });

  it("works with the back button and from a copied link", async () => {
    window.history.replaceState(null, "", "/?view=questions&question=fixture-log-2");
    render(<App api={fakeApi()} />);
    expect(await screen.findByRole("heading", { name: "How many hours of non-productive time did AK-3 have?" })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Back to the list" }));
    expect(await screen.findByRole("list", { name: "Questions" })).toBeInTheDocument();
    window.history.back();
    expect(await screen.findByRole("heading", { name: "How many hours of non-productive time did AK-3 have?" })).toBeInTheDocument();
  });

  describe("a question that could not be answered", () => {
    const failed = {
      id: "failed-1", asked_at: "2026-11-24T08:00:00+00:00", question: "What caused the kick on AK-3?", mode: "allow_fallback",
      kind: null, report_type: null, status: "error", lanes: [], fallback: false, answered_from: null, answer_text: null,
      verdict: null, feedback: [],
    } as unknown as LoggedQuestion;

    function withFailed(error: string): Fake {
      const api = fakeApi();
      api.questions.mockImplementation(async (filters: { status?: string }, limit: number, offset: number): Promise<QuestionPage> => {
        const all = [failed, ...(await exampleApi.questions({}, 50, 0)).questions].filter((q) => !filters.status || q.status === filters.status);
        return { total: all.length, limit, offset, questions: all };
      });
      api.questionCounts.mockImplementation(async () => (
        { questions: 4, by_kind: {}, by_status: { answered: 2, not_found_in_graph: 1, error: 1 }, by_verdict: { right: 1, wrong: 0, none: 3 } }
      ));
      api.question.mockImplementation(async () => ({ ...failed, record: { error } }));
      return api;
    }

    it("is listed plainly, counted apart from the answered ones, and can be filtered for", async () => {
      const api = withFailed("Busy");
      const user = await openPage(api);
      const list = screen.getByRole("list", { name: "Questions" });
      expect(within(list).getAllByRole("button")[0]).toHaveTextContent("Could not be answered");
      const counts = screen.getByLabelText("Counts");
      expect(counts).toHaveTextContent("Asked4");
      expect(counts).toHaveTextContent("Answered2");
      expect(counts).toHaveTextContent("Could not be answered1");
      await user.selectOptions(screen.getByLabelText("How it ended"), "Could not be answered");
      await waitFor(() => expect(api.questions).toHaveBeenLastCalledWith({ status: "error" }, PAGE_SIZE, 0));
      await waitFor(() => expect(within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button")).toHaveLength(1));
    });

    it("says why when opened, without the system's own name for what went wrong", async () => {
      const user = await openPage(withFailed("Busy"));
      await user.click(within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button")[0]);
      expect(await screen.findByText("Could not be answered: the system was busy")).toBeInTheDocument();
      expect(screen.getByText("Not answered")).toBeInTheDocument();
      expect(document.body).not.toHaveTextContent(/Busy\b|ReadTimeout/);
    });

    it("says the answering service did not respond for a time-out", async () => {
      const user = await openPage(withFailed("ReadTimeout"));
      await user.click(within(screen.getByRole("list", { name: "Questions" })).getAllByRole("button")[0]);
      expect(await screen.findByText("Could not be answered: the answering service did not respond")).toBeInTheDocument();
      expect(document.body).not.toHaveTextContent("ReadTimeout");
    });

    it("leaves the counts as they were when nothing failed", async () => {
      await openPage(fakeApi());
      expect(screen.getByLabelText("Counts")).not.toHaveTextContent("Could not be answered");
    });
  });
});
